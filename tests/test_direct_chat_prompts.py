"""Epic 50 (R50-4/R50-7/R50-8, Section 58.2): каноны VERBATIM.

CHAT_SYSTEM_PROMPT — байт-в-байт эталон канона (раунд 8, Context-Layer
X-Features T-790, spec 3.B1: первый абзац КАК ЧИТАТЬ КОНТЕКСТ — «как читать
блоки», блок ПРИОРИТЕТЫ, запрет вывода служебных номеров); слепок канона
раунда 5 (HEAD b198d13, байт-в-байт) сохранён как
PREV_R8_CHAT_SYSTEM_PROMPT; LEGACY_CHAT_SYSTEM_PROMPT — канон раунда 2
(эталон Section 58.2, НЕ меняется); PREV_CHAT_SYSTEM_PROMPT — слепок канона
раунда 4 (HEAD 68fb03e ДО правки раунда 5, для авто-миграции PG); пулы
кулдауна/ошибок — поэлементно (прецедент R11/R42-6). Миграция PG-канонов
(раунд 5/раунд 8) — в tests/test_prompt_migrations.py (migrate_prompt_canons:
direct_chat — три ступени LEGACY/PREV/PREV_R8 → новый канон).
"""
import re

from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    LEGACY_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_SYSTEM_PROMPT,
    PREV_R8_CHAT_SYSTEM_PROMPT,
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

# Эталон слепка канона раунда 5 (HEAD b198d13, до правок раунда 8; бывший
# эталон канона раунда 5) — байт-в-байт.
_PREV_R8_CHAT_SYSTEM_PROMPT_REFERENCE = """СИСТЕМНАЯ РОЛЬ:
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

# Эталон нового канона (раунд 8, T-790, spec 3.B1) — байт-в-байт.
_CHAT_SYSTEM_PROMPT_REFERENCE = """КАК ЧИТАТЬ КОНТЕКСТ:
Твой контекст разбит на блоки-теги. <UserResolutionMap> — кто есть кто в чате; рядом с именем в квадратных скобках стоит служебный номер человека. <Global_Context> — фон беседы: конспект и недавние сообщения. <Conversation_Thread> — история вашего текущего диалога с тем, кто тебя зовёт. <Conversation_Branch> — самые свежие ходы этой ветки. <RAG_Memory> — старые факты и разговоры из памяти, там бывают и давние события с датами. <Current_Question> — сообщение, на которое ты отвечаешь сейчас. <Target_User> — кто к тебе обращается. <Protected_Facts> и <chat_lore> — важные факты, помни о них всегда. Теги не цитируй дословно, только используй по смыслу. Служебные номера в квадратных скобках не выводи и не упоминай в ответе — людей называй только именами.

СИСТЕМНАЯ РОЛЬ:
Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер). Ты отвечаешь на прямые обращения пользователя (<Target_User>).

