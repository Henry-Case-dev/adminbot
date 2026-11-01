"""ASAP-EVIDENCE-ROUTING-01 v3 — контрактные тесты runtime evidence policy.

Offline: без сети, без живых провайдеров, без Telegram-публикаций. Мокаются
существующие швы (`ToolRouter.dispatch`, Writer/LLM, capability-состояния),
реальные остаются: политика (`services/evidence_policy`), merge capability
(`_l1_tool_subset`), mode-резолв и деривация шагов (`direct_execution`),
egress-guard (choke-point `direct_chat_service`).

Покрытие сценариев ТЗ (46-матрица): 1, 4, 5, 6, 7, 8, 11, 12, 14, 15, 16,
19, 23, 24, 28, 29, 30, 31, 32, 33, 41, 45 — плюс C1–C4 из §0.2 контракта.

TEST-LIFECYCLE: CONTRACT owner=ASAP-EVIDENCE-ROUTING-01
Каждый тест привязан к сценарию/поправке; investigation-only артефактов нет.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from services import direct_capabilities as dc
from services import direct_chat_service as dcs
from services import direct_execution as dx
from services import direct_l1 as l1
from services import evidence_policy as ep
from services import hot_config as hot
from services import mca_events
from services.tool_router import ToolContext
from tests.test_asap8_v6_wc_direct_d04 import _Router

CHAT = -1001234567890


@pytest.fixture(autouse=True)
def _clean_state():
    hot.set_config_cache(None)
    ep.POLICY_ENABLED_OVERRIDE = None
    ep.EGRESS_ENABLED_OVERRIDE = None
    yield
    hot.set_config_cache(None)
    ep.POLICY_ENABLED_OVERRIDE = None
    ep.EGRESS_ENABLED_OVERRIDE = None


def _plan(**over) -> l1.L1Plan:
    data = {"action": "reply", "confidence": 0.9, "response_act": "answer"}
    data.update(over)
    return l1.normalize_l1_plan(data)


def _service(router=None, llm=None) -> dcs.DirectChatService:
    svc = object.__new__(dcs.DirectChatService)
    svc.tool_router = router
    svc.llm = llm
    svc.db = None
    return svc


def _ctx(query: str = "вопрос") -> ToolContext:
    return ToolContext(CHAT, query)


def _ok_ctx(**over) -> ep.EvidenceContext:
    """Разрешения, при которых read-only проверка технически возможна."""
    values = dict(
        rbac_ok=True, privacy_ok=True, user_forbids_external=False,
        network_allowed={"web_search": True, "fetch_url": True},
        capabilities={"web_search": (True, ""), "fetch_url": (True, ""),
                      "fact_check": (True, "")},
        quota_ok={"web_search": True, "fetch_url": True, "fact_check": True},
        ssrf_ok={"fetch_url": True})
    values.update(over)
    return ep.EvidenceContext(**values)


async def _permissive_context(chat_id, required_caps=(), *, user_forbids=False):
    return _ok_ctx(user_forbids_external=bool(user_forbids))


# ── закрытые перечисления и привязка к существующим reason_code ─────────────


def test_enums_closed_and_mapped_to_existing_reason_codes():
    """§1.4: ровно 12 skip-причин и 8 failure-кодов; конвертация одна.

    `capability_not_ready` — существующий код Л1-слоя
    (`direct_capabilities.REASON_NOT_READY`), а не новое значение словаря
    mca_events (санкция — ровно +3 кода)."""
    assert len(list(ep.EvidenceSkipReason)) == 12
    assert len(list(ep.EvidenceFailureCode)) == 8
    for reason in ep.EvidenceSkipReason:
        assert ep.skip_reason_code(reason) in mca_events.REASON_CODES
    for code in ep.EvidenceFailureCode:
        mapped = ep.failure_reason_code(code)
        assert (mapped in mca_events.REASON_CODES
                or mapped == dc.REASON_NOT_READY), code
    assert ep.failure_reason_code(
        ep.EvidenceFailureCode.CAPABILITY_NOT_READY) == dc.REASON_NOT_READY
    assert ep.skip_reason_code(
        ep.EvidenceSkipReason.SUFFICIENT_CHAT_HISTORY_SOURCE,
        found=False) == "no_relevant_memory"
    assert ep.skip_reason_code(
        ep.EvidenceSkipReason.QUALIFIED_VERIFIED_REUSE) == "exact_match_used"


def test_exactly_three_new_reason_codes_added():
    """§1.4: аддитивно ровно три кода, второго словаря нет."""
    for code in (ep.REASON_EVIDENCE_SKIPPED, ep.REASON_EVIDENCE_REUSED,
                 ep.REASON_EVIDENCE_CLAIM_REMOVED):
        assert code in mca_events.REASON_CODES
    assert ep.REASON_EVIDENCE_SKIPPED == "evidence_skipped"
    assert ep.REASON_EVIDENCE_REUSED == "evidence_reused"
    assert ep.REASON_EVIDENCE_CLAIM_REMOVED == \
        "evidence_unverified_claim_removed"


# ── C1: execution_mode=none не скрывает обязательную проверку ───────────────


def test_c1_execution_mode_none_overridden_by_required_caps():
    """Сценарий 6 + C1: mode `none` из L1-плана не отменяет проверку."""
    plan = _plan(execution_mode="none", capabilities_needed=[],
                 tool_policy="none")
    schemas = [{"function": {"name": "execute_web_search"}}]
    mode, reason = dx.resolve_execution_mode(plan, schemas)
    assert mode == dx.EXECUTION_NONE                     # прежнее поведение
    mode, reason = dx.resolve_execution_mode(
        plan, schemas, required_caps=("web_search",))
    assert (mode, reason) == (dx.EXECUTION_SIMPLE,
                              dx.REASON_EVIDENCE_REQUIRED)


def test_c1_required_caps_derive_steps_with_empty_l1_plan():
    """§2.1: пустой L1-план + required → шаг web_search деривируется."""
    plan = _plan(execution_mode="none", capabilities_needed=[],
                 tool_policy="none")
    steps, limitations = dx.derive_simple_steps(
        plan, query="Radeon RX 9090 характеристики",
        announced={"execute_web_search"})
    assert steps == []
    steps, _ = dx.derive_simple_steps(
        plan, query="Radeon RX 9090 характеристики",
        announced={"execute_web_search"}, required_caps=("web_search",))
    assert [s["tool"] for s in steps] == ["execute_web_search"]


# ── Сценарий 1/5: low confidence не снимает обязательную проверку ──────────


@pytest.mark.asyncio
async def test_scenario1_explicit_search_low_confidence_still_calls_tool():
    """Сценарий 1: «погугли» + low confidence → Search реально вызван."""
    query = "погугли, какая сейчас версия DeepSeek"
    plan = _plan(confidence=0.2, capabilities_needed=["web_search"],
                 execution_mode="none")
    assert plan.confidence_bucket == "low"
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="social_chat",
        explicit=dcs._evidence_explicit_request(query),
        supplied=dcs._evidence_supplied(query, "", plan),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert decision.required and decision.explicit_request
    assert decision.required_caps == ("web_search",)
    router = _Router(outputs={"execute_web_search": "DeepSeek V4.1 Flash"})
    svc = _service(router)
    schemas, rejected = await svc._l1_tool_subset(
        CHAT, "run-s1", True, False, plan, decision=decision)
    assert [t["function"]["name"] for t in schemas] == ["execute_web_search"]
    assert (("web_search", dc.REASON_LOW_CONFIDENCE) not in rejected)
    result = await svc._l1_tool_phase(
        None, _ctx(query), query=query, lore_enabled=True,
        image_enabled=False, temperature=None, chat_id=CHAT,
        correlation_id="run-s1", l1_plan=plan, response_plan=None,
        fallback_meta={}, time_line="", tool_schemas=schemas,
        required_caps=decision.required_caps)
    assert result is not None
    assert [d["tool"] for d in router.dispatched] == ["execute_web_search"]


@pytest.mark.asyncio
async def test_scenario5_low_confidence_skip_cannot_remove_capability():
    """Сценарий 5 / C2: skip (low_confidence) — только для L1-запрошенных,
    runtime_required защищён и не помечается low_confidence."""
    plan = _plan(confidence=0.1, capabilities_needed=["health"])
    decision = ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual",
                                   required_caps=("web_search",))
    router = _Router()
    svc = _service(router)
    schemas, rejected = await svc._l1_tool_subset(
        CHAT, "run-s5", True, False, plan, decision=decision)
    names = {t["function"]["name"] for t in schemas}
    assert "execute_web_search" in names
    assert ("health", dc.REASON_LOW_CONFIDENCE) in rejected
    assert ("web_search", dc.REASON_LOW_CONFIDENCE) not in rejected


# ── Сценарий 4: технический claim без «погугли» → runtime evidence ─────────


@pytest.mark.asyncio
async def test_scenario4_technical_question_without_marker_requires_evidence():
    """Сценарий 4: capabilities=[], tool_policy=none, confidence=high,
    execution_mode=none → обязательная runtime-проверка исполняется."""
    plan = _plan(response_act="answer", capabilities_needed=[],
                 tool_policy="none", execution_mode="none")
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer",
        supplied=ep.SuppliedSources(), runtime_state=ep.RuntimeState(),
        context=_ok_ctx())
    assert decision.required and not decision.required_unmet
    assert decision.required_caps == ("web_search",)
    router = _Router(outputs={"execute_web_search": "официально 5 ГБ"})
    svc = _service(router)
    schemas, _ = await svc._l1_tool_subset(
        CHAT, "run-s4", True, False, plan, decision=decision)
    result = await svc._l1_tool_phase(
        None, _ctx(), query="у новой карты официально 5 ГБ видеопамяти?",
        lore_enabled=True, image_enabled=False, temperature=None,
        chat_id=CHAT, correlation_id="run-s4", l1_plan=plan,
        response_plan=None, fallback_meta={}, time_line="",
        tool_schemas=schemas, required_caps=decision.required_caps)
    assert result is not None
    assert [d["tool"] for d in router.dispatched] == ["execute_web_search"]


# ── Сценарии 11/12/14: социальное и атрибуция — ноль внешних вызовов ──────


@pytest.mark.asyncio
async def test_scenario11_social_turn_makes_no_tool_calls():
    """Сценарий 11: «лол»/приветствие → 0 внешних вызовов."""
    plan = _plan(response_act="banter")
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="social_chat",
        supplied=ep.SuppliedSources(), runtime_state=ep.RuntimeState(),
        context=_ok_ctx())
    assert not decision.required
    assert decision.skip_reason is ep.EvidenceSkipReason.PURE_SOCIAL_OR_CREATIVE
    router = _Router()
    svc = _service(router)
    schemas, _ = await svc._l1_tool_subset(
        CHAT, "run-s11", True, False, plan, decision=decision)
    assert schemas == []
    result = await svc._l1_tool_phase(
        None, _ctx("лол"), query="лол", lore_enabled=True,
        image_enabled=False, temperature=None, chat_id=CHAT,
        correlation_id="run-s11", l1_plan=plan, response_plan=None,
        fallback_meta={}, time_line="", tool_schemas=schemas)
    assert result is None
    assert router.dispatched == []


@pytest.mark.asyncio
async def test_scenario12_technical_topic_with_sarcasm_makes_no_calls():
    """Сценарий 12: разговор о GPU, ответ сарказмом → веб не запускается."""
    plan = _plan(response_act="banter", capabilities_needed=[])
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="social_chat",
        explicit=ep.ExplicitRequest(search=False),
        supplied=ep.SuppliedSources(), runtime_state=ep.RuntimeState(),
        context=_ok_ctx())
    assert not decision.required
    assert decision.required_caps == ()


def test_scenario14_attributed_retelling_is_not_forced_to_search():
    """Сценарий 14: «Лёха говорил, что у X 5 ГБ» — не новый claim бота."""
    query = "Лёха говорил, что у него 5 ГБ видеопамяти"
    plan = _plan(response_act="answer")
    supplied = dcs._evidence_supplied(query, "", plan)
    assert supplied.attributed_only is True
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer", supplied=supplied,
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert not decision.required
    assert decision.evidence_class == "attributed"
    assert decision.skip_reason is \
        ep.EvidenceSkipReason.ATTRIBUTED_HISTORY_OR_SUMMARY


def test_scenario15_new_external_claim_requires_check_even_with_joke():
    """Сценарий 15: «У X официально 5 ГБ» как новый claim → проверка
    обязательна, даже если форма шутливая."""
    plan = _plan(
        response_act="banter",
        external_claims=[{"entity": "iphone 18", "relation": "event",
                          "date": "2027"}])
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="social_chat", supplied=ep.SuppliedSources(),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert decision.required
    assert decision.evidence_class == "externally_factual"
    assert decision.claims and decision.claims[0].version == "" \
        or decision.claims[0].date == "2027"


def test_external_claims_parsed_from_single_l1_call():
    """§1.6: optional claim-аннотация в ТОМ ЖЕ L1-вызове; мусор отброшен."""
    plan = _plan(external_claims=[
        {"entity": "DeepSeek V4.1 Flash", "relation": "version",
         "version": "4.1"},
        {"relation": "exists"},
        {"entity": "x", "relation": "teleportation"},
        "не-объект",
    ])
    assert len(plan.external_claims) == 1
    claim = plan.external_claims[0]
    assert claim["entity"] == "DeepSeek V4.1 Flash"
    assert claim["relation"] == "version"
    keys = ep.classify_claims(plan)
    assert len(keys) == 1 and keys[0].version == "4.1"


# ── Сценарий 7/8/16/24: bounded outbound guard ─────────────────────────────


def test_scenario7_categorical_nonexistence_needs_source():
    """Сценарий 7: категорическое «модель X не существует» без источника —
    ровно один адресный lookup, затем регенерация, затем удаление claim'а."""
    decision = ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual")
    answer = "Модели GeForce RTX 9090 не существует. Ну и ладно."
    verdict = ep.guard_egress(answer=answer, decision=decision,
                              evidence_text="")
    assert verdict.action == ep.GUARD_ONE_LOOKUP
    verdict = ep.guard_egress(answer=answer, decision=decision,
                              evidence_text="", lookup_used=True)
    assert verdict.action == ep.GUARD_HINT_RETRY
    verdict = ep.guard_egress(answer=answer, decision=decision,
                              evidence_text="", lookup_used=True,
                              retry_used=True)
    assert verdict.action == ep.GUARD_DROP_CLAIM
    assert verdict.reason_code == ep.REASON_EVIDENCE_CLAIM_REMOVED
    rest = ep.drop_claim_sentence(answer, verdict.sentence)
    assert "Ну и ладно." in rest
    assert "не существует" not in rest


