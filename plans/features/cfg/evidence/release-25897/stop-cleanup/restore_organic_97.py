# -*- coding: utf-8 -*-
"""Restore the 9 organic bot messages that lane STOP-ACCEPTANCE-97 removed.

Source of truth: `mca_bot_outputs` keeps the delivered text and the parent ref
of every bot message, so the content can be re-sent verbatim.

DRY BY DEFAULT. It sends only with RESTORE_SEND=1 and only if the ledger row is
still marked as the deleted mid (a small local state file prevents a second
restore of the same mid).

Writes /tmp/cleanup_all/restore-organic.json.
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
MIDS = [1164703, 1165152, 1166038, 1166041, 1166048, 1166051, 1166053,
        1166056, 1166058]
OUT = "/tmp/cleanup_all/restore-organic.json"
SEND = os.environ.get("RESTORE_SEND", "") == "1"


def out(tag, text=""):
    print("RESTORE97 %s | %s" % (tag, text), flush=True)


def db_path():
    from config.settings import settings
    path = str(getattr(settings, "DB_PATH", "") or "local_database.db")
    if not os.path.isabs(path):
        path = os.path.join(APP, path)
    return path


def load_rows():
    con = sqlite3.connect("file:%s?mode=ro" % db_path(), uri=True,
                          timeout=20)
    con.row_factory = sqlite3.Row
    try:
        rows = []
        for mid in MIDS:
            row = con.execute(
                "SELECT tg_message_id mid, sent_at, output_kind, "
                "parent_message_ref, content_text FROM mca_bot_outputs "
                "WHERE chat_id=? AND tg_message_id=?", (CHAT_A, mid)).fetchone()
            if row:
                rows.append(dict(row))
            else:
                out("MISSING", str(mid))
        return rows
    finally:
        con.close()


async def main() -> int:
    from config.settings import settings
    from aiogram import Bot
    from aiogram.exceptions import TelegramBadRequest

    rows = load_rows()
    out("PLAN", "rows=%d send=%s" % (len(rows), SEND))

    session = None
    if bool(getattr(settings, "DOWNLOAD_ENABLED", False)):
        from services.local_bot_api import build_local_api_session
        session = build_local_api_session(settings.LOCAL_BOT_API_URL)
    bot = Bot(token=settings.API_TOKEN, session=session) if session else \
        Bot(token=settings.API_TOKEN)

    result = {"generated_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                             time.gmtime()),
              "mode": "send" if SEND else "dry", "items": []}
    try:
        previous = {}
        if os.path.exists(OUT):
            try:
                previous = {i["old_mid"]: i for i in
                            json.load(open(OUT, encoding="utf-8"))["items"]}
            except Exception:  # noqa: BLE001
                previous = {}
        for row in rows:
            mid = row["mid"]
            text = row["content_text"] or ""
            pref = row.get("parent_message_ref") or ""
            parent = int(pref[3:]) if pref.startswith("tg:") else None
            item = {"old_mid": mid, "kind": row["output_kind"],
                    "parent_mid": parent, "text_len": len(text),
                    "text": text}
            if mid in previous and previous[mid].get("new_mid"):
                item["new_mid"] = previous[mid]["new_mid"]
                item["skipped"] = "already restored"
                result["items"].append(item)
                continue
            if not SEND:
                item["would_send"] = True
                result["items"].append(item)
                out("DRY", "mid=%s parent=%s len=%d" % (mid, parent, len(text)))
                continue
            kwargs = {"chat_id": CHAT_A, "text": text}
            if parent:
                kwargs["reply_to_message_id"] = parent
                kwargs["allow_sending_without_reply"] = True
            try:
                msg = await bot.send_message(**kwargs)
                item["new_mid"] = msg.message_id
                out("SENT", "old=%s new=%s parent=%s"
                    % (mid, msg.message_id, parent))
            except TelegramBadRequest as exc:
                item["error"] = str(exc)[:200]
                out("FAIL", "old=%s %s" % (mid, str(exc)[:160]))
            result["items"].append(item)
            await asyncio.sleep(1.0)
    finally:
        try:
            await bot.session.close()
        except Exception:  # noqa: BLE001
            pass
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("RESTORE97_FATAL %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("RESTORE97_RC=%d" % rc, flush=True)
    os._exit(rc)
