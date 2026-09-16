"""Раунд 10.14 (F1 anti-echo-self-reply, ADR-1014-2 D2/D6/D7) — SQLite v9.

Покрытие:
  * v8 → v9: rebuild graph_facts с сохранением ВСЕХ 16 колонок и id 1:1,
    CHECK += 'bot_self_reply', user_version=9, FTS-хит по id, vec-rowid
    остаётся валидным (таблица НЕ пересоздаётся);
  * from scratch: свежая БД → v9, 16 колонок, origin в CHECK;
  * повторный прогон — no-op (строки не задвоены);
  * origin-исключения self: list_new_confirmed_facts / search_golden_facts_fts /
    get_live_graph_facts / find_exact_dup_groups / graph_stats;
  * RAG: FTS include_self=False (default) прячет self, True — показывает;
    _filter_vec_rows — та же семантика на vec-пути.
"""
import asyncio
import sqlite3
import time

import pytest

from services.database import DatabaseService
from services.summary_memory import MemoryManager

# Полная v8-схема (16 колонок) — тот же CHECK origin, что ставила v8-миграция.
_V8_DDL = """CREATE TABLE graph_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
    fact TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
    ('chat_history', 'search_fact', 'youtube_content', 'web_content',
     'bot_direct_reply', 'voice_transcript', 'video_transcript', 'user_memory',
     'history_import', 'derived_belief')),
    expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT,
    weight REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'confirmed',
    last_confirmed_at INTEGER, supersedes INTEGER,
    message_timestamp INTEGER, importance INTEGER NOT NULL DEFAULT 0,
    source_ids TEXT, kind TEXT NOT NULL DEFAULT 'fact'
    CHECK (kind IN ('fact','belief')), belief_meta TEXT);
CREATE VIRTUAL TABLE graph_facts_fts USING fts5(
    fact, content='graph_facts', content_rowid='id', tokenize='unicode61');
CREATE INDEX idx_graph_facts_chat_origin ON graph_facts(chat_id, origin);
CREATE INDEX idx_graph_facts_target_user ON graph_facts(chat_id, target_user);
CREATE UNIQUE INDEX idx_graph_facts_history_import
    ON graph_facts(chat_id, fact, message_timestamp)
    WHERE origin='history_import' AND message_timestamp IS NOT NULL;
CREATE INDEX idx_graph_facts_chat_kind ON graph_facts(chat_id, kind);
CREATE INDEX idx_graph_facts_beliefs ON graph_facts(chat_id) WHERE kind='belief';
"""

_ALL_COLS = ("id", "chat_id", "fact", "origin", "expires_at", "created_at",
             "target_user", "weight", "status", "last_confirmed_at",
             "supersedes", "message_timestamp", "importance", "source_ids",
             "kind", "belief_meta")


