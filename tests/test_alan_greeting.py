"""Tests for Alan greeting video (F7).

Tests cover:
  - Alan join via ChatMemberUpdated sends video with @Alan_Z caption
  - Non-Alan join is ignored
  - Alan leave is ignored
  - Alan join via new_chat_members fallback sends video
  - Dedup cooldown prevents double-posting
  - Empty greeting directory handled gracefully
  - Random video selection from multiple files
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.alan_greeting import (
    on_alan_join,
    on_alan_new_member,
    _pick_random_greeting,
    _send_greeting,
    alan_greeting_router,
    _last_greeting,
)


def make_cmu_event(user_id: int, old_status: str = "left", new_status: str = "member",
                   chat_id: int = -1001234567890):
    """Create a mock ChatMemberUpdated event with send_video on the bot."""
    event = MagicMock()
    event.chat = MagicMock()
    event.chat.id = chat_id
    event.bot = AsyncMock()
    event.bot.send_message = AsyncMock()
    event.bot.send_video = AsyncMock()

    event.old_chat_member = MagicMock()
    event.old_chat_member.status = old_status
    event.old_chat_member.user = MagicMock()
    event.old_chat_member.user.id = user_id

    event.new_chat_member = MagicMock()
    event.new_chat_member.status = new_status
    event.new_chat_member.user = MagicMock()
    event.new_chat_member.user.id = user_id

    return event


class TestAlanGreeting:
    @pytest.mark.asyncio
    async def test_alan_join_sends_video(self):
        event = make_cmu_event(138811255, "left", "member")

        with patch("handlers.alan_greeting._last_greeting", {}), \
             patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):
            await on_alan_join(event)

        event.bot.send_video.assert_called_once()
        args, kwargs = event.bot.send_video.call_args
        assert kwargs["chat_id"] == event.chat.id
        assert kwargs["caption"] == "@Alan_Z"
        assert kwargs["video"] is not None

    @pytest.mark.asyncio
    async def test_non_alan_join_ignored(self):
        event = make_cmu_event(99999, "left", "member")

        with patch("handlers.alan_greeting._last_greeting", {}):
            await on_alan_join(event)

        event.bot.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_alan_leave_ignored(self):
        """Alan leave events are filtered by ChatMemberUpdatedFilter —
        the router only subscribes to joins (IS_NOT_MEMBER >> IS_MEMBER),
        not leaves. Verify no leave handler is registered."""
        assert len(alan_greeting_router.chat_member.handlers) == 1

    @pytest.mark.asyncio
    async def test_alan_join_new_chat_members(self):
        msg = MagicMock()
        msg.new_chat_members = [MagicMock()]
        msg.new_chat_members[0].id = 138811255
        msg.chat = MagicMock()
        msg.chat.id = -1001234567890
        msg.bot = AsyncMock()
        msg.bot.send_video = AsyncMock()

        with patch("handlers.alan_greeting._last_greeting", {}), \
             patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):
            await on_alan_new_member(msg)

        msg.bot.send_video.assert_called_once()
        args, kwargs = msg.bot.send_video.call_args
        assert kwargs["caption"] == "@Alan_Z"

    @pytest.mark.asyncio
    async def test_dedup_cooldown(self):
        event = make_cmu_event(138811255, "left", "member")

        greeting_dict = {}
        with patch("handlers.alan_greeting._last_greeting", greeting_dict), \
             patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):
            await on_alan_join(event)
            assert event.bot.send_video.call_count == 1

            event2 = make_cmu_event(138811255, "left", "member", chat_id=event.chat.id)
            event2.bot = event.bot
            await on_alan_join(event2)

        assert event.bot.send_video.call_count == 1

    @pytest.mark.asyncio
    async def test_cooldown_expires(self):
        event = make_cmu_event(138811255, "left", "member")

        greeting_dict = {}
        with patch("handlers.alan_greeting._last_greeting", greeting_dict), \
             patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):
            await on_alan_join(event)
            assert event.bot.send_video.call_count == 1

            greeting_dict[event.chat.id] = time.time() - 15

            event2 = make_cmu_event(138811255, "left", "member", chat_id=event.chat.id)
            event2.bot = event.bot
            await on_alan_join(event2)

        assert event.bot.send_video.call_count == 2

    @pytest.mark.asyncio
    async def test_no_videos_in_directory(self):
        event = make_cmu_event(138811255, "left", "member")

        with patch("handlers.alan_greeting._last_greeting", {}), \
             patch("handlers.alan_greeting._pick_random_greeting", return_value=None):
            await on_alan_join(event)

        event.bot.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_random_video_selection(self):
        videos = ["media/leha_greeting/v1.mp4", "media/leha_greeting/v2.mp4", "media/leha_greeting/v3.mp4"]

        with patch("handlers.alan_greeting.os.path.isdir", return_value=True), \
             patch("handlers.alan_greeting.os.path.isfile", return_value=True), \
             patch("handlers.alan_greeting.glob.glob", return_value=videos):
            seen = set()
            for _ in range(20):
                path = _pick_random_greeting()
                assert path in videos
                seen.add(path)

            assert len(seen) >= 2

    @pytest.mark.asyncio
    async def test_empty_pick_returns_none(self):
        with patch("handlers.alan_greeting.os.path.isdir", return_value=True), \
             patch("handlers.alan_greeting.glob.glob", return_value=["readme.txt", "notes.md"]):
            result = _pick_random_greeting()
            assert result is None

    @pytest.mark.asyncio
    async def test_directory_not_exists(self):
        with patch("handlers.alan_greeting.os.path.isdir", return_value=False):
            result = _pick_random_greeting()
            assert result is None

    @pytest.mark.asyncio
    async def test_send_greeting_no_videos(self):
        bot = AsyncMock()
        with patch("handlers.alan_greeting._pick_random_greeting", return_value=None):
            result = await _send_greeting(bot, -100)
            assert result is False
            bot.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_greeting_success(self):
        bot = AsyncMock()
        bot.send_video = AsyncMock()
        with patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):
            result = await _send_greeting(bot, -100)
            assert result is True
            bot.send_video.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_greeting_error(self):
        bot = AsyncMock()
        bot.send_video = AsyncMock(side_effect=Exception("Network error"))
        with patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):
            result = await _send_greeting(bot, -100)
            assert result is False
            bot.send_video.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_chats_independent_cooldown(self):
        event_a = make_cmu_event(138811255, "left", "member", chat_id=-100)
        event_b = make_cmu_event(138811255, "left", "member", chat_id=-200)

        greeting_dict = {}
        with patch("handlers.alan_greeting._last_greeting", greeting_dict), \
             patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"):
            await on_alan_join(event_a)
            await on_alan_join(event_b)

        assert event_a.bot.send_video.call_count == 1
        assert event_b.bot.send_video.call_count == 1

    @pytest.mark.asyncio
    async def test_new_chat_members_empty_list(self):
        msg = MagicMock()
        msg.new_chat_members = []

        await on_alan_new_member(msg)

        if hasattr(msg, 'bot') and hasattr(msg.bot, 'send_video'):
            msg.bot.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_chat_members_no_alan(self):
        msg = MagicMock()
        other_user = MagicMock()
        other_user.id = 99999
        msg.new_chat_members = [other_user]
        msg.chat = MagicMock()
        msg.chat.id = -100
        msg.bot = AsyncMock()
        msg.bot.send_video = AsyncMock()

        with patch("handlers.alan_greeting._last_greeting", {}):
            await on_alan_new_member(msg)

        msg.bot.send_video.assert_not_called()

    @pytest.mark.asyncio
    async def test_router_has_chat_member_handler(self):
        from aiogram.filters import ChatMemberUpdatedFilter
        assert len(alan_greeting_router.chat_member.handlers) >= 1

    @pytest.mark.asyncio
    async def test_router_has_message_handler(self):
        assert len(alan_greeting_router.message.handlers) >= 1

    @pytest.mark.asyncio
    async def test_both_routers_dispatch_correctly(self):
        """D21: Integration test verifying both routers coexist on one Dispatcher."""
        from aiogram import Dispatcher
        from aiogram.fsm.storage.memory import MemoryStorage
        from handlers.slava_presence import slava_presence_router, setup_presence

        dp = Dispatcher(storage=MemoryStorage())
        dp.include_router(slava_presence_router)
        dp.include_router(alan_greeting_router)

        assert len(slava_presence_router.chat_member.handlers) >= 1
        assert len(alan_greeting_router.chat_member.handlers) >= 1

        slava_handlers = slava_presence_router.chat_member.handlers
        alan_handlers = alan_greeting_router.chat_member.handlers

        for slava_h in slava_handlers:
            assert slava_h.callback is not on_alan_join
        for alan_h in alan_handlers:
            assert alan_h.callback is on_alan_join

        alan_filters = alan_handlers[0].filters if alan_handlers else []
        slava_filters = slava_handlers[0].filters if slava_handlers else []
        assert alan_filters != slava_filters

        mock_db = MagicMock()
        mock_db.set_presence = AsyncMock()
        mock_scheduler = MagicMock()
        mock_scheduler.signal_immediate_post = AsyncMock()
        setup_presence(mock_db, mock_scheduler)

        event = make_cmu_event(138811255, "left", "member")

        with patch("handlers.alan_greeting._last_greeting", {}), \
             patch("handlers.alan_greeting._pick_random_greeting", return_value="media/leha_greeting/test.mp4"), \
             patch.object(event.bot, "send_message", AsyncMock()):
            await on_alan_join(event)

        event.bot.send_video.assert_called_once()
        args, kwargs = event.bot.send_video.call_args
        assert kwargs["caption"] == "@Alan_Z"
        assert kwargs["chat_id"] == event.chat.id
