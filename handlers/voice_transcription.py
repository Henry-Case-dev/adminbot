"""Epic 67 — Voice-to-Text handler (Section 71.3/71.4, D267/D268).

Роутер 0i — ПОСЛЕ summary_observer 0a и direct_chat 0h, ДО admin_commands.
Observer-стиль: ловит СТРОГО F.voice | F.video_note (F.audio/F.document не
триггерят) и ВСЕГДА возвращает UNHANDLED — апдейт никогда не потребляется.

Флоу: лимит длительности → TYPING → скачивание во временный файл (.ogg/.mp4)
→ каскад Groq→OpenRouter → реплай «<b>{name}</b> 🗣: <i>{text}</i>»
(parse_mode=HTML, D268) строго на голосовое/кружочек → двойная инъекция в
память: UPDATE smart_messages.text вместо плейсхолдера + memorize_facts
(source_type='voice_transcript', fire_and_forget). Temp-файл удаляется в
finally на 100% путей. Имя отправителя — каскад AliasResolver
(Алиас → Никнейм → Юзернейм → ID).
"""
import html
import logging
import os
import random
import tempfile
from datetime import datetime, timezone

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.enums import ChatAction

from config.settings import settings
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


def wrap_media_fact(media_type: str, sender: str, text: str) -> str:
    """Обёртка транскрипта для GraphRAG-экстрактора (D267):
    '<MediaMessage type="voice" sender="..." timestamp="<ISO8601 UTC>">...</MediaMessage>'.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    return (f'<MediaMessage type="{media_type}" sender="{sender}" '
            f'timestamp="{timestamp}">{text}</MediaMessage>')


async def _safe_typing(bot, chat_id: int) -> None:
    try:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
    except Exception:
        pass


async def _inject_memory(message: types.Message, name: str, text: str,
                         is_video_note: bool) -> None:
    """CRITICAL (D267): двойная инъекция — L2-строка + GraphRAG-факт."""
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
    wrapped = wrap_media_fact(media_type, name, text)
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
    name = _aliases.resolve(
        user.id,
        nickname=_build_nickname(user),
        username=getattr(user, "username", None),
    )
    is_video_note = getattr(message, "video_note", None) is not None
    suffix = ".mp4" if is_video_note else ".ogg"
    audio_format = "mp4" if is_video_note else "ogg"
    chat_id = message.chat.id

    await _safe_typing(bot, chat_id)
    fd, path = tempfile.mkstemp(prefix="vt_", suffix=suffix)
    os.close(fd)
    try:
        # Хотфикс v2.46.1 (Epic 69): Bot.download принимает file_id, сам
        # делает get_file внутри (aiogram 3.x — File без IO-методов).
        await bot.download(media.file_id, destination=path)
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

    # Успех (D268): HTML, html.escape; ответ СТРОГО реплаем на голосовое.
    escaped_name = html.escape(name)              # html.escape, НЕ xml!
    escaped_text = html.escape(text)
    await message.reply(
        f"<b>{escaped_name}</b> 🗣: <i>{escaped_text}</i>", parse_mode="HTML")
    logger.info("[transcribe] OK | chat=%s user=%s len=%d",
                chat_id, user.id, len(text))
    await _inject_memory(message, name, text, is_video_note)


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
