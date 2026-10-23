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
from unittest.mock import AsyncMock

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
    # ── B1 (review-struct 23.10.2026): сама строка «смысловой акт ответа:
    # clarification» — второй model-facing сигнал. При needs=false её нет ни
    # при каком значении флага clarification (в т.ч. true с пустой целью).
    for flag in (False, True):
        block = _l1.build_l2_plan_block(plan, clarification=flag)
        assert "clarification" not in block.lower(), flag
    plan_empty_target = _l1.normalize_l1_plan(
        {"action": "reply", "response_act": "clarification",
         "needs_clarification": True, "clarification_target": "   "})
    assert "clarification" not in _l1.build_l2_plan_block(
        plan_empty_target, clarification=True).lower()
    # валидное структурированное уточнение (true + непустой target) — сигнал
    # легитимен и остаётся вместе с узкой директивой §4.3
    plan_valid = _l1.normalize_l1_plan(
        {"action": "reply", "response_act": "clarification",
         "needs_clarification": True, "clarification_target": "media_target"})
    valid = _l1.build_l2_plan_block(plan_valid, clarification=True)
    assert "смысловой акт ответа: clarification" in valid
    assert "недостающий обязательный предмет: media_target" in valid
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

def test_33_fallback_speech_and_canons_clean():
    """B2 (review-struct 23.10.2026): прежнее покрытие — fallback-план,
    speech-блок и оба канона. Собственно Composer/L1 ON-OFF payload —
    в service-level тестах ниже (test_33_*)."""
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


# ── №34 (B3): реальная миграция/rollback/hot для новых L1/L2-ступеней ───────

_L1_KEY = "prompts.direct_l1_planner_system_prompt"
_L2_KEY = "prompts.direct_chat_verbalizer_system_prompt"


class _ClarCache:
    """ConfigCache-контракт для миграций: pg_available, sync get, async set."""

    def __init__(self, values=None, pg_available=True):
        self.pg_available = pg_available
        self.values = dict(values or {})
        self.set_calls = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))

    def apply_writes(self):
        """Запись, которую ConfigCache.set сделал бы в PG."""
        for key, value, _cat in self.set_calls:
            self.values[key] = value


@pytest.mark.asyncio
async def test_34_migrate_rollback_idempotent_hot_resolve_custom_kept():
    """§5/T34: миграция W1→новые каноны L1/L2 идемпотентна, rollback
    возвращает ПРЕЖНИЕ байты, кастом владельца не перетирается, effective
    (factory → global → hot) отдаёт новую ступень. Per-chat override для
    этих ключей read-path не читает (T-3965/prompt-map-audit: resolve_prompt
    без chat_id) — N/A, не имитируется."""
    from services import hot_config as hot
    from services.prompt_style_blocks import (resolve_prompt,
                                              resolve_prompt_with_source)

    cache = _ClarCache({
        _L1_KEY: cp.PREV_DIRECT_L1_PLANNER_W1,
        _L2_KEY: cp.PREV_CHAT_VERBALIZER_W1_31,
    })
    report = await pm.migrate_prompt_canons(cache)
    assert report == {_L1_KEY: "updated", _L2_KEY: "updated"}
    # порядок set — по объявлению PROMPT_MIGRATIONS (L2-ключ объявлен выше)
    assert [k for k, _v, _c in cache.set_calls] == [_L2_KEY, _L1_KEY]
    assert {k: v for k, v, _c in cache.set_calls} == {
        _L1_KEY: CANON_L1, _L2_KEY: CANON_L2}
    assert {c for _k, _v, c in cache.set_calls} == {"prompts"}
    cache.apply_writes()
    # повторный запуск — no-op (идемпотентность на новых байтах)
    assert await pm.migrate_prompt_canons(cache) == {}
    assert len(cache.set_calls) == 2

    hot.set_config_cache(cache)
    try:
        assert resolve_prompt(_L1_KEY, "CODE_DEFAULT") == CANON_L1
        assert resolve_prompt(_L2_KEY, "CODE_DEFAULT") == CANON_L2
        assert resolve_prompt_with_source(_L1_KEY, "CODE_DEFAULT")[0] == \
            CANON_L1
        # per-chat-слот у stage-ключей не читается (документировано в
        # resolve_prompt_with_source) — параметра chat_id в read-path нет
        import inspect
        assert "chat_id" not in inspect.signature(resolve_prompt).parameters
    finally:
        hot.set_config_cache(None)
    # factory остаётся новой фабрикой (reset-to-factory не вернёт старый баг)
    assert pr.factory_text("direct.base.l1_planner") == CANON_L1
    assert pr.factory_text("direct.base.l2_writer") == CANON_L2

    # rollback → ровно прежние прод-байты 2.58.111; повтор — no-op
    back = _ClarCache({_L1_KEY: CANON_L1, _L2_KEY: CANON_L2})
    assert await pm.rollback_prompt_canons(back) == {
        _L1_KEY: "rolled_back", _L2_KEY: "rolled_back"}
    assert {k: v for k, v, _c in back.set_calls} == {
        _L1_KEY: cp.PREV_DIRECT_L1_PLANNER_W1,
        _L2_KEY: cp.PREV_CHAT_VERBALIZER_W1_31}
    assert {c for _k, _v, c in back.set_calls} == {"prompts"}
    back.apply_writes()
    assert back.values[_L1_KEY] == cp.PREV_DIRECT_L1_PLANNER_W1
    assert await pm.rollback_prompt_canons(back) == {}
    # и ступень снова ведёт вперёд (стек цел)
    assert await pm.migrate_prompt_canons(back) == {
        _L1_KEY: "updated", _L2_KEY: "updated"}

    # кастом владельца (не точное совпадение байт) не перетирается ни в одну
    # сторону: миграция skip, rollback skip
    custom_l1 = cp.PREV_DIRECT_L1_PLANNER_W1 + " правка владельца"
    custom = _ClarCache({_L1_KEY: custom_l1,
                         _L2_KEY: "мой кастом вербализатора"})
    assert await pm.migrate_prompt_canons(custom) == {}
    assert custom.set_calls == []
    edited = _ClarCache({_L1_KEY: CANON_L1 + " правка владельца",
                         _L2_KEY: CANON_L2 + " правка владельца"})
    assert await pm.rollback_prompt_canons(edited) == {}
    assert edited.set_calls == []


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
    # Core v3 (W1 §3.2/§3.3) + owner-абзац §3 аддендума 24.10.2026
    # (P0-CHECKUP/CORE): байты осознанно обновлены вместе с каноном.
    assert hashlib.sha256(
        cp.PERSONALITY_CORE_FULL_TEXT.encode("utf-8")).hexdigest()[:12] == \
        "03514adb2b6a"
    assert hashlib.sha256(
        cp.PERSONALITY_CORE_COMPACT_TEXT.encode("utf-8")).hexdigest()[:12] == \
        "8be08a0d547c"
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


