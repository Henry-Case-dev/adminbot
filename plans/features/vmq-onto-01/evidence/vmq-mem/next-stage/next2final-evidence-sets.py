"""Add pre-registered ACCEPTABLE-EVIDENCE sets to the frozen query sample.

Why: the exact-anchor rule (mandatory = the one corpus row the question was
built from) produced a floor for both sides (recall ~0.10 for `multi`, ~0.30
for `recent`), because a top-10 context rarely contains that exact row. The
comparison itself is unaffected (the deterministic sides are identical), but
the absolute number says nothing about quality.

The evidence sets are computed from the CORPUS ONLY, before scoring, and are
symmetric for both sides:
  * old/recent  - a required fact is evidenced by any corpus row of the same
                  year sharing >=2 §2 stems with the ANCHOR FACT text (the
                  event/topic), capped at 12 rows (strongest overlap first);
  * multi       - a required year is evidenced by any corpus row of that year
                  that mentions the participant name, capped at 12 (lowest id);
  * the anchor row itself is always included.
Nothing here looks at baseline/candidate output.
"""
import json
import os
import sqlite3
import sys

DB = (r"C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489"
      r"\vmq-onto-01-3689dd92710d\probe-d86a98460c\prod-copy.db")
HERE = os.path.dirname(os.path.abspath(__file__))
IN = os.path.join(HERE, "next2final-sample.json")
OUT = os.path.join(HERE, "next2final-gold-v2.json")
sys.path.insert(0, r"C:\Users\main\.config\opencode\WorkspaceData\worktrees"
                   r"\c742e4de9e92c489\vmq-onto-01-3689dd92710d-aaecec2a")
from services import direct_chat_service as dcs   # noqa: E402


def main():
    with open(IN, encoding="utf-8") as fh:
        sample = json.load(fh)
    db = sqlite3.connect("file:%s?mode=ro&immutable=1" % DB.replace("\\", "/"),
                         uri=True)
    rows = db.execute(
        "select id, fact, message_timestamp, created_at from graph_facts "
        "where chat_id=? and status='confirmed' order by id",
        (-1002661910336,)).fetchall()
    facts = []
    for fid, fact, mts, cts in rows:
        ts = mts or cts
        if not ts:
            continue
        import datetime
        facts.append({"id": int(fid), "fact": str(fact or ""),
                      "year": datetime.datetime.fromtimestamp(
                          int(ts), datetime.timezone.utc).year})
    by_year = {}
    for fact in facts:
        by_year.setdefault(fact["year"], []).append(fact)

    out = {"meta": dict(sample["meta"]), "queries": []}
    out["meta"]["evidence_rule"] = {
        "old/recent": "same year + >=2 §2 stems with the anchor fact text, "
                      "anchor always included, cap 12",
        "multi": "same year + participant name in the fact text, cap 12 by id",
    }
    for query in sample["queries"]:
        item = dict(query)
        stratum = query["stratum"]
        evidence = []
        if stratum == "multi":
            name = (query.get("name")
                    or query["question"].split("про ", 1)[1].split(" за", 1)[0])
            for year in query["required_years"]:
                ids = [f["id"] for f in by_year.get(int(year), [])
                       if name in f["fact"]]
                anchor_ids = [m["id"] for m in query["mandatory"]
                              if m["year"] == year]
                ids = list(dict.fromkeys(anchor_ids + ids))
                evidence.append({"label": "name in %s" % year,
                                 "year": int(year), "ids": ids})
        else:
            anchor_fact = query["mandatory"][0]["fact"]
            anchor_stems = dcs._rag_subject_stems(anchor_fact)
            scored = []
            for fact in by_year.get(int(query["anchor_year"]), []):
                overlap = dcs._rag_subject_shared(anchor_stems, fact["fact"])
                if overlap >= 2:
                    scored.append((overlap, fact["id"]))
            scored.sort(key=lambda pair: (-pair[0], pair[1]))
            ids = [query["anchor"]]
            ids += [fid for _o, fid in scored if fid != query["anchor"]]
            evidence.append({"label": "event %s" % query["anchor_year"],
                             "year": int(query["anchor_year"]),
                             "ids": ids})
        item["mandatory_evidence"] = evidence
        out["queries"].append(item)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    sizes = [len(e["ids"]) for q in out["queries"]
             for e in q["mandatory_evidence"]]
    print("queries", len(out["queries"]), "evidence sets", len(sizes),
          "size min/median/max", min(sizes), sorted(sizes)[len(sizes) // 2],
          max(sizes))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
