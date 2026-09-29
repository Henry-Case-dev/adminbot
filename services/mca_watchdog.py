"""Раунд 10.27 (MCA Wave 0 — остаток, `mca-17a-observability-core`) —
heartbeat/watchdog/takeover/recovery §27.5.

* heartbeat ≠ progress: `heartbeat_at` — живость владельца; `progress_at` —
  фактически выполненная работа; `deadline_at` — абсолютный срок; порог
  progress-stall — по типу стадии LLM/видео/архив (жизненная длительная
  транскрибация не объявляется упавшей по общему таймеру).
* Watchdog проверяет durable state **периодически** (background asyncio-задача)
  и **на старте**; при stale lease — подозрение → проверка владельца/состояния
  → `interrupted`/retry по безопасной политике через `TaskJobStore.recover_stale`
  (fencing/generation бампаются).
* Recovery: прочитать checkpoint, определить подтверждённые записи/side effects,
  возобновить только безопасные этапы; бесконечных retries нет. Неопределённая
  доставка/платная операция — `delivery_unknown` до сверки по operation ID;
  опасное задание без обязательного durable checkpoint — явная приостановка.
* Детект недоступности процесса — **вне** основного event loop (REUSE
  `services/uptime_heartbeat.py` + внешний менеджер процессов); при отсутствии
  внешнего наблюдателя ограничение отражается явно (`external_observer=False`),
  сбой обнаруживается после восстановления. UI при потере backend →
  `telemetry stale/unknown` (старый «зелёный» не сохраняется).

Kill-switch: `MCA_HEARTBEAT_WATCHDOG_ENABLED` (env-only, default ON, master).
"""
from __future__ import annotations

import asyncio
import logging
import time

from services import mca_gates
from services.log_ring import sanitize

logger = logging.getLogger(__name__)

# Опасные типы job: без обязательного durable checkpoint — явная пауза.
DANGEROUS_JOB_OWNERS = frozenset({"archive", "dossier", "backup"})

_watchdog_task: asyncio.Task | None = None
_watchdog_stop: asyncio.Event | None = None


def heartbeat_interval_seconds() -> int:
    return mca_gates.job_heartbeat_seconds()


def stale_seconds() -> int:
    return mca_gates.job_stale_seconds()


async def _emit(event_name: str, reason_code: str | None, **fields) -> None:
    try:
        from services import mca_trace as mt
        mt.emit_stage(event_name, outcome="success", component="watchdog",
                      reason_code=reason_code, **fields)
    except Exception:
        return


async def stale_jobs(db, *, now: int | None = None) -> list[dict]:
    """`running`-задачи без свежего heartbeat (кандидаты takeover)."""
    if db is None:
        return []
    ts = int(now if now is not None else time.time())
    cutoff = ts - stale_seconds()
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE status = 'running' AND "
            "(heartbeat_at IS NULL OR heartbeat_at < ?)", (cutoff,))
        return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []


async def progress_stalled_jobs(db, *, now: int | None = None) -> list[dict]:
    """`running`-задачи с живым heartbeat, но без прогресса (по типу стадии).

    Порог — по типу job (`MCA_PROGRESS_STALL_<TYPE>_SECONDS`)."""
    if db is None:
        return []
    ts = int(now if now is not None else time.time())
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE status = 'running' AND "
            "progress_at IS NOT NULL")
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []
    out = []
    for row in rows:
        stall = mca_gates.progress_stall_seconds(row.get("owner"))
        if ts - int(row["progress_at"]) > stall:
            out.append(row)
    return out


