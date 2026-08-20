"""Tests for handlers/factcheck.py (T-257-A, R33-3, Section 42.7.1/42.10).

Парсер триггера (^фактчек\b, регистронезависимо), user_hint, репост-вариант,
reply-таргеты: вердикт/5.3/5.4b/5.5 → target.message_id (ЦЕЛЕВОЕ),
троттлинг 5.1 → message.message_id (ВЫЗОВ, D107).
"""
import datetime
import logging

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Chat, MessageOriginChannel
from unittest.mock import AsyncMock, MagicMock

from handlers import factcheck as factcheck_mod
from services.llm_client import LLMError
from services.search_aggregator import AllSearchEnginesFailedException
from services.smartmodule_phrases import (
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    LLM_ERROR_PHRASES,
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
def factcheck_cleanup():
    yield
    factcheck_mod._service = None
    factcheck_mod._cooldown._last.clear()


def _make_msg(text=None, caption=None, message_id=1, user_id=1,
              reply_to_message=None, forward_origin=None, media_group_id=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.reply_to_message = reply_to_message
    msg.forward_origin = forward_origin
    msg.media_group_id = media_group_id   # Epic 36: не альбом по умолчанию
    return msg


@pytest.fixture
def media_buffer_cleanup():
    from services import media_group_buffer as mgb_mod

    yield
    mgb_mod._buffer.clear()


@pytest.fixture
def buffer_time(monkeypatch):
    from services import media_group_buffer as mgb_mod

    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr(mgb_mod, "time", FakeTime)
    return state


def _channel_origin(title="Канал X", username="channelx", signature="Подпись"):
    return MessageOriginChannel(
        date=datetime.datetime.now(),
        chat=Chat(id=-777, type="channel", title=title, username=username),
        message_id=5,
        author_signature=signature,
    )


class TestParseTrigger:
    @pytest.mark.parametrize(
        "text", ["фактчек", "ФАКТЧЕК", "Фактчек", "фактчек про дату"]
    )
    def test_trigger_matches_case_insensitive(self, text):
        target = _make_msg(message_id=77)
        msg = _make_msg(text=text, reply_to_message=target)
        parsed_target, hint = factcheck_mod._parse_trigger(msg)
        assert parsed_target is target

    @pytest.mark.parametrize("text", ["фактчекинг", "это фактчек", "проверь факты"])
    def test_non_triggers(self, text):
        target = _make_msg(message_id=77)
        msg = _make_msg(text=text, reply_to_message=target)
        assert factcheck_mod._parse_trigger(msg) == (None, None)

    def test_trigger_without_reply_or_forward_is_not_trigger(self):
        msg = _make_msg(text="фактчек")
        assert factcheck_mod._parse_trigger(msg) == (None, None)

    def test_repost_media_variant_caption_trigger_target_is_self(self):
        """Репост-вариант: медиа-репост (text=None) с caption-триггером → target=self."""
        msg = _make_msg(
            text=None,
            caption="фактчек",
            forward_origin=_channel_origin(),
        )
        target, hint = factcheck_mod._parse_trigger(msg)
        assert target is msg

    def test_repost_text_trigger_target_is_self(self):
        """Репост-вариант: текст репоста сам начинается с «фактчек» → target=self."""
        msg = _make_msg(
            text="фактчек сам",
            forward_origin=_channel_origin(),
        )
        target, hint = factcheck_mod._parse_trigger(msg)
        assert target is msg

    def test_repost_text_wins_over_caption(self):
        """Фактическое поведение кода 4a: (text or caption) — при непустом text
        caption-триггер не проверяется → не триггер."""
        msg = _make_msg(
            text="контент репоста",
            caption="фактчек",
            forward_origin=_channel_origin(),
        )
        assert factcheck_mod._parse_trigger(msg) == (None, None)

    def test_user_hint_extraction(self):
        target = _make_msg(message_id=77)
        msg = _make_msg(text="фактчек про дату", reply_to_message=target)
        _, hint = factcheck_mod._parse_trigger(msg)
        assert hint == "про дату"

    def test_user_hint_after_comma(self):
        target = _make_msg(message_id=77)
        msg = _make_msg(text="фактчек, это так?", reply_to_message=target)
        _, hint = factcheck_mod._parse_trigger(msg)
        assert hint == "это так?"

    def test_user_hint_empty_when_nothing_after(self):
        target = _make_msg(message_id=77)
        msg = _make_msg(text="фактчек  ", reply_to_message=target)
        _, hint = factcheck_mod._parse_trigger(msg)
        assert hint is None


class TestExtractTargetText:
    def test_reply_target_text(self):
        target = _make_msg(text="Земля плоская")
        msg = _make_msg(text="фактчек")
        assert factcheck_mod._extract_target_text(msg, target) == "Земля плоская"

    def test_reply_target_caption(self):
        target = _make_msg(text=None, caption="глянь это")
        msg = _make_msg(text="фактчек")
        assert factcheck_mod._extract_target_text(msg, target) == "глянь это"

    def test_reply_target_empty(self):
        target = _make_msg(text=None, caption=None)
        msg = _make_msg(text="фактчек")
        assert factcheck_mod._extract_target_text(msg, target) is None

    def test_repost_target_trigger_text_means_empty(self):
        """Репост: текст сам начинается с «фактчек» → нечего проверять (5.3)."""
        msg = _make_msg(text="фактчек сам", forward_origin=_channel_origin())
        assert factcheck_mod._extract_target_text(msg, msg) is None

    def test_repost_target_plain_text(self):
        msg = _make_msg(text="контент репоста", forward_origin=_channel_origin())
        assert factcheck_mod._extract_target_text(msg, msg) == "контент репоста"


class TestHandlerReplyTargets:
    @pytest.mark.asyncio
    async def test_verdict_replies_to_target(self, factcheck_cleanup):
        service = MagicMock()
        service.check_claim = AsyncMock(return_value="вердикт: пиздеж")
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text="Земля плоская", message_id=77)
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        result = await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert result is None  # консьюм
        assert bot.send_message.await_args.args[0] == CHAT_ID
        assert bot.send_message.await_args.args[1] == "вердикт: пиздеж"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77

    @pytest.mark.asyncio
    async def test_search_error_replies_to_target(self, factcheck_cleanup):
        service = MagicMock()
        service.check_claim = AsyncMock(
            side_effect=AllSearchEnginesFailedException("все упали")
        )
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text="текст", message_id=77)
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in FACTCHECK_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77

    @pytest.mark.asyncio
    async def test_llm_error_replies_to_target(self, factcheck_cleanup, caplog):
        """D190 (#28): LLMError → WARNING (exc_info пустой) + 5.5 на target."""
        service = MagicMock()
        service.check_claim = AsyncMock(side_effect=LLMError("llm сдох"))
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text="текст", message_id=77)
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        with caplog.at_level(logging.WARNING):
            await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        assert any(
            r.name == "handlers.factcheck" and "LLM failed" in r.message
            and "| error=llm сдох" in r.message and r.exc_info is None
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_unexpected_error_replies_to_target(self, factcheck_cleanup, caplog):
        """D190 (#27): неожиданный Exception → logger.exception (ERROR, exc_info)."""
        service = MagicMock()
        service.check_claim = AsyncMock(side_effect=RuntimeError("неожиданно"))
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text="текст", message_id=77)
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        with caplog.at_level(logging.ERROR):
            await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        assert any(
            r.name == "handlers.factcheck" and "unexpected error" in r.message
            and r.exc_info is not None
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_empty_context_replies_to_target_without_search(self, factcheck_cleanup):
        """5.3: пустой контекст цели → фраза на ЦЕЛЕВОЕ, агрегатор НЕ вызывается."""
        service = MagicMock()
        service.check_claim = AsyncMock()
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text=None, caption=None, message_id=77)
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in FACTCHECK_EMPTY_CONTEXT_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77
        service.check_claim.assert_not_called()

    @pytest.mark.asyncio
    async def test_throttle_replies_to_call_message(self, factcheck_cleanup, fake_time):
        """5.1/D107: троттлинг → reply на message.message_id ВЫЗОВА."""
        service = MagicMock()
        service.check_claim = AsyncMock(return_value="вердикт")
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text="текст", message_id=77)
        first = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(first, bot=bot)
        assert service.check_claim.await_count == 1

        fake_time["now"] += 100
        expected_remaining = factcheck_mod._cooldown.remaining(CHAT_ID, 1)
        assert expected_remaining > 0
        second = _make_msg(text="фактчек", message_id=22, reply_to_message=target)
        await factcheck_mod.factcheck_handler(second, bot=bot)
        assert service.check_claim.await_count == 1  # второй вызов НЕ прошёл
        fmt = format_remaining_time(expected_remaining)
        candidates = [p.replace("{remaining_time}", fmt) for p in THROTTLE_PHRASES]
        assert bot.send_message.await_args.args[1] in candidates
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 22

    @pytest.mark.asyncio
    async def test_non_trigger_returns_unhandled(self, factcheck_cleanup):
        service = MagicMock()
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text="текст", message_id=77)
        msg = _make_msg(text="фактчекинг", message_id=11, reply_to_message=target)
        result = await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert result is UNHANDLED
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_service_returns_unhandled(self, factcheck_cleanup):
        factcheck_mod._service = None
        bot = AsyncMock()
        target = _make_msg(text="текст", message_id=77)
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        result = await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_forward_target_passes_source_to_service(self, factcheck_cleanup):
        """Целевой репост → forward_source в аргументах сервиса."""
        service = MagicMock()
        service.check_claim = AsyncMock(return_value="вердикт")
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(
            text="содержание репоста", message_id=77, forward_origin=_channel_origin()
        )
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        service.check_claim.assert_awaited_once_with(
            "содержание репоста", None, "Канал X @channelx Подпись", chat_id=CHAT_ID
        )

    @pytest.mark.asyncio
    async def test_repost_self_variant_flow(self, factcheck_cleanup):
        """Репост-вариант: caption-триггер на медиа-репосте → target=self;
        текст цели пуст (репост без текста) → 5.3, reply на свой message_id,
        БЕЗ вызова сервиса."""
        service = MagicMock()
        service.check_claim = AsyncMock()
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        msg = _make_msg(
            text=None,
            caption="фактчек",
            message_id=33,
            forward_origin=_channel_origin(),
        )
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in FACTCHECK_EMPTY_CONTEXT_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 33
        service.check_claim.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_answer_sent_as_is(self, factcheck_cleanup):
        """cleanup — внутри сервиса (R33-7); хендлер шлёт текст без изменений."""
        service = MagicMock()
        service.check_claim = AsyncMock(return_value='уже чисто: "кавычки" - дефис')
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text="текст", message_id=77)
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] == 'уже чисто: "кавычки" - дефис'

    @pytest.mark.asyncio
    async def test_gone_400_on_target_delivers_verdict_without_reply(
        self, factcheck_cleanup, caplog
    ):
        """Epic 34 (#9): target.message_id «удалён» → gone-400 → fallback без
        reply; вердикт доставлен, ровно 2 вызова, без ERROR-лога
        (симметрия 43.3 — фактчек делит те же utils)."""
        import logging

        from aiogram.exceptions import TelegramBadRequest

        service = MagicMock()
        service.check_claim = AsyncMock(return_value="вердикт: пиздеж")
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        gone = TelegramBadRequest(
            method=None, message="Bad Request: message to be replied not found"
        )
        bot.send_message = AsyncMock(side_effect=[gone, None])
        target = _make_msg(text="Земля плоская", message_id=77)
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        with caplog.at_level(logging.ERROR):
            await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_count == 2
        calls = bot.send_message.await_args_list
        assert calls[0].kwargs["reply_to_message_id"] == 77
        assert "reply_to_message_id" not in calls[1].kwargs
        assert calls[1].args[1] == "вердикт: пиздеж"
        assert not any("unexpected error" in r.message for r in caplog.records)


