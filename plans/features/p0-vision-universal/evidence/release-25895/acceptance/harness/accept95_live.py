# -*- coding: utf-8 -*-
"""ACCEPTANCE-95 — live acceptance for prod 2.58.95 (CFG-03 Ф6 + POSTGEN +
VISION-ADAPT + orphan + cleanup register).

Phases (evidence -> /tmp/accept95/evidence/*.json):
  P0  pre-state snapshot (config/budgets/vision/analyses/jobs/debts)
  P1  vision-adapt fixture: real document upload + intake + download precheck
  P2  flags.vision_enabled OFF in the work chat -> honest refusal (03.4/03.12)
  P3  vision ON -> long PNG document analysis through the adaptive path (c)
  P4  03.4 quota hot-check + exactly ONE live post-generation (b)
  P5  03.11 negatives (wrong type / bad option / stale 409)
  P6  03.6 showcase via the live admin API + served-bytes equality
  P7  economics/journal data + orphan classification (d)
  P8  cleanup register (mids) + mca_events flush

No product code is modified. Controlled writes: synthetic user 990002001 +
temporary per-chat overrides restored exactly (chat_params snapshot/restore).
"""
from __future__ import annotations

import asyncio
import hashlib
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
BOT_ID = 8802473181
EVID = "/tmp/accept95/evidence"
FIXTURE = "/tmp/accept95/fixture.png"
FIXTURE_META = "/tmp/accept95/fixture-ground-truth.json"
CLEANUP_OUT = "/tmp/accept95_cleanup_mids.json"

DEAD_KEYS = [
    "limits.chat_budget_response_ratio",
    "limits.chat_lock_max_entries",
    "limits.dig_year_back_window_days",
    "limits.youtube_transcript_proxy_locations",
    "limits.youtube_transcript_proxy_retries",
]
HONEST_MARK = "Не влияет: значение сохраняется в конфиге"

GEN_PROMPT_1 = "бот, нарисуй оранжевый апельсин на белом фоне"
GEN_PROMPT_2 = "бот, нарисуй зелёную грушу на белом фоне"


