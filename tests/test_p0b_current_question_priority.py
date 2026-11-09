"""P0-B (source 2026-11-10 smart-module-semantic-routing §2/§3/§8-B).

Инвариант: текущее собственное сообщение пользователя — предмет поручения.
Reply-цель, цитата, пересылка, история, расшифровка и результаты инструментов
— только свидетельства. Медиа-маркер сам по себе не выбирает инструмент, и
никто ниже по цепочке не заменяет анализ разговора медиаоперацией.

Реальный инцидент: «Бот, что происходит в чате» дважды разбиралось как анализ
чужого ролика, а затем бот просил выбрать один из двух роликов. Оба симптома
давал лексический `video_intent.detect_intent` (подстрока «что происходит») +
окно соседних медиа в `handlers/youtube.py::_handle_unclassified`.

Тесты проверяют наблюдаемое поведение, а не счётчики вызовов:
* chat-summary запросы НЕ потребляются видео-роутером ни при каком содержимом
  окна (видео/два видео/кружок/пересылка), доходят до Direct Chat и получают в
  L1-пакете инструменты истории/памяти/поиска и свой текст дословно;
* видео-вопросы по-прежнему доходят до медиа-инструмента и отвечают про видео;
* reply на видео с общим вопросом о разговоре не превращается в анализ ролика;
* исполнитель по L1-плану «анализ разговора» не подменяет шаги медиаоперацией.
"""
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram.dispatcher.event.bases import UNHANDLED

from handlers import direct_chat as dc
from handlers import youtube as yt
from services import direct_capabilities as dcap
from services import video_intent
from services.smartmodule_phrases import VIDEO_INTENT_EXPIRED_PHRASES
from services.direct_chat_service import DirectChatService
from services.direct_execution import derive_simple_steps
from services.direct_l1 import L1Plan, build_l1_context

CHAT_ID = -1001234567890
USER_A = 111
USER_B = 222
BOT_ID = 999

#: Сценарий B: вопросы о разговоре, а не о ролике.
CHAT_QUESTIONS = (
    "Бот, что происходит в чате",
    "Бот, что нового?",
    "Бот, о чём сейчас спорят?",
    "Бот, что обсуждали, пока меня не было?",
    "Бот, что тут за движ?",
    "Бот, перескажи, о чём говорили",
)


def _media(file_id="f1", file_unique_id="u1", **kw):
    data = {"file_id": file_id, "file_unique_id": file_unique_id,
            "duration": 12, "file_size": 1024, "mime_type": "video/mp4",
            "file_name": None}
    data.update(kw)
    return SimpleNamespace(**data)


def _msg(text=None, caption=None, message_id=11, user_id=USER_A,
         chat_id=CHAT_ID, video=None, document=None, voice=None,
         video_note=None, reply_to_message=None, forward_origin=None,
         thread_id=None, chat_type="group", quote=None):
    m = MagicMock()
    m.text = text
    m.caption = caption
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = chat_id
    m.chat.type = chat_type
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.from_user.username = "user"
    m.from_user.first_name = "User"
    m.from_user.last_name = None
    m.reply_to_message = reply_to_message
    m.forward_origin = forward_origin
    m.video = video
    m.document = document
    m.voice = voice
    m.video_note = video_note
    m.message_thread_id = thread_id
    m.entities = None
    m.caption_entities = None
    m.media_group_id = None
    m.quote = quote
    m.reply = AsyncMock(return_value=MagicMock(message_id=900))
    return m


def _bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=500))
    bot.send_video = AsyncMock(return_value=MagicMock(message_id=501))
    bot.send_document = AsyncMock(return_value=MagicMock(message_id=502))
    return bot


