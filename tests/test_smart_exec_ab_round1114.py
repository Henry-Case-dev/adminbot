"""SMART-EXECUTION-RELIABILITY-01 — контракт этапов A+B (owner 2026-11-14).

Проверяется НАБЛЮДАЕМОЕ поведение, а не текст исходников:

A (budgets OFF)
  * effective `flags.budgets_enabled=false` не включает enforcement ни через
    legacy/env-переключатели, ни через внутренние потолки;
  * last-known-valid: известный OFF не превращается в ON при ошибке чтения;
    отсутствие достоверной конфигурации помечается явно (`known=False`);
  * usage/metered/стоимость продолжают собираться (наблюдательные оси);
  * при budgets ON явная операторская политика действует и даёт честный
    структурный отказ, не теряя tool_call_id.

B (единая политика tool-loop)
  * L1-контроль: >4 раундов, >6 вызовов, >2 вызовов за раунд — все
    исполнены, каждый со своим `tool_call_id` и валидной последовательностью
    `assistant(tool_calls) -> tool(each id) -> assistant`;
  * завершение по прогрессу (`no_progress`), дедуп идентичных условий,
    retryable-повтор, отсутствие универсального дедлайна.
"""
from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock

import pytest

from config.settings import Settings
from services import budget_gate
from services import tool_result
from services import worker_settings
from services.llm_client import LLMChatResult, LLMToolCall
from services.tool_loop import (
    CHAIN_CALL_LIMIT_REASON,
    ToolLoopResult,
    chat_with_tools,
    normalize_tool_plan,
    resolve_chain_limits,
)

MESSAGES = [{"role": "user", "content": "исследуй"}]
TOOLS = [{"type": "function"}]
CHAT_ID = -1001234567890


# ── фейки ───────────────────────────────────────────────────────────────────


class FakeLLM:
    def __init__(self, answers):
        self._answers = list(answers)
        self.all_messages = []

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.all_messages.append(copy.deepcopy(messages))
        assert self._answers, "не хватило запланированных ответов"
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):        # plain-фолбэк провайдера без tools
        return "обычный ответ"


class FakeRouter:
    def __init__(self, outputs=None, fn=None):
        self._outputs = dict(outputs or {})
        self._fn = fn
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments or {})))
        if self._fn is not None:
            return await self._fn(name, arguments, ctx)
        return self._outputs.get(name, f"данные:{name}")


def _round(prefix: str, calls: list[tuple[str, dict]]) -> LLMChatResult:
    return LLMChatResult(
        content=None,
        tool_calls=[LLMToolCall(id=f"{prefix}_{i}", name=name,
                                arguments=json.dumps(args, ensure_ascii=False))
                    for i, (name, args) in enumerate(calls)],
        finish_reason="tool_calls")


def _text(value: str) -> LLMChatResult:
    return LLMChatResult(content=value, tool_calls=None, finish_reason="stop")


def _assert_valid_sequence(snapshot: list[dict]) -> None:
    """Провайдерская валидность: на каждый id ассистента есть role:tool."""
    assistant_ids: list[str] = []
    tool_ids: list[str] = []
    for message in snapshot:
        if message["role"] == "assistant":
            for call in message.get("tool_calls") or ():
                assistant_ids.append(call["id"])
        elif message["role"] == "tool":
            tool_ids.append(message["tool_call_id"])
    assert assistant_ids == tool_ids


def _patch_budgets(monkeypatch, value: bool) -> None:
    async def _enabled(chat_id=None):
        return bool(value)

    monkeypatch.setattr(budget_gate, "budgets_enabled", _enabled)


# ── A: master-рубильник и last-known-valid ─────────────────────────────────


