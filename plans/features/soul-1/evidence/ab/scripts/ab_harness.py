# -*- coding: utf-8 -*-
"""SOUL-14.0 A/B — слепое сравнение композиции: старая (OFF) vs новая (ON).

Форк прецедента plans/features/soul-1/evidence/amd-probes (7a70e41a).
Ось A/B — ЕДИНСТВЕННЫЙ флаг `UNIFIED_COMPOSER_ENABLED` (env-ось, ON/OFF) на
одной HEAD-копии: OFF-рука = байт-в-байт прежняя сборка
(``prompt_style_blocks.compose_verbalizer_system`` + хвосты, direct_chat_service
L4636-4644), ON-рука = единый композер (``prompt_composer.compose_prompt`` через
реальный ``_compose_speech_system``-набор резолверов, direct_chat_service
L4403-4535). Одна модель/провайдер/temperature (0.7). LLM-судьи НЕТ
(acceptance запрещает объявлять качество баллом судьи): рубрика = 4
скриптовые детерминированные метрики + 6 ручных слепых размерностей.

Стадии:
  check    — валидация сцен: 11/11 типов, PII-паттерны, явные формы;
  smoke    — 1 сцена x 2 руки (2 платных вызова): манифесты + ось флага;
  run      — полный прогон (сцены x 2 руки) -> results.json + blind-файлы;
  analyze  — скриптовые метрики + слияние ручных слепых оценок -> analysis.md.

Безопасность: 0 сообщений в реальные чаты (прямые вызовы LLM на HEAD-копии);
персистентные конфиги не читаются/не пишутся (FakeHot/FakeChats — как в бою,
но данные процесса); env-оси — процесс-локальные; ретраев и поллинга нет;
пустой ответ честно записывается пустым. Результаты НЕ переключают прод-флаги.

TEST-LIFECYCLE: PROVISIONAL owner=SOUL-14.0 (evidence-харнес; не тест)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import random
import re
import sys
import time

# ── окружение ДО импортов конфига (зеркало прод-.env 2.58.86+; процесс-локально)
os.environ.setdefault("UNIFIED_COMPOSER_ENABLED", "1")
os.environ.setdefault("CHARACTER_CORE_ENABLED", "1")
os.environ.setdefault("SPEECH_STYLE_POLICY_ENABLED", "1")
os.environ.setdefault("HUMOR_CRAFT_ENABLED", "1")
os.environ.setdefault("HUMOR_LIBRARY_ENABLED", "1")
os.environ.setdefault("HUMOR_FEEDBACK_ENABLED", "1")

HERE = pathlib.Path(__file__).resolve().parent
EVID = HERE.parent                      # .../evidence/ab
HEAD_ROOT = pathlib.Path(os.environ.get(
    "AB_HEAD_ROOT",
    str(HERE.parents[5] / "OPENCODE_WORKFLOW_SCRATCH" / "ab-eval" / "head")))
sys.path.insert(0, str(HEAD_ROOT))
os.chdir(HEAD_ROOT)

from config.settings import settings    # noqa: E402  (после env)
from services import bot_persona        # noqa: E402
from services import chat_params        # noqa: E402
from services import direct_l1          # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import mca_expression     # noqa: E402
from services import mca_gates          # noqa: E402
from services import prompt_composer as pc        # noqa: E402
from services import prompt_style_blocks as psb   # noqa: E402
from services import response_extent as _extent   # noqa: E402
from services.chat_prompts import (     # noqa: E402
    DIRECT_VERBALIZER_SYSTEM_PROMPT)
from services.database import DatabaseService     # noqa: E402
from services.llm_client import LLMClient         # noqa: E402

PROBE_CHAT = -1007770000401
PROBE_USER = 990004001
TEMPERATURE = 0.7
BASE_KEY = "prompts.direct_chat_verbalizer_system_prompt"
BASE_DEFAULT = DIRECT_VERBALIZER_SYSTEM_PROMPT

MANUAL_DIMS = ("wit", "appropriacy", "coherence", "naturalness",
               "facts", "addressee")
MANUAL_DIMS_RU = {
    "wit": "остроумие", "appropriacy": "уместность",
    "coherence": "внутренняя связность", "naturalness": "естественность",
    "facts": "факты", "addressee": "адресат"}

# прод-зеркало hot-флагов (release-2.58.86 runbook + prod_recon-tr 19.10):
# jsonb-bool в bot_settings; документ Core — rev 1 detail_level=full
# (persistence-audit: full_text = заводской), текстовые поля пустые -> фабрика.
HOT_PROD_MIRROR = {
    "flags.unified_composer_enabled": True,
    "flags.character_core_enabled": True,
    "flags.speech_style_policy_enabled": True,
    "flags.humor_craft_enabled": True,
    "flags.humor_library_enabled": True,
    "flags.humor_feedback_enabled": True,
    "flags.persona_enabled": True,
    "character.core": {"detail_level": "full"},
}

# ── PII/анонимизация: закрытый набор паттернов (сцены - фикстуры) ───────────
PII_PATTERNS = (
    ("phone", re.compile(r"(?<!\d)[+78][\s\-(]?\d{3}[\s\-)]?\d{3}[\s\-]?\d{2}"
                         r"[\s\-]?\d{2}(?!\d)")),
    ("card", re.compile(r"(?<!\d)\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}(?!\d)")),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("handle", re.compile(r"@[A-Za-z_][A-Za-z0-9_]{3,}")),
    ("url", re.compile(r"https?://|t\.me/|www\.")),
    ("owner_circle", re.compile(
        r"\b(славик|костик|алан|ол[ья])\b", re.IGNORECASE)),
)


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def info(tag: str, text: str) -> None:
    print("AB %s | %s" % (tag, text), flush=True)


class FakeHot:
    """Процесс-локальное зеркало hot-конфига (персистентные не читаются)."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_updated_at(self, key):
        return None


