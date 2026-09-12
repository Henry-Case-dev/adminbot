"""Раунд 9 (AGI Memory, spec §3.6.2, T-829/F2) — REST «Сон»/«Ностальгия».

APIRouter (prefix="/api"): эндпоинты аудита и ручного запуска воркеров
памяти. DI — services.lore_runtime (Q2): SQLite-часть через get_lore_db(),
воркеры — get_dream_worker()/get_nostalgia_worker() (компонент не
установлен → 503, fail-open NFR-4).

Права (spec §3.6.2, консервативно): ручной запуск/мягкое удаление/protect —
ТОЛЬКО глобальный admin (роль admin / wildcard / ADMIN_USER_ID — паттерн
`_is_global_admin` web/api/chat_lore.py); GET-логи/списки — глобальный
admin (moderator-выдачи НЕ расширяем, известные роли не трогаем).

Коды по конвенции 84.5: 401 (нет initData) / 403 / 404 (belief нет/не
kind='belief') / 409 (already_running — воркер уже бежит) / 422
(валидация) / 503 (PG/компонент/БД недоступны — fail-open).

Контракт (spec §3.6.2; D-8: POST /api/memory/nostalgia/test НЕ реализуем):
  * POST /api/memory/dream/run {chat_id?} → 202 {status: started} |
    409 {detail:{code: already_running}} — ручной run_once: окно 4–6
    игнорирует (D-5), флаг memory.dream_enabled НЕ требуется, бюджеты
    соблюдаются; асинхронный ответ (до 5 кластеров × минуты — таймаут
    API не ждём);
  * GET  /api/memory/dream/beliefs?chat_id=&limit= → последние beliefs;
  * DELETE /api/memory/dream/beliefs/{id} → мягкое удаление (D-7);
  * POST /api/memory/dream/beliefs/{id}/protect → в protected_facts чата;
  * GET  /api/memory/dream/log?limit= → строки memory_dream_log (аудит);
  * GET  /api/memory/nostalgia/log?chat_id=&limit= → nostalgia_log.
Плоские алиасы формы F2-сессии: POST /api/memory/dream (как /dream/run),
GET /api/memory/dream?limit= (beliefs+log одним ответом).
"""
import asyncio
import datetime
import json
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.settings import settings
from services import hot_config as hot
from services import lore_runtime
from web.api.deps import get_cache, get_tma_user

logger = logging.getLogger(__name__)

memory_router = APIRouter()

_DREAM_LOG_LIMIT_MAX = 500     # потолок строк лога «снов» (422-гейт Query)
_NOSTALGIA_LOG_LIMIT_MAX = 500
_BELIEF_LIMIT_MAX = 200

# F5 (cognition-dashboard-round1013, spec §3.3): серверные лимиты графа —
# код-константы (каталог-Δ=0), предохранитель Canvas на Android (ADR-1013-2).
GRAPH_MAX_NODES = 120
GRAPH_MAX_EDGES = 240
_TIMELINE_LIMIT_MAX = 100


