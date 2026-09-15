"""Раунд 10 (global-oversight-dashboard, F-12 §2) — сводка всех чатов.

`build_summary()` → list[ChatSummary] (загнутое: кэш 60 с + refresh-
инвалидация при записи kill-switch/глобального ключа; PG down → ошибки-
массив + живые данные по другим источникам). Источники: профили PG
(chat_params/gates_opt_in), feature_gates (effective), permsoc (master),
chat_keys (own/forbidden), worker_budget (day-chat), chat_admins COUNT,
SQLite last_active (smart_messages MAX(ts), кэш 120 с), названия чатов —
кэш 10 мин (bot.get_chat через web_runtime; фолбэк «Чат {id}»).

Запись (kill-switch/глобальный ключ) — ЕДИНЫЕ пути: feature_gates
.set_feature_gate (spec §3) и chat_params.set_chat_params
(keys.allow_global) — без отдельных override-слоёв.
"""
import asyncio
import datetime
import logging
import time
from dataclasses import dataclass

from config.settings import settings
from services import (budget_limits, chat_keys, chat_params, chat_usage,
                      feature_gates, permsoc, worker_budget, worker_settings)

logger = logging.getLogger(__name__)

_SUMMARY_TTL = 60.0
_TITLE_TTL = 600.0
_ACTIVITY_TTL = 120.0
_HISTORY_LIMIT = 5

# F3 (10.19, ADR-1019-8 D6): ключи лимита контекста и хранения импорта —
# для аддитивного блока `limits` «Сводки».
# D-6 (ревью Батча C): env-значение (может быть None) + ФАКТИЧЕСКИ
# эффективный дефолт для «не задано» (0/None). F4 (10.19, ADR-1019-4 D3):
# эффективные дефолты контекста — 5000/3000/16000 (были 1000/500/4000).
CONTEXT_LIMIT_KEYS: tuple[tuple[str, str, int | None, int], ...] = (
    ("global_tokens", "limits.chat_global_context_max_tokens",
     settings.CHAT_GLOBAL_CONTEXT_MAX_TOKENS, 5000),
    ("thread_tokens", "limits.chat_thread_max_tokens",
     settings.CHAT_THREAD_MAX_TOKENS, 3000),
    ("total_budget_tokens", "limits.chat_context_budget_tokens",
     settings.CHAT_CONTEXT_BUDGET_TOKENS, settings.CHAT_CONTEXT_BUDGET_TOKENS),
)
STORAGE_KEY = "limits.import_history_retention_days"
STORAGE_DEFAULT = settings.IMPORT_HISTORY_RETENTION_DAYS
# per-chat ключи фон-контура (source-диагностика зеркала `budget`).
WORKER_LIMIT_KEYS = {
    "llm_calls": "limits.worker_daily_llm_calls_per_chat",
    "llm_tokens": "limits.worker_daily_llm_tokens_per_chat",
}
# S10.19-14 (Medium): глобальные дефолты фон-контура — для «тихих» чатов без
# строк дня (`used=0`), чтобы НЕ рапортовать ложное «Запрещено» (limit 0).
WORKER_DEFAULT_LIMITS = {
    "llm_calls": settings.WORKER_DAILY_LLM_CALLS_PER_CHAT,
    "llm_tokens": settings.WORKER_DAILY_LLM_TOKENS_PER_CHAT,
}

PROFILE_COLS_SQL = (
    "SELECT p.chat_id, p.is_active, p.chat_params, p.gates_opt_in, "
    "p.updated_at FROM chat_profiles p WHERE p.chat_id < 0 "
    "ORDER BY p.chat_id"
)
ADMINS_COUNT_SQL = (
    "SELECT chat_id, COUNT(*) AS c FROM chat_admins GROUP BY chat_id"
)
ACTIVITY_SQL = (
    "SELECT chat_id, MAX(ts) AS last_ts FROM smart_messages "
    "WHERE chat_id IN ({ph}) GROUP BY chat_id"
)
OWN_KEYS_SQL = (
    "SELECT chat_id FROM chat_keys WHERE key_name = 'keys.llm_api_key'"
)


@dataclass(frozen=True)
class ChatSummary:
    chat_id: int
    title: str
    is_active: bool
    gates_opt_in: bool
    heavy: dict
    permsoc: bool
    key_status: str            # 'own' | 'global' | 'forbidden' | 'none'
    key_last4: str | None
    allow_global: bool
    admins_count: int
    last_active_ts: str | None
    budget: dict | None


