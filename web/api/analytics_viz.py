"""ASAP 8 v6.3 W3-ANALYTICS (U05.3 / D12 §18I.12) — read-only данные
визализаций Аналитики на РЕАЛЬНЫХ durable-данных.

Два маленьких GET-endpoint на собственном роутере (прецедент
memory_overview/stories/oversight_router; routes.py и cover_styles не
затрагиваются; регистрация — в web/app.py рядом с analytics_router):

  * GET /api/analytics/viz/activity?days=14 — heatmap фактической
    активности (D12 §18I.12-L): durable-события mca_events, buckets
    «день × час» (время сервера), honest-доступность. Телеметрия OFF →
    `telemetry_enabled:false` + причина (НЕ нули-от-балды).
  * GET /api/analytics/viz/process-activity — последнее реальное
    действие/эффективный статус для «Процессов» (U05.1): поверх
    СУЩЕСТВУЮЩЕГО реестра (mca_process_registry.registry_snapshot) +
    durable-события mca_events по заявленным event_names. Ничего не
    выдумывается: нет событий → «не запускался», skip → «не было
    условий», failed → «ошибка».

Права: ТОЛЬКО глобальный admin (та же матрица, что /api/oversight/*).
R17-safe: только числа/статусы/коды причин и ТИПЫ ошибок — ни текстов
сообщений, ни фактов, ни ключей, ни stack trace. Fail-open: ошибка
секции → {"available": false, reason}; нет БД → 503 (конвенция
oversight/memory-API). Bounded: окно дней ≤ 60, LIMIT/GROUP BY по
индексу idx_mca_events_ts / полному скану только по именам событий.
"""
import json
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Query, Request

from web.api.deps import requires_global_admin

logger = logging.getLogger(__name__)

analytics_viz_router = APIRouter()

_MAX_DAYS = 60
# Bounded-кап на IN-clause (реестр ~50 процессов × 1–3 события).
_MAX_EVENT_NAMES = 200


def _lore_db():
    from services import lore_runtime
    return lore_runtime.get_lore_db()


def _error_type(error_json) -> str | None:
    """Тип ошибки (R17-safe: только класс, не текст)."""
    if not error_json:
        return None
    try:
        raw = json.loads(error_json) if isinstance(error_json, str) \
            else error_json
        t = (raw or {}).get("type")
        return str(t)[:80] if t else None
    except (TypeError, ValueError):
        return None


async def _rows(db, sql: str, params=()) -> list[dict]:
    cursor = await db.db.execute(sql, params)
    try:
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        pass


@analytics_viz_router.get("/analytics/viz/activity")
async def analytics_viz_activity(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    days: Annotated[int, Query(ge=1, le=_MAX_DAYS)] = 14,
):
    """Heatmap фактической активности (день × час) из durable mca_events.

    Честность: `telemetry_enabled:false` (гейты observability/store OFF) —
    данных НЕ рисуем нулями; пустое окно → `empty_reason:
    'no_events_in_window'` (было тихо ≠ «ноль активности» выдумкой:
    события durable, отсутствие строк = отсутствие событий)."""
    from services import mca_gates
    telemetry = bool(mca_gates.telemetry_store_enabled()
                     and mca_gates.observability_enabled())
    now = int(time.time())
    base = {"available": False, "days": days, "generated_at": now,
            "telemetry_enabled": telemetry, "timezone": "server-local"}
    if not telemetry:
        return {**base, "reason": "telemetry_off (MCA_OBSERVABILITY/"
                                  "TELEMETRY_STORE_ENABLED=OFF)"}
    db = _lore_db()
    if db is None:
        return {**base, "reason": "db_unavailable"}
    since = now - int(days) * 86400
    try:
        totals = (await _rows(
            db,
            "SELECT COUNT(*) AS c, COALESCE(SUM(CASE WHEN outcome = 'failed' "
            "THEN 1 ELSE 0 END), 0) AS errs, MIN(ts) AS first_ts, "
            "MAX(ts) AS last_ts FROM mca_events WHERE ts >= ?",
            (since,)) or [{}])[0]
        bucket_rows = await _rows(
            db,
            "SELECT strftime('%Y-%m-%d', ts, 'unixepoch', 'localtime') AS d, "
            "CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) "
            "AS h, COUNT(*) AS c, COALESCE(SUM(CASE WHEN outcome = 'failed' "
            "THEN 1 ELSE 0 END), 0) AS errs FROM mca_events WHERE ts >= ? "
            "GROUP BY d, h ORDER BY d, h",
            (since,))
    except Exception:
        logger.warning("[analytics_viz] activity read failed — fail-open",
                       exc_info=True)
        return {**base, "reason": "read_failed"}
    total = int(totals.get("c") or 0)
    buckets = [{"d": str(r["d"]), "h": int(r["h"] or 0),
                "c": int(r["c"] or 0), "errs": int(r["errs"] or 0)}
               for r in bucket_rows]
    out = {**base, "available": True, "total": total,
           "errors_total": int(totals.get("errs") or 0),
           "first_ts": int(totals["first_ts"] or 0) or None,
           "last_ts": int(totals["last_ts"] or 0) or None,
           "buckets": buckets}
    if not total:
        out["empty_reason"] = "no_events_in_window"
    return out


