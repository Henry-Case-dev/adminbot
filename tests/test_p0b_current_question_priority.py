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


class TestVideoWordStillNeedsAddressing:
    """Видео-слово в чужой речи не делает ход видео-задачей (§2/§7)."""

    @pytest.mark.asyncio
    async def test_group_unaddressed_video_talk_unhandled(self, env):
        bot = _bot()
        msg = _msg(text="поясни за видос", message_id=850, user_id=USER_B)
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert bot.send_message.await_count == 0
        assert not video_intent.has_pending(CHAT_ID)

    @pytest.mark.asyncio
    async def test_group_addressed_video_request_is_a_command(self, env):
        bot = _bot()
        msg = _msg(text="Бот, поясни за видос", message_id=851)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert bot.send_message.await_count == 0
        assert video_intent.has_pending(CHAT_ID)


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
    async def test_reply_to_video_with_video_question_is_analysed(self, env):
        """«Что в этом видео?» — видео-объект назван, анализ исполняется."""
        bot = _bot()
        video = _observe_video(960)
        request = _msg(text="Бот, что происходит в этом видео?",
                       message_id=961, reply_to_message=video)

        assert await yt.youtube_handler(request, bot=bot) is None
        assert env.svc.summarize_media_url.await_count == 1
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.kwargs.get(
            "reply_to_message_id") == 960

    @pytest.mark.asyncio
    async def test_reply_to_video_with_command_is_analysed(self, env):
        bot = _bot()
        video = _observe_video(970)
        request = _msg(text="Бот, сделай выжимку видео", message_id=971,
                       reply_to_message=video)

        assert await yt.youtube_handler(request, bot=bot) is None
        assert env.svc.summarize_media_url.await_count == 1
        assert bot.send_message.await_count == 1


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


# ── 6. Исполнитель не подменяет решение L1 ───────────────────────────────

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