class FakeChats:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}


class CountingLLM(LLMClient):
    async def generate(self, messages, temperature=None, *a, **kw):
        CALLS["llm"] += 1
        return await super().generate(messages, temperature, *a, **kw)


CALLS = {"llm": 0, "search": 0}


def load_scenes() -> list[dict]:
    data = json.loads((EVID / "scenes.json").read_text(encoding="utf-8"))
    return list(data["scenes"])


# ═════════════════════════════════════════════════════════════════════════════
# Стадия check: покрытие типов, PII, явные формы
# ═════════════════════════════════════════════════════════════════════════════

def stage_check() -> int:
    scenes = load_scenes()
    need = {"empty_joke", "tech_question", "insult", "support", "story",
            "creative", "one_word", "longform", "flame",
            "factual_correction", "initiative_hook"}
    have = {s["type"] for s in scenes}
    missing = need - have
    extra = have - need
    counts = {t: sum(1 for s in scenes if s["type"] == t) for t in sorted(have)}
    info("check", "scenes=%d types=%d/11 counts=%s" % (
        len(scenes), len(have), counts))
    problems = []
    if missing:
        problems.append("missing types: %s" % sorted(missing))
    if extra:
        problems.append("extra types: %s" % sorted(extra))
    for t, n in counts.items():
        if n < 2:
            problems.append("type %s has %d scenes (<2)" % (t, n))
    for s in scenes:
        for name, rx in PII_PATTERNS:
            hit = rx.search(s["text"])
            if hit:
                problems.append("PII[%s] in %s: %r" % (name, s["id"],
                                                       hit.group(0)))
        if len(s["text"]) < 12 or len(s["text"]) > 600:
            problems.append("len out of bounds in %s (%d)" % (
                s["id"], len(s["text"])))
        if s["type"] == "one_word" and not _extent.explicit_form_override(
                s["text"]):
            problems.append("one_word scene %s: explicit form NOT detected"
                            % s["id"])
        if s["type"] == "longform" and _extent.explicit_form_override(
                s["text"]) != "longform":
            problems.append("longform scene %s: explicit form != longform"
                            % s["id"])
    ids = [s["id"] for s in scenes]
    if len(set(ids)) != len(ids):
        problems.append("duplicate scene ids")
    if problems:
        for p in problems:
            info("check_FAIL", p)
        return 3
    info("check", "OK: 11/11 типов, PII-паттернов нет, явные формы детектятся")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# Сборка рук: точная репликация runtime-путей direct_chat_service
