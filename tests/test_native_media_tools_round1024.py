"""Раунд 10.24 (F14, ADR-1024-15) — native-media-tools.

Покрытие spec §6 (F14-часть):
(a) Fast-Track native-first: «скачай» реплаем/своим видео с caption-URL →
    нативная пересылка, URL-ветка (probe) НЕ задействована;
(b) инструменты без `url` при `ctx.native_media` исполняются (`download_media`
    fetch→send; `summarize_video` STT-фолбэк выжимки);
(f) невидео-document (PDF) → `VD_NO_LINK_PHRASES`, не нативный путь;
(d) контракт схем: `url` необязателен + `source`, `mode` убран; определения
    `summarize_video`/`transcribe_video` различимы (F19 регистрирует 10-й);
(c) probe-fail (`probe_timeout`/`probe_failed`) → `VD_PROBE_FAIL_PHRASES`,
    R17-safe причина в логе без URL;
(g) аддитивность `ToolContext.native_media`/`ToolDeps.transcriber`.

Без сети: фейки bot/downloader/STT.
"""
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import video_download as vd
from services import hot_config as hot
from services import native_media
from services.native_media import (
    NativeMedia,
    document_is_video,
    resolve_reply_video,
)
from services.smartmodule_throttling import CooldownTracker
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.tool_schemas import (
    TOOL_CALLING_TOOLS,
    TOOL_SUMMARIZE_VIDEO,
    TOOL_TRANSCRIBE_VIDEO,
)
from tools.video_download_phrases import (
    VD_ERROR_PHRASES,
    VD_NO_LINK_PHRASES,
    VD_PROBE_FAIL_PHRASES,
    VD_SERVICE_DOWN_PHRASES,
)
from tools.video_downloader import DownloadError, ProbeResult

CHAT_ID = -1001234567890
USER_ID = 10
URL = "https://example.com/watch?v=1"

_FIRST_NINE = [
    "query_chat_memory", "dig_into_lore", "execute_web_search",
    "summarize_video", "download_media", "get_bot_health",
    "get_recent_history", "compile_lore_story", "generate_image"]


# ── фейки / окружение ────────────────────────────────────────────────────


class _NativeBot:
    """Bot: download пишет байты (cloud-режим), send_* — фейки."""

    def __init__(self):
        self.download = AsyncMock(side_effect=self._download)
        self.send_video = AsyncMock(return_value=SimpleNamespace(message_id=1))
        self.send_document = AsyncMock(
            return_value=SimpleNamespace(message_id=1))
        self.send_message = AsyncMock(return_value=SimpleNamespace(message_id=1))
        self.edit_message_text = AsyncMock()
        self.delete_message = AsyncMock()

    @staticmethod
    async def _download(file_id, destination=None):
        from pathlib import Path
        Path(destination).write_bytes(b"DATA" * 100)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """download-гейт ON (как боевой .env) + cloud-режим media_download
    (bot.download напрямую — без локального retry-цикла)."""
    from services import media_download
    real_get = hot.get
    monkeypatch.setattr(
        hot, "get",
        lambda key, default=None: True
        if key == "flags.download_enabled" else real_get(key, default))
    monkeypatch.setattr(media_download, "hot",
                        SimpleNamespace(get=lambda *a, **k: False))
    yield


@pytest.fixture
def vd_env(monkeypatch):
    old_dl, old_cd = vd._downloader, vd._cooldown
    dl = MagicMock()
    dl.busy = False
    dl.probe = AsyncMock()
    dl.download = AsyncMock()
    vd._downloader = dl
    vd._cooldown = CooldownTracker(1800.0)
    vd._PENDING.clear()
    yield dl
    vd._downloader, vd._cooldown = old_dl, old_cd
    vd._PENDING.clear()


