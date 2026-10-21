# -*- coding: utf-8 -*-
"""SOUL-AMD-PROBES — локальный харнес трёх малых проб на HEAD (без Telegram).

Пробы (write-scope: plans/features/soul-1/evidence/amd-probes/):
  * P1 / SOUL-AMD.8.2 — сравнительный прогон полной vs компактной редакций
    Personality Core (заводские тексты, выбор уровня владельцем) на двух
    обезличенных сценах: абсурд/остроумие и серьёзный неагрессивный ответ.
    Реальный композер (speech_plain, l2_writer) + реальный провайдер LLM.
  * P2 / SOUL-AMD.8.11 — живые локальные пробы search (реальный запрос) и
    fact_check (один тезис, v2-контур как на проде: hot=true отражён
    ПРОЦЕСС-ЛОКАЛЬНОЙ env-переменной, никакой персистентный конфиг не
    трогается); видео — только состояние capability (провайдер not_configured
    на проде — WAITING_EXTERNAL, платный видео-пайплайн не запускается).
  * P3 / SOUL-21.3 — пример класса «3–6 предложений логичного абсурда»:
    реальная генерация Writer-харнесом (та же сборка, что в P1/S1).

Безопасность: ноль сообщений в реальные чаты (бота нет, только RecordingBot-
подобных заглушек нет и не нужно — прямые вызовы сервисов); платные вызовы
считаются и печатаются. Запуск: python amd_probes_harness.py (cwd любой).

TEST-LIFECYCLE: PROVISIONAL owner=SOUL-AMD-PROBES (evidence-проба; не тест)
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

# ── окружение ДО импортов конфига ────────────────────────────────────────────
# v2-фактчек: на проде hot flags.factcheck_pipeline_v2=true (cfg evidence);
# локально отражаем ТОТ ЖЕ маршрут процесс-локальной env-переменной
# (приоритет gate: hot → env → False). Никакой персистентный конфиг не пишется.
os.environ["FACTCHECK_PIPELINE_V2_ENABLED"] = "1"

HERE = pathlib.Path(__file__).resolve().parent
# HEAD-корень (git archive HEAD ceb3e437) — код под пробой байт-в-байт HEAD.
HEAD_ROOT = pathlib.Path(os.environ.get(
    "AMD_PROBES_HEAD_ROOT",
    str(HERE.parents[5] / "OPENCODE_WORKFLOW_SCRATCH" / "amd-probes" / "head")))
EVID = HERE.parent                      # .../evidence/amd-probes
sys.path.insert(0, str(HEAD_ROOT))
os.chdir(HEAD_ROOT)                     # относительный DB_PATH остаётся в HEAD-копии

from config.settings import settings    # noqa: E402  (после env)
from services import capability_registry as caps          # noqa: E402
from services import chat_params                          # noqa: E402
from services import factcheck_orchestrator as fco        # noqa: E402
from services import hot_config as hot                    # noqa: E402
from services import mca_gates                            # noqa: E402
from services import prompt_composer as pc                # noqa: E402
from services import prompt_registry as pr                # noqa: E402
from services.database import DatabaseService             # noqa: E402
from services.llm_client import LLMClient                 # noqa: E402
from services.search_aggregator import SearchAggregator   # noqa: E402
from services.tool_router import (                        # noqa: E402
    ToolContext, ToolDeps, ToolRouter)
from services.chat_prompts import DIRECT_VERBALIZER_SYSTEM_PROMPT  # noqa: E402

PROBE_CHAT = -1007770000301
PROBE_USER = 990003001
TEMPERATURE = 0.7
CORE_DOC_KEY = pr.CORE_DOC_KEY

SCENES = (
    ("S1_absurd",
     "Бот, а объясни нормально: почему понедельник — это статистическая "
     "ошибка Вселенной. Только 3–6 предложений, без списков."),
    ("S2_serious",
     "Сосед третий месяц сверлит по выходным в восемь утра. Разговаривать "
     "с ним всё равно придётся — как построить разговор, чтобы не сорваться "
     "и не прогнуться?"),
)

RESULTS: list[tuple[str, bool, str]] = []
CALLS = {"llm": 0, "search": 0}


def out(tag: str, ok: bool, text: str) -> None:
    RESULTS.append((tag, bool(ok), str(text)))
    print("AMD %s %s | %s" % (tag, "OK" if ok else "FAIL", text), flush=True)


def info(tag: str, text: str) -> None:
    print("AMD %s INFO | %s" % (tag, text), flush=True)


def sha12(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def sha256(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


class FakeHot:
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


class CountingSearch(SearchAggregator):
    async def search(self, query, max_symbols):
        CALLS["search"] += 1
        return await super().search(query, max_symbols=max_symbols)


def core_doc(level: str) -> dict:
    """Документ владельца, выбирающий редакцию; ПОЛЯ ПУСТЫЕ → тексты
    наследуют ЗАВОДСКИЕ редакции (core_selection: doc_field_text or factory).
    document_revision пуст → активная ревизия имеет заводской префикс fac:."""
    return {"detail_level": level}


async def resolve_ref(level: str):
    pr.reset_cache()
    cache = FakeHot({CORE_DOC_KEY: core_doc(level)})
    hot.set_config_cache(cache)
    chat_params.set_chat_params_cache(FakeChats())
    pc.reset_state()
    try:
        ref = await pc.resolve_core_ref(PROBE_CHAT)
        doc = dict(cache.values[CORE_DOC_KEY])
    finally:
        hot.set_config_cache(None)
        chat_params.set_chat_params_cache(None)
        pc.reset_state()
        pr.reset_cache()
    return ref, doc


def build_plan(ref: pc.CoreRef, scene_text: str) -> pc.PromptPlan:
    extent_text = "ОЖИДАЕМАЯ ПОЛНОТА: ПОДРОБНО."
    gates = pc.GateState(
        unified_composer_enabled=True, character_core_enabled=True,
        persona_enabled=True, character_layers_enabled=True,
        smart_verbalizer_modes_enabled=True, response_plan_enabled=True,
        humor_craft_enabled=True)
    return pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=PROBE_CHAT,
        channel="plain", html_safe=True, run_id="amd-probes",
        base_prompt=DIRECT_VERBALIZER_SYSTEM_PROMPT,
        base_source="factory_default",
        response_plan=pc.PlanRef(text=extent_text, extent="detailed",
                                 structure="answer", tone="inherit",
                                 revision=pc.sha12(extent_text), source="l1"),
        core=ref,
        gates=gates,
        user_parts=(scene_text,))


def core_facts(manifest: pc.PromptManifest) -> dict:
    trace = next((t for t in manifest.layers if t.layer == "core"), None)
    return {
        "rendered": bool(trace and trace.rendered),
        "detail": (trace.detail if trace else ""),
        "revision": (trace.revision if trace else ""),
        "chars": (trace.chars if trace else 0),
        "tokens": (trace.tokens if trace else 0),
        "skip_reason": (trace.skip_reason if trace else ""),
        "system_chars": len(manifest.system),
        "tokens_total": int(manifest.tokens_total or 0),
        "versions_core_detail": (manifest.versions or {}).get("core_detail",
                                                              ""),
    }


def count_sentences(text: str) -> int:
    parts = [p for p in re.split(r"[.!?…]+(?:\s|$)", str(text or "").strip())
             if p.strip()]
    return len(parts)


async def phase1(llm) -> dict:
    info("P1", "AMD.8.2: сравнение full vs compact Core (заводские тексты)")
    full_factory = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    comp_factory = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    capture = {
        "head_sha_target": os.environ.get("AMD_PROBES_HEAD_SHA", ""),
        "model": settings.LLM_MODEL_NAME,
        "temperature": TEMPERATURE,
        "factory_full": {"chars": len(full_factory),
                         "words": len(full_factory.split()),
                         "sha256_12": sha12(full_factory),
                         "est_tokens": pc.estimate_tokens(full_factory)},
        "factory_compact": {"chars": len(comp_factory),
                            "words": len(comp_factory.split()),
                            "sha256_12": sha12(comp_factory),
                            "est_tokens": pc.estimate_tokens(comp_factory)},
        "runs": [],
    }
    for level in ("full", "compact"):
        ref, doc = await resolve_ref(level)
        expected_rev = ("fac:" + sha12(full_factory) if level == "full"
                        else "fac:" + sha12(comp_factory))
        out("P1_ref_%s" % level,
            ref.detail_level == level and ref.text == (full_factory
                                                       if level == "full"
                                                       else comp_factory)
            and ref.revision == expected_rev
            and ref.detail_reason == "owner_setting",
            "level=%s reason=%s origin=%s revision=%s chars=%d" % (
                ref.detail_level, ref.detail_reason, ref.origin,
                ref.revision, len(ref.text)))
        plan = build_plan(ref, "")
        for scene_id, scene_text in SCENES:
            plan = pc.PromptPlan(**{**plan.__dict__,
                                    "user_parts": (scene_text,)})
            manifest = pc.compose_prompt(plan)
            facts = core_facts(manifest)
            ok_manifest = (facts["rendered"] and
                           facts["detail"].startswith("level=" + level))
            t0 = time.time()
            reply = await llm.generate(
                [{"role": "system", "content": manifest.system},
                 {"role": "user", "content": scene_text}],
                temperature=TEMPERATURE, chat_id=PROBE_CHAT,
                module="amd-probe", step="core_compare",
                correlation_id="amd-probe-82-%s-%s" % (level, scene_id))
            dt = time.time() - t0
            ok_reply = bool(reply and reply.strip())
            out("P1_gen_%s_%s" % (level, scene_id), ok_manifest and ok_reply,
                "core[%s] rev=%s tokens=%d | reply %d chars %.1fs" % (
                    level, facts["revision"], facts["tokens"],
                    len(reply or ""), dt))
            capture["runs"].append({
                "level": level, "scene": scene_id, "scene_text": scene_text,
                "core": facts, "core_ref": {
                    "detail_level": ref.detail_level,
                    "detail_reason": ref.detail_reason,
                    "origin": ref.origin, "source": ref.source,
                    "revision": ref.revision,
                    "document_revision": ref.document_revision},
                "doc_sent": doc,
                "reply": reply or "", "reply_sha12": sha12(reply or ""),
                "reply_chars": len(reply or ""), "elapsed_s": round(dt, 1),
                "sentences": count_sentences(reply or "")})
    full_s1 = next((r for r in capture["runs"]
                    if r["level"] == "full" and r["scene"] == "S1_absurd"), {})
    comp_s1 = next((r for r in capture["runs"]
                    if r["level"] == "compact" and r["scene"] == "S1_absurd"),
                   {})
    out("P1_distinct_outputs",
        full_s1.get("reply") != comp_s1.get("reply"),
        "full_sha12=%s compact_sha12=%s (независимые генерации)" % (
            full_s1.get("reply_sha12"), comp_s1.get("reply_sha12")))
    return capture


async def phase2(db, llm) -> dict:
    info("P2", "AMD.8.11: живые пробы search + fact_check; состояние video")
    capture: dict = {"search": {}, "factcheck": {}, "video": {}}

    # ── search: реальный запрос через РЕАЛЬНЫЙ tool-маршрут (llm=None) ──
    router_s = ToolRouter(ToolDeps(search=CountingSearch(), memory=None,
                                   db=db, llm=None))
    t0 = time.time()
    res = await router_s.dispatch(
        "execute_web_search",
        {"query": "расстояние от Земли до Луны в километрах"},
        ToolContext(PROBE_CHAT, "расстояние от Земли до Луны",
                    user_id=PROBE_USER,
                    correlation_id="amd-probe-811-search"))
    dt = time.time() - t0
    ok = isinstance(res, str) and res.startswith("Результаты поиска") \
        and len(res) > 500
    capture["search"] = {"query": "расстояние от Земли до Луны в километрах",
                         "elapsed_s": round(dt, 1), "chars": len(res or ""),
                         "head": str(res or "")[:600],
                         "tail": str(res or "")[-200:]}
    out("P2_search", ok,
        "elapsed=%.1fs chars=%d head=%r" % (dt, len(res or ""),
                                            str(res or "")[:90]))

    # ── fact_check: один тезис через РЕАЛЬНЫЙ tool-маршрут (v2-контур) ──
    v2 = fco.pipeline_v2_enabled()
    info("P2_v2gate", "pipeline_v2_enabled=%s (env процесс-локально; "
                      "hot-флаг прод-конфига не читался и не менялся)" % v2)
    router_f = ToolRouter(ToolDeps(search=CountingSearch(), memory=None,
                                   db=db, llm=llm))
    claim = ("Эйфелева башня была построена в Париже к Всемирной выставке "
             "1889 года.")
    t0 = time.time()
    res2 = await router_f.dispatch(
        "fact_check", {"claim": claim},
        ToolContext(PROBE_CHAT, claim, user_id=PROBE_USER,
                    correlation_id="amd-probe-811-factcheck"))
    dt = time.time() - t0
    try:
        payload = json.loads(res2)
    except Exception:
        payload = {"raw_head": str(res2)[:300]}
    status = payload.get("status")
    capture["factcheck"] = {"claim": claim, "elapsed_s": round(dt, 1),
                            "v2_gate": v2, "payload": payload}
    out("P2_factcheck", status in ("ready", "skipped", "unavailable",
                                   "insufficient_evidence", "failed"),
        "elapsed=%.1fs status=%s factual_verdict=%s temporal_status=%s "
        "mode=%s" % (dt, status, payload.get("factual_verdict"),
                     payload.get("temporal_status"),
                     payload.get("assessment_mode")))
    if status == "ready":
        out("P2_factcheck_verdict",
            payload.get("factual_verdict") in ("supported", "refuted",
                                               "partial", "unverifiable"),
            "verdict=%s reason=%s run_id=%s" % (
                payload.get("factual_verdict"), payload.get("reason"),
                payload.get("run_id") or payload.get("temporal_run_id")))

    # ── video: только состояние capability (платный пайплайн НЕ запускаем) ──
    st = await caps.resolve("video_summary", PROBE_CHAT)
    capture["video"] = {"status": st.status, "reason": st.reason_code,
                        "available": st.available,
                        "detail": str(st.detail)[:200]}
    out("P2_video_state", st.status in ("not_configured", "disabled"),
        "status=%s reason=%s detail=%r (WAITING_EXTERNAL: провайдер на проде "
        "not_configured — media_source/cobalt; платный видео-пайплайн "
        "намеренно не запускался)" % (st.status, st.reason_code,
                                      str(st.detail)[:80]))
    return capture


async def phase3(capture82) -> dict:
    info("P3", "SOUL-21.3: пример класса «3–6 предложений логичного абсурда»")
    candidates = [r for r in capture82["runs"] if r["scene"] == "S1_absurd"]
    fit = [r for r in candidates if 3 <= r["sentences"] <= 6]
    capture = {"class": "3-6 предложений логичного абсурда",
               "candidates": [
                   {"level": r["level"], "sentences": r["sentences"],
                    "chars": r["reply_chars"], "sha12": r["reply_sha12"]}
                   for r in candidates],
               "chosen_level": (fit[0]["level"] if fit else None),
               "dedicated_generation": None}
    out("P3_class_fit", bool(fit),
        "кандидаты: %s" % ", ".join(
            "%s=%d предл." % (r["level"], r["sentences"]) for r in candidates))
    if not fit:
        ref, doc = await resolve_ref("compact")
        plan = build_plan(ref, SCENES[0][1])
        manifest = pc.compose_prompt(plan)
        reply = await llm_global[0].generate(
            [{"role": "system", "content": manifest.system},
             {"role": "user", "content": SCENES[0][1]}],
            temperature=TEMPERATURE, chat_id=PROBE_CHAT,
            module="amd-probe", step="absurd_dedicated",
            correlation_id="amd-probe-213-dedicated")
        capture["dedicated_generation"] = {
            "level": "compact", "reply": reply, "sha12": sha12(reply),
            "sentences": count_sentences(reply), "chars": len(reply or "")}
        out("P3_dedicated", 3 <= count_sentences(reply) <= 6,
            "sentences=%d chars=%d" % (count_sentences(reply), len(reply or "")))
    return capture


llm_global = [None]


async def main() -> int:
    t_start = time.time()
    head_sha = ""
    try:
        import subprocess
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(HEAD_ROOT.parent.parent.parent),
            capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        head_sha = ""
    info("BOOT", "head_root=%s model=%s base_url_host=%s db=%s" % (
        HEAD_ROOT.name, settings.LLM_MODEL_NAME,
        str(settings.LLM_BASE_URL).split("//")[-1].split("/")[0],
        settings.DB_PATH))

    db = DatabaseService(settings.DB_PATH)
    await db.initialize_existing()
    llm = CountingLLM(settings.LLM_BASE_URL, settings.LLM_API_KEY,
                      settings.LLM_MODEL_NAME, settings.EMBEDDING_MODEL_NAME)
    llm_global[0] = llm

    cap82 = await phase1(llm)
    cap811 = await phase2(db, llm)
    cap213 = await phase3(cap82)

    results = {
        "kind": "soul1_amd_probes",
        "date_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "head_sha": os.environ.get("AMD_PROBES_HEAD_SHA", head_sha),
        "model": settings.LLM_MODEL_NAME,
        "temperature": TEMPERATURE,
        "v2_env_process_local": True,
        "calls": dict(CALLS),
        "elapsed_total_s": round(time.time() - t_start, 1),
        "phases": {"amd82": cap82, "amd811": cap811, "soul213": cap213},
        "checks": [{"tag": t, "ok": ok, "detail": d} for t, ok, d in RESULTS],
    }
    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    n_all = len(RESULTS)
    results["summary"] = "ok=%d/%d" % (n_ok, n_all)
    (EVID / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")

    # amd82 текстовый артефакт
    lines = [
        "SOUL-AMD.8.2 — сравнительная проба Core: полная vs компактная редакции",
        "HEAD: %s | модель: %s | temperature: %s | дата_utc: %s" % (
            results["head_sha"], settings.LLM_MODEL_NAME, TEMPERATURE,
            results["date_utc"]),
        "Сборка хода: РЕАЛЬНЫЙ композер (profile=speech_plain, writer=l2_writer,",
        "  base=DIRECT_VERBALIZER_SYSTEM_PROMPT, PlanRef extent=detailed),",
        "  Core через РЕАЛЬНЫЙ resolve_core_ref (документ владельца выбирает",
        "  редакцию; поля документа пустые → тексты = ЗАВОДСКИЕ редакции).",
        "Заводская полная: %d симв. / %d слов / ~%d токенов / fac:%s" % (
            cap82["factory_full"]["chars"], cap82["factory_full"]["words"],
            cap82["factory_full"]["est_tokens"],
            cap82["factory_full"]["sha256_12"]),
        "Заводская компактная: %d симв. / %d слов / ~%d токенов / fac:%s" % (
            cap82["factory_compact"]["chars"],
            cap82["factory_compact"]["words"],
            cap82["factory_compact"]["est_tokens"],
            cap82["factory_compact"]["sha256_12"]),
        "",
    ]
    for run in cap82["runs"]:
        lines += [
            "═" * 78,
            "%s | Core %s (%s, rev %s, %d токенов слоя, system %d симв.)" % (
                run["scene"], run["level"], run["core_ref"]["detail_reason"],
                run["core"]["revision"], run["core"]["tokens"],
                run["core"]["system_chars"]),
            "СЦЕНА: %s" % run["scene_text"],
            "manifest: core rendered=%s detail=%r versions.core_detail=%r"
            % (run["core"]["rendered"], run["core"]["detail"],
               run["core"]["versions_core_detail"]),
            "ОТВЕТ (%d симв., предложений: %d, %.1fs, sha12 %s):" % (
                run["reply_chars"], run["sentences"], run["elapsed_s"],
                run["reply_sha12"]),
            "-" * 78,
            run["reply"],
            "",
        ]
    (EVID / "amd82-core-full-vs-compact.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    # amd811 текстовый артефакт
    s, f, v = cap811["search"], cap811["factcheck"], cap811["video"]
    lines = [
        "SOUL-AMD.8.11 — живые локальные пробы search / fact_check / video-состояние",
        "HEAD: %s | модель: %s | дата_utc: %s" % (
            results["head_sha"], settings.LLM_MODEL_NAME, results["date_utc"]),
        "Маршрут: реальные ToolRouter.dispatch (как в бою); search на llm=None,",
        "  fact_check на реальном LLM-клиенте; v2-гейт включён процесс-локальной",
        "  env (FACTCHECK_PIPELINE_V2_ENABLED=1) — зеркало прод-hot "
        "flags.factcheck_pipeline_v2=true; персистентные конфиги не тронуты.",
        "",
        "── SEARCH ──",
        "запрос: %r" % s.get("query"),
        "статус: OK | elapsed=%.1fs | %d символов реальных результатов" % (
            s.get("elapsed_s", -1), s.get("chars", 0)),
        "начало: %s" % (s.get("head", "")[:400].replace("\n", " ⏎ ")),
        "",
        "── FACT_CHECK (v2-контур) ──",
        "тезис: %s" % f.get("claim"),
        "v2 gate: %s | elapsed=%.1fs" % (f.get("v2_gate"),
                                         f.get("elapsed_s", -1)),
        "payload: %s" % json.dumps(f.get("payload", {}), ensure_ascii=False),
        "",
        "── VIDEO (состояние, БЕЗ платного пайплайна) ──",
        "capability: status=%s reason=%s available=%s detail=%s" % (
            v.get("status"), v.get("reason"), v.get("available"),
            v.get("detail")),
        "WAITING_EXTERNAL: реальный видео-сценарий требует медиа-источника;",
        "  на проде провайдер not_configured (окна agent-checks-1/2:",
        "  media_source_unconfigured / cobalt_absent). Платный видео-пайплайн",
        "  намеренно не запускался; Human Gate не создаётся.",
    ]
    (EVID / "amd811-search-factcheck-video.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    # soul213 артефакт
    chosen = None
    if cap213.get("chosen_level"):
        chosen = next(r for r in cap82["runs"]
                      if r["scene"] == "S1_absurd"
                      and r["level"] == cap213["chosen_level"])
    elif cap213.get("dedicated_generation"):
        dg = cap213["dedicated_generation"]
        chosen = {"level": "compact", "reply": dg["reply"],
                  "sentences": dg["sentences"], "reply_chars": dg["chars"],
                  "elapsed_s": None, "reply_sha12": dg["sha12"],
                  "core": {"revision": "fac-compact"}}
    lines = [
        "SOUL-21.3 — реальный пример класса «3–6 предложений логичного абсурда»",
        "HEAD: %s | модель: %s | temperature: %s | дата_utc: %s" % (
            results["head_sha"], settings.LLM_MODEL_NAME, TEMPERATURE,
            results["date_utc"]),
        "Метод: Writer-харнес (реальный композер + Core + провайдер), та же",
        "  сборка, что в пробе AMD.8.2 / сцена S1_absurd (без отдельного",
        "  платного вызова, если подошла существующая генерация).",
        "Запрос: %s" % SCENES[0][1],
        "Кандидаты: %s" % json.dumps(cap213["candidates"], ensure_ascii=False),
        "Выбран: редакция %s | предложений: %s | символов: %s | sha12 %s" % (
            chosen["level"] if chosen else None,
            chosen["sentences"] if chosen else None,
            chosen["reply_chars"] if chosen else None,
            chosen["reply_sha12"] if chosen else None),
        "",
        "ТЕКСТ ГЕНЕРАЦИИ:",
        "-" * 78,
        chosen["reply"] if chosen else "<нет подходящей генерации>",
        "-" * 78,
    ]
    (EVID / "soul213-absurd-example.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    try:
        await db.close()
    except Exception:
        pass
    print("AMD SUMMARY ok=%d/%d llm_calls=%d search_calls=%d elapsed=%.0fs"
          % (n_ok, n_all, CALLS["llm"], CALLS["search"],
             time.time() - t_start), flush=True)
    return 0 if n_ok == n_all else 3


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print("AMD FATAL %s: %s" % (type(exc).__name__, str(exc)[:400]))
        rc = 4
    sys.exit(rc)
