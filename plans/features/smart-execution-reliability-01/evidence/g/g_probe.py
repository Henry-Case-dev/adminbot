"""RED/GREEN probe for S7-FINALIZE (§G) — run with cwd = candidate checkout.

Self-contained: no pytest, no repo test fixtures. Prints one JSON line per
scenario with observable outcomes (text, degraded, reason, finalize_mode,
LLM calls, router calls, envelope statuses).

Usage:
  python g_red_probe.py
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.getcwd())

from config.settings import Settings
from services import budget_gate
from services.llm_client import LLMChatResult, LLMError, LLMToolCall
from services.tool_loop import TOOL_LOOP_FALLBACK_PHRASE, chat_with_tools

MESSAGES = [{"role": "user", "content": "почему упал деплой?"}]
TOOLS = [{"type": "function", "function": {"name": "execute_web_search"}},
         {"type": "function", "function": {"name": "fetch_article"}}]
CHAT_ID = -1001234567890


class FakeLLM:
    def __init__(self, answers, finalize_text="FINALIZE_OK", finalize_error=None):
        self.answers = list(answers)
        self.finalize_text = finalize_text
        self.finalize_error = finalize_error
        self.chat_calls = 0
        self.finalize_calls = 0

    async def generate_chat(self, messages, *, tools=None, **kwargs):
        self.chat_calls += 1
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, messages, **kwargs):
        self.finalize_calls += 1
        if self.finalize_error is not None:
            raise self.finalize_error
        return self.finalize_text


class FakeRouter:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments or {})))
        return await self.fn(name, arguments, ctx)


def ctx():
    return SimpleNamespace(tool_results=[])


def tool_round(prefix, calls):
    return LLMChatResult(
        content=None,
        tool_calls=[LLMToolCall(id=f"{prefix}_{i}", name=n,
                                arguments=json.dumps(a, ensure_ascii=False))
                    for i, (n, a) in enumerate(calls)],
        finish_reason="tool_calls")


def text_round(value):
    return LLMChatResult(content=value, tool_calls=None, finish_reason="stop")


def summarize(out, llm, router=None):
    text = str(out)
    return {
        "text_prefix": text[:160],
        "is_fallback_phrase": text == TOOL_LOOP_FALLBACK_PHRASE,
        "degraded": getattr(out, "degraded", None),
        "reason": getattr(out, "reason", None),
        "finalize_mode": getattr(out, "finalize_mode", "<attr-missing>"),
        "finalize_calls": llm.finalize_calls,
        "chat_calls": llm.chat_calls,
        "router_calls": len(router.calls) if router else None,
        "statuses": [e.get("status") for e in
                     (getattr(out, "tool_results", None) or [])],
        "tool_results": len(getattr(out, "tool_results", None) or []),
    }


async def scenario_stop_with_evidence():
    llm = FakeLLM([tool_round("r0", [("execute_web_search", {"query": "a"})]),
                   LLMError("upstream 500")])
    router = FakeRouter(lambda n, a, c: asyncio.sleep(0, "данные поиска"))
    out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                ctx=ctx(), chat_id=CHAT_ID)
    return summarize(out, llm, router)


async def scenario_final_llm_down():
    llm = FakeLLM([tool_round("r0", [("execute_web_search", {"query": "a"})]),
                   LLMError("upstream 500")], finalize_error=LLMError("writer down"))
    router = FakeRouter(lambda n, a, c: asyncio.sleep(0, "данные поиска"))
    out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                ctx=ctx(), chat_id=CHAT_ID)
    return summarize(out, llm, router)


async def scenario_no_progress():
    same = tool_round("r0", [("execute_web_search", {"query": "a"})])
    llm = FakeLLM([same, same, same], finalize_text="PLAIN")
    router = FakeRouter(lambda n, a, c: asyncio.sleep(0, "данные поиска"))
    out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                ctx=ctx(), chat_id=CHAT_ID)
    return summarize(out, llm, router)


async def scenario_limit_exhausted():
    async def _budgets(chat_id=None):
        return True

    old = budget_gate.budgets_enabled
    old_max = Settings.MCA_TOOL_MAX_TOTAL_CALLS
    budget_gate.budgets_enabled = _budgets
    Settings.MCA_TOOL_MAX_TOTAL_CALLS = 1
    try:
        llm = FakeLLM([tool_round("r0", [("execute_web_search", {"query": "a"}),
                                         ("execute_web_search", {"query": "b"})])],
                      finalize_text="LIMIT_FINAL")
        router = FakeRouter(lambda n, a, c: asyncio.sleep(0, "данные поиска"))
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ctx(), chat_id=CHAT_ID)
        return summarize(out, llm, router)
    finally:
        budget_gate.budgets_enabled = old
        Settings.MCA_TOOL_MAX_TOTAL_CALLS = old_max


def error_payload(**fields):
    payload = {"status": "error"}
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False)


async def scenario_nonretryable_same_host():
    calls = []

    async def fn(name, arguments, ctx_):
        calls.append(arguments)
        return error_payload(error="destination_blocked",
                             reason="destination_blocked",
                             retryable=False, host="blocked.example")

    llm = FakeLLM([
        tool_round("r0", [("fetch_article",
                           {"url": "https://blocked.example/one"})]),
        tool_round("r1", [("fetch_article",
                           {"url": "https://blocked.example/two"})]),
        text_round("финал")])
    router = FakeRouter(fn)
    out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                ctx=ctx(), chat_id=CHAT_ID)
    result = summarize(out, llm, router)
    result["dispatched_urls"] = [c.get("url") for c in calls]
    return result


async def scenario_resource_failure_host_alternative():
    calls = []

    async def fn(name, arguments, ctx_):
        url = str((arguments or {}).get("url") or "")
        calls.append(url)
        if url.endswith("/bad"):
            return error_payload(error="extract_failed",
                                 reason="source_unavailable",
                                 retryable=False, host="news.example")
        return "альтернативная статья доступна"

    llm = FakeLLM([
        tool_round("r0", [("fetch_article",
                           {"url": "https://news.example/bad"})]),
        tool_round("r1", [("fetch_article",
                           {"url": "https://news.example/good"})]),
        text_round("финал по альтернативе")])
    router = FakeRouter(fn)
    out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                ctx=ctx(), chat_id=CHAT_ID)
    result = summarize(out, llm, router)
    result["dispatched_urls"] = calls
    return result


async def scenario_retryable_other_query():
    calls = []

    async def fn(name, arguments, ctx_):
        calls.append(arguments)
        if arguments.get("query") == "a":
            return error_payload(error="provider_unavailable", retryable=True)
        return "второй запрос дал данные"

    llm = FakeLLM([
        tool_round("r0", [("execute_web_search", {"query": "a"})]),
        tool_round("r1", [("execute_web_search", {"query": "b"})]),
        text_round("финал по второму запросу")])
    router = FakeRouter(fn)
    out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                ctx=ctx(), chat_id=CHAT_ID)
    result = summarize(out, llm, router)
    result["dispatched_queries"] = [c.get("query") for c in calls]
    return result


async def scenario_single_provider_route():
    calls = []

    async def fn(name, arguments, ctx_):
        calls.append(arguments)
        return error_payload(error="auth_failed", retryable=False,
                             provider="tavily")

    llm = FakeLLM([
        tool_round("r0", [("execute_web_search", {"query": "a"})]),
        tool_round("r1", [("execute_web_search", {"query": "b"})]),
        text_round("финал")])
    router = FakeRouter(fn)
    out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                ctx=ctx(), chat_id=CHAT_ID)
    result = summarize(out, llm, router)
    result["dispatched_queries"] = [c.get("query") for c in calls]
    return result


async def scenario_verified_url_route():
    calls = []

    async def fn(name, arguments, ctx_):
        calls.append(arguments)
        return error_payload(
            error="auth_failed", retryable=False,
            verified_url="https://github.com/o/r/blob/main/x.py")

    llm = FakeLLM([
        tool_round("r0", [("read_source_code",
                           {"url": "https://github.com/o/r/blob/main/x.py"})]),
        tool_round("r1", [("read_source_code",
                           {"url": "https://github.com/o/r/blob/main/y.py"})]),
        text_round("финал")])
    router = FakeRouter(fn)
    out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                ctx=ctx(), chat_id=CHAT_ID)
    result = summarize(out, llm, router)
    result["dispatched_urls"] = [c.get("url") for c in calls]
    return result


async def scenario_plan_policy_denial_finalize_down():
    async def _budgets(chat_id=None):
        return True

    old = budget_gate.budgets_enabled
    old_max = Settings.MCA_TOOL_MAX_TOTAL_CALLS
    budget_gate.budgets_enabled = _budgets
    Settings.MCA_TOOL_MAX_TOTAL_CALLS = 1
    try:
        llm = FakeLLM([LLMError("research broke")],
                      finalize_error=LLMError("writer down"))
        router = FakeRouter(
            lambda n, a, c: asyncio.sleep(0, "статья A"
                                          if n == "fetch_article"
                                          else "полезные данные поиска"))
        plan = [
            {"step_id": "search", "tool": "execute_web_search",
             "arguments": {"query": "x"}},
            {"step_id": "read", "tool": "fetch_article",
             "arguments": {"url": "https://a.example/x"}},
        ]
        out = await chat_with_tools(llm, MESSAGES, tools=TOOLS, router=router,
                                    ctx=ctx(), chat_id=CHAT_ID, tool_plan=plan)
        result = summarize(out, llm, router)
        result["has_policy_denial"] = "- fetch_article: chain_call_limit" in str(out)
        result["has_usable_data"] = "полезные данные поиска" in str(out)
        return result
    finally:
        budget_gate.budgets_enabled = old
        Settings.MCA_TOOL_MAX_TOTAL_CALLS = old_max


async def main():
    scenarios = (
        ("stop_with_evidence", scenario_stop_with_evidence),
        ("final_llm_down", scenario_final_llm_down),
        ("no_progress", scenario_no_progress),
        ("limit_exhausted", scenario_limit_exhausted),
        ("nonretryable_same_host", scenario_nonretryable_same_host),
        ("resource_failure_host_alternative",
         scenario_resource_failure_host_alternative),
        ("retryable_other_query", scenario_retryable_other_query),
        ("single_provider_route", scenario_single_provider_route),
        ("verified_url_route", scenario_verified_url_route),
        ("plan_policy_denial_finalize_down",
         scenario_plan_policy_denial_finalize_down),
    )
    for name, fn in scenarios:
        try:
            payload = await fn()
        except Exception as exc:
            payload = {"exception": f"{type(exc).__name__}: {exc}"}
        print(json.dumps({"scenario": name, **payload}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
