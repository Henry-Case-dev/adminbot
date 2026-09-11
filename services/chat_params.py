"""Раунд 10 (multi-chat-rbac-byok, F-7 §4) — слой per-chat параметров.

`chat_profiles.chat_params` JSONB (v-1-лейаут):
    {"v": 1,
     "overrides": {"<pg_key>": <значение>},   # per_chat=True ключи
     "gates": {"dream": false, ...},          # F-9/F-10 (booleans)
     "keys": {"allow_global": true},          # мета; секреты — chat_keys
     "perm_overrides": {"<pg_key>": {...}},    # чат-скоуп min-ролей
     "meta": {"updated_by": <id>, "note": ""}}

Резолв (spec §4.5): async get_chat_param → chat_params.overrides (каст по
каталогу!) → hot.get (глобал/дефолт). Прямых обращений к ConfigCache — НЕТ
(hot.get не изменяется — §1.2-8). Кэш — паттерн ChatLoreCache (TTL 120 с +
NOTIFY-инвалидация pg_notify('chat_params_updated')), fail-open {}.

Конфликт-протокол (Q4): ОДИН optimistic-токен на профиль — updated_at
chat_profiles; `expected_updated_at` не совпал → ChatParamsConflict →
409 {code:'conflict', current_updated_at} (прецедент ChatLoreConflict).
"""
import asyncio
import datetime
import json
import logging
import math
import time

from services.param_catalog import get_by_pg_key, normalize_value

logger = logging.getLogger(__name__)

# F-14 (dm-user-settings, spec §1): DM-скоуп = chat_profiles/chat_params с
# chat_id = user.id; группы — отрицательные id, лички — положительные.
def is_dm_scope(chat_id) -> bool:
    """Единственный идентификатор DM-скоупа: положительный chat_id = ЛС."""
    return chat_id is not None and int(chat_id) > 0

_NOTIFY_CHANNEL = "chat_params_updated"
_CACHE_TTL = 120.0
_HISTORY_FIELD = "chat_params"

PROFILE_COLS = (
    "chat_id", "updated_at", "chat_params", "gates_opt_in",
)


class ChatParamsConflict(Exception):
    """Рассинхрон optimistic-метки (0 строк) либо профиля нет вовсе.

    current_updated_at — ISO-строка или None (профиля нет) → API 409.
    """

    def __init__(self, chat_id: int, current_updated_at: str | None):
        self.chat_id = chat_id
        self.current_updated_at = current_updated_at
        super().__init__(
            f"chat_params conflict: chat_id={chat_id} "
            f"current_updated_at={current_updated_at}")


