# -*- coding: utf-8 -*-
"""ACCEPTANCE-97 prep — remove the aborted-attempt leftovers, restore chat A.

The first wave attempt died hard after 4 occasional turns (launcher/session
issue, see diag). It left: chat-scope `occasional` on A, 4 bot answers and one
anchor message. This script removes exactly those messages (text-verified
against the recorded answers), their SQLite rows, and returns A to the global
state (pre-run: `source=global`, no chat document).

Safety gates:
  * only messages present in `bot_replies` with a text prefix recorded in the
    aborted `live.out` are deleted;
  * the anchor is deleted only if its id is a recorded parent of those replies
    and it is NOT present in `smart_messages` (i.e. not a user message).
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
SINCE = 1792439610          # 2026-10-19 19:53:30Z (first aborted turn)
EVID = "/tmp/accept97/evidence"
ANSWER_PREFIXES = [
    "В восемь утра в понедельник",
    "На роутере сзади наклейка",
    "Половина не готова",
    "Курица с рисом",
]


def out(tag, text):
    print("ACC97PREP %s | %s" % (tag, text), flush=True)


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


def make_init_data() -> str:
    import hashlib
    import hmac
    import urllib.parse
    from config.settings import settings
    token = settings.API_TOKEN or ""
    fields = {"auth_date": str(int(time.time())),
              "query_id": "AAHaccept97prep",
              "user": json.dumps({"id": 5885953495, "first_name": "Accept97",
                                  "username": "accept97"},
                                 separators=(",", ":"))}
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


async def main() -> int:
    import httpx
    from aiogram import Bot
    from services.local_bot_api import build_local_api_session
    from config.settings import settings

    report = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
              "since_epoch": SINCE}
    replies = q("SELECT tg_message_id mid, substr(text,1,120) head, "
                "last_used_at FROM bot_replies WHERE chat_id=? AND "
                "last_used_at >= ? ORDER BY tg_message_id", (CHAT_A, SINCE))
    report["bot_replies_window"] = replies
    parents = q("SELECT tg_message_id mid, parent_tg_message_id parent, "
                "last_used_at FROM bot_reply_parents WHERE chat_id=? AND "
                "last_used_at >= ?", (CHAT_A, SINCE))
    report["bot_reply_parents_window"] = parents
    matched = [r for r in replies
               if any(str(r["head"]).startswith(p) for p in ANSWER_PREFIXES)]
    report["matched_by_prefix"] = [r["mid"] for r in matched]
    anchors = {int(p["parent"]) for p in parents
               if int(p["mid"]) in {int(r["mid"]) for r in matched}
               and p["parent"]}
    report["anchor_candidates"] = sorted(anchors)

    # safety: anchors must not be user messages
    safe_anchors = []
    for mid in sorted(anchors):
        rows = q("SELECT user_id FROM smart_messages WHERE chat_id=? AND "
                 "tg_message_id=?", (CHAT_A, mid))
        if rows:
            report.setdefault("anchor_blocked", []).append(
                {"mid": mid, "rows": rows})
            continue
        safe_anchors.append(mid)
    delete_mids = sorted({int(r["mid"]) for r in matched} | set(safe_anchors))
    report["delete_mids"] = delete_mids

    if settings.DOWNLOAD_ENABLED:
        bot = Bot(token=settings.API_TOKEN,
                  session=build_local_api_session(settings.LOCAL_BOT_API_URL))
    else:
        bot = Bot(token=settings.API_TOKEN)
    deleted = []
    try:
        me = await bot.get_me()
        report["bot_id"] = me.id
        for mid in delete_mids:
            rec = {"mid": mid}
            try:
                await bot.delete_message(chat_id=CHAT_A, message_id=mid)
                rec["status"] = "deleted"
            except Exception as exc:  # noqa: BLE001
                text = str(exc).lower()
                rec["status"] = ("already_deleted" if "not found" in text
                                 else "error")
                if rec["status"] == "error":
                    rec["error"] = (type(exc).__name__ + ": "
                                    + str(exc))[:160]
            deleted.append(rec)
            out("DEL", "%s %s" % (mid, rec["status"]))
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
    report["deleted"] = deleted

    # sqlite rows of the deleted synthetic messages
    removed = {}
    con = sqlite3.connect(db_path(), timeout=20)
    con.execute("PRAGMA busy_timeout=20000")
    try:
        if delete_mids:
            ph = ",".join("?" * len(delete_mids))
            cur = con.execute("DELETE FROM bot_replies WHERE chat_id=? AND "
                              "tg_message_id IN (%s)" % ph,
                              (CHAT_A, *delete_mids))
            removed["bot_replies"] = int(cur.rowcount or 0)
            cur = con.execute("DELETE FROM bot_reply_parents WHERE chat_id=? "
                              "AND (tg_message_id IN (%s) OR "
                              "parent_tg_message_id IN (%s))"
                              % (ph, ph), (CHAT_A, *(delete_mids + delete_mids)))
            removed["bot_reply_parents"] = int(cur.rowcount or 0)
            cur = con.execute("DELETE FROM throttle_state WHERE scope IN "
                              "('direct_chat','direct_silence') AND chat_id=? "
                              "AND user_id=?", (CHAT_A, 990002001))
            removed["throttle"] = int(cur.rowcount or 0)
        con.commit()
    finally:
        con.close()
    report["synthetic_rows_removed"] = removed

    # reset chat A/B chat-scope expression to global (pre-run state)
    init = make_init_data()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=60.0) as c:
        hdr = {"X-Telegram-Init-Data": init}
        reset = {}
        for label, cid in (("a", CHAT_A), ("b", CHAT_B)):
            r = await c.post("/api/speech/expression/reset-chat",
                             headers={**hdr, "X-Chat-Id": str(cid)})
            reset[label] = {"http": r.status_code, "body": r.text[:300]}
        views = {}
        for label, cid in (("a", CHAT_A), ("b", CHAT_B)):
            for attempt in range(3):
                r = await c.get("/api/speech/expression",
                                headers={**hdr, "X-Chat-Id": str(cid)})
                try:
                    body = r.json()
                except Exception:
                    body = {}
                views[label] = {
                    "http": r.status_code,
                    "profanity": ((body.get("effective") or {}).get(
                        "profanity") or {}),
                    "chat_present": body.get("chat_present"),
                    "inheritance": body.get("inheritance"),
                }
                if views[label]["chat_present"] is False:
                    break
                await asyncio.sleep(15)
    report["reset"] = reset
    report["views"] = views

    residual = {}
    for mid in delete_mids:
        rows = q("SELECT tg_message_id FROM bot_replies WHERE chat_id=? AND "
                 "tg_message_id=?", (CHAT_A, mid))
        if rows:
            residual[mid] = rows
    report["residual_rows"] = residual
    a_prof = views["a"]["profanity"] or {}
    report["ok"] = (not [d for d in deleted if d["status"] == "error"]
                    and not residual
                    and str(a_prof.get("source")) == "global"
                    and views["a"].get("chat_present") is False)
    os.makedirs(EVID, exist_ok=True)
    with open(os.path.join(EVID, "prep.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    out("RESULT", json.dumps({"deleted": len(deleted),
                              "anchors": safe_anchors,
                              "removed": removed,
                              "a": views["a"], "b": views["b"],
                              "ok": report["ok"]}, ensure_ascii=False)[:600])
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC97PREP FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("ACC97PREP RC=%d" % rc, flush=True)
    os._exit(rc)
