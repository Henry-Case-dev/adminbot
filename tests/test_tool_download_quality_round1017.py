"""Раунд 10.17 (F2, ADR-1017-2) — tool-скачивание + запрос качества.

Покрытие spec §6: probe→меню (`needs_quality`), callback `tdq:` доводит
скачивание, direct/явное качество без меню, bounded probe-fallback,
TTL/stale, busy, кулдаун (D279), R17, паритет enum схемы, supersede ADR.
Без сети — downloader/bot/LLM замоканы.
"""
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from handlers import video_download as vd
from services import hot_config as hot
from services import tool_router as tr
from services.llm_client import LLMChatResult, LLMToolCall
from services.smartmodule_throttling import CooldownTracker
from services.tool_loop import (
    TOOL_MAX_ROUNDS,
    _TOOL_CALLS_PER_ROUND_MAX,
    chat_with_tools,
)
from services.tool_router import (
    ToolContext,
    ToolDeps,
    ToolRouter,
    pop_tool_download_pending,
    store_tool_download_pending,
)
from services.tool_schemas import TOOL_CALLING_TOOLS, TOOL_DOWNLOAD_MEDIA
from tools.video_download_phrases import VD_BUSY_PHRASES
from tools.video_downloader import (
    QUALITY_ENUM,
    DownloadError,
    ProbeResult,
    VideoDownloader,
)

CHAT_ID = -1001234567890
USER_ID = 10
_YT = "https://youtu.be/ABCDEFGHIJK"
_TIKTOK = "https://www.tiktok.com/@user/video/1234567890"
_MP4 = "https://cdn.example.com/secret-clip-777.mp4?key=TOPSECRETSIGNATURE"


# ── фейки/хелперы ────────────────────────────────────────────────────────


class _FakeBot:
    def __init__(self):
        self.sent_video = []
        self.sent_document = []
        self.send_message = AsyncMock(
            return_value=SimpleNamespace(message_id=42))
        self.edit_message_text = AsyncMock()
        self.delete_message = AsyncMock()
        self.send_chat_action = AsyncMock()

    async def send_video(self, chat_id, file, **kwargs):
        self.sent_video.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)

    async def send_document(self, chat_id, file, **kwargs):
        self.sent_document.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)


def _make_cb(data, user_id=USER_ID):
    cb = MagicMock()
    cb.data = data
    cb.answer = AsyncMock()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = MagicMock()
    cb.message.chat.id = CHAT_ID
    cb.message.delete = AsyncMock()
    return cb


def _gate(monkeypatch, enabled):
    real_get = hot.get
    monkeypatch.setattr(
        hot, "get",
        lambda key, default=None: enabled
        if key == "flags.download_enabled" else real_get(key, default))


def _deps(**kwargs) -> ToolDeps:
    kwargs.setdefault("search", MagicMock())
    kwargs.setdefault("memory", MagicMock())
    return ToolDeps(**kwargs)


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(CHAT_ID, "свободная форма", **kwargs)


def _mk_downloader(*, probe_result=None, probe_exc=None,
                   download_result=None, download_exc=None):
    """MagicMock-downloader с РЕАЛЬНЫМ `_normalize_quality` (паритет с prod)."""
    dl = MagicMock()
    dl.busy = False
    dl._normalize_quality = VideoDownloader._normalize_quality
    if probe_exc is not None:
        dl.probe = AsyncMock(side_effect=probe_exc)
    else:
        dl.probe = AsyncMock(
            return_value=(probe_result
                          or ProbeResult("Ролик", ("1080p", "720p"))))
    if download_exc is not None:
        dl.download = AsyncMock(side_effect=download_exc)
    else:
        dl.download = AsyncMock(return_value=download_result)
    return dl


@pytest.fixture(autouse=True)
def _clean_pending():
    tr._TOOL_DL_PENDING.clear()
    yield
    tr._TOOL_DL_PENDING.clear()


# ── 1. tool: probe → меню, download НЕ вызван ────────────────────────────


