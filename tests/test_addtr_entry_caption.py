"""ADD-TR.2 (слайс ADTR-ENTRY, 19.10.2026) — единый вход Direct.

Контракт (source-add-tr-2026-10-19.md §ADD-TR.2, снапшот L28–L36):
одно Telegram-событие интерпретируется ЦЕЛИКОМ — text/caption,
entities/caption_entities, вложения (photo / image-document), media_group,
reply, forward. Подпись к медиа — тот же пользовательский текст того же
события (не отдельная реплика): «бот …» / @username / reply боту активируют
Direct и в подписи. Канонические старые триггеры других роутеров (0c–0g)
остаются приоритетными. Три способа ссылки на изображение: (A) photo+caption
в одном сообщении; (B) текстовый reply на photo/document-image; (C) явная
ссылка на ранее присланное в чате изображение при ОДНОЗНАЧНОЙ разрешимости
(неоднозначность → без «угаданной» цели, уточнение — штатный путь L1/Writer).

TEST-LIFECYCLE: CONTRACT owner=ADTR-ENTRY
Покрывает M-ADTR-ENTRY-EVENT / -TRIGGERS / -REFS / -HANDLER
(plans/features/add-tr/requirements-map.json).
"""
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import Chat, Message, MessageEntity, PhotoSize, Update, User

import handlers.direct_chat as dc_mod
from services.direct_chat_service import (
    DirectChatService,
    _message_user_text,
)
from tests.test_direct_chat import FakeDB, FakeLLM, FakeMemory  # noqa: F401
from tests.test_direct_chat import _bot, _make_service

BOT_ID = 12345
BOT_USERNAME = "test_bot"
CHAT_ID = -1001234567890
USER_ID = 10


@pytest.fixture(autouse=True)
def _legacy_direct_l1_off(monkeypatch):
    """Контракт этого файла — входной слой, не L1-планировщик:
    детерминированно пин legacy-пайплайн (прецедент test_direct_chat)."""
    from config.settings import Settings
    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", False)
    yield


# ── Handler-level (0h) ──────────────────────────────────────────────────────


@pytest.fixture
def wire():
    service = MagicMock()
    service.handle = AsyncMock()
    dc_mod.setup_direct_chat(service, BOT_ID, BOT_USERNAME)
    yield service
    dc_mod.setup_direct_chat(None, None, None)


def _mention_entity(text: str, username: str = BOT_USERNAME) -> MessageEntity:
    at = text.lower().index("@" + username.lower())
    return MessageEntity(type="mention", offset=at, length=len(username) + 1)


def _doc(mime="image/png"):
    d = MagicMock()
    d.mime_type = mime
    d.file_id = "doc-file"
    d.file_unique_id = "doc-unique"
    return d


def _msg(text=None, caption=None, entities=None, caption_entities=None,
         reply_to=None, user_id=USER_ID, message_id=1, *, photo=False,
         document=None, media_group_id=None, forward=False):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.entities = entities
    msg.caption_entities = caption_entities
    msg.reply_to_message = reply_to
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.chat.type = "supergroup"
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    # Нативные медиа-поля — явные (MagicMock-автоатрибуты `message_media_type`
    # принял бы за «медиа есть»).
    msg.photo = [MagicMock()] if photo else None
    msg.document = document
    msg.video = None
    msg.video_note = None
    msg.voice = None
    msg.audio = None
    msg.animation = None
    msg.sticker = None
    msg.media_group_id = media_group_id
    msg.forward_origin = MagicMock() if forward else None
    return msg


def _bot_reply_target(message_id=99, text="ответ бота"):
    reply = _msg(text=text, user_id=BOT_ID, message_id=message_id)
    return reply


