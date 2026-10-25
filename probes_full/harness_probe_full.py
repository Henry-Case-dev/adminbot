#!/usr/bin/env python3
"""P0 FULL probe (corrected 25.10.2026): один реальный L1 на весь payload.

Исполняется ИЗ ТОГО ЖЕ ДЕРЕВА, что и проверяемый код (`--root`), read-only:
PG через read-only сессию, SQLite через mode=ro; без Telegram/деплоя/записи.

Отличия от прежней копии (аудит `evidence/p0-hotfix/l1-harness-audit.md` §6-7):

* версия пинуется: git HEAD/ветка/грязность + sha256 импортированных модулей,
  запуск из самого дерева (никакой staging-копии без `.git`);
* ОДИН реальный план L1 на весь payload: mode, extent-блок, plan-блок и
  system собираются из одного и того же решения L1;
* принудительный research — отдельный сценарий `--force-plan research`,
  помеченный `forced=true` (не выдаётся за решение L1);
* счётчики — по фактическим `psb.ANALYSIS_DIRECTIVE_TEXT` /
  `psb.ANALYSIS_WRITER_TEXT` в system/user/total (не по ASCII-именам);
* RAG — реальной цепочкой прод-сервиса (`_rag_rows_with_ranks` → фильтр
  self-origin → `dedup_rag_vs_global` → `_mark_rag_fact` →
  `order_rag_facts_asc` → `build_rag_context(origin_labels=True)` →
  `<RAG_Memory>` + cap); ошибка рендера = `invalid`, без подмены строками;
* user-часть — в порядке сервиса (time_line → plan → speech/lessons при
  composer OFF → user_blocks → evidence) и передаётся композеру как
  защищённые `user_parts`;
* сбой L1/сборки — `invalid`, а не детерминированный fallback-план.

`--self-check` — офлайн-проверка счётчиков/предиката/пинов на целевом дереве;
обязателен перед серверным сеансом.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

CHAT_ID = -1002661910336
TG_A, TG_B = 1175252, 1175255
TS_A, TS_B = 1792873281, 1792873478
AUTHOR = "Ринтаро"

PINNED_MODULES = (
    "services/chat_prompts.py",
    "services/direct_l1.py",
    "services/prompt_style_blocks.py",
    "services/response_extent.py",
    "services/direct_chat_service.py",
    "services/summary_memory.py",
    "services/prompt_composer.py",
    "services/prompt_registry.py",
)


def sha12(text) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_state(root: str) -> dict:
    def _run(*args):
        try:
            return subprocess.run(["git", "-C", root, *args], check=True,
                                  capture_output=True, text=True,
                                  timeout=20).stdout.strip()
        except Exception as exc:                      # noqa: BLE001
            return "ERR:%s" % exc
    return {"commit": _run("rev-parse", "HEAD"),
            "branch": _run("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(_run("status", "--porcelain")),
            "dirty_files": _run("status", "--porcelain").splitlines()[:20]}


def module_pins(root: str) -> dict:
    out = {}
    for rel in PINNED_MODULES:
        path = os.path.join(root, rel)
        out[rel] = {"sha256": sha256_file(path), "chars": os.path.getsize(path)}
    return out


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
        self._chat_params = chat_params or {}
        self._journal = []

    def get(self, key, default=None):
        overrides = self._chat_params.get("overrides") or {}
        if key in overrides:
            return overrides[key]
        return self._settings.get(key, default)

    async def get_chat_params(self, chat_id):
        self._journal.append(chat_id)
        return {"overrides": self._chat_params}

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
           "traits": [], "identity": None}
    for r in await conn.fetch("SELECT key, value FROM bot_settings"):
        out["settings"][r["key"]] = jload(r["value"], r["value"])
    try:
        rows = await conn.fetch(
            "SELECT chat_params FROM chat_profiles WHERE chat_id = $1", CHAT_ID)
        if rows and rows[0]["chat_params"]:
            out["chat_params"] = jload(rows[0]["chat_params"], {}) or {}
    except Exception as exc:                          # noqa: BLE001
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
        except Exception as exc:                      # noqa: BLE001
            out[key + "_error"] = str(exc)[:160]
    await conn.close()
    return out


def load_sqlite(root):
    conn = sqlite3.connect(
        "file:%s?mode=ro" % os.path.join(root, "local_database.db"),
        uri=True, timeout=20)
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
            ("chat_running_summary", "SELECT * FROM chat_running_summary "
                                     "WHERE chat_id = ? LIMIT 3"),
            ("summary_runs", "SELECT * FROM summary_runs WHERE chat_id = ? "
                             "ORDER BY rowid DESC LIMIT 4"),
            ("summary_levels", "SELECT * FROM chat_summary_levels "
                               "WHERE chat_id = ? LIMIT 3"),
        ):
            try:
                out[name] = [dict(r) for r in cur.execute(sql, (CHAT_ID,)).fetchall()]
            except Exception as exc:                  # noqa: BLE001
                out[name + "_error"] = str(exc)[:160]
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


def text_counts(text: str, psb) -> dict:
    """Честные счётчики: фактические тексты, а не ASCII-имена констант."""
    return {"directive": text.count(psb.ANALYSIS_DIRECTIVE_TEXT),
            "writer": text.count(psb.ANALYSIS_WRITER_TEXT),
            "ascii_marker": text.count("ANALYSIS_DIRECTIVE")}


def payload_counts(system: str, user_text: str, psb) -> dict:
    s, u = text_counts(system, psb), text_counts(user_text, psb)
    total = text_counts(system + "\n\n" + user_text, psb)
    return {"system": s, "user": u, "total": total,
            "invariant_1x1": (total["directive"], total["writer"]) == (1, 1),
            "invariant_0x0": (total["directive"], total["writer"]) == (0, 0)}


# ── RAG: реальная цепочка прод-сервиса (без самодельного рендера) ───────────

def build_rag_block(root: str, sq: dict, question: str, global_ctx: str,
                    hot) -> tuple[str, dict]:
    from services import provenance as _prov
    from services.direct_chat_service import (
        _SELF_ECHO_INSTRUCTION, _mark_rag_fact, _rag_rows_with_ranks,
        dedup_rag_vs_global, order_rag_facts_asc)
    from services.summary_memory import build_rag_context

    rows = sq.get("graph_facts") or []
    meta = {"rows": len(rows), "kept": 0, "render": "real"}
    if not rows:
        meta["render"] = "absent"
        return "", meta
    facts, ranks = _rag_rows_with_ranks(rows)
    facts = [item for item in facts
             if not _prov.is_self_referential_origin(item[0])]
    meta["after_self_filter"] = len(facts)
    if facts:
        kept = dedup_rag_vs_global(facts, global_ctx)
        meta["after_dedup"] = len(kept)
        if kept:
            kept = [_mark_rag_fact(item, ranks) for item in kept]
            content = build_rag_context(
                order_rag_facts_asc(kept), origin_labels=True)
            if not content:
                raise RuntimeError("rag_render: empty build_rag_context")
            if any(str(item[0]) == "bot_self_reply" for item in kept):
                content = f"{_SELF_ECHO_INSTRUCTION}\n{content}"
            cap = int(hot.get("limits.graph_rag_context_max_chars",
                              _service_settings().GRAPH_RAG_CONTEXT_MAX_CHARS)
                      or 0)
            meta["cap"] = cap
            if cap and len(content) > cap:
                content = content[:cap]
            meta["kept"] = len(kept)
            return f"<RAG_Memory>\n{content}\n</RAG_Memory>", meta
    meta["kept"] = 0
    return "", meta


def _service_settings():
    from services import direct_chat_service
    return direct_chat_service.settings


def self_check(root: str, json_out: bool = False) -> int:
    os.chdir(root)
    sys.path.insert(0, root)
    from services import direct_l1 as l1
    from services import prompt_style_blocks as psb
    from services import response_extent as extent

    pins = {"root": root, "git": git_state(root), "modules": module_pins(root)}
    # 1) счётчик по фактическому тексту = 1; ASCII-имя константы = 0
    synthetic = "a " + psb.ANALYSIS_DIRECTIVE_TEXT + " b " + \
        psb.ANALYSIS_WRITER_TEXT + " c"
    counts = text_counts(synthetic, psb)
    # 2) предикат и режим на синтетическом research-плане
    plan = l1.normalize_l1_plan({
        "action": "reply", "response_act": "research", "extent": "compact",
        "structure": "answer", "confidence": 0.8})
    answer = l1.normalize_l1_plan({
        "action": "reply", "response_act": "answer", "extent": "compact",
        "structure": "chat", "confidence": 0.8})
    # 3) тот же путь сборки, что в _run: mode/extent/plan из одного плана
    extent_block = extent.render_extent_block(plan.to_response_plan())
    plan_block = l1.build_l2_plan_block(plan, include_analysis=True)
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", l1.plan_response_mode(plan), "plain",
        html_safe=True, extent_block=extent_block)
    synthetic_payload = payload_counts(system, plan_block, psb)
    results = {
        "counts_1x1": counts["directive"] == 1 and counts["writer"] == 1,
        "ascii_marker_zero": counts["ascii_marker"] == 0,
        "payload_1x1": synthetic_payload["invariant_1x1"],
        "predicate_research": l1.analysis_directive_needed(plan) is True,
        "predicate_answer": l1.analysis_directive_needed(answer) is False,
        "mode_research_serious": l1.plan_response_mode(plan) == "serious",
        "modules_under_root": all(
            os.path.commonpath([os.path.abspath(root),
                                os.path.abspath(p)]) == os.path.abspath(root)
            for p in (psb.__file__, l1.__file__)),
    }
    ok = all(results.values())
    out = {"self_check": "PASS" if ok else "FAIL", "results": results,
           "counts": counts, "synthetic_payload": synthetic_payload,
           "pins": pins}
    print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])
    return 0 if ok else 1


def _make_llm(root, result):
    from services.llm_client import LLMClient
    base = env(os.path.join(root, ".env"), "LLM_BASE_URL")
    keyv = env(os.path.join(root, ".env"), "LLM_API_KEY")
    model = env(os.path.join(root, ".env"), "LLM_MODEL_NAME")
    client = LLMClient(base, keyv, model, "", embed_base_url="",
                       embed_api_key="")

    async def _noop(*a, **k):
        return None

    for name in ("_record_analytics", "_record_global_usage"):
        if hasattr(client, name):
            setattr(client, name, _noop)
    try:
        from services import mca_events
        mca_events.emit_mca_event = lambda *a, **k: None
    except Exception:                                 # noqa: BLE001
        pass
    try:
        from services import usage_events
        usage_events.record = _noop
    except Exception:                                 # noqa: BLE001
        pass
    result["llm"] = {"model": model,
                     "base_host": base.split("//")[-1].split("/")[0]}
    return client


def _plan_dict(plan):
    if plan is None:
        return None
    keys = ("action", "response_act", "extent", "structure", "tone",
            "delivery_hint", "confidence", "confidence_bucket", "source",
            "needs_clarification")
    return {k: getattr(plan, k, None) for k in keys}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--label", default="probe")
    ap.add_argument("--case", default="A", choices=("A", "B"))
    ap.add_argument("--out", default="")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--skip-l2", action="store_true")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--force-plan", default="",
                    choices=("", "research"))
    ap.add_argument("--force-extent", default="normal",
                    choices=("compact", "normal", "auto", "detailed"))
    ap.add_argument("--force-structure", default="answer",
                    choices=("answer", "report"))
    args = ap.parse_args()
    if args.self_check:
        return self_check(args.root)
    if not args.out:
        print("--out is required (no silent console-only run)", file=sys.stderr)
        return 2

    os.chdir(args.root)
    sys.path.insert(0, args.root)
    result = {"label": args.label, "root": args.root, "case": args.case,
              "chat_id": CHAT_ID, "forced": bool(args.force_plan),
              "force_plan": args.force_plan or None,
              "invalid": "", "stage_errors": {},
              "pins": {"git": git_state(args.root),
                       "harness": {
                           "path": os.path.abspath(__file__),
                           "sha256": sha256_file(os.path.abspath(__file__))},
                       "modules": module_pins(args.root)}}
    try:
        asyncio.run(_run(args, result))
    except Exception as exc:                          # noqa: BLE001
        import traceback
        result["fatal"] = "%s: %s" % (type(exc).__name__, str(exc)[:400])
        result["traceback"] = traceback.format_exc()[-2500:]
    json.dump(result, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: result.get(k) for k in
                      ("label", "case", "forced", "invalid", "fatal",
                       "l1_plan", "mode", "payload_counts", "l2_runs",
                       "stage_errors")}, ensure_ascii=False)[:2200])
    return 0


async def _run(args, result):
    from services import hot_config as hot
    from services import prompt_composer as pcomp
    from services import prompt_style_blocks as psb
    from services import response_extent as extent
    from services import direct_l1 as l1mod
    from services.prompt_style_blocks import resolve_prompt
    from services.prompt_registry import resolve_chat_speech

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
    try:
        import asyncpg
        dsn = ""
        for k in ("DATABASE_URL", "POSTGRES_DSN"):
            dsn = env(os.path.join(args.root, ".env"), k)
            if dsn:
                break
        pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=2,
            server_settings={"default_transaction_read_only": "on"})
        bot_persona.set_persona_pool(pool)
    except Exception as exc:                          # noqa: BLE001
        result["stage_errors"]["persona_pool"] = str(exc)[:200]

    target_ts = TS_A if args.case == "A" else TS_B
    tg_id = TG_A if args.case == "A" else TG_B
    win = [m for m in sq.get("window_%s" % args.case, [])
           if str(m.get("tg_message_id")) != str(tg_id)]
    question = ""
    for m in sq.get("window_A", []):
        if str(m.get("tg_message_id")) == str(tg_id):
            question = m.get("text") or ""
    result["question"] = question
    result["target_ts"] = target_ts

    # ── identity / persona (PG pool + real renderers)
    character_block = ""
    try:
        from services import mca_gates
        if mca_gates.character_layers_enabled():
            ctx = await bot_persona.resolve_character_context(CHAT_ID)
            persona, traits = ctx.persona, list(ctx.traits)
        else:
            persona = await bot_persona.resolve_bot_persona(CHAT_ID)
            traits = await bot_persona.get_traits(50)
        character_block = bot_persona.build_persona_prompt_block(
            persona, traits, enabled=True) or ""
        if mca_gates.character_layers_enabled():
            rules = bot_persona.build_character_rules_block()
            if rules:
                character_block = (character_block + "\n\n" + rules).strip()
    except Exception as exc:                          # noqa: BLE001
        result["stage_errors"]["identity"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:220])
    result["identity_block_chars"] = len(character_block)

    # ── реальный L2 summary (SQLite)
    summary_text = ""
    rows = sq.get("chat_running_summary") or []
    if rows:
        row = rows[0]
        summary_text = str(row.get("summary") or row.get("text") or "")
    result["l2_summary"] = {"chars": len(summary_text),
                            "sha12": sha12(summary_text) if summary_text else ""}

    # ── реальный RAG (ошибка рендера = invalid, без fallback-строк)
    window_text = build_window_text(win)
    try:
        rag_block, rag_meta = build_rag_block(
            args.root, sq, question, window_text, hot)
    except Exception as exc:                          # noqa: BLE001
        rag_block, rag_meta = "", {"render": "error"}
        result["invalid"] = "rag_render"
        result["stage_errors"]["rag"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:220])
    result["rag"] = dict(rag_meta, block_chars=len(rag_block),
                         block_sha12=sha12(rag_block))

    # ── реальные lessons (SQLite) через реальный рендерер
    lessons_block = ""
    try:
        from services import mca_experience as mca_exp
        lessons = sq.get("mca_lessons") or []
        if lessons:
            lessons_block = mca_exp.render_lessons_block(lessons)
    except Exception as exc:                          # noqa: BLE001
        result["stage_errors"]["lessons"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:200])
    result["lessons_block_chars"] = len(lessons_block)

    # ── base prompt + gates
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
    modes_on = bool(getattr(gates, "smart_verbalizer_modes_enabled", True))

    # ── L1: один реальный план (или явно помеченный forced)
    llm = _make_llm(args.root, result)
    l1_system = resolve_prompt("prompts.direct_l1_planner_system_prompt", None)
    source = "pg" if l1_system else "code_default"
    if not l1_system:
        from services.direct_chat_service import (
            DIRECT_L1_PLANNER_SYSTEM_PROMPT as l1_system)
    result["l1_canon"] = {"chars": len(l1_system), "sha12": sha12(l1_system),
                          "source": source}
    plan = None
    if args.force_plan:
        plan = l1mod.normalize_l1_plan({
            "action": "reply", "response_act": args.force_plan,
            "extent": args.force_extent, "structure": args.force_structure,
            "delivery_hint": "plain", "confidence": 1.0})
        result["plan_source"] = "forced"
    else:
        try:
            l1_context = l1mod.build_l1_context(
                query=question, current_question=question,
                reply_block="", window=win, speaker=AUTHOR, addressee="чат",
                memory_hints=rag_block, speech_hints="", capabilities=(),
                force_line="", persona_frame=character_block, bot_replies=(),
                history_partial=False, alias_resolver=None)
        except Exception as exc:                      # noqa: BLE001
            result["invalid"] = result["invalid"] or "l1_context"
            result["stage_errors"]["l1_context"] = "%s: %s" % (
                type(exc).__name__, str(exc)[:300])
            l1_context = None
        result["l1_input"] = {"system_sha12": sha12(l1_system),
                              "context_chars": len(l1_context or ""),
                              "context_sha12": sha12(l1_context)}
        if l1_context is not None:
            t0 = time.time()
            try:
                raw_l1 = await llm.generate(
                    [{"role": "system", "content": l1_system},
                     {"role": "user", "content": l1_context}],
                    temperature=(l1mod.l1_temperature(None)
                                 if hasattr(l1mod, "l1_temperature") else None),
                    chat_id=None, module="probe", step="l1_planner",
                    max_output_tokens=l1mod.l1_max_output_tokens())
                plan = l1mod.parse_l1_plan(raw_l1)
                result["l1_raw"] = str(raw_l1 or "")[:4000]
                result["l1_elapsed_s"] = round(time.time() - t0, 1)
            except Exception as exc:                  # noqa: BLE001
                result["stage_errors"]["l1_call"] = "%s: %s" % (
                    type(exc).__name__, str(exc)[:300])
        if plan is None:
            # никакого fallback-плана: прогон невалиден
            result["invalid"] = result["invalid"] or "l1_plan"
            result["plan_source"] = "invalid"
            return
        result["plan_source"] = "llm"
    result["l1_plan"] = _plan_dict(plan)

    # ── ОДИН план на весь payload
    if plan is None:
        result["invalid"] = result["invalid"] or "l1_plan"
        return
    try:
        response_mode = l1mod.plan_response_mode(plan)
        response_plan = plan.to_response_plan()
        extent_block = extent.render_extent_block(response_plan)
        _adn = getattr(l1mod, "analysis_directive_needed", None)
        include_analysis = (bool(_adn(plan, modes_on=modes_on))
                            if _adn is not None else None)
        if include_analysis is None:
            result["invalid"] = result["invalid"] or "predicate_absent"
            return
        plan_block = l1mod.build_l2_plan_block(
            plan, include_analysis=include_analysis)
    except Exception as exc:                          # noqa: BLE001
        result["invalid"] = result["invalid"] or "plan_build"
        result["stage_errors"]["plan_build"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:300])
        return
    result["mode"] = response_mode
    result["analysis_predicate"] = include_analysis
    result["extent_block_chars"] = len(extent_block)
    result["plan_block"] = {"chars": len(plan_block),
                            "sha12": sha12(plan_block)}

    # ── user-часть в порядке сервиса: plan → speech/lessons (composer OFF) →
    #    user_blocks (rag → global → target → current) → evidence (нет).
    #    <Chat_Summary> не изобретаем: в direct-пути пересказ приходит внутри
    #    global head/tail; summary фиксируется отдельным фактом, не инжектом.
    user_blocks = [b for b in (
        rag_block,
        ("<Global_Context>\n" + window_text + "\n</Global_Context>")
        if window_text else "") if b]
    _c_on = pcomp.composer_enabled_now(await pcomp.resolve_gates(CHAT_ID))
    parts = []
    if plan_block:
        parts.append(plan_block)
    if not _c_on:
        if lessons_block:
            parts.append(lessons_block)
    parts.extend(user_blocks)
    parts.extend(("<Target_User>%s</Target_User>" % AUTHOR,
                  "<Current_Question>\n" + question + "\n</Current_Question>"))
    user_text = "\n\n".join([p for p in parts if p])
    result["composer_on"] = _c_on
    result["summary_injection"] = {"chars": len(summary_text),
                                   "injected": False,
                                   "reason": "summary живёт в global head/tail"}

    # ── system из того же плана; user_parts передаются композеру
    from services.direct_chat_service import DirectChatService
    try:
        system, manifest = await DirectChatService._compose_speech_system(
            None, chat_id=CHAT_ID, writer="l2_writer", run_id="p0-probe",
            base_prompt=base_prompt,
            base_key="prompts.direct_chat_verbalizer_system_prompt",
            base_default="", gates=gates, channel="plain", html_safe=True,
            base_source=(base_source or ""), include_mode_block=True,
            response_mode=response_mode, response_plan=response_plan,
            extent_block=extent_block, identity_text=character_block,
            identity_source="chat",
            identity_skipped=("" if getattr(gates, "persona_enabled", True)
                              else "persona_disabled"),
            lessons_block=lessons_block,
            lessons_skip=("" if lessons_block else "lessons_absent"),
            speech_block="", speech_skip="speech_absent",
            context_text=question,
            user_parts=(tuple(parts) if _c_on else ()))
        # тот же конфликт-скраб, что сервис применяет к ФИНАЛЬНОЙ сборке
        system, _scrubbed = extent.scrub_for_plan(system, response_plan)
        result["extent_scrub_removed"] = int(_scrubbed or 0)
        result["layers"] = [{"layer": t.layer, "block_id": t.block_id,
                             "chars": t.chars, "rendered": bool(t.rendered),
                             "skip_reason": t.skip_reason}
                            for t in manifest.layers]
        result["core"] = {"chars": len(getattr(manifest.versions, "core", "")
                                       or ""),
                          "detail": getattr(manifest.versions, "core_detail",
                                            None)}
    except Exception as exc:                          # noqa: BLE001
        result["invalid"] = result["invalid"] or "compose_system"
        result["stage_errors"]["compose_system"] = "%s: %s" % (
            type(exc).__name__, str(exc)[:300])
        return

    result["system"] = {"chars": len(system), "sha12": sha12(system),
                        "core_marker": "<Personality_Core>" in system,
                        "expression_marker": "<Expression" in system}
    result["user"] = {"chars": len(user_text), "sha12": sha12(user_text)}
    counts = payload_counts(system, user_text, psb)
    result["payload_counts"] = counts
    research = str(getattr(plan, "response_act", "")) == "research"
    if research and include_analysis and not counts["invariant_1x1"]:
        result["invalid"] = result["invalid"] or "counter_invariant"
    if not research and not include_analysis and not counts["invariant_0x0"]:
        result["invalid"] = result["invalid"] or "counter_invariant"
    result["payload"] = {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text}]}
    if result["invalid"]:
        return
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
                result["payload"]["messages"], temperature=args.temperature,
                chat_id=None, module="probe", step="l2_writer",
                max_output_tokens=max_tokens)
            rec.update({"chars": len(text or ""), "sha12": sha12(text),
                        "text": text})
        except Exception as exc:                      # noqa: BLE001
            rec["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        rec["elapsed_s"] = round(time.time() - t0, 1)
        l2.append(rec)
    result["l2_runs"] = [{k: v for k, v in r.items() if k != "text"}
                         for r in l2]
    result["l2_texts"] = [r.get("text") or "" for r in l2]


if __name__ == "__main__":
    raise SystemExit(main())
