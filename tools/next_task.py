#!/usr/bin/env python3
"""Select the next executable task from the durable queue.

Reads plans/progress_scope.json and applies the same admission rules the
orchestrator uses when choosing work: an open task is executable when its
execution_state allows starting/resuming and every blocked_by dependency is
already VERIFIED/DONE. Returns the lowest queue_position among them.

This is a selector over the existing queue, not a second queue.
Exit 0 with the chosen task; exit 1 when nothing is executable.
"""
from __future__ import annotations

import argparse
import json
import sys

DONE = {"VERIFIED", "DONE", "DONE_WITH_GAPS"}
RUNNABLE_STATES = {
    "queued",
    "not_started",
    "paused_with_progress",
    "paused_with_branch",
    "in_review_without_assignment",
}
NOT_RUNNABLE_STATES = {
    "active_assignment",     # already running elsewhere
    "release_pending",       # waits for a release slot, not a build slot
    "waiting_external",      # real external event
    "awaiting_dependency",   # blocked_by not satisfied yet
    "awaiting_architecture", # design/decision not landed
    "amendment",             # executes inside its parent epics
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-file", default="plans/progress_scope.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    scope = json.load(open(args.scope_file, encoding="utf-8"))
    tasks = [t for t in scope.get("tasks") or [] if str(t.get("status") or "").upper() not in DONE]
    by_id = {t.get("id"): t for t in tasks}

    def deps_done(t):
        return all(str(by_id.get(d, {}).get("status", "")).upper() in DONE for d in (t.get("blocked_by") or []))

    ready, skipped = [], []
    for t in sorted(tasks, key=lambda x: x.get("queue_position") or 10 ** 6):
        state = t.get("execution_state") or "queued"
        if state in NOT_RUNNABLE_STATES:
            skipped.append((t.get("id"), t.get("queue_position"), state, "state not runnable"))
            continue
        if not deps_done(t):
            skipped.append((t.get("id"), t.get("queue_position"), state, "dependency open"))
            continue
        ready.append(t)

    payload = {
        "next": ready[0].get("id") if ready else None,
        "next_position": ready[0].get("queue_position") if ready else None,
        "next_priority": ready[0].get("priority") if ready else None,
        "ready": [(t.get("id"), t.get("queue_position"), t.get("priority")) for t in ready],
        "skipped": skipped,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if ready:
            t = ready[0]
            print(f"NEXT: {t.get('id')} (position {t.get('queue_position')}, {t.get('priority')}, "
                  f"{t.get('execution_state')})")
        else:
            print("NEXT: none — nothing is runnable right now")
        for tid, pos, state, why in skipped[:12]:
            print(f"  skip {pos:>3} {tid:<40} {state:<24} {why}")
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
