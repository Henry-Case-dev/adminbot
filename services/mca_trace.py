"""Раунд 10.27 (MCA Wave 0 — остаток, `mca-17a-observability-core`) —
сквозной trace/span §27.3, lifecycle/честный итог §27.4 и ядро диагностических
действий §27.9.

Расширение контракта `mca-13`, **не второй store**: поля принимает
`mca_events.build_event`, персистит `flush_events` (v19-колонки). Логическая
модель:
  * `pipeline_run_id` — корень прогона (`mca_pipeline_runs`);
  * `span_id`/`parent_span_id` — реальное вложение;
  * `linked_span_ids` — связи без владения (singleflight/кеш/async-continuation);
  * `job_id`/`attempt_id`/`causation_id` — связь с durable-задачей и причиной;
  * `event_sequence` — монотонный счётчик в run; связь — по ID/sequence, не по ts;
  * `status` — состояние стадии (§27.4);
  * длительность — `time.monotonic()`; отображение — UTC.

Kill-switch: `MCA_TRACE_SPAN_ENABLED`/`MCA_JOB_LIFECYCLE_ENABLED` (env-only,
default ON, master-aware).
"""
from __future__ import annotations

import logging
import time
import uuid

from services import mca_gates

logger = logging.getLogger(__name__)

# ── состояния стадии (§27.4) ────────────────────────────────────────────────
STAGE_QUEUED = "queued"
STAGE_RUNNING = "running"
STAGE_WAITING_EXTERNAL = "waiting_external"
STAGE_RETRY_SCHEDULED = "retry_scheduled"
STAGE_SUCCEEDED = "succeeded"
STAGE_SKIPPED = "skipped"
STAGE_FAILED = "failed"
STAGE_CANCELLED = "cancelled"
STAGE_INTERRUPTED = "interrupted"
STAGE_STATUSES = (
    STAGE_QUEUED, STAGE_RUNNING, STAGE_WAITING_EXTERNAL, STAGE_RETRY_SCHEDULED,
    STAGE_SUCCEEDED, STAGE_SKIPPED, STAGE_FAILED, STAGE_CANCELLED,
    STAGE_INTERRUPTED,
)
TERMINAL_STAGE_STATUSES = frozenset({
    STAGE_SUCCEEDED, STAGE_SKIPPED, STAGE_FAILED, STAGE_CANCELLED,
    STAGE_INTERRUPTED,
})

# ── состояния run (§27.4) ───────────────────────────────────────────────────
RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_PARTIAL = "partial"
RUN_DEGRADED = "degraded"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"
RUN_INTERRUPTED = "interrupted"
RUN_STATUSES = (RUN_RUNNING, RUN_SUCCEEDED, RUN_PARTIAL, RUN_DEGRADED,
                RUN_FAILED, RUN_CANCELLED, RUN_INTERRUPTED)
# `stalled` — диагностическое (не персистится как outcome).
RUN_STALLED = "stalled"

# ── ядро диагностических действий (§27.9) ───────────────────────────────────
ACTION_CANCEL = "cancel"
ACTION_RESUME = "resume"
ACTION_RETRY = "retry"
ACTION_REFRESH = "refresh"      # read-only
CONTROL_ACTIONS = frozenset({ACTION_CANCEL, ACTION_RESUME, ACTION_RETRY,
                             ACTION_REFRESH})
# Разрешённые типы job для управления (кандидаты `mca-17c`);
# остальные → `job_not_allowed`.
ALLOWED_CONTROL_JOB_TYPES = frozenset({
    "archive", "dossier", "summary", "maintenance", "backup",
})

_SEQUENCES: dict[str, int] = {}


def new_run_id() -> str:
    return "run_" + uuid.uuid4().hex


def new_span_id() -> str:
    return "sp_" + uuid.uuid4().hex


def new_attempt_id() -> str:
    return "at_" + uuid.uuid4().hex


