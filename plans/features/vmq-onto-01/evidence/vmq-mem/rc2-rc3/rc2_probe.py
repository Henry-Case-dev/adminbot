"""VMQ-MEM RC2 snapshot probe (read-only): old time-order vs new rank window.

Opens snapshot-2.58.225.db mode=ro&immutable=1 + PRAGMA query_only=ON.
Writes IDs/years/latency only, no message texts.
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
OUT = os.path.join(os.path.dirname(__file__), "rc2-snapshot.json")
CHAT = -1002661910336
QUERY = "что известно о конфликте Корсара с Олей в 2025 году?"
TARGET = 60823
os.chdir(WT)
sys.path.insert(0, WT)

from services.database import DatabaseService  # noqa: E402
from services.mca_retrieval_context import (  # noqa: E402
    RetrievalRequest,
    retrieve,
    year_time_bounds,
)


def _year(ts):
    try:
        return datetime.datetime.fromtimestamp(
            int(ts), datetime.timezone.utc).year
    except Exception:
        return None


def _cands(result):
    return [{
        "type": c.entity_type, "entity_id": str(c.entity_id),
        "id": c.id, "year": _year(c.sent_at),
    } for c in (result.candidates or ())]


async def _run(ds, rank, top_k):
    bounds = year_time_bounds(2025)
    started = time.perf_counter()
    result = await retrieve(ds, None, RetrievalRequest(
        chat_id=CHAT, query=QUERY, mode="history", top_k=top_k,
        channels=("lexical",), no_age_bias=True,
        time_from=bounds[0], time_to=bounds[1],
        lexical_time_window=True, lexical_window_rank=rank,
        include_self=True, include_direct_reply=True,
        memory_scope="auto"))
    ms = (time.perf_counter() - started) * 1000
    cands = _cands(result)
    messages = [c for c in cands if c["type"] == "message"]
    target_pos = next((i + 1 for i, c in enumerate(messages)
                       if c["entity_id"] == str(TARGET)), None)
    return {
        "rank": bool(rank), "top_k": top_k, "ms": round(ms, 1),
        "message_ids": [int(c["entity_id"]) for c in messages],
        "years": sorted({c["year"] for c in cands if c["year"]}),
        "target_position": target_pos,
        "target_in_top8": bool(target_pos and target_pos <= 8),
        "target_in_top16": bool(target_pos and target_pos <= 16),
    }


async def main():
    ds = DatabaseService(SNAP)
    uri = "file:" + SNAP.replace("\\", "/") + "?mode=ro&immutable=1"
    ds.db = await aiosqlite.connect(uri, uri=True)
    ds.db.row_factory = aiosqlite.Row
    await ds.db.execute("PRAGMA query_only=ON")
    try:
        old = await _run(ds, False, 8)
        new_runs = [await _run(ds, True, 16) for _ in range(3)]
    finally:
        await ds.db.close()
    latencies = [r["ms"] for r in new_runs]
    result = {
        "artifact_kind": "vmq_mem_rc2_snapshot_probe",
        "snapshot": SNAP,
        "snapshot_sha256_expected": "b907d4c1e24321fffa48e3719974fd2293b1b1ff721ad21661446d22033e06e7",
        "chat_id": CHAT,
        "query": QUERY,
        "target_message_id": TARGET,
        "old_time_order": old,
        "new_rank_window": new_runs,
        "new_latency_ms": {
            "min": min(latencies), "max": max(latencies),
            "p50": sorted(latencies)[len(latencies) // 2],
        },
        "pass": {
            "old_target_absent": not old["target_in_top8"],
            "new_target_top8": all(r["target_in_top8"] for r in new_runs),
            "new_target_top16": all(r["target_in_top16"] for r in new_runs),
            "new_years_2025_only": all(r["years"] == [2025] for r in new_runs),
        },
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=True, indent=1)
    print(json.dumps(result, ensure_ascii=True, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
