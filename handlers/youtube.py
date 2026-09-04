"""Epic 37 — YouTube handler (R37-4, Section 46.9.1).
Роутер 0e (после 0d search, ДО 0:admin). Триггер: YT-триггер-фраза
(регистронезависимо, substring) + валидный YouTube-URL (D125-формы).
Reply-таргеты: успех/5.6/5.5 → target.message_id (ЦЕЛЕВОЕ: сценарий А —
message.reply_to_message, сценарий Б — сам message); троттлинг 5.1 →
message.message_id (ВЫЗОВ, D131-прецедент D107).

Bugfix 04.09.2026 (Часть 1, FR-1…FR-10): медиа-ветка — нативные TG-видео
(message.video / document video/* по mime/имени, включая репосты) с
триггером «транскрипт/че за видос/…», но БЕЗ YouTube-URL → VoiceTranscriber
(общий инстанс с voice, 0i) → «транскрипт» = сырой текст, остальные =
LLM-выжимка (канон prompts.youtube_system_prompt) + двойная инъекция памяти
(media_type='video', source_type='video_transcript'). YouTube-URL-ветка
(:85-107 и тело хендлера) — байт-в-байт, НЕ меняется.
"""
import asyncio
import dataclasses
import logging
import os
import random
import tempfile

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from handlers.media_common import (
    _resolve_transcript_author,
    set_media_aliases,
    wrap_media_fact,
)
from services import hot_config as hot
from services.llm_client import LLMBadResponseError, LLMError
from services.media_download import fetch_media_to_tmp
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.smart_cache import get_smart_cache
from services.smartmodule_phrases import (
    LLM_ERROR_PHRASES,
    VIDEO_MEDIA_EMPTY_PHRASES,
    VIDEO_MEDIA_TOO_BIG_PHRASES,
    VIDEO_MEDIA_TOO_LONG_PHRASES,
    VIDEO_MEDIA_UNAVAILABLE_PHRASES,
    YOUTUBE_ERROR_PHRASES,
    YOUTUBE_RETRY_PHRASES,   # НОВОЕ (5.8, R41-2)
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_urls import extract_youtube_video_id
from services.smartmodule_utils import (
    _reply,
    react_moai,
    send_chunked_reply,
    throttle_phrase,
)
from services.summary_memory import fire_and_forget
from services.typing_manager import typing_active
from services.youtube_transcript_engine import YouTubeTranscriptUnavailableException
from SmartModule.service import (
    EmptyTranscript,
    TranscriptionUnavailable,
    VoiceTranscriber,
)

logger = logging.getLogger(__name__)

youtube_router = Router(name="youtube")

_service = None                                   # YoutubeSummarizerService (DI)
_cooldown = CooldownTracker(settings.YOUTUBE_COOLDOWN_SECONDS)

# ── Bugfix 04.09.2026 (Часть 1): DI медиа-ветки (общий VoiceTranscriber) ──
_media_transcriber: VoiceTranscriber | None = None   # ОБЩИЙ с voice (0i)
_media_memory = None
_media_db = None
_media_bot_id: int | None = None

_YOUTUBE_TRIGGERS: tuple[str, ...] = (
    "транскрипт", "че за видос", "о чем видео", "поясни за видос",
    "перескажи видос", "че в видосе",
)

# Медиа-ветка: бюджет на скачивание TG-файла (NFR-4).
_FETCH_TIMEOUT = 120.0

# Документы-«видео» БЕЗ mime — по расширению file_name (3.1.1).
_VIDEO_DOC_EXTENSIONS = ("mp4", "webm", "mov", "mkv", "avi")


def setup_youtube(service, db=None) -> None:
    """DI: YoutubeSummarizerService. Вызывается из bot.py on_startup (46.10).
    Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED → персистентный кулдаун
    (throttle_state, scope='youtube')."""
    global _service, _cooldown
    _service = service
    _cooldown = make_cooldown(
        "youtube", settings.YOUTUBE_COOLDOWN_SECONDS, db)


def setup_youtube_video_media(transcriber, db=None, aliases=None,
                              memory=None, bot_id=None) -> None:
    """Bugfix 04.09.2026 (Часть 1): DI медиа-ветки (нативные TG-видео).
    transcriber — ОБЩИЙ инстанс VoiceTranscriber (общий семафор D295:
    голосовые/кружочки и видео не устраивают гонку за Groq Free Tier).
    Вызывается из bot.py on_startup ВНУТРИ summary-блока, порядок регистрации
    роутеров не меняется."""
    global _media_transcriber, _media_db, _media_memory, _media_bot_id
    _media_transcriber = transcriber
    _media_db = db
    _media_memory = memory
    _media_bot_id = bot_id
    set_media_aliases(aliases)


def _has_trigger(text: str) -> bool:
    """Регистронезависимый substring-матч любой триггер-фразы (R37-4)."""
    lowered = text.lower()
    return any(trigger in lowered for trigger in _YOUTUBE_TRIGGERS)


def _make_retry_notifier(bot, chat_id, target_message_id):
    """R41-2/D156 + D298 (Epic 79): on_retry-замыкание для движка —
    токсичная фраза из 5.8 реплаем на ЦЕЛЕВОЕ сообщение (target.message_id),
    прецедент Reply-To 5.6/5.5. Антиспам: озвучиваем ТОЛЬКО первую
    промежуточную попытку (attempt=1); 2..4 молчат — итоговые успех/провал
    приходят одним сообщением и так.
    Best-effort: если таргет исчез (_reply бросит MessageToReplyNotFound) —
    каскад НЕ падает: движок глушит колбэк logger.exception (50.3)."""
    async def on_retry(attempt: int, max_attempts: int) -> None:
        if attempt > 1:
            return
        await _reply(bot, chat_id, random.choice(YOUTUBE_RETRY_PHRASES),
                     target_message_id)
    return on_retry


def _parse(message: types.Message) -> tuple[types.Message | None, str | None]:
    """→ (reply_target, video_id) | (None, None).
    Сценарий А: reply на сообщение с YT-URL → (reply_to_message, video_id);
    D126 (Q2): в replied-сообщении URL нет → fallback на URL в тексте вызова
    → (message, video_id) = сценарий Б; URL нигде нет → НЕ триггер.
    Сценарий Б: URL+триггер в самом сообщении (любой порядок/позиция)."""
    text = (message.text or message.caption or "")
    if not _has_trigger(text):
        return None, None
    reply_target = message.reply_to_message
    if reply_target is not None:
        target_text = (reply_target.text or reply_target.caption or "")
        video_id = extract_youtube_video_id(target_text)
        if video_id is not None:
            return reply_target, video_id
        video_id = extract_youtube_video_id(text)   # D126: fallback на Б
        if video_id is not None:
            return message, video_id
        return None, None
    video_id = extract_youtube_video_id(text)
    if video_id is None:
        return None, None
    return message, video_id


@dataclasses.dataclass(frozen=True)
class _VideoMedia:
    """Медиа-ветка (Часть 1): сообщение-носитель + объект Video/Document."""
    source: types.Message
    media: object
    kind: str                    # "video" | "document"


def _document_is_video(doc) -> bool:
    """Document → видео: mime video/*; mime пуст/None → расширение file_name;
    mime задан и не video/* → НЕ видео (mime авторитетнее имени)."""
    mime = str(getattr(doc, "mime_type", "") or "").strip().lower()
    if mime:
        return mime.startswith("video/")
    name = str(getattr(doc, "file_name", "") or "").lower()
    return any(name.endswith("." + ext) for ext in _VIDEO_DOC_EXTENSIONS)


def _resolve_video_media(message: types.Message) -> _VideoMedia | None:
    """Триггер есть (substring, тот же _has_trigger) + НЕТ YouTube-URL (по
    _parse это уже гарантировано вызывающим) + медиа «видео» на message ИЛИ
    reply_to_message → _VideoMedia. ВАЖНО: voice/video_note/audio НИКОГДА не
    квалифицируются (0i их обслуживает). Собственное медиа вызова
    приоритетнее медиа реплая. Любое исключение → None (не ронять роутер).
    Форварды: aiogram кладёт вложение в те же поля (message.video +
    forward_origin) — репосты работают через ту же квалификацию."""
    try:
        text = (message.text or message.caption or "")
        if not _has_trigger(text):
            return None
        for candidate in (message, getattr(message, "reply_to_message", None)):
            if candidate is None:
                continue
            video = getattr(candidate, "video", None)
            if video is not None:
                return _VideoMedia(source=candidate, media=video, kind="video")
            document = getattr(candidate, "document", None)
            if document is not None and _document_is_video(document):
                return _VideoMedia(source=candidate, media=document,
                                   kind="document")
        return None
    except Exception:
        logger.warning("[youtube] media resolve failed — UNHANDLED", exc_info=True)
        return None


def _video_suffix(media: _VideoMedia) -> str:
    """Суффикс tmp-файла: video → .mp4; document — по file_name (известное
    видео-расширение) либо .mp4 по умолчанию."""
    if media.kind == "video":
        return ".mp4"
    name = str(getattr(media.media, "file_name", "") or "").lower()
    for ext in _VIDEO_DOC_EXTENSIONS:
        if name.endswith("." + ext):
            return f".{ext}"
    return ".mp4"


def _resolve_author(message: types.Message) -> str:
    """Автор лейбла расшифровки видео (форвард → источник, иначе from_user)."""
    return _resolve_transcript_author(message)


async def _inject_video_memory(media: _VideoMedia, author: str,
                               transcript: str) -> None:
    """Двойная инъекция (как voice 0i, D267): L2-строка сообщения → текст
    расшифровки + GraphRAG-факт source_type='video_transcript'. Обе —
    best-effort: сбой → WARNING, ответ юзеру уже отправлен."""
    source = media.source
    chat_id = source.chat.id
    if _media_db is not None:
        try:
            updated = await _media_db.update_smart_message_text(
                chat_id, source.message_id, transcript)
            if not updated:
                logger.info("[youtube] smart_message row not found | chat=%s "
                            "msg=%s", chat_id, source.message_id)
        except Exception:
            logger.warning("[youtube] smart_message text update failed | chat=%s",
                           chat_id, exc_info=True)
    if _media_memory is None:
        return
    origin = getattr(source, "forward_origin", None)
    forward_source = None
    if origin is not None:
        from handlers.summary import _extract_forward_source
        forward_source = _extract_forward_source(origin)
    wrapped = wrap_media_fact("video", author, transcript,
                              forward_source=forward_source)
    fire_and_forget(
        _media_memory.memorize_facts(chat_id, wrapped,
                                     source_type="video_transcript"),
        "video_transcript")


async def _process_video_media(bot, message: types.Message,
                               media: _VideoMedia) -> None:
    """Медиа-ветка (Часть 1): лимиты ДО скачивания → fetch → VoiceTranscriber
    (тот же каскад, что у video_note) → выдача по триггеру (сырой текст при
    «транскрипт», иначе LLM-выжимка) → память. Консьюм (None) на 100% путей."""
    chat_id = media.source.chat.id
    size_mb = hot.get("limits.video_transcribe_max_size_mb",
                      settings.VIDEO_TRANSCRIBE_MAX_SIZE_MB)
    dur_limit = hot.get("limits.video_transcribe_max_duration_seconds",
                        settings.VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS)
    file_size = getattr(media.media, "file_size", None)
    if isinstance(file_size, int) and file_size > size_mb * 1024 * 1024:
        await _reply(bot, chat_id, random.choice(VIDEO_MEDIA_TOO_BIG_PHRASES),
                     media.source.message_id)
        logger.info("[youtube] video-file too big | chat=%s bytes=%d",
                    chat_id, file_size)
        return
    duration = getattr(media.media, "duration", None)   # Video: int; Document: нет
    if isinstance(duration, int) and duration > 0 and duration > dur_limit:
        await _reply(bot, chat_id, random.choice(VIDEO_MEDIA_TOO_LONG_PHRASES),
                     media.source.message_id)
        logger.info("[youtube] video-file too long | chat=%s dur=%d",
                    chat_id, duration)
        return
    if _media_transcriber is None:
        logger.warning("[youtube] media branch without transcriber | chat=%s",
                       chat_id)
        await _reply(bot, chat_id,
                     random.choice(VIDEO_MEDIA_UNAVAILABLE_PHRASES),
                     media.source.message_id)
        return
    transcript = None
    try:
        async with typing_active(bot, chat_id):
            fd, path = tempfile.mkstemp(prefix="yv_", suffix=_video_suffix(media))
            os.close(fd)
            try:
                try:
                    await asyncio.wait_for(
                        fetch_media_to_tmp(bot, media.media, path),
                        timeout=_FETCH_TIMEOUT)
                except Exception as exc:
                    logger.warning(
                        "[youtube] video-file fetch failed | chat=%s | %s",
                        chat_id, type(exc).__name__)
                    await _reply(bot, chat_id, random.choice(
                        VIDEO_MEDIA_UNAVAILABLE_PHRASES), media.source.message_id)
                    return
                try:
                    transcript = await _media_transcriber.transcribe_voice(
                        path, "mp4")
                except EmptyTranscript:
                    logger.info("[youtube] video-file empty transcript | chat=%s",
                                chat_id)
                    await _reply(bot, chat_id,
                                 random.choice(VIDEO_MEDIA_EMPTY_PHRASES),
                                 media.source.message_id)
                    return
                except TranscriptionUnavailable as exc:
                    logger.warning(
                        "[youtube] video-file stt unavailable | chat=%s | error=%s",
                        chat_id, exc)
                    await _reply(bot, chat_id, random.choice(
                        VIDEO_MEDIA_UNAVAILABLE_PHRASES), media.source.message_id)
                    return
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except Exception:
        # typing_active/обвязка упала — консьюм с фразой (поток жив)
        logger.warning("[youtube] video-file processing failed | chat=%s",
                       chat_id, exc_info=True)
        try:
            await _reply(bot, chat_id,
                         random.choice(VIDEO_MEDIA_UNAVAILABLE_PHRASES),
                         media.source.message_id)
        except Exception:
            pass
        return

    author = _resolve_author(media.source)
    text = (message.text or message.caption or "")
    want_raw = "транскрипт" in text.lower()
    try:
        if want_raw:
            label = f"{author} 🗣:"
            await send_chunked_reply(bot, chat_id, f"{label}\n{transcript}",
                                     media.source.message_id)
        else:
            async with typing_active(bot, chat_id):
                text_out = await _service.summarize_transcript(
                    chat_id=chat_id, rag_query=text, transcript=transcript)
                await send_chunked_reply(bot, chat_id, text_out,
                                         media.source.message_id)
    except LLMBadResponseError:
        # Пустой ответ модели → 🗿-молчание (прецедент URL-ветки 65.1).
        logger.warning("[youtube] video-file empty answer — silence | chat=%s",
                       chat_id)
        await react_moai(bot, chat_id, media.source.message_id)
        return
    except LLMError as exc:
        logger.warning("[youtube] video-file LLM failed | chat=%s | error=%s",
                       chat_id, exc)
        await _reply(bot, chat_id, random.choice(LLM_ERROR_PHRASES),
                     media.source.message_id)
        return
    except Exception:
        logger.exception("[youtube] video-file unexpected error | chat=%s",
                         chat_id)
        await _reply(bot, chat_id, random.choice(LLM_ERROR_PHRASES),
                     media.source.message_id)
        return
    await _inject_video_memory(media, author, transcript)
    logger.info("[youtube] video-file OK | chat=%s kind=%s chars=%d",
                chat_id, media.kind, len(transcript))


@youtube_router.message()
async def youtube_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        return UNHANDLED
    target, video_id = _parse(message)
    media = None
    if target is None:
        # Bugfix 04.09.2026 (Часть 1, FR-1): триггер + нативное TG-видео
        # (video/document, включая репосты) без YT-URL → медиа-ветка.
        media = _resolve_video_media(message)
        if media is None:
            return UNHANDLED                       # не триггер → пропагация живёт
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[youtube] triggered | chat=%s user=%s video_id=%r",   # R41-5
                message.chat.id, user_id, video_id)
    # T-619: кулдаун — горячая точка (ConfigCache → settings-фолбек)
    cooldown_refresh(_cooldown, hot.get("limits.youtube_cooldown_seconds",
                                        settings.YOUTUBE_COOLDOWN_SECONDS))
    remaining = await cooldown_remaining(_cooldown, message.chat.id, user_id)
    if remaining > 0:                          # 5.1 → РЕПЛАЙ НА ВЫЗОВ (D131/D107)
        await _reply(bot, message.chat.id, throttle_phrase(remaining), message.message_id)
        return                                # консьюм
    await cooldown_touch(_cooldown, message.chat.id, user_id)
    text = (message.text or message.caption or "")   # Epic 46 (55.5): rag_query
    if media is not None:
        # Bugfix 04.09.2026 (Часть 1, FR-1): медиа-ветка (консьюм; в
        # smart_cache НЕ пишем — у файла нет стабильного канонического ключа,
        # FR-10; кулдаун общий с youtube уже touch'нут выше).
        await _process_video_media(bot, message, media)
        return
    # Epic 51 (59.2, D210): Exact Match Cache по video_id (канонический
    # идентификатор — разные URL одной ссылки дают один ключ) — ДО
    # транскрипта/LLM. Хит → reply на ТЕКУЩЕЕ сообщение.
    cache = get_smart_cache()
    cache_key = cache.build_key("youtube", video_id)
    cached = await cache.get(cache_key)
    if cached is not None:
        await _reply(bot, message.chat.id, cached, message.message_id)
        logger.info("[youtube] cache hit | chat=%s video_id=%r",
                    message.chat.id, video_id)
        return
    try:
        # Epic 60 (65.7, T-475): «печатает…» от контекста в ИИ до отправки.
        async with typing_active(bot, message.chat.id):
            # Эпик 04.09.2026 (3.2): каскад L1 (видео-модель) → L2 (запасная) →
            # L3 (субтитры). Ошибки L1/L2 в хендлер НЕ приходят (молчаливая
            # деградация внутри сервиса); try/except ниже покрывает только
            # финальный провал ВСЕГО каскада (L3).
            text_out = await _service.summarize_cascade(
                video_id,
                on_retry=_make_retry_notifier(bot, message.chat.id,
                                              target.message_id),
                chat_id=message.chat.id,
                rag_query=text,
            )
            await send_chunked_reply(bot, message.chat.id, text_out, target.message_id)
        await cache.set(cache_key, text_out)      # только успешная генерация (59.2)
        logger.info("[youtube] summary sent | chat=%s video_id=%r",      # R41-5
                    message.chat.id, video_id)
    except LLMBadResponseError as exc:
        # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿 (НЕ R13).
        logger.warning("[youtube] empty answer — silence | chat=%s video_id=%r | error=%s",
                       message.chat.id, video_id, exc)
        await react_moai(bot, message.chat.id, target.message_id)
    except YouTubeTranscriptUnavailableException:
        logger.exception("[youtube] transcript failed | chat=%s video_id=%r",
                         message.chat.id, video_id)                       # R41-5
        await _reply(bot, message.chat.id, random.choice(YOUTUBE_ERROR_PHRASES),  # 5.6 → ЦЕЛЕВОЕ
                     target.message_id)
    except LLMError as exc:
        logger.warning("[youtube] LLM failed | chat=%s video_id=%r | error=%s",  # Epic 47 (D190): WARNING
                       message.chat.id, video_id, exc)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),       # 5.5 → ЦЕЛЕВОЕ
                     target.message_id)
    except Exception:
        logger.exception("[youtube] unexpected error | chat=%s video_id=%r",
                         message.chat.id, video_id)                       # R41-5
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),
                     target.message_id)
