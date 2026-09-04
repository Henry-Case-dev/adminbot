"""Tests for the GraphRAG nodes/edges DB layer (Epic 26, T-200/T26.1, Section 35.2/35.5)."""
import asyncio

import pytest

from services.database import DatabaseService


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class TestGraphSchema:
    @pytest.mark.asyncio
    async def test_tables_created(self, db):
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row["name"] async for row in cursor]
        assert "nodes" in tables
        assert "edges" in tables

    @pytest.mark.asyncio
    async def test_indexes_created(self, db):
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        indexes = {row["name"] async for row in cursor}
        assert {"idx_nodes_chat_type", "idx_edges_source", "idx_edges_target",
                "idx_edges_chat_weight"} <= indexes

    @pytest.mark.asyncio
    async def test_reinitialize_on_existing_db_is_idempotent(self, tmp_path):
        """Старая БД получает таблицы графа при рестарте (pattern 33.3) без потери данных."""
        d = DatabaseService(str(tmp_path / "graph.db"))
        await d.initialize()
        first_id = await d.upsert_node(-100, "вася", "user")
        await d.close()        # гигиена: закрываем коннекцию перед «рестартом»
        await d.initialize()   # рестарт: reconnect к тому же файлу
        again_id = await d.upsert_node(-100, "вася", "user")
        assert again_id == first_id
        cursor = await d.db.execute(
            "SELECT COUNT(*) AS c FROM nodes WHERE chat_id = ?", (-100,)
        )
        row = await cursor.fetchone()
        assert row["c"] == 1
        await d.close()

    @pytest.mark.asyncio
    async def test_entity_type_check_rejects_unknown(self, db):
        import aiosqlite

        with pytest.raises(aiosqlite.IntegrityError):
            await db.db.execute(
                "INSERT INTO nodes (chat_id, entity_name, entity_type) "
                "VALUES (-100, 'х', 'banana')"
            )

    @pytest.mark.asyncio
    async def test_entity_type_event_allowed_by_ddl(self, db):
        """Q1: CHECK включает 'event' (форвард-совместимость), парсер v1 его не создаёт."""
        await db.db.execute(
            "INSERT INTO nodes (chat_id, entity_name, entity_type) "
            "VALUES (-100, 'событие', 'event')"
        )
        await db.db.commit()
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM nodes")
        row = await cursor.fetchone()
        assert row["c"] == 1


class TestUpsertNode:
    @pytest.mark.asyncio
    async def test_creates_node_and_returns_id(self, db):
        node_id = await db.upsert_node(-100, "вася", "user")
        assert node_id > 0
        cursor = await db.db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = await cursor.fetchone()
        assert row["chat_id"] == -100
        assert row["entity_name"] == "вася"
        assert row["entity_type"] == "user"

    @pytest.mark.asyncio
    async def test_idempotent_same_id(self, db):
        first = await db.upsert_node(-100, "вася", "user")
        second = await db.upsert_node(-100, "вася", "user")
        assert first == second
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM nodes")
        row = await cursor.fetchone()
        assert row["c"] == 1

    @pytest.mark.asyncio
    async def test_chat_isolation(self, db):
        id_a = await db.upsert_node(-100, "вася", "user")
        id_b = await db.upsert_node(-200, "вася", "user")
        assert id_a != id_b

    @pytest.mark.asyncio
    async def test_normalization_is_code_side(self, db):
        """D70: lower/strip делает код; БД хранит ровно то, что передали."""
        await db.upsert_node(-100, "Вася", "user")
        cursor = await db.db.execute("SELECT entity_name FROM nodes")
        row = await cursor.fetchone()
        assert row["entity_name"] == "Вася"