class TestToolAsksQuality:
    @pytest.mark.asyncio
    async def test_platform_probe_menu_no_download(self, monkeypatch):
        _gate(monkeypatch, True)
        dl = _mk_downloader()
        bot = _FakeBot()
        out = await ToolRouter(_deps(downloader=dl)).dispatch(
            "download_media", {"url": _YT},
            _ctx(bot=bot, reply_to_message_id=7, user_id=USER_ID))
        assert json.loads(out)["status"] == "needs_quality"
        assert "качества" in json.loads(out)["message"]
        dl.download.assert_not_awaited()
        assert bot.send_message.await_count == 1
        kb = bot.send_message.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert data == ["tdq:1080", "tdq:720"]
        # pending сохранён под (chat_id, user_id)
        assert (CHAT_ID, USER_ID) in tr._TOOL_DL_PENDING


# ── 2. callback tdq:1080 → download(url, "1080p") + отправка ─────────────


class TestToolQualityCallback:
    @pytest.mark.asyncio
    async def test_callback_downloads_chosen_quality(self, monkeypatch,
                                                     tmp_path):
        path = tmp_path / "out.mp4"
        path.write_bytes(b"x")
        dl = _mk_downloader(download_result=path)
        monkeypatch.setattr(vd, "_downloader", dl)
        monkeypatch.setattr(vd, "_cooldown", CooldownTracker(1800.0))
        store_tool_download_pending(CHAT_ID, USER_ID, url=_YT,
                                    title="Ролик", qualities=("1080p", "720p"),
                                    trigger_message_id=7)
        bot = _FakeBot()
        cb = _make_cb("tdq:1080")
        await vd.cb_tool_quality(cb, bot=bot)
        dl.download.assert_awaited_once_with(_YT, "1080p", progress_cb=ANY)
        assert len(bot.sent_video) == 1
        assert (CHAT_ID, USER_ID) not in tr._TOOL_DL_PENDING
        cb.answer.assert_awaited_once_with()          # ack без alert
        # L6: паритет UX с Fast-Track — chat action отправлен до скачивания.
        assert bot.send_chat_action.await_count == 1
        # callback кулдаун НЕ жжёт (producer уже сжёг после probe)
        assert (CHAT_ID, USER_ID) not in vd._cooldown._last

    @pytest.mark.asyncio
    async def test_callback_invalid_height_keeps_pending(self, monkeypatch):
        """L1 (ревью-итер.1): подделанная высота отвергается до consume."""
        dl = _mk_downloader()
        monkeypatch.setattr(vd, "_downloader", dl)
        store_tool_download_pending(CHAT_ID, USER_ID, url=_YT, title="t",
                                    qualities=("1080p", "720p"),
                                    trigger_message_id=7)
        cb = _make_cb("tdq:99999")
        await vd.cb_tool_quality(cb, bot=_FakeBot())
        assert cb.answer.await_args.args[0] == "эта менюха протухла"
        dl.download.assert_not_awaited()
        # pending НЕ потерян — валидная кнопка в меню продолжает работать.
        assert (CHAT_ID, USER_ID) in tr._TOOL_DL_PENDING

    @pytest.mark.asyncio
    async def test_callback_stale_pending(self, monkeypatch):
        dl = _mk_downloader()
        monkeypatch.setattr(vd, "_downloader", dl)
        tr._TOOL_DL_PENDING[(CHAT_ID, USER_ID)] = {
            "url": _YT, "title": "t", "qualities": ("1080p",),
            "trigger_message_id": 7, "expires": time.monotonic() - 1,
        }
        cb = _make_cb("tdq:1080")
        await vd.cb_tool_quality(cb, bot=_FakeBot())
        assert cb.answer.await_args.args[0] == "эта менюха протухла"
        dl.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_callback_busy_keeps_pending(self, monkeypatch):
        dl = _mk_downloader()
        dl.busy = True
        monkeypatch.setattr(vd, "_downloader", dl)
        store_tool_download_pending(CHAT_ID, USER_ID, url=_YT, title="t",
                                    qualities=("1080p",), trigger_message_id=7)
        cb = _make_cb("tdq:1080")
        await vd.cb_tool_quality(cb, bot=_FakeBot())
        assert cb.answer.call_args.kwargs.get("show_alert") is True
        assert cb.answer.call_args.args[0] in VD_BUSY_PHRASES
        dl.download.assert_not_awaited()
        # pending НЕ потерян — кнопка остаётся рабочей после BUSY
        assert (CHAT_ID, USER_ID) in tr._TOOL_DL_PENDING


# ── 3. direct / явное качество — без меню ────────────────────────────────


