"""Epic 10 — Admin test commands.

/deadpage — manually trigger DeadPageRelay.send_dead_page()
/alangreet — manually trigger Alan greeting video (_send_greeting)

DM: anyone can use. Groups: admin-only (ADMIN_USER_ID).
Command message is deleted after processing.
"""
import logging
from aiogram import F, Router, types
from aiogram.filters import Command
from config.settings import settings

logger = logging.getLogger(__name__)

admin_commands_router = Router()

_relay = None


def setup_admin_commands(relay):
    """Inject DeadPageRelay dependency. Called from bot.py on_startup()."""
    global _relay
    _relay = relay


async def _delete_command(message: types.Message) -> None:
    """Delete the command message. Failure is non-fatal — logged at debug."""
    try:
        await message.delete()
    except Exception:
        logger.debug("Failed to delete command message %d in chat %d", 
                     message.message_id, message.chat.id)


# ── /deadpage ─────────────────────────────────────────

@admin_commands_router.message(Command("deadpage"), F.chat.type == "private")
async def cmd_deadpage_dm(message: types.Message):
    """DM: anyone can trigger dead_page relay."""
    await _delete_command(message)
    if _relay is None:
        await message.answer("DeadPageRelay not initialized")
        return
    chat_id = message.chat.id
    await _relay.send_dead_page(chat_id, slot="manual")
    logger.info("[/deadpage] Manual trigger in DM chat %d", chat_id)


@admin_commands_router.message(Command("deadpage"), F.chat.type != "private")
async def cmd_deadpage_group(message: types.Message):
    """Group: admin-only. Trigger dead_page relay."""
    if message.from_user.id != settings.ADMIN_USER_ID:
        logger.debug("[/deadpage] Non-admin %d rejected in chat %d", 
                     message.from_user.id, message.chat.id)
        return
    await _delete_command(message)
    if _relay is None:
        await message.answer("DeadPageRelay not initialized")
        return
    chat_id = message.chat.id
    await _relay.send_dead_page(chat_id, slot="manual")
    logger.info("[/deadpage] Admin-triggered in group chat %d", chat_id)


# ── /alangreet ────────────────────────────────────────

@admin_commands_router.message(Command("alangreet"), F.chat.type == "private")
async def cmd_alangreet_dm(message: types.Message):
    """DM: anyone can trigger Alan greeting video."""
    await _delete_command(message)
    from handlers.alan_greeting import _send_greeting
    chat_id = message.chat.id
    await _send_greeting(message.bot, chat_id)
    logger.info("[/alangreet] Manual trigger in DM chat %d", chat_id)


@admin_commands_router.message(Command("alangreet"), F.chat.type != "private")
async def cmd_alangreet_group(message: types.Message):
    """Group: admin-only. Trigger Alan greeting video."""
    if message.from_user.id != settings.ADMIN_USER_ID:
        logger.debug("[/alangreet] Non-admin %d rejected in chat %d",
                     message.from_user.id, message.chat.id)
        return
    await _delete_command(message)
    from handlers.alan_greeting import _send_greeting
    chat_id = message.chat.id
    await _send_greeting(message.bot, chat_id)
    logger.info("[/alangreet] Admin-triggered in group chat %d", chat_id)
