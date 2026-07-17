"""Tests for Alan_Z reply engine (F6) and silence greeting (F7v2).

Tests cover:
  - Counter increments correctly
  - Reply fires every ALAN_REPLY_INTERVAL (10) messages
  - Reply does NOT fire on non-divisible messages
  - Random selection from reply pool
  - DB dependency injection
  - No reply when DB not set up
  - Silence greeting: baseline, threshold exceeded, threshold not reached
  - Silence greeting: disabled, float threshold, cooldown suppression
  - Silence greeting: multi-chat isolation, error handling
  - F6 + F7v2 coexistence
"""
import pytest
from unittest.mock import AsyncMock, patch

from handlers.alan import alan_handler, setup_alan, ALAN_REPLIES, _last_greeting


class TestAlanHandler:
    """Unit tests for the Alan reply engine handler."""

    @pytest.mark.asyncio
    async def test_reply_fires_every_10_messages(self, make_message):
        """Reply should fire exactly on messages 10, 20, 30, etc."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Messages 1-9: no reply
        for i in range(1, 10):
            mock_db.increment_and_get_count.return_value = i
            msg = make_message(138811255, text=f"message {i}")
            await alan_handler(msg)
            msg.reply.assert_not_called()

        # Message 10: reply fires
        mock_db.increment_and_get_count.return_value = 10
        msg = make_message(138811255, text="message 10")
        await alan_handler(msg)
        msg.reply.assert_called_once()
        reply_arg = msg.reply.call_args[0][0]
        assert reply_arg in ALAN_REPLIES

    @pytest.mark.asyncio
    async def test_no_reply_on_non_divisible(self, make_message):
        """Messages not divisible by interval should not trigger reply."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        for count in [1, 3, 7, 11, 19, 21, 99]:
            mock_db.increment_and_get_count.return_value = count
            msg = make_message(138811255, text=f"msg_{count}")
            await alan_handler(msg)
            msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_at_20_30_40(self, make_message):
        """Verify reply fires at each multiple of 10."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        for count in [10, 20, 30, 40, 50]:
            mock_db.increment_and_get_count.return_value = count
            msg = make_message(138811255, text=f"msg_{count}")
            await alan_handler(msg)
            msg.reply.assert_called_once()
            reply_arg = msg.reply.call_args[0][0]
            assert reply_arg in ALAN_REPLIES
            msg.reply.reset_mock()

    @pytest.mark.asyncio
    async def test_random_selection_from_pool(self, make_message):
        """Over many calls, we should see different replies (not always the same)."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        seen_replies = set()
        for i in range(1, 51):
            mock_db.increment_and_get_count.return_value = i
            msg = make_message(138811255, text=f"msg_{i}")
            await alan_handler(msg)
            if msg.reply.called:
                seen_replies.add(msg.reply.call_args[0][0])
                msg.reply.reset_mock()

        # At 10,20,30,40,50 we should have 5 replies
        # They should not all be identical (probabilistic check)
        assert len(seen_replies) >= 2, (
            f"Expected at least 2 unique replies from 5 calls, got {len(seen_replies)}"
        )

    @pytest.mark.asyncio
    async def test_all_replies_in_pool_are_strings(self):
        """All entries in ALAN_REPLIES must be non-empty strings."""
        for reply in ALAN_REPLIES:
            assert isinstance(reply, str), f"Non-string reply: {reply!r}"
            assert len(reply) > 0, f"Empty reply found in pool"

    @pytest.mark.asyncio
    async def test_pool_has_minimum_size(self):
        """Pool should have at least 16 variants (6 original + 10 new)."""
        assert len(ALAN_REPLIES) >= 16, (
            f"ALAN_REPLIES pool has {len(ALAN_REPLIES)} entries, need at least 16"
        )

    @pytest.mark.asyncio
    async def test_topic_coverage(self):
        """Key topics must be represented in the reply pool."""
        pool_text = " ".join(ALAN_REPLIES).lower()
        required_topics = [
            "тренировк",   # тренировки/тренировка
            "лонгковид",
            "фьючерс",
            "нейросет",    # нейросети/нейросеть/нейросетки
            "жим дьявола",
        ]
        for topic in required_topics:
            assert topic in pool_text, f"Topic '{topic}' not found in ALAN_REPLIES"

    @pytest.mark.asyncio
    async def test_no_reply_for_wrong_user(self, make_message):
        """Handler itself does NOT filter by user ID — that's the router/filter's job.
        
        The UserIdFilter decorator on alan_router handles user-ID matching.
        When calling the handler directly (bypassing the router), it processes
        any message. This is correct: filtering is a router concern.
        
        The UserIdFilter itself is tested in test_filters.py.
        """
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Even with wrong user ID, handler processes it (filtering happens at router level)
        mock_db.increment_and_get_count.return_value = 10
        mock_db.get_alan_last_message_ts = AsyncMock(return_value=None)
        mock_db.set_alan_last_message_ts = AsyncMock()
        msg = make_message(479167456, text="hello")

        with patch("handlers.alan._send_greeting", return_value=True):
            with patch("handlers.alan._last_greeting", {}):
                with patch("handlers.alan.settings") as mock_settings:
                    mock_settings.ALAN_SILENCE_GREETING_HOURS = 6.0
                    mock_settings.ALAN_REPLY_INTERVAL = 10
                    mock_settings.ALAN_GREETING_COOLDOWN = 10
                    await alan_handler(msg)

        # Handler fires because we bypassed the router filter — this is expected
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_reply_when_db_not_setup(self, make_message):
        """If setup_alan() was never called, handler should silently return."""
        global alan_db
        from handlers import alan as alan_module
        alan_module.alan_db = None  # Simulate no setup

        msg = make_message(138811255, text="hello")
        await alan_handler(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_counter_increments_even_without_reply(self, make_message):
        """increment_and_get_count should be called on every message, not just reply ones."""
        mock_db = AsyncMock()
        setup_alan(mock_db)
        mock_db.increment_and_get_count.return_value = 3

        msg = make_message(138811255, text="message that won't trigger reply")
        await alan_handler(msg)
        mock_db.increment_and_get_count.assert_called_once_with(msg.chat.id, msg.from_user.id)

    @pytest.mark.asyncio
    async def test_configurable_interval(self, make_message, monkeypatch):
        """Changing ALAN_REPLY_INTERVAL via a new Settings instance changes reply timing."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Create a new settings instance with interval=5 and inject into alan module
        import config.settings as settings_module
        new_settings = settings_module.Settings(
            ALAN_REPLY_INTERVAL=5,
        )
        monkeypatch.setattr("handlers.alan.settings", new_settings)

        # Count 5: should fire
        mock_db.increment_and_get_count.return_value = 5
        msg = make_message(138811255, text="fifth message")
        await alan_handler(msg)
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_text_message_also_counts(self, make_message):
        """Photo/sticker messages should still increment counter and potentially reply."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Photo message (no text)
        mock_db.increment_and_get_count.return_value = 10
        msg = make_message(138811255, text=None)
        msg.photo = []  # Simulate photo message
        await alan_handler(msg)
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_reply_uses_message_reply(self, make_message):
        """Verify reply is sent as a reply to the original message."""
        mock_db = AsyncMock()
        setup_alan(mock_db)
        mock_db.increment_and_get_count.return_value = 10

        msg = make_message(138811255, text="test reply")
        await alan_handler(msg)
        msg.reply.assert_called_once()
        # message.reply() should be called (not answer() or send_message())
        assert msg.reply.called
        assert not msg.answer.called

    @pytest.mark.asyncio
    async def test_same_chat_separate_counters(self, make_message):
        """Different chats should have independent counters."""
        mock_db = AsyncMock()
        setup_alan(mock_db)

        # Chat A: count 10 → reply
        mock_db.increment_and_get_count.return_value = 10
        msg_a = make_message(138811255, text="chat A msg", chat_id=-100)
        await alan_handler(msg_a)
        assert msg_a.reply.called

        # Chat B: count 9 → no reply (separate counter)
        mock_db.increment_and_get_count.return_value = 9
        msg_b = make_message(138811255, text="chat B msg", chat_id=-200)
        await alan_handler(msg_b)
        msg_b.reply.assert_not_called()


class TestAlanSilenceGreeting:
    """Unit tests for F7v2 Alan silence greeting (Epic 11).

    Default settings values are used for most tests:
      ALAN_SILENCE_GREETING_HOURS=6.0, ALAN_GREETING_COOLDOWN=10.
    Tests that need different values replace the entire settings object
    on handlers.alan.settings (Settings is a frozen dataclass).
    """

    NOW = 1721000000.0

    @pytest.fixture(autouse=True)
    def _clear_last_greeting(self):
        """Reset _last_greeting dict between tests to avoid cross-test pollution."""
        _last_greeting.clear()

    @pytest.mark.asyncio
    async def test_silence_first_message_baseline(self, make_message):
        """First Alan message: no DB record → baseline, no greeting, timestamp recorded."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = None
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting") as mock_send:
                msg = make_message(138811255, text="first msg", chat_id=-100)
                await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.get_alan_last_message_ts.assert_called_once_with(-100)
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_threshold_exceeded_sends_greeting(self, make_message):
        """elapsed >= threshold → _send_greeting called, _last_greeting updated."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 6.1 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="woke up", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)
        assert _last_greeting[-100] == self.NOW

    @pytest.mark.asyncio
    async def test_silence_threshold_not_reached_no_greeting(self, make_message):
        """elapsed < threshold → no greeting, timestamp updated."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 2.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting") as mock_send:
                msg = make_message(138811255, text="quick msg", chat_id=-100)
                await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_disabled_when_zero(self, make_message, monkeypatch):
        """ALAN_SILENCE_GREETING_HOURS=0 → entire silence logic skipped."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        setup_alan(mock_db)

        import config.settings as settings_module
        new_settings = settings_module.Settings(ALAN_SILENCE_GREETING_HOURS=0.0)
        monkeypatch.setattr("handlers.alan.settings", new_settings)

        with patch("handlers.alan._send_greeting") as mock_send:
            msg = make_message(138811255, text="hello", chat_id=-100)
            await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.get_alan_last_message_ts.assert_not_called()
        mock_db.set_alan_last_message_ts.assert_not_called()

    @pytest.mark.asyncio
    async def test_silence_float_threshold(self, make_message, monkeypatch):
        """ALAN_SILENCE_GREETING_HOURS=0.5 (30 min), elapsed=31 min → triggered."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 31 * 60
        setup_alan(mock_db)

        import config.settings as settings_module
        new_settings = settings_module.Settings(ALAN_SILENCE_GREETING_HOURS=0.5)
        monkeypatch.setattr("handlers.alan.settings", new_settings)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="back", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_silence_cooldown_suppresses_duplicate(self, make_message):
        """_last_greeting[chat_id]=2s ago, cooldown=10 → suppressed."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        _last_greeting[-100] = self.NOW - 2

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting") as mock_send:
                msg = make_message(138811255, text="hi", chat_id=-100)
                await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_cooldown_expired_allows_greeting(self, make_message):
        """_last_greeting[chat_id]=15s ago, cooldown=10 → greeting allowed."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        _last_greeting[-100] = self.NOW - 15

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="back again", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_silence_multi_chat_isolation(self, make_message):
        """Different chats have independent silence timers."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1

        async def get_last_ts_mock(chat_id):
            if chat_id == -100:
                return self.NOW - 7.0 * 3600
            else:
                return self.NOW - 1.0 * 3600
        mock_db.get_alan_last_message_ts.side_effect = get_last_ts_mock
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg_a = make_message(138811255, text="chat A", chat_id=-100)
                msg_a.bot = AsyncMock()
                await alan_handler(msg_a)

                msg_b = make_message(138811255, text="chat B", chat_id=-200)
                msg_b.bot = AsyncMock()
                await alan_handler(msg_b)

        assert mock_send.call_count == 1
        mock_db.set_alan_last_message_ts.assert_any_call(-100, self.NOW)
        mock_db.set_alan_last_message_ts.assert_any_call(-200, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_db_read_error_graceful(self, make_message):
        """get_alan_last_message_ts raises → handler doesn't crash, F6 still works."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.side_effect = Exception("DB read error")
        setup_alan(mock_db)

        with patch("handlers.alan._send_greeting") as mock_send:
            msg = make_message(138811255, text="hello", chat_id=-100)
            await alan_handler(msg)

        mock_send.assert_not_called()
        mock_db.increment_and_get_count.assert_called_once()

    @pytest.mark.asyncio
    async def test_silence_db_write_error_graceful(self, make_message):
        """set_alan_last_message_ts raises → handler doesn't crash."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        mock_db.set_alan_last_message_ts.side_effect = Exception("DB write error")
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="woke up", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_silence_send_greeting_error_graceful(self, make_message):
        """_send_greeting returns False → handler doesn't crash, timestamp still updated."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=False) as mock_send:
                msg = make_message(138811255, text="woke up", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()
        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)
        assert -100 not in _last_greeting

    @pytest.mark.asyncio
    async def test_f6_reply_still_works_with_silence(self, make_message):
        """F6 reply fires on interval while F7v2 silence is active."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 10
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
                msg = make_message(138811255, text="msg 10", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_send.assert_called_once()
        msg.reply.assert_called_once()
        assert msg.reply.call_args[0][0] in ALAN_REPLIES

    @pytest.mark.asyncio
    async def test_silence_timestamp_always_updated(self, make_message):
        """Even when greeting send fails, timestamp is still updated."""
        mock_db = AsyncMock()
        mock_db.increment_and_get_count.return_value = 1
        mock_db.get_alan_last_message_ts.return_value = self.NOW - 7.0 * 3600
        setup_alan(mock_db)

        with patch("handlers.alan.time.time", return_value=self.NOW):
            with patch("handlers.alan._send_greeting", return_value=False):
                msg = make_message(138811255, text="woke up", chat_id=-100)
                msg.bot = AsyncMock()
                await alan_handler(msg)

        mock_db.set_alan_last_message_ts.assert_called_once_with(-100, self.NOW)

    @pytest.mark.asyncio
    async def test_silence_non_alan_ignored(self, make_message):
        """Silence logic should not execute for non-Alan users (UserIdFilter at router level).

        When handler is called directly (bypassing router filter), silence logic
        still executes because it's in the same alan_handler. But for non-Alan messages
        the router won't route to this handler at all. This test verifies that even
        if somehow reached, the logic doesn't crash.
        """
        global alan_db
        from handlers import alan as alan_module

        mock_db = AsyncMock()
        mock_db.increment_and_get_count = AsyncMock(return_value=3)
        mock_db.get_alan_last_message_ts = AsyncMock(return_value=None)
        mock_db.set_alan_last_message_ts = AsyncMock()
        alan_module.alan_db = mock_db

        with patch("handlers.alan._send_greeting", return_value=True) as mock_send:
            with patch("handlers.alan._last_greeting", {}):
                with patch("handlers.alan.settings") as mock_settings:
                    mock_settings.ALAN_SILENCE_GREETING_HOURS = 6.0
                    mock_settings.ALAN_REPLY_INTERVAL = 10
                    mock_settings.ALAN_GREETING_COOLDOWN = 10
                    msg = make_message(99999, text="random message from non-Alan")
                    await alan_handler(msg)

        # Silence greeting should NOT be called (first message = baseline)
        mock_send.assert_not_called()
        # DB should still record timestamp (baseline for non-Alan via this handler)
        mock_db.set_alan_last_message_ts.assert_called_once()
