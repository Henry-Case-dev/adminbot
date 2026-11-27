"""SELF-DIAG-01 D6 (`SD1-D6-20`): derived-срезы ресурсов/очереди/БД.

Одна аддитивная таблица числовых срезов и три чистые операции над ней:
`record` (снять фактические значения), `prune` (ретенция), `series`
(окно для витрины). Писатель — СУЩЕСТВУЮЩИЙ 300-секундный тик
`services.memory_maintenance`; новых демонов/планировщиков/флагов нет.

Честность значений (главный контракт):
* первый системный `psutil.cpu_percent(None)` после старта процесса всегда
  `0.0` — это отсутствие измерения, а не ноль: пишем `NULL`;
* один модульный `psutil.Process` (идентичность/время старта/rss стабильны),
  отсутствующий файл (`-wal`/`-shm`) — `None`, а не `0` байт;
* очередь/файлы недоступны — `None` в конкретной колонке, остальные поля
  среза сохраняются.

Разделение процессов: каждая строка несёт `pid` и `process_started_at`;
`summarize` считает сегменты и агрегирует процессные поля только по
последнему (текущему) сегменту — через рестарт они не усредняются.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

SELF_DIAG_SAMPLES_TABLE = "self_diag_samples"
SELF_DIAG_SAMPLES_MIGRATION_STEP_NAME = "self_diag_samples_v49"
SELF_DIAG_SAMPLE_RETENTION_DAYS = 30
SELF_DIAG_SAMPLE_WINDOW_MAX_POINTS = 288
SELF_DIAG_SAMPLE_SOURCE = "maintenance_tick"

#: Точная DDL-форма (v49). Все числовые поля nullable: неизвестное — NULL.
SELF_DIAG_SAMPLES_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS self_diag_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    pid INTEGER,
    process_started_at INTEGER,
    app_version TEXT,
    cpu_percent REAL,
    cpu_count INTEGER,
    loadavg_1 REAL,
    mem_percent REAL,
    mem_used_bytes INTEGER,
    mem_total_bytes INTEGER,
    rss_mb REAL,
    disk_total_bytes INTEGER,
    disk_used_bytes INTEGER,
    disk_free_bytes INTEGER,
    db_bytes INTEGER,
    wal_bytes INTEGER,
    shm_bytes INTEGER,
    queue_depth INTEGER,
    queue_age_seconds INTEGER,
    active_jobs INTEGER,
    sample_source TEXT
)
"""

SELF_DIAG_SAMPLES_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_self_diag_samples_ts "
    "ON self_diag_samples (ts)",
)

#: Колонки INSERT (порядок = порядок значений в `_insert`).
SAMPLE_COLUMNS: tuple[str, ...] = (
    "ts", "pid", "process_started_at", "app_version", "cpu_percent",
    "cpu_count", "loadavg_1", "mem_percent", "mem_used_bytes",
    "mem_total_bytes", "rss_mb", "disk_total_bytes", "disk_used_bytes",
    "disk_free_bytes", "db_bytes", "wal_bytes", "shm_bytes", "queue_depth",
    "queue_age_seconds", "active_jobs", "sample_source",
)

#: Поля, отдаваемые витрине в `resources.samples` (плюс производный
#: `disk_percent`). Явный список — таблица не протекает целиком.
SERIES_COLUMNS: tuple[str, ...] = (
    "ts", "pid", "process_started_at", "app_version", "cpu_percent",
    "mem_percent", "rss_mb", "disk_total_bytes", "disk_used_bytes",
    "disk_free_bytes", "db_bytes", "wal_bytes", "queue_depth",
    "queue_age_seconds", "active_jobs", "sample_source",
)

_INSERT_SQL = (
    "INSERT INTO self_diag_samples ("
    + ", ".join(SAMPLE_COLUMNS)
    + ") VALUES ("
    + ", ".join("?" for _ in SAMPLE_COLUMNS)
    + ")"
)

