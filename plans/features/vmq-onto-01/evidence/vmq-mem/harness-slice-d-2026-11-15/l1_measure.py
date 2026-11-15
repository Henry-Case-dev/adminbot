# -*- coding: utf-8 -*-
"""Read-only measurement of the REAL L1 plan for five Slice D queries.

Uses the production L1 system prompt and a minimal `build_l1_context` (query +
current question; no live bundle/window) and the configured LLM. Stores only
codes/enums and lengths — never prompt/query/response text.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

WORKTREE = os.environ.get("VMQ_CLONE") or (
    r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489"
    r"\vmq-slice-d-963e66a7a511-6602ef7e")
APP = r"C:\Code\Python\adminbot"
OUT = os.environ.get("PROBE_OUT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "l1-measure.json")

sys.path.insert(0, WORKTREE)
os.chdir(APP)

from config.settings import settings                    # noqa: E402
from services.chat_prompts import DIRECT_L1_PLANNER_SYSTEM_PROMPT  # noqa: E402
from services.direct_l1 import build_l1_context, parse_l1_plan  # noqa: E402
from services.llm_client import LLMClient               # noqa: E402

QUERIES = [
    ("A1", "напиши юмористический рассказ об основных шизах конфы"),
    ("A1P", "что за шизы были на конфе?"),
    ("P1", "что ты знаешь про Алину?"),
    ("P2", "что ты знаешь про Лёху?"),
    ("P3", "что ты знаешь про Васю?"),
]


async def main():
    llm = LLMClient(
        settings.LLM_BASE_URL, settings.LLM_API_KEY,
        settings.LLM_MODEL_NAME, settings.EMBEDDING_MODEL_NAME,
        embed_base_url=settings.EMBEDDING_BASE_URL,
        embed_api_key=settings.EMBEDDING_API_KEY)
    out = {"model": settings.LLM_MODEL_NAME or "",
           "base_url_present": bool(settings.LLM_BASE_URL),
           "key_present": bool(settings.LLM_API_KEY),
           "context": "minimal build_l1_context(query) — no live bundle",
           "rows": []}
    for key, query in QUERIES:
        entry = {"class": key}
        try:
            context_text = build_l1_context(query=query,
                                            current_question=query)
            messages = [
                {"role": "system",
                 "content": DIRECT_L1_PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": context_text},
            ]
            raw = await asyncio.wait_for(llm.generate(messages), 120)
            plan = parse_l1_plan(raw)
            entry["raw_len"] = len(str(raw or ""))
            if plan is None:
                entry["parsed"] = False
            else:
                entry.update({
                    "parsed": True,
                    "action": str(plan.action or ""),
                    "response_act": str(plan.response_act or ""),
                    "memory_scope": str(getattr(plan, "memory_scope",
                                                "") or ""),
                    "source": str(plan.source or ""),
                })
        except Exception as exc:                          # noqa: BLE001
            entry["error"] = type(exc).__name__
            entry["error_text"] = str(exc)[:200]
        out["rows"].append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("OUT", OUT, flush=True)
    os._exit(0)


try:
    asyncio.run(main())
except BaseException:                                     # noqa: BLE001
    import traceback
    traceback.print_exc()
    os._exit(2)
