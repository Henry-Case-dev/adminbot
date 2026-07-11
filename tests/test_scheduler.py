import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.scheduler import SchedulerService
from config.settings import settings


class TestSchedulerServiceV2:
    """Tests for simplified SchedulerService (Dead Page V2)."""

    @pytest.fixture
    def mock_relay(self):
        """Mock DeadPageRelay."""
        relay = MagicMock()
        relay.send_dead_page = AsyncMock()
        return relay

    @pytest.fixture
    def scheduler(self, mock_relay):
        return SchedulerService(relay=mock_relay, target_user_id=settings.SLAVIK_USER_ID)

    @pytest.mark.asyncio
    async def test_signal_immediate_post_calls_relay(self, scheduler, mock_relay):
        """Join trigger should delegate to DeadPageRelay."""
        chat_id = -100123
        await scheduler.signal_immediate_post(chat_id)
        mock_relay.send_dead_page.assert_called_once_with(chat_id, slot="join")

    @pytest.mark.asyncio
    async def test_signal_immediate_post_dedup(self, scheduler, mock_relay):
        """Second call within DEDUP_WINDOW should be ignored."""
        chat_id = -100123
        await scheduler.signal_immediate_post(chat_id)
        await scheduler.signal_immediate_post(chat_id)
        assert mock_relay.send_dead_page.call_count == 1

    @pytest.mark.asyncio
    async def test_signal_immediate_post_no_relay(self):
        """Without relay, should log error but not crash."""
        scheduler = SchedulerService(relay=None)
        await scheduler.signal_immediate_post(-100123)

    @pytest.mark.asyncio
    async def test_scheduler_has_no_tick_method(self, scheduler):
        """V2 scheduler should not have _tick or _send_dead_page."""
        assert not hasattr(scheduler, '_tick')
        assert not hasattr(scheduler, '_send_dead_page')

    @pytest.mark.asyncio
    async def test_signal_immediate_post_respects_join_config(self, mock_relay):
        """When DEAD_PAGE_POST_ON_JOIN=False, should skip."""
        scheduler = SchedulerService(relay=mock_relay, post_on_join=False)
        await scheduler.signal_immediate_post(-100123)
        mock_relay.send_dead_page.assert_not_called()
