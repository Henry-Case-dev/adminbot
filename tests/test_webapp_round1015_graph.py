"""F1 `graph-sampling-centrality-round1015` — умная выборка графа памяти
(Degree Centrality + окрестность + очистка сирот), ТЗ §1 backend, spec §4,
ADR-1015-2. **Ф3 (раунд 10.18) SUPERSEDE ADR-1015-2**: сиды теперь по
Σ importance и cap 800/2400 — ожидания диапазонов/cap обновлены.

Покрытие:
  * топ-сиды по score и приоритет сидов над соседями;
  * раскрытие окрестности (смежные узлы включены, чужие компоненты отсечены);
  * удаление сирот (узел без рёбер внутри выборки);
  * отсутствие висячих рёбер (S10.13-14: оба конца в nodes);
  * финальный cap/truncated и пустая БД;
  * edge-cap → узел становится сиротой и удаляется;
  * скоуп chat_id и исключение origin='bot_direct_reply';
  * API: limits на месте, проброс seed_nodes, fail-open 200.
"""
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(".")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite DatabaseService (async-фикстура — без утечек loop)."""
    from services.database import DatabaseService
    d = DatabaseService(":memory:")
    await d.initialize()
    yield d
    await d.close()


async def _node(db, chat_id, name, etype="user"):
    return await db.upsert_node(chat_id, name, etype)


async def _edge(db, src, dst, rel="связь", origin="chat_history",
                weight=1):
    await db.upsert_edge(src, dst, rel, weight_increment=weight,
                         origin=origin)


def _ids(snap):
    return {n["id"] for n in snap["nodes"]}


def _assert_connected(snap):
    """Все рёбра замкнуты на узлы (S10.13-14) и нет сирот."""
    ids = _ids(snap)
    assert all(e["from"] in ids and e["to"] in ids for e in snap["edges"])
    touch = {e["from"] for e in snap["edges"]} | \
        {e["to"] for e in snap["edges"]}
    assert all(n["id"] in touch for n in snap["nodes"])


class TestSeedsAndNeighbourhood:
    @pytest.mark.asyncio
    async def test_top_seed_priority(self, db):
        """Хаб с максимальным degree идёт первым; degree в JSON сохранён."""
        ids = [await _node(db, 1, f"n{i}") for i in range(4)]
        for s, d in ((0, 1), (0, 2), (0, 3), (1, 2)):
            await _edge(db, ids[s], ids[d])
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=2)
        assert snap["nodes"][0]["id"] == ids[0]
        assert snap["nodes"][0]["degree"] == 3
        # сиды (0 и 1) стоят перед соседями с тем же degree
        assert snap["nodes"][1]["id"] == ids[1]
        assert snap["nodes"][1]["degree"] == 2
        assert snap["truncated"] is False
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_neighbourhood_and_other_component_dropped(self, db):
        """Соседи сида включены; компонента, не касающаяся сидов, отсечена."""
        a0 = await _node(db, 1, "a0")
        a1 = await _node(db, 1, "a1")
        a2 = await _node(db, 1, "a2")
        for s, d in ((a0, a1), (a0, a2), (a1, a2)):
            await _edge(db, s, d)
        b0 = await _node(db, 1, "b0")
        b1 = await _node(db, 1, "b1")
        await _edge(db, b0, b1)
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        got = _ids(snap)
        assert {a0, a1, a2} <= got
        assert b0 not in got and b1 not in got
        assert len(snap["edges"]) == 3
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_isolated_node_degree_zero_absent(self, db):
        """Узел без рёбер вообще (degree=0) в выборку не попадает."""
        a = await _node(db, 1, "a")
        b = await _node(db, 1, "b")
        lone = await _node(db, 1, "lone")
        await _edge(db, a, b)
        snap = await db.graph_snapshot(chat_id=1)
        assert lone not in _ids(snap)
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_hidden_high_degree_not_seeded(self, db):
        """Follow-up R10.15-8: скрытый узел (пустое имя) с высоким degree не
        занимает слот сида — сидируется топ по ВИДИМЫМ узлам."""
        a = await _node(db, 1, "A")
        b = await _node(db, 1, "B")
        await _edge(db, a, b)
        hidden = await _node(db, 1, "")          # скрыт (пустое имя)
        xs = [await _node(db, 1, f"x{i}") for i in range(3)]
        for x in xs:
            await _edge(db, hidden, x)
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        assert {a, b} <= _ids(snap)
        _assert_connected(snap)


class TestOrphansAndDangling:
    @pytest.mark.asyncio
    async def test_orphan_removed_when_only_edge_hidden(self, db):
        """Узел с degree≥1 в базе, но единственное ребро ведёт к узлу без
        entity_name → узел-сирота удаляется из JSON."""
        visible = await _node(db, 1, "видный")
        hidden = await _node(db, 1, "")   # пустое имя — отфильтровано из nodes
        await _edge(db, visible, hidden)
        snap = await db.graph_snapshot(chat_id=1)
        assert snap["nodes"] == []
        assert snap["edges"] == []
        assert snap["truncated"] is True
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_no_dangling_edges(self, db):
        """Ребро к «скрытому» узлу не отдаётся; остальные рёбра замкнуты."""
        v1 = await _node(db, 1, "v1")
        v2 = await _node(db, 1, "v2")
        hidden = await _node(db, 1, "")
        await _edge(db, v1, v2)
        await _edge(db, v2, hidden)
        snap = await db.graph_snapshot(chat_id=1)
        assert _ids(snap) == {v1, v2}
        assert len(snap["edges"]) == 1
        assert snap["edges"][0]["from"] in (v1, v2)
        _assert_connected(snap)


class TestCapsAndEmpty:
    @pytest.mark.asyncio
    async def test_empty_db(self, db):
        snap = await db.graph_snapshot(chat_id=1)
        assert snap == {"nodes": [], "edges": [], "truncated": False}

    @pytest.mark.asyncio
    async def test_cap_and_truncated(self, db):
        """>max_nodes кандидатов → len(nodes) ≤ cap и truncated True.
        F3: явно задаём старый cap — проверяем механику отсечения."""
        hub = await _node(db, 1, "hub")
        for i in range(130):
            leaf = await _node(db, 1, f"leaf{i}")
            await _edge(db, hub, leaf)
        snap = await db.graph_snapshot(chat_id=1, max_nodes=120, max_edges=240)
        assert len(snap["nodes"]) == 120
        assert len(snap["edges"]) <= 240
        assert snap["truncated"] is True
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_edge_cap_creates_orphans(self, db):
        """Ребро-cap отрезает связи узла → узел становится сиротой и удаляется."""
        hub = await _node(db, 1, "hub")
        leaves = [await _node(db, 1, f"l{i}") for i in range(4)]
        for leaf in leaves:
            await _edge(db, hub, leaf)
        snap = await db.graph_snapshot(chat_id=1, max_edges=1)
        assert len(snap["edges"]) == 1
        # остаются только концы единственного оставшегося ребра
        assert len(snap["nodes"]) == 2
        assert snap["truncated"] is True
        _assert_connected(snap)


class TestScopeAndOrigin:
    @pytest.mark.asyncio
    async def test_chat_scope(self, db):
        """chat_id-скоуп: узлы/рёбра второго чата не протекают."""
        c1 = [await _node(db, 1, f"c1_{i}") for i in range(3)]
        for s, d in ((0, 1), (1, 2)):
            await _edge(db, c1[s], c1[d])
        c2 = [await _node(db, 2, f"c2_{i}") for i in range(3)]
        for s, d in ((0, 1), (1, 2)):
            await _edge(db, c2[s], c2[d])
        snap = await db.graph_snapshot(chat_id=1)
        got = _ids(snap)
        assert got == set(c1)
        assert not set(c2) & got
        assert all(n["degree"] == (1 if n["id"] in (c1[0], c1[2]) else 2)
                   for n in snap["nodes"])
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_bot_direct_reply_excluded(self, db):
        """Рёбра origin='bot_direct_reply' не считаются в degree и не отдаются."""
        a = await _node(db, 1, "a")
        b = await _node(db, 1, "b")
        c = await _node(db, 1, "c")
        await _edge(db, a, b)
        await _edge(db, a, c, origin="bot_direct_reply")
        snap = await db.graph_snapshot(chat_id=1)
        assert _ids(snap) == {a, b}
        assert c not in _ids(snap)
        deg = {n["id"]: n["degree"] for n in snap["nodes"]}
        assert deg[a] == 1 and deg[b] == 1
        assert len(snap["edges"]) == 1
        _assert_connected(snap)


class TestApi:
    @pytest.mark.asyncio
    async def test_api_limits_and_seed_passed(self, db, monkeypatch):
        from web.api import memory_agi as ma
        captured = {}

        real = db.graph_snapshot

        async def _spy(**kwargs):
            captured.update(kwargs)
            return await real(**kwargs)

        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        monkeypatch.setattr(db, "graph_snapshot", _spy)
        a = await _node(db, 1, "a")
        b = await _node(db, 1, "b")
        await _edge(db, a, b)
        snap = await ma.memory_graph(request=None, user=None, chat_id=1)
        assert snap["limits"] == {"nodes": ma.GRAPH_MAX_NODES,
                                  "edges": ma.GRAPH_MAX_EDGES}
        # F3 (T-1728/T-1731, ADR-1018-3 D5): seeds 150, cap 800/2400.
        assert captured["seed_nodes"] == ma.GRAPH_SEED_NODES == 150
        assert captured["max_nodes"] == 800 and captured["max_edges"] == 2400
        assert _ids(snap) == {a, b}

    @pytest.mark.asyncio
    async def test_api_fail_open(self, monkeypatch):
        from web.api import memory_agi as ma

        class _Boom:
            async def graph_snapshot(self, **kwargs):
                raise RuntimeError("db down")

        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _Boom())
        snap = await ma.memory_graph(request=None, user=None, chat_id=None)
        assert snap["nodes"] == [] and snap["edges"] == []
        assert snap["truncated"] is False
        assert snap["limits"] == {"nodes": ma.GRAPH_MAX_NODES,
                                  "edges": ma.GRAPH_MAX_EDGES}


class TestMarkers:
    def test_db_uses_indexed_cte_no_correlated_count(self):
        src = _read("services/database.py")
        # F3: дефолт сидов — 150 (ADR-1018-3 D5).
        assert "seed_nodes: int = 150" in src
        assert "WITH re AS (" in src
        assert "GROUP BY nid" in src
        assert "origin != 'bot_direct_reply'" in src
        # старый коррелированный COUNT(*) на узел устранён
        assert ("(SELECT COUNT(*) FROM edges e " not in src)

    def test_api_constant_present(self):
        src = _read("web/api/memory_agi.py")
        assert "GRAPH_SEED_NODES = 150" in src
        assert "seed_nodes=GRAPH_SEED_NODES" in src

    @pytest.mark.asyncio
    async def test_snapshot_no_secrets(self, db):
        import json
        a = await _node(db, 1, "a")
        b = await _node(db, 1, "b")
        await _edge(db, a, b)
        blob = json.dumps(await db.graph_snapshot(chat_id=1)).lower()
        assert not any(bad in blob for bad in
                       ("api_key", "base_url", "embedding", "secret"))
