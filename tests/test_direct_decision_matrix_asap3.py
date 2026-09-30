"""ASAP-3 (round 1028) — тесты Decision Matrix (T-4018…T-4025, §41–§44).

Приёмочные сценарии владельца:
  §41 FORCE: «бот, …» → REPLY всегда (шорт-каты не перехватывают);
  §42 AUTONOMOUS: reply на бота → Decision Making (REPLY/REACT/SILENT+🗿);
  §43 BACKGROUND: не-addressed silence без 🗿; спама нет;
  §44 FAIL-SOFT: реакция упала → SILENT остаётся SILENT, без текста.
Плюс: trigger-модель (D8), независимый bot_replied_recently (§23),
детерминированный REACT по классу (D9), per-chat autonomous-off (D10).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import settings
import services.direct_chat_service as dcs
from services.direct_chat_service import (
    MSG_ACK, MSG_LAUGHTER, REASON_ACKNOWLEDGEMENT, REASON_FORCE_DIRECT,
    _reaction_for_class, _resolve_direct_trigger,
    bot_replied_recently_window_seconds, silent_ack_enabled,
)

pytestmark = pytest.mark.asap3

BOT_ID = 12345
CHAT_ID = -1001234567890


def _reply_message(text="ответ бота", tg_id=900):
    m = MagicMock()
    m.text = text
    m.message_id = tg_id
    m.from_user = MagicMock()
    m.from_user.id = BOT_ID
    m.web_page = None
    return m


def _message(text, message_id=100, *, reply_to_bot=False, user_id=10,
             chat_type="supergroup"):
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.chat.type = chat_type
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.from_user.username = "vasya"
    m.reply_to_message = _reply_message() if reply_to_bot else None
    m.entities = None
    m.web_page = None
    return m


def _bot():
    bot = AsyncMock()
    sent = MagicMock()
    sent.message_id = 999
    bot.send_message = AsyncMock(return_value=sent)
    bot.set_message_reaction = AsyncMock(return_value=True)
    return bot


def _make_service(llm=None):
    from services.summary_aliases import AliasResolver
    from tests.test_direct_chat import FakeDB, FakeMemory
    return dcs.DirectChatService(
        FakeMemory(), FakeDB(), llm or _FakeLLM(),
        AliasResolver("{}"),
        bot_id=BOT_ID, bot_username="test_bot", breaker=None, cache=None,
        tool_router=None)


class _FakeLLM:
    def __init__(self, text="держись, всё нормально"):
        self.text = text
        self.calls = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.calls.append({"messages": messages, "temperature": temperature})
        return self.text


# ── §41/§20: trigger-матрица ────────────────────────────────────────────────

class TestTriggerMatrix:
    def test_botword_force(self):
        ttype, force = _resolve_direct_trigger(
            "бот, почему?", reply_to_bot=False, bot_username="test_bot")
        assert (ttype, force) == ("force_keyword", True)

    def test_persona_name_force(self):
        ttype, force = _resolve_direct_trigger(
            "Олег, ты тут?", reply_to_bot=False, bot_username="test_bot",
            persona_name_check=lambda text: text.startswith("Олег"))
        assert (ttype, force) == ("persona_name", True)

    def test_mention_force(self):
        ttype, force = _resolve_direct_trigger(
            "эй @test_bot ответь", reply_to_bot=False,
            bot_username="test_bot")
        assert (ttype, force) == ("mention", True)

    def test_reply_to_bot_autonomous(self):
        ttype, force = _resolve_direct_trigger(
            "ну тут ты по-моему неправ", reply_to_bot=True,
            bot_username="test_bot")
        assert (ttype, force) == ("reply_to_bot", False)

    def test_combined_reply_to_bot_with_botword_is_force(self):
        # §4.1: «бот, нет, ответь нормально» (reply-to-bot + ботворд) → force.
        ttype, force = _resolve_direct_trigger(
            "бот, нет, ответь нормально", reply_to_bot=True,
            bot_username="test_bot")
        assert (ttype, force) == ("force_keyword", True)

    def test_plain_free_will(self):
        ttype, force = _resolve_direct_trigger(
            "просто болтовня", reply_to_bot=False, bot_username="test_bot")
        assert (ttype, force) == ("free_will", False)


# ── §41: FORCE → гарантированный REPLY ──────────────────────────────────────

class TestForceReply:
    @pytest.mark.asyncio
    async def test_bot_ok_gets_reply_not_silence(self):
        # «бот, ок» — MSG_ACK; раньше ignore_trivial глушал; теперь force →
        # REPLY до LLM (§21, T-4019).
        llm = _FakeLLM(text="тут")
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("бот, ок", message_id=1101)
        await svc.handle(bot, msg, msg.from_user)
        assert llm.calls, "force обязан дойти до LLM (REPLY)"
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_recent_reply_does_not_cancel_force(self):
        # §23/§41: bot_replied_recently не отменяет force.
        llm = _FakeLLM(text="я тут")
        svc = _make_service(llm=llm)
        with patch.object(svc, "_bot_replied_recently",
                          AsyncMock(return_value=True)):
            bot = _bot()
            msg = _message("бот, ты тут?", message_id=1102)
            await svc.handle(bot, msg, msg.from_user)
        assert llm.calls, "recent_reply не глушит force"
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_force_reply_to_bot_stays_force(self):
        # reply-to-bot с ботвордом → force (приоритет 1 матрицы).
        llm = _FakeLLM(text="отвечаю нормально")
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("бот, нет, ответь нормально", message_id=1103,
                       reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert llm.calls
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_force_short_style_allowed(self):
        # Decision Maker может задавать краткость — но не молчание: «бот,
        # ты тут?» допускает короткий ответ (факт ответа — ключевое).
        llm = _FakeLLM(text="ага")
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("бот, ты тут?", message_id=1104)
        await svc.handle(bot, msg, msg.from_user)
        sent_texts = [c.args[1] for c in bot.send_message.await_args_list
                      if len(c.args) >= 2]
        assert any("ага" in t for t in sent_texts)

    def test_force_direct_reason_code_registered(self):
        # Контракт A7: 16-й код аддитивен, существующие 15 целы.
        assert "force_direct" in dcs.REASON_CODES
        assert len(dcs.REASON_CODES) == 16
        decision = dcs.CoordinatorDecision(
            intent="chat", addressee="author", memory_need=False,
            tool_calls=(), evaluation="none", action="reply",
            reason_code=REASON_FORCE_DIRECT)
        assert decision.reason_code == REASON_FORCE_DIRECT


# ── §42: AUTONOMOUS reply-to-bot ────────────────────────────────────────────

class TestAutonomous:
    @pytest.mark.asyncio
    async def test_question_reply_goes_through_decision(self):
        # reply_to_bot «а почему?» → содержательный вопрос → REPLY.
        llm = _FakeLLM(text="потому что так")
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("а почему?", message_id=1201, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert llm.calls
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_laughter_prefers_react(self, monkeypatch):
        # reply_to_bot «ахах» → предпочтительно REACT (набор {😂,🤣}).
        # ASAP-3.1 (ADR-1028-3 D7): детерминированный шорт-кат — путь
        # kill-switch `DIRECT_LLM_REACTION_ENABLED=false` (OFF-паритет);
        # ON-путь LLM-выбора покрыт test_llm_react_asap31.py.
        monkeypatch.setattr(type(settings), "DIRECT_LLM_REACTION_ENABLED",
                            False, raising=False)
        llm = _FakeLLM(text="не нужен текст")
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("ахах", message_id=1202, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert not llm.calls, "REACT (kill-switch OFF) не должен ходить в LLM"
        assert bot.set_message_reaction.await_count >= 1
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis and emojis[0] in ("😂", "🤣")
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_ack_silent_gets_moai_ack(self):
        # reply_to_bot «ок» → ignore_trivial → demoted SILENT → Decision
        # Task → LLM SILENT → 🗿 (§25 конъюнкция; ASAP-3.2 D11: SILENT —
        # conscious LLM-решение, один Stage-1 вызов).
        llm = _FakeLLM(text='{"action":"SILENT","reason":"нечего сказать"}')
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("ок", message_id=1203, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert len(llm.calls) == 1
        assert bot.set_message_reaction.await_count >= 1
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] == "🗿"
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_silent_ack_env_off_is_silence(self, monkeypatch):
        # D10: DIRECT_SILENT_ACK_ENABLED=false → тишина без 🗿 (паритет).
        # ASAP-3.2 D11: LLM SILENT — тишина без 🗿 и без текста.
        # Целимся в класс module-привязанного instance (reload-safe).
        monkeypatch.setattr(type(dcs.settings), "DIRECT_SILENT_ACK_ENABLED",
                            False)
        assert not silent_ack_enabled()
        llm = _FakeLLM(text='{"action":"SILENT","reason":"нечего сказать"}')
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("ок", message_id=1204, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert bot.set_message_reaction.await_count == 0
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_per_chat_autonomous_off_always_replies(self, monkeypatch):
        # D10: flags.chat_autonomous_reply_enabled=false → reply-to-bot этого
        # чата всегда текстовый ответ (decision-матрица не применяется).
        async def fake_param(chat_id, key, default=None):
            if key == "flags.chat_autonomous_reply_enabled":
                return False
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            fake_param)
        llm = _FakeLLM(text="ок, отвечаю текстом")
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("ахах", message_id=1205, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert llm.calls, "autonomous-off → REPLY вместо REACT"
        assert bot.send_message.await_count >= 1


# ── §25/§26: конъюнкция 🗿 ──────────────────────────────────────────────────

class TestSilentAckConjunction:
    @pytest.mark.asyncio
    async def test_not_addressed_silent_no_moai(self):
        # §26: не-addressed silence НЕ получает 🗿 (фон/free-will — тем более).
        llm = _FakeLLM()
        svc = _make_service(llm=llm)
        ctx = dcs.DecisionContext(reply_to_bot=False, addressed=False,
                                  is_private=False)
        with patch.object(svc, "_decision_context",
                          AsyncMock(return_value=ctx)), \
                patch.object(dcs, "_decision_pre_action",
                             return_value=(dcs.ACTION_SILENT,
                                           REASON_ACKNOWLEDGEMENT,
                                           None, 1301)):
            bot = _bot()
            msg = _message("ахах между своими", message_id=1301)
            await svc.handle(bot, msg, msg.from_user)
        assert bot.set_message_reaction.await_count == 0
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_force_never_reaches_silent_branch(self):
        # §52.F: force не может закончиться SILENT/REACT — в force-ветке
        # pre_action принудительно REPLY (без вызова _decision_pre_action).
        llm = _FakeLLM(text="ответ")
        svc = _make_service(llm=llm)
        with patch.object(dcs, "_decision_pre_action",
                          side_effect=AssertionError("шорт-каты недостижимы "
                                                     "для force")) as sp:
            bot = _bot()
            msg = _message("бот, ок", message_id=1302)
            await svc.handle(bot, msg, msg.from_user)
        sp.assert_not_called()
        assert llm.calls


# ── §44: fail-soft реакции ──────────────────────────────────────────────────

class TestReactionFailure:
    @pytest.mark.asyncio
    async def test_silent_ack_failure_stays_silent(self):
        # §28/§44: падение API реакции → SILENT остаётся SILENT, текст НЕ
        # генерируется, отказ логируется. ASAP-3.2 D11: SILENT выбирает LLM
        # (один Stage-1 вызов); fail-soft ack — без текста.
        llm = _FakeLLM(text='{"action":"SILENT","reason":"нечего сказать"}')
        svc = _make_service(llm=llm)
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=RuntimeError("telegram down"))
        msg = _message("ок", message_id=1401, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert len(llm.calls) == 1, "D11: один Decision Task вызов"
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_react_failure_no_text(self, monkeypatch):
        # §28: REACT-failure не генерирует текст (механика A8, ≤2 попытки).
        # ASAP-3.1: детерминированный путь = kill-switch OFF (паритет).
        monkeypatch.setattr(type(settings), "DIRECT_LLM_REACTION_ENABLED",
                            False, raising=False)
        llm = _FakeLLM(text="не должен уйти")
        svc = _make_service(llm=llm)
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=RuntimeError("telegram down"))
        msg = _message("ахах", message_id=1402, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert not llm.calls
        assert bot.send_message.await_count == 0


# ── §23: reply_to_bot ≠ bot_replied_recently ────────────────────────────────

class TestBotRepliedRecentlyIndependence:
    def test_window_env_default_600(self):
        assert bot_replied_recently_window_seconds() == 600

    @pytest.mark.asyncio
    async def test_recent_true_without_reply_to_bot(self):
        # Недавний ответ бота (bot_replies) при НЕ-reply сообщении — признаки
        # независимы (фикс :1233, §23). Внимание: метод читает self.db.db.
        svc = _make_service()
        cursor = MagicMock()
        cursor.fetchone = AsyncMock(return_value={"1": 1})
        fake_inner = MagicMock()
        fake_inner.execute = AsyncMock(return_value=cursor)
        fake_db = MagicMock()
        fake_db.db = fake_inner
        svc.db = fake_db
        assert await svc._bot_replied_recently(CHAT_ID) is True
        # и наоборот: нет недавних ответов → False.
        cursor2 = MagicMock()
        cursor2.fetchone = AsyncMock(return_value=None)
        fake_inner.execute = AsyncMock(return_value=cursor2)
        assert await svc._bot_replied_recently(CHAT_ID) is False

    @pytest.mark.asyncio
    async def test_context_fields_independent(self):
        svc = _make_service()
        cursor_yes = MagicMock()
        cursor_yes.fetchone = AsyncMock(return_value={"1": 1})
        fake_inner = MagicMock()
        fake_inner.execute = AsyncMock(return_value=cursor_yes)
        fake_db = MagicMock()
        fake_db.db = fake_inner
        svc.db = fake_db
        msg = _message("ну ок", message_id=1501)
        ctx = await svc._decision_context(CHAT_ID, msg, "ну ок")
        assert ctx.bot_replied_recently is True
        assert ctx.reply_to_bot is False          # больше НЕ приравнены


# ── §24/D9: REACT — детерминированные наборы по классу ─────────────────────

class TestReactionSets:
    def test_laughter_set(self):
        candidates = {"😂", "🤣"}
        for mid in range(1, 40):
            assert _reaction_for_class(MSG_LAUGHTER, mid) in candidates

    def test_ack_set(self):
        candidates = {"👍", "👌", "❤️"}
        for mid in range(1, 40):
            assert _reaction_for_class(MSG_ACK, mid) in candidates

    def test_deterministic_by_message_id(self):
        first = _reaction_for_class(MSG_LAUGHTER, 777)
        for _ in range(5):
            assert _reaction_for_class(MSG_LAUGHTER, 777) == first

    def test_varies_across_ids(self):
        picks = {_reaction_for_class(MSG_LAUGHTER, mid) for mid in range(20)}
        assert len(picks) > 1, "набор из двух кандидатов не вырожден"

    def test_unknown_class_falls_back_moai(self):
        assert _reaction_for_class("other", 1) == "🗿"


# ── §30/§31/§46: decision-side observability (T-4026) ──────────────────────

class TestDecisionObservability:
    @staticmethod
    def _collect_events():
        """DIRECT_* идут через composer-обёртки, DECISION_* — напрямую из
        сервиса: собираем оба binding'а emit_agentic_event."""
        from services import agentic_events
        holders = []

        class _Recorder:
            def __init__(self):
                self.calls = []

            def add(self, module_name):
                return patch(module_name,
                             side_effect=lambda *a, **k:
                             self.calls.append((a, k)))

        return holders

    @pytest.mark.asyncio
    async def test_direct_trigger_and_decision_events(self):
        llm = _FakeLLM(text="я тут")
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("бот, ты тут?", message_id=1601)
        with patch("services.direct_chat_service.emit_agentic_event") as e1, \
                patch("services.direct_context_composer."
                      "emit_agentic_event") as e2:
            await svc.handle(bot, msg, msg.from_user)
        events = {}
        for mock in (e1, e2):
            for c in mock.call_args_list:
                events.setdefault(c.args[0], []).append(c.kwargs)
        trigger = events.get("DIRECT_TRIGGER")
        assert trigger, "DIRECT_TRIGGER обязан эмитироваться (§30)"
        assert trigger[0]["trigger_type"] == "force_keyword"
        assert trigger[0]["force_reply_required"] is True
        assert trigger[0]["reply_to_bot"] is False
        complete = events.get("DECISION_COMPLETE")
        assert complete, "DECISION_COMPLETE обязан нести аддитивные поля (§31)"
        assert complete[0]["trigger_type"] == "force_keyword"
        assert complete[0]["force_reply_required"] is True
        assert complete[0]["message_class"]
        assert complete[0]["action"] == "reply"
        assert complete[0]["reason"] == REASON_FORCE_DIRECT
        # R17: ни одно событие не содержит raw user text.
        blob = repr(events)
        assert "бот, ты тут" not in blob

    @pytest.mark.asyncio
    async def test_silent_ack_events_and_counters(self):
        # ASAP-3.2 D11: SILENT — conscious LLM-решение (mock SILENT JSON).
        llm = _FakeLLM(text='{"action":"SILENT","reason":"нечего сказать"}')
        svc = _make_service(llm=llm)
        bot = _bot()
        msg = _message("ок", message_id=1602, reply_to_bot=True)
        dcs._composer.reset_direct_metrics()
        with patch("services.direct_chat_service.emit_agentic_event"), \
                patch("services.direct_context_composer."
                      "emit_agentic_event") as e2:
            await svc.handle(bot, msg, msg.from_user)
        events = {}
        for c in e2.call_args_list:
            events.setdefault(c.args[0], []).append(c.kwargs)
        ack = events.get("DIRECT_SILENT_ACK")
        assert ack and ack[0]["reaction"] == "🗿"
        assert ack[0]["success"] is True
        stats = dcs._composer.direct_metrics_snapshot()
        assert stats["direct_silent_ack_success_total"] >= 1
        assert stats["direct_autonomous_silent_total"] >= 1
        dcs._composer.reset_direct_metrics()

    @pytest.mark.asyncio
    async def test_silent_ack_failure_event(self):
        # ASAP-3.2 D11: SILENT — conscious LLM-решение (mock SILENT JSON).
        llm = _FakeLLM(text='{"action":"SILENT","reason":"нечего сказать"}')
        svc = _make_service(llm=llm)
        bot = _bot()
        bot.set_message_reaction = AsyncMock(
            side_effect=RuntimeError("down"))
        msg = _message("ок", message_id=1603, reply_to_bot=True)
        dcs._composer.reset_direct_metrics()
        with patch("services.direct_chat_service.emit_agentic_event"), \
                patch("services.direct_context_composer."
                      "emit_agentic_event") as e2:
            await svc.handle(bot, msg, msg.from_user)
        events = {}
        for c in e2.call_args_list:
            events.setdefault(c.args[0], []).append(c.kwargs)
        failed = events.get("DIRECT_SILENT_ACK_FAILED")
        assert failed and failed[0]["error_code"]
        stats = dcs._composer.direct_metrics_snapshot()
        assert stats["direct_silent_ack_failed_total"] >= 1
        dcs._composer.reset_direct_metrics()

    @pytest.mark.asyncio
    async def test_force_counter_incremented(self):
        llm = _FakeLLM(text="ответ")
        svc = _make_service(llm=llm)
        dcs._composer.reset_direct_metrics()
        await svc.handle(_bot(), _message("бот, привет", message_id=1604),
                         _message("бот, привет", message_id=1604).from_user)
        stats = dcs._composer.direct_metrics_snapshot()
        assert stats["direct_force_reply_total"] >= 1
        dcs._composer.reset_direct_metrics()
