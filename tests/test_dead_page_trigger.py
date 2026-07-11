import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, Chat, User, MessageOriginChannel
from handlers.dead_page_trigger import on_forward, setup_dead_page
from config.settings import settings


class TestDeadPageTrigger:
    """Tests for dead_page_trigger handler."""

    def make_forward_message(self, username="d_pages", chat_id=-100123):
        """Create a Message with forward_origin from a channel."""
        user = User(id=111, is_bot=False, first_name="Test")
        chat_obj = Chat(id=chat_id, type="group")
        origin_chat = Chat(id=-100999, type="channel", username=username)
        origin = MessageOriginChannel(
            type="channel",
            date=1234567890,
            chat=origin_chat,
            message_id=42,
        )
        msg = Message(
            message_id=1,
            date=1234567890,
            chat=chat_obj,
            from_user=user,
            forward_origin=origin,
        )
        return msg

    @pytest.fixture
    def mock_relay(self):
        relay = MagicMock()
        relay.send_dead_page = AsyncMock()
        return relay

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.is_present = AsyncMock(return_value=True)
        return db

    @pytest.mark.asyncio
    async def test_triggers_on_d_pages_repost(self, mock_relay, mock_db):
        """Should detect repost from @d_pages and send dead page."""
        setup_dead_page(mock_relay, mock_db)
        msg = self.make_forward_message(username="d_pages")
        await on_forward(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")

    @pytest.mark.asyncio
    async def test_ignores_other_channels(self, mock_relay, mock_db):
        """Should not trigger for reposts from other channels."""
        setup_dead_page(mock_relay, mock_db)
        msg = self.make_forward_message(username="other_channel")
        await on_forward(msg)
        mock_relay.send_dead_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_slava_not_present(self, mock_relay, mock_db):
        """Should skip dead page if Slava is not in chat."""
        setup_dead_page(mock_relay, mock_db)
        mock_db.is_present.return_value = False
        msg = self.make_forward_message(username="d_pages")
        await on_forward(msg)
        mock_relay.send_dead_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_crash_when_relay_not_setup(self, mock_db):
        """Should not crash if relay is not initialized."""
        setup_dead_page(None, mock_db)
        msg = self.make_forward_message(username="d_pages")
        await on_forward(msg)
