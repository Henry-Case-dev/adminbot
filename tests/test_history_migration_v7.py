"""Фаза 2 (T-760, E3 + T-758/T-759) — миграция v7 и дата-рендер COALESCE.

(а) graph_facts rebuild: + message_timestamp (backfill = created_at), CHECK
origin += 'history_import'; id сохранены; graph_facts_fts валиден БЕЗ
пересоздания; повторный запуск no-op; user_version=7.
(б) smart_messages: import_key/history_processed (ALTER) + частичные индексы.
Вставка: insert_graph_fact(..., message_timestamp=…) проходит и пишет FTS;
рендер RAG: импортированный факт (message_timestamp = старая дата) рендерится
[старая дата], live-факт — как раньше (created_at).
"""
import asyncio
import sqlite3
import time

import aiosqlite
import pytest

from services.database import DatabaseService
from services.summary_memory import MemoryManager, build_rag_context


@pytest.fixture
def db():
    """In-memory БД (миграции v1..v7 применены initialize)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()

# Точная v6-схема (после раунда 5): 8 origins (без history_import), БЕЗ
# message_timestamp; smart_messages без import_key/history_processed.
_V6_GRAPH_FACTS_DDL = """CREATE TABLE graph_facts (
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

_V6_SMART_MESSAGES_DDL = """CREATE TABLE smart_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, chat_id INTEGER NOT NULL, text TEXT,
    reply_to_id INTEGER, timestamp INTEGER NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'text',
    author_name TEXT NOT NULL DEFAULT '',
    is_forward INTEGER NOT NULL DEFAULT 0,
    forward_source TEXT NOT NULL DEFAULT '',
    tg_message_id INTEGER
);"""

_V6_FTS_DDL = (
    "CREATE VIRTUAL TABLE graph_facts_fts USING fts5("
    "fact, content='graph_facts', content_rowid='id', tokenize='unicode61');"
    "CREATE VIRTUAL TABLE smart_messages_fts USING fts5("
    "text, content='smart_messages', content_rowid='id', tokenize='unicode61');"
)


def _create_v6_db(path):
    """v6-фикстура: факт с FTS-строкой + строки smart_messages, user_version=6."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_V6_GRAPH_FACTS_DDL + _V6_SMART_MESSAGES_DDL
                       + _V6_FTS_DDL)
    conn.execute(
        "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
        "created_at, target_user, weight, status, last_confirmed_at, "
        "supersedes) VALUES (7, -100, 'старый факт до v7', 'chat_history', "
        "NULL, 1700000000, 'вася', 0.7, 'confirmed', 1700000000, NULL)")
    conn.execute(
        "INSERT INTO graph_facts_fts(rowid, fact) VALUES (7, 'старый факт до v7')")
    conn.execute(
        "INSERT INTO smart_messages (id, user_id, chat_id, text, timestamp, "
        "author_name) VALUES (1, 111, -100, 'старое сообщение', 1700000000, "
        "'вася')")
    conn.execute(
        "INSERT INTO smart_messages_fts(rowid, text) "
        "VALUES (1, 'старое сообщение')")
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()


class TestMigrationV7:
    @pytest.mark.asyncio
    async def test_v6_db_migrates_preserving_rows_and_fts(self, tmp_path):
        path = tmp_path / "v6.db"
        _create_v6_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        # данные сохранены, id цел
        cursor = await d.db.execute(
            "SELECT id, fact, origin, message_timestamp, weight "
            "FROM graph_facts")
        row = await cursor.fetchone()
        assert row["id"] == 7
        assert row["fact"] == "старый факт до v7"
        assert row["origin"] == "chat_history"
        # backfill message_timestamp = created_at
        assert row["message_timestamp"] == 1700000000
        # CHECK расширен + колонка в схеме
        cursor = await d.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'")
        sql = (await cursor.fetchone())["sql"]
        assert "history_import" in sql
        assert "message_timestamp" in sql
        cursor = await d.db.execute("PRAGMA table_info(smart_messages)")
        cols = {r["name"] for r in await cursor.fetchall()}
        assert {"import_key", "history_processed"} <= cols
        # FTS валиден БЕЗ пересоздания (rowid 7 сохранён)
        rows = await d.search_graph_facts_fts(
            -100, '"старый"*', 5, 2_000_000_000)
        assert any(r["id"] == 7 and r["fact"] == "старый факт до v7"
                   for r in rows)
        # PRAGMA user_version = 7
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7
        # индексы v7 существуют
        cursor = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
            "('idx_graph_facts_history_import', 'idx_smart_messages_import_key', "
            "'idx_smart_messages_history_pending')")
        names = {r["name"] for r in await cursor.fetchall()}
        assert names == {"idx_graph_facts_history_import",
                         "idx_smart_messages_import_key",
                         "idx_smart_messages_history_pending"}
        # smart-строки целы
        cursor = await d.db.execute(
            "SELECT text FROM smart_messages WHERE id = 1")
        assert (await cursor.fetchone())["text"] == "старое сообщение"
        await d.close()

    @pytest.mark.asyncio
    async def test_reinitialize_v7_noop(self, tmp_path):
        path = tmp_path / "v6b.db"
        _create_v6_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        await d.close()
        await d.initialize()                        # «рестарт» — no-op
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1  # строки не задвоены
        await d.close()

    @pytest.mark.asyncio
    async def test_history_import_origin_and_unique_index(self, db):
        """INSERT origin='history_import' проходит (CHECK расширен); дубль
        (chat_id, fact, message_timestamp) отсекается частичным UNIQUE."""
        now = int(time.time())
        fid = await db.insert_graph_fact(
            -100, "в марте 2024 петя купил машину", "history_import", None,
            weight=0.3, message_timestamp=1_700_000_000)
        cursor = await db.db.execute(
            "SELECT origin, weight, expires_at, message_timestamp, status "
            "FROM graph_facts WHERE id = ?", (fid,))
        row = await cursor.fetchone()
        assert row["origin"] == "history_import"
        assert row["weight"] == 0.3
        assert row["expires_at"] is None
        assert row["message_timestamp"] == 1_700_000_000
        assert row["status"] == "confirmed"
        # FTS-строка записана внутри insert_graph_fact
        found = await db.search_graph_facts_fts(
            -100, '"машину"*', 5, now)
        assert any(r["id"] == fid for r in found)
        # дубль той же пачки → INSERT OR IGNORE-семантика индекса
        await db.db.execute(
            "INSERT OR IGNORE INTO graph_facts (chat_id, fact, origin, "
            "expires_at, created_at, weight, status, message_timestamp) "
            "VALUES (-100, 'в марте 2024 петя купил машину', 'history_import', "
            "NULL, ?, 0.3, 'confirmed', ?)",
            (now, 1_700_000_000))
        await db.db.commit()
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE origin='history_import'")
        assert (await cursor.fetchone())["c"] == 1
        # неизвестный origin отклоняется CHECK
        with pytest.raises(aiosqlite.IntegrityError):
            await db.db.execute(
                "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
                "VALUES (-100, 'x', 'alien_origin', 100)")

    @pytest.mark.asyncio
    async def test_live_insert_without_message_timestamp(self, db):
        """Live-вызов insert_graph_fact без message_timestamp — NULL (регресс
        поведения: рендер COALESCE → created_at)."""
        fid = await db.insert_graph_fact(
            -100, "живой факт", "chat_history", None)
        cursor = await db.db.execute(
            "SELECT message_timestamp FROM graph_facts WHERE id = ?", (fid,))
        assert (await cursor.fetchone())["message_timestamp"] is None

    @pytest.mark.asyncio
    async def test_import_key_duplicate_rejected(self, db):
        """smart_messages: дубль import_key не проходит (UNIQUE-индекс)."""
        import hashlib

        key = hashlib.sha256(b"1|2|text").hexdigest()[:32]
        await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
            "media_type, author_name, import_key) VALUES (2, -100, 'text', 1, "
            "'text', 'a', ?)", (key,))
        await db.db.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
                "media_type, author_name, import_key) VALUES (2, -100, 'text', 1, "
                "'text', 'a', ?)", (key,))
        # live-строки (import_key NULL) не затронуты
        await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, timestamp) "
            "VALUES (2, -100, 'live', 2)")
        await db.db.commit()
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages WHERE import_key = ?",
            (key,))
        assert (await cursor.fetchone())["c"] == 1


class _FakeLLM:
    """Мини-LLM для MemoryManager (без сети): embed недоступен — FTS-путь."""

    async def generate(self, messages):
        raise AssertionError("generate не должен вызываться")

    async def embed(self, texts):
        raise AssertionError("embed не должен вызываться")


class TestDateRenderCoalesce:
    @pytest.mark.asyncio
    async def test_imported_fact_renders_message_date(self, db):
        """Факт с message_timestamp (дата сообщения 2024-го) и created_at=сейчас
        рендерится в RAG-контексте с [2024-…]; live-факт — с created_at."""
        import datetime as _dt

        msg_ts = 1_715_731_200            # 2024-05-15 00:00:00 UTC
        await db.insert_graph_fact(
            -100, "петя купил машину в марте", "history_import", None,
            weight=0.3, message_timestamp=msg_ts)
        live_id = await db.insert_graph_fact(
            -100, "петя и вася чинили машину", "chat_history", None)
        cursor = await db.db.execute(
            "SELECT created_at FROM graph_facts WHERE id = ?", (live_id,))
        live_ts = (await cursor.fetchone())["created_at"]
        live_day = _dt.datetime.fromtimestamp(
            int(live_ts), _dt.timezone.utc).strftime("[%Y-%m-%d] ")
        memory = MemoryManager(db, _FakeLLM())
        memory._vec_available = False      # → FTS-ветка поиска
        ctx = await memory.get_rag_context(
            -100, "петя машина март", include_direct_reply=True)
        assert "[2024-05-15] " in ctx
        # live-факт рендерится с датой created_at (COALESCE после backfill v7)
        assert live_day in ctx

    @pytest.mark.asyncio
    async def test_knn_path_rows_carry_rag_ts(self, db):
        """search_graph_facts_fts отдаёт rag_ts=COALESCE; get_graph_fact_texts/
        get_graph_fact_records — message_timestamp в строках (источник троек)."""
        msg_ts = 1_715_731_200
        fid = await db.insert_graph_fact(
            -100, "петя купил машину в марте", "history_import", None,
            weight=0.3, message_timestamp=msg_ts)
        rows = await db.search_graph_facts_fts(-100, '"машину"*', 5,
                                               int(time.time()))
        row = next(r for r in rows if r["id"] == fid)
        assert row["message_timestamp"] == msg_ts
        assert row["rag_ts"] == msg_ts
        # get_graph_fact_texts: ts = message_timestamp (COALESCE в Python)
        (origin, fact, ts) = (await db.get_graph_fact_texts([fid]))[0]
        assert origin == "history_import"
        assert ts == msg_ts
        records = await db.get_graph_fact_records([fid])
        assert records[0]["message_timestamp"] == msg_ts

    @pytest.mark.asyncio
    async def test_build_rag_context_legacy_and_ts(self):
        """build_rag_context: 2-кортеж без даты — как раньше; 3-кортеж —
        дата из ts."""
        assert build_rag_context([("chat_history", "факт")]) == \
            "<context>\n  <user_gossip>факт</user_gossip>\n" \
            "  <bot_knowledge></bot_knowledge>\n</context>"
        ctx = build_rag_context(
            [("chat_history", "факт", 1_715_731_200)])
        assert "[2024-05-15] " in ctx
