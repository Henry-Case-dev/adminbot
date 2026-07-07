import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_bot():
    """Mock aiogram Bot instance."""
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_animation = AsyncMock()
    return bot


@pytest.fixture
def make_message():
    """Factory fixture to create mock Message objects."""
    def _make(from_id: int, text: str | None = None, chat_id: int = -1001234567890,
              username: str | None = None, **kwargs):
        msg = MagicMock()
        msg.text = text
        msg.chat = MagicMock()
        msg.chat.id = chat_id
        msg.from_user = MagicMock()
        msg.from_user.id = from_id
        msg.from_user.username = username
        msg.reply = AsyncMock()
        msg.answer = AsyncMock()
        msg.answer_animation = AsyncMock()
        # Apply extra kwargs
        for k, v in kwargs.items():
            setattr(msg, k, v)
        return msg
    return _make


@pytest.fixture
def make_chat_member_updated():
    """Factory fixture to create mock ChatMemberUpdated objects."""
    def _make(user_id: int, old_status: str, new_status: str, chat_id: int = -1001234567890):
        event = MagicMock()
        event.chat = MagicMock()
        event.chat.id = chat_id
        event.bot = AsyncMock()
        event.bot.send_message = AsyncMock()
        
        event.old_chat_member = MagicMock()
        event.old_chat_member.status = old_status
        event.old_chat_member.user = MagicMock()
        event.old_chat_member.user.id = user_id
        
        event.new_chat_member = MagicMock()
        event.new_chat_member.status = new_status
        event.new_chat_member.user = MagicMock()
        event.new_chat_member.user.id = user_id
        
        return event
    return _make


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for all tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