# ═══════════════════════════════════════════════════════════════════════════
# Service-level: реальный DirectChatService.handle, фейковый LLM/память (0 сети)
# ═══════════════════════════════════════════════════════════════════════════

#: Маркеры снятого второго приказа уточнения (model-facing, §3.3/§4.4).
_SECOND_ORDER_MARKERS = (
    "clarify=ask",
    "задай",
    "Ничего кроме вопроса",
    "смысловой акт ответа: clarification",
)


def _drive_l1(monkeypatch, text, *, llm, l1=True, composer_on=False,
              memory=None, reply=None):
    """Real DirectChatService.handle в L1-режиме: моки I/O, без сети.

    Маркеры ``system2``/``asap3`` на самих тестах включают прод-дефолты
    kill-switch'ей (иначе conftest гасит их для «старых» тестов)."""
    import services.direct_chat_service as dcs
    from config.settings import Settings
    from services import prompt_composer as pcomp
    from tests.test_direct_chat import _bot, _make_service, _message, _user

    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", l1)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    # speech ON — второй путь «уточни» проверяется именно под ним
    monkeypatch.setattr(dcs.mca_gates, "character_speech_enabled",
                        lambda: True)
    monkeypatch.setattr(
        dcs, "_composer_resolve_gates",
        AsyncMock(return_value=pcomp.GateState(
            unified_composer_enabled=bool(composer_on))))
    svc = _make_service(llm=llm, memory=memory)
    svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc._send_direct_answer = AsyncMock(return_value=999)
    svc.remember_bot_reply = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", AsyncMock())
    msg = _message(text=text)
    if reply is not None:
        msg.reply_to_message = reply
    return svc, _bot(), msg, _user()


def _messages_text(messages) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages)


def _assert_no_second_clarify_order(text: str) -> None:
    for marker in _SECOND_ORDER_MARKERS:
        assert marker not in text, marker


# ── №33 (B2): итоговый L1-payload Composer ON/OFF и L1 ON — чист (§3.3) ─────

