"""F5 (T-2053…T-2061 + T-2096, ADR-1022-5) — direct chat: 2 вызова.

Покрытие: Синтезатор тулов → JSON-справка; Вербализатор видит ТОЛЬКО справку;
R17-маскирование секретов tool_context; невалидный JSON/ошибка → финал
tool-loop; validator-loop; `lore_compiled`/degraded вне System 2.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services.chat_prompts import (
    DIRECT_SYNTHESIZER_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
)
from services.direct_chat_service import DirectChatService
from services.prompt_style_blocks import compose_verbalizer_system
from services.tool_loop import ToolLoopResult

pytestmark = pytest.mark.system2

_SYNTH_JSON = json.dumps({
    "user_question": "что там с погодой",
    "facts": [{"topic": "погода", "finding": "завтра дождь",
               "source": "exa", "confidence": "high"}],
    "answer_outline": "взять зонт",
    "limitations": [],
})


def _service(side_effect):
    svc = DirectChatService.__new__(DirectChatService)
    svc.llm = MagicMock()
    svc.llm.generate = AsyncMock(side_effect=side_effect)
    return svc


def _tool_raw(text="финал tool-loop", tool_context="сырые логи инструмента"):
    return ToolLoopResult(
        text, rounds_used=2,
        tool_trace=[{"round": 1, "tool": "execute_web_search", "ok": True,
                     "out_chars": 20}],
        tool_context=tool_context)


class TestDirectTwoCall:
    @pytest.mark.asyncio
    async def test_valid_two_call(self):
        svc = _service([_SYNTH_JSON, "дерзкий короткий ответ"])
        text, mode = await svc._synthesize_direct_answer(
            -100, "что с погодой", _tool_raw(), None)
        assert text == "дерзкий короткий ответ"
        assert mode == "serious"          # нет поля → fail-safe serious
        assert svc.llm.generate.await_count == 2
        stage1 = svc.llm.generate.await_args_list[0].args[0]
        stage2 = svc.llm.generate.await_args_list[1].args[0]
        assert stage1[0]["content"] == DIRECT_SYNTHESIZER_SYSTEM_PROMPT
        assert stage2[0]["content"] == compose_verbalizer_system(
            DIRECT_VERBALIZER_SYSTEM_PROMPT, "serious", "plain")
        assert stage2[1]["content"].startswith("СПРАВКА (JSON):")

    @pytest.mark.asyncio
    async def test_verbalizer_isolated_from_tool_logs(self):
        svc = _service([_SYNTH_JSON, "ответ"])
        await svc._synthesize_direct_answer(
            -100, "q", _tool_raw(tool_context="СЕКРЕТНЫЙ_ЛОГ_ТУЛА"), None)
        stage2_user = svc.llm.generate.await_args_list[1].args[0][1]["content"]
        assert "СЕКРЕТНЫЙ_ЛОГ_ТУЛА" not in stage2_user

    @pytest.mark.asyncio
    async def test_secrets_redacted_before_synth(self):
        secret = "sk-abcdefghijklmnop123456"
        svc = _service([_SYNTH_JSON, "ответ"])
        await svc._synthesize_direct_answer(
            -100, "q", _tool_raw(tool_context=f"token={secret}"), None)
        stage1_user = svc.llm.generate.await_args_list[0].args[0][1]["content"]
        assert secret not in stage1_user
        assert "[redacted]" in stage1_user

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none_single_call(self):
        svc = _service(["не json"])
        assert await svc._synthesize_direct_answer(
            -100, "q", _tool_raw(), None) is None
        assert svc.llm.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_llm_error_returns_none(self):
        svc = _service(RuntimeError("boom"))
        assert await svc._synthesize_direct_answer(
            -100, "q", _tool_raw(), None) is None

    @pytest.mark.asyncio
    async def test_validator_loop_retry(self):
        svc = _service([_SYNTH_JSON, "как ИИ", "чистый ответ"])
        text, _mode = await svc._synthesize_direct_answer(
            -100, "q", _tool_raw(), None)
        assert text == "чистый ответ"
        assert svc.llm.generate.await_count == 3

    @pytest.mark.asyncio
    async def test_validator_exhausted_returns_best(self):
        svc = _service([_SYNTH_JSON, "как ИИ и подводя итог", "подводя итог",
                        "в заключение"])
        text, _mode = await svc._synthesize_direct_answer(
            -100, "q", _tool_raw(), None)
        assert text == "подводя итог"

    @pytest.mark.asyncio
    async def test_empty_verbalizer_returns_none(self):
        svc = _service([_SYNTH_JSON, "   "])
        assert await svc._synthesize_direct_answer(
            -100, "q", _tool_raw(), None) is None


class TestDirectSynthesisValidation:
    """Ревью (Medium-7): `user_question`/`answer_outline` тоже проходят
    `contains_system_ids`/`redact_secrets`; нарушение → None (fallback)."""

    def _raw(self, **over):
        data = json.loads(_SYNTH_JSON)
        data.update(over)
        return json.dumps(data)

    def test_system_ids_in_question_rejected(self):
        from services.system2_handoff import parse_direct_synthesis
        assert parse_direct_synthesis(
            self._raw(user_question="смотри fact:12")) is None

    def test_system_ids_in_outline_rejected(self):
        from services.system2_handoff import parse_direct_synthesis
        assert parse_direct_synthesis(
            self._raw(answer_outline="шаг 1 msg:9")) is None

    def test_secrets_redacted_in_question_and_outline(self):
        from services.system2_handoff import parse_direct_synthesis
        secret = "sk-abcdefghijklmnop123456"
        data = parse_direct_synthesis(self._raw(
            user_question=f"токен {secret}",
            answer_outline=f"отдать {secret}"))
        assert data is not None
        assert secret not in data["user_question"]
        assert secret not in data["answer_outline"]
        assert "[redacted]" in data["user_question"]
        assert "[redacted]" in data["answer_outline"]


class TestDirectHandleBranchOn:
    """Ревью (High-3): прод-ветка `handle` при SYSTEM2_DIRECT_ENABLED=ON —
    System 2 не вызывается при degraded/lore_compiled/пустом tool_trace."""

    def _drive(self, monkeypatch, raw, *, lore=False, enabled=True):
        import services.direct_chat_service as dcs
        from tests.test_direct_chat import _bot, _make_service, _message, _user
        monkeypatch.setattr(Settings, "SYSTEM2_DIRECT_ENABLED", enabled)
        svc = _make_service(tool_router=MagicMock())
        synth = AsyncMock(return_value=("SYNTH", "serious"))
        send = AsyncMock(return_value=None)
        svc._synthesize_direct_answer = synth
        svc._send_direct_answer = send

        async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                       temperature, chat_id):
            if lore:
                ctx.lore_compiled = True
                ctx.lore_story = "HTML история"
            return raw

        monkeypatch.setattr(dcs, "chat_with_tools", fake_chat_with_tools)
        return svc, synth, send, _bot, _message, _user

    def _trace(self):
        return [{"round": 1, "tool": "t", "ok": True, "out_chars": 3}]

    @pytest.mark.asyncio
    async def test_degraded_skips_system2(self, monkeypatch):
        raw = ToolLoopResult("финал tool-loop", rounds_used=2, degraded=True,
                             reason="llm_error", tool_trace=self._trace(),
                             tool_context="логи")
        svc, synth, send, _bot, _msg, _user = self._drive(monkeypatch, raw)
        await svc.handle(_bot(), _msg(), _user())
        synth.assert_not_awaited()
        assert send.await_args.args[2] == "финал tool-loop"

    @pytest.mark.asyncio
    async def test_lore_compiled_skips_system2(self, monkeypatch):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=self._trace(), tool_context="логи")
        svc, synth, send, _bot, _msg, _user = self._drive(
            monkeypatch, raw, lore=True)
        await svc.handle(_bot(), _msg(), _user())
        synth.assert_not_awaited()
        assert send.await_args.args[2] == "HTML история"
        assert send.await_args.kwargs.get("lore") is True

    @pytest.mark.asyncio
    async def test_empty_tool_trace_skips_system2(self, monkeypatch):
        raw = ToolLoopResult("финал", rounds_used=1, tool_trace=[],
                             tool_context="")
        svc, synth, _send, _bot, _msg, _user = self._drive(monkeypatch, raw)
        await svc.handle(_bot(), _msg(), _user())
        synth.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_valid_trace_calls_system2(self, monkeypatch):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=self._trace(), tool_context="логи")
        svc, synth, send, _bot, _msg, _user = self._drive(monkeypatch, raw)
        await svc.handle(_bot(), _msg(), _user())
        synth.assert_awaited_once()
        assert send.await_args.args[2] == "SYNTH"

    @pytest.mark.asyncio
    async def test_flag_off_skips_system2(self, monkeypatch):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=self._trace(), tool_context="логи")
        svc, synth, _send, _bot, _msg, _user = self._drive(
            monkeypatch, raw, enabled=False)
        await svc.handle(_bot(), _msg(), _user())
        synth.assert_not_awaited()
