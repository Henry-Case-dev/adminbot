"""MCA-11 `mca-11-tools-costs` — focused блок D (T-4956/T-4957).

Покрытие: AMEND реестра `tools.chain` v1→v2 (стадии route/execute/deliver/
account, widget-ID — контракт mca-17c), стадийные события через единственный
store `mca_events` (notable-only), reason_code из единого словаря, честный
`not_run`/`disabled`, K4 OFF-паритет и R17-скан.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings, settings
from services import image_generation as ig
from services import mca_events, mca_gates
from services import mca_process_registry as reg
from services import tool_result
from services.llm_client import LLMChatResult, LLMToolCall
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, ToolDeps, ToolRouter

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = [{"role": "user", "content": "вопрос"}]
TOOLS = [{"type": "function"}]


class FakeLLM:
    def __init__(self, answers):
        self._answers = list(answers)

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        if not self._answers:
            raise AssertionError("не хватило запланированных ответов")
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        return "plain"


class FakeRouter:
    def __init__(self, outputs=None, *, fn=None):
        self._outputs = dict(outputs or {})
        self._fn = fn

    async def dispatch(self, name, arguments, ctx):
        if self._fn is not None:
            return await self._fn(name, arguments, ctx)
        return self._outputs.get(name, f"данные:{name}")


def _tc(call_id, name, args=None):
    return LLMChatResult(content=None,
                         tool_calls=[LLMToolCall(id=call_id, name=name,
                                                 arguments=json.dumps(
                                                     args or {}))],
                         finish_reason="tool_calls")


def _tc2(prefix, name_args):
    return LLMChatResult(
        content=None,
        tool_calls=[LLMToolCall(id=f"{prefix}_{i}", name=n,
                                arguments=json.dumps(a))
                    for i, (n, a) in enumerate(name_args)],
        finish_reason="tool_calls")


def _text(text):
    return LLMChatResult(content=text, tool_calls=None, finish_reason="stop")


async def _run(llm, router):
    return await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                 ctx=ToolContext(-100, "corr-1"),
                                 chat_id=-100, correlation_id="corr-1")


@pytest.fixture
def events(monkeypatch):
    """Перехват единственной точки эмиссии `mca_events.emit_mca_event`."""
    captured: list[dict] = []

    def fake_emit(event_name, *, outcome, level="INFO", **fields):
        event = {"event_name": event_name, "outcome": outcome,
                 "level": level, **fields}
        captured.append(event)
        return event

    monkeypatch.setattr(mca_events, "emit_mca_event", fake_emit)
    return captured


# ── T-4956: реестр v2 ───────────────────────────────────────────────────────

class TestRegistryV2:
    def test_tools_chain_v2_contract(self):
        p = reg.get_process("tools.chain")
        assert p.version == "2"
        assert p.stages == ("route", "execute", "deliver", "account")
        assert p.stages_to_events == {"execute": "tool_call",
                                      "deliver": "tool_delivery",
                                      "account": "tool_accounting"}
        assert p.instrumentation == ("execute", "deliver", "account")
        assert p.enabled_gate == "MCA_TOOL_CHAIN_STAGES_ENABLED"
        assert p.widget_id == "Tool chain"          # контракт mca-17c
        assert p.event_names == ("tool_call", "tool_delivery", "tool_accounting")
        assert "MCA_TOOL_RESULT_ENABLED" in p.settings_ref
        assert "MCA_COST_ACCOUNTING_ENABLED" in p.settings_ref

    def test_event_names_literal_in_code(self):
        """F1-конвенция mca-17a: имена эмитятся литералами `emit_mca_event`."""
        text = (ROOT / "services/tool_result.py").read_text(encoding="utf-8")
        for name in ("tool_call", "tool_delivery", "tool_accounting"):
            assert f'emit_mca_event("{name}"' in text, name

    def test_runtime_status_honest(self, monkeypatch):
        p = reg.get_process("tools.chain")
        assert reg.runtime_status(
            p, event_names_present=frozenset({"tool_call"})) == \
            reg.STATUS_IMPLEMENTED
        assert reg.runtime_status(
            p, event_names_present=frozenset({"UNRELATED"})) == \
            reg.STATUS_NOT_RUN
        monkeypatch.setattr(mca_gates, "tool_chain_stages_enabled",
                            lambda: False)
        assert reg.runtime_status(p) == reg.STATUS_DISABLED


# ── T-4956: notable-события стадий ──────────────────────────────────────────

class TestStageEvents:
    @pytest.mark.asyncio
    async def test_success_call_no_noise(self, events):
        await _run(FakeLLM([_tc("c1", "query_chat_memory", {"query": "x"}),
                            _text("финал")]),
                   FakeRouter({"query_chat_memory": "данные"}))
        assert events == []

    @pytest.mark.asyncio
    async def test_error_terminal_emits_tool_call(self, events):
        await _run(FakeLLM([_tc("c1", "execute_web_search", {"query": "x"}),
                            _text("финал")]),
                   FakeRouter({"execute_web_search":
                               "ОШИБКА execute_web_search: timeout"}))
        calls = [e for e in events if e["event_name"] == "tool_call"]
        assert len(calls) == 1
        ev = calls[0]
        assert ev["outcome"] == "failed"
        assert ev["component"] == "tools"
        assert ev["stage"] == "execute"
        assert ev["status"] == "timeout"
        assert ev["reason_code"] == "timeout"
        assert ev["chat_id"] == -100
        assert ev["trace_id"] == "corr-1"
        assert ev["entity_ids"]["tool"] == "execute_web_search"
        assert len(ev["entity_ids"]["args_fingerprint"]) == 16

    @pytest.mark.asyncio
    async def test_denied_terminal_emits_skipped(self, events):
        await _run(FakeLLM([_tc("c1", "dig_into_lore", {"query": "x"}),
                            _text("финал")]),
                   FakeRouter({"dig_into_lore": "Инструмент dig_into_lore "
                                                "отключен."}))
        ev = [e for e in events if e["event_name"] == "tool_call"][0]
        assert ev["outcome"] == "skipped" and ev["status"] == "denied"
        assert ev["reason_code"] == "disabled"      # код из единого словаря

    @pytest.mark.asyncio
    async def test_delivery_unknown_and_account_unknown(self, events,
                                                        monkeypatch):
        monkeypatch.setattr(ig, "unified_image_request_enabled",
                            lambda: False)
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(ig, "generate_and_send",
                            AsyncMock(return_value=ig.GenerationResult(
                                ok=False, reason="send_failed")))
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        await _run(FakeLLM([_tc("c1", "generate_image", {"prompt": "кот"}),
                            _text("финал")]), router)
        deliver = [e for e in events if e["event_name"] == "tool_delivery"]
        account = [e for e in events if e["event_name"] == "tool_accounting"]
        assert len(deliver) == 1 and len(account) == 1
        assert deliver[0]["stage"] == "deliver"
        assert deliver[0]["outcome"] == "pending_external"
        assert deliver[0]["reason_code"] == "delivery_unknown"
        assert account[0]["stage"] == "account"
        assert account[0]["reason_code"] == "cost_unknown"
        usage = account[0]["usage_json"]
        assert usage["cost_usd"] is None            # unknown ≠ 0
        assert usage["price_known"] is False
        assert usage["price_version"] == "unknown"
        assert usage["currency"] == "USD"
        assert usage["source"] == "image"
        assert account[0]["status"] == "delivery_unknown"
        # execute-событие для delivery_unknown не дублируется.
        assert not [e for e in events if e["event_name"] == "tool_call"]

    @pytest.mark.asyncio
    async def test_chain_limit_reason_codes_mapped(self, events, monkeypatch):
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", 3)
        answers = [_tc2(f"r{r}", [("query_chat_memory", {"query": f"q{r}a"}),
                                  ("query_chat_memory", {"query": f"q{r}b"})])
                   for r in range(4)]
        await _run(FakeLLM(answers), FakeRouter())
        denied = [e for e in events
                  if e["event_name"] == "tool_call"
                  and e["status"] == "denied"]
        assert denied and denied[-1]["reason_code"] == "tool_step_limit"

    @pytest.mark.asyncio
    async def test_chain_timeout_maps_deadline_exceeded(self, events,
                                                        monkeypatch):
        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", -1.0)
        await _run(FakeLLM([_tc("c1", "execute_web_search", {"query": "x"}),
                            _text("финал")]), FakeRouter())
        ev = [e for e in events if e["event_name"] == "tool_call"][0]
        assert ev["reason_code"] == "deadline_exceeded"
        assert ev["status"] == "denied"

    @pytest.mark.asyncio
    async def test_chain_cost_limit_maps_financial(self, events, monkeypatch):
        monkeypatch.setattr(Settings, "MCA_TOOL_MAX_METERED_CALLS", 1)
        await _run(FakeLLM([_tc2("r0", [
            ("execute_web_search", {"query": "a"}),
            ("execute_web_search", {"query": "b"})]), _text("финал")]),
            FakeRouter())
        ev = [e for e in events if e["event_name"] == "tool_call"][0]
        assert ev["reason_code"] == "financial_limit_reached"

    @pytest.mark.asyncio
    async def test_k4_off_no_stage_events(self, events, monkeypatch):
        monkeypatch.setattr(Settings, "MCA_TOOL_CHAIN_STAGES_ENABLED", False)
        assert tool_result.chain_stages_enabled() is False
        await _run(FakeLLM([_tc("c1", "execute_web_search", {"query": "x"}),
                            _text("финал")]),
                   FakeRouter({"execute_web_search":
                               "ОШИБКА execute_web_search: timeout"}))
        assert events == []


# ── T-4957: R17-скан ────────────────────────────────────────────────────────

class TestR17:
    @pytest.mark.asyncio
    async def test_events_have_no_raw_text_or_args(self, events):
        secret = "SECRET_TEXT_https://leak.example/xyz"
        await _run(FakeLLM([_tc("c1", "fetch_article", {"url": secret}),
                            _text("финал")]),
                   FakeRouter({"fetch_article": f"ОШИБКА: {secret}"}))
        blob = json.dumps(events, ensure_ascii=False)
        assert secret not in blob
        for ev in events:
            assert set(ev["entity_ids"]) == {"tool", "args_fingerprint"}
            for forbidden in ("args", "output", "content", "markdown", "url"):
                assert forbidden not in ev

    @pytest.mark.asyncio
    async def test_account_usage_json_only_numbers_codes(self, events,
                                                         monkeypatch):
        monkeypatch.setattr(ig, "unified_image_request_enabled",
                            lambda: False)
        monkeypatch.setattr(ig, "resolve_module_enabled",
                            AsyncMock(return_value=True))
        monkeypatch.setattr(ig, "generate_and_send",
                            AsyncMock(return_value=ig.GenerationResult(
                                ok=False, reason="send_failed")))
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock()))
        await _run(FakeLLM([_tc("c1", "generate_image", {"prompt": "SECRET"}),
                            _text("финал")]), router)
        account = [e for e in events if e["event_name"] == "tool_accounting"]
        blob = json.dumps(account, ensure_ascii=False)
        assert "SECRET" not in blob
        usage = account[0]["usage_json"]
        assert set(usage) == {"input_tokens", "output_tokens", "cached_tokens",
                              "tokens_estimated", "cost_usd", "price_known",
                              "currency", "price_version", "source"}
