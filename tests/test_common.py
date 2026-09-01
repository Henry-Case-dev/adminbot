"""Tests for Epic 15 — Common Service Refactoring.

Covers:
  - OtboyWordFilter: matching, word boundaries, case-insensitivity
  - DangerWordFilter: matching, word boundaries, case-insensitivity, custom config
  - CommonRelay: _detect_media_type, _scan_directory, send_common, cooldown
  - Handlers: otboy_handler, danger_handler, relay guard, propagation
  - Migration: settings fields renamed/removed
  - Epic 18: GIF detection, scan robustness, dual cooldown
"""
import logging
import random
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import FSInputFile, ReplyParameters
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramBadRequest

from config.settings import settings
from filters.danger_word import (
    DangerWordFilter,
    _build_danger_patterns,
    _build_phrase_patterns,
    _parse_danger_words,
)
from filters.otboy_word import OtboyWordFilter
from filters.word_lists import DANGER_PHRASES
from handlers.common import (
    danger_handler,
    mimic_handler,
    otboy_handler,
    setup_common,
    setup_common_mimic,
)
from services.common_relay import (
    MEDIA_ANIMATION,
    MEDIA_AUDIO,
    MEDIA_PHOTO,
    MEDIA_VIDEO,
    MEDIA_VOICE,
    CommonRelay,
)


# ── Helpers ──


def make_message(text=None, caption=None, chat_id=-100123, message_id=1,
                 from_id=111, from_username="testuser"):
    """Create a mock aiogram Message."""
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.forward_origin = None  # ordinary message, not a forward (MagicMock-safe)
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = from_id
    msg.from_user.username = from_username
    return msg


# ═══════════════════════════════════════════════════════════════════
# A. OtboyWordFilter Tests (unchanged, imported from filters/otboy_word)
# ═══════════════════════════════════════════════════════════════════


class TestOtboyWordFilter:
    """Unit tests for OtboyWordFilter (filters/otboy_word.py)."""

    @pytest.mark.asyncio
    async def test_text_with_otboy_matches_and_returns_dict(self):
        f = OtboyWordFilter()
        msg = make_message(text="\u043e\u0442\u0431\u043e\u0439 \u0442\u0440\u0435\u0432\u043e\u0433\u0438")
        result = await f(msg)
        assert result == {"matched_word": "\u043e\u0442\u0431\u043e\u0439"}

    @pytest.mark.asyncio
    async def test_caption_with_otboy_matches(self):
        f = OtboyWordFilter()
        msg = make_message(text=None, caption="\u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d \u043e\u0442\u0431\u043e\u0439")
        result = await f(msg)
        assert result == {"matched_word": "\u043e\u0442\u0431\u043e\u0439"}

    @pytest.mark.asyncio
    async def test_text_without_otboy_returns_false(self):
        f = OtboyWordFilter()
        msg = make_message(text="\u043f\u0440\u0438\u0432\u0435\u0442 \u043a\u0430\u043a \u0434\u0435\u043b\u0430")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_uppercase_otboy_matches(self):
        f = OtboyWordFilter()
        msg = make_message(text="\u041e\u0422\u0411\u041e\u0419")
        result = await f(msg)
        assert result == {"matched_word": "\u041e\u0422\u0411\u041e\u0419"}

    @pytest.mark.asyncio
    async def test_titlecase_otboy_matches(self):
        f = OtboyWordFilter()
        msg = make_message(text="\u041e\u0442\u0431\u043e\u0439")
        result = await f(msg)
        assert result == {"matched_word": "\u041e\u0442\u0431\u043e\u0439"}

    @pytest.mark.asyncio
    async def test_mixedcase_otboy_matches(self):
        f = OtboyWordFilter()
        msg = make_message(text="\u041e\u0442\u0411\u043e\u0439")
        result = await f(msg)
        assert result == {"matched_word": "\u041e\u0442\u0411\u043e\u0439"}

    @pytest.mark.asyncio
    async def test_otboyny_not_matched(self):
        f = OtboyWordFilter()
        msg = make_message(text="\u043e\u0442\u0431\u043e\u0439\u043d\u044b\u0439 \u043c\u043e\u043b\u043e\u0442\u043e\u043a")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_otboy_in_middle_of_sentence(self):
        f = OtboyWordFilter()
        msg = make_message(text="\u043e\u0431\u044a\u044f\u0432\u0438\u043b\u0438 \u043e\u0442\u0431\u043e\u0439 \u0432\u043e\u0437\u0434\u0443\u0448\u043d\u043e\u0439 \u0442\u0440\u0435\u0432\u043e\u0433\u0438")
        result = await f(msg)
        assert result == {"matched_word": "\u043e\u0442\u0431\u043e\u0439"}

    @pytest.mark.asyncio
    async def test_non_string_content_does_not_crash(self):
        f = OtboyWordFilter()
        msg = make_message(text=None, caption=None)
        msg.text = 12345
        msg.caption = None
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_both_text_and_caption_none_returns_false(self):
        f = OtboyWordFilter()
        msg = make_message(text=None, caption=None)
        result = await f(msg)
        assert result is False


# ═══════════════════════════════════════════════════════════════════
# B. DangerWordFilter Tests
# ═══════════════════════════════════════════════════════════════════


