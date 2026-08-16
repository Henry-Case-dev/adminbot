"""T-231: юниты SelfdevWordFilter (Epic 30, R30-1, D85/D92).

Покрытие: все 48 форм SELFDEV_WORDS + 17 фраз SELFDEV_PHRASES,
регистр, кириллические границы, text/caption, гейт репостов.
"""
from unittest.mock import MagicMock

import pytest

from filters.selfdev_word import SelfdevWordFilter, _build_patterns
from filters.word_lists import SELFDEV_PHRASES, SELFDEV_WORDS


def make_message(text=None, caption=None, chat_id=-100123, message_id=1, forwarded=False):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.forward_origin = MagicMock() if forwarded else None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    return msg


class TestSelfdevWordLists:
    def test_selfdev_words_count_is_48(self):
        assert len(SELFDEV_WORDS) == 48

    def test_selfdev_phrases_count_is_17(self):
        assert len(SELFDEV_PHRASES) == 17

    def test_no_duplicates_in_words(self):
        assert len(set(SELFDEV_WORDS)) == len(SELFDEV_WORDS)

    def test_no_duplicates_in_phrases(self):
        assert len(set(SELFDEV_PHRASES)) == len(SELFDEV_PHRASES)

    def test_no_intersection_with_danger_lists(self):
        from filters.word_lists import DANGER_PHRASES, DANGER_WORDS

        assert set(SELFDEV_WORDS) & set(DANGER_WORDS) == set()
        assert set(SELFDEV_PHRASES) & set(DANGER_PHRASES) == set()

    def test_no_intersection_with_otboy(self):
        otboy = {'отбой', 'отбоя', 'отбою', 'отбоем', 'отбое'}
        assert set(SELFDEV_WORDS) & otboy == set()
        assert set(SELFDEV_PHRASES) & otboy == set()


class TestSelfdevWordFilter:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("form", SELFDEV_WORDS)
    async def test_each_word_form_matches(self, form):
        f = SelfdevWordFilter()
        msg = make_message(text=f"сегодня у меня {form} по расписанию")
        result = await f(msg)
        assert result == {"matched_word": form}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("phrase", SELFDEV_PHRASES)
    async def test_each_phrase_matches(self, phrase):
        f = SelfdevWordFilter()
        msg = make_message(text=f"занимаюсь {phrase} вечерами")
        result = await f(msg)
        assert result == {"matched_word": phrase}

    @pytest.mark.asyncio
    async def test_uppercase_matches_with_original_case(self):
        f = SelfdevWordFilter()
        msg = make_message(text="САМОРАЗВИТИЕ это база")
        result = await f(msg)
        assert result == {"matched_word": "САМОРАЗВИТИЕ"}

    @pytest.mark.asyncio
    async def test_mixed_case_matches(self):
        f = SelfdevWordFilter()
        msg = make_message(text="ПрОкАчКа идёт полным ходом")
        result = await f(msg)
        assert result == {"matched_word": "ПрОкАчКа"}

    @pytest.mark.asyncio
    async def test_right_boundary_blocks_suffix(self):
        f = SelfdevWordFilter()
        msg = make_message(text="саморазвитиемс не существует")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_left_boundary_blocks_prefix(self):
        f = SelfdevWordFilter()
        msg = make_message(text="прасаморазвитие в кавычках")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_word_inside_longer_word_not_matched(self):
        f = SelfdevWordFilter()
        msg = make_message(text="прокачкам не место в словаре")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_phrase_checked_before_word(self):
        f = SelfdevWordFilter()
        msg = make_message(text="хочу прокачку, личностный рост это важно")
        result = await f(msg)
        assert result == {"matched_word": "личностный рост"}

    @pytest.mark.asyncio
    async def test_phrase_boundary_right(self):
        f = SelfdevWordFilter()
        msg = make_message(text="у меня личностный ростик намечается")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_caption_matches(self):
        f = SelfdevWordFilter()
        msg = make_message(text=None, caption="фото с прокачкой скилла")
        result = await f(msg)
        assert result == {"matched_word": "прокачкой"}

    @pytest.mark.asyncio
    async def test_ordinary_message_with_caption_matches(self):
        f = SelfdevWordFilter()
        msg = make_message(text=None, caption="саморазвитие без выходных")
        result = await f(msg)
        assert result == {"matched_word": "саморазвитие"}

    @pytest.mark.asyncio
    async def test_text_takes_priority_over_caption(self):
        f = SelfdevWordFilter()
        msg = make_message(text="прокачка", caption="личностный рост")
        result = await f(msg)
        assert result == {"matched_word": "прокачка"}

    @pytest.mark.asyncio
    async def test_no_content_returns_false(self):
        f = SelfdevWordFilter()
        msg = make_message(text=None, caption=None)
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_non_string_content_returns_false(self):
        f = SelfdevWordFilter()
        msg = make_message(text=12345)
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_forwarded_text_not_matched(self):
        f = SelfdevWordFilter()
        msg = make_message(text="саморазвитие", forwarded=True)
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_forwarded_caption_not_matched(self):
        f = SelfdevWordFilter()
        msg = make_message(text=None, caption="личностный рост", forwarded=True)
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_develop_word_itself_not_matched(self):
        """«развиваться» НЕ в словаре (D85) — ложные срабатывания исключены."""
        f = SelfdevWordFilter()
        msg = make_message(text="события развиваются стремительно")
        result = await f(msg)
        assert result is False

    def test_build_patterns_compiles_all_forms(self):
        patterns = _build_patterns(SELFDEV_WORDS + SELFDEV_PHRASES)
        assert len(patterns) == 48 + 17
