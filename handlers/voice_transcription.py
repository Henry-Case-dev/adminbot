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

Раунд 10.24 (F19, ADR-1024-20 §2.3) — принудительный повтор по команде
«транскрипт»: тело авто-пути вынесено в ``transcribe_media_message(...,
force=...)`` (поведение 0i байт-в-байт), публичная точка
``force_repeat_from_reply(bot, command_message)`` переиспользуется
``handlers/youtube.py`` (0e — текстовая команда приходит раньше 0i).
Идемпотентность: ``memorize_facts`` при force-повторе — только если строка
ещё не несла расшифровку (защита от дублей GraphRAG-фактов).
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


# Плейсхолдеры медиа-строк smart_messages (summary_xml._MEDIA_DESCRIPTIONS):
# их наличие ≠ готовая расшифровка. F19 — база идемпотентности форс-повтора.
_PLACEHOLDER_TEXTS = frozenset({
    "[голосовое]", "[кружок]", "[видео]", "[аудио]", "[файл]",
    "[медиа]", "[фото]", "[гифка]", "[стикер]",
})


async def _row_has_transcript(chat_id: int, message_id: int) -> bool:
    """True — строка smart_messages уже несла расшифровку (не плейсхолдер).

    F19 (ADR-1024-20 §2.6): защита от дублей GraphRAG-фактов при
    принудительном повторе. Нет БД/API/строки → False (поведение прежнее)."""
    if _db is None:
        return False
    getter = getattr(_db, "get_smart_message_by_tg_id", None)
    if getter is None:
        return False
    try:
        row = await getter(chat_id, message_id)
    except Exception:
        logger.warning("[transcribe] smart_message read failed | chat=%s",
                       chat_id)
        return False
    if row is None:
        return False
    try:
        old = str(dict(row).get("text") or "").strip()
    except (TypeError, ValueError):
        old = ""
    return bool(old) and old not in _PLACEHOLDER_TEXTS


async def _inject_memory(message: types.Message, name: str, text: str,
                         is_video_note: bool,
                         forward_source: str | None = None, *,
                         force: bool = False) -> None:
    """CRITICAL (D267): двойная инъекция — L2-строка + GraphRAG-факт.
    Epic 72 (74.B.3): у форвардов факт несёт forward_from-атрибуцию.
    F19: при ``force=True`` ``memorize_facts`` пропускается, если строка уже
    содержала расшифровку (идемпотентность повторного «транскрипта»)."""
    chat_id = message.chat.id
    already = (await _row_has_transcript(chat_id, message.message_id)
               if force else False)
    try:
        updated = await _db.update_smart_message_text(
            chat_id, message.message_id, text)
        if not updated:
            logger.info("[transcribe] smart_message row not found | chat=%s msg=%s",
                        chat_id, message.message_id)
    except Exception:
        logger.warning("[transcribe] smart_message text update failed | chat=%s",
                       chat_id, exc_info=True)
    if _memory is None or already:
        if already:
            logger.info("[transcribe] repeat — memorize skipped (row already "
                        "has transcript) | chat=%s msg=%s",
                        chat_id, message.message_id)
        return
    media_type = "video_note" if is_video_note else "voice"
    wrapped = wrap_media_fact(media_type, name, text,
                              forward_source=forward_source)
    fire_and_forget(
        _memory.memorize_facts(chat_id, wrapped, source_type="voice_transcript"),
        "voice_transcript")


def _has_voice_media(message) -> bool:
    """True — у сообщения есть ``voice``/``video_note`` с валидным ``file_id``.
    Строгая проверка (str file_id) — не путаем MagicMock-атрибуты с медиа."""
    for attr in ("voice", "video_note"):
        media = getattr(message, attr, None)
        if media is None:
            continue
        fid = getattr(media, "file_id", None)
        if isinstance(fid, str) and fid:
            return True
    return False


async def _reply_media(bot, media_message, reply_to_id, text,
                       parse_mode: str | None = None) -> None:
    """Ответ на целевое медиа (F19): ``reply_to_id`` == message_id медиа →
    прежний ``message.reply`` (байт-в-байт авто-путь); иное → ``bot.send_message``
    с ``reply_to_message_id``. ``parse_mode`` — только локальный (HTML)."""
    own_id = getattr(media_message, "message_id", None)
    target = reply_to_id if reply_to_id is not None else own_id
    if target is None or target == own_id:
        if parse_mode is not None:
            await media_message.reply(text, parse_mode=parse_mode)
        else:
            await media_message.reply(text)
        return
    kwargs = {"reply_to_message_id": target}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    await bot.send_message(media_message.chat.id, text, **kwargs)