def test_scenario17_metaphor_and_mat_are_outside_guard():
    """Сценарий 17: яркая метафора без проверяемого факта не трогается."""
    decision = ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual")
    answer = "Этот движок летает как ракета, блин, чистый космос."
    assert ep.guard_egress(answer=answer, decision=decision,
                           evidence_text="").action == ep.GUARD_NONE


@pytest.mark.asyncio
async def test_scenario16_egress_one_lookup_one_retry_keeps_joke():
    """Сценарий 16: одна адресная попытка и не более одной регенерации;
    шутка сохраняется, добавленный claim удаляется только при исчерпании."""
    calls = {"lookup": 0, "rewrite": 0}

    async def lookup(claim):
        calls["lookup"] += 1
        return "iPhone 18 официально анонсирован к выходу в 2027 году, 256 ГБ"

    async def rewrite(hint, extra):
        calls["rewrite"] += 1
        return "Ну и мрак. Кстати, iPhone 18 выйдет в 2027."

    decision = ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual")
    answer, stats = await dcs._run_evidence_egress_guard(
        answer="Ну и мрак. Кстати, iPhone 18 выйдет в 2027.",
        decision=decision, evidence_text="",
        lookup=lookup, rewrite=rewrite)
    assert calls["lookup"] == 1 and calls["rewrite"] <= 1
    assert stats["lookup_used"] == 1
    assert "Ну и мрак" in answer


