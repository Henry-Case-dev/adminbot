"""Tests for services/summary_memory.py (T-176/T-177/T-179, Section 33.5)."""
import asyncio
import time
from dataclasses import replace
from unittest.mock import patch

import pytest

from config.settings import settings
from services.database import DatabaseService
from services.llm_client import LLMError
from services.summary_memory import MemoryManager, build_fts_query


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class FakeLLM:
    def __init__(self, facts="факт раз\nфакт два", vectors=None, fail_generate=False,
                 fail_embed=False):
        self.facts = facts
        self.vectors = vectors
        self.fail_generate = fail_generate
        self.fail_embed = fail_embed
        self.generate_calls = 0
        self.embed_calls = 0

    async def generate(self, messages):
        self.generate_calls += 1
        if self.fail_generate:
            raise LLMError("api упал")
        return self.facts

    async def embed(self, texts):
        self.embed_calls += 1
        if self.fail_embed:
            raise LLMError("эмбеддинги упали")
        if self.vectors is not None:
            return self.vectors
        return [[0.1] * settings.EMBEDDING_DIM for _ in texts]


async def _save(db, chat_id, text, ts, author="кто-то", media_type="text"):
    return await db.save_smart_message(1, chat_id, text, None, ts, media_type, author)


class TestBuildFtsQuery:
    def test_basic(self):
        assert build_fts_query(["привет", "мир"]) == '"привет"* OR "мир"*'

    def test_sanitizes_quotes_and_stars(self):
        assert build_fts_query(['при*вет"', '"цитата"']) == '"привет"* OR "цитата"*'

    def test_empty_keywords(self):
        assert build_fts_query([]) == ""
        assert build_fts_query(['"*"', "   "]) == ""


