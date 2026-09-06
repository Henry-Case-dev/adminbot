"""Раунд N (T-841/T-842): SummaryGenerator на per-chat пуле вместо
глобального asyncio.Lock (A5). Ключевые регрессии:
  * чаты A и B генерируют саммари ПАРАЛЛЕЛЬНО (старый глобальный лок
    сериализовал ВСЕ чаты — max_active == 1);
  * N=1: cron и ручной /summary одного чата сериализуются, занятый чат →
    busy-фраза manual (B5) + лог «lock busy — queued», крон молчит;
  * крон-summary ходит через тот же пул (chat_id из задания).
"""
import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

import config.settings as settings_module
from services.summary_aliases import AliasResolver
from services.summary_generator import SummaryGenerator
from services.summary_xml import XmlGroundingBuilder

CHAT_A = -1111
CHAT_B = -2222

_UX_BUSY = "уже делаю саммари, подожди"


@pytest.fixture
def busy_pool_n(monkeypatch):
    """Чистый синглтон пула с N=1 — изолирован на время теста."""

    def _set(n: int = 1):
        monkeypatch.setattr(
            "services.smartmodule_concurrency.settings",
            settings_module.Settings(
                SMARTMODULE_CONCURRENCY_PER_CHAT=n,
                SMARTMODULE_CONCURRENCY_WAIT_SECONDS=60.0))
        from services.smartmodule_concurrency import (
            get_smartmodule_concurrency_pool,
            reset_smartmodule_concurrency_pool,
        )
        reset_smartmodule_concurrency_pool()
        return get_smartmodule_concurrency_pool()
    return _set


class FakeMemory:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.events = []

    async def compress_and_purge(self, chat_id):
        self.events.append("compress")

    async def get_window_messages(self, chat_id):
        self.events.append("window")
        return self.rows

    async def search_long_term(self, chat_id, keywords, limit):
        self.events.append("l2")
        return []

    async def vector_search(self, chat_id, query, limit):
        self.events.append("l3")
        return []

    async def get_graph_facts(self, chat_id, rows, keywords):
        return []

    async def memorize_facts(self, chat_id, raw_text, source_type):
        return None

    async def get_rag_context(self, chat_id, query):
        return ""


class GateLLM:
    """LLM под асинхронным затвором: generate висит до release — измеряем
    реальную параллельность генераций."""

    def __init__(self, text="саммари текста"):
        self.text = text
        self.gate = asyncio.Event()
        self.call_count = 0
        self.active = 0
        self.max_active = 0

    async def generate(self, messages):
        self.call_count += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await self.gate.wait()
            return self.text
        finally:
            self.active -= 1


def _row(author_name="вася", text="какое-то сообщение", **kwargs):
    row = {
        "id": 1,
        "user_id": 10,
        "timestamp": 1_700_000_000,
        "author_name": author_name,
        "text": text,
        "reply_to_id": None,
        "media_type": "text",
    }
    row.update(kwargs)
    return row


def _make_generator(memory, llm, bot, aliases=None):
    return SummaryGenerator(memory, XmlGroundingBuilder(), llm, bot,
                            aliases=aliases)


async def _until(pred, ticks: int = 30) -> bool:
    for _ in range(ticks):
        if pred():
            return True
        await asyncio.sleep(0)
    return pred()


class TestSummaryConcurrency:
    @pytest.mark.asyncio
    async def test_chats_a_and_b_summarize_in_parallel(self):
        """Регрессия глобального лока A5: саммари чатов A и B выполняются
        одновременно (per-chat пул; раньше — строго последовательно)."""
        llm = GateLLM()
        generator = _make_generator(FakeMemory(rows=[_row()]), llm,
                                    AsyncMock())
        bot = generator.bot

        task_a = asyncio.ensure_future(generator.generate_and_send(CHAT_A))
        task_b = asyncio.ensure_future(generator.generate_and_send(CHAT_B))
        assert await _until(lambda: llm.call_count == 2)
        assert llm.max_active == 2               # обе генерации в полёте
        llm.gate.set()
        await asyncio.gather(task_a, task_b)
        texts = [c.args[1] for c in bot.send_message.await_args_list]
        assert sum("самым главным шизом" in t for t in texts) == 2

    @pytest.mark.asyncio
    async def test_same_chat_manual_queued_after_cron(self, busy_pool_n,
                                                      caplog):
        """N=1: cron занимает чат → manual /summary того же чата получает
        busy-фразу и встаёт в очередь; после cron оба саммари отправлены."""
        busy_pool_n(1)
        llm = GateLLM()
        bot = AsyncMock()
        generator = _make_generator(FakeMemory(rows=[_row()]), llm, bot)

        cron = asyncio.ensure_future(generator.generate_and_send(CHAT_A))
        assert await _until(lambda: llm.call_count == 1)
        with caplog.at_level(logging.INFO):
            manual = asyncio.ensure_future(
                generator.generate_and_send(CHAT_A, manual=True))
            assert await _until(lambda: bool(bot.send_message.await_args_list))
        first = bot.send_message.await_args.args[1]
        assert first == _UX_BUSY
        assert any("lock busy — queued" in r.message and
                   "manual=True" in r.message for r in caplog.records)
        llm.gate.set()
        await asyncio.gather(cron, manual)
        texts = [c.args[1] for c in bot.send_message.await_args_list]
        assert sum("самым главным шизом" in t for t in texts) == 2

    @pytest.mark.asyncio
    async def test_same_chat_cron_queued_silent(self, busy_pool_n, caplog):
        """N=1: ручной /summary занимает чат → cron того же чата молчит
        (без UX-фразы), только INFO «lock busy — queued»; после release —
        крон-саммари уходит."""
        busy_pool_n(1)
        llm = GateLLM()
        bot = AsyncMock()
        generator = _make_generator(FakeMemory(rows=[_row()]), llm, bot)

        manual = asyncio.ensure_future(
            generator.generate_and_send(CHAT_A, manual=True))
        assert await _until(lambda: llm.call_count == 1)
        with caplog.at_level(logging.INFO):
            cron = asyncio.ensure_future(generator.generate_and_send(CHAT_A))
            assert await _until(lambda: any(
                "lock busy — queued" in r.message and
                "manual=False" in r.message for r in caplog.records))
            texts = [c.args[1] for c in bot.send_message.await_args_list]
            assert all("уже делаю" not in t for t in texts)   # крон без UX
            llm.gate.set()
            await asyncio.gather(manual, cron)
        texts = [c.args[1] for c in bot.send_message.await_args_list]
        assert sum("самым главным шизом" in t for t in texts) == 2