def utc_now() -> int:
    return int(time.time())


def monotonic_ms(start: float | None) -> int | None:
    """Длительность внутри процесса — монотонными часами (§27.3)."""
    if start is None:
        return None
    try:
        return max(0, int((time.monotonic() - start) * 1000))
    except Exception:      # pragma: no cover
        return None


def next_sequence(run_id: str, *, seed: int | None = None) -> int:
    """Следующий монотонный `event_sequence` в рамках run."""
    if seed is not None:
        _SEQUENCES[run_id] = max(_SEQUENCES.get(run_id, 0), int(seed))
    value = _SEQUENCES.get(run_id, 0) + 1
    _SEQUENCES[run_id] = value
    return value


def reset_sequences() -> None:
    """Сброс in-process счётчиков (тесты)."""
    _SEQUENCES.clear()


# ── span-поля события (§27.3; расширение MCA-13, не второй store) ───────────

_SPAN_FIELD_KEYS = (
    "pipeline_run_id", "pipeline_type", "pipeline_version", "span_id",
    "parent_span_id", "job_id", "attempt_id", "causation_id",
    "event_sequence", "status", "heartbeat_at", "progress_at", "deadline_at",
    "checkpoint_ref",
)


def span_fields(*, run_id=None, pipeline_type=None, pipeline_version=None,
                span_id=None, parent_span_id=None, job_id=None,
                attempt_id=None, causation_id=None, status=None,
                heartbeat_at=None, progress_at=None, deadline_at=None,
                checkpoint_ref=None, linked_span_ids=None) -> dict:
    """Нормализовать span-поля; OFF-гейт → пустой dict (паритет MCA-13).

    `linked_span_ids` (связь без владения) остаётся списком — `build_event`
    сериализует JSON-поле sanitize'ом."""
    if not mca_gates.trace_span_enabled():
        return {}
    raw = {
        "pipeline_run_id": run_id,
        "pipeline_type": pipeline_type,
        "pipeline_version": pipeline_version,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "job_id": job_id,
        "attempt_id": attempt_id,
        "causation_id": causation_id,
        "status": status,
        "heartbeat_at": heartbeat_at,
        "progress_at": progress_at,
        "deadline_at": deadline_at,
        "checkpoint_ref": checkpoint_ref,
        "linked_span_ids": linked_span_ids,
    }
    return {k: v for k, v in raw.items() if v is not None}


def emit_stage(event_name: str, *, outcome: str, level: str = "INFO",
               linked_span_ids=None, **fields):
    """Эмитировать стадийное событие через единую точку `mca_events` (fail-open).

    `linked_span_ids` (list) кладётся в JSON-поле `linked_span_ids`; список
    передаётся как есть — `build_event` сериализует JSON-поле ровно один раз
    (F9: без двойного кодирования)."""
    try:
        from services import mca_events as me
        if linked_span_ids is not None:
            fields["linked_span_ids"] = list(linked_span_ids)
        return me.emit_mca_event(event_name, outcome=outcome, level=level,
                                 **fields)
    except Exception:
        return None


# ── honest outcome (§27.4) ──────────────────────────────────────────────────

