"""Tests for slavik media type detection and sending (Epic 20)."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from handlers.slavik import (
    _detect_slavik_media_type,
    _send_slavik_media,
    _pick_random_slavik_media,
    _IMAGE_EXTENSIONS,
    _VIDEO_EXTENSIONS,
    _AUDIO_EXTENSIONS,
    _VOICE_EXTENSIONS,
)


# ── Test: _detect_slavik_media_type ──


class TestDetectSlavikMediaType:
    """Tests for _detect_slavik_media_type function."""

    @pytest.mark.parametrize("ext", sorted(_IMAGE_EXTENSIONS))
    def test_photo_extensions(self, ext, tmp_path):
        filepath = tmp_path / f"test{ext}"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "photo"

    @pytest.mark.parametrize("ext", sorted(_VIDEO_EXTENSIONS))
    def test_video_extensions(self, ext, tmp_path):
        filepath = tmp_path / f"regular{ext}"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "video"

    @pytest.mark.parametrize("ext", sorted(_AUDIO_EXTENSIONS))
    def test_audio_extensions(self, ext, tmp_path):
        filepath = tmp_path / f"track{ext}"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "audio"

    @pytest.mark.parametrize("ext", sorted(_VOICE_EXTENSIONS))
    def test_voice_extensions(self, ext, tmp_path):
        filepath = tmp_path / f"voice{ext}"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "voice"

    @pytest.mark.parametrize("filename", [
        "document.pdf",
        "archive.zip",
        "text.txt",
        "data.csv",
        "script.py",
        "image.svg",
        "file.unknown",
    ])
    def test_document_fallback(self, filename, tmp_path):
        filepath = tmp_path / filename
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "document"

    # ── GIF detection variants ──

    @pytest.mark.parametrize("filename,expected", [
        ("gif.mp4", "animation"),
        ("something_gif.mp4", "animation"),
        ("my_gif.mov", "animation"),
        ("image.gif.mp4", "animation"),
        ("test_gif.webm", "animation"),
        ("GIF.MP4", "animation"),
        ("Something_GIF.mp4", "animation"),
        ("notagif.mp4", "video"),
        ("regular.mp4", "video"),
        ("agifile.mp4", "video"),
        ("gift.mp4", "animation"),  # starts with "gif"
        ("gif_photo.mp4", "animation"),  # "_gif" detected
    ])
    def test_gif_detection(self, filename, expected, tmp_path):
        filepath = tmp_path / filename
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == expected

    def test_gif_midword_not_detected(self, tmp_path):
        """'notagif.mp4' should not match as animation."""
        filepath = tmp_path / "notagif.mp4"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "video"

    def test_gif_within_word_not_detected(self, tmp_path):
        """'agifile.mp4' should not match as animation (no word boundary)."""
        filepath = tmp_path / "agifile.mp4"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "video"

    def test_gift_not_detected_as_gif(self, tmp_path):
        """'.gift' should NOT be detected as GIF animation (Epic 20 D51)."""
        filepath = tmp_path / "file.gift.mp4"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "video"

    # ── Edge cases ──

    def test_no_extension(self, tmp_path):
        filepath = tmp_path / "noextension"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "document"

    def test_hidden_file_video(self, tmp_path):
        filepath = tmp_path / ".hidden.mp4"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "video"

    def test_uppercase_extension(self, tmp_path):
        filepath = tmp_path / "photo.JPG"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "photo"

    def test_mixed_case_extension(self, tmp_path):
        filepath = tmp_path / "photo.JpG"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "photo"


# ── Test: _send_slavik_media ──


class TestSendSlavikMedia:
    """Tests for _send_slavik_media function."""

    def _make_msg(self, make_message):
        msg = make_message(479167456, text="test")
        msg.answer_photo = AsyncMock()
        msg.answer_video = AsyncMock()
        msg.answer_animation = AsyncMock()
        msg.answer_audio = AsyncMock()
        msg.answer_voice = AsyncMock()
        msg.answer_document = AsyncMock()
        return msg

    @pytest.mark.asyncio
    async def test_sends_photo(self, make_message, tmp_path):
        msg = self._make_msg(make_message)
        filepath = tmp_path / "test.jpg"
        filepath.touch()

        with patch("handlers.slavik.FSInputFile"):
            await _send_slavik_media(msg, filepath, "photo")

        msg.answer_photo.assert_called_once()
        msg.answer_video.assert_not_called()
        msg.answer_animation.assert_not_called()
        msg.answer_audio.assert_not_called()
        msg.answer_voice.assert_not_called()
        msg.answer_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_video(self, make_message, tmp_path):
        msg = self._make_msg(make_message)
        filepath = tmp_path / "test.mp4"
        filepath.touch()

        with patch("handlers.slavik.FSInputFile"):
            await _send_slavik_media(msg, filepath, "video")

        msg.answer_video.assert_called_once()
        msg.answer_photo.assert_not_called()
        msg.answer_animation.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_animation(self, make_message, tmp_path):
        msg = self._make_msg(make_message)
        filepath = tmp_path / "gif.mp4"
        filepath.touch()

        with patch("handlers.slavik.FSInputFile"):
            await _send_slavik_media(msg, filepath, "animation")

        msg.answer_animation.assert_called_once()
        msg.answer_photo.assert_not_called()
        msg.answer_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_audio(self, make_message, tmp_path):
        msg = self._make_msg(make_message)
        filepath = tmp_path / "track.mp3"
        filepath.touch()

        with patch("handlers.slavik.FSInputFile"):
            await _send_slavik_media(msg, filepath, "audio")

        msg.answer_audio.assert_called_once()
        msg.answer_photo.assert_not_called()
        msg.answer_video.assert_not_called()
        msg.answer_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_voice(self, make_message, tmp_path):
        msg = self._make_msg(make_message)
        filepath = tmp_path / "voice.ogg"
        filepath.touch()

        with patch("handlers.slavik.FSInputFile"):
            await _send_slavik_media(msg, filepath, "voice")

        msg.answer_voice.assert_called_once()
        msg.answer_photo.assert_not_called()
        msg.answer_audio.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_document(self, make_message, tmp_path):
        msg = self._make_msg(make_message)
        filepath = tmp_path / "file.pdf"
        filepath.touch()

        with patch("handlers.slavik.FSInputFile"):
            await _send_slavik_media(msg, filepath, "document")

        msg.answer_document.assert_called_once()
        msg.answer_photo.assert_not_called()
        msg.answer_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_type_falls_back_to_document(self, make_message, tmp_path):
        """Unknown media type should fall back to answer_document."""
        msg = self._make_msg(make_message)
        filepath = tmp_path / "weird.xyz"
        filepath.touch()

        with patch("handlers.slavik.FSInputFile"):
            await _send_slavik_media(msg, filepath, "unknown_type")

        msg.answer_document.assert_called_once()
        msg.answer_photo.assert_not_called()


# ── Test: _pick_random_slavik_media ──


class TestPickRandomSlavikMedia:
    """Tests for _pick_random_slavik_media function."""

    def test_empty_directory_returns_none(self, tmp_path, monkeypatch):
        """Empty directory should return None."""
        mock_settings = MagicMock()
        mock_settings.SLAVIC_RANDOM_DIR = str(tmp_path)
        monkeypatch.setattr("handlers.slavik.settings", mock_settings)

        result = _pick_random_slavik_media()
        assert result is None

    def test_only_unsupported_files(self, tmp_path, monkeypatch):
        """Directory with only unsupported files still picks them as 'document'."""
        (tmp_path / "file1.txt").touch()
        (tmp_path / "file2.csv").touch()
        (tmp_path / "file3.pdf").touch()

        mock_settings = MagicMock()
        mock_settings.SLAVIC_RANDOM_DIR = str(tmp_path)
        monkeypatch.setattr("handlers.slavik.settings", mock_settings)

        result = _pick_random_slavik_media()
        assert result is not None
        filepath, media_type = result
        assert media_type == "document"
        assert filepath.name in ("file1.txt", "file2.csv", "file3.pdf")

    def test_nonexistent_directory_returns_none(self, tmp_path, monkeypatch):
        """Non-existent directory should return None."""
        nonexistent = tmp_path / "does_not_exist"
        mock_settings = MagicMock()
        mock_settings.SLAVIC_RANDOM_DIR = str(nonexistent)
        monkeypatch.setattr("handlers.slavik.settings", mock_settings)

        result = _pick_random_slavik_media()
        assert result is None

    def test_mixed_media_types(self, tmp_path, monkeypatch):
        """Directory with mixed media types should pick one."""
        (tmp_path / "photo.jpg").touch()
        (tmp_path / "video.mp4").touch()
        (tmp_path / "audio.mp3").touch()
        (tmp_path / "voice.ogg").touch()
        (tmp_path / "doc.pdf").touch()

        mock_settings = MagicMock()
        mock_settings.SLAVIC_RANDOM_DIR = str(tmp_path)
        monkeypatch.setattr("handlers.slavik.settings", mock_settings)

        result = _pick_random_slavik_media()
        assert result is not None
        filepath, media_type = result
        assert filepath.name in ("photo.jpg", "video.mp4", "audio.mp3", "voice.ogg", "doc.pdf")
        assert media_type in ("photo", "video", "audio", "voice", "document")

    def test_all_six_types_present(self, tmp_path, monkeypatch):
        """Directory with all 6 media types should pick one correctly."""
        (tmp_path / "image.jpg").touch()
        (tmp_path / "regular.mp4").touch()
        (tmp_path / "gif_vid.mp4").touch()
        (tmp_path / "song.mp3").touch()
        (tmp_path / "note.ogg").touch()
        (tmp_path / "file.pdf").touch()

        mock_settings = MagicMock()
        mock_settings.SLAVIC_RANDOM_DIR = str(tmp_path)
        monkeypatch.setattr("handlers.slavik.settings", mock_settings)

        result = _pick_random_slavik_media()
        assert result is not None
        filepath, media_type = result

        expected_map = {
            "image.jpg": "photo",
            "regular.mp4": "video",
            "gif_vid.mp4": "animation",
            "song.mp3": "audio",
            "note.ogg": "voice",
            "file.pdf": "document",
        }
        assert filepath.name in expected_map
        assert media_type == expected_map[filepath.name]

    def test_subdirectory_ignored(self, tmp_path, monkeypatch):
        """Subdirectories should be ignored."""
        (tmp_path / "photo.jpg").touch()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "inside.mp4").touch()

        mock_settings = MagicMock()
        mock_settings.SLAVIC_RANDOM_DIR = str(tmp_path)
        monkeypatch.setattr("handlers.slavik.settings", mock_settings)

        result = _pick_random_slavik_media()
        assert result is not None
        filepath, media_type = result
        assert filepath.name == "photo.jpg"
        assert media_type == "photo"

    def test_only_directories_returns_none(self, tmp_path, monkeypatch):
        """Directory with only subdirectories (no files) should return None."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        mock_settings = MagicMock()
        mock_settings.SLAVIC_RANDOM_DIR = str(tmp_path)
        monkeypatch.setattr("handlers.slavik.settings", mock_settings)

        result = _pick_random_slavik_media()
        assert result is None


