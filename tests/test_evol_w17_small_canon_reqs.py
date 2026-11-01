# -*- coding: utf-8 -*-
"""EVOL W17 — две малые требования владельца: ER-S25 и ER-54.

Источник (владелец, `plans/current_task.md`, читается из основного репозитория):
* §10 сценарий 25 (L02388): «Сделай саммари и проверь, кто прав» — результаты
  разделены на Summary и FactCheck; исходная история неизменна  → ER-S25;
* §6 (L02245): «Не считать противоречием две фразы о разных фазах работы
  модели, если их предметы действительно отличаются (prefill vs decode).
  Отдельно разбирать точные утверждения, параметры и условия. Социальная
  бравада не заменяет технический анализ.» → ER-54.

Что проверяется (и чем это может упасть):

1. ER-S25 — контракт двух различимых фаз живёт в АКТИВНОМ каноне L1-планера
   (`l1-planner-two-phase-precedence`), а не в комментарии; план по сценарию 25
   различает фазы существующими полями (structure=summary +
   external_claims), фаза проверки реально доходит до runtime-политики
   (`required=True`), а чисто пересказный план проверку не запускает.
   Разделение фаз на выходе: egress-guard не трогает атрибутированный
   пересказ и удаляет только добавленный фазой проверки неподтверждённый
   claim — текст сводки остаётся байт-в-байт.
2. ER-54 — правило фаз работы модели (prefill/decode) в АКТИВНОМ каноне
   Аналитика фактчека (стадия, которая присваивает статусы) и его границы:
   правило не появляется в канонах Summary/Writer (иначе «противоречий не
   бывает» стало бы общей лицензией). Пары утверждений о разных фазах не
   становятся одной проверяемой пропозицией (разные claim-единицы с разными
   метриками), а настоящее противоречие ВНУТРИ одной фазы по-прежнему
   помечается (`evidence_conflicting` / `contradictory_evidence`).
3. Обе правки — ревизия канона, а не «правка на глаз»: метка + печать,
   ступень `PROMPT_MIGRATIONS` ровно на выложенных байтах (не на подстроке и
   не на кастоме владельца с хвостом) и обратная ступень откатa на те же
   выложенные байты.
4. W17b — правило фаз есть в ОБОИХ канонах фактчека: в Аналитике (двухвызовный
   путь) и в одиночном `factcheck.base.single` (путь fallback при сбое
   Stage-1). Нормативное ядро у них — один и тот же объект
   (`FACTCHECK_PHASE_SCOPE_CORE`), поэтому эквивалентность проверяется
   сравнением байт, а не пересказом. Блок эталона
   `plans/docs/canon/architecture.md` (Section 72) обязан совпадать с кодом
   байт-в-байт — это и есть смысл пина.

ЧЕГО ЭТОТ ФАЙЛ НЕ ДОКАЗЫВАЕТ (честная граница): поведение модели на живом
прогоне (LLM выбирает structure/statuses) — offline-фикстура проверяет
контракт канона и детерминированные швы, а не текст будущего ответа модели.

TEST-LIFECYCLE: CONTRACT owner=ER-S25+ER-54 (EVOL W17/W17b)
"""
from __future__ import annotations

import hashlib

from services import chat_prompts as cp
from services import direct_l1 as l1
from services import evidence_policy as ep
from services import factcheck_planner as fp
from services import factcheck_prompts as fcp
from services import prompt_migrations as pm
from services import prompt_registry as pr
from services.prompt_style_blocks import resolve_prompt

L1_KEY = "prompts.direct_l1_planner_system_prompt"
FC_KEY = "prompts.factcheck_analyst_system_prompt"
FC_SINGLE_KEY = "prompts.factcheck_system_prompt"

