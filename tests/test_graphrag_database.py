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
        sid = await db.upsert_node(-100, "вася", "user")
        oid = await db.upsert_node(-100, "петя", "user")
        await db.upsert_edge(sid, oid, "спорил с", weight_increment=5)
        await db.upsert_edge(sid, oid, "спорил с", weight_increment=5)
        cursor = await db.db.execute("SELECT weight FROM edges")
        row = await cursor.fetchone()
        assert row["weight"] == 10

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
