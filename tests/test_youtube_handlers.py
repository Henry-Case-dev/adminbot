"""Tests for handlers/youtube.py (T-289, R37-4, D126/D131, Section 46.9.1/46.12).

Сценарии А/Б (reply / single-message), D126-fallback А→Б, не-триггеры →
UNHANDLED, reply-таргеты: успех/5.6/5.5 → target.message_id (ЦЕЛЕВОЕ),
троттлинг 5.1 → message.message_id (ВЫЗОВ).
"""
import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from unittest.mock import AsyncMock, MagicMock

from handlers import youtube as youtube_mod
from services.llm_client import LLMError
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    THROTTLE_PHRASES,
    YOUTUBE_ERROR_PHRASES,
    YOUTUBE_RETRY_PHRASES,
)
from services.smartmodule_throttling import format_remaining_time
from services.youtube_transcript_engine import YouTubeTranscriptUnavailableException

CHAT_ID = -1001234567890
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
def youtube_cleanup():
    yield
    youtube_mod._service = None
    youtube_mod._cooldown._last.clear()


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
        """#28: reply на сообщение с YT-URL + триггер → (reply, id)."""
        target = _make_msg(text=f"вот видос {YT_URL}", message_id=77)
        msg = _make_msg(text="поясни за видос", message_id=11,
                        reply_to_message=target)
        parsed_target, video_id = youtube_mod._parse(msg)
        assert parsed_target is target
        assert video_id == "dQw4w9WgXcQ"

    def test_scenario_b_url_and_trigger_in_one_message(self):
        """#29: URL+триггер в одном сообщении → (message, id)."""
        msg = _make_msg(text=f"{YT_URL} че за видос вообще", message_id=11)
        target, video_id = youtube_mod._parse(msg)
        assert target is msg
        assert video_id == "dQw4w9WgXcQ"

    def test_scenario_b_trigger_first_url_last(self):
        """#29: любой порядок — триггер в начале, URL в конце."""
        msg = _make_msg(text=f"поясни за видос вот: {YT_URL}", message_id=11)
        target, video_id = youtube_mod._parse(msg)
        assert target is msg
        assert video_id == "dQw4w9WgXcQ"

    def test_scenario_b_caption(self):
        msg = _make_msg(text=None, caption=f"{YT_URL} о чем видео", message_id=11)
        target, video_id = youtube_mod._parse(msg)
        assert target is msg
        assert video_id == "dQw4w9WgXcQ"

    def test_d126_fallback_from_a_to_b(self):
        """#30: reply есть, URL в цели НЕТ, URL в вызове есть → таргет = вызов."""
        target = _make_msg(text="просто текст без ссылок", message_id=77)
        msg = _make_msg(text=f"че за видос {YT_URL}", message_id=11,
                        reply_to_message=target)
        target_out, video_id = youtube_mod._parse(msg)
        assert target_out is msg
        assert video_id == "dQw4w9WgXcQ"

    def test_trigger_without_url_anywhere_not_trigger(self):
        target = _make_msg(text="без ссылок", message_id=77)
        msg = _make_msg(text="поясни за видос", message_id=11,
                        reply_to_message=target)
        assert youtube_mod._parse(msg) == (None, None)

    def test_url_without_trigger_not_trigger(self):
        msg = _make_msg(text=f"просто скинул {YT_URL}", message_id=11)
        assert youtube_mod._parse(msg) == (None, None)

    def test_youtube_url_with_web_trigger_not_trigger(self):
        """YT-URL + web-триггер → UNHANDLED (триггер-сеты доменоспецифичны)."""
        msg = _make_msg(text=f"выжимка {YT_URL}", message_id=11)
        assert youtube_mod._parse(msg) == (None, None)

    @pytest.mark.parametrize(
        "trigger",
        ["транскрипт", "че за видос", "о чем видео", "поясни за видос",
         "перескажи видос", "че в видосе"],
    )
    def test_all_triggers_case_insensitive(self, trigger):
        """#32: все 6 триггеров регистронезависимо."""
        msg = _make_msg(text=f"{trigger.upper()} {YT_URL}", message_id=11)
        target, video_id = youtube_mod._parse(msg)
        assert target is msg
        assert video_id == "dQw4w9WgXcQ"


