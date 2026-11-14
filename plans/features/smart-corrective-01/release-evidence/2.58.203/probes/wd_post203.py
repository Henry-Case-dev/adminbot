# -*- coding: utf-8 -*-
"""Post-deploy watchdog window (only events created at/after the release)."""
from __future__ import annotations

import json
import sqlite3
import sys
import time

DB = "/var/www/admin_bot/local_database.db"
DEPLOY_EPOCH = 1794682609          # 2026-11-14T18:56:49Z (service start)


def main() -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=1")
    now = int(time.time())
    try:
        def q(sql, args=()):
            return [dict(r) for r in con.execute(sql, args).fetchall()]

        series = q(
            "SELECT ts, outcome, usage_json FROM mca_events "
            "WHERE event_name='WATCHDOG_SWEEP' AND ts >= ? ORDER BY ts",
            (DEPLOY_EPOCH,))
        rows = []
        for r in series:
            try:
                u = json.loads(r["usage_json"] or "{}")
            except Exception:
                u = {}
            rows.append({"ts": r["ts"], "outcome": r["outcome"], "u": u})

        def s(path, default=0):
            total = 0
            for row in rows:
                cur = row["u"]
                for part in path.split("."):
                    cur = cur.get(part) if isinstance(cur, dict) else None
                    if cur is None:
                        break
                if isinstance(cur, (int, float)):
                    total += int(cur)
            return total

        def mx(path):
            best = 0
            for row in rows:
                cur = row["u"]
                for part in path.split("."):
                    cur = cur.get(part) if isinstance(cur, dict) else None
                    if cur is None:
                        break
                if isinstance(cur, (int, float)):
                    best = max(best, int(cur))
            return best

        incidents_after = q(
            "SELECT incident_id, fingerprint, severity, stage, first_ts, last_ts, "
            "       resolved_at FROM mca_incidents WHERE first_ts >= ? "
            "ORDER BY first_ts", (DEPLOY_EPOCH,))
        incidents_totals = q(
            "SELECT count(*) AS n, sum(CASE WHEN resolved_at IS NULL THEN 1 ELSE 0 END) AS open "
            "FROM mca_incidents")
        events = q(
            "SELECT event_name, outcome, count(*) AS n FROM mca_events "
            "WHERE ts >= ? AND event_name LIKE 'WATCHDOG%' "
            "GROUP BY event_name, outcome", (DEPLOY_EPOCH,))
        return {
            "generated_at": now,
            "deploy_epoch": DEPLOY_EPOCH,
            "window_seconds": now - DEPLOY_EPOCH,
            "sweeps": len(rows),
            "first_sweep_ts": rows[0]["ts"] if rows else None,
            "last_sweep_ts": rows[-1]["ts"] if rows else None,
            "sweep_outcomes": {o: sum(1 for r in rows if r["outcome"] == o)
                               for o in {r["outcome"] for r in rows}},
            "totals": {
                "incidents.created": s("incident.created"),
                "incidents.updated": s("incident.updated"),
                "incidents.reopened": s("incident.reopened"),
                "incidents.failed": s("incident.failed"),
                "takeover.discovered": s("takeover.discovered"),
                "takeover.attempted": s("takeover.attempted"),
                "takeover.recovered": s("takeover.recovered"),
                "takeover.failed": s("takeover.failed"),
                "takeover.no_change": s("takeover.no_change"),
                "reconcile.checked": s("reconcile.checked"),
                "reconcile.resolved": s("reconcile.resolved"),
                "reconcile.pending": s("reconcile.pending"),
                "reconcile.failed": s("reconcile.failed"),
                "stale": s("stale"),
                "progress_stalled": s("progress_stalled"),
            },
            "maxima": {
                "overdue.running": mx("overdue.running"),
                "overdue.queued": mx("overdue.queued"),
                "queued.overdue": mx("queued.overdue"),
                "queued.hang": mx("queued.hang"),
                "queued.scheduled_retry": mx("queued.scheduled_retry"),
                "running_contract.heartbeat_only": mx("running_contract.heartbeat_only"),
                "running_contract.deadline_bounded": mx("running_contract.deadline_bounded"),
            },
            "events": events,
            "incidents_created_after_deploy": incidents_after,
            "incidents_totals_all_time": incidents_totals,
            "last_sweep_usage": rows[-1]["u"] if rows else None,
        }
    finally:
        con.close()


if __name__ == "__main__":
    data = main()
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/watchdog_post_window203.json"
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: data[k] for k in
                      ("sweeps", "first_sweep_ts", "last_sweep_ts",
                       "sweep_outcomes", "totals", "maxima", "events",
                       "incidents_created_after_deploy",
                       "incidents_totals_all_time")},
                     ensure_ascii=False, indent=1))
