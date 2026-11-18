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
import types as pytypes
from pathlib import Path

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.enums import ChatAction

from config.settings import settings
from services import feature_gates
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
    MediaDownloadError,
    fetch_media_to_tmp as _fetch_media_to_tmp,
    local_files_subdir as _local_files_subdir,
)
from services import native_media
from services.summary_memory import fire_and_forget
from services.summary_xml import _MEDIA_DESCRIPTIONS as _MEDIA_PLACEHOLDERS
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


# Плейсхолдеры медиа-строк smart_messages — единый словарь summary_xml
# (_MEDIA_DESCRIPTIONS): их наличие ≠ готовая расшифровка. F19 — база
# идемпотентности форс-повтора (voice_note мапится на «video» → «[видео]»).
_PLACEHOLDER_TEXTS = frozenset(_MEDIA_PLACEHOLDERS.values())


async def _row_has_transcript(chat_id: int, message_id: int,
                              media_caption: str | None = None,
                              db=None) -> bool:
    """True — строка smart_messages уже несла расшифровку.

    F19 (ADR-1024-20 §2.6): защита от дублей GraphRAG-фактов при
    принудительном повторе. Расшифровкой НЕ считается пустая строка, строка-
    плейсхолдер медиа и **подпись исходного медиа** (observer кладёт в ``text``
    ``message.text or message.caption`` — на ГС/кружке с подписью это caption,
    а не транскрипт). Нет БД/API/строки → False (поведение прежнее)."""
    source = db if db is not None else _db
    if source is None:
        return False
    getter = getattr(source, "get_smart_message_by_tg_id", None)
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
    if not old or old in _PLACEHOLDER_TEXTS:
        return False
    caption = str(media_caption or "").strip()
    if caption and old == caption:
        return False
    return True


async def _inject_memory(message: types.Message, name: str, text: str,
                         is_video_note: bool,
                         forward_source: str | None = None, *,
                         force: bool = False, db=None, memory=None) -> int:
    """CRITICAL (D267): двойная инъекция — L2-строка + GraphRAG-факт.
    Epic 72 (74.B.3): у форвардов факт несёт forward_from-атрибуцию.
    F19: при ``force=True`` ``memorize_facts`` пропускается, если строка уже
    содержала расшифровку (идемпотентность повторного «транскрипта»).

    VMQ-V (VOICE-01 P0, 09.11.2026): текст STT пишется как ВЕРСИЯ содержимого
    исходного source-ref (`set_smart_message_transcript(status='ready')`:
    монотонная `transcript_revision`, `transcript_updated_at`), а не как
    независимая реплика «пользователь сказал ещё раз». Ответ бота с
    расшифровкой в `smart_messages` не попадает вовсе (observer бот-сообщения
    не сохраняет), поэтому второй пользовательской реплики не возникает.

    Возвращает `transcript_revision` (=-1, если строки нет/запись не удалась):
    replay-путь использует это же значение для честного отчёта, не создавая
    второй записи."""
    db = db if db is not None else _db
    memory = memory if memory is not None else _memory
    chat_id = message.chat.id
    # Подпись медиа (observer пишет её в text): не путать с расшифровкой.
    caption = (getattr(message, "text", None)
               or getattr(message, "caption", None))
    already = (await _row_has_transcript(chat_id, message.message_id, caption,
                                         db=db)
               if force else False)
    revision = -1
    try:
        revision = await db.set_smart_message_transcript(
            chat_id, message.message_id, status="ready", text=text)
        if revision < 0:
            logger.info("[transcribe] smart_message row not found | chat=%s msg=%s",
                        chat_id, message.message_id)
        else:
            logger.info("[transcribe] transcript stored | chat=%s msg=%s | "
                        "revision=%s", chat_id, message.message_id, revision)
    except Exception:
        logger.warning("[transcribe] smart_message transcript write failed | "
                       "chat=%s", chat_id, exc_info=True)
    if memory is None or already:
        if already:
            logger.info("[transcribe] repeat — memorize skipped (row already "
                        "has transcript) | chat=%s msg=%s",
                        chat_id, message.message_id)
        return revision
    media_type = "video_note" if is_video_note else "voice"
    wrapped = wrap_media_fact(media_type, name, text,
                              forward_source=forward_source)
    fire_and_forget(
        memory.memorize_facts(chat_id, wrapped, source_type="voice_transcript"),
        "voice_transcript")
    return revision


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


