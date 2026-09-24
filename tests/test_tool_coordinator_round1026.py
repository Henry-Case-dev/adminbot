"""A1 `tool-coordinator-round1026` (Эпик 3 Wave 1, §13/§14, ADR-1026-14 D1–D10).

Покрытие:
  * Координатор (программный слой в существующем Синтезаторе): намерение /
    адресат / необходимость памяти; выбор инструментов + оценка результатов;
    решение о действии ≠ текст (гейт Stage-2).
  * Общий механизм цепочек — reuse `tool_loop` (зависимые A→B последовательны;
    лимиты `TOOL_MAX_ROUNDS`/≤2-в-раунде; fail-open); отсутствие
    per-combination обработчиков.
  * Изоляция Вербализатора (только `stage2_payload` + стиль).
  * R17-safe наблюдаемость координатора.
  * Регресс живого direct-чата: OFF/legacy; 2-вызовность (`await_count==2`);
    отсутствие wire-`action`.
  * Границы diff (§104/§85-UI/DDL/каталог/промпты), версия/канон.
"""
import dataclasses
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import APP_VERSION, Settings
from services import param_catalog as pc
from services.direct_chat_service import (
    ACTION_REACT,
    ACTION_REPLY,
    ACTION_SILENT,
    ACTION_TOOL,
    ADDRESSEE_AUTHOR,
    ADDRESSEE_FORWARD,
    ADDRESSEE_REPLY,
    ADDRESSEE_UNKNOWN,
    COORDINATOR_ACTIONS,
    CoordinatorDecision,
    EVAL_DEGRADED,
    EVAL_FAILED,
    EVAL_NONE,
    EVAL_OK,
    EVAL_PARTIAL,
    INTENT_CHAT,
    INTENT_FORWARD,
    INTENT_IMAGE,
    INTENT_NOSTALGIA,
    INTENT_QUESTION,
    DirectChatService,
    _coordinator_addressee,
    _coordinator_choose_action,
    _coordinator_evaluate,
    _coordinator_intent,
    _coordinator_memory_need,
    _coordinator_tool_names,
    build_coordinator_decision,
    coordinator_enabled,
)
from services.llm_client import LLMChatResult, LLMError, LLMToolCall
from services.system2_handoff import parse_direct_synthesis, stage2_payload
from services.tool_loop import (
    TOOL_LOOP_FALLBACK_PHRASE,
    TOOL_MAX_ROUNDS,
    ToolLoopResult,
    chat_with_tools,
)
from services.tool_schemas import TOOL_CALLING_TOOLS

ROOT = Path(__file__).resolve().parents[1]

# Тесты System-2-контура (гейт Stage-2, 2-вызовность) — маркер снимает
# autouse-патч `_system2_flags_off_by_default` (tests/conftest.py) и держит
# прод-дефолты ON, как в test_direct_two_call_round1022.py.
pytestmark = pytest.mark.system2

_SYNTH_JSON = json.dumps({
    "user_question": "что там с погодой",
    "facts": [{"topic": "погода", "finding": "завтра дождь",
               "source": "exa", "confidence": "high"}],
    "answer_outline": "взять зонт",
    "limitations": [],
})


# ── Вспомогательные ────────────────────────────────────────────────────────

def _tc(name, call_id=None, arguments="{}"):
    return LLMToolCall(id=call_id or f"call_{name}", name=name,
                       arguments=arguments)


def _chat(content=None, tool_calls=None):
    return LLMChatResult(content=content, tool_calls=tool_calls,
                         finish_reason="tool_calls" if tool_calls else "stop")


class _FakeRouter:
    def __init__(self):
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments)))
        return f"out:{name}"


