"""Tests for Epic 37 router isolation (T-289, Section 46.12 #37).

Один aiogram Dispatcher: summary_observer_router (0a) + youtube_router (0e) +
web_router (0f) + common_router (4c). Прогон через Dispatcher.feed_update
(прецедент test_epic33_router_isolation.py):
- YT-сообщение → ровно 1 ответ от 0e;
- веб-сообщение → ровно 1 ответ от 0f;
- URL без триггера → 0e/0f молчат, common не задвоен (UNHANDLED-пропагация жива);
- троттлинг 0e НЕ блокирует 0f (раздельные CooldownTracker).
"""
import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import Chat, Message, Update, User

from handlers import common as common_mod
from handlers import summary as summary_mod
from handlers import web as web_mod
from handlers import youtube as youtube_mod
from handlers.common import common_router, setup_common
from handlers.summary import setup_summary, summary_observer_router
from handlers.web import setup_web, web_router
from handlers.youtube import setup_youtube, youtube_router
from services import media_group_buffer as mgb_mod
from services.database import DatabaseService
from services.smartmodule_phrases import THROTTLE_PHRASES
from services.summary_aliases import AliasResolver

CHAT_ID = -1001234567890
YT_URL = "https://youtu.be/dQw4w9WgXcQ"
WEB_URL = "https://habr.com/ru/articles/1"

_ROUTERS = [summary_observer_router, youtube_router, web_router, common_router]


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


@pytest.fixture
def integration_cleanup():
    yield
    for router in _ROUTERS:
        router._parent_router = None
    summary_mod._generator = None
    summary_mod._db = None
    summary_mod._aliases = None
    summary_mod._bot_id = None
    youtube_mod._service = None
    youtube_mod._cooldown._last.clear()
    web_mod._service = None
    web_mod._cooldown._last.clear()
    common_mod._relay = None
    mgb_mod._buffer.clear()


@pytest.fixture
def env(db, integration_cleanup):
    """Dispatcher: 0a observer + 0e youtube + 0f web + 4c common."""
    for router in _ROUTERS:
        router._parent_router = None

    dp = Dispatcher()
    dp.include_router(summary_observer_router)   # 0a
    dp.include_router(youtube_router)            # 0e
    dp.include_router(web_router)                # 0f
    dp.include_router(common_router)             # 4c

    relay = MagicMock()
    relay.send_common = AsyncMock()
    setup_common(relay)
    setup_summary(None, db, AliasResolver(""), bot_id=None)

    youtube_service = MagicMock()
    youtube_service.summarize = AsyncMock(return_value="выжимка видоса")
    setup_youtube(youtube_service)

    web_service = MagicMock()
    web_service.summarize = AsyncMock(return_value="выжимка статьи")
    setup_web(web_service)

    bot = AsyncMock()
    bot.send_message = AsyncMock()

    yield dp, bot, db, relay, youtube_service, web_service


