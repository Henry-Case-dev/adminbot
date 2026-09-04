"""Фаза 2 (T-751, B4) — тесты FTS-загрузчика (INSERT smart_messages + FTS).

Пересечение файлов (одинаковые import_key) → INSERT OR IGNORE не дублирует;
FTS-индекс синхронен (MATCH находит ровно текстовые строки); обрыв → повторный
запуск продолжает без дублей (идемпотентность); dry-run ничего не пишет;
чекпоинты done. Примечание: COUNT(*) по FTS5-таблице проксирует content-таблицу
(SQLite 3.42, external content) — реальный индекс проверяется через MATCH.
"""
import json

import aiosqlite
import pytest

from services.database import DatabaseService
from tools.history_import.loader import import_history_fts
from tools.history_import.parser import BadTimestampError, normalize_message

FIXTURE_DIR = "tests/fixtures/history"
CHAT_2026 = f"{FIXTURE_DIR}/chat_2026.json"
CHAT_2025 = f"{FIXTURE_DIR}/chat_2025.json"
TARGET_CHAT = -1002661910336


async def _make_db(tmp_path, name: str) -> str:
    """БД с применёнными миграциями v1..v7 (как CLI _ensure_db)."""
    db_path = str(tmp_path / name)
    svc = DatabaseService(db_path)
    try:
        await svc.initialize()
    finally:
        await svc.close()
    return db_path


