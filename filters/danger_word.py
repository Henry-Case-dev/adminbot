"""DangerWordFilter — matches danger-related keywords via regex.

Borrows the exact same _build_patterns function from filters/war_word.py:
  - Cyrillic word boundaries: (?<![а-яё])...(?![а-яё])
  - Case-insensitive: re.IGNORECASE

Epic 23: phrases branch (DANGER_PHRASES) checked BEFORE single words,
same boundary logic applied to the whole phrase. Phrases always come
from the defaults in filters/word_lists.py (no env override).

Returns {"matched_word": match.group()} so the handler can quote
the matched word/phrase in the reply.
"""
import re
import logging
from aiogram.filters import BaseFilter
from aiogram.types import Message
from config.settings import settings
from filters.word_lists import DANGER_WORDS, DANGER_PHRASES

logger = logging.getLogger(__name__)


def _build_danger_patterns(words: list[str]) -> list[re.Pattern]:
    """Compile regex patterns with Cyrillic word boundaries.

    Borrows the exact same pattern as _build_patterns from filters/war_word.py.
    """
    patterns: list[re.Pattern] = []
    for word in words:
        try:
            patterns.append(
                re.compile(
                    rf"(?<![а-яё]){re.escape(word)}(?![а-яё])",
                    re.IGNORECASE,
                )
            )
        except re.error:
            logger.warning(
                "DangerWordFilter: failed to compile pattern for word %r", word
            )
    return patterns


def _build_phrase_patterns(phrases: list[str]) -> list[re.Pattern]:
    """Compile regex patterns for multi-word phrases (D55).

    Same boundary logic as _build_danger_patterns, applied to the whole
    phrase: (?<![а-яё]){phrase}(?![а-яё]) — spaces inside the phrase are
    literal (re.escape), boundaries only at the phrase edges.
    """
    patterns: list[re.Pattern] = []
    for phrase in phrases:
        try:
            patterns.append(
                re.compile(
                    rf"(?<![а-яё]){re.escape(phrase)}(?![а-яё])",
                    re.IGNORECASE,
                )
            )
        except re.error:
            logger.warning(
                "DangerWordFilter: failed to compile pattern for phrase %r", phrase
            )
    return patterns


def _parse_danger_words(raw: str) -> list[str]:
    """Parse comma-separated danger words from config.

    Falls back to DANGER_WORDS from filters/word_lists.py if config is empty or unset.
    """
    if not raw:
        return list(DANGER_WORDS)
    parts = [w.strip().lower() for w in raw.split(",") if w.strip()]
    return parts if parts else list(DANGER_WORDS)


class DangerWordFilter(BaseFilter):
    """Matches messages containing danger-related keywords or phrases.

    Checks BOTH message.text and message.caption.
    Returns {"matched_word": match.group()} to pass the matched word
    or phrase to the handler for quoting.

    Pattern borrowed from WarWordFilter (filters/war_word.py):
      - Cyrillic word boundaries: (?<![а-яё])...(?![а-яё])
      - Case-insensitive: re.IGNORECASE

    Epic 23 (D55): phrases (DANGER_PHRASES) are checked FIRST — they are
    more specific than single words. Phrase branch always uses the
    defaults from filters/word_lists.py; DANGER_WORDS env override does
    not affect phrases.
    """

    def __init__(self, words: list[str] | None = None) -> None:
        if words is not None:
            self._words = words
        else:
            self._words = _parse_danger_words(settings.DANGER_WORDS)
        self._patterns = _build_danger_patterns(self._words)
        # D55: фразы ВСЕГДА из дефолтов word_lists.py — env-оверрайда нет
        self._phrase_patterns = _build_phrase_patterns(DANGER_PHRASES)

    async def __call__(self, message: Message) -> dict[str, str] | bool:
        """Check message text/caption for danger phrases and keywords.

        Returns:
            {"matched_word": match.group()} if a danger phrase or word
            is found, False otherwise.
        """
        content = message.text or message.caption
        if not content or not isinstance(content, str):
            return False

        # 1) Ветка фраз ПЕРВАЯ (обоснование — ARCHITECTURE 32.5)
        for p in self._phrase_patterns:
            match = p.search(content)
            if match:
                matched_phrase = match.group()
                logger.info(
                    "DangerWordFilter matched phrase | phrase=%r | msg_id=%s | chat_id=%s",
                    matched_phrase,
                    message.message_id,
                    message.chat.id,
                )
                return {"matched_word": matched_phrase}

        # 2) Ветка одиночных слов (как раньше)
        for p in self._patterns:
            match = p.search(content)
            if match:
                matched_word = match.group()
                logger.info(
                    "DangerWordFilter matched | word=%r | msg_id=%s | chat_id=%s",
                    matched_word,
                    message.message_id,
                    message.chat.id,
                )
                return {"matched_word": matched_word}
        return False
