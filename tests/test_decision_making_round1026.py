"""A7 `decision-making-round1026` (Эпик 3 Wave 5, §38–§48, ADR-1026-20 D1–D12).

Покрытие (T-3651…T-3662):
  * Контракт решения: `action` ≠ `style`, `style=silent` невозможен, аддитивные
    поля (`target_message_id`/`reaction`/`reason_code`/`needs_tools`), служебный
    JSON не в чат / Stage-JSON без `action`.
  * Фаза P (§42–§45): детерминированный приоритет — explicit/question всегда
    reply; эмоции → react; подтверждения/не-адресовано → silent; без
    случайности; «Почему?» не теряется.
  * Фаза T (§46): tool → инструменты → итог; недоступный инструмент →
    `tool_unavailable` + reply (не молчание).
  * Порядок исполнения §46: silent/react → 0 Вербализатора/0 отправок; react
    → `react_moai` на trigger; reply → существующий путь.
  * Контекст §47; настройки §48 (3 тумблера, global/local); reason_code R17-safe.
  * Kill-switch `DIRECT_DECISION_MAKING_ENABLED` OFF → точный A1-baseline;
    сосуществование с `CHAT_SILENCE_*` (без двойного молчания).
  * Границы: канон 12, Δ DDL=0, Δ каталога 473/430/448/102/100/21, версия.
"""
import dataclasses
import inspect
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import APP_VERSION, Settings
from services import param_catalog as pc
from services.direct_chat_service import (
    ACTION_REACT,
    ACTION_REPLY,
    ACTION_SILENT,
    ACTION_TOOL,
    COORDINATOR_ACTIONS,
    REASON_ACKNOWLEDGEMENT,
    REASON_CODES,
    REASON_DEFAULT,
    REASON_DISABLED,
    REASON_ERROR,
    REASON_EXPLICIT_REQUEST,
    REASON_IMAGE_REACTION,
    REASON_LAUGHTER,
    REASON_NOT_ADDRESSED,
    REASON_QUESTION,
    REASON_RECENT_REPLY,
    REASON_TOOL_RESULT,
    REASON_TOOL_UNAVAILABLE,
    REACTION_LAUGH,
    REACTION_MOAI,
    CoordinatorDecision,
    DecisionContext,
    DecisionToggles,
    DirectChatService,
    MSG_ACK,
    MSG_EMOJI,
    MSG_EXPLICIT,
    MSG_LAUGHTER,
    MSG_OTHER,
    MSG_QUESTION,
    _coordinator_choose_action,
    _decision_message_class,
    _decision_pre_action,
    build_coordinator_decision,
    decision_making_enabled,
)
from services.system2_handoff import parse_direct_synthesis, stage2_payload
from services.tool_loop import ToolLoopResult
from services.tool_schemas import TOOL_CALLING_TOOLS

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.system2

_SYNTH_JSON = (
    '{"user_question": "q", "facts": [], "answer_outline": "o", '
    '"limitations": [], "response_mode": "casual"}'
)


def _ctx(**over) -> DecisionContext:
    base = dict(addressed=True)
    base.update(over)
    return DecisionContext(**base)


def _toggles(ignore=True, reactions=True, image=True) -> DecisionToggles:
    return DecisionToggles(ignore, reactions, image)


def _pre(text, *, ctx=None, toggles=None, **kw):
    return _decision_pre_action(
        message_class=_decision_message_class(text),
        context=ctx if ctx is not None else _ctx(),
        toggles=toggles if toggles is not None else _toggles(),
        target_message_id=100,
        **kw)


# ── 1. Контракт решения (T-3651) ───────────────────────────────────────────

