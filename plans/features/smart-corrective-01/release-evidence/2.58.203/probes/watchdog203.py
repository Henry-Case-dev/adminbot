# -*- coding: utf-8 -*-
"""Read-only watchdog snapshot from the production SQLite (mca_* tables)."""
from __future__ import annotations

import json
import sqlite3
import sys
import time

DB = "/var/www/admin_bot/local_database.db"


def load(con, sql, args=()):
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    except Exception as exc:
        return [{"error": f"{exc.__class__.__name__}: {exc}"}]


def main(minutes: int) -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=1")
    now = int(time.time())
    since = now - minutes * 60
    try:
        by_name = load(con,
                       "SELECT event_name, outcome, count(*) AS n "
                       "FROM mca_events WHERE ts >= ? AND event_name LIKE 'WATCHDOG%' "
                       "GROUP BY event_name, outcome ORDER BY event_name, outcome",
                       (since,))
        sweeps = load(con,
                      "SELECT ts, outcome, usage_json FROM mca_events "
                      "WHERE ts >= ? AND event_name = 'WATCHDOG_SWEEP' "
                      "ORDER BY id DESC LIMIT 400", (since,))
        takeovers = load(con,
                         "SELECT ts, outcome, reason_code, entity_ids, usage_json "
                         "FROM mca_events WHERE ts >= ? "
                         "AND event_name = 'WATCHDOG_TAKEOVER' ORDER BY id DESC LIMIT 50",
                         (since,))
        failures = load(con,
                        "SELECT ts, event_name, outcome, reason_code, error_json "
                        "FROM mca_events WHERE ts >= ? AND ("
                        " event_name = 'WATCHDOG_INCIDENT_FAILURE' OR outcome = 'failed'"
                        ") AND event_name LIKE 'WATCHDOG%' ORDER BY id DESC LIMIT 50",
                        (since,))
        recoveries = load(con,
                          "SELECT ts, event_name, outcome, usage_json FROM mca_events "
                          "WHERE ts >= ? AND event_name LIKE 'WATCHDOG%' "
                          "AND (outcome LIKE '%recover%' OR usage_json LIKE '%recovered\":%')"
                          " ORDER BY id DESC LIMIT 50", (since,))

        agg = {"sweeps": len(sweeps), "takeover_events": len(takeovers),
               "incident_failures": len(failures),
               "recovery_events": len(recoveries)}
        keys = ("discovered", "attempted", "recovered", "failed", "no_change",
                "overdue", "queued", "heartbeat_only")
        totals = {k: 0 for k in keys}
        incident = {}
        reconcile = {}
        running_contract = {}
        last_sweep = None
        for row in sweeps:
            try:
                usage = json.loads(row["usage_json"] or "{}")
            except Exception:
                continue
            for k in keys:
                try:
                    totals[k] += int(usage.get(k) or 0)
                except Exception:
                    pass

            def bump(target: dict, value) -> None:
                if isinstance(value, dict):
                    for kk, vv in value.items():
                        try:
                            target[kk] = target.get(kk, 0) + int(vv or 0)
                        except Exception:
                            pass
                elif isinstance(value, (int, float)):
                    target["_scalar"] = target.get("_scalar", 0) + int(value)

            bump(incident, usage.get("incidents"))
            bump(reconcile, usage.get("reconcile"))
            bump(running_contract, usage.get("running_contract"))
            if last_sweep is None:
                last_sweep = {"ts": row["ts"], "outcome": row["outcome"],
                              "usage_keys": sorted(usage.keys()),
                              "usage": {k: usage.get(k) for k in keys},
                              "incidents": usage.get("incidents"),
                              "reconcile": usage.get("reconcile"),
                              "running_contract": usage.get("running_contract"),
                              "raw_usage": usage}
        incidents = load(con,
                         "SELECT incident_id, fingerprint, severity, title, stage, "
                         "       first_ts, last_ts, repeat_count, resolved_at "
                         "FROM mca_incidents ORDER BY last_ts DESC LIMIT 20")
        incidents_count = load(con, "SELECT count(*) AS n, "
                               "sum(CASE WHEN resolved_at IS NULL THEN 1 ELSE 0 END) AS open "
                               "FROM mca_incidents")
        return {
            "now": now,
            "window_minutes": minutes,
            "window_since": since,
            "events_by_name": by_name,
            "aggregate": agg,
            "sweep_totals": totals,
            "incident_outcomes": incident,
            "reconcile": reconcile,
            "running_contract": running_contract,
            "last_sweep": last_sweep,
            "takeovers": takeovers,
            "incident_failures": failures,
            "recoveries": recoveries,
            "incidents_total": incidents_count,
            "incidents_recent": incidents,
        }
    finally:
        con.close()


if __name__ == "__main__":
    minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    data = main(minutes)
    dest = sys.argv[2] if len(sys.argv) > 2 else "/tmp/watchdog203.json"
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: data[k] for k in
                      ("window_minutes", "aggregate", "sweep_totals",
                       "incident_outcomes", "reconcile", "incidents_total")},
                     ensure_ascii=False, indent=1))
