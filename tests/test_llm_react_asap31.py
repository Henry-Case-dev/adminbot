"""ASAP-3.1 (round 1028, ADR-1028-3 D7) — тесты LLM REACT / SILENT / Force
(T-4079, §47/§48).

§47: mock Decision LLM {"action":"REACT","reaction":"💀"} → отправлено 💀;
{"action":"REACT","reaction":"🤡"} → отправлено 🤡; нет hardcoded
laughter→😂 как единственного пути.
§48: SILENT direct → 🗿 даже если LLM вернула другое reaction; background
SILENT → без обязательной реакции; Force → text reply (§33).
Невалидное reaction значение отклоняется валидацией → детерминированный
fallback (§31).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.direct_chat_service as dcs
import services.direct_llm_react as llm_react
from config.settings import settings
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver

pytestmark = pytest.mark.asap31

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

    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        return None

    async def get_running_summary(self, chat_id, now):
        return None

    async def get_summary_level(self, chat_id, level):
        return None

    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_user_tone_preset(self, chat_id, user_id):
        return None

    async def set_user_tone_preset(self, chat_id, user_id, preset):
        return None

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def clear_direct_dialogue(self, chat_id, target_user):
        return 0

    async def forget_direct_facts(self, chat_id, target_user, phrase, ts):
        return 0

    async def get_active_participants(self, chat_id, since, cap):
        return []

    async def get_bot_reply(self, chat_id, tg_id, now):
        return None

    async def get_bot_reply_parent(self, chat_id, tg_id, now):
        return None

    async def set_bot_reply_parent(self, chat_id, tg_id, parent_tg, now):
        return None

    async def upsert_bot_reply(self, chat_id, tg_id, text, ts):
        return None

    async def search_messages_fts(self, chat_id, match, limit):
        return []

    async def search_graph_facts_fts(self, chat_id, match, limit, now):
        return []

    async def list_lore_stories(self, chat_id, limit=200):
        return []

    async def get_messages_around(self, chat_id, target_tg, before, after):
        return []

    async def get_active_embedding_generation(self, name):
        return None


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
def _legacy_direct_l1_off(monkeypatch):
    """ASAP 7 (F1): файл — контракт legacy Reaction_Task/decision-линии
    (asap31); L1-линия (default ON) подменяет топологию. Пин
    DIRECT_L1_ENABLED=false; L1-ветка покрыта tests/test_asap7_direct_l1.py."""
    from config.settings import Settings
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", False)
    yield


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


# ── §47: LLM выбирает реакцию ───────────────────────────────────────────────

class TestLLMReact:
    @pytest.mark.asyncio
    async def test_skull_reaction_sent(self):
        """{"action":"REACT","reaction":"💀"} → отправлено 💀 (не 😂)."""
        llm = _FakeLLM('{"action":"REACT","reaction":"💀","reason":"ирония"}')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=1202, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert llm.calls, "Stage-1 должен быть вызван ровно один раз"
        assert len(llm.calls) == 1
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] == "💀"
        assert bot.send_message.await_count == 0, "текст не отправляется"

    @pytest.mark.asyncio
    async def test_clown_reaction_sent(self):
        """{"action":"REACT","reaction":"🤡"} → отправлено 🤡."""
        llm = _FakeLLM('{"action":"REACT","reaction":"🤡","reason":"троллинг"}')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=1203, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] == "🤡"

    @pytest.mark.asyncio
    async def test_no_hardcoded_laughter_path(self):
        """Нет hardcoded laughter→😂 как единственного пути: разные ответы
        LLM дают разные реакции."""
        for emoji in ("💀", "🤡", "🔥"):
            llm = _FakeLLM(
                '{"action":"REACT","reaction":"%s"}' % emoji)
            svc = _make_service(llm)
            bot = _bot()
            msg = _message("ахах", message_id=1210, reply_to_bot=True)
            await svc.handle(bot, msg, msg.from_user)
            kwargs = bot.set_message_reaction.await_args
            emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
            assert emojis[0] == emoji

    @pytest.mark.asyncio
    async def test_invalid_reaction_falls_back_deterministically(self):
        """Недопустимое значение/мусор → детерминированный fallback (§31).
        ASAP-3.2 D11: невалидный REACT-JSON → fallback-реакция;
        обычный текст = сознательный REPLY (не трактуется как мусор)."""
        for raw in ('{"action":"REACT","reaction":"🫠"}',   # вне allowed set
                    '{"action":"REPLY","reaction":"💀"}'):  # REPLY без текста
            llm = _FakeLLM(raw)
            svc = _make_service(llm)
            bot = _bot()
            msg = _message("ахах", message_id=1220, reply_to_bot=True)
            await svc.handle(bot, msg, msg.from_user)
            kwargs = bot.set_message_reaction.await_args
            emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
            assert emojis[0] in ("😂", "🤣"), \
                "fallback — детерминированный набор laughter-класса"

    @pytest.mark.asyncio
    async def test_plain_text_answer_is_conscious_reply(self):
        """D11 (§52): ответ обычным текстом на Decision Task = REPLY —
        текст уходит пользователю (второго LLM-вызова нет)."""
        llm = _FakeLLM("да ну, не смешно")
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=1221, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_llm_error_falls_back_soft(self):
        """Fail-soft: LLMError → детерминированная реакция, без текста."""
        class FailingLLM(_FakeLLM):
            async def generate(self, messages, temperature=None, chat_id=None,
                               **kwargs):
                self.calls.append(messages)
                from services.llm_client import LLMError
                raise LLMError("transport down")

        llm = FailingLLM("x")
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=1230, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] in ("😂", "🤣")
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_kill_switch_off_deterministic_no_llm(self, monkeypatch):
        """env OFF → байт-в-байт прежний шорт-кат (0 LLM-вызовов)."""
        monkeypatch.setattr(type(settings), "DIRECT_LLM_REACTION_ENABLED",
                            False, raising=False)
        llm = _FakeLLM('{"action":"REACT","reaction":"💀"}')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=1240, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert not llm.calls
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] in ("😂", "🤣")

    @pytest.mark.asyncio
    async def test_per_chat_flag_off_deterministic(self, monkeypatch):
        """per-chat `flags.chat_decision_reactions_enabled=false` → реакции
        выключены (матрица даёт REPLY; ни LLM-выбора, ни детерминированной
        реакции — прежняя семантика A8)."""

        async def fake_toggles(self, chat_id):
            return dcs.DecisionToggles(True, False, True)

        monkeypatch.setattr(DirectChatService, "_decision_toggles",
                            fake_toggles)
        llm = _FakeLLM("обычный ответ")
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=1250, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert bot.set_message_reaction.await_count == 0
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_instruction_block_in_stage1(self):
        """Allowed set передаётся Decision Maker (§31/§51); контекст
        учитывается (тот же payload, что генерировал бы ответ).
        ASAP-3.2 D11: блок — `<Decision_Task>` (LLM решает действие)."""
        llm = _FakeLLM('{"action":"REACT","reaction":"🔥"}')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ахах", message_id=1260, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        user_content = llm.calls[0][1]["content"]
        assert "<Decision_Task>" in user_content
        for emoji in llm_react.ALLOWED_LLM_REACTIONS:
            assert emoji in user_content

    def test_metrics_and_distribution(self):
        llm_react.record_react_outcome(source="llm_decision", reaction="💀")
        llm_react.record_react_outcome(source="deterministic", reaction="😂")
        snap = llm_react.react_metrics_snapshot()
        assert snap["llm_react_total"] == 2
        assert snap["llm_react_llm_choice_total"] == 1
        assert snap["llm_react_fallback_total"] == 1
        assert snap["distribution"] == {"💀": 1, "😂": 1}


# ── §48: SILENT — единственный hardcode ─────────────────────────────────────

class TestSilentMoai:
    @pytest.mark.asyncio
    async def test_silent_direct_always_moai(self):
        """ASAP-3.2 (ADR-1028-5 D11, §50/§74): LLM SILENT (direct addressed
        autonomous) → 🗿 hardcode. Один Decision Task вызов; JSON-решение
        SILENT не публикует текст."""
        llm = _FakeLLM('{"action":"SILENT","reason":"нечего сказать"}')
        svc = _make_service(llm)
        bot = _bot()
        # «ок» → ignore_trivial → demoted SILENT → Decision Task → LLM
        # решает SILENT → 🗿 (конъюнкция reply_to_bot).
        msg = _message("ок", message_id=1301, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert len(llm.calls) == 1, "D11: решение — один Stage-1 вызов"
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] == "🗿"
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_silent_llm_react_conscious_choice(self):
        """D11 (§47): на «ок» LLM может сознательно выбрать REACT —
        алгоритм не навязывает SILENT."""
        llm = _FakeLLM('{"action":"REACT","reaction":"🤨"}')
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ок", message_id=1303, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        kwargs = bot.set_message_reaction.await_args
        emojis = [r.emoji for r in kwargs.kwargs["reaction"]]
        assert emojis[0] == "🤨"
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_llm_reply_text_on_ack(self):
        """D11 (§74): mock {"action":"REPLY"}-текст → text generation."""
        llm = _FakeLLM("ну, если коротко — всё норм")
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("ок", message_id=1304, reply_to_bot=True)
        await svc.handle(bot, msg, msg.from_user)
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_background_silent_no_moai(self):
        """Background SILENT (не reply_to_bot) — БЕЗ обязательной реакции
        (никакого 🗿 фону; §48)."""
        llm = _FakeLLM("текст")
        svc = _make_service(llm)
        bot = _bot()
        # Не reply_to_bot, нет «бот»-слова → free_will (фон) — никакой 🗿.
        msg = _message("просто разговор мимо", message_id=1302,
                       reply_to_bot=False)
        await svc.handle(bot, msg, msg.from_user)
        assert bot.set_message_reaction.await_count == 0


# ── §33: Force keyword → всегда REPLY ───────────────────────────────────────

class TestForceDirect:
    @pytest.mark.asyncio
    async def test_force_keyword_text_reply_even_laughter(self):
        """«бот, ахахах» → REPLY (текст), не REACT/не SILENT, даже если
        сообщение похоже на laughter (force-гейт приоритет 1)."""
        llm = _FakeLLM("держись, всё будет хорошо")
        svc = _make_service(llm)
        bot = _bot()
        msg = _message("бот, ахахах", message_id=1401)
        await svc.handle(bot, msg, msg.from_user)
        assert llm.calls, "force → генерация текстового ответа"
        assert bot.send_message.await_count >= 1


# ── Unit: парсер/валидация ──────────────────────────────────────────────────

class TestExtractReaction:
    def test_valid_emoji(self):
        assert llm_react.extract_llm_reaction(
            '{"action":"REACT","reaction":"💀"}') == "💀"

    def test_fenced_json(self):
        assert llm_react.extract_llm_reaction(
            'преамбула ```json\n{"action":"REACT","reaction":"🔥"}\n```'
        ) == "🔥"

    def test_rejects_out_of_set(self):
        assert llm_react.extract_llm_reaction(
            '{"action":"REACT","reaction":"🫠"}') is None

    def test_rejects_non_react_action(self):
        assert llm_react.extract_llm_reaction(
            '{"action":"SILENT","reaction":"🗿"}') is None

    def test_rejects_garbage(self):
        assert llm_react.extract_llm_reaction("") is None
        assert llm_react.extract_llm_reaction("ахах") is None

    def test_allowed_set_union_a8(self):
        assert set(llm_react.ALLOWED_LLM_REACTIONS) == {
            "😂", "🤣", "👍", "👌", "❤️", "🔥", "🤨", "🤔", "💀", "🤡"}
