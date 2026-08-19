"""Tests for services/smartmodule_phrases.py (T-257-D, R33-5, D108; Epic 37 R37-5).

Пулы 5.1–5.7 ДОСЛОВНО из ТЗ (каноны пользователя — не переписывать):
принадлежность пулу, ровно по 5 фраз, плейсхолдер {remaining_time} в 5.1,
все фразы строчными, без эмодзи. Epic 37: пулы 5.6/5.7 добавлены В КОНЕЦ,
старые каноны 5.1–5.5 без правок; пул «Ошибка LLM» Epic 37 == существующий 5.5
(переиспользование, дублирование запрещено).
"""
import pytest

from services.smartmodule_phrases import (
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    LLM_ERROR_PHRASES,
    SEARCH_EMPTY_QUERY_PHRASES,
    SEARCH_ERROR_PHRASES,
    THROTTLE_PHRASES,
    WEB_ERROR_PHRASES,
    YOUTUBE_ERROR_PHRASES,
    YOUTUBE_RETRY_PHRASES,
)

# Каноны R33-5 (backlog, дословно)
EXPECTED_5_1 = (
    "отъебись от меня, подожди {remaining_time}",
    "че доебался, жди {remaining_time}",
    "иди потрогай траву {remaining_time}, потом пиши",
    "куда ты так спешишь, шиз, посиди молча {remaining_time}",
    "дай от тебя отдохнуть, таймер еще {remaining_time}",
)
EXPECTED_5_2 = (
    "и че тебе найти, мысли твои прочитать?",
    "запрос забыл высрать, гений",
    "ты мне пустоту предлагаешь гуглить, шиз?",
    "пальцы отсохли запрос дописать?",
    "воздух нашел, держи в курсе",
)
EXPECTED_5_3 = (
    "и че тут проверять, пустоту?",
    "в этом высере даже текста нет для фактчека",
    "я стикеры и войсы на пруфы не проверяю, дай текст",
    "фактчек воздуха прошел успешно: это пиздеж",
    "тут букв нет, шиз, на что мне отвечать?",
)
EXPECTED_5_4_SEARCH = (
    "интернет сдох, ищи сам",
    "поисковики легли, пиздуй в библиотеку",
    "сеть отвалилась, гугли своими культяпками",
    "провайдер сдох от твоих запросов, ничего не нашел",
    "интернет кончился, больше инфы нет",
)
EXPECTED_5_4_FACTCHECK = (
    "интернет сдох, фактчека не будет",
    "поисковики легли, проверяй свои вбросы сам",
    "пруфов в сети не нашлось, все базы упали",
    "сеть легла, считай что тебе все наврали",
    "не могу достучаться до пруфов, интернет откис",
)
EXPECTED_5_5 = (
    "база подавилась",
    "нейронка срыгнула от этого бреда",
    "мозги закипели это переваривать, попробуй позже",
    "токенов на твою хуйню не хватило, сервер сдох",
    "llm откинулась, сгенерировать не вышло",
)

# Каноны R37-5 (Epic 37, Section 46.6, дословно)
EXPECTED_5_6 = (
    "в этом высере нет субтитров, сиди и слушай ушами",
    "автор видоса зажал субтитры, пересказывать нечего",
    "видео сдохло или закрыто приватностью, иди нахуй",
    "не могу выдрать текст из этого ролика, ютуб послал меня",
    "там либо музыки навалили, либо автор немой, текста нет",
)
EXPECTED_5_7 = (
    "сайт сдох или закрылся пейволлом, читать нечего",
    "страница пустая как твоя голова, инфы ноль",
    "не могу открыть эту помойку, сервак лег",
    "сайт заблокировал парсер, читай своими глазами",
    "там три строчки рекламы и больше ничего, пересказывать нечего",
)

# Канон R41-2 (Epic 41, Section 50.7, дословно)
EXPECTED_5_8 = (
    "ютуб опять тупит, пробую выдрать текст еще раз",
    "не отвалился я, это ютуб упирается, щас повторим",
    "попытка в молоко, кручу еще раз, не ной",
    "субтитры не отдают, долблюсь в них снова",
    "канал сопротивляется, повторяю, отстань на секунду",
)


