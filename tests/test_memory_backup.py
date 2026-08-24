"""Epic 60 (Section 64.3/64.9, T-464): MemoryBackupService — VACUUM INTO-
бэкап + текстовый экспорт фактов + ротация + ленивый скип."""
import asyncio
import logging
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

import services.memory_backup as mb
from services.database import DatabaseService
from services.memory_backup import MemoryBackupService


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _patch_settings(monkeypatch, **kwargs):
    mod = replace(mb.settings, **kwargs)
    monkeypatch.setattr(mb, "settings", mod)
    return mod


def _backup_files(tmp_path):
    return sorted(tmp_path.glob("local_database_*.db"))


def _export_files(tmp_path):
    return sorted(tmp_path.glob("facts_*.txt"))


class TestBackupAndExport:
    @pytest.mark.asyncio
    async def test_creates_backup_and_readable_export(self, db, tmp_path,
                                                      monkeypatch):
        _patch_settings(monkeypatch, MEMORY_BACKUP_DIR=str(tmp_path))
        await db.insert_graph_fact(-100, "озон доставляет быстрее чем wildberries",
                                   "search_fact", None)
        await db.save_archive_fact(-200, "сжатый архивный факт", 1)
        service = MemoryBackupService(db)
        await service.backup_and_export()

        backups = _backup_files(tmp_path)
        exports = _export_files(tmp_path)
        assert len(backups) == 1
        assert backups[0].name.startswith("local_database_")
        assert backups[0].stat().st_size > 0

        assert len(exports) == 1
        text = exports[0].read_text(encoding="utf-8")
        # читаемый глазами: построчно, UTF-8, без JSON/экранирований
        assert "[archive] [-200] сжатый архивный факт" in text
        graph_line = next(
            line for line in text.splitlines() if not line.startswith("[archive]"))
        assert graph_line.startswith("[-100] search_fact confirmed")
        assert "weight=0.5" in graph_line
        assert "created=" in graph_line
        assert "озон доставляет быстрее чем wildberries" in graph_line

    @pytest.mark.asyncio
    async def test_empty_memory_skips_lazily(self, db, tmp_path, monkeypatch,
                                             caplog):
        _patch_settings(monkeypatch, MEMORY_BACKUP_DIR=str(tmp_path))
        service = MemoryBackupService(db)
        with caplog.at_level(logging.INFO):
            await service.backup_and_export()
        assert _backup_files(tmp_path) == []
        assert _export_files(tmp_path) == []
        assert any("memory empty — backup/export skipped" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_rotation_keeps_last_n(self, db, tmp_path, monkeypatch):
        _patch_settings(monkeypatch, MEMORY_BACKUP_DIR=str(tmp_path),
                        MEMORY_BACKUP_KEEP=3)
        # 5 старых бэкапов + 5 старых экспортов
        for i in range(5):
            (tmp_path / f"local_database_20260{i}01.db").write_bytes(b"x")
            (tmp_path / f"facts_20260{i}01.txt").write_text("x", encoding="utf-8")
        await db.insert_graph_fact(-100, "факт", "search_fact", None)
        service = MemoryBackupService(db)
        await service.backup_and_export()

        backups = _backup_files(tmp_path)
        exports = _export_files(tmp_path)
        assert len(backups) == 3        # KEEP=3: 2 старых + сегодняшний
        assert len(exports) == 3
        assert backups[0].name.startswith("local_database_20260301")

    @pytest.mark.asyncio
    async def test_vacuum_into_failure_falls_back_to_subprocess(
            self, db, tmp_path, monkeypatch):
        _patch_settings(monkeypatch, MEMORY_BACKUP_DIR=str(tmp_path))
        await db.insert_graph_fact(-100, "факт", "search_fact", None)
        service = MemoryBackupService(db)
        service._backup_subprocess = AsyncMock()

        real_execute = db.db.execute

        async def guarded_execute(sql, params=()):
            if "VACUUM INTO" in str(sql):
                raise Exception("old sqlite: no VACUUM INTO")
            return await real_execute(sql, params)

        db.db.execute = guarded_execute
        await service.backup_and_export()
        assert service._backup_subprocess.await_count == 1

    @pytest.mark.asyncio
    async def test_subprocess_missing_sqlite_quiet_warning(self, db, tmp_path,
                                                           monkeypatch, caplog):
        _patch_settings(monkeypatch, MEMORY_BACKUP_DIR=str(tmp_path))
        await db.insert_graph_fact(-100, "факт", "search_fact", None)
        service = MemoryBackupService(db)
        with caplog.at_level(logging.WARNING):
            await service._backup_subprocess(tmp_path / "x.db")
        assert any(("sqlite3 CLI not found" in r.message or
                    "subprocess backup failed" in r.message)
                   for r in caplog.records)

    def test_parse_hour_invalid_falls_back(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert MemoryBackupService._parse_hour("не час") == (5, 0)
        with caplog.at_level(logging.WARNING):
            assert MemoryBackupService._parse_hour("23:45") == (23, 45)