def load_base():
    spec = importlib.util.spec_from_file_location("accept95_base",
                                                  "/tmp/accept95_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def out(tag, text):
    print("ACC95 %s | %s" % (tag, text), flush=True)


def doc_kwargs(p1):
    """Synthetic document object for the fixture message (from P1 evidence).

    The real file_id/file_unique_id live under underscore keys (stripped from
    the saved JSON, kept in-process) — no chat identifiers leak into evidence.
    """
    sent = (p1 or {}).get("sent") or {}
    return {
        "file_id": sent.get("_file_id"),
        "file_unique_id": sent.get("_file_unique_id"),
        "mime_type": sent.get("_mime_type") or "image/png",
        "file_size": sent.get("_file_size"),
        "file_name": sent.get("_file_name") or "fixture-95.png",
    }


def make_doc_obj(base, p1):
    kw = doc_kwargs(p1)
    return base.make_document(kw["file_id"], kw["file_unique_id"],
                              kw["mime_type"], kw["file_size"],
                              kw["file_name"])


async def main() -> int:
    try:
        os.umask(0o022)
    except Exception:
        pass
    base = load_base()
    out("START_EPOCH", base.START_EPOCH)
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    await base.bootstrap()
    base.CTX.api = base.Api()
    from services import chat_params
    root = await chat_params.get_all_chat_params(WORK_CHAT, pg=base.CTX.pg)
    base.CTX.original_overrides = dict((root or {}).get("overrides") or {})
    out("OVERRIDES", "touched=%s total_keys=%d"
        % (json.dumps({k: base.CTX.original_overrides[k]
                       for k in base.TOUCH_KEYS
                       if k in base.CTX.original_overrides},
                      ensure_ascii=False), len(base.CTX.original_overrides)))
    results = {}
    try:
        results["p0"] = await phase0_pre_state(base)
        results["p1"] = await phase1_fixture(base)
        results["p2"] = await phase2_vision_off(base, results["p1"])
        results["p3"] = await phase3_vision_on(base, results["p1"],
                                               results["p2"])
        results["p4"] = await phase4_generation(base)
        results["p5"] = await phase5_negatives(base)
        results["p6"] = await phase6_showcase(base)
        results["p7"] = await phase7_economics(base, results)
        results["p8"] = await phase8_cleanup_register(base, results)
    except Exception as exc:  # noqa: BLE001
        import traceback
        out("FATAL", "%s: %s" % (type(exc).__name__, str(exc)[:300]))
        traceback.print_exc()
        results["fatal"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
    # safety net: never leave temporary overrides behind
    try:
        changed = await base.restore_overrides(base.TOUCH_KEYS, "final-safety")
        results["final_restore"] = changed
    except Exception as exc:  # noqa: BLE001
        out("FATAL", "final restore failed: %s" % type(exc).__name__)
        results["final_restore"] = "failed: %s" % type(exc).__name__
    try:
        from services import mca_events
        flushed = await mca_events.flush_events(base.CTX.db)
        out("FLUSH", "mca_events flushed=%s" % flushed)
    except Exception as exc:  # noqa: BLE001
        out("FLUSH", "failed: %s" % type(exc).__name__)
    base.save("summary.json", {
        "start_epoch": base.START_EPOCH,
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "phases": {k: (v.get("ok") if isinstance(v, dict) else None)
                   for k, v in results.items()},
        "tools_called": [t.get("tool") for t in base.CTX.tool_calls],
        "provider_calls": base.CTX.provider_calls,
        "vision_transport_calls": base.CTX.vision_transport_calls,
        "postgen": base.CTX.postgen,
        "sends": base._sanitize_sends(base.CTX.rec.sends),
    })
    out("DONE", "evidence=%s" % EVID)
    await base.close_all()
    return 0


# ─────────────────────────── P0 ─────────────────────────────────────────────

async def phase0_pre_state(base):
    res = {"phase": "P0-pre-state",
           "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    from config.settings import settings
    from services import image_normalize, mca_gates, mca_vision
    res["app_version"] = str(getattr(settings, "APP_VERSION", "?"))
    res["axes"] = {
        "DOWNLOAD_ENABLED": bool(getattr(settings, "DOWNLOAD_ENABLED", None)),
        "LOCAL_BOT_API_URL": str(getattr(settings, "LOCAL_BOT_API_URL", "")),
        "TELEGRAM_LOCAL": str(getattr(settings, "TELEGRAM_LOCAL", "")),
        "DB_PATH": str(getattr(settings, "DB_PATH", "")),
    }
    lim = image_normalize.vision_limits()
    res["vision_limits"] = {
        "request_max_bytes": lim.request_max_bytes,
        "prep_max_pixels": lim.prep_max_pixels,
        "hard_max_pixels": lim.hard_max_pixels,
        "adapt_budget_seconds": lim.adapt_budget_seconds,
        "segment_window": lim.segment_window,
        "normalize_enabled": image_normalize.normalize_enabled(),
        "codec": image_normalize.codec_available(),
        "defaults_match": (lim.request_max_bytes == 700_000
                           and lim.prep_max_pixels == 4_000_000
                           and abs(lim.adapt_budget_seconds - 90.0) < 0.01),
    }
    res["gates"] = {
        "vision_enabled": mca_gates.vision_enabled(),
        "vision_tool_enabled": mca_gates.vision_tool_enabled(),
        "vision_max_bytes": mca_gates.vision_max_bytes(),
        "vision_max_pixels": mca_gates.vision_max_pixels(),
    }
    try:
        st = await mca_vision.resolve_effective_state(WORK_CHAT)
        res["vision_state_before"] = {
            "requested": st.requested, "effective": st.effective_enabled,
            "capability": st.capability, "reason": st.reason,
            "visible_reason": st.visible_reason, "model": st.model,
            "source": st.source}
    except Exception as exc:  # noqa: BLE001
        res["vision_state_before"] = "failed:%s" % type(exc).__name__
    from services import image_generation as ig
    res["reserve_mode_before"] = list(await ig.image_reserve_mode(WORK_CHAT))
    try:
        freq_limits, freq_reason = await ig.image_freq_config(WORK_CHAT)
        res["freq_config_before"] = {
            "reason": freq_reason,
            "enabled": bool(getattr(freq_limits, "enabled", None)),
            "mode": str(getattr(freq_limits, "mode", "")),
            "burst": getattr(freq_limits, "burst", None),
            "cooldown": getattr(freq_limits, "cooldown_seconds", None)}
    except Exception as exc:  # noqa: BLE001
        res["freq_config_before"] = "failed:%s" % type(exc).__name__
    st, cfg = await base.CTX.api.req("GET", "/api/config", chat_id=WORK_CHAT)
    res["config_before"] = {"http": st, "items": base.pick_cfg(cfg,
                                                              base.TOUCH_KEYS)}
    st, budget = await base.CTX.api.req("GET", "/api/workers/budget")
    res["budget_before"] = _budget_pick(budget)
    # DB snapshots
    try:
        res["analyses_counts_before"] = await base.sqlite_fetch(
            "SELECT status, COUNT(*) n FROM mca_media_analyses "
            "GROUP BY status ORDER BY n DESC")
        res["analyses_running_before"] = await base.sqlite_fetch(
            "SELECT id, asset_id, status, revision, analyzer_model, "
            "analyzer_provider, created_at, updated_at, error_reason "
            "FROM mca_media_analyses WHERE status='running' "
            "ORDER BY id")
        res["jobs_recent_before"] = await base.sqlite_fetch(
            "SELECT job_id, owner, kind, status, reason_code, attempt, "
            "created_at, updated_at, heartbeat_at, coalesce_key "
            "FROM task_jobs WHERE kind IN ('vision.media','vision.backfill') "
            "ORDER BY created_at DESC LIMIT 12")
        res["events_recent_before"] = await base.sqlite_fetch(
            "SELECT event_name, outcome, level, component, stage, "
            "reason_code, chat_id, COUNT(*) n, MAX(ts) last_ts "
            "FROM mca_events WHERE event_name IN "
            "('vision_adapt','image_postgen_vision','vision_media') "
            "GROUP BY 1,2,3,4,5,6,7 ORDER BY last_ts DESC LIMIT 30")
        res["user_version_before"] = await base.sqlite_fetch(
            "PRAGMA user_version")
    except Exception as exc:  # noqa: BLE001
        res["sqlite_error"] = type(exc).__name__
    try:
        res["debts_scan"] = await base.sqlite_fetch(
            "SELECT tg_message_id mid, user_id, author_name, media_type, "
            "reply_to_id, timestamp, substr(text,1,90) head "
            "FROM smart_messages WHERE chat_id=? AND tg_message_id IS NOT "
            "NULL AND (user_id=? OR text LIKE '%Приёмка%' OR text LIKE "
            "'%приёмка%' OR text LIKE '%🧪%' OR text LIKE '%accept%') "
            "ORDER BY tg_message_id DESC LIMIT 40", (WORK_CHAT, SYNTH_USER))
    except Exception as exc:  # noqa: BLE001
        res["debts_error"] = type(exc).__name__
    try:
        res["pg_reservations_before"] = await base.pg_fetch(
            "SELECT COUNT(*) n FROM image_reservation WHERE chat_id=$1 "
            "AND created_at >= to_timestamp($2)", (WORK_CHAT,
                                                   base.START_EPOCH))
        res["pg_budget_rows_before"] = await base.pg_fetch(
            "SELECT day, scope, metric, used FROM worker_budget "
            "WHERE metric='image_calls' ORDER BY day DESC, scope LIMIT 12")
    except Exception as exc:  # noqa: BLE001
        res["pg_error"] = type(exc).__name__
    res["ok"] = bool(res.get("vision_limits"))
    base.save("p0-pre-state.json", res)
    out("P0", "done ok=%s" % res["ok"])
    return res


def _budget_pick(budget):
    entry = None
    for e in (budget.get("chats") or []) if isinstance(budget, dict) else []:
        if str(e.get("scope")) == "chat:%d" % WORK_CHAT:
            entry = e
            break
    g = ((budget or {}).get("global") or {}).get("image_calls") or {}
    img = (entry or {}).get("image_calls") or {}
    use = (entry or {}).get("image_usage") or {}
    return {
        "http_ok": bool(budget),
        "global_used": g.get("used"), "global_limit": g.get("limit"),
        "global_cover_used": g.get("cover_used"),
        "chat_used": img.get("used"), "chat_limit": img.get("limit"),
        "chat_day": img.get("day"), "chat_tz": img.get("timezone"),
        "chat_source": img.get("source"),
        "reserve_path": use.get("reserve_path"),
        "reserve_reason": use.get("reserve_reason"),
        "shared_used": use.get("shared_used"),
        "shared_limit": use.get("shared_limit"),
        "requests": use.get("requests"), "success": use.get("success"),
        "errors": use.get("errors"), "denied": use.get("denied"),
        "delivery_failed": use.get("delivery_failed"),
        "freq": use.get("freq"),
    }


# ─────────────────────────── P1 ─────────────────────────────────────────────

async def phase1_fixture(base):
    res = {"phase": "P1-fixture-doc"}
    from aiogram.types import FSInputFile
    meta = json.load(open(FIXTURE_META, encoding="utf-8"))
    raw = open(FIXTURE, "rb").read()
    res["fixture"] = {"bytes": len(raw), "sha256": meta.get("sha256"),
                      "sha12": meta.get("sha256_12"),
                      "width": meta.get("width"), "height": meta.get("height"),
                      "pixels": meta.get("pixels"),
                      "payload_chars_est": meta.get("payload_chars_est"),
                      "gt_tokens": meta.get("gt_tokens"),
                      "over_700k": meta.get("over_request_max_bytes_700k")}
    caption = ("🧪 Приёмка 2.58.95 · фикстура vision-adapt "
               "(длинный PNG-скриншот, >700 КБ)")
    msg = await base.CTX.rec.send_document(
        WORK_CHAT, FSInputFile(FIXTURE), caption=caption)
    doc = getattr(msg, "document", None)
    res["sent"] = {
        "message_id": getattr(msg, "message_id", None),
        "file_id_present": bool(getattr(doc, "file_id", None)),
        "file_id_len": len(str(getattr(doc, "file_id", "") or "")),
        "file_unique_id": str(getattr(doc, "file_unique_id", "") or ""),
        "file_name": str(getattr(doc, "file_name", "") or ""),
        "file_size": getattr(doc, "file_size", None),
        "mime_type": str(getattr(doc, "mime_type", "") or ""),
        "caption_head": caption[:120],
        # in-process only (stripped from the saved evidence):
        "_file_id": str(getattr(doc, "file_id", "") or ""),
        "_file_unique_id": str(getattr(doc, "file_unique_id", "") or ""),
        "_mime_type": str(getattr(doc, "mime_type", "") or "image/png"),
        "_file_size": getattr(doc, "file_size", None),
        "_file_name": str(getattr(doc, "file_name", "") or "fixture-95.png"),
    }
    doc_mid = int(getattr(msg, "message_id"))
    synthetic = base.make_message(
        msg_id=doc_mid, caption=caption,
        document=base.make_document(
            getattr(doc, "file_id", None),
            getattr(doc, "file_unique_id", None),
            str(getattr(doc, "mime_type", "") or "image/png"),
            getattr(doc, "file_size", None),
            str(getattr(doc, "file_name", "") or "fixture-95.png")))
    from services import mca_vision
    ids = await mca_vision.register_intake_assets(base.CTX.db, synthetic)
    res["intake_asset_ids"] = ids
    res["asset_id"] = ids[0] if ids else None
    # prod-faithful download pre-check (local Bot API session, same FS view)
    try:
        image = await mca_vision.download_telegram_file(
            base.CTX.bot, str(getattr(doc, "file_id", "")))
        got_sha = hashlib.sha256(image.data).hexdigest()
        res["download_precheck"] = {
            "bytes": len(image.data), "mime": image.mime,
            "width": image.width, "height": image.height,
            "sha256": got_sha,
            "bytes_equal_fixture": len(image.data) == len(raw),
            "sha_equal_fixture": got_sha == meta.get("sha256"),
        }
    except Exception as exc:  # noqa: BLE001
        res["download_precheck"] = "failed: %s: %s" % (
            type(exc).__name__, str(exc)[:200])
    res["doc_mid"] = doc_mid
    res["ok"] = bool(ids) and bool(
        res.get("download_precheck", {}).get("sha_equal_fixture"))
    base.save("p1-fixture-doc.json", res)
    out("P1", "done mid=%s asset=%s precheck_ok=%s"
        % (doc_mid, res["asset_id"], res["ok"]))
    return res


# ─────────────────────────── P2 ─────────────────────────────────────────────

async def _analyses_for_asset(base, asset_id):
    return await base.sqlite_fetch(
        "SELECT id, status, revision, analyzer_model, created_at, updated_at, "
        "error_reason, length(visual_description) desc_len "
        "FROM mca_media_analyses WHERE asset_id=? ORDER BY id",
        (asset_id,))


async def _jobs_for_asset(base, asset_id):
    return await base.sqlite_fetch(
        "SELECT job_id, status, reason_code, attempt, created_at, updated_at "
        "FROM task_jobs WHERE coalesce_key=? ORDER BY created_at DESC",
        ("vision:asset:%s" % asset_id,))


async def phase2_vision_off(base, p1):
    res = {"phase": "P2-vision-off", "asset_id": p1.get("asset_id"),
           "doc_mid": p1.get("doc_mid")}
    from services import mca_vision
    asset_id = p1.get("asset_id")
    doc_mid = int(p1.get("doc_mid"))
    # premise: chat override flags.vision_enabled=false
    res["cfg_write"] = await base.set_cfg(
        [{"key": "flags.vision_enabled", "value": False}], "vision-off")
    await asyncio.sleep(2.0)
    await base.invalidate_caches()
    try:
        st = await mca_vision.resolve_effective_state(WORK_CHAT)
        res["vision_state_off"] = {
            "requested": st.requested, "effective": st.effective_enabled,
            "reason": st.reason, "visible_reason": st.visible_reason,
            "capability": st.capability}
    except Exception as exc:  # noqa: BLE001
        res["vision_state_off"] = "failed:%s" % type(exc).__name__
    # deterministic server-side proof: direct tool dispatch
    try:
        raw = await base.CTX.router.dispatch(
            "recognize_image",
            {"target": {"chat_id": WORK_CHAT, "message_id": doc_mid}},
            base._tool_ctx("vision-off-direct", message_id=doc_mid))
        res["direct_tool_result"] = json.loads(str(raw))
    except Exception as exc:  # noqa: BLE001
        res["direct_tool_result"] = "failed:%s" % type(exc).__name__
    # full turn (end-to-end honest answer)
    transport_before = len(base.CTX.vision_transport_calls)
    turn = await base.run_turn(
        None, msg_id=doc_mid, caption="бот, что на картинке?",
        document=make_doc_obj(base, p1), label="vision-off-turn",
        timeout=240)
    res["turn"] = base._strip_turn(turn)
    res["turn"]["vision_transport_calls"] = turn.get(
        "vision_transport_calls")
    res["transport_delta"] = (len(base.CTX.vision_transport_calls)
                              - transport_before)
    res["analyses_after_off"] = await _analyses_for_asset(base, asset_id)
    res["jobs_after_off"] = await _jobs_for_asset(base, asset_id)
    gt = p1["fixture"]["gt_tokens"] or []
    answer = str(turn.get("answer") or "")
    res["answer_gt_tokens_found"] = [t for t in gt
                                     if t.lower() in answer.lower()]
    res["ok"] = (
        str(res.get("vision_state_off", {}).get("reason")) == "vision_disabled"
        and str(res.get("direct_tool_result", {}).get("status")) == "disabled"
        and res["transport_delta"] == 0
        and not res["analyses_after_off"]
        and not res["jobs_after_off"]
        and not res["answer_gt_tokens_found"])
    base.save("p2-vision-off.json", res)
    out("P2", "done ok=%s reason=%s direct=%s transport=%d"
        % (res["ok"], res.get("vision_state_off", {}).get("reason"),
           res.get("direct_tool_result", {}).get("status"),
           res["transport_delta"]))
    return res


# ─────────────────────────── P3 ─────────────────────────────────────────────

async def phase3_vision_on(base, p1, p2):
    res = {"phase": "P3-vision-on-adapt", "asset_id": p1.get("asset_id"),
           "doc_mid": p1.get("doc_mid")}
    from services import mca_vision
    asset_id = p1.get("asset_id")
    doc_mid = int(p1.get("doc_mid"))
    # restore original flags.vision_enabled exactly (snapshot: chat=true)
    res["restore"] = await base.restore_overrides(["flags.vision_enabled"],
                                                  "vision-on")
    await asyncio.sleep(2.0)
    await base.invalidate_caches()
    try:
        st = await mca_vision.resolve_effective_state(WORK_CHAT)
        res["vision_state_on"] = {
            "requested": st.requested, "effective": st.effective_enabled,
            "reason": st.reason, "capability": st.capability}
        if not st.effective_enabled \
                and st.reason == "capability_check_pending":
            out("P3", "capability probe (bounded)")
            try:
                await asyncio.wait_for(mca_vision.ensure_capability(
                    mca_vision.resolve_route(WORK_CHAT)), timeout=25)
            except Exception as exc:  # noqa: BLE001
                out("P3", "probe failed %s" % type(exc).__name__)
            st = await mca_vision.resolve_effective_state(WORK_CHAT)
            res["vision_state_on_after_probe"] = {
                "requested": st.requested, "effective": st.effective_enabled,
                "reason": st.reason, "capability": st.capability}
    except Exception as exc:  # noqa: BLE001
        res["vision_state_on"] = "failed:%s" % type(exc).__name__
    document = make_doc_obj(base, p1)
    turn1 = await base.run_turn(
        None, msg_id=doc_mid, caption="бот, что на картинке?",
        document=document, label="vision-on-1", timeout=260)
    res["turn1"] = base._strip_turn(turn1)
    res["turn1"]["vision_transport_calls"] = turn1.get(
        "vision_transport_calls")
    tool1 = next((t for t in turn1.get("tool_calls", [])
                  if t.get("tool") == "recognize_image"), None)
    res["tool1"] = tool1
    # poll the analysis row (prod worker completes the durable job)
    terminal = {"ready", "no_text", "failed", "unreadable", "unsupported"}
    rows = await _analyses_for_asset(base, asset_id)
    polls = []
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        rows = await _analyses_for_asset(base, asset_id)
        last = rows[-1] if rows else {}
        polls.append({"t": int(time.time()), "status": last.get("status"),
                      "revision": last.get("revision")})
        if str(last.get("status")) in terminal:
            break
        await asyncio.sleep(10)
    res["analysis_polls"] = polls[-12:]
    res["analyses"] = rows
    last_row = rows[-1] if rows else {}
    res["analysis_final"] = last_row
    # full analysis text (description + ocr) from the DB
    analysis_text = ""
    ocr_text = ""
    try:
        full = await base.sqlite_fetch(
            "SELECT id, status, revision, analyzer_model, visual_description, "
            "ocr_blocks, uncertainty, created_at, updated_at, error_reason "
            "FROM mca_media_analyses WHERE asset_id=? ORDER BY id DESC "
            "LIMIT 1", (asset_id,))
        if full:
            row = full[0]
            analysis_text = str(row.get("visual_description") or "")
            try:
                blocks = json.loads(row.get("ocr_blocks") or "[]")
                if isinstance(blocks, list):
                    ocr_text = "\n".join(
                        str(b.get("text") if isinstance(b, dict) else b)
                        for b in blocks)
            except Exception:
                ocr_text = str(row.get("ocr_blocks") or "")
            res["analysis_row"] = {
                "id": row.get("id"), "status": row.get("status"),
                "revision": row.get("revision"),
                "analyzer_model": row.get("analyzer_model"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "error_reason": row.get("error_reason"),
                "description_len": len(analysis_text),
                "description": analysis_text[:4000],
                "ocr_blocks_count": len(ocr_text.splitlines()) if ocr_text else 0,
                "ocr_text": ocr_text[:4000],
                "uncertainty": row.get("uncertainty"),
            }
    except Exception as exc:  # noqa: BLE001
        res["analysis_row_error"] = type(exc).__name__
    # delivery turn: if the tool returned ready, turn1 already delivered;
    # otherwise repeat (cache-hit ready) to obtain the bot's content answer.
    turn2 = None
    if str((tool1 or {}).get("status")) != "ready":
        turn2 = await base.run_turn(
            None, msg_id=doc_mid, caption="бот, что на картинке?",
            document=document, label="vision-on-2", timeout=260)
        res["turn2"] = base._strip_turn(turn2)
        tool2 = next((t for t in turn2.get("tool_calls", [])
                      if t.get("tool") == "recognize_image"), None)
        res["tool2"] = tool2
    gt = p1["fixture"]["gt_tokens"] or []
    haystacks = {
        "analysis_description": analysis_text,
        "analysis_ocr": ocr_text,
        "answer_turn1": str(turn1.get("answer") or ""),
        "answer_turn2": str((turn2 or {}).get("answer") or ""),
    }
    res["gt_check"] = {
        name: {"tokens_found": [t for t in gt if t.lower() in text.lower()],
               "found_n": sum(1 for t in gt if t.lower() in text.lower())}
        for name, text in haystacks.items()}
    res["gt_tokens"] = gt
    # vision_adapt events (prod process writes them; bounded wait)
    events = []
    ev_deadline = time.monotonic() + 45
    while time.monotonic() < ev_deadline:
        events = await base.sqlite_fetch(
            "SELECT ts, event_name, outcome, level, component, stage, "
            "reason_code, chat_id, error_json FROM mca_events "
            "WHERE event_name='vision_adapt' AND ts >= ? ORDER BY ts",
            (base.START_EPOCH,))
        if events:
            break
        await asyncio.sleep(5)
    res["vision_adapt_events"] = events
    res["vision_media_events"] = await base.sqlite_fetch(
        "SELECT ts, event_name, outcome, level, stage, reason_code, "
        "operation_id, model FROM mca_events WHERE event_name='vision_media' "
        "AND ts >= ? ORDER BY ts", (base.START_EPOCH,))
    res["adapt_used"] = any(
        str(e.get("stage")) == "optimize" for e in events)
    res["ok"] = (str(last_row.get("status")) == "ready"
                 and bool(res["adapt_used"]))
    base.save("p3-vision-on-adapt.json", res)
    out("P3", "done status=%s tool1=%s desc_len=%s adapt=%s gt_found=%s"
        % (last_row.get("status"), (tool1 or {}).get("status"),
           res.get("analysis_row", {}).get("description_len"),
           res["adapt_used"],
           res["gt_check"]["analysis_description"]["found_n"]))
    return res


# ─────────────────────────── P4 ─────────────────────────────────────────────

async def phase4_generation(base):
    res = {"phase": "P4-generation-postgen-quota"}
    from services import image_generation as ig
    st, budget = await base.CTX.api.req("GET", "/api/workers/budget")
    before = _budget_pick(budget)
    res["budget_before"] = before
    st, cfg0 = await base.CTX.api.req("GET", "/api/config", chat_id=WORK_CHAT)
    res["config_before"] = {"http": st, "items": base.pick_cfg(
        cfg0, ("flags.budgets_enabled", "limits.image_daily_limit"))}
    used = int(before.get("chat_used") or 0)
    limit = used + 1 if used > 0 else 1
    res["premise"] = {
        "chat_used_before": used, "chat_limit_set": limit,
        "note": ("сценарий 03.4 писался как «глобально 1»; на проде chat-day "
                 "уже used=%d (legacy-путь), поэтому «разрешена ровно одна "
                 "генерация» реализовано chat-scope лимитом used+1=%d; "
                 "глобальный слой не тронут" % (used, limit)),
    }
    res["cfg_write"] = await base.set_cfg([
        {"key": "flags.budgets_enabled", "value": True},
        {"key": "limits.image_daily_limit", "value": limit},
    ], "gen-premise")
    await asyncio.sleep(2.0)
    await base.invalidate_caches()
    mode = None
    for _ in range(5):
        mode = list(await ig.image_reserve_mode(WORK_CHAT))
        if mode[0] == "reserve":
            break
        await asyncio.sleep(4)
    res["reserve_mode_premise"] = mode
    await base.reset_image_freq_throttle()
    # exactly ONE live generation
    anchor = await base.latest_anchor()
    p_before = len(base.CTX.provider_calls)
    t1 = await base.run_turn(GEN_PROMPT_1, msg_id=anchor.message_id,
                             reply_to=anchor, label="gen-1", timeout=420)
    res["gen1"] = base._strip_turn(t1)
    res["gen1"]["provider_calls"] = len(base.CTX.provider_calls) - p_before
    res["gen1"]["vision_transport_calls"] = t1.get("vision_transport_calls")
    res["gen1"]["postgen"] = t1.get("postgen")
    res["gen1"]["image_blocks"] = t1.get("image_blocks")
    res["gen1"]["image_logs"] = [ln for ln in t1.get("logs", [])
                                 if "[image]" in ln or "[vision]" in ln]
    res["pg_reservations_after_gen1"] = await base.pg_fetch(
        "SELECT reservation_key, chat_id, source, status, error_code, "
        "delivery_failed, day, created_at, updated_at "
        "FROM image_reservation WHERE chat_id=$1 AND created_at >= "
        "to_timestamp($2) ORDER BY created_at", (WORK_CHAT, base.START_EPOCH))
    st, budget2 = await base.CTX.api.req("GET", "/api/workers/budget")
    res["budget_after_gen1"] = _budget_pick(budget2)
    # second attempt -> quota refusal (0 paid calls)
    anchor2 = t1.get("_last_msg") or anchor
    p_before2 = len(base.CTX.provider_calls)
    s_before2 = len(base.CTX.rec.sends)
    t2 = await base.run_turn(GEN_PROMPT_2, msg_id=anchor2.message_id,
                             reply_to=anchor2, label="gen-2-denied",
                             timeout=240)
    res["gen2"] = base._strip_turn(t2)
    res["gen2"]["provider_calls"] = len(base.CTX.provider_calls) - p_before2
    new_sends = base.CTX.rec.sends[s_before2:]
    res["gen2"]["new_sends"] = len(new_sends)
    res["gen2"]["new_photo_sends"] = sum(1 for s in new_sends
                                         if s.get("kind") == "photo")
    res["gen2"]["image_blocks"] = t2.get("image_blocks")
    block2 = ""
    if res["gen2"].get("image_blocks"):
        block2 = str((res["gen2"]["image_blocks"][0] or {}).get("block") or "")
    res["gen2_block"] = block2[:2500]
    res["gen2_block_quota_exhausted"] = 'reason="quota_exhausted"' in block2
    res["gen2_block_reset_note"] = "Суточная квота обновится" in block2
    res["pg_reservations_after_gen2"] = await base.pg_fetch(
        "SELECT reservation_key, source, status, error_code "
        "FROM image_reservation WHERE chat_id=$1 AND created_at >= "
        "to_timestamp($2) ORDER BY created_at", (WORK_CHAT, base.START_EPOCH))
    st, budget3 = await base.CTX.api.req("GET", "/api/workers/budget")
    res["budget_after_gen2"] = _budget_pick(budget3)
    answer2 = str(t2.get("answer") or "")
    res["gen2_answer"] = answer2
    res["gen2_answer_mentions_quota"] = "квот" in answer2.lower()
    # restore premise exactly
    res["restore"] = await base.restore_overrides(
        ["flags.budgets_enabled", "limits.image_daily_limit"], "gen-restore")
    await asyncio.sleep(2.0)
    await base.invalidate_caches()
    res["reserve_mode_after_restore"] = list(
        await ig.image_reserve_mode(WORK_CHAT))
    cfg_after = None
    expected = base.cfg_map(res["config_before"]["items"])
    for _ in range(3):
        st2, cfg2 = await base.CTX.api.req("GET", "/api/config",
                                           chat_id=WORK_CHAT)
        cfg_after = {"http": st2, "items": base.pick_cfg(
            cfg2, ("flags.budgets_enabled", "limits.image_daily_limit"))}
        if base.cfg_map(cfg_after["items"]) == expected:
            break
        await asyncio.sleep(10)
    res["config_after"] = cfg_after
    res["config_matches"] = base.cfg_map(cfg_after.get("items")) == expected
    b1, b3 = res["budget_before"], res["budget_after_gen2"]
    res["checks"] = {
        "gen1_provider_calls_1": res["gen1"]["provider_calls"] == 1,
        "gen1_photo_sent": any(s.get("kind") == "photo"
                               for s in res["gen1"].get("sends", [])),
        "gen1_chat_used_plus1": (int(b3.get("chat_used") or 0)
                                 - int(b1.get("chat_used") or 0)) == 1,
        "gen1_shared_plus1": (int(b3.get("shared_used") or 0)
                              - int(b1.get("shared_used") or 0)) == 1,
        "gen2_zero_provider_calls": res["gen2"]["provider_calls"] == 0,
        "gen2_zero_photo_sends": res["gen2"]["new_photo_sends"] == 0,
        "gen2_block_quota_exhausted": res["gen2_block_quota_exhausted"],
        "gen2_block_reset_note": res["gen2_block_reset_note"],
        "gen2_answer_mentions_quota": res["gen2_answer_mentions_quota"],
        "restore_mode": res["reserve_mode_after_restore"][0] == "legacy",
        "config_matches": res["config_matches"],
    }
    res["ok"] = all(res["checks"].values())
    base.save("p4-generation.json", res)
    out("P4", "done ok=%s checks=%s"
        % (res["ok"], json.dumps(res["checks"], ensure_ascii=False)))
    return res


# ─────────────────────────── P5 ─────────────────────────────────────────────

async def phase5_negatives(base):
    res = {"phase": "P5-negatives-0311"}
    st, cfg = await base.CTX.api.req("GET", "/api/config", chat_id=WORK_CHAT)
    watch = ("limits.image_daily_limit", "limits.image_freq_limit_mode",
             "limits.image_freq_limit_burst")
    before = base.cfg_map(base.pick_cfg(cfg, watch))
    res["before"] = before
    cases = []

    async def case(name, items, updated_at=None, expect=(409, 422)):
        import httpx
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=60.0) as c:
            r = await c.post("/api/config", headers={
                "X-Telegram-Init-Data": base.make_init_data(),
                "X-Chat-Id": str(WORK_CHAT)},
                json={"items": items, "updated_at": updated_at})
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:200]}
        st2, cfg2 = await base.CTX.api.req("GET", "/api/config",
                                           chat_id=WORK_CHAT)
        after = base.cfg_map(base.pick_cfg(cfg2, watch))
        cases.append({"name": name, "http": r.status_code, "body": body,
                      "expect": list(expect),
                      "pass": r.status_code in expect,
                      "no_write": after == before, "after": after})
        out("P5", "%s http=%s no_write=%s" % (name, r.status_code,
                                              after == before))

    await case("wrong_type_int", [
        {"key": "limits.image_daily_limit", "value": "abc"}], expect=(422,))
    await case("bad_select_option", [
        {"key": "limits.image_freq_limit_mode", "value": "bogus"}],
        expect=(422,))
    await case("stale_updated_at", [
        {"key": "limits.image_freq_limit_burst", "value": 7}],
        updated_at="1970-01-01T00:00:00Z", expect=(409,))
    res["cases"] = cases
    res["ok"] = all(c["pass"] and c["no_write"] for c in cases)
    base.save("p5-negatives.json", res)
    out("P5", "done ok=%s" % res["ok"])
    return res


# ─────────────────────────── P6 ───────────────────────────���─────────────────

async def phase6_showcase(base):
    res = {"phase": "P6-showcase-036"}
    st, cfg = await base.CTX.api.req("GET", "/api/config", chat_id=WORK_CHAT)
    items = cfg.get("items") if isinstance(cfg, dict) else []
    by_key = {it.get("key"): it for it in (items or [])}
    res["dead_keys"] = {
        k: {
            "present": k in by_key,
            "title": by_key.get(k, {}).get("title"),
            "group": by_key.get(k, {}).get("group"),
            "type": by_key.get(k, {}).get("type"),
            "honest_exact": HONEST_MARK in str(
                by_key.get(k, {}).get("description") or ""),
            "description": str(by_key.get(k, {}).get("description") or "")[:400],
        } for k in DEAD_KEYS}
    res["honest_exact_count"] = sum(
        1 for it in (items or [])
        if HONEST_MARK in str(it.get("description") or ""))
    res["honest_any_count"] = sum(
        1 for it in (items or [])
        if "Не влияет" in str(it.get("description") or ""))
    # served bytes vs disk (served==disk regression check)
    import httpx
    from config.settings import settings as _settings
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=60.0) as c:
        r_js = await c.get("/web/app.js")
        r_css = await c.get("/static/app.css")
        r_html = await c.get("/web/")
    disk_js = open(os.path.join(APP, "web", "app.js"), "rb").read()
    disk_css = open(os.path.join(APP, "web", "static", "app.css"),
                    "rb").read()
    disk_html = open(os.path.join(APP, "web", "index.html"), "rb").read()
    ver = str(getattr(_settings, "APP_VERSION", "?"))

    def sha12(b):
        return hashlib.sha256(b).hexdigest()[:12]

    res["served"] = {
        "appjs_status": r_js.status_code,
        "appjs_served_sha12": sha12(r_js.content),
        "appjs_disk_sha12": sha12(disk_js),
        "appjs_same": r_js.content == disk_js,
        "css_status": r_css.status_code,
        "css_same": r_css.content == disk_css,
        "html_status": r_html.status_code,
        "html_version_count": r_html.text.count(ver),
        "html_has_scope_label": "Обложки сводок здесь не учитываются"
                                in r_html.text,
        "html_eq_disk_substituted": (r_html.content
                                     == disk_html.replace(
                                         b"__APP_VERSION__", ver.encode())),
    }
    res["ok"] = (all(v.get("present") and v.get("honest_exact")
                     for v in res["dead_keys"].values())
                 and res["honest_exact_count"] == len(DEAD_KEYS)
                 and res["served"]["appjs_same"])
    base.save("p6-showcase-api.json", res)
    out("P6", "done ok=%s honest=%d served_js_same=%s"
        % (res["ok"], res["honest_exact_count"],
           res["served"]["appjs_same"]))
    return res


