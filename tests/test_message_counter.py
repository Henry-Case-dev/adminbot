import pytest
from unittest.mock import AsyncMock, MagicMock
from services.message_counter import MessageCounterMiddleware
from services.database import DatabaseService


class TestMessageCounterMiddleware:
    @pytest.mark.asyncio
    async def test_increments_counter(self):
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=1)
        
        middleware = MessageCounterMiddleware(mock_db)
        
        event = MagicMock()
        event.from_user.id = 479167456
        event.chat.id = -100123
        event.answer_animation = AsyncMock()
        
        handler = AsyncMock(return_value="done")
        data = {}
        
        result = await middleware(handler, event, data)
        
        mock_db.increment_and_get_count.assert_called_once_with(-100123, 479167456)
        handler.assert_called_once_with(event, data)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_sends_gif_on_5th_message(self):
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)
        
        middleware = MessageCounterMiddleware(mock_db)
        
        event = MagicMock()
        event.from_user.id = 479167456
        event.chat.id = -100123
        event.answer_animation = AsyncMock()
        
        handler = AsyncMock(return_value="done")
        
        await middleware(handler, event, {})
        
        event.answer_animation.assert_called_once()
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_gif_on_3rd_message(self):
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=3)
        
        middleware = MessageCounterMiddleware(mock_db)
        
        event = MagicMock()
        event.from_user.id = 479167456
        event.chat.id = -100123
        event.answer_animation = AsyncMock()
        
        handler = AsyncMock(return_value="done")
        
        await middleware(handler, event, {})
        
        event.answer_animation.assert_not_called()
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_gif_on_10th_message(self):
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=10)
        
        middleware = MessageCounterMiddleware(mock_db)
        
        event = MagicMock()
        event.from_user.id = 479167456
        event.chat.id = -100123
        event.answer_animation = AsyncMock()
        
        handler = AsyncMock(return_value="done")
        
        await middleware(handler, event, {})
        
        event.answer_animation.assert_called_once()

    @pytest.mark.asyncio
    async def test_gif_send_error_silently_handled(self):
        mock_db = AsyncMock(spec=DatabaseService)
        mock_db.increment_and_get_count = AsyncMock(return_value=5)
        
        middleware = MessageCounterMiddleware(mock_db)
        
        event = MagicMock()
        event.from_user.id = 479167456
        event.chat.id = -100123
        event.answer_animation = AsyncMock(side_effect=Exception("Network error"))
        
        handler = AsyncMock(return_value="done")
        
        result = await middleware(handler, event, {})
        
        handler.assert_called_once()
        assert result == "done"
