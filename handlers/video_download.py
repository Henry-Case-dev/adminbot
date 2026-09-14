"""Epic 66 — Video Download handler (Section 70.5, D265).

Роутер 4e (после 4d olya, до 5 slavik). Триггер: «скачай/загрузи/стяни/
спизди/скачать» в НАЧАЛЕ строки (IGNORECASE) + хотя бы одна http(s)-ссылка
(в тексте/caption или в реплае). Не-триггер → UNHANDLED; триггер → консьюм.

Флоу (ТЗ): 1 ссылка → сразу выбор качества; >1 → «читаю ссылки…» →
yt-dlp titles → выбор видео (vdv:<idx>) → выбор качества (vd:<quality>).
Перед скачиванием сообщение с клавиатурой удаляется СТРОГО (перехват
TelegramBadRequest → RIGHTS_ERROR реплаем на триггер, скачивание
ПРОДОЛЖАЕТСЯ). Ответ — строго реплай на триггер, FSInputFile +
supports_streaming=True; файл удаляется в finally при ЛЮБОМ исходе.
"""
import asyncio
import logging
import os
import random
import re
import tempfile
import time
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from services import command_prefix
from services import hot_config as hot
from services.media_send import send_quality_menu
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.progress_reporter import (
    ProgressReporter,
    get_active,
    register,
    unregister,
)
from services.smartmodule_throttling import CooldownTracker, format_remaining_time
from services.tool_router import (
    peek_tool_download_pending,
    pop_tool_download_pending,
)
from tools.video_download_phrases import (
    VD_BUSY_PHRASES,
    VD_COOLDOWN_PHRASES,
    VD_ERROR_PHRASES,
    VD_MULTI_LINK_PHRASES,
    VD_NO_LINK_PHRASES,
    VD_RIGHTS_ERROR_PHRASES,
    VD_SERVICE_DOWN_PHRASES,
    VD_TOO_BIG_PHRASES,
    VD_UNAVAILABLE_PHRASES,
)
from tools.video_downloader import (
    CobaltServiceDownError,
    DownloadBusyError,
    DownloadError,
    DownloadTooBigError,
    DownloadUnavailableError,
    ProbeResult,
    VideoDownloader,
    is_direct_media_url,
    log_download_env_once,
)

logger = logging.getLogger(__name__)

video_download_router = Router(name="video_download")

_downloader = None                                  # VideoDownloader (DI)
_cooldown = CooldownTracker(settings.DOWNLOAD_COOLDOWN)

# Section 70.5 + раунд 10.15 (F6, T-1597): обязательный префикс (Имя/«Бот,»);
# триггер ищется в ОСТАТКЕ. F6-U1: «спизди»/«скачать» из реестра убраны.
_TRIGGER_RE = re.compile(r"^\s*(скачай|загрузи|стяни)\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")


def _command_body(message: types.Message) -> str | None:
    """Остаток сообщения ПОСЛЕ обязательного префикса; None — префикса нет."""
    text = message.text or message.caption or ""
    if not isinstance(text, str):
        return None
    tok, body = command_prefix.split_prefix(text)
    if tok is None:
        return None
    return body

_PENDING_TTL_SECONDS = 600                          # Section 70.5 п.4
_PENDING: dict[tuple[int, int], dict] = {}
_FASTTRACK_QUALITY_PREFIX = "vd:"                   # callback меню Fast-Track


def setup_video_download(downloader: VideoDownloader, db=None) -> None:
    """DI: VideoDownloader. Вызывается из bot.py on_startup (70.7).
    Dual-layer cooldown (63.1): db + THROTTLE_PERSISTENT_ENABLED → персистентный
    трекер (throttle_state, scope='video_download'), иначе in-memory.
    Прод-хотфикс 30.08.2026: ffmpeg-чек при старте (WARNING, если нет —
    merge yt-dlp (postprocess) будет падать с «Invalid data found…»)."""
    import shutil
    if shutil.which("ffmpeg") is None:
        logger.warning("[videodl] ffmpeg НЕ найден в PATH — merge yt-dlp "
                       "(postprocess) будет падать (Invalid data found)")
    global _downloader, _cooldown
    _downloader = downloader
    _cooldown = make_cooldown(
        "video_download", settings.DOWNLOAD_COOLDOWN, db)


