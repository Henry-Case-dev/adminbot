# -*- coding: utf-8 -*-
"""ACCEPTANCE-96d — удалить единственное пропущенное тестовое сообщение
(ответ на цитату-пробу follow-up, mid 1166725) + синтетические строки.

Safety: mid 1166725 — сообщение бота из RecordingBot follow-up (записано в
quote-off.json); строк реальных пользователей для него нет.
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

CHAT = -1002661910336
MID = 1166725
SYNTH_USER = 990002001
BOT_ID = 8802473181
OUT = "/tmp/accept96d/evidence/cleanup-quote.json"


def out(tag, text):
    print("ACC96D %s | %s" % (tag, text), flush=True)


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
    from config.settings import settings
    from aiogram import Bot
    from services.local_bot_api import build_local_api_session

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    smart = q("SELECT tg_message_id, user_id, substr(text,1,80) head FROM "
              "smart_messages WHERE chat_id=? AND tg_message_id=?",
              (CHAT, MID))
    replies = q("SELECT tg_message_id, substr(text,1,80) head FROM "
                "bot_replies WHERE chat_id=? AND tg_message_id=?",
                (CHAT, MID))
    parents = q("SELECT tg_message_id, parent_tg_message_id FROM "
                "bot_reply_parents WHERE chat_id=? AND tg_message_id=?",
                (CHAT, MID))
    out("INV", "smart=%s replies=%s parents=%s"
        % (len(smart), len(replies), len(parents)))
    blocked = [r for r in smart if r["user_id"] not in (SYNTH_USER, BOT_ID)
               and not replies]
    if blocked:
        out("ABORT", "mid принадлежит реальному пользователю — не трогаем")
        return 5
    if bool(getattr(settings, "DOWNLOAD_ENABLED", False)):
        bot = Bot(token=settings.API_TOKEN,
                  session=build_local_api_session(
                      settings.LOCAL_BOT_API_URL))
    else:
        bot = Bot(token=settings.API_TOKEN)
    result = {"mid": MID, "chat_id": CHAT}
    try:
        me = await bot.get_me()
        if int(me.id) != BOT_ID:
            out("ABORT", "unexpected bot id")
            return 5
        try:
            await bot.delete_message(chat_id=CHAT, message_id=MID)
            result["delete"] = "deleted"
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            result["delete"] = ("already_deleted"
                                if "not found" in text.lower() else "error")
            result["delete_detail"] = "%s: %s" % (type(exc).__name__,
                                                  text[:160])
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
    out("DEL", result["delete"])
    removed = {"bot_replies": 0, "bot_reply_parents": 0,
               "smart_messages": 0}
    try:
        con = sqlite3.connect(db_path(), timeout=20)
        con.execute("PRAGMA busy_timeout=20000")
        for uid_row in con.execute(
                "SELECT rowid rid, user_id FROM smart_messages WHERE "
                "chat_id=? AND tg_message_id=?", (CHAT, MID)).fetchall():
            rid, uid = uid_row
            if uid not in (SYNTH_USER, BOT_ID):
                continue
            try:
                con.execute("DELETE FROM smart_messages_fts WHERE rowid=?",
                            (rid,))
            except Exception:
                pass
            con.execute("DELETE FROM smart_messages WHERE rowid=?", (rid,))
            removed["smart_messages"] += 1
        cur = con.execute("DELETE FROM bot_replies WHERE chat_id=? AND "
                          "tg_message_id=?", (CHAT, MID))
        removed["bot_replies"] = int(cur.rowcount or 0)
        cur = con.execute("DELETE FROM bot_reply_parents WHERE chat_id=? AND "
                          "tg_message_id=?", (CHAT, MID))
        removed["bot_reply_parents"] = int(cur.rowcount or 0)
        con.commit()
        con.close()
    except Exception as exc:  # noqa: BLE001
        result["rows_error"] = type(exc).__name__
    result["rows_removed"] = removed
    result["residual"] = {
        "smart": q("SELECT tg_message_id FROM smart_messages WHERE chat_id=? "
                   "AND tg_message_id=?", (CHAT, MID)),
        "replies": q("SELECT tg_message_id FROM bot_replies WHERE chat_id=? "
                     "AND tg_message_id=?", (CHAT, MID)),
        "parents": q("SELECT tg_message_id FROM bot_reply_parents WHERE "
                     "chat_id=? AND tg_message_id=?", (CHAT, MID)),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(result, ensure_ascii=False, indent=1))
    out("DONE", json.dumps({"delete": result["delete"],
                            "rows": removed,
                            "residual": sum(len(v) for v in
                                            result["residual"].values())},
                           ensure_ascii=False))
    return 0 if result["delete"] in ("deleted", "already_deleted") and sum(
        len(v) for v in result["residual"].values()) == 0 else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC96D FATAL | %s: %s" % (type(exc).__name__,
                                         str(exc)[:300]), flush=True)
        traceback.print_exc()
    print("ACC96D RC=%d" % rc, flush=True)
    os._exit(rc)
