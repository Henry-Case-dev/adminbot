#!/usr/bin/env python3
"""P0 FULL production-context probe: real L1 planner + real L2 writer, old/new.

Runs ON the server. Read-only: PG via a read-only pool, SQLite via mode=ro.
No Telegram, no deploy, no INSERT/UPDATE/DELETE. Secrets are never printed.

Per invocation it builds the FULL production speech system (Core, identity,
lessons, few-shot/samples, speech, expression, extent/plan block, L2 summary,
RAG facts, window) with the VARIANT'S OWN code and renderers.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import types

CHAT_ID = -1002661910336
TG_A, TG_B = 1175252, 1175255
TS_A, TS_B = 1792873281, 1792873478
AUTHOR = "Ринтаро"
AUTHOR_ID = 134812796


def sha12(text) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def env(path, key):
    for line in open(path, encoding="utf-8", errors="replace"):
        s = line.strip()
        if s.startswith(key + "="):
            return s.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def jload(raw, default=None):
    try:
        return json.loads(raw)
    except Exception:
        return default


class ROCache:
    """Read-only stand-in for the app's config cache (hot_config + chat params)."""

    pg_available = True

    def __init__(self, settings, chat_params):
        self._settings = settings
        self._chat_params = chat_params
        self._journal = []

    def get(self, key, default=None):
        return self._settings.get(key, default)

    async def get_chat_params(self, chat_id):
        self._journal.append(chat_id)
        return {"overrides": self._chat_params or {}}

    async def set(self, *a, **k):
        raise RuntimeError("read-only probe: cache.set forbidden")


async def load_pg(root):
    import asyncpg

    dsn = ""
    for key in ("DATABASE_URL", "POSTGRES_DSN", "PG_DSN"):
        dsn = env(os.path.join(root, ".env"), key)
        if dsn:
            break
    if not dsn:
        raise RuntimeError("no PG DSN in .env")
    conn = await asyncpg.connect(dsn, timeout=20)
    await conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    ro = await conn.fetchval("SHOW transaction_read_only")
    out = {"read_only": ro, "settings": {}, "chat_params": {}, "personas": None,
           "traits": [], "profile": None, "identity": None}
    rows = await conn.fetch("SELECT key, value FROM bot_settings")
    for r in rows:
        out["settings"][r["key"]] = jload(r["value"], r["value"])
    try:
        rows = await conn.fetch(
            "SELECT chat_params FROM chat_profiles WHERE chat_id = $1", CHAT_ID)
        if rows and rows[0]["chat_params"]:
            out["chat_params"] = jload(rows[0]["chat_params"], {}) or {}
    except Exception as exc:                              # noqa: BLE001
        out["chat_params_error"] = str(exc)[:160]
    for table, key in (("personas", "personas"), ("persona_traits", "traits")):
        try:
            if table == "personas":
                rows = await conn.fetch(
                    "SELECT * FROM personas WHERE chat_id = $1 OR is_global "
                    "ORDER BY is_global LIMIT 5", CHAT_ID)
            else:
                rows = await conn.fetch(
                    "SELECT * FROM persona_traits WHERE chat_id = $1 "
                    "ORDER BY id DESC LIMIT 50", CHAT_ID)
            out[key] = [dict(r) for r in rows]
        except Exception as exc:                          # noqa: BLE001
            out[key + "_error"] = str(exc)[:160]
    for table in ("mca_self_identity",):
        try:
            rows = await conn.fetch("SELECT * FROM %s LIMIT 5" % table)
            out["identity"] = [dict(r) for r in rows]
        except Exception as exc:                          # noqa: BLE001
            out["identity_error"] = str(exc)[:160]
    await conn.close()
    return out