class TestUpsertEdge:
    @pytest.mark.asyncio
    async def test_creates_edge_with_default_weight(self, db):
        sid = await db.upsert_node(-100, "вася", "user")
        oid = await db.upsert_node(-100, "петя", "user")
        await db.upsert_edge(sid, oid, "спорил с")
        cursor = await db.db.execute("SELECT * FROM edges")
        row = await cursor.fetchone()
        assert row["source_id"] == sid
        assert row["target_id"] == oid
        assert row["relation_type"] == "спорил с"
        assert row["weight"] == 1
        assert row["chat_id"] == -100  # из узла-источника

    @pytest.mark.asyncio
    async def test_conflict_increments_weight_and_dedups(self, db):
        sid = await db.upsert_node(-100, "вася", "user")
        oid = await db.upsert_node(-100, "петя", "user")
        await db.upsert_edge(sid, oid, "спорил с")
        await db.upsert_edge(sid, oid, "спорил с")
        await db.upsert_edge(sid, oid, "спорил с")
        cursor = await db.db.execute("SELECT weight FROM edges")
        row = await cursor.fetchone()
        assert row["weight"] == 3
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM edges")
        row = await cursor.fetchone()
        assert row["c"] == 1  # UNIQUE (source, target, relation) дедуп

    @pytest.mark.asyncio
    async def test_weight_increment_parameter(self, db):
        """Epic 60 (66.3): подтверждение связи — +инкремент с cap 5
        (T-459 тема 5: «+1 cap 5») — вес не растёт вечно."""
        sid = await db.upsert_node(-100, "вася", "user")
        oid = await db.upsert_node(-100, "петя", "user")
        await db.upsert_edge(sid, oid, "спорил с", weight_increment=5)
        await db.upsert_edge(sid, oid, "спорил с", weight_increment=5)
        cursor = await db.db.execute("SELECT weight FROM edges")
        row = await cursor.fetchone()
        assert row["weight"] == 5                       # cap 5 (66.3)

    @pytest.mark.asyncio
    async def test_conflict_bumps_last_updated(self, db):
        sid = await db.upsert_node(-100, "вася", "user")
        oid = await db.upsert_node(-100, "петя", "user")
        await db.upsert_edge(sid, oid, "спорил с")
        await db.db.execute(
            "UPDATE edges SET last_updated = '2000-01-01 00:00:00'"
        )
        await db.db.commit()
        await db.upsert_edge(sid, oid, "спорил с")
        cursor = await db.db.execute("SELECT last_updated FROM edges")
        row = await cursor.fetchone()
        assert row["last_updated"] != "2000-01-01 00:00:00"

    @pytest.mark.asyncio
    async def test_different_relation_types_are_separate_rows(self, db):
        sid = await db.upsert_node(-100, "вася", "user")
        oid = await db.upsert_node(-100, "петя", "user")
        await db.upsert_edge(sid, oid, "спорил с")
        await db.upsert_edge(sid, oid, "фанатеет от")
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM edges")
        row = await cursor.fetchone()
        assert row["c"] == 2


class TestMatchNodes:
    @pytest.mark.asyncio
    async def test_user_exact_match(self, db):
        nid = await db.upsert_node(-100, "вася", "user")
        assert await db.match_nodes(-100, ["вася"], []) == [nid]

    @pytest.mark.asyncio
    async def test_user_multiple_names(self, db):
        id1 = await db.upsert_node(-100, "вася", "user")
        id2 = await db.upsert_node(-100, "петя", "user")
        await db.upsert_node(-100, "дима", "user")
        ids = await db.match_nodes(-100, ["вася", "петя"], [])
        assert sorted(ids) == sorted([id1, id2])

    @pytest.mark.asyncio
    async def test_topic_like_substring(self, db):
        nid = await db.upsert_node(-100, "ракеты", "topic")
        ids = await db.match_nodes(-100, [], ["ракет"])
        assert ids == [nid]

    @pytest.mark.asyncio
    async def test_users_and_topics_combined(self, db):
        uid = await db.upsert_node(-100, "вася", "user")
        tid = await db.upsert_node(-100, "дроны", "topic")
        ids = await db.match_nodes(-100, ["вася"], ["дрон"])
        assert sorted(ids) == sorted([uid, tid])

    @pytest.mark.asyncio
    async def test_empty_lists_return_empty_without_sql(self, db):
        assert await db.match_nodes(-100, [], []) == []

    @pytest.mark.asyncio
    async def test_user_not_matched_as_topic_and_vice_versa(self, db):
        await db.upsert_node(-100, "ракеты", "user")
        await db.upsert_node(-100, "вася", "topic")
        assert await db.match_nodes(-100, [], ["ракет"]) == []
        assert await db.match_nodes(-100, ["вася"], []) == []

    @pytest.mark.asyncio
    async def test_chat_isolation(self, db):
        await db.upsert_node(-100, "вася", "user")
        assert await db.match_nodes(-200, ["вася"], []) == []

    @pytest.mark.asyncio
    async def test_no_match(self, db):
        await db.upsert_node(-100, "вася", "user")
        assert await db.match_nodes(-100, ["петя"], []) == []


