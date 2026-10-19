# -*- coding: utf-8 -*-
"""ADD-EXP Ф0 cleanup — delete the F0 test messages + synthetic rows.

Owner rule: test messages are removed after the check. Safety gate: a mid is
never deleted unless it is a recorded bot reply / the synthetic user row;
real user messages are never touched.

Input: /tmp/addexp_f0/cleanup_spec.json (delete_mids/smart_rows/window)
Output: /tmp/addexp_f0/evidence/cleanup-register.json
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

WORK_CHAT = -1002661910336
SYNTH_USER = 990002001
EXPECTED_BOT_ID = 8802473181
REGISTER_IN = "/tmp/addexp_f0/cleanup_spec.json"
REGISTER_OUT = "/tmp/addexp_f0/evidence/cleanup-register.json"


def out(tag, text):
    print("F0CLEAN %s | %s" % (tag, text), flush=True)


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


def short(value, n=80):
    return " ".join(str(value or "").split())[:n]


async def main() -> int:
    from config.settings import settings
    from aiogram import Bot
    from services.local_bot_api import build_local_api_session

    try:
        os.umask(0o022)
    except Exception:
        pass
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    with open(REGISTER_IN, "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    delete_mids = sorted({int(m) for m in spec.get("delete_mids") or []})
    smart_rows = sorted({int(m) for m in spec.get("smart_rows") or []})
    win = spec.get("window") or {}
    lo, hi = int(win.get("lo") or 0), int(win.get("hi") or 0)
    out("SPEC", "delete=%d smart_rows=%d window=%s..%s"
        % (len(delete_mids), len(smart_rows), lo, hi))

    incoming = q(
        "SELECT tg_message_id mid, user_id, author_name, "
        "substr(text,1,90) head FROM smart_messages WHERE chat_id=? AND "
        "tg_message_id BETWEEN ? AND ? ORDER BY tg_message_id",
        (WORK_CHAT, lo, hi))
    botrep = q(
        "SELECT tg_message_id mid, substr(text,1,90) head, last_used_at "
        "FROM bot_replies WHERE chat_id=? AND tg_message_id BETWEEN ? AND ? "
        "ORDER BY tg_message_id", (WORK_CHAT, lo, hi))
    out("INV", "smart_messages=%d bot_replies=%d" % (len(incoming),
                                                     len(botrep)))

    inc_by_mid = {r["mid"]: r for r in incoming}
    rep_by_mid = {r["mid"]: r for r in botrep}

    blocked = []
    for mid in delete_mids:
        row = inc_by_mid.get(mid)
        if row is not None and row["user_id"] not in (SYNTH_USER,
                                                      EXPECTED_BOT_ID) \
                and mid not in rep_by_mid:
            blocked.append({"mid": mid, "user_id": row["user_id"],
                            "head": short(row["head"]),
                            "reason": "real user message"})
    if blocked:
        out("ABORT", "delete set overlaps user messages: %s"
            % [b["mid"] for b in blocked])
        return 5

    if bool(getattr(settings, "DOWNLOAD_ENABLED", False)):
        bot = Bot(token=settings.API_TOKEN,
                  session=build_local_api_session(
                      settings.LOCAL_BOT_API_URL))
    else:
        bot = Bot(token=settings.API_TOKEN)
    deleted = []
    try:
        me = await bot.get_me()
        out("BOT", "id=%s username=%s" % (me.id, me.username))
        if int(me.id) != EXPECTED_BOT_ID:
            out("ABORT", "unexpected bot id")
            return 5
        for mid in delete_mids:
            rec = {"mid": mid}
            row = inc_by_mid.get(mid)
            if row is not None:
                rec["author"] = row["author_name"]
                rec["head"] = short(row["head"])
            if mid in rep_by_mid:
                rec["bot_reply_head"] = short(rep_by_mid[mid]["head"])
            try:
                await bot.delete_message(chat_id=WORK_CHAT, message_id=mid)
                rec["status"] = "deleted"
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                if "not found" in text.lower():
                    rec["status"] = "already_deleted"
                else:
                    rec["status"] = "error"
                    rec["error"] = (type(exc).__name__ + ": " + text)[:160]
            deleted.append(rec)
            out("DEL", "%s %s" % (mid, rec["status"]))
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass

    db_removed = []
    rep_removed = []
    thr_removed = 0
    try:
        con = sqlite3.connect(db_path(), timeout=20)
        con.execute("PRAGMA busy_timeout=20000")
        for mid in sorted(set(delete_mids) | set(smart_rows)):
            rows = con.execute(
                "SELECT rowid rid, user_id FROM smart_messages "
                "WHERE chat_id=? AND tg_message_id=?", (WORK_CHAT, mid)
            ).fetchall()
            for rid, uid in rows:
                if uid not in (SYNTH_USER, EXPECTED_BOT_ID):
                    continue
                try:
                    con.execute("DELETE FROM smart_messages_fts WHERE rowid=?",
                                (rid,))
                except Exception:
                    pass
                con.execute("DELETE FROM smart_messages WHERE rowid=?", (rid,))
                db_removed.append({"mid": mid, "rowid": rid})
            brows = con.execute(
                "SELECT rowid rid FROM bot_replies WHERE chat_id=? AND "
                "tg_message_id=?", (WORK_CHAT, mid)).fetchall()
            for (rid,) in brows:
                con.execute("DELETE FROM bot_replies WHERE rowid=?", (rid,))
                rep_removed.append({"mid": mid, "rowid": rid})
        cur = con.execute(
            "DELETE FROM throttle_state WHERE scope IN "
            "('direct_chat','direct_silence') AND chat_id=? AND user_id=?",
            (WORK_CHAT, SYNTH_USER))
        thr_removed = cur.rowcount
        con.commit()
        con.close()
    except Exception as exc:  # noqa: BLE001
        out("DBROWS", "cleanup failed: %s" % type(exc).__name__)
    out("DBROWS", "smart_removed=%d bot_replies_removed=%d throttle_removed=%d"
        % (len(db_removed), len(rep_removed), thr_removed))

    after = q(
        "SELECT tg_message_id mid, user_id FROM smart_messages "
        "WHERE chat_id=? AND tg_message_id BETWEEN ? AND ?",
        (WORK_CHAT, lo, hi))
    residual_rows = [r for r in after if r["mid"] in set(delete_mids)]
    after_rep = q(
        "SELECT tg_message_id mid FROM bot_replies WHERE chat_id=? AND "
        "tg_message_id BETWEEN ? AND ?", (WORK_CHAT, lo, hi))
    residual_replies = [r for r in after_rep if r["mid"] in set(delete_mids)]
    failed = [r["mid"] for r in deleted if r["status"] == "error"]
    verification = {
        "delete_attempts": len(deleted),
        "deleted_now": sum(r["status"] == "deleted" for r in deleted),
        "already_deleted": sum(r["status"] == "already_deleted"
                               for r in deleted),
        "failed": failed,
        "residual_smart_rows_for_deleted": residual_rows,
        "residual_bot_replies_for_deleted": residual_replies,
        "synthetic_rows_removed": db_removed,
        "bot_replies_removed": rep_removed,
        "throttle_rows_removed": thr_removed,
        "window": {"lo": lo, "hi": hi},
    }
    register = {
        "generated_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "chat_id": WORK_CHAT,
        "method": ("Telegram Bot API deleteMessage via the deployed bot "
                   "(local session); safety gate vs real user messages; "
                   "synthetic smart_messages/bot_replies/throttle rows "
                   "removed"),
        "delete_mids": delete_mids,
        "deleted": deleted,
        "diagnostics_inventory": {"smart_messages_window": incoming,
                                  "bot_replies_window": botrep},
        "verification": verification,
    }
    os.makedirs(os.path.dirname(REGISTER_OUT), exist_ok=True)
    with open(REGISTER_OUT, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(register, ensure_ascii=False, indent=1,
                            default=str))
    out("VERIFY", json.dumps(verification, ensure_ascii=False)[:600])
    out("DONE", "deleted=%d residual_rows=%d residual_replies=%d failed=%s"
        % (verification["deleted_now"], len(residual_rows),
           len(residual_replies), failed))
    return 0 if not failed and not residual_rows and not residual_replies \
        else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("F0CLEAN FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("F0CLEAN RC=%d" % rc, flush=True)
    os._exit(rc)
