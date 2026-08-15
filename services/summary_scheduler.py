"""Epic 24 — APScheduler service for periodic summaries (R8, Section 33.10).

Cron 00:00/06:00/12:00/18:00 Asia/Yekaterinburg; MemoryJobStore ONLY;
max_instances=1 + coalesce=True (anti-race); start() before dp.start_polling.
"""
import asyncio
import logging

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings

logger = logging.getLogger(__name__)


class SummarySchedulerService:
    """Runs the summary pipeline on a fixed cron schedule."""

    JOB_ID = "summary_job"

    def __init__(self, generator, db) -> None:
        self._generator = generator
        self._db = db
        # MemoryJobStore only (default) — persistent stores break on pickle
        self._scheduler = AsyncIOScheduler(timezone=settings.SUMMARY_TIMEZONE)

    def start(self) -> None:
        self._scheduler.add_job(
            self._tick,
            CronTrigger(
                hour="0,6,12,18", minute=0, timezone=settings.SUMMARY_TIMEZONE
            ),
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "SmartModule scheduler started (cron 0,6,12,18 %s)",
            settings.SUMMARY_TIMEZONE,
        )

    async def _tick(self) -> None:
        target = settings.SUMMARY_TARGET_CHAT_IDS or await self._db.get_smart_chat_ids()
        for chat_id in target:
            await self._generator.generate_and_send(chat_id)

    async def shutdown(self) -> None:
        try:
            if self._scheduler.running:
                # AsyncIOScheduler._shutdown выполняется через call_soon_threadsafe —
                # даём event loop один тик, чтобы состояние реально стало STOPPED.
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("SmartModule scheduler stopped")
        except SchedulerNotRunningError:
            logger.info("SmartModule scheduler was not running — nothing to stop")