class TestTopEdges:
    @pytest.mark.asyncio
    async def _graph(self, db):
        a = await db.upsert_node(-100, "вася", "user")
        b = await db.upsert_node(-100, "петя", "user")
        c = await db.upsert_node(-100, "дима", "user")
        t = await db.upsert_node(-100, "ракеты", "topic")
        await db.upsert_edge(a, b, "спорил с")                    # weight 1
        await db.upsert_edge(a, b, "спорил с")                    # weight 2
        await db.upsert_edge(b, c, "оскорбил")                    # weight 1
        await db.upsert_edge(a, t, "фанатеет от", weight_increment=5)  # weight 5
        return {"a": a, "b": b, "c": c, "t": t}

    @pytest.mark.asyncio
    async def test_weight_desc_order(self, db):
        ids = await self._graph(db)
        rows = await db.get_top_edges(-100, [ids["a"], ids["b"]], 10)
        assert [r["weight"] for r in rows] == [5, 2, 1]

    @pytest.mark.asyncio
    async def test_limit(self, db):
        ids = await self._graph(db)
        rows = await db.get_top_edges(-100, [ids["a"], ids["b"]], 2)
        assert len(rows) == 2
        assert [r["weight"] for r in rows] == [5, 2]

    @pytest.mark.asyncio
    async def test_entity_scope(self, db):
        ids = await self._graph(db)
        rows = await db.get_top_edges(-100, [ids["c"]], 10)
        assert len(rows) == 1
        assert rows[0]["relation_type"] == "оскорбил"
        assert rows[0]["source_name"] == "петя"
        assert rows[0]["target_name"] == "дима"

    @pytest.mark.asyncio
    async def test_empty_entity_ids_return_empty(self, db):
        await self._graph(db)
        assert await db.get_top_edges(-100, [], 10) == []

    @pytest.mark.asyncio
    async def test_joined_names_present(self, db):
        ids = await self._graph(db)
        rows = await db.get_top_edges(-100, [ids["a"]], 10)
        first = rows[0]
        assert first["source_name"] == "вася"
        assert first["target_name"] == "ракеты"
        assert first["source_type"] == "user"
        assert first["target_type"] == "topic"

    @pytest.mark.asyncio
    async def test_tie_break_id_desc(self, db):
        a = await db.upsert_node(-100, "вася", "user")
        b = await db.upsert_node(-100, "петя", "user")
        c = await db.upsert_node(-100, "дима", "user")
        await db.upsert_edge(a, b, "р1")   # id 1, weight 1
        await db.upsert_edge(a, c, "р2")   # id 2, weight 1
        rows = await db.get_top_edges(-100, [a], 10)
        assert [r["relation_type"] for r in rows] == ["р2", "р1"]

    @pytest.mark.asyncio
    async def test_get_top_edges_all_ignores_scope(self, db):
        ids = await self._graph(db)
        rows = await db.get_top_edges_all(-100, 10)
        assert len(rows) == 3
        assert [r["weight"] for r in rows] == [5, 2, 1]

    @pytest.mark.asyncio
    async def test_get_top_edges_all_limit(self, db):
        await self._graph(db)
        rows = await db.get_top_edges_all(-100, 1)
        assert len(rows) == 1
        assert rows[0]["weight"] == 5

    @pytest.mark.asyncio
    async def test_chat_isolation(self, db):
        ids = await self._graph(db)
        assert await db.get_top_edges(-200, [ids["a"]], 10) == []
        assert await db.get_top_edges_all(-200, 10) == []

    @pytest.mark.asyncio
    async def test_empty_graph(self, db):
        assert await db.get_top_edges_all(-100, 10) == []


