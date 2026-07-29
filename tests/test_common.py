"""Tests for Epic 15 — Common Service Refactoring.

Covers:
  - OtboyWordFilter: matching, word boundaries, case-insensitivity
  - DangerWordFilter: matching, word boundaries, case-insensitivity, custom config
  - CommonRelay: _detect_media_type, _scan_directory, send_common, cooldown
  - Handlers: otboy_handler, danger_handler, relay guard, propagation
  - Migration: settings fields renamed/removed
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import FSInputFile, ReplyParameters
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramBadRequest

from config.settings import settings
from filters.danger_word import DangerWordFilter, _build_danger_patterns, _parse_danger_words
from filters.otboy_word import OtboyWordFilter
from handlers.common import danger_handler, otboy_handler, setup_common
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
        f = DangerWordFilter()
        msg = make_message(text="\u0432\u0441\u0435 \u0432 \u0443\u043a\u0440\u044b\u0442\u0438\u0435")
        result = await f(msg)
        assert result is not False
        assert "укрытие" in result["matched_word"].lower()

    @pytest.mark.asyncio
    async def test_bunker_matches(self):
        f = DangerWordFilter()
        msg = make_message(text="\u0437\u0430\u0445\u043e\u0434\u0438 \u0432 \u0431\u0443\u043d\u043a\u0435\u0440")
        result = await f(msg)
        assert result is not False
        assert "бункер" in result["matched_word"].lower()

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
        # Expanded WAR_WORDS list from filters/war_word.py (T-109)
        assert "\u0431\u043f\u043b\u0430" in result
        assert "\u0434\u0440\u043e\u043d" in result
        assert "\u0440\u0430\u043a\u0435\u0442\u0430" in result
        assert "\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c" in result
        assert "\u0432\u0437\u0440\u044b\u0432" in result
        assert len(result) > 100

    def test_parse_danger_words_default_list_length(self):
        result = _parse_danger_words("")
        # Expanded WAR_WORDS list from filters/war_word.py (T-109)
        assert len(result) > 100


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

    def test_common_cooldown_seconds_exists(self):
        assert hasattr(settings, "COMMON_COOLDOWN_SECONDS")
        assert isinstance(settings.COMMON_COOLDOWN_SECONDS, float)
        assert settings.COMMON_COOLDOWN_SECONDS == 0

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