# ─────────────────────────── P7 ──────────────────────────────���──────────────

async def phase7_economics(base, results):
    res = {"phase": "P7-economics"}
    st, budget = await base.CTX.api.req("GET", "/api/workers/budget")
    res["budget_after"] = _budget_pick(budget)
    try:
        res["reservations_since_start"] = await base.pg_fetch(
            "SELECT reservation_key, chat_id, source, status, error_code, "
            "delivery_failed, day, created_at FROM image_reservation "
            "WHERE created_at >= to_timestamp($1) ORDER BY created_at",
            (base.START_EPOCH,))
        res["usage_since_start"] = await base.pg_fetch(
            "SELECT step, COUNT(*) n, COALESCE(SUM(cost_usd),0) cost, "
            "COALESCE(SUM(input_tokens+output_tokens),0) tokens "
            "FROM llm_usage_events WHERE ts >= to_timestamp($1) "
            "GROUP BY step ORDER BY n DESC", (base.START_EPOCH,))
        res["budget_rows_after"] = await base.pg_fetch(
            "SELECT day, scope, metric, used FROM worker_budget "
            "WHERE metric='image_calls' ORDER BY day DESC, scope LIMIT 12")
    except Exception as exc:  # noqa: BLE001
        res["pg_error"] = type(exc).__name__
    try:
        res["analyses_counts_after"] = await base.sqlite_fetch(
            "SELECT status, COUNT(*) n FROM mca_media_analyses "
            "GROUP BY status ORDER BY n DESC")
        res["analyses_running_after"] = await base.sqlite_fetch(
            "SELECT id, asset_id, status, revision, created_at, updated_at "
            "FROM mca_media_analyses WHERE status='running' ORDER BY id")
        res["jobs_since_start"] = await base.sqlite_fetch(
            "SELECT job_id, owner, kind, status, reason_code, attempt, "
            "created_at, updated_at FROM task_jobs WHERE created_at >= ? "
            "ORDER BY created_at", (base.START_EPOCH,))
        res["events_since_start"] = await base.sqlite_fetch(
            "SELECT ts, event_name, outcome, level, component, stage, "
            "reason_code, chat_id, error_json FROM mca_events "
            "WHERE ts >= ? ORDER BY ts", (base.START_EPOCH,))
        res["user_version_after"] = await base.sqlite_fetch(
            "PRAGMA user_version")
        res["mca_errors_since_start"] = await base.sqlite_fetch(
            "SELECT COUNT(*) n FROM mca_events WHERE ts >= ? AND level IN "
            "('ERROR','CRITICAL')", (base.START_EPOCH,))
    except Exception as exc:  # noqa: BLE001
        res["sqlite_error"] = type(exc).__name__
    # (d) orphan classification: the pre-wave running row + context
    try:
        running = (results.get("p0") or {}).get("analyses_running_before") or []
        detail = []
        for row in running:
            item = dict(row)
            item["asset"] = (await base.sqlite_fetch(
                "SELECT asset_id, message_key, chat_id, tg_message_id, "
                "asset_kind, mime, byte_size, width, height, media_group_id "
                "FROM mca_media_assets WHERE asset_id=?",
                (row.get("asset_id"),)) or [None])[0]
            item["jobs_for_asset"] = await base.sqlite_fetch(
                "SELECT job_id, status, reason_code, attempt, created_at, "
                "updated_at, heartbeat_at FROM task_jobs WHERE coalesce_key=? "
                "ORDER BY created_at", ("vision:asset:%s"
                                        % row.get("asset_id"),))
            item["later_ready_same_asset"] = await base.sqlite_fetch(
                "SELECT id, status, revision, created_at FROM "
                "mca_media_analyses WHERE asset_id=? AND id != ? ORDER BY id",
                (row.get("asset_id"), row.get("id")))
            item["events_for_asset"] = await base.sqlite_fetch(
                "SELECT ts, event_name, outcome, level, stage, reason_code "
                "FROM mca_events WHERE operation_id=? ORDER BY ts",
                (row.get("asset_id"),))
            detail.append(item)
        res["orphan_detail"] = detail
        res["orphan_classification"] = _classify_orphan(detail)
    except Exception as exc:  # noqa: BLE001
        res["orphan_error"] = "%s: %s" % (type(exc).__name__,
                                          str(exc)[:200])
    res["ok"] = True
    base.save("p7-economics.json", res)
    base.save("d-orphan.json", {
        "phase": "D-orphan",
        "running_before": (results.get("p0") or {}).get(
            "analyses_running_before"),
        "detail": res.get("orphan_detail"),
        "classification": res.get("orphan_classification"),
    })
    out("P7", "done orphan=%s"
        % json.dumps(res.get("orphan_classification"), ensure_ascii=False))
    return res