class TestDangerWordFilter:
    """Unit tests for DangerWordFilter (filters/danger_word.py)."""

    @pytest.mark.asyncio
    async def test_bpla_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0431\u043f\u043b\u0430")
        result = await f(msg)
        assert result == {"matched_word": "\u0431\u043f\u043b\u0430"}

    @pytest.mark.asyncio
    async def test_raketnaya_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f \u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c")
        result = await f(msg)
        assert result == {"matched_word": "\u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f"}

    @pytest.mark.asyncio
    async def test_opasnost_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c")
        result = await f(msg)
        assert result == {"matched_word": "\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c"}

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        f = DangerWordFilter()
        for t in ["\u0411\u041f\u041b\u0410", "\u0411\u043f\u043b\u0430", "\u0431\u041f\u041b\u0410"]:
            msg = make_message(text=t)
            result = await f(msg)
            assert result == {"matched_word": t}

    @pytest.mark.asyncio
    async def test_in_sentence(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0432\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u0431\u043f\u043b\u0430 \u0432 \u043d\u0435\u0431\u0435")
        result = await f(msg)
        assert result == {"matched_word": "\u0431\u043f\u043b\u0430"}

    @pytest.mark.asyncio
    async def test_word_boundary_no_match(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0431\u043f\u043b\u0430\u0448\u043d\u0438\u043a")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_caption_matches(self):
        f = DangerWordFilter()
        msg = make_message(text=None, caption="\u0431\u043f\u043b\u0430")
        result = await f(msg)
        assert result == {"matched_word": "\u0431\u043f\u043b\u0430"}

    @pytest.mark.asyncio
    async def test_both_none_returns_false(self):
        f = DangerWordFilter()
        msg = make_message(text=None, caption=None)
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_custom_words_from_config(self):
        f = DangerWordFilter(words=["\u0430\u0442\u0430\u043a\u0430", "\u0443\u0433\u0440\u043e\u0437\u0430"])
        msg = make_message(text="\u0430\u0442\u0430\u043a\u0430 \u043d\u0430\u0447\u0430\u043b\u0430\u0441\u044c")
        result = await f(msg)
        assert result == {"matched_word": "\u0430\u0442\u0430\u043a\u0430"}

        msg2 = make_message(text="\u0441\u0435\u0440\u044c\u0435\u0437\u043d\u0430\u044f \u0443\u0433\u0440\u043e\u0437\u0430")
        result2 = await f(msg2)
        assert result2 == {"matched_word": "\u0443\u0433\u0440\u043e\u0437\u0430"}

        # Epic 23 (D55): phrase branch works regardless of custom words
        msg3 = make_message(text="\u0432 \u0431\u0443\u043d\u043a\u0435\u0440")
        result3 = await f(msg3)
        assert result3 == {"matched_word": "\u0432 \u0431\u0443\u043d\u043a\u0435\u0440"}

    @pytest.mark.asyncio
    async def test_empty_config_uses_defaults(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0431\u043f\u043b\u0430")
        result = await f(msg)
        assert result == {"matched_word": "\u0431\u043f\u043b\u0430"}

    @pytest.mark.asyncio
    async def test_multi_word_trevoga_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0442\u0440\u0435\u0432\u043e\u0433\u0430")
        result = await f(msg)
        assert result == {"matched_word": "\u0442\u0440\u0435\u0432\u043e\u0433\u0430"}

    @pytest.mark.asyncio
    async def test_vnimanie_vsem_matches_via_vnimanie(self):
        """'внимание всем' matches via standalone 'внимание' (T-109 expanded list)."""
        f = DangerWordFilter()
        msg = make_message(text="\u0432\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u0432\u0441\u0435\u043c")
        result = await f(msg)
        assert result is not False
        assert "внимание" in result["matched_word"].lower()

    @pytest.mark.asyncio
    async def test_sirena_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0441\u0438\u0440\u0435\u043d\u0430")
        result = await f(msg)
        assert result == {"matched_word": "\u0441\u0438\u0440\u0435\u043d\u0430"}

    @pytest.mark.asyncio
    async def test_dron_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0434\u0440\u043e\u043d")
        result = await f(msg)
        assert result == {"matched_word": "\u0434\u0440\u043e\u043d"}

    @pytest.mark.asyncio
    async def test_non_string_content_does_not_crash(self):
        f = DangerWordFilter()
        msg = make_message(text=None, caption=None)
        msg.text = 12345
        result = await f(msg)
        assert result is False


class TestDangerWordFilterExpanded:
    """Tests for new danger words from expanded WAR_WORDS list (T-109)."""

    @pytest.mark.asyncio
    async def test_raketa_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0440\u0430\u043a\u0435\u0442\u0430")
        result = await f(msg)
        assert result is not False
        assert "ракета" in result["matched_word"].lower()

    @pytest.mark.asyncio
    async def test_bpla_uppercase_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0411\u041f\u041b\u0410 \u0432 \u043d\u0435\u0431\u0435")
        result = await f(msg)
        assert result is not False
        assert result["matched_word"].lower() == "бпла"

    @pytest.mark.asyncio
    async def test_dron_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0434\u0440\u043e\u043d")
        result = await f(msg)
        assert result is not False
        assert "дрон" in result["matched_word"].lower()

    @pytest.mark.asyncio
    async def test_ukrytie_matches(self):
        """Epic 23: 'все в укрытие' matches via phrase 'в укрытие'."""
        f = DangerWordFilter()
        msg = make_message(text="\u0432\u0441\u0435 \u0432 \u0443\u043a\u0440\u044b\u0442\u0438\u0435")
        result = await f(msg)
        assert result == {"matched_word": "\u0432 \u0443\u043a\u0440\u044b\u0442\u0438\u0435"}

    @pytest.mark.asyncio
    async def test_ukrytie_alone_not_matched(self):
        """Epic 23: single 'укрытие' must NOT match."""
        f = DangerWordFilter()
        msg = make_message(text="\u0443\u043a\u0440\u044b\u0442\u0438\u0435")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_bunker_matches(self):
        """Epic 23: 'заходи в бункер' matches via phrase 'в бункер'."""
        f = DangerWordFilter()
        msg = make_message(text="\u0437\u0430\u0445\u043e\u0434\u0438 \u0432 \u0431\u0443\u043d\u043a\u0435\u0440")
        result = await f(msg)
        assert result == {"matched_word": "\u0432 \u0431\u0443\u043d\u043a\u0435\u0440"}

    @pytest.mark.asyncio
    async def test_bunker_alone_not_matched(self):
        """Epic 23: single 'бункер' must NOT match."""
        f = DangerWordFilter()
        msg = make_message(text="\u0431\u0443\u043d\u043a\u0435\u0440")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_ordinary_word_does_not_match(self):
        f = DangerWordFilter()
        msg = make_message(text="\u043f\u0440\u0438\u0432\u0435\u0442 \u043a\u0430\u043a \u0434\u0435\u043b\u0430")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_caption_with_danger_word_matches(self):
        f = DangerWordFilter()
        msg = make_message(text=None, caption="\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c \u0430\u0442\u0430\u043a\u0438")
        result = await f(msg)
        assert result is not False
        assert "опасность" in result["matched_word"].lower()

    @pytest.mark.asyncio
    async def test_forwarded_caption_with_danger_word_matches(self):
        f = DangerWordFilter()
        msg = make_message(text=None, caption="\u0432\u043d\u0438\u043c\u0430\u043d\u0438\u0435 \u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f \u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c")
        # simulates a forwarded message with caption
        result = await f(msg)
        assert result is not False

    @pytest.mark.asyncio
    async def test_evakuatsiya_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0430 \u044d\u0432\u0430\u043a\u0443\u0430\u0446\u0438\u044f")
        result = await f(msg)
        assert result is not False
        assert "эвакуация" in result["matched_word"].lower()

    @pytest.mark.asyncio
    async def test_sbit_matches(self):
        """Epic 23: 'бпла сбит' matches via 'бпла' ('сбит' removed, 'бпла' remains)."""
        f = DangerWordFilter()
        msg = make_message(text="\u0431\u043f\u043b\u0430 \u0441\u0431\u0438\u0442")
        result = await f(msg)
        assert result is not False
        assert "бпла" in result["matched_word"].lower()

    @pytest.mark.asyncio
    async def test_vzryv_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u043f\u0440\u043e\u0438\u0437\u043e\u0448\u0451\u043b \u0432\u0437\u0440\u044b\u0432")
        result = await f(msg)
        assert result is not False
        assert "взрыв" in result["matched_word"].lower()


# ═══════════════════════════════════════════════════════════════════
# C. DangerWordFilter Pattern Builder
# ═══════════════════════════════════════════════════════════════════


class TestDangerPatternBuilder:
    """Tests for _build_danger_patterns and _parse_danger_words."""

    def test_build_patterns_compiles_valid_words(self):
        patterns = _build_danger_patterns(["\u0431\u043f\u043b\u0430", "\u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f"])
        assert len(patterns) == 2
        assert patterns[0].search("\u0431\u043f\u043b\u0430 \u0432 \u043d\u0435\u0431\u0435") is not None

    def test_build_patterns_word_boundary(self):
        patterns = _build_danger_patterns(["\u0434\u0440\u043e\u043d"])
        assert patterns[0].search("\u0434\u0440\u043e\u043d \u043b\u0435\u0442\u0438\u0442") is not None
        assert patterns[0].search("\u0434\u0440\u043e\u043d\u044b") is None

    def test_parse_danger_words_from_comma_string(self):
        result = _parse_danger_words("\u0431\u043f\u043b\u0430,\u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f,\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c")
        assert result == ["\u0431\u043f\u043b\u0430", "\u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f", "\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c"]

    def test_parse_danger_words_strips_whitespace(self):
        result = _parse_danger_words(" \u0431\u043f\u043b\u0430 , \u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f , \u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c ")
        assert result == ["\u0431\u043f\u043b\u0430", "\u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f", "\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c"]

    def test_parse_danger_words_empty_returns_defaults(self):
        result = _parse_danger_words("")
        # Epic 23 (32.2): 118 word forms in filters/word_lists.py
        assert "\u0431\u043f\u043b\u0430" in result
        assert "\u0434\u0440\u043e\u043d" in result
        assert "\u0440\u0430\u043a\u0435\u0442\u0430" in result
        assert "\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c" in result
        assert "\u0432\u0437\u0440\u044b\u0432" in result
        assert len(result) == 118

    def test_parse_danger_words_default_list_length(self):
        result = _parse_danger_words("")
        # Epic 23 (32.2): 191 − 77 removed + 4 'хлопок' forms = 118
        assert len(result) == 118

    def test_build_phrase_patterns_compiles_valid_phrases(self):
        patterns = _build_phrase_patterns(["\u0432 \u0431\u0443\u043d\u043a\u0435\u0440", "\u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f \u0430\u0442\u0430\u043a\u0430"])
        assert len(patterns) == 2
        assert patterns[0].search("\u0438\u0434\u0438 \u0432 \u0431\u0443\u043d\u043a\u0435\u0440") is not None

    def test_build_phrase_patterns_word_boundary(self):
        patterns = _build_phrase_patterns(["\u0432 \u0431\u0443\u043d\u043a\u0435\u0440"])
        assert patterns[0].search("\u0432 \u0431\u0443\u043d\u043a\u0435\u0440") is not None
        # right boundary: 'в бункере' must NOT match 'в бункер'
        assert patterns[0].search("\u0432 \u0431\u0443\u043d\u043a\u0435\u0440\u0435") is None

    def test_danger_phrases_count_matches_contract(self):
        """Epic 23 (32.2/32.3): ровно 17 фраз — 10 shelter + 7 attack, longest-first."""
        assert len(DANGER_PHRASES) == 17
        assert DANGER_PHRASES[:10] == [
            'укрыться в убежище', 'уйти в бомбоубежище', 'пройти в убежище',
            'спрятаться в бункере', 'бегом в укрытие', 'иди в бункер',
            'в бомбоубежище', 'в убежище', 'в укрытие', 'в бункер',
        ]
        assert DANGER_PHRASES[10:] == [
            'беспилотная атака', 'ракетная атака', 'атака дронов',
            'атака беспилотников', 'ракетный обстрел',
            'артиллерийский обстрел', 'массированный обстрел',
        ]


# ═══════════════════════════════════════════════════════════════════
# D. CommonRelay — Media Type Detection
# ═══════════════════════════════════════════════════════════════════


class TestCommonRelayDetectMediaType:
    """Tests for CommonRelay._detect_media_type."""

    @pytest.fixture
    def relay(self):
        bot = AsyncMock()
        return CommonRelay(bot, cooldown_seconds=0)

    def test_detect_photo_jpg(self, relay):
        assert relay._detect_media_type(Path("photo.jpg")) == MEDIA_PHOTO

    def test_detect_photo_jpeg(self, relay):
        assert relay._detect_media_type(Path("photo.jpeg")) == MEDIA_PHOTO

    def test_detect_photo_png(self, relay):
        assert relay._detect_media_type(Path("photo.png")) == MEDIA_PHOTO

    def test_detect_photo_webp(self, relay):
        assert relay._detect_media_type(Path("photo.webp")) == MEDIA_PHOTO

    def test_detect_photo_bmp(self, relay):
        assert relay._detect_media_type(Path("photo.bmp")) == MEDIA_PHOTO

    def test_detect_video_mp4(self, relay):
        assert relay._detect_media_type(Path("video.mp4")) == MEDIA_VIDEO

    def test_detect_video_mov(self, relay):
        assert relay._detect_media_type(Path("video.mov")) == MEDIA_VIDEO

    def test_detect_video_webm(self, relay):
        assert relay._detect_media_type(Path("video.webm")) == MEDIA_VIDEO

    def test_detect_animation_mp4_gif(self, relay):
        assert relay._detect_media_type(Path("danger_02_gif.mp4")) == MEDIA_ANIMATION

    def test_detect_animation_webm_gif(self, relay):
        assert relay._detect_media_type(Path("funny_gif.webm")) == MEDIA_ANIMATION

    def test_detect_animation_gif_in_middle(self, relay):
        assert relay._detect_media_type(Path("animation_gif_v2.mp4")) == MEDIA_ANIMATION

    def test_unsupported_txt(self, relay):
        assert relay._detect_media_type(Path("readme.txt")) is None

    def test_unsupported_pdf(self, relay):
        assert relay._detect_media_type(Path("doc.pdf")) is None

    def test_case_insensitive_extension(self, relay):
        assert relay._detect_media_type(Path("photo.JPG")) == MEDIA_PHOTO

    def test_gif_in_stem_case_insensitive(self, relay):
        assert relay._detect_media_type(Path("MY_GIF.mp4")) == MEDIA_ANIMATION

    def test_detect_audio_mp3(self, relay):
        assert relay._detect_media_type(Path("alert.mp3")) == MEDIA_AUDIO

    def test_detect_voice_ogg(self, relay):
        assert relay._detect_media_type(Path("message.ogg")) == MEDIA_VOICE

    def test_detect_audio_mp3_uppercase(self, relay):
        assert relay._detect_media_type(Path("ALERT.MP3")) == MEDIA_AUDIO

    def test_detect_voice_ogg_uppercase(self, relay):
        assert relay._detect_media_type(Path("VOICE.OGG")) == MEDIA_VOICE


# ═══════════════════════════════════════════════════════════════════
# E. CommonRelay — Scan Directory
# ═══════════════════════════════════════════════════════════════════


class TestCommonRelayScanDirectory:
    """Tests for CommonRelay._scan_directory with tmp_path fixtures."""

    @pytest.fixture
    def relay(self):
        bot = AsyncMock()
        return CommonRelay(bot, cooldown_seconds=0)

    def test_scan_otboy_dir_with_images(self, relay, tmp_path):
        subdir = tmp_path / "otboy"
        subdir.mkdir()
        (subdir / "otboy_01.jpg").write_text("fake")
        (subdir / "otboy_02.png").write_text("fake")

        relay._media_base = str(tmp_path)
        files = relay._scan_directory("otboy")
        assert len(files) == 2
        assert files[0][0].name in {"otboy_01.jpg", "otboy_02.png"}
        assert all(mt == MEDIA_PHOTO for _, mt in files)

    def test_scan_danger_dir_mixed_types(self, relay, tmp_path):
        subdir = tmp_path / "danger"
        subdir.mkdir()
        (subdir / "danger_01.jpg").write_text("fake")
        (subdir / "danger_02.mp4").write_text("fake")
        (subdir / "danger_03_gif.mp4").write_text("fake")
        (subdir / "readme.txt").write_text("fake")

        relay._media_base = str(tmp_path)
        files = relay._scan_directory("danger")
        assert len(files) == 3
        types = {mt for _, mt in files}
        assert MEDIA_PHOTO in types
        assert MEDIA_VIDEO in types
        assert MEDIA_ANIMATION in types

    def test_scan_skips_unsupported_files(self, relay, tmp_path):
        subdir = tmp_path / "test"
        subdir.mkdir()
        (subdir / "readme.txt").write_text("fake")
        (subdir / "notes.md").write_text("fake")

        relay._media_base = str(tmp_path)
        files = relay._scan_directory("test")
        assert files == []

    def test_scan_missing_directory_returns_empty(self, relay, tmp_path):
        relay._media_base = str(tmp_path)
        files = relay._scan_directory("nonexistent")
        assert files == []

    def test_scan_empty_directory_returns_empty(self, relay, tmp_path):
        subdir = tmp_path / "empty"
        subdir.mkdir()

        relay._media_base = str(tmp_path)
        files = relay._scan_directory("empty")
        assert files == []

    def test_scan_skips_subdirectories(self, relay, tmp_path):
        subdir = tmp_path / "test"
        subdir.mkdir()
        (subdir / "nested").mkdir()
        (subdir / "photo.jpg").write_text("fake")

        relay._media_base = str(tmp_path)
        files = relay._scan_directory("test")
        assert len(files) == 1
        assert files[0][0].name == "photo.jpg"

    def test_scan_with_permission_error(self, relay, tmp_path):
        subdir = tmp_path / "locked"
        subdir.mkdir()
        relay._media_base = str(tmp_path)
        with patch.object(Path, "iterdir", side_effect=PermissionError("access denied")):
            with pytest.raises(PermissionError):
                relay._scan_directory("locked")

    def test_scan_with_audio_and_voice(self, relay, tmp_path):
        subdir = tmp_path / "audio_test"
        subdir.mkdir()
        (subdir / "siren.mp3").write_text("fake")
        (subdir / "voice.ogg").write_text("fake")
        (subdir / "readme.txt").write_text("fake")

        relay._media_base = str(tmp_path)
        files = relay._scan_directory("audio_test")
        assert len(files) == 2
        types = {mt for _, mt in files}
        assert MEDIA_AUDIO in types
        assert MEDIA_VOICE in types


# ═══════════════════════════════════════════════════════════════════
# F. CommonRelay — Send Common
# ═══════════════════════════════════════════════════════════════════


class TestCommonRelaySendCommon:
    """Tests for CommonRelay.send_common and _send_by_type."""

    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.send_video = AsyncMock()
        bot.send_animation = AsyncMock()
        bot.send_audio = AsyncMock()
        bot.send_voice = AsyncMock()
        return bot

    @pytest.fixture
    def mock_scan(self):
        return [(Path("/fake/photo.jpg"), MEDIA_PHOTO)]

    @pytest.mark.asyncio
    async def test_send_photo_called_for_image(self, mock_bot, mock_scan):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        with patch.object(relay, "_scan_directory", return_value=mock_scan):
            await relay.send_common(chat_id=42, message_id=99, matched_word="\u043e\u0442\u0431\u043e\u0439", subdir="otboy")

        mock_bot.send_photo.assert_called_once()
        mock_bot.send_video.assert_not_called()
        mock_bot.send_animation.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_video_called_for_video(self, mock_bot):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        mock_files = [(Path("/fake/danger_01.mp4"), MEDIA_VIDEO)]
        with patch.object(relay, "_scan_directory", return_value=mock_files):
            await relay.send_common(chat_id=42, message_id=99, matched_word="\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c", subdir="danger")

        mock_bot.send_video.assert_called_once()
        mock_bot.send_photo.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_animation_called_for_gif(self, mock_bot):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        mock_files = [(Path("/fake/danger_02_gif.mp4"), MEDIA_ANIMATION)]
        with patch.object(relay, "_scan_directory", return_value=mock_files):
            await relay.send_common(chat_id=42, message_id=99, matched_word="\u0431\u043f\u043b\u0430", subdir="danger")

        mock_bot.send_animation.assert_called_once()
        mock_bot.send_photo.assert_not_called()
        mock_bot.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_audio_called_for_mp3(self, mock_bot):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        mock_files = [(Path("/fake/alert.mp3"), MEDIA_AUDIO)]
        with patch.object(relay, "_scan_directory", return_value=mock_files):
            await relay.send_common(chat_id=42, message_id=99, matched_word="\u0441\u0438\u0440\u0435\u043d\u0430", subdir="danger")

        mock_bot.send_audio.assert_called_once()
        mock_bot.send_photo.assert_not_called()
        mock_bot.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_voice_called_for_ogg(self, mock_bot):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        mock_files = [(Path("/fake/msg.ogg"), MEDIA_VOICE)]
        with patch.object(relay, "_scan_directory", return_value=mock_files):
            await relay.send_common(chat_id=42, message_id=99, matched_word="\u043e\u0442\u0431\u043e\u0439", subdir="otboy")

        mock_bot.send_voice.assert_called_once()
        mock_bot.send_photo.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_parameters_passed(self, mock_bot):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        mock_files = [(Path("/fake/photo.jpg"), MEDIA_PHOTO)]
        with patch.object(relay, "_scan_directory", return_value=mock_files):
            await relay.send_common(chat_id=42, message_id=99, matched_word="\u041e\u0442\u0431\u043e\u0439", subdir="otboy")

        call_kwargs = mock_bot.send_photo.call_args.kwargs
        assert call_kwargs["chat_id"] == 42
        assert isinstance(call_kwargs["photo"], FSInputFile)
        assert isinstance(call_kwargs["reply_parameters"], ReplyParameters)
        assert call_kwargs["reply_parameters"].message_id == 99
        assert call_kwargs["reply_parameters"].quote == "\u041e\u0442\u0431\u043e\u0439"

    @pytest.mark.asyncio
    async def test_scan_error_returns_none(self, mock_bot):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        with patch.object(relay, "_scan_directory", return_value=[]):
            result = await relay.send_common(chat_id=1, message_id=10, matched_word="x", subdir="otboy")

        assert result is None
        mock_bot.send_photo.assert_not_called()

    @pytest.mark.asyncio
    async def test_damaged_media_file_raises_telegram_bad_request(self, mock_bot):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        mock_files = [(Path("/fake/corrupt.jpg"), MEDIA_PHOTO)]
        with patch.object(relay, "_scan_directory", return_value=mock_files):
            mock_bot.send_photo.side_effect = TelegramBadRequest(
                method="sendPhoto",
                message="Bad Request: wrong file identifier"
            )
            await relay.send_common(chat_id=42, message_id=99, matched_word="\u043e\u0442\u0431\u043e\u0439", subdir="otboy")

        mock_bot.send_photo.assert_called_once()

    @pytest.mark.asyncio
    async def test_unsupported_format_in_send_by_type(self, mock_bot):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        with pytest.raises(ValueError, match="Unknown media_type"):
            await relay._send_by_type(
                chat_id=42,
                message_id=99,
                matched_word="test",
                filepath=Path("/fake/test.xyz"),
                media_type="document",
            )


# ═══════════════════════════════════════════════════════════════════
# G. CommonRelay — Cooldown Tests
# ═══════════════════════════════════════════════════════════════════


class TestCommonRelayCooldown:
    """Tests for CommonRelay shared cooldown behavior."""

    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.send_video = AsyncMock()
        return bot

    @pytest.fixture
    def mock_scan_files(self):
        return [(Path("/fake/photo.jpg"), MEDIA_PHOTO)]

    @pytest.mark.asyncio
    async def test_shared_cooldown_blocks_second(self, mock_bot, mock_scan_files):
        relay = CommonRelay(mock_bot, cooldown_seconds=60, media_base="/fake/media")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_scan_files):
            with patch.object(relay, "_media_base", "/fake/media"):
                with patch("services.common_relay.time.monotonic", return_value=fake_now):
                    await relay.send_common(chat_id=1, message_id=10, matched_word="otboy", subdir="otboy")
                assert mock_bot.send_photo.call_count == 1

                with patch("services.common_relay.time.monotonic", return_value=fake_now + 30):
                    await relay.send_common(chat_id=1, message_id=11, matched_word="bpla", subdir="danger")
                assert mock_bot.send_photo.call_count == 1

    @pytest.mark.asyncio
    async def test_cross_subservice_cooldown(self, mock_bot, mock_scan_files):
        relay = CommonRelay(mock_bot, cooldown_seconds=60, media_base="/fake/media")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_scan_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(chat_id=1, message_id=10, matched_word="otboy", subdir="otboy")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 30):
                await relay.send_common(chat_id=1, message_id=11, matched_word="bpla", subdir="danger")
            assert mock_bot.send_photo.call_count == 1

    @pytest.mark.asyncio
    async def test_cooldown_expired_allows(self, mock_bot, mock_scan_files):
        relay = CommonRelay(mock_bot, cooldown_seconds=1, media_base="/fake/media")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_scan_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(chat_id=1, message_id=10, matched_word="otboy", subdir="otboy")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 1.1):
                await relay.send_common(chat_id=1, message_id=11, matched_word="bpla", subdir="danger")
            assert mock_bot.send_photo.call_count == 2

    @pytest.mark.asyncio
    async def test_cooldown_per_chat_isolation(self, mock_bot, mock_scan_files):
        relay = CommonRelay(mock_bot, cooldown_seconds=60, media_base="/fake/media")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_scan_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(chat_id=1, message_id=10, matched_word="otboy", subdir="otboy")
                await relay.send_common(chat_id=2, message_id=20, matched_word="bpla", subdir="danger")
            assert mock_bot.send_photo.call_count == 2

    @pytest.mark.asyncio
    async def test_cooldown_zero_always_sends(self, mock_bot, mock_scan_files):
        relay = CommonRelay(mock_bot, cooldown_seconds=0, media_base="/fake/media")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_scan_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(chat_id=1, message_id=10, matched_word="otboy", subdir="otboy")
            with patch("services.common_relay.time.monotonic", return_value=fake_now + 0.1):
                await relay.send_common(chat_id=1, message_id=11, matched_word="bpla", subdir="danger")
            assert mock_bot.send_photo.call_count == 2

    @pytest.mark.asyncio
    async def test_first_call_no_cooldown_check(self, mock_bot, mock_scan_files):
        relay = CommonRelay(mock_bot, cooldown_seconds=60, media_base="/fake/media")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_scan_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(chat_id=1, message_id=10, matched_word="otboy", subdir="otboy")
            assert mock_bot.send_photo.call_count == 1

    @pytest.mark.asyncio
    async def test_cooldown_not_activated_on_send_error(self, mock_bot, mock_scan_files):
        relay = CommonRelay(mock_bot, cooldown_seconds=60, media_base="/fake/media")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_scan_files):
            mock_bot.send_photo.side_effect = TelegramBadRequest(
                method="sendPhoto",
                message="Bad Request: failed to send"
            )
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(chat_id=1, message_id=10, matched_word="otboy", subdir="otboy")

            assert 1 not in relay._cooldowns


