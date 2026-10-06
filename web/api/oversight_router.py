"""Раунд 10.47 (mca-17c-analytics-matrix, ADR-1028-23 D10/D11) — API витрины
наблюдаемости: РОВНО 3 санкционированных маршрута на существующем
oversight-пространстве (`/api/oversight/*`):

  * ``GET  /api/oversight/runs`` — список/деталь runs поверх единого
    ``mca_events`` (read-only агрегат + keyset-пагинация; серверные фильтры —
    client-side trust запрещён, TH-2/TH-4);
  * ``GET  /api/oversight/experience/funnel`` — периодные агрегаты воронки
    самообучения из СУЩЕСТВУЮЩИХ таблиц mca-16 (read-only SELECT; второго
    store/агрегатора нет, §100.4/CA-17C-1);
  * ``POST /api/oversight/jobs/{job_id}/action`` — ЕДИНСТВЕННЫЙ write:
    cancel/resume/retry только через существующие операции TaskJobStore
    (spec §5 D13; свой контрольный контур запрещён CA-17C-1).

RBAC: все три — `requires_global_admin()` (прецедент killswitch
`web/api/oversight.py:294`); 401 без initData / 403 не-глоб-админ.
Идемпотентность — state-машина supervisor (повтор cancel на cancelled —
no-op) + idempotency-key в payload; actor/audit — событие
``OVERSIGHT_JOB_ACTION`` с reason ``oversight_job_action`` (санкция:
reason 279→280), одно на запрос (TH-8).

R17: наружу только id/коды/числа/timestamps; ``usage_json``/
``source_ref_json``/stack наружу не отдаются; из ``error_json`` — только
очищенные ``type``/``cause`` (sanitize до записи делает mca-17a).
Статусы run — read-render контракта mca-17a (partial/degraded/stalled
различимы; stalled — диагностический флаг, НЕ подмена outcome; «зелёный» =
завершение успешных стадий/валидное молчание, не «получение текста»).
"""

import json
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from services import lore_runtime
from web.api.deps import requires_global_admin

logger = logging.getLogger(__name__)

oversight17c_router = APIRouter()

# TH-4: ограничители чтения (admin-only, но границы обязаны быть).
_RUNS_SCAN_CAP = 5000          # максимум run-ов в агрегате страницы/счётчиков
_RUN_EVENTS_CAP = 1000         # событий в детале одного run
_RUN_DETAIL_JOBS_SQL_CAP = 500 # job_id страниц для error-догрузки

_RUN_STATUSES = ("succeeded", "partial", "degraded", "failed", "interrupted",
                 "cancelled", "running", "stalled")

# Reason-коды (словарь mca-13), влияющие на read-render статуса/флагов.
_R_PARTIAL = "run_partial"
_R_DEGRADED = "run_degraded"
_R_STALLED = "run_stalled"
_R_INTERRUPTERS = frozenset({"worker_lost", "heartbeat_stale",
                             "checkpoint_missing"})

_RUN_REASON_KEYS = (_R_PARTIAL, _R_DEGRADED, _R_STALLED, "worker_lost",
                    "heartbeat_stale", "checkpoint_missing", "progress_stall")

#: Whitelist полей события для детализации run (R17-safe подмножество
#: колонок `mca_events` §17.1/§27.3).
_EVENT_PUBLIC_FIELDS = (
    "event_name", "ts", "event_sequence", "outcome", "stage", "status",
    "reason_code", "component", "span_id", "parent_span_id", "pipeline_type",
    "pipeline_version", "attempt", "duration_ms", "model", "provider",
    "chat_id", "operation_id", "trace_id", "job_id", "heartbeat_at",
    "progress_at", "deadline_at",
)

_ACTIONS = ("cancel", "resume", "retry")


class JobActionBody(BaseModel):
    action: str
    idempotency_key: str | None = None


def _pool_db():
    return lore_runtime.get_lore_db()


def _error_type_cause(error_json) -> tuple[str, str]:
    """Очищенные type/cause из error_json (БЕЗ stack/сырых значений)."""
    try:
        data = json.loads(error_json) if isinstance(error_json, str) \
            else (error_json or {})
        if not isinstance(data, dict):
            return "", ""
        return (str(data.get("type") or "")[:120],
                str(data.get("cause") or "")[:120])
    except Exception:
        return "", ""


