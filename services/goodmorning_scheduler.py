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
import time
from zoneinfo import ZoneInfo

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from services.goodmorning_relay import GoodmorningRelay

logger = logging.getLogger(__name__)

DEFAULT_TZ = "Asia/Yekaterinburg"


def _emit_goodmorning(event_name: str, outcome: str, *, level: str = "INFO",
                      **fields):
    """MCA-17 (`goodmorning.run`): fail-open эмиссия (REUSE mca-13).

    Прецедент graphrag_rebuild._emit; R17: только chat_id/счётчики/коды."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(event_name, outcome=outcome, level=level,
                       component="goodmorning", **fields)
    except Exception:      # контракт не рвёт планировщик
        pass


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
        """MCA-17 (`goodmorning.run`): один терминальный emit на тик —
        success (есть отправки) / silent (отправок не было) / skipped
        (пустые targets/гейт) / failed (исключение доставки). Релей
        (goodmorning_relay) не инструментируется — bot_output_ledger уже
        пишет доставку; R17: только счётчики, chat_id не переносятся."""
        started = time.monotonic()
        if not self._target_chat_ids:
            # D88: пустые targets — рассылка выключена (тик не должен
            # наступить, но прямой вызов/тест честно фиксируют skip).
            _emit_goodmorning("goodmorning_run", "skipped",
                              reason_code="disabled",
                              usage_json={"targets": 0})
            return
        sent = skipped = failures = 0
        for chat_id in self._target_chat_ids:
            try:
                # F7 (10.25, ADR-1025-20 D3): per-chat блок-гейт «Расписания».
                # OFF → рассылка этому чату НЕ отправляется (фоновая задача
                # «прекращается» для чата); остальные чаты не затронуты.
                from services import permsoc
                if not await permsoc.block_enabled(chat_id, "schedule"):
                    logger.info(
                        "Goodmorning tick skipped (permsoc_schedule OFF) | "
                        "chat_id=%s", chat_id)
                    skipped += 1
                    continue
                ok = await self._relay.send_goodmorning(chat_id)
                logger.info("Goodmorning tick: chat_id=%s sent=%s", chat_id, ok)
                if ok:
                    sent += 1
                else:
                    skipped += 1
            except Exception:
                failures += 1
                logger.exception("Goodmorning tick failed | chat_id=%s", chat_id)
        usage = {"targets": len(self._target_chat_ids), "sent": sent,
                 "skipped": skipped, "failed": failures}
        duration_ms = int((time.monotonic() - started) * 1000)
        if failures:
            _emit_goodmorning("goodmorning_run", "failed", level="WARN",
                              reason_code="delivery_unknown",
                              usage_json=usage, duration_ms=duration_ms)
        elif sent:
            _emit_goodmorning("goodmorning_run", "success",
                              usage_json=usage, duration_ms=duration_ms)
        else:
            # Ни одной отправки (гейты/пустая папка релея) и без ошибок —
            # честный silent, не success и не failed.
            _emit_goodmorning("goodmorning_run", "silent",
                              usage_json=usage, duration_ms=duration_ms)

    async def shutdown(self) -> None:
        """КОПИЯ паттерна summary_scheduler.py:51-60."""
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("Goodmorning scheduler stopped")
        except SchedulerNotRunningError:
            logger.info("Goodmorning scheduler was not running — nothing to stop")