# ═══════════════════════════════════════════════════════════════════
# H. Handler Tests
# ═══════════════════════════════════════════════════════════════════


class TestCommonHandlers:
    """Tests for otboy_handler and danger_handler (handlers/common.py)."""

    @pytest.fixture(autouse=True)
    def reset_relay(self):
        setup_common(None)
        yield
        setup_common(None)

    @pytest.mark.asyncio
    async def test_otboy_handler_calls_relay(self):
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        msg = make_message(text="\u043e\u0442\u0431\u043e\u0439", chat_id=-100456, message_id=789)
        await otboy_handler(msg, matched_word="\u043e\u0442\u0431\u043e\u0439")

        mock_relay.send_common.assert_called_once_with(
            chat_id=-100456,
            message_id=789,
            matched_word="\u043e\u0442\u0431\u043e\u0439",
            subdir="otboy",
        )

    @pytest.mark.asyncio
    async def test_danger_handler_calls_relay(self):
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        msg = make_message(text="\u0431\u043f\u043b\u0430", chat_id=-100789, message_id=555)
        await danger_handler(msg, matched_word="\u0431\u043f\u043b\u0430")

        mock_relay.send_common.assert_called_once_with(
            chat_id=-100789,
            message_id=555,
            matched_word="\u0431\u043f\u043b\u0430",
            subdir="danger",
        )

    @pytest.mark.asyncio
    async def test_otboy_handler_relay_none_returns_none(self):
        setup_common(None)
        msg = make_message(text="\u043e\u0442\u0431\u043e\u0439")
        result = await otboy_handler(msg, matched_word="\u043e\u0442\u0431\u043e\u0439")
        assert result is None

    @pytest.mark.asyncio
    async def test_danger_handler_relay_none_returns_none(self):
        setup_common(None)
        msg = make_message(text="\u0431\u043f\u043b\u0430")
        result = await danger_handler(msg, matched_word="\u0431\u043f\u043b\u0430")
        assert result is None

    @pytest.mark.asyncio
    async def test_otboy_handler_catches_exception(self):
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock(side_effect=RuntimeError("fail"))
        setup_common(mock_relay)

        msg = make_message(text="\u043e\u0442\u0431\u043e\u0439")
        await otboy_handler(msg, matched_word="\u043e\u0442\u0431\u043e\u0439")

    @pytest.mark.asyncio
    async def test_danger_handler_catches_exception(self):
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock(side_effect=RuntimeError("fail"))
        setup_common(mock_relay)

        msg = make_message(text="\u0431\u043f\u043b\u0430")
        await danger_handler(msg, matched_word="\u0431\u043f\u043b\u0430")

    @pytest.mark.asyncio
    async def test_setup_common_injects_relay(self):
        mock_relay = MagicMock()
        setup_common(mock_relay)

        import handlers.common as common_mod
        assert common_mod._relay is mock_relay

        setup_common(None)

    @pytest.mark.asyncio
    async def test_otboy_handler_with_case_preserving_word(self):
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        msg = make_message(text="\u0441\u043a\u0430\u0437\u0430\u043b\u0438 \u041e\u0442\u0431\u043e\u0439")
        await otboy_handler(msg, matched_word="\u041e\u0442\u0431\u043e\u0439")

        mock_relay.send_common.assert_called_once_with(
            chat_id=-100123,
            message_id=1,
            matched_word="\u041e\u0442\u0431\u043e\u0439",
            subdir="otboy",
        )