class TestBudgetsOffContract:
    @pytest.fixture(autouse=True)
    def _reset(self):
        budget_gate.reset_cache()
        yield
        budget_gate.reset_cache()

    @pytest.mark.asyncio
    async def test_budgets_off_from_global_layer(self, monkeypatch):
        async def _resolve(key, *, chat_id=None, default=None):
            assert key == budget_gate.KEY_BUDGETS_ENABLED
            return False, "global"

        monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                            _resolve)
        state = await budget_gate.resolve_budgets(CHAT_ID)
        assert state.enabled is False
        assert state.source == "global" and state.stale is False
        assert await budget_gate.budgets_enabled(CHAT_ID) is False

    @pytest.mark.asyncio
    async def test_read_error_keeps_last_known_off(self, monkeypatch):
        calls = {"n": 0}

        async def _resolve(key, *, chat_id=None, default=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return False, "chat"
            raise RuntimeError("pg down")

        monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                            _resolve)
        assert await budget_gate.budgets_enabled(CHAT_ID) is False
        state = await budget_gate.resolve_budgets(CHAT_ID)
        assert state.enabled is False          # известный OFF не стал ON
        assert state.source == "last_known" and state.stale is True
        assert budget_gate.last_known_state(CHAT_ID).enabled is False

    @pytest.mark.asyncio
    async def test_read_error_without_known_state_is_explicit(
            self, monkeypatch):
        async def _boom(key, *, chat_id=None, default=None):
            raise RuntimeError("pg down")

        monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                            _boom)
        state = await budget_gate.resolve_budgets(7)
        assert state.known is False and state.stale is True
        assert state.source == "unknown"
        assert state.enabled is bool(Settings.BUDGETS_ENABLED)

    @pytest.mark.asyncio
    async def test_legacy_env_policy_cannot_enforce_when_off(
            self, monkeypatch):
        """budgets OFF: kill-switch/env-числа не включают enforcement."""
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", 2)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_METERED_CALLS", 1)
        monkeypatch.setattr(Settings, "TOOL_CHAIN_LIMITS_ENABLED", True)
        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                            0.5)
        _patch_budgets(monkeypatch, False)
        answers = [
            _round(f"r{r}", [("execute_web_search", {"query": f"q{r}{i}"})
                             for i in range(3)])
            for r in range(3)] + [_text("финал после девяти вызовов")]
        llm = FakeLLM(answers)
        router = FakeRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=MagicMock(),
                                    chat_id=CHAT_ID)
        assert len(router.calls) == 9            # ни один не обрезан
        assert out == "финал после девяти вызовов"
        assert out.degraded is False and out.reason == "ok"
        assert all(e["status"] == "ok" for e in out.tool_results)
        limits = resolve_chain_limits(budgets_enabled=False)
        assert limits.enforce is False
        assert (limits.max_total_calls, limits.max_metered_calls) == (2, 1)

    @pytest.mark.asyncio
    async def test_stats_continue_when_off(self, monkeypatch):
        """OFF снимает только enforcement: metered/usage-оси собираются."""
        _patch_budgets(monkeypatch, False)
        llm = FakeLLM([
            _round("r0", [("execute_web_search", {"query": "a"})]),
            _text("готово")])
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=FakeRouter(), ctx=MagicMock(),
                                    chat_id=CHAT_ID)
        env = out.tool_results[0]
        assert env["metered"] is True
        assert "usage" in env and "category" in env
        assert out == "готово"

    @pytest.mark.asyncio
    async def test_budgets_on_explicit_policy_applies(self, monkeypatch):
        """ON: явная политика оператора действует, id не теряются."""
        _patch_budgets(monkeypatch, True)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", 2)
        llm = FakeLLM([
            _round("r0", [("query_chat_memory", {"query": f"q{i}"})
                          for i in range(3)]),
            _text("финал")])
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=FakeRouter(), ctx=MagicMock(),
                                    chat_id=CHAT_ID)
        assert out.degraded is True
        assert out.reason == CHAIN_CALL_LIMIT_REASON
        assert [e.get("tool_call_id") for e in out.tool_results] == \
            ["r0_0", "r0_1", "r0_2"]             # ни один id не потерян
        assert [e["status"] for e in out.tool_results] == \
            ["ok", "ok", "denied"]
        # Отказ структурный и модельно-видимый (tool-context канал).
        denied = json.loads(out.tool_context.splitlines()[-1])
        assert denied["status"] == "denied"
        assert denied["reason"] == CHAIN_CALL_LIMIT_REASON

    def test_zero_means_policy_not_set(self, monkeypatch):
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", 0)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_METERED_CALLS", 0)
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_SAME_CALL", 0)
        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                            0.0)
        limits = resolve_chain_limits(budgets_enabled=True)
        assert (limits.max_total_calls, limits.max_metered_calls,
                limits.max_same_call, limits.fuse_seconds) == (0, 0, 0, 0.0)
        assert limits.enforce is True            # политика есть — квот нет


# ── B: L1-контроль единой политики ─────────────────────────────────────────