#: Байты прода 2.58.147 (выложенный кандидат e18a86eb): ступень обязана
#: узнавать ИХ и только их.
DEPLOYED_L1_SHA12 = "eb496e938c49"
#: Байты прода 2.58.148 (ASAP-FC-VOICE-01 / A): канон Аналитика с правилом фаз
#: БЕЗ двух смысловых полей — непосредственная ступень откатa.
DEPLOYED_FC_ANALYST_SHA12 = "806d6cc6af77"
#: Байты прода 2.58.147 (ступень ER-54): канон БЕЗ правила фаз.
DEPLOYED_FC_ANALYST_PHASE_SHA12 = "9573b3d86161"
DEPLOYED_FC_SINGLE_SHA12 = "aa6a2ed38b4c"
#: Байты прода 2.58.148 одиночного канона (ER-54 + директива «торопливое
#: письмо») — непосредственная ступень откатa правки ASAP-FC-VOICE-01 / A.
DEPLOYED_FC_SINGLE_VOICE01_SHA12 = "d02776dec166"

DOC_CANON = "plans/docs/canon/architecture.md"


def _doc_section72_canon() -> str:
    """Эталонный блок канона фактчека из `architecture.md` (Section 72).

    Тот же разбор, что в `tests/test_factcheck_prompts.py` (якорь — строка
    `## Section 72`, тело — первый ```text-фенс после якоря). Здесь он нужен,
    чтобы сверять ДОКУМЕНТ и КОД в одном месте и падать с внятным сообщением.
    """
    import pathlib

    lines = pathlib.Path(DOC_CANON).read_text(encoding="utf-8").splitlines()
    anchor = next((i for i, line in enumerate(lines)
                   if line.startswith("## Section 72")), None)
    assert anchor is not None, "в эталоне нет якоря '## Section 72'"
    fence_start = next((i for i in range(anchor, len(lines))
                       if lines[i].strip() == "```text"), None)
    assert fence_start is not None, "после якоря нет ```text-фенса"
    fence_end = next((i for i in range(fence_start + 1, len(lines))
                     if lines[i].strip() == "```"), None)
    assert fence_end is not None, "фенс канона не закрыт"
    return "\n".join(lines[fence_start + 1:fence_end])


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════════════
#  ER-S25 — «сделай саммари и проверь, кто прав» = две различимые фазы
# ═══════════════════════════════════════════════════════════════════════════


def test_scenario25_canon_has_two_phase_contract():
    """Правило разделения фаз есть в активном каноне и это ревизия EVR2."""
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert cp._DIRECT_L1_TWO_PHASE_EVR2 in canon
    # ASAP-FC-VOICE-01 / B: слепок W17 — EVR2; активные байты = EVR2 + одно
    # правило статуса секции [ПРОФИЛЬ РЕШЕНИЙ].
    assert cp.PREV_DIRECT_L1_PLANNER_EVR2 == (
        cp.PREV_DIRECT_L1_PLANNER_EVR1 + cp._DIRECT_L1_TWO_PHASE_EVR2)
    assert canon == cp.PREV_DIRECT_L1_PLANNER_EVR2 \
        + cp._DIRECT_L1_DECISION_PROFILE_EVR3
    # Обе фазы названы, и у каждой свой маркер из СУЩЕСТВУЮЩИХ полей плана.
    assert "САММАРИ И ПРОВЕРКА" in canon
    assert "response_act=summarization" in canon
    assert "structure=summary" in canon
    assert "external_claims" in canon
    # Нормативная часть: сводка без вердиктов, проверка не переписывает
    # пересказ, история неизменна.
    assert "собственных вердиктов не выносит" in canon
    assert "уже сделанный пересказ не переписывает" in canon
    assert "Исходные сообщения в обеих фазах неизменны" in canon
    # W17c (блокер ревью): приоритет над правилом 7 обязан стоять В ТОМ ЖЕ
    # блоке. Без него в одном payload живут два взаимоисключающих указания
    # («обобщить материал → research» против «свод → summarization»), и
    # планировщик может вернуть research, потеряв маркер сводки.
    assert "это правило старше правила 7" in canon
    assert "в response_act=research не превращает" in canon
    # Разрешение конфликта — приоритетом, а не правкой правила 7: его текст
    # (и весь owner-текст) на месте байт-в-байт.
    assert "обобщить сообщения, переписку, историю" in canon
    assert "Материал важнее оценки" in canon
    # Печать и метка — та же ревизия, что в реестре (канон не «висит» мимо).
    label, seal = pr.FACTORY_REVISION_SEALS["direct.base.l1_planner"]
    assert label == "l1-planner-decision-profile"
    assert pr.FACTORY_REVISION_LABELS["direct.base.l1_planner"] == label
    assert pr.sha12(pr.factory_text("direct.base.l1_planner")) == seal
    assert pr.seal_integrity() == {}