def _derive_status(*, reason_partial: bool, reason_degraded: bool,
                   failed_total: int, success_total: int,
                   interrupted_total: int, cancelled_total: int,
                   has_interrupt_reason: bool,
                   last_outcome: str | None) -> str:
    """Read-render статуса run по контракту mca-17a (§27.4).

    Порядок важен: сигналы деградации честнее «грубого» failed; ошибка
    одной ветви не стирает успехи других (partial); silent = валидное
    молчание (не падение). `stalled` — ОТДЕЛЬНЫЙ диагностический флаг,
    статус не подменяет."""
    if reason_degraded:
        return "degraded"
    if reason_partial:
        return "partial"
    if failed_total > 0 and success_total > 0:
        return "partial"
    if failed_total > 0:
        return "failed"
    if interrupted_total > 0 or has_interrupt_reason:
        return "interrupted"
    if cancelled_total > 0 and success_total == 0:
        return "cancelled"
    if last_outcome in ("success", "silent", "skipped"):
        return "succeeded"
    return "running"


# ── SQL-строительные блоки runs ─────────────────────────────────────────────

_RUNS_SELECT = """
SELECT pipeline_run_id,
       MIN(ts) AS started_ts,
       MAX(ts) AS updated_ts,
       COUNT(*) AS events_total,
       COUNT(DISTINCT CASE WHEN stage IS NOT NULL AND stage != ''
                      THEN stage END) AS stages_total,
       SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END) AS failed_total,
       SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success_total,
       SUM(CASE WHEN outcome = 'interrupted' THEN 1 ELSE 0 END)
           AS interrupted_total,
       SUM(CASE WHEN outcome = 'cancelled' THEN 1 ELSE 0 END)
           AS cancelled_total,
       MAX(model) AS model,
       MAX(provider) AS provider,
       MAX(chat_id) AS chat_id,
       MAX(trace_id) AS trace_id,
       MAX(component) AS component,
       MAX(pipeline_type) AS pipeline_type,
       MAX(pipeline_version) AS pipeline_version,
       (SELECT e2.outcome FROM mca_events e2
         WHERE e2.pipeline_run_id = m.pipeline_run_id
         ORDER BY COALESCE(e2.event_sequence, e2.id) DESC, e2.id DESC
         LIMIT 1) AS last_outcome,
       (SELECT e3.error_json FROM mca_events e3
         WHERE e3.pipeline_run_id = m.pipeline_run_id
           AND e3.outcome = 'failed'
         ORDER BY COALESCE(e3.event_sequence, e3.id) DESC, e3.id DESC
         LIMIT 1) AS last_error_json
"""


def _runs_where(*, since_ts: int, until_ts: int, pipeline_type: str | None,
                model: str | None, chat_id: int | None,
                component: str | None = None) -> tuple[str, list]:
    """Серверные фильтры (TH-2: только параметризованные условия)."""
    clauses, params = ["pipeline_run_id IS NOT NULL"], []
    if since_ts > 0:
        clauses.append("ts >= ?")
        params.append(int(since_ts))
    if until_ts > 0:
        clauses.append("ts <= ?")
        params.append(int(until_ts))
    if pipeline_type:
        clauses.append("pipeline_type = ?")
        params.append(pipeline_type)
    if model:
        clauses.append("model = ?")
        params.append(model)
    if component:
        clauses.append("component = ?")
        params.append(component)
    if chat_id is not None:
        clauses.append("chat_id = ?")
        params.append(int(chat_id))
    return " WHERE " + " AND ".join(clauses), params