def test_scenario24_only_new_claim_is_checked_in_mixed_reply():
    """Сценарий 24: пересказ чужого + своя новая цена → проверяется только
    добавка; предложение-атрибуция не считается неподтверждённым."""
    decision = ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual")
    answer = ("По словам участников, цена уже 500$. "
              "Новая цена будет 700$.")
    verdict = ep.guard_egress(answer=answer, decision=decision,
                              evidence_text="")
    assert verdict.action == ep.GUARD_ONE_LOOKUP
    assert "700" in verdict.sentence
    assert "500" not in verdict.sentence
    answer2 = "Участники спорили об акциях. Новая цена будет 500$."
    verdict2 = ep.guard_egress(answer=answer2, decision=decision,
                               evidence_text="")
    assert verdict2.action == ep.GUARD_ONE_LOOKUP
    assert "500" in verdict2.sentence


def test_scenario8_snippet_is_not_a_read_source():
    """Сценарий 8: без доставленной выдержки число не подтверждается —
    «прочитал документацию» не проходит guard."""
    decision = ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual")
    answer = "Я прочитал документацию: там 16 ГБ видеопамяти."
    verdict = ep.guard_egress(answer=answer, decision=decision,
                              evidence_text="")
    assert verdict.action == ep.GUARD_ONE_LOOKUP
    supported = ep.guard_egress(
        answer=answer, decision=decision,
        evidence_text="Спецификация: видеопамяти 16 ГБ, шина 256 бит.")
    assert supported.action == ep.GUARD_NONE


# ── Сценарии 19/23/26: фон и трансформация не запускают сеть ───────────────


