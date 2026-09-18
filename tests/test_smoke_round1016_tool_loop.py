"""Смоук раунда 10.16 (T-1644) — tool-loop «имитация реальной работы».

In-process, без сети: LLM-фейк отдаёт `tool_calls`, реальный `ToolRouter`
диспатчит инструмент, результат уходит в роль `tool`. Проверяются:
  * полный цикл LLM→tool_call→dispatch→tool_response→финал (в т.ч. фиктивный
    success скачивания F8 — бэкенд сам отправляет файл);
  * лимиты: ≤2 вызовов на раунд (truncate) и ≤4 раундов (LLMBadResponseError);
  * fail-safe: неизвестный инструмент → текст «ОШИБКА…», цикл не падает;
  * деградация провайдера (LLMError на 1-м раунде) → обычный ответ без tools.
"""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import video_download as vd
from services import hot_config as hot
from services.llm_client import (
    LLMBadResponseError,
    LLMChatResult,
    LLMError,
    LLMToolCall,
)
from services.smartmodule_throttling import CooldownTracker
from services.tool_loop import TOOL_MAX_ROUNDS, chat_with_tools
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.tool_schemas import TOOL_CALLING_TOOLS

CHAT_ID = -1001234567890
_URL = "https://youtu.be/ABCDEFGHIJK"


class _FakeBot:
    def __init__(self):
        self.sent_video = []

    async def send_video(self, chat_id, file, **kwargs):
        self.sent_video.append((chat_id, kwargs))
        return SimpleNamespace(message_id=1)

    async def send_document(self, chat_id, file, **kwargs):
        return SimpleNamespace(message_id=1)

    async def send_message(self, chat_id, text, **kwargs):
        return SimpleNamespace(message_id=2)


