# -*- coding: utf-8 -*-
"""P0C-INT R2: L1-канон (правило 7) и детерминированная нормализация акта.

TEST-LIFECYCLE: CONTRACT
owner=P0-SPEECH/hotfix
why=`probes_final4.md` §3: natural A/B дали `answer` и `hostile_rebuff` (0/2
    research) при том же каноне. Два дефекта: (1) синонимы `response_act`
    (`analysis`/`review`/`разбор`) молча не равны `research` и выключают
    анализ; (2) правило 7 ставило триггер разбора второстепенным и не
    исключало враждебные акты для просьбы разобрать материал.
replace_when=если схема L1 перестанет быть открытым словарём.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import chat_prompts as cp  # noqa: E402
from services import direct_l1 as l1  # noqa: E402
from services import prompt_migrations as pm  # noqa: E402


# ── нормализация: известные формы → канон, незнакомое не теряется ───────────

@pytest.mark.parametrize("raw,expected", [
    ("analysis", "research"),
    ("ANALYSIS", "research"),
    ("  review  ", "research"),
    ("analyze", "research"),
    ("разбор", "research"),
    ("анализ", "research"),
    ("investigation", "research"),
    ("deep-analysis", "research"),
    ("summary", "summarization"),
    ("summarize", "summarization"),
    ("history", "historical_recall"),
    ("compare", "comparison"),
    ("explain", "explanation"),
    ("emotional", "emotional_reply"),
    ("tease", "tease"),
    ("answer", "answer"),
    ("research", "research"),
])
def test_known_forms_map_to_canon(raw, expected):
    assert l1.canonical_response_act(raw) == expected


def test_unknown_and_empty_keep_previous_behaviour():
    assert l1.canonical_response_act("my_custom_act") == "my_custom_act"
    assert l1.canonical_response_act("") == "other"
    assert l1.canonical_response_act(None) == "other"


def test_normalized_plan_enables_the_analysis_path():
    """Синоним больше не выключает анализ: план → research → предикат True."""
    plan = l1.normalize_l1_plan({
        "action": "reply", "response_act": "analysis", "extent": "compact",
        "structure": "answer", "confidence": 0.9})
    assert plan.response_act == "research"
    assert l1.analysis_directive_needed(plan) is True
    assert l1.plan_response_mode(plan) == "serious"
    block = l1.build_l2_plan_block(plan, include_analysis=True, modes_on=True)
    assert "как разбирать:" in block and "как начать ответ:" in block


def test_plain_answer_plan_stays_answer():
    """Оценка без разбора материала — answer, без analysis-блока."""
    plan = l1.normalize_l1_plan({
        "action": "reply", "response_act": "answer", "extent": "compact",
        "structure": "answer", "confidence": 0.9})
    assert l1.analysis_directive_needed(plan) is False
    block = l1.build_l2_plan_block(plan, include_analysis=False,
                                   modes_on=True)
    assert "как разбирать:" not in block


def test_open_dictionary_still_accepts_unknown_act_in_plan():
    """Открытый словарь §2.3 не превращается в закрытое множество."""
    plan = l1.normalize_l1_plan({
        "action": "reply", "response_act": "brand_new_act", "confidence": 0.5})
    assert plan.response_act == "brand_new_act"


# ── канон: правило 7 семантически закрывает观测ённые сбои ────────────────────

def _rule(text: str, number: int) -> str:
    start = text.index("%d. " % number)
    nxt = text.find("%d. " % (number + 1), start)
    return text[start:nxt if nxt != -1 else len(text)]


def test_rule7_material_request_is_research_regardless_of_trailing_question():
    rule = _rule(cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT, 7)
    assert "response_act=research" in rule
    assert "разбор материала" in rule
    # Вопрос-оценка не отменяет разбор: оценка — вывод разбора.
    assert "вопрос-оценка" in rule
    assert "оценка - вывод разбора" in rule
    # Оценка БЕЗ разбора материала остаётся answer.
    assert "answer по существу" in rule


def test_rule7_forbids_hostile_acts_for_material_review():
    """probes_final4: просьба разобрать переписку ушла в hostile_rebuff."""
    rule = _rule(cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT, 7)
    assert "не является выпадом в адрес бота" in rule
    assert "hostile_rebuff" in rule


def test_rule7_precedes_rule8_and_keeps_depth_clause():
    text = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert text.index("7. Сначала определи") < text.index("8. Глубина разбора")
    assert "Глубина разбора не задаёт длину ответа" in text


def test_canon_has_no_hardcoded_user_phrases():
    """Никаких списков фраз запроса: решение остаётся семантическим."""
    low = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT.lower()
    for phrase in ("проанализируй мои сообщения", "мои сообщения", "в чате",
                   "злобный", "злобоный"):
        assert phrase not in low, phrase


def test_prev_step_is_the_live_canon_of_editor_2():
    """PREV-ступень — ровно те байты, что крутились в живом прогоне."""
    import hashlib
    prev = cp.PREV_DIRECT_L1_PLANNER_P0CINT
    assert len(prev) == 9288
    assert hashlib.sha256(prev.encode()).hexdigest()[:12] == "23aae0c9499d"
    assert prev != cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT


def test_migration_maps_previous_step_to_current():
    steps = dict(pm.PROMPT_MIGRATIONS["prompts.direct_l1_planner_system_prompt"])
    assert steps[cp.PREV_DIRECT_L1_PLANNER_P0CINT] \
        == cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert steps[cp.PREV_DIRECT_L1_PLANNER_P0CS2] \
        == cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
