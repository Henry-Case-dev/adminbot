"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-07 — миграция `v44` и сборка сообществ.

Проверяются реальные контрактные пункты `plans/features/memory-cognitive-02/
contracts.md` §5.1 и §6 (инертность):

* `v44` — единственный новый шаг для сообществ: на свежей БД создаются
  `mca_community_builds` и `mca_community_members` + индексы, голова схемы
  (v45 = VMQ-V voice transcript) выше, реестр шагов совпадает с фактической
  головой;
* повторный прогон шага и повторный старт — no-op (DDL только
  `CREATE ... IF NOT EXISTS`), версия не растёт, строки не теряются;
* апгрейд существующей БД `v43` доводит её до головы схемы (`v44` + `v45`),
  не меняя данные `v43`
  (`mca_entity_canonical`) и не трогая `nodes`/`edges`/`graph_facts`;
* колонки/индексы обеих таблиц — ровно контрактные;
* шаг инертен: миграция ничего не backfill'ит, обычные писатели памяти не
  пишут в таблицы сообществ.

Волна 2 (C-6, §6): точные веса 1.0/0.5/0.25/0.1 через существующий
`classify_fact_provenance`, `mca_associations` всегда `cooccurrence`, членство
— канонический `nodes.id` (не Telegram UID), детерминированное разбиение,
жизненный цикл `building → active → superseded`/`failed`, атомарная
публикация, один `active` на чат, стабильность `community_id` и mapping
split/merge, отсутствие мутаций графа и записей вне двух таблиц сообществ.

TEST-LIFECYCLE: CONTRACT owner=MEMORY-07 (contracts §5.1, §6, C-6)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services import entity_resolver as er
from services import graphrag_provenance as gprov
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
    # Голова схемы выше v44 (v45 = VMQ-V voice transcript); пиним точно.
    assert max(steps) == 45
    assert callable(DatabaseService._migrate_communities_v44)


# ── свежая БД ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v44_fresh_db_creates_contract_tables_and_columns(tmp_path):
    svc = DatabaseService(str(tmp_path / "v44_fresh.db"))
    await svc.initialize()
    try:
        assert await _user_version(svc) == 45
        assert 45 == max(s.version for s in DatabaseService.migration_steps())

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

        # Прямой вызов шага фиксирует ЕГО версию (44), а не голову схемы:
        # голову (45) доводит только полный раннер — см. ниже.
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
        assert await _user_version(reopened) == 45
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
        assert await _user_version(upgraded) == 45
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

    # Повторный старт после апгрейда — no-op, версия остаётся 45 (голова).
    reopened = DatabaseService(str(path))
    await reopened.initialize()
    try:
        assert await _user_version(reopened) == 45
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


# ══ волна 2: сборщик, веса, жизненный цикл (C-6, §6) ═══════════════════════

# ── посев данных ───────────────────────────────────────────────────────────

async def _fact(db, *, subject=None, speaker=None, text="факт") -> int:
    """Факт с управляемой атрибуцией (её читает `classify_fact_provenance`)."""
    cursor = await db.db.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
        "subject_ref_id, speaker_author_id) "
        "VALUES (?, ?, 'chat_history', ?, ?, ?)",
        (CHAT, str(text), 1700000000, subject, speaker))
    await db.db.commit()
    return int(cursor.lastrowid)


async def _edge(db, source: int, target: int, relation: str = "знает",
                fact_id: int | None = None) -> None:
    await db.upsert_edge(source, target, relation, fact_id=fact_id)


async def _episode(db, episode_id: str, participants) -> None:
    await db.db.execute(
        "INSERT INTO mca_episodes (episode_id, chat_id, discovered_at, "
        "updated_at, participants_json, segment_key) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (episode_id, CHAT, 1700000000, 1700000000,
         json.dumps(list(participants), ensure_ascii=False), episode_id))
    await db.db.commit()


