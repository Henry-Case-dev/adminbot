"""Раунд 10.15 (F8, T-1616) — гибридный вызов функций: Fast-Track regex (F6)
остаётся приоритетным, свободная форма идёт в tool-loop.

Покрытие spec §10: состав тулов (7), существующие схемы не изменены,
приоритет Fast-Track, свободная форма → tool_call → бэкенд, корнер-кейс
скачивания (фиктивный tool_response + реальная отправка), summarize_video,
get_bot_health, лимиты tool-loop, R17, обратная совместимость.

Моки сервисов/LLM, без сети.
"""
import copy
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.llm_client import (
    LLMBadResponseError,
    LLMChatResult,
    LLMError,
    LLMToolCall,
)
from services.smartmodule_throttling import CooldownTracker
from services.tool_loop import chat_with_tools
from services.tool_router import (
    ToolContext,
    ToolDeps,
    ToolHealthDeps,
    ToolRouter,
)
from services.tool_schemas import (
    TOOL_CALLING_TOOLS,
    TOOL_DIG_INTO_LORE,
    TOOL_DOWNLOAD_MEDIA,
    TOOL_EXECUTE_WEB_SEARCH,
    TOOL_GET_BOT_HEALTH,
    TOOL_GET_RECENT_HISTORY,
    TOOL_QUERY_CHAT_MEMORY,
    TOOL_SUMMARIZE_VIDEO,
)

CHAT_ID = -1001234567890
_URL = "https://cdn.example.com/secret-video-98765.mp4"
_YT_URL = "https://youtu.be/ABCDEFGHIJK"


# ── общие фейки ──────────────────────────────────────────────────────────


class _FakeBot:
    """Минимальный Bot: send_video/send_document/send_message."""

    def __init__(self, send_error=None):
        self.sent_video = []
        self.sent_document = []
        self._send_error = send_error

    async def send_video(self, chat_id, file, **kwargs):
        if self._send_error is not None:
            raise self._send_error
        self.sent_video.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)

    async def send_document(self, chat_id, file, **kwargs):
        self.sent_document.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)

    async def send_message(self, chat_id, text, **kwargs):
        return SimpleNamespace(message_id=2)


def _set_download_gate(monkeypatch, enabled):
    """flags.download_enabled через hot.get (settings — frozen)."""
    from services import hot_config as hot
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


# ── 1. Состав tool-сета и снапшот существующих схем ─────────────────────


class TestToolSet:
    def test_twelve_tools_in_canonical_order(self):
        # 10.20 (C/T-1887): +compile_lore_story (8-й, в конце);
        # 10.23 (F5/ADR-1023-5 D2): +generate_image (9-й);
        # 10.24 (F19/ADR-1024-20 §2.1): +transcribe_video (10-й, в конец);
        # 10.26 (A2/ADR-1026-15 D5): +fetch_article (11-й, в конец);
        # 10.26 (A6/ADR-1026-18 D1): +get_user_context (12-й, в конец).
        assert [t["function"]["name"] for t in TOOL_CALLING_TOOLS] == [
            "query_chat_memory", "dig_into_lore", "execute_web_search",
            "summarize_video", "download_media", "get_bot_health",
            "get_recent_history", "compile_lore_story", "generate_image",
            "transcribe_video", "fetch_article", "get_user_context"]

    def test_existing_schemas_unchanged(self):
        """Существующие 3 схемы — те же объекты и та же форма (не менялись)."""
        assert TOOL_CALLING_TOOLS[0] is TOOL_QUERY_CHAT_MEMORY
        assert TOOL_CALLING_TOOLS[1] is TOOL_DIG_INTO_LORE
        assert TOOL_CALLING_TOOLS[2] is TOOL_EXECUTE_WEB_SEARCH
        props = TOOL_QUERY_CHAT_MEMORY["function"]["parameters"]["properties"]
        assert props["time_range"]["enum"] == [
            "last_day", "last_week", "last_month", "all"]
        assert TOOL_DIG_INTO_LORE["function"]["parameters"]["properties"][
            "mode"]["enum"] == ["messages", "facts", "both"]

    def test_new_schemas_shape(self):
        # F14 (ADR-1024-15 §2.3-bis, UPD5): url стал ОПЦИОНАЛЬНЫМ, добавлен
        # `source`; у summarize_video удалён `mode` (только выжимка).
        params = TOOL_SUMMARIZE_VIDEO["function"]["parameters"]
        assert params["required"] == []
        assert params["properties"]["url"]["type"] == "string"
        assert params["properties"]["source"]["enum"] == ["link", "reply"]
        assert "mode" not in params["properties"]
        dl_params = TOOL_DOWNLOAD_MEDIA["function"]["parameters"]
        assert dl_params["required"] == []
        assert dl_params["properties"]["source"]["enum"] == ["link", "reply"]
        assert TOOL_GET_BOT_HEALTH["function"]["parameters"]["properties"] == {}
        assert "depth" in TOOL_GET_RECENT_HISTORY["function"]["parameters"][
            "properties"]
        for tool in TOOL_CALLING_TOOLS:
            json.dumps(tool)                 # JSON-сериализуемость payload

    def test_backward_compatible_deps_and_context(self):
        deps = ToolDeps(search=MagicMock(), memory=MagicMock())
        assert deps.video is None and deps.downloader is None
        assert deps.health is None and deps.db is None
        ctx = ToolContext(1, "q")
        assert ctx.bot is None and ctx.reply_to_message_id is None
        assert ctx.user_id is None


