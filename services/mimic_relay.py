"""MimicRelay — cooldown and dispatch for mimic feature (common service, §3.1).

Encapsulates: per-(chat_id, user_id) cooldown, word-count threshold,
mimic_transform call, and reply sending.

Follows the same in-memory cooldown pattern as CommonRelay/OtboyRelay.
"""
import logging
import time

from aiogram import Bot
from services.mimic_transform import mimic_transform, count_words

logger = logging.getLogger(__name__)


class MimicRelay:
    """Sends 'mimic' (teasing/lisp) replies to target user messages.

    Cooldown: per (chat_id, user_id), in-memory, no DB.
    """

    def __init__(self, min_words: int, cooldown_seconds: float) -> None:
        self._min_words = min_words
        self._cooldown_seconds = cooldown_seconds
        self._last_sent: dict[tuple[int, int], float] = {}

    def should_trigger(self, chat_id: int, user_id: int, text: str) -> bool:
        """Check conditions: word count > min_words AND cooldown elapsed.

        Does NOT update cooldown — caller must call mark_sent()
        after successful send to avoid false-positive timer bump on errors.
        """
        if count_words(text) <= self._min_words:
            return False
        if self._cooldown_seconds > 0:
            key = (chat_id, user_id)
            last = self._last_sent.get(key)
            if last is not None and (time.monotonic() - last) < self._cooldown_seconds:
                return False
        return True

    def mark_sent(self, chat_id: int, user_id: int) -> None:
        """Record that a mimic reply was sent for (chat_id, user_id)."""
        self._last_sent[(chat_id, user_id)] = time.monotonic()

    async def send_mimic(
        self,
        bot: Bot,
        chat_id: int,
        message_id: int,
        text: str,
    ) -> None:
        """Transform text and send as reply with quote."""
        transformed = mimic_transform(text)
        await bot.send_message(
            chat_id=chat_id,
            text=transformed,
            reply_to_message_id=message_id,
        )
        logger.info(
            "MimicRelay: sent | chat_id=%s | msg_id=%s | len=%d",
            chat_id, message_id, len(transformed),
        )