class TestCaptionEntryHandler:
    """M-ADTR-ENTRY-EVENT/TRIGGERS: caption — тот же текст того же события."""

    @pytest.mark.asyncio
    async def test_photo_caption_botword_triggers_direct(self, wire):
        """S1: фото + caption «бот, что на этой картинке?» → Direct
        активируется (до фикса: message.text is None → UNHANDLED)."""
        msg = _msg(text=None, caption="бот, что на этой картинке?", photo=True)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_photo_caption_without_addressing_unhandled(self, wire):
        """S3: медиа без обращения к боту — обычное поведение, БЕЗ forced Direct."""
        msg = _msg(text=None, caption="красивая кошка на закате", photo=True)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_caption_mention_entity_triggers(self, wire):
        """caption_entities (mention) — наравне с entities текста."""
        caption = "@Test_Bot что на фото?"
        msg = _msg(text=None, caption=caption, photo=True,
                   caption_entities=[_mention_entity(caption)])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_caption_text_mention_entity_by_user_id(self, wire):
        """text_mention в caption_entities: user.id == bot.id."""
        bot_user = User(id=BOT_ID, is_bot=True, first_name="Тест")
        caption = "слышь, бот"
        entity = MessageEntity(type="text_mention", offset=7, length=3,
                               user=bot_user)
        msg = _msg(text=None, caption=caption, photo=True,
                   caption_entities=[entity])
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_caption_username_fallback_without_entities(self, wire):
        """Fallback-ветка @username — тоже по подписи."""
        msg = _msg(text=None, caption="а ну @Test_Bot глянь что тут",
                   photo=True)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_caption_slash_command_unhandled(self, wire):
        """Команды не перехватываются и в подписи."""
        msg = _msg(text=None, caption="/summary", photo=True)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_photo_reply_to_bot_without_caption_triggers(self, wire):
        """Reply боту — осознанное обращение и без подписи (photo)."""
        msg = _msg(text=None, caption=None, photo=True,
                   reply_to=_bot_reply_target())
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_photo_without_caption_and_without_addressing_unhandled(self, wire):
        """S3: «голое» фото без reply/подписи — без принудительного Direct."""
        msg = _msg(text=None, caption=None, photo=True)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_image_reply_to_bot_without_caption_unhandled(self, wire):
        """Голос/стикер/прочее без подписи — свои пути (0i и ниже) не ломаем."""
        msg = _msg(text=None, caption=None, photo=False,
                   reply_to=_bot_reply_target())
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_image_document_caption_triggers(self, wire):
        """Image-document по единой политике MCA-19 (mime image/*)."""
        msg = _msg(text=None, caption="бот, прочитай скрин",
                   document=_doc("image/png"))
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pdf_document_reply_to_bot_unhandled(self, wire):
        """Не любой документ — картинка: PDF без подписи реплаем не перехват."""
        msg = _msg(text=None, caption=None, document=_doc("application/pdf"),
                   reply_to=_bot_reply_target())
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_pdf_document_caption_with_addressing_triggers(self, wire):
        """PDF + подпись с обращением: активирует Direct как текст события;
        «картинкой» документ не считается (это уровень media-маркера)."""
        msg = _msg(text=None, caption="бот, что это за файл?",
                   document=_doc("application/pdf"))
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_media_group_caption_first_element_triggers(self, wire):
        """Альбом: caption на 1-м элементе — Direct на этом элементе."""
        msg = _msg(text=None, caption="бот, что на картинке?", photo=True,
                   media_group_id="mg-1", message_id=11)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_media_group_caption_other_element_triggers(self, wire):
        """Caption может прийти на «другом» элементе альбома — тоже работаем."""
        msg = _msg(text=None, caption="бот, глянь эту", photo=True,
                   media_group_id="mg-2", message_id=13)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is None
        wire.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_media_group_member_without_caption_unhandled(self, wire):
        """Элемент альбома без подписи не активирует Direct (нет дублей)."""
        msg = _msg(text=None, caption=None, photo=True,
                   media_group_id="mg-3", message_id=12)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_forwarded_photo_caption_without_addressing_unhandled(self, wire):
        """Forward: чужая подпись без обращения — не перехватываем."""
        msg = _msg(text=None, caption="смотрите какой кот", photo=True,
                   forward=True)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_self_photo_caption_unhandled(self, wire):
        """Само-сообщения бота (photo+caption) — UNHANDLED как раньше."""
        msg = _msg(text=None, caption="бот, отчёт", photo=True, user_id=BOT_ID)
        result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_caption_memory_command_consumed_like_text(self, wire):
        """Единый путь: память-команда в подписи консьюмится тем же
        детерминированным разбором (без LLM-дубля и без второго роутера)."""
        wire.remember_user_fact = AsyncMock(return_value="saved")
        msg = _msg(text=None, caption="бот, запомни: я люблю кошек", photo=True)
        result = await dc_mod.direct_chat_handler(msg, bot=AsyncMock())
        assert result is None
        wire.handle.assert_not_called()
        wire.remember_user_fact.assert_awaited_once()
        await_args = wire.remember_user_fact.await_args.args
        assert await_args[2] == "я люблю кошек"

    @pytest.mark.asyncio
    async def test_module_flag_off_photo_caption_unhandled(self, wire):
        """Master-гейт модуля: OFF → Direct молчит и для caption-события."""
        import dataclasses
        from config.settings import settings
        mod = dataclasses.replace(settings, DIRECT_CHAT_BOTWORD_ENABLED=False)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(dc_mod, "settings", mod)
            msg = _msg(text=None, caption="бот, что на фото?", photo=True)
            result = await dc_mod.direct_chat_handler(msg, bot=MagicMock())
        assert result is UNHANDLED
        wire.handle.assert_not_called()