def _make_msg(text=None, caption=None, message_id=100, user_id=USER_ID,
              video=None, document=None, reply_to_message=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = SimpleNamespace(id=CHAT_ID)
    msg.from_user = SimpleNamespace(id=user_id)
    msg.reply = AsyncMock(return_value=SimpleNamespace(message_id=999))
    msg.video = video
    msg.document = document
    msg.reply_to_message = reply_to_message
    return msg


def _deps(**kwargs) -> ToolDeps:
    kwargs.setdefault("search", MagicMock())
    kwargs.setdefault("memory", MagicMock())
    return ToolDeps(**kwargs)


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(CHAT_ID, "свободная форма", **kwargs)


def _video_native(file_id="fid") -> NativeMedia:
    return NativeMedia(source=MagicMock(),
                       media=SimpleNamespace(file_id=file_id), kind="video")


# ── (a)/(f) Fast-Track native-first + квалификация document ──────────────


class TestFastTrackNativeFirst:
    @pytest.mark.asyncio
    async def test_video_with_caption_url_goes_native(self, vd_env):
        """Баг A-2: живое видео побеждает caption-URL в реплае/своём caption."""
        bot = _NativeBot()
        msg = _make_msg(text="Бот, скачай",
                        video=SimpleNamespace(file_id="fid"),
                        caption=f"смотри {URL}")
        await vd.video_download_handler(msg, bot=bot)
        assert bot.download.await_count == 1
        assert bot.send_video.await_count == 1
        vd_env.probe.assert_not_awaited()          # URL-ветка не тронута
        vd_env.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reply_video_with_caption_url_goes_native(self, vd_env):
        target = _make_msg(message_id=55, video=SimpleNamespace(file_id="rfid"),
                           caption=f"источник {URL}")
        msg = _make_msg(text="Бот, скачай", message_id=56,
                        reply_to_message=target)
        bot = _NativeBot()
        await vd.video_download_handler(msg, bot=bot)
        assert bot.download.await_count == 1
        assert bot.send_video.await_count == 1
        vd_env.probe.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pdf_document_not_native(self, vd_env):
        """Латентный баг: невидео-document (PDF) → «нет ссылки», не native."""
        bot = _NativeBot()
        msg = _make_msg(
            text="Бот, скачай",
            document=SimpleNamespace(file_id="d", mime_type="application/pdf",
                                     file_name="док.pdf"))
        await vd.video_download_handler(msg, bot=bot)
        assert bot.send_video.await_count == 0
        assert bot.download.await_count == 0
        assert msg.reply.await_args.args[0] in VD_NO_LINK_PHRASES

    @pytest.mark.asyncio
    async def test_reply_pdf_not_native(self, vd_env):
        target = _make_msg(message_id=66, document=SimpleNamespace(
            file_id="d", mime_type="application/pdf", file_name="док.pdf"))
        msg = _make_msg(text="Бот, скачай", message_id=67,
                        reply_to_message=target)
        bot = _NativeBot()
        await vd.video_download_handler(msg, bot=bot)
        assert bot.send_video.await_count == 0
        assert msg.reply.await_args.args[0] in VD_NO_LINK_PHRASES

    @pytest.mark.asyncio
    async def test_flag_off_urls_first(self, vd_env, monkeypatch):
        """OFF → байт-в-байт прежнее: URL-ветка (probe) при наличии ссылки."""
        monkeypatch.setattr(vd, "settings", SimpleNamespace(
            NATIVE_MEDIA_TOOLS_ENABLED=False, DOWNLOAD_COOLDOWN=1800.0))
        vd_env.probe = AsyncMock(return_value=ProbeResult("t", ("720p",)))
        bot = _NativeBot()
        msg = _make_msg(text=f"Бот, скачай {URL}",
                        video=SimpleNamespace(file_id="fid"))
        await vd.video_download_handler(msg, bot=bot)
        vd_env.probe.assert_awaited_once()
        assert bot.download.await_count == 0


# ── (b) инструменты: native источник без url ─────────────────────────────


class TestToolsNativeSource:
    @pytest.mark.asyncio
    async def test_download_media_native_fetch_and_send(self):
        bot = _NativeBot()
        router = ToolRouter(_deps(downloader=MagicMock()))
        ctx = _ctx(bot=bot, user_id=USER_ID, native_media=_video_native())
        out = await router.dispatch("download_media", {"source": "reply"},
                                    ctx)
        assert json.loads(out)["status"] == "success"
        assert bot.download.await_count == 1
        assert bot.send_video.await_count == 1

    @pytest.mark.asyncio
    async def test_summarize_video_native_stt_fallback(self):
        bot = _NativeBot()
        video = MagicMock()
        video.video_client = None                   # нет L1/L2 → STT-фолбэк
        video.summarize_transcript = AsyncMock(return_value="выжимка из STT")
        transcriber = MagicMock()
        transcriber.transcribe_voice = AsyncMock(return_value="сырой текст")
        router = ToolRouter(_deps(video=video, transcriber=transcriber))
        ctx = _ctx(bot=bot, native_media=_video_native())
        out = await router.dispatch("summarize_video", {}, ctx)
        assert out == "выжимка из STT"
        transcriber.transcribe_voice.assert_awaited_once()
        video.summarize_transcript.assert_awaited_once()
        assert bot.download.await_count == 1

    @pytest.mark.asyncio
    async def test_no_source_is_error_string_not_exception(self):
        router = ToolRouter(_deps(video=MagicMock(), downloader=MagicMock()))
        out = await router.dispatch(
            "summarize_video", {}, _ctx(bot=_NativeBot()))
        assert out.startswith("ОШИБКА summarize_video")
        dl = await router.dispatch(
            "download_media", {}, _ctx(bot=_NativeBot()))
        assert json.loads(dl)["status"] == "error"


# ── (c) probe-fail: отдельный пул + R17-safe лог ─────────────────────────


class TestProbeFail:
    def test_probe_reasons_map_to_dedicated_pool(self):
        assert vd._probe_error_phrase("probe_failed") is VD_PROBE_FAIL_PHRASES
        assert vd._probe_error_phrase("probe_timeout") is VD_PROBE_FAIL_PHRASES
        assert vd._probe_error_phrase("cobalt_down") is VD_SERVICE_DOWN_PHRASES
        assert VD_PROBE_FAIL_PHRASES is not VD_ERROR_PHRASES

    @pytest.mark.asyncio
    async def test_probe_fail_message_from_dedicated_pool(self, vd_env):
        vd_env.probe = AsyncMock(
            side_effect=DownloadError("p", reason="probe_timeout"))
        vd_env.download = AsyncMock(
            side_effect=DownloadError("d", reason="probe_failed"))
        bot = _NativeBot()
        await vd.video_download_handler(_make_msg(text=f"Бот, скачай {URL}"),
                                        bot=bot)
        edits = [c.args[2] for c in bot.edit_message_text.call_args_list]
        assert any(t in VD_PROBE_FAIL_PHRASES for t in edits)

    @pytest.mark.asyncio
    async def test_probe_fail_logs_reason_without_url(self, vd_env, caplog):
        vd_env.probe = AsyncMock(
            side_effect=DownloadError("p", reason="probe_timeout"))
        vd_env.download = AsyncMock(
            side_effect=DownloadError("d", reason="probe_failed"))
        with caplog.at_level(logging.WARNING):
            await vd.video_download_handler(
                _make_msg(text=f"Бот, скачай {URL}"), bot=_NativeBot())
        assert "reason=probe_timeout" in caplog.text
        assert "example.com" not in caplog.text


# ── (d) контракт схем (F14 → F19) ────────────────────────────────────────


class TestSchemasContract:
    def test_summarize_video_optional_url_no_mode(self):
        params = TOOL_SUMMARIZE_VIDEO["function"]["parameters"]
        assert params["required"] == []
        assert "mode" not in params["properties"]
        assert params["properties"]["source"]["enum"] == ["link", "reply"]
        assert params["additionalProperties"] is False

    def test_transcribe_contract_defined_but_not_registered(self):
        """F14 фиксирует контракт; 10-й (в конец) регистрирует F19 — текущий
        список остаётся 9 имён в каноническом порядке."""
        names = [t["function"]["name"] for t in TOOL_CALLING_TOOLS]
        assert names == _FIRST_NINE
        assert "transcribe_video" not in names
        assert TOOL_TRANSCRIBE_VIDEO["function"]["name"] == "transcribe_video"
        params = TOOL_TRANSCRIBE_VIDEO["function"]["parameters"]
        assert params["required"] == []
        assert params["properties"]["source"]["enum"] == ["link", "reply"]
        assert params["additionalProperties"] is False

    def test_definitions_distinguishable(self):
        summary = TOOL_SUMMARIZE_VIDEO["function"]["description"]
        transcribe = TOOL_TRANSCRIBE_VIDEO["function"]["description"]
        assert "SUMMARY" in summary
        assert "not the raw transcript" in summary
        assert "RAW verbatim" in transcribe
        assert "do NOT summarize" in transcribe


# ── (g) аддитивность + резолвер ──────────────────────────────────────────


class TestAdditive:
    def test_deps_context_new_fields_default_none(self):
        deps = ToolDeps(search=MagicMock(), memory=MagicMock())
        assert deps.transcriber is None
        assert ToolContext(1, "q").native_media is None

    def test_document_pdf_not_video(self):
        pdf = SimpleNamespace(file_id="d", mime_type="application/pdf",
                              file_name="док.pdf")
        assert not document_is_video(pdf)
        msg = _make_msg(document=pdf)
        assert resolve_reply_video(msg) is None

    def test_youtube_resolver_delegates(self):
        from handlers import youtube
        assert youtube._document_is_video is native_media.document_is_video
        assert youtube._VideoMedia is native_media.NativeMedia
