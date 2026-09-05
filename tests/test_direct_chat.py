"""Epic 50 (R50-3/R50-7, Section 58.5/58.6): DirectChatThrottle (token bucket)
и DirectChatService (context partitioning, handle-поток, memorize-хук).
Epic 60 (Section 63.1/63.2, T-460/T-461): persistent-троттлинг
(PersistentThrottle), bot_replies в БД, per-chat замок генерации.
Epic 60 (Section 65, T-469/T-471/T-472/T-476/T-477): 🗿-молчание, стачка
кулдаунов, стилевые якоря, temperature-пресеты, mood-блок."""
import asyncio
import dataclasses
import logging
import re
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services.chat_prompts import CHAT_SYSTEM_PROMPT
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService, DirectChatThrottle
from services.llm_circuit_breaker import (
    LLMCircuitBreaker,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
)
from services.llm_client import (
    LLMAuthError,
    LLMBadResponseError,
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMTransportError,
)
from services.persistent_throttling import PersistentThrottle, SilenceStreak
from services.smart_cache import SmartCache, build_key
from services.smartmodule_phrases import (
    CHAT_COOLDOWN_PHRASES,
    CHAT_ERROR_PHRASES,
    CHAT_LLM_DOWN_PHRASES,
    CHAT_LOCK_BUSY_PHRASES,
)
from services.summary_aliases import AliasResolver

CHAT_ID = -1001234567890


@pytest.fixture
def fake_time(monkeypatch):
    """Заменяем time в direct_chat_service на управляемый счётчик
    (monotonic — CB/throttle; time — bot_replies TTL)."""
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

        @staticmethod
        def time():
            return state["now"]

    monkeypatch.setattr("services.direct_chat_service.time", FakeTime)
    return state


@pytest.fixture
def fake_wall(monkeypatch):
    """Заменяем time.time() в persistent_throttling на управляемую стену."""
    state = {"now": 1_800_000_000.0}

    class FakeTime:
        @staticmethod
        def time():
            return state["now"]

    monkeypatch.setattr("services.persistent_throttling.time", FakeTime)
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
    # Раунд 8 (D4/T-801): reply-маркер триггера <Conversation_Branch> —
    # у обычного сообщения его нет (MagicMock без явного поля авто-создал бы).
    m.reply_to_message = None
    return m


def _bot():
    bot = AsyncMock()
    sent = MagicMock()
    sent.message_id = 999
    bot.send_message = AsyncMock(return_value=sent)
    return bot


def _block_tag(block: str) -> str:
    """Первая строка-тег блока для сравнения порядка (sandwich — без тега)."""
    if block.startswith("отвечай коротко"):
        return "<sandwich>"
    m = re.match(r"<[A-Za-z_]+>", block)
    return m.group(0) if m else block.split("\n", 1)[0][:24]


class FakeMemory:
    """Раунд 8 (F1-F4/T-807-T-810): direct-путь ходит в memory через
    get_rag_facts (список 3-кортежей rel-порядка) + rerank_rag_facts
    (LLM-фильтр; вызов записывается — флаг проверяет direct-слой)."""

    def __init__(self, window=None, rag="", rag_facts=None,
                 memorize_error=None):
        self.window = window if window is not None else []
        self.rag = rag
        self.rag_facts = rag_facts               # None → производное от rag
        self.memorize_error = memorize_error
        self.rag_facts_calls = []
        self.rerank_calls = []
        self.memorized = []

    async def get_window_messages(self, chat_id):
        return self.window

    async def get_rag_context(self, chat_id, query, *, sort_by_timestamp=False,
                              include_direct_reply=False):
        self.rag_facts_calls.append(("ctx", chat_id, query, sort_by_timestamp,
                                     include_direct_reply))
        return self.rag

    async def get_rag_facts(self, chat_id, query, *,
                            include_direct_reply=False):
        self.rag_facts_calls.append(
            (chat_id, query, include_direct_reply))
        if self.rag_facts is not None:
            return list(self.rag_facts)
        return [("chat_history", self.rag, None)] if self.rag else []

    async def rerank_rag_facts(self, query, facts):
        self.rerank_calls.append((query, len(facts)))
        return list(facts)

    async def memorize_facts(self, chat_id, raw_text, source_type, target_user=None):
        if self.memorize_error:
            raise self.memorize_error
        self.memorized.append(dict(
            chat_id=chat_id, raw=raw_text, source=source_type,
            target_user=target_user))


class FakeDB:
    def __init__(self, rows=None, tone_preset=None):
        self.rows = rows if rows is not None else {}   # tg_message_id -> row
        self.lookups = []
        self.tone_preset = tone_preset
        self.tone_sets = []

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        self.lookups.append((chat_id, tg_message_id))
        return self.rows.get(tg_message_id)

    # Epic 60 Фаза C: заглушки новых методов (реальный DatabaseService их
    # имеет; FakeDB — для контекст-тестов без БД).
    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_user_tone_preset(self, chat_id, user_id):
        return self.tone_preset

    async def set_user_tone_preset(self, chat_id, user_id, preset):
        self.tone_preset = preset
        self.tone_sets.append((chat_id, user_id, preset))

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def clear_direct_dialogue(self, chat_id, target_user):
        return 0

    async def forget_direct_facts(self, chat_id, target_user, phrase, now_ts):
        return 0


class FakeLLM:
    def __init__(self, text="всё по делу, иди нахуй", error=None):
        self.text = text
        self.error = error
        self.messages = None
        self.call_count = 0
        self.temperature = None

    async def generate(self, messages, temperature=None):
        self.call_count += 1
        self.messages = messages
        self.temperature = temperature
        if self.error:
            raise self.error
        return self.text


class GatedLLM:
    """Блокирующий LLM для тестов конкуренции: generate висит на asyncio.Event
    до явного release — детерминированная гонка двух handle()."""

    def __init__(self, text="всё по делу, иди нахуй"):
        self.text = text
        self.enter = asyncio.Event()
        self.call_count = 0

    async def generate(self, messages, temperature=None):
        self.call_count += 1
        await self.enter.wait()
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
                  bot_id=12345, bot_username="test_bot", breaker=None,
                  cache=None, tool_router=None):
    return DirectChatService(
        memory or FakeMemory(),
        db or FakeDB(),
        llm or FakeLLM(),
        aliases or AliasResolver("{}"),
        throttle=throttle,
        bot_id=bot_id,
        bot_username=bot_username,
        breaker=breaker,
        cache=cache,
        tool_router=tool_router,
    )


class TestDirectChatThrottle:
    """63.6 #5 (правка 58.10 #5): persistent-версия token bucket
    (PersistentThrottle) — те же семантики + bucket переживает рестарт."""

    async def _make_throttle(self, path, burst=3, cooldown=300.0):
        d = DatabaseService(str(path))
        await d.initialize()
        return d, PersistentThrottle(burst, cooldown, "direct_chat", d)

    @pytest.mark.asyncio
    async def test_burst_limit_exhausted(self, tmp_path, fake_wall):
        d, t = await self._make_throttle(tmp_path / "p0.db")
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) == 0.0
        denied = await t.allow(CHAT_ID, 10)
        assert denied > 0
        assert denied == 300.0            # ceil-по-остатку, ничего не прошло
        await d.close()

    @pytest.mark.asyncio
    async def test_denied_does_not_spend_charges(self, tmp_path, fake_wall):
        d, t = await self._make_throttle(tmp_path / "p1.db", burst=1)
        assert await t.allow(CHAT_ID, 10) == 0.0
        fake_wall["now"] += 10
        assert await t.allow(CHAT_ID, 10) > 0
        fake_wall["now"] += 10
        assert await t.allow(CHAT_ID, 10) > 0   # по-прежнему denied (заряд не списан)
        await d.close()

    @pytest.mark.asyncio
    async def test_full_refill_after_cooldown(self, tmp_path, fake_wall):
        d, t = await self._make_throttle(tmp_path / "p2.db")
        for _ in range(3):
            assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) > 0
        fake_wall["now"] += 300.0         # cooldown прошёл → полное восстановление
        assert await t.allow(CHAT_ID, 10) == 0.0
        await d.close()

    @pytest.mark.asyncio
    async def test_remaining_is_ceiled_cooldown_elapsed(self, tmp_path, fake_wall):
        d, t = await self._make_throttle(tmp_path / "p3.db", burst=1)
        assert await t.allow(CHAT_ID, 10) == 0.0
        fake_wall["now"] += 100.0
        assert await t.allow(CHAT_ID, 10) == 200.0
        await d.close()

    @pytest.mark.asyncio
    async def test_isolation_per_chat_and_user(self, tmp_path, fake_wall):
        d, t = await self._make_throttle(tmp_path / "p4.db")
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 10) == 0.0
        assert await t.allow(CHAT_ID, 20) == 0.0      # другой юзер — свой слот
        assert await t.allow(-200, 10) == 0.0         # другой чат — свой слот
        await d.close()

    @pytest.mark.asyncio
    async def test_bucket_survives_restart(self, tmp_path, fake_wall):
        """63.6 #5: исчерпанный bucket НЕ «перезаряжается» рестартом."""
        path = tmp_path / "p_restart.db"
        d1 = DatabaseService(str(path))
        await d1.initialize()
        t1 = PersistentThrottle(3, 300.0, "direct_chat", d1)
        for _ in range(3):
            assert await t1.allow(CHAT_ID, 10) == 0.0
        await d1.close()

        d2 = DatabaseService(str(path))               # «рестарт»
        await d2.initialize()
        t2 = PersistentThrottle(3, 300.0, "direct_chat", d2)
        assert await t2.allow(CHAT_ID, 10) > 0        # кулдаун продолжает течь
        await d2.close()

    @pytest.mark.asyncio
    async def test_handle_uses_persistent_throttle_across_restart(self, tmp_path):
        """63.6 #5: handle() с persistent-троттлингом — после «рестарта»
        (новый сервис на той же БД) флудер получает кулдаун-фразу R50-7."""
        path = tmp_path / "svc.db"
        d1 = DatabaseService(str(path))
        await d1.initialize()
        service = _make_service(
            db=d1, llm=FakeLLM(),
            throttle=PersistentThrottle(1, 300.0, "direct_chat", d1))
        await service.handle(_bot(), _message(message_id=1), _user())
        await d1.close()

        d2 = DatabaseService(str(path))
        await d2.initialize()
        service2 = _make_service(
            db=d2, llm=FakeLLM(),
            throttle=PersistentThrottle(1, 300.0, "direct_chat", d2))
        bot = _bot()
        await service2.handle(bot, _message(message_id=2), _user())
        assert bot.send_message.await_args.args[1] in [
            p.replace("{remaining_time}", "5 мин") for p in CHAT_COOLDOWN_PHRASES]
        await d2.close()


class TestDirectChatThrottleInMemory:
    """58.10 #5 (R51-4а): in-memory DirectChatThrottle — fallback-режим
    (THROTTLE_PERSISTENT_ENABLED=false) сохраняет исходные семантики."""

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
    """58.10 #6/#7: порядок секций, escape, лимиты, RAG-флаги.
    Раунд 8 (B2/T-791, spec §3.B2): реордер «важное к концу» — map → rag →
    global → thread → target → current → … → sandwich; uid-рендеры строк
    (C1/T-792)."""

    @pytest.mark.asyncio
    async def test_section_order_and_flags(self, fake_time):
        window = [
            _window_row(user_id=10, author_name="вася", text="привет"),
            _window_row(user_id=20, author_name="петя", text="как дела"),
        ]
        memory = FakeMemory(window=window, rag="фон из памяти")
        db = FakeDB({100: _thread_row(100, user_id=10, author_name="вася",
                                      text="расскажи про дроны", reply_to_id=None)})
        service = _make_service(memory=memory, db=db)
        msg = _message(text="расскажи про дроны")
        blocks = await service._build_user_content(CHAT_ID, msg, "вася")
        # Раунд 8 (§3.B2): map → rag → global → thread → target → current;
        # sandwich — последняя строка (блоки, которых нет, пропущены).
        assert blocks[0].startswith("<UserResolutionMap>")
        assert blocks[1].startswith("<RAG_Memory>")
        assert blocks[2].startswith("<Global_Context>")
        assert blocks[3].startswith("<Conversation_Thread>")
        assert blocks[4] == "<Target_User>вася</Target_User>"
        assert blocks[5].startswith("<Current_Question>")
        assert blocks[-1].startswith("отвечай коротко, по делу")
        # Раунд 8 (F1/T-807): RAG-факты direct — rel-порядок memory
        # (sort_by_timestamp на direct-пути больше не передаётся);
        # include_direct_reply=True — только DirectChat.
        assert memory.rag_facts_calls == [
            (CHAT_ID, "расскажи про дроны", True)]
        assert memory.rerank_calls == []           # флаг реранка off (default)
        # F3/T-809: direct-рендер с origin-меткой («[чат] …»)
        assert blocks[1] == "<RAG_Memory>\n[чат] фон из памяти\n</RAG_Memory>"
        # C1/T-792: uid-рендеры строк Global_Context («имя [uid]: текст»)
        assert "вася [10]: привет" in blocks[2]
        assert "петя [20]: как дела" in blocks[2]

    @pytest.mark.asyncio
    async def test_sandwich_last_and_order_with_all_blocks(self, fake_time):
        """Раунд 8 (п.24/п.25/FR-22/FR-23): полный порядок §3.B2 — map →
        rag → global → thread → target → protected → mood → current →
        anchors → sandwich-строка в самом конце."""
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (?, 'вася', 'день рождения 5 мая', 1.0)", (CHAT_ID,))
        await d.db.commit()
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="спросил", reply_to_id=None,
            timestamp=100, media_type="text", author_name="вася", message_id=100)
        await d.upsert_bot_reply(CHAT_ID, 1, "норм отвечаю", 1000.0)
        window = [_window_row(user_id=10, author_name="вася", text="привет"),
                  _window_row(user_id=20, author_name="петя", text="как дела")]
        memory = FakeMemory(window=window, rag="<context>фон</context>")
        service = _make_service(memory=memory, db=d)
        msg = _message(text="нахуй это всё бесит")
        blocks = await service._build_user_content(CHAT_ID, msg, "вася")
        kinds = [_block_tag(b) for b in blocks]
        expected = ["<UserResolutionMap>", "<RAG_Memory>", "<Global_Context>",
                    "<Conversation_Thread>", "<Target_User>",
                    "<protected_facts>", "<mood>", "<Current_Question>",
                    "<style_anchors>"]
        positions = [kinds.index(k) for k in expected]
        assert positions == sorted(positions)       # строгий порядок «важное к концу»
        assert blocks[-1].startswith("отвечай коротко, по делу")
        assert kinds[-2] == "<style_anchors>"       # anchors перед sandwich
        await d.close()

    @pytest.mark.asyncio
    async def test_xml_escape_applied(self, fake_time):
        window = [_window_row(text="1 < 2 & 3")]
        memory = FakeMemory(window=window)
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        assert "старое имя [10]: 1 &lt; 2 &amp; 3" in global_block
        assert "1 < 2" not in global_block

    @pytest.mark.asyncio
    async def test_empty_rag_section_omitted(self, fake_time):
        memory = FakeMemory(window=[_window_row()], rag="")
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert all("<RAG_Memory>" not in b for b in blocks)

    @pytest.mark.asyncio
    async def test_global_context_truncated_with_warning(self, fake_time, caplog):
        """Раунд 8 (D2/T-799): потолок <Global_Context> — keep-head с
        importance-удержанием: под давлением первыми жертвуются шумные строки
        со стороны начала (старое), метка-строка объёма держится; WARNING."""
        from config.settings import settings

        window = [_window_row(text="х" * settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS + "!"),
                  _window_row(text="конец")]
        memory = FakeMemory(window=window)
        service = _make_service(memory=memory)
        with caplog.at_level(logging.WARNING):
            blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        assert body.startswith("фон: дословно последние 2 сообщений")  # D5-метка
        assert "конец" in body                       # свежайшая строка держится
        assert body.count("х") < settings.CHAT_GLOBAL_CONTEXT_MAX_CHARS  # шум выпал
        assert any("global context truncated" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_thread_renders_top_down_with_bot_reply(self, fake_time):
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="ты кто?", reply_to_id=50,
            timestamp=100, media_type="text", author_name="вася", message_id=100)
        service = _make_service(db=d)
        await service.remember_bot_reply(CHAT_ID, 50, "я твой кошмар")
        blocks = await service._build_user_content(CHAT_ID, _message(text="ты кто?"), "вася")
        thread = next(b for b in blocks if b.startswith("<Conversation_Thread>"))
        # C1/T-792: бот-строка «{имя} [bot]: {текст}», юзер — «{имя} [{uid}]: …»
        assert thread.index("test_bot [bot]: я твой кошмар") < \
            thread.index("вася [10]: ты кто?")
        await d.close()

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
        assert thread.count("вася [10]: сообщение") == settings.CHAT_THREAD_MAX_DEPTH
        assert "сообщение 91" not in thread       # глубина 6, дальше — стоп

    @pytest.mark.asyncio
    async def test_thread_break_on_missing(self, fake_time):
        service = _make_service(db=FakeDB({}))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert all("<Conversation_Thread>" not in b for b in blocks)


