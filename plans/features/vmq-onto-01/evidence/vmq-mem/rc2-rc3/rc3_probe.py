"""VMQ-MEM RC3 snapshot probe (read-only): explicit-year base filter/slots.

Uses the real MemoryManager FTS fallback (vector leg unavailable in this
environment), DirectChatService._rag_unified_rows, read-only snapshot.
Writes IDs/years/counters only, no fact or message texts.
"""
import asyncio
import datetime
import json
import os
import sys
import time

import aiosqlite

WT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", ".."))
SNAP = r"C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\snapshot-2.58.225.db"
OUT = os.path.join(os.path.dirname(__file__), "rc3-snapshot.json")
CHAT = -1002661910336
os.chdir(WT)
sys.path.insert(0, WT)

from services import hot_config as hot  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.direct_chat_service import DirectChatService  # noqa: E402
from services.summary_memory import MemoryManager  # noqa: E402


class StubLLM:
    async def generate(self, *a, **k):
        raise RuntimeError("no_llm")

    async def embed(self, *a, **k):
        raise RuntimeError("no_embed")


async def _noop(*a, **k):
    return None


def _year(row):
    try:
        ts = (row.get("message_timestamp") or row.get("created_at")
              or row.get("rag_ts"))
        return datetime.datetime.fromtimestamp(
            int(ts), datetime.timezone.utc).year
    except Exception:
        return None


def _summary(rows, stats):
    years: dict = {}
    for row in rows or ():
        year = _year(row)
        years[str(year)] = years.get(str(year), 0) + 1
    return {
        "rows": len(rows or ()),
        "years": dict(sorted(years.items())),
        "ids": [row.get("id") for row in rows or ()],
        "stats": {
            key: stats.get(key) for key in (
                "breadth_reason", "breadth_cap", "base_out_of_year_dropped",
                "base_out_of_year_candidates", "base_year_fallback",
                "period_message_candidates",
                "period_message_candidates_reason", "selection_kept",
                "breadth_used")
        },
    }


async def main():
    ds = DatabaseService(SNAP)
    uri = "file:" + SNAP.replace("\\", "/") + "?mode=ro&immutable=1"
    ds.db = await aiosqlite.connect(uri, uri=True)
    ds.db.row_factory = aiosqlite.Row
    await ds.db.execute("PRAGMA query_only=ON")
    ds.touch_graph_facts = _noop
    mem = MemoryManager(ds, StubLLM())
    original_get = hot.get

    def _get(key, default=None):
        if key == "limits.graph_rag_facts_limit":
            return 12
        return original_get(key, default)

    hot.get = _get
    try:
        service = DirectChatService(
            memory=mem, db=ds, llm=None, aliases=None)
        q = "что известно о конфликте Корсара с Олей в 2025 году?"
        started = time.perf_counter()
        rows = await service._rag_unified_rows(
            CHAT, q, None, memory_scope="auto", plan_act="answer")
        ms = (time.perf_counter() - started) * 1000
        explicit = _summary(rows, service._rag_period_stats or {})
        current_rows = await service._rag_unified_rows(
            CHAT, "что сейчас происходит с ботом?", None,
            memory_scope="auto", plan_act="answer")
        current = _summary(
            current_rows, service._rag_period_stats or {})
    finally:
        hot.get = original_get
        await ds.db.close()
    result = {
        "artifact_kind": "vmq_mem_rc3_snapshot_probe",
        "snapshot": SNAP,
        "snapshot_sha256_expected": "b907d4c1e24321fffa48e3719974fd2293b1b1ff721ad21661446d22033e06e7",
        "chat_id": CHAT,
        "explicit_year": {"query": q, "ms": round(ms, 1), **explicit},
        "current_state": {
            "query": "что сейчас происходит с ботом?", **current},
        "pass": {
            "explicit_all_2025": explicit["years"] == {"2025": 12},
            "out_of_year_dropped": (
                explicit["stats"]["base_out_of_year_dropped"] == 10),
            "capacity_slots": explicit["stats"]["breadth_cap"] == 10,
            "message_candidates_accounted": (
                explicit["stats"]["period_message_candidates"] == 12
                and explicit["stats"]["period_message_candidates_reason"]
                == "fact_only_consumer"),
            "current_state_2026": current["years"] == {"2026": 12},
        },
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=True, indent=1)
    print(json.dumps(result, ensure_ascii=True, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
