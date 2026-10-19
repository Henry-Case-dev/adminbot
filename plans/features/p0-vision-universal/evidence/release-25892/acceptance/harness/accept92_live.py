# -*- coding: utf-8 -*-
"""ACCEPTANCE-92 — controlled live acceptance for prod 2.58.92 (1d367e4c).

One controlled process ON the production host (NOT the poller): imports the
deployed modules through the proven ACCEPTANCE-91 bootstrap (uploaded as
/tmp/accept92_base.py), sends real Telegram messages, uses the real SQLite/PG
stores and the real providers. No product code is modified; writes are limited
to the synthetic user's test messages (deleted afterwards by the cleanup
phase), the temporary smart_messages fidelity row and the temporary vision
model switch (kept only if the live probe proves it works, reverted otherwise).

Scenarios (release-25892 §4c/§4d/§4e/§4f/§4h):
  S2  per-chat /api/vision/state + /api/vision/test (X-Chat-Id vs global vs
      foreign chat; no secret leak)
  S5  live vision probe (current model) + ONE alternative free OpenRouter
      image model attempt via the standard setting (keep if OK, revert if not)
  S3  reply-to-photo: recognize_image target = photo from the replied message
      (+ replay dedup check; + repeat after a successful model switch =
      positive recognition)
  S4  reply "это правда?": fact_check claim = replied text, target = replied
  S7  economics / journal window since T0

Evidence: /tmp/accept92/evidence/*.json
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
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
ADMIN_ID = 5885953495
T0_EPOCH = 1792365948          # deploy 2.58.92 T0 = 2026-10-18 23:25:48 UTC
ALT_MODEL = "nvidia/nemotron-3.5-super-vl:free"   # candidate (1 attempt)
PROBE_SPACING_S = 12.0         # /api/vision/test: server limit 10 s/user
PREFERRED_PHOTOS = (1165606, 1165607)  # real user photos kept in the chat


def out(tag, text):
    print("ACC92 %s | %s" % (tag, text), flush=True)


def load_base():
    spec = importlib.util.spec_from_file_location("accept92_base",
                                                  "/tmp/accept92_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _api_json(api, method, path, chat_id=None, body=None):
    st, payload = await api.req(method, path, chat_id=chat_id,
                                json_body=body)
    return {"http": st, "body": payload}


async def _safe(tag, fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        import traceback
        out(tag, "FAILED %s: %s" % (type(exc).__name__, str(exc)[:300]))
        traceback.print_exc()
        return {"error": "%s: %s" % (type(exc).__name__, str(exc)[:300])}


# ─────────────────────────── S2: per-chat state ─────────────────────────────

async def s2_perchat_state(mod):
    api = mod.CTX.api
    res = {"scenario": "S2-perchat-state"}
    res["owner_get_before"] = await _api_json(
        api, "GET", "/api/vision/state", chat_id=WORK_CHAT)
    # live probe through the admin-TMA route (real provider call)
    res["owner_probe"] = await _api_json(
        api, "POST", "/api/vision/test", chat_id=WORK_CHAT, body={})
    res["owner_get_after"] = await _api_json(
        api, "GET", "/api/vision/state", chat_id=WORK_CHAT)
    res["global_get"] = await _api_json(api, "GET", "/api/vision/state")
    # foreign chat: a DM that is NOT the admin's own (no access by
    # can_access_chat -> must fall back to the global layer, no leak)
    res["foreign_get"] = await _api_json(
        api, "GET", "/api/vision/state", chat_id=SYNTH_USER)
    # secondary boundary: a user without vision-key rights (403, no data)
    try:
        import httpx
        headers = {"X-Telegram-Init-Data": mod.make_init_data(SYNTH_USER)}
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=20.0) as c:
            r = await c.get("/api/vision/state", headers=headers)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        res["no_rights_user"] = {"http": r.status_code, "body": body}
    except Exception as exc:  # noqa: BLE001
        res["no_rights_user"] = {"error": type(exc).__name__}
    # secret leak check (raw key must never appear in any response)
    from services import mca_vision
    route = mca_vision.resolve_route()
    key = mca_vision.api_key_for(route) or ""
    blob = json.dumps(res, ensure_ascii=False, default=str)
    res["secret_leak"] = bool(key) and (key in blob)
    b1 = res["owner_get_before"]["body"] or {}
    b2 = (res["owner_probe"]["body"] or {}).get("state") or {}
    b3 = res["owner_get_after"]["body"] or {}
    b4 = res["global_get"]["body"] or {}
    b5 = res["foreign_get"]["body"] or {}
    res["checks"] = {
        "owner_requested_true": bool(b1.get("requested")),
        "owner_reason_not_disabled": b1.get("reason") != "vision_disabled",
        "owner_model": b1.get("model"),
        "probe_http": res["owner_probe"]["http"],
        "probe_state_requested_true": bool(b2.get("requested")),
        "probe_state_reason_not_disabled": b2.get("reason") != "vision_disabled",
        "after_probe_requested_true": bool(b3.get("requested")),
        "after_probe_reason_not_disabled": b3.get("reason") != "vision_disabled",
        "global_requested_false": b4.get("requested") is False,
        "global_reason_disabled": b4.get("reason") == "vision_disabled",
        "foreign_requested_false": b5.get("requested") is False,
        "foreign_reason_disabled": b5.get("reason") == "vision_disabled",
        "no_rights_http": (res.get("no_rights_user") or {}).get("http"),
        "no_secret_leak": not res["secret_leak"],
    }
    mod.save("s2-perchat-state.json", res)
    out("S2", json.dumps(res["checks"], ensure_ascii=False))
    return res


# ─────────────────────── S5: probe + alternative model ──────────────────────

async def _openrouter_key_status(mod):
    """Account-level OpenRouter status (numbers only; R17-safe, no label)."""
    from services import mca_vision
    route = mca_vision.resolve_route()
    key = mca_vision.api_key_for(route)
    if not key:
        return {"error": "no key"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.get("https://openrouter.ai/api/v1/auth/key",
                            headers={"Authorization": "Bearer " + key})
        try:
            d = (r.json() or {}).get("data") or {}
        except Exception:
            return {"http": r.status_code, "parse": "fail"}
        return {"http": r.status_code, "usage": d.get("usage"),
                "limit": d.get("limit"),
                "limit_remaining": d.get("limit_remaining"),
                "is_free_tier": d.get("is_free_tier"),
                "rate_limit": d.get("rate_limit")}
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}


async def _alt_model_check(mod):
    """Re-verify the candidate against the live OpenRouter model list."""
    res = {"candidate": ALT_MODEL}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get("https://openrouter.ai/api/v1/models")
        data = (r.json() or {}).get("data") or []
        free_img = []
        for m in data:
            arch = m.get("architecture") or {}
            if "image" not in (arch.get("input_modalities") or []):
                continue
            p = m.get("pricing") or {}
            try:
                pr = float(p.get("prompt") or 1)
                co = float(p.get("completion") or 1)
            except (TypeError, ValueError):
                continue
            if pr == 0 and co == 0:
                free_img.append(str(m.get("id")))
        res["free_image_input_count"] = len(free_img)
        res["candidate_in_list"] = ALT_MODEL in free_img
        res["in_free_image_list"] = ALT_MODEL in free_img
        res["free_image_sample"] = free_img[:14]
    except Exception as exc:  # noqa: BLE001
        res["error"] = type(exc).__name__
    return res


async def _switch_model(mod, value):
    st, body = await mod.CTX.api.req(
        "POST", "/api/config",
        json_body={"items": [{"key": "models.vision_model", "value": value}],
                   "updated_at": None})
    reload_state = "ok"
    try:
        await mod.CTX.cache.reload()
    except Exception as exc:  # noqa: BLE001
        reload_state = type(exc).__name__
    return {"http": st, "body": body, "cache_reload": reload_state}


async def s5_probe_and_model(mod, s2):
    res = {"scenario": "S5-vision-probe"}
    from services import mca_vision
    from services import hot_config as hot
    from config.settings import settings as st
    api = mod.CTX.api
    orig_model = str(hot.get(mca_vision.VISION_MODEL_KEY,
                             st.VISION_MODEL) or "")
    route = mca_vision.resolve_route(WORK_CHAT)
    res["orig_model"] = orig_model
    res["orig_route"] = {"source": route.source,
                         "provider": mca_vision.provider_host(route.base_url),
                         "api_type": route.api_type}
    res["key_status_before"] = await _openrouter_key_status(mod)
    probe1 = (s2 or {}).get("owner_probe") or {}
    res["probe_current"] = probe1
    res["probe_current_ok"] = bool((probe1.get("body") or {}).get("ok"))
    res["decision"] = "current_model_ok" if res["probe_current_ok"] \
        else "current_failed"
    if not res["probe_current_ok"]:
        alt_check = await _alt_model_check(mod)
        res["alt_check"] = alt_check
        if alt_check.get("in_free_image_list"):
            sw = await _switch_model(mod, ALT_MODEL)
            res["switch_to_alt"] = sw
            if sw.get("http") == 200:
                await asyncio.sleep(PROBE_SPACING_S)
                res["probe_alt"] = await _api_json(
                    api, "POST", "/api/vision/test", chat_id=WORK_CHAT,
                    body={})
                res["probe_alt_ok"] = bool(
                    (res["probe_alt"].get("body") or {}).get("ok"))
                res["key_status_after"] = await _openrouter_key_status(mod)
                if res["probe_alt_ok"]:
                    res["decision"] = "kept_alt_model"
                else:
                    res["revert"] = await _switch_model(mod, orig_model)
                    await asyncio.sleep(1.0)
                    res["state_after_revert"] = await _api_json(
                        api, "GET", "/api/vision/state", chat_id=WORK_CHAT)
                    res["decision"] = "reverted_alt_failed"
            else:
                res["decision"] = "switch_rejected"
        else:
            res["decision"] = "alt_not_in_free_image_list"
    res["state_end"] = await _api_json(api, "GET", "/api/vision/state",
                                       chat_id=WORK_CHAT)
    mod.save("s5-vision-probe.json", res)
    out("S5", json.dumps({"decision": res["decision"],
                          "probe_current_ok": res["probe_current_ok"],
                          "probe_alt_ok": res.get("probe_alt_ok")},
                         ensure_ascii=False))
    return res


# ─────────────────────────── S3: reply-to-photo ─────────────────────────────

async def _photo_candidates(mod):
    rows = await mod.sqlite_fetch(
        "SELECT asset_id, tg_message_id, asset_kind, mime, byte_size, "
        "width, height, file_id, file_unique_id, content_hash "
        "FROM mca_media_assets WHERE chat_id=? AND asset_kind='photo' "
        "AND byte_size>=20000 ORDER BY tg_message_id DESC LIMIT 12",
        (WORK_CHAT,))
    have = {int(r["tg_message_id"] or 0) for r in rows}
    for mid in PREFERRED_PHOTOS:          # ensure known-good photos present
        if mid in have:
            continue
        extra = await mod.sqlite_fetch(
            "SELECT asset_id, tg_message_id, asset_kind, mime, byte_size, "
            "width, height, file_id, file_unique_id, content_hash "
            "FROM mca_media_assets WHERE chat_id=? AND asset_kind='photo' "
            "AND tg_message_id=? LIMIT 1", (WORK_CHAT, mid))
        rows.extend(extra)
    for r in rows:
        try:
            cur = await mod.CTX.db.db.execute(
                "SELECT status, revision, analyzer_model, error_reason, "
                "completed_at FROM mca_media_analyses WHERE asset_id=? "
                "ORDER BY id DESC LIMIT 1", (str(r["asset_id"]),))
            row = await cur.fetchone()
            r["last_analysis"] = dict(row) if row is not None else None
        except Exception:
            r["last_analysis"] = None
        try:
            cur = await mod.CTX.db.db.execute(
                "SELECT 1 FROM bot_replies WHERE chat_id=? AND "
                "tg_message_id=? LIMIT 1",
                (WORK_CHAT, int(r["tg_message_id"] or 0)))
            r["bot_sent"] = (await cur.fetchone()) is not None
        except Exception:
            r["bot_sent"] = None
    return rows


def _pick_asset(rows, exclude_mids=()):
    excl = {int(x) for x in exclude_mids if x}
    # 1) preferred known-good real user photos kept in the chat
    for mid in PREFERRED_PHOTOS:
        if mid in excl:
            continue
        for r in rows:
            if int(r["tg_message_id"] or 0) == mid:
                return r, "preferred_kept_user_photo"
    # 2) newest not-ready photo that was not sent by the bot
    for r in rows:
        mid = int(r["tg_message_id"] or 0)
        if mid in excl or r.get("bot_sent"):
            continue
        st = (r.get("last_analysis") or {}).get("status")
        if st != "ready":
            return r, "not_ready_not_bot_sent"
    # 3) any not-ready photo
    for r in rows:
        mid = int(r["tg_message_id"] or 0)
        if mid in excl:
            continue
        if (r.get("last_analysis") or {}).get("status") != "ready":
            return r, "not_ready_any"
    # 4) fallback: newest not excluded
    for r in rows:
        if int(r["tg_message_id"] or 0) not in excl:
            return r, "fallback_newest"
    return None, "none"


async def s3_reply_photo(mod, label="vision-reply92",
                         out_name="s3-vision-reply.json",
                         exclude_mids=()):
    res = {"scenario": "S3-reply-to-photo", "label": label}
    assets = await _photo_candidates(mod)
    res["candidates"] = [
        {"asset_id": a.get("asset_id"), "tg_message_id": a.get("tg_message_id"),
         "byte_size": a.get("byte_size"), "mime": a.get("mime"),
         "bot_sent": a.get("bot_sent"),
         "last_analysis": a.get("last_analysis"),
         "file_id_len": len(str(a.get("file_id") or ""))}
        for a in assets]
    asset, why = _pick_asset(assets, exclude_mids)
    res["choice"] = why
    if asset is None:
        res["ok"] = False
        res["error"] = "no photo assets"
        mod.save(out_name, res)
        return res
    res["asset"] = {"asset_id": asset["asset_id"],
                    "tg_message_id": asset["tg_message_id"],
                    "byte_size": asset["byte_size"], "mime": asset["mime"],
                    "last_analysis": asset.get("last_analysis")}
    photo_msg = mod.make_photo_message(asset, caption=None)
    anchor = await mod.CTX.rec.send_message(
        WORK_CHAT, "🧪 Приёмка 2.58.92 · reply-на-фото (контроль).")
    res["anchor_mid"] = anchor.message_id
    t = await mod.run_turn("бот, что тут?", msg_id=anchor.message_id,
                           reply_to=photo_msg, label=label, timeout=300)
    res["turns"] = [{"phrase": "бот, что тут?", **mod._strip_turn(t)}]
    tool = next((x for x in t.get("tool_calls", [])
                 if x.get("tool") == "recognize_image"), None)
    if tool is None:
        anchor2 = await mod.CTX.rec.send_message(
            WORK_CHAT, "🧪 Приёмка 2.58.92 · reply-на-фото (повтор фразы).")
        res["anchor2_mid"] = anchor2.message_id
        t2 = await mod.run_turn("бот, прочитай надпись",
                                msg_id=anchor2.message_id, reply_to=photo_msg,
                                label=label + "-retry", timeout=300)
        res["turns"].append({"phrase": "бот, прочитай надпись",
                             **mod._strip_turn(t2)})
        tool = next((x for x in t2.get("tool_calls", [])
                     if x.get("tool") == "recognize_image"), None)
        t = t2
    target = ((tool or {}).get("args") or {}).get("target") or {}
    res["tool_called"] = tool is not None
    res["tool_target"] = target
    res["target_is_reply_photo"] = (
        int(target.get("message_id") or -1) == int(asset["tg_message_id"]))
    res["target_not_question"] = (
        int(target.get("message_id") or -1) != int(anchor.message_id))
    res["tool_result"] = tool
    res["plan_caps"] = mod._turn_plan_caps(t)
    res["status"] = (tool or {}).get("status")
    res["positive_recognition"] = (tool or {}).get("status") == "ready"
    res["ok"] = bool(res["tool_called"] and res["target_is_reply_photo"])
    # fresh analysis row for the target asset (proof of a real analysis)
    try:
        cur = await mod.CTX.db.db.execute(
            "SELECT status, revision, analyzer_model, error_reason, "
            "completed_at FROM mca_media_analyses WHERE asset_id=? "
            "ORDER BY id DESC LIMIT 1", (str(asset["asset_id"]),))
        row = await cur.fetchone()
        res["analysis_row_after"] = dict(row) if row is not None else None
    except Exception as exc:  # noqa: BLE001
        res["analysis_row_after"] = {"error": type(exc).__name__}
    # replay of the same update: dedup must not produce a second answer
    try:
        s_before = len(mod.CTX.rec.sends)
        t_r = await mod.run_turn("бот, что тут?", msg_id=anchor.message_id,
                                 reply_to=photo_msg,
                                 label=label + "-replay", timeout=120)
        res["replay"] = {"new_sends": len(mod.CTX.rec.sends) - s_before,
                         "tool_calls": [x.get("tool")
                                        for x in t_r.get("tool_calls", [])],
                         "handled": t_r.get("handled"),
                         "elapsed_s": t_r.get("elapsed_s")}
    except Exception as exc:  # noqa: BLE001
        res["replay"] = {"error": type(exc).__name__}
    mod.save(out_name, res)
    out("S3", json.dumps({k: res[k] for k in (
        "label", "tool_called", "target_is_reply_photo",
        "target_not_question", "status", "positive_recognition")},
        ensure_ascii=False))
    return res


# ─────────────────────── S4: reply "это правда?" ────────────────────────────

async def s4_factcheck_reply(mod):
    res = {"scenario": "S4-factcheck-reply"}
    claim = "Вода закипает при 100 °C на уровне моря."
    claim_msg = await mod.CTX.rec.send_message(WORK_CHAT, claim)
    res["claim_mid"] = claim_msg.message_id
    res["claim_text"] = claim
    try:
        await mod.sqlite_exec(
            "DELETE FROM smart_messages WHERE chat_id=? AND "
            "tg_message_id=?", (WORK_CHAT, claim_msg.message_id))
    except Exception:
        pass
    try:
        row_id = await mod.CTX.db.save_smart_message(
            SYNTH_USER, WORK_CHAT, claim, claim_msg.message_id,
            int(time.time()), "text", "Acceptance",
            message_id=claim_msg.message_id, origin_type="user")
        res["smart_message_row"] = row_id
    except Exception as exc:  # noqa: BLE001
        res["smart_message_error"] = "%s: %s" % (type(exc).__name__,
                                                 str(exc)[:160])
    anchor = await mod.CTX.rec.send_message(
        WORK_CHAT, "🧪 Приёмка 2.58.92 · reply-фактчек (контроль).")
    res["anchor_mid"] = anchor.message_id
    t = await mod.run_turn("бот, это правда?", msg_id=anchor.message_id,
                           reply_to=claim_msg, label="fact-reply92",
                           timeout=360)
    res["turns"] = [{"phrase": "бот, это правда?", **mod._strip_turn(t)}]
    tool = next((x for x in t.get("tool_calls", [])
                 if x.get("tool") == "fact_check"), None)
    args = (tool or {}).get("args") or {}
    res["tool_called"] = tool is not None
    res["tool_args"] = args
    res["claim_from_replied"] = str(args.get("claim") or "").strip() == claim
    res["claim_not_question"] = (
        str(args.get("claim") or "").strip() != "бот, это правда?")
    res["target_is_replied"] = (
        int((args.get("target") or {}).get("message_id") or -1)
        == int(claim_msg.message_id))
    res["tool_result"] = tool
    res["status_ready"] = (tool or {}).get("status") == "ready"
    res["ok"] = bool(res["tool_called"] and res["claim_from_replied"]
                     and res["target_is_replied"])
    mod.save("s4-factcheck-reply.json", res)
    out("S4", json.dumps({k: res[k] for k in (
        "tool_called", "claim_from_replied", "target_is_replied",
        "status_ready")}, ensure_ascii=False))
    return res


# ─────────────────────────── S7: economics ──────────────────────────────────

async def s7_economics(mod, start_epoch):
    res = {"scenario": "S7-economics", "start_epoch": start_epoch,
           "t0_epoch": T0_EPOCH}
    try:
        res["head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
        res["tracked_mod"] = int(subprocess.check_output(
            "git status --porcelain | grep -v '^??' | wc -l",
            cwd=APP, shell=True, text=True).strip() or 0)
        res["branch"] = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=APP,
            text=True).strip()
    except Exception:
        pass
    try:
        import httpx
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=10.0) as c:
            r = await c.get("/healthz")
        res["healthz"] = r.text[:200]
    except Exception as exc:  # noqa: BLE001
        res["healthz_error"] = type(exc).__name__
    try:
        res["service"] = subprocess.check_output(
            "systemctl show admin_bot -p MainPID -p NRestarts -p ActiveState "
            "-p SubState -p ExecMainStatus --no-pager", shell=True,
            text=True).strip().replace("\n", " ")
    except Exception:
        pass
    try:
        res["usage_since_t0"] = await mod.pg_fetch(
            "SELECT step, COUNT(*) n, COALESCE(SUM(cost_usd),0) cost, "
            "COALESCE(SUM(input_tokens+output_tokens),0) tokens, "
            "MAX(ts) last FROM llm_usage_events WHERE ts >= to_timestamp($1) "
            "GROUP BY step ORDER BY n DESC", T0_EPOCH)
        res["usage_acceptance"] = await mod.pg_fetch(
            "SELECT step, COUNT(*) n, COALESCE(SUM(cost_usd),0) cost, "
            "COALESCE(SUM(input_tokens+output_tokens),0) tokens "
            "FROM llm_usage_events WHERE ts >= to_timestamp($1) "
            "GROUP BY step ORDER BY n DESC", start_epoch)
        res["budget"] = await mod.pg_fetch(
            "SELECT day, scope, metric, used FROM worker_budget "
            "WHERE metric='image_calls' ORDER BY day DESC, scope LIMIT 16")
        res["reservations_since_t0"] = await mod.pg_fetch(
            "SELECT reservation_key, status, error_code, delivery_failed, "
            "created_at FROM image_reservation "
            "WHERE created_at >= to_timestamp($1) ORDER BY created_at",
            T0_EPOCH)
    except Exception as exc:  # noqa: BLE001
        res["pg_error"] = type(exc).__name__
    try:
        res["mca_events_since_t0"] = await mod.sqlite_fetch(
            "SELECT event_name, outcome, reason_code, COUNT(*) n, MAX(ts) last "
            "FROM mca_events WHERE ts >= ? GROUP BY 1,2,3 "
            "ORDER BY n DESC LIMIT 40", (T0_EPOCH,))
        res["mca_errors_since_t0"] = await mod.sqlite_fetch(
            "SELECT COUNT(*) n FROM mca_events WHERE ts >= ? AND "
            "level IN ('ERROR','CRITICAL')", (T0_EPOCH,))
        res["jobs_since_t0"] = await mod.sqlite_fetch(
            "SELECT job_id, kind, status, reason_code, attempt, created_at, "
            "updated_at FROM task_jobs WHERE created_at >= ? "
            "ORDER BY created_at DESC LIMIT 30", (T0_EPOCH,))
        res["vision_jobs_recent"] = await mod.sqlite_fetch(
            "SELECT job_id, kind, status, reason_code, attempt, created_at, "
            "updated_at FROM task_jobs WHERE kind LIKE 'vision%' "
            "ORDER BY updated_at DESC LIMIT 20", ())
        res["user_version"] = (await mod.sqlite_fetch("PRAGMA user_version"))[0]
    except Exception as exc:  # noqa: BLE001
        res["sqlite_error"] = type(exc).__name__
    mod.save("s7-econ.json", res)
    out("S7", "done")
    return res


# ─────────────────────────── main ───────────────────────────────────────────

async def main() -> int:
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    mod = load_base()
    mod.EVID = "/tmp/accept92/evidence"
    os.makedirs(mod.EVID, exist_ok=True)
    await mod.bootstrap()
    mod.CTX.api = mod.Api()
    start_epoch = int(time.time())
    out("START_EPOCH", start_epoch)

    s2 = await _safe("S2", s2_perchat_state, mod)
    s5 = await _safe("S5", s5_probe_and_model, mod, s2)
    s3 = await _safe("S3", s3_reply_photo, mod)
    s3b = None
    if isinstance(s5, dict) and s5.get("decision") == "kept_alt_model":
        await asyncio.sleep(2.0)
        excl = ((s3 or {}).get("asset") or {}).get("tg_message_id")
        s3b = await _safe("S3b", s3_reply_photo, mod,
                          "vision-reply92-repeat", "s3b-vision-reply-repeat.json",
                          (excl,) if excl else ())
    s4 = await _safe("S4", s4_factcheck_reply, mod)
    s7 = await _safe("S7", s7_economics, mod, start_epoch)
    final_state = await _safe(
        "FIN", _api_json, mod.CTX.api, "GET", "/api/vision/state",
        chat_id=WORK_CHAT)

    summary = {
        "final_state": final_state,
        "start_epoch": start_epoch,
        "t0_epoch": T0_EPOCH,
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "s2_checks": (s2 or {}).get("checks"),
        "s5_decision": (s5 or {}).get("decision"),
        "s5_probe_current_ok": (s5 or {}).get("probe_current_ok"),
        "s5_probe_alt_ok": (s5 or {}).get("probe_alt_ok"),
        "s5_key_status_before": (s5 or {}).get("key_status_before"),
        "s3_target_ok": (s3 or {}).get("target_is_reply_photo"),
        "s3_status": (s3 or {}).get("status"),
        "s3_positive": (s3 or {}).get("positive_recognition"),
        "s3_replay": (s3 or {}).get("replay"),
        "s3b_positive": (s3b or {}).get("positive_recognition"),
        "s3b_target_ok": (s3b or {}).get("target_is_reply_photo"),
        "s4_ok": (s4 or {}).get("ok"),
        "s4_status": ((s4 or {}).get("tool_result") or {}).get("status"),
        "sends": mod._sanitize_sends(mod.CTX.rec.sends),
        "tool_calls": [t.get("tool") for t in mod.CTX.tool_calls],
        "vision_transport_calls": len(mod.CTX.vision_transport_calls),
        "postgen": mod.CTX.postgen,
    }
    mod.save("summary.json", summary)
    try:
        from services import mca_events
        flushed = await mca_events.flush_events(mod.CTX.db)
        out("FLUSH", "mca_events flushed=%s" % flushed)
    except Exception as exc:  # noqa: BLE001
        out("FLUSH", "failed: %s" % type(exc).__name__)
    out("DONE", "evidence=%s" % mod.EVID)
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC92 FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC92 RC=%d" % rc, flush=True)
    os._exit(rc)