# ═══════════════════════════════════════════════════════════════════
# I. Integration Tests
# ═══════════════════════════════════════════════════════════════════


class TestCommonIntegration:
    """Integration tests: propagation, cross-component interactions."""

    @pytest.mark.asyncio
    async def test_otboy_handler_does_not_block_propagation(self):
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        msg = make_message(text="\u043e\u0442\u0431\u043e\u0439")
        result = await otboy_handler(msg, matched_word="\u043e\u0442\u0431\u043e\u0439")
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_danger_handler_does_not_block_propagation(self):
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        msg = make_message(text="\u0431\u043f\u043b\u0430")
        result = await danger_handler(msg, matched_word="\u0431\u043f\u043b\u0430")
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_otboy_filter_independent_of_user_id(self):
        f = OtboyWordFilter()
        for uid in [111, 479167456, 350803143, 999999999]:
            msg = make_message(text="\u043e\u0442\u0431\u043e\u0439", from_id=uid)
            result = await f(msg)
            assert result == {"matched_word": "\u043e\u0442\u0431\u043e\u0439"}

    @pytest.mark.asyncio
    async def test_danger_filter_independent_of_user_id(self):
        f = DangerWordFilter()
        for uid in [111, 479167456, 350803143, 999999999]:
            msg = make_message(text="\u0431\u043f\u043b\u0430", from_id=uid)
            result = await f(msg)
            assert result == {"matched_word": "\u0431\u043f\u043b\u0430"}

    @pytest.mark.asyncio
    async def test_both_filters_match_same_message(self):
        f_otboy = OtboyWordFilter()
        f_danger = DangerWordFilter()

        msg = make_message(text="\u043e\u0442\u0431\u043e\u0439 \u0431\u043f\u043b\u0430 \u0440\u0430\u043a\u0435\u0442\u043d\u0430\u044f \u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c")
        r1 = await f_otboy(msg)
        r2 = await f_danger(msg)
        assert r1 == {"matched_word": "\u043e\u0442\u0431\u043e\u0439"}
        assert r2 == {"matched_word": "\u0431\u043f\u043b\u0430"}

    @pytest.mark.asyncio
    async def test_message_with_both_otboy_and_danger_words(self):
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        msg = make_message(text="\u043e\u0442\u0431\u043e\u0439 \u0431\u043f\u043b\u0430 \u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c")
        await otboy_handler(msg, matched_word="\u043e\u0442\u0431\u043e\u0439")
        await danger_handler(msg, matched_word="\u0431\u043f\u043b\u0430")
        assert mock_relay.send_common.call_count == 2


