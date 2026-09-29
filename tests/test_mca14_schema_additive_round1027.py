"""MCA Wave 0 (`mca-14-schema-additive`) — ядро v13 (T-3754, T-3755, T-3756,
T-3758, T-3759).

Покрытие:
  * реестр миграций + книга `schema_migrations`; `PRAGMA user_version`
    сохраняется; legacy v12 back-fill baseline-ряда; идемпотентный повтор;
  * `VACUUM INTO` backup + free-space + read-back (провал → отказ);
  * сохранение ID/таблиц; новые nullable = честный unknown;
  * kill-switch `MCA_SCHEMA_MIGRATIONS_ENABLED` OFF-паритет.
"""
import asyncio
import sqlite3
import time

import pytest

import services.database as dbmod
from services.database import (DatabaseService, MigrationStep,
                               _SCHEMA_VERSION_SCHEMA_MIGRATIONS)


def _target_version() -> int:
    """Текущая целевая версия схемы = max зарегистрированного шага.

    Устойчиво к добавлению v14/v15: тест не хардкодит номер."""
    return max(s.version for s in DatabaseService.migration_steps())


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(dbmod, "_LOCK_BACKOFF", 0.0)


async def _fresh(tmp_path, name="mca14.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ── T-3754: реестр + книга ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v13_book_and_user_version(tmp_path):
    """SC-01/SC-02: книга `schema_migrations` создана; user_version = target."""
    d = await _fresh(tmp_path)
    try:
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == _target_version()
        cur = await d.db.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version")
        rows = [tuple(r) for r in await cur.fetchall()]
        assert any(v == 13 and n == "schema_migrations_book" for v, n in rows)
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_idempotent_reinitialize_zero_duplicates(tmp_path):
    """SC-01: повторный initialize — 0 изменений, 0 дублей в книге."""
    d = await _fresh(tmp_path)
    await d.close()
    d2 = DatabaseService(str(d.db_path))
    await d2.initialize()
    try:
        cur = await d2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version = 13")
        assert (await cur.fetchone())["c"] == 1
    finally:
        await d2.close()


@pytest.mark.asyncio
async def test_legacy_v12_backfill(tmp_path):
    """SC-01: legacy v12 без книги → baseline-ряд + v13; user_version = 13."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(DatabaseService._SCHEMA_SQL)
    conn.execute("PRAGMA user_version = 12")
    conn.commit()
    conn.close()
    d = DatabaseService(str(path))
    await d.initialize()
    try:
        cur = await d.db.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version")
        rows = [tuple(r) for r in await cur.fetchall()]
        assert (12, "legacy_baseline") in rows
        assert any(v == 13 for v, _ in rows)
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == _target_version()
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_migration_steps_ordered_and_distinct():
    """Реестр: версии строго возрастают и уникальны."""
    steps = DatabaseService.migration_steps()
    versions = [s.version for s in steps]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert all(isinstance(s, MigrationStep) for s in steps)


@pytest.mark.asyncio
async def test_kill_switch_off_legacy_path(tmp_path, monkeypatch):
    """T-3759: `MCA_SCHEMA_MIGRATIONS_ENABLED=false` → legacy-путь, книга НЕ
    создаётся, user_version = 12 (паритет baseline)."""
    monkeypatch.setattr(dbmod, "_schema_migrations_enabled", lambda: False)
    d = await _fresh(tmp_path)
    try:
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='schema_migrations'")
        assert (await cur.fetchone()) is None
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 12
    finally:
        await d.close()


# ── T-3755: backup + free-space + read-back ────────────────────────────────

@pytest.mark.asyncio
async def test_migration_backup_created_and_readable(tmp_path):
    """SC-03/SC-04: backup `pre_migration_*.db` читается (integrity ok)."""
    from services.memory_backup import migration_backup

    d = DatabaseService(str(tmp_path / "src.db"))
    await d.initialize()
    try:
        target_version = _target_version()
        target = await migration_backup(d, target_version=target_version)
        assert target is not None and target.exists()
        conn = sqlite3.connect(str(target))
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute(
            "PRAGMA user_version").fetchone()[0] == target_version
        conn.close()
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_migration_backup_memory_none():
    """`:memory:` → backup неприменим (None), не ошибка."""
    from services.memory_backup import migration_backup

    d = DatabaseService(":memory:")
    await d.initialize()
    try:
        assert await migration_backup(d) is None
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_migration_backup_insufficient_space(tmp_path, monkeypatch):
    """SC-03: недостаток места → явная ошибка (MigrationBackupError)."""
    import services.memory_backup as mb

    d = DatabaseService(str(tmp_path / "src2.db"))
    await d.initialize()
    try:
        import shutil as _shutil

        class _Usage:
            free = 0
            total = 0
            used = 0

        monkeypatch.setattr(_shutil, "disk_usage", lambda p: _Usage())
        with pytest.raises(mb.MigrationBackupError):
            await mb.migration_backup(d, target_version=13)
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_migration_fails_if_backup_fails(tmp_path, monkeypatch):
    """SC-03: провал backup → миграция НЕ применяется (нет частичного)."""
    import services.memory_backup as mb
    path = tmp_path / "unmigrated.db"
    await _legacy_v12(path)

    async def _boom(*a, **k):
        raise mb.MigrationBackupError("no space")

    monkeypatch.setattr(mb, "migration_backup", _boom)
    d = DatabaseService(str(path))
    try:
        with pytest.raises(mb.MigrationBackupError):
            await d.initialize()
    finally:
        # L-MCA01-4: провал на этапе миграций не должен оставлять открытое
        # соединение (иначе pytest видит leaked aiosqlite connection).
        await d.close()
    # user_version не поднят; книга не создана
    conn = sqlite3.connect(str(path))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
    conn.close()


# ── T-3756: стабильные ID / honest unknown ─────────────────────────────────

async def _legacy_v12(path):
    """Построить валидную legacy v12-БД (полная схема) и снять книгу."""
    d = DatabaseService(str(path))
    await d.initialize()
    await d.db.execute("DROP TABLE IF EXISTS schema_migrations")
    await d.db.execute("PRAGMA user_version = 12")
    await d.db.commit()
    await d.close()


@pytest.mark.asyncio
async def test_legacy_ids_preserved(tmp_path):
    """SC-05: legacy-строки сохраняют id после миграции (аддитивность)."""
    path = tmp_path / "ids.db"
    await _legacy_v12(path)
    conn = sqlite3.connect(str(path))
    conn.execute("INSERT INTO protected_facts (id, chat_id, user_name, fact, "
                 "created_at) VALUES (11, -1, 'a', 'f', 1.0)")
    conn.execute("PRAGMA user_version = 12")
    conn.commit()
    conn.close()
    d = DatabaseService(str(path))
    await d.initialize()
    try:
        cur = await d.db.execute("SELECT id FROM protected_facts")
        assert [r["id"] for r in await cur.fetchall()] == [11]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_new_nullable_columns_are_null(tmp_path):
    """SC-05: новые nullable-поля = NULL (честный unknown), не выдуманы."""
    path = tmp_path / "null.db"
    await _legacy_v12(path)
    conn = sqlite3.connect(str(path))
    conn.execute("INSERT INTO graph_facts (id, chat_id, fact, origin, "
                 "created_at, status, weight) VALUES (7, -1, 'f', "
                 "'chat_history', 1, 'confirmed', 0.5)")
    conn.execute("PRAGMA user_version = 12")
    conn.commit()
    conn.close()
    d = DatabaseService(str(path))
    await d.initialize()
    try:
        cur = await d.db.execute(
            "SELECT tg_message_id, source_ids, belief_meta FROM graph_facts "
            "WHERE id = 7")
        row = await cur.fetchone()
        assert row["tg_message_id"] is None
        assert row["source_ids"] is None
        assert row["belief_meta"] is None
    finally:
        await d.close()


# ── v14/v15: реестр-строки, порядок, идемпотентность ───────────────────────

@pytest.mark.asyncio
async def test_v14_v15_tables_and_order(tmp_path):
    """v14 `task_jobs` и v15 `mca_events` созданы; книга содержит их ряды."""
    d = await _fresh(tmp_path, name="wave0.db")
    try:
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] for r in await cur.fetchall()}
        assert {"task_jobs", "mca_events",
                "mca_event_aggregates"} <= tables
        cur = await d.db.execute(
            "SELECT version FROM schema_migrations ORDER BY version")
        versions = [r["version"] for r in await cur.fetchall()]
        assert versions == sorted(versions)
        assert 14 in versions and 15 in versions
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == _target_version()
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v14_v15_idempotent(tmp_path):
    """Повторный initialize: task_jobs/mca_events не дублируются; книга — 1 ряд."""
    d = await _fresh(tmp_path, name="wave0b.db")
    await d.close()
    d2 = DatabaseService(str(d.db_path))
    await d2.initialize()
    try:
        cur = await d2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version IN "
            "(14, 15)")
        assert (await cur.fetchone())["c"] == 2
        cur = await d2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == _target_version()
    finally:
        await d2.close()


@pytest.mark.asyncio
async def test_v14_v15_indices_present(tmp_path):
    d = await _fresh(tmp_path, name="idx.db")
    try:
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")
        idx = {r["name"] for r in await cur.fetchall()}
        assert {"idx_task_jobs_status_created",
                "idx_task_jobs_coalesce_active"} <= idx
        assert {"idx_mca_events_ts", "idx_mca_events_trace",
                "idx_mca_events_chat_component",
                "idx_mca_events_reason"} <= idx
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_legacy_v12_gains_v14_v15(tmp_path):
    """Legacy v12 → применяются v13/v14/v15 по возрастанию версий."""
    path = tmp_path / "legacy2.db"
    await _legacy_v12(path)
    d = DatabaseService(str(path))
    await d.initialize()
    try:
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] for r in await cur.fetchall()}
        assert "task_jobs" in tables and "mca_events" in tables
    finally:
        await d.close()


# ── B-MCA14-1: восстановление после сбоя раннего шага на fresh-БД ───────────

@pytest.mark.asyncio
async def test_fresh_init_failure_on_early_step_recovers(tmp_path, monkeypatch):
    """B-MCA14-1/G13: сбой на раннем шаге (fresh-БД) НЕ оставляет
    `user_version=13`; повторный `initialize()` доводит схему до целевой
    (v1…v12 не пропускаются)."""
    path = tmp_path / "recover.db"
    d = DatabaseService(str(path))
    original = DatabaseService.migration_steps
    state = {"failed": False}

    def steps_with_failing_v1():
        out = []
        for step in original():
            if step.version == 1:
                async def _fail(svc, _s=step):
                    if not state["failed"]:
                        state["failed"] = True
                        raise RuntimeError("injected early-step failure")
                    await _s.apply(svc)
                out.append(MigrationStep(1, step.name, _fail))
            else:
                out.append(step)
        return out

    monkeypatch.setattr(DatabaseService, "migration_steps",
                        staticmethod(steps_with_failing_v1))
    try:
        with pytest.raises(RuntimeError):
            await d.initialize()
    finally:
        await d.close()
    # преждевременной фиксации user_version=13 нет
    conn = sqlite3.connect(str(path))
    version_after_failure = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert version_after_failure != _SCHEMA_VERSION_SCHEMA_MIGRATIONS

    monkeypatch.setattr(DatabaseService, "migration_steps",
                        staticmethod(original))
    d2 = DatabaseService(str(path))
    await d2.initialize()
    try:
        cur = await d2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == _target_version()
        # схема восстановлена полностью (v1…v12 не пропущены)
        cur = await d2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version = 13")
        assert (await cur.fetchone())["c"] == 1
        cur = await d2.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='smart_messages'")
        assert (await cur.fetchone()) is not None
    finally:
        await d2.close()


# ── L-MCA14-1: ротация pre-migration копий отдельно от daily-бэкапов ────────

def test_prune_migration_backups_keeps_one_and_spares_daily(tmp_path):
    """L-MCA14-1: `pre_migration_*` ротируются до 1, daily-бэкапы не тронуты."""
    from services.disk_retention import prune_migration_backups

    old = tmp_path / "pre_migration_20200101_000000.db"
    new = tmp_path / "pre_migration_20260101_000000.db"
    daily = tmp_path / "local_database_20260101.db"
    for p in (old, new, daily):
        p.write_bytes(b"x")
    import os
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    removed = prune_migration_backups(tmp_path, keep=1)
    assert [p for p in removed] == [str(old)]
    assert not old.exists()
    assert new.exists() and daily.exists()   # daily-бэкап не тронут
