"""Bugfix 04.09.2026 (Часть 1, AC-1.2…AC-1.6) — медиа-ветка youtube.py:
нативные TG-видео (video/document video/*, включая репосты) по триггерам
«транскрипт/че за видос/…» БЕЗ YouTube-URL → VoiceTranscriber → сырой текст /
LLM-выжимка; лимиты ДО скачивания; деградация; двойная инъекция памяти;
voice/video_note НЕ перехватываются; триггер без URL и без медиа → UNHANDLED.
"""
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from handlers import youtube as youtube_mod
from services.llm_client import LLMBadResponseError, LLMError
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    VIDEO_MEDIA_EMPTY_PHRASES,
    VIDEO_MEDIA_TOO_BIG_PHRASES,
    VIDEO_MEDIA_TOO_LONG_PHRASES,
    VIDEO_MEDIA_UNAVAILABLE_PHRASES,
)
from SmartModule.service import EmptyTranscript, TranscriptionUnavailable

CHAT_ID = -1001234567890
USER_ID = 111
MEDIA_MSG_ID = 77

_TRANSCRIPT = "текст расшифровки"


@pytest.fixture
def yv_cleanup():
    """Сброс DI/кулдауна после каждого теста (прецедент youtube_cleanup)."""
    yield
    youtube_mod._service = None
    youtube_mod._media_transcriber = None
    youtube_mod._media_db = None
    youtube_mod._media_memory = None
    youtube_mod._media_bot_id = None
    youtube_mod._cooldown._last.clear()


def _make_media_msg(text=None, caption=None, message_id=11, user_id=USER_ID,
                    video=None, document=None, voice=None, video_note=None,
                    reply_to_message=None, forward_origin=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.username = "vasya"
    msg.from_user.first_name = "Вася"
    msg.from_user.last_name = None
    msg.reply_to_message = reply_to_message
    msg.forward_origin = forward_origin
    msg.video = video
    msg.document = document
    msg.voice = voice
    msg.video_note = video_note
    return msg


def _media(**kw):
    return MagicMock(**kw)


def _setup(transcribe_result=_TRANSCRIPT, transcribe_error=None,
           summarize_result="выжимка видоса", db=None, memory=None,
           aliases=None):
    """DI окружения: сервис выжимки (summarize_transcript) + STT-заглушка
    (transcribe_voice как у контроллера VoiceTranscriber)."""
    svc = MagicMock()
    svc.summarize_transcript = AsyncMock(return_value=summarize_result)
    svc.summarize_cascade = AsyncMock(return_value="url-выжимка")
    youtube_mod.setup_youtube(svc)

    transcriber = MagicMock()
    if transcribe_error is not None:
        transcriber.transcribe_voice = AsyncMock(side_effect=transcribe_error)
    else:
        transcriber.transcribe_voice = AsyncMock(return_value=transcribe_result)
    youtube_mod.setup_youtube_video_media(transcriber, db, aliases, memory,
                                          bot_id=999)
    return svc, transcriber


def _make_bot(file_bytes=b"videodata"):
    """Bot: download пишет байты в destination (облачный режим хелпера)."""
    bot = AsyncMock()

    async def _download(file_id, destination=None):
        Path(destination).write_bytes(file_bytes)

    bot.download = AsyncMock(side_effect=_download)
    bot.get_file = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=500))
    bot.set_message_reaction = AsyncMock()
    bot.send_chat_action = AsyncMock()
    return bot


@pytest.fixture
def tmp_file_path(tmp_path, monkeypatch):
    """mkstemp → tmp_path; регистрирует созданные пути (cleanup-тесты)."""
    created = []

    def _mkstemp(prefix="yv_", suffix=""):
        path = os.path.join(str(tmp_path), f"{prefix}x{suffix}")
        with open(path, "wb") as fh:
            fh.write(b"videodata")
        created.append(path)
        return os.open(path, os.O_RDONLY), path

    monkeypatch.setattr(youtube_mod.tempfile, "mkstemp", _mkstemp)
    return created


# ── 1. Квалификация медиа / маршрутизация (FR-1/FR-2) ─────────────────

