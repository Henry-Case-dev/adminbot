import datetime
import logging
import random
from aiogram import Bot
from aiogram.types import FSInputFile
from config.settings import settings
from services.database import DatabaseService
from services.media_picker import MediaService

logger = logging.getLogger(__name__)

# ── Epic 14: Album detection constants ──
_ALBUM_PROBE_RANGE: int = 9          # max siblings to probe in each direction
_ALBUM_DATE_TOLERANCE_S: int = 2     # seconds between post dates to consider same album
_MAX_CONSECUTIVE_GAPS: int = 2       # max deleted messages to skip before stopping probe

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
                        result = await self._forward_with_album_detection(
                            chat_id, msg_id, last_msg_id
                        )
                        logger.info(
                            f"[dead_page]   SUCCESS: msg_id={msg_id} forwarded to chat {chat_id} "
                            f"(sequential scan, range [{lo},{hi}])"
                        )
                        return result
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
                        result = await self._forward_with_album_detection(
                            chat_id, msg_id, last_msg_id
                        )
                        logger.info(
                            f"[dead_page]   SUCCESS: msg_id={msg_id} forwarded to chat {chat_id} "
                            f"(range [{lo},{hi}], attempt {attempts})"
                        )
                        return result

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

    # ── Album-aware forwarding (Epic 14) ──────────────────────

    @staticmethod
    def _normalize_date(dt: datetime.datetime) -> datetime.datetime:
        """Strip timezone info to ensure safe datetime comparison."""
        return dt.replace(tzinfo=None) if dt.tzinfo else dt

    async def _safe_delete(self, chat_id: int, message_id: int) -> None:
        """Try to delete a probe message; log warning on failure (no permission)."""
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.debug(f"[dead_page] Deleted non-album probe msg_id={message_id}")
        except Exception as e:
            logger.warning(
                f"[dead_page] Failed to delete probe msg_id={message_id}: {e}"
            )

    async def _forward_with_album_detection(
        self, chat_id: int, msg_id: int, last_msg_id: int | None
    ) -> bool:
        """
        Forward msg_id to chat_id. If msg_id belongs to an album (media group),
        forward all siblings too.

        Path 1 (DB): media_group_id known → forward_messages() for entire album.
        Path 2 (Heuristic): no DB entry → probe adjacent IDs with date matching.

        Returns True on success. Raises exceptions for primary forward failures
        (caller handles "not found" and channel errors).
        """
        # PATH 1: DB lookup — known album
        media_group_id = await self.db.get_relay_media_group_id(msg_id)
        if media_group_id:
            album_ids = await self.db.get_relay_album_message_ids(media_group_id)
            # SQL ORDER BY already sorts; no need for .sort()
            logger.info(
                f"[dead_page]   Album (DB lookup): {len(album_ids)} messages, "
                f"IDs={album_ids}"
            )
            await self.bot.forward_messages(
                chat_id=chat_id,
                from_chat_id=self.relay_channel_id,
                message_ids=album_ids,
                disable_notification=False,
            )
            if album_ids:
                max_id = max(album_ids)
                if not last_msg_id or max_id > last_msg_id:
                    await self.db.update_last_known_message_id(max_id)
                    logger.info(
                        f"[dead_page]   DB updated: last_known_message_id → {max_id}"
                    )
            return True

        # PATH 2: Heuristic fallback — probe adjacent IDs
        return await self._forward_with_heuristic(chat_id, msg_id, last_msg_id)

    async def _forward_with_heuristic(
        self, chat_id: int, msg_id: int, last_msg_id: int | None
    ) -> bool:
        """
        Heuristic album detection using Collect-then-Group strategy.

        Phase 1 — Probe & Collect: forward each candidate to determine date,
        collect matching IDs instead of keeping each forward as a separate message.

        Phase 2 — Group Forward: if siblings were found, delete the individually
        forwarded messages and re-forward everything as a single forward_messages
        call to preserve album grouping.
        """
        collected_ids: list[int] = [msg_id]
        probe_forwarded_ids: list[int] = []  # track probe msgs for deletion

        # Phase 1: Forward primary to get base date
        sent = await self.bot.forward_message(
            chat_id=chat_id,
            from_chat_id=self.relay_channel_id,
            message_id=msg_id,
            disable_notification=False,
        )
        base_date = self._normalize_date(sent.date)
        primary_sent_msg_id = sent.message_id

        # Phase 2a: Probe forward (msg_id+1, +2, ..., +_ALBUM_PROBE_RANGE)
        consecutive_gaps = 0
        for offset in range(1, _ALBUM_PROBE_RANGE + 1):
            candidate = msg_id + offset
            try:
                sibling = await self.bot.forward_message(
                    chat_id=chat_id,
                    from_chat_id=self.relay_channel_id,
                    message_id=candidate,
                    disable_notification=True,
                )
                sibling_date = self._normalize_date(sibling.date)
                if abs((sibling_date - base_date).total_seconds()) <= _ALBUM_DATE_TOLERANCE_S:
                    collected_ids.append(candidate)
                    probe_forwarded_ids.append(sibling.message_id)
                    consecutive_gaps = 0
                else:
                    await self._safe_delete(chat_id, sibling.message_id)
                    break
            except Exception as e:
                err = str(e).lower()
                if "not found" in err or "bad request" in err:
                    consecutive_gaps += 1
                    if consecutive_gaps > _MAX_CONSECUTIVE_GAPS:
                        break
                    continue
                raise

        # Phase 2b: Probe backward (msg_id-1, -2, ..., -_ALBUM_PROBE_RANGE)
        consecutive_gaps = 0
        for offset in range(1, _ALBUM_PROBE_RANGE + 1):
            candidate = msg_id - offset
            if candidate < 1:
                break
            try:
                sibling = await self.bot.forward_message(
                    chat_id=chat_id,
                    from_chat_id=self.relay_channel_id,
                    message_id=candidate,
                    disable_notification=True,
                )
                sibling_date = self._normalize_date(sibling.date)
                if abs((sibling_date - base_date).total_seconds()) <= _ALBUM_DATE_TOLERANCE_S:
                    collected_ids.append(candidate)
                    probe_forwarded_ids.append(sibling.message_id)
                    consecutive_gaps = 0
                else:
                    await self._safe_delete(chat_id, sibling.message_id)
                    break
            except Exception as e:
                err = str(e).lower()
                if "not found" in err or "bad request" in err:
                    consecutive_gaps += 1
                    if consecutive_gaps > _MAX_CONSECUTIVE_GAPS:
                        break
                    continue
                raise

        # Phase 3: Group forward if siblings found
        if len(collected_ids) > 1:
            sorted_ids = sorted(collected_ids)
            # Delete primary and all matching probes before group forward
            await self._safe_delete(chat_id, primary_sent_msg_id)
            for probe_id in probe_forwarded_ids:
                await self._safe_delete(chat_id, probe_id)
            try:
                await self.bot.forward_messages(
                    chat_id=chat_id,
                    from_chat_id=self.relay_channel_id,
                    message_ids=sorted_ids,
                    disable_notification=False,
                )
            except Exception:
                logger.exception(
                    "[dead_page]   forward_messages failed for album IDs=%s",
                    sorted_ids,
                )
                return False
            logger.info(
                "[dead_page]   Album (heuristic): %d messages, IDs=%s",
                len(sorted_ids),
                sorted_ids,
            )

        # Phase 4: Update DB with max forwarded ID
        max_id = max(collected_ids)
        if not last_msg_id or max_id > last_msg_id:
            await self.db.update_last_known_message_id(max_id)
            logger.info(
                "[dead_page]   DB updated: last_known_message_id → %d", max_id
            )

        return True

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
