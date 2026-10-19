# -*- coding: utf-8 -*-
"""ACCEPTANCE-92 — read-only SQLite probe (queue/journal since T0)."""
import json
import sqlite3

T0 = 1792365948
con = sqlite3.connect("file:/var/www/admin_bot/local_database.db?mode=ro",
                      uri=True)
con.row_factory = sqlite3.Row


def q(sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


out = {}
try:
    out["user_version"] = q("PRAGMA user_version")[0]["user_version"]
except Exception as exc:  # noqa: BLE001
    out["user_version_error"] = type(exc).__name__
try:
    out["jobs_since_t0"] = q(
        "SELECT job_id, kind, status, reason_code, attempt, created_at, "
        "updated_at FROM task_jobs WHERE created_at >= ? "
        "ORDER BY created_at", (T0,))
except Exception as exc:  # noqa: BLE001
    out["jobs_error"] = type(exc).__name__
try:
    out["vision_jobs_recent"] = q(
        "SELECT job_id, kind, status, reason_code, attempt, created_at, "
        "updated_at FROM task_jobs WHERE kind LIKE 'vision%' "
        "ORDER BY updated_at DESC LIMIT 15")
except Exception as exc:  # noqa: BLE001
    out["vision_jobs_error"] = type(exc).__name__
try:
    out["events_since_t0"] = q(
        "SELECT event_name, outcome, reason_code, COUNT(*) n, MAX(ts) last "
        "FROM mca_events WHERE ts >= ? GROUP BY 1,2,3 "
        "ORDER BY n DESC LIMIT 30", (T0,))
except Exception as exc:  # noqa: BLE001
    out["events_error"] = type(exc).__name__
try:
    out["mca_errors_since_t0"] = q(
        "SELECT COUNT(*) n FROM mca_events WHERE ts >= ? AND "
        "level IN ('ERROR','CRITICAL')", (T0,))
except Exception as exc:  # noqa: BLE001
    out["mca_errors_error"] = type(exc).__name__
try:
    out["analyses_since_t0"] = q(
        "SELECT COUNT(*) n, "
        "SUM(CASE WHEN status='ready' THEN 1 ELSE 0 END) ready "
        "FROM mca_media_analyses WHERE created_at >= ?", (T0,))
except Exception as exc:  # noqa: BLE001
    out["analyses_error"] = type(exc).__name__
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