class TestRound8RendersAndParticipants:
    """Раунд 8 (C1/C2/C3/C5/T-792…T-796): uid-рендеры строк и Target_User,
    карта по активным участникам (вне окна — в периоде), cap, дискриминатор
    коллизий имён только во внутренних рендерах (NFR-2)."""

    async def _db(self):
        d = DatabaseService(":memory:")
        await d.initialize()
        return d

    @pytest.mark.asyncio
    async def test_target_user_block_with_uid(self, fake_time):
        """C5/T-796: <Target_User>{имя} [{uid}]</Target_User> — uid автора
        запроса; без uid (None/0) — без скобки (§3.0)."""
        service = _make_service(memory=FakeMemory(window=[]))
        blocks = await service._build_user_content(
            CHAT_ID, _message(), "вася", target_user_id=10)
        target = next(b for b in blocks if b.startswith("<Target_User>"))
        assert target == "<Target_User>вася [10]</Target_User>"
        blocks = await service._build_user_content(
            CHAT_ID, _message(), "вася", target_user_id=0)
        target = next(b for b in blocks if b.startswith("<Target_User>"))
        assert target == "<Target_User>вася</Target_User>"

    @pytest.mark.asyncio
    async def test_global_lines_without_uid_for_anonymous(self, fake_time):
        """C1: строка анонима/канала (user_id None) — без скобки [uid]."""
        window = [{"user_id": None, "author_name": "канал",
                   "text": "анонс", "timestamp": 100, "media_type": "text",
                   "reply_to_id": None, "tg_message_id": None},
                  _window_row(user_id=10, author_name="вася",
                              text="спросил")]
        service = _make_service(memory=FakeMemory(window=window))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        assert "канал: анонс" in global_block
        assert "канал [None]" not in global_block and "[None]" not in global_block
        assert "вася [10]: спросил" in global_block

    @pytest.mark.asyncio
    async def test_active_participant_outside_window_in_map(self, fake_time):
        """C2/T-793: участник, молчавший дольше окна, но в пределах периода
        (limits.chat_map_participants_hours) — есть в карте."""
        d = await self._db()
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="привет", reply_to_id=None,
            timestamp=100, media_type="text", author_name="вася", message_id=1)
        await d.save_smart_message(
            user_id=20, chat_id=CHAT_ID, text="давно писал", reply_to_id=None,
            timestamp=50, media_type="text", author_name="петя", message_id=2)
        # окно (FakeMemory) знает только васю — петя вне окна
        window = [_window_row(user_id=10, author_name="вася", text="привет")]
        service = _make_service(db=d, memory=FakeMemory(window=window))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert blocks[0].startswith("<UserResolutionMap>")
        assert "вася — 10" in blocks[0]
        assert "петя — 20" in blocks[0]            # вне окна, но в периоде
        await d.close()

    @pytest.mark.asyncio
    async def test_active_participants_ordered_by_activity(self, fake_time):
        """C2.3: порядок карты — по убыванию активности (cnt DESC, uid ASC)."""
        d = await self._db()
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="1", reply_to_id=None,
            timestamp=100, media_type="text", author_name="вася", message_id=1)
        for i in range(3):
            await d.save_smart_message(
                user_id=20, chat_id=CHAT_ID, text=f"петя {i}", reply_to_id=None,
                timestamp=100 + i, media_type="text", author_name="петя",
                message_id=10 + i)
        window = [_window_row(user_id=10, author_name="вася", text="1")]
        service = _make_service(db=d, memory=FakeMemory(window=window))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert blocks[0].index("петя — 20") < blocks[0].index("вася — 10")
        await d.close()

    @pytest.mark.asyncio
    async def test_map_cap_limits_rows(self, fake_time, monkeypatch):
        """C2: cap limits.chat_map_participants_cap ограничивает карту."""
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_MAP_PARTICIPANTS_CAP=1))
        d = await self._db()
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="привет", reply_to_id=None,
            timestamp=100, media_type="text", author_name="вася", message_id=1)
        await d.save_smart_message(
            user_id=20, chat_id=CHAT_ID, text="привет", reply_to_id=None,
            timestamp=101, media_type="text", author_name="петя", message_id=2)
        window = [_window_row(user_id=10, author_name="вася", text="привет"),
                  _window_row(user_id=20, author_name="петя", text="привет")]
        service = _make_service(db=d, memory=FakeMemory(window=window))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert blocks[0].startswith("<UserResolutionMap>")
        assert blocks[0].count("\n") == 2         # одна строка + теги
        await d.close()

    @pytest.mark.asyncio
    async def test_map_and_render_collision_discriminator(self, fake_time):
        """C3/T-794: два разных uid с одинаковым display → второй (по uid ASC)
        получает суффикс « (#хвост)» в карте и строках; каскад-резолв для
        чистовых путей суффикс НЕ содержит (NFR-2)."""
        window = [
            _window_row(user_id=2, author_name="саша", text="реплика саши"),
            _window_row(user_id=1, author_name="саша", text="другая реплика"),
        ]
        service = _make_service(memory=FakeMemory(window=window))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert blocks[0].startswith("<UserResolutionMap>")
        # суффикс у ВТОРОГО по uid ASC (uid=2); первый — без суффикса
        assert "саша (#2) — 2" in blocks[0]
        assert "саша — 1" in blocks[0]
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        assert "саша (#2) [2]: реплика саши" in global_block
        assert "саша [1]: другая реплика" in global_block
        # чистый путь: каскад resolve НЕ тронут суффиксами
        assert service.aliases.resolve(2, "саша", None) == "саша"
        assert service._resolve_name(
            _user(user_id=2, first_name="Саша", last_name=None)) == "Саша"

    @pytest.mark.asyncio
    async def test_discriminator_does_not_leak_into_clean_renders(self, fake_time):
        """C3/NFR-2: карта и внутренние строки несут суффиксы, но чистые
        пути (карточка/persona/resolve/canon) их не содержат."""
        d = await self._db()
        await d.insert_graph_fact(
            CHAT_ID, "саша любит дроны", "bot_direct_reply", None,
            target_user="Саша")
        service = _make_service(db=d)
        assert service._resolve_name(
            _user(user_id=2, first_name="Саша", last_name=None)) == "Саша"
        card = await service.build_persona_card(CHAT_ID, "Саша")
        assert card is not None
        assert "саша любит дроны" in card
        assert "(#2)" not in card
        await d.close()


class TestRound8CurrentQuestionAndBranch:
    """Раунд 8 (D1/T-798, D4/T-801): блок <Current_Question>, компактный
    <Conversation_Branch> над фоном (без LLM)."""

    @pytest.mark.asyncio
    async def test_current_question_block_and_prefix_strip(self, fake_time):
        service = _make_service(memory=FakeMemory(window=[]))
        msg = _message(text="бот, расскажи про дроны")
        blocks = await service._build_user_content(CHAT_ID, msg, "вася")
        current = next(b for b in blocks if b.startswith("<Current_Question>"))
        assert current == "<Current_Question>\nрасскажи про дроны\n</Current_Question>"
        msg = _message(text="@test_bot: как дела?")
        blocks = await service._build_user_content(CHAT_ID, msg, "вася")
        current = next(b for b in blocks if b.startswith("<Current_Question>"))
        assert "как дела?" in current and "@test_bot" not in current

    @pytest.mark.asyncio
    async def test_current_question_omitted_when_empty(self, fake_time):
        service = _make_service(memory=FakeMemory(window=[]))
        blocks = await service._build_user_content(
            CHAT_ID, _message(text="бот"), "вася")
        # блок отсутствует (sandwich-строка упоминает тег в тексте — не считаем)
        assert all(not b.startswith("<Current_Question>") for b in blocks)
        assert blocks[-1].startswith("отвечай коротко")

    @pytest.mark.asyncio
    async def test_current_question_cap_and_escape(self, fake_time, monkeypatch):
        service = _make_service(memory=FakeMemory(window=[]))
        # escape в блоке (полный текст, дефолтный кап)
        msg = _message(text="расскажи про <дроны> и & роботов")
        blocks = await service._build_user_content(CHAT_ID, msg, "вася")
        current = next(b for b in blocks if b.startswith("<Current_Question>"))
        assert "&lt;дроны&gt;" in current and "&amp;" in current
        assert "расскажи про <дроны>" not in current
        # кап по символам ДО escape
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_CURRENT_QUESTION_MAX_CHARS=10))
        msg = _message(text="бот, очень длинный вопрос про дроны и всё такое")
        blocks = await service._build_user_content(CHAT_ID, msg, "вася")
        current = next(b for b in blocks if b.startswith("<Current_Question>"))
        inner = current[len("<Current_Question>\n"):-len("\n</Current_Question>")]
        assert len(inner) == 10 and inner == "очень длин"

    @pytest.mark.asyncio
    async def test_current_question_before_anchors_after_mood(self, fake_time):
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.upsert_bot_reply(CHAT_ID, 1, "норм отвечаю", 1000.0)
        service = _make_service(db=d)
        msg = _message(text="нахуй это всё, расскажи про дроны")
        blocks = await service._build_user_content(CHAT_ID, msg, "вася")
        kinds = [_block_tag(b) for b in blocks]
        assert kinds.index("<Current_Question>") < kinds.index("<style_anchors>")
        assert kinds.index("<mood>") < kinds.index("<Current_Question>")
        await d.close()

    async def _reply_chain_db(self):
        d = DatabaseService(":memory:")
        await d.initialize()
        # 40 (вася, старый вопрос) ← бот-ответ 50 ← 100 (петя, текущий)
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="а что там с дронами?",
            reply_to_id=None, timestamp=100, media_type="text",
            author_name="вася", message_id=40)
        await d.save_smart_message(
            user_id=20, chat_id=CHAT_ID, text="вот теперь про дроны",
            reply_to_id=50, timestamp=300, media_type="text",
            author_name="петя", message_id=100)
        service = _make_service(db=d)
        await service.remember_bot_reply(
            CHAT_ID, 50, "дроны летят нормально",
            parent_tg_message_id=40)
        return d

    @pytest.mark.asyncio
    async def test_branch_block_rendered_for_reply_chain(self, fake_time):
        d = await self._reply_chain_db()
        service = _make_service(db=d)
        msg = _message(message_id=100, text="вот теперь про дроны")
        msg.reply_to_message = MagicMock()          # reply-триггер
        blocks = await service._build_user_content(CHAT_ID, msg, "петя")
        kinds = [_block_tag(b) for b in blocks]
        assert "<Conversation_Branch>" in kinds
        # позиция: сразу после map (над RAG/фоном); полный Thread ниже
        assert kinds[0] == "<UserResolutionMap>"
        assert kinds[1] == "<Conversation_Branch>"
        assert kinds.index("<Conversation_Branch>") < \
            kinds.index("<Conversation_Thread>")
        branch = next(b for b in blocks
                      if b.startswith("<Conversation_Branch>"))
        assert "вася [10]: а что там с дронами?" in branch
        assert "test_bot [bot]: дроны летят нормально" in branch
        assert "петя [20]: вот теперь про дроны" in branch
        await d.close()

    @pytest.mark.asyncio
    async def test_no_branch_for_plain_message(self, fake_time):
        d = await self._reply_chain_db()
        service = _make_service(db=d)
        msg = _message(message_id=100, text="вот теперь про дроны")
        # без reply_to_message — обычное сообщение
        blocks = await service._build_user_content(CHAT_ID, msg, "петя")
        assert all("<Conversation_Branch>" not in b for b in blocks)
        # полный Thread рендерится как обычно
        assert any("<Conversation_Thread>" in b for b in blocks)
        await d.close()

    @pytest.mark.asyncio
    async def test_branch_capped_by_hops(self, fake_time, monkeypatch):
        """D4: <Conversation_Branch> — последние limits.chat_branch_context_hops
        ходов цепочки."""
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_BRANCH_CONTEXT_HOPS=1))
        d = await self._reply_chain_db()
        service = _make_service(db=d)
        msg = _message(message_id=100, text="вот теперь про дроны")
        msg.reply_to_message = MagicMock()
        blocks = await service._build_user_content(CHAT_ID, msg, "петя")
        branch = next(b for b in blocks
                      if b.startswith("<Conversation_Branch>"))
        assert "петя [20]: вот теперь про дроны" in branch
        assert "вася [10]" not in branch and "test_bot" not in branch
        await d.close()


