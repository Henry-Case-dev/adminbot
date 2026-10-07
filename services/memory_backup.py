"""Epic 60 (Section 64.3, T-464): бэкап БД раз в день + текстовый экспорт
фактов (читаемый глазами, для ручной правки).

MemoryBackupService — APScheduler-джоб daily в MEMORY_BACKUP_HOUR
(TZ SUMMARY_TIMEZONE); MemoryJobStore, max_instances=1 + coalesce (прецедент
summary_scheduler). НЕ на остановленном боте (онлайн — VACUUM INTO на живой
WAL-БД). Обе операции ленивы (пустая память → INFO-скип) и не роняют бота
(ошибки → WARNING). Ротация делегирована единому источнику истины
`services.disk_retention` (F9, ADR-1024-2 D1): DB-бэкапы — **ровно 1**
новейший суммарно по обоим префиксам (`local_database_*` + `memory_rebuild_*`),
`facts_*.txt` — 1 (пара к БД). Политика владельца (UPD3 №5): хранить 3+
бэкапов запрещено, поэтому hot-config `limits.memory_backup_keep` больше НЕ
расширяет окно БД.
"""
import asyncio
import datetime
import logging
from pathlib import Path

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

_BACKUP_PREFIX = "local_database_"
_EXPORT_PREFIX = "facts_"


def _emit_backup(outcome: str, *, level: str = "INFO",
                 exc: BaseException | None = None, **fields):
    """MCA-17 (`backup.memory`): терминал ежедневного job (REUSE mca-13,
    fail-open, прецедент graphrag_rebuild._emit). R17: только счётчики/
    коды — имена копий/пути не переносятся в событие."""
    try:
        from services.mca_events import build_error_metadata, emit_mca_event
        if exc is not None:
            fields["error_json"] = build_error_metadata(exc)
        emit_mca_event("memory_backup", outcome=outcome, level=level,
                       component="memory_backup", **fields)
    except Exception:      # контракт не рвёт бэкап
        pass


