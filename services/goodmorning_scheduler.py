"""Epic 30 — APScheduler-сервис утренней рассылки (R30-3, D88; 39.6.3).

Прецедент: services/summary_scheduler.py. CronTrigger(hour, minute,
timezone=tz), MemoryJobStore (default), max_instances=1 + coalesce=True
(утро не должно наступать дважды одновременно), start() ДО
dp.start_polling, shutdown() в on_shutdown.

Пустые TARGET_CHAT_IDS = рассылка выключена (D88): start() возвращает
False с WARNING, планировщик не стартует.
"""
import asyncio
import logging
import re
from zoneinfo import ZoneInfo

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from services.goodmorning_relay import GoodmorningRelay

logger = logging.getLogger(__name__)

DEFAULT_TZ = "Asia/Yekaterinburg"


def _parse_hhmm(value: str) -> tuple[int, int]:
    """'HH:MM' → (hour, minute). Кривой формат → WARNING + fallback (7, 0)."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if m and 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59:
        return int(m.group(1)), int(m.group(2))
    logger.warning("Goodmorning: invalid GOODMORNING_TIME %r — fallback 07:00", value)
    return 7, 0


class GoodmorningSchedulerService:
    """Утренний будильник чата: раз в сутки — медиа + капция."""

    JOB_ID = "goodmorning_job"

    def __init__(
        self,
        relay: GoodmorningRelay,
        time_str: str,
        tz: str,
        target_chat_ids: tuple[int, ...],
    ) -> None:
        self._relay = relay
        self._target_chat_ids = target_chat_ids
        try:
            ZoneInfo(tz)
            self._tz = tz
        except Exception:
            logger.warning(
                "Goodmorning: invalid GOODMORNING_TZ %r — fallback %s",
                tz,
                DEFAULT_TZ,
            )
            self._tz = DEFAULT_TZ
        self._hour, self._minute = _parse_hhmm(time_str)
        # MemoryJobStore only (default) — как в summary_scheduler
        self._scheduler = AsyncIOScheduler(timezone=self._tz)

    def start(self) -> bool:
        """Запуск ТОЛЬКО при непустых TARGET_CHAT_IDS (D88).

        Returns:
            True — планировщик стартовал; False — targets пусты
            (WARNING, рассылка выключена).
        """
        if not self._target_chat_ids:
            logger.warning(
                "Goodmorning: рассылка выключена — GOODMORNING_TARGET_CHAT_IDS пуст"
            )
            return False
        self._scheduler.add_job(
            self._tick,
            CronTrigger(hour=self._hour, minute=self._minute, timezone=self._tz),
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        # ОБЯЗАТЕЛЬНО внутри работающего event loop (APScheduler 3.11+, 39.1 п.4)
        self._scheduler.start()
        logger.info(
            "Goodmorning scheduler started (%02d:%02d %s, %d chats)",
            self._hour,
            self._minute,
            self._tz,
            len(self._target_chat_ids),
        )
        return True

    async def _tick(self) -> None:
        for chat_id in self._target_chat_ids:
            try:
                sent = await self._relay.send_goodmorning(chat_id)
                logger.info("Goodmorning tick: chat_id=%s sent=%s", chat_id, sent)
            except Exception:
                logger.exception("Goodmorning tick failed | chat_id=%s", chat_id)

    async def shutdown(self) -> None:
        """КОПИЯ паттерна summary_scheduler.py:51-60."""
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("Goodmorning scheduler stopped")
        except SchedulerNotRunningError:
            logger.info("Goodmorning scheduler was not running — nothing to stop")
