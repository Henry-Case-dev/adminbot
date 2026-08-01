import logging
import random
import time
from pathlib import Path
from aiogram import Router, types
from aiogram.types import FSInputFile
from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from config.settings import settings
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


def _detect_slavik_media_type(filepath: Path) -> str | None:
    """Determine media type from file extension and filename.

    Returns 'photo', 'video', 'animation', or None for unsupported.
    """
    ext = filepath.suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return "photo"
    if ext in _VIDEO_EXTENSIONS:
        if "gif" in filepath.stem.lower():
            return "animation"
        return "video"
    return None


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
        if not entry.is_file():
            continue
        media_type = _detect_slavik_media_type(entry)
        if media_type is not None:
            files.append((entry, media_type))

    if not files:
        logger.warning("Slavic Photo: no supported media files in %s", media_dir)
        return None

    picked = random.choice(files)
    logger.info(
        "Slavic Photo: picked %s (%s) from %s",
        picked[0].name, picked[1], media_dir,
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
    else:
        logger.warning("Slavic Photo: unknown media type %s for %s", media_type, filepath.name)
        await message.answer_photo(photo=input_file)


def setup_slavik(db):
    """Inject DatabaseService dependency for slavik handlers."""
    global _db
    _db = db


def _slavik_mimic_should_trigger(chat_id: int, text: str) -> bool:
    """Check mimic conditions for Slavik: word count and cooldown.

    Returns True if mimic should fire instead of the default reply.
    """
    if settings.SLAVIK_MIMIC_MIN_WORDS < 0:
        return False
    if count_words(text) <= settings.SLAVIK_MIMIC_MIN_WORDS:
        return False
    cooldown = settings.SLAVIK_MIMIC_COOLDOWN_SECONDS
    if cooldown > 0:
        last = _slavik_mimic_last_sent.get(chat_id)
        if last is not None and (time.monotonic() - last) < cooldown:
            return False
    return True


# Handler 1: F4 — KUCHA words → "ДАЛБАЕБ"
@slavik_router.message(KuchaWordFilter())
async def kucha_handler(message: types.Message):
    await message.reply("ДАЛБАЕБ")


# Handler 2: Catch-all — priority: photo (F8) > mimic (F11) > "пошёл нахуй"
# Note: F5 (war words) moved to war_alert_router at position 4b (Epic 10)
# Note: F6 (slavic photo) — every N replies, send slavic_na_litso.jpg (Epic 12)
@slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID))
async def slavik_catchall_handler(message: types.Message):
    """Reply to Slava. Priority: photo (F8) > mimic (F11) > default text.

    Mutex via if/elif/else chain — exactly ONE response per message.
    """
    logger.debug(
        "Slavic catchall: processing msg_id=%d from user_id=%d",
        message.message_id,
        message.from_user.id if message.from_user else 0,
    )

    # ── Branch 1: Photo interval (F8) — random media from SLAVIC_RANDOM_DIR ──
    if _db is not None and settings.SLAVIC_PHOTO_INTERVAL > 0:
        logger.debug(
            "Slavic photo logic: _db=%s SLAVIC_PHOTO_INTERVAL=%d",
            type(_db).__name__ if _db is not None else "None",
            settings.SLAVIC_PHOTO_INTERVAL,
        )
        try:
            chat_id = message.chat.id
            should_send = await _db.slavic_photo_count_tick(
                chat_id, settings.SLAVIC_PHOTO_INTERVAL
            )
            logger.debug(
                "Slavic photo: tick result=%s | chat_id=%d | interval=%d",
                should_send,
                chat_id,
                settings.SLAVIC_PHOTO_INTERVAL,
            )
            if should_send:
                logger.info(
                    "Slavic Photo: interval reached | interval=%d | user_id=%d | chat_id=%d",
                    settings.SLAVIC_PHOTO_INTERVAL,
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
    if content and _slavik_mimic_should_trigger(message.chat.id, content):
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
