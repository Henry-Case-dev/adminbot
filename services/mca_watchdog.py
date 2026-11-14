"""Раунд 10.27 (MCA Wave 0 — остаток, `mca-17a-observability-core`) —
heartbeat/watchdog/takeover/recovery §27.5.

* heartbeat ≠ progress: `heartbeat_at` — живость владельца; `progress_at` —
  фактически выполненная работа; `deadline_at` — абсолютный срок; порог
  progress-stall — по типу стадии LLM/видео/архив (жизненная длительная
  транскрибация не объявляется упавшей по общему таймеру).
* Watchdog проверяет durable state **периодически** (background asyncio-задача)
  и **на старте**; при stale lease — подозрение → проверка владельца/состояния
  → `interrupted`/retry по безопасной политике через `TaskJobStore.takeover_stale`
  (fencing/generation бампаются).
* S5A (SMART-CORRECTIVE-01 §9): успешный `takeover_recovered` эмитится только
  после ПОДТВЕРЖДЁННОГО перехода (queued+retry); обнаружение, попытка, отказ и
  отсутствие изменений различимы. Активные инциденты сверяются с фактическим
  терминальным состоянием связанных job; закрытый инцидент не переоткрывается
  тем же evidence. Отказ incident-service наблюдаем (log + счётчики) без
  рекурсивного инцидента.
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

# S5A/W-10 (partial): наблюдаемые исходы регистрации инцидентов. S5D
# расширит это WARN-событием; здесь — честные счётчики + log.warning, без
# рекурсивного создания инцидента из собственной ошибки (AC-24).
_INCIDENT_OUTCOME_KEYS = ("created", "updated", "reopened", "failed",
                          "disabled")
_incident_outcome_totals = {key: 0 for key in _INCIDENT_OUTCOME_KEYS}
# S5A/W-02: наблюдаемые исходы takeover (discovered/attempted/recovered/
# failed/no_change); per-job записи живут в результате sweep.
_TAKEOVER_OUTCOME_KEYS = ("recovered", "failed", "no_change")
_takeover_outcome_totals = {key: 0 for key in _TAKEOVER_OUTCOME_KEYS}


def incident_outcome_totals() -> dict:
    """Накопленные исходы регистрации инцидентов (S5A/W-10, S5D-совместимо)."""
    return dict(_incident_outcome_totals)


def takeover_outcome_totals() -> dict:
    """Накопленные исходы takeover (S5A/W-02)."""
    return dict(_takeover_outcome_totals)


def _bump_incident_outcome(outcome: str) -> str:
    key = outcome if outcome in _INCIDENT_OUTCOME_KEYS else "failed"
    _incident_outcome_totals[key] += 1
    return key


def _bump_takeover_outcome(outcome: str) -> str:
    key = outcome if outcome in _TAKEOVER_OUTCOME_KEYS else "failed"
    _takeover_outcome_totals[key] += 1
    return key


def heartbeat_interval_seconds() -> int:
    return mca_gates.job_heartbeat_seconds()


def stale_seconds() -> int:
    return mca_gates.job_stale_seconds()


async def _emit(event_name: str, reason_code: str | None, *,
                outcome: str = "success", level: str = "INFO",
                **fields) -> None:
    """Единая эмиссия watchdog-события с ЧЕСТНЫМ outcome/level (S5A/W-02)."""
    try:
        from services import mca_trace as mt
        mt.emit_stage(event_name, outcome=outcome, level=level,
                      component="watchdog", reason_code=reason_code, **fields)
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

    S5A/W-02: `takeover_recovered` эмитится только когда допустимый переход
    действительно произошёл (`recovered`); отказ/отсутствие store — отдельные
    `failed`/`skipped` с честным level. Исходы разделены:
    `discovered|attempted|recovered|failed|no_change` (per-job в
    `result["takeover"]["records"]`). S5C добавит per-job identity в событие.

    S5A/W-05: перед новыми наблюдениями активные watchdog-инциденты
    сверяются с фактическим состоянием связанных job; закрытие — только
    после терминального итога всех job (`reconcile_linked_incidents`).

    S5A/W-10: отказ регистрации инцидента наблюдаем (log.warning + счётчики
    `created|updated|reopened|failed|disabled`), без рекурсии.

    Возвращает `{recovered, stale, progress_stalled, incidents, takeover,
    incident_outcomes, incident_reconcile, ran}`. Fail-open: ошибки не
    бросают наружу."""
    result = {"recovered": [], "stale": [], "progress_stalled": [],
              "incidents": 0, "ran": False,
              "takeover": {"discovered": [], "attempted": [],
                           "recovered": [], "failed": [], "no_change": [],
                           "records": []},
              "incident_outcomes": {key: 0 for key in _INCIDENT_OUTCOME_KEYS},
              "incident_reconcile": {"checked": 0, "resolved": 0,
                                     "pending": 0, "inconclusive": 0,
                                     "failed": 0}}
    if db is None or not mca_gates.heartbeat_watchdog_enabled():
        return result
    result["ran"] = True
    ts = int(now if now is not None else time.time())
    # W-05: сверка ДО новых наблюдений — инцидент, созданный этим проходом,
    # закрывается только следующим sweep'ом после реального терминала job.
    if track_incidents:
        try:
            from services import mca_incidents as inc
            result["incident_reconcile"] = \
                await inc.reconcile_linked_incidents(
                    db, job_store, process_id="watchdog.jobs")
        except Exception:
            logger.warning("[mca_watchdog] incident reconcile failed",
                           exc_info=True)
    stale = await stale_jobs(db, now=ts)
    discovered = [r.get("job_id") for r in stale]
    result["stale"] = discovered
    result["takeover"]["discovered"] = list(discovered)
    if stale:
        if job_store is None:
            # S5A/W-02: без store recovery не вызывался — никакого success.
            result["takeover"]["no_change"] = list(discovered)
            for _jid in discovered:
                _bump_takeover_outcome("no_change")
            await _emit("WATCHDOG_TAKEOVER", "worker_lost", stage="takeover",
                        outcome="skipped", level="WARN")
        else:
            result["takeover"]["attempted"] = list(discovered)
            try:
                records = await job_store.takeover_stale(
                    stale_after_seconds=stale_seconds(),
                    retry_delay_seconds=heartbeat_interval_seconds(),
                    dangerous_owners=DANGEROUS_JOB_OWNERS)
            except Exception:
                logger.warning("[mca_watchdog] takeover failed", exc_info=True)
                records = [{"job_id": jid, "outcome": "failed",
                            "reason": "takeover_error", "action": "error"}
                           for jid in discovered]
            # Job мог обновить heartbeat между обнаружением и takeover —
            # честно фиксируем no_change, а не теряем его из результата.
            seen = {str(r.get("job_id")) for r in records}
            for jid in discovered:
                if str(jid) not in seen:
                    records.append({"job_id": jid, "outcome": "no_change",
                                    "reason": "state_changed",
                                    "action": "state_changed"})
            result["takeover"]["records"] = records
            for record in records:
                jid = str(record.get("job_id") or "")
                if not jid:
                    continue
                key = _bump_takeover_outcome(str(record.get("outcome")))
                result["takeover"][key].append(jid)
            result["recovered"] = list(result["takeover"]["recovered"])
            # Одно событие на класс исхода за проход (S5C добавит per-job
            # доказательства через разрешённые additive-поля).
            if result["takeover"]["recovered"]:
                await _emit("WATCHDOG_TAKEOVER", "takeover_recovered",
                            stage="takeover", outcome="success")
            if result["takeover"]["failed"]:
                await _emit("WATCHDOG_TAKEOVER", "worker_lost",
                            stage="takeover", outcome="failed", level="ERROR")
            if result["takeover"]["no_change"]:
                await _emit("WATCHDOG_TAKEOVER", "worker_lost",
                            stage="takeover", outcome="skipped", level="WARN")
    # ASAP 8 v6 C03A: recovery-контур styled cover (restart mid-style /
    # bounded style retry с сохранённой Base). Неблокирующий kick (background
    # task в cover_style_jobs), fail-open — не влияет на sweep-контракт.
    try:
        from services import cover_style_jobs as _csj
        result["cover_style_recovery_kicked"] = \
            bool(_csj.kick_cover_style_recovery(db))
    except Exception:
        logger.debug("[mca_watchdog] cover style recovery hook failed",
                     exc_info=True)
    await _emit("WATCHDOG_SWEEP", None, stage="sweep")
    if track_incidents:
        for row in stale:
            outcome = await _track_incident(
                db, row, reason_code="worker_lost", stage="takeover")
            key = _bump_incident_outcome(outcome)
            result["incident_outcomes"][key] += 1
            if key in ("created", "reopened"):
                result["incidents"] += 1
    if detect_progress_stall:
        stalled = await progress_stalled_jobs(db, now=ts)
        result["progress_stalled"] = [r.get("job_id") for r in stalled]
        for row in stalled:
            if track_incidents:
                outcome = await _track_incident(
                    db, row, reason_code="progress_stall", stage="progress")
                key = _bump_incident_outcome(outcome)
                result["incident_outcomes"][key] += 1
                if key in ("created", "reopened"):
                    result["incidents"] += 1
    return result


