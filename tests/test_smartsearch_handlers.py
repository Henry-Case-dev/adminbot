"""Tests for handlers/search.py (T-257-A, R33-4, Section 42.7.2/42.10).

Регулярка ДОСЛОВНО из ТЗ: «найди/поищи/загугли» + тело; пустой запрос → 5.2
БЕЗ поисковиков; ВСЕ ответы → reply на message.message_id; 5.1 при троттлинге;
5.4a/5.5.
"""
import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from unittest.mock import AsyncMock, MagicMock

from handlers import search as search_mod
from services.llm_client import LLMError
from services.search_aggregator import AllSearchEnginesFailedException
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    SEARCH_EMPTY_QUERY_PHRASES,
    SEARCH_ERROR_PHRASES,
    THROTTLE_PHRASES,
)
from services.smartmodule_throttling import format_remaining_time

CHAT_ID = -1001234567890


@pytest.fixture
def fake_time(monkeypatch):
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr("services.smartmodule_throttling.time", FakeTime)
    return state


@pytest.fixture
def search_cleanup():
    yield
    search_mod._service = None
    search_mod._cooldown._last.clear()


def _make_msg(text=None, message_id=1, user_id=1):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    return msg


class TestParseSearchQuery:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("найди X", "X"),
            ("НАЙДИ x", "x"),
            ("Найди котиков", "котиков"),
            ("поищи X", "X"),
            ("загугли X", "X"),
            ("найди, мне X", "X"),          # «найди, мне X» → body «X» (ТЗ-квирк)
            ("поищи пожалуйста X", "X"),
            ("найди мне X", "X"),
            ("загугли,  пожалуйста X", "X"),
            ("поищи: где пруфы", "где пруфы"),
            ("   найди это", "это"),        # raw.strip() перед парсингом
        ],
    )
    def test_query_body(self, raw, expected):
        assert search_mod._parse_search_query(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("найди", ""),
            ("найди   ", ""),
            ("найди,", ""),
            ("ПОИЩИ", ""),
            # ТЗ-квирк: «загугли,,» — жадный [\s,:]+ отдаёт один разделитель (.+)
            # и телом становится последняя запятая (фактическое поведение кода 4a)
            ("загугли,,", ","),
        ],
    )
    def test_empty_query_trigger(self, raw, expected):
        assert search_mod._parse_search_query(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["найдикто", "проверь", "найдите X", "привет", ""]
    )
    def test_non_trigger(self, raw):
        assert search_mod._parse_search_query(raw) is None


