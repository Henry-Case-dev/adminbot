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

    @pytest.mark.asyncio
    async def test_media_group_dedup_skips_duplicates(self, mock_relay, mock_db):
        """D48: Second msg with same media_group_id within 5s → skipped."""
        setup_dead_page(mock_relay, mock_db)

        msg1 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg1, "media_group_id", "mg_test_123")

        msg2 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg2, "media_group_id", "mg_test_123")

        await on_forward(msg1)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")

        mock_relay.send_dead_page.reset_mock()

        await on_forward(msg2)
        mock_relay.send_dead_page.assert_not_called()

    @pytest.mark.asyncio
    async def test_media_group_dedup_allows_first(self, mock_relay, mock_db):
        """D48: First msg with media_group_id is NOT skipped."""
        setup_dead_page(mock_relay, mock_db)

        msg = self.make_forward_message(username="d_pages")
        object.__setattr__(msg, "media_group_id", "mg_first_456")

        await on_forward(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")

    @pytest.mark.asyncio
    async def test_media_group_dedup_different_groups(self, mock_relay, mock_db):
        """D48: Different media_group_ids → both trigger."""
        setup_dead_page(mock_relay, mock_db)

        msg1 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg1, "media_group_id", "mg_aaa")

        msg2 = self.make_forward_message(username="d_pages")
        object.__setattr__(msg2, "media_group_id", "mg_bbb")

        await on_forward(msg1)
        assert mock_relay.send_dead_page.call_count == 1

        await on_forward(msg2)
        assert mock_relay.send_dead_page.call_count == 2

    @pytest.mark.asyncio
    async def test_no_media_group_id_still_triggers(self, mock_relay, mock_db):
        """Non-album forwards (no media_group_id) should still work normally."""
        setup_dead_page(mock_relay, mock_db)

        msg = self.make_forward_message(username="d_pages")
        object.__setattr__(msg, "media_group_id", None)

        await on_forward(msg)
        mock_relay.send_dead_page.assert_called_once_with(-100123, slot="repost")
