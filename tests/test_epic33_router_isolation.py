"""Tests for Epic 33 router isolation (T-257-E, Section 42.10).

Один aiogram Dispatcher: summary_observer_router (0a) + factcheck_router (0c) +
search_router (0d) + common_router (4c). Прогон через Dispatcher.feed_update:
- «найди ракету» → ровно 1 ответ, от search (danger/common НЕ срабатывает);
- reply «фактчек …» на целевое → ровно 1 ответ от factcheck, reply_to_message_id
  == target.message_id;
- обычное сообщение → поиск/фактчек молчат, observer 0a сохраняет в память;
- danger-слово → common 4c по-прежнему работает (консьюма на 0c/0d нет для
  не-триггеров, UNHANDLED-пропагация жива).
"""
import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.types import Chat, Message, PhotoSize, Update, User

from handlers import common as common_mod
from handlers import factcheck as factcheck_mod
from handlers import search as search_mod
from handlers import summary as summary_mod
from handlers.common import common_router, setup_common
from handlers.factcheck import factcheck_router, setup_factcheck
from handlers.search import search_router, setup_search
from handlers.summary import setup_summary, summary_observer_router
from services import media_group_buffer as mgb_mod
from services.database import DatabaseService
from services.smartmodule_phrases import FACTCHECK_EMPTY_CONTEXT_PHRASES
from services.summary_aliases import AliasResolver

CHAT_ID = -1001234567890

_ROUTERS = [summary_observer_router, factcheck_router, search_router, common_router]


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
    factcheck_mod._service = None
    factcheck_mod._cooldown._last.clear()
    search_mod._service = None
    search_mod._cooldown._last.clear()
    common_mod._relay = None
    mgb_mod._buffer.clear()


@pytest.fixture
def env(db, integration_cleanup):
    """Dispatcher: 0a observer + 0c factcheck + 0d search + 4c common."""
    for router in _ROUTERS:
        router._parent_router = None

    dp = Dispatcher()
    dp.include_router(summary_observer_router)   # 0a
    dp.include_router(factcheck_router)          # 0c
    dp.include_router(search_router)             # 0d
    dp.include_router(common_router)             # 4c

    relay = MagicMock()
    relay.send_common = AsyncMock()
    setup_common(relay)
    setup_summary(None, db, AliasResolver(""), bot_id=None)

    search_service = MagicMock()
    search_service.research = AsyncMock(return_value="выжимка про ракету")
    setup_search(search_service)

    factcheck_service = MagicMock()
    factcheck_service.check_claim = AsyncMock(return_value="вердикт: пиздеж")
    setup_factcheck(factcheck_service)

    bot = AsyncMock()
    bot.send_message = AsyncMock()

    yield dp, bot, db, relay, search_service, factcheck_service