def _cooldown_phrase(remaining: float) -> str:
    return random.choice(VD_COOLDOWN_PHRASES).replace(
        "{remaining_time}", format_remaining_time(remaining))


def get_download_cooldown():
    """Follow-up R10.15-9: текущий общий download-кулдаун для tool-сета.

    Ленивая ссылка (провайдер): `setup_video_download` пересоздаёт трекер в
    on_startup уже ПОСЛЕ сборки `ToolDeps`, поэтому провайдер читает
    актуальный модульный глобал в момент tool-вызова."""
    return _cooldown


def download_available() -> bool:
    """R10.15-4: поднят ли download-воркер (DI-сервис внедрён).

    S10.16-3: в текущем прод-DI `bot.py` ВСЕГДА вызывает
    `setup_video_download(...)` (роутер 4e регистрируется безусловно, гейт —
    горячий флаг в хендлере), поэтому здесь всегда `True`. Оставляем как
    осознанную защиту на случай будущего УСЛОВНОГО DI (напр. downloader не
    сконфигурирован) и потому что она покрыта тестами
    `test_smoke_round1016_fixes.TestDownloadAlwaysRegistered`; иначе `yield`
    direct_chat при отсутствующем сервисе потерял бы сообщение без ответа."""
    return _downloader is not None


def _extract_urls(message: types.Message) -> list[str]:
    """http(s)-ссылки из text/caption сообщения и реплая (дедуп, порядок)."""
    texts: list[str] = []
    for raw in (message.text, message.caption):
        if isinstance(raw, str):
            texts.append(raw)
    replied = getattr(message, "reply_to_message", None)
    if replied is not None:
        for attr in ("text", "caption"):
            value = getattr(replied, attr, None)
            if isinstance(value, str):
                texts.append(value)
    urls: list[str] = []
    for text in texts:
        for url in _URL_RE.findall(text):
            if url not in urls:
                urls.append(url)
    return urls


# Bugfix 04.09.2026 (Часть 1b, FR-12): квалификация медиа реплая — та же,
# что в handlers/youtube.py 3.1.1 (видео-документ: mime video/*; без mime —
# по расширению file_name; voice/video_note/audio НЕ подходят).
_VIDEO_DOC_EXTENSIONS = ("mp4", "webm", "mov", "mkv", "avi")


def _document_is_video(doc) -> bool:
    """Document → видео: mime video/*; mime пуст/None → расширение file_name;
    mime задан и не video/* → НЕ видео (mime авторитетнее имени)."""
    mime = str(getattr(doc, "mime_type", "") or "").strip().lower()
    if mime:
        return mime.startswith("video/")
    name = str(getattr(doc, "file_name", "") or "").lower()
    return any(name.endswith("." + ext) for ext in _VIDEO_DOC_EXTENSIONS)


def _reply_video_media(message: types.Message):
    """Видео-медиа из reply_target (video | документ video/* по mime/имени)
    → объект медиа для пересылки; None — не видео/нет реплая."""
    reply_target = getattr(message, "reply_to_message", None)
    if reply_target is None:
        return None
    video = getattr(reply_target, "video", None)
    if video is not None and isinstance(getattr(video, "file_id", None), str):
        return video
    document = getattr(reply_target, "document", None)
    if document is not None and _document_is_video(document):
        return document
    return None


def _get_pending(chat_id: int, user_id: int) -> dict | None:
    """Ленивая чистка протухших ключей (Section 70.5 п.4) + выдача слота."""
    now = time.monotonic()
    for key in [k for k, v in _PENDING.items() if v["expires"] <= now]:
        _PENDING.pop(key, None)
    entry = _PENDING.get((chat_id, user_id))
    if entry is None or entry["expires"] <= now:
        _PENDING.pop((chat_id, user_id), None)
        return None
    return entry


async def _send_quality_menu(bot: Bot, chat_id: int, trigger_message_id: int,
                             title: str | None,
                             qualities: tuple[str, ...]) -> None:
    """Инлайн-меню качества Fast-Track `vd:<height>` — общий хелпер (T-1679).

    Клавиатура/заголовок строятся в `services.media_send.send_quality_menu` —
    единый источник с tool-путём (`tdq:`), без дублирования меню."""
    await send_quality_menu(
        bot, chat_id, reply_to=trigger_message_id, title=title,
        qualities=qualities, callback_prefix=_FASTTRACK_QUALITY_PREFIX)


