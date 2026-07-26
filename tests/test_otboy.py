"""
Tests for F9 — Otboy Service (Epic 13).

Covers:
  - OtboyWordFilter: matching, word boundaries, case-insensitivity
  - otboy_handler: relay None guard, correct delegation
  - OtboyRelay: cooldown logic, photo sending
  - Integration: propagation (does not block other handlers)
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from filters.otboy_word import OtboyWordFilter
from handlers.otboy import otboy_handler, setup_otboy, _relay as _otboy_relay_module
from services.otboy_relay import OtboyRelay


# ── Helpers ──

def make_otboy_message(text=None, caption=None, chat_id=-100123, message_id=1,
                       from_id=111, from_username="testuser"):
    """Create a mock Message for otboy tests."""
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = from_id
    msg.from_user.username = from_username
    return msg


# ── Filter Tests ──

class TestOtboyWordFilter:
    """Unit tests for OtboyWordFilter (filters/otboy_word.py)."""

    @pytest.mark.asyncio
    async def test_text_with_otboy_matches_and_returns_dict(self):
        """Text containing 'отбой' should return dict with matched_word."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text="отбой тревоги")
        result = await f(msg)
        assert result == {"matched_word": "отбой"}

    @pytest.mark.asyncio
    async def test_caption_with_otboy_matches(self):
        """Caption containing 'отбой' should match (forwarded media)."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text=None, caption="объявлен отбой")
        result = await f(msg)
        assert result == {"matched_word": "отбой"}

    @pytest.mark.asyncio
    async def test_text_without_otboy_returns_false(self):
        """Text without 'отбой' should return False."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text="привет как дела")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_uppercase_otboy_matches(self):
        """'ОТБОЙ' (uppercase) should match (case-insensitive)."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text="ОТБОЙ")
        result = await f(msg)
        assert result == {"matched_word": "ОТБОЙ"}

    @pytest.mark.asyncio
    async def test_titlecase_otboy_matches(self):
        """'Отбой' (title case) should match."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text="Отбой")
        result = await f(msg)
        assert result == {"matched_word": "Отбой"}

    @pytest.mark.asyncio
    async def test_mixedcase_otboy_matches(self):
        """'ОтБой' (mixed case) should match."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text="ОтБой")
        result = await f(msg)
        assert result == {"matched_word": "ОтБой"}

    @pytest.mark.asyncio
    async def test_otboyny_not_matched(self):
        """'отбойный' should NOT match — word boundary excludes suffix."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text="отбойный молоток")
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_otboy_in_middle_of_sentence(self):
        """'отбой' in the middle of a sentence should match."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text="объявили отбой воздушной тревоги")
        result = await f(msg)
        assert result == {"matched_word": "отбой"}

    @pytest.mark.asyncio
    async def test_non_string_content_does_not_crash(self):
        """isinstance guard: non-string text/caption should return False, not crash."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text=None, caption=None)
        msg.text = 12345
        msg.caption = None
        result = await f(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_both_text_and_caption_none_returns_false(self):
        """Both text and caption None → returns False."""
        f = OtboyWordFilter()
        msg = make_otboy_message(text=None, caption=None)
        result = await f(msg)
        assert result is False


# ── Handler Tests ──

class TestOtboyHandler:
    """Tests for otboy_handler (handlers/otboy.py)."""

    @pytest.fixture(autouse=True)
    def reset_relay(self):
        """Reset module-level _relay before each test."""
        setup_otboy(None)
        yield
        setup_otboy(None)

    @pytest.mark.asyncio
    async def test_relay_none_returns_none_without_error(self):
        """When _relay is None, handler should log error and return None."""
        setup_otboy(None)
        msg = make_otboy_message(text="отбой")
        result = await otboy_handler(msg, matched_word="отбой")
        assert result is None

    @pytest.mark.asyncio
    async def test_relay_none_does_not_call_send_otboy(self):
        """When _relay is None, send_otboy must not be called."""
        setup_otboy(None)
        mock_relay = MagicMock()
        mock_relay.send_otboy = AsyncMock()
        msg = make_otboy_message(text="отбой")
        await otboy_handler(msg, matched_word="отбой")
        mock_relay.send_otboy.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_relay_send_otboy_with_correct_params(self):
        """Handler should call _relay.send_otboy with correct chat_id, message_id, matched_word."""
        mock_relay = MagicMock()
        mock_relay.send_otboy = AsyncMock()
        setup_otboy(mock_relay)

        msg = make_otboy_message(text="отбой", chat_id=-100456, message_id=789)
        await otboy_handler(msg, matched_word="отбой")

        mock_relay.send_otboy.assert_called_once_with(
            chat_id=-100456,
            message_id=789,
            matched_word="отбой",
        )

    @pytest.mark.asyncio
    async def test_handler_sends_matched_word_from_filter(self):
        """Handler should pass the exact matched_word from the filter."""
        mock_relay = MagicMock()
        mock_relay.send_otboy = AsyncMock()
        setup_otboy(mock_relay)

        msg = make_otboy_message(text="сказали Отбой")
        await otboy_handler(msg, matched_word="Отбой")

        mock_relay.send_otboy.assert_called_once_with(
            chat_id=-100123,
            message_id=1,
            matched_word="Отбой",
        )

    @pytest.mark.asyncio
    async def test_handler_catches_send_otboy_exception(self):
        """Handler should not propagate exceptions from send_otboy."""
        mock_relay = MagicMock()
        mock_relay.send_otboy = AsyncMock(side_effect=RuntimeError("Telegram API error"))
        setup_otboy(mock_relay)

        msg = make_otboy_message(text="отбой")
        # Should not raise
        await otboy_handler(msg, matched_word="отбой")


# ── Relay Tests ──

class TestOtboyRelay:
    """Tests for OtboyRelay (services/otboy_relay.py)."""

    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock()
        return bot

    @pytest.mark.asyncio
    async def test_cooldown_active_skips_photo(self, mock_bot, monkeypatch):
        """When cooldown is active, photo should NOT be sent again."""
        relay = OtboyRelay(mock_bot, cooldown_seconds=60)
        fake_now = 1000.0

        # First call — should send
        with patch("services.otboy_relay.time.monotonic", return_value=fake_now):
            await relay.send_otboy(chat_id=1, message_id=10, matched_word="отбой")
        assert mock_bot.send_photo.call_count == 1

        # Second call at fake_now + 30 (within cooldown) — should skip
        with patch("services.otboy_relay.time.monotonic", return_value=fake_now + 30):
            await relay.send_otboy(chat_id=1, message_id=11, matched_word="отбой")
        assert mock_bot.send_photo.call_count == 1  # Still 1, cooldown blocked it

    @pytest.mark.asyncio
    async def test_cooldown_expired_sends_photo(self, mock_bot, monkeypatch):
        """When cooldown has expired, photo should be sent."""
        relay = OtboyRelay(mock_bot, cooldown_seconds=60)
        fake_now = 1000.0

        with patch("services.otboy_relay.time.monotonic", return_value=fake_now):
            await relay.send_otboy(chat_id=1, message_id=10, matched_word="отбой")
        assert mock_bot.send_photo.call_count == 1

        # After cooldown expires (61 seconds later)
        with patch("services.otboy_relay.time.monotonic", return_value=fake_now + 61):
            await relay.send_otboy(chat_id=1, message_id=11, matched_word="отбой")
        assert mock_bot.send_photo.call_count == 2

    @pytest.mark.asyncio
    async def test_cooldown_zero_always_sends(self, mock_bot, monkeypatch):
        """Cooldown of 0 should always send (disabled cooldown)."""
        relay = OtboyRelay(mock_bot, cooldown_seconds=0)
        fake_now = 1000.0

        with patch("services.otboy_relay.time.monotonic", return_value=fake_now):
            await relay.send_otboy(chat_id=1, message_id=10, matched_word="отбой")
        assert mock_bot.send_photo.call_count == 1

        # Immediate second call — should also send
        with patch("services.otboy_relay.time.monotonic", return_value=fake_now + 1):
            await relay.send_otboy(chat_id=1, message_id=11, matched_word="отбой")
        assert mock_bot.send_photo.call_count == 2

    @pytest.mark.asyncio
    async def test_different_chats_independent_cooldowns(self, mock_bot, monkeypatch):
        """Cooldown is per-chat; different chats don't block each other."""
        relay = OtboyRelay(mock_bot, cooldown_seconds=60)
        fake_now = 1000.0

        with patch("services.otboy_relay.time.monotonic", return_value=fake_now):
            await relay.send_otboy(chat_id=1, message_id=10, matched_word="отбой")
            await relay.send_otboy(chat_id=2, message_id=20, matched_word="отбой")
        # Both chats should have received the photo — independent cooldowns
        assert mock_bot.send_photo.call_count == 2

    @pytest.mark.asyncio
    async def test_first_call_no_cooldown_check(self, mock_bot, monkeypatch):
        """First call for a chat_id with no previous cooldown entry should always send."""
        relay = OtboyRelay(mock_bot, cooldown_seconds=60)
        fake_now = 1000.0

        with patch("services.otboy_relay.time.monotonic", return_value=fake_now):
            await relay.send_otboy(chat_id=1, message_id=10, matched_word="отбой")
        assert mock_bot.send_photo.call_count == 1

    @pytest.mark.asyncio
    async def test_send_photo_passes_correct_params(self, mock_bot, monkeypatch):
        """send_otboy should call bot.send_photo with FSInputFile and ReplyParameters."""
        relay = OtboyRelay(mock_bot, cooldown_seconds=0)
        fake_now = 1000.0

        with patch("services.otboy_relay.time.monotonic", return_value=fake_now):
            await relay.send_otboy(chat_id=42, message_id=99, matched_word="отбой")

        mock_bot.send_photo.assert_called_once()
        call_kwargs = mock_bot.send_photo.call_args.kwargs
        assert call_kwargs["chat_id"] == 42
        # reply_parameters should have message_id and quote
        from aiogram.types import FSInputFile, ReplyParameters
        assert isinstance(call_kwargs["photo"], FSInputFile)
        assert isinstance(call_kwargs["reply_parameters"], ReplyParameters)
        assert call_kwargs["reply_parameters"].message_id == 99
        assert call_kwargs["reply_parameters"].quote == "отбой"

    @pytest.mark.asyncio
    async def test_send_photo_error_is_caught(self, mock_bot, monkeypatch):
        """Exception from bot.send_photo should be caught, not propagated."""
        mock_bot.send_photo.side_effect = Exception("Telegram API error")
        relay = OtboyRelay(mock_bot, cooldown_seconds=0)
        fake_now = 1000.0

        with patch("services.otboy_relay.time.monotonic", return_value=fake_now):
            # Should not raise
            await relay.send_otboy(chat_id=1, message_id=10, matched_word="отбой")


# ── Integration Tests ──

class TestOtboyIntegration:
    """Integration tests: propagation, cross-component interactions."""

    @pytest.mark.asyncio
    async def test_handler_does_not_block_propagation(self):
        """Handler should return None (not UNHANDLED) so other routers continue."""
        mock_relay = MagicMock()
        mock_relay.send_otboy = AsyncMock()
        setup_otboy(mock_relay)

        msg = make_otboy_message(text="отбой")
        result = await otboy_handler(msg, matched_word="отбой")
        # Handler returns None → aiogram continues to next handlers
        assert result is None

    @pytest.mark.asyncio
    async def test_otboy_filter_independent_of_user_id(self):
        """OtboyWordFilter does NOT filter by user ID — works for anyone."""
        f = OtboyWordFilter()
        # Any user should match
        for uid in [111, 479167456, 350803143, 999999999]:
            msg = make_otboy_message(text="отбой", from_id=uid)
            result = await f(msg)
            assert result == {"matched_word": "отбой"}

    @pytest.mark.asyncio
    async def test_handler_does_not_affect_relay_state_for_other_tests(self):
        """Verify setup_otboy() properly isolates relay state."""
        relay1 = MagicMock()
        relay1.send_otboy = AsyncMock()
        setup_otboy(relay1)

        msg = make_otboy_message(text="отбой")
        await otboy_handler(msg, matched_word="отбой")
        assert relay1.send_otboy.call_count == 1

        # Reset for cleanliness
        setup_otboy(None)