@pytest.fixture
def env(monkeypatch):
    """DI youtube-модуля + моки внешних границ; окно видео-интентов чистое."""
    svc = MagicMock()
    svc.video_client = MagicMock(available=True)
    svc.summarize_media_url = AsyncMock(return_value="выжимка по видео")
    svc.summarize_transcript = AsyncMock(return_value="выжимка по транскрипту")
    svc.summarize_cascade = AsyncMock(return_value="выжимка по субтитрам")
    svc.engine = MagicMock()
    svc.engine.fetch_transcript = AsyncMock(return_value="")
    yt.setup_youtube(svc)

    transcriber = MagicMock()
    transcriber.transcribe_voice = AsyncMock(return_value="длинный транскрипт")
    yt.setup_youtube_video_media(transcriber, db=None, aliases=None,
                                 memory=None, bot_id=BOT_ID, downloader=None)

    async def _fetch(bot, media, path, *a, **kw):
        Path(path).write_bytes(b"videodata")

    monkeypatch.setattr(yt, "fetch_media_to_tmp", _fetch)
    monkeypatch.setattr(yt.media_share, "enabled", lambda: True)
    monkeypatch.setattr(
        yt.media_share, "publish_media_file",
        AsyncMock(return_value=SimpleNamespace(
            abs_url="https://media.local/x.mp4", file_id="ticket1")))
    monkeypatch.setattr(yt.media_share, "delete_file", AsyncMock())
    real_get = yt.hot.get

    def _get(key, default=None):
        return real_get(key, default)

    monkeypatch.setattr(yt.hot, "get", _get)
    yt._cooldown._last.clear()
    video_intent.reset()
    video_intent.configure_watchdog(False)
    yield SimpleNamespace(svc=svc, transcriber=transcriber)
    video_intent.reset()
    video_intent.configure_watchdog(True)
    yt._service = None
    yt._media_transcriber = None
    yt._media_db = None
    yt._media_memory = None
    yt._media_bot_id = None
    yt._media_downloader = None
    yt._cooldown._last.clear()


def _events(name):
    return [e for e in video_intent.recent_events() if e["event"] == name]


# ── VMQ-V двойники: durable source-ref + версия расшифровки ───────────────

@pytest_asyncio.fixture
async def db():
    from services.database import DatabaseService
    service = DatabaseService(":memory:")
    await service.initialize()
    try:
        yield service
    finally:
        await service.close()


async def _add_voice(db, tg_id, *, status=None, transcript=None,
                     user_id=USER_B, author="Вася"):
    row_id = await db.save_smart_message(
        user_id=user_id, chat_id=CHAT_ID, text=None, reply_to_id=None,
        timestamp=int(time.time()) - 300, media_type="voice",
        author_name=author, is_forward=False, forward_source="",
        message_id=tg_id)
    if status is not None:
        await db.set_smart_message_transcript(
            CHAT_ID, tg_id, status=status, text=transcript, reason="")
    return row_id


def _voice_query(text, *, message_id=5000, reply=None):
    return SimpleNamespace(message_id=message_id, text=text, caption=None,
                           quote=None, reply_to_message=reply,
                           from_user=SimpleNamespace(id=USER_A))


def _observe_video(message_id, *, user_id=USER_B, chat_type="group",
                   forward_origin=None, voice=None):
    """Участник присылает видео/кружок в чат (окно соседства наполняется)."""
    return _msg(message_id=message_id, user_id=user_id, chat_type=chat_type,
                video=None if voice else _media(
                    file_id=f"f{message_id}", file_unique_id=f"u{message_id}"),
                voice=voice, forward_origin=forward_origin)


# ── 1. Вопрос о разговоре не превращается в разбор ролика ─────────────────

