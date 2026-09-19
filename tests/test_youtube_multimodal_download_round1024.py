"""Раунд 10.24 (F16, ADR-1024-17) — YouTube+summary: скачать → мультимодалка
→ фолбэк субтитры (+ credentialed-уровень).

Покрытие (spec §6, T1–T11):
- download → publish → summarize_media_url (реальный /media-URL, не watch?v=);
- мультимодалка упала → фолбэк на субтитры (summarize_cascade);
- скачивание упало/таймаут → тихий фолбэк (без промежуточной фразы);
- media_share.enabled()==False → скачивание НЕ вызывается, сразу субтитры;
- флаг OFF → скачивание НЕ вызывается, сразу субтитры;
- age_restricted → отдельный пул YOUTUBE_AGE_RESTRICTED_PHRASES;
- credentialed presence (set|empty, без значений — R17);
- R17: в логах ветки нет подписанного /media/-URL;
- пул age-restricted не пересекается с прочими; allowlist/таймаут-хелперы.
"""
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import youtube as youtube_mod
from services.media_share import ShareTicket
from services.smartmodule_phrases import (
    CHAT_COOLDOWN_PHRASES,
    CHAT_ERROR_PHRASES,
    CHAT_LLM_DOWN_PHRASES,
    CHAT_LOCK_BUSY_PHRASES,
    COMMAND_NO_TARGET_PHRASES,
    LLM_ERROR_PHRASES,
    SMARTMODULE_BUSY_PHRASES,
    THROTTLE_PHRASES,
    VIDEO_MEDIA_EMPTY_PHRASES,
    VIDEO_MEDIA_TOO_BIG_PHRASES,
    VIDEO_MEDIA_TOO_LONG_PHRASES,
    VIDEO_MEDIA_UNAVAILABLE_PHRASES,
    VIDEO_NO_SPEECH_PHRASES,
    YOUTUBE_AGE_RESTRICTED_PHRASES,
    YOUTUBE_ERROR_PHRASES,
    YOUTUBE_RETRY_PHRASES,
)
from services.video_cascade_client import VideoLevelError
from services.youtube_transcript_engine import YouTubeTranscriptUnavailableException
from tools.video_downloader import DownloadError

CHAT_ID = -1001234567890
VIDEO_ID = "1TON5W_SNKY"
YT_URL = f"https://youtu.be/{VIDEO_ID}"
CANONICAL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
MEDIA_URL = "https://admin-bot.example.org/media/abc123.mp4?e=123&s=signedsecret"


class _FakeCache:
    def __init__(self):
        self.sets = []

    def build_key(self, slug, raw):
        return f"{slug}:{raw}"

    async def get(self, key):
        return None

    async def set(self, key, value):
        self.sets.append((key, value))


class _FakeDownloader:
    """download(url, quality) → файл в tmp | DownloadError/timeout."""

    def __init__(self, tmp_path, error=None, timeout=False):
        self.tmp = Path(tmp_path)
        self.downloaded = []
        self.quality = []
        self._error = error
        self._timeout = timeout

    async def download(self, url, quality, progress_cb=None):
        self.downloaded.append(url)
        self.quality.append(quality)
        if self._timeout:
            import asyncio
            await asyncio.sleep(10)
        if self._error is not None:
            raise self._error
        path = self.tmp / "vid.mp4"
        path.write_bytes(b"videodata")
        return path


def _make_msg(text=None, message_id=11, reply_to=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = 1
    msg.reply_to_message = reply_to
    msg.video = None
    msg.document = None
    msg.voice = None
    msg.video_note = None
    msg.audio = None
    return msg


def _make_bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=500))
    bot.set_message_reaction = AsyncMock()
    bot.send_chat_action = AsyncMock()
    return bot


def _ticket():
    return ShareTicket(file_id="abc123.mp4", expires=123,
                       sig="signedsecret", rel_url="/media/abc123.mp4?e=123&s=signedsecret",
                       abs_url=MEDIA_URL)


