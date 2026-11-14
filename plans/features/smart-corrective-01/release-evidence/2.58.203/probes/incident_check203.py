# -*- coding: utf-8 -*-
"""Latest watchdog/incident events after the release (read-only)."""
from __future__ import annotations

import json
import sqlite3

DB = "/var/www/admin_bot/local_database.db"
DEPLOY_EPOCH = 1794682609
FOCUS = 1794683600          # 19:13:20Z, around the new INCIDENT


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=1")
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT id, ts, level, event_name, outcome, reason_code, component, "
            "       stage, entity_ids, usage_json FROM mca_events "
            "WHERE ts >= ? AND (event_name LIKE 'WATCHDOG%' OR event_name = 'INCIDENT') "
            "ORDER BY id", (DEPLOY_EPOCH,))]
        print("EVENTS_SINCE_DEPLOY", len(rows))
        for r in rows:
            if r["event_name"] == "WATCHDOG_SWEEP":
                try:
                    u = json.loads(r["usage_json"] or "{}")
                except Exception:
                    u = {}
                if (u.get("takeover") or {}).get("discovered") or \
                        (u.get("incidents") or 0) or \
                        (u.get("incident") or {}).get("created"):
                    print("SWEEP", r["ts"], json.dumps(u, ensure_ascii=False)[:900])
                continue
            print(r["event_name"], r["ts"], r["outcome"], r["reason_code"],
                  "stage=%s" % r["stage"], "entity=%s" % r["entity_ids"],
                  (r["usage_json"] or "")[:900])
        print("--- incidents touched after deploy ---")
        for r in con.execute(
                "SELECT incident_id, fingerprint, severity, stage, title, first_ts, "
                "       last_ts, repeat_count, resolved_at, resolution_evidence "
                "FROM mca_incidents WHERE last_ts >= ? ORDER BY last_ts", (DEPLOY_EPOCH,)):
            print(dict(r))
        print("--- totals ---")
        for r in con.execute("SELECT count(*) n, sum(CASE WHEN resolved_at IS NULL "
                            "THEN 1 ELSE 0 END) open FROM mca_incidents"):
            print(dict(r))
    finally:
        con.close()


if __name__ == "__main__":
    main()
