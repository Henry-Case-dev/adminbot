"""PEMsoc: одно сообщение = одна реакция (25.10.2026).

Покрывает claim по message_id, media_group_id и origin поста, а также
связку war_alert → slavik (раньше war отдавал UNHANDLED и slavik дублировал
«пошёл нахуй»).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Chat, MessageOriginChannel

from handlers import slavik as slavik_mod
from handlers.common import otboy_handler, setup_common
from handlers.slavik import kucha_handler, slavik_catchall_handler
from handlers.war_alert import (
    WAR_REPLIES,
    war_channel_repost_handler,
    war_keyword_handler,
)
from services.common_relay import CommonRelay
from services.message_counter import MessageCounterMiddleware
from services.pemsoc_reactions import claim_reaction, release_claim

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


# ── «пошёл нахуй» — гарантированный дефолт при сбое другой реакции ──────────

def test_release_claim_allows_new_reaction():
    msg = _message()
    assert claim_reaction(msg) is True
    release_claim(msg)
    assert claim_reaction(msg) is True


@pytest.mark.asyncio
async def test_war_send_failure_falls_back_to_default():
    msg = _message(message_id=1, text="ракетная опасность")
    msg.reply = AsyncMock(side_effect=RuntimeError("boom"))
    result = await war_keyword_handler(msg)
    assert result is UNHANDLED
    msg.reply = AsyncMock()
    await slavik_catchall_handler(msg)
    assert msg.reply.call_count == 1
    assert msg.reply.call_args[0][0] == "пошёл нахуй"


@pytest.mark.asyncio
async def test_kucha_send_failure_falls_back_to_default(monkeypatch):
    cfg = SimpleNamespace(
        KUCHA_ENABLED=True,
        SLAVIK_USER_ID=SLAVIK_ID,
        SLAVIC_PHOTO_INTERVAL=0,
        SLAVIC_PHOTO_PATH="",
        SLAVIK_MIMIC_MIN_WORDS=5,
        SLAVIK_MIMIC_COOLDOWN=0.0,
        MIMIC_FORWARDS_ENABLED=False,
        DEAD_PAGE_SOURCE_CHANNEL_USERNAME="d_pages",
        DEAD_PAGE_SOURCE_CHANNEL_ID=0,
    )
    monkeypatch.setattr(slavik_mod, "settings", cfg)
    monkeypatch.setattr(
        "services.hot_config.get",
        lambda key, default=None: True if key == "reactions.kucha_enabled"
        else default,
    )
    msg = _message(message_id=1, text="КУЧА денег")
    msg.reply = AsyncMock(side_effect=RuntimeError("boom"))
    result = await kucha_handler(msg)
    assert result is UNHANDLED
    msg.reply = AsyncMock()
    await slavik_catchall_handler(msg)
    assert msg.reply.call_args[0][0] == "пошёл нахуй"


@pytest.mark.asyncio
async def test_gif_send_failure_falls_back_to_default(monkeypatch):
    monkeypatch.setattr("services.message_counter.Path.is_file",
                        lambda self: True)
    middleware = MessageCounterMiddleware(MagicMock())
    middleware.gif_path = "test.gif"
    msg = _message(message_id=1)
    msg.answer_animation = AsyncMock(side_effect=RuntimeError("boom"))
    assert await middleware._send_gif(msg, CHAT_ID, 1) is False
    await slavik_catchall_handler(msg)
    assert msg.reply.call_count == 1
    assert msg.reply.call_args[0][0] == "пошёл нахуй"


@pytest.mark.asyncio
async def test_gif_success_blocks_default(monkeypatch):
    monkeypatch.setattr("services.message_counter.Path.is_file",
                        lambda self: True)
    middleware = MessageCounterMiddleware(MagicMock())
    middleware.gif_path = "test.gif"
    msg = _message(message_id=1)
    msg.answer_animation = AsyncMock()
    assert await middleware._send_gif(msg, CHAT_ID, 1) is True
    await slavik_catchall_handler(msg)
    msg.reply.assert_not_called()


@pytest.mark.asyncio
async def test_common_skip_falls_back_to_default():
    """send_common вернул False (кулдаун/тумблер/пусто) → дефолт, не тишина."""
    mock_relay = MagicMock()
    mock_relay.send_common = AsyncMock(return_value=False)
    setup_common(mock_relay)
    msg = _message(message_id=1, text="отбой")
    result = await otboy_handler(msg, matched_word="отбой")
    assert result is UNHANDLED
    await slavik_catchall_handler(msg)
    assert msg.reply.call_count == 1
    assert msg.reply.call_args[0][0] == "пошёл нахуй"


@pytest.mark.asyncio
async def test_common_relay_disabled_returns_false(monkeypatch):
    relay = CommonRelay(MagicMock(), cooldown_seconds=0,
                        media_base="/fake/media")
    monkeypatch.setattr(
        "services.common_relay.hot.get",
        lambda key, default=None: False if key == "flags.common_media_enabled"
        else default,
    )
    assert await relay.send_common(1, 2, "отбой", "otboy") is False


@pytest.mark.asyncio
async def test_common_relay_cooldown_returns_false(monkeypatch):
    relay = CommonRelay(MagicMock(), cooldown_seconds=60,
                        media_base="/fake/media")
    monkeypatch.setattr(
        "services.common_relay.hot.get",
        lambda key, default=None: True if key == "flags.common_media_enabled"
        else default,
    )
    monkeypatch.setattr(
        relay, "_scan_directory",
        lambda subdir: [(Path("/fake/media/photo.jpg"), "photo")],
    )
    monkeypatch.setattr(relay, "_send_by_type", AsyncMock())
    assert await relay.send_common(1, 2, "устал", "work") is True
    assert await relay.send_common(1, 3, "устал", "work") is False
