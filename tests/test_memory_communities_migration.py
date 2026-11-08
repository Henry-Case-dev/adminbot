"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-07 (волна 1) — миграция `v44`.

Проверяются реальные контрактные пункты `plans/features/memory-cognitive-02/
contracts.md` §5.1 и §6 (инертность):

* `v44` — единственный новый шаг для сообществ: на свежей БД создаются
  `mca_community_builds` и `mca_community_members` + индексы, `user_version`
  заканчивается на `44`, реестр шагов совпадает с фактической головой;
* повторный прогон шага и повторный старт — no-op (DDL только
  `CREATE ... IF NOT EXISTS`), версия не растёт, строки не теряются;
* апгрейд существующей БД `v43` доводит её до `44`, не меняя данные `v43`
  (`mca_entity_canonical`) и не трогая `nodes`/`edges`/`graph_facts`;
* колонки/индексы обеих таблиц — ровно контрактные;
* шаг инертен: миграция ничего не backfill'ит, обычные писатели памяти не
  пишут в таблицы сообществ (гейт `MCA_MEMORY_COMMUNITIES_ENABLED` — волна 2).

TEST-LIFECYCLE: CONTRACT owner=MEMORY-07 (contracts §5.1, C-6)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services import entity_resolver as er
from services import memory_communities as mcomm
from services.database import DatabaseService

CHAT = -1001777000777
UID_A = 428494

BUILD_COLUMNS = (
    "build_id", "chat_id", "algorithm", "algorithm_version", "params_json",
    "graph_revision", "node_count", "edge_count", "prev_build_id",
    "change_summary_json", "status", "started_at", "finished_at",
)
MEMBER_COLUMNS = (
    "chat_id", "build_id", "community_id", "node_id", "member_weight",
    "created_at",
)
BUILD_INDEXES = (
    "idx_mca_community_builds_chat_status",
)
MEMBER_INDEXES = (
    "idx_mca_community_members_node",
    "idx_mca_community_members_community",
)


class _V43EraService(DatabaseService):
    """Раннер эпохи v43: шага v44 ещё нет (симуляция апгрейда)."""

    @staticmethod
    def migration_steps():
        return [s for s in DatabaseService.migration_steps()
                if s.version < 44]


async def _user_version(db) -> int:
    cursor = await db.db.execute("PRAGMA user_version")
    return int((await cursor.fetchone())[0])


async def _schema_objects(db, table: str) -> dict[str, str]:
    cursor = await db.db.execute(
        "SELECT name, type FROM sqlite_master WHERE tbl_name = ? "
        "ORDER BY type, name", (table,))
    return {row["name"]: row["type"] for row in await cursor.fetchall()}


async def _columns(db, table: str) -> list[str]:
    cursor = await db.db.execute(f"PRAGMA table_info({table})")
    return [row["name"] for row in await cursor.fetchall()]


async def _row_count(db, table: str) -> int:
    cursor = await db.db.execute(f"SELECT COUNT(*) AS n FROM {table}")
    return int((await cursor.fetchone())["n"])


async def _v43_row(db, member_node_id: int) -> list:
    cursor = await db.db.execute(
        f"SELECT * FROM {er.ENTITY_CANONICAL_TABLE} WHERE chat_id = ? "
        "AND entity_type = ? AND member_node_id = ?",
        (CHAT, "user", member_node_id))
    row = await cursor.fetchone()
    return list(row) if row is not None else []


# ── реестр шагов ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v44_registered_as_next_step_after_v43():
    steps = {s.version: s.name for s in DatabaseService.migration_steps()}
    assert steps[43] == er.ENTITY_CANONICAL_MIGRATION_STEP_NAME   # v43 не тронут
    assert steps[44] == mcomm.COMMUNITIES_MIGRATION_STEP_NAME
    assert max(steps) == 44                                        # голова
    assert callable(DatabaseService._migrate_communities_v44)