def _make_message(user_id, text, message_id=1, reply_to_message=None):
    message = Message(
        message_id=message_id,
        date=datetime.datetime.now(),
        chat=Chat(id=CHAT_ID, type="group"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
        reply_to_message=reply_to_message,
    )
    return message


def _make_photo_message(user_id, caption, message_id, media_group_id):
    """Epic 36: элемент альбома — реальный aiogram Message с photo."""
    photo = [PhotoSize(file_id="f", file_unique_id="u", width=10, height=10)]
    return Message(
        message_id=message_id,
        date=datetime.datetime.now(),
        chat=Chat(id=CHAT_ID, type="group"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"),
        caption=caption,
        media_group_id=media_group_id,
        photo=photo,
    )


class TestRouterIsolation:
    @pytest.mark.asyncio
    async def test_search_consumes_before_common(self, env):
        """«найди ракету» → ровно 1 ответ от search; common/danger не срабатывает."""
        dp, bot, db, relay, search_service, _ = env
        message = _make_message(1, "найди ракету", message_id=11)
        await dp.feed_update(bot, Update(update_id=1, message=message))

        assert bot.send_message.await_count == 1
        sent = bot.send_message.await_args
        assert sent.args[0] == CHAT_ID
        assert sent.args[1] == "выжимка про ракету"
        assert sent.kwargs["reply_to_message_id"] == 11
        search_service.research.assert_awaited_once_with("ракету")
        relay.send_common.assert_not_awaited()   # 4c danger НЕ сработал

    @pytest.mark.asyncio
    async def test_factcheck_reply_targets_target_message(self, env):
        """reply «фактчек …» → ровно 1 ответ от factcheck на ЦЕЛЕВОЕ сообщение."""
        dp, bot, db, relay, _, factcheck_service = env
        target = _make_message(2, "Земля плоская", message_id=77)
        message = _make_message(1, "фактчек это правда?", message_id=11,
                                reply_to_message=target)
        await dp.feed_update(bot, Update(update_id=2, message=message))

        assert bot.send_message.await_count == 1
        sent = bot.send_message.await_args
        assert sent.args[1] == "вердикт: пиздеж"
        assert sent.kwargs["reply_to_message_id"] == 77   # target.message_id
        factcheck_service.check_claim.assert_awaited_once_with(
            "Земля плоская", "это правда?", None
        )
        relay.send_common.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ordinary_message_observer_saves_and_no_answers(self, env):
        """Не-триггер: поиск/фактчек молчат (UNHANDLED), observer 0a записал в память."""
        dp, bot, db, relay, search_service, factcheck_service = env
        message = _make_message(1, "привет народ", message_id=11)
        await dp.feed_update(bot, Update(update_id=3, message=message))

        bot.send_message.assert_not_awaited()
        search_service.research.assert_not_awaited()
        factcheck_service.check_claim.assert_not_awaited()
        relay.send_common.assert_not_awaited()
        rows = await db.get_smart_window(CHAT_ID, 0, 10)
        assert any(r["text"] == "привет народ" for r in rows)

    @pytest.mark.asyncio
    async def test_danger_word_still_reaches_common(self, env):
        """Danger-слово (не-триггер для 0c/0d) доходит до common 4c как раньше."""
        dp, bot, db, relay, search_service, factcheck_service = env
        message = _make_message(1, "слышал хлопок в небе", message_id=11)
        await dp.feed_update(bot, Update(update_id=4, message=message))

        relay.send_common.assert_awaited_once()
        assert relay.send_common.await_args.kwargs["subdir"] == "danger"
        bot.send_message.assert_not_awaited()     # danger шлёт медиа, не текст
        search_service.research.assert_not_awaited()
        factcheck_service.check_claim.assert_not_awaited()

    # ── Epic 36 (R36-1, Section 45.3 #17-18): альбомы через полный Dispatcher ──

    @pytest.mark.asyncio
    async def test_album_reply_uses_buffered_caption_full_pipeline(self, env):
        """#17: пачка альбома из 3 фото (caption на 1-м) → reply «фактчек» на 3-е
        → ровно 1 ответ, check_claim с caption, reply_to_message_id == 3-го фото."""
        dp, bot, db, relay, _, factcheck_service = env
        await dp.feed_update(bot, Update(update_id=10, message=_make_photo_message(
            2, "текст новости", message_id=70, media_group_id="album-1")))
        await dp.feed_update(bot, Update(update_id=11, message=_make_photo_message(
            2, None, message_id=71, media_group_id="album-1")))
        await dp.feed_update(bot, Update(update_id=12, message=_make_photo_message(
            2, None, message_id=72, media_group_id="album-1")))

        third = _make_photo_message(2, None, message_id=72, media_group_id="album-1")
        reply_msg = _make_message(1, "фактчек", message_id=80, reply_to_message=third)
        await dp.feed_update(bot, Update(update_id=13, message=reply_msg))

        assert bot.send_message.await_count == 1          # ровно 1 ответ
        sent = bot.send_message.await_args
        assert sent.args[1] == "вердикт: пиздеж"
        assert sent.kwargs["reply_to_message_id"] == 72   # target = 3-е фото
        factcheck_service.check_claim.assert_awaited_once_with(
            "текст новости", None, None
        )
        relay.send_common.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_album_without_caption_goes_empty_context_full_pipeline(self, env):
        """#18: caption пуст у ВСЕХ элементов → 5.3 (empty-context фраза),
        check_claim не вызван."""
        dp, bot, db, relay, _, factcheck_service = env
        await dp.feed_update(bot, Update(update_id=20, message=_make_photo_message(
            2, None, message_id=70, media_group_id="album-2")))
        await dp.feed_update(bot, Update(update_id=21, message=_make_photo_message(
            2, None, message_id=71, media_group_id="album-2")))

        second = _make_photo_message(2, None, message_id=71, media_group_id="album-2")
        reply_msg = _make_message(1, "фактчек", message_id=81, reply_to_message=second)
        await dp.feed_update(bot, Update(update_id=22, message=reply_msg))

        assert bot.send_message.await_count == 1
        sent = bot.send_message.await_args
        assert sent.args[1] in FACTCHECK_EMPTY_CONTEXT_PHRASES
        assert sent.kwargs["reply_to_message_id"] == 71
        factcheck_service.check_claim.assert_not_called()