class TestRound8ThreadThroughBot:
    """Раунд 8 (D3/T-800): Conversation_Thread НЕ рвётся на бот-сообщениях —
    цепочка идёт сквозь bot_reply_parents; обрыв только терминальный."""

    async def _full_chain_db(self):
        d = DatabaseService(":memory:")
        await d.initialize()
        # 30(вася) → бот40(parent 30) → 50(петя) → бот60(parent 50) → 70(юзер)
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="ты кто?", reply_to_id=None,
            timestamp=100, media_type="text", author_name="вася", message_id=30)
        await d.save_smart_message(
            user_id=20, chat_id=CHAT_ID, text="а почему так?",
            reply_to_id=40, timestamp=200, media_type="text",
            author_name="петя", message_id=50)
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="вот это новости",
            reply_to_id=60, timestamp=300, media_type="text",
            author_name="вася", message_id=70)
        service = _make_service(db=d)
        await service.remember_bot_reply(
            CHAT_ID, 40, "я твой кошмар", parent_tg_message_id=30)
        await service.remember_bot_reply(
            CHAT_ID, 60, "потому что так надо", parent_tg_message_id=50)
        return d

    @pytest.mark.asyncio
    async def test_thread_full_chain_through_bot_replies(self, fake_time):
        """юзер→бот→юзер→бот — полная цепочка (без обрыва на боте)."""
        d = await self._full_chain_db()
        service = _make_service(db=d)
        blocks = await service._build_user_content(
            CHAT_ID, _message(message_id=70, text="вот это новости"), "вася")
        thread = next(b for b in blocks if b.startswith("<Conversation_Thread>"))
        assert thread.index("вася [10]: ты кто?") < \
            thread.index("test_bot [bot]: я твой кошмар")
        assert thread.index("test_bot [bot]: я твой кошмар") < \
            thread.index("петя [20]: а почему так?")
        assert thread.index("петя [20]: а почему так?") < \
            thread.index("test_bot [bot]: потому что так надо")
        assert thread.index("test_bot [bot]: потому что так надо") < \
            thread.index("вася [10]: вот это новости")
        assert thread.count("[bot]:") == 2
        await d.close()

    @pytest.mark.asyncio
    async def test_thread_breaks_without_parent_link(self, fake_time):
        """D3/Edge-case 4: бот-ответ без parent-линка (легаси) — цепочка
        обрывается на боте ровно как раньше (обратная совместимость)."""
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="ты кто?", reply_to_id=None,
            timestamp=100, media_type="text", author_name="вася", message_id=30)
        await d.save_smart_message(
            user_id=20, chat_id=CHAT_ID, text="а почему так?",
            reply_to_id=40, timestamp=200, media_type="text",
            author_name="петя", message_id=50)
        service = _make_service(db=d)
        await service.remember_bot_reply(CHAT_ID, 40, "я твой кошмар")
        blocks = await service._build_user_content(
            CHAT_ID, _message(message_id=50, text="а почему так?"), "петя")
        thread = next(b for b in blocks if b.startswith("<Conversation_Thread>"))
        assert "test_bot [bot]: я твой кошмар" in thread
        assert "вася [10]: ты кто?" not in thread    # parent нет — стоп на боте
        await d.close()

    @pytest.mark.asyncio
    async def test_thread_break_after_ttl_expiry(self, fake_time):
        """D3: протухшие записи бота (TTL 3600) — терминальный обрыв на
        бот-сообщении (как если бы parent/текста не было)."""
        d = await self._full_chain_db()
        fake_time["now"] += 4000.0                   # > TTL 3600
        service = _make_service(db=d)
        blocks = await service._build_user_content(
            CHAT_ID, _message(message_id=70, text="вот это новости"), "вася")
        thread = next(b for b in blocks if b.startswith("<Conversation_Thread>"))
        assert "вася [10]: вот это новости" in thread   # текущее сообщение
        assert "ты кто?" not in thread
        assert "я твой кошмар" not in thread            # протухло по TTL
        await d.close()

    @pytest.mark.asyncio
    async def test_handle_records_bot_reply_parent(self, fake_time):
        """D3/T-800: handle() пишет parent-линк «бот-ответ → сообщение, на
        которое отвечал» — цепочка продолжается через бот на следующем ходу."""
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.save_smart_message(
            user_id=10, chat_id=CHAT_ID, text="первый вопрос",
            reply_to_id=None, timestamp=100, media_type="text",
            author_name="вася", message_id=77)
        service = _make_service(db=d, memory=FakeMemory(window=[]))
        await service.handle(
            _bot(), _message(message_id=77, text="первый вопрос"), _user())
        assert await service._bot_reply_parent(CHAT_ID, 999) == 77
        await d.close()


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
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        bot = _bot()
        msg = _message(message_id=77)
        await service.handle(bot, msg, msg.from_user)
        assert await service.get_bot_reply(CHAT_ID, 999) == "всё по делу, иди нахуй"
        await d.close()

    @pytest.mark.asyncio
    async def test_empty_answer_silence_with_moai(self, fake_time, monkeypatch, caplog):
        """65.1 (T-469): пустой ответ модели → МОЛЧАНИЕ (без заглушки/ошибки
        пустого текста) + реакция 🗿; memorize НЕ вызывается."""
        tasks = []

        def sync_fire_and_forget(coro, tag):
            tasks.append(coro)

        monkeypatch.setattr("services.direct_chat_service.fire_and_forget",
                            sync_fire_and_forget)
        d = DatabaseService(":memory:")
        await d.initialize()
        memory = FakeMemory(window=[])
        service = _make_service(memory=memory, db=d, llm=FakeLLM(text="   "))
        bot = _bot()
        msg = _message(message_id=77)
        with caplog.at_level(logging.WARNING):
            await service.handle(bot, msg, msg.from_user)
        bot.send_message.assert_not_called()          # молчание гарантировано
        bot.set_message_reaction.assert_awaited_once()
        reaction_call = bot.set_message_reaction.await_args
        assert reaction_call.args[:2] == (CHAT_ID, 77)
        reactions = reaction_call.kwargs["reaction"]
        assert len(reactions) == 1 and reactions[0].emoji == "🗿"
        assert any("empty answer" in r.message for r in caplog.records)
        assert tasks == []                            # memorize не запланирован
        assert not memory.memorized
        assert await service.get_bot_reply(CHAT_ID, 999) is None
        await d.close()

    @pytest.mark.asyncio
    async def test_bad_response_silence_with_moai(self, fake_time, caplog):
        """65.1: LLMBadResponseError (модель жива, ответила пустым) → молчание
        + 🗿; R13-фраза НЕ отправляется (это НЕ сбой LLM)."""
        llm = FakeLLM(error=LLMBadResponseError("chat/completions: empty content"))
        service = _make_service(llm=llm)
        bot = _bot()
        msg = _message(message_id=88)
        with caplog.at_level(logging.WARNING):
            await service.handle(bot, msg, msg.from_user)
        bot.send_message.assert_not_called()
        bot.set_message_reaction.assert_awaited_once()
        assert any("empty answer" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_temperature_from_user_prefs(self, fake_time):
        """65.8 (T-476): пресет юзера из user_prefs попадает в generate."""
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.set_user_tone_preset(CHAT_ID, 10, "chatty")
        llm = FakeLLM()
        service = _make_service(db=d, llm=llm)
        await service.handle(_bot(), _message(), _user())
        assert llm.temperature == settings.CHAT_TEMPERATURE_CHATTY
        await d.close()

    @pytest.mark.asyncio
    async def test_temperature_default_preset(self, fake_time):
        """65.8: нет пресета в user_prefs → дефолт-пресет (balanced)."""
        llm = FakeLLM()
        service = _make_service(db=FakeDB(), llm=llm)
        await service.handle(_bot(), _message(), _user())
        assert llm.temperature == settings.CHAT_TEMPERATURE_BALANCED

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


def _cfg(**overrides):
    """Копия frozen-Settings с переопределениями (65.x-выключатели в тестах)."""
    return dataclasses.replace(settings, **overrides)


class TestSilenceAfterCooldowns:
    """65.3 (T-471): стачка кулдаунов подряд (throttle_state scope=
    'direct_silence') → при CHAT_SILENCE_AFTER_COOLDOWNS — молчание без фразы;
    успешный допуск сбрасывает стачку."""

    async def _make(self, path):
        d = DatabaseService(str(path))
        await d.initialize()
        service = _make_service(
            db=d, llm=FakeLLM(),
            throttle=PersistentThrottle(1, 300.0, "direct_chat", d))
        return d, service

    async def _streak(self, d, chat_id, user_id):
        cursor = await d.db.execute(
            "SELECT burst_left FROM throttle_state "
            "WHERE scope='direct_silence' AND chat_id=? AND user_id=?",
            (chat_id, user_id))
        row = await cursor.fetchone()
        return None if row is None else row["burst_left"]

    @pytest.mark.asyncio
    async def test_silence_after_five_cooldowns(self, tmp_path, fake_wall, caplog):
        """1 успех → 4 кулдаун-фразы (стачка 1..4) → 5-й кулдаун — МОЛЧАНИЕ
        (без фразы R50-7), счётчик в БД."""
        d, service = await self._make(tmp_path / "silence.db")
        bot = _bot()
        for i in range(1, 7):
            await service.handle(bot, _message(message_id=i), _user())
        assert service.llm.call_count == 1
        assert bot.send_message.await_count == 5     # 1 ответ + 4 кулдаун-фразы
        assert await self._streak(d, CHAT_ID, 10) == 5
        with caplog.at_level(logging.WARNING):
            await service.handle(bot, _message(message_id=99), _user())
        assert bot.send_message.await_count == 5     # 6-й кулдаун — молчание
        assert any("silent after" in r.message for r in caplog.records)
        await d.close()

    @pytest.mark.asyncio
    async def test_success_resets_streak(self, tmp_path, fake_wall):
        d, service = await self._make(tmp_path / "reset.db")
        bot = _bot()
        for i in range(1, 7):
            await service.handle(bot, _message(message_id=i), _user())
        assert await self._streak(d, CHAT_ID, 10) == 5
        fake_wall["now"] += 301.0                  # кулдаун истёк → допуск
        await service.handle(bot, _message(message_id=7), _user())
        assert service.llm.call_count == 2         # успех — LLM вызван
        assert await self._streak(d, CHAT_ID, 10) is None   # стачка сброшена
        await d.close()

    @pytest.mark.asyncio
    async def test_silence_disabled_old_behavior(self, tmp_path, fake_wall, monkeypatch):
        """65.3: CHAT_SILENCE_ENABLED=false → стачка не считается — фраза
        R50-7 приходит на КАЖДЫЙ кулдаун (ровно старое поведение)."""
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_SILENCE_ENABLED=False))
        d, service = await self._make(tmp_path / "off.db")
        bot = _bot()
        for i in range(1, 8):
            await service.handle(bot, _message(message_id=i), _user())
        assert bot.send_message.await_count == 7   # 1 ответ + 6 фраз
        assert await self._streak(d, CHAT_ID, 10) is None
        await d.close()

    @pytest.mark.asyncio
    async def test_streak_lazy_reset_after_cooldown(self, tmp_path, fake_wall):
        """65.3: bump обнуляет стачку, если last_ts (последний кулдаун) старше
        CHAT_COOLDOWN_SECONDS («кулдауны уже не подряд»); reset — полный сброс."""
        d = DatabaseService(str(tmp_path / "lazy.db"))
        await d.initialize()
        streak = SilenceStreak(300.0, d)
        assert await streak.bump(CHAT_ID, 10) == 1
        fake_wall["now"] += 150.0
        assert await streak.bump(CHAT_ID, 10) == 2
        fake_wall["now"] += 301.0                 # > 300 от последнего кулдауна
        assert await streak.bump(CHAT_ID, 10) == 1
        await streak.reset(CHAT_ID, 10)
        assert await streak.bump(CHAT_ID, 10) == 1
        await d.close()


class TestStyleAnchorsAndMood:
    """65.4/65.9/65.10 (T-472/T-477/T-478): секции <style_anchors>/<mood>/
    <protected_facts> в user-контенте; R50-4 (системный промпт) не тронут."""

    @pytest.mark.asyncio
    async def test_style_anchors_section(self, fake_time):
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        replies = ["норм отвечаю", "сцуко, ну держи", "да блин, всё пучком",
                   "короче, работает"]
        for i, text in enumerate(replies):
            await service.remember_bot_reply(CHAT_ID, i, text)
            fake_time["now"] += 1.0
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        anchors = next(b for b in blocks if b.startswith("<style_anchors>"))
        # Раунд 3 (3.7/C1): новый текст инструкции (эталон байт-в-байт)
        assert ("подражай общей интонации этих ответов, но НЕ копируй "
                "дословно и не начинай каждый ответ с одного и того же "
                "слова:" in anchors)
        assert "1. сцуко, ну держи" in anchors and "3. короче, работает" in anchors
        assert "норм отвечаю" not in anchors      # последние 3 (default count)
        await d.close()

    @pytest.mark.asyncio
    async def test_style_anchor_truncated(self, fake_time, monkeypatch):
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_STYLE_ANCHOR_MAX_CHARS=4))
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        await service.remember_bot_reply(CHAT_ID, 1, "длинный ответ бота")
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        anchors = next(b for b in blocks if b.startswith("<style_anchors>"))
        assert "1. длин" in anchors and "длинный ответ бота" not in anchors
        await d.close()

    @pytest.mark.asyncio
    async def test_style_anchors_disabled(self, fake_time, monkeypatch):
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_STYLE_ANCHORS_ENABLED=False))
        service = _make_service(db=FakeDB())
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert all("<style_anchors>" not in b for b in blocks)

    # ── Раунд 3 (3.7/C1, T-696): анти-залипание style_anchors ──

    def test_normalize_first_word(self):
        service = _make_service()
        norm = service._normalize_first_word
        assert norm("Сцуко, бля!") == "сцуко"
        assert norm("  Давай норм") == "давай"
        assert norm("а ну-ка") == ""              # < _STICKY_MIN_WORD_LEN
        assert norm("«сука» в начале") == ""      # пунктуация-префикс не слово
        assert norm("") == ""

    def test_detect_sticky_prefixes(self):
        window = ["сцуко, ну держи", "сцуко, вот опять", "норм отвечаю",
                  "сцуко, хватит", "да норм"]
        sticky = DirectChatService._detect_sticky(window)
        assert sticky == {"сцуко"}
        # единичный префикс — НЕ залипший
        assert DirectChatService._detect_sticky(
            ["сцуко, раз", "норм два", "так три", "ну четыре", "да пять"]
        ) == set()

    @pytest.mark.asyncio
    async def test_style_anchors_sticky_replies_excluded(self, fake_time,
                                                         monkeypatch):
        """AC-C1: >=2 из последних count начинаются с одного слова («сцуко») →
        такие ответы исключаются; в якоря попадают старые различные."""
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_STYLE_ANCHORS_COUNT=3, CHAT_STYLE_ANCHOR_MAX_CHARS=400))
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        replies = ["норм, первое дело", "сцуко, раз", "сцуко, два",
                   "сцуко, три", "да норм, свежее"]
        for i, text in enumerate(replies):
            await service.remember_bot_reply(CHAT_ID, i, text)
            fake_time["now"] += 1.0
        anchors = await service._build_style_anchors(CHAT_ID)
        # «сцуко»-ответы (2 из последних 3) исключены; остаются различные
        assert "сцуко" not in anchors
        assert "да норм, свежее" in anchors
        assert "норм, первое дело" in anchors
        assert anchors.startswith("<style_anchors>")

    @pytest.mark.asyncio
    async def test_style_anchors_all_sticky_empty_section(self, fake_time,
                                                          monkeypatch):
        """AC-C1: ВСЕ последние ответы залипли одним словом (count=3) →
        секция не строится (безопаснее, чем модель-«попугай»)."""
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_STYLE_ANCHORS_COUNT=3))
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        for i in range(5):
            await service.remember_bot_reply(CHAT_ID, i, f"сцуко, ответ {i}")
            fake_time["now"] += 1.0
        assert await service._build_style_anchors(CHAT_ID) == ""
        await d.close()

    @pytest.mark.asyncio
    async def test_style_anchors_single_prefix_not_excluded(self, fake_time,
                                                            monkeypatch):
        """AC-C1 edge: префикс встретился 1 раз из count — НЕ «запрет мата»,
        ответ остаётся в якорях (только де-залипание)."""
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_STYLE_ANCHORS_COUNT=3))
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        replies = ["сцуко, редкий гость", "норм отвечаю", "да ладно тебе"]
        for i, text in enumerate(replies):
            await service.remember_bot_reply(CHAT_ID, i, text)
            fake_time["now"] += 1.0
        anchors = await service._build_style_anchors(CHAT_ID)
        assert "сцуко, редкий гость" in anchors
        await d.close()

    def test_mood_block_negative(self):
        service = _make_service()
        block = service._build_mood_block("ты бля сука заебал")
        assert block == ("<mood>собеседник звучит зло, "
                         "подстрой тон под это, но не переигрывай</mood>")

    def test_mood_block_positive(self):
        service = _make_service()
        assert "радостно" in service._build_mood_block("спасибо красава")

    def test_mood_block_neutral(self):
        service = _make_service()
        assert service._build_mood_block("расскажи про дроны") == ""

    @pytest.mark.asyncio
    async def test_mood_block_in_user_content(self, fake_time):
        service = _make_service()
        blocks = await service._build_user_content(
            CHAT_ID, _message(text="нахуй это всё бесит"), "вася")
        assert any(b.startswith("<mood>") for b in blocks)

    @pytest.mark.asyncio
    async def test_mood_disabled(self, fake_time, monkeypatch):
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_MOOD_ENABLED=False))
        service = _make_service()
        blocks = await service._build_user_content(
            CHAT_ID, _message(text="нахуй это всё бесит"), "вася")
        assert all("<mood>" not in b for b in blocks)

    @pytest.mark.asyncio
    async def test_protected_facts_block(self, fake_time):
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (?, ?, ?, ?)",
            (CHAT_ID, "вася", "день рождения 5 мая", 1.0))
        await d.db.commit()
        service = _make_service(db=d)
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        protected = next(b for b in blocks if b.startswith("<protected_facts>"))
        assert "день рождения 5 мая" in protected
        # чужой юзер → секции нет
        blocks_other = await service._build_user_content(CHAT_ID, _message(), "петя")
        assert all("<protected_facts>" not in b for b in blocks_other)
        await d.close()

    @pytest.mark.asyncio
    async def test_chat_level_fact_visible_to_everyone(self, fake_time):
        """Раунд 5 (T-732): чат-уровневый protected-факт (user_name NULL —
        лор чата) виден ВСЕМ юзерам чата в <protected_facts>."""
        d = DatabaseService(":memory:")
        await d.initialize()
        await d.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (?, NULL, 'конфа пермская, из джаббера', 1.0)",
            (CHAT_ID,))
        await d.db.commit()
        service = _make_service(db=d)
        for name in ("вася", "петя"):
            blocks = await service._build_user_content(
                CHAT_ID, _message(), name)
            protected = next(b for b in blocks
                             if b.startswith("<protected_facts>"))
            assert "конфа пермская, из джаббера" in protected
        # user-факты других юзеров по-прежнему не видны (include False-путь)
        blocks_other = await service._build_user_content(
            CHAT_ID, _message(), "вася")
        assert any(b.startswith("<protected_facts>") for b in blocks_other)
        await d.close()