class TestHandler:
    @pytest.mark.asyncio
    async def test_summary_replies_to_message(self, search_cleanup):
        service = MagicMock()
        service.research = AsyncMock(return_value="выжимка сути")
        search_mod.setup_search(service)
        bot = AsyncMock()
        msg = _make_msg(text="найди пруфы", message_id=11)
        result = await search_mod.smartsearch_handler(msg, bot=bot)
        assert result is None
        service.research.assert_awaited_once_with("пруфы", chat_id=CHAT_ID)
        assert bot.send_message.await_args.args[1] == "выжимка сути"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_empty_query_5_2_without_search(self, search_cleanup):
        """5.2: «найди» без тела → фраза на message_id, БЕЗ поисковиков."""
        service = MagicMock()
        service.research = AsyncMock()
        search_mod.setup_search(service)
        bot = AsyncMock()
        msg = _make_msg(text="найди", message_id=11)
        await search_mod.smartsearch_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in SEARCH_EMPTY_QUERY_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11
        service.research.assert_not_called()

    @pytest.mark.asyncio
    async def test_throttle_5_1_replies_to_message(self, search_cleanup, fake_time):
        service = MagicMock()
        service.research = AsyncMock(return_value="выжимка")
        search_mod.setup_search(service)
        bot = AsyncMock()
        first = _make_msg(text="найди раз", message_id=11)
        await search_mod.smartsearch_handler(first, bot=bot)
        assert service.research.await_count == 1

        fake_time["now"] += 100
        expected_remaining = search_mod._cooldown.remaining(CHAT_ID, 1)
        assert expected_remaining > 0
        second = _make_msg(text="найди два", message_id=22)
        await search_mod.smartsearch_handler(second, bot=bot)
        assert service.research.await_count == 1
        fmt = format_remaining_time(expected_remaining)
        candidates = [p.replace("{remaining_time}", fmt) for p in THROTTLE_PHRASES]
        assert bot.send_message.await_args.args[1] in candidates
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 22

    @pytest.mark.asyncio
    async def test_search_error_5_4a_replies_to_message(self, search_cleanup):
        service = MagicMock()
        service.research = AsyncMock(
            side_effect=AllSearchEnginesFailedException("все упали")
        )
        search_mod.setup_search(service)
        bot = AsyncMock()
        msg = _make_msg(text="найди что-то", message_id=11)
        await search_mod.smartsearch_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in SEARCH_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_llm_error_5_5_replies_to_message(self, search_cleanup):
        service = MagicMock()
        service.research = AsyncMock(side_effect=LLMError("llm сдох"))
        search_mod.setup_search(service)
        bot = AsyncMock()
        msg = _make_msg(text="найди что-то", message_id=11)
        await search_mod.smartsearch_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_unexpected_error_5_5_replies_to_message(self, search_cleanup):
        service = MagicMock()
        service.research = AsyncMock(side_effect=RuntimeError("неожиданно"))
        search_mod.setup_search(service)
        bot = AsyncMock()
        msg = _make_msg(text="найди что-то", message_id=11)
        await search_mod.smartsearch_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_non_trigger_returns_unhandled(self, search_cleanup):
        service = MagicMock()
        search_mod.setup_search(service)
        bot = AsyncMock()
        msg = _make_msg(text="проверь это", message_id=11)
        result = await search_mod.smartsearch_handler(msg, bot=bot)
        assert result is UNHANDLED
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_service_returns_unhandled(self, search_cleanup):
        search_mod._service = None
        bot = AsyncMock()
        msg = _make_msg(text="найди что-то", message_id=11)
        result = await search_mod.smartsearch_handler(msg, bot=bot)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_caption_triggers_too(self, search_cleanup):
        service = MagicMock()
        service.research = AsyncMock(return_value="выжимка")
        search_mod.setup_search(service)
        bot = AsyncMock()
        msg = _make_msg(text=None, message_id=11)
        msg.caption = "загугли мем"
        await search_mod.smartsearch_handler(msg, bot=bot)
        service.research.assert_awaited_once_with("мем", chat_id=CHAT_ID)
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_gone_400_fallback_delivers_without_reply_no_error(
        self, search_cleanup, caplog
    ):
        """Epic 34 (#8, T-263-C): 1-й send_message с reply → «gone»-400,
        2-й без reply OK → доставка есть, logger.exception НЕ вызывается,
        ровно 2 вызова send_message (дублей нет)."""
        import logging

        from aiogram.exceptions import TelegramBadRequest

        service = MagicMock()
        service.research = AsyncMock(return_value="выжимка сути")
        search_mod.setup_search(service)
        bot = AsyncMock()
        gone = TelegramBadRequest(
            method=None, message="Bad Request: message to be replied not found"
        )
        bot.send_message = AsyncMock(side_effect=[gone, None])
        msg = _make_msg(text="найди пруфы", message_id=11)
        with caplog.at_level(logging.ERROR):
            await search_mod.smartsearch_handler(msg, bot=bot)
        assert bot.send_message.await_count == 2
        calls = bot.send_message.await_args_list
        assert calls[0].kwargs["reply_to_message_id"] == 11
        assert "reply_to_message_id" not in calls[1].kwargs
        assert calls[1].args[1] == "выжимка сути"
        assert not any("unexpected error" in r.message for r in caplog.records)