async def _association(db, association_id: str, a_episode: str,
                       b_episode: str, status: str = "candidate") -> None:
    await db.db.execute(
        "INSERT INTO mca_associations (association_id, chat_id, link_type, "
        "a_event_id, b_event_id, status, created_at, updated_at) "
        "VALUES (?, ?, 'analogy', ?, ?, ?, ?, ?)",
        (association_id, CHAT, a_episode, b_episode, status, 1700000000,
         1700000000))
    await db.db.commit()


def _identity_gate_on(monkeypatch) -> None:
    """Гейт C-1 ON: схлопывание member→canonical работает через резолвер."""
    import services.hot_config as hot

    monkeypatch.setenv("MCA_MEMORY_IDENTITY_ENABLED", "on")
    real_get = hot.get

    def fake_get(key, default=None):
        if key == "flags.memory_identity_enabled":
            return True
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


async def _canonical_row(db, *, member: int, canonical: int, uid: int,
                         entity_type: str = "user") -> None:
    await db.db.execute(
        f"INSERT INTO {er.ENTITY_CANONICAL_TABLE} (chat_id, entity_type, "
        "member_node_id, canonical_node_id, resolution, stable_kind, "
        "stable_value, method, evidence_ref_id, confidence, status, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (CHAT, entity_type, member, canonical, er.RESOLUTION_MERGED,
         er.STABLE_KIND_TG_USER, str(uid), er.METHOD_ALIAS_MAP, None,
         er.CONFIDENCE_CONFIRMED, er.STATUS_ACTIVE, 1, 1))
    await db.db.commit()


async def _builds(db) -> list[dict]:
    cursor = await db.db.execute(
        f"SELECT * FROM {mcomm.COMMUNITY_BUILDS_TABLE} "
        "ORDER BY started_at, build_id")
    return [dict(row) for row in await cursor.fetchall()]


async def _membership(db, build_id: str) -> dict[str, set[int]]:
    cursor = await db.db.execute(
        f"SELECT community_id, node_id, member_weight "
        f"FROM {mcomm.COMMUNITY_MEMBERS_TABLE} WHERE chat_id = ? AND "
        "build_id = ? ORDER BY community_id, node_id", (CHAT, build_id))
    result: dict[str, set[int]] = {}
    for row in await cursor.fetchall():
        result.setdefault(str(row["community_id"]), set()).add(
            int(row["node_id"]))
    return result


async def _active_builds(db) -> list[dict]:
    return [b for b in await _builds(db) if b["status"] == mcomm.STATUS_ACTIVE]


async def _seed_chain(db, names: tuple[str, ...]) -> list[int]:
    """Цепочка узлов с legacy-рёбрами (факт-обоснования нет)."""
    ids = [await db.upsert_node(CHAT, name, "user") for name in names]
    for left, right in zip(ids, ids[1:]):
        await _edge(db, left, right)
    return ids


# ── веса и классы происхождения (§6) ───────────────────────────────────────

def test_community_weight_table_matches_contract():
    assert mcomm.PROVENANCE_WEIGHTS == {
        "confirmed": 1.0, "tentative": 0.5, "legacy": 0.25, "cooccurrence": 0.1,
    }
    assert mcomm.link_weight("confirmed") == 1.0
    assert mcomm.link_weight("tentative") == 0.5
    assert mcomm.link_weight("legacy") == 0.25
    assert mcomm.link_weight("cooccurrence") == 0.1
    with pytest.raises(ValueError):
        mcomm.link_weight("почти-подтверждено")
    assert mcomm.association_provenance() == "cooccurrence"


def test_fact_provenance_delegates_to_existing_classifier(monkeypatch):
    seen: list[dict] = []
    real = gprov.classify_fact_provenance

    def spy(fact_row):
        seen.append(dict(fact_row))
        return real(fact_row)

    monkeypatch.setattr(gprov, "classify_fact_provenance", spy)

    assert mcomm.fact_provenance(
        {"subject_ref_id": 1, "speaker_author_id": 2}) == "confirmed"
    assert mcomm.fact_provenance(
        {"subject_ref_id": 1, "speaker_author_id": None}) == "tentative"
    assert mcomm.fact_provenance(
        {"subject_ref_id": None, "speaker_author_id": None}) == "legacy"
    assert mcomm.fact_provenance(None) == "legacy"
    # Решение принято существующим классификатором, а не второй копией правила.
    assert len(seen) == 3
    assert all("subject_ref_id" in row for row in seen)


