import logging
import random
import time
from pathlib import Path
from aiogram import Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import FSInputFile, MessageOriginChannel
from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from config.settings import settings
from services import hot_config as hot
from services.mimic_transform import mimic_transform, count_words

logger = logging.getLogger(__name__)

slavik_router = Router()

# DB reference injected via setup_slavik()
_db = None

# ── Slavik Mimic cooldown (F11) — per-chat, independent from common service ──
_slavik_mimic_last_sent: dict[int, float] = {}

# ── Media type detection — same logic as CommonRelay._detect_media_type ──
_IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXTENSIONS: set[str] = {".mp4", ".mov", ".webm"}
_AUDIO_EXTENSIONS: set[str] = {".mp3"}
_VOICE_EXTENSIONS: set[str] = {".ogg"}


def _detect_slavik_media_type(filepath: Path) -> str:
    """Determine media type from file extension and filename.

    Returns 'photo', 'video', 'animation', 'audio', 'voice', or 'document' (fallback).
    """
    ext = filepath.suffix.lower()
    name_lower = filepath.name.lower()

    if ext in _IMAGE_EXTENSIONS:
        return "photo"
    if ext in _VIDEO_EXTENSIONS:
        # GIF detection: check full filename (not just stem) for "gif" with word boundaries
        if (
            "_gif" in name_lower
            or name_lower.startswith("gif")
            or ".gif." in name_lower
        ):
            return "animation"
        return "video"
    if ext in _AUDIO_EXTENSIONS:
        return "audio"
    if ext in _VOICE_EXTENSIONS:
        return "voice"
    # Fallback: any other file → document
    return "document"


def _pick_random_slavik_media() -> tuple[Path, str] | None:
    """Pick a random media file from SLAVIC_RANDOM_DIR.

    Returns (filepath, media_type) or None if directory is empty/missing.
    """
    media_dir = Path(settings.SLAVIC_RANDOM_DIR)
    if not media_dir.exists():
        logger.warning("Slavic Photo: directory not found: %s", media_dir)
        return None

    files: list[tuple[Path, str]] = []
    for entry in media_dir.iterdir():
        try:
            if not entry.is_file():
                continue
            media_type = _detect_slavik_media_type(entry)
            files.append((entry, media_type))
        except OSError:
            logger.warning(
                "Slavic Photo: cannot access entry %s — skipping", entry
            )
            continue

    if not files:
        logger.warning("Slavic Photo: no supported media files in %s", media_dir)
        return None

    picked = random.choice(files)
    logger.info(
        "Slavic Photo: picked %s (%s) from %d files in %s",
        picked[0].name, picked[1], len(files), media_dir,
    )
    return picked


async def _send_slavik_media(
    message: types.Message,
    filepath: Path,
    media_type: str,
) -> None:
    """Send media file as reply using the appropriate bot method."""
    input_file = FSInputFile(str(filepath))
    if media_type == "photo":
        await message.answer_photo(photo=input_file)
    elif media_type == "video":
        await message.answer_video(video=input_file)
    elif media_type == "animation":
        await message.answer_animation(animation=input_file)
    elif media_type == "audio":
        await message.answer_audio(audio=input_file)
    elif media_type == "voice":
        await message.answer_voice(voice=input_file)
    elif media_type == "document":
        await message.answer_document(document=input_file)
    else:
        logger.warning("Slavik: unknown media type %s for %s, falling back to document", media_type, filepath.name)
        await message.answer_document(document=input_file)


def setup_slavik(db):
    """Inject DatabaseService dependency for slavik handlers."""
    global _db
    _db = db


def _slavik_mimic_should_trigger(
    chat_id: int, text: str, is_forwarded: bool = False
) -> bool:
    """Check mimic conditions for Slavik: word count, cooldown, forward gate (D52).

    Returns True if mimic should fire instead of the default reply.
    T-619: параметры мимикрии — горячие точки (фолбек settings).
    """
    if is_forwarded and not hot.get("flags.mimic_forwards_enabled",
                                    settings.MIMIC_FORWARDS_ENABLED):
        return False  # D52: mimic пропускается → дальше Branch 3 «пошёл нахуй»
    min_words = hot.get("limits.slavik_mimic_min_words",
                        settings.SLAVIK_MIMIC_MIN_WORDS)
    if min_words < 0:
        return False
    if count_words(text) <= min_words:
        return False
    cooldown = hot.get("limits.slavik_mimic_cooldown",
                       settings.SLAVIK_MIMIC_COOLDOWN)
    if cooldown > 0:
        last = _slavik_mimic_last_sent.get(chat_id)
        if last is not None and (time.monotonic() - last) < cooldown:
            return False
    return True


# Handler 1: F4 — KUCHA words → "ДАЛБАЕБ"
@slavik_router.message(KuchaWordFilter())
async def kucha_handler(message: types.Message, data: dict | None = None):
    # T-410 (Section 61.4.1): строгая семантика «одно действие» — если гифка
    # уже ушла (data-флаг от миддлвари), ДАЛБАЕБ не шлём.
    if (data or {}).get("slavik_gif_sent"):
        return UNHANDLED
    await message.reply("ДАЛБАЕБ")


