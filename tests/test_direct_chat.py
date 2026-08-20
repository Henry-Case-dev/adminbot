"""Epic 50 (R50-3/R50-7, Section 58.5/58.6): DirectChatThrottle (token bucket)
и DirectChatService (context partitioning, handle-поток, memorize-хук)."""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.chat_prompts import CHAT_SYSTEM_PROMPT
from services.direct_chat_service import DirectChatService, DirectChatThrottle
from services.llm_client import LLMError
from services.smartmodule_phrases import CHAT_COOLDOWN_PHRASES, CHAT_ERROR_PHRASES
from services.summary_aliases import AliasResolver

CHAT_ID = -1001234567890


@pytest.fixture
def fake_time(monkeypatch):
    """Заменяем time.monotonic() на управляемый счётчик."""
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr("services.direct_chat_service.time", FakeTime)
    return state


def _user(user_id=10, first_name="Вася", last_name="Пупкин", username="vasya"):
    u = MagicMock()
    u.id = user_id
    u.first_name = first_name
    u.last_name = last_name
    u.username = username
    return u


def _message(text="привет, бот", message_id=100, user=None, chat_id=CHAT_ID):
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = chat_id
    m.from_user = user if user is not None else _user()
    return m


def _bot():
    bot = AsyncMock()
    sent = MagicMock()
    sent.message_id = 999
    bot.send_message = AsyncMock(return_value=sent)
    return bot


class FakeMemory:
    def __init__(self, window=None, rag="", memorize_error=None):
        self.window = window if window is not None else []
        self.rag = rag
        self.rag_calls = []
        self.memorized = []
        self.memorize_error = memorize_error

    async def get_window_messages(self, chat_id):
        return self.window

    async def get_rag_context(self, chat_id, query, *, sort_by_timestamp=False,
                              include_direct_reply=False):
        self.rag_calls.append(
            (chat_id, query, sort_by_timestamp, include_direct_reply))
        return self.rag

    async def memorize_facts(self, chat_id, raw_text, source_type, target_user=None):
        if self.memorize_error:
            raise self.memorize_error
        self.memorized.append(dict(
            chat_id=chat_id, raw=raw_text, source=source_type,
            target_user=target_user))


class FakeDB:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else {}   # tg_message_id -> row
        self.lookups = []

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        self.lookups.append((chat_id, tg_message_id))
        return self.rows.get(tg_message_id)


