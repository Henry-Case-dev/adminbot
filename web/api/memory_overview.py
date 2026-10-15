"""ASAP 8 v6.3 W3-STATUS (U03/B03) — read-only данные для Статуса.

Два маленьких GET-endpoint на собственном роутере (прецедент stories/
oversight_router; routes.py и cover_styles не затрагиваются):

  * GET /api/memory/expired-overview?chat_id= — B03.3 блок «Просрочено N»:
    раскладка expired-памяти из MemoryManager.expired_memory_overview
    (W1-MEMORY-MIG §7): expired_total / expired_searchable / needs_recheck /
    superseded_total / infinite_retention. Bounded COUNT-агрегаты, без
    re-embedding и без выборки контента.
  * GET /api/memory/intel-funnels?chat_id= — U03.4 воронки «Инициатива» и
    «Опыт» (данные W1-CHAT-INTEL UI-handoff): counters durable-задач
    task_jobs kind='initiative.observe' / kind='experience.review'
    (checkpoint-payload, честные), liveness-штамп наблюдателя, оконные
    (24ч/7д) счётчики событий mca_events, лаг семантики
    (watermark/pending vs MAX(smart_messages.id)) и последнее применение
    урока (mca_lesson_applications).

Права: ТОЛЬКО глобальный admin (та же матрица, что /api/memory/health —
`_require_global_admin` web/api/memory_agi.py). R17-safe: только числа,
статусы и reason-коды — ни текстов сообщений, ни фактов, ни ключей.
Fail-open: ошибка секции → {"available": false} внутри секции (не 500);
нет БД → 503 (конвенция memory-API).
"""
import json
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from web.api.deps import get_tma_user
from web.api.memory_agi import _db_or_503, _require_global_admin

logger = logging.getLogger(__name__)

memory_overview_router = APIRouter()

# Durable-константы владельцев данных (W1): kind'и task_jobs и события.
_OBSERVE_JOB_KIND = "initiative.observe"
_REVIEW_JOB_KIND = "experience.review"

_INITIATIVE_EVENTS = (
    "initiative_observer_scan", "initiative_opportunity",
    "initiative_decided", "initiative_writer_generated",
    "initiative_writer_unavailable", "initiative_recheck_passed",
    "initiative_sent", "initiative_observer_diagnostic",
)
_EXPERIENCE_EVENTS = ("semantic_extract", "detector_signal", "applied",
                      "retrieved")

# TTL-кэш счётчиков воронок (60с) — тот же бюджет-паттерн, что
# _HEALTH_COUNT_TTL в memory_agi: polling Статуса не должен сканировать
# mca_events/task_jobs на каждый тик.
_FUNNELS_TTL = 60.0
_funnels_cache: dict = {}          # "funnels" -> (db, ts, payload)
# MemoryManager-обёртка кэшируется per-db (без LLM: overview читает только
# COUNT-агрегаты через self.db).
_overview_mm: dict = {}            # id(db) -> (db, MemoryManager)


def _memory_manager(db):
    """MemoryManager(db, llm=None) — для expired_memory_overview достаточно
    self.db (fail-open обёртка над expired_graph_facts_overview). Кэш per-db:
    __init__ лёгкий, но пересоздавать на каждый GET незачем."""
    entry = _overview_mm.get(id(db))
    if entry is not None and entry[0] is db:
        return entry[1]
    from services.summary_memory import MemoryManager
    mm = MemoryManager(db, None)
    _overview_mm[id(db)] = (db, mm)
    return mm


def _funnels_cached(db):
    entry = _funnels_cache.get("funnels")
    if entry is not None:
        c_db, ts, payload = entry
        if c_db is db and (time.monotonic() - ts) < _FUNNELS_TTL:
            return payload
    return None


def _funnels_store(db, payload) -> None:
    _funnels_cache["funnels"] = (db, time.monotonic(), payload)


async def _latest_job_async(db, kind: str) -> dict | None:
    """Свежая durable-задача kind (любой статус — running тоже честный)
    по последнему checkpoint (updated_at). Публичное подмножество: статус,
    штампы, counters/семантика-курсоры из payload (числа, R17-safe)."""
    cursor = await db.db.execute(
        "SELECT status, reason_code, payload, created_at, updated_at, "
        "finished_at FROM task_jobs WHERE kind = ? "
        "ORDER BY updated_at DESC, created_at DESC LIMIT 1", (kind,))
    row = await cursor.fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    out = {
        "status": str(row["status"] or ""),
        "reason_code": row["reason_code"],
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
        "finished_at": row["finished_at"],
        "counters": {},
    }
    counters = payload.get("counters")
    if isinstance(counters, dict):
        # Плоские int-счётчики + подполя-словари (eval_skips/reject reasons)
        # как есть — честные коды причин, без контента.
        out["counters"] = counters
    if kind == _REVIEW_JOB_KIND:
        # B02: лаг семантики — watermark/pending vs MAX(smart_messages.id).
        watermark = int(payload.get("semantic_watermark") or 0)
        pending = payload.get("semantic_pending")
        pending_sum = 0
        if isinstance(pending, dict):
            for v in pending.values():
                pending_sum += max(0, int(v or 0))
        out["semantic_watermark"] = watermark
        out["semantic_pending"] = pending_sum
    return out


