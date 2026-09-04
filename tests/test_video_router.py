"""Раунд 3 (T-688…T-694, AC-B3…AC-B8) — универсальный видео-маршрутизатор 0e.

Классификация kind×mode (reply-медиа/caption/«триггер <ссылка>», youtube в
reply-таргете, видео+ссылка → URL, voice/video_note НЕ 0e, UNHANDLED);
матрица потоков с моками (summarize_media_url/download/publish_media_file/
transcribe_voice): direct_url+summary (внешний URL → провал → скачать →
опубликовать → L1/L2 → STT), platform_url+summary (скачать → публикация),
direct/platform+transcript (скачать → STT), youtube+transcript (субтитры →
скачивание+STT), честная фраза 5.13 на «немом» видео, B8-фолбек отсутствующей
строки smart_messages (юзер → INSERT; бот → INFO-skip), память URL-режимов
(только memorize), изоляция от voice/video_note.
"""
import asyncio
import dataclasses
import os
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from handlers import youtube as yt
from services import hot_config as hot
from services.media_share import ShareTicket
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    VIDEO_MEDIA_EMPTY_PHRASES,
    VIDEO_MEDIA_TOO_BIG_PHRASES,
    VIDEO_MEDIA_UNAVAILABLE_PHRASES,
    VIDEO_NO_SPEECH_PHRASES,
    YOUTUBE_ERROR_PHRASES,
)
from services.video_cascade_client import VideoLevelError
from SmartModule.service import (
    EmptyTranscript,
    TranscriptionUnavailable,
)

CHAT_ID = -1001234567890
USER_ID = 111
MEDIA_MSG_ID = 77
YT_ID = "dQw4w9WgXcQ"

_LONG_TEXT = ("длинная речь в ролике, которой достаточно для честной выжимки "
              "и пересказа, потому что здесь действительно много слов, "
              "вот так вот, да.")


def _msg(text=None, caption=None, message_id=11, user_id=USER_ID,
         video=None, document=None, voice=None, video_note=None,
         reply_to_message=None, forward_origin=None):
    m = MagicMock()
    m.text = text
    m.caption = caption
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.from_user.username = "vasya"
    m.from_user.first_name = "Вася"
    m.from_user.last_name = None
    m.reply_to_message = reply_to_message
    m.forward_origin = forward_origin
    m.video = video
    m.document = document
    m.voice = voice
    m.video_note = video_note
    return m


def _media(**kw):
    return MagicMock(**kw)


class _FakeDownloader:
    """VideoDownloader-заглушка: пишет файл в tmp_path и отдаёт путь."""

    def __init__(self, tmp_path, error=None, too_big=False, size_mb=None):
        self.tmp = Path(tmp_path)
        self.error = error
        self.too_big = too_big
        self.size_mb = size_mb          # явный размер файла (МБ)
        self.downloaded = []

    @property
    def busy(self):
        return False

    async def download(self, url, quality, progress_cb=None):
        if self.error is not None:
            raise self.error
        self.downloaded.append(url)
        path = self.tmp / f"vd_{len(self.downloaded)}.mp4"
        if self.too_big:
            size = 200 * 1024 * 1024
        elif self.size_mb is not None:
            size = self.size_mb * 1024 * 1024
        else:
            size = 1024
        path.write_bytes(b"0" * size)
        return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """DI окружения: сервис (cascade/transcript/engine-моки), транскрайбер,
    downloader; медиа-шара выключена по умолчанию (честный STT-фолбек)."""
    old = (yt._service, yt._media_transcriber, yt._media_db,
           yt._media_memory, yt._media_bot_id, yt._media_downloader)
    svc = MagicMock()
    svc.summarize_cascade = AsyncMock(return_value="выжимка урл")
    svc.summarize_transcript = AsyncMock(return_value="выжимка файла")
    svc.summarize_media_url = AsyncMock(return_value="выжимка по кадрам")
    engine = MagicMock()
    engine.fetch_transcript = AsyncMock(return_value="[00:01] привет мир")
    svc.engine = engine
    transcriber = MagicMock()
    transcriber.transcribe_voice = AsyncMock(return_value=_LONG_TEXT)
    transcriber.available = True
    downloader = _FakeDownloader(tmp_path)
    yt.setup_youtube(svc)
    yt.setup_youtube_video_media(transcriber, None, None, None,
                                 bot_id=999, downloader=downloader)
    db = MagicMock()
    db.update_smart_message_text = AsyncMock(return_value=1)
    db.save_smart_message = AsyncMock(return_value=1)
    memory = MagicMock()
    memory.memorize_facts = AsyncMock()
    monkeypatch.setattr(yt, "_media_db", db)
    monkeypatch.setattr(yt, "_media_memory", memory)
    old_cache = hot.get_config_cache()
    hot.set_config_cache(None)
    monkeypatch.setattr(yt.media_share, "enabled", lambda: False)
    yield svc, transcriber, db, memory, downloader
    (yt._service, yt._media_transcriber, yt._media_db, yt._media_memory,
     yt._media_bot_id, yt._media_downloader) = old
    hot.set_config_cache(old_cache)


