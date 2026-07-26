import logging
import time
from pathlib import Path
from aiogram import Bot
from aiogram.types import FSInputFile, ReplyParameters
from config.settings import settings

logger = logging.getLogger(__name__)


class OtboyRelay:
    """Responds to "отбой" keyword with otboy.jpg photo.

    Per-chat cooldown prevents spam within the configured interval.
    """

    def __init__(self, bot: Bot, cooldown_seconds: int):
        self._bot = bot
        self._cooldown_seconds = cooldown_seconds
        # NOTE: No TTL cleanup — acceptable for small number of chats.
        self._cooldowns: dict[int, float] = {}

        if not Path(settings.OTBOY_PHOTO_PATH).exists():
            logger.warning(
                "OtboyRelay: photo file not found at %s",
                settings.OTBOY_PHOTO_PATH,
            )

    async def send_otboy(
        self, chat_id: int, message_id: int, matched_word: str
    ) -> None:
        """Send otboy.jpg as a reply quoting the matched word.

        Args:
            chat_id: Target chat ID.
            message_id: Original message to reply to.
            matched_word: The exact word that triggered the filter.
        """
        now = time.monotonic()

        if self._cooldown_seconds > 0:
            last_sent = self._cooldowns.get(chat_id)
            if last_sent is not None:
                elapsed = now - last_sent
                if elapsed < self._cooldown_seconds:
                    logger.info(
                        "OtboyRelay: cooldown_active | chat_id=%s | elapsed=%.1fs | remaining=%.1fs",
                        chat_id,
                        elapsed,
                        self._cooldown_seconds - elapsed,
                    )
                    return
                logger.debug(
                    "OtboyRelay: cooldown_expired | chat_id=%s | elapsed=%.1fs",
                    chat_id,
                    elapsed,
                )

        try:
            await self._bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(settings.OTBOY_PHOTO_PATH),
                reply_parameters=ReplyParameters(
                    message_id=message_id,
                    quote=matched_word,
                ),
            )
            self._cooldowns[chat_id] = now
            logger.info(
                "OtboyRelay: sent | chat_id=%s | message_id=%s | matched_word=%r",
                chat_id,
                message_id,
                matched_word,
            )
        except Exception:
            logger.exception(
                "OtboyRelay: send_photo failed | chat_id=%s | message_id=%s | photo_path=%s",
                chat_id,
                message_id,
                settings.OTBOY_PHOTO_PATH,
            )
