"""ASAP-3.2 (ADR-1028-5 D11, §47–§52, §74) — LLM-driven decision
REPLY/REACT/SILENT: один Decision Maker structured output в Stage-1.

§47: выбор действия решает LLM (не алгоритм); §48: алгоритм — только hard
gates/cheap safety; §49: force → всегда REPLY; §50: SILENT direct → 🗿;
§51: invalid → детерминированный fallback; §52: call count не растёт
(второй LLM-call запрещён).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.direct_chat_service as dcs
import services.direct_llm_react as llm_react
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver

pytestmark = pytest.mark.asap32

BOT_ID = 12345
CHAT_ID = -1001234567890


class _FakeLLM:
    def __init__(self, text):
        self.text = text
        self.calls = []
        self._chat_model = "deepseek-chat"
        self._fallback_model = ""
        self._base_url = "https://nano-gpt.com/v1"
        self._fallback_base_url = ""

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):
        self.calls.append(messages)
        return self.text


def _bot():
    bot = AsyncMock()
    sent = MagicMock()
    sent.message_id = 999
    bot.send_message = AsyncMock(return_value=sent)
    bot.set_message_reaction = AsyncMock(return_value=True)
    return bot


def _message(text, message_id=100, *, reply_to_bot=False, user_id=10):
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.from_user.username = "vasya"
    if reply_to_bot:
        reply = MagicMock()
        reply.from_user = MagicMock()
        reply.from_user.id = BOT_ID
        reply.text = "ответ бота"
        reply.web_page = None
        m.reply_to_message = reply
    else:
        m.reply_to_message = None
    m.entities = None
    m.web_page = None
    return m


class FakeDB:
    def __init__(self):
        self.db = MagicMock()
        cursor = MagicMock()
        cursor.fetchone = AsyncMock(return_value=None)
        cursor.fetchall = AsyncMock(return_value=[])
        self.db.execute = AsyncMock(return_value=cursor)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return AsyncMock(return_value=None)

    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        return None

    async def get_active_embedding_generation(self, name):
        return None

    async def get_active_participants(self, chat_id, since, cap):
        return []

    async def last_bot_replies(self, chat_id, limit, now):
        return []


class FakeMemory:
    async def get_window_messages(self, chat_id):
        return []

    async def get_rag_context(self, chat_id, query, **kwargs):
        return ""

    async def get_rag_facts(self, chat_id, query, **kwargs):
        return []

    async def rerank_rag_facts(self, query, facts):
        return list(facts)

    async def retrieve_fact_candidates(self, chat_id, query, limit=8):
        return []

    async def memorize_facts(self, chat_id, raw_text, source_type, **kw):
        return None

    async def memorize_self_reply(self, chat_id, essence):
        return 1


def _make_service(llm):
    return DirectChatService(
        FakeMemory(), FakeDB(), llm, AliasResolver("{}"),
        bot_id=BOT_ID, bot_username="test_bot", breaker=None, cache=None,
        tool_router=None)


@pytest.fixture(autouse=True)
def _reset_react_metrics():
    llm_react._METRICS["llm_react_total"] = 0
    llm_react._METRICS["llm_react_llm_choice_total"] = 0
    llm_react._METRICS["llm_react_fallback_total"] = 0
    llm_react._METRICS["distribution"] = {}
    yield
    llm_react._METRICS["llm_react_total"] = 0
    llm_react._METRICS["llm_react_llm_choice_total"] = 0
    llm_react._METRICS["llm_react_fallback_total"] = 0
    llm_react._METRICS["distribution"] = {}


# ── §74: Decision Maker scenarios ───────────────────────────────────────────

class TestDecisionMaker:
    @pytest.mark.asyncio
    async def test_mock_react_json_one_call(self):
        """§74/§52: mock REACT → реакция; РОВНО ОДИН LLM-вызов (второй
        call для emoji запрещён)."""
        llm = _FakeLLM('{"action":"REACT","reaction":"💀","reason":"ирония"}')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=2001, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert len(llm.calls) == 1
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] == "💀"
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_mock_reply_json_without_text_fallback(self):
        """§51: {"action":"REPLY"} без текста → детерминированный fallback
        demoted-матрицы (laughter → реакция), JSON-мусор не уходит."""
        llm = _FakeLLM('{"action":"REPLY"}')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=2002, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] in ("😂", "🤣")
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_silent_background_no_moai(self):
        """§50: SILENT без direct-autonomous (не reply_to_bot — здесь
        decision не вызывается, фон) → тишина без реакции."""
        llm = _FakeLLM("текст")
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("фоновый разговор", message_id=2003,
                       reply_to_bot=False)
        await svc.handle(bot, msg, msg.from_user)
        assert bot.set_message_reaction.await_count == 0

    @pytest.mark.asyncio
    async def test_force_keyword_reply_hard_gate(self):
        """§49/§74: force keyword + модель отвечает текстом → REPLY.
        Decision Task НЕ вводится (hard gate до Decision Maker)."""
        llm = _FakeLLM("всё будет хорошо")
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("бот, ахахах", message_id=2004)
        await svc.handle(bot, msg, msg.from_user)
        assert bot.send_message.await_count >= 1
        # force → матрица не доходит до REACT/SILENT: нет Decision_Task
        user_content = llm.calls[0][1]["content"]
        assert "<Decision_Task>" not in user_content

    @pytest.mark.asyncio
    async def test_real_task_no_decision_task(self):
        """§43/§48: реальные задачи (demoted REPLY: explicit/question) не
        глушатся — Decision Task не вводится (hard product rule)."""
        llm = _FakeLLM("дела отлично")
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("бот, как дела?", message_id=2005, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        user_content = llm.calls[0][1]["content"]
        assert "<Decision_Task>" not in user_content
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_kill_switch_off_legacy_react_task(self, monkeypatch):
        """§80 OFF-паритет: DIRECT_LLM_DECISION_ENABLED=False → прежний
        алгоритмический decision + Reaction_Task контракт ASAP-3.1."""
        monkeypatch.setattr(type(dcs.settings), "DIRECT_LLM_DECISION_ENABLED",
                            False, raising=False)
        llm = _FakeLLM('{"action":"REACT","reaction":"💀"}')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=2006, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        user_content = llm.calls[0][1]["content"]
        assert "<Reaction_Task>" in user_content
        assert "<Decision_Task>" not in user_content
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] == "💀"

    @pytest.mark.asyncio
    async def test_invalid_decision_json_garbage_fallback(self):
        """§51: битый JSON-декор → fallback demoted-матрицы (реакция),
        без отправки мусора текстом."""
        llm = _FakeLLM('{"action":"REACT", broken')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=2007, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] in ("😂", "🤣")


# ── Unit: контракт модуля ───────────────────────────────────────────────────

class TestDecisionContract:
    def test_extract_valid_actions(self):
        assert llm_react.extract_llm_decision(
            '{"action":"REACT","reaction":"🔥"}') == {
                "action": "REACT", "reaction": "🔥", "reason": None}
        assert llm_react.extract_llm_decision(
            '{"action":"SILENT"}')["action"] == "SILENT"
        assert llm_react.extract_llm_decision(
            '{"action":"REPLY"}')["action"] == "REPLY"

    def test_extract_text_is_not_decision(self):
        assert llm_react.extract_llm_decision("обычный ответ") is None
        assert llm_react.extract_llm_decision("") is None
        # JSON-подобная попытка без action → INVALID (не отправляется)
        assert llm_react.extract_llm_decision('{"foo":1}')["action"] == \
            "INVALID"

    def test_extract_fenced(self):
        assert llm_react.extract_llm_decision(
            '```json\n{"action":"SILENT"}\n```')["action"] == "SILENT"

    def test_decision_enabled_conjunction(self, monkeypatch):
        monkeypatch.setattr(type(dcs.settings), "DIRECT_LLM_DECISION_ENABLED",
                            True, raising=False)
        assert llm_react.llm_decision_enabled(True) is True
        assert llm_react.llm_decision_enabled(False) is False
        monkeypatch.setattr(type(dcs.settings), "DIRECT_LLM_DECISION_ENABLED",
                            False, raising=False)
        assert llm_react.llm_decision_enabled(True) is False

    def test_instruction_contains_allowed_actions(self):
        text = llm_react.build_decision_instruction(
            ("REPLY", "REACT", "SILENT"), llm_react.ALLOWED_LLM_REACTIONS)
        assert "REPLY" in text and "REACT" in text and "SILENT" in text
        for emoji in llm_react.ALLOWED_LLM_REACTIONS:
            assert emoji in text
        # без REACT список реакций не печатается
        text2 = llm_react.build_decision_instruction(("REPLY", "SILENT"))
        assert "Разрешённые реакции" not in text2

    def test_record_decision_outcome_metrics(self):
        llm_react._METRICS.pop("decision_total", None)
        llm_react._METRICS.pop("decision_llm_total", None)
        llm_react._METRICS.pop("decision_actions", None)
        llm_react.record_decision_outcome(source="llm", action="REACT")
        llm_react.record_decision_outcome(source="llm", action="SILENT")
        assert llm_react._METRICS["decision_total"] == 2
        assert llm_react._METRICS["decision_llm_total"] == 2
        assert llm_react._METRICS["decision_actions"]["REACT"] == 1
