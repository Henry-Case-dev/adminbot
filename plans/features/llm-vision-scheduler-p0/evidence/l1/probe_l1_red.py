# -*- coding: utf-8 -*-
"""P0 L1 RED/GREEN probe — факты о планировщике на конкретном коде.

Запускается из корня checkout'а: `.venv\\Scripts\\python.exe <этот файл>`.
Печатает один JSON-объект фактов (без секретов и текстов чата). Один и тот же
скрипт используется и на базе `ea9f760f` (RED), и на кандидате (GREEN).

Проверяемые факты:
  1. наличие capability-API / единого нормализатора ответа;
  2. код-дефолты 15 s / 512 tokens;
  3. перенос main-ключа на чужой endpoint dedicated-слота;
  4. 1M-оценка, выданная за `model_window`;
  5. поведение на инциденте 09:27:43Z (пустой content + finish_reason=length):
     число реальных попыток и отправленный output-бюджет.
"""
from __future__ import annotations

import asyncio
import json
import sys

import services.llm_client as lc
import services.model_capacity as mc
from services import direct_l1 as l1
from services.llm_client import LLMBadResponseError

FACTS: dict = {}


def _safe(name, fn):
    try:
        FACTS[name] = fn()
    except Exception as exc:      # честная фиксация отсутствия API/поломки
        FACTS[name] = f"{type(exc).__name__}: {str(exc)[:120]}"


def _capability_api():
    caps = {}
    if hasattr(mc, "catalog_capability_fields"):
        item = {"id": "x", "context_length": 131072,
                "max_output_tokens": 8192, "capabilities": ["reasoning"]}
        caps = mc.catalog_capability_fields(item)
    return caps


def _normalizer_api():
    if not hasattr(lc, "classify_chat_response"):
        return "absent"
    out = {}
    for name, payload in {
        "reasoning_only": {"choices": [{"message": {
            "content": None, "reasoning_content": "x"}}]},
        "length_empty": {"choices": [{"message": {"content": ""},
                                      "finish_reason": "length"}]},
        "content_parts": {"choices": [{"message": {"content": [
            {"type": "text", "text": "a"}]}}]},
    }.items():
        classified = lc.classify_chat_response(payload)
        out[name] = {"kind": classified.kind,
                     "content_is_answer": classified.content is not None}
    return out


def _l1_defaults():
    return {"timeout_seconds": l1.l1_timeout_seconds(),
            "max_output_tokens": l1.l1_max_output_tokens()}


def _dedicated_key():
    hot = {
        "models.llm_base_url": "https://main.example/v1",
        "models.llm_model_name": "main-model",
        "keys.llm_api_key": "sk-main",
        "models.direct_l1_base_url": "https://other.example/v1",
        "models.direct_l1_model_name": "l1-model",
        "keys.direct_l1_api_key": "",
    }
    slot = l1.resolve_l1_model(hot_get=lambda k, d=None: hot.get(k, d))
    return {"dedicated": slot.dedicated,
            "key_empty": slot.api_key == "",
            "key_equals_main": slot.api_key == "sk-main",
            "base_url": slot.base_url}


def _budget_api():
    if not hasattr(l1, "l1_plan_output_budget"):
        return "absent"
    class _Cap:
        supports_reasoning = True
        max_output = None
    return l1.l1_plan_output_budget(_Cap())


def _route_api():
    if not hasattr(l1, "resolve_l1_route"):
        return "absent"
    slot = l1.L1ModelSlot(base_url="https://nano-gpt.com/api/v1",
                          model="z-ai/glm-5.3-uncensored", api_key="k")
    route = asyncio.run(l1.resolve_l1_route(slot, None))
    return {"timeout": route.timeout_seconds,
            "deadline": route.deadline_seconds,
            "output_field": route.output_field,
            "max_output": route.max_output_tokens,
            "output_source": route.output_source,
            "window_estimated": route.window_estimated}


class _ScriptLLM:
    """Двойник: первый вызов падает как инцидент, дальше — валидный план."""

    def __init__(self, plan_json):
        self.plan_json = plan_json
        self.calls = []
        self._timeout = 180.0
        self._budget = 360.0
        self._base_url = "https://primary.example/v1"
        self._chat_model = "main-model"
        self._fallback_active = False

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kw):
        self.calls.append({"step": step, "kwargs": dict(kw)})
        if step == "l1_planner":
            if len([c for c in self.calls if c["step"] == "l1_planner"]) == 1:
                exc = LLMBadResponseError("chat/completions: empty content")
                # На базе этих атрибутов нет — матрица исхода их и не читает.
                exc.response_kind = lc.RESPONSE_KIND_TRUNCATED_REASONING \
                    if hasattr(lc, "RESPONSE_KIND_TRUNCATED_REASONING") else ""
                exc.llm_finish_reason = "length"
                raise exc
            return self.plan_json
        return "готовый ответ"


class _MP:
    def __init__(self):
        self.undo = []

    def setattr(self, obj, name, value):
        self.undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def delattr(self, obj, name):
        self.undo.append((obj, name, getattr(obj, name)))
        delattr(obj, name)

    def revert(self):
        for obj, name, value in reversed(self.undo):
            setattr(obj, name, value)


async def _incident():
    from tests.test_asap7_direct_l1 import _drive, _plan_json
    from tests.test_direct_chat import CHAT_ID
    mp = _MP()
    try:
        llm = _ScriptLLM(_plan_json(extent="micro"))
        svc, react, bot, msg, user = _drive(mp, "а этот?", llm=llm)
        await svc.handle(bot, msg, user)
        calls = [c for c in llm.calls if c["step"] == "l1_planner"]
        diag = l1.get_l1_diagnostics(CHAT_ID) or {}
        return {
            "planner_calls": len(calls),
            "sent_max_output_tokens": [c["kwargs"].get("max_output_tokens")
                                       for c in calls],
            "failure_mode": diag.get("l1_failure_mode"),
            "finish_reason": diag.get("l1_finish_reason"),
        }
    finally:
        mp.revert()


async def _budget_source():
    async def _no_catalog(url, *, headers=None):
        return None
    original = mc._http_get_json
    mc._http_get_json = _no_catalog
    try:
        _budget, meta = await l1.resolve_l1_context_budget(
            base_url="https://example.invalid/v1", model="unknown-model-xyz")
        return {"source": meta.get("source"),
                "capacity_source": meta.get("capacity_source"),
                "context_window": meta.get("context_window"),
                "window_estimated": meta.get("window_estimated"),
                "model_window_as_verified": meta.get("source") == "model_window"}
    finally:
        mc._http_get_json = original


def main() -> int:
    _safe("capability_api", _capability_api)
    _safe("normalizer_api", _normalizer_api)
    _safe("l1_defaults", _l1_defaults)
    _safe("dedicated_key", _dedicated_key)
    _safe("output_budget_api", _budget_api)
    _safe("route_api", _route_api)
    _safe("context_budget_source", lambda: asyncio.run(_budget_source()))
    _safe("incident_09_27", lambda: asyncio.run(_incident()))
    print(json.dumps(FACTS, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
