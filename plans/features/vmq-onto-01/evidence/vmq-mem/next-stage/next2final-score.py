"""Paired scorer for the NEXT-02 final candidate (base 23477658 vs candidate).

Judges ONLY with pre-registered gold labels from `next2final-sample.json` and
fixed mechanical relevance rules (see sample meta). No LLM judge.

Metrics per query (retrieval level = rows handed to the block builder; final
level = rows actually rendered into the RAG block):
  required_fact_recall   mandatory facts found / mandatory facts (corpus-backed)
  relevance_precision    mechanically relevant rows / returned rows
  temporal_coverage      required_years subset of years present
  fresh_loss             mandatory facts the BASELINE rendered but candidate did
                         not (must be empty)
Year share is computed as a DIAGNOSTIC only; no gate is applied.
"""
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "next2final-gold-v2.json")
if not os.path.exists(SAMPLE):
    SAMPLE = os.path.join(HERE, "next2final-sample.json")
BASE_RAW = os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1
                         else "next2final-raw-base-det.json")
CAND_RAW = os.path.join(HERE, sys.argv[2] if len(sys.argv) > 2
                        else "next2final-raw-cand-det.json")
OUT_NAME = sys.argv[3] if len(sys.argv) > 3 else "next2final-score.json"
# product stem helpers from the BASE worktree (identical in both sides; §A
# does not touch them) - used only as a deterministic relevance judge
sys.path.insert(0, r"C:\Users\main\.config\opencode\WorkspaceData\worktrees"
                   r"\c742e4de9e92c489\vmq-onto-01-3689dd92710d-aaecec2a")
from services import direct_chat_service as dcs   # noqa: E402


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def rows_by_key(raw):
    out = {}
    for item in raw["items"]:
        for policy, run in item["runs"].items():
            out[(item["key"], policy)] = run
    return out


def judged(query, stratum, rows):
    """[(row, relevant_bool)] for the returned rows."""
    text_q = query["question"]
    q_stems = dcs._rag_subject_stems(text_q)
    name = (query.get("name") or "").lower()
    out = []
    for row in rows or ():
        text = str(row.get("text") or "")
        if stratum == "multi":
            ok = bool(name) and name in text.lower()
        else:
            ok = dcs._rag_subject_shared(q_stems, text) >= 2
        out.append((row, bool(ok), row.get("year")))
    return out


def block_years(block):
    years = {}
    for line in str(block or "").splitlines():
        if not line.strip() or line.startswith("<RAG_Memory"):
            continue
        year = None
        for token in ("2022", "2023", "2024", "2025", "2026"):
            if token in line:
                year = token
                break
        key = year or "none"
        years[key] = years.get(key, 0) + 1
    return years


