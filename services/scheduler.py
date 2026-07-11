import asyncio
import logging
from config.settings import settings

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Simplified scheduler for Dead Page V2.
    
    Time-based scheduling (morning/evening) has been REMOVED.
    Now only handles the immediate join trigger (F1).
    
    Delegates actual dead page sending to DeadPageRelay.
    """
    
    DEDUP_WINDOW = 10  # seconds — prevent duplicate join posts
    
    def __init__(self, relay=None, target_user_id: int = None, post_on_join: bool = None):
        """
        Args:
            relay: DeadPageRelay instance (injected by bot.py)
            target_user_id: Slava's user ID
            post_on_join: Override DEAD_PAGE_POST_ON_JOIN (default: from settings)
        """
        self.relay = relay
        self.target_user_id = target_user_id or settings.SLAVIK_USER_ID
        self.post_on_join = post_on_join if post_on_join is not None else settings.DEAD_PAGE_POST_ON_JOIN
        self._last_join_post: float = 0
    
    async def run(self) -> None:
        """
        No-op loop for backward compatibility.
        Kept as a placeholder — does nothing, never returns unless cancelled.
        """
        logger.info("Scheduler running (no-op, join-trigger only)")
        while True:
            await asyncio.sleep(3600)  # Sleep for an hour, just to exist
    
    async def signal_immediate_post(self, chat_id: int) -> None:
        """
        Called by F1 handler when Slava joins.
        Sends a dead page if DEAD_PAGE_POST_ON_JOIN is enabled.
        """
        if not self.post_on_join:
            logger.debug(f"Join trigger disabled, skipping dead page for chat {chat_id}")
            return
        
        now = asyncio.get_running_loop().time()
        if now - self._last_join_post < self.DEDUP_WINDOW:
            logger.debug(f"Join trigger dedup: skipping for chat {chat_id}")
            return
        self._last_join_post = now
        
        if self.relay is None:
            logger.error("DeadPageRelay not injected — cannot send dead page on join")
            return
        
        logger.info(f"Join trigger: sending dead page to chat {chat_id}")
        await self.relay.send_dead_page(chat_id, slot="join")
