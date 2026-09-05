"""Раунд 7 (chat-lore-management-v2, T-785/H3.3, G1) — тесты сида легаси-лора.

scripts/seed_chat_lore.py на мок-PG (прецедент моков pg в test_pg_db.py):
1-й прогон — inserted; повтор — no-op (existing-manual-not-empty); существующий
непустой manual_lore НЕ затирается; текст сида == константе
CHAT_LORE_2661910336; без side-эффектов на SQLite (только PG-таблица).
"""
import pytest

from scripts import seed_chat_lore as seed_mod
from services.chat_lore import (
    CHAT_LORE_2661910336,
    CHAT_LORE_TARGET_CHAT_ID,
)
from services.pg_db import DDL_STATEMENTS

TARGET = CHAT_LORE_TARGET_CHAT_ID


class _FakeConn:
    """Мини-PG для сида: строка профиля + INSERT ... ON CONFLICT DO NOTHING."""

    def __init__(self, profiles=None):
        # chat_id → {"manual_lore": str}
        self.profiles = dict(profiles or {})
        self.queries: list[str] = []

    async def fetchrow(self, sql: str, *args):
        self.queries.append(sql)
        row = self.profiles.get(args[0])
        return {"manual_lore": row["manual_lore"]} if row is not None else None

    async def execute(self, sql: str, *args):
        self.queries.append(sql)
        assert "ON CONFLICT" in sql          # сид всегда DO NOTHING
        if args[0] in self.profiles:
            return "INSERT 0 0"
        self.profiles[args[0]] = {"manual_lore": args[1]}
        return "INSERT 0 1"

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)
        self.closed = False

    async def close(self):
        self.closed = True


def _pg(conn=None):
    return _FakePg(conn if conn is not None else _FakeConn())


class TestSeed:
    @pytest.mark.asyncio
    async def test_first_run_inserts_constant(self):
        conn = _FakeConn()
        report = await seed_mod.seed_chat_lore(_pg(conn))
        assert report["chat_id"] == TARGET
        assert report["status"] == "inserted"
        assert report["inserted"] is True
        assert conn.profiles[TARGET]["manual_lore"] == CHAT_LORE_2661910336
        assert "VALUES ($1, $2" in conn.queries[-1]      # текст — параметром

    @pytest.mark.asyncio
    async def test_second_run_noop_existing_manual(self):
        conn = _FakeConn({TARGET: {"manual_lore": CHAT_LORE_2661910336}})
        pg = _pg(conn)
        report = await seed_mod.seed_chat_lore(pg)
        assert report["status"] == "existing-manual-not-empty"
        assert report["inserted"] is False
        # INSERT не выполнялся (ручные правки приоритетнее — §3.12)
        assert not any("INSERT INTO chat_profiles" in q
                       for q in conn.queries)
        assert conn.profiles[TARGET]["manual_lore"] == CHAT_LORE_2661910336
        assert not pg.closed            # внешний pg не закрываем

    @pytest.mark.asyncio
    async def test_existing_custom_manual_not_overwritten(self):
        custom = "Ручной лор после правки админом в TMA"
        conn = _FakeConn({TARGET: {"manual_lore": custom}})
        report = await seed_mod.seed_chat_lore(_pg(conn))
        assert report["status"] == "existing-manual-not-empty"
        assert conn.profiles[TARGET]["manual_lore"] == custom

    @pytest.mark.asyncio
    async def test_existing_empty_manual_insert_skipped(self):
        conn = _FakeConn({TARGET: {"manual_lore": ""}})
        report = await seed_mod.seed_chat_lore(_pg(conn))
        assert report["status"] == "skipped"       # ON CONFLICT DO NOTHING
        assert report["inserted"] is False
        assert conn.profiles[TARGET]["manual_lore"] == ""  # пустой не затираем
        assert any("INSERT INTO chat_profiles" in q for q in conn.queries)

    @pytest.mark.asyncio
    async def test_insert_sql_idempotent_on_conflict(self):
        assert "ON CONFLICT (chat_id) DO NOTHING" in seed_mod.SEED_INSERT_SQL
        assert "manual_lore" in seed_mod.SEED_INSERT_SQL
        assert str(TARGET) not in seed_mod.SEED_INSERT_SQL  # id — параметр

    def test_seed_text_is_legacy_constant(self):
        assert "джаббер конфы" in CHAT_LORE_2661910336
        assert TARGET == -1002661910336

    def test_ddl_table_exists_for_seed(self):
        ddl = " ".join(DDL_STATEMENTS)
        assert "CREATE TABLE IF NOT EXISTS chat_profiles" in ddl

    def test_main_module_runs_without_pg_fails_gracefully(self, monkeypatch):
        """Автономный запуск без POSTGRES_DSN → код 1 + stderr, не падение."""
        monkeypatch.delenv("POSTGRES_DSN", raising=False)
        assert seed_mod._inserted("INSERT 0 1") is True
        assert seed_mod._inserted("INSERT 0 0") is False
        assert seed_mod._inserted("мусор") is False

    @pytest.mark.asyncio
    async def test_seed_chat_lore_profile_accepts_store(self):
        """Адаптер seed_chat_lore_profile(store): pg берётся из store.pg."""
        from services.chat_lore_store import ChatLoreStore

        conn = _FakeConn()
        store = ChatLoreStore(_FakePg(conn))
        report = await seed_mod.seed_chat_lore_profile(store)
        assert report["status"] == "inserted"
        assert conn.profiles[TARGET]["manual_lore"] == CHAT_LORE_2661910336
