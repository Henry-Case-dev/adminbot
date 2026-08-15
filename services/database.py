import asyncio
import datetime
import logging
import time
import aiosqlite
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseService:
    """Async SQLite wrapper using aiosqlite. Manages schema, connections, and all queries."""
    
    _SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS user_presence (
            user_id    INTEGER NOT NULL,
            chat_id    INTEGER NOT NULL,
            is_present INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, chat_id)
        );
        
        CREATE TABLE IF NOT EXISTS message_counters (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );
        
        CREATE TABLE IF NOT EXISTS dead_page_posts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            slot      TEXT    NOT NULL,
            date      TEXT    NOT NULL,
            timestamp INTEGER
        );

        CREATE TABLE IF NOT EXISTS channel_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relay_album_map (
            message_id INTEGER PRIMARY KEY,
            media_group_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_relay_album_media_group ON relay_album_map(media_group_id);
    """
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Open connection, create tables, enable WAL mode."""
        self.db = await aiosqlite.connect(str(self.db_path))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(self._SCHEMA_SQL)
        await self.db.commit()

        # Migration: add timestamp column if missing (Dead Page V2)
        try:
            await self.db.execute("ALTER TABLE dead_page_posts ADD COLUMN timestamp INTEGER")
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists
    
    async def close(self) -> None:
        if self.db:
            await self.db.close()
    
    # ── Slava Presence ──────────────────────────────────
    
    async def set_presence(self, user_id: int, chat_id: int, present: bool) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO user_presence (user_id, chat_id, is_present) VALUES (?, ?, ?)",
            (user_id, chat_id, 1 if present else 0)
        )
        await self.db.commit()
    
    async def is_present(self, user_id: int, chat_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT is_present FROM user_presence WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        row = await cursor.fetchone()
        return bool(row and row["is_present"])
    
    async def get_present_chats(self, user_id: int) -> list[int]:
        cursor = await self.db.execute(
            "SELECT chat_id FROM user_presence WHERE user_id = ? AND is_present = 1",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [row["chat_id"] for row in rows]
    
    # ── Message Counters ────────────────────────────────
    
    async def increment_and_get_count(self, chat_id: int, user_id: int) -> int:
        """Atomically increment counter and return new value."""
        async with self._lock:
            await self.db.execute(
                "INSERT INTO message_counters (chat_id, user_id, count) "
                "VALUES (?, ?, 1) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1",
                (chat_id, user_id)
            )
            await self.db.commit()
            cursor = await self.db.execute(
                "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            row = await cursor.fetchone()
            return row["count"] if row else 0
    
    async def get_count(self, chat_id: int, user_id: int) -> int:
        cursor = await self.db.execute(
            "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0
    
    # ── Dead Page Posts ─────────────────────────────────

    async def was_dead_page_recently(self, chat_id: int, cooldown_seconds: int) -> bool:
        """Check if a dead page was posted in this chat within the last N seconds."""
        cutoff = int(time.time()) - cooldown_seconds
        cursor = await self.db.execute(
            "SELECT 1 FROM dead_page_posts WHERE chat_id = ? AND slot = 'repost' AND timestamp > ?",
            (chat_id, cutoff)
        )
        row = await cursor.fetchone()
        return row is not None

    async def record_dead_page_post(self, chat_id: int, slot: str) -> None:
        """Record that a dead page post was made."""
        today = datetime.date.today().isoformat()
        now_ts = int(time.time())
        await self.db.execute(
            "INSERT INTO dead_page_posts (chat_id, slot, date, timestamp) VALUES (?, ?, ?, ?)",
            (chat_id, slot, today, now_ts)
        )
        await self.db.commit()

    # ── Alan Activity ──────────────────────────────────

    async def get_alan_last_message_ts(self, chat_id: int) -> float | None:
        """Get the timestamp of Alan's last message in a chat."""
        key = f"alan_last_msg:{chat_id}"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            try:
                return float(row["value"])
            except (ValueError, TypeError):
                return None
        return None

    async def set_alan_last_message_ts(self, chat_id: int, timestamp: float) -> None:
        """Record the timestamp of Alan's last message in a chat."""
        key = f"alan_last_msg:{chat_id}"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(timestamp))
        )
        await self.db.commit()

    # ── Channel State ───────────────────────────────────

    async def get_last_known_message_id(self, channel_id: int = 0) -> int | None:
        """Get the last known message_id in the relay channel."""
        key = f"last_msg_id:{channel_id}" if channel_id else "last_known_message_id"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            return int(row["value"])
        return None

    async def update_last_known_message_id(self, msg_id: int, channel_id: int = 0) -> None:
        """Update the last known message_id in the relay channel."""
        key = f"last_msg_id:{channel_id}" if channel_id else "last_known_message_id"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(msg_id))
        )
        await self.db.commit()

    # ── Dead Page Anti-Repeat (Epic 22 / D54) ─────────────

    async def get_dead_page_last_sent(self, chat_id: int) -> int | None:
        """Primary relay-channel msg_id forwarded into this chat last time (anti-repeat).

        Uses channel_state key `dead_page_last_sent:{chat_id}`. Returns None when
        the key is missing or holds a broken (non-int) value.
        """
        key = f"dead_page_last_sent:{chat_id}"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            try:
                return int(row["value"])
            except (ValueError, TypeError):
                return None
        return None

    async def set_dead_page_last_sent(self, chat_id: int, msg_id: int) -> None:
        """Record the primary relay-channel msg_id forwarded into this chat."""
        key = f"dead_page_last_sent:{chat_id}"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(msg_id)),
        )
        await self.db.commit()

    # ── Slavic Photo Counter (Epic 12) ──

    async def slavic_photo_count_tick(self, chat_id: int, interval: int) -> bool:
        """Increment Slava's photo counter. Returns True if photo should be sent.

        Counter auto-resets after reaching the configured interval.
        Uses channel_state key: slavic_photo:{chat_id}
        """
        key = f"slavic_photo:{chat_id}"
        logger.debug("slavic_photo_count_tick: key=%s interval=%d", key, interval)
        async with self._lock:
            cursor = await self.db.execute(
                "SELECT value FROM channel_state WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            current = int(row["value"]) if row else 0
            logger.debug("slavic_photo_count_tick: current=%d", current)
            new_count = current + 1
            logger.debug("slavic_photo_count_tick: new_count=%d", new_count)
            if new_count >= interval:
                logger.debug("slavic_photo_count_tick: interval reached, resetting counter")
                await self.db.execute(
                    "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
                    (key, "0"),
                )
                await self.db.commit()
                return True
            else:
                logger.debug("slavic_photo_count_tick: incrementing counter to %d", new_count)
                await self.db.execute(
                    "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
                    (key, str(new_count)),
                )
                await self.db.commit()
                return False

    # ── Relay Album Map (Epic 14) ──────────────────────

    async def save_relay_album_map(self, message_id: int, media_group_id: str) -> None:
        """Save media_group_id for a relay channel message. Idempotent."""
        await self.db.execute(
            "INSERT OR REPLACE INTO relay_album_map (message_id, media_group_id) VALUES (?, ?)",
            (message_id, media_group_id),
        )
        await self.db.commit()

    async def get_relay_media_group_id(self, message_id: int) -> str | None:
        """Get media_group_id for a relay channel message. Returns None if not found."""
        cursor = await self.db.execute(
            "SELECT media_group_id FROM relay_album_map WHERE message_id = ?",
            (message_id,),
        )
        row = await cursor.fetchone()
        return row["media_group_id"] if row else None

    async def get_relay_album_message_ids(self, media_group_id: str) -> list[int]:
        """Get all message_ids belonging to the same media group, sorted ascending."""
        cursor = await self.db.execute(
            "SELECT message_id FROM relay_album_map WHERE media_group_id = ? ORDER BY message_id ASC",
            (media_group_id,),
        )
        rows = await cursor.fetchall()
        return [row["message_id"] for row in rows]