# ── свежая БД ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v44_fresh_db_creates_contract_tables_and_columns(tmp_path):
    svc = DatabaseService(str(tmp_path / "v44_fresh.db"))
    await svc.initialize()
    try:
        assert await _user_version(svc) == 44
        assert 44 == max(s.version for s in DatabaseService.migration_steps())

        objects = await _schema_objects(svc, mcomm.COMMUNITY_BUILDS_TABLE)
        assert objects.get(mcomm.COMMUNITY_BUILDS_TABLE) == "table"
        for name in BUILD_INDEXES:
            assert objects.get(name) == "index", name

        objects = await _schema_objects(svc, mcomm.COMMUNITY_MEMBERS_TABLE)
        assert objects.get(mcomm.COMMUNITY_MEMBERS_TABLE) == "table"
        for name in MEMBER_INDEXES:
            assert objects.get(name) == "index", name

        assert await _columns(svc, mcomm.COMMUNITY_BUILDS_TABLE) == \
            list(BUILD_COLUMNS)
        assert await _columns(svc, mcomm.COMMUNITY_MEMBERS_TABLE) == \
            list(MEMBER_COLUMNS)

        # Контрактные дефолты (§5.1), а не «похожие» значения.
        cursor = await svc.db.execute(
            f"PRAGMA table_info({mcomm.COMMUNITY_BUILDS_TABLE})")
        defaults = {row["name"]: row["dflt_value"]
                    for row in await cursor.fetchall()}
        assert defaults["params_json"] == "'{}'"
        assert defaults["change_summary_json"] == "'{}'"
        cursor = await svc.db.execute(
            f"PRAGMA table_info({mcomm.COMMUNITY_MEMBERS_TABLE})")
        defaults = {row["name"]: row["dflt_value"]
                    for row in await cursor.fetchall()}
        assert defaults["member_weight"] == "1.0"

        # Миграция ничего не выдумывает: обе таблицы пусты.
        assert await _row_count(svc, mcomm.COMMUNITY_BUILDS_TABLE) == 0
        assert await _row_count(svc, mcomm.COMMUNITY_MEMBERS_TABLE) == 0

        cursor = await svc.db.execute(
            "SELECT name FROM schema_migrations WHERE version = 44")
        assert [row["name"] for row in await cursor.fetchall()] == \
            [mcomm.COMMUNITIES_MIGRATION_STEP_NAME]
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_v44_repeat_run_is_noop_and_keeps_rows(tmp_path):
    svc = DatabaseService(str(tmp_path / "v44_noop.db"))
    await svc.initialize()
    try:
        await svc.db.execute(
            f"INSERT INTO {mcomm.COMMUNITY_BUILDS_TABLE} (build_id, chat_id, "
            "algorithm, algorithm_version, graph_revision, node_count, "
            "edge_count, status, started_at) "
            "VALUES ('b1', ?, 'louvain', '1', 'rev1', 2, 1, 'active', 100)",
            (CHAT,))
        await svc.db.execute(
            f"INSERT INTO {mcomm.COMMUNITY_MEMBERS_TABLE} (chat_id, build_id, "
            "community_id, node_id, created_at) VALUES (?, 'b1', 'c1', 1, 100)",
            (CHAT,))
        await svc.db.commit()
        book_before = await _row_count(svc, "schema_migrations")

        objects_before = await _schema_objects(
            svc, mcomm.COMMUNITY_BUILDS_TABLE)

        # Прямой повтор шага (как это делает раннер при частичном DDL).
        await svc._migrate_communities_v44()
        await svc._migrate_communities_v44()

        assert await _user_version(svc) == 44
        assert await _row_count(svc, "schema_migrations") == book_before
        assert await _row_count(svc, mcomm.COMMUNITY_BUILDS_TABLE) == 1
        assert await _row_count(svc, mcomm.COMMUNITY_MEMBERS_TABLE) == 1
        assert await _schema_objects(svc, mcomm.COMMUNITY_BUILDS_TABLE) == \
            objects_before
    finally:
        await svc.close()

    # Повторный старт полного раннера: шаг уже применён, книга не растёт.
    reopened = DatabaseService(str(tmp_path / "v44_noop.db"))
    await reopened.initialize()
    try:
        assert await _user_version(reopened) == 44
        assert await _row_count(reopened, "schema_migrations") == book_before
        assert await _row_count(reopened, mcomm.COMMUNITY_BUILDS_TABLE) == 1
    finally:
        await reopened.close()