def test_scenario25_plan_keeps_phases_distinguishable():
    """План по сценарию 25 несёт ОБА маркера; чистая сводка — только свой."""
    mixed = l1.normalize_l1_plan({
        "action": "reply",
        "response_act": "summarization",
        "structure": "summary",
        "extent": "detailed",
        "confidence": 0.8,
        "external_claims": [
            {"entity": "модель X", "relation": "spec",
             "metric": "частота decode"},
            {"entity": "модель X", "relation": "spec",
             "metric": "частота prefill"},
        ],
    })
    assert mixed is not None
    assert mixed.response_act == "summarization"
    assert mixed.structure == "summary"
    assert len(mixed.external_claims) == 2
    assert {c["metric"] for c in mixed.external_claims} == {
        "частота decode", "частота prefill"}

    summary_only = l1.normalize_l1_plan({
        "action": "reply",
        "response_act": "summarization",
        "structure": "summary",
        "confidence": 0.8,
    })
    assert summary_only is not None
    assert summary_only.structure == "summary"
    # Фаза проверки не «угадывается»: её нет, и это видно по плану.
    assert summary_only.external_claims == ()


def test_scenario25_check_phase_reaches_runtime_policy():
    """Фаза проверки не проглатывается правилом «это пересказ».

    Пересказ поданного текста (``transformed_only``) — законное основание НЕ
    искать. Но если в том же ходе запрошена проверка, claim'ы плана не дают
    этому правилу погасить фазу: политика обязана оставить проверку.
    """
    plan = l1.normalize_l1_plan({
        "action": "reply",
        "response_act": "summarization",
        "structure": "summary",
        "confidence": 0.8,
        "external_claims": [
            {"entity": "модель X", "relation": "spec", "metric": "частота"},
        ],
    })
    supplied = ep.SuppliedSources(text="Иван: 5 ГГц.", transformed_only=True)
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="summarization",
        explicit=ep.ExplicitRequest(), supplied=supplied,
        runtime_state=ep.RuntimeState())
    assert decision.required is True
    assert decision.note == "external_claims"
    assert len(decision.claims) == 1
    assert decision.skip_reason is None

    # Чистый пересказ (без фазы проверки) остаётся трансформацией: поиска нет.
    summary_only = l1.normalize_l1_plan({
        "action": "reply",
        "response_act": "summarization",
        "structure": "summary",
        "confidence": 0.8,
    })
    quiet = ep.evaluate_evidence_need(
        plan=summary_only, task_kind="summarization",
        explicit=ep.ExplicitRequest(), supplied=supplied,
        runtime_state=ep.RuntimeState())
    assert quiet.required is False
    assert quiet.skip_reason is ep.EvidenceSkipReason.\
        TEXT_TRANSFORM_OR_TRANSLATION
    assert quiet.claims == ()