async def _delete_keyboard(bot: Bot, chat_id: int, trigger_message_id: int,
                           kb_message) -> bool:
    """СТРОГОЕ удаление сообщения с клавиатурой. TelegramBadRequest (нет прав /
    уже удалено) → RIGHTS_ERROR реплаем на триггер, но НЕ отменяет скачивание."""
    try:
        await kb_message.delete()
        return True
    except TelegramBadRequest as exc:
        logger.warning("[videodl] keyboard delete failed | chat=%s | error=%s",
                       chat_id, exc)
        try:
            await bot.send_message(
                chat_id, random.choice(VD_RIGHTS_ERROR_PHRASES),
                reply_to_message_id=trigger_message_id)
        except TelegramBadRequest:
            pass
        return False


@video_download_router.message()
async def video_download_handler(message: types.Message, bot: Bot = None):
    if _downloader is None or bot is None:
        return UNHANDLED
    # R10.15-4: горячий гейт master-флага. Роутер зарегистрирован всегда
    # (позиция 4e не меняется), поэтому выключенный модуль «спит» — сообщение
    # уходит дальше по штатной пропагации, а не теряется без ответа.
    if not hot.get("flags.download_enabled",
                   getattr(settings, "DOWNLOAD_ENABLED", False)):
        return UNHANDLED
    text = message.text or message.caption or ""
    if not isinstance(text, str):
        return UNHANDLED
    body = _command_body(message)
    if body is None or not _TRIGGER_RE.match(body):
        return UNHANDLED                        # не триггер → пропагация живёт
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info("[videodl] triggered | chat=%s user=%s", chat_id, user_id)

    urls = _extract_urls(message)
    if not urls:
        # Замечание чекапа: нативное TG-видео («скачай <видео-сообщение>»)
        video = getattr(message, "video", None) or getattr(
            message, "document", None)
        if video is not None and isinstance(getattr(video, "file_id", None),
                                            str):
            await _handle_native_media(bot, message, video)
        else:
            # Bugfix 04.09.2026 (Часть 1b, FR-12): реплай «скачай» на чужое
            # видео-сообщение/документ (в т.ч. репосты — те же поля, mime
            # video/* либо имя-расширение) без ссылок → нативная пересылка;
            # voice/video_note/audio НЕ квалифицируются (как в youtube 3.1.1).
            reply_media = _reply_video_media(message)
            if reply_media is not None:
                await _handle_native_media(bot, message, reply_media)
            else:
                await message.reply(random.choice(VD_NO_LINK_PHRASES))  # consume
        return None

    # Замечание чекапа: прямые медиа-ссылки — сразу скачиваем без quality-меню
    if len(urls) == 1 and is_direct_media_url(urls[0]):
        cooldown_refresh(_cooldown, hot.get("limits.download_cooldown",
                                            settings.DOWNLOAD_COOLDOWN))
        remaining = await cooldown_remaining(_cooldown, chat_id, user_id)
        if remaining > 0:
            await message.reply(_cooldown_phrase(remaining))
            return None
        trigger_message_id = message.message_id
        # 84.23 (D303): прогресс-бар и для direct-стрима (синтетический
        # прогресс из download_direct: bytes/percent по Content-Length).
        reporter = ProgressReporter(bot, chat_id,
                                    trigger_message_id=trigger_message_id)
        register(chat_id, reporter)
        path = None
        try:
            await reporter.start("⏳ Скачивание…")
            # Bugfix 04.09.2026 (Часть 1b, FR-13/D279): успешный старт
            # скачивания жжёт кулдаун; провал ДО старта (except-ветки ниже)
            # touch НЕ вызывает (fail не жжёт кулдаун).
            await cooldown_touch(_cooldown, chat_id, user_id)
            path = await _downloader.download(urls[0], None,
                                              progress_cb=reporter.on_progress)
            await reporter.finish("✅ Файл готов, отправляю…")
            await _send_file(bot, chat_id, path, trigger_message_id,
                             title=None)
            await reporter.close()
        except DownloadTooBigError as exc:
            log_download_env_once()
            logger.warning("[videodl] too big | chat=%s | error=%s reason=%s",
                           chat_id, type(exc).__name__, exc.reason)
            if not await reporter.fail(random.choice(VD_TOO_BIG_PHRASES)):
                await _safe_error_reply(bot, chat_id, trigger_message_id,
                                        VD_TOO_BIG_PHRASES)
        except DownloadUnavailableError as exc:
            log_download_env_once()
            logger.warning(
                "[videodl] unavailable | chat=%s | error=%s reason=%s",
                chat_id, type(exc).__name__, exc.reason)
            if not await reporter.fail(random.choice(VD_UNAVAILABLE_PHRASES)):
                await _safe_error_reply(bot, chat_id, trigger_message_id,
                                        VD_UNAVAILABLE_PHRASES)
        except Exception as exc:
            log_download_env_once()
            # R17: без URL / str(exc).
            logger.warning(
                "[videodl] download failed | chat=%s | error=%s",
                chat_id, type(exc).__name__)
            if not await reporter.fail(random.choice(VD_ERROR_PHRASES)):
                await _safe_error_reply(bot, chat_id, trigger_message_id,
                                        VD_ERROR_PHRASES)
        finally:
            # B1: файл не копим при ЛЮБОМ исходе (прецедент cb_pick_quality)
            if path is not None and path.exists():
                path.unlink(missing_ok=True)
            unregister(chat_id)
        return None

    # T-619: кулдаун — горячая точка (ConfigCache → settings-фолбек)
    cooldown_refresh(_cooldown, hot.get("limits.download_cooldown",
                                        settings.DOWNLOAD_COOLDOWN))
    remaining = await cooldown_remaining(_cooldown, chat_id, user_id)
    if remaining > 0:
        await message.reply(_cooldown_phrase(remaining))           # consume
        return None

    trigger_message_id = message.message_id
    if len(urls) == 1:
        try:
            probe = await _downloader.probe(urls[0])
        except DownloadError as exc:
            # R17: только класс + safe-reason (без URL/str(exc)).
            logger.warning("[videodl] probe failed | chat=%s | error=%s "
                           "reason=%s", chat_id, type(exc).__name__,
                           exc.reason)
            log_download_env_once()
            # T-1628: probe (yt-dlp) гейтит и cobalt-платформы — при провале
            # для не-direct ссылки одна ограниченная попытка без меню
            # качества (probe-fail кулдаун НЕ жжёт — см. _download_without_menu).
            # Ревью-итер.1 (Medium): ветка is_direct_media_url(urls[0]) здесь
            # недостижима — одиночный direct-URL перехвачен выше (:280), так
            # как direct обрабатывается до probe. Ветка удалена.
            return await _download_without_menu(
                bot, message, urls[0], chat_id, user_id)
        # D279: touch только после успешного probe — fail не жжёт кулдаун.
        await cooldown_touch(_cooldown, chat_id, user_id)
        _PENDING[(chat_id, user_id)] = {
            "urls": urls,
            "probes": [probe],
            "selected": 0,
            "trigger_message_id": trigger_message_id,
            "expires": time.monotonic() + _PENDING_TTL_SECONDS,
        }
        await _send_quality_menu(bot, chat_id, trigger_message_id,
                                 probe.title, probe.qualities)
        return None

    # Несколько ссылок → «читаю ссылки…» → titles → выбор видео.
    status = await message.reply("читаю ссылки...")
    probes = await asyncio.gather(*[_safe_probe(url) for url in urls])
    # D279: частично битые ссылки — штатный UX (probe-фаза успешна, если
    # есть хоть один непровалившийся результат); все битые → БЕЗ touch.
    if any(p is not None for p in probes):
        await cooldown_touch(_cooldown, chat_id, user_id)
    _PENDING[(chat_id, user_id)] = {
        "urls": urls,
        "probes": probes,
        "selected": None,
        "trigger_message_id": trigger_message_id,
        "expires": time.monotonic() + _PENDING_TTL_SECONDS,
    }
    builder = InlineKeyboardBuilder()
    for idx, probe in enumerate(probes):
        label = probe.title[:40] if probe else f"ссылка {idx + 1}"
        builder.button(text=label or f"ссылка {idx + 1}",
                       callback_data=f"vdv:{idx}")
    builder.adjust(1)
    try:
        await bot.edit_message_text(
            random.choice(VD_MULTI_LINK_PHRASES),
            chat_id=chat_id,
            message_id=status.message_id,
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        await bot.send_message(chat_id, random.choice(VD_MULTI_LINK_PHRASES),
                               reply_markup=builder.as_markup(),
                               reply_to_message_id=trigger_message_id)
    return None


def _probe_error_phrase(reason: str) -> tuple[str, ...]:
    """T-1628: safe-код причины → СУЩЕСТВУЮЩИЙ пул фраз (spec §4.4). Новых
    пулов не вводим; неизвестная причина → общий VD_ERROR_PHRASES.
    S10.16-5: probe эмитит только probe_timeout/probe_bot_check/probe_failed
    (probe-raise в tools/video_downloader.py) — мёртвый probe_unavailable убран."""
    if reason == "probe_bot_check":
        return VD_UNAVAILABLE_PHRASES
    if reason == "cobalt_down":
        return VD_SERVICE_DOWN_PHRASES
    if reason in ("direct_too_big", "ytdlp_too_big", "stream_too_big"):
        return VD_TOO_BIG_PHRASES
    return VD_ERROR_PHRASES


def _fallback_phrases(exc: Exception) -> tuple[str, ...]:
    """Пул фраз для сбоя bounded fallback (по классу, затем по reason)."""
    if isinstance(exc, DownloadTooBigError):
        return VD_TOO_BIG_PHRASES
    if isinstance(exc, CobaltServiceDownError):
        return VD_SERVICE_DOWN_PHRASES
    if isinstance(exc, DownloadUnavailableError):
        return VD_UNAVAILABLE_PHRASES
    if isinstance(exc, DownloadBusyError):
        return VD_BUSY_PHRASES
    if isinstance(exc, DownloadError):
        return _probe_error_phrase(exc.reason)
    return VD_ERROR_PHRASES


async def _download_without_menu(bot: Bot, message: types.Message, url: str,
                                 chat_id: int, user_id: int):
    """T-1628 (ADR-1016-1 §2.5): bounded probe-fallback Fast-Track — probe
    (yt-dlp) провалился, но ссылка НЕ direct (cobalt-eligible) → одна попытка
    `download(url, None)` без quality-меню. Кулдаун жжётся только после
    успешного старта (probe-fail его не жжёт); провал → классифицированная
    фраза (bot_check/unavailable ≠ «битая ссылка»)."""
    remaining = await cooldown_remaining(_cooldown, chat_id, user_id)
    if remaining > 0:
        await message.reply(_cooldown_phrase(remaining))
        return None
    trigger_message_id = message.message_id
    reporter = ProgressReporter(bot, chat_id,
                                trigger_message_id=trigger_message_id)
    register(chat_id, reporter)
    path = None
    try:
        await reporter.start("⏳ Скачивание без выбора качества…")
        path = await _downloader.download(url, None,
                                          progress_cb=reporter.on_progress)
        # S10.16-4: touch — после УСПЕШНОГО старта скачивания, но ДО
        # `_send_file`: падение Telegram-отправки не должно позволять
        # немедленно повторить тяжёлое скачивание. Провал самого download
        # (probe-fail → fallback-fail, spec §4.4) кулдаун НЕ жжёт.
        await cooldown_touch(_cooldown, chat_id, user_id)
        await reporter.finish("✅ Файл готов, отправляю…")
        await _send_file(bot, chat_id, path, trigger_message_id, title=None)
        await reporter.close()
    except Exception as exc:
        log_download_env_once()
        if isinstance(exc, DownloadError):
            logger.warning("[videodl] fallback failed | chat=%s | error=%s "
                           "reason=%s", chat_id, type(exc).__name__,
                           exc.reason)
        else:
            logger.warning("[videodl] fallback failed | chat=%s | error=%s",
                           chat_id, type(exc).__name__)
        phrases = _fallback_phrases(exc)
        if not await reporter.fail(random.choice(phrases)):
            await _safe_error_reply(bot, chat_id, trigger_message_id, phrases)
    finally:
        if path is not None and path.exists():
            path.unlink(missing_ok=True)
        unregister(chat_id)
    return None


async def _safe_probe(url: str) -> ProbeResult | None:
    try:
        return await _downloader.probe(url)
    except DownloadError as exc:
        logger.warning("[videodl] multi probe failed | error=%s reason=%s",
                       type(exc).__name__, exc.reason)
        return None


@video_download_router.callback_query(F.data.startswith("vdv:"))
async def cb_pick_video(callback: types.CallbackQuery, bot: Bot = None):
    """Выбор видео из нескольких ссылок → показ выбора качества."""
    if _downloader is None or bot is None:
        return
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id if callback.from_user else 0
    pending = _get_pending(chat_id, user_id)
    idx = _parse_int_suffix(callback.data, "vdv:")
    if pending is None or idx is None or not (0 <= idx < len(pending["urls"])):
        await callback.answer("эта менюха протухла")
        return
    pending["selected"] = idx
    trigger_message_id = pending["trigger_message_id"]
    await callback.answer()                     # ack ДО удаления клавиатуры
    await _delete_keyboard(bot, chat_id, trigger_message_id, callback.message)
    probe = pending["probes"][idx]
    title = probe.title if probe else pending["urls"][idx]
    qualities = probe.qualities if probe else ("1080p", "720p", "360p")
    await _send_quality_menu(bot, chat_id, trigger_message_id, title, qualities)


@video_download_router.callback_query(F.data.startswith("vd:"))
async def cb_pick_quality(callback: types.CallbackQuery, bot: Bot = None):
    """Выбор качества → удалить клавиатуру → скачать → reply-video → cleanup."""
    if _downloader is None or bot is None:
        return
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id if callback.from_user else 0
    pending = _get_pending(chat_id, user_id)
    quality = _parse_int_suffix(callback.data, "vd:")
    if pending is None or quality is None or pending["selected"] is None:
        await callback.answer("эта менюха протухла")
        return
    # Лок занят → BUSY без ожидания (answer, не спамим чат — Section 70.8 #3).
    # 84.23: chat уже с активным прогресс-баром — тоже BUSY (реестр).
    if _downloader.busy or get_active(chat_id) is not None:
        await callback.answer(random.choice(VD_BUSY_PHRASES), show_alert=True)
        return
    await callback.answer()                     # ack
    trigger_message_id = pending["trigger_message_id"]
    idx = pending["selected"]
    url = pending["urls"][idx]
    probe = pending["probes"][idx]
    title = probe.title if probe else url

    await _delete_keyboard(bot, chat_id, trigger_message_id, callback.message)
    _PENDING.pop((chat_id, user_id), None)

    # 84.23 (D303): прогресс-бар — одно сообщение, троттлинг 2с.
    reporter = ProgressReporter(bot, chat_id,
                                trigger_message_id=trigger_message_id)
    register(chat_id, reporter)

    try:
        await bot.send_chat_action(chat_id, "upload_video")
    except TelegramBadRequest:
        pass

    path = None
    try:
        await reporter.start("⏳ Скачивание…")
        path = await _downloader.download(url, f"{quality}p",
                                          progress_cb=reporter.on_progress)
        await reporter.finish("✅ Файл готов, отправляю…")
        file = FSInputFile(str(path.absolute()))
        try:
            await bot.send_video(
                chat_id, file,
                supports_streaming=True,
                caption=(title or "")[:1024],
                reply_to_message_id=trigger_message_id,
            )
        except TelegramBadRequest:
            # таргет реплая исчез — отправляем БЕЗ reply, файл не пропадает
            await bot.send_video(
                chat_id, FSInputFile(str(path.absolute())),
                supports_streaming=True, caption=(title or "")[:1024])
        logger.info("[videodl] sent | chat=%s user=%s quality=%sp",
                    chat_id, user_id, quality)
        # 84.23.4: статус-сообщение исчезает, остаётся только медиа
        await reporter.close()
    except DownloadTooBigError as exc:
        log_download_env_once()
        logger.warning("[videodl] too big | chat=%s | error=%s reason=%s",
                       chat_id, type(exc).__name__, exc.reason)
        if not await reporter.fail(random.choice(VD_TOO_BIG_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_TOO_BIG_PHRASES)
    except CobaltServiceDownError as exc:
        log_download_env_once()
        logger.warning("[videodl] service down | chat=%s | error=%s "
                       "reason=%s", chat_id, type(exc).__name__, exc.reason)
        if not await reporter.fail(random.choice(VD_SERVICE_DOWN_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_SERVICE_DOWN_PHRASES)
    except DownloadBusyError as exc:            # гонка между busy-проверкой и локом
        logger.warning("[videodl] busy race | chat=%s | reason=%s",
                       chat_id, exc.reason)
        if not await reporter.fail(random.choice(VD_BUSY_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_BUSY_PHRASES)
    except DownloadUnavailableError as exc:
        # Прод-хотфикс: понятная причина (возраст/вход/DRM/live). R17: без URL.
        log_download_env_once()
        logger.warning("[videodl] unavailable | chat=%s | error=%s reason=%s",
                       chat_id, type(exc).__name__, exc.reason)
        if not await reporter.fail(random.choice(VD_UNAVAILABLE_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_UNAVAILABLE_PHRASES)
    except Exception as exc:
        log_download_env_once()
        logger.warning("[videodl] download failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        if not await reporter.fail(random.choice(VD_ERROR_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_ERROR_PHRASES)
    finally:
        # Cleanup ЛЮБОГО исхода (Section 70.4 п.4): файл не копится.
        if path is not None and path.exists():
            path.unlink(missing_ok=True)
        unregister(chat_id)


@video_download_router.callback_query(F.data.startswith("tdq:"))
async def cb_tool_quality(callback: types.CallbackQuery, bot: Bot = None):
    """Раунд 10.17 (F2, ADR-1017-2 §3.3): выбор качества для tool-скачивания.

    Инициатор меню — tool `download_media` (probe→инлайн-клавиатура `tdq:`);
    здесь доводим скачивание (download+send) как `cb_pick_quality`. Кулдаун
    НЕ проверяется и НЕ жжётся — producer уже сделал это после probe.
    R17: в логи — только chat_id/user/quality, без URL/title."""
    if _downloader is None or bot is None:
        return
    chat_id = callback.message.chat.id
    user_id = callback.from_user.id if callback.from_user else 0
    quality = _parse_int_suffix(callback.data, "tdq:")
    # L1 (ревью-итер.1): высота обязана быть среди предложенных probe. Мусор /
    # подделанный callback отвергаем ДО consume — pending и меню сохраняются.
    pending = peek_tool_download_pending(chat_id, user_id)
    if (quality is None or pending is None
            or f"{quality}p" not in (pending.get("qualities") or ())):
        await callback.answer("эта менюха протухла")
        return
    # Лок занят → BUSY без ожидания (как cb_pick_quality). Pending НЕ забираем:
    # после BUSY кнопка остаётся рабочей в пределах TTL.
    if _downloader.busy or get_active(chat_id) is not None:
        await callback.answer(random.choice(VD_BUSY_PHRASES), show_alert=True)
        return
    pending = pop_tool_download_pending(chat_id, user_id)
    if pending is None:
        await callback.answer("эта менюха протухла")
        return
    await callback.answer()                     # ack ДО удаления клавиатуры
    logger.info("[videodl] tool quality resolved | chat=%s user=%s quality=%sp",
                chat_id, user_id, quality)
    trigger_message_id = pending.get("trigger_message_id")
    await _delete_keyboard(bot, chat_id, trigger_message_id, callback.message)
    reporter = ProgressReporter(bot, chat_id,
                                trigger_message_id=trigger_message_id)
    register(chat_id, reporter)
    path = None
    try:
        # L6 (ревью-итер.1): паритет UX с Fast-Track `cb_pick_quality`.
        try:
            await bot.send_chat_action(chat_id, "upload_video")
        except TelegramBadRequest:
            pass
        await reporter.start("⏳ Скачивание…")
        path = await _downloader.download(pending["url"], f"{quality}p",
                                          progress_cb=reporter.on_progress)
        await reporter.finish("✅ Файл готов, отправляю…")
        await _send_file(bot, chat_id, path, trigger_message_id,
                         pending.get("title"))
        await reporter.close()
    except Exception as exc:                    # R17: класс/reason, без URL
        log_download_env_once()
        if isinstance(exc, DownloadError):
            logger.warning("[videodl] tool download failed | chat=%s | "
                           "error=%s reason=%s", chat_id,
                           type(exc).__name__, exc.reason)
        else:
            logger.warning("[videodl] tool download failed | chat=%s | "
                           "error=%s", chat_id, type(exc).__name__)
        phrases = _fallback_phrases(exc)
        if not await reporter.fail(random.choice(phrases)):
            await _safe_error_reply(bot, chat_id, trigger_message_id, phrases)
    finally:
        if path is not None and path.exists():
            path.unlink(missing_ok=True)
        unregister(chat_id)


def _parse_int_suffix(data: str | None, prefix: str) -> int | None:
    if not data or not data.startswith(prefix):
        return None
    tail = data[len(prefix):]
    return int(tail) if tail.isdigit() else None


async def _safe_error_reply(bot: Bot, chat_id: int, trigger_message_id: int,
                            phrases: tuple[str, ...]) -> None:
    try:
        await bot.send_message(chat_id, random.choice(phrases),
                               reply_to_message_id=trigger_message_id)
    except TelegramBadRequest:
        try:
            await bot.send_message(chat_id, random.choice(phrases))
        except TelegramBadRequest:
            pass


async def _send_file(bot: Bot, chat_id: int, path: Path,
                     trigger_message_id: int | None,
                     title: str | None) -> None:
    """Отправка скачанного файла (видео/документ) с реплаем на триггер.
    Файл НЕ удаляется здесь — очистка в finally у вызывающего."""
    from aiogram.types import FSInputFile
    file = FSInputFile(str(path.absolute()))
    caption = (title or "")[:1024] if title else None
    try:
        if trigger_message_id:
            await bot.send_video(
                chat_id, file, supports_streaming=True, caption=caption,
                reply_to_message_id=trigger_message_id)
        else:
            await bot.send_video(chat_id, file, supports_streaming=True,
                                 caption=caption)
    except TelegramBadRequest:
        # таргет реплая исчез / тип не видео — шлём документом
        try:
            await bot.send_document(
                chat_id, FSInputFile(str(path.absolute())),
                reply_to_message_id=trigger_message_id,
                caption=caption)
        except TelegramBadRequest:
            await bot.send_document(chat_id,
                                    FSInputFile(str(path.absolute())))
    logger.info("[videodl] sent | chat=%s | file=%s", chat_id, path.name)


async def _handle_native_media(bot: Bot, message: types.Message,
                               media) -> None:
    """Замечание чекапа: «скачай <видео/документ-сообщение>» — без ссылок.
    Bugfix 04.09.2026 (Часть 1b, FR-12): скачивание через общий
    services.media_download.fetch_media_to_tmp (локальный Bot API — копия
    с диска; облако — bot.download), tmp-уборка в finally. Ошибки — понятные."""
    from services.media_download import fetch_media_to_tmp
    chat_id = message.chat.id
    tmp_path = None
    try:
        ext = _native_media_ext(media)
        fd, tmp_path = tempfile.mkstemp(prefix=f"vd_native_{int(time.time())}_",
                                        suffix=f".{ext}")
        os.close(fd)
        await fetch_media_to_tmp(bot, media, tmp_path)
        size = os.path.getsize(tmp_path)
        if size > 2_000_000_000:
            os.unlink(tmp_path)
            await message.reply(random.choice(VD_TOO_BIG_PHRASES))
            return
        await message.reply(
            f"нативное видео: {size // (1024 * 1024)} МБ, пересылаю...")
        await bot.send_video(chat_id, FSInputFile(str(tmp_path)),
                             supports_streaming=True)
        logger.info("[videodl] native media re-sent | chat=%s | bytes=%d",
                    chat_id, size)
    except Exception as exc:
        # R17: только класс (локальные temp-пути/file_id из str(exc) не логируем).
        logger.warning("[videodl] native media failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        await _safe_error_reply(bot, chat_id, message.message_id,
                                VD_ERROR_PHRASES)
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _native_media_ext(media) -> str:
    """Расширение tmp-файла нативного медиа: document — по file_name,
    иначе по mime_type; дефолт mp4 (контейнер TG-видео); неизвестно → bin."""
    name = str(getattr(media, "file_name", "") or "").lower()
    suffix = Path(name).suffix.lstrip(".").lower()
    if suffix:
        return suffix if suffix != "jpeg" else "jpg"
    mime = str(getattr(media, "mime_type", "") or "").lower()
    mapping = {"video/mp4": "mp4", "video/webm": "webm",
               "video/x-matroska": "mkv", "video/quicktime": "mov",
               "video/avi": "avi", "video/x-msvideo": "avi"}
    if mime in mapping:
        return mapping[mime]
    return "bin"
