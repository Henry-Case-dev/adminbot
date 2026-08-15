"""Epic 24/25 — ThrottlingMiddleware for /summary (R10, Sections 33.11 + 34.4).

Router-scoped outer middleware on summary_router only. In-memory TTL storage,
key = (chat_id, user_id). On spam: silent return WITHOUT calling the handler
(R8 by design — молчание при троттлинге сохранено, только INFO-лог).

Epic 25 (B3): mentions are validated against the bot username, symmetric to
aiogram's Command filter — a command addressed to ANOTHER bot does NOT consume
the throttle slot. Own mention (/summary@НашБот) throttles like plain /summary.
"""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import Message

from config.settings import settings

logger = logging.getLogger(__name__)


def _parse_command(text: str) -> tuple[str, str | None]:
    """Split the first token into (base, mention): '/summary@Bot' → ('/summary', 'bot')."""
    token = text.split()[0]
    base, _, mention = token.partition("@")
    return base, (mention.lower() if mention else None)


class ThrottlingMiddleware(BaseMiddleware):
    """Silently drops repeated /summary commands within the throttle window."""

    def __init__(self, throttle_seconds: float = settings.SUMMARY_THROTTLE_SECONDS) -> None:
        self._throttle_seconds = throttle_seconds
        self._last: dict[tuple[int, int], float] = {}

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and (event.text or "").strip():
            base, mention = _parse_command(event.text)
            # B3: точное сравнение — /summaryfoo не матчится (полная симметрия с Command)
            if base == "/summary":
                if mention:
                    bot = data.get("bot")
                    me = await bot.me() if bot is not None else None
                    if (
                        me is not None
                        and getattr(me, "username", None)
                        and mention != str(me.username).lower()
                    ):
                        # чужая команда — слот НЕ потребляем, событие идёт дальше
                        # (Command-фильтр сам корректно отклонит чужую mention)
                        return await handler(event, data)
                key = (event.chat.id, event.from_user.id if event.from_user else 0)
                now = time.monotonic()
                last = self._last.get(key)
                if last is not None and (now - last) < self._throttle_seconds:
                    logger.info(
                        "[/summary] throttled | chat=%s user=%s remaining=%.0fs",
                        *key, self._throttle_seconds - (now - last),
                    )
                    return  # R8: молчаливое прерывание СОХРАНЕНО
                self._last[key] = now
        return await handler(event, data)