def test_scenario25_factcheck_phase_does_not_rewrite_summary():
    """Egress фазы проверки снимает ТОЛЬКО её claim, пересказ не переписан.

    Сценарий 25: сводка остаётся сводкой. Атрибутированный пересказ чужой
    речи не является нашим claim и не может быть вырезан; неподтверждённое
    утверждение фазы проверки — может (и только оно).
    """
    plan = l1.normalize_l1_plan({
        "action": "reply",
        "response_act": "summarization",
        "structure": "summary",
        "confidence": 0.8,
        "external_claims": [
            {"entity": "модель X", "relation": "spec", "metric": "частота"},
        ],
    })
    decision = ep.evaluate_evidence_need(
        plan=plan, task_kind="summarization", explicit=ep.ExplicitRequest(),
        supplied=ep.SuppliedSources(text="Иван: 5 ГГц.",
                                    transformed_only=True),
        runtime_state=ep.RuntimeState())
    summary_part = ("Иван говорил, что на prefill модель работает на 5 ГГц, "
                    "а Пётр утверждал, что на decode всё медленно.")
    check_part = "На decode эта же модель выдаёт 2.5 ГГц."
    answer = summary_part + "\n" + check_part

    # Сводка — чужая атрибутированная речь: под egress не попадает.
    assert ep.is_attributed_speech(summary_part) is True

    first = ep.guard_egress(answer=answer, decision=decision, evidence_text="")
    assert first.action == ep.GUARD_ONE_LOOKUP
    assert first.sentence == check_part
    second = ep.guard_egress(answer=answer, decision=decision,
                             evidence_text="", lookup_used=True)
    assert second.action == ep.GUARD_HINT_RETRY
    third = ep.guard_egress(answer=answer, decision=decision,
                            evidence_text="", lookup_used=True,
                            retry_used=True)
    assert third.action == ep.GUARD_DROP_CLAIM
    assert third.sentence == check_part
    assert third.reason_code == ep.REASON_EVIDENCE_CLAIM_REMOVED

    # Пересказ не переписан ни на байт: удалено ровно предложение проверки.
    remainder = ep.drop_claim_sentence(answer, third.sentence)
    assert remainder.strip() == summary_part
    assert summary_part in remainder


def test_scenario25_migration_applies_only_to_deployed_bytes():
    """Ступень W17 узнаёт ровно выложенные байты 2.58.147 и ведёт на канон.

    ASAP-FC-VOICE-01 / B добавил БОЛЕЕ НОВУЮ ступень (EVR2 → EVR3) выше по
    стеку, поэтому ступень W17 проверяется как элемент стека: правило «ступень
    узнаёт только точное совпадение байт» не изменилось.
    """
    deployed = cp.PREV_DIRECT_L1_PLANNER_EVR1
    active = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert deployed != active
    assert _sha12(deployed) == DEPLOYED_L1_SHA12
    steps = pm.PROMPT_MIGRATIONS[L1_KEY]
    assert (deployed, active) in steps
    assert steps[0] == (cp.PREV_DIRECT_L1_PLANNER_EVR2, active)
    assert steps[0][0] != active
    rollback = pm.ROLLBACK_MIGRATIONS[L1_KEY]
    assert (active, cp.PREV_DIRECT_L1_PLANNER_EVR2) in rollback
    assert (cp.PREV_DIRECT_L1_PLANNER_EVR2, deployed) in rollback
    # Кастом владельца (те же байты + хвост) ступенью не узнаётся: правка
    # привязана к точному совпадению, а не к подстроке.
    owner_tail = deployed + "\n\nмой хвост"
    assert all(old != owner_tail for old, _new in steps)


# ═══════════════════════════════════════════════════════════════════════════
#  ER-54 — prefill и decode: разные фазы, не противоречие
# ═══════════════════════════════════════════════════════════════════════════


def test_er54_phase_scope_reaches_factcheck_judge():
    """Правило фаз есть в каноне, который реально уходит судье (Stage-1)."""
    canon = fcp.FACTCHECK_ANALYST_SYSTEM_PROMPT
    assert fcp.FACTCHECK_PHASE_SCOPE_BLOCK in canon
    # ASAP-FC-VOICE-01 / A: правило фаз осталось ПОСЛЕДНЕЙ частью канона
    # (порядок не переписан), схема Stage-1 расширена двумя смысловыми полями.
    assert canon.endswith(fcp.FACTCHECK_PHASE_SCOPE_BLOCK)
    assert canon.startswith(fcp._FACTCHECK_ANALYST_SEMANTICS_BASE)
    # Именно этот текст сервис передаёт стадии-1 (`resolve_prompt` по ключу).
    resolved = resolve_prompt(FC_KEY, canon)
    assert fcp.FACTCHECK_PHASE_SCOPE_BLOCK in resolved
    # Нормативная часть: обе фазы названы и обе стороны правила есть.
    assert "prefill" in canon and "decode" in canon
    assert "не противоречат друг другу" in canon
    assert "только внутри одной фазы" in canon
    assert "не заменяют технический анализ" in canon
    label, seal = pr.FACTORY_REVISION_SEALS["factcheck.base.analyst"]
    assert label == "factcheck-analyst-voice01-semantics"
    assert pr.FACTORY_REVISION_LABELS["factcheck.base.analyst"] == label
    assert pr.sha12(pr.factory_text("factcheck.base.analyst")) == seal
    assert pr.seal_integrity() == {}