# ── 2. Fast-Track (F6) приоритетнее LLM ──────────────────────────────────


def _vd_message(text):
    return SimpleNamespace(
        text=text, caption=None, message_id=5,
        chat=SimpleNamespace(id=CHAT_ID),
        from_user=SimpleNamespace(id=10),
        reply_to_message=None, video=None, document=None)


class TestFastTrackPriority:
    async def _run(self, monkeypatch, text):
        from handlers import video_download as vd
        # R10.15-4: хендлер гейтит master-флаг (в тест-env settings-дефолт
        # False) — для прямого вызова включаем флаг, как боевой .env.
        _set_download_gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.probe = AsyncMock(
            return_value=vd.ProbeResult("видео", ("360p", "720p")))
        monkeypatch.setattr(vd, "_downloader", downloader)
        monkeypatch.setattr(vd, "_cooldown", CooldownTracker(0))
        bot = _FakeBot()
        result = await vd.video_download_handler(_vd_message(text), bot)
        return result, downloader, bot

    @pytest.mark.asyncio
    async def test_canonical_command_consumed_by_worker(self, monkeypatch):
        """`Бот, скачай <url>` — консьюм download-воркером; до LLM не доходит
        (хендлер возвращает None, а не UNHANDLED → пропагации нет)."""
        result, downloader, bot = await self._run(
            monkeypatch, f"Бот, скачай {_YT_URL}")
        assert result is None                    # consumed (не UNHANDLED)
        downloader.probe.assert_awaited_once()
        assert bot.sent_document == []           # LLM-путь не запускался

    @pytest.mark.asyncio
    async def test_persona_name_prefix_consumed(self, monkeypatch):
        from services import command_prefix
        monkeypatch.setattr(command_prefix, "command_prefix_tokens",
                            lambda: ("олег",))
        result, downloader, _ = await self._run(
            monkeypatch, f"Олег, скачай {_YT_URL}")
        assert result is None
        downloader.probe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_free_form_without_prefix_propagates(self, monkeypatch):
        """Без префикса F6 — не Fast-Track: сообщение уходит дальше
        (UNHANDLED) → его распознаёт LLM через инструменты (гибрид)."""
        result, downloader, _ = await self._run(
            monkeypatch, "скачай этот видос пожалуйста")
        assert result is not None                # UNHANDLED
        downloader.probe.assert_not_awaited()


# ── 3. tool-loop: свободная форма → tool_call → бэкенд ───────────────────


class _ToolCallLLM:
    """1-й вызов → tool_calls; 2-й → финальный текст. Хранит messages."""

    def __init__(self, tool_calls, final_text="готово"):
        self._tool_calls = list(tool_calls)
        self.final_text = final_text
        self.calls = 0
        self.last_messages = None

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.calls += 1
        self.last_messages = copy.deepcopy(messages)
        if self.calls == 1:
            return LLMChatResult(content=None, tool_calls=self._tool_calls,
                                 finish_reason="tool_calls")
        return LLMChatResult(content=self.final_text, tool_calls=None,
                             finish_reason="stop")


