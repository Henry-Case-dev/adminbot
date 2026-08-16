"""WorkWordFilter — ловит «устал/заебался»-семью (Epic 30, R30-2, D86/D92).

Паттерн — клон DangerWordFilter (filters/danger_word.py):
  - кириллические word-boundary: (?<![а-яё])...(?![а-яё])
  - re.IGNORECASE
  - ветка фраз (WORK_PHRASES) ПРОВЕРЯЕТСЯ ПЕРВОЙ (специфичнее)
  - text И caption

D92 (гейт репостов): `forward_origin is not None` → False — чужую
усталость бот не лечит, у него и без того пациентов хватает.

Возвращает {"matched_word": match.group()} (исходный регистр) — хендлер
цитирует найденное слово через ReplyParameters.
"""
import re
import logging

from aiogram.filters import BaseFilter
from aiogram.types import Message

from filters.word_lists import WORK_PHRASES, WORK_WORDS

logger = logging.getLogger(__name__)


def _build_patterns(forms: list[str]) -> list[re.Pattern]:
    """Кириллические word-boundary + re.escape + IGNORECASE (паттерн danger_word.py)."""
    patterns: list[re.Pattern] = []
    for form in forms:
        try:
            patterns.append(
                re.compile(rf"(?<![а-яё]){re.escape(form)}(?![а-яё])", re.IGNORECASE)
            )
        except re.error:
            logger.warning("WorkWordFilter: failed to compile pattern %r", form)
    return patterns


class WorkWordFilter(BaseFilter):
    """D86/D92: «устал/заебался»-семья в text/caption; репосты НЕ триггерят.

    Returns:
        {"matched_word": match.group()} при матче (фраза ПЕРВЕЕ слова),
        False иначе.
    """

    def __init__(self) -> None:
        self._phrase_patterns = _build_patterns(WORK_PHRASES)
        self._patterns = _build_patterns(WORK_WORDS)

    async def __call__(self, message: Message) -> dict[str, str] | bool:
        # D92: репосты не триггерят (гейт ПЕРВЫМ — дёшево и явно)
        if message.forward_origin is not None:
            return False

        content = message.text or message.caption
        if not content or not isinstance(content, str):
            return False

        # 1) Ветка фраз ПЕРВАЯ (специфичнее; прецедент DangerWordFilter/D55)
        for p in self._phrase_patterns:
            m = p.search(content)
            if m:
                logger.info(
                    "WorkWordFilter matched phrase | phrase=%r | msg_id=%s | chat_id=%s",
                    m.group(), message.message_id, message.chat.id,
                )
                return {"matched_word": m.group()}

        # 2) Ветка одиночных слов
        for p in self._patterns:
            m = p.search(content)
            if m:
                logger.info(
                    "WorkWordFilter matched | word=%r | msg_id=%s | chat_id=%s",
                    m.group(), message.message_id, message.chat.id,
                )
                return {"matched_word": m.group()}
        return False