class TestForgetAndClear:
    """65.5/65.10 (T-478): /forget — FTS-удаление конкретных фактов юзера,
    protected_facts НЕ трогаются, журнал graph_fact_compressions; /clear —
    bot_replies чата + bot_direct_reply-факты юзера, chat_history живёт."""

    @pytest.mark.asyncio
    async def test_forget_removes_matching_direct_facts(self, tmp_path):
        d = DatabaseService(str(tmp_path / "forget.db"))
        await d.initialize()
        await d.insert_graph_fact(
            CHAT_ID, "вася любит дроны", "bot_direct_reply", None, target_user="вася")
        await d.insert_graph_fact(
            CHAT_ID, "вася любит пиво", "bot_direct_reply", None, target_user="вася")
        await d.insert_graph_fact(
            CHAT_ID, "петя любит дроны", "bot_direct_reply", None, target_user="петя")
        removed = await d.forget_direct_facts(CHAT_ID, "вася", "дроны", int(time.time()))
        assert removed == 1
        cursor = await d.db.execute("SELECT fact FROM graph_facts WHERE chat_id = ?", (CHAT_ID,))
        facts = [row["fact"] for row in await cursor.fetchall()]
        assert "вася любит дроны" not in facts
        assert "вася любит пиво" in facts
        assert "петя любит дроны" in facts
        cursor = await d.db.execute(
            "SELECT reason, fact_before, fact_after FROM graph_fact_compressions")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["reason"] == "forget"
        assert rows[0]["fact_before"] == "вася любит дроны"
        assert rows[0]["fact_after"] is None
        await d.close()

    @pytest.mark.asyncio
    async def test_forget_skips_protected_facts(self, tmp_path):
        d = DatabaseService(str(tmp_path / "protected.db"))
        await d.initialize()
        await d.insert_graph_fact(
            CHAT_ID, "вася любит дроны", "bot_direct_reply", None, target_user="вася")
        await d.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (?, ?, ?, ?)",
            (CHAT_ID, "вася", "вася любит дроны", 1.0))
        await d.db.commit()
        removed = await d.forget_direct_facts(CHAT_ID, "вася", "дроны", int(time.time()))
        assert removed == 0                            # защищённый факт НЕ удалён
        cursor = await d.db.execute("SELECT fact FROM graph_facts WHERE chat_id = ?", (CHAT_ID,))
        facts = [row["fact"] for row in await cursor.fetchall()]
        assert "вася любит дроны" in facts
        await d.close()

    @pytest.mark.asyncio
    async def test_forget_empty_phrase_returns_zero(self, tmp_path):
        d = DatabaseService(str(tmp_path / "empty.db"))
        await d.initialize()
        assert await d.forget_direct_facts(CHAT_ID, "вася", "  ", int(time.time())) == 0
        await d.close()

    @pytest.mark.asyncio
    async def test_forget_fts_failure_fail_open(self, tmp_path, monkeypatch, caplog):
        """T-502: падение FTS MATCH (битый индекс) → WARNING + возврат 0
        (fail-open); факты не тронуты, хендлер не роняется."""
        import sqlite3

        d = DatabaseService(str(tmp_path / "forget_broken.db"))
        await d.initialize()
        await d.insert_graph_fact(
            CHAT_ID, "вася любит дроны", "bot_direct_reply", None,
            target_user="вася")
        original = d.db.execute

        async def broken_match(query, params=None):
            if "MATCH" in str(query):
                raise sqlite3.OperationalError(
                    "database disk image is malformed")
            return await original(query, params)

        monkeypatch.setattr(d.db, "execute", broken_match)
        with caplog.at_level(logging.WARNING):
            removed = await d.forget_direct_facts(
                CHAT_ID, "вася", "дроны", int(time.time()))
        assert removed == 0
        assert any("/forget FTS search failed" in r.message
                   for r in caplog.records)
        cursor = await original(
            "SELECT fact FROM graph_facts WHERE chat_id = ?", (CHAT_ID,))
        facts = [row["fact"] for row in await cursor.fetchall()]
        assert facts == ["вася любит дроны"]      # fail-open: ничего не удалено
        await d.close()

    @pytest.mark.asyncio
    async def test_clear_direct_dialogue(self, tmp_path):
        d = DatabaseService(str(tmp_path / "clear.db"))
        await d.initialize()
        await d.insert_graph_fact(
            CHAT_ID, "вася любит дроны", "bot_direct_reply", None, target_user="вася")
        await d.insert_graph_fact(
            CHAT_ID, "петя любит дроны", "bot_direct_reply", None, target_user="петя")
        await d.insert_graph_fact(CHAT_ID, "фон чата", "chat_history", None)
        await d.upsert_bot_reply(CHAT_ID, 1, "ответ", time.time())
        removed = await d.clear_direct_dialogue(CHAT_ID, "вася")
        assert removed == 1
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM bot_replies WHERE chat_id = ?", (CHAT_ID,))
        assert (await cursor.fetchone())["c"] == 0       # цепочки чата стёрты
        cursor = await d.db.execute("SELECT fact FROM graph_facts WHERE chat_id = ?", (CHAT_ID,))
        facts = [row["fact"] for row in await cursor.fetchall()]
        assert "вася любит дроны" not in facts           # факт юзера удалён
        assert "петя любит дроны" in facts               # чужой факт живёт
        assert "фон чата" in facts                       # chat_history не тронут
        await d.close()


class TestBotRepliesLru:
    """63.6 #6: персистентные bot_replies (TTL 3600 + cap 200) — правка
    in-memory LRU 58.6; get после «рестарта» работает."""

    @pytest.mark.asyncio
    async def test_lru_eviction_and_ttl(self, fake_time):
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        for i in range(5):
            await service.remember_bot_reply(CHAT_ID, i, f"ответ {i}")
        assert await service.get_bot_reply(CHAT_ID, 0) == "ответ 0"
        fake_time["now"] += 3601.0                   # TTL истёк
        assert await service.get_bot_reply(CHAT_ID, 1) is None
        cursor = await d.db.execute(
            "SELECT COUNT(*) AS c FROM bot_replies WHERE chat_id = ? AND tg_message_id = ?",
            (CHAT_ID, 1))
        assert (await cursor.fetchone())["c"] == 0   # ленивый DELETE на чтении
        await d.close()

    @pytest.mark.asyncio
    async def test_evicts_oldest_when_over_limit(self, fake_time):
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        for i in range(300):
            await service.remember_bot_reply(CHAT_ID, i, f"ответ {i}")
            fake_time["now"] += 1.0          # монотонная стена → детерминированный LRU
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM bot_replies")
        assert (await cursor.fetchone())["c"] == 200
        assert await service.get_bot_reply(CHAT_ID, 0) is None     # вытеснен
        assert await service.get_bot_reply(CHAT_ID, 299) == "ответ 299"
        await d.close()

    @pytest.mark.asyncio
    async def test_survives_restart(self, tmp_path):
        """63.6 #6: новый сервис на той же БД видит ответы бота."""
        path = str(tmp_path / "replies.db")
        d1 = DatabaseService(path)
        await d1.initialize()
        service1 = _make_service(db=d1)
        await service1.remember_bot_reply(CHAT_ID, 42, "цепочка жива")
        await d1.close()

        d2 = DatabaseService(path)
        await d2.initialize()
        service2 = _make_service(db=d2)
        assert await service2.get_bot_reply(CHAT_ID, 42) == "цепочка жива"
        await d2.close()

    @pytest.mark.asyncio
    async def test_get_missing_is_none(self, fake_time):
        d = DatabaseService(":memory:")
        await d.initialize()
        service = _make_service(db=d)
        assert await service.get_bot_reply(CHAT_ID, 777) is None
        await d.close()


class RecordingLLM:
    """Считает параллельные вызовы generate: active > 1 = замок нарушен;
    порядок входов фиксируется."""

    def __init__(self, text="ок", delay=0.02):
        self.text = text
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.order = []

    async def generate(self, messages, temperature=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.order.append(len(self.order) + 1)
        await asyncio.sleep(self.delay)
        self.active -= 1
        return self.text


class TestChatLock:
    """63.6 #7 (T-461, R60-2): per-chat замок — генерация сериализована,
    порядок ответов сохранён (FIFO), таймаут → CHAT_LOCK_BUSY_PHRASES
    (прецедент Epic 35 alan_greeting)."""

    @pytest.mark.asyncio
    async def test_parallel_handles_serialized_and_ordered(self, fake_time):
        llm = RecordingLLM()
        service = _make_service(llm=llm, throttle=DirectChatThrottle(10, 300.0))

        async def run(mid):
            await service.handle(_bot(), _message(message_id=mid), _user())

        await asyncio.gather(run(1), run(2), run(3))
        assert llm.max_active == 1          # генерация НЕ параллельна
        assert llm.order == [1, 2, 3]       # FIFO: ответы в порядке обращений

    @pytest.mark.asyncio
    async def test_lock_wait_timeout_sends_busy_phrase(self, fake_time, monkeypatch):
        import config.settings as settings_module
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            settings_module.Settings(CHAT_LOCK_WAIT_SECONDS=0.05))
        gated = GatedLLM(text="пробный ответ")
        service = _make_service(llm=gated, throttle=DirectChatThrottle(10, 300.0))
        bot1, bot2 = _bot(), _bot()

        async def run_first():
            await service.handle(bot1, _message(message_id=1), _user())

        task = asyncio.ensure_future(run_first())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert gated.call_count == 1              # первая генерация висит на gated
        await service.handle(bot2, _message(message_id=2), _user())
        assert bot2.send_message.await_args.args[1] in CHAT_LOCK_BUSY_PHRASES
        assert bot2.send_message.await_args.kwargs["reply_to_message_id"] == 2
        gated.enter.set()
        await task
        assert bot1.send_message.await_args.args[1] == gated.text   # первая не пострадала

    @pytest.mark.asyncio
    async def test_different_chats_not_blocked(self, fake_time):
        gated = GatedLLM(text="думаю")
        service = _make_service(llm=gated, throttle=DirectChatThrottle(10, 300.0))
        other_chat = -999

        async def run_first():
            await service.handle(_bot(), _message(message_id=1), _user())

        async def run_other():
            msg = _message(message_id=5, chat_id=other_chat)
            await service.handle(_bot(), msg, msg.from_user)

        task1 = asyncio.ensure_future(run_first())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert gated.call_count == 1              # первый чат висит в генерации
        task2 = asyncio.ensure_future(run_other())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert gated.call_count == 2              # другой чат НЕ ждал замок первого
        gated.enter.set()
        await asyncio.gather(task1, task2)

    @pytest.mark.asyncio
    async def test_cooldown_not_blocked_by_lock(self, fake_time):
        """63.2: кулдаун-фразы мгновенные — НЕ стоят в очереди за замком."""
        gated = GatedLLM(text="думаю")
        service = _make_service(
            llm=gated, throttle=DirectChatThrottle(2, 300.0))

        async def run_first():
            await service.handle(_bot(), _message(message_id=1), _user())

        async def run_second():
            await service.handle(_bot(), _message(message_id=2), _user())

        task1 = asyncio.ensure_future(run_first())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert gated.call_count == 1
        task2 = asyncio.ensure_future(run_second())   # заряд 2 списан → встаёт на замок
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        bot3 = _bot()
        await service.handle(bot3, _message(message_id=3), _user())   # 3-й — кулдаун сразу
        assert bot3.send_message.await_args.args[1] in [
            p.replace("{remaining_time}", "5 мин") for p in CHAT_COOLDOWN_PHRASES]
        gated.enter.set()
        await asyncio.gather(task1, task2)

    @pytest.mark.asyncio
    async def test_lock_released_after_llm_error(self, fake_time):
        """Замок освобождается и при падении генерации (finally)."""
        llm = FakeLLM(error=LLMError("апи сдохло"))
        service = _make_service(llm=llm, throttle=DirectChatThrottle(10, 300.0))
        await service.handle(_bot(), _message(message_id=1), _user())
        await service.handle(_bot(), _message(message_id=2), _user())
        assert llm.call_count == 2              # второй вызов НЕ завис на замке

    @pytest.mark.asyncio
    async def test_lock_cleanup_when_over_capacity(self, fake_time, monkeypatch):
        """63.2: len > CHAT_LOCK_MAX_ENTRIES → незалоченные без ожидающих
        удаляются (T-501: прямой вызов _get_chat_lock оставляет бронь —
        снимаем её, как это делает боевой handle() после acquire)."""
        import config.settings as settings_module
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            settings_module.Settings(CHAT_LOCK_MAX_ENTRIES=16))
        service = _make_service(throttle=DirectChatThrottle(1000, 300.0))
        for chat in range(20):
            lock = await service._get_chat_lock(chat)
            service._drop_chat_lock_pending(lock)
        assert len(service._chat_locks) <= 16
        lock = await service._get_chat_lock(CHAT_ID)   # свежий — доступен
        service._drop_chat_lock_pending(lock)
        assert not lock.locked()

    @pytest.mark.asyncio
    async def test_eviction_skips_lock_with_pending_waiter(
            self, fake_time, monkeypatch):
        """T-501 регрессия eviction-гонки: корутина X получила лок L чата A
        (вышла из guard, ещё НЕ вошла в acquire — окно гонки), Y чистит
        переполнение — лок с ожидающим НЕ выселяется; повторный
        _get_chat_lock(A) возвращает ТОТ ЖЕ объект (иначе X и Z — два
        владельца одного чата одновременно)."""
        import config.settings as settings_module
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            settings_module.Settings(CHAT_LOCK_MAX_ENTRIES=16))
        service = _make_service(throttle=DirectChatThrottle(1000, 300.0))
        victim = await service._get_chat_lock(CHAT_ID)
        assert not victim.locked()          # X ещё НЕ в acquire (окно гонки)
        for chat in range(20):              # перелив → ленивая чистка под Y
            other = await service._get_chat_lock(chat)
            service._drop_chat_lock_pending(other)
        assert service._chat_locks.get(CHAT_ID) is victim   # не выселен
        again = await service._get_chat_lock(CHAT_ID)
        assert again is victim              # Z получает тот же объект замка


