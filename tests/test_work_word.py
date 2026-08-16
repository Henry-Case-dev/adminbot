"""T-231: юниты WorkWordFilter (Epic 30, R30-2, D86/D92).

Покрытие: все 128 форм WORK_WORDS + 31 фраза WORK_PHRASES,
регистр, кириллические границы, text/caption, гейт репостов, мат-формы.
"""
from unittest.mock import MagicMock

import pytest

from filters.work_word import WorkWordFilter, _build_patterns
from filters.word_lists import WORK_PHRASES, WORK_WORDS


def make_message(text=None, caption=None, chat_id=-100123, message_id=1, forwarded=False):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.forward_origin = MagicMock() if forwarded else None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    return msg


class TestWorkWordLists:
    def test_work_words_count_is_128(self):
        assert len(WORK_WORDS) == 128

    def test_work_phrases_count_is_31(self):
        assert len(WORK_PHRASES) == 31

    def test_no_duplicates_in_words(self):
        assert len(set(WORK_WORDS)) == len(WORK_WORDS)

    def test_no_duplicates_in_phrases(self):
        assert len(set(WORK_PHRASES)) == len(WORK_PHRASES)

    def test_no_intersection_with_danger_lists(self):
        from filters.word_lists import DANGER_PHRASES, DANGER_WORDS

        assert set(WORK_WORDS) & set(DANGER_WORDS) == set()
        assert set(WORK_PHRASES) & set(DANGER_PHRASES) == set()

    def test_no_intersection_with_selfdev_lists(self):
        from filters.word_lists import SELFDEV_PHRASES, SELFDEV_WORDS

        assert set(WORK_WORDS) & set(SELFDEV_WORDS) == set()
        assert set(WORK_PHRASES) & set(SELFDEV_PHRASES) == set()

    def test_no_intersection_with_otboy(self):
        otboy = {'отбой', 'отбоя', 'отбою', 'отбоем', 'отбое'}
        assert set(WORK_WORDS) & otboy == set()
        assert set(WORK_PHRASES) & otboy == set()


class TestWorkWordFilter:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("form", WORK_WORDS)
    async def test_each_word_form_matches(self, form):
        f = WorkWordFilter()
        msg = make_message(text=f"я сегодня {form}, пойду спать")
        result = await f(msg)
        assert result == {"matched_word": form}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("phrase", WORK_PHRASES)
    async def test_each_phrase_matches(self, phrase):
        f = WorkWordFilter()
        msg = make_message(text=f"бля, {phrase}, всё")
        result = await f(msg)
        # «совсем нет сил» содержит более раннюю фразу «нет сил» —
        # ветка фраз идёт по порядку списка (D55: longest-first, порядок D86)
        expected = "нет сил" if phrase == "совсем нет сил" else phrase
        assert result == {"matched_word": expected}

    @pytest.mark.asyncio
    async def test_uppercase_matches_with_original_case(self):
        f = WorkWordFilter()
        msg = make_message(text="Я УСТАЛ от этой жизни")
        result = await f(msg)
        assert result == {"matched_word": "УСТАЛ"}

    def test_ustav_does_not_match_ustavshiy(self):
        """«устав» не матчит «уставший» (правая граница) — проверка на уровне паттерна."""
        pattern = _build_patterns(["устав"])[0]
        assert pattern.search("он уставший человек") is None
        assert pattern.search("я устав, как дед") is not None

    @pytest.mark.asyncio
    async def test_ustav_matches_standalone(self):
        f = WorkWordFilter()
        msg = make_message(text="я устав, как дед")
        result = await f(msg)
        assert result == {"matched_word": "устав"}

    @pytest.mark.asyncio
    async def test_ustalost_does_not_match_ustalosti(self):
        """«усталость» не матчит «усталости» — у каждой формы свой паттерн."""
        f = WorkWordFilter()
        msg = make_message(text="у меня нет усталости")
        result = await f(msg)
        assert result == {"matched_word": "усталости"}

    @pytest.mark.asyncio
    async def test_ustalost_matches_own_form(self):
        f = WorkWordFilter()
        msg = make_message(text="накопилась усталость")
        result = await f(msg)
        assert result == {"matched_word": "усталость"}

    @pytest.mark.asyncio
    async def test_mat_forms_match(self):
        f = WorkWordFilter()
        for form in ("заебался", "заебусь", "заебётся", "уебался"):
            msg = make_message(text=f"я {form} сегодня")
            result = await f(msg)
            assert result == {"matched_word": form}

    @pytest.mark.asyncio
    async def test_left_boundary_blocks_prefix(self):
        f = WorkWordFilter()
        msg = make_message(text="приустал слегка")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_phrase_checked_before_word(self):
        f = WorkWordFilter()
        msg = make_message(text="устал, заебала работа окончательно")
        result = await f(msg)
        assert result == {"matched_word": "заебала работа"}

    @pytest.mark.asyncio
    async def test_phrase_right_boundary(self):
        f = WorkWordFilter()
        msg = make_message(text="нет силы воли")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_caption_matches(self):
        f = WorkWordFilter()
        msg = make_message(text=None, caption="фото: устал на работе")
        result = await f(msg)
        assert result == {"matched_word": "устал на работе"}

    @pytest.mark.asyncio
    async def test_ordinary_message_with_caption_matches(self):
        f = WorkWordFilter()
        msg = make_message(text=None, caption="заебался")
        result = await f(msg)
        assert result == {"matched_word": "заебался"}

    @pytest.mark.asyncio
    async def test_text_takes_priority_over_caption(self):
        f = WorkWordFilter()
        msg = make_message(text="заебался", caption="нет сил")
        result = await f(msg)
        assert result == {"matched_word": "заебался"}

    @pytest.mark.asyncio
    async def test_no_content_returns_false(self):
        f = WorkWordFilter()
        msg = make_message(text=None, caption=None)
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_non_string_content_returns_false(self):
        f = WorkWordFilter()
        msg = make_message(text=12345)
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_forwarded_text_not_matched(self):
        f = WorkWordFilter()
        msg = make_message(text="устал", forwarded=True)
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_forwarded_caption_not_matched(self):
        f = WorkWordFilter()
        msg = make_message(text=None, caption="заебала работа", forwarded=True)
        result = await f(msg)
        assert result is False

    def test_build_patterns_compiles_all_forms(self):
        patterns = _build_patterns(WORK_WORDS + WORK_PHRASES)
        assert len(patterns) == 128 + 31
