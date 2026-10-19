# -*- coding: utf-8 -*-
"""ACCEPTANCE-94 follow-up: cover isolation retry (§Ф6) + restore.

C2 failed because the harness expected run status "completed" while the
deployed summary test-run reports "ok" — the cover POST was never sent and
the cover budget stayed unspent. This script:
  1. snapshots the current (restored) config/budget;
  2. applies the §Ф6 premise (budgets ON + user daily=0 + freq ON);
  3. generates ONE base cover via the standard summary test-run:
     - first tries the still-alive test_id of the completed run
       (c9ac3c575def409dbde2287e9f91160c, TTL 15 min), else a fresh run;
  4. verifies the typed journal row source='summary_cover:base', per-chat
     user counter unchanged, shared +1, cover_used +1, freq untouched;
  5. restores the original per-chat overrides exactly.

Output: /tmp/accept94/evidence/c5-cover-fix.json (+ cover94-base.png).
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
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
T0_EPOCH = 1792397900
EXISTING_TEST_ID = "c9ac3c575def409dbde2287e9f91160c"
COVER_WINDOW_HOURS = 6
TOUCHED_KEYS = ("flags.budgets_enabled", "limits.image_daily_limit",
                "limits.image_freq_limit_enabled")
KEEP_CFG_KEYS = ("flags.budgets_enabled", "limits.image_daily_limit",
                 "limits.image_freq_limit_enabled",
                 "limits.image_freq_limit_burst",
                 "limits.image_freq_limit_cooldown_seconds",
                 "limits.image_freq_limit_mode")


def out(tag, text):
    print("ACC94B %s | %s" % (tag, text), flush=True)


def load_base():
    spec = importlib.util.spec_from_file_location("accept94_base",
                                                  "/tmp/accept94_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pick_cfg(cfg):
    items = cfg.get("items") if isinstance(cfg, dict) else None
    keep = []
    if isinstance(items, list):
        for it in items:
            if str(it.get("key")) in KEEP_CFG_KEYS:
                keep.append({k: it.get(k) for k in (
                    "key", "value", "global_value", "chat_source",
                    "per_chat", "type") if k in it})
    return keep


def _cfg_map(items):
    return {str(it.get("key")): it.get("value") for it in (items or [])}


def _budget_chat_entry(budget):
    if not isinstance(budget, dict):
        return None
    for entry in (budget.get("chats") or []):
        if str(entry.get("scope")) == "chat:%d" % WORK_CHAT:
            return entry
    return None


async def _budget_snapshot(mod, tag):
    st, body = await mod.CTX.api.req("GET", "/api/workers/budget")
    entry = _budget_chat_entry(body)
    g = ((body or {}).get("global") or {}).get("image_calls") or {}
    c = (entry or {}).get("image_calls") or {}
    u = ((entry or {}).get("image_usage") or {})
    return {"tag": tag, "http": st,
            "global_used": g.get("used"), "global_limit": g.get("limit"),
            "global_cover_used": g.get("cover_used"),
            "chat_used": c.get("used"), "chat_limit": c.get("limit"),
            "chat_limit_source": c.get("source"),
            "chat_reserve_path": u.get("reserve_path"),
            "chat_reserve_reason": u.get("reserve_reason"),
            "cover_requests": (u.get("cover") or {}).get("requests"),
            "cover_success": (u.get("cover") or {}).get("success")}


async def _reserve_mode(mod):
    from services import image_generation as ig
    mode, reason = await ig.image_reserve_mode(WORK_CHAT)
    return {"mode": mode, "reason": reason}


async def _cap_state(mod):
    from services import capability_registry as caps
    st = await caps.resolve("image_generation", WORK_CHAT, use_cache=False)
    return {"status": st.status, "reason_code": st.reason_code,
            "detail": st.detail}


async def _invalidate(mod):
    try:
        from services.chat_params import get_chat_params_cache
        cpc = get_chat_params_cache()
        if cpc is not None:
            await cpc.invalidate_chat(WORK_CHAT)
    except Exception as exc:  # noqa: BLE001
        out("CACHE", "invalidate failed: %s" % type(exc).__name__)
    try:
        from services import capability_registry as caps
        caps.invalidate("image_generation", WORK_CHAT, reason="accept94b")
    except Exception:
        pass


async def _set_cfg(mod, items, tag):
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=60.0) as c:
        r = await c.post("/api/config", headers={
            "X-Telegram-Init-Data": mod.make_init_data(),
            "X-Chat-Id": str(WORK_CHAT)},
            json={"items": items, "updated_at": None})
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
    await _invalidate(mod)
    out("CFG", "%s http=%s body=%s" % (tag, r.status_code,
                                       json.dumps(body,
                                                  ensure_ascii=False)[:300]))
    return {"http": r.status_code, "body": body}


async def _journal(mod, since):
    return await mod.pg_fetch(
        "SELECT reservation_key, chat_id, source, status, error_code, "
        "delivery_failed, day, created_at, updated_at "
        "FROM image_reservation WHERE created_at >= to_timestamp($1) "
        "ORDER BY created_at", since)


async def _poll_run(mod, test_id, timeout_s=420):
    import httpx
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=30.0) as c:
            r = await c.get("/api/summary/test/%s" % test_id,
                            headers={"X-Telegram-Init-Data":
                                     mod.make_init_data()})
            try:
                last = r.json()
            except Exception:
                last = {"raw": r.text[:200]}
        status = str((last or {}).get("status") or "")
        if status and status != "running":
            return last
        await asyncio.sleep(10)
    return last


async def _cover_call(mod, test_id):
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=300.0) as c:
        r = await c.post("/api/summary/test/%s/cover" % test_id,
                         headers={"X-Telegram-Init-Data":
                                  mod.make_init_data()},
                         json={"confirm": True})
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
    return r.status_code, body


async def _cover_image(mod, test_id):
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=90.0) as c:
        r = await c.get("/api/summary/test/%s/cover-image" % test_id,
                        headers={"X-Telegram-Init-Data":
                                 mod.make_init_data()})
        return r.status_code, r.content


async def main() -> int:
    try:
        os.umask(0o022)
    except Exception:
        pass
    mod = load_base()
    await mod.bootstrap()
    mod.CTX.api = mod.Api()
    res = {"phase": "C5-cover-fix",
           "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    from services import chat_params
    root = await chat_params.get_all_chat_params(WORK_CHAT, pg=mod.CTX.pg)
    orig = dict((root or {}).get("overrides") or {})
    res["original_overrides_touched"] = {
        k: orig.get(k) for k in TOUCHED_KEYS if k in orig}
    st, cfg = await mod.CTX.api.req("GET", "/api/config", chat_id=WORK_CHAT)
    res["config_before"] = {"http": st, "items": _pick_cfg(cfg)}
    res["budget_before"] = await _budget_snapshot(mod, "before")
    res["reserve_mode_before"] = await _reserve_mode(mod)
    res["throttle_before"] = await mod.sqlite_fetch(
        "SELECT scope, chat_id, user_id, burst_left, last_ts "
        "FROM throttle_state WHERE scope='image_freq' AND chat_id=? "
        "ORDER BY user_id", (WORK_CHAT,))
    # §Ф6 premise
    res["cfg_premise"] = await _set_cfg(mod, [
        {"key": "flags.budgets_enabled", "value": True},
        {"key": "limits.image_daily_limit", "value": 0},
        {"key": "limits.image_freq_limit_enabled", "value": True},
    ], "cover-premise-2")
    await asyncio.sleep(2.0)
    await _invalidate(mod)
    res["reserve_mode_premise"] = await _reserve_mode(mod)
    res["cap_state_premise"] = await _cap_state(mod)
    cover_ok = False
    # 1) the still-alive completed run of C2
    try:
        http, cov = await _cover_call(mod, EXISTING_TEST_ID)
    except Exception as exc:  # noqa: BLE001
        http, cov = -1, {"error": "%s: %s" % (type(exc).__name__,
                                             str(exc)[:200])}
    res["cover_existing"] = {"test_id": EXISTING_TEST_ID, "http": http,
                             "body": cov}
    if http == 200 and str((cov or {}).get("cover_status")) == "generated":
        res["cover_test_id"] = EXISTING_TEST_ID
        cover_ok = True
    if not cover_ok:
        # 2) fresh run (fixed status check: "ok" == success)
        st, run = await mod.CTX.api.req(
            "POST", "/api/summary/test/run",
            json_body={"chat_id": WORK_CHAT,
                       "window_hours": COVER_WINDOW_HOURS})
        res["run_start"] = {"http": st, "body": run if isinstance(
            run, dict) else str(run)[:200]}
        test_id = (run or {}).get("test_id") if isinstance(run, dict) else None
        if st in (200, 202) and test_id:
            result = await _poll_run(mod, test_id, timeout_s=420)
            res["run_result"] = {"status": (result or {}).get("status"),
                                 "cover": (result or {}).get("cover"),
                                 "error": (result or {}).get("error"),
                                 "window": (result or {}).get("window")}
            if str((result or {}).get("status")) in ("ok", "completed"):
                http2, cov2 = await _cover_call(mod, test_id)
                res["cover_fresh"] = {"test_id": test_id, "http": http2,
                                      "body": cov2}
                if http2 == 200 and str(
                        (cov2 or {}).get("cover_status")) == "generated":
                    res["cover_test_id"] = test_id
                    cover_ok = True
    if cover_ok:
        st3, img = await _cover_image(mod, res["cover_test_id"])
        res["cover_image"] = {"http": st3, "bytes": len(img or b""),
                              "sha12": mod.sha12(img or b"")}
        if img:
            with open(os.path.join(mod.EVID, "cover94-base.png"),
                      "wb") as fh:
                fh.write(img)
    res["cover_ok"] = cover_ok
    await asyncio.sleep(2.0)
    res["journal_since_start"] = await _journal(mod, T0_EPOCH)
    res["cover_rows"] = [r for r in (res["journal_since_start"] or [])
                         if str(r.get("source") or "").startswith(
                             "summary_cover")]
    res["budget_after"] = await _budget_snapshot(mod, "after")
    res["throttle_after"] = await mod.sqlite_fetch(
        "SELECT scope, chat_id, user_id, burst_left, last_ts "
        "FROM throttle_state WHERE scope='image_freq' AND chat_id=? "
        "ORDER BY user_id", (WORK_CHAT,))
    before, after = res["budget_before"], res["budget_after"]
    res["checks"] = {
        "cover_row_committed": bool(
            res["cover_rows"]
            and res["cover_rows"][-1].get("status") == "committed"
            and res["cover_rows"][-1].get("source") == "summary_cover:base"),
        "chat_used_unchanged": before.get("chat_used") == after.get("chat_used"),
        "shared_plus_one": (int(after.get("global_used") or 0)
                            - int(before.get("global_used") or 0)) == 1,
        "cover_used_plus_one": (int(after.get("global_cover_used") or 0)
                                - int(before.get("global_cover_used") or 0))
        == 1,
        "freq_charges_untouched": res["throttle_before"] == res["throttle_after"],
    }
    # exact restore of the original overrides
    root2 = await chat_params.get_all_chat_params(WORK_CHAT, pg=mod.CTX.pg)
    ov = dict((root2 or {}).get("overrides") or {})
    for key in TOUCHED_KEYS:
        if key in orig:
            ov[key] = orig[key]
        else:
            ov.pop(key, None)
    try:
        await chat_params.set_chat_params(WORK_CHAT, {"overrides": ov},
                                          changed_by=None, pg=mod.CTX.pg)
        res["restore"] = "ok"
    except Exception as exc:  # noqa: BLE001
        res["restore"] = "failed: %s" % type(exc).__name__
    await _invalidate(mod)
    await asyncio.sleep(2.0)
    res["reserve_mode_after_restore"] = await _reserve_mode(mod)
    cfg_after = None
    for attempt in range(3):
        st2, cfg2 = await mod.CTX.api.req("GET", "/api/config",
                                          chat_id=WORK_CHAT)
        cfg_after = {"http": st2, "items": _pick_cfg(cfg2)}
        if _cfg_map(cfg_after["items"]) == _cfg_map(
                res["config_before"]["items"]):
            break
        await asyncio.sleep(20)
    res["config_after"] = cfg_after
    res["config_matches"] = (_cfg_map(cfg_after.get("items"))
                             == _cfg_map(res["config_before"]["items"]))
    res["ok"] = bool(cover_ok and all(res["checks"].values())
                     and res.get("restore") == "ok"
                     and res["config_matches"]
                     and res["reserve_mode_after_restore"].get("mode")
                     == "legacy")
    mod.save("c5-cover-fix.json", res)
    out("C5", json.dumps({"cover_ok": cover_ok, "checks": res["checks"],
                          "restore": res.get("restore"),
                          "matches": res["config_matches"]},
                         ensure_ascii=False, default=str)[:700])
    out("DONE", "c5-cover-fix")
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC94B FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC94B RC=%d" % rc, flush=True)
    os._exit(rc)