class TestToolLoopIntegration:
    @pytest.mark.asyncio
    async def test_free_form_download_sends_file_and_fake_response(
            self, monkeypatch, tmp_path):
        """Свободная форма → LLM вызвал download_media → бэкенд сам отправил
        файл → в LLM ушёл фиктивный {"status":"success",...}."""
        _set_download_gate(monkeypatch, True)
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"data")
        downloader = MagicMock()
        downloader.download = AsyncMock(return_value=path)
        router = ToolRouter(_deps(downloader=downloader))
        bot = _FakeBot()
        llm = _ToolCallLLM([
            LLMToolCall(id="call_1", name="download_media",
                        arguments=json.dumps({"url": _URL}))])
        ctx = _ctx(bot=bot, reply_to_message_id=77, user_id=10)
        out = await chat_with_tools(llm, [{"role": "user", "content": "скачай"}],
                                    tools=TOOL_CALLING_TOOLS, router=router,
                                    ctx=ctx)
        assert out == "готово"
        downloader.download.assert_awaited_once_with(_URL, None)
        assert len(bot.sent_video) == 1
        assert bot.sent_video[0][1]["reply_to_message_id"] == 77
        assert not path.exists()                 # tmp убран
        tool_msg = [m for m in llm.last_messages if m.get("role") == "tool"][0]
        assert json.loads(tool_msg["content"]) == {
            "status": "success", "message": "Файл успешно загружен в чат"}

    @pytest.mark.asyncio
    async def test_platform_url_asks_quality(
            self, monkeypatch, tmp_path):
        """Раунд 10.17 (ADR-1017-2): YouTube/платформенный URL → probe →
        меню качества (`needs_quality`), download не стартует."""
        from tools.video_downloader import ProbeResult
        _set_download_gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.probe = AsyncMock(
            return_value=ProbeResult("ролик", ("1080p", "720p")))
        downloader.download = AsyncMock()
        bot = _FakeBot()
        out = await ToolRouter(_deps(downloader=downloader)).dispatch(
            "download_media", {"url": _YT_URL}, _ctx(bot=bot))
        assert json.loads(out)["status"] == "needs_quality"
        downloader.download.assert_not_awaited()
        assert bot.sent_video == []

    @pytest.mark.asyncio
    async def test_download_failure_is_honest_error_no_send(
            self, monkeypatch):
        _set_download_gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.download = AsyncMock(side_effect=RuntimeError("boom"))
        router = ToolRouter(_deps(downloader=downloader))
        bot = _FakeBot()
        out = await router.dispatch("download_media", {"url": _URL},
                                    _ctx(bot=bot, reply_to_message_id=1))
        data = json.loads(out)
        assert data["status"] == "error"
        assert "успешно" not in data["message"].lower()
        assert bot.sent_video == [] and bot.sent_document == []

    @pytest.mark.asyncio
    async def test_send_failure_reports_error_and_cleans_tmp(
            self, monkeypatch, tmp_path):
        _set_download_gate(monkeypatch, True)
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"data")
        downloader = MagicMock()
        downloader.download = AsyncMock(return_value=path)
        router = ToolRouter(_deps(downloader=downloader))
        bot = _FakeBot(send_error=RuntimeError("tg down"))
        out = await router.dispatch("download_media", {"url": _URL},
                                    _ctx(bot=bot))
        assert json.loads(out)["status"] == "error"
        assert not path.exists()

    @pytest.mark.asyncio
    async def test_download_gate_off_returns_error(self, monkeypatch):
        _set_download_gate(monkeypatch, False)
        downloader = MagicMock()
        downloader.download = AsyncMock()
        router = ToolRouter(_deps(downloader=downloader))
        out = await router.dispatch("download_media", {"url": _URL},
                                    _ctx(bot=_FakeBot()))
        assert json.loads(out)["status"] == "error"
        downloader.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_download_bad_url_error(self):
        out = await ToolRouter(_deps(downloader=MagicMock())).dispatch(
            "download_media", {"url": "не ссылка"}, _ctx(bot=_FakeBot()))
        assert json.loads(out)["status"] == "error"


