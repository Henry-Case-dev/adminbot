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
from typing import Optional

from aiogram import F, Router, types
from aiogram.types import MessageOriginChannel

from config.settings import settings
from filters.user_id import UserIdFilter
from filters.war_word import WarWordFilter

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
    env_val = settings.WAR_REPLIES
    if env_val:
        parts = [r.strip() for r in env_val.split(",") if r.strip()]
        if parts:
            logger.info("War Alert: %d custom reply phrases loaded from env", len(parts))
            return parts
    logger.info("War Alert: using %d default reply phrases", len(_DEFAULT_WAR_REPLIES))
    return list(_DEFAULT_WAR_REPLIES)


WAR_REPLIES: list[str] = _load_replies()


def setup_war_alert() -> None:
    """Initialize war alert module. Called from bot.on_startup()."""
    target_ids = _get_target_channel_ids()
    target_usernames = _get_target_channel_usernames()
    logger.info(
        "War Alert initialized: %d replies, %d channel IDs (%s), %d channel usernames (%s)",
        len(WAR_REPLIES),
        len(target_ids),
        target_ids,
        len(target_usernames),
        target_usernames,
    )


# ── Channel match helpers ──

def _parse_int_list(raw: str) -> list[int]:
    """Parse comma-separated list of integers."""
    if not raw:
        return []
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                result.append(int(part))
            except ValueError:
                logger.warning("War Alert: invalid channel ID in config: %r", part)
    return result


def _parse_str_list(raw: str) -> list[str]:
    """Parse comma-separated list of strings."""
    if not raw:
        return []
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


# Lazy-loaded target channels (parsed once at first access)
_TARGET_CHANNEL_IDS: Optional[list[int]] = None
_TARGET_CHANNEL_USERNAMES: Optional[list[str]] = None


def _get_target_channel_ids() -> list[int]:
    global _TARGET_CHANNEL_IDS
    if _TARGET_CHANNEL_IDS is None:
        _TARGET_CHANNEL_IDS = _parse_int_list(settings.WAR_CHANNEL_IDS)
    return _TARGET_CHANNEL_IDS


def _get_target_channel_usernames() -> list[str]:
    global _TARGET_CHANNEL_USERNAMES
    if _TARGET_CHANNEL_USERNAMES is None:
        _TARGET_CHANNEL_USERNAMES = _parse_str_list(settings.WAR_CHANNEL_USERNAMES)
    return _TARGET_CHANNEL_USERNAMES


def _is_target_channel(origin: MessageOriginChannel) -> bool:
    """Check if the forward origin matches a target channel by ID or username."""
    target_ids = _get_target_channel_ids()
    target_usernames = _get_target_channel_usernames()

    # Check by channel ID (most reliable)
    if target_ids and origin.chat.id in target_ids:
        logger.info(
            "War Alert (repost): matched channel by ID=%d (msg_id=%d)",
            origin.chat.id,
            origin.message_id,
        )
        return True

    # Check by channel username (case-insensitive)
    if target_usernames and origin.chat.username:
        if origin.chat.username.lower() in target_usernames:
            logger.info(
                "War Alert (repost): matched channel by username=@%s (msg_id=%d)",
                origin.chat.username,
                origin.message_id,
            )
            return True

    return False


# ── Handler 1: Slava's keywords ──

@war_alert_router.message(
    UserIdFilter(settings.SLAVIK_USER_ID),
    WarWordFilter(),
)
async def war_keyword_handler(message: types.Message):
    """Slava wrote/sent a message with a military keyword → random reply."""
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


# ── Handler 2: Channel reposts ──

@war_alert_router.message(F.forward_origin)
async def war_channel_repost_handler(message: types.Message):
    """Any channel repost from a target channel → random reply."""
    origin = message.forward_origin

    # Guard: only handle channel forwards
    if not isinstance(origin, MessageOriginChannel):
        logger.debug(
            "War Alert (repost): forward origin is not a channel (type=%s), skipping",
            getattr(origin, "type", "unknown"),
        )
        return

    # Check if this is a target channel
    if not _is_target_channel(origin):
        logger.debug(
            "War Alert (repost): non-target channel id=%d username=%s, skipping",
            origin.chat.id,
            origin.chat.username,
        )
        return

    reply_text = random.choice(WAR_REPLIES)
    reposter_id = message.from_user.id if message.from_user else 0
    logger.info(
        "War Alert (repost): target channel repost detected | channel_id=%d | "
        "username=%s | msg_id=%d | chat_id=%d | reposter_id=%d",
        origin.chat.id,
        origin.chat.username,
        reply_text,
        message.message_id,
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
