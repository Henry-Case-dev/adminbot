"""
F5v2 — War Words Alert Redesign (Epic 10).

Two handlers on a single router:
  1. keyword_handler: Slava's own messages containing war keywords → random reply
  2. channel_repost_handler: any repost from target channels → random reply

Both use the same random reply pool and reply via reply_to mechanism.

Architecture:
  - Router registered at position 4b between dead_page_router and slavik_router.
  - Filter fix (T-057): WarWordFilter now checks message.caption in addition to message.text.
  - Channel detection follows the dead_page_trigger.py pattern (F.forward_origin + MessageOriginChannel).
"""
import logging
import random

from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import MessageOriginChannel

from config.settings import settings
from services import hot_config as hot
from filters.target_channel import TargetChannelFilter
from filters.user_id import UserIdFilter
from filters.danger_word import DangerWordFilter

logger = logging.getLogger(__name__)

war_alert_router = Router(name="war_alert")

# ── Random reply pool (extensible via .env) ──

_DEFAULT_WAR_REPLIES: list[str] = [
    "потрясись",
    "повизжи",
    "прячься под шконку быстрее",
    "закрой ушки и считай до десяти",
    "поплачь",
]


def _load_replies() -> list[str]:
    """Load war replies from env or use defaults. Supports comma-separated env var."""
    env_val = hot.get("reactions.war_replies", settings.WAR_REPLIES)
    if env_val:
        parts = [r.strip() for r in env_val.split(",") if r.strip()]
        if parts:
            logger.info("War Alert: %d custom reply phrases loaded from env", len(parts))
            return parts
    logger.info("War Alert: using %d default reply phrases", len(_DEFAULT_WAR_REPLIES))
    return list(_DEFAULT_WAR_REPLIES)


# P2 (ревью миграции): WAR_REPLIES загружается в setup_war_alert (on_startup,
# ПОСЛЕ set_config_cache) — live-at-startup; здесь — дефолт до setup.
WAR_REPLIES: list[str] = list(_DEFAULT_WAR_REPLIES)


def setup_war_alert() -> None:
    """Initialize war alert module. Called from bot.on_startup() (после
    set_config_cache — значения из админки применяются при старте)."""
    global WAR_REPLIES
    WAR_REPLIES = _load_replies()
    logger.info(
        "War Alert initialized: %d replies, %d channel IDs (%s), %d channel usernames (%s)",
        len(WAR_REPLIES),
        len(_target_channel_ids_set),
        _target_channel_ids_set,
        len(_target_channel_usernames_set),
        _target_channel_usernames_set,
    )


# ── Channel match helpers ──

def _parse_int_list(raw) -> list[int]:
    """Parse comma-separated list of integers. N6: list/tuple-значение из кэша
    тоже принимается (join по запятой)."""
    if not raw:
        return []
    if not isinstance(raw, str):
        raw = ",".join(str(x) for x in raw)
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                result.append(int(part))
            except ValueError:
                logger.warning("War Alert: invalid channel ID in config: %r", part)
    return result


def _parse_str_list(raw) -> list[str]:
    """Parse comma-separated list of strings. N6: list/tuple-значение тоже."""
    if not raw:
        return []
    if not isinstance(raw, str):
        raw = ",".join(str(x) for x in raw)
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


# Module-level target channel sets for TargetChannelFilter.
# N3 (ЧЕСТНО): значение из админки НЕ применяется без рефакторинга фильтров —
# декораторы (TargetChannelFilter ниже, UserIdFilter в war_keyword_handler)
# захватывают эти объекты при импорте; на КАЖДОМ старте здесь — фолбек
# settings (кэш ещё не засеян). Live-применение требует переделки фильтров
# на динамическое чтение hot.get (зафиксировано в отчёте Builder).
_target_channel_ids_set: set[int] = set(_parse_int_list(hot.get("reactions.war_channel_ids", settings.WAR_CHANNEL_IDS)))
_target_channel_usernames_set: set[str] = set(_parse_str_list(hot.get("reactions.war_channel_usernames", settings.WAR_CHANNEL_USERNAMES)))


# ── Handler 1: Slava's own (non-forwarded) keywords ──

@war_alert_router.message(
    # N3 (ЧЕСТНО): импорт-time декоратор — значение из админки НЕ применяется
    # без рефакторинга фильтра; на каждом старте — фолбек settings.
    UserIdFilter(hot.get("reactions.slavik_user_id", settings.SLAVIK_USER_ID)),
    DangerWordFilter(),
)
async def war_keyword_handler(message: types.Message):
    """Any message from Slava (regular or forwarded) with a military keyword → random reply."""
    # Diagnostic: log whether this is a forwarded message
    if message.forward_origin is not None:
        logger.info(
            "War Alert DIAG: handler1 matched FORWARDED msg | msg_id=%s | text=%r | caption=%r",
            message.message_id,
            (message.text[:80] if message.text else None),
            (message.caption[:80] if message.caption else None),
        )
    else:
        logger.debug(
            "War Alert DIAG: handler1 matched regular msg | msg_id=%s",
            message.message_id,
        )
    reply_text = random.choice(WAR_REPLIES)
    content_preview = (message.text or message.caption or "")[:80]
    logger.info(
        "War Alert (keyword): matched in message | user_id=%d | preview=%r | msg_id=%d | chat_id=%d",
        message.from_user.id,
        content_preview,
        message.message_id,
        message.chat.id,
    )
    try:
        await message.reply(reply_text)
        logger.info(
            "War Alert (keyword): reply sent | reply=%r | msg_id=%d",
            reply_text,
            message.message_id,
        )
    except Exception:
        logger.exception(
            "War Alert (keyword): failed to send reply | msg_id=%d",
            message.message_id,
        )
    return UNHANDLED


# ── Handler 2: Channel reposts ──

@war_alert_router.message(
    TargetChannelFilter(_target_channel_ids_set, _target_channel_usernames_set),
)
async def war_channel_repost_handler(message: types.Message):
    """Any channel repost from a target channel → random reply.

    TargetChannelFilter guarantees origin is a MessageOriginChannel
    from one of the configured target channels.
    """
    origin = message.forward_origin
    if not isinstance(origin, MessageOriginChannel):
        logger.error("War Alert (repost): unexpected origin type %s", type(origin))
        return

    reply_text = random.choice(WAR_REPLIES)
    reposter_id = message.from_user.id if message.from_user else 0
    logger.info(
        "War Alert (repost): target channel repost detected | channel_id=%d | "
        "username=%s | msg_id=%d | chat_id=%d | reposter_id=%d",
        origin.chat.id,
        origin.chat.username,
        origin.message_id,
        message.chat.id,
        reposter_id,
    )
    try:
        await message.reply(reply_text)
        logger.info(
            "War Alert (repost): reply sent | reply=%r | msg_id=%d",
            reply_text,
            message.message_id,
        )
    except Exception:
        logger.exception(
            "War Alert (repost): failed to send reply | msg_id=%d | channel_id=%d",
            message.message_id,
            origin.chat.id,
        )
    return UNHANDLED