"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-07 — волна 4: community-канал retrieval.

Контракт `plans/features/memory-cognitive-02/contracts.md` §6 (retrieval читает
ТОЛЬКО `active`-сборку через существующий единый `retrieve`) и §5.2 (гейт
`MCA_MEMORY_COMMUNITIES_ENABLED` — заводской default ON после приёмки; OFF —
явный выбор владельца или аварийный env).

Проверяется:

* нет active-сборки → канал пуст, а обычная выдача байт-в-байт та же, что при
  выключенном гейте (никакого второго поиска и никаких новых кандидатов);
* есть active-сборка → в выдачу попадают только её сообщества; `superseded`/
  `building` не читаются никогда;
* гейт OFF → канал пуст даже при готовой active-сборке;
* нетематический режим → канал пуст (сообщества — только широкий обзор);
* `member_weight` — внутренний вес ребра, а не нормированный 0..1-скор:
  изменение веса не меняет ранг кандидата;
* идентификаторы членства — `nodes.id`, не Telegram UID.

TEST-LIFECYCLE: CONTRACT owner=MEMORY-07 (contracts §6, §5.2)
"""
from __future__ import annotations

import pytest

from services import mca_gates
from services import mca_retrieval_context as rc
from services.database import DatabaseService

CHAT = -1001777000777
FLAG_KEY = "flags.memory_communities_enabled"


def _gate(monkeypatch, *, on: bool) -> None:
    """Реальный резолвер гейта: патчится источник значения (`hot.get`)."""
    import services.hot_config as hot

    if on:
        monkeypatch.setenv("MCA_MEMORY_COMMUNITIES_ENABLED", "on")
    else:
        # Аварийный env не выставлен (заводской дефолт — ON), значит OFF
        # задаётся именно каталоговым слоем — как у владельца, снявшего флаг.
        monkeypatch.delenv("MCA_MEMORY_COMMUNITIES_ENABLED", raising=False)
    real_get = hot.get

    def fake_get(key, default=None):
        if key == FLAG_KEY:
            return on
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


async def _db(tmp_path, name: str = "communities_retrieval.db") \
        -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add_build(db, *, build_id: str, status: str, members: dict,
                     started_at: int, prev_build_id: str | None = None) -> None:
    """Настоящие строки реестра сборок/членства (без выдуманных колонок)."""
    await db.db.execute(
        "INSERT INTO mca_community_builds (build_id, chat_id, algorithm, "
        "algorithm_version, params_json, graph_revision, node_count, "
        "edge_count, prev_build_id, change_summary_json, status, started_at, "
        "finished_at) VALUES (?, ?, 'test', '1', '{}', 'rev', ?, 0, ?, '{}', "
        "?, ?, ?)",
        (build_id, CHAT, len(members), prev_build_id, status, started_at,
         started_at))
    for community_id, nodes in members.items():
        for node_id, weight in nodes:
            await db.db.execute(
                "INSERT INTO mca_community_members (chat_id, build_id, "
                "community_id, node_id, member_weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (CHAT, build_id, community_id, node_id, weight, started_at))
    await db.db.commit()


def _communities(result) -> list:
    return [c for c in result.candidates if c.channel == "community"]


@pytest.mark.asyncio
async def test_no_active_build_keeps_ordinary_results_byte_equivalent(
        tmp_path, monkeypatch):
    """Нет сборок: заводской ON не меняет выдачу относительно явного OFF."""
    db = await _db(tmp_path, "no_build.db")
    try:
        await db.insert_graph_fact(
            CHAT, "живой факт про дроны", "chat_history", None,
            target_user="Лёха")

        # Заводской дефолт (env не выставлен, каталог не патчится) — ON.
        monkeypatch.delenv("MCA_MEMORY_COMMUNITIES_ENABLED", raising=False)
        assert await mca_gates.memory_communities_enabled(CHAT) is True
        on = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=CHAT, query="дроны", mode="thematic", top_k=10))

        _gate(monkeypatch, on=False)     # владелец снял флаг в каталоге
        assert await mca_gates.memory_communities_enabled(CHAT) is False
        off = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=CHAT, query="дроны", mode="thematic", top_k=10))

        assert [c.id for c in on.candidates] == [c.id for c in off.candidates]
        assert on.channels_used == off.channels_used
        assert _communities(on) == []
        assert "community" not in on.channels_used
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_only_active_build_membership_is_returned(tmp_path, monkeypatch):
    """active-сборка отдаётся; superseded того же чата — никогда."""
    db = await _db(tmp_path, "active_only.db")
    try:
        first = await db.upsert_node(CHAT, "Папаха", "user")
        second = await db.upsert_node(CHAT, "Александр", "user")
        old_node = await db.upsert_node(CHAT, "Старый участник", "user")

        await _add_build(db, build_id="cb-old", status="superseded",
                         members={"c-stale": [(old_node, 1.0)]},
                         started_at=1000)
        await _add_build(db, build_id="cb-new", status="active",
                         members={"c-fresh": [(first, 1.0), (second, 0.25)]},
                         started_at=2000, prev_build_id="cb-old")
        await _add_build(db, build_id="cb-broken", status="failed",
                         members={"c-failed": [(old_node, 1.0)]},
                         started_at=3000)
        await _add_build(db, build_id="cb-partial", status="building",
                         members={"c-building": [(old_node, 1.0)]},
                         started_at=4000)

        _gate(monkeypatch, on=True)

        # Членство читается ТОЛЬКО из active-сборки: остальные статусы
        # (superseded/failed/building) не появляются даже без keyword-фильтра.
        rows = await rc._community_candidates(db, CHAT, [], 10)
        pairs = {(row["community_id"], row["node_id"]) for row in rows}
        assert pairs == {("c-fresh", first), ("c-fresh", second)}

        result = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=CHAT, query="Папаха", mode="thematic", top_k=10))
        found = _communities(result)
        assert found, "active-сборка обязана давать community-кандидата"
        assert "community" in result.channels_used
        # Кандидаты — только сообщество действующей сборки; узлы членства
        # берутся из `nodes.id`, а stale/failed/building не читаются вообще.
        assert {c.entity_id for c in found} == {"c-fresh"}
        allowed = {f"comm:c-fresh:{first}", f"comm:c-fresh:{second}"}
        assert {c.id for c in found} <= allowed
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_gate_off_hides_existing_active_build(tmp_path, monkeypatch):
    """Гейт OFF → канал пуст даже при готовой active-сборке."""
    db = await _db(tmp_path, "gate_off.db")
    try:
        node = await db.upsert_node(CHAT, "Папаха", "user")
        await _add_build(db, build_id="cb-active", status="active",
                         members={"c-1": [(node, 1.0)]}, started_at=1000)
        _gate(monkeypatch, on=False)
        result = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=CHAT, query="Папаха", mode="thematic", top_k=10))
        assert _communities(result) == []
        assert "community" not in result.channels_used
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_non_thematic_mode_never_reads_communities(tmp_path, monkeypatch):
    """Сообщества — только широкий обзор (`thematic`), не точечный поиск."""
    db = await _db(tmp_path, "modes.db")
    try:
        node = await db.upsert_node(CHAT, "Папаха", "user")
        await _add_build(db, build_id="cb-active", status="active",
                         members={"c-1": [(node, 1.0)]}, started_at=1000)
        _gate(monkeypatch, on=True)
        for mode in ("specific", "episodic"):
            result = await rc.retrieve(db, None, rc.RetrievalRequest(
                chat_id=CHAT, query="Папаха", mode=mode, top_k=10))
            assert _communities(result) == [], mode
            assert "community" not in result.channels_used, mode
        thematic = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=CHAT, query="Папаха", mode="thematic", top_k=10))
        assert _communities(thematic) != []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_member_weight_is_internal_weight_not_ranking_score(
        tmp_path, monkeypatch):
    """Вес ребра кластера не нормируется и в ранг канала не подмешивается."""
    db = await _db(tmp_path, "weights.db")
    try:
        weak = await db.upsert_node(CHAT, "Слабый", "user")
        strong = await db.upsert_node(CHAT, "Сильный", "user")
        await _add_build(db, build_id="cb-w", status="active", started_at=1000,
                         members={"c-w": [(weak, 0.1), (strong, 1.0)]})
        _gate(monkeypatch, on=True)

        rows = await rc._community_candidates(db, CHAT, [], 10)
        # Вес сохраняется как есть: 0.1 не «нормируется» в 1.0 и не режется.
        weights = {row["node_id"]: row["member_weight"] for row in rows}
        assert weights == {weak: 0.1, strong: 1.0}

        # Ранг кандидата — канальный вес минус позиция, а не member_weight:
        # при одинаковой позиции разные веса дают одинаковый score.
        cands = [rc._community_candidate(row, CHAT, pos)
                 for pos, row in enumerate(rows)]
        assert [c.score for c in cands] == [
            rc._channel_rank("community", pos) for pos in range(len(cands))]
        # Документированная семантика веса (не 0..1-скор) видна потребителю.
        doc = rc._community_candidates.__doc__ or ""
        assert "member_weight" in doc
        assert "нормированный 0..1-скор" in doc
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_membership_ids_are_node_ids_not_telegram_uids(
        tmp_path, monkeypatch):
    """`community_id` + `nodes.id` из БД; uid (`subject_entity_ids`) не
    подмешивается в кандидата сообщества."""
    db = await _db(tmp_path, "ids.db")
    try:
        node = await db.upsert_node(CHAT, "Папаха", "user")
        await _add_build(db, build_id="cb-active", status="active",
                         members={"c-node": [(node, 1.0)]}, started_at=1000)
        _gate(monkeypatch, on=True)
        result = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=CHAT, query="Папаха", mode="thematic", top_k=10,
            subject_entity_ids=(428494,)))
        found = _communities(result)
        assert len(found) == 1
        candidate = found[0]
        assert candidate.id == f"comm:c-node:{node}"
        assert candidate.entity_id == "c-node"
        assert candidate.subject_entity_id is None
        assert candidate.chat_id == CHAT
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_channel_is_empty_when_tables_absent(tmp_path, monkeypatch):
    """До применения `v44` (нет таблиц) канал честно пуст, а не падает."""
    db = await _db(tmp_path, "no_tables.db")
    try:
        await db.db.execute("DROP TABLE IF EXISTS mca_community_members")
        await db.db.execute("DROP TABLE IF EXISTS mca_community_builds")
        await db.db.commit()
        _gate(monkeypatch, on=True)
        assert await rc._community_candidates(db, CHAT, [], 10) == []
        result = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=CHAT, query="Папаха", mode="thematic", top_k=10))
        assert _communities(result) == []
    finally:
        await db.close()
