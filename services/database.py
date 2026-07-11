import asyncio
import datetime
import time
import aiosqlite
from pathlib import Path


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
