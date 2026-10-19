# -*- coding: utf-8 -*-
"""ACCEPTANCE-92C — bounded retry: positive Vision + (on success) postgen.

One controlled process ON the production host via the proven bootstrap
(uploaded as /tmp/accept92c_base.py). Real Telegram delivery, real stores,
real providers.

C1: same fresh asset 1165720 (download pre-checked) -> reply path
    "бот, что тут?" -> recognize_image -> nemotron analysis -> ready ->
    meaningful description + delivery mid. STOP on any provider 502/429
    (record WAITING_EXTERNAL with time/class; no hammering).
C2: ONLY if C1 succeeded: ONE generation ("бот, нарисуй ...") -> photo mid ->
    image_postgen_vision -> description from the actual bitmap.
C3: final state/economics snapshot.

Evidence: /tmp/accept92c/evidence/*.json
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
ASSET_MID = 1165720                     # fresh asset, download verified in 92B
GEN_PROMPT = "бот, нарисуй безобидный рисунок: красный воздушный шарик на белом фоне"
BSTATE: dict = {"postgen_heads": []}


def out(tag, text):
    print("ACC92C %s | %s" % (tag, text), flush=True)


def load_base():
    spec = importlib.util.spec_from_file_location("accept92c_base",
                                                  "/tmp/accept92c_base.py")
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


def _wrap_postgen_heads():
    from services import postgen_vision as pv
    prev = pv.analyze_generated_image

    async def spy(data, *, chat_id, correlation_id=None):
        outcome = await prev(data, chat_id=chat_id,
                             correlation_id=correlation_id)
        desc = str(getattr(outcome, "visual_description", "") or "")
        BSTATE["postgen_heads"].append({
            "status": getattr(outcome, "status", None),
            "reason": getattr(outcome, "reason", None),
            "visible_reason": getattr(outcome, "visible_reason", None),
            "has_content": bool(getattr(outcome, "has_content", False)),
            "cache_hit": bool(getattr(outcome, "cache_hit", False)),
            "desc_len": len(desc),
            "desc_head": desc[:220],
            "bytes": len(data) if isinstance(data, (bytes, bytearray)) else None,
        })
        return outcome

    pv.analyze_generated_image = spy


async def _asset_row(mod, mid):
    rows = await mod.sqlite_fetch(
        "SELECT asset_id, tg_message_id, asset_kind, mime, byte_size, "
        "width, height, file_id, file_unique_id FROM mca_media_assets "
        "WHERE chat_id=? AND tg_message_id=? AND asset_kind='photo' LIMIT 1",
        (WORK_CHAT, mid))
    return rows[0] if rows else None


async def _analysis_row(mod, asset_id):
    try:
        cur = await mod.CTX.db.db.execute(
            "SELECT status, revision, analyzer_model, error_reason, "
            "visual_description, completed_at FROM mca_media_analyses "
            "WHERE asset_id=? ORDER BY id DESC LIMIT 1", (str(asset_id),))
        row = await cur.fetchone()
        return dict(row) if row is not None else None
    except Exception:
        return None


async def _wait_analysis(mod, asset_id, timeout_s=180):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = await _analysis_row(mod, asset_id)
        if last and last.get("status") in ("ready", "no_text", "unreadable",
                                           "unsupported", "failed",
                                           "unavailable"):
            return last
        await asyncio.sleep(5)
    return last


def _find_tool(turn):
    return next((x for x in turn.get("tool_calls", [])
                 if x.get("tool") == "recognize_image"), None)


def _provider_stop(tool):
    if not tool:
        return None
    if tool.get("status") == "disabled" and tool.get("reason") in (
            "vision_unavailable", "vision_rate_limited"):
        return tool.get("reason")
    return None


async def _api_probe(mod):
    """One live POST /api/vision/test (free provider call, no chat messages)."""
    st, body = await mod.CTX.api.req("POST", "/api/vision/test",
                                     chat_id=WORK_CHAT, json_body={})
    try:
        safe = {"http": st, "ok": body.get("ok"),
                "capability": body.get("capability"),
                "reason": body.get("reason"), "detail": body.get("detail"),
                "visible_reason": body.get("visible_reason"),
                "model": body.get("model")}
    except Exception:
        safe = {"http": st, "raw": str(body)[:200]}
    return safe


async def c1_retry(mod):
    res = {"scenario": "C1-positive-retry", "asset_mid": ASSET_MID}
    from services import mca_vision
    res["pre_probe"] = await _api_probe(mod)
    if not (res["pre_probe"] or {}).get("ok"):
        res["stop_reason"] = "pre_probe_failed"
        res["waiting_external"] = {
            "class": (res["pre_probe"] or {}).get("capability"),
            "detail": (res["pre_probe"] or {}).get("detail"),
            "visible_reason": (res["pre_probe"] or {}).get("visible_reason"),
            "at_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        }
        res["ok"] = False
        mod.save("c1-retry.json", res)
        out("C1", "pre-probe not ok: %s"
            % json.dumps(res["waiting_external"], ensure_ascii=False))
        return res
    asset = await _asset_row(mod, ASSET_MID)
    if asset is None:
        res["ok"] = False
        res["error"] = "asset row not found"
        mod.save("c1-retry.json", res)
        return res
    res["asset"] = {k: asset[k] for k in (
        "asset_id", "tg_message_id", "byte_size", "mime", "width", "height")}
    try:
        img = await mca_vision.download_telegram_file(
            mod.CTX.rec, str(asset["file_id"] or ""))
        res["download_check"] = {"ok": True, "bytes": img.byte_size,
                                 "mime": img.mime, "width": img.width,
                                 "height": img.height}
    except Exception as exc:  # noqa: BLE001
        res["download_check"] = {"ok": False,
                                 "error": "%s: %s" % (type(exc).__name__,
                                                      str(exc)[:140])}
        res["ok"] = False
        mod.save("c1-retry.json", res)
        return res
    res["analysis_before"] = await _analysis_row(mod, asset["asset_id"])
    photo_msg = mod.make_photo_message(asset, caption=None)

    turns = []
    tool = None
    stop = None
    t = None
    for attempt, phrase in enumerate(("бот, что тут?",
                                      "бот, прочитай надпись на фото"), 1):
        anchor = await mod.CTX.rec.send_message(
            WORK_CHAT, "🧪 Приёмка 2.58.92C · распознавание (ретрай %d)." % attempt)
        rec = {"attempt": attempt, "phrase": phrase,
               "announce_mid": anchor.message_id}
        vc_before = len(mod.CTX.vision_transport_calls)
        t = await mod.run_turn(phrase, msg_id=anchor.message_id,
                               reply_to=photo_msg,
                               label="c-vision-%d" % attempt, timeout=300)
        tool = _find_tool(t)
        rec.update(mod._strip_turn(t))
        rec["vision_transport_calls"] = (len(mod.CTX.vision_transport_calls)
                                         - vc_before)
        rec["tool"] = tool
        rec["plan_caps"] = mod._turn_plan_caps(t)
        turns.append(rec)
        if tool is not None:
            break
        if attempt >= 2:
            break
    res["turns"] = turns
    res["tool"] = tool
    res["status"] = (tool or {}).get("status")
    stop = _provider_stop(tool)
    if stop:
        res["stop_reason"] = stop
        res["waiting_external"] = {
            "class": stop,
            "visible_reason": (tool or {}).get("visible_reason"),
            "at_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        }
    if tool is not None and not stop and res["status"] != "ready":
        # pending (or other non-terminal): wait for the analysis, then repeat
        res["analysis_after_wait"] = await _wait_analysis(
            mod, asset["asset_id"], timeout_s=180)
        if (res["analysis_after_wait"] or {}).get("status") == "ready":
            anchor2 = await mod.CTX.rec.send_message(
                WORK_CHAT, "🧪 Приёмка 2.58.92C · распознавание (повтор, кеш).")
            t2 = await mod.run_turn("бот, что тут?", msg_id=anchor2.message_id,
                                    reply_to=photo_msg, label="c-vision-repeat",
                                    timeout=300)
            tool2 = _find_tool(t2)
            res["turn_repeat"] = {"phrase": "бот, что тут?",
                                  "announce_mid": anchor2.message_id,
                                  **mod._strip_turn(t2)}
            res["tool_repeat"] = tool2
            res["status_repeat"] = (tool2 or {}).get("status")
            tool = tool2 or tool
        else:
            st = (res["analysis_after_wait"] or {}).get("status")
            if st in ("unavailable", "failed"):
                res["stop_reason"] = "analysis_%s" % st
                res["waiting_external"] = {
                    "class": (res["analysis_after_wait"] or {}).get(
                        "error_reason"),
                    "at_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                            time.gmtime()),
                }
    res["analysis_final"] = await _analysis_row(mod, asset["asset_id"])
    final_status = res.get("status_repeat") or res.get("status")
    res["positive_recognition"] = final_status == "ready"
    res["ok"] = bool(res["positive_recognition"])
    if res["positive_recognition"]:
        row = res["analysis_final"] or {}
        desc = str(row.get("visual_description") or "")
        res["description"] = {"len": len(desc), "head": desc[:400],
                              "analyzer_model": row.get("analyzer_model"),
                              "revision": row.get("revision"),
                              "completed_at": row.get("completed_at")}
    mod.save("c1-retry.json", res)
    out("C1", json.dumps({"status": res.get("status"),
                          "status_repeat": res.get("status_repeat"),
                          "positive": res["positive_recognition"],
                          "stop": res.get("stop_reason")},
                         ensure_ascii=False))
    return res


async def c2_postgen(mod):
    res = {"scenario": "C2-postgen"}
    from services import postgen_vision as pv
    from config.settings import settings as st
    res["postgen_enabled"] = bool(getattr(st, "IMAGE_POSTGEN_VISION_ENABLED",
                                          True))
    try:
        res["postgen_budget_s"] = float(pv.analysis_budget_seconds())
    except Exception:
        pass
    anchor = await mod.CTX.rec.send_message(
        WORK_CHAT, "🧪 Приёмка 2.58.92C · генерация + пост-генерация (контроль).")
    res["announce_mid"] = anchor.message_id
    res["query"] = GEN_PROMPT
    p_before = len(mod.CTX.provider_calls)
    heads_before = len(BSTATE["postgen_heads"])
    t = await mod.run_turn(GEN_PROMPT, msg_id=anchor.message_id,
                           reply_to=anchor, label="c-gen", timeout=360)
    res["provider_calls"] = len(mod.CTX.provider_calls) - p_before
    res["turn"] = {"phrase": GEN_PROMPT, **mod._strip_turn(t)}
    res["image_blocks"] = t.get("image_blocks")
    res["postgen_turn"] = t.get("postgen")
    res["postgen_heads"] = BSTATE["postgen_heads"][heads_before:]
    sends = t.get("sends") or []
    res["photo_sends"] = [s for s in sends if s.get("kind") == "photo"]
    res["text_sends"] = [s for s in sends if s.get("kind") == "message"]
    res["ok"] = bool(res["photo_sends"])
    res["postgen_ok"] = any(
        (h.get("status") == "ready" and h.get("has_content"))
        for h in res["postgen_heads"])
    mod.save("c2-postgen.json", res)
    out("C2", json.dumps({"provider_calls": res["provider_calls"],
                          "photo_mids": [s.get("message_id")
                                         for s in res["photo_sends"]],
                          "postgen_ok": res["postgen_ok"]},
                         ensure_ascii=False))
    return res


async def c3_final(mod, start_epoch):
    res = {"scenario": "C3-final", "start_epoch": start_epoch,
           "t0_epoch": 1792365948}
    try:
        res["head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
        res["tracked_mod"] = int(subprocess.check_output(
            "git status --porcelain | grep -v '^??' | wc -l",
            cwd=APP, shell=True, text=True).strip() or 0)
    except Exception:
        pass
    try:
        st, body = await mod.CTX.api.req("GET", "/api/vision/state",
                                         chat_id=WORK_CHAT)
        res["vision_state"] = {"http": st, "body": body}
    except Exception as exc:  # noqa: BLE001
        res["vision_state_error"] = type(exc).__name__
    try:
        res["budget"] = await mod.pg_fetch(
            "SELECT day, scope, metric, used FROM worker_budget "
            "WHERE metric='image_calls' ORDER BY day DESC, scope LIMIT 12")
        res["reservations_since_start"] = await mod.pg_fetch(
            "SELECT reservation_key, status, error_code, delivery_failed, "
            "created_at FROM image_reservation "
            "WHERE created_at >= to_timestamp($1) ORDER BY created_at",
            start_epoch)
        res["usage_since_start"] = await mod.pg_fetch(
            "SELECT step, COUNT(*) n, "
            "COALESCE(SUM(input_tokens+output_tokens),0) tokens "
            "FROM llm_usage_events WHERE ts >= to_timestamp($1) "
            "GROUP BY step ORDER BY n DESC", start_epoch)
    except Exception as exc:  # noqa: BLE001
        res["pg_error"] = type(exc).__name__
    try:
        res["jobs_recent"] = await mod.sqlite_fetch(
            "SELECT job_id, kind, status, reason_code, attempt, created_at, "
            "updated_at FROM task_jobs WHERE kind LIKE 'vision%' "
            "ORDER BY updated_at DESC LIMIT 8", ())
        res["analyses_recent"] = await mod.sqlite_fetch(
            "SELECT id, asset_id, status, revision, analyzer_model, "
            "error_reason, completed_at FROM mca_media_analyses "
            "ORDER BY id DESC LIMIT 6", ())
    except Exception as exc:  # noqa: BLE001
        res["sqlite_error"] = type(exc).__name__
    mod.save("c3-final.json", res)
    out("C3", "done")
    return res


async def main() -> int:
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    mod = load_base()
    mod.EVID = "/tmp/accept92c/evidence"
    os.makedirs(mod.EVID, exist_ok=True)
    await mod.bootstrap()
    mod.CTX.api = mod.Api()
    _wrap_postgen_heads()
    start_epoch = int(time.time())
    out("START_EPOCH", start_epoch)

    c1 = await _safe("C1", c1_retry, mod)
    c2 = None
    if isinstance(c1, dict) and c1.get("positive_recognition"):
        c2 = await _safe("C2", c2_postgen, mod)
    else:
        out("C2", "skipped (C1 not positive)")
    c3 = await _safe("C3", c3_final, mod, start_epoch)

    summary = {
        "start_epoch": start_epoch,
        "t0_epoch": 1792365948,
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "c1_positive": (c1 or {}).get("positive_recognition"),
        "c1_status": (c1 or {}).get("status"),
        "c1_status_repeat": (c1 or {}).get("status_repeat"),
        "c1_stop_reason": (c1 or {}).get("stop_reason"),
        "c1_waiting_external": (c1 or {}).get("waiting_external"),
        "c1_description": (c1 or {}).get("description"),
        "c2_ran": c2 is not None,
        "c2_ok": (c2 or {}).get("ok"),
        "c2_postgen_ok": (c2 or {}).get("postgen_ok"),
        "c2_photo_sends": (c2 or {}).get("photo_sends"),
        "sends": mod._sanitize_sends(mod.CTX.rec.sends),
        "tool_calls": [t.get("tool") for t in mod.CTX.tool_calls],
        "postgen_heads": BSTATE["postgen_heads"],
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
        print("ACC92C FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC92C RC=%d" % rc, flush=True)
    os._exit(rc)