@pytest.mark.asyncio
async def test_build_weights_exact_per_provenance_class(tmp_path):
    svc = DatabaseService(str(tmp_path / "weights.db"))
    await svc.initialize()
    try:
        confirmed_fact = await _fact(svc, subject=1, speaker=2)
        tentative_fact = await _fact(svc, subject=1)
        legacy_fact = await _fact(svc, subject=None, speaker=None)

        hub = await svc.upsert_node(CHAT, "Хаб", "user")
        people = [await svc.upsert_node(CHAT, name, "user")
                  for name in ("Аня", "Боря", "Вика", "Гена")]
        anna, boris, vika, ghena = people
        await _edge(svc, hub, anna, "знает", fact_id=confirmed_fact)
        await _edge(svc, hub, boris, "знает", fact_id=tentative_fact)
        await _edge(svc, hub, vika, "знает", fact_id=legacy_fact)
        await _edge(svc, hub, ghena, "знает", fact_id=None)

        await _episode(svc, "ep-a", ["Хаб"])
        await _episode(svc, "ep-b", ["Аня"])
        await _association(svc, "assoc-1", "ep-a", "ep-b")

        snapshot = await mcomm._read_nodes(svc, CHAT)
        canonical, _unresolved = await mcomm._resolve_canonical_ids(
            svc, CHAT, snapshot, await mcomm._read_active_canonical_rows(
                svc, CHAT))
        links, counts, dropped = await mcomm._collect_links(
            svc, CHAT, nodes=snapshot, canonical=canonical,
            facts=await mcomm._read_facts(svc, CHAT),
            associations=await mcomm._read_association_rows(svc, CHAT))

        weights = sorted(link.weight for link in links)
        assert weights == [0.1, 0.25, 0.25, 0.5, 1.0]
        assert counts == {"confirmed": 1, "tentative": 1, "legacy": 2,
                          "cooccurrence": 1}
        assert dropped == 0
        by_source = {link.source: link for link in links
                     if link.source == mcomm.LINK_SOURCE_ASSOCIATION}
        assert by_source["association"].provenance == "cooccurrence"
        assert by_source["association"].weight == 0.1

        result = await mcomm.build_chat_communities(svc, CHAT, now=1000)
        assert result.status == mcomm.STATUS_ACTIVE
        # Классы весов не изменились; §14.3 добавляет ТОЛЬКО наблюдаемость
        # proven/weak в те же счётчики сборки.
        assert {key: result.provenance_counts[key] for key in counts} == counts
        assert result.provenance_counts["proven_communities"] == 1
        assert result.provenance_counts["weak_communities"] == 0
        assert result.edge_count == 5
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_cooccurrence_never_becomes_confirmed(tmp_path):
    svc = DatabaseService(str(tmp_path / "cooccurrence.db"))
    await svc.initialize()
    try:
        # Оба участника имеют доказанный факт, но связь между ними — только
        # ассоциация эпизодов: она обязана остаться гипотезой веса 0.1.
        await _fact(svc, subject=1, speaker=2)
        await svc.upsert_node(CHAT, "Аня", "user")
        await svc.upsert_node(CHAT, "Боря", "user")
        await _episode(svc, "ep-a", ["Аня"])
        await _episode(svc, "ep-b", ["Боря"])
        await _association(svc, "assoc-1", "ep-a", "ep-b")

        edges_before = await _row_count(svc, "edges")
        snapshot = await mcomm._read_nodes(svc, CHAT)
        facts = await mcomm._read_facts(svc, CHAT)
        links, counts, _ = await mcomm._collect_links(
            svc, CHAT, nodes=snapshot, canonical={}, facts=facts,
            associations=await mcomm._read_association_rows(svc, CHAT))

        assert len(links) == 1
        link = links[0]
        assert link.source == mcomm.LINK_SOURCE_ASSOCIATION
        assert link.provenance == "cooccurrence"
        assert link.weight == 0.1
        assert counts == {"confirmed": 0, "tentative": 0, "legacy": 0,
                          "cooccurrence": 1}
        # Гипотеза не превращается в типизированное ребро.
        assert await _row_count(svc, "edges") == edges_before
        # Даже при доказанных фактах у обоих участников класс связи не растёт.
        assert link.provenance not in ("confirmed", "tentative")

        result = await mcomm.build_chat_communities(svc, CHAT, now=1000)
        community = result.communities[0]
        assert community.stats.confirmed_links == 0
        assert community.stats.cooccurrence_links == 1
        # Подпись не выдаёт совпадение за источник (MEM-07.4/07.6).
        assert community.label.label.startswith("Сообщество")
        assert community.label.dominant_names == ()
    finally:
        await svc.close()


