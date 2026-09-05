import asyncio
import datetime
import time
import pytest
from services.database import DatabaseService


@pytest.fixture
def db():
    """In-memory database for testing."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class TestDatabaseService:
    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, db):
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] async for row in cursor]
        assert "user_presence" in tables
        assert "message_counters" in tables
        assert "dead_page_posts" in tables
        assert "channel_state" in tables

    @pytest.mark.asyncio
    async def test_set_and_check_presence(self, db):
        await db.set_presence(479167456, -100123, True)
        assert await db.is_present(479167456, -100123) is True
        
        await db.set_presence(479167456, -100123, False)
        assert await db.is_present(479167456, -100123) is False

    @pytest.mark.asyncio
    async def test_default_presence_not_found(self, db):
        assert await db.is_present(479167456, -99999) is False

    @pytest.mark.asyncio
    async def test_get_present_chats(self, db):
        await db.set_presence(479167456, -1001, True)
        await db.set_presence(479167456, -1002, True)
        await db.set_presence(479167456, -1003, False)
        
        chats = await db.get_present_chats(479167456)
        assert sorted(chats) == [-1002, -1001]

    @pytest.mark.asyncio
    async def test_increment_count_new(self, db):
        count = await db.increment_and_get_count(-100123, 479167456)
        assert count == 1

    @pytest.mark.asyncio
    async def test_increment_count_existing(self, db):
        await db.increment_and_get_count(-100123, 479167456)
        await db.increment_and_get_count(-100123, 479167456)
        count = await db.increment_and_get_count(-100123, 479167456)
        assert count == 3

    @pytest.mark.asyncio
    async def test_get_count(self, db):
        await db.increment_and_get_count(-100123, 479167456)
        await db.increment_and_get_count(-100123, 479167456)
        assert await db.get_count(-100123, 479167456) == 2

    @pytest.mark.asyncio
    async def test_get_count_nonexistent(self, db):
        assert await db.get_count(-100123, 99999) == 0

    @pytest.mark.asyncio
    async def test_separate_chat_counters(self, db):
        await db.increment_and_get_count(-1001, 479167456)
        await db.increment_and_get_count(-1002, 479167456)
        
        assert await db.get_count(-1001, 479167456) == 1
        assert await db.get_count(-1002, 479167456) == 1

    @pytest.mark.asyncio
    async def test_was_dead_page_recently(self, db):
        """was_dead_page_recently returns True for posts within cooldown."""
        chat_id = -100123
        assert not await db.was_dead_page_recently(chat_id, 3600)
        await db.record_dead_page_post(chat_id, "repost")
        assert await db.was_dead_page_recently(chat_id, 3600)

    @pytest.mark.asyncio
    async def test_record_dead_page_post_separate_chats(self, db):
        """Posts in different chats are independent."""
        chat_1 = -100123
        chat_2 = -100456
        await db.record_dead_page_post(chat_1, "repost")
        assert await db.was_dead_page_recently(chat_1, 3600)
        assert not await db.was_dead_page_recently(chat_2, 3600)

    @pytest.mark.asyncio
    async def test_channel_state_get_set(self, db):
        """get_last_known_message_id and update_last_known_message_id roundtrip."""
        assert await db.get_last_known_message_id() is None
        await db.update_last_known_message_id(42)
        assert await db.get_last_known_message_id() == 42

    @pytest.mark.asyncio
    async def test_channel_state_scoped_by_channel(self, db):
        """Different channels have independent state."""
        await db.update_last_known_message_id(42, channel_id=100)
        await db.update_last_known_message_id(99, channel_id=200)
        assert await db.get_last_known_message_id(channel_id=100) == 42
        assert await db.get_last_known_message_id(channel_id=200) == 99

    # ── Dead Page Anti-Repeat (Epic 22 / D54) ────────────

    @pytest.mark.asyncio
    async def test_dead_page_last_sent_roundtrip(self, db):
        """set/get_dead_page_last_sent roundtrip."""
        assert await db.get_dead_page_last_sent(-100123) is None
        await db.set_dead_page_last_sent(-100123, 42)
        assert await db.get_dead_page_last_sent(-100123) == 42

    @pytest.mark.asyncio
    async def test_dead_page_last_sent_overwrite(self, db):
        """Repeated set overwrites the previous value."""
        await db.set_dead_page_last_sent(-100123, 3)
        await db.set_dead_page_last_sent(-100123, 7)
        assert await db.get_dead_page_last_sent(-100123) == 7

    @pytest.mark.asyncio
    async def test_dead_page_last_sent_per_chat_isolation(self, db):
        """Different chats have independent last-sent values."""
        await db.set_dead_page_last_sent(-1001, 3)
        await db.set_dead_page_last_sent(-1002, 7)
        assert await db.get_dead_page_last_sent(-1001) == 3
        assert await db.get_dead_page_last_sent(-1002) == 7

    @pytest.mark.asyncio
    async def test_dead_page_last_sent_corrupted_value(self, db):
        """Broken value in DB returns None gracefully."""
        await db.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            ("dead_page_last_sent:-100123", "not_a_number"),
        )
        await db.db.commit()
        assert await db.get_dead_page_last_sent(-100123) is None

    # ── Alan Activity (F7v2 / Epic 11) ──────────────────

    @pytest.mark.asyncio
    async def test_get_alan_last_message_ts_none(self, db):
        """When no record exists, return None."""
        assert await db.get_alan_last_message_ts(-100123) is None

    @pytest.mark.asyncio
    async def test_set_and_get_alan_last_message_ts(self, db):
        """Write and read back a timestamp."""
        await db.set_alan_last_message_ts(-100123, 1721000000.0)
        result = await db.get_alan_last_message_ts(-100123)
        assert result == 1721000000.0

    @pytest.mark.asyncio
    async def test_set_alan_last_message_ts_overwrite(self, db):
        """Overwrite an existing timestamp."""
        await db.set_alan_last_message_ts(-100123, 100.0)
        await db.set_alan_last_message_ts(-100123, 200.0)
        assert await db.get_alan_last_message_ts(-100123) == 200.0

    @pytest.mark.asyncio
    async def test_get_alan_last_message_ts_multiple_chats(self, db):
        """Different chats have independent timestamps."""
        await db.set_alan_last_message_ts(-1001, 100.0)
        await db.set_alan_last_message_ts(-1002, 200.0)
        assert await db.get_alan_last_message_ts(-1001) == 100.0
        assert await db.get_alan_last_message_ts(-1002) == 200.0

    @pytest.mark.asyncio
    async def test_get_alan_last_message_ts_corrupted_value(self, db):
        """Corrupted value in DB returns None gracefully."""
        import aiosqlite
        await db.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            ("alan_last_msg:-100123", "not_a_number")
        )
        await db.db.commit()
        assert await db.get_alan_last_message_ts(-100123) is None


# ── SmartModule: Summary (Epic 24) ─────────────────────

class TestSmartModuleDatabase:
    @pytest.mark.asyncio
    async def test_smart_tables_created(self, db):
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table') ORDER BY name"
        )
        names = [row["name"] async for row in cursor]
        assert "smart_messages" in names
        assert "smart_messages_fts" in names
        assert "smart_archive_facts" in names
        assert "smart_archive_facts_fts" in names

    @pytest.mark.asyncio
    async def test_save_and_window(self, db):
        await db.save_smart_message(1, -100, "первое", None, 100, "text", "вася")
        await db.save_smart_message(2, -100, "второе", None, 200, "text", "петя")
        rows = await db.get_smart_window(-100, 0, 10)
        assert [r["text"] for r in rows] == ["первое", "второе"]
        assert rows[0]["author_name"] == "вася"

    @pytest.mark.asyncio
    async def test_window_since_boundary(self, db):
        await db.save_smart_message(1, -100, "граница", None, 500, "text", "а")
        await db.save_smart_message(2, -100, "раньше", None, 499, "text", "б")
        rows = await db.get_smart_window(-100, 500, 10)
        assert [r["text"] for r in rows] == ["граница"]

    @pytest.mark.asyncio
    async def test_get_smart_raw_older_than(self, db):
        await db.save_smart_message(1, -100, "старое", None, 100, "text", "а")
        await db.save_smart_message(2, -100, "новое", None, 200, "text", "б")
        rows = await db.get_smart_raw(-100, 150, 10)
        assert [r["text"] for r in rows] == ["старое"]

    @pytest.mark.asyncio
    async def test_delete_older_than_removes_fts(self, db):
        await db.save_smart_message(1, -100, "старое", None, 100, "text", "а")
        await db.save_smart_message(2, -100, "новое", None, 200, "text", "б")
        deleted = await db.delete_smart_messages_older_than(-100, 150)
        assert deleted == 1
        rows = await db.search_messages_fts(-100, '"старое"', 10)
        assert rows == []
        rows = await db.get_smart_raw(-100, 9999, 10)
        assert [r["text"] for r in rows] == ["новое"]

    # ── T-206 (T26.7-C): медиа без подписи и FTS-консистентность удаления ──

    @pytest.mark.asyncio
    async def test_delete_by_ids_media_without_caption_no_fts_row(self, db):
        """Медиа без подписи (text=None) нет в FTS → удаление не падает, сырьё удаляется."""
        media_id = await db.save_smart_message(1, -100, None, None, 100, "photo", "вася")
        text_id = await db.save_smart_message(2, -100, "подпись", None, 200, "text", "петя")
        deleted = await db.delete_smart_messages_by_ids(-100, [media_id, text_id])
        assert deleted == 2
        assert await db.get_smart_raw(-100, 9999, 10) == []

    @pytest.mark.asyncio
    async def test_delete_by_ids_media_with_empty_caption(self, db):
        """Медиа с пустой подписью (text='') нет в FTS → удаление не падает."""
        media_id = await db.save_smart_message(1, -100, "", None, 100, "photo", "вася")
        deleted = await db.delete_smart_messages_by_ids(-100, [media_id])
        assert deleted == 1
        assert await db.get_smart_raw(-100, 9999, 10) == []

    @pytest.mark.asyncio
    async def test_delete_older_than_media_without_caption(self, db):
        """Медиа без подписи под cutoff не ломает FTS-DELETE; текстовые строки целы."""
        await db.save_smart_message(1, -100, None, None, 100, "photo", "вася")
        await db.save_smart_message(2, -100, "текст", None, 200, "text", "петя")
        deleted = await db.delete_smart_messages_older_than(-100, 150)
        assert deleted == 1
        rows = await db.get_smart_raw(-100, 9999, 10)
        assert [r["text"] for r in rows] == ["текст"]
        assert len(await db.search_messages_fts(-100, '"текст"', 10)) == 1

    @pytest.mark.asyncio
    async def test_delete_by_ids_removes_fts_rows(self, db):
        """Обычный текст: FTS-строки удаляются вместе с сырьём."""
        gone_id = await db.save_smart_message(1, -100, "удалим", None, 100, "text", "а")
        await db.save_smart_message(2, -100, "останется", None, 200, "text", "б")
        deleted = await db.delete_smart_messages_by_ids(-100, [gone_id])
        assert deleted == 1
        assert await db.search_messages_fts(-100, '"удалим"', 10) == []
        assert len(await db.search_messages_fts(-100, '"останется"', 10)) == 1

    @pytest.mark.asyncio
    async def test_delete_older_than_removes_fts_rows(self, db):
        """Обычный текст: FTS-строки удаляются вместе с сырьём (older_than)."""
        await db.save_smart_message(1, -100, "удалим", None, 100, "text", "а")
        await db.save_smart_message(2, -100, "останется", None, 200, "text", "б")
        deleted = await db.delete_smart_messages_older_than(-100, 150)
        assert deleted == 1
        assert await db.search_messages_fts(-100, '"удалим"', 10) == []
        assert len(await db.search_messages_fts(-100, '"останется"', 10)) == 1

    @pytest.mark.asyncio
    async def test_no_fts_orphans_after_delete(self, db):
        """FTS-консистентность: после удаления в FTS нет сирот (rowid без строки сырья)."""
        m1 = await db.save_smart_message(1, -100, "текст", None, 100, "text", "а")
        m2 = await db.save_smart_message(2, -100, None, None, 200, "photo", "б")
        m3 = await db.save_smart_message(3, -100, "", None, 300, "photo", "в")
        await db.delete_smart_messages_by_ids(-100, [m1, m2])
        await db.delete_smart_messages_older_than(-100, 9999)
        cursor = await db.db.execute(
            "SELECT rowid FROM smart_messages_fts "
            "WHERE rowid NOT IN (SELECT id FROM smart_messages)"
        )
        assert await cursor.fetchall() == []

    @pytest.mark.asyncio
    async def test_save_archive_fact_and_search(self, db):
        await db.save_archive_fact(-100, "факт номер один", 100)
        facts = await db.search_archive_fts(-100, '"факт"', 10)
        assert facts == ["факт номер один"]

    @pytest.mark.asyncio
    async def test_delete_archive_facts_older_than(self, db):
        await db.save_archive_fact(-100, "древний", 100)
        await db.save_archive_fact(-100, "свежий", 200)
        deleted = await db.delete_archive_facts_older_than(-100, 150)
        assert deleted == 1
        facts = await db.search_archive_fts(-100, '"свежий"', 10)
        assert facts == ["свежий"]

    @pytest.mark.asyncio
    async def test_search_messages_fts_chat_isolation(self, db):
        await db.save_smart_message(1, -100, "секрет", None, 100, "text", "а")
        await db.save_smart_message(2, -200, "секрет чужой", None, 100, "text", "б")
        rows = await db.search_messages_fts(-100, '"секрет"', 10)
        assert len(rows) == 1
        assert rows[0]["text"] == "секрет"

    # ── Bugfix 04.09.2026 (Часть 2, AC-3.6): FTS-count для query_chat_memory ──

    @pytest.mark.asyncio
    async def test_search_messages_fts_count_basic(self, db):
        await db.save_smart_message(1, -100, "бензин подорожал", None, 1000,
                                    "text", "вася")
        await db.save_smart_message(2, -100, "опять про бензин", None, 2000,
                                    "text", "петя")
        await db.save_smart_message(3, -100, "не про топливо", None, 3000,
                                    "text", "иван")
        stats = await db.search_messages_fts_count(-100, '"бензин"*')
        assert stats["count"] == 2
        assert stats["first_seen"] == 1000
        assert stats["last_seen"] == 2000

    @pytest.mark.asyncio
    async def test_search_messages_fts_count_since_window(self, db):
        await db.save_smart_message(1, -100, "бензин старый", None, 1000,
                                    "text", "вася")
        await db.save_smart_message(2, -100, "бензин свежий", None, 3000,
                                    "text", "петя")
        stats = await db.search_messages_fts_count(-100, '"бензин"*',
                                                   since_ts=2000)
        assert stats["count"] == 1
        assert stats["first_seen"] == 3000
        assert stats["last_seen"] == 3000

    @pytest.mark.asyncio
    async def test_search_messages_fts_count_no_matches(self, db):
        await db.save_smart_message(1, -100, "совсем другое", None, 1000,
                                    "text", "вася")
        stats = await db.search_messages_fts_count(-100, '"отсутствует"*')
        assert stats["count"] == 0
        assert stats["first_seen"] is None
        assert stats["last_seen"] is None

    @pytest.mark.asyncio
    async def test_search_messages_fts_count_chat_isolation(self, db):
        await db.save_smart_message(1, -100, "бензин тут", None, 1000,
                                    "text", "вася")
        await db.save_smart_message(2, -200, "бензин чужой", None, 2000,
                                    "text", "петя")
        stats = await db.search_messages_fts_count(-100, '"бензин"*')
        assert stats["count"] == 1


    @pytest.mark.asyncio
    async def test_get_smart_chat_ids(self, db):
        await db.save_smart_message(1, -100, "а", None, 1, "text", "х")
        await db.save_smart_message(2, -100, "б", None, 2, "text", "х")
        await db.save_smart_message(3, -200, "в", None, 3, "text", "х")
        assert sorted(await db.get_smart_chat_ids()) == [-200, -100]

    @pytest.mark.asyncio
    async def test_migration_on_existing_db(self, db):
        """Old tables exist alongside the new ones after migration."""
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] async for row in cursor]
        assert "user_presence" in tables  # legacy table
        assert "smart_messages" in tables


# ── Epic 28 (T-211): forward-marking columns ─────────────

class TestSmartModuleForward:
    @pytest.mark.asyncio
    async def test_forward_columns_exist_in_fresh_db(self, db):
        """CREATE-путь: новые колонки есть с дефолтами (0 / '')."""
        cursor = await db.db.execute("PRAGMA table_info(smart_messages)")
        cols = {row["name"] for row in await cursor.fetchall()}
        assert {"is_forward", "forward_source"} <= cols
        await db.save_smart_message(1, -100, "обычное", None, 100, "text", "вася")
        rows = await db.get_smart_window(-100, 0, 10)
        assert rows[0]["is_forward"] == 0
        assert rows[0]["forward_source"] == ""

    @pytest.mark.asyncio
    async def test_migration_alters_existing_old_table(self, tmp_path):
        """Старая smart_messages (без новых колонок) → initialize() → ALTER добавил."""
        import aiosqlite

        path = str(tmp_path / "migrate.db")
        raw = await aiosqlite.connect(path)
        await raw.execute(
            "CREATE TABLE smart_messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,"
            "chat_id INTEGER NOT NULL, text TEXT, reply_to_id INTEGER,"
            "timestamp INTEGER NOT NULL, media_type TEXT NOT NULL DEFAULT 'text',"
            "author_name TEXT NOT NULL DEFAULT '')"
        )
        await raw.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, media_type, author_name) "
            "VALUES (1, -100, 'старое', 100, 'text', 'вася')"
        )
        await raw.commit()
        await raw.close()

        d = DatabaseService(path)
        await d.initialize()
        cursor = await d.db.execute("PRAGMA table_info(smart_messages)")
        cols = {row["name"] for row in await cursor.fetchall()}
        assert {"is_forward", "forward_source"} <= cols
        rows = await d.get_smart_raw(-100, 9999, 10)
        assert rows[0]["text"] == "старое"
        assert rows[0]["is_forward"] == 0
        assert rows[0]["forward_source"] == ""
        await d.close()

    @pytest.mark.asyncio
    async def test_save_with_forward_kw(self, db):
        await db.save_smart_message(
            1, -100, "репост", None, 100, "text", "вася",
            is_forward=True, forward_source="Канал X",
        )
        rows = await db.get_smart_window(-100, 0, 10)
        assert rows[0]["is_forward"] == 1
        assert rows[0]["forward_source"] == "Канал X"

    @pytest.mark.asyncio
    async def test_selects_return_forward_fields(self, db):
        await db.save_smart_message(
            1, -100, "репост текст", None, 100, "text", "вася",
            is_forward=True, forward_source="Канал X",
        )
        window = await db.get_smart_window(-100, 0, 10)
        raw = await db.get_smart_raw(-100, 9999, 10)
        fts = await db.search_messages_fts(-100, '"репост"', 10)
        for row in (window[0], raw[0], fts[0]):
            assert row["is_forward"] == 1
            assert row["forward_source"] == "Канал X"


# ── Epic 60 (Section 63.3, T-460): миграция user_version 2→3 ────────

_V2_GRAPH_FACTS_DDL = """CREATE TABLE graph_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    fact       TEXT NOT NULL,
    origin     TEXT NOT NULL DEFAULT 'chat_history',
    expires_at INTEGER,
    created_at INTEGER NOT NULL,
    target_user TEXT
);"""

_V2_EDGES_DDL = """CREATE TABLE edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    source_id     INTEGER NOT NULL,
    target_id     INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    weight        INTEGER NOT NULL DEFAULT 1,
    last_updated  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    origin        TEXT NOT NULL DEFAULT 'chat_history',
    expires_at    INTEGER,
    UNIQUE (source_id, target_id, relation_type)
);"""


def _create_v2_db(path):
    """v2-фикстура (63.6 #2): пре-Epic-60 схема, user_version = 2."""
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.executescript(_V2_GRAPH_FACTS_DDL + _V2_EDGES_DDL)
    conn.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
        "VALUES (-100, 'старый факт', 'chat_history', 1700000000)")
    conn.execute(
        "INSERT INTO edges (chat_id, source_id, target_id, relation_type, last_updated) "
        "VALUES (-100, 1, 2, 'связь', '2024-01-01 00:00:00')")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()