# ── Epic 46 (Section 55.3, T-366-A #1-7) ─────────────────────────

_OLD_NODES_DDL = """
CREATE TABLE nodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('user', 'topic', 'event')),
    UNIQUE (chat_id, entity_name)
);
"""

_OLD_EDGES_DDL = """
CREATE TABLE edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    source_id     INTEGER NOT NULL REFERENCES nodes(id),
    target_id     INTEGER NOT NULL REFERENCES nodes(id),
    relation_type TEXT NOT NULL,
    weight        INTEGER NOT NULL DEFAULT 1,
    last_updated  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, target_id, relation_type)
);
"""


def _create_old_db(path):
    """Пре-Epic-46 схема (без origin/expires_at, CHECK без 'fact', user_version 0)."""
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.executescript(_OLD_NODES_DDL + _OLD_EDGES_DDL)
    conn.execute(
        "INSERT INTO nodes (id, chat_id, entity_name, entity_type) "
        "VALUES (7, -100, 'вася', 'user'), (9, -100, 'ракеты', 'topic')"
    )
    conn.execute(
        "INSERT INTO edges (chat_id, source_id, target_id, relation_type) "
        "VALUES (-100, 7, 9, 'фанатеет от')"
    )
    conn.commit()
    conn.close()


class TestGraphRagV2Migration:
    @pytest.mark.asyncio
    async def test_origin_expires_at_columns_present(self, db):
        """#1: nodes/edges имеют origin/expires_at (PRAGMA table_info)."""
        for table in ("nodes", "edges"):
            cursor = await db.db.execute(f"PRAGMA table_info({table})")
            columns = {row["name"] for row in await cursor.fetchall()}
            assert {"origin", "expires_at"} <= columns

    @pytest.mark.asyncio
    async def test_entity_type_check_fact_allowed_banana_rejected(self, db):
        """#1: CHECK расширен до 'fact'; 'banana' — IntegrityError."""
        import aiosqlite

        await db.db.execute(
            "INSERT INTO nodes (chat_id, entity_name, entity_type) "
            "VALUES (-100, 'факт-узел', 'fact')"
        )
        await db.db.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await db.db.execute(
                "INSERT INTO nodes (chat_id, entity_name, entity_type) "
                "VALUES (-100, 'х', 'banana')"
            )

    @pytest.mark.asyncio
    async def test_user_version_is_3_after_initialize(self, db):
        """#2: PRAGMA user_version == 7 (Epic 46 → 1, Epic 50/58.7 → 2,
        Epic 60/63.3 → 3, видео-origins → 4, user_memory-origins → 5,
        protected_facts chat-level → 6, фаза 2: history_import → 7)."""
        cursor = await db.db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row[0] == 7

    @pytest.mark.asyncio
    async def test_reinitialize_is_idempotent_user_version_stays_3(self, tmp_path):
        """#2: повторный initialize идемпотентен (user_version остаётся 7)."""
        d = DatabaseService(str(tmp_path / "mig2.db"))
        await d.initialize()
        await d.close()
        await d.initialize()
        cursor = await d.db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row[0] == 7
        await d.close()

    @pytest.mark.asyncio
    async def test_old_db_migrated_data_kept_ids_preserved(self, tmp_path):
        """#3: старая БД (DDL до Epic 46) → initialize: колонки добавлены,
        данные сохранены (id узлов те же), user_version 3 (Epic 60/63.3)."""
        path = tmp_path / "old.db"
        _create_old_db(path)
        d = DatabaseService(str(path))
        await d.initialize()

        for table in ("nodes", "edges"):
            cursor = await d.db.execute(f"PRAGMA table_info({table})")
            columns = {row["name"] for row in await cursor.fetchall()}
            assert {"origin", "expires_at"} <= columns

        cursor = await d.db.execute(
            "SELECT id, chat_id, entity_name, entity_type, origin, expires_at "
            "FROM nodes ORDER BY id"
        )
        rows = await cursor.fetchall()
        assert [(r["id"], r["entity_name"], r["entity_type"]) for r in rows] == [
            (7, "вася", "user"), (9, "ракеты", "topic"),
        ]
        assert all(r["origin"] == "chat_history" for r in rows)
        assert all(r["expires_at"] is None for r in rows)

        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM edges")
        row = await cursor.fetchone()
        assert row["c"] == 1

        cursor = await d.db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        assert row[0] == 7                      # каскад до v7 (раунды 4/5 + фаза 2)

        # расширенный CHECK активен: 'fact' проходит, 'banana' — нет
        import aiosqlite

        await d.db.execute(
            "INSERT INTO nodes (chat_id, entity_name, entity_type) "
            "VALUES (-100, 'ф', 'fact')"
        )
        await d.db.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await d.db.execute(
                "INSERT INTO nodes (chat_id, entity_name, entity_type) "
                "VALUES (-100, 'б', 'banana')"
            )
        await d.close()