class TestDecisionContract:
    def test_actions_split_from_style(self):
        # style никогда не silent; action ∈ {reply,react,silent,tool}.
        d = CoordinatorDecision(
            intent="chat", addressee="author", memory_need=False,
            tool_calls=(), evaluation="none", action=ACTION_REPLY,
            style="silent")
        assert d.style == ""
        assert d.action in COORDINATOR_ACTIONS

    def test_invalid_action_normalized_to_reply(self):
        d = CoordinatorDecision(
            intent="chat", addressee="author", memory_need=False,
            tool_calls=(), evaluation="none", action="yell")
        assert d.action == ACTION_REPLY

    def test_reaction_only_on_react(self):
        d = CoordinatorDecision(
            intent="chat", addressee="author", memory_need=False,
            tool_calls=(), evaluation="none", action=ACTION_REPLY,
            reaction=REACTION_MOAI)
        assert d.reaction is None

    def test_reason_must_be_closed_enum(self):
        d = CoordinatorDecision(
            intent="chat", addressee="author", memory_need=False,
            tool_calls=(), evaluation="none", action=ACTION_REPLY,
            reason_code="made_up")
        assert d.reason_code == REASON_DEFAULT

    def test_additive_fields_present(self):
        raw = ToolLoopResult("x", rounds_used=1, tool_trace=[])
        m = MagicMock()
        m.reply_to_message = None
        d = build_coordinator_decision(
            query="Ок", message=m, raw=raw, user_id=1, image_fired=False,
            dig_fired=False, lore_compiled=False, pre_reason=REASON_ACKNOWLEDGEMENT,
            target_message_id=55)
        assert d.target_message_id == 55
        assert d.reason_code == REASON_ACKNOWLEDGEMENT
        assert d.needs_tools is False
        assert hasattr(d, "reaction")

    def test_stage_json_contracts_unchanged(self):
        data = parse_direct_synthesis(_SYNTH_JSON)
        assert "action" not in data
        payload = stage2_payload(data)
        assert "action" not in payload
        assert "response_mode" not in payload

    def test_decision_is_internal_not_json(self):
        raw = ToolLoopResult("x", rounds_used=1, tool_trace=[])
        m = MagicMock()
        m.reply_to_message = None
        d = build_coordinator_decision(
            query="q", message=m, raw=raw, user_id=1, image_fired=False,
            dig_fired=False, lore_compiled=False)
        assert isinstance(d, CoordinatorDecision)
        assert not hasattr(d, "to_json")


# ── 2. Классификация сообщений (§42–§45) ───────────────────────────────────

class TestMessageClass:
    @pytest.mark.parametrize("text,expected", [
        ("Бот, нарисуй кота", MSG_EXPLICIT),
        ("фактчекни это", MSG_EXPLICIT),
        ("объясни, почему", MSG_EXPLICIT),
        ("что ты знаешь о дронах", MSG_EXPLICIT),
        ("Почему?", MSG_QUESTION),
        ("как дела", MSG_QUESTION),
        ("?", MSG_QUESTION),
        ("???", MSG_QUESTION),
        ("?!", MSG_QUESTION),
        ("...", MSG_OTHER),
        ("АХАХА", MSG_LAUGHTER),
        ("лол", MSG_LAUGHTER),
        ("😂", MSG_EMOJI),
        ("Ок", MSG_ACK),
        ("спасибо", MSG_ACK),
        ("понял", MSG_ACK),
        ("просто фраза", MSG_OTHER),
    ])
    def test_classification(self, text, expected):
        assert _decision_message_class(text) == expected

    def test_empty_is_other(self):
        assert _decision_message_class("") == MSG_OTHER


# ── 3. Политика §42–§45 (T-3653) ───────────────────────────────────────────