def _make_message(user_id, text, message_id=1, reply_to_message=None):
    return Message(
        message_id=message_id,
        date=datetime.datetime.now(),
        chat=Chat(id=CHAT_ID, type="group"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
        reply_to_message=reply_to_message,
    )


class TestRouterIsolation:
    @pytest.mark.asyncio
    async def test_youtube_consumes_before_common(self, env):
        """YT-URL + YT-триггер → ровно 1 ответ от 0e; common не срабатывает."""
        dp, bot, db, relay, youtube_service, web_service = env
        message = _make_message(1, f"{YT_URL} че за видос", message_id=11)
        await dp.feed_update(bot, Update(update_id=1, message=message))

        assert bot.send_message.await_count == 1
        sent = bot.send_message.await_args
        assert sent.args[1] == "выжимка видоса"
        assert sent.kwargs["reply_to_message_id"] == 11
        youtube_service.summarize.assert_awaited_once()
        assert youtube_service.summarize.await_args.args[0] == "dQw4w9WgXcQ"
        assert "on_retry" in youtube_service.summarize.await_args.kwargs
        web_service.summarize.assert_not_awaited()
        relay.send_common.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_web_consumes_before_common(self, env):
        """Веб-URL + web-триггер → ровно 1 ответ от 0f."""
        dp, bot, db, relay, youtube_service, web_service = env
        message = _make_message(1, f"{WEB_URL} выжимка", message_id=11)
        await dp.feed_update(bot, Update(update_id=2, message=message))

        assert bot.send_message.await_count == 1
        sent = bot.send_message.await_args
        assert sent.args[1] == "выжимка статьи"
        assert sent.kwargs["reply_to_message_id"] == 11
        web_service.summarize.assert_awaited_once_with(WEB_URL)
        youtube_service.summarize.assert_not_awaited()
        relay.send_common.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_youtube_reply_targets_replied_message(self, env):
        """Сценарий А через полный Dispatcher: reply на ЦЕЛЕВОЕ сообщение."""
        dp, bot, db, relay, youtube_service, web_service = env
        target = _make_message(2, f"видос {YT_URL}", message_id=77)
        message = _make_message(1, "поясни за видос", message_id=11,
                                reply_to_message=target)
        await dp.feed_update(bot, Update(update_id=3, message=message))

        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 77

    @pytest.mark.asyncio
    async def test_url_without_trigger_unhandled_propagation_alive(self, env):
        """URL без триггера → 0e/0f молчат (UNHANDLED), common не задвоен."""
        dp, bot, db, relay, youtube_service, web_service = env
        message = _make_message(1, f"просто скинул {WEB_URL}", message_id=11)
        await dp.feed_update(bot, Update(update_id=4, message=message))

        bot.send_message.assert_not_awaited()
        youtube_service.summarize.assert_not_awaited()
        web_service.summarize.assert_not_awaited()
        relay.send_common.assert_not_awaited()
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert any(r["text"] == f"просто скинул {WEB_URL}" for r in rows)

    @pytest.mark.asyncio
    async def test_youtube_throttle_does_not_block_web(self, env):
        """Раздельные CooldownTracker: троттлинг 0e НЕ блокирует 0f."""
        dp, bot, db, relay, youtube_service, web_service = env
        first_yt = _make_message(1, f"{YT_URL} че за видос", message_id=11)
        await dp.feed_update(bot, Update(update_id=5, message=first_yt))
        assert youtube_service.summarize.await_count == 1

        web_message = _make_message(1, f"{WEB_URL} выжимка", message_id=12)
        await dp.feed_update(bot, Update(update_id=6, message=web_message))

        assert web_service.summarize.await_count == 1   # web НЕ затроттлен
        assert youtube_service.summarize.await_count == 1
        sent_texts = [c.args[1] for c in bot.send_message.await_args_list]
        assert "выжимка статьи" in sent_texts
        assert not any(
            any(candidate.split("{")[0] in t for candidate in THROTTLE_PHRASES)
            for t in sent_texts
        )

    @pytest.mark.asyncio
    async def test_web_after_youtube_throttle_in_same_handler(self, env):
        """Повторный YT-триггер → 5.1 (на вызов), а web продолжает работать."""
        dp, bot, db, relay, youtube_service, web_service = env
        first_yt = _make_message(1, f"{YT_URL} че за видос", message_id=11)
        await dp.feed_update(bot, Update(update_id=7, message=first_yt))

        second_yt = _make_message(1, f"{YT_URL} че за видос", message_id=22)
        await dp.feed_update(bot, Update(update_id=8, message=second_yt))

        assert youtube_service.summarize.await_count == 1  # сервис НЕ вызван 2-й раз
        throttle_reply = bot.send_message.await_args
        assert throttle_reply.kwargs["reply_to_message_id"] == 22   # 5.1 → на ВЫЗОВ
        assert any(
            throttle_reply.args[1].startswith(candidate.split("{remaining_time}")[0])
            for candidate in THROTTLE_PHRASES
        )

    @pytest.mark.asyncio
    async def test_danger_word_still_reaches_common(self, env):
        """Danger-слово (не-триггер для 0e/0f) доходит до common 4c как раньше."""
        dp, bot, db, relay, youtube_service, web_service = env
        message = _make_message(1, "слышал хлопок в небе", message_id=11)
        await dp.feed_update(bot, Update(update_id=9, message=message))

        relay.send_common.assert_awaited_once()
        assert relay.send_common.await_args.kwargs["subdir"] == "danger"
        youtube_service.summarize.assert_not_awaited()
        web_service.summarize.assert_not_awaited()