class TestEpic60V3Migration:
    @pytest.mark.asyncio
    async def test_user_version_is_3_after_initialize(self, db):
        """63.6 #1 + раунды 3/4/5 + фаза 2: PRAGMA user_version == 7 (Epic 46
        → 1, Epic 50 → 2, Epic 60/63.3 → 3, видео-origins CHECK → 4, раунд 4:
        user_memory-origins CHECK → 5, раунд 5: protected_facts chat-level
        (user_name NULL) → 6, фаза 2: message_timestamp/history_import →
        7)."""
        cursor = await db.db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row[0] == 7

    @pytest.mark.asyncio
    async def test_v3_tables_created(self, db):
        """63.6 #2: все 8 таблиц v3 созданы на свежей БД."""
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] async for row in cursor}
        assert {"throttle_state", "bot_replies", "user_prefs",
                "embedding_cache", "chat_running_summary",
                "graph_fact_compressions", "protected_facts"} <= tables

    @pytest.mark.asyncio
    async def test_v2_db_migrates_columns_and_backfill(self, tmp_path):
        """v2-фикстура → initialize: weight/status/last_confirmed_at/supersedes/
        created_at добавлены, backfill применён, данные сохранены."""
        path = tmp_path / "v2.db"
        _create_v2_db(path)
        d = DatabaseService(str(path))
        await d.initialize()

        cursor = await d.db.execute("PRAGMA table_info(graph_facts)")
        cols = {r["name"] for r in await cursor.fetchall()}
        assert {"weight", "status", "last_confirmed_at", "supersedes"} <= cols

        cursor = await d.db.execute(
            "SELECT fact, weight, status, last_confirmed_at, supersedes "
            "FROM graph_facts")
        row = await cursor.fetchone()
        assert row["fact"] == "старый факт"        # данные сохранены
        assert row["weight"] == 0.5                # дефолт (66.1)
        assert row["status"] == "confirmed"        # дефолт (66.1/64.2)
        assert row["last_confirmed_at"] == 1700000000   # backfill = created_at
        assert row["supersedes"] is None

        cursor = await d.db.execute("PRAGMA table_info(edges)")
        cols = {r["name"] for r in await cursor.fetchall()}
        assert "created_at" in cols
        cursor = await d.db.execute("SELECT created_at FROM edges")
        row = await cursor.fetchone()
        assert row["created_at"] == 1704067200     # strftime('%s', '2024-01-01 00:00:00')

        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7     # каскад 3→7 (v5/v6/v7)
        await d.close()

    @pytest.mark.asyncio
    async def test_reinitialize_is_idempotent_stays_3(self, tmp_path):
        """63.6 #1/#4 + раунды 3-5 + фаза 2: повторный initialize — no-op
        (user_version остаётся 7, данные не задвоены)."""
        path = tmp_path / "reinit.db"
        _create_v2_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        await d.close()
        await d.initialize()                       # «рестарт»
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM throttle_state")
        assert (await cursor.fetchone())["c"] == 0
        await d.close()

    @pytest.mark.asyncio
    async def test_throttle_state_shape(self, db):
        """63.1: scope/chat_id/user_id — PK; burst_left NULL (cooldown-стиль);
        last_ts REAL NOT NULL."""
        cursor = await db.db.execute("PRAGMA table_info(throttle_state)")
        cols = {r["name"]: r for r in await cursor.fetchall()}
        assert set(cols) == {"scope", "chat_id", "user_id", "burst_left", "last_ts"}
        assert cols["last_ts"]["notnull"] == 1

    @pytest.mark.asyncio
    async def test_bot_replies_shape(self, db):
        """63.1: bot_replies — PK (chat_id, tg_message_id), text NOT NULL,
        last_used_at REAL NOT NULL."""
        cursor = await db.db.execute("PRAGMA table_info(bot_replies)")
        cols = {r["name"]: r for r in await cursor.fetchall()}
        assert set(cols) == {"chat_id", "tg_message_id", "text", "last_used_at"}
        assert cols["text"]["notnull"] == 1
        assert cols["last_used_at"]["notnull"] == 1

    @pytest.mark.asyncio
    async def test_synchronous_pragma_is_normal(self, db):
        """63.1 (T-459 тема 9): PRAGMA synchronous=NORMAL в initialize."""
        cursor = await db.db.execute("PRAGMA synchronous")
        row = await cursor.fetchone()
        assert row[0] in (1, "NORMAL")             # 1 = NORMAL