def _effective_status(p: dict, acts: dict) -> dict:
    """Эффективный статус процесса (U05.1) из реестра + durable-событий.

    Коды: off (выключен гейтом) / not_instrumented / never_run /
    error / no_conditions / fallback / running / working. Ровно словарь
    ТЗ: «не запускался», «работает с результатом», «ошибка», «не было
    условий», «выключен» (+ честные служебные not_instrumented/fallback)."""
    status = str(p.get("status") or "")
    if status == "disabled":
        return {"code": "off", "reason": "выключен (гейт)"}
    if status == "not_instrumented":
        return {"code": "not_instrumented",
                "reason": "события не инструментированы"}
    if status == "not_run":
        return {"code": "never_run", "reason": "запусков не было"}
    names = [str(n) for n in (p.get("event_names") or []) if n in acts]
    if not names:
        return {"code": "never_run",
                "reason": "событий нет (не запускался или давно)"}
    last = max((acts[n] for n in names), key=lambda r: r["ts"])
    outcome = str(last.get("outcome") or "")
    reason = str(last.get("reason_code") or "")
    if outcome == "failed":
        return {"code": "error", "reason": "последний запуск с ошибкой"
                + (": " + reason if reason else ""),
                "last": last}
    if outcome == "skipped":
        return {"code": "no_conditions",
                "reason": "условий не было" + (": " + reason
                                               if reason else ""),
                "last": last}
    if outcome == "fallback":
        return {"code": "fallback",
                "reason": "работает через резервный контур", "last": last}
    if outcome in ("running", "pending"):
        return {"code": "running", "reason": "выполняется сейчас",
                "last": last}
    return {"code": "working", "reason": "работает, есть результат",
            "last": last}


@analytics_viz_router.get("/analytics/viz/process-activity")
async def analytics_viz_process_activity(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """«Последнее реальное действие» по каждому процессу реестра.

    Источник — реестр (registry_snapshot: статус/гейт/имена событий) +
    mca_events (последнее событие по имени, счётчики 24ч/7д). Процесс без
    заявленных событий честно `not_instrumented`; событие никогда не
    встречалось — `never_run`. Никаких dummy-значений."""
    from services import mca_process_registry
    db = _lore_db()
    if db is None:
        return {"available": False, "reason": "db_unavailable",
                "generated_at": int(time.time())}
    try:
        snap = await mca_process_registry.registry_snapshot(db)
    except Exception:
        logger.warning("[analytics_viz] registry_snapshot failed",
                       exc_info=True)
        return {"available": False, "reason": "registry_unavailable",
                "generated_at": int(time.time())}
    processes = snap.get("processes") or []
    names: list[str] = []
    for p in processes:
        for n in (p.get("event_names") or []):
            if n and n not in names:
                names.append(str(n))
    names = names[:_MAX_EVENT_NAMES]
    acts: dict[str, dict] = {}
    if names:
        placeholders = ",".join("?" * len(names))
        now = int(time.time())
        try:
            last_rows = await _rows(
                db,
                "SELECT event_name, ts, outcome, reason_code, error_json "
                "FROM (SELECT event_name, ts, outcome, reason_code, "
                "error_json, ROW_NUMBER() OVER (PARTITION BY event_name "
                "ORDER BY ts DESC, id DESC) AS rn FROM mca_events "
                "WHERE event_name IN (" + placeholders + ")) "
                "WHERE rn = 1", tuple(names))
            for r in last_rows:
                acts[str(r["event_name"])] = {
                    "ts": int(r["ts"] or 0), "outcome": str(r["outcome"]),
                    "reason_code": r["reason_code"],
                    "error_type": _error_type(r.get("error_json"))}
            for label, days in (("24h", 1), ("7d", 7)):
                since = now - days * 86400
                cnt_rows = await _rows(
                    db,
                    "SELECT event_name, COUNT(*) AS c FROM mca_events "
                    "WHERE ts >= ? AND event_name IN (" + placeholders
                    + ") GROUP BY event_name", (since, *names))
                for r in cnt_rows:
                    acts.setdefault(str(r["event_name"]), {})["c_" + label] \
                        = int(r["c"] or 0)
        except Exception:
            logger.warning("[analytics_viz] process events read failed",
                           exc_info=True)
            acts = {}
    out = []
    for p in processes:
        eff = _effective_status(p, acts)
        last = eff.pop("last", None)
        counts = {"24h": 0, "7d": 0}
        for n in (p.get("event_names") or []):
            a = acts.get(str(n)) or {}
            counts["24h"] = max(counts["24h"], int(a.get("c_24h") or 0))
            counts["7d"] = max(counts["7d"], int(a.get("c_7d") or 0))
        out.append({
            "process_id": p.get("process_id"),
            "status": p.get("status"),
            "effective": eff.get("code"),
            "reason": eff.get("reason"),
            "last_ts": (last or {}).get("ts"),
            "last_outcome": (last or {}).get("outcome"),
            "last_reason": (last or {}).get("reason_code"),
            "last_error_type": (last or {}).get("error_type"),
            "counts": counts,
        })
    return {"available": True, "generated_at": int(time.time()),
            "processes": out,
            "events_available": bool(acts)}
