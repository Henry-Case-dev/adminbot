"""Epic 15 — Common Service (was Otboy Service F9).

Three-handler router on a single common_router:
  1. otboy_handler: catches "отбой" (OtboyWordFilter) → random media from common/otboy/
  2. danger_handler: catches danger words (DangerWordFilter) → random media from common/danger/
  3. mimic_handler: catches messages from MIMIC_VICTIM_USER_ID → mimic transform reply

otboy + danger share CommonRelay with a single per-chat cooldown.
mimic uses MimicRelay with independent per-(chat, user) cooldown.

Router registered at position 4c between war_alert_router and slavik_router.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from filters.danger_word import DangerWordFilter
from filters.otboy_word import OtboyWordFilter
from filters.user_id import UserIdFilter

if TYPE_CHECKING:
    from services.common_relay import CommonRelay
    from services.mimic_relay import MimicRelay

logger = logging.getLogger(__name__)

common_router = Router(name="common")

_relay: CommonRelay | None = None
_mimic_relay: MimicRelay | None = None


def setup_common(relay: CommonRelay) -> None:
    """Inject CommonRelay dependency. Called from bot.on_startup()."""
    global _relay
    _relay = relay
    logger.info("Common Service: relay injected")


def setup_common_mimic(mimic_relay: MimicRelay) -> None:
    """Inject MimicRelay dependency. Called from bot.on_startup()."""
    global _mimic_relay
    _mimic_relay = mimic_relay
    logger.info("Common Service: mimic relay injected")


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
    return UNHANDLED


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
    return UNHANDLED


# ── Mimic handler (§3.1) ──────────────────────────────────


@common_router.message(UserIdFilter(settings.MIMIC_VICTIM_USER_ID))
async def mimic_handler(message: types.Message) -> None:
    """Mimic feature: if victim wrote >N words and cooldown elapsed → mimic reply."""
    if settings.MIMIC_VICTIM_USER_ID <= 0:
        return
    if _mimic_relay is None:
        logger.warning(
            "Common Service: mimic relay not initialized — skipping | "
            "chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
        return

    content = message.text or message.caption
    if not content:
        return

    user_id = message.from_user.id if message.from_user else 0
    if not _mimic_relay.should_trigger(message.chat.id, user_id, content):
        return

    try:
        await _mimic_relay.send_mimic(
            message.bot, message.chat.id, message.message_id, content
        )
        _mimic_relay.mark_sent(message.chat.id, user_id)
    except Exception:
        logger.exception(
            "mimic_handler: send failed | chat_id=%s | msg_id=%s",
            message.chat.id,
            message.message_id,
        )
    return UNHANDLED