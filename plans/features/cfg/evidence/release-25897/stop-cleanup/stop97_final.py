# -*- coding: utf-8 -*-
"""STOP-ACCEPTANCE-97 — FINAL read-only verification (no deletes, no sends).

Purpose
  1. prove that every *test* message mid (acceptance registers + the 13 mids the
     cleanup lane found alive + F4 registers) is gone from Telegram;
  2. record database residual counters;
  3. dump the ledger rows of the 9 organic bot messages that lane
     STOP-ACCEPTANCE-97 removed by mistake, so they can be restored verbatim.

Nothing is deleted and nothing is sent here: probes only classify
(editMessageReplyMarkup with an empty keyboard is a no-op for a message that has
no inline keyboard; the state is only *read*).

Writes /tmp/cleanup_all/stop-final.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
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

BOT_ID = 8802473181
SYNTH_USER = 990002001
CHAT_A = -1002661910336
CHAT_B = -1004482340693
OUT = "/tmp/cleanup_all/stop-final.json"
PLAN = "/tmp/cleanup_all/delete_plan.json"

# the 13 mids the cleanup lane found alive and deleted at 21:09:44Z
ALIVE_13 = [(CHAT_A, m) for m in
            (1166946, 1166948, 1166949, 1166950, 1166952, 1166954, 1166955,
             1166956, 1166957, 1166958, 1166959, 1166960, 1166961)]
# organic bot messages this lane removed by mistake (must be restorable)
MISTAKE = [1164703, 1165152, 1166038, 1166041, 1166048, 1166051, 1166053,
           1166056, 1166058]


def out(tag, text=""):
    print("STOP97F %s | %s" % (tag, text), flush=True)


def iso(ts=None):
    return time.strftime("%Y-%m-%d %H:%M:%S",
                         time.gmtime(ts if ts else time.time()))


def db_path():
    from config.settings import settings
    path = str(getattr(settings, "DB_PATH", "") or "local_database.db")
    if not os.path.isabs(path):
        path = os.path.join(APP, path)
    return path


def collect_test_mids():
    """Mids that provably belong to acceptance runs (never organic traffic)."""
    cand = {}

    def add(chat, mid, src):
        if chat in (CHAT_A, CHAT_B):
            cand.setdefault((chat, mid), [])
            if src not in cand[(chat, mid)]:
                cand[(chat, mid)].append(src)

    for chat, mid in ALIVE_13:
        add(chat, mid, "cleanup-lane-alive-13")
    if os.path.exists(PLAN):
        try:
            plan = json.load(open(PLAN, encoding="utf-8"))
            for item in plan.get("items", []):
                add(int(item["chat_id"]), int(item["mid"]), "delete_plan")
        except Exception as exc:  # noqa: BLE001
            out("PLAN_ERR", str(exc)[:120])

    # registers that are *delete lists* of the acceptance waves
    for root, _dirs, files in os.walk("/tmp"):
        if not re.search(r"accept97|addexp_f0|cleanup_97", root, re.I):
            continue
        for name in files:
            if not name.endswith(".json"):
                continue
            if not re.search(r"(cleanup|spec|register|mids)", name, re.I):
                continue
            path = os.path.join(root, name)
            try:
                data = json.load(open(path, encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue

            def walk(obj):
                if isinstance(obj, dict):
                    chat = obj.get("chat_id")
                    chat = int(chat) if isinstance(chat, int) else None
                    for key in ("mid", "tg_message_id", "message_id"):
                        val = obj.get(key)
                        if isinstance(val, int) and not isinstance(val, bool):
                            if chat is not None:
                                add(chat, val, path)
                            else:
                                for c in (CHAT_A, CHAT_B):
                                    add(c, val, path)
                    for value in obj.values():
                        walk(value)
                elif isinstance(obj, list):
                    for value in obj:
                        walk(value)

            walk(data)
    return cand


def classify_error(text):
    low = (text or "").lower()
    if "not modified" in low:
        return "owned"
    if any(m in low for m in ("to edit not found", "message not found",
                              "message to delete not found")):
        return "absent"
    if "can't be edited" in low or "can't be modified" in low:
        return "not_owned"
    return "error"


async def main() -> int:
    from config.settings import settings
    from aiogram import Bot
    from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

    cand = collect_test_mids()
    pairs = sorted(cand)

    session = None
    if bool(getattr(settings, "DOWNLOAD_ENABLED", False)):
        from services.local_bot_api import build_local_api_session
        session = build_local_api_session(settings.LOCAL_BOT_API_URL)
    bot = Bot(token=settings.API_TOKEN, session=session) if session else \
        Bot(token=settings.API_TOKEN)

    async def probe(chat, mid):
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat, message_id=mid,
                reply_markup={"inline_keyboard": []})
            return "owned", ""
        except TelegramRetryAfter as exc:
            await asyncio.sleep(min(float(getattr(exc, "retry_after", 1)) + .5,
                                    60))
            return "retry", ""
        except TelegramBadRequest as exc:
            return classify_error(str(exc)), str(exc)[:140]
        except Exception as exc:  # noqa: BLE001
            return "error", "%s: %s" % (type(exc).__name__, str(exc)[:120])

    try:
        me = await bot.get_me()
        out("BOT", "id=%s username=%s" % (me.id, me.username))
        if int(me.id) != BOT_ID:
            out("ABORT", "unexpected bot id")
            return 5

        states = {"owned": 0, "absent": 0, "not_owned": 0, "error": 0}
        still_alive = []
        for idx, (chat, mid) in enumerate(pairs, 1):
            state, err = await probe(chat, mid)
            if state == "retry":
                state, err = await probe(chat, mid)
            states[state] = states.get(state, 0) + 1
            if state in ("owned", "error"):
                still_alive.append({"chat_id": chat, "mid": mid,
                                    "state": state, "error": err,
                                    "sources": cand[(chat, mid)][:3]})
            if idx % 60 == 0:
                out("PROGRESS", "%d/%d %s" % (idx, len(pairs), states))
            await asyncio.sleep(0.05)
        out("TEST_PROBE", json.dumps(states))

        path = db_path()
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=20)
        con.row_factory = sqlite3.Row
        try:
            db = {
                "smart_synth": con.execute(
                    "SELECT COUNT(*) n FROM smart_messages WHERE user_id=?",
                    (SYNTH_USER,)).fetchone()["n"],
                "throttle_synth": con.execute(
                    "SELECT COUNT(*) n FROM throttle_state WHERE user_id=?",
                    (SYNTH_USER,)).fetchone()["n"],
                "bot_replies_synth_chat_a": con.execute(
                    "SELECT COUNT(*) n FROM bot_replies WHERE chat_id=?",
                    (CHAT_A,)).fetchone()["n"],
                "bot_replies_synth_chat_b": con.execute(
                    "SELECT COUNT(*) n FROM bot_replies WHERE chat_id=?",
                    (CHAT_B,)).fetchone()["n"],
            }
            mist = []
            for mid in MISTAKE:
                row = con.execute(
                    "SELECT chat_id, tg_message_id, sent_at, output_kind, "
                    "parent_message_ref, content_text FROM mca_bot_outputs "
                    "WHERE chat_id=? AND tg_message_id=?",
                    (CHAT_A, mid)).fetchone()
                rec = dict(row) if row else {"mid": mid, "missing": True}
                pref = (rec.get("parent_message_ref") or "")
                if pref.startswith("tg:"):
                    pm = int(pref[3:])
                    prow = con.execute(
                        "SELECT user_id FROM smart_messages WHERE chat_id=? "
                        "AND tg_message_id=?", (CHAT_A, pm)).fetchone()
                    rec["parent_mid"] = pm
                    rec["parent_user_id"] = (prow["user_id"] if prow
                                             else None)
                    rec["parent_is_synth"] = bool(
                        prow and int(prow["user_id"]) == SYNTH_USER)
                mist.append(rec)
            db["mistake_rows"] = mist
        finally:
            con.close()
        out("DB", json.dumps({k: v for k, v in db.items()
                              if k != "mistake_rows"}))

        report = {
            "generated_utc": iso(),
            "mode": "read-only (no delete, no send)",
            "test_candidates": len(pairs),
            "test_probe_states": states,
            "test_still_alive": still_alive,
            "residual_clean": not still_alive,
            "db": db,
        }
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
        out("RESIDUAL_CLEAN", str(not still_alive))
        return 0 if not still_alive else 3
    finally:
        try:
            await bot.session.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("STOP97F_FATAL %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    print("STOP97F_RC=%d" % rc, flush=True)
    os._exit(rc)
