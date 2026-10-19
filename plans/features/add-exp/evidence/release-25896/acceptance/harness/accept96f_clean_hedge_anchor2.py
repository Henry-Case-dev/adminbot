# -*- coding: utf-8 -*-
"""ACCEPTANCE-96f — идентификация anchor добора (mid 1166670) через
editMessageText: бот правит только СВОИ сообщения (у чужого — «message can't
be edited», без изменений). Своё (текстовый anchor) — удаляем.
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
MID = 1166670
BOT_ID = 8802473181
OUT = "/tmp/accept96f/evidence/cleanup-hedge-anchor2.json"


def out(tag, text):
    print("ACC96F %s | %s" % (tag, text), flush=True)


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
            await bot.edit_message_text(
                chat_id=CHAT, message_id=MID,
                text="🧪 ACC96 anchor identification probe")
            result["edit_text"] = "ok"
            result["owner"] = "bot"
        except Exception as exc:  # noqa: BLE001
            result["edit_text"] = "%s: %s" % (type(exc).__name__,
                                              str(exc)[:180])
            result["owner"] = "not_bot"
        out("PROBE", "owner=%s (%s)" % (result["owner"],
                                        result["edit_text"][:120]))
        if result["owner"] == "bot":
            try:
                await bot.delete_message(chat_id=CHAT, message_id=MID)
                result["delete"] = "deleted"
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                result["delete"] = ("already_deleted"
                                    if "not found" in text.lower() else "error")
                result["delete_detail"] = text[:160]
            out("DEL", result.get("delete"))
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
    removed = {"bot_replies": 0, "bot_reply_parents": 0}
    try:
        con = sqlite3.connect(db_path(), timeout=20)
        con.execute("PRAGMA busy_timeout=20000")
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
    out("DONE", json.dumps(result, ensure_ascii=False)[:300])
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC96F FATAL | %s: %s" % (type(exc).__name__,
                                         str(exc)[:300]), flush=True)
        traceback.print_exc()
    print("ACC96F RC=%d" % rc, flush=True)
    os._exit(rc)