def test_scenario19_background_services_have_no_web_imports():
    """Сценарий 19/20/22: фоновая стадия не импортирует поисковый контур."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for name in ("summary_generator", "dream_worker", "summary_memory",
                 "dossier_service"):
        path = root / "services" / f"{name}.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        assert "services.search_aggregator" not in imported
        assert "services.web_content_extractor" not in imported
        assert "services.tool_router" not in imported


def test_scenario23_public_summary_retelling_is_transformation():
    """Сценарий 23: пересказ Summary не «допроверяется» вебом."""
    plan = _plan(response_act="summarization", structure="summary")
    supplied = dcs._evidence_supplied(
        "перескажи кратко", "В чате обсуждали новость о ценах", plan)
    assert supplied.transformed_only is True
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="summarization", supplied=supplied,
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert not decision.required
    assert decision.skip_reason is \
        ep.EvidenceSkipReason.TEXT_TRANSFORM_OR_TRANSLATION


# ── Сценарии 28/29: Initiative ─────────────────────────────────────────────


def test_scenario28_silent_and_react_have_no_evidence_phase():
    """Сценарий 28: SILENT/REACT — участие решено до tool-фазы, 0 поисков."""
    for action in ("silent", "react"):
        decision = ep.evaluate_evidence_need(
            plan=_plan(action=action), task_kind="social_chat",
            runtime_state=ep.RuntimeState(), context=_ok_ctx())
        assert not decision.required
        assert decision.evidence_class == "social"
        assert decision.skip_reason is ep.EvidenceSkipReason.SILENT_OR_REACT_ONLY
        assert decision.required_caps == ()
        assert decision.skip_code() == "stage_skipped"


def test_scenario29_initiative_path_structure():
    """Сценарий 29: участиe решается ДО tool-фазы, retrieval — в Writer-методе.

    `handle_initiative` (оркестратор) сам инструментов не запускает: SILENT/
    REACT выходят раньше генерации. Сам retrieval/guard живёт в
    `generate_initiative_reply` — том же методе, что пишет инициативный текст."""
    root = pathlib.Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "services" / "direct_chat_service.py")
                     .read_text(encoding="utf-8"))

    def _used(func_name: str) -> set[str]:
        target = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) \
                    and node.name == func_name:
                target = node
                break
        assert target is not None, func_name
        used: set[str] = set()
        for node in ast.walk(target):
            if isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                used.add(node.value)      # getattr(self, "_name")-форма
        return used

    handle_used = _used("handle_initiative")
    for forbidden in ("_l1_tool_phase", "_l1_tool_subset", "_evidence_preflight",
                      "_evidence_lookup", "run_simple_tools"):
        assert forbidden not in handle_used, forbidden
    reply_used = _used("generate_initiative_reply")
    for required in ("_evidence_preflight", "_l1_tool_subset", "_l1_tool_phase",
                     "_evidence_lookup", "_run_evidence_egress_guard"):
        assert required in reply_used, required


class _InitMemory:
    """Мини-окно чата для инициативного пути (без БД)."""

    async def get_window_messages(self, chat_id):
        return [{"role": "user", "content": "обсуждали релиз 1017"}]


def _init_service(router, monkeypatch, answer="Кстати, релиз 1017 вышел 1 октября."):
    svc = _service(router)
    svc.memory = _InitMemory()
    writer_calls: list[dict] = []

    async def _persona(chat_id):
        return "persona"

    async def _writer(self, chat_id, query, *, temperature=None,
                      correlation_id=None, **kw):
        writer_calls.append({"query": query,
                             "evidence": kw.get("evidence", ""),
                             "user_blocks": list(kw.get("user_blocks") or [])})
        return (answer, "reply")

    svc._initiative_persona_block = _persona
    monkeypatch.setattr(dcs.DirectChatService, "_l2_write_answer", _writer)
    return svc, writer_calls


@pytest.mark.asyncio
async def test_scenario29_initiative_uses_same_evidence_contour(monkeypatch):
    """Сценарий 29: инициатива С внешним claim'ом — тот же контур.

    Инициатива не «отдельный контур»: тот же `_evidence_preflight`, та же
    tool-фаза по `required_caps`, тот же пакет в Writer и тот же bounded
    egress-guard. Поисковый запрос — из claim-key плана, не из цели."""
    router = _Router(outputs={"execute_web_search": "Релиз 1017 вышел 1 октября"})
    svc, writer_calls = _init_service(router, monkeypatch)
    monkeypatch.setattr(dcs, "_evidence_context", _permissive_context)
    plan = _plan(response_act="answer", external_claims=[
        {"entity": "релиз 1017", "relation": "event", "date": "1 октября"}])
    text = await svc.generate_initiative_reply(
        CHAT, {"goal": "напомнить про релиз 1017"}, l1_plan=plan,
        correlation_id="run-s29")
    assert [d["tool"] for d in router.dispatched] == ["execute_web_search"]
    assert "релиз 1017" in json.dumps(router.dispatched[0]["arguments"],
                                      ensure_ascii=False).lower()
    assert writer_calls and writer_calls[0]["evidence"]
    assert any(block.startswith("[EVIDENCE]")
               for block in writer_calls[0]["user_blocks"])
    assert text


@pytest.mark.asyncio
async def test_scenario29_initiative_answer_without_claims_makes_no_search(
        monkeypatch):
    """Инициатива `response_act=answer` без claim'ов — НОЛЬ сетевых вызовов.

    Внутренняя цель («напомнить про релиз 1017») — служебный текст, а не
    пользовательский вопрос: адресовать запрос нечем, поэтому tool-фаза не
    запускается, а Writer не получает ни пакета, ни утверждения о проверке."""
    router = _Router(outputs={"execute_web_search": "что-то из сети"})
    svc, writer_calls = _init_service(router, monkeypatch,
                                      answer="Кстати, в чате тихо.")
    monkeypatch.setattr(dcs, "_evidence_context", _permissive_context)
    text = await svc.generate_initiative_reply(
        CHAT, {"goal": "напомнить Ane про релиз 1017"},
        l1_plan=_plan(response_act="answer"), correlation_id="run-s29b")
    assert router.dispatched == []
    assert text == "Кстати, в чате тихо."
    assert writer_calls and writer_calls[0]["evidence"] == ""
    assert not any(block.startswith("[EVIDENCE]")
                   for block in writer_calls[0]["user_blocks"])



@pytest.mark.asyncio
async def test_scenario28_initiative_silent_makes_no_calls(monkeypatch):
    """Сценарий 28: SILENT/REACT доходят до Writer-метода — и не тратят ничего."""
    router = _Router()
    svc, writer_calls = _init_service(router, monkeypatch)
    monkeypatch.setattr(dcs, "_evidence_context", _permissive_context)
    for action in ("silent", "react"):
        text = await svc.generate_initiative_reply(
            CHAT, {"goal": "x"}, l1_plan=_plan(action=action),
            correlation_id="run-s28")
        assert text == ""
    assert router.dispatched == []
    assert writer_calls == []



def test_review_decimal_number_is_not_a_version_claim():
    """Review fix 1: дробное число само по себе — не claim о версии.

    «версия 1.5» и «1.2.3» остаются высокорисковыми, а «1.5 часа» — нет:
    иначе guard искал бы в вебе по обычной арифметике в болтовне."""
    factual = ep.EvidenceDecision(required=True,
                                  evidence_class="externally_factual")
    assert ep.guard_egress(
        answer="Потратил 1.5 часа на отладку этой штуки.",
        decision=factual, evidence_text="").action == ep.GUARD_NONE
    assert ep.guard_egress(
        answer="Вышла версия 1.5 этого ядра.",
        decision=factual, evidence_text="").action == ep.GUARD_ONE_LOOKUP
    assert ep.guard_egress(
        answer="Сборка 1.2.3 падает на старте.",
        decision=factual, evidence_text="").action == ep.GUARD_ONE_LOOKUP


@pytest.mark.asyncio
async def test_review_social_reply_with_decimal_makes_no_lookup():
    """Review fix 1/2: социальная реплика с «1.5 часа» → GUARD_NONE, 0 запросов.

    Guard для социального класса ТЕПЕРЬ ЗАПУСКАЕТСЯ (review fix 2: в шутке
    может быть добавленный Writer'ом новый внешний факт), но детектор высокого
    риска её не трогает: «1.5 часа» — арифметика, а не claim о версии. Ни
    лишнего веб-поиска, ни удаления предложения."""
    plan = _plan(response_act="banter")
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="social_chat", supplied=ep.SuppliedSources(),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert not decision.required
    verdict = ep.guard_egress(
        answer="Я потратил 1.5 часа на этот баг, зато выспался.",
        decision=decision, evidence_text="")
    assert verdict.action == ep.GUARD_NONE
    assert verdict.lookup_allowed is False
    assert verdict.note != "not_externally_factual"   # guard реально проверял
    assert verdict.note == ""                         # и ничего не нашёл
    calls = {"lookup": 0, "rewrite": 0}

    async def lookup(claim):
        calls["lookup"] += 1
        return "нашлось"

    async def rewrite(hint, extra):
        calls["rewrite"] += 1
        return "иное"

    answer, stats = await dcs._run_evidence_egress_guard(
        answer="Я потратил 1.5 часа на этот баг, зато выспался.",
        decision=decision, evidence_text="", lookup=lookup, rewrite=rewrite)
    assert answer == "Я потратил 1.5 часа на этот баг, зато выспался."
    assert calls == {"lookup": 0, "rewrite": 0}
    assert stats["guard_action"] == ep.GUARD_NONE


# ── Review fix 2: guard НЕ выключен для шутки и атрибутированного пересказа ─


def _banter_decision() -> "ep.EvidenceDecision":
    """Реальное решение политики для шутки: act=banter, claim'ов нет."""
    decision = ep.evaluate_evidence_need(
        plan=_plan(response_act="banter"), task_kind="social_chat",
        supplied=ep.SuppliedSources(), runtime_state=ep.RuntimeState(),
        context=_ok_ctx())
    assert decision.evidence_class == "social"
    assert decision.required is False and decision.claims == ()
    assert decision.required_caps == ()
    return decision


def _attributed_decision() -> "ep.EvidenceDecision":
    """Реальное решение политики для пересказа чужой речи (сц. 24)."""
    decision = ep.evaluate_evidence_need(
        plan=_plan(response_act="other"), task_kind="social_chat",
        supplied=ep.SuppliedSources(attributed_only=True),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert decision.evidence_class == "attributed"
    assert decision.required is False and decision.claims == ()
    return decision


@pytest.mark.asyncio
async def test_review_fix2_joke_with_added_nonexistence_is_checked():
    """Сценарий 16: «Кстати, модели GeForce RTX 9090 не существует» в шутке.

    Класс `social` больше не глушит guard: добавленный Writer'ом новый внешний
    факт — это НАШ claim. Реакция ограничена: один адресный lookup, одна
    регенерация, и только потом удаляется ровно это предложение."""
    decision = _banter_decision()
    answer = "Ну и мрак. Кстати, модели GeForce RTX 9090 не существует."
    verdict = ep.guard_egress(answer=answer, decision=decision,
                              evidence_text="")
    assert verdict.action == ep.GUARD_ONE_LOOKUP
    assert "не существует" in verdict.sentence
    assert "Ну и мрак" not in verdict.sentence     # шутка не в фокусе

    calls = {"lookup": 0, "rewrite": 0}
    seen: list[str] = []

    async def lookup(claim):
        calls["lookup"] += 1
        seen.append(str(claim))
        return ""                                  # выдержки нет

    async def rewrite(hint, extra):
        calls["rewrite"] += 1
        assert "Не пиши, что ты что-то проверял" in hint
        return "Ну и мрак."                        # claim убран, шутка цела

    text, stats = await dcs._run_evidence_egress_guard(
        answer=answer, decision=decision, evidence_text="",
        lookup=lookup, rewrite=rewrite)
    assert calls == {"lookup": 1, "rewrite": 1}
    assert seen and "не существует" in seen[0]
    assert text == "Ну и мрак."
    assert stats["lookup_used"] == 1 and stats["retry_used"] == 1
    assert stats["dropped_claim"] == 0

    # Writer проигнорировал подсказку → удаляется ТОЛЬКО это предложение.
    async def stubborn(hint, extra):
        return answer

    text2, stats2 = await dcs._run_evidence_egress_guard(
        answer=answer, decision=decision, evidence_text="",
        lookup=lookup, rewrite=stubborn)
    assert "не существует" not in text2
    assert "Ну и мрак" in text2
    assert stats2["dropped_claim"] == 1


@pytest.mark.asyncio
async def test_review_fix2_attributed_retelling_checks_only_the_addition():
    """Сценарий 24: атрибуция + НОВАЯ цена → проверяется только добавка.

    «По словам участников, цена 500$» — чужая речь (попредложенческий skip),
    «Новая цена будет 700$» — собственный claim Writer'а: он и уходит в
    адресную проверку, а пересказ остаётся в тексте."""
    decision = _attributed_decision()
    answer = ("По словам участников, цена уже 500$. "
              "Новая цена будет 700$.")
    verdict = ep.guard_egress(answer=answer, decision=decision,
                              evidence_text="")
    assert verdict.action == ep.GUARD_ONE_LOOKUP
    assert "700" in verdict.sentence and "500" not in verdict.sentence

    seen: list[str] = []

    async def lookup(claim):
        seen.append(str(claim))
        return ""

    async def rewrite(hint, extra):
        return "По словам участников, цена уже 500$."

    text, stats = await dcs._run_evidence_egress_guard(
        answer=answer, decision=decision, evidence_text="",
        lookup=lookup, rewrite=rewrite)
    assert len(seen) == 1 and "700" in seen[0] and "500" not in seen[0]
    assert text == "По словам участников, цена уже 500$."
    assert "700" not in text
    assert stats["dropped_claim"] == 0

    # Та же реплика БЕЗ добавки — guard молчит, атрибуция не наш claim.
    clean = ep.guard_egress(
        answer="По словам участников, цена уже 500$.",
        decision=decision, evidence_text="")
    assert clean.action == ep.GUARD_NONE


def test_review_fix2_transformation_class_is_still_not_guarded():
    """Сценарий 23: пересказ Summary не «допроверяется» вебом.

    Класс-уровневый skip сужен, но не снят: `transformation` по-прежнему вне
    egress-проверки (иначе пересказ поданного текста стоил бы сети)."""
    plan = _plan(response_act="summarization", structure="summary")
    supplied = dcs._evidence_supplied(
        "перескажи кратко", "В чате обсуждали новость о ценах", plan)
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="social_chat", supplied=supplied,
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert decision.evidence_class == "transformation"
    verdict = ep.guard_egress(answer="Новая цена будет 700$.",
                              decision=decision, evidence_text="")
    assert verdict.action == ep.GUARD_NONE
    assert verdict.note == "not_externally_factual"


def test_review_fix2_direct_unknown_plan_still_requires_check():
    """§1.2 п.8 для Direct: неизвестно → проверка требуется.

    Правило 7b (review-fix 2) было ГЛОБАЛЬНЫМ и гасило п.8: план
    `response_act=other` + `tool_policy=none` без `external_claims` в Direct
    получал «проверка не требуется», хотя содержания мы просто не знаем.
    Теперь его законная часть живёт только на инициативном пути
    (`RuntimeState.initiative`)."""
    decision = ep.evaluate_evidence_need(
        plan=_plan(response_act="other", tool_policy="none"),
        task_kind="direct_answer", supplied=ep.SuppliedSources(),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert decision.required is True
    assert decision.required_caps == ("web_search",)
    assert decision.skip_reason is None
    assert decision.note == "unknown_requires_check"


def test_review_fix2_casual_initiative_plan_without_claims_needs_no_search():
    """Инициатива/casual с response_act=other и без claim'ов → нет проверки.

    Адресного запроса у инициативного хода нет: единственный его источник —
    claim-key плана (`claims_query`)."""
    decision = ep.evaluate_evidence_need(
        plan=_plan(response_act="other"), task_kind="social_chat",
        supplied=ep.SuppliedSources(),
        runtime_state=ep.RuntimeState(initiative=True), context=_ok_ctx())
    assert decision.required is False
    assert decision.required_caps == ()
    assert decision.skip_reason is ep.EvidenceSkipReason.NO_NEW_EXTERNAL_CLAIM
    assert decision.note == "initiative_without_claim_query"
    assert ep.claims_query(decision) == ""
    claim_plan = _plan(response_act="answer", external_claims=[
        {"entity": "GeForce RTX 9090", "relation": "version", "version": "1.0"}])
    factual = ep.evaluate_evidence_need(
        plan=claim_plan, task_kind="social_chat",
        supplied=ep.SuppliedSources(),
        runtime_state=ep.RuntimeState(initiative=True), context=_ok_ctx())
    assert factual.required and factual.required_caps == ("web_search",)
    query = ep.claims_query(factual)
    assert "geforce rtx 9090" in query.lower() and "1.0" in query
    assert "напомнить" not in query


@pytest.mark.asyncio
async def test_review_fix2_casual_initiative_makes_no_search(monkeypatch):
    """Инициатива с response_act=other и без claim'ов → 0 сетевых вызовов.

    Раньше §1.2 п.8 отправлял веб-поиск по внутренней формулировке цели
    («напомнить про релиз 1017»); теперь это NO_NEW_EXTERNAL_CLAIM, а запрос
    (если он вообще нужен) строится только из claim'а."""
    router = _Router()
    svc, writer_calls = _init_service(router, monkeypatch,
                                      answer="Кстати, в чате тихо.")
    monkeypatch.setattr(dcs, "_evidence_context", _permissive_context)
    text = await svc.generate_initiative_reply(
        CHAT, {"goal": "напомнить про релиз 1017"},
        l1_plan=_plan(response_act="other"), correlation_id="run-rf2")
    assert router.dispatched == []
    assert text == "Кстати, в чате тихо."
    assert writer_calls and writer_calls[0]["evidence"] == ""


@pytest.mark.asyncio
async def test_review_fix3_initiative_required_without_query_is_unmet(monkeypatch):
    """§1.2 п.10: обязательная проверка без адресного запроса — честно unmet.

    Инициативная цель с маркером поиска («погугли …») делает проверку
    обязательной, но claim'ов в плане нет → запроса, который можно отправить
    в сеть, тоже нет. Служебная цель в поисковик НЕ уходит (0 вызовов), а
    решение остаётся `required=True` + `required_unmet`, Writer получает
    «внешняя проверка НЕ выполнена»."""
    router = _Router(outputs={"execute_web_search": "что-то из сети"})
    svc, writer_calls = _init_service(router, monkeypatch,
                                      answer="Кстати, в чате тихо.")
    monkeypatch.setattr(dcs, "_evidence_context", _permissive_context)
    text = await svc.generate_initiative_reply(
        CHAT, {"goal": "погугли про релиз 1017"},
        l1_plan=_plan(response_act="other"), correlation_id="run-rf3")
    assert router.dispatched == []
    assert text == "Кстати, в чате тихо."
    assert writer_calls and writer_calls[0]["evidence"] == ""
    note = " ".join(writer_calls[0]["user_blocks"])
    assert "внешняя проверка НЕ выполнена" in note


@pytest.mark.asyncio
async def test_review_egress_lookup_respects_allowed_gate(monkeypatch):
    """Review fix 2: адресный lookup НЕ обходит §1.5.

    Положительный контроль: разрешено → ровно один web_search. Рубильник
    «Модуль Поиск» выключен, явный запрет пользователя или отсутствие
    `web_search` в решении политики → ноль сетевых вызовов."""
    router = _Router(outputs={"execute_web_search": "DeepSeek 4.1"})
    svc = _service(router)
    decision = ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual",
                                   required_caps=("web_search",))

    async def _permissive(chat_id, required_caps=(), *, user_forbids=False):
        return _ok_ctx(user_forbids_external=bool(user_forbids))

    monkeypatch.setattr(dcs, "_evidence_context", _permissive)
    found = await svc._evidence_lookup(
        _ctx(), "какая версия DeepSeek", chat_id=CHAT,
        correlation_id="run-lk", lore=False, image=False, decision=decision)
    assert found
    assert [d["tool"] for d in router.dispatched] == ["execute_web_search"]

    async def _off(chat_id, required_caps=(), *, user_forbids=False):
        return _ok_ctx(network_allowed={"web_search": False,
                                        "fetch_url": True},
                       user_forbids_external=bool(user_forbids))

    router.dispatched.clear()
    monkeypatch.setattr(dcs, "_evidence_context", _off)
    assert await svc._evidence_lookup(
        _ctx(), "какая версия DeepSeek", chat_id=CHAT,
        correlation_id="run-lk", lore=False, image=False,
        decision=decision) == ""
    assert router.dispatched == []          # рубильник: 0 сетевых вызовов

    monkeypatch.setattr(dcs, "_evidence_context", _permissive)
    assert await svc._evidence_lookup(
        _ctx("без интернета, скажи просто"), "какая версия DeepSeek",
        chat_id=CHAT, correlation_id="run-lk", lore=False, image=False,
        decision=decision, user_forbids=True) == ""
    assert router.dispatched == []          # явный запрет: 0 сетевых вызовов

    no_caps = ep.EvidenceDecision(required=True,
                                  evidence_class="externally_factual")
    assert await svc._evidence_lookup(
        _ctx(), "какая версия DeepSeek", chat_id=CHAT,
        correlation_id="run-lk", lore=False, image=False,
        decision=no_caps) == ""
    assert router.dispatched == []


def test_review_user_forbidden_is_valid_skip_not_failure():
    """Review fix: запрет сети — законный skip (`disabled`), не сбой проверки."""
    decision = ep.evaluate_evidence_need(
        plan=_plan(response_act="answer"), task_kind="direct_answer",
        supplied=ep.SuppliedSources(),
        runtime_state=ep.RuntimeState(user_forbids_external=True),
        context=_ok_ctx())
    assert not decision.required
    assert decision.required_unmet is False
    assert decision.failure_code is None
    assert decision.skip_reason is ep.EvidenceSkipReason.USER_FORBIDS_EXTERNAL
    assert decision.skip_code() == "disabled"
    assert decision.required_caps == ()
    assert decision.blocked == (("web_search", ep.BLOCK_EXTERNAL_DISABLED),)


def test_review_scenario13_hardware_question_is_runtime_source():
    """Сценарий 13: «на каком железе ты это запускал?» — runtime, не веб.

    Вопрос о собственной машине/запуске отвечается фактическим runtime-источником,
    а не внешним поиском; класс не `externally_factual`."""
    query = "на каком железе ты это запускал?"
    assert ep.is_runtime_self_question(query)
    plan = _plan(response_act="answer")
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer",
        supplied=dcs._evidence_supplied(query, "", plan),
        runtime_state=ep.RuntimeState(
            self_status_question=ep.is_runtime_self_question(query)),
        context=_ok_ctx())
    assert not decision.required
    assert decision.evidence_class == "runtime"
    assert decision.skip_reason is ep.EvidenceSkipReason.SUFFICIENT_RUNTIME_SOURCE


# ── Сценарии 30/31: qualified reuse по claim-key ───────────────────────────


def _reuse_plan(version="4.1") -> l1.L1Plan:
    return _plan(external_claims=[{"entity": "deepseek v4.1 flash",
                                   "relation": "version",
                                   "version": version}])


def test_scenario30_same_claim_with_fresh_source_is_verified_reuse():
    """Сценарий 30: тот же claim + свежий источник → verified_reuse, 0 поиска."""
    plan = _reuse_plan("4.1")
    keys = ep.classify_claims(plan)
    supplied = ep.SuppliedSources(verified_reuse=frozenset({keys[0].key()}))
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer", supplied=supplied,
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert not decision.required
    assert decision.skip_reason is ep.EvidenceSkipReason.QUALIFIED_VERIFIED_REUSE
    assert decision.skip_code() == "exact_match_used"
    assert decision.claims and decision.claims[0].key() == keys[0].key()


def test_scenario31_changed_version_invalidates_reuse():
    """Сценарий 31: другая версия → другой claim-key, reuse не засчитан."""
    old = _reuse_plan("4.1")
    keys = ep.classify_claims(old)
    supplied = ep.SuppliedSources(verified_reuse=frozenset({keys[0].key()}))
    decision = ep.evaluate_evidence_need(
        plan=_reuse_plan("4.2"), task_kind="direct_answer", supplied=supplied,
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert decision.required and not decision.required_unmet


def test_claim_key_canon_distinguishes_metric_and_date():
    """§3.2: «тема та же» недостаточно — метрика/дата меняют ключ."""
    base = ep.ClaimKey("X", "spec", metric="5 гб")
    other_metric = ep.ClaimKey("X", "spec", metric="8 гб")
    other_date = ep.ClaimKey("X", "spec", date="2027")
    assert base.key() != other_metric.key()
    assert base.key() != other_date.key()
    assert base.key() == ep.ClaimKey("  X ", "SPEC", metric="5  ГБ").key()


# ── Сценарии 32/33: история чата и собственный runtime ─────────────────────


def test_scenario32_chat_history_answer_needs_no_network():
    """Сценарий 32: «что было в чате» → исторический источник, 0 веба."""
    decision = ep.evaluate_evidence_need(
        plan=_plan(response_act="historical_recall"),
        task_kind="historical_recall",
        supplied=ep.SuppliedSources(history_answer=True),
        runtime_state=ep.RuntimeState(), context=_ok_ctx())
    assert not decision.required
    assert decision.evidence_class == "historical"
    assert decision.skip_reason is \
        ep.EvidenceSkipReason.SUFFICIENT_CHAT_HISTORY_SOURCE


def test_scenario33_own_model_question_is_runtime_source():
    """Сценарий 33: «на какой модели работаешь?» → runtime, не веб; Writer
    получает фактический маршрут вызова, а не догадку из промпта."""
    query = "на какой модели ты работаешь?"
    plan = _plan(response_act="answer")
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer",
        supplied=dcs._evidence_supplied(query, "", plan),
        runtime_state=ep.RuntimeState(self_status_question=True,
                                      effective_route="deepseek-v4.1-flash"),
        context=_ok_ctx())
    assert not decision.required
    assert decision.evidence_class == "runtime"
    assert decision.skip_reason is ep.EvidenceSkipReason.SUFFICIENT_RUNTIME_SOURCE
    note = ep.runtime_source_note("deepseek-v4.1-flash", provider="opencode-go")
    assert "opencode-go/deepseek-v4.1-flash" in note
    svc = _service()
    writer_note = svc._evidence_writer_note(
        decision, "", route="deepseek-v4.1-flash")
    assert "deepseek-v4.1-flash" in writer_note


def test_runtime_self_question_detector_is_narrow():
    """Детектор «о себе» не срабатывает на технический вопрос о моделях."""
    assert ep.is_runtime_self_question("бот, на какой модели ты работаешь?")
    assert ep.is_runtime_self_question("на каком железе ты это запускал?")
    assert not ep.is_runtime_self_question(
        "какая модель лучше для игр в 2026?")
    assert not ep.is_runtime_self_question("какое железо взять для игр?")


# ── Сценарий 41: запрет сети/RBAC/квота/SSRF ───────────────────────────────


def test_c3_search_switch_off_blocks_network_and_reason_is_honest():
    """C3/сценарий 41: выключенный «Модуль Поиск» = 0 сетевых вызовов.

    Выключенный рубильник — законный skip (`disabled`, `USER_FORBIDS_EXTERNAL`),
    а не «проверка сорвалась»: сеть просто не разрешена (§1.4)."""
    plan = _plan(capabilities_needed=["web_search"])
    ctx = _ok_ctx(network_allowed={"web_search": False, "fetch_url": True})
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer",
        supplied=ep.SuppliedSources(), runtime_state=ep.RuntimeState(),
        context=ctx)
    assert not decision.required
    assert decision.skip_reason is ep.EvidenceSkipReason.USER_FORBIDS_EXTERNAL
    assert decision.skip_code() == "disabled"
    assert decision.blocked == (("web_search", ep.BLOCK_EXTERNAL_DISABLED),)
    effective, blocked = ep.effective_capabilities(
        ("web_search",), ("web_search",), ctx)
    assert effective == () and blocked


