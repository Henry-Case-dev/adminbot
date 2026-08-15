"""Tests for services/summary_scheduler.py (T-183, R8)."""
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from services.summary_scheduler import SummarySchedulerService


@pytest.fixture
def service():
    generator = MagicMock()
    generator.generate_and_send = AsyncMock()
    db = MagicMock()
    db.get_smart_chat_ids = AsyncMock(return_value=[-100, -200])
    return SummarySchedulerService(generator, db)


class TestSchedulerConfig:
    @pytest.mark.asyncio
    async def test_cron_hours_minutes(self, service):
        service.start()
        try:
            job = service._scheduler.get_job("summary_job")
            assert isinstance(job.trigger, CronTrigger)
            fields = {f.name: f for f in job.trigger.fields}
            hour_exprs = [str(e) for e in fields["hour"].expressions]
            assert hour_exprs == ["0", "6", "12", "18"]
            minute_exprs = [str(e) for e in fields["minute"].expressions]
            assert minute_exprs == ["0"]
        finally:
            await service.shutdown()

    @pytest.mark.asyncio
    async def test_timezone_asia_yekaterinburg(self, service):
        service.start()
        try:
            job = service._scheduler.get_job("summary_job")
            assert str(job.trigger.timezone) == "Asia/Yekaterinburg"
            assert str(service._scheduler.timezone) == "Asia/Yekaterinburg"
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
    async def test_max_instances_and_coalesce(self, service):
        service.start()
        try:
            job = service._scheduler.get_job("summary_job")
            assert job.max_instances == 1
            assert job.coalesce is True
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
        mod = replace(settings, SUMMARY_TARGET_CHAT_IDS=(111, 222))
        with patch("services.summary_scheduler.settings", mod):
            await service._tick()
        assert generator.generate_and_send.await_count == 2
        generator.generate_and_send.assert_any_await(111)
        generator.generate_and_send.assert_any_await(222)
        db.get_smart_chat_ids.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_falls_back_to_db_chats(self):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[-100])
        service = SummarySchedulerService(generator, db)
        await service._tick()
        db.get_smart_chat_ids.assert_awaited_once()
        generator.generate_and_send.assert_awaited_once_with(-100)

    @pytest.mark.asyncio
    async def test_tick_no_chats_no_calls(self):
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[])
        service = SummarySchedulerService(generator, db)
        await service._tick()
        generator.generate_and_send.assert_not_called()


    @pytest.mark.asyncio
    async def test_tick_passes_no_manual_kwarg(self):
        """B2: cron-вызов без manual — scheduler не менялся."""
        generator = MagicMock()
        generator.generate_and_send = AsyncMock()
        db = MagicMock()
        db.get_smart_chat_ids = AsyncMock(return_value=[-100])
        service = SummarySchedulerService(generator, db)
        await service._tick()
        generator.generate_and_send.assert_awaited_once_with(-100)
        assert generator.generate_and_send.await_args.kwargs == {}
