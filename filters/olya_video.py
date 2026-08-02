"""Olya video filter — detects video/photo from @ole4444444ka with SaveAsBot conditions."""

from aiogram import types
from aiogram.enums import ContentType
from aiogram.filters import BaseFilter
from aiogram.types import MessageOriginChannel
from config.settings import settings


class OlyaVideoFilter(BaseFilter):
    """Filter: message is video/photo from configured Olya user, with SaveAsBot detection."""

    async def __call__(self, message: types.Message) -> dict | bool:
        if not settings.OLYA_ENABLED:
            return False

        if message.from_user is None or message.from_user.id != settings.OLYA_USER_ID:
            return False

        content_type = message.content_type
        if settings.OLYA_MEDIA_TYPE == "video":
            if content_type != ContentType.VIDEO:
                return False
        elif settings.OLYA_MEDIA_TYPE == "photo":
            if content_type != ContentType.PHOTO:
                return False
        elif settings.OLYA_MEDIA_TYPE == "any":
            if content_type not in (ContentType.VIDEO, ContentType.PHOTO):
                return False

        is_saveasbot = False
        matched_caption = False

        if settings.OLYA_CAPTION_ENABLED and message.caption:
            if settings.OLYA_CAPTION_TEXT.lower() in (message.caption or "").lower():
                matched_caption = True

        if settings.OLYA_REPOST_ENABLED and message.forward_origin:
            origin = message.forward_origin
            if isinstance(origin, MessageOriginChannel):
                if origin.chat.id in settings.OLYA_SAVEASBOT_CHANNEL_IDS:
                    is_saveasbot = True

        saveasbot_triggered = is_saveasbot or matched_caption
        always_send = settings.OLYA_ALWAYS_SEND

        if saveasbot_triggered or always_send:
            return {
                "is_saveasbot": saveasbot_triggered,
                "matched_caption": matched_caption,
            }

        return False