def load_sqlite(root):
    db = os.path.join(root, "local_database.db")
    conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    out = {}
    try:
        cur = conn.cursor()
        window = [dict(r) for r in cur.execute(
            "SELECT * FROM smart_messages WHERE chat_id = ? "
            "AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (CHAT_ID, TS_A - 5400, TS_A)).fetchall()]
        out["window_A"] = window
        out["window_B"] = [m for m in window if int(m["timestamp"]) < TS_B]
        for name, sql in (
            ("graph_facts", "SELECT * FROM graph_facts WHERE chat_id = ? "
                            "ORDER BY id DESC LIMIT 40"),
            ("lore_stories", "SELECT * FROM lore_stories WHERE chat_id = ? "
                             "ORDER BY id DESC LIMIT 6"),
            ("mca_lessons", "SELECT * FROM mca_lessons LIMIT 40"),
        ):
            try:
                out[name] = [dict(r) for r in cur.execute(sql, (CHAT_ID,)).fetchall()]
            except Exception as exc:                      # noqa: BLE001
                try:
                    out[name] = [dict(r) for r in cur.execute(
                        sql.replace(" WHERE chat_id = ?", ""),
                        () if "chat_id = ?" not in sql else ()).fetchall()]
                except Exception as exc2:                 # noqa: BLE001
                    out[name + "_error"] = "%s / %s" % (str(exc)[:120], str(exc2)[:120])
        for name, sql in (
            ("chat_running_summary", "SELECT * FROM chat_running_summary "
                                     "WHERE chat_id = ? LIMIT 3"),
            ("summary_runs", "SELECT * FROM summary_runs WHERE chat_id = ? "
                             "ORDER BY rowid DESC LIMIT 4"),
            ("summary_levels", "SELECT * FROM chat_summary_levels "
                               "WHERE chat_id = ? LIMIT 3"),
            ("selfecho_fact", "SELECT * FROM graph_facts WHERE id = 21255"),
            ("selfecho_lore", "SELECT * FROM lore_stories WHERE id = 4"),
        ):
            try:
                out[name] = [dict(r) for r in cur.execute(sql, (CHAT_ID,)).fetchall()]
            except Exception as exc:                      # noqa: BLE001
                try:
                    out[name] = [dict(r) for r in cur.execute(sql, ()).fetchall()]
                except Exception as exc2:                 # noqa: BLE001
                    out[name + "_error"] = "%s / %s" % (str(exc)[:120], str(exc2)[:120])
    finally:
        conn.close()
    return out


def build_window_text(rows, limit=50):
    lines = []
    for m in rows[-limit:]:
        txt = (m.get("text") or "").strip()
        if txt:
            lines.append("%s: %s" % (m.get("author_name") or "?", txt))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--case", required=True, choices=("A", "B"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--skip-l2", action="store_true")
    ap.add_argument("--temperature", type=float, default=0.7)
    args = ap.parse_args()

    os.chdir(args.root)
    sys.path.insert(0, args.root)
    result = {"label": args.label, "root": args.root, "case": args.case,
              "chat_id": CHAT_ID, "stage_errors": {}}
    try:
        asyncio.run(_run(args, result))
    except Exception as exc:                              # noqa: BLE001
        import traceback
        result["fatal"] = "%s: %s" % (type(exc).__name__, str(exc)[:400])
        result["traceback"] = traceback.format_exc()[-2500:]
    json.dump(result, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: result.get(k) for k in
                      ("label", "case", "fatal", "system_chars", "l1_plan",
                       "l2_runs", "stage_errors")}, ensure_ascii=False)[:1500])
    return 0


