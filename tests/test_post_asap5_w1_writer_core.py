# -*- coding: utf-8 -*-
"""POST-ASAP5 CORRECTIVE W1 — L1/writer core (§3, §7, §8).

Источник: plans/features/post-asap5-corrective/source-2026-10-27.md
(строки §3.1=92-159, §7=371-434, §8=437-478; verbatim-якорь §8 — строка 473).

Контрактные проверки (CONTRACT/REGRESSION), payload-level, 0 LLM:
* §3.1: канон L1 получил секцию понимания меняющейся задачи — семантическую,
  без хардкода слов/фраз инцидента и без квот; различаются уточнение условий
  той же задачи / возражение / новый вопрос / продолжение без изменений;
* §3.2: запрет искусственных противоречий в обе стороны (не опровержение —
  если не противоречит; не смена темы — если противоречит) + допущение
  держится допущением, а не требованием человека;
* §7.1: прежний ответ бота — контекст, а не доказательство (канон L1);
  self-echo из фактического RAG исключён ранее (проверяется существующим
  интеграционным тестом test_asap5_integration_w3::test_d12_self_echo_excluded
  и origin-фильтрами database.py — здесь фиксируется диалоговое правило);
* §7.2: характер сохраняется (Core не тронут), но стиль не защищает ошибку:
  директива владельца §8 едет в существующем plan-блоке L2 РОВНО один раз;
* §7.3: запрет ложной симметрии (подтверждённое возражение не обесценивается;
  обе неподтверждённые — так и сказать);
* §8: verbatim-якорь (строка 473) байт-в-байт; один носитель — план; без
  нового слоя Composer, без дублирования в Core/Expression/Humor/Writer-каноне,
  без квот и обязательной композиции; NO_META (анонсы) и DELTA (research)
  не регрессируют и не дублируют директиву;
* лестница ADR-1013-3: слепок PREV_DIRECT_L1_PLANNER_PA5W1 = байты ред.4
  (sha12 422e9d73d316), ступень + откат на месте, кастом владельца не трогается.

TEST-LIFECYCLE: CONTRACT owner=post-asap5-corrective/W1
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest

from services import chat_prompts as cp
from services import direct_l1 as l1
from services import prompt_migrations as pm
from services import prompt_style_blocks as psb

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "plans" / "features" / "post-asap5-corrective" / \
    "source-2026-10-27.md"

L1_KEY = "prompts.direct_l1_planner_system_prompt"

#: Слова-инциденты: НЕ должны появиться ни в каноне L1, ни в директиве §8,
#: ни в plan-блоке (запрет хардкода §3.1/§11).
_INCIDENT_WORDS = ("шина", "чип", "забей", "LPDDR", "Crescent", "GDDR",
                   "5060", "фотонн", "интерконнект")


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _source_directive() -> str:
    """Verbatim-якорь §8 (строка 473) прямо из снапшота источника."""
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    raw = lines[472].strip()
    assert raw.startswith('"') and raw.endswith('"'), raw
    return raw[1:-1]


def _plan(**kwargs) -> l1.L1Plan:
    base = dict(action="reply", response_act="answer", extent="compact",
                structure="chat", delivery_hint="plain")
    base.update(kwargs)
    return l1.L1Plan(**base)


def _payload(plan, *, include_delta: bool | None = None,
             include_analysis: bool | None = None,
             modes_on: bool = True) -> tuple[str, str, str]:
    """Та же сборка payload, что у Writer: system + plan-блок + closing."""
    delta = (l1.delta_instruction_needed(plan) if include_delta is None
             else include_delta)
    analysis = (l1.analysis_directive_needed(plan, modes_on=modes_on)
                if include_analysis is None else include_analysis)
    block = l1.build_l2_plan_block(plan, include_analysis=analysis,
                                   include_delta=delta, modes_on=modes_on)
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", l1.plan_response_mode(plan),
        "plain", html_safe=True,
        extent_block=__import__("services.response_extent",
                                fromlist=["render_extent_block"])
        .render_extent_block(plan.to_response_plan()))
    closing = psb.NO_META_CLOSING_TEXT.strip()
    payload = system + "\n\n" + block + "\n\n" + closing
    return payload, block, system


# ═══ §8. Директива фокуса: verbatim, один носитель, без дублей ══════════════

def test_focus_directive_verbatim_from_source():
    assert psb.WRITER_FOCUS_DIRECTIVE_TEXT == _source_directive()
    assert psb.WRITER_FOCUS_DIRECTIVE_TEXT.startswith("Спорь и шути свободно")
    assert psb.WRITER_FOCUS_DIRECTIVE_TEXT.endswith(
        "не заменяй расчёт насмешками.")


@pytest.mark.parametrize("plan_kwargs", [
    dict(response_act="answer", extent="compact", structure="chat"),
    dict(response_act="chat", extent="micro", structure="chat"),
    dict(response_act="research", extent="normal", structure="answer"),
    dict(response_act="research", extent="auto", structure="report",
         delivery_hint="rich"),
])
def test_focus_rides_plan_block_exactly_once(plan_kwargs):
    plan = _plan(**plan_kwargs)
    payload, block, system = _payload(plan)
    assert payload.count(psb.WRITER_FOCUS_DIRECTIVE_TEXT) == 1
    assert block.count(psb.WRITER_FOCUS_DIRECTIVE_TEXT) == 1
    # носитель — план: system-канон директиву не содержит
    assert psb.WRITER_FOCUS_DIRECTIVE_TEXT not in system


def test_focus_line_labeled_and_no_composition_mandate():
    plan = _plan()
    block = l1.build_l2_plan_block(plan)
    line = next(ln for ln in block.splitlines()
                if psb.WRITER_FOCUS_DIRECTIVE_TEXT in ln)
    assert line.startswith("фокус ответа: ")
    # без квот и обязательной композиции: ни чисел-лимитов, ни порядка
    for banned in ("символов", "токен", "знаков", "сначала", "первым "
                   "предложением", "обязательно начни"):
        assert banned not in line.lower()


def test_focus_fallback_plan_also_carries_once():
    fb = l1.fallback_plan("посчитай")
    block = l1.build_l2_plan_block(fb)
    assert block.count(psb.WRITER_FOCUS_DIRECTIVE_TEXT) == 1


def test_focus_no_duplicate_carriers_anywhere():
    """Единственный носитель — план: ни режимных блоков, ни канона Writer,
    ни Core/Expression/Humor (§8: не дублировать в Personality Core,
    Expression, Humor и Writer)."""
    focus = psb.WRITER_FOCUS_DIRECTIVE_TEXT
    assert focus not in psb.MODE_DEEP_RESEARCH_BLOCK
    assert focus not in psb.MODE_CASUAL_BLOCK
    assert focus not in psb.MODE_SERIOUS_BLOCK
    assert focus not in psb.NO_META_STRUCTURE_TEXT
    assert focus not in psb.NO_META_CLOSING_TEXT
    assert focus not in cp.DIRECT_VERBALIZER_SYSTEM_PROMPT
    assert focus not in cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert focus not in cp.PERSONALITY_CORE_FULL_TEXT
    assert focus not in cp.PERSONALITY_CORE_COMPACT_TEXT
    from services import mca_expression as expr
    for text in (expr.BASE_SPEECH_TEXT, expr.HUMOR_TEXT,
                 expr.RESPONSE_LENGTH_TEXT, expr.FACTUAL_SPEECH_TEXT):
        assert focus not in text


def test_focus_coexists_with_no_meta_and_delta_without_duplication():
    """research-ответ: директива ×1, DELTA ×1, NO_META ×1 — сосуществование
    без дублирования (каждый текст — один раз на payload)."""
    plan = _plan(response_act="research", extent="normal", structure="answer")
    payload, block, system = _payload(plan)
    assert payload.count(psb.WRITER_FOCUS_DIRECTIVE_TEXT) == 1
    assert payload.count(psb.DELTA_READY_INSTRUCTION_TEXT) == 1
    assert payload.count(psb.NO_META_STRUCTURE_TEXT) == 1
    # deep_research с extent-блоком: режимный блок вытеснен, NO_META несёт
    # план — все три текста по одному разу
    deep = _plan(response_act="research", extent="auto", structure="report",
                 delivery_hint="rich")
    payload2, _b2, _s2 = _payload(deep)
    assert payload2.count(psb.WRITER_FOCUS_DIRECTIVE_TEXT) == 1
    assert payload2.count(psb.DELTA_READY_INSTRUCTION_TEXT) == 1
    assert payload2.count(psb.NO_META_STRUCTURE_TEXT) == 1


# ═══ §3.1/§3.2/§7. Канон L1: секция понимания меняющейся задачи ════════════

def test_l1_intent_update_section_present_once_before_rules():
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    section = cp._DIRECT_L1_INTENT_UPDATE_PA5
    assert canon.count(section) == 1
    assert "ИЗМЕНЕНИЕ ЗАДАЧИ И ВОЗРАЖЕНИЯ" in section
    # после контракта уточнений/продолжения, до ПРАВИЛ
    assert canon.index("УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА") < \
        canon.index(section) < canon.index("ПРАВИЛА:")


def test_l1_intent_update_semantic_anchors():
    section = cp._DIRECT_L1_INTENT_UPDATE_PA5
    # §3.1: перечитывание актуального сообщения, пересмотр постановки
    for anchor in ("Перечитывай актуальное сообщение каждый ход",
                   "действующая постановка задачи задаётся текущей "
                   "формулировкой человека",
                   "рабочая гипотеза"):
        assert anchor in section, anchor
    # различение четырёх случаев — по категориям, без слов-триггеров
    for anchor in ("уточнение условий той же задачи",
                   "возражение против твоего предыдущего ответа",
                   "новый самостоятельный вопрос",
                   "продолжение темы без изменений"):
        assert anchor in section, anchor
    # снятые условия больше не обязательны; история сохраняется
    assert "условия, которые человек снял, перестают быть обязательными" \
        in section
    assert "полезная история сохраняется" in section
    # §3.2: обе стороны искусственного противоречия + допущение
    assert "не трактуй его как опровержение" in section
    assert "не называй это сменой темы" in section
    assert "допущение назови допущением, а не требованием человека" in section
    assert "вместо бесконечных уточняющих вопросов" in section
    # §7.1: прежний ответ — не доказательство
    assert "Твой предыдущий ответ - контекст, а не доказательство" in section
    # §7.3: без ложной симметрии, честная неопределённость
    assert "не объявляй позицию человека неподтверждённой автоматически" \
        in section
    assert "когда обе стороны не подтверждены - так и скажи" in section
    # §7.3/10.3: возражение — по данным, не по настойчивости
    assert "отклоняется аргументами, а не настойчивостью собеседника" \
        in section
    # §3.2 (классификация): disagreement только при реальном споре
    assert "disagreement - только когда сообщение действительно оспаривает" \
        in section


def test_l1_intent_update_no_hardcode_no_quota_no_style_ban():
    section = cp._DIRECT_L1_INTENT_UPDATE_PA5
    joined = section + psb.WRITER_FOCUS_DIRECTIVE_TEXT
    # запрет хардкода слов/фраз инцидента (§3.1 «Не создавать хардкод»)
    for word in _INCIDENT_WORDS:
        assert word.lower() not in joined.lower(), word
    # языковая дисциплина: без ёлочек и длинных тире (прецедент R5/R9)
    assert "«" not in section and "»" not in section
    assert "—" not in section
    # без квот/лимитов (ADDENDUM #3 §2.10) и без шаблона речи
    for banned in ("символов", "токен", "знаков", "обязательная структура",
                   "шаблон ответа"):
        assert banned not in section.lower()
    # это внутренняя логика корректировки, а не структура сообщения (§7.1)
    assert "ИЗМЕНЕНИЕ ЗАДАЧИ" in section


def test_l1_canon_persona_and_rules_bytes_preserved():
    """§7.2/§8: характер не тронут; правила 1-9 канона байт-в-байт; база,
    контракт уточнений и продолжение прежние (единственная дельта — секция)."""
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    prev = cp.PREV_DIRECT_L1_PLANNER_PA5W1
    # канон = прежние байты + секция, вставленная между продолжением и правилами
    head, tail = prev.rsplit(cp._DIRECT_L1_PLANNER_RULES, 1)
    assert canon == head + cp._DIRECT_L1_INTENT_UPDATE_PA5 + \
        cp._DIRECT_L1_PLANNER_RULES
    assert canon.count(cp._DIRECT_L1_CLARIFICATION_CONTRACT) == 1
    assert canon.count(cp._DIRECT_L1_CONTINUATION_R3B) == 1
    assert canon.count(cp._DIRECT_L1_PLANNER_RULES) == 1
    # Core: характер сохранён, корректность не подчинена стилю (§7.2)
    assert "Резкость не заменяет мысль" in cp.PERSONALITY_CORE_FULL_TEXT
    assert "подменять проверяемое утверждение красивой догадкой" in \
        cp.CORE_FREE_SPEECH_PARAGRAPH


# ═══ §7.1. Диалоговое правило + self-echo (носители существующие) ══════════

def test_previous_answer_authority_rule_in_canon():
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert "Новые проверяемые данные и уточнения человека приоритетнее него" \
        in canon
    assert "не защищай прежний вывод вопреки им" in canon


def test_self_echo_protection_still_in_place():
    """Существующая защита self-echo не регрессировала: инструкция эха,
    origin-метка и SQL-фильтр прямого RAG на месте (конец-в-конец проверяется
    интеграционным test_d12_self_echo_excluded)."""
    from services.summary_memory import _SELF_ECHO_INSTRUCTION
    assert "ПРОШЛЫЕ слова" in _SELF_ECHO_INSTRUCTION
    assert "критически" in _SELF_ECHO_INSTRUCTION
    src = (ROOT / "services" / "database.py").read_text(encoding="utf-8")
    # прямой RAG: origin='bot_direct_reply' исключается из выборки фактов
    assert "AND f.origin != 'bot_direct_reply'" in src


# ═══ Лестница ADR-1013-3: слепок ред.4, ступень, откат ═════════════════════

def test_pa5w1_snapshot_is_exact_previous_active_bytes():
    prev = cp.PREV_DIRECT_L1_PLANNER_PA5W1
    assert prev == (cp._DIRECT_L1_PLANNER_BASE_R3
                    + cp._DIRECT_L1_CLARIFICATION_CONTRACT
                    + cp._DIRECT_L1_CONTINUATION_R3B
                    + cp._DIRECT_L1_PLANNER_RULES)
    # прежний активный пин (ред.4) сохранён байт-в-байт
    assert len(prev) == 9750 and _sha12(prev) == "422e9d73d316"
    assert prev != cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert _sha12(cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT) == "902dd00edf52"
    assert "ИЗМЕНЕНИЕ ЗАДАЧИ И ВОЗРАЖЕНИЯ" not in prev


def test_pa5w1_migration_step_and_rollback_head():
    steps = dict(pm.PROMPT_MIGRATIONS[L1_KEY])
    assert steps[cp.PREV_DIRECT_L1_PLANNER_PA5W1] == \
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert pm.ROLLBACK_MIGRATIONS[L1_KEY][0] == (
        cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT,
        cp.PREV_DIRECT_L1_PLANNER_PA5W1)
    assert pm.ROLLBACK_MIGRATIONS[L1_KEY][1] == (
        cp.PREV_DIRECT_L1_PLANNER_PA5W1,
        cp.PREV_DIRECT_L1_PLANNER_P0CINTR2)
    from services import prompt_registry as pr
    assert pr.is_known_canon(cp.PREV_DIRECT_L1_PLANNER_PA5W1)
    assert "l1-planner-intent-update" in pr.factory_revision(
        "direct.base.l1_planner")
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12


# ═══ §11-гварды карты: без новых слоёв/вызовов/маршрутизаторов ═════════════

def test_no_new_layers_or_routers_introduced():
    """§5.3/§11: ни нового маршрутизатора, ни дублирующего Fact-check, ни
    новых обязательных LLM-вызовов — правки только в существующих каноне L1
    и plan-блоке (строковая сборка, 0 LLM)."""
    src_l1 = (ROOT / "services" / "direct_l1.py").read_text(encoding="utf-8")
    assert "WRITER_FOCUS_DIRECTIVE_TEXT" in src_l1
    # носитель — строка план-блока, не новый вызов/слой
    assert "фокус ответа: " in src_l1
    src_chats = (ROOT / "services" / "chat_prompts.py").read_text(
        encoding="utf-8")
    assert "_DIRECT_L1_INTENT_UPDATE_PA5" in src_chats
    # directive не создаёт новых composer-слоёв: имя не появляется в
    # prompt_composer
    composer_src = (ROOT / "services" / "prompt_composer.py").read_text(
        encoding="utf-8")
    assert "WRITER_FOCUS_DIRECTIVE_TEXT" not in composer_src
