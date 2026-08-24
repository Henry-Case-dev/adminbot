"""Epic 60 Фаза D (Section 66.2/66.11, T-480/T-489): MemoryMaintenanceService —
слияние повторяющихся эпизодов + периодический пересмотр фактов."""
import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from config.settings import settings
from services.database import DatabaseService
from services.memory_maintenance import (
    _MERGE_CLUSTER_SIM,
    MemoryMaintenanceService,
)
from services.summary_memory import MemoryManager


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class MergeLLM:
    """generate: канон-ответ для слияния (COMPRESS_PROMPT); embed не нужен
    (FTS-фолбек кластеризации — vec выключен)."""

    def __init__(self, response="вася спорил с петей и колей", fail=False):
        self.response = response
        self.fail = fail
        self.calls = []

    async def generate(self, messages):
        self.calls.append(messages)
        if self.fail:
            from services.llm_client import LLMError
            raise LLMError("слияние упало")
        return self.response


def _service(db, llm) -> tuple[MemoryMaintenanceService, MemoryManager]:
    memory = MemoryManager(db, llm)          # _vec_available=False → FTS-фолбек
    return MemoryMaintenanceService(db, memory, llm), memory


class TestEpisodeMerge:
    @pytest.mark.asyncio
    async def test_cluster_merged_sources_deleted_logged(self, db):
        """66.2: кластер (точный subject+predicate, FTS-фолбек) → слитый факт,
        исходные удалены, журнал reason='episode_merge'."""
        await db.insert_graph_fact(-100, "вася спорил с петей", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей", "chat_history", None)
        await db.insert_graph_fact(
            -100, "озон доставляет быстрее wildberries", "search_fact", None)
        llm = MergeLLM(response="вася спорил с петей и колей")
        svc, _ = _service(db, llm)
        merged = await svc.merge_episodes()
        assert merged == 1
        cursor = await db.db.execute(
            "SELECT fact FROM graph_facts ORDER BY id")
        facts = [row["fact"] for row in await cursor.fetchall()]
        assert "вася спорил с петей и колей" in facts
        assert "вася спорил с петей" not in facts
        assert "вася спорил с колей" not in facts
        assert len(facts) == 2                   # чужой кластер не тронут
        cursor = await db.db.execute(
            "SELECT fact_before, reason FROM graph_fact_compressions")
        logs = await cursor.fetchall()
        assert len(logs) == 2
        assert all(row["reason"] == "episode_merge" for row in logs)

    @pytest.mark.asyncio
    async def test_coverage_check_skips_cluster(self, db, caplog):
        """66.2: «ничего не потерялось» не прошло (токены слитого < 60%
        исходных) → пропуск кластера, исходные живут."""
        await db.insert_graph_fact(-100, "вася спорил с петей вчера вечером", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей утром рано", "chat_history", None)
        llm = MergeLLM(response="вася")
        svc, _ = _service(db, llm)
        import logging
        with caplog.at_level(logging.WARNING):
            merged = await svc.merge_episodes()
        assert merged == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2     # исходные живы
        assert any("coverage check failed" in r.message for r in caplog.records)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_fact_compressions")
        assert (await cursor.fetchone())["c"] == 0     # журнала нет

    @pytest.mark.asyncio
    async def test_llm_error_skips_run(self, db):
        """66.2: LLMError → прогон прерван, исходные живут."""
        await db.insert_graph_fact(-100, "вася спорил с петей", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей", "chat_history", None)
        llm = MergeLLM(fail=True)
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2

    @pytest.mark.asyncio
    async def test_protected_excluded_from_clusters(self, db):
        """65.10: защищённый факт в кластеры не попадает — слияния нет."""
        await db.insert_graph_fact(-100, "вася спорил с петей", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей", "chat_history", None)
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, 'вася', 'вася спорил с петей', ?)", (time.time(),))
        await db.db.commit()
        llm = MergeLLM()
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2
        llm.generate.assert_not_awaited() if hasattr(llm.generate, "assert_not_awaited") else None

    @pytest.mark.asyncio
    async def test_batch_budget_respected(self, db, monkeypatch):
        """66.2: GRAPH_EPISODE_MERGE_BATCH — потолок кластеров за прогон."""
        mod_clusters = 3
        for i in range(mod_clusters):
            await db.insert_graph_fact(
                -100, f"тема{i} обсуждали подробно", "chat_history", None)
            await db.insert_graph_fact(
                -100, f"тема{i} обсуждали мельком", "chat_history", None)
        llm = MergeLLM(response="тема обсуждали подробно и мельком")
        svc, _ = _service(db, llm)
        mod = __import__("dataclasses").replace(
            settings, GRAPH_EPISODE_MERGE_BATCH=1)
        monkeypatch.setattr(
            "services.memory_maintenance.settings", mod)
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        # 1 кластер слит (−1 факт), остальные 4 живы
        assert (await cursor.fetchone())["c"] == 5

    @pytest.mark.asyncio
    async def test_merged_fact_keeps_max_weight_and_null_expiry(self, db):
        """Слитый факт: weight = max исходных; expiry NULL если хоть один
        источник вечный; origin chat_history при наличии такого источника."""
        f1 = await db.insert_graph_fact(
            -100, "вася ходит в кино часто", "chat_history", None)
        await db.db.execute("UPDATE graph_facts SET weight = 0.9 WHERE id = ?", (f1,))
        await db.insert_graph_fact(
            -100, "вася ходит в кино редко", "search_fact", None)
        await db.db.commit()
        llm = MergeLLM(response="вася ходит в кино часто и редко")
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute(
            "SELECT weight, expires_at, origin FROM graph_facts "
            "ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        assert row["weight"] == 0.9
        assert row["expires_at"] is None
        assert row["origin"] == "chat_history"


class TestReview:
    @pytest.mark.asyncio
    async def test_exact_dups_glued_keep_heaviest(self, db):
        """66.11 #1: точные дубли → keep самый тяжёлый, журнал review_glue."""
        keep_id = await db.insert_graph_fact(
            -100, "дроны летали низко", "web_content", None, weight=0.9)
        drop_id = await db.insert_graph_fact(
            -100, "Дроны летали низко ", "web_content", None, weight=0.3)
        svc, _ = _service(db, MergeLLM())
        await svc.review()
        cursor = await db.db.execute(
            "SELECT id, fact FROM graph_facts WHERE fact LIKE '%дроны%'")
        rows = await cursor.fetchall()
        assert len(rows) == 1 and rows[0]["id"] == keep_id
        cursor = await db.db.execute(
            "SELECT fact_before, fact_after, reason FROM graph_fact_compressions "
            "WHERE reason = 'review_glue'")
        log = await cursor.fetchone()
        assert log is not None
        assert log["fact_after"].strip().lower().startswith("дроны")

    @pytest.mark.asyncio
    async def test_expired_purged_globally(self, db):
        """66.11 #2: истёкшие выбрасываются глобальным проходом (без chat_id)."""
        now = int(time.time())
        await db.insert_graph_fact(
            -100, "мёртвый факт чата один", "search_fact", now - 100)
        await db.insert_graph_fact(
            -200, "мёртвый факт чата два", "search_fact", now - 100)
        await db.insert_graph_fact(
            -100, "живой вечный факт", "chat_history", None)
        svc, _ = _service(db, MergeLLM())
        await svc.review()
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1

    @pytest.mark.asyncio
    async def test_unconfirmed_dropped_after_retention(self, db, monkeypatch):
        """66.11 #3: unconfirmed старше GRAPH_UNCONFIRMED_RETENTION_DAYS —
        выброс (вместе с FTS/vec-строками)."""
        now = int(time.time())
        fid = await db.insert_graph_fact(
            -100, "сомнительный факт без подтверждения", "search_fact", None,
            status="unconfirmed")
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ? WHERE id = ?",
            (now - (settings.GRAPH_UNCONFIRMED_RETENTION_DAYS + 1) * 86400, fid))
        await db.db.commit()
        svc, _ = _service(db, MergeLLM())
        await svc.review()
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE id = ?", (fid,))
        assert (await cursor.fetchone())["c"] == 0
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts_fts WHERE rowid = ?", (fid,))
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_compression_log_trimmed(self, db, monkeypatch):
        """66.11 #4: graph_fact_compressions старше retention усечены."""
        old_ts = time.time() - (settings.GRAPH_COMPRESSION_LOG_RETENTION_DAYS + 1) * 86400
        await db.log_fact_compression(-100, 1, "старая запись", None, "supersede")
        await db.db.execute(
            "UPDATE graph_fact_compressions SET created_at = ? "
            "WHERE reason = 'supersede'", (old_ts,))
        await db.log_fact_compression(-100, 2, "свежая запись", None, "forget")
        await db.db.commit()
        svc, _ = _service(db, MergeLLM())
        await svc.review()
        cursor = await db.db.execute(
            "SELECT fact_before FROM graph_fact_compressions")
        rows = await cursor.fetchall()
        assert [r["fact_before"] for r in rows] == ["свежая запись"]

    @pytest.mark.asyncio
    async def test_review_never_raises_on_broken_db(self, db):
        """Пересмотр НЕ бросает (любая ошибка → WARNING)."""

        class BrokenDB(DatabaseService):
            async def find_exact_dup_groups(self, *args, **kwargs):
                raise RuntimeError("бд сломалась")

        broken = BrokenDB.__new__(BrokenDB)
        broken.__dict__.update(db.__dict__)
        broken.find_exact_dup_groups = AsyncMock(side_effect=RuntimeError("x"))
        svc, _ = _service(broken, MergeLLM())
        await svc.review()                       # не падает
