# -*- coding: utf-8 -*-
"""ACCEPTANCE-94 — read-only SQLite probe (journal since T0 = 2.58.94 deploy)."""
import json
import sqlite3

T0 = 1792397900          # 2026-10-19 08:18:20 UTC (deploy 2.58.94)
WORK_CHAT = -1002661910336
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
    out["vision_jobs_since_t0"] = q(
        "SELECT job_id, status, reason_code, attempt, max_attempts, "
        "created_at, updated_at FROM task_jobs WHERE kind LIKE 'vision%' "
        "AND created_at >= ? ORDER BY created_at", (T0,))
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
    out["analyses_total"] = q("SELECT COUNT(*) n FROM mca_media_analyses")[0]
    out["analyses_by_status"] = q(
        "SELECT status, COUNT(*) n FROM mca_media_analyses GROUP BY status")
    out["analyses_recent"] = q(
        "SELECT id, asset_id, status, revision, analyzer_model, "
        "substr(visual_description,1,200) desc_head, completed_at "
        "FROM mca_media_analyses ORDER BY id DESC LIMIT 5")
    out["assets_total"] = q("SELECT COUNT(*) n FROM mca_media_assets")[0]
except Exception as exc:  # noqa: BLE001
    out["analyses_error"] = type(exc).__name__
try:
    out["throttle_image_freq"] = q(
        "SELECT scope, chat_id, user_id, burst_left, last_ts "
        "FROM throttle_state WHERE scope='image_freq' AND chat_id=? "
        "ORDER BY user_id", (WORK_CHAT,))
except Exception as exc:  # noqa: BLE001
    out["throttle_error"] = type(exc).__name__
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
