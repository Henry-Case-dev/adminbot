"""Epic 60 (Section 64.5/64.9, T-466): collect_metrics — фикс-формат блока
метрик здоровья памяти; только счётчики/размеры, без персональных данных."""
import asyncio
import time
from unittest.mock import MagicMock

import pytest

from services.database import DatabaseService
from services.memory_health import collect_metrics


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


@pytest.fixture
def no_vec_memory():
    memory = MagicMock()
    memory.vec_available = False
    return memory


class TestCollectMetrics:
    @pytest.mark.asyncio
    async def test_fixed_format_with_data(self, db, no_vec_memory):
        await db.insert_graph_fact(-100, "озон доставляет быстрее чем wildberries",
                                   "search_fact", None)
        await db.insert_graph_fact(-100, "вася спорил с петей", "chat_history", None)
        await db.save_archive_fact(-100, "архивный факт", 1)
        await db.save_smart_message(1, -100, "сообщение", None,
                                    int(time.time()), "text", "вася")

        text = await collect_metrics(db, no_vec_memory)

        lines = text.splitlines()
        assert lines[0].startswith("graph_facts: 2 (")
        assert "chat_history 1" in lines[0]
        assert "search_fact 1" in lines[0]
        assert "graph_facts: просрочено 0, не подтверждено 0" in text
        assert "smart_archive_facts: 1" in text
        assert "smart_messages: 1" in text
        assert "nodes: 0, edges: 0" in text           # insert_graph_fact не трогает граф
        assert "embedding_cache: 0 строк" in text
        assert "throttle_state: 0 строк" in text
        assert "vec: недоступен" in text
        assert "записано фактов за сутки: 2, дублей отсеяно: 0" in text
        assert any(line.startswith("диск: свободно") for line in lines)
        # R17: никаких персональных данных — только счётчики/размеры

    @pytest.mark.asyncio
    async def test_unconfirmed_and_expired_counters(self, db, no_vec_memory):
        now = int(time.time())
        await db.insert_graph_fact(-100, "свежий факт", "search_fact", now + 100)
        await db.insert_graph_fact(-100, "протухший факт", "web_content", now - 100)
        await db.insert_graph_fact(-100, "не подтверждено факт", "search_fact",
                                   now + 100, status="unconfirmed")
        text = await collect_metrics(db, no_vec_memory)
        assert "просрочено 1, не подтверждено 1" in text

    @pytest.mark.asyncio
    async def test_vec_available_line(self, db):
        memory = MagicMock()
        memory.vec_available = True
        memory._vec_dim = 3072
        text = await collect_metrics(db, memory)
        assert "vec: float32 dim=3072" in text

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_string(self, db, no_vec_memory, caplog):
        import logging

        async def boom(*args, **kwargs):
            raise RuntimeError("бд сломалась")

        db.db.execute = boom
        with caplog.at_level(logging.WARNING):
            text = await collect_metrics(db, no_vec_memory)
        assert text == ""
        assert any("memory_health: collect failed" in r.message
                   for r in caplog.records)
