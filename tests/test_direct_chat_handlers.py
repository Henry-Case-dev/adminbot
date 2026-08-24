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

import datetime
import logging
import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import CommandObject
from aiogram.types import MessageEntity, User

from config.settings import settings
from handlers import direct_chat as dc_mod
from services.smartmodule_phrases import (
    CHAT_CLEAR_DONE_PHRASE,
    CHAT_FORGET_DONE_PHRASE,
    CHAT_FORGET_MISS_PHRASE,
    CHAT_FORGET_NOARG_PHRASE,
    CHAT_PERSONA_PHRASE,
    CHAT_TONE_SET_PHRASES,
    CHAT_TONE_SHOW_PHRASE,
    CHAT_TONE_UNKNOWN_PHRASE,
)

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
        """text_mention другого юзера БЕЗ standalone keyword-триггера → UNHANDLED
        («робот» — не триггер: «бот» внутри слова, lookbehind блокирует).
        (T-411: standalone «бот» в тексте — осознанный keyword-триггер, см.
        test_text_mention_other_user_with_botword_triggers.)"""
        other = User(id=999, is_bot=False, first_name="Друг")
        text = "слышь, робот какой-то"
        msg = _msg(text=text, entities=[_text_mention_entity(text, other)])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_text_mention_other_user_with_botword_triggers(self, wire):
        """T-411: text_mention чужого юзера, но в тексте standalone «бот» →
        keyword-ветка срабатывает (OR-семантика, R52-4)."""
        other = User(id=999, is_bot=False, first_name="Друг")
        text = "слышь, бот"
        msg = _msg(text=text, entities=[_text_mention_entity(text, other)])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

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


# ── Epic 52 (T-411, R52-4): keyword-триггеры «бот»-семьи ──


