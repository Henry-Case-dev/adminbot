"""Tests for Epic 19 — Olya Service.

Covers:
  - OlyaVideoFilter: user match, media type, caption detection, repost detection, always_send
  - OlyaRelay: _detect_media_type, _scan_directory, send_olya, cooldown
  - Handlers: olya_handler, service guard, propagation
  - Integration: filter → handler → service pipeline, no-reply constraint
"""
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.enums import ContentType
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from filters.olya_video import OlyaVideoFilter
from handlers.olya import olya_handler, setup_olya
from services.olya_relay import OlyaRelay


# ── Helpers ──


@pytest.fixture
def olya_filter():
    return OlyaVideoFilter()


@pytest.fixture
def olya_user_id():
    return settings.OLYA_USER_ID


def _modified_settings(**overrides):
    return replace(settings, **overrides)


# ═══════════════════════════════════════════════════════════════════
# A. OlyaVideoFilter Tests
# ═══════════════════════════════════════════════════════════════════


class TestOlyaVideoFilter:
    """Unit tests for OlyaVideoFilter."""

    @pytest.mark.asyncio
    async def test_filter_user_mismatch(self, olya_filter, make_message):
        msg = make_message(from_id=999, text=None, content_type=ContentType.VIDEO)
        result = await olya_filter(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_filter_user_match_video(self, olya_filter, make_message, olya_user_id):
        msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
        result = await olya_filter(msg)
        assert isinstance(result, dict)
        assert result == {"is_saveasbot": False, "matched_caption": False}

    @pytest.mark.asyncio
    async def test_filter_user_match_photo_when_media_type_photo(self, make_message, olya_user_id):
        import filters.olya_video as filter_mod
        mod = _modified_settings(OLYA_MEDIA_TYPE="photo")
        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.PHOTO)
            result = await f(msg)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_filter_wrong_media_type(self, olya_filter, make_message, olya_user_id):
        msg = make_message(from_id=olya_user_id, content_type=ContentType.TEXT)
        result = await olya_filter(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_filter_disabled(self, make_message, olya_user_id):
        import filters.olya_video as filter_mod
        mod = _modified_settings(OLYA_ENABLED=False)
        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
            result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_filter_caption_detected(self, make_message, olya_user_id):
        import filters.olya_video as filter_mod
        cap_text = settings.OLYA_CAPTION_TEXT
        mod = _modified_settings(OLYA_ALWAYS_SEND=False, OLYA_CAPTION_ENABLED=True)
        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO, caption=cap_text)
            result = await f(msg)
        assert isinstance(result, dict)
        assert result["matched_caption"] is True

    @pytest.mark.asyncio
    async def test_filter_caption_not_detected(self, make_message, olya_user_id):
        import filters.olya_video as filter_mod
        mod = _modified_settings(OLYA_ALWAYS_SEND=False, OLYA_CAPTION_ENABLED=True)
        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO, caption="some other text")
            result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_filter_repost_saveasbot(self, make_message, olya_user_id):
        from aiogram.types import MessageOriginChannel
        import filters.olya_video as filter_mod

        mod = _modified_settings(OLYA_ALWAYS_SEND=False, OLYA_REPOST_ENABLED=True)
        origin = MagicMock(spec=MessageOriginChannel)
        origin.chat = MagicMock()
        origin.chat.id = 523131145

        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO, forward_origin=origin)
            result = await f(msg)
        assert isinstance(result, dict)
        assert result["is_saveasbot"] is True

    @pytest.mark.asyncio
    async def test_filter_repost_not_saveasbot(self, make_message, olya_user_id):
        from aiogram.types import MessageOriginChannel
        import filters.olya_video as filter_mod

        mod = _modified_settings(OLYA_ALWAYS_SEND=False, OLYA_REPOST_ENABLED=True)
        origin = MagicMock(spec=MessageOriginChannel)
        origin.chat = MagicMock()
        origin.chat.id = 999999

        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO, forward_origin=origin)
            result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_filter_always_send_false_no_match(self, make_message, olya_user_id):
        import filters.olya_video as filter_mod
        mod = _modified_settings(OLYA_ALWAYS_SEND=False, OLYA_CAPTION_ENABLED=False, OLYA_REPOST_ENABLED=False)
        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
            result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_filter_always_send_true_no_match(self, make_message, olya_user_id):
        import filters.olya_video as filter_mod
        mod = _modified_settings(OLYA_ALWAYS_SEND=True, OLYA_CAPTION_ENABLED=False, OLYA_REPOST_ENABLED=False)
        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
            result = await f(msg)
        assert isinstance(result, dict)
        assert result == {"is_saveasbot": False, "matched_caption": False}