def compute_run_outcome(stage_results: list[dict], *,
                        pipeline_type: str | None = None,
                        version: str | None = None,
                        pending_children: int = 0,
                        uncommitted_write: bool = False) -> str:
    """Честный итог run по контракту pipeline version (§27.4/D5).

    Приоритет: `cancelled`/`interrupted`/`failed` обязательной стадии →
    соответствующий итог; сбой необязательной с работающим fallback →
    `degraded`/`partial`; незафиксированная обязательная запись или
    незавершённый обязательный дочерний job → **не** `succeeded`;
    иначе — `succeeded`.

    `stage_results`: список `{name, status, required?, has_fallback?,
    reason_code?}`. Обязательность/fallback, если не заданы явно, берутся из
    реестра pipeline-version."""
    from services import mca_process_registry as reg
    pv = reg.get_pipeline(pipeline_type, version) if pipeline_type else None

    def _spec(name):
        return pv.stage(name) if pv is not None else None

    has_optional_failure = False
    req_failed = req_cancelled = req_interrupted = False
    for res in stage_results:
        status = str(res.get("status") or "")
        spec = _spec(res.get("name"))
        required = res.get("required", spec.required if spec else True)
        if status not in (STAGE_FAILED, STAGE_SKIPPED, STAGE_CANCELLED,
                          STAGE_INTERRUPTED):
            continue
        if not required:
            has_optional_failure = True
            continue
        # F10: только ТЕРМИНАЛЬНЫЙ статус ОБЯЗАТЕЛЬНОЙ стадии определяет
        # cancelled/interrupted/failed run; optional cancelled/interrupted с
        # fallback → degraded/partial (не отменяет весь run).
        if status == STAGE_CANCELLED:
            req_cancelled = True
        elif status == STAGE_INTERRUPTED:
            req_interrupted = True
        else:
            req_failed = True
    if req_failed or req_cancelled or req_interrupted:
        if req_interrupted:
            return RUN_INTERRUPTED
        if req_cancelled:
            return RUN_CANCELLED
        return RUN_FAILED
    if pending_children > 0 or uncommitted_write:
        # run не success, пока не зафиксирована запись/остаётся обязательный
        # дочерний job — честно остаётся running (асинхронное продолжение
        # оформляется отдельным linked job).
        return RUN_RUNNING
    if has_optional_failure:
        # Необязательная стадия с fallback → degraded/partial.
        failed_optional = [
            r for r in stage_results
            if str(r.get("status")) in (STAGE_FAILED, STAGE_SKIPPED,
                                        STAGE_CANCELLED, STAGE_INTERRUPTED)
            and not _is_required(r, _spec(r.get("name")))]
        if any(r.get("has_fallback",
                     _spec(r.get("name")).has_fallback
                     if _spec(r.get("name")) else False)
               for r in failed_optional):
            return RUN_DEGRADED
        return RUN_PARTIAL
    return RUN_SUCCEEDED


def _is_required(res: dict, spec) -> bool:
    return bool(res.get("required", spec.required if spec else True))


def run_diagnostic(row: dict, *, now: int | None = None) -> dict:
    """Добавить диагностическое `stalled` (§27.4 — не заменяет outcome).

    `stalled` = stale heartbeat ИЛИ progress-stall по типу; вычисляется на
    чтении, не персистится."""
    now = int(now if now is not None else time.time())
    out = dict(row)
    out["stalled"] = False
    status = str(row.get("status") or "")
    if status != RUN_RUNNING:
        return out
    stale = mca_gates.job_stale_seconds()
    hb = row.get("heartbeat_at")
    pa = row.get("progress_at")
    if hb is not None and now - int(hb) > stale:
        out["stalled"] = True
        out["stall_reason"] = "heartbeat_stale"
    stall_secs = mca_gates.progress_stall_seconds(row.get("pipeline_type"))
    if pa is not None and now - int(pa) > stall_secs:
        out["stalled"] = True
        out["stall_reason"] = out.get("stall_reason") or "progress_stall"
    return out


# ── durable run lifecycle (`mca_pipeline_runs`, v19) ────────────────────────

