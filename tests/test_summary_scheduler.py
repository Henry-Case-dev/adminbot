"""Tests for services/summary_scheduler.py (T-183, R8).

UNIFIED-REPLY UR-C-SCHED (arch contract §4): глобальный cron
`0,6,12,18` заменён ОДНИМ тикером 60 c + per-chat локальные слоты
ChatClock + атомарный claim слотов. Тесты фиксируют НОВЫЙ контракт:

* в планировщике нет CronTrigger и глобального пояса (UR-BAN-06);
* анти-race семантика прежнего cron сохранена (max_instances=1,
  coalesce=True, MemoryJobStore);
* тик запускает генератор только внутри due-окна ЛОКАЛЬНОГО слота чата
  (по умолчанию Asia/Yekaterinburg = UTC+5), с now-инъекцией.
"""
import datetime
import zoneinfo
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from services import slot_claims
from services.summary_scheduler import SummarySchedulerService

pytestmark = pytest.mark.system2

#: 18:00 локального времени Asia/Yekaterinburg (+5) = 13:00 UTC; +30 c —
#: внутри due-окна слота (120 c). Yekaterinburg — без DST.
YEKAT = zoneinfo.ZoneInfo("Asia/Yekaterinburg")
DUE_UTC = datetime.datetime(2026, 1, 15, 13, 0, 30,
                            tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_slot_claims():
    """Деградационный in-process дедуп claim'ов не протекает между тестами."""
    slot_claims.reset_in_memory_claims()
    yield
    slot_claims.reset_in_memory_claims()


@pytest.fixture
def service():
    generator = MagicMock()
    generator.generate_and_send = AsyncMock()
    db = MagicMock()
    db.get_smart_chat_ids = AsyncMock(return_value=[-100, -200])
    return SummarySchedulerService(generator, db)


class TestSchedulerConfig:
    @pytest.mark.asyncio
    async def test_ticker_interval_and_anti_race(self, service):
        """UR-C-SCHED (§4.1): ОДИН тикер 60 c; анти-race семантика прежнего
        cron сохранена (max_instances=1, coalesce=True)."""
        service.start()
        try:
            job = service._scheduler.get_job("summary_job")
            assert isinstance(job.trigger, IntervalTrigger)
            assert job.trigger.interval == datetime.timedelta(seconds=60)
            assert job.max_instances == 1
            assert job.coalesce is True
        finally:
            await service.shutdown()

    @pytest.mark.asyncio
    async def test_no_parallel_global_cron(self, service):
        """UR-BAN-06: старого глобального cron `0,6,12,18` больше нет;
        локальные слоты чата вычисляет ChatClock, а не CronTrigger."""
        from apscheduler.triggers.cron import CronTrigger
        service.start()
        try:
            jobs = service._scheduler.get_jobs()
            assert len(jobs) == 1
            assert not isinstance(jobs[0].trigger, CronTrigger)
        finally:
            await service.shutdown()

    @pytest.mark.asyncio
    async def test_memory_jobstore_only(self, service):
        service.start()
        try:
            jobstore = service._scheduler._jobstores["default"]
            assert isinstance(jobstore, MemoryJobStore)
        finally:
            await service.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_without_start(self, service):
        await service.shutdown()  # не должно падать

    @pytest.mark.asyncio
    async def test_restart_after_shutdown(self, service):
        service.start()
        await service.shutdown()
        service.start()
        try:
            jobs = service._scheduler.get_jobs()
            assert len(jobs) == 1
        finally:
            await service.shutdown()


class TestTick:
    @pytest.mark.asyncio
    async def test_tick_uses_target_chat_ids(self):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[-999])
        service = SummarySchedulerService(generator, db)
        mod = replace(settings, SUMMARY_TARGET_CHAT_IDS=(-111, -222))
        with patch("services.summary_scheduler.settings", mod):
            await service._tick(now_utc=DUE_UTC)
        assert generator.generate_and_send.await_count == 2
        generator.generate_and_send.assert_any_await(-111)
        generator.generate_and_send.assert_any_await(-222)
        db.get_smart_chat_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_skips_dm_positive_ids(self):
        """F-14 (S3): ЛС-рассылки нет — положительные chat_id (DM-скоуп)
        исключаются из _tick (и из hot-источника, и из smart-чатов)."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[-100, 555])
        service = SummarySchedulerService(generator, db)
        mod = replace(settings, SUMMARY_TARGET_CHAT_IDS=(-777, 424242))
        with patch("services.summary_scheduler.settings", mod):
            await service._tick(now_utc=DUE_UTC)
        assert generator.generate_and_send.await_count == 1
        generator.generate_and_send.assert_awaited_once_with(-777)
        # фолбэк-источник (get_smart_chat_ids) — тот же фильтр
        generator.generate_and_send.reset_mock()
        slot_claims.reset_in_memory_claims()
        mod2 = replace(settings, SUMMARY_TARGET_CHAT_IDS=None)
        with patch("services.summary_scheduler.settings", mod2):
            await service._tick(now_utc=DUE_UTC)
        db.get_smart_chat_ids.assert_awaited_once()
        generator.generate_and_send.assert_awaited_once_with(-100)

    @pytest.mark.asyncio
    async def test_tick_falls_back_to_db_chats(self):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[-100])
        service = SummarySchedulerService(generator, db)
        await service._tick(now_utc=DUE_UTC)
        db.get_smart_chat_ids.assert_awaited_once()
        generator.generate_and_send.assert_awaited_once_with(-100)

    @pytest.mark.asyncio
    async def test_tick_no_chats_no_calls(self):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[])
        service = SummarySchedulerService(generator, db)
        await service._tick(now_utc=DUE_UTC)
        generator.generate_and_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_passes_no_manual_kwarg(self):
        """B2: cron-вызов без manual — scheduler не менялся."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[-100])
        service = SummarySchedulerService(generator, db)
        await service._tick(now_utc=DUE_UTC)
        generator.generate_and_send.assert_awaited_once_with(-100)
        assert generator.generate_and_send.await_args.kwargs == {}

    @pytest.mark.asyncio
    async def test_tick_outside_due_window_no_run(self):
        """UR-28.3: вне due-окна локального слота генератор не запускается
        (просроченный слот — честный skip, не запуск)."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[-100])
        service = SummarySchedulerService(generator, db)
        # 14:00 UTC = 19:00 local: слот 18:00 уже вне due-окна (120 c).
        late = datetime.datetime(2026, 1, 15, 14, 0, 0,
                                 tzinfo=datetime.timezone.utc)
        await service._tick(now_utc=late)
        generator.generate_and_send.assert_not_called()