@pytest.fixture
def breaker_time(monkeypatch):
    """Мок time.monotonic в llm_circuit_breaker (CB живёт в своём модуле)."""
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr("services.llm_circuit_breaker.time", FakeTime)
    return state


class TestCircuitBreakerIntegration:
    """Epic 53 (62.3.3, тест-план 62.5 #11-13): CB-обёртка в DirectChatService."""

    @pytest.mark.asyncio
    async def test_cb_open_skips_llm_and_sends_down_phrase(self, fake_time, caplog):
        """62.5 #11: CB OPEN → llm.generate НЕ вызван, фраза из
        CHAT_LLM_DOWN_PHRASES, WARNING «circuit breaker open», reply_to."""
        breaker = LLMCircuitBreaker(failure_threshold=1, cooldown_seconds=300.0)
        breaker.on_failure()                          # OPEN
        llm = FakeLLM()
        service = _make_service(
            llm=llm, breaker=breaker,
            throttle=DirectChatThrottle(10, 300.0),
        )
        bot = _bot()
        msg = _message(message_id=55)
        with caplog.at_level(logging.WARNING):
            await service.handle(bot, msg, msg.from_user)
        assert llm.call_count == 0                    # 0 вызовов LLM
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 55
        assert bot.send_message.await_args.args[1] in CHAT_LLM_DOWN_PHRASES
        assert any("circuit breaker open" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_three_transient_failures_open_fourth_skips_llm(self, fake_time):
        """62.5 #12: 3× LLMServerError → CHAT_ERROR_PHRASES + OPEN; 4-й вызов —
        БЕЗ LLM, CHAT_LLM_DOWN_PHRASES."""
        breaker = LLMCircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)
        llm = FakeLLM(error=LLMServerError(
            "LLM server error 502 after 3 attempts: https://api.test/v1/chat/completions"))
        service = _make_service(
            llm=llm, breaker=breaker,
            throttle=DirectChatThrottle(10, 300.0),
        )
        bot = _bot()
        for i in range(3):
            await service.handle(bot, _message(message_id=i), _user())
            assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES
        assert breaker.state == STATE_OPEN
        assert llm.call_count == 3
        await service.handle(bot, _message(message_id=99), _user())
        assert llm.call_count == 3                    # 4-й — без вызова LLM
        assert bot.send_message.await_args.args[1] in CHAT_LLM_DOWN_PHRASES

    @pytest.mark.asyncio
    async def test_transient_failure_increments_counter(self, fake_time):
        """LLMServerError → CHAT_ERROR_PHRASES (R50-8) + _failures==1."""
        breaker = LLMCircuitBreaker(failure_threshold=3)
        llm = FakeLLM(error=LLMServerError("LLM server error 500 after 3 attempts: u"))
        service = _make_service(llm=llm, breaker=breaker)
        bot = _bot()
        await service.handle(bot, _message(), _user())
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES
        assert breaker._failures == 1
        assert breaker.state == STATE_CLOSED

    @pytest.mark.asyncio
    async def test_auth_error_does_not_increment(self, fake_time):
        """62.5 #13: LLMAuthError → CHAT_ERROR_PHRASES, счётчик НЕ инкрементится."""
        breaker = LLMCircuitBreaker(failure_threshold=3)
        llm = FakeLLM(error=LLMAuthError("LLM auth failed (401): u"))
        service = _make_service(llm=llm, breaker=breaker)
        bot = _bot()
        await service.handle(bot, _message(), _user())
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES
        assert breaker._failures == 0

    @pytest.mark.asyncio
    async def test_success_resets_breaker(self, fake_time):
        """62.5 #13: 2 транзиентных фейла + успех → полный сброс CB."""
        breaker = LLMCircuitBreaker(failure_threshold=3)
        llm = FakeLLM(error=LLMServerError("LLM server error 502 after 3 attempts: u"))
        service = _make_service(llm=llm, breaker=breaker)
        bot = _bot()
        for _ in range(2):
            await service.handle(bot, _message(), _user())
        assert breaker._failures == 2
        llm.error = None                             # апстрим ожил
        await service.handle(bot, _message(), _user())
        assert breaker._failures == 0
        assert breaker.state == STATE_CLOSED

    @pytest.mark.asyncio
    async def test_half_open_non_transient_probe_reopens(self, breaker_time):
        """Отклонение от буквы 62.3.3 (см. отчёт): пробная генерация в
        HALF_OPEN, упавшая НЕ-транзиентно (LLMAuthError), снова открывает CB —
        иначе CB залипает в HALF_OPEN навсегда (пробная уже израсходована)."""
        breaker = LLMCircuitBreaker(failure_threshold=1, cooldown_seconds=300.0)
        llm = FakeLLM(error=LLMServerError("LLM server error 502 after 3 attempts: u"))
        service = _make_service(
            llm=llm, breaker=breaker,
            throttle=DirectChatThrottle(10, 300.0),
        )
        bot = _bot()
        await service.handle(bot, _message(), _user())   # OPEN (threshold=1)
        assert breaker.state == STATE_OPEN
        breaker_time["now"] += 300.0
        llm.error = LLMAuthError("LLM auth failed (401): u")   # проба: апстрим ответил 401
        await service.handle(bot, _message(), _user())
        assert breaker.state == STATE_OPEN              # не залипли в HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_non_llm_error_probe_reopens(self, breaker_time, fake_time):
        """H1: half-open-проба падает НЕ-LLMError (RuntimeError из generate —
        аналог TelegramRetryAfter/ошибки БД в except Exception) → CB снова
        OPEN, а не навсегда HALF_OPEN."""
        breaker = LLMCircuitBreaker(failure_threshold=1, cooldown_seconds=300.0)
        llm = FakeLLM(error=LLMServerError("LLM server error 502 after 3 attempts: u"))
        service = _make_service(
            llm=llm, breaker=breaker,
            throttle=DirectChatThrottle(10, 300.0),
        )
        bot = _bot()
        await service.handle(bot, _message(), _user())   # OPEN (threshold=1)
        assert breaker.state == STATE_OPEN
        breaker_time["now"] += 300.0                     # кулдаун истёк
        llm.error = RuntimeError("внезапно")             # проба: не-LLMError
        await service.handle(bot, _message(), _user())
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES
        assert breaker.state == STATE_OPEN               # не залипли в HALF_OPEN

    @pytest.mark.asyncio
    async def test_timeout_error_increments_counter(self, fake_time):
        """62.3.3: LLMTimeoutError — транзиентный класс → CB._failures==1."""
        breaker = LLMCircuitBreaker(failure_threshold=3)
        llm = FakeLLM(error=LLMTimeoutError(
            "LLM request timed out after 3 attempts: u"))
        service = _make_service(llm=llm, breaker=breaker)
        bot = _bot()
        await service.handle(bot, _message(), _user())
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES
        assert breaker._failures == 1
        assert breaker.state == STATE_CLOSED

    @pytest.mark.asyncio
    async def test_transport_error_increments_counter(self, fake_time):
        """62.3.3: LLMTransportError — транзиентный класс → CB._failures==1."""
        breaker = LLMCircuitBreaker(failure_threshold=3)
        llm = FakeLLM(error=LLMTransportError(
            "LLM transport error after 3 attempts: u"))
        service = _make_service(llm=llm, breaker=breaker)
        bot = _bot()
        await service.handle(bot, _message(), _user())
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES
        assert breaker._failures == 1
        assert breaker.state == STATE_CLOSED

    @pytest.mark.asyncio
    async def test_half_open_concurrent_handles_single_probe(self, breaker_time, fake_time):
        """M2д: два параллельных handle() при истёкшем кулдауне → РОВНО одна
        пробная генерация; вторая получает down-фразу (CB HALF_OPEN)."""
        breaker = LLMCircuitBreaker(failure_threshold=1, cooldown_seconds=300.0)
        llm = FakeLLM(error=LLMServerError("LLM server error 502 after 3 attempts: u"))
        service = _make_service(
            llm=llm, breaker=breaker,
            throttle=DirectChatThrottle(10, 300.0),
        )
        await service.handle(_bot(), _message(), _user())   # OPEN (threshold=1)
        assert breaker.state == STATE_OPEN
        breaker_time["now"] += 300.0                     # кулдаун истёк
        gated = GatedLLM(text="пробный ответ")
        service.llm = gated
        bot1, bot2 = _bot(), _bot()
        async def run(bot, mid):
            await service.handle(bot, _message(message_id=mid), _user())
            return bot

        task = asyncio.ensure_future(
            asyncio.gather(run(bot1, 1), run(bot2, 2)))
        await asyncio.sleep(0)                           # обе задачи начали handle
        await asyncio.sleep(0)                           # дожали до точек блокировки
        # Пробная генерация висит на gated — второй handle должен увидеть
        # HALF_OPEN и отдать down-фразу БЕЗ вызова LLM.
        assert breaker.state == STATE_HALF_OPEN
        assert gated.call_count == 1                     # ровно одна проба
        assert bot2.send_message.await_args.args[1] in CHAT_LLM_DOWN_PHRASES
        gated.enter.set()                                # проба успешна
        await task
        assert breaker.state == STATE_CLOSED             # успех → сброс
        assert gated.call_count == 1

    @pytest.mark.asyncio
    async def test_cb_disabled_by_settings(self, fake_time, monkeypatch):
        """LLM_CB_ENABLED=False → breaker None, поведение как раньше."""
        import config.settings as settings_module
        new_settings = settings_module.Settings(LLM_CB_ENABLED=False)
        monkeypatch.setattr("services.direct_chat_service.settings", new_settings)
        llm = FakeLLM(error=LLMError("апи сдохло"))
        service = _make_service(llm=llm)
        assert service._breaker is None
        bot = _bot()
        await service.handle(bot, _message(), _user())
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES

    @pytest.mark.asyncio
    async def test_throttle_charge_spent_when_cb_open(self, fake_time):
        """62.1 в.5: при CB OPEN заряд троттлинга списывается как обычно."""
        breaker = LLMCircuitBreaker(failure_threshold=1, cooldown_seconds=300.0)
        breaker.on_failure()
        throttle = DirectChatThrottle(1, 300.0)
        service = _make_service(llm=FakeLLM(), breaker=breaker, throttle=throttle)
        bot = _bot()
        await service.handle(bot, _message(), _user())           # OPEN → down-фраза
        assert bot.send_message.await_args.args[1] in CHAT_LLM_DOWN_PHRASES
        assert throttle.allow(CHAT_ID, 10) > 0                   # заряд израсходован


class SummaryDB:
    """FakeDB + бегущий конспект (64.6). Раунд 8 (D5/T-802): строка несёт
    raw_count (метка объёма «фон: конспект из N сообщений…»).
    Раунд 8 (E2/T-804): get_summary_level — уровень 2 (широкий фон), None —
    уровня нет (инжект L2 не выполняется)."""

    def __init__(self, summary=None, level2=None):
        self.summary = summary          # dict | None
        self.level2 = level2            # dict | None (chat_summary_levels)

    async def get_running_summary(self, chat_id, now):
        return self.summary

    async def get_summary_level(self, chat_id, level):
        return self.level2

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        return None


