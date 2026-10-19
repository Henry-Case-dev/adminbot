# -*- coding: utf-8 -*-
"""ACCEPTANCE-97 final state verification (read-only) + evidence JSON.

Confirms: zero test bot messages left in the wave window, zero synthetic rows,
corrected expression_diag row, chats back to global, prod markers.
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
OUT = "/tmp/accept97/final-verify.json"


def out(tag, text):
    print("ACC97FV %s | %s" % (tag, text), flush=True)


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
              "query_id": "AAHaccept97verify",
              "user": json.dumps({"id": 5885953495, "first_name": "Accept97",
                                  "username": "accept97"},
                                 separators=(",", ":"))}
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


async def main() -> int:
    import httpx
    res = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "window_start": WINDOW_START}
    for cid in (CHAT_A, CHAT_B):
        key = str(cid)
        res[key] = {
            "replies_in_window": q(
                "SELECT tg_message_id mid, last_used_at FROM bot_replies "
                "WHERE chat_id=? AND last_used_at >= ? ORDER BY "
                "tg_message_id", (cid, WINDOW_START)),
            "parents_in_window": q(
                "SELECT tg_message_id mid, parent_tg_message_id parent FROM "
                "bot_reply_parents WHERE chat_id=? AND last_used_at >= ?",
                (cid, WINDOW_START)),
            "user_messages_in_window": q(
                "SELECT tg_message_id mid, user_id, substr(text,1,60) head "
                "FROM smart_messages WHERE chat_id=? AND timestamp >= ? AND "
                "user_id NOT IN (990002001, 8802473181)", (cid, WINDOW_START)),
            "throttle_rows": q(
                "SELECT scope, COUNT(*) n FROM throttle_state WHERE chat_id=? "
                "AND user_id=990002001 GROUP BY scope", (cid,)),
        }
    res["expression_diag_recent"] = q(
        "SELECT ts, outcome, level, status, reason_code, chat_id, usage_json "
        "FROM mca_events WHERE event_name='expression_diag' ORDER BY ts DESC "
        "LIMIT 4")
    res["mca_events_errors_since_wave"] = q(
        "SELECT COUNT(*) n FROM mca_events WHERE ts >= ? AND level IN "
        "('ERROR','CRITICAL')", (WINDOW_START,))
    init = make_init_data()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=30.0) as c:
        hdr = {"X-Telegram-Init-Data": init}
        views = {}
        for label, cid in (("a", CHAT_A), ("b", CHAT_B)):
            r = await c.get("/api/speech/expression",
                            headers={**hdr, "X-Chat-Id": str(cid)})
            body = r.json()
            views[label] = {
                "http": r.status_code,
                "profanity": (body.get("effective") or {}).get("profanity"),
                "chat_present": body.get("chat_present"),
                "inheritance": body.get("inheritance"),
            }
        res["views"] = views
        h = await c.get("/healthz")
        res["healthz"] = {"http": h.status_code, "body": h.text[:120]}
    res["ok"] = (
        all(not res[str(cid)]["replies_in_window"] for cid in (CHAT_A, CHAT_B))
        and all(not res[str(cid)]["parents_in_window"]
                for cid in (CHAT_A, CHAT_B))
        and all(res[str(cid)]["throttle_rows"] == [] for cid in (CHAT_A, CHAT_B))
        and views["a"]["chat_present"] is False
        and views["b"]["chat_present"] is False
        and all(str(views[x]["profanity"].get("source")) == "global"
                for x in ("a", "b"))
        and res["mca_events_errors_since_wave"][0]["n"] == 0
    )
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    out("RESULT", json.dumps({"ok": res["ok"], "a": views["a"],
                              "b": views["b"],
                              "diag": res["expression_diag_recent"][:1],
                              "residual_a": len(res[str(CHAT_A)]
                                                ["replies_in_window"]),
                              "residual_b": len(res[str(CHAT_B)]
                                                ["replies_in_window"])},
                             ensure_ascii=False)[:700])
    return 0 if res["ok"] else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC97FV FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("ACC97FV RC=%d" % rc, flush=True)
    os._exit(rc)