# ── детерминизм и членство ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_is_deterministic_over_seeded_fixture(tmp_path):
    async def _seed_and_build(name: str):
        svc = DatabaseService(str(tmp_path / name))
        await svc.initialize()
        try:
            ids = await _seed_chain(svc, ("Аня", "Боря", "Вика", "Гена"))
            await _edge(svc, ids[0], ids[2], "дружит")
            result = await mcomm.build_chat_communities(
                svc, CHAT, now=5000, build_id=f"det-{name}")
            membership = await _membership(svc, result.build_id)
            return [(c.community_id, c.members,
                     tuple(sorted(c.member_weights.items())))
                    for c in result.communities], membership
        finally:
            await svc.close()

    first, first_membership = await _seed_and_build("det_a.db")
    second, second_membership = await _seed_and_build("det_b.db")
    assert first == second
    assert first_membership == second_membership
    assert len(first) >= 2  # фикстура действительно распадается на сообщества


@pytest.mark.asyncio
async def test_membership_stores_canonical_node_ids_never_uids(tmp_path,
                                                              monkeypatch):
    _identity_gate_on(monkeypatch)
    svc = DatabaseService(str(tmp_path / "canonical.db"))
    await svc.initialize()
    try:
        canonical = await svc.upsert_node(CHAT, "Александр", "user")
        member = await svc.upsert_node(CHAT, "Саша", "user")
        other = await svc.upsert_node(CHAT, "Папаха", "user")
        await _canonical_row(svc, member=member, canonical=canonical,
                             uid=UID_A)
        await _edge(svc, member, other, "знает")
        await _edge(svc, canonical, other, "знает")

        result = await mcomm.build_chat_communities(svc, CHAT, now=1000)
        cursor = await svc.db.execute("SELECT id FROM nodes WHERE chat_id = ?",
                                      (CHAT,))
        node_ids = {int(row["id"]) for row in await cursor.fetchall()}
        published = set()
        for members in (await _membership(svc, result.build_id)).values():
            published |= members

        assert published <= node_ids          # только nodes.id
        assert canonical in published and other in published
        assert member not in published        # схлопнуто в канонический узел
        assert UID_A not in published         # Telegram UID в членство не попал
        # Схлопывание видно: у канонического узла внутренний вес двух рёбер.
        weights = dict(result.communities[0].member_weights)
        assert weights[canonical] == pytest.approx(0.5)
        assert weights[other] == pytest.approx(0.5)
    finally:
        await svc.close()