def score_run(query, run):
    stratum = query["stratum"]
    rows = run.get("rows_detail") or []
    block_ids = {str(x) for x in (run.get("ids") or [])}
    mandatory = [str(m["id"]) for m in query["mandatory"]]
    found_rows = [m for m in mandatory
                  if any(str(r.get("id")) == m for r in rows)]
    found_block = [m for m in mandatory if m in block_ids]
    evidence = query.get("mandatory_evidence") or []
    row_ids = {str(r.get("id")) for r in rows}
    found_evidence = [ev for ev in evidence
                      if any(str(i) in row_ids for i in ev["ids"])]
    missed_evidence = [ev["label"] for ev in evidence
                       if ev not in found_evidence]
    found_evidence_block = [ev for ev in evidence
                            if any(str(i) in block_ids for i in ev["ids"])]
    missed_evidence_block = [ev["label"] for ev in evidence
                             if ev not in found_evidence_block]
    judges = judged(query, stratum, rows)
    relevant = sum(1 for _r, ok, _y in judges if ok)
    years_rows = {str(y) for _r, _ok, y in judges if y is not None}
    years_block = set()
    for line in str(run.get("block") or "").splitlines():
        for token in ("2022", "2023", "2024", "2025", "2026"):
            if token in line:
                years_block.add(token)
    return {
        "key": query["key"], "stratum": stratum, "policy": run.get("policy"),
        "mandatory_n": len(mandatory),
        "found_rows_n": len(found_rows), "found_block_n": len(found_block),
        "recall_rows": len(found_rows) / max(1, len(mandatory)),
        "recall_block": len(found_block) / max(1, len(mandatory)),
        "rows_n": len(rows), "relevant_n": relevant,
        "precision": (relevant / len(rows)) if rows else None,
        "required_years": [str(y) for y in query["required_years"]],
        "years_rows": sorted(years_rows), "years_block": sorted(years_block),
        "coverage_rows": all(str(y) in years_rows
                             for y in query["required_years"]),
        "coverage_block": all(str(y) in years_block
                              for y in query["required_years"]),
        "found_rows_ids": found_rows, "found_block_ids": found_block,
        "evidence_n": len(evidence), "found_evidence_n": len(found_evidence),
        "recall_evidence": (len(found_evidence) / max(1, len(evidence))),
        "recall_evidence_block": (len(found_evidence_block)
                                  / max(1, len(evidence))),
        "miss_evidence_labels": missed_evidence,
        "miss_evidence_block_labels": missed_evidence_block,
        "miss_rows_ids": [m for m in mandatory if m not in found_rows],
        "miss_block_ids": [m for m in mandatory if m not in found_block],
        "block_years": block_years(run.get("block")),
        "block_rows": sum(block_years(run.get("block")).values()),
        "period_rows_n": run.get("period_rows_n"),
        "period_stats": run.get("period_stats_service"),
        "irrelevant_ids": [str(r.get("id")) for r, ok, _y in judges
                           if not ok],
        "pool_rows_n": len(run.get("period_pool_rows") or []),
        "pool_lexical_n": sum(1 for r in (run.get("period_pool_rows") or [])
                              if r.get("proxy") != "knn"),
        "pool_knn_n": sum(1 for r in (run.get("period_pool_rows") or [])
                          if r.get("proxy") == "knn"),
        "pool_years": sorted({str(r.get("year")) for r
                              in (run.get("period_pool_rows") or [])
                              if r.get("year") is not None}),
    }


def mean(values):
    values = [v for v in values if v is not None]
    return (sum(values) / len(values)) if values else None


def bootstrap_diff(base_vals, cand_vals, reps=2000, seed=20261313):
    rng = random.Random(seed)
    n = len(base_vals)
    diffs = []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        b = [base_vals[i] for i in idx]
        c = [cand_vals[i] for i in idx]
        diffs.append(mean(c) - mean(b))
    diffs.sort()
    return {"point": mean(cand_vals) - mean(base_vals),
            "ci95": [round(diffs[int(0.025 * reps)], 4),
                     round(diffs[int(0.975 * reps) - 1], 4)]}


