# -*- coding: utf-8 -*-
"""ACCEPTANCE-91 follow-up:
  1) capture CFG-02B active state + image ledger for the main run;
  2) restore the work chat's original per-chat overrides;
  3) focused health-phrase retry (warm planner);
  4) explicit-claim factcheck (real CFG-06 verdict);
  5) delete generated image messages (evidence mids kept).
No new image generation. One foreground SSH run.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
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
SYNTH_USER = 990002001
EVID = "/tmp/accept91/evidence"


def load_live():
    spec = importlib.util.spec_from_file_location(
        "accept91_live", "/tmp/accept91_live.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def out(tag, text):
    print("AC91F %s | %s" % (tag, text), flush=True)


async def main() -> int:
    mod = load_live()
    await mod.bootstrap()
    mod.CTX.api = mod.Api()
    from services import image_generation as ig
    from services import chat_params
    from services.database import DatabaseService  # noqa: F401

    summary = {}
    try:
        summary = json.load(open(os.path.join(EVID, "summary.json"),
                                 encoding="utf-8"))
    except Exception:
        pass

    # ── 1) capture CFG-02B active state + ledger ──
    cap = {}
    try:
        st, body = await mod.CTX.api.req("GET", "/api/workers/budget")
        freq = None
        if isinstance(body, dict):
            for entry in (body.get("chats") or []):
                if str(entry.get("scope")) == "chat:%d" % WORK_CHAT:
                    freq = entry.get("freq")
                    break
            if freq is None:
                freq = body.get("freq")
        cap["budget_api"] = {"status": st, "freq": freq}
    except Exception as exc:  # noqa: BLE001
        cap["budget_api"] = {"error": type(exc).__name__}
    try:
        state = await ig.image_freq_state(WORK_CHAT, SYNTH_USER)
        cap["freq_state"] = {
            "applied": getattr(state, "applied", None),
            "allowed": getattr(state, "allowed", None),
            "remaining": getattr(state, "remaining_seconds", None),
            "reason": getattr(state, "reason", None),
            "limits": str(getattr(state, "limits", None)),
        }
    except Exception as exc:  # noqa: BLE001
        cap["freq_state"] = {"error": type(exc).__name__}
    try:
        import asyncpg
        from config.settings import settings
        dsn = os.environ.get("POSTGRES_DSN") or ""
        if dsn:
            conn = await asyncpg.connect(dsn, timeout=10)
            try:
                rows = await conn.fetch(
                    "SELECT reservation_key, source, message_id, day, status, "
                    "error_code, delivery_failed, created_at "
                    "FROM image_reservation WHERE chat_id=$1 "
                    "AND created_at >= to_timestamp($2) "
                    "ORDER BY created_at", WORK_CHAT,
                    int(summary.get("start_epoch") or (time.time() - 1800)))
                cap["reservations"] = [
                    {k: str(v) for k, v in dict(r).items()} for r in rows]
            finally:
                await conn.close()
    except Exception as exc:  # noqa: BLE001
        cap["ledger_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    try:
        cap["sqlite_events"] = await mod.sqlite_fetch(
            "SELECT event_name, outcome, reason_code, chat_id, COUNT(*) n, "
            "MAX(ts) last FROM mca_events WHERE ts >= ? "
            "AND (event_name LIKE 'image%' OR event_name LIKE 'vision%') "
            "GROUP BY 1,2,3,4 ORDER BY n DESC",
            (int(summary.get("start_epoch") or (time.time() - 1800)),))
    except Exception as exc:  # noqa: BLE001
        cap["sqlite_events_error"] = type(exc).__name__
    # blocked attempt text/mid from summary
    sends = summary.get("sends") or []
    cap["blocked_send"] = next(
        (s for s in sends if s.get("message_id") == 1165624), None)
    cap["generation_sends"] = [s for s in sends
                               if s.get("kind") == "photo"
                               or s.get("message_id") in
                               (1165619, 1165621, 1165623)]
    mod.save("scenario-7-cfg02b-capture.json", cap)
    out("CAPTURE", "freq=%s state=%s reservations=%d"
        % (json.dumps(cap.get("budget_api", {}).get("freq"),
                      ensure_ascii=False)[:300],
           json.dumps(cap.get("freq_state"), ensure_ascii=False)[:200],
           len(cap.get("reservations") or [])))

    # ── 2) restore original per-chat overrides ──
    restore = {}
    try:
        root = await chat_params.get_all_chat_params(WORK_CHAT, pg=mod.CTX.pg)
        ov = dict((root or {}).get("overrides") or {})
        for key in ("limits.image_freq_limit_enabled",
                    "limits.image_freq_limit_burst",
                    "limits.image_freq_limit_cooldown_seconds",
                    "limits.image_freq_limit_mode"):
            ov.pop(key, None)
        ov["flags.budgets_enabled"] = False
        await chat_params.set_chat_params(WORK_CHAT, {"overrides": ov},
                                          changed_by=None, pg=mod.CTX.pg)
        cpc = chat_params.get_chat_params_cache()
        if cpc is not None:
            await cpc.invalidate_chat(WORK_CHAT)
        await asyncio.sleep(1.5)
        limits, reason = await ig.image_freq_config(WORK_CHAT)
        restore["after"] = {
            "enabled": bool(getattr(limits, "enabled", None)),
            "reason": reason, "limits": str(limits)}
        st, body = await mod.CTX.api.req("GET", "/api/workers/budget")
        freq = None
        if isinstance(body, dict):
            for entry in (body.get("chats") or []):
                if str(entry.get("scope")) == "chat:%d" % WORK_CHAT:
                    freq = entry.get("freq")
                    break
        restore["budget_api"] = {"status": st, "freq": freq}
        restore["overrides_keys"] = sorted(ov.keys())
        restore["budgets_enabled"] = ov.get("flags.budgets_enabled")
    except Exception as exc:  # noqa: BLE001
        restore["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    mod.save("cleanup-restore.json", restore)
    out("RESTORE", json.dumps(restore.get("after") or restore,
                              ensure_ascii=False)[:400])

    # clean synthetic runtime state
    try:
        await mod.sqlite_exec(
            "DELETE FROM throttle_state WHERE scope IN "
            "('image_freq','direct_chat','direct_silence') "
            "AND chat_id=? AND user_id=?", (WORK_CHAT, SYNTH_USER))
        out("CLEAN", "synthetic throttle rows removed")
    except Exception as exc:  # noqa: BLE001
        out("CLEAN", "throttle cleanup failed: %s" % type(exc).__name__)

    # delete generated images (mids from summary)
    deleted = []
    photo_mids = [s.get("message_id") for s in sends
                  if s.get("kind") == "photo" and s.get("message_id")]
    for mid in photo_mids:
        try:
            await mod.CTX.rec.delete_message(WORK_CHAT, mid)
            deleted.append({"mid": mid, "ok": True})
        except Exception as exc:  # noqa: BLE001
            deleted.append({"mid": mid, "ok": False,
                            "error": type(exc).__name__})
    mod.save("cleanup-deleted-images.json", {"deleted": deleted})
    out("DELETE", json.dumps(deleted, ensure_ascii=False))

    # ── 3) warm health-phrase retry ──
    health = {"scenario": "1-health-retry", "turns": []}
    # clean anchor: a fresh real bot message (controlled)
    try:
        anchor = await mod.CTX.rec.send_message(
            WORK_CHAT,
            "🧪 Приёмка 2.58.91 · health retry (контролируемый вызов).")
        anchor_mid = int(anchor.message_id)
        anchor_text = "health retry"
        health["anchor_mid"] = anchor_mid
    except Exception as exc:  # noqa: BLE001
        health["error"] = "anchor send failed: %s" % type(exc).__name__
        anchor_mid = None
    if anchor_mid is not None:
        phrase = "бот, как состояние сервера?"
        t = await mod.run_turn(phrase, msg_id=anchor_mid, reply_to=anchor,
                              label="health-retry", timeout=300)
        health["turns"].append({"phrase": phrase, **mod._strip_turn(t)})
        health["tool_called"] = mod._turn_has_tool(t, "get_bot_health")
        health["plan_caps"] = mod._turn_plan_caps(t)
        health["tool_result"] = next(
            (x for x in t.get("tool_calls", [])
             if x.get("tool") == "get_bot_health"), None)
        health["ok"] = health["tool_called"]
        last = t.get("_last_msg")
        anchor2 = last if last is not None else anchor
        # ── 4) explicit-claim factcheck ──
        fact = {"scenario": "4-factcheck-explicit", "turns": []}
        q = "бот, проверь факт: вода закипает при 100 °C на уровне моря."
        t2 = await mod.run_turn(q, msg_id=anchor2.message_id,
                                reply_to=anchor2, label="fact-explicit",
                                timeout=300)
        fact["turns"].append({"phrase": q, **mod._strip_turn(t2)})
        fact["tool_called"] = mod._turn_has_tool(t2, "fact_check")
        fact["tool_result"] = next(
            (x for x in t2.get("tool_calls", [])
             if x.get("tool") == "fact_check"), None)
        fact["ok"] = fact["tool_called"]
        mod.save("scenario-4-factcheck-explicit.json", fact)
        mod.save("scenario-1-health-retry.json", health)
        out("HEALTH_RETRY", "tool=%s caps=%s"
            % (health["tool_called"], health["plan_caps"]))
        out("FACT_EXPLICIT", "tool=%s result=%s"
            % (fact["tool_called"],
               json.dumps(fact.get("tool_result") or {},
                          ensure_ascii=False)[:300]))
    mod.save("scenario-1-health-retry.json", health)

    # healthz after
    try:
        import httpx
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=10.0) as c:
            r = await c.get("/healthz")
            out("HEALTHZ", r.text)
    except Exception as exc:  # noqa: BLE001
        out("HEALTHZ", "ERR %s" % type(exc).__name__)

    await mod._close()
    out("DONE", "follow-up complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("AC91F FATAL | %s: %s" % (type(exc).__name__,
                                        str(exc)[:300]), flush=True)
        traceback.print_exc()
        raise SystemExit(4)
