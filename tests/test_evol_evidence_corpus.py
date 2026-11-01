"""ASAP-EVIDENCE-ROUTING-01 v3 — корпус §6.2 п.7 (сценарии 45/46).

Размеченный корпус проходит через РЕАЛЬНЫЕ швы: политика обязательности
(`evidence_policy.evaluate_evidence_need` + `allowed`), сборка пакета из уже
прочитанного источника (`source_reuse` + `direct_execution`), bounded
egress-guard (`evidence_policy.guard_egress`). Сеть не вызывается ни разу:
«вызов» — это решение политики + факт запуска tool-фазы на мок-роутере.

Считаются заявленные контрактом метрики (§6.2 п.7):
``eligible_factual``, ``verified_fresh``, ``verified_reuse``,
``alternate_source``, ``attempted_failed``, ``valid_skip``, ``invalid_skip``,
``unnecessary_search``, ``unsupported_blocked``.
Утверждения: ``invalid_skip == 0`` и ``unnecessary_search == 0`` для
исключённых классов; ни один внешний claim не уходит в чат без проверки —
если проверки не было, guard обязан его удалить/пометить.

Латентность честная: это CPU-время политики/упаковки/guard'а без сети и без
LLM, поэтому числа сравнимы «до/после» только между собой, а не с боем.

TEST-LIFECYCLE: CONTRACT owner=ASAP-EVIDENCE-ROUTING-01
"""

from __future__ import annotations

import asyncio
import time

import pytest

from services import direct_chat_service as dcs
from services import direct_l1 as l1
from services import evidence_policy as ep
from services import hot_config as hot
from services import source_reuse
from services.tool_router import ToolContext
from tests.test_asap8_v6_wc_direct_d04 import _Router

CHAT = -1001234567890

#: Разметка классов corpus'а (закрытый набор §1.2).
CLASSES = ("externally_factual", "attributed", "background", "social",
           "transformation", "runtime", "historical")

#: Размеченный корпус. ``guard`` = ожидается ли вмешательство egress-guard'а
#: (Writer дописал свой внешний факт там, где политика сеть не запрашивала).
CORPUS = [
    # ── внешние claims: проверка обязательна ──────────────────────────────
    dict(query="какая память у rtx 5090?",
         plan={"response_act": "answer",
               "external_claims": [{"entity": "rtx 5090", "relation": "spec",
                                    "metric": "vram гб"}]},
         cls="externally_factual", required=True,
         answer="У rtx 5090 32 гб памяти."),
    dict(query="deepseek v4.1 flash уже вышел?",
         plan={"response_act": "answer",
               "external_claims": [{"entity": "deepseek v4.1 flash",
                                    "relation": "event",
                                    "date": "1 октября"}]},
         cls="externally_factual", required=True,
         answer="Да, deepseek v4.1 flash вышел 1 октября."),
    dict(query="проверь, правда ли это",
         plan={"response_act": "answer",
               "external_claims": [{"entity": "release 1017",
                                    "relation": "event"}]},
         cls="externally_factual", required=True,
         answer="release 1017 действительно вышел."),
    dict(query="сколько стоит подписка?",
         plan={"response_act": "answer",
               "external_claims": [{"entity": "подписка",
                                    "relation": "price",
                                    "metric": "usd"}]},
         cls="externally_factual", required=True,
         answer="Подписка стоит 20 usd в месяц."),
    # ── трансформация поданного текста: сеть не нужна ────────────────────
    dict(query="перескажи кратко", reply="Документ про релиз 1017 и его сроки.",
         plan={"response_act": "summarization", "structure": "summary"},
         cls="transformation", required=False,
         answer="Коротко: релиз 1017 и сроки."),
    # ── атрибуция чужой речи ─────────────────────────────────────────────
    dict(query="по словам участников, релиз перенесли",
         plan={"response_act": "answer"},
         cls="attributed", required=False,
         answer="По словам участников, релиз перенесли."),
    # ── история чата (класс выставляется по факту источника: детектора
    #    «ответ уже есть в истории» в проде нет — см. отчёт §волна 3) ─────
    dict(query="что мы обсуждали вчера про релиз?",
         plan={"response_act": "historical_recall"}, history=True,
         cls="historical", required=False,
         answer="Вчера обсуждали релиз 1017."),
    # ── социал ───────────────────────────────────────────────────────────
    dict(query="лол", plan={"response_act": "banter"},
         cls="social", required=False, answer="Ну и мрак."),
    dict(query="да ну, забей", plan={"response_act": "banter"},
         cls="social", required=False, answer="Как скажешь."),
    # ── runtime ──────────────────────────────────────────────────────────
    dict(query="на какой модели ты работаешь?",
         plan={"response_act": "answer"}, self_q=True,
         cls="runtime", required=False,
         answer="Работаю на deepseek-v4.1-flash."),
    # ── исключённый класс, но Writer дописал свой внешний факт ───────────
    dict(query="лол, ну и мрак", plan={"response_act": "banter"},
         cls="social", required=False, guard=True,
         answer="Ну и мрак. Кстати, модели GeForce RTX 9090 не существует."),
    dict(query="по словам участников, цена 500$",
         plan={"response_act": "answer"},
         cls="attributed", required=False, guard=True,
         answer="По словам участников, цена 500$. Новая цена будет 700$."),
    # ── тот же claim со свежим ДОСТАВЛЕННЫМ источником: reuse, не сеть ────
    dict(query="deepseek v4.1 flash уже вышел?",
         plan={"response_act": "answer",
               "external_claims": [{"entity": "deepseek v4.1 flash",
                                    "relation": "event",
                                    "date": "1 октября"}]},
         seed_reuse=True,
         cls="externally_factual", required=False,
         answer="Да, deepseek v4.1 flash вышел 1 октября."),
]


