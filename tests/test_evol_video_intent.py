"""EVOL §4 — единое видео-намерение: 8 контрактных сценариев (офлайн).

Покрывает подтверждённый пользовательский сценарий §4.1 (просьба о выжимке →
отдельным сообщением пересланный ролик), приоритеты источника §4.2, поздний
приход медиа/истечение TTL §4.3, маршрутизацию/single-flight §4.4 и
наблюдаемость по correlation_id §4.5.

Никаких живых отправок в Telegram: bot — AsyncMock, все внешние границы
(скачивание файла, публикация /media, LLM/STT) — моки.
"""
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from handlers import video_download as vd
from handlers import youtube as yt
from services import video_intent
from services.smartmodule_phrases import (
    VIDEO_INTENT_AMBIGUOUS_PHRASES,
    VIDEO_INTENT_EXPIRED_PHRASES,
    VIDEO_MEDIA_UNAVAILABLE_PHRASES,
)

CHAT_ID = -1001234567890
OTHER_CHAT = -1009999999999
USER_A = 111
USER_B = 222
BOT_ID = 999

_LONG_TRANSCRIPT = ("в ролике подробно рассказывают про подготовку, тренировки "
                    "и питание, объясняют план на сезон и разбирают ошибки, "
                    "которые мешают прогрессу в первые месяцы.")


# ── Хелперы ──────────────────────────────────────────────────────────

def _media(file_id="f1", file_unique_id="u1", **kw):
    data = {"file_id": file_id, "file_unique_id": file_unique_id,
            "duration": 12, "file_size": 1024, "mime_type": "video/mp4",
            "file_name": None}
    data.update(kw)
    return SimpleNamespace(**data)


def _msg(text=None, caption=None, message_id=11, user_id=USER_A,
         chat_id=CHAT_ID, video=None, document=None, voice=None,
         video_note=None, reply_to_message=None, forward_origin=None,
         thread_id=None, chat_type="group"):
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
    m.reply = AsyncMock(return_value=MagicMock(message_id=900))
    return m


def _bot():
    bot = AsyncMock()

    async def _download(file_id, destination=None):
        Path(destination).write_bytes(b"videodata")

    bot.download = AsyncMock(side_effect=_download)
    bot.get_file = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=500))
    bot.send_video = AsyncMock(return_value=MagicMock(message_id=501))
    bot.send_document = AsyncMock(return_value=MagicMock(message_id=502))
    bot.set_message_reaction = AsyncMock()
    bot.send_chat_action = AsyncMock()
    return bot


def _flags(monkeypatch, **overrides):
    """hot.get: переопределённые ключи, остальные — реальный дефолт."""
    real_get = yt.hot.get

    def _get(key, default=None):
        if key in overrides:
            return overrides[key]
        return real_get(key, default)

    monkeypatch.setattr(yt.hot, "get", _get)


@pytest.fixture
def env(monkeypatch):
    """DI youtube-модуля + моки внешних границ (публикация, LLM, STT, fetch)."""
    svc = MagicMock()
    svc.video_client = MagicMock(available=True)
    svc.summarize_media_url = AsyncMock(return_value="выжимка по видео")
    svc.summarize_transcript = AsyncMock(return_value="выжимка по транскрипту")
    svc.summarize_cascade = AsyncMock(return_value="выжимка по субтитрам")
    svc.engine = MagicMock()
    svc.engine.fetch_transcript = AsyncMock(return_value="")
    yt.setup_youtube(svc)

    transcriber = MagicMock()
    transcriber.transcribe_voice = AsyncMock(return_value=_LONG_TRANSCRIPT)
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
    _flags(monkeypatch, **{"flags.video_summary_enabled": True,
                           "flags.download_enabled": True,
                           "limits.youtube_cooldown_seconds": 0})
    yt._cooldown._last.clear()
    yield SimpleNamespace(svc=svc, transcriber=transcriber)
    yt._service = None
    yt._media_transcriber = None
    yt._media_db = None
    yt._media_memory = None
    yt._media_bot_id = None
    yt._media_downloader = None
    yt._cooldown._last.clear()


