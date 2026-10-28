# -*- coding: utf-8 -*-
"""EXPRESSION-BISECT — офлайн-абляция «минимальная инструкция vs полный
effective prompt» Direct-writer (метод владельца, owner-corrective §2).

Без Telegram, без изменения конфигов. LLM — тот же клиент/модель, что в
бою (deepseek-v4-flash, temp 0.7 = CHAT_TEMPERATURE_BALANCED).

Плечи:
  A_min     — «используй мат, пиши как двачер» + стимул.
  B_full    — полный effective prompt (композер HEAD, frequent rev.2).
  C_full_nomat — B без <Expression_Settings> + минимальная инструкция в конец.
  D_nopersona  — B без <Persona>-блока (frame-правила «теплее/короче»).
  E_oldexpr    — B с Expression-блоком образца 2.58.96 (тексты до rewrite).

Валидация реконструкции: офлайн-дифф с живым сэмплом 2.58.96
(full_l2_system_sample, 7070 симв., sha12 c484a481868a).

TEST-LIFECYCLE: PROVISIONAL owner=EXPRESSION-BISECT (evidence-проба; не тест)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import re
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
HEAD_ROOT = (HERE.parent / "head").resolve()
OUT = HERE.parent / "results"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(HEAD_ROOT))
os.chdir(str(HEAD_ROOT))

from config.settings import settings                    # noqa: E402
from services import chat_params                        # noqa: E402
from services import hot_config as hot                  # noqa: E402
from services import mca_expression as expr             # noqa: E402
from services import prompt_composer as pc              # noqa: E402
from services import prompt_registry as pr              # noqa: E402
from services.chat_prompts import (                     # noqa: E402
    DIRECT_VERBALIZER_SYSTEM_PROMPT)
from services.llm_client import LLMClient               # noqa: E402
from services.prompt_style_blocks import resolve_prompt  # noqa: E402

PROBE_CHAT = -1002661910336          # старый чат (frequent rev.2 из диагностики)
TEMPERATURE = settings.CHAT_TEMPERATURE_BALANCED  # прод-дефолт balanced
MODEL = settings.LLM_MODEL_NAME      # прод .env: deepseek-v4-flash (тот же)

# ── известные прод-факты (план owner-corrective, диагностика 21.10) ─────────
CHAT_EXPRESSION_DOC = {
    "profanity": "frequent", "wit": "high", "sharpness": "sharp",
}
GLOBAL_EXPRESSION_DOC = {"profanity": "allowed"}   # read-alias → occasional

STIMULUS = "бот, ну что думаешь про понедельник?"
WINDOW_LINES = (
    "<Fresh_Chat_Window>\n"
    "Лена: рабочий день снова пролетел\n"
    "Макс: ага, как всегда\n"
    "Оля: " + STIMULUS + "\n"
    "</Fresh_Chat_Window>"
)
TIME_LINE = "[Текущее время в чате: 21.10.2026, 22:00, вторник]"
PLAN_BLOCK = "<Response_Plan>\nдействие: reply\n</Response_Plan>"
MINIMAL_INSTRUCTION = "используй мат, пиши как двачер"

EXTENT_MICRO_BLOCK = (
    "ОЖИДАЕМАЯ ПОЛНОТА: МИКРО. Ответ - одна короткая фраза или да/нет. "
    "Без разворотов и списков: ровно то, о чём спросили.")

# Identity-слайс из ЖИВОГО прод-сэмпла 2.58.96 (full_l2_system_sample):
# frame-рендер mca-18 + Character_Rules — те же байты, что видел Writer.
LIVE_SAMPLE_PATH = (HEAD_ROOT / "plans" / "features" / "add-exp" / "evidence"
                    / "release-25896" / "acceptance" / "followup"
                    / "summary.json")

CALLS = {"llm": 0}


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_updated_at(self, key):
        return None


class FakeChats:
    """chat_params-двойник: overrides старого чата (frequent rev.2)."""

    async def get_chat_params(self, chat_id):
        if int(chat_id) == PROBE_CHAT:
            return {"overrides": {
                "character.expression": dict(CHAT_EXPRESSION_DOC)}}
        return {"overrides": {}}


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def install_caches() -> None:
    # Прод: PG-значение ключа писателя = байты заводского канона
    # (soul-prep/prompts_classification.txt: stored_sha=39a7cce1523e ==
    #  factory=39a7cce1523e) БЕЗ провенанса API → withheld → эффективна
    # заводская редакция после suppress_legacy_speech (подтверждено живым
    # сэмплом 2.58.96: identity-предложение в payload отсутствует).
    hot.set_config_cache(FakeHot({
        "character.expression": dict(GLOBAL_EXPRESSION_DOC),
        "prompts.direct_chat_verbalizer_system_prompt":
            str(DIRECT_VERBALIZER_SYSTEM_PROMPT),
    }))
    chat_params.set_chat_params_cache(FakeChats())


def release_caches() -> None:
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    pr.reset_cache()


def identity_slice_from_sample() -> str:
    """Identity-слайс (Persona-frame + Character_Rules) из живого сэмпла."""
    raw = json.loads(LIVE_SAMPLE_PATH.read_text(encoding="utf-8"))
    system = raw["full_l2_system_sample"]["system_text"]
    start = system.index("<Persona>")
    end = system.index("</Character_Rules>") + len("</Character_Rules>")
    return system[start:end]


def style_hint_from_sample() -> str:
    raw = json.loads(LIVE_SAMPLE_PATH.read_text(encoding="utf-8"))
    system = raw["full_l2_system_sample"]["system_text"]
    start = system.index("<Style_Policy_Hint>")
    end = system.index("</Style_Policy_Hint>") + len("</Style_Policy_Hint>")
    return system[start:end]


def old_expression_block_from_sample() -> str:
    raw = json.loads(LIVE_SAMPLE_PATH.read_text(encoding="utf-8"))
    system = raw["full_l2_system_sample"]["system_text"]
    start = system.index("<Expression_Settings>")
    end = system.index("</Expression_Settings>") + len("</Expression_Settings>")
    return system[start:end]


async def build_full_system(*, with_expression: bool = True,
                            with_persona: bool = True,
                            old_expression: bool = False) -> tuple[str, dict]:
    """Полный effective prompt через РЕАЛЬНЫЙ композер HEAD (l2_writer)."""
    install_caches()
    try:
        verbalizer_template = resolve_prompt(
            "prompts.direct_chat_verbalizer_system_prompt",
            DIRECT_VERBALIZER_SYSTEM_PROMPT)
        core_full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
        core_ref = pc.CoreRef(
            text=core_full, revision="fac:" + sha12(core_full),
            source="global", detail_level="full", origin="owner_edit",
            detail_reason="owner_setting")
        expression_ref = await pc.resolve_expression_settings(PROBE_CHAT)
        if not with_expression:
            expression_ref = pc.ExpressionSettings(
                text="", enabled=False, skip_reason="expression_disabled")
        identity_text = identity_slice_from_sample() if with_persona else ""
        plan = pc.PromptPlan(
            profile="speech_plain", writer="l2_writer", chat_id=PROBE_CHAT,
            channel="plain", html_safe=True, run_id="expression-bisect",
            base_prompt=verbalizer_template, base_source="global",
            include_mode_block=True, response_mode="",
            response_plan=pc.PlanRef(
                text=EXTENT_MICRO_BLOCK, extent="micro", structure="chat",
                tone="inherit", revision=pc.sha12(EXTENT_MICRO_BLOCK),
                source="l1"),
            core=core_ref,
            identity=(pc.identity_from_text(
                identity_text, chat_id=PROBE_CHAT, run_id="expression-bisect",
                source="chat") if identity_text else None),
            expression=expression_ref,
            style_policy=pc.StylePolicyRef(
                hint=style_hint_from_sample(), revision=sha12(
                    style_hint_from_sample()), source="default",
                rule_count=3, soft_count=0),
            gates=pc.GateState(
                unified_composer_enabled=True, character_core_enabled=True,
                persona_enabled=True, character_layers_enabled=True,
                smart_verbalizer_modes_enabled=True,
                response_plan_enabled=True),
            user_parts=(TIME_LINE, PLAN_BLOCK, WINDOW_LINES),
        )
        manifest = pc.compose_prompt(plan)
        system = manifest.system
        if old_expression:
            # Плечо E: подменяем новый Expression-блок на байты 2.58.96.
            cur_start = system.index("<Expression_Settings>")
            cur_end = (system.index("</Expression_Settings>")
                       + len("</Expression_Settings>"))
            system = (system[:cur_start] + old_expression_block_from_sample()
                      + system[cur_end:])
        trace = {
            "manifest_id": manifest.manifest_id,
            "system_chars": len(system),
            "system_sha12": sha12(system),
            "tokens_total": manifest.tokens_total,
            "layers": [
                {"layer": t.layer, "block_id": t.block_id,
                 "rendered": t.rendered, "chars": t.chars,
                 "skip_reason": t.skip_reason}
                for t in manifest.layers],
        }
        return system, trace
    finally:
        release_caches()


def strip_block(system: str, tag_open: str, tag_close: str) -> str:
    start = system.index(tag_open)
    end = system.index(tag_close) + len(tag_close)
    return (system[:start] + system[end:]).replace("\n\n\n", "\n\n").strip()


async def generate(llm: LLMClient, system: str, tag: str,
                   runs: int) -> list[dict]:
    if tag == "A_min":
        user_content = STIMULUS
    else:
        user_content = "\n\n".join((TIME_LINE, PLAN_BLOCK, WINDOW_LINES))
    rows = []
    for i in range(runs):
        CALLS["llm"] += 1
        t0 = time.time()
        try:
            reply = await llm.generate(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user_content}],
                temperature=TEMPERATURE, chat_id=PROBE_CHAT,
                module="expression-bisect", step=tag,
                correlation_id="expression-bisect-%s-%d" % (tag, i))
        except Exception as exc:                     # noqa: BLE001
            reply = ""
            rows.append({"arm": tag, "run": i, "error": repr(exc)[:200]})
            continue
        rows.append({
            "arm": tag, "run": i,
            "reply": str(reply or ""),
            "reply_chars": len(str(reply or "")),
            "mat_roots": expr.count_profanity(reply),
            "mat_present": expr.count_profanity(reply) > 0,
            "elapsed_s": round(time.time() - t0, 1),
        })
        print("BISECT %s run%d mat_roots=%d chars=%d"
              % (tag, i, rows[-1]["mat_roots"], rows[-1]["reply_chars"]),
              flush=True)
    return rows


async def main() -> int:
    t0 = time.time()
    report: dict = {
        "kind": "expression_bisect",
        "date_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "head": "dad9afce (2.58.106, prod healthz)",
        "model": MODEL, "temperature": TEMPERATURE,
        "chat": PROBE_CHAT,
        "chat_expression": CHAT_EXPRESSION_DOC,
        "stimulus": STIMULUS, "minimal_instruction": MINIMAL_INSTRUCTION,
        "runs_per_arm": 4, "calls": 0,
        "arms": {}, "validation": {}, "static_analysis": {},
    }

    # ── Валидация реконструкции против живого сэмпла 2.58.96 ────────────────
    sample_raw = json.loads(LIVE_SAMPLE_PATH.read_text(encoding="utf-8"))
    sample_system = sample_raw["full_l2_system_sample"]["system_text"]
    install_caches()
    try:
        base_factory = resolve_prompt(
            "prompts.direct_chat_verbalizer_system_prompt",
            DIRECT_VERBALIZER_SYSTEM_PROMPT)
    finally:
        release_caches()
    report["static_analysis"]["base_factory_sha12"] = sha12(base_factory)
    report["static_analysis"]["base_pg_stored_sha12"] = "39a7cce1523e"
    report["static_analysis"]["base_factory_has_identity_sentence"] = (
        "бот-абьюзер" in DIRECT_VERBALIZER_SYSTEM_PROMPT)
    report["static_analysis"]["base_effective_has_identity_sentence"] = (
        "бот-абьюзер" in base_factory)
    report["validation"]["sample_sha12"] = sha12(sample_system)
    report["validation"]["sample_chars"] = len(sample_system)
    core_full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    report["validation"]["core_full_in_sample"] = core_full.strip()[:80] \
        in sample_system
    report["validation"]["extent_micro_in_sample"] = (
        EXTENT_MICRO_BLOCK in sample_system)

    # ── Сборка плеч ────────────────────────────────────────────────────────
    sys_full, trace_full = await build_full_system()
    sys_no_expr, _ = await build_full_system(with_expression=False)
    sys_no_persona, _ = await build_full_system(with_persona=False)
    sys_old_expr, _ = await build_full_system(old_expression=True)
    report["arms"]["B_full"] = {"system_trace": trace_full,
                                "system_sha12": trace_full["system_sha12"]}
    for name, s in (("B_full", sys_full), ("C_full_nomat", sys_no_expr),
                    ("D_nopersona", sys_no_persona), ("E_oldexpr", sys_old_expr)):
        (OUT / ("system_%s.txt" % name)).write_text(
            s + "\n", encoding="utf-8", newline="\n")
    sys_c = strip_block(sys_full, "<Expression_Settings>",
                        "</Expression_Settings>") + "\n\n" + MINIMAL_INSTRUCTION
    (OUT / "system_C_full_nomat.txt").write_text(
        sys_c + "\n", encoding="utf-8", newline="\n")

    # Статический анализ полного system
    blocks = {}
    for tag_open, tag_close, name in (
            ("<Expression_Settings>", "</Expression_Settings>", "expression"),
            ("<Persona>", "</Persona>", "persona"),
            ("<Character_Rules>", "</Character_Rules>", "character_rules"),
            ("<Style_Policy_Hint>", "</Style_Policy_Hint>", "style_hint")):
        try:
            s = sys_full.index(tag_open)
            e = sys_full.index(tag_close) + len(tag_close)
            blocks[name] = {"chars": e - s,
                            "share_pct": round(100.0 * (e - s)
                                               / len(sys_full), 1)}
        except ValueError:
            blocks[name] = None
    expr_text = strip_block(sys_full, "<Expression_Settings>",
                            "</Expression_Settings>")
    report["static_analysis"]["full_system_chars"] = len(sys_full)
    report["static_analysis"]["full_system_tokens_est"] = pc.estimate_tokens(
        sys_full)
    report["static_analysis"]["expression_block"] = blocks.get("expression")
    report["static_analysis"]["expression_position"] = (
        sys_full.index("<Expression_Settings>") if "<Expression_Settings>"
        in sys_full else -1)
    report["static_analysis"]["expression_chars"] = len(expr_text)
    report["static_analysis"]["expression_share_pct"] = round(
        100.0 * len(expr_text) / len(sys_full), 1)
    report["static_analysis"]["blocks"] = blocks
    neutralizers = {}
    for phrase in ("мат не вставляется насильно", "без мата", "уместность",
                   "оскорбления и травля не появляются", "травля",
                   "агрессия", "не агрессия", "Не подменяй шутку оскорблением",
                   "морализаторство", "вежлив", "нейтральн", "без грубости",
                   "избегай", "professional"):
        hits = len(re.findall(re.escape(phrase), sys_full, re.IGNORECASE))
        if hits:
            neutralizers[phrase] = hits
    report["static_analysis"]["neutralizing_phrases"] = neutralizers

    # ── LLM-абляция ────────────────────────────────────────────────────────
    if "--build-only" in sys.argv:
        report["calls"] = 0
        (OUT / "bisect-results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8", newline="\n")
        print("BISECT BUILD-ONLY OK full_sha12=%s chars=%d"
              % (trace_full["system_sha12"], trace_full["system_chars"]),
              flush=True)
        return 0
    llm = LLMClient(settings.LLM_BASE_URL, settings.LLM_API_KEY,
                    settings.LLM_MODEL_NAME, settings.EMBEDDING_MODEL_NAME)
    plan_runs = [("A_min", None, 4),
                 ("B_full", sys_full, 4),
                 ("C_full_nomat", sys_c, 4),
                 ("D_nopersona", sys_no_persona, 4),
                 ("E_oldexpr", sys_old_expr, 4)]
    all_rows = []
    for tag, system, n in plan_runs:
        if system is None:
            system = MINIMAL_INSTRUCTION
        rows = await generate(llm, system, tag, n)
        all_rows.extend(rows)
        report["arms"][tag] = {
            "runs": rows,
            "mat_present_n": sum(1 for r in rows if r.get("mat_present")),
            "mat_roots_total": sum(int(r.get("mat_roots") or 0)
                                   for r in rows),
            "avg_chars": round(sum(r.get("reply_chars") or 0 for r in rows)
                               / max(1, len(rows)), 0),
        }
    report["calls"] = CALLS["llm"]
    report["elapsed_total_s"] = round(time.time() - t0, 1)
    (OUT / "bisect-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    print("BISECT DONE calls=%d elapsed=%.0fs"
          % (CALLS["llm"], time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except Exception as exc:                          # noqa: BLE001
        import traceback
        (HERE.parent / "harness-error.log").write_text(
            traceback.format_exc(), encoding="utf-8")
        print("BISECT FATAL %s: %s" % (type(exc).__name__, str(exc)[:300]))
        rc = 4
    sys.exit(rc)