# ── Dispatcher-level (реальные aiogram-типы) ────────────────────────────────


def _real_photo_message(message_id=5, caption=None, caption_entities=None):
    return Message(
        message_id=message_id,
        date=datetime.datetime.now(),
        chat=Chat(id=CHAT_ID, type="supergroup"),
        from_user=User(id=USER_ID, is_bot=False, first_name="Тест"),
        photo=[PhotoSize(file_id="f1", file_unique_id="u1",
                         width=800, height=600)],
        caption=caption,
        caption_entities=caption_entities,
    )


class TestAdtrEntryDispatcher:
    """Реальные Message/Dispatcher: caption-событие доходит до 0h, UNHANDLED
    семантика для остальных сохранена."""

    @pytest.mark.asyncio
    async def test_real_photo_caption_mention_reaches_direct(self):
        dc_mod.direct_chat_router._parent_router = None
        dp = Dispatcher()
        dp.include_router(dc_mod.direct_chat_router)
        service = MagicMock()
        service.handle = AsyncMock()
        dc_mod.setup_direct_chat(service, BOT_ID, BOT_USERNAME)
        try:
            caption = "@Test_Bot что на этой картинке?"
            entity = _mention_entity(caption)
            message = _real_photo_message(caption=caption,
                                          caption_entities=[entity])
            await dp.feed_update(AsyncMock(), Update(update_id=1,
                                                     message=message))
            service.handle.assert_awaited_once()
            handled = service.handle.await_args.args[1]
            assert handled.caption == caption
        finally:
            dc_mod.direct_chat_router._parent_router = None
            dc_mod.setup_direct_chat(None, None, None)

    @pytest.mark.asyncio
    async def test_real_photo_caption_plain_unhandled(self):
        dc_mod.direct_chat_router._parent_router = None
        dp = Dispatcher()
        dp.include_router(dc_mod.direct_chat_router)
        service = MagicMock()
        service.handle = AsyncMock()
        dc_mod.setup_direct_chat(service, BOT_ID, BOT_USERNAME)
        try:
            message = _real_photo_message(caption="смотрите какой кот")
            await dp.feed_update(AsyncMock(), Update(update_id=2,
                                                     message=message))
            service.handle.assert_not_called()
        finally:
            dc_mod.direct_chat_router._parent_router = None
            dc_mod.setup_direct_chat(None, None, None)

    @pytest.mark.asyncio
    async def test_canonical_checkup_caption_priority_over_direct(self):
        """S3-adjacent + приоритет старых триггеров: «чекап»-подпись
        консьюмится 0g checkup ДО direct_chat (0h)."""
        import handlers.checkup as checkup_mod

        for router in (checkup_mod.checkup_router, dc_mod.direct_chat_router):
            router._parent_router = None
        dp = Dispatcher()
        dp.include_router(checkup_mod.checkup_router)    # 0g
        dp.include_router(dc_mod.direct_chat_router)     # 0h

        fetcher = MagicMock()
        fetcher.fetch = AsyncMock(return_value=("logs", False))
        checkup_service = MagicMock()
        checkup_service.checkup = AsyncMock(return_value="отчёт по серваку")
        checkup_mod.setup_checkup(checkup_service, fetcher)

        dc_service = MagicMock()
        dc_service.handle = AsyncMock()
        dc_mod.setup_direct_chat(dc_service, BOT_ID, BOT_USERNAME)

        bot = AsyncMock()
        bot.send_message = AsyncMock()
        try:
            message = _real_photo_message(
                message_id=11, caption="бот, чекни здоровье")
            await dp.feed_update(bot, Update(update_id=3, message=message))
            bot.send_message.assert_awaited()
            assert ("отчёт по серваку"
                    in [c.args[1] for c in bot.send_message.await_args_list
                        if len(c.args) > 1])
            dc_service.handle.assert_not_called()
        finally:
            for router in (checkup_mod.checkup_router,
                           dc_mod.direct_chat_router):
                router._parent_router = None
            checkup_mod._service = None
            checkup_mod._fetcher = None
            dc_mod.setup_direct_chat(None, None, None)