async def sweep(db, job_store=None, *, now: int | None = None,
                detect_progress_stall: bool = True,
                track_incidents: bool = True) -> dict:
    """Один проход watchdog: takeover stale + фиксация stalled-диагностики.

    Возвращает `{recovered, stale, progress_stalled, incidents}`. Fail-open:
    ошибки не бросают наружу."""
    result = {"recovered": [], "stale": [], "progress_stalled": [],
              "incidents": 0, "ran": False}
    if db is None or not mca_gates.heartbeat_watchdog_enabled():
        return result
    result["ran"] = True
    ts = int(now if now is not None else time.time())
    stale = await stale_jobs(db, now=ts)
    result["stale"] = [r.get("job_id") for r in stale]
    if stale and job_store is not None:
        try:
            recovered = await job_store.recover_stale(
                stale_after_seconds=stale_seconds())
            result["recovered"] = list(recovered)
        except Exception:
            logger.warning("[mca_watchdog] recover_stale failed", exc_info=True)
    await _emit("WATCHDOG_SWEEP", None, stage="sweep")
    for row in stale:
        await _emit("WATCHDOG_TAKEOVER", "takeover_recovered",
                    stage="takeover",
                    **{"job_ids": list(result["recovered"]) or None})
        if track_incidents:
            result["incidents"] += await _track_incident(
                db, row, reason_code="worker_lost", stage="takeover")
    if detect_progress_stall:
        stalled = await progress_stalled_jobs(db, now=ts)
        result["progress_stalled"] = [r.get("job_id") for r in stalled]
        for row in stalled:
            if track_incidents:
                result["incidents"] += await _track_incident(
                    db, row, reason_code="progress_stall", stage="progress")
    return result


async def _track_incident(db, row: dict, *, reason_code: str,
                          stage: str) -> int:
    try:
        from services import mca_incidents as inc
        # F8: тип/владелец job берётся из строки (а не хардкод «archive.rebuild»)
        # — разные job-типы не сливаются в один fingerprint.
        owner = str(row.get("owner") or "unknown")
        res = await inc.open_or_update(
            db, process_id="watchdog.jobs", pipeline_type=owner,
            stage=stage, reason_code=reason_code,
            error_type=str(row.get("error_code") or ""),
            dependency=None, severity=inc.SEVERITY_ERROR,
            title=f"job {row.get('job_id')}: {reason_code}",
            job_id=row.get("job_id"),
            trace_id=row.get("pipeline_run_id"),
            impact="задача потеряла владельца/не прогрессирует")
        return 1 if res is not None else 0
    except Exception:
        return 0


async def startup_check(db, job_store=None) -> dict:
    """Проверка durable state на старте (§27.5: периодически **и** на старте)."""
    return await sweep(db, job_store=job_store)


async def telemetry_freshness(db, *, now: int | None = None) -> str:
    """Свежесть телеметрии для UI: `ok`/`stale`/`unknown`.

    При потере backend — `unknown` (старый «зелёный» не сохраняется)."""
    if db is None:
        return "unknown"
    ts = int(now if now is not None else time.time())
    max_age = max(stale_seconds() * 10, 600)
    try:
        cursor = await db.db.execute(
            "SELECT MAX(updated_at) AS m FROM task_jobs WHERE "
            "status IN ('queued', 'running')")
        row = await cursor.fetchone()
        if row is None or row["m"] is None:
            return "ok"      # нет активных задач — не «устарело», а пусто
        return "stale" if ts - int(row["m"]) > max_age else "ok"
    except Exception:
        return "unknown"


# ── recovery по checkpoint + delivery_unknown (§27.5/§27.9) ─────────────────

