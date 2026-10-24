# -*- coding: utf-8 -*-
"""QUOTA-REMOVAL (ADDENDUM #3 §2.7): искусственных квот инструкций нет.

Контракт лейна: локальный бюджет речевых слоёв удалён целиком — длинные
управляющие инструкции (Personality Core full, Style_Policy_Hint, авторские
примеры Expression, humor) доходят до payload при достаточном реальном окне;
никакая старая переменная/значение не возвращает квоту.

Что СОХРАНЕНО и здесь не проверяется на удаление: реальное окно
(`model_capacity`, `CHAT_CONTEXT_BUDGET_TOKENS`), `llm_client.max_tokens`,
retry/fallback/таймауты (их зелёность покрыта профильными наборами).

TEST-LIFECYCLE: REGRESSION owner=P0/QUOTA-REMOVAL (ADDENDUM #3 §2.7 A1–A6)
"""
from __future__ import annotations

import pytest

from services import mca_gates
from services import prompt_composer as pc
from services import prompt_registry as pr


LONG_CORE = "ЯДРО_МАРКЕР: " + ("личность и характер. " * 400)
LONG_HINT = "<Style_Policy_Hint>\n" + ("- без канцелярита\n" * 120) + \
    "</Style_Policy_Hint>"
LONG_EXPR = "<Expression>\n" + ("температура: средняя\n" * 120) + "</Expression>"
LONG_EXAMPLE = "<Expression_Examples mode=\"frequent\">\n" + \
    ("- быт: пример реплики -> ответ\n" * 120) + "</Expression_Examples>"
LONG_HUMOR = "<Humor_Craft>\n" + ("приём: буквализм\n" * 100) + "</Humor_Craft>"


def _plan() -> pc.PromptPlan:
    return pc.PromptPlan(
        profile=pc.PROFILE_SPEECH_PLAIN, writer="l2_writer", chat_id=42,
        channel="plain", html_safe=True, run_id="run-quota",
        base_prompt="КАНАЛ: факты.", base_source="global",
        core=pc.CoreRef(text=LONG_CORE, revision="r9", source="global",
                        detail_level="full", detail_reason="owner_setting"),
        expression=pc.ExpressionSettings(text=LONG_EXPR, revision="e9",
                                         mode="frequent"),
        humor=pc.HumorStrategy(text=LONG_HUMOR, technique="literalism",
                               revision="h9"),
        expression_examples=(pc.SampleRef(
            block_id="expression_examples", text=LONG_EXAMPLE,
            revision="x9", source="global",
            technique="expression_register"),),
        style_policy=pc.StylePolicyRef(hint=LONG_HINT, revision="s9",
                                       source="global", rule_count=3,
                                       soft_count=3),
        gates=pc.GateState(unified_composer_enabled=True,
                           humor_library_enabled=True,
                           humor_craft_enabled=True))


def test_quota_api_is_gone_not_disabled():
    """A1/A6: функции и причины удалены, а не «выключены нулём»."""
    assert not hasattr(mca_gates, "composer_additive_budget_tokens")
    assert not hasattr(pc, "_BUDGET_LAYERS")
    assert "budget_excluded" not in pc.SKIP_REASONS
    assert "context_budget" not in pr.CORE_DETAIL_REASONS
    # прежние служебные конфликты «бюджет против характера» не производятся
    manifest = pc.compose_prompt(_plan())
    ids = {c.conflict_id for c in manifest.conflicts}
    assert "core_protected_from_budget" not in ids
    assert "expression_protected_from_budget" not in ids


@pytest.mark.parametrize("raw", ("1", "0", "-1", "40"))
def test_long_instructions_reach_payload_whatever_env_says(monkeypatch, raw):
    """A2–A5: ни одно значение старой переменной не обрезает инструкции."""
    monkeypatch.setenv("COMPOSER_LAYER_BUDGET_TOKENS", raw)
    manifest = pc.compose_prompt(_plan())
    system = manifest.system
    assert LONG_CORE in system
    assert LONG_HINT in system
    assert LONG_EXPR in system
    assert LONG_EXAMPLE in system
    assert LONG_HUMOR in system
    traces = {t.block_id: t for t in manifest.layers}
    for block_id in ("core", "expression", "humor_craft",
                     "expression_examples", "style_policy_hint"):
        assert traces[block_id].rendered is True, block_id
        assert traces[block_id].skip_reason == "", block_id
    assert all(t.skip_reason != "budget_excluded" for t in manifest.layers)
    # порядок слоёв не изменился удалением квоты
    order = list(dict.fromkeys(t.layer for t in manifest.layers))
    assert order == list(pc.LAYER_ORDER)


def test_owner_full_core_detail_is_not_downgraded():
    """A4: `detail_level=full` владельца — единственный источник выбора."""
    full = "ПОЛНАЯ РЕДАКЦИЯ " + ("слово " * 900)
    selection = pr.core_selection(
        {"revision": 4, "full_text": full, "compact_text": "КОМПАКТ",
         "detail_level": "full"}, source="global")
    assert selection["level"] == "full"
    assert selection["reason"] == "owner_setting"
    assert selection["text"] == full
    # Inspector-вид не публикует удалённый бюджет как настройку
    view = pr.core_selection_view(None, source="default")
    assert "budget_tokens" not in view


def test_render_has_no_local_expression_example_quota():
    """A5: рендер примеров не режет по числу строк, символам и токенам."""
    from services import mca_expression as ex

    rows = [{"context_note": "быт", "input_text": "и" * 300,
             "reply_text": "о" * 300} for _ in range(12)]
    block = ex.render_expression_examples_block("frequent", rows)
    assert block.total_items == 12 and block.included_items == 12
    assert block.dropped == 0 and block.limited_by == ""
    assert block.count(" -> ") == 12
    assert block.endswith("</Expression_Examples>")


def test_owner_expression_note_is_not_truncated():
    """A7 (REV-QUOTA-QUOTES F1): «Пожелание владельца» доходит целиком.

    ADDENDUM #3 §2.2/§2.10: пожелание — управляющая инструкция, потолка
    2000 символов нет; хвост виден и в `<Expression_Settings>`.
    """
    from services import mca_expression as ex

    note = ("СТАРТ_ПОЖЕЛАНИЯ: пиши живо, без канцелярита и воды. " * 60
            + "ХВОСТ_МАРКЕР")
    assert len(note) > 2000
    doc = {"profanity": "occasional", "note": note}
    assert ex.normalize_expression(doc)["note"] == note
    assert ex.resolve_effective(doc, None)["note"] == note
    text = ex.build_expression_settings(doc, None).text
    assert text.startswith("<Expression_Settings>")
    assert note in text, "пожелание обрезано до вставки в слой"
    assert "ХВОСТ_МАРКЕР" in text
