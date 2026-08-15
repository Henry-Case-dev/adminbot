"""Epic 24 — SmartModule Summary handlers (Section 33.9).

summary_observer_router (position 0a): catch-all observer — saves ALL chat
messages to smart_messages, ALWAYS returns UNHANDLED so propagation to the
other routers is guaranteed even on failures.

summary_router (position 0b): /summary manual trigger. ALLOWED_SUMMARY_IDS
empty = everyone; non-empty = listed IDs only (silent absorb). Handler never
returns UNHANDLED on its own path (A4) — Slava's catch-all must not fire.
"""
import logging
import time

from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import Command

from config.settings import settings
from services.summary_throttling import ThrottlingMiddleware

logger = logging.getLogger(__name__)

summary_observer_router = Router(name="summary_observer")
summary_router = Router(name="summary")

_generator = None
_db = None
_aliases = None
_bot_id = None


def setup_summary(generator, db=None, aliases=None, bot_id=None) -> None:
    """Inject dependencies. Called from bot.py on_startup() (33.9)."""
    global _generator, _db, _aliases, _bot_id
    _generator = generator
    _db = db
    _aliases = aliases
    _bot_id = bot_id


def _detect_media_type(message: types.Message) -> str:
    """Map message fields to smart_messages.media_type (33.9)."""
    if getattr(message, "text", None) is not None:
        return "text"
    if getattr(message, "photo", None) is not None:
        return "photo"
    if getattr(message, "video", None) is not None or getattr(message, "video_note", None) is not None:
        return "video"
    if getattr(message, "voice", None) is not None:
        return "voice"
    if getattr(message, "audio", None) is not None:
        return "audio"
    if getattr(message, "animation", None) is not None:
        return "animation"
    if getattr(message, "sticker", None) is not None:
        return "sticker"
    if getattr(message, "document", None) is not None:
        return "document"
    return "other"


def _build_nickname(user) -> str | None:
    parts = []
    for attr in ("first_name", "last_name"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts) if parts else None


# ── 0a. Observer ──────────────────────────────────────────────

@summary_observer_router.message()
async def summary_observer(message: types.Message):
    """Catch-all: save every chat message. ALWAYS returns UNHANDLED."""
    try:
        if _db is None or _aliases is None:
            return UNHANDLED
        user = message.from_user
        if user is None:
            return UNHANDLED
        if _bot_id is not None and user.id == _bot_id:
            return UNHANDLED
        text = message.text or message.caption
        media_type = _detect_media_type(message)
        if not text and media_type == "other":
            # чистые сервисные (join/pin и т.п.) — не сохраняем
            return UNHANDLED
        reply_to_id = (
            message.reply_to_message.message_id if message.reply_to_message else None
        )
        author_name = _aliases.resolve(
            user.id,
            nickname=_build_nickname(user),
            username=getattr(user, "username", None),
        )
        try:
            await _db.save_smart_message(
                user_id=user.id,
                chat_id=message.chat.id,
                text=text,
                reply_to_id=reply_to_id,
                timestamp=int(time.time()),
                media_type=media_type,
                author_name=author_name,
            )
        except Exception:
            logger.warning(
                "SmartModule observer: save failed | chat=%s user=%s",
                message.chat.id, user.id, exc_info=True,
            )
    except Exception:
        logger.warning("SmartModule observer: unexpected error", exc_info=True)
    return UNHANDLED


# ── 0b. /summary command ─────────────────────────────────────

@summary_router.message(Command("summary"))
async def cmd_summary(message: types.Message):
    """Manual summary trigger (R9/D62)."""
    user_id = message.from_user.id if message.from_user else 0
    allowed = settings.ALLOWED_SUMMARY_IDS
    if allowed and user_id not in allowed:
        logger.debug("[/summary] user %s not in ALLOWED_SUMMARY_IDS", user_id)
        return
    if _generator is None:
        logger.warning("[/summary] SummaryGenerator not initialized — skipping")
        return
    logger.info("[/summary] triggered | chat=%s user=%s", message.chat.id, user_id)
    await _generator.generate_and_send(message.chat.id)
    return


summary_router.message.outer_middleware(ThrottlingMiddleware())