async def _mark_transcript_status(message, status: str, reason: str = "",
                                  *, db=None) -> None:
    """Честный статус версии расшифровки у исходного source-ref (VMQ-V).

    Вызывается ДО/вместо записи текста, чтобы Writer мог отличить «ещё идёт»,
    «не удалось» и «расшифровки нет» — без выдумывания содержимого. Ошибка
    записи статуса НЕ ломает STT-поток (fail-open): отсутствие статуса
    читатель трактует как «ещё не расшифровано»."""
    source = db if db is not None else _db
    if source is None:
        return
    try:
        await source.set_smart_message_transcript(
            message.chat.id, getattr(message, "message_id", None),
            status=status, reason=reason)
    except Exception:
        logger.debug("[transcribe] transcript status write failed | chat=%s",
                     getattr(getattr(message, "chat", None), "id", None),
                     exc_info=True)


def _download_failure_reason(stage: str, error_class: str) -> str:
    """Терминальная причина отказа скачивания для `transcript_reason`.

    Формат `download_<stage>_<class>` (только `[a-z0-9_]`, ≤120 симв.) —
    стадия и класс из `MediaDownloadError`, без путей/токена/URL. Причина
    доезжает до Writer'а и чекапа (`last_error.reason_code`) как есть.
    """
    clean = []
    for part in (stage, error_class):
        value = re.sub(r"[^a-z0-9_]", "", str(part or "").lower())
        clean.append(value or "unknown")
    return ("download_" + "_".join(clean))[:120]


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
        await _mark_transcript_status(media_message, "unavailable",
                                      "duration_limit")
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
        # Хотфикс v2.46.1 (Epic 69) + Epic 78 (D292) + P0 18.11.2026: медиа
        # получает единый транспорт (local file → aiogram → cloud fallback).
        # Отказ скачивания — ТЕРМИНАЛЬНЫЙ статус с конкретной стадией/классом,
        # а не вечный pending: STT ещё не запускался, и pending здесь был бы
        # ложью. Ответ в чат не отправляем (у голосового пути уже может быть
        # прежняя расшифровка; ошибка скачивания не повод для второго ответа).
        try:
            await _fetch_media_to_tmp(bot, media, path, site="transcribe")
        except MediaDownloadError as exc:
            reason = _download_failure_reason(exc.stage, exc.error_class)
            await _mark_transcript_status(media_message, "failed", reason)
            logger.warning(
                "[transcribe] download failed | chat=%s msg=%s | stage=%s | "
                "class=%s | retryable=%s", chat_id,
                getattr(media_message, "message_id", None), exc.stage,
                exc.error_class, exc.retryable)
            return False
        except Exception:
            await _mark_transcript_status(
                media_message, "failed", "download_error")
            logger.warning(
                "[transcribe] download failed | chat=%s msg=%s | "
                "unclassified", chat_id,
                getattr(media_message, "message_id", None), exc_info=True)
            raise
        # VMQ-V: «расшифровка идёт» — durable статус ТОЛЬКО когда файл уже
        # получен и STT реально запускается (а не до скачивания).
        await _mark_transcript_status(media_message, "pending")
        await _safe_typing(bot, chat_id)          # индикация на время API-запросов
        try:
            text = await _service.transcribe_voice(path, audio_format)
        except EmptyTranscript:
            logger.info("[transcribe] empty transcript | chat=%s user=%s",
                        chat_id, user.id)
            await _mark_transcript_status(media_message, "unavailable",
                                          "empty_transcript")
            await _reply_media(bot, media_message, reply_to_id,
                               random.choice(VT_SILENCE_PHRASES))
            return False
        except TranscriptionUnavailable as exc:
            logger.warning("[transcribe] all strategies failed | chat=%s | error=%s",
                           chat_id, exc)
            await _mark_transcript_status(media_message, "failed",
                                          "stt_failed")
            await _reply_media(bot, media_message, reply_to_id,
                               random.choice(VT_ALL_FAILED_PHRASES))
            return False
        except Exception:
            # Нештатный сбой STT — честный терминальный статус, а не «идёт».
            await _mark_transcript_status(media_message, "failed", "stt_error")
            raise
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


