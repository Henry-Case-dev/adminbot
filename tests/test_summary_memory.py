"""Tests for services/summary_memory.py (T-176/T-177/T-179, Section 33.5)."""
import asyncio
import sqlite3
import time
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from config.settings import settings
from services.database import DatabaseService
from services.llm_client import LLMError
from services.summary_memory import (
    MemoryManager,
    _build_batch_text,
    build_fts_query,
)
from services.summary_prompts import EXTRACT_PROMPT


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
                 fail_embed=False, extract_response="[]"):
        self.facts = facts
        self.vectors = vectors
        self.fail_generate = fail_generate
        self.fail_embed = fail_embed
        self.extract_response = extract_response
        self.generate_calls = 0
        self.embed_calls = 0

    async def generate(self, messages):
        self.generate_calls += 1
        if self.fail_generate:
            raise LLMError("api упал")
        if messages[0]["content"] == EXTRACT_PROMPT:
            return self.extract_response
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


# ── Epic 28 (T-215): forward-маркировка в batch-тексте L3/GraphRAG ──

class TestBuildBatchTextForward:
    def test_forward_with_source(self):
        batch = [
            {
                "author_name": "оля",
                "text": "текст",
                "is_forward": 1,
                "forward_source": "Канал X",
            }
        ]
        assert _build_batch_text(batch) == '[оля (репост из "Канал X")]: текст'

    def test_forward_without_source(self):
        batch = [
            {"author_name": "оля", "text": "текст", "is_forward": 1, "forward_source": ""}
        ]
        assert _build_batch_text(batch) == "[оля (репост)]: текст"

    def test_plain_row_old_format_byte_for_byte(self):
        batch = [{"author_name": "оля", "text": "текст"}]
        assert _build_batch_text(batch) == "[оля]: текст"

    def test_skip_empty_still_works(self):
        batch = [
            {"author_name": "оля", "text": "", "is_forward": 1, "forward_source": "X"},
            {"author_name": "петя", "text": "текст"},
        ]
        assert _build_batch_text(batch, skip_empty=True) == "[петя]: текст"

    def test_inner_quotes_replaced(self):
        batch = [
            {
                "author_name": "оля",
                "text": "т",
                "is_forward": 1,
                "forward_source": 'Канал "X"',
            }
        ]
        assert _build_batch_text(batch) == '[оля (репост из "Канал \'X\'")]: т'


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


# ── Epic 28 (T-216): векторное автолечение ──────────────────

