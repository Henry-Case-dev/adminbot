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
import hashlib
import logging
import os
import time

import aiosqlite

from tools.history_import import checkpoints
from tools.history_import.parser import (
    BadTimestampError,
    detect_export_id,
    normalize_message,
    parse_items,
)
from services import mca_gates
from services.message_identity import message_content_hash

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5000


def _emit_import(event_name: str, outcome: str, *, level: str = "INFO",
                 exc: BaseException | None = None, stage: str | None = None,
                 **fields):
    """MCA-17 (`ingestion.import`): fail-open эмиссия (REUSE mca-13).

    CLI-инструмент: телеметрия не рвёт импорт (прецедент
    graphrag_rebuild._emit). R17: только счётчики/коды/длительность —
    пути файлов/тексты сообщений не переносятся."""
    try:
        from services.mca_events import build_error_metadata, emit_mca_event
        if exc is not None:
            fields["error_json"] = build_error_metadata(exc, stage=stage)
        emit_mca_event(event_name, outcome=outcome, level=level,
                       component="history_import", **fields)
    except Exception:      # контракт не рвёт импорт
        pass
# Legacy-namespace существующих (backfill v16) импортных строк: сохраняем для
# совместимости; НОВЫЕ импорты получают per-dataset namespace (см. ниже).
_LEGACY_IMPORT_NAMESPACE = "legacy_import_v1"


def _dataset_namespace(path: str) -> str:
    """Per-import namespace (ADR-1027-4 D2, B-MCA03-1).

    Экспортные record-id (``messages.item.id``) стабильны внутри чата, но
    пересекаются между разными экспортами. Общий литерал ``legacy_import_v1`` +
    ``UNIQUE (namespace, local_record_id)`` терял бы вхождения второго экспорта.
    Namespace выводится из идентичности партии: ``id`` шапки экспорта +
    отпечаток файла (abspath+size) — стабилен для повторного импорта того же
    файла и различает даже экспорты с одинаковой шапкой.

    L-MCA03-8 (mca-04b, ADR-1027-9): при включённом гейте
    ``MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED`` (default ON) отпечаток
    версионируется (``import:<tag>:v2:<content-digest>``) — digest включает
    content-fingerprint (полный стриминговый SHA-256 файла, M-MCA04B-1),
    поэтому in-place регенерация файла с ТЕМ ЖЕ размером получает новый
    namespace и source records НЕ пропускаются (v1-отпечаток абspath+size их
    молча терял). Повторный импорт НЕИЗМЕНЁННОГО файла даёт тот же namespace
    (дедуп работает). ``legacy_import_v1`` не переприсваивается; гейт OFF →
    прежний v1-отпечаток (паритет baseline)."""
    try:
        export_id = detect_export_id(path)
    except Exception:
        export_id = None
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    tag = str(export_id) if export_id is not None else "na"
    if _namespace_fingerprint_v2_enabled():
        content_digest = _file_content_digest(path)
        return f"import:{tag}:v2:{content_digest}"
    digest = hashlib.sha256(
        f"{os.path.abspath(path)}|{size}".encode("utf-8")).hexdigest()[:16]
    return f"import:{tag}:{digest}"


def _namespace_fingerprint_v2_enabled() -> bool:
    """Резолв гейта L-MCA03-8 per-call (никогда не бросает)."""
    try:
        from services import mca_gates
        return mca_gates.dossier_namespace_fingerprint_v2_enabled()
    except Exception:
        return True


def _file_content_digest(path: str) -> str:
    """Content-fingerprint файла — ПОЛНЫЙ стриминговый SHA-256 (M-MCA04B-1,
    review round 1: раньше хэшировалась только голова 256 KiB + size, поэтому
    регенерация файла >256 KiB с идентичной головой и тем же размером
    коллидировала и source records молча терялись). Чтение порциями —
    память не зависит от размера файла. Детерминирован для неизменённого
    файла; любое изменение байта меняет digest. Ошибка чтения → fallback
    на size+abspath-дайджест (никогда не бросает)."""
    try:
        size = os.path.getsize(path)
        hasher = hashlib.sha256()
        hasher.update(f"v2full|{size}|".encode("utf-8"))
        with open(path, "rb") as fh:
            while True:
                block = fh.read(1024 * 1024)
                if not block:
                    break
                hasher.update(block)
        return hasher.hexdigest()[:16]
    except OSError:
        return hashlib.sha256(
            f"v2|{os.path.abspath(path)}|{size}".encode("utf-8")
        ).hexdigest()[:16]

