"""Epic 15 — Common Service (was Otboy Service F9).

Five-handler router on a single common_router:
  1. otboy_handler: catches "отбой" (OtboyWordFilter) → random media from common/otboy/
  2. danger_handler: catches danger words (DangerWordFilter) → random media from common/danger/
  3. selfdev_handler: catches «саморазвитие» (SelfdevWordFilter, Epic 30) → common/selfdev/
  4. work_handler: catches «устал/заебался» (WorkWordFilter, Epic 30) → common/work/
  5. mimic_handler: catches messages from MIMIC_VICTIM_USER_IDS → mimic transform reply

otboy + danger + selfdev + work share CommonRelay (Layer 1 пер-сабдирные
коулдауны + Layer 2 shared cooldown).
mimic uses MimicRelay with independent per-(chat, user) cooldown.

Router registered at position 4c between war_alert_router and slavik_router.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services import hot_config as hot
from filters.danger_word import DangerWordFilter
from filters.otboy_word import OtboyWordFilter
from filters.selfdev_word import SelfdevWordFilter
from filters.user_id import UserIdFilter
from filters.work_word import WorkWordFilter

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


@common_router.message(SelfdevWordFilter())
async def selfdev_handler(
    message: types.Message,
    matched_word: str,
) -> None:
    """Epic 30: слово «саморазвитие» → случайное медиа из common/selfdev/ с reply+quote."""
    if _relay is None:
        logger.error(
            "Common Service: relay not initialized — skipping selfdev | "
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
            subdir="selfdev",
        )
    except Exception:
        logger.exception(
            "Common Service: selfdev handler failed | chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
    return UNHANDLED


@common_router.message(WorkWordFilter())
async def work_handler(
    message: types.Message,
    matched_word: str,
) -> None:
    """Epic 30: «устал/заебался»-семья → случайное медиа из common/work/ с reply+quote."""
    # T-409 (Epic 52, D213): точечный гейт work-медиа — ПЕРВАЯ строка, ДО проверки _relay.
    # false → work-медиа не шлются, хендлер остаётся зарегистрированным (триггеры живы),
    # UNHANDLED — пропагация не ломается.
    # ФИКС 2026-09-03: выключатель work-медиа — горячая точка
    # (hot.get с фолбеком на settings): переключение «Медиа work-подсервиса»
    # в веб-админке (flags.common_work_media_enabled) применяется БЕЗ рестарта.
    if not hot.get("flags.common_work_media_enabled",
                   settings.COMMON_WORK_MEDIA_ENABLED):
        logger.info(
            "Common Service: work media disabled (COMMON_WORK_MEDIA_ENABLED=False) | "
            "chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
        return UNHANDLED
    if _relay is None:
        logger.error(
            "Common Service: relay not initialized — skipping work | "
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
            subdir="work",
        )
    except Exception:
        logger.exception(
            "Common Service: work handler failed | chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
    return UNHANDLED


# ── Mimic handler (§3.1) ──────────────────────────────────


def _parse_mimic_victim_ids() -> list[int]:
    """Parse comma-separated MIMIC_VICTIM_USER_IDS into a list of ints.
    Returns empty list if disabled (empty string or only 0).
    """
    raw = hot.get("reactions.mimic_victim_user_ids", settings.MIMIC_VICTIM_USER_IDS).strip()
    if not raw:
        return []
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            uid = int(part)
        except ValueError:
            logger.warning("Mimic: invalid user ID in MIMIC_VICTIM_USER_IDS: %r", part)
            continue
        if uid > 0:
            ids.append(uid)
    return ids


_VICTIM_IDS = _parse_mimic_victim_ids()
# If no valid IDs, register with a non-existent ID so handler never fires
_MIMIC_USER_IDS = tuple(_VICTIM_IDS) if _VICTIM_IDS else (0,)


@common_router.message(UserIdFilter(*_MIMIC_USER_IDS))
async def mimic_handler(message: types.Message) -> None:
    """Mimic feature: if victim wrote >N words and cooldown elapsed → mimic reply."""
    if not _VICTIM_IDS:  # disabled
        return
    # ── D52 (Epic 22): репосты не передразниваем (если не включено явно) ──
    if message.forward_origin is not None and not hot.get("flags.mimic_forwards_enabled", settings.MIMIC_FORWARDS_ENABLED):
        logger.debug(
            "Mimic: forwarded message — skipping (MIMIC_FORWARDS_ENABLED=False) | "
            "chat_id=%s | message_id=%s",
            message.chat.id,
            message.message_id,
        )
        return UNHANDLED
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