def _bot():
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=500))
    bot.set_message_reaction = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.get_file = AsyncMock()
    bot.download = AsyncMock()
    return bot


def _setup_bot_download(tmp_path, monkeypatch):
    """mkstemp → tmp_path (чтобы fetch писал в реальный файл)."""
    created = []

    def _mkstemp(prefix="yv_", suffix=""):
        path = os.path.join(str(tmp_path), f"{prefix}x{suffix}")
        path = path if not os.path.exists(path) else path + "2"
        with open(path, "wb") as fh:
            fh.write(b"videodata")
        created.append(path)
        return os.open(path, os.O_RDONLY), path

    monkeypatch.setattr(yt.tempfile, "mkstemp", _mkstemp)
    return created


@pytest.fixture
def yv_cleanup():
    yield
    yt._service = None
    yt._media_transcriber = None
    yt._media_db = None
    yt._media_memory = None
    yt._media_bot_id = None
    yt._media_downloader = None
    try:
        yt._cooldown._last.clear()
    except AttributeError:
        pass


# ── 1. Классификация kind × mode (AC-B3) ──────────────────────────────

class TestClassification:
    def test_reply_media_native(self, yv_cleanup):
        target = _msg(message_id=MEDIA_MSG_ID, video=_media(file_id="f"))
        msg = _msg(text="че за видос", reply_to_message=target)
        req = yt._classify_video_request(msg)
        assert req.kind == "native" and req.mode == "summary"
        assert req.media.source is target

    def test_own_video_caption_trigger(self, yv_cleanup):
        msg = _msg(text=None, caption="транскрипт", video=_media(file_id="f"))
        req = yt._classify_video_request(msg)
        assert req.kind == "native" and req.mode == "transcript"

    def test_youtube_url_message(self, yv_cleanup):
        msg = _msg(text=f"че за видос https://youtu.be/{YT_ID}")
        req = yt._classify_video_request(msg)
        assert req.kind == "youtube" and req.mode == "summary"
        assert req.video_id == YT_ID

    def test_youtube_url_in_reply_target_priority(self, yv_cleanup):
        target = _msg(text=f"https://youtu.be/{YT_ID}", message_id=MEDIA_MSG_ID)
        msg = _msg(text="транскрипт", reply_to_message=target)
        req = yt._classify_video_request(msg)
        assert req.kind == "youtube" and req.mode == "transcript"

    def test_direct_media_url(self, yv_cleanup):
        msg = _msg(text="че за видос https://cdn.example.com/clip.mp4")
        req = yt._classify_video_request(msg)
        assert req.kind == "direct_url" and req.mode == "summary"
        assert req.url == "https://cdn.example.com/clip.mp4"

    def test_direct_url_in_reply(self, yv_cleanup):
        target = _msg(text="https://cdn.example.com/трейлер.mov", message_id=5)
        msg = _msg(text="перескажи видос", reply_to_message=target)
        req = yt._classify_video_request(msg)
        assert req.kind == "direct_url"
        assert req.url == "https://cdn.example.com/трейлер.mov"

    def test_platform_url_tiktok(self, yv_cleanup):
        msg = _msg(text="че за видос https://www.tiktok.com/@x/video/123")
        req = yt._classify_video_request(msg)
        assert req.kind == "platform_url"
        assert "tiktok.com" in req.url

    def test_platform_url_vk_and_instagram(self, yv_cleanup):
        for url in ("https://vk.com/video-123_456",
                    "https://www.instagram.com/reel/ABC/"):
            msg = _msg(text=f"транскрипт {url}")
            req = yt._classify_video_request(msg)
            assert req.kind == "platform_url", url
            assert req.mode == "transcript"

    def test_video_plus_youtube_url_prefers_url(self, yv_cleanup):
        msg = _msg(text=f"че за видос https://youtu.be/{YT_ID}",
                   video=_media(file_id="f"))
        req = yt._classify_video_request(msg)
        assert req.kind == "youtube"            # URL выше native (FR-2)

    def test_trigger_without_url_or_media_unhandled(self, yv_cleanup):
        assert yt._classify_video_request(_msg(text="поясни за видос")) is None

    def test_voice_video_note_not_classified(self, yv_cleanup):
        for attr in ("voice", "video_note"):
            req = yt._classify_video_request(
                _msg(text="транскрипт", **{attr: _media()}))
            assert req is None, attr

    def test_no_trigger_unhandled(self, yv_cleanup):
        assert yt._classify_video_request(_msg(text="просто текст")) is None
        assert yt._classify_video_request(
            _msg(text="просто текст https://youtu.be/x" + "a" * 9)) is None

    def test_unknown_web_url_unhandled(self, yv_cleanup):
        msg = _msg(text="че за видос https://example.com/page")
        assert yt._classify_video_request(msg) is None