_INSERT_SQL = (
    "INSERT OR IGNORE INTO smart_messages "
    "(user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
    "is_forward, forward_source, tg_message_id, import_key) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)"
)
# MCA-03 (ADR-1027-4 D2/D3): импорт с namespace/source record, датой события
# и reply_to_kind='export'; `timestamp` сохранён как есть (дата события).
_INSERT_SQL_IDENTITY = (
    "INSERT OR IGNORE INTO smart_messages "
    "(user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
    "is_forward, forward_source, tg_message_id, import_key, caption, sent_at, "
    "ingested_at, sent_at_source, source_kind, namespace, source_record_id, "
    "content_hash, reply_to_kind, message_state, current_revision) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
    "'active', 1)"
)
_SOURCE_RECORD_SQL = (
    "INSERT OR IGNORE INTO message_source_records "
    "(message_id, namespace, local_record_id, tg_message_id, chat_id, "
    "source_kind, observed_at) VALUES (?, ?, ?, NULL, ?, 'import', ?)"
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
                       path: str, est_total: int | None,
                       chat_id: int) -> None:
    """Батч в одной транзакции: INSERT smart_messages (+FTS при rowcount==1)
    + чекпоинт + commit (spec §3.3). F7: чекпоинт ключуется (path, chat_id).

    MCA-03 (ADR-1027-4 D2/D3): при `MCA_MESSAGE_IDENTITY_ENABLED` (default ON)
    пишутся namespace (из `msg["namespace"]`)/source record/дата события/
    reply_to_kind; OFF — точный legacy-INSERT (паритет baseline)."""
    identity_on = mca_gates.message_identity_enabled()
    now = int(time.time())
    try:
        for msg in buffer:
            if identity_on:
                namespace = msg.get("namespace") or _LEGACY_IMPORT_NAMESPACE
                content_hash = msg.get("content_hash")
                if content_hash is None and (msg["text"] or msg.get("caption")):
                    content_hash = message_content_hash(msg["text"],
                                                        msg.get("caption"))
                row = (msg["user_id"], msg["chat_id"], msg["text"],
                       msg["reply_to_id"], msg["timestamp"], msg["media_type"],
                       msg["author_name"], msg["is_forward"],
                       msg["forward_source"], msg["import_key"],
                       msg.get("caption"), msg.get("sent_at"), now,
                       msg.get("sent_at_source"),
                       msg.get("source_kind") or "import",
                       namespace, msg.get("source_record_id"), content_hash,
                       msg.get("reply_to_kind"))
                cursor = await conn.execute(_INSERT_SQL_IDENTITY, row)
            else:
                row = (msg["user_id"], msg["chat_id"], msg["text"],
                       msg["reply_to_id"], msg["timestamp"], msg["media_type"],
                       msg["author_name"], msg["is_forward"],
                       msg["forward_source"], msg["import_key"])
                cursor = await conn.execute(_INSERT_SQL, row)
            if cursor.rowcount == 1:
                fr.inserted += 1
                if msg["text"]:
                    await conn.execute(_FTS_INSERT_SQL, (cursor.lastrowid,
                                                         msg["text"]))
                if identity_on and msg.get("source_record_id"):
                    ns = msg.get("namespace") or _LEGACY_IMPORT_NAMESPACE
                    await conn.execute(
                        _SOURCE_RECORD_SQL,
                        (cursor.lastrowid, ns, msg["source_record_id"],
                         chat_id, now))
            else:
                fr.duplicates += 1
        await checkpoints.mark(conn, path, chat_id, fr.read,
                               est_total or fr.read, done=False)
        await conn.commit()
    except Exception as exc:
        # MCA-17 (`ingestion.import`): notable WARN при ошибке батча
        # (терминал импорта эмитит import_history_fts). Чекпоинты
        # import_checkpoints — отдельный механизм, событиями НЕ дублируется.
        _emit_import("import_history_batch", "failed", level="WARN",
                     exc=exc, stage="flush_batch", chat_id=chat_id,
                     usage_json={"read": fr.read, "inserted": fr.inserted,
                                 "duplicates": fr.duplicates})
        raise
    buffer.clear()


