import logging
from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from config.settings import settings

logger = logging.getLogger(__name__)

slava_presence_router = Router()

# Store references set from outside (set in bot.py)
_db = None
_scheduler = None


def setup_presence(db, scheduler):
    """Called from bot.py to inject dependencies."""
    global _db, _scheduler
    _db = db
    _scheduler = scheduler


@slava_presence_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    )
)
async def on_user_join(event: types.ChatMemberUpdated):
    """F1: Detect when any user joins the chat."""
    user = event.new_chat_member.user
    chat_id = event.chat.id
    
    if user.id != settings.SLAVIK_USER_ID:
        return UNHANDLED
    
    logger.info(f"Slava joined chat {chat_id}")
    
    if _db:
        await _db.set_presence(user.id, chat_id, True)
    
    await event.bot.send_message(
        chat_id=chat_id,
        text="ДОЛБОЕБ ВЕРНУЛСЯ"
    )
    
    if _scheduler:
        await _scheduler.signal_immediate_post(chat_id)


@slava_presence_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_MEMBER >> IS_NOT_MEMBER
    )
)
async def on_user_leave(event: types.ChatMemberUpdated):
    """Detect when Slava leaves the chat."""
    user = event.old_chat_member.user
    chat_id = event.chat.id
    
    if user.id != settings.SLAVIK_USER_ID:
        return UNHANDLED
    
    logger.info(f"Slava left chat {chat_id}")
    
    if _db:
        await _db.set_presence(user.id, chat_id, False)


@slava_presence_router.message(F.new_chat_members)
async def on_new_slava_member(message: types.Message):
    """Fallback: detect Slava join via new_chat_members field."""
    if not message.new_chat_members:
        return UNHANDLED
    
    if any(u.id == settings.SLAVIK_USER_ID for u in message.new_chat_members):
        chat_id = message.chat.id
        user_id = settings.SLAVIK_USER_ID
        
        logger.info(f"Slava joined chat {chat_id} (via new_chat_members)")
        
        if _db:
            await _db.set_presence(user_id, chat_id, True)
        
        await message.reply("ДОЛБОЕБ ВЕРНУЛСЯ")
        
        if _scheduler:
            await _scheduler.signal_immediate_post(chat_id)

    return UNHANDLED
