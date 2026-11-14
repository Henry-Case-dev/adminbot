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
* S5B (W-04/W-06/W-08/W-09): снятие lease ограничивается owner/kind (каждый
  watchdog восстанавливает только свои задачи); `MCA_JOB_HEARTBEAT_SECONDS`
  реально используется производителями; контракт `kind → progress|heartbeat|
  deadline` определяет порог «нет прогресса»; `progress_at IS NULL` больше не
  делает running-job невидимой; истёкший `deadline_at` — законный повод
  takeover у running-задач; queued-задачи только классифицируются
  (scheduled retry / ожидание срока / владелец очереди / зависание) и никогда
  не забираются автоматически.
* S5C (W-01/W-11): `WATCHDOG_TAKEOVER` эмитится по одному событию на реально
  затронутую задачу (job_id/owner/kind через разрешённые additive-поля), без
  агрегата, повторяемого на каждой строке stale batch; fingerprint инцидента
  включает `kind` и `job_id`, исторические строки не переписываются.
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


def _progress_age(row: dict, ts: int) -> int:
    """Возраст подтверждённого прогресса (S5B/W-08).

    `progress_at IS NULL` больше не исключает running-job из диагностики:
    baseline — момент постановки задачи (`created_at`), т.к. `mark_running`
    ставит `progress_at` для kind'ов с контрактом `progress`."""
    for key in ("progress_at", "created_at"):
        try:
            value = row.get(key)
            if value is not None:
                return max(0, ts - int(value))
        except (TypeError, ValueError):
            continue
    return 0


async def progress_stalled_jobs(db, *, now: int | None = None) -> list[dict]:
    """`running`-задачи без прогресса ПО КОНТРАКТУ ИХ ТИПА (S5B/W-08).

    Порог берётся из `mca_gates.job_progress_stall_seconds(kind, owner)`:
    карта `kind → llm/video/archive/default` вместо прежнего owner-совпадения
    с типами стадий. Задачи с контрактом `heartbeat` (долгие внешние вызовы)
    и `deadline` (TTL/абсолютный срок) в progress-корзину не попадают — их
    видимость обеспечивают heartbeat/overdue-корзины (`running_contract_jobs`
    и `overdue_jobs`), поэтому они не «невидимы», но и не объявляются
    зависшими по чужому таймеру."""
    if db is None:
        return []
    ts = int(now if now is not None else time.time())
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE status = 'running'")
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []
    out = []
    for row in rows:
        if not mca_gates.job_progress_required(row.get("kind"),
                                               row.get("owner")):
            continue
        stall = mca_gates.job_progress_stall_seconds(row.get("kind"),
                                                     row.get("owner"))
        if _progress_age(row, ts) > stall:
            out.append(row)
    return out


async def running_contract_jobs(db, *, now: int | None = None) -> dict:
    """Видимость running-job'ов БЕЗ обязательного прогресса (S5B/W-08).

    `heartbeat`-задачи наблюдаемы по возрасту heartbeat, `deadline`-задачи —
    по оставшемуся сроку. Их не надо объявлять stalled по progress-таймеру,
    но и терять из диагностики нельзя (прежний дефект: `progress_at IS NULL`
    ⇒ задача невидима)."""
    result = {"heartbeat_only": [], "deadline_bounded": []}
    if db is None:
        return result
    ts = int(now if now is not None else time.time())
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE status = 'running'")
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return result
    for row in rows:
        mode = mca_gates.job_progress_mode(row.get("kind"), row.get("owner"))
        item = {"job_id": row.get("job_id"), "owner": row.get("owner"),
                "kind": row.get("kind"), "mode": mode,
                "heartbeat_age": _age_of(row.get("heartbeat_at"), ts),
                "progress_age": _progress_age(row, ts),
                "deadline_in": _deadline_in(row.get("deadline_at"), ts)}
        if mode == mca_gates.JOB_MODE_HEARTBEAT:
            result["heartbeat_only"].append(item)
        elif mode == mca_gates.JOB_MODE_DEADLINE:
            result["deadline_bounded"].append(item)
    return result


def _age_of(value, ts: int) -> int | None:
    try:
        return None if value is None else max(0, ts - int(value))
    except (TypeError, ValueError):
        return None


def _deadline_in(value, ts: int) -> int | None:
    try:
        return None if value is None else int(value) - ts
    except (TypeError, ValueError):
        return None