class TestPolicy:
    def test_short_real_question_replies(self):
        action, reason, _, target = _pre("Почему?")
        assert (action, reason, target) == (ACTION_REPLY, REASON_QUESTION, 100)

    def test_explicit_request_replies(self):
        action, reason, _, _ = _pre("Бот, нарисуй кота")
        assert action == ACTION_REPLY
        assert reason == REASON_EXPLICIT_REQUEST

    def test_laughter_reacts(self):
        action, reason, reaction, _ = _pre("АХАХА")
        assert action == ACTION_REACT
        assert reason == REASON_LAUGHTER
        # A8 (ADR-1026-21 D1): значение эмодзи стало контекстным (механика
        # делегирована A7→A8); правило/класс/`action` не изменились.
        assert reaction == REACTION_LAUGH

    def test_laughter_no_reactions_toggle_replies(self):
        action, _, _, _ = _pre("АХАХА", toggles=_toggles(reactions=False))
        assert action == ACTION_REPLY

    def test_image_reaction_on_own_image(self):
        action, reason, reaction, _ = _pre(
            "АХАХА", ctx=_ctx(reply_to_bot=True, reply_to_is_image=True))
        assert action == ACTION_REACT
        assert reason == REASON_IMAGE_REACTION
        # A8 (ADR-1026-21 D1): image_reaction → 😂 (контекстный эмодзи).
        assert reaction == REACTION_LAUGH

    def test_image_reactions_off_replies_not_react(self):
        action, _, _, _ = _pre(
            "АХАХА", ctx=_ctx(reply_to_bot=True, reply_to_is_image=True),
            toggles=_toggles(reactions=True, image=False))
        assert action == ACTION_REPLY

    def test_acknowledgement_silent(self):
        action, reason, _, _ = _pre("Ок")
        assert (action, reason) == (ACTION_SILENT, REASON_ACKNOWLEDGEMENT)

    def test_acknowledgement_ignore_off_reply_or_react(self):
        # ignore OFF + reactions ON → react (не молчание);
        # ignore OFF + reactions OFF → существующий текстовый путь.
        action_react, _, _, _ = _pre("Ок", toggles=_toggles(ignore=False))
        assert action_react == ACTION_REACT
        action_reply, _, _, _ = _pre(
            "Ок", toggles=_toggles(ignore=False, reactions=False))
        assert action_reply == ACTION_REPLY

    def test_not_addressed_silent(self):
        action, reason, _, _ = _pre("просто фраза", ctx=_ctx(addressed=False))
        assert (action, reason) == (ACTION_SILENT, REASON_NOT_ADDRESSED)

    def test_not_addressed_after_bot_reply_recent(self):
        action, reason, _, _ = _pre(
            "просто фраза",
            ctx=_ctx(addressed=False, bot_replied_recently=True))
        assert action == ACTION_SILENT
        assert reason == REASON_RECENT_REPLY

    def test_addressed_other_replies(self):
        action, reason, _, _ = _pre("просто фраза")
        assert (action, reason) == (ACTION_REPLY, REASON_DEFAULT)

    def test_expects_tool_result_replies(self):
        action, reason, _, _ = _pre(
            "просто фраза", ctx=_ctx(expects_tool_result=True))
        assert (action, reason) == (ACTION_REPLY, REASON_TOOL_RESULT)

    def test_expects_tool_result_beats_ack_silence(self):
        # F-2/§47(6): при ожидании результата инструмента даже «Ок» — reply,
        # а не silent-подтверждение.
        action, reason, _, _ = _pre("Ок", ctx=_ctx(expects_tool_result=True))
        assert (action, reason) == (ACTION_REPLY, REASON_TOOL_RESULT)
        assert _pre("Ок", ctx=_ctx())[0] == ACTION_SILENT     # контраст

    def test_article_reply_context_replies(self):
        # F-2/§47: ответ на статью-результат бота — reply/tool_result,
        # а не «эмоциональная» реакция/молчание.
        action, reason, _, _ = _pre(
            "Ок", ctx=_ctx(reply_to_bot=True, reply_to_is_article=True))
        assert (action, reason) == (ACTION_REPLY, REASON_TOOL_RESULT)

    def test_private_overrides_not_addressed(self):
        # F-2/§47: в ЛС «не адресовано» неприменимо → reply, не silent.
        action, _, _, _ = _pre(
            "просто фраза", ctx=_ctx(addressed=False, is_private=True))
        assert action == ACTION_REPLY
        assert _pre("просто фраза", ctx=_ctx(addressed=False))[0] \
            == ACTION_SILENT                                  # контраст

    def test_bare_question_punctuation_replies(self):
        # F-3/§42: короткая вопросительная пунктуация — реальный вопрос.
        for text in ("?", "???", "?!"):
            action, reason, _, _ = _pre(text)
            assert (action, reason) == (ACTION_REPLY, REASON_QUESTION), text

    def test_image_emoji_off_replies(self):
        # F-4/D-1 probe: IMAGE_REACTIONS OFF глушит реакции на своё фото
        # даже при REACTIONS ON (эмодзи-подкласс).
        action, _, _, _ = _pre(
            "😂", ctx=_ctx(reply_to_bot=True, reply_to_is_image=True),
            toggles=_toggles(reactions=True, image=False))
        assert action == ACTION_REPLY

    def test_image_reaction_ignores_generic_reactions_off(self):
        # F-4/D-1 probe: для своего изображения решает image-тумблер; общий
        # REACTIONS OFF не должен отменять разрешённую image-реакцию.
        action, _, _, _ = _pre(
            "АХАХА", ctx=_ctx(reply_to_bot=True, reply_to_is_image=True),
            toggles=_toggles(reactions=False, image=True))
        assert action == ACTION_REACT

    def test_pre_gate_fired_replies(self):
        action, reason, _, _ = _pre("АХАХА", image_pre_gate_fired=True)
        assert (action, reason) == (ACTION_REPLY, REASON_TOOL_RESULT)

    def test_deterministic_no_randomness(self):
        results = {_pre("АХАХА") for _ in range(25)}
        assert len(results) == 1

    def test_policy_has_no_random(self):
        src = inspect.getsource(_decision_pre_action)
        assert "random" not in src

    def test_fail_safe_on_bad_toggles(self):
        # Ошибка политики → reply/error, никогда не ложное молчание.
        action, reason, _, _ = _decision_pre_action(
            message_class=MSG_ACK, context=_ctx(), toggles=None,
            target_message_id=1)
        assert action == ACTION_REPLY
        assert reason == REASON_ERROR

    def test_explicit_and_question_never_silent(self):
        for text in ("Бот, найди информацию", "Почему?", "что ты знаешь?",
                     "объясни"):
            for toggles in (_toggles(), _toggles(ignore=False),
                            _toggles(reactions=False)):
                action, _, _, _ = _pre(text, toggles=toggles)
                assert action != ACTION_SILENT, text