class TestHandler:
    @pytest.mark.asyncio
    async def test_success_replies_to_target_scenario_a(self, youtube_cleanup):
        """#28: успех → reply на target.message_id (целевое, сценарий А)."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка видоса")
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        target = _make_msg(text=f"{YT_URL}", message_id=77)
        msg = _make_msg(text="поясни за видос", message_id=11,
                        reply_to_message=target)
        result = await youtube_mod.youtube_handler(msg, bot=bot)
        assert result is None  # консьюм
        assert bot.send_message.await_args.args[0] == CHAT_ID
        assert bot.send_message.await_args.args[1] == "выжимка видоса"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        service.summarize.assert_awaited_once()
        await_args = service.summarize.await_args
        assert await_args.args[0] == "dQw4w9WgXcQ"
        assert "on_retry" in await_args.kwargs
        assert callable(await_args.kwargs["on_retry"])

    @pytest.mark.asyncio
    async def test_success_replies_to_message_scenario_b(self, youtube_cleanup):
        """#29: сценарий Б → reply на message.message_id (само сообщение)."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка")
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        msg = _make_msg(text=f"{YT_URL} че за видос", message_id=11)
        await youtube_mod.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_on_retry_callback_sends_pool_phrase_on_target(self, youtube_cleanup):
        """#17 (50.8): on_retry из kwargs summarize → фраза 5.8 реплаем на target (77)."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка видоса")
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        target = _make_msg(text=f"{YT_URL}", message_id=77)
        msg = _make_msg(text="поясни за видос", message_id=11,
                        reply_to_message=target)
        await youtube_mod.youtube_handler(msg, bot=bot)
        on_retry = service.summarize.await_args.kwargs["on_retry"]
        await on_retry(2, 4)
        assert bot.send_message.await_args.args[1] in YOUTUBE_RETRY_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77

    @pytest.mark.asyncio
    async def test_on_retry_called_four_times_sends_four_pool_phrases(
        self, youtube_cleanup
    ):
        """#18 (50.8): 4 вызова cb → 4 send_message, все тексты в пуле 5.8."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка")
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        msg = _make_msg(text=f"{YT_URL} че за видос", message_id=11)
        await youtube_mod.youtube_handler(msg, bot=bot)
        before = bot.send_message.await_count
        on_retry = service.summarize.await_args.kwargs["on_retry"]
        for attempt in (1, 2, 3, 4):
            await on_retry(attempt, 4)
        assert bot.send_message.await_count == before + 4
        texts = [c.args[1] for c in bot.send_message.await_args_list[before:]]
        assert all(t in YOUTUBE_RETRY_PHRASES for t in texts)

    @pytest.mark.asyncio
    async def test_d126_fallback_success_replies_to_call(self, youtube_cleanup):
        """#30: А→Б fallback → ответ на сообщение вызова."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка")
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        target = _make_msg(text="нет ссылки тут", message_id=77)
        msg = _make_msg(text=f"поясни за видос {YT_URL}", message_id=11,
                        reply_to_message=target)
        await youtube_mod.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 11

    @pytest.mark.asyncio
    async def test_transcript_error_5_6_on_target(self, youtube_cleanup):
        """#34: YouTubeTranscriptUnavailableException → 5.6 на target."""
        service = MagicMock()
        service.summarize = AsyncMock(
            side_effect=YouTubeTranscriptUnavailableException("нет субтитров")
        )
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        target = _make_msg(text=YT_URL, message_id=77)
        msg = _make_msg(text="поясни за видос", message_id=11,
                        reply_to_message=target)
        await youtube_mod.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in YOUTUBE_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77

    @pytest.mark.asyncio
    async def test_llm_error_5_5_on_target(self, youtube_cleanup, caplog):
        """#34: LLMError → WARNING без exc_info + 5.5 на target."""
        import logging

        service = MagicMock()
        service.summarize = AsyncMock(side_effect=LLMError("llm сдох"))
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        target = _make_msg(text=YT_URL, message_id=77)
        msg = _make_msg(text="поясни за видос", message_id=11,
                        reply_to_message=target)
        with caplog.at_level(logging.WARNING):
            await youtube_mod.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        assert any(
            r.name == "handlers.youtube" and "LLM failed" in r.message
            and "| error=llm сдох" in r.message and r.exc_info is None
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_unexpected_error_5_5_on_target(self, youtube_cleanup, caplog):
        """#34: Exception → 5.5 на target + logger.exception."""
        import logging

        service = MagicMock()
        service.summarize = AsyncMock(side_effect=RuntimeError("неожиданно"))
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        target = _make_msg(text=YT_URL, message_id=77)
        msg = _make_msg(text="поясни за видос", message_id=11,
                        reply_to_message=target)
        with caplog.at_level(logging.ERROR):
            await youtube_mod.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        assert any("unexpected error" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)   # полный трейс в лог

    @pytest.mark.asyncio
    async def test_throttle_5_1_on_call_service_not_called(
        self, youtube_cleanup, fake_time
    ):
        """#33: троттлинг → 5.1 на message.message_id, сервис НЕ вызван, консьюм."""
        service = MagicMock()
        service.summarize = AsyncMock(return_value="выжимка")
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        msg = _make_msg(text=f"{YT_URL} че за видос", message_id=11)
        await youtube_mod.youtube_handler(msg, bot=bot)
        assert service.summarize.await_count == 1

        fake_time["now"] += 100
        expected_remaining = youtube_mod._cooldown.remaining(CHAT_ID, 1)
        assert expected_remaining > 0
        second = _make_msg(text=f"{YT_URL} че за видос", message_id=22)
        result = await youtube_mod.youtube_handler(second, bot=bot)
        assert result is None  # консьюм
        assert service.summarize.await_count == 1  # второй вызов НЕ прошёл
        fmt = format_remaining_time(expected_remaining)
        candidates = [p.replace("{remaining_time}", fmt) for p in THROTTLE_PHRASES]
        assert bot.send_message.await_args.args[1] in candidates
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 22

    @pytest.mark.asyncio
    async def test_non_trigger_returns_unhandled(self, youtube_cleanup):
        """#31: триггер без URL → UNHANDLED, сервис не вызван."""
        service = MagicMock()
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        msg = _make_msg(text="поясни за видос", message_id=11)
        result = await youtube_mod.youtube_handler(msg, bot=bot)
        assert result is UNHANDLED
        bot.send_message.assert_not_called()
        service.summarize.assert_not_called()

    @pytest.mark.asyncio
    async def test_url_without_trigger_returns_unhandled(self, youtube_cleanup):
        service = MagicMock()
        youtube_mod.setup_youtube(service)
        bot = AsyncMock()
        msg = _make_msg(text=f"{YT_URL}", message_id=11)
        result = await youtube_mod.youtube_handler(msg, bot=bot)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_no_service_returns_unhandled(self, youtube_cleanup):
        youtube_mod._service = None
        bot = AsyncMock()
        msg = _make_msg(text=f"{YT_URL} че за видос", message_id=11)
        result = await youtube_mod.youtube_handler(msg, bot=bot)
        assert result is UNHANDLED
