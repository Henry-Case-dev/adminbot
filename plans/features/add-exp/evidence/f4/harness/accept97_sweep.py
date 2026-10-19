# -*- coding: utf-8 -*-
"""ACCEPTANCE-97 sweep — remove ALL test bot messages of the doubled run.

The second attempt accidentally started two harness processes (systemd-run unit
+ nohup fallback); the cleanup register covered only one of them. This sweep
deletes every bot reply and anchor created in the wave window, with a hard
safety gate: if the owner wrote anything in the window, the sweep refuses.
"""
from __future__ import annotations

import asyncio
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

CHAT_A = -1002661910336
CHAT_B = -1004482340693
WINDOW_START = 1792440030      # 2026-10-19 20:00:30Z
SYNTH_USER = 990002001
EVID = "/tmp/accept97/evidence"


def out(tag, text):
    print("ACC97SWEEP %s | %s" % (tag, text), flush=True)


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


async def main() -> int:
    from aiogram import Bot
    from services.local_bot_api import build_local_api_session
    from config.settings import settings

    report = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
              "window_start": WINDOW_START}
    # safety: no real user messages in the window
    user_rows = q("SELECT chat_id, tg_message_id, user_id, substr(text,1,60) h "
                  "FROM smart_messages WHERE chat_id IN (?,?) AND "
                  "timestamp >= ? AND user_id NOT IN (?, 8802473181) "
                  "ORDER BY tg_message_id", (CHAT_A, CHAT_B, WINDOW_START - 120,
                                             SYNTH_USER))
    report["user_messages_in_window"] = user_rows
    if user_rows:
        report["ok"] = False
        report["abort"] = "real user activity in window — manual review"
        out("ABORT", "real user messages in window: %s" % user_rows[:3])
        with open(os.path.join(EVID, "sweep.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
        return 4

    replies = {}
    for cid in (CHAT_A, CHAT_B):
        replies[str(cid)] = q(
            "SELECT tg_message_id mid FROM bot_replies WHERE chat_id=? AND "
            "last_used_at >= ? ORDER BY tg_message_id", (cid, WINDOW_START))
    parents = {}
    for cid in (CHAT_A, CHAT_B):
        parents[str(cid)] = q(
            "SELECT tg_message_id mid, parent_tg_message_id parent FROM "
            "bot_reply_parents WHERE chat_id=? AND last_used_at >= ?",
            (cid, WINDOW_START))
    delete = {}
    for cid in (CHAT_A, CHAT_B):
        mids = {int(r["mid"]) for r in replies[str(cid)]}
        for p in parents[str(cid)]:
            if int(p["mid"]) in mids and p["parent"]:
                pm = int(p["parent"])
                rows = q("SELECT user_id FROM smart_messages WHERE chat_id=? "
                         "AND tg_message_id=?", (cid, pm))
                if not rows:
                    mids.add(pm)
                else:
                    report.setdefault("blocked_parents", []).append(
                        {"chat": cid, "mid": pm, "rows": rows})
        delete[str(cid)] = sorted(mids)
    report["delete_mids"] = delete
    out("PLAN", "A=%d B=%d" % (len(delete[str(CHAT_A)]),
                               len(delete[str(CHAT_B)])))

    if settings.DOWNLOAD_ENABLED:
        bot = Bot(token=settings.API_TOKEN,
                  session=build_local_api_session(settings.LOCAL_BOT_API_URL))
    else:
        bot = Bot(token=settings.API_TOKEN)
    deleted = []
    try:
        me = await bot.get_me()
        report["bot_id"] = me.id
        for cid in (CHAT_A, CHAT_B):
            for mid in delete[str(cid)]:
                rec = {"chat": cid, "mid": mid}
                try:
                    await bot.delete_message(chat_id=cid, message_id=mid)
                    rec["status"] = "deleted"
                except Exception as exc:  # noqa: BLE001
                    txt = str(exc).lower()
                    rec["status"] = ("already_deleted" if "not found" in txt
                                     else "error")
                    if rec["status"] == "error":
                        rec["error"] = (type(exc).__name__ + ": "
                                        + str(exc))[:160]
                deleted.append(rec)
                out("DEL", "chat=%s %s %s" % (cid, mid, rec["status"]))
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
    report["deleted"] = deleted

    removed = {}
    con = sqlite3.connect(db_path(), timeout=20)
    con.execute("PRAGMA busy_timeout=20000")
    try:
        for cid in (CHAT_A, CHAT_B):
            mids = delete[str(cid)]
            if not mids:
                continue
            ph = ",".join("?" * len(mids))
            cur = con.execute("DELETE FROM bot_replies WHERE chat_id=? AND "
                              "tg_message_id IN (%s)" % ph, (cid, *mids))
            removed["bot_replies_%s" % cid] = int(cur.rowcount or 0)
            cur = con.execute("DELETE FROM bot_reply_parents WHERE chat_id=? "
                              "AND (tg_message_id IN (%s) OR "
                              "parent_tg_message_id IN (%s))"
                              % (ph, ph), (cid, *(mids + mids)))
            removed["bot_reply_parents_%s" % cid] = int(cur.rowcount or 0)
        cur = con.execute("DELETE FROM throttle_state WHERE scope IN "
                          "('direct_chat','direct_silence') AND chat_id IN "
                          "(?,?) AND user_id=?", (CHAT_A, CHAT_B, SYNTH_USER))
        removed["throttle"] = int(cur.rowcount or 0)
        con.commit()
    finally:
        con.close()
    report["synthetic_rows_removed"] = removed

    residual = {}
    for cid in (CHAT_A, CHAT_B):
        rows = q("SELECT tg_message_id FROM bot_replies WHERE chat_id=? AND "
                 "last_used_at >= ?", (cid, WINDOW_START))
        if rows:
            residual[str(cid)] = rows
    report["residual_rows"] = residual
    report["ok"] = (not [d for d in deleted if d["status"] == "error"]
                    and not residual)
    with open(os.path.join(EVID, "sweep.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    out("RESULT", json.dumps({"deleted": len(deleted), "removed": removed,
                              "residual": {k: len(v) for k, v in
                                           residual.items()},
                              "ok": report["ok"]}, ensure_ascii=False))
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC97SWEEP FATAL | %s: %s" % (type(exc).__name__,
                                             str(exc)[:300]), flush=True)
        traceback.print_exc()
    print("ACC97SWEEP RC=%d" % rc, flush=True)
    os._exit(rc)
