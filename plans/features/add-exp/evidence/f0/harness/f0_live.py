# -*- coding: utf-8 -*-
"""ADD-EXP Ф0 — ONE controlled live Direct turn + payload/manifest capture.

Runs ON prod via the proven ACCEPTANCE-91..94 bootstrap (/tmp/f0_base.py =
accept94_base.py). One synthetic user message ("бот, как настроение?") from
user 990002001 in the working chat; real Telegram delivery via the deployed
bot session; real providers; real DB.

Captures:
  * exact logical LLM payloads (generate/generate_chat spies): messages,
    full text of each call, sha12, profanity/instruction markers;
  * wire-level payloads (_post/_post_fallback spies on /chat/completions);
  * composer manifests for the turn (tool_phase / l2_writer) via
    prompt_composer.get_manifest -> manifest_for_events (expression layer
    trace: rendered/skip_reason/revision);
  * journal-style captured log lines (mca_event/prompt_layers/expression);
  * expression API view (chat + global) incl. runtime_wired;
  * composer gates (resolve_gates for the working chat);
  * the delivered answer text and sent mids.

Writes: /tmp/addexp_f0/evidence/f0-live.json + /tmp/addexp_f0/cleanup_spec.json
(the cleanup wave deletes the bot mids and removes synthetic rows).
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
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
SYNTH_MID = 990940201
EVID = "/tmp/addexp_f0/evidence"
SPEC = "/tmp/addexp_f0/cleanup_spec.json"

MAT_HARD = (
    r"\bху[йяеёию]\w*", r"\bхуйн\w*", r"\bзахуя\w*", r"\bнахуя\w*",
    r"\bпохуй\w*", r"\bохуе\w*", r"\bнихуя\b", r"\bпизд\w*", r"\bбля\w*",
    r"\bеб(а|ё|е|у|и|л|н|с|ш)\w*", r"\bёб\w*", r"\bзаеб\w*", r"\bнаеб\w*",
    r"\bвыеб\w*", r"\bотъеб\w*", r"\bуеб\w*", r"\bпроеб\w*", r"\bдолбоёб\w*",
    r"\bсука\b|\bсуки\b|\bсуке\b|\bсуку\b|\bсукой\b|\bсучк\w*",
    r"\bмудак\w*|\bмудил\w*", r"\bпидор\w*|\bпидар\w*|\bпедик\w*",
    r"\bгондон\w*|\bгандон\w*", r"\bмандав\w*", r"\bшлюх\w*", r"\bдроч\w*",
)
INSTR_MARKERS = ("Expression_Settings", "Мат и грубость", "profanity",
                 "нецензур", "обсцен", "матерн", "без мата")


def out(tag, text):
    print("F0LIVE %s | %s" % (tag, text), flush=True)


def sha12(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def scan_text(text):
    text = str(text or "")
    res = {"hard": [], "soft": [], "instr": []}
    seen = set()
    for pat in MAT_HARD:
        for m in re.finditer(pat, text, re.IGNORECASE):
            key = (m.start(), m.end())
            if key in seen:
                continue
            seen.add(key)
            s, e = max(0, m.start() - 40), min(len(text), m.end() + 40)
            res["hard"].append({"m": m.group(0),
                                "ctx": " ".join(text[s:e].split())})
    low = text.lower()
    for marker in INSTR_MARKERS:
        if marker.lower() in low:
            res["instr"].append(marker)
    return res


def load_base():
    spec = importlib.util.spec_from_file_location("f0_base",
                                                  "/tmp/f0_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CapAll(logging.Handler):
    """Capture journal-style lines of interest (mca_event / expression)."""

    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        if not msg:
            return
        if any(k in msg for k in ("mca_event", "prompt_layers", "expression",
                                  "Expression", "[direct] triggered",
                                  "l2_writer", "composer")):
            self.lines.append(msg[:2000])


CAP = CapAll()
logging.getLogger().addHandler(CAP)
logging.getLogger().setLevel(logging.INFO)


async def main() -> int:
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    out("NOW_UTC", now)
    base = load_base()
    await base.bootstrap()
    out("BOOT", "ok; bot_id=%s" % getattr(base.CTX.me, "id", None))

    from services import prompt_composer as pc
    llm = base.CTX.llm
    evidence: dict = {"now_utc": now, "chat_id": WORK_CHAT,
                      "synth_mid": SYNTH_MID, "turn_text": "бот, как настроение?"}

    # ── gates ──────────────────────────────────────────────────────────────
    try:
        gates = await pc.resolve_gates(WORK_CHAT)
        evidence["gates_chat"] = {k: getattr(gates, k) for k in (
            "unified_composer_enabled", "character_core_enabled",
            "speech_style_policy_enabled", "humor_library_enabled",
            "humor_craft_enabled", "persona_enabled",
            "character_layers_enabled", "smart_verbalizer_modes_enabled",
            "response_plan_enabled")}
        evidence["composer_on"] = pc.composer_enabled_now(gates)
    except Exception as exc:  # noqa: BLE001
        evidence["gates_chat"] = {"error": type(exc).__name__}

    # ── expression API view (read-only) ───────────────────────────────────
    try:
        api = base.Api()
        st, body = await api.req("GET", "/api/speech/expression",
                                 chat_id=WORK_CHAT)
        evidence["expression_api_chat"] = {"http": st, "body": body}
        st2, body2 = await api.req("GET", "/api/speech/expression")
        evidence["expression_api_global"] = {"http": st2, "body": body2}
        await api.close()
    except Exception as exc:  # noqa: BLE001
        evidence["expression_api_chat"] = {"error": type(exc).__name__}

    # ── LLM spies (logical + wire level) ──────────────────────────────────
    calls: list[dict] = []
    wire: list[dict] = []

    def _msgs(messages):
        out_msgs = []
        for m in messages or []:
            if isinstance(m, dict):
                out_msgs.append({"role": str(m.get("role")),
                                 "content": str(m.get("content"))})
        return out_msgs

    orig_generate = llm.generate

    async def generate_spy(messages, **kw):
        msgs = _msgs(messages)
        rec = {"seq": len(calls) + 1, "via": "generate",
               "module": kw.get("module"), "step": kw.get("step"),
               "correlation_id": kw.get("correlation_id"),
               "temperature": kw.get("temperature"),
               "n_messages": len(msgs),
               "roles": [m["role"] for m in msgs],
               "messages": msgs}
        calls.append(rec)
        return await orig_generate(messages, **kw)

    orig_generate_chat = llm.generate_chat

    async def generate_chat_spy(messages, **kw):
        msgs = _msgs(messages)
        rec = {"seq": len(calls) + 1, "via": "generate_chat",
               "module": kw.get("module"), "step": kw.get("step"),
               "correlation_id": kw.get("correlation_id"),
               "temperature": kw.get("temperature"),
               "n_messages": len(msgs),
               "roles": [m["role"] for m in msgs],
               "messages": msgs}
        calls.append(rec)
        return await orig_generate_chat(messages, **kw)

    orig_post = llm._post

    async def post_spy(path, payload, **kw):
        if str(path) == "/chat/completions" and isinstance(payload, dict):
            msgs = _msgs(payload.get("messages"))
            wire.append({"seq": len(wire) + 1, "via": "_post",
                         "path": str(path), "model": payload.get("model"),
                         "payload_chars": len(json.dumps(payload,
                                                         ensure_ascii=False)),
                         "payload_sha12": sha12(json.dumps(payload,
                                                           sort_keys=True,
                                                           ensure_ascii=False)),
                         "n_messages": len(msgs),
                         "messages_sha12": [sha12(m["content"])
                                            for m in msgs]})
        return await orig_post(path, payload, **kw)

    orig_post_fb = llm._post_fallback

    async def post_fb_spy(payload, path="/chat/completions", model=None,
                          **kw):
        if str(path) == "/chat/completions" and isinstance(payload, dict):
            wire.append({"seq": len(wire) + 1, "via": "_post_fallback",
                         "path": str(path),
                         "model": model or payload.get("model"),
                         "payload_sha12": sha12(json.dumps(payload,
                                                           sort_keys=True,
                                                           ensure_ascii=False))})
        return await orig_post_fb(payload, path=path, model=model, **kw)

    llm.generate = generate_spy
    llm.generate_chat = generate_chat_spy
    llm._post = post_spy
    llm._post_fallback = post_fb_spy

    # ── ONE controlled direct turn ────────────────────────────────────────
    sends_before = len(base.CTX.rec.sends)
    logs_before = len(CAP.lines)
    res = await base.run_turn("бот, как настроение?", msg_id=SYNTH_MID,
                              label="f0_turn", timeout=420)
    corr = res.get("correlation_id")
    out("TURN", "status=%s corr=%s elapsed=%ss answer_len=%s" % (
        res.get("status"), corr, res.get("elapsed_s"),
        len(res.get("answer_head") or "")))

    # full text of every send of this turn (from the raw _msg objects)
    sends_full = []
    for s in base.CTX.rec.sends[sends_before:]:
        msg = s.get("_msg")
        text = ""
        if msg is not None:
            text = str(getattr(msg, "text", None)
                       or getattr(msg, "caption", None) or "")
        sends_full.append({"kind": s.get("kind"),
                           "message_id": s.get("message_id"),
                           "text": text, "text_len": len(text),
                           "scan": scan_text(text)})
    evidence["sends_full"] = sends_full
    evidence["turn"] = {
        "status": res.get("status"), "error": res.get("error"),
        "correlation_id": corr, "elapsed_s": res.get("elapsed_s"),
        "answer_head": res.get("answer_head"),
        "plan_meta": res.get("plan_meta"),
        "usage": res.get("usage"),
        "logs": res.get("logs"),
    }

    # ── manifests of the turn ─────────────────────────────────────────────
    manifests = {}
    for writer in ("tool_phase", "l2_writer", "l1_planner", "synthesizer",
                   None):
        try:
            m = pc.get_manifest(WORK_CHAT, run_id=corr, writer=writer)
        except Exception as exc:  # noqa: BLE001
            manifests[str(writer)] = {"error": type(exc).__name__}
            continue
        if m is None:
            manifests[str(writer)] = None
            continue
        rep = pc.manifest_for_events(m)
        # full expression trace (with skip reason) + rendered layer list
        rep["expression_trace"] = [
            t for t in rep["layers"] if t.get("layer") == "expression"]
        rep["system_sha12"] = sha12(m.system)
        rep["system_chars"] = len(m.system or "")
        manifests[str(writer)] = rep
    evidence["manifests"] = manifests

    # ── payload analysis ──────────────────────────────────────────────────
    all_system_parts: list[str] = []
    for rec in calls:
        sys_txt = next((m["content"] for m in rec["messages"]
                        if m["role"] == "system"), "")
        usr_txt = next((m["content"] for m in rec["messages"]
                        if m["role"] == "user"), "")
        all_system_parts.append(sys_txt)
        rec["system_chars"] = len(sys_txt)
        rec["system_sha12"] = sha12(sys_txt)
        rec["user_chars"] = len(usr_txt)
        rec["user_sha12"] = sha12(usr_txt)
        rec["markers"] = scan_text(sys_txt + "\n" + usr_txt)
        if str(rec.get("step")) == "l2_writer":
            rec["system_text"] = sys_txt[:120000]
            rec["user_text"] = usr_txt[:20000]
        else:
            rec.pop("messages", None)
    evidence["llm_calls"] = calls
    evidence["wire_calls"] = wire
    evidence["captured_logs"] = CAP.lines[logs_before:][:120]

    expr_layers = []
    for w, rep in manifests.items():
        if isinstance(rep, dict):
            expr_layers.append({"writer": w,
                                "expression_trace": rep.get("expression_trace")})
    evidence["expression_layers"] = expr_layers
    all_system = "\n".join(all_system_parts)
    evidence["payload_marker_totals"] = {
        "Expression_Settings": all_system.count("Expression_Settings"),
        "Мат и грубость": all_system.count("Мат и грубость"),
        "profanity": all_system.lower().count("profanity"),
    }
    # hypothesis check: any profanity instruction at all in the final payload?
    final_l2 = [c for c in calls if str(c.get("step")) == "l2_writer"]
    last_sys = (final_l2[-1].get("system_text") if final_l2 else "")
    evidence["final_payload_profanity"] = scan_text(last_sys)

    # ── flush in-process events to shared SQLite (as acceptance did) ─────
    try:
        from services import mca_events
        flushed = await mca_events.flush_events(base.CTX.db)
        evidence["mca_events_flushed"] = flushed
    except Exception as exc:  # noqa: BLE001
        evidence["mca_events_flushed"] = "failed:%s" % type(exc).__name__

    os.makedirs(EVID, exist_ok=True)
    with open(os.path.join(EVID, "f0-live.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(evidence, ensure_ascii=False, indent=1,
                            default=str))

    # ── cleanup spec ──────────────────────────────────────────────────────
    mids = sorted({int(s["message_id"]) for s in sends_full
                   if s.get("message_id")})
    window_lo = min([SYNTH_MID] + mids) - 5
    window_hi = max([SYNTH_MID] + mids) + 5
    spec = {"delete_mids": mids, "smart_rows": [SYNTH_MID],
            "window": {"lo": window_lo, "hi": window_hi},
            "turn_text": "бот, как настроение?", "corr": corr}
    with open(SPEC, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(spec, ensure_ascii=False, indent=1))
    out("CLEANUP_SPEC", json.dumps(spec, ensure_ascii=False)[:400])

    out("PAYLOAD", "llm_calls=%d wire=%d l2_calls=%d" % (
        len(calls), len(wire), len(final_l2)))
    out("MARKERS", json.dumps(evidence["payload_marker_totals"],
                              ensure_ascii=False))
    out("EXPR_TRACE", json.dumps(expr_layers, ensure_ascii=False)[:600])

    try:
        await base.CTX.llm.close()
    except Exception:
        pass
    try:
        await base.CTX.bot.session.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("F0LIVE FATAL | %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        traceback.print_exc()
    print("F0LIVE RC=%d" % rc, flush=True)
    os._exit(rc)