class TestGraphRagV2Upserts:
    @pytest.mark.asyncio
    async def test_upsert_node_writes_origin_and_expires_at(self, db):
        """#4: upsert_node с origin/expires_at — колонки записаны."""
        exp = 1_800_000_000
        nid = await db.upsert_node(-100, "озон", "fact", origin="search_fact",
                                   expires_at=exp)
        cursor = await db.db.execute(
            "SELECT origin, expires_at FROM nodes WHERE id = ?", (nid,)
        )
        row = await cursor.fetchone()
        assert row["origin"] == "search_fact"
        assert row["expires_at"] == exp

    @pytest.mark.asyncio
    async def test_upsert_node_existing_keeps_its_own_values(self, db):
        """#4: INSERT OR IGNORE — существующий узел НЕ перезаписан."""
        first = await db.upsert_node(-100, "озон", "fact", origin="web_content",
                                     expires_at=1_800_000_000)
        again = await db.upsert_node(-100, "озон", "fact", origin="chat_history",
                                     expires_at=None)
        assert again == first
        cursor = await db.db.execute(
            "SELECT origin, expires_at FROM nodes WHERE id = ?", (first,)
        )
        row = await cursor.fetchone()
        assert row["origin"] == "web_content"
        assert row["expires_at"] == 1_800_000_000

    @pytest.mark.asyncio
    async def test_upsert_edge_writes_origin_and_expires_at(self, db):
        """#4: upsert_edge с origin/expires_at."""
        exp = 1_800_000_000
        sid = await db.upsert_node(-100, "озон", "fact", origin="search_fact")
        oid = await db.upsert_node(-100, "вб", "fact", origin="search_fact")
        await db.upsert_edge(sid, oid, "доставляет быстрее чем",
                             origin="search_fact", expires_at=exp)
        cursor = await db.db.execute(
            "SELECT origin, expires_at FROM edges WHERE source_id = ?", (sid,)
        )
        row = await cursor.fetchone()
        assert row["origin"] == "search_fact"
        assert row["expires_at"] == exp


