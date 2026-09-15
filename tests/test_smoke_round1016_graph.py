"""Смоук раунда 10.16 (T-1646) — graph (умная выборка) «имитация реальной работы».

In-process: реальный `DatabaseService(":memory:")`, реальный `graph_snapshot`
и API-обёртка `web.api.memory_agi.memory_graph` (замокан только auth/DI).
Проверяются скоринг по **Σ importance** (F3 раунда 10.18, ADR-1018-3;
SUPERSEDE ADR-1015-2 — Degree Centrality), раскрытие смежных, отсечение
сирот, cap после раскрытия и контракт `nodes/edges/truncated/limits`.
"""
import json

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db():
    from services.database import DatabaseService
    d = DatabaseService(":memory:")
    await d.initialize()
    yield d
    await d.close()


async def _node(db, chat_id, name, etype="user"):
    return await db.upsert_node(chat_id, name, etype)


async def _edge(db, src, dst, rel="связь", origin="chat_history", weight=1):
    await db.upsert_edge(src, dst, rel, weight_increment=weight, origin=origin)


def _ids(snap):
    return {n["id"] for n in snap["nodes"]}


def _connected(snap):
    ids = _ids(snap)
    touch = set()
    for e in snap["edges"]:
        assert e["from"] in ids and e["to"] in ids
        touch.add(e["from"])
        touch.add(e["to"])
    assert all(n["id"] in touch for n in snap["nodes"])


class TestGraphSnapshotSmoke:
    @pytest.mark.asyncio
    async def test_centrality_cluster_and_orphans(self, db):
        hub = await _node(db, 1, "Хаб")
        leaves = [await _node(db, 1, f"Лист{i}") for i in range(4)]
        for leaf in leaves:
            await _edge(db, hub, leaf)
        lone = await _node(db, 1, "Одиночка")           # degree 0
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        assert snap["nodes"][0]["id"] == hub
        assert snap["nodes"][0]["degree"] == 4
        assert lone not in _ids(snap)
        _connected(snap)

    @pytest.mark.asyncio
    async def test_other_component_dropped(self, db):
        a = [await _node(db, 1, f"a{i}") for i in range(3)]
        for s, d in ((0, 1), (0, 2), (1, 2)):
            await _edge(db, a[s], a[d])
        b0 = await _node(db, 1, "b0")
        b1 = await _node(db, 1, "b1")
        await _edge(db, b0, b1)
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        assert {a[0], a[1], a[2]} <= _ids(snap)
        assert b0 not in _ids(snap) and b1 not in _ids(snap)
        _connected(snap)

    @pytest.mark.asyncio
    async def test_cap_after_expansion_truncated(self, db):
        hub = await _node(db, 1, "hub")
        for i in range(130):
            leaf = await _node(db, 1, f"leaf{i}")
            await _edge(db, hub, leaf)
        # F3: cap поднят до 800/2400; отсечение проверяем явным cap.
        snap = await db.graph_snapshot(chat_id=1, max_nodes=120)
        assert len(snap["nodes"]) <= 120
        assert snap["truncated"] is True
        _connected(snap)

    @pytest.mark.asyncio
    async def test_chat_scope_and_secrets(self, db):
        c1 = [await _node(db, 1, f"c1_{i}") for i in range(3)]
        await _edge(db, c1[0], c1[1])
        await _edge(db, c1[1], c1[2])
        c2 = [await _node(db, 2, f"c2_{i}") for i in range(3)]
        await _edge(db, c2[0], c2[1])
        snap = await db.graph_snapshot(chat_id=1)
        assert _ids(snap) == set(c1)
        blob = json.dumps(snap).lower()
        assert not any(bad in blob for bad in ("api_key", "base_url", "secret"))


class TestGraphApiSmoke:
    @pytest.mark.asyncio
    async def test_api_contract_with_real_db(self, db, monkeypatch):
        from web.api import memory_agi as ma
        a = await _node(db, 1, "A")
        b = await _node(db, 1, "B")
        await _edge(db, a, b)
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        snap = await ma.memory_graph(request=None, user=None, chat_id=1)
        assert snap["limits"] == {"nodes": ma.GRAPH_MAX_NODES,
                                  "edges": ma.GRAPH_MAX_EDGES}
        # F3 (ADR-1018-3 D5): плотность — cap 800/2400, seeds 150.
        assert snap["limits"]["nodes"] == 800
        assert snap["limits"]["edges"] == 2400
        assert _ids(snap) == {a, b}
        assert len(snap["edges"]) == 1

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
