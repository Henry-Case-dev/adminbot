# -*- coding: utf-8 -*-
"""ACCEPTANCE-96e — добить возможный остаток основной волны: anchor добора
occasional (mid не сохранился в волновой записи; кандидаты 1166670/1166671/
1166672 между последним ответом frequent (1166669) и ответом добора (1166673)).

Безопасная идентификация: Bot API editMessageCaption выполняется ТОЛЬКО для
сообщений, отправленных самим ботом; сообщения пользователей не изменяются
(ошибка «message can't be edited»). Своё сообщение (anchor) удаляется.
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
CANDIDATES = (1166670, 1166671, 1166672)
SYNTH_USER = 990002001
BOT_ID = 8802473181
OUT = "/tmp/accept96e/evidence/cleanup-hedge-anchor.json"


def out(tag, text):
    print("ACC96E %s | %s" % (tag, text), flush=True)


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
    result = {"chat_id": CHAT, "candidates": list(CANDIDATES), "probes": [],
              "deleted": []}
    try:
        me = await bot.get_me()
        if int(me.id) != BOT_ID:
            out("ABORT", "unexpected bot id")
            return 5
        for mid in CANDIDATES:
            rec = {"mid": mid}
            smart = q("SELECT user_id FROM smart_messages WHERE chat_id=? AND "
                      "tg_message_id=?", (CHAT, mid))
            rec["smart_user_ids"] = [r["user_id"] for r in smart]
            try:
                await bot.edit_message_caption(
                    chat_id=CHAT, message_id=mid,
                    caption="🧪 ACC96 anchor identification probe")
                rec["edit_caption"] = "ok"
                rec["owner"] = "bot"
            except Exception as exc:  # noqa: BLE001
                rec["edit_caption"] = "%s: %s" % (type(exc).__name__,
                                                  str(exc)[:180])
                rec["owner"] = "not_bot"
            result["probes"].append(rec)
            out("PROBE", "mid=%s owner=%s (%s)"
                % (mid, rec["owner"], rec["edit_caption"][:100]))
        for rec in result["probes"]:
            if rec.get("owner") != "bot":
                continue
            try:
                await bot.delete_message(chat_id=CHAT,
                                         message_id=int(rec["mid"]))
                rec["delete"] = "deleted"
                result["deleted"].append(rec["mid"])
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                rec["delete"] = ("already_deleted"
                                 if "not found" in text.lower() else "error")
                rec["delete_detail"] = text[:160]
            out("DEL", "%s %s" % (rec["mid"], rec.get("delete")))
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
    # синтетические строки для удалённых
    removed = 0
    try:
        con = sqlite3.connect(db_path(), timeout=20)
        con.execute("PRAGMA busy_timeout=20000")
        for mid in result["deleted"]:
            con.execute("DELETE FROM bot_replies WHERE chat_id=? AND "
                        "tg_message_id=?", (CHAT, mid))
            con.execute("DELETE FROM bot_reply_parents WHERE chat_id=? AND "
                        "tg_message_id=?", (CHAT, mid))
        con.commit()
        con.close()
    except Exception as exc:  # noqa: BLE001
        result["rows_error"] = type(exc).__name__
    result["residual"] = [
        {"mid": mid,
         "smart": q("SELECT tg_message_id FROM smart_messages WHERE chat_id=? "
                    "AND tg_message_id=?", (CHAT, mid)),
         "replies": q("SELECT tg_message_id FROM bot_replies WHERE chat_id=? "
                      "AND tg_message_id=?", (CHAT, mid)),
         "parents": q("SELECT tg_message_id FROM bot_reply_parents WHERE "
                      "chat_id=? AND tg_message_id=?", (CHAT, mid))}
        for mid in result["deleted"]]
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(result, ensure_ascii=False, indent=1))
    out("DONE", "bot_owned=%s deleted=%s"
        % ([r["mid"] for r in result["probes"] if r.get("owner") == "bot"],
           result["deleted"]))
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC96E FATAL | %s: %s" % (type(exc).__name__,
                                         str(exc)[:300]), flush=True)
        traceback.print_exc()
    print("ACC96E RC=%d" % rc, flush=True)
    os._exit(rc)