class TestEpic60RunningSummaryContext:
    """Epic 60 (64.6, T-467): <Global_Context> = конспект + дословный хвост
    сообщений с ts > window_end_ts. Раунд 8 (D2/D5/T-799/T-802): голова
    (метка + конспект) держится при обрезке, хвост режется первым; метка
    объёма — первая строка body."""

    @pytest.mark.asyncio
    async def test_global_context_uses_summary_plus_tail(self, fake_time):
        summary = {"summary": "суть окна: спорили про дроны",
                   "window_end_ts": 200, "raw_count": 3}
        window = [
            _window_row(ts=100, text="старое сообщение"),
            _window_row(ts=200, text="последнее покрытое"),
            _window_row(ts=300, text="новое сообщение"),
        ]
        service = _make_service(memory=FakeMemory(window=window),
                                db=SummaryDB(summary))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        # D5: метка summary-режима первой строкой (каноническая форма)
        assert body.split("\n")[0] == \
            "фон: конспект из 3 сообщений, ниже дословно свежий хвост"
        assert "суть окна: спорили про дроны" in body
        assert "новое сообщение" in body
        assert "старое сообщение" not in body
        assert "последнее покрытое" not in body

    @pytest.mark.asyncio
    async def test_summary_kept_when_tail_trimmed(self, fake_time, caplog):
        """D2/T-799: под внутренним давлением первым режется verbatim-хвост
        (после summary), конспект-голова остаётся."""
        summary = {"summary": "суть окна: спорили про дроны",
                   "window_end_ts": 100, "raw_count": 1}
        tail = [f"хвостовая реплика {i} очень длинная чтобы переполнить лимит токенов в блоке фона" * 40
                for i in range(6)]
        window = ([_window_row(ts=50, text="покрытое")] +
                  [_window_row(ts=200 + i, text=t) for i, t in enumerate(tail)])
        service = _make_service(memory=FakeMemory(window=window),
                                db=SummaryDB(summary))
        with caplog.at_level(logging.WARNING):
            blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        assert "фон: конспект из 1 сообщений, ниже дословно свежий хвост" in body
        assert "суть окна: спорили про дроны" in body    # конспект держится
        assert any("global context truncated" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_summary_falls_back_to_recent_window(self, fake_time):
        window = [_window_row(ts=300, text="обычное сообщение")]
        service = _make_service(memory=FakeMemory(window=window),
                                db=SummaryDB(None))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        # D5: verbatim-метка — первая строка
        assert body.split("\n")[0] == "фон: дословно последние 1 сообщений"
        assert "обычное сообщение" in body

    @pytest.mark.asyncio
    async def test_summary_db_error_falls_back(self, fake_time, caplog):
        """Ошибка чтения конспекта → обычный путь (WARNING, не бросает)."""
        import logging

        class BrokenSummaryDB:
            async def get_running_summary(self, chat_id, now):
                raise RuntimeError("бд упала")

            async def get_summary_level(self, chat_id, level):
                return None

            async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
                return None

        window = [_window_row(ts=300, text="обычное сообщение")]
        service = _make_service(memory=FakeMemory(window=window),
                                db=BrokenSummaryDB())
        with caplog.at_level(logging.WARNING):
            blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        assert "обычное сообщение" in global_block
        assert any("running summary read failed" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_level2_injected_first_line_with_l1(self, fake_time):
        """E2/T-804: при наличии L1 и level-2 строка «широкий фон: …» —
        ПЕРВАЯ строка body <Global_Context>, затем метка summary-режима."""
        summary = {"summary": "суть окна: спорили про дроны",
                   "window_end_ts": 200, "raw_count": 3}
        level2 = {"summary": "раньше спорили про ракеты и запуски",
                  "msg_count_highwater": 500}
        window = [
            _window_row(ts=100, text="старое сообщение"),
            _window_row(ts=200, text="последнее покрытое"),
            _window_row(ts=300, text="новое сообщение"),
        ]
        service = _make_service(memory=FakeMemory(window=window),
                                db=SummaryDB(summary, level2))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        lines = body.split("\n")
        assert lines[0] == \
            "широкий фон: раньше спорили про ракеты и запуски"
        assert lines[1] == \
            "фон: конспект из 3 сообщений, ниже дословно свежий хвост"
        assert "суть окна: спорили про дроны" in body
        assert "новое сообщение" in body

    @pytest.mark.asyncio
    async def test_level2_not_injected_without_l1(self, fake_time):
        """E2: level-2 инжектится ТОЛЬКО вместе с L1 (без конспекта — только
        verbatim-фон; широкая строка не выводится)."""
        level2 = {"summary": "широкий фон: раньше спорили про ракеты",
                  "msg_count_highwater": 500}
        window = [_window_row(ts=300, text="обычное сообщение")]
        service = _make_service(memory=FakeMemory(window=window),
                                db=SummaryDB(None, level2))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        assert "широкий фон" not in body
        assert body.split("\n")[0] == "фон: дословно последние 1 сообщений"

    @pytest.mark.asyncio
    async def test_level2_capped_by_max_chars_keep_end(self, fake_time,
                                                       monkeypatch):
        """E2: кап limits.chat_level2_max_chars — обрезание keep-end (свежий
        конец L2 ближе к текущему окну)."""
        import dataclasses as _dc

        mod = _dc.replace(settings, CHAT_LEVEL2_MAX_CHARS=40)
        monkeypatch.setattr("services.direct_chat_service.settings", mod)
        level2_text = "начало-маркер " + "м" * 100 + " конец-маркер"
        summary = {"summary": "суть окна", "window_end_ts": 100, "raw_count": 1}
        level2 = {"summary": level2_text, "msg_count_highwater": 500}
        window = [_window_row(ts=200, text="новое сообщение")]
        service = _make_service(memory=FakeMemory(window=window),
                                db=SummaryDB(summary, level2))
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        assert "конец-маркер" in body.split("\n")[0]   # keep-end: хвост L2
        assert "начало-маркер" not in body              # голова обрезана

    @pytest.mark.asyncio
    async def test_level2_db_error_fail_open_keeps_l1(self, fake_time, caplog):
        """E2/NFR-6: ошибка чтения level-2 → WARNING, конспект L1 как был."""
        import logging

        class L2BrokenDB(SummaryDB):
            async def get_summary_level(self, chat_id, level):
                raise RuntimeError("бд упала")

        summary = {"summary": "суть окна: спорили про дроны",
                   "window_end_ts": 100, "raw_count": 2}
        window = [_window_row(ts=100, text="покрытое"),
                  _window_row(ts=200, text="свежее")]
        service = _make_service(memory=FakeMemory(window=window),
                                db=L2BrokenDB(summary))
        with caplog.at_level(logging.WARNING):
            blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        assert body.startswith("фон: конспект из 2 сообщений")
        assert "суть окна: спорили про дроны" in body
        assert any("level2 read failed" in r.message for r in caplog.records)


class TestRagDirectPipeline:
    """Раунд 8 (F2/T-808, F4/T-810): direct-сборка <RAG_Memory> — словарный
    дедуп фактов против текста <Global_Context>; LLM-реранк вызывается
    ТОЛЬКО при flags.chat_rag_rerank_enabled=True (default off — 0 вызовов),
    ошибка реранка → исходные факты (fail-open)."""

    @pytest.mark.asyncio
    async def test_rag_fact_duplicating_tail_dropped(self, fake_time):
        window = [_window_row(user_id=10, author_name="вася",
                              text="вася купил новый айфон за сто тысяч")]
        rag_facts = [
            ("chat_history", "вася купил новый айфон", None),
            ("search_fact", "про дроны вчера обсуждали", None),
        ]
        memory = FakeMemory(window=window, rag_facts=rag_facts)
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        rag_block = next(b for b in blocks if b.startswith("<RAG_Memory>"))
        assert "купил новый айфон" not in rag_block    # дубль хвоста выпал
        assert "[поиск] про дроны вчера обсуждали" in rag_block

    @pytest.mark.asyncio
    async def test_close_rag_fact_survives_dedup(self, fake_time):
        """Близкий, но не покрытый факт (0.75 < 0.8) остаётся в блоке."""
        window = [_window_row(user_id=10, author_name="вася",
                              text="вася купил новый айфон за сто тысяч")]
        rag_facts = [("chat_history", "вася купил новый айфон и чехол", None)]
        memory = FakeMemory(window=window, rag_facts=rag_facts)
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        rag_block = next(b for b in blocks if b.startswith("<RAG_Memory>"))
        assert "вася купил новый айфон и чехол" in rag_block

    @pytest.mark.asyncio
    async def test_all_rag_deduped_block_omitted(self, fake_time):
        window = [_window_row(user_id=10, author_name="вася",
                              text="вася купил новый айфон за сто тысяч")]
        rag_facts = [("chat_history", "вася купил новый айфон", None)]
        memory = FakeMemory(window=window, rag_facts=rag_facts)
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(CHAT_ID, _message(), "вася")
        assert all("<RAG_Memory>" not in b for b in blocks)

    @pytest.mark.asyncio
    async def test_rerank_off_by_default_zero_calls(self, fake_time):
        memory = FakeMemory(
            window=[_window_row()],
            rag_facts=[("chat_history", "про дроны вчера", None)])
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(
            CHAT_ID, _message(text="дроны"), "вася")
        rag_block = next(b for b in blocks if b.startswith("<RAG_Memory>"))
        assert "про дроны вчера" in rag_block
        assert memory.rerank_calls == []       # флаг off → 0 LLM-вызовов

    @pytest.mark.asyncio
    async def test_rerank_on_calls_memory_filter(self, fake_time, monkeypatch):
        import dataclasses as _dc

        mod = _dc.replace(settings, CHAT_RAG_RERANK_ENABLED=True)
        monkeypatch.setattr("services.direct_chat_service.settings", mod)
        memory = FakeMemory(
            window=[_window_row()],
            rag_facts=[("chat_history", "про дроны вчера", None),
                       ("search_fact", "про дроны в поиске", None)])
        service = _make_service(memory=memory)
        await service._build_user_content(
            CHAT_ID, _message(text="дроны"), "вася")
        assert len(memory.rerank_calls) == 1
        assert memory.rerank_calls[0][0] == "дроны"

    @pytest.mark.asyncio
    async def test_rerank_error_fail_open_keeps_facts(self, fake_time,
                                                      monkeypatch):
        import dataclasses as _dc

        mod = _dc.replace(settings, CHAT_RAG_RERANK_ENABLED=True)
        monkeypatch.setattr("services.direct_chat_service.settings", mod)

        class BoomMemory(FakeMemory):
            async def rerank_rag_facts(self, query, facts):
                raise RuntimeError("llm упал")

        memory = BoomMemory(
            window=[_window_row()],
            rag_facts=[("chat_history", "про дроны вчера", None)])
        service = _make_service(memory=memory)
        blocks = await service._build_user_content(
            CHAT_ID, _message(text="дроны"), "вася")
        rag_block = next(b for b in blocks if b.startswith("<RAG_Memory>"))
        assert "про дроны вчера" in rag_block       # fail-open


class TestPersonaCard:
    """Epic 60 Фаза D (66.9, T-487): карточка человека — агрегация графа
    (прямые факты + связи + защищённые), формат VERBATIM, права доступа."""

    @pytest.fixture
    def db(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        d = DatabaseService(":memory:")
        loop.run_until_complete(d.initialize())
        yield d
        loop.run_until_complete(d.close())
        loop.close()

    def _service(self, db):
        return _make_service(db=db, aliases=AliasResolver('{"10": "вася"}'))

    @pytest.mark.asyncio
    async def test_card_format_verbatim(self, db):
        """66.9: «карточка: {имя}\nзнаю о тебе: {N} фактов, {M} связей\n1. …»."""
        await db.insert_graph_fact(CHAT_ID, "вася любит дроны", "bot_direct_reply",
                                   None, target_user="вася", weight=0.7)
        service = self._service(db)
        card = await service.build_persona_card(CHAT_ID, "Вася")   # алиас → канон
        assert card is not None
        assert card.startswith("карточка: вася")
        assert "знаю о тебе: 1 фактов, 0 связей" in card
        assert "1. вася любит дроны" in card

    @pytest.mark.asyncio
    async def test_card_counts_links_and_protected(self, db):
        a = await db.upsert_node(CHAT_ID, "вася", "user")
        b = await db.upsert_node(CHAT_ID, "ракеты", "topic")
        await db.upsert_edge(a, b, "фанатеет от")
        await db.insert_graph_fact(CHAT_ID, "вася любит дроны", "bot_direct_reply",
                                   None, target_user="вася")
        import time as _time
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (?, 'вася', 'вася живёт в екатеринбурге', ?)",
            (CHAT_ID, _time.time()))
        await db.db.commit()
        service = self._service(db)
        card = await service.build_persona_card(CHAT_ID, "вася")
        assert "знаю о тебе: 2 фактов, 1 связей" in card
        assert "вася живёт в екатеринбурге" in card          # защищённый первым
        assert "вася (фанатеет от) ракеты" in card

    @pytest.mark.asyncio
    async def test_card_empty_returns_none(self, db):
        service = self._service(db)
        assert await service.build_persona_card(CHAT_ID, "петя") is None

    @pytest.mark.asyncio
    async def test_card_db_error_fail_open_empty_phrase(
            self, db, monkeypatch, caplog):
        """T-503: ошибка БД при чтении карточки → build_persona_card = None
        (WARNING, fail-open) → маппинг хендлера 66.9 даёт VERBATIM-фразу
        CHAT_PERSONA_EMPTY_PHRASE с именем."""
        async def broken(chat_id, canon, limit, now):
            raise RuntimeError("бд упала")

        monkeypatch.setattr(db, "get_persona_card", broken)
        service = self._service(db)
        with caplog.at_level(logging.WARNING):
            card = await service.build_persona_card(CHAT_ID, "вася")
        assert card is None
        assert any("persona card read failed" in r.message
                   for r in caplog.records)
        from services.smartmodule_phrases import CHAT_PERSONA_EMPTY_PHRASE
        # хендлер 66.9: card is None → VERBATIM-фраза пустой карточки с именем
        assert (card if card is not None else
                CHAT_PERSONA_EMPTY_PHRASE.replace("{имя}", "вася")) == (
            "в памяти про вася пока пусто, "
            "пусть хоть раз нормально пообщается")

    @pytest.mark.asyncio
    async def test_persona_access_own_foreign_admin(self, db):
        service = self._service(db)
        own = MagicMock()
        own.id = 10
        other = MagicMock()
        other.id = 999
        admin = MagicMock()
        admin.id = settings.ADMIN_USER_ID
        assert service.persona_access(own, "вася") is True       # своя
        assert service.persona_access(other, "вася") is False    # чужая не админом
        assert service.persona_access(admin, "кто угодно") is True   # админ видит всех
        assert service.persona_access(None, "вася") is False

    @pytest.mark.asyncio
    async def test_persona_names_list(self, db):
        await db.insert_graph_fact(CHAT_ID, "вася любит дроны", "bot_direct_reply",
                                   None, target_user="вася")
        service = self._service(db)
        names = await service.list_persona_names(CHAT_ID)
        assert names == [("вася", 1)]


class TestContextBudgets:
    """Epic 60 Фаза D (66.12, T-490): бюджеты контекста direct_chat — доли от
    CHAT_CONTEXT_BUDGET_TOKENS; Target_User неприкосновенен; порядок урезания
    Style_Anchors → Global_Context → Thread → RAG_Memory → Map."""

    def _svc(self):
        return _make_service()

    def test_small_blocks_untouched(self):
        svc = self._svc()
        blocks = [
            ("map", "<UserResolutionMap>\nвася — 10\n</UserResolutionMap>"),
            ("target", "<Target_User>вася</Target_User>"),
            ("global", "<Global_Context>\nкороткий текст\n</Global_Context>"),
        ]
        result = svc._apply_context_budget(blocks)
        assert result == [text for _, text in blocks]

    def test_huge_rag_truncated_to_ratio(self):
        svc = self._svc()
        big = "слово " * 20000                     # сильно больше 15% × 4000
        blocks = [("rag", f"<RAG_Memory>\n{big}\n</RAG_Memory>")]
        result = svc._apply_context_budget(blocks)
        text = result[0]
        from services.token_counter import count_tokens
        limit = int(settings.CHAT_CONTEXT_BUDGET_TOKENS * settings.CHAT_BUDGET_RAG_RATIO)
        assert count_tokens(text) <= limit + 10    # + closing tag
        assert text.startswith("<RAG_Memory>")     # открывающий тег сохранён
        assert text.rstrip().endswith("</RAG_Memory>")

    def test_target_user_never_truncated(self):
        svc = self._svc()
        huge_name = "оченьдлинноебессмысленноемя" * 200
        target = f"<Target_User>{huge_name}</Target_User>"
        blocks = [("target", target), ("global", "<Global_Context>\nх\n</Global_Context>")]
        result = svc._apply_context_budget(blocks)
        assert result[0] == target                 # Target_User цел всегда

    def test_mood_fully_cut_when_target_exceeds_share(self, caplog):
        """T-505: mood_limit <= 0 (Target_User съел всю долю target) → mood
        срезан ПОЛНОСТЬЮ (блока нет в выдаче), Target_User цел."""
        svc = self._svc()
        huge_name = "оченьдлинноебессмысленноемя" * 200
        blocks = [
            ("target", f"<Target_User>{huge_name}</Target_User>"),
            ("mood", "<mood>собеседник звучит зло, подстрой тон</mood>"),
            ("global", "<Global_Context>\nх\n</Global_Context>"),
        ]
        with caplog.at_level(logging.WARNING):
            result = svc._apply_context_budget(blocks)
        assert result[0] == blocks[0][1]           # Target_User цел
        assert all(not b.startswith("<mood>") for b in result)
        assert any("block=mood" in r.message for r in caplog.records)

    def test_reduction_order_anchors_first(self):
        svc = self._svc()
        budget = settings.CHAT_CONTEXT_BUDGET_TOKENS
        filler = "текстовыйнаполнитель " * (budget * 2)
        blocks = [
            ("target", "<Target_User>вася</Target_User>"),
            ("global", f"<Global_Context>\n{filler}\n</Global_Context>"),
            ("thread", f"<Conversation_Thread>\n{filler}\n</Conversation_Thread>"),
            ("anchors", f"<style_anchors>\n{filler}\n</style_anchors>"),
        ]
        result = svc._apply_context_budget(blocks)
        texts = {kind: text for (kind, _), text in zip(blocks, result)}
        from services.token_counter import count_tokens
        total = sum(count_tokens(t) for t in texts.values() if t)
        assert total <= budget
        anchors_left = count_tokens(texts["anchors"]) if texts["anchors"] else 0
        global_left = count_tokens(texts["global"])
        assert anchors_left <= global_left         # самое дешёвое урезано первым

    def test_budgets_disabled_old_behavior(self, monkeypatch):
        svc = self._svc()
        big = "слово " * 20000
        blocks = [("rag", f"<RAG_Memory>\n{big}\n</RAG_Memory>")]
        mod = dataclasses.replace(settings, CHAT_CONTEXT_BUDGETS_ENABLED=False)
        monkeypatch.setattr("services.direct_chat_service.settings", mod)
        result = svc._apply_context_budget(blocks)
        assert result[0] == blocks[0][1]           # без обрезки бюджетами


class TestRound8ContextBudgets:
    """Раунд 8 (B2/D2/T-791/T-799, spec §3.B2): effective-база бюджета
    (неприкосновенные target/protected/lore/current/sandwich вне лимитов и
    вне порядка урезания), новая доля branch, порядок урезания anchors →
    rag → thread → global(keep-head) → map; mood делит долю target."""

    def _svc(self):
        return _make_service()

    def test_uncuttable_kinds_never_truncated(self):
        svc = self._svc()
        target = "<Target_User>" + "оченьдлинноебессмысленноемя" * 400 + "</Target_User>"
        current = "<Current_Question>\n" + "вопрос " * 20000 + "\n</Current_Question>"
        protected = "<protected_facts>\nважные факты:\n- " + "факт " * 20000 + "\n</protected_facts>"
        lore = "<chat_lore>\n" + "лор " * 20000 + "\n</chat_lore>"
        sandwich = "отвечай коротко " * 20000
        blocks = [
            ("target", target), ("current", current),
            ("protected", protected), ("lore", lore),
            ("sandwich", sandwich),
        ]
        result = svc._apply_context_budget(blocks)
        texts = {kind: text for (kind, _), text in zip(blocks, result)}
        # неприкосновенные kinds вне лимитов и вне порядка урезания — целы
        assert texts["target"] == target
        assert texts["current"] == current
        assert texts["protected"] == protected
        assert texts["lore"] == lore
        assert texts["sandwich"] == sandwich

    def test_effective_base_reduces_cuttable_shares(self):
        """B2: лимиты долей считаются от effective = max(1, budget − fixed):
        большой неприкосновенный блок ужимает доли режущихся."""
        svc = self._svc()
        from services.token_counter import count_tokens

        def _big(tokens: int) -> str:
            unit = "текстовыйнаполнитель "
            text = ""
            while count_tokens(text) < tokens:
                text += unit
            return text

        big_map = f"<UserResolutionMap>\n{_big(4000)}\n</UserResolutionMap>"
        small_target = "<Target_User>вася</Target_User>"
        # (1) без fixed → доля от полного бюджета
        result = svc._apply_context_budget([("map", big_map)])
        full = count_tokens(result[0])
        # (2) с большим (но влезающим) fixed → effective заметно меньше
        fixed = f"<Target_User>{_big(1200)}</Target_User>"
        result2 = svc._apply_context_budget([("map", big_map),
                                             ("target", fixed)])
        texts2 = {kind: text for (kind, _), text in
                  zip([("map", big_map), ("target", fixed)], result2)}
        assert texts2["target"] == fixed               # неприкосновенный цел
        assert count_tokens(texts2["map"]) < full      # доля от effective

    def test_reduction_order_anchors_rag_thread_global_map(self):
        svc = self._svc()
        budget = settings.CHAT_CONTEXT_BUDGET_TOKENS
        filler = "текстовыйнаполнитель " * (budget * 3)
        blocks = [
            ("target", "<Target_User>вася</Target_User>"),
            ("map", f"<UserResolutionMap>\n{filler}\n</UserResolutionMap>"),
            ("rag", f"<RAG_Memory>\n{filler}\n</RAG_Memory>"),
            ("global", f"<Global_Context>\n{filler}\n</Global_Context>"),
            ("thread", f"<Conversation_Thread>\n{filler}\n</Conversation_Thread>"),
            ("anchors", f"<style_anchors>\n{filler}\n</style_anchors>"),
        ]
        result = svc._apply_context_budget(blocks)
        texts = {kind: text for (kind, _), text in zip(blocks, result)}
        from services.token_counter import count_tokens
        # первым дешёвое: anchors урезаны сильнее всех режущихся
        anchors_t = count_tokens(texts["anchors"]) if texts["anchors"] else 0
        map_t = count_tokens(texts["map"])
        assert anchors_t <= map_t
        assert texts["map"].startswith("<UserResolutionMap>")
        assert texts["global"].startswith("<Global_Context>")

    def test_global_keep_head_vs_thread_keep_end(self):
        """D2: урезание kind=global держит голову (конец body режется),
        thread/map — keep-end (как сегодня)."""
        svc = self._svc()
        head = "AAAA-начало-конспекта " * 300
        tail = "BBBB-свежий-хвост " * 300
        global_block = f"<Global_Context>\n{head}{tail}\n</Global_Context>"
        from services.token_counter import count_tokens
        limit = count_tokens(f"<Global_Context>\n{head}\n</Global_Context>") + 5
        cut = svc._truncate_block(global_block, limit, kind="global")
        assert "AAAA-начало-конспекта" in cut       # голова держится
        assert "BBBB-свежий-хвост" not in cut       # конец режется первым
        thread_block = f"<Conversation_Thread>\n{head}{tail}\n</Conversation_Thread>"
        cut_t = svc._truncate_block(thread_block, limit, kind="thread")
        assert "AAAA-начало-конспекта" not in cut_t  # keep-end: старое режется
        assert "BBBB-свежий-хвост" in cut_t

    def test_branch_share_applied(self, monkeypatch):
        """B2: доля branch = limits.chat_budget_branch_ratio от effective."""
        svc = self._svc()
        big = "<Conversation_Branch>\n" + "ход " * 20000 + "\n</Conversation_Branch>"
        result = svc._apply_context_budget([("branch", big)])
        from services.token_counter import count_tokens
        share = settings.CHAT_CONTEXT_BUDGET_TOKENS * \
            settings.CHAT_BUDGET_BRANCH_RATIO
        assert count_tokens(result[0]) <= share + 10

    def test_sandwich_not_added_by_budget(self):
        """B2/FR-23: sandwich добавляется в сборке (не бюджетом) — бюджет
        просто не режет kind вне лимитов; пустой список не ломается."""
        svc = self._svc()
        assert svc._apply_context_budget([]) == []


class TestRound8Importance:
    """Раунд 8 (E1/T-803): importance-удержание verbatim-строк — маркеры
    без LLM (имя из карты / «бот» / кавычки / число / «?» / ≥3 слов);
    флаг chat_importance_keep_enabled off → старое поведение."""

    def test_line_markers_matrix(self):
        from services.direct_chat_service import _line_markers
        names = frozenset(("вася", "саша"))
        assert _line_markers("петя: вася принёс торт", names) == {"name", "long"}
        assert _line_markers("петя: бот вчера отвечал", names) == {"bot", "long"}
        assert _line_markers("петя: он сказал \"да\"", names) == {"quote", "long"}
        assert _line_markers("петя: цифра 42", names) == {"number"}
        assert _line_markers("петя: 42", names) == {"number"}
        assert "qmark" in _line_markers("петя: а ты кто?", names)
        assert "long" in _line_markers("петя: а ты кто?", names)
        assert _line_markers("петя: лол", names) == frozenset()      # шум
        assert _line_markers("петя: лол кек", names) == frozenset()

    def test_trim_keeps_important_drops_noise_from_old(self):
        from services.direct_chat_service import trim_verbatim_lines
        lines = [
            "петя: лол",                        # шум (старая)
            "петя: 42",                         # слабый (ровно один маркер: число)
            "петя: вася принёс торт",           # сильный (имя в тексте)
            "петя: кек",                        # шум (новая)
        ]
        # chars-мера для детерминизма
        kept = trim_verbatim_lines(lines, 22, names=frozenset(("вася",)),
                                   measure=len)
        assert kept == ["петя: вася принёс торт"]  # шум+слабый выпали, strong жив
        kept2 = trim_verbatim_lines(lines, 35, names=frozenset(("вася",)),
                                    measure=len)
        assert kept2 == ["петя: 42", "петя: вася принёс торт"]  # шум выпал первым
        # порядок ASC не меняется
        kept3 = trim_verbatim_lines(lines, 60, names=frozenset(("вася",)),
                                    measure=len)
        assert kept3 == lines

    def test_trim_weak_markers_drop_after_noise(self):
        from services.direct_chat_service import trim_verbatim_lines
        lines = [
            "петя: лол",                    # шум
            "петя: хватит уже спорить",     # слабый (≥3 слов, ровно один)
            "петя: вася принёс торт",       # сильный
        ]
        kept = trim_verbatim_lines(lines, 22, names=frozenset(("вася",)),
                                   measure=len)
        # шум ушёл первым, потом слабый; сильный остался
        assert kept == ["петя: вася принёс торт"]

    def test_trim_flag_off_old_behavior(self):
        from services.direct_chat_service import trim_verbatim_lines
        lines = [
            "петя: лол",
            "петя: завтра в 12",
            "петя: вася принёс торт",
            "петя: кек",
        ]
        kept = trim_verbatim_lines(lines, 45, names=frozenset(("вася",)),
                                   keep_important=False, measure=len)
        # старое поведение: жертвы со стороны начала, маркеры НЕ влияют
        assert kept == ["петя: вася принёс торт", "петя: кек"]
        assert "петя: лол" not in kept
        # с включённым удержанием при том же давлении шум ушёл бы первым
        kept_on = trim_verbatim_lines(lines, 45, names=frozenset(("вася",)),
                                      keep_important=True, measure=len)
        assert kept_on == ["петя: завтра в 12", "петя: вася принёс торт"]

    @pytest.mark.asyncio
    async def test_global_keeps_important_lines_under_pressure(self, fake_time,
                                                               caplog,
                                                               monkeypatch):
        """E1.4(а): при урезании global verbatim-хвоста шумные строки
        выпадают первыми, важные (числа/длина/имя) держатся."""
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_GLOBAL_CONTEXT_MAX_TOKENS=300))
        important = ("завтра в 12 идём смотреть дроны очень круто потому что "
                     "вася сказал это точно")            # name+number+long
        window = []
        for i in range(40):
            text = important if i % 2 == 0 else "лол"
            row = _window_row(user_id=10, author_name="старое имя",
                              text=text, ts=100 + i)
            window.append(row)
        window[-1] = _window_row(user_id=10, author_name="старое имя",
                                 text="угу", ts=100 + len(window))
        memory = FakeMemory(window=window)
        service = _make_service(memory=memory)
        with caplog.at_level(logging.WARNING):
            blocks = await service._build_user_content(
                CHAT_ID, _message(), "вася")
        global_block = next(b for b in blocks
                            if b.startswith("<Global_Context>"))
        body = global_block[len("<Global_Context>\n"):-len("\n</Global_Context>")]
        assert important in body                    # важное держится
        assert "угу" not in body                    # свежий шум — жертва
        assert body.count("лол") == 0               # весь шум выпал
        assert any("global context truncated" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_importance_flag_off_old_behavior(self, fake_time,
                                                    monkeypatch):
        """E1.3: флаг chat_importance_keep_enabled off → trim без маркер-
        фильтра (срез со стороны начала, ровно старое поведение)."""
        from services.direct_chat_service import trim_verbatim_lines
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _cfg(CHAT_IMPORTANCE_KEEP_ENABLED=False))
        lines = [
            "петя: лол",
            "петя: завтра в 12",
            "петя: вася принёс торт",
            "петя: кек",
        ]
        # флаг off: и в _build_global_context, и в чистой функции
        kept = trim_verbatim_lines(
            lines, 45, names=frozenset(("вася",)),
            keep_important=False, measure=len)
        # жертвы со стороны начала, маркеры НЕ влияют
        assert kept == ["петя: вася принёс торт", "петя: кек"]
        assert trim_verbatim_lines(lines, 45, names=frozenset(("вася",)),
                                   keep_important=False, measure=len) == \
            ["петя: вася принёс торт", "петя: кек"]


