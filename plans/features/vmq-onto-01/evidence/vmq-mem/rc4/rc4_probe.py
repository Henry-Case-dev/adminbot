"""VMQ-MEM RC4 snapshot probe (read-only): short stem + year-token policy.

Writes counts/years/IDs only, no fact/message texts.
"""
import asyncio
import collections
import datetime
import json
import os
import sqlite3
import sys

import aiosqlite

WT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", ".."))
SNAP = r"C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\snapshot-2.58.225.db"
OUT = os.path.join(os.path.dirname(__file__), "rc4-snapshot.json")
CHAT = -1002661910336
os.chdir(WT)
sys.path.insert(0, WT)

from services.database import DatabaseService  # noqa: E402
from services.mca_retrieval_context import (  # noqa: E402
    RetrievalRequest,
    _period_fts_keywords,
    _tokenize,
    period_subject_shared,
    period_subject_stems,
    resolve_period_intent,
    retrieve,
    select_period_rows,
)
from services.summary_memory import build_fts_query  # noqa: E402
from services.text_morphology import stem_word  # noqa: E402

A1 = "напиши юмористический рассказ об основных шизах конфы"
D = "что известно о конфликте Корсара с Олей в 2025 году?"


def _year(ts):
    try:
        return datetime.datetime.fromtimestamp(
            int(ts), datetime.timezone.utc).year
    except Exception:
        return None


def _rows(match, limit):
    c = sqlite3.connect(
        "file:" + SNAP.replace("\\", "/") + "?mode=ro&immutable=1",
        uri=True)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    rows = c.execute(
        "SELECT f.id, f.fact, f.message_timestamp, f.created_at, "
        "COALESCE(f.message_timestamp, f.created_at) AS rag_ts "
        "FROM graph_facts_fts JOIN graph_facts f "
        "ON f.id = graph_facts_fts.rowid "
        "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
        "AND f.status IN ('confirmed','archived_belief','archived_fact') "
        "ORDER BY graph_facts_fts.rank LIMIT ?",
        (match, CHAT, limit)).fetchall()
    c.close()
    return [dict(row) for row in rows]


def _old_stems(text):
    out = set()
    for word in _tokenize(text):
        stem = stem_word(str(word))
        if len(stem) >= 4:
            out.add(stem)
    return out


def _dist(rows, stems):
    dist = collections.Counter(
        period_subject_shared(stems, row["fact"]) for row in rows)
    years = collections.Counter(
        _year(row["rag_ts"]) for row in rows if _year(row["rag_ts"]))
    return {
        "count": len(rows),
        "years": {str(k): v for k, v in sorted(years.items())},
        "shared": {str(k): v for k, v in sorted(dist.items())},
        "shared_ge_2": sum(v for k, v in dist.items() if k >= 2),
    }


