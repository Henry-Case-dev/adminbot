"""Epic 24 — ThrottlingMiddleware for /summary (R10, Section 33.11).

Router-scoped outer middleware on summary_router only. In-memory TTL storage,
key = (chat_id, user_id). On spam: silent return WITHOUT calling the handler.
"""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import Message

from config.settings import settings

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Silently drops repeated /summary commands within the throttle window."""

    def __init__(self, throttle_seconds: float = settings.SUMMARY_THROTTLE_SECONDS) -> None:
        self._throttle_seconds = throttle_seconds
        self._last: dict[tuple[int, int], float] = {}

    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            text = event.text or ""
            first_token = text.split()[0] if text.strip() else ""
            # отрезаем суффикс @BotName (review Low-3): /summary@MyBot → /summary
            command = first_token.split("@", 1)[0]
            if command.startswith("/summary"):
                key = (event.chat.id, event.from_user.id if event.from_user else 0)
                now = time.monotonic()
                last = self._last.get(key)
                if last is not None and (now - last) < self._throttle_seconds:
                    logger.info("[/summary] throttled | chat=%s user=%s", *key)
                    return
                self._last[key] = now
        return await handler(event, data)