async def _scan_runs(db, *, since_ts: int, until_ts: int,
                     pipeline_type: str | None, model: str | None,
                     chat_id: int | None, component: str | None = None,
                     run_id: str | None = None) -> list[dict]:
    """Один агрегатный SELECT (read-only, batch, без writer-lock).

    Строки → read-render-хедеры run (деривация статуса в Python). Cap
    `_RUNS_SCAN_CAP` — защита от вырожденно больших периодов (TH-4);
    ретенция терминальных событий (90d) ограничивает окно фактически."""
    where, params = _runs_where(since_ts=since_ts, until_ts=until_ts,
                                pipeline_type=pipeline_type, model=model,
                                chat_id=chat_id, component=component)
    if run_id is not None:
        where += " AND pipeline_run_id = ?"
        params = params + [run_id]
    reason_cols = ", ".join(
        f"SUM(CASE WHEN reason_code = '{code}' THEN 1 ELSE 0 END) AS "
        f"r{i}" for i, code in enumerate(_RUN_REASON_KEYS))
    sql = (_RUNS_SELECT + ",\n       " + reason_cols
           + f" FROM mca_events m{where} GROUP BY pipeline_run_id "
             "ORDER BY started_ts DESC LIMIT ?")
    cursor = await db.db.execute(sql, tuple(params) + (_RUNS_SCAN_CAP,))
    rows = [dict(r) for r in await cursor.fetchall()]
    runs: list[dict] = []
    for row in rows:
        reasons_present = [
            code for i, code in enumerate(_RUN_REASON_KEYS)
            if int(row.get(f"r{i}") or 0) > 0]
        failed_total = int(row.get("failed_total") or 0)
        success_total = int(row.get("success_total") or 0)
        status = _derive_status(
            reason_partial=_R_PARTIAL in reasons_present,
            reason_degraded=_R_DEGRADED in reasons_present,
            failed_total=failed_total, success_total=success_total,
            interrupted_total=int(row.get("interrupted_total") or 0),
            cancelled_total=int(row.get("cancelled_total") or 0),
            has_interrupt_reason=bool(
                set(reasons_present) & _R_INTERRUPTERS),
            last_outcome=row.get("last_outcome"))
        started = int(row.get("started_ts") or 0)
        updated = int(row.get("updated_ts") or 0)
        error_last = None
        if failed_total > 0:
            etype, cause = _error_type_cause(row.get("last_error_json"))
            if etype or cause:
                error_last = {"type": etype, "cause": cause}
        runs.append({
            "pipeline_run_id": row.get("pipeline_run_id"),
            "pipeline_type": row.get("pipeline_type"),
            "pipeline_version": row.get("pipeline_version"),
            "status": status,
            "stalled": _R_STALLED in reasons_present,
            "started_ts": started,
            "updated_ts": updated,
            "duration_ms": max(0, updated - started) * 1000,
            "events_total": int(row.get("events_total") or 0),
            "stages_total": int(row.get("stages_total") or 0),
            "stages_failed": failed_total,
            "stages_ok": success_total,
            "chat_id": row.get("chat_id"),
            "component": row.get("component"),
            "model": row.get("model"),
            "provider": row.get("provider"),
            "trace_id": row.get("trace_id"),
            "last_stage": None,
            "reason_codes": sorted(reasons_present),
            "error_last": error_last,
        })
    return runs


def _runs_disabled() -> dict:
    return {"available": False, "enabled": False, "runs": [], "counts": {},
            "next_cursor": None, "filters": {}, "generated_at": int(time.time())}


@oversight17c_router.get("/runs")
async def oversight_runs(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    run_id: str | None = Query(default=None, max_length=120),
    chat_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    pipeline_type: str | None = Query(default=None, max_length=64),
    model: str | None = Query(default=None, max_length=64),
    component: str | None = Query(default=None, max_length=64),
    since_ts: int = Query(default=0, ge=0),
    until_ts: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: int = Query(default=0, ge=0),
):
    """mca-17c (ADR-1028-23 D11): список/деталь runs поверх `mca_events`.

    Серверные фильтры (chat/период/process/status/model — TH-2/TH-4),
    keyset-пагинация по `cursor` (started_ts < cursor). `run_id` — режим
    детали: события run (R17-safe whitelist) + required/optional стадии
    из СУЩЕСТВУЮЩЕГО контракта PIPELINE_VERSIONS. Гейты
    observability+telemetry OFF → честный disabled (не нули)."""
    from services import mca_gates
    if not (mca_gates.observability_enabled()
            and mca_gates.telemetry_store_enabled()):
        return _runs_disabled()
    if status is not None and status not in _RUN_STATUSES:
        raise HTTPException(status_code=422, detail="недопустимый status")
    if since_ts and until_ts and since_ts > until_ts:
        raise HTTPException(status_code=422, detail="since_ts > until_ts")
    db = _pool_db()
    generated_at = int(time.time())
    filters = {"chat_id": chat_id, "status": status,
               "pipeline_type": pipeline_type, "model": model,
               "component": component,
               "since_ts": since_ts or None, "until_ts": until_ts or None}
    if db is None:
        return _runs_disabled()
    try:
        run_id_clean = str(run_id or "").strip()
        if run_id_clean:
            return await _run_detail(db, run_id_clean, generated_at)
        runs = await _scan_runs(db, since_ts=since_ts, until_ts=until_ts,
                                pipeline_type=pipeline_type, model=model,
                                chat_id=chat_id, component=component)
        counts: dict = {}
        for r in runs:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        page = runs
        if status is not None:
            page = [r for r in page if r["status"] == status]
        if cursor > 0:
            page = [r for r in page if int(r["started_ts"]) < int(cursor)]
        page = page[:limit + 1]
        next_cursor = None
        if len(page) > limit:
            page = page[:limit]
            next_cursor = int(page[-1]["started_ts"])
        return {"available": True, "enabled": True, "runs": page,
                "counts": counts, "next_cursor": next_cursor,
                "filters": filters, "generated_at": generated_at}
    except HTTPException:
        raise
    except Exception:
        logger.warning("[oversight17c] runs read failed — fail-open",
                       exc_info=True)
        return _runs_disabled()