def _fixture_stats(path: str) -> dict:
    """Ожидаемая статистика фикстуры по нормализации (эталон)."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    accepted = []
    service = 0
    empty = 0
    for item in raw["messages"]:
        try:
            msg = normalize_message(item)
        except BadTimestampError:
            continue
        if msg is None:
            if item.get("type") != "message":
                service += 1
            else:
                empty += 1
            continue
        accepted.append(msg)
    return {"accepted": accepted, "service": service, "empty": empty,
            "with_text": sum(1 for m in accepted if m["text"])}


async def _counts(db_path: str) -> dict:
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        cursor = await conn.execute(
            "SELECT COUNT(*) AS c FROM smart_messages")
        total = (await cursor.fetchone())[0]
        cursor = await conn.execute(
            "SELECT COUNT(*) AS c FROM smart_messages "
            "WHERE import_key IS NOT NULL")
        keys = (await cursor.fetchone())[0]
        return {"total": total, "keys": keys}
    finally:
        await conn.close()


async def _fts_search_rowids(db_path: str, query: str) -> list:
    """Реальные rowid FTS-индекса по MATCH (см. docstring модуля)."""
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        cursor = await conn.execute(
            "SELECT DISTINCT rowid FROM smart_messages_fts "
            "WHERE smart_messages_fts MATCH ?", (query,))
        return [r[0] for r in await cursor.fetchall()]
    finally:
        await conn.close()


async def _checkpoint_rows(db_path: str) -> list:
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    try:
        cursor = await conn.execute(
            "SELECT path, processed, total, done FROM import_checkpoints "
            "ORDER BY path")
        return await cursor.fetchall()
    finally:
        await conn.close()


class TestLoaderOverlap:
    @pytest.mark.asyncio
    async def test_overlap_files_do_not_duplicate(self, tmp_path):
        """2 файла с пересечением (одинаковые сообщения) → дубли НЕ вставлены
        (COUNT не растёт), FTS-индекс синхронен, чекпоинты done."""
        db_path = await _make_db(tmp_path, "overlap.db")
        stats1 = _fixture_stats(CHAT_2026)
        stats2 = _fixture_stats(CHAT_2025)
        keys1 = {m["import_key"] for m in stats1["accepted"]}
        overlap = sum(1 for m in stats2["accepted"]
                      if m["import_key"] in keys1)
        expect_total = len(stats1["accepted"]) + \
            len(stats2["accepted"]) - overlap
        expect_with_text = stats1["with_text"] + stats2["with_text"] - \
            sum(1 for m in stats2["accepted"]
                if m["import_key"] in keys1 and m["text"])

        summary = await import_history_fts(
            db_path, [CHAT_2026, CHAT_2025], TARGET_CHAT, batch_size=2)
        assert summary["dry_run"] is False
        assert summary["inserted"] == expect_total
        assert summary["duplicates"] == overlap
        assert summary["vacuumed"] is True
        counts = await _counts(db_path)
        assert counts["total"] == expect_total
        assert counts["keys"] == expect_total
        # FTS-индекс синхронен: MATCH находит РОВНО текстовые строки обоих
        # файлов (media-only строка в FTS-индексе отсутствует).
        rowids = await _fts_search_rowids(
            db_path, '"привет"* OR "куски"* OR "пост"* OR "вот"* '
                     'OR "уникальное"*')
        assert len(rowids) == expect_with_text
        # media-only строка (animation без подписи) не находится поиском
        rowids = await _fts_search_rowids(db_path, '"animation"*')
        assert rowids == []
        # чат-таргет проставлен всем строкам
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        try:
            cursor = await conn.execute(
                "SELECT DISTINCT chat_id FROM smart_messages")
            chats = [r[0] for r in await cursor.fetchall()]
            assert chats == [TARGET_CHAT]
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM smart_messages_fts "
                "WHERE smart_messages_fts MATCH 'уникальное*'")
            assert (await cursor.fetchone())["c"] == 1
        finally:
            await conn.close()
        # чекпоинты: оба файла done=1
        rows = await _checkpoint_rows(db_path)
        assert {r["path"] for r in rows} == {CHAT_2026, CHAT_2025}
        assert all(r["done"] == 1 for r in rows)
        assert all(r["processed"] == r["total"] for r in rows)

    @pytest.mark.asyncio
    async def test_repeat_run_idempotent(self, tmp_path):
        """Повторный полный прогон — идемпотентен (INSERT OR IGNORE +
        чекпоинт done): ничего не вставлено, COUNT не меняется."""
        db_path = await _make_db(tmp_path, "repeat.db")
        await import_history_fts(db_path, [CHAT_2026], TARGET_CHAT,
                                 batch_size=2)
        before = await _counts(db_path)
        summary = await import_history_fts(db_path, [CHAT_2026], TARGET_CHAT,
                                           batch_size=2)
        after = await _counts(db_path)
        assert summary["inserted"] == 0
        assert summary["duplicates"] == before["total"]
        assert after == before

    @pytest.mark.asyncio
    async def test_resume_after_abort(self, tmp_path, monkeypatch):
        """Обрыв на середине (искусственный exception в батч-флаше) → уже
        записанные батчи сохранены; повторный запуск продолжает с чекпоинта,
        дублей нет (итог == одному полному прогону)."""
        import tools.history_import.loader as loader_mod

        db_path = await _make_db(tmp_path, "resume.db")
        calls = {"n": 0}
        orig_flush = loader_mod._flush_batch

        async def failing_flush(conn, fr, buffer, path, est_total):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("обрыв на середине")
            await orig_flush(conn, fr, buffer, path, est_total)

        monkeypatch.setattr(loader_mod, "_flush_batch", failing_flush)
        with pytest.raises(RuntimeError):
            await import_history_fts(db_path, [CHAT_2026], TARGET_CHAT,
                                     batch_size=2)
        partial = await _counts(db_path)
        assert 0 < partial["total"] < 5      # часть батчей записана

        monkeypatch.setattr(loader_mod, "_flush_batch", orig_flush)
        # после «починки» — полный прогон обоих файлов продолжает без дублей
        summary = await import_history_fts(
            db_path, [CHAT_2026, CHAT_2025], TARGET_CHAT, batch_size=2)
        keys1 = {m["import_key"]
                 for m in _fixture_stats(CHAT_2026)["accepted"]}
        expect_total = len(_fixture_stats(CHAT_2026)["accepted"]) + \
            sum(1 for m in _fixture_stats(CHAT_2025)["accepted"]
                if m["import_key"] not in keys1)
        counts = await _counts(db_path)
        assert counts["total"] == expect_total
        assert summary["inserted"] + partial["total"] == expect_total
        # повтор после resume — вставок 0 (идемпотентно)
        again = await import_history_fts(db_path, [CHAT_2026, CHAT_2025],
                                         TARGET_CHAT, batch_size=2)
        assert again["inserted"] == 0
        assert (await _counts(db_path))["total"] == expect_total

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, tmp_path):
        """--dry-run: ничего не пишется (строки/чекпоинты не появляются),
        статы считаются (прочитано = все записи файлов)."""
        db_path = await _make_db(tmp_path, "dry.db")
        stats = _fixture_stats(CHAT_2026)
        summary = await import_history_fts(
            db_path, [CHAT_2026, CHAT_2025], TARGET_CHAT, dry_run=True,
            batch_size=2)
        assert summary["dry_run"] is True
        assert summary["vacuumed"] is False
        assert summary["inserted"] == 0
        assert summary["read"] == 7 + 3
        assert summary["accepted"] == len(stats["accepted"]) + \
            len(_fixture_stats(CHAT_2025)["accepted"])
        assert summary["skipped_service"] == \
            stats["service"] + _fixture_stats(CHAT_2025)["service"]
        assert summary["errors"] == 0
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        try:
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM smart_messages")
            assert (await cursor.fetchone())["c"] == 0
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM sqlite_master "
                "WHERE type='table' AND name='import_checkpoints'")
            assert (await cursor.fetchone())["c"] == 0
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_reset_flag_restarts_cleanly(self, tmp_path):
        """--reset: чистый старт на уже импортированной БД не падает и не
        дублирует (INSERT OR IGNORE — запись идемпотентна)."""
        db_path = await _make_db(tmp_path, "reset.db")
        await import_history_fts(db_path, [CHAT_2026], TARGET_CHAT)
        before = await _counts(db_path)
        summary = await import_history_fts(db_path, [CHAT_2026], TARGET_CHAT,
                                           reset=True)
        assert summary["inserted"] == 0
        assert (await _counts(db_path))["total"] == before["total"]
        rows = await _checkpoint_rows(db_path)
        assert len(rows) == 1 and rows[0]["done"] == 1

    @pytest.mark.asyncio
    async def test_corrupt_file_aborts_with_checkpoint(self, tmp_path):
        """Структурный обрыв файла → стоп с ошибкой; уже записанные файлы
        импортированы; повторный запуск после исправления — без дублей."""
        db_path = await _make_db(tmp_path, "corrupt.db")
        bad = tmp_path / "bad.json"
        bad.write_text('{"name": "x", "messages": [{"id": 1}, ',
                       encoding="utf-8")
        good_stats = _fixture_stats(CHAT_2026)
        with pytest.raises(Exception):
            await import_history_fts(db_path, [CHAT_2026, str(bad)],
                                     TARGET_CHAT, batch_size=2)
        assert (await _counts(db_path))["total"] == len(good_stats["accepted"])
        # чекпоинт обрыва сохранён (done=0), good-файл — done=1
        rows = await _checkpoint_rows(db_path)
        by_path = {r["path"]: r for r in rows}
        assert by_path[str(bad)]["done"] == 0
        assert by_path[CHAT_2026]["done"] == 1
        # «исправленный» файл (запись дообрывалась) — повтор безопасен
        bad.write_text(json.dumps(
            {"name": "x", "id": 2661910336,
             "messages": [{"id": 2, "type": "message", "date": "2026-01-05",
                           "date_unixtime": "1767568000", "from": "А",
                           "from_id": "user1", "text": "новое",
                           "text_entities": []}]}), encoding="utf-8")
        summary = await import_history_fts(db_path, [CHAT_2026, str(bad)],
                                           TARGET_CHAT, batch_size=2)
        assert summary["inserted"] == 1
        assert (await _counts(db_path))["total"] == \
            len(good_stats["accepted"]) + 1
