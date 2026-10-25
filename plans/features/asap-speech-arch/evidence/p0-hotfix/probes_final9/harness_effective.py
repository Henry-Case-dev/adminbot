#!/usr/bin/env python3
"""Stand wrapper: production research fallback on the committed harness.

Why: the committed `probes_full/harness_probe_full.py` builds the payload from
the RAW Planner plan and never calls DirectChatService._plan_direct_l1, where
the candidate (7ca05a92) applies `services.direct_l1.apply_research_fallback`
after the ladder. The committed `--self-check` only proves the function exists.

This wrapper imports the committed harness UNCHANGED and patches ONLY
`services.direct_l1.parse_l1_plan` so that a valid plan gets the SAME committed
fallback applied with the SAME query text before payload/metrics/L2 are built.
Product code is not modified; output JSON is labelled `stand_wrapper`.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def load_harness():
    path = os.path.join(HERE, "harness_probe_full.py")
    spec = importlib.util.spec_from_file_location("harness_probe_full", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, choices=("A", "B"))
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()

    hp = load_harness()
    sys.path.insert(0, os.path.abspath(args.root))
    from services import direct_l1 as l1

    state = {"query": "", "calls": []}
    original_sqlite = hp.load_sqlite
    tg_id = hp.TG_A if args.name == "A" else hp.TG_B
    window_key = "window_%s" % args.name

    def patched_sqlite(root):
        sq = original_sqlite(root)
        hits = 0
        for row in sq.get(window_key) or []:
            if str(row.get("tg_message_id")) == str(tg_id):
                state["query"] = row.get("text") or ""
                hits += 1
        sq["extra_question"] = state["query"]
        sq["extra_hits"] = hits
        return sq

    original_parse = l1.parse_l1_plan

    def patched_parse(raw):
        plan = original_parse(raw)
        if plan is None:
            state["calls"].append({"before": None, "after": None,
                                   "applied": False})
            return None
        before = str(getattr(plan, "response_act", "") or "")
        plan, applied = l1.apply_research_fallback(plan, state["query"])
        state["calls"].append({"before": before,
                               "after": str(getattr(plan, "response_act", "") or ""),
                               "applied": bool(applied)})
        return plan

    hp.load_sqlite = patched_sqlite
    l1.parse_l1_plan = patched_parse
    sys.argv = [
        "harness_probe_full.py",
        "--root", args.root,
        "--label", "eff_" + args.name,
        "--case", args.name,
        "--repeats", str(args.repeats),
        "--use-code-l1-canon",
        "--out", args.out,
    ]
    rc = hp.main()
    try:
        data = json.load(open(args.out, encoding="utf-8"))
        data["stand_wrapper"] = {
            "file": os.path.basename(os.path.abspath(__file__)),
            "patched": "services.direct_l1.parse_l1_plan -> apply_research_fallback(plan, query)",
            "harness_unchanged": True,
            "query_sha12": sha12(state["query"]),
            "fallback_calls": state["calls"],
            "reason": "committed harness bypasses DirectChatService._plan_direct_l1",
        }
        json.dump(data, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception as exc:                              # noqa: BLE001
        print("wrapper annotate failed: %s" % exc, file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