# ── Test: GIF detection edge cases ──


class TestGifDetectionEdgeCases:
    """Advanced GIF detection boundary tests."""

    @pytest.mark.parametrize("filename", [
        "gif.mp4",
        "gif.mov",
        "gif.webm",
    ])
    def test_starts_with_gif(self, filename, tmp_path):
        filepath = tmp_path / filename
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "animation"

    @pytest.mark.parametrize("filename", [
        "cat_gif.mp4",
        "cat_gif.mov",
        "cat_gif.webm",
    ])
    def test_contains_underscore_gif(self, filename, tmp_path):
        filepath = tmp_path / filename
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "animation"

    @pytest.mark.parametrize("filename", [
        "cat.gif.mp4",
        "cat.gif.mov",
        "cat.gif.webm",
    ])
    def test_contains_dot_gif(self, filename, tmp_path):
        filepath = tmp_path / filename
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "animation"

    def test_photo_with_gif_in_name_not_animation(self, tmp_path):
        """Image file with 'gif' in name should still be photo, not animation."""
        filepath = tmp_path / "gif_image.jpg"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "photo"

    def test_audio_with_gif_in_name_not_animation(self, tmp_path):
        """Audio file with 'gif' in name should be audio, not animation."""
        filepath = tmp_path / "gif_song.mp3"
        filepath.touch()
        assert _detect_slavik_media_type(filepath) == "audio"
