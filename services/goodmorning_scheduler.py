"""Epic 30 — APScheduler-сервис утренней рассылки (R30-3, D88; 39.6.3).

UNIFIED-REPLY UR-C-SCHED (arch contract §4.6, UR-28.5): per-chat
расписание. ОДИН тикер APScheduler (interval 60 c, `max_instances=1` +
`coalesce=True`) вместо глобального cron `GOODMORNING_TIME` в
`GOODMORNING_TZ`: `GOODMORNING_TIME` остаётся настраиваемым часом
рассылки, но пояс КАЖДОГО чата берётся только из ChatClock
(services/chat_clock.py — единственный резолвер, UR-24.3; отдельного
рабочего поля GOODMORNING_TZ у расписания больше нет — его цепочка
UR-24.3 поглощает как read-only legacy). Слот чата атомарно бронируется
(`services/slot_claims.py`, kind='goodmorning' — тот же claim-механизм,
что у саммари); дедуп «одно утро в день на чат» теперь держится claim'ом
(рестарт/повторный тик дубль не создают), просроченный тик — честный
skip (`missed_slot_expired`).

`target_chat_ids`, per-chat schedule gate («Расписания»), «нет target →
старт False» и ручная настройка времени сохранены; медиа-рассылка
(goodmorning_relay) не переписана.

MemoryJobStore (default), start() ДО dp.start_polling, shutdown() в
on_shutdown. Пустые TARGET_CHAT_IDS = рассылка выключена (D88): start()
возвращает False с WARNING, планировщик не стартует.
"""
import asyncio
import datetime
import logging
import re
import time

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.goodmorning_relay import GoodmorningRelay

logger = logging.getLogger(__name__)

CLAIM_KIND = "goodmorning"
TICKER_INTERVAL_SECONDS = 60


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
    """Утренний будильник чата: раз в сутки по ЛОКАЛЬНОМУ времени чата.

    `GOODMORNING_TIME` — час рассылки (семантика сохранена); пояс —
    ChatClock чата (UR-28.5). Один тикер на все target-чаты."""

    JOB_ID = "goodmorning_job"

    def __init__(
        self,
        relay: GoodmorningRelay,
        time_str: str,
        target_chat_ids: tuple[int, ...],
        db=None,
    ) -> None:
        self._relay = relay
        self._target_chat_ids = target_chat_ids
        self._db = db
        self._hour, self._minute = _parse_hhmm(time_str)
        self._slot_seq = ((self._hour, self._minute),)
        # MemoryJobStore only (default); пояс не задаётся — локальный слот
        # каждого чата вычисляет ChatClock (UR-C-SCHED).
        self._scheduler = AsyncIOScheduler()

    @property
    def send_time(self) -> tuple[int, int]:
        """(hour, minute) из GOODMORNING_TIME — час рассылки (UR-28.5)."""
        return self._hour, self._minute

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
        # ОДИН тикер на все чаты (arch §4.6): per-chat слот + claim на тике.
        self._scheduler.add_job(
            self._tick,
            IntervalTrigger(seconds=TICKER_INTERVAL_SECONDS),
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        # ОБЯЗАТЕЛЬНО внутри работающего event loop (APScheduler 3.11+, 39.1 п.4)
        self._scheduler.start()
        logger.info(
            "Goodmorning scheduler started (%02d:%02d chat-local via "
            "ChatClock, %d chats, ticker %ss)",
            self._hour,
            self._minute,
            len(self._target_chat_ids),
            TICKER_INTERVAL_SECONDS,
        )
        return True

    async def _tick(self, now_utc: datetime.datetime | None = None) -> None:
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
        from services.slot_claims import (
            GOODMORNING_DUE_WINDOW_SECONDS,
            claim_slot_if_due,
        )
        now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        sent = skipped = failures = 0
        for chat_id in self._target_chat_ids:
            try:
                # F7 (10.25, ADR-1025-20 D3): per-chat блок-гейт «Расписания».
                # OFF → рассылка этому чату НЕ отправляется (фоновая задача
                # «прекращается» для чата); остальные чаты не затронуты.
                # Гейт ДО claim: выключенный чат не съедает слот дня.
                from services import permsoc
                if not await permsoc.block_enabled(chat_id, "schedule"):
                    logger.info(
                        "Goodmorning tick skipped (permsoc_schedule OFF) | "
                        "chat_id=%s", chat_id)
                    skipped += 1
                    continue
                # UR-C-SCHED (§4.6): локальный слот GOODMORNING_TIME чата
                # через ChatClock + атомарный claim (дедуп запуска).
                verdict = await claim_slot_if_due(
                    kind=CLAIM_KIND, db=self._db, chat_id=int(chat_id),
                    now_utc=now, slot_seq=self._slot_seq,
                    due_window_s=GOODMORNING_DUE_WINDOW_SECONDS)
                if verdict.action != "fire":
                    logger.info(
                        "Goodmorning tick skipped (slot=%s) | chat_id=%s",
                        verdict.action, chat_id)
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
        """КОПИЯ паттерна summary_scheduler.py."""
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("Goodmorning scheduler stopped")
        except SchedulerNotRunningError:
            logger.info("Goodmorning scheduler was not running — nothing to stop")
