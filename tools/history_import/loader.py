"""Фаза 2 (T-750, B3/T-753, C1) — FTS-загрузчик истории (smart_messages + FTS).

Потоковый разбор (parser.parse_items) → батчи по `--batch-size` (500), одна
транзакция на батч (spec §3.3):

1. `INSERT OR IGNORE INTO smart_messages (…, import_key) VALUES (…)`
   (tg_message_id — NULL: экспортные id отрицательны/коллизятся); rowcount == 0
   → дубль по import_key (partial UNIQUE-индекс v7/FR-6) — FTS-шаг
   пропускается (строка и её FTS-запись уже существуют: идемпотентность;
   edge 5 — FTS5 не знает о дублях rowid, пишем ТОЛЬКО при фактической
   вставке);
2. при вставке и непустом text: `INSERT INTO smart_messages_fts(rowid, text)
   VALUES (lastrowid, …)` (external content — ручная синхронизация, паттерн
   save_smart_message database.py:851-881);
3. чекпоинт import_checkpoints upsert (processed/total на текущий момент);
4. commit.

После всех файлов — `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM` (NFR-1).
Dry-run (`dry_run=True`) — только парсинг + статы (B5-аудит), БД вообще не
открывается, ничего не пишется (AC-8). Прогресс — tqdm-объект из CLI
(unit='msgs'); оценка total по прочитанным байтам — ETA на больших файлах.
"""
import dataclasses
import logging
import os
import time

import aiosqlite

from tools.history_import import checkpoints
from tools.history_import.parser import (
    BadTimestampError,
    normalize_message,
    parse_items,
)

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5000

_INSERT_SQL = (
    "INSERT OR IGNORE INTO smart_messages "
    "(user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
    "is_forward, forward_source, tg_message_id, import_key) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)"
)
_FTS_INSERT_SQL = "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)"


@dataclasses.dataclass
class FileResult:
    """Статистика обработки одного файла (принято/отсеяно/ошибки/скорость)."""

    path: str
    read: int = 0                # записей прочитано (messages.item)
    accepted: int = 0            # принято после нормализации
    inserted: int = 0            # фактически вставлено (только не dry-run)
    duplicates: int = 0          # дублей import_key (IGNORE / seen-set)
    with_text: int = 0           # принятых с непустым text (FTS-кандидаты)
    skipped_service: int = 0     # type != 'message'
    skipped_empty: int = 0       # пустой текст и нет медиа
    bad_ts: int = 0              # битый date_unixtime
    errors: int = 0              # структурные ошибки (записи/файл)
    duration: float = 0.0        # сек (разбор + запись)

    @property
    def skipped(self) -> int:
        return (self.skipped_service + self.skipped_empty
                + self.bad_ts + self.errors)

    def rate(self) -> float:
        return self.read / self.duration if self.duration else 0.0


class _CountingReader:
    """Файл + счётчик прочитанных байт: оценка total для ETA tqdm (ijson
    читает через read(n), без seek)."""

    def __init__(self, path: str):
        self._fh = open(path, "rb")
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._fh.read(size)
        self.bytes_read += len(chunk)
        return chunk

    def close(self) -> None:
        self._fh.close()


def _estimate_total(reader: _CountingReader, file_size: int,
                    seen: int) -> int | None:
    """Оценка общего числа сообщений файла: seen / consumed × size (первая
    стабильная оценка — после ~1% файла или 1000 записей)."""
    if reader.bytes_read <= 0 or seen < 1000:
        return None
    fraction = reader.bytes_read / max(1, file_size)
    if fraction < 0.01:
        return None
    return max(seen, int(seen / fraction))


async def _flush_batch(conn, fr: FileResult, buffer: list[dict],
                       path: str, est_total: int | None) -> None:
    """Батч в одной транзакции: INSERT smart_messages (+FTS при rowcount==1)
    + чекпоинт + commit (spec §3.3)."""
    for msg in buffer:
        row = (msg["user_id"], msg["chat_id"], msg["text"], msg["reply_to_id"],
               msg["timestamp"], msg["media_type"], msg["author_name"],
               msg["is_forward"], msg["forward_source"], msg["import_key"])
        cursor = await conn.execute(_INSERT_SQL, row)
        if cursor.rowcount == 1:
            fr.inserted += 1
            if msg["text"]:
                await conn.execute(_FTS_INSERT_SQL, (cursor.lastrowid,
                                                     msg["text"]))
        else:
            fr.duplicates += 1
    await checkpoints.mark(conn, path, fr.read, est_total or fr.read,
                           done=False)
    await conn.commit()
    buffer.clear()


