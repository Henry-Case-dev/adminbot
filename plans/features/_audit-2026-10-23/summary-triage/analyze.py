# -*- coding: utf-8 -*-
"""LANE SUMMARY-PROD-TRIAGE — local aggregation of raw/summary_probe.txt."""
from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw" / "summary_probe.txt"


def sections(path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    cur = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("--- ") and " (n=" in line:
            label = line[4:].split(" (n=")[0].strip()
            cur = label
            out[cur] = []
            continue
        if line.startswith("--- ") and line.endswith("---"):
            cur = None
            continue
        if cur and line.startswith("{"):
            try:
                out[cur].append(ast.literal_eval(line))
            except Exception:
                pass
    return out


S = sections(RAW)


def ts(v):
    if v is None:
        return "-"
    return dt.datetime.fromtimestamp(int(v), dt.timezone.utc).strftime(
        "%m-%d %H:%MZ")


runs = {r["run_id"]: r for r in S["runs_all"]}
stages: dict[str, dict[str, dict]] = {}
for s in S["stage_per_run"]:
    stages.setdefault(s["run_id"], {})[s["stage"]] = s

done: dict[str, dict] = {}
for e in S["run_done_detail"]:
    try:
        payload = json.loads(e["usage_json"])
    except Exception:
        continue
    done.setdefault(e["pipeline_run_id"], payload)

l2stage: dict[str, dict] = {}
for e in S["l2_stage_detail"]:
    if e["event_name"] == "SUMMARY_L2_STAGE":
        try:
            payload = json.loads(e["usage_json"])
        except Exception:
            payload = {}
        l2stage.setdefault(e["pipeline_run_id"], {
            "status": e["status"], "reason": e["reason_code"],
            "counts": payload, "ts": e["ts"]})

review = {}
for e in S["l2_stage_detail"]:
    if e["event_name"] == "SUMMARY_L2_REVIEW":
        review.setdefault(e["pipeline_run_id"], e)

print("runs:", len(runs), "| stages runs:", len(stages),
      "| run_done:", len(done), "| l2_stage:", len(l2stage))

rows = []
for rid, r in sorted(runs.items(), key=lambda kv: kv[1]["created_at"]):
    d = done.get(rid) or {}
    l2 = l2stage.get(rid) or {}
    st = stages.get(rid, {})
    final = st.get("final_policy", {}).get("status")
    l1st = st.get("l1", {}).get("status")
    rows.append({
        "run": rid[:8], "start": ts(r["created_at"]), "end": ts(r["updated_at"]),
        "state": r["state"], "pub": r["publication_status"],
        "health": r["pipeline_health"],
        "l2_review": l2.get("status"), "l2_reason": l2.get("reason"),
        "l2_chars": (l2.get("counts") or {}).get("chars"),
        "l2_calls": (l2.get("counts") or {}).get("l2_calls"),
        "l2_hint": (l2.get("counts") or {}).get("repair_hint"),
        "l1": l1st, "final": final,
        "cov": d.get("coverage"), "total": d.get("source_total"),
        "cons": d.get("source_considered"), "fb": d.get("fallback"),
        "grade": d.get("package_grade"), "dhealth": d.get("pipeline_health"),
        "msg": d.get("message_id"),
    })

hdr = ("run      start       state     pub         health    l2review   "
       "reason                 chars calls l1           final         cov  "
       "total cons fb")
print(hdr)
for x in rows:
    print("%-8s %-11s %-9s %-11s %-9s %-10s %-22s %-5s %-5s %-12s %-13s %-4s %-5s %-4s %s" % (
        x["run"], x["start"], x["state"], x["pub"], x["health"],
        x["l2_review"], x["l2_reason"], x["l2_chars"], x["l2_calls"], x["l1"],
        x["final"], x["cov"], x["total"], x["cons"], x["fb"]))

print("\n=== distribution ===")
from collections import Counter
print("state:", Counter(r["state"] for r in runs.values()))
print("pub:", Counter(str(r["publication_status"]) for r in runs.values()))
print("l2 review reason:", Counter(
    (l2stage.get(r, {}).get("reason") or "none") for r in runs))
print("coverage values (run_done):", Counter(
    str(d.get("coverage")) for d in done.values()))
print("fallback:", Counter(str(d.get("fallback")) for d in done.values()))
print("health vs cov0:", Counter(
    (str(d.get("pipeline_health")), str(d.get("coverage"))) for d in done.values()))

print("\n=== failed runs detail ===")
for rid, r in runs.items():
    if r["state"] != "FAILED":
        continue
    print(rid, "created", ts(r["created_at"]), "updated", ts(r["updated_at"]),
          "pub", r["publication_status"], "health", r["pipeline_health"])
    for name, s in stages.get(rid, {}).items():
        print("   ", name, s["status"], s["reason_code"],
              ts(s["started_at"]), "->", ts(s["finished_at"]))
    print("    done:", done.get(rid))
    print("    l2:", l2stage.get(rid))
