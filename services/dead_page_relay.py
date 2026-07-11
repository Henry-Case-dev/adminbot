import logging
import random
from aiogram import Bot
from aiogram.types import FSInputFile
from config.settings import settings
from services.database import DatabaseService
from services.media_picker import MediaService

logger = logging.getLogger(__name__)


class DeadPageRelay:
    """
    Dead Page V2 relay service.
    
    Primary flow:
      - Pick a random existing post from the relay channel
      - Forward that post to the target chat via forwardMessage
    
    Fallback flow (if channel unavailable):
      - Pick random image + text from local media/dead_page/
      - Send via sendPhoto + optional sendMessage for overflow
    """
    
    def __init__(self, bot: Bot, db: DatabaseService, media: MediaService):
        self.bot = bot
        self.db = db
        self.media = media
        self.relay_channel_id = settings.DEAD_PAGE_RELAY_CHANNEL_ID
        self.max_retries = settings.DEAD_PAGE_MAX_FORWARD_RETRIES
    
    async def send_dead_page(self, chat_id: int, slot: str = "repost") -> None:
        """
        Main entry point. Attempts to forward a random channel post.
        Falls back to local media if channel is unavailable.
        """
        # Anti-spam check
        if await self.db.was_dead_page_recently(
            chat_id, settings.DEAD_PAGE_COOLDOWN_SECONDS
        ):
            logger.info(
                f"Dead page skipped for chat {chat_id}: cooldown active "
                f"({settings.DEAD_PAGE_COOLDOWN_SECONDS}s)"
            )
            return
        
        # Try primary: forward from relay channel
        success = await self._try_forward_from_channel(chat_id)
        
        if not success:
            # Fallback: local media
            logger.warning(
                f"Channel forward failed for chat {chat_id}, using local fallback"
            )
            await self._fallback_local_send(chat_id)
        
        # Record the post
        await self.db.record_dead_page_post(chat_id, slot)
        logger.info(f"Dead page sent to chat {chat_id}, slot={slot}")
    
    async def _try_forward_from_channel(self, chat_id: int) -> bool:
        """
        Try to forward a random post from the relay channel.
        Returns True on success, False on failure.
        """
        try:
            # Get the last known message_id from DB
            last_msg_id = await self.db.get_last_known_message_id()
            
            if last_msg_id is None or last_msg_id < 1:
                logger.warning("No known message_id in relay channel, trying to discover...")
                # Try chat info to discover — but we can't easily get message count
                # Fall back to trying message_id from 1 to 100
                last_msg_id = 100
                await self.db.update_last_known_message_id(last_msg_id)
            
            # Pick random message_id with retries
            tried: set[int] = set()
            for attempt in range(self.max_retries):
                msg_id = random.randint(1, last_msg_id)
                if msg_id in tried:
                    continue
                tried.add(msg_id)
                
                try:
                    await self.bot.forward_message(
                        chat_id=chat_id,
                        from_chat_id=self.relay_channel_id,
                        message_id=msg_id,
                        disable_notification=False,
                    )
                    logger.info(
                        f"Forwarded channel post msg_id={msg_id} "
                        f"to chat {chat_id} (attempt {attempt + 1})"
                    )
                    return True
                    
                except Exception as e:
                    error_msg = str(e)
                    if "message to forward not found" in error_msg.lower() or \
                       "message not found" in error_msg.lower() or \
                       "bad request" in error_msg.lower():
                        logger.debug(
                            f"msg_id={msg_id} not found in relay channel "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        continue
                    else:
                        # Different error — channel might be inaccessible
                        logger.error(
                            f"Failed to forward msg_id={msg_id}: {e}"
                        )
                        return False
            
            logger.error(
                f"All {self.max_retries} forward attempts failed for chat {chat_id}"
            )
            return False
            
        except Exception as e:
            logger.error(f"Channel forward failed for chat {chat_id}: {e}")
            return False
    
    async def _fallback_local_send(self, chat_id: int) -> None:
        """
        Fallback: send dead page from local media/dead_page/ directory.
        Uses the old pattern: sendPhoto + optional sendMessage for overflow.
        """
        try:
            photo_path, text = await self.media.pick_random()
        except FileNotFoundError as e:
            logger.error(f"Local dead page media missing: {e}")
            return
        
        caption = text[:settings.DEAD_PAGE_CAPTION_MAX_CHARS]
        if len(text) > settings.DEAD_PAGE_CAPTION_MAX_CHARS:
            logger.warning(
                f"Dead page text truncated for fallback: "
                f"{len(text)} → {len(caption)} chars"
            )
        
        try:
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(photo_path),
                caption=caption,
            )
            logger.info(f"Fallback photo sent to chat {chat_id}")
            
            if len(text) > settings.DEAD_PAGE_CAPTION_MAX_CHARS:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text[settings.DEAD_PAGE_CAPTION_MAX_CHARS:],
                )
                logger.info(f"Fallback text overflow sent to chat {chat_id}")
                
        except Exception as e:
            logger.error(f"Fallback send failed for chat {chat_id}: {e}")
