"""Фаза 2 (T-750, B3) — чекпоинты FTS-этапа (аддитивная таблица).

F7 (10.19, ADR-1019-6 D1b, UPD3 п.2): ключ чекпоинта — `(path, chat_id)`.
`import_checkpoints (path TEXT, chat_id INTEGER, processed INTEGER NOT NULL
DEFAULT 0, total INTEGER, done INTEGER NOT NULL DEFAULT 0, updated_at INTEGER,
PRIMARY KEY (path, chat_id))` — прогресс обработки файла ДЛЯ КОНКРЕТНОГО ЧАТА
(spec FR-4). Раньше ключевался только `path` → импорт того же файла во второй
чат видел чужой «done» (искажение прогресса). Создаётся CREATE IF NOT EXISTS
БЕЗ подъёма user_version (прецедент smart_cache R51-5); существующие БД
апгрейдит SQLite-миграция v11 (`DatabaseService`, legacy-строки → chat_id=0).
Философия (Q4): дедуп по import_key + INSERT OR IGNORE делает «resume после
обрыва» = перечитать файл с начала — чекпоинт служит прогрессу/статам.
"""
import time

IMPORT_CHECKPOINTS_DDL = (
    "CREATE TABLE IF NOT EXISTS import_checkpoints ("
    "path TEXT NOT NULL, "
    "chat_id INTEGER NOT NULL DEFAULT 0, "
    "processed INTEGER NOT NULL DEFAULT 0, "
    "total INTEGER, "
    "done INTEGER NOT NULL DEFAULT 0, "
    "updated_at INTEGER, "
    "PRIMARY KEY (path, chat_id))"
)


async def ensure_table(conn) -> None:
    """Таблица чекпоинтов в целевой БД (идемпотентно)."""
    await conn.execute(IMPORT_CHECKPOINTS_DDL)
    await conn.commit()


async def get(conn, path: str, chat_id: int = 0):
    """Строка чекпоинта файла для чата (None — не начинался/сброшен)."""
    cursor = await conn.execute(
        "SELECT path, chat_id, processed, total, done, updated_at "
        "FROM import_checkpoints WHERE path = ? AND chat_id = ?",
        (path, int(chat_id)))
    return await cursor.fetchone()


async def mark(conn, path: str, chat_id: int, processed: int,
               total: int | None, done: bool = False) -> None:
    """UPSERT прогресса (path, chat_id) после каждого батча (processed/total —
    на текущий момент файла; done=1 — файл завершён для ЭТОГО чата)."""
    await conn.execute(
        "INSERT INTO import_checkpoints "
        "(path, chat_id, processed, total, done, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (path, chat_id) DO UPDATE SET "
        "processed = excluded.processed, "
        "total = excluded.total, "
        "done = excluded.done, "
        "updated_at = excluded.updated_at",
        (path, int(chat_id), processed, total, 1 if done else 0,
         int(time.time())))


async def reset(conn, path: str, chat_id: int = 0) -> None:
    """Сброс чекпоинта файла для чата (--reset — чистый старт)."""
    await conn.execute(
        "DELETE FROM import_checkpoints WHERE path = ? AND chat_id = ?",
        (path, int(chat_id)))


async def reset_many(conn, paths: list[str], chat_id: int = 0) -> int:
    """Сброс чекпоинтов нескольких файлов чата; возвращает число удалённых
    строк."""
    if not paths:
        return 0
    cursor = await conn.execute(
        "DELETE FROM import_checkpoints WHERE chat_id = ? "
        "AND path IN (%s)" % ",".join("?" * len(paths)),
        [int(chat_id), *paths])
    return cursor.rowcount