def _tz(name: str | None):
    """ZoneInfo с фолбэком UTC (не роняем API из-за кривого TZ)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(str(name or "UTC"))
    except Exception:
        return datetime.timezone.utc


def _next_hour_epoch(hour: int, tz_name: str | None,
                     now: float | None = None) -> int:
    """Ближайший epoch момента HH:00:00 в TZ (следующее наступление часа).
    Используется как next_wake/next_run (spec §3.2: окно 4–6 + TZ)."""
    tz = _tz(tz_name)
    now = now if now is not None else time.time()
    local = datetime.datetime.fromtimestamp(now, tz)
    target = local.replace(hour=int(hour) % 24, minute=0, second=0,
                           microsecond=0)
    if target <= local:
        target += datetime.timedelta(days=1)
    return int(target.timestamp())


def _local_day_start(now: float | None, tz_name: str | None) -> int:
    """Epoch начала локальных суток (для суточных лимитов сна)."""
    tz = _tz(tz_name)
    now = now if now is not None else time.time()
    local = datetime.datetime.fromtimestamp(now, tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


# ── Pydantic-модели ─────────────────────────────────────────────────────────

class DreamRunRequest(BaseModel):
    """POST /api/memory/dream/run: chat_id None → все чаты-кандидаты."""
    chat_id: int | None = Field(default=None)


# ── helpers: права и компоненты ─────────────────────────────────────────────

def _user_permissions(cache, telegram_id: int):
    perms = cache.get_permissions_by_telegram_id(telegram_id)
    if perms is None:
        role = cache.get_permissions("user")
        return role if role is not None else type(perms)()
    return perms


def _is_global_admin(cache, telegram_id: int) -> bool:
    """Глобальный admin: роль admin / wildcard / settings.ADMIN_USER_ID
    (паттерн web/api/chat_lore.py — единая матрица доступа)."""
    if telegram_id == settings.ADMIN_USER_ID:
        return True
    perms = _user_permissions(cache, telegram_id)
    if getattr(perms, "wildcard", False):
        return True
    return cache.get_role(telegram_id) == "admin"


def _require_global_admin(request: Request, user: WebAppUser) -> None:
    """403 — юзер не глобальный admin (spec §3.6.2: только admin)."""
    if not _is_global_admin(get_cache(request), user.id):
        raise HTTPException(status_code=403, detail="permission denied")


def _db_or_503():
    """SQLite DatabaseService из lore_runtime (Q2); None → 503."""
    db = lore_runtime.get_lore_db()
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="база памяти недоступна (не инициализирована)")
    return db


def _json_list(value) -> list:
    """JSON-строка/None → list (source_ids; кривое — пусто, fail-open)."""
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        loaded = json.loads(str(value))
    except (ValueError, TypeError):
        return []
    return loaded if isinstance(loaded, list) else []


def _json_dict(value) -> dict:
    """JSON-строка/None → dict (belief_meta/meta; кривое — пусто)."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except (ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _belief_out(row: dict) -> dict:
    """Нормализация строки belief для TMA (source_ids/belief_meta — JSON).
    F2/T-1430 (spec §3): + archived/base_weight/archived_at — R17-safe
    (только метаданные; ни ключей, ни эмбеддингов).
    F3/T-1442 (spec §6): + is_paradigm — мета-факт глубокого сна."""
    status = row.get("status")
    meta = _json_dict(row.get("belief_meta"))
    is_paradigm = meta.get("type") == "paradigm"
    return {
        "id": int(row["id"]),
        "chat_id": int(row["chat_id"]),
        "fact": row["fact"],
        "weight": float(row["weight"] or 0.0),
        "importance": int(row["importance"] or 0),
        "source_ids": _json_list(row.get("source_ids")),
        "belief_meta": meta,
        "status": status,
        "archived": status == "archived_belief",
        "is_paradigm": is_paradigm,
        # F5 (spec §3.1): явный тип ленты для UI-фильтров (belief|paradigm).
        "type": "paradigm" if is_paradigm else "belief",
        "base_weight": meta.get("base_weight"),
        "archived_at": meta.get("archived_at"),
        "supersedes": row.get("supersedes"),
        "created_at": int(row["created_at"] or 0),
    }


def _dream_log_out(row: dict) -> dict:
    """Строка memory_dream_log для TMA (source_ids — JSON-массив id)."""
    return {
        "id": int(row["id"]),
        "chat_id": int(row["chat_id"]),
        "run_at": int(row["run_at"] or 0),
        "kind": row.get("kind"),
        "cluster_id": row.get("cluster_id"),
        "source_ids": _json_list(row.get("source_ids")),
        "belief_id": row.get("belief_id"),
        "tokens": int(row.get("tokens") or 0),
        "status": row.get("status"),
    }


def _nostalgia_log_out(row: dict) -> dict:
    """Строка nostalgia_log для TMA (meta — JSON-объект с reason)."""
    return {
        "id": int(row["id"]),
        "chat_id": int(row["chat_id"]),
        "ts": int(row["ts"] or 0),
        "kind": row.get("kind"),
        "fact_id": row.get("fact_id"),
        "status": row.get("status"),
        "meta": _json_dict(row.get("meta")),
    }


