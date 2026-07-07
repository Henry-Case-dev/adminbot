import asyncio
import datetime
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
    async def test_has_post_today(self, db):
        today = datetime.date.today().isoformat()
        chat_id = -100123
        
        assert await db.has_post_today(chat_id, "morning") is False
        
        await db.record_post(chat_id, "morning")
        assert await db.has_post_today(chat_id, "morning") is True
        assert await db.has_post_today(chat_id, "evening") is False

    @pytest.mark.asyncio
    async def test_separate_chats_posts(self, db):
        await db.record_post(-1001, "morning")
        await db.record_post(-1002, "evening")
        
        assert await db.has_post_today(-1001, "morning") is True
        assert await db.has_post_today(-1001, "evening") is False
        assert await db.has_post_today(-1002, "morning") is False
        assert await db.has_post_today(-1002, "evening") is True
