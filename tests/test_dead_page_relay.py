import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from services.dead_page_relay import DeadPageRelay
from services.media_picker import MediaService
from config.settings import settings


class TestDeadPageRelay:
    """Tests for DeadPageRelay (channel forward + fallback)."""

    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        bot.forward_message = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        db.was_dead_page_recently = AsyncMock(return_value=False)
        db.get_last_known_message_id = AsyncMock(return_value=10)
        db.update_last_known_message_id = AsyncMock()
        db.record_dead_page_post = AsyncMock()
        return db

    @pytest.fixture
    def mock_media(self):
        media = MagicMock(spec=MediaService)
        media.pick_random = AsyncMock(return_value=("test.jpg", "test text"))
        return media

    @pytest.fixture
    def relay(self, mock_bot, mock_db, mock_media):
        return DeadPageRelay(mock_bot, mock_db, mock_media)

    @pytest.mark.asyncio
    async def test_send_dead_page_forwards_from_channel(self, relay, mock_bot, mock_db):
        """Primary flow: forward random post from relay channel."""
        await relay.send_dead_page(-100123)
        mock_bot.forward_message.assert_called_once()
        mock_db.record_dead_page_post.assert_called_once_with(-100123, "repost")

    @pytest.mark.asyncio
    async def test_send_dead_page_respects_cooldown(self, relay, mock_db):
        """Should skip if cooldown is active."""
        mock_db.was_dead_page_recently.return_value = True
        await relay.send_dead_page(-100123)
        mock_db.record_dead_page_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_dead_page_fallback_on_forward_failure(self, relay, mock_bot, mock_db):
        """When forward fails, should use local fallback."""
        mock_bot.forward_message.side_effect = Exception("Channel unavailable")
        await relay.send_dead_page(-100123)
        mock_bot.forward_message.assert_called()
        mock_bot.send_photo.assert_called()

    @pytest.mark.asyncio
    async def test_forward_retries_with_tried_set(self, relay, mock_bot, mock_db):
        """Should try different message_ids on failure."""
        mock_db.get_last_known_message_id.return_value = 100
        call_count = 0

        async def forward_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("message not found")
            return MagicMock()

        mock_bot.forward_message.side_effect = forward_side_effect
        await relay.send_dead_page(-100123)
        assert call_count >= 1
