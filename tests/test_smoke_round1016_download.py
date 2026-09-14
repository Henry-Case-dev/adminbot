"""Смоук раунда 10.16 (T-1643) — download/probe «имитация реальной работы».

In-process, без сети: yt-dlp подменяется фейком, cobalt/бот — моками.
Сквозные сценарии (а не только unit-изоляция):
  * реальный `VideoDownloader.probe` (yt-dlp mock) → качества/title и reason-код;
  * `download_media` (tool) для YouTube/платформы/direct через реальный
    `ToolRouter` → бэкенд сам отправляет файл, в LLM уходит фиктивный JSON;
  * Fast-Track (роутер 4e): probe-fail → bounded fallback download и отправка.
"""
import json
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from handlers import video_download as vd
from services import hot_config as hot
from services.smartmodule_throttling import CooldownTracker
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from tools.video_downloader import (
    DownloadError,
    DownloadUnavailableError,
    ProbeResult,
    VideoDownloader,
)

CHAT_ID = -1001234567890
USER_ID = 10
_YT = "https://youtu.be/ABCDEFGHIJK"
_TIKTOK = "https://www.tiktok.com/@user/video/1234567890"
_MP4 = "https://cdn.example.com/clip.mp4"


class _FakeBot:
    def __init__(self):
        self.sent_video = []
        self.sent_document = []
        self.send_message = AsyncMock(
            return_value=SimpleNamespace(message_id=42))
        self.edit_message_text = AsyncMock()
        self.delete_message = AsyncMock()

    async def send_video(self, chat_id, file, **kwargs):
        self.sent_video.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)

    async def send_document(self, chat_id, file, **kwargs):
        self.sent_document.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)


def _msg(text, message_id=100, user_id=USER_ID):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = SimpleNamespace(id=CHAT_ID)
    msg.from_user = SimpleNamespace(id=user_id)
    msg.reply = AsyncMock(return_value=SimpleNamespace(message_id=999))
    msg.video = None
    msg.document = None
    msg.reply_to_message = None
    return msg


def _gate(monkeypatch, enabled):
    real_get = hot.get
    monkeypatch.setattr(
        hot, "get",
        lambda key, default=None: enabled
        if key == "flags.download_enabled" else real_get(key, default))


def _patch_ytdlp(monkeypatch, *, info=None, exc=None):
    import sys
    import types

    class _YDL:
        def __init__(self, opts):
            pass

        def extract_info(self, url, download=False):
            if exc is not None:
                raise exc
            return info if info is not None else {"title": "t", "formats": []}

    monkeypatch.setitem(sys.modules, "yt_dlp",
                        types.SimpleNamespace(YoutubeDL=_YDL))


def _deps(**kwargs) -> ToolDeps:
    kwargs.setdefault("search", MagicMock())
    kwargs.setdefault("memory", MagicMock())
    return ToolDeps(**kwargs)


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(CHAT_ID, "свободная форма", **kwargs)


# ── 1. реальный probe (yt-dlp mock) ──────────────────────────────────────


class TestProbeSmoke:
    @pytest.mark.asyncio
    async def test_probe_qualities_and_title(self, tmp_path, monkeypatch):
        _patch_ytdlp(monkeypatch, info={"title": "Название",
                                        "formats": [
                                            {"vcodec": "avc", "height": 720},
                                            {"vcodec": "none", "height": 1080},
                                            {"vcodec": "avc", "height": 1080},
                                            {"vcodec": "avc", "height": 360},
                                        ]})
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        probe = await dl.probe(_YT)
        assert probe.title == "Название"
        assert probe.qualities == ("1080p", "720p", "360p")

    @pytest.mark.asyncio
    async def test_probe_bot_check_reason(self, tmp_path, monkeypatch):
        _patch_ytdlp(monkeypatch, exc=RuntimeError(
            "Sign in to confirm you're not a bot"))
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadUnavailableError) as exc:
            await dl.probe(_YT)
        assert exc.value.reason == "probe_bot_check"

    @pytest.mark.asyncio
    async def test_probe_generic_reason(self, tmp_path, monkeypatch):
        _patch_ytdlp(monkeypatch, exc=RuntimeError("boom"))
        dl = VideoDownloader("http://localhost:9000/", str(tmp_path))
        with pytest.raises(DownloadError) as exc:
            await dl.probe(_YT)
        assert exc.value.reason == "probe_failed"


# ── 2. tool download_media (реальный ToolRouter) ─────────────────────────