# ═══════════════════════════════════════════════════════════════════
# J. Migration Tests
# ═══════════════════════════════════════════════════════════════════


class TestMigration:
    """Verify settings migration from OTBOY_* to COMMON_*."""

    def test_common_cooldown_exists(self):
        assert hasattr(settings, "COMMON_COOLDOWN")
        assert isinstance(settings.COMMON_COOLDOWN, float)
        assert settings.COMMON_COOLDOWN == 0

    def test_common_media_base_exists(self):
        assert hasattr(settings, "COMMON_MEDIA_BASE")
        assert settings.COMMON_MEDIA_BASE == "media/common"

    def test_danger_words_exists(self):
        assert hasattr(settings, "DANGER_WORDS")
        assert isinstance(settings.DANGER_WORDS, str)

    def test_otboy_cooldown_removed(self):
        assert not hasattr(settings, "OTBOY_COOLDOWN_SECONDS")

    def test_otboy_photo_path_removed(self):
        assert not hasattr(settings, "OTBOY_PHOTO_PATH")


# ═══════════════════════════════════════════════════════════════════
# K. Epic 18 — GIF Detection Tests (Bug B)
# ═══════════════════════════════════════════════════════════════════


class TestCommonRelayGifDetection:
    """Tests for GIF detection in filename (Epic 18 Bug B)."""

    @pytest.fixture
    def relay(self):
        bot = AsyncMock()
        return CommonRelay(bot, cooldown_seconds=0)

    def test_gif_in_middle_with_underscore(self, relay):
        assert relay._detect_media_type(Path("danger_02_gif.mp4")) == MEDIA_ANIMATION

    def test_gif_before_number(self, relay):
        assert relay._detect_media_type(Path("danger_zelelyot_gif_02.mp4")) == MEDIA_ANIMATION

    def test_gif_at_end_of_stem(self, relay):
        assert relay._detect_media_type(Path("danger_nahryuck_gif.mp4")) == MEDIA_ANIMATION

    def test_gif_at_start(self, relay):
        assert relay._detect_media_type(Path("gif_animation.mp4")) == MEDIA_ANIMATION

    def test_gift_not_detected_as_gif(self, relay):
        """'gift' should NOT be treated as 'gif'."""
        assert relay._detect_media_type(Path("file.gift.mp4")) == MEDIA_VIDEO

    def test_no_gif_in_name_is_video(self, relay):
        assert relay._detect_media_type(Path("danger_boom.mp4")) == MEDIA_VIDEO

    def test_gif_in_camelcase_name(self, relay):
        assert relay._detect_media_type(Path("my_GiF_file.mp4")) == MEDIA_ANIMATION

    def test_gif_with_dot_in_middle(self, relay):
        """file.giF.mp4 should be detected as animation ('.gif' in name)."""
        assert relay._detect_media_type(Path("my.giF.animation.mp4")) == MEDIA_ANIMATION


# ═══════════════════════════════════════════════════════════════════
# L. Epic 18 — Scan Robustness Tests (Bug A)
# ═══════════════════════════════════════════════════════════════════