# ── 2. youtube+transcript: субтитры / скачивание+STT (T-690) ───────────

class TestYoutubeTranscriptMode:
    @pytest.mark.asyncio
    async def test_subtitles_text_sent_html(self, env, monkeypatch, yv_cleanup):
        svc, transcriber, db, memory, dl = env
        bot = _bot()
        msg = _msg(text=f"транскрипт https://youtu.be/{YT_ID}")
        await yt.youtube_handler(msg, bot=bot)
        svc.engine.fetch_transcript.assert_awaited_once_with(
            YT_ID, 20000, on_retry=None)
        sent = bot.send_message.await_args
        assert sent.args[1] == ("<b>Вася</b> 🗣: "
                                "<i>[00:01] привет мир</i>")
        assert sent.kwargs["parse_mode"] == "HTML"
        assert sent.kwargs["reply_to_message_id"] == 11
        # URL-режим: L1-обновления нет, memorize — есть
        db.update_smart_message_text.assert_not_called()
        await asyncio.sleep(0)
        args, kwargs = memory.memorize_facts.call_args
        assert kwargs["source_type"] == "video_transcript"
        assert 'sender="Вася"' in args[1]
        # smart_cache не пишем (кэш только для summary)
        svc.summarize_cascade.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_subtitles_unavailable_download_stt(self, env, monkeypatch,
                                                      yv_cleanup):
        svc, transcriber, db, memory, dl = env
        svc.engine.fetch_transcript = AsyncMock(
            side_effect=Exception("нет субтитров"))
        bot = _bot()
        msg = _msg(text=f"транскрипт https://youtu.be/{YT_ID}")
        await yt.youtube_handler(msg, bot=bot)
        assert dl.downloaded == [f"https://www.youtube.com/watch?v={YT_ID}"]
        transcriber.transcribe_voice.assert_awaited()
        sent = bot.send_message.await_args
        assert f"<i>{_LONG_TEXT}</i>" in sent.args[1]

    @pytest.mark.asyncio
    async def test_download_busy_honest_phrase(self, env, monkeypatch,
                                               yv_cleanup):
        svc, transcriber, db, memory, dl = env
        svc.engine.fetch_transcript = AsyncMock(
            side_effect=Exception("нет субтитров"))
        from tools.video_downloader import DownloadBusyError
        dl.error = DownloadBusyError("занято")
        bot = _bot()
        msg = _msg(text=f"транскрипт https://youtu.be/{YT_ID}")
        await yt.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_UNAVAILABLE_PHRASES


# ── fix-round 04.09 (m5): кламп STT-таймаута при PG=0 ──────────────────

class TestSttTimeoutClamp:
    def test_pg_zero_clamped_to_settings_default(self, monkeypatch):
        """Явный 0 в PG (limits.video_stt_timeout_seconds) не даёт timeout=0
        (иначе мгновенный TimeoutError) — кламп настройкой-дефолтом."""
        old_cache = hot.get_config_cache()
        hot.set_config_cache(None)

        def _fake_get(key, default=None):
            return 0 if key == "limits.video_stt_timeout_seconds" else default

        monkeypatch.setattr(hot, "get", _fake_get)
        try:
            assert yt._stt_timeout() == settings.VIDEO_STT_TIMEOUT_SECONDS
        finally:
            hot.set_config_cache(old_cache)