async def _run_detail(db, run_id: str, generated_at: int) -> dict:
    """Деталь run: хедер + события (whitelist-поля) + контракт стадий."""
    runs = await _scan_runs(db, since_ts=0, until_ts=0, pipeline_type=None,
                            model=None, chat_id=None, run_id=run_id)
    header = runs[0] if runs else None
    if header is None:
        return {"available": True, "enabled": True, "run": None,
                "generated_at": generated_at}
    cursor = await db.db.execute(
        "SELECT * FROM mca_events WHERE pipeline_run_id = ? "
        "ORDER BY COALESCE(event_sequence, id), id LIMIT ?",
        (run_id, _RUN_EVENTS_CAP))
    events: list[dict] = []
    for raw in await cursor.fetchall():
        row = dict(raw)
        ev = {k: row.get(k) for k in _EVENT_PUBLIC_FIELDS}
        etype, cause = _error_type_cause(row.get("error_json"))
        ev["error_type"] = etype or None
        ev["error_cause"] = cause or None
        events.append(ev)
    required = optional = None
    try:
        from services.mca_process_registry import get_pipeline
        pv = get_pipeline(str(header.get("pipeline_type") or ""),
                          header.get("pipeline_version"))
        if pv is not None:
            required = list(pv.required_stages)
            optional = [s.name for s in pv.stages if not s.required]
    except Exception:
        required = optional = None
    return {"available": True, "enabled": True,
            "run": {**header, "events": events,
                    "required_stages": required, "optional_stages": optional},
            "generated_at": generated_at}


# ── воронка самообучения (mca-16 read-only; второго store нет) ──────────────

def _funnel_disabled(days: int) -> dict:
    zero = {"total": 0, "success": 0, "failure": 0, "unknown": 0}
    return {"available": False, "enabled": False,
            "period": {"since_ts": 0, "until_ts": 0, "days": days},
            "episodes": dict(zero),
            "lessons": {"candidate": 0, "validated": 0, "active": 0,
                        "suspended": 0, "superseded": 0, "new_in_period": 0,
                        "scope": "current"},
            "applications": {**zero, "unique_lessons": 0},
            "feedback": {"total": 0, "unique_episodes": 0},
            "notes": [], "generated_at": int(time.time())}


