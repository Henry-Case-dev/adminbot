"""Раунд 10 (multi-chat-rbac-byok, F-7 §5) — BYOK: ключи чатов.

`chat_keys (chat_id, key_name PK-часть, key_value, key_hint)`. Whitelist
key_name — ТОЛЬКО 'keys.llm_api_key' (fallback и embed-ключи строго
глобальные — §5.1-правка @Architect T-843). R17: сырые значения отдаются
ТОЛЬКО сервисам (llm_client) — по API никогда (только mask
{key_name?, configured, last4}). Аудит записи/удаления — chat_lore_history
field='chat_keys', changed_by.

`mask_key_info(key_name, value)` — ЕДИНАЯ маска: {"key_name": str,
"configured": bool, "last4": str|None} (изменение контракта _mask_secret —
F-7 §5.2: новая маска mask_chat_key_info).
"""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BYOK_KEYS_WHITELIST: frozenset[str] = frozenset({"keys.llm_api_key"})
# F11 (10.24, ADR-1024-12 D2): ГЛОБАЛЬНЫЕ секреты-провайдеры — сохраняются в
# глобальный слой (тем же `cache.set`, что читает image_generation), НЕ в
# `chat_keys`. Per-chat image-ключ сознательно НЕ добавляем (backend его не
# резолвит → «ручка без эффекта»). BYOK_KEYS_WHITELIST не расширяется.
GLOBAL_SECRET_KEYS: frozenset[str] = frozenset({"keys.image_api_key"})
# Sentinel chat_id для аудита глобального секрета: реальный Telegram-chat_id
# не бывает 0; `chat_lore_history.field='chat_keys'` переиспользуем (Δ DDL = 0),
# значения — только '***' (R17).
GLOBAL_AUDIT_CHAT_ID = 0
_HISTORY_FIELD = "chat_keys"

SELECT_KEY_SQL = (
    "SELECT chat_id, key_name, key_value, key_hint, updated_at "
    "FROM chat_keys WHERE chat_id = $1 AND key_name = $2"
)
INSERT_KEY_SQL = (
    "INSERT INTO chat_keys (chat_id, key_name, key_value, key_hint) "
    "VALUES ($1, $2, $3, $4) "
    "ON CONFLICT (chat_id, key_name) DO UPDATE "
    "SET key_value = EXCLUDED.key_value, key_hint = EXCLUDED.key_hint, "
    "updated_at = now()"
)
DELETE_KEY_SQL = (
    "DELETE FROM chat_keys WHERE chat_id = $1 AND key_name = $2"
)
INSERT_HISTORY_SQL = (
    "INSERT INTO chat_lore_history (chat_id, field, changed_by, old_value, "
    "new_value) VALUES ($1, $2, $3, $4, $5)"
)


def is_whitelisted(key_name: str) -> bool:
    return key_name in BYOK_KEYS_WHITELIST


def is_global_secret(key_name: str) -> bool:
    """F11 (ADR-1024-12 D2): True — ключ из allowlist ГЛОБАЛЬНЫХ секретов И
    рубильник `BYOK_IMAGE_KEY_ENABLED` включён. OFF → global-ветка отключена
    (allowlist пуст, прежнее поведение)."""
    from config.settings import settings
    if not getattr(settings, "BYOK_IMAGE_KEY_ENABLED", True):
        return False
    return key_name in GLOBAL_SECRET_KEYS


def mask_key_info(key_name: str, value: str | None) -> dict:
    """Единая маска собственного ключа чата (никогда raw, R17)."""
    configured = bool(value)
    return {
        "key_name": key_name,
        "configured": configured,
        "last4": (str(value)[-4:] if configured else None),
    }


def mask_chat_key_info(key_name: str, value: str | None) -> dict:
    """Спец-имя маски (F-7 §5.2: mask_chat_key_info) — алиас mask_key_info."""
    return mask_key_info(key_name, value)


def _pool(pg):
    return getattr(pg, "pool", None) if pg is not None else None