# ── 3. direct_url / platform_url × summary/transcript (AC-B4) ──────────

_DIRECT = "https://cdn.example.com/clip.mp4"
_PLATFORM = "https://www.tiktok.com/@x/video/1234567890"


class TestUrlSummaryFlows:
    @pytest.mark.asyncio
    async def test_direct_url_multimodal_on_external_url(self, env, yv_cleanup):
        """direct_url+summary: L1/L2 сразу по внешней ссылке (без скачивания)."""
        svc, transcriber, db, memory, dl = env
        bot = _bot()
        msg = _msg(text=f"че за видос {_DIRECT}")
        await yt.youtube_handler(msg, bot=bot)
        svc.summarize_media_url.assert_awaited_once()
        call = svc.summarize_media_url.await_args.kwargs
        assert call["video_url"] == _DIRECT
        assert dl.downloaded == []               # мультимодалка успела
        assert bot.send_message.await_args.args[1] == "выжимка по кадрам"
        await asyncio.sleep(0)
        memory.memorize_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_direct_url_fallback_download_publish_stt(self, env,
                                                            monkeypatch,
                                                            yv_cleanup):
        """Провал внешней мультимодалки → скачать → опубликовать → L1/L2 по
        /media (тоже пуст) → STT-фолбек → выжимка по транскрипту + память."""
        svc, transcriber, db, memory, dl = env
        svc.summarize_media_url = AsyncMock(
            side_effect=VideoLevelError("level empty"))
        monkeypatch.setattr(yt.media_share, "enabled", lambda: True)
        published = []
        monkeypatch.setattr(yt.media_share, "publish_media_file",
                            AsyncMock(side_effect=async_publish(published)))
        monkeypatch.setattr(yt.media_share, "delete_file", AsyncMock())
        bot = _bot()
        msg = _msg(text=f"че за видос {_DIRECT}")
        await yt.youtube_handler(msg, bot=bot)
        assert dl.downloaded == [_DIRECT]        # скачали после провала
        assert len(published) == 1               # опубликовали
        # вторая попытка каскада шла ПО опубликованному /media-URL
        calls = svc.summarize_media_url.await_args_list
        assert len(calls) == 2
        assert calls[1].kwargs["video_url"].startswith(
            "https://admin-bot.duckdns.org/media/")
        # L1/L2 на /media тоже пуст → STT → выжимка по транскрипту
        transcriber.transcribe_voice.assert_awaited()
        svc.summarize_transcript.assert_awaited_once()
        assert bot.send_message.await_args.args[1] == "выжимка файла"
        # URL-режим: только memorize (L1-обновления нет)
        await asyncio.sleep(0)
        args, kwargs = memory.memorize_facts.call_args
        assert kwargs["source_type"] == "video_transcript"

    @pytest.mark.asyncio
    async def test_direct_url_summary_60mb_file_publishes_multimodal(
            self, env, monkeypatch, yv_cleanup):
        """fix-round 04.09 (M2): скачанный файл 60 МБ (50МБ < размер < потолка
        публикации 200МБ) НЕ отсекается от мультимодалки — publish_media_file
        вызван, summarize_media_url по /media вызван (STT-гейт 50МБ к
        публикации неприменим)."""
        svc, transcriber, db, memory, dl = env
        dl.size_mb = 60
        svc.summarize_media_url = AsyncMock(
            side_effect=[VideoLevelError("external level empty"),
                         "выжимка по кадрам 60мб"])
        monkeypatch.setattr(yt.media_share, "enabled", lambda: True)
        published = []
        monkeypatch.setattr(yt.media_share, "publish_media_file",
                            AsyncMock(side_effect=async_publish(published)))
        monkeypatch.setattr(yt.media_share, "delete_file", AsyncMock())
        bot = _bot()
        msg = _msg(text=f"че за видос {_DIRECT}")
        await yt.youtube_handler(msg, bot=bot)
        assert len(published) == 1                  # 60 МБ — опубликован
        calls = svc.summarize_media_url.await_args_list
        assert len(calls) == 2                      # внешний URL + /media
        assert calls[1].kwargs["video_url"].startswith(
            "https://admin-bot.duckdns.org/media/")
        assert bot.send_message.await_args.args[1] == "выжимка по кадрам 60мб"
        transcriber.transcribe_voice.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_platform_summary_download_publish_cascade(self, env,
                                                             monkeypatch,
                                                             yv_cleanup):
        """platform_url+summary: сразу скачивание → публикация → L1/L2."""
        svc, transcriber, db, memory, dl = env
        monkeypatch.setattr(yt.media_share, "enabled", lambda: True)
        monkeypatch.setattr(yt.media_share, "publish_media_file",
                            AsyncMock(side_effect=async_publish([])))
        monkeypatch.setattr(yt.media_share, "delete_file", AsyncMock())
        bot = _bot()
        msg = _msg(text=f"че за видос {_PLATFORM}")
        await yt.youtube_handler(msg, bot=bot)
        assert dl.downloaded == [_PLATFORM]
        call = svc.summarize_media_url.await_args.kwargs
        assert call["video_url"].startswith("https://admin-bot.duckdns.org/media/")
        assert call["label"] == "platform-url"
        assert bot.send_message.await_args.args[1] == "выжимка по кадрам"

    @pytest.mark.asyncio
    async def test_url_summary_stt_fallback_with_honest_phrase(self, env,
                                                               monkeypatch,
                                                               yv_cleanup):
        """Публикация недоступна + STT вернул «немой» транскрипт → 5.13."""
        svc, transcriber, db, memory, dl = env
        svc.summarize_media_url = AsyncMock(
            side_effect=VideoLevelError("no openrouter key"))
        transcriber.transcribe_voice = AsyncMock(return_value="пара слов")
        bot = _bot()
        msg = _msg(text=f"че за видос {_PLATFORM}")
        await yt.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_NO_SPEECH_PHRASES
        svc.summarize_transcript.assert_not_awaited()
        await asyncio.sleep(0)
        memory.memorize_facts.assert_not_called()