# ── Epic 60 (63.1): bot_replies — TTL+LRU в БД ─────────────────────

class TestBotRepliesTable:
    @pytest.mark.asyncio
    async def test_upsert_and_get_roundtrip(self, db):
        await db.upsert_bot_reply(-100, 42, "ответ", 1000.0)
        assert await db.get_bot_reply(-100, 42, 1001.0) == "ответ"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, db):
        assert await db.get_bot_reply(-100, 999, 1000.0) is None

    @pytest.mark.asyncio
    async def test_ttl_lazy_delete_on_read(self, db):
        await db.upsert_bot_reply(-100, 42, "ответ", 1000.0)
        assert await db.get_bot_reply(-100, 42, 1000.0 + 3600.5) is None
        assert await db.get_bot_reply(-100, 42, 1000.0 + 3600.5) is None
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM bot_replies WHERE chat_id = -100 AND tg_message_id = 42")
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_ttl_sweep_on_write(self, db):
        await db.upsert_bot_reply(-100, 1, "старое", 1000.0)
        await db.upsert_bot_reply(-100, 2, "свежее", 5000.0)   # sweep вычистит #1
        assert await db.get_bot_reply(-100, 1, 5001.0) is None
        assert await db.get_bot_reply(-100, 2, 5001.0) == "свежее"

    @pytest.mark.asyncio
    async def test_lru_cap_200(self, db):
        for i in range(300):
            await db.upsert_bot_reply(-100, i, f"ответ {i}", 1000.0 + i)
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM bot_replies")
        assert (await cursor.fetchone())["c"] == 200
        assert await db.get_bot_reply(-100, 0, 2000.0) is None      # старейшее вытеснено
        assert await db.get_bot_reply(-100, 299, 2000.0) == "ответ 299"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, db):
        await db.upsert_bot_reply(-100, 42, "версия 1", 1000.0)
        await db.upsert_bot_reply(-100, 42, "версия 2", 2000.0)
        assert await db.get_bot_reply(-100, 42, 2001.0) == "версия 2"

    @pytest.mark.asyncio
    async def test_chat_isolation(self, db):
        await db.upsert_bot_reply(-100, 42, "наш", 1000.0)
        assert await db.get_bot_reply(-200, 42, 1001.0) is None


