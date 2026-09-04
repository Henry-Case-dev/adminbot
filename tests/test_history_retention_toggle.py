"""Фаза 2 (T-757, D3 + T-755/T-756) — тумблер memory.infinite_retention.

(1) каталог/сид: REGISTRY memory.infinite_retention (bool, категория memory,
группа memory_infinite, env_name совпадает с settings-полем), SEED_CATEGORIES
включает memory, settings-дефолт False; (2) матрица ON/OFF: OFF — регресс
текущего поведения (TTL-факты удаляются); ON — purge_* возвращают 0, сырьё
не удаляется/не сжимается, extract-only работает (импортированные строки
import_key IS NOT NULL исключены из extract), archive не чистится, review:
merge-фазы работают, purge-фазы скипаются; (3) hot.get фолбэк False без кэша.
"""
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import settings
from services import hot_config as hot
from services import param_catalog as pc
from services.database import DatabaseService
from services.llm_client import LLMError
from services.memory_maintenance import MemoryMaintenanceService
from services.pg_db import SEED_CATEGORIES
from services.summary_memory import MemoryManager
from services.summary_prompts import EXTRACT_PROMPT

RETENTION_KEY = "memory.infinite_retention"


class _Cache:
    """Мини-кэш для hot.get (как в test_hot_migration)."""

    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


@pytest.fixture
def hot_cache():
    old = hot._cache
    holder = {}

    class _W:
        def set(self, data):
            hot.set_config_cache(_Cache(data))

    w = _W()
    w.set({})
    try:
        yield w
    finally:
        hot.set_config_cache(old)


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _FakeLLM:
    """Мини-LLM: generate отвечает на EXTRACT_PROMPT (валидные триплеты),
    на COMPRESS_PROMPT — пустые факты; embed падает (vec-путь не нужен)."""

    def __init__(self, extract_response=None):
        self.extract_calls = 0
        self.compress_calls = 0
        self.extract_response = extract_response or json.dumps(
            [{"subject": "петя", "subject_type": "user",
              "predicate": "спорил с", "object": "вася",
              "object_type": "user"}], ensure_ascii=False)

    async def generate(self, messages):
        if messages[0]["content"] == EXTRACT_PROMPT:
            self.extract_calls += 1
            return self.extract_response
        self.compress_calls += 1
        return "сжатый факт\nфакт два"

    async def embed(self, texts):
        raise LLMError("vec не нужен")


async def _save_message(db, chat_id, text, ts, author="кто-то",
                        import_key=None):
    """save_smart_message + прямой import_key (импортированные строки)."""
    row_id = await db.save_smart_message(1, chat_id, text, None, ts, "text",
                                         author)
    if import_key:
        await db.db.execute(
            "UPDATE smart_messages SET import_key = ? WHERE id = ?",
            (import_key, row_id))
        await db.db.commit()
    return row_id


def _old_ts(days=40):
    return int(time.time()) - days * 86400


# ── 1. Каталог/сид (T-755) ──────────────────────────────────────────────────

class TestCatalogSeed:
    def test_memory_key_in_registry(self):
        spec = pc.get("INFINITE_RETENTION")
        assert spec is not None
        assert spec.category == pc.CATEGORY_MEMORY == "memory"
        assert spec.type == "bool"
        assert spec.group == "memory_infinite"
        assert spec.env_name == "INFINITE_RETENTION"
        assert spec.settings_field == "INFINITE_RETENTION"
        assert spec.pg_id == "memory.infinite_retention"
        assert spec.pg_key == "memory.infinite_retention"
        assert "Бессрочное хранение памяти" in spec.title_ru
        assert spec.description.strip()
        by_key = pc.get_by_pg_key("memory.infinite_retention")
        assert by_key is spec
        # env_name обязателен для migrate_env_to_pg (нет None → os.environ.get)
        assert spec.env_name is not None

    def test_settings_default_false(self):
        assert settings.INFINITE_RETENTION is False

    def test_group_and_categories(self):
        group = pc.get_group("memory_infinite")
        assert group is not None
        assert group.category == "memory"
        assert group.title_ru == "Бессрочное хранение"
        assert pc.CATEGORY_MEMORY in pc.CATEGORIES
        assert pc.groups_by_category("memory") == [group]
        assert pc.settings_field_coverage() == (set(), set())

    def test_seed_categories_include_memory(self):
        assert pc.CATEGORY_MEMORY in SEED_CATEGORIES

    def test_hot_get_fallback_false_without_cache(self):
        # кэша нет → hot.get возвращает default (False)
        old = hot._cache
        hot.set_config_cache(None)
        try:
            assert hot.get(RETENTION_KEY, settings.INFINITE_RETENTION) is False
        finally:
            hot.set_config_cache(old)

    def test_hot_get_coerces_cache_value(self, hot_cache):
        hot_cache.set({RETENTION_KEY: "true"})      # строка → bool по каталогу
        assert hot.get(RETENTION_KEY, False) is True
        hot_cache.set({RETENTION_KEY: False})
        assert hot.get(RETENTION_KEY, True) is False