class TestNoMenuBranches:
    @pytest.mark.asyncio
    async def test_direct_mp4_immediate(self, monkeypatch, tmp_path):
        _gate(monkeypatch, True)
        path = tmp_path / "d.mp4"
        path.write_bytes(b"x")
        dl = _mk_downloader(download_result=path)
        bot = _FakeBot()
        out = await ToolRouter(_deps(downloader=dl)).dispatch(
            "download_media", {"url": _MP4}, _ctx(bot=bot))
        assert json.loads(out)["status"] == "success"
        dl.download.assert_awaited_once_with(_MP4, None)
        dl.probe.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_quality_no_menu(self, monkeypatch, tmp_path):
        _gate(monkeypatch, True)
        path = tmp_path / "q.mp4"
        path.write_bytes(b"x")
        dl = _mk_downloader(download_result=path)
        bot = _FakeBot()
        out = await ToolRouter(_deps(downloader=dl)).dispatch(
            "download_media", {"url": _YT, "quality": "720"}, _ctx(bot=bot))
        assert json.loads(out)["status"] == "success"
        dl.download.assert_awaited_once_with(_YT, "720")
        dl.probe.assert_not_awaited()
        bot.send_message.assert_not_awaited()


# ── 4. bounded fallback / провалы / кулдаун ──────────────────────────────


class TestFallbackAndFailures:
    @pytest.mark.asyncio
    async def test_probe_fail_bounded_fallback(self, monkeypatch, tmp_path):
        _gate(monkeypatch, True)
        path = tmp_path / "fb.mp4"
        path.write_bytes(b"x")
        dl = _mk_downloader(
            probe_exc=DownloadError("probe", reason="probe_failed"),
            download_result=path)
        bot = _FakeBot()
        out = await ToolRouter(_deps(downloader=dl)).dispatch(
            "download_media", {"url": _YT}, _ctx(bot=bot, user_id=USER_ID))
        assert json.loads(out)["status"] == "success"
        dl.download.assert_awaited_once_with(_YT, None)
        bot.send_message.assert_not_awaited()           # меню НЕ слалось

    @pytest.mark.asyncio
    async def test_probe_and_download_fail_no_cooldown(
            self, monkeypatch, caplog):
        _gate(monkeypatch, True)
        tracker = CooldownTracker(1800.0)
        dl = _mk_downloader(
            probe_exc=DownloadError("probe", reason="probe_failed"),
            download_exc=DownloadError("dl", reason="cobalt_down"))
        router = ToolRouter(_deps(downloader=dl,
                                  download_cooldown=lambda: tracker))
        with caplog.at_level(logging.WARNING):
            out = await router.dispatch("download_media", {"url": _YT},
                                        _ctx(bot=_FakeBot(),
                                             user_id=USER_ID))
        assert json.loads(out)["status"] == "error"
        assert "reason=probe_failed" in caplog.text
        assert "reason=cobalt_down" in caplog.text
        assert (CHAT_ID, USER_ID) not in tracker._last  # провал не жжёт

    @pytest.mark.asyncio
    async def test_cooldown_blocks_without_touch(self, monkeypatch):
        _gate(monkeypatch, True)
        tracker = CooldownTracker(1800.0)
        tracker.touch(CHAT_ID, USER_ID)
        touch_spy = AsyncMock()
        monkeypatch.setattr(tr, "cooldown_touch", touch_spy)
        dl = _mk_downloader()
        router = ToolRouter(_deps(downloader=dl,
                                  download_cooldown=lambda: tracker))
        out = await router.dispatch("download_media", {"url": _YT},
                                    _ctx(bot=_FakeBot(), user_id=USER_ID))
        assert json.loads(out)["status"] == "error"
        assert "кулдаун" in json.loads(out)["message"].lower()
        dl.download.assert_not_awaited()
        dl.probe.assert_not_awaited()
        touch_spy.assert_not_awaited()


# ── 5. R17: без URL/токенов в логах ──────────────────────────────────────