def _events(name, correlation_id=None):
    return [e for e in video_intent.recent_events()
            if e["event"] == name
            and (correlation_id is None or e["correlation_id"] == correlation_id)]


def _corr_of_pending(chat_id=CHAT_ID):
    pending = video_intent.pending_for(chat_id)
    assert pending, "ожидание медиа не создано"
    return pending[0].vintent.correlation_id


# ── 1. Просьба → отдельным update пересланный ролик ───────────────────

class TestLateVideo:
    @pytest.mark.asyncio
    async def test_request_then_forwarded_video_one_analysis_one_reply(self, env):
        bot = _bot()
        request = _msg(text="Бот, сделай выжимку видео", message_id=100)

        result = await yt.youtube_handler(request, bot=bot)
        assert result is None                      # консьюм: в LLM не уходит
        assert bot.send_message.await_count == 0   # мгновенного «видео нет» нет
        corr = _corr_of_pending()
        assert _events("waiting_for_media", corr)

        forwarded = _msg(
            message_id=101,
            video=_media(file_id="fwd", file_unique_id="fwd_u"),
            forward_origin=SimpleNamespace(type="channel"))
        result = await yt.youtube_handler(forwarded, bot=bot)

        assert result is None                       # медиа потреблено
        assert env.svc.summarize_media_url.await_count == 1
        assert bot.send_message.await_count == 1    # РОВНО один ответ
        assert bot.send_message.await_args.kwargs.get("reply_to_message_id") == 101
        assert not video_intent.has_pending(CHAT_ID)

        names = [e["event"] for e in video_intent.recent_events()
                 if e["correlation_id"] == corr]
        assert names == ["request_seen", "waiting_for_media", "media_matched",
                         "request_seen", "analysis_started",
                         "multimodal_success", "delivered"]

    @pytest.mark.asyncio
    async def test_no_raw_refs_in_events(self, env):
        bot = _bot()
        await yt.youtube_handler(
            _msg(text="Бот, сделай выжимку видео", message_id=100), bot=bot)
        await yt.youtube_handler(
            _msg(message_id=101, video=_media(file_id="secret_file_id",
                                              file_unique_id="secret_uid")),
            bot=bot)
        dumped = json.dumps(video_intent.recent_events(), ensure_ascii=False)
        assert "secret_file_id" not in dumped
        assert "secret_uid" not in dumped
        assert "https://" not in dumped


# ── 2. Медиа ДО запроса ───────────────────────────────────────────────

class TestMediaBeforeRequest:
    @pytest.mark.asyncio
    async def test_video_before_request_binds_from_window(self, env):
        bot = _bot()
        video = _msg(message_id=200, video=_media(file_id="v200",
                                                  file_unique_id="u200"))
        assert await yt.youtube_handler(video, bot=bot) is UNHANDLED
        assert bot.send_message.await_count == 0

        request = _msg(text="Бот, че за видос", message_id=201)
        assert await yt.youtube_handler(request, bot=bot) is None
        assert env.svc.summarize_media_url.await_count == 1
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.kwargs.get("reply_to_message_id") == 200
        matched = _events("media_matched")
        assert matched and matched[-1]["reason_code"] == "window_before_request"


# ── 3. Прямой reply на видео приоритетнее соседей ─────────────────────

class TestReplyPriority:
    def test_reply_media_wins_over_window(self, env):
        video_intent.observe(_msg(message_id=300, video=_media(
            file_id="a300", file_unique_id="ua300")))
        target = _msg(message_id=302, video=_media(file_id="b302",
                                                   file_unique_id="ub302"))
        request = _msg(text="Бот, сделай выжимку", message_id=303,
                       reply_to_message=target)
        vintent = video_intent.resolve_request(request, video_intent.SUMMARY)
        assert vintent.resolution == video_intent.RESOLVED
        assert vintent.reason_code == video_intent.REASON_REPLY_MEDIA
        assert vintent.media_tg_message_id == 302
        assert vintent.source_ref == "ub302"

    @pytest.mark.asyncio
    async def test_handler_replies_to_quoted_video(self, env):
        bot = _bot()
        video_intent.observe(_msg(message_id=300, video=_media(
            file_id="a300", file_unique_id="ua300")))
        target = _msg(message_id=302, video=_media(file_id="b302",
                                                   file_unique_id="ub302"))
        request = _msg(text="Бот, сделай выжимку", message_id=303,
                       reply_to_message=target)
        assert await yt.youtube_handler(request, bot=bot) is None
        assert env.svc.summarize_media_url.await_count == 1
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.kwargs.get("reply_to_message_id") == 302