# ── 2. Гейты db-слоя G3-G5 (T-756) ──────────────────────────────────────────

class TestDatabaseGates:
    async def _seed_expired(self, db):
        expired = await db.insert_graph_fact(
            -100, "истёкший факт", "search_fact", _old_ts(days=100) - 1000)
        live = await db.insert_graph_fact(
            -100, "живой факт", "chat_history", None)
        return expired, live

    @pytest.mark.asyncio
    async def test_off_purges_expired(self, db):
        expired, live = await self._seed_expired(db)
        deleted = await db.purge_expired_graph_facts(-100)
        assert deleted == 1
        texts = await db.get_graph_fact_texts([expired, live])
        assert [t[1] for t in texts] == ["живой факт"]

    @pytest.mark.asyncio
    async def test_on_returns_zero_and_keeps(self, db, hot_cache):
        expired, live = await self._seed_expired(db)
        hot_cache.set({RETENTION_KEY: True})
        deleted = await db.purge_expired_graph_facts(-100)
        assert deleted == 0
        texts = await db.get_graph_fact_texts([expired, live])
        assert {t[1] for t in texts} == {"истёкший факт", "живой факт"}

    @pytest.mark.asyncio
    async def test_unconfirmed_and_trim_gates(self, db, hot_cache):
        now = int(time.time())
        old = _old_ts(days=120)  # старше retention: unconfirmed 14д и лог 90д              # старше retention 14 дней
        # OFF: регресс — unconfirmed старше retention выброшен, лог усечён
        await db.insert_graph_fact(-100, "неподтверждённый",
                                   "chat_history", None,
                                   status="unconfirmed")
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ? WHERE status='unconfirmed'",
            (old,))
        await db.log_fact_compression(-100, 1, "было", "стало", "test")
        await db.db.execute(
            "UPDATE graph_fact_compressions SET created_at = ?", (old,))
        await db.db.commit()
        assert await db.purge_unconfirmed_graph_facts(now, 14) == 1
        assert await db.trim_compression_log(now + 100, 90) == 1
        # ON: гейты G4/G5 возвращают 0, строки живы
        await db.insert_graph_fact(-100, "неподтверждённый 2",
                                   "chat_history", None,
                                   status="unconfirmed")
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ? WHERE status='unconfirmed'",
            (old,))
        await db.log_fact_compression(-100, 2, "было", "стало", "test")
        await db.db.execute(
            "UPDATE graph_fact_compressions SET created_at = ?", (old,))
        await db.db.commit()
        hot_cache.set({RETENTION_KEY: True})
        assert await db.purge_unconfirmed_graph_facts(now, 14) == 0
        assert await db.trim_compression_log(now + 100, 90) == 0
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE status='unconfirmed'")
        assert (await cursor.fetchone())["c"] == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_fact_compressions")
        assert (await cursor.fetchone())["c"] == 1


# ── 3. summary_memory: G1/G2 (T-756) ────────────────────────────────────────

