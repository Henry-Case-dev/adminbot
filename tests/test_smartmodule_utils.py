"""Tests for services/smartmodule_utils.py (T-257-D, R33-7, D110, Section 42.9).

send_chunked_reply: чанкинг >4096, reply_to_message_id ТОЛЬКО у первой части,
TelegramRetryAfter → sleep + один повтор, chunk_delay между частями.
_reply: best-effort. throttle_phrase: пул 5.1 + .replace-подстановка.
Epic 34 (D112/D114, Section 43.4): _send_once — fallback «gone»-400 → ровно
один повтор БЕЗ reply_to_message_id; прочие 400 — наверх.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from services import smartmodule_utils as utils_mod
from services.smartmodule_phrases import THROTTLE_PHRASES
from services.summary_generator import SummaryGenerator

CHAT_ID = -1001234567890


def _long_text(chunks: int = 2, word_len: int = 1000) -> str:
    words = []
    for i in range(chunks * 5):
        words.append(chr(ord("a") + i % 26) * word_len)
    return " ".join(words)


def _gone_400() -> TelegramBadRequest:
    """aiogram 3.29.1: TelegramAPIError.__init__(method, message) — .message
    содержит description (Section 43.4)."""
    return TelegramBadRequest(
        method=None, message="Bad Request: message to be replied not found"
    )


class TestSendChunkedReply:
    @pytest.mark.asyncio
    async def test_short_text_single_send_with_reply(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "короткий ответ", 42)
        assert bot.send_message.await_count == 1
        args, kwargs = bot.send_message.await_args.args, bot.send_message.await_args.kwargs
        assert args == (CHAT_ID, "короткий ответ")
        assert kwargs["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_long_text_chunked_reply_only_on_first(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        text = _long_text()
        assert len(text) > 4096
        await utils_mod.send_chunked_reply(bot, CHAT_ID, text, 42)
        calls = bot.send_message.await_args_list
        assert len(calls) > 1
        first_args, first_kwargs = calls[0].args, calls[0].kwargs
        assert first_kwargs["reply_to_message_id"] == 42
        for call in calls[1:]:
            assert "reply_to_message_id" not in call.kwargs

    @pytest.mark.asyncio
    async def test_chunks_do_not_break_words(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        text = _long_text()
        await utils_mod.send_chunked_reply(bot, CHAT_ID, text, 42)
        sent = [call.args[1] for call in bot.send_message.await_args_list]
        assert " ".join(sent) == text
        for chunk in sent:
            assert len(chunk) <= 4096

    @pytest.mark.asyncio
    async def test_retry_after_sleeps_and_retries_once(self, monkeypatch):
        sleep = AsyncMock()
        monkeypatch.setattr(utils_mod.asyncio, "sleep", sleep)
        bot = AsyncMock()
        retry_error = TelegramRetryAfter(method=None, message="retry", retry_after=3)
        bot.send_message = AsyncMock(side_effect=[retry_error, None])
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "текст", 42)
        assert bot.send_message.await_count == 2
        sleep.assert_awaited_once_with(3)

    @pytest.mark.asyncio
    async def test_chunk_delay_between_parts(self, monkeypatch):
        sleep = AsyncMock()
        monkeypatch.setattr(utils_mod.asyncio, "sleep", sleep)
        bot = AsyncMock()
        await utils_mod.send_chunked_reply(bot, CHAT_ID, _long_text(), 42)
        delays = [call.args[0] for call in sleep.await_args_list]
        assert delays and all(d == utils_mod.settings.SUMMARY_CHUNK_DELAY for d in delays)

    @pytest.mark.asyncio
    async def test_empty_text_no_sends(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "", 42)
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_default_chunk_delay_from_settings(self):
        assert utils_mod.send_chunked_reply.__defaults__[0] == utils_mod.settings.SUMMARY_CHUNK_DELAY


class TestSendChunkedReplyParseMode:
    """Epic 43 (52.2): опциональный kwarg parse_mode; обратная совместимость."""

    @pytest.mark.asyncio
    async def test_parse_mode_passed_to_send(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "текст", 42, parse_mode="HTML")
        kwargs = bot.send_message.await_args.kwargs
        assert kwargs["parse_mode"] == "HTML"
        assert kwargs["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_no_parse_mode_by_default_backward_compat(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "текст", 42)
        assert "parse_mode" not in bot.send_message.await_args.kwargs

    @pytest.mark.asyncio
    async def test_parse_mode_with_reply_none_no_reply_kwarg(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "текст", None, parse_mode="HTML")
        kwargs = bot.send_message.await_args.kwargs
        assert kwargs["parse_mode"] == "HTML"
        assert "reply_to_message_id" not in kwargs

    @pytest.mark.asyncio
    async def test_parse_mode_kept_on_gone_fallback(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=[_gone_400(), None])
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "ответ", 42, parse_mode="HTML")
        calls = bot.send_message.await_args_list
        assert calls[0].kwargs["parse_mode"] == "HTML"
        assert "reply_to_message_id" not in calls[1].kwargs
        assert calls[1].kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_parse_mode_kept_on_retry_after(self, monkeypatch):
        sleep = AsyncMock()
        monkeypatch.setattr(utils_mod.asyncio, "sleep", sleep)
        bot = AsyncMock()
        retry_error = TelegramRetryAfter(method=None, message="retry", retry_after=3)
        bot.send_message = AsyncMock(side_effect=[retry_error, None])
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "текст", 42, parse_mode="HTML")
        assert bot.send_message.await_count == 2
        for call in bot.send_message.await_args_list:
            assert call.kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_parse_mode_on_all_chunks(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        await utils_mod.send_chunked_reply(bot, CHAT_ID, _long_text(), 42, parse_mode="HTML")
        for call in bot.send_message.await_args_list:
            assert call.kwargs["parse_mode"] == "HTML"


class TestReply:
    @pytest.mark.asyncio
    async def test_sends_with_reply_to(self):
        bot = AsyncMock()
        await utils_mod._reply(bot, CHAT_ID, "привет", 42)
        bot.send_message.assert_awaited_once_with(
            CHAT_ID, "привет", reply_to_message_id=42
        )

    @pytest.mark.asyncio
    async def test_send_failure_warns_but_does_not_raise(self, caplog):
        import logging

        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=Exception("сеть упала"))
        with caplog.at_level(logging.WARNING):
            await utils_mod._reply(bot, CHAT_ID, "привет", 42)
        assert any("failed to send reply" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_bot_warns_and_returns(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            await utils_mod._reply(None, CHAT_ID, "привет")
        assert any("no bot available" in r.message for r in caplog.records)


class TestSendOnceFallback:
    """Epic 34 (43.4): _send_once — единая точка отправки с reply-fallback."""

    @pytest.mark.asyncio
    async def test_reply_gone_400_retries_once_without_reply(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=[_gone_400(), None])
        await utils_mod._reply(bot, CHAT_ID, "ответ", 42)
        assert bot.send_message.await_count == 2
        calls = bot.send_message.await_args_list
        assert calls[0].args == (CHAT_ID, "ответ")
        assert calls[0].kwargs["reply_to_message_id"] == 42
        assert calls[1].args == (CHAT_ID, "ответ")
        assert "reply_to_message_id" not in calls[1].kwargs

    @pytest.mark.asyncio
    async def test_other_bad_request_propagates_without_retry(self):
        bot = AsyncMock()
        other = TelegramBadRequest(method=None, message="Bad Request: chat not found")
        bot.send_message = AsyncMock(side_effect=other)
        with pytest.raises(TelegramBadRequest):
            await utils_mod._send_once(bot, CHAT_ID, "ответ", 42)
        assert bot.send_message.await_count == 1

    @pytest.mark.asyncio
    async def test_no_reply_gone_400_does_not_fallback(self):
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=_gone_400())
        with pytest.raises(TelegramBadRequest):
            await utils_mod._send_once(bot, CHAT_ID, "ответ")
        assert bot.send_message.await_count == 1
        assert "reply_to_message_id" not in bot.send_message.await_args.kwargs

    @pytest.mark.asyncio
    async def test_chunked_first_chunk_gone_fallback_others_plain(self, monkeypatch):
        monkeypatch.setattr(utils_mod.asyncio, "sleep", AsyncMock())
        bot = AsyncMock()
        text = _long_text()
        chunks = SummaryGenerator._chunk_by_whitespace(text, utils_mod._CHUNK_LIMIT)
        assert len(chunks) > 1
        bot.send_message = AsyncMock(side_effect=[_gone_400()] + [None] * len(chunks))
        await utils_mod.send_chunked_reply(bot, CHAT_ID, text, 42)
        assert bot.send_message.await_count == len(chunks) + 1
        calls = bot.send_message.await_args_list
        assert calls[0].kwargs["reply_to_message_id"] == 42
        assert calls[0].args[1] == chunks[0]
        assert "reply_to_message_id" not in calls[1].kwargs
        assert calls[1].args[1] == chunks[0]
        for call, chunk in zip(calls[2:], chunks[1:]):
            assert "reply_to_message_id" not in call.kwargs
            assert call.args[1] == chunk

    @pytest.mark.asyncio
    async def test_retry_after_retry_goes_through_send_once(self, monkeypatch):
        sleep = AsyncMock()
        monkeypatch.setattr(utils_mod.asyncio, "sleep", sleep)
        bot = AsyncMock()
        retry_error = TelegramRetryAfter(method=None, message="retry", retry_after=3)
        bot.send_message = AsyncMock(side_effect=[retry_error, _gone_400(), None])
        await utils_mod.send_chunked_reply(bot, CHAT_ID, "текст", 42)
        assert bot.send_message.await_count == 3
        sleep.assert_awaited_once_with(3)
        calls = bot.send_message.await_args_list
        assert calls[0].kwargs["reply_to_message_id"] == 42
        assert calls[1].kwargs["reply_to_message_id"] == 42
        assert "reply_to_message_id" not in calls[2].kwargs

    @pytest.mark.asyncio
    async def test_successful_send_exactly_one_call(self):
        bot = AsyncMock()
        await utils_mod._send_once(bot, CHAT_ID, "ответ", 42)
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 42

    @pytest.mark.asyncio
    async def test_fallback_logs_warning_and_info(self, caplog):
        import logging

        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=[_gone_400(), None])
        with caplog.at_level(logging.INFO):
            await utils_mod._reply(bot, CHAT_ID, "ответ", 42)
        assert any(
            "reply target gone" in r.message and r.levelno == logging.WARNING
            for r in caplog.records
        )
        assert any(
            "sent without reply" in r.message and r.levelno == logging.INFO
            for r in caplog.records
        )


class TestThrottlePhrase:
    def test_placeholder_substituted(self, monkeypatch):
        monkeypatch.setattr(
            utils_mod.random, "choice", lambda pool: THROTTLE_PHRASES[0]
        )
        text = utils_mod.throttle_phrase(300.0)
        assert text == "отъебись от меня, подожди 5 мин"
        assert "{remaining_time}" not in text

    def test_seconds_format(self, monkeypatch):
        monkeypatch.setattr(
            utils_mod.random, "choice", lambda pool: THROTTLE_PHRASES[1]
        )
        text = utils_mod.throttle_phrase(45.0)
        assert text == "че доебался, жди 45 сек"

    def test_membership_in_pool(self, monkeypatch):
        monkeypatch.setattr(utils_mod.random, "choice", lambda pool: pool[2])
        text = utils_mod.throttle_phrase(90.0)
        candidates = [
            p.replace("{remaining_time}", "1 мин 30 сек") for p in THROTTLE_PHRASES
        ]
        assert text in candidates