# Тристейт командного форс-повтора (F19, review iter2): нейтральный ответ
# вызывающего уместен ТОЛЬКО при отсутствии цели/сервиса. После деградации ASR
# фраза деградации уже отправлена `transcribe_media_message` — второй ответ
# слать нельзя (иначе «нет цели» поверх реальной причины).
FORCE_REPEAT_NO_TARGET = "no_target"   # цели/сервиса нет — ответа НЕ было
FORCE_REPEAT_HANDLED = "handled"       # цель была: ответ (деградация) отправлен
FORCE_REPEAT_SENT_OK = "sent_ok"       # цель была: успешный транскрипт отправлен


async def force_repeat_from_reply(bot, command_message) -> str:
    """F19 (ADR-1024-20 §2.3): команда «транскрипт» → принудительный повтор
    транскрибации ГС/кружка. Цель: реплай на ``voice``/``video_note`` (или
    собственное медиа сообщения-команды).

    Возвращает тристейт: ``no_target`` — цели/сервиса нет, ответа не было
    (вызывающий отдаёт прежний нейтральный ответ); ``handled`` — цель была,
    но ASR деградировал и фраза деградации УЖЕ отправлена; ``sent_ok`` —
    цель была и успешный транскрипт отправлен. Исключения — наружу
    (вызывающий делает нейтральный фолбэк).

    MOD-ACL-UX-01 M2.1 (D2): командный форс-повтор — тоже потребление
    модуля «Транскрипция»: гейт ``flags.enable_voice_transcription``
    решается per chat каноническим резолвером ДО любого STT (GLOBAL default
    → CHAT override). CHAT OFF при GLOBAL ON транскрипт по команде НЕ
    запускает; ошибка резолвера → fail-closed (``module_enabled`` → False).
    """
    chat_id = getattr(getattr(command_message, "chat", None), "id", None)
    if chat_id is None:
        return FORCE_REPEAT_NO_TARGET
    if not await feature_gates.module_enabled(
            chat_id, key="flags.enable_voice_transcription",
            default=settings.ENABLE_VOICE_TRANSCRIPTION):
        logger.info("[transcribe] force repeat disabled for chat | chat=%s",
                    chat_id)
        return FORCE_REPEAT_NO_TARGET
    if _service is None or bot is None:
        return FORCE_REPEAT_NO_TARGET
    # Единый выбор цели (своё > реплай) — тот же хелпер, что в классификации
    # handlers/youtube.py (`_resolve_voice_media`), порядок не расходится.
    media_message = native_media.voice_media_message(command_message)
    if media_message is None:
        return FORCE_REPEAT_NO_TARGET
    logger.info("[transcribe] force repeat | chat=%s",
                getattr(getattr(media_message, "chat", None), "id", None))
    sent = await transcribe_media_message(
        media_message, bot,
        reply_to_id=getattr(media_message, "message_id", None), force=True)
    return FORCE_REPEAT_SENT_OK if sent else FORCE_REPEAT_HANDLED


def _id_prefix(value, limit: int = 6) -> str:
    """R17-safe префикс идентификатора для логов (полный не пишем)."""
    return str(value or "")[:limit]


def _row_field(row, name: str):
    """Поле sqlite Row/словаря без падения на чужом типе."""
    try:
        return dict(row).get(name)
    except (TypeError, ValueError):
        return None


