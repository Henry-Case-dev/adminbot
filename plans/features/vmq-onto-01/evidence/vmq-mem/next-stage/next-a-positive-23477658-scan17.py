"""Lexical-candidate scan for the 17 archive questions (A1-A15, C1, C2).

For each question: REAL product FTS builder + REAL `search_graph_facts_fts`
(64 rows, same flags as the period fill) + REAL `_rag_subject_shared`.
Answers: how many 2023-2024 lexical candidates pass the two-stem threshold
BEFORE any ranking/slot competition.
"""
import asyncio, json, os, sys, time, datetime

CODE_ROOT = os.environ["CODE_ROOT"]
DERIV = os.environ["DERIV"]
OUT = os.environ["OUT"]
SAMPLE = os.environ["SAMPLE"]
sys.path.insert(0, CODE_ROOT)
import services.direct_chat_service as dcs
import services.mca_retrieval_context as mca_rc
from services.database import DatabaseService
from services.summary_memory import build_fts_query

CHAT = -1002661910336
LIMIT = 64


def year_of(row):
    ts = row.get("message_timestamp") or row.get("created_at")
    return (datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).year
            if ts else None)


async def main():
    db = DatabaseService(DERIV)
    await db.initialize()
    now = int(time.time())
    sample = json.load(open(SAMPLE, encoding="utf-8-sig"))
    out = []
    for item in sample:
        q = item["question"]
        match = build_fts_query(mca_rc._tokenize(q), "prefix_or_stem")
        rows = await db.search_graph_facts_fts(
            CHAT, match, LIMIT, now, include_direct_reply=True,
            include_archived=True, include_self=True, include_expired=True,
            exclude_years=None)
        qs = dcs._rag_subject_stems(q)
        old = []
        shared_hist = {}
        for _r in rows:
            r = dict(_r)
            y = year_of(r)
            shared = dcs._rag_subject_shared(qs, r.get("fact"))
            if y in (2023, 2024):
                shared_hist[str(shared)] = shared_hist.get(str(shared), 0) + 1
                if shared >= 2:
                    old.append({"id": r.get("id"), "year": y, "shared": shared,
                                "fact": str(r.get("fact"))[:120]})
        rec = {"key": item["key"], "question": q, "stems": sorted(qs),
               "fts_rows": len(rows), "old_rows_2023_2024": sum(
                   shared_hist.values()), "old_shared_histogram": shared_hist,
               "old_passing_threshold": old}
        out.append(rec)
        print("%-4s fts=%-3d old=%-3d passing=%d hist=%s"
              % (item["key"], len(rows), rec["old_rows_2023_2024"],
                 len(old), shared_hist), flush=True)
        for h in old[:3]:
            print("    id=%s y=%s shared=%s %s" % (h["id"], h["year"],
                                                   h["shared"], h["fact"]),
                  flush=True)
    json.dump({"results": out}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    await db.db.close()


asyncio.run(main())