# ── Раунд 8 (spec §3.G1/D3, T-800): bot_reply_parents — TTL+LRU ─────

class TestBotReplyParentsTable:
    """D3/T-800: parent-линк «бот-ответ → сообщение» — тот же паттерн
    TTL+LRU, что bot_replies; user_version остаётся 7 (NFR-4)."""

    @pytest.mark.asyncio
    async def test_shape(self, db):
        cursor = await db.db.execute("PRAGMA table_info(bot_reply_parents)")
        cols = {r["name"]: r for r in await cursor.fetchall()}
        assert set(cols) == {"chat_id", "tg_message_id",
                             "parent_tg_message_id", "last_used_at"}
        cursor = await db.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7     # v8 НЕ вводится

    @pytest.mark.asyncio
    async def test_set_and_get_roundtrip(self, db):
        await db.set_bot_reply_parent(-100, 42, 7, 1000.0)
        assert await db.get_bot_reply_parent(-100, 42, 1001.0) == 7

    @pytest.mark.asyncio
    async def test_set_none_is_noop(self, db):
        """edited-путь: parent=None — строка не создаётся и существующая
        НЕ перезаписывается NULL (D3)."""
        await db.set_bot_reply_parent(-100, 42, 7, 1000.0)
        await db.set_bot_reply_parent(-100, 42, None, 2000.0)
        assert await db.get_bot_reply_parent(-100, 42, 2001.0) == 7
        await db.set_bot_reply_parent(-100, 43, None, 2000.0)
        assert await db.get_bot_reply_parent(-100, 43, 2001.0) is None

    @pytest.mark.asyncio
    async def test_ttl_lazy_delete_on_read(self, db):
        await db.set_bot_reply_parent(-100, 42, 7, 1000.0)
        assert await db.get_bot_reply_parent(-100, 42, 1000.0 + 3600.5) is None
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM bot_reply_parents "
            "WHERE chat_id = -100 AND tg_message_id = 42")
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_lru_cap_and_sweep(self, db):
        for i in range(300):
            await db.set_bot_reply_parent(-100, i, i - 1, 1000.0 + i)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM bot_reply_parents")
        assert (await cursor.fetchone())["c"] == 200
        assert await db.get_bot_reply_parent(-100, 0, 2000.0) is None
        assert await db.get_bot_reply_parent(-100, 299, 2000.0) == 298