class TestChatSummaryIsNotAVideoTask:
    """§8-B: chat-summary не потребляется 0e и доходит до Direct Chat/L1."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", CHAT_QUESTIONS)
    @pytest.mark.parametrize("window", ["empty", "one_video", "two_videos"])
    async def test_not_consumed_by_video_router(self, env, text, window):
        bot = _bot()
        if window == "one_video":
            await yt.youtube_handler(_observe_video(500), bot=bot)
        elif window == "two_videos":
            await yt.youtube_handler(_observe_video(500), bot=bot)
            await yt.youtube_handler(_observe_video(501), bot=bot)

        request = _msg(text=text, message_id=600)

        assert await yt.youtube_handler(request, bot=bot) is UNHANDLED
        # Разбора ролика нет, уточнения «какой из двух» нет, ответа нет.
        assert env.svc.summarize_media_url.await_count == 0
        assert env.svc.summarize_transcript.await_count == 0
        assert bot.send_message.await_count == 0
        assert not _events("media_ambiguous")
        assert not video_intent.has_pending(CHAT_ID)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", CHAT_QUESTIONS)
    async def test_reaches_direct_chat_trigger(self, env, text):
        """Сообщение реально попадает в 0h (триггер срабатывает)."""
        dc.setup_direct_chat(None, BOT_ID, "testbot")
        try:
            assert dc._is_direct_trigger(_msg(text=text, message_id=601)) is True
        finally:
            dc.setup_direct_chat(None, None, "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("window", ["video", "voice", "forwarded", "two"])
    async def test_media_kind_in_window_does_not_change_decision(self, env,
                                                                 window):
        """Любое содержимое окна (видео/кружок/пересылка/два) — не объект."""
        bot = _bot()
        if window == "video":
            await yt.youtube_handler(_observe_video(700), bot=bot)
        elif window == "voice":
            await yt.youtube_handler(_observe_video(
                701, voice=_media(file_id="v701", file_unique_id="uv701")),
                bot=bot)
        elif window == "forwarded":
            await yt.youtube_handler(_observe_video(
                702, forward_origin=SimpleNamespace(type="channel")), bot=bot)
        else:
            await yt.youtube_handler(_observe_video(703), bot=bot)
            await yt.youtube_handler(_observe_video(704), bot=bot)

        request = _msg(text="Бот, что происходит в чате", message_id=705)

        assert await yt.youtube_handler(request, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_previous_foreign_request_is_not_inherited(self, env):
        """§3.3: медиа-намерение соседнего сообщения не наследуется."""
        bot = _bot()
        # Участник B просит выжимку — это ЕГО задача, не задача следующего хода.
        foreign = _msg(text="Сделай выжимку", message_id=800, user_id=USER_B)
        assert await yt.youtube_handler(foreign, bot=bot) is UNHANDLED
        await yt.youtube_handler(_observe_video(801), bot=bot)

        mine = _msg(text="Бот, что нового?", message_id=802, user_id=USER_A)
        assert await yt.youtube_handler(mine, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_repeat_after_wrong_answer_asks_the_same_question(self, env):
        """§8-B: повтор вопроса после неверного ответа — снова вопрос о чате."""
        bot = _bot()
        await yt.youtube_handler(_observe_video(900), bot=bot)
        await yt.youtube_handler(_observe_video(901), bot=bot)
        first = _msg(text="Бот, что происходит в чате", message_id=902)
        second = _msg(text="Бот, что происходит в чате", message_id=903)

        assert await yt.youtube_handler(first, bot=bot) is UNHANDLED
        assert await yt.youtube_handler(second, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0
        assert not _events("media_ambiguous")


class TestMediaWordsAndLinksAreNotATask:
    """Owner correction: «видео»/«ролик»/ссылка НЕ подтверждают намерение."""

    @pytest.mark.asyncio
    async def test_video_question_without_reply_reaches_l1(self, env):
        """«Бот, что происходит в этом видео?» без reply → L1, ноль вызовов."""
        bot = _bot()
        msg = _msg(text="Бот, что происходит в этом видео?", message_id=850)
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert env.svc.summarize_transcript.await_count == 0
        assert bot.send_message.await_count == 0
        assert not video_intent.has_pending(CHAT_ID)

    @pytest.mark.asyncio
    async def test_look_at_this_video_reaches_l1(self, env):
        bot = _bot()
        msg = _msg(text="Бот, посмотри это видео", message_id=852)
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", [
        "https://youtu.be/dQw4w9WgXcQ",
        "Бот, https://youtu.be/dQw4w9WgXcQ",
        "Бот, вот https://www.tiktok.com/@x/video/1",
    ])
    async def test_bare_video_link_reaches_l1(self, env, text):
        bot = _bot()
        msg = _msg(text=text, message_id=853)
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", [
        "поясни за видос",
        "Бот, а я вчера смотрел ролик про поезда",
        "Бот, видео из отпуска получилось смешным",
        "смотрели видео вчера, прикольно",
    ])
    async def test_video_word_in_unrelated_sentence_reaches_l1(self, env, text):
        bot = _bot()
        msg = _msg(text=text, message_id=854, user_id=USER_B)
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0
        assert not video_intent.has_pending(CHAT_ID)


class TestRegisteredCommandsStillWork:
    """Реестр команд сохраняется: «транскрипт» и «че за видос»."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("command", ["транскрипт", "че за видос"])
    async def test_command_with_default_botword(self, env, command):
        """Имя персоны не задано → работает «Бот, …»."""
        from services import bot_persona
        bot_persona.set_global_name_cache("")
        bot = _bot()
        msg = _msg(text=f"Бот, {command}", message_id=860)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert video_intent.has_pending(CHAT_ID)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("address", ["Олег,", "Олега,", "Олег:"])
    @pytest.mark.parametrize("command", ["транскрипт", "че за видос"])
    async def test_command_with_configured_persona_name(self, env, address,
                                                        command):
        """Обращение по имени персоны (со склонениями) работает как «Бот»."""
        from services import bot_persona
        bot_persona.set_global_name_cache("Олег")
        try:
            bot = _bot()
            msg = _msg(text=f"{address} {command}", message_id=861)
            assert await yt.youtube_handler(msg, bot=bot) is None
            assert video_intent.has_pending(CHAT_ID)
        finally:
            bot_persona.set_global_name_cache("")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", [
        "Бот, о чем видео",
        "Бот, о чём видео",
        "Бот, поясни за видос",
    ])
    async def test_removed_phrases_reach_l1_without_video_calls(self, env,
                                                                text):
        bot = _bot()
        msg = _msg(text=text, message_id=863)
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert env.svc.summarize_transcript.await_count == 0
        assert bot.send_message.await_count == 0
        assert not video_intent.has_pending(CHAT_ID)

    @pytest.mark.asyncio
    async def test_forwarded_command_text_is_not_executed(self, env):
        """Пересланное сообщение с текстом команды — чужая речь."""
        bot = _bot()
        msg = _msg(text="Бот, че за видос", message_id=864,
                   forward_origin=SimpleNamespace(type="channel"))
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert bot.send_message.await_count == 0
        assert not video_intent.has_pending(CHAT_ID)

    @pytest.mark.asyncio
    async def test_quoted_command_text_is_not_executed(self, env):
        """Цитата чужой команды внутри своего вопроса — данные, не команда."""
        bot = _bot()
        video = _observe_video(865)
        msg = _msg(text="Бот, что это значит?", message_id=866,
                   reply_to_message=video,
                   quote=SimpleNamespace(text="Бот, че за видос"))
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_registered_command_with_reply_analyses_that_video(self, env):
        bot = _bot()
        target = _observe_video(861)
        msg = _msg(text="Бот, транскрипт", message_id=862,
                   reply_to_message=target)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.kwargs.get(
            "reply_to_message_id") == 861


