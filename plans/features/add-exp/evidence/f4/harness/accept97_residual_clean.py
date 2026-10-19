# -*- coding: utf-8 -*-
"""ACCEPTANCE-97 residual pass: remove the last synthetic turns of the doubled
attempt and re-verify.

Discriminator (deterministic): a service bot-reply whose `bot_reply_parents`
parent is ANOTHER BOT MESSAGE can only come from the harness trick (synthetic
user update reusing the previous bot message id). Real replies always have a
real user message as parent. Legit replies to the owner's messages are kept.
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
WINDOW_START = 1792440030
OUT = "/tmp/accept97/residual-clean.json"


def out(tag, text):
    print("ACC97RES %s | %s" % (tag, text), flush=True)


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

    rep = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    targets = {}
    for cid in (CHAT_A, CHAT_B):
        replies = q("SELECT tg_message_id mid, substr(text,1,160) head, "
                    "last_used_at FROM bot_replies WHERE chat_id=? AND "
                    "last_used_at >= ?", (cid, WINDOW_START))
        bot_mids = {int(r["mid"]) for r in replies}
        par = q("SELECT tg_message_id mid, parent_tg_message_id parent FROM "
                "bot_reply_parents WHERE chat_id=? AND last_used_at >= ?",
                (cid, WINDOW_START))
        test = sorted({int(p["mid"]) for p in par
                       if p["parent"] and int(p["parent"]) in bot_mids})
        ids = {int(r["mid"]): r for r in replies}
        targets[str(cid)] = {
            "test": [{"mid": m, "head": (ids.get(m) or {}).get("head")}
                     for m in test],
            "kept": [{"mid": int(r["mid"]), "head": r["head"]}
                     for r in replies if int(r["mid"]) not in test],
        }
        out("PLAN", "chat=%s test=%s kept=%s"
            % (cid, [t["mid"] for t in targets[str(cid)]["test"]],
               [k["mid"] for k in targets[str(cid)]["kept"]]))
    rep["plan"] = targets

    if settings.DOWNLOAD_ENABLED:
        bot = Bot(token=settings.API_TOKEN,
                  session=build_local_api_session(settings.LOCAL_BOT_API_URL))
    else:
        bot = Bot(token=settings.API_TOKEN)
    deleted = []
    try:
        for cid in (CHAT_A, CHAT_B):
            for t in targets[str(cid)]["test"]:
                rec = {"chat": cid, "mid": t["mid"]}
                try:
                    await bot.delete_message(chat_id=cid,
                                             message_id=t["mid"])
                    rec["status"] = "deleted"
                except Exception as exc:  # noqa: BLE001
                    txt = str(exc).lower()
                    rec["status"] = ("already_deleted" if "not found" in txt
                                     else "error")
                    if rec["status"] == "error":
                        rec["error"] = (type(exc).__name__ + ": "
                                        + str(exc))[:160]
                deleted.append(rec)
                out("DEL", "chat=%s %s %s" % (cid, t["mid"], rec["status"]))
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
    rep["deleted"] = deleted

    con = sqlite3.connect(db_path(), timeout=20)
    con.execute("PRAGMA busy_timeout=20000")
    removed = {}
    try:
        for cid in (CHAT_A, CHAT_B):
            mids = [t["mid"] for t in targets[str(cid)]["test"]]
            if not mids:
                continue
            ph = ",".join("?" * len(mids))
            cur = con.execute("DELETE FROM bot_replies WHERE chat_id=? AND "
                              "tg_message_id IN (%s)" % ph, (cid, *mids))
            removed["replies_%s" % cid] = int(cur.rowcount or 0)
            cur = con.execute("DELETE FROM bot_reply_parents WHERE chat_id=? "
                              "AND tg_message_id IN (%s)" % ph,
                              (cid, *mids))
            removed["parents_%s" % cid] = int(cur.rowcount or 0)
        con.commit()
    finally:
        con.close()
    rep["removed"] = removed

    # verify: no bot reply whose parent is a bot message remains in the window
    after = {}
    for cid in (CHAT_A, CHAT_B):
        replies = q("SELECT tg_message_id mid FROM bot_replies WHERE chat_id=? "
                    "AND last_used_at >= ?", (cid, WINDOW_START))
        bot_mids = {int(r["mid"]) for r in replies}
        par = q("SELECT tg_message_id mid, parent_tg_message_id parent FROM "
                "bot_reply_parents WHERE chat_id=? AND last_used_at >= ?",
                (cid, WINDOW_START))
        test = sorted({int(p["mid"]) for p in par
                       if p["parent"] and int(p["parent"]) in bot_mids})
        after[str(cid)] = {"replies": len(replies), "test_left": test,
                           "kept": sorted(bot_mids - set(test))}
    rep["after"] = after
    rep["ok"] = (not [d for d in deleted if d["status"] == "error"]
                 and not after[str(CHAT_A)]["test_left"]
                 and not after[str(CHAT_B)]["test_left"])
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=str)
    out("RESULT", json.dumps({"deleted": len(deleted), "removed": removed,
                              "after": after, "ok": rep["ok"]},
                             ensure_ascii=False)[:600])
    return 0 if rep["ok"] else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC97RES FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("ACC97RES RC=%d" % rc, flush=True)
    os._exit(rc)