def _create_v8_db(path, *, with_vec: bool = False):
    """v8-фикстура: 2 факта (chat_history/derived_belief) с полными колонками
    + FTS-строки; при with_vec — vec0-таблица с rowid = id (эмуляция prod)."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_V8_DDL)
    conn.execute(
        "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
        "created_at, target_user, weight, status, last_confirmed_at, "
        "supersedes, message_timestamp, importance, source_ids, kind, "
        "belief_meta) VALUES "
        "(7, -100, 'вася переехал в москву', 'chat_history', NULL, "
        "1700000000, 'вася', 0.7, 'confirmed', 1700000000, NULL, 1700000000, "
        "5, NULL, 'fact', NULL),"
        "(8, -100, 'вася всегда платит за всех', 'derived_belief', NULL, "
        "1700000001, NULL, 0.6, 'confirmed', 1700000001, NULL, NULL, 9, "
        "'[7]', 'belief', '{\"cluster_id\": 1}')")
    conn.execute(
        "INSERT INTO graph_facts_fts(rowid, fact) SELECT id, fact FROM graph_facts")
    if with_vec:
        import sqlite_vec
        conn.enable_load_extension(True)
        conn.load_extension(sqlite_vec.loadable_path())
        conn.execute(
            "CREATE VIRTUAL TABLE graph_facts_vec USING vec0("
            "embedding float[4] distance_metric=cosine, +fact_id INTEGER, "
            "+chat_id INTEGER, +origin TEXT, +expires_at INTEGER)")
        conn.execute(
            "INSERT INTO graph_facts_vec(rowid, embedding, fact_id, chat_id, "
            "origin, expires_at) VALUES (7, '[1,0,0,0]', 7, -100, "
            "'chat_history', NULL)")
    conn.execute("PRAGMA user_version = 8")
    conn.commit()
    conn.close()


@pytest.fixture
def db():
    """Свежая in-memory БД (каскад миграций v1..v9 применён)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class TestMigrationV9:
    @pytest.mark.asyncio
    async def test_v8_db_migrates_preserving_all_16_columns_and_fts(
            self, tmp_path):
        path = tmp_path / "v8.db"
        _create_v8_db(path)
        d = DatabaseService(str(path))
        await d.initialize()

        cols = {r["name"] for r in
                await (await d.db.execute("PRAGMA table_info(graph_facts)")).fetchall()}
        assert set(_ALL_COLS) <= cols
        cursor = await d.db.execute(
            "SELECT " + ", ".join(_ALL_COLS) + " FROM graph_facts ORDER BY id")
        rows = await cursor.fetchall()
        assert [(r["id"], r["origin"]) for r in rows] == \
            [(7, "chat_history"), (8, "derived_belief")]
        assert rows[0]["fact"] == "вася переехал в москву"
        assert rows[0]["importance"] == 5
        assert rows[0]["target_user"] == "вася"
        assert rows[0]["message_timestamp"] == 1700000000
        # не потеряли v8 belief-колонки
        assert rows[1]["kind"] == "belief"
        assert rows[1]["importance"] == 9
        assert rows[1]["source_ids"] == "[7]"
        assert rows[1]["belief_meta"] == '{"cluster_id": 1}'
        # CHECK расширен
        cursor = await d.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='graph_facts'")
        assert "bot_self_reply" in (await cursor.fetchone())["sql"]
        # 5 индексов v8 пересозданы
        cursor = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
            "('idx_graph_facts_chat_origin', 'idx_graph_facts_target_user', "
            "'idx_graph_facts_history_import', 'idx_graph_facts_chat_kind', "
            "'idx_graph_facts_beliefs')")
        assert len({r["name"] for r in await cursor.fetchall()}) == 5
        # FTS валиден БЕЗ пересоздания (rowid 1:1)
        found = await d.search_graph_facts_fts(-100, '"москву"*', 5,
                                               2_000_000_000)
        assert any(r["id"] == 7 for r in found)
        # self-факт теперь проходит CHECK + FTS пишется
        fid = await d.insert_graph_fact(
            -100, "[Бот] посоветовал: пить чай", "bot_self_reply", None,
            weight=0.2, importance=2, kind="fact")
        assert fid > 0
        found = await d.search_graph_facts_fts(
            -100, '"чай"*', 5, 2_000_000_000, include_self=True)
        assert any(r["id"] == fid for r in found)
        # user_version = 9
        assert (await (await d.db.execute("PRAGMA user_version")).fetchone())[0] == 12
        await d.close()

    @pytest.mark.asyncio
    async def test_reinitialize_is_noop(self, tmp_path):
        path = tmp_path / "v8b.db"
        _create_v8_db(path)
        d = DatabaseService(str(path))
        await d.initialize()
        await d.close()
        await d.initialize()                        # «рестарт» — no-op
        assert (await (await d.db.execute("PRAGMA user_version")).fetchone())[0] == 12
        assert (await (await d.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts")).fetchone())["c"] == 2
        await d.close()

    @pytest.mark.asyncio
    async def test_from_scratch_schema_version_and_check(self):
        d = DatabaseService(":memory:")
        await d.initialize()
        cols = {r["name"] for r in
                await (await d.db.execute("PRAGMA table_info(graph_facts)")).fetchall()}
        assert set(_ALL_COLS) <= cols
        sql = (await (await d.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='graph_facts'")).fetchone())["sql"]
        assert "bot_self_reply" in sql
        assert (await (await d.db.execute("PRAGMA user_version")).fetchone())[0] == 12
        await d.close()

    @pytest.mark.asyncio
    async def test_vec_rowid_survives_rebuild(self, tmp_path):
        """vec-строка (rowid=id факта) остаётся валидной: graph_facts rebuild
        сохраняет id 1:1 и НЕ трогает graph_facts_vec (прецедент D201)."""
        path = tmp_path / "v8vec.db"
        _create_v8_db(path, with_vec=True)
        d = DatabaseService(str(path))
        await d.initialize()
        cursor = await d.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE id = 7")
        assert (await cursor.fetchone())["c"] == 1
        # vec-таблица сохранена и ссылается на тот же id
        import sqlite_vec
        await d.db.enable_load_extension(True)
        await d.db.load_extension(sqlite_vec.loadable_path())
        cur = await d.db.execute(
            "SELECT rowid AS r, fact_id FROM graph_facts_vec WHERE rowid = 7")
        row = await cur.fetchone()
        assert row is not None and row["fact_id"] == 7
        await d.close()


class TestOriginFilters:
    """ADR-1014-2 D6: self не виден Сну/золотым/компакции/счётчикам."""

    @pytest.mark.asyncio
    async def test_self_excluded_from_new_confirmed_and_golden(self, db):
        now = int(time.time())
        old = now - 400 * 86400
        await db.insert_graph_fact(-100, "пользовательский старый факт",
                                   "chat_history", None, importance=5)
        self_id = await db.insert_graph_fact(
            -100, "[Бот] заявил: любит грибы", "bot_self_reply", None,
            weight=0.2, importance=5)
        # list_new_confirmed_facts
        rows = await db.list_new_confirmed_facts(-100, 0, now_ts=now)
        assert all("грибы" not in r["fact"] for r in rows)
        assert any("пользовательский" in r["fact"] for r in rows)
        # search_golden_facts_fts (kind=fact, importance>=5, давность)
        cur = await db.db.execute(
            "UPDATE graph_facts SET message_timestamp = ?, created_at = ? "
            "WHERE id = ?", (old, old, self_id))
        await db.db.commit()
        golden = await db.search_golden_facts_fts(
            -100, '"грибы"*', 10, now, min_importance=1,
            max_age_ts=now - 86400)
        assert golden == []

    @pytest.mark.asyncio
    async def test_self_excluded_from_live_and_dup_groups(self, db):
        now = int(time.time())
        await db.insert_graph_fact(-100, "[Бот] решил: дубль",
                                   "bot_self_reply", None, weight=0.2)
        await db.insert_graph_fact(-100, "[Бот] решил: дубль",
                                   "bot_self_reply", None, weight=0.2)
        live = await db.get_live_graph_facts(-100, now)
        assert all(r["origin"] != "bot_self_reply" for r in live)
        groups = await db.find_exact_dup_groups(-100, now)
        assert groups == []

    @pytest.mark.asyncio
    async def test_graph_stats_excludes_self_and_counts_it(self, db):
        await db.insert_graph_fact(-100, "обычный факт", "chat_history", None)
        await db.insert_graph_fact(-100, "[Бот] заявил: тест", "bot_self_reply",
                                   None, weight=0.2, importance=2)
        stats = await db.graph_stats(chat_id=-100)
        assert stats["facts"] == 1
        assert stats["bot_self_replies"] == 1

    @pytest.mark.asyncio
    async def test_fts_default_hides_self_include_self_shows(self, db):
        fid = await db.insert_graph_fact(
            -100, "[Бот] посоветовал: гулять", "bot_self_reply", None,
            weight=0.2, importance=2)
        hidden = await db.search_graph_facts_fts(-100, '"гулять"*', 5,
                                                 2_000_000_000)
        assert all(r["id"] != fid for r in hidden)
        shown = await db.search_graph_facts_fts(
            -100, '"гулять"*', 5, 2_000_000_000, include_self=True)
        assert any(r["id"] == fid for r in shown)

    def test_vec_filter_hides_self_by_default(self):
        now = int(time.time())
        rows = [
            {"fact_id": 1, "chat_id": -100, "origin": "bot_self_reply",
             "expires_at": None},
            {"fact_id": 2, "chat_id": -100, "origin": "chat_history",
             "expires_at": None},
        ]
        kept = MemoryManager._filter_vec_rows(rows, -100, True, now)
        assert [r["fact_id"] for r in kept] == [2]
        kept = MemoryManager._filter_vec_rows(rows, -100, True, now,
                                              include_self=True)
        assert [r["fact_id"] for r in kept] == [1, 2]


class _NoLLM:
    """LLM-заглушка: embed недоступен → FTS-режим MemoryManager."""

    async def generate(self, messages):
        raise AssertionError("generate не должен вызываться")

    async def embed(self, texts):
        raise AssertionError("embed не должен вызываться")


class TestSelfWeightAndLabel:
    def test_origin_weight_self_default_and_hot_override(self, monkeypatch):
        from services import hot_config as hot
        from services.summary_memory import _origin_weight
        assert _origin_weight("bot_self_reply") == pytest.approx(0.2)
        real_get = hot.get
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: 0.35
            if key == "limits.graph_fact_weight_bot" else real_get(key, default))
        assert _origin_weight("bot_self_reply") == pytest.approx(0.35)
        # пользовательский вес не тронут
        assert _origin_weight("bot_direct_reply") == pytest.approx(0.7)

    def test_rule_importance_self_is_low(self):
        from services.database import rule_importance
        assert rule_importance("bot_self_reply", "короткий") == 2

    def test_origin_label_is_self_tag(self):
        from services.summary_memory import _ORIGIN_LABELS
        assert _ORIGIN_LABELS["bot_self_reply"] == "Источник: Я сам (Бот)"


class TestMemorizeSelfReply:
    @pytest.mark.asyncio
    async def test_flag_on_writes_self_fact(self, db, monkeypatch):
        from services import hot_config as hot
        real_get = hot.get
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: True
            if key == "flags.bot_self_awareness_enabled"
            else real_get(key, default))
        memory = MemoryManager(db, _NoLLM())
        memory._vec_available = False
        fid = await memory.memorize_self_reply(-100, "[Бот] решил: пить чай")
        assert fid > 0
        cursor = await db.db.execute(
            "SELECT origin, status, kind, target_user, weight, importance "
            "FROM graph_facts WHERE id = ?", (fid,))
        row = await cursor.fetchone()
        assert row["origin"] == "bot_self_reply"
        assert row["status"] == "confirmed"
        assert row["kind"] == "fact"
        assert row["target_user"] is None
        assert row["weight"] == pytest.approx(0.2)
        assert row["importance"] == 2
        # FTS-строка записана (внутри insert_graph_fact)
        found = await db.search_graph_facts_fts(
            -100, '"чай"*', 5, int(time.time()) + 10, include_self=True)
        assert any(r["id"] == fid for r in found)
        # nodes/edges НЕ создаются
        assert (await (await db.db.execute(
            "SELECT COUNT(*) AS c FROM nodes")).fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_empty_essence_noop(self, db):
        memory = MemoryManager(db, _NoLLM())
        memory._vec_available = False
        assert await memory.memorize_self_reply(-100, "   ") == 0

    @pytest.mark.asyncio
    async def test_flag_off_noop(self, db, monkeypatch):
        from services import hot_config as hot
        real_get = hot.get
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: False
            if key == "flags.bot_self_awareness_enabled"
            else real_get(key, default))
        memory = MemoryManager(db, _NoLLM())
        memory._vec_available = False
        assert await memory.memorize_self_reply(-100, "[Бот] решил: x") == 0

