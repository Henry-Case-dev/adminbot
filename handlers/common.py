"""Epic 15 — Common Service (was Otboy Service F9).

Two-handler router on a single common_router:
  1. otboy_handler: catches "отбой" (OtboyWordFilter) → random media from common/otboy/
  2. danger_handler: catches danger words (DangerWordFilter) → random media from common/danger/

Both share CommonRelay with a single per-chat cooldown.

Router registered at position 4c between war_alert_router and slavik_router.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Router, types

from filters.danger_word import DangerWordFilter
from filters.otboy_word import OtboyWordFilter

if TYPE_CHECKING:
    from services.common_relay import CommonRelay

logger = logging.getLogger(__name__)

common_router = Router(name="common")

_relay: CommonRelay | None = None


def setup_common(relay: CommonRelay) -> None:
    """Inject CommonRelay dependency. Called from bot.on_startup()."""
    global _relay
    _relay = relay
    logger.info("Common Service: relay injected")


@common_router.message(OtboyWordFilter())
async def otboy_handler(
    message: types.Message,
    matched_word: str,
) -> None:
    """F9: Any user writes "отбой" → random media from common/otboy/."""
    if _relay is None:
        logger.error(
            "Common Service: relay not initialized — skipping otboy | "
            "chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
        return

    try:
        await _relay.send_common(
            chat_id=message.chat.id,
            message_id=message.message_id,
            matched_word=matched_word,
            subdir="otboy",
        )
    except Exception:
        logger.exception(
            "Common Service: otboy handler failed | chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )


@common_router.message(DangerWordFilter())
async def danger_handler(
    message: types.Message,
    matched_word: str,
) -> None:
    """Epic 15: Danger word detected → random media from common/danger/."""
    if _relay is None:
        logger.error(
            "Common Service: relay not initialized — skipping danger | "
            "chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
        return

    try:
        await _relay.send_common(
            chat_id=message.chat.id,
            message_id=message.message_id,
            matched_word=matched_word,
            subdir="danger",
        )
    except Exception:
        logger.exception(
            "Common Service: danger handler failed | chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
