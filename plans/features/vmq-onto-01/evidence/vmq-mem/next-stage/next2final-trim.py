"""Trim a raw harness run into durable evidence (drops the full block text,
the per-call FTS dumps and the chat-param receipts; keeps every scored field).
"""
import json
import os
import sys

KEEP_RUN = ("query", "policy", "rerank_mode", "seam", "keep", "subject",
            "sha_block", "block_len", "sha_ids", "block_empty",
            "period_rows", "period_rows_n", "period_protected_n",
            
            "period_pool_n", "period_stats_service", "rag_counts",
            "rerank_calls", "rows_returned", "rows_returned_years",
            "rows_returned_ids", "rows_detail", "base_slice_rows",
            "base_slice_years", "base_slice_ids", "usable", "elapsed_ms",
            "q_ms", "anchor_in_block", "anchor_in_rows", "anchor_in_base",
            "anchor_in_period_pool", "error", "timeout")
KEEP_RUNS = ("channels", "limit", "policy", "period_fill", "lexical_stem",
             "include_archived", "exclude_years", "pool_rows", "usable",
             "pool_years", "period_meta", "ms")

LITE = "--lite" in sys.argv
ARGS = [a for a in sys.argv[1:] if a != "--lite"]
src = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARGS[0])
dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARGS[1])
with open(src, encoding="utf-8") as fh:
    raw = json.load(fh)
out = {"meta": raw["meta"], "config": raw["config"],
       "vec": {k: v for k, v in (raw.get("vec") or {}).items()
               if k != "identity_fp"},
       "sample_meta": raw.get("sample_meta"),
       "items": []}
for item in raw.get("items") or ():
    rec = {"key": item["key"], "stratum": item.get("stratum"),
           "anchor": item.get("anchor"), "anchor_year": item.get("anchor_year"),
           "question": item.get("question"),
           "required_years": item.get("required_years"),
           "mandatory": item.get("mandatory"), "runs": {}}
    for policy, run in (item.get("runs") or {}).items():
        trimmed = {k: run.get(k) for k in KEEP_RUN if k in run}
        if LITE:
            trimmed.pop("rows_detail", None)
        else:
            trimmed["rows_detail"] = [
                dict(r, text=str(r.get("text"))[:120])
                for r in (run.get("rows_detail") or ())]
        trimmed["period_pool_rows"] = [
            {k: r.get(k) for k in ("id", "year", "proxy")}
            for r in (run.get("period_pool_rows") or ())]
        trimmed["retrieval_calls"] = [
            {k: call.get(k) for k in KEEP_RUNS if k in call}
            for call in (run.get("retrieval_calls") or ())]
        rec["runs"][policy] = trimmed
    out["items"].append(rec)
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print("trimmed", os.path.getsize(src), "->", os.path.getsize(dst))
