# -*- coding: utf-8 -*-
"""ACCEPTANCE-94 cleanup completion (one foreground run).

The first cleanup deleted all 9 test messages via Bot API but its DB block
failed with OperationalError (message not captured then). This run:
  * removes residual bot_replies / synthetic smart_messages rows for the
    deleted test mids (with per-step error capture),
  * verifies residual == 0,
  * dumps the single ERROR-level mca_event since the wave start (for the
    release report).

Output: /tmp/accept94/evidence/cleanup-register-2.json
"""
from __future__ import annotations

import json
import os
import sqlite3
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
EXPECTED_BOT_ID = 8802473181
WAVE_START = 1792400925
MIDS = [1166064, 1166066, 1166165, 1166167, 1166168, 1166169, 1166170,
        1166177, 1166178]


def out(tag, text):
    print("CLEAN94B %s | %s" % (tag, text), flush=True)


def db_path():
    from config.settings import settings
    path = str(getattr(settings, "DB_PATH", "") or "local_database.db")
    if not os.path.isabs(path):
        path = os.path.join(APP, path)
    return path


def q(sql, args=()):
    con = sqlite3.connect(db_path(), timeout=20)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=20000")
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def main() -> int:
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    result = {"phase": "cleanup-completion", "mids": MIDS}
    errors = []
    removed_smart = []
    removed_replies = []
    # 1) synthetic smart_messages rows for test mids (never real users)
    for attempt in range(3):
        try:
            con = sqlite3.connect(db_path(), timeout=30)
            con.execute("PRAGMA busy_timeout=30000")
            for mid in MIDS:
                rows = con.execute(
                    "SELECT rowid rid, user_id FROM smart_messages "
                    "WHERE chat_id=? AND tg_message_id=?",
                    (WORK_CHAT, mid)).fetchall()
                for rid, uid in rows:
                    if uid not in (SYNTH_USER, EXPECTED_BOT_ID):
                        continue
                    try:
                        con.execute(
                            "DELETE FROM smart_messages_fts WHERE rowid=?",
                            (rid,))
                    except Exception as exc:  # noqa: BLE001
                        errors.append("fts mid=%s: %s" % (mid,
                                                          str(exc)[:120]))
                    con.execute("DELETE FROM smart_messages WHERE rowid=?",
                                (rid,))
                    removed_smart.append({"mid": mid, "rowid": rid})
                rep = con.execute(
                    "SELECT rowid rid FROM bot_replies WHERE chat_id=? AND "
                    "tg_message_id=?", (WORK_CHAT, mid)).fetchall()
                for (rid,) in rep:
                    con.execute("DELETE FROM bot_replies WHERE rowid=?",
                                (rid,))
                    removed_replies.append({"mid": mid, "rowid": rid})
            con.commit()
            con.close()
            break
        except Exception as exc:  # noqa: BLE001
            errors.append("db attempt %d: %s: %s" % (
                attempt + 1, type(exc).__name__, str(exc)[:200]))
            try:
                con.close()
            except Exception:
                pass
            time.sleep(3)
    # 2) residual verification
    residual_smart = q(
        "SELECT tg_message_id mid, user_id FROM smart_messages "
        "WHERE chat_id=? AND tg_message_id IN (%s)"
        % ",".join(str(m) for m in MIDS), (WORK_CHAT,))
    residual_replies = q(
        "SELECT tg_message_id mid FROM bot_replies "
        "WHERE chat_id=? AND tg_message_id IN (%s)"
        % ",".join(str(m) for m in MIDS), (WORK_CHAT,))
    residual_synth = [r for r in residual_smart
                      if r.get("user_id") in (SYNTH_USER, EXPECTED_BOT_ID)]
    # 3) the single ERROR-level mca_event since the wave start
    try:
        err_events = q(
            "SELECT ts, event_name, outcome, reason_code, level, component, "
            "substr(error_json,1,220) ej FROM mca_events WHERE ts >= ? "
            "AND level IN ('ERROR','CRITICAL') ORDER BY ts DESC LIMIT 5",
            (WAVE_START,))
    except Exception as exc:  # noqa: BLE001
        err_events = [{"error": type(exc).__name__}]
    result.update({
        "generated_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "removed_smart_rows": removed_smart,
        "removed_bot_replies": removed_replies,
        "db_errors": errors,
        "residual_smart_rows": residual_smart,
        "residual_synth_smart_rows": residual_synth,
        "residual_bot_replies": residual_replies,
        "mca_error_events_since_wave": err_events,
        "ok": (not residual_synth and not residual_replies),
    })
    os.makedirs("/tmp/accept94/evidence", exist_ok=True)
    with open("/tmp/accept94/evidence/cleanup-register-2.json", "w",
              encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1, default=str)
    out("RESULT", json.dumps({
        "removed_smart": len(removed_smart),
        "removed_replies": len(removed_replies),
        "db_errors": errors[:3],
        "residual_synth": residual_synth,
        "residual_replies": residual_replies,
        "mca_err_n": len(err_events)}, ensure_ascii=False)[:700])
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("CLEAN94B FATAL | %s: %s" % (type(exc).__name__,
                                           str(exc)[:300]), flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("CLEAN94B RC=%d" % rc, flush=True)
    os._exit(rc)