class TestCompressAndPurgeToggle:
    @pytest.mark.asyncio
    async def test_off_compresses_and_deletes_raw(self, db):
        """OFF: ровно текущее поведение — сжатие → archive → DELETE сырья."""
        await _save_message(db, -100, "старьё про войну", _old_ts())
        memory = MemoryManager(db, _FakeLLM())
        memory._vec_available = False
        await memory.compress_and_purge(-100)
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 10)
        assert raw == []
        facts = await db.search_archive_fts(-100, '"факт"', 10)
        assert "сжатый факт" in facts
        assert "факт два" in facts

    @pytest.mark.asyncio
    async def test_on_keeps_raw_and_extracts_only(self, db, hot_cache):
        """ON: сырьё НЕ удаляется, smart_archive НЕ пополняется, граф
        пополняется (nodes/edges из extract), импортированные строки
        (import_key) в extract НЕ участвуют. Маркер обработанности
        (history_processed=1): повторный крон НЕ пере-экстрактит те же
        live-строки (extract_calls не растёт); новые строки ПОСЛЕ маркера
        экстрактятся следующим кроном."""
        hot_cache.set({RETENTION_KEY: True})
        live_ts = _old_ts()
        llm = _FakeLLM()
        await _save_message(db, -100, "сообщение живого чата про войну",
                            live_ts, author="вася")
        await _save_message(db, -100, "импортированное сообщение",
                            live_ts - 1000, author="петя",
                            import_key="a" * 32)
        memory = MemoryManager(db, llm)
        memory._vec_available = False
        await memory.compress_and_purge(-100)
        # сырьё живо (в т.ч. импортированное)
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 10)
        assert len(raw) == 2
        # archive не пополнялся
        facts = await db.search_archive_fts(-100, '"факт"', 10)
        assert facts == []
        # граф пополнен из живого сообщения (extract вызван ровно 1 раз)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM nodes WHERE chat_id = -100")
        assert (await cursor.fetchone())["c"] >= 2
        assert llm.extract_calls == 1
        # live-строка помечена обработанной (маркер стоит)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages "
            "WHERE chat_id = -100 AND import_key IS NULL "
            "AND history_processed = 1")
        assert (await cursor.fetchone())["c"] == 1
        # повторный прогон — extract НЕ пере-экстрактит (0 повторных
        # экстракций), сырьё по-прежнему живо
        await memory.compress_and_purge(-100)
        assert llm.extract_calls == 1
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 10)
        assert len(raw) == 2
        # новые live-строки (после маркера, старше cutoff) — экстрактятся
        await _save_message(db, -100, "новое сообщение про события недели",
                            live_ts - 2000, author="петя")
        await _save_message(db, -100, "ещё одно новое сообщение чата",
                            live_ts - 3000, author="вася")
        await memory.compress_and_purge(-100)
        assert llm.extract_calls == 2
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages "
            "WHERE chat_id = -100 AND import_key IS NULL "
            "AND history_processed = 1")
        assert (await cursor.fetchone())["c"] == 3
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 10)
        assert len(raw) == 4

    @pytest.mark.asyncio
    async def test_on_imported_only_no_extract(self, db, hot_cache):
        """ON: пачки только из импортированных строк (import_key IS NOT
        NULL) исключаются из extract — LLM не дёргается, сырьё живо."""
        hot_cache.set({RETENTION_KEY: True})
        llm = _FakeLLM()
        await _save_message(db, -100, "только импортированное",
                            _old_ts(), author="петя",
                            import_key="b" * 32)
        memory = MemoryManager(db, llm)
        memory._vec_available = False
        await memory.compress_and_purge(-100)
        assert llm.extract_calls == 0
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 10)
        assert len(raw) == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM nodes WHERE chat_id = -100")
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_on_graph_flag_off_noop_no_busyloop(self, db, hot_cache):
        """ON + flags.graph_rag_enabled=False (extract_enabled=False):
        extract-only ветка — ранний no-op (фикс B-раунда busy-loop). При
        ≥batch_size необработанных live-строк старше cutoff цикл завершается
        сразу: строки НЕ помечаются history_processed (без экстракции маркер
        не ставится), НЕ удаляются, LLM не вызывается — при включении
        graph-флага экстракция возобновится с той же выборки."""
        hot_cache.set({RETENTION_KEY: True, "flags.graph_rag_enabled": False})
        llm = _FakeLLM()
        for i in range(110):                     # > SUMMARY_COMPRESS_BATCH (100)
            await _save_message(db, -100, f"live-сообщение №{i} про войну",
                                _old_ts() - i, author="вася")
        memory = MemoryManager(db, llm)
        memory._vec_available = False
        await asyncio.wait_for(memory.compress_and_purge(-100), timeout=5)
        # сырьё живо (все 110 строк), маркер НЕ поставлен, LLM не дёргался
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages WHERE chat_id = -100")
        assert (await cursor.fetchone())["c"] == 110
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages "
            "WHERE chat_id = -100 AND history_processed = 1")
        assert (await cursor.fetchone())["c"] == 0
        assert llm.extract_calls == 0
        assert llm.compress_calls == 0
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM nodes WHERE chat_id = -100")
        assert (await cursor.fetchone())["c"] == 0
        # повторный прогон — тот же мгновенный no-op (не busy-loop)
        await asyncio.wait_for(memory.compress_and_purge(-100), timeout=5)
        assert llm.extract_calls == 0

    @pytest.mark.asyncio
    async def test_on_purge_archive_skipped(self, db, hot_cache):
        """ON: _purge_archive no-op — древние архивные факты живут."""
        hot_cache.set({RETENTION_KEY: True})
        old_fact_ts = int(time.time()) - 100 * 86400
        await db.save_archive_fact(-100, "древний архивный факт", old_fact_ts)
        memory = MemoryManager(db, _FakeLLM())
        memory._vec_available = False
        await memory._purge_archive(-100)
        remaining = await db.search_archive_fts(-100, '"факт"', 10)
        assert remaining == ["древний архивный факт"]
        # OFF — регресс: древний факт вычищается
        hot_cache.set({})
        await memory._purge_archive(-100)
        assert await db.search_archive_fts(-100, '"факт"', 10) == []