# ── жизненный цикл сборки (§6) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rebuild_keeps_single_active_and_links_prev_build(tmp_path):
    svc = DatabaseService(str(tmp_path / "lifecycle.db"))
    await svc.initialize()
    try:
        await _seed_chain(svc, ("Аня", "Боря", "Вика", "Гена"))
        first = await mcomm.build_chat_communities(svc, CHAT, now=1000,
                                                  build_id="build-1")
        assert first.status == mcomm.STATUS_ACTIVE
        assert first.prev_build_id is None

        second = await mcomm.build_chat_communities(svc, CHAT, now=2000,
                                                   build_id="build-2")
        assert second.status == mcomm.STATUS_ACTIVE
        assert second.prev_build_id == "build-1"

        active = await _active_builds(svc)
        assert [b["build_id"] for b in active] == ["build-2"]
        statuses = {b["build_id"]: b["status"] for b in await _builds(svc)}
        assert statuses == {"build-1": mcomm.STATUS_SUPERSEDED,
                            "build-2": mcomm.STATUS_ACTIVE}
        # Членство предыдущей сборки не переписано и не удалено.
        assert await _membership(svc, "build-1") == \
            await _membership(svc, "build-2")
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_failed_build_does_not_displace_active(tmp_path, monkeypatch):
    svc = DatabaseService(str(tmp_path / "failed.db"))
    await svc.initialize()
    try:
        await _seed_chain(svc, ("Аня", "Боря", "Вика", "Гена"))
        active = await mcomm.build_chat_communities(svc, CHAT, now=1000,
                                                   build_id="build-ok")
        active_members = await _membership(svc, "build-ok")

        def boom(**_kwargs):
            raise RuntimeError("compute exploded")

        monkeypatch.setattr(mcomm, "_build_communities", boom)
        failed = await mcomm.build_chat_communities(svc, CHAT, now=2000,
                                                    build_id="build-fail")
        assert failed.status == mcomm.STATUS_FAILED
        assert "compute exploded" in (failed.error or "")

        statuses = {b["build_id"]: b["status"] for b in await _builds(svc)}
        assert statuses == {"build-ok": mcomm.STATUS_ACTIVE,
                            "build-fail": mcomm.STATUS_FAILED}
        assert [b["build_id"] for b in await _active_builds(svc)] == \
            ["build-ok"]
        assert await _membership(svc, "build-ok") == active_members
        assert await _membership(svc, "build-fail") == {}   # failed не читается
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_atomic_publish_keeps_previous_active_on_partial_failure(
        tmp_path, monkeypatch):
    svc = DatabaseService(str(tmp_path / "atomic.db"))
    await svc.initialize()
    try:
        await _seed_chain(svc, ("Аня", "Боря", "Вика", "Гена"))
        await mcomm.build_chat_communities(svc, CHAT, now=1000,
                                          build_id="build-ok")
        ok_members = await _membership(svc, "build-ok")

        async def broken(conn, **_kwargs):
            raise RuntimeError("community_members_incomplete")

        monkeypatch.setattr(mcomm, "_assert_publication_complete", broken)
        result = await mcomm.build_chat_communities(svc, CHAT, now=2000,
                                                    build_id="build-partial")
        assert result.status == mcomm.STATUS_FAILED

        monkeypatch.undo()
        statuses = {b["build_id"]: b["status"] for b in await _builds(svc)}
        assert statuses == {"build-ok": mcomm.STATUS_ACTIVE,
                            "build-partial": mcomm.STATUS_FAILED}
        # Полная атомарность: ни одной строки членства, ни одного supersede.
        assert await _membership(svc, "build-partial") == {}
        assert await _membership(svc, "build-ok") == ok_members
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_cancelled_build_marks_failed_and_reraises(tmp_path,
                                                          monkeypatch):
    svc = DatabaseService(str(tmp_path / "cancelled.db"))
    await svc.initialize()
    try:
        await _seed_chain(svc, ("Аня", "Боря"))
        await mcomm.build_chat_communities(svc, CHAT, now=1000,
                                          build_id="build-ok")

        def cancel(**_kwargs):
            raise asyncio.CancelledError()

        monkeypatch.setattr(mcomm, "_build_communities", cancel)
        with pytest.raises(asyncio.CancelledError):
            await mcomm.build_chat_communities(svc, CHAT, now=2000,
                                               build_id="build-cancel")
        monkeypatch.undo()
        statuses = {b["build_id"]: b["status"] for b in await _builds(svc)}
        assert statuses["build-cancel"] == mcomm.STATUS_FAILED
        assert [b["build_id"] for b in await _active_builds(svc)] == \
            ["build-ok"]
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_retry_after_failure_uses_new_build_id_but_stable_community_ids(
        tmp_path, monkeypatch):
    svc = DatabaseService(str(tmp_path / "retry.db"))
    await svc.initialize()
    try:
        await _seed_chain(svc, ("Аня", "Боря", "Вика", "Гена"))
        first = await mcomm.build_chat_communities(svc, CHAT, now=1000,
                                                  build_id="build-ok")
        first_ids = sorted(c.community_id for c in first.communities)
        first_members = {c.community_id: c.members for c in first.communities}

        def boom(**_kwargs):
            raise RuntimeError("retry needed")

        monkeypatch.setattr(mcomm, "_build_communities", boom)
        failed = await mcomm.build_chat_communities(svc, CHAT, now=2000,
                                                    build_id="build-retry-1")
        assert failed.status == mcomm.STATUS_FAILED
        monkeypatch.undo()

        retried = await mcomm.build_chat_communities(svc, CHAT, now=3000,
                                                     build_id="build-retry-2")
        assert retried.status == mcomm.STATUS_ACTIVE
        assert retried.build_id != failed.build_id       # новый build_id
        assert retried.prev_build_id == "build-ok"       # failed не предок
        assert sorted(c.community_id for c in retried.communities) == first_ids
        assert {c.community_id: c.members for c in retried.communities} == \
            first_members
        assert [b["build_id"] for b in await _active_builds(svc)] == \
            ["build-retry-2"]
    finally:
        await svc.close()


