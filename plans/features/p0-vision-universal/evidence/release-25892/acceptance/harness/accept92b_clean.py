# -*- coding: utf-8 -*-
"""ACCEPTANCE-92 cleanup + read-only diagnostics (ONE foreground SSH run).

Part A (read-only diagnostics):
  * full vision event dump since T0 (stage/model/error_json, no cuts);
  * vision task_jobs detail (attempts/next_retry_at);
  * latest mca_media_analyses rows;
  * live GET /api/vision/state (per-chat + global) вЂ” prod-process view;
  * bounded settle-wait (<=6 min) for the next queued vision retry, then
    re-check jobs/analyses/state once;
  * SCEN-B (nostalgia) observations since T0.
Part B (owner rule): delete the acceptance test messages via Bot API +
remove the synthetic smart_messages fidelity row (safety gate vs real users).

Input: /tmp/accept92b_cleanup_mids.json
Output: /tmp/accept92b/evidence/cleanup-register.json
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
import urllib.parse

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORK_CHAT = -1002661910336
SYNTH_USER = 990002001
ADMIN_ID = 5885953495
EXPECTED_BOT_ID = 8802473181
T0 = 1792365948
REGISTER_IN = "/tmp/accept92b_cleanup_mids.json"
REGISTER_OUT = "/tmp/accept92b/evidence/cleanup-register.json"


def out(tag, text):
    print("CLEAN92B %s | %s" % (tag, text), flush=True)


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


def short(value, n=70):
    return " ".join(str(value or "").split())[:n]


def make_init_data(user_id=ADMIN_ID):
    from config.settings import settings
    token = settings.API_TOKEN or ""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHaccept92clean",
        "user": json.dumps({"id": user_id, "first_name": "Accept92",
                            "username": "accept92"},
                           separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


async def live_state(tag):
    """Live GET /api/vision/state (per-chat + global) via loopback."""
    import httpx
    res = {}
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=20.0) as c:
            h = {"X-Telegram-Init-Data": make_init_data(),
                 "X-Chat-Id": str(WORK_CHAT)}
            r = await c.get("/api/vision/state", headers=h)
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:200]}
            res["owner"] = {"http": r.status_code, "body": body}
            r2 = await c.get("/api/vision/state",
                             headers={"X-Telegram-Init-Data": make_init_data()})
            try:
                body2 = r2.json()
            except Exception:
                body2 = {"raw": r2.text[:200]}
            res["global"] = {"http": r2.status_code, "body": body2}
    except Exception as exc:  # noqa: BLE001
        res["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    out(tag, json.dumps(res, ensure_ascii=False, default=str)[:1400])
    return res


async def probe_now():
    """One live POST /api/vision/test (free provider call, no chat messages)."""
    import httpx
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=90.0) as c:
            h = {"X-Telegram-Init-Data": make_init_data(),
                 "X-Chat-Id": str(WORK_CHAT)}
            r = await c.post("/api/vision/test", headers=h, json={})
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:200]}
        safe = {"http": r.status_code, "ok": body.get("ok"),
                "capability": body.get("capability"),
                "reason": body.get("reason"), "detail": body.get("detail"),
                "visible_reason": body.get("visible_reason"),
                "model": body.get("model"),
                "state_requested": (body.get("state") or {}).get("requested"),
                "state_effective": (body.get("state") or {}).get(
                    "effective_enabled")}
        out("PROBE_NOW", json.dumps(safe, ensure_ascii=False))
        return safe
    except Exception as exc:  # noqa: BLE001
        out("PROBE_NOW", "error %s" % type(exc).__name__)
        return {"error": type(exc).__name__}


def vision_events():
    return q(
        "SELECT id, ts, event_name, outcome, reason_code, stage, level, "
        "model, chat_id, operation_id, substr(error_json,1,220) ej "
        "FROM mca_events WHERE ts >= ? AND (event_name LIKE 'vision%' "
        "OR reason_code LIKE 'vision%') ORDER BY id", (T0,))


def vision_jobs():
    return q(
        "SELECT job_id, status, reason_code, attempt, max_attempts, "
        "error_code, created_at, updated_at, next_retry_at, finished_at "
        "FROM task_jobs WHERE kind LIKE 'vision%' ORDER BY created_at DESC "
        "LIMIT 10")


def analyses():
    return q(
        "SELECT id, asset_id, status, revision, analyzer_model, "
        "error_reason, created_at, completed_at FROM mca_media_analyses "
        "ORDER BY id DESC LIMIT 8")


async def main() -> int:
    from config.settings import settings
    from aiogram import Bot

    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    with open(REGISTER_IN, "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    delete_mids = sorted({int(m) for m in spec.get("delete_mids") or []})
    smart_rows = sorted({int(m) for m in spec.get("smart_rows") or []})
    win = spec.get("window") or {}
    lo, hi = int(win.get("lo") or 0), int(win.get("hi") or 0)
    out("SPEC", "delete=%d smart_rows=%d window=%s..%s"
        % (len(delete_mids), len(smart_rows), lo, hi))

    # в”Ђв”Ђ Part A1: diagnostics в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    diag = {}
    try:
        diag["events"] = vision_events()
        out("DIAG_EVENTS", "rows=%d" % len(diag["events"]))
    except Exception as exc:  # noqa: BLE001
        diag["events_error"] = type(exc).__name__
    try:
        diag["jobs"] = vision_jobs()
        diag["analyses"] = analyses()
    except Exception as exc:  # noqa: BLE001
        diag["jobs_error"] = type(exc).__name__
    diag["state_before_wait"] = await live_state("DIAG_STATE")
    diag["probe_now"] = await probe_now()

    # в”Ђв”Ђ Part A2: bounded settle-wait for the next queued retry в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    try:
        rows = q("SELECT MIN(next_retry_at) m FROM task_jobs WHERE "
                 "kind LIKE 'vision%' AND status='queued'")
        nxt = int((rows[0]["m"] or 0) if rows else 0)
        now = int(time.time())
        wait_s = nxt - now
        diag["settle_wait"] = {"next_retry_at": nxt, "now": now,
                               "waited_s": 0}
        if 0 < wait_s <= 360:
            out("WAIT", "settle %ss for vision retry" % (wait_s + 75))
            await asyncio.sleep(wait_s + 75)
            diag["settle_wait"]["waited_s"] = wait_s + 75
            diag["jobs_after_wait"] = vision_jobs()
            diag["analyses_after_wait"] = analyses()
            diag["state_after_wait"] = await live_state("DIAG_STATE2")
        else:
            out("WAIT", "no bounded retry to wait for (delta=%s)" % wait_s)
    except Exception as exc:  # noqa: BLE001
        diag["settle_error"] = type(exc).__name__

    # в”Ђв”Ђ Part A3: SCEN-B (nostalgia, read-only) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    scen_b = {"t0_epoch": T0}
    try:
        scen_b["nostalgia_since_t0"] = q(
            "SELECT ts, kind, status, substr(meta,1,200) meta FROM "
            "nostalgia_log WHERE chat_id=? AND ts >= ? ORDER BY ts DESC "
            "LIMIT 20", (WORK_CHAT, T0))
        scen_b["nostalgia_events_since_t0"] = q(
            "SELECT ts, event_name, outcome, reason_code FROM mca_events "
            "WHERE ts >= ? AND (event_name LIKE '%nostalgia%' OR "
            "reason_code LIKE '%nostalgia%') ORDER BY ts DESC LIMIT 20",
            (T0,))
    except Exception as exc:  # noqa: BLE001
        scen_b["error"] = type(exc).__name__
    out("SCEN_B", json.dumps(scen_b, ensure_ascii=False)[:700])

    # в”Ђв”Ђ Part B: cleanup (owner rule) в”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђ
    incoming = q(
        "SELECT tg_message_id mid, user_id, author_name, media_type, "
        "reply_to_id, timestamp ts, substr(text,1,90) head "
        "FROM smart_messages WHERE chat_id=? AND tg_message_id IS NOT NULL "
        "AND tg_message_id BETWEEN ? AND ? ORDER BY tg_message_id",
        (WORK_CHAT, lo, hi))
    botrep = q(
        "SELECT tg_message_id mid, substr(text,1,90) head, last_used_at "
        "FROM bot_replies WHERE chat_id=? AND tg_message_id BETWEEN ? AND ? "
        "ORDER BY tg_message_id", (WORK_CHAT, lo, hi))
    parents = q(
        "SELECT tg_message_id mid, parent_tg_message_id parent "
        "FROM bot_reply_parents WHERE chat_id=? AND tg_message_id BETWEEN ? "
        "AND ? ORDER BY tg_message_id", (WORK_CHAT, lo, hi))
    out("INV", "smart_messages=%d bot_replies=%d parents=%d"
        % (len(incoming), len(botrep), len(parents)))

    inc_by_mid = {r["mid"]: r for r in incoming}
    rep_by_mid = {r["mid"]: r for r in botrep}
    parent_by_mid = {r["mid"]: r["parent"] for r in parents}

    delete_set = set(delete_mids)
    blocked = []
    for mid in delete_mids:
        row = inc_by_mid.get(mid)
        if row is not None and row["user_id"] not in (SYNTH_USER,
                                                      EXPECTED_BOT_ID) \
                and mid not in rep_by_mid:
            blocked.append({"mid": mid, "user_id": row["user_id"],
                            "head": short(row["head"]),
                            "reason": "real user message in smart_messages"})
    if blocked:
        out("ABORT", "delete set overlaps user messages: %s"
            % [b["mid"] for b in blocked])
        return 5

    bot = Bot(token=settings.API_TOKEN)
    deleted = []
    try:
        me = await bot.get_me()
        out("BOT", "id=%s username=%s" % (me.id, me.username))
        if EXPECTED_BOT_ID and int(me.id) != EXPECTED_BOT_ID:
            out("ABORT", "unexpected bot id")
            return 5
        for mid in delete_mids:
            rec = {"mid": mid}
            row = inc_by_mid.get(mid)
            if row is not None:
                rec["author"] = row["author_name"]
                rec["head"] = short(row["head"])
            if mid in rep_by_mid:
                rec["bot_reply_head"] = short(rep_by_mid[mid]["head"])
            rec["reply_to"] = parent_by_mid.get(mid) or (
                row["reply_to_id"] if row else None)
            try:
                await bot.delete_message(chat_id=WORK_CHAT, message_id=mid)
                rec["status"] = "deleted"
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                if "not found" in text.lower():
                    rec["status"] = "already_deleted"
                else:
                    rec["status"] = "error"
                    rec["error"] = (type(exc).__name__ + ": " + text)[:160]
            deleted.append(rec)
            out("DEL", "%s %s" % (mid, rec["status"]))
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass

    db_removed = []
    if smart_rows:
        try:
            con = sqlite3.connect(db_path(), timeout=20)
            con.execute("PRAGMA busy_timeout=20000")
            for mid in smart_rows:
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
                    db_removed.append({"mid": mid, "rowid": rid})
            con.commit()
            con.close()
        except Exception as exc:  # noqa: BLE001
            out("DBROWS", "cleanup failed: %s" % type(exc).__name__)
    out("DBROWS", "removed=%d" % len(db_removed))

    after = q(
        "SELECT tg_message_id mid, user_id FROM smart_messages "
        "WHERE chat_id=? AND tg_message_id BETWEEN ? AND ?",
        (WORK_CHAT, lo, hi))
    residual_rows = [r for r in after if r["mid"] in delete_set]
    failed = [r["mid"] for r in deleted if r["status"] == "error"]
    verification = {
        "delete_attempts": len(deleted),
        "deleted_now": sum(r["status"] == "deleted" for r in deleted),
        "already_deleted": sum(r["status"] == "already_deleted"
                               for r in deleted),
        "failed": failed,
        "residual_smart_rows_for_deleted": residual_rows,
        "synthetic_rows_removed": db_removed,
        "window": {"lo": lo, "hi": hi},
    }
    register = {
        "generated_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "chat_id": WORK_CHAT,
        "method": ("Telegram Bot API deleteMessage via the deployed bot; "
                   "single SSH run; safety gate vs real user messages; "
                   "synthetic smart_messages fidelity rows removed"),
        "deleted": deleted,
        "diagnostics": diag,
        "scen_b": scen_b,
        "verification": verification,
    }
    os.makedirs("/tmp/accept92/evidence", exist_ok=True)
    payload = json.dumps(register, ensure_ascii=False, indent=1, default=str)
    with open(REGISTER_OUT, "w", encoding="utf-8") as fh:
        fh.write(payload)
    out("REGISTER_SIZE", len(payload))
    out("VERIFY", json.dumps(verification, ensure_ascii=False))
    out("DONE", "deleted=%d residual_rows=%d failed=%s"
        % (verification["deleted_now"], len(residual_rows), failed))
    return 0 if not failed else 3


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("CLEAN92B FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("CLEAN92B RC=%d" % rc, flush=True)
    os._exit(rc)