async def start_run(db, *, pipeline_type: str, version: str = "1",
                    root_job_id: str | None = None,
                    run_id: str | None = None,
                    deadline_at: int | None = None,
                    config_version: str | None = None,
                    parent_span_id: str | None = None,
                    span_id: str | None = None,
                    causation_id: str | None = None,
                    job_id: str | None = None,
                    attempt_id: str | None = None) -> str | None:
    """Открыть durable run (`running`), вернуть `pipeline_run_id`.

    Fail-open: ошибка БД не рвёт поток (возвращает `run_id` для логов, но записи
    может не быть)."""
    if not mca_gates.job_lifecycle_enabled():
        return None
    rid = run_id or new_run_id()
    sid = span_id or new_span_id()
    now = utc_now()
    if db is not None:
        try:
            await db.write_transaction(
                lambda conn: _insert_run(conn, rid, pipeline_type, version,
                                         root_job_id, deadline_at,
                                         config_version, now),
                op_name="mca_pipeline_run_start")
        except Exception:
            logger.warning("[mca_trace] run start persist failed | run=%s",
                           rid, exc_info=True)
    emit_stage("PIPELINE_START", outcome="start", level="INFO",
               component=pipeline_type, stage=STAGE_QUEUED, **span_fields(
                   run_id=rid, pipeline_type=pipeline_type,
                   pipeline_version=version, span_id=sid,
                   parent_span_id=parent_span_id, job_id=job_id,
                   attempt_id=attempt_id, causation_id=causation_id,
                   status=STAGE_QUEUED, deadline_at=deadline_at))
    return rid


async def _insert_run(conn, rid, pipeline_type, version, root_job_id,
                      deadline_at, config_version, now):
    await conn.execute(
        "INSERT OR REPLACE INTO mca_pipeline_runs (pipeline_run_id, "
        "pipeline_type, pipeline_version, root_job_id, status, reason_code, "
        "started_at, finished_at, heartbeat_at, progress_at, deadline_at, "
        "checkpoint_ref, config_version, created_at, updated_at) VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, pipeline_type, version, root_job_id, RUN_RUNNING, None, now,
         None, now, now, deadline_at, None, config_version, now, now))


async def touch_run(db, run_id: str, *, progress: bool = False,
                    checkpoint_ref: str | None = None) -> None:
    """Обновить heartbeat/progress run (durable); fail-open."""
    if db is None or not mca_gates.job_lifecycle_enabled():
        return
    now = utc_now()

    async def _body(conn):
        if progress:
            await conn.execute(
                "UPDATE mca_pipeline_runs SET heartbeat_at = ?, progress_at = "
                "?, updated_at = ? WHERE pipeline_run_id = ?",
                (now, now, now, run_id))
        elif checkpoint_ref is not None:
            await conn.execute(
                "UPDATE mca_pipeline_runs SET heartbeat_at = ?, "
                "checkpoint_ref = ?, updated_at = ? WHERE pipeline_run_id = ?",
                (now, checkpoint_ref, now, run_id))
        else:
            await conn.execute(
                "UPDATE mca_pipeline_runs SET heartbeat_at = ?, updated_at = ? "
                "WHERE pipeline_run_id = ?", (now, now, run_id))

    try:
        await db.write_transaction(_body, op_name="mca_pipeline_run_touch")
    except Exception:
        logger.debug("[mca_trace] run touch failed", exc_info=True)


async def finish_run(db, run_id: str, *, outcome: str,
                     reason_code: str | None = None,
                     checkpoint_ref: str | None = None) -> bool:
    """Закрыть durable run терминальным итогом; fail-open → False."""
    if db is None or not mca_gates.job_lifecycle_enabled():
        return False
    now = utc_now()

    async def _body(conn):
        cursor = await conn.execute(
            "UPDATE mca_pipeline_runs SET status = ?, reason_code = ?, "
            "finished_at = ?, updated_at = ?, "
            "checkpoint_ref = COALESCE(?, checkpoint_ref) "
            "WHERE pipeline_run_id = ?",
            (outcome, reason_code, now, now, checkpoint_ref, run_id))
        return cursor.rowcount

    try:
        return bool(await db.write_transaction(
            _body, op_name="mca_pipeline_run_finish"))
    except Exception:
        logger.warning("[mca_trace] run finish failed | run=%s", run_id,
                       exc_info=True)
        return False