class _ScriptedLLM:
    """По одному результату на вызов generate_chat, последний — финал."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0
        self.last_messages = None

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.calls += 1
        self.last_messages = copy.deepcopy(messages)
        return self._results.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        return "обычный ответ"


def _tc(call_id, name, args):
    return LLMToolCall(id=call_id, name=name,
                       arguments=json.dumps(args))


def _tool_msg(llm):
    return [m for m in llm.last_messages if m.get("role") == "tool"]


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(CHAT_ID, "свободная форма", **kwargs)


def _deps(**kwargs) -> ToolDeps:
    kwargs.setdefault("search", MagicMock())
    kwargs.setdefault("memory", MagicMock())
    return ToolDeps(**kwargs)


def _gate(monkeypatch, enabled):
    real_get = hot.get
    monkeypatch.setattr(
        hot, "get",
        lambda key, default=None: enabled
        if key == "flags.download_enabled" else real_get(key, default))


# ── 1. полный цикл ───────────────────────────────────────────────────────


class TestToolLoopFullCycle:
    @pytest.mark.asyncio
    async def test_download_media_asks_quality_and_fake_response(
            self, monkeypatch, tmp_path):
        """R10.17 (ADR-1017-2): LLM вызвал download_media для платформы →
        бэкенд шлёт меню качества, в LLM уходит фиктивный
        `{"status":"needs_quality",...}` (модель не «печатает» файл)."""
        from tools.video_downloader import ProbeResult
        _gate(monkeypatch, True)
        downloader = MagicMock()
        downloader.probe = AsyncMock(
            return_value=ProbeResult("ролик", ("1080p", "720p")))
        downloader.download = AsyncMock()
        router = ToolRouter(_deps(downloader=downloader))
        bot = _FakeBot()
        llm = _ScriptedLLM([
            LLMChatResult(content=None,
                          tool_calls=[_tc("call_1", "download_media",
                                          {"url": _URL})],
                          finish_reason="tool_calls"),
            LLMChatResult(content="готово", tool_calls=None,
                          finish_reason="stop"),
        ])
        out = await chat_with_tools(
            llm, [{"role": "user", "content": "скачай"}],
            tools=TOOL_CALLING_TOOLS, router=router,
            ctx=_ctx(bot=bot, reply_to_message_id=7, user_id=1))
        assert out == "готово"
        downloader.download.assert_not_awaited()
        tool = _tool_msg(llm)[0]
        assert json.loads(tool["content"])["status"] == "needs_quality"
        assert bot.sent_video == []

    @pytest.mark.asyncio
    async def test_unknown_tool_is_failsafe_and_loop_continues(
            self, monkeypatch):
        router = ToolRouter(_deps())
        llm = _ScriptedLLM([
            LLMChatResult(content=None,
                          tool_calls=[_tc("c1", "no_such_tool", {})],
                          finish_reason="tool_calls"),
            LLMChatResult(content="финал", tool_calls=None, finish_reason="stop"),
        ])
        out = await chat_with_tools(llm, [{"role": "user", "content": "x"}],
                                    tools=TOOL_CALLING_TOOLS, router=router,
                                    ctx=_ctx(bot=_FakeBot()))
        assert out == "финал"
        assert "ОШИБКА" in _tool_msg(llm)[0]["content"]


# ── 2. лимиты 4/2 ────────────────────────────────────────────────────────


class TestToolLoopLimits:
    @pytest.mark.asyncio
    async def test_per_round_truncated_to_two(self, monkeypatch, caplog):
        router = ToolRouter(_deps())
        calls = [_tc(f"c{i}", "no_such_tool", {}) for i in range(3)]
        llm = _ScriptedLLM([
            LLMChatResult(content=None, tool_calls=calls,
                          finish_reason="tool_calls"),
            LLMChatResult(content="финал", tool_calls=None, finish_reason="stop"),
        ])
        import logging
        with caplog.at_level(logging.WARNING):
            await chat_with_tools(llm, [{"role": "user", "content": "x"}],
                                  tools=TOOL_CALLING_TOOLS, router=router,
                                  ctx=_ctx(bot=_FakeBot()))
        assert len(_tool_msg(llm)) == 2         # 3 → 2
        assert any("tool_calls truncated" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_round_limit_degrades(self, monkeypatch):
        from services.tool_loop import TOOL_LOOP_FALLBACK_PHRASE
        router = ToolRouter(_deps())
        always = [LLMChatResult(content=None,
                                tool_calls=[_tc(f"c{i}", "no_such_tool", {})],
                                finish_reason="tool_calls")
                  for i in range(TOOL_MAX_ROUNDS)]
        llm = _ScriptedLLM(always)
        out = await chat_with_tools(llm, [{"role": "user", "content": "x"}],
                                    tools=TOOL_CALLING_TOOLS, router=router,
                                    ctx=_ctx(bot=_FakeBot()))
        assert out.degraded is True
        assert out.reason == "round_limit"
        assert out == TOOL_LOOP_FALLBACK_PHRASE
        assert llm.calls == TOOL_MAX_ROUNDS


# ── 3. деградация провайдера ─────────────────────────────────────────────


class TestToolLoopDegrade:
    @pytest.mark.asyncio
    async def test_provider_rejects_tools_plain_answer(self, monkeypatch):
        class _Rejecting(_ScriptedLLM):
            async def generate_chat(self, *a, **k):
                self.calls += 1
                raise LLMError("tools unsupported")

        llm = _Rejecting([])
        router = ToolRouter(_deps())
        out = await chat_with_tools(llm, [{"role": "user", "content": "x"}],
                                    tools=TOOL_CALLING_TOOLS, router=router,
                                    ctx=_ctx())
        assert out == "обычный ответ"
        assert llm.calls == 1


# ── 4. Fast-Track приоритет (4e) ─────────────────────────────────────────


class TestFastTrackPrioritySmoke:
    @pytest.mark.asyncio
    async def test_prefixed_download_consumed_not_llm(self, monkeypatch):
        _gate(monkeypatch, True)
        dl = MagicMock()
        dl.busy = False
        dl.probe = AsyncMock(return_value=vd.ProbeResult(
            "видео", ("360p", "720p")))
        monkeypatch.setattr(vd, "_downloader", dl)
        monkeypatch.setattr(vd, "_cooldown", CooldownTracker(0))
        msg = SimpleNamespace(
            text=f"Бот, скачай {_URL}", caption=None, message_id=5,
            chat=SimpleNamespace(id=CHAT_ID),
            from_user=SimpleNamespace(id=10),
            reply_to_message=None, video=None, document=None)
        result = await vd.video_download_handler(msg, _FakeBot())
        assert result is None                 # consumed → до LLM не доходит