# ── Service-level: media context, MessageRef, (C)-резолв ────────────────────


def _caption_message(caption, *, message_id=777, photo=True,
                     reply_to=None, text=None, message_text=None):
    """MagicMock-сообщение с явными медиа-полями (см. комментарий _msg)."""
    m = MagicMock()
    m.text = text
    m.caption = caption
    m.entities = None
    m.caption_entities = None
    m.reply_to_message = reply_to
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.chat.type = "supergroup"
    m.from_user = MagicMock()
    m.from_user.id = USER_ID
    m.photo = [MagicMock()] if photo else None
    m.document = None
    m.video = None
    m.video_note = None
    m.voice = None
    m.audio = None
    m.animation = None
    m.sticker = None
    m.media_group_id = None
    m.forward_origin = None
    return m


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    async def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return _FakeCursor(self.rows)


class _DbWithConn:
    """Минимальный db-двойник для C-резолвера (raw-чтение mca_media_assets)."""

    def __init__(self, rows):
        self.db = _FakeConn(rows)


class TestAdtrEntryServiceMediaContext:
    """M-ADTR-ENTRY-EVENT/REFS: подпись не теряется, MessageRef сохраняется."""

    @pytest.fixture
    def svc(self):
        return _make_service(memory=FakeMemory(window=[]))

    def test_message_user_text_prefers_text(self):
        m = MagicMock()
        m.text = "привет"
        m.caption = "другая"
        assert _message_user_text(m) == "привет"

    def test_message_user_text_falls_back_to_caption(self):
        m = MagicMock()
        m.text = None
        m.caption = "  бот, что тут?  "
        assert _message_user_text(m) == "бот, что тут?"

    def test_message_user_text_empty_for_non_string(self):
        m = MagicMock()
        m.text = None
        m.caption = None
        assert _message_user_text(m) == ""

    def test_current_question_carries_caption_and_photo_ref(self, svc):
        """(A): photo+caption → текст подписи и MessageRef самого сообщения."""
        msg = _caption_message("бот, что на этой картинке?")
        q = svc._render_current_question(msg)
        assert q == ("<Current_Question>\n"
                     "что на этой картинке? [медиа: photo tg:777]\n"
                     "</Current_Question>")

    def test_current_question_carries_reply_photo_ref_for_text_reply(self, svc):
        """(B): текстовый reply на photo → ref из reply_to_message."""
        reply = _caption_message("котик", message_id=555)
        msg = _caption_message("бот, прочитай надпись", photo=False,
                               text="бот, прочитай надпись", reply_to=reply)
        q = svc._render_current_question(msg)
        assert "прочитай надпись" in q
        assert "[медиа: photo tg:555]" in q

    def test_current_question_keeps_extra_markers(self, svc):
        """(C)-маркер прокидывается тем же диалектом, как own/reply."""
        msg = _caption_message("бот, что на картинке?", photo=False,
                               text="бот, что на картинке?")
        q = svc._render_current_question(
            msg, extra_markers=("[медиа: photo tg:500]",))
        assert "[медиа: photo tg:500]" in q
        assert "что на картинке?" in q

    def test_reply_to_bot_image_result_targets_image_not_text(self, svc):
        """Reply на уже отправленный ботом image-результат: цель — реальная
        картинка (ref reply-сообщения), текста-подмены нет."""
        bot_photo = _caption_message(None, message_id=888)
        bot_photo.caption = None
        bot_photo.from_user.id = BOT_ID
        bot_photo.from_user.first_name = ""
        msg = _caption_message("бот, что тут?", photo=False,
                               text="бот, что тут?", reply_to=bot_photo)
        q = svc._render_current_question(msg)
        assert "[медиа: photo tg:888]" in q
        assert svc._l1_reply_block(msg) == ""       # текст ответа — пуст

    @pytest.mark.asyncio
    async def test_build_user_content_accepts_extra_markers(self):
        svc = _make_service(memory=FakeMemory(window=[]), db=FakeDB())
        msg = _caption_message("бот, что на картинке?", photo=False,
                               text="бот, что на картинке?")
        blocks = await svc._build_user_content(
            CHAT_ID, msg, "вася",
            extra_media_markers=("[медиа: photo tg:500]",))
        current = next(b for b in blocks if b.startswith("<Current_Question>"))
        assert "[медиа: photo tg:500]" in current

    @pytest.mark.asyncio
    async def test_handle_flow_caption_reaches_llm_context(self, monkeypatch):
        """Сквозной вход: photo+caption «бот, расскажи про дроны» →
        подпись и photo-ref доходят до ответа (Context для LLM)."""
        svc = _make_service(memory=FakeMemory(window=[]), db=FakeDB(),
                            llm=FakeLLM(text="про дроны вот что"))
        bot = _bot()
        msg = _caption_message("бот, расскажи про дроны")
        await svc.handle(bot, msg, msg.from_user)
        content = svc.llm.messages[1]["content"]
        assert "расскажи про дроны" in content
        assert "[медиа: photo tg:777]" in content
        assert bot.send_message.await_args.kwargs[
            "reply_to_message_id"] == 777

    @pytest.mark.asyncio
    async def test_handle_flow_bare_photo_reply_to_bot(self, monkeypatch):
        """Reply боту «голым» фото (text/caption оба пустые): ход не падает,
        контекст несёт медиа-маркер, ответ отправлен."""
        svc = _make_service(memory=FakeMemory(window=[]), db=FakeDB(),
                            llm=FakeLLM(text="вижу фото"))
        bot = _bot()
        reply = _caption_message("ответ бота", photo=False, message_id=90)
        reply.from_user.id = BOT_ID
        msg = _caption_message(None, reply_to=reply)
        msg.caption = None
        await svc.handle(bot, msg, msg.from_user)
        content = svc.llm.messages[1]["content"]
        assert "[медиа: photo tg:777]" in content
        bot.send_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_caption_reaches_image_route_query(self, monkeypatch):
        """Свободная/каноническая image-форма в ПОДПИСИ доходит до
        существующего Fast-Track маршрута (query = подпись). Capability-гейт
        отключён заглушкой: проверяется именно прокидывание текста события."""
        svc = _make_service(memory=FakeMemory(window=[]), db=FakeDB(),
                            llm=FakeLLM(text="ок"))
        seen = {}

        async def _fake_gate(self, chat_id, query, message, bot, **kwargs):
            return False, None

        async def _fake_pre_gate(self, chat_id, query, bot, message, user_id,
                                 **kwargs):
            seen["query"] = query
            return ""

        monkeypatch.setattr(DirectChatService, "_image_capability_gate",
                            _fake_gate)
        monkeypatch.setattr(DirectChatService, "_image_pre_gate_block",
                            _fake_pre_gate)
        bot = _bot()
        msg = _caption_message("бот, нарисуй мема с котом")
        await svc.handle(bot, msg, msg.from_user)
        assert "нарисуй мема с котом" in seen["query"]