# Handler 2: Catch-all — priority: dead page (0) > service (0.5) > GIF (1) > photo (2) > mimic (3) > "пошёл нахуй" (4)
# Note: F5 (war words) moved to war_alert_router at position 4b (Epic 10)
# Note: F6 (slavic photo) — every N replies, send slavic_na_litso.jpg (Epic 12)
@slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID))
async def slavik_catchall_handler(message: types.Message, data: dict | None = None):
    """Reply to Slava. Priority: dead page (0) > service (0.5) > GIF (1) > photo (2) > mimic (3) > "пошёл нахуй" (4).

    T-410 (Epic 52, Section 61.4.3): жёсткий приоритет РОВНО ОДНОГО действия
    на сообщение. Mutex via if/elif/else chain.
    """
    logger.debug(
        "Slavic catchall: processing msg_id=%d from user_id=%d",
        message.message_id,
        message.from_user.id if message.from_user else 0,
    )

    # ── Branch 0: Dead Page gate (Epic 22 / D53) ──
    # d_pages-репост принадлежит dead_page_router (позиция 4). Defense-in-depth:
    # если событие всё же дошло сюда — уступить, dead page должен быть ЕДИНСТВЕННЫМ ответом.
    origin = message.forward_origin
    if isinstance(origin, MessageOriginChannel):
        src_username = settings.DEAD_PAGE_SOURCE_CHANNEL_USERNAME
        src_id = settings.DEAD_PAGE_SOURCE_CHANNEL_ID
        if (src_username and origin.chat.username == src_username) or (
            src_id and origin.chat.id == src_id
        ):
            logger.info(
                "Slavik catchall: d_pages repost — yielding to dead_page_router | msg_id=%d",
                message.message_id,
            )
            return UNHANDLED  # ни photo, ни mimic, ни «пошёл нахуй»

    # ── Branch 0.5: service-сообщение (T-410, Section 61.4.3) ──
    # join обрабатывает ТОЛЬКО slava_presence («ДОЛБОЕБ ВЕРНУЛСЯ») — без гифки/медиа.
    if message.new_chat_members or message.left_chat_member:
        return UNHANDLED

    # ── Branch 1: GIF уже отправлен (T-410, Section 61.4.1) ──
    # data-флаг ставит MessageCounterMiddleware после УСПЕШНОЙ отправки гифки.
    # Гифка уже ушла → рандом-медиа/mimic/«пошёл нахуй» НЕ выполняются,
    # фото-счётчик НЕ тикает (slavic_photo_count_tick не вызывается).
    if (data or {}).get("slavik_gif_sent"):
        logger.debug(
            "Slavic catchall: GIF already sent by middleware — no further action | msg_id=%d",
            message.message_id,
        )
        return None

    # ── Branch 2: Photo interval (F8) — random media from SLAVIC_RANDOM_DIR ──
    # T-619: интервал фото — горячая точка (фолбек settings)
    photo_interval = hot.get("limits.slavic_photo_interval",
                             settings.SLAVIC_PHOTO_INTERVAL)
    if _db is not None and photo_interval > 0:
        logger.debug(
            "Slavic photo logic: _db=%s SLAVIC_PHOTO_INTERVAL=%d",
            type(_db).__name__ if _db is not None else "None",
            photo_interval,
        )
        try:
            chat_id = message.chat.id
            should_send = await _db.slavic_photo_count_tick(
                chat_id, photo_interval
            )
            logger.debug(
                "Slavic photo: tick result=%s | chat_id=%d | interval=%d",
                should_send,
                chat_id,
                photo_interval,
            )
            if should_send:
                logger.info(
                    "Slavic Photo: interval reached | interval=%d | user_id=%d | chat_id=%d",
                    photo_interval,
                    message.from_user.id,
                    chat_id,
                )
                # Primary: pick random media from SLAVIC_RANDOM_DIR
                picked = _pick_random_slavik_media()
                if picked is not None:
                    filepath, media_type = picked
                    await _send_slavik_media(message, filepath, media_type)
                    logger.info(
                        "Slavic Photo: sent random media | file=%s | type=%s | chat_id=%d",
                        filepath.name, media_type, chat_id,
                    )
                    return
                # Fallback: deprecated SLAVIC_PHOTO_PATH (single file)
                fallback_path = settings.SLAVIC_PHOTO_PATH
                if fallback_path and Path(fallback_path).exists():
                    logger.info(
                        "Slavic Photo: fallback to deprecated path %s", fallback_path
                    )
                    await message.answer_photo(
                        photo=FSInputFile(fallback_path)
                    )
                    return
                else:
                    logger.warning(
                        "Slavic Photo: no media found in %s and fallback not available",
                        settings.SLAVIC_RANDOM_DIR,
                    )
        except Exception:
            logger.exception(
                "Slavic Photo: failed to send media, falling back | msg_id=%d",
                message.message_id,
            )

    # ── Branch 2: Mimic (F11, new) — replaces "пошёл нахуй" when conditions met ──
    content = message.text or message.caption
    if content and _slavik_mimic_should_trigger(
        message.chat.id, content,
        is_forwarded=message.forward_origin is not None,
    ):
        try:
            transformed = mimic_transform(content)
            await message.reply(transformed)
            _slavik_mimic_last_sent[message.chat.id] = time.monotonic()
            logger.info(
                "Slavik Mimic: sent | chat_id=%d | words=%d | msg_id=%d",
                message.chat.id, count_words(content), message.message_id,
            )
            return
        except Exception:
            logger.exception(
                "Slavik Mimic: failed to send, falling back to text | msg_id=%d",
                message.message_id,
            )

    # ── Branch 3: Default fallback ──
    await message.reply("пошёл нахуй")
