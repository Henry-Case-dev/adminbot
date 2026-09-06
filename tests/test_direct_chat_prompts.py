"""Epic 50 (R50-4/R50-7/R50-8, Section 58.2): каноны VERBATIM.

CHAT_SYSTEM_PROMPT — байт-в-байт эталон канона (раунд 9, AGI Memory T-821,
spec §3.2.2; фикс-раунд major-3/D-15: + <user_relations> в КАК ЧИТАТЬ КОНТЕКСТ
(дефис, не длинное тире), ОТНОШЕНИЯ списком 5 пунктов, третий пункт
ИНСТРУМЕНТЫ dig_into_lore; п.5 ПРИОРИТЕТЫ удалён — dig-контракт ровно в
ИНСТРУМЕНТАХ); слепок канона раунда 8 (HEAD 84c4887, байт-в-байт) сохранён
как PREV_R9_CHAT_SYSTEM_PROMPT; слепок канона раунда 5 (HEAD b198d13, байт-в-байт)
сохранён как PREV_R8_CHAT_SYSTEM_PROMPT; LEGACY_CHAT_SYSTEM_PROMPT — канон
раунда 2 (эталон Section 58.2, НЕ меняется); PREV_CHAT_SYSTEM_PROMPT — слепок
канона раунда 4 (HEAD 68fb03e ДО правки раунда 5, для авто-миграции PG); пулы
кулдаунов/ошибок — поэлементно (прецедент R11/R42-6). Миграция PG-канонов
(раунд 5/раунд 8/раунд 9) — в tests/test_prompt_migrations.py
(migrate_prompt_canons: direct_chat — четыре ступени LEGACY/PREV/PREV_R8/
PREV_R9 → новый канон).

Мини-фикс (D-16, канон НЕ задеплоен): ИНСТРУМЕНТЫ п.3 execute_web_search +
финальная фраза «Для вопросов о прошлом чата его не используй.» — эталон
R9 (ниже) обновлён, слепок PREV_R9 не тронут.
"""
import re

from services.chat_prompts import (
    CHAT_SYSTEM_PROMPT,
    LEGACY_CHAT_SYSTEM_PROMPT,
    PREV_CHAT_SYSTEM_PROMPT,
    PREV_R8_CHAT_SYSTEM_PROMPT,
    PREV_R9_CHAT_SYSTEM_PROMPT,
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

# Эталон слепка канона раунда 8 (HEAD 84c4887, до правок раунда 9; бывший
# эталон канона раунда 8) — байт-в-байт.
_PREV_R9_CHAT_SYSTEM_PROMPT_REFERENCE = """КАК ЧИТАТЬ КОНТЕКСТ:
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

# Эталон нового канона (раунд 9, AGI Memory T-821, spec §3.2.2; фикс-раунд
# major-3/D-15: ОТНОШЕНИЯ списком 5 пунктов, dig-контракт только в
# ИНСТРУМЕНТАХ; мини-фикс D-16: п.3 execute_web_search + фраза «прошлое
# чата») — байт-в-байт.
_CHAT_SYSTEM_PROMPT_REFERENCE = """КАК ЧИТАТЬ КОНТЕКСТ:
Твой контекст разбит на блоки-теги. <UserResolutionMap> — кто есть кто в чате; рядом с именем в квадратных скобках стоит служебный номер человека. <Global_Context> — фон беседы: конспект и недавние сообщения. <Conversation_Thread> — история вашего текущего диалога с тем, кто тебя зовёт. <Conversation_Branch> — самые свежие ходы этой ветки. <RAG_Memory> — старые факты и разговоры из памяти, там бывают и давние события с датами. <Current_Question> — сообщение, на которое ты отвечаешь сейчас. <Target_User> — кто к тебе обращается. <Protected_Facts> и <chat_lore> — важные факты, помни о них всегда. <user_relations> - твои отношения с участниками чата (стадия и активность). Теги не цитируй дословно, только используй по смыслу. Служебные номера в квадратных скобках не выводи и не упоминай в ответе — людей называй только именами.

СИСТЕМНАЯ РОЛЬ:
Ты — токсичный, саркастичный и циничный участник чата (бот-абьюзер). Ты отвечаешь на прямые обращения пользователя (<Target_User>).

ПРИОРИТЕТЫ:
1. Отвечай только на <Current_Question>.
2. <Conversation_Thread> и <Conversation_Branch> важнее <Global_Context>: ваш диалог — правда для ответа, фон — только подсказка.
3. При конфликте фактов верь более свежему.
4. Не путай людей: разные имена в <UserResolutionMap> — разные люди, даже если имена похожи.

ОТНОШЕНИЯ:
В блоке <user_relations> - отношения с тем, кто сейчас пишет (стадия и активность).
1. Своему или знакомому отвечай как обычно.
2. Ветерану чата - теплее, с отсылками к общему прошлому.
3. Новичку - короче, без глубоких отсылок к лору.
4. Если у собеседника есть ручная пометка админа - она важнее расчёта, не спорь с ней.
5. Не упоминай сам блок и стадии в ответе.

ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:
1. Имитируй торопливое письмо: иногда начинай предложения с маленькой буквы. Без форматирования (никакого маркдауна).
2. Типографика: только короткие дефисы (-) и обычные двойные кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»).
3. Разрешен мат и сленг. Будь грубым, но по факту.