class TestGraphFacts:
    @pytest.mark.asyncio
    async def test_insert_and_fts_search_with_ttl_param(self, db):
        """#5: insert_graph_fact + search_graph_facts_fts; истёкший факт НЕ в
        выдаче (TTL-параметр now_ts)."""
        now = 1_800_000_000
        await db.insert_graph_fact(-100, "озон доставляет быстрее", "search_fact",
                                   now + 1000)
        await db.insert_graph_fact(-100, "древний факт про озон", "search_fact",
                                   now - 1000)
        await db.insert_graph_fact(-100, "вечный факт про озон", "chat_history", None)
        rows = await db.search_graph_facts_fts(-100, '"озон"*', 10, now)
        facts = [r["fact"] for r in rows]
        assert "озон доставляет быстрее" in facts
        assert "вечный факт про озон" in facts
        assert "древний факт про озон" not in facts

    @pytest.mark.asyncio
    async def test_get_graph_fact_texts_keeps_knn_order(self, db):
        """get_graph_fact_texts: [(origin, fact, created_at), ...] в порядке
        fact_ids (Epic 50/58.7: + created_at для хронологии DirectChat)."""
        f1 = await db.insert_graph_fact(-100, "факт один", "web_content", None)
        f2 = await db.insert_graph_fact(-100, "факт два", "search_fact", None)
        rows = await db.get_graph_fact_texts([f2, f1, 999])
        assert len(rows) == 2
        assert rows[0][:2] == ("search_fact", "факт два")
        assert rows[1][:2] == ("web_content", "факт один")
        assert all(isinstance(r[2], int) for r in rows)

    @pytest.mark.asyncio
    async def test_direct_chat_migration_columns_and_check(self, db):
        """Epic 50 (58.7, D201): graph_facts CHECK + 'bot_direct_reply' +
        target_user; smart_messages.tg_message_id; user_version == 3
        (Epic 60/63.3 — v2 поверх v1, v3 поверх v2)."""
        import aiosqlite

        cursor = await db.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'")
        row = await cursor.fetchone()
        assert "bot_direct_reply" in row["sql"]
        cursor = await db.db.execute("PRAGMA table_info(graph_facts)")
        cols = {r["name"] for r in await cursor.fetchall()}
        assert "target_user" in cols
        cursor = await db.db.execute("PRAGMA table_info(smart_messages)")
        cols = {r["name"] for r in await cursor.fetchall()}
        assert "tg_message_id" in cols
        # CHECK принимает bot_direct_reply, отклоняет левый origin
        fid = await db.insert_graph_fact(-100, "диалог с ботом", "bot_direct_reply",
                                         None, target_user="вася")
        cursor = await db.db.execute(
            "SELECT origin, target_user FROM graph_facts WHERE id = ?", (fid,))
        fact = await cursor.fetchone()
        assert fact["origin"] == "bot_direct_reply"
        assert fact["target_user"] == "вася"
        with pytest.raises(aiosqlite.IntegrityError):
            await db.db.execute(
                "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
                "VALUES (-100, 'x', 'alien_origin', 100)")

    @pytest.mark.asyncio
    async def test_direct_chat_migration_idempotent_and_fts_intact(self, tmp_path):
        """Epic 50 (58.7): повторный initialize — no-op; graph_facts_fts
        валиден БЕЗ пересоздания (id сохранены)."""
        d = DatabaseService(str(tmp_path / "mig_dc.db"))
        await d.initialize()
        fid = await d.insert_graph_fact(-100, "факт до рестарта", "chat_history", None)
        await d.close()
        await d.initialize()                       # рестарт: миграция — no-op
        cursor = await d.db.execute(
            "SELECT id, fact FROM graph_facts WHERE id = ?", (fid,))
        row = await cursor.fetchone()
        assert row["fact"] == "факт до рестарта"
        rows = await d.search_graph_facts_fts(-100, '"факт"*', 10, 1_800_000_000)
        assert any(r["fact"] == "факт до рестарта" for r in rows)
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 7    # каскад v2…v7 (раунды 4/5)
        await d.close()

    @pytest.mark.asyncio
    async def test_search_fts_filters_direct_reply_by_default(self, db):
        """Epic 50 (58.8, D206): default — bot_direct_reply НЕ в чужих RAG;
        include_direct_reply=True — участвует."""
        await db.insert_graph_fact(-100, "бот рассказал секрет", "bot_direct_reply", None)
        await db.insert_graph_fact(-100, "пользователь спросил", "chat_history", None)
        rows = await db.search_graph_facts_fts(-100, '"рассказал"*', 10, 1_800_000_000)
        assert not any("бот рассказал" in r["fact"] for r in rows)
        rows = await db.search_graph_facts_fts(
            -100, '"рассказал"*', 10, 1_800_000_000, include_direct_reply=True)
        assert any("бот рассказал" in r["fact"] for r in rows)

    @pytest.mark.asyncio
    async def test_save_smart_message_with_tg_message_id(self, db):
        """Epic 50 (58.7): tg_message_id сохраняется; get_smart_message_by_tg_id."""
        await db.save_smart_message(
            user_id=10, chat_id=-100, text="привет", reply_to_id=None,
            timestamp=1_700_000_000, media_type="text", author_name="вася",
            message_id=777)
        row = await db.get_smart_message_by_tg_id(-100, 777)
        assert row is not None and row["text"] == "привет"
        assert await db.get_smart_message_by_tg_id(-100, 999) is None

    @pytest.mark.asyncio
    async def test_purge_expired_graph_facts(self, db, monkeypatch):
        """#6: purge: истёкшие nodes/edges/facts удалены, живые остались."""
        now = 1_800_000_000
        monkeypatch.setattr("services.database.time.time", lambda: now)
        dead_exp = now - 100
        live_exp = now + 1000
        # истёкшие узлы + ребро
        a = await db.upsert_node(-100, "мёртвый а", "fact", origin="search_fact",
                                 expires_at=dead_exp)
        b = await db.upsert_node(-100, "мёртвый б", "fact", origin="search_fact",
                                 expires_at=dead_exp)
        await db.upsert_edge(a, b, "связь мёртвых", origin="search_fact",
                             expires_at=dead_exp)
        # живые узлы + ребро с собственным истёкшим expires_at
        c = await db.upsert_node(-100, "живой в", "fact", origin="web_content",
                                 expires_at=live_exp)
        d = await db.upsert_node(-100, "живой г", "fact", origin="web_content",
                                 expires_at=live_exp)
        await db.upsert_edge(c, d, "связь с истёкшим ttl", origin="web_content",
                             expires_at=dead_exp)
        await db.upsert_edge(c, d, "живая связь", origin="web_content",
                             expires_at=live_exp)
        # факты
        await db.insert_graph_fact(-100, "мёртвый факт", "search_fact", dead_exp)
        await db.insert_graph_fact(-100, "живой факт", "web_content", live_exp)
        await db.insert_graph_fact(-100, "вечный факт", "chat_history", None)

        deleted = await db.purge_expired_graph_facts(-100)
        assert deleted == 1            # только graph_facts (rowcount последнего DELETE)

        cursor = await db.db.execute("SELECT entity_name FROM nodes ORDER BY id")
        names = [r["entity_name"] for r in await cursor.fetchall()]
        assert names == ["живой в", "живой г"]

        cursor = await db.db.execute(
            "SELECT relation_type FROM edges ORDER BY id"
        )
        rels = [r["relation_type"] for r in await cursor.fetchall()]
        assert rels == ["живая связь"]

        cursor = await db.db.execute("SELECT fact FROM graph_facts ORDER BY id")
        facts = [r["fact"] for r in await cursor.fetchall()]
        assert facts == ["живой факт", "вечный факт"]

    @pytest.mark.asyncio
    async def test_busy_timeout_pragma_is_5000(self, db):
        """#7: PRAGMA busy_timeout == 5000 после initialize."""
        cursor = await db.db.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
        assert row[0] == 5000