# ═══════════════════════════════════════════════════════════════════
# B. OlyaRelay — Media Type Detection
# ═══════════════════════════════════════════════════════════════════


class TestOlyaRelayDetectMediaType:
    """Tests for OlyaRelay._detect_media_type."""

    @pytest.fixture
    def relay(self, mock_bot):
        return OlyaRelay(mock_bot, cooldown_seconds=0, media_base="/fake")

    def test_detect_media_type_photo_jpg(self, relay):
        assert relay._detect_media_type(Path("photo.jpg")) == OlyaRelay.MEDIA_PHOTO

    def test_detect_media_type_video_mp4(self, relay):
        assert relay._detect_media_type(Path("video.mp4")) == OlyaRelay.MEDIA_VIDEO

    def test_detect_media_type_animation(self, relay):
        assert relay._detect_media_type(Path("fun_gif.mp4")) == OlyaRelay.MEDIA_ANIMATION

    def test_detect_media_type_audio_mp3(self, relay):
        assert relay._detect_media_type(Path("sound.mp3")) == OlyaRelay.MEDIA_AUDIO

    def test_detect_media_type_voice_ogg(self, relay):
        assert relay._detect_media_type(Path("msg.ogg")) == OlyaRelay.MEDIA_VOICE

    def test_detect_media_type_unsupported(self, relay):
        assert relay._detect_media_type(Path("readme.txt")) == OlyaRelay.MEDIA_VIDEO


# ═══════════════════════════════════════════════════════════════════
# C. OlyaRelay — Scan Directory
# ═══════════════════════════════════════════════════════════════════


class TestOlyaRelayScanDirectory:
    """Tests for OlyaRelay._scan_directory."""

    @pytest.fixture
    def relay(self, mock_bot):
        return OlyaRelay(mock_bot, cooldown_seconds=0, media_base="/fake")

    def test_scan_empty_directory(self, relay, tmp_path):
        subdir = tmp_path / "cringe"
        subdir.mkdir()
        relay._media_base = subdir
        files = relay._scan_directory()
        assert files == []

    def test_scan_directory_with_files(self, relay, tmp_path):
        subdir = tmp_path / "cringe"
        subdir.mkdir()
        (subdir / "a.mp4").write_text("fake")
        (subdir / "b.jpg").write_text("fake")
        (subdir / "c.mp3").write_text("fake")
        relay._media_base = subdir
        files = relay._scan_directory()
        assert len(files) == 3
        names = {f.name for f in files}
        assert names == {"a.mp4", "b.jpg", "c.mp3"}

    def test_scan_missing_directory_returns_empty(self, relay, tmp_path):
        relay._media_base = tmp_path / "nonexistent"
        files = relay._scan_directory()
        assert files == []


# ═══════════════════════════════════════════════════════════════════
# D. OlyaRelay — Send Olya / Cooldown
# ═══════════════════════════════════════════════════════════════════


class TestOlyaRelaySendOlya:
    """Tests for OlyaRelay.send_olya and cooldown."""

    @pytest.fixture
    def relay(self, mock_bot):
        relay = OlyaRelay(mock_bot, cooldown_seconds=60, media_base="/fake")
        mock_bot.send_photo = AsyncMock()
        mock_bot.send_video = AsyncMock()
        mock_bot.send_animation = AsyncMock()
        mock_bot.send_audio = AsyncMock()
        mock_bot.send_voice = AsyncMock()
        return relay

    @pytest.mark.asyncio
    async def test_send_olya_cooldown_active(self, relay, mock_bot, tmp_path):
        subdir = tmp_path / "cringe"
        subdir.mkdir()
        (subdir / "test.mp4").write_text("fake")
        relay._media_base = subdir
        relay._cooldown_seconds = 60

        with patch("services.olya_relay.time.monotonic", return_value=1000.0):
            result1 = await relay.send_olya(42)
        assert result1 is True
        mock_bot.send_video.assert_called_once()

        mock_bot.reset_mock()
        with patch("services.olya_relay.time.monotonic", return_value=1030.0):
            result2 = await relay.send_olya(42)
        assert result2 is False
        mock_bot.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_olya_cooldown_expired(self, relay, mock_bot, tmp_path):
        subdir = tmp_path / "cringe"
        subdir.mkdir()
        (subdir / "test.mp4").write_text("fake")
        relay._media_base = subdir
        relay._cooldown_seconds = 60

        with patch("services.olya_relay.time.monotonic", return_value=1000.0):
            await relay.send_olya(42)
        assert mock_bot.send_video.call_count == 1

        mock_bot.reset_mock()
        with patch("services.olya_relay.time.monotonic", return_value=1100.0):
            result2 = await relay.send_olya(42)
        assert result2 is True
        mock_bot.send_video.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_olya_no_files(self, relay, tmp_path):
        relay._media_base = tmp_path / "cringe"
        relay._media_base.mkdir()
        result = await relay.send_olya(42)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_olya_success(self, relay, mock_bot, tmp_path):
        subdir = tmp_path / "cringe"
        subdir.mkdir()
        (subdir / "test.jpg").write_text("fake")
        relay._media_base = subdir
        relay._cooldown_seconds = 0

        result = await relay.send_olya(42)
        assert result is True
        mock_bot.send_photo.assert_called_once()
        call_kwargs = mock_bot.send_photo.call_args.kwargs
        assert "reply_parameters" not in call_kwargs
        assert "reply_to_message_id" not in call_kwargs