class TestR17:
    @pytest.mark.asyncio
    async def test_no_urls_in_logs(self, monkeypatch, caplog):
        _gate(monkeypatch, True)
        # direct-URL: скачивание падает — в логе только класс/reason.
        dl = _mk_downloader(
            download_exc=DownloadError(f"boom {_MP4}",
                                       reason="direct_failed"))
        with caplog.at_level(logging.DEBUG):
            await ToolRouter(_deps(downloader=dl)).dispatch(
                "download_media", {"url": _MP4}, _ctx(bot=_FakeBot()))
        # платформа: probe падает — в логе только класс/reason.
        dl2 = _mk_downloader(
            probe_exc=DownloadError(f"boom {_YT}", reason="probe_failed"),
            download_exc=DownloadError("nope", reason="probe_failed"))
        with caplog.at_level(logging.DEBUG):
            await ToolRouter(_deps(downloader=dl2)).dispatch(
                "download_media", {"url": _YT},
                _ctx(bot=_FakeBot(), user_id=USER_ID))
        for leak in ("http://", "https://", "secret-clip",
                     "TOPSECRETSIGNATURE", "cdn.example.com", "youtu.be"):
            assert leak not in caplog.text, leak


# ── 6. schema/enum/ADR/tool-сет ──────────────────────────────────────────


class TestSchemaAndAdr:
    def test_quality_enum_parity(self):
        params = TOOL_DOWNLOAD_MEDIA["function"]["parameters"]
        assert params["properties"]["quality"]["enum"] == list(QUALITY_ENUM)
        assert params["additionalProperties"] is False
        # F14 (ADR-1024-15 §2.3): url стал опциональным + добавлен `source`.
        assert params["required"] == []
        assert params["properties"]["source"]["enum"] == ["link", "reply"]

    def test_quality_enum_matches_allowed_heights(self):
        from tools.video_downloader import _ALLOWED_HEIGHTS
        assert QUALITY_ENUM == ("max",) + tuple(
            str(h) for h in _ALLOWED_HEIGHTS)

    def test_tool_set_names_unchanged(self):
        # 10.20 (C/T-1887): состав 7 → 8 (+compile_lore_story);
        # 10.23 (F5/ADR-1023-5 D2): +generate_image → 9;
        # 10.24 (F19/ADR-1024-20 §2.1): +transcribe_video (10-й, в конец).
        # Прежние имена и их порядок сохранены байт-в-байт.
        assert len(TOOL_CALLING_TOOLS) == 10
        assert [t["function"]["name"] for t in TOOL_CALLING_TOOLS] == [
            "query_chat_memory", "dig_into_lore", "execute_web_search",
            "summarize_video", "download_media", "get_bot_health",
            "get_recent_history", "compile_lore_story", "generate_image",
            "transcribe_video"]

    def test_adr_supersede_recorded(self):
        # 10.17: фича заархивирована @PM → артефакты лежат в plans/archive/.
        root = Path(__file__).resolve().parents[1] / "plans"
        adr = (root / "features" / "tool-download-quality-round1017"
               / "adr-1017-2-tool-download-quality.md")
        if not adr.exists():                     # fallback на архив (актуальный)
            adr = (root / "archive" / "tool-download-quality-round1017"
                   / "adr-1017-2-tool-download-quality.md")
        text = adr.read_text(encoding="utf-8")
        assert "SUPERSEDE" in text
        assert "ADR-1016-1" in text
        assert "§2 п.3" in text
        assert "§3" in text


# ── 7. tool-loop: needs_quality + лимиты 4/2 не тронуты ──────────────────


class _ScriptedLLM:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0
        self.last_messages = None

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.calls += 1
        self.last_messages = [dict(m) for m in messages]
        return self._results.pop(0)


class TestToolLoopNeedsQuality:
    @pytest.mark.asyncio
    async def test_tool_response_needs_quality(self, monkeypatch):
        _gate(monkeypatch, True)
        dl = _mk_downloader()
        router = ToolRouter(_deps(downloader=dl))
        llm = _ScriptedLLM([
            LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(
                    id="c1", name="download_media",
                    arguments=json.dumps({"url": _YT}))],
                finish_reason="tool_calls"),
            LLMChatResult(content="Предложил качество", tool_calls=None,
                          finish_reason="stop"),
        ])
        out = await chat_with_tools(
            llm, [{"role": "user", "content": "скачай"}],
            tools=TOOL_CALLING_TOOLS, router=router,
            ctx=_ctx(bot=_FakeBot(), user_id=USER_ID))
        assert out == "Предложил качество"
        tool = [m for m in llm.last_messages if m.get("role") == "tool"][0]
        assert json.loads(tool["content"])["status"] == "needs_quality"
        dl.download.assert_not_awaited()
        assert TOOL_MAX_ROUNDS == 4
        assert _TOOL_CALLS_PER_ROUND_MAX == 2