# ── 4. Два участника, один ролик → single-flight ──────────────────────

class TestSingleFlight:
    @pytest.mark.asyncio
    async def test_two_users_same_video_one_analysis_one_reply(self, env,
                                                              monkeypatch):
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow(chat_id, video_url, label):
            started.set()
            await release.wait()
            return "выжимка по видео"

        env.svc.summarize_media_url = AsyncMock(side_effect=_slow)
        bot = _bot()
        target = _msg(message_id=400, video=_media(file_id="same",
                                                   file_unique_id="usame"))
        first = _msg(text="Бот, сделай выжимку", message_id=401,
                     user_id=USER_A, reply_to_message=target)
        second = _msg(text="Бот, че за видос", message_id=402,
                      user_id=USER_B, reply_to_message=target)

        task = asyncio.create_task(yt.youtube_handler(first, bot=bot))
        await started.wait()
        joined = await yt.youtube_handler(second, bot=bot)
        assert joined is None                       # присоединились, не дублируем
        release.set()
        await task

        assert env.svc.summarize_media_url.await_count == 1
        assert bot.send_message.await_count == 1    # один исходящий итог
        assert _events("joined_existing_job")


# ── 5. Два разных ролика рядом → ambiguous ────────────────────────────

class TestAmbiguous:
    @pytest.mark.asyncio
    async def test_two_videos_ambiguous_no_random_pick(self, env):
        bot = _bot()
        video_intent.observe(_msg(message_id=500, video=_media(
            file_id="v500", file_unique_id="u500")))
        video_intent.observe(_msg(message_id=501, video=_media(
            file_id="v501", file_unique_id="u501")))

        request = _msg(text="Бот, сделай выжимку видео", message_id=502)
        assert await yt.youtube_handler(request, bot=bot) is None
        assert env.svc.summarize_media_url.await_count == 0
        assert env.transcriber.transcribe_voice.await_count == 0
        assert bot.send_message.await_count == 1
        assert (bot.send_message.await_args.args[1]
                in VIDEO_INTENT_AMBIGUOUS_PHRASES)
        assert _events("media_ambiguous")


# ── 6. «Скачай» ≠ «сделай выжимку» ────────────────────────────────────

class TestOperations:
    @pytest.mark.asyncio
    async def test_summary_sends_no_file(self, env):
        bot = _bot()
        target = _msg(message_id=600, video=_media(file_id="v600",
                                                   file_unique_id="u600"))
        request = _msg(text="Бот, сделай выжимку", message_id=601,
                       reply_to_message=target)
        assert await yt.youtube_handler(request, bot=bot) is None
        assert bot.send_message.await_count == 1
        assert bot.send_video.await_count == 0
        assert bot.send_document.await_count == 0

    @pytest.mark.asyncio
    async def test_download_request_is_separate_operation(self, env,
                                                          monkeypatch):
        downloader = MagicMock()
        downloader.busy = False
        downloader.download = AsyncMock(return_value=Path("x.mp4"))
        vd.setup_video_download(downloader)
        vd._cooldown._last.clear()
        _flags(monkeypatch, **{"flags.download_enabled": True,
                               "limits.download_cooldown": 0})

        async def _fetch(bot, media, path, *a, **kw):
            Path(path).write_bytes(b"videodata")

        monkeypatch.setattr("services.media_download.fetch_media_to_tmp",
                            _fetch)
        bot = _bot()
        target = _msg(message_id=610, video=_media(file_id="v610",
                                                   file_unique_id="u610"))
        request = _msg(text="Бот, скачай", message_id=611,
                       reply_to_message=target)
        result = await vd.video_download_handler(request, bot=bot)

        assert result is None
        assert bot.send_video.await_count == 1      # файл — только по «скачай»
        assert yt._service.summarize_media_url.await_count == 0
        assert _events("request_seen")
        assert any(e["intent"] == video_intent.DOWNLOAD
                   for e in _events("request_seen"))


