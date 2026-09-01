"""Olya video filter — detects video/photo from @ole4444444ka with SaveAsBot conditions."""

import logging
import re

from aiogram import types
from aiogram.enums import ContentType
from aiogram.filters import BaseFilter
from aiogram.types import MessageOriginChannel, MessageOriginUser
from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

_NORMALIZE_TRANSLATION = str.maketrans(
    {
        "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
        "\u2019": "'", "\u02bc": "'", "`": "'", "\u2032": "'",
    }
)
_MULTISPACE_RE = re.compile(r"\s+")


def _normalize_caption(text: str) -> str:
    text = text.strip().lower()
    text = text.translate(_NORMALIZE_TRANSLATION)
    return _MULTISPACE_RE.sub(" ", text)


class OlyaVideoFilter(BaseFilter):
    """Filter: message is video/photo from configured Olya user, with SaveAsBot detection."""

    async def __call__(self, message: types.Message) -> dict | bool:
        # Миграция read-пути (2026-09-03): горячие точки — изменение в
        # админке применяется без рестарта; фолбек на settings (R1).
        if not hot.get("flags.olya_enabled", settings.OLYA_ENABLED):
            return False

        if message.from_user is None or message.from_user.id != hot.get(
                "reactions.olya_user_id", settings.OLYA_USER_ID):
            return False

        content_type = message.content_type
        media_type = hot.get("reactions.olya_media_type",
                             settings.OLYA_MEDIA_TYPE)
        if media_type == "video":
            if content_type != ContentType.VIDEO:
                return False
        elif media_type == "photo":
            if content_type != ContentType.PHOTO:
                return False
        elif media_type == "any":
            if content_type not in (ContentType.VIDEO, ContentType.PHOTO):
                return False

        if hot.get("flags.olya_always_send", settings.OLYA_ALWAYS_SEND):
            return {
                "is_saveasbot": False,
                "matched_caption": False,
            }

        matched_caption = False
        is_saveasbot = False

        caption_enabled = hot.get("flags.olya_caption_enabled",
                                  settings.OLYA_CAPTION_ENABLED)
        if caption_enabled and message.caption:
            norm_caption = _normalize_caption(message.caption)
            norm_expected = _normalize_caption(hot.get(
                "reactions.olya_caption_text", settings.OLYA_CAPTION_TEXT))
            if norm_expected in norm_caption:
                matched_caption = True
            elif hot.get("flags.olya_caption_mention_enabled",
                         settings.OLYA_CAPTION_MENTION_ENABLED) \
                    and "@saveasbot" in norm_caption:
                matched_caption = True

        if hot.get("flags.olya_repost_enabled",
                   settings.OLYA_REPOST_ENABLED) and message.forward_origin:
            origin = message.forward_origin
            if isinstance(origin, MessageOriginChannel):
                if origin.chat.id in hot.get(
                        "reactions.olya_saveasbot_channel_ids",
                        settings.OLYA_SAVEASBOT_CHANNEL_IDS):
                    is_saveasbot = True
            elif isinstance(origin, MessageOriginUser):
                if origin.sender_user.id in hot.get(
                        "reactions.olya_saveasbot_user_ids",
                        settings.OLYA_SAVEASBOT_USER_IDS):
                    is_saveasbot = True
            else:
                logger.info("Olya: unexpected forward origin type | type=%s", type(origin).__name__)

        if matched_caption or is_saveasbot:
            return {
                "is_saveasbot": is_saveasbot,
                "matched_caption": matched_caption,
            }

        return False