async def load_file(conn, path: str, target_chat: int, *,
                    batch_size: int = 500, dry_run: bool = False,
                    progress=None) -> FileResult:
    """Один файл: потоковый разбор + батч-запись (+FTS) + чекпоинт.

    conn — соединение aiosqlite; при dry_run conn может быть None (чистая
    статистика без записи). Структурная ошибка файла (битый JSON/обрыв) →
    стоп файла с ошибкой и сохранённым чекпоинтом (повторный `--resume`
    безопасен — INSERT OR IGNORE; spec §3.3/edge 4)."""
    fr = FileResult(path=path)
    started = time.monotonic()
    file_size = os.path.getsize(path)
    reader = _CountingReader(path)
    buffer: list[dict] = []
    est_total: int | None = None
    aborted = False

    async def flush() -> None:
        if buffer:
            if dry_run:
                buffer.clear()
            else:
                await _flush_batch(conn, fr, buffer, path, est_total)

    try:
        for raw in parse_items(reader):
            if raw is None or not isinstance(raw, dict):
                continue
            fr.read += 1                 # «прочитано записей» — все записи файла
            try:
                msg = normalize_message(raw)
            except BadTimestampError:
                fr.bad_ts += 1
                fr.errors += 1
                if progress is not None:
                    progress.update(1)
                continue
            if msg is None:
                if raw.get("type") != "message":
                    fr.skipped_service += 1
                else:
                    fr.skipped_empty += 1
                if progress is not None:
                    progress.update(1)
                continue
            fr.accepted += 1
            if msg["text"]:
                fr.with_text += 1
            msg["chat_id"] = target_chat
            buffer.append(msg)
            if progress is not None:
                progress.update(1)
            if len(buffer) >= batch_size:
                await flush()
            if progress is not None:
                estimated = _estimate_total(reader, file_size, fr.read)
                if estimated is not None and estimated != est_total:
                    est_total = estimated
                    try:
                        progress.total = estimated
                        progress.refresh()
                    except Exception:
                        pass
        await flush()
        if not dry_run:
            await checkpoints.mark(conn, path, fr.read, est_total or fr.read,
                                   done=True)
            await conn.commit()
    except Exception as exc:
        aborted = True
        fr.errors += 1
        logger.warning("history import: файл остановлен с ошибкой | path=%s | "
                       "error=%s", path, exc)
        if not dry_run and conn is not None:
            try:
                await conn.rollback()
            except Exception:
                pass
            try:
                # чекпоинт обрыва всегда сохраняется (в т.ч. 0 строк —
                # признак «не завершён») — повторный --resume безопасен
                await checkpoints.mark(conn, path, fr.read,
                                       est_total or fr.read, done=False)
                await conn.commit()
            except Exception:
                pass
        raise
    finally:
        reader.close()
    fr.duration = time.monotonic() - started
    if progress is not None and not aborted:
        try:
            progress.set_description(
                f"{os.path.basename(path)} ({fr.inserted} new)"
                if not dry_run else f"{os.path.basename(path)} (ok)")
        except Exception:
            pass
    return fr


async def import_history_fts(db_path: str, files: list[str],
                             target_chat: int, *,
                             batch_size: int = 500, reset: bool = False,
                             dry_run: bool = False,
                             no_vacuum: bool = False,
                             progress=None) -> dict:
    """FTS-этап по файлам в ПЕРЕДАННОМ порядке (порядок = приоритет дедупа:
    «свежий первым» задаёт вызывающий — CLI). Идемпотентен (INSERT OR IGNORE
    по import_key); --reset — чистый старт (сброс чекпоинтов). Возвращает
    словарь-отчёт (files, inserted, duplicates, …, vacuumed)."""
    started = time.monotonic()
    results: list[FileResult] = []
    conn = None
    if not dry_run:
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        await conn.execute("PRAGMA journal_mode=WAL")
        await checkpoints.ensure_table(conn)
        if reset:
            await checkpoints.reset_many(conn, files)
            await conn.commit()
    try:
        for path in files:
            fr = await load_file(conn, path, target_chat,
                                 batch_size=batch_size, dry_run=dry_run,
                                 progress=progress)
            results.append(fr)
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
    inserted = sum(f.inserted for f in results)
    summary = {
        "files": results,
        "inserted": inserted,
        "duplicates": sum(f.duplicates for f in results),
        "accepted": sum(f.accepted for f in results),
        "read": sum(f.read for f in results),
        "with_text": sum(f.with_text for f in results),
        "skipped_service": sum(f.skipped_service for f in results),
        "skipped_empty": sum(f.skipped_empty for f in results),
        "errors": sum(f.errors for f in results),
        "dry_run": dry_run,
        "vacuumed": False,
        "duration": time.monotonic() - started,
    }
    if not dry_run and not no_vacuum and inserted > 0:
        summary["vacuumed"] = await vacuum_db(db_path)
    return summary


async def vacuum_db(db_path: str) -> bool:
    """Финальные `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM` (NFR-1)."""
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        cursor = await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        row = await cursor.fetchone()
        await conn.execute("VACUUM")
        logger.info("history import: vacuum done | checkpoint=%s",
                    row[0] if row else "?")
        return True
    finally:
        await conn.close()
