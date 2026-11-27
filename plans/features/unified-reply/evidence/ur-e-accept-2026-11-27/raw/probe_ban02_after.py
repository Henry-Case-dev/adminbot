"""UR-BAN-02 — runtime probe AFTER the fix (read-only, no DB, no network).

Тот же сценарий, что и RED-проба: fake-LLM каждый раунд просит новый запрос,
fake-router отдаёт новый непустой материал. Теперь цепочка обязана
остановиться на физическом анти-цикле шагов и сохранить материал.

Запуск: py plans/features/unified-reply/evidence/ur-e-accept-2026-11-27/raw/probe_ban02_after.py
"""
import asyncio
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = _HERE
while not os.path.exists(os.path.join(REPO, "services", "direct_execution.py")):
    parent = os.path.dirname(REPO)
    if parent == REPO:
        raise SystemExit("repo root not found")
    REPO = parent
sys.path.insert(0, REPO)
os.chdir(REPO)

import services.direct_execution as dx                      # noqa: E402
import tests.test_unified_reply_ur_b_search_first as T      # noqa: E402


class Router:
    def __init__(self):
        self.dispatched = []

    async def dispatch(self, name, arguments, ctx):
        self.dispatched.append(arguments.get("query"))
        n = len(self.dispatched)
        return "Результаты\nНовый факт %d\nhttps://example.com/%d" % (n, n)


class LLM:
    """Без предохранителя: если предела нет, проба не завершится сама."""

    def __init__(self, safety=200):
        self.calls = 0
        self.safety = safety

    async def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls > self.safety:
            raise RuntimeError("PROBE SAFETY: %d calls without stop" % self.safety)
        return json.dumps({"action": "call_tool",
                           "tool": "execute_web_search",
                           "arguments": {"query": "q%d" % self.calls},
                           "reason": "more"})


async def main():
    router, llm = Router(), LLM()
    result = await dx.run_adaptive_chain(
        llm=llm, router=router, ctx=None,
        plan=T._plan(execution_mode="adaptive_tool_chain"),
        query="q", tool_schemas=T._schemas("execute_web_search"),
        chat_id=T.CHAT_ID, correlation_id="corr-ban02-after")
    print("llm_calls:", llm.calls)
    print("dispatched_steps:", len(router.dispatched))
    print("stop_reason:", result.chain_meta["reason"])
    print("meta_max_steps:", result.chain_meta["max_steps"])
    print("meta_steps:", result.chain_meta["steps"])
    print("window_tokens:", result.chain_meta["window_tokens"])
    print("evidence_sources:", len(result.evidence_sources))
    print("material_kept:", all(s.content for s in result.evidence_sources))
    print("hard_max_constant:", dx.ORCHESTRATOR_STEPS_HARD_MAX)
    print("factory_max_steps_policy:", dx.orchestrator_max_steps())
    print("factory_fuse_seconds:", dx.orchestrator_max_time_seconds())
    print("BOUNDED" if llm.calls <= dx.ORCHESTRATOR_STEPS_HARD_MAX
          else "UNBOUNDED")


asyncio.run(main())