async def overdue_jobs(db, *, now: int | None = None,
                       store=None) -> dict:
    """Задачи с истёкшим `deadline_at` (S5B/W-08/W-09).

    Running-overdue — законный повод takeover (решает вызывающий,
    `takeover_stale(include_overdue=True)`); queued-overdue — только
    диагностика: takeover queued запрещён архитектурным контрактом.
    При наличии store используется его существующий `overdue()` — второго
    чтения того же состояния не вводится."""
    result = {"running": [], "queued": []}
    if db is None:
        return result
    ts = int(now if now is not None else time.time())
    try:
        if store is not None:
            rows = [dict(r) for r in await store.overdue(now=ts)]
        else:
            cursor = await db.db.execute(
                "SELECT * FROM task_jobs WHERE status IN ('queued', "
                "'running') AND deadline_at IS NOT NULL AND deadline_at < ? "
                "ORDER BY deadline_at", (ts,))
            rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return result
    for row in rows:
        key = "running" if str(row.get("status")) == "running" else "queued"
        result[key].append(row)
    return result


def classify_queued_jobs(rows, *, now: int | None = None) -> dict:
    """Диагностическая классификация queued-задач (S5B/W-09) — БЕЗ takeover.

    Корзины:
      * `scheduled_retry` — `next_retry_at > now` (легальный bounded-retry);
      * `deadline_pending` — `deadline_at > now` (TTL/внешний срок ещё не
        истёк; ожидание зависимости/окна доставки);
      * `overdue` — `deadline_at <= now` (срок истёк — диагностика);
      * `owner_managed` — у типа задачи есть собственный claim/retry-цикл
        владельца (vision/exploration/cover/memory/meme/media);
      * `hang` — ни срока, ни владельца-цикла, возраст больше порога типа:
        настоящий «queued без исполнителя» (диагностический инцидент);
      * `normal_wait` — молодой queued без признаков зависания.
    """
    ts = int(now if now is not None else time.time())
    out = {"scheduled_retry": [], "deadline_pending": [], "overdue": [],
           "owner_managed": [], "hang": [], "normal_wait": []}
    for row in rows or ():
        item = {"job_id": row.get("job_id"), "owner": row.get("owner"),
                "kind": row.get("kind"),
                "attempt": int(row.get("attempt") or 0),
                "age": _age_of(row.get("updated_at") or row.get("created_at"),
                               ts),
                "next_retry_in": _deadline_in(row.get("next_retry_at"), ts),
                "deadline_in": _deadline_in(row.get("deadline_at"), ts)}
        if item["next_retry_in"] is not None and item["next_retry_in"] > 0:
            out["scheduled_retry"].append(item)
            continue
        if item["deadline_in"] is not None:
            if item["deadline_in"] > 0:
                out["deadline_pending"].append(item)
            else:
                out["overdue"].append(item)
            continue
        if mca_gates.job_queued_owner_managed(row.get("kind"),
                                              row.get("owner")):
            out["owner_managed"].append(item)
            continue
        hang_after = mca_gates.job_queued_hang_seconds(row.get("kind"),
                                                       row.get("owner"))
        if (item["age"] or 0) > hang_after:
            out["hang"].append(item)
        else:
            out["normal_wait"].append(item)
    return out


async def queued_jobs(db) -> list[dict]:
    """Все `queued`-строки (для диагностической классификации W-09)."""
    if db is None:
        return []
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE status = 'queued' "
            "ORDER BY created_at")
        return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []


def _merge_takeover_records(discovered_rows: dict, records) -> list[dict]:
    """Одна честная запись на РЕАЛЬНО затронутую задачу (S5C/W-01).

    `takeover_stale` уже возвращает per-job записи; для задач, изменившихся
    между обнаружением и takeover, добавляется `no_change/state_changed`.
    Идентичность (owner/kind/status_before/attempt/fencing) добирается из
    обнаруженной durable-строки, если store её не вернул (ошибка/путь без
    store). Дубли job_id не создаются."""
    merged: list[dict] = []
    seen: set[str] = set()
    for record in records or ():
        if not isinstance(record, dict):
            continue
        jid = str(record.get("job_id") or "")
        if not jid or jid in seen:
            continue
        seen.add(jid)
        row = discovered_rows.get(jid) or {}
        item = dict(record)
        for key in ("owner", "kind", "status_before"):
            if item.get(key) in (None, "") and row.get(key) is not None:
                item[key] = row.get(key)
        if item.get("attempt") is None:
            item["attempt"] = row.get("attempt")
        if item.get("fencing_token") is None:
            item["fencing_token"] = row.get("fencing_token")
        merged.append(item)
    for jid, row in discovered_rows.items():
        if jid in seen:
            continue
        merged.append({"job_id": jid, "outcome": "no_change",
                       "reason": "state_changed", "action": "state_changed",
                       "owner": row.get("owner"), "kind": row.get("kind"),
                       "status_before": row.get("status"),
                       "attempt": row.get("attempt"),
                       "fencing_token": row.get("fencing_token")})
    return merged


