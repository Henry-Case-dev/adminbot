# -*- coding: utf-8 -*-
"""L1D (owner-corrective-initreply 22.10.2026) — контракт формы участия L1.

Директива владельца plans/features/owner-corrective-initreply-2026-10-22.md:

  * §3: разделить «написать текст» (action=reply) и доставку Telegram-reply
    (delivery=reply + target_message_id); target_user_id — смысловой адресат,
    сам по себе reply НЕ включает; source_refs — контекст, а не команда;
  * §1: никакой способ участия не имеет приоритета (reply ≠ предпочтительнее
    обычного сообщения; молчание — полноценный исход); критерии форм —
    позитивные, без словарей слов;
  * §2: инициативный L1 видит окно с id/reply-связями, ответы бота,
    allowed-реакции и повод наблюдателя КАК ПРЕДЛОЖЕНИЕ;
  * ADR-1013-3: прежний канон (прод 2.58.109) заморожен и ведётся лестницей
    миграций на новый.

TEST-LIFECYCLE: CONTRACT owner=INITREPLY-L1D (канон/схема/лестница/контекст)
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import direct_l1 as _l1  # noqa: E402
from services.chat_prompts import (  # noqa: E402
    DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    PREV_DIRECT_L1_PLANNER_1022,
    PREV_DIRECT_L1_PLANNER_CLAR,
    PREV_DIRECT_L1_PLANNER_W1,
    _DIRECT_L1_CLARIFICATION_CONTRACT,
    _DIRECT_L1_CONTINUATION_R3B,
    _DIRECT_L1_PLANNER_BASE,
    _DIRECT_L1_PLANNER_BASE_L1D,
    _DIRECT_L1_PLANNER_BASE_R1022,
    _DIRECT_L1_PLANNER_BASE_R3,
    _DIRECT_L1_PLANNER_RULES,
    _DIRECT_L1_PLANNER_RULES_R3B,
    _DIRECT_L1_PLANNER_RULES_W1,
)
from services.direct_llm_react import ALLOWED_LLM_REACTIONS  # noqa: E402
from services.prompt_migrations import PROMPT_MIGRATIONS  # noqa: E402

#: Прод-байты 2.58.109 (база R1022 + правила FIX-CORRECTIVE-R1).
PROD_1022_SHA16 = "5fdc90b3f1143abe"


def _flatten(text: str) -> str:
    return " ".join(text.split())


# ═══ канон: схема с формой участия, без приоритетов ══════════════════════════

def test_canon_schema_has_delivery_fields():
    """§3: delivery/target_message_id/target_user_id в схеме; action-enum
    и правила 1-7 прежние (совместимость с L1Plan и маршрутами).
    ASAP 2 (§4.1 asap2 source): между секцией участия и ПРАВИЛАМИ вставлен
    контракт «УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА» (текст владельца)."""
    canon = DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert canon == (_DIRECT_L1_PLANNER_BASE_R3
                     + _DIRECT_L1_CLARIFICATION_CONTRACT
                     + _DIRECT_L1_CONTINUATION_R3B
                     + _DIRECT_L1_PLANNER_RULES)
    assert '"action": "reply|react|silent"' in canon
    assert '"delivery": "chat|reply|null"' in canon
    assert '"target_message_id": null' in canon
    assert '"target_user_id": null' in canon
    # правила 1-6 прежние; 7-8 — семантика P0-CORRECTIVE; JSON — 9
    assert "1. Решение семантическое" in canon
    assert "7. Смотри, что человек просит сделать с материалом" in canon
    assert "response_act=research" in canon
    assert "9. В ответе - ровно одна JSON-строка" in canon
    assert "8. В ответе - ровно одна JSON-строка" not in canon


def test_canon_forms_no_priority_and_positive_criteria():
    """§1/§3 (W1: секция §3.7 «ВЫБОР УЧАСТИЯ»; R3: смысловое усиление):
    семантика форм — без приоритетов; reply осмыслен только как ответ на
    конкретное сообщение; адресат текста определяет цель; silent —
    полноценное действие; запрет эвристик/квот."""
    flat = _flatten(DIRECT_L1_PLANNER_SYSTEM_PROMPT)
    assert "Никакое действие не предпочтительнее остальных по умолчанию" \
        in flat
    assert ("Reply возможен, но никогда не обязателен и не используется как "
            "fallback по умолчанию") in flat
    # target_message_id — выбор LLM из окна по смысловой связи
    assert "твоя мысль отвечает именно на это сообщение" in flat
    # R3: адресат текста и цель совпадают; свежесть не решает
    assert ("target_message_id должен быть сообщением этого участника"
            ) in flat
    assert "target_user_id указывай только для реального адресата из окна" \
        in flat
    assert "Свежесть сообщения сама по себе не делает его адресатом" in flat
    assert ("action=reply означает решение написать текст, а не "
            "Telegram-reply") in flat
    # R3: содержательная общая мысль не прячется за молчанием
    assert ("Если по общей теме у тебя есть содержательная мысль для всех, "
            "выбери chat") in flat
    # target_user_id сам по себе не включает reply (сценарий C)
    assert "target_user_id не превращает chat в reply" in flat
    # реакция требует конкретную цель; молчание без полей доставки
    assert ("Для реакции укажи target_message_id сообщения, на которое "
            "ставится реакция") in flat
    assert "без конкретной цели реакция не исполняется" in flat
    assert "Для молчания не заполняй поля доставки и адресата" in flat
    # запрет подгонки/эвристик (§4 директивы) — в каноне владельца
    assert "Не принимай решение по признаку" in flat
    assert "Нет квоты, процента, принудительного чередования" in flat
    # доставка — только для инициативного вызова (Direct scope не переносит
    # инициативный контракт)
    assert ("этот вызов относится к инициативе, отдельно выбери доставку"
            ) in flat
    # запрет подгонки: нет словарей конкретных слов-триггеров
    for banned in ("«лол»", "«ахах", "«ок»"):
        assert banned not in flat


def test_canon_prev_1022_is_exact_prod_bytes():
    """Прод-канон 2.58.109 заморожен байт-в-байт (ступень ADR-1013-3).
    ASAP 2: правила прод-канонов 1022/L1D/W1 собраны из замороженного
    слепка _DIRECT_L1_PLANNER_RULES_W1 (байты прежних активных правил
    неизменны — sha16 ниже доказывает)."""
    assert PREV_DIRECT_L1_PLANNER_1022 == (
        _DIRECT_L1_PLANNER_BASE_R1022 + _DIRECT_L1_PLANNER_RULES_W1)
    assert hashlib.sha256(
        PREV_DIRECT_L1_PLANNER_1022.encode("utf-8")).hexdigest()[:16] == \
        PROD_1022_SHA16
    assert len(PREV_DIRECT_L1_PLANNER_1022) == 3022
    assert PREV_DIRECT_L1_PLANNER_1022 != DIRECT_L1_PLANNER_SYSTEM_PROMPT


def test_migration_ladder_leads_prod_109_to_new_canon():
    steps = PROMPT_MIGRATIONS["prompts.direct_l1_planner_system_prompt"]
    targets = {src: dst for src, dst in steps}
    assert targets[PREV_DIRECT_L1_PLANNER_1022] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    from services.chat_prompts import (PREV_DIRECT_L1_PLANNER_1021,
                                       PREV_DIRECT_L1_PLANNER_BASE,
                                       PREV_DIRECT_L1_PLANNER_L1D)
    assert targets[PREV_DIRECT_L1_PLANNER_1021] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert targets[PREV_DIRECT_L1_PLANNER_BASE] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # W1 (§3.7): прод-канон 2.58.110 (ace6246bd360) ведёт на секцию
    # «ВЫБОР УЧАСТИЯ»; прежний канон заморожен байт-в-байт.
    assert targets[PREV_DIRECT_L1_PLANNER_L1D] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert PREV_DIRECT_L1_PLANNER_L1D == (
        _DIRECT_L1_PLANNER_BASE_L1D + _DIRECT_L1_PLANNER_RULES_W1)
    assert "ФОРМА УЧАСТИЯ" in PREV_DIRECT_L1_PLANNER_L1D
    assert "ФОРМА УЧАСТИЯ" not in DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert "ВЫБОР УЧАСТИЯ" in DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # ASAP 2 (§4.1): прод-канон 2.58.111 (f8ab20121c0265e0, канон W1)
    # ведёт на контракт уточнений; байты слепка точны.
    assert targets[PREV_DIRECT_L1_PLANNER_W1] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert PREV_DIRECT_L1_PLANNER_W1 == (
        _DIRECT_L1_PLANNER_BASE + _DIRECT_L1_PLANNER_RULES_W1)
    assert hashlib.sha256(
        PREV_DIRECT_L1_PLANNER_W1.encode("utf-8")).hexdigest()[:16] == \
        "f8ab20121c0265e0"
    assert "УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА" in \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert "УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА" not in PREV_DIRECT_L1_PLANNER_W1
    # SPEECH-INIT-FIX R3: прод-канон 2.58.113 (W1 + контракт уточнений)
    # ведёт на усиленную секцию участия; слепок точен.
    # SPEECH-CANON R3b: R3-канон ведёт на канон с усилением продолжения;
    # откат снимает только ступень R3b (на слепок R3).
    from services.chat_prompts import PREV_DIRECT_L1_PLANNER_R3
    assert targets[PREV_DIRECT_L1_PLANNER_CLAR] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert PREV_DIRECT_L1_PLANNER_CLAR == (
        _DIRECT_L1_PLANNER_BASE + _DIRECT_L1_CLARIFICATION_CONTRACT
        + _DIRECT_L1_PLANNER_RULES_R3B)
    assert targets[PREV_DIRECT_L1_PLANNER_R3] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert PREV_DIRECT_L1_PLANNER_R3 == (
        _DIRECT_L1_PLANNER_BASE_R3 + _DIRECT_L1_CLARIFICATION_CONTRACT
        + _DIRECT_L1_PLANNER_RULES_R3B)
    assert PREV_DIRECT_L1_PLANNER_R3 not in targets.values()
    from services.chat_prompts import PREV_DIRECT_L1_PLANNER_R3B
    assert targets[PREV_DIRECT_L1_PLANNER_R3B] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert PREV_DIRECT_L1_PLANNER_R3B == (
        _DIRECT_L1_PLANNER_BASE_R3 + _DIRECT_L1_CLARIFICATION_CONTRACT
        + _DIRECT_L1_CONTINUATION_R3B + _DIRECT_L1_PLANNER_RULES_R3B)
    # P0-CORRECTIVE: верхняя ступень — текущие активные байты до правки
    from services.chat_prompts import (PREV_DIRECT_L1_PLANNER_P0CS,
                                       PREV_DIRECT_L1_PLANNER_P0CS2,
                                       _DIRECT_L1_PLANNER_RULES_P0CS)
    assert targets[PREV_DIRECT_L1_PLANNER_P0CS] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert targets[PREV_DIRECT_L1_PLANNER_P0CS2] == \
        DIRECT_L1_PLANNER_SYSTEM_PROMPT
    assert PREV_DIRECT_L1_PLANNER_P0CS == (
        _DIRECT_L1_PLANNER_BASE_R3 + _DIRECT_L1_CLARIFICATION_CONTRACT
        + _DIRECT_L1_CONTINUATION_R3B + _DIRECT_L1_PLANNER_RULES_P0CS)
    assert PREV_DIRECT_L1_PLANNER_P0CS != DIRECT_L1_PLANNER_SYSTEM_PROMPT
    # ступени-источники не являются целями прямого маппинга (нет циклов)
    assert PREV_DIRECT_L1_PLANNER_P0CS not in targets.values()
    assert PREV_DIRECT_L1_PLANNER_P0CS2 not in targets.values()
    assert PREV_DIRECT_L1_PLANNER_R3B not in targets.values()
    from services.prompt_migrations import ROLLBACK_MIGRATIONS
    # ADR-1013-3: цепочка отката L1 — active→P0CS2→P0CS→R3b→R3→2.58.113
    assert ROLLBACK_MIGRATIONS["prompts.direct_l1_planner_system_prompt"] == [
        (DIRECT_L1_PLANNER_SYSTEM_PROMPT, PREV_DIRECT_L1_PLANNER_P0CS2),
        (PREV_DIRECT_L1_PLANNER_P0CS2, PREV_DIRECT_L1_PLANNER_P0CS),
        (PREV_DIRECT_L1_PLANNER_P0CS, PREV_DIRECT_L1_PLANNER_R3B),
        (PREV_DIRECT_L1_PLANNER_R3B, PREV_DIRECT_L1_PLANNER_R3),
        (PREV_DIRECT_L1_PLANNER_R3, PREV_DIRECT_L1_PLANNER_CLAR)]
    assert DIRECT_L1_PLANNER_SYSTEM_PROMPT not in targets


# ═══ нормализация плана (никогда не бросает; отсутствие ≠ reply) ════════════

def test_normalize_delivery_contract():
    plan = _l1.normalize_l1_plan({
        "action": "reply", "delivery": "reply", "target_message_id": 321,
        "target_user_id": 77, "confidence": 0.9})
    assert plan.delivery == "reply"
    assert plan.target_message_id == 321
    assert plan.target_user_id == 77
    assert _l1.reply_binding_requested(plan)


def test_normalize_defaults_never_enable_reply():
    """Отсутствие/мусор полей → обычное сообщение (2.58.109-дефект
    невозможен молча)."""
    for data in ({"action": "reply"}, {"action": "reply", "delivery": None},
                 {"action": "reply", "delivery": "CHAT"},
                 {"action": "reply", "delivery": "banana"},
                 {"action": "reply", "delivery": "reply"},   # без цели
                 {"action": "reply", "delivery": "reply",
                  "target_message_id": -5},
                 {"action": "reply", "delivery": "reply",
                  "target_message_id": "abc"},
                 {"action": "reply", "delivery": "reply",
                  "target_message_id": True}):
        plan = _l1.normalize_l1_plan(data)
        assert plan is not None
        assert _l1.reply_binding_requested(plan) is False, data
    # delivery="chat" + смысловой адресат — НЕ reply (сценарий C)
    plan = _l1.normalize_l1_plan({"action": "reply", "delivery": "chat",
                                  "target_user_id": 42})
    assert plan.delivery == "chat" and plan.target_user_id == 42
    assert _l1.reply_binding_requested(plan) is False


def test_normalize_is_total_garbage_safe():
    assert _l1.normalize_l1_plan({"action": "reply", "delivery": 123,
                                  "target_message_id": [],
                                  "target_user_id": {}}) is not None
    assert _l1.normalize_l1_plan(None) is None


def test_fallback_plan_has_no_delivery_binding():
    """Детерминированный fallback (§1.6) не включает reply — решение
    доставки принадлежит только LLM."""
    plan = _l1.fallback_plan("вопрос?")
    assert plan.delivery == ""
    assert plan.target_message_id is None
    assert _l1.reply_binding_requested(plan) is False


# ═══ контекст: идентифицированное окно + равноправие форм ════════════════════

def test_initiative_line_declares_equal_forms():
    line = _l1.INITIATIVE_LINE
    assert "никто бота не звал" in line
    assert "[msg:N]" in line
    assert "никакая форма не имеет приоритета" in line
    assert "предложение, а не приказ" in line


def test_render_window_with_ids_marks_messages_and_reply_links():
    window = [
        {"id": 11, "user_id": 1, "author_name": "Аня", "text": "привет",
         "reply_to_id": None},
        {"id": 12, "user_id": 2, "author_name": "Боря",
         "text": "отвечаю Ане", "reply_to_id": 11},
    ]
    lines = _l1.render_window_lines(window, 10, with_ids=True)
    assert lines[0].startswith("[msg:11] [user:1] Аня: привет")
    assert lines[1].startswith("[msg:12] [user:2] Боря:")
    assert "(ответ на msg:11)" in lines[1]
    # прежний формат (без id) — для прямого чата, байт-совместим
    plain = _l1.render_window_lines(window, 10)
    assert plain == ["Аня: привет", "Боря: отвечаю Ане"]


def test_render_window_with_ids_skips_garbage_fields():
    window = [{"author_name": "Вика", "text": "текст",
               "id": "x", "user_id": None, "reply_to_id": "y"}]
    lines = _l1.render_window_lines(window, 10, with_ids=True)
    assert lines == ["Вика: текст"]


def test_build_l1_context_with_ids_keeps_direct_default():
    """with_ids=False (Direct) — прежняя сборка; with_ids=True — разметка."""
    window = [{"id": 9, "user_id": 3, "author_name": "Галя",
               "text": "вопрос", "reply_to_id": None}]
    ctx_plain = _l1.build_l1_context(query="?", window=window)
    ctx_ids = _l1.build_l1_context(query="?", window=window, with_ids=True)
    assert "[msg:9]" not in ctx_plain
    assert "[msg:9]" in ctx_ids


def test_initiative_context_carries_bot_replies_and_reactions():
    parts = [_l1.INITIATIVE_LINE,
             "разрешённые реакции: " + " ".join(ALLOWED_LLM_REACTIONS)]
    ctx = _l1.build_l1_context(query="инициатива",
                               bot_replies=("мой прошлый ответ",),
                               force_line="; ".join(parts))
    assert _l1.BOT_REPLIES_SECTION in ctx
    assert "мой прошлый ответ" in ctx
    assert _l1.INITIATIVE_LINE in ctx
    for emoji in ALLOWED_LLM_REACTIONS:
        assert emoji in ctx


# ═══ plan-блок Writer: форма доставки доезжает (только инициатива) ═══════════

def test_l2_plan_block_delivery_lines():
    reply_plan = _l1.normalize_l1_plan({
        "action": "reply", "delivery": "reply", "target_message_id": 42})
    block = _l1.build_l2_plan_block(reply_plan, include_delivery=True)
    assert "[msg:42]" in block and "прямым" in block
    chat_plan = _l1.normalize_l1_plan({
        "action": "reply", "delivery": "chat", "target_user_id": 7})
    block_chat = _l1.build_l2_plan_block(chat_plan, include_delivery=True)
    assert "[user:7]" in block_chat and "reply-привязки" in block_chat
    plain_plan = _l1.normalize_l1_plan({"action": "reply"})
    block_plain = _l1.build_l2_plan_block(plain_plan, include_delivery=True)
    assert "самостоятельная реплика" in block_plain
    # Direct (include_delivery=False) — блок без строк доставки
    assert "форма доставки" not in _l1.build_l2_plan_block(reply_plan)


# ═══ граница свежести цели — то же окно, что видел L1 ════════════════════════

def test_context_window_seconds_follows_setting():
    import services.direct_chat_service as dcs
    seconds = dcs._initiative_context_window_seconds()
    assert seconds >= 3600
    from config.settings import settings
    expected = max(3600, int(float(
        getattr(settings, "SUMMARY_WINDOW_HOURS", 6.0)) * 3600))
    assert seconds == expected