@pytest.mark.asyncio
async def test_c3_subset_hides_web_tools_when_module_off(monkeypatch):
    """C3: рубильник действует в Direct tool-пути (не только в хендлерах)."""

    class _Cfg:
        def get(self, key, default=None):
            return False if key == "flags.search_enabled" else default

    hot.set_config_cache(_Cfg())
    plan = _plan(capabilities_needed=["web_search"])
    svc = _service(_Router())
    schemas, rejected = await svc._l1_tool_subset(
        CHAT, "run-c3", True, False, plan)
    assert "execute_web_search" not in {
        t["function"]["name"] for t in schemas}
    assert ("web_search", "disabled") in rejected


def test_user_forbids_external_is_recorded_skip():
    """§1.5 п.2/§1.4: явный запрет пользователя → skip `disabled`, не сбой."""
    decision = ep.evaluate_evidence_need(
        plan=_plan(response_act="answer"), task_kind="direct_answer",
        supplied=ep.SuppliedSources(),
        runtime_state=ep.RuntimeState(user_forbids_external=True),
        context=_ok_ctx())
    assert not decision.required
    assert decision.skip_reason is ep.EvidenceSkipReason.USER_FORBIDS_EXTERNAL
    assert decision.required_caps == ()
    assert ep.is_external_forbidden("без интернета, просто скажи")
    assert not ep.is_external_forbidden("найди в интернете, что это")


