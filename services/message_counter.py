import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import FSInputFile, Message

from config.settings import settings
from services import hot_config as hot
from services.database import DatabaseService

logger = logging.getLogger(__name__)


class MessageCounterMiddleware(BaseMiddleware):
    """
    Inner middleware for slavik_router.

    On every message from a user on this router:
      1. Increments the DB counter for (chat_id, user_id).
      2. If new count is divisible by interval (hot.get("limits.gif_interval", settings.GIF_INTERVAL)),
         sends GIF (hot.get("reactions.gif_path", settings.GIF_PATH)) as animation.
      3. Passes to next handler (does NOT consume the update).
    """

    def __init__(self, db: DatabaseService) -> None:
        self.db = db
        self.gif_path: str = hot.get("reactions.gif_path", settings.GIF_PATH)
        self.interval: int = hot.get("limits.gif_interval", settings.GIF_INTERVAL)
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        # T-410 (Epic 52, Section 61.4.2-1): service-сообщения (join/leave) —
        # БЕЗ инкремента счётчика и БЕЗ гифки (чинит «гифка на вход Славика»).
        if getattr(event, "new_chat_members", None) or getattr(event, "left_chat_member", None):
            return await handler(event, data)

        user_id = event.from_user.id
        # Эпик 04.09.2026 (3.4.4): slavic_chlen.mp4 — строго Славику. Чужой
        # счёт не тикает и гифка не шлётся; data-флаг "slavik_gif_sent"
        # ставится только при фактической отправке Славику (hot.get — фолбек
        # settings, как остальные горячие точки этого роутера).
        slavik_id = hot.get("reactions.slavik_user_id", settings.SLAVIK_USER_ID)
        if user_id != slavik_id:
            return await handler(event, data)
        chat_id = event.chat.id

        new_count = await self.db.increment_and_get_count(chat_id, user_id)

        if self.interval > 0 and new_count % self.interval == 0:
            sent = await self._send_gif(event, chat_id, new_count)
            if sent:
                # T-410 (Section 61.4.1): флаг для slavik_catchall_handler —
                # гифка уже отправлена → никаких других действий на это сообщение.
                data["slavik_gif_sent"] = True
        elif self.interval <= 0:
            logger.warning("GIF interval is %s — GIF sending disabled", self.interval)

        return await handler(event, data)

    async def _send_gif(self, event: Message, chat_id: int, new_count: int) -> bool:
        """Send GIF. Returns True if the animation was actually sent."""
        if not Path(self.gif_path).is_file():
            logger.warning("GIF file not found: %s, skipping", self.gif_path)
            return False
        try:
            await event.answer_animation(animation=FSInputFile(self.gif_path))
        except FileNotFoundError as exc:
            logger.error("GIF file missing at send time | path=%s | error=%s", self.gif_path, exc)
            return False
        except Exception:
            logger.error("GIF send failed | path=%s", self.gif_path, exc_info=True)
            return False
        else:
            logger.info("GIF sent | path=%s | chat_id=%s | count=%s", self.gif_path, chat_id, new_count)
            return True
