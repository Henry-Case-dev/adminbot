"""Tests for services/summary_throttling.py (T-185, R10; Epic 31: T-237/R31-3)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message, User

from services.summary_throttling import (
    _THROTTLE_PHRASES,
    _pluralize,
    ThrottlingMiddleware,
    format_remaining_seconds,
)


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
    message.reply = AsyncMock()
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
        event.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_spam_replies_with_pool_phrase(self, fake_time):
        """R31-3/D96-D98: внутри окна — reply фразой ИЗ пула с реальным временем."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        event = _make_message()
        await middleware(handler, event, {})
        fake_time["now"] += 30
        result = await middleware(handler, event, {})
        assert result is None
        handler.assert_awaited_once()  # только первый вызов
        event.reply.assert_awaited_once()
        text = event.reply.await_args.args[0]
        assert "{remaining}" not in text
        assert format_remaining_seconds(30.0) in text
        candidates = [
            phrase.format(remaining=format_remaining_seconds(30.0))
            for phrase in _THROTTLE_PHRASES
        ]
        assert text in candidates

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
    async def test_reply_failure_does_not_crash(self, fake_time, caplog):
        """D98: сбой event.reply → WARNING-лог, хендлер не вызван, исключение не всплывает."""
        import logging

        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        event = _make_message()
        await middleware(handler, event, {})
        fake_time["now"] += 30
        event.reply = AsyncMock(side_effect=Exception("сеть упала"))
        with caplog.at_level(logging.WARNING):
            result = await middleware(handler, event, {})
        assert result is None
        handler.assert_awaited_once()
        assert any("throttled reply failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_throttled_without_bot_in_data_replies_anyway(self, fake_time):
        """D98: bot в data не обязателен — reply шлётся через event, юнит-вызов не падает."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        event = _make_message()
        await middleware(handler, event, {})
        fake_time["now"] += 30
        result = await middleware(handler, event, {})
        assert result is None
        event.reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_default_constructor_uses_settings(self):
        from config.settings import settings

        middleware = ThrottlingMiddleware()
        assert middleware._throttle_seconds == settings.SUMMARY_THROTTLE_SECONDS


class TestFormatRemainingSeconds:
    """Epic 31 (D97): ceil + русская плюрализация краёв."""

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "1 секунда"),       # guard max(1, ceil)
            (0.4, "1 секунда"),     # ceil вверх
            (1, "1 секунда"),
            (2, "2 секунды"),
            (5, "5 секунд"),
            (11, "11 секунд"),
            (21, "21 секунда"),
            (22, "22 секунды"),
            (25, "25 секунд"),
            (59, "59 секунд"),
            (59.2, "1 минута"),     # ceil → 60
            (60, "1 минута"),
            (61, "2 минуты"),
            (90, "2 минуты"),       # ceil минут
            (120, "2 минуты"),
            (300, "5 минут"),
        ],
    )
    def test_format_remaining_seconds(self, seconds, expected):
        assert format_remaining_seconds(seconds) == expected


class TestPluralize:
    """Epic 31 (D97): краевые 11/12/21/22/25 и 101/111."""

    FORMS = ("секунда", "секунды", "секунд")

    @pytest.mark.parametrize(
        "n,expected",
        [
            (1, "секунда"),
            (2, "секунды"),
            (5, "секунд"),
            (11, "секунд"),
            (12, "секунд"),
            (14, "секунд"),
            (21, "секунда"),
            (22, "секунды"),
            (25, "секунд"),
            (101, "секунда"),
            (111, "секунд"),
        ],
    )
    def test_pluralize(self, n, expected):
        assert _pluralize(n, self.FORMS) == expected


class TestThrottlePhrasesPool:
    """Epic 31 (D96): пул из 7 фраз, каноны байт-в-байт, стиль-гард."""

    def test_pool_size_is_7(self):
        assert len(_THROTTLE_PHRASES) == 7

    def test_first_two_are_canons_verbatim(self):
        assert _THROTTLE_PHRASES[0] == "хули ты дрочишь, подожди {remaining}"
        assert _THROTTLE_PHRASES[1] == "угомонись нахуй, не можешь {remaining} подождать?"

    def test_style_guard(self):
        for phrase in _THROTTLE_PHRASES:
            assert "{remaining}" in phrase
            assert phrase == phrase.lower()
            assert not any(0x1F000 <= ord(ch) <= 0x1FAFF for ch in phrase)


def _fake_bot(username="v1vv2as_bot"):
    """Fake aiogram Bot с me() → username (для валидации mention, B3)."""
    bot = MagicMock()
    me = MagicMock()
    me.username = username
    bot.me = AsyncMock(return_value=me)
    return bot


class TestMentionValidation:
    """Epic 25 (B3): симметрия троттлинга с Command-фильтром."""

    @pytest.mark.asyncio
    async def test_foreign_mention_does_not_consume_slot(self, fake_time):
        """Регресс первопричины: /summary@RofloslavBot не жжёт слот троттлинга."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        data = {"bot": _fake_bot("v1vv2as_bot")}
        await middleware(handler, _make_message(text="/summary@RofloslavBot"), data)
        fake_time["now"] += 12
        await middleware(handler, _make_message(text="/summary"), data)
        assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_foreign_mention_passes_event_through(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock(return_value="handled")
        data = {"bot": _fake_bot("v1vv2as_bot")}
        result = await middleware(handler, _make_message(text="/summary@RofloslavBot"), data)
        assert result == "handled"
        assert middleware._last == {}

    @pytest.mark.asyncio
    async def test_own_mention_still_throttled(self, fake_time):
        """Low-3 жив: /summary@НашБот троттлится как /summary."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        data = {"bot": _fake_bot("v1vv2as_bot")}
        await middleware(handler, _make_message(text="/summary@v1vv2as_bot"), data)
        fake_time["now"] += 10
        result = await middleware(handler, _make_message(text="/summary@v1vv2as_bot"), data)
        assert result is None
        assert handler.await_count == 1

    @pytest.mark.asyncio
    async def test_own_mention_case_insensitive(self, fake_time):
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        data = {"bot": _fake_bot("v1vv2as_bot")}
        await middleware(handler, _make_message(text="/summary@V1VV2AS_BOT"), data)
        fake_time["now"] += 10
        result = await middleware(handler, _make_message(text="/summary"), data)
        assert result is None
        assert handler.await_count == 1

    @pytest.mark.asyncio
    async def test_summaryfoo_not_matched(self, fake_time):
        """B3: точное сравнение — /summaryfoo не матчится и не жжёт слот."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        await middleware(handler, _make_message(text="/summaryfoo"), {})
        await middleware(handler, _make_message(text="/summary"), {})
        assert handler.await_count == 2

    @pytest.mark.asyncio
    async def test_blank_text_passes_through(self, fake_time):
        """Guard: пробельный текст не роняет middleware (замечание PM)."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock(return_value="ok")
        result = await middleware(handler, _make_message(text="   "), {})
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_mention_without_bot_in_data_treated_as_own(self, fake_time):
        """Нет bot в data (юнит-вызов) → mention не валидируется, троттлится как своя."""
        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        await middleware(handler, _make_message(text="/summary@AnyBot"), {})
        fake_time["now"] += 10
        result = await middleware(handler, _make_message(text="/summary"), {})
        assert result is None
        assert handler.await_count == 1

    @pytest.mark.asyncio
    async def test_throttled_log_contains_remaining(self, fake_time, caplog):
        import logging

        middleware = ThrottlingMiddleware(throttle_seconds=60.0)
        handler = AsyncMock()
        await middleware(handler, _make_message(text="/summary"), {})
        fake_time["now"] += 30
        with caplog.at_level(logging.INFO):
            await middleware(handler, _make_message(text="/summary"), {})
        assert any("throttled" in r.message and "remaining=" in r.message
                   for r in caplog.records)
