"""PEMsoc: одно сообщение = одна реакция (25.10.2026).

Покрывает claim по message_id, media_group_id и origin поста, а также
связку war_alert → slavik (раньше war отдавал UNHANDLED и slavik дублировал
«пошёл нахуй»).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, MessageOriginChannel

from handlers import slavik as slavik_mod
from handlers.slavik import slavik_catchall_handler
from handlers.war_alert import (
    WAR_REPLIES,
    war_channel_repost_handler,
    war_keyword_handler,
)
from services.pemsoc_reactions import claim_reaction

CHAT_ID = -1001234567890
SLAVIK_ID = 479167456


def _origin(message_id: int = 42) -> MessageOriginChannel:
    return MessageOriginChannel(
        type="channel",
        date=1730000000,
        chat=Chat(id=-100999, type="channel", username="chp_perm"),
        message_id=message_id,
    )


def _message(
    *,
    message_id: int = 1,
    text: str = "привет",
    user_id: int = SLAVIK_ID,
    media_group_id: str | None = None,
    origin: MessageOriginChannel | None = None,
) -> MagicMock:
    msg = MagicMock()
    msg.message_id = message_id
    msg.text = text
    msg.caption = None
    msg.media_group_id = media_group_id
    msg.forward_origin = origin
    msg.new_chat_members = None
    msg.left_chat_member = None
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.reply = AsyncMock()
    return msg


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(slavik_mod, "_db", None)


# ── claim: ключи и TTL-семантика ────────────────────────────────────────────

def test_same_message_claims_once():
    msg = _message()
    assert claim_reaction(msg) is True
    assert claim_reaction(msg) is False


def test_different_messages_are_independent():
    assert claim_reaction(_message(message_id=1)) is True
    assert claim_reaction(_message(message_id=2)) is True


def test_album_claims_once():
    first = _message(message_id=1, media_group_id="album-1")
    second = _message(message_id=2, media_group_id="album-1")
    assert claim_reaction(first) is True
    assert claim_reaction(second) is False


def test_repeated_repost_of_same_origin_claims_once():
    origin = _origin(42)
    first = _message(message_id=1, origin=origin)
    second = _message(message_id=2, origin=origin)
    assert claim_reaction(first) is True
    assert claim_reaction(second) is False


def test_other_user_same_origin_is_allowed():
    origin = _origin(42)
    assert claim_reaction(_message(message_id=1, user_id=111,
                                   origin=origin)) is True
    assert claim_reaction(_message(message_id=2, user_id=222,
                                   origin=origin)) is True


# ── war_alert → slavik: ровно одна реакция ───────────────────────────────────

@pytest.mark.asyncio
async def test_channel_repost_war_then_slavik_is_one_reply():
    origin = _origin(42)
    msg = _message(message_id=1, origin=origin)
    await war_channel_repost_handler(msg)
    await slavik_catchall_handler(msg)
    assert msg.reply.call_count == 1
    assert msg.reply.call_args[0][0] in WAR_REPLIES


@pytest.mark.asyncio
async def test_war_keyword_then_slavik_is_one_reply():
    msg = _message(message_id=1, text="ракетная опасность")
    await war_keyword_handler(msg)
    await slavik_catchall_handler(msg)
    assert msg.reply.call_count == 1
    assert msg.reply.call_args[0][0] in WAR_REPLIES


@pytest.mark.asyncio
async def test_slavik_twice_is_one_reply():
    msg = _message(message_id=1, text="привет")
    await slavik_catchall_handler(msg)
    await slavik_catchall_handler(msg)
    assert msg.reply.call_count == 1
    assert msg.reply.call_args[0][0] == "пошёл нахуй"


@pytest.mark.asyncio
async def test_album_war_repost_is_one_reply():
    origin1 = _origin(42)
    origin2 = _origin(43)
    first = _message(message_id=1, media_group_id="album-1", origin=origin1)
    second = _message(message_id=2, media_group_id="album-1", origin=origin2)
    await war_channel_repost_handler(first)
    await war_channel_repost_handler(second)
    assert first.reply.call_count == 1
    second.reply.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_repost_same_origin_is_one_reply():
    origin = _origin(42)
    first = _message(message_id=1, origin=origin)
    second = _message(message_id=2, origin=origin)
    await war_channel_repost_handler(first)
    await war_channel_repost_handler(second)
    assert first.reply.call_count == 1
    second.reply.assert_not_called()


@pytest.mark.asyncio
async def test_gif_flag_blocks_war_and_slavik():
    msg = _message(message_id=1, text="ракетная опасность")
    await war_keyword_handler(msg, data={"slavik_gif_sent": True})
    await slavik_catchall_handler(msg, data={"slavik_gif_sent": True})
    msg.reply.assert_not_called()