# ── POST /api/memory/dream/run (ручной запуск «синтеза сейчас») ─────────────

def _launch_dream(chat_id: int | None, deep: bool = False):
    """Запуск DreamWorker.run_once в фоне: воркер не установлен → 503;
    уже бежит → 409 {code: already_running}; иначе 202 {status: started}
    (асинхронный ответ — LLM-прогон до 5 кластеров занимает минуты).
    F3 (spec §8): deep=True — ручной прогон ГЛУБОКОГО сна (staged rollout)."""
    worker = lore_runtime.get_dream_worker()
    if worker is None:
        raise HTTPException(status_code=503,
                            detail="DreamWorker недоступен (не инициализирован)")
    if getattr(worker, "running", False):
        raise HTTPException(status_code=409,
                            detail={"code": "already_running"})
    asyncio.create_task(worker.run_once(chat_id, deep=deep))
    return JSONResponse(status_code=202,
                        content={"status": "started", "deep": bool(deep)})


@memory_router.post("/memory/dream/run")
async def dream_run(
    payload: DreamRunRequest | None = None,
    request: Request = None,
    user: Annotated[WebAppUser, Depends(get_tma_user)] = None,
    deep: Annotated[bool, Query()] = False,
):
    """Ручной запуск «сна» (spec §3.6.2): 202/409; только глобальный admin.
    F3 (spec §8): ?deep=1 — ручной прогон глубокого сна."""
    _require_global_admin(request, user)
    chat_id = payload.chat_id if payload is not None else None
    return _launch_dream(chat_id, deep=deep)


# POST /api/memory/dream (плоский алиас формы F2: body {chat_id?})
@memory_router.post("/memory/dream")
async def dream_run_flat(
    payload: DreamRunRequest | None = None,
    request: Request = None,
    user: Annotated[WebAppUser, Depends(get_tma_user)] = None,
    deep: Annotated[bool, Query()] = False,
):
    """Алиас POST /api/memory/dream/run (тело {chat_id?: int|null})."""
    _require_global_admin(request, user)
    chat_id = payload.chat_id if payload is not None else None
    return _launch_dream(chat_id, deep=deep)


# ── GET /api/memory/dream/beliefs ───────────────────────────────────────────

