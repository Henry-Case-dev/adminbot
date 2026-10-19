# -*- coding: utf-8 -*-
"""ADD-EXP Ф0 — read-only probe 2: reply-frequency fact (bot replies + mat).

Fixes the ordering/attribution question of probe 1 and uses an extended mat
detector (нахуй/наёб/заёб/съеб/поеб/хер...). SELECT-only.

Output: /tmp/addexp_f0/evidence/probe_replies.json
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

WORK_CHAT = -1002661910336
BOT_ID = 8802473181
EVID = "/tmp/addexp_f0/evidence"
TAG = "probe_replies"

MAT_HARD = (
    r"\bху[йяеёию]\w*", r"\bхуйн\w*", r"\bзахуя\w*", r"\bнахуя\w*",
    r"\bнахуй\w*", r"\bпохуй\w*", r"\bохуе\w*", r"\bнихуя\b",
    r"\bпизд\w*", r"\bбля\w*",
    r"\bеб(а|ё|е|у|и|л|н|с|ш)\w*", r"\bёб\w*", r"\bзаеб\w*", r"\bзаёб\w*",
    r"\bнаеб\w*", r"\bнаёб\w*", r"\bвыеб\w*", r"\bотъеб\w*", r"\bотъёб\w*",
    r"\bуеб\w*", r"\bуёб\w*", r"\bпроеб\w*", r"\bсъеб\w*", r"\bпоеб\w*",
    r"\bдоеб\w*", r"\bдолбоёб\w*",
    r"\bсука\b|\bсуки\b|\bсуке\b|\bсуку\b|\bсукой\b|\bсучк\w*",
    r"\bмудак\w*|\bмудил\w*",
    r"\bпидор\w*|\bпидар\w*|\bпидр\w*|\bпедик\w*|\bпедераст\w*",
    r"\bгондон\w*|\bгандон\w*", r"\bманда\w*|\bмандав\w*",
    r"\bшлюх\w*", r"\bдроч\w*", r"\bзалуп\w*", r"\bелда\w*",
)
MAT_SOFT = (
    r"\bжоп\w*", r"\bговн\w*", r"\bсрать\w*|\bссан\w*|\bобосра\w*",
    r"\bхер\b|\bхерня\b|\bпохер\b|\bхеров\w*|\bхерн\w*",
)


def out(tag, text):
    print("F0P2 %s | %s" % (tag, text), flush=True)


def scan(text):
    text = str(text or "")
    hard, soft = [], []
    seen = set()
    for pat in MAT_HARD:
        for m in re.finditer(pat, text, re.IGNORECASE):
            k = (m.start(), m.end())
            if k in seen:
                continue
            seen.add(k)
            s, e = max(0, m.start() - 50), min(len(text), m.end() + 50)
            hard.append({"m": m.group(0),
                         "ctx": " ".join(text[s:e].split())})
    for pat in MAT_SOFT:
        for m in re.finditer(pat, text, re.IGNORECASE):
            s, e = max(0, m.start() - 50), min(len(text), m.end() + 50)
            soft.append({"m": m.group(0),
                         "ctx": " ".join(text[s:e].split())})
    return {"hard": hard, "soft": soft}


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
    from config.settings import settings as _settings  # noqa: F401 (dotenv)
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    out("NOW_UTC", now)
    res: dict = {"now_utc": now, "chat_id": WORK_CHAT}

    cols = q("PRAGMA table_info(smart_messages)")
    res["smart_messages_columns"] = [c["name"] for c in cols]

    last60 = q(
        "SELECT id, user_id, author_name, timestamp, reply_to_id, media_type, "
        "tg_message_id, substr(text,1,4000) AS text FROM smart_messages "
        "WHERE chat_id=? ORDER BY id DESC LIMIT 60", (WORK_CHAT,))
    res["last60_rows"] = [
        {**r, "ts_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.gmtime(int(r["timestamp"]))),
         "is_bot": r["user_id"] == BOT_ID} for r in last60]

    by_author = q(
        "SELECT user_id, author_name, COUNT(*) AS c, MIN(timestamp) AS first_ts,"
        " MAX(timestamp) AS last_ts FROM smart_messages WHERE chat_id=? "
        "GROUP BY user_id ORDER BY c DESC LIMIT 15", (WORK_CHAT,))
    res["authors"] = by_author

    bot_rows = [r for r in res["last60_rows"] if r["is_bot"]]
    res["bot_rows_in_last60"] = len(bot_rows)
    res["bot_rows_with_mid"] = sum(1 for r in bot_rows
                                   if r["tg_message_id"] is not None)

    # full bot history scan (all rows authored by the bot in this chat)
    bot_all = q(
        "SELECT id, tg_message_id, author_name, timestamp, reply_to_id, "
        "substr(text,1,4000) AS text FROM smart_messages "
        "WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT 40",
        (WORK_CHAT, BOT_ID))
    res["bot_last40"] = []
    for r in bot_all:
        s = scan(r["text"])
        res["bot_last40"].append({
            "id": r["id"], "mid": r["tg_message_id"],
            "ts_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                    time.gmtime(int(r["timestamp"]))),
            "author": r["author_name"],
            "head": " ".join(str(r["text"] or "").split())[:120],
            "hard": s["hard"], "soft": s["soft"]})
    hard_bot = [r for r in res["bot_last40"] if r["hard"]]
    soft_bot = [r for r in res["bot_last40"] if r["soft"]]
    res["bot_scan"] = {
        "checked": len(res["bot_last40"]),
        "with_hard": len(hard_bot),
        "with_soft": len(soft_bot),
        "hard_examples": [{"mid": r["mid"], "head": r["head"],
                           "hard": r["hard"][:3]} for r in hard_bot[:6]],
        "soft_examples": [{"mid": r["mid"], "head": r["head"],
                           "soft": r["soft"][:3]} for r in soft_bot[:6]],
    }

    # scan the same last-60 window, split by author kind
    win_scan = {"bot": {"n": 0, "hard": 0, "soft": 0},
                "other": {"n": 0, "hard": 0, "soft": 0}}
    for r in res["last60_rows"]:
        s = scan(r["text"])
        kind = "bot" if r["is_bot"] else "other"
        win_scan[kind]["n"] += 1
        win_scan[kind]["hard"] += 1 if s["hard"] else 0
        win_scan[kind]["soft"] += 1 if s["soft"] else 0
    res["window_scan"] = win_scan

    br = q("SELECT COUNT(*) AS c, MIN(tg_message_id) AS lo, "
           "MAX(tg_message_id) AS hi, MAX(last_used_at) AS last_used "
           "FROM bot_replies WHERE chat_id=?", (WORK_CHAT,))
    res["bot_replies_total"] = br

    os.makedirs(EVID, exist_ok=True)
    path = os.path.join(EVID, "%s.json" % TAG)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    out("SAVED", "%s (%d bytes)" % (path, os.path.getsize(path)))
    out("AUTHORS", json.dumps(by_author[:8], ensure_ascii=False)[:600])
    out("BOT_SCAN", json.dumps(res["bot_scan"], ensure_ascii=False)[:900])
    out("WINDOW", json.dumps(win_scan, ensure_ascii=False))
    out("BOT_REPLIES_TOTAL", json.dumps(br, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("F0P2 FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("F0P2 RC=%d" % rc, flush=True)
    os._exit(rc)
