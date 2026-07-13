import logging
import random
from aiogram import Bot
from aiogram.types import FSInputFile
from config.settings import settings
from services.database import DatabaseService
from services.media_picker import MediaService

logger = logging.getLogger(__name__)

# ── Search ranges: (lo, hi) — tried in order until a valid post is found ──
# Narrow ranges first (fast for small channels), then expand.
_DISCOVERY_RANGES: list[tuple[int, int]] = [
    (1, 10),    # Tiny channel:  1 post  → ~50%/attempt → ~97% in 5 retries
    (1, 50),    # Small channel
    (1, 200),   # Medium channel
    (1, 500),   # Large channel
    (1, 2000),  # Very large
]

_SEQUENTIAL_THRESHOLD: int = 50


class DeadPageRelay:
    """
    Dead Page V2 relay service.

    Primary flow:
      - Discover valid posts in the relay channel via progressive range probing
      - Pick and forward a random post to the target chat via forwardMessage

    Fallback flow (if channel unavailable or no posts found):
      - Pick random image + text from local media/dead_page/
      - Send via sendPhoto + optional sendMessage for overflow
    """

    def __init__(self, bot: Bot, db: DatabaseService, media: MediaService):
        self.bot = bot
        self.db = db
        self.media = media
        self.relay_channel_id = settings.DEAD_PAGE_RELAY_CHANNEL_ID
        self.max_retries = settings.DEAD_PAGE_MAX_FORWARD_RETRIES

    # ── Public API ──────────────────────────────────────────────

    async def send_dead_page(self, chat_id: int, slot: str = "repost") -> None:
        """
        Main entry point. Attempts to forward a random channel post.
        Falls back to local media if channel is unavailable or empty.
        """
        logger.info(f"[dead_page] === Triggered for chat {chat_id}, slot={slot} ===")

        if await self.db.was_dead_page_recently(
            chat_id, settings.DEAD_PAGE_COOLDOWN_SECONDS
        ):
            logger.info(
                f"[dead_page] SKIP chat {chat_id}: cooldown active "
                f"({settings.DEAD_PAGE_COOLDOWN_SECONDS}s)"
            )
            return

        success = await self._try_forward_from_channel(chat_id)

        if not success:
            logger.warning(
                f"[dead_page] FALLBACK: channel forward failed for chat {chat_id}, "
                f"using local media"
            )
            await self._fallback_local_send(chat_id)

        await self.db.record_dead_page_post(chat_id, slot)
        logger.info(f"[dead_page] === Done for chat {chat_id}, slot={slot} ===")

    # ── Channel forward ─────────────────────────────────────────

    async def _try_forward_from_channel(self, chat_id: int) -> bool:
        """
        Discover valid posts and forward a random one to chat_id.

        Strategy:
          1. If last_msg_id is known from DB, try that exact ID first (fast path).
          2. Try progressively wider random ranges.
          3. On first success → update DB ceiling and return True.
          4. If all ranges exhausted → return False (trigger fallback).
          5. If a non-"not found" error occurs → return False immediately (channel issue).
        """
        logger.info(
            f"[dead_page] Forward attempt: chat={chat_id}, "
            f"relay_channel={self.relay_channel_id}"
        )

        last_msg_id = await self.db.get_last_known_message_id()
        logger.info(f"[dead_page] DB last_known_message_id = {last_msg_id}")

        ranges = self._build_search_ranges(last_msg_id)
        logger.info(f"[dead_page] Search plan: {len(ranges)} range(s)")

        for range_idx, (lo, hi) in enumerate(ranges):
            logger.info(
                f"[dead_page] Range {range_idx + 1}/{len(ranges)}: "
                f"ID ∈ [{lo}, {hi}]"
            )

            range_size = hi - lo + 1

            if range_size <= _SEQUENTIAL_THRESHOLD:
                # D28: Sequential scan for narrow ranges — guaranteed coverage for sparse channels
                logger.info(
                    f"[dead_page] Range [{lo},{hi}] → sequential scan ({range_size} IDs)"
                )
                for msg_id in range(lo, hi + 1):
                    try:
                        await self.bot.forward_message(
                            chat_id=chat_id,
                            from_chat_id=self.relay_channel_id,
                            message_id=msg_id,
                            disable_notification=False,
                        )
                        logger.info(
                            f"[dead_page]   SUCCESS: msg_id={msg_id} forwarded to chat {chat_id} "
                            f"(sequential scan, range [{lo},{hi}])"
                        )
                        if not last_msg_id or msg_id > last_msg_id:
                            await self.db.update_last_known_message_id(msg_id)
                            logger.info(f"[dead_page]   DB updated: last_known_message_id → {msg_id}")
                        return True
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "not found" in error_msg or "bad request" in error_msg:
                            continue
                        else:
                            logger.error(
                                f"[dead_page]   CHANNEL ERROR: msg_id={msg_id} → {e}",
                                exc_info=True,
                            )
                            return False

                logger.warning(
                    f"[dead_page] Range [{lo},{hi}] exhausted "
                    f"(sequential, {range_size} IDs)"
                )
            else:
                # Random probing for large ranges
                tried: set[int] = set()
                attempts = 0
                while attempts < self.max_retries:
                    msg_id = random.randint(lo, hi)
                    if msg_id in tried:
                        continue  # D17: re-roll without burning attempt
                    tried.add(msg_id)
                    attempts += 1

                    logger.debug(
                        f"[dead_page]   Try msg_id={msg_id} "
                        f"(range [{lo},{hi}], attempt {attempts}/{self.max_retries})"
                    )

                    try:
                        await self.bot.forward_message(
                            chat_id=chat_id,
                            from_chat_id=self.relay_channel_id,
                            message_id=msg_id,
                            disable_notification=False,
                        )
                        logger.info(
                            f"[dead_page]   SUCCESS: msg_id={msg_id} forwarded to chat {chat_id} "
                            f"(range [{lo},{hi}], attempt {attempts})"
                        )
                        if not last_msg_id or msg_id > last_msg_id:
                            await self.db.update_last_known_message_id(msg_id)
                            logger.info(f"[dead_page]   DB updated: last_known_message_id → {msg_id}")
                        return True

                    except Exception as e:
                        error_msg = str(e).lower()
                        if "not found" in error_msg or "bad request" in error_msg:
                            logger.debug(
                                f"[dead_page]   NOT FOUND: msg_id={msg_id} "
                                f"(attempt {attempts})"
                            )
                            continue
                        else:
                            logger.error(
                                f"[dead_page]   CHANNEL ERROR: msg_id={msg_id} → {e}",
                                exc_info=True,
                            )
                            return False

                logger.warning(
                    f"[dead_page] Range [{lo},{hi}] exhausted "
                    f"({self.max_retries} misses)"
                )

        logger.error(
            f"[dead_page] ALL RANGES EXHAUSTED for chat {chat_id}: "
            f"no valid posts found in channel {self.relay_channel_id}. "
            f"DB last_msg_id={last_msg_id}. "
            f"Possible causes: channel is empty, all posts deleted, "
            f"or last_known_message_id is way off."
        )
        return False

    def _build_search_ranges(
        self, last_msg_id: int | None
    ) -> list[tuple[int, int]]:
        """
        Build search ranges. If we know the last valid ID, anchor around it.
        Otherwise use the predefined discovery ranges.
        """
        if last_msg_id and last_msg_id > 0:
            anchored = [
                (1, last_msg_id),
                (1, max(last_msg_id * 2, 100)),
            ]
            # Добавляем _DISCOVERY_RANGES как safety net: если канал вырос
            # далеко за пределы anchored-диапазонов, прогрессивные диапазоны
            # ([1,10], [1,50], [1,200], [1,500], [1,2000]) найдут свежие посты.
            anchored.extend(_DISCOVERY_RANGES)
            return anchored
        return list(_DISCOVERY_RANGES)

    # ── Fallback: local media ───────────────────────────────────

    async def _fallback_local_send(self, chat_id: int) -> None:
        """
        Fallback: send dead page from local media/dead_page/ directory.
        Uses sendPhoto (caption ≤ 1024) + optional sendMessage for overflow.
        """
        logger.info(f"[dead_page] Fallback: picking local media for chat {chat_id}")

        try:
            photo_path, text = await self.media.pick_random()
            logger.info(
                f"[dead_page] Fallback media: photo={photo_path}, "
                f"text_len={len(text)}"
            )
        except FileNotFoundError as e:
            logger.error(f"[dead_page] Fallback FAILED: no local media — {e}")
            return

        max_chars = settings.DEAD_PAGE_CAPTION_MAX_CHARS
        caption = text[:max_chars]
        overflow = text[max_chars:] if len(text) > max_chars else ""

        if overflow:
            logger.info(
                f"[dead_page] Fallback: text {len(text)} chars → "
                f"caption {len(caption)} + overflow {len(overflow)}"
            )

        try:
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(photo_path),
                caption=caption,
            )
            logger.info(f"[dead_page] Fallback: photo sent to chat {chat_id}")

            if overflow:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=overflow,
                )
                logger.info(f"[dead_page] Fallback: overflow text sent to chat {chat_id}")

        except Exception as e:
            logger.error(
                f"[dead_page] Fallback SEND FAILED for chat {chat_id}: {e}",
                exc_info=True,
            )