# ── Раунд 8 (spec §3.C2, T-793): активные участники ───────────────

class TestActiveParticipants:
    """C2/T-793: SQL-агрегат участников за период — user_id + MAX(author_name)
    + счётчик, порядок cnt DESC/uid ASC, cap."""

    @pytest.mark.asyncio
    async def test_aggregate_order_and_author(self, db):
        await db.save_smart_message(
            user_id=10, chat_id=-100, text="раз", reply_to_id=None,
            timestamp=100, media_type="text", author_name="вася", message_id=1)
        await db.save_smart_message(
            user_id=20, chat_id=-100, text="раз", reply_to_id=None,
            timestamp=101, media_type="text", author_name="петя", message_id=2)
        await db.save_smart_message(
            user_id=20, chat_id=-100, text="два", reply_to_id=None,
            timestamp=102, media_type="text", author_name="петя", message_id=3)
        await db.save_smart_message(
            user_id=20, chat_id=-100, text="три", reply_to_id=None,
            timestamp=103, media_type="text", author_name="петя пупкин",
            message_id=4)
        rows = await db.get_active_participants(-100, since_ts=50, cap=150)
        assert [(r["user_id"], r["author_name"], r["cnt"]) for r in rows] == \
            [(20, "петя пупкин", 3), (10, "вася", 1)]    # MAX(author_name)

    @pytest.mark.asyncio
    async def test_since_ts_filters_and_cap(self, db):
        await db.save_smart_message(
            user_id=10, chat_id=-100, text="старое", reply_to_id=None,
            timestamp=10, media_type="text", author_name="вася", message_id=1)
        for i, uid in enumerate((11, 12, 13), 1):
            await db.save_smart_message(
                user_id=uid, chat_id=-100, text="свежее", reply_to_id=None,
                timestamp=100 + i, media_type="text", author_name=f"имя{uid}",
                message_id=10 + i)
        rows = await db.get_active_participants(-100, since_ts=100, cap=2)
        assert [r["user_id"] for r in rows] == [11, 12]   # cap работает
        # user_id IS NULL (канал/аноним) в карту не попадает
        await db.save_smart_message(
            user_id=None, chat_id=-100, text="анонс", reply_to_id=None,
            timestamp=200, media_type="text", author_name="канал", message_id=99)
        rows = await db.get_active_participants(-100, since_ts=50, cap=150)
        assert 99 not in [r["user_id"] for r in rows]


# Раунд 3 (3.6/B7, T-693): CHECK graph_facts.origin — voice/video_transcript
# (пересоздание с сохранением id/весов, user_version 3→4, повтор — no-op).

_V3_GRAPH_FACTS_DDL = """CREATE TABLE graph_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    fact       TEXT NOT NULL,
    origin     TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
               ('chat_history', 'search_fact', 'youtube_content', 'web_content',
                'bot_direct_reply')),
    expires_at INTEGER,
    created_at INTEGER NOT NULL,
    target_user TEXT,
    weight REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'confirmed',
    last_confirmed_at INTEGER,
    supersedes INTEGER
);"""


def _create_v3_db(path):
    """v3-фикстура (раунд 3): пре-B7 схема graph_facts (без voice/video),
    user_version = 3, один факт с весом/статусом."""
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.executescript(_V3_GRAPH_FACTS_DDL)
    conn.execute(
        "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
        "created_at, target_user, weight, status, last_confirmed_at, supersedes) "
        "VALUES (7, -100, 'факт до миграции', 'chat_history', NULL, "
        "1700000000, 'вася', 0.7, 'confirmed', 1700000000, NULL)")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()


