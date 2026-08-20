"""Epic 50 (R50-1, D202, Section 58.4): триггеры DirectChat-хендлера.

1) Reply на бота (reply_to_message.from_user.id == bot.id);
2) entities mention (username бота, регистронезависимо) / text_mention (user.id);
3) fallback-текст @username (regex (?i), \b-граница).
Исключения → UNHANDLED: нет DI, само-сообщения бота, команды «/…», пустой текст.

REVISE S1: entities — РЕАЛЬНЫЕ aiogram.types.MessageEntity (в 3.x у entity НЕТ
поля username — юзернейм извлекается через extract_from(text)); text_mention
несёт user (User). MagicMock-атрибутов больше нет — тест ловит регрессию.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import MessageEntity, User

from handlers import direct_chat as dc_mod

BOT_ID = 12345
BOT_USERNAME = "test_bot"
CHAT_ID = -1001234567890


@pytest.fixture
def wire():
    service = MagicMock()
    service.handle = AsyncMock()
    dc_mod.setup_direct_chat(service, BOT_ID, BOT_USERNAME)
    yield service
    dc_mod.setup_direct_chat(None, None, None)


def _mention_entity(text: str, username: str) -> MessageEntity:
    """Реальный MessageEntity(type='mention') с корректными offset/length
    поверх фактического текста (извлечение идёт через extract_from)."""
    at = text.lower().index("@" + username.lower())
    return MessageEntity(type="mention", offset=at, length=len("@" + username))


def _text_mention_entity(text: str, user: User) -> MessageEntity:
    at = text.index("бот")
    return MessageEntity(type="text_mention", offset=at, length=3, user=user)


def _msg(text="привет", entities=None, reply_to=None, user_id=10,
         message_id=1):
    msg = MagicMock()
    msg.text = text
    msg.entities = entities
    msg.reply_to_message = reply_to
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    return msg


def _bot_user(user_id=BOT_ID):
    u = MagicMock()
    u.id = user_id
    return u


class TestTriggers:
    @pytest.mark.asyncio
    async def test_reply_to_bot_triggers(self, wire):
        reply_to = _msg(text="ответ бота")
        reply_to.from_user = _bot_user()
        msg = _msg(text="понятно", reply_to=reply_to)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reply_to_another_user_unhandled(self, wire):
        reply_to = _msg(text="сообщение юзера")
        reply_to.from_user = _bot_user(user_id=999)
        msg = _msg(text="понятно", reply_to=reply_to)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_mention_entity_username_case_insensitive(self, wire):
        text = "@Test_Bot расскажи"
        msg = _msg(text=text, entities=[_mention_entity(text, "test_bot")])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mention_entity_mid_text(self, wire):
        """mention не в начале строки — extract_from даёт полный срез."""
        text = "а ну-ка @test_bot иди сюда"
        msg = _msg(text=text, entities=[_mention_entity(text, "test_bot")])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_text_mention_entity_by_user_id(self, wire):
        bot_user = User(id=BOT_ID, is_bot=True, first_name="Тест")
        text = "слышь, бот"
        msg = _msg(text=text, entities=[_text_mention_entity(text, bot_user)])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mention_other_user_unhandled(self, wire):
        text = "@other_user привет"
        msg = _msg(text=text, entities=[_mention_entity(text, "other_user")])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_text_mention_other_user_unhandled(self, wire):
        other = User(id=999, is_bot=False, first_name="Друг")
        text = "слышь, бот"
        msg = _msg(text=text, entities=[_text_mention_entity(text, other)])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_fallback_text_mention(self, wire):
        msg = _msg(text="а ну @Test_Bot иди сюда")
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_at_inside_word_not_trigger(self, wire):
        msg = _msg(text="пиши @test_botв лс")
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED                      # \b-граница слова

    @pytest.mark.asyncio
    async def test_plain_message_unhandled(self, wire):
        msg = _msg(text="просто текст без триггера")
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_command_not_caught(self, wire):
        msg = _msg(text="/summary")
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_bot_self_message_unhandled(self, wire):
        text = "@test_bot привет"
        msg = _msg(text=text, entities=[_mention_entity(text, "test_bot")])
        msg.from_user.id = BOT_ID
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_empty_text_unhandled(self, wire):
        msg = _msg(text="")
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_no_service_unhandled(self, wire):
        dc_mod.setup_direct_chat(None, BOT_ID, BOT_USERNAME)
        msg = _msg(text="@test_bot привет")
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