async def replay_saved_media(bot, *, chat_id: int, message_id: int,
                             file_id: str, media_type: str = "",
                             service=None, db=None, memory=None) -> dict:
    """Повторная транскрибация СОХРАНЁННОГО voice/video_note без Update.

    P0 18.11.2026 (уточнение владельца): Telegram не отдаёт файл по
    `message_id`, поэтому replay получает `file_id` сохранённого сообщения
    явно (из ранее наблюдённого update/ручного списка) и привязывает его к
    существующему source-ref `(chat_id, message_id)`. Никакого нового
    Telegram-клиента/сессии/флагов: тот же `fetch_media_to_tmp` → тот же STT →
    та же durable-версия `smart_messages` (+ существующая идемпотентная
    инъекция памяти).

    Replay НИКОГДА не отвечает в чат: ни успех, ни ошибка не отправляют
    сообщение. Повторный replay с тем же текстом не создаёт дубль (та же
    `transcript_revision`, `memorize_facts` пропускается). Ошибка скачивания
    даёт терминальный `failed` с причиной `download_<stage>_<class>` и НЕ
    трогает ранее полученный текст; `pending` ставится только перед реальным
    STT.

    Возвращает R17-safe отчёт: `{chat_id, message_id, source_ref, status,
    reason, stage, revision, chars, asr, persisted}`. Полный `file_id` в
    отчёт/логи не попадает (только префикс).
    """
    db = db if db is not None else _db
    service = service if service is not None else _service
    memory = memory if memory is not None else _memory
    report = {
        "chat_id": chat_id, "message_id": message_id,
        "source_ref": f"tg:{message_id}", "status": "unavailable",
        "reason": "", "stage": "", "revision": 0, "chars": 0,
        "asr": "not_run", "persisted": False,
        "file_id_prefix": _id_prefix(file_id),
    }
    try:
        chat_id = int(chat_id)
        message_id = int(message_id)
    except (TypeError, ValueError):
        report["reason"] = "invalid_ids"
        return report
    if db is None:
        report["reason"] = "no_db"
        return report
    getter = getattr(db, "get_smart_message_by_tg_id", None)
    if getter is None:
        report["reason"] = "no_db_reader"
        return report
    try:
        row = await getter(chat_id, message_id)
    except Exception:
        report["reason"] = "source_read_failed"
        return report
    if row is None:
        report["reason"] = "source_missing"
        return report
    row_type = str(_row_field(row, "media_type") or "")
    status_raw = str(_row_field(row, "transcript_status") or "")
    is_video_note = (str(media_type) == "video_note"
                     or (not media_type and row_type == "video"))
    if str(media_type) == "voice":
        is_video_note = False
    if row_type not in ("voice", "video") and not media_type:
        report["reason"] = "not_voice_source"
        return report
    if row_type == "video" and not status_raw and str(media_type) != "video_note":
        report["reason"] = "not_voice_source"
        return report
    if service is None:
        report["reason"] = "stt_unavailable"
        return report
    try:
        report["revision"] = int(_row_field(row, "transcript_revision") or 0)
    except (TypeError, ValueError):
        report["revision"] = 0
    previous_text = str(_row_field(row, "text") or "").strip()
    if previous_text:
        report["chars"] = len(previous_text)
    author = str(_row_field(row, "author_name") or MEDIA_UNKNOWN_AUTHOR)
    caption = _row_field(row, "caption")
    proxy = pytypes.SimpleNamespace(
        chat=pytypes.SimpleNamespace(id=chat_id), message_id=message_id,
        text=None, caption=caption, from_user=None)
    suffix = ".mp4" if is_video_note else ".ogg"
    audio_format = "mp4" if is_video_note else "ogg"

    fd, path = tempfile.mkstemp(prefix="vt_replay_", suffix=suffix)
    os.close(fd)

    async def _fail(reason: str, *, stage: str = "",
                    error_class: str = "") -> dict:
        await _mark_transcript_status(proxy, "failed", reason, db=db)
        report.update(status="failed", reason=reason, stage=stage,
                      persisted=True, asr="not_run")
        logger.warning(
            "[transcribe] replay failed | chat=%s msg=%s | stage=%s | "
            "class=%s", chat_id, message_id, stage or "-",
            error_class or "-")
        return report

    try:
        try:
            await _fetch_media_to_tmp(bot, pytypes.SimpleNamespace(
                file_id=file_id), path, site="transcribe")
        except MediaDownloadError as exc:
            reason = _download_failure_reason(exc.stage, exc.error_class)
            return await _fail(reason, stage=exc.stage,
                               error_class=exc.error_class)
        except Exception:
            await _mark_transcript_status(proxy, "failed", "download_error",
                                          db=db)
            report.update(status="failed", reason="download_error",
                          stage="download", persisted=True, asr="not_run")
            logger.warning(
                "[transcribe] replay download failed | chat=%s msg=%s | "
                "unclassified", chat_id, message_id, exc_info=True)
            return report
        await _mark_transcript_status(proxy, "pending", db=db)
        report["stage"] = "asr"
        try:
            text = await service.transcribe_voice(path, audio_format)
        except EmptyTranscript:
            await _mark_transcript_status(proxy, "unavailable",
                                          "empty_transcript", db=db)
            report.update(status="unavailable",
                          reason="empty_transcript", persisted=True,
                          asr="empty")
            return report
        except TranscriptionUnavailable as exc:
            logger.warning("[transcribe] replay STT unavailable | chat=%s "
                           "msg=%s | error=%s", chat_id, message_id, exc)
            await _mark_transcript_status(proxy, "failed", "stt_failed",
                                          db=db)
            report.update(status="failed", reason="stt_failed",
                          persisted=True, asr="failed")
            return report
        except Exception:
            await _mark_transcript_status(proxy, "failed", "stt_error",
                                          db=db)
            report.update(status="failed", reason="stt_error",
                          persisted=True, asr="error")
            logger.warning("[transcribe] replay STT error | chat=%s msg=%s",
                           chat_id, message_id, exc_info=True)
            return report
        if not str(text or "").strip():
            await _mark_transcript_status(proxy, "unavailable",
                                          "empty_transcript", db=db)
            report.update(status="unavailable",
                          reason="empty_transcript", persisted=True,
                          asr="empty")
            return report
        revision = await _inject_memory(
            proxy, author, text, is_video_note, force=True,
            db=db, memory=memory)
        if revision < 0:
            report.update(status="failed", reason="persist_failed",
                          stage="persist", persisted=False, asr="ok")
            return report
        report.update(status="ready", reason="", stage="persisted",
                      revision=revision, chars=len(str(text or "")),
                      asr="ok", persisted=True)
        logger.info("[transcribe] replay OK | chat=%s msg=%s | revision=%s | "
                    "chars=%d", chat_id, message_id, report["revision"],
                    report["chars"])
        return report
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def _process(message: types.Message, bot) -> None:
    """Авто-путь 0i (observer): тонкая обёртка над ``transcribe_media_message``
    (F19) — поведение байт-в-байт (``force=False``, ответ на само медиа)."""
    await transcribe_media_message(
        message, bot, reply_to_id=message.message_id, force=False)


