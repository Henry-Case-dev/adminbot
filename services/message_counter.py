from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import Message, FSInputFile
from services.database import DatabaseService


class MessageCounterMiddleware(BaseMiddleware):
    """
    Inner middleware for slavik_router.
    
    On every message from a user on this router:
      1. Increments the DB counter for (chat_id, user_id).
      2. If new count is divisible by INTERVAL, sends GIF as animation.
      3. Passes to next handler (does NOT consume the update).
    """
    
    GIF_PATH = "media/slavic_chlen.mp4"
    INTERVAL = 5
    
    def __init__(self, db: DatabaseService):
        self.db = db
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
        
        if new_count % self.INTERVAL == 0:
            try:
                await event.answer_animation(
                    animation=FSInputFile(self.GIF_PATH)
                )
            except Exception:
                pass  # Silently ignore errors sending GIF
        
        return await handler(event, data)
