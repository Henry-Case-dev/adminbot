"""F0.5 (раунд 10.25, ADR-1025-5) — устойчивость к `database is locked`
в main write-path `services/database.py` и переведённых сервисах.

(a) PRAGMA реально применены на файловой БД;
(b) имитация `locked` → retry успешен (запись не потеряна);
(c) исчерпание → WARNING `event=database_lock_exhausted` + счётчик;
(d) non-lock исключение НЕ ретраится;
(e) сериализация: параллельные логические транзакции атомарны (не интерливинятся);
(f) kill-switch OFF = baseline (без повторов);
(g) fail-open хендлера: исчерпание не роняет вызов (persistent throttle).

Тест-хук нулевого backoff (D7): `services.database._LOCK_BACKOFF = 0` —
тесты не спят (прецедент services/llm_client.py:604).
"""
import asyncio
import sqlite3

import aiosqlite
import pytest

import services.database as dbmod
from services.database import (
    DatabaseService,
    database_lock_exhausted_total,
)


def _locked() -> sqlite3.OperationalError:
    return sqlite3.OperationalError("database is locked")


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(dbmod, "_LOCK_BACKOFF", 0.0)
    return None


async def _make_db(tmp_path, name="lock.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ── (a) PRAGMA-паритет на файловой БД ───────────────────────────────────────

@pytest.mark.asyncio
async def test_pragma_parity_on_file_db(tmp_path):
    d = await _make_db(tmp_path)
    try:
        cur = await d.db.execute("PRAGMA journal_mode")
        mode = (await cur.fetchone())[0]
        cur = await d.db.execute("PRAGMA busy_timeout")
        busy = (await cur.fetchone())[0]
        cur = await d.db.execute("PRAGMA synchronous")
        sync = (await cur.fetchone())[0]
        assert str(mode).lower() == "wal"
        assert int(busy) == 5000
        assert int(sync) == 1                      # NORMAL
    finally:
        await d.close()


# ── (b) retry на locked → успех ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_locked_retry_succeeds(no_backoff):
    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        calls = {"n": 0}

        async def op(conn):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _locked()
            return "done"

        before = database_lock_exhausted_total()
        result = await d.write_transaction(op, op_name="t")
        assert result == "done"
        assert calls["n"] == 3                     # 2 ретрая + успех
        assert database_lock_exhausted_total() == before   # не исчерпано
    finally:
        await d.close()


# ── (c) исчерпание → WARNING + счётчик + re-raise ───────────────────────────

@pytest.mark.asyncio
async def test_exhaustion_warns_and_counts(no_backoff, caplog):
    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        calls = {"n": 0}

        async def op(conn):
            calls["n"] += 1
            raise _locked()

        before = database_lock_exhausted_total()
        with caplog.at_level("WARNING"):
            with pytest.raises(sqlite3.OperationalError):
                await d.write_transaction(op, op_name="boom", chat_id=-100)
        assert calls["n"] == dbmod._LOCK_RETRIES + 1        # 1 + 3 попытки
        assert database_lock_exhausted_total() == before + 1
        assert any("event=database_lock_exhausted" in r.message
                   for r in caplog.records)
    finally:
        await d.close()


# ── (d) non-lock исключение НЕ ретраится ────────────────────────────────────

@pytest.mark.asyncio
async def test_non_lock_not_retried(no_backoff):
    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        calls = {"n": 0}

        async def op(conn):
            calls["n"] += 1
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await d.write_transaction(op, op_name="t")
        assert calls["n"] == 1
    finally:
        await d.close()


# ── (e) сериализация (single-writer) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_transactions_serialized(no_backoff):
    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        active = {"n": 0, "max": 0}

        async def op(conn):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            await asyncio.sleep(0.02)              # окно для интерливинга
            active["n"] -= 1
            return None

        await asyncio.gather(
            d.write_transaction(op, op_name="a"),
            d.write_transaction(op, op_name="b"),
            d.write_transaction(op, op_name="c"),
        )
        assert active["max"] == 1                   # ни одна не вклинилась
    finally:
        await d.close()


# ── (f) kill-switch OFF = baseline ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_off_baseline_no_retry(monkeypatch, no_backoff):
    monkeypatch.setattr(dbmod, "_lock_resilience_enabled", lambda: False)
    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        calls = {"n": 0}

        async def op(conn):
            calls["n"] += 1
            raise _locked()

        before = database_lock_exhausted_total()
        with pytest.raises(sqlite3.OperationalError):
            await d.write_transaction(op, op_name="t")
        assert calls["n"] == 1                      # ни одного повтора
        assert database_lock_exhausted_total() == before
    finally:
        await d.close()


# ── (g) fail-open хендлера: исчерпание не роняет вызов ──────────────────────

@pytest.mark.asyncio
async def test_throttle_fail_open_on_exhaustion(no_backoff, monkeypatch):
    from services.persistent_throttling import PersistentThrottle

    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        async def always_locked(*args, **kwargs):
            raise _locked()

        monkeypatch.setattr(d.db, "execute", always_locked)
        throttle = PersistentThrottle(3, 60.0, "direct_chat", d)
        before = database_lock_exhausted_total()
        # fail-open: allow возвращает 0.0 (допуск), хендлер не падает.
        assert await throttle.allow(-100, 7) == 0.0
        assert database_lock_exhausted_total() == before + 1
    finally:
        await d.close()


# ── Тест-хук backoff (D7) существует и нулевой в тестах ─────────────────────

def test_zero_backoff_hook_available():
    assert hasattr(dbmod, "_LOCK_BACKOFF")
    assert dbmod._LOCK_RETRIES == 3


# ── Ревью item 1: rollback на ЛЮБОЕ исключение (не только locked) ────────────

@pytest.mark.asyncio
async def test_non_lock_error_rolls_back(no_backoff):
    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        await d.db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        await d.db.commit()

        async def op(conn):
            await conn.execute("INSERT INTO t (v) VALUES (?)", ("x",))
            raise ValueError("boom on 2nd statement")   # не locked

        with pytest.raises(ValueError):
            await d.write_transaction(op, op_name="t")
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM t")
        assert (await cur.fetchone())[0] == 0, "частичная транзакция откатана"

        # Следующий write_transaction не «подхватывает» огрызки.
        async def op2(conn):
            await conn.execute("INSERT INTO t (v) VALUES (?)", ("y",))
            return 1
        assert await d.write_transaction(op2, op_name="t2") == 1
        cur = await d.db.execute("SELECT v FROM t")
        rows = await cur.fetchall()
        assert [r[0] for r in rows] == ["y"]
    finally:
        await d.close()


# ── Ревью item 4/5: OFF-путь тоже откатывает транзакцию ─────────────────────

@pytest.mark.asyncio
async def test_off_path_rolls_back(monkeypatch, no_backoff):
    monkeypatch.setattr(dbmod, "_lock_resilience_enabled", lambda: False)
    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        await d.db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        await d.db.commit()

        async def op(conn):
            await conn.execute("INSERT INTO t (v) VALUES (?)", ("x",))
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await d.write_transaction(op, op_name="t")
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM t")
        assert (await cur.fetchone())[0] == 0
    finally:
        await d.close()