def test_rbac_quota_ssrf_codes_are_specific():
    """§1.5: RBAC/квота/SSRF — конкретные коды, не «неизвестно»."""
    assert ep.allowed("web_search", _ok_ctx(rbac_ok=False)) == \
        (False, ep.BLOCK_RBAC)
    assert ep.allowed("web_search", _ok_ctx(quota_ok={"web_search": False})) \
        == (False, ep.BLOCK_QUOTA)
    assert ep.allowed("fetch_url", _ok_ctx(ssrf_ok={"fetch_url": False})) \
        == (False, ep.BLOCK_SSRF)
    assert ep.allowed("source_read", _ok_ctx()) == \
        (False, ep.BLOCK_CAPABILITY_NOT_READY)


# ── C4: один резерв вывода и один измеритель ───────────────────────────────


def test_c4_no_double_output_reserve():
    """C4: композер уже вычел резерв вывода — второй раз не вычитаем."""
    tight = dx.l2_evidence_budget_chars(400, other_chars=1200)
    double = dx.l2_evidence_budget_chars(400, other_chars=1200,
                                         output_reserve_tokens=512)
    assert tight is not None and tight > dx.EVIDENCE_FLOOR_CHARS
    assert double == dx.EVIDENCE_FLOOR_CHARS
    # Явный резерв вызывающего по-прежнему работает (совместимость).
    assert dx.l2_evidence_budget_chars(8000, 4000,
                                       output_reserve_tokens=0) > 0