async def transcribe_media_message(media_message, bot, *,
                                   reply_to_id: int | None = None,
                                   force: bool = False) -> bool:
    """Скачивание → STT → курсив (D268) → инъекция памяти (идемпотентно).

    ``force=True`` — повтор по явной команде «транскрипт»: STT запускается
    всегда свежим (кэш/готовый текст не читаем), ``memorize_facts`` — только
    если строка ещё не содержала расшифровку. ``reply_to_id`` — целевое
    сообщение ответа (по умолчанию — сам медиа-месседж). Возвращает True при
    успешной транскрибации. Temp-файл удаляется в finally на 100% путей."""
    user = getattr(media_message, "from_user", None)
    if user is None or (_bot_id is not None and user.id == _bot_id):
        return False
    media = getattr(media_message, "voice", None) \
        or getattr(media_message, "video_note", None)
    if media is None:
        return False
    chat_id = media_message.chat.id
    if _service is None:
        logger.warning("[transcribe] STT service unavailable | chat=%s", chat_id)
        return False
    duration = getattr(media, "duration", 0) or 0
    if duration > hot.get("limits.voice_max_duration_seconds",
                          settings.VOICE_MAX_DURATION_SECONDS):
        # Edge case #4: файл НЕ качаем.
        await _reply_media(bot, media_message, reply_to_id,
                           random.choice(VT_TOO_LONG_PHRASES))
        return False
    # Epic 72 (74.B/D272): у форварда в bold — АВТОР источника; не-форвард —
    # прежний каскад от from_user (D268-поведение, байт-в-байт).
    origin = getattr(media_message, "forward_origin", None)
    is_forward = origin is not None
    name = _resolve_transcript_author(media_message)
    is_video_note = getattr(media_message, "video_note", None) is not None
    suffix = ".mp4" if is_video_note else ".ogg"
    audio_format = "mp4" if is_video_note else "ogg"

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
            await _reply_media(bot, media_message, reply_to_id,
                               random.choice(VT_SILENCE_PHRASES))
            return False
        except TranscriptionUnavailable as exc:
            logger.warning("[transcribe] all strategies failed | chat=%s | error=%s",
                           chat_id, exc)
            await _reply_media(bot, media_message, reply_to_id,
                               random.choice(VT_ALL_FAILED_PHRASES))
            return False
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
    await _reply_media(bot, media_message, reply_to_id,
                       f"{label} 🗣: <i>{escaped_text}</i>", parse_mode="HTML")
    logger.info("[transcribe] OK | chat=%s user=%s len=%d force=%s",
                chat_id, user.id, len(text), bool(force))
    await _inject_memory(
        media_message, name, text, is_video_note,
        forward_source=_extract_forward_source(origin) if is_forward else None,
        force=force)
    return True


async def force_repeat_from_reply(bot, command_message) -> bool:
    """F19 (ADR-1024-20 §2.3): команда «транскрипт» → принудительный повтор
    транскрибации ГС/кружка. Цель: реплай на ``voice``/``video_note`` (или
    собственное медиа сообщения-команды). Возвращает True при успехе; False —
    цели нет (вызывающий отдаёт прежний нейтральный ответ)."""
    if _service is None or bot is None:
        return False
    reply = getattr(command_message, "reply_to_message", None)
    media_message = None
    if reply is not None and _has_voice_media(reply):
        media_message = reply
    elif _has_voice_media(command_message):
        media_message = command_message
    if media_message is None:
        return False
    logger.info("[transcribe] force repeat | chat=%s",
                getattr(getattr(media_message, "chat", None), "id", None))
    return await transcribe_media_message(
        media_message, bot,
        reply_to_id=getattr(media_message, "message_id", None), force=True)


async def _process(message: types.Message, bot) -> None:
    """Авто-путь 0i (observer): тонкая обёртка над ``transcribe_media_message``
    (F19) — поведение байт-в-байт (``force=False``, ответ на само медиа)."""
    await transcribe_media_message(
        message, bot, reply_to_id=message.message_id, force=False)


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