# ── 3b. Контекст §47 — реальные поля (F-2, T-3655) ────────────────────────

class TestDecisionContextFields:
    """F-2: `reply_to_is_article`/`is_private`/`expects_tool_result`
    действительно вычисляются из реального контекста `_decision_context`."""

    @staticmethod
    def _svc():
        svc = DirectChatService.__new__(DirectChatService)
        svc.bot_id = 12345
        svc.bot_username = "test_bot"
        return svc

    @staticmethod
    def _message(reply, chat_type="supergroup"):
        msg = MagicMock()
        msg.reply_to_message = reply
        msg.chat = MagicMock()
        msg.chat.type = chat_type
        return msg

    @staticmethod
    def _reply_bot(**over):
        reply = MagicMock()
        reply.from_user = MagicMock()
        reply.from_user.id = 12345
        reply.web_page = None
        reply.text = "текст"
        for attr in ("photo", "video", "video_note", "voice", "audio",
                     "animation", "sticker", "document"):
            setattr(reply, attr, None)
        for key, value in over.items():
            setattr(reply, key, value)
        return reply

    @pytest.mark.asyncio
    async def test_article_sets_expects_tool_result(self):
        reply = self._reply_bot(web_page=MagicMock())
        ctx = await self._svc()._decision_context(
            -100, self._message(reply), "спасибо")
        assert ctx.reply_to_is_article is True
        assert ctx.expects_tool_result is True

    @pytest.mark.asyncio
    async def test_document_result_sets_expects_tool_result(self):
        reply = self._reply_bot(text=None, document=MagicMock())
        ctx = await self._svc()._decision_context(
            -100, self._message(reply), "спасибо")
        assert ctx.reply_to_is_image is False
        assert ctx.expects_tool_result is True

    @pytest.mark.asyncio
    async def test_photo_is_image_not_tool_result(self):
        reply = self._reply_bot(text=None, photo=MagicMock())
        ctx = await self._svc()._decision_context(
            -100, self._message(reply), "АХАХА")
        assert ctx.reply_to_is_image is True
        assert ctx.expects_tool_result is False

    @pytest.mark.asyncio
    async def test_private_marks_addressed(self):
        reply = MagicMock()
        reply.from_user = MagicMock()
        reply.from_user.id = 10                   # сам пользователь
        reply.web_page = None
        reply.text = "моё"
        ctx = await self._svc()._decision_context(
            -1, self._message(reply, "private"), "просто фраза")
        assert ctx.is_private is True
        assert ctx.addressed is True

    @pytest.mark.asyncio
    async def test_group_reply_to_other_not_addressed(self):
        reply = MagicMock()
        reply.from_user = MagicMock()
        reply.from_user.id = 999                  # другой участник
        reply.web_page = None
        reply.text = "чужое"
        ctx = await self._svc()._decision_context(
            -100, self._message(reply), "просто фраза")
        assert ctx.is_private is False
        assert ctx.addressed is False


# ── 4. Фаза T: tool/недоступность инструмента (T-3652) ─────────────────────

class TestPhaseT:
    def test_tool_action_when_tools_ok(self):
        action = _coordinator_choose_action(
            has_tools=True, degraded=False, lore_compiled=False)
        assert action == ACTION_TOOL

    def _build(self, trace, degraded=False):
        raw = ToolLoopResult("x", rounds_used=1, tool_trace=list(trace),
                             degraded=degraded)
        m = MagicMock()
        m.reply_to_message = None
        return build_coordinator_decision(
            query="Бот, загугли", message=m, raw=raw, user_id=1,
            image_fired=False, dig_fired=False, lore_compiled=False)

    def test_tool_reason_tool_result(self):
        d = self._build([{"tool": "execute_web_search", "ok": True}])
        assert d.action == ACTION_TOOL
        assert d.reason_code == REASON_TOOL_RESULT
        assert d.needs_tools is True
        assert d.tool_calls == ("execute_web_search",)

    def test_tool_unavailable_reason_and_reply(self):
        # Провал инструмента → честная причина; финал даёт существующий
        # Stage-2 (не молчание). Действие остаётся `tool` (гейт A1 не меняется).
        d = self._build([{"tool": "execute_web_search", "ok": False}])
        assert d.action == ACTION_TOOL
        assert d.reason_code == REASON_TOOL_UNAVAILABLE
        assert d.needs_tools is True

    def test_degraded_tool_reason_unavailable(self):
        d = self._build([{"tool": "execute_web_search", "ok": True}],
                        degraded=True)
        assert d.action == ACTION_REPLY
        assert d.reason_code == REASON_TOOL_UNAVAILABLE

    def test_plain_reply_default_reason(self):
        d = self._build([])
        assert d.action == ACTION_REPLY
        assert d.reason_code == REASON_DEFAULT