def test_c4_measure_includes_plan_block_and_system_base():
    """C4/§4.2: «прочее» считается одним измерителем по всему payload."""
    only_users = dx.measure_nonevidence_chars(user_blocks=["x" * 100])
    full = dx.measure_nonevidence_chars(
        system_base="s" * 1000, plan_block="p" * 500,
        time_line="t" * 50, user_blocks=["x" * 100],
        lessons="l" * 10, speech="c" * 10, character="h" * 10)
    assert full > only_users
    assert full == 1000 + 500 + 50 + 100 + 10 + 10 + 10


# ── Сценарий 45: размеченный corpus — нет необоснованных skip/вызовов ──────


CORPUS = [
    # (label, class, required, plan-overrides, supplied, explicit)
    ("social", "social", False, {"response_act": "banter"}, {}, {}),
    ("joke", "social", False, {"response_act": "tease"}, {}, {}),
    ("attributed", "attributed", False, {"response_act": "answer"},
     {"attributed_only": True}, {}),
    ("transform", "transformation", False,
     {"response_act": "summarization", "structure": "summary"},
     {"transformed_only": True}, {}),
    ("history", "historical", False, {"response_act": "historical_recall"},
     {"history_answer": True}, {}),
    ("runtime", "runtime", False, {"response_act": "answer"},
     {"self_question": True}, {}),
    ("fact", "externally_factual", True, {"response_act": "answer"}, {}, {}),
    ("explicit", "externally_factual", True, {"response_act": "banter"}, {},
     {"search": True}),
]


