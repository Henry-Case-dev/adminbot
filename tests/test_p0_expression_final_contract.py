# -*- coding: utf-8 -*-
"""P0-E v2 — финальный контракт речи в САМОМ КОНЦЕ system.

Замер 24.10.2026 (полная боевая сборка L2-writer): слой
``<Expression_Settings>`` заканчивается на 91.5%, но последним модель читает
другой блок. Поэтому тот же режим повторяется в хвосте с пометкой приоритета
из единственного источника ``PROFANITY_INSTRUCTIONS``.

TEST-LIFECYCLE: CONTRACT owner=P0-E/EX-02 (финальная позиция режима мата).
"""
from __future__ import annotations

import pytest

from services import mca_expression as ex
from services import prompt_composer as pc

HEADER = ex.EXPRESSION_FINAL_HEADER
ALL_MODES = ("off", "occasional", "frequent")


def _plan(expression: pc.ExpressionSettings | None, *,
          profile: str = "speech_plain", **overrides) -> pc.PromptPlan:
    plan = pc.PromptPlan(
        profile=profile, writer="l2_writer", chat_id=777,
        channel="plain", html_safe=True,
        base_prompt="КАНАЛ: факты, имена, доставка.",
        base_source="global", expression=expression,
        gates=pc.GateState(unified_composer_enabled=True),
        user_parts=("ВОПРОС_МАРКЕР: как оно?",))
    return pc.PromptPlan(**{**plan.__dict__, **overrides}) if overrides \
        else plan


def _expression(mode: str) -> pc.ExpressionSettings:
    return ex.build_expression_settings({"profanity": mode}, None)


# ═══ 1. Финальный блок: ровно один и последний ════════════════════════════

@pytest.mark.parametrize("mode", ALL_MODES)
def test_final_contract_is_the_last_block_and_rendered_once(mode):
    manifest = pc.compose_prompt(_plan(_expression(mode)))
    system = manifest.system
    final_text = ex.render_expression_final_contract(mode)

    assert final_text
    assert system.rstrip().endswith(final_text.rstrip())
    assert system.count(HEADER) == 1
    # Слой остаётся на своём месте ровно один раз (второго слоя нет).
    assert system.count("<Expression_Settings>") == 1
    assert system.index("<Expression_Settings>") < system.index(HEADER)


@pytest.mark.parametrize("mode", ALL_MODES)
def test_final_contract_text_is_the_same_owner_instruction(mode):
    """Тот же текст режима, не новый источник и не новая формулировка."""
    final_text = ex.render_expression_final_contract(mode)
    assert final_text == HEADER + "\n" + ex.PROFANITY_INSTRUCTIONS[mode]
    # Ровно одна копия инструкции внутри финального блока.
    assert final_text.count(ex.PROFANITY_INSTRUCTIONS[mode]) == 1
    # Другие режимы в хвост не протекают.
    for other in ALL_MODES:
        if other != mode:
            assert ex.PROFANITY_INSTRUCTIONS[other] not in final_text


def test_final_contract_states_priority_over_other_instructions():
    final_text = ex.render_expression_final_contract("frequent")
    assert "действует поверх остальных инструкций" in final_text


# ═══ 2. Нет квот/постпроцессора/второго регулятора ═════════════════════════

def test_final_contract_has_no_quota_or_forced_insertion():
    for mode in ALL_MODES:
        text = ex.render_expression_final_contract(mode).casefold()
        assert "%" not in text
        assert "каждом сообщении" not in text
        for banned in ("квот", "вероятност", "обязательно добавь"):
            assert banned not in text


def test_final_contract_absent_without_expression_or_mode():
    no_expression = pc.compose_prompt(_plan(None))
    disabled = pc.compose_prompt(_plan(pc.ExpressionSettings(
        text="", enabled=False, skip_reason="expression_disabled",
        mode="frequent")))
    inherit = pc.compose_prompt(_plan(pc.ExpressionSettings(
        text="<Expression_Settings>\n- Мат: …\n</Expression_Settings>",
        revision="rtest", mode="inherit")))
    machine = pc.compose_prompt(_plan(_expression("frequent"),
                                      profile="machine_json"))
    for manifest in (no_expression, disabled, inherit, machine):
        assert HEADER not in manifest.system


# ═══ 3. OFF / OCCASIONAL: смысл не меняется ═══════════════════════════════

def test_off_final_contract_does_not_add_profanity():
    manifest = pc.compose_prompt(_plan(_expression("off")))
    final_text = ex.render_expression_final_contract("off")
    assert manifest.system.rstrip().endswith(final_text.rstrip())
    assert ex.count_profanity(final_text) == 0
    assert ex.PROFANITY_INSTRUCTIONS["off"] == \
        "Не используй мат в собственной речи."


def test_occasional_final_contract_keeps_occasional_semantics():
    manifest = pc.compose_prompt(_plan(_expression("occasional")))
    final_text = ex.render_expression_final_contract("occasional")
    assert manifest.system.rstrip().endswith(final_text.rstrip())
    assert final_text.count(ex.PROFANITY_INSTRUCTIONS["occasional"]) == 1
    low = ex.PROFANITY_INSTRUCTIONS["occasional"].casefold()
    assert "не должен доминировать" in low


@pytest.mark.parametrize("mode", ALL_MODES)
def test_mode_semantics_sources_are_untouched(mode):
    """v2 не переписывает тексты режимов: они ровно те же, что в слое."""
    rendered = ex.render_expression_text(
        ex.resolve_effective({"profanity": mode}, None))
    assert f"- Мат: {ex.PROFANITY_INSTRUCTIONS[mode]}" in rendered


# ═══ 4. Трасса: хвост виден, лишнего слоя нет ══════════════════════════════

def test_expression_trace_documents_the_tail_contract():
    manifest = pc.compose_prompt(_plan(_expression("frequent")))
    traces = [t for t in manifest.layers if t.layer == "expression"]
    assert len(traces) == 1
    trace = traces[0]
    assert trace.block_id == "expression"
    assert trace.rendered is True
    assert "final_contract=tail" in trace.detail
    assert ex.PROFANITY_INSTRUCTIONS["frequent"] in trace.text
    assert trace.revision == _expression("frequent").revision
    # Порядок слоёв не изменился: второго `expression` в трассе нет.
    assert [t.layer for t in manifest.layers].count("expression") == 1
    assert list(dict.fromkeys(t.layer for t in manifest.layers)) == \
        list(pc.LAYER_ORDER)
