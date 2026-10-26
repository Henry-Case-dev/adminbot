# -*- coding: utf-8 -*-
"""P0 DELTA-DEPTH (26.10.2026) — дословная инструкция §11 в Analysis/Writer.

Источник: plans/features/p0-delta-analysis/source-2026-10-26.md (строки
128-136, §11 «Разделить исследование и способ ответа»); открытые строки
карты M00128/M00129/M00136, M00026 и note-row S03 (writer-conclusions).

Контрактные проверки (CONTRACT/REGRESSION), payload-level:
* текст инструкции владельца (строки 129-134) совпадает с исходником
  ДОСЛОВНО, без добавленных структур/схем/примеров/чисел;
* носитель один — существующий plan-блок L2 (`build_l2_plan_block`),
  НИКАКОГО нового слоя/LLM-вызова; research/deep-ответ получают текст
  ровно один раз на payload, casual/answer остаётся без него;
* требование выводов по существу (вместо отчёта о покрытии — дефект S03)
  едет рядом без фиксированных количеств и обязательной композиции;
* NO_META не затронут (только запрет анонсов) — конфликта нет.
"""
from __future__ import annotations

import pathlib

import pytest

from services import direct_l1 as l1
from services import prompt_style_blocks as psb
from services import response_extent as _extent

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "plans" / "features" / "p0-delta-analysis" / \
    "source-2026-10-26.md"

#: Строки источника с готовой инструкцией (1-based, включительно).
SRC_LINES = range(129, 135)


def _source_instruction() -> str:
    """Вербатим-текст §11 прямо из снапшота источника (read-only)."""
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()[SRC_LINES.start - 1:SRC_LINES.stop - 1]
    assert len(lines) == 6, lines
    joined = " ".join(part.strip() for part in lines)
    assert joined.startswith("«") and joined.endswith("»"), joined
    return joined[1:-1]


def _research_plan(**kwargs) -> l1.L1Plan:
    base = dict(action="reply", response_act="research", extent="normal",
                structure="answer", delivery_hint="plain")
    base.update(kwargs)
    return l1.L1Plan(**base)


def _payload(plan, include_analysis: bool) -> str:
    """Тот же способ сборки payload, что у Writer (system+plan+closing)."""
    block = l1.build_l2_plan_block(
        plan, include_analysis=include_analysis,
        include_delta=l1.delta_instruction_needed(plan))
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", l1.plan_response_mode(plan),
        "plain", html_safe=True,
        extent_block=_extent.render_extent_block(plan.to_response_plan()))
    closing = psb.NO_META_CLOSING_TEXT.strip()
    return system + "\n\n" + block + "\n\n" + closing, block, system


# ── 1. Вербатим §11 (M00129) ───────────────────────────────────────────────

def test_delta_instruction_is_verbatim_from_source():
    assert psb.DELTA_READY_INSTRUCTION_TEXT == _source_instruction()
    # ключевые фразы приёмки карты присутствуют дословно
    assert ("Самостоятельно выбирай естественную форму, длину и тон "
            "ответа") in psb.DELTA_READY_INSTRUCTION_TEXT
    assert ("используя релевантные сведения из разговора, истории и "
            "памяти") in psb.DELTA_READY_INSTRUCTION_TEXT


def test_delta_instruction_not_in_mode_blocks():
    """Инструкция НЕ в режиме/каноне deep_research: носитель один — план,
    фабричные тексты реестра не меняются (фингерпринт набора не трогаем)."""
    assert psb.DELTA_READY_INSTRUCTION_TEXT not in psb.MODE_DEEP_RESEARCH_BLOCK
    assert psb.DELTA_SUBSTANCE_TEXT not in psb.MODE_DEEP_RESEARCH_BLOCK
    # прежние контракты deep-режима не переехали
    assert psb.ANALYSIS_DIRECTIVE_TEXT in psb.MODE_DEEP_RESEARCH_BLOCK
    assert psb.NO_META_STRUCTURE_TEXT in psb.MODE_DEEP_RESEARCH_BLOCK


# ── 2. Предикат: research/deep — да, casual/answer — нет ──────────────────