class FakeLLM:
    def __init__(self, text="всё по делу, иди нахуй", error=None):
        self.text = text
        self.error = error
        self.messages = None

    async def generate(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return self.text


def _window_row(user_id=10, author_name="старое имя", text="сообщение", ts=100):
    return {"user_id": user_id, "author_name": author_name, "text": text,
            "timestamp": ts, "media_type": "text", "reply_to_id": None,
            "tg_message_id": None}


def _thread_row(tg_id, user_id=10, author_name="вася", text="сообщение",
                reply_to_id=None):
    return {"user_id": user_id, "author_name": author_name, "text": text,
            "reply_to_id": reply_to_id, "media_type": "text", "tg_message_id": tg_id}


def _make_service(memory=None, db=None, llm=None, aliases=None, throttle=None,
                  bot_id=12345, bot_username="test_bot"):
    return DirectChatService(
        memory or FakeMemory(),
        db or FakeDB(),
        llm or FakeLLM(),
        aliases or AliasResolver("{}"),
        throttle=throttle,
        bot_id=bot_id,
        bot_username=bot_username,
    )


class TestDirectChatThrottle:
    """58.10 #5 (R51-4а): 3 подряд allowed → 4-й denied + остаток; полное
    восстановление после cooldown; изоляция per (chat, user)."""

    def test_burst_limit_exhausted(self, fake_time):
        t = DirectChatThrottle(3, 300.0)
        assert t.allow(CHAT_ID, 10) == 0.0
        assert t.allow(CHAT_ID, 10) == 0.0
        assert t.allow(CHAT_ID, 10) == 0.0
        denied = t.allow(CHAT_ID, 10)
        assert denied > 0
        assert denied == 300.0            # ceil-по-остатку, ничего не прошло

    def test_denied_does_not_spend_charges(self, fake_time):
        t = DirectChatThrottle(1, 300.0)
        assert t.allow(CHAT_ID, 10) == 0.0
        fake_time["now"] += 10
        assert t.allow(CHAT_ID, 10) > 0
        fake_time["now"] += 10
        assert t.allow(CHAT_ID, 10) > 0   # по-прежнему denied (заряд не списан)

    def test_full_refill_after_cooldown(self, fake_time):
        t = DirectChatThrottle(3, 300.0)
        for _ in range(3):
            assert t.allow(CHAT_ID, 10) == 0.0
        assert t.allow(CHAT_ID, 10) > 0
        fake_time["now"] += 300.0         # cooldown прошёл → полное восстановление
        assert t.allow(CHAT_ID, 10) == 0.0

    def test_remaining_is_ceiled_cooldown_elapsed(self, fake_time):
        t = DirectChatThrottle(1, 300.0)
        assert t.allow(CHAT_ID, 10) == 0.0
        fake_time["now"] += 100.0
        assert t.allow(CHAT_ID, 10) == 200.0

    def test_isolation_per_chat_and_user(self, fake_time):
        t = DirectChatThrottle(3, 300.0)
        assert t.allow(CHAT_ID, 10) == 0.0
        assert t.allow(CHAT_ID, 10) == 0.0
        assert t.allow(CHAT_ID, 20) == 0.0      # другой юзер — свой слот
        assert t.allow(-200, 10) == 0.0         # другой чат — свой слот


class TestContextPartitioning:
    """58.10 #6/#7: порядок секций, escape, лимиты, RAG-флаги."""

    @pytest.mark.asyncio
    async def test_section_order_and_flags(self, fake_time):
        window = [
            _window_row(user_id=10, author_name="вася", text="привет"),
            _window_row(user_id=20, author_name="петя", text="как дела"),
        ]
        memory = FakeMemory(window=window, rag="<context>фон</context>")
        db = FakeDB({100: _thread_row(100, user_id=10, author_name="вася",
                                      text="расскажи про дроны", reply_to_id=None)})
        service = _make_service(memory=memory, db=db)
        msg = _message(text="расскажи про дроны")
        blocks = await service._build_user_content(CHAT_ID, msg, "вася")
        assert blocks[0].startswith("<UserResolutionMap>")
        assert blocks[1].startswith("<RAG_Memory>")
        assert blocks[2] == "<Target_User>вася</Target_User>"
        assert blocks[3].startswith("<Global_Context>")
        assert blocks[4].startswith("<Conversation_Thread>")
        # RAG-флаги: sort_by_timestamp + include_direct_reply — только DirectChat
        assert memory.rag_calls == [(CHAT_ID, "расскажи про дроны", True, True)]
        assert "вася: привет" in blocks[3] and "петя: как дела" in blocks[3]

    @pytest.mark.asyncio
    async def test_xml_escape_applied(self, fake_time):
        window = [_window_row(text="1 < 2 & 3")]
        memory = FakeMemory(window=window)
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        assert "старое имя: 1 &lt; 2 &amp; 3" in global_block
        assert "1 < 2" not in global_block

    @pytest.mark.asyncio
    async def test_empty_rag_section_omitted(self, fake_time):
        memory = FakeMemory(window=[_window_row()], rag="")
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert all("<RAG_Memory>" not in b for b in blocks)

    @pytest.mark.asyncio
    async def test_global_context_truncated_with_warning(self, fake_time, caplog):
        from config.settings import settings

        window = [_window_row(text="х" * settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS + "!"),
                  _window_row(text="конец")]
        memory = FakeMemory(window=window)
        service = _make_service(memory=memory)
        with caplog.at_level(logging.WARNING):
            blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        assert len(body) <= settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS
        assert "конец" not in body              # последнее сообщение отрезано
        assert any("global context truncated" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_thread_renders_top_down_with_bot_reply(self, fake_time):
        db = FakeDB({
            100: _thread_row(100, user_id=10, author_name="вася",
                             text="ты кто?", reply_to_id=50),
        })
        service = _make_service(db=db)
        service.remember_bot_reply(CHAT_ID, 50, "я твой кошмар")
        blocks = await service._build_user_content(CHAT_ID, _message(text="ты кто?"), "вася")
        thread = next(b for b in blocks if b.startswith("<Conversation_Thread>"))
        assert thread.index("test_bot: я твой кошмар") < thread.index("вася: ты кто?")

    @pytest.mark.asyncio
    async def test_thread_depth_capped(self, fake_time):
        rows = {}
        # цепочка 100 → 99 → 98 → … → 91 (10 уровней)
        for i in range(91, 101):
            rows[i] = _thread_row(i, user_id=10, author_name="вася",
                                  text=f"сообщение {i}",
                                  reply_to_id=(i - 1) if i > 91 else None)
        service = _make_service(db=FakeDB(rows))
        blocks = await service._build_user_content(CHAT_ID, _message(message_id=100), "вася")
        thread = next(b for b in blocks if b.startswith("<Conversation_Thread>"))
        from config.settings import settings
        assert thread.count("вася: сообщение") == settings.CHAT_THREAD_MAX_DEPTH
        assert "сообщение 91" not in thread       # глубина 6, дальше — стоп

    @pytest.mark.asyncio
    async def test_thread_break_on_missing(self, fake_time):
        service = _make_service(db=FakeDB({}))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert all("<Conversation_Thread>" not in b for b in blocks)


class TestHandleFlow:
    """58.4: кулдаун-фраза, payload system@0, Reply на сообщение, memorize-хук."""

    def _collect_fire_forget(self, monkeypatch):
        tasks = []

        def sync_fire_and_forget(coro, tag):
            tasks.append(coro)

        monkeypatch.setattr("services.direct_chat_service.fire_and_forget",
                            sync_fire_and_forget)
        return tasks

    @pytest.mark.asyncio
    async def test_success_reply_and_memorize(self, fake_time, monkeypatch):
        tasks = self._collect_fire_forget(monkeypatch)
        memory = FakeMemory(window=[_window_row()])
        llm = FakeLLM(text="короткий ответ бота")
        aliases = AliasResolver('{"10": "вася"}')
        service = _make_service(memory=memory, llm=llm, aliases=aliases)
        bot = _bot()
        msg = _message(text="расскажи про себя", message_id=77)
        await service.handle(bot, msg, msg.from_user)
        # payload: system на индексе 0 (R51-4в)
        assert llm.messages[0]["role"] == "system"
        assert llm.messages[0]["content"] == CHAT_SYSTEM_PROMPT
        assert llm.messages[1]["role"] == "user"
        assert llm.messages[1]["content"].startswith("<UserResolutionMap>")
        # Reply на сообщение юзера
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        assert bot.send_message.await_args.args[1] == "короткий ответ бота"
        # memorize: origin + target_user + запрос+ответ парой (fire-and-forget)
        assert tasks, "memorize-hook не запланирован"
        await tasks[0]
        assert memory.memorized[0]["source"] == "bot_direct_reply"
        assert memory.memorized[0]["target_user"] == "вася"
        assert memory.memorized[0]["chat_id"] == CHAT_ID
        assert memory.memorized[0]["raw"] == "расскажи про себя\nкороткий ответ бота"

    @pytest.mark.asyncio
    async def test_bot_reply_recorded_for_thread(self, fake_time):
        service = _make_service()
        bot = _bot()
        msg = _message(message_id=77)
        await service.handle(bot, msg, msg.from_user)
        assert service.get_bot_reply(CHAT_ID, 999) == "всё по делу, иди нахуй"

    @pytest.mark.asyncio
    async def test_empty_answer_no_memorize_no_bot_reply(self, fake_time, monkeypatch):
        """REVISE S2: пустой ответ → send вернул None → memorize НЕ вызывается
        (memorize ТОЛЬКО ПОСЛЕ успешной отправки, 58.8)."""
        tasks = []

        def sync_fire_and_forget(coro, tag):
            tasks.append(coro)

        monkeypatch.setattr("services.direct_chat_service.fire_and_forget",
                            sync_fire_and_forget)
        memory = FakeMemory(window=[])
        service = _make_service(memory=memory, llm=FakeLLM(text="   "))
        bot = _bot()
        msg = _message(message_id=77)
        await service.handle(bot, msg, msg.from_user)
        assert tasks == []                       # memorize не запланирован
        assert not memory.memorized
        assert service.get_bot_reply(CHAT_ID, 999) is None

    @pytest.mark.asyncio
    async def test_cooldown_phrase_after_burst(self, fake_time):
        llm = FakeLLM()
        service = _make_service(llm=llm, throttle=DirectChatThrottle(3, 300.0))
        bot = _bot()
        for i in range(3):
            await service.handle(bot, _message(message_id=i), _user())
        llm_calls_after_burst = llm.messages
        await service.handle(bot, _message(message_id=99), _user())
        assert llm.messages is llm_calls_after_burst   # LLM НЕ вызван (кулдаун)
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 99
        text = bot.send_message.await_args.args[1]
        candidates = [p.replace("{remaining_time}", "5 мин") for p in CHAT_COOLDOWN_PHRASES]
        assert text in candidates                   # фраза R50-7 с подстановкой

    @pytest.mark.asyncio
    async def test_cooldown_does_not_call_llm(self, fake_time):
        llm = FakeLLM()
        service = _make_service(llm=llm, throttle=DirectChatThrottle(1, 300.0))
        bot = _bot()
        await service.handle(bot, _message(), _user())
        assert llm.messages is not None              # первый — сработал
        await service.handle(bot, _message(message_id=2), _user())
        assert bot.send_message.await_args.args[1] in [
            p.replace("{remaining_time}", "5 мин") for p in CHAT_COOLDOWN_PHRASES]

    @pytest.mark.asyncio
    async def test_llm_error_uses_error_pool(self, fake_time, caplog):
        llm = FakeLLM(error=LLMError("апи сдохло"))
        service = _make_service(llm=llm)
        bot = _bot()
        with caplog.at_level(logging.WARNING):
            await service.handle(bot, _message(), _user())
        assert any("[direct] LLM failed" in r.message for r in caplog.records)
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES

    @pytest.mark.asyncio
    async def test_unexpected_error_uses_error_pool(self, fake_time):
        llm = FakeLLM(error=RuntimeError("внезапно"))
        service = _make_service(llm=llm)
        bot = _bot()
        await service.handle(bot, _message(), _user())
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES


class TestBotRepliesLru:
    def test_lru_eviction_and_ttl(self, fake_time):
        service = _make_service()
        for i in range(5):
            service.remember_bot_reply(CHAT_ID, i, f"ответ {i}")
        assert service.get_bot_reply(CHAT_ID, 0) == "ответ 0"
        fake_time["now"] += 3601.0                   # TTL истёк
        assert service.get_bot_reply(CHAT_ID, 1) is None
        assert (CHAT_ID, 1) not in service._bot_replies

    def test_evicts_oldest_when_over_limit(self, fake_time, monkeypatch):
        service = _make_service()
        for i in range(300):
            service.remember_bot_reply(CHAT_ID, i, f"ответ {i}")
        assert len(service._bot_replies) == 200
        assert service.get_bot_reply(CHAT_ID, 0) is None     # вытеснен
        assert service.get_bot_reply(CHAT_ID, 299) == "ответ 299"