@oversight17c_router.get("/experience/funnel")
async def oversight_experience_funnel(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    days: int = Query(default=30, ge=1, le=365),
    chat_id: int | None = Query(default=None),
):
    """mca-17c (ADR-1028-23 D11/D8): воронка самообучения за период.

    Read-only SELECT поверх существующих таблиц mca-16
    (`mca_experience_episodes`/`mca_lessons`/`mca_lesson_applications`/
    `mca_experience_feedback`) — БЕЗ второго store/агрегатора (§100.4).
    Каждое число — записи своей таблицы за период; статусы уроков —
    ТЕКУЩЕЕ состояние реестра (scope: current); unknown отображается
    как unknown (≠ провал/успех, A57)."""
    from services import mca_gates
    now = int(time.time())
    generated_at = now
    if not mca_gates.experience_lessons_enabled():
        return _funnel_disabled(days)
    db = _pool_db()
    if db is None:
        return _funnel_disabled(days)
    since = now - int(days) * 86400
    try:
        ep_params: list = [since, now]
        ep_where = "created_at BETWEEN ? AND ?"
        if chat_id is not None:
            ep_where += " AND chat_id = ?"
            ep_params.append(int(chat_id))
        cursor = await db.db.execute(
            f"SELECT outcome_kind, COUNT(*) c FROM mca_experience_episodes "
            f"WHERE {ep_where} GROUP BY outcome_kind", tuple(ep_params))
        ep_rows = {str(r["outcome_kind"]): int(r["c"])
                   for r in await cursor.fetchall()}
        episodes = {"total": sum(ep_rows.values()),
                    "success": ep_rows.get("success", 0),
                    "failure": ep_rows.get("failure", 0),
                    "unknown": ep_rows.get("unknown", 0)}
        lessons_where = "scope_chat_id = ?" if chat_id is not None else "1=1"
        lesson_params: tuple = (int(chat_id),) if chat_id is not None else ()
        cursor = await db.db.execute(
            f"SELECT status, COUNT(*) c FROM mca_lessons WHERE "
            f"{lessons_where} GROUP BY status", lesson_params)
        ls_rows = {str(r["status"]): int(r["c"])
                   for r in await cursor.fetchall()}
        cursor = await db.db.execute(
            f"SELECT COUNT(*) c FROM mca_lessons WHERE created_at BETWEEN "
            f"? AND ? AND {lessons_where}",
            (since, now) + lesson_params)
        new_row = await cursor.fetchone()
        lessons = {"candidate": ls_rows.get("candidate", 0),
                   "validated": ls_rows.get("validated", 0),
                   "active": ls_rows.get("active", 0),
                   "suspended": ls_rows.get("suspended", 0),
                   "superseded": ls_rows.get("superseded", 0),
                   "new_in_period": int(new_row["c"]) if new_row else 0,
                   "scope": "current"}
        app_params: list = [since, now]
        app_where = "applied_at BETWEEN ? AND ?"
        if chat_id is not None:
            app_where += " AND chat_id = ?"
            app_params.append(int(chat_id))
        cursor = await db.db.execute(
            f"SELECT outcome, COUNT(*) c FROM mca_lesson_applications "
            f"WHERE {app_where} GROUP BY outcome", tuple(app_params))
        ap_rows = {str(r["outcome"]): int(r["c"])
                   for r in await cursor.fetchall()}
        cursor = await db.db.execute(
            f"SELECT COUNT(DISTINCT lesson_id) u FROM "
            f"mca_lesson_applications WHERE {app_where}",
            tuple(app_params))
        u_row = await cursor.fetchone()
        applications = {
            "total": sum(ap_rows.values()),
            "success": ap_rows.get("success", 0),
            "failure": ap_rows.get("failure", 0),
            "unknown": ap_rows.get("unknown", 0),
            "unique_lessons": int(u_row["u"]) if u_row else 0,
        }
        fb_params: list = [since, now]
        fb_where = "ts BETWEEN ? AND ?"
        if chat_id is not None:
            fb_where += " AND chat_id = ?"
            fb_params.append(int(chat_id))
        cursor = await db.db.execute(
            f"SELECT COUNT(*) c, COUNT(DISTINCT episode_id) u FROM "
            f"mca_experience_feedback WHERE {fb_where}", tuple(fb_params))
        fb_row = await cursor.fetchone()
        feedback = {"total": int(fb_row["c"]) if fb_row else 0,
                    "unique_episodes": int(fb_row["u"]) if fb_row else 0}
        return {"available": True, "enabled": True,
                "period": {"since_ts": since, "until_ts": now,
                           "days": int(days)},
                "episodes": episodes, "lessons": lessons,
                "applications": applications, "feedback": feedback,
                "notes": ["единица — записи соответствующих таблиц за период",
                          "число feedback ≠ число уникальных уроков",
                          "unknown ≠ провал и ≠ успех",
                          "статусы уроков — текущее состояние реестра"],
                "generated_at": generated_at}
    except Exception:
        logger.warning("[oversight17c] funnel read failed — fail-open",
                       exc_info=True)
        return _funnel_disabled(days)


# ── диагностические действия (ЕДИНСТВЕННЫЙ write; ADR-1028-23 D10) ─────────