class TestDownloadCooldown:
    """Follow-up R10.15-9: tool `download_media` уважает общий кулдаун 4e."""

    @staticmethod
    def _tracker(seconds=1000.0):
        from services.smartmodule_throttling import CooldownTracker
        return CooldownTracker(seconds)

    @pytest.mark.asyncio
    async def test_active_cooldown_blocks_without_download(self, monkeypatch):
        _set_download_gate(monkeypatch, True)
        tracker = self._tracker()
        tracker.touch(CHAT_ID, 10)              # слот занят
        downloader = MagicMock()
        downloader.download = AsyncMock()
        router = ToolRouter(_deps(downloader=downloader,
                                  download_cooldown=lambda: tracker))
        out = await router.dispatch("download_media", {"url": _URL},
                                    _ctx(bot=_FakeBot(), user_id=10))
        assert json.loads(out)["status"] == "error"
        downloader.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_touches_cooldown(self, monkeypatch, tmp_path):
        _set_download_gate(monkeypatch, True)
        tracker = self._tracker()
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"data")
        downloader = MagicMock()
        downloader.download = AsyncMock(return_value=path)
        router = ToolRouter(_deps(downloader=downloader,
                                  download_cooldown=lambda: tracker))
        out = await router.dispatch("download_media", {"url": _URL},
                                    _ctx(bot=_FakeBot(), user_id=10))
        assert json.loads(out)["status"] == "success"
        assert tracker.remaining(CHAT_ID, 10) > 0

    @pytest.mark.asyncio
    async def test_no_cooldown_provider_is_noop(self, monkeypatch, tmp_path):
        _set_download_gate(monkeypatch, True)
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"data")
        downloader = MagicMock()
        downloader.download = AsyncMock(return_value=path)
        out = await ToolRouter(_deps(downloader=downloader)).dispatch(
            "download_media", {"url": _URL}, _ctx(bot=_FakeBot(), user_id=10))
        assert json.loads(out)["status"] == "success"


# ── 4. summarize_video ───────────────────────────────────────────────────


class _FakeVideo:
    def __init__(self, summary="выжимка", transcript="сырой текст",
                 media="выжимка по ссылке"):
        self.engine = MagicMock()
        self.engine.fetch_transcript = AsyncMock(return_value=transcript)
        self.summarize_cascade = AsyncMock(return_value=summary)
        self.summarize_media_url = AsyncMock(return_value=media)


class TestSummarizeVideo:
    @pytest.mark.asyncio
    async def test_youtube_summary_delegates_cascade(self):
        video = _FakeVideo()
        out = await ToolRouter(_deps(video=video)).dispatch(
            "summarize_video", {"url": _YT_URL, "mode": "summary"}, _ctx())
        assert out == "выжимка"
        video.summarize_cascade.assert_awaited_once_with(
            "ABCDEFGHIJK", chat_id=CHAT_ID)
        video.engine.fetch_transcript.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_summarize_ignores_stray_mode(self):
        """F14 (ADR-1024-15 §2.3-bis): `mode` удалён из схемы; лишний аргумент
        больше НЕ переключает summarize на транскрипт — инструмент всегда
        отдаёт выжимку (сырой транскрипт — отдельный `transcribe_video`, F19)."""
        video = _FakeVideo()
        out = await ToolRouter(_deps(video=video)).dispatch(
            "summarize_video", {"url": _YT_URL, "mode": "transcript"}, _ctx())
        assert out == "выжимка"
        video.engine.fetch_transcript.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_youtube_summary_uses_media_url(self):
        video = _FakeVideo()
        out = await ToolRouter(_deps(video=video)).dispatch(
            "summarize_video", {"url": _URL}, _ctx())
        assert out == "выжимка по ссылке"
        video.summarize_media_url.assert_awaited_once_with(
            chat_id=CHAT_ID, video_url=_URL)

    @pytest.mark.asyncio
    async def test_non_url_error(self):
        video = _FakeVideo()
        out = await ToolRouter(_deps(video=video)).dispatch(
            "summarize_video", {"url": "просто текст"}, _ctx())
        assert out.startswith("ОШИБКА summarize_video")
        video.summarize_cascade.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_service_error_structured(self):
        video = _FakeVideo()
        video.summarize_cascade = AsyncMock(side_effect=LLMError("нет ключа"))
        out = await ToolRouter(_deps(video=video)).dispatch(
            "summarize_video", {"url": _YT_URL}, _ctx())
        assert out == "ОШИБКА summarize_video: LLMError"

    @pytest.mark.asyncio
    async def test_result_truncated(self):
        video = _FakeVideo(summary="x" * 9000)
        out = await ToolRouter(_deps(video=video)).dispatch(
            "summarize_video", {"url": _YT_URL}, _ctx())
        assert len(out) <= 3510 and out.endswith("…")

    @pytest.mark.asyncio
    async def test_video_service_missing(self):
        out = await ToolRouter(_deps()).dispatch(
            "summarize_video", {"url": _YT_URL}, _ctx())
        assert out.startswith("ОШИБКА summarize_video")