def test_predicate_matrix():
    assert l1.delta_instruction_needed(_research_plan()) is True
    deep_auto = _research_plan(delivery_hint="rich", extent="auto",
                               structure="report")
    assert l1.plan_response_mode(deep_auto) == "deep_research"
    assert l1.delta_instruction_needed(deep_auto) is True
    # report/rich при answer-акте — тоже содержательный ответ §11
    deep_answer = l1.L1Plan(action="reply", response_act="answer",
                            extent="normal", structure="report")
    assert l1.delta_instruction_needed(deep_answer) is True
    # короткие бытовые ответы — без инструкции (payload не раздувается)
    casual = l1.L1Plan(action="reply", response_act="chat",
                       extent="compact", structure="chat")
    assert l1.delta_instruction_needed(casual) is False
    plain_answer = l1.L1Plan(action="reply", response_act="answer",
                             extent="compact", structure="chat")
    assert l1.delta_instruction_needed(plain_answer) is False
    assert l1.delta_instruction_needed(None) is False

    def _kind_stub(kind: str):
        class _RP:  # ResponsePlan-подобный объект (task_kind)
            response_act = ""
            task_kind = kind
            structure = "answer"
            delivery_hint = "plain"
        return _RP()

    assert l1.delta_instruction_needed(_kind_stub("research")) is True
    assert l1.delta_instruction_needed(_kind_stub("chat")) is False


# ── 3. Ровно один раз на research/deep-ответе (M00128/M00129) ─────────────

def test_research_payload_has_instruction_exactly_once():
    plan = _research_plan()
    payload, block, system = _payload(plan, include_analysis=True)
    assert l1.delta_instruction_needed(plan) is True
    assert payload.count(psb.DELTA_READY_INSTRUCTION_TEXT) == 1
    assert payload.count(psb.DELTA_SUBSTANCE_TEXT) == 1
    assert block.count(psb.DELTA_READY_INSTRUCTION_TEXT) == 1
    assert psb.DELTA_READY_INSTRUCTION_TEXT not in system
    # по умолчанию (флаг не запрошен) дельта-текстов нет — контракт прежний
    plain = l1.build_l2_plan_block(plan)
    assert psb.DELTA_READY_INSTRUCTION_TEXT not in plain
    assert psb.DELTA_SUBSTANCE_TEXT not in plain


def test_deep_research_empty_extent_exactly_once():
    """deep/auto: режимный блок несёт analysis-тексты, НО не дельту;
    план — единственный носитель инструкции, дубля нет."""
    plan = _research_plan(delivery_hint="rich", extent="auto",
                          structure="report")
    assert _extent.render_extent_block(plan.to_response_plan()) == ""
    payload, block, system = _payload(plan, include_analysis=False)
    assert psb.ANALYSIS_DIRECTIVE_TEXT in system          # режимный блок
    assert psb.DELTA_READY_INSTRUCTION_TEXT not in system
    assert payload.count(psb.DELTA_READY_INSTRUCTION_TEXT) == 1
    assert payload.count(psb.DELTA_SUBSTANCE_TEXT) == 1
    assert psb.DELTA_READY_INSTRUCTION_TEXT in block


def test_deep_research_with_extent_exactly_once():
    """deep + непустой extent-блок: режимный блок вытеснен, план несёт и
    analysis-тексты, и дельту — каждая ровно один раз."""
    plan = _research_plan(delivery_hint="rich", extent="normal",
                          structure="report")
    assert _extent.render_extent_block(plan.to_response_plan()) != ""
    payload, block, system = _payload(plan, include_analysis=True)
    assert payload.count(psb.DELTA_READY_INSTRUCTION_TEXT) == 1
    assert payload.count(psb.DELTA_SUBSTANCE_TEXT) == 1
    assert payload.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert psb.DELTA_READY_INSTRUCTION_TEXT in block
    assert psb.DELTA_READY_INSTRUCTION_TEXT not in system


# ── 4. Casual/answer — payload лёгкий ──────────────────────────────────────