class TestRound8FactAttribution:
    """Раунд 8 (C6/T-797): memorize-хук «кто спрашивал» + пост-фаза — факт
    про третье лицо НЕ приписывается спрашивающему (target_user → subject)."""

    async def _db(self):
        d = DatabaseService(":memory:")
        await d.initialize()
        return d

    async def _participants(self, d):
        for uid, author in ((10, "вася"), (20, "саша"), (30, "петя")):
            await d.save_smart_message(
                user_id=uid, chat_id=CHAT_ID, text="реплика",
                reply_to_id=None, timestamp=100, media_type="text",
                author_name=author, message_id=uid)

    @pytest.mark.asyncio
    async def test_fact_about_third_person_not_attributed_to_asker(self,
                                                                    fake_time):
        """Петя спросил про Васю → факт с subject=вася записывается на васю
        (target_user=вася), карточка/квота спрашивающего не засоряется."""
        d = await self._db()
        await self._participants(d)
        # батч «после min_id=0», записанный на Петю (asker)
        await d.insert_graph_fact(
            CHAT_ID, "вася любит дроны", "bot_direct_reply", None,
            target_user="петя")
        await d.insert_graph_fact(
            CHAT_ID, "саша купил машину", "bot_direct_reply", None,
            target_user="петя")
        await d.insert_graph_fact(
            CHAT_ID, "проект переезжает в офис", "bot_direct_reply", None,
            target_user="петя")                    # тема — остаётся Пете
        await d.insert_graph_fact(
            CHAT_ID, "петя любит пиво", "bot_direct_reply", None,
            target_user="петя")                    # self-факт — остаётся Пете
        service = _make_service(db=d)
        await service._reassign_fact_owners(CHAT_ID, "петя", min_id=0)
        cursor = await d.db.execute(
            "SELECT fact, target_user FROM graph_facts "
            "WHERE chat_id = ? ORDER BY id", (CHAT_ID,))
        rows = {row["fact"]: row["target_user"] for row in await cursor.fetchall()}
        assert rows["вася любит дроны"] == "вася"      # третье лицо → ему
        assert rows["саша купил машину"] == "саша"
        assert rows["проект переезжает в офис"] == "петя"   # тема остаётся
        assert rows["петя любит пиво"] == "петя"            # self остаётся
        await d.close()

    @pytest.mark.asyncio
    async def test_memorize_direct_reply_wrapper_keeps_path(self, fake_time,
                                                            monkeypatch):
        """C6: handle-путь — memorize_facts зовётся с target_user=канон
        спрашивающего; пост-фаза fail-open (FakeDB без graph) не роняет."""
        tasks = []

        def sync_fire_and_forget(coro, tag):
            tasks.append(coro)

        monkeypatch.setattr("services.direct_chat_service.fire_and_forget",
                            sync_fire_and_forget)
        memory = FakeMemory(window=[_window_row()])
        llm = FakeLLM(text="короткий ответ бота")
        aliases = AliasResolver('{"10": "вася"}')
        service = _make_service(memory=memory, llm=llm, aliases=aliases)
        bot = _bot()
        msg = _message(text="расскажи про себя", message_id=77)
        await service.handle(bot, msg, msg.from_user)
        assert tasks
        await tasks[0]                               # wrapper отработал без падения
        assert memory.memorized[0]["source"] == "bot_direct_reply"
        assert memory.memorized[0]["target_user"] == "вася"
        assert memory.memorized[0]["raw"] == "расскажи про себя\nкороткий ответ бота"
        assert bot.send_message.await_args.args[1] == "короткий ответ бота"