class TestReplyTargetResolution:
    """Reply задаёт ОБЪЕКТ команды; соседний ролик не подставляется."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("command", ["транскрипт", "че за видос"])
    async def test_reply_to_video_targets_that_message(self, env, command):
        bot = _bot()
        target = _observe_video(1100)
        msg = _msg(text=f"Бот, {command}", message_id=1101,
                   reply_to_message=target)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.kwargs[
            "reply_to_message_id"] == 1100

    @pytest.mark.asyncio
    async def test_reply_target_wins_over_newer_history_video(self, env):
        """Два видео в истории: цель — именно replied, не более свежий."""
        bot = _bot()
        older = _observe_video(1110)
        await yt.youtube_handler(_observe_video(1111), bot=bot)
        msg = _msg(text="Бот, че за видос", message_id=1112,
                   reply_to_message=older)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert bot.send_message.await_args.kwargs[
            "reply_to_message_id"] == 1110

    @pytest.mark.asyncio
    async def test_reply_to_forwarded_video_targets_that_message(self, env):
        bot = _bot()
        target = _msg(message_id=1120, video=_media(
            file_id="f1120", file_unique_id="u1120"),
            forward_origin=SimpleNamespace(type="channel"))
        msg = _msg(text="Бот, че за видос", message_id=1121,
                   reply_to_message=target)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert bot.send_message.await_args.kwargs[
            "reply_to_message_id"] == 1120

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["voice", "video_note"])
    async def test_reply_to_voice_and_note_goes_to_transcript_path(self, env,
                                                                   kind):
        """Reply на голосовое/кружочек + «транскрипт» — свой путь 0e."""
        bot = _bot()
        target = _msg(message_id=1130, voice=_media(
            file_id="f1130", file_unique_id="u1130"),
            video_note=(_media(file_id="f1130", file_unique_id="u1130")
                        if kind == "video_note" else None))
        msg = _msg(text="Бот, транскрипт", message_id=1131,
                   reply_to_message=target)
        request = yt._classify_video_request(msg)
        assert request is not None and request.kind == "voice"
        assert request.source is target          # цель — replied, не сосед
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert bot.send_message.await_count >= 1  # транскрипт отправлен

    @pytest.mark.asyncio
    async def test_reply_to_text_message_uses_no_target_answer(self, env):
        """Reply на текст без медиа — цели нет: существующий ответ по TTL."""
        bot = _bot()
        plain = _msg(text="просто текст", message_id=1140)
        msg = _msg(text="Бот, че за видос", message_id=1141,
                   reply_to_message=plain)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0
        assert video_intent.has_pending(CHAT_ID)

        await video_intent.expire(now=time.monotonic() + 10_000)
        assert bot.send_message.await_count == 1
        assert (bot.send_message.await_args.args[1]
                in VIDEO_INTENT_EXPIRED_PHRASES)


class TestEarlyHandlersDoNotSwallowNaturalLanguage:
    """Аудит порядка роутеров: ни один ранний обработчик не ест обычную речь.

    Ранние роутеры bot.py: summary_observer(903), summary(906),
    factcheck(909), search(912), youtube(915), web(918), checkup(921) — до
    Direct Chat(925). Условия приёма у всех, кроме 0e, — зарегистрированные
    команды (см. отчёт в коммите); здесь это проверяется вызовом обработчиков
    с «заряженным» DI.
    """

    TEXTS = (
        "Бот, что происходит в чате",
        "Бот, что нового?",
        "Бот, о чём сейчас спорят?",
        "Бот, что происходит в этом видео?",
        "Бот, посмотри это видео",
        "Бот, о чем видео",
        "Бот, поясни за видос",
        "Бот, вчера смотрел ролик, смешно",
        "Бот, вот https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
    )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", TEXTS)
    async def test_factcheck_handler_does_not_consume(self, env, text):
        from handlers import factcheck as fc
        fc.setup_factcheck(MagicMock(), db=None)
        try:
            bot = _bot()
            assert await fc.factcheck_handler(_msg(text=text, message_id=1300),
                                              bot=bot) is UNHANDLED
            assert bot.send_message.await_count == 0
        finally:
            fc.setup_factcheck(None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", TEXTS)
    async def test_search_handler_does_not_consume(self, env, text):
        from handlers import search as sm
        sm.setup_search(MagicMock(), db=None)
        try:
            bot = _bot()
            assert await sm.smartsearch_handler(
                _msg(text=text, message_id=1301), bot=bot) is UNHANDLED
            assert bot.send_message.await_count == 0
        finally:
            sm.setup_search(None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", TEXTS)
    async def test_web_handler_does_not_consume(self, env, text):
        from handlers import web as wm
        wm.setup_web(MagicMock(), db=None)
        try:
            bot = _bot()
            assert await wm.web_handler(
                _msg(text=text, message_id=1302), bot=bot) is UNHANDLED
            assert bot.send_message.await_count == 0
        finally:
            wm.setup_web(None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", TEXTS)
    async def test_checkup_handler_does_not_consume(self, env, text):
        from handlers import checkup as cm
        cm.setup_checkup(MagicMock(), MagicMock(), db=None)
        try:
            bot = _bot()
            assert await cm.checkup_handler(
                _msg(text=text, message_id=1303), bot=bot) is UNHANDLED
            assert bot.send_message.await_count == 0
        finally:
            cm.setup_checkup(None, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", TEXTS)
    async def test_summary_observer_does_not_consume(self, env, text):
        from handlers import summary as sm
        sm.setup_summary(MagicMock(), db=None, aliases=None, bot_id=None)
        try:
            bot = _bot()
            assert await sm.summary_observer(
                _msg(text=text, message_id=1304)) is UNHANDLED
            assert bot.send_message.await_count == 0
        finally:
            sm.setup_summary(None)


class TestRoutingTable:
    """Таблица маршрутизации: команда → детерминированный воркер, иначе L1."""

    def test_functional_group_values(self):
        from services import bot_persona
        from services.command_prefix import functional_group
        bot_persona.set_global_name_cache("")
        assert functional_group("Бот, транскрипт") == "youtube"
        assert functional_group("Бот, че за видос") == "youtube"
        assert functional_group("Бот, о чем видео") is None
        assert functional_group("Бот, поясни за видос") is None
        assert functional_group("Бот, что происходит в чате") is None
        assert functional_group("Бот, что происходит в этом видео?") is None
        assert functional_group("Бот, найди курс биткоина") == "search"
        assert functional_group("Бот, скачай https://youtu.be/x") == "download"
        assert functional_group("Бот, ты в порядке") == "checkup"
        # «чекап»/«фактчек» — bare-команды реестра (BARE_COMMANDS), не группы.
        assert functional_group("чекап") is None
        # «нарисуй» — отдельная команда внутри Direct Chat, не ранний воркер.
        assert functional_group("Бот, нарисуй кота") is None


# ── 2. L1 получает и вопрос, и инструменты истории ───────────────────────

class TestL1PayloadKeepsQuestionAndHistoryTools:
    def test_chat_question_and_history_capabilities(self):
        """Пакет L1: вопрос дословно + history/memory/search доступны."""
        caps = tuple(dcap.available_capabilities(
            t["function"]["name"] for t in
            __import__("services.tool_schemas", fromlist=["x"])
            .active_tools(True, False)))
        assert "chat_history" in caps and "chat_memory" in caps

        text = build_l1_context(
            query="Бот, что происходит в чате",
            current_question=(
                "<Current_Question>\nчто происходит в чате "
                "[медиа: video tg:900]\n</Current_Question>"),
            reply_block="Участник: смотрите какой ролик",
            window=[{"user": "User", "text": "привет"}],
            capabilities=caps, budget_tokens=4000)

        assert "что происходит в чате" in text
        assert "chat_history" in text and "chat_memory" in text
        # Текущий вопрос идёт первым разделом пакета.
        assert text.split("\n\n", 1)[0].startswith("[СООБЩЕНИЕ]")

    def test_current_question_survives_long_reply(self):
        """Длинная цитата не вытесняет текущий вопрос из пакета L1."""
        question = "что происходит в чате"
        text = build_l1_context(
            query=question,
            current_question=f"<Current_Question>\n{question}\n"
                             f"</Current_Question>",
            reply_block="цитата " * 700,
            budget_tokens=4000)
        assert question in text
        from services.direct_l1 import L1_REPLY_SECTION
        assert f"[{L1_REPLY_SECTION}]" in text


# ── 3. Медиа-объект — свидетельство, но не задача ────────────────────────

class TestReplyObjectIsEvidenceNotTask:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", [
        "Бот, что происходит в чате",
        "Бот, что нового?",
        "Бот, о чём сейчас спорят?",
        "Бот, перескажи, о чём говорили",
    ])
    async def test_reply_to_video_with_general_question(self, env, text):
        bot = _bot()
        video = _observe_video(950)
        request = _msg(text=text, message_id=951, reply_to_message=video)

        assert await yt.youtube_handler(request, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert env.svc.summarize_transcript.await_count == 0
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_reply_to_video_with_video_question_reaches_l1(self, env):
        """Reply на реальное видео + вопрос о видео → L1 (выбор за моделью).

        Проверяем ПУТЬ: 0e не потребляет сообщение, а медиа-объект остаётся
        доступен инструментам (ctx.native_media из reply).
        """
        bot = _bot()
        video = _observe_video(960)
        request = _msg(text="Бот, что происходит в этом видео?",
                       message_id=961, reply_to_message=video)

        assert await yt.youtube_handler(request, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0

        from services import native_media
        resolved = native_media.resolve_reply_video(request)
        assert resolved is not None and resolved.kind == "video"
        assert resolved.source is video

    @pytest.mark.asyncio
    async def test_unregistered_video_wording_reaches_l1(self, env):
        """«Бот, сделай выжимку видео» — не команда реестра (выжимка — web)."""
        bot = _bot()
        video = _observe_video(970)
        request = _msg(text="Бот, сделай выжимку видео", message_id=971,
                       reply_to_message=video)

        assert await yt.youtube_handler(request, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 0


# ── 4. Текущий вопрос в блоке <Current_Question> ─────────────────────────

class TestCurrentQuestionRendering:
    def test_question_is_verbatim_and_marker_is_extra(self):
        msg = _msg(text="Бот, что происходит в чате", message_id=980)
        rendered = DirectChatService._render_current_question(None, msg)
        assert "что происходит в чате" in rendered
        assert "[медиа:" not in rendered

    def test_reply_media_adds_marker_without_replacing_text(self):
        video = _observe_video(981)
        msg = _msg(text="Бот, что происходит в чате", message_id=982,
                   reply_to_message=video)
        rendered = DirectChatService._render_current_question(None, msg)
        assert "что происходит в чате" in rendered
        assert "[медиа: video tg:981]" in rendered

    def test_long_question_not_replaced_by_reply_text(self):
        long_text = "Бот, " + ("обсуждали релиз и сроки " * 80).strip()
        msg = _msg(text=long_text, message_id=983,
                   reply_to_message=_observe_video(984))
        rendered = DirectChatService._render_current_question(
            None, msg, cap_chars=4000)
        assert "обсуждали релиз и сроки" in rendered
        assert "[медиа: video tg:984]" in rendered


# ── 5. Голосовые: расшифровка — данные source-ref (contract §5) ──────────

class TestVoiceTranscriptIsDataNotTask:
    """Contract §5: общий вопрос о чате не создаёт VoiceBundle."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", CHAT_QUESTIONS)
    async def test_chat_question_builds_no_voice_bundle(self, db, text):
        from services import voice_transcripts as vt
        await _add_voice(db, tg_id=1011, status="ready",
                         transcript="обсуждали релиз")
        await _add_voice(db, tg_id=1012, status="pending")

        parsed = vt.analyze_voice_query(text)
        assert parsed.references is False

        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID, message=_voice_query(text), query=text)
        assert bundle is None
        assert vt.render_voice_block(bundle) == ""

    @pytest.mark.asyncio
    async def test_voice_question_still_gets_transcripts(self, db):
        """Явный вопрос про голосовые — прежний VMQ-V путь сохранён."""
        from services import voice_transcripts as vt
        await _add_voice(db, tg_id=1021, status="ready",
                         transcript="обсуждали релиз")

        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=_voice_query("Бот, что там в голосовых?"),
            query="Бот, что там в голосовых?")

        assert bundle is not None
        assert bundle.items[0].source_ref
        assert bundle.items[0].status == "ready"
        assert "обсуждали релиз" in vt.render_voice_block(bundle)

    @pytest.mark.asyncio
    async def test_reply_to_video_general_question_no_voice_bundle(self, db):
        from services import voice_transcripts as vt
        await _add_voice(db, tg_id=1031, status="ready", transcript="речь")

        video_reply = SimpleNamespace(
            message_id=1030, from_user=SimpleNamespace(id=USER_B),
            voice=None, video_note=None)
        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=_voice_query("Бот, что происходит в чате",
                                 reply=video_reply),
            query="Бот, что происходит в чате")
        assert bundle is None

    @pytest.mark.asyncio
    async def test_reply_to_voice_general_question_builds_bundle_deviation(
            self, db):
        """КОНТРАКТНАЯ ДЕВИАЦИЯ §5 (зафиксирована, VMQ-V не перерабатывался).

        Reply на голосовое — СТРУКТУРНАЯ адресация конкретного source-ref
        (`structural_reply`), поэтому bundle строится (`kind="reply"`) даже
        когда `analyze_voice_query.references == False`. Литеральное условие
        контракта «references == False ⇒ не создавать VoiceBundle» для этого
        случая не выполняется. Block остаётся ДАННЫМИ: вставляется до
        `<Current_Question>` (тест ниже) и не выбирает инструмент.
        """
        from services import voice_transcripts as vt
        await _add_voice(db, tg_id=1041, status="ready", transcript="речь")
        voice_reply = SimpleNamespace(
            message_id=1041, from_user=SimpleNamespace(id=USER_B),
            voice=SimpleNamespace(file_id="v1"), video_note=None)

        bundle = await vt.resolve_voice_bundle(
            db, chat_id=CHAT_ID,
            message=_voice_query("Бот, что происходит в чате",
                                 reply=voice_reply),
            query="Бот, что происходит в чате")

        assert vt.analyze_voice_query(
            "Бот, что происходит в чате").references is False
        assert bundle is not None and bundle.kind == "reply"
        assert bundle.items[0].source_ref == "tg:1041"

    def test_voice_block_never_displaces_current_question(self):
        """Блок расшифровок вставляется ДО вопроса и не заменяет его."""
        from services import voice_transcripts as vt
        blocks = ["<Current_Question>\nчто происходит в чате\n"
                  "</Current_Question>"]
        bundle = vt.VoiceBundle(
            chat_id=CHAT_ID, target_message_id=1, kind="reply",
            items=(vt.VoiceSource(
                chat_id=CHAT_ID, tg_message_id=1011,
                timestamp=int(time.time()), author="Вася", user_id=USER_B,
                media_type="voice", reply_to_id=None, status="ready",
                revision=1, text="обсуждали релиз"),))
        stub = SimpleNamespace(
            VOICE_EVIDENCE_TAG=DirectChatService.VOICE_EVIDENCE_TAG)
        result = DirectChatService._insert_voice_evidence(stub, blocks,
                                                          bundle)

        assert len(result) == 2
        assert result[0].startswith("<voice_transcripts")
        assert "что происходит в чате" in result[1]