# ── 5. Интеграция `handle`: порядок §46 (T-3654/T-3658) ────────────────────

def _drive(monkeypatch, text, *, reply=None, decision=True, tool_router=None,
           settings_over=None, llm=None):
    import services.direct_chat_service as dcs
    from tests.test_direct_chat import _bot, _make_service, _message, _user
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", decision)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    for key, value in (settings_over or {}).items():
        monkeypatch.setattr(Settings, key, value)
    svc = _make_service(tool_router=tool_router, llm=llm)
    svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc._send_direct_answer = AsyncMock(return_value=999)
    svc.remember_bot_reply = AsyncMock()
    react = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", react)
    msg = _message(text=text)
    if reply is not None:
        msg.reply_to_message = reply
    return svc, react, _bot(), msg, _user()


def _bot_reply(message_id=7, text="картинка"):
    m = MagicMock()
    m.message_id = message_id
    m.text = text
    m.from_user = MagicMock()
    m.from_user.id = 12345          # bot_id из _make_service
    # Явно сбрасываем §47-контекст-поля: MagicMock иначе «автосоздаёт»
    # truthy-атрибуты (web_page/photo/…), искажая статью/медиа.
    m.web_page = None
    for attr in ("photo", "video", "video_note", "voice", "audio",
                 "animation", "sticker", "document"):
        setattr(m, attr, None)
    return m


def _tool_result_ok():
    return ToolLoopResult(
        "финал инструмента", rounds_used=2,
        tool_trace=[{"tool": "execute_web_search", "ok": True}],
        tool_context="логи")


def _tool_result_failed():
    return ToolLoopResult(
        "частичный ответ", rounds_used=4, degraded=True, reason="round_limit",
        tool_trace=[{"tool": "execute_web_search", "ok": False}],
        tool_context="логи")


class _CaptureRouter:
    """Реальный роутер-спай: фиксирует фактический dispatch инструмента."""

    def __init__(self, result="данные поиска"):
        self.calls = []
        self.result = result

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, dict(arguments), ctx.chat_id))
        return self.result


class _ToolAndStageLLM:
    """LLM с обоими контурами: `generate_chat` (tool-раунд + финал) и
    `generate` (Stage-1 Синтезатор + Stage-2 Вербализатор)."""

    def __init__(self):
        self.chat_calls = 0
        self.generate_calls = 0

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        from services.llm_client import LLMChatResult, LLMToolCall
        self.chat_calls += 1
        if self.chat_calls == 1:
            return LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(
                    id="call_1", name="execute_web_search",
                    arguments='{"query": "новости"}')],
                finish_reason="tool_calls")
        return LLMChatResult(content="финал инструмента", tool_calls=None,
                             finish_reason="stop")

    async def generate(self, messages, temperature=None, chat_id=None, **kw):
        self.generate_calls += 1
        return _SYNTH_JSON if self.generate_calls == 1 else "итоговый текст"


