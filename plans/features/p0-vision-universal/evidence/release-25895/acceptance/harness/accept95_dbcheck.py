# -*- coding: utf-8 -*-
"""ACCEPTANCE-95 — read-only SQLite probe (journal wave). No writes.

Prints compact JSON: analyses by status, the running/orphan rows, recent
vision jobs, vision_adapt/image_postgen_vision/vision_media events since the
deploy T0, image reservation day counters (PG-free part), user_version.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config.settings import settings  # noqa: E402


def db_path():
    path = str(getattr(settings, "DB_PATH", "") or "local_database.db")
    if not os.path.isabs(path):
        path = os.path.join(APP, path)
    return path


con = sqlite3.connect(db_path(), timeout=20)
con.row_factory = sqlite3.Row
con.execute("PRAGMA busy_timeout=20000")


def q(sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


res = {}
res["user_version"] = q("PRAGMA user_version")
res["analyses_by_status"] = q(
    "SELECT status, COUNT(*) n FROM mca_media_analyses GROUP BY status "
    "ORDER BY n DESC")
res["analyses_running"] = q(
    "SELECT id, asset_id, status, revision, analyzer_model, created_at, "
    "updated_at FROM mca_media_analyses WHERE status='running' ORDER BY id")
res["jobs_vision_recent"] = q(
    "SELECT job_id, owner, kind, status, reason_code, attempt, created_at, "
    "updated_at FROM task_jobs WHERE kind IN ('vision.media','vision.backfill') "
    "ORDER BY created_at DESC LIMIT 12")
res["events_recent"] = q(
    "SELECT ts, event_name, outcome, level, stage, reason_code, chat_id "
    "FROM mca_events WHERE event_name IN "
    "('vision_adapt','image_postgen_vision','vision_media') "
    "ORDER BY ts DESC LIMIT 40")
res["mca_errors_today"] = q(
    "SELECT COUNT(*) n FROM mca_events WHERE level IN ('ERROR','CRITICAL') "
    "AND ts >= strftime('%s','now') - 86400")
res["image_reservations_sqlite_free"] = q(
    "SELECT COUNT(*) n FROM mca_media_assets WHERE chat_id=-1002661910336")
print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
con.close()
