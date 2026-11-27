"""SELF-DIAG-01 D6-20 (T1-T6): срезы ресурсов/очереди/БД без выдуманных нулей."""

import os

import pytest

from services import self_diag_samples as sds
from services.database import DatabaseService


async def _new_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _rows(db) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT * FROM self_diag_samples ORDER BY ts ASC")
    return [dict(row) for row in await cursor.fetchall()]


def _sample(ts, *, pid, started, cpu=None, rss=None, db_bytes=None,
            wal=None, free=None, depth=None, age=None) -> dict:
    return {
        "ts": ts, "pid": pid, "process_started_at": started,
        "cpu_percent": cpu, "rss_mb": rss, "db_bytes": db_bytes,
        "wal_bytes": wal, "disk_free_bytes": free, "queue_depth": depth,
        "queue_age_seconds": age,
    }


@pytest.mark.asyncio
async def test_record_writes_one_row_with_process_identity():
    db = await _new_db()
    sds.reset_process_cache()
    try:
        assert await sds.record(db, now=1_700_000_000) is True
        rows = await _rows(db)
        assert len(rows) == 1
        row = rows[0]
        assert row["ts"] == 1_700_000_000
        assert row["pid"] == os.getpid()
        assert isinstance(row["process_started_at"], int)
        assert isinstance(row["app_version"], str) and row["app_version"]
        assert row["sample_source"] == "maintenance_tick"
        # Nullable-колонки честно допускают NULL (in-memory БД без файлов).
        assert row["db_bytes"] is None
        assert row["wal_bytes"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_first_tick_cpu_is_null_not_zero(monkeypatch):
    db = await _new_db()
    sds.reset_process_cache()
    values = iter([0.0, 41.5])

    def _fake_cpu(interval=None):
        return next(values)

    monkeypatch.setattr(sds.psutil, "cpu_percent", _fake_cpu)
    try:
        await sds.record(db, now=1_700_000_000)
        await sds.record(db, now=1_700_000_300)
        rows = await _rows(db)
        assert rows[0]["cpu_percent"] is None, (
            "первый замер CPU не измерен — обязан быть NULL, не 0")
        assert rows[1]["cpu_percent"] == 41.5
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prune_removes_only_older_than_retention():
    db = await _new_db()
    now = 1_700_000_000
    old = now - (sds.SELF_DIAG_SAMPLE_RETENTION_DAYS + 1) * 86400
    recent = now - 86400
    try:
        for ts in (old, recent):
            await db.db.execute(
                "INSERT INTO self_diag_samples (ts) VALUES (?)", (ts,))
        await db.db.commit()
        deleted = await sds.prune(db, now=now)
        rows = await _rows(db)
        assert deleted == 1
        assert [row["ts"] for row in rows] == [recent]
        assert sds.SELF_DIAG_SAMPLE_RETENTION_DAYS == 30
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_growth_summary_requires_two_samples():
    one = [_sample(100, pid=1, started=10, db_bytes=1000, wal=100,
                   free=5000, depth=2, age=10)]
    summary = sds.summarize(one)
    assert summary["db"]["measured"] is False
    assert summary["db"]["reason"] == "single_sample"
    assert summary["db"]["db_growth_bytes"] is None
    assert summary["db"]["wal_growth_bytes"] is None
    assert summary["queue"]["measured"] is False
    assert summary["queue"]["delta_depth"] is None

    two = one + [_sample(400, pid=1, started=10, db_bytes=1400, wal=160,
                         free=4700, depth=5, age=20)]
    summary = sds.summarize(two)
    assert summary["db"]["measured"] is True
    assert summary["db"]["reason"] is None
    assert summary["db"]["db_growth_bytes"] == 400
    assert summary["db"]["wal_growth_bytes"] == 60
    assert summary["db"]["free_delta_bytes"] == -300
    assert summary["queue"]["measured"] is True
    assert summary["queue"]["delta_depth"] == 3
    assert summary["queue"]["peak_depth"] == 5
    assert summary["queue"]["current"]["oldest_age_seconds"] == 20


@pytest.mark.asyncio
async def test_process_segments_not_merged():
    rows = [
        _sample(100, pid=111, started=1, cpu=10.0, rss=100.0,
                db_bytes=1000, free=5000),
        _sample(200, pid=222, started=2, cpu=70.0, rss=300.0,
                db_bytes=1200, free=4900),
        _sample(300, pid=222, started=2, cpu=80.0, rss=320.0,
                db_bytes=1500, free=4800),
    ]
    summary = sds.summarize(rows)
    assert summary["segments"] == 2
    current = summary["process_current"]
    assert current["pid"] == 222
    assert current["cpu_percent"] == 80.0
    assert current["rss_mb"] == 320.0
    # Процессные поля не усреднены через рестарт (среднее было бы 53.3/240).
    assert current["cpu_percent"] != round((10.0 + 70.0 + 80.0) / 3, 1)
    assert current["rss_mb"] != round((100.0 + 300.0 + 320.0) / 3, 1)
    # Host-дельты считаются по всему окну и не теряются из-за рестарта.
    assert summary["db"]["db_growth_bytes"] == 500
    assert summary["db"]["free_delta_bytes"] == -200


@pytest.mark.asyncio
async def test_db_wal_sizes_from_files(tmp_path):
    db = await _new_db()
    sds.reset_process_cache()
    try:
        real = tmp_path / "t6.db"
        real.write_bytes(b"x" * 10)
        (tmp_path / "t6.db-wal").write_bytes(b"w" * 4)
        db.db_path = real
        await sds.record(db, now=1_700_000_000)
        rows = await _rows(db)
        assert rows[0]["db_bytes"] == 10
        assert rows[0]["wal_bytes"] == 4
        assert rows[0]["shm_bytes"] is None

        db.db_path = tmp_path / "absent.db"
        await sds.record(db, now=1_700_000_300)
        rows = await _rows(db)
        assert rows[1]["db_bytes"] is None, "отсутствующий файл — NULL, не 0"
        assert rows[1]["wal_bytes"] is None
    finally:
        await db.close()