class TestHandleOrder:
    @pytest.mark.asyncio
    async def test_silent_no_verbalizer_no_send(self, monkeypatch):
        import services.direct_chat_service as dcs
        svc, react, bot, msg, user = _drive(monkeypatch, "Ок")
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="не должно")
        synth = AsyncMock(return_value=("SYNTH", "serious"))
        svc._synthesize_direct_answer = synth
        await svc.handle(bot, msg, user)
        assert svc.llm.generate.await_count == 0
        synth.assert_not_awaited()
        react.assert_not_awaited()
        svc._send_direct_answer.assert_not_awaited()
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_react_no_verbalizer_target_trigger(self, monkeypatch):
        svc, react, bot, msg, user = _drive(monkeypatch, "АХАХА")
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="не должно")
        msg.message_id = 4242
        await svc.handle(bot, msg, user)
        react.assert_awaited_once()
        assert react.await_args.args == (bot, msg.chat.id, 4242)
        assert svc.llm.generate.await_count == 0
        svc._send_direct_answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reply_path_continues(self, monkeypatch):
        svc, react, bot, msg, user = _drive(monkeypatch, "Почему?")
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="потому что")
        await svc.handle(bot, msg, user)
        react.assert_not_awaited()
        assert svc.llm.generate.await_count == 1
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_image_laugh_reacts(self, monkeypatch):
        svc, react, bot, msg, user = _drive(
            monkeypatch, "АХАХА", reply=_bot_reply(text=""))
        reply_target = msg.reply_to_message
        reply_target.photo = MagicMock()      # медиа → message_media_type=photo
        reply_target.text = None
        await svc.handle(bot, msg, user)
        react.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_question_after_image_replies(self, monkeypatch):
        svc, react, bot, msg, user = _drive(
            monkeypatch, "А почему у него шесть пальцев?", reply=_bot_reply())
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="ответ")
        await svc.handle(bot, msg, user)
        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_addressed_silent(self, monkeypatch):
        other = MagicMock()
        other.message_id = 7
        other.text = "чужое сообщение"
        other.from_user = MagicMock()
        other.from_user.id = 999              # не бот
        svc, react, bot, msg, user = _drive(
            monkeypatch, "просто фраза", reply=other)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="не должно")
        await svc.handle(bot, msg, user)
        svc._send_direct_answer.assert_not_awaited()
        react.assert_not_awaited()
        assert svc.llm.generate.await_count == 0

    @pytest.mark.asyncio
    async def test_off_killswitch_parity_reply(self, monkeypatch):
        svc, react, bot, msg, user = _drive(monkeypatch, "Ок", decision=False)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="обычный ответ")
        await svc.handle(bot, msg, user)
        # OFF → A1-baseline: политика не строится; reply идёт существующим путём.
        assert svc.llm.generate.await_count == 1
        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()

    # ── F-1 (T-3663 rework): end-to-end §46-tool / §43-unavailable ─────────

    @pytest.mark.asyncio
    async def test_tool_path_runs_tools_then_final_action(self, monkeypatch):
        """§46 REQ-A7-25: `action=tool` → инструмент **реально исполнен**
        (router.dispatch) → итоговое действие (текст пользователю через
        существующий Stage-2), не короткое замыкание."""
        import services.direct_chat_service as dcs
        router = _CaptureRouter()
        llm = _ToolAndStageLLM()
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Бот, загугли новости", tool_router=router, llm=llm)
        logged = []
        monkeypatch.setattr(dcs, "_log_coordinator_decision",
                            lambda d, **kw: logged.append(d))
        await svc.handle(bot, msg, user)
        # Инструмент вызван через реальный chat_with_tools + router.dispatch.
        assert router.calls == [("execute_web_search", {"query": "новости"},
                                 msg.chat.id)]
        assert llm.chat_calls == 2                    # tool-раунд + финал
        assert logged and logged[0].action == ACTION_TOOL
        assert logged[0].reason_code == REASON_TOOL_RESULT
        assert logged[0].tool_calls == ("execute_web_search",)
        # Итоговое действие после tool → текст пользователю (Stage-1 + Stage-2).
        assert llm.generate_calls == 2
        svc._send_direct_answer.assert_awaited_once()
        assert svc._send_direct_answer.await_args.args[2] == "итоговый текст"
        react.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tool_degraded_sends_reply_not_silence(self, monkeypatch):
        """§43 REQ-A7-16: недоступный/деградировавший инструмент → честный
        текстовый ответ, НЕ молчание; Вербализатор (Stage-2) не запускается."""
        import services.direct_chat_service as dcs
        svc, react, bot, msg, user = _drive(
            monkeypatch, "Бот, загугли новости", tool_router=MagicMock())
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="не должно")
        svc.remember_bot_reply = AsyncMock()

        async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                       temperature, chat_id=None, **kwargs):
            return _tool_result_failed()

        monkeypatch.setattr(dcs, "chat_with_tools", fake_chat_with_tools)
        logged = []
        monkeypatch.setattr(dcs, "_log_coordinator_decision",
                            lambda d, **kw: logged.append(d))
        await svc.handle(bot, msg, user)
        assert logged and logged[0].reason_code == REASON_TOOL_UNAVAILABLE
        # Ошибка инструмента доведена текстом, а не молчанием/реакцией.
        svc._send_direct_answer.assert_awaited_once()
        react.assert_not_awaited()
        assert svc.llm.generate.await_count == 0     # деградация → без Stage-2

    @pytest.mark.asyncio
    async def test_await_count_two_on_tool_path(self, monkeypatch):
        """F-1c/инвариант 13: ровно 2 физических LLM-вызова System 2
        (Stage-1 + Stage-2) на tool-ходе — третьего вызова нет."""
        import services.direct_chat_service as dcs
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "Бот, загугли новости", tool_router=MagicMock())
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[_SYNTH_JSON, "финал"])
        svc.remember_bot_reply = AsyncMock()

        async def fake_chat_with_tools(llm, payload, *, tools, router, ctx,
                                       temperature, chat_id=None, **kwargs):
            return _tool_result_ok()

        monkeypatch.setattr(dcs, "chat_with_tools", fake_chat_with_tools)
        await svc.handle(bot, msg, user)
        assert svc.llm.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_await_count_zero_on_silent_path(self, monkeypatch):
        """F-1c/§46: `silent` не порождает ни текстового LLM-вызова, ни
        вызова Вербализатора (0 LLM)."""
        svc, react, bot, msg, user = _drive(monkeypatch, "Ок")
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(side_effect=[_SYNTH_JSON, "финал"])
        synth = AsyncMock(return_value=("S", "serious"))
        svc._synthesize_direct_answer = synth
        await svc.handle(bot, msg, user)
        assert svc.llm.generate.await_count == 0
        synth.assert_not_awaited()
        react.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_off_killswitch_reason_disabled(self, monkeypatch):
        """F-5/§3.3 строка 0: OFF kill-switch → reason_code = `disabled`
        (политика не строится, A1-baseline по поведению)."""
        import services.direct_chat_service as dcs
        svc, _react, bot, msg, user = _drive(monkeypatch, "Ок", decision=False)
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="обычный ответ")
        logged = []
        monkeypatch.setattr(dcs, "_log_coordinator_decision",
                            lambda d, **kw: logged.append(d))
        await svc.handle(bot, msg, user)
        assert logged, "решение координатора должно быть залогировано"
        assert logged[0].action == ACTION_REPLY
        assert logged[0].reason_code == REASON_DISABLED

    @pytest.mark.asyncio
    async def test_private_chat_reply_to_other_still_replies(self, monkeypatch):
        """F-2/§47: в ЛС ответ на сообщение (в т.ч. своё) всегда адресован
        боту → reply, а не silent."""
        other = MagicMock()
        other.message_id = 7
        other.text = "своё сообщение"
        other.from_user = MagicMock()
        other.from_user.id = 10                # сам пользователь, не бот
        other.web_page = None
        for attr in ("photo", "video", "voice", "audio", "animation",
                     "sticker", "document"):
            setattr(other, attr, None)
        svc, react, bot, msg, user = _drive(
            monkeypatch, "просто фраза", reply=other)
        msg.chat.type = "private"
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="ответ")
        await svc.handle(bot, msg, user)
        react.assert_not_awaited()
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_throttle_runs_before_decision(self, monkeypatch, caplog):
        """CHAT_SILENCE_*/cooldown — первый барьер: A7 не дублирует молчание."""
        from tests.test_direct_chat import _bot, _make_service, _message, _user
        from services.direct_chat_service import DirectChatThrottle
        svc = _make_service(throttle=DirectChatThrottle(1, 300.0))
        svc.llm = MagicMock()
        svc.llm.generate = AsyncMock(return_value="x")
        bot = _bot()
        user = _user()
        svc.throttle.allow(-1001234567890, 10)      # кулдаун уже активен
        with caplog.at_level("INFO", logger="services.direct_chat_service"):
            await svc.handle(bot, _message(text="Ок", message_id=1), user)
        assert svc.llm.generate.await_count == 0
        assert any("[direct] cooldown" in r.getMessage()
                   for r in caplog.records)
        assert not [r for r in caplog.records
                    if r.getMessage().startswith("[decision]")]