class _FakeToolLLM:
    """LLM для `chat_with_tools`: очередь ответов (или исключений)."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def generate_chat(self, messages, **kwargs):
        self.calls.append([dict(m) for m in messages])
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, messages, **kwargs):
        return "PLAIN"


def _trace(*tools):
    return [{"round": i + 1, "tool": t, "ok": True, "out_chars": 5}
            for i, t in enumerate(tools)]


# ── 1. Координатор: чистые функции ─────────────────────────────────────────

class TestCoordinatorIntent:
    def test_image_marker_wins(self):
        assert _coordinator_intent("что угодно", image_fired=True,
                                   dig_fired=True, forward=True) == INTENT_IMAGE

    def test_nostalgia_marker(self):
        assert _coordinator_intent("помнишь", image_fired=False,
                                   dig_fired=True, forward=False) == INTENT_NOSTALGIA

    def test_forward(self):
        assert _coordinator_intent("текст", image_fired=False,
                                   dig_fired=False, forward=True) == INTENT_FORWARD

    def test_question(self):
        assert _coordinator_intent("как дела?", image_fired=False,
                                   dig_fired=False, forward=False) == INTENT_QUESTION

    def test_chat_default(self):
        assert _coordinator_intent("привет", image_fired=False,
                                   dig_fired=False, forward=False) == INTENT_CHAT


class TestCoordinatorAddressee:
    def test_forward(self):
        assert _coordinator_addressee(MagicMock(), forward=True,
                                      has_author=True) == ADDRESSEE_FORWARD

    def test_reply_target(self):
        m = MagicMock()
        m.reply_to_message = MagicMock()
        m.reply_to_message.from_user = MagicMock()
        assert _coordinator_addressee(m, forward=False,
                                      has_author=True) == ADDRESSEE_REPLY

    def test_author(self):
        m = MagicMock()
        m.reply_to_message = None
        assert _coordinator_addressee(m, forward=False,
                                      has_author=True) == ADDRESSEE_AUTHOR

    def test_unknown(self):
        m = MagicMock()
        m.reply_to_message = None
        assert _coordinator_addressee(m, forward=False,
                                      has_author=False) == ADDRESSEE_UNKNOWN


class TestCoordinatorMemoryAndTools:
    def test_memory_tool_detected(self):
        assert _coordinator_memory_need(
            ("query_chat_memory",), dig_fired=False, lore_compiled=False)

    def test_dig_pre_gate_detected(self):
        assert _coordinator_memory_need(
            (), dig_fired=True, lore_compiled=False)

    def test_no_memory_need(self):
        assert not _coordinator_memory_need(
            ("execute_web_search",), dig_fired=False, lore_compiled=False)

    def test_tool_names_order_and_dedup(self):
        trace = _trace("b", "a", "b")
        assert _coordinator_tool_names(trace) == ("b", "a")

    def test_tool_names_empty(self):
        assert _coordinator_tool_names([]) == ()


class TestCoordinatorEvaluation:
    def test_none(self):
        assert _coordinator_evaluate([], False) == EVAL_NONE

    def test_ok(self):
        assert _coordinator_evaluate(_trace("a", "b"), False) == EVAL_OK

    def test_partial(self):
        trace = [{"tool": "a", "ok": True}, {"tool": "b", "ok": False}]
        assert _coordinator_evaluate(trace, False) == EVAL_PARTIAL

    def test_failed(self):
        trace = [{"tool": "a", "ok": False}, {"tool": "b", "ok": False}]
        assert _coordinator_evaluate(trace, False) == EVAL_FAILED

    def test_degraded_wins(self):
        assert _coordinator_evaluate(_trace("a"), True) == EVAL_DEGRADED


class TestCoordinatorAction:
    def test_tool_action(self):
        assert _coordinator_choose_action(
            has_tools=True, degraded=False, lore_compiled=False) == ACTION_TOOL

    def test_reply_without_tools(self):
        assert _coordinator_choose_action(
            has_tools=False, degraded=False, lore_compiled=False) == ACTION_REPLY

    def test_reply_when_degraded(self):
        assert _coordinator_choose_action(
            has_tools=True, degraded=True, lore_compiled=False) == ACTION_REPLY

    def test_reply_when_lore_compiled(self):
        assert _coordinator_choose_action(
            has_tools=True, degraded=False, lore_compiled=True) == ACTION_REPLY

    def test_enum_members(self):
        assert set(COORDINATOR_ACTIONS) == {
            ACTION_REPLY, ACTION_REACT, ACTION_SILENT, ACTION_TOOL}


# ── 2. Сборка решения (0 LLM) ──────────────────────────────────────────────

class TestBuildCoordinatorDecision:
    def _build(self, raw, **over):
        kwargs = dict(query="привет", message=MagicMock(), raw=raw,
                      user_id=10, image_fired=False, dig_fired=False,
                      lore_compiled=False)
        kwargs.update(over)
        kwargs["message"].reply_to_message = None
        return build_coordinator_decision(**kwargs)

    def test_tool_turn(self):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("execute_web_search",
                                               "query_chat_memory"),
                             tool_context="логи")
        d = self._build(raw)
        assert isinstance(d, CoordinatorDecision)
        assert d.action == ACTION_TOOL
        assert d.tool_calls == ("execute_web_search", "query_chat_memory")
        assert d.evaluation == EVAL_OK
        assert d.memory_need is True
        assert d.intent == INTENT_CHAT
        assert d.enabled is True

    def test_plain_turn(self):
        raw = ToolLoopResult("просто ответ", rounds_used=1, tool_trace=[],
                             tool_context="")
        d = self._build(raw, query="как дела?")
        assert d.action == ACTION_REPLY
        assert d.tool_calls == ()
        assert d.evaluation == EVAL_NONE
        assert d.memory_need is False
        assert d.intent == INTENT_QUESTION

    def test_degraded_turn(self):
        raw = ToolLoopResult("частичный", rounds_used=4, degraded=True,
                             reason="round_limit",
                             tool_trace=_trace("execute_web_search"))
        d = self._build(raw)
        assert d.action == ACTION_REPLY
        assert d.evaluation == EVAL_DEGRADED

    def test_intent_image(self):
        raw = ToolLoopResult("x", rounds_used=1, tool_trace=[])
        d = self._build(raw, image_fired=True)
        assert d.intent == INTENT_IMAGE

    def test_never_raises_on_garbage(self):
        d = self._build(object())
        assert d.action == ACTION_REPLY


# ── 3. Общий механизм цепочек — reuse `tool_loop` ──────────────────────────

class TestChainMechanism:
    """A1 не создаёт per-combination обработчики: механизм цепочек — общий
    многораундовый `tool_loop` (ADR-1026-14 D3). Границы §15–§17 — A2."""

    @pytest.mark.asyncio
    async def test_dependent_calls_are_sequential(self):
        llm = _FakeToolLLM([
            _chat(tool_calls=[_tc("tool_a")]),
            _chat(tool_calls=[_tc("tool_b")]),
            _chat(content="финал"),
        ])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "tool_a"}}],
            router=router, ctx=object())
        assert str(result) == "финал"
        # A→B — последовательно, в порядке вызова моделью.
        assert [c[0] for c in router.calls] == ["tool_a", "tool_b"]
        assert [e["tool"] for e in result.tool_trace] == ["tool_a", "tool_b"]
        # Результат A попал в следующий LLM-вызов (role "tool"), затем B.
        second = llm.calls[1]
        assert any(m.get("role") == "tool"
                   and m.get("content") == "out:tool_a" for m in second)
        third = llm.calls[2]
        assert any(m.get("role") == "tool"
                   and m.get("content") == "out:tool_b" for m in third)

    @pytest.mark.asyncio
    async def test_calls_per_round_truncated(self):
        llm = _FakeToolLLM([
            _chat(tool_calls=[_tc("a"), _tc("b"), _tc("c")]),
            _chat(content="финал"),
        ])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "a"}}],
            router=router, ctx=object())
        assert [c[0] for c in router.calls] == ["a", "b"]
        assert len(result.tool_trace) == 2

    @pytest.mark.asyncio
    async def test_round_limit_degraded(self):
        llm = _FakeToolLLM([
            _chat(tool_calls=[_tc("a")]) for _ in range(TOOL_MAX_ROUNDS)
        ])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "a"}}],
            router=router, ctx=object())
        assert result.degraded is True
        assert result.reason == "round_limit"
        assert str(result) == TOOL_LOOP_FALLBACK_PHRASE

    @pytest.mark.asyncio
    async def test_late_llm_error_fail_open(self):
        llm = _FakeToolLLM([
            _chat(tool_calls=[_tc("a")]),
            LLMError("boom"),
        ])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "a"}}],
            router=router, ctx=object())
        assert result.degraded is True
        assert result.reason == "llm_error"

    @pytest.mark.asyncio
    async def test_provider_reject_plain_fallback(self):
        llm = _FakeToolLLM([LLMError("no tools")])
        router = _FakeRouter()
        result = await chat_with_tools(
            llm, [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "a"}}],
            router=router, ctx=object())
        assert str(result) == "PLAIN"
        assert result.degraded is False

    def test_tool_loop_is_tool_agnostic(self):
        """Нет per-combination обработчиков: цикл не ветвится по именам
        инструментов, а диспетчеризует ЛЮБОЕ имя через общий `router.dispatch`."""
        src = (ROOT / "services" / "tool_loop.py").read_text(encoding="utf-8")
        assert "router.dispatch(tc.name, arguments, ctx)" in src
        assert "if tc.name ==" not in src
        assert "if tc.name in" not in src
        assert "if name ==" not in src

    def test_no_second_router_in_direct_service(self):
        src = (ROOT / "services" / "direct_chat_service.py").read_text(
            encoding="utf-8")
        assert "async def dispatch(" not in src


# ── 4. Изоляция Вербализатора + отсутствие wire-`action` ───────────────────

def _synth_service(side_effect):
    svc = DirectChatService.__new__(DirectChatService)
    svc.llm = MagicMock()
    svc.llm.generate = AsyncMock(side_effect=side_effect)
    return svc


class TestVerbalizerIsolation:
    @pytest.mark.asyncio
    async def test_stage2_excludes_raw_tool_logs(self):
        raw = ToolLoopResult(
            "финал", rounds_used=2, tool_trace=_trace("execute_web_search"),
            tool_context="СЕКРЕТНЫЙ_ЛОГ_ТУЛА")
        svc = _synth_service([_SYNTH_JSON, "ответ"])
        await svc._synthesize_direct_answer(-100, "q", raw, None)
        stage2_user = svc.llm.generate.await_args_list[1].args[0][1]["content"]
        assert "СЕКРЕТНЫЙ_ЛОГ_ТУЛА" not in stage2_user
        assert stage2_user.startswith("СПРАВКА (JSON):")

    @pytest.mark.asyncio
    async def test_stage2_gets_style_not_service_fields(self):
        raw = ToolLoopResult(
            "финал", rounds_used=2, tool_trace=_trace("execute_web_search"),
            tool_context="логи")
        svc = _synth_service([_SYNTH_JSON, "ответ"])
        await svc._synthesize_direct_answer(-100, "q", raw, None)
        stage2_system = svc.llm.generate.await_args_list[1].args[0][0]["content"]
        stage2_user = svc.llm.generate.await_args_list[1].args[0][1]["content"]
        # Стиль (response_mode) едет системным блоком Вербализатора.
        assert "response_mode" not in stage2_user
        assert "action" not in stage2_user
        assert stage2_system


class TestNoWireAction:
    def test_stage1_contract_keys_unchanged(self):
        data = parse_direct_synthesis(_SYNTH_JSON)
        assert set(data.keys()) == {
            "user_question", "facts", "answer_outline", "limitations",
            "response_mode"}
        assert "action" not in data

    def test_stage2_payload_strips_service_fields(self):
        data = {"user_question": "q", "facts": [], "answer_outline": "o",
                "response_mode": "casual", "cover_prompt": "x"}
        payload = stage2_payload(data)
        assert "response_mode" not in payload
        assert "cover_prompt" not in payload
        assert "action" not in payload

    def test_decision_is_not_serialized(self):
        raw = ToolLoopResult("x", rounds_used=1, tool_trace=[])
        m = MagicMock()
        m.reply_to_message = None
        d = build_coordinator_decision(
            query="q", message=m, raw=raw, user_id=1, image_fired=False,
            dig_fired=False, lore_compiled=False)
        # Объект решения — внутренний; в Stage-контракты не попадает.
        assert isinstance(d, CoordinatorDecision)
        assert not hasattr(d, "to_json")


# ── 5. Интеграция в `handle`: гейт Stage-2 и OFF/legacy ────────────────────

def _drive_handle(monkeypatch, raw, *, enabled=True, lore=False,
                  synth=("SYNTH", "serious")):
    import services.direct_chat_service as dcs
    from tests.test_direct_chat import _bot, _make_service, _message, _user
    monkeypatch.setattr(Settings, "DIRECT_COORDINATOR_ENABLED", enabled)
    svc = _make_service(tool_router=MagicMock())
    synth_mock = AsyncMock(return_value=synth)
    send = AsyncMock(return_value=None)
    svc._synthesize_direct_answer = synth_mock
    svc._send_direct_answer = send

    async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                   temperature, chat_id, **kwargs):
        if lore:
            ctx.lore_compiled = True
            ctx.lore_story = "HTML история"
        return raw

    monkeypatch.setattr(dcs, "chat_with_tools", fake_chat_with_tools)
    return svc, synth_mock, send, _bot(), _message(), _user()


class TestHandleGate:
    @pytest.mark.asyncio
    async def test_tool_action_calls_verbalizer(self, monkeypatch):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("execute_web_search"),
                             tool_context="логи")
        svc, synth, send, bot, msg, user = _drive_handle(monkeypatch, raw)
        await svc.handle(bot, msg, user)
        synth.assert_awaited_once()
        assert send.await_args.args[2] == "SYNTH"

    @pytest.mark.asyncio
    async def test_plain_turn_skips_verbalizer(self, monkeypatch):
        raw = ToolLoopResult("просто", rounds_used=1, tool_trace=[],
                             tool_context="")
        svc, synth, send, bot, msg, user = _drive_handle(monkeypatch, raw)
        await svc.handle(bot, msg, user)
        synth.assert_not_awaited()
        assert send.await_args.args[2] == "просто"

    @pytest.mark.asyncio
    async def test_degraded_skips_verbalizer(self, monkeypatch):
        raw = ToolLoopResult("частичный", rounds_used=4, degraded=True,
                             reason="round_limit",
                             tool_trace=_trace("execute_web_search"),
                             tool_context="логи")
        svc, synth, _send, bot, msg, user = _drive_handle(monkeypatch, raw)
        await svc.handle(bot, msg, user)
        synth.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lore_compiled_skips_verbalizer(self, monkeypatch):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("compile_lore_story"),
                             tool_context="логи")
        svc, synth, send, bot, msg, user = _drive_handle(
            monkeypatch, raw, lore=True)
        await svc.handle(bot, msg, user)
        synth.assert_not_awaited()
        assert send.await_args.args[2] == "HTML история"

    @pytest.mark.asyncio
    async def test_gate_equivalence_on_off(self, monkeypatch):
        """Координатор не меняет исход гейта Stage-2 (ON ≡ OFF)."""
        scenarios = {
            "tool": ToolLoopResult("f", rounds_used=2,
                                   tool_trace=_trace("a"), tool_context=""),
            "plain": ToolLoopResult("f", rounds_used=1, tool_trace=[],
                                    tool_context=""),
            "degraded": ToolLoopResult("f", rounds_used=4, degraded=True,
                                       reason="round_limit",
                                       tool_trace=_trace("a"),
                                       tool_context=""),
        }
        for name, raw in scenarios.items():
            for enabled in (True, False):
                svc, synth, _send, bot, msg, user = _drive_handle(
                    monkeypatch, raw, enabled=enabled)
                await svc.handle(bot, msg, user)
                expected = name == "tool"
                assert synth.await_count == (1 if expected else 0), (
                    name, enabled)


class TestHandleTwoCallPreserved:
    @pytest.mark.asyncio
    async def test_await_count_is_two(self, monkeypatch):
        from tests.test_direct_chat import _bot, _make_service, _message, _user
        import services.direct_chat_service as dcs
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("execute_web_search"),
                             tool_context="логи")
        svc = _make_service(tool_router=MagicMock())
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[_SYNTH_JSON, "дерзкий ответ"])
        svc._send_direct_answer = AsyncMock(return_value=999)
        svc.remember_bot_reply = AsyncMock()

        async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                       temperature, chat_id, **kwargs):
            return raw

        monkeypatch.setattr(dcs, "chat_with_tools", fake_chat_with_tools)
        await svc.handle(_bot(), _message(), _user())
        # Ровно 2 физических LLM-вызова System 2 (Stage-1 + Stage-2).
        assert svc.llm.generate.await_count == 2


class TestCoordinatorObservability:
    @pytest.mark.asyncio
    async def test_r17_no_raw_text_in_logs(self, monkeypatch, caplog):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("execute_web_search"),
                             tool_context="СЕКРЕТ_ТУЛА")
        svc, _synth, _send, bot, msg, user = _drive_handle(monkeypatch, raw)
        query_secret = "СЕКРЕТ_ЗАПРОСА_42"
        msg.text = query_secret
        with caplog.at_level("INFO", logger="services.direct_chat_service"):
            await svc.handle(bot, msg, user)
        coord_lines = [r.getMessage() for r in caplog.records
                       if r.getMessage().startswith("[coordinator]")]
        assert coord_lines, "нет событий координатора"
        blob = "\n".join(coord_lines)
        assert query_secret not in blob
        assert "СЕКРЕТ_ТУЛА" not in blob
        assert "execute_web_search" in blob      # имя инструмента — безопасно

    @pytest.mark.asyncio
    async def test_off_no_coordinator_logs(self, monkeypatch, caplog):
        raw = ToolLoopResult("финал", rounds_used=2,
                             tool_trace=_trace("execute_web_search"),
                             tool_context="логи")
        svc, _synth, _send, bot, msg, user = _drive_handle(
            monkeypatch, raw, enabled=False)
        with caplog.at_level("INFO", logger="services.direct_chat_service"):
            await svc.handle(bot, msg, user)
        assert not [r for r in caplog.records
                    if r.getMessage().startswith("[coordinator]")]

    def test_kill_switch_default_on(self, monkeypatch):
        monkeypatch.setattr(Settings, "DIRECT_COORDINATOR_ENABLED", True)
        assert coordinator_enabled() is True

    def test_kill_switch_off(self, monkeypatch):
        monkeypatch.setattr(Settings, "DIRECT_COORDINATOR_ENABLED", False)
        assert coordinator_enabled() is False


# ── 6. Границы / версия / канон ────────────────────────────────────────────

class TestBounds:
    def _diff_names(self):
        out = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only",
             "pre-round1026-a1"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace")
        return [ln.strip().replace("\\", "/")
                for ln in out.stdout.splitlines() if ln.strip()]

    def test_forbidden_paths_out_of_diff(self):
        names = self._diff_names()
        forbidden = [
            "services/image_generation.py",
            "services/summary_prompts.py",
            "services/prompt_migrations.py",
            "services/param_catalog.py",
            "services/telegram_send.py",
            "services/chat_prompts.py",
            "services/execution_graph_source.py",
            "web/api/routes.py",
            "plans/current_task.md",
        ]
        for path in forbidden:
            assert path not in names, path
        assert not any(n.startswith("db/") for n in names)
        assert not any(n.startswith("web/") for n in names)
        assert not any(n.startswith("services/summary_") for n in names)

    def test_version_and_catalog(self):
        assert APP_VERSION == "2.58.30"
        assert len(pc.REGISTRY) == 469
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 444
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21

    def test_canon_ten_tools(self):
        assert len(TOOL_CALLING_TOOLS) == 10

    def test_kill_switch_not_in_catalog(self):
        assert "DIRECT_COORDINATOR_ENABLED" not in pc.REGISTRY
        assert "DIRECT_COORDINATOR_ENABLED" not in {
            f.name for f in dataclasses.fields(Settings)}

    def test_no_ddl_in_coordinator_sources(self):
        for rel in ("services/direct_chat_service.py",
                    "services/tool_loop.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            assert "CREATE TABLE" not in src, rel
            assert "ALTER TABLE" not in src, rel