# ── 7. Классификация источников и честный фолбэк ──────────────────────

class TestSourceClassification:
    def test_detect_intent_matrix(self):
        assert video_intent.detect_intent("Бот, сделай выжимку видео") == "summary"
        assert video_intent.detect_intent("Бот, перескажи ролик") == "summary"
        assert video_intent.detect_intent("Бот, транскрипт") == "transcript"
        assert video_intent.detect_intent("Бот, че за видос") == "describe"
        assert video_intent.detect_intent("Бот, скачай видос") == "download"
        assert video_intent.detect_intent("Бот, как дела") == "unknown"

    def test_source_kinds(self, env):
        cases = {
            "native": _msg(message_id=1, video=_media(file_id="a",
                                                      file_unique_id="a")),
            "forwarded": _msg(message_id=2, video=_media(file_id="b",
                                                         file_unique_id="b"),
                              forward_origin=SimpleNamespace(type="chat")),
            "document": _msg(message_id=3, document=_media(
                file_id="c", file_unique_id="c", mime_type="video/mp4")),
            "note": _msg(message_id=4, video_note=_media(
                file_id="d", file_unique_id="d")),
            "url": _msg(message_id=5,
                        text="https://www.tiktok.com/@x/video/123"),
        }
        expected = {
            "native": video_intent.NATIVE_VIDEO,
            "forwarded": video_intent.PLATFORM_FORWARD,
            "document": video_intent.VIDEO_DOCUMENT,
            "note": video_intent.VIDEO_NOTE,
            "url": video_intent.URL,
        }
        for name, message in cases.items():
            candidate = video_intent.candidate_of(message)
            assert candidate is not None, name
            assert candidate.source_kind == expected[name], name
        assert video_intent.candidate_of(_msg(message_id=6, text="привет")) is None

    @pytest.mark.asyncio
    async def test_video_note_honest_transcript_fallback(self, env,
                                                         monkeypatch):
        # Публикация недоступна (кружок нельзя отдать мультимодалке) → STT.
        monkeypatch.setattr(yt.media_share, "enabled", lambda: False)
        bot = _bot()
        note = _msg(message_id=700, video_note=_media(file_id="n700",
                                                      file_unique_id="un700"))
        request = _msg(text="Бот, сделай выжимку", message_id=701,
                       reply_to_message=note)
        assert await yt.youtube_handler(request, bot=bot) is None
        assert env.transcriber.transcribe_voice.await_count == 1
        assert env.svc.summarize_media_url.await_count == 0   # визуал не заявлен
        assert env.svc.summarize_transcript.await_count == 1
        assert bot.send_message.await_count == 1
        fallback = _events("transcript_fallback")
        assert fallback and fallback[-1]["reason_code"] == "audio_only_source"
        assert not _events("multimodal_success")

    @pytest.mark.asyncio
    async def test_platform_url_honest_fallback_no_file(self, env):
        bot = _bot()
        msg = _msg(text="Бот, че за видос https://www.tiktok.com/@x/video/123",
                   message_id=710)
        assert await yt.youtube_handler(msg, bot=bot) is None
        # downloader не сконфигурирован → честная фраза, файла нет
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.args[1] in VIDEO_MEDIA_UNAVAILABLE_PHRASES
        assert bot.send_video.await_count == 0
        assert bot.send_document.await_count == 0
        assert _events("failed")

    @pytest.mark.asyncio
    async def test_no_media_request_waits_instead_of_instant_refusal(self, env):
        bot = _bot()
        msg = _msg(text="Бот, сделай выжимку видео", message_id=720)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert bot.send_message.await_count == 0
        assert video_intent.has_pending(CHAT_ID)


# ── 8. Медиа не пришло / другой чат / истечение TTL ───────────────────

