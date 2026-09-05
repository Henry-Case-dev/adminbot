"""Раунд 7 (chat-lore-management-v2, T-784, H2.2) — тесты lifecycle чатов.

handlers/chat_lifecycle.py (D1/D2): my_chat_member ТОЛЬКО по событиям самого
бота (узкий фильтр user.id == bot.id; чужие → UNHANDLED — Group Privacy),
вход → ensure_profile + is_active=true, выход/kick → is_active=false;
migrate_to_chat_id → add_link + migrate_profile (Q9-merge). Fail-open: ошибки
store — WARNING, апдейт consumed.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

import handlers.chat_lifecycle as lifecycle

BOT_ID = 12345
CHAT_ID = -1002661910336


@pytest.fixture(autouse=True)
def _lifecycle_store():
    """Мок-store + bot_id в модульных глобалах (прецедент slava_presence)."""
    store = AsyncMock()
    with patch.object(lifecycle, "_store", store), \
            patch.object(lifecycle, "_bot_id", BOT_ID):
        yield store


def _make_event(user_id: int, old_status: str, new_status: str,
                chat_id: int = CHAT_ID):
    """Событие chat_member с указанными статусами (как tests/conftest)."""
    event = MagicMock()
    event.chat = MagicMock()
    event.chat.id = chat_id
    event.bot = AsyncMock()
    event.old_chat_member = MagicMock()
    event.old_chat_member.status = old_status
    event.old_chat_member.user = MagicMock()
    event.old_chat_member.user.id = user_id
    event.new_chat_member = MagicMock()
    event.new_chat_member.status = new_status
    event.new_chat_member.user = MagicMock()
    event.new_chat_member.user.id = user_id
    return event


class TestBotJoin:
    @pytest.mark.asyncio
    async def test_bot_join_ensures_and_activates(self, _lifecycle_store):
        event = _make_event(BOT_ID, "left", "member")
        result = await lifecycle.on_bot_joined(event)
        assert result is None                     # consumed
        _lifecycle_store.upsert_profile_on_join.assert_awaited_once_with(
            CHAT_ID)
        _lifecycle_store.set_active.assert_awaited_once_with(CHAT_ID, True)

    @pytest.mark.asyncio
    async def test_bot_join_as_administrator_activates(self, _lifecycle_store):
        event = _make_event(BOT_ID, "left", "administrator")
        result = await lifecycle.on_bot_joined(event)
        assert result is None
        _lifecycle_store.upsert_profile_on_join.assert_awaited_once_with(
            CHAT_ID)
        _lifecycle_store.set_active.assert_awaited_once_with(CHAT_ID, True)

    @pytest.mark.asyncio
    async def test_other_user_join_unhandled(self, _lifecycle_store):
        event = _make_event(99999, "left", "member")
        result = await lifecycle.on_bot_joined(event)
        assert result is UNHANDLED
        _lifecycle_store.upsert_profile_on_join.assert_not_awaited()
        _lifecycle_store.set_active.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_store_error_fail_open_consumed(self, _lifecycle_store):
        _lifecycle_store.set_active.side_effect = RuntimeError("pg down")
        event = _make_event(BOT_ID, "left", "member")
        result = await lifecycle.on_bot_joined(event)
        assert result is None                     # апдейт не роняет бот


class TestBotLeave:
    @pytest.mark.asyncio
    async def test_bot_kicked_deactivates(self, _lifecycle_store):
        event = _make_event(BOT_ID, "member", "kicked")
        result = await lifecycle.on_bot_left(event)
        assert result is None
        _lifecycle_store.set_active.assert_awaited_once_with(CHAT_ID, False)

    @pytest.mark.asyncio
    async def test_bot_left_deactivates(self, _lifecycle_store):
        event = _make_event(BOT_ID, "administrator", "left")
        result = await lifecycle.on_bot_left(event)
        assert result is None
        _lifecycle_store.set_active.assert_awaited_once_with(CHAT_ID, False)

    @pytest.mark.asyncio
    async def test_other_user_leave_unhandled(self, _lifecycle_store):
        event = _make_event(99999, "member", "left")
        result = await lifecycle.on_bot_left(event)
        assert result is UNHANDLED
        _lifecycle_store.set_active.assert_not_awaited()


class TestMigrate:
    def _migrate_message(self, old_id: int = -100111,
                         new_id: int = -100222):
        msg = MagicMock()
        msg.chat = MagicMock()
        msg.chat.id = old_id
        msg.migrate_to_chat_id = new_id
        msg.message_id = 555
        return msg

    @pytest.mark.asyncio
    async def test_migrate_writes_link_and_moves_profile(self,
                                                         _lifecycle_store):
        msg = self._migrate_message()
        result = await lifecycle.on_chat_migrated(msg)
        assert result is None
        _lifecycle_store.add_link.assert_awaited_once_with(-100111, -100222)
        _lifecycle_store.migrate_profile.assert_awaited_once_with(
            old_chat_id=-100111, new_chat_id=-100222, changed_by=None)

    @pytest.mark.asyncio
    async def test_migrate_fail_open_consumed(self, _lifecycle_store):
        _lifecycle_store.migrate_profile.side_effect = RuntimeError("boom")
        msg = self._migrate_message()
        result = await lifecycle.on_chat_migrated(msg)
        assert result is None                     # апдейт consumed, бот жив
        _lifecycle_store.add_link.assert_awaited_once_with(-100111, -100222)

    @pytest.mark.asyncio
    async def test_setup_chat_lifecycle_injects(self):
        store = MagicMock()
        lifecycle.setup_chat_lifecycle(store, bot_id=777)
        assert lifecycle._store is store
        assert lifecycle._bot_id == 777
        lifecycle.setup_chat_lifecycle(None, None)   # сброс для других тестов
