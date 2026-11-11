#!/usr/bin/env python3
"""Durable-queue completeness lint for plans/progress_scope.json.

Complements (does not replace) `workflow_progress.py --require-queue`:
that checker validates the whole scope; this one is a fast local gate with the
same rules plus a few stricter ones (uniqueness, dependency provenance).

Exit 0 = queue metadata complete, 1 = defects.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

DONE = {"VERIFIED", "DONE", "DONE_WITH_GAPS"}
PRIORITY_RE = re.compile(r"^P[0-9]$")


def check(scope: dict) -> list[str]:
    problems: list[str] = []
    tasks = scope.get("tasks") or []
    ids = {t.get("id") for t in tasks if t.get("id")}
    seen_pos: dict[int, str] = {}

    if not scope.get("queue_schema"):
        problems.append("scope: queue_schema missing")

    for t in tasks:
        tid = t.get("id") or "<no-id>"
        if str(t.get("status") or "").upper() in DONE:
            continue

        pos = t.get("queue_position")
        if not isinstance(pos, int) or isinstance(pos, bool) or pos <= 0:
            problems.append(f"{tid}: queue_position must be a positive integer, got {pos!r}")
        elif pos in seen_pos:
            problems.append(f"{tid}: queue_position {pos} duplicates {seen_pos[pos]}")
        else:
            seen_pos[pos] = tid

        prio = t.get("priority")
        if not isinstance(prio, str) or not PRIORITY_RE.match(prio):
            problems.append(f"{tid}: priority must be P0..P9, got {prio!r}")

        blocked = t.get("blocked_by")
        if blocked is None:
            problems.append(f"{tid}: blocked_by missing (use [] when none)")
        elif not isinstance(blocked, list):
            problems.append(f"{tid}: blocked_by must be a list")
        else:
            sources = t.get("blocker_sources") or {}
            for dep in blocked:
                dep = str(dep)
                if dep == tid:
                    problems.append(f"{tid}: blocked_by references itself")
                elif dep not in ids and dep not in sources:
                    problems.append(f"{tid}: blocked_by '{dep}' is neither an existing task nor declared in blocker_sources")

        if not t.get("execution_state"):
            problems.append(f"{tid}: execution_state missing (active_assignment/queued/awaiting_dependency/awaiting_architecture/paused_with_branch/release_pending/waiting_external/amendment)")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-file", default="plans/progress_scope.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.scope_file, encoding="utf-8") as fh:
        scope = json.load(fh)

    problems = check(scope)
    payload = {"scope_file": args.scope_file, "tasks": len(scope.get("tasks") or []),
               "problems": problems, "ok": not problems}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"queue_check: tasks={payload['tasks']} problems={len(problems)}")
        for p in problems:
            print("  FAIL", p)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
