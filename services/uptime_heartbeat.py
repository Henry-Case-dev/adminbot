"""Epic 85 (84.11.3, T-630) — heartbeat аптайма в uptime_events (PostgreSQL).

APScheduler AsyncIOScheduler в том же event loop:
  * джоб interval=60s → INSERT INTO uptime_events (status) VALUES ('up');
    ретраи до 3; при устойчивой ошибке PG — WARNING, бот жив (R6);
  * джоб раз в час → DELETE FROM uptime_events WHERE ts < now() - interval
    '<UPTIME_EVENTS_RETENTION_HOURS> hours' (env, дефолт 72).

PG недоступен (нет пула/DSN) → start() логирует WARNING и не стартует.
"""
import asyncio
import logging
import os

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 60
_CLEANUP_INTERVAL_HOURS = 1
_HEARTBEAT_RETRIES = 3
_HEARTBEAT_RETRY_DELAY = 1.0

_INSERT_SQL = "INSERT INTO uptime_events (status) VALUES ('up')"


class UptimeHeartbeatService:
    """60-секундный heartbeat + автоочистка uptime_events (84.11.3)."""

    def __init__(self, pg=None, retention_hours: int | None = None,
                 heartbeat_seconds: int = _HEARTBEAT_INTERVAL_SECONDS) -> None:
        self._pg = pg
        if retention_hours is None:
            try:
                retention_hours = int(
                    os.getenv("UPTIME_EVENTS_RETENTION_HOURS", "72"))
            except ValueError:
                retention_hours = 72
        self._retention_hours = max(1, retention_hours)
        self._heartbeat_seconds = max(5, heartbeat_seconds)
        self._scheduler = AsyncIOScheduler()
        self._running = False

    @property
    def retention_hours(self) -> int:
        return self._retention_hours

    def start(self) -> None:
        """Запуск джобов. PG недоступен → WARNING, бот жив (R6)."""
        if self._pg is None or getattr(self._pg, "pool", None) is None:
            logger.warning(
                "[uptime] heartbeat не запущен: PostgreSQL недоступен (R6)")
            return
        self._scheduler.add_job(
            self._heartbeat, IntervalTrigger(seconds=self._heartbeat_seconds),
            id="uptime_heartbeat", max_instances=1, coalesce=True)
        self._scheduler.add_job(
            self._cleanup, IntervalTrigger(hours=_CLEANUP_INTERVAL_HOURS),
            id="uptime_cleanup", max_instances=1, coalesce=True)
        self._scheduler.start()
        self._running = True
        logger.info("[uptime] heartbeat started: interval=%ds retention=%dh",
                    self._heartbeat_seconds, self._retention_hours)

    async def _heartbeat(self) -> None:
        """INSERT 'up' с ретраями до 3 (84.11.3)."""
        for attempt in range(1, _HEARTBEAT_RETRIES + 1):
            try:
                async with self._pg.pool.acquire() as conn:
                    await conn.execute(_INSERT_SQL)
                return
            except Exception:
                logger.warning(
                    "[uptime] heartbeat insert failed (попытка %d/%d)",
                    attempt, _HEARTBEAT_RETRIES, exc_info=True)
                await asyncio.sleep(_HEARTBEAT_RETRY_DELAY)
        logger.warning("[uptime] heartbeat failed после %d попыток — "
                       "PG недоступен, бот жив (R6)", _HEARTBEAT_RETRIES)

    async def _cleanup(self) -> None:
        """Автоочистка старше UPTIME_EVENTS_RETENTION_HOURS (84.11.3)."""
        try:
            async with self._pg.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM uptime_events "
                    "WHERE ts < now() - ($1::int * interval '1 hour')",
                    self._retention_hours)
        except Exception:
            logger.warning("[uptime] cleanup failed (PG down?) — R6",
                           exc_info=True)

    async def shutdown(self) -> None:
        if self._running:
            try:
                self._scheduler.shutdown(wait=False)
            except SchedulerNotRunningError:  # pragma: no cover
                pass
            self._running = False
            logger.info("[uptime] heartbeat stopped")
