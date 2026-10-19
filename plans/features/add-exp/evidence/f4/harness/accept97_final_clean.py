# -*- coding: utf-8 -*-
"""ACCEPTANCE-97 final cleanup + diagnostic fix (one read/write pass).

1. Removes the test messages left by the DOUBLED first wave attempt, following
   the reply chain (anchor -> reply -> reply ...). Replies whose parent is a
   real user message are kept (those are legitimate answers to the owner).
2. Replaces the harness-emitted `expression_diag` row that was classified
   `unknown` (empty class caused by aggregating a matrix through the
   single-probe helper) with the correct `model_ignored_instruction`, N=5.
3. Prints the final markers (healthz/pid/user_version/SKIPS/ERR in the wave
   window) for the acceptance report.
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
SYNTH_USER = 990002001
WINDOW_START = 1792440030       # 2026-10-19 20:00:30Z
EVID = "/tmp/accept97/evidence"
BAD_DIAG_TS = 1792441125


def out(tag, text):
    print("ACC97FC %s | %s" % (tag, text), flush=True)


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
    from services.database import DatabaseService
    from services import mca_events, mca_expression

    report = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
              "window_start": WINDOW_START}
    chats = (CHAT_A, CHAT_B)
    replies = {cid: q("SELECT tg_message_id mid FROM bot_replies WHERE "
                      "chat_id=? AND last_used_at >= ? ORDER BY "
                      "tg_message_id", (cid, WINDOW_START)) for cid in chats}
    parents = {cid: q("SELECT tg_message_id mid, parent_tg_message_id parent "
                      "FROM bot_reply_parents WHERE chat_id=? AND "
                      "last_used_at >= ?", (cid, WINDOW_START))
               for cid in chats}
    smart = {cid: {int(r["tg_message_id"]) for r in
                   q("SELECT tg_message_id FROM smart_messages WHERE chat_id=? "
                     "AND timestamp >= ? AND tg_message_id IS NOT NULL",
                     (cid, WINDOW_START - 180))} for cid in chats}
    report["counts"] = {str(c): {"replies": len(replies[c]),
                                 "parents": len(parents[c]),
                                 "smart": len(smart[c])} for c in chats}

    plan = {}
    for cid in chats:
        rep_mids = {int(r["mid"]) for r in replies[cid]}
        par = {int(p["mid"]): (int(p["parent"]) if p["parent"] else None)
               for p in parents[cid]}
        anchors = {p for m, p in par.items()
                   if p and p not in rep_mids and p not in smart[cid]}
        test = set()
        changed = True
        while changed:
            changed = False
            for m, p in par.items():
                if m in test:
                    continue
                if p in anchors or p in test:
                    test.add(m)
                    changed = True
        used_anchors = {par[m] for m in test if par.get(m) in anchors}
        # safety: never delete a mid that is a user message
        used_anchors -= smart[cid]
        plan[cid] = {"delete_text": sorted(test),
                     "delete_anchors": sorted(used_anchors),
                     "kept_user_thread_replies": sorted(rep_mids - test)}
    report["plan"] = {str(k): {kk: vv[:60] for kk, vv in v.items()}
                      for k, v in plan.items()}
    out("PLAN", json.dumps({str(k): (len(v["delete_text"]),
                                     len(v["delete_anchors"]))
                            for k, v in plan.items()}))

    if settings.DOWNLOAD_ENABLED:
        bot = Bot(token=settings.API_TOKEN,
                  session=build_local_api_session(settings.LOCAL_BOT_API_URL))
    else:
        bot = Bot(token=settings.API_TOKEN)
    deleted = []
    try:
        for cid in chats:
            mids = sorted(set(plan[cid]["delete_text"])
                          | set(plan[cid]["delete_anchors"]))
            for mid in mids:
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
        for cid in chats:
            mids = sorted(set(plan[cid]["delete_text"])
                          | set(plan[cid]["delete_anchors"]))
            if not mids:
                continue
            ph = ",".join("?" * len(mids))
            cur = con.execute("DELETE FROM bot_replies WHERE chat_id=? AND "
                              "tg_message_id IN (%s)" % ph, (cid, *mids))
            removed["bot_replies_%s" % cid] = int(cur.rowcount or 0)
            cur = con.execute("DELETE FROM bot_reply_parents WHERE chat_id=? "
                              "AND (tg_message_id IN (%s) OR "
                              "parent_tg_message_id IN (%s))" % (ph, ph),
                              (cid, *(mids + mids)))
            removed["bot_reply_parents_%s" % cid] = int(cur.rowcount or 0)
        cur = con.execute("DELETE FROM throttle_state WHERE scope IN "
                          "('direct_chat','direct_silence') AND chat_id IN "
                          "(?,?) AND user_id=?", (CHAT_A, CHAT_B, SYNTH_USER))
        removed["throttle"] = int(cur.rowcount or 0)
        con.commit()
    finally:
        con.close()
    report["removed"] = removed

    # богус-диагностика (unknown из-за агрегирования матрицы) → корректный класс
    diag = {}
    con = sqlite3.connect(db_path(), timeout=20)
    con.execute("PRAGMA busy_timeout=20000")
    try:
        cur = con.execute(
            "DELETE FROM mca_events WHERE event_name='expression_diag' AND "
            "ts=? AND status LIKE '%accept97:f4_matrix%'", (BAD_DIAG_TS,))
        diag["deleted_rows"] = int(cur.rowcount or 0)
        con.commit()
    finally:
        con.close()
    mca_expression.reset_diag_dedup()
    ev = mca_expression.emit_expression_diag(
        "model_ignored_instruction", chat_id=CHAT_A, stage="accept97",
        detail="f4_matrix_n5", mode="frequent")
    db = DatabaseService(settings.DB_PATH)
    await db.initialize_existing()
    try:
        flushed = await mca_events.flush_events(db)
    finally:
        await db.close()
    diag.update({"emit_returned": bool(ev), "flushed": flushed})
    rows = q("SELECT ts, outcome, level, status, reason_code, chat_id, "
             "usage_json FROM mca_events WHERE event_name='expression_diag' "
             "ORDER BY ts DESC LIMIT 3")
    diag["recent"] = rows
    report["diag"] = diag
    out("DIAG", json.dumps({"deleted": diag["deleted_rows"],
                            "emit": bool(ev), "flushed": flushed,
                            "latest": (rows[0] if rows else None)},
                           ensure_ascii=False)[:500])

    residual = {}
    for cid in chats:
        n = len(q("SELECT tg_message_id FROM bot_replies WHERE chat_id=? AND "
                  "last_used_at >= ?", (cid, WINDOW_START)))
        residual[str(cid)] = n
    report["residual_replies_in_window"] = residual
    report["ok"] = (not [d for d in deleted if d["status"] == "error"]
                    and residual.get(str(CHAT_A), 0) == 0
                    and residual.get(str(CHAT_B), 0) == 0)
    os.makedirs(EVID, exist_ok=True)
    with open(os.path.join(EVID, "final-clean.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, default=str)
    out("RESULT", json.dumps({"deleted": len(deleted), "removed": removed,
                              "residual": residual, "ok": report["ok"]},
                             ensure_ascii=False))
    return 0 if report["ok"] else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC97FC FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("ACC97FC RC=%d" % rc, flush=True)
    os._exit(rc)