# ── 5. get_bot_health ────────────────────────────────────────────────────


class TestGetBotHealth:
    @pytest.mark.asyncio
    async def test_fetch_and_checkup(self):
        service = MagicMock()
        service.checkup = AsyncMock(return_value="бота зелёный")
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("logs", False))
        router = ToolRouter(_deps(health=ToolHealthDeps(service, fetcher)))
        out = await router.dispatch("get_bot_health", {}, _ctx())
        assert out == "бота зелёный"
        fetcher.fetch.assert_awaited_once()
        service.checkup.assert_awaited_once_with("logs", False)

    @pytest.mark.asyncio
    async def test_failure_structured(self):
        service = MagicMock()
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(side_effect=RuntimeError("нет логов"))
        router = ToolRouter(_deps(health=ToolHealthDeps(service, fetcher)))
        out = await router.dispatch("get_bot_health", {}, _ctx())
        assert out == "ОШИБКА get_bot_health: RuntimeError"

    @pytest.mark.asyncio
    async def test_missing_health(self):
        out = await ToolRouter(_deps()).dispatch("get_bot_health", {}, _ctx())
        assert out.startswith("ОШИБКА get_bot_health")

    @pytest.mark.asyncio
    async def test_disabled_module_short_circuits(self, monkeypatch):
        """Follow-up R10.15-2: flags.checkup_enabled=false → без fetch/LLM."""
        from services import hot_config as hot
        real_get = hot.get
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: False
            if key == "flags.checkup_enabled" else real_get(key, default))
        service = MagicMock()
        service.checkup = AsyncMock()
        fetcher = MagicMock()
        fetcher.fetch = AsyncMock()
        router = ToolRouter(_deps(health=ToolHealthDeps(service, fetcher)))
        out = await router.dispatch("get_bot_health", {}, _ctx())
        assert out.startswith("ОШИБКА get_bot_health")
        fetcher.fetch.assert_not_awaited()
        service.checkup.assert_not_awaited()


# ── 6. get_recent_history (seam F9) ──────────────────────────────────────


class TestRecentHistorySeam:
    @pytest.mark.asyncio
    async def test_registered_not_unknown(self):
        """F8 регистрирует инструмент (7-й); «неизвестный инструмент» — нет."""
        out = await ToolRouter(_deps()).dispatch("get_recent_history", {},
                                                 _ctx())
        assert "неизвестный инструмент" not in out
        assert "get_recent_history" in out


# ── 7. Лимиты tool-loop ──────────────────────────────────────────────────


class _CountingRouter:
    def __init__(self):
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments)))
        return "ok"


class _OverflowLLM:
    def __init__(self):
        self.calls = 0

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            calls = [LLMToolCall(id=f"c{i}", name="query_chat_memory",
                                 arguments='{"query":"x"}') for i in range(3)]
            return LLMChatResult(content=None, tool_calls=calls,
                                 finish_reason="tool_calls")
        return LLMChatResult(content="ответ", tool_calls=None,
                             finish_reason="stop")


