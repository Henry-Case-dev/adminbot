"""Epic 50 (R50-4/R50-7/R50-8, Section 58.2): каноны VERBATIM.

CHAT_SYSTEM_PROMPT — байт-в-байт эталон из Section 58.2 (дословная строка);
пулы кулдауна/ошибок — поэлементно (прецедент R11/R42-6).
"""
import re

from services.chat_prompts import CHAT_SYSTEM_PROMPT
from services.smartmodule_phrases import (
    CHAT_COOLDOWN_PHRASES,
    CHAT_ERROR_PHRASES,
    CHECKUP_DEAD_PHRASES,
    CHECKUP_FALLBACK_PHRASES,
    CHECKUP_LLM_ERROR_PHRASES,
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    INFO_BAD_MARKUP_PHRASES,
    INFO_EDIT_OK_PHRASES,
    INFO_NO_DELETE_RIGHTS_PHRASES,
    INFO_NOT_ADMIN_PHRASES,
    LLM_ERROR_PHRASES,
    SEARCH_EMPTY_QUERY_PHRASES,
    SEARCH_ERROR_PHRASES,
    THROTTLE_PHRASES,
    WEB_ERROR_PHRASES,
    YOUTUBE_ERROR_PHRASES,
    YOUTUBE_RETRY_PHRASES,
)

# Эталон-строка Section 58.2 (R50-4) — байт-в-байт, НЕ редактировать.
_CHAT_SYSTEM_PROMPT_REFERENCE = """СИСТЕМНАЯ РОЛЬ:
Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер). Ты отвечаешь на прямые обращения пользователя (<Target_User>).
В блоке <Global_Context> находится фон беседы. В блоке <Conversation_Thread> — история вашего текущего диалога.

ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:
1. Имитируй ленивую печать: только строчные буквы (включая начало предложений), без форматирования (никакого маркдауна).
2. Пунктуация базовая, без сложных тире.
3. Разрешен мат и сленг. Будь грубым, но по факту.

ГЛАВНОЕ ОГРАНИЧЕНИЕ (КРИТИЧЕСКИ ВАЖНО):
Ты должен отвечать ОЧЕНЬ коротко. Твой ответ должен состоять СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ. 
Не объясняй свои мысли, не пиши списки. Максимум пара язвительных фраз. Если напишешь больше двух предложений — система упадет."""

_EXPECTED_COOLDOWN = (
    "ты заебал спамить, я пошел курить на {remaining_time}",
    "лимит тупых вопросов исчерпан, отдыхай {remaining_time}",
    "дай передохнуть от твоей духоты, вернусь через {remaining_time}",
    "рот оффни на {remaining_time}, я не нанимался с тобой болтать без остановки",
)

_EXPECTED_ERROR = (
    "мои мозги расплавились от твоего бреда",
    "внутренняя ошибка базы, иди нахуй",
    "я подавился токенами, попробуй позже",
)


class TestChatSystemPromptCanon:
    def test_byte_for_byte(self):
        assert CHAT_SYSTEM_PROMPT == _CHAT_SYSTEM_PROMPT_REFERENCE

    def test_contains_target_user_placeholder(self):
        assert "<Target_User>" in CHAT_SYSTEM_PROMPT

    def test_no_format_placeholders(self):
        assert re.findall(r"\{(\w+)\}", CHAT_SYSTEM_PROMPT) == []

    def test_no_trailing_newline(self):
        assert not CHAT_SYSTEM_PROMPT.endswith("\n")


class TestChatPoolsCanon:
    def test_cooldown_verbatim(self):
        assert CHAT_COOLDOWN_PHRASES == _EXPECTED_COOLDOWN

    def test_error_verbatim(self):
        assert CHAT_ERROR_PHRASES == _EXPECTED_ERROR

    def test_chat_pools_do_not_overlap_existing_pools(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
            | set(YOUTUBE_ERROR_PHRASES)
            | set(WEB_ERROR_PHRASES)
            | set(YOUTUBE_RETRY_PHRASES)
            | set(CHECKUP_FALLBACK_PHRASES)
            | set(CHECKUP_DEAD_PHRASES)
            | set(CHECKUP_LLM_ERROR_PHRASES)
            | set(INFO_NO_DELETE_RIGHTS_PHRASES)
            | set(INFO_NOT_ADMIN_PHRASES)
            | set(INFO_BAD_MARKUP_PHRASES)
            | set(INFO_EDIT_OK_PHRASES)
        )
        assert not set(CHAT_COOLDOWN_PHRASES) & existing
        assert not set(CHAT_ERROR_PHRASES) & existing