# ── 4. memory_maintenance.review (G6) ───────────────────────────────────────

class TestReviewToggle:
    def _service(self, db):
        memory = MagicMock()
        memory._vec_available = False
        svc = MemoryMaintenanceService.__new__(MemoryMaintenanceService)
        svc.db = db
        svc.memory = memory
        svc.llm = MagicMock()
        return svc

    @pytest.mark.asyncio
    async def test_on_merge_works_purge_skipped(self, db, hot_cache):
        """ON: review — purge-фазы (G3-G5) скипаются, но merge-фазы работают
        (склейка точных дублей — слияние, не удаление по TTL)."""
        hot_cache.set({RETENTION_KEY: True})
        now = int(time.time())
        # истёкший + unconfirmed-старьё + лог — должны ПЕРЕЖИТЬ review
        await db.insert_graph_fact(-100, "истёкший", "search_fact", now - 10)
        await db.insert_graph_fact(-100, "неподтверждённый", "chat_history",
                                   None, status="unconfirmed")
        await db.log_fact_compression(-100, 1, "было", "стало", "test")
        # точный дубль живых фактов (merge-фаза review)
        a = await db.insert_graph_fact(-100, "петя купил машину",
                                       "chat_history", None, weight=0.4)
        b = await db.insert_graph_fact(-100, "петя купил машину",
                                       "chat_history", None, weight=0.9)
        svc = self._service(db)
        await svc.review()
        # purge-фазы не сработали
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE fact = 'истёкший'")
        assert (await cursor.fetchone())["c"] == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts "
            "WHERE status = 'unconfirmed'")
        assert (await cursor.fetchone())["c"] == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_fact_compressions")
        assert (await cursor.fetchone())["c"] >= 2   # лог не усечён (+merge)
        # merge-фаза: дубль склеен — остался самый тяжёлый
        cursor = await db.db.execute(
            "SELECT id, weight FROM graph_facts WHERE fact = 'петя купил машину'")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["weight"] == 0.9
        assert a != b