@pytest.mark.system2
@pytest.mark.asap3
@pytest.mark.asyncio
async def test_33_composer_on_off_payload_identical_and_clean(monkeypatch):
    """§6.4/T33: Composer ON не добавляет слоёв (machine_json) и не меняет
    L1-payload; второго приказа уточнения нет ни в одном режиме."""
    from services import prompt_composer as pcomp
    from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json

    llm_off = _FakeLLM(l1=_plan_json(), l2="нормальный ответ")
    svc_off, bot_off, msg_off, user_off = _drive_l1(
        monkeypatch, "что происходит?", llm=llm_off, composer_on=False)
    await svc_off.handle(bot_off, msg_off, user_off)
    off_calls = llm_off.calls_of("l1_planner")
    assert len(off_calls) == 1
    off_text = _messages_text(off_calls[0]["messages"])
    assert CANON_L1 in off_text            # канон L1 реально в payload
    assert "[СООБЩЕНИЕ]" in off_text
    _assert_no_second_clarify_order(off_text)

    llm_on = _FakeLLM(l1=_plan_json(), l2="нормальный ответ")
    svc_on, bot_on, msg_on, user_on = _drive_l1(
        monkeypatch, "что происходит?", llm=llm_on, composer_on=True)
    await svc_on.handle(bot_on, msg_on, user_on)
    on_calls = llm_on.calls_of("l1_planner")
    assert len(on_calls) == 1
    on_text = _messages_text(on_calls[0]["messages"])
    # Composer ON: та же строка системного слоя (Core/Expression не
    # подключаются на машинной стадии), payload не меняется
    machine = pcomp.compose_machine_system(
        CANON_L1, writer="l1_planner", chat_id=1)
    assert machine.system == CANON_L1
    assert on_text == off_text
    _assert_no_second_clarify_order(on_text)


@pytest.mark.system2
@pytest.mark.asap3
@pytest.mark.asyncio
async def test_33_l1_off_and_prev_fallback_payload_clean(monkeypatch):
    """§6.4/T33: L1 OFF (прежний pipeline) и дет. fallback при L1-аварии —
    второго скрытого приказа уточнять нет."""
    from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json

    # L1 OFF → ровно прежний путь, L1-стадии нет
    llm_off = _FakeLLM(l1=_plan_json(), l2="ответ", single="обычный ответ")
    svc, bot, msg, user = _drive_l1(
        monkeypatch, "что происходит?", llm=llm_off, l1=False)
    await svc.handle(bot, msg, user)
    assert llm_off.calls_of("l1_planner") == []
    legacy_text = _messages_text(llm_off.calls[-1]["messages"])
    _assert_no_second_clarify_order(legacy_text)
    assert "<Response_Plan>" not in legacy_text

    # L1 ON, но невалидный JSON дважды → дет. fallback (fallback_plan)
    llm_fb = _FakeLLM(l1="это не json", l2="ответ по контексту")
    svc2, bot2, msg2, user2 = _drive_l1(
        monkeypatch, "что происходит?", llm=llm_fb)
    await svc2.handle(bot2, msg2, user2)
    l2_text = _messages_text(llm_fb.last_messages("l2_writer"))
    assert l2_text                       # L2 реально вызывался
    _assert_no_second_clarify_order(l2_text)
    assert "clarification" not in l2_text.lower()
    assert _l1.fallback_plan("почему?").needs_clarification is False


# ── №19–24 / §3.4 / §8.1 D1 (B4): второй ход видит исходную просьбу ────────

_ORIGINAL = "Бот, скинь recap чата"
_BOT_QUESTION = "За какой период рассказать: сегодня или за неделю?"


def _history_window(rows):
    from tests.test_asap7_direct_l1 import _window
    return _window(rows)


@pytest.mark.system2
@pytest.mark.asap3
@pytest.mark.asyncio
async def test_24_second_turn_sees_original_request_bot_question_answer(
        monkeypatch):
    """T19–T24/CLAR-CTX-THREE: после вопроса бота короткое «сегодня»
    приходит в L1 вместе с исходной просьбой и вопросом бота; restart
    (новый экземпляр сервиса, история перезагружена) даёт тот же payload."""
    from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json
    from tests.test_direct_chat import FakeMemory

    history = [("Кирилл", _ORIGINAL), ("Бот", _BOT_QUESTION)]
    llm = _FakeLLM(l1=_plan_json(response_act="summarization"),
                   l2="сегодня: кратко о чате")
    svc, bot, msg, user = _drive_l1(
        monkeypatch, "сегодня", llm=llm,
        memory=FakeMemory(window=_history_window(history)))
    await svc.handle(bot, msg, user)
    calls = llm.calls_of("l1_planner")
    assert len(calls) == 1
    text = _messages_text(calls[0]["messages"])
    assert _ORIGINAL in text               # исходная просьба (окно)
    assert _BOT_QUESTION in text           # предыдущий вопрос бота
    assert "[СООБЩЕНИЕ]" in text and "сегодня" in text   # ответ человека
    # второй ход не запускает новое уточнение
    l2_text = _messages_text(llm.last_messages("l2_writer"))
    assert "clarification" not in l2_text.lower()

    # «рестарт»: новый экземпляр сервиса + повторная загрузка истории
    llm2 = _FakeLLM(l1=_plan_json(response_act="summarization"),
                    l2="сегодня: кратко о чате")
    svc2, bot2, msg2, user2 = _drive_l1(
        monkeypatch, "сегодня", llm=llm2,
        memory=FakeMemory(window=_history_window(history)))
    await svc2.handle(bot2, msg2, user2)
    text2 = _messages_text(llm2.calls_of("l1_planner")[0]["messages"])
    assert text2 == text