def test_split_and_merge_community_id_mapping():
    split_prev = {"c1": {1, 2, 3, 4}, "c9": {7, 8}}
    split_ids, split_summary = mcomm.map_community_ids(
        [frozenset({1, 2}), frozenset({3, 4})], split_prev)
    assert split_ids[0] == "c1"                 # сопоставленный прежний id
    assert split_ids[1] not in split_prev       # новая часть получает новый id
    assert split_summary["split"][0]["prev_community_id"] == "c1"
    assert sorted(split_summary["split"][0]["parts"]) == sorted(split_ids)
    assert split_summary["split"][0]["reason"] == mcomm.REASON_SPLIT
    assert split_summary["dropped"] == ["c9"]   # исчезнувшее сообщество
    assert split_summary["mapping"] == {split_ids[0]: "c1"}

    merge_prev = {"c1": {1, 2}, "c9": {3, 4}}
    merged_ids, merged_summary = mcomm.map_community_ids(
        [frozenset({1, 2, 3, 4})], merge_prev)
    assert merged_ids == ["c1"]                 # детерминированно меньший id
    assert merged_summary["merge"][0]["community_id"] == "c1"
    assert merged_summary["merge"][0]["prev_community_ids"] == ["c1", "c9"]
    assert merged_summary["merge"][0]["reason"] == mcomm.REASON_MERGE
    assert merged_summary["mapping"] == {"c1": "c1"}

    stable_prev = {"c1": {1, 2, 3, 4}, "c9": {7, 8}}
    unchanged_ids, unchanged = mcomm.map_community_ids(
        [frozenset({1, 2, 3, 4}), frozenset({7, 8})], stable_prev)
    assert unchanged_ids == ["c1", "c9"]
    assert unchanged["split"] == [] and unchanged["merge"] == []
    assert unchanged["created"] == [] and unchanged["dropped"] == []
    assert unchanged["reused"] == 2
    assert unchanged["reasons"]["created"] == mcomm.REASON_CREATED


