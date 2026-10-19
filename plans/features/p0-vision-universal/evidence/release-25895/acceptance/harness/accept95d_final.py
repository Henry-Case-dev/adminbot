# -*- coding: utf-8 -*-
"""ACCEPTANCE-95d — final verification + cleanup completion.

1. Verify the 16 deleted wave messages (read-only).
2. Complete the cleanup: remove the wave's bot_replies / bot_reply_parents
   rows (the first cleanup pass hit an OperationalError on the DB block).
3. Final read-only state: analyses/jobs/events/user_version + the disclosed
   residual (the 95a gen1 photo without a saved mid).

Output: /tmp/accept95/evidence/final95d.json
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
SYNTH_USER = 990002001
BOT_ID = 8802473181
EVID = "/tmp/accept95/evidence"
DELETED_MIDS = [1166463, 1166464, 1166471, 1166482, 1166483, 1166485,
                1166486, 1166487, 1166489, 1166491, 1166495, 1166496,
                1166497, 1166499, 1166500, 1166501]


def load_base():
    spec = importlib.util.spec_from_file_location("accept95_base",
                                                  "/tmp/accept95_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def out(tag, text):
    print("ACC95D %s | %s" % (tag, text), flush=True)


async def main() -> int:
    base = load_base()
    await base.bootstrap()
    res = {"phase": "final95d",
           "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    # 1) verify deletions (read-only)
    try:
        placeholders = ",".join("?" * len(DELETED_MIDS))
        res["residual_smart_messages"] = await base.sqlite_fetch(
            "SELECT tg_message_id mid, user_id FROM smart_messages WHERE "
            "chat_id=? AND tg_message_id IN (%s)" % placeholders,
            (WORK_CHAT, *DELETED_MIDS))
        res["residual_bot_replies"] = await base.sqlite_fetch(
            "SELECT tg_message_id mid FROM bot_replies WHERE chat_id=? AND "
            "tg_message_id IN (%s)" % placeholders,
            (WORK_CHAT, *DELETED_MIDS))
        res["residual_bot_reply_parents"] = await base.sqlite_fetch(
            "SELECT tg_message_id mid, parent_tg_message_id parent FROM "
            "bot_reply_parents WHERE chat_id=? AND tg_message_id IN (%s)"
            % placeholders, (WORK_CHAT, *DELETED_MIDS))
    except Exception as exc:  # noqa: BLE001
        res["verify_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:150])
    # 2) cleanup completion: remove our bot_replies / parents rows
    removed = {"bot_replies": 0, "bot_reply_parents": 0}
    try:
        placeholders = ",".join("?" * len(DELETED_MIDS))
        cur = await base.CTX.db.db.execute(
            "DELETE FROM bot_replies WHERE chat_id=? AND tg_message_id IN "
            "(%s)" % placeholders, (WORK_CHAT, *DELETED_MIDS))
        removed["bot_replies"] = int(cur.rowcount or 0)
        await base.CTX.db.db.commit()
    except Exception as exc:  # noqa: BLE001
        removed["bot_replies_error"] = "%s: %s" % (type(exc).__name__,
                                                   str(exc)[:120])
    try:
        placeholders = ",".join("?" * len(DELETED_MIDS))
        cur = await base.CTX.db.db.execute(
            "DELETE FROM bot_reply_parents WHERE chat_id=? AND "
            "tg_message_id IN (%s)" % placeholders,
            (WORK_CHAT, *DELETED_MIDS))
        removed["bot_reply_parents"] = int(cur.rowcount or 0)
        await base.CTX.db.db.commit()
    except Exception as exc:  # noqa: BLE001
        removed["bot_reply_parents_error"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:120])
    res["cleanup_completion"] = removed
    # 3) final state (read-only)
    try:
        res["analyses_by_status"] = await base.sqlite_fetch(
            "SELECT status, COUNT(*) n FROM mca_media_analyses "
            "GROUP BY status ORDER BY n DESC")
        res["analyses_running"] = await base.sqlite_fetch(
            "SELECT id, asset_id, status, revision, created_at, updated_at "
            "FROM mca_media_analyses WHERE status='running' ORDER BY id")
        res["jobs_recent"] = await base.sqlite_fetch(
            "SELECT job_id, owner, kind, status, reason_code, attempt, "
            "created_at, updated_at FROM task_jobs WHERE kind='vision.media' "
            "ORDER BY created_at DESC LIMIT 6")
        res["user_version"] = await base.sqlite_fetch("PRAGMA user_version")
        res["mca_events_recent"] = await base.sqlite_fetch(
            "SELECT ts, event_name, outcome, level, stage, reason_code FROM "
            "mca_events ORDER BY ts DESC LIMIT 12")
        res["mca_errors_since_wave"] = await base.sqlite_fetch(
            "SELECT COUNT(*) n FROM mca_events WHERE ts >= 1792417638 AND "
            "level IN ('ERROR','CRITICAL')")
        # residual disclosure: which mids in the wave window are NOT ours and
        # NOT real users' (the uncaptioned 95a gen1 photo candidates)
        res["wave_window_unattributed"] = await base.sqlite_fetch(
            "SELECT tg_message_id mid FROM smart_messages WHERE chat_id=? "
            "AND tg_message_id BETWEEN 1166463 AND 1166501", (WORK_CHAT,))
    except Exception as exc:  # noqa: BLE001
        res["state_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:150])
    # 4) verify again after the cleanup completion
    try:
        placeholders = ",".join("?" * len(DELETED_MIDS))
        res["after_bot_replies"] = await base.sqlite_fetch(
            "SELECT COUNT(*) n FROM bot_replies WHERE chat_id=? AND "
            "tg_message_id IN (%s)" % placeholders, (WORK_CHAT,
                                                     *DELETED_MIDS))
        res["after_bot_reply_parents"] = await base.sqlite_fetch(
            "SELECT COUNT(*) n FROM bot_reply_parents WHERE chat_id=? AND "
            "tg_message_id IN (%s)" % placeholders, (WORK_CHAT,
                                                     *DELETED_MIDS))
    except Exception as exc:  # noqa: BLE001
        res["after_error"] = type(exc).__name__
    res["ok"] = True
    base.save("final95d.json", res)
    out("FINAL", "residual_smart=%s residual_rep=%s removed=%s"
        % (len(res.get("residual_smart_messages") or []),
           len(res.get("residual_bot_replies") or []),
           json.dumps(removed, ensure_ascii=False)))
    await base.close_all()
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC95D FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC95D RC=%d" % rc, flush=True)
    os._exit(rc)