class TestCanonP20MemoryGuards:
    """67.1 (T-491, правило п.20, D243/D249): в память идут ТОЛЬКО факты из
    УСПЕШНО отправленных ответов (гейт sent_id). Заглушки/мусор — НИКОГДА:
    пустой ответ/LLMError/исключение/fail отправки — memorize не планируется.
    Стражи-тесты БЕЗ изменения поведения."""

    def _collect_fire_forget(self, monkeypatch):
        tasks = []
        monkeypatch.setattr("services.direct_chat_service.fire_and_forget",
                            sync_fire_forget_helper(tasks))
        return tasks

    @pytest.mark.asyncio
    async def test_llm_error_never_memorizes(self, fake_time, monkeypatch):
        tasks = self._collect_fire_forget(monkeypatch)
        memory = FakeMemory()
        service = _make_service(memory=memory,
                                llm=FakeLLM(error=LLMError("апи упал")))
        await service.handle(_bot(), _message(text="привет"), _user())
        assert tasks == []                         # memorize НЕ запланирован
        assert not memory.memorized

    @pytest.mark.asyncio
    async def test_send_failure_never_memorizes(self, fake_time, monkeypatch):
        """sent_id None (отправка не удалась) → факты НЕ пишутся."""
        tasks = self._collect_fire_forget(monkeypatch)
        memory = FakeMemory()
        service = _make_service(memory=memory)
        bot = _bot()
        bot.send_message = AsyncMock(return_value=None)
        await service.handle(bot, _message(text="привет"), _user())
        assert tasks == []
        assert not memory.memorized

    @pytest.mark.asyncio
    async def test_cooldown_phrase_never_memorizes(self, fake_time, monkeypatch):
        """Кулдаун-фраза (R50-7) — заглушка: в память не попадает."""
        tasks = self._collect_fire_forget(monkeypatch)
        memory = FakeMemory()
        llm = FakeLLM()
        throttle = DirectChatThrottle(1, 300.0)
        service = _make_service(memory=memory, llm=llm, throttle=throttle)
        throttle.allow(CHAT_ID, 10)                # заранее сжечь заряд
        await service.handle(_bot(), _message(text="ну что"), _user())
        assert tasks == []
        assert not memory.memorized
        assert llm.call_count == 0                 # LLM даже не вызывался

    @pytest.mark.asyncio
    async def test_unexpected_error_never_memorizes(self, fake_time, monkeypatch):
        tasks = self._collect_fire_forget(monkeypatch)
        memory = FakeMemory()

        class BoomMemory(FakeMemory):
            async def get_window_messages(self, chat_id):
                raise RuntimeError("БД упала")

        service = _make_service(memory=BoomMemory())
        await service.handle(_bot(), _message(text="привет"), _user())
        assert tasks == []
        assert not memory.memorized


class TestHandleDedup:
    """Epic 60 Фаза E (67.4, T-499, п.8): дедуп одинаковых текстов подряд.
    Ключ «чат+человек+текст» (slug direct_dedup в smart_cache); проверка ПОСЛЕ
    throttle/CB/замка и ПЕРЕД сборкой контекста; повтор → сохранённый ответ
    без LLM (или молчание, если в прошлый раз ответа не было)."""

    @pytest.fixture
    def cache(self, tmp_path):
        return SmartCache(str(tmp_path / "dedup.db"))

    @pytest.mark.asyncio
    async def test_first_occurrence_answers_then_repeat_replays(self, fake_time, cache):
        llm = FakeLLM(text="короткий ответ бота")
        service = _make_service(llm=llm, cache=cache)
        bot = _bot()
        await service.handle(bot, _message(text="бот, привет", message_id=1), _user())
        assert llm.call_count == 1
        await service.handle(bot, _message(text="БОТ, ПРИВЕТ", message_id=2), _user())
        assert llm.call_count == 1                 # LLM НЕ вызван повторно
        assert bot.send_message.await_count == 2
        second = bot.send_message.await_args_list[1]
        assert second.args[1] == "короткий ответ бота"
        assert second.kwargs["reply_to_message_id"] == 2   # reply на НОВОЕ сообщение

    @pytest.mark.asyncio
    async def test_different_user_independent(self, fake_time, cache):
        llm = FakeLLM()
        service = _make_service(llm=llm, cache=cache)
        bot = _bot()
        await service.handle(bot, _message(text="одинаковый текст"), _user(user_id=10))
        await service.handle(bot, _message(text="одинаковый текст"), _user(user_id=20))
        assert llm.call_count == 2                 # ключ включает user_id

    @pytest.mark.asyncio
    async def test_different_text_not_deduped(self, fake_time, cache):
        llm = FakeLLM()
        service = _make_service(llm=llm, cache=cache)
        bot = _bot()
        await service.handle(bot, _message(text="первый вопрос"), _user())
        await service.handle(bot, _message(text="второй вопрос"), _user())
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_ttl_expiry_calls_llm_again(self, fake_time, cache, monkeypatch):
        clock = {"now": 1000.0}

        class FakeCacheTime:
            @staticmethod
            def monotonic():
                return clock["now"]

            @staticmethod
            def time():
                return clock["now"]

        monkeypatch.setattr("services.smart_cache.time", FakeCacheTime)
        monkeypatch.setattr(
            "services.smart_cache.settings",
            dataclasses.replace(settings, CHAT_DEDUP_TTL_SECONDS=10))
        llm = FakeLLM()
        service = _make_service(llm=llm, cache=cache)
        bot = _bot()
        await service.handle(bot, _message(text="один и тот же"), _user())
        clock["now"] += 5
        await service.handle(bot, _message(text="один и тот же"), _user())
        assert llm.call_count == 1                 # в пределах TTL — кэш
        clock["now"] += 11
        await service.handle(bot, _message(text="один и тот же"), _user())
        assert llm.call_count == 2                 # TTL истёк — обычный поток

    @pytest.mark.asyncio
    async def test_switch_off_restores_old_behavior(self, fake_time, cache, monkeypatch):
        monkeypatch.setattr(
            "services.smart_cache.settings",
            dataclasses.replace(settings, CHAT_DEDUP_ENABLED=False))
        llm = FakeLLM()
        service = _make_service(llm=llm, cache=cache)
        bot = _bot()
        await service.handle(bot, _message(text="задвоенный текст"), _user())
        await service.handle(bot, _message(text="задвоенный текст"), _user())
        assert llm.call_count == 2                 # рубильник выключил слой

    @pytest.mark.asyncio
    async def test_no_cache_injected_feature_dormant(self, fake_time):
        """cache=None (старая сигнатура/тесты) → фича полностью прозрачна."""
        llm = FakeLLM()
        service = _make_service(llm=llm)           # без cache=
        bot = _bot()
        await service.handle(bot, _message(text="текст"), _user())
        await service.handle(bot, _message(text="текст"), _user())
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_answer_repeat_silence(self, fake_time, cache):
        """Прошлый раз ответа не было (🗿-пустой) → повтор того же текста
        МОЛЧИТ: ни LLM, ни заглушки (67.4: маркер "" в дедуп-кэше)."""
        llm = FakeLLM(text="   ")                  # пустой ответ
        service = _make_service(llm=llm, cache=cache)
        bot = _bot()
        await service.handle(bot, _message(text="бот, эй", message_id=1), _user())
        bot.send_message.assert_not_called()       # 🗿-ветка (65.1)
        await service.handle(bot, _message(text="бот, эй", message_id=2), _user())
        assert llm.call_count == 1                 # модель не дёргается
        bot.send_message.assert_not_called()       # повтор — чистое молчание

    @pytest.mark.asyncio
    async def test_llm_error_repeat_silence(self, fake_time, cache):
        """После LLMError (фраза-ошибка отправлена) повтор того же текста
        молчит: фраза-ошибка НЕ переотправляется и НЕ кэшируется как ответ."""
        llm = FakeLLM(error=LLMError("апи упал"))
        service = _make_service(llm=llm, cache=cache)
        bot = _bot()
        await service.handle(bot, _message(text="бот, эй", message_id=1), _user())
        assert bot.send_message.await_count == 1   # фраза CHAT_ERROR_PHRASES
        await service.handle(bot, _message(text="бот, эй", message_id=2), _user())
        assert llm.call_count == 1
        assert bot.send_message.await_count == 1   # тишина, не повтор заглушки

    @pytest.mark.asyncio
    async def test_throttle_stays_first_barrier(self, fake_time, cache):
        """D237: троттлинг остаётся первым барьером — флудер одинаковым
        текстом выжигает заряды и получает cooldown-фразу, а НЕ обход кэша."""
        llm = FakeLLM()
        service = _make_service(llm=llm, cache=cache,
                                throttle=DirectChatThrottle(1, 300.0))
        bot = _bot()
        await service.handle(bot, _message(text="спам", message_id=1), _user())
        assert llm.call_count == 1
        before = bot.send_message.await_count
        await service.handle(bot, _message(text="спам", message_id=2), _user())
        assert llm.call_count == 1                 # до дедупа слои не дошли
        assert bot.send_message.await_count > before   # cooldown-фраза R50-7


# ═══════════════════════════════════════════════════════════════════
# Эпик 04.09.2026 (3.3, FR-17): direct_chat с настроенным tool_router —
# цикл chat_with_tools вместо generate; tool_router=None — старое поведение.
# ═══════════════════════════════════════════════════════════════════


class _ToolsLLM:
    """FakeLLM + generate_chat: первый вызов отдаёт tool_calls, второй — текст."""

    def __init__(self, final_text="итоговый ответ"):
        self.final_text = final_text
        self.call_count = 0
        self.seen_tools = None

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto"):
        self.call_count += 1
        self.seen_tools = tools
        if self.call_count == 1:
            from services.llm_client import LLMChatResult, LLMToolCall
            return LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(id="call_1", name="execute_web_search",
                                        arguments='{"query": "новости"}')],
                finish_reason="tool_calls")
        from services.llm_client import LLMChatResult
        return LLMChatResult(content=self.final_text, tool_calls=None,
                             finish_reason="stop")

    async def generate(self, messages, temperature=None):
        raise AssertionError("generate не должен зваться при живом tools-цикле")


class _FakeToolRouter:
    def __init__(self):
        self.calls = []

    async def dispatch(self, name, arguments, ctx):
        self.calls.append((name, arguments, ctx.chat_id))
        return "данные поиска"


class TestDirectChatToolCalling:
    @pytest.mark.asyncio
    async def test_tool_router_enabled_runs_loop_and_replies(self, fake_time):
        """Настроенный tool_router → chat_with_tools: инструмент отработал,
        финальный текст ушёл юзеру обычным reply."""
        llm = _ToolsLLM(final_text="вот данные: новости такие")
        router = _FakeToolRouter()
        memory = FakeMemory(window=[])
        service = _make_service(memory=memory, llm=llm, tool_router=router)
        bot = _bot()
        msg = _message(text="бот, загугли новости", message_id=77)
        await service.handle(bot, msg, msg.from_user)
        assert router.calls == [("execute_web_search", {"query": "новости"},
                                 CHAT_ID)]
        assert llm.call_count == 2                    # tools-раунд + финал
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        assert bot.send_message.await_args.args[1] == "вот данные: новости такие"

    @pytest.mark.asyncio
    async def test_tool_router_none_plain_generate(self, fake_time):
        """tool_router=None → старый вызов generate (без tools): ровно одно
        обращение к модели, инструменты не объявляются."""
        llm = FakeLLM(text="обычный ответ")
        service = _make_service(llm=llm)              # tool_router=None
        bot = _bot()
        await service.handle(bot, _message(message_id=1), _user())
        assert llm.call_count == 1
        assert bot.send_message.await_args.args[1] == "обычный ответ"

    @pytest.mark.asyncio
    async def test_tool_round_failure_sends_error_phrase(self, fake_time):
        """Сбой LLM во время tools-раунда → существующая фраза CHAT_ERROR_PHRASES
        (классы ошибок те же; юзер не видит деталей инструментов)."""

        class _FailingToolsLLM(_ToolsLLM):
            async def generate_chat(self, messages, *, temperature=None,
                                    tools=None, tool_choice="auto"):
                from services.llm_client import LLMServerError
                raise LLMServerError("LLM server error 503 after 3 attempts: u")

        service = _make_service(llm=_FailingToolsLLM(),
                                tool_router=_FakeToolRouter())
        bot = _bot()
        await service.handle(bot, _message(message_id=1), _user())
        assert bot.send_message.await_args.args[1] in CHAT_ERROR_PHRASES


def sync_fire_forget_helper(tasks):
    def sync_fire_and_forget(coro, tag):
        tasks.append(coro)
    return sync_fire_and_forget
