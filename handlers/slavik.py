import logging
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

    # ── Branch 1: Photo interval (F8) — DO NOT TOUCH existing logic ──
    if _db is not None and settings.SLAVIC_PHOTO_INTERVAL > 0:
        logger.debug(
            "Slavic photo logic: _db=%s SLAVIC_PHOTO_INTERVAL=%d",
            type(_db).__name__ if _db is not None else "None",
            settings.SLAVIC_PHOTO_INTERVAL,
        )
        try:
            chat_id = message.chat.id
            should_send_photo = await _db.slavic_photo_count_tick(
                chat_id, settings.SLAVIC_PHOTO_INTERVAL
            )
            logger.debug(
                "Slavic photo: tick result=%s | chat_id=%d | interval=%d",
                should_send_photo,
                chat_id,
                settings.SLAVIC_PHOTO_INTERVAL,
            )
            if should_send_photo:
                logger.info(
                    "Slavic Photo: interval reached | interval=%d | user_id=%d | chat_id=%d",
                    settings.SLAVIC_PHOTO_INTERVAL,
                    message.from_user.id,
                    chat_id,
                )
                if not Path(settings.SLAVIC_PHOTO_PATH).exists():
                    logger.warning(
                        "Slavic Photo: file not found: %s", settings.SLAVIC_PHOTO_PATH
                    )
                else:
                    await message.answer_photo(
                        photo=FSInputFile(settings.SLAVIC_PHOTO_PATH)
                    )
                    return
        except Exception:
            logger.exception(
                "Slavic Photo: failed to send photo, falling back | msg_id=%d",
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