def _classify_orphan(detail):
    if not detail:
        return {"verdict": "no_running_rows"}
    item = detail[0]
    jobs = item.get("jobs_for_asset") or []
    interrupted = [j for j in jobs
                   if str(j.get("status")) == "interrupted"]
    if interrupted:
        return {
            "verdict": ("in-flight_at_restart_orphan: analysis row 'running' "
                        "left by the 2.58.95 restart; its vision.media job is "
                        "interrupted (worker_lost), no auto-requeue; the row "
                        "is inert (no active process holds it) and a future "
                        "tool/manual call would finish a new revision"),
            "job_interrupted": interrupted[0].get("job_id"),
            "job_reason": interrupted[0].get("reason_code"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
    return {"verdict": "unclassified", "jobs": jobs}


# ─────────────────────────── P8 ─────────────────────────────────────────────

async def phase8_cleanup_register(base, results):
    res = {"phase": "P8-cleanup-register"}
    mids: set = set()
    smart_rows: set = set()

    def add_sends(turn):
        for s in (turn or {}).get("sends", []) or []:
            mid = s.get("message_id")
            if mid:
                mids.add(int(mid))
            for m2 in s.get("message_ids") or []:
                if m2:
                    mids.add(int(m2))

    for key in ("p2", "p3", "p4"):
        phase = results.get(key) or {}
        for tkey in ("turn", "turn1", "turn2", "gen1", "gen2"):
            add_sends(phase.get(tkey))
    p1 = results.get("p1") or {}
    if p1.get("doc_mid"):
        mids.add(int(p1["doc_mid"]))
    debts = (results.get("p0") or {}).get("debts_scan") or []
    debt_mids = []
    for row in debts:
        mid = row.get("mid")
        uid = row.get("user_id")
        if mid and uid in (SYNTH_USER, BOT_ID):
            mids.add(int(mid))
            debt_mids.append(int(mid))
            smart_rows.add(int(mid))
    res["debt_mids_from_scan"] = debt_mids
    res["debts_scan"] = debts[:20]
    # also sweep synthetic smart_messages rows in the wave window
    lo = min(mids) - 40 if mids else 0
    hi = max(mids) + 15 if mids else 0
    try:
        extra = await base.sqlite_fetch(
            "SELECT tg_message_id mid FROM smart_messages WHERE chat_id=? "
            "AND user_id=? AND tg_message_id BETWEEN ? AND ?",
            (WORK_CHAT, SYNTH_USER, lo, hi))
        for row in extra:
            if row.get("mid"):
                mids.add(int(row["mid"]))
                smart_rows.add(int(row["mid"]))
        res["extra_synth_rows"] = extra
    except Exception as exc:  # noqa: BLE001
        res["extra_scan_error"] = type(exc).__name__
    payload = {"delete_mids": sorted(mids), "smart_rows": sorted(smart_rows),
               "window": {"lo": lo, "hi": hi}}
    with open(CLEANUP_OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    res["cleanup_spec"] = payload
    res["ok"] = bool(mids)
    base.save("p8-cleanup-register.json", res)
    out("P8", "done delete=%d smart=%d window=%s..%s"
        % (len(mids), len(smart_rows), lo, hi))
    return res


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC95 FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC95 RC=%d" % rc, flush=True)
    os._exit(rc)