class TestCommonRelayScanRobustness:
    """Tests for scan directory robustness (Epic 18 Bug A)."""

    @pytest.fixture
    def relay(self):
        bot = AsyncMock()
        return CommonRelay(bot, cooldown_seconds=0)

    def test_scan_logs_all_files(self, relay, tmp_path, caplog):
        subdir = tmp_path / "danger"
        subdir.mkdir()
        (subdir / "a.mp4").write_text("fake")
        (subdir / "b.mp4").write_text("fake")
        (subdir / "c.mp4").write_text("fake")

        relay._media_base = str(tmp_path)
        with caplog.at_level(logging.INFO):
            files = relay._scan_directory("danger")
        assert len(files) == 3
        log_text = caplog.text
        assert "a.mp4" in log_text
        assert "b.mp4" in log_text
        assert "c.mp4" in log_text

    def test_scan_skips_unreadable_file(self, relay, tmp_path, caplog):
        """Per-entry OSError should skip bad files, not crash the whole scan."""
        subdir = tmp_path / "danger"
        subdir.mkdir()
        (subdir / "good1.mp4").write_text("fake")
        bad_file = subdir / "bad_link.mp4"
        bad_file.write_text("fake")
        (subdir / "good2.mp4").write_text("fake")

        original_is_file = Path.is_file

        def mock_is_file(self_path):
            if self_path.name == "bad_link.mp4":
                raise OSError("Permission denied")
            return original_is_file(self_path)

        relay._media_base = str(tmp_path)
        with caplog.at_level(logging.WARNING):
            with patch.object(Path, "is_file", mock_is_file):
                files = relay._scan_directory("danger")
        assert len(files) == 2
        names = {f[0].name for f in files}
        assert names == {"good1.mp4", "good2.mp4"}
        assert "bad_link" in caplog.text

    def test_random_choice_covers_all_files_over_many_calls(self, relay, tmp_path):
        """Verify random.choice picks all files eventually (statistical test)."""
        subdir = tmp_path / "danger"
        subdir.mkdir()
        for i in range(1, 4):
            (subdir / f"file_{i}.mp4").write_text("fake")

        relay._media_base = str(tmp_path)
        picked = set()
        for _ in range(100):
            files = relay._scan_directory("danger")
            fpath, _ = random.choice(files)
            picked.add(fpath.name)
        assert picked == {"file_1.mp4", "file_2.mp4", "file_3.mp4"}


# ═══════════════════════════════════════════════════════════════════
# M. Epic 18 — Dual Cooldown Tests (Bug C)
# ═══════════════════════════════════════════════════════════════════


class TestCommonRelayDualCooldown:
    """Tests for dual-layer cooldown (Epic 18 Bug C)."""

    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.send_video = AsyncMock()
        bot.send_animation = AsyncMock()
        return bot

    @pytest.fixture
    def mock_files(self):
        return [(Path("/fake/photo.jpg"), MEDIA_PHOTO)]

    @pytest.mark.asyncio
    async def test_danger_then_otboy_blocked_by_shared(self, mock_bot, mock_files):
        """danger → otboy: otboy blocked by shared cooldown."""
        relay = CommonRelay(mock_bot, cooldown_seconds=60, danger_cooldown_seconds=60, media_base="/fake")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 30):
                await relay.send_common(1, 11, "отбой", "otboy")
            assert mock_bot.send_photo.call_count == 1  # blocked by shared

    @pytest.mark.asyncio
    async def test_danger_then_danger_blocked_by_both(self, mock_bot, mock_files):
        """danger → danger: blocked by both cooldowns."""
        relay = CommonRelay(mock_bot, cooldown_seconds=60, danger_cooldown_seconds=60, media_base="/fake")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 30):
                await relay.send_common(1, 11, "ракета", "danger")
            assert mock_bot.send_photo.call_count == 1  # blocked

    @pytest.mark.asyncio
    async def test_danger_after_danger_cooldown_expired(self, mock_bot, mock_files):
        """danger → danger after 70s: both cooldowns expired, sends."""
        relay = CommonRelay(mock_bot, cooldown_seconds=60, danger_cooldown_seconds=60, media_base="/fake")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 70):
                await relay.send_common(1, 11, "ракета", "danger")
            assert mock_bot.send_photo.call_count == 2  # sends

    @pytest.mark.asyncio
    async def test_danger_then_otboy_after_shared_expired(self, mock_bot, mock_files):
        """danger → otboy after 70s: shared expired, otboy sends."""
        relay = CommonRelay(mock_bot, cooldown_seconds=60, danger_cooldown_seconds=60, media_base="/fake")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 70):
                await relay.send_common(1, 11, "отбой", "otboy")
            assert mock_bot.send_photo.call_count == 2  # otboy sends

    @pytest.mark.asyncio
    async def test_otboy_then_danger_blocked_by_shared(self, mock_bot, mock_files):
        """otboy → danger: danger blocked by shared cooldown."""
        relay = CommonRelay(mock_bot, cooldown_seconds=60, danger_cooldown_seconds=60, media_base="/fake")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "отбой", "otboy")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 30):
                await relay.send_common(1, 11, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 1  # blocked by shared

    @pytest.mark.asyncio
    async def test_danger_only_cooldown_with_shared_zero(self, mock_bot, mock_files):
        """shared=0, danger=60: danger blocked by danger-only cooldown."""
        relay = CommonRelay(mock_bot, cooldown_seconds=0, danger_cooldown_seconds=60, media_base="/fake")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 30):
                await relay.send_common(1, 11, "ракета", "danger")
            assert mock_bot.send_photo.call_count == 1  # blocked by danger cooldown

    @pytest.mark.asyncio
    async def test_otboy_not_blocked_by_danger_cooldown(self, mock_bot, mock_files):
        """shared=0, danger=60: otboy is NOT blocked by danger cooldown."""
        relay = CommonRelay(mock_bot, cooldown_seconds=0, danger_cooldown_seconds=60, media_base="/fake")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 5):
                await relay.send_common(1, 11, "отбой", "otboy")
            assert mock_bot.send_photo.call_count == 2  # otboy NOT blocked by danger

    @pytest.mark.asyncio
    async def test_danger_with_zero_danger_cooldown_blocked_by_shared(self, mock_bot, mock_files):
        """shared=60, danger=0: danger blocked by shared cooldown."""
        relay = CommonRelay(mock_bot, cooldown_seconds=60, danger_cooldown_seconds=0, media_base="/fake")
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 30):
                await relay.send_common(1, 11, "ракета", "danger")
            assert mock_bot.send_photo.call_count == 1  # blocked by shared

    @pytest.mark.asyncio
    async def test_default_danger_cooldown_is_zero(self, mock_bot, mock_files):
        """Without explicit danger_cooldown_seconds, it defaults to 0 (no extra restriction)."""
        relay = CommonRelay(mock_bot, cooldown_seconds=60, media_base="/fake")
        assert relay._danger_cooldown_seconds == 0
        assert relay._danger_cooldowns == {}


# ═══════════════════════════════════════════════════════════════════
# N. Epic 22 — Mimic Forwards Gate (D52)
# ═══════════════════════════════════════════════════════════════════


