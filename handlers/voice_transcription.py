"""Epic 67 — Voice-to-Text handler (Section 71.3/71.4, D267/D268).

Роутер 0i — ПОСЛЕ summary_observer 0a и direct_chat 0h, ДО admin_commands.
Observer-стиль: ловит СТРОГО F.voice | F.video_note (F.audio/F.document не
триггерят) и ВСЕГДА возвращает UNHANDLED — апдейт никогда не потребляется.

Флоу: лимит длительности → TYPING → скачивание во временный файл (.ogg/.mp4)
→ каскад Groq→OpenRouter → реплай «<b>{name}</b> 🗣: <i>{text}</i>»
(parse_mode=HTML, D268; форвард — «<b>{автор}</b> (переслал {X}) 🗣: …», D272)
строго на голосовое/кружочек → двойная инъекция в память: UPDATE
smart_messages.text вместо плейсхолдера + memorize_facts
(source_type='voice_transcript', fire_and_forget). Temp-файл удаляется в
finally на 100% путей. Имя отправителя — каскад AliasResolver
(Алиас → Никнейм → Юзернейм → ID); у форвардов — автор источника
(_extract_forward_source, Epic 72 / Section 74.B).
"""
import asyncio
import html
import logging
import os
import random
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.enums import ChatAction

from config.settings import settings
from handlers.summary import _extract_forward_source
from services.summary_memory import fire_and_forget
from SmartModule.phrases import (
    VT_ALL_FAILED_PHRASES,
    VT_SILENCE_PHRASES,
    VT_TOO_LONG_PHRASES,
)
from SmartModule.service import (
    EmptyTranscript,
    TranscriptionUnavailable,
    VoiceTranscriber,
)

logger = logging.getLogger(__name__)

voice_transcription_router = Router(name="voice_transcription")

_service: VoiceTranscriber | None = None
_db = None
_aliases = None
_memory = None
_bot_id = None


def setup_voice_transcription(service: VoiceTranscriber, db=None, aliases=None,
                              memory=None, bot_id=None) -> None:
    """DI из bot.py on_startup (Section 71.6)."""
    global _service, _db, _aliases, _memory, _bot_id
    _service = service
    _db = db
    _aliases = aliases
    _memory = memory
    _bot_id = bot_id


def _build_nickname(user) -> str | None:
    """Прецедент handlers/summary.py:137 — first_name+last_name."""
    parts = []
    for attr in ("first_name", "last_name"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts) if parts else None


_VT_UNKNOWN_AUTHOR = "Неизвестный"   # Epic 72 (74.B/D272): ЛОКАЛЬНАЯ константа


def _resolve_transcript_author(message: types.Message) -> str:
    """Epic 72 (74.B.1, D272): автор для лейбла расшифровки.
    Форвард → каскад _extract_forward_source (handlers/summary.py,
    прецедент импорта handler→handler: handlers/factcheck.py:21):
    MessageOriginUser → AliasResolver (Алиас→Никнейм→Юзернейм без @),
    HiddenUser → sender_user_name, Channel/Chat → title (+@username).
    Извлечение не удалось (exotic-тип/битый origin) → «Неизвестный»
    (локальная константа транскрипции; summary/observer НЕ затронуты).
    Не-форвард → прежний каскад от from_user (D268-поведение).
    DI: _extract_forward_source читает глобальную handlers.summary._aliases —
    заполняется setup_summary(...) в bot.py on_startup ДО регистрации роутеров."""
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        return (_extract_forward_source(origin) or _VT_UNKNOWN_AUTHOR)
    user = message.from_user
    return _aliases.resolve(
        user.id,
        nickname=_build_nickname(user),
        username=getattr(user, "username", None),
    )


