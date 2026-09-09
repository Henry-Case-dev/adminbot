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
from services import chat_keys, chat_params, feature_gates, permsoc, worker_budget

logger = logging.getLogger(__name__)

_SUMMARY_TTL = 60.0
_TITLE_TTL = 600.0
_ACTIVITY_TTL = 120.0
_HISTORY_LIMIT = 5

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
                heavy[feature] = await feature_gates.gates_enabled(
                    chat_id, feature, root=root)
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