class TestBotwordTriggers:
    """T-411: «бот»/«ботохуета»/«ботина»/«ботяра»/«ботик»/«ботохуйня» с word-boundary."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", [
        "бот",
        "бот, чё по жизни",
        "ботохуета",
        "ботина",
        "ботяра",
        "ботик",
        "ботохуйня",
        "давай, бот, рассказывай",
    ])
    async def test_keyword_triggers(self, wire, text):
        """Позитив: keyword → service.handle вызван."""
        msg = _msg(text=text)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", [
        "робот",
        "работа",
        "забота",
        "заботиться",
        "ботва",
        "это не ботва а работа",
        "рабочий график",
    ])
    async def test_keyword_not_trigger(self, wire, text):
        """Негатив: «робот»/«ботва»/«работа»/«забота» → UNHANDLED, handle НЕ вызван."""
        msg = _msg(text=text)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_botva_substring_not_trigger(self, wire):
        """«ботва» — lookahead блокирует голый «бот» внутри."""
        msg = _msg(text="ботва растёт")
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_uppercase_keyword_triggers(self, wire):
        """Регистронезависимость: «БОТ»/«Ботохуета»."""
        for text in ("БОТ", "Ботохуета"):
            msg = _msg(text=text)
            result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
            assert result is None
            wire.handle.assert_awaited()
            wire.handle.reset_mock()

    @pytest.mark.asyncio
    async def test_keyword_flag_false_silent(self, wire):
        """DIRECT_CHAT_BOTWORD_ENABLED=False → keyword-ветка молчит."""
        import handlers.direct_chat as dc_module
        from dataclasses import replace
        from config.settings import settings
        mod = replace(settings, DIRECT_CHAT_BOTWORD_ENABLED=False)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dc_module, "settings", mod)
            msg = _msg(text="бот")
            result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_keyword_flag_false_reply_still_works(self, wire):
        """Flag false: reply на бота продолжает работать (приоритет не ломается)."""
        import handlers.direct_chat as dc_module
        from dataclasses import replace
        from config.settings import settings
        mod = replace(settings, DIRECT_CHAT_BOTWORD_ENABLED=False)
        reply_to = _msg(text="ответ бота")
        reply_to.from_user = _bot_user()
        msg = _msg(text="понятно, бот", reply_to=reply_to)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dc_module, "settings", mod)
            result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_keyword_flag_false_mention_still_works(self, wire):
        """Flag false: mention продолжает работать."""
        import handlers.direct_chat as dc_module
        from dataclasses import replace
        from config.settings import settings
        mod = replace(settings, DIRECT_CHAT_BOTWORD_ENABLED=False)
        text = "@Test_Bot расскажи"
        msg = _msg(text=text, entities=[_mention_entity(text, "test_bot")])
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dc_module, "settings", mod)
            result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reply_to_other_user_with_keyword_unhandled(self, wire):
        """Reply на чужое сообщение + «бот» в тексте → reply-приоритет НЕ сработал,
        keyword сработал (OR-семантика)."""
        reply_to = _msg(text="сообщение юзера")
        reply_to.from_user = _bot_user(user_id=999)
        msg = _msg(text="бот", reply_to=reply_to)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None                      # keyword → trigger
        wire.handle.assert_awaited_once()


# ── H2 (review-fix): keyword «бот» не перехватывает чужие роутерные сценарии ──


class TestBotwordUserExclusions:
    """H2: юзеры со своими роутерами (alan 3 / kostik 2) — keyword-ветка
    НЕ триггерит (0h → UNHANDLED); reply на бота / mention — осознанное
    обращение, работают как раньше."""

    @pytest.mark.asyncio
    async def test_alan_botword_unhandled(self, wire):
        from config.settings import settings
        msg = _msg(text="бот", user_id=settings.ALAN_USER_ID)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_kostik_botword_unhandled(self, wire):
        from config.settings import settings
        msg = _msg(text="бот, чё по жизни", user_id=settings.KOSTIK_USER_ID)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_alan_reply_to_bot_still_triggers(self, wire):
        """Исключение — ТОЛЬКО для keyword-ветки: reply на бота остаётся
        триггером (осознанное обращение)."""
        from config.settings import settings
        reply_to = _msg(text="ответ бота")
        reply_to.from_user = _bot_user()
        msg = _msg(text="бот, ты тут?", reply_to=reply_to, user_id=settings.ALAN_USER_ID)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_kostik_mention_still_triggers(self, wire):
        """Mention на бота от Костика — осознанное обращение, триггер жив."""
        from config.settings import settings
        text = "@test_bot привет"
        msg = _msg(text=text, entities=[_mention_entity(text, "test_bot")],
                   user_id=settings.KOSTIK_USER_ID)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_other_user_botword_still_triggers(self, wire):
        """Обычный юзер (без своего роутера) — keyword работает как раньше."""
        msg = _msg(text="бот", user_id=10)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()


# ── L3 (review-fix): «домен.бот» / «путь/бот» не триггерят ──


class TestBotwordDomainSeparators:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", [
        "зайди на домен.бот",
        "файл лежит в путе/бот",
        "домен.бот или что-то ещё",
    ])
    async def test_dot_slash_before_bot_not_trigger(self, wire, text):
        """L3: '.'/'/' в lookbehind — «домен.бот»/«путь/бот» НЕ триггерят."""
        msg = _msg(text=text)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()


# ── H2 (review-fix): интеграция — 0h не консьюмит «бот» Алана/Костика ──


class TestBotwordRouterExclusionIntegration:
    """Полный Dispatcher: direct_chat (0h) + kostik (2) + alan (3).
    Сообщение Алана с «бот» (без reply/mention) → 0h вернул UNHANDLED →
    alan_router видит (increment_and_get_count вызван). Сообщение Костика
    с «бот» → kostik_router отвечает."""

    @pytest.mark.asyncio
    async def test_alan_and_kostik_botword_reach_own_routers(self):
        import handlers.alan as alan_mod
        import handlers.direct_chat as dc_module
        import handlers.kostik as kostik_mod
        from aiogram import Dispatcher
        from aiogram.types import Chat, Message, Update, User
        from config.settings import settings

        for router in (dc_module.direct_chat_router,
                       kostik_mod.kostik_router,
                       alan_mod.alan_router):
            router._parent_router = None

        dp = Dispatcher()
        dp.include_router(dc_module.direct_chat_router)   # 0h (раньше 2/3)
        dp.include_router(kostik_mod.kostik_router)       # 2
        dp.include_router(alan_mod.alan_router)           # 3

        alan_db = MagicMock()
        alan_db.increment_and_get_count = AsyncMock(return_value=1)
        alan_db.get_alan_last_message_ts = AsyncMock(return_value=None)
        alan_db.set_alan_last_message_ts = AsyncMock()
        alan_mod.setup_alan(alan_db)
        alan_mod._last_greeting.clear()

        dc_service = MagicMock()
        dc_service.handle = AsyncMock()
        dc_module.setup_direct_chat(dc_service, BOT_ID, BOT_USERNAME)

        bot = AsyncMock()
        bot.send_message = AsyncMock()

        alan_msg = Message(
            message_id=1,
            date=datetime.datetime.now(),
            chat=Chat(id=CHAT_ID, type="group"),
            from_user=User(id=settings.ALAN_USER_ID, is_bot=False, first_name="Алан"),
            text="бот",
        )
        await dp.feed_update(bot, Update(update_id=1, message=alan_msg))

        # 0h НЕ консьюмил → alan_router (3) увидел: счётчик инкрементился
        alan_db.increment_and_get_count.assert_awaited_once()
        dc_service.handle.assert_not_called()

        kostik_msg = Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=Chat(id=CHAT_ID, type="group"),
            from_user=User(id=settings.KOSTIK_USER_ID, is_bot=False, first_name="Костик"),
            text="бот, ну что",
        )
        await dp.feed_update(bot, Update(update_id=2, message=kostik_msg))

        # kostik (2) ответил своей фразой через message.reply → bot вызван
        assert bot.called
        method = bot.call_args.args[0]
        assert method.text in kostik_mod.KOSTIK_REPLIES
        # direct_chat по-прежнему молчит (сообщение не консьюмлено 0h)
        dc_service.handle.assert_not_called()

        for router in (dc_module.direct_chat_router,
                       kostik_mod.kostik_router,
                       alan_mod.alan_router):
            router._parent_router = None
        alan_mod.alan_db = None
        alan_mod._last_greeting.clear()
        dc_module.setup_direct_chat(None, None, None)


# ── Epic 52 (T-411): приоритет 0a–0g над 0h (checkup консьюмит раньше) ──


class TestBotwordPriorityIntegration:
    """«пульс бота»/«бот, чекни здоровье» → checkup (0g) консьюмит,
    direct_chat (0h) НЕ отвечает."""

    @pytest.mark.asyncio
    async def test_checkup_consumes_before_direct_chat(self):
        import handlers.checkup as checkup_mod
        import handlers.direct_chat as dc_module
        from aiogram import Dispatcher
        from aiogram.types import Chat, Message, Update, User
        from unittest.mock import AsyncMock

        for router in (checkup_mod.checkup_router, dc_module.direct_chat_router):
            router._parent_router = None

        dp = Dispatcher()
        dp.include_router(checkup_mod.checkup_router)    # 0g
        dp.include_router(dc_module.direct_chat_router)  # 0h

        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("logs", False))
        service = MagicMock()
        service.checkup = AsyncMock(return_value="отчёт по серваку")
        checkup_mod.setup_checkup(service, fetcher)

        dc_service = MagicMock()
        dc_service.handle = AsyncMock()
        dc_module.setup_direct_chat(dc_service, BOT_ID, BOT_USERNAME)

        bot = AsyncMock()
        bot.send_message = AsyncMock()

        message = Message(
            message_id=11,
            date=datetime.datetime.now(),
            chat=Chat(id=CHAT_ID, type="group"),
            from_user=User(id=10, is_bot=False, first_name="Тест"),
            text="бот, чекни здоровье",
        )
        await dp.feed_update(bot, Update(update_id=1, message=message))

        # ответил ровно checkup (0g); direct_chat (0h) НЕ вызван
        bot.send_message.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == "отчёт по серваку"
        dc_service.handle.assert_not_called()

        for router in (checkup_mod.checkup_router, dc_module.direct_chat_router):
            router._parent_router = None
        checkup_mod._service = None
        checkup_mod._fetcher = None
        dc_module.setup_direct_chat(None, None, None)


class TestEditedMessage:
    """65.2 (T-470): бот отредактировал СВОЁ сообщение → обновить bot_replies;
    правка человеком → UNHANDLED, переотвечания нет."""

    @pytest.fixture
    def wire_edited(self):
        service = MagicMock()
        service.remember_bot_reply = AsyncMock()
        dc_mod.setup_direct_chat(service, BOT_ID, BOT_USERNAME)
        yield service
        dc_mod.setup_direct_chat(None, None, None)

    @pytest.mark.asyncio
    async def test_bot_edit_updates_bot_replies(self, wire_edited):
        msg = _msg(text="новый текст ответа бота", message_id=55)
        msg.from_user.id = BOT_ID
        result = await dc_mod.direct_chat_edited_handler(msg, bot=AsyncMock())
        assert result is not UNHANDLED
        wire_edited.remember_bot_reply.assert_awaited_once_with(
            CHAT_ID, 55, "новый текст ответа бота")

    @pytest.mark.asyncio
    async def test_human_edit_unhandled(self, wire_edited):
        msg = _msg(text="человек поправил себя", message_id=56)
        result = await dc_mod.direct_chat_edited_handler(msg, bot=AsyncMock())
        assert result is UNHANDLED
        wire_edited.remember_bot_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_edit_unhandled(self, wire_edited):
        msg = _msg(text="   ", message_id=57)
        msg.from_user.id = BOT_ID
        result = await dc_mod.direct_chat_edited_handler(msg, bot=AsyncMock())
        assert result is UNHANDLED
        wire_edited.remember_bot_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_service_unhandled(self):
        dc_mod.setup_direct_chat(None, BOT_ID, BOT_USERNAME)
        msg = _msg(text="текст", message_id=58)
        msg.from_user.id = BOT_ID
        result = await dc_mod.direct_chat_edited_handler(msg, bot=AsyncMock())
        assert result is UNHANDLED
        dc_mod.setup_direct_chat(None, None, None)


class TestDialogCommands:
    """65.5 (T-473): /clear /persona /tone /forget — фразы VERBATIM из
    Section 65.5; Command-хендлеры регистрируются ВЫШЕ catch-all."""

    @pytest.fixture
    def wire_commands(self):
        service = MagicMock()
        service.get_tone_preset = AsyncMock(return_value=None)
        service.set_tone_preset = AsyncMock()
        service.clear_user_dialogue = AsyncMock(return_value=3)
        service.forget_user_fact = AsyncMock(return_value=0)
        dc_mod.setup_direct_chat(service, BOT_ID, BOT_USERNAME)
        yield service
        dc_mod.setup_direct_chat(None, None, None)

    async def _run(self, handler, text="команда", command=None, bot=None):
        msg = _msg(text=text)
        kwargs = {}
        if command is not None:
            kwargs["command"] = command
        return await handler(msg, bot=bot or AsyncMock(), **kwargs)

    @pytest.mark.asyncio
    async def test_clear_replies_verbatim(self, wire_commands):
        bot = AsyncMock()
        result = await self._run(dc_mod.cmd_clear, bot=bot)
        assert result is not UNHANDLED
        wire_commands.clear_user_dialogue.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == CHAT_CLEAR_DONE_PHRASE
        assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 1

    @pytest.mark.asyncio
    async def test_persona_default_tone(self, wire_commands):
        bot = AsyncMock()
        await self._run(dc_mod.cmd_persona, bot=bot)
        expected = CHAT_PERSONA_PHRASE.replace("{tone}", "сбалансированный")
        assert bot.send_message.await_args.args[1] == expected

    @pytest.mark.asyncio
    async def test_persona_stored_tone(self, wire_commands):
        wire_commands.get_tone_preset = AsyncMock(return_value="chatty")
        bot = AsyncMock()
        await self._run(dc_mod.cmd_persona, bot=bot)
        expected = CHAT_PERSONA_PHRASE.replace("{tone}", "болтливый")
        assert bot.send_message.await_args.args[1] == expected

    @pytest.mark.asyncio
    async def test_tone_show_without_args(self, wire_commands):
        bot = AsyncMock()
        await self._run(dc_mod.cmd_tone, bot=bot,
                        command=CommandObject(command="tone"))
        expected = CHAT_TONE_SHOW_PHRASE.replace("{tone}", "сбалансированный")
        assert bot.send_message.await_args.args[1] == expected
        wire_commands.set_tone_preset.assert_not_called()

    @pytest.mark.asyncio
    async def test_tone_set_chatty(self, wire_commands):
        bot = AsyncMock()
        await self._run(dc_mod.cmd_tone, bot=bot,
                        command=CommandObject(command="tone", args="болтливый"))
        wire_commands.set_tone_preset.assert_awaited_once_with(CHAT_ID, 10, "chatty")
        assert bot.send_message.await_args.args[1] == CHAT_TONE_SET_PHRASES["chatty"]

    @pytest.mark.asyncio
    async def test_tone_unknown_word(self, wire_commands):
        bot = AsyncMock()
        await self._run(dc_mod.cmd_tone, bot=bot,
                        command=CommandObject(command="tone", args="кринжовый"))
        assert bot.send_message.await_args.args[1] == CHAT_TONE_UNKNOWN_PHRASE
        wire_commands.set_tone_preset.assert_not_called()

    @pytest.mark.asyncio
    async def test_forget_without_args(self, wire_commands):
        bot = AsyncMock()
        await self._run(dc_mod.cmd_forget, bot=bot,
                        command=CommandObject(command="forget"))
        assert bot.send_message.await_args.args[1] == CHAT_FORGET_NOARG_PHRASE
        wire_commands.forget_user_fact.assert_not_called()

    @pytest.mark.asyncio
    async def test_forget_miss(self, wire_commands):
        bot = AsyncMock()
        await self._run(dc_mod.cmd_forget, bot=bot,
                        command=CommandObject(command="forget", args="про дроны"))
        args = wire_commands.forget_user_fact.await_args.args
        assert args[0] == CHAT_ID and args[2] == "про дроны"
        assert bot.send_message.await_args.args[1] == CHAT_FORGET_MISS_PHRASE

    @pytest.mark.asyncio
    async def test_forget_done(self, wire_commands):
        wire_commands.forget_user_fact = AsyncMock(return_value=2)
        bot = AsyncMock()
        await self._run(dc_mod.cmd_forget, bot=bot,
                        command=CommandObject(command="forget", args="дроны"))
        assert bot.send_message.await_args.args[1] == CHAT_FORGET_DONE_PHRASE

    @pytest.mark.asyncio
    async def test_commands_from_bot_user_unhandled(self, wire_commands):
        msg = _msg(text="/clear")
        msg.from_user.id = BOT_ID
        result = await dc_mod.cmd_clear(msg, bot=AsyncMock())
        assert result is UNHANDLED
        wire_commands.clear_user_dialogue.assert_not_called()

    @pytest.mark.asyncio
    async def test_commands_without_from_user_unhandled(self, wire_commands):
        msg = _msg(text="/clear")
        msg.from_user = None
        result = await dc_mod.cmd_clear(msg, bot=AsyncMock())
        assert result is UNHANDLED
        wire_commands.clear_user_dialogue.assert_not_called()


class TestPersonaCardCommand:
    """Epic 60 Фаза D (66.9, T-487): /persona <имя> — карточка; /persona list —
    админ-список; права (своя/чужая/админ); пустая карточка — фраза VERBATIM."""

    @pytest.fixture
    def wire_card(self):
        service = MagicMock()
        service.get_tone_preset = AsyncMock(return_value=None)
        service.build_persona_card = AsyncMock(return_value=None)
        service.list_persona_names = AsyncMock(return_value=[])
        service.persona_access = MagicMock(return_value=True)
        dc_mod.setup_direct_chat(service, BOT_ID, BOT_USERNAME)
        yield service
        dc_mod.setup_direct_chat(None, None, None)

    async def _run(self, handler, args=None, user_id=10):
        msg = _msg(text="команда", user_id=user_id)
        command = CommandObject(command="persona", args=args)
        bot = AsyncMock()
        return await handler(msg, bot=bot, command=command), bot

    @pytest.mark.asyncio
    async def test_no_args_shows_persona_tone(self, wire_card):
        _, bot = await self._run(dc_mod.cmd_persona, args=None)
        expected = CHAT_PERSONA_PHRASE.replace("{tone}", "сбалансированный")
        assert bot.send_message.await_args.args[1] == expected
        wire_card.build_persona_card.assert_not_called()

    @pytest.mark.asyncio
    async def test_card_with_name(self, wire_card):
        wire_card.build_persona_card = AsyncMock(
            return_value="карточка: вася\nзнаю о тебе: 1 фактов, 0 связей\n1. факт")
        _, bot = await self._run(dc_mod.cmd_persona, args="вася")
        wire_card.persona_access.assert_called_once()
        assert bot.send_message.await_args.args[1].startswith("карточка: вася")

    @pytest.mark.asyncio
    async def test_card_empty_verbatim_phrase(self, wire_card):
        """66.9 VERBATIM: «в памяти про {имя} пока пусто, пусть хоть раз
        нормально пообщается»."""
        _, bot = await self._run(dc_mod.cmd_persona, args="петя")
        sent = bot.send_message.await_args.args[1]
        assert sent == ("в памяти про петя пока пусто, "
                        "пусть хоть раз нормально пообщается")

    @pytest.mark.asyncio
    async def test_foreign_card_denied(self, wire_card):
        """66.9/R17: чужую карточку видит только ADMIN_USER_ID."""
        wire_card.persona_access = MagicMock(return_value=False)
        _, bot = await self._run(dc_mod.cmd_persona, args="вася")
        from services.smartmodule_phrases import CHAT_PERSONA_FOREIGN_PHRASE
        assert bot.send_message.await_args.args[1] == CHAT_PERSONA_FOREIGN_PHRASE
        wire_card.build_persona_card.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_denied_for_non_admin(self, wire_card):
        from services.smartmodule_phrases import CHAT_PERSONA_ADMIN_ONLY_PHRASE
        _, bot = await self._run(dc_mod.cmd_persona, args="list", user_id=999)
        assert bot.send_message.await_args.args[1] == CHAT_PERSONA_ADMIN_ONLY_PHRASE
        wire_card.list_persona_names.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_for_admin(self, wire_card):
        wire_card.list_persona_names = AsyncMock(return_value=[("вася", 3)])
        _, bot = await self._run(dc_mod.cmd_persona, args="list",
                                 user_id=settings.ADMIN_USER_ID)
        sent = bot.send_message.await_args.args[1]
        assert "вася — 3 фактов" in sent

    @pytest.mark.asyncio
    async def test_list_empty_for_admin(self, wire_card):
        from services.smartmodule_phrases import CHAT_PERSONA_LIST_EMPTY_PHRASE
        _, bot = await self._run(dc_mod.cmd_persona, args="list",
                                 user_id=settings.ADMIN_USER_ID)
        assert bot.send_message.await_args.args[1] == CHAT_PERSONA_LIST_EMPTY_PHRASE


class TestBotwordFromConfig:
    """Epic 60 Фаза E (67.2, T-492, правило п.49): keyword-regex «бот»-семьи —
    в конфиге CHAT_BOTWORD_PATTERN. Дефолт байт-в-байт равен старому литералу
    (тесты 61.5 выше зелёные без правок); невалидный regex → WARNING + дефолт."""

    LEGACY = r"(?i)(?<![0-9a-zа-яё_./])бот(?:ина|яра|ик|охуета|охуйня)?(?![0-9a-zа-яё_])"

    def test_default_pattern_byte_for_byte_legacy(self):
        assert settings.CHAT_BOTWORD_PATTERN == self.LEGACY
        assert dc_mod._BOTWORD_PATTERN_DEFAULT == self.LEGACY
        assert dc_mod._BOTWORD_RE.pattern == self.LEGACY

    def test_custom_pattern_compiles(self):
        rx = dc_mod._compile_botword(r"(?i)альфа")
        assert rx.search("ну альфа и привет")
        assert not rx.search("слышь, бот")

    def test_invalid_regex_falls_back_to_default(self, caplog):
        with caplog.at_level(logging.WARNING):
            rx = dc_mod._compile_botword("(?i)(?<бот")     # битый lookbehind
        assert rx.pattern == dc_mod._BOTWORD_PATTERN_DEFAULT
        assert any("CHAT_BOTWORD_PATTERN invalid" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_default_semantics_unchanged(self, wire):
        """Дефолт из конфига триггит ровно как старый литерал."""
        msg = _msg(text="слышь, бот")
        assert await dc_mod.direct_chat_handler(msg, bot=MagicMock()) is None
        wire.handle.assert_awaited_once()