@memory_router.get("/memory/dream/beliefs")
async def dream_beliefs(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_BELIEF_LIMIT_MAX)] = 50,
    status: Annotated[str, Query()] = "all",
    kind: Annotated[str, Query(pattern="^(belief|paradigm|all)$")] = "all",
):
    """Последние beliefs (kind='belief', DESC по id; spec §3.6.2):
    chat_id — фильтр чата, limit — потолок строк. F2/T-1430 (spec §3):
    status — 'confirmed' | 'archived_belief' | 'all' (дефолт all).
    F5/T-1449 (spec §3.1): kind — 'belief' (обычные убеждения) |
    'paradigm' (мета-факты глубокого сна) | 'all' (дефолт)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    status_filter = None if status in (None, "", "all") else str(status)
    belief_type = None if kind in (None, "", "all") else str(kind)
    try:
        rows = await db.list_recent_beliefs(
            chat_id=chat_id, limit=limit, status=status_filter,
            belief_type=belief_type)
    except Exception:
        logger.warning("[memory_api] beliefs read failed — fail-open (пусто)",
                       exc_info=True)
        rows = []
    return [_belief_out(r) for r in rows]


# ── GET /api/memory/health (F2/T-1430, spec §3): телеметрия убеждений ───────

@memory_router.get("/memory/health")
async def memory_health_summary(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Счётчики охлаждения/воскрешения убеждений (spec §3): активные/архив,
    воскрешения, прогоны decay, время последнего прогона. R17-safe —
    только числа. Fail-open: ошибка БД → нули (не 500)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        counts = await db.count_beliefs_by_status()
        resurrections = await db.count_dream_log(0, kind="resurrect")
        decay_runs = await db.count_dream_log(0, kind="decay_run")
        last_decay = await db.last_decay_run()
    except Exception:
        logger.warning("[memory_api] memory health failed — нули",
                       exc_info=True)
        counts, resurrections, decay_runs, last_decay = {}, 0, 0, None
    return {
        "beliefs_active": int(counts.get("confirmed", 0)),
        "beliefs_archived": int(counts.get("archived_belief", 0)),
        "resurrections_total": int(resurrections),
        "decay_runs_total": int(decay_runs),
        "last_decay_at": last_decay,
    }


# ── GET /api/memory/deep-sleep (F3/T-1442, spec §6/§8) ──────────────────────

@memory_router.get("/memory/deep-sleep")
async def deep_sleep_status(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Статус глубокого сна (spec §6): рубильник, парадигмы, прогоны, время
    последнего запуска + лог. R17-safe — только метаданные/счётчики.
    Fail-open: ошибка БД → пустой ответ (не 500)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        paradigms = [dict(r) for r in await db.list_recent_beliefs(
            chat_id=None, limit=50, belief_type="paradigm")]
    except Exception:
        logger.warning("[memory_api] deep-sleep paradigms failed — пусто",
                       exc_info=True)
        paradigms = []
    try:
        total = await db.count_paradigms()
        last_run = await db.last_deep_run()
        runs_total = await db.count_dream_log(0, kind="deep_run")
        log = [dict(r) for r in await db.recent_dream_log(limit=50)]
    except Exception:
        logger.warning("[memory_api] deep-sleep counters failed — нули",
                       exc_info=True)
        total, last_run, runs_total, log = 0, None, 0, []
    deep_log = [r for r in log
                if str(r.get("kind") or "") in ("deep_run", "deep_skip")]
    return {
        "enabled": bool(hot.get("flags.deep_sleep_enabled",
                                settings.DEEP_SLEEP_ENABLED)),
        "paradigms_total": int(total),
        "runs_total": int(runs_total),
        "last_run_at": last_run,
        "paradigms": [_belief_out(r) for r in paradigms],
        "log": [_dream_log_out(r) for r in deep_log],
    }


# ── GET /api/memory/cognition/status (F5/T-1449, spec §3.2) ─────────────────

def _nostalgia_state(last_user_ts: int | None, sent_ts: int | None,
                     now: float, silence_min: int,
                     cooldown_h: int) -> dict:
    """Режим ностальгии для виджета (spec §3.2/§7): silence (тишина ещё не
    выдержана) | cooldown (после отправки) | ready (можно слать).
    leftover-минуты/часы — ceil, не отрицательные."""
    if last_user_ts is not None and silence_min > 0:
        ready_at = last_user_ts + silence_min * 60
        if now < ready_at:
            left = int((ready_at - now + 59) // 60)
            return {"mode": "silence", "silence_left_min": max(0, left),
                    "silence_min_total": int(silence_min),
                    "cooldown_left_h": 0,
                    "cooldown_h_total": int(cooldown_h)}
    if sent_ts is not None and cooldown_h > 0:
        ready_at = sent_ts + cooldown_h * 3600
        if now < ready_at:
            left = int((ready_at - now + 3599) // 3600)
            return {"mode": "cooldown", "silence_left_min": 0,
                    "silence_min_total": int(silence_min),
                    "cooldown_left_h": max(0, left),
                    "cooldown_h_total": int(cooldown_h)}
    return {"mode": "ready", "silence_left_min": 0,
            "silence_min_total": int(silence_min),
            "cooldown_left_h": 0, "cooldown_h_total": int(cooldown_h)}


@memory_router.get("/memory/cognition/status")
async def cognition_status(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
):
    """Статус фаз интеллекта (spec §3.2): обычный сон (running/enabled/
    state/next wake), глубокий сон, время инжекта лора, таймер ностальгии.
    R17-safe — только флаги/числа. Fail-open: ошибка БД → нейтральные
    значения (не 500)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    now = time.time()
    tz_name = hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
    worker = lore_runtime.get_dream_worker()
    dream_running = bool(getattr(worker, "dream_running", False))
    deep_running = bool(getattr(worker, "deep_running", False))
    enabled = bool(hot.get("memory.dream_enabled", settings.DREAM_ENABLED))
    deep_enabled = bool(hot.get("flags.deep_sleep_enabled",
                                settings.DEEP_SLEEP_ENABLED))
    start_h = int(hot.get("memory.dream_window_start_hour",
                          settings.DREAM_WINDOW_START_HOUR) or 4)
    last_dream = last_deep = None
    distilled_today = tokens_today = 0
    try:
        last_dream = await db.last_run_at(
            ("distilled", "resurrect", "decay_run"))
        last_deep = await db.last_deep_run()
        today = _local_day_start(now, tz_name)
        distilled_today = await db.count_dream_log(today, kind="distilled")
        tokens_today = await db.sum_dream_tokens(today)
    except Exception:
        logger.warning("[memory_api] cognition counters failed — нули",
                       exc_info=True)
    limit_dist = int(hot.get("memory.dream_distillations_per_day",
                             settings.DREAM_DISTILLATIONS_PER_DAY) or 0)
    limit_tok = int(hot.get("memory.dream_tokens_per_day",
                            settings.DREAM_TOKENS_PER_DAY) or 0)
    limit_exhausted = bool(
        (limit_dist and distilled_today >= limit_dist)
        or (limit_tok and tokens_today >= limit_tok))
    if dream_running:
        dream_state = "synthesizing"
    elif limit_exhausted:
        dream_state = "limit_exhausted"
    else:
        dream_state = "sleep"
    next_wake = _next_hour_epoch(start_h, tz_name, now)
    trigger = str(hot.get("memory.deep_sleep_trigger",
                          settings.DEEP_SLEEP_TRIGGER) or "after_sleep")
    if trigger == "fixed":
        deep_hour = int(hot.get("memory.deep_sleep_hour",
                                settings.DEEP_SLEEP_HOUR) or 7)
        deep_next = _next_hour_epoch(deep_hour, tz_name, now)
    else:
        deep_next = next_wake   # after_sleep — сразу после окна обычного сна
    lore_last = None
    try:
        from services import direct_chat_service as dcs
        lore_last = dcs.get_process_accounting().get("lore_last_inject_at")
    except Exception:
        lore_last = None
    silence_min = int(hot.get("memory.nostalgia_min_silence_minutes",
                              settings.NOSTALGIA_MIN_SILENCE_MINUTES) or 0)
    cooldown_h = int(hot.get("memory.nostalgia_cooldown_hours",
                             settings.NOSTALGIA_COOLDOWN_HOURS) or 0)
    last_user = sent_ts = None
    if chat_id is not None:
        try:
            # BLOCKER-2: реальный bot_id воркера — сообщения бота обязаны
            # исключаться из «последнего юзерского» (как в nostalgia_worker).
            bot_id = getattr(lore_runtime.get_nostalgia_worker(),
                             "bot_id", None)
            last_user = await db.get_last_user_message_ts(int(chat_id),
                                                          bot_id)
            sent_rows = await db.recent_nostalgia_sent(int(chat_id), None, 1)
            if sent_rows:
                sent_ts = int(sent_rows[0]["ts"])
        except Exception:
            logger.warning("[memory_api] nostalgia state failed — None",
                           exc_info=True)
    return {
        "dream": {"running": dream_running, "enabled": enabled,
                  "last_run_at": last_dream, "next_wake_at": next_wake,
                  "state": dream_state,
                  "budget": {"distilled_today": distilled_today,
                             "distilled_limit": limit_dist,
                             "tokens_today": tokens_today,
                             "tokens_limit": limit_tok}},
        "deep_sleep": {"running": deep_running, "enabled": deep_enabled,
                       "last_run_at": last_deep, "next_run_at": deep_next},
        "lore": {"last_inject_at": lore_last},
        # BLOCKER-2: сигнатура — _nostalgia_state(last_user_ts, sent_ts, ...).
        "nostalgia": _nostalgia_state(last_user, sent_ts, now,
                                      silence_min, cooldown_h),
        "generated_at": int(now),
    }


