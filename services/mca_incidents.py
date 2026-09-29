"""Раунд 10.27 (MCA Wave 0 — остаток, `mca-17a-observability-core`) —
durable инциденты §27.6 (v19 `mca_incidents`).

Семантика:
  * **fingerprint** — устойчивый признак группировки
    `process_id|pipeline_type|stage|reason_code|error_type|dependency`
    (без свободного текста и без одного слова «timeout»);
  * отдельные trace (`first_trace_id`/`last_trace_id`) и `repeat_count`
    сохраняются; `mca_event_aggregates` — дополнительный агрегат событий;
  * **`acknowledged ≠ resolved`**; `resolved` — только после реальной проверки
    (`resolution_evidence`); история сохраняется (строка не удаляется при
    исчезновении ошибки — выставляется только `resolved_at`);
  * успешный fallback (`fallback_used=1`) понижает `severity`/`impact`, но
    инцидент основного пути остаётся видимым;
  * доставка — incremental polling (SSE/WS нет); cursor — `last_ts`/`incident_id`;
    **только миниапп** (без чата/DM/email/сторонних); stack traces не публикуются.

Kill-switch: `MCA_INCIDENTS_ENABLED`/`MCA_INCIDENT_PUSH_ENABLED` (env-only,
default ON, master-aware). REUSE `mca_events` (второй store запрещён).
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from services import mca_gates
from services.log_ring import sanitize

logger = logging.getLogger(__name__)

SEVERITY_INFO = "INFO"
SEVERITY_WARN = "WARN"
SEVERITY_ERROR = "ERROR"
SEVERITIES = (SEVERITY_INFO, SEVERITY_WARN, SEVERITY_ERROR)
_SEVERITY_ORDER = {SEVERITY_INFO: 0, SEVERITY_WARN: 1, SEVERITY_ERROR: 2}

# Bounded-контейнеры (кардинальность не растёт бесконечно).
_MAX_JOBS = 20
_MAX_CHATS = 20


def compute_fingerprint(*, process_id=None, pipeline_type=None, stage=None,
                        reason_code=None, error_type=None,
                        dependency=None) -> str:
    """Устойчивый fingerprint (§27.6): без свободного текста/слова «timeout».

    Разные симптомы (разный stage/reason/error_type/dependency) получают
    разные инциденты — новые симптомы НЕ сливаются по слову «timeout»."""
    parts = [str(process_id or ""), str(pipeline_type or ""),
             str(stage or ""), str(reason_code or ""),
             str(error_type or ""), str(dependency or "")]
    return "|".join(parts)[:400]


def _bounded_append(existing_json, value, limit: int) -> str:
    try:
        data = json.loads(existing_json) if existing_json else []
        if not isinstance(data, list):
            data = []
    except Exception:
        data = []
    if value is not None and value not in data:
        data.append(value)
    return json.dumps(data[-limit:], ensure_ascii=False)


async def _emit(event_name: str, reason_code: str | None, *,
                incident_id: str, severity: str, stage=None,
                process_id=None, pipeline_type=None, trace_id=None) -> None:
    try:
        from services import mca_trace as mt
        from services import mca_events as me
        mt.emit_stage(event_name, outcome="success", level=(
            me.LEVEL_ERROR if severity == SEVERITY_ERROR
            else me.LEVEL_WARN if severity == SEVERITY_WARN else me.LEVEL_INFO),
            component="incidents", stage=stage, reason_code=reason_code,
            entity_ids=[str(incident_id)],
            **mt.span_fields(pipeline_type=pipeline_type))
    except Exception:
        return


async def open_or_update(db, *, process_id=None, pipeline_type=None,
                         stage=None, reason_code=None, error_type=None,
                         dependency=None, severity: str = SEVERITY_ERROR,
                         title: str | None = None, job_id=None, chat_id=None,
                         trace_id=None, impact: str | None = None,
                         fallback_used: bool = False) -> dict | None:
    """Создать/обновить инцидент по fingerprint (§27.6). Fail-open → None."""
    if db is None or not mca_gates.incidents_enabled():
        return None
    if severity not in SEVERITIES:
        severity = SEVERITY_ERROR
    fingerprint = compute_fingerprint(
        process_id=process_id, pipeline_type=pipeline_type, stage=stage,
        reason_code=reason_code, error_type=error_type, dependency=dependency)
    now = int(time.time())
    incident_id = "inc_" + uuid.uuid4().hex
    safe_title = sanitize(str(title or fingerprint))[:200]
    safe_impact = sanitize(str(impact))[:300] if impact else None
    # Успешный fallback снижает severity, но инцидент основного пути остаётся.
    initial_severity = severity
    if fallback_used and severity == SEVERITY_ERROR:
        initial_severity = SEVERITY_WARN

    async def _body(conn):
        cursor = await conn.execute(
            "SELECT incident_id, resolved_at, repeat_count, severity, "
            "jobs_json, chats_json, fallback_used FROM mca_incidents "
            "WHERE fingerprint = ? ORDER BY last_ts DESC LIMIT 1",
            (fingerprint,))
        row = await cursor.fetchone()
        if row is None:
            await conn.execute(
                "INSERT INTO mca_incidents (incident_id, fingerprint, "
                "process_id, pipeline_type, stage, severity, title, first_ts, "
                "last_ts, repeat_count, jobs_json, chats_json, impact, "
                "fallback_used, first_trace_id, last_trace_id, "
                "acknowledged_at, acknowledged_by, resolved_at, "
                "resolution_evidence, created_at, updated_at) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (incident_id, fingerprint, process_id, pipeline_type, stage,
                 initial_severity, safe_title, now, now, 1,
                 json.dumps([job_id] if job_id else []),
                 json.dumps([chat_id] if chat_id is not None else []),
                 safe_impact, 1 if fallback_used else 0, trace_id, trace_id,
                 None, None, None, None, now, now))
            return {"incident_id": incident_id, "reopened": False,
                    "created": True, "fingerprint": fingerprint,
                    "severity": initial_severity}
        iid = row["incident_id"]
        was_resolved = row["resolved_at"] is not None
        # Успешный fallback понижает severity, но не скрывает инцидент.
        new_severity = severity
        if fallback_used and _SEVERITY_ORDER[severity] > _SEVERITY_ORDER[
                SEVERITY_INFO]:
            new_severity = SEVERITY_WARN
        await conn.execute(
            "UPDATE mca_incidents SET last_ts = ?, repeat_count = "
            "repeat_count + 1, severity = ?, jobs_json = ?, chats_json = ?, "
            "last_trace_id = COALESCE(?, last_trace_id), "
            "impact = COALESCE(?, impact), fallback_used = ?, "
            "resolved_at = CASE WHEN resolved_at IS NOT NULL THEN NULL "
            "ELSE resolved_at END, updated_at = ? WHERE incident_id = ?",
            (now, new_severity,
             _job_append(row["jobs_json"], job_id),
             _chat_append(row["chats_json"], chat_id),
             trace_id, safe_impact,
             1 if fallback_used else int(row["fallback_used"] or 0),
             now, iid))
        return {"incident_id": iid, "reopened": bool(was_resolved),
                "created": False, "fingerprint": fingerprint,
                "severity": new_severity}

    try:
        result = await db.write_transaction(_body, op_name="mca_incidents_open")
    except Exception:
        logger.warning("[mca_incidents] open/update failed", exc_info=True)
        return None
    if result is None:
        return None
    reason = ("incident_reopened" if result["reopened"]
              else "incident_opened")
    await _emit("INCIDENT", reason, incident_id=result["incident_id"],
                severity=result["severity"], stage=stage,
                process_id=process_id, pipeline_type=pipeline_type,
                trace_id=trace_id)
    return result


def _job_append(existing, job_id) -> str:
    try:
        data = json.loads(existing) if existing else []
        if not isinstance(data, list):
            data = []
    except Exception:
        data = []
    if job_id and job_id not in data:
        data.append(job_id)
    return json.dumps(data[-_MAX_JOBS:], ensure_ascii=False)


def _chat_append(existing, chat_id) -> str:
    try:
        data = json.loads(existing) if existing else []
        if not isinstance(data, list):
            data = []
    except Exception:
        data = []
    if chat_id is not None and chat_id not in data:
        data.append(chat_id)
    return json.dumps(data[-_MAX_CHATS:], ensure_ascii=False)


async def acknowledge(db, incident_id: str, *, actor: int) -> bool:
    """`acknowledged ≠ resolved`: фиксирует просмотр владельцем, не закрывает."""
    if db is None or not mca_gates.incidents_enabled():
        return False
    now = int(time.time())

    async def _body(conn):
        cursor = await conn.execute(
            "UPDATE mca_incidents SET acknowledged_at = ?, "
            "acknowledged_by = ?, updated_at = ? WHERE incident_id = ? "
            "AND acknowledged_at IS NULL", (now, int(actor), now, incident_id))
        return cursor.rowcount

    try:
        ok = bool(await db.write_transaction(
            _body, op_name="mca_incidents_ack"))
    except Exception:
        return False
    if ok:
        await _emit("INCIDENT", "incident_acknowledged",
                    incident_id=incident_id, severity=SEVERITY_INFO)
    return ok


async def resolve(db, incident_id: str, *, evidence: str,
                  actor: int | None = None) -> bool:
    """`resolved` — только после реальной проверки (`resolution_evidence`).

    История сохраняется: строка не удаляется при исчезновении ошибки."""
    if db is None or not mca_gates.incidents_enabled():
        return False
    if not evidence or not str(evidence).strip():
        return False      # без подтверждения проверки resolve запрещён
    now = int(time.time())
    safe_evidence = sanitize(str(evidence))[:300]

    async def _body(conn):
        cursor = await conn.execute(
            "UPDATE mca_incidents SET resolved_at = ?, resolution_evidence = ?, "
            "updated_at = ? WHERE incident_id = ? AND resolved_at IS NULL",
            (now, safe_evidence, now, incident_id))
        return cursor.rowcount

    try:
        ok = bool(await db.write_transaction(
            _body, op_name="mca_incidents_resolve"))
    except Exception:
        return False
    if ok:
        await _emit("INCIDENT", "incident_resolved", incident_id=incident_id,
                    severity=SEVERITY_INFO)
    return ok


def _row_to_public(row: dict) -> dict:
    """R17-safe публичная форма (без stack traces; bounded jobs/chats)."""
    def _loads(value):
        try:
            data = json.loads(value) if value else []
            return data if isinstance(data, list) else []
        except Exception:
            return []

    return {
        "incident_id": row.get("incident_id"),
        "fingerprint": row.get("fingerprint"),
        "process_id": row.get("process_id"),
        "pipeline_type": row.get("pipeline_type"),
        "stage": row.get("stage"),
        "severity": row.get("severity"),
        "title": row.get("title"),
        "first_ts": row.get("first_ts"),
        "last_ts": row.get("last_ts"),
        "repeat_count": row.get("repeat_count"),
        "jobs": _loads(row.get("jobs_json")),
        "chats": _loads(row.get("chats_json")),
        "impact": row.get("impact"),
        "fallback_used": bool(row.get("fallback_used")),
        "first_trace_id": row.get("first_trace_id"),
        "last_trace_id": row.get("last_trace_id"),
        "acknowledged_at": row.get("acknowledged_at"),
        "acknowledged_by": row.get("acknowledged_by"),
        "resolved_at": row.get("resolved_at"),
        "resolution_evidence": row.get("resolution_evidence"),
    }


async def active_incidents(db, *, limit: int = 100) -> list[dict]:
    """Активные инциденты (не resolved), свежие первыми."""
    if db is None or not mca_gates.incidents_enabled():
        return []
    try:
        cursor = await db.db.execute(
            "SELECT * FROM mca_incidents WHERE resolved_at IS NULL "
            "ORDER BY severity DESC, last_ts DESC LIMIT ?",
            (max(1, min(500, int(limit))),))
        return [_row_to_public(dict(r)) for r in await cursor.fetchall()]
    except Exception:
        return []


async def incident_changes(db, *, since_ts: int = 0,
                           limit: int = 200) -> dict:
    """Инкрементальный polling по cursor (§27.6): изменения после `since_ts`.

    Возвращает `{cursor, changes, degraded}`; `cursor` — max `last_ts` (для
    reconnect-догона + сверки состояния). SSE/WS нет → polling на существующей
    инфраструктуре; уведомления — только миниапп."""
    if db is None or not mca_gates.incidents_enabled():
        return {"cursor": int(since_ts), "changes": [], "degraded": True,
                "enabled": False}
    if not mca_gates.incident_push_enabled():
        return {"cursor": int(since_ts), "changes": [], "degraded": False,
                "enabled": False}
    try:
        cursor = await db.db.execute(
            "SELECT * FROM mca_incidents WHERE updated_at > ? "
            "ORDER BY updated_at ASC LIMIT ?",
            (int(since_ts), max(1, min(500, int(limit)))))
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return {"cursor": int(since_ts), "changes": [], "degraded": True,
                "enabled": True}
    new_cursor = int(since_ts)
    for r in rows:
        new_cursor = max(new_cursor, int(r.get("updated_at") or 0))
    return {
        "cursor": new_cursor,
        "changes": [_row_to_public(r) for r in rows],
        "degraded": False,
        "enabled": True,
    }


async def compact_indicator(db) -> dict:
    """Компактный индикатор на витрине (счётчики активных по severity)."""
    if db is None or not mca_gates.incidents_enabled():
        return {"available": False, "active": None, "unacknowledged": None,
                "by_severity": {}}
    try:
        cursor = await db.db.execute(
            "SELECT severity, COUNT(*) AS c, "
            "SUM(CASE WHEN acknowledged_at IS NULL THEN 1 ELSE 0 END) AS u "
            "FROM mca_incidents WHERE resolved_at IS NULL GROUP BY severity")
        by_sev, active, unack = {}, 0, 0
        for r in await cursor.fetchall():
            by_sev[str(r["severity"])] = int(r["c"])
            active += int(r["c"])
            unack += int(r["u"] or 0)
        return {"available": True, "active": active, "unacknowledged": unack,
                "by_severity": by_sev}
    except Exception:
        return {"available": False, "active": None, "unacknowledged": None,
                "by_severity": {}}