# ── 6. Настройки §48 + каталог (T-3656) ────────────────────────────────────

class TestSettings:
    KEYS = (
        "CHAT_DECISION_IGNORE_TRIVIAL_ENABLED",
        "CHAT_DECISION_REACTIONS_ENABLED",
        "CHAT_DECISION_IMAGE_REACTIONS_ENABLED",
    )

    def test_three_params_in_catalog(self):
        specs = [pc.get_by_pg_key(
            "flags." + k.lower()) for k in self.KEYS]
        for spec in specs:
            assert spec is not None
            assert spec.group == "flags_decision_making"
            assert spec.type == "bool"
            assert spec.per_chat is True
        assert "flags_decision_making" in pc.tab_group_ids("mod_direct")

    def test_defaults_true(self):
        for k in self.KEYS:
            assert getattr(Settings, k) is True

    def test_exactly_three_params_and_one_group(self):
        group_params = [s for s in pc.REGISTRY.values()
                        if s.group == "flags_decision_making"]
        assert len(group_params) == 3
        assert len([g for g in pc.GROUPS
                    if g.id == "flags_decision_making"]) == 1

    @pytest.mark.asyncio
    async def test_toggles_global_resolution(self, monkeypatch):
        import services.direct_chat_service as dcs
        svc = DirectChatService.__new__(DirectChatService)
        monkeypatch.setattr(
            dcs, "settings",
            dataclasses.replace(dcs.settings,
                                CHAT_DECISION_REACTIONS_ENABLED=False))
        t = await svc._decision_toggles(-100)
        assert t.reactions is False
        assert t.ignore_trivial is True and t.image_reactions is True

    @pytest.mark.asyncio
    async def test_toggles_local_override(self, monkeypatch):
        import services.chat_params as cp
        monkeypatch.setattr(Settings, "CHAT_DECISION_REACTIONS_ENABLED", True)

        async def fake_get(chat_id, key, default=None):
            if key == "flags.chat_decision_reactions_enabled":
                return False
            return default

        monkeypatch.setattr(cp, "get_chat_param", fake_get)
        svc = DirectChatService.__new__(DirectChatService)
        t = await svc._decision_toggles(-100)
        assert t.reactions is False