class TestMimicForwardsGate:
    """D52 (Epic 22): mimic_handler skips forwarded messages unless enabled."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        import handlers.common as common_mod
        original_ids = common_mod._VICTIM_IDS
        common_mod._VICTIM_IDS = [111]
        mock_relay = MagicMock()
        mock_relay.should_trigger = MagicMock(return_value=True)
        mock_relay.send_mimic = AsyncMock()
        mock_relay.mark_sent = MagicMock()
        setup_common_mimic(mock_relay)
        yield common_mod, mock_relay
        setup_common_mimic(None)
        common_mod._VICTIM_IDS = original_ids

    @pytest.mark.asyncio
    async def test_forwarded_off_returns_unhandled(self, _reset):
        """forwarded + MIMIC_FORWARDS_ENABLED=False (default) → UNHANDLED, no mimic."""
        common_mod, mock_relay = _reset
        msg = make_message(text="раз два три четыре пять шесть", from_id=111)
        msg.forward_origin = MagicMock()

        result = await mimic_handler(msg)

        assert result is UNHANDLED
        mock_relay.send_mimic.assert_not_called()

    @pytest.mark.asyncio
    async def test_ordinary_message_mimics(self, _reset):
        """Ordinary (not forwarded) message → mimic works as before."""
        common_mod, mock_relay = _reset
        msg = make_message(text="раз два три четыре пять шесть", from_id=111)
        msg.forward_origin = None

        result = await mimic_handler(msg)

        assert result is UNHANDLED
        mock_relay.send_mimic.assert_called_once()

    @pytest.mark.asyncio
    async def test_forwarded_on_mimics(self, _reset):
        """forwarded + MIMIC_FORWARDS_ENABLED=True → mimic fires."""
        common_mod, mock_relay = _reset
        mod = replace(settings, MIMIC_FORWARDS_ENABLED=True)
        msg = make_message(text="раз два три четыре пять шесть", from_id=111)
        msg.forward_origin = MagicMock()

        with patch.object(common_mod, "settings", mod):
            result = await mimic_handler(msg)

        assert result is UNHANDLED
        mock_relay.send_mimic.assert_called_once()

    @pytest.mark.asyncio
    async def test_forwarded_on_without_content_skips(self, _reset):
        """forwarded + enabled but no text/caption → skip, no send."""
        common_mod, mock_relay = _reset
        mod = replace(settings, MIMIC_FORWARDS_ENABLED=True)
        msg = make_message(text=None, caption=None, from_id=111)
        msg.forward_origin = MagicMock()

        with patch.object(common_mod, "settings", mod):
            result = await mimic_handler(msg)

        assert result is None
        mock_relay.send_mimic.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# O. Epic 30 — selfdev/work (T-227/T-228): relay cooldowns + handlers
# ═══════════════════════════════════════════════════════════════════


class TestCommonRelaySelfdevWorkCooldowns:
    """Epic 30 (39.5): generic пер-сабдир cooldown-слой (Layer 1)."""

    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.send_video = AsyncMock()
        bot.send_animation = AsyncMock()
        return bot

    @pytest.fixture
    def mock_files(self):
        return [(Path("/fake/photo.jpg"), MEDIA_PHOTO)]

    @pytest.mark.asyncio
    async def test_selfdev_then_selfdev_blocked_by_selfdev_cooldown(self, mock_bot, mock_files):
        """selfdev → selfdev через <5m: пер-сабдирный коулдаун блокирует."""
        relay = CommonRelay(
            mock_bot,
            cooldown_seconds=0,
            selfdev_cooldown_seconds=300,
            media_base="/fake",
        )
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "прокачка", "selfdev")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 60):
                await relay.send_common(1, 11, "саморазвитие", "selfdev")
            assert mock_bot.send_photo.call_count == 1  # blocked

    @pytest.mark.asyncio
    async def test_selfdev_after_selfdev_cooldown_expired(self, mock_bot, mock_files):
        """selfdev → selfdev через >5m: отправка проходит."""
        relay = CommonRelay(
            mock_bot,
            cooldown_seconds=0,
            selfdev_cooldown_seconds=300,
            media_base="/fake",
        )
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "прокачка", "selfdev")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 301):
                await relay.send_common(1, 11, "саморазвитие", "selfdev")
            assert mock_bot.send_photo.call_count == 2  # sends

    @pytest.mark.asyncio
    async def test_selfdev_does_not_block_work(self, mock_bot, mock_files):
        """Сабдиры независимы: selfdev не блокирует work при shared=0."""
        relay = CommonRelay(
            mock_bot,
            cooldown_seconds=0,
            selfdev_cooldown_seconds=300,
            work_cooldown_seconds=300,
            media_base="/fake",
        )
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "прокачка", "selfdev")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 5):
                await relay.send_common(1, 11, "устал", "work")
            assert mock_bot.send_photo.call_count == 2  # work НЕ заблокирован selfdev

    @pytest.mark.asyncio
    async def test_work_then_work_blocked_by_work_cooldown(self, mock_bot, mock_files):
        relay = CommonRelay(
            mock_bot,
            cooldown_seconds=0,
            work_cooldown_seconds=300,
            media_base="/fake",
        )
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "устал", "work")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 60):
                await relay.send_common(1, 11, "заебался", "work")
            assert mock_bot.send_photo.call_count == 1  # blocked

    @pytest.mark.asyncio
    async def test_selfdev_does_not_block_danger_and_otboy(self, mock_bot, mock_files):
        """shared=0: selfdev-коулдаун не трогает danger/otboy."""
        relay = CommonRelay(
            mock_bot,
            cooldown_seconds=0,
            danger_cooldown_seconds=60,
            selfdev_cooldown_seconds=300,
            media_base="/fake",
        )
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "прокачка", "selfdev")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 5):
                await relay.send_common(1, 11, "бпла", "danger")
            assert mock_bot.send_photo.call_count == 2  # danger не заблокирован selfdev

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 6):
                await relay.send_common(1, 12, "отбой", "otboy")
            assert mock_bot.send_photo.call_count == 3  # otboy не заблокирован

    @pytest.mark.asyncio
    async def test_selfdev_blocked_by_shared(self, mock_bot, mock_files):
        """shared=60: selfdev после любой отправки заблокирован общим слоем."""
        relay = CommonRelay(
            mock_bot,
            cooldown_seconds=60,
            selfdev_cooldown_seconds=300,
            media_base="/fake",
        )
        fake_now = 1000.0

        with patch.object(relay, "_scan_directory", return_value=mock_files):
            with patch("services.common_relay.time.monotonic", return_value=fake_now):
                await relay.send_common(1, 10, "прокачка", "selfdev")
            assert mock_bot.send_photo.call_count == 1

            with patch("services.common_relay.time.monotonic", return_value=fake_now + 30):
                await relay.send_common(1, 11, "устал", "work")
            assert mock_bot.send_photo.call_count == 1  # blocked by shared

    @pytest.mark.asyncio
    async def test_cooldown_not_stamped_on_send_error(self, mock_bot):
        relay = CommonRelay(
            mock_bot,
            cooldown_seconds=0,
            selfdev_cooldown_seconds=300,
            media_base="/fake",
        )
        mock_files = [(Path("/fake/corrupt.jpg"), MEDIA_PHOTO)]
        with patch.object(relay, "_scan_directory", return_value=mock_files):
            mock_bot.send_photo.side_effect = TelegramBadRequest(
                method="sendPhoto",
                message="Bad Request: failed to send",
            )
            await relay.send_common(chat_id=1, message_id=10, matched_word="прокачка", subdir="selfdev")

        assert 1 not in relay._cooldowns
        assert 1 not in relay._subdir_cooldowns.get("selfdev", {})

    @pytest.mark.asyncio
    async def test_default_selfdev_work_cooldowns_are_zero(self, mock_bot, mock_files):
        relay = CommonRelay(mock_bot, cooldown_seconds=60, media_base="/fake")
        assert relay._subdir_cooldown_seconds["selfdev"] == 0
        assert relay._subdir_cooldown_seconds["work"] == 0

    def test_danger_alias_backward_compat(self, mock_bot):
        """Epic 18-алиасы живы (тест :1304-1308 зелёный + прямое соответствие)."""
        relay = CommonRelay(
            mock_bot,
            cooldown_seconds=60,
            danger_cooldown_seconds=30,
            media_base="/fake",
        )
        assert relay._danger_cooldown_seconds == 30
        assert relay._danger_cooldowns is relay._subdir_cooldowns["danger"]
        relay._danger_cooldowns[42] = 123.0
        assert relay._subdir_cooldowns["danger"][42] == 123.0


class TestSelfdevWorkHandlers:
    """Epic 30: selfdev_handler/work_handler (handlers/common.py)."""

    @pytest.fixture(autouse=True)
    def reset_relay(self):
        setup_common(None)
        yield
        setup_common(None)

    @pytest.mark.asyncio
    async def test_selfdev_handler_calls_relay_with_selfdev_subdir(self):
        from handlers.common import selfdev_handler

        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        msg = make_message(text="саморазвитие", chat_id=-100456, message_id=789)
        result = await selfdev_handler(msg, matched_word="саморазвитие")

        assert result is UNHANDLED
        mock_relay.send_common.assert_called_once_with(
            chat_id=-100456,
            message_id=789,
            matched_word="саморазвитие",
            subdir="selfdev",
        )

    @pytest.mark.asyncio
    async def test_work_handler_calls_relay_with_work_subdir(self):
        from handlers.common import work_handler

        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        msg = make_message(text="устал", chat_id=-100789, message_id=555)
        result = await work_handler(msg, matched_word="устал")

        assert result is UNHANDLED
        mock_relay.send_common.assert_called_once_with(
            chat_id=-100789,
            message_id=555,
            matched_word="устал",
            subdir="work",
        )

    @pytest.mark.asyncio
    async def test_selfdev_handler_relay_none_returns_none(self):
        from handlers.common import selfdev_handler

        setup_common(None)
        msg = make_message(text="саморазвитие")
        result = await selfdev_handler(msg, matched_word="саморазвитие")
        assert result is None

    @pytest.mark.asyncio
    async def test_work_handler_relay_none_returns_none(self):
        from handlers.common import work_handler

        setup_common(None)
        msg = make_message(text="устал")
        result = await work_handler(msg, matched_word="устал")
        assert result is None

    @pytest.mark.asyncio
    async def test_selfdev_handler_catches_exception(self):
        from handlers.common import selfdev_handler

        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock(side_effect=RuntimeError("fail"))
        setup_common(mock_relay)

        msg = make_message(text="саморазвитие")
        result = await selfdev_handler(msg, matched_word="саморазвитие")
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_work_handler_catches_exception(self):
        from handlers.common import work_handler

        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock(side_effect=RuntimeError("fail"))
        setup_common(mock_relay)

        msg = make_message(text="устал")
        result = await work_handler(msg, matched_word="устал")
        assert result is UNHANDLED


# ── Epic 52 (T-409, D213): common/work env-выключатели ──


class TestCommonMediaFlags:
    """T-409: COMMON_WORK_MEDIA_ENABLED (точечный) × COMMON_MEDIA_ENABLED (глобальный)."""

    @pytest.fixture(autouse=True)
    def reset_relay(self):
        setup_common(None)
        yield
        setup_common(None)

    # ── work=false → work_handler UNHANDLED, relay не вызван ──

    @pytest.mark.asyncio
    async def test_work_disabled_handler_returns_unhandled(self):
        import handlers.common as common_mod
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        mod = replace(settings, COMMON_WORK_MEDIA_ENABLED=False)
        with patch.object(common_mod, "settings", mod):
            from handlers.common import work_handler
            msg = make_message(text="устал", chat_id=-100789, message_id=555)
            result = await work_handler(msg, matched_word="устал")

        assert result is UNHANDLED
        mock_relay.send_common.assert_not_called()

    @pytest.mark.asyncio
    async def test_work_disabled_still_returns_unhandled_without_relay(self):
        """work=false и relay=None → UNHANDLED (не падает на _relay-проверке)."""
        import handlers.common as common_mod
        mod = replace(settings, COMMON_WORK_MEDIA_ENABLED=False)
        with patch.object(common_mod, "settings", mod):
            from handlers.common import work_handler
            msg = make_message(text="заебался")
            result = await work_handler(msg, matched_word="заебался")

        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_work_enabled_default_calls_relay(self):
        """default (флаг не трогали) — work работает как раньше."""
        import handlers.common as common_mod
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        from handlers.common import work_handler
        msg = make_message(text="устал", chat_id=-100789, message_id=555)
        result = await work_handler(msg, matched_word="устал")

        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_work_flag_from_hot_cache_true(self):
        """ФИКС 2026-09-03: work-флаг читается через hot.get —
        значение True из ConfigCache (веб-админка) применяется даже при
        settings=False (env)."""
        import handlers.common as common_mod
        from services import hot_config as hot

        class _Cache:
            def __init__(self, data):
                self._data = data

            def get(self, key, default=None):
                return self._data.get(key, default)

        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)
        old_cache = hot._cache
        hot.set_config_cache(_Cache({"flags.common_work_media_enabled": True}))
        try:
            mod = replace(settings, COMMON_WORK_MEDIA_ENABLED=False)
            with patch.object(common_mod, "settings", mod):
                from handlers.common import work_handler
                msg = make_message(text="устал", chat_id=-100789,
                                   message_id=555)
                result = await work_handler(msg, matched_word="устал")
            assert result is UNHANDLED
            mock_relay.send_common.assert_called_once()   # hot=True победил
        finally:
            hot.set_config_cache(old_cache)

    @pytest.mark.asyncio
    async def test_work_flag_absent_from_hot_falls_back_to_settings(self):
        """ФИКС: флага НЕТ в кэше → фолбек на settings (default=True) →
        relay вызывается."""
        from services import hot_config as hot

        class _Cache:
            def __init__(self, data):
                self._data = data

            def get(self, key, default=None):
                return self._data.get(key, default)

        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)
        old_cache = hot._cache
        hot.set_config_cache(_Cache({}))
        try:
            from handlers.common import work_handler
            msg = make_message(text="устал", chat_id=-100789, message_id=555)
            result = await work_handler(msg, matched_word="устал")
            assert result is UNHANDLED
            mock_relay.send_common.assert_called_once()
        finally:
            hot.set_config_cache(old_cache)
        mock_relay.send_common.assert_called_once_with(
            chat_id=-100789,
            message_id=555,
            matched_word="устал",
            subdir="work",
        )

    # ── global=false → send_common молчит для ВСЕХ сабдиров ──

    @pytest.mark.asyncio
    async def test_global_disabled_all_subdirs_silent(self):
        import services.common_relay as relay_mod
        bot = AsyncMock()
        relay = CommonRelay(bot, cooldown_seconds=0, media_base="/fake/media")

        mod = replace(settings, COMMON_MEDIA_ENABLED=False)
        with patch.object(relay_mod, "settings", mod):
            with patch.object(relay, "_scan_directory",
                              return_value=[(Path("/fake/photo.jpg"), MEDIA_PHOTO)]):
                for subdir in ("otboy", "danger", "selfdev", "work"):
                    await relay.send_common(1, 10, "слово", subdir)

        bot.send_photo.assert_not_called()
        bot.send_video.assert_not_called()
        bot.send_animation.assert_not_called()

    @pytest.mark.asyncio
    async def test_global_disabled_even_with_work_enabled(self):
        """GLOBAL=false + WORK=true → всё равно молчит (гейт в relay — верхний)."""
        import services.common_relay as relay_mod
        bot = AsyncMock()
        relay = CommonRelay(bot, cooldown_seconds=0, media_base="/fake/media")

        mod = replace(settings, COMMON_MEDIA_ENABLED=False, COMMON_WORK_MEDIA_ENABLED=True)
        with patch.object(relay_mod, "settings", mod):
            with patch.object(relay, "_scan_directory",
                              return_value=[(Path("/fake/photo.jpg"), MEDIA_PHOTO)]):
                await relay.send_common(1, 10, "устал", "work")

        bot.send_photo.assert_not_called()

    # ── изоляция: work=false ≠ otboy/danger/selfdev off ──

    @pytest.mark.asyncio
    async def test_work_disabled_other_handlers_still_send(self):
        """WORK=false → молчит ТОЛЬКО work; otboy/danger/selfdev шлют."""
        import handlers.common as common_mod
        mock_relay = MagicMock()
        mock_relay.send_common = AsyncMock()
        setup_common(mock_relay)

        mod = replace(settings, COMMON_WORK_MEDIA_ENABLED=False)
        with patch.object(common_mod, "settings", mod):
            from handlers.common import (danger_handler, otboy_handler,
                                         selfdev_handler)
            await otboy_handler(make_message(text="отбой"), matched_word="отбой")
            await danger_handler(make_message(text="бпла"), matched_word="бпла")
            await selfdev_handler(make_message(text="саморазвитие"), matched_word="саморазвитие")

        assert mock_relay.send_common.call_count == 3
        subdirs = [c.kwargs["subdir"] for c in mock_relay.send_common.call_args_list]
        assert set(subdirs) == {"otboy", "danger", "selfdev"}

    @pytest.mark.asyncio
    async def test_global_enabled_default_sends(self):
        """default (global флаг не трогали) — media шлются."""
        import services.common_relay as relay_mod
        bot = AsyncMock()
        relay = CommonRelay(bot, cooldown_seconds=0, media_base="/fake/media")

        with patch.object(relay, "_scan_directory",
                          return_value=[(Path("/fake/photo.jpg"), MEDIA_PHOTO)]):
            await relay.send_common(1, 10, "отбой", "otboy")

        bot.send_photo.assert_called_once()


class TestCommonRouterHandlerOrder:
    """D91: порядок хендлеров в common_router: otboy → danger → selfdev → work → mimic."""

    def test_handler_order_in_common_router(self):
        from handlers.common import common_router

        names = [h.callback.__name__ for h in common_router.message.handlers]
        expected = ["otboy_handler", "danger_handler", "selfdev_handler", "work_handler", "mimic_handler"]
        assert names == expected