class TestUrlTranscriptFlows:
    @pytest.mark.asyncio
    async def test_direct_url_transcript_download_stt_html(self, env,
                                                           yv_cleanup):
        svc, transcriber, db, memory, dl = env
        bot = _bot()
        msg = _msg(text=f"транскрипт {_DIRECT}")
        await yt.youtube_handler(msg, bot=bot)
        assert dl.downloaded == [_DIRECT]
        transcriber.transcribe_voice.assert_awaited()
        sent = bot.send_message.await_args
        assert sent.args[1] == f"<b>Вася</b> 🗣: <i>{_LONG_TEXT}</i>"
        assert sent.kwargs["parse_mode"] == "HTML"
        await asyncio.sleep(0)
        args, kwargs = memory.memorize_facts.call_args
        assert kwargs["source_type"] == "video_transcript"

    @pytest.mark.asyncio
    async def test_platform_transcript_download_stt_html(self, env, yv_cleanup):
        svc, transcriber, db, memory, dl = env
        bot = _bot()
        msg = _msg(text=f"транскрипт {_PLATFORM}")
        await yt.youtube_handler(msg, bot=bot)
        assert dl.downloaded == [_PLATFORM]
        transcriber.transcribe_voice.assert_awaited()
        sent = bot.send_message.await_args
        # fix-round 04.09 (m7): ужесточено — платформенная ветка идёт тем же
        # путём (download → STT → HTML-текст кружков), что и direct_url
        assert sent.args[1] == f"<b>Вася</b> 🗣: <i>{_LONG_TEXT}</i>"
        assert sent.kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_url_transcript_download_too_big_5_10(self, env, monkeypatch,
                                                        yv_cleanup):
        svc, transcriber, db, memory, dl = env
        dl.too_big = True                          # 200 МБ файл
        bot = _bot()
        msg = _msg(text=f"транскрипт {_PLATFORM}")
        await yt.youtube_handler(msg, bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in VIDEO_MEDIA_TOO_BIG_PHRASES
        transcriber.transcribe_voice.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_url_transcript_stt_empty_5_12(self, env, yv_cleanup):
        svc, transcriber, db, memory, dl = env
        transcriber.transcribe_voice = AsyncMock(
            side_effect=EmptyTranscript("vd_1.mp4"))
        bot = _bot()
        msg = _msg(text=f"транскрипт {_DIRECT}")
        await yt.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in VIDEO_MEDIA_EMPTY_PHRASES


# ── 4. native+summary: мультимодалка через /media, честная выжимка ─────

class TestNativeSummary:
    @pytest.mark.asyncio
    async def test_native_summary_publish_cascade_then_memory(self, env,
                                                              monkeypatch,
                                                              tmp_path,
                                                              yv_cleanup):
        svc, transcriber, db, memory, dl = env
        monkeypatch.setattr(yt.media_share, "enabled", lambda: True)
        published = []
        monkeypatch.setattr(yt.media_share, "publish_media_file",
                            AsyncMock(side_effect=async_publish(published)))
        monkeypatch.setattr(yt.media_share, "delete_file", AsyncMock())
        _setup_bot_download(tmp_path, monkeypatch)
        bot = _bot()
        msg = _msg(text="че за видос", video=_media(file_id="fid"))
        await yt.youtube_handler(msg, bot=bot)
        call = svc.summarize_media_url.await_args.kwargs
        assert call["video_url"].startswith("https://admin-bot.duckdns.org/media/")
        assert call["label"] == "tg-file"
        assert bot.send_message.await_args.args[1] == "выжимка по кадрам"
        # память в мультимодальном успехе без STT не инжектится (нет сырого
        # текста для факт-экстрактора)
        await asyncio.sleep(0)
        memory.memorize_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_native_summary_cascade_fail_stt_fallback(self, env,
                                                            monkeypatch,
                                                            tmp_path,
                                                            yv_cleanup):
        """Провал каскада на /media → STT → выжимка по транскрипту + память."""
        svc, transcriber, db, memory, dl = env
        monkeypatch.setattr(yt.media_share, "enabled", lambda: True)
        published = []
        monkeypatch.setattr(yt.media_share, "publish_media_file",
                            AsyncMock(side_effect=async_publish(published)))
        monkeypatch.setattr(yt.media_share, "delete_file", AsyncMock())
        svc.summarize_media_url = AsyncMock(
            side_effect=VideoLevelError("empty"))
        _setup_bot_download(tmp_path, monkeypatch)
        bot = _bot()
        msg = _msg(text="че за видос", video=_media(file_id="fid"))
        await yt.youtube_handler(msg, bot=bot)
        transcriber.transcribe_voice.assert_awaited()
        svc.summarize_transcript.assert_awaited_once()
        kwargs = svc.summarize_transcript.await_args.kwargs
        assert kwargs["chat_id"] == CHAT_ID
        assert "rag_query" not in kwargs
        assert kwargs["transcript"] == _LONG_TEXT
        assert bot.send_message.await_args.args[1] == "выжимка файла"
        # двойная инъекция (native): update + memorize
        db.update_smart_message_text.assert_awaited()
        await asyncio.sleep(0)
        args, kwargs2 = memory.memorize_facts.call_args
        assert kwargs2["source_type"] == "video_transcript"

    @pytest.mark.asyncio
    async def test_native_summary_no_publish_stt_fallback(self, env,
                                                          monkeypatch,
                                                          tmp_path,
                                                          yv_cleanup):
        """Публикация выключена → прежний STT-путь Части 1 (выжимка по тексту)."""
        svc, transcriber, db, memory, dl = env
        _setup_bot_download(tmp_path, monkeypatch)
        bot = _bot()
        msg = _msg(text="че за видос", video=_media(file_id="fid"))
        await yt.youtube_handler(msg, bot=bot)
        svc.summarize_media_url.assert_not_awaited()
        transcriber.transcribe_voice.assert_awaited()
        assert bot.send_message.await_args.args[1] == "выжимка файла"

    @pytest.mark.asyncio
    async def test_native_summary_honest_phrase_on_mute_video(self, env,
                                                              monkeypatch,
                                                              tmp_path,
                                                              yv_cleanup):
        """02:45-кейс: STT вернул 29 символов → фраза 5.13, БЕЗ выжимки/RAG."""
        svc, transcriber, db, memory, dl = env
        transcriber.transcribe_voice = AsyncMock(
            return_value="короткая фраза без смысла и контекста")
        svc.summarize_transcript = AsyncMock(return_value="выжимка файла")
        _setup_bot_download(tmp_path, monkeypatch)
        bot = _bot()
        msg = _msg(text="че за видос", video=_media(file_id="fid"))
        await yt.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in VIDEO_NO_SPEECH_PHRASES
        svc.summarize_transcript.assert_not_awaited()
        memory.memorize_facts.assert_not_called()
        db.update_smart_message_text.assert_not_called()


# ── 5. B8: отсутствующая строка smart_messages (T-694) ────────────────

def async_publish(published):
    async def _publish(src, ttl):
        ticket = ShareTicket(
            file_id="f" * 32 + ".mp4", expires=1, sig="s",
            rel_url=f"/media/{'f' * 32}.mp4?e=1&s=s",
            abs_url=f"https://admin-bot.duckdns.org/media/{'f' * 32}.mp4?e=1&s=s")
        published.append(ticket)
        return ticket
    return _publish


class TestSmartMessageRowFallback:
    @pytest.mark.asyncio
    async def test_user_media_row_created(self, env, monkeypatch, tmp_path,
                                          yv_cleanup):
        svc, transcriber, db, memory, dl = env
        db.update_smart_message_text = AsyncMock(return_value=0)  # строки нет
        _setup_bot_download(tmp_path, monkeypatch)
        bot = _bot()
        msg = _msg(text="транскрипт", video=_media(file_id="fid"),
                   user_id=USER_ID)
        await yt.youtube_handler(msg, bot=bot)
        db.save_smart_message.assert_awaited_once()
        call = db.save_smart_message.await_args.kwargs
        assert call["user_id"] == USER_ID
        assert call["chat_id"] == CHAT_ID
        assert call["media_type"] == "video"
        assert call["message_id"] == 11

    @pytest.mark.asyncio
    async def test_bot_media_row_skipped_with_info(self, env, monkeypatch,
                                                   tmp_path, yv_cleanup):
        """Строки нет + медиа от БОТА → skip L1 (INFO), факт всё равно."""
        svc, transcriber, db, memory, dl = env
        db.update_smart_message_text = AsyncMock(return_value=0)
        db.save_smart_message = AsyncMock()
        _setup_bot_download(tmp_path, monkeypatch)
        bot = _bot()
        msg = _msg(text="транскрипт", video=_media(file_id="fid"), user_id=999)
        await yt.youtube_handler(msg, bot=bot)
        db.save_smart_message.assert_not_called()
        await asyncio.sleep(0)
        assert memory.memorize_facts.await_count >= 0
        args, kwargs = memory.memorize_facts.call_args
        assert kwargs["source_type"] == "video_transcript"


# ── 6. Изоляция / общие фразы (NFR-6) ─────────────────────────────────

class TestRouterIsolation:
    @pytest.mark.asyncio
    async def test_voice_note_not_consumed_by_router(self, env, yv_cleanup):
        svc, transcriber, db, memory, dl = env
        bot = _bot()
        msg = _msg(text="че за видос", video_note=_media())
        result = await yt.youtube_handler(msg, bot=bot)
        assert result is UNHANDLED
        transcriber.transcribe_voice.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_media_or_url_unhandled_propagation(self, env, yv_cleanup):
        bot = _bot()
        msg = _msg(text="поясни за видос")
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_stt_unavailable_phrase_and_no_crash(self, env, monkeypatch,
                                                       tmp_path, yv_cleanup):
        svc, transcriber, db, memory, dl = env
        transcriber.transcribe_voice = AsyncMock(
            side_effect=TranscriptionUnavailable("yv_x.mp4"))
        _setup_bot_download(tmp_path, monkeypatch)
        bot = _bot()
        msg = _msg(text="транскрипт", video=_media(file_id="fid"))
        await yt.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in \
            VIDEO_MEDIA_UNAVAILABLE_PHRASES

    @pytest.mark.asyncio
    async def test_unexpected_error_replies_llm_phrase(self, env, monkeypatch,
                                                       tmp_path, yv_cleanup):
        svc, transcriber, db, memory, dl = env
        svc.summarize_transcript = AsyncMock(
            side_effect=RuntimeError("взрыв"))
        _setup_bot_download(tmp_path, monkeypatch)
        bot = _bot()
        msg = _msg(text="че за видос", video=_media(file_id="fid"))
        await yt.youtube_handler(msg, bot=bot)
        assert bot.send_message.await_args.args[1] in LLM_ERROR_PHRASES
