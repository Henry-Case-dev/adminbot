"""Фаза 2 (T-750, B3) — чекпоинты FTS-этапа (аддитивная таблица).

`import_checkpoints (path TEXT PRIMARY KEY, processed INTEGER NOT NULL DEFAULT
0, total INTEGER, done INTEGER NOT NULL DEFAULT 0, updated_at INTEGER)` —
прогресс обработки файла (spec FR-4). Создаётся CREATE IF NOT EXISTS БЕЗ
подъёма user_version (прецедент smart_cache R51-5). Философия (Q4): дедуп по
import_key + INSERT OR IGNORE делает «resume после обрыва» = перечитать файл
с начала (парсинг быстрый, дубли отбрасываются индексом за O(1)) — чекпоинт
служит прогрессу/статам и `--reset`, отдельные side-файлы не нужны.
"""
import time

IMPORT_CHECKPOINTS_DDL = (
    "CREATE TABLE IF NOT EXISTS import_checkpoints ("
    "path TEXT PRIMARY KEY, "
    "processed INTEGER NOT NULL DEFAULT 0, "
    "total INTEGER, "
    "done INTEGER NOT NULL DEFAULT 0, "
    "updated_at INTEGER)"
)


async def ensure_table(conn) -> None:
    """Таблица чекпоинтов в целевой БД (идемпотентно)."""
    await conn.execute(IMPORT_CHECKPOINTS_DDL)
    await conn.commit()


async def get(conn, path: str):
    """Строка чекпоинта файла (None — файл не начинался/сброшен)."""
    cursor = await conn.execute(
        "SELECT path, processed, total, done, updated_at "
        "FROM import_checkpoints WHERE path = ?", (path,))
    return await cursor.fetchone()


async def mark(conn, path: str, processed: int, total: int | None,
               done: bool = False) -> None:
    """UPSERT прогресса после каждого батча (processed/total — на текущий
    момент файла; done=1 — файл завершён)."""
    await conn.execute(
        "INSERT INTO import_checkpoints (path, processed, total, done, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (path) DO UPDATE SET "
        "processed = excluded.processed, "
        "total = excluded.total, "
        "done = excluded.done, "
        "updated_at = excluded.updated_at",
        (path, processed, total, 1 if done else 0, int(time.time())))


async def reset(conn, path: str) -> None:
    """Сброс чекпоинта файла (--reset — чистый старт)."""
    await conn.execute("DELETE FROM import_checkpoints WHERE path = ?", (path,))


async def reset_many(conn, paths: list[str]) -> int:
    """Сброс чекпоинтов нескольких файлов; возвращает число удалённых строк."""
    if not paths:
        return 0
    cursor = await conn.execute(
        "DELETE FROM import_checkpoints WHERE path IN (%s)"
        % ",".join("?" * len(paths)), paths)
    return cursor.rowcount
