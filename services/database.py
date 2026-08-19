import asyncio
import datetime
import logging
import time
import aiosqlite
from pathlib import Path

logger = logging.getLogger(__name__)

_BUSY_TIMEOUT_MS = 5000          # R46-8: «database is locked» → ждём до 5с
_SCHEMA_VERSION = 1              # PRAGMA user_version; 0 = до Epic 46 (R46-8)


def row_get(row, key, default=None):
    """Field accessor: if row has .get (dict) — row.get(key, default);
    otherwise row[key], falling back to default on KeyError/IndexError/TypeError."""
    if hasattr(row, "get"):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


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

        -- ── SmartModule: Summary (Epic 24) ─────────────────────────
        -- R1: сырьё всех сообщений чата (+author_name — резолв A8 на момент сохранения;
        -- Epic 28: is_forward/forward_source — forward-маркировка, R28-1)
        CREATE TABLE IF NOT EXISTS smart_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            chat_id         INTEGER NOT NULL,
            text            TEXT,
            reply_to_id     INTEGER,
            timestamp       INTEGER NOT NULL,
            media_type      TEXT NOT NULL DEFAULT 'text',
            author_name     TEXT NOT NULL DEFAULT '',
            is_forward      INTEGER NOT NULL DEFAULT 0,
            forward_source  TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_ts ON smart_messages(chat_id, timestamp);

        -- FTS5 над сырьём L1/L2 (встроенный, без расширений) — L2-RAG + фоллбек
        CREATE VIRTUAL TABLE IF NOT EXISTS smart_messages_fts USING fts5(
            text, content='smart_messages', content_rowid='id', tokenize='unicode61'
        );

        -- L3: архивные факты — обычная таблица (пишется ВСЕГДА при сжатии)
        CREATE TABLE IF NOT EXISTS smart_archive_facts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            fact      TEXT NOT NULL,
            timestamp INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_archive_facts_chat_ts ON smart_archive_facts(chat_id, timestamp);
        CREATE VIRTUAL TABLE IF NOT EXISTS smart_archive_facts_fts USING fts5(
            fact, content='smart_archive_facts', content_rowid='id', tokenize='unicode61'
        );

        -- L3: векторы создаются ЛЕНИВО из MemoryManager.initialize()
        -- (только если sqlite-vec загрузился; dim из конфига EMBEDDING_DIM)

        -- ── GraphRAG: граф знаний (Epic 26/46) ──────────────────
        CREATE TABLE IF NOT EXISTS nodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            entity_name TEXT NOT NULL,
            entity_type TEXT NOT NULL CHECK (entity_type IN ('user', 'topic', 'event', 'fact')),
            origin      TEXT NOT NULL DEFAULT 'chat_history',
            expires_at  INTEGER,
            UNIQUE (chat_id, entity_name)
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_chat_type ON nodes(chat_id, entity_type);

        CREATE TABLE IF NOT EXISTS edges (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER NOT NULL,
            source_id     INTEGER NOT NULL REFERENCES nodes(id),
            target_id     INTEGER NOT NULL REFERENCES nodes(id),
            relation_type TEXT NOT NULL,
            weight        INTEGER NOT NULL DEFAULT 1,
            last_updated  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            origin        TEXT NOT NULL DEFAULT 'chat_history',
            expires_at    INTEGER,
            UNIQUE (source_id, target_id, relation_type)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_chat_weight ON edges(chat_id, weight);

        -- GraphRAG v2 (Epic 46, Section 55.3): факты гибридного RAG
        -- (origin/expires_at — ТЗ R46-1; TTL-исключение — ленивое WHERE, D175)
        CREATE TABLE IF NOT EXISTS graph_facts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    INTEGER NOT NULL,
            fact       TEXT NOT NULL,
            origin     TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
                       ('chat_history', 'search_fact', 'youtube_content', 'web_content')),
            expires_at INTEGER,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin ON graph_facts(chat_id, origin);
        CREATE VIRTUAL TABLE IF NOT EXISTS graph_facts_fts USING fts5(
            fact, content='graph_facts', content_rowid='id', tokenize='unicode61'
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
        await self.db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        await self.db.executescript(self._SCHEMA_SQL)
        await self.db.commit()
        await self._migrate_graphrag_v2()

        # Migration: add timestamp column if missing (Dead Page V2)
        try:
            await self.db.execute("ALTER TABLE dead_page_posts ADD COLUMN timestamp INTEGER")
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # Epic 28 (R28-1): forward-marking columns for existing smart_messages tables
        try:
            await self.db.execute(
                "ALTER TABLE smart_messages ADD COLUMN is_forward INTEGER NOT NULL DEFAULT 0"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists
        try:
            await self.db.execute(
                "ALTER TABLE smart_messages ADD COLUMN forward_source TEXT NOT NULL DEFAULT ''"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # GraphRAG (Epic 26): log the actual FK pragma state (Q4).
        # FK constraints are declared as documentation only — we never enable
        # the pragma because it would change semantics of the existing connection.
        try:
            cursor = await self.db.execute("PRAGMA foreign_keys")
            row = await cursor.fetchone()
            logger.debug("PRAGMA foreign_keys = %s (declared as docs, not enforced — Q4)",
                         row[0] if row is not None else None)
        except Exception:
            logger.debug("PRAGMA foreign_keys check failed", exc_info=True)
    
    async def _migrate_graphrag_v2(self) -> None:
        """Идемпотентная миграция Epic 46 (55.3): origin/expires_at в nodes/edges,
        CHECK entity_type + 'fact' (пересоздание nodes с сохранением id),
        PRAGMA user_version = 1. Повторный запуск — no-op."""
        for table in ("nodes", "edges"):
            for sql in (
                f"ALTER TABLE {table} ADD COLUMN origin TEXT NOT NULL DEFAULT 'chat_history'",
                f"ALTER TABLE {table} ADD COLUMN expires_at INTEGER",
            ):
                try:
                    await self.db.execute(sql)
                    await self.db.commit()
                except aiosqlite.OperationalError:
                    pass                        # колонка уже есть
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='nodes'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "'fact'" not in row["sql"]:
            # SQLite не умеет ALTER CHECK — пересоздание с сохранением id (55.1 #4)
            await self.db.executescript(
                "ALTER TABLE nodes RENAME TO nodes_old; "
                "CREATE TABLE nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "chat_id INTEGER NOT NULL, entity_name TEXT NOT NULL, "
                "entity_type TEXT NOT NULL CHECK (entity_type IN "
                "('user','topic','event','fact')), "
                "origin TEXT NOT NULL DEFAULT 'chat_history', expires_at INTEGER, "
                "UNIQUE (chat_id, entity_name)); "
                "INSERT INTO nodes (id, chat_id, entity_name, entity_type, origin, expires_at) "
                "SELECT id, chat_id, entity_name, entity_type, 'chat_history', NULL "
                "FROM nodes_old; "
                "DROP TABLE nodes_old; "
                "CREATE INDEX IF NOT EXISTS idx_nodes_chat_type ON nodes(chat_id, entity_type);"
            )
            await self.db.commit()
        await self.db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        await self.db.commit()

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

    # ── SmartModule: Summary (Epic 24) ──────────────────

    async def save_smart_message(
        self,
        user_id: int,
        chat_id: int,
        text: str | None,
        reply_to_id: int | None,
        timestamp: int,
        media_type: str,
        author_name: str,
        is_forward: bool = False,
        forward_source: str = "",
    ) -> int:
        """Insert a chat message into smart_messages + FTS index. Returns the new row id."""
        cursor = await self.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name,
             int(is_forward), forward_source),
        )
        row_id = cursor.lastrowid
        if text:
            await self.db.execute(
                "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
                (row_id, text),
            )
        await self.db.commit()
        return row_id

    async def get_smart_window(self, chat_id: int, since_ts: int, limit: int) -> list:
        """L1: messages within the generation window (timestamp >= since_ts), ASC order."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source "
            "FROM smart_messages WHERE chat_id = ? AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (chat_id, since_ts, limit),
        )
        rows = await cursor.fetchall()
        rows.reverse()
        return rows

    async def get_smart_raw(self, chat_id: int, older_than_ts: int, limit: int) -> list:
        """L2/сжатие: messages older than the cutoff timestamp, ASC order."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source "
            "FROM smart_messages WHERE chat_id = ? AND timestamp < ? "
            "ORDER BY timestamp ASC LIMIT ?",
            (chat_id, older_than_ts, limit),
        )
        return await cursor.fetchall()

    async def delete_smart_messages_older_than(self, chat_id: int, cutoff_ts: int) -> int:
        """Delete messages (+ FTS rows) older than cutoff. Returns count of deleted rows."""
        await self.db.execute(
            "DELETE FROM smart_messages_fts WHERE rowid IN "
            "(SELECT id FROM smart_messages WHERE chat_id = ? AND timestamp < ? "
            "AND text IS NOT NULL AND text != '')",
            (chat_id, cutoff_ts),
        )
        cursor = await self.db.execute(
            "DELETE FROM smart_messages WHERE chat_id = ? AND timestamp < ?",
            (chat_id, cutoff_ts),
        )
        await self.db.commit()
        return cursor.rowcount

    async def delete_smart_messages_by_ids(self, chat_id: int, ids: list[int]) -> int:
        """Delete specific messages (+ FTS rows) of a chat. Returns count deleted."""
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        await self.db.execute(
            f"DELETE FROM smart_messages_fts WHERE rowid IN "
            f"(SELECT id FROM smart_messages WHERE chat_id = ? AND id IN ({placeholders}) "
            "AND text IS NOT NULL AND text != '')",
            [chat_id, *ids],
        )
        cursor = await self.db.execute(
            f"DELETE FROM smart_messages WHERE chat_id = ? AND id IN ({placeholders})",
            [chat_id, *ids],
        )
        await self.db.commit()
        return cursor.rowcount

    async def save_archive_fact(self, chat_id: int, fact: str, timestamp: int) -> int:
        """L3: save a compressed archive fact (+ FTS row). Returns the new fact id."""
        cursor = await self.db.execute(
            "INSERT INTO smart_archive_facts (chat_id, fact, timestamp) VALUES (?, ?, ?)",
            (chat_id, fact, timestamp),
        )
        fact_id = cursor.lastrowid
        await self.db.execute(
            "INSERT INTO smart_archive_facts_fts(rowid, fact) VALUES (?, ?)",
            (fact_id, fact),
        )
        await self.db.commit()
        return fact_id

    async def delete_archive_facts_older_than(self, chat_id: int, cutoff_ts: int) -> int:
        """Delete archive facts (+ FTS rows) older than cutoff. Returns count deleted."""
        await self.db.execute(
            "DELETE FROM smart_archive_facts_fts WHERE rowid IN "
            "(SELECT id FROM smart_archive_facts WHERE chat_id = ? AND timestamp < ?)",
            (chat_id, cutoff_ts),
        )
        cursor = await self.db.execute(
            "DELETE FROM smart_archive_facts WHERE chat_id = ? AND timestamp < ?",
            (chat_id, cutoff_ts),
        )
        await self.db.commit()
        return cursor.rowcount

    async def search_messages_fts(self, chat_id: int, match_query: str, limit: int) -> list:
        """L2-RAG / фоллбек: FTS5 search over raw messages, ordered by rank."""
        cursor = await self.db.execute(
            "SELECT m.id, m.user_id, m.chat_id, m.text, m.reply_to_id, m.timestamp, "
            "m.media_type, m.author_name, m.is_forward, m.forward_source "
            "FROM smart_messages_fts JOIN smart_messages m ON m.id = smart_messages_fts.rowid "
            "WHERE smart_messages_fts MATCH ? AND m.chat_id = ? "
            "ORDER BY smart_messages_fts.rank LIMIT ?",
            (match_query, chat_id, limit),
        )
        return await cursor.fetchall()

    async def search_archive_fts(self, chat_id: int, match_query: str, limit: int) -> list[str]:
        """L3 фоллбек: FTS5 search over archive facts, ordered by rank."""
        cursor = await self.db.execute(
            "SELECT f.fact FROM smart_archive_facts_fts "
            "JOIN smart_archive_facts f ON f.id = smart_archive_facts_fts.rowid "
            "WHERE smart_archive_facts_fts MATCH ? AND f.chat_id = ? "
            "ORDER BY smart_archive_facts_fts.rank LIMIT ?",
            (match_query, chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [row["fact"] for row in rows]

    async def get_smart_chat_ids(self) -> list[int]:
        """Distinct chat ids that have at least one saved message."""
        cursor = await self.db.execute("SELECT DISTINCT chat_id FROM smart_messages")
        rows = await cursor.fetchall()
        return [row["chat_id"] for row in rows]

    # ── GraphRAG: nodes/edges (Epic 26, Section 35.2) ───────

    async def upsert_node(self, chat_id: int, entity_name: str, entity_type: str,
                          origin: str = "chat_history", expires_at=None) -> int:
        """INSERT OR IGNORE (ключ chat_id+entity_name): существующий узел сохраняет
        СВОЙ тип/origin (не перезаписывается); новые получают origin/expires_at."""
        await self.db.execute(
            "INSERT OR IGNORE INTO nodes (chat_id, entity_name, entity_type, origin, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, entity_name, entity_type, origin, expires_at),
        )
        cursor = await self.db.execute(
            "SELECT id FROM nodes WHERE chat_id = ? AND entity_name = ?",
            (chat_id, entity_name),
        )
        row = await cursor.fetchone()
        await self.db.commit()
        return row["id"]

    async def upsert_edge(
        self,
        source_id: int,
        target_id: int,
        relation_type: str,
        weight_increment: int = 1,
        origin: str = "chat_history",
        expires_at=None,
    ) -> None:
        """Merge a graph edge; duplicate (source,target,relation) bumps weight (D70).

        chat_id is taken from the source node (both nodes always belong to the
        same chat by construction). One statement → atomic. Epic 46 (55.3):
        origin/expires_at записываются.
        """
        await self.db.execute(
            "INSERT INTO edges (chat_id, source_id, target_id, relation_type, weight, "
            "origin, expires_at) "
            "SELECT chat_id, ?, ?, ?, ?, ?, ? FROM nodes WHERE id = ? "
            "ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET "
            "weight = weight + excluded.weight, last_updated = CURRENT_TIMESTAMP",
            (source_id, target_id, relation_type, weight_increment, origin, expires_at, source_id),
        )
        await self.db.commit()

    async def match_nodes(
        self, chat_id: int, user_names: list[str], topic_keywords: list[str]
    ) -> list[int]:
        """Node ids matched by exact user names or topic substring LIKE (35.5)."""
        conditions = []
        params: list = []
        if user_names:
            placeholders = ",".join("?" for _ in user_names)
            conditions.append(f"(entity_type = 'user' AND entity_name IN ({placeholders}))")
            params.extend(user_names)
        if topic_keywords:
            like_clauses = " OR ".join("entity_name LIKE ?" for _ in topic_keywords)
            conditions.append(f"(entity_type = 'topic' AND ({like_clauses}))")
            params.extend(f"%{kw}%" for kw in topic_keywords)
        if not conditions:
            return []
        sql = "SELECT id FROM nodes WHERE chat_id = ? AND (" + " OR ".join(conditions) + ")"
        cursor = await self.db.execute(sql, [chat_id, *params])
        rows = await cursor.fetchall()
        return [row["id"] for row in rows]

    async def get_top_edges(self, chat_id: int, entity_ids: list[int], limit: int) -> list:
        """Top edges incident to any of entity_ids, weight DESC (35.5)."""
        if not entity_ids:
            return []
        placeholders = ",".join("?" for _ in entity_ids)
        cursor = await self.db.execute(
            "SELECT e.id, e.chat_id, e.source_id, e.target_id, e.relation_type, "
            "e.weight, e.last_updated, "
            "s.entity_name AS source_name, s.entity_type AS source_type, "
            "t.entity_name AS target_name, t.entity_type AS target_type "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            f"WHERE e.chat_id = ? AND (e.source_id IN ({placeholders}) "
            f"OR e.target_id IN ({placeholders})) "
            "ORDER BY e.weight DESC, e.last_updated DESC, e.id DESC "
            "LIMIT ?",
            [chat_id, *entity_ids, *entity_ids, limit],
        )
        return await cursor.fetchall()

    async def get_top_edges_all(self, chat_id: int, limit: int) -> list:
        """Chat-wide top edges, weight DESC (cold-graph fallback, 35.5)."""
        cursor = await self.db.execute(
            "SELECT e.id, e.chat_id, e.source_id, e.target_id, e.relation_type, "
            "e.weight, e.last_updated, "
            "s.entity_name AS source_name, s.entity_type AS source_type, "
            "t.entity_name AS target_name, t.entity_type AS target_type "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            "WHERE e.chat_id = ? "
            "ORDER BY e.weight DESC, e.last_updated DESC, e.id DESC "
            "LIMIT ?",
            (chat_id, limit),
        )
        return await cursor.fetchall()

    # ── GraphRAG v2 (Epic 46, Section 55.3): graph_facts ─────────

    async def insert_graph_fact(self, chat_id, fact, origin, expires_at) -> int:
        """Факт-строка (+FTS-индекс). Возвращает id."""
        cursor = await self.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, fact, origin, expires_at, int(time.time())))
        fact_id = cursor.lastrowid
        await self.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)", (fact_id, fact))
        await self.db.commit()
        return fact_id

    async def search_graph_facts_fts(self, chat_id, match_query, limit, now_ts) -> list:
        """FTS-фолбек RAG с ленивым TTL-фильтром (D175)."""
        cursor = await self.db.execute(
            "SELECT f.id, f.fact, f.origin FROM graph_facts_fts "
            "JOIN graph_facts f ON f.id = graph_facts_fts.rowid "
            "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
            "AND (f.expires_at IS NULL OR f.expires_at > ?) "
            "ORDER BY graph_facts_fts.rank LIMIT ?",
            (match_query, chat_id, now_ts, limit))
        return await cursor.fetchall()

    async def get_graph_fact_texts(self, fact_ids) -> list:
        """[(origin, fact), ...] в порядке fact_ids (порядок KNN сохраняется)."""
        if not fact_ids:
            return []
        placeholders = ",".join("?" for _ in fact_ids)
        cursor = await self.db.execute(
            f"SELECT id, fact, origin FROM graph_facts WHERE id IN ({placeholders})",
            fact_ids)
        by_id = {row["id"]: (row["origin"], row["fact"]) for row in await cursor.fetchall()}
        return [by_id[fid] for fid in fact_ids if fid in by_id]

    async def purge_expired_graph_facts(self, chat_id) -> int:
        """Опциональный purge (D175, 55.1 #5): edges истёкших узлов → edges с
        истёкшим expires_at → истёкшие nodes → истёкшие graph_facts (+FTS)."""
        now = int(time.time())
        for side in ("source_id", "target_id"):
            await self.db.execute(
                f"DELETE FROM edges WHERE id IN ("
                f"SELECT e.id FROM edges e JOIN nodes n ON n.id = e.{side} "
                "WHERE n.expires_at IS NOT NULL AND n.expires_at <= ?)", (now,))
        await self.db.execute(
            "DELETE FROM edges WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        await self.db.execute(
            "DELETE FROM nodes WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        await self.db.execute(
            "DELETE FROM graph_facts_fts WHERE rowid IN "
            "(SELECT id FROM graph_facts WHERE expires_at IS NOT NULL AND expires_at <= ?)",
            (now,))
        cursor = await self.db.execute(
            "DELETE FROM graph_facts WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        await self.db.commit()
        return cursor.rowcount
