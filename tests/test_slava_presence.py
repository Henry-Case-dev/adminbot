import pytest
from unittest.mock import AsyncMock, patch
from aiogram.dispatcher.event.bases import UNHANDLED
from handlers.slava_presence import on_user_join, on_user_leave, on_new_slava_member


class TestSlavaPresence:
    @pytest.mark.asyncio
    async def test_slava_join_triggers_message(self, make_chat_member_updated):
        event = make_chat_member_updated(479167456, "left", "member")
        with patch("handlers.slava_presence._db", new=AsyncMock()), \
             patch("handlers.slava_presence._scheduler", new=AsyncMock()):
            await on_user_join(event)
        
        event.bot.send_message.assert_called_once()
        args, kwargs = event.bot.send_message.call_args
        assert kwargs["text"] == "ДОЛБОЕБ ВЕРНУЛСЯ"

    @pytest.mark.asyncio
    async def test_non_slava_join_ignored(self, make_chat_member_updated):
        event = make_chat_member_updated(99999, "left", "member")
        with patch("handlers.slava_presence._db", new=AsyncMock()), \
             patch("handlers.slava_presence._scheduler", new=AsyncMock()):
            await on_user_join(event)
        
        event.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_slava_leave_updates_presence(self, make_chat_member_updated):
        event = make_chat_member_updated(479167456, "member", "left")
        mock_db = AsyncMock()
        with patch("handlers.slava_presence._db", new=mock_db), \
             patch("handlers.slava_presence._scheduler", new=AsyncMock()):
            await on_user_leave(event)
        
        mock_db.set_presence.assert_called_once_with(479167456, event.chat.id, False)

    @pytest.mark.asyncio
    async def test_non_slava_leave_ignored(self, make_chat_member_updated):
        event = make_chat_member_updated(99999, "member", "left")
        mock_db = AsyncMock()
        with patch("handlers.slava_presence._db", new=mock_db), \
             patch("handlers.slava_presence._scheduler", new=AsyncMock()):
            await on_user_leave(event)
        
        mock_db.set_presence.assert_not_called()

    @pytest.mark.asyncio
    async def test_slava_join_updates_presence(self, make_chat_member_updated):
        event = make_chat_member_updated(479167456, "left", "member")
        mock_db = AsyncMock()
        with patch("handlers.slava_presence._db", new=mock_db), \
             patch("handlers.slava_presence._scheduler", new=AsyncMock()):
            await on_user_join(event)
        
        mock_db.set_presence.assert_called_once_with(479167456, event.chat.id, True)

    @pytest.mark.asyncio
    async def test_slava_join_calls_scheduler(self, make_chat_member_updated):
        event = make_chat_member_updated(479167456, "left", "member")
        mock_scheduler = AsyncMock()
        with patch("handlers.slava_presence._db", new=AsyncMock()), \
             patch("handlers.slava_presence._scheduler", new=mock_scheduler):
            await on_user_join(event)
        
        mock_scheduler.signal_immediate_post.assert_called_once_with(event.chat.id)

    @pytest.mark.asyncio
    async def test_on_user_join_returns_unhandled_for_non_slava(self, make_chat_member_updated):
        event = make_chat_member_updated(99999, "left", "member")
        with patch("handlers.slava_presence._db", new=AsyncMock()), \
             patch("handlers.slava_presence._scheduler", new=AsyncMock()):
            result = await on_user_join(event)
        
        assert result is UNHANDLED
        assert result is not None

    @pytest.mark.asyncio
    async def test_on_user_leave_returns_unhandled_for_non_slava(self, make_chat_member_updated):
        event = make_chat_member_updated(99999, "member", "left")
        mock_db = AsyncMock()
        with patch("handlers.slava_presence._db", new=mock_db), \
             patch("handlers.slava_presence._scheduler", new=AsyncMock()):
            result = await on_user_leave(event)
        
        assert result is UNHANDLED
        mock_db.set_presence.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_new_slava_member_returns_unhandled_for_non_slava(self):
        from unittest.mock import MagicMock
        
        msg = MagicMock()
        other_user = MagicMock()
        other_user.id = 99999
        msg.new_chat_members = [other_user]
        msg.chat = MagicMock()
        msg.chat.id = -1001234567890
        msg.reply = AsyncMock()
        
        with patch("handlers.slava_presence._db", new=AsyncMock()), \
             patch("handlers.slava_presence._scheduler", new=AsyncMock()):
            result = await on_new_slava_member(msg)
        
        assert result is UNHANDLED
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_new_slava_member_returns_unhandled_when_empty(self):
        from unittest.mock import MagicMock
        
        msg = MagicMock()
        msg.new_chat_members = None
        
        result = await on_new_slava_member(msg)
        
        assert result is UNHANDLED