# ── апгрейд существующей v43-БД ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v44_upgrades_v43_db_without_touching_v43_data(tmp_path):
    path = tmp_path / "v43.db"
    old = _V43EraService(str(path))
    await old.initialize()
    try:
        assert await _user_version(old) == 43
        papa = await old.upsert_node(CHAT, "Папаха", "user")
        alex = await old.upsert_node(CHAT, "Александр", "user")
        await old.upsert_edge(papa, alex, "знает", fact_id=None)
        await old.insert_graph_fact(CHAT, "базовый факт", "chat_history", None)
        await old.db.execute(
            f"INSERT INTO {er.ENTITY_CANONICAL_TABLE} (chat_id, entity_type, "
            "member_node_id, canonical_node_id, resolution, stable_kind, "
            "stable_value, method, evidence_ref_id, confidence, status, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (CHAT, "user", papa, papa, er.RESOLUTION_SELF,
             er.STABLE_KIND_TG_USER, str(UID_A), er.METHOD_ALIAS_MAP, None,
             er.CONFIDENCE_CONFIRMED, er.STATUS_ACTIVE, 1, 1))
        await old.db.commit()
        v43_row_before = await _v43_row(old, papa)
        nodes_before = await _row_count(old, "nodes")
        edges_before = await _row_count(old, "edges")
        facts_before = await _row_count(old, "graph_facts")
        assert v43_row_before and nodes_before == 2 and facts_before == 1
        # До апгрейда таблиц сообществ нет вовсе (эпоха v43).
        cursor = await old.db.execute(
            "SELECT name FROM sqlite_master WHERE name IN (?, ?)",
            (mcomm.COMMUNITY_BUILDS_TABLE, mcomm.COMMUNITY_MEMBERS_TABLE))
        assert await cursor.fetchall() == []
    finally:
        await old.close()

    upgraded = DatabaseService(str(path))
    await upgraded.initialize()
    try:
        assert await _user_version(upgraded) == 44
        # Данные v43 и графа не тронуты (ни ALTER, ни UPDATE/DELETE).
        assert await _v43_row(upgraded, papa) == v43_row_before
        assert await _row_count(upgraded, "nodes") == nodes_before
        assert await _row_count(upgraded, "edges") == edges_before
        assert await _row_count(upgraded, "graph_facts") == facts_before
        # Новые таблицы добавлены пустыми: бэкфилла миграцией нет.
        assert await _row_count(upgraded, mcomm.COMMUNITY_BUILDS_TABLE) == 0
        assert await _row_count(upgraded, mcomm.COMMUNITY_MEMBERS_TABLE) == 0
        cursor = await upgraded.db.execute("PRAGMA integrity_check")
        assert (await cursor.fetchone())[0] == "ok"
        assert list(Path(tmp_path).glob("pre_migration_*.db")), \
            "backup-guard до миграции не сработал"
    finally:
        await upgraded.close()

    # Повторный старт после апгрейда — no-op, версия остаётся 44.
    reopened = DatabaseService(str(path))
    await reopened.initialize()
    try:
        assert await _user_version(reopened) == 44
        assert await _v43_row(reopened, papa) == v43_row_before
    finally:
        await reopened.close()


# ── инертность (гейт OFF: таблицы есть, их никто не читает/не пишет) ───────

@pytest.mark.asyncio
async def test_v44_tables_stay_empty_for_ordinary_memory_writes(tmp_path):
    svc = DatabaseService(str(tmp_path / "v44_inert.db"))
    await svc.initialize()
    try:
        papa = await svc.upsert_node(CHAT, "Папаха", "user")
        alex = await svc.upsert_node(CHAT, "Александр", "user")
        await svc.upsert_edge(papa, alex, "знает", fact_id=None)
        await svc.insert_graph_fact(CHAT, "обычный факт", "chat_history", None)
        await svc.db.commit()

        # Обычные писатели памяти таблиц сообществ не касаются (волна 2 —
        # сборка/lifecycle за гейтом MCA_MEMORY_COMMUNITIES_ENABLED).
        assert await _row_count(svc, "nodes") == 2
        assert await _row_count(svc, "graph_facts") == 1
        assert await _row_count(svc, mcomm.COMMUNITY_BUILDS_TABLE) == 0
        assert await _row_count(svc, mcomm.COMMUNITY_MEMBERS_TABLE) == 0
    finally:
        await svc.close()
