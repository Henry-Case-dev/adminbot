"""Tests for services/summary_throttling.py (T-185, R10)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, User

from services.summary_throttling import ThrottlingMiddleware


@pytest.fixture
def fake_time(monkeypatch):
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr("services.summary_throttling.time", FakeTime)
    return state


def _make_message(text="/summary", user_id=5, chat_id=-100):
    message = MagicMock(spec=Message)
    message.text = text
    message.chat = MagicMock()
    message.chat.id = chat_id
    message.from_user = MagicMock()
    message.from_user.id = user_id
    return message


class TestThrottlingMiddleware:
    @pytest.mark.asyncio
    async def test_first_call_passes(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock(return_value="handled")
        event = _make_message()
        result = await middleware(handler, event, {})
        assert result == "handled"
        handler.assert_awaited_once_with(event, {})

    @pytest.mark.asyncio
    async def test_spam_silently_dropped(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        event = _make_message()
        await middleware(handler, event, {})
        fake_time["now"] += 30
        result = await middleware(handler, event, {})
        assert result is None
        handler.assert_awaited_once()  # только первый вызов

    @pytest.mark.asyncio
    async def test_after_ttl_passes_again(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        event = _make_message()
        await middleware(handler, event, {})
        fake_time["now"] += 61
        await middleware(handler, event, {})
        assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_key_is_chat_and_user(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        await middleware(handler, _make_message(user_id=1, chat_id=-100), {})
        await middleware(handler, _make_message(user_id=2, chat_id=-100), {})
        await middleware(handler, _make_message(user_id=1, chat_id=-200), {})
        assert handler.await_count == 3

    @pytest.mark.asyncio
    async def test_non_summary_not_throttled(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        event = _make_message(text="/other")
        await middleware(handler, event, {})
        await middleware(handler, event, {})
        assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_summary_with_botname_suffix_throttled(self, fake_time):
        """Review Low-3: /summary@MyBot трактуется как /summary."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        first = _make_message(text="/summary@MyBot")
        await middleware(handler, first, {})
        fake_time["now"] += 10
        result = await middleware(handler, _make_message(text="/summary@MyBot"), {})
        assert result is None
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summary_botname_and_plain_share_throttle_key(self, fake_time):
        """Review Low-3: /summary и /summary@BotName — один ключ троттлинга."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        await middleware(handler, _make_message(text="/summary@MyBot"), {})
        fake_time["now"] += 10
        result = await middleware(handler, _make_message(text="/summary"), {})
        assert result is None
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summary_botname_after_ttl_passes(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        await middleware(handler, _make_message(text="/summary@MyBot"), {})
        fake_time["now"] += 61
        await middleware(handler, _make_message(text="/summary@MyBot"), {})
        assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_no_from_user_key_zero(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        event = _make_message()
        event.from_user = None
        await middleware(handler, event, {})
        await middleware(handler, event, {})
        assert handler.await_count == 1

    @pytest.mark.asyncio
    async def test_non_message_event_passes(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock(return_value="ok")
        event = MagicMock()
        result = await middleware(handler, event, {})
        assert result == "ok"
        handler.assert_awaited_once_with(event, {})

    @pytest.mark.asyncio
    async def test_default_constructor_uses_settings(self):
        from config.settings import settings

        middleware = ThrottlingMiddleware()
        assert middleware._throttle_seconds == settings.SUMMARY_THROTTLE_SECONDS
