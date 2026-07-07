import asyncio
import datetime
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.scheduler import SchedulerService


class TestSchedulerService:
    @pytest.mark.asyncio
    async def test_send_dead_page_sends_photo_and_records(self):
        mock_bot = AsyncMock()
        mock_db = AsyncMock()
        
        scheduler = SchedulerService(mock_bot, mock_db)
        
        scheduler.media.pick_random = AsyncMock(
            return_value=("path/to/photo.jpg", "Some text content")
        )
        
        await scheduler._send_dead_page(-100123, "morning")
        
        mock_bot.send_photo.assert_called_once()
        mock_db.record_post.assert_called_once_with(-100123, "morning")

    @pytest.mark.asyncio
    async def test_send_dead_page_long_text_split(self):
        mock_bot = AsyncMock()
        mock_db = AsyncMock()
        
        scheduler = SchedulerService(mock_bot, mock_db)
        
        long_text = "A" * 2000
        
        scheduler.media.pick_random = AsyncMock(
            return_value=("path/to/photo.jpg", long_text)
        )
        
        await scheduler._send_dead_page(-100123, "morning")
        
        call_args = mock_bot.send_photo.call_args
        assert len(call_args[1]["caption"]) == 1024
        
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_dead_page_handles_missing_media(self):
        mock_bot = AsyncMock()
        mock_db = AsyncMock()
        
        scheduler = SchedulerService(mock_bot, mock_db)
        scheduler.media.pick_random = AsyncMock(
            side_effect=FileNotFoundError("No .jpg files")
        )
        
        await scheduler._send_dead_page(-100123, "morning")
        
        mock_bot.send_photo.assert_not_called()
        mock_db.record_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_signal_immediate_post_dedup(self):
        mock_bot = AsyncMock()
        mock_db = AsyncMock()
        
        scheduler = SchedulerService(mock_bot, mock_db)
        scheduler._send_dead_page = AsyncMock()
        
        chat_id = -100123
        
        await scheduler.signal_immediate_post(chat_id)
        scheduler._send_dead_page.assert_called_once_with(chat_id, 'join')
        
        scheduler._send_dead_page.reset_mock()
        await scheduler.signal_immediate_post(chat_id)
        scheduler._send_dead_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_posts_morning_slot(self):
        mock_bot = AsyncMock()
        mock_db = AsyncMock()
        mock_db.get_present_chats = AsyncMock(return_value=[-100123])
        mock_db.has_post_today = AsyncMock(return_value=False)
        
        scheduler = SchedulerService(mock_bot, mock_db)
        scheduler._send_dead_page = AsyncMock()
        
        with patch('services.scheduler.datetime') as mock_datetime:
            mock_now = MagicMock()
            mock_now.hour = 10
            mock_datetime.datetime.now.return_value = mock_now
            
            await scheduler._tick()
            
            scheduler._send_dead_page.assert_called_once_with(-100123, 'morning')

    @pytest.mark.asyncio
    async def test_tick_skips_already_posted(self):
        mock_bot = AsyncMock()
        mock_db = AsyncMock()
        mock_db.get_present_chats = AsyncMock(return_value=[-100123])
        mock_db.has_post_today = AsyncMock(return_value=True)
        
        scheduler = SchedulerService(mock_bot, mock_db)
        scheduler._send_dead_page = AsyncMock()
        
        with patch('services.scheduler.datetime') as mock_datetime:
            mock_now = MagicMock()
            mock_now.hour = 10
            mock_datetime.datetime.now.return_value = mock_now
            
            await scheduler._tick()
            
            scheduler._send_dead_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_no_present_chats(self):
        mock_bot = AsyncMock()
        mock_db = AsyncMock()
        mock_db.get_present_chats = AsyncMock(return_value=[])
        mock_db.has_post_today = AsyncMock(return_value=False)
        
        scheduler = SchedulerService(mock_bot, mock_db)
        scheduler._send_dead_page = AsyncMock()
        
        with patch('services.scheduler.datetime') as mock_datetime:
            mock_now = MagicMock()
            mock_now.hour = 10
            mock_datetime.datetime.now.return_value = mock_now
            
            await scheduler._tick()
            
            scheduler._send_dead_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_outside_posting_window(self):
        mock_bot = AsyncMock()
        mock_db = AsyncMock()
        mock_db.get_present_chats = AsyncMock(return_value=[-100123])
        
        scheduler = SchedulerService(mock_bot, mock_db)
        scheduler._send_dead_page = AsyncMock()
        
        with patch('services.scheduler.datetime') as mock_datetime:
            mock_now = MagicMock()
            mock_now.hour = 3
            mock_datetime.datetime.now.return_value = mock_now
            
            await scheduler._tick()
            
            scheduler._send_dead_page.assert_not_called()
