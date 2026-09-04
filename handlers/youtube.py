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

Раунд 3 (T-688…T-694, spec 3.2/3.3/3.4/3.6): универсальный маршрутизатор
видео-запроса: (kind: youtube/direct_url/platform_url/native) ×
(mode: summary/transcript). Медиа-ветка получает мультимодальный каскад
L1/L2 по временному опубликованному URL (/media, services.media_share),
«транскрипт» оформляется как у кружков (HTML, 3.3), честная выжимка ТОЛЬКО
по транскрипту ≥ limits.video_summary_min_chars (иначе пул 5.13, БЕЗ RAG),
B8-фолбек отсутствующей строки smart_messages. Прямые ссылки и платформы
(tiktok/instagram/vk/…) — скачивание существующим VideoDownloader
(в тихую, quality 360) → публикация → L1/L2 → STT-фолбек. YouTube-URL-ветка
для mode=summary — байт-в-байт прежняя. Voice/video_note НЕ квалифицируются
(их обслуживает 0i).
"""
import asyncio
import dataclasses
import logging
import os
import random
import tempfile
from pathlib import Path

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramBadRequest

from config.settings import settings
from handlers.media_common import (
    _resolve_author_from_user,
    _resolve_transcript_author,
    format_transcript_html,
    set_media_aliases,
    split_transcript_first,
    wrap_media_fact,
)
from services import hot_config as hot
from services import media_share
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
    VIDEO_NO_SPEECH_PHRASES,
    YOUTUBE_ERROR_PHRASES,
    YOUTUBE_RETRY_PHRASES,   # НОВОЕ (5.8, R41-2)
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_urls import extract_urls, extract_youtube_video_id
from services.smartmodule_utils import (
    _reply,
    _send_once,
    react_moai,
    send_chunked_reply,
    throttle_phrase,
)
from services.summary_memory import fire_and_forget
from services.typing_manager import typing_active
from services.video_cascade_client import VideoLevelError
from services.youtube_transcript_engine import (
    YouTubeTranscriptUnavailableException,
)
from tools.video_downloader import (
    DownloadBusyError,
    DownloadError,
    DownloadTooBigError,
    DownloadUnavailableError,
    is_direct_media_url,
)
from tools.video_downloader import _is_platform_url
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
# Раунд 3 (T-688): общий VideoDownloader (тот же инстанс, что у 4e «скачай» —
# один глобальный лок скачивания на процесс). Лёгкий, клиенты ленивые (D261).
_media_downloader = None

_YOUTUBE_TRIGGERS: tuple[str, ...] = (
    "транскрипт", "че за видос", "о чем видео", "поясни за видос",
    "перескажи видос", "че в видосе",
)

# Медиа-ветка: бюджет на скачивание TG-файла (NFR-4).
_FETCH_TIMEOUT = 120.0

# Документы-«видео» БЕЗ mime — по расширению file_name (3.1.1).
_VIDEO_DOC_EXTENSIONS = ("mp4", "webm", "mov", "mkv", "avi")

# Раунд 3 (3.2, T-690): cap субтитров YouTube для mode=transcript.
_YT_TRANSCRIPT_CAP = 20000
# Ссылочные ветки качают «в тихую» в 360p (без probe-меню 4e).
_URL_QUALITY = "360"
# Лейблы в мультимодальном запросе (R17: URL/подпись в логах НЕ светятся).
_LABEL_TG_FILE = "tg-file"
_LABEL_DIRECT = "direct-url"
_LABEL_PLATFORM = "platform-url"


def setup_youtube(service, db=None) -> None:
    """DI: YoutubeSummarizerService. Вызывается из bot.py on_startup (46.10).
    Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED → персистентный кулдаун
    (throttle_state, scope='youtube')."""
    global _service, _cooldown
    _service = service
    _cooldown = make_cooldown(
        "youtube", settings.YOUTUBE_COOLDOWN_SECONDS, db)


def setup_youtube_video_media(transcriber, db=None, aliases=None,
                              memory=None, bot_id=None, downloader=None) -> None:
    """Bugfix 04.09.2026 (Часть 1): DI медиа-ветки (нативные TG-видео).
    transcriber — ОБЩИЙ инстанс VoiceTranscriber (общий семафор D295:
    голосовые/кружочки и видео не устраивают гонку за Groq Free Tier).
    Раунд 3 (T-688): downloader — общий VideoDownloader (создаётся в
    summary-блоке bot.py рядом с voice_service; ссылочные ветки 0e НЕ гейтятся
    flags.download_enabled — скачивание по ссылке для пересказа часть
    summary-функционала). Вызывается из bot.py on_startup ВНУТРИ summary-блока,
    порядок регистрации роутеров не меняется."""
    global _media_transcriber, _media_db, _media_memory, _media_bot_id
    global _media_downloader
    _media_transcriber = transcriber
    _media_db = db
    _media_memory = memory
    _media_bot_id = bot_id
    _media_downloader = downloader
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
    классификатору это уже гарантировано вызывающим) + медиа «видео» на
    message ИЛИ reply_to_message → _VideoMedia. ВАЖНО: voice/video_note/audio
    НИКОГДА не квалифицируются (0i их обслуживает). Собственное медиа вызова
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


def _request_author(message: types.Message) -> str:
    """Раунд 3 (3.3): автор запроса для ссылочных kind (youtube/direct_url/
    platform_url) — каскад AliasResolver от from_user, БЕЗ «(переслал)»."""
    return _resolve_author_from_user(message.from_user)


# ── Раунд 3 (3.2, T-688): классификация видео-запроса ─────────────────

@dataclasses.dataclass(frozen=True)
class _VideoRequest:
    """Матрица kind × mode (FR-B3/FR-B4)."""
    kind: str            # "youtube" | "direct_url" | "platform_url" | "native"
    mode: str            # "summary" | "transcript"
    url: str | None      # исходный URL для url-кидов
    video_id: str | None # youtube-ветка (каскад работает по id)
    media: _VideoMedia | None
    source: types.Message   # сообщение, на которое реплаим/с которого читаем


def _request_mode(message: types.Message) -> str:
    text = str(message.text or message.caption or "")
    return "transcript" if "транскрипт" in text.lower() else "summary"


def _classify_video_request(message: types.Message) -> _VideoRequest | None:
    """Классификация (FR-B3): триггер есть (substring); приоритеты:
    (1) YouTube-URL (reply-таргет приоритетнее вызова, D126-семантика);
    (2) прямая медиа-ссылка; (3) известная платформа (НЕ youtube, НЕ direct);
    (4) нативное медиа (video/document; voice/video_note НЕ квалифицируются);
    (5) ничего → None (UNHANDLED → пропагация живёт). mode — «транскрипт»
    substring текста вызова (FR-B4). Никогда не бросает."""
    try:
        text = (message.text or message.caption or "")
        if not _has_trigger(text):
            return None
        mode = _request_mode(message)
        # (1) YouTube-URL: reply-таргет → текст вызова (D126)
        target, video_id = _parse(message)
        if video_id is not None:
            return _VideoRequest(kind="youtube", mode=mode,
                                 url=None, video_id=video_id,
                                 media=None, source=target or message)
        # (2)/(3) НЕ-youtube URL: сначала текст вызова, затем reply-таргет
        reply = getattr(message, "reply_to_message", None)
        for src in (message, reply):
            if src is None:
                continue
            src_text = (src.text or src.caption or "")
            for url in extract_urls(src_text):
                if is_direct_media_url(url):
                    return _VideoRequest(kind="direct_url", mode=mode,
                                         url=url, video_id=None,
                                         media=None, source=message)
                if _is_platform_url(url):
                    return _VideoRequest(kind="platform_url", mode=mode,
                                         url=url, video_id=None,
                                         media=None, source=message)
        # (4) нативное медиа (своё приоритетнее reply) — Часть 1
        media = _resolve_video_media(message)
        if media is not None:
            return _VideoRequest(kind="native", mode=mode, url=None,
                                 video_id=None, media=media,
                                 source=media.source)
        return None
    except Exception:
        logger.warning("[youtube] classify failed — UNHANDLED", exc_info=True)
        return None


# ── Раунд 3 (3.5, T-692): STT-хелперы ────────────────────────────────

def _stt_timeout() -> float:
    """Таймаут STT видео (limits.video_stt_timeout_seconds, дефолт 120).
    fix-round 04.09 (m5): явный 0/пусто в PG НЕ даёт timeout=0 (мгновенный
    TimeoutError) — кламп настройкой-дефолтом."""
    return float(hot.get("limits.video_stt_timeout_seconds",
                         settings.VIDEO_STT_TIMEOUT_SECONDS)
                 or settings.VIDEO_STT_TIMEOUT_SECONDS)


def _summary_min_chars() -> int:
    return int(hot.get("limits.video_summary_min_chars",
                       settings.VIDEO_SUMMARY_MIN_CHARS) or 0)


def _media_share_ttl() -> int:
    return int(hot.get("limits.media_share_ttl_seconds",
                       settings.MEDIA_SHARE_TTL_SECONDS) or 0)


async def _transcribe_video_file(path: str) -> str:
    """STT видео-файла с видео-таймаутом (EmptyTranscript/
    TranscriptionUnavailable — наружу, фразы выбирает вызывающий)."""
    if _media_transcriber is None:
        raise TranscriptionUnavailable(path)
    return await _media_transcriber.transcribe_voice(
        path, "mp4", timeout=_stt_timeout())


async def _stt_or_phrase(bot, chat_id: int, path: str,
                         target_message_id: int) -> str | None:
    """STT видео-файла: успех → текст; EmptyTranscript → пул 5.12;
    TranscriptionUnavailable → пул 5.11 (реплай на target). None — фраза
    уже отправлена (деградация, поток жив)."""
    try:
        return await _transcribe_video_file(path)
    except EmptyTranscript:
        logger.info("[youtube] video-file empty transcript | chat=%s", chat_id)
        await _reply(bot, chat_id, random.choice(VIDEO_MEDIA_EMPTY_PHRASES),
                     target_message_id)
        return None
    except TranscriptionUnavailable as exc:
        logger.warning("[youtube] video-file stt unavailable | chat=%s | %s",
                       chat_id, exc)
        await _reply(bot, chat_id,
                     random.choice(VIDEO_MEDIA_UNAVAILABLE_PHRASES),
                     target_message_id)
        return None


# ── Раунд 3 (3.3, T-690): выдача «транскрипт» как у кружков ──────────

async def _send_transcript_reply(bot, chat_id: int, target_message_id: int,
                                 name: str, text: str,
                                 forwarder: str | None = None) -> None:
    """HTML-первая часть реплаем на целевое сообщение (лейбл + <i>-текст
    первого чанка) + plain-чанки остатка (send_chunked_reply, reply только
    у первой части). Эскейп ПОСЛЕ резки — стыки разметку не рвут (3.3)."""
    first, rest = split_transcript_first(text)
    html_part = format_transcript_html(name, first, forwarder)
    try:
        await _send_once(bot, chat_id, html_part, target_message_id, "HTML")
    except TelegramBadRequest as exc:
        # Страховка: битая разметка/удалённый таргет вне _send_once-фолбэка —
        # падаем на plain-отправку первой части (формат-якорь «🗣:» цел).
        logger.warning("[youtube] transcript html send failed (%s) — plain "
                       "fallback | chat=%s", type(exc).__name__, chat_id)
        try:
            await _send_once(bot, chat_id, f"{name} 🗣:\n{first}",
                             target_message_id)
        except Exception:
            pass
    if rest:
        await send_chunked_reply(bot, chat_id, rest, None)


# ── Раунд 3 (3.6/B8, T-694): инъекции памяти ─────────────────────────

def _reply_to_id(source) -> int | None:
    reply = getattr(source, "reply_to_message", None)
    return getattr(reply, "message_id", None) if reply is not None else None


async def _ensure_smart_message_row(source, chat_id: int, transcript: str) -> None:
    """B8 (T-694): строки smart_messages нет (бот-репост / канал / строка
    ушла из L1-окна/сжата). Создаём ТОЛЬКО если сообщение принадлежит
    реальному юзеру (не боту): контент юзера должен оставаться FTS-искомым
    (прецедент D267). Бот-медиа → INFO-skip. Никаких молчаливых падений."""
    user = getattr(source, "from_user", None)
    if user is None or (_media_bot_id is not None and user.id == _media_bot_id):
        logger.info("[youtube] smart_message row not found (bot/canal media) "
                    "— skip L1 | chat=%s msg=%s", chat_id, source.message_id)
        return
    origin = getattr(source, "forward_origin", None)
    forward_source = None
    if origin is not None:
        from handlers.summary import _extract_forward_source
        forward_source = _extract_forward_source(origin)
    author_name = _resolve_author_from_user(user)
    timestamp = int(getattr(getattr(source, "date", None), "timestamp", None)()) \
        if getattr(getattr(source, "date", None), "timestamp", None) is not None \
        else None
    if timestamp is None:
        timestamp = 0
    try:
        await _media_db.save_smart_message(
            user_id=user.id, chat_id=chat_id, text=transcript,
            reply_to_id=_reply_to_id(source), timestamp=timestamp,
            media_type="video", author_name=author_name,
            is_forward=origin is not None,
            forward_source=(forward_source or ""),
            message_id=source.message_id)
        logger.info("[youtube] smart_message row created (missing) | chat=%s "
                    "msg=%s", chat_id, source.message_id)
    except Exception:
        logger.warning("[youtube] smart_message row create failed | chat=%s",
                       chat_id, exc_info=True)


async def _inject_video_memory(media: _VideoMedia, author: str,
                               transcript: str) -> None:
    """Двойная инъекция (как voice 0i, D267): L2-строка сообщения → текст
    расшифровки + GraphRAG-факт source_type='video_transcript'. Обе —
    best-effort: сбой → WARNING, ответ юзеру уже отправлен. B8 (T-694):
    отсутствующая строка → создаётся для юзер-медиа (бот/канал → INFO-skip)."""
    source = media.source
    chat_id = source.chat.id
    if _media_db is not None:
        try:
            updated = await _media_db.update_smart_message_text(
                chat_id, source.message_id, transcript)
            if not updated:
                logger.info("[youtube] smart_message row not found | chat=%s "
                            "msg=%s", chat_id, source.message_id)
                await _ensure_smart_message_row(source, chat_id, transcript)
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


async def _inject_url_memory(message: types.Message, author: str,
                             transcript: str) -> None:
    """URL-режимы (FR-B7): только GraphRAG-факт (текст запроса — не
    плейсхолдер → L1-обновления нет, INFO). Сбой → WARNING, поток жив."""
    chat_id = message.chat.id
    if _media_db is not None:
        logger.info("[youtube] url video memory: L1 update skipped (no "
                    "placeholder row) | chat=%s", chat_id)
    if _media_memory is None:
        return
    wrapped = wrap_media_fact("video", author, transcript)
    fire_and_forget(
        _media_memory.memorize_facts(chat_id, wrapped,
                                     source_type="video_transcript"),
        "video_transcript")


# ── Раунд 3 (3.4, T-691): честная выжимка и отправка ответа ──────────

async def _summarize_and_send(bot, chat_id: int, transcript: str,
                              target_message_id: int) -> bool:
    """«Честная выжимка»: транскрипт < limits.video_summary_min_chars →
    фраза пула 5.13 (БЕЗ RAG-памяти, поведение 02:45 исключено); иначе
    summarize_transcript (без RAG) → отправка. LLMBadResponseError → 🗿,
    LLMError/неожиданное → LLM_ERROR_PHRASES. False = выжимка не построена
    (память-инъекцию НЕ вызывать)."""
    if len(str(transcript or "").strip()) < _summary_min_chars():
        logger.info("[youtube] video-file speech too short — honest phrase | "
                    "chat=%s chars=%d", chat_id, len(str(transcript or "").strip()))
        await _reply(bot, chat_id, random.choice(VIDEO_NO_SPEECH_PHRASES),
                     target_message_id)
        return False
    try:
        text_out = await _service.summarize_transcript(
            chat_id=chat_id, transcript=transcript)
    except LLMBadResponseError:
        # Пустой ответ модели → 🗿-молчание (прецедент URL-ветки 65.1).
        logger.warning("[youtube] video-file empty answer — silence | chat=%s",
                       chat_id)
        await react_moai(bot, chat_id, target_message_id)
        return False
    except LLMError as exc:
        logger.warning("[youtube] video-file LLM failed | chat=%s | error=%s",
                       chat_id, exc)
        await _reply(bot, chat_id, random.choice(LLM_ERROR_PHRASES),
                     target_message_id)
        return False
    except Exception:
        logger.exception("[youtube] video-file unexpected error | chat=%s",
                         chat_id)
        await _reply(bot, chat_id, random.choice(LLM_ERROR_PHRASES),
                     target_message_id)
        return False
    if not (text_out or "").strip():
        await react_moai(bot, chat_id, target_message_id)
        return False
    await send_chunked_reply(bot, chat_id, text_out, target_message_id)
    return True


async def _send_plain_answer(bot, chat_id: int, text_out: str,
                             target_message_id: int) -> None:
    """Отправка обычного текстового ответа (чанки, reply на target)."""
    await send_chunked_reply(bot, chat_id, text_out, target_message_id)


# ── Раунд 3 (3.2, T-689): мультимодалка опубликованного файла ─────────

async def _publish_and_cascade(bot, chat_id: int, path: str,
                               label: str) -> tuple[object | None, str | None]:
    """Публикация tmp-файла → L1/L2 на /media abs_url → ticket.
    Публикация выключена/файл не опубликован → (None, None) — уровни L1/L2
    пропускаются сразу (лог, без таймаутов 120с×2). Провал обеих моделей →
    (None, None) (STT-фолбек). Успех → (None, text). Удаление файла — в
    finally (TTL — страховка). R17: URL/подпись не логируются (label-хвост)."""
    if not media_share.enabled():
        logger.info("[video cascade] file publish unavailable — skip L1/L2 | "
                    "chat=%s label=%s", chat_id, label)
        return None, None
    ticket = await media_share.publish_media_file(path, _media_share_ttl())
    if ticket is None:
        logger.info("[video cascade] file publish failed — skip L1/L2 | "
                    "chat=%s label=%s", chat_id, label)
        return None, None
    try:
        try:
            text_out = await _service.summarize_media_url(
                chat_id=chat_id, video_url=ticket.abs_url, label=label)
        except VideoLevelError as exc:
            logger.warning("[video cascade] file L1/L2 unavailable — STT "
                           "fallback | label=%s | reason=%s", label, exc)
            return ticket, None
        except Exception:
            logger.exception("[video cascade] file cascade unexpected — STT "
                             "fallback | label=%s", label)
            return ticket, None
        if not (text_out or "").strip():
            return ticket, None
        return ticket, text_out
    finally:
        await media_share.delete_file(ticket.file_id)


# ── Раунд 3 (3.2): скачивание ссылок «в тихую» ───────────────────────

def _downloaded_too_big(path) -> bool:
    """Скачанный файл больше гейта STT (50 МБ по умолчанию) — STT невозможен."""
    try:
        size_mb = os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return False
    limit_mb = hot.get("limits.video_transcribe_max_size_mb",
                       settings.VIDEO_TRANSCRIBE_MAX_SIZE_MB)
    return size_mb > int(limit_mb or 0)


async def _download_url(url: str) -> Path:
    """Скачивание ссылочного источника (direct-стрим/yt-dlp/cobalt, quality
    360) под глобальным локом downloader'а. DownloadBusyError — лок занят
    («скачай»/другой пересказ) — наружу (фраза 5.11)."""
    if _media_downloader is None:
        raise DownloadUnavailableError("0e downloader not configured")
    if _media_downloader.busy:
        raise DownloadBusyError("another download is running")
    return await _media_downloader.download(url, _URL_QUALITY)


async def _download_or_phrase(bot, chat_id: int, url: str,
                              target_message_id: int) -> Path | None:
    """_download_url + фразовая деградация (пул 5.11, NFR-1: юзеру без
    трейсбеков). None — фраза уже отправлена."""
    try:
        return await _download_url(url)
    except DownloadTooBigError as exc:
        logger.warning("[youtube] download too big | chat=%s | %s",
                       chat_id, exc)
        await _reply(bot, chat_id, random.choice(VIDEO_MEDIA_TOO_BIG_PHRASES),
                     target_message_id)
        return None
    except DownloadError as exc:
        logger.warning("[youtube] download failed | chat=%s | error=%s",
                       chat_id, exc)
        await _reply(bot, chat_id,
                     random.choice(VIDEO_MEDIA_UNAVAILABLE_PHRASES),
                     target_message_id)
        return None


# ── Раунд 3 (3.2): ссылочные потоки (direct_url / platform_url) ───────

async def _process_url_media(bot, message: types.Message,
                             request: _VideoRequest) -> None:
    """direct_url+platform_url × summary/transcript (матрица B5). Консьюм на
    100% путей; временный скачанный файл удаляется в finally."""
    chat_id = message.chat.id
    target_message_id = message.message_id
    url = request.url
    mode = request.mode
    author = _request_author(message)
    label = _LABEL_DIRECT if request.kind == "direct_url" else _LABEL_PLATFORM
    path: Path | None = None
    ticket = None
    try:
        if mode == "transcript":
            # direct/platform+transcript: скачать → STT → текст кружков
            path = await _download_or_phrase(bot, chat_id, url,
                                             target_message_id)
            if path is None:
                return
            if _downloaded_too_big(path):          # 5.10 (проверка по st_size)
                logger.info("[youtube] downloaded file too big for STT | "
                            "chat=%s", chat_id)
                await _reply(bot, chat_id,
                             random.choice(VIDEO_MEDIA_TOO_BIG_PHRASES),
                             target_message_id)
                return
            transcript = await _stt_or_phrase(bot, chat_id, str(path),
                                              target_message_id)
            if transcript is None:
                return
            await _send_transcript_reply(bot, chat_id, target_message_id,
                                         author, transcript)
            await _inject_url_memory(message, author, transcript)
            logger.info("[youtube] url-file transcript OK | chat=%s kind=%s "
                        "chars=%d", chat_id, request.kind, len(transcript))
            return
        # ── mode=summary ──
        text_out = None
        if request.kind == "direct_url":
            # 1) мультимодалка L1/L2 напрямую по внешней ссылке
            if _service.video_client is not None and \
                    _service.video_client.available:
                try:
                    text_out = await _service.summarize_media_url(
                        chat_id=chat_id, video_url=url, label=_LABEL_DIRECT)
                except VideoLevelError as exc:
                    logger.warning(
                        "[video cascade] direct-url L1/L2 failed → download | "
                        "chat=%s | reason=%s", chat_id, exc)
                    text_out = None
                except Exception:
                    logger.exception(
                        "[video cascade] direct-url cascade unexpected → "
                        "download | chat=%s", chat_id)
                    text_out = None
            else:
                logger.info(
                    "[video cascade] direct-url L1/L2 disabled (no key) → "
                    "download | chat=%s", chat_id)
            if text_out:
                await _send_plain_answer(bot, chat_id, text_out,
                                         target_message_id)
                logger.info("[youtube] direct-url cascade OK | chat=%s",
                            chat_id)
                return
        # 2) скачать → опубликовать → L1/L2 на /media URL. fix-round 04.09
        # (M2): гейт STT (50МБ) НЕ применяем к мультимодалке — потолок
        # публикации (200МБ) уже внутри publish_media_file, поэтому файл
        # 50–200МБ тоже получает L1/L2; STT-фолбек для него невозможен
        # (гейт ниже) → при пустоте мультимодалки — фраза.
        path = await _download_or_phrase(bot, chat_id, url, target_message_id)
        if path is None:
            return
        ticket, text_out = await _publish_and_cascade(
            bot, chat_id, str(path), label)
        if text_out:
            await _send_plain_answer(bot, chat_id, text_out,
                                     target_message_id)
            logger.info("[youtube] published cascade OK | chat=%s kind=%s",
                        chat_id, request.kind)
            return
        # 3) STT → честная выжимка/фраза (файл ≤ гейта STT)
        if _downloaded_too_big(path):
            # >50МБ: STT структурно невозможен; мультимодалка /media уже
            # пробована выше (no-op при >200МБ/без секрета) — фраза 5.11
            await _reply(bot, chat_id,
                         random.choice(VIDEO_MEDIA_UNAVAILABLE_PHRASES),
                         target_message_id)
            return
        transcript = await _stt_or_phrase(bot, chat_id, str(path),
                                          target_message_id)
        if transcript is None:
            return
        if await _summarize_and_send(bot, chat_id, transcript,
                                     target_message_id):
            await _inject_url_memory(message, author, transcript)
    finally:
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass
        if ticket is not None:
            await media_share.delete_file(ticket.file_id)


# ── Раунд 3 (3.2): youtube+transcript (субтитры-текст) ────────────────

async def _process_youtube_transcript(bot, message: types.Message,
                                      request: _VideoRequest) -> None:
    """«транскрипт <yt-url>»: субтитры текстом (cap 20000) — ЗАМЕНА прежнего
    «каскад-выжимки» (отметить юзеру, T-699). Субтитры недоступны →
    скачивание (yt-dlp/cobalt, 360) → STT (timeout 120) → текст кружков.
    STT пуст/недоступен → пул 5.11. Память (FR-B7): только факт;
    smart_cache НЕ пишем (кэш — только summary-результаты)."""
    chat_id = message.chat.id
    target_message_id = message.message_id
    video_id = request.video_id
    author = _request_author(message)
    transcript = None
    path: Path | None = None
    try:
        try:
            async with typing_active(bot, chat_id):
                transcript = await _service.engine.fetch_transcript(
                    video_id, _YT_TRANSCRIPT_CAP, on_retry=None)
        except Exception:
            # Движок исчерпан (нет субтитров/приватность/сеть) → скачать → STT
            logger.warning(
                "[youtube] yt subtitles unavailable — download+STT | "
                "video_id=%r", video_id, exc_info=True)
            transcript = None
        if transcript:
            await _send_transcript_reply(bot, chat_id, target_message_id,
                                         author, transcript)
            await _inject_url_memory(message, author, transcript)
            logger.info("[youtube] yt transcript sent | video_id=%r chars=%d",
                        video_id, len(transcript))
            return
        url = f"https://www.youtube.com/watch?v={video_id}"
        path = await _download_or_phrase(bot, chat_id, url, target_message_id)
        if path is None:
            return
        if _downloaded_too_big(path):              # 5.10 (проверка по st_size)
            await _reply(bot, chat_id,
                         random.choice(VIDEO_MEDIA_TOO_BIG_PHRASES),
                         target_message_id)
            return
        transcript = await _stt_or_phrase(bot, chat_id, str(path),
                                          target_message_id)
        if transcript is None:
            return
        await _send_transcript_reply(bot, chat_id, target_message_id,
                                     author, transcript)
        await _inject_url_memory(message, author, transcript)
        logger.info("[youtube] yt download+STT transcript sent | "
                    "video_id=%r chars=%d", video_id, len(transcript))
    finally:
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass


# ── Bugfix 04.09.2026 (Часть 1) + Раунд 3: нативная медиа-ветка ───────

async def _process_video_media(bot, message: types.Message,
                               request: _VideoRequest) -> None:
    """native × summary/transcript (матрица B5): лимиты ДО скачивания →
    fetch → (summary: публикация → L1/L2 на /media → фолбек STT → честная
    выжимка/фраза; transcript: STT → HTML-текст кружков) → память (B8).
    Консьюм (None) на 100% путей."""
    media = request.media
    mode = request.mode
    chat_id = media.source.chat.id
    target_message_id = media.source.message_id
    size_mb = hot.get("limits.video_transcribe_max_size_mb",
                      settings.VIDEO_TRANSCRIBE_MAX_SIZE_MB)
    dur_limit = hot.get("limits.video_transcribe_max_duration_seconds",
                        settings.VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS)
    file_size = getattr(media.media, "file_size", None)
    if isinstance(file_size, int) and file_size > size_mb * 1024 * 1024:
        await _reply(bot, chat_id, random.choice(VIDEO_MEDIA_TOO_BIG_PHRASES),
                     target_message_id)
        logger.info("[youtube] video-file too big | chat=%s bytes=%d",
                    chat_id, file_size)
        return
    duration = getattr(media.media, "duration", None)   # Video: int; Document: нет
    if isinstance(duration, int) and duration > 0 and duration > dur_limit:
        await _reply(bot, chat_id, random.choice(VIDEO_MEDIA_TOO_LONG_PHRASES),
                     target_message_id)
        logger.info("[youtube] video-file too long | chat=%s dur=%d",
                    chat_id, duration)
        return
    path = None
    ticket = None
    try:
        async with typing_active(bot, chat_id):
            fd, path = tempfile.mkstemp(prefix="yv_",
                                        suffix=_video_suffix(media))
            os.close(fd)
            try:
                await asyncio.wait_for(
                    fetch_media_to_tmp(bot, media.media, path),
                    timeout=_FETCH_TIMEOUT)
            except Exception as exc:
                logger.warning(
                    "[youtube] video-file fetch failed | chat=%s | %s",
                    chat_id, type(exc).__name__)
                await _reply(bot, chat_id, random.choice(
                    VIDEO_MEDIA_UNAVAILABLE_PHRASES), target_message_id)
                return
            if mode == "transcript":
                # native+transcript: STT → HTML-текст кружков (3.3)
                if _media_transcriber is None:
                    logger.warning(
                        "[youtube] media branch without transcriber | chat=%s",
                        chat_id)
                    await _reply(bot, chat_id,
                                 random.choice(VIDEO_MEDIA_UNAVAILABLE_PHRASES),
                                 target_message_id)
                    return
                transcript = await _stt_or_phrase(bot, chat_id, path,
                                                  target_message_id)
                if transcript is None:
                    return
                author = _resolve_author(media.source)
                origin = getattr(media.source, "forward_origin", None)
                forwarder = None
                if origin is not None:
                    forwarder = _resolve_author_from_user(
                        media.source.from_user)
                await _send_transcript_reply(bot, chat_id, target_message_id,
                                             author, transcript,
                                             forwarder=forwarder)
                await _inject_video_memory(media, author, transcript)
                logger.info("[youtube] video-file transcript OK | chat=%s "
                            "kind=%s chars=%d", chat_id, media.kind,
                            len(transcript))
                return
            # ── mode=summary: публикация → L1/L2 → STT-фолбек ──
            if _service.video_client is not None and \
                    _service.video_client.available:
                ticket, text_out = await _publish_and_cascade(
                    bot, chat_id, path, _LABEL_TG_FILE)
                if text_out:
                    await _send_plain_answer(bot, chat_id, text_out,
                                             target_message_id)
                    logger.info(
                        "[youtube] video-file cascade OK | chat=%s kind=%s",
                        chat_id, media.kind)
                    return
            else:
                logger.info("[video cascade] file L1/L2 disabled (no key) — "
                            "STT path | chat=%s", chat_id)
            # STT-фолбек (публикация недоступна / каскад пуст / нет ключа)
            if _media_transcriber is None:
                logger.warning(
                    "[youtube] media branch without transcriber | chat=%s",
                    chat_id)
                await _reply(bot, chat_id,
                             random.choice(VIDEO_MEDIA_UNAVAILABLE_PHRASES),
                             target_message_id)
                return
            transcript = await _stt_or_phrase(bot, chat_id, path,
                                              target_message_id)
            if transcript is None:
                return
            if await _summarize_and_send(bot, chat_id, transcript,
                                         target_message_id):
                author = _resolve_author(media.source)
                await _inject_video_memory(media, author, transcript)
            logger.info("[youtube] video-file OK | chat=%s kind=%s chars=%d",
                        chat_id, media.kind, len(transcript))
    finally:
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass
        if ticket is not None:
            await media_share.delete_file(ticket.file_id)


# ── youtube+summary: URL-ветка Части 1 (байт-в-байт) ──────────────────

async def _process_youtube_summary(bot, message: types.Message,
                                   target: types.Message,
                                   video_id: str) -> None:
    """Прежняя URL-ветка 0e (cache → L1/L2/L3-каскад → фразы) — байт-в-байт
    для mode=summary (T-688/границы: не трогаем)."""
    text = (message.text or message.caption or "")
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
            await send_chunked_reply(bot, message.chat.id, text_out,
                                     target.message_id)
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


@youtube_router.message()
async def youtube_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        return UNHANDLED
    request = _classify_video_request(message)
    if request is None:
        return UNHANDLED                       # не триггер → пропагация живёт
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[youtube] triggered | chat=%s user=%s kind=%s video_id=%r",
                message.chat.id, user_id, request.kind, request.video_id)
    # T-619: кулдаун — горячая точка (ConfigCache → settings-фолбек)
    cooldown_refresh(_cooldown, hot.get("limits.youtube_cooldown_seconds",
                                        settings.YOUTUBE_COOLDOWN_SECONDS))
    remaining = await cooldown_remaining(_cooldown, message.chat.id, user_id)
    if remaining > 0:                          # 5.1 → РЕПЛАЙ НА ВЫЗОВ (D131/D107)
        await _reply(bot, message.chat.id, throttle_phrase(remaining),
                     message.message_id)
        return                                # консьюм
    await cooldown_touch(_cooldown, message.chat.id, user_id)
    if request.kind == "youtube" and request.mode == "summary":
        # URL-ветка Части 1 — байт-в-байт (T-688)
        await _process_youtube_summary(bot, message, request.source,
                                       request.video_id)
        return
    if request.kind == "youtube":
        await _process_youtube_transcript(bot, message, request)
        return
    if request.kind == "native":
        # Медиа-ветка (консьюм; в smart_cache НЕ пишем — у файла нет
        # стабильного канонического ключа, FR-10; кулдаун общий уже touch'нут).
        await _process_video_media(bot, message, request)
        return
    await _process_url_media(bot, message, request)