@pytest.mark.parametrize("label,klass,required,over,supplied_over,explicit_over",
                         CORPUS)
def test_scenario45_corpus_zero_invalid_skip_zero_extra_search(
        label, klass, required, over, supplied_over, explicit_over):
    """Сценарий 45: класс/обязательность по размеченному корпусу.

    Контрактные метрики: `invalid_skip == 0` (ни одна обязательная проверка
    не потеряна) и `unnecessary_search == 0` (на исключённых классах нет
    вызовов)."""
    supplied_over = dict(supplied_over)
    self_question = bool(supplied_over.pop("self_question", False))
    plan = _plan(**over)
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="direct_answer",
        explicit=ep.ExplicitRequest(**{'search': bool(
            dict(explicit_over).get("search", False))}),
        supplied=ep.SuppliedSources(**supplied_over),
        runtime_state=ep.RuntimeState(self_status_question=self_question),
        context=_ok_ctx())
    assert decision.evidence_class == klass, label
    assert decision.required is required, label
    invalid_skip = (not decision.required) and required
    unnecessary_search = decision.required and klass in (
        "social", "attributed", "transformation", "historical", "runtime")
    assert invalid_skip is False, label
    assert unnecessary_search is False, label


# ── Интеграция: preflight политики на реальном шве сервиса ─────────────────


@pytest.mark.asyncio
async def test_preflight_wires_decision_and_emits_event(monkeypatch):
    """§2.1: preflight ДО tool-фазы возвращает required-решение и событие."""
    events: list = []
    monkeypatch.setattr(dcs, "_evidence_context", _permissive_context)
    monkeypatch.setattr(dcs, "_EVIDENCE_EVENT_POLICY",
                        "EVIDENCE_POLICY_DECIDED")
    original = dcs.emit_agentic_event
    monkeypatch.setattr(dcs, "emit_agentic_event",
                        lambda name, **kw: events.append((name, kw)))
    try:
        svc = _service()
        plan = _plan(response_act="answer")
        decision = await svc._evidence_preflight(
            CHAT, "run-pre", query="у новой карты 5 ГБ памяти?",
            reply_text="", l1_plan=plan, response_plan=plan.to_response_plan())
        assert decision.required and decision.required_caps == ("web_search",)
        assert decision.network_calls == 0
        assert any(name == "EVIDENCE_POLICY_DECIDED" for name, _ in events)
        fields = dict(events[0][1])
        assert fields.get("network_calls") == 0
        assert fields.get("evidence_class") == "externally_factual"
    finally:
        monkeypatch.setattr(dcs, "emit_agentic_event", original)


@pytest.mark.asyncio
async def test_preflight_is_fail_open(monkeypatch):
    """Сбой политики не роняет ход (честная пометка, обычный ход)."""
    async def boom(*a, **kw):
        raise RuntimeError("policy boom")

    monkeypatch.setattr(dcs, "_evidence_context", boom)
    svc = _service()
    plan = _plan(response_act="answer")
    decision = await svc._evidence_preflight(
        CHAT, "run-fail", query="вопрос", reply_text="", l1_plan=plan,
        response_plan=plan.to_response_plan())
    assert decision.required is False
    assert decision.note == "preflight_error"


# ── kill-switch: OFF → прежнее поведение (без обязательной проверки) ───────


def test_policy_gate_off_returns_previous_behaviour():
    """§8.2: EVIDENCE_ROUTING_POLICY_ENABLED OFF → проверка не требуется."""
    ep.POLICY_ENABLED_OVERRIDE = False
    decision = ep.evaluate_evidence_need(
        plan=_plan(response_act="answer"), task_kind="direct_answer",
        runtime_state=ep.RuntimeState(enabled=ep.policy_enabled()),
        context=_ok_ctx())
    assert not decision.required and decision.note == "policy_disabled"


@pytest.mark.asyncio
async def test_egress_gate_off_keeps_answer_byte_identical():
    """§8.2: EVIDENCE_EGRESS_GUARD_ENABLED OFF → ответ не меняется."""
    ep.EGRESS_ENABLED_OVERRIDE = False
    decision = ep.EvidenceDecision(required=True,
                                   evidence_class="externally_factual")
    answer, stats = await dcs._run_evidence_egress_guard(
        answer="Модели X не существует.", decision=decision,
        evidence_text="")
    assert answer == "Модели X не существует."
    assert stats["guard_action"] == ep.GUARD_NONE