async def _emit_takeover_record(record: dict) -> None:
    """Per-job `WATCHDOG_TAKEOVER` с честным исходом (S5C/W-01).

    Имя события, §17.1 `outcome` и `reason_code`-словарь сохранены; identity
    передаётся ТОЛЬКО разрешёнными additive-полями `mca_events`:
    `job_id`/`entity_ids`/`pipeline_type` (owner)/`status` (канонический исход
    `recovered|failed|no_change`)/`attempt`; kind/action/previous status/
    fencing — в JSON-поле `error_json` (отдельной колонки kind в `mca_events`
    нет, DDL в S5C запрещён). Повторной эмиссии одного и того же агрегата на
    каждую строку stale batch нет: каждая запись уникальна своим job_id."""
    jid = str(record.get("job_id") or "")
    if not jid:
        return
    outcome = str(record.get("outcome") or "no_change")
    if outcome == "recovered":
        event_outcome, reason_code, level = ("success", "takeover_recovered",
                                             "INFO")
    elif outcome == "no_change":
        event_outcome, reason_code, level = ("skipped", "worker_lost", "WARN")
    else:
        # `failed` и любой неожиданный исход не выдаются за успех/skip.
        outcome = "failed"
        event_outcome, reason_code, level = ("failed", "worker_lost", "ERROR")
    await _emit("WATCHDOG_TAKEOVER", reason_code, stage="takeover",
                outcome=event_outcome, level=level,
                job_id=jid, entity_ids=[jid],
                pipeline_type=str(record.get("owner") or "") or None,
                status=outcome,
                attempt=int(record.get("attempt") or 0),
                error_json={"kind": record.get("kind"),
                            "reason": record.get("reason"),
                            "action": record.get("action"),
                            "status_before": record.get("status_before"),
                            "fencing_token": record.get("fencing_token")})


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
    incident_outcomes, incident_reconcile, queued, overdue,
    running_contract, ran}`. Fail-open: ошибки не бросают наружу."""
    result = {"recovered": [], "stale": [], "progress_stalled": [],
              "incidents": 0, "ran": False,
              "takeover": {"discovered": [], "attempted": [],
                           "recovered": [], "failed": [], "no_change": [],
                           "records": []},
              "incident_outcomes": {key: 0 for key in _INCIDENT_OUTCOME_KEYS},
              "incident_reconcile": {"checked": 0, "resolved": 0,
                                     "pending": 0, "inconclusive": 0,
                                     "failed": 0},
              "queued": {"scheduled_retry": [], "deadline_pending": [],
                         "overdue": [], "owner_managed": [], "hang": [],
                         "normal_wait": []},
              "overdue": {"running": [], "queued": []},
              "running_contract": {"heartbeat_only": [],
                                   "deadline_bounded": []}}
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
    # S5B/W-08: overdue — второй законный повод takeover у running-задач;
    # queued-overdue остаётся только диагностикой (W-09).
    overdue = await overdue_jobs(db, now=ts, store=job_store)
    result["overdue"] = {"running": [r.get("job_id")
                                     for r in overdue["running"]],
                         "queued": [r.get("job_id")
                                    for r in overdue["queued"]]}
    discovered_rows: dict[str, dict] = {}
    for row in list(stale) + list(overdue["running"]):
        jid = str(row.get("job_id") or "")
        if jid and jid not in discovered_rows:
            discovered_rows[jid] = dict(row)
    discovered = list(discovered_rows)
    result["stale"] = discovered
    result["takeover"]["discovered"] = list(discovered)
    if discovered:
        if job_store is None:
            # S5A/W-02: без store recovery не вызывался — никакого success.
            records = [{"job_id": jid, "outcome": "no_change",
                        "reason": "worker_lost",
                        "action": "store_unavailable"} for jid in discovered]
        else:
            result["takeover"]["attempted"] = list(discovered)
            try:
                records = await job_store.takeover_stale(
                    stale_after_seconds=stale_seconds(),
                    retry_delay_seconds=heartbeat_interval_seconds(),
                    dangerous_owners=DANGEROUS_JOB_OWNERS,
                    include_overdue=True)
            except Exception:
                logger.warning("[mca_watchdog] takeover failed", exc_info=True)
                records = [{"job_id": jid, "outcome": "failed",
                            "reason": "takeover_error", "action": "error"}
                           for jid in discovered]
        # Job мог обновить heartbeat между обнаружением и takeover —
        # честно фиксируем no_change, а не теряем его из результата.
        records = _merge_takeover_records(discovered_rows, records)
        result["takeover"]["records"] = records
        for record in records:
            jid = str(record.get("job_id") or "")
            if not jid:
                continue
            key = _bump_takeover_outcome(str(record.get("outcome")))
            result["takeover"][key].append(jid)
        result["recovered"] = list(result["takeover"]["recovered"])
        # S5C/W-01: ровно одно событие на реально затронутую задачу, с её
        # identity; агрегатного события, повторяемого на каждую строку
        # stale batch, больше нет.
        for record in records:
            await _emit_takeover_record(record)
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
    # S5B/W-08: overdue-running — такое же наблюдение, как stale (без него
    # deadline-задача не оставляет инцидента, если heartbeat ещё жив).
    stale_ids = {r.get("job_id") for r in stale}
    incident_rows = list(stale) + [r for r in overdue["running"]
                                   if r.get("job_id") not in stale_ids]
    if track_incidents:
        for row in incident_rows:
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
    # S5B/W-08: running-job'ы без обязательного прогресса (heartbeat/deadline
    # контракты) остаются видимыми — не «невидимы» и не stalled по чужому
    # таймеру. Никаких переходов/инцидентов из этой корзины не следует.
    result["running_contract"] = await running_contract_jobs(db, now=ts)
    # S5B/W-09: queued-задачи диагностируются, но НЕ забираются: разделяем
    # scheduled retry, ожидание срока/зависимости, специализированного
    # владельца очереди и настоящий «queued без исполнителя».
    try:
        result["queued"] = classify_queued_jobs(await queued_jobs(db), now=ts)
    except Exception:
        logger.debug("[mca_watchdog] queued classification failed",
                     exc_info=True)
    for item in result["queued"]["hang"]:
        if not track_incidents:
            continue
        outcome = await _track_incident(
            db, {"job_id": item.get("job_id"), "owner": item.get("owner"),
                 "kind": item.get("kind"), "error_code": "queue_no_claimer"},
            reason_code="stage_queued", stage="queued", severity="WARN")
        key = _bump_incident_outcome(outcome)
        result["incident_outcomes"][key] += 1
        if key in ("created", "reopened"):
            result["incidents"] += 1
    return result


async def _track_incident(db, row: dict, *, reason_code: str,
                          stage: str, severity: str | None = None) -> str:
    """Зарегистрировать инцидент и вернуть честный исход регистрации.

    S5A/W-10: ошибка не подавляется — log.warning + статус `failed`
    (вызывающий считает); `open_or_update` повторно НЕ вызывается и инцидент
    из собственной ошибки не создаётся (AC-24).

    S5B/W-09: диагностическая корзина queued передаёт `severity="WARN"` —
    отсутствие claimer'а наблюдаемо, но не выдаётся за падение компонента.

    S5C/W-11: `kind` входит в fingerprint — два job одного owner разных типов
    не сливаются в один инцидент; title каждого инцидента называет свой job."""
    try:
        from services import mca_incidents as inc
        # F8: тип/владелец job берётся из строки (а не хардкод «archive.rebuild»)
        # — разные job-типы не сливаются в один fingerprint.
        owner = str(row.get("owner") or "unknown")
        level = str(severity or "").upper()
        incident_severity = (inc.SEVERITY_WARN if level == "WARN"
                             else inc.SEVERITY_INFO if level == "INFO"
                             else inc.SEVERITY_ERROR)
        impact = ("очередь: задача не взята исполнителем/истёк срок"
                  if stage == "queued"
                  else "задача потеряла владельца/не прогрессирует")
        res = await inc.open_or_update(
            db, process_id="watchdog.jobs", pipeline_type=owner,
            stage=stage, reason_code=reason_code,
            error_type=str(row.get("error_code") or ""),
            dependency=None, severity=incident_severity,
            title=f"job {row.get('job_id')}: {reason_code}",
            job_id=row.get("job_id"), kind=row.get("kind"),
            trace_id=row.get("pipeline_run_id"),
            impact=impact)
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
