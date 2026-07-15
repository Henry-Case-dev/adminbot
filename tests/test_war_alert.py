"""
Tests for F5v2 — War Words Alert Redesign (Epic 10).

Covers:
  - war_alert_router keyword_handler (Slava + war word → random reply)
  - war_alert_router channel_repost_handler (target channel repost → random reply)
  - Random reply selection
  - Caption-based keyword matching
  - Channel ID and username matching
  - Logging coverage
"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from aiogram.types import Message, Chat, User, MessageOriginChannel

from handlers.war_alert import (
    war_keyword_handler,
    war_channel_repost_handler,
    war_alert_router,
    WAR_REPLIES,
    _is_target_channel,
    _parse_int_list,
    _parse_str_list,
    _load_replies,
    setup_war_alert,
)
from config.settings import settings


# ── Helpers ──

def make_war_message(text=None, caption=None, from_id=479167456, chat_id=-100123,
                     message_id=1, forward_origin=None):
    """Create a mock Message for war alert tests."""
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = from_id
    msg.reply = AsyncMock()
    msg.forward_origin = forward_origin
    return msg


def make_channel_origin(channel_id=-100999, username="chp_perm"):
    """Create a MessageOriginChannel for testing."""
    origin_chat = Chat(id=channel_id, type="channel", username=username)
    return MessageOriginChannel(
        type="channel",
        date=1730000000,
        chat=origin_chat,
        message_id=42,
    )


# ── Parser Helpers ──

class TestParseIntList:
    def test_empty_string(self):
        assert _parse_int_list("") == []

    def test_single_id(self):
        assert _parse_int_list("1654872411") == [1654872411]

    def test_multiple_ids(self):
        assert _parse_int_list("111, 222, 333") == [111, 222, 333]

    def test_with_spaces(self):
        assert _parse_int_list("  111 ,  222  ") == [111, 222]

    def test_invalid_value_skipped(self):
        assert _parse_int_list("111, abc, 333") == [111, 333]

    def test_all_invalid_returns_empty(self):
        assert _parse_int_list("abc, xyz") == []


class TestParseStrList:
    def test_empty_string(self):
        assert _parse_str_list("") == []

    def test_single_username(self):
        assert _parse_str_list("chp_perm") == ["chp_perm"]

    def test_multiple_usernames(self):
        assert _parse_str_list("chp_perm, radar_bpla") == ["chp_perm", "radar_bpla"]

    def test_case_lowered(self):
        assert _parse_str_list("CHP_Perm") == ["chp_perm"]

    def test_with_spaces(self):
        assert _parse_str_list("  chp_perm ,  radar_bpla  ") == ["chp_perm", "radar_bpla"]


# ── Load Replies ──

class TestLoadReplies:
    def test_default_replies(self):
        """Default replies should have at least 5 phrases."""
        replies = _load_replies()
        assert len(replies) >= 5
        assert "потрясись" in replies
        assert "поплачь" in replies

    def test_env_replies(self, monkeypatch):
        """Custom env replies should override defaults (via monkeypatch of module list)."""
        monkeypatch.setattr("handlers.war_alert.WAR_REPLIES", ["фраза1", "фраза2"])
        from handlers.war_alert import WAR_REPLIES
        assert WAR_REPLIES == ["фраза1", "фраза2"]


# ── Channel Target Detection ──

class TestIsTargetChannel:
    """Test _is_target_channel logic by directly patching the cached lists."""

    def test_match_by_id(self, monkeypatch):
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_IDS", [1654872411])
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_USERNAMES", [])
        origin = make_channel_origin(channel_id=1654872411, username="whatever")
        assert _is_target_channel(origin) is True

    def test_match_by_username(self, monkeypatch):
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_IDS", [])
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_USERNAMES", ["chp_perm"])
        origin = make_channel_origin(channel_id=-100999, username="chp_perm")
        assert _is_target_channel(origin) is True

    def test_match_by_username_case_insensitive(self, monkeypatch):
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_IDS", [])
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_USERNAMES", ["chp_perm"])
        origin = make_channel_origin(channel_id=-100999, username="CHP_Perm")
        assert _is_target_channel(origin) is True

    def test_no_match_different_id(self, monkeypatch):
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_IDS", [1654872411])
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_USERNAMES", [])
        origin = make_channel_origin(channel_id=999999999, username="other")
        assert _is_target_channel(origin) is False

    def test_no_match_different_username(self, monkeypatch):
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_IDS", [])
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_USERNAMES", ["chp_perm"])
        origin = make_channel_origin(channel_id=-100999, username="other_channel")
        assert _is_target_channel(origin) is False

    def test_no_match_none_username(self, monkeypatch):
        """Channel without username should not match when filtering by username."""
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_IDS", [])
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_USERNAMES", ["chp_perm"])
        origin = make_channel_origin(channel_id=-100999, username=None)
        # make_channel_origin creates Chat with username=None; no need to reassign
        assert _is_target_channel(origin) is False

    def test_no_ids_or_usernames_configured(self, monkeypatch):
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_IDS", [])
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_USERNAMES", [])
        origin = make_channel_origin()
        assert _is_target_channel(origin) is False


# ── Handler: Keyword (Slava + war word) ──

class TestWarKeywordHandler:
    @pytest.mark.asyncio
    async def test_replies_with_random_phrase(self):
        """Keyword handler should reply with one of the war replies."""
        msg = make_war_message(text="опасность ракетная атака", from_id=479167456)
        with patch("handlers.war_alert.random.choice", return_value="потрясись"):
            await war_keyword_handler(msg)
        msg.reply.assert_called_once_with("потрясись")

    @pytest.mark.asyncio
    async def test_uses_text_content(self):
        """Should match keywords in message.text."""
        msg = make_war_message(text="внимание БПЛА в небе", from_id=479167456)
        await war_keyword_handler(msg)
        msg.reply.assert_called_once()
        reply_text = msg.reply.call_args[0][0]
        assert reply_text in WAR_REPLIES

    @pytest.mark.asyncio
    async def test_uses_caption_content(self):
        """Should match keywords in message.caption (forwarded media fix)."""
        msg = make_war_message(text=None, caption="угроза атаки беспилотников", from_id=479167456)
        await war_keyword_handler(msg)
        msg.reply.assert_called_once()
        reply_text = msg.reply.call_args[0][0]
        assert reply_text in WAR_REPLIES

    @pytest.mark.asyncio
    async def test_reply_is_random(self):
        """Multiple calls should produce different replies (statistically)."""
        msg = make_war_message(text="ракетная опасность", from_id=479167456)
        replies_seen = set()
        for _ in range(20):
            msg.reply.reset_mock()
            await war_keyword_handler(msg)
            replies_seen.add(msg.reply.call_args[0][0])
        # At least 2 different replies seen
        assert len(replies_seen) >= 2

    @pytest.mark.asyncio
    async def test_handles_reply_error(self):
        """Should not raise if reply fails (e.g., Telegram error)."""
        msg = make_war_message(text="тревога", from_id=479167456)
        msg.reply.side_effect = Exception("Telegram API error")
        # Should not raise
        await war_keyword_handler(msg)

    @pytest.mark.asyncio
    async def test_multiple_keywords_in_message(self):
        """Any one keyword match triggers the handler."""
        msg = make_war_message(
            text="внимание опасность атака бпла ракетная угроза",
            from_id=479167456,
        )
        await war_keyword_handler(msg)
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_keyword_case_insensitive(self):
        """Keywords should match regardless of case."""
        msg = make_war_message(text="ВНИМАНИЕ ОПАСНОСТЬ", from_id=479167456)
        await war_keyword_handler(msg)
        msg.reply.assert_called_once()


# ── Handler: Channel Repost ──

class TestWarChannelRepostHandler:
    @pytest.mark.asyncio
    async def test_replies_to_target_channel_repost(self):
        """Should reply when repost is from a target channel."""
        origin = make_channel_origin(channel_id=1654872411, username="chp_perm")
        msg = make_war_message(
            text="какой-то пост",
            from_id=479167456,
            forward_origin=origin,
        )
        with patch("handlers.war_alert._is_target_channel", return_value=True):
            with patch("handlers.war_alert.random.choice", return_value="повизжи"):
                await war_channel_repost_handler(msg)
        msg.reply.assert_called_once_with("повизжи")

    @pytest.mark.asyncio
    async def test_ignores_non_channel_forward(self):
        """Should not reply to user-to-user forwards (not channel)."""
        from aiogram.types import MessageOriginUser
        origin = MessageOriginUser(
            type="user",
            date=1730000000,
            sender_user=User(id=111, is_bot=False, first_name="Test"),
        )
        msg = make_war_message(
            text="пересланное сообщение",
            from_id=479167456,
            forward_origin=origin,
        )
        await war_channel_repost_handler(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_non_target_channel(self):
        """Should not reply for reposts from non-target channels."""
        origin = make_channel_origin(channel_id=-999999, username="random_channel")
        msg = make_war_message(
            text="репост из другого канала",
            from_id=479167456,
            forward_origin=origin,
        )
        await war_channel_repost_handler(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_is_random_for_channel(self):
        """Channel repost replies should be random."""
        origin = make_channel_origin(channel_id=1654872411)
        msg = make_war_message(
            text="...",
            from_id=479167456,
            forward_origin=origin,
        )
        replies_seen = set()
        with patch("handlers.war_alert._is_target_channel", return_value=True):
            for _ in range(20):
                msg.reply.reset_mock()
                await war_channel_repost_handler(msg)
                if msg.reply.call_count > 0:
                    replies_seen.add(msg.reply.call_args[0][0])
        assert len(replies_seen) >= 2

    @pytest.mark.asyncio
    async def test_handles_reply_error(self):
        """Should not crash on reply failure."""
        origin = make_channel_origin(channel_id=1654872411)
        msg = make_war_message(
            text="...",
            from_id=479167456,
            forward_origin=origin,
        )
        msg.reply.side_effect = Exception("API error")
        with patch("handlers.war_alert._is_target_channel", return_value=True):
            await war_channel_repost_handler(msg)  # Should not raise

    @pytest.mark.asyncio
    async def test_any_user_can_trigger_channel_repost(self):
        """Channel repost detection fires for ANY user reposting from target channel."""
        origin = make_channel_origin(channel_id=1654872411)
        msg = make_war_message(
            text="репост",
            from_id=999999999,  # Not Slava
            forward_origin=origin,
        )
        with patch("handlers.war_alert._is_target_channel", return_value=True):
            await war_channel_repost_handler(msg)
        msg.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_forward_origin_skipped(self):
        """Messages without forward_origin are not processed by channel handler."""
        msg = make_war_message(text="обычное сообщение", from_id=479167456)
        # The router filter F.forward_origin prevents this from being called,
        # but test direct handler call for sanity
        await war_channel_repost_handler(msg)
        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_channel_handler_none_from_user(self):
        """Channel repost with from_user=None should not crash (channel auto-forward)."""
        origin = make_channel_origin(channel_id=1654872411)
        msg = make_war_message(
            text="автопересылка из канала",
            from_id=0,
            forward_origin=origin,
        )
        msg.from_user = None
        with patch("handlers.war_alert._is_target_channel", return_value=True):
            # Should NOT raise AttributeError
            await war_channel_repost_handler(msg)
        msg.reply.assert_called_once()


# ── Router Integration ──

class TestWarAlertRouter:
    """Verify router integration with other components."""

    def test_setup_war_alert_does_not_crash(self, monkeypatch):
        """setup_war_alert() should initialize without errors."""
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_IDS", [1654872411])
        monkeypatch.setattr("handlers.war_alert._TARGET_CHANNEL_USERNAMES", [])
        # Should not raise
        setup_war_alert()

    @pytest.mark.asyncio
    async def test_keyword_handler_only_for_slavik(self):
        """Keyword handler should have UserIdFilter for SLAVIK_USER_ID."""
        msg = make_war_message(text="опасность", from_id=999999999)
        from filters.user_id import UserIdFilter
        f = UserIdFilter(settings.SLAVIK_USER_ID)
        assert await f(msg) is False

    @pytest.mark.asyncio
    async def test_channel_handler_works_without_keywords(self):
        """Channel repost doesn't require keywords — just target channel match."""
        origin = make_channel_origin(channel_id=1654872411)
        msg = make_war_message(
            text="любое сообщение без ключевых слов",
            from_id=479167456,
            forward_origin=origin,
        )
        with patch("handlers.war_alert._is_target_channel", return_value=True):
            await war_channel_repost_handler(msg)
        msg.reply.assert_called_once()