class TestVideoOriginsMigrationV4:
    """3.6/B7 (T-693, AC-B9): старая схема → v4 с сохранением id/весов;
    INSERT voice_transcript/video_transcript успешен; user_version=6 (каскад
    v4→v5 раунда 4, T-713 → v6 раунда 5, T-731); повторный запуск no-op;
    факт виден в get_rag_context."""

    @pytest.mark.asyncio
    async def test_v3_db_migrates_to_v4_preserving_rows(self, tmp_path):
        path = tmp_path / "v3.db"
        _create_v3_db(path)
        d = DatabaseService(str(path))
        await d.initialize()

        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7
        # schema содержит новые origins
        cursor = await d.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'")
        sql = (await cursor.fetchone())["sql"]
        assert "video_transcript" in sql
        assert "voice_transcript" in sql
        # данные сохранены (id 7, вес/статус целы)
        cursor = await d.db.execute(
            "SELECT id, fact, origin, weight, status FROM graph_facts")
        row = await cursor.fetchone()
        assert row["id"] == 7
        assert row["fact"] == "факт до миграции"
        assert row["weight"] == 0.7
        assert row["status"] == "confirmed"
        await d.close()

    @pytest.mark.asyncio
    async def test_v4_insert_voice_and_video_origins_ok(self, db):
        fact_id1 = await db.insert_graph_fact(
            -100, "кружок: вася говорил про борщ", "voice_transcript", None)
        fact_id2 = await db.insert_graph_fact(
            -100, "видео: в ролике показывают сервер", "video_transcript", None)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE origin IN "
            "('voice_transcript', 'video_transcript')")
        assert (await cursor.fetchone())["c"] == 2
        assert fact_id1 > 0 and fact_id2 > fact_id1

    @pytest.mark.asyncio
    async def test_v4_fact_reachable_via_fts_rag(self, db):
        """AC-B9: факт новых origins попадает в FTS-путь get_rag_context
        (search_graph_facts_fts — без origin-фильтра)."""
        await db.insert_graph_fact(
            -100, "ролик про дрессировку собаки породы шпиц",
            "video_transcript", None)
        rows = await db.search_graph_facts_fts(
            -100, '"шпиц"*', 5, int(time.time()))
        assert rows and rows[0]["origin"] == "video_transcript"

    @pytest.mark.asyncio
    async def test_reinitialize_v4_is_noop(self, tmp_path):
        path = tmp_path / "v4.db"
        _create_v3_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        await d.close()
        await d.initialize()                        # «рестарт» — no-op
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7    # каскад до v7 (раунды 4/5 + фаза 2)
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1  # данные не задвоены
        await d.close()


# ── Раунд 5 (T-731, spec 3.2.1/5.2.1, FR-C1): миграция v6 ────────────────
# protected_facts.user_name → nullable (чат-уровневые факты, user_name NULL) +
# частичный уникальный индекс idx_protected_facts_chat_level; повторный
# запуск — no-op; PRAGMA user_version = 6.

_V5_PROTECTED_FACTS_DDL = """CREATE TABLE protected_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    fact TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE (chat_id, user_name, fact)
);"""

_V5_GRAPH_FACTS_DDL = """CREATE TABLE graph_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
    fact TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
    ('chat_history', 'search_fact', 'youtube_content', 'web_content',
     'bot_direct_reply', 'voice_transcript', 'video_transcript',
     'user_memory')),
    expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT,
    weight REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'confirmed',
    last_confirmed_at INTEGER, supersedes INTEGER
);"""


def _create_v5_db(path):
    """v5-фикстура (раунд 5): пре-v6 схема — protected_facts с
    user_name TEXT NOT NULL + пер-юзерные строки; user_version = 5."""
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.executescript(_V5_GRAPH_FACTS_DDL + _V5_PROTECTED_FACTS_DDL)
    conn.execute(
        "INSERT INTO protected_facts (id, chat_id, user_name, fact, created_at) "
        "VALUES (11, -100, 'вася', 'день рождения 5 мая', 1.0), "
        "(12, -100, 'петя', 'аллергия на кошек', 2.0)")
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()


class TestChatProtectedFactsV6Migration:
    @pytest.mark.asyncio
    async def test_v5_db_migrates_preserving_rows_and_ids(self, tmp_path):
        path = tmp_path / "v5.db"
        _create_v5_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        # данные сохранены, id не изменились
        cursor = await d.db.execute(
            "SELECT id, chat_id, user_name, fact FROM protected_facts "
            "ORDER BY id")
        rows = await cursor.fetchall()
        assert [(r["id"], r["user_name"], r["fact"]) for r in rows] == [
            (11, "вася", "день рождения 5 мая"),
            (12, "петя", "аллергия на кошек"),
        ]
        # user_name — nullable (NOT NULL снят)
        cursor = await d.db.execute("PRAGMA table_info(protected_facts)")
        cols = {r["name"]: r for r in await cursor.fetchall()}
        assert cols["user_name"]["notnull"] == 0
        assert cols["fact"]["notnull"] == 1
        # UNIQUE (chat_id, user_name, fact) сохранён
        cursor = await d.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='protected_facts'")
        assert "UNIQUE (chat_id, user_name, fact)" in (await cursor.fetchone())["sql"]
        # частичный уникальный индекс существует
        cursor = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_protected_facts_chat_level'")
        assert (await cursor.fetchone()) is not None
        # PRAGMA user_version = 7 (каскад v5→v6→v7)
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7
        await d.close()

    @pytest.mark.asyncio
    async def test_chat_level_insert_allowed_and_unique(self, tmp_path):
        """user_name NULL принимается; дубль (chat_id, fact) падает на
        частичном индексе; INSERT OR IGNORE поглощает дубль."""
        import aiosqlite

        path = tmp_path / "v5b.db"
        _create_v5_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        await d.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, NULL, 'лор чата', 3.0)")
        await d.db.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await d.db.execute(
                "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
                "VALUES (-100, NULL, 'лор чата', 4.0)")
        # UNIQUE(chat_id, user_name, fact): тот же лор под ПЕР-юзерным именем — ок
        await d.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, 'вася', 'лор чата', 5.0)")
        await d.db.commit()
        # OR IGNORE: повторный chat-level инжект — строка не добавится
        res = await d.db.execute(
            "INSERT OR IGNORE INTO protected_facts "
            "(chat_id, user_name, fact, created_at) VALUES (-100, NULL, 'лор чата', 6.0)")
        assert res.rowcount == 0
        await d.db.commit()
        cursor = await d.db.execute(
            "SELECT COUNT(*) AS c FROM protected_facts WHERE chat_id = -100 "
            "AND user_name IS NULL AND fact = 'лор чата'")
        assert (await cursor.fetchone())["c"] == 1
        await d.close()

    @pytest.mark.asyncio
    async def test_v6_reinitialize_is_noop(self, tmp_path):
        path = tmp_path / "v5c.db"
        _create_v5_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        await d.close()
        await d.initialize()                        # «рестарт» — no-op
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM protected_facts")
        assert (await cursor.fetchone())["c"] == 2  # строки не задвоены
        await d.close()

    @pytest.mark.asyncio
    async def test_get_protected_facts_include_chat_level_matrix(self, tmp_path):
        """T-732 (spec 5.2.2): chat-level факты видны при ЛЮБОМ user_name,
        первыми; False — только свои user-факты; порядок ASC по датам."""
        path = tmp_path / "matrix.db"
        d = DatabaseService(str(path))
        await d.initialize()
        for user, fact, ts in (
            ("вася", "васин старый факт", 1.0),
            ("петя", "петин факт", 2.0),
            ("вася", "васин свежий факт", 3.0),
        ):
            await d.db.execute(
                "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
                "VALUES (?, ?, ?, ?)", (-100, user, fact, ts))
        await d.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, NULL, 'лор чата', 10.0)")
        await d.db.commit()
        # True: чат-лор при ЛЮБОМ юзере + только свои user-факты; лор первый
        both = await d.get_protected_facts(-100, "вася")
        assert both[0] == "лор чата"
        assert set(both[1:]) == {"васин старый факт", "васин свежий факт"}
        assert both[1:] == ["васин старый факт", "васин свежий факт"]  # ASC
        other = await d.get_protected_facts(-100, "петя")
        assert other == ["лор чата", "петин факт"]
        # False: только свои
        own_only = await d.get_protected_facts(-100, "вася",
                                               include_chat_level=False)
        assert own_only == ["васин старый факт", "васин свежий факт"]
        assert await d.get_protected_facts(-100, "петя",
                                           include_chat_level=False) == ["петин факт"]
        await d.close()