_cache: dict = {}
_cache_ts: float = 0.0
_title_cache: dict[int, tuple[float, str]] = {}
_activity_cache: dict = {}
_activity_ts: float = 0.0


def invalidate_summary() -> None:
    """Refresh-инвалидация (после POST killswitch/global_key)."""
    global _cache_ts
    _cache_ts = 0.0


def _pool(pg):
    return getattr(pg, "pool", None) if pg is not None else None


async def _chat_title(chat_id: int) -> str:
    """Имя чата (кэш 10 мин): bot.get_chat → title; фолбэк «Чат id»."""
    if chat_id in _title_cache:
        ts, title = _title_cache[chat_id]
        if time.monotonic() - ts < _TITLE_TTL:
            return title
    title = f"Чат {chat_id}"
    try:
        from services import web_runtime
        bot = web_runtime.get_web_bot()
        if bot is not None:
            chat = await bot.get_chat(chat_id)
            title = getattr(chat, "title", None) or title
    except Exception:
        logger.debug("[oversight] title fetch failed | chat=%s", chat_id)
    _title_cache[chat_id] = (time.monotonic(), title)
    return title


async def _activity_map(pg) -> dict[int, str | None]:
    """SQLite-агрегат MAX(ts) smart_messages (кэш 120 с) — дешёвый."""
    global _activity_ts
    now = time.monotonic()
    if _activity_cache and (now - _activity_ts) < _ACTIVITY_TTL:
        return _activity_cache
    out: dict[int, str | None] = {}
    try:
        from services import web_runtime
        db = web_runtime.get_lore_db()
        if db is not None and getattr(db, "db", None) is not None:
            rows = await db.db.fetch_all(
                "SELECT chat_id, MAX(ts) AS last_ts "
                "FROM smart_messages GROUP BY chat_id")
            for r in rows:
                chat_id = r["chat_id"]
                ts = r.get("last_ts")
                if ts is not None:
                    out[chat_id] = datetime.datetime.fromtimestamp(
                        float(ts)).isoformat()
    except Exception:
        logger.warning("[oversight] activity aggregate failed — empty",
                       exc_info=True)
    _activity_cache = out
    _activity_ts = now
    return out


async def _limits_metric(pg, chat_id: int, *, contour: str, used_key: str,
                         day_rows, metric: str) -> dict:
    """F3 (ADR-1019-8 D6): метрика {used, limit, unlimited, forbidden, source}.

    D-1 (ревью Батча C): контур задаётся ЯВНО (`contour`), а не по имени
    метрики — раньше обе ветки вызывались с `metric='llm_calls'/'llm_tokens'`,
    поэтому условие `metric in WORKER_LIMIT_KEYS` было всегда истинным и
    `chat_usage` (direct) не читался, а `key_status`-ветка была мёртвой.

    * `contour='direct'` — источник `chat_usage.key_status` (общий ключ чата);
    * `contour='worker'` — `worker_budget.get_usage` (зеркало `budget`);
    * `used_key` значим только для direct (`'calls'|'tokens'`).
    Вызывающий ловит исключения (fail-open по под-объекту).

    S10.19-14: при ПУСТОМ дне (нет строк `worker_budget`) лимит фон-контура
    резолвится `chat → global → default` (`WORKER_DEFAULT_LIMITS`), а не
    обнуляется (было ложное «Запрещено»). Если строка дня есть — её `limit`
    уже per-chat-резолвнут (`worker_budget._metric_limit`), берём как есть;
    `source` уточняем best-effort."""
    if contour == "direct":
        status = await chat_usage.key_status(pg, chat_id)
        return dict(status[used_key])
    rows = [r for r in (day_rows or []) if r.get("metric") == metric]
    used = int(rows[0]["used"]) if rows else 0
    if rows:
        limit = int(rows[0]["limit"])
    else:
        limit = int(WORKER_DEFAULT_LIMITS.get(metric, 0))
    source = "default"
    try:
        resolved, source = await worker_settings.resolve_setting_with_source(
            WORKER_LIMIT_KEYS[metric], chat_id=chat_id, default=limit)
        if not rows and resolved is not None:
            limit = int(resolved)
    except Exception:
        source = "default"
    return {
        "used": used, "limit": limit,
        "unlimited": budget_limits.is_unlimited(limit),
        "forbidden": budget_limits.is_forbidden(limit),
        "source": source,
    }


