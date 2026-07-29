import re
import logging
from aiogram.filters import BaseFilter
from aiogram.types import Message

from filters.word_lists import DANGER_WORDS

logger = logging.getLogger(__name__)


def _build_patterns(words):
    """Compile regex patterns from word list with Cyrillic word boundaries."""
    patterns = []
    for word in words:
        try:
            patterns.append(
                re.compile(rf'(?<![а-яё]){re.escape(word)}(?![а-яё])', re.IGNORECASE)
            )
        except re.error:
            logger.warning(
                "WarWordFilter: failed to compile pattern for word %r", word
            )
    return patterns


class WarWordFilter(BaseFilter):
    """Matches messages containing military/drone/alert-related keywords.

    Checks BOTH message.text and message.caption to handle forwarded
    media messages where text is stored in caption (T-057 fix).
    """

    _PATTERNS = _build_patterns(DANGER_WORDS)

    async def __call__(self, message: Message) -> bool:
        # Diagnostic log for forwarded message debugging
        if message.forward_origin is not None:
            logger.info(
                "WarWordFilter DIAG: msg_id=%s | text=%r | caption=%r | "
                "forward_origin_type=%s | content_type=%s | raw_text_len=%d | raw_caption_len=%d",
                message.message_id,
                (message.text[:100] if message.text else None),
                (message.caption[:100] if message.caption else None),
                type(message.forward_origin).__name__,
                message.content_type,
                len(message.text) if message.text else 0,
                len(message.caption) if message.caption else 0,
            )
        content = message.text or message.caption
        # Guard: ensure we have an actual string (not MagicMock, not None, not empty)
        if not content or not isinstance(content, str):
            return False

        for p in self._PATTERNS:
            match = p.search(content)
            if match:
                matched_word = match.group()
                logger.info(
                    "WarWordFilter matched | word=%r | msg_id=%s | chat_id=%s | "
                    "source=%s",
                    matched_word,
                    message.message_id,
                    message.chat.id,
                    "caption" if message.caption and not message.text else "text",
                )
                return True
        return False