# ── Раунд 8 (spec §3.G1/E2/E4, T-804/T-806): уровни конспекта ──────────────

class TestSummaryLevelsTable:
    """E2/T-804: chat_summary_levels — аддитивная таблица (CREATE IF NOT
    EXISTS в _SCHEMA_SQL, user_version НЕ поднимается — NFR-4); UPSERT/чтение
    уровней; чтение L1 (chat_running_summary) без TTL-смерти (E4/T-806)."""

    @pytest.mark.asyncio
    async def test_round8_tables_created_and_version_stays_7(self, db):
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] async for r in cursor}
        assert {"bot_reply_parents", "chat_summary_levels"} <= tables
        cursor = await db.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7

    @pytest.mark.asyncio
    async def test_level_upsert_and_get_roundtrip(self, db):
        assert await db.get_summary_level(-100, 2) is None
        await db.upsert_summary_level(
            -100, 2, "широкий фон: спорили о дронах", 100.0, 300)
        row = await db.get_summary_level(-100, 2)
        assert row["summary"] == "широкий фон: спорили о дронах"
        assert row["msg_count_highwater"] == 300
        # перезапись уровня (новая сборка) — PK chat_id+level
        await db.upsert_summary_level(-100, 2, "новая версия L2", 200.0, 450)
        row = await db.get_summary_level(-100, 2)
        assert row["summary"] == "новая версия L2"
        assert row["msg_count_highwater"] == 450
        assert await db.get_summary_level(-200, 2) is None    # чужой чат

    @pytest.mark.asyncio
    async def test_levels_are_per_chat_per_level(self, db):
        await db.upsert_summary_level(-100, 1, "уровень один", 1.0, 10)
        await db.upsert_summary_level(-100, 2, "уровень два", 2.0, 20)
        await db.upsert_summary_level(-200, 2, "другой чат", 3.0, 30)
        assert (await db.get_summary_level(-100, 1))["summary"] == "уровень один"
        assert (await db.get_summary_level(-100, 2))["summary"] == "уровень два"
        assert (await db.get_summary_level(-200, 2))["summary"] == "другой чат"
        assert await db.get_summary_level(-100, 3) is None

    @pytest.mark.asyncio
    async def test_expired_running_summary_stays_visible_e4(self, db):
        """E4/T-806: get_running_summary возвращает строку при ЛЮБОМ
        expires_at и НЕ удаляет её (ленивый TTL-DELETE убран) — тихий чат
        держит конспект в контексте до пересборки по заполнению."""
        await db.upsert_running_summary(-100, "старый конспект", 100, 200, 50,
                                        300.0, 350.0)
        row = await db.get_running_summary(-100, 400.0)   # expires_at прошёл
        assert row is not None
        assert row["summary"] == "старый конспект"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM chat_running_summary WHERE chat_id = ?",
            (-100,))
        assert (await cursor.fetchone())["c"] == 1         # строка жива
        assert await db.get_running_summary(-200, 400.0) is None


# ── Раунд 8 (spec §3.E3, T-805): purge/quota-гейты защищённого множества ──

class _PurgeSeedMixin:
    NOW = 1_800_000_000

    def _old(self, days):
        return self.NOW - int(days * 86400)

    async def _insert_fact(self, db, fact, *, weight=0.5, expires_at,
                           confirmed_at=None):
        """Прямой INSERT факта чата -100 (вес/expires/last_confirmed_at
        задаются явно — insert_graph_fact рождает подтверждение «сейчас»)."""
        cursor = await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, expires_at, "
            "created_at, target_user, status, supersedes, weight, "
            "last_confirmed_at, message_timestamp) "
            "VALUES (-100, ?, 'bot_direct_reply', ?, ?, 'вася', "
            "'confirmed', NULL, ?, ?, NULL)",
            (fact, expires_at, self.NOW, weight,
             self.NOW if confirmed_at is None else confirmed_at))
        fid = cursor.lastrowid
        await db.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
            (fid, fact))
        await db.db.commit()
        return fid

    async def _live_ids(self, db, ids):
        return [t[1] for t in await db.get_graph_fact_texts(ids)]


