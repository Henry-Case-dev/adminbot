import asyncio
import datetime
import logging
from aiogram import Bot
from aiogram.types import FSInputFile
from services.database import DatabaseService
from services.media_picker import MediaService

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Background scheduler for dead-page posts (F2).
    
    Runs an infinite loop:
      - Every POLL_INTERVAL seconds, checks if it's time to post.
      - Two slots: morning (MORNING_HOUR) and evening (EVENING_HOUR).
      - Only posts if Slava is_present in the chat.
    """
    
    MORNING_HOUR = 10
    EVENING_HOUR = 20
    POLL_INTERVAL = 60
    DEDUP_WINDOW = 10  # seconds — prevent duplicate join posts
    
    def __init__(self, bot: Bot, db: DatabaseService, target_user_id: int = 479167456):
        self.bot = bot
        self.db = db
        self.target_user_id = target_user_id
        self.media = MediaService()
        self._last_join_post: float = 0
    
    async def run(self) -> None:
        """Main scheduler loop. Never returns unless cancelled."""
        logger.info("Scheduler started")
        while True:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}")
            await asyncio.sleep(self.POLL_INTERVAL)
    
    async def _tick(self) -> None:
        """Check and post for all present chats."""
        now = datetime.datetime.now()
        current_hour = now.hour
        
        slot = None
        if self.MORNING_HOUR <= current_hour < self.MORNING_HOUR + 1:
            slot = 'morning'
        elif self.EVENING_HOUR <= current_hour < self.EVENING_HOUR + 1:
            slot = 'evening'
        
        if slot is None:
            return
        
        chats = await self.db.get_present_chats(self.target_user_id)
        
        for chat_id in chats:
            already_posted = await self.db.has_post_today(chat_id, slot)
            if not already_posted:
                await self._send_dead_page(chat_id, slot)
    
    async def signal_immediate_post(self, chat_id: int) -> None:
        """Called by F1 handler when Slava joins."""
        loop = asyncio.get_event_loop()
        now = loop.time()
        if now - self._last_join_post < self.DEDUP_WINDOW:
            return
        self._last_join_post = now
        await self._send_dead_page(chat_id, 'join')
    
    async def _send_dead_page(self, chat_id: int, slot: str) -> None:
        """Pick random media and post to chat."""
        try:
            photo_path, text = await self.media.pick_random()
        except FileNotFoundError as e:
            logger.error(f"Dead page media missing: {e}")
            return
        
        caption = text[:1024]
        
        try:
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(photo_path),
                caption=caption
            )
            if len(text) > 1024:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text[1024:]
                )
        except Exception as e:
            logger.error(f"Failed to send dead page: {e}")
            return
        
        await self.db.record_post(chat_id, slot)
