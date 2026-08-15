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
