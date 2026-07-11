import logging
from aiogram import F, Router, types
from aiogram.types import MessageOriginChannel
from config.settings import settings

logger = logging.getLogger(__name__)

dead_page_router = Router()

_relay = None
_db = None


def setup_dead_page(relay, db):
    global _relay, _db
    _relay = relay
    _db = db


@dead_page_router.message(F.forward_origin)
async def on_forward(message: types.Message):
    origin = message.forward_origin
    
    if not isinstance(origin, MessageOriginChannel):
        logger.debug(f"Forward origin is not a channel: {type(origin).__name__}")
        return
    
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
        return
    
    # Check if Slava is present (configurable, for future scaling)
    if _db is not None:
        is_present = await _db.is_present(settings.SLAVIK_USER_ID, message.chat.id)
        if not is_present:
            logger.debug(f"Slava not present in chat {message.chat.id}, skipping dead page")
            return
    
    if _relay is None:
        logger.error("DeadPageRelay not initialized — cannot send dead page")
        return
    
    chat_id = message.chat.id
    
    await _relay.send_dead_page(chat_id, slot="repost")
