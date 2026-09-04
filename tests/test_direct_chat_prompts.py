"""Epic 50 (R50-4/R50-7/R50-8, Section 58.2): каноны VERBATIM.

CHAT_SYSTEM_PROMPT — байт-в-байт эталон канона (bugfix 04.09.2026, Часть 2 —
с блоком ИНСТРУМЕНТЫ); LEGACY_CHAT_SYSTEM_PROMPT — старый канон (эталон
Section 58.2, сохраняется для авто-миграции прод-БД); пулы кулдауна/ошибок —
поэлементно (прецедент R11/R42-6).
"""
import re

import pytest

from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    LEGACY_CHAT_SYSTEM_PROMPT,
    migrate_direct_chat_prompt_if_legacy,
)
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
_LEGACY_CHAT_SYSTEM_PROMPT_REFERENCE = """СИСТЕМНАЯ РОЛЬ:
Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер). Ты отвечаешь на прямые обращения пользователя (<Target_User>).
В блоке <Global_Context> находится фон беседы. В блоке <Conversation_Thread> — история вашего текущего диалога.

ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:
1. Имитируй ленивую печать: только строчные буквы (включая начало предложений), без форматирования (никакого маркдауна).
2. Пунктуация базовая, без сложных тире.
3. Разрешен мат и сленг. Будь грубым, но по факту.

ГЛАВНОЕ ОГРАНИЧЕНИЕ (КРИТИЧЕСКИ ВАЖНО):
Ты должен отвечать ОЧЕНЬ коротко. Твой ответ должен состоять СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ. \nНе объясняй свои мысли, не пиши списки. Максимум пара язвительных фраз. Если напишешь больше двух предложений — система упадет."""

# Эталон нового канона (bugfix 04.09.2026, Часть 2, FR-16) — байт-в-байт.
_CHAT_SYSTEM_PROMPT_REFERENCE = """СИСТЕМНАЯ РОЛЬ:
Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер). Ты отвечаешь на прямые обращения пользователя (<Target_User>).
В блоке <Global_Context> находится фон беседы. В блоке <Conversation_Thread> — история вашего текущего диалога.

ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:
1. Имитируй ленивую печать: только строчные буквы (включая начало предложений), без форматирования (никакого маркдауна).
2. Пунктуация базовая, без сложных тире.
3. Разрешен мат и сленг. Будь грубым, но по факту.

ИНСТРУМЕНТЫ:
У тебя есть инструменты — используй их, когда ответ требует данных, которых нет в контексте:
1. query_chat_memory — история и факты этого чата. Вызывай ПЕРВЫМ при вопросах про прошлое: «сколько раз упоминалось слово или тема», «когда это было», «кто говорил», любая статистика чата. Результат инструмента содержит число совпадений и даты — цифры бери только из него.
2. execute_web_search — свежие внешние данные: новости, проверка фактов в интернете, то, чего нет в контексте и памяти.
Вызвал инструмент — отвечай строго по его результату. Не выдумывай цифры и факты, которых нет в контексте или в результате инструмента.

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

    def test_legacy_matches_old_reference(self):
        assert LEGACY_CHAT_SYSTEM_PROMPT == _LEGACY_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_new_differs_from_legacy(self):
        assert CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT

    def test_contains_target_user_placeholder(self):
        assert "<Target_User>" in CHAT_SYSTEM_PROMPT

    def test_contains_tools_block(self):
        assert "ИНСТРУМЕНТЫ" in CHAT_SYSTEM_PROMPT
        assert "query_chat_memory" in CHAT_SYSTEM_PROMPT
        assert "execute_web_search" in CHAT_SYSTEM_PROMPT

    def test_no_format_placeholders(self):
        assert re.findall(r"\{(\w+)\}", CHAT_SYSTEM_PROMPT) == []
        assert re.findall(r"\{(\w+)\}", LEGACY_CHAT_SYSTEM_PROMPT) == []

    def test_no_trailing_newline(self):
        assert not CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not LEGACY_CHAT_SYSTEM_PROMPT.endswith("\n")

    def test_short_answer_limit_preserved(self):
        assert "ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" in CHAT_SYSTEM_PROMPT


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


# ── Bugfix 04.09.2026 (Часть 2, AC-3.3): миграция промпта в PG ──────────

class FakeCache:
    """Фейковый ConfigCache-контракт: pg_available, sync get, async set."""

    def __init__(self, current=None, pg_available=True):
        self.pg_available = pg_available
        self.value = current
        self.set_calls = []

    def get(self, key, default=None):
        if key != "prompts.direct_chat_system_prompt":
            return default
        return self.value

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))


class TestPromptMigration:
    @pytest.mark.asyncio
    async def test_legacy_value_replaced_with_new_canon(self):
        cache = FakeCache(current=LEGACY_CHAT_SYSTEM_PROMPT)
        assert await migrate_direct_chat_prompt_if_legacy(cache) is True
        assert cache.set_calls == [
            ("prompts.direct_chat_system_prompt", CHAT_SYSTEM_PROMPT, "prompts")]

    @pytest.mark.asyncio
    async def test_already_new_canon_noop(self):
        cache = FakeCache(current=CHAT_SYSTEM_PROMPT)
        assert await migrate_direct_chat_prompt_if_legacy(cache) is False
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_custom_user_value_untouched(self):
        cache = FakeCache(current="мой собственный промпт для бота")
        assert await migrate_direct_chat_prompt_if_legacy(cache) is False
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_pg_unavailable_skipped(self):
        cache = FakeCache(current=LEGACY_CHAT_SYSTEM_PROMPT, pg_available=False)
        assert await migrate_direct_chat_prompt_if_legacy(cache) is False
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_missing_key_skipped(self):
        cache = FakeCache(current=None)
        assert await migrate_direct_chat_prompt_if_legacy(cache) is False
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_none_cache_skipped(self):
        assert await migrate_direct_chat_prompt_if_legacy(None) is False