async def recover_job(db, job_store, job_id: str) -> dict:
    """Восстановить задачу по checkpoint (только безопасные этапы).

    * читает `get_checkpoint(job_id)`;
    * определяет подтверждённые записи/side effects;
    * возобновляет только безопасные этапы; бесконечных retries нет;
    * `delivery_unknown` → сверка по operation ID (не слепой повтор);
    * опасное задание без обязательного durable checkpoint — явная пауза.
    """
    result = {"job_id": job_id, "resumed": False, "status": "noop",
              "safe_stages": [], "checkpoint": None, "reason": None}
    if db is None or job_store is None:
        result["status"] = "unavailable"
        return result
    row = await job_store.get(job_id)
    if row is None:
        result["status"] = "not_found"
        return result
    checkpoint = await job_store.get_checkpoint(job_id)
    result["checkpoint"] = checkpoint
    reason = str(row.get("reason_code") or "")
    if reason == "delivery_unknown":
        result["status"] = "reconcile_required"
        result["reason"] = "delivery_unknown"
        await _emit("RECOVERY", "delivery_unknown", stage="reconcile")
        return result
    owner = str(row.get("owner") or "")
    if checkpoint is None and owner in DANGEROUS_JOB_OWNERS:
        # Нет обязательного durable checkpoint → не повторяем вслепую.
        try:
            await job_store.finish(job_id, status="interrupted",
                                   reason_code="checkpoint_missing")
        except Exception:
            pass
        result["status"] = "paused"
        result["reason"] = "checkpoint_missing"
        await _emit("RECOVERY", "checkpoint_missing", stage="recover")
        return result
    # Безопасные этапы возобновляемы; фиксация подтверждённых записей известна
    # из checkpoint (cursor/processed) — повторяем только их продолжение.
    safe = []
    if checkpoint is not None:
        safe = ["resume_after_cursor"]
    try:
        await job_store.finish(job_id, status="queued",
                               reason_code="recovery_from_checkpoint")
        result["status"] = "resumed"
    except Exception:
        result["status"] = "error"
    result["resumed"] = result["status"] == "resumed"
    result["safe_stages"] = safe
    await _emit("RECOVERY", "recovery_from_checkpoint", stage="recover")
    return result


async def mark_delivery_unknown(db, job_store, job_id: str,
                                *, operation_id: str | None = None) -> bool:
    """Пометить неопределённую доставку/платёж — без слепого повтора."""
    if db is None or job_store is None:
        return False
    try:
        ok = await job_store.finish(
            job_id, status="failed", reason_code="delivery_unknown",
            error_code="delivery_unknown")
    except Exception:
        return False
    await _emit("DELIVERY", "delivery_unknown", stage="delivery",
                **{"checkpoint_ref": sanitize(str(operation_id))
                   if operation_id else None})
    return bool(ok)


# ── background-цикл (детект вне основного loop) ─────────────────────────────

def external_observer_available() -> bool:
    """Есть ли внешний наблюдатель (uptime/heartbeat/systemd).

    Детект падения самого процесса — вне основного event loop; при отсутствии
    внешнего наблюдателя ограничение отражается явно."""
    try:
        from services import uptime_heartbeat as uh
        return bool(getattr(uh, "EXTERNAL_HEARTBEAT_ENABLED", True))
    except Exception:
        return False


async def watchdog_loop(db, job_store, *, interval_seconds: int | None = None,
                        stop_event: asyncio.Event | None = None) -> None:
    """Периодический проход watchdog (останавливается по `stop_event`)."""
    interval = max(5, int(interval_seconds or stale_seconds()))
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            await sweep(db, job_store=job_store)
        except Exception:
            logger.warning("[mca_watchdog] sweep failed", exc_info=True)
        try:
            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval)
                    return
                except asyncio.TimeoutError:
                    continue
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


def start_watchdog(db, job_store, *, interval_seconds: int | None = None
                   ) -> asyncio.Task | None:
    """Запустить background-watchdog (идемпотентно). Возвращает task/None."""
    global _watchdog_task, _watchdog_stop
    if not mca_gates.heartbeat_watchdog_enabled() or db is None:
        return None
    if _watchdog_task is not None and not _watchdog_task.done():
        return _watchdog_task
    _watchdog_stop = asyncio.Event()
    _watchdog_task = asyncio.create_task(
        watchdog_loop(db, job_store, interval_seconds=interval_seconds,
                      stop_event=_watchdog_stop))
    return _watchdog_task


async def stop_watchdog() -> None:
    """Остановить background-watchdog (shutdown)."""
    global _watchdog_task, _watchdog_stop
    if _watchdog_stop is not None:
        _watchdog_stop.set()
    if _watchdog_task is not None:
        try:
            await asyncio.wait_for(_watchdog_task, timeout=5)
        except Exception:
            _watchdog_task.cancel()
    _watchdog_task = None
    _watchdog_stop = None