async def _track_incident(db, row: dict, *, reason_code: str,
                          stage: str) -> str:
    """Зарегистрировать инцидент и вернуть честный исход регистрации.

    S5A/W-10: ошибка не подавляется — log.warning + статус `failed`
    (вызывающий считает); `open_or_update` повторно НЕ вызывается и инцидент
    из собственной ошибки не создаётся (AC-24)."""
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
    except Exception:
        logger.warning("[mca_watchdog] incident registration failed | "
                       "job_id=%s | stage=%s", row.get("job_id"), stage,
                       exc_info=True)
        return "failed"
    status = str((res or {}).get("status") or "")
    if status in _INCIDENT_OUTCOME_KEYS:
        return status
    if res is None:
        return "disabled"
    return "failed"


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
    error_code = str(row.get("error_code") or "")
    # F-S5A-01: `delivery_unknown` — не «потеря владельца», а запрет слепого
    # повтора side effect/доставки. Durable-маркер сохраняется takeover'ом;
    # здесь он блокирует resume НЕЗАВИСИМО от наличия checkpoint: строка не
    # переводится в queued/running до сверки по operation ID.
    if reason == "delivery_unknown" or error_code == "delivery_unknown":
        result["status"] = "reconcile_required"
        result["reason"] = "delivery_unknown"
        await _emit("RECOVERY", "delivery_unknown", stage="reconcile")
        return result
    owner = str(row.get("owner") or "")
    if checkpoint is None and owner in DANGEROUS_JOB_OWNERS:
        # Нет обязательного durable checkpoint → не повторяем вслепую.
        try:
            await job_store.finish(job_id, status="interrupted",
                                   reason_code="checkpoint_missing",
                                   recovery=True)
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
        # Явный recovery-путь: возобновление припаркованной задачи, а не
        # терминальная запись живого владельца (S5A/W-07).
        await job_store.finish(job_id, status="queued",
                               reason_code="recovery_from_checkpoint",
                               recovery=True)
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