# ═════════════════════════════════════════════════════════════════════════════

def install_caches() -> None:
    hot.set_config_cache(FakeHot(HOT_PROD_MIRROR))
    chat_params.set_chat_params_cache(FakeChats())


def uninstall_caches() -> None:
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()


async def character_block_for(chat_id: int) -> dict:
    """Реальный хвост личности (как в OFF-пути direct_chat_service L2673-2700).

    На HEAD-копии с dev-БД персона может быть пустой -> "" в ОБЕИХ руках
    (честно фиксируется). Никогда не бросает.
    """
    out = {"block": "", "persona_chars": 0, "rules_chars": 0, "error": ""}
    try:
        if mca_gates.character_layers_enabled():
            ctx = await bot_persona.resolve_character_context(chat_id)
            persona_block = bot_persona.build_persona_prompt_block(
                ctx.persona, [t.text for t in ctx.traits], enabled=True)
        else:
            persona = await bot_persona.resolve_bot_persona(chat_id)
            traits = await bot_persona.get_traits(
                int(getattr(settings, "PERSONA_TRAITS_MAX", 50) or 50))
            persona_block = bot_persona.build_persona_prompt_block(
                persona, [t.get("text") for t in traits], enabled=True)
        block = persona_block or ""
        out["persona_chars"] = len(persona_block or "")
        if mca_gates.character_layers_enabled():
            rules = bot_persona.build_character_rules_block()
            if rules:
                block = (block + "\n\n" + rules) if block else rules
                out["rules_chars"] = len(rules)
        out["block"] = block
    except Exception as exc:            # noqa: BLE001 — как runtime-ветка
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        out["block"] = ""
    return out


def manifest_trace(manifest: pc.PromptManifest) -> list[dict]:
    return [{
        "layer": t.layer, "block_id": t.block_id, "owner": t.owner,
        "source": t.source, "revision": t.revision, "chars": t.chars,
        "tokens": t.tokens, "rendered": bool(t.rendered),
        "skip_reason": t.skip_reason, "conflict": t.conflict,
        "detail": t.detail,
    } for t in manifest.layers]


async def build_off_system(chat_id: int, query: str, response_plan,
                           character_block: str) -> dict:
    """OFF-рука: байт-в-байт прежняя сборка (direct_chat_service L4570-4648)."""
    modes_on = bool(getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True))
    if not modes_on:                    # вне A/B-оси: в проде ось всегда ON
        raise RuntimeError("SMART_VERBALIZER_MODES_ENABLED is OFF — "
                           "legacy-шаблон вне скоупа A/B")
    response_mode = direct_l1.plan_response_mode(response_plan)
    extent_block = _extent.render_extent_block(response_plan)
    system = psb.compose_verbalizer_system(
        BASE_DEFAULT, response_mode, "plain", html_safe=True,
        character_block=character_block, style_directives="",
        extent_block=extent_block)
    system, scrubbed = _extent.scrub_for_plan(system, response_plan)
    return {"system": system, "response_mode": response_mode,
            "extent_block": extent_block, "scrubbed": int(scrubbed),
            "base_source": "factory_default", "modes_on": modes_on}