async def _limits_block(pg, chat_id: int, day_rows) -> dict:
    """F3 (ADR-1019-8 D6): аддитивный блок `limits` карточки чата.

    Ключи: key_budget/worker_budget {calls,tokens}, context {global_tokens,
    thread_tokens, total_budget_tokens}, storage {import_retention_days,
    import_forever, source, label}. Fail-open ПО-ПОД-ОБЪЕКТНО: ошибка любого
    источника → под-объект с нулём/дефолтом, но 500 не бывает (R16)."""
    limits: dict = {}
    try:
        limits["key_budget"] = {
            "calls": await _limits_metric(pg, chat_id, contour="direct",
                                          used_key="calls", day_rows=day_rows,
                                          metric="llm_calls"),
            "tokens": await _limits_metric(pg, chat_id, contour="direct",
                                           used_key="tokens", day_rows=day_rows,
                                           metric="llm_tokens"),
        }
    except Exception:
        logger.warning("[oversight] key_budget limits failed | chat=%s",
                       chat_id, exc_info=True)
    try:
        limits["worker_budget"] = {
            "calls": await _limits_metric(pg, chat_id, contour="worker",
                                          used_key="calls", day_rows=day_rows,
                                          metric="llm_calls"),
            "tokens": await _limits_metric(pg, chat_id, contour="worker",
                                           used_key="tokens", day_rows=day_rows,
                                           metric="llm_tokens"),
        }
    except Exception:
        logger.warning("[oversight] worker_budget limits failed | chat=%s",
                       chat_id, exc_info=True)
    context: dict = {}
    for name, key, env_default, effective_default in CONTEXT_LIMIT_KEYS:
        cap = {"limit": int(effective_default), "unlimited": False,
               "source": "default"}
        try:
            value, source = await worker_settings.resolve_setting_with_source(
                key, chat_id=chat_id, default=env_default)
            state = budget_limits.context_state(value)
            if state == "unset":
                # D-6: `0`/None = «не задано» → показываем фактически
                # эффективный дефолт (не ложный 0), source='default'.
                value, source = effective_default, "default"
                state = budget_limits.context_state(value)
            cap = {
                "limit": int(value),
                "unlimited": state == "unlimited",
                "source": source,
            }
        except Exception:
            logger.warning("[oversight] context limit failed | chat=%s | "
                           "key=%s", chat_id, key, exc_info=True)
        context[name] = cap
    limits["context"] = context
    # D-2.6 (Low, ревью итерации 4): единый нормализованный fallback из
    # retention_policy (один источник истины) — при негативном
    # `STORAGE_DEFAULT` label не может стать «-1 дней».
    from services import retention_policy as retention_policy_srv
    fallback_days = retention_policy_srv.normalized_retention_default()
    storage = {"import_retention_days": fallback_days,
               "import_forever": fallback_days == 0,
               "source": "default",
               "label": "Вечно" if fallback_days == 0
                        else f"{fallback_days} дней"}
    try:
        value, source = await worker_settings.resolve_setting_with_source(
            STORAGE_KEY, chat_id=chat_id, default=STORAGE_DEFAULT)
        state = budget_limits.retention_state(value)
        if state == "invalid":
            # негатив невалиден → нормализованный глобальный дефолт (F7).
            logger.warning("[oversight] invalid retention override | chat=%s "
                           "— fallback на глобальный дефолт", chat_id)
            value, source = fallback_days, "default"
            state = budget_limits.retention_state(value)
        days = 0 if state == "eternal" else int(value)
        storage = {
            "import_retention_days": days,
            "import_forever": state == "eternal",
            "source": source,
            "label": "Вечно" if state == "eternal" else f"{days} дней",
        }
    except Exception:
        logger.warning("[oversight] storage limits failed | chat=%s",
                       chat_id, exc_info=True)
    limits["storage"] = storage
    return limits


