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
import tempfile
from pathlib import Path

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.enums import ChatAction

from config.settings import settings
from services import hot_config as hot
from handlers.summary import _extract_forward_source
# Bugfix 04.09.2026 (Часть 1): общие хелперы автора/факта — из media_common
# (реэкспорт теми же именами: внешние точки/тесты не меняются);
# скачивание — общий модуль services/media_download.
from handlers.media_common import (
    MEDIA_UNKNOWN_AUTHOR,
    _build_nickname,
    _resolve_transcript_author,
    set_media_aliases,
    wrap_media_fact,
)
from services.media_download import (
    fetch_media_to_tmp as _fetch_media_to_tmp,
    local_files_subdir as _local_files_subdir,
)
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

# Совместимость: константа «Неизвестный» доступна под прежним именем.
_VT_UNKNOWN_AUTHOR = MEDIA_UNKNOWN_AUTHOR

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
    set_media_aliases(aliases)


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
    if duration > hot.get("limits.voice_max_duration_seconds", settings.VOICE_MAX_DURATION_SECONDS):
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
