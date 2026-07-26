import re
import logging
from aiogram.filters import BaseFilter
from aiogram.types import Message

logger = logging.getLogger(__name__)

_OTBOY_PATTERN = re.compile(r'(?<![а-яё])отбой(?![а-яё])', re.IGNORECASE)


class OtboyWordFilter(BaseFilter):
    """Matches messages containing the exact word "отбой" (case-insensitive).

    Checks both message.text and message.caption to handle forwarded
    media messages where text is stored in caption.

    Returns {"matched_word": match.group()} to pass the matched word
    to the handler without requiring a second regex search.
    """

    async def __call__(self, message: Message) -> dict[str, str] | bool:
        content = message.text or message.caption
        if not content or not isinstance(content, str):
            return False

        match = _OTBOY_PATTERN.search(content)
        if match:
            source = "caption" if message.caption and not message.text else "text"
            logger.info(
                "OtboyWordFilter matched | matched_word=%r | chat_id=%s | user_id=%s | source=%s",
                match.group(),
                message.chat.id,
                message.from_user.id if message.from_user else "unknown",
                source,
            )
            return {"matched_word": match.group()}
        return False