def main():
    sample = load(SAMPLE)
    queries = {q["key"]: q for q in sample["queries"]}
    base_raw, cand_raw = load(BASE_RAW), load(CAND_RAW)
    base, cand = rows_by_key(base_raw), rows_by_key(cand_raw)
    print("### side meta")
    for name, raw in (("base", base_raw), ("cand", cand_raw)):
        print(name, raw["meta"]["git_head"], "seam=", raw["meta"]["seam"],
              "rerank_flag=", raw["config"]["rerank_flag_settings_default"],
              "batch_s=", raw["meta"]["batch_s"])

    keys = sorted(base)
    per_query, fresh_loss = [], []
    for pair_key in keys:
        key = pair_key[0]
        query = queries[key]
        b = score_run(query, base[pair_key])
        c = score_run(query, cand[pair_key])
        per_query.append({"key": key, "stratum": query["stratum"],
                          "policy": b["policy"], "base": b, "cand": c,
                          "delta_recall_rows":
                              c["recall_rows"] - b["recall_rows"],
                          "delta_recall_block":
                              c["recall_block"] - b["recall_block"],
                          "delta_recall_evidence":
                              c["recall_evidence"] - b["recall_evidence"],
                          "delta_precision":
                              (c["precision"] or 0) - (b["precision"] or 0)})
        lost = set(b["found_block_ids"]) - set(c["found_block_ids"])
        if lost:
            fresh_loss.append({"key": key, "policy": b["policy"],
                               "lost": sorted(lost)})
        lost_ev = (set(b["miss_evidence_labels"]) ^
                   set(c["miss_evidence_labels"]))
        new_miss = set(c["miss_evidence_labels"]) - set(b["miss_evidence_labels"])
        if new_miss:
            fresh_loss.append({"key": key, "policy": b["policy"],
                               "lost_evidence": sorted(new_miss)})
        new_miss_block = (set(c["miss_evidence_block_labels"])
                          - set(b["miss_evidence_block_labels"]))
        if new_miss_block:
            fresh_loss.append({"key": key, "policy": b["policy"],
                               "lost_evidence_block": sorted(new_miss_block)})

    print("\n### per stratum (protocollary: historical for old/multi, "
          "auto for recent is the PRIMARY reading)")
    strata = ("old", "multi", "recent")
    summary = {}
    for stratum in strata:
        for primary, policies in (("primary", (
                "historical" if stratum != "recent" else "auto",)),
                ("both", ("historical", "auto"))):
            sel = [p for p in per_query
                   if p["stratum"] == stratum and p["policy"] in policies]
            if not sel:
                continue
            row = {
                "n_pairs": len(sel),
                "recall_evidence": [mean([p[s]["recall_evidence"] for p in sel])
                                    for s in ("base", "cand")],
                "recall_rows": [mean([p[s]["recall_rows"] for p in sel])
                                for s in ("base", "cand")],
                "recall_block": [mean([p[s]["recall_block"] for p in sel])
                                 for s in ("base", "cand")],
                "precision": [mean([p[s]["precision"] for p in sel])
                              for s in ("base", "cand")],
                "coverage_rows": [mean([1.0 if p[s]["coverage_rows"] else 0.0
                                        for p in sel])
                                  for s in ("base", "cand")],
                "coverage_block": [mean([1.0 if p[s]["coverage_block"]
                                         else 0.0 for p in sel])
                                   for s in ("base", "cand")],
                "year_share_2026": [
                    sum(p[s]["block_years"].get("2026", 0) for p in sel)
                    / max(1, sum(p[s]["block_rows"] for p in sel))
                    for s in ("base", "cand")],
                "bootstrap_recall_evidence_delta": bootstrap_diff(
                    [p["base"]["recall_evidence"] for p in sel],
                    [p["cand"]["recall_evidence"] for p in sel]),
                "bootstrap_recall_rows_delta": bootstrap_diff(
                    [p["base"]["recall_rows"] for p in sel],
                    [p["cand"]["recall_rows"] for p in sel]),
                "bootstrap_precision_delta": bootstrap_diff(
                    [p["base"]["precision"] or 0.0 for p in sel],
                    [p["cand"]["precision"] or 0.0 for p in sel]),
            }
            summary["%s/%s" % (stratum, primary)] = row
            print("%-14s %-8s n=%2d  recall_ev %.3f -> %.3f  "
                  "recall_exact %.3f -> %.3f  precision %s -> %s  "
                  "cov_rows %.2f -> %.2f  cov_block %.2f -> %.2f  "
                  "2026share %.3f -> %.3f  d_ev_ci=%s d_prec_ci=%s"
                  % (stratum, primary, row["n_pairs"],
                     row["recall_evidence"][0], row["recall_evidence"][1],
                     row["recall_rows"][0], row["recall_rows"][1],
                     _fmt(row["precision"][0]), _fmt(row["precision"][1]),
                     row["coverage_rows"][0], row["coverage_rows"][1],
                     row["coverage_block"][0], row["coverage_block"][1],
                     row["year_share_2026"][0], row["year_share_2026"][1],
                     row["bootstrap_recall_evidence_delta"]["ci95"],
                     row["bootstrap_precision_delta"]["ci95"]))

    print("\n### fresh/required fact loss (candidate missing a baseline fact)")
    print("losses:", len(fresh_loss))
    for item in fresh_loss[:20]:
        print("  ", item)

    print("\n### identical block ids per (query,policy)")
    same = sum(1 for p in per_query
               if set(p["base"]["found_block_ids"]) ==
               set(p["cand"]["found_block_ids"])
               and p["base"]["block_years"] == p["cand"]["block_years"])
    print("identical block-year composition: %d/%d" % (same, len(per_query)))
    identical_rows = sum(1 for key in keys
                         if [str(r.get("id")) for r in
                             (base[key].get("rows_detail") or [])]
                         == [str(r.get("id")) for r in
                             (cand[key].get("rows_detail") or [])])
    print("identical returned-row id lists: %d/%d"
          % (identical_rows, len(keys)))
    period_diff = []
    for key in keys:
        bs = base[key].get("period_stats_service") or {}
        cs = cand[key].get("period_stats_service") or {}
        if (bs.get("vector_rows"), bs.get("vector_pool_miss")) != (
                cs.get("vector_rows"), cs.get("vector_pool_miss")):
            period_diff.append(key)
    print("period-leg stat differences:", period_diff[:10],
          "count=", len(period_diff))

    print("\n### period pool composition (retrieval source)")
    print("  base pool rows total:", sum(p["base"]["pool_rows_n"]
                                       for p in per_query),
          " lexical:", sum(p["base"]["pool_lexical_n"] for p in per_query),
          " knn:", sum(p["base"]["pool_knn_n"] for p in per_query))
    print("  cand pool rows total:", sum(p["cand"]["pool_rows_n"]
                                       for p in per_query),
          " lexical:", sum(p["cand"]["pool_lexical_n"] for p in per_query),
          " knn:", sum(p["cand"]["pool_knn_n"] for p in per_query))
    print("  period accepted rows base/cand:",
          sum(p["base"]["period_rows_n"] or 0 for p in per_query),
          "/", sum(p["cand"]["period_rows_n"] or 0 for p in per_query))

    print("\n### NEXT-05 timings (candidate, from usage_json.period_fill)")
    metas = [call.get("period_meta") or {}
             for run in cand.values()
             for call in (run.get("retrieval_calls") or [])
             if call.get("period_fill")]
    print("period calls:", len(metas),
          "knn_ms present:", sum(1 for m in metas if m.get("knn_ms") is not None),
          "fts_ms present:", sum(1 for m in metas if m.get("fts_ms") is not None),
          "knn reason:", sorted({m.get("knn_ms_reason") for m in metas
                                 if m.get("knn_ms") is None}),
          "fts reason:", sorted({m.get("fts_ms_reason") for m in metas
                                 if m.get("fts_ms") is None}))
    p95 = sorted(m["fts_ms"] + (m.get("knn_ms") or 0.0) for m in metas
                 if m.get("fts_ms") is not None)
    if p95:
        print("period call ms p95 (fts+knn): %.1f  median %.1f"
              % (p95[max(0, int(0.95 * len(p95)) - 1)],
                 p95[len(p95) // 2]))

    with open(os.path.join(HERE, OUT_NAME), "w",
              encoding="utf-8") as fh:
        json.dump({"summary": summary, "per_query": per_query,
                   "fresh_loss": fresh_loss,
                   "sample_meta": sample["meta"]}, fh,
                  ensure_ascii=False, indent=1)
    print("\nwrote", OUT_NAME)


def _fmt(value):
    return "n/a" if value is None else "%.3f" % value


if __name__ == "__main__":
    main()