class TestToolLoopLimits:
    @pytest.mark.asyncio
    async def test_more_than_two_calls_truncated(self):
        router = _CountingRouter()
        await chat_with_tools(_OverflowLLM(), [{"role": "user", "content": "x"}],
                              tools=TOOL_CALLING_TOOLS, router=router,
                              ctx=_ctx())
        assert len(router.calls) == 2

    @pytest.mark.asyncio
    async def test_provider_without_tools_plain_answer(self):
        class _NoToolsLLM:
            def __init__(self):
                self.plain = 0

            async def generate_chat(self, *a, **k):
                raise LLMError("provider rejects tools")

            async def generate(self, messages, temperature=None, chat_id=None,
                               **kwargs):
                self.plain += 1
                return "обычный ответ"

        llm = _NoToolsLLM()
        out = await chat_with_tools(llm, [{"role": "user", "content": "x"}],
                                    tools=TOOL_CALLING_TOOLS,
                                    router=_CountingRouter(), ctx=_ctx())
        assert out == "обычный ответ" and llm.plain == 1

    @pytest.mark.asyncio
    async def test_round_limit_degrades(self):
        from services.tool_loop import TOOL_LOOP_FALLBACK_PHRASE

        class _AlwaysToolLLM:
            async def generate_chat(self, *a, **k):
                return LLMChatResult(
                    content=None,
                    tool_calls=[LLMToolCall(id="c", name="query_chat_memory",
                                            arguments='{"query":"x"}')],
                    finish_reason="tool_calls")

        out = await chat_with_tools(_AlwaysToolLLM(),
                                    [{"role": "user", "content": "x"}],
                                    tools=TOOL_CALLING_TOOLS,
                                    router=_CountingRouter(), ctx=_ctx())
        assert out.degraded is True
        assert out.reason == "round_limit"
        assert out == TOOL_LOOP_FALLBACK_PHRASE


# ── 8. R17 ───────────────────────────────────────────────────────────────


class TestR17:
    @pytest.mark.asyncio
    async def test_download_failure_logs_no_url(self, monkeypatch, caplog):
        _set_download_gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.download = AsyncMock(side_effect=RuntimeError("boom"))
        router = ToolRouter(_deps(downloader=downloader))
        with caplog.at_level(logging.WARNING):
            await router.dispatch("download_media", {"url": _URL},
                                  _ctx(bot=_FakeBot()))
        assert "secret-video" not in caplog.text
        assert "cdn.example.com" not in caplog.text

    @pytest.mark.asyncio
    async def test_summarize_failure_logs_no_url(self, caplog):
        video = _FakeVideo()
        video.summarize_cascade = AsyncMock(side_effect=RuntimeError("boom"))
        with caplog.at_level(logging.WARNING):
            await ToolRouter(_deps(video=video)).dispatch(
                "summarize_video", {"url": _YT_URL}, _ctx())
        assert "youtu.be" not in caplog.text


# ── 9. direct_chat: ctx несёт bot/reply/user (F8 §4) ─────────────────────


class TestDirectChatContext:
    @pytest.mark.asyncio
    async def test_tool_context_carries_bot_and_reply(self, monkeypatch):
        from tests.test_direct_chat import (
            _bot as dc_bot,
            _make_service,
            _message as dc_message,
            _user as dc_user,
        )
        from services import hot_config as hot
        real_get = hot.get
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: False
            if key == "flags.bot_self_awareness_enabled"
            else real_get(key, default))
        captured = {}

        async def _fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                        temperature, chat_id=None, **kwargs):
            captured["ctx"] = ctx
            captured["tools"] = tools
            return "готовый ответ"

        monkeypatch.setattr("services.direct_chat_service.chat_with_tools",
                            _fake_chat_with_tools)
        service = _make_service(tool_router=MagicMock())
        bot = dc_bot()
        user = dc_user()
        msg = dc_message(text="скачай этот видос пожалуйста", message_id=555,
                         user=user)
        await service.handle(bot, msg, user)
        ctx = captured["ctx"]
        assert ctx.bot is bot
        assert ctx.reply_to_message_id == 555
        assert ctx.user_id == user.id
        # 10.20 (C/T-1887): флаг «Летописца» default ON; 10.23 (F5): модуль
        # генерации изображений default ON; 10.24 (F19): transcribe_video
        # default ON; 10.26 (A2): fetch_article default ON; 10.26 (A6):
        # get_user_context default ON → 12 инструментов.
        assert len(captured["tools"]) == 12