class TestGraphPurgeProtectE3(_PurgeSeedMixin):
    """E3/T-805 (spec §3.E3.2): TTL-purge НЕ удаляет истёкший факт, если он
    высоковесный (weight >= 0.8) ИЛИ недавно подтверждён (last_confirmed_at
    свежее 3 дней) ИЛИ текст совпадает с protected_facts; вечные
    (expires_at NULL) не кандидаты; слабые протухшие удаляются; границы
    порогов фиксируются."""

    @pytest.mark.asyncio
    async def test_purge_keeps_protected_set_and_deletes_weak(self, db, monkeypatch):
        monkeypatch.setattr("services.database.time.time", lambda: self.NOW)
        weak = await self._insert_fact(db, "слабый протухший",
                                       expires_at=self._old(10),
                                       confirmed_at=self._old(10))
        heavy = await self._insert_fact(db, "тяжёлый протухший",
                                        weight=1.0, expires_at=self._old(10))
        confirmed = await self._insert_fact(db, "недавно подтверждённый",
                                            expires_at=self._old(10),
                                            confirmed_at=self._old(2))
        eternal = await self._insert_fact(db, "вечный", expires_at=None)
        as_protected = await self._insert_fact(
            db, "текст из protected", expires_at=self._old(10),
            confirmed_at=self._old(10))
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, 'вася', 'текст из protected', 1.0)")
        await db.db.commit()
        deleted = await db.purge_expired_graph_facts(-100)
        assert deleted == 1                       # только слабый протухший
        assert set(await self._live_ids(
            db, [weak, heavy, confirmed, eternal, as_protected])) == {
            "тяжёлый протухший", "недавно подтверждённый", "вечный",
            "текст из protected"}

    @pytest.mark.asyncio
    async def test_purge_weight_boundary_079_kept_080(self, db, monkeypatch):
        monkeypatch.setattr("services.database.time.time", lambda: self.NOW)
        below = await self._insert_fact(db, "вес 0.79", weight=0.79,
                                        expires_at=self._old(10),
                                        confirmed_at=self._old(10))
        at = await self._insert_fact(db, "вес 0.8", weight=0.8,
                                     expires_at=self._old(10),
                                     confirmed_at=self._old(10))
        assert await db.purge_expired_graph_facts(-100) == 1
        assert await self._live_ids(db, [below, at]) == ["вес 0.8"]

    @pytest.mark.asyncio
    async def test_purge_confirm_boundary_3_days(self, db, monkeypatch):
        monkeypatch.setattr("services.database.time.time", lambda: self.NOW)
        fresh = await self._insert_fact(db, "подтверждён 2 дня назад",
                                        expires_at=self._old(10),
                                        confirmed_at=self._old(2))
        stale = await self._insert_fact(db, "подтверждён 4 дня назад",
                                        expires_at=self._old(10),
                                        confirmed_at=self._old(4))
        edge = await self._insert_fact(db, "подтверждён ровно 3 дня назад",
                                       expires_at=self._old(10),
                                       confirmed_at=self._old(3))
        assert await db.purge_expired_graph_facts(-100) == 1
        assert set(await self._live_ids(db, [fresh, stale, edge])) == {
            "подтверждён 2 дня назад", "подтверждён ровно 3 дня назад"}

    @pytest.mark.asyncio
    async def test_global_purge_respects_chat_scope(self, db, monkeypatch):
        monkeypatch.setattr("services.database.time.time", lambda: self.NOW)
        cursor = await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, expires_at, "
            "created_at, target_user, status, supersedes, weight, "
            "last_confirmed_at, message_timestamp) "
            "VALUES (-777, 'чужой слабый факт', 'bot_direct_reply', ?, ?, "
            "'петя', 'confirmed', NULL, 0.5, ?, NULL)",
            (self._old(10), self.NOW, self._old(10)))
        fid = cursor.lastrowid
        await db.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
            (fid, "чужой слабый факт"))
        await db.db.commit()
        deleted = await db.purge_expired_graph_facts()    # глобальный проход
        assert deleted == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE chat_id = -777")
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_protected_facts_table_survives_all_purge_paths(self, db):
        """E3.1-инвариант: protected_facts (отдельная таблица) не удаляется
        ни одним purge/eviction путём db-слоя."""
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, 'вася', 'защищённый факт', 1.0)")
        await db.db.commit()
        old = int(time.time()) - 100 * 86400
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, expires_at, "
            "created_at, target_user, status, supersedes, weight, "
            "last_confirmed_at) VALUES (-100, 'живой', 'chat_history', NULL, "
            "?, 'вася', 'confirmed', NULL, 0.5, ?)", (old, old))
        await db.db.commit()
        await db.purge_expired_graph_facts(-100)
        await db.purge_unconfirmed_graph_facts(int(time.time()), 1)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM protected_facts WHERE chat_id = -100")
        assert (await cursor.fetchone())["c"] == 1


class TestQuotaVictimProtectE3(_PurgeSeedMixin):
    """E3/T-805: get_quota_victim не выбирает жертву из защищённого
    множества (вес >= 0.8 / свежее подтверждение) — расширение
    существующего исключения protected_facts."""

    @pytest.mark.asyncio
    async def test_victim_skips_high_weight(self, db):
        now = int(time.time())
        for i, (fact, weight) in enumerate((("самый лёгкий", 0.3),
                                            ("средний", 0.5),
                                            ("тяжёлый", 1.0))):
            await db.insert_graph_fact(-100, fact, "bot_direct_reply",
                                       now + 86400, target_user="вася",
                                       weight=weight)
            await db.db.execute(
                "UPDATE graph_facts SET last_confirmed_at = ? WHERE fact = ?",
                (now - 30 * 86400, fact))
        await db.db.commit()
        victim = await db.get_quota_victim(-100, "вася", 3, now)
        assert victim is not None
        assert victim["fact"] == "самый лёгкий"     # тяжёлый (1.0) не жертва

    @pytest.mark.asyncio
    async def test_victim_skips_recently_confirmed(self, db):
        now = int(time.time())
        for i, (fact, weight) in enumerate((("старый лёгкий", 0.3),
                                            ("свежеподтверждённый", 0.3),
                                            ("ещё один", 0.5))):
            await db.insert_graph_fact(-100, fact, "bot_direct_reply",
                                       now + 86400, target_user="вася",
                                       weight=weight)
        # «свежеподтверждённый» — дедуп-hit вчера (защита 3 дня)
        await db.db.execute(
            "UPDATE graph_facts SET last_confirmed_at = ? "
            "WHERE fact = 'свежеподтверждённый'", (now - 86400,))
        await db.db.execute(
            "UPDATE graph_facts SET last_confirmed_at = ? "
            "WHERE fact IN ('старый лёгкий', 'ещё один')",
            (now - 30 * 86400,))
        await db.db.commit()
        victim = await db.get_quota_victim(-100, "вася", 3, now)
        assert victim["fact"] == "старый лёгкий"    # свежий не жертва

    @pytest.mark.asyncio
    async def test_victim_none_when_all_protected(self, db):
        now = int(time.time())
        for fact in ("а", "б", "в"):
            await db.insert_graph_fact(-100, fact, "bot_direct_reply",
                                       now + 86400, target_user="вася",
                                       weight=1.0)
        await db.db.commit()
        # квота превышена (3 >= 3), но все кандидаты защищены → None
        assert await db.get_quota_victim(-100, "вася", 3, now) is None