# ── 7. reason_code / R17 (T-3657) ──────────────────────────────────────────

class TestReasonAndR17:
    def test_closed_vocabulary(self):
        assert {
            "explicit_request", "question", "image_reaction", "laughter",
            "emotion", "acknowledgement", "emoji_reaction", "not_addressed",
            "dialogue_completed", "recent_reply", "tool_result",
            "tool_unavailable", "disabled", "default", "error",
        } == set(REASON_CODES)

    @pytest.mark.asyncio
    async def test_logs_r17_safe(self, monkeypatch, caplog):
        other = MagicMock()
        other.message_id = 7
        other.text = "чужое"
        other.from_user = MagicMock()
        other.from_user.id = 999
        secret = "секретный_текст_42"
        svc, _react, bot, msg, user = _drive(monkeypatch, secret, reply=other)
        with caplog.at_level("INFO", logger="services.direct_chat_service"):
            await svc.handle(bot, msg, user)
        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert "[decision]" in blob
        assert secret not in blob


# ── 8. Adversarial §53 (T-3662) ────────────────────────────────────────────

class TestAdversarial:
    def test_silence_never_eats_task(self):
        tasks = ("Бот, нарисуй кота", "Бот, фактчекни это",
                 "объясни, почему так", "что ты знаешь о Риме",
                 "ответь в стиле casual", "Почему?", "Как это работает?")
        for text in tasks:
            action, _, _, _ = _pre(text)
            assert action == ACTION_REPLY, text

    def test_tool_unavailable_is_reply_not_silence(self):
        d = build_coordinator_decision(
            query="Бот, загугли", message=MagicMock(reply_to_message=None),
            raw=ToolLoopResult("частичный", rounds_used=2, degraded=True,
                               reason="round_limit",
                               tool_trace=[{"tool": "execute_web_search",
                                            "ok": False}]),
            user_id=1, image_fired=False, dig_fired=False, lore_compiled=False)
        assert d.action == ACTION_REPLY
        assert d.reason_code == REASON_TOOL_UNAVAILABLE

    def test_robot_not_fully_passive(self):
        # silent — не универсальный ответ: одиночное «Ок» ≠ молчание для задач.
        assert _pre("Бот, привет")[0] == ACTION_REPLY
        assert _pre("расскажи историю")[0] == ACTION_REPLY


# ── 9. Границы / версия / канон (T-3659/T-3660) ────────────────────────────

class TestBounds:
    def test_counts_sanctioned(self):
        assert len(pc.REGISTRY) == 473
        assert len({f.name for f in dataclasses.fields(Settings)}) == 430
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 448
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
        assert len(pc.TAB_RULES) == 21

    def test_version_unchanged(self):
        assert APP_VERSION == "2.58.31"

    def test_canon_twelve_tools(self):
        assert len(TOOL_CALLING_TOOLS) == 12

    def test_kill_switch_not_in_catalog(self):
        assert "DIRECT_DECISION_MAKING_ENABLED" not in pc.REGISTRY
        assert "DIRECT_DECISION_MAKING_ENABLED" not in {
            f.name for f in dataclasses.fields(Settings)}

    def test_kill_switch_default_on(self, monkeypatch):
        monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
        assert decision_making_enabled() is True
        monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", False)
        assert decision_making_enabled() is False

    def test_no_ddl(self):
        src = (ROOT / "services/direct_chat_service.py").read_text(
            encoding="utf-8")
        assert "CREATE TABLE" not in src
        assert "ALTER TABLE" not in src

    def test_no_set_message_reaction_direct_call(self):
        """§41-механика (A8): A7 не вызывает set_message_reaction напрямую."""
        src = (ROOT / "services/direct_chat_service.py").read_text(
            encoding="utf-8")
        assert "set_message_reaction" not in src