class TestAdtrEntryEarlierImageRef:
    """(C): ранее присланное изображение при однозначности; иначе — без
    «угаданной» цели (уточнение остаётся штатному пути)."""

    def _svc(self, rows):
        return _make_service(memory=FakeMemory(window=[]),
                             db=_DbWithConn(rows))

    def _ask_msg(self, text="бот, что на картинке?", message_id=777):
        return _caption_message(None, photo=False, text=text,
                                message_id=message_id)

    @pytest.mark.asyncio
    async def test_single_recent_image_resolves(self):
        rows = [{"tg_message_id": 500, "asset_kind": "photo",
                 "created_at": 1_800_000_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ("[медиа: photo tg:500]",)

    @pytest.mark.asyncio
    async def test_document_image_resolves(self):
        rows = [{"tg_message_id": 501, "asset_kind": "document",
                 "created_at": 1_800_000_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ("[медиа: document tg:501]",)

    @pytest.mark.asyncio
    async def test_two_images_ambiguous_no_marker(self):
        rows = [{"tg_message_id": 500, "asset_kind": "photo",
                 "created_at": 1_800_000_000},
                {"tg_message_id": 490, "asset_kind": "photo",
                 "created_at": 1_799_999_900}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ()

    @pytest.mark.asyncio
    async def test_album_members_ambiguous_no_marker(self):
        """Альбом = несколько изображений-сообщений → цель неоднозначна."""
        rows = [{"tg_message_id": 600, "asset_kind": "photo",
                 "created_at": 1_800_000_000},
                {"tg_message_id": 599, "asset_kind": "photo",
                 "created_at": 1_800_000_000},
                {"tg_message_id": 598, "asset_kind": "photo",
                 "created_at": 1_800_000_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ()

    @pytest.mark.asyncio
    async def test_no_assets_no_marker(self):
        svc = self._svc([])
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ()

    @pytest.mark.asyncio
    async def test_current_message_asset_excluded(self):
        rows = [{"tg_message_id": 777, "asset_kind": "photo",
                 "created_at": 1_800_000_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ()

    @pytest.mark.asyncio
    async def test_no_vision_intent_no_db_touch(self):
        svc = self._svc([{"tg_message_id": 500, "asset_kind": "photo",
                          "created_at": 1_800_000_000}])
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg(text="бот, как дела?"))
        assert markers == ()
        assert svc.db.db.executed == []

    @pytest.mark.asyncio
    async def test_own_media_no_db_touch(self):
        svc = self._svc([{"tg_message_id": 500, "asset_kind": "photo",
                          "created_at": 1_800_000_000}])
        msg = _caption_message("бот, что на картинке?")   # photo=True (own)
        markers = await svc._resolve_earlier_image_markers(CHAT_ID, msg)
        assert markers == ()
        assert svc.db.db.executed == []

    @pytest.mark.asyncio
    async def test_reply_present_no_c_resolve(self):
        """Reply уже сужает контекст (A/B): C не подменяет цель."""
        svc = self._svc([{"tg_message_id": 500, "asset_kind": "photo",
                          "created_at": 1_800_000_000}])
        reply = _caption_message(None, photo=False, message_id=300)
        reply.text = "просто текст"
        msg = self._ask_msg()
        msg.reply_to_message = reply
        markers = await svc._resolve_earlier_image_markers(CHAT_ID, msg)
        assert markers == ()
        assert svc.db.db.executed == []

    @pytest.mark.asyncio
    async def test_non_image_kinds_not_candidates(self):
        rows = [{"tg_message_id": 500, "asset_kind": "animation",
                 "created_at": 1_800_000_000},
                {"tg_message_id": 490, "asset_kind": "photo",
                 "created_at": 1_799_999_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ("[медиа: photo tg:490]",)

    @pytest.mark.asyncio
    async def test_video_preview_kind_resolves_as_earlier_target(self):
        """ASAP5 (шов 2): превью-покрытое видео в реестре — consistent
        auto-target с reply/tool-путями (обложка kind video_preview)."""
        rows = [{"tg_message_id": 500, "asset_kind": "video_preview",
                 "created_at": 1_800_000_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ("[медиа: video_preview tg:500]",)

    @pytest.mark.asyncio
    async def test_animation_preview_kind_resolves_as_earlier_target(self):
        """ASAP5 (шов 2): обложка GIF/TGS/WebM-стикера (kind
        animation_preview, вкл. size_variant sticker_preview — отдельного
        kind sticker_preview в реестре нет) — тот же consistent auto-target."""
        rows = [{"tg_message_id": 501, "asset_kind": "animation_preview",
                 "created_at": 1_800_000_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ("[медиа: animation_preview tg:501]",)

    @pytest.mark.asyncio
    async def test_gif_rows_resolve_via_cover_only(self):
        """GIF в реестре = animation (unsupported-хвост) + animation_preview
        (обложка) с одним tg_message_id: цель резолвится ПО ОБЛОЖКЕ,
        unsupported-kind кандидатом не становится и двусмысленности не
        создаёт."""
        rows = [{"tg_message_id": 502, "asset_kind": "animation_preview",
                 "created_at": 1_800_000_000},
                {"tg_message_id": 502, "asset_kind": "animation",
                 "created_at": 1_800_000_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ("[медиа: animation_preview tg:502]",)

    @pytest.mark.asyncio
    async def test_two_preview_media_ambiguous_no_marker(self):
        """Однозначность не ослабляется: два preview-покрытых медиа в окне —
        цели НЕТ (уточнение — штатный путь)."""
        rows = [{"tg_message_id": 500, "asset_kind": "video_preview",
                 "created_at": 1_800_000_000},
                {"tg_message_id": 490, "asset_kind": "animation_preview",
                 "created_at": 1_799_999_000}]
        svc = self._svc(rows)
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ()

    @pytest.mark.asyncio
    async def test_db_error_fail_open(self):
        class _Boom:
            async def execute(self, sql, params=()):
                raise RuntimeError("db down")

        from types import SimpleNamespace
        svc = _make_service(memory=FakeMemory(window=[]),
                            db=SimpleNamespace(db=_Boom()))
        markers = await svc._resolve_earlier_image_markers(
            CHAT_ID, self._ask_msg())
        assert markers == ()