async def load_file(conn, path: str, target_chat: int, *,
                    batch_size: int = 500, dry_run: bool = False,
                    progress=None,
                    namespace: str | None = None) -> FileResult:
    """Один файл: потоковый разбор + батч-запись (+FTS) + чекпойнт.

    conn — соединение aiosqlite; при dry_run conn может быть None (чистая
    статистика без записи). Структурная ошибка файла (битый JSON/обрыв) →
    стоп файла с ошибкой и сохранённым чекпойнтом (повторный `--resume`
    безопасен — INSERT OR IGNORE; spec §3.3/edge 4).

    `namespace=None` → per-dataset namespace файла (`_dataset_namespace`);
    явный namespace используется всеми записями файла (override)."""
    fr = FileResult(path=path)
    started = time.monotonic()
    file_size = os.path.getsize(path)
    if namespace is None:
        namespace = _dataset_namespace(path)
    reader = _CountingReader(path)
    buffer: list[dict] = []
    est_total: int | None = None
    aborted = False

    async def flush() -> None:
        if buffer:
            if dry_run:
                buffer.clear()
            else:
                await _flush_batch(conn, fr, buffer, path, est_total,
                                   target_chat)

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
            msg["namespace"] = namespace
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
            await checkpoints.mark(conn, path, target_chat, fr.read,
                                   est_total or fr.read, done=True)
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
                await checkpoints.mark(conn, path, target_chat, fr.read,
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
                             progress=None,
                             namespace: str | None = None) -> dict:
    """FTS-этап по файлам в ПЕРЕДАННОМ порядке (порядок = приоритет дедупа:
    «свежий первым» задаёт вызывающий — CLI). Идемпотентен (INSERT OR IGNORE
    по import_key); --reset — чистый старт (сброс чекпойнтов). Возвращает
    словарь-отчёт (files, inserted, duplicates, …, vacuumed).

    `namespace=None` (default) → у КАЖДОГО файла свой per-dataset namespace
    (B-MCA03-1: пересечение record-id между экспортами не теряет provenance);
    явный `namespace` — единый override для всех файлов."""
    started = time.monotonic()
    results: list[FileResult] = []
    conn = None
    if not dry_run:
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        await conn.execute("PRAGMA journal_mode=WAL")
        # F0.5 (ADR-1025-5 D3): PRAGMA-паритет с services/database.py:516-520.
        await conn.execute("PRAGMA synchronous=NORMAL")
        await checkpoints.ensure_table(conn)
        if reset:
            await checkpoints.reset_many(conn, files, target_chat)
            await conn.commit()
    try:
        for path in files:
            fr = await load_file(conn, path, target_chat,
                                 batch_size=batch_size, dry_run=dry_run,
                                 progress=progress, namespace=namespace)
            results.append(fr)
    except Exception as exc:
        # MCA-17 (`ingestion.import`): терминал прерванного импорта.
        _emit_import("import_history_fts", "failed", level="WARN",
                     exc=exc, stage="import", chat_id=target_chat,
                     usage_json={"files": len(results),
                                 "inserted": sum(f.inserted for f in results),
                                 "read": sum(f.read for f in results),
                                 "errors": sum(f.errors for f in results)},
                     duration_ms=int((time.monotonic() - started) * 1000))
        raise
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
    # MCA-17 (`ingestion.import`): терминал полного прогона. dry_run —
    # честный silent (записи не было). Счётчики сообщений — usage_json.
    _emit_import(
        "import_history_fts", "silent" if dry_run else "success",
        chat_id=target_chat,
        usage_json={"files": len(results), "inserted": inserted,
                    "duplicates": summary["duplicates"],
                    "read": summary["read"], "accepted": summary["accepted"],
                    "errors": summary["errors"]},
        duration_ms=int(summary["duration"] * 1000))
    return summary


async def vacuum_db(db_path: str) -> bool:
    """Финальные `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM` (NFR-1)."""
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        await conn.execute("PRAGMA synchronous=NORMAL")  # F0.5 D3: паритет
        cursor = await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        row = await cursor.fetchone()
        await conn.execute("VACUUM")
        logger.info("history import: vacuum done | checkpoint=%s",
                    row[0] if row else "?")
        return True
    finally:
        await conn.close()