def test_casual_payload_stays_lean():
    casual = l1.L1Plan(action="reply", response_act="chat",
                       extent="compact", structure="chat")
    payload, block, system = _payload(casual, include_analysis=False)
    assert psb.DELTA_READY_INSTRUCTION_TEXT not in payload
    assert psb.DELTA_SUBSTANCE_TEXT not in payload
    plain_answer = l1.L1Plan(action="reply", response_act="answer",
                             extent="compact", structure="chat")
    payload2, _, _ = _payload(plain_answer, include_analysis=False)
    assert psb.DELTA_READY_INSTRUCTION_TEXT not in payload2
    assert psb.DELTA_SUBSTANCE_TEXT not in payload2


# ── 5. S03-сценарий: выводы вместо отчёта о покрытии (M00026) ─────────────

def test_stub_scenario_writer_prompt_asks_conclusions_over_coverage():
    """Многолетний анализ человека (research + evidence) — Writer-промпт
    требует содержательные выводы и честную оговорку покрытия, а не
    coverage-стаб (находка live-scenarios-r2, S03)."""
    plan = _research_plan(extent="normal")
    payload, block, _ = _payload(plan, include_analysis=True)
    substance = psb.DELTA_SUBSTANCE_TEXT
    assert substance in block
    assert "выводы по существу вопроса на основе найденного" in substance
    assert ("честно скажи, что установлено и за какой период") in substance
    assert "вместо отчёта о покрытии" in substance
    # инструкция держит внимание Writer на охвате вопроса и статусе данных
    instruction = psb.DELTA_READY_INSTRUCTION_TEXT
    assert "насколько они охватывают вопрос" in instruction
    assert "какие данные подтверждены" in instruction
    # наблюдения/предположения не выдаются за факты (честность покрытия)
    assert "не выдавай предположения за факты" in instruction
    # всё это реально в payload ровно один раз
    assert payload.count(substance) == 1
    assert payload.count(instruction) == 1


# ── 6. Без обязательных структур/схем/примеров (M00136) ───────────────────

def test_no_mandatory_structures_numbers_examples():
    for text in (psb.DELTA_READY_INSTRUCTION_TEXT,
                 psb.DELTA_SUBSTANCE_TEXT):
        # никаких чисел/количеств и списков-схем
        assert not any(ch.isdigit() for ch in text), text
        for marker in ("- ", "1.", "•", "|"):
            assert marker not in text, marker
        # никаких приказов композиции/старта/формы ответа
        for phrase in ("Во-первых", "раздел", "подзаголов", "шаг",
                       "начинай с", "начни с", "Первое предложение",
                       "первое содержательное", "обязател",
                       "схема", "формат ответа", "структуру ответа"):
            assert phrase not in text, phrase


def test_no_conflict_with_no_meta():
    """NO_META остаётся только про анонсы; дельта-тексты его не дублируют
    и не подменяют."""
    assert psb.NO_META_STRUCTURE_TEXT not in psb.DELTA_READY_INSTRUCTION_TEXT
    assert psb.NO_META_CLOSING_TEXT not in psb.DELTA_READY_INSTRUCTION_TEXT
    assert psb.NO_META_STRUCTURE_TEXT not in psb.DELTA_SUBSTANCE_TEXT
    # запрет анонсов по-прежнему в режиме и плане на casual (не тронут)
    assert psb.NO_META_STRUCTURE_TEXT in psb.MODE_DEEP_RESEARCH_BLOCK
    chat = l1.L1Plan(action="reply", response_act="chat",
                     extent="compact", structure="chat")
    assert psb.NO_META_STRUCTURE_TEXT in l1.build_l2_plan_block(chat)


# ── 7. Сервисные call-site передают тот же предикат (REGRESSION) ──────────

def test_direct_chat_call_sites_pass_delta_flag():
    src = (ROOT / "services" / "direct_chat_service.py").read_text(
        encoding="utf-8")
    # основной путь ответа и инициатива: include_delta из того же предиката
    assert src.count("include_delta=_l1.delta_instruction_needed(") == 2
    assert src.count(
        "include_delta=_l1.delta_instruction_needed(l1_plan)") == 1
    assert src.count(
        "include_delta=_l1.delta_instruction_needed(plan)") == 1
    # ни одного нового LLM-вызова/слоя полоса не добавила
    assert "delta_writer" not in src