@pytest.mark.asyncio
async def test_rebuild_records_mapping_and_new_communities(tmp_path):
    svc = DatabaseService(str(tmp_path / "mapping.db"))
    await svc.initialize()
    try:
        ids = await _seed_chain(svc, ("Аня", "Боря", "Вика", "Гена"))
        first = await mcomm.build_chat_communities(svc, CHAT, now=1000,
                                                  build_id="build-1")
        assert first.change_summary["reused"] == 0

        extra_a = await svc.upsert_node(CHAT, "Дина", "user")
        extra_b = await svc.upsert_node(CHAT, "Егор", "user")
        await _edge(svc, extra_a, extra_b, "дружит")
        second = await mcomm.build_chat_communities(svc, CHAT, now=2000,
                                                   build_id="build-2")
        summary = second.change_summary
        assert summary["prev_build_id"] == "build-1"
        assert summary["mapping"]                        # id перенесены
        assert summary["created"]                        # новые сообщества
        # Старые id не переписаны: прежняя сборка осталась как была.
        old = await _membership(svc, "build-1")
        assert set(old) <= set(summary["mapping"].values()) | set(
            summary["dropped"])
        assert ids[0] in set().union(*old.values())
    finally:
        await svc.close()


# ── неприкосновенность памяти и границы записей (§6) ───────────────────────

async def _memory_snapshot(db) -> dict[str, object]:
    cursor = await db.db.execute(
        "SELECT COUNT(*) FROM nodes")
    nodes = int((await cursor.fetchone())[0])
    cursor = await db.db.execute("SELECT COUNT(*) FROM edges")
    edges = int((await cursor.fetchone())[0])
    cursor = await db.db.execute("SELECT COUNT(*) FROM graph_facts")
    facts = int((await cursor.fetchone())[0])
    cursor = await db.db.execute(
        "SELECT id, status, weight FROM graph_facts ORDER BY id")
    fact_rows = [tuple(row) for row in await cursor.fetchall()]
    cursor = await db.db.execute(
        "SELECT id, source_id, target_id, relation_type, weight, fact_id "
        "FROM edges ORDER BY id")
    edge_rows = [tuple(row) for row in await cursor.fetchall()]
    cursor = await db.db.execute(
        "SELECT id, entity_name, entity_type FROM nodes ORDER BY id")
    node_rows = [tuple(row) for row in await cursor.fetchall()]
    cursor = await db.db.execute(
        f"SELECT COUNT(*) FROM {er.ENTITY_CANONICAL_TABLE}")
    canonical = int((await cursor.fetchone())[0])
    cursor = await db.db.execute(
        "SELECT association_id, status FROM mca_associations "
        "ORDER BY association_id")
    associations = [tuple(row) for row in await cursor.fetchall()]
    return {"nodes": nodes, "edges": edges, "facts": facts,
            "fact_rows": fact_rows, "edge_rows": edge_rows,
            "node_rows": node_rows, "canonical": canonical,
            "associations": associations}


@pytest.mark.asyncio
async def test_build_does_not_mutate_memory_tables(tmp_path):
    svc = DatabaseService(str(tmp_path / "immutable.db"))
    await svc.initialize()
    try:
        fact = await _fact(svc, subject=1, speaker=2)
        ids = await _seed_chain(svc, ("Аня", "Боря", "Вика", "Гена"))
        await _edge(svc, ids[0], ids[3], "знает", fact_id=fact)
        await _episode(svc, "ep-a", ["Аня"])
        await _episode(svc, "ep-b", ["Боря"])
        await _association(svc, "assoc-1", "ep-a", "ep-b")

        before = await _memory_snapshot(svc)
        result = await mcomm.build_chat_communities(svc, CHAT, now=1000)
        after = await _memory_snapshot(svc)

        assert result.status == mcomm.STATUS_ACTIVE
        assert before == after
        assert await _row_count(svc, mcomm.COMMUNITY_BUILDS_TABLE) == 1
        assert await _row_count(svc, mcomm.COMMUNITY_MEMBERS_TABLE) == \
            result.member_count
    finally:
        await svc.close()


