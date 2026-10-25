"""SPEECH-P0-CORE-SERIOUS (25.10.2026) — активный Core, serious-разбор, L1.

Доказывает по `plans/features/asap-speech-arch/evidence/p0-hotfix/active-core.md`
и `source-owner-p0-corrective-2026-10-25.md` §1.1/§3:

* payload-сборка НЕ обрезает АКТИВНЫЙ owner-Core: в модель уходят все абзацы
  P1/P2/P3/P4/P5/P6 — 3294 симв., ``ead77b2ab509``; хранимые байты и БД не
  меняются, повтор идемпотентен (прежний фильтр P2/P5/P3 снят как
  произвольное обрезание, P0-CORRECTIVE §3);
* серьёзный разбор (``response_act=research`` без deep_research) получает
  ТЕ ЖЕ дословные тексты анализа/Writer в ``<Response_Plan>`` плюс запрет
  мета-вступлений и навязанной отчётной структуры; deep-режим несёт их
  режимным блоком, а когда его вытесняет непустой extent-блок плана
  (SPEECH-P0-DEEP-PAYLOAD) — снова plan-блоком; ровно один раз в payload;
* правило 7 канона L1: разбор накопленного материала приоритетнее финального
  вопроса-оценки; quick opinion остаётся answer без эссе.

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
from services import response_extent as _extent

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


def test_active_core_payload_keeps_all_paragraphs_verbatim():
    """P0-CORRECTIVE §3: активный owner-Core уходит в payload целиком.

    Прежний allowlist вырезал P2/P5/P3 и отдавал модели 1246 вместо 3294 —
    это произвольное обрезание авторского текста на сборке. Фильтр снят;
    хранимые байты Core не меняются.
    """
    out = pcomp.simplify_core_for_prompt(ACTIVE_CORE)
    assert out == ACTIVE_CORE
    assert len(out) == 3294
    assert _sha12(out) == "ead77b2ab509"
    for kept in (P1, P2, P3, P4, P5, P6):
        assert kept in out


def test_core_filter_is_pure_and_idempotent():
    """Payload-сборка: хранимые байты Core не меняются, повтор — no-op."""
    before = ACTIVE_CORE
    once = pcomp.simplify_core_for_prompt(before)
    assert before == ACTIVE_CORE          # вход не мутирован
    assert once == before
    assert pcomp.simplify_core_for_prompt(once) == once


def test_factory_core_is_not_truncated():
    """Заводская редакция v3 тоже уходит целиком (без вырезания абзацев)."""
    out = pcomp.simplify_core_for_prompt(cp.PERSONALITY_CORE_FULL_TEXT)
    assert out == cp.PERSONALITY_CORE_FULL_TEXT
    assert pcomp._CORE_HUMOR_TECHNIQUE_PARAGRAPH in out
    assert pcomp._CORE_RHYTHM_PARAGRAPH in out
    assert cp.CORE_REAL_EVENTS_PARAGRAPH in out
    assert cp.CORE_FREE_SPEECH_PARAGRAPH in out


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


def test_writer_no_meta_and_no_imposed_structure():
    """P0-CORRECTIVE §3:Writer не анонсирует разбор и не навязывает структуру.

    Директива не задаёт ни длины, ни формата ответа — только запрещает
    мета-вступление и отчётную нумерацию без просьбы пользователя.
    """
    text = psb.NO_META_STRUCTURE_TEXT
    assert "Не анонсируй разбор" in text
    assert "Не нумеруй" in text
    assert "если пользователь не просил" in text
    # никаких приказов объёма/готовой схемы
    for forbidden in ("символ", "абзац", "ПОЛНОСТЬЮ", "Во-первых",
                      "markdown", "Markdown"):
        assert forbidden not in text, forbidden
    plan = _research_plan()
    block = l1.build_l2_plan_block(
        plan, include_analysis=l1.analysis_directive_needed(plan))
    assert block.count(text) == 1
    assert text in psb.MODE_DEEP_RESEARCH_BLOCK
    # без include_analysis директива в план не попадает
    assert text not in l1.build_l2_plan_block(plan)


# TEST-LIFECYCLE: REGRESSION owner=SPEECH-P0-DEEP-PAYLOAD (rev. 25.10.2026)
def test_deep_research_extent_block_carries_analysis_texts_once():
    """SPEECH-P0-DEEP-PAYLOAD (ревью 25.10.2026): deep_research с непустым
    extent-блоком ЗАМЕНЯЕТ ``MODE_DEEP_RESEARCH_BLOCK`` — значит точные
    тексты §1 обязаны приехать plan-блоком, ровно один раз в payload."""
    plan = _research_plan(delivery_hint="rich", extent="detailed",
                          structure="report")
    assert l1.plan_response_mode(plan) == "deep_research"
    rp = plan.to_response_plan()
    extent_block = _extent.render_extent_block(rp)
    assert extent_block                            # реальный payload ветка
    assert l1.analysis_directive_needed(plan) is True
    block = l1.build_l2_plan_block(
        plan, include_analysis=l1.analysis_directive_needed(plan))
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", "deep_research", "rich",
        html_safe=True,
        extent_block=extent_block)
    # режимный блок вытеснен планом — второй копии инструкции нет
    assert psb.MODE_DEEP_RESEARCH_BLOCK not in system
    payload = system + "\n\n" + block
    assert payload.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert payload.count(psb.ANALYSIS_WRITER_TEXT) == 1
    assert extent_block in payload


def test_deep_research_without_extent_keeps_mode_block_only():
    """``extent=auto`` → extent-блока нет, режимный блок рендерится и
    остаётся единственным носителем точных текстов (0 в плане)."""
    plan = _research_plan(delivery_hint="rich", extent="auto",
                          structure="report")
    assert l1.plan_response_mode(plan) == "deep_research"
    assert _extent.render_extent_block(plan.to_response_plan()) == ""
    assert l1.analysis_directive_needed(plan) is False
    block = l1.build_l2_plan_block(
        plan, include_analysis=l1.analysis_directive_needed(plan))
    system = psb.compose_verbalizer_system(
        "КАНАЛ: технический контракт.", "deep_research", "rich",
        html_safe=True, extent_block="")
    payload = system + "\n\n" + block
    assert psb.MODE_DEEP_RESEARCH_BLOCK in payload
    assert payload.count(psb.ANALYSIS_DIRECTIVE_TEXT) == 1
    assert payload.count(psb.ANALYSIS_WRITER_TEXT) == 1


def test_analysis_directive_matrix():
    assert l1.analysis_directive_needed(None) is False
    chat = l1.L1Plan(action="reply", response_act="chat")
    assert l1.analysis_directive_needed(chat) is False
    # режимы выключены → deep-блок не рендерится, инструкция нужна из плана
    rich = _research_plan(delivery_hint="rich")
    assert l1.analysis_directive_needed(rich, modes_on=False) is True
    # deep + непустой extent (normal) → режимный блок вытеснен → нужна
    assert l1.analysis_directive_needed(rich, modes_on=True) is True
    # deep + пустой extent → режимный блок несёт тексты → не нужна
    auto_rich = _research_plan(delivery_hint="rich", extent="auto")
    assert l1.analysis_directive_needed(auto_rich, modes_on=True) is False
    # ResponsePlan-путь (L2 Writer получает именно его)
    rp = chat.to_response_plan()
    assert l1.analysis_directive_needed(rp) is False
    assert l1.analysis_directive_needed(_research_plan().to_response_plan())
    assert l1.analysis_directive_needed(
        _research_plan(delivery_hint="rich").to_response_plan()) is True
    assert l1.analysis_directive_needed(
        _research_plan(delivery_hint="rich",
                       extent="auto").to_response_plan()) is False


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

def test_l1_rule_routes_material_to_research_and_opinion_to_answer():
    """P0-CORRECTIVE §1.1: правило 7 больше не оценивает ОБЪЕКТ просьбы —
    оно разделяет материал («уже сказанное» → research) и quick opinion
    (→ answer без эссе). Детальные пины — test_speech_p0_corrective_l1_route."""
    rules = cp._DIRECT_L1_PLANNER_RULES
    assert "Просьба оценить человека" not in rules
    assert "response_act=research" in rules
    assert "structure=answer" in rules
    assert "9. В ответе - ровно одна JSON-строка" in rules
    assert cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT.count(rules) == 1
    # прежние правила 1-6 байт-в-байт (изменился только хвост)
    assert cp._DIRECT_L1_PLANNER_RULES_R3B.split(
        "6. confidence")[0] == rules.split("6. confidence")[0]


def test_l1_frozen_r3b_rules_have_no_routing_rule():
    assert "7. Просьба оценить человека" not in cp._DIRECT_L1_PLANNER_RULES_R3B
    assert "7. В ответе - ровно одна JSON-строка" in \
        cp._DIRECT_L1_PLANNER_RULES_R3B
    assert "7. Просьба оценить человека" in \
        cp._DIRECT_L1_PLANNER_RULES_P0CS


# ── 4. HUMOR_TEXT: один источник ───────────────────────────────────────────

def test_humor_text_has_single_source():
    assert craft.HUMOR_TEXT == ex.HUMOR_TEXT
    assert craft.HUMOR_TEXT is ex.HUMOR_TEXT
    assert craft.HUMOR_TEXT == (
        "Шути спонтанно, когда это уместно. Не вымучивай панчлайны, не строй "
        "истории ради шутки, не пытайся быть смешной в каждом сообщении. Не "
        "объясняй собственный юмор.")