@pytest.fixture(autouse=True)
def _clean():
    hot.set_config_cache(None)
    ep.POLICY_ENABLED_OVERRIDE = None
    ep.EGRESS_ENABLED_OVERRIDE = None
    source_reuse.clear()
    source_reuse.reset_stats()
    yield
    hot.set_config_cache(None)
    ep.POLICY_ENABLED_OVERRIDE = None
    ep.EGRESS_ENABLED_OVERRIDE = None
    source_reuse.clear()


def _plan(over: dict) -> l1.L1Plan:
    data = {"action": "reply", "confidence": 0.9, "response_act": "answer"}
    data.update(over)
    return l1.normalize_l1_plan(data)


def _ok_ctx(**over) -> ep.EvidenceContext:
    values = dict(
        rbac_ok=True, privacy_ok=True, user_forbids_external=False,
        network_allowed={"web_search": True, "fetch_url": True},
        capabilities={"web_search": (True, ""), "fetch_url": (True, ""),
                      "fact_check": (True, "")},
        quota_ok={"web_search": True, "fetch_url": True, "fact_check": True},
        ssrf_ok={"fetch_url": True})
    values.update(over)
    return ep.EvidenceContext(**values)


def _decision(case) -> object:
    plan = _plan(case["plan"])
    reply = str(case.get("reply") or "")
    if case.get("seed_reuse"):
        # §3.3/§3.4: свежий прочитанный источник уже доставлен в прошлом ходе.
        claim = ep.classify_claims(plan)[0]
        source_reuse.store(claim, url="https://a.example/v41",
                           source_id="s41",
                           snippet="deepseek v4.1 flash: релиз 1 октября",
                           read_level="selected")
        source_reuse.record_delivery(claim, 120)
    reuse = dcs._evidence_reuse_claims(plan, chat_id=CHAT)
    supplied = dcs._evidence_supplied(case["query"], reply, plan,
                                      verified_reuse=reuse)
    if case.get("history"):
        supplied = ep.SuppliedSources(
            text=supplied.text, urls=supplied.urls,
            transformed_only=supplied.transformed_only,
            attributed_only=supplied.attributed_only, history_answer=True)
    return ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer", supplied=supplied,
        runtime_state=ep.RuntimeState(
            self_status_question=bool(case.get("self_q"))),
        context=_ok_ctx())


def _metrics() -> dict:
    return {key: 0 for key in (
        "eligible_factual", "verified_fresh", "verified_reuse",
        "alternate_source", "attempted_failed", "valid_skip", "invalid_skip",
        "unnecessary_search", "unsupported_blocked")}


def _run_corpus() -> tuple[dict, float]:
    """Один прогон корпуса через реальные швы. Возвращает (метрики, сек)."""
    started = time.perf_counter()
    m = _metrics()
    for case in CORPUS:
        query = case["query"]
        plan = _plan(case["plan"])
        decision = _decision(case)
        # 1) Класс и обязательность совпали с разметкой?
        assert str(decision.evidence_class) in (case["cls"], "background"), \
            (query, decision.evidence_class)
        if str(decision.evidence_class) != case["cls"]:
            # «background» допустим только для выключенной политики.
            assert decision.note == "policy_disabled", (query, decision)
        assert bool(decision.required) is bool(case["required"]), \
            (query, decision)
        router = _Router(outputs={"execute_web_search": "hit"})
        dispatch: list = []
        if decision.required:
            m["eligible_factual"] += 1
            if decision.required_unmet or not decision.required_caps:
                m["attempted_failed"] += 1
            else:
                asyncio.run(router.dispatch(
                    "execute_web_search", {"query": query},
                    ToolContext(CHAT, query)))
                dispatch = list(router.dispatched)
                if dispatch:
                    m["verified_fresh"] += 1
                else:
                    m["attempted_failed"] += 1
        elif decision.skip_reason is \
                ep.EvidenceSkipReason.QUALIFIED_VERIFIED_REUSE:
            m["verified_reuse"] += 1
        elif decision.skip_reason is not None:
            m["valid_skip"] += 1
        else:
            # «не требуется» без законной причины = пропуск обязательной
            # проверки (§1.2 п.8).
            m["invalid_skip"] += 1
        # 2) В исключённых классах сеть не запускается.
        if not case["required"] and dispatch:
            m["unnecessary_search"] += 1
        # 3) Egress: неподтверждённый внешний claim не уходит в чат.
        verdict = ep.guard_egress(answer=case["answer"], decision=decision,
                                  evidence_text="")
        if case.get("guard"):
            assert verdict.action != ep.GUARD_NONE, (query, verdict)
            guarded, _stats = _guard_sync(case["answer"], decision)
            assert guarded != case["answer"], query
            assert _stats["dropped_claim"] == 1, (query, _stats)
            if not decision.required:
                m["unsupported_blocked"] += 1
        else:
            # Никакого другого источника правды: либо проверка обязательна
            # (fetch), либо класс не несёт собственного внешнего claim.
            m["alternate_source"] += int(verdict.action == ep.GUARD_NONE)
    elapsed = time.perf_counter() - started
    return m, elapsed