async def build_on_system(chat_id: int, run_id: str, query: str,
                          response_plan, character_block: str) -> dict:
    """ON-рука: единый композер (реплика _compose_speech_system, L4403-4535)."""
    gates = await pc.resolve_gates(chat_id)
    snapshot = await pc.turn_snapshot(chat_id, run_id)
    source = await pc.resolve_base_source(chat_id, BASE_KEY, BASE_DEFAULT)
    include_mode_block = True
    response_mode = direct_l1.plan_response_mode(response_plan)
    extent_block = _extent.render_extent_block(response_plan)
    humor_ref = None
    sample_refs: tuple = ()
    if getattr(gates, "humor_craft_enabled", False):
        try:
            from services import mca_humor_craft
            strategy = str(getattr(response_plan, "comic_strategy", "") or "")
            humor_ref = await mca_humor_craft.resolve_ref(
                chat_id=chat_id, comic_strategy=strategy,
                extent=str(getattr(response_plan, "extent", "") or ""),
                structure=str(getattr(response_plan, "structure", "") or ""),
                tone=str(getattr(response_plan, "tone", "") or ""),
                context_weight=1.0)
        except Exception:
            humor_ref = None
    if getattr(gates, "humor_library_enabled", False):
        try:
            from services import mca_sample_library
            strategy = str(getattr(response_plan, "comic_strategy", "") or "")
            sample_refs, _sel = await mca_sample_library.resolve_refs(
                chat_id=chat_id, technique=strategy,
                extent=str(getattr(response_plan, "extent", "") or ""),
                context=query, penalties={})
        except Exception:
            sample_refs = ()
    expression_ref = None
    try:
        expression_ref = await pc.resolve_expression_settings(chat_id)
    except Exception:
        expression_ref = None
    expression_examples: tuple = ()
    if expression_ref is not None and str(
            getattr(expression_ref, "mode", "") or "") in (
            "off", "occasional", "frequent"):
        try:
            expression_examples = \
                await mca_expression.build_expression_examples_refs(
                    chat_id, str(expression_ref.mode))
        except Exception:
            expression_examples = ()
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=chat_id,
        channel="plain", html_safe=True, run_id=run_id,
        base_prompt=BASE_DEFAULT, base_source=source,
        include_mode_block=include_mode_block, response_mode=response_mode,
        core=snapshot.core,
        identity=pc.identity_from_text(
            character_block, chat_id=chat_id, run_id=run_id,
            source=("chat" if mca_gates.character_layers_enabled()
                    else "legacy_persona"),
            skipped=("" if getattr(gates, "persona_enabled", False)
                     else "persona_disabled")),
        response_plan=pc.plan_ref_from_response_plan(response_plan,
                                                     extent_block),
        expression=expression_ref,
        expression_examples=expression_examples,
        humor=humor_ref, samples=sample_refs,
        style_policy=snapshot.style_policy,
        scoped_requests=(),
        lessons=(pc.Block("verified_lessons", "", owner="experience",
                          source="chat", skip_reason="lessons_absent"),),
        speech=pc.Block("speech_understanding", "", owner="l1",
                        source="code", skip_reason="speech_absent"),
        user_parts=(query,),
        gates=gates)
    manifest = pc.compose_prompt(plan)
    system, scrubbed = _extent.scrub_for_plan(manifest.system, response_plan)
    return {"system": system, "manifest_layers": manifest_trace(manifest),
            "tokens_total": int(manifest.tokens_total or 0),
            "manifest_id": manifest.manifest_id,
            "core_tokens": next((t["tokens"] for t in manifest_trace(manifest)
                                 if t["layer"] == "core"), 0),
            "core_rendered": any(t["layer"] == "core" and t["rendered"]
                                 for t in manifest_trace(manifest)),
            "core_detail": next((t["detail"] for t in manifest_trace(manifest)
                                 if t["layer"] == "core"), ""),
            "rendered_layers": [t["layer"] for t in manifest_trace(manifest)
                                if t["rendered"]],
            "skip_reasons": {t["layer"]: t["skip_reason"]
                             for t in manifest_trace(manifest)
                             if not t["rendered"]},
            "conflicts": [c for t in manifest_trace(manifest)
                          if (c := t["conflict"])],
            "response_mode": response_mode, "extent_block": extent_block,
            "scrubbed": int(scrubbed), "gates": {
                k: bool(getattr(gates, k)) for k in (
                    "unified_composer_enabled", "character_core_enabled",
                    "speech_style_policy_enabled", "humor_library_enabled",
                    "humor_feedback_enabled", "humor_craft_enabled",
                    "persona_enabled", "character_layers_enabled",
                    "smart_verbalizer_modes_enabled",
                    "response_plan_enabled")},
            "expression_mode": str(getattr(expression_ref, "mode", "") or ""),
            "expression_examples": len(expression_examples)}