class TestPendingExpiry:
    @pytest.mark.asyncio
    async def test_expiry_sends_exactly_one_fallback(self, env):
        bot = _bot()
        await yt.youtube_handler(
            _msg(text="Бот, сделай выжимку видео", message_id=800), bot=bot)
        assert bot.send_message.await_count == 0

        await video_intent.expire(now=time.monotonic() + 10_000)
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.args[1] in VIDEO_INTENT_EXPIRED_PHRASES
        assert bot.send_message.await_args.kwargs.get("reply_to_message_id") == 800

        # повторный expire ничего не дублирует
        await video_intent.expire(now=time.monotonic() + 20_000)
        assert bot.send_message.await_count == 1
        assert _events("failed", None)[-1]["reason_code"] == "pending_expired"

    @pytest.mark.asyncio
    async def test_media_in_other_chat_does_not_bind(self, env):
        bot = _bot()
        await yt.youtube_handler(
            _msg(text="Бот, сделай выжимку видео", message_id=810), bot=bot)
        corr = _corr_of_pending()

        foreign = _msg(message_id=811, chat_id=OTHER_CHAT,
                       video=_media(file_id="other", file_unique_id="uother"))
        assert await yt.youtube_handler(foreign, bot=bot) is UNHANDLED
        assert video_intent.has_pending(CHAT_ID)      # ожидание не закрыто
        assert env.svc.summarize_media_url.await_count == 0
        assert not _events("media_matched", corr)

        await video_intent.expire(now=time.monotonic() + 10_000)
        assert bot.send_message.await_count == 1
        assert bot.send_message.await_args.args[0] == CHAT_ID

    @pytest.mark.asyncio
    async def test_video_after_expiry_is_new_request_not_retroactive(self, env):
        bot = _bot()
        await yt.youtube_handler(
            _msg(text="Бот, сделай выжимку видео", message_id=820), bot=bot)
        await video_intent.expire(now=time.monotonic() + 10_000)
        assert bot.send_message.await_count == 1

        # ролик пришёл ПОСЛЕ истечения: старое намерение не воскресает
        late = _msg(message_id=821, video=_media(file_id="late",
                                                 file_unique_id="ulate"))
        assert await yt.youtube_handler(late, bot=bot) is UNHANDLED
        assert env.svc.summarize_media_url.await_count == 0
        assert bot.send_message.await_count == 1


# ── 9. Review-fix: ожидание без слова «видео» и «чужая цель» ──────────

class TestWaitingWithoutVideoWord:
    """§4.5 #1 буквально: «Сделай выжимку» (без слова «видео») → ролик.

    Раньше ожидание регистрировалось только при слове «видео/видос/ролик»
    (или при уже активном ожидании) — формулировка из ТЗ уходила в LLM, а
    присланный следом ролик не привязывался (0 анализов, 0 ответов)."""

    @pytest.mark.asyncio
    async def test_literal_request_without_video_word_then_forwarded_video(
            self, env):
        bot = _bot()
        request = _msg(text="Сделай выжимку", message_id=900,
                       chat_type="private")

        assert await yt.youtube_handler(request, bot=bot) is None
        assert bot.send_message.await_count == 0        # «видео нет» не отвечаем
        corr = _corr_of_pending()

        forwarded = _msg(message_id=901, chat_type="private",
                         video=_media(file_id="fwd9", file_unique_id="fwd9u"),
                         forward_origin=SimpleNamespace(type="channel"))
        assert await yt.youtube_handler(forwarded, bot=bot) is None

        assert env.svc.summarize_media_url.await_count == 1
        assert bot.send_message.await_count == 1         # РОВНО один ответ
        assert bot.send_message.await_args.kwargs.get(
            "reply_to_message_id") == 901
        assert not video_intent.has_pending(CHAT_ID)
        names = [e["event"] for e in video_intent.recent_events()
                 if e["correlation_id"] == corr]
        assert names[0] == "request_seen"
        assert "waiting_for_media" in names and "media_matched" in names

    @pytest.mark.asyncio
    async def test_prefixed_request_without_video_word_waits(self, env):
        """«Бот, сделай выжимку» — тоже ожидание, без слова «видео»."""
        bot = _bot()
        assert await yt.youtube_handler(
            _msg(text="Бот, сделай выжимку", message_id=910), bot=bot) is None
        assert bot.send_message.await_count == 0
        assert video_intent.has_pending(CHAT_ID)

    @pytest.mark.asyncio
    async def test_private_chat_question_is_not_hijacked(self, env):
        """Обычный вопрос в личке («в чём суть?») ожидание НЕ создаёт."""
        bot = _bot()
        msg = _msg(text="в чём суть?", message_id=940, chat_type="private")
        assert await yt.youtube_handler(msg, bot=bot) is UNHANDLED
        assert not video_intent.has_pending(CHAT_ID)