def _audit_job_action(*, job_id: str, action: str, actor: int,
                      changed: bool, idempotent: bool,
                      prev_status: str) -> None:
    """actor/audit: одно событие на запрос (TH-8), reason
    `oversight_job_action` (санкция reason 279→280); fail-open.

    Rework R1 (T-5196): outcome — `success` (валидный терминальный исход
    ALL_OUTCOMES; `"ok"` словарём не является — build_event отбрасывал
    событие ЦЕЛИКОМ: ни лог-строки, ни записи в хранилище)."""
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            "OVERSIGHT_JOB_ACTION", outcome="success",
            component="oversight_actions",
            operation_id=str(job_id)[:120],
            reason_code="oversight_job_action",
            job_id=str(job_id)[:120],
            usage_json={"action": action, "actor": int(actor),
                        "changed": bool(changed),
                        "idempotent": bool(idempotent),
                        "prev_status": str(prev_status)})
    except Exception:
        logger.warning("[oversight17c] audit emit failed — fail-open",
                       exc_info=True)


@oversight17c_router.post("/jobs/{job_id}/action")
async def oversight_job_action(
    job_id: str,
    request: Request,
    payload: JobActionBody,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """mca-17c (spec §5 D13, A56): cancel/resume/retry над job.

    ТОЛЬКО через существующие операции TaskJobStore (свой контрольный
    контур запрещён CA-17C-1): cancel — `TaskJobStore.cancel` (тот же
    терминальный исход JOB_CANCELLED + fencing-механизм recover_stale);
    resume — `requeue`; retry — `set_next_retry` (прошлая ошибка не
    затирается; retry = новая попытка по контракту mca-17a). Повтор на
    том же состоянии — идемпотентный no-op. Гейт супервизора OFF → 409
    (честный disabled)."""
    from services import mca_gates, task_supervisor as ts
    action = str(payload.action or "").strip()
    if action not in _ACTIONS:
        raise HTTPException(status_code=422,
                            detail=f"допустимо одно из {_ACTIONS}")
    if not mca_gates.task_supervisor_enabled():
        raise HTTPException(status_code=409,
                            detail="task supervisor disabled")
    job_id_clean = str(job_id or "").strip()
    if not job_id_clean or len(job_id_clean) > 120:
        raise HTTPException(status_code=422, detail="некорректный job_id")
    db = _pool_db()
    if db is None:
        raise HTTPException(status_code=503, detail="локальная БД недоступна")
    store = ts.TaskJobStore(db)
    job = await store.get(job_id_clean)
    if job is None:
        raise HTTPException(status_code=404, detail="задача не найдена")
    prev_status = str(job.get("status") or "")
    active = prev_status in (ts.JOB_QUEUED, ts.JOB_RUNNING)
    changed = False
    idempotent = False
    if action == "cancel":
        if active:
            changed = bool(await store.cancel(job_id_clean))
        elif prev_status == ts.JOB_CANCELLED:
            idempotent = True        # повтор cancel на cancelled = no-op
        else:
            raise HTTPException(
                status_code=409,
                detail=f"invalid state for cancel: {prev_status}")
    elif action == "resume":
        if active:
            idempotent = True        # уже активна — no-op
        elif prev_status == ts.JOB_COMPLETED:
            raise HTTPException(
                status_code=409,
                detail=f"invalid state for resume: {prev_status}")
        else:
            changed = bool(await store.requeue(job_id_clean))
    else:  # retry
        if active:
            idempotent = True
        elif prev_status == ts.JOB_COMPLETED:
            raise HTTPException(
                status_code=409,
                detail=f"invalid state for retry: {prev_status}")
        elif prev_status == ts.JOB_INTERRUPTED:
            # `set_next_retry` прерывания не поднимает (state-машина) —
            # resume-ветка существующего `requeue`.
            changed = bool(await store.requeue(job_id_clean))
        else:
            # `set_next_retry` сохраняет reason/error (прошлая ошибка не
            # затирается) и ставит статус queued — новая попытка.
            changed = bool(await store.set_next_retry(
                job_id_clean, int(time.time()), reason_code=None))
    after = await store.get(job_id_clean)
    new_status = str(after.get("status") or prev_status) if after \
        else prev_status
    actor = getattr(user, "id", 0) or 0
    _audit_job_action(job_id=job_id_clean, action=action, actor=actor,
                      changed=changed, idempotent=idempotent,
                      prev_status=prev_status)
    return {"ok": True, "job_id": job_id_clean, "action": action,
            "status": new_status, "changed": changed,
            "idempotent": idempotent, "delivery": "accepted"}