class TestMediaQualification:
    def test_document_is_video_by_mime(self):
        assert youtube_mod._document_is_video(
            _media(mime_type="video/mp4", file_name="x.bin"))
        assert youtube_mod._document_is_video(
            _media(mime_type="Video/QuickTime", file_name=""))

    def test_document_no_mime_by_extension(self):
        for ext in ("mp4", "webm", "mov", "mkv", "avi"):
            assert youtube_mod._document_is_video(
                _media(mime_type=None, file_name=f"клип.{ext}"))
            assert youtube_mod._document_is_video(
                _media(mime_type="", file_name=f"КЛИП.{ext.upper()}"))

    def test_document_mime_authoritative_over_name(self):
        """mime задан и не video/* → НЕ видео (даже с именем .mp4)."""
        assert not youtube_mod._document_is_video(
            _media(mime_type="application/pdf", file_name="ролик.mp4"))

    def test_non_video_document_excluded(self):
        assert not youtube_mod._document_is_video(
            _media(mime_type="audio/mp4", file_name="a.m4a"))
        assert not youtube_mod._document_is_video(
            _media(mime_type="application/octet-stream", file_name="a.bin"))

    @pytest.mark.asyncio
    async def test_voice_and_video_note_not_qualified(self, yv_cleanup):
        """FR-1: voice/video_note НЕ перехватываются роутером 0e (их
        обслуживает 0i) — триггер есть, медиа не видео → UNHANDLED."""
        _setup()
        for attr in ("voice", "video_note"):
            msg = _make_media_msg(text="транскрипт", **{attr: _media()})
            result = await youtube_mod.youtube_handler(msg, bot=_make_bot())
            assert result is UNHANDLED, attr

    @pytest.mark.asyncio
    async def test_trigger_without_url_and_media_unhandled(self, yv_cleanup):
        _setup()
        msg = _make_media_msg(text="поясни за видос")
        result = await youtube_mod.youtube_handler(msg, bot=_make_bot())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_video_without_trigger_unhandled(self, yv_cleanup):
        _setup()
        msg = _make_media_msg(text="просто скинул", video=_media(file_id="f"))
        result = await youtube_mod.youtube_handler(msg, bot=_make_bot())
        assert result is UNHANDLED

    @pytest.mark.asyncio
    async def test_url_branch_priority_over_media(self, yv_cleanup,
                                                  tmp_file_path):
        """FR-2: YT-URL в тексте → старая URL-ветка, медиа НЕ качается."""
        svc, transcriber = _setup()
        msg = _make_media_msg(
            text="че за видос https://youtu.be/dQw4w9WgXcQ",
            video=_media(file_id="fid_video"))
        bot = _make_bot()
        result = await youtube_mod.youtube_handler(msg, bot=bot)
        assert result is None                       # консьюм
        svc.summarize_cascade.assert_awaited_once()
        transcriber.transcribe_voice.assert_not_awaited()
        bot.download.assert_not_awaited()
        assert len(tmp_file_path) == 0              # tmp не создавался

    @pytest.mark.asyncio
    async def test_own_media_priority_over_reply_media(self, yv_cleanup,
                                                       tmp_file_path):
        """3.1.1: собственное медиа вызова приоритетнее медиа реплая."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        reply = _make_media_msg(message_id=MEDIA_MSG_ID,
                                video=_media(file_id="reply_fid"))
        msg = _make_media_msg(text="транскрипт", message_id=11,
                              video=_media(file_id="own_fid"),
                              reply_to_message=reply)
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        transcriber.transcribe_voice.assert_awaited_once()
        db.update_smart_message_text.assert_awaited_once_with(
            CHAT_ID, 11, _TRANSCRIPT)               # собственное медиа (id=11)
        reply_mock = reply
        assert reply_mock.message_id == MEDIA_MSG_ID


# ── 2. Лимиты ДО скачивания (FR-3/AC-1.3) ─────────────────────────────

class TestMediaLimits:
    @pytest.mark.asyncio
    async def test_too_big_size_phrase_before_download(self, yv_cleanup,
                                                       tmp_file_path):
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        big = _media(file_id="f", file_size=51 * 1024 * 1024, duration=10)
        msg = _make_media_msg(text="транскрипт", video=big)
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_TOO_BIG_PHRASES
        assert bot.send_message.await_args.kwargs.get("reply_to_message_id") == 11
        bot.download.assert_not_awaited()
        transcriber.transcribe_voice.assert_not_awaited()
        assert len(tmp_file_path) == 0
        db.update_smart_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_too_long_duration_phrase_before_download(self, yv_cleanup,
                                                            tmp_file_path):
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        long = _media(file_id="f", file_size=1000, duration=601)
        msg = _make_media_msg(text="че за видос", video=long)
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_TOO_LONG_PHRASES
        bot.download.assert_not_awaited()
        transcriber.transcribe_voice.assert_not_awaited()
        assert len(tmp_file_path) == 0

    @pytest.mark.asyncio
    async def test_duration_zero_or_none_not_blocked(self, yv_cleanup,
                                                     tmp_file_path):
        """duration 0/None не блокирует (FR-3); размер в лимите."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        for i, duration in enumerate((0, None)):
            media = _media(file_id="f", file_size=1000, duration=duration)
            msg = _make_media_msg(text="транскрипт",
                                  message_id=11 + i, video=media)
            bot = _make_bot()
            await youtube_mod.youtube_handler(msg, bot=bot)
            transcriber.transcribe_voice.assert_awaited()
            youtube_mod._cooldown._last.clear()

    @pytest.mark.asyncio
    async def test_document_checks_size_only(self, yv_cleanup, tmp_file_path):
        """Document: длительности нет — гейт только по размеру (в лимите)."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        doc = _media(file_id="f", file_size=5 * 1024 * 1024, duration=None,
                     mime_type="video/mp4", file_name="x.mp4")
        msg = _make_media_msg(text="транскрипт", document=doc)
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        bot.download.assert_awaited()
        transcriber.transcribe_voice.assert_awaited_once_with(
            tmp_file_path[0], "mp4")


# ── 3. Выдача: сырой текст vs LLM-выжимка (FR-6/AC-1.5) ──────────────

class TestMediaOutput:
    @pytest.mark.asyncio
    async def test_transcript_trigger_raw_text_chunked(self, yv_cleanup,
                                                       tmp_file_path):
        """«транскрипт» → сырой текст реплаем на медиа-сообщение (чанки)."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        msg = _make_media_msg(text="транскрипт", message_id=11,
                              video=_media(file_id="f"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        svc.summarize_transcript.assert_not_called()
        args, kwargs = bot.send_message.await_args
        assert args[1].startswith("Вася 🗣:")
        assert _TRANSCRIPT in args[1]
        assert kwargs.get("reply_to_message_id") == 11

    @pytest.mark.asyncio
    async def test_other_triggers_llm_summary(self, yv_cleanup,
                                              tmp_file_path):
        """«че за видос» → summarize_transcript (канон на файле) → ответ."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        msg = _make_media_msg(text="че за видос", message_id=11,
                              video=_media(file_id="f"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        svc.summarize_transcript.assert_awaited_once()
        kwargs = svc.summarize_transcript.await_args.kwargs
        assert kwargs["chat_id"] == CHAT_ID
        assert kwargs["rag_query"] == "че за видос"
        assert kwargs["transcript"] == _TRANSCRIPT
        assert bot.send_message.await_args.args[1] == "выжимка видоса"

    @pytest.mark.asyncio
    async def test_forward_repost_video_uses_source_author(
            self, yv_cleanup, tmp_file_path, monkeypatch):
        """Репост видео (forward_origin) → автор источника в лейбле/факте."""
        from handlers import summary as summary_mod

        resolver = MagicMock()
        resolver.resolve = MagicMock(
            side_effect=lambda uid, nickname=None, username=None:
            nickname or "Анонимус")
        monkeypatch.setattr(summary_mod, "_aliases", resolver)
        from aiogram.types import MessageOriginHiddenUser
        origin = MessageOriginHiddenUser.model_construct(
            type="hidden_user", date=123, sender_user_name="Скрытый Гость")
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        msg = _make_media_msg(text="транскрипт", message_id=11,
                              video=_media(file_id="f"),
                              forward_origin=origin)
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1].startswith(
            "Скрытый Гость 🗣:")

    @pytest.mark.asyncio
    async def test_caption_trigger_on_own_video(self, yv_cleanup,
                                                tmp_file_path):
        """Капшен-триггер у самого видео («видео + че за видос» в caption)."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        msg = _make_media_msg(text=None, caption="че за видос", message_id=11,
                              video=_media(file_id="f"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        svc.summarize_transcript.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == "выжимка видоса"

    @pytest.mark.asyncio
    async def test_empty_llm_answer_moai_silence(self, yv_cleanup,
                                                 tmp_file_path):
        """Пустой ответ LLM-выжимки → 🗿-молчание (без сообщения)."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        svc.summarize_transcript = AsyncMock(
            side_effect=LLMBadResponseError("empty"))
        msg = _make_media_msg(text="че за видос", message_id=11,
                              video=_media(file_id="f"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        bot.send_message.assert_not_called()
        bot.set_message_reaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_error_phrase(self, yv_cleanup, tmp_file_path):
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        svc.summarize_transcript = AsyncMock(side_effect=LLMError("llm down"))
        msg = _make_media_msg(text="че за видос", message_id=11,
                              video=_media(file_id="f"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in LLM_ERROR_PHRASES


# ── 4. Деградация (FR-8/AC-1.4) ───────────────────────────────────────

class TestMediaDegradation:
    @pytest.mark.asyncio
    async def test_empty_transcript_phrase(self, yv_cleanup, tmp_file_path):
        _setup(transcribe_error=EmptyTranscript("yv_x.mp4"))
        msg = _make_media_msg(text="транскрипт", video=_media(file_id="f"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_EMPTY_PHRASES
        assert len(tmp_file_path) == 1
        assert not os.path.exists(tmp_file_path[0])   # tmp удалён

    @pytest.mark.asyncio
    async def test_stt_unavailable_phrase(self, yv_cleanup, tmp_file_path):
        _setup(transcribe_error=TranscriptionUnavailable("yv_x.mp4"))
        msg = _make_media_msg(text="че за видос", video=_media(file_id="f"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_UNAVAILABLE_PHRASES
        assert not os.path.exists(tmp_file_path[0])

    @pytest.mark.asyncio
    async def test_fetch_failure_phrase(self, yv_cleanup, tmp_file_path):
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        bot = _make_bot()

        async def _boom(file_id, destination=None):
            raise RuntimeError("сеть упала")

        bot.download = AsyncMock(side_effect=_boom)
        msg = _make_media_msg(text="транскрипт", video=_media(file_id="f"))
        await youtube_mod.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_UNAVAILABLE_PHRASES
        transcriber.transcribe_voice.assert_not_awaited()
        assert not os.path.exists(tmp_file_path[0])
        db.update_smart_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_broken_media_resolve_does_not_crash(self, yv_cleanup):
        """Медиа-детекция упала → UNHANDLED (пропагация жива)."""
        _setup()

        class BoomDoc:
            """Любое чтение атрибутов документа падает (кривой апдейт)."""

            def __getattr__(self, name):
                raise RuntimeError("кривое сообщение")

        msg = _make_media_msg(text="транскрипт", document=BoomDoc())
        result = await youtube_mod.youtube_handler(msg, bot=_make_bot())
        assert result is UNHANDLED


# ── 5. Память (FR-7/AC-1.6) ───────────────────────────────────────────

class TestMediaMemory:
    @pytest.mark.asyncio
    async def test_double_injection(self, yv_cleanup, tmp_file_path):
        import asyncio
        import re
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, _ = _setup(db=db, memory=memory)
        msg = _make_media_msg(text="транскрипт", message_id=11,
                              video=_media(file_id="f"))
        await youtube_mod.youtube_handler(msg, bot=_make_bot())
        db.update_smart_message_text.assert_awaited_once_with(
            CHAT_ID, 11, _TRANSCRIPT)
        await asyncio.sleep(0)                # fire_and_forget
        args, kwargs = memory.memorize_facts.call_args
        raw_text = args[1]
        assert kwargs["source_type"] == "video_transcript"
        m = re.fullmatch(
            r'<MediaMessage type="video" sender="([^"]*)" '
            r'timestamp="([^"]*)">([^<]*)</MediaMessage>', raw_text)
        assert m, raw_text
        assert m.group(1) == "Вася"
        assert m.group(3) == _TRANSCRIPT

    @pytest.mark.asyncio
    async def test_memory_failure_does_not_break_reply(self, yv_cleanup,
                                                       tmp_file_path):
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(side_effect=RuntimeError)
        svc, _ = _setup(db=db, memory=None)
        msg = _make_media_msg(text="транскрипт", video=_media(file_id="f"))
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1].startswith("Вася 🗣:")


# ── 6. Document-медиа и reply (AC-1.2) ────────────────────────────────

class TestDocumentMedia:
    @pytest.mark.asyncio
    async def test_document_video_mime_transcribed(self, yv_cleanup,
                                                   tmp_file_path):
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        doc = _media(file_id="f", mime_type="video/mp4", file_name="ролик.mp4")
        msg = _make_media_msg(text="транскрипт", document=doc)
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        transcriber.transcribe_voice.assert_awaited_once()
        bot.download.assert_awaited()
        assert bot.send_message.await_args.args[1].endswith(_TRANSCRIPT)

    @pytest.mark.asyncio
    async def test_document_no_mime_by_name_transcribed(self, yv_cleanup,
                                                        tmp_file_path):
        """Document без mime, имя .mkv → транскрибируется (tmp .mkv)."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        doc = _media(file_id="f", mime_type=None, file_name="клип.mkv",
                     duration=None, file_size=100)
        msg = _make_media_msg(text="транскрипт", document=doc)
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        transcriber.transcribe_voice.assert_awaited_once()
        assert tmp_file_path[0].endswith(".mkv")

    @pytest.mark.asyncio
    async def test_reply_transcript_on_foreign_video(self, yv_cleanup,
                                                     tmp_file_path):
        """Reply «транскрипт» на чужое видео → по медиа реплая."""
        db = MagicMock()
        db.update_smart_message_text = AsyncMock(return_value=1)
        memory = MagicMock()
        memory.memorize_facts = AsyncMock()
        svc, transcriber = _setup(db=db, memory=memory)
        target = _make_media_msg(message_id=MEDIA_MSG_ID,
                                 video=_media(file_id="foreign"))
        msg = _make_media_msg(text="транскрипт", message_id=11,
                              reply_to_message=target)
        bot = _make_bot()
        await youtube_mod.youtube_handler(msg, bot=bot)
        db.update_smart_message_text.assert_awaited_once_with(
            CHAT_ID, MEDIA_MSG_ID, _TRANSCRIPT)
        assert bot.send_message.await_args.kwargs.get(
            "reply_to_message_id") == MEDIA_MSG_ID


# ── 7. Изоляция от реакций (прецедент test_epic37_router_isolation) ───

_SLAVIK_USER_ID = 479167456


def _make_reaction_msg(text, **kwargs):
    import datetime

    from aiogram.types import Chat, Message, User

    return Message(
        message_id=11,
        date=datetime.datetime.now(),
        chat=Chat(id=CHAT_ID, type="group"),
        from_user=User(id=_SLAVIK_USER_ID, is_bot=False,
                       first_name="Славик", username="slavik"),
        text=text,
        **kwargs,
    )


@pytest.fixture
def reaction_env(yv_cleanup):
    """Dispatcher: youtube 0e (медиа-ветка) + slavik/vasya-реакции в том же
    порядке, что в bot.py (0e раньше реакций). Hot-кэш выключен (settings)."""
    from aiogram import Dispatcher

    from handlers.slavik import slavik_router
    from handlers.vasya import vasya_router
    from services import hot_config as hot

    routers = (youtube_mod.youtube_router, slavik_router, vasya_router)
    for router in routers:
        router._parent_router = None

    db = MagicMock()
    db.update_smart_message_text = AsyncMock(return_value=1)
    memory = MagicMock()
    memory.memorize_facts = AsyncMock()
    _setup(db=db, memory=memory)

    old_cache = hot.get_config_cache()
    hot.set_config_cache(None)

    dp = Dispatcher()
    for router in routers:
        dp.include_router(router)
    bot = _make_bot()
    yield dp, bot
    hot.set_config_cache(old_cache)
    for router in routers:
        router._parent_router = None


def _sent_texts(bot):
    texts = []
    for call in bot.send_message.await_args_list:
        text = call.args[1] if len(call.args) > 1 else call.kwargs.get("text")
        if text:
            texts.append(text)
    for call in bot.await_args_list:
        method = call.args[0] if call.args else None
        if method is not None and getattr(method, "__api_method__", None) == "sendMessage":
            texts.append(method.text)
    return texts


class TestReactionIsolation:
    @pytest.mark.asyncio
    async def test_media_trigger_consumed_before_reactions(self, reaction_env):
        """Медиа-триггер консьюмится роутером 0e → апдейт НЕ доходит до
        реакций (slavik catch-all молчит, ровно один ответ — транскрипт)."""
        from aiogram.types import Update, Video

        dp, bot = reaction_env
        video = Video(file_id="fid", file_unique_id="fu", width=320,
                      height=240, duration=10, file_size=1000)
        msg = _make_reaction_msg("транскрипт", video=video)
        await dp.feed_update(bot, Update(update_id=1, message=msg))

        sent = _sent_texts(bot)
        assert len(sent) == 1, sent
        assert sent[0].startswith("Славик 🗣:")
        assert "пошёл нахуй" not in sent[0]

    @pytest.mark.asyncio
    async def test_media_without_trigger_still_reaches_reactions(
            self, reaction_env):
        """Обратная сторона: видео БЕЗ триггера → 0e возвращает UNHANDLED и
        апдейт ДОХОДИТ до реакций (slavik catch-all отвечает) — контроль того,
        что предыдущий тест ловит именно поломку консьюма."""
        from aiogram.types import Update, Video

        dp, bot = reaction_env
        video = Video(file_id="fid", file_unique_id="fu", width=320,
                      height=240, duration=10, file_size=1000)
        msg = _make_reaction_msg("просто скинул", video=video)
        await dp.feed_update(bot, Update(update_id=2, message=msg))

        sent = _sent_texts(bot)
        assert sent == ["пошёл нахуй"]