# ── GET /api/memory/graph (F5/T-1449, spec §3.3) ────────────────────────────

@memory_router.get("/memory/graph")
async def memory_graph(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
):
    """Force-directed граф (spec §3.3): nodes/edges SQLite GraphRAG, cap
    GRAPH_MAX_NODES/EDGES. R16 — id-ключи, label — канон-имя. Fail-open:
    ошибка БД → пустой граф."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        snap = await db.graph_snapshot(chat_id=chat_id,
                                       max_nodes=GRAPH_MAX_NODES,
                                       max_edges=GRAPH_MAX_EDGES)
    except Exception:
        logger.warning("[memory_api] graph read failed — пустой граф",
                       exc_info=True)
        snap = {"nodes": [], "edges": [], "truncated": False}
    snap["limits"] = {"nodes": GRAPH_MAX_NODES, "edges": GRAPH_MAX_EDGES}
    return snap


# ── GET /api/memory/stats (F5/T-1449, spec §3.4) ────────────────────────────

@memory_router.get("/memory/stats")
async def memory_stats(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
):
    """Метрики БД (spec §3.4) + граф-статистика для «Модулей» (§4.4):
    facts/beliefs/archived_beliefs/protected_facts/paradigms/memes и
    graph_nodes/graph_edges/relation_types. R17-safe — только числа.
    Fail-open: ошибка → нули."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        return await db.graph_stats(chat_id=chat_id)
    except Exception:
        logger.warning("[memory_api] stats failed — нули", exc_info=True)
        return {"facts": 0, "beliefs": 0, "archived_beliefs": 0,
                "protected_facts": 0, "paradigms": 0, "memes": 0,
                "graph_nodes": 0, "graph_edges": 0, "relation_types": 0}