class TestPoolsVerbatim:
    """Каждый пул — ровно 5 фраз, дословно из ТЗ R33-5/R37-5."""

    @pytest.mark.parametrize(
        "actual,expected,name",
        [
            (THROTTLE_PHRASES, EXPECTED_5_1, "5.1"),
            (SEARCH_EMPTY_QUERY_PHRASES, EXPECTED_5_2, "5.2"),
            (FACTCHECK_EMPTY_CONTEXT_PHRASES, EXPECTED_5_3, "5.3"),
            (SEARCH_ERROR_PHRASES, EXPECTED_5_4_SEARCH, "5.4 search"),
            (FACTCHECK_ERROR_PHRASES, EXPECTED_5_4_FACTCHECK, "5.4 factcheck"),
            (LLM_ERROR_PHRASES, EXPECTED_5_5, "5.5"),
            (YOUTUBE_ERROR_PHRASES, EXPECTED_5_6, "5.6"),
            (WEB_ERROR_PHRASES, EXPECTED_5_7, "5.7"),
            (YOUTUBE_RETRY_PHRASES, EXPECTED_5_8, "5.8"),
        ],
    )
    def test_pool_matches_canon_verbatim(self, actual, expected, name):
        assert actual == expected

    @pytest.mark.parametrize(
        "actual,expected,name",
        [
            (THROTTLE_PHRASES, EXPECTED_5_1, "5.1"),
            (SEARCH_EMPTY_QUERY_PHRASES, EXPECTED_5_2, "5.2"),
            (FACTCHECK_EMPTY_CONTEXT_PHRASES, EXPECTED_5_3, "5.3"),
            (SEARCH_ERROR_PHRASES, EXPECTED_5_4_SEARCH, "5.4 search"),
            (FACTCHECK_ERROR_PHRASES, EXPECTED_5_4_FACTCHECK, "5.4 factcheck"),
            (LLM_ERROR_PHRASES, EXPECTED_5_5, "5.5"),
            (YOUTUBE_ERROR_PHRASES, EXPECTED_5_6, "5.6"),
            (WEB_ERROR_PHRASES, EXPECTED_5_7, "5.7"),
            (YOUTUBE_RETRY_PHRASES, EXPECTED_5_8, "5.8"),
        ],
    )
    def test_pool_has_exactly_5_phrases(self, actual, expected, name):
        assert len(actual) == 5
        assert len(set(actual)) == 5  # без дублей внутри пула


class TestEpic37Pools:
    """R37-5 (Section 46.6): переиспользование 5.5, отсутствие дублей."""

    def test_llm_error_pool_reused_not_duplicated(self):
        """Пул «Ошибка LLM» из ТЗ R37-5 == существующий 5.5 (T-286-ассерт)."""
        assert LLM_ERROR_PHRASES == EXPECTED_5_5

    def test_new_pools_disjoint_from_existing(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
        )
        assert not set(YOUTUBE_ERROR_PHRASES) & existing
        assert not set(WEB_ERROR_PHRASES) & existing

    def test_new_pools_disjoint_from_each_other(self):
        assert not set(YOUTUBE_ERROR_PHRASES) & set(WEB_ERROR_PHRASES)


class TestEpic41Pool:
    """R41-2 (Section 50.7): пул 5.8 disjoint со всеми существующими."""

    def test_retry_pool_disjoint_from_5_1_to_5_7(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(SEARCH_EMPTY_QUERY_PHRASES)
            | set(FACTCHECK_EMPTY_CONTEXT_PHRASES)
            | set(SEARCH_ERROR_PHRASES)
            | set(FACTCHECK_ERROR_PHRASES)
            | set(LLM_ERROR_PHRASES)
            | set(YOUTUBE_ERROR_PHRASES)
            | set(WEB_ERROR_PHRASES)
        )
        assert not set(YOUTUBE_RETRY_PHRASES) & existing


class TestPoolStyle:
    ALL_POOLS = (
        THROTTLE_PHRASES,
        SEARCH_EMPTY_QUERY_PHRASES,
        FACTCHECK_EMPTY_CONTEXT_PHRASES,
        SEARCH_ERROR_PHRASES,
        FACTCHECK_ERROR_PHRASES,
        LLM_ERROR_PHRASES,
        YOUTUBE_ERROR_PHRASES,
        WEB_ERROR_PHRASES,
        YOUTUBE_RETRY_PHRASES,
    )

    def test_all_phrases_lowercase(self):
        for pool in self.ALL_POOLS:
            for phrase in pool:
                assert phrase == phrase.lower()

    def test_no_emoji(self):
        for pool in self.ALL_POOLS:
            for phrase in pool:
                assert not any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in phrase)

    def test_throttle_pool_has_placeholder_in_every_phrase(self):
        for phrase in THROTTLE_PHRASES:
            assert "{remaining_time}" in phrase
            assert phrase.count("{remaining_time}") == 1

    def test_other_pools_have_no_placeholder(self):
        for pool in (
            SEARCH_EMPTY_QUERY_PHRASES,
            FACTCHECK_EMPTY_CONTEXT_PHRASES,
            SEARCH_ERROR_PHRASES,
            FACTCHECK_ERROR_PHRASES,
            LLM_ERROR_PHRASES,
            YOUTUBE_ERROR_PHRASES,
            WEB_ERROR_PHRASES,
            YOUTUBE_RETRY_PHRASES,
        ):
            for phrase in pool:
                assert "{remaining_time}" not in phrase

    def test_5_4_subpools_are_disjoint(self):
        assert set(SEARCH_ERROR_PHRASES) != set(FACTCHECK_ERROR_PHRASES)
        assert not set(SEARCH_ERROR_PHRASES) & set(FACTCHECK_ERROR_PHRASES)


class TestPlaceholderSubstitution:
    def test_replace_leaves_no_placeholder(self):
        for phrase in THROTTLE_PHRASES:
            substituted = phrase.replace("{remaining_time}", "5 мин")
            assert "{remaining_time}" not in substituted
            assert "5 мин" in substituted