SELECT_PROFILE_SQL = (
    "SELECT chat_id, updated_at, chat_params, gates_opt_in "
    "FROM chat_profiles WHERE chat_id = $1"
)
UPDATE_PARAMS_LOCKED_SQL = (
    "UPDATE chat_profiles SET chat_params = $2::jsonb, updated_at = now() "
    "WHERE chat_id = $1 AND updated_at = $3::timestamptz RETURNING *"
)
UPDATE_PARAMS_SQL = (
    "UPDATE chat_profiles SET chat_params = $2::jsonb, updated_at = now() "
    "WHERE chat_id = $1 RETURNING *"
)
INSERT_HISTORY_SQL = (
    "INSERT INTO chat_lore_history (chat_id, field, changed_by, old_value, "
    "new_value) VALUES ($1, $2, $3, $4, $5)"
)
NOTIFY_SQL = "SELECT pg_notify('chat_params_updated', $1)"
UPSERT_GATES_OPT_IN_SQL = (
    "UPDATE chat_profiles SET gates_opt_in = true, updated_at = now() "
    "WHERE chat_id = $1"
)
# F-14 (§3.1): ленивое создание профиля скоупа перед ПЕРВОЙ записью —
# паттерн chat_lore_store.py:44-47, идемпотентный (INSERT ON CONFLICT).
INSERT_SCOPE_PROFILE_SQL = (
    "INSERT INTO chat_profiles "
    "(chat_id, auto_enabled, is_active, chat_params, gates_opt_in) "
    "VALUES ($1, $2, $3, $4::jsonb, $5) ON CONFLICT (chat_id) DO NOTHING"
)


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _parse_ts(value):
    """ISO-строка клиента → datetime для asyncpg-параметра timestamptz."""
    if value is None or not isinstance(value, str):
        return value
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_chat_params(value) -> dict:
    """JSONB chat_params → dict (мусор/строка → {})."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except ValueError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _root_with_meta(root: dict) -> dict:
    """Гарантия v-1-лейаута (v/overrides/gates/keys/perm_overrides/meta)."""
    out = {
        "v": 1,
        "overrides": dict(root.get("overrides") or {}),
        "gates": dict(root.get("gates") or {}),
        "keys": dict(root.get("keys") or {}),
        "perm_overrides": dict(root.get("perm_overrides") or {}),
        "meta": dict(root.get("meta") or {}),
    }
    return out


class ChatParamsCache:
    """Per-chat кэш chat_params (паттерн ChatLoreCache, T-774): load-on-
    demand, TTL 120 с, инвалидация по NOTIFY chat_params_updated; fail-open
    {} (PG down → слой пуст, резолв уходит на глобал/дефолт)."""

    def __init__(self, pg=None):
        self._pg = pg
        self._lock = asyncio.Lock()
        self._items: dict[int, tuple[float, dict]] = {}
        self._ttl = _CACHE_TTL

    def set_pg(self, pg) -> None:
        self._pg = pg

    async def invalidate_chat(self, chat_id: int) -> None:
        self._items.pop(chat_id, None)

    def _pool(self):
        pool = getattr(self._pg, "pool", None) if self._pg is not None else None
        return pool

    async def get_chat_params(self, chat_id: int) -> dict:
        """Сырой chat_params чата (root-лейаут) либо {} — fail-open."""
        root, _ = await self.get_chat_params_full(chat_id)
        return root

    async def get_chat_params_full(self, chat_id: int) -> tuple[dict, str | None]:
        """(root, updated_at профиля) — updated_at из профиля (optimistic-
        метка единого конфликт-протокола spec §4.3)."""
        now = time.monotonic()
        if chat_id in self._items:
            ts, root, updated_at = self._items[chat_id]
            if (now - ts) < self._ttl:
                return root, updated_at
        pool = self._pool()
        if pool is None:
            return {}, None
        root, updated_at = {}, None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(SELECT_PROFILE_SQL, chat_id)
            if row is not None:
                root = _load_chat_params(row.get("chat_params"))
                updated_at = _iso(row.get("updated_at"))
        except Exception:
            logger.warning(
                "[chat_params] cache load failed — fail-open | chat=%s",
                chat_id, exc_info=True)
            return {}, None
        async with self._lock:
            self._items[chat_id] = (time.monotonic(), root, updated_at)
        return root, updated_at


async def get_chat_updated_at(chat_id: int) -> str | None:
    """updated_at профиля чата (optimistic-метка; None — нет/недоступен)."""
    cache = _chat_params_cache
    if cache is None:
        return None
    try:
        _, updated_at = await cache.get_chat_params_full(chat_id)
    except Exception:
        return None
    return updated_at


_chat_params_cache = None   # runtime-глобал (DI из bot.py; тесты подменяют)


def set_chat_params_cache(cache: ChatParamsCache | None) -> None:
    global _chat_params_cache
    _chat_params_cache = cache


def get_chat_params_cache() -> ChatParamsCache | None:
    return _chat_params_cache


# ── hot_chat: async-резолв (F-9/F-10-гейты; БЕЗ ConfigCache) ────────────────

async def get_chat_param(chat_id: int, key: str, default=None) -> object:
    """async-резолв: overrides (каст по каталогу) → hot.get → default."""
    from services import hot_config as hot
    cache = _chat_params_cache
    root = {}
    if cache is not None:
        root = await cache.get_chat_params(chat_id)
    return _resolve_from_root(root, key, default)


def _resolve_from_root(root: dict, key: str, default=None) -> object:
    """Спец §4.5: chat_params.overrides (cast!!) → hot.get → default.
    Раунд 10.4 (G-2): после каста — проверка типа + math.isfinite для float
    (мусор/NaN/inf → hot.get-фолбэк; AC-G4; валидные — без изменений)."""
    from services import hot_config as hot
    overrides = root.get("overrides") or {}
    try:
        value = overrides.get(key, hot.get(key, default))
    except Exception:
        logger.warning("[chat_params] resolve failed — global | key=%s", key)
        return hot.get(key, default)
    spec = get_by_pg_key(key)
    if spec is not None:
        try:
            casted = normalize_value(key, value)
            if _cast_type_ok(spec.type, casted) \
                    and not (spec.type == "float" and isinstance(casted, float)
                             and not math.isfinite(casted)):
                return casted
            # мусор/NaN/inf → fallback (hot.get → default)
            return hot.get(key, default)
        except Exception:
            return hot.get(key, default)
    return value
async def get_all_chat_params(chat_id: int) -> dict:
    """Полный root-лейаут чата (для GET /api/config X-Chat-Id)."""
    cache = _chat_params_cache
    if cache is None:
        return {}
    root = await cache.get_chat_params(chat_id)
    return _root_with_meta(root)


async def set_chat_params(chat_id: int, patch: dict, *, changed_by=None,
                          expected_updated_at: str | None = None,
                          pg=None,
                          # История при gates/keys-записи — отдельные fields
                          history_field: str = _HISTORY_FIELD,
                          record_history: bool = True,
                          ) -> dict:
    """Атомарная запись патча в chat_params (spec §4.3).

    Одна транзакция: UPDATE (optimistic при expected_updated_at) + история
    field='chat_params' (+ NOTIFY). 0 строк → ChatParamsConflict(chat_id,
    current_updated_at). Частичный успех исключён. Возвращает новый root."""
    from services.chat_lore_store import (
        ChatLorePgUnavailable as _PgUnavailable,
    )
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        raise _PgUnavailable("PostgreSQL недоступен (пул отсутствует)")
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(SELECT_PROFILE_SQL, chat_id)
            if row is None:
                raise ChatParamsConflict(chat_id, None)
            old_raw = _load_chat_params(row.get("chat_params"))
            old_root = _root_with_meta(old_raw)
            new_root = _root_with_meta(old_root)
            for ns in ("overrides", "gates", "keys", "perm_overrides",
                       "meta"):
                if ns in patch and isinstance(patch[ns], dict):
                    new_root[ns] = dict(patch[ns])
            new_root["v"] = patch.get("v", 1)
            if expected_updated_at is not None:
                sql = UPDATE_PARAMS_LOCKED_SQL
                args = (chat_id, json.dumps(new_root),
                        _parse_ts(expected_updated_at))
            else:
                sql = UPDATE_PARAMS_SQL
                args = (chat_id, json.dumps(new_root))
            updated = await conn.fetchrow(sql, *args)
            if updated is None:
                current = await conn.fetchrow(SELECT_PROFILE_SQL, chat_id)
                raise ChatParamsConflict(
                    chat_id, _iso(current["updated_at"]) if current else None)
            old_json = json.dumps(old_root, ensure_ascii=False,
                                  sort_keys=True)
            new_json = json.dumps(new_root, ensure_ascii=False, sort_keys=True)
            if record_history and old_json != new_json:
                await conn.execute(
                    INSERT_HISTORY_SQL, chat_id, history_field, changed_by,
                    old_json, new_json)
            await conn.execute(NOTIFY_SQL, str(chat_id))
    cache = _chat_params_cache
    if cache is not None:
        try:
            await cache.invalidate_chat(chat_id)
        except Exception:
            pass
    return _root_with_meta(new_root)


async def set_gates_opt_in(chat_id: int, pg=None) -> None:
    """gates_opt_in=true (F-10 auto_opt_in; история — одна на гейт-запись)."""
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        raise ChatLorePgUnavailable("PostgreSQL недоступен (пул отсутствует)")
    async with pool.acquire() as conn:
        await conn.execute(UPSERT_GATES_OPT_IN_SQL, chat_id)


# ═══ F-14 (dm-user-settings, spec §3.1/§4.1) — DM-скоуп ══════════════════════

# 10.10 (ADR-1010-1): единый источник «тяжёлые модули OFF» для ЛС —
# и дефолт новых ЛС (ensure_scope_profile), и data-скрипт используют эти
# константы. Групповые дефолты НЕ трогаются.
_DM_DISABLED_GATES = {"dream": False, "nostalgia": False}
_DM_DISABLED_OVERRIDES = {
    "memory.dream_enabled": False,
    "memory.nostalgia_enabled": False,
    "flags.summary_enabled": False,
    "flags.chat_running_summary_enabled": False,
}


async def ensure_scope_profile(chat_id: int, *, dm: bool, pg=None) -> bool:
    """F-14 (§3.1): ленивое создание профиля скоупа (INSERT ON CONFLICT DO
    NOTHING — паттерн chat_lore_store.py:44-47). Вызывается ПЕРЕД первой
    записью в DM-скоупе (иначе set_chat_params даст мусорный
    ChatParamsConflict(chat_id, None) «профиля нет»).

    DM (dm=True): auto_enabled=false (LoreWorker не тронет — двойной guard
    с SQL-фильтрами chat_id < 0), is_active=true, chat_params =
    v-1-лейаут с DM-дефолтами тяжёлых модулей OFF (10.10, ADR-1010-1:
    gates dream/nostalgia=false + 4 override=false), gates_opt_in=false.
    dm=False — INSERT дефолтного профиля (как ensure_profile чат-лора).
    Идемпотентен: вставка → True; повтор (или нет пула) → False."""
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        return False
    if dm:
        params = json.dumps(_root_with_meta({
            "gates": dict(_DM_DISABLED_GATES),
            "overrides": dict(_DM_DISABLED_OVERRIDES),
        }))
        args = (chat_id, False, True, params, False)
    else:
        from services.chat_lore_store import INSERT_DEFAULT_PROFILE
        async with pool.acquire() as conn:
            res = await conn.execute(INSERT_DEFAULT_PROFILE, chat_id)
        return res.split()[-1] != "0"
    try:
        async with pool.acquire() as conn:
            res = await conn.execute(INSERT_SCOPE_PROFILE_SQL, *args)
        return res.split()[-1] != "0"
    except Exception:
        logger.warning(
            "[chat_params] ensure_scope_profile failed — idempotent retry "
            "на следующей записи | chat=%s dm=%s", chat_id, dm, exc_info=True)
        return False


async def get_chat_param_defaulted(chat_id: int, key: str,
                                   fallback=None) -> object:
    """F-14 (§4.1): резолв ТОЛЬКО из override'ов своего скоупа — БЕЗ
    горячего global-фолбэка hot.get. Ключ ЯВНО присутствует в
    chat_params.overrides → каст по каталогу (normalize_value; тип не
    сошёлся/мусор → fallback); иначе — НЕМЕДЛЕННО fallback."""
    cache = _chat_params_cache
    root = {}
    if cache is not None:
        try:
            root = await cache.get_chat_params(chat_id)
        except Exception:
            root = {}
    overrides = root.get("overrides") or {}
    if key not in overrides:
        return fallback
    try:
        value = normalize_value(key, overrides[key])
        spec = get_by_pg_key(key)
        if spec is not None and not _cast_type_ok(spec.type, value):
            return fallback          # мусор (не кастуется к типу) → fallback
        return value
    except Exception:
        return fallback


def _cast_type_ok(spec_type: str, value) -> bool:
    """Проверка результата normalize_value по типу каталога (мусор → False)."""
    if spec_type == "bool":
        return isinstance(value, bool)
    if spec_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if spec_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if spec_type == "str":
        return isinstance(value, str)
    return True                       # json/прочие — каталог сам решит


async def chat_summary_enabled(chat_id: int) -> bool:
    """F-14 (§4.1): гейт бегущего конспекта (S1 summary_memory /
    S2 direct_chat_service).

    * группа (<0): hot.get('flags.chat_running_summary_enabled', settings…)
      — байт-в-байт старое поведение;
    * ЛС (>0): override своего ЛС → cast → False; глобальный ON НЕ
      наследуется (единственное исключение из наследования; пустой
      профиль → False даже при глобальном ON)."""
    if is_dm_scope(chat_id):
        return bool(await get_chat_param_defaulted(
            chat_id, "flags.chat_running_summary_enabled", False))
    from services import hot_config as hot
    from config.settings import settings
    return bool(hot.get("flags.chat_running_summary_enabled",
                        settings.CHAT_RUNNING_SUMMARY_ENABLED))