def test_er54_phase_scope_is_not_a_general_licence():
    """Правило не растекается по чужим канонам (иначе «противоречий нет»)."""
    clause = fcp.FACTCHECK_PHASE_SCOPE_BLOCK
    for block_id in ("summary.base.single", "summary.base.l2_writer",
                     "direct.base.l2_writer", "direct.base.l1_planner"):
        assert clause not in pr.factory_text(block_id), block_id
        assert "prefill" not in pr.factory_text(block_id), block_id


def test_er54_two_phase_statements_are_never_one_proposition():
    """Фразы о разных фазах не сводятся в одну проверяемую пропозицию."""
    units = fp.build_claim_units(
        [], "На prefill эта модель работает на 5 ГГц. "
            "На decode эта же модель работает на 2.5 ГГц.")
    assert len(units) == 2
    prefill, decode = units
    # Каждая часть несёт ТОЛЬКО свою метрику: числа фаз не смешаны, значит
    # сравнение «декод против префилла» в пайплайне не выполняется вовсе.
    assert prefill.metrics == ("5 Г",)
    assert decode.metrics == ("2.5 Г",)
    assert "2.5" not in prefill.text
    # Число префилла не встречается в части декода (подстрока "2.5" не в счёт).
    assert " на 5 ГГц" not in decode.text
    # Контрпример к «просто не сравнивать»: если бы фазы слили в одну часть,
    # собственное число уже спорило бы с источником о ДРУГОЙ фазе. Проверяем,
    # что такой слитой части в пайплайне не появляется.
    merged = [u for u in units
              if " на 5 ГГц" in u.text and " на 2.5 ГГц" in u.text]
    assert merged == []


def test_er54_same_phase_contradiction_is_still_flagged():
    """Настоящее противоречие внутри одной фазы по-прежнему ловится."""
    claim = fp.build_claim_units(
        [], "На decode эта модель работает на 5 ГГц.")[0]
    run = fp._ClaimRun(claim)
    run.attempts = 1
    support = fp.EvidenceRef(
        evidence_id="e1", url="https://a.test/1",
        support="На decode эта модель работает на 5 ГГц.")
    against = fp.EvidenceRef(
        evidence_id="e2", url="https://b.test/2",
        support="На decode эта модель работает на 2.5 ГГц.")
    run.bound[run.key(support)] = (support, fp.EVIDENCE_ROLE_SUPPORTS, "")
    run.bound[run.key(against)] = (
        against, fp.EVIDENCE_ROLE_CONTRADICTS, "числа расходятся")
    coverage = fp._finalize_claim(run)
    assert coverage.outcome == fp.CLAIM_OUTCOME_CONFLICTING
    assert coverage.status_detail == fp.CLAIM_STATUS_CONFLICTING
    assert fp.CLAIM_OUTCOME_REASON[coverage.status_detail] == \
        "contradictory_evidence"

    # Только противоречащее доказательство без поддержки — опровержение,
    # а не «противоречие»: правило фаз не смягчает сам разбор.
    refuted = fp._ClaimRun(claim)
    refuted.attempts = 1
    refuted.bound[refuted.key(against)] = (
        against, fp.EVIDENCE_ROLE_CONTRADICTS, "числа расходятся")
    outcome = fp._finalize_claim(refuted)
    assert outcome.outcome == fp.CLAIM_OUTCOME_REFUTED


