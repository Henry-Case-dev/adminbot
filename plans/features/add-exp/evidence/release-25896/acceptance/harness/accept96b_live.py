# -*- coding: utf-8 -*-
"""ACCEPTANCE-96b — follow-up: корректная изоляция, маршруты/«вживую» в frequent,
цитата с матом, точное восстановление, идентификация остатка «1 фото 95a».

Контекст основного прогона (ACCEPTANCE-96): выражение было в wire-payload
(<Expression_Settings> + строка режима + точный текст слоя) во всех L2-вызовах,
но модель не дала мата ни в occasional, ни в frequent (model_ignored_instruction),
а мой порядок «добора» occasional переключил чат A обратно в occasional ДО
изоляции/маршрутов. Этот прогон закрывает пробелы: A=frequent одновременно с
B=off, authorial/initiative/live-check в frequent, цитата с матом в off,
PG-доказательство точного восстановления, + безопасная идентификация
фото-остатка (Bot API editMessageCaption: бот может редактировать только свои
сообщения; чужое сообщение не трогается).

Runs ON prod через /tmp/accept96_base.py + helper-модуль /tmp/accept96_live.py.
Выход: /tmp/accept96b/evidence/*.json + /tmp/accept96b/cleanup_spec.json.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time

APP = "/var/www/admin_bot"
try:
    os.chdir(APP)
except Exception:
    pass
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHAT_A = -1002661910336
CHAT_B_DEFAULT = -1004482340693
SYNTH_USER = 990002001
EVID = "/tmp/accept96b/evidence"
SPEC = "/tmp/accept96b/cleanup_spec.json"
MID_BASE = 990960500
RESIDUAL_MIDS = (1166467, 1166469)


def out(tag, text):
    print("ACC96B %s | %s" % (tag, text), flush=True)


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def identify_message(base, chat_id, mid, marker):
    """Bot API editMessageCaption: бот правит только СВОИ сообщения.

    Успех → сообщение бота (удаляем); ошибка → чужое (не трогаем).
    """
    res = {"mid": int(mid)}
    try:
        await base.CTX.bot.edit_message_caption(
            chat_id=chat_id, message_id=int(mid), caption=marker)
        res["edit_caption"] = "ok"
        res["owner"] = "bot"
    except Exception as exc:  # noqa: BLE001
        res["edit_caption"] = "%s: %s" % (type(exc).__name__,
                                          str(exc)[:200])
        res["owner"] = "not_bot"
    return res


async def main() -> int:
    os.makedirs(EVID, exist_ok=True)
    base = load_mod("accept96_base", "/tmp/accept96_base.py")
    base.EVID = EVID
    acc96 = load_mod("acc96_live", "/tmp/accept96_live.py")
    acc96.STORE_SYSTEM_TEXT = True
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    wave_start = int(time.time())
    await base.bootstrap()
    acc96.install_spies(base)
    api = base.Api()
    base.CTX.api = api
    chat_b = CHAT_B_DEFAULT
    summary: dict = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.gmtime()),
                     "wave_start_epoch": wave_start,
                     "chat_a": CHAT_A, "chat_b": chat_b}

    # ── P0b: восстановленное состояние + PG-доказательство ────────────────
    p0: dict = {}
    p0["view_a"] = await acc96.api_view(api, CHAT_A)
    p0["view_b"] = await acc96.api_view(api, chat_b)
    p0["view_global"] = await acc96.api_view(api, None)
    p0["resolve_a"] = await acc96.resolve_expected(CHAT_A)
    try:
        p0["pg_overrides"] = await base.pg_fetch(
            "SELECT chat_id, "
            "jsonb_object_keys(chat_params->'overrides') AS key "
            "FROM chat_profiles WHERE chat_id IN ($1, $2) "
            "ORDER BY chat_id, key", CHAT_A, chat_b)
        p0["pg_expr_override"] = await base.pg_fetch(
            "SELECT chat_id, (chat_params->'overrides'->'character.expression')"
            "::text AS doc FROM chat_profiles WHERE chat_id IN ($1, $2)",
            CHAT_A, chat_b)
        p0["pg_global_expression"] = await base.pg_fetch(
            "SELECT key, value::text AS value, updated_at::text AS updated_at "
            "FROM bot_settings WHERE key='character.expression'")
    except Exception as exc:  # noqa: BLE001
        p0["pg_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    base.save("p0b-state.json", p0)
    out("P0b", "A chat_present=%s inheritance=%s | B inheritance=%s | "
        "override_keys=%s"
        % ((p0["view_a"]["body"] or {}).get("chat_present"),
           (p0["view_a"]["body"] or {}).get("inheritance"),
           (p0["view_b"]["body"] or {}).get("inheritance"),
           len(p0.get("pg_overrides") or [])))

    # ── остаток «1 фото 95a»: безопасная идентификация ───────────────────
    residual: dict = {"candidates": list(RESIDUAL_MIDS), "probes": [],
                      "deleted": []}
    marker = "🧪 ACC96 identification probe"
    if p0["view_a"]["body"].get("chat_present"):
        out("RESIDUAL", "WARN: chat A все ещё имеет override — пропуск")
    for mid in RESIDUAL_MIDS:
        probe = await identify_message(base, CHAT_A, mid, marker)
        residual["probes"].append(probe)
        out("RESIDUAL", "mid=%s owner=%s (%s)"
            % (mid, probe["owner"], probe["edit_caption"]))
    for probe in residual["probes"]:
        if probe.get("owner") != "bot":
            continue
        try:
            await base.CTX.bot.delete_message(chat_id=CHAT_A,
                                              message_id=int(probe["mid"]))
            probe["deleted"] = "ok"
            residual["deleted"].append(int(probe["mid"]))
        except Exception as exc:  # noqa: BLE001
            probe["deleted"] = "%s: %s" % (type(exc).__name__,
                                           str(exc)[:160])
    base.save("residual-95a.json", residual)

    # ── frequent: подтверждение + изоляция B=off одновременно ────────────
    EXPECT = acc96.EXPECT
    switch_a = await acc96.set_chat_mode(base, api, CHAT_A, "frequent")
    EXPECT["mode"] = "frequent"
    EXPECT["text"] = str((switch_a.get("resolved") or {}).get("text") or "")
    out("WAVE", "A=frequent eff=%s src=%s rev=%s"
        % (((switch_a.get("reread") or {}).get("body") or {}).get(
            "effective", {}).get("profanity", {}).get("value"),
           ((switch_a.get("reread") or {}).get("body") or {}).get(
            "effective", {}).get("profanity", {}).get("source"),
           (switch_a.get("resolved") or {}).get("revision")))
    anchor_a = await base.CTX.rec.send_message(
        CHAT_A, "🧪 Приёмка 2.58.96 ADD-EXP · follow-up (frequent; сообщения "
                "удаляются)")
    turns: list = []
    mid_a = int(getattr(anchor_a, "message_id", 0) or MID_BASE)
    last_a = anchor_a
    t, last_new, _ = await acc96.do_turn(
        base, CHAT_A, "бот, ну ты и выдал вчера с докладом, это было эпично",
        label="b-freq-01-banter", context="banter", mode="frequent",
        anchor_msg=last_a, mid=mid_a)
    turns.append(t)
    if last_new is not None:
        last_a, mid_a = last_new, int(getattr(last_new, "message_id", 0))
    out("TURN", "A banter status=%s own_mat=%d | %s"
        % (t["status"], t["answer_scan"]["own_count"],
           t["answer"][:90].replace("\n", " ")))

    # B: off (изоляция)
    switch_b = await acc96.set_chat_mode(base, api, chat_b, "off")
    view_a_iso = await acc96.api_view(api, CHAT_A)
    EXPECT["mode"] = "off"
    EXPECT["text"] = str((switch_b.get("resolved") or {}).get("text") or "")
    anchor_b = await base.CTX.rec.send_message(
        chat_b, "🧪 Приёмка 2.58.96 ADD-EXP · follow-up изоляция (чат B: off; "
                "сообщения удаляются)")
    b_turns = []
    mid_b = int(getattr(anchor_b, "message_id", 0) or MID_BASE)
    last_b = anchor_b
    for i, (context, phrase) in enumerate((
            ("banter", "бот, ну ты и выдал вчера с докладом, это было эпично"),
            ("short", "бот, ты в деле завтра?"))):
        tb, last_new_b, _ = await acc96.do_turn(
            base, chat_b, phrase, label="b-iso-B-%02d-%s" % (i + 1, context),
            context=context, mode="off", anchor_msg=last_b, mid=mid_b)
        b_turns.append(tb)
        if last_new_b is not None:
            last_b, mid_b = last_new_b, int(getattr(last_new_b,
                                                    "message_id", 0))
        out("ISO", "B %s status=%s own_mat=%d | %s"
            % (context, tb["status"], tb["answer_scan"]["own_count"],
               tb["answer"][:90].replace("\n", " ")))
    # A: тот же короткий вопрос — одновременно frequent
    EXPECT["mode"] = "frequent"
    EXPECT["text"] = str((switch_a.get("resolved") or {}).get("text") or "")
    ta, last_new_a, _ = await acc96.do_turn(
        base, CHAT_A, "бот, ты в деле завтра?", label="b-freq-02-short",
        context="short", mode="frequent", anchor_msg=last_a, mid=mid_a)
    turns.append(ta)
    if last_new_a is not None:
        last_a = last_new_a
    out("TURN", "A short status=%s own_mat=%d | %s"
        % (ta["status"], ta["answer_scan"]["own_count"],
           ta["answer"][:90].replace("\n", " ")))
    iso = {"chat_b": chat_b, "switch_a": switch_a, "switch_b": switch_b,
           "view_a_while_b_off": view_a_iso, "turns_a": turns,
           "turns_b": b_turns, "anchor_a_mid": getattr(anchor_a,
                                                       "message_id", None),
           "anchor_b_mid": getattr(anchor_b, "message_id", None)}
    base.save("isolation.json", iso)

    # ── маршруты frequent: authorial + initiative + «Проверить вживую» ───
    routes: dict = {}
    try:
        from services import mca_authorial_speech as mas
        system, manifest = await mas.authorial_system(
            chat_id=CHAT_A, writer="nostalgia_writer", genre="nostalgia",
            legacy_canon="Ты пишешь тёплый ностальгический текст о прошлом.",
            channel="plain")
        layers = []
        try:
            import services.prompt_composer as pc
            layers = [t for t in pc.manifest_for_events(manifest)["layers"]
                      if t.get("layer") in ("expression", "few_shot")]
        except Exception:
            pass
        routes["authorial"] = {
            "writer": "nostalgia_writer", "system_chars": len(system or ""),
            "has_marker": "<Expression_Settings>" in str(system or ""),
            "mode_line": next((m for m, mk in acc96.MODE_LINE_MARKERS.items()
                               if mk in str(system or "")), ""),
            "layers": layers}
        out("ROUTE", "authorial marker=%s mode=%s"
            % (routes["authorial"]["has_marker"],
               routes["authorial"]["mode_line"]))
    except Exception as exc:  # noqa: BLE001
        routes["authorial"] = {"error": "%s: %s" % (type(exc).__name__,
                                                    str(exc)[:160])}
    try:
        from services import usage_events as _ue
        corr = _ue.new_correlation_id()
        before = len(acc96.CALLS)
        text = await base.CTX.svc.generate_initiative_reply(
            CHAT_A, {"kind": "unanswered_question", "origin": "accept96b",
                     "goal": "в чате недавно обсуждали интернет и роутер — "
                             "прояви инициативу и предложи проверку"},
            correlation_id=corr)
        routes["initiative"] = {
            "correlation_id": corr, "reply": str(text or "")[:1500],
            "reply_scan": acc96.scan_own(text),
            "llm_calls": acc96.CALLS[before:]}
        init_l2 = [c for c in (routes["initiative"]["llm_calls"] or [])
                   if str(c.get("step")) == "l2_writer"]
        routes["initiative"]["l2_marker"] = [
            {"has_marker": c.get("has_marker"),
             "mode_line": c.get("mode_line"),
             "expected_text_present": c.get("expected_text_present")}
            for c in init_l2]
        out("ROUTE", "initiative len=%s own_mat=%s l2=%s"
            % (len(str(text or "")), routes["initiative"]["reply_scan"]
               ["own_count"],
               json.dumps(routes["initiative"]["l2_marker"],
                          ensure_ascii=False)))
    except Exception as exc:  # noqa: BLE001
        routes["initiative"] = {"error": "%s: %s" % (type(exc).__name__,
                                                     str(exc)[:160])}
    try:
        st, body = await api.req(
            "POST", "/api/speech/expression/live-check", chat_id=CHAT_A,
            json_body={"message": "ну ты и выдал вчера с докладом, это было "
                                  "эпично"})
        routes["live_check"] = {"http": st, "body": body}
        out("LIVE_CHECK", "http=%s mode=%s diag=%s marker=%s prof=%s"
            % (st, (body or {}).get("mode"), (body or {}).get("diag_class"),
               (body or {}).get("expression_marker"),
               (body or {}).get("profanity_roots")))
    except Exception as exc:  # noqa: BLE001
        routes["live_check"] = {"error": "%s: %s" % (type(exc).__name__,
                                                     str(exc)[:160])}
    # диагностический контроль (не входит в матрицу): прямая просьба «матерись»
    # в frequent — отличает «модель не применяет частотную инструкцию» от
    # «модель/провайдер вообще не выдают мат».
    EXPECT["mode"] = "frequent"
    EXPECT["text"] = str((switch_a.get("resolved") or {}).get("text") or "")
    tdiag_f, last_new_df, _ = await acc96.do_turn(
        base, CHAT_A,
        "бот, скажи что-нибудь матерное про понедельник, это для проверки",
        label="b-freq-direct-request", context="diag_direct", mode="frequent",
        anchor_msg=last_a, mid=int(getattr(last_a, "message_id", 0)))
    if last_new_df is not None:
        last_a = last_new_df
    routes["diag_direct_frequent"] = {
        "phrase": "бот, скажи что-нибудь матерное про понедельник, это для "
                  "проверки",
        "status": tdiag_f["status"],
        "answer": (tdiag_f.get("answer") or "")[:600],
        "own_mat": tdiag_f["answer_scan"]["own_count"]}
    out("DIAG_DIRECT", "frequent own_mat=%d | %s"
        % (tdiag_f["answer_scan"]["own_count"],
           (tdiag_f.get("answer") or "")[:120].replace("\n", " ")))
    base.save("routes.json", routes)

    # ── цитата с матом при off (цитата задана в самой реплике) ───────────
    switch_off = await acc96.set_chat_mode(base, api, CHAT_A, "off")
    EXPECT["mode"] = "off"
    EXPECT["text"] = str((switch_off.get("resolved") or {}).get("text") or "")
    quote_anchor = await base.CTX.rec.send_message(
        CHAT_A, "🧪 Приёмка 2.58.96 ADD-EXP · follow-up цитата (off; "
                "сообщения удаляются)")
    mid_q = int(getattr(quote_anchor, "message_id", 0) or MID_BASE)
    tq, _last_q, _ = await acc96.do_turn(
        base, CHAT_A,
        "бот, вот цитата из статьи: «да пошёл он нахуй со своими правками, "
        "я устал ждать». Передай её дословно, слово в слово.",
        label="b-off-quote", context="genre_quote", mode="off",
        anchor_msg=quote_anchor, mid=mid_q)
    quote = {"turn": tq, "switch": switch_off,
             "anchor_mid": getattr(quote_anchor, "message_id", None),
             "quote_preserved": "нахуй" in (tq.get("answer") or ""),
             "own_mat": tq["answer_scan"]["own_count"]}
    base.save("quote-off.json", quote)
    out("QUOTE", "status=%s preserved=%s own_mat=%d | %s"
        % (tq["status"], quote["quote_preserved"], quote["own_mat"],
           (tq.get("answer") or "")[:160].replace("\n", " ")))
    # диагностический контроль P3×P4: off + прямая просьба «матерись»
    last_q = _last_q if _last_q is not None else quote_anchor
    toff, _last_off, _ = await acc96.do_turn(
        base, CHAT_A,
        "бот, выругайся матерным словом, чтобы я понял, что ты умеешь",
        label="b-off-direct-request", context="diag_direct", mode="off",
        anchor_msg=last_q, mid=int(getattr(last_q, "message_id", 0)))
    quote["diag_direct_off"] = {
        "phrase": "бот, выругайся матерным словом, чтобы я понял, что ты "
                  "умеешь",
        "status": toff["status"],
        "answer": (toff.get("answer") or "")[:600],
        "own_mat": toff["answer_scan"]["own_count"]}
    base.save("quote-off.json", quote)
    out("DIAG_DIRECT", "off own_mat=%d | %s"
        % (toff["answer_scan"]["own_count"],
           (toff.get("answer") or "")[:120].replace("\n", " ")))

    # ── классификация частоты (§6) ────────────────────────────────────────
    diag: dict = {}
    try:
        import services.mca_expression as expr
        l2_freq = [c for t in turns for c in (t.get("llm_calls") or [])
                   if str(c.get("step")) == "l2_writer"]
        freq_answers = [t.get("answer") for t in turns]
        raw_joined = "\n".join(str(a or "") for a in freq_answers)
        # 7 разговорных проб основной волны + 2 follow-up = N=9 подряд без мата
        marker_present = bool(l2_freq) and all(
            bool(c.get("has_marker")) for c in l2_freq)
        diag["frequent"] = {
            "probes": 9,
            "probes_note": "7 main-wave conversational + 2 follow-up",
            "mat_roots": expr.count_profanity(raw_joined),
            "marker_present_l2": marker_present,
            "class": expr.classify_expression_response(
                raw_joined, "frequent", genre="accept96_live_set",
                probes=9, marker_present=marker_present),
        }
        if diag["frequent"]["class"] == "model_ignored_instruction":
            emitted = expr.emit_expression_diag(
                "model_ignored_instruction", chat_id=CHAT_A,
                stage="accept96_live_set",
                detail="frequent_no_mat_n9", mode="frequent")
            diag["emitted_event"] = bool(emitted)
        out("DIAG", json.dumps(diag, ensure_ascii=False)[:300])
    except Exception as exc:  # noqa: BLE001
        diag["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    base.save("diag.json", diag)

    # ── restore A/B + финальные срезы ────────────────────────────────────
    restore: dict = {"chat_a": await acc96.reset_chat_mode(api, CHAT_A),
                     "chat_b": await acc96.reset_chat_mode(api, chat_b)}
    restore["view_global_after"] = await acc96.api_view(api, None)
    restore["view_a_after"] = await acc96.api_view(api, CHAT_A)
    try:
        restore["pg_overrides_after"] = await base.pg_fetch(
            "SELECT chat_id, jsonb_object_keys(chat_params->'overrides') "
            "AS key FROM chat_profiles WHERE chat_id IN ($1, $2) "
            "ORDER BY chat_id, key", CHAT_A, chat_b)
        restore["pg_expr_override_after"] = await base.pg_fetch(
            "SELECT chat_id, (chat_params->'overrides'->'character.expression')"
            "::text AS doc FROM chat_profiles WHERE chat_id IN ($1, $2)",
            CHAT_A, chat_b)
        restore["pg_global_expression_after"] = await base.pg_fetch(
            "SELECT key, value::text AS value, updated_at::text AS updated_at "
            "FROM bot_settings WHERE key='character.expression'")
    except Exception as exc:  # noqa: BLE001
        restore["pg_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    base.save("restore.json", restore)
    out("RESTORE", "A http=%s inher=%s | B http=%s inher=%s"
        % (restore["chat_a"]["http"],
           (restore["view_a_after"]["body"] or {}).get("inheritance"),
           restore["chat_b"]["http"],
           (restore["chat_b"]["reread"]["body"] or {}).get("inheritance")))

    # ── сводка follow-up ─────────────────────────────────────────────────
    try:
        from services import mca_events
        await mca_events.flush_events(base.CTX.db)
    except Exception:
        pass
    l2 = [c for t in turns for c in (t.get("llm_calls") or [])
          if str(c.get("step")) == "l2_writer"]
    b_l2 = [c for t in b_turns for c in (t.get("llm_calls") or [])
            if str(c.get("step")) == "l2_writer"]
    summary.update({
        "p0b": {k: v for k, v in p0.items() if k != "view_global"},
        "isolation": {
            "a_effective": (((iso["view_a_while_b_off"].get("body") or {})
                             .get("effective") or {}).get("profanity")),
            "b_effective": ((((iso["switch_b"].get("reread") or {}).get(
                "body") or {}).get("effective") or {}).get("profanity")),
            "a_wire_mode_lines": [c.get("mode_line") for c in l2],
            "a_wire_markers": [c.get("has_marker") for c in l2],
            "b_wire_mode_lines": [c.get("mode_line") for c in b_l2],
            "b_wire_markers": [c.get("has_marker") for c in b_l2],
            "a_turns": len(turns), "b_turns": len(b_turns),
            "a_own_mat": sum(t["answer_scan"]["own_count"] for t in turns),
            "b_own_mat": sum(t["answer_scan"]["own_count"] for t in b_turns),
            "verdict": ("PASS" if (
                (((iso["view_a_while_b_off"].get("body") or {}).get(
                    "effective") or {}).get("profanity") or {}).get("value")
                == "frequent"
                and all(c.get("mode_line") == "frequent" for c in l2)
                and all(c.get("mode_line") == "off" for c in b_l2)
                and all(c.get("has_marker") for c in l2 + b_l2)
                and sum(t["answer_scan"]["own_count"] for t in b_turns) == 0)
                else "FAIL"),
        },
        "routes": routes, "quote_off": {
            "quote_preserved": quote["quote_preserved"],
            "own_mat": quote["own_mat"],
            "answer": (tq.get("answer") or "")[:600]},
        "diag_direct": {
            "frequent": routes.get("diag_direct_frequent"),
            "off": quote.get("diag_direct_off")},
        "diag": diag,
        "restore": {
            "a_http": restore["chat_a"]["http"],
            "b_http": restore["chat_b"]["http"],
            "a_inheritance": (restore["view_a_after"]["body"] or {}).get(
                "inheritance"),
            "a_chat_present": (restore["view_a_after"]["body"] or {}).get(
                "chat_present"),
            "b_inheritance": (restore["chat_b"]["reread"]["body"] or {}).get(
                "inheritance"),
            "pg_overrides_after": restore.get("pg_overrides_after"),
            "pg_expr_override_after": restore.get("pg_expr_override_after"),
            "pg_global_before": p0.get("pg_global_expression"),
            "pg_global_after": restore.get("pg_global_expression_after"),
        },
        "full_l2_system_sample": {
            "label": l2[0].get("label") if l2 else None,
            "system_chars": l2[0].get("system_chars") if l2 else None,
            "system_sha12": l2[0].get("system_sha12") if l2 else None,
            "system_text": (l2[0].get("system_text") if l2 else ""),
        },
        "turns_used": len(turns) + len(b_turns) + 3,
    })
    base.save("summary.json", summary)

    # ── cleanup spec (все сообщения этого прогона) ───────────────────────
    mids_a = []
    mids_b = []
    extra_turns = [tdiag_f, toff]
    for src in ([anchor_a, quote_anchor] + list(turns) + extra_turns):
        if hasattr(src, "message_id"):
            mids_a.append(int(src.message_id))
            continue
        for s in (src.get("sends") or []):
            if s.get("message_id"):
                mids_a.append(int(s["message_id"]))
    for src in [anchor_b] + list(b_turns):
        if hasattr(src, "message_id"):
            mids_b.append(int(src.message_id))
            continue
        for s in (src.get("sends") or []):
            if s.get("message_id"):
                mids_b.append(int(s["message_id"]))
    spec = {
        "chat_a": CHAT_A, "chat_b": chat_b,
        "delete_mids": {str(CHAT_A): sorted(set(mids_a)),
                        str(chat_b): sorted(set(mids_b))},
        "residual_95a": {"candidates": list(RESIDUAL_MIDS),
                         "delete": residual.get("deleted") or [],
                         "identification": residual.get("probes")},
        "synth_user": SYNTH_USER,
        "notes": ("follow-up: anchor'ы и ответы волн A/B; остаток 95a — "
                  "только сообщения, подтверждённые как собственные (edit "
                  "probe) и удалённые этим прогоном"),
    }
    with open(SPEC, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(spec, ensure_ascii=False, indent=1))
    out("SPEC", "A=%d B=%d residual_deleted=%s"
        % (len(mids_a), len(mids_b), residual.get("deleted")))
    out("SUMMARY", json.dumps({
        "turns_used": summary["turns_used"],
        "isolation": summary["isolation"]["verdict"],
        "quote_preserved": quote["quote_preserved"],
        "diag_class": diag.get("frequent", {}).get("class"),
    }, ensure_ascii=False))
    await base._close()
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC96B FATAL | %s: %s" % (type(exc).__name__,
                                         str(exc)[:400]), flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC96B RC=%d" % rc, flush=True)
    os._exit(rc)
