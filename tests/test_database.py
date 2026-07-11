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