async def _run(args, result):
    from services import hot_config as hot
    pg = await load_pg(args.root)
    sq = load_sqlite(args.root)
    result["sources"] = {
        "pg_read_only": pg["read_only"],
        "settings_keys": len(pg["settings"]),
        "chat_param_keys": len(pg["chat_params"]),
        "window_messages": len(sq.get("window_A", [])),
        "graph_facts_rows": len(sq.get("graph_facts", [])),
        "lore_stories_rows": len(sq.get("lore_stories", [])),
        "mca_lessons_rows": len(sq.get("mca_lessons", [])),
    }
    cache = ROCache(pg["settings"], pg["chat_params"])
    hot.set_config_cache(cache)

    from services import bot_persona
    if pg.get("personas"):
        pass
    try:
        import asyncpg
        for k in ("DATABASE_URL", "POSTGRES_DSN"):
            dsn = env(os.path.join(args.root, ".env"), k)
            if dsn:
                break
        pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=2,
            server_settings={"default_transaction_read_only": "on"})
        bot_persona.set_persona_pool(pool)
        result["persona_pool"] = "injected"
    except Exception as exc:                              # noqa: BLE001
        result["stage_errors"]["persona_pool"] = str(exc)[:200]

    from services import prompt_composer as pcomp
    from services import prompt_style_blocks as psb
    from services import response_extent as extent
    from services import direct_l1 as l1mod
    from services.prompt_style_blocks import resolve_prompt
    from services.prompt_registry import resolve_chat_speech

    target_ts = TS_A if args.case == "A" else TS_B
    tg_id = TG_A if args.case == "A" else TG_B
    win = [m for m in sq.get("window_%s" % args.case, [])
           if str(m.get("tg_message_id")) != str(tg_id)]
    question = ""
    for m in sq.get("window_A", []):
        if str(m.get("tg_message_id")) == str(tg_id):
            question = m.get("text") or ""
    result["question"] = question

    # ── real route of the traced run (trace): A serious/research/normal,
    #    B deep_research/research/detailed/report
    if args.case == "A":
        response_mode, plan = "serious", extent.ResponsePlan(
            task_kind="research", extent="normal", structure="answer",
            delivery_hint="plain")
    else:
        response_mode, plan = "deep_research", extent.ResponsePlan(
            task_kind="research", extent="detailed", structure="report",
            delivery_hint="plain")

    # ── real identity / persona (PG pool + real renderers)
    character_block = ""
    try:
        from services import mca_gates
        if mca_gates.character_layers_enabled():
            ctx = await bot_persona.resolve_character_context(CHAT_ID)
            persona, traits = ctx.persona, list(ctx.traits)
        else:
            persona = await bot_persona.resolve_bot_persona(CHAT_ID)
            traits = await bot_persona.get_traits(50)
        persona_block = bot_persona.build_persona_prompt_block(
            persona, traits, enabled=True)
        character_block = persona_block or ""
        if mca_gates.character_layers_enabled():
            rules = bot_persona.build_character_rules_block()
            if rules:
                character_block = (character_block + "\n\n" + rules).strip()
    except Exception as exc:                              # noqa: BLE001
        result["stage_errors"]["identity"] = "%s: %s" % (type(exc).__name__, str(exc)[:220])
    result["identity_block_chars"] = len(character_block)

    # ── real L2 summary (SQLite)
    summary_text = ""
    rows = sq.get("chat_running_summary") or []
    if rows:
        row = rows[0]
        summary_text = str(row.get("summary") or row.get("text") or "")
    result["l2_summary"] = {
        "chars": len(summary_text),
        "sha12": sha12(summary_text) if summary_text else "",
        "runs": [{k: (str(v)[:60] if v is not None else None)
                  for k, v in (r or {}).items()
                  if k in ("status", "created_at", "updated_at", "summary_len",
                           "source_type", "stage")}
                 for r in (sq.get("summary_runs") or [])][:4],
        "levels": len(sq.get("summary_levels") or []),
    }

    # ── real RAG facts (SQLite graph_facts) via real renderer
    rag_block = ""
    try:
        from services.summary_memory import build_rag_context
        facts = sq.get("graph_facts") or []
        kw = [w for w in re.split(r"\W+", question.lower()) if len(w) > 4][:4]
        picked = [f for f in facts
                  if any(k and k in str(f.get("fact", "")).lower() for k in kw)][:6]
        if picked:
            try:
                rag_block = build_rag_context(picked)
            except Exception:
                rag_block = "\n".join(
                    "- %s" % str(f.get("fact") or "") for f in picked)
                result["rag_render"] = "fallback_lines" 
    except Exception as exc:                              # noqa: BLE001
        result["stage_errors"]["rag"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    result["rag_block_chars"] = len(rag_block)

    # ── real lessons block (SQLite mca_lessons) via real renderer
    lessons_block = ""
    try:
        from services import mca_experience as mca_exp
        lessons = sq.get("mca_lessons") or []
        if lessons:
            lessons_block = mca_exp.render_lessons_block(lessons)
    except Exception as exc:                              # noqa: BLE001
        result["stage_errors"]["lessons"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    result["lessons_block_chars"] = len(lessons_block)

    # ── real base prompt + gates
    base_prompt, base_source = await resolve_chat_speech(
        "prompts.direct_chat_verbalizer_system_prompt", "", chat_id=CHAT_ID)
    if not base_prompt:
        base_prompt, base_source = await resolve_chat_speech(
            "prompts.direct_chat_system_prompt", "", chat_id=CHAT_ID)
    result["base_prompt"] = {"chars": len(base_prompt or ""),
                             "sha12": sha12(base_prompt),
                             "source": base_source}
    gates = pcomp.gates_from_config()
    result["gates"] = {k: getattr(gates, k, None) for k in
                       ("unified_composer_enabled", "character_core_enabled",
                        "persona_enabled", "character_layers_enabled",
                        "smart_verbalizer_modes_enabled",
                        "expression_examples_enabled", "humor_library_enabled",
                        "humor_craft_enabled")}

    # ── system via the REAL service builder (_compose_speech_system)
    from services.direct_chat_service import DirectChatService
    extent_block = extent.render_extent_block(plan)
    system = ""
    try:
        system, manifest = await DirectChatService._compose_speech_system(
            None, chat_id=CHAT_ID, writer="l2_writer", run_id="p0-probe",
            base_prompt=base_prompt, base_key=(
                "prompts.direct_chat_verbalizer_system_prompt"),
            base_default="", gates=gates, channel="plain", html_safe=True,
            base_source=(base_source or ""), include_mode_block=True,
            response_mode=response_mode, response_plan=plan,
            extent_block=extent_block, identity_text=character_block,
            identity_source="chat",
            identity_skipped=("" if getattr(gates, "persona_enabled", True)
                              else "persona_disabled"),
            lessons_block=lessons_block,
            lessons_skip=("" if lessons_block else "lessons_absent"),
            speech_block="", speech_skip="speech_absent",
            context_text=question, user_parts=())
        result["layers"] = [{"layer": t.layer, "block_id": t.block_id,
                             "chars": t.chars, "rendered": bool(t.rendered),
                             "skip_reason": t.skip_reason}
                            for t in manifest.layers]
        result["core"] = {
            "chars": len(getattr(manifest.versions, "core", "") or ""),
            "detail": getattr(manifest.versions, "core_detail", None),
        }
    except Exception as exc:                              # noqa: BLE001
        result["stage_errors"]["compose_system"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])

    n_core = system.count("<Personality_Core>")
    result["system"] = {
        "chars": len(system), "sha12": sha12(system),
        "core_blocks": n_core,
        "analysis_directive": system.count("ANALYSIS_DIRECTIVE"),
        "analysis_writer": system.count("ANALYSIS_WRITER"),
        "persona_marker": ("<Character_Rules>" in system),
        "mode_block": ("MODE_DEEP_RESEARCH_BLOCK" in system),
    }
    result["system_chars"] = len(system)

    # ── user part (same order as the service builds it)
    parts = []
    if rag_block:
        parts.append(rag_block)
    if summary_text:
        parts.append("<Chat_Summary>\n" + summary_text + "\n</Chat_Summary>")
    user_blocks = "\n\n".join(parts)
    result["user_blocks_chars"] = len(user_blocks)

    # ── real L1 planner
    llm = _make_llm(args.root, result)
    l1_system = resolve_prompt("prompts.direct_l1_planner_system_prompt", None)
    if not l1_system:
        from services.direct_chat_service import DIRECT_L1_PLANNER_SYSTEM_PROMPT
        l1_system = DIRECT_L1_PLANNER_SYSTEM_PROMPT
    try:
        l1_context = l1mod.build_l1_context(
            query=question, current_question=question,
            reply_block="", window=win, speaker=AUTHOR, addressee="чат",
            memory_hints=user_blocks, speech_hints="", capabilities=(),
            force_line="", persona_frame=character_block, bot_replies=(),
            history_partial=False, alias_resolver=None)
    except Exception as exc:                              # noqa: BLE001
        result["stage_errors"]["l1_context"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        l1_context = question
    result["l1_input"] = {"system_chars": len(l1_system),
                          "system_sha12": sha12(l1_system),
                          "context_chars": len(l1_context),
                          "context_sha12": sha12(l1_context)}
    t0 = time.time()
    try:
        raw_l1 = await llm.generate(
            [{"role": "system", "content": l1_system},
             {"role": "user", "content": l1_context}],
            temperature=(l1mod.l1_temperature(None) if hasattr(l1mod, "l1_temperature") else None), chat_id=None, module="probe", step="l1_planner",
            max_output_tokens=l1mod.l1_max_output_tokens())
        plan_l1 = l1mod.parse_l1_plan(raw_l1)
        result["l1_raw"] = str(raw_l1 or "")[:4000]
        result["l1_plan"] = (_plan_dict(plan_l1) if plan_l1 else None)
        result["l1_elapsed_s"] = round(time.time() - t0, 1)
        result["l1_parse_failed"] = plan_l1 is None
    except Exception as exc:                              # noqa: BLE001
        result["stage_errors"]["l1_call"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        plan_l1 = None

    # ── real L2 writer with the produced plan (2 repeats)
    plan_block = ""
    try:
        _adn = getattr(l1mod, "analysis_directive_needed", None)
        modes_on = bool(getattr(gates, "smart_verbalizer_modes_enabled", True))
        if plan_l1 is not None:
            _plan_used = plan_l1
        else:
            _plan_used = l1mod.fallback_plan(question)
            result["plan_source"] = "deterministic_fallback"
        if _adn is None:
            plan_block = l1mod.build_l2_plan_block(_plan_used)
            result["analysis_predicate"] = "absent_in_variant"
        else:
            _inc = bool(_adn(_plan_used, modes_on=modes_on))
            plan_block = l1mod.build_l2_plan_block(_plan_used,
                                                   include_analysis=_inc)
            result["analysis_predicate"] = {"value": _inc,
                                            "present": True}
    except Exception as exc:                              # noqa: BLE001
        result["stage_errors"]["plan_block"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
    result["plan_block"] = {"chars": len(plan_block),
                            "sha12": sha12(plan_block),
                            "analysis_directive": plan_block.count("ANALYSIS_DIRECTIVE"),
                            "analysis_writer": plan_block.count("ANALYSIS_WRITER")}

    user_parts = [p for p in (plan_block, user_blocks,
                              "<Target_User>%s</Target_User>" % AUTHOR,
                              "<Global_Context>\n" + build_window_text(win) +
                              "\n</Global_Context>",
                              "<Current_Question>\n" + question + "\n</Current_Question>") if p]
    user_text = "\n\n".join(user_parts)
    result["user"] = {"chars": len(user_text), "sha12": sha12(user_text),
                      "analysis_directive": user_text.count("ANALYSIS_DIRECTIVE"),
                      "analysis_writer": user_text.count("ANALYSIS_WRITER")}
    payload = {"messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user_text}]}
    if args.skip_l2:
        return
    l2 = []
    max_tokens = 2400
    for i in range(max(1, args.repeats)):
        t0 = time.time()
        rec = {"repeat": i + 1, "temperature": args.temperature,
               "max_tokens": max_tokens}
        try:
            text = await llm.generate(
                payload["messages"], temperature=args.temperature,
                chat_id=None, module="probe", step="l2_writer",
                max_output_tokens=max_tokens)
            rec.update({"chars": len(text or ""), "sha12": sha12(text),
                        "text": text})
        except Exception as exc:                          # noqa: BLE001
            rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        rec["elapsed_s"] = round(time.time() - t0, 1)
        l2.append(rec)
    result["l2_runs"] = [{k: v for k, v in r.items() if k != "text"} for r in l2]
    result["l2_texts"] = [r.get("text") or "" for r in l2]


def _plan_dict(plan):
    if plan is None:
        return None
    keys = ("action", "response_act", "extent", "structure", "tone",
            "delivery_hint", "confidence", "confidence_bucket", "source",
            "needs_clarification")
    return {k: getattr(plan, k, None) for k in keys}


def _make_llm(root, result):
    from services.llm_client import LLMClient
    base = env(os.path.join(root, ".env"), "LLM_BASE_URL")
    keyv = env(os.path.join(root, ".env"), "LLM_API_KEY")
    model = env(os.path.join(root, ".env"), "LLM_MODEL_NAME")
    client = LLMClient(base, keyv, model, "", embed_base_url="", embed_api_key="")

    async def _noop(*a, **k):
        return None

    for name in ("_record_analytics", "_record_global_usage"):
        if hasattr(client, name):
            setattr(client, name, _noop)
    try:
        from services import mca_events
        mca_events.emit_mca_event = lambda *a, **k: None
    except Exception:                                     # noqa: BLE001
        pass
    try:
        from services import usage_events
        usage_events.record = _noop
    except Exception:                                     # noqa: BLE001
        pass
    result["llm"] = {"model": model, "base_host": base.split("//")[-1].split("/")[0]}
    return client


if __name__ == "__main__":
    raise SystemExit(main())