@voice_transcription_router.message(F.voice | F.video_note)
async def voice_transcription_handler(message: types.Message, bot=None):
    """Observer-стиль (D267): любые сбои — WARNING, апдейт НЕ потребляется.

    F5 (ТЗ §18H(4), архитектура §5.1): AND-гейт bot.py переезжает в рантайм —
    только СВОЙ флаг ``flags.enable_voice_transcription`` (зависимость от
    ``flags.summary_enabled`` УДАЛЕНА: роутер регистрируется всегда).
    MOD-ACL-UX-01 M2.1: флаг решается per chat каноническим резолвером
    (GLOBAL-дефолт → CHAT-override)."""
    try:
        # MOD-ACL-UX-01 M2.1: флаг модуля решается per chat (GLOBAL-дефолт →
        # CHAT-override) через канонический резолвер; глобальный hot.get
        # игнорировал настройку этого чата.
        if not await feature_gates.module_enabled(
                message.chat.id, key="flags.enable_voice_transcription",
                default=settings.ENABLE_VOICE_TRANSCRIPTION):
            return UNHANDLED
        if _service is None or bot is None:
            return UNHANDLED
        await _process(message, bot)
    except Exception:
        logger.warning("[transcribe] unexpected error", exc_info=True)
    return UNHANDLED
