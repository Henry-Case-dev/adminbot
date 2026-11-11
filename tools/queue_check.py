#!/usr/bin/env python3
"""Durable-queue completeness lint for plans/progress_scope.json.

Not a second queue: it validates the queue metadata that already lives in the
scope file. Registration of an epic is complete only when the task has a
queue position, a priority and a dependency list, and any "fork" position is
documented with concrete options and the decision it needs.

Exit code 0 = queue metadata complete, 1 = defects found.

Usage: python tools/queue_check.py [--scope-file plans/progress_scope.json] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys

DONE = {"VERIFIED", "DONE", "DONE_WITH_GAPS"}
POSITION_RE = re.compile(
    r"^(active|release_pending|blocked_external|unranked:fork:[a-z0-9][a-z0-9-]*"
    r"|after:[a-z0-9][a-z0-9._-]*(,[a-z0-9][a-z0-9._-]*)*"
    r"|immediately_after:[a-z0-9][a-z0-9._-]*|immediately_before:[a-z0-9][a-z0-9._-]*)$"
)
PRIORITY = {"P0", "P1", "P2", "fork"}
FORK_FIELDS = ("question", "options", "decision_needed", "why_not_derived")


def check(scope: dict) -> list[str]:
    problems: list[str] = []
    tasks = scope.get("tasks") or []
    ids = {t.get("id") for t in tasks if t.get("id")}

    schema = scope.get("queue_schema")
    if not schema:
        problems.append("scope: queue_schema missing (queue grammar is not declared)")

    for t in tasks:
        tid = t.get("id") or "<no-id>"
        status = str(t.get("status") or "").upper()
        if status in DONE:
            continue

        pos = t.get("queue_position")
        prio = t.get("priority")
        blocked = t.get("blocked_by")

        if not pos:
            problems.append(f"{tid}: queue_position missing")
        elif not POSITION_RE.match(str(pos)):
            problems.append(f"{tid}: queue_position '{pos}' violates the declared grammar")

        if not prio:
            problems.append(f"{tid}: priority missing")
        elif str(prio) not in PRIORITY:
            problems.append(f"{tid}: priority '{prio}' not in {sorted(PRIORITY)}")

        if blocked is None:
            problems.append(f"{tid}: blocked_by missing (use [] when there are no task-level blockers)")
        elif not isinstance(blocked, list):
            problems.append(f"{tid}: blocked_by must be a list")
        else:
            for dep in blocked:
                base = str(dep).split(":")[0]
                if base not in ids:
                    problems.append(f"{tid}: blocked_by references unknown task '{dep}'")

        if isinstance(pos, str):
            if pos.startswith("after:") or pos.startswith("immediately_after:") or pos.startswith("immediately_before:"):
                refs = pos.split(":", 1)[1].split(",")
                for ref in refs:
                    if ref not in ids:
                        problems.append(f"{tid}: queue_position references unknown task '{ref}'")
                    if ref == tid:
                        problems.append(f"{tid}: queue_position references itself")
            if pos.startswith("unranked:fork:"):
                fork = t.get("queue_fork") or {}
                for field in FORK_FIELDS:
                    if not fork.get(field):
                        problems.append(f"{tid}: fork position without queue_fork.{field}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-file", default="plans/progress_scope.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.scope_file, encoding="utf-8") as fh:
        scope = json.load(fh)

    problems = check(scope)
    payload = {
        "scope_file": args.scope_file,
        "tasks": len(scope.get("tasks") or []),
        "problems": problems,
        "ok": not problems,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"queue_check: tasks={payload['tasks']} problems={len(problems)}")
        for p in problems:
            print("  FAIL", p)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
