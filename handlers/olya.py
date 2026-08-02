"""Olya handler — auto-sends media when @ole4444444ka posts video/photo."""

import logging

from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from filters.olya_video import OlyaVideoFilter
from services.olya_relay import OlyaRelay

logger = logging.getLogger(__name__)

olya_router = Router(name="olya")

_service: OlyaRelay | None = None


def setup_olya(service: OlyaRelay) -> None:
    """Inject OlyaRelay instance into the handler module."""
    global _service
    _service = service


@olya_router.message(OlyaVideoFilter())
async def olya_handler(message: types.Message, is_saveasbot: bool = False, matched_caption: bool = False) -> None:
    """Handle video/photo from Olya user — send random media from cringe folder."""
    if _service is None:
        logger.warning("OlyaRelay not initialized, skipping olya_handler")
        return UNHANDLED

    try:
        sent = await _service.send_olya(message.chat.id)
        if not sent:
            logger.debug("Olya send skipped (cooldown or no files)")
    except Exception as exc:
        logger.exception("Olya handler error: %s", exc)

    return UNHANDLED
