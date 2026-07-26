"""Otboy Service (F9 / Epic 13).

Detects the word "отбой" in messages and responds with otboy.jpg,
quoting the matched word in the reply.
"""
import logging
from aiogram import Router, types
from filters.otboy_word import OtboyWordFilter
from services.otboy_relay import OtboyRelay

logger = logging.getLogger(__name__)

otboy_router = Router(name="otboy")

_relay: OtboyRelay | None = None


def setup_otboy(relay: OtboyRelay) -> None:
    """Inject OtboyRelay dependency. Called from bot.on_startup()."""
    global _relay
    _relay = relay
    logger.info("Otboy handler: relay injected")


@otboy_router.message(OtboyWordFilter())
async def otboy_handler(
    message: types.Message,
    matched_word: str,
) -> None:
    """Handle messages containing the word "отбой".

    Receives matched_word from OtboyWordFilter (via dict return)
    and delegates to OtboyRelay for photo sending.
    """
    if _relay is None:
        logger.error(
            "Otboy handler: relay not initialized (setup_otboy not called) | chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
        return

    try:
        await _relay.send_otboy(
            chat_id=message.chat.id,
            message_id=message.message_id,
            matched_word=matched_word,
        )
    except Exception:
        logger.exception(
            "Otboy handler: send_otboy failed | chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
