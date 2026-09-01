"""Epic 60 (Section 64.3, T-464): бэкап БД раз в день + текстовый экспорт
фактов (читаемый глазами, для ручной правки).

MemoryBackupService — APScheduler-джоб daily в MEMORY_BACKUP_HOUR
(TZ SUMMARY_TIMEZONE); MemoryJobStore, max_instances=1 + coalesce (прецедент
summary_scheduler). НЕ на остановленном боте (онлайн — VACUUM INTO на живой
WAL-БД). Обе операции ленивы (пустая память → INFO-скип) и не роняют бота
(ошибки → WARNING). Ротация: последние MEMORY_BACKUP_KEEP файлов каждого вида.
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
        except Exception:
            logger.warning("memory_backup: daily job failed", exc_info=True)

    async def backup_and_export(self) -> None:
        """64.3: VACUUM INTO-копия + facts_*.txt; ленивый скип на пустой
        памяти; ротация KEEP."""
        cursor = await self._db.db.execute(
            "SELECT (SELECT COUNT(*) FROM graph_facts) + "
            "(SELECT COUNT(*) FROM smart_archive_facts)")
        row = await cursor.fetchone()
        if not row or not row[0]:
            logger.info("memory_backup: memory empty — backup/export skipped")
            return
        directory = Path(hot.get("reactions.memory_backup_dir", settings.MEMORY_BACKUP_DIR))
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("memory_backup: cannot create %s (%s) — skipped",
                           directory, exc)
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d")
        await self._backup_db(directory, stamp)
        await self._export_facts(directory, stamp)
        self._rotate(directory)

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
        """Держать последние MEMORY_BACKUP_KEEP файлов каждого вида."""
        try:
            for prefix, suffix in ((_BACKUP_PREFIX, "*.db"),
                                   (_EXPORT_PREFIX, "*.txt")):
                files = sorted(
                    (path for path in directory.glob(suffix)
                     if path.name.startswith(prefix)),
                    key=lambda p: p.name,
                )
                for old in files[:-hot.get("limits.memory_backup_keep", settings.MEMORY_BACKUP_KEEP)]:
                    try:
                        old.unlink()
                        logger.info("memory_backup: rotated out %s", old.name)
                    except OSError:
                        logger.warning("memory_backup: rotation unlink failed | %s",
                                       old.name)
        except Exception:
            logger.warning("memory_backup: rotation failed", exc_info=True)