class TestSelfHeal:
    @pytest.mark.asyncio
    async def test_broken_extension_zero_probe_calls(self, db, monkeypatch):
        """Расширение не загрузилось → пробный embed НЕ вызывается (0 вызовов)."""
        monkeypatch.setattr("sqlite_vec.loadable_path", lambda: "/nonexistent/vec0.dll")
        llm = FakeLLM()
        memory = MemoryManager(db, llm)
        result = await memory.initialize()
        assert result is False
        assert memory._vec_dim is None
        assert llm.embed_calls == 0

    @pytest.mark.asyncio
    async def test_probe_embed_failure_falls_back_without_crash(self, db, caplog, monkeypatch):
        """Probe падает (LLM-ошибка) → старт ок, FTS5, WARNING."""
        import logging

        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)

        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FakeLLM(fail_embed=True))
        with caplog.at_level(logging.WARNING):
            ok = await memory.initialize()
        assert ok is False
        assert memory._vec_dim is None
        assert any("probe embed failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_actual_dim_differs_from_settings_warns(self, db, caplog):
        """actual_dim(3) != settings.EMBEDDING_DIM(768) → WARNING, таблица создана с actual."""
        import logging

        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FakeLLM(vectors=[[0.1] * 3]))
        with caplog.at_level(logging.WARNING):
            ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded here")
        assert memory._vec_dim == 3
        assert memory.vec_available is True
        assert any("EMBEDDING_DIM" in r.message for r in caplog.records)
        cursor = await db.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='smart_archive'"
        )
        row = await cursor.fetchone()
        assert "float[3]" in row["sql"]

    @pytest.mark.asyncio
    async def test_dimension_mismatch_drops_and_recreates_facts_kept(self, db):
        """stored 768 vs actual 3072 → DROP smart_archive + пересоздание; факты целы (D78)."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        first = MemoryManager(db, FakeLLM(vectors=[[0.1] * 768]))
        if not await first.initialize():
            pytest.skip("sqlite-vec extension could not be loaded here")
        assert first._vec_dim == 768
        fact_id = await db.save_archive_fact(-100, "факт сохранился", 1)
        await first._save_archive_embedding(-100, fact_id, "факт сохранился")

        second = MemoryManager(db, FakeLLM(vectors=[[0.1] * 3072]))
        ok = await second.initialize()
        assert ok is True
        assert second._vec_dim == 3072
        cursor = await db.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='smart_archive'"
        )
        row = await cursor.fetchone()
        assert "float[3072]" in row["sql"]
        facts = await db.search_archive_fts(-100, '"факт"', 10)
        assert facts == ["факт сохранился"]
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM smart_archive_facts")
        row = await cursor.fetchone()
        assert row["c"] == 1

    @pytest.mark.asyncio
    async def test_empty_knn_falls_back_to_fts(self, db):
        """Пустой KNN-результат → FTS5-фоллбек (не пустой return)."""
        await db.save_archive_fact(-100, "факт из фтс", 1)
        memory = MemoryManager(db, FakeLLM())
        memory._vec_available = True
        memory._search_archive_knn = AsyncMock(return_value=[])
        facts = await memory.vector_search(-100, "фтс", 10)
        assert facts == ["факт из фтс"]
        memory._search_archive_knn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_insert_dimension_mismatch_disables_vec(self, db, caplog):
        """Рантайм-mismatch на INSERT → _vec_available=False (без живого DROP) + ERROR один раз."""
        import logging

        memory = MemoryManager(db, FakeLLM())
        memory._vec_available = True

        async def boom(*args, **kwargs):
            raise sqlite3.OperationalError("Dimension mismatch")

        memory.db.db.execute = boom
        with caplog.at_level(logging.ERROR):
            await memory._save_archive_embedding(-100, 1, "факт")
        assert memory._vec_available is False
        assert any("dimension mismatch on INSERT" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_insert_other_error_keeps_vec(self, db, caplog, monkeypatch):
        """Обычная ошибка embed/INSERT не гасит vec (факт остаётся в FTS5)."""
        import logging

        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)

        memory = MemoryManager(db, FakeLLM(fail_embed=True))
        memory._vec_available = True
        with caplog.at_level(logging.WARNING):
            await memory._save_archive_embedding(-100, 1, "факт")
        assert memory._vec_available is True
        assert any("fact stays in FTS5 only" in r.message for r in caplog.records)


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


class TestCountMentions:
    """Bugfix 04.09.2026 (Часть 2, AC-3.6): count_mentions — точный счётчик
    FTS-совпадений + диапазон дат (для query_chat_memory)."""

    @pytest.mark.asyncio
    async def test_count_with_dates(self, db):
        await _save(db, -100, "бензин подорожал вчера", 1000)
        await _save(db, -100, "опять бензин", 3000)
        await _save(db, -100, "ни слова про бензин не скажу", 2000)
        memory = MemoryManager(db, FakeLLM())
        stats = await memory.count_mentions(-100, ["бензин"])
        assert stats == {"count": 3, "first_seen": 1000, "last_seen": 3000}

    @pytest.mark.asyncio
    async def test_count_respects_since_window(self, db):
        await _save(db, -100, "бензин старый", 1000)
        await _save(db, -100, "бензин свежий", 3000)
        memory = MemoryManager(db, FakeLLM())
        stats = await memory.count_mentions(-100, ["бензин"], since_ts=2000)
        assert stats["count"] == 1
        assert stats["first_seen"] == 3000

    @pytest.mark.asyncio
    async def test_no_keywords_returns_none(self, db):
        memory = MemoryManager(db, FakeLLM())
        assert await memory.count_mentions(-100, []) is None

    @pytest.mark.asyncio
    async def test_no_matches_zero(self, db):
        await _save(db, -100, "про другое", 1000)
        memory = MemoryManager(db, FakeLLM())
        stats = await memory.count_mentions(-100, ["небывальщина"])
        assert stats["count"] == 0

    @pytest.mark.asyncio
    async def test_chat_isolation(self, db):
        await _save(db, -100, "бензин тут", 1000)
        await _save(db, -200, "бензин чужой", 1001)
        memory = MemoryManager(db, FakeLLM())
        stats = await memory.count_mentions(-100, ["бензин"])
        assert stats["count"] == 1


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
    async def test_embed_fails_uses_fts(self, db, monkeypatch):
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
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
    async def test_vec_embed_failure_fact_stays_in_fts(self, db, monkeypatch):
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
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
                if messages[0]["content"] == EXTRACT_PROMPT:
                    return "[]"      # Epic 26: extraction call succeeds (graph stays empty)
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
    async def test_compress_and_purge_purges_expired_graph_facts(self, db):
        """Epic 46 (55.1 #5, D175): piggyback — истёкшие GraphRAG v2-факты
        удаляются в хвосте compress_and_purge; живые (expires_at NULL) остаются."""
        expired_id = await db.insert_graph_fact(
            -100, "истёкший факт", "search_fact", int(time.time()) - 100)
        live_id = await db.insert_graph_fact(
            -100, "живой факт", "chat_history", None)
        memory = MemoryManager(db, FakeLLM())
        await memory.compress_and_purge(-100)
        texts = await db.get_graph_fact_texts([expired_id, live_id])
        assert [(origin, fact) for origin, fact, _ in texts] == [
            ("chat_history", "живой факт")]

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


# ── Epic 46 (Section 55.8, T-366-A #22-25) ────────────────────────


class FlakyLLM:
    """Embed падает первые fail_calls раз, затем отвечает (403-эпизод, 55.8)."""

    def __init__(self, fail_calls=3, dim=None):
        self.fail_calls = fail_calls
        self.calls = 0
        self.dim = dim or settings.EMBEDDING_DIM
        self.generate_calls = 0

    async def embed(self, texts):
        self.calls += 1
        if self.calls <= self.fail_calls:
            raise LLMError("403 эмбеддингов")
        return [[0.1] * self.dim for _ in texts]

    async def generate(self, messages):
        self.generate_calls += 1
        return "[]"


class TestVecOffReasonSplit:
    @pytest.mark.asyncio
    async def test_extension_fail_sets_reason_extension(self, db, monkeypatch, caplog):
        """#22: расширение не загрузилось → reason=="extension" + лог
        «sqlite-vec unavailable» (НЕ «probe embed failed»)."""
        import logging

        monkeypatch.setattr("sqlite_vec.loadable_path", lambda: "/nonexistent/vec0.dll")
        memory = MemoryManager(db, FakeLLM())
        with caplog.at_level(logging.WARNING):
            ok = await memory.initialize()
        assert ok is False
        assert memory._vec_off_reason == "extension"
        assert any("sqlite-vec unavailable" in r.message for r in caplog.records)
        assert not any("probe embed failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_probe_fail_sets_reason_embed_split_log(self, db, monkeypatch, caplog):
        """#22: probe упал → reason=="embed" + лог «probe embed failed»
        (НЕ «sqlite-vec unavailable»)."""
        import logging

        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
        memory = MemoryManager(db, FakeLLM(fail_embed=True))
        with caplog.at_level(logging.WARNING):
            ok = await memory.initialize()
        assert ok is False
        assert memory._vec_off_reason == "embed"
        assert any("probe embed failed" in r.message for r in caplog.records)
        assert not any("sqlite-vec unavailable" in r.message for r in caplog.records)


class TestEmbedRetries:
    @pytest.mark.asyncio
    async def test_embed_retries_three_attempts(self, db, monkeypatch):
        """#23: FakeLLM падает 2 раза → 3-я попытка ок (backoff=0)."""
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
        llm = FlakyLLM(fail_calls=2)
        memory = MemoryManager(db, llm)
        vectors = await memory._embed(["текст"])
        assert vectors[0] == [0.1] * settings.EMBEDDING_DIM
        assert llm.calls == 3

    @pytest.mark.asyncio
    async def test_embed_exhausted_retries_raises(self, db, monkeypatch):
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
        llm = FlakyLLM(fail_calls=99)
        memory = MemoryManager(db, llm)
        with pytest.raises(LLMError):
            await memory._embed(["текст"])
        assert llm.calls == 3


class TestVecReactivation:
    @pytest.mark.asyncio
    async def test_reactivation_after_embed_recovery(self, db, monkeypatch, caplog):
        """#24: probe-фейл → FTS; интервал=0 → re-probe ок → vec reactivated
        (лог) + KNN работает."""
        import logging

        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
        monkeypatch.setattr("services.summary_memory._VEC_REACTIVATE_INTERVAL", 0.0)

        llm = FlakyLLM(fail_calls=3)          # первый probe исчерпывает 3 попытки
        memory = MemoryManager(db, llm)
        ok = await memory.initialize()
        assert ok is False
        assert memory._vec_off_reason == "embed"

        with caplog.at_level(logging.INFO):
            reactivated = await memory._ensure_vec_retry()
        assert reactivated is True
        assert memory._vec_available is True
        assert memory._vec_off_reason is None
        assert any("vec reactivated after embed recovery" in r.message
                   for r in caplog.records)

        # KNN работает после реактивации
        fact_id = await db.save_archive_fact(-100, "факт про дроны", 1)
        await memory._save_archive_embedding(-100, fact_id, "факт про дроны")
        facts = await memory.vector_search(-100, "дроны", 5)
        assert facts == ["факт про дроны"]

    @pytest.mark.asyncio
    async def test_reactivation_interval_not_elapsed_no_probe(self, db, monkeypatch):
        """#24: интервал не прошёл → re-probe НЕ выполняется (остаётся FTS)."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
        monkeypatch.setattr("services.summary_memory._VEC_REACTIVATE_INTERVAL", 600.0)
        llm = FlakyLLM(fail_calls=99)
        memory = MemoryManager(db, llm)
        await memory.initialize()
        assert memory._vec_off_reason == "embed"
        calls_before = llm.calls
        assert await memory._ensure_vec_retry() is False
        assert llm.calls == calls_before          # новых embed-вызовов нет


class TestBackfill:
    @pytest.mark.asyncio
    async def test_backfill_reembeds_and_is_idempotent(self, db):
        """#25: 2 факта без vec → re-embedded; повторный вызов → 0."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FakeLLM())
        ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded")
        await asyncio.sleep(0.05)     # фоновый backfill из initialize завершился (пусто)
        await db.save_archive_fact(-100, "факт один", 1)
        await db.save_archive_fact(-100, "факт два", 2)
        assert await memory.backfill_archive_vectors() == 2
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM smart_archive")
        row = await cursor.fetchone()
        assert row["c"] == 2
        assert await memory.backfill_archive_vectors() == 0

    @pytest.mark.asyncio
    async def test_backfill_embed_fail_deferred_returns_zero(self, db, monkeypatch):
        """#25: embed-фейл внутри backfill → 0, НЕ бросает."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
        memory = MemoryManager(db, FakeLLM())
        ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded")
        await asyncio.sleep(0.05)
        await db.save_archive_fact(-100, "факт один", 1)
        memory.llm = FakeLLM(fail_embed=True)
        assert await memory.backfill_archive_vectors() == 0

    @pytest.mark.asyncio
    async def test_backfill_vec_unavailable_returns_zero(self, db):
        memory = MemoryManager(db, FakeLLM())
        memory._vec_available = False
        assert await memory.backfill_archive_vectors() == 0


class TestFireAndForget:
    @pytest.mark.asyncio
    async def test_background_failure_logged_not_raised(self, caplog):
        """R46-5 (55.5): падение фонового факта НЕ всплывает (тихий WARNING)."""
        import logging

        from services.summary_memory import fire_and_forget

        async def boom():
            raise ValueError("фон упал")

        with caplog.at_level(logging.WARNING):
            fire_and_forget(boom(), "test-tag")
            for _ in range(5):
                await asyncio.sleep(0)
        assert any("[graphrag hook] test-tag failed" in r.message
                   for r in caplog.records)


# ── Epic 47 (Section 56.5/56.7, D188/D190; 56.8 #15-19) ─────────────


class MemorizeRetryLLM:
    """generate падает LLMError `fail_times` раз, затем отдаёт JSON-факты."""

    def __init__(self, fail_times=0, facts='[{"subject":"А","predicate":"Б","object":"В"}]',
                 raise_type=LLMError):
        self.fail_times = fail_times
        self.facts = facts
        self.raise_type = raise_type
        self.generate_calls = 0

    async def generate(self, messages):
        self.generate_calls += 1
        if self.generate_calls <= self.fail_times:
            raise self.raise_type("api упал")
        return self.facts

    async def embed(self, texts):
        return [[0.1] * settings.EMBEDDING_DIM for _ in texts]


class TestMemorizeResilience:
    @pytest.mark.asyncio
    async def test_extract_retry_then_success_saves_batch(self, db, caplog):
        """56.8 #15: LLMError 1-й → успех 2-й → факты+узлы сохранены,
        generate_calls==2, INFO «extract retry»."""
        import logging

        llm = MemorizeRetryLLM(fail_times=1)
        memory = MemoryManager(db, llm)
        mod = replace(settings, GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF=0)
        with patch("services.summary_memory.settings", mod):
            with caplog.at_level(logging.INFO):
                await memory.memorize_facts(1, "какой-то текст для фактов", "chat_history")
        assert llm.generate_calls == 2
        assert any("graphrag memorize: extract retry" in r.message
                   for r in caplog.records)
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        row = await cursor.fetchone()
        assert row["c"] == 1
        assert all(r.levelno < logging.ERROR for r in caplog.records)

    @pytest.mark.asyncio
    async def test_extract_llm_error_exhausted_warning_no_error(self, db, caplog):
        """56.8 #16: LLMError ×3 → WARNING «graphrag memorize: LLM failed»,
        0 строк, caplog БЕЗ ERROR, без raise (без traceback-шторма)."""
        import logging

        llm = MemorizeRetryLLM(fail_times=99)
        memory = MemoryManager(db, llm)
        mod = replace(settings, GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF=0)
        with patch("services.summary_memory.settings", mod):
            with caplog.at_level(logging.WARNING):
                await memory.memorize_facts(1, "какой-то текст", "chat_history")   # без raise
        assert llm.generate_calls == 3
        assert any("graphrag memorize: LLM failed" in r.message for r in caplog.records)
        assert all(r.levelno < logging.ERROR for r in caplog.records)
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        row = await cursor.fetchone()
        assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_extract_non_llm_exception_logs_error(self, db, caplog):
        """56.8 #17: RuntimeError экстракции → ERROR logger.exception
        («graphrag memorize: unexpected failure»), без raise из memorize_facts."""
        import logging

        llm = MemorizeRetryLLM(fail_times=1, raise_type=RuntimeError)
        memory = MemoryManager(db, llm)
        mod = replace(settings, GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF=0)
        with patch("services.summary_memory.settings", mod):
            with caplog.at_level(logging.ERROR):
                await memory.memorize_facts(1, "какой-то текст", "chat_history")
        assert any("graphrag memorize: unexpected failure" in r.message
                   for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)
        assert llm.generate_calls == 1            # НЕ ретраится (только LLMError)

    @pytest.mark.asyncio
    async def test_per_fact_save_failure_skipped_others_saved(self, db, caplog):
        """56.8 #18: сбой сохранения факта №2 (фейковый БД) → факт №1 сохранён,
        WARNING «save skipped», INFO saved=1 skipped=1."""
        import logging

        llm = MemorizeRetryLLM(
            facts='[{"subject":"А","predicate":"Б","object":"В"},'
                  '{"subject":"Г","predicate":"Д","object":"Е"}]')
        memory = MemoryManager(db, llm)
        original = memory.db.upsert_node
        state = {"n": 0}

        async def flaky_upsert(*args, **kwargs):
            state["n"] += 1
            if state["n"] == 3:                    # subject факта №2
                raise sqlite3.OperationalError("db сбой")
            return await original(*args, **kwargs)

        memory.db.upsert_node = flaky_upsert
        with caplog.at_level(logging.INFO):
            await memory.memorize_facts(1, "какой-то текст", "chat_history")
        assert any("graphrag memorize: fact #2 save skipped" in r.message
                   for r in caplog.records)
        assert any("graphrag memorize: saved=1 skipped=1" in r.message
                   for r in caplog.records)
        texts = await db.get_graph_fact_texts(
            [row["id"] for row in await (await db.db.execute(
                "SELECT id FROM graph_facts")).fetchall()])
        assert any("а б в" in fact for _, fact, _ in texts)

    @pytest.mark.asyncio
    async def test_fire_and_forget_llm_error_warning_without_exc_info(self, caplog):
        """56.8 #19a: fire_and_forget: LLMError → WARNING БЕЗ exc_info."""
        import logging

        from services.summary_memory import fire_and_forget

        async def boom():
            raise LLMError("api упал")

        with caplog.at_level(logging.WARNING):
            fire_and_forget(boom(), "llm-tag")
            for _ in range(5):
                await asyncio.sleep(0)
        match = [r for r in caplog.records
                 if r.message.startswith("[graphrag hook] llm-tag failed")]
        assert match and all(r.exc_info is None for r in match)

    @pytest.mark.asyncio
    async def test_fire_and_forget_generic_error_warning_with_exc_info(self, caplog):
        """56.8 #19b: fire_and_forget: RuntimeError → WARNING + exc_info."""
        import logging

        from services.summary_memory import fire_and_forget

        async def boom():
            raise RuntimeError("фон упал")

        with caplog.at_level(logging.WARNING):
            fire_and_forget(boom(), "gen-tag")
            for _ in range(5):
                await asyncio.sleep(0)
        match = [r for r in caplog.records
                 if r.message == "[graphrag hook] gen-tag failed"]
        assert match and any(r.exc_info for r in match)


class TestEmbeddingCache:
    """Epic 60 (64.4, T-465): embedding_cache — батч-лукап SHA-256 → miss →
    API → write-back; TTL; dim-guard; fail-open."""

    @pytest.mark.asyncio
    async def test_repeat_text_hits_cache_single_api_call(self, db):
        """64.9 #5: два одинаковых запроса → llm.embed вызван 1 раз."""
        llm = FakeLLM()
        memory = MemoryManager(db, llm)
        first = await memory._embed(["текст раз", "текст два"])
        second = await memory._embed(["текст раз", "текст два"])
        assert llm.embed_calls == 1
        # Epic 64: кэш хранит float16 BLOB → чтение даёт half-float точность
        # (0.1 → 0.099975…); для cosine-поиска разница ~1e-3 незначима.
        flat_a = [x for vec in first for x in vec]
        flat_b = [x for vec in second for x in vec]
        assert len(flat_a) == len(flat_b)
        assert all(abs(a - b) < 1e-2 for a, b in zip(flat_a, flat_b))
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM embedding_cache")
        assert (await cursor.fetchone())["c"] == 2

    @pytest.mark.asyncio
    async def test_partial_hit_only_miss_to_api(self, db):
        llm = FakeLLM()
        memory = MemoryManager(db, llm)
        await memory._embed(["текст раз"])
        assert llm.embed_calls == 1
        vectors = await memory._embed(["текст раз", "текст два"])
        assert llm.embed_calls == 2              # только miss ушёл в API
        assert len(vectors) == 2
        assert all(len(vector) == settings.EMBEDDING_DIM for vector in vectors)

    @pytest.mark.asyncio
    async def test_ttl_expired_refetches(self, db):
        """64.9 #5: TTL-истёкшая кэш-строка → повторный вызов API."""
        llm = FakeLLM()
        memory = MemoryManager(db, llm)
        await memory._embed(["текст раз"])
        assert llm.embed_calls == 1
        await db.db.execute(
            "UPDATE embedding_cache SET last_used_at = last_used_at - 100 * 86400")
        await db.db.commit()
        await memory._embed(["текст раз"])
        assert llm.embed_calls == 2              # строка протухла → API

    @pytest.mark.asyncio
    async def test_dim_guard_miss_on_shift(self, db):
        """64.9 #6: dim-сдвиг → кэш не используется (miss → API → перезапись)."""
        llm = FakeLLM()
        memory = MemoryManager(db, llm)
        await memory._embed(["текст раз"])
        assert llm.embed_calls == 1
        memory._vec_dim = 768                     # dim-сдвиг (55.8)
        await memory._embed(["текст раз"])
        assert llm.embed_calls == 2
        cursor = await db.db.execute(
            "SELECT dim FROM embedding_cache WHERE text_hash IN "
            "(SELECT text_hash FROM embedding_cache LIMIT 1)")
        row = await cursor.fetchone()
        assert row["dim"] == settings.EMBEDDING_DIM   # фактический dim вектора

    @pytest.mark.asyncio
    async def test_cache_failure_falls_back_to_api(self, db, monkeypatch, caplog):
        """64.4: ошибки БД кэша → WARNING → обычный вызов API."""
        import logging

        llm = FakeLLM()
        memory = MemoryManager(db, llm)

        async def boom(*args, **kwargs):
            raise sqlite3.OperationalError("кэш сломался")

        monkeypatch.setattr(memory.db.db, "execute", boom)
        with caplog.at_level(logging.WARNING):
            vectors = await memory._embed(["текст раз"])
        assert llm.embed_calls == 1
        assert vectors[0] == [0.1] * settings.EMBEDDING_DIM

    @pytest.mark.asyncio
    async def test_lru_cap_evicts_oldest(self, db):
        """LRU-cap: EMBED_CACHE_MAX_ROWS=2 → третья запись вытесняет старейшую."""
        mod = replace(settings, EMBED_CACHE_MAX_ROWS=2)
        with patch("services.summary_memory.settings", mod):
            llm = FakeLLM()
            memory = MemoryManager(db, llm)
            await memory._embed(["текст а"])
            await memory._embed(["текст б"])
            await memory._embed(["текст в"])
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM embedding_cache")
        assert (await cursor.fetchone())["c"] == 2

    @pytest.mark.asyncio
    async def test_cache_disabled_direct_api(self, db):
        """EMBED_CACHE_ENABLED=false → каждый вызов в API (старое поведение)."""
        mod = replace(settings, EMBED_CACHE_ENABLED=False)
        with patch("services.summary_memory.settings", mod):
            llm = FakeLLM()
            memory = MemoryManager(db, llm)
            await memory._embed(["текст раз"])
            await memory._embed(["текст раз"])
            assert llm.embed_calls == 2
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM embedding_cache")
        assert (await cursor.fetchone())["c"] == 0


# ── Раунд 3 (3.7/C2, T-697): TTL bot_direct_reply — миграция PG-дефолта и
# backfill существующих NULL-фактов (идемпотентный).

class TestDirectReplyTtlMigration:
    """migrate_direct_reply_ttl_default (FR-C2): PG-NULL/пусто → 30 (set
    вызван); 0/число → не тронут; ключ отсутствует / PG down → skip."""

    class _Cache:
        def __init__(self, value="__missing__", pg=True):
            self._value = value
            self.pg_available = pg
            self.calls = []

        def get(self, key):
            if self._value == "__missing__":
                return None
            return self._value

        async def set(self, key, value, category):
            self.calls.append((key, value, category))

    @pytest.mark.asyncio
    async def test_null_value_set_to_30(self):
        from services.summary_memory import migrate_direct_reply_ttl_default
        cache = self._Cache(value=None)
        assert await migrate_direct_reply_ttl_default(cache) is True
        assert cache.calls == [
            ("limits.chat_direct_reply_ttl_days", 30, "limits")]

    @pytest.mark.asyncio
    async def test_empty_string_value_set_to_30(self):
        from services.summary_memory import migrate_direct_reply_ttl_default
        cache = self._Cache(value="")
        assert await migrate_direct_reply_ttl_default(cache) is True

    @pytest.mark.asyncio
    async def test_zero_and_number_untouched(self):
        from services.summary_memory import migrate_direct_reply_ttl_default
        for value in (0, 7, "7"):
            cache = self._Cache(value=value)
            assert await migrate_direct_reply_ttl_default(cache) is False
            assert cache.calls == []

    @pytest.mark.asyncio
    async def test_missing_key_and_pg_down_skip(self):
        from services.summary_memory import migrate_direct_reply_ttl_default
        # PG down → skip (R6); отсутствующий ключ неразличим с NULL —
        # миграция ставит 30 (сид сделал бы то же самое)
        assert await migrate_direct_reply_ttl_default(
            self._Cache(value=None, pg=False)) is False
        assert await migrate_direct_reply_ttl_default(
            self._Cache(value="__missing__")) is True


class TestDirectReplyTtlBackfill:
    @pytest.mark.asyncio
    async def test_backfill_null_rows_gets_expires_at(self, db, monkeypatch):
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        for origin, created in (
                ("bot_direct_reply", now - 40 * 86400),     # старше 29д → created+30д
                ("bot_direct_reply", now - 5 * 86400),      # свежий → min(..., now)
                ("chat_history", now),                       # не трогаем
        ):
            await db.db.execute(
                "INSERT INTO graph_facts (chat_id, fact, origin, expires_at, "
                "created_at, weight, status, last_confirmed_at) "
                "VALUES (-100, ?, ?, NULL, ?, 0.7, 'confirmed', ?)",
                (f"факт {origin}", origin, created, created))
        await db.db.commit()
        memory = MemoryManager(db, FakeLLM(extract_response="[]"))
        rows = await memory.backfill_direct_reply_ttl()
        assert rows == 2
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts WHERE origin = 'bot_direct_reply' "
            "ORDER BY created_at")
        rows_out = [r["expires_at"] for r in await cursor.fetchall()]
        # expires_at = min(created_at + 30д, now): старый → created+30д; свежий → now
        assert rows_out[0] == (now - 40 * 86400) + 30 * 86400
        assert rows_out[1] == now
        # повторный запуск — no-op (NULL-строк больше нет)
        assert await memory.backfill_direct_reply_ttl() == 0

    @pytest.mark.asyncio
    async def test_backfill_zero_ttl_is_noop(self, db, monkeypatch):
        mod = replace(settings, CHAT_DIRECT_REPLY_TTL_DAYS=0)
        with patch("services.summary_memory.settings", mod):
            await db.db.execute(
                "INSERT INTO graph_facts (chat_id, fact, origin, expires_at, "
                "created_at) VALUES (-100, 'вечный', 'bot_direct_reply', NULL, "
                "1700000000)")
            await db.db.commit()
            memory = MemoryManager(db, FakeLLM(extract_response="[]"))
            assert await memory.backfill_direct_reply_ttl() == 0
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts WHERE origin = 'bot_direct_reply'")
        assert (await cursor.fetchone())["expires_at"] is None