class TestToolDownloadMediaSmoke:
    @pytest.mark.asyncio
    async def test_youtube_url_asks_quality_menu(
            self, monkeypatch, tmp_path):
        """R10.17 (ADR-1017-2): YouTube-URL в tool-пути → probe → меню
        качества; файл не скачивается до callback (fix UPD3 §2)."""
        _gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.probe = AsyncMock(
            return_value=ProbeResult("Название", ("1080p", "720p", "360p")))
        downloader.download = AsyncMock()
        bot = _FakeBot()
        router = ToolRouter(_deps(downloader=downloader))
        out = await router.dispatch("download_media", {"url": _YT},
                                    _ctx(bot=bot, reply_to_message_id=7))
        assert json.loads(out)["status"] == "needs_quality"
        downloader.download.assert_not_awaited()
        assert bot.send_message.await_count == 1
        assert bot.sent_video == []

    @pytest.mark.asyncio
    async def test_platform_url_asks_quality(self, monkeypatch):
        _gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.probe = AsyncMock(
            return_value=ProbeResult("tk", ("720p", "360p")))
        downloader.download = AsyncMock()
        bot = _FakeBot()
        router = ToolRouter(_deps(downloader=downloader))
        out = await router.dispatch("download_media", {"url": _TIKTOK},
                                    _ctx(bot=bot))
        assert json.loads(out)["status"] == "needs_quality"
        downloader.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failure_is_honest_error_no_send(self, monkeypatch):
        _gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.probe = AsyncMock(
            side_effect=DownloadError("probe", reason="probe_failed"))
        downloader.download = AsyncMock(side_effect=DownloadError("boom"))
        bot = _FakeBot()
        router = ToolRouter(_deps(downloader=downloader))
        out = await router.dispatch("download_media", {"url": _YT},
                                    _ctx(bot=bot))
        assert json.loads(out)["status"] == "error"
        assert bot.sent_video == []

    @pytest.mark.asyncio
    async def test_disabled_flag_blocks_tool(self, monkeypatch):
        _gate(monkeypatch, False)
        downloader = MagicMock()
        downloader.download = AsyncMock()
        router = ToolRouter(_deps(downloader=downloader))
        out = await router.dispatch("download_media", {"url": _YT},
                                    _ctx(bot=_FakeBot()))
        assert json.loads(out)["status"] == "error"
        downloader.download.assert_not_awaited()


# ── 3. Fast-Track роутера 4e: probe-fail → fallback download ─────────────


class TestFastTrackFallbackSmoke:
    def _downloader(self, monkeypatch, *, download_result=None,
                    download_exc=None):
        dl = MagicMock()
        dl.busy = False
        dl.probe = AsyncMock(side_effect=DownloadError(
            "probe", reason="probe_failed"))
        dl.download = AsyncMock(return_value=download_result,
                                side_effect=download_exc)
        monkeypatch.setattr(vd, "_downloader", dl)
        monkeypatch.setattr(vd, "_cooldown", CooldownTracker(1800.0))
        _gate(monkeypatch, True)
        return dl

    @pytest.mark.asyncio
    async def test_probe_fail_fallback_sends_file(self, monkeypatch, tmp_path):
        out = tmp_path / "fb.mp4"
        out.write_bytes(b"x")
        dl = self._downloader(monkeypatch, download_result=out)
        bot = _FakeBot()
        result = await vd.video_download_handler(
            _msg(f"Бот, скачай {_TIKTOK}"), bot)
        assert result is None
        dl.download.assert_awaited_once_with(_TIKTOK, None, progress_cb=ANY)
        assert len(bot.sent_video) == 1

    @pytest.mark.asyncio
    async def test_flag_off_is_unhandled(self, monkeypatch):
        dl = self._downloader(monkeypatch)
        _gate(monkeypatch, False)
        result = await vd.video_download_handler(
            _msg(f"Бот, скачай {_TIKTOK}"), _FakeBot())
        assert result is UNHANDLED
        dl.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_direct_media_url_downloads(self, monkeypatch, tmp_path):
        out = tmp_path / "d.mp4"
        out.write_bytes(b"x")
        dl = self._downloader(monkeypatch, download_result=out)
        # direct-медиа: downloader.download вызывается напрямую (без probe-меню).
        bot = _FakeBot()
        result = await vd.video_download_handler(_msg(f"Бот, скачай {_MP4}"),
                                                 bot)
        assert result is None
        assert dl.download.await_count == 1
