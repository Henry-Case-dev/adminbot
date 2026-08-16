import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import FSInputFile, Message

from config.settings import settings
from services.database import DatabaseService

logger = logging.getLogger(__name__)


class MessageCounterMiddleware(BaseMiddleware):
    """
    Inner middleware for slavik_router.

    On every message from a user on this router:
      1. Increments the DB counter for (chat_id, user_id).
      2. If new count is divisible by interval (settings.GIF_INTERVAL),
         sends GIF (settings.GIF_PATH) as animation.
      3. Passes to next handler (does NOT consume the update).
    """

    def __init__(self, db: DatabaseService) -> None:
        self.db = db
        self.gif_path: str = settings.GIF_PATH
        self.interval: int = settings.GIF_INTERVAL
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user_id = event.from_user.id
        chat_id = event.chat.id

        new_count = await self.db.increment_and_get_count(chat_id, user_id)

        if self.interval > 0 and new_count % self.interval == 0:
            await self._send_gif(event, chat_id, new_count)
        elif self.interval <= 0:
            logger.warning("GIF interval is %s — GIF sending disabled", self.interval)

        return await handler(event, data)

    async def _send_gif(self, event: Message, chat_id: int, new_count: int) -> None:
        if not Path(self.gif_path).is_file():
            logger.warning("GIF file not found: %s, skipping", self.gif_path)
            return
        try:
            await event.answer_animation(animation=FSInputFile(self.gif_path))
        except FileNotFoundError as exc:
            logger.error("GIF file missing at send time | path=%s | error=%s", self.gif_path, exc)
        except Exception:
            logger.error("GIF send failed | path=%s", self.gif_path, exc_info=True)
        else:
            logger.info("GIF sent | path=%s | chat_id=%s | count=%s", self.gif_path, chat_id, new_count)
