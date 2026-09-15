"""Раунд 10.18 (F3 `graph-density-scoring-stoplist`, ADR-1018-3) — скоринг графа
по Σ importance, STOP_LIST центров, ×2 за Убеждение/Парадигму и миграция v10.

Покрытие:
  * миграция SQLite v9→v10: fresh/legacy, идемпотентность, индекс, user_version;
  * ранжирование по Σ importance (а не degree) + legacy NULL → weight;
  * STOP_LIST центров (мета-узел — периферия, не центр);
  * ×2 для узла-участника Убеждения/Парадигмы;
  * запись `edges.fact_id` (memorize / upsert) и COALESCE при конфликте;
  * единый модуль `services.graph_stoplist` + API-константы F3.
"""
import asyncio
import sqlite3
import time

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db():
    from services.database import DatabaseService
    d = DatabaseService(":memory:")
    await d.initialize()
    yield d
    await d.close()


def _ids(snap):
    return {n["id"] for n in snap["nodes"]}


def _assert_connected(snap):
    ids = _ids(snap)
    assert all(e["from"] in ids and e["to"] in ids for e in snap["edges"])
    touch = {e["from"] for e in snap["edges"]} | {e["to"] for e in snap["edges"]}
    assert all(n["id"] in touch for n in snap["nodes"])


async def _node(db, chat_id, name, etype="user"):
    return await db.upsert_node(chat_id, name, etype)


async def _edge(db, src, dst, rel="связь", origin="chat_history", weight=1,
                fact_id=None):
    await db.upsert_edge(src, dst, rel, weight_increment=weight, origin=origin,
                         fact_id=fact_id)


async def _fact(db, chat_id, text, importance, *, kind="fact",
                belief_meta=None):
    return await db.insert_graph_fact(
        chat_id, text, "chat_history", None, importance=importance,
        kind=kind, belief_meta=belief_meta)


# ── миграция v9 → v10 ───────────────────────────────────────────────────────

