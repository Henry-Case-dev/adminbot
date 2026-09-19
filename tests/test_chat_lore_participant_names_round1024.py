"""Раунд 10.24 (UPD4-D / F18 `sqlite-row-get-fix-round1024`).

Регресс-тесты `web/api/chat_lore.py::_participant_names`.

Баг: функция читала поля строки как у словаря (`r.get("user_id")`),
но источник — `aiosqlite.Row` (это `sqlite3.Row`) без метода `.get` →
`AttributeError`, который глотался широким `except` → имена участников
терялись (uid-fallback). Фикс: канонический `services.database.row_get`
(ADR-1024-19). Тесты работают на **настоящих** `sqlite3.Row`, а не на
dict-заглушках, чтобы регресс не мог спрятаться за тихим `except`.
"""
import sqlite3

import pytest

from web.api.chat_lore import _participant_names


def _real_rows(sql: str, params: tuple = ()) -> list:
    """Настоящие `sqlite3.Row` из in-memory SQLite (как aiosqlite.Row)."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params)
        return cursor.fetchall()
    finally:
        conn.close()


class _FakeDB:
    """Минимальный db-стаб: только `get_active_participants`."""

    def __init__(self, rows):
        self._rows = rows
        self.calls: list = []

    async def get_active_participants(self, chat_id, since_ts, cap):
        self.calls.append((chat_id, since_ts, cap))
        return self._rows


def test_sqlite_row_has_no_get_method():
    """Корень бага: у `sqlite3.Row` нет `.get` (в отличие от asyncpg Record)."""
    (row,) = _real_rows("SELECT 1 AS user_id, 'Аня' AS author_name")
    assert not hasattr(row, "get")
    # subscript при этом работает — на нём и строится `row_get`.
    assert row["user_id"] == 1
    assert row["author_name"] == "Аня"


@pytest.mark.asyncio
async def test_participant_names_real_sqlite_row_no_attribute_error():
    """§6.1: реальные `sqlite3.Row` → не бросаем, возвращаем {1: 'Аня'}."""
    rows = _real_rows("SELECT 1 AS user_id, 'Аня' AS author_name")
    db = _FakeDB(rows)

    names = await _participant_names(db, -100500)

    assert names == {1: "Аня"}


@pytest.mark.asyncio
async def test_participant_names_mapping_and_filtering():
    """§6.2: пустые/пробельные имена, user_id=0/NULL пропускаются;
    значения не чистятся (эмодзи/пробелы внутри — дословно)."""
    rows = _real_rows(
        "SELECT 1 AS user_id, '  Аня 😀 ' AS author_name "
        "UNION ALL SELECT 2, '   ' "
        "UNION ALL SELECT 3, '' "
        "UNION ALL SELECT 0, 'Ноль' "
        "UNION ALL SELECT NULL, 'Никто' "
        "UNION ALL SELECT 4, 'Борис'")
    db = _FakeDB(rows)

    names = await _participant_names(db, -100500)

    assert names == {1: "  Аня 😀 ", 4: "Борис"}


@pytest.mark.asyncio
async def test_participant_names_empty_result_returns_none():
    """§6.3: нет строк → None (штатный uid-fallback, не ошибка)."""
    empty_db = _FakeDB([])
    assert await _participant_names(empty_db, -100500) is None

    # все строки отфильтрованы → тоже None.
    filtered_db = _FakeDB(_real_rows(
        "SELECT 0 AS user_id, 'Ноль' AS author_name "
        "UNION ALL SELECT 1, '   '"))
    assert await _participant_names(filtered_db, -100500) is None


@pytest.mark.asyncio
async def test_participant_names_missing_column_no_crash():
    """§6.4: строки без колонки `author_name` → row_get даёт default,
    строка пропускается, падения нет."""
    rows = _real_rows("SELECT 1 AS user_id UNION ALL SELECT 2")
    for r in rows:
        assert "author_name" not in r.keys()
    db = _FakeDB(rows)

    assert await _participant_names(db, -100500) is None


@pytest.mark.asyncio
async def test_participant_names_dict_rows_compat():
    """§6.5: dict-строки продолжают работать (row_get не регрессирует)."""
    db = _FakeDB([
        {"user_id": 7, "author_name": "Дима"},
        {"user_id": 8, "author_name": " "},
        {"user_id": None, "author_name": "Никто"},
    ])

    names = await _participant_names(db, -100500)

    assert names == {7: "Дима"}
