"""Epic 50 (R50-4/R50-7/R50-8, Section 58.2): каноны VERBATIM.

CHAT_SYSTEM_PROMPT — байт-в-байт эталон канона (раунд 5, T-735: п.1
«торопливое письмо» + п.2 TYPO); LEGACY_CHAT_SYSTEM_PROMPT — канон раунда 2
(эталон Section 58.2, НЕ меняется); PREV_CHAT_SYSTEM_PROMPT — слепок канона
раунда 4 (HEAD 68fb03e ДО правки раунда 5, для авто-миграции PG); пулы
кулдауна/ошибок — поэлементно (прецедент R11/R42-6). Миграция PG-канонов
(раунд 5) — в tests/test_prompt_migrations.py (migrate_prompt_canons).
"""
import re

from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    LEGACY_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_SYSTEM_PROMPT,
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

# Эталон канона раунда 4 (HEAD 68fb03e ДО правки раунда 5) — байт-в-байт.
_PREV_CHAT_SYSTEM_PROMPT_REFERENCE = """СИСТЕМНАЯ РОЛЬ:
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
Ты должен отвечать ОЧЕНЬ коротко. Твой ответ должен состоять СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ. \nНе объясняй свои мысли, не пиши списки. Максимум пара язвительных фраз. Если напишешь больше двух предложений — система упадет."""

# Эталон нового канона (раунд 5, T-735: п.1 «торопливое письмо», п.2 TYPO) —
# байт-в-байт.
_CHAT_SYSTEM_PROMPT_REFERENCE = """СИСТЕМНАЯ РОЛЬ:
Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер). Ты отвечаешь на прямые обращения пользователя (<Target_User>).
В блоке <Global_Context> находится фон беседы. В блоке <Conversation_Thread> — история вашего текущего диалога.

ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:
1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Без форматирования (никакого маркдауна).
2. Типографика: только короткие дефисы (-) и обычные двойные кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»).
3. Разрешен мат и сленг. Будь грубым, но по факту.

ИНСТРУМЕНТЫ:
У тебя есть инструменты — используй их, когда ответ требует данных, которых нет в контексте:
1. query_chat_memory — история и факты этого чата. Вызывай ПЕРВЫМ при вопросах про прошлое: «сколько раз упоминалось слово или тема», «когда это было», «кто говорил», любая статистика чата. Результат инструмента содержит число совпадений и даты — цифры бери только из него.
2. execute_web_search — свежие внешние данные: новости, проверка фактов в интернете, то, чего нет в контексте и памяти.
Вызвал инструмент — отвечай строго по его результату. Не выдумывай цифры и факты, которых нет в контексте или в результате инструмента.

ГЛАВНОЕ ОГРАНИЧЕНИЕ (КРИТИЧЕСКИ ВАЖНО):
Ты должен отвечать ОЧЕНЬ коротко. Твой ответ должен состоять СТРОГО ИЗ ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ. \nНе объясняй свои мысли, не пиши списки. Максимум пара язвительных фраз. Если напишешь больше двух предложений — система упадет."""

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

    def test_prev_snapshot_matches_round4_reference(self):
        assert PREV_CHAT_SYSTEM_PROMPT == _PREV_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_legacy_matches_old_reference(self):
        assert LEGACY_CHAT_SYSTEM_PROMPT == _LEGACY_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_new_differs_from_prev_and_legacy(self):
        assert CHAT_SYSTEM_PROMPT != PREV_CHAT_SYSTEM_PROMPT
        assert CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT
        assert PREV_CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT

    def test_prev_snapshot_is_really_before_round5(self):
        """Раунд 5 (spec 5.3.2): PREV-слепок содержит старые фразы канона
        раунда 4, нового текста — нет."""
        assert "Имитируй ленивую печать: только строчные буквы (включая начало предложений)" in PREV_CHAT_SYSTEM_PROMPT
        assert "Пунктуация базовая, без сложных тире." in PREV_CHAT_SYSTEM_PROMPT
        assert "Имитируй торопливое письмо" not in PREV_CHAT_SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире" not in PREV_CHAT_SYSTEM_PROMPT

    def test_legacy_is_untouched_historical_snapshot(self):
        """LEGACY (канон раунда 2) — байт-неизменен: без ИНСТРУМЕНТЫ, со
        старой «ленивой печатью» и старой пунктуацией."""
        assert "ИНСТРУМЕНТЫ" not in LEGACY_CHAT_SYSTEM_PROMPT
        assert "1. Имитируй ленивую печать: только строчные буквы" in LEGACY_CHAT_SYSTEM_PROMPT
        assert "2. Пунктуация базовая, без сложных тире." in LEGACY_CHAT_SYSTEM_PROMPT

    def test_contains_target_user_placeholder(self):
        assert "<Target_User>" in CHAT_SYSTEM_PROMPT

    def test_contains_tools_block(self):
        assert "ИНСТРУМЕНТЫ" in CHAT_SYSTEM_PROMPT
        assert "query_chat_memory" in CHAT_SYSTEM_PROMPT
        assert "execute_web_search" in CHAT_SYSTEM_PROMPT

    def test_round5_casing_and_typography_present(self):
        """Раунд 5 (T-735): п.1 «торопливое письмо» + п.2 TYPO во всех трёх
        слепках-преемниках не путаются."""
        assert ("1. Имитируй торопливое письмо: иногда начинай предложения "
                "с маленькой буквы. Без форматирования (никакого маркдауна)."
                in CHAT_SYSTEM_PROMPT)
        assert ("2. Типографика: только короткие дефисы (-) и обычные двойные "
                'кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и '
                "кавычки-елочки («»)." in CHAT_SYSTEM_PROMPT)
        # старые строгие формулировки в новом каноне отсутствуют
        assert "только строчные буквы (включая начало предложений)" not in CHAT_SYSTEM_PROMPT
        assert "Пунктуация базовая" not in CHAT_SYSTEM_PROMPT

    def test_no_format_placeholders(self):
        assert re.findall(r"\{(\w+)\}", CHAT_SYSTEM_PROMPT) == []
        assert re.findall(r"\{(\w+)\}", LEGACY_CHAT_SYSTEM_PROMPT) == []
        assert re.findall(r"\{(\w+)\}", PREV_CHAT_SYSTEM_PROMPT) == []

    def test_no_trailing_newline(self):
        assert not CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not LEGACY_CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not PREV_CHAT_SYSTEM_PROMPT.endswith("\n")

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


# ── Раунд 5 (T-740): миграция PG-канонов перенесена в
# tests/test_prompt_migrations.py (migrate_prompt_canons, PROMPT_MIGRATIONS);
# migrate_direct_chat_prompt_if_legacy удалена из chat_prompts.py ──────────