class TestSingleToolLoopPolicy:
    @pytest.mark.asyncio
    async def test_l1_multi_round_multi_call_all_dispatched(self):
        """>4 раундов, >6 вызовов суммарно, >2 вызова в раунде: все
        исполнены, ни один tool_call_id не потерян."""
        rounds = 5
        per_round = 3
        answers = [
            _round(f"r{r}", [("execute_web_search", {"query": f"q{r}{i}"})
                             for i in range(per_round)])
            for r in range(rounds)] + [_text("итоговый ответ")]
        llm = FakeLLM(answers)
        router = FakeRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=MagicMock(),
                                    chat_id=CHAT_ID)
        total = rounds * per_round
        assert total > 6 and per_round > 2 and rounds > 4
        assert len(router.calls) == total
        assert out == "итоговый ответ"
        assert isinstance(out, ToolLoopResult)
        assert out.degraded is False and out.reason == "ok"
        assert out.rounds_used == rounds + 1
        expected_ids = [f"r{r}_{i}" for r in range(rounds)
                        for i in range(per_round)]
        assert [e.get("tool_call_id") for e in out.tool_results] == expected_ids
        # Каждый снимок payload валиден для провайдера.
        for snapshot in llm.all_messages[1:]:
            _assert_valid_sequence(snapshot)
        # assistant-сообщение раунда содержит все три вызова (не срез).
        first_assistant = llm.all_messages[1][1]
        assert len(first_assistant["tool_calls"]) == per_round

    @pytest.mark.asyncio
    async def test_no_progress_stops_identical_repeats(self):
        answers = [_round(f"r{r}", [("execute_web_search", {"query": "same"})])
                   for r in range(6)]
        llm = FakeLLM(answers)
        router = FakeRouter()
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=MagicMock(),
                                    chat_id=CHAT_ID)
        assert out.degraded is True and out.reason == "no_progress"
        assert len(router.calls) == 1             # повтор из кэша
        assert len(llm.all_messages) == 3         # раунд + 2 без прогресса
        for snapshot in llm.all_messages[1:]:
            _assert_valid_sequence(snapshot)

    @pytest.mark.asyncio
    async def test_retryable_failure_is_retried(self):
        state = {"n": 0}

        async def _flaky(name, arguments, ctx):
            state["n"] += 1
            if state["n"] == 1:
                tool_result.set_signal(ctx, {"status": "timeout",
                                             "retryable": True})
                return '{"status":"timeout","error":"timeout"}'
            return "успех со второй попытки"

        llm = FakeLLM([
            _round("r0", [("execute_web_search", {"query": "x"})]),
            _round("r1", [("execute_web_search", {"query": "x"})]),
            _text("финал")])
        router = FakeRouter(fn=_flaky)
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS,
                                    router=router, ctx=MagicMock(),
                                    chat_id=CHAT_ID)
        assert state["n"] == 2                    # retryable повторён
        assert out.degraded is False and out.reason == "ok"
        assert out.tool_results[0]["status"] == "timeout"
        assert out.tool_results[1]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_no_universal_deadline_by_default(self, monkeypatch):
        """Заводской fuse = 0: длинная цепочка не обрывается временем."""
        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                            0.0)
        answers = [
            _round(f"r{r}", [("query_chat_memory", {"query": f"q{r}"})])
            for r in range(6)] + [_text("длинный финал")]
        out = await chat_with_tools(FakeLLM(answers), MESSAGES, tools=TOOLS,
                                    router=FakeRouter(), ctx=MagicMock(),
                                    chat_id=CHAT_ID)
        assert out == "длинный финал"
        assert out.degraded is False
        assert len(out.tool_results) == 6

    @pytest.mark.asyncio
    async def test_model_final_answer_completes_loop(self):
        llm = FakeLLM([
            _round("r0", [("query_chat_memory", {"query": "a"})]),
            _text("достаточно данных")])
        router = FakeRouter({"query_chat_memory": "факт"})
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=MagicMock(), chat_id=CHAT_ID)
        assert out == "достаточно данных"
        assert len(router.calls) == 1
        assert out.degraded is False and out.reason == "ok"

    def test_plan_not_truncated(self):
        plan = [{"step_id": f"s{i}", "tool": "execute_web_search",
                 "arguments": {"query": str(i)}} for i in range(9)]
        assert len(normalize_tool_plan(plan)) == 9
