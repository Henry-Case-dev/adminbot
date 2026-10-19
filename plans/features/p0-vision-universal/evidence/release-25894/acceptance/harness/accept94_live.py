# -*- coding: utf-8 -*-
"""ACCEPTANCE-94 — combined live acceptance for prod 2.58.94 (9072347b).

VISION-DL-FIX (positive recognition) + CFG-02C §Ф6 (cover/user budget
isolation), on the deployed build. Runs ON the production host through the
proven ACCEPTANCE-91/92/93 bootstrap (uploaded as /tmp/accept94_base.py):
real Telegram delivery (local Bot API session, prod-faithful), real
SQLite/PG stores, real providers. No product code is modified.

Paid budget of this wave: exactly 1 generation + 1 cover + 1 meme
(+1 free honest denial attempt). All temporary per-chat config changes are
restored exactly at the end (P0 snapshot -> C4 restore).

Phases:
  P0 pre-state (read-only): HEAD/service, vision state (per-chat+global),
     image-generation capability state, reserve/freq modes, admin budget
     view, per-chat config + original overrides, PG/SQLite snapshots.
  B1 (b) POSITIVE recognition: fresh photo asset -> reply "бот, что тут?" ->
     recognize_image -> download->decode->vision->store (prod worker) ->
     mca_media_analyses 0 -> N (ready) -> description -> delivery mid.
     Bounded provider retry (1) on 502/429, then honest status.
  G0 generation-readiness: resolve image_generation capability; if the
     baseline gate is not READY (chat day quota), apply the documented temp
     config (budgets ON + daily 20 + freq ON) so the paid generations of this
     wave are allowed; recorded as a temp acceptance premise.
  B2 (c) postgen: "бот, надо нарисовать <объект>" -> 1 generation -> photo
     (mid) -> image_postgen_vision -> description from the final bitmap
     (not prompt echo) -> delivery mid. Honest block if analysis fails.
  C1 (d) showcase (read-only): served app.js contains the CFG-02C label;
     admin GET /api/workers/budget carries cover fields/breakdown.
  C2 (d) cover isolation: temp premise budgets ON + user daily=0 + freq ON ->
     ONE base cover via the standard summary test-run -> typed journal row
     source='summary_cover:base' committed, per-chat user counter NOT
     incremented, shared +1, cover_used +1, freq charges untouched.
  C3 (d) meme isolation: user path at daily=0 -> honest denial before any
     paid call (provider_calls=0, no journal rows, cover aggregate
     unchanged); then temp daily=20 -> ONE meme generated -> typed user
     journal row (direct), per-chat +1, cover aggregate unchanged.
  C4 (d) restore: exact restore of the original per-chat overrides + verify
     (reserve legacy/budgets_off, freq switch_off, config values match).
  E economics: budget deltas, journal rows since start, LLM usage counts,
     mca image events, sqlite user_version, freq charges.
  F cleanup register: every bot-sent test mid of this wave + known leftovers
     -> spec /tmp/accept94_cleanup_mids.json for the cleanup wave (owner rule).

Evidence: /tmp/accept94/evidence/*.json (+ cover94-base.png).
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
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
T0_EPOCH = 1792397900          # deploy 2.58.94 T0 = 2026-10-19 08:18:20 UTC
EVID = "/tmp/accept94/evidence"
COVER_WINDOW_HOURS = 6
SYNTH_MIDS = (990940101, 990940102, 990940103)   # fresh synthetic ids
LEFTOVER_MIDS = (1166064, 1166066)   # ACCEPTANCE-93 denials (cleanup debt)
PREFERRED_PHOTO_MID = 1165720        # fresh owner photo (92B pre-check OK)
EXCLUDE_PHOTOS = {1165606, 1165607}  # legacy assets (data finding, 92B)
TOUCHED_KEYS = ("flags.budgets_enabled", "limits.image_daily_limit",
                "limits.image_freq_limit_enabled")
KEEP_CFG_KEYS = ("flags.budgets_enabled", "limits.image_daily_limit",
                 "limits.image_freq_limit_enabled",
                 "limits.image_freq_limit_burst",
                 "limits.image_freq_limit_cooldown_seconds",
                 "limits.image_freq_limit_mode")
GEN_READY_LIMIT = 20
CFG_LABEL = "Обложки сводок здесь не учитываются"


def out(tag, text):
    print("ACC94 %s | %s" % (tag, text), flush=True)


def load_base():
    spec = importlib.util.spec_from_file_location("accept94_base",
                                                  "/tmp/accept94_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _safe(tag, fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        import traceback
        out(tag, "FAILED %s: %s" % (type(exc).__name__, str(exc)[:300]))
        traceback.print_exc()
        return {"error": "%s: %s" % (type(exc).__name__, str(exc)[:300])}


def _strip_turn(t):
    return {k: v for k, v in t.items() if not k.startswith("_")}


def _sanitize_sends(sends):
    return [{k: v for k, v in s.items() if not k.startswith("_")}
            for s in sends]


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


def _cfg_map(cfg_items):
    return {str(it.get("key")): it.get("value") for it in (cfg_items or [])}


def _budget_chat_entry(budget):
    if not isinstance(budget, dict):
        return None
    for entry in (budget.get("chats") or []):
        if str(entry.get("scope")) == "chat:%d" % WORK_CHAT:
            return entry
    return None


async def _budget_snapshot(mod, tag):
    api = mod.CTX.api
    st, body = await api.req("GET", "/api/workers/budget")
    entry = _budget_chat_entry(body)
    return {"tag": tag, "http": st, "global": (body or {}).get("global"),
            "chat": entry, "day": (body or {}).get("day"),
            "timezone": (body or {}).get("timezone")}


def _budget_numbers(snap):
    """Compact numbers from a budget snapshot (evidence-friendly)."""
    try:
        g = (snap.get("global") or {}).get("image_calls") or {}
        c = (snap.get("chat") or {}).get("image_calls") or {}
        u = ((snap.get("chat") or {}).get("image_usage") or {})
        cover = u.get("cover") or {}
        return {
            "global_used": g.get("used"), "global_limit": g.get("limit"),
            "global_cover_used": g.get("cover_used"),
            "chat_used": c.get("used"), "chat_limit": c.get("limit"),
            "chat_limit_source": c.get("source"),
            "chat_reserve_path": u.get("reserve_path"),
            "chat_reserve_reason": u.get("reserve_reason"),
            "cover_requests": cover.get("requests"),
            "cover_success": cover.get("success"),
        }
    except Exception:
        return {}


async def _freq_state(mod):
    from services import image_generation as ig
    st = await ig.image_freq_state(WORK_CHAT, SYNTH_USER)
    return {"applied": getattr(st, "applied", None),
            "allowed": getattr(st, "allowed", None),
            "remaining_seconds": getattr(st, "remaining_seconds", None),
            "reason": getattr(st, "reason", None),
            "limits": str(getattr(st, "limits", None))}


async def _reserve_mode(mod):
    from services import image_generation as ig
    mode, reason = await ig.image_reserve_mode(WORK_CHAT)
    return {"mode": mode, "reason": reason}


async def _cap_state(mod):
    from services import capability_registry as caps
    st = await caps.resolve("image_generation", WORK_CHAT, use_cache=False)
    return {"status": st.status, "reason_code": st.reason_code,
            "detail": st.detail, "tryable": st.tryable,
            "last_result": st.last_result, "last_result_code": st.last_result_code}


async def _journal_rows(mod, since):
    return await mod.pg_fetch(
        "SELECT reservation_key, chat_id, source, status, error_code, "
        "delivery_failed, day, created_at, updated_at "
        "FROM image_reservation WHERE created_at >= to_timestamp($1) "
        "ORDER BY created_at", since)


async def _wb_rows(mod):
    return await mod.pg_fetch(
        "SELECT day, scope, metric, used FROM worker_budget "
        "WHERE metric='image_calls' ORDER BY day DESC, scope LIMIT 12")


async def _throttle_rows(mod):
    return await mod.sqlite_fetch(
        "SELECT scope, chat_id, user_id, burst_left, last_ts "
        "FROM throttle_state WHERE scope='image_freq' AND chat_id=? "
        "ORDER BY user_id", (WORK_CHAT,))


async def _analyses_total(mod):
    rows = await mod.sqlite_fetch(
        "SELECT COUNT(*) n FROM mca_media_analyses", ())
    return int((rows[0] or {}).get("n") or 0) if rows else 0


async def _invalidate_caches(mod, *, reason="acceptance94"):
    """After a per-chat config write: drop BOTH caches of THIS process.

    * ChatParamsCache (limits/flags resolution);
    * capability_registry resolve cache (its config token does NOT include
      per-chat override values — stale DISABLED/QUOTA state would otherwise
      live up to TTL 60s; observed in ACCEPTANCE-93).
    """
    try:
        from services.chat_params import get_chat_params_cache
        cpc = get_chat_params_cache()
        if cpc is not None:
            await cpc.invalidate_chat(WORK_CHAT)
    except Exception as exc:  # noqa: BLE001
        out("CACHE", "chat params invalidate failed: %s"
            % type(exc).__name__)
    try:
        from services import capability_registry as caps
        caps.invalidate("image_generation", WORK_CHAT, reason=reason)
    except Exception as exc:  # noqa: BLE001
        out("CACHE", "capability invalidate failed: %s" % type(exc).__name__)


async def _set_chat_config(mod, items, tag, *, timeout=60.0):
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=timeout) as c:
        r = await c.post("/api/config", headers={
            "X-Telegram-Init-Data": mod.make_init_data(),
            "X-Chat-Id": str(WORK_CHAT)},
            json={"items": items, "updated_at": None})
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
    await _invalidate_caches(mod)
    out("CFG", "%s http=%s body=%s" % (
        tag, r.status_code, json.dumps(body, ensure_ascii=False)[:300]))
    return {"http": r.status_code, "body": body}


# ─────────────────────────────── P0 ────────────────────────────────────────

async def p0_pre_state(mod):
    from services import image_generation as ig
    from services import chat_params
    res = {"phase": "P0-pre-state",
           "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "t0_epoch": T0_EPOCH}
    try:
        res["head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
        res["branch"] = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=APP,
            text=True).strip()
        res["tracked_mod"] = int(subprocess.check_output(
            "git status --porcelain | grep -v '^??' | wc -l",
            cwd=APP, shell=True, text=True).strip() or 0)
    except Exception as exc:  # noqa: BLE001
        res["git_error"] = type(exc).__name__
    from services import mca_vision
    try:
        st = await mca_vision.resolve_effective_state(WORK_CHAT)
        res["vision_state_chat"] = {
            "requested": getattr(st, "requested", None),
            "effective": getattr(st, "effective_enabled", None),
            "capability": getattr(st, "capability", None),
            "reason": getattr(st, "reason", None),
            "visible_reason": getattr(st, "visible_reason", None),
            "provider": getattr(st, "provider", None),
            "model": getattr(st, "model", None),
            "source": getattr(st, "source", None)}
    except Exception as exc:  # noqa: BLE001
        res["vision_state_error"] = "%s: %s" % (type(exc).__name__,
                                                str(exc)[:200])
    try:
        st_g = await mca_vision.resolve_effective_state(None)
        res["vision_state_global"] = {
            "requested": getattr(st_g, "requested", None),
            "effective": getattr(st_g, "effective_enabled", None),
            "reason": getattr(st_g, "reason", None)}
    except Exception as exc:  # noqa: BLE001
        res["vision_state_global_error"] = type(exc).__name__
    res["reserve_mode_entry"] = await _reserve_mode(mod)
    res["cap_state_entry"] = await _cap_state(mod)
    res["freq_state_entry"] = await _freq_state(mod)
    res["budget_entry"] = await _budget_snapshot(mod, "entry")
    res["budget_entry_numbers"] = _budget_numbers(res["budget_entry"])
    st, cfg_payload = await mod.CTX.api.req("GET", "/api/config",
                                            chat_id=WORK_CHAT)
    res["config_entry"] = {"http": st, "items": _pick_cfg(cfg_payload)}
    root = await chat_params.get_all_chat_params(WORK_CHAT, pg=mod.CTX.pg)
    mod.CTX.original_overrides = dict((root or {}).get("overrides") or {})
    res["original_overrides_keys"] = sorted(mod.CTX.original_overrides.keys())
    res["original_overrides_touched"] = {
        k: mod.CTX.original_overrides.get(k) for k in TOUCHED_KEYS
        if k in mod.CTX.original_overrides}
    res["pg_worker_budget"] = await _wb_rows(mod)
    res["pg_reservations_since_start"] = await _journal_rows(
        mod, mod.START_EPOCH)
    res["pg_reservations_since_t0"] = await _journal_rows(mod, T0_EPOCH)
    res["sqlite_user_version"] = (await mod.sqlite_fetch(
        "PRAGMA user_version"))[0]
    res["analyses_total_entry"] = await _analyses_total(mod)
    res["analyses_by_status_entry"] = await mod.sqlite_fetch(
        "SELECT status, COUNT(*) n FROM mca_media_analyses GROUP BY status",
        ())
    res["assets_total_entry"] = (await mod.sqlite_fetch(
        "SELECT COUNT(*) n FROM mca_media_assets", ()))[0]
    res["sqlite_throttle_image_freq"] = await _throttle_rows(mod)
    res["vision_jobs_recent"] = await mod.sqlite_fetch(
        "SELECT job_id, kind, status, reason_code, attempt, created_at, "
        "updated_at FROM task_jobs WHERE kind LIKE 'vision%' "
        "ORDER BY created_at DESC LIMIT 6", ())
    try:
        res["mca_image_events_since_t0"] = await mod.sqlite_fetch(
            "SELECT event_name, outcome, reason_code, COUNT(*) n, MAX(ts) last "
            "FROM mca_events WHERE ts >= ? AND event_name LIKE 'image%' "
            "GROUP BY 1,2,3 ORDER BY n DESC LIMIT 20", (T0_EPOCH,))
    except Exception as exc:  # noqa: BLE001
        res["mca_image_events_error"] = type(exc).__name__
    mod.save("p0-pre-state.json", res)
    out("P0", json.dumps({
        "head": res.get("head", "")[:12],
        "vision": res.get("vision_state_chat"),
        "cap": res.get("cap_state_entry"),
        "reserve": res.get("reserve_mode_entry"),
        "budget": res.get("budget_entry_numbers"),
        "analyses_total": res.get("analyses_total_entry"),
        "orig_touched": res.get("original_overrides_touched")},
        ensure_ascii=False, default=str)[:900])
    return res


# ─────────────────────────── B1: positive recognition ───────────────────────

async def _wait_analysis(mod, asset_id, timeout_s=300):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            cur = await mod.CTX.db.db.execute(
                "SELECT id, asset_id, status, revision, analyzer_model, "
                "error_reason, visual_description, completed_at "
                "FROM mca_media_analyses WHERE asset_id=? "
                "ORDER BY id DESC LIMIT 1", (str(asset_id),))
            row = await cur.fetchone()
            last = dict(row) if row is not None else None
        except Exception:
            last = None
        if last and last.get("status") in ("ready", "no_text", "unreadable",
                                           "unsupported", "failed",
                                           "unavailable"):
            if last.get("visual_description"):
                last["visual_description"] = str(
                    last["visual_description"])[:400]
            return last
        await asyncio.sleep(5)
    if last and last.get("visual_description"):
        last["visual_description"] = str(last["visual_description"])[:400]
    return last


async def _vision_job_for_asset(mod, asset_id, since):
    rows = await mod.sqlite_fetch(
        "SELECT job_id, kind, status, reason_code, attempt, max_attempts, "
        "created_at, updated_at, finished_at, payload "
        "FROM task_jobs WHERE kind LIKE 'vision%' AND created_at >= ? "
        "ORDER BY created_at DESC LIMIT 8", (since,))
    for r in rows:
        if str(asset_id) in str(r.get("payload") or ""):
            r.pop("payload", None)
            return r
    for r in rows:
        r.pop("payload", None)
    return rows[0] if rows else None


async def _vision_stage_events(mod, asset_id, since):
    rows = await mod.sqlite_fetch(
        "SELECT ts, event_name, outcome, reason_code, stage, operation_id, "
        "model, attempt FROM mca_events WHERE ts >= ? "
        "AND (operation_id = ? OR event_name LIKE 'vision%' "
        "OR event_name LIKE 'media%' OR event_name LIKE 'MEDIA%') "
        "ORDER BY ts LIMIT 80", (since, str(asset_id)))
    by_asset = [r for r in rows if str(r.get("operation_id") or "")
                == str(asset_id)]
    return {"by_asset": by_asset, "all_recent": rows[-30:]}


def _token_overlap(a, b):
    import re as _re
    ta = set(_re.findall(r"[а-яёa-z0-9]{4,}", str(a or "").lower()))
    tb = set(_re.findall(r"[а-яёa-z0-9]{4,}", str(b or "").lower()))
    if not ta:
        return 0.0
    return round(len(ta & tb) / float(len(ta)), 3)


async def b1_recognition(mod):
    from services import mca_vision
    from config.settings import settings
    res = {"scenario": "B1-positive-recognition",
           "t0_epoch": T0_EPOCH}
    start = int(time.time())
    res["start_epoch"] = start
    try:
        st = await mca_vision.resolve_effective_state(WORK_CHAT)
        res["vision_state"] = {
            "requested": getattr(st, "requested", None),
            "effective": getattr(st, "effective_enabled", None),
            "capability": getattr(st, "capability", None),
            "reason": getattr(st, "reason", None),
            "visible_reason": getattr(st, "visible_reason", None),
            "model": getattr(st, "model", None)}
    except Exception as exc:  # noqa: BLE001
        res["vision_state_error"] = type(exc).__name__
    res["analyses_total_before"] = await _analyses_total(mod)
    rows = await mod.sqlite_fetch(
        "SELECT asset_id, tg_message_id, asset_kind, mime, byte_size, "
        "width, height, file_id, file_unique_id FROM mca_media_assets "
        "WHERE chat_id=? AND asset_kind='photo' AND byte_size>=20000 "
        "ORDER BY tg_message_id DESC LIMIT 12", (WORK_CHAT,))
    # prefer the known fresh owner photo
    rows.sort(key=lambda r: (int(r.get("tg_message_id") or 0)
                             != PREFERRED_PHOTO_MID,
                             -int(r.get("tg_message_id") or 0)))
    checks = []
    asset = None          # preferred: local-session download OK
    asset_cloud = None    # fallback: file_id valid (cloud download OK)
    for r in rows:
        mid = int(r.get("tg_message_id") or 0)
        if mid in EXCLUDE_PHOTOS:
            continue
        rec = {"mid": mid, "asset_id": r.get("asset_id"),
               "byte_size": r.get("byte_size"), "mime": r.get("mime")}
        try:
            img = await mca_vision.download_telegram_file(
                mod.CTX.rec, str(r.get("file_id") or ""))
            rec.update({"download": "ok", "bytes": img.byte_size,
                        "mime": img.mime, "width": img.width,
                        "height": img.height})
            checks.append(rec)
            if asset is None:
                asset = r
            break
        except Exception as exc:  # noqa: BLE001
            rec.update({"download": "fail",
                        "error": "%s: %s" % (type(exc).__name__,
                                             str(exc)[:160])})
            # cloud fallback: proves the file_id itself is still valid
            try:
                from aiogram import Bot
                cloud = Bot(token=settings.API_TOKEN)
                try:
                    tg_file = await cloud.get_file(str(r.get("file_id") or ""))
                    bio = io.BytesIO()
                    await cloud.download(tg_file, destination=bio)
                    rec["cloud_download"] = "ok"
                    rec["cloud_bytes"] = len(bio.getvalue())
                finally:
                    await cloud.session.close()
                if (asset_cloud is None
                        and int(rec.get("cloud_bytes") or 0) >= 20000):
                    asset_cloud = r
            except Exception as exc2:  # noqa: BLE001
                rec["cloud_download"] = "fail"
                rec["cloud_error"] = "%s: %s" % (type(exc2).__name__,
                                                 str(exc2)[:120])
            checks.append(rec)
    if asset is None:
        asset = asset_cloud
    res["download_checks"] = checks
    if asset is None:
        res["ok"] = False
        res["error"] = "no downloadable fresh photo"
        mod.save("b1-recognition.json", res)
        out("B1", "NO_DOWNLOADABLE_PHOTO")
        return res
    res["asset"] = {"asset_id": asset.get("asset_id"),
                    "tg_message_id": asset.get("tg_message_id"),
                    "byte_size": asset.get("byte_size"),
                    "mime": asset.get("mime")}
    asset_id = str(asset.get("asset_id"))
    photo_msg = mod.make_photo_message(asset, caption=None)
    attempts = []
    turn_final = None
    outcome = None
    provider_retry_done = False
    for attempt in (1, 2, 3):
        anchor = await mod.CTX.rec.send_message(
            WORK_CHAT,
            "🧪 Приёмка 2.58.94 · распознавание фото (контроль).")
        t = await mod.run_turn("бот, что тут?", msg_id=anchor.message_id,
                               reply_to=photo_msg,
                               label="b-vision-%d" % attempt, timeout=300)
        tool = next((x for x in t.get("tool_calls", [])
                     if x.get("tool") == "recognize_image"), None)
        status = (tool or {}).get("status")
        rec = {"attempt": attempt, "announce_mid": anchor.message_id,
               "tool": tool, "status": status, "turn": _strip_turn(t)}
        attempts.append(rec)
        if tool is None:
            outcome = "no_tool"
            if attempt < 3:
                await asyncio.sleep(15)
                continue
            break
        if status == "ready":
            outcome = "ready"
            turn_final = t
            break
        if status == "pending":
            analysis = await _wait_analysis(mod, asset_id, timeout_s=300)
            rec["analysis_after_wait"] = analysis
            if analysis and analysis.get("status") == "ready":
                anchor2 = await mod.CTX.rec.send_message(
                    WORK_CHAT,
                    "🧪 Приёмка 2.58.94 · распознавание: результат "
                    "(контроль).")
                t2 = await mod.run_turn(
                    "бот, что тут?", msg_id=anchor2.message_id,
                    reply_to=photo_msg, label="b-vision-delivery",
                    timeout=300)
                tool2 = next((x for x in t2.get("tool_calls", [])
                              if x.get("tool") == "recognize_image"), None)
                attempts.append({"attempt": "delivery",
                                 "announce_mid": anchor2.message_id,
                                 "tool": tool2,
                                 "status": (tool2 or {}).get("status"),
                                 "turn": _strip_turn(t2)})
                if (tool2 or {}).get("status") == "ready":
                    outcome = "ready_delivery"
                    turn_final = t2
                else:
                    outcome = "delivery_%s" % (
                        (tool2 or {}).get("status") or "none")
                break
            outcome = "analysis_%s" % ((analysis or {}).get("status")
                                       or "none")
            if attempt < 3:
                await asyncio.sleep(60)
                continue
            break
        if status in ("disabled", "unavailable", "failed"):
            rec["retry_reason"] = (tool or {}).get("reason")
            outcome = "provider_retry"
            if not provider_retry_done:
                provider_retry_done = True
                out("B1", "provider %s — bounded retry in 100s"
                    % (tool or {}).get("reason"))
                await asyncio.sleep(100)
                continue
            outcome = "provider_%s" % (tool or {}).get("reason")
            break
        outcome = str(status)
        break
    res["attempts"] = attempts
    res["outcome"] = outcome
    res["analysis_final"] = await _wait_analysis(mod, asset_id,
                                                 timeout_s=10)
    res["analyses_total_after"] = await _analyses_total(mod)
    res["job_final"] = await _vision_job_for_asset(mod, asset_id, start)
    res["stage_events"] = await _vision_stage_events(mod, asset_id, start)
    final_tool = None
    if turn_final is not None:
        final_tool = next((x for x in turn_final.get("tool_calls", [])
                           if x.get("tool") == "recognize_image"), None)
    if final_tool is None:
        for rec in reversed(attempts):
            tool = rec.get("tool")
            if tool and tool.get("status") == "ready":
                final_tool = tool
                turn_final = attempts[attempts.index(rec)].get("turn")
                break
    desc = str((final_tool or {}).get("visual_description_head") or "")
    answer = str((turn_final or {}).get("answer_head") or "")
    analysis = res.get("analysis_final") or {}
    res["five_facts"] = {
        "1_target": {
            "asset_id": asset_id,
            "asset_mid": asset.get("tg_message_id"),
            "tool_target": ((final_tool or {}).get("args") or {}).get(
                "target")},
        "2_chain": {
            "download_check": next((c for c in checks
                                    if c.get("mid")
                                    == int(asset.get("tg_message_id"))), None),
            "job": res.get("job_final"),
            "stages_by_asset": (res.get("stage_events") or {}).get("by_asset"),
        },
        "3_analysis": {
            "status": analysis.get("status"),
            "revision": analysis.get("revision"),
            "analyzer_model": analysis.get("analyzer_model"),
            "desc_len": len(str(analysis.get("visual_description") or "")),
            "desc_head": str(analysis.get("visual_description") or "")[:300],
        },
        "4_delivery": {
            "tool_status": (final_tool or {}).get("status"),
            "tool_desc_len": (final_tool or {}).get("visual_description_len"),
            "tool_desc_head": desc,
            "answer_head": answer,
            "desc_in_answer_overlap": _token_overlap(desc, answer),
            "delivery_mids": [
                s.get("message_id")
                for rec in attempts
                for s in (rec.get("turn", {}).get("sends") or [])
                if s.get("kind") == "message"],
        },
        "5_counters": {
            "analyses_total_before": res.get("analyses_total_before"),
            "analyses_total_after": res.get("analyses_total_after"),
        },
    }
    ready = outcome in ("ready", "ready_delivery")
    desc_ok = (analysis.get("status") == "ready"
               and len(str(analysis.get("visual_description") or "")) > 0)
    res["ok"] = bool(ready and desc_ok)
    res["positive_recognition"] = res["ok"]
    mod.save("b1-recognition.json", res)
    out("B1", json.dumps({
        "outcome": outcome,
        "asset_mid": asset.get("tg_message_id"),
        "analysis": res.get("five_facts", {}).get("3_analysis", {}).get(
            "status"),
        "total": [res.get("analyses_total_before"),
                  res.get("analyses_total_after")],
        "positive": res["ok"]}, ensure_ascii=False, default=str)[:600])
    return res


# ─────────────────────────── B2: postgen ────────────────────────────────────

async def _ensure_generation_ready(mod):
    """Make the user image path actually allowed for the paid generations.

    The baseline capability gate for this chat can already be non-READY
    (day quota). If so, apply the documented temp premise (budgets ON +
    daily 20 + freq ON) — restored exactly in C4.
    """
    res = {"phase": "G0-generation-readiness"}
    res["cap_state_before"] = await _cap_state(mod)
    res["reserve_mode_before"] = await _reserve_mode(mod)
    if (res["cap_state_before"].get("status") == "ready"):
        res["mode"] = "baseline_ready"
        res["ok"] = True
        mod.save("g0-generation-ready.json", res)
        out("G0", "baseline capability READY — no temp config needed")
        return res
    res["cfg_write"] = await _set_chat_config(mod, [
        {"key": "flags.budgets_enabled", "value": True},
        {"key": "limits.image_daily_limit", "value": GEN_READY_LIMIT},
        {"key": "limits.image_freq_limit_enabled", "value": True},
    ], "gen-ready")
    await asyncio.sleep(2.0)
    await _invalidate_caches(mod)
    res["cap_state_after"] = await _cap_state(mod)
    res["reserve_mode_after"] = await _reserve_mode(mod)
    res["mode"] = "temp_raised"
    res["ok"] = res["cap_state_after"].get("status") == "ready"
    mod.save("g0-generation-ready.json", res)
    out("G0", json.dumps({"mode": res["mode"],
                          "cap_after": res["cap_state_after"]},
                         ensure_ascii=False)[:400])
    return res


async def b2_postgen(mod):
    res = {"scenario": "B2-postgen", "start_epoch": int(time.time())}
    from services import postgen_vision as pv
    from config.settings import settings as st
    try:
        res["postgen_enabled"] = bool(pv.enabled())
        res["postgen_budget_s"] = float(pv.analysis_budget_seconds())
    except Exception as exc:  # noqa: BLE001
        res["postgen_cfg_error"] = type(exc).__name__
    res["cap_state"] = await _cap_state(mod)
    res["budget_before"] = _budget_numbers(await _budget_snapshot(
        mod, "postgen-before"))
    anchor = await mod.CTX.rec.send_message(
        WORK_CHAT,
        "🧪 Приёмка 2.58.94 · генерация + пост-генерация (контроль).")
    res["announce_mid"] = anchor.message_id
    q = "бот, надо нарисовать картинку: жёлтый лимон на белом фоне"
    res["query"] = q
    p_before = len(mod.CTX.provider_calls)
    heads_before = len(mod.CTX.postgen)
    t = await mod.run_turn(q, msg_id=anchor.message_id, reply_to=anchor,
                           label="b-gen", timeout=420)
    res["provider_calls"] = len(mod.CTX.provider_calls) - p_before
    res["turn"] = {"phrase": q, **_strip_turn(t)}
    res["image_blocks"] = t.get("image_blocks")
    res["postgen_turn"] = t.get("postgen")
    res["postgen_heads"] = mod.CTX.postgen[heads_before:]
    sends = t.get("sends") or []
    res["photo_sends"] = [s for s in sends if s.get("kind") == "photo"]
    res["text_sends"] = [s for s in sends if s.get("kind") == "message"]
    ok_photo = bool(res["photo_sends"])
    ready_heads = [h for h in res["postgen_heads"]
                   if h.get("status") == "ready" and h.get("has_content")]
    res["ok"] = bool(ok_photo)
    res["postgen_ok"] = bool(ready_heads)
    if ready_heads:
        head = ready_heads[-1]
        res["postgen_facts"] = {
            "status": head.get("status"),
            "desc_len": head.get("desc_len"),
            "desc_head": head.get("desc_head"),
            "not_prompt_echo": (
                str(head.get("desc_head") or "")[:60].lower()
                not in q.lower()),
            "prompt": q,
        }
    res["budget_after"] = _budget_numbers(await _budget_snapshot(
        mod, "postgen-after"))
    mod.save("b2-postgen.json", res)
    out("B2", json.dumps({
        "provider_calls": res["provider_calls"],
        "photo_mids": [s.get("message_id")
                       for s in res["photo_sends"]],
        "postgen_ok": res["postgen_ok"],
        "postgen_status": (res.get("postgen_facts") or {}).get("status"),
    }, ensure_ascii=False)[:500])
    return res


# ─────────────────────────── C1: showcase ───────────────────────────────────

async def c1_showcase(mod):
    import httpx
    res = {"phase": "C1-showcase"}
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=30.0) as c:
            r = await c.get("/web/")
            html = r.text
            r2 = await c.get("/web/app.js")
            served_js = r2.content
            r3 = await c.get("/static/app.css")
            served_css = r3.content
        repo_js = io.open(os.path.join(APP, "web", "app.js"),
                          "rb").read()
        label_b = CFG_LABEL.encode("utf-8")
        res["served"] = {
            "web_status": r.status_code,
            "appjs_status": r2.status_code,
            "appcss_status": r3.status_code,
            "appjs_sha12": mod.sha12(served_js),
            "repo_appjs_sha12": mod.sha12(repo_js),
            "served_eq_appjs": mod.sha12(served_js) == mod.sha12(repo_js),
            "label_in_served_appjs": served_js.count(label_b),
            "label_in_repo_appjs": repo_js.count(label_b),
            "label_in_served_html": html.count(CFG_LABEL),
            "scope_label_html": html.count("data-image-quota-scope-label"),
            "breakdown_html": html.count(
                "data-image-quota-shared-breakdown"),
            "cover_tpl_html": html.count(
                "imageQuotaFacts.shared.cover_used"),
        }
    except Exception as exc:  # noqa: BLE001
        res["served_error"] = "%s: %s" % (type(exc).__name__,
                                          str(exc)[:200])
    st, body = await mod.CTX.api.req("GET", "/api/workers/budget")
    entry = _budget_chat_entry(body)
    res["budget_api"] = {
        "http": st,
        "global_image_calls": ((body or {}).get("global") or {}).get(
            "image_calls"),
        "chat_image_calls": (entry or {}).get("image_calls"),
        "chat_cover_breakdown": ((entry or {}).get("image_usage")
                                 or {}).get("cover"),
        "chat_reserve_path": ((entry or {}).get("image_usage")
                              or {}).get("reserve_path"),
    }
    served = res.get("served") or {}
    res["ok"] = bool(served.get("label_in_served_appjs")
                     and served.get("served_eq_appjs"))
    mod.save("c1-showcase.json", res)
    out("C1", json.dumps({"label_served": served.get(
        "label_in_served_appjs"), "eq": served.get("served_eq_appjs"),
        "cover_used": (res["budget_api"]["global_image_calls"] or {}).get(
            "cover_used")}, ensure_ascii=False)[:400])
    return res


# ─────────────────────────── C2: cover isolation ────────────────────────────

def _sanitize_run(payload):
    if not isinstance(payload, dict):
        return {"raw": str(payload)[:200]}
    return {"status": payload.get("status"), "test_id": payload.get("test_id"),
            "chat_id": payload.get("chat_id"),
            "window": payload.get("window"), "cover": payload.get("cover"),
            "error": payload.get("error")}


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
        if str((last or {}).get("status")) != "running":
            return last
        await asyncio.sleep(10)
    return last


async def _fetch_cover_image(mod, test_id):
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=90.0) as c:
        r = await c.get("/api/summary/test/%s/cover-image" % test_id,
                        headers={"X-Telegram-Init-Data":
                                 mod.make_init_data()})
        return r.status_code, r.content


async def c2_cover(mod):
    import httpx
    res = {"phase": "C2-cover-isolation"}
    res["cfg_zero"] = await _set_chat_config(mod, [
        {"key": "flags.budgets_enabled", "value": True},
        {"key": "limits.image_daily_limit", "value": 0},
        {"key": "limits.image_freq_limit_enabled", "value": True},
    ], "cover-premise")
    await asyncio.sleep(2.0)
    await _invalidate_caches(mod)
    res["reserve_mode"] = await _reserve_mode(mod)
    res["cap_state"] = await _cap_state(mod)
    res["budget_before"] = _budget_numbers(await _budget_snapshot(
        mod, "cover-before"))
    res["freq_state_before"] = await _freq_state(mod)
    res["throttle_before"] = await _throttle_rows(mod)
    cover_ok = False
    for attempt in (1, 2):
        st, run = await mod.CTX.api.req(
            "POST", "/api/summary/test/run",
            json_body={"chat_id": WORK_CHAT,
                       "window_hours": COVER_WINDOW_HOURS})
        res["run_start_%d" % attempt] = {"http": st, "body": _sanitize_run(run)}
        test_id = (run or {}).get("test_id") if isinstance(run, dict) else None
        if st not in (200, 202) or not test_id:
            continue
        result = await _poll_run(mod, test_id, timeout_s=420)
        res["run_result_%d" % attempt] = _sanitize_run(result)
        if str((result or {}).get("status")) != "completed":
            continue
        try:
            async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                         timeout=300.0) as c:
                r = await c.post("/api/summary/test/%s/cover" % test_id,
                                 headers={"X-Telegram-Init-Data":
                                          mod.make_init_data()},
                                 json={"confirm": True})
                try:
                    cov = r.json()
                except Exception:
                    cov = {"raw": r.text[:200]}
            res["cover_call_%d" % attempt] = {"http": r.status_code,
                                              "body": cov}
        except Exception as exc:  # noqa: BLE001
            res["cover_call_%d" % attempt] = {
                "error": "%s: %s" % (type(exc).__name__, str(exc)[:200])}
            continue
        if str((cov or {}).get("cover_status")) == "generated":
            res["cover_test_id"] = test_id
            st3, img = await _fetch_cover_image(mod, test_id)
            res["cover_image"] = {"http": st3, "bytes": len(img or b""),
                                  "sha12": mod.sha12(img or b"")}
            if img:
                with open(os.path.join(mod.EVID, "cover94-base.png"),
                          "wb") as fh:
                    fh.write(img)
            cover_ok = True
            break
    res["cover_ok"] = cover_ok
    await asyncio.sleep(2.0)
    res["journal_after_cover"] = await _journal_rows(mod, mod.START_EPOCH)
    res["cover_rows"] = [r for r in (res["journal_after_cover"] or [])
                         if str(r.get("source") or "").startswith(
                             "summary_cover")]
    res["budget_after"] = _budget_numbers(await _budget_snapshot(
        mod, "cover-after"))
    res["freq_state_after"] = await _freq_state(mod)
    res["throttle_after"] = await _throttle_rows(mod)
    before = res.get("budget_before") or {}
    after = res.get("budget_after") or {}
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
        "freq_charges_untouched": (res.get("throttle_before")
                                   == res.get("throttle_after")),
    }
    res["ok"] = bool(cover_ok and all(res["checks"].values()))
    mod.save("c2-cover-isolation.json", res)
    out("C2", json.dumps({
        "cover_ok": cover_ok, "checks": res["checks"],
        "cover_row": (res["cover_rows"] or [{}])[-1].get("source"),
        "budget_before": before, "budget_after": after,
    }, ensure_ascii=False, default=str)[:800])
    return res


# ─────────────────────────── C3: meme isolation ─────────────────────────────

async def c3_meme(mod):
    res = {"phase": "C3-meme-isolation"}
    res["state_before_denied"] = await _cap_state(mod)
    res["budget_before_denied"] = _budget_numbers(await _budget_snapshot(
        mod, "meme-before-denied"))
    journal_before = await _journal_rows(mod, mod.START_EPOCH)
    res["journal_before_denied_n"] = len(journal_before)
    res["cover_rows_before_denied"] = [
        r for r in (journal_before or [])
        if str(r.get("source") or "").startswith("summary_cover")]
    p_before = len(mod.CTX.provider_calls)
    t1 = await mod.run_turn(
        "бот, нарисуй мем: добрый кот-пират с попугаем",
        msg_id=SYNTH_MIDS[0], label="meme-denied", timeout=300)
    res["attempt_denied"] = {
        "provider_calls": len(mod.CTX.provider_calls) - p_before,
        "turn": _strip_turn(t1)}
    await asyncio.sleep(1.0)
    res["journal_after_denied"] = await _journal_rows(mod, mod.START_EPOCH)
    res["cover_rows_after_denied"] = [
        r for r in (res["journal_after_denied"] or [])
        if str(r.get("source") or "").startswith("summary_cover")]
    res["budget_after_denied"] = _budget_numbers(await _budget_snapshot(
        mod, "meme-after-denied"))
    # temp raise: allow the paid user generation (restored in C4)
    res["cfg_raise"] = await _set_chat_config(mod, [
        {"key": "limits.image_daily_limit", "value": GEN_READY_LIMIT},
    ], "meme-raise")
    await asyncio.sleep(2.0)
    await _invalidate_caches(mod)
    res["state_before_generated"] = await _cap_state(mod)
    res["reserve_mode_before_generated"] = await _reserve_mode(mod)
    res["budget_before_generated"] = _budget_numbers(await _budget_snapshot(
        mod, "meme-before-generated"))
    res["throttle_before_generated"] = await _throttle_rows(mod)
    p_before = len(mod.CTX.provider_calls)
    heads_before = len(mod.CTX.postgen)
    t2 = await mod.run_turn(
        "бот, нарисуй мем: добрый кот-астронавт на Луне",
        msg_id=SYNTH_MIDS[1], label="meme-generated", timeout=420)
    res["attempt_generated"] = {
        "provider_calls": len(mod.CTX.provider_calls) - p_before,
        "turn": _strip_turn(t2)}
    res["postgen_meme"] = mod.CTX.postgen[heads_before:]
    await asyncio.sleep(2.0)
    res["journal_after_meme"] = await _journal_rows(mod, mod.START_EPOCH)
    res["user_rows_after_meme"] = [
        r for r in (res["journal_after_meme"] or [])
        if not str(r.get("source") or "").startswith("summary_cover")]
    res["cover_rows_after_meme"] = [
        r for r in (res["journal_after_meme"] or [])
        if str(r.get("source") or "").startswith("summary_cover")]
    res["budget_after_meme"] = _budget_numbers(await _budget_snapshot(
        mod, "meme-after-generated"))
    res["freq_state_after_meme"] = await _freq_state(mod)
    res["throttle_after_meme"] = await _throttle_rows(mod)
    before_g = res.get("budget_before_generated") or {}
    after_g = res.get("budget_after_meme") or {}
    cover_after = res.get("cover_rows_after_meme") or []
    res["checks"] = {
        "denied_no_provider_calls": res["attempt_denied"]["provider_calls"]
        == 0,
        "denied_no_new_rows": (len(res.get("journal_after_denied") or [])
                               == len(journal_before)),
        "denied_cover_untouched": (len(res.get("cover_rows_after_denied")
                                       or [])
                                   == len(res.get("cover_rows_before_denied")
                                          or [])),
        "generated_provider_calls_one":
            res["attempt_generated"]["provider_calls"] == 1,
        "user_row_typed": bool(
            res.get("user_rows_after_meme")
            and res["user_rows_after_meme"][-1].get("status") == "committed"
            and res["user_rows_after_meme"][-1].get("source") in
            ("direct", "tool")),
        "chat_plus_one": (int(after_g.get("chat_used") or 0)
                          - int(before_g.get("chat_used") or 0)) == 1,
        "cover_aggregate_unchanged": (
            int(after_g.get("global_cover_used") or 0)
            == int(before_g.get("global_cover_used") or 0)
            and len(cover_after) == len(res.get("cover_rows_before_denied")
                                        or [])),
    }
    res["ok"] = bool(all(res["checks"].values()))
    mod.save("c3-meme-isolation.json", res)
    out("C3", json.dumps({
        "denied_answer": (res["attempt_denied"]["turn"].get("answer_head")
                          or "")[:120],
        "denied_calls": res["attempt_denied"]["provider_calls"],
        "gen_calls": res["attempt_generated"]["provider_calls"],
        "checks": res["checks"],
    }, ensure_ascii=False, default=str)[:800])
    return res


# ─────────────────────────── C4: restore ────────────────────────────────────

async def c4_restore(mod):
    res = {"phase": "C4-restore"}
    from services import chat_params
    root = await chat_params.get_all_chat_params(WORK_CHAT, pg=mod.CTX.pg)
    ov = dict((root or {}).get("overrides") or {})
    original = dict(mod.CTX.original_overrides or {})
    for key in TOUCHED_KEYS:
        if key in original:
            ov[key] = original[key]
        else:
            ov.pop(key, None)
    try:
        await chat_params.set_chat_params(WORK_CHAT, {"overrides": ov},
                                          changed_by=None, pg=mod.CTX.pg)
        res["restore"] = "ok"
    except Exception as exc:  # noqa: BLE001
        res["restore"] = "failed: %s" % type(exc).__name__
    await _invalidate_caches(mod, reason="restore")
    await asyncio.sleep(2.0)
    res["reserve_mode_after"] = await _reserve_mode(mod)
    res["freq_state_after"] = await _freq_state(mod)
    res["cap_state_after"] = await _cap_state(mod)
    # verify through the prod process view as well (bounded)
    cfg_after = None
    for attempt in range(3):
        st, cfg = await mod.CTX.api.req("GET", "/api/config",
                                        chat_id=WORK_CHAT)
        cfg_after = {"http": st, "items": _pick_cfg(cfg)}
        if _cfg_map(cfg_after["items"]) == _cfg_map(
                (mod.RESULTS.get("P0", {}) or {}).get("config_entry", {})
                .get("items")):
            break
        await asyncio.sleep(20)
    res["config_after"] = cfg_after
    res["config_entry_p0"] = (mod.RESULTS.get("P0", {}) or {}).get(
        "config_entry")
    res["matches"] = (_cfg_map(cfg_after.get("items"))
                      == _cfg_map((res.get("config_entry_p0") or {}).get(
                          "items")))
    entry_cap = ((mod.RESULTS.get("P0", {}) or {}).get("cap_state_entry")
                 or {})
    after_cap = res.get("cap_state_after") or {}
    res["cap_state_match"] = all(
        entry_cap.get(k) == after_cap.get(k)
        for k in ("status", "reason_code", "detail"))
    res["budget_after_restore"] = _budget_numbers(await _budget_snapshot(
        mod, "after-restore"))
    res["ok"] = bool(res.get("restore") == "ok" and res["matches"]
                     and res["cap_state_match"]
                     and res["reserve_mode_after"].get("mode") == "legacy"
                     and res["reserve_mode_after"].get("reason")
                     == "budgets_off")
    mod.save("c4-restore.json", res)
    out("C4", json.dumps({"restore": res.get("restore"),
                          "matches": res["matches"],
                          "cap_state_match": res["cap_state_match"],
                          "reserve": res["reserve_mode_after"]},
                         ensure_ascii=False)[:400])
    return res


# ─────────────────────────── E: economics ───────────────────────────────────

async def e_economics(mod):
    res = {"phase": "E-economics", "start_epoch": mod.START_EPOCH,
           "t0_epoch": T0_EPOCH}
    try:
        res["head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
        res["tracked_mod"] = int(subprocess.check_output(
            "git status --porcelain | grep -v '^??' | wc -l",
            cwd=APP, shell=True, text=True).strip() or 0)
    except Exception:
        pass
    res["budget_final"] = _budget_numbers(await _budget_snapshot(
        mod, "final"))
    res["pg_worker_budget"] = await _wb_rows(mod)
    res["journal_since_start"] = await _journal_rows(mod, mod.START_EPOCH)
    res["journal_since_t0"] = await _journal_rows(mod, T0_EPOCH)
    try:
        res["usage_since_start"] = await mod.pg_fetch(
            "SELECT step, COUNT(*) n, COALESCE(SUM(input_tokens+output_tokens),0) "
            "tokens FROM llm_usage_events WHERE ts >= to_timestamp($1) "
            "GROUP BY step ORDER BY n DESC", mod.START_EPOCH)
    except Exception as exc:  # noqa: BLE001
        res["pg_error"] = type(exc).__name__
    try:
        res["mca_events_since_start"] = await mod.sqlite_fetch(
            "SELECT event_name, outcome, reason_code, COUNT(*) n, MAX(ts) last "
            "FROM mca_events WHERE ts >= ? GROUP BY 1,2,3 "
            "ORDER BY n DESC LIMIT 30", (mod.START_EPOCH,))
        res["mca_errors_since_start"] = await mod.sqlite_fetch(
            "SELECT COUNT(*) n FROM mca_events WHERE ts >= ? AND "
            "level IN ('ERROR','CRITICAL')", (mod.START_EPOCH,))
        res["user_version"] = (await mod.sqlite_fetch(
            "PRAGMA user_version"))[0]
        res["throttle_final"] = await _throttle_rows(mod)
        res["analyses_total_final"] = await _analyses_total(mod)
        res["analyses_by_status_final"] = await mod.sqlite_fetch(
            "SELECT status, COUNT(*) n FROM mca_media_analyses GROUP BY status",
            ())
        res["assets_total_final"] = (await mod.sqlite_fetch(
            "SELECT COUNT(*) n FROM mca_media_assets", ()))[0]
    except Exception as exc:  # noqa: BLE001
        res["sqlite_error"] = type(exc).__name__
    res["provider_calls_total"] = len(mod.CTX.provider_calls)
    res["vision_transport_calls"] = len(mod.CTX.vision_transport_calls)
    mod.save("e-economics.json", res)
    out("E", "done")
    return res


# ─────────────────────────── F: cleanup register ────────────────────────────

async def f_cleanup_register(mod):
    res = {"phase": "F-cleanup-register"}
    mids = []
    for s in mod.CTX.rec.sends:
        mid = s.get("message_id")
        if mid:
            mids.append(int(mid))
        for m2 in (s.get("message_ids") or []):
            mids.append(int(m2))
    mids = sorted(set(mids))
    delete_mids = sorted(set(mids) | set(LEFTOVER_MIDS))
    lo = min(delete_mids) - 3
    hi = max(delete_mids) + 3
    incoming = await mod.sqlite_fetch(
        "SELECT tg_message_id mid, user_id, author_name, media_type, "
        "reply_to_id, timestamp ts, substr(text,1,90) head "
        "FROM smart_messages WHERE chat_id=? AND tg_message_id IS NOT NULL "
        "AND tg_message_id BETWEEN ? AND ? ORDER BY tg_message_id",
        (WORK_CHAT, lo, hi))
    botrep = await mod.sqlite_fetch(
        "SELECT tg_message_id mid, substr(text,1,90) head, last_used_at "
        "FROM bot_replies WHERE chat_id=? AND tg_message_id BETWEEN ? AND ? "
        "ORDER BY tg_message_id", (WORK_CHAT, lo, hi))
    synth_rows = [r["mid"] for r in incoming
                  if r.get("user_id") == SYNTH_USER]
    spec = {
        "generated_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "chat_id": WORK_CHAT,
        "delete_mids": delete_mids,
        "harness_sent_mids": mids,
        "leftover_mids": sorted(LEFTOVER_MIDS),
        "smart_rows": sorted(set(synth_rows)),
        "window": {"lo": lo, "hi": hi},
    }
    with open("/tmp/accept94_cleanup_mids.json", "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=1)
    res["delete_mids"] = delete_mids
    res["sends"] = _sanitize_sends(mod.CTX.rec.sends)
    res["window"] = spec["window"]
    res["smart_rows_window"] = incoming
    res["bot_replies_window"] = botrep
    res["spec_saved"] = "/tmp/accept94_cleanup_mids.json"
    mod.save("f-cleanup-register.json", res)
    out("F", "mids=%d smart_synth=%d" % (len(delete_mids), len(synth_rows)))
    return res


# ─────────────────────────── main ───────────────────────────────────────────

def _wrap_postgen_heads(mod):
    """Second wrap over the base postgen spy: capture a bounded description
    head + byte count of the FINAL bitmap that was analyzed."""
    from services import postgen_vision as pv
    prev = pv.analyze_generated_image

    async def spy(data, *, chat_id, correlation_id=None):
        outcome = await prev(data, chat_id=chat_id,
                             correlation_id=correlation_id)
        desc = str(getattr(outcome, "visual_description", "") or "")
        if mod.CTX.postgen:
            mod.CTX.postgen[-1]["desc_head"] = desc[:300]
            mod.CTX.postgen[-1]["bytes"] = (
                len(data) if isinstance(data, (bytes, bytearray)) else None)
        return outcome

    pv.analyze_generated_image = spy


async def main() -> int:
    try:
        os.umask(0o022)   # evidence readable by the SSH user / SFTP
    except Exception:
        pass
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    mod = load_base()
    mod.EVID = EVID
    os.makedirs(mod.EVID, exist_ok=True)
    await mod.bootstrap()
    mod.CTX.api = mod.Api()
    _wrap_postgen_heads(mod)
    out("START_EPOCH", mod.START_EPOCH)

    p0 = await _safe("P0", p0_pre_state, mod)
    mod.RESULTS["P0"] = p0 if isinstance(p0, dict) else {}
    b1 = await _safe("B1", b1_recognition, mod)
    mod.RESULTS["B1"] = b1 if isinstance(b1, dict) else {}
    g0 = await _safe("G0", _ensure_generation_ready, mod)
    mod.RESULTS["G0"] = g0 if isinstance(g0, dict) else {}
    b2 = await _safe("B2", b2_postgen, mod)
    mod.RESULTS["B2"] = b2 if isinstance(b2, dict) else {}
    c1 = await _safe("C1", c1_showcase, mod)
    mod.RESULTS["C1"] = c1 if isinstance(c1, dict) else {}
    c2 = await _safe("C2", c2_cover, mod)
    mod.RESULTS["C2"] = c2 if isinstance(c2, dict) else {}
    c3 = await _safe("C3", c3_meme, mod)
    mod.RESULTS["C3"] = c3 if isinstance(c3, dict) else {}
    c4 = await _safe("C4", c4_restore, mod)
    mod.RESULTS["C4"] = c4 if isinstance(c4, dict) else {}
    econ = await _safe("E", e_economics, mod)
    mod.RESULTS["E"] = econ if isinstance(econ, dict) else {}
    cleanup = await _safe("F", f_cleanup_register, mod)
    mod.RESULTS["F"] = cleanup if isinstance(cleanup, dict) else {}

    summary = {
        "start_epoch": mod.START_EPOCH,
        "t0_epoch": T0_EPOCH,
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "head": (mod.RESULTS.get("P0") or {}).get("head"),
        "b1_positive": (b1 or {}).get("positive_recognition"),
        "b1_outcome": (b1 or {}).get("outcome"),
        "b1_asset": (b1 or {}).get("asset"),
        "b2_ok": (b2 or {}).get("ok"),
        "b2_postgen_ok": (b2 or {}).get("postgen_ok"),
        "b2_provider_calls": (b2 or {}).get("provider_calls"),
        "g0_mode": (g0 or {}).get("mode"),
        "c1_ok": (c1 or {}).get("ok"),
        "c2_ok": (c2 or {}).get("ok"),
        "c2_checks": (c2 or {}).get("checks"),
        "c3_ok": (c3 or {}).get("ok"),
        "c3_checks": (c3 or {}).get("checks"),
        "c4_ok": (c4 or {}).get("ok"),
        "econ_final": (econ or {}).get("budget_final"),
        "cleanup_mids": (cleanup or {}).get("delete_mids"),
        "sends": _sanitize_sends(mod.CTX.rec.sends),
        "tool_calls": [t.get("tool") for t in mod.CTX.tool_calls],
        "provider_calls": len(mod.CTX.provider_calls),
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
        print("ACC94 FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC94 RC=%d" % rc, flush=True)
    os._exit(rc)
