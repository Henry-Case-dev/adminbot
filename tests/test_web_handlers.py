"""Tests for handlers/web.py (T-289, R37-4, D126/D128/D131, Section 46.9.2/46.12).

Сценарии А/Б (reply / single-message), D126-fallback А→Б, не-триггеры →
UNHANDLED, reply-таргеты: успех/5.7/5.5 → target.message_id (ЦЕЛЕВОЕ),
троттлинг 5.1 → message.message_id (ВЫЗОВ). extract_web_url НЕ отдаёт
YouTube-URL в сервис (D128).
"""
import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from unittest.mock import AsyncMock, MagicMock

from handlers import web as web_mod
from services.llm_client import LLMError
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    THROTTLE_PHRASES,
    WEB_ERROR_PHRASES,
)
from services.smartmodule_throttling import format_remaining_time
from services.web_content_extractor import WebContentExtractionFailedException

CHAT_ID = -1001234567890
WEB_URL = "https://habr.com/ru/articles/1"
YT_URL = "https://youtu.be/dQw4w9WgXcQ"


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
def web_cleanup():
    yield
    web_mod._service = None
    web_mod._cooldown._last.clear()


def _make_msg(text=None, caption=None, message_id=1, user_id=1,
              reply_to_message=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.reply_to_message = reply_to_message
    return msg


class TestParse:
    def test_scenario_a_reply_with_url(self):
        """#28: reply на сообщение с веб-URL + триггер → (reply, url)."""
        target = _make_msg(text=f"вот статья {WEB_URL}", message_id=77)
        msg = _make_msg(text="поясни за статью", message_id=11,
                        reply_to_message=target)
        parsed_target, url = web_mod._parse(msg)
        assert parsed_target is target
        assert url == WEB_URL

    def test_scenario_b_url_and_trigger_in_one_message(self):
        """#29: URL+триггер в одном сообщении → (message, url)."""
        msg = _make_msg(text=f"{WEB_URL} че по ссылке", message_id=11)
        target, url = web_mod._parse(msg)
        assert target is msg
        assert url == WEB_URL

    def test_scenario_b_caption(self):
        msg = _make_msg(text=None, caption=f"выжимка {WEB_URL}", message_id=11)
        target, url = web_mod._parse(msg)
        assert target is msg
        assert url == WEB_URL

    def test_d126_fallback_from_a_to_b(self):
        """#30: reply есть, URL в цели НЕТ, URL в вызове есть → таргет = вызов."""
        target = _make_msg(text="просто текст без ссылок", message_id=77)
        msg = _make_msg(text=f"о чем статья {WEB_URL}", message_id=11,
                        reply_to_message=target)
        target_out, url = web_mod._parse(msg)
        assert target_out is msg
        assert url == WEB_URL

    def test_trigger_without_url_anywhere_not_trigger(self):
        target = _make_msg(text="без ссылок", message_id=77)
        msg = _make_msg(text="выжимка", message_id=11, reply_to_message=target)
        assert web_mod._parse(msg) == (None, None)

    def test_url_without_trigger_not_trigger(self):
        msg = _make_msg(text=f"просто скинул {WEB_URL}", message_id=11)
        assert web_mod._parse(msg) == (None, None)

    def test_youtube_url_alone_not_trigger(self):
        """YT-URL без веб-URL → extract_web_url возвращает None → UNHANDLED."""
        msg = _make_msg(text=f"выжимка {YT_URL}", message_id=11)
        assert web_mod._parse(msg) == (None, None)

    def test_youtube_url_skipped_web_url_taken(self):
        """D128: в тексте YT-URL И веб-URL → сервис получает веб-URL."""
        msg = _make_msg(text=f"{YT_URL} и {WEB_URL} че по ссылке", message_id=11)
        target, url = web_mod._parse(msg)
        assert target is msg
        assert url == WEB_URL

    @pytest.mark.parametrize(
        "trigger",
        ["поясни за ссылку", "че по ссылке", "о чем статья", "поясни за статью",
         "выжимка", "че на сайте", "перескажи статью"],
    )
    def test_all_triggers_case_insensitive(self, trigger):
        """#35: все 7 триггеров регистронезависимо."""
        msg = _make_msg(text=f"{trigger.upper()} {WEB_URL}", message_id=11)
        target, url = web_mod._parse(msg)
        assert target is msg
        assert url == WEB_URL


class TestHandler:
    @pytest.mark.asyncio
    async def test_success_replies_to_target_scenario_a(self, web_cleanup):
        """#28: успех → reply на target.message_id (целевое, сценарий А)."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка статьи")
        web_mod.setup_web(service)
        bot = AsyncMock()
        target = _make_msg(text=WEB_URL, message_id=77)
        msg = _make_msg(text="поясни за статью", message_id=11,
                        reply_to_message=target)
        result = await web_mod.web_handler(msg, bot=bot)
        assert result is None  # консьюм
        assert bot.send_message.await_args.args[0] == CHAT_ID
        assert bot.send_message.await_args.args[1] == "выжимка статьи"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        service.summarize.assert_awaited_once_with(
            WEB_URL, chat_id=CHAT_ID, rag_query="поясни за статью"
        )

    @pytest.mark.asyncio
    async def test_success_replies_to_message_scenario_b(self, web_cleanup):
        """#29: сценарий Б → reply на message.message_id (само сообщение)."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка")
        web_mod.setup_web(service)
        bot = AsyncMock()
        msg = _make_msg(text=f"{WEB_URL} выжимка", message_id=11)
        await web_mod.web_handler(msg, bot=bot)
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_d126_fallback_success_replies_to_call(self, web_cleanup):
        """#30: А→Б fallback → ответ на сообщение вызова."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка")
        web_mod.setup_web(service)
        bot = AsyncMock()
        target = _make_msg(text="нет ссылки тут", message_id=77)
        msg = _make_msg(text=f"поясни за ссылку {WEB_URL}", message_id=11,
                        reply_to_message=target)
        await web_mod.web_handler(msg, bot=bot)
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_extractor_error_5_7_on_target(self, web_cleanup):
        """#35: WebContentExtractionFailedException → 5.7 на target."""
        service = MagicMock()
        service.summarize = AsyncMock(
            side_effect=WebContentExtractionFailedException("сайт сдох")
        )
        web_mod.setup_web(service)
        bot = AsyncMock()
        target = _make_msg(text=WEB_URL, message_id=77)
        msg = _make_msg(text="поясни за ссылку", message_id=11,
                        reply_to_message=target)
        await web_mod.web_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in WEB_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77

    @pytest.mark.asyncio
    async def test_llm_error_5_5_on_target(self, web_cleanup, caplog):
        """#35: LLMError → WARNING без exc_info + 5.5 на target."""
        import logging

        service = MagicMock()
        service.summarize = AsyncMock(side_effect=LLMError("llm сдох"))
        web_mod.setup_web(service)
        bot = AsyncMock()
        target = _make_msg(text=WEB_URL, message_id=77)
        msg = _make_msg(text="поясни за ссылку", message_id=11,
                        reply_to_message=target)
        with caplog.at_level(logging.WARNING):
            await web_mod.web_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        assert any(
            r.name == "handlers.web" and "LLM failed" in r.message
            and "| error=llm сдох" in r.message and r.exc_info is None
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_unexpected_error_5_5_on_target(self, web_cleanup, caplog):
        """#35: Exception → 5.5 на target + logger.exception."""
        import logging

        service = MagicMock()
        service.summarize = AsyncMock(side_effect=RuntimeError("неожиданно"))
        web_mod.setup_web(service)
        bot = AsyncMock()
        target = _make_msg(text=WEB_URL, message_id=77)
        msg = _make_msg(text="поясни за ссылку", message_id=11,
                        reply_to_message=target)
        with caplog.at_level(logging.ERROR):
            await web_mod.web_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        assert any("unexpected error" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)

    @pytest.mark.asyncio
    async def test_throttle_5_1_on_call_service_not_called(
        self, web_cleanup, fake_time
    ):
        """#35: троттлинг → 5.1 на message.message_id, сервис НЕ вызван, консьюм."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка")
        web_mod.setup_web(service)
        bot = AsyncMock()
        msg = _make_msg(text=f"{WEB_URL} выжимка", message_id=11)
        await web_mod.web_handler(msg, bot=bot)
        assert service.summarize.await_count == 1

        fake_time["now"] += 100
        expected_remaining = web_mod._cooldown.remaining(CHAT_ID, 1)
        assert expected_remaining > 0
        second = _make_msg(text=f"{WEB_URL} выжимка", message_id=22)
        result = await web_mod.web_handler(second, bot=bot)
        assert result is None  # консьюм
        assert service.summarize.await_count == 1
        fmt = format_remaining_time(expected_remaining)
        candidates = [p.replace("{remaining_time}", fmt) for p in THROTTLE_PHRASES]
        assert bot.send_message.await_args.args[1] in candidates
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 22

    @pytest.mark.asyncio
    async def test_non_trigger_returns_unhandled(self, web_cleanup):
        """#35: триггер без URL → UNHANDLED, сервис не вызван."""
        service = MagicMock()
        web_mod.setup_web(service)
        bot = AsyncMock()
        msg = _make_msg(text="выжимка", message_id=11)
        result = await web_mod.web_handler(msg, bot=bot)
        assert result is UNHANDLED
        bot.send_message.assert_not_called()
        service.summarize.assert_not_called()

    @pytest.mark.asyncio
    async def test_youtube_url_never_reaches_service(self, web_cleanup):
        """#36: только YT-URL → UNHANDLED, экстрактор НЕ вызван с YT-ссылкой."""
        service = MagicMock()
        service.summarize = AsyncMock()
        web_mod.setup_web(service)
        bot = AsyncMock()
        msg = _make_msg(text=f"выжимка {YT_URL}", message_id=11)
        result = await web_mod.web_handler(msg, bot=bot)
        assert result is UNHANDLED
        service.summarize.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_service_returns_unhandled(self, web_cleanup):
        web_mod._service = None
        bot = AsyncMock()
        msg = _make_msg(text=f"{WEB_URL} выжимка", message_id=11)
        result = await web_mod.web_handler(msg, bot=bot)
        assert result is UNHANDLED