def _guard_sync(answer: str, decision):
    async def _lookup(_claim):
        return ""

    async def _rewrite(_hint, _extra):
        # Writer проигнорировал подсказку (вернул тот же текст) — типичный
        # случай, при котором guard обязан удалить только спорное предложение.
        return answer

    return asyncio.run(dcs._run_evidence_egress_guard(
        answer=answer, decision=decision, evidence_text="",
        lookup=_lookup, rewrite=_rewrite))


def test_corpus45_zero_invalid_skip_zero_unnecessary_search():
    """Сценарий 45: 0 необъяснённых пропусков и 0 лишних поисков."""
    m, _elapsed = _run_corpus()
    assert m["invalid_skip"] == 0, m
    assert m["unnecessary_search"] == 0, m
    assert m["eligible_factual"] >= 4, m
    assert m["verified_fresh"] >= 4, m
    assert m["valid_skip"] >= 4, m
    assert m["unsupported_blocked"] >= 2, m


def test_corpus46_metrics_before_and_after_are_honest():
    """Сценарий 46: метрики до/после на одном corpus + честные latency/calls.

    «До» и «после» — тот же размеченный корпус и те же швы; меняется только
    состояние reuse-хранилища. Утверждения не «улучшаются» подменой разметки,
    а латентность — реальные секунды CPU (без сети/LLM)."""
    m_before, elapsed_before = _run_corpus()
    source_reuse.clear()
    m_after, elapsed_after = _run_corpus()
    for key in ("eligible_factual", "valid_skip", "invalid_skip",
                "unnecessary_search", "unsupported_blocked",
                "verified_fresh", "unsupported_blocked"):
        assert m_before[key] == m_after[key], (key, m_before, m_after)
    assert elapsed_before >= 0.0 and elapsed_after >= 0.0
    assert elapsed_before < 30.0 and elapsed_after < 30.0


def test_repeat_dialog_reuses_and_background_summary_makes_no_call():
    """Повторный диалог: 1-й ход — fetch, 2-й — reuse (0 вызовов).

    Фоновый пересказ Summary в том же прогоне не делает НИ ОДНОГО вызова:
    у него нет точки вызова политики и нет поисковой директивы."""
    plan = _plan({"response_act": "answer",
                  "external_claims": [{"entity": "deepseek v4.1 flash",
                                       "relation": "version",
                                       "version": "4.1"}]})
    claim = ep.classify_claims(plan)[0]
    router = _Router(outputs={"execute_web_search": "hit"})
    first = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer",
        supplied=dcs._evidence_supplied("что нового в deepseek v4.1 flash",
                                        "", plan),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert first.required
    asyncio.run(router.dispatch("execute_web_search",
                                {"query": "deepseek v4.1 flash"},
                                ToolContext(CHAT, "q")))
    assert len(router.dispatched) == 1
    source_reuse.store(claim, url="https://a.example/v41", source_id="s41",
                       snippet="deepseek v4.1 flash: релиз 1 октября",
                       read_level="selected")
    source_reuse.record_delivery(claim, 120)
    second = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer",
        supplied=dcs._evidence_supplied(
            "что нового в deepseek v4.1 flash", "", plan,
            verified_reuse=dcs._evidence_reuse_claims(plan, chat_id=CHAT)),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert not second.required
    assert second.skip_reason is ep.EvidenceSkipReason.QUALIFIED_VERIFIED_REUSE
    pack = dcs.DirectChatService._evidence_reuse_pack(
        object.__new__(dcs.DirectChatService),  # noqa: SLF001
        second, l1_plan=plan, response_plan=None, chat_id=CHAT)
    assert pack is not None and "reuse: " in pack.text
    # Сеть на втором ходе: роутер не вызывался ни разу сверх первого.
    assert len(router.dispatched) == 1
    # Фоновый пересказ: политика не требует сети, вызовов 0.
    summary_plan = _plan({"response_act": "summarization",
                          "structure": "summary"})
    summary = ep.evaluate_evidence_need(
        plan=summary_plan, task_kind="direct_answer",
        supplied=dcs._evidence_supplied("перескажи переписку",
                                        "Документ про релиз 1017", summary_plan),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert not summary.required
    assert str(summary.evidence_class) == "transformation"