@pytest.mark.system2
@pytest.mark.asap3
@pytest.mark.asyncio
async def test_24_truncated_window_and_branch_are_honest(monkeypatch):
    """T24/§3.4: усечённое окно не выдумывает исходную просьбу; ветка
    (Telegram-reply на вопрос бота) доносит вопрос бота отдельно."""
    import services.direct_chat_service as dcs
    from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json, _bot_reply
    from tests.test_direct_chat import FakeMemory

    # Ограничение окна: истории почти нет — в payload только то, что есть
    llm = _FakeLLM(l1=_plan_json(response_act="summarization"),
                   l2="сегодня: кратко о чате")
    svc, bot, msg, user = _drive_l1(
        monkeypatch, "сегодня", llm=llm,
        memory=FakeMemory(window=_history_window([("Кирилл", "сегодня")])))
    await svc.handle(bot, msg, user)
    text = _messages_text(llm.calls_of("l1_planner")[0]["messages"])
    assert "сегодня" in text
    assert "recap" not in text.lower()      # просьбы нет — и не выдумана
    assert _BOT_QUESTION not in text

    # Бюджет контекста: окно сжимается первым, вопрос (СООБЩЕНИЕ) остаётся —
    # честная деградация вместо подмешивания несуществующего контекста
    llm_small = _FakeLLM(l1=_plan_json(response_act="summarization"),
                         l2="сегодня: кратко о чате")
    svc_s, bot_s, msg_s, user_s = _drive_l1(
        monkeypatch, "сегодня", llm=llm_small,
        memory=FakeMemory(window=_history_window(
            [("Кирилл", _ORIGINAL), ("Бот", _BOT_QUESTION)])))
    with monkeypatch.context() as m_small:
        m_small.setattr(_l1, "l1_context_tokens", lambda: 140)
        await svc_s.handle(bot_s, msg_s, user_s)
    small = _messages_text(llm_small.calls_of("l1_planner")[0]["messages"])
    assert "сегодня" in small
    assert "recap" not in small.lower()

    # Ветка: пользователь отвечает reply'ем на вопрос бота — ветка доносит
    # вопрос даже без окна истории
    llm_r = _FakeLLM(l1=_plan_json(response_act="summarization"),
                     l2="сегодня: кратко о чате")
    svc_r, bot_r, msg_r, user_r = _drive_l1(
        monkeypatch, "сегодня", llm=llm_r,
        memory=FakeMemory(window=_history_window([("Кирилл", "сегодня")])),
        reply=_bot_reply(message_id=77, text=_BOT_QUESTION))
    await svc_r.handle(bot_r, msg_r, user_r)
    branch = _messages_text(llm_r.calls_of("l1_planner")[0]["messages"])
    assert "[ОТВЕТ НА (reply/цитата)]" in branch
    assert _BOT_QUESTION in branch


@pytest.mark.system2
@pytest.mark.asap3
@pytest.mark.asyncio
async def test_24_first_turn_clarification_asks_one_and_continues(monkeypatch):
    """T19–T21: первый ход с подлинно неизвестным предметом — ровно один
    адресный вопрос (§4.3), без generic-опроса и без квот/счётчиков."""
    from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json
    from tests.test_direct_chat import FakeMemory

    llm = _FakeLLM(
        l1=_plan_json(response_act="clarification", needs_clarification=True,
                      clarification_target="period"),
        l2="За какой период: сегодня или за неделю?")
    svc, bot, msg, user = _drive_l1(
        monkeypatch, _ORIGINAL, llm=llm,
        memory=FakeMemory(window=_history_window([("Кирилл", _ORIGINAL)])))
    await svc.handle(bot, msg, user)
    assert len(llm.calls_of("l2_writer")) == 1
    l2_text = _messages_text(llm.last_messages("l2_writer"))
    assert "недостающий обязательный предмет: period" in l2_text
    assert "Спроси только о нём" in l2_text
    assert "Ничего кроме вопроса" not in l2_text
    # валидное уточнение — единственная ветка, где допустим и act-сигнал
    assert "смысловой акт ответа: clarification" in l2_text
    svc._send_direct_answer.assert_awaited_once()
    assert svc._send_direct_answer.await_args.args[2].startswith(
        "За какой период")
