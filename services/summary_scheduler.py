"""Epic 24 — APScheduler service for periodic summaries (R8, Section 33.10).

Cron 00:00/06:00/12:00/18:00 Asia/Yekaterinburg; MemoryJobStore ONLY;
max_instances=1 + coalesce=True (anti-race); start() before dp.start_polling.

ASAP 8 v6.3 B06.1: единый резолвер per-chat Summary — здесь ОДНА точка
истины `summary_effective_enabled(chat_id)`; producer (cron/queue/trigger/
manual/retry через generate_and_send) следует этому резолверу.
"""
import asyncio
import logging
import os

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# ── ASAP 8 v6.3 B06.1: резолюция global default → explicit chat → env ──────

# Аварийный env-гейт (env-only, без Settings-поля): OFF блокирует ВСЕ
# сводки, включая явный chat ON (прод-инцидент-рубильник).
SUMMARY_EMERGENCY_ENV = "SUMMARY_EMERGENCY_DISABLE"

SOURCE_EMERGENCY = "emergency_env"
SOURCE_CHAT = "chat"
SOURCE_GLOBAL = "global"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def summary_emergency_disabled() -> bool:
    """Emergency env-ось (B06.1): `SUMMARY_EMERGENCY_DISABLE` честно
    включённый kill-switch; env OFF важнее UI/чата. Читается per-call."""
    return os.getenv(SUMMARY_EMERGENCY_ENV, "").strip().lower() in _TRUTHY


def summary_global_default() -> bool:
    """Global default-ось: hot `flags.summary_enabled` (default Settings)."""
    return bool(hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED))


async def summary_chat_override(chat_id: int):
    """Явный per-chat override `flags.summary_enabled` (bool) или None
    (inherit). Читается через chat_params (категория flags — per_chat)."""
    try:
        from services import chat_params
        return await chat_params.get_chat_param_defaulted(
            int(chat_id), "flags.summary_enabled", None)
    except Exception:            # pragma: no cover - fail-open к inherit
        return None


async def summary_effective_enabled(chat_id: int) -> tuple[bool, str]:
    """ЕДИНЫЙ резолвер Summary (B06.1): emergency env → explicit chat
    ON/OFF → global default. Возвращает ``(enabled, source)``;
    ``source`` — честная причина (emergency_env | chat | global)."""
    if summary_emergency_disabled():
        return False, SOURCE_EMERGENCY
    override = await summary_chat_override(chat_id)
    if override is not None:
        return bool(override), SOURCE_CHAT
    return summary_global_default(), SOURCE_GLOBAL


async def summary_any_chat_opted_in(pg=None) -> bool:
    """Есть ли хоть один чат с ЯВНЫМ chat=ON override (B06.1: явный chat ON
    при global OFF разрешает этот чат → producer обязан существовать).
    Грубый фильтр SQL + точная проверка JSON в Python; fail-open → False."""
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT p.chat_id, p.chat_params->'overrides' AS overrides "
                "FROM chat_profiles p "
                "WHERE p.chat_params ? 'overrides' "
                "AND p.chat_params->'overrides' IS NOT NULL")
    except Exception:            # pragma: no cover - PG down/fail-open
        return False
    for row in rows or []:
        overrides = row["overrides"] if not isinstance(row, dict) \
            else row.get("overrides")
        if isinstance(overrides, str):
            import json as _json
            try:
                overrides = _json.loads(overrides)
            except (ValueError, TypeError):
                continue
        if isinstance(overrides, dict) and \
                overrides.get("flags.summary_enabled") is True:
            return True
    return False


class SummarySchedulerService:
    """Runs the summary pipeline on a fixed cron schedule."""

    JOB_ID = "summary_job"

    def __init__(self, generator, db) -> None:
        self._generator = generator
        self._db = db
        # MemoryJobStore only (default) — persistent stores break on pickle
        self._scheduler = AsyncIOScheduler(timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE))

    def start(self) -> None:
        self._scheduler.add_job(
            self._tick,
            CronTrigger(
                hour="0,6,12,18", minute=0, timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
            ),
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        logger.info(
            "SmartModule scheduler started (cron 0,6,12,18 %s)",
            hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE),
        )

    async def _tick(self) -> None:
        target = hot.get("reactions.summary_target_chat_ids", settings.SUMMARY_TARGET_CHAT_IDS) or await self._db.get_smart_chat_ids()
        for raw_chat_id in target:
            # Хотфикс-5 (round10.25): chat_id из PG приходит строкой/NULL —
            # приводим к int ДО вызова, иначе per-chat override стиля не
            # резолвится (chat_params ключуется int). NULL/невалидные —
            # пропускаем, не роняя весь тик.
            try:
                chat_id = int(raw_chat_id)
            except (TypeError, ValueError):
                logger.warning(
                    "summary: invalid chat_id skipped | chat_id=%r",
                    raw_chat_id)
                continue
            # F-14 (S3, spec §4.2): ЛС-рассылки нет — положительные chat_id
            # (= user.id, DM-скоуп) исключаются из периодических саммари
            # (manual /summary в ЛС работает — S4, явный вызов).
            if chat_id > 0:
                logger.debug("dm summary skip: chat_id=%s", chat_id)
                continue
            # B06.1: cron реально следует per-chat резолверу (emergency →
            # chat override → global default), а не только /api/config.
            enabled, source = await summary_effective_enabled(chat_id)
            if not enabled:
                logger.info(
                    "summary: cron skip (disabled, source=%s) | chat_id=%s",
                    source, chat_id)
                continue
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