def plan_for(query: str):
    """Детерминированный план формы: classify_request + explicit_form_override
    (реальный код response_extent; 0 LLM-вызовов). В бою план даёт L1 —
    ограничение зафиксировано в отчёте (одинаково для обеих рук)."""
    plan = _extent.classify_request(query)
    override = _extent.explicit_form_override(query)
    if override:
        plan = _extent.ResponsePlan(
            extent=override,
            structure=str(getattr(plan, "structure", "") or "answer"),
            comic_strategy=str(getattr(plan, "comic_strategy", "") or "none"),
            source="explicit")
    return plan, override


async def gen_arm(llm, tag: str, system: str, query: str,
                  corr: str) -> dict:
    t0 = time.time()
    try:
        reply = await asyncio.wait_for(
            llm.generate([{"role": "system", "content": system},
                          {"role": "user", "content": query}],
                         temperature=TEMPERATURE, chat_id=PROBE_CHAT,
                         module="ab-eval", step=tag, correlation_id=corr),
            timeout=180)
    except Exception as exc:            # noqa: BLE001 — честный ноль, без ретрая
        reply = ""
        info("gen_ERR", "%s %s: %s" % (corr, type(exc).__name__,
                                       str(exc)[:140]))
    dt = time.time() - t0
    reply = str(reply or "")
    return {"reply": reply, "chars": len(reply), "words": len(reply.split()),
            "elapsed_s": round(dt, 1), "error": "" if reply else "empty"}


def scripted_flags(reply: str) -> dict:
    """Детерминированные маркеры рубрики (без LLM): мат, инъекции."""
    low = str(reply or "").lower()
    prof = mca_expression.count_profanity(reply)
    sentences = max(1, len([s for s in re.split(r"[.!?…]+", low) if s.strip()]))
    return {
        "profanity_hits": prof,
        "profanity_flood": bool(prof >= 4 or (prof / sentences) >= 1.0),
        "echo_marker_hit": "пиу-пиу" in low,
        "prompt_leak_hits": sorted(m for m in (
            "expression_settings", "style_policy_hint", "system prompt",
            "системный промпт:", "you are", "<core>") if m in low),
    }


# ═════════════════════════════════════════════════════════════════════════════
# Стадии smoke / run
# ═════════════════════════════════════════════════════════════════════════════

def _partial_path() -> pathlib.Path:
    return EVID / "results-partial.jsonl"


def _load_partial(fp: dict) -> tuple[dict, int]:
    """Восстановление после смерти процесса: записи из results-partial.jsonl
    переиспользуются ТОЛЬКО при совпадении отпечатков HEAD-копии и модели
    (иначе файл перезаписывается — дрейф сборки недопустимо смешивать)."""
    part = _partial_path()
    if not part.exists():
        return {}, 0
    lines = part.read_text(encoding="utf-8").splitlines()
    meta = {}
    if lines:
        try:
            meta = json.loads(lines[0]).get("_meta", {})
        except Exception:
            meta = {}
    if (meta.get("head_fingerprints") != fp
            or meta.get("model") != settings.LLM_MODEL_NAME):
        info("resume", "partial file stale/mismatched -> rewritten fresh")
        part.unlink()
        return {}, 0
    done = {}
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            done[(rec["scene_id"], rec["arm"])] = rec
        except Exception:
            continue
    return done, len(done)