ИНСТРУМЕНТЫ:
У тебя есть инструменты — используй их, когда ответ требует данных, которых нет в контексте:
1. query_chat_memory — история и факты этого чата. Вызывай ПЕРВЫМ при вопросах про прошлое: «сколько раз упоминалось слово или тема», «когда это было», «кто говорил», любая статистика чата. Результат инструмента содержит число совпадений и даты — цифры бери только из него.
2. dig_into_lore - датированные выдержки из старой переписки и факты графа. Вызывай ПЕРВЫМ и ОБЯЗАТЕЛЬНО до ответа, когда юзер вспоминает: помнишь/а помните/как мы тогда/год назад/в 2024/что было с (именем)/кто был тот. В запросе передавай год и имя, если они названы. Не отвечай по памяти, пока не посмотришь результат копания.
3. execute_web_search — свежие внешние данные: новости, проверка фактов в интернете, то, чего нет в контексте и памяти. Для вопросов о прошлом чата его не используй.
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

    def test_prev_r9_snapshot_matches_round8_canon(self):
        """Раунд 9: PREV_R9 == слепок канона раунда 8 (HEAD 84c4887,
        свежий срез из git: бывший CHAT_SYSTEM_PROMPT)."""
        assert PREV_R9_CHAT_SYSTEM_PROMPT == _PREV_R9_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_prev_r8_snapshot_matches_round5_canon(self):
        """PREV_R8 == слепок канона раунда 5 (HEAD b198d13, свежий срез
        из git: бывший CHAT_SYSTEM_PROMPT)."""
        assert PREV_R8_CHAT_SYSTEM_PROMPT == _PREV_R8_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_prev_snapshot_matches_round4_reference(self):
        assert PREV_CHAT_SYSTEM_PROMPT == _PREV_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_legacy_matches_old_reference(self):
        assert LEGACY_CHAT_SYSTEM_PROMPT == _LEGACY_CHAT_SYSTEM_PROMPT_REFERENCE

    def test_new_differs_from_prev_and_legacy(self):
        assert CHAT_SYSTEM_PROMPT != PREV_R9_CHAT_SYSTEM_PROMPT
        assert CHAT_SYSTEM_PROMPT != PREV_R8_CHAT_SYSTEM_PROMPT
        assert CHAT_SYSTEM_PROMPT != PREV_CHAT_SYSTEM_PROMPT
        assert CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT
        assert PREV_R9_CHAT_SYSTEM_PROMPT != PREV_R8_CHAT_SYSTEM_PROMPT
        assert PREV_R9_CHAT_SYSTEM_PROMPT != PREV_CHAT_SYSTEM_PROMPT
        assert PREV_R9_CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT
        assert PREV_R8_CHAT_SYSTEM_PROMPT != PREV_CHAT_SYSTEM_PROMPT
        assert PREV_R8_CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT
        assert PREV_CHAT_SYSTEM_PROMPT != LEGACY_CHAT_SYSTEM_PROMPT

    def test_prev_r9_is_really_before_round9(self):
        """Раунд 9: слепок PREV_R9 == канон раунда 8 — без <user_relations>,
        без ОТНОШЕНИЯ и без dig_into_lore."""
        assert "КАК ЧИТАТЬ КОНТЕКСТ" in PREV_R9_CHAT_SYSTEM_PROMPT
        assert "ПРИОРИТЕТЫ" in PREV_R9_CHAT_SYSTEM_PROMPT
        assert "<user_relations>" not in PREV_R9_CHAT_SYSTEM_PROMPT
        assert "ОТНОШЕНИЯ" not in PREV_R9_CHAT_SYSTEM_PROMPT
        assert "dig_into_lore" not in PREV_R9_CHAT_SYSTEM_PROMPT

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
        блок-тег с назначением, теги не цитируются дословно. Раунд 9 (R9):
        + <user_relations> в списке тегов."""
        canon = CHAT_SYSTEM_PROMPT
        lines = canon.splitlines()
        assert lines[0] == "КАК ЧИТАТЬ КОНТЕКСТ:"
        assert lines[1].startswith("Твой контекст разбит на блоки-теги.")
        for tag in ("UserResolutionMap", "Global_Context", "Conversation_Thread",
                    "Conversation_Branch", "RAG_Memory", "Current_Question",
                    "Target_User", "Protected_Facts", "chat_lore",
                    "user_relations"):
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
        assert re.findall(r"\{(\w+)\}", PREV_R9_CHAT_SYSTEM_PROMPT) == []

    def test_no_trailing_newline(self):
        assert not CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not LEGACY_CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not PREV_CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not PREV_R8_CHAT_SYSTEM_PROMPT.endswith("\n")
        assert not PREV_R9_CHAT_SYSTEM_PROMPT.endswith("\n")

    def test_short_answer_limit_preserved(self):
        assert "ОДНОГО ИЛИ ДВУХ ПРЕДЛОЖЕНИЙ" in CHAT_SYSTEM_PROMPT

    # ── Раунд 9 (AGI Memory, T-821, spec §3.2.2): dig_into_lore + ОТНОШЕНИЯ ──

    def test_r9_priorities_have_no_dig_trigger(self):
        """Фикс-раунд (major-3/D-15): ПРИОРИТЕТЫ БЕЗ изменений (ровно 4
        пункта раунда 8) — dig-контракт живёт в одном месте: ИНСТРУМЕНТЫ п.2."""
        priorities = (CHAT_SYSTEM_PROMPT.split("ПРИОРИТЕТЫ:")[1]
                      .split("ОТНОШЕНИЯ:")[0])
        assert "5." not in priorities
        assert "dig_into_lore" not in priorities
        assert ("4. Не путай людей: разные имена в <UserResolutionMap> — "
                "разные люди, даже если имена похожи.") in priorities

    def test_r9_relations_tone_block(self):
        """ОТНОШЕНИЯ между ПРИОРИТЕТЫ и ПРАВИЛА ОФОРМЛЕНИЯ (B4): 5 пунктов
        списком (D-15) — своему/знакомому как обычно, ветерану теплее,
        новичку короче, ручная пометка админа важнее расчёта, блок/стадии
        не упоминать."""
        assert "ОТНОШЕНИЯ:" in CHAT_SYSTEM_PROMPT
        relations = (CHAT_SYSTEM_PROMPT.split("ОТНОШЕНИЯ:")[1]
                     .split("ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:")[0])
        assert "1. Своему или знакомому отвечай как обычно." in relations
        assert "2. Ветерану чата - теплее, с отсылками к общему прошлому." \
            in relations
        assert "3. Новичку - короче, без глубоких отсылок к лору." in relations
        assert ("4. Если у собеседника есть ручная пометка админа - она "
                "важнее расчёта, не спорь с ней.") in relations
        assert "5. Не упоминай сам блок и стадии в ответе." in relations
        # блок идёт строго ДО правил оформления (порядок секций)
        assert (CHAT_SYSTEM_PROMPT.index("ОТНОШЕНИЯ:")
                < CHAT_SYSTEM_PROMPT.index("ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЬ:"))
        assert (CHAT_SYSTEM_PROMPT.index("ПРИОРИТЕТЫ:")
                < CHAT_SYSTEM_PROMPT.index("ОТНОШЕНИЯ:"))

    def test_r9_tools_include_dig_second(self):
        """ИНСТРУМЕНТЫ: query_chat_memory → dig_into_lore → execute_web_search
        (ностальгия сначала копает память, а не веб)."""
        tools = (CHAT_SYSTEM_PROMPT.split("ИНСТРУМЕНТЫ:")[1]
                 .split("ГЛАВНОЕ ОГРАНИЧЕНИЕ")[0])
        assert tools.index("1. query_chat_memory") \
            < tools.index("2. dig_into_lore") \
            < tools.index("3. execute_web_search")
        assert ("dig_into_lore - датированные выдержки из старой переписки "
                "и факты графа." in tools)

    def test_r9_dig_contract_triggers(self):
        """Контракт dig (spec §3.2.2(в) п.2): словесные триггеры ностальгии и
        «ДО ответа»."""
        dig_line = next(l for l in CHAT_SYSTEM_PROMPT.splitlines()
                        if l.startswith("2. dig_into_lore"))
        for trigger in ("помнишь", "а помните", "как мы тогда", "год назад",
                        "в 2024", "кто был тот", "ПЕРВЫМ", "ОБЯЗАТЕЛЬНО"):
            assert trigger in dig_line, trigger
        assert "Не отвечай по памяти" in dig_line

    def test_r9_new_lines_have_no_fancy_quotes_or_emdash(self):
        """Типографическая дисциплина (раунд 5): новые строки R9
        (вставка <user_relations> в «как читать», ОТНОШЕНИЯ, п.2
        ИНСТРУМЕНТЫ) — без ёлочек и без «—» (перенесённые строки с
        примерами сохранены, как в R8)."""
        # вставка в «как читать»: только сегмент от <user_relations> до
        # «Теги не цитируй» (в строке есть и R8-эм-тире других тегов)
        intro = next(l for l in CHAT_SYSTEM_PROMPT.splitlines()
                     if "<user_relations>" in l)
        segment = intro[intro.index("<user_relations>"):intro.index("Теги не цитируй")]
        assert "«" not in segment and "»" not in segment
        assert "—" not in segment
        assert " - " in segment
        for frag in ("1. Своему или знакомому отвечай", "2. dig_into_lore"):
            line = next(l for l in CHAT_SYSTEM_PROMPT.splitlines()
                        if l.startswith(frag))
            assert "«" not in line and "»" not in line
            assert "—" not in line
        dig_line = next(l for l in CHAT_SYSTEM_PROMPT.splitlines()
                        if l.startswith("2. dig_into_lore"))
        assert " - " in dig_line


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
