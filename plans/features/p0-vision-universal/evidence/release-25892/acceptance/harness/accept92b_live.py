# -*- coding: utf-8 -*-
"""ACCEPTANCE-92B — positive Vision recognition + post-generation (prod 2.58.92).

One controlled process ON the production host (NOT the poller) via the proven
ACCEPTANCE-91 bootstrap (uploaded as /tmp/accept92b_base.py). Real Telegram
delivery, real SQLite/PG, real providers. Budget: exactly ONE image generation.

B1: reply-to-fresh-photo -> recognize_image -> real provider analysis (the prod
    vision model kept per PET) -> ready -> meaningful answer -> delivery mid.
    Fresh asset is pre-checked with a real Telegram download before the turn
    (legacy assets 1165606/1165607 are excluded: download fails, data finding).
B2: "бот, нарисуй ..." -> 1 generation -> photo delivery -> image_postgen_vision
    (description from the final bitmap analysis).
B3: final state/economics snapshot.

Evidence: /tmp/accept92b/evidence/*.json
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
EXCLUDE_PHOTOS = {1165606, 1165607}      # legacy: download fails (data)
BSTATE: dict = {"postgen_heads": []}


def out(tag, text):
    print("ACC92B %s | %s" % (tag, text), flush=True)


def load_base():
    spec = importlib.util.spec_from_file_location("accept92b_base",
                                                  "/tmp/accept92b_base.py")
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
    """Second wrap over the base spy: capture a bounded description head."""
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
            "desc_head": desc[:200],
            "bytes": len(data) if isinstance(data, (bytes, bytearray)) else None,
        })
        return outcome

    pv.analyze_generated_image = spy


# ─────────────────────────── B1: positive recognition ───────────────────────

async def _photo_candidates(mod):
    rows = await mod.sqlite_fetch(
        "SELECT asset_id, tg_message_id, asset_kind, mime, byte_size, "
        "width, height, file_id, file_unique_id FROM mca_media_assets "
        "WHERE chat_id=? AND asset_kind='photo' AND byte_size>=20000 "
        "ORDER BY tg_message_id DESC LIMIT 12", (WORK_CHAT,))
    for r in rows:
        try:
            cur = await mod.CTX.db.db.execute(
                "SELECT status, revision, analyzer_model, error_reason "
                "FROM mca_media_analyses WHERE asset_id=? "
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


async def _pick_downloadable_photo(mod):
    from services import mca_vision
    rows = await _photo_candidates(mod)
    checks = []
    for r in rows:
        mid = int(r["tg_message_id"] or 0)
        if mid in EXCLUDE_PHOTOS or r.get("bot_sent"):
            continue
        if (r.get("last_analysis") or {}).get("status") in ("ready", "no_text"):
            continue
        rec = {"mid": mid, "asset_id": r["asset_id"],
               "byte_size": r["byte_size"]}
        try:
            img = await mca_vision.download_telegram_file(
                mod.CTX.rec, str(r["file_id"] or ""))
            rec.update({"download": "ok", "bytes": img.byte_size,
                        "mime": img.mime, "width": img.width,
                        "height": img.height})
            checks.append(rec)
            return r, checks
        except Exception as exc:  # noqa: BLE001
            rec.update({"download": "fail",
                        "error": "%s: %s" % (type(exc).__name__,
                                             str(exc)[:140])})
            checks.append(rec)
    return None, checks


async def _wait_analysis(mod, asset_id, timeout_s=180):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            cur = await mod.CTX.db.db.execute(
                "SELECT status, revision, analyzer_model, error_reason, "
                "completed_at FROM mca_media_analyses WHERE asset_id=? "
                "ORDER BY id DESC LIMIT 1", (str(asset_id),))
            row = await cur.fetchone()
            last = dict(row) if row is not None else None
        except Exception:
            last = None
        if last and last.get("status") in ("ready", "no_text", "unreadable",
                                           "unsupported", "failed",
                                           "unavailable"):
            return last
        await asyncio.sleep(5)
    return last


async def b1_recognition(mod):
    res = {"scenario": "B1-positive-recognition"}
    asset, checks = await _pick_downloadable_photo(mod)
    res["download_checks"] = checks
    if asset is None:
        res["ok"] = False
        res["error"] = "no downloadable fresh photo"
        mod.save("b1-recognition.json", res)
        return res
    res["asset"] = {"asset_id": asset["asset_id"],
                    "tg_message_id": asset["tg_message_id"],
                    "byte_size": asset["byte_size"], "mime": asset["mime"]}
    photo_msg = mod.make_photo_message(asset, caption=None)
    anchor = await mod.CTX.rec.send_message(
        WORK_CHAT, "🧪 Приёмка 2.58.92B · распознавание свежего фото (контроль).")
    res["announce_mid"] = anchor.message_id
    t1 = await mod.run_turn("бот, что тут?", msg_id=anchor.message_id,
                            reply_to=photo_msg, label="b-vision-1",
                            timeout=300)
    res["turn1"] = {"phrase": "бот, что тут?", **mod._strip_turn(t1)}
    tool1 = next((x for x in t1.get("tool_calls", [])
                  if x.get("tool") == "recognize_image"), None)
    res["tool1"] = tool1
    res["status1"] = (tool1 or {}).get("status")
    if res["status1"] != "ready":
        res["analysis_after_wait"] = await _wait_analysis(
            mod, asset["asset_id"], timeout_s=180)
        anchor2 = await mod.CTX.rec.send_message(
            WORK_CHAT, "🧪 Приёмка 2.58.92B · распознавание (повтор, кеш).")
        res["announce2_mid"] = anchor2.message_id
        t2 = await mod.run_turn("бот, что тут?", msg_id=anchor2.message_id,
                                reply_to=photo_msg, label="b-vision-2",
                                timeout=300)
        res["turn2"] = {"phrase": "бот, что тут?", **mod._strip_turn(t2)}
        tool2 = next((x for x in t2.get("tool_calls", [])
                      if x.get("tool") == "recognize_image"), None)
        res["tool2"] = tool2
        res["status2"] = (tool2 or {}).get("status")
    res["analysis_final"] = await _wait_analysis(
        mod, asset["asset_id"], timeout_s=10)
    final_tool = res.get("tool2") or res.get("tool1") or {}
    res["ok"] = (final_tool.get("status") == "ready")
    res["positive_recognition"] = res["ok"]
    mod.save("b1-recognition.json", res)
    out("B1", json.dumps({k: res.get(k) for k in (
        "status1", "status2", "positive_recognition")}, ensure_ascii=False))
    return res


# ─────────────────────────── B2: post-generation ────────────────────────────

async def b2_postgen(mod):
    res = {"scenario": "B2-postgen"}
    from services import postgen_vision as pv
    from config.settings import settings as st
    try:
        res["postgen_enabled"] = bool(getattr(st, "IMAGE_POSTGEN_VISION_ENABLED",
                                              True))
        res["postgen_budget_s"] = float(pv.analysis_budget_seconds())
    except Exception as exc:  # noqa: BLE001
        res["postgen_cfg_error"] = type(exc).__name__
    anchor = await mod.CTX.rec.send_message(
        WORK_CHAT, "🧪 Приёмка 2.58.92B · генерация + пост-генерация (контроль).")
    res["announce_mid"] = anchor.message_id
    q = "бот, нарисуй безобидный рисунок: жёлтый лимон на белом фоне"
    res["query"] = q
    p_before = len(mod.CTX.provider_calls)
    heads_before = len(BSTATE["postgen_heads"])
    t = await mod.run_turn(q, msg_id=anchor.message_id, reply_to=anchor,
                           label="b-gen", timeout=360)
    res["provider_calls"] = len(mod.CTX.provider_calls) - p_before
    res["turn"] = {"phrase": q, **mod._strip_turn(t)}
    res["image_blocks"] = t.get("image_blocks")
    res["postgen_turn"] = t.get("postgen")
    res["postgen_heads"] = BSTATE["postgen_heads"][heads_before:]
    sends = t.get("sends") or []
    res["photo_sends"] = [s for s in sends if s.get("kind") == "photo"]
    res["text_sends"] = [s for s in sends if s.get("kind") == "message"]
    ok_photo = bool(res["photo_sends"])
    ok_postgen = any((h.get("status") == "ready" and h.get("has_content"))
                     for h in res["postgen_heads"])
    res["ok"] = bool(ok_photo)
    res["postgen_ok"] = ok_postgen
    mod.save("b2-postgen.json", res)
    out("B2", json.dumps({"provider_calls": res["provider_calls"],
                          "photo_mids": [s.get("message_id")
                                         for s in res["photo_sends"]],
                          "postgen_ok": ok_postgen}, ensure_ascii=False))
    return res


# ─────────────────────────── B3: final state ────────────────────────────────

async def b3_final(mod, start_epoch):
    res = {"scenario": "B3-final", "start_epoch": start_epoch,
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
            "WHERE metric='image_calls' ORDER BY day DESC, scope LIMIT 16")
        res["reservations_since_start"] = await mod.pg_fetch(
            "SELECT reservation_key, status, error_code, delivery_failed, "
            "created_at FROM image_reservation "
            "WHERE created_at >= to_timestamp($1) ORDER BY created_at",
            start_epoch)
        res["usage_since_start"] = await mod.pg_fetch(
            "SELECT step, COUNT(*) n, COALESCE(SUM(input_tokens+output_tokens),0) "
            "tokens FROM llm_usage_events WHERE ts >= to_timestamp($1) "
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
        res["user_version"] = (await mod.sqlite_fetch("PRAGMA user_version"))[0]
    except Exception as exc:  # noqa: BLE001
        res["sqlite_error"] = type(exc).__name__
    mod.save("b3-final.json", res)
    out("B3", "done")
    return res


# ─────────────────────────── main ───────────────────────────────────────────

async def main() -> int:
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    mod = load_base()
    mod.EVID = "/tmp/accept92b/evidence"
    os.makedirs(mod.EVID, exist_ok=True)
    await mod.bootstrap()
    mod.CTX.api = mod.Api()
    _wrap_postgen_heads()
    start_epoch = int(time.time())
    out("START_EPOCH", start_epoch)

    b1 = await _safe("B1", b1_recognition, mod)
    b2 = await _safe("B2", b2_postgen, mod)
    b3 = await _safe("B3", b3_final, mod, start_epoch)

    summary = {
        "start_epoch": start_epoch,
        "t0_epoch": 1792365948,
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "b1_positive": (b1 or {}).get("positive_recognition"),
        "b1_status1": (b1 or {}).get("status1"),
        "b1_status2": (b1 or {}).get("status2"),
        "b1_asset": (b1 or {}).get("asset"),
        "b2_ok": (b2 or {}).get("ok"),
        "b2_postgen_ok": (b2 or {}).get("postgen_ok"),
        "b2_provider_calls": (b2 or {}).get("provider_calls"),
        "b2_photo_sends": (b2 or {}).get("photo_sends"),
        "sends": mod._sanitize_sends(mod.CTX.rec.sends),
        "tool_calls": [t.get("tool") for t in mod.CTX.tool_calls],
        "postgen": mod.CTX.postgen,
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
        print("ACC92B FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC92B RC=%d" % rc, flush=True)
    os._exit(rc)