def wrap_media_fact(media_type: str, sender: str, text: str,
                    forward_source: str | None = None) -> str:
    """Обёртка транскрипта для GraphRAG-экстрактора (D267):
    '<MediaMessage type="voice" sender="..." timestamp="<ISO8601 UTC>">...</MediaMessage>'.
    Epic 72 (74.B.3, D273): у форвардов добавляются атрибуты
    forwarded="true" forward_from="{автор источника}" (html.escape quote=True —
    ОВ-3: XML-совместимо и консистентно с D268; ОВ-3 решён в пользу html.escape).
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    extra = ""
    if forward_source:
        extra = (f' forwarded="true"'
                 f' forward_from="{html.escape(forward_source, quote=True)}"')
    return (f'<MediaMessage type="{media_type}" sender="{sender}" '
            f'timestamp="{timestamp}"{extra}>{text}</MediaMessage>')


# ── Epic 72 (74.C, D274): детектор «reply на расшифровку» ────────────

# Якорь формата D268/D272 в PLAIN-тексте цели: бот шлёт parse_mode=HTML,
# поэтому в target.text разметки НЕТ («Вася 🗣: …» / «Вася (переслал X) 🗣: …»).
# «🗣:» стоит в первой строке после непустого префикса-имени.
_TRANSCRIPTION_ANCHOR_RE = re.compile(r"^.+🗣:")


def _is_transcription_target(target) -> bool:
    """True = сообщение является расшифровкой бота (Epic 72, 74.C).
    Синхронно и без БД. Primary — якорь «🗣:» в тексте; structural-фолбэк
    ТОЛЬКО при пустом тексте цели (страховка на смену формата): цель сама
    реплай на voice/video_note (reply-цепочка доступна в апдейте)."""
    frm = getattr(target, "from_user", None)
    if frm is None or _bot_id is None or frm.id != _bot_id:
        return False
    text = target.text or ""
    if _TRANSCRIPTION_ANCHOR_RE.search(text):
        return True
    if not text.strip():                       # structural fallback
        orig = getattr(target, "reply_to_message", None)
        return orig is not None and (
            getattr(orig, "voice", None) is not None
            or getattr(orig, "video_note", None) is not None)
    return False


def is_reply_to_transcription(message: types.Message) -> bool:
    """True = юзер реплаит НА сообщение бота-расшифровку (Epic 72, 74.C/D274).
    Синхронный и без БД: вызывается из sync-хотпата direct_chat._is_direct_trigger.
    R72-2: якорь связан с форматом ответа D268/D272 — меняя формат,
    правь и этот regex (+ тесты обоих в одном PR)."""
    target = getattr(message, "reply_to_message", None)
    return target is not None and _is_transcription_target(target)


async def _safe_typing(bot, chat_id: int) -> None:
    try:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
    except Exception:
        pass


async def _fetch_media_to_tmp(bot, media, tmp_path) -> None:
    """Epic 78 (D292/Section 79): получить медиа во tmp-файл.
    Гейт локального режима = settings.DOWNLOAD_ENABLED (D262 import-time
    сессия с is_local=True). Локальный режим И относительный file_path →
    копирование с диска из TELEGRAM_API_FILES_DIR/<bot_id>:<token>/
    (root cause: локальный Bot API возвращает file_path ОТНОСИТЕЛЬНЫМ,
    aiogram читает исходник относительно cwd → FileNotFoundError).
    Файла нет / get_file упал / path абсолютный / облако → прежний
    bot.download (облачный режим байт-в-байт, без get_file-двойного запроса).
    Секреты (R17): строка '<bot_id>:<token>' нигде не логируется — в логах
    только file_path-хвост или src.name."""
    if not settings.DOWNLOAD_ENABLED:            # облачный режим: как раньше
        await bot.download(media.file_id, destination=tmp_path)
        return
    file_path = None
    try:
        tg_file = await bot.get_file(media.file_id)
        file_path = getattr(tg_file, "file_path", None)
    except Exception as exc:
        logger.warning("[transcribe] get_file failed | file_id=%s | %s",
                       media.file_id, type(exc).__name__)
    if (isinstance(file_path, str) and file_path
            and not PurePosixPath(file_path).is_absolute()):
        src = (Path(settings.TELEGRAM_API_FILES_DIR)
               / f"{bot.id}:{settings.API_TOKEN}" / file_path)
        try:
            if src.resolve().is_relative_to(
                    Path(settings.TELEGRAM_API_FILES_DIR).resolve()):
                if src.exists():
                    await asyncio.to_thread(shutil.copyfile, src, tmp_path)
                    return
                logger.warning(
                    "[transcribe] local api file missing, fallback to "
                    "download | path=%s", file_path)
        except OSError as exc:
            # R17: только имя файла и тип ошибки — сообщение OSError содержит
            # ПОЛНЫЙ путь (<bot_id>:<token>), exc_info нельзя.
            logger.warning("[transcribe] host copy failed | file=%s | %s",
                           src.name, type(exc).__name__)
    await bot.download(media.file_id, destination=tmp_path)


async def _inject_memory(message: types.Message, name: str, text: str,
                         is_video_note: bool,
                         forward_source: str | None = None) -> None:
    """CRITICAL (D267): двойная инъекция — L2-строка + GraphRAG-факт.
    Epic 72 (74.B.3): у форвардов факт несёт forward_from-атрибуцию."""
    chat_id = message.chat.id
    try:
        updated = await _db.update_smart_message_text(
            chat_id, message.message_id, text)
        if not updated:
            logger.info("[transcribe] smart_message row not found | chat=%s msg=%s",
                        chat_id, message.message_id)
    except Exception:
        logger.warning("[transcribe] smart_message text update failed | chat=%s",
                       chat_id, exc_info=True)
    if _memory is None:
        return
    media_type = "video_note" if is_video_note else "voice"
    wrapped = wrap_media_fact(media_type, name, text,
                              forward_source=forward_source)
    fire_and_forget(
        _memory.memorize_facts(chat_id, wrapped, source_type="voice_transcript"),
        "voice_transcript")


async def _process(message: types.Message, bot) -> None:
    user = message.from_user
    if user is None or (_bot_id is not None and user.id == _bot_id):
        return
    media = getattr(message, "voice", None) or getattr(message, "video_note", None)
    if media is None:
        return
    duration = getattr(media, "duration", 0) or 0
    if duration > settings.VOICE_MAX_DURATION_SECONDS:
        # Edge case #4: файл НЕ качаем.
        await message.reply(random.choice(VT_TOO_LONG_PHRASES))
        return
    # Epic 72 (74.B/D272): у форварда в bold — АВТОР источника; не-форвард —
    # прежний каскад от from_user (D268-поведение, байт-в-байт).
    origin = getattr(message, "forward_origin", None)
    is_forward = origin is not None
    name = _resolve_transcript_author(message)
    is_video_note = getattr(message, "video_note", None) is not None
    suffix = ".mp4" if is_video_note else ".ogg"
    audio_format = "mp4" if is_video_note else "ogg"
    chat_id = message.chat.id

    await _safe_typing(bot, chat_id)
    fd, path = tempfile.mkstemp(prefix="vt_", suffix=suffix)
    os.close(fd)
    try:
        # Хотфикс v2.46.1 (Epic 69) + Epic 78 (D292): при локальном Bot API
        # файл берётся с диска хоста; иначе — прежний bot.download.
        await _fetch_media_to_tmp(bot, media, path)
        await _safe_typing(bot, chat_id)          # индикация на время API-запросов
        try:
            text = await _service.transcribe_voice(path, audio_format)
        except EmptyTranscript:
            logger.info("[transcribe] empty transcript | chat=%s user=%s",
                        chat_id, user.id)
            await message.reply(random.choice(VT_SILENCE_PHRASES))
            return
        except TranscriptionUnavailable as exc:
            logger.warning("[transcribe] all strategies failed | chat=%s | error=%s",
                           chat_id, exc)
            await message.reply(random.choice(VT_ALL_FAILED_PHRASES))
            return
    finally:
        # Cleanup temp ГАРАНТИРОВАННО на 100% путей (Section 71.4 п.5).
        try:
            os.unlink(path)
        except OSError:
            pass

    # Успех (D268/D272): HTML, html.escape; ответ СТРОГО реплаем на голосовое.
    # Анкер «🗣:» сохраняет позицию сразу после префикса (детектор 74.C).
    escaped_name = html.escape(name)              # html.escape, НЕ xml!
    escaped_text = html.escape(text)
    label = f"<b>{escaped_name}</b>"
    if is_forward:
        forwarder = _aliases.resolve(
            user.id,
            nickname=_build_nickname(user),
            username=getattr(user, "username", None),
        )
        label += f" (переслал {html.escape(forwarder)})"
    await message.reply(
        f"{label} 🗣: <i>{escaped_text}</i>", parse_mode="HTML")
    logger.info("[transcribe] OK | chat=%s user=%s len=%d",
                chat_id, user.id, len(text))
    await _inject_memory(
        message, name, text, is_video_note,
        forward_source=_extract_forward_source(origin) if is_forward else None)


@voice_transcription_router.message(F.voice | F.video_note)
async def voice_transcription_handler(message: types.Message, bot=None):
    """Observer-стиль (D267): любые сбои — WARNING, апдейт НЕ потребляется."""
    try:
        if _service is None or bot is None:
            return UNHANDLED
        await _process(message, bot)
    except Exception:
        logger.warning("[transcribe] unexpected error", exc_info=True)
    return UNHANDLED
