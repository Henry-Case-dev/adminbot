# -*- coding: utf-8 -*-
"""ACCEPTANCE-95c — read-only probe (no writes, no paid calls).

1. bot_replies / bot_reply_parents window inventory (recover the wave-95a/95b
   bot message ids for the cleanup register: answers + their anchors).
2. The pre-existing 'running' analysis row (d): asset a32e0331 + its job/events.
3. Current analyses/jobs/events state + the smart_messages window (safety:
   which mids belong to real users).
4. user_version.

Output: /tmp/accept95/evidence/probe95c.json
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORK_CHAT = -1002661910336
EVID = "/tmp/accept95/evidence"
ORPHAN_ASSET = "a32e03310af2c39fcd6a44d57972ca26"
WIN_LO, WIN_HI = 1166455, 1166600


def load_base():
    spec = importlib.util.spec_from_file_location("accept95_base",
                                                  "/tmp/accept95_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def out(tag, text):
    print("ACC95C %s | %s" % (tag, text), flush=True)


async def main() -> int:
    base = load_base()
    await base.bootstrap()
    res = {"phase": "probe95c",
           "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    try:
        res["bot_replies_window"] = await base.sqlite_fetch(
            "SELECT tg_message_id mid, substr(text,1,70) head, last_used_at "
            "FROM bot_replies WHERE chat_id=? AND tg_message_id BETWEEN ? "
            "AND ? ORDER BY tg_message_id", (WORK_CHAT, WIN_LO, WIN_HI))
        res["bot_reply_parents_window"] = await base.sqlite_fetch(
            "SELECT tg_message_id mid, parent_tg_message_id parent, "
            "last_used_at FROM bot_reply_parents WHERE chat_id=? AND "
            "tg_message_id BETWEEN ? AND ? ORDER BY tg_message_id",
            (WORK_CHAT, WIN_LO, WIN_HI))
        res["smart_messages_window"] = await base.sqlite_fetch(
            "SELECT tg_message_id mid, user_id, media_type, substr(text,1,40) "
            "head FROM smart_messages WHERE chat_id=? AND tg_message_id "
            "BETWEEN ? AND ? ORDER BY tg_message_id",
            (WORK_CHAT, WIN_LO, WIN_HI))
        res["analyses_running"] = await base.sqlite_fetch(
            "SELECT id, asset_id, status, revision, created_at, updated_at "
            "FROM mca_media_analyses WHERE status='running' ORDER BY id")
        res["orphan_asset"] = await base.sqlite_fetch(
            "SELECT asset_id, message_key, chat_id, tg_message_id, asset_kind, "
            "mime, byte_size, width, height FROM mca_media_assets WHERE "
            "asset_id=?", (ORPHAN_ASSET,))
        res["orphan_analyses"] = await base.sqlite_fetch(
            "SELECT id, status, revision, analyzer_model, created_at, "
            "updated_at, error_reason FROM mca_media_analyses WHERE asset_id=? "
            "ORDER BY id", (ORPHAN_ASSET,))
        res["orphan_jobs"] = await base.sqlite_fetch(
            "SELECT job_id, status, reason_code, attempt, created_at, "
            "updated_at, heartbeat_at FROM task_jobs WHERE coalesce_key=? "
            "ORDER BY created_at", ("vision:asset:%s" % ORPHAN_ASSET,))
        res["orphan_events"] = await base.sqlite_fetch(
            "SELECT ts, event_name, outcome, level, stage, reason_code "
            "FROM mca_events WHERE operation_id=? ORDER BY ts",
            (ORPHAN_ASSET,))
        res["user_version"] = await base.sqlite_fetch("PRAGMA user_version")
        res["jobs_recent"] = await base.sqlite_fetch(
            "SELECT job_id, owner, kind, status, reason_code, attempt, "
            "created_at, updated_at FROM task_jobs WHERE kind='vision.media' "
            "ORDER BY created_at DESC LIMIT 8")
    except Exception as exc:  # noqa: BLE001
        res["sqlite_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    base.save("probe95c.json", res)
    out("PROBE", "saved: bot_replies=%s parents=%s running=%s"
        % (len(res.get("bot_replies_window") or []),
           len(res.get("bot_reply_parents_window") or []),
           len(res.get("analyses_running") or [])))
    await base.close_all()
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC95C FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC95C RC=%d" % rc, flush=True)
    os._exit(rc)