async def get_chat_key(pg, chat_id: int, key_name: str) -> str | None:
    """Сырое значение ТОЛЬКО для сервисов (llm_client); None — нет."""
    pool = _pool(pg)
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_KEY_SQL, chat_id, key_name)
    except Exception:
        logger.warning("[chat_keys] read failed — fail-open | chat=%s key=%s",
                       chat_id, key_name, exc_info=True)
        return None
    return row["key_value"] if row is not None else None


async def set_chat_key(pg, chat_id: int, key_name: str, value: str,
                       changed_by: int | None = None,
                       record_history: bool = True) -> dict:
    """Insert-or-replace + история field='chat_keys'. Возвращает маску."""
    if not is_whitelisted(key_name):
        raise ValueError(f"ключ не в whitelist BYOK: {key_name}")
    pool = _pool(pg)
    if pool is None:
        raise RuntimeError("PostgreSQL недоступен (пул отсутствует)")
    old_value = None
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(SELECT_KEY_SQL, chat_id, key_name)
            if row is not None:
                old_value = row["key_value"]
            if record_history and (old_value or "") != str(value):
                await conn.execute(
                    INSERT_HISTORY_SQL, chat_id, _HISTORY_FIELD, changed_by,
                    old_value or "", "***" if value else "")
            await conn.execute(INSERT_KEY_SQL, chat_id, key_name, str(value),
                               "")
    logger.info("[chat_keys] key upsert | chat=%s key=%s by=%s (mask)",
                chat_id, key_name, changed_by)
    return mask_key_info(key_name, value)


async def delete_chat_key(pg, chat_id: int, key_name: str,
                          changed_by: int | None = None) -> bool:
    """Удаление ключа (без мягкой пометки — insert-or-replace, §5.1)."""
    if not is_whitelisted(key_name):
        raise ValueError(f"ключ не в whitelist BYOK: {key_name}")
    pool = _pool(pg)
    if pool is None:
        raise RuntimeError("PostgreSQL недоступен (пул отсутствует)")
    removed = False
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(SELECT_KEY_SQL, chat_id, key_name)
            if row is not None:
                await conn.execute(INSERT_HISTORY_SQL, chat_id,
                                   _HISTORY_FIELD, changed_by,
                                   "***", "")
                deleted = await conn.execute(DELETE_KEY_SQL, chat_id,
                                             key_name)
                removed = ("DELETE" in (deleted or "")
                           and deleted.split()[-1] != "0")
    logger.info("[chat_keys] key delete | chat=%s key=%s by=%s",
                chat_id, key_name, changed_by)
    return removed


async def list_own_keys(pg, chat_id: int) -> list[dict]:
    """Маски СВОИХ ключей чата (для GET /api/config/keys/own)."""
    pool = _pool(pg)
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key_name, key_value FROM chat_keys "
                "WHERE chat_id = $1 ORDER BY key_name", chat_id)
    except Exception:
        logger.warning("[chat_keys] list failed — fail-open | chat=%s",
                       chat_id, exc_info=True)
        return []
    return [mask_key_info(r["key_name"], r["key_value"]) for r in rows]


async def record_global_secret_audit(pg, key_name: str, changed_by: int | None,
                                     old_value, new_value) -> bool:
    """F11 (ADR-1024-12): аудит изменения ГЛОБАЛЬНОГО секрета — та же таблица
    `chat_lore_history` (sentinel-chat, field='chat_keys', Δ DDL = 0), значения
    ТОЛЬКО '***' (R17: raw не пишем). Fail-open: ошибка аудита не роняет save."""
    pool = _pool(pg)
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(INSERT_HISTORY_SQL, GLOBAL_AUDIT_CHAT_ID,
                               _HISTORY_FIELD, changed_by,
                               "***" if old_value else "",
                               "***" if new_value else "")
    except Exception:
        logger.warning("[chat_keys] global audit failed — fail-open | key=%s",
                       key_name, exc_info=True)
        return False
    return True


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
