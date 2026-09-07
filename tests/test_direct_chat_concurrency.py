"""Раунд N (T-840/T-842): direct_chat на per-chat пуле семафоров вместо
замка R60-2. Ключевые регрессии:
  * N=2: два handle ОДНОГО чата выполняются параллельно (раньше — строго
    последовательно per-chat локом); третий ждёт слот / получает busy-фразу;
  * N=1: чат A занят — чат B НЕ блокируется (гарантия разных чатов);
  * таймаут ожидания слота → CHAT_LOCK_BUSY_PHRASES (текст лога
    «direct: lock wait timeout» сохранён).
Сервис получает собственный ChatConcurrencyPool (DI) — синглтон не задет.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import config.settings as settings_module
from services.direct_chat_service import DirectChatService, DirectChatThrottle
from services.smartmodule_concurrency import ChatConcurrencyPool
from services.smartmodule_phrases import CHAT_LOCK_BUSY_PHRASES
from services.summary_aliases import AliasResolver

CHAT_A = -1001234567890
CHAT_B = -1001234567891


@pytest.fixture
def pool_n(monkeypatch):
    """N для НОВЫХ пулов (hot-кэш в тестах не инициализирован → settings)."""

    def _set(n: int, wait: float = 60.0):
        monkeypatch.setattr(
            "services.smartmodule_concurrency.settings",
            settings_module.Settings(
                SMARTMODULE_CONCURRENCY_PER_CHAT=n,
                SMARTMODULE_CONCURRENCY_WAIT_SECONDS=wait))
    return _set


def _user(user_id=10, first_name="Вася", last_name="Пупкин", username="vasya"):
    u = MagicMock()
    u.id = user_id
    u.first_name = first_name
    u.last_name = last_name
    u.username = username
    return u


def _message(text="привет, бот", message_id=100, user=None, chat_id=CHAT_A):
    m = MagicMock()
    m.text = text
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = chat_id
    m.from_user = user if user is not None else _user()
    m.reply_to_message = None
    return m


def _bot():
    bot = AsyncMock()
    sent = MagicMock()
    sent.message_id = 999
    bot.send_message = AsyncMock(return_value=sent)
    return bot


class FakeMemory:
    """Минимум для handle(): пустое окно → контекст-блоки пустые/без RAG."""

    def __init__(self, window=None, rag=""):
        self.window = window if window is not None else []
        self.rag = rag

    async def get_window_messages(self, chat_id):
        return self.window

    async def get_rag_context(self, chat_id, query, *, sort_by_timestamp=False,
                              include_direct_reply=False):
        return self.rag

    async def get_rag_facts(self, chat_id, query, *,
                            include_direct_reply=False):
        return [("chat_history", self.rag, None)] if self.rag else []

    async def rerank_rag_facts(self, query, facts):
        return list(facts)

    async def memorize_facts(self, chat_id, raw_text, source_type,
                             target_user=None):
        return None


class FakeDB:
    """Заглушки БД для путей handle() с пустым окном (лучше-эффект)."""

    def __init__(self):
        self.tone_preset = None

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        return None

    async def last_bot_replies(self, chat_id, limit, now):
        return []

    async def get_user_tone_preset(self, chat_id, user_id):
        return self.tone_preset

    async def set_user_tone_preset(self, chat_id, user_id, preset):
        self.tone_preset = preset

    async def get_protected_facts(self, chat_id, user_name,
                                  include_chat_level=True):
        return []

    async def clear_direct_dialogue(self, chat_id, target_user):
        return 0

    async def forget_direct_facts(self, chat_id, target_user, phrase, now_ts):
        return 0

    async def upsert_bot_reply(self, chat_id, tg_message_id, text, ts):
        return None

    async def set_bot_reply_parent(self, chat_id, tg_message_id, parent, ts):
        return None

    async def get_bot_reply_parent(self, chat_id, tg_message_id, now):
        return None

    async def get_bot_reply(self, chat_id, tg_message_id, now):
        return None


class GateLLM:
    """LLM с активностью под асинхронным затвором (детерминированная гонка
    параллельных handle): generate висит на Event до явного release."""

    def __init__(self, text="всё по делу, иди нахуй"):
        self.text = text
        self.gate = asyncio.Event()
        self.call_count = 0
        self.active = 0
        self.max_active = 0

    async def generate(self, messages, temperature=None, chat_id=None):
        self.call_count += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await self.gate.wait()
            return self.text
        finally:
            self.active -= 1


@pytest.fixture
def lock_wait_short(monkeypatch):
    """CHAT_LOCK_WAIT_SECONDS=0.05 в direct_chat_service (таймаут-ветка)."""
    monkeypatch.setattr(
        "services.direct_chat_service.settings",
        settings_module.Settings(CHAT_LOCK_WAIT_SECONDS=0.05))


def _make_service(llm=None, concurrency_pool=None):
    return DirectChatService(
        FakeMemory(),
        FakeDB(),
        llm or GateLLM(),
        AliasResolver("{}"),
        throttle=DirectChatThrottle(50, 300.0),
        bot_id=12345,
        bot_username="test_bot",
        breaker=None,
        cache=None,
        tool_router=None,
        concurrency_pool=concurrency_pool,
    )


async def _until(pred, ticks: int = 20) -> bool:
    """Дать циклу до ticks тиков, пока pred() не станет истиной."""
    for _ in range(ticks):
        if pred():
            return True
        await asyncio.sleep(0)
    return pred()


class TestDirectChatConcurrency:
    @pytest.mark.asyncio
    async def test_two_handles_same_chat_parallel_at_n2(self, pool_n):
        """N=2: два handle ОДНОГО чата одновременно в генерации
        (регрессия старого per-chat лока: раньше max_active == 1)."""
        pool_n(2)
        llm = GateLLM()
        service = _make_service(llm=llm, concurrency_pool=ChatConcurrencyPool())
        bot1, bot2 = _bot(), _bot()

        task1 = asyncio.ensure_future(
            service.handle(bot1, _message(message_id=1), _user()))
        task2 = asyncio.ensure_future(
            service.handle(bot2, _message(message_id=2), _user()))
        assert await _until(lambda: llm.call_count == 2)
        assert llm.max_active == 2              # обе генерации параллельны
        llm.gate.set()
        await asyncio.gather(task1, task2)
        assert llm.active == 0
        assert bot1.send_message.await_args.args[1] == llm.text
        assert bot2.send_message.await_args.args[1] == llm.text

    @pytest.mark.asyncio
    async def test_third_handle_waits_for_slot_at_n2(self, pool_n):
        """N=2 исчерпан → третий handle встаёт в очередь и проходит после
        освобождения слота (без busy-фразы)."""
        pool_n(2)
        llm = GateLLM()
        service = _make_service(llm=llm, concurrency_pool=ChatConcurrencyPool())
        bot1, bot2, bot3 = _bot(), _bot(), _bot()

        task1 = asyncio.ensure_future(
            service.handle(bot1, _message(message_id=1), _user()))
        task2 = asyncio.ensure_future(
            service.handle(bot2, _message(message_id=2), _user()))
        assert await _until(lambda: llm.call_count == 2)
        task3 = asyncio.ensure_future(
            service.handle(bot3, _message(message_id=3), _user()))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert llm.call_count == 2              # третий ждёт слот
        assert not task3.done()
        llm.gate.set()                          # первые два завершаются →
        await asyncio.wait_for(task3, timeout=5)   # слот освободился
        assert llm.call_count == 3
        assert llm.max_active == 2
        await asyncio.gather(task1, task2)

    @pytest.mark.asyncio
    async def test_third_handle_busy_phrase_on_timeout(self, pool_n,
                                                       lock_wait_short):
        """N исчерпан и таймаут истёк → CHAT_LOCK_BUSY_PHRASES (реплика на
        ВЫЗОВ), лог «direct: lock wait timeout» сохранён."""
        pool_n(2)
        llm = GateLLM()
        service = _make_service(llm=llm, concurrency_pool=ChatConcurrencyPool())
        bot1, bot2, bot3 = _bot(), _bot(), _bot()

        task1 = asyncio.ensure_future(
            service.handle(bot1, _message(message_id=1), _user()))
        task2 = asyncio.ensure_future(
            service.handle(bot2, _message(message_id=2), _user()))
        assert await _until(lambda: llm.call_count == 2)
        await service.handle(bot3, _message(message_id=3), _user())
        assert bot3.send_message.await_args.args[1] in CHAT_LOCK_BUSY_PHRASES
        assert bot3.send_message.await_args.kwargs["reply_to_message_id"] == 3
        llm.gate.set()
        await asyncio.gather(task1, task2)

    @pytest.mark.asyncio
    async def test_busy_chat_a_does_not_block_chat_b(self, pool_n):
        """N=1: чат A держит слот — чат B генерирует параллельно
        (разные чаты никогда не блокируют друг друга)."""
        pool_n(1)
        llm = GateLLM()
        service = _make_service(llm=llm, concurrency_pool=ChatConcurrencyPool())
        bot_a, bot_b = _bot(), _bot()

        task_a = asyncio.ensure_future(
            service.handle(bot_a, _message(message_id=1, chat_id=CHAT_A),
                           _user()))
        assert await _until(lambda: llm.call_count == 1)
        task_b = asyncio.ensure_future(
            service.handle(bot_b, _message(message_id=2, chat_id=CHAT_B),
                           _user()))
        assert await _until(lambda: llm.call_count == 2)
        assert llm.max_active == 2              # оба чата в генерации
        llm.gate.set()
        await asyncio.gather(task_a, task_b)