def test_er54_migration_applies_only_to_deployed_bytes():
    """Ступень узнаёт ровно выложенные байты канона Аналитика 2.58.148.

    ASAP-FC-VOICE-01 / A добавил новую первую ступень: байты прода 2.58.148
    (2.58.147 + правило фаз) → редакция с двумя смысловыми полями. Ступень
    ER-54 (2.58.147) остаётся в лестнице и ведёт на тот же активный канон.
    """
    deployed = fcp.PREV_FACTCHECK_ANALYST_VOICE01
    active = fcp.FACTCHECK_ANALYST_SYSTEM_PROMPT
    assert deployed != active
    assert _sha12(deployed) == DEPLOYED_FC_ANALYST_SHA12
    assert _sha12(fcp.PREV_FACTCHECK_ANALYST_PHASE_SCOPE) == \
        DEPLOYED_FC_ANALYST_PHASE_SHA12
    steps = pm.PROMPT_MIGRATIONS[FC_KEY]
    assert steps[0] == (deployed, active)
    assert (fcp.PREV_FACTCHECK_ANALYST_PHASE_SCOPE, active) in steps
    rollback = pm.ROLLBACK_MIGRATIONS[FC_KEY]
    assert rollback[0] == (active, deployed)
    owner_tail = deployed + "\n\nмой хвост"
    assert all(old != owner_tail for old, _new in steps)


# ═══════════════════════════════════════════════════════════════════════════
#  W17b — то же правило в ОДИНОЧНОМ каноне фактчека (путь fallback)
# ═══════════════════════════════════════════════════════════════════════════


def test_er54_single_stage_rule_reaches_effective_payload():
    """Правило фаз есть в каноне одиночной стадии — и в том виде, что уходит."""
    canon = fcp.FACTCHECK_SYSTEM_PROMPT
    assert fcp.FACTCHECK_PHASE_SCOPE_CORE in canon
    assert fcp.FACTCHECK_PHASE_SCOPE_TITLE in canon
    # Сервис собирает system prompt так: resolve_prompt + подстановка лимита.
    effective = resolve_prompt(FC_SINGLE_KEY, canon).replace(
        "{max_symbols}", "4000")
    assert fcp.FACTCHECK_PHASE_SCOPE_CORE in effective
    assert "{max_symbols}" not in effective
    # Прежний owner-абзац R46-4 остаётся последним: правило вставлено ПЕРЕД ним,
    # порядок канона не переписан.
    assert effective.rstrip().endswith(
        "используй её, чтобы унизить оппонента своими знаниями.")
    assert effective.rfind(fcp.FACTCHECK_PHASE_SCOPE_BLOCK) < \
        effective.rfind("Если в блоке <bot_knowledge>")


def test_er54_both_stages_share_the_same_normative_core():
    """Эквивалентность стадий — совпадение байт нормативного ядра, не пересказ."""
    core = fcp.FACTCHECK_PHASE_SCOPE_CORE
    analyst = fcp.FACTCHECK_ANALYST_SYSTEM_PROMPT
    single = fcp.FACTCHECK_SYSTEM_PROMPT
    assert core in analyst and core in single
    # Ядро входит в оба канона ровно один раз (нет второго, «смягчённого»).
    assert analyst.count(core) == 1
    assert single.count(core) == 1
    # Блок каждой стадии — заголовок + то же ядро.
    block = fcp.FACTCHECK_PHASE_SCOPE_TITLE + "\n" + core
    assert fcp.FACTCHECK_PHASE_SCOPE_BLOCK == block
    assert block in analyst and block in single
    # Обе ревизии зарегистрированы и целы.
    assert pr.FACTORY_REVISION_LABELS["factcheck.base.analyst"] == \
        "factcheck-analyst-voice01-semantics"
    # ASAP-FC-VOICE-01 / A: одиночный канон получил вторую правку (снята
    # директива «торопливое письмо»), метка поднята поверх ER-54.
    assert pr.FACTORY_REVISION_LABELS["factcheck.base.single"] == \
        "factcheck-single-voice01"
    assert pr.sha12(pr.factory_text("factcheck.base.single")) == \
        pr.FACTORY_REVISION_SEALS["factcheck.base.single"][1]
    assert pr.seal_integrity() == {}


