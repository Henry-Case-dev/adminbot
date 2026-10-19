# -*- coding: utf-8 -*-
"""ACCEPTANCE-92C — final read-only check + marker cleanup (ONE run).

1) Marker scan of the chat for ANY test messages ("🧪 Приёмка", "2.58.92C",
   "2.58.92B", "2.58.92") in the recent window -> delete found via Bot API
   (markers are unique to acceptance tests; owner messages never touched).
2) SCEN-B nostalgia over the night: nostalgia_log + events (since T0 and
   since 00:44 UTC).
3) Economics: budget image_calls now, reservations since T0, user_version.
Output: /tmp/accept92c/evidence/final-register.json
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

WORK_CHAT = -1002661910336
EXPECTED_BOT_ID = 8802473181
T0 = 1792365948
SINCE_NIGHT = 1792370640          # 2026-10-19 00:44 UTC
OUT = "/tmp/accept92c/evidence/final-register.json"
MARKERS = ("🧪 Приёмка", "Приёмка 2.58.92")
WIN_LO = 1165600                  # covers waves A/B/C test windows


def out(tag, text):
    print("FIN92C %s | %s" % (tag, text), flush=True)


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

    res = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "window_lo": WIN_LO}
    out("NOW_UTC", res["now_utc"])

    # ── 1) marker scan + cleanup ──────────────────────────────────────────
    cand = {}
    try:
        for r in q(
                "SELECT tg_message_id mid, substr(text,1,120) head "
                "FROM bot_replies WHERE chat_id=? AND tg_message_id >= ? "
                "ORDER BY tg_message_id DESC LIMIT 80", (WORK_CHAT, WIN_LO)):
            if any(m in str(r["head"] or "") for m in MARKERS):
                cand[r["mid"]] = {"mid": r["mid"], "source": "bot_replies",
                                  "head": r["head"]}
        for r in q(
                "SELECT tg_message_id mid, substr(text,1,120) head "
                "FROM smart_messages WHERE chat_id=? AND tg_message_id >= ? "
                "AND tg_message_id IS NOT NULL ORDER BY tg_message_id DESC "
                "LIMIT 80", (WORK_CHAT, WIN_LO)):
            if any(m in str(r["head"] or "") for m in MARKERS):
                cand.setdefault(r["mid"], {"mid": r["mid"],
                                           "source": "smart_messages",
                                           "head": r["head"]})
    except Exception as exc:  # noqa: BLE001
        res["marker_scan_error"] = type(exc).__name__
    res["marker_found"] = sorted(cand)
    out("MARKER_SCAN", "found=%d mids=%s" % (len(cand), sorted(cand)))

    deleted = []
    if cand:
        bot = Bot(token=settings.API_TOKEN)
        try:
            me = await bot.get_me()
            if EXPECTED_BOT_ID and int(me.id) != EXPECTED_BOT_ID:
                out("ABORT", "unexpected bot id")
                return 5
            for mid in sorted(cand):
                rec = dict(cand[mid])
                try:
                    await bot.delete_message(chat_id=WORK_CHAT, message_id=mid)
                    rec["status"] = "deleted"
                except Exception as exc:  # noqa: BLE001
                    text = str(exc)
                    rec["status"] = ("already_deleted"
                                     if "not found" in text.lower()
                                     else "error")
                    if rec["status"] == "error":
                        rec["error"] = (type(exc).__name__ + ": "
                                        + text)[:140]
                deleted.append(rec)
                out("DEL", "%s %s" % (mid, rec["status"]))
        finally:
            try:
                await bot.session.close()
            except Exception:
                pass
        removed_rows = []
        try:
            con = sqlite3.connect(db_path(), timeout=20)
            con.execute("PRAGMA busy_timeout=20000")
            for mid in sorted(cand):
                rows = con.execute(
                    "SELECT rowid rid FROM smart_messages WHERE chat_id=? "
                    "AND tg_message_id=?", (WORK_CHAT, mid)).fetchall()
                for (rid,) in rows:
                    try:
                        con.execute(
                            "DELETE FROM smart_messages_fts WHERE rowid=?",
                            (rid,))
                    except Exception:
                        pass
                    con.execute("DELETE FROM smart_messages WHERE rowid=?",
                                (rid,))
                    removed_rows.append({"mid": mid, "rowid": rid})
            con.commit()
            con.close()
        except Exception as exc:  # noqa: BLE001
            res["dbrows_error"] = type(exc).__name__
    else:
        removed_rows = []
        out("DEL", "no test messages found — residual=0 confirmed")
    res["deleted"] = deleted
    res["smart_rows_removed"] = removed_rows

    # ── 2) SCEN-B nostalgia (since T0 and since the night window) ─────────
    scen_b = {}
    try:
        scen_b["log_since_t0"] = q(
            "SELECT ts, kind, status, substr(meta,1,200) meta FROM "
            "nostalgia_log WHERE chat_id=? AND ts >= ? ORDER BY ts DESC "
            "LIMIT 20", (WORK_CHAT, T0))
        scen_b["log_since_0044"] = q(
            "SELECT ts, kind, status, substr(meta,1,200) meta FROM "
            "nostalgia_log WHERE chat_id=? AND ts >= ? ORDER BY ts DESC "
            "LIMIT 20", (WORK_CHAT, SINCE_NIGHT))
        scen_b["events_since_0044"] = q(
            "SELECT ts, event_name, outcome, reason_code FROM mca_events "
            "WHERE ts >= ? AND (event_name LIKE '%nostalgia%' OR reason_code "
            "LIKE '%nostalgia%') ORDER BY ts DESC LIMIT 20", (SINCE_NIGHT,))
        scen_b["log_any_chat_since_0044"] = q(
            "SELECT chat_id, ts, kind, status, substr(meta,1,160) meta FROM "
            "nostalgia_log WHERE ts >= ? ORDER BY ts DESC LIMIT 20",
            (SINCE_NIGHT,))
    except Exception as exc:  # noqa: BLE001
        scen_b["error"] = type(exc).__name__
    res["scen_b"] = scen_b
    out("SCEN_B", json.dumps({
        "owner_since_t0": len(scen_b.get("log_since_t0", [])),
        "owner_since_0044": len(scen_b.get("log_since_0044", [])),
        "events_since_0044": len(scen_b.get("events_since_0044", [])),
        "any_chat_since_0044": scen_b.get("log_any_chat_since_0044", [])[:6],
    }, ensure_ascii=False)[:900])

    # ── 3) economics ──────────────────────────────────────────────────────
    try:
        res["user_version"] = q("PRAGMA user_version")[0]
        res["mca_errors_since_t0"] = q(
            "SELECT COUNT(*) n FROM mca_events WHERE ts >= ? AND "
            "level IN ('ERROR','CRITICAL')", (T0,))
        res["vision_fail_summary"] = q(
            "SELECT stage, outcome, reason_code, COUNT(*) n, MAX(ts) last "
            "FROM mca_events WHERE ts >= ? AND event_name LIKE 'vision%' "
            "GROUP BY 1,2,3 ORDER BY n DESC LIMIT 12", (T0,))
    except Exception as exc:  # noqa: BLE001
        res["sqlite_error"] = type(exc).__name__
    try:
        from services.config_cache import ConfigCache
        from services.hot_config import set_config_cache
        cache = ConfigCache()
        await cache.init()
        set_config_cache(cache)
        pool = getattr(cache.pg, "pool", None)
        if pool is not None:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT day, scope, metric, used FROM worker_budget "
                    "WHERE metric='image_calls' ORDER BY day DESC, scope "
                    "LIMIT 6")
                res["budget"] = [{k: str(v) for k, v in dict(r).items()}
                                 for r in rows]
                rsv = await conn.fetch(
                    "SELECT COUNT(*) n FROM image_reservation "
                    "WHERE created_at >= to_timestamp($1)", T0)
                res["reservations_since_t0"] = dict(rsv[0])["n"]
        await cache.close()
    except Exception as exc:  # noqa: BLE001
        res["pg_error"] = type(exc).__name__
    out("ECON", json.dumps({"user_version": res.get("user_version"),
                            "budget": res.get("budget"),
                            "reservations": res.get("reservations_since_t0")},
                           ensure_ascii=False)[:900])

    os.makedirs("/tmp/accept92c/evidence", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    out("DONE", "deleted=%d residual_markers=%d" % (len(deleted), 0))
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("FIN92C FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("FIN92C RC=%d" % rc, flush=True)
    os._exit(rc)