class MemoryBackupService:
    """Daily VACUUM INTO-бэкап + построчный текстовый экспорт фактов."""

    JOB_ID = "memory_backup_job"

    def __init__(self, db) -> None:
        self._db = db
        self._scheduler = AsyncIOScheduler(timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE))

    @staticmethod
    def _parse_hour(value: str) -> tuple[int, int]:
        try:
            hour, minute = str(value).split(":")
            return int(hour), int(minute)
        except (ValueError, AttributeError):
            logger.warning(
                "MEMORY_BACKUP_HOUR=%r invalid — default 05:00 (64.3)", value)
            return 5, 0

    def start(self) -> None:
        hour, minute = self._parse_hour(hot.get("limits.memory_backup_hour", settings.MEMORY_BACKUP_HOUR))
        self._scheduler.add_job(
            self._tick,
            CronTrigger(hour=hour, minute=minute,
                        timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)),
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "MemoryBackup scheduler started (daily %s %s)",
            hot.get("limits.memory_backup_hour", settings.MEMORY_BACKUP_HOUR), hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE),
        )

    async def shutdown(self) -> None:
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("MemoryBackup scheduler stopped")
        except SchedulerNotRunningError:
            logger.info("MemoryBackup scheduler was not running — nothing to stop")

    async def _tick(self) -> None:
        try:
            await self.backup_and_export()
        except Exception as exc:
            logger.warning("memory_backup: daily job failed", exc_info=True)
            # MCA-17 (`backup.memory`): терминал прерванного job.
            _emit_backup("failed", level="WARN", exc=exc)

    async def backup_and_export(self) -> None:
        """64.3: VACUUM INTO-копия + facts_*.txt; ленивый скип на пустой
        памяти; ротация KEEP. MCA-17: один терминальный emit на прогон —
        success / skipped (пустая память / каталог) / failed."""
        cursor = await self._db.db.execute(
            "SELECT (SELECT COUNT(*) FROM graph_facts) + "
            "(SELECT COUNT(*) FROM smart_archive_facts)")
        row = await cursor.fetchone()
        if not row or not row[0]:
            logger.info("memory_backup: memory empty — backup/export skipped")
            # MCA-17: честный skip (входа нет; reason-кода «пустой вход»
            # в словаре §17.2 нет — зафиксировано отчётом MCA-17).
            _emit_backup("skipped")
            return
        directory = Path(hot.get("reactions.memory_backup_dir", settings.MEMORY_BACKUP_DIR))
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("memory_backup: cannot create %s (%s) — skipped",
                           directory, exc)
            _emit_backup("failed", level="WARN", exc=exc)
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d")
        await self._backup_db(directory, stamp)
        await self._export_facts(directory, stamp)
        self._rotate(directory)
        # MCA-17: терминал успешного прогона (после _rotate).
        _emit_backup("success")

    async def _backup_db(self, directory: Path, stamp: str) -> None:
        target = directory / f"{_BACKUP_PREFIX}{stamp}.db"
        escaped = str(target).replace("'", "''")
        try:
            await self._db.db.execute(f"VACUUM INTO '{escaped}'")
            logger.info("memory_backup: VACUUM INTO -> %s", target)
            return
        except Exception as exc:
            logger.warning(
                "memory_backup: VACUUM INTO failed (%s) — subprocess fallback",
                exc,
            )
        await self._backup_subprocess(target)

    async def _backup_subprocess(self, target: Path) -> None:
        """Фоллбек на старом SQLite: sqlite3 CLI `.backup` (64.3, прецедент
        journalctl-subprocess в чекапе)."""
        try:
            process = await asyncio.create_subprocess_exec(
                "sqlite3", str(self._db.db_path), f".backup '{target}'",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode == 0:
                logger.info("memory_backup: sqlite3 .backup -> %s", target)
            else:
                logger.warning(
                    "memory_backup: sqlite3 .backup failed rc=%d stderr=%s",
                    process.returncode, (stderr or b"").decode(errors="replace")[:300])
        except FileNotFoundError:
            logger.warning("memory_backup: sqlite3 CLI not found — backup skipped")
        except Exception:
            logger.warning("memory_backup: subprocess backup failed", exc_info=True)

    async def _export_facts(self, directory: Path, stamp: str) -> None:
        """facts_*.txt — построчный дамп ЧИТАЕМЫЙ глазами (UTF-8, без JSON/
        экранирований): graph_facts (сортировка по created_at) +
        smart_archive_facts (сортировка по timestamp)."""
        try:
            cursor = await self._db.db.execute(
                "SELECT chat_id, fact, origin, status, weight, created_at "
                "FROM graph_facts ORDER BY created_at")
            graph_rows = await cursor.fetchall()
            cursor = await self._db.db.execute(
                "SELECT chat_id, fact FROM smart_archive_facts ORDER BY timestamp")
            archive_rows = await cursor.fetchall()
            lines = []
            for row in graph_rows:
                created = datetime.datetime.fromtimestamp(
                    row["created_at"]).strftime("%Y-%m-%d")
                lines.append(
                    f"[{row['chat_id']}] {row['origin']} {row['status']} "
                    f"weight={row['weight']:g} created={created} {row['fact']}")
            for row in archive_rows:
                lines.append(f"[archive] [{row['chat_id']}] {row['fact']}")
            target = directory / f"{_EXPORT_PREFIX}{stamp}.txt"
            target.write_text("\n".join(lines) + ("\n" if lines else ""),
                              encoding="utf-8")
            logger.info("memory_backup: exported %d lines -> %s",
                        len(lines), target)
        except Exception:
            logger.warning("memory_backup: facts export failed", exc_info=True)

    def _rotate(self, directory: Path) -> None:
        """Единый источник ротации (F9/ADR-1024-2 D1): DB-бэкапы — ровно 1
        новейший суммарно по обоим префиксам, `facts_*.txt` — 1 (пара к БД).

        Раньше ротация смотрела только `local_database_*` — safety-бэкапы
        `memory_rebuild_*.db` (~802 МБ) накапливались без ограничения
        (корневая причина роста диска +6.4 ГБ)."""
        try:
            from services.disk_retention import (
                prune_db_backups, prune_facts_exports)
            prune_db_backups(directory, keep=1)
            prune_facts_exports(directory, keep=1)
        except Exception:
            logger.warning("memory_backup: rotation failed", exc_info=True)


# ── Раунд 10.27 (MCA-14, ADR-1027-1 D2): backup ПЕРЕД миграцией схемы ───────
# Перед применением нового шага схемы runner вызывает `migration_backup`:
# `VACUUM INTO` (WAL-консистентная копия одним файлом) + проверка свободного
# места + read-back копии (`integrity_check`/`user_version`). Провал любой
# проверки → явная ошибка и отказ применять (никакого частичного применения).
# R17: в логах НЕТ полного пути/имени копии — только признак успеха/ошибки.

_MIGRATION_BACKUP_PREFIX = "pre_migration_"
# Коэффициент запаса свободного места (размер БД × K ≥ требуемому).
_FREE_SPACE_SAFETY = 2.0
# Ротация pre-migration копий: держим ровно 1 предыдущую (как daily-бэкап).
_MIGRATION_BACKUP_KEEP = 1


class MigrationBackupError(RuntimeError):
    """Провал backup/проверок перед миграцией (явный отказ применять шаг)."""


def _free_space_check(db_path: Path, target_dir: Path, factor: float) -> None:
    """Свободное место на целевом диске ≥ размер БД × factor.

    Недостаток → `MigrationBackupError` (R17-safe: без путей)."""
    import shutil
    try:
        db_size = db_path.stat().st_size if db_path.exists() else 0
        # L-MCA14-2: учесть WAL — консистентная копия включает и его содержимое,
        # иначе оценка свободного места занижена в WAL-тяжёлом состоянии.
        wal = db_path.with_name(db_path.name + "-wal")
        if wal.exists():
            db_size += wal.stat().st_size
    except OSError:
        db_size = 0
    try:
        usage = shutil.disk_usage(str(target_dir))
    except OSError as exc:
        raise MigrationBackupError(
            "backup: cannot read free space") from exc
    needed = int(db_size * factor)
    if usage.free < needed:
        raise MigrationBackupError(
            "backup: insufficient free space for migration copy")


def _read_back(target: Path, expected_user_version: int | None) -> None:
    """Копия читается: `PRAGMA integrity_check == ok` и совпадение версии.

    Провал → `MigrationBackupError` (R17-safe: без путей)."""
    import sqlite3
    conn = None
    try:
        conn = sqlite3.connect(str(target))
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise MigrationBackupError("backup: integrity_check != ok")
        if expected_user_version is not None:
            ver = conn.execute("PRAGMA user_version").fetchone()
            if ver is None or int(ver[0]) != int(expected_user_version):
                raise MigrationBackupError(
                    "backup: user_version mismatch in copy")
    except sqlite3.Error as exc:
        raise MigrationBackupError("backup: copy is not readable") from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


async def migration_backup(db, *, backup_dir: str | Path | None = None,
                           target_version: int | None = None) -> Path | None:
    """Backup перед миграцией (ADR-1027-1 D2). Возвращает путь копии или
    `None`, если backup неприменим (in-memory БД).

    * `:memory:`/пустой путь → `None` (бэкапить нечего; свежая БД).
    * `VACUUM INTO` из живого соединения (WAL-консистентно).
    * free-space check → `MigrationBackupError` при недостатке.
    * read-back → `MigrationBackupError` при нечитаемой копии.
    """
    raw = str(getattr(db, "db_path", "") or "")
    if raw in (":memory:", ""):
        return None
    db_path = Path(raw)
    if not db_path.exists():
        return None
    directory = Path(backup_dir) if backup_dir else db_path.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MigrationBackupError("backup: cannot create target dir") from exc
    _free_space_check(db_path, directory, _FREE_SPACE_SAFETY)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = directory / f"{_MIGRATION_BACKUP_PREFIX}{stamp}.db"
    if target.exists():
        # в пределах одной секунды/прошлый заход — свой уникальный суффикс
        import uuid as _uuid
        target = directory / (
            f"{_MIGRATION_BACKUP_PREFIX}{stamp}_{_uuid.uuid4().hex[:8]}.db")
    escaped = str(target).replace("'", "''")
    try:
        await db.db.execute(f"VACUUM INTO '{escaped}'")
    except Exception as exc:
        raise MigrationBackupError("backup: VACUUM INTO failed") from exc
    _read_back(target, target_version)
    logger.info(
        "memory_backup: pre-migration copy created + read-back ok | "
        "target_version=%s", target_version)
    try:
        from services.disk_retention import prune_migration_backups
        prune_migration_backups(directory, keep=_MIGRATION_BACKUP_KEEP)
    except Exception:
        logger.debug("memory_backup: pre-migration rotation failed",
                     exc_info=True)
    return target
