"""SELF-DIAG-01 D2 — онлайн-проверка «админ именно этого Telegram-чата».

Единственный источник истины о роли `chat_admin` — Bot API `getChatMember`
(`services/telegram_role_check.check_chat_admin`). Никакие текстовые
заявления, username, должности, пересланные сообщения или Reply не
используются: проверяются только числовой `from_user.id` и `chat.id`.

Контракт (owner amendment 2026-11-09 §2, ТЗ §7.1):
  * статусы Telegram `administrator`/`creator` → `chat_admin`;
  * прочие удостоверяемые статусы → `member`;
  * нет проверяемой личности (anonymous_admin/sender_chat) → `unverified`;
  * нет прав у бота / ошибка API / нет chat-скоупа → `unverified`
    (отказ ТОЛЬКО в protected readback, публичная диагностика остаётся);
  * DM (`chat_id > 0`) — понятия «админ чата» нет → `member`.

Проверка вызывается в момент авторизованного запроса. TTL-кэш (60 c) —
оптимизация для быстрых публичных путей; авторитетная перепроверка перед
публикацией защищённого результата идёт с `fresh=True` (реальный вызов API),
поэтому старый TTL не может продлить действие отозванного админства.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Telegram-статусы, дающие роль `chat_admin` (owner amendment: только они).
ADMIN_STATUSES: frozenset[str] = frozenset({"administrator", "creator"})

#: TTL кэша успешных ответов Telegram (сек). Инвалидация по изменениям
#: членства — оптимизация, а не замена онлайн-проверке.
CACHE_TTL_SECONDS = 60.0
#: Неуспех (ошибка API) не кэшируем дольше короткого окна: нужен честный
#: повтор, чтобы `unverified` не залипал.
ERROR_TTL_SECONDS = 5.0

STATUS_CHAT_ADMIN = "chat_admin"
STATUS_MEMBER = "member"
STATUS_UNVERIFIED = "unverified"

SOURCE_TELEGRAM_API = "telegram_api"
SOURCE_CACHE = "cache"
SOURCE_DM_SCOPE = "dm_scope"
SOURCE_NO_IDENTITY = "no_identity"
SOURCE_NO_CHAT_SCOPE = "no_chat_scope"
SOURCE_BOT_UNAVAILABLE = "bot_unavailable"
SOURCE_ERROR = "telegram_api_error"

_CACHE: dict[tuple[int, int], tuple[float, "RoleCheck"]] = {}


@dataclass(frozen=True)
class RoleCheck:
    """Результат проверки членства/админства в конкретном чате."""

    status: str                 # chat_admin | member | unverified
    telegram_status: str        # сырой статус Telegram ('' — неизвестен)
    source: str                 # откуда взято (см. SOURCE_*)
    reason: str                 # машинный код причины
    chat_id: int | None
    telegram_id: int | None

    @property
    def is_admin(self) -> bool:
        return self.status == STATUS_CHAT_ADMIN

    @property
    def verified(self) -> bool:
        """Личность и членство подтверждены самим Telegram."""
        return self.status in (STATUS_CHAT_ADMIN, STATUS_MEMBER)


def reset_cache() -> None:
    """Полный сброс кэша проверок (тесты/рестарт внешнего состояния)."""
    _CACHE.clear()


def invalidate(chat_id: int | None = None,
               telegram_id: int | None = None) -> None:
    """Точечная инвалидация по событиям членства (ChatMemberUpdated и т.п.).

    Не заменяет онлайн-проверку: используется как ускорение и для явного
    отзыва в пределах процесса.
    """
    for key in list(_CACHE):
        if chat_id is not None and key[0] != chat_id:
            continue
        if telegram_id is not None and key[1] != telegram_id:
            continue
        _CACHE.pop(key, None)


def cached_check(chat_id: int, telegram_id: int) -> RoleCheck | None:
    """Последний известный результат (без сети) — для объяснений в админке."""
    entry = _CACHE.get((chat_id, telegram_id))
    return entry[1] if entry is not None else None


async def check_chat_admin(bot, chat_id: int | None, telegram_id: int | None,
                           *, fresh: bool = False) -> RoleCheck:
    """Проверить статус `telegram_id` в `chat_id` через Bot API.

    Никогда не бросает: любая ошибка → `unverified` + машинный reason.
    `fresh=True` — игнорировать кэш (перепроверка перед публикацией).
    """
    if telegram_id is None:
        return RoleCheck(STATUS_UNVERIFIED, "", SOURCE_NO_IDENTITY,
                         "anonymous_sender", chat_id, None)
    if chat_id is None:
        # Внутренний/непривязанный к чату вызов: админство чата не заявляется.
        return RoleCheck(STATUS_UNVERIFIED, "", SOURCE_NO_CHAT_SCOPE,
                         "no_chat_scope", None, int(telegram_id))
    chat_id = int(chat_id)
    telegram_id = int(telegram_id)
    if chat_id > 0:
        # Личный диалог: администраторов чата не существует.
        return RoleCheck(STATUS_MEMBER, "private", SOURCE_DM_SCOPE,
                         "dm_scope", chat_id, telegram_id)

    key = (chat_id, telegram_id)
    if not fresh:
        entry = _CACHE.get(key)
        if entry is not None and entry[0] > time.monotonic():
            cached = entry[1]
            # Кэшированный успех помечаем источником «cache» (наблюдаемость),
            # сам статус не меняется.
            return RoleCheck(cached.status, cached.telegram_status,
                             SOURCE_CACHE, cached.reason, chat_id, telegram_id)

    if bot is None:
        return _store(chat_id, telegram_id,
                      RoleCheck(STATUS_UNVERIFIED, "", SOURCE_BOT_UNAVAILABLE,
                                "bot_unavailable", chat_id, telegram_id))

    try:
        member = await bot.get_chat_member(chat_id=chat_id,
                                           user_id=telegram_id)
    except Exception as exc:                      # noqa: BLE001 — «никогда не бросает»
        logger.warning("[diag-role] getChatMember failed | chat=%s user=%s | "
                       "error=%s", chat_id, telegram_id, type(exc).__name__)
        return _store(chat_id, telegram_id,
                      RoleCheck(STATUS_UNVERIFIED, "", SOURCE_ERROR,
                                "telegram_api_error", chat_id, telegram_id),
                      ttl=ERROR_TTL_SECONDS)

    raw = str(getattr(member, "status", "") or "")
    if raw in ADMIN_STATUSES:
        return _store(chat_id, telegram_id,
                      RoleCheck(STATUS_CHAT_ADMIN, raw, SOURCE_TELEGRAM_API,
                                "telegram_admin_status", chat_id, telegram_id))
    return _store(chat_id, telegram_id,
                  RoleCheck(STATUS_MEMBER, raw, SOURCE_TELEGRAM_API,
                            "telegram_member_status", chat_id, telegram_id))


def _store(chat_id: int, telegram_id: int, value: RoleCheck, *,
           ttl: float = CACHE_TTL_SECONDS) -> RoleCheck:
    _CACHE[(chat_id, telegram_id)] = (time.monotonic() + ttl, value)
    return value