async def get_run(db, run_id: str) -> dict | None:
    """Прочитать run-строку с диагностическим `stalled`."""
    if db is None:
        return None
    try:
        cursor = await db.db.execute(
            "SELECT * FROM mca_pipeline_runs WHERE pipeline_run_id = ?",
            (run_id,))
        row = await cursor.fetchone()
        return run_diagnostic(dict(row)) if row is not None else None
    except Exception:
        return None


async def recent_runs(db, *, limit: int = 50) -> list[dict]:
    if db is None:
        return []
    try:
        cursor = await db.db.execute(
            "SELECT * FROM mca_pipeline_runs ORDER BY started_at DESC LIMIT ?",
            (max(1, min(500, int(limit))),))
        return [run_diagnostic(dict(r)) for r in await cursor.fetchall()]
    except Exception:
        return []


# ── root job + batch traces (§27.3) ─────────────────────────────────────────

def batch_span_fields(*, run_id: str, root_span_id: str, batch_index: int,
                      range_start=None, range_end=None, processed=None,
                      failed_ids=None, job_id=None) -> dict:
    """Span-поля batch-трейса длительного job: links на root + счётчики.

    failures не скрываются усреднением — `failed_ids`/`failed_count` явны."""
    linked = [root_span_id] if root_span_id else []
    fields = span_fields(
        run_id=run_id, span_id=new_span_id(), linked_span_ids=linked,
        job_id=job_id, status=STAGE_RUNNING)
    # Счётчики batch — в R17-safe `usage_json`; проблемные записи — bounded
    # `entity_ids` (failures не скрываются усреднением «обработано N»).
    payload = {"batch_index": int(batch_index)}
    if range_start is not None:
        payload["range_start"] = range_start
    if range_end is not None:
        payload["range_end"] = range_end
    if processed is not None:
        payload["processed"] = int(processed)
    payload["failed_count"] = len(failed_ids or [])
    fields["usage_json"] = payload
    if failed_ids:
        fields["entity_ids"] = [str(x)[:64] for x in list(failed_ids)[:10]]
    return fields


# ── ядро диагностических действий (§27.9) ───────────────────────────────────

def job_allowed_for_control(owner: str | None, kind: str | None) -> bool:
    owner = str(owner or "")
    return owner in ALLOWED_CONTROL_JOB_TYPES


async def control_action(db, job_store, *, action: str, job_id: str,
                         actor: int, dry_run: bool = False) -> dict:
    """cancel/resume/retry/refresh ядро (§27.9).

    * по правам (RBAC проверяет вызывающий API/`mca-17c`);
    * actor + audit-событие (через MCA-13);
    * идемпотентно (повтор → no-op/тот же результат);
    * refresh — только чтение; повтор внешнего side effect/`delivery_unknown`
      запрещён без безопасной семантики (сверка по operation ID вместо
      слепого retry);
    * интерфейса запуска произвольного кода/SQL нет.
    """
    result = {"action": action, "job_id": job_id, "status": "noop",
              "allowed": False, "idempotent_replay": False}
    if action not in CONTROL_ACTIONS:
        result["status"] = "invalid_action"
        return result
    row = await job_store.get(job_id) if (job_store is not None and job_id) \
        else None
    if row is None:
        result["status"] = "not_found"
        return result
    owner, kind = row.get("owner"), row.get("kind")
    if not job_allowed_for_control(owner, kind):
        result["status"] = "not_allowed"
        _audit(action, job_id, actor, "job_not_allowed", row)
        return result
    result["allowed"] = True
    current = str(row.get("status") or "")
    # Идемпотентность: повтор терминального действия — no-op.
    if action == ACTION_CANCEL and current in ("cancelled", "completed",
                                               "failed", "interrupted"):
        result["idempotent_replay"] = True
        result["status"] = "already_terminal"
        return result
    if action == ACTION_REFRESH:
        result["status"] = "read_only"
        result["job"] = {k: row.get(k) for k in
                         ("job_id", "owner", "kind", "status", "reason_code",
                          "attempt", "heartbeat_at", "progress_at",
                          "checkpoint_ref", "pipeline_run_id", "span_id")}
        return result
    if action == ACTION_RETRY:
        # `delivery_unknown` — слепой повтор side effect запрещён.
        if current == "delivery_unknown" or \
                str(row.get("reason_code") or "") == "delivery_unknown":
            result["status"] = "reconcile_required"
            _audit(action, job_id, actor, "action_idempotent_replay", row)
            return result
    if dry_run:
        result["status"] = "dry_run"
        return result
    # Реальное действие на durable-строке.
    try:
        if action == ACTION_CANCEL:
            ok = await job_store.finish(job_id, status="cancelled",
                                        reason_code="cancelled")
        elif action == ACTION_RETRY:
            ok = await job_store.requeue(
                job_id, reason_code="stage_retry_scheduled")
        elif action == ACTION_RESUME:
            ok = await job_store.requeue(
                job_id, reason_code="recovery_from_checkpoint")
        else:      # pragma: no cover
            ok = False
        result["status"] = "applied" if ok else "noop"
        _audit(action, job_id, actor, result["status"], row)
    except Exception:
        logger.warning("[mca_trace] control action failed | action=%s job=%s",
                       action, job_id, exc_info=True)
        result["status"] = "error"
    return result