def test_er54_single_migration_applies_on_deployed_bytes_only():
    """Ступень узнаёт ровно выложенные байты одиночного канона 2.58.147.

    ASAP-FC-VOICE-01 / A добавил верхнюю ступень (байты 2.58.148 → канон без
    директивы «торопливое письмо»); ступень ER-54 осталась в лестнице второй и
    по-прежнему ведёт на тот же активный канон.
    """
    deployed = fcp.PREV_FACTCHECK_SINGLE_PHASE_SCOPE
    active = fcp.FACTCHECK_SYSTEM_PROMPT
    assert deployed != active
    assert _sha12(deployed) == DEPLOYED_FC_SINGLE_SHA12
    assert _sha12(fcp.PREV_FACTCHECK_SINGLE_VOICE01) == \
        DEPLOYED_FC_SINGLE_VOICE01_SHA12
    steps = pm.PROMPT_MIGRATIONS[FC_SINGLE_KEY]
    assert steps[0] == (fcp.PREV_FACTCHECK_SINGLE_VOICE01, active)
    assert steps[1] == (deployed, active)
    rollback = pm.ROLLBACK_MIGRATIONS[FC_SINGLE_KEY]
    assert rollback[0] == (active, fcp.PREV_FACTCHECK_SINGLE_VOICE01)
    assert rollback[1] == (fcp.PREV_FACTCHECK_SINGLE_VOICE01, deployed)
    # Кастом владельца (те же байты + хвост) ступенью не узнаётся.
    owner_tail = deployed + "\n\nмой хвост"
    assert all(old != owner_tail for old, _new in steps)


def test_er54_single_migration_preserves_owner_edit_as_revision(monkeypatch):
    """Правка владельца не теряется: она становится ревизией журнала.

    Действующая политика (решение владельца 29.10.2026, EVOL-012) активирует
    новую заводскую ревизию ПО МЕТКЕ, в том числе поверх ручной правки; сама
    правка сохраняется неизменяемой записью журнала. Поэтому «не перетирать
    кастом» проверяется двумя фактами: ступень не матчит кастом по байтам
    (см. тест выше) и текст владельца остаётся в журнале после прогона.
    """
    import asyncio

    from services import prompt_release_policy as prp

    store = prp.MemoryPromptJournal()
    monkeypatch.setattr(prp, "default_journal", lambda cache=None: store)
    try:
        custom = fcp.FACTCHECK_SYSTEM_PROMPT + "\n\nвладельческая строка"

        class Cache:
            pg_available = True

            def __init__(self, values):
                self.values = dict(values)

            def get(self, key, default=None):
                return self.values.get(key, default)

            async def set(self, key, value, category):
                self.values[key] = value

        cache = Cache({FC_SINGLE_KEY: custom})
        report = asyncio.run(pm.migrate_prompt_canons(cache))
        assert report.get(FC_SINGLE_KEY) in ("updated", "same")
        # Активна заводская ревизия (по метке), а текст владельца сохранён.
        assert cache.values[FC_SINGLE_KEY] == fcp.FACTCHECK_SYSTEM_PROMPT
        kept = [r for r in store.revisions.values()
                if r.pg_key == FC_SINGLE_KEY
                and r.content_sha12 == pr.sha12(custom)]
        assert len(kept) == 1
        assert kept[0].body == custom

        # Повторный прогон на тех же байтах — no-op: ничего не перезаписано.
        before = (len(store.revisions), len(store.activations))
        again = asyncio.run(pm.migrate_prompt_canons(cache))
        assert again.get(FC_SINGLE_KEY) == "same"
        assert (len(store.revisions), len(store.activations)) == before
    finally:
        pr.set_release_policy_active(False)
        from services import prompt_factory as pf
        pf._HISTORY_FROZEN = False
        pr.reset_cache()


def test_er54_doc_block_and_code_canon_are_byte_identical():
    """Пин эталона: документ Section 72 и код — одни и те же байты."""
    doc = _doc_section72_canon()
    assert doc == fcp.FACTCHECK_SYSTEM_PROMPT
    assert _sha12(doc) == pr.FACTORY_REVISION_SEALS["factcheck.base.single"][1]
    assert fcp.FACTCHECK_PHASE_SCOPE_CORE in doc
