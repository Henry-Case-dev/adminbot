# -*- coding: utf-8 -*-
"""D1 reproduction: current-state questions under memory_scope=auto."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace

CLONE = os.environ.get("VMQ_CLONE") or os.getcwd()
DBPATH = os.environ.get("VMQ_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dbcopy.db")
OUT = os.environ.get("PROBE_OUT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "d1.json")
CHAT = -1002661910336
sys.path.insert(0, CLONE)
os.chdir(CLONE)

from services import hot_config as hot                    # noqa: E402
from services import mca_retrieval_context as mrc         # noqa: E402
from services.database import DatabaseService             # noqa: E402
from services.direct_chat_service import DirectChatService  # noqa: E402
from services.summary_memory import MemoryManager         # noqa: E402


class _Cache:
    def get(self, key, default=None):
        return default

    def get_all(self):
        return {}


class StubLLM:
    async def embed(self, texts):
        raise RuntimeError("EMBED_API_FAILED provider_unavailable")

    async def generate(self, messages):
        raise RuntimeError("LLM unavailable")


class StubAliases:
    def resolve(self, user_id, nickname=None, username=None, memory_name=None):
        return str(nickname or username or memory_name or user_id or "")


def year_of(ts):
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    return time.gmtime(ts).tm_year if ts > 0 else None


def hist(values):
    out = {}
    for value in values:
        key = str(value) if value is not None else "no_date"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def brief(row, stems):
    text = str((row or {}).get("fact") or "")
    return {
        "id": (row or {}).get("id"),
        "year": year_of((row or {}).get("rag_ts")
                        or (row or {}).get("message_timestamp")
                        or (row or {}).get("created_at")),
        "shared": mrc.period_subject_shared(stems, text),
        "reason": (row or {}).get("stems_shared_reason"),
        "proxy": (row or {}).get("subject_proxy"),
        "role": (row or {}).get("subject_role"),
        "origin": (row or {}).get("origin"),
    }


async def main():
    hot.set_config_cache(_Cache())
    db = DatabaseService(DBPATH)
    await db.initialize()
    memory = MemoryManager(db, StubLLM(), aliases=None)

    async def _noop():
        return 0

    memory.backfill_archive_vectors = _noop
    memory.backfill_graph_fact_vectors = _noop
    try:
        await asyncio.wait_for(memory.initialize(), 120)
    except Exception:                                     # noqa: BLE001
        pass
    svc = DirectChatService(memory, db, StubLLM(), StubAliases())
    stub = SimpleNamespace(text="", chat_id=CHAT, message_id=0)
    queries = [
        ("A1P", "что за шизы были на конфе?"),
        ("T3_mulyanka", "как сейчас дела с мулянкой?"),
        ("T3_alina", "что сейчас с Алиной?"),
        ("T3_E1", "что сейчас происходит с E1?"),
    ]
    out = {"db": DBPATH, "classes": {}}
    for key, query in queries:
        stub.text = query
        stems = mrc.period_subject_stems(query)
        captured = {"calls": []}
        original = svc._rag_retrieve

        async def spy(*args, **kwargs):
            got = await original(*args, **kwargs)
            rows = list(getattr(got, "fact_rows", ()) or ())
            captured["calls"].append({
                "period_fill": bool(kwargs.get("period_fill")),
                "intent": str(kwargs.get("period_intent") or ""),
                "rows": [brief(row, stems) for row in rows],
                "period_fill_stats": dict(
                    getattr(got, "period_fill", None) or {}),
            })
            return got

        svc._rag_retrieve = spy
        try:
            rows = await asyncio.wait_for(svc._rag_unified_rows(
                CHAT, query, stub, memory_scope="auto"), 300)
        finally:
            svc._rag_retrieve = original
        out["classes"][key] = {
            "stems": sorted(stems),
            "rows": [brief(row, stems) for row in (rows or ())
                     if isinstance(row, dict)],
            "years": hist([year_of((row or {}).get("rag_ts")
                                   or (row or {}).get("message_timestamp"))
                           for row in (rows or ()) if isinstance(row, dict)]),
            "calls": captured["calls"],
            "period_stats": dict(getattr(svc, "_rag_period_stats", None) or {}),
        }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    for key, value in out["classes"].items():
        print("==", key, value["stems"], "years", value["years"])
        for call in value["calls"]:
            print("  call period_fill=%s intent=%s rows=%s" % (
                call["period_fill"], call["intent"][:80],
                [(r["id"], r["year"], r["shared"]) for r in call["rows"]]))
        print("  final", [(r["id"], r["year"], r["shared"], r["reason"],
                           r["role"]) for r in value["rows"]])
        print("  stats", json.dumps(value["period_stats"],
                                    ensure_ascii=False)[:500])
    await db.close()
    os._exit(0)


try:
    asyncio.run(main())
except BaseException:                                     # noqa: BLE001
    import traceback
    traceback.print_exc()
    os._exit(2)