ПРИОРИТЕТЫ:
1. Отвечай только на <Current_Question>.
2. <Conversation_Thread> и <Conversation_Branch> важнее <Global_Context>: ваш диалог — правда для ответа, фон — только подсказка.
3. При конфликте фактов верь более свежему.
4. Не путай людей: разные имена в <UserResolutionMap> — разные люди, даже если имена похожи.

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

    def test_prev_r8_snapshot_matches_round5_canon(self):
        """PREV_R8 == слепок канона раунда 5 (HEAD b198d13, свежий срез
        из git: бывший CHAT_SYSTEM_PROMPT)."""
        assert PREV_R8_CHAT_SYSTEM_PROMPT == _PREV_R8_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_prev_snapshot_matches_round4_reference(self):
        assert PREV_CHAT_SYSTEM_PROMPT == _PREV_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_legacy_matches_old_reference(self):
        assert LEGACY_CHAT_SYSTEM_PROMPT == _LEGACY_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_new_differs_from_prev_and_legacy(self):
        assert CHAT_SYSTEM_PROMPT != PREV_R8_CHAT_SYSTEM_PROMPT
        assert CHAT_SYSTEM_PROMPT != PREV_CHAT_SYSTEM_PROMPT
        assert CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT
        assert PREV_R8_CHAT_SYSTEM_PROMPT != PREV_CHAT_SYSTEM_PROMPT
        assert PREV_R8_CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT
        assert PREV_CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT

    def test_prev_snapshot_is_really_before_round5(self):
        """Раунд 5 (spec 5.3.2): PREV-слепок содержит старые фразы канона
        раунда 4, нового текста — нет."""
        assert "Имитируй ленивую печать: только строчные буквы (включая начало предложений)" in PREV_CHAT_SYSTEM_PROMPT
        assert "Пунктуация базовая, без сложных тире." in PREV_CHAT_SYSTEM_PROMPT
        assert "Имитируй торопливое письмо" not in PREV_CHAT_SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире" not in PREV_CHAT_SYSTEM_PROMPT

    def test_prev_r8_is_really_before_round8(self):
        """Раунд 8: слепок PREV_R8 == канон раунда 5 — без правил чтения
        блоков, приоритетов и запрета служебных номеров."""
        assert "Имитируй торопливое письмо" in PREV_R8_CHAT_SYSTEM_PROMPT
        assert "ИНСТРУМЕНТЫ" in PREV_R8_CHAT_SYSTEM_PROMPT
        assert ("В блоке <Global_Context> находится фон беседы. В блоке "
                "<Conversation_Thread> — история вашего текущего диалога."
                in PREV_R8_CHAT_SYSTEM_PROMPT)
        assert "КАК ЧИТАТЬ КОНТЕКСТ" not in PREV_R8_CHAT_SYSTEM_PROMPT
        assert "ПРИОРИТЕТЫ" not in PREV_R8_CHAT_SYSTEM_PROMPT
        assert "не выводи и не упоминай" not in PREV_R8_CHAT_SYSTEM_PROMPT

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
        """Раунд 5 (T-735): п.1 «торопливое письмо» + п.2 TYPO во всех
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

    def test_contains_read_context_rule(self):
        """Раунд 8 (FR-21/п.23): первый абзац «как читать блоки» — каждый
        блок-тег с назначением, теги не цитируются дословно."""
        canon = CHAT_SYSTEM_PROMPT
        lines = canon.splitlines()
        assert lines[0] == "КАК ЧИТАТЬ КОНТЕКСТ:"
        assert lines[1].startswith("Твой контекст разбит на блоки-теги.")
        for tag in ("UserResolutionMap", "Global_Context", "Conversation_Thread",
                    "Conversation_Branch", "RAG_Memory", "Current_Question",
                    "Target_User", "Protected_Facts", "chat_lore"):
            assert "<%s>" % tag in lines[1]
        assert "Теги не цитируй дословно, только используй по смыслу." in canon

    def test_contains_priorities(self):
        """Раунд 8 (FR-8/п.8): блок ПРИОРИТЕТЫ — Current_Question, иерархия
        Thread/Branch > Global_Context, свежесть, «не путай людей»."""
        canon = CHAT_SYSTEM_PROMPT
        assert "ПРИОРИТЕТЫ:" in canon
        assert "1. Отвечай только на <Current_Question>." in canon
        assert ("2. <Conversation_Thread> и <Conversation_Branch> важнее "
                "<Global_Context>: ваш диалог — правда для ответа, фон — "
                "только подсказка.") in canon
        assert "3. При конфликте фактов верь более свежему." in canon
        assert ("4. Не путай людей: разные имена в <UserResolutionMap> — "
                "разные люди, даже если имена похожи.") in canon

    def test_no_service_numbers_in_output(self):
        """Раунд 8 (NFR-2/п.1+п.3): служебные номера в скобках не выводятся
        и не упоминаются — людей называть только именами."""
        assert ("Служебные номера в квадратных скобках не выводи и не упоминай "
                "в ответе — людей называй только именами."
                in CHAT_SYSTEM_PROMPT)
        # старая строка-объяснение блоков из СИСТЕМНОЙ РОЛИ поглощена абзацем
        # «как читать блоки» и в новом каноне отсутствует
        assert ("В блоке <Global_Context> находится фон беседы. В блоке "
                "<Conversation_Thread> — история вашего текущего диалога."
                not in CHAT_SYSTEM_PROMPT)

    def test_no_fancy_quotes_outside_inherited_lines(self):
        """Дисциплина типографики (раунд 5): кавычки-елочки («») в каноне
        допустимы строго в двух перенесённых строках — примере запрета в
        правиле типографики и примерах-вопросов query_chat_memory; новые
        абзацы раунда 8 (КАК ЧИТАТЬ КОНТЕКСТ, ПРИОРИТЕТЫ) их не вводят."""
        lines_with_quotes = [l for l in CHAT_SYSTEM_PROMPT.splitlines()
                             if "«" in l or "»" in l]
        assert len(lines_with_quotes) == 2
        assert ("2. Типографика: только короткие дефисы (-) и обычные двойные "
                'кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и '
                "кавычки-елочки («»)." == lines_with_quotes[0])
        assert "«сколько раз упоминалось слово или тема»" in lines_with_quotes[1]
        # в абзаце «как читать блоки» и блоке ПРИОРИТЕТЫ ёлочек нет
        intro = CHAT_SYSTEM_PROMPT.splitlines()[1]
        assert "«" not in intro and "»" not in intro
        priorities = (CHAT_SYSTEM_PROMPT.split("ПРИОРИТЕТЫ:")[1]
                      .split("ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:")[0])
        assert "«" not in priorities and "»" not in priorities

    def test_no_format_placeholders(self):
        assert re.findall(r"\{(\w+)\}", CHAT_SYSTEM_PROMPT) == []
        assert re.findall(r"\{(\w+)\}", LEGACY_CHAT_SYSTEM_PROMPT) == []
        assert re.findall(r"\{(\w+)\}", PREV_CHAT_SYSTEM_PROMPT) == []
        assert re.findall(r"\{(\w+)\}", PREV_R8_CHAT_SYSTEM_PROMPT) == []

    def test_no_trailing_newline(self):
        assert not CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not LEGACY_CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not PREV_CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not PREV_R8_CHAT_SYSTEM_PROMPT.endswith("\n")

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
# migrate_direct_chat_prompt_if_legacy удалена из chat_prompts.py.
# Раунд 8 (T-790): PREV_R8-слепок добавлен третьей ступенью direct_chat ────
