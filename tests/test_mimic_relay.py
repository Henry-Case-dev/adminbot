"""Tests for MimicRelay — cooldown and dispatch service."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.mimic_relay import MimicRelay
from services.mimic_transform import mimic_transform


# ═══════════════════════════════════════════════════════════════════
# A. should_trigger — word count
# ═══════════════════════════════════════════════════════════════════

class TestShouldTriggerWordCount:
    """should_trigger returns False when word count ≤ min_words."""

    @pytest.fixture
    def relay(self):
        return MimicRelay(min_words=5, cooldown_seconds=60.0)

    def test_too_few_words(self, relay):
        assert relay.should_trigger(1, 100, "короткое сообщение") is False

    def test_exactly_min_words(self, relay):
        """Exact N words → count_words=N, which is NOT > N → False."""
        assert relay.should_trigger(1, 100, "одно два три четыре пять") is False

    def test_more_than_min_words(self, relay):
        assert relay.should_trigger(1, 100, "одно два три четыре пять шесть") is True

    def test_empty_text(self, relay):
        assert relay.should_trigger(1, 100, "") is False


# ═══════════════════════════════════════════════════════════════════
# B. should_trigger — cooldown
# ═══════════════════════════════════════════════════════════════════

class TestShouldTriggerCooldown:
    """should_trigger respects cooldown."""

    def test_first_call_no_cooldown(self):
        relay = MimicRelay(min_words=3, cooldown_seconds=60.0)
        assert relay.should_trigger(1, 100, "раз два три четыре") is True

    def test_cooldown_active_blocks(self):
        relay = MimicRelay(min_words=3, cooldown_seconds=60.0)
        relay._last_sent[(1, 100)] = time.monotonic()
        assert relay.should_trigger(1, 100, "раз два три четыре") is False

    def test_cooldown_expired_allows(self):
        relay = MimicRelay(min_words=3, cooldown_seconds=0.1)
        relay._last_sent[(1, 100)] = time.monotonic() - 1.0  # 1 sec ago
        assert relay.should_trigger(1, 100, "раз два три четыре") is True

    def test_cooldown_zero_always_allows(self):
        relay = MimicRelay(min_words=3, cooldown_seconds=0)
        relay._last_sent[(1, 100)] = time.monotonic()
        assert relay.should_trigger(1, 100, "раз два три четыре") is True

    def test_different_chat_independent(self):
        relay = MimicRelay(min_words=3, cooldown_seconds=60.0)
        relay._last_sent[(1, 100)] = time.monotonic()
        # Same user, different chat → not blocked
        assert relay.should_trigger(2, 100, "раз два три четыре") is True

    def test_different_user_independent(self):
        relay = MimicRelay(min_words=3, cooldown_seconds=60.0)
        relay._last_sent[(1, 100)] = time.monotonic()
        # Same chat, different user → not blocked
        assert relay.should_trigger(1, 200, "раз два три четыре") is True

    def test_min_words_zero(self):
        """min_words=0 → count_words(text) > 0 → True for non-empty."""
        relay = MimicRelay(min_words=0, cooldown_seconds=60.0)
        assert relay.should_trigger(1, 100, "одно") is True
        assert relay.should_trigger(1, 100, "") is False


# ═══════════════════════════════════════════════════════════════════
# C. mark_sent
# ═══════════════════════════════════════════════════════════════════

class TestMarkSent:
    """mark_sent updates the cooldown timestamp."""

    def test_updates_timestamp(self):
        relay = MimicRelay(min_words=3, cooldown_seconds=60.0)
        before = time.monotonic()
        relay.mark_sent(1, 100)
        assert (1, 100) in relay._last_sent
        assert relay._last_sent[(1, 100)] >= before

    def test_blocks_after_mark(self):
        relay = MimicRelay(min_words=3, cooldown_seconds=60.0)
        relay.mark_sent(1, 100)
        assert relay.should_trigger(1, 100, "раз два три четыре") is False


# ═══════════════════════════════════════════════════════════════════
# D. send_mimic
# ═══════════════════════════════════════════════════════════════════

class TestSendMimic:
    """send_mimic calls bot.send_message with transformed text."""

    @pytest.mark.asyncio
    async def test_calls_bot_send_message(self):
        bot = AsyncMock()
        relay = MimicRelay(min_words=3, cooldown_seconds=60.0)
        await relay.send_mimic(bot, chat_id=42, message_id=99, text="мама мыла раму")
        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 42
        assert call_kwargs["reply_to_message_id"] == 99
        assert call_kwargs["text"] == mimic_transform("мама мыла раму")

    @pytest.mark.asyncio
    async def test_send_mimic_uses_transform(self):
        bot = AsyncMock()
        relay = MimicRelay(min_words=3, cooldown_seconds=60.0)
        await relay.send_mimic(bot, chat_id=1, message_id=1, text="черный жук")
        sent_text = bot.send_message.call_args.kwargs["text"]
        assert sent_text == "цейний зюк"