# ── 6. Сквозной путь: сообщение → Direct Chat → L1 → инструменты → Writer ──

class TestFullPathChatSummary:
    """Реальный pipeline DirectChatService с подменёнными I/O и LLM.

    Проверяется не возврат роутера, а весь ход: сообщение доходит до L1 с
    текстом вопроса дословно и инструментами истории/памяти, L1 выбирает
    инструменты, исполнитель не добавляет медиа-шаг, Writer отвечает.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", [
        "Бот, что происходит в чате",
        "Бот, что нового?",
    ])
    async def test_chat_summary_plan_reaches_history_tools(self, monkeypatch,
                                                           text):
        from tests.test_asap7_direct_l1 import (
            _FakeLLM, _FakeRouter, _drive, _plan_json)

        router = _FakeRouter(outputs={
            "get_recent_history": "хроника чата",
            "query_chat_memory": "факты из памяти",
        })
        llm = _FakeLLM(
            l1=_plan_json(tool_policy="auto",
                          capabilities_needed=["chat_history", "chat_memory"]),
            l2="короткая сводка обсуждения")
        svc, _react, bot, msg, user = _drive(
            monkeypatch, text, tool_router=router, llm=llm)

        await svc.handle(bot, msg, user)

        # 1. L1 реально вызван и получил вопрос дословно + инструменты истории.
        l1_msgs = llm.last_messages("l1_planner")
        assert l1_msgs, "L1 не вызывался"
        payload = "\n".join(str(m.get("content") or "") for m in l1_msgs)
        assert text.split(", ", 1)[1] in payload
        assert "chat_history" in payload and "chat_memory" in payload

        # 2. Инструменты выбраны L1: история/память, никаких медиа-шагов.
        tools = [d["tool"] for d in router.dispatched]
        assert "get_recent_history" in tools
        assert "query_chat_memory" in tools
        assert "summarize_video" not in tools
        assert "transcribe_video" not in tools

        # 3. Ответ доставлен Writer'ом.
        svc._send_direct_answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reply_to_video_does_not_add_media_step(self, monkeypatch):
        """Reply на видео + вопрос о чате: медиа-шага у исполнителя нет."""
        from tests.test_asap7_direct_l1 import (
            _FakeLLM, _FakeRouter, _drive, _plan_json)

        router = _FakeRouter(outputs={"get_recent_history": "хроника чата"})
        llm = _FakeLLM(
            l1=_plan_json(tool_policy="auto",
                          capabilities_needed=["chat_history"]),
            l2="что обсуждали")
        svc, _react, bot, msg, user = _drive(
            monkeypatch, "Бот, что происходит в чате",
            reply=_observe_video(1200), tool_router=router, llm=llm)

        await svc.handle(bot, msg, user)

        tools = [d["tool"] for d in router.dispatched]
        assert tools == ["get_recent_history"]
        svc._send_direct_answer.assert_awaited_once()


# ── 7. Исполнитель не подменяет решение L1 ───────────────────────────────

class TestNoDownstreamMediaSubstitution:
    def test_conversation_plan_has_no_media_steps(self):
        plan = L1Plan()
        plan.capabilities_needed = ["chat_history", "chat_memory"]
        steps, limitations = derive_simple_steps(
            plan, query="Бот, что происходит в чате [медиа: video tg:900]",
            announced=("get_recent_history", "query_chat_memory",
                       "summarize_video", "transcribe_video"))
        tools = [s["tool"] for s in steps]

        assert "get_recent_history" in tools
        assert "query_chat_memory" in tools
        assert "summarize_video" not in tools
        assert "transcribe_video" not in tools
        assert not limitations

    def test_video_plan_still_reaches_media_tool(self):
        """Медиа-инструмент выбирается только когда его выбрал L1."""
        plan = L1Plan()
        plan.capabilities_needed = ["video_summary"]
        steps, _ = derive_simple_steps(
            plan, query="Бот, что происходит в этом видео?",
            announced=("summarize_video", "transcribe_video",
                       "get_recent_history"))
        assert [s["tool"] for s in steps] == ["summarize_video"]
