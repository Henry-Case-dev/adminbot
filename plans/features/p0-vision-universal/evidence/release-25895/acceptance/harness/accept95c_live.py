# -*- coding: utf-8 -*-
"""ACCEPTANCE-95c — third (c) attempt with a leaner heavy PNG + cleanup
register for ALL waves (95a/95b/95c).

Context: wave 95b verified the adaptive path live (payload_over -> stage A ->
stage B -> exactly 1 provider call) but the free vision model returned
non-JSON for the dense-text 4000px screenshot (analysis failed/parse_error).
This wave uses a leaner >700KB fixture (3 large tokens) so a compliant JSON
answer is plausible; same single pipeline, no config premises, no generation.

Also writes /tmp/accept95_cleanup_mids.json covering:
  * wave 95a: doc 1166463, OFF answer 1166464, gen1 answer (recovered via
    bot_reply_parents from the probe), + anchors discovered via parents;
  * wave 95b: doc 1166482, answers 1166485/1166487/1166491/1166495,
    gen1 photo 1166489 + anchors via parents;
  * wave 95c: all mids of this wave;
  * safety: mids whose smart_messages row belongs to a real user are EXCLUDED.
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
FIXTURE = "/tmp/accept95/fixture95c.png"
FIXTURE_META = "/tmp/accept95/fixture95c-ground-truth.json"
PROBE = "/tmp/accept95/evidence/probe95c.json"
CLEANUP_OUT = "/tmp/accept95_cleanup_mids.json"

#: known mids from waves 95a/95b evidence
W95A_DOC_MID = 1166463
W95A_OFF_ANSWER_MID = 1166464
W95B_MIDS = [1166482, 1166485, 1166487, 1166489, 1166491, 1166495]
#: answers whose parent (= the turn anchor) must be recovered from the probe
W95B_ANSWERS = [1166485, 1166487]
W95A_GEN1_PARENT = 1166464


def load_base():
    spec = importlib.util.spec_from_file_location("accept95_base",
                                                  "/tmp/accept95_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def out(tag, text):
    print("ACC95C %s | %s" % (tag, text), flush=True)


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
    results = {}
    try:
        results["p3c"] = await phase3c_vision_adapt(base)
    except Exception as exc:  # noqa: BLE001
        import traceback
        out("FATAL", "%s: %s" % (type(exc).__name__, str(exc)[:300]))
        traceback.print_exc()
        results["fatal"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
    try:
        from services import mca_events
        flushed = await mca_events.flush_events(base.CTX.db)
        out("FLUSH", "mca_events flushed=%s" % flushed)
    except Exception as exc:  # noqa: BLE001
        out("FLUSH", "failed: %s" % type(exc).__name__)
    try:
        results["p8c"] = await phase8c_register(base, results)
    except Exception as exc:  # noqa: BLE001
        out("FATAL", "register failed: %s: %s" % (type(exc).__name__,
                                                  str(exc)[:200]))
        results["p8c"] = {"ok": False, "error": type(exc).__name__}
    base.save("summary95c.json", {
        "start_epoch": base.START_EPOCH,
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "phases": {k: (v.get("ok") if isinstance(v, dict) else None)
                   for k, v in results.items()},
        "sends": base._sanitize_sends(base.CTX.rec.sends),
    })
    out("DONE", "evidence=%s" % EVID)
    await base.close_all()
    return 0


async def phase3c_vision_adapt(base):
    res = {"phase": "P3c-vision-adapt-lean"}
    from aiogram.types import FSInputFile
    from services import mca_vision
    meta = json.load(open(FIXTURE_META, encoding="utf-8"))
    raw = open(FIXTURE, "rb").read()
    res["fixture"] = {"bytes": len(raw), "sha256": meta.get("sha256"),
                      "sha12": meta.get("sha256_12"),
                      "width": meta.get("width"), "height": meta.get("height"),
                      "payload_chars_est": meta.get("payload_chars_est"),
                      "gt_tokens": meta.get("gt_tokens")}
    caption = ("🧪 Приёмка 2.58.95c · фикстура vision-adapt (лёгкий текст, "
               ">700 КБ)")
    msg = await base.CTX.rec.send_document(
        WORK_CHAT, FSInputFile(FIXTURE), caption=caption)
    doc = getattr(msg, "document", None)
    doc_mid = int(getattr(msg, "message_id"))
    doc_kw = {
        "file_id": str(getattr(doc, "file_id", "") or ""),
        "file_unique_id": str(getattr(doc, "file_unique_id", "") or ""),
        "mime_type": str(getattr(doc, "mime_type", "") or "image/png"),
        "file_size": getattr(doc, "file_size", None),
        "file_name": str(getattr(doc, "file_name", "") or "fixture95c.png"),
    }
    res["sent"] = {"message_id": doc_mid,
                   "file_id_present": bool(doc_kw["file_id"]),
                   "file_size": doc_kw["file_size"],
                   "mime_type": doc_kw["mime_type"],
                   "caption_head": caption[:120]}
    synthetic = base.make_message(
        msg_id=doc_mid, caption=caption,
        document=base.make_document(doc_kw["file_id"],
                                    doc_kw["file_unique_id"],
                                    doc_kw["mime_type"], doc_kw["file_size"],
                                    doc_kw["file_name"]))
    ids = await mca_vision.register_intake_assets(base.CTX.db, synthetic)
    res["asset_id"] = ids[0] if ids else None
    asset_id = res["asset_id"]
    try:
        image = await mca_vision.download_telegram_file(base.CTX.bot,
                                                        doc_kw["file_id"])
        res["download_precheck"] = {
            "bytes": len(image.data), "mime": image.mime,
            "width": image.width, "height": image.height,
            "sha_equal_fixture": (hashlib.sha256(image.data).hexdigest()
                                  == meta.get("sha256")),
        }
    except Exception as exc:  # noqa: BLE001
        res["download_precheck"] = "failed: %s" % type(exc).__name__
    reply_doc = base.make_message(msg_id=doc_mid, caption=None,
                                  document=synthetic.document)
    anchor1 = await base.CTX.rec.send_message(
        WORK_CHAT, "🧪 Приёмка 2.58.95c · вопрос по фикстуре (turn 1)")
    res["anchor1_mid"] = anchor1.message_id
    t1 = await base.run_turn(None, msg_id=anchor1.message_id,
                             caption="бот, что на картинке?",
                             reply_to=reply_doc, label="vision-onc-1",
                             timeout=260)
    res["turn1"] = base._strip_turn(t1)
    res["tool1"] = next((t for t in t1.get("tool_calls", [])
                         if t.get("tool") == "recognize_image"), None)
    terminal = {"ready", "no_text", "failed", "unreadable", "unsupported"}
    rows = await base.sqlite_fetch(
        "SELECT id, status, revision, analyzer_model, created_at, updated_at, "
        "error_reason FROM mca_media_analyses WHERE asset_id=? ORDER BY id",
        (asset_id,))
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        rows = await base.sqlite_fetch(
            "SELECT id, status, revision, analyzer_model, created_at, "
            "updated_at, error_reason FROM mca_media_analyses WHERE "
            "asset_id=? ORDER BY id", (asset_id,))
        last = rows[-1] if rows else {}
        if str(last.get("status")) in terminal:
            break
        await asyncio.sleep(10)
    res["analyses"] = rows
    last_row = rows[-1] if rows else {}
    res["analysis_final"] = last_row
    analysis_text = ""
    ocr_text = ""
    try:
        full = await base.sqlite_fetch(
            "SELECT id, status, revision, analyzer_model, visual_description, "
            "ocr_blocks, uncertainty, created_at, updated_at, error_reason "
            "FROM mca_media_analyses WHERE asset_id=? ORDER BY id DESC LIMIT 1",
            (asset_id,))
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
                "ocr_blocks_count": (len(ocr_text.splitlines())
                                     if ocr_text else 0),
                "ocr_text": ocr_text[:4000],
                "uncertainty": row.get("uncertainty"),
            }
    except Exception as exc:  # noqa: BLE001
        res["analysis_row_error"] = type(exc).__name__
    turn2 = None
    if str((res.get("tool1") or {}).get("status")) != "ready":
        anchor2 = await base.CTX.rec.send_message(
            WORK_CHAT, "🧪 Приёмка 2.58.95c · вопрос по фикстуре (turn 2)")
        res["anchor2_mid"] = anchor2.message_id
        turn2 = await base.run_turn(None, msg_id=anchor2.message_id,
                                    caption="бот, что на картинке?",
                                    reply_to=reply_doc, label="vision-onc-2",
                                    timeout=260)
        res["turn2"] = base._strip_turn(turn2)
        res["tool2"] = next((t for t in turn2.get("tool_calls", [])
                             if t.get("tool") == "recognize_image"), None)
    gt = meta.get("gt_tokens") or []
    haystacks = {
        "analysis_description": analysis_text,
        "analysis_ocr": ocr_text,
        "answer_turn1": str(t1.get("answer") or ""),
        "answer_turn2": str((turn2 or {}).get("answer") or ""),
    }
    res["gt_check"] = {
        name: {"tokens_found": [t for t in gt if t.lower() in text.lower()],
               "found_n": sum(1 for t in gt if t.lower() in text.lower())}
        for name, text in haystacks.items()}
    res["gt_tokens"] = gt
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
    res["adapt_used"] = any(str(e.get("stage")) == "optimize" for e in events)
    res["ok"] = (str(last_row.get("status")) == "ready"
                 and bool(res["adapt_used"])
                 and res["gt_check"]["analysis_description"]["found_n"] > 0)
    base.save("p3c-vision-adapt.json", res)
    out("P3c", "done status=%s tool1=%s adapt=%s desc_len=%s gt=%s ok=%s"
        % (last_row.get("status"), (res.get("tool1") or {}).get("status"),
           res["adapt_used"],
           res.get("analysis_row", {}).get("description_len"),
           res["gt_check"]["analysis_description"]["found_n"], res["ok"]))
    return res


async def phase8c_register(base, results):
    res = {"phase": "P8c-cleanup-register-all-waves"}
    mids: set = set()
    # wave 95a/95b known mids
    mids.add(W95A_DOC_MID)
    mids.add(W95A_OFF_ANSWER_MID)
    mids.update(W95B_MIDS)
    # wave 95c mids (this process)
    p3c = results.get("p3c") or {}
    if p3c.get("sent", {}).get("message_id"):
        mids.add(int(p3c["sent"]["message_id"]))
    for k in ("anchor1_mid", "anchor2_mid"):
        if p3c.get(k):
            mids.add(int(p3c[k]))
    for tkey in ("turn1", "turn2"):
        for s in ((p3c.get(tkey) or {}).get("sends") or []):
            if s.get("message_id"):
                mids.add(int(s["message_id"]))
    # recover anchors / the 95a gen1 answer via the probe's parents map
    parents = {}
    bot_replies = []
    try:
        probe = json.load(open(PROBE, encoding="utf-8"))
        parents = {int(r["mid"]): r.get("parent")
                   for r in (probe.get("bot_reply_parents_window") or [])}
        bot_replies = probe.get("bot_replies_window") or []
    except Exception as exc:  # noqa: BLE001
        res["probe_error"] = type(exc).__name__
    recovered = []
    for mid in W95B_ANSWERS:
        parent = parents.get(mid)
        if parent:
            mids.add(int(parent))
            recovered.append({"answer": mid, "anchor": int(parent)})
    gen1_answer = None
    for r in bot_replies:
        mid = int(r["mid"])
        if mid > W95A_GEN1_PARENT and parents.get(mid) == W95A_GEN1_PARENT:
            gen1_answer = mid
            break
    if gen1_answer:
        mids.add(int(gen1_answer))
        recovered.append({"answer": gen1_answer,
                          "anchor": W95A_GEN1_PARENT, "wave": "95a-gen1"})
    res["recovered"] = recovered
    # safety: exclude mids whose smart_messages row belongs to a real user
    excluded = []
    try:
        sm = await base.sqlite_fetch(
            "SELECT tg_message_id mid, user_id FROM smart_messages WHERE "
            "chat_id=? AND tg_message_id IN (%s)"
            % ",".join("?" * len(mids)), (WORK_CHAT, *sorted(mids)))
        for row in sm:
            if row.get("user_id") not in (SYNTH_USER, BOT_ID):
                excluded.append({"mid": row.get("mid"),
                                 "user_id": row.get("user_id"),
                                 "reason": "real user message in "
                                           "smart_messages"})
    except Exception as exc:  # noqa: BLE001
        res["safety_error"] = type(exc).__name__
    for e in excluded:
        mids.discard(int(e["mid"]))
    res["excluded_real_users"] = excluded
    payload = {"delete_mids": sorted(mids),
               "smart_rows": [],
               "window": {"lo": min(mids) - 10 if mids else 0,
                          "hi": max(mids) + 10 if mids else 0},
               "notes": ("95a gen1 PHOTO mid is not recoverable (harness "
                         "crashed before saving P4); it stays as a disclosed "
                         "residual (uncaptioned bot photo ~13:54:17Z)")}
    with open(CLEANUP_OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    res["cleanup_spec"] = payload
    res["ok"] = bool(mids)
    base.save("p8c-register.json", res)
    out("P8c", "done delete=%d excluded=%d recovered=%s"
        % (len(mids), len(excluded),
           json.dumps(recovered, ensure_ascii=False)))
    return res


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC95C FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC95C RC=%d" % rc, flush=True)
    os._exit(rc)