@pytest.fixture
def fm_env(tmp_path, monkeypatch):
    """DI youtube+summary: сервис-моки, fake downloader, включённая публикация,
    fake smart_cache; кулдаун сброшен."""
    service = MagicMock()
    service.summarize_cascade = AsyncMock(return_value="выжимка по субтитрам")
    service.summarize_media_url = AsyncMock(return_value="выжимка по видео")
    service.video_client = MagicMock()
    service.video_client.available = True
    youtube_mod._service = service

    downloader = _FakeDownloader(tmp_path)
    youtube_mod._media_downloader = downloader
    youtube_mod._cooldown._last.clear()

    monkeypatch.setattr(youtube_mod.media_share, "enabled", lambda: True)
    monkeypatch.setattr(youtube_mod.media_share, "publish_media_file",
                        AsyncMock(return_value=_ticket()))
    monkeypatch.setattr(youtube_mod.media_share, "delete_file", AsyncMock())

    cache = _FakeCache()
    monkeypatch.setattr(youtube_mod, "get_smart_cache", lambda: cache)

    yield service, downloader, cache
    youtube_mod._service = None
    youtube_mod._media_downloader = None
    youtube_mod._cooldown._last.clear()


async def _run_summary(bot=None):
    bot = bot or _make_bot()
    msg = _make_msg(text=f"Бот, че за видос {YT_URL}")
    await youtube_mod.youtube_handler(msg, bot=bot)
    return bot


# ── T2/T3: скачать → опубликовать → мультимодалка (успех) ────────────────

class TestDownloadPublishMultimodal:
    @pytest.mark.asyncio
    async def test_download_publish_multimodal_success(self, fm_env):
        service, downloader, cache = fm_env
        bot = _make_bot()
        await _run_summary(bot)
        # скачали канонический watch-URL (вход для yt-dlp, не video_url модели)
        assert downloader.downloaded == [CANONICAL]
        # опубликовали и отдали мультимодалке РЕАЛЬНЫЙ /media-URL
        youtube_mod.media_share.publish_media_file.assert_awaited_once()
        kwargs = service.summarize_media_url.await_args.kwargs
        assert kwargs["video_url"] == MEDIA_URL
        assert kwargs["label"] == "youtube-file"
        assert "watch?v=" not in kwargs["video_url"]
        # субтитры НЕ запускались, ответ ушёл, кэш записан
        service.summarize_cascade.assert_not_awaited()
        assert bot.send_message.await_args.args[1] == "выжимка по видео"
        assert cache.sets == [(f"youtube:{VIDEO_ID}", "выжимка по видео")]
        # ticket удалён в finally
        youtube_mod.media_share.delete_file.assert_awaited()

    @pytest.mark.asyncio
    async def test_downloaded_file_cleaned_up(self, fm_env, tmp_path):
        service, downloader, cache = fm_env
        await _run_summary()
        assert not (Path(tmp_path) / "vid.mp4").exists()


# ── T4/T5: фолбэк на субтитры ────────────────────────────────────────────

