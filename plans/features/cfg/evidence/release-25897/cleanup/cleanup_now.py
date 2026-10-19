# -*- coding: utf-8 -*-
"""Delete test messages immediately after a check (reusable, safety-gated).

Owner rule (2026-10-20): every test message is deleted right after the check
that used it, not only at the end of the acceptance run.

Usage (on the prod host, from /var/www/admin_bot):
    ./venv/bin/python cleanup_now.py --spec /tmp/accept97/check-now.json \
        --register /tmp/accept97/evidence/cleanup-now.json

Spec formats accepted:
    {"chat_id": -100..., "mids": [123, 124]}
    {"delete_mids": {"-100...": [123, 124], ...}, "bot_id": 8802473181}

Safety gate per mid:
  * a bot_replies row must exist (it is a bot answer), and
  * if bot_reply_parents has a row, the parent must be a bot/synthetic message;
    a real-user parent means a normal conversation reply -> skipped.
  * smart_messages rows are removed only for user_id in (bot_id, synth_user).

This file is durable evidence/tooling. It does not change prod code/settings.
"""
from __future__ import annotations

import argparse
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
except Exception:  # noqa: BLE001
    pass

BOT_ID = 8802473181
SYNTH_USER = 990002001


def db_path() -> str:
    from config.settings import settings
    p = str(getattr(settings, "DB_PATH", "") or "local_database.db")
    return p if os.path.isabs(p) else os.path.join(APP, p)


def norm(s) -> str:
    return " ".join(str(s or "").split())


def load_spec(path: str) -> tuple[int, list[int], int, int]:
    spec = json.load(open(path, encoding="utf-8"))
    bot_id = int(spec.get("bot_id") or BOT_ID)
    synth = int(spec.get("synth_user") or SYNTH_USER)
    if "delete_mids" in spec:
        out = {int(k): [int(x) for x in (v or [])]
               for k, v in (spec.get("delete_mids") or {}).items()}
        if len(out) != 1:
            raise SystemExit("delete_mids must contain exactly one chat")
        chat, mids = next(iter(out.items()))
        return chat, sorted(set(mids)), bot_id, synth
    return (int(spec["chat_id"]), sorted({int(x) for x in spec["mids"]}),
            bot_id, synth)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--register", required=True)
    args = ap.parse_args()

    from config.settings import settings
    from aiogram import Bot
    from services.local_bot_api import build_local_api_session

    chat_id, mids, bot_id, synth = load_spec(args.spec)
    con = sqlite3.connect(db_path(), timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=20000")

    plan, skipped = [], []
    for mid in mids:
        rep = con.execute(
            "SELECT text FROM bot_replies WHERE chat_id=? AND "
            "tg_message_id=?", (chat_id, mid)).fetchone()
        if rep is None:
            skipped.append({"mid": mid, "reason": "no bot_replies row"})
            continue
        parent = con.execute(
            "SELECT parent_tg_message_id FROM bot_reply_parents WHERE "
            "chat_id=? AND tg_message_id=?", (chat_id, mid)).fetchone()
        if parent is not None:
            pu = con.execute(
                "SELECT user_id FROM smart_messages WHERE chat_id=? AND "
                "tg_message_id=?", (chat_id,
                                    parent["parent_tg_message_id"])).fetchall()
            if any(r["user_id"] not in (bot_id, synth) for r in pu):
                skipped.append({"mid": mid,
                                "reason": "real-user parent"})
                continue
        plan.append(mid)

    if bool(getattr(settings, "DOWNLOAD_ENABLED", False)):
        bot = Bot(token=settings.API_TOKEN,
                  session=build_local_api_session(
                      settings.LOCAL_BOT_API_URL))
    else:
        bot = Bot(token=settings.API_TOKEN)
    deleted = []
    try:
        me = await bot.get_me()
        if int(me.id) != bot_id:
            print("ABORT unexpected bot id", me.id)
            return 5
        for mid in plan:
            rec = {"chat_id": chat_id, "mid": mid}
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
                rec["status"] = "deleted"
            except Exception as exc:  # noqa: BLE001
                txt = str(exc)
                rec["status"] = ("already_deleted"
                                 if "not found" in txt.lower() else "error")
                if rec["status"] == "error":
                    rec["error"] = txt[:160]
            deleted.append(rec)
            print("DEL", chat_id, mid, rec["status"], flush=True)
    finally:
        try:
            await bot.session.close()
        except Exception:  # noqa: BLE001
            pass

    ok_mids = [r["mid"] for r in deleted
               if r["status"] in ("deleted", "already_deleted")]
    removed = {"smart": 0, "replies": 0, "parents": 0}
    if ok_mids:
        ph = ",".join("?" * len(ok_mids))
        cur = con.execute(
            "DELETE FROM smart_messages WHERE chat_id=? AND user_id IN (?,?) "
            "AND tg_message_id IN (%s)" % ph,
            (chat_id, bot_id, synth, *ok_mids))
        removed["smart"] = int(cur.rowcount or 0)
        cur = con.execute("DELETE FROM bot_replies WHERE chat_id=? AND "
                          "tg_message_id IN (%s)" % ph,
                          (chat_id, *ok_mids))
        removed["replies"] = int(cur.rowcount or 0)
        cur = con.execute("DELETE FROM bot_reply_parents WHERE chat_id=? AND "
                          "tg_message_id IN (%s)" % ph,
                          (chat_id, *ok_mids))
        removed["parents"] = int(cur.rowcount or 0)
        con.commit()
    residual = {}
    for mid in ok_mids:
        residual[str(mid)] = con.execute(
            "SELECT (SELECT COUNT(*) FROM smart_messages WHERE chat_id=? AND "
            "tg_message_id=?) + (SELECT COUNT(*) FROM bot_replies WHERE "
            "chat_id=? AND tg_message_id=?) + (SELECT COUNT(*) FROM "
            "bot_reply_parents WHERE chat_id=? AND tg_message_id=?)",
            (chat_id, mid, chat_id, mid, chat_id, mid)).fetchone()[0]
    con.close()
    report = {"generated_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                            time.gmtime()),
              "chat_id": chat_id, "plan": plan, "skipped": skipped,
              "deleted": deleted, "removed": removed,
              "residual": residual}
    os.makedirs(os.path.dirname(args.register), exist_ok=True)
    with open(args.register, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("CLEAN_NOW", json.dumps(report, ensure_ascii=False)[:600])
    return 0 if not any(residual.values()) else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("FATAL", type(exc).__name__, str(exc)[:200], flush=True)
        traceback.print_exc()
    print("RC=%d" % rc, flush=True)
    os._exit(rc)
