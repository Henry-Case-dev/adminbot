import logging
from pathlib import Path
from aiogram import Router, types
from aiogram.types import FSInputFile
from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from config.settings import settings

logger = logging.getLogger(__name__)

slavik_router = Router()

# DB reference injected via setup_slavik()
_db = None


def setup_slavik(db):
    """Inject DatabaseService dependency for slavik handlers."""
    global _db
    _db = db


# Handler 1: F4 — KUCHA words → "ДАЛБАЕБ"
@slavik_router.message(KuchaWordFilter())
async def kucha_handler(message: types.Message):
    await message.reply("ДАЛБАЕБ")


# Handler 2: Catch-all → "пошёл нахуй" (original behavior)
# Note: F5 (war words) moved to war_alert_router at position 4b (Epic 10)
# Note: F6 (slavic photo) — every N replies, send slavic_na_litso.jpg (Epic 12)
@slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID))
async def slavik_catchall_handler(message: types.Message):
    """Reply to Slava. Every N replies, send photo instead of text."""
    # Check if it's time for the photo
    if _db is not None and settings.SLAVIC_PHOTO_INTERVAL > 0:
        try:
            chat_id = message.chat.id
            should_send_photo = await _db.slavic_photo_count_tick(
                chat_id, settings.SLAVIC_PHOTO_INTERVAL
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
                "Slavic Photo: failed to send photo, falling back to text | msg_id=%d",
                message.message_id,
            )
    await message.reply("пошёл нахуй")
