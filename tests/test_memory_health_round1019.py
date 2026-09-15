"""F7 (10.19, ADR-1019-6 D4) — аддитивные метрики здоровья памяти.

`GET /api/memory/health` (R16): существующие ключи сохранены + `facts_overdue`,
`facts_unconfirmed`, `smart_messages_total`, `deep_sleep_runs_total`,
`storage.{db_size_bytes, db_size_mb, disk_free_bytes}`. R17 — только числа.
Fail-open: ошибка БД → нули (не 500).
"""
import time

import pytest

from services.database import DatabaseService
from web.api import memory_agi


@pytest.fixture
def db(tmp_path):
    return DatabaseService(str(tmp_path / "health.db"))


class TestCounts:
    @pytest.mark.asyncio
    async def test_overdue_and_unconfirmed(self, db):
        await db.initialize()
        try:
            now = int(time.time())
            await db.insert_graph_fact(-100, "протухший", "web_content",
                                       now - 100)
            await db.insert_graph_fact(-100, "свежий", "search_fact",
                                       now + 100)
            await db.insert_graph_fact(-100, "unconf", "search_fact",
                                       now + 100, status="unconfirmed")
            await db.save_smart_message(1, -100, "привет", None, now, "text",
                                        "вася")
            assert await db.count_overdue_facts() == 1
            assert await db.count_unconfirmed_facts() == 1
            assert await db.count_smart_messages() == 1
            assert await db.count_smart_messages(-100) == 1
            assert await db.count_smart_messages(-999) == 0
        finally:
            await db.close()


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_additive_fields_and_r16(self, db, monkeypatch):
        await db.initialize()
        try:
            monkeypatch.setattr(memory_agi, "_require_global_admin",
                                lambda request, user: None)
            monkeypatch.setattr(memory_agi, "_db_or_503", lambda: db)
            out = await memory_agi.memory_health_summary(
                request=object(), user=object())
        finally:
            await db.close()
        for key in ("beliefs_active", "beliefs_archived",
                    "resurrections_total", "decay_runs_total", "last_decay_at",
                    "facts_overdue", "facts_unconfirmed",
                    "smart_messages_total", "deep_sleep_runs_total", "storage"):
            assert key in out
        assert set(out["storage"]) == {"db_size_bytes", "db_size_mb",
                                       "disk_free_bytes"}
        assert out["storage"]["db_size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_fail_open_on_db_error(self, db, monkeypatch):
        await db.initialize()
        try:
            async def _boom(*a, **k):
                raise RuntimeError("db boom")
            monkeypatch.setattr(db, "count_beliefs_by_status", _boom)
            monkeypatch.setattr(memory_agi, "_require_global_admin",
                                lambda request, user: None)
            monkeypatch.setattr(memory_agi, "_db_or_503", lambda: db)
            out = await memory_agi.memory_health_summary(
                request=object(), user=object())
        finally:
            await db.close()
        assert out["facts_overdue"] == 0
        assert out["smart_messages_total"] == 0
        assert out["beliefs_active"] == 0

    def test_storage_metrics_memory_db_zero(self):
        class _Mem:
            db_path = ":memory:"
        out = memory_agi._storage_metrics(_Mem())
        assert out["db_size_bytes"] == 0
        assert out["db_size_mb"] == 0

    @pytest.mark.asyncio
    async def test_health_counts_cached_within_ttl(self, db, monkeypatch):
        """D-2.3 (Medium): два вызова `/api/memory/health` в окне TTL (60с)
        → тяжёлый `count_smart_messages` вызван ОДИН раз (D-5-кэш)."""
        await db.initialize()
        try:
            monkeypatch.setattr(memory_agi, "_require_global_admin",
                                lambda request, user: None)
            monkeypatch.setattr(memory_agi, "_db_or_503", lambda: db)
            memory_agi._health_count_cache.clear()
            calls = {"n": 0}
            real = db.count_smart_messages

            async def _spy(*a, **k):
                calls["n"] += 1
                return await real(*a, **k)
            monkeypatch.setattr(db, "count_smart_messages", _spy)
            out1 = await memory_agi.memory_health_summary(
                request=object(), user=object())
            out2 = await memory_agi.memory_health_summary(
                request=object(), user=object())
        finally:
            await db.close()
        assert calls["n"] == 1
        assert out1["smart_messages_total"] == out2["smart_messages_total"]