def test_module_writes_only_community_tables():
    """Статическая граница: SQL записи модуля не адресуют таблицы памяти."""
    import re

    root = Path(__file__).resolve().parent.parent
    source = (root / "services" / "memory_communities.py").read_text(
        encoding="utf-8")
    forbidden = (
        "nodes", "edges", "graph_facts", "graph_facts_vec", "graph_facts_fts",
        "mca_associations", "mca_episodes", "mca_entity_canonical",
        "mca_source_refs", "mca_evidence_links", "mca_provenance_status",
        "mca_stories", "smart_messages", "task_jobs", "graph_snapshots",
    )
    statements = list(re.finditer(
        r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)", source))
    assert statements, "не найдено ни одной записи — тест потерял смысл"
    for match in statements:
        tail = source[match.end(): match.end() + 120]
        target = tail.strip().split()[0] if tail.strip() else ""
        assert target.startswith("{"), (match.group(0), target)
        for table in forbidden:
            assert not re.search(rf"\b{re.escape(table)}\b", target), \
                (match.group(0), target)
        assert "COMMUNITY_BUILDS_TABLE" in target \
            or "COMMUNITY_MEMBERS_TABLE" in target, target


def test_builder_is_not_registered_on_hot_path():
    """Ни один горячий путь не собирает сообщества (MEM-07.3).

    Проверяется достижимость СБОРЩИКА: модуль не импортируется и
    `build_chat_communities` не вызывается. Гейт-резолвер
    (`mca_gates.memory_communities_enabled`) горячему пути разрешён — это
    чтение флага (волна 4: канал читает готовую active-сборку), а не сборка.
    """
    import ast

    root = Path(__file__).resolve().parent.parent
    hot_paths = (
        "services/direct_chat_service.py",
        "services/mca_retrieval_context.py",
        "web/api/memory_agi.py",
        "web/api/cognitive_map.py",
    )
    for relative in hot_paths:
        text = (root / relative).read_text(encoding="utf-8")
        assert "build_chat_communities" not in text, relative
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(
                        "services.memory_communities"), relative
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") != "services.memory_communities", \
                    relative
                if node.module == "services":
                    for alias in node.names:
                        assert alias.name != "memory_communities", relative


# ── подписи (§6/MEM-07.4) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_labels_use_dominant_sourced_entity_and_neutral_fallback(tmp_path):
    svc = DatabaseService(str(tmp_path / "labels.db"))
    await svc.initialize()
    try:
        fact = await _fact(svc, subject=1, speaker=2)
        hub = await svc.upsert_node(CHAT, "Папаха", "user")
        leaf = await svc.upsert_node(CHAT, "Александр", "user")
        await _edge(svc, hub, leaf, "знает", fact_id=fact)

        result = await mcomm.build_chat_communities(svc, CHAT, now=1000)
        labelled = result.communities[0]
        assert labelled.label.label.startswith("Сообщество: ")
        assert "Папаха" in labelled.label.dominant_names
        assert "подтверждённых 1" in labelled.label.basis
        assert "последняя активность" in labelled.label.basis
        assert labelled.stats.density == pytest.approx(1.0)
    finally:
        await svc.close()

    neutral = DatabaseService(str(tmp_path / "labels_neutral.db"))
    await neutral.initialize()
    try:
        await neutral.upsert_node(CHAT, "Иван", "user")
        await neutral.upsert_node(CHAT, "Пётр", "user")
        await _episode(neutral, "ep-a", ["Иван"])
        await _episode(neutral, "ep-b", ["Пётр"])
        await _association(neutral, "assoc-1", "ep-a", "ep-b")

        result = await mcomm.build_chat_communities(neutral, CHAT, now=1000)
        community = result.communities[0]
        assert community.label.label == "Сообщество 1"
        assert community.label.dominant_names == ()
        assert "совпадений 1" in community.label.basis
        assert mcomm.UNKNOWN_VALUE_TEXT in community.label.basis  # активность
    finally:
        await neutral.close()