class TestOtherTargetNotConsumed:
    """Веб-ссылка (статья) — ЧУЖАЯ цель: 0f обслуживает её, 0e не перехватывает."""

    @pytest.mark.asyncio
    async def test_web_summary_not_consumed_while_pending_active(self, env):
        bot = _bot()
        await yt.youtube_handler(
            _msg(text="Бот, сделай выжимку видео", message_id=920), bot=bot)
        assert len(video_intent.pending_for(CHAT_ID)) == 1
        corr = _corr_of_pending()
        events_before = len(video_intent.recent_events())

        web = _msg(text="Бот, сделай выжимку https://example.com/article",
                   message_id=921)
        assert await yt.youtube_handler(web, bot=bot) is UNHANDLED

        assert bot.send_message.await_count == 0          # ответит 0f/LLM
        assert len(video_intent.pending_for(CHAT_ID)) == 1  # не второе ожидание
        assert _corr_of_pending() == corr
        assert len(video_intent.recent_events()) == events_before

    @pytest.mark.asyncio
    async def test_web_summary_without_pending_not_consumed(self, env):
        bot = _bot()
        web = _msg(text="Бот, сделай выжимку https://example.com/article",
                   message_id=930)
        assert await yt.youtube_handler(web, bot=bot) is UNHANDLED
        assert not video_intent.has_pending(CHAT_ID)
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_video_url_still_analyzed(self, env):
        """Видео-URL — своя цель: как и раньше уходит в анализ."""
        bot = _bot()
        msg = _msg(text="Бот, сделай выжимку https://www.tiktok.com/@x/video/1",
                   message_id=950)
        assert await yt.youtube_handler(msg, bot=bot) is None
        assert not video_intent.has_pending(CHAT_ID)


class TestAudioOnlyReplyHonesty:
    """F2: STT/аудио-фолбэк не выдаёт себя за просмотренное видео."""

    @pytest.mark.asyncio
    async def test_audio_only_fallback_reply_marks_transcript_only(self, env,
                                                                  monkeypatch):
        monkeypatch.setattr(yt.media_share, "enabled", lambda: False)
        bot = _bot()
        note = _msg(message_id=730, video_note=_media(file_id="n730",
                                                      file_unique_id="un730"))
        request = _msg(text="Бот, сделай выжимку", message_id=731,
                       reply_to_message=note)

        assert await yt.youtube_handler(request, bot=bot) is None
        assert env.svc.summarize_transcript.await_count == 1
        assert env.svc.summarize_media_url.await_count == 0   # визуал не заявлен
        assert bot.send_message.await_count == 1
        text = bot.send_message.await_args.args[1]
        assert yt.TRANSCRIPT_ONLY_NOTE in text
        assert "аудиодорожк" in text.lower()
        assert not _events("multimodal_success")
        assert _events("transcript_fallback")[-1]["reason_code"] == \
            "audio_only_source"

    @pytest.mark.asyncio
    async def test_multimodal_success_has_no_transcript_note(self, env):
        """Мультимодальный путь НЕ получает пометку (видео реально смотрели)."""
        bot = _bot()
        target = _msg(message_id=740, video=_media(file_id="v740",
                                                   file_unique_id="u740"))
        request = _msg(text="Бот, сделай выжимку", message_id=741,
                       reply_to_message=target)

        assert await yt.youtube_handler(request, bot=bot) is None
        assert env.svc.summarize_media_url.await_count == 1
        text = bot.send_message.await_args.args[1]
        assert yt.TRANSCRIPT_ONLY_NOTE not in text
        assert _events("multimodal_success")
