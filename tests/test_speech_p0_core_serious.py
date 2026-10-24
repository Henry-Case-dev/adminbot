"""SPEECH-P0-CORE-SERIOUS (25.10.2026) — активный Core, serious-разбор, L1.

Доказывает по `plans/features/asap-speech-arch/evidence/p0-hotfix/active-core.md`
и `source-owner-p0-hotfix-addendum-2026-10-25.md` §1:

* фильтр payload снимает из АКТИВНОГО owner-Core конкурирующие P2/P5
  (759/498 симв.) вместе с прежним P3: остаются P1/P4/P6 — 1246 симв.,
  ``4e67334b00ad``; хранимые байты и БД не меняются, повтор идемпотентен;
* серьёзный разбор (``response_act=research`` без deep_research) получает
  ТЕ ЖЕ дословные тексты анализа/Writer в ``<Response_Plan>``; deep-режим
  несёт их режимным блоком — ровно один раз в payload, без дубля;
* правило 7 канона L1: просьба оценить человека/мнение о нём — обычный
  содержательный разбор (normal/compact + answer), а detailed/report только
  при явной просьбе подробного/полного разбора; подробный анализ остаётся.

TEST-LIFECYCLE: CONTRACT owner=SPEECH-P0-CORE-SERIOUS/§1
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest

from services import chat_prompts as cp
from services import direct_l1 as l1
from services import mca_expression as ex
from services import mca_humor_craft as craft
from services import prompt_composer as pcomp
from services import prompt_style_blocks as psb

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVIDENCE = (ROOT / "plans" / "features" / "asap-speech-arch" / "evidence" /
            "p0-hotfix" / "active-core.md")


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _active_core_paragraphs() -> list[str]:
    """Активный Core verbatim из evidence-снимка (read-only источник)."""
    text = EVIDENCE.read_text(encoding="utf-8")
    start = text.index("```text\n") + len("```text\n")
    core = text[start:text.index("```", start)].rstrip("\n")
    assert len(core) == 3294 and _sha12(core) == "ead77b2ab509"
    return core.split("\n\n")


ACTIVE_CORE = "\n\n".join(_active_core_paragraphs())
P1, P2, P3, P4, P5, P6 = _active_core_paragraphs()


# ── 1. Core payload: активные P2/P5 не конкурируют ─────────────────────────

def test_active_core_paragraph_fingerprints_are_pinned():
    assert (len(P1), _sha12(P1)) == (246, "ee5f96d4462a")
    assert (len(P2), _sha12(P2)) == (759, "e551049be4d0")
    assert (len(P3), _sha12(P3)) == (785, "f3aeb50f00fd")
    assert (len(P4), _sha12(P4)) == (510, "e89981adcda4")
    assert (len(P5), _sha12(P5)) == (498, "3cad0802336d")
    assert (len(P6), _sha12(P6)) == (486, "053124e6e67a")


def test_active_core_payload_drops_p2_p5_p3_and_keeps_character():
    out = pcomp.simplify_core_for_prompt(ACTIVE_CORE)
    assert len(out) == 1246
    assert _sha12(out) == "4e67334b00ad"
    for kept in (P1, P4, P6):
        assert kept in out
    for dropped in (P2, P3, P5):
        assert dropped not in out
    # конкурирующие формулировки действительно ушли из payload
    for phrase in ("развивай её, а не бросай после первой фразы",
                   "нарастающего абсурда",
                   "Не обрывай удачную мысль"):
        assert phrase not in out, phrase


def test_core_filter_is_pure_and_idempotent():
    """Фильтр payload: хранимые байты Core не меняются, повтор — no-op."""
    before = ACTIVE_CORE
    once = pcomp.simplify_core_for_prompt(before)
    assert before == ACTIVE_CORE          # вход не мутирован
    assert pcomp.simplify_core_for_prompt(once) == once
    assert pcomp.simplify_core_for_prompt(once) == pcomp.simplify_core_for_prompt(
        pcomp.simplify_core_for_prompt(once))


def test_factory_v3_core_still_filtered_as_before():
    """Заводская редакция v3 фильтруется прежними точными абзацами."""
    out = pcomp.simplify_core_for_prompt(cp.PERSONALITY_CORE_FULL_TEXT)
    assert cp._DIRECT_L1_PLANNER_BASE_R3 not in out
    assert pcomp._CORE_HUMOR_TECHNIQUE_PARAGRAPH not in out
    assert pcomp._CORE_RHYTHM_PARAGRAPH not in out
    assert cp.CORE_REAL_EVENTS_PARAGRAPH not in out
    # характер/свобода речи v3 остаются
    assert cp.CORE_FREE_SPEECH_PARAGRAPH in out
    # идемпотентно
    assert pcomp.simplify_core_for_prompt(out) == out


# ── 2. Serious-разбор получает точную analysis-инструкцию один раз ─────────

def _research_plan(**kwargs) -> l1.L1Plan:
    base = dict(action="reply", response_act="research", extent="normal",
                structure="answer", delivery_hint="plain")
    base.update(kwargs)
    return l1.L1Plan(**base)


def test_analysis_texts_are_single_source():
    """Тексты §1 аддендума — одни и те же байты у deep-режима и plan-блока."""
    assert psb.ANALYSIS_DIRECTIVE_TEXT in psb.MODE_DEEP_RESEARCH_BLOCK
    assert psb.ANALYSIS_WRITER_TEXT in psb.MODE_DEEP_RESEARCH_BLOCK
    assert psb.MODE_DEEP_RESEARCH_BLOCK.count(
        psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert psb.MODE_DEEP_RESEARCH_BLOCK.count(psb.ANALYSIS_WRITER_TEXT) == 1


def test_serious_research_plan_block_has_exact_analysis_texts_once():
    plan = _research_plan()
    block = l1.build_l2_plan_block(
        plan, include_analysis=l1.analysis_directive_needed(plan))
    assert block.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert block.count(psb.ANALYSIS_WRITER_TEXT) == 1
    assert "Проанализируй доступные сведения по существу вопроса." in block
    assert ("Используй результаты анализа для ответа на вопрос, но не "
            "пересказывай внутреннюю структуру анализа.") in block
    assert block.startswith("<Response_Plan>") and \
        block.endswith("</Response_Plan>")
    # по умолчанию (флаг не запрошен) текстов нет — контракт прежний
    plain = l1.build_l2_plan_block(plan)
    assert psb.ANALYSIS_DIRECTIVE_TEXT not in plain


def test_deep_research_does_not_duplicate_analysis_instruction():
    plan = _research_plan(delivery_hint="rich", extent="detailed",
                          structure="report")
    assert l1.plan_response_mode(plan) == "deep_research"
    assert l1.analysis_directive_needed(plan) is False
    block = l1.build_l2_plan_block(
        plan, include_analysis=l1.analysis_directive_needed(plan))
    assert psb.ANALYSIS_DIRECTIVE_TEXT not in block
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", "deep_research", "rich",
        html_safe=True)
    payload = system + "\n\n" + block
    assert payload.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert payload.count(psb.ANALYSIS_WRITER_TEXT) == 1


def test_analysis_directive_matrix():
    assert l1.analysis_directive_needed(None) is False
    chat = l1.L1Plan(action="reply", response_act="chat")
    assert l1.analysis_directive_needed(chat) is False
    # режимы выключены → deep-блок не рендерится, инструкция нужна из плана
    rich = _research_plan(delivery_hint="rich")
    assert l1.analysis_directive_needed(rich, modes_on=False) is True
    assert l1.analysis_directive_needed(rich, modes_on=True) is False
    # ResponsePlan-путь (L2 Writer получает именно его)
    rp = chat.to_response_plan()
    assert l1.analysis_directive_needed(rp) is False
    assert l1.analysis_directive_needed(_research_plan().to_response_plan())


def test_plan_block_analysis_survives_noise_flags():
    """Флаг не ломает прежние ветки блока (low_conf/clarification/humor)."""
    plan = _research_plan(comic_strategy="literalism", tone="dry")
    block = l1.build_l2_plan_block(
        plan, low_confidence=True, include_analysis=True)
    assert psb.ANALYSIS_DIRECTIVE_TEXT in block
    assert "уверенность плана низкая" in block
    assert "приём юмора: literalism" in block
    assert "тон: dry" in block
    # уточнение по-прежнему идёт своей узкой фразой и не отменяет анализ
    clarify = _research_plan(needs_clarification=True,
                             clarification_target="предмет оценки")
    block = l1.build_l2_plan_block(
        clarify, clarification=True, include_analysis=True)
    assert "недостающий обязательный предмет: предмет оценки" in block
    assert psb.ANALYSIS_DIRECTIVE_TEXT in block


# ── 3. L1 routing: личный разбор не заказывает хронику/отчёт ───────────────

def test_l1_rule_routes_personal_analysis_to_normal_answer():
    canon = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    rules = cp._DIRECT_L1_PLANNER_RULES
    assert rules.count("7. Просьба оценить человека") == 1
    assert "extent=normal или compact" in rules
    assert "structure=answer" in rules
    assert "detailed и report выбирай только при явной" in rules
    assert "просьбе подробного или полного разбора" in rules
    # правило стоит до дисциплины JSON и не отменяет её
    assert rules.index("7. Просьба оценить человека") < \
        rules.index("8. В ответе - ровно одна JSON-строка")
    assert canon.count(rules) == 1
    # прежние правила 1-6 байт-в-байт (только нумерация хвоста изменилась)
    assert cp._DIRECT_L1_PLANNER_RULES_R3B.split(
        "6. confidence")[0] == rules.split("6. confidence")[0]
    # правило про подробный анализ не превратилось в запрет
    low = rules.casefold()
    for banned in ("запрещено подробно", "не отвечай подробно",
                   "максимум абзац", "архетип", "обязательн"):
        assert banned not in low, banned


def test_l1_frozen_r3b_rules_have_no_routing_rule():
    assert "7. Просьба оценить человека" not in cp._DIRECT_L1_PLANNER_RULES_R3B
    assert "7. В ответе - ровно одна JSON-строка" in \
        cp._DIRECT_L1_PLANNER_RULES_R3B


# ── 4. HUMOR_TEXT: один источник ───────────────────────────────────────────

def test_humor_text_has_single_source():
    assert craft.HUMOR_TEXT == ex.HUMOR_TEXT
    assert craft.HUMOR_TEXT is ex.HUMOR_TEXT
    assert craft.HUMOR_TEXT == (
        "Шути спонтанно, когда это уместно. Не вымучивай панчлайны, не строй "
        "истории ради шутки, не пытайся быть смешной в каждом сообщении. Не "
        "объясняй собственный юмор.")