# ── GET /api/memory/timeline (F5/T-1449, spec §3.5) ─────────────────────────

_DREAM_TIMELINE = {
    "distilled": ("🌙", "Синтезировано убеждение"),
    "resurrect": ("🌙", "Воскрешено убеждение"),
    "decay_run": ("🌙", "Охлаждение убеждений"),
    "deep_run": ("🌌", "Синтез парадигм (глубокий сон)"),
    "deep_skip": ("🌌", "Глубокий сон: пропуск"),
    "window_skip": ("🌙", "Сон: окно закрыто"),
}


@memory_router.get("/memory/timeline")
async def memory_timeline(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_TIMELINE_LIMIT_MAX)] = 20,
):
    """Объединённый Timeline последних действий (spec §3.5): memory_dream_log
    (distilled/deep_run/resurrect/decay) + nostalgia_log (sent) + инжект лора
    (in-memory). DESC по ts. R17-safe: без ключей/эмбеддингов/сырых фактов."""
    _require_global_admin(request, user)
    db = _db_or_503()
    events: list[dict] = []
    try:
        logs = await db.recent_dream_log(limit=int(limit) * 2, chat_id=chat_id)
        for row in logs:
            kind = str(row.get("kind") or "")
            icon_text = _DREAM_TIMELINE.get(kind)
            if icon_text is None:
                continue
            events.append({"ts": int(row.get("run_at") or 0),
                           "icon": icon_text[0], "text": icon_text[1],
                           "source": "dream"})
    except Exception:
        logger.warning("[memory_api] timeline dream failed — пропуск",
                       exc_info=True)
    try:
        nlogs = await db.recent_nostalgia_log(limit=int(limit) * 2,
                                              chat_id=chat_id)
        for row in nlogs:
            if str(row.get("status") or "") != "sent":
                continue
            events.append({"ts": int(row.get("ts") or 0), "icon": "📻",
                           "text": "Ностальгия: вброшен факт",
                           "source": "nostalgia"})
    except Exception:
        logger.warning("[memory_api] timeline nostalgia failed — пропуск",
                       exc_info=True)
    try:
        from services import direct_chat_service as dcs
        lore_ts = dcs.get_process_accounting().get("lore_last_inject_at")
        if lore_ts:
            events.append({"ts": int(lore_ts), "icon": "💾",
                           "text": "Лор чата инжектирован в контекст",
                           "source": "lore"})
    except Exception:
        pass
    events.sort(key=lambda e: e["ts"], reverse=True)
    return events[:int(limit)]


