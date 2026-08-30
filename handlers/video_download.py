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
import random
import re
import time
from pathlib import Path

from aiogram import Bot, F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from services import hot_config as hot
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
)

logger = logging.getLogger(__name__)

video_download_router = Router(name="video_download")

_downloader = None                                  # VideoDownloader (DI)
_cooldown = CooldownTracker(settings.DOWNLOAD_COOLDOWN)

# Section 70.5: триггер ТОЛЬКО в начале строки.
_TRIGGER_RE = re.compile(
    r"^\s*(скачай|загрузи|стяни|спизди|скачать)\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")

_PENDING_TTL_SECONDS = 600                          # Section 70.5 п.4
_PENDING: dict[tuple[int, int], dict] = {}
_QUALITY_ROW_SIZE = 3


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


def _quality_keyboard(qualities: tuple[str, ...]) -> InlineKeyboardMarkup:
    """Кнопки «{h}p» рядами по 3, callback_data=vd:<quality> (ТЗ)."""
    builder = InlineKeyboardBuilder()
    for quality in qualities:
        builder.button(text=quality, callback_data=f"vd:{quality[:-1]}")
    builder.adjust(_QUALITY_ROW_SIZE)
    return builder.as_markup()


async def _send_quality_menu(bot: Bot, chat_id: int, trigger_message_id: int,
                             title: str | None,
                             qualities: tuple[str, ...]) -> None:
    header = f"{title[:200]}\n\n" if title else ""
    await bot.send_message(
        chat_id,
        f"{header}выбери качество:",
        reply_markup=_quality_keyboard(qualities),
        reply_to_message_id=trigger_message_id,
        disable_web_page_preview=True,
    )


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
    text = message.text or message.caption or ""
    if not isinstance(text, str) or not _TRIGGER_RE.match(text):
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
            path = await _downloader.download(urls[0], "direct",
                                              progress_cb=reporter.on_progress)
            await reporter.finish("✅ Файл готов, отправляю…")
            await _send_file(bot, chat_id, path, trigger_message_id,
                             title=None)
            await reporter.close()
        except DownloadTooBigError as exc:
            logger.warning("[videodl] too big | chat=%s | url=%s | %s",
                           chat_id, urls[0], exc)
            if not await reporter.fail(random.choice(VD_TOO_BIG_PHRASES)):
                await _safe_error_reply(bot, chat_id, trigger_message_id,
                                        VD_TOO_BIG_PHRASES)
        except DownloadUnavailableError as exc:
            logger.warning("[videodl] unavailable | chat=%s | url=%s | %s",
                           chat_id, urls[0], exc)
            if not await reporter.fail(random.choice(VD_UNAVAILABLE_PHRASES)):
                await _safe_error_reply(bot, chat_id, trigger_message_id,
                                        VD_UNAVAILABLE_PHRASES)
        except Exception as exc:
            logger.warning("[videodl] download failed | chat=%s | url=%s | "
                           "quality=direct | error=%s", chat_id, urls[0], exc)
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
            logger.warning("[videodl] probe failed | chat=%s | error=%s",
                           chat_id, exc)
            await message.reply(random.choice(VD_ERROR_PHRASES))
            return None
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


async def _safe_probe(url: str) -> ProbeResult | None:
    try:
        return await _downloader.probe(url)
    except DownloadError as exc:
        logger.warning("[videodl] multi probe failed | error=%s", exc)
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
        logger.warning("[videodl] too big | chat=%s | error=%s", chat_id, exc)
        if not await reporter.fail(random.choice(VD_TOO_BIG_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_TOO_BIG_PHRASES)
    except CobaltServiceDownError as exc:
        logger.warning("[videodl] service down | chat=%s | error=%s",
                       chat_id, exc)
        if not await reporter.fail(random.choice(VD_SERVICE_DOWN_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_SERVICE_DOWN_PHRASES)
    except DownloadBusyError as exc:            # гонка между busy-проверкой и локом
        logger.warning("[videodl] busy race | chat=%s", chat_id)
        if not await reporter.fail(random.choice(VD_BUSY_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_BUSY_PHRASES)
    except DownloadUnavailableError as exc:
        # Прод-хотфикс: понятная причина (возраст/вход/DRM/live).
        logger.warning("[videodl] unavailable | chat=%s | url=%s | %s",
                       chat_id, url, exc)
        if not await reporter.fail(random.choice(VD_UNAVAILABLE_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_UNAVAILABLE_PHRASES)
    except Exception as exc:
        logger.warning("[videodl] download failed | chat=%s | url=%s | "
                       "quality=%s | error=%s", chat_id, url, f"{quality}p",
                       exc)
        if not await reporter.fail(random.choice(VD_ERROR_PHRASES)):
            await _safe_error_reply(bot, chat_id, trigger_message_id,
                                    VD_ERROR_PHRASES)
    finally:
        # Cleanup ЛЮБОГО исхода (Section 70.4 п.4): файл не копится.
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
    bot.get_file → temp → отправить как видео/документ. Ошибки — понятные."""
    from pathlib import Path
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    tmp_path = None
    try:
        f = await bot.get_file(media.file_id)
        ext = Path(f.file_path or "").suffix.lstrip(".").lower() or "bin"
        tmp_path = Path(f"/tmp/vd_native_{time.time()}_{user_id}.{ext}")
        data = await bot.download_file(f.file_path)
        tmp_path.write_bytes(data.read())
        size = tmp_path.stat().st_size
        if size > 2_000_000_000:
            tmp_path.unlink(missing_ok=True)
            await message.reply(random.choice(VD_TOO_BIG_PHRASES))
            return
        await message.reply(
            f"нативное видео: {size // (1024 * 1024)} МБ, пересылаю...")
        await bot.send_video(chat_id, FSInputFile(str(tmp_path.absolute())),
                             supports_streaming=True)
        logger.info("[videodl] native media re-sent | chat=%s | bytes=%d",
                    chat_id, size)
    except Exception as exc:
        logger.warning("[videodl] native media failed | chat=%s | error=%s",
                       chat_id, exc)
        await _safe_error_reply(bot, chat_id, message.message_id,
                                VD_ERROR_PHRASES)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
