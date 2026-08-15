import logging
import time
from collections import OrderedDict

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import MessageOriginChannel
from config.settings import settings
from filters.user_id import UserIdFilter

logger = logging.getLogger(__name__)

# ── Media group deduplication (Epic 14) ──
_seen_media_groups: OrderedDict[str, float] = OrderedDict()
_MEDIA_GROUP_DEDUP_TTL = 5  # seconds
_MAX_DEDUP_ENTRIES = 100


def _cleanup_expired_media_groups():
    """Remove expired entries to prevent unbounded memory growth."""
    now = time.monotonic()
    expired = [k for k, v in _seen_media_groups.items() if now - v > _MEDIA_GROUP_DEDUP_TTL]
    for k in expired:
        del _seen_media_groups[k]


dead_page_router = Router()

_relay = None
_db = None


def setup_dead_page(relay, db):
    """Inject DeadPageRelay + DatabaseService (db kept for bot.py signature compat).

    Epic 22 / D53: db is no longer used inside this module — a repost by Slava
    itself implies Slava is present in the chat.
    """
    global _relay, _db
    _relay = relay
    _db = db


@dead_page_router.message(
    F.forward_origin,
    UserIdFilter(settings.SLAVIK_USER_ID),  # D53: только репосты Славы
)
async def on_forward(message: types.Message):
    origin = message.forward_origin
    
    if not isinstance(origin, MessageOriginChannel):
        logger.debug(f"Forward origin is not a channel: {type(origin).__name__}")
        return UNHANDLED
    
    source_username = settings.DEAD_PAGE_SOURCE_CHANNEL_USERNAME
    source_id = settings.DEAD_PAGE_SOURCE_CHANNEL_ID
    
    is_target = False
    
    if source_username and origin.chat.username == source_username:
        is_target = True
        logger.info(
            f"Detected repost from @{source_username} "
            f"in chat {message.chat.id} (by username match)"
        )
    
    if source_id and origin.chat.id == source_id:
        is_target = True
        logger.info(
            f"Detected repost from channel ID {source_id} "
            f"in chat {message.chat.id} (by ID match)"
        )
    
    if not is_target:
        return UNHANDLED

    # ── Epic 14: Deduplicate media group forwards ──
    _cleanup_expired_media_groups()
    if message.media_group_id:
        now = time.monotonic()
        if message.media_group_id in _seen_media_groups:
            logger.debug(
                f"[dead_page] Dedup skip: media_group_id={message.media_group_id}"
            )
            return
        _seen_media_groups[message.media_group_id] = now
        # LRU eviction: remove oldest if over limit
        if len(_seen_media_groups) > _MAX_DEDUP_ENTRIES:
            _seen_media_groups.popitem(last=False)

    # ── D53 (Epic 22): is_present-гейт УДАЛЁН ──
    # Репост Славы сам по себе означает, что Слава в чате.
    # _db остаётся в сигнатуре setup_dead_page(relay, db) для совместимости с bot.py,
    # но больше не используется в этом модуле.

    if _relay is None:
        logger.error("DeadPageRelay not initialized — cannot send dead page")
        return
    
    chat_id = message.chat.id
    
    await _relay.send_dead_page(chat_id, slot="repost")