def _audit(action: str, job_id: str, actor: int, outcome: str, row: dict) -> None:
    try:
        emit_stage("CONTROL_ACTION", outcome="success",
                   component="control_plane", stage=action,
                   reason_code="action_idempotent_replay"
                   if outcome in ("already_terminal", "idempotent_replay")
                   else None,
                   entity_ids=[str(job_id)],
                   **span_fields(run_id=row.get("pipeline_run_id"),
                                 span_id=row.get("span_id"),
                                 job_id=job_id, attempt_id=row.get("attempt_id"),
                                 status=STAGE_RUNNING))
    except Exception:
        return


# ── runtime-продюсер метрик §17.4 (carry-over §94.5 п.3) ────────────────────

def _rss_mb() -> float | None:
    try:
        from services.memory_health import _rss_bytes
        rss = _rss_bytes()
        return round(rss / 1024 / 1024, 1) if rss else None
    except Exception:
        return None


async def collect_runtime_metrics(db) -> dict:
    """Живые источники `runtime`-метрик; отсутствующий источник → None.

    `UNKNOWN ≠ 0`: поле без продюсера не выдумывается. Fail-open."""
    runtime: dict = {}
    rss = _rss_mb()
    if rss is not None:
        runtime["rss_mb"] = rss
    if db is not None:
        try:
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM mca_provenance_status "
                "WHERE origin_status IS NOT NULL")
            row = await cursor.fetchone()
            if row is not None:
                total = int(row["c"])
                cur2 = await db.db.execute(
                    "SELECT COUNT(*) AS c FROM mca_provenance_status "
                    "WHERE origin_status NOT IN ('unknown', '')")
                resolved = int((await cur2.fetchone())["c"])
                if total > 0:
                    runtime["provenance_coverage"] = round(resolved / total, 6)
        except Exception:
            pass
        try:
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM lore_stories")
            row = await cursor.fetchone()
            if row is not None:
                runtime["histories"] = int(row["c"])
        except Exception:
            pass
        try:
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM graph_facts WHERE origin = "
                "'derived_belief'")
            row = await cursor.fetchone()
            if row is not None:
                runtime["episodes"] = int(row["c"])
        except Exception:
            pass
    try:
        from services.smart_cache import get_smart_cache
        cache = get_smart_cache()
        size = getattr(cache, "size", None) or getattr(cache, "__len__", None)
        if callable(size):
            runtime["cache_entries"] = int(size())
    except Exception:
        pass
    return runtime