async def build_summary(pg, sqlite_db=None) -> dict:
    """Сводка (кэш 60 с): {generated_at, chats: [ChatSummary...],
    errors: [...], global_budget: {...}}."""
    global _cache, _cache_ts
    now = time.monotonic()
    if _cache and (now - _cache_ts) < _SUMMARY_TTL:
        return dict(_cache)
    errors: list[dict] = []
    pool = _pool(pg)
    if pool is None:
        errors.append({"source": "pg", "code": "unavailable"})
        out = {"generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(), "chats": [], "errors": errors,
            "global_budget": await worker_budget.get_day_summary(pg)}
        _cache = out
        _cache_ts = now
        return dict(out)
    profiles = []
    rows = []
    admins = {}
    own = set()
    try:
        async with pool.acquire() as conn:
            profiles = await conn.fetch(PROFILE_COLS_SQL)
            admins_rows = await conn.fetch(ADMINS_COUNT_SQL)
            own_rows = await conn.fetch(OWN_KEYS_SQL)
        admins = {int(r["chat_id"]): int(r["c"]) for r in admins_rows}
        own = {int(r["chat_id"]) for r in own_rows}
    except Exception as exc:
        errors.append({"source": "pg", "code": str(type(exc).__name__)})
        logger.warning("[oversight] pg read failed", exc_info=True)
    activity = {}
    try:
        activity = await _activity_map(pg)
    except Exception:
        errors.append({"source": "sqlite", "code": "unavailable"})
    chats = []
    for row in profiles:
        chat_id = int(row["chat_id"])
        try:
            root = chat_params._load_chat_params(row.get("chat_params"))
            gates_opt_in = bool(row.get("gates_opt_in"))
            heavy = {}
            for feature in sorted(feature_gates.HEAVY_FEATURES):
                # R10.18-3: fallback = per-chat master (как у воркера) —
                # карточка «Тяжёлые» не расходится с фактическим поведением.
                fb = await feature_gates.master_fallback(chat_id, feature)
                heavy[feature] = await feature_gates.gates_enabled(
                    chat_id, feature, root=root, fallback=fb)
            permsoc_on = await permsoc.master_enabled(chat_id)
            allow_global = bool((root.get("keys") or {}).get(
                "allow_global", True))
            if chat_id in own:
                key_status, key_last4 = "own", None
                try:
                    val = await chat_keys.get_chat_key(
                        pg, chat_id, "keys.llm_api_key")
                    key_last4 = str(val)[-4:] if val else None
                except Exception:
                    key_last4 = None
            elif not allow_global:
                key_status, key_last4 = "forbidden", None
            else:
                key_status, key_last4 = "global", None
            title = await _chat_title(chat_id)
            budget = None
            day_rows = await worker_budget.get_usage(
                pg, scope=f"chat:{chat_id}")
            if day_rows:
                def _pair(m):
                    hits = [r for r in day_rows if r["metric"] == m]
                    return {"used": hits[0]["used"] if hits else 0,
                            "limit": hits[0]["limit"] if hits else 0}
                budget = {"calls": _pair("llm_calls"),
                          "tokens": _pair("llm_tokens")}
            # F3 (ADR-1019-8 D6): аддитивный `limits` — оба контура +
            # контекст + хранение; каждый источник fail-open.
            try:
                limits = await _limits_block(pg, chat_id, day_rows)
            except Exception:
                logger.warning("[oversight] limits block failed | chat=%s",
                               chat_id, exc_info=True)
                limits = {}
            chats.append({
                "chat_id": chat_id,
                "title": title,
                "is_active": bool(row["is_active"]),
                "gates_opt_in": gates_opt_in,
                "heavy": heavy,
                "permsoc": permsoc_on,
                "key_status": key_status,
                "key_last4": key_last4,
                "allow_global": allow_global,
                "admins_count": admins.get(chat_id, 0),
                "last_active_ts": activity.get(chat_id),
                "budget": budget,
                "limits": limits,
                "updated_at": chat_params._iso(row.get("updated_at")),
            })
        except Exception as exc:
            errors.append({"source": "chat", "code": str(type(exc).__name__),
                           "chat_id": chat_id})
    out = {
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "chats": chats,
        "errors": errors,
        "global_budget": await worker_budget.get_day_summary(pg),
    }
    _cache = out
    _cache_ts = now
    return dict(out)


async def get_chat_details(pg, chat_id: int, store=None) -> dict:
    """Детали чата: summary + админы (store) + 5 записей истории."""
    summary = await build_summary(pg)
    entry = None
    for cand in summary["chats"]:
        if int(cand["chat_id"]) == int(chat_id):
            entry = cand
            break
    if entry is None:
        return None
    out = dict(entry)
    out["admins"] = []
    out["history"] = []
    try:
        if store is not None:
            out["admins"] = await store.list_chat_admins(int(chat_id))
            out["history"] = await store.history(int(chat_id),
                                                 _HISTORY_LIMIT)
    except Exception:
        logger.warning("[oversight] details enrich failed | chat=%s",
                       chat_id, exc_info=True)
    return out