class TestSubtitleFallback:
    @pytest.mark.asyncio
    async def test_multimodal_failure_falls_back_to_subtitles(self, fm_env):
        service, downloader, cache = fm_env
        service.summarize_media_url = AsyncMock(
            side_effect=VideoLevelError("level empty"))
        bot = _make_bot()
        await _run_summary(bot)
        assert downloader.downloaded == [CANONICAL]
        service.summarize_cascade.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == "выжимка по субтитрам"
        assert cache.sets == [(f"youtube:{VIDEO_ID}", "выжимка по субтитрам")]

    @pytest.mark.asyncio
    async def test_empty_multimodal_answer_falls_back(self, fm_env):
        service, downloader, cache = fm_env
        service.summarize_media_url = AsyncMock(return_value="   ")
        bot = _make_bot()
        await _run_summary(bot)
        service.summarize_cascade.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == "выжимка по субтитрам"

    @pytest.mark.asyncio
    async def test_download_failure_silent_then_subtitles(self, fm_env, caplog):
        service, downloader, cache = fm_env
        downloader._error = DownloadError("yt-dlp failed", reason="ytdlp_failed")
        bot = _make_bot()
        with caplog.at_level(logging.WARNING):
            await _run_summary(bot)
        # юзеру — только выжимка/фраза субтитрового пути, без промежуточной
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.args[1] == "выжимка по субтитрам"
        # публикация не запускалась
        youtube_mod.media_share.publish_media_file.assert_not_awaited()
        service.summarize_cascade.assert_awaited_once()
        assert any("multimodal download failed" in r.message and "reason=ytdlp_failed"
                   in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_download_timeout_silent_then_subtitles(self, fm_env,
                                                          monkeypatch):
        service, downloader, cache = fm_env
        downloader._timeout = True
        monkeypatch.setattr(type(youtube_mod.settings),
                            "YOUTUBE_MULTIMODAL_DOWNLOAD_TIMEOUT_SECONDS", 30.0)
        # 30с ждать нельзя — ускоряем wait_for через фейковый asyncio
        monkeypatch.setattr(youtube_mod, "_yt_multimodal_timeout", lambda: 0.01)
        bot = _make_bot()
        await _run_summary(bot)
        service.summarize_cascade.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == "выжимка по субтитрам"

    @pytest.mark.asyncio
    async def test_publish_disabled_skips_download(self, fm_env, monkeypatch):
        """NFR-8: media_share выключен → download НЕ вызывается, сразу L3."""
        service, downloader, cache = fm_env
        monkeypatch.setattr(youtube_mod.media_share, "enabled", lambda: False)
        bot = _make_bot()
        await _run_summary(bot)
        assert downloader.downloaded == []
        service.summarize_cascade.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == "выжимка по субтитрам"

    @pytest.mark.asyncio
    async def test_flag_off_skips_download(self, fm_env, monkeypatch):
        """Kill-switch OFF → download НЕ вызывается, сразу субтитровый L3."""
        service, downloader, cache = fm_env
        monkeypatch.setattr(type(youtube_mod.settings),
                            "YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED", False)
        bot = _make_bot()
        await _run_summary(bot)
        assert downloader.downloaded == []
        youtube_mod.media_share.publish_media_file.assert_not_awaited()
        service.summarize_cascade.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == "выжимка по субтитрам"


# ── T8: age-restricted → отдельный пул фраз ──────────────────────────────

class TestAgeRestrictedReason:
    @pytest.mark.asyncio
    async def test_age_restricted_uses_dedicated_pool(self, fm_env):
        service, downloader, cache = fm_env
        service.summarize_media_url = AsyncMock(
            side_effect=VideoLevelError("no video frames"))
        service.summarize_cascade = AsyncMock(
            side_effect=YouTubeTranscriptUnavailableException(
                "both engines failed", reason="age_restricted"))
        bot = _make_bot()
        await _run_summary(bot)
        assert bot.send_message.await_args.args[1] in YOUTUBE_AGE_RESTRICTED_PHRASES

    @pytest.mark.asyncio
    async def test_unavailable_uses_generic_pool(self, fm_env):
        service, downloader, cache = fm_env
        service.summarize_media_url = AsyncMock(
            side_effect=VideoLevelError("no video frames"))
        service.summarize_cascade = AsyncMock(
            side_effect=YouTubeTranscriptUnavailableException("no subs"))
        bot = _make_bot()
        await _run_summary(bot)
        assert bot.send_message.await_args.args[1] in YOUTUBE_ERROR_PHRASES
        assert bot.send_message.await_args.args[1] not in \
            YOUTUBE_AGE_RESTRICTED_PHRASES


# ── Кэш-hit: A/B/L3 не запускаются ──────────────────────────────────────

class TestCacheFastPath:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_everything(self, fm_env, monkeypatch):
        service, downloader, cache = fm_env

        class _HitCache(_FakeCache):
            async def get(self, key):
                return "старая выжимка"

        monkeypatch.setattr(youtube_mod, "get_smart_cache", lambda: _HitCache())
        bot = _make_bot()
        await _run_summary(bot)
        assert downloader.downloaded == []
        service.summarize_cascade.assert_not_awaited()
        service.summarize_media_url.assert_not_awaited()
        assert bot.send_message.await_args.args[1] == "старая выжимка"


# ── R17: в логах ветки нет подписанного /media-URL ───────────────────────

class TestR17NoSignedUrlInLogs:
    @pytest.mark.asyncio
    async def test_no_media_url_in_logs(self, fm_env, caplog):
        service, downloader, cache = fm_env
        with caplog.at_level(logging.DEBUG):
            await _run_summary()
        text = caplog.text
        assert "signedsecret" not in text
        assert "?e=123&s=" not in text
        assert "/media/abc123" not in text


# ── Credentialed presence (UPD5) + хелперы ──────────────────────────────

class TestCredentialedLevel:
    def test_credentialed_enabled_default(self):
        assert youtube_mod._yt_credentialed_enabled() is True

    def test_presence_log_set_empty_without_values(self, monkeypatch, caplog):
        import dataclasses
        patched = dataclasses.replace(
            youtube_mod.settings,
            YOUTUBE_COOKIES_FILE="/secret/cookies.txt",
            YOUTUBE_TRANSCRIPT_PROXY_URL="")
        monkeypatch.setattr(youtube_mod, "settings", patched)
        monkeypatch.setattr("config.settings.get_ytdlp_pot_provider",
                            lambda: "bgutil:http")
        with caplog.at_level(logging.INFO):
            youtube_mod._log_yt_credentials_presence()
        text = caplog.text
        assert "cookies=set" in text
        assert "pot=set" in text
        assert "proxy=empty" in text
        # R17: значения кредов НЕ светятся
        assert "/secret/cookies.txt" not in text
        assert "bgutil:http" not in text

    def test_presence_all_empty(self, monkeypatch, caplog):
        import dataclasses
        patched = dataclasses.replace(
            youtube_mod.settings,
            YOUTUBE_COOKIES_FILE="",
            YOUTUBE_TRANSCRIPT_PROXY_URL="")
        monkeypatch.setattr(youtube_mod, "settings", patched)
        monkeypatch.setattr("config.settings.get_ytdlp_pot_provider",
                            lambda: "")
        with caplog.at_level(logging.INFO):
            youtube_mod._log_yt_credentials_presence()
        assert "cookies=empty" in caplog.text
        assert "pot=empty" in caplog.text
        assert "proxy=empty" in caplog.text


class TestHelperFlags:
    def test_timeout_default_and_clamp(self, monkeypatch):
        assert youtube_mod._yt_multimodal_timeout() == 240.0
        monkeypatch.setattr(type(youtube_mod.settings),
                            "YOUTUBE_MULTIMODAL_DOWNLOAD_TIMEOUT_SECONDS", 5.0)
        assert youtube_mod._yt_multimodal_timeout() == 30.0

    def test_allowlist_empty_allows_all(self, monkeypatch):
        monkeypatch.setattr(type(youtube_mod.settings),
                            "YOUTUBE_MULTIMODAL_DOWNLOAD_CHAT_IDS", "")
        assert youtube_mod._yt_multimodal_allowed(CHAT_ID) is True

    def test_allowlist_filters(self, monkeypatch):
        monkeypatch.setattr(type(youtube_mod.settings),
                            "YOUTUBE_MULTIMODAL_DOWNLOAD_CHAT_IDS",
                            f"-1,{CHAT_ID}")
        assert youtube_mod._yt_multimodal_allowed(CHAT_ID) is True
        assert youtube_mod._yt_multimodal_allowed(-42) is False

    @pytest.mark.asyncio
    async def test_allowlist_blocks_branch(self, fm_env, monkeypatch):
        service, downloader, cache = fm_env
        monkeypatch.setattr(type(youtube_mod.settings),
                            "YOUTUBE_MULTIMODAL_DOWNLOAD_CHAT_IDS", "-42")
        bot = _make_bot()
        await _run_summary(bot)
        assert downloader.downloaded == []
        service.summarize_cascade.assert_awaited_once()


# ── T11: пул age-restricted не пересекается с прочими ────────────────────

class TestAgeRestrictedPhrases:
    def test_pool_size_no_duplicates(self):
        assert len(YOUTUBE_AGE_RESTRICTED_PHRASES) == 3
        assert len(set(YOUTUBE_AGE_RESTRICTED_PHRASES)) == 3

    def test_pool_lowercase_no_emoji(self):
        for phrase in YOUTUBE_AGE_RESTRICTED_PHRASES:
            assert phrase == phrase.lower()
            assert not any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in phrase)

    def test_pool_disjoint_from_existing(self):
        existing = (
            set(THROTTLE_PHRASES)
            | set(LLM_ERROR_PHRASES)
            | set(YOUTUBE_ERROR_PHRASES)
            | set(YOUTUBE_RETRY_PHRASES)
            | set(VIDEO_MEDIA_TOO_LONG_PHRASES)
            | set(VIDEO_MEDIA_TOO_BIG_PHRASES)
            | set(VIDEO_MEDIA_UNAVAILABLE_PHRASES)
            | set(VIDEO_MEDIA_EMPTY_PHRASES)
            | set(VIDEO_NO_SPEECH_PHRASES)
            | set(SMARTMODULE_BUSY_PHRASES)
            | set(COMMAND_NO_TARGET_PHRASES)
            | set(CHAT_COOLDOWN_PHRASES)
            | set(CHAT_ERROR_PHRASES)
            | set(CHAT_LLM_DOWN_PHRASES)
            | set(CHAT_LOCK_BUSY_PHRASES)
        )
        assert not set(YOUTUBE_AGE_RESTRICTED_PHRASES) & existing