class TestAlbumCaptionBuffer:
    """Epic 36 (R36-1, Section 45.3 #12-16): reply на 2-е/3-е фото альбома —
    caption берётся из MediaGroupCaptionBuffer (заполняется observer 0a)."""

    def _fill(self, caption, media_group_id="album-1", message_id=70):
        from services import media_group_buffer as mgb_mod

        mgb_mod.record_media_group_message(
            _make_msg(caption=caption, message_id=message_id,
                      media_group_id=media_group_id)
        )

    @pytest.mark.asyncio
    async def test_album_target_uses_buffered_caption(
        self, factcheck_cleanup, media_buffer_cleanup
    ):
        """#12: буфер записан observer'ом → reply на 2-е фото (без caption)
        → check_claim получает caption 1-го фото, reply на target.message_id."""
        service = MagicMock()
        service.check_claim = AsyncMock(return_value="вердикт: пиздеж")
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        self._fill("текст новости")
        target = _make_msg(text=None, caption=None, message_id=71,
                           media_group_id="album-1")
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        service.check_claim.assert_awaited_once_with(
            "текст новости", None, None, chat_id=CHAT_ID
        )
        assert bot.send_message.await_args.args[1] == "вердикт: пиздеж"
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 71

    @pytest.mark.asyncio
    async def test_album_reply_before_buffer_fill_goes_empty_context(
        self, factcheck_cleanup, media_buffer_cleanup
    ):
        """#13: reply ДО заполнения буфера (буфер пуст) → 5.3, check_claim не вызван."""
        service = MagicMock()
        service.check_claim = AsyncMock()
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        target = _make_msg(text=None, caption=None, message_id=71,
                           media_group_id="album-empty")
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in FACTCHECK_EMPTY_CONTEXT_PHRASES
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 71
        service.check_claim.assert_not_called()

    @pytest.mark.asyncio
    async def test_album_caption_expired_goes_empty_context(
        self, factcheck_cleanup, media_buffer_cleanup, buffer_time
    ):
        """#14: TTL истёк → 5.3."""
        from services import media_group_buffer as mgb_mod

        service = MagicMock()
        service.check_claim = AsyncMock()
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        self._fill("текст новости", media_group_id="album-ttl")
        buffer_time["now"] += mgb_mod.TTL_SECONDS + 1
        target = _make_msg(text=None, caption=None, message_id=71,
                           media_group_id="album-ttl")
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in FACTCHECK_EMPTY_CONTEXT_PHRASES
        service.check_claim.assert_not_called()

    @pytest.mark.asyncio
    async def test_album_caption_lru_evicted_goes_empty_context(
        self, factcheck_cleanup, media_buffer_cleanup
    ):
        """#15: LRU-эвикция записи → 5.3."""
        from services import media_group_buffer as mgb_mod

        service = MagicMock()
        service.check_claim = AsyncMock()
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        self._fill("старейший caption", media_group_id="album-lru")
        for i in range(1, mgb_mod.MAX_ENTRIES + 1):
            self._fill(f"c{i}", media_group_id=f"album-{i}")
        assert mgb_mod.get_media_group_caption("album-lru") is None
        target = _make_msg(text=None, caption=None, message_id=71,
                           media_group_id="album-lru")
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in FACTCHECK_EMPTY_CONTEXT_PHRASES
        service.check_claim.assert_not_called()

    @pytest.mark.asyncio
    async def test_direct_caption_has_priority_over_buffer(
        self, factcheck_cleanup, media_buffer_cleanup
    ):
        """#16: у цели есть прямой caption → буфер не читается (регрессия)."""
        service = MagicMock()
        service.check_claim = AsyncMock(return_value="вердикт")
        factcheck_mod.setup_factcheck(service)
        bot = AsyncMock()
        self._fill("старый caption из буфера", media_group_id="album-dir")
        target = _make_msg(text=None, caption="глянь это", message_id=71,
                           media_group_id="album-dir")
        msg = _make_msg(text="фактчек", message_id=11, reply_to_message=target)
        await factcheck_mod.factcheck_handler(msg, bot=bot)
        service.check_claim.assert_awaited_once_with(
            "глянь это", None, None, chat_id=CHAT_ID
        )