class TestMigrationV10:
    @pytest.mark.asyncio
    async def test_fresh_db_has_fact_id_index_and_version(self, db):
        cols = {r["name"] for r in await (await db.db.execute(
            "PRAGMA table_info(edges)")).fetchall()}
        assert "fact_id" in cols
        idx = (await (await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_edges_fact_id'")).fetchone())
        assert idx is not None
        assert (await (await db.db.execute(
            "PRAGMA user_version")).fetchone())[0] == 10

    @pytest.mark.asyncio
    async def test_legacy_edges_are_migrated_preserving_rows(self, tmp_path):
        """Старая edges без fact_id → initialize добавляет колонку+индекс,
        строки сохраняются, legacy fact_id = NULL (осознанно)."""
        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(path))
        conn.executescript(
            "CREATE TABLE nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "chat_id INTEGER NOT NULL, entity_name TEXT NOT NULL, "
            "entity_type TEXT NOT NULL, origin TEXT NOT NULL DEFAULT "
            "'chat_history', expires_at INTEGER, UNIQUE(chat_id, entity_name));"
            "CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "chat_id INTEGER NOT NULL, source_id INTEGER NOT NULL, "
            "target_id INTEGER NOT NULL, relation_type TEXT NOT NULL, "
            "weight INTEGER NOT NULL DEFAULT 1, "
            "last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "origin TEXT NOT NULL DEFAULT 'chat_history', expires_at INTEGER, "
            "UNIQUE(source_id, target_id, relation_type));"
            "INSERT INTO nodes (chat_id, entity_name, entity_type) "
            "VALUES (1, 'a', 'user'), (1, 'b', 'user');"
            "INSERT INTO edges (chat_id, source_id, target_id, relation_type) "
            "VALUES (1, 1, 2, 'rel');"
            "PRAGMA user_version = 9;")
        conn.commit()
        conn.close()

        from services.database import DatabaseService
        d = DatabaseService(str(path))
        await d.initialize()
        try:
            cols = {r["name"] for r in await (await d.db.execute(
                "PRAGMA table_info(edges)")).fetchall()}
            assert "fact_id" in cols
            row = await (await d.db.execute(
                "SELECT fact_id FROM edges WHERE relation_type='rel'")).fetchone()
            assert row is not None and row["fact_id"] is None
            assert (await (await d.db.execute(
                "PRAGMA user_version")).fetchone())[0] == 10
            # idempotent re-init — no-op (guard по table_info)
            await d.close()
            await d.initialize()
            assert (await (await d.db.execute(
                "SELECT COUNT(*) AS c FROM edges")).fetchone())["c"] == 1
            assert (await (await d.db.execute(
                "PRAGMA user_version")).fetchone())[0] == 10
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_fts_survives_migration(self, tmp_path):
        """FTS-хит по id факта валиден после v10 (graph_facts не трогается)."""
        path = tmp_path / "fts.db"
        conn = sqlite3.connect(str(path))
        conn.executescript(
            "CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "chat_id INTEGER NOT NULL, source_id INTEGER NOT NULL, "
            "target_id INTEGER NOT NULL, relation_type TEXT NOT NULL, "
            "weight INTEGER NOT NULL DEFAULT 1, "
            "last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "origin TEXT NOT NULL DEFAULT 'chat_history', expires_at INTEGER, "
            "UNIQUE(source_id, target_id, relation_type));"
            "PRAGMA user_version = 9;")
        conn.commit()
        conn.close()
        from services.database import DatabaseService
        d = DatabaseService(str(path))
        await d.initialize()
        try:
            fid = await d.insert_graph_fact(1, "уникальный факт про бобра",
                                            "chat_history", None, importance=6)
            found = await d.search_graph_facts_fts(
                1, '"бобра"*', 5, int(time.time()) + 10)
            assert any(r["id"] == fid for r in found)
        finally:
            await d.close()


# ── скоринг: Σ importance ───────────────────────────────────────────────────

class TestSumImportanceScoring:
    @pytest.mark.asyncio
    async def test_high_importance_beats_higher_degree(self, db):
        """Узел с ОДНИМ важным фактом (importance 10) обыгрывает хаб из 3
        рёбер (score 3) — сортировка НЕ по degree."""
        a1 = await _node(db, 1, "a1")
        a2 = await _node(db, 1, "a2")
        fid = await _fact(db, 1, "a1 важен для a2", 10)
        await _edge(db, a1, a2, fact_id=fid)
        b1 = await _node(db, 1, "b1")
        for i in range(3):
            leaf = await _node(db, 1, f"b_leaf{i}")
            await _edge(db, b1, leaf)
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        got = _ids(snap)
        assert {a1, a2} <= got, "важный факт должен вывести компоненту в сиды"
        assert b1 not in got, "хаб с degree 3 проигрывает Σ importance 10"
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_legacy_null_fact_id_degrades_to_weight(self, db):
        """Legacy-ребро (fact_id NULL) → importance = weight; ребро с weight 5
        обыгрывает хаб из 3 рёбер weight 1."""
        x = await _node(db, 1, "x")
        y = await _node(db, 1, "y")
        await _edge(db, x, y, weight=5)            # legacy (fact_id NULL)
        hub = await _node(db, 1, "hub")
        for i in range(3):
            leaf = await _node(db, 1, f"leaf{i}")
            await _edge(db, hub, leaf)
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        got = _ids(snap)
        assert {x, y} <= got
        assert hub not in got
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_degree_metric_preserved(self, db):
        """degree — отдельная метрика (фронт `_graphSignature`) — сохранён."""
        hub = await _node(db, 1, "hub")
        for i in range(3):
            leaf = await _node(db, 1, f"leaf{i}")
            await _edge(db, hub, leaf)
        snap = await db.graph_snapshot(chat_id=1)
        deg = {n["id"]: n["degree"] for n in snap["nodes"]}
        assert deg[hub] == 3


# ── STOP_LIST центров ───────────────────────────────────────────────────────

class TestCenterStoplist:
    @pytest.mark.asyncio
    async def test_stopword_not_center_but_periphery(self, db):
        """Мета-узел «видеосообщение» с высоким score НЕ выбирается центром,
        но остаётся в графе как периферия соседнего сида."""
        stop = await _node(db, 1, "видеосообщение")
        for i in range(3):
            leaf = await _node(db, 1, f"s_leaf{i}")
            await _edge(db, stop, leaf, weight=1)   # stop score 3 > листья 1
        good = await _node(db, 1, "нормальная_тема")
        bro = await _node(db, 1, "сосед")
        await _edge(db, good, bro, weight=1)
        await _edge(db, good, stop, weight=1)       # stopword — периферия good
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        got = _ids(snap)
        assert good in got and bro in got
        # stopword — не центр: его эксклюзивные листья не попали в граф...
        assert not any(f"s_leaf{i}" in got for i in range(3))
        # ...но сам он остаётся периферией (сосед сида).
        assert stop in got
        _assert_connected(snap)


# ── ×2 за Убеждение/Парадигму ───────────────────────────────────────────────

class TestBeliefMultiplier:
    @pytest.mark.asyncio
    async def test_belief_participant_gets_x2(self, db):
        tema = await _node(db, 1, "тема")
        vasya = await _node(db, 1, "вася")
        fid = await _fact(db, 1, "тема важна для васи", 4)
        await _edge(db, tema, vasya, fact_id=fid)   # тема score 4
        petya = await _node(db, 1, "петя")
        p2 = await _node(db, 1, "петя_два")
        fid2 = await _fact(db, 1, "петя молодец", 5)
        await _edge(db, petya, p2, fact_id=fid2)    # петя score 5
        await _fact(db, 1, "тема всегда права", 7, kind="belief")
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        got = _ids(snap)
        assert tema in got, "×2 выводит участника убеждения в топ (4→8 > 5)"
        assert petya not in got
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_paradigm_marker_also_gets_x2(self, db):
        para = await _node(db, 1, "парадигма_х")
        other = await _node(db, 1, "друг")
        fid = await _fact(db, 1, "парадигма_х связана с друг", 4)
        await _edge(db, para, other, fact_id=fid)
        rival = await _node(db, 1, "соперник")
        r2 = await _node(db, 1, "соперник_2")
        fid2 = await _fact(db, 1, "соперник впереди", 5)
        await _edge(db, rival, r2, fact_id=fid2)
        await _fact(db, 1, "парадигма_х держит мир", 8, kind="belief",
                    belief_meta='{"type":"paradigm"}')
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        got = _ids(snap)
        assert para in got
        assert rival not in got

    @pytest.mark.asyncio
    async def test_substring_does_not_grant_x2(self, db):
        """B3-4: «тема» — ПОДСТРОКА «система», но ×2 НЕ получает (границы
        токенов): соперник со score 5 обыгрывает тему со score 4."""
        tema = await _node(db, 1, "тема")
        other = await _node(db, 1, "рядом")
        fid = await _fact(db, 1, "тема рядом", 4)
        await _edge(db, tema, other, fact_id=fid)        # тема score 4
        rival = await _node(db, 1, "соперник")
        r2 = await _node(db, 1, "соперник_2")
        fid2 = await _fact(db, 1, "соперник важен", 5)
        await _edge(db, rival, r2, fact_id=fid2)         # соперник score 5
        # «тема» входит в «система» как подстрока — ×2 быть НЕ должно
        await _fact(db, 1, "система всегда права", 9, kind="belief")
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        got = _ids(snap)
        assert rival in got, "соперник (5) > тема (4×1): ×2 от «система» не применён"
        assert tema not in got, "подстрочный матч не даёт ×2"
        _assert_connected(snap)

    @pytest.mark.asyncio
    async def test_multiword_name_in_belief_gets_x2(self, db):
        """B3-4: многословное имя матчится по границам (позитивный кейс)."""
        person = await _node(db, 1, "тема дня")
        other = await _node(db, 1, "рядом")
        fid = await _fact(db, 1, "тема дня рядом", 4)
        await _edge(db, person, other, fact_id=fid)      # score 4
        rival = await _node(db, 1, "соперник")
        r2 = await _node(db, 1, "соперник_2")
        fid2 = await _fact(db, 1, "соперник важен", 5)
        await _edge(db, rival, r2, fact_id=fid2)         # score 5
        await _fact(db, 1, "тема дня всегда права", 7, kind="belief")
        snap = await db.graph_snapshot(chat_id=1, seed_nodes=1)
        got = _ids(snap)
        assert person in got, "×2 (4→8) выводит многословное имя в топ"
        assert rival not in got


# ── запись edges.fact_id ────────────────────────────────────────────────────

class TestFactIdWritePath:
    @pytest.mark.asyncio
    async def test_upsert_edge_persists_fact_id(self, db):
        a = await _node(db, 1, "a")
        b = await _node(db, 1, "b")
        fid = await _fact(db, 1, "a связан с b", 6)
        await _edge(db, a, b, fact_id=fid)
        row = await (await db.db.execute(
            "SELECT fact_id FROM edges WHERE source_id=? AND target_id=?",
            (a, b))).fetchone()
        assert row["fact_id"] == fid

    @pytest.mark.asyncio
    async def test_conflict_with_null_keeps_existing_fact_id(self, db):
        """COALESCE(excluded.fact_id, edges.fact_id): повтор без fact_id не
        затирает уже записанный provenance."""
        a = await _node(db, 1, "a")
        b = await _node(db, 1, "b")
        fid = await _fact(db, 1, "a связан с b", 6)
        await _edge(db, a, b, fact_id=fid)
        await _edge(db, a, b)                       # fact_id=None (повтор)
        row = await (await db.db.execute(
            "SELECT fact_id FROM edges WHERE source_id=? AND target_id=?",
            (a, b))).fetchone()
        assert row["fact_id"] == fid

    @pytest.mark.asyncio
    async def test_upsert_edge_missing_source_warns_fail_open(self, db, caplog):
        """S10.18-33: отсутствующий узел-источник → ребро не пишется, но это
        больше не «молча»: WARNING; транзакция не ломается (fail-open)."""
        import logging
        with caplog.at_level(logging.WARNING):
            await db.upsert_edge(9999, 8888, "связь")
        assert any("upsert_edge" in r.getMessage() for r in caplog.records), \
            "отсутствие узла должно логироваться WARNING"
        cnt = (await (await db.db.execute(
            "SELECT COUNT(*) AS c FROM edges")).fetchone())["c"]
        assert cnt == 0

    @pytest.mark.asyncio
    async def test_memorize_writes_fact_id_on_edge(self, db, monkeypatch):
        """`_memorize_facts_inner`: порядок insert_graph_fact → upsert_edge
        (fact_id заполнен), а не наоборот."""
        from services.summary_memory import MemoryManager

        class _LLM:
            async def generate(self, messages):
                return '[{"subject":"Аня","predicate":"любит","object":"кофе"}]'

            async def embed(self, texts):
                raise AssertionError("embed не должен вызываться")

        memory = MemoryManager(db, _LLM())
        memory._vec_available = False
        await memory.memorize_facts(1, "аня любит кофе", "chat_history")
        row = await (await db.db.execute(
            "SELECT e.fact_id AS fid, f.id AS gid FROM edges e "
            "JOIN graph_facts f ON f.id = e.fact_id")).fetchone()
        assert row is not None and row["fid"] == row["gid"]

    @pytest.mark.asyncio
    async def test_fact_and_edge_are_atomic(self, db, monkeypatch):
        """B3-5: сбой второго шага (`upsert_edge`) откатывает незакоммиченный
        факт — «факта без ребра» не остаётся (единая транзакция fact+edge)."""
        from services.summary_memory import MemoryManager

        class _LLM:
            async def generate(self, messages):
                return '[{"subject":"Аня","predicate":"любит","object":"кофе"}]'

            async def embed(self, texts):
                raise AssertionError("embed не должен вызываться")

        memory = MemoryManager(db, _LLM())
        memory._vec_available = False

        async def _boom(*args, **kwargs):
            raise RuntimeError("edge write failed")

        monkeypatch.setattr(db, "upsert_edge", _boom)
        await memory.memorize_facts(1, "аня любит кофе", "chat_history")
        cnt = (await (await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts")).fetchone())["c"]
        assert cnt == 0, "факт не должен остаться без ребра после отката"


# ── плотность: итог 500–800 узлов (B3-2) ────────────────────────────────────

class TestDensityRange:
    @pytest.mark.asyncio
    async def test_representative_graph_yields_500_800_nodes(self, db):
        """B3-2: репрезентативный профиль — 150 сидов-центров, у каждого
        3–5 соседей (spec §6/R11; выбрано так, чтобы НЕусечённый результат
        попадал в 500–800). Проверяем гарантию плотности алгоритмом, а не
        cap-ом."""
        n_centers = 150
        leaves_total = 0
        for i in range(n_centers):
            center = await _node(db, 1, f"центр_{i:03d}")
            fid = await _fact(db, 1, f"центр_{i:03d} факт", 4)
            n_neighbors = 3 + (i % 3)          # 3 / 4 / 5
            for j in range(n_neighbors):
                leaf = await _node(db, 1, f"сосед_{i:03d}_{j}")
                await _edge(db, center, leaf, fact_id=fid)
            leaves_total += n_neighbors
        # B3-R3: не тавтология — сверяем ожидаемое число рёбер (150 × avg 4)
        # с РЕАЛЬНЫМ количеством строк в БД (профиль без усечения).
        edges_total = (await (await db.db.execute(
            "SELECT COUNT(*) AS c FROM edges")).fetchone())["c"]
        assert edges_total == leaves_total == 600
        snap = await db.graph_snapshot(chat_id=1)
        n = len(snap["nodes"])
        assert 500 <= n <= 800, f"плотность {n} вне диапазона 500–800"
        assert snap["truncated"] is False, "профиль не должен упираться в cap"
        _assert_connected(snap)


class TestGraphStoplistModule:
    def test_center_and_penalty_lists_differ(self):
        from services.graph_stoplist import (
            GRAPH_CENTER_STOPLIST as C, METAFACT_PENALTY_STOPLIST as P)
        assert "сообщение" in C and "сообщение" not in P
        assert "стикер" in P and "стикер" not in C

    def test_normalize_and_predicates(self):
        from services.graph_stoplist import (
            normalize_token, is_center_stopword, is_metafact_stopword)
        assert normalize_token("  «Видеосообщение»!  ") == "видеосообщение"
        assert normalize_token("КРУЖОЧЁК") == "кружочек"
        assert is_center_stopword("Ссылка.") is True
        assert is_center_stopword("Обычная тема") is False
        assert is_metafact_stopword("Стикер") is True
        assert is_metafact_stopword("сообщение") is False


class TestApiConstants:
    def test_round1018_limits(self):
        from web.api import memory_agi as ma
        assert ma.GRAPH_MAX_NODES == 800
        assert ma.GRAPH_MAX_EDGES == 2400
        assert ma.GRAPH_SEED_NODES == 150
