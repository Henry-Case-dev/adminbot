"""SMART-EXECUTION-RELIABILITY-01 stage A/B RED->GREEN probe.

Запускается против произвольного снимка репозитория (base d20a7f73 или
candidate). Печатает JSON наблюдаемых значений — без утверждений, чтобы
один и тот же прогон работал на обеих версиях.
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))

from config.settings import Settings  # noqa: E402
from services import budget_gate, tool_loop, worker_settings  # noqa: E402
from services.llm_client import LLMChatResult, LLMToolCall  # noqa: E402

MESSAGES = [{"role": "user", "content": "q"}]
TOOLS = [{"type": "function"}]


class FakeLLM:
    def __init__(self, answers):
        self._answers = list(answers)
        self.all_messages = []

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kw):
        self.all_messages.append(copy.deepcopy(messages))
        return self._answers.pop(0)

    async def generate(self, messages, temperature=None, chat_id=None, **kw):
        return "plain"


class FakeRouter:
    def __init__(self):
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append(name)
        return "data"


def _round(prefix, count, query_prefix):
    return LLMChatResult(
        content=None,
        tool_calls=[LLMToolCall(id=f"{prefix}_{i}", name="execute_web_search",
                                arguments=json.dumps({"query":
                                                      f"{query_prefix}{i}"}))
                    for i in range(count)],
        finish_reason="tool_calls")


def _text(value):
    return LLMChatResult(content=value, tool_calls=None, finish_reason="stop")


async def run_chain(answers):
    llm = FakeLLM(answers)
    router = FakeRouter()
    out = await tool_loop.chat_with_tools(
        llm, MESSAGES, tools=TOOLS, router=router, ctx=object(), chat_id=-100)
    payloads = llm.all_messages
    per_round = [len([m for m in p if m["role"] == "tool"]) for p in payloads]
    return {
        "llm_calls": len(payloads),
        "tool_msgs_per_request": per_round,
        "router_calls": len(router.calls),
        "reason": getattr(out, "reason", None),
        "degraded": getattr(out, "degraded", None),
        "rounds_used": getattr(out, "rounds_used", None),
        "tool_results": len(getattr(out, "tool_results", ()) or ()),
        "text": str(out)[:60],
    }


async def scenario_multiround():
    # 5 раундов × 3 вызова = 15 (>4 раундов, >2/раунд, >6 суммарно)
    answers = [_round(f"r{r}", 3, f"q{r}") for r in range(5)] + [_text("финал")]
    return await run_chain(answers)


async def scenario_identical_repeats():
    answers = [_round(f"r{r}", 1, "same") for r in range(6)]
    return await run_chain(answers)


def scenario_constants():
    names = ["TOOL_MAX_ROUNDS", "_TOOL_CALLS_PER_ROUND_MAX",
             "TOOL_MAX_TOTAL_CALLS", "_TOOL_MAX_SAME_CALL",
             "TOOL_CHAIN_MAX_METERED_CALLS", "PLAN_MAX_STEPS"]
    present = [n for n in names if hasattr(tool_loop, n)]
    fuse = (tool_loop._chain_timeout_seconds()
            if hasattr(tool_loop, "_chain_timeout_seconds") else None)
    return {"legacy_constants_present": present,
            "chain_fuse_seconds": fuse,
            "settings_defaults": {
                "MCA_TOOL_MAX_TOTAL_CALLS":
                    getattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", None),
                "MCA_TOOL_MAX_METERED_CALLS":
                    getattr(Settings, "MCA_TOOL_MAX_METERED_CALLS", None),
                "MCA_TOOL_MAX_SAME_CALL":
                    getattr(Settings, "MCA_TOOL_MAX_SAME_CALL", None),
                "MCA_TOOL_CHAIN_TIMEOUT_SECONDS":
                    getattr(Settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS", None),
            }}


def scenario_plan_truncation():
    plan = [{"step_id": f"s{i}", "tool": "execute_web_search",
             "arguments": {"query": str(i)}} for i in range(9)]
    return {"normalized_steps": len(tool_loop.normalize_tool_plan(plan))}


async def scenario_budgets_read_error():
    reset = getattr(budget_gate, "reset_cache", None)
    if callable(reset):
        reset()

    async def _boom(key, *, chat_id=None, default=None):
        raise RuntimeError("pg down")

    original = worker_settings.resolve_setting_with_source
    worker_settings.resolve_setting_with_source = _boom
    try:
        value = await budget_gate.budgets_enabled(-100)
        detail = None
        resolver = getattr(budget_gate, "resolve_budgets", None)
        if callable(resolver):
            state = await resolver(-100)
            detail = {"enabled": state.enabled, "source": state.source,
                      "known": state.known, "stale": state.stale}
    finally:
        worker_settings.resolve_setting_with_source = original
    return {"budgets_enabled_on_read_error": value, "state": detail}


async def scenario_budget_off_policy():
    """budgets OFF (предикат False) + MCA_TOOL_MAX_TOTAL_CALLS=2."""
    original_setting = getattr(Settings, "MCA_TOOL_MAX_TOTAL_CALLS", None)
    Settings.MCA_TOOL_MAX_TOTAL_CALLS = 2
    original_predicate = budget_gate.budgets_enabled

    async def _off(chat_id=None):
        return False

    budget_gate.budgets_enabled = _off
    try:
        answers = [_round("r0", 3, "x"), _text("финал")]
        result = await run_chain(answers)
    finally:
        budget_gate.budgets_enabled = original_predicate
        if original_setting is not None:
            Settings.MCA_TOOL_MAX_TOTAL_CALLS = original_setting
    return result


async def main():
    report = {
        "root": str(ROOT),
        "multiround": await scenario_multiround(),
        "identical_repeats": await scenario_identical_repeats(),
        "constants": scenario_constants(),
        "plan": scenario_plan_truncation(),
        "budgets_read_error": await scenario_budgets_read_error(),
        "budget_off_policy": await scenario_budget_off_policy(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main())