async def main():
    old_kw = _period_fts_keywords(_tokenize(A1), explicit_year=False)
    new_kw = _period_fts_keywords(_tokenize(A1), explicit_year=False)
    old_match = build_fts_query(old_kw, mode="prefix_or_stem")
    new_match = build_fts_query(new_kw, mode="prefix_or_stem_short")
    old_stems = _old_stems(A1)
    new_stems = period_subject_stems(A1)
    a2 = {"old_match": old_match, "new_match": new_match}
    for limit in (32, 64):
        a2[str(limit)] = {
            "old": _dist(_rows(old_match, limit), old_stems),
            "new": _dist(_rows(new_match, limit), new_stems),
        }
    a2["shizah_total"] = {
        "old": len(_rows(build_fts_query(["шизах"], mode="prefix_or_stem"), 1000)),
        "new": len(_rows(build_fts_query(["шизах"], mode="prefix_or_stem_short"), 1000)),
    }

    d_old_kw = _period_fts_keywords(_tokenize(D), explicit_year=False)
    d_new_kw = _period_fts_keywords(_tokenize(D), explicit_year=True)
    d_stems = period_subject_stems(D, explicit_year=True)
    d_old_match = build_fts_query(d_old_kw, mode="prefix_or_stem_short")
    d_new_match = build_fts_query(d_new_kw, mode="prefix_or_stem_short")
    d4 = {
        "old_keywords": d_old_kw,
        "new_keywords": d_new_kw,
        "old_match": d_old_match,
        "new_match": d_new_match,
        "old_has_2025": '"2025"*' in d_old_match,
        "new_has_2025": '"2025"*' in d_new_match,
        "old_has_godu": '"году"*' in d_old_match,
        "new_has_godu": '"году"*' in d_new_match,
        "new_pool_64": _dist(_rows(d_new_match, 64), d_stems),
    }

    ds = DatabaseService(SNAP)
    uri = "file:" + SNAP.replace("\\", "/") + "?mode=ro&immutable=1"
    ds.db = await aiosqlite.connect(uri, uri=True)
    ds.db.row_factory = aiosqlite.Row
    await ds.db.execute("PRAGMA query_only=ON")
    try:
        bounds = (int(datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc).timestamp()),
                  int(datetime.datetime(2025, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc).timestamp()))
        intent = resolve_period_intent(D, memory_scope="auto")
        res = await retrieve(ds, None, RetrievalRequest(
            chat_id=CHAT, query=D, mode="specific", top_k=32,
            channels=("lexical",), preserve_channel_order=True,
            include_self=True, include_direct_reply=True,
            memory_scope="auto", lexical_stem=True, include_archived=True,
            period_fill=True, period_intent=intent,
            time_from=bounds[0], time_to=bounds[1],
            lexical_time_window=True, lexical_window_rank=True))
        delivered_years = collections.Counter(
            _year(c.sent_at) for c in res.candidates or () if c.sent_at)
        explicit = {
            "candidates": len(res.candidates or ()),
            "years": {str(k): v for k, v in sorted(delivered_years.items())},
            "has_2024": 2024 in delivered_years,
            "has_2026": 2026 in delivered_years,
        }
        a2_intent = resolve_period_intent(A1, memory_scope="historical")
        a2_res = await retrieve(ds, None, RetrievalRequest(
            chat_id=CHAT, query=A1, mode="specific", top_k=64,
            channels=("lexical",), preserve_channel_order=True,
            include_self=True, include_direct_reply=True,
            memory_scope="historical", lexical_stem=True,
            include_archived=True, period_fill=True,
            period_intent=a2_intent))
        a2_rows = [dict(row) for row in (a2_res.fact_rows or ())]
        a2_accepted, a2_sel = select_period_rows(
            a2_rows, query=A1, intent=a2_intent, policy="historical",
            slots=2)
        a2_years = collections.Counter(
            _year(row.get("message_timestamp") or row.get("created_at")
                  or row.get("rag_ts")) for row in a2_accepted)
        a2_accept = {
            "fact_rows": len(a2_rows),
            "accepted": len(a2_accepted),
            "accepted_years": {str(k): v for k, v in sorted(a2_years.items())},
            "accepted_ids": [row.get("id") for row in a2_accepted],
            "strict_passed": a2_sel.get("lexical_strict_passed"),
            "soft_fallback": a2_sel.get("soft_fallback"),
        }
    finally:
        await ds.db.close()

    result = {
        "artifact_kind": "vmq_mem_rc4_snapshot_probe",
        "snapshot": SNAP,
        "snapshot_sha256_expected": "b907d4c1e24321fffa48e3719974fd2293b1b1ff721ad21661446d22033e06e7",
        "a2_short_stem": a2,
        "a2_accept": a2_accept,
        "d4_year_tokens": d4,
        "explicit_year_no_leak": explicit,
        "pass": {
            "a2_total_103": a2["shizah_total"]["new"] == 103,
            "a2_shared_32_up": (a2["32"]["new"]["shared_ge_2"]
                                > a2["32"]["old"]["shared_ge_2"]),
            "a2_shared_64_up": (a2["64"]["new"]["shared_ge_2"]
                                > a2["64"]["old"]["shared_ge_2"]),
            "a2_old_year_accepted": any(
                str(year) in a2_accept["accepted_years"]
                for year in (2023, 2024)),
            "d4_2025_removed": (d4["old_has_2025"]
                                and not d4["new_has_2025"]),
            "d4_godu_removed": (d4["old_has_godu"]
                                and not d4["new_has_godu"]),
            "explicit_no_2024_2026": (not explicit["has_2024"]
                                      and not explicit["has_2026"]),
        },
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