class TestInitialize:
    @pytest.mark.asyncio
    async def test_broken_extension_falls_back(self, db, monkeypatch):
        monkeypatch.setattr("sqlite_vec.loadable_path", lambda: "/nonexistent/vec0.dll")
        memory = MemoryManager(db, FakeLLM())
        result = await memory.initialize()
        assert result is False
        assert memory.vec_available is False

    @pytest.mark.asyncio
    async def test_real_sqlite_vec_optional(self, db):
        """Runs only when sqlite-vec is available in the environment."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FakeLLM())
        ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded here")
        assert memory.vec_available is True


class TestWindow:
    @pytest.mark.asyncio
    async def test_window_boundaries_include_exclude(self, db):
        now = int(time.time())
        await _save(db, -100, "старое", now - 10_000)
        await _save(db, -100, "на границе", now - 3600)
        await _save(db, -100, "в окне", now - 100)
        rows = await db.get_smart_window(-100, since_ts=now - 3600, limit=100)
        texts = [r["text"] for r in rows]
        assert "на границе" in texts  # включительно
        assert "в окне" in texts
        assert "старое" not in texts  # исключено

    @pytest.mark.asyncio
    async def test_window_asc_order(self, db):
        now = int(time.time())
        await _save(db, -100, "первое", now - 500)
        await _save(db, -100, "второе", now - 100)
        rows = await db.get_smart_window(-100, now - 3600, 100)
        assert [r["text"] for r in rows] == ["первое", "второе"]

    @pytest.mark.asyncio
    async def test_get_window_messages_uses_settings(self, db):
        now = int(time.time())
        await _save(db, -100, "внутри", now - 100)
        await _save(db, -100, "снаружи", now - 100_000)
        memory = MemoryManager(db, FakeLLM())
        mod = replace(settings, SUMMARY_WINDOW_HOURS=1.0)
        with patch("services.summary_memory.settings", mod):
            rows = await memory.get_window_messages(-100)
        assert [r["text"] for r in rows] == ["внутри"]


class TestSearchLongTerm:
    @pytest.mark.asyncio
    async def test_phrase_search(self, db):
        await _save(db, -100, "кто-то говорил про ракету вчера", 1000)
        await _save(db, -100, "совсем другое сообщение", 1001)
        memory = MemoryManager(db, FakeLLM())
        rows = await memory.search_long_term(-100, ["ракет"], 10)
        assert [r["text"] for r in rows] == ["кто-то говорил про ракету вчера"]

    @pytest.mark.asyncio
    async def test_no_keywords_returns_empty(self, db):
        memory = MemoryManager(db, FakeLLM())
        rows = await memory.search_long_term(-100, [], 10)
        assert rows == []

    @pytest.mark.asyncio
    async def test_chat_isolation(self, db):
        await _save(db, -100, "секрет чата сто", 1000)
        await _save(db, -200, "тот же секрет", 1001)
        memory = MemoryManager(db, FakeLLM())
        rows = await memory.search_long_term(-100, ["секрет"], 10)
        assert len(rows) == 1
        assert rows[0]["text"] == "секрет чата сто"


class TestVectorSearchFallback:
    @pytest.mark.asyncio
    async def test_vec_unavailable_uses_fts(self, db):
        await db.save_archive_fact(-100, "старый факт про дроны", 1)
        await db.save_archive_fact(-100, "другой факт", 2)
        llm = FakeLLM()
        memory = MemoryManager(db, llm)
        memory._vec_available = False
        facts = await memory.vector_search(-100, "дроны", 10)
        assert facts == ["старый факт про дроны"]
        assert llm.embed_calls == 0  # LLM не дёргался

    @pytest.mark.asyncio
    async def test_embed_fails_uses_fts(self, db):
        await db.save_archive_fact(-100, "факт про полёты", 1)
        memory = MemoryManager(db, FakeLLM(fail_embed=True))
        memory._vec_available = True
        facts = await memory.vector_search(-100, "полёт", 10)
        assert facts == ["факт про полёты"]

    @pytest.mark.asyncio
    async def test_vec_available_embed_success_but_no_table(self, db):
        # vec_available=True, но vec0-таблицы нет → KNN падает → FTS5
        await db.save_archive_fact(-100, "факт-спасение", 1)
        memory = MemoryManager(db, FakeLLM())
        memory._vec_available = True
        facts = await memory.vector_search(-100, "спасение", 10)
        assert facts == ["факт-спасение"]


class TestVectorSearchKnn:
    @pytest.mark.asyncio
    async def test_knn_search_with_real_extension(self, db):
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FakeLLM())
        ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded")
        f1 = await db.save_archive_fact(-100, "близкий факт", 1)
        f2 = await db.save_archive_fact(-200, "чужой факт", 2)
        await memory._save_archive_embedding(-100, f1, "близкий факт")
        await memory._save_archive_embedding(-200, f2, "чужой факт")
        facts = await memory.vector_search(-100, "запрос", 5)
        assert facts == ["близкий факт"]


class TestCompressAndPurge:
    @pytest.mark.asyncio
    async def test_compress_saves_facts_and_purges_raw(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое сообщение про войну", old, author="вася")
        await _save(db, -100, "ещё старое", old + 1, author="петя")
        await _save(db, -100, "свежее", int(time.time()), author="вася")
        memory = MemoryManager(db, FakeLLM(facts="факт про войну\nфакт два"))
        memory._vec_available = False
        await memory.compress_and_purge(-100)

        facts = await db.search_archive_fts(-100, '"факт"', 10)
        assert "факт про войну" in facts
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 100)
        assert [r["text"] for r in raw] == ["свежее"]

    @pytest.mark.asyncio
    async def test_compress_llm_error_keeps_raw(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старьё", old)
        memory = MemoryManager(db, FakeLLM(fail_generate=True))
        await memory.compress_and_purge(-100)
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 100)
        assert [r["text"] for r in raw] == ["старьё"]

    @pytest.mark.asyncio
    async def test_compress_empty_facts_keeps_raw(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старьё", old)
        memory = MemoryManager(db, FakeLLM(facts="   \n  "))
        await memory.compress_and_purge(-100)
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 100)
        assert [r["text"] for r in raw] == ["старьё"]

    @pytest.mark.asyncio
    async def test_compress_caps_facts_at_10(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое", old)
        facts = "\n".join(f"факт {i}" for i in range(25))
        memory = MemoryManager(db, FakeLLM(facts=facts))
        await memory.compress_and_purge(-100)
        stored = await db.search_archive_fts(-100, '"факт"', 100)
        assert len(stored) == 10

    @pytest.mark.asyncio
    async def test_archive_retention_90d(self, db):
        old_fact_ts = int(time.time()) - 100 * 86400
        fresh_fact_ts = int(time.time())
        await db.save_archive_fact(-100, "древний факт", old_fact_ts)
        await db.save_archive_fact(-100, "свежий факт", fresh_fact_ts)
        memory = MemoryManager(db, FakeLLM())
        await memory.compress_and_purge(-100)
        remaining = await db.search_archive_fts(-100, '"факт"', 10)
        assert remaining == ["свежий факт"]

    @pytest.mark.asyncio
    async def test_vec_embed_failure_fact_stays_in_fts(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старьё про войну", old)
        memory = MemoryManager(db, FakeLLM(facts="сжатый факт", fail_embed=True))
        memory._vec_available = True
        await memory.compress_and_purge(-100)
        facts = await db.search_archive_fts(-100, '"факт"', 10)
        assert "сжатый факт" in facts
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 100)
        assert raw == []

    @pytest.mark.asyncio
    async def test_compress_batches(self, db):
        old = int(time.time()) - 40 * 86400
        for i in range(25):
            await _save(db, -100, f"старое {i}", old + i)
        memory = MemoryManager(db, FakeLLM(facts="факт"))
        mod = replace(settings, SUMMARY_COMPRESS_BATCH=10)
        with patch("services.summary_memory.settings", mod):
            await memory.compress_and_purge(-100)
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 1000)
        assert raw == []

    @pytest.mark.asyncio
    async def test_batch_failure_keeps_unprocessed(self, db):
        old = int(time.time()) - 40 * 86400
        for i in range(15):
            await _save(db, -100, f"старое {i}", old + i)

        class FailingLLM:
            def __init__(self):
                self.calls = 0

            async def generate(self, messages):
                self.calls += 1
                if self.calls > 1:
                    raise LLMError("второй раз упал")
                return "факт"

            async def embed(self, texts):
                raise LLMError("no")

        memory = MemoryManager(db, FailingLLM())
        mod = replace(settings, SUMMARY_COMPRESS_BATCH=10)
        with patch("services.summary_memory.settings", mod):
            await memory.compress_and_purge(-100)
        # первая пачка (10) сжата и удалена, вторая (5) не тронута после ошибки
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 1000)
        assert len(raw) == 5
        assert [r["text"] for r in raw] == [f"старое {i}" for i in range(10, 15)]

    @pytest.mark.asyncio
    async def test_vec_purge_removes_vectors(self, db):
        """QA (T-188-D): vec0 purge uses documented rowid IN form; vectors removed."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FakeLLM())
        ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded")
        old = int(time.time()) - 100 * 86400
        fact_id = await db.save_archive_fact(-100, "древний факт", old)
        await memory._save_archive_embedding(-100, fact_id, "древний факт")
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM smart_archive")
        row = await cursor.fetchone()
        assert row["c"] == 1
        await memory._purge_archive(-100)
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM smart_archive")
        row = await cursor.fetchone()
        assert row["c"] == 0
        facts = await db.search_archive_fts(-100, '"древний"', 10)
        assert facts == []