# GET /api/memory/dream?limit= (плоский алиас формы F2: beliefs + log)
@memory_router.get("/memory/dream")
async def dream_overview(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    limit: Annotated[int, Query(ge=1, le=_DREAM_LOG_LIMIT_MAX)] = 20,
):
    """Сводка «сна» одним ответом (форма F2-сессии): последние beliefs +
    последние строки memory_dream_log (DESC по id, limit на каждую часть)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        beliefs = [dict(r) for r in
                   await db.list_recent_beliefs(chat_id=None, limit=limit)]
        log = [dict(r) for r in await db.recent_dream_log(limit=limit)]
    except Exception:
        logger.warning("[memory_api] dream overview failed — fail-open",
                       exc_info=True)
        return {"beliefs": [], "log": []}
    return {"beliefs": [_belief_out(r) for r in beliefs],
            "log": [_dream_log_out(r) for r in log]}


# ── DELETE/POST beliefs/{id} (мягкое удаление D-7 / protect §3.4.8) ─────────

@memory_router.delete("/memory/dream/beliefs/{fact_id}")
async def dream_belief_delete(
    fact_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Мягкое удаление belief (spec §3.6.2/D-7): status='unconfirmed',
    last_confirmed_at=NULL; исключается из RAG, вычищается review-воркером.
    404 — id нет / не belief."""
    _require_global_admin(request, user)
    db = _db_or_503()
    deleted = await db.soft_delete_belief(fact_id)
    if not deleted:
        raise HTTPException(status_code=404,
                            detail="belief не найден (или не belief)")
    logger.info("[memory_api] belief soft-deleted | fact_id=%s", fact_id)
    return {"status": "ok", "deleted": True, "id": fact_id}


@memory_router.post("/memory/dream/beliefs/{fact_id}/protect")
async def dream_belief_protect(
    fact_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """«Сделать protected» (spec §3.4.8/§3.6.2): текст belief → protected_facts
    чата (chat-level); belief остаётся в графе, гейт «сна» его не тронет."""
    _require_global_admin(request, user)
    db = _db_or_503()
    row = await db.get_graph_fact(fact_id)
    if row is None or str(row.get("kind") or "") != "belief":
        raise HTTPException(status_code=404,
                            detail="belief не найден (или не belief)")
    inserted = await db.protect_belief_text(
        int(row["chat_id"]), str(row["fact"] or ""))
    logger.info("[memory_api] belief protected | fact_id=%s | chat_id=%s "
                "| inserted=%s", fact_id, row["chat_id"], inserted)
    return {"status": "ok", "protected": bool(inserted), "id": fact_id}


# ── GET /api/memory/dream/log ───────────────────────────────────────────────

@memory_router.get("/memory/dream/log")
async def dream_log(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_DREAM_LOG_LIMIT_MAX)] = 100,
):
    """Строки memory_dream_log (аудит «снов»; TMA «последние сны»)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        rows = await db.recent_dream_log(limit=limit, chat_id=chat_id)
    except Exception:
        logger.warning("[memory_api] dream log read failed — fail-open",
                       exc_info=True)
        rows = []
    return [_dream_log_out(r) for r in rows]


# ── GET /api/memory/nostalgia/log ───────────────────────────────────────────

@memory_router.get("/memory/nostalgia/log")
async def nostalgia_log(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_NOSTALGIA_LOG_LIMIT_MAX)] = 100,
):
    """Строки nostalgia_log (последние срабатывания: sent/skipped/error +
    meta-reason; spec §3.6.2)."""
    _require_global_admin(request, user)
    db = _db_or_503()
    try:
        rows = await db.recent_nostalgia_log(chat_id=chat_id, limit=limit)
    except Exception:
        logger.warning("[memory_api] nostalgia log read failed — fail-open",
                       exc_info=True)
        rows = []
    return [_nostalgia_log_out(r) for r in rows]