#: Один `psutil.Process` на процесс: create_time/rss должны относиться к
#: одному и тому же объекту процесса, а не к пересоздаваемой обёртке.
_process_cache: psutil.Process | None = None
_host_cpu_primed = False


def reset_process_cache() -> None:
    """Сбросить кэш процесса/признак первого замера (тесты и пере-старт)."""
    global _process_cache, _host_cpu_primed
    _process_cache = None
    _host_cpu_primed = False


def _process() -> psutil.Process:
    global _process_cache
    if _process_cache is None:
        _process_cache = psutil.Process(os.getpid())
    return _process_cache


def _num(value):
    """Только настоящие числа (bool — не число измерений)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _file_size(path) -> int | None:
    """Размер файла или `None`, если файла нет (НЕ ноль байт)."""
    if path is None:
        return None
    try:
        candidate = Path(path)
        if not candidate.exists():
            return None
        return int(candidate.stat().st_size)
    except Exception:
        return None


def _host_cpu_percent() -> float | None:
    """Системный CPU: первый замер процесса — `None` (нет дельты)."""
    global _host_cpu_primed
    try:
        value = float(psutil.cpu_percent(interval=None))
    except Exception:
        return None
    if not _host_cpu_primed:
        _host_cpu_primed = True
        return None
    return value


def _process_started_at() -> int | None:
    """Старт процесса: типизированный `status.started_at_dt()`, затем psutil."""
    try:
        from services.status_service import status as _status
        moment = _status.started_at_dt()
        if moment is not None:
            return int(moment.timestamp())
    except Exception:
        pass
    try:
        return int(_process().create_time())
    except Exception:
        return None


def _app_version() -> str | None:
    try:
        from config.settings import APP_VERSION
        return str(APP_VERSION or "") or None
    except Exception:
        return None


async def _queue_stats(conn, *, now: int | None = None
                       ) -> tuple[int | None, int | None, int | None]:
    """(queued, oldest_age_seconds, running) из существующей `task_jobs`.

    Недоступность таблицы/запроса → `(None, None, None)`, а не нули.
    """
    try:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM task_jobs WHERE status = 'queued'")
        row = await cursor.fetchone()
        depth = int(row[0]) if row is not None else None
        cursor = await conn.execute(
            "SELECT MIN(created_at) FROM task_jobs WHERE status = 'queued'")
        row = await cursor.fetchone()
        oldest_age = None
        if row is not None and row[0] is not None:
            current = int(now if now is not None else time.time())
            oldest_age = max(0, current - int(row[0]))
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM task_jobs WHERE status = 'running'")
        row = await cursor.fetchone()
        active = int(row[0]) if row is not None else None
        return depth, oldest_age, active
    except Exception:
        logger.debug("[self-diag-samples] queue stats unavailable",
                     exc_info=True)
        return None, None, None


async def _collect(db, *, now: int | None = None) -> dict:
    """Снять один срез. Каждая секция fail-open в свою NULL-колонку."""
    values: dict = {name: None for name in SAMPLE_COLUMNS}
    values["sample_source"] = SELF_DIAG_SAMPLE_SOURCE
    values["pid"] = os.getpid()
    values["process_started_at"] = _process_started_at()
    values["app_version"] = _app_version()

    values["cpu_percent"] = _host_cpu_percent()
    try:
        cpu_count = psutil.cpu_count()
        values["cpu_count"] = int(cpu_count) if cpu_count else None
    except Exception:
        values["cpu_count"] = None
    if os.name == "posix":
        try:
            loadavg = psutil.getloadavg()
            values["loadavg_1"] = (float(loadavg[0]) if loadavg else None)
        except Exception:
            values["loadavg_1"] = None

    try:
        memory = psutil.virtual_memory()
        values["mem_percent"] = float(memory.percent)
        values["mem_used_bytes"] = int(memory.used)
        values["mem_total_bytes"] = int(memory.total)
    except Exception:
        pass

    try:
        proc = _process()
        values["rss_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        pass

    try:
        disk_path = "/" if os.name == "posix" else os.getcwd()
        disk = psutil.disk_usage(disk_path)
        values["disk_total_bytes"] = int(disk.total)
        values["disk_used_bytes"] = int(disk.used)
        values["disk_free_bytes"] = int(disk.free)
    except Exception:
        pass

    db_path = getattr(db, "db_path", None)
    values["db_bytes"] = _file_size(db_path)
    if db_path is not None:
        base = str(db_path)
        values["wal_bytes"] = _file_size(base + "-wal")
        values["shm_bytes"] = _file_size(base + "-shm")

    conn = getattr(db, "db", None)
    if conn is not None:
        depth, age, active = await _queue_stats(conn, now=now)
        values["queue_depth"] = depth
        values["queue_age_seconds"] = age
        values["active_jobs"] = active
    return values


async def record(db, *, now: int | None = None,
                 sample_source: str = SELF_DIAG_SAMPLE_SOURCE) -> bool:
    """Записать один срез. `False` — БД не готова (ничего не выдумываем)."""
    if db is None or getattr(db, "db", None) is None:
        return False
    ts = int(now if now is not None else time.time())
    values = await _collect(db, now=ts)
    values["ts"] = ts
    values["sample_source"] = str(sample_source or SELF_DIAG_SAMPLE_SOURCE)
    row = [values.get(name) for name in SAMPLE_COLUMNS]

    async def _body(conn):
        await conn.execute(_INSERT_SQL, tuple(row))

    await db.write_transaction(_body, op_name="self_diag_samples_record")
    return True


async def prune(db, *, now: int | None = None,
                retention_days: int = SELF_DIAG_SAMPLE_RETENTION_DAYS) -> int:
    """Удалить срезы старше ретенции; вернуть число удалённых строк."""
    if db is None or getattr(db, "db", None) is None:
        return 0
    cutoff = int(now if now is not None else time.time()) - int(
        max(1, retention_days) * 86400)

    async def _body(conn):
        cursor = await conn.execute(
            "DELETE FROM self_diag_samples WHERE ts < ?", (cutoff,))
        return int(cursor.rowcount or 0)

    return await db.write_transaction(
        _body, op_name="self_diag_samples_prune", commit_if=lambda _r: True)


async def series(db, *, since: int,
                 limit: int = SELF_DIAG_SAMPLE_WINDOW_MAX_POINTS
                 ) -> list[dict] | None:
    """Срезы окна по возрастанию `ts`; `None` — источник не прочитан."""
    if db is None or getattr(db, "db", None) is None:
        return None
    try:
        cursor = await db.db.execute(
            "SELECT " + ", ".join(SERIES_COLUMNS) + " FROM "
            + SELF_DIAG_SAMPLES_TABLE + " WHERE ts >= ? "
            "ORDER BY ts DESC LIMIT ?",
            (int(since), int(max(1, limit))))
        rows = [dict(row) for row in await cursor.fetchall()]
    except Exception:
        logger.warning("[self-diag-samples] series query failed",
                       exc_info=True)
        return None
    rows.reverse()
    return rows


def _segments(rows: list[dict]) -> int:
    """Число различных `(pid, process_started_at)` в окне."""
    pairs = {(row.get("pid"), row.get("process_started_at"))
             for row in rows if row.get("pid") is not None}
    return len(pairs)


def _reason_for(usable: int) -> str | None:
    if usable <= 0:
        return "no_history_yet"
    if usable == 1:
        return "single_sample"
    return None


def summarize(rows: list[dict]) -> dict:
    """Сводка по окну: сегменты, текущий процесс, рост БД/очереди.

    Процессные поля берутся ТОЛЬКО из последней строки (текущий сегмент),
    host-дельты считаются по всему окну и сопровождаются числом сегментов.
    """
    rows = list(rows or [])
    last = rows[-1] if rows else None
    process_current = None
    if last is not None and last.get("pid") is not None:
        process_current = {
            "pid": last.get("pid"),
            "process_started_at": last.get("process_started_at"),
            "cpu_percent": _num(last.get("cpu_percent")),
            "rss_mb": _num(last.get("rss_mb")),
            "mem_percent": _num(last.get("mem_percent")),
        }

    db_usable = [row for row in rows if _num(row.get("db_bytes")) is not None]
    db_first = db_usable[0] if db_usable else None
    db_last = db_usable[-1] if db_usable else None
    db_measured = len(db_usable) >= 2
    db_growth = wal_growth = free_delta = None
    if db_measured:
        db_growth = int(db_last["db_bytes"]) - int(db_first["db_bytes"])
        first_wal = _num(db_first.get("wal_bytes"))
        last_wal = _num(db_last.get("wal_bytes"))
        if first_wal is not None and last_wal is not None:
            wal_growth = int(last_wal) - int(first_wal)
        first_free = _num(db_first.get("disk_free_bytes"))
        last_free = _num(db_last.get("disk_free_bytes"))
        if first_free is not None and last_free is not None:
            free_delta = int(last_free) - int(first_free)

    def _db_point(row):
        if row is None:
            return None
        return {
            "ts": row.get("ts"),
            "db_bytes": _num(row.get("db_bytes")),
            "wal_bytes": _num(row.get("wal_bytes")),
            "disk_free_bytes": _num(row.get("disk_free_bytes")),
        }

    queue_usable = [row for row in rows
                    if _num(row.get("queue_depth")) is not None]
    q_first = queue_usable[0] if queue_usable else None
    q_last = queue_usable[-1] if queue_usable else None
    queue_measured = len(queue_usable) >= 2
    queue_delta = None
    if queue_measured:
        queue_delta = int(q_last["queue_depth"]) - int(q_first["queue_depth"])
    peak_depth = (max(int(row["queue_depth"]) for row in queue_usable)
                  if queue_usable else None)

    def _queue_point(row):
        if row is None:
            return None
        return {"ts": row.get("ts"), "depth": _num(row.get("queue_depth"))}

    return {
        "sample_count": len(rows),
        "segments": _segments(rows),
        "process_current": process_current,
        "db": {
            "measured": db_measured,
            "reason": _reason_for(len(db_usable)),
            "first": _db_point(db_first),
            "last": _db_point(db_last),
            "db_bytes_now": (_num(db_last.get("db_bytes"))
                             if db_last is not None else None),
            "wal_bytes_now": (_num(db_last.get("wal_bytes"))
                              if db_last is not None else None),
            "free_bytes_now": (_num(db_last.get("disk_free_bytes"))
                               if db_last is not None else None),
            "db_growth_bytes": db_growth,
            "wal_growth_bytes": wal_growth,
            "free_delta_bytes": free_delta,
        },
        "queue": {
            "measured": queue_measured,
            "reason": _reason_for(len(queue_usable)),
            "current": ({
                "depth": _num(q_last.get("queue_depth")),
                "oldest_age_seconds": _num(q_last.get("queue_age_seconds")),
            } if q_last is not None else None),
            "first": _queue_point(q_first),
            "last": _queue_point(q_last),
            "peak_depth": peak_depth,
            "delta_depth": queue_delta,
        },
    }


__all__ = [
    "SELF_DIAG_SAMPLES_TABLE",
    "SELF_DIAG_SAMPLES_MIGRATION_STEP_NAME",
    "SELF_DIAG_SAMPLES_DDL_SQLITE",
    "SELF_DIAG_SAMPLES_INDEX_DDL",
    "SELF_DIAG_SAMPLE_RETENTION_DAYS",
    "SELF_DIAG_SAMPLE_WINDOW_MAX_POINTS",
    "SELF_DIAG_SAMPLE_SOURCE",
    "SAMPLE_COLUMNS",
    "SERIES_COLUMNS",
    "reset_process_cache",
    "record",
    "prune",
    "series",
    "summarize",
]
