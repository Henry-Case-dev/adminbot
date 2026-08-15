"""Epic 22 / D53 — integration: приветствие > dead page > «пошёл нахуй».

Covers the answer race for Slava:
  - join event → exactly one answer («ДОЛБОЕБ ВЕРНУЛСЯ»), no dead page;
  - Slava's @d_pages repost through Dispatcher → exactly one dead page, no «пошёл нахуй»;
  - non-Slava @d_pages repost → nothing (filter rejects, propagation continues);
  - ordinary Slava message → «пошёл нахуй» as usual (no regression).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from aiogram import Router
from aiogram.types import Chat, ChatMemberLeft, ChatMemberMember
from aiogram.types import ChatMemberUpdated, Message, MessageOriginChannel, User

from config.settings import settings
from handlers.dead_page_trigger import (
    _seen_media_groups,
    dead_page_router,
    setup_dead_page,
)
from handlers.slavik import setup_slavik, slavik_router
from handlers.slava_presence import setup_presence, slava_presence_router
from services.scheduler import SchedulerService

CHAT_ID = -1001234567890


def _make_repost_message(from_user_id, origin_username, origin_chat_id, text="репост"):
    """Real aiogram Message with forward_origin from a channel."""
    user = User(id=from_user_id, is_bot=False, first_name="Test")
    chat = Chat(id=CHAT_ID, type="supergroup")
    origin_chat = Chat(id=origin_chat_id, type="channel", username=origin_username)
    origin = MessageOriginChannel(
        type="channel",
        date=1234567890,
        chat=origin_chat,
        message_id=42,
    )
    return Message(
        message_id=1,
        date=1234567890,
        chat=chat,
        from_user=user,
        forward_origin=origin,
        text=text,
    )


def _make_plain_message(from_user_id, text="привет"):
    """Real aiogram Message without forward_origin."""
    user = User(id=from_user_id, is_bot=False, first_name="Test")
    chat = Chat(id=CHAT_ID, type="supergroup")
    return Message(
        message_id=2,
        date=1234567890,
        chat=chat,
        from_user=user,
        text=text,
    )


class TestSlavikDeadPagePriority:
    """Integration: dead_page_router (4) + slavik_router (5) on one dispatcher."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        dead_page_router._parent_router = None
        slavik_router._parent_router = None
        _seen_media_groups.clear()
        yield

    def _make_parent(self):
        parent = Router(name="test_dispatcher")
        parent.include_router(dead_page_router)
        parent.include_router(slavik_router)
        return parent

    @pytest.mark.asyncio
    async def test_d_pages_repost_only_dead_page(self, _setup):
        """Slava's @d_pages repost → 1 dead page, no «пошёл нахуй»/mimic."""
        parent = self._make_parent()
        mock_relay = MagicMock()
        mock_relay.send_dead_page = AsyncMock()
        setup_dead_page(mock_relay, MagicMock())
        setup_slavik(None)

        bot_mock = AsyncMock()
        msg = _make_repost_message(settings.SLAVIK_USER_ID, "d_pages", -100999)
        msg._bot = bot_mock

        await parent.propagate_event(update_type="message", event=msg, bot=bot_mock)

        mock_relay.send_dead_page.assert_called_once_with(CHAT_ID, slot="repost")
        bot_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_slavik_d_pages_repost_ignored(self, _setup):
        """@d_pages repost from anyone else → filter rejects, nothing is sent."""
        parent = self._make_parent()
        mock_relay = MagicMock()
        mock_relay.send_dead_page = AsyncMock()
        setup_dead_page(mock_relay, MagicMock())
        setup_slavik(None)

        bot_mock = AsyncMock()
        msg = _make_repost_message(111, "d_pages", -100999)
        msg._bot = bot_mock

        await parent.propagate_event(update_type="message", event=msg, bot=bot_mock)

        mock_relay.send_dead_page.assert_not_called()
        bot_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_ordinary_slava_message_poshel_nahui(self, _setup):
        """Ordinary Slava message → exactly one «пошёл нахуй» (no regression)."""
        parent = self._make_parent()
        mock_relay = MagicMock()
        mock_relay.send_dead_page = AsyncMock()
        setup_dead_page(mock_relay, MagicMock())
        setup_slavik(None)

        bot_mock = AsyncMock()
        msg = _make_plain_message(settings.SLAVIK_USER_ID, text="привет как дела")
        msg._bot = bot_mock

        await parent.propagate_event(update_type="message", event=msg, bot=bot_mock)

        mock_relay.send_dead_page.assert_not_called()
        # aiogram 3.29: message.reply() executes via bot(SendMessage) request
        assert bot_mock.call_count == 1
        request = bot_mock.call_args.args[0]
        assert request.chat_id == CHAT_ID
        assert request.text == "пошёл нахуй"


class TestSlavikJoinPriority:
    """Integration: join event → greeting only (DEAD_PAGE_POST_ON_JOIN=False)."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        slava_presence_router._parent_router = None
        yield

    @pytest.mark.asyncio
    async def test_join_sends_greeting_only(self, _setup):
        parent = Router(name="test_dispatcher")
        parent.include_router(slava_presence_router)

        mock_db = MagicMock()
        mock_db.set_presence = AsyncMock()
        mock_relay = MagicMock()
        mock_relay.send_dead_page = AsyncMock()
        scheduler = SchedulerService(relay=mock_relay, post_on_join=False)
        setup_presence(mock_db, scheduler)

        user = User(id=settings.SLAVIK_USER_ID, is_bot=False, first_name="Slava")
        chat = Chat(id=CHAT_ID, type="group")
        old_cm = ChatMemberLeft(user=user, status="left")
        new_cm = ChatMemberMember(user=user, status="member")
        event = ChatMemberUpdated(
            update_id=1,
            chat=chat,
            from_user=user,
            date=0,
            old_chat_member=old_cm,
            new_chat_member=new_cm,
        )
        bot_mock = AsyncMock()
        bot_mock.send_message = AsyncMock()
        event._bot = bot_mock

        await parent.propagate_event(update_type="chat_member", event=event, bot=bot_mock)

        bot_mock.send_message.assert_called_once()
        assert bot_mock.send_message.call_args.kwargs["text"] == "ДОЛБОЕБ ВЕРНУЛСЯ"
        mock_relay.send_dead_page.assert_not_called()