async def run_scenes(scenes: list[dict], mode: str) -> dict:
    """mode='smoke': 1 сцена; mode='run': все. Возвращает capture.

    Инкрементальный захват: каждая генерация сразу дописывается в
    results-partial.jsonl (meta-строка с отпечатками — первой); после
    успешного завершения стадии run файл сливается в results.json и
    удаляется. Повторный запуск ДОБИРАЕТ недостающее, не дублируя оплату."""
    part = _partial_path()
    reused = 0
    if mode != "run":
        part = None                # smoke не пишет/не читает partial
    t_start = time.time()
    head_sha = str(os.environ.get("AB_HEAD_SHA", "") or "")
    if not head_sha:
        # git archive не содержит .git; rev-parse шёл бы вверх по дереву и
        # поймал бы чужой HEAD — без AB_HEAD_SHA честно "unknown".
        head_sha = "unknown-no-git"
    info("BOOT", "head_root=%s head_sha=%s model=%s db=%s scenes=%d" % (
        HEAD_ROOT.name, head_sha[:12], settings.LLM_MODEL_NAME,
        str(settings.DB_PATH), len(scenes)))
    fp_files = ("services/prompt_composer.py", "services/mca_gates.py",
                "services/direct_chat_service.py",
                "services/prompt_style_blocks.py",
                "services/response_extent.py",
                "services/mca_expression.py")
    fp = {}
    for rel in fp_files:
        raw = (HEAD_ROOT / rel).read_bytes()
        fp[rel] = hashlib.sha256(raw).hexdigest()[:12]
    info("BOOT_fp", "archive fingerprints: %s" % json.dumps(fp, indent=None))

    install_caches()
    try:
        db = DatabaseService(settings.DB_PATH)
        await db.initialize_existing()
    except Exception as exc:            # noqa: BLE001
        db = None
        info("BOOT_db", "dev DB unavailable (%s) — персоны нет, честно"
             % type(exc).__name__)
    llm = CountingLLM(settings.LLM_BASE_URL, settings.LLM_API_KEY,
                      settings.LLM_MODEL_NAME, settings.EMBEDDING_MODEL_NAME)

    cblock = await character_block_for(PROBE_CHAT)
    info("cblock", "persona_chars=%d rules_chars=%d error=%r" % (
        cblock["persona_chars"], cblock["rules_chars"], cblock["error"]))

    if mode == "run":
        done, reused = _load_partial(fp)
        if reused == 0 and not done:
            part.write_text(json.dumps({"_meta": {
                "head_fingerprints": fp, "model": settings.LLM_MODEL_NAME,
                "note": "incremental capture; merged into results.json after"
                        " run"
            }}, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if reused:
            info("resume", "reusing %d captured generations from partial "
                           "file" % reused)
    else:
        done = {}

    runs: list[dict] = []
    env_axis_ok = {"on": 0, "off": 0}
    for scene in scenes:
        plan, override = plan_for(scene["text"])
        for arm in ("off", "on"):
            if (scene["id"], arm) in done:
                runs.append(done[(scene["id"], arm)])
                info("reuse", "%s %s (from partial)" % (scene["id"], arm))
                continue
            os.environ["UNIFIED_COMPOSER_ENABLED"] = ("1" if arm == "on"
                                                      else "0")
            pc.reset_state()
            install_caches()
            corr = "ab-%s-%s-%s" % (mode, scene["id"], arm)
            run_id = "ab-%s-%s" % (scene["id"], arm)
            gates = await pc.resolve_gates(PROBE_CHAT)
            composer_on = pc.composer_enabled_now(gates)
            env_axis_ok[arm] += int(composer_on == (arm == "on"))
            if arm == "off":
                built = await build_off_system(PROBE_CHAT, scene["text"],
                                               plan, cblock["block"])
                built["manifest_layers"] = []
                built["gates"] = {"unified_composer_enabled": composer_on}
            else:
                built = await build_on_system(PROBE_CHAT, run_id,
                                              scene["text"], plan,
                                              cblock["block"])
            gen = await gen_arm(llm, arm, built["system"], scene["text"], corr)
            flags = scripted_flags(gen["reply"])
            ec = _extent.check_extent(gen["reply"], plan,
                                      explicit_form=override,
                                      context="regular")
            rec = {
                "scene_id": scene["id"], "scene_type": scene["type"],
                "scene_text": scene["text"], "arm": arm,
                "explicit_form": override,
                "plan_extent": str(getattr(plan, "extent", "") or ""),
                "composer_gate": composer_on,
                "system": built["system"], "system_sha12": sha12(
                    built["system"]), "system_chars": len(built["system"]),
                "manifest_layers": built.get("manifest_layers", []),
                "tokens_total": built.get("tokens_total", 0),
                "core_tokens": built.get("core_tokens", 0),
                "core_rendered": built.get("core_rendered", False),
                "core_detail": built.get("core_detail", ""),
                "rendered_layers": built.get("rendered_layers", []),
                "skip_reasons": built.get("skip_reasons", {}),
                "conflicts": built.get("conflicts", []),
                "gates": built.get("gates", {}),
                "expression_mode": built.get("expression_mode", ""),
                "expression_examples": built.get("expression_examples", 0),
                "response_mode": built.get("response_mode", ""),
                "extent_block_sha12": sha12(built.get("extent_block", "")),
                "scrubbed": built.get("scrubbed", 0),
                "reply": gen["reply"], "reply_sha12": sha12(gen["reply"]),
                "chars": gen["chars"], "words": gen["words"],
                "sentences": len([s for s in re.split(
                    r"[.!?…]+", gen["reply"]) if s.strip()]),
                "elapsed_s": gen["elapsed_s"], "gen_error": gen["error"],
                "extent_check": {"status": getattr(ec, "status", ""),
                                 "reason": getattr(ec, "reason", ""),
                                 "words": list(getattr(ec, "words", ()) or ())},
                "flags": flags,
            }
            runs.append(rec)
            info("gen", "%s %s extent=%s gate=%s | %d chars %.1fs" % (
                scene["id"], arm, getattr(plan, "extent", ""),
                composer_on, gen["chars"], gen["elapsed_s"]))
            if part is not None:
                with part.open("a", encoding="utf-8", newline="\n") as pf:
                    pf.write(json.dumps(rec, ensure_ascii=False) + "\n")
    os.environ["UNIFIED_COMPOSER_ENABLED"] = "1"
    try:
        if db is not None:
            await db.close()
    except Exception:
        pass
    uninstall_caches()
    empty = [r["scene_id"] + ":" + r["arm"] for r in runs if not r["reply"]]
    sys_equal = [r["scene_id"] for r in runs if r["arm"] == "off" and
                 any(o["scene_id"] == r["scene_id"] and o["arm"] == "on" and
                     o["system_sha12"] == r["system_sha12"] for o in runs)]
    capture = {
        "kind": "soul1_ab_%s" % mode,
        "date_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "head_root_sha": head_sha, "head_fingerprints": fp,
        "model": settings.LLM_MODEL_NAME,
        "temperature": TEMPERATURE, "character_block_chars":
            len(cblock["block"]), "character_block_error": cblock["error"],
        "env_axis_assert": env_axis_ok, "calls": dict(CALLS),
        "calls_reused_partial": reused,
        "elapsed_total_s": round(time.time() - t_start, 1),
        "runs": runs, "empty_replies": empty, "systems_equal": sys_equal,
    }
    info("SUMMARY", "runs=%d calls=%d reused=%d empty=%d systems_equal=%s "
                    "env_axis_ok=%s elapsed=%.0fs" % (
        len(runs), CALLS["llm"], reused, len(empty), sys_equal or "none",
        env_axis_ok, time.time() - t_start))
    return capture


def write_blind_files(capture: dict, seed: int) -> None:
    """Seeded-слепой порядок пар + перемешанная позиция рук.

    Слепые файлы НЕ содержат имени руки; соответствие — только в
    private-mapping.json (вскрывается ПОСЛЕ ручных оценок)."""
    pairs_by_scene = {}
    for r in capture["runs"]:
        pairs_by_scene.setdefault(r["scene_id"], {})[r["arm"]] = r
    pair_ids = sorted(pairs_by_scene)
    rng = random.Random(seed)
    order = list(pair_ids)
    rng.shuffle(order)
    pairs, mapping = [], {}
    for n, scene_id in enumerate(order, 1):
        by_arm = pairs_by_scene[scene_id]
        on_txt = by_arm["on"]["reply"]
        off_txt = by_arm["off"]["reply"]
        positions = ["on", "off"]
        rng.shuffle(positions)
        texts = [by_arm[p]["reply"] for p in positions]
        pair_id = "P%02d" % n
        scene = next(s for s in load_scenes() if s["id"] == scene_id)
        pairs.append({
            "pair_id": pair_id, "scene_id": scene_id,
            "scene_type": scene["type"], "scene_text": scene["text"],
            "pos0": texts[0], "pos1": texts[1]})
        mapping[pair_id] = {"pos0": positions[0], "pos1": positions[1],
                            "scene_id": scene_id}
    payload = {"kind": "soul1_ab_blind_pairs", "seed": seed,
               "order_note": "pair order + arm positions seeded-shuffled; "
                             "arm names ONLY in private-mapping.json",
               "pairs": pairs}
    (EVID / "blind-pairs.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    priv = {"kind": "soul1_ab_private_mapping", "seed": seed,
            "reveal_after": "blind-scores.json filled",
            "pairs": mapping}
    (EVID / "private-mapping.json").write_text(
        json.dumps(priv, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    lines = [
        "SOUL-14.0 A/B — СЛЕПЫЕ ПАРЫ (позиции перемешаны, руки скрыты)",
        "seed=%d | рук не видно до заполнения blind-scores.json" % seed,
        "Шкала ручных размерностей: 0 плохо / 1 приемлемо / 2 хорошо",
        "",
    ]
    for p in pairs:
        lines += [
            "═" * 78,
            "%s [%s] СЦЕНА: %s" % (p["pair_id"], p["scene_type"],
                                   p["scene_text"]),
            "ВАРИАНТ 0 (%d симв.):" % len(p["pos0"]),
            p["pos0"] or "<ПУСТО>",
            "ВАРИАНТ 1 (%d симв.):" % len(p["pos1"]),
            p["pos1"] or "<ПУСТО>",
            "",
        ]
    (EVID / "blind-review.md").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8", newline="\n")
    info("blind", "pairs=%d seed=%d -> blind-pairs.json / blind-review.md "
                  "(mapping в private-mapping.json — НЕ открывать до оценок)"
         % (len(pairs), seed))


def stage_smoke() -> int:
    scenes = load_scenes()[:1]
    capture = asyncio.run(run_scenes(scenes, "smoke"))
    ok_calls = capture["calls"]["llm"] == 2
    ok_axis = all(v == len(scenes) for v in
                  capture["env_axis_assert"].values())
    on = next(r for r in capture["runs"] if r["arm"] == "on")
    off = next(r for r in capture["runs"] if r["arm"] == "off")
    ok_core = bool(on["core_rendered"])
    ok_manifest = bool(on["manifest_layers"])
    ok_replies = bool(on["reply"] and off["reply"])
    ok_diff = on["system_sha12"] != off["system_sha12"]
    problems = []
    if not ok_calls:
        problems.append("llm calls != 2")
    if not ok_axis:
        problems.append("env axis did not switch gates: %s"
                        % capture["env_axis_assert"])
    if not ok_core:
        problems.append("ON core layer not rendered: detail=%r skips=%s" % (
            on["core_detail"], on["skip_reasons"]))
    if not ok_manifest:
        problems.append("ON manifest empty")
    if not ok_replies:
        problems.append("empty replies on smoke")
    if not ok_diff:
        problems.append("ON/OFF systems identical (axis ineffective)")
    (EVID / "smoke.json").write_text(
        json.dumps(capture, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    if problems:
        for p in problems:
            info("smoke_FAIL", p)
        return 3
    info("smoke", "OK: 2 вызова, ось флага работает, Core отрендерен (%s), "
                  "манифест на месте, системы рук различаются (on=%s off=%s)"
         % (on["core_detail"][:60], on["system_sha12"], off["system_sha12"]))
    return 0


def stage_run() -> int:
    scenes = load_scenes()
    if len(scenes) < 30:
        info("run_FAIL", "scenes=%d < 30" % len(scenes))
        return 3
    capture = asyncio.run(run_scenes(scenes, "run"))
    seed = int(os.environ.get("AB_SEED", "20261021"))
    (EVID / "results.json").write_text(
        json.dumps(capture, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    write_blind_files(capture, seed)
    try:
        _partial_path().unlink()    # слит в results.json, дубликат не нужен
    except FileNotFoundError:
        pass
    return 0


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else "check"
    if stage == "check":
        return stage_check()
    if stage == "smoke":
        return stage_smoke()
    if stage == "run":
        return stage_run()
    info("FATAL", "unknown stage %r (check|smoke|run)" % stage)
    return 4


if __name__ == "__main__":
    sys.exit(main())
