# -*- coding: utf-8 -*-
"""ASAP 2 Direct Chat — структурные контракты корректи P0 уточнений.

Первoисточник: plans/features/asap2-direct-chat/source-2026-10-22.md
(§3.2 строгий boolean, §3.3 снятие speech-императива, §3.4 контекст
продолжения, §4.1-4.3 каноны, §6.4 таблица №27-36). Доказывается офлайн
(0 Telegram, 0 LLM); семантика проверяется отдельными живыми пробами L1/L2
(evidence/impl), не фейковым L1.

TEST-LIFECYCLE: CONTRACT owner=ASAP2-CLAR (§3.2/§3.3/§4.1-4.3/§6.4)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import chat_prompts as cp  # noqa: E402
from services import claim_envelope as ce  # noqa: E402
from services import direct_l1 as _l1  # noqa: E402
from services import prompt_migrations as pm  # noqa: E402
from services import prompt_registry as pr  # noqa: E402
from services import response_extent as _extent  # noqa: E402

CANON_L1 = cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT
CANON_L2 = cp.DIRECT_VERBALIZER_SYSTEM_PROMPT

#: Прод-байты 2.58.111 (W1-каноны, слепки лестницы ASAP 2).
PROD_W1_L1_SHA16 = "f8ab20121c0265e0"
PROD_W1_L2_SHA12 = "be03964322aa"


# ── №27-29: строгий JSON boolean (§3.2) ─────────────────────────────────────

@pytest.mark.parametrize("raw", [False, None, "false", "true", [], {},
                                 0, 1])
def test_27_29_needs_clarification_strict_boolean(raw):
    """№27 false → False; №28 "false" → НЕ True; №29 null → НЕ True.
    Любая некорректная структура не трактуется как запрос уточнения
    (безопасный fallback прежний, нового LLM-вызова нет)."""
    plan = _l1.normalize_l1_plan({"action": "reply",
                                  "needs_clarification": raw})
    assert plan is not None
    assert plan.needs_clarification is False, raw


def test_27_real_true_is_only_truthy_path():
    """Реальный JSON true → True (флаг остаётся решением L1, §3.2)."""
    plan = _l1.normalize_l1_plan({"action": "reply",
                                  "needs_clarification": True,
                                  "clarification_target": "media_target"})
    assert plan.needs_clarification is True
    assert plan.clarification_target == "media_target"


# ── №30: true + пустая цель → generic-опроса нет (§3.2/§4.3) ────────────────

def test_30_empty_target_never_generic_clarify():
    for target in (None, "", "   "):
        plan = _l1.normalize_l1_plan({"action": "reply",
                                      "needs_clarification": True,
                                      "clarification_target": target})
        block = _l1.build_l2_plan_block(plan, clarification=True)
        assert plan.needs_clarification is True
        # ни директивы уточнения, ни вопроса-меню: Writer пишет по плану
        assert "уточняющ" not in block.lower(), target
        assert "недостающий обязательный предмет" not in block
        assert "Ничего кроме вопроса" not in block


def test_30_target_present_narrow_directive_only():
    """§4.3: при непустой цели — узкая фраза владельца + предмет; старого
    императива «Ничего кроме вопроса не пиши» нет."""
    plan = _l1.normalize_l1_plan({"action": "reply",
                                  "needs_clarification": True,
                                  "clarification_target": "media_target"})
    block = _l1.build_l2_plan_block(plan, clarification=True)
    assert "недостающий обязательный предмет: media_target" in block
    assert ("Для выполнения этого запроса действительно не хватает "
            "обязательного предмета" in block)
    assert "После ответа следует продолжить исходную задачу" in block
    assert "Ничего кроме вопроса" not in block
    # обычная ветка (clarification=False) директивы не несёт вовсе
    assert "недостающий обязательный предмет" not in \
        _l1.build_l2_plan_block(plan, clarification=False)


# ── №31: response_act=clarification ≠ уточнение (§3.2) ──────────────────────

def test_31_response_act_does_not_force_clarification():
    plan = _l1.normalize_l1_plan({"action": "reply",
                                  "response_act": "clarification",
                                  "needs_clarification": False})
    assert plan.needs_clarification is False
    assert plan.response_act == "clarification"
    # единый контракт действий: ни один второй флаг не включает уточнение
    assert "уточняющ" not in _l1.build_l2_plan_block(
        plan, clarification=bool(plan.needs_clarification)).lower()
    # tool-гейт читает только needs_clarification (строковые «true» уже
    # отсеяны нормализацией)
    assert getattr(plan, "needs_clarification") is False


# ── №32: tool-путь не блокируется Speech-сигналом (§3.3/§4.4) ───────────────

def test_32_speech_hints_never_suggest_clarify(monkeypatch):
    from services import direct_chat_service as dcs
    monkeypatch.setattr(dcs.mca_gates, "character_speech_enabled",
                        lambda: True)

    class _Msg:
        text = "почему?"
        reply_to_message = None

        class chat:
            type = "supergroup"

    class _Stub:
        bot_id = 999
        _build_speech_understanding = \
            dcs.DirectChatService._build_speech_understanding
        _l1_speech_hints = dcs.DirectChatService._l1_speech_hints

    hints = _Stub._l1_speech_hints(_Stub(), _Msg(), "почему?", None)
    assert "clarify" not in hints
    assert "задай" not in hints
    # обычный вопрос с доступными тулами: план без clarification →
    # tool-фаза не блокируется речью (блокирует только needs_clarification)
    plan = _l1.normalize_l1_plan({"action": "reply",
                                  "tool_policy": "auto",
                                  "needs_clarification": False})
    assert plan.needs_clarification is False


# ── №33: Composer/L1 ON-OFF и fallback — второго приказа нет (§3.3) ─────────

def test_33_no_second_clarify_directive_any_path():
    # детерминированный fallback не включает уточнение
    fb = _l1.fallback_plan("вопрос?")
    assert fb.needs_clarification is False
    assert fb.clarification_target is None
    # Speech-блок не содержит модельного приказа «задай … вопрос»
    u = ce.build_speech_understanding("почему?", is_group=True)
    assert "задай" not in ce.render_speech_block(u)
    # каноны не несут снятых императивов
    assert "Ничего кроме вопроса" not in CANON_L1
    assert "Ничего кроме вопроса" not in CANON_L2
    # легаси fixed-уточнение медиа (узкая обязательная цель) не сломано
    media = _extent.classify_request("скачай это видео")
    if getattr(media, "task_kind", "") in ("media", "transcription",
                                           "video", "audio"):
        assert _extent.clarification_question(media, has_target=False)


# ── №34: Factory/active/override/hot — канон доезжает, кастом цел (§5) ──────

def test_34_factory_and_ladder_and_custom_preserved():
    # фабрики обоих ключей = новые каноны; метки бампнуты
    assert pr.factory_text("direct.base.l1_planner") == CANON_L1
    assert pr.factory_text("direct.base.l2_writer") == CANON_L2
    assert "l1-planner-clar" in pr.factory_revision("direct.base.l1_planner")
    assert "l2-writer-clar" in pr.factory_revision("direct.base.l2_writer")
    # лестница: прод-байты 2.58.111 ведутся на новые каноны при рестарте
    steps_l1 = {src: dst for src, dst in
                pm.PROMPT_MIGRATIONS["prompts.direct_l1_planner_system_prompt"]}
    steps_l2 = {src: dst for src, dst in
                pm.PROMPT_MIGRATIONS[
                    "prompts.direct_chat_verbalizer_system_prompt"]}
    assert steps_l1[cp.PREV_DIRECT_L1_PLANNER_W1] == CANON_L1
    assert steps_l2[cp.PREV_CHAT_VERBALIZER_W1_31] == CANON_L2
    import hashlib
    assert hashlib.sha256(
        cp.PREV_DIRECT_L1_PLANNER_W1.encode("utf-8")).hexdigest()[:16] == \
        PROD_W1_L1_SHA16
    assert hashlib.sha256(
        cp.PREV_CHAT_VERBALIZER_W1_31.encode("utf-8")).hexdigest()[:12] == \
        PROD_W1_L2_SHA12
    # кастом владельца (не точное совпадение) не является ступенью-источником
    custom_l1 = cp.PREV_DIRECT_L1_PLANNER_W1 + " правка владельца"
    assert custom_l1 not in steps_l1
    # прежние W1-каноны остаются известными канонами (не «кастом»)
    assert pr.is_known_canon(cp.PREV_DIRECT_L1_PLANNER_W1)
    assert pr.is_known_canon(CANON_L1)
    # откат ведёт на непосредственный прежний канон 2.58.111
    assert pm.ROLLBACK_MIGRATIONS["prompts.direct_l1_planner_system_prompt"] \
        == (CANON_L1, cp.PREV_DIRECT_L1_PLANNER_W1)
    assert pm.ROLLBACK_MIGRATIONS[
        "prompts.direct_chat_verbalizer_system_prompt"] == \
        (CANON_L2, cp.PREV_CHAT_VERBALIZER_W1_31)


# ── №35: инициатива — контракты доставки не изменились (L1D) ────────────────

def test_35_initiative_delivery_contracts_unchanged():
    assert _l1.L1_DELIVERY_MODES == ("chat", "reply")
    plan = _l1.normalize_l1_plan({"action": "reply", "delivery": "reply",
                                  "target_message_id": 42})
    assert _l1.reply_binding_requested(plan) is True
    block = _l1.build_l2_plan_block(plan, include_delivery=True)
    assert "[msg:42]" in block and "прямым" in block
    assert "никакая форма не имеет приоритета" in _l1.INITIATIVE_LINE
    # секция участия W1 в каноне не тронута (байт-в-байт)
    assert cp._DIRECT_L1_PARTICIPATION_W1 in CANON_L1


# ── №36: Character/Expression/Style и обычные вопросы не тронуты ────────────

def test_36_character_expression_style_untouched():
    import hashlib
    from services import mca_expression as ex
    # Core v3 (W1 §3.2/§3.3) — байты прежние
    assert hashlib.sha256(
        cp.PERSONALITY_CORE_FULL_TEXT.encode("utf-8")).hexdigest()[:12] == \
        "2ab417d11404"
    assert hashlib.sha256(
        cp.PERSONALITY_CORE_COMPACT_TEXT.encode("utf-8")).hexdigest()[:12] == \
        "9e6a4ec8b1ea"
    # Expression §3.4 — байты прежние
    assert ex.EXPRESSION_HEADER.startswith("<Expression_Settings>")
    assert "ПРАВИЛА МАНЕРЫ РЕЧИ" in ex.EXPRESSION_HEADER.splitlines()[1]
    # речевые сигналы (кроме снятого ask) работают: цитата/отрицание/юмор
    u = ce.build_speech_understanding("> он уехал\nя не был дома",
                                      is_group=True)
    block = ce.render_speech_block(u)
    assert "не приписывай" in block and "отрицание" in block
    # L2-канон не трогает характер/форматы: личность и типографика в нём
    # отсутствуют (слои отдельные)
    for marker in ("токсичн", "бот-абьюзер", "ТИПОГРАФИКА"):
        assert marker not in CANON_L2


# ── §3.4/§8.1: три элемента продолжения доходят до L1 ───────────────────────

def test_34b_continuation_context_carries_three_elements():
    """Исходная просьба (окно) + предыдущий вопрос бота (bot_replies) +
    ответ пользователя (СООБЩЕНИЕ) присутствуют в L1-контексте."""
    ctx = _l1.build_l1_context(
        query="сегодня",
        window=[{"author_name": "Кирилл", "text": "Бот, скинь recap чата"},
                {"author_name": "Бот",
                 "text": "За какой период рассказать: сегодня или за "
                         "неделю?"},
                {"author_name": "Кирилл", "text": "сегодня"}],
        bot_replies=("За какой период рассказать: сегодня или за неделю?",))
    assert "[СООБЩЕНИЕ]" in ctx and "сегодня" in ctx
    assert _l1.BOT_REPLIES_SECTION in ctx
    assert "За какой период рассказать" in ctx
    assert "[ПОСЛЕДНИЕ СООБЩЕНИЯ]" in ctx
    assert "скинь recap чата" in ctx