# ═══════════════════════════════════════════════════════════════════
# E. Handler Tests
# ═══════════════════════════════════════════════════════════════════


class TestOlyaHandler:
    """Tests for olya_handler (handlers/olya.py)."""

    @pytest.fixture(autouse=True)
    def reset_service(self):
        setup_olya(None)
        yield
        setup_olya(None)

    @pytest.mark.asyncio
    async def test_handler_service_none(self, make_message, olya_user_id):
        setup_olya(None)
        msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
        result = await olya_handler(msg)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_handler_calls_service(self, make_message, olya_user_id):
        mock_service = MagicMock()
        mock_service.send_olya = AsyncMock(return_value=True)
        setup_olya(mock_service)

        msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
        result = await olya_handler(msg)
        mock_service.send_olya.assert_called_once_with(msg.chat.id)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_handler_returns_unhandled(self, make_message, olya_user_id):
        mock_service = MagicMock()
        mock_service.send_olya = AsyncMock(return_value=True)
        setup_olya(mock_service)

        msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
        result = await olya_handler(msg)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_handler_service_exception(self, make_message, olya_user_id):
        mock_service = MagicMock()
        mock_service.send_olya = AsyncMock(side_effect=RuntimeError("fail"))
        setup_olya(mock_service)

        msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
        result = await olya_handler(msg)
        assert result is UNHANDLED
        mock_service.send_olya.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# F. Integration Tests
# ═══════════════════════════════════════════════════════════════════


class TestOlyaIntegration:
    """Integration tests: filter → handler → service pipeline."""

    @pytest.fixture(autouse=True)
    def reset_service(self):
        setup_olya(None)
        yield
        setup_olya(None)

    @pytest.mark.asyncio
    async def test_integration_filter_to_handler(self, make_message, olya_user_id):
        """Full pipeline: filter passes → handler called → service called."""
        mock_service = MagicMock()
        mock_service.send_olya = AsyncMock(return_value=True)
        setup_olya(mock_service)

        f = OlyaVideoFilter()
        msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
        filter_result = await f(msg)
        assert isinstance(filter_result, dict)

        await olya_handler(msg, **filter_result)
        mock_service.send_olya.assert_called_once_with(msg.chat.id)

    @pytest.mark.asyncio
    async def test_no_reply_parameters(self, mock_bot, tmp_path, olya_user_id):
        """bot.send_* called WITHOUT reply_to_message_id or reply_parameters."""
        subdir = tmp_path / "cringe"
        subdir.mkdir()
        (subdir / "test.jpg").write_text("fake")

        relay = OlyaRelay(mock_bot, cooldown_seconds=0, media_base=str(subdir))
        mock_bot.send_photo = AsyncMock()
        mock_bot.send_video = AsyncMock()
        mock_bot.send_animation = AsyncMock()
        mock_bot.send_audio = AsyncMock()
        mock_bot.send_voice = AsyncMock()

        await relay.send_olya(42)
        call_kwargs = mock_bot.send_photo.call_args.kwargs
        call_args = mock_bot.send_photo.call_args.args
        assert "reply_parameters" not in call_kwargs
        assert "reply_to_message_id" not in call_kwargs
        assert call_args[0] == 42


# ═══════════════════════════════════════════════════════════════════
# G. Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestOlyaEdgeCases:
    """Edge case tests for Olya service."""

    @pytest.mark.asyncio
    async def test_disabled_feature_skips_all(self, make_message, olya_user_id):
        """OLYA_ENABLED=False → filter returns False."""
        import filters.olya_video as filter_mod
        mod = _modified_settings(OLYA_ENABLED=False)
        with patch.object(filter_mod, "settings", mod):
            f = OlyaVideoFilter()
            msg = make_message(from_id=olya_user_id, text=None, content_type=ContentType.VIDEO)
            result = await f(msg)
        assert result is False