async def _events_counts(db, names: tuple, since_ts: int,
                         chat_id: int | None) -> dict:
    """COUNT событий mca_events по именам за окно (chat-scope опционально).
    Fail-open → нули (воронка не рвёт снимок)."""
    out = {name: 0 for name in names}
    try:
        sql = ("SELECT event_name, COUNT(*) AS c FROM mca_events "
               "WHERE ts >= ? AND event_name IN "
               "(" + ",".join("?" * len(names)) + ")")
        params: list = [int(since_ts), *names]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(int(chat_id))
        sql += " GROUP BY event_name"
        cursor = await db.db.execute(sql, tuple(params))
        for r in await cursor.fetchall() or ():
            name = str(r["event_name"])
            if name in out:
                out[name] = int(r["c"] or 0)
    except Exception:
        logger.warning("[memory_overview] events count failed — zeros",
                       exc_info=True)
    return out


async def _max_smart_message_id(db) -> int:
    try:
        cursor = await db.db.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM smart_messages")
        row = await cursor.fetchone()
        return int(row["m"] or 0)
    except Exception:
        return 0


async def _last_application(db, chat_id: int | None) -> dict | None:
    """Последнее применение урока (mca-16) — ts + исход, без контента."""
    try:
        sql = ("SELECT applied_at, outcome FROM mca_lesson_applications ")
        params: list = []
        if chat_id is not None:
            sql += "WHERE chat_id = ? "
            params.append(int(chat_id))
        sql += "ORDER BY applied_at DESC LIMIT 1"
        cursor = await db.db.execute(sql, tuple(params))
        row = await cursor.fetchone()
        if row is None:
            return None
        return {"ts": int(row["applied_at"] or 0),
                "outcome": str(row["outcome"] or "")}
    except Exception:
        return None


def _section_disabled() -> dict:
    return {"available": False}


@memory_overview_router.get("/memory/expired-overview")
async def memory_expired_overview(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
):
    """B03.3: блок «Просрочено N» — сколько памяти истекло, сколько из неё
    доступно историческому поиску, сколько требует перепроверки, сколько
    вытеснено новыми версиями, режим хранения. Chat-scope: без chat_id —
    вся база. Никогда не 500 по данным: fail-open внутри обёртки W1."""
    _require_global_admin(request, user)
    db = _db_or_503()
    overview = await _memory_manager(db).expired_memory_overview(
        None if chat_id is None else int(chat_id))
    failed = bool(overview.get("error"))
    return {
        "available": not failed,
        "now_ts": int(overview.get("now_ts") or time.time()),
        "expired_total": int(overview.get("expired_total") or 0),
        "expired_searchable": int(overview.get("expired_searchable") or 0),
        "needs_recheck": int(overview.get("needs_recheck") or 0),
        "superseded_total": int(overview.get("superseded_total") or 0),
        "infinite_retention": bool(overview.get("infinite_retention")),
    }


@memory_overview_router.get("/memory/intel-funnels")
async def memory_intel_funnels(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
):
    """U03.4: durable-воронки «Инициатива» (B01) и «Опыт» (B02) для Статуса.

    initiative.observe: counters checkpoint-payload (observed/eligible/
    opportunities/intents_created/silent_decisions/react_decisions/sent/
    writer_unavailable/eval_unavailable/errors/eval_skips) + liveness-штамп
    наблюдателя + оконные 24ч/7д события. experience.review: semantic_*
    counters + лаг семантики + последнее применение + оконные события.
    Счётчики job — durable-накопленные (наследуются между прогонами);
    окна 24ч/7д — события mca_events. chat_id фильтрует ТОЛЬКО события
    (job глобальный — подпись честная)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    cached = _funnels_cached(db)
    if cached is not None:
        return cached
    now = int(time.time())
    init_events: dict = {}
    exp_events: dict = {}
    for key, days in (("24h", 1), ("7d", 7)):
        since = now - days * 86400
        init_events[key] = await _events_counts(
            db, _INITIATIVE_EVENTS, since, chat_id)
        exp_events[key] = await _events_counts(
            db, _EXPERIENCE_EVENTS, since, chat_id)
    try:
        init_job = await _latest_job_async(db, _OBSERVE_JOB_KIND)
    except Exception:
        logger.warning("[memory_overview] observe job read failed",
                       exc_info=True)
        init_job = None
    try:
        review_job = await _latest_job_async(db, _REVIEW_JOB_KIND)
    except Exception:
        logger.warning("[memory_overview] review job read failed",
                       exc_info=True)
        review_job = None
    liveness = {}
    try:
        from services import memory_maintenance as _mm
        liveness = dict(getattr(_mm, "_initiative_observer_last_tick", {}) or {})
    except Exception:
        liveness = {}
    payload = {
        "available": True,
        "now_ts": now,
        "chat_scoped_events": chat_id is not None,
        "initiative": {
            "available": init_job is not None or bool(init_events["24h"]),
            "job": init_job,
            "liveness": {
                "ts": liveness.get("ts"),
                "status": liveness.get("status"),
                "observed": liveness.get("observed"),
                "opportunities": liveness.get("opportunities"),
            },
            "events": init_events,
        },
        "experience": {
            "available": review_job is not None or bool(exp_events["24h"]),
            "job": review_job,
            "semantic_lag": {
                "watermark": int((review_job or {}).get(
                    "semantic_watermark") or 0),
                "max_message_id": await _max_smart_message_id(db),
                "pending": int((review_job or {}).get(
                    "semantic_pending") or 0),
            },
            "last_application": await _last_application(db, chat_id),
            "events": exp_events,
        },
    }
    _funnels_store(db, payload)
    return payload
