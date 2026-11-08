"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-07 — quality contract §14 (09.11.2026).

Контракт: `plans/features/memory-cognitive-02/contracts.md` §14 (заморожен
владельцем; отклонён выпуск «тихо, с нейтральными подписями»).

Проверяется ИСТОЧНИК причины, а не маскировка симптома:

* §14.1(A): крон-путь `summary_memory::_write_graph_triplets` создаёт факт и
  передаёт `fact_id` ребру тем же контрактом, что живой путь; повторный прогон
  переиспользует факт (существующий дедуп 64.1), а не инфлирует строки;
* §14.1(B): `subject_ref_id` резолвится для ЛЮБОЙ факт-строки с резолвимым
  субъектом (`world_knowledge` в т.ч.), а нерезолвимый субъект остаётся без
  ref — идентичность не выдумывается (ни неизвестное имя, ни одноимённые);
* §14.2: пороги PROVEN (size ≥ 3, S ≥ 1.0, S/T ≥ 0.5) на границах 2/3,
  ниже/на 1.0, ниже/на 0.5; WEAK — всё остальное;
* §14.3: proven-набор хранится в `change_summary_json` без DDL и без нового
  шага схемы; сборщик отдаёт метрики proven-сообществ и счётчики weak.

TEST-LIFECYCLE: CONTRACT owner=MEMORY-07 (contracts §14.1–§14.4)
"""
from __future__ import annotations

import dataclasses
import json
import time

import pytest

from services import graphrag_provenance as gprov
from services import memory_communities as mcomm
from services.database import DatabaseService
from services.summary_memory import MemoryManager

CHAT = -1001777000123


class _NoLLM:
    """Крон-путь пишет граф без LLM и без векторов (проверяется явно)."""

    async def generate(self, *args, **kwargs):      # pragma: no cover
        raise AssertionError("cron-путь не должен звать LLM")

    async def generate_background(self, *args, **kwargs):   # pragma: no cover
        raise AssertionError("cron-путь не должен звать LLM")

    async def embed(self, texts):                   # pragma: no cover
        raise AssertionError("cron-путь не запрашивает векторы")


async def _db(tmp_path, name: str) -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _rows(db, sql: str, params=()) -> list[dict]:
    cursor = await db.db.execute(sql, params)
    return [dict(row) for row in await cursor.fetchall()]


def _triplet(subject="аня", subject_type="user", predicate="любит",
             obj="дроны", object_type="topic") -> dict:
    return {"subject": subject, "subject_type": subject_type,
            "predicate": predicate, "object": obj, "object_type": object_type}


# ── §14.1(A): крон-путь создаёт факт и связывает ребро ─────────────────────

@pytest.mark.asyncio
async def test_cron_path_creates_fact_and_links_edge(tmp_path):
    """Ребро cron-пути обязано нести `fact_id` того же утверждения."""
    db = await _db(tmp_path, "cron_fact.db")
    try:
        await db.save_smart_message(
            42, CHAT, "аня любит дроны", None, int(time.time()), "text", "аня")
        memory = MemoryManager(db, _NoLLM())
        triplets = [_triplet()]

        await memory._write_graph_triplets(CHAT, triplets)

        edges = await _rows(
            db, "SELECT id, fact_id FROM edges WHERE chat_id = ?", (CHAT,))
        assert len(edges) == 1
        assert edges[0]["fact_id"] is not None, "cron-ребро осталось без факта"

        facts = await _rows(
            db, "SELECT id, fact, attribution_method, assertion_kind, "
                "subject_ref_id, speaker_author_id FROM graph_facts "
                "WHERE chat_id = ?", (CHAT,))
        assert len(facts) == 1
        fact = facts[0]
        assert fact["id"] == edges[0]["fact_id"]
        assert fact["fact"] == "аня любит дроны"      # тот же рендер, что live
        # §14.1(B): субъект резолвится → ref есть; говорящего cron не знает.
        assert fact["subject_ref_id"] is not None
        assert fact["speaker_author_id"] is None
        assert fact["attribution_method"] == "world_knowledge"
        assert fact["assertion_kind"] == "world_knowledge"
        assert gprov.classify_fact_provenance(fact) == gprov.EDGE_TENTATIVE

        # Повторный прогон батча: факт переиспользуется (дедуп 64.1), вес
        # ребра наращивается как раньше — строки фактов не инфлируют.
        await memory._write_graph_triplets(CHAT, triplets)
        assert len(await _rows(
            db, "SELECT id FROM graph_facts WHERE chat_id = ?", (CHAT,))) == 1
        edges_after = await _rows(
            db, "SELECT id, fact_id, weight FROM edges WHERE chat_id = ?",
            (CHAT,))
        assert len(edges_after) == 1
        assert edges_after[0]["fact_id"] == fact["id"]
        assert edges_after[0]["weight"] == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_cron_path_rolls_back_facts_and_edges_together(tmp_path):
    """Сбой посреди записи не оставляет ни факта, ни ребра (одна транзакция)."""
    db = await _db(tmp_path, "cron_rollback.db")
    try:
        memory = MemoryManager(db, _NoLLM())
        original = db.upsert_edge
        calls = {"n": 0}

        async def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("mid-write failure")
            return await original(*args, **kwargs)

        db.upsert_edge = flaky
        with pytest.raises(RuntimeError):
            await memory._write_graph_triplets(
                CHAT, [_triplet(), _triplet(subject="боря", obj="самовары")])
        assert await _rows(
            db, "SELECT id FROM graph_facts WHERE chat_id = ?", (CHAT,)) == []
        assert await _rows(
            db, "SELECT id FROM edges WHERE chat_id = ?", (CHAT,)) == []
    finally:
        await db.close()


# ── §14.1(B): subject_ref_id для резолвимого субъекта, не «на всякий случай» ─

async def _attach(db, memory: MemoryManager, subject: str,
                  kind: str = "world_knowledge") -> dict:
    fact_id = await db.insert_graph_fact(
        CHAT, f"{subject} любит дроны", "chat_history", None, subject=subject)
    await memory._attach_fact_provenance(
        CHAT, fact_id, "chat_history", subject, None, None, {},
        declared_method=kind, declared_kind=kind)
    rows = await _rows(
        db, "SELECT id, subject_ref_id, speaker_author_id, "
            "attribution_method FROM graph_facts WHERE id = ?", (fact_id,))
    return rows[0]


@pytest.mark.asyncio
async def test_subject_ref_resolves_for_world_knowledge(tmp_path):
    """world_knowledge с резолвимым субъектом получает ref (раньше — никогда)."""
    db = await _db(tmp_path, "subject_ref.db")
    try:
        await db.save_smart_message(
            42, CHAT, "аня любит дроны", None, int(time.time()), "text", "аня")
        memory = MemoryManager(db, _NoLLM())

        resolved = await _attach(db, memory, "аня")
        assert resolved["attribution_method"] == "world_knowledge"
        assert resolved["subject_ref_id"] is not None
        # speaker cron/импорт не знает → tentative, а не «подтверждено».
        assert gprov.classify_fact_provenance(resolved) == gprov.EDGE_TENTATIVE
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_subject_ref_stays_empty_when_unresolvable(tmp_path):
    """Неизвестное имя и одноимённые остаются без ref (идентичность не выдумана)."""
    db = await _db(tmp_path, "subject_ref_miss.db")
    try:
        await db.save_smart_message(
            1, CHAT, "привет", None, int(time.time()), "text", "тёзка")
        await db.save_smart_message(
            2, CHAT, "привет", None, int(time.time()), "text", "тёзка")
        memory = MemoryManager(db, _NoLLM())

        unknown = await _attach(db, memory, "Совсем Неизвестный")
        assert unknown["subject_ref_id"] is None
        assert gprov.classify_fact_provenance(unknown) == \
            gprov.EDGE_LEGACY_UNVERIFIED

        ambiguous = await _attach(db, memory, "тёзка")
        assert ambiguous["subject_ref_id"] is None, \
            "одноимённые uid не сливаются в одну идентичность"
        assert gprov.classify_fact_provenance(ambiguous) == \
            gprov.EDGE_LEGACY_UNVERIFIED

        # Никакой SourceRef «на будущее» не создаётся: колонка не заполнена и
        # строки-получателя у факта нет (проверяем, что ref именно NULL).
        rows = await _rows(
            db, "SELECT subject_ref_id FROM graph_facts WHERE chat_id = ?",
            (CHAT,))
        assert [row["subject_ref_id"] for row in rows] == [None, None]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_subject_ref_not_written_for_bot_self_reply(tmp_path):
    """C-8 §8.4/R-3: собственный вывод бота не становится «основанием»."""
    db = await _db(tmp_path, "subject_ref_bot.db")
    try:
        await db.save_smart_message(
            42, CHAT, "аня любит дроны", None, int(time.time()), "text", "аня")
        memory = MemoryManager(db, _NoLLM())
        fact_id = await db.insert_graph_fact(
            CHAT, "аня любит дроны", "bot_self_reply", None, subject="аня")
        await memory._attach_fact_provenance(
            CHAT, fact_id, "bot_self_reply", "аня", None, None, {})
        rows = await _rows(
            db, "SELECT subject_ref_id, attribution_method FROM graph_facts "
                "WHERE id = ?", (fact_id,))
        assert rows[0]["attribution_method"] == "bot_self_reply"
        assert rows[0]["subject_ref_id"] is None
    finally:
        await db.close()


# ── §14.2: пороги PROVEN/WEAK на границах ──────────────────────────────────

PROVEN = mcomm.COMMUNITY_STATUS_PROVEN
WEAK = mcomm.COMMUNITY_STATUS_WEAK


def test_proven_size_boundary():
    """Пара (размер 2) — WEAK даже при идеальном доказательстве."""
    assert mcomm.classify_community_status(
        size=2, strong_weight=3.0, total_weight=3.0) == WEAK
    assert mcomm.classify_community_status(
        size=3, strong_weight=3.0, total_weight=3.0) == PROVEN


def test_proven_strong_weight_boundary():
    """S ниже 1.0 — WEAK; ровно 1.0 — PROVEN (при выполняющейся доле)."""
    assert mcomm.classify_community_status(
        size=3, strong_weight=0.999, total_weight=0.999) == WEAK
    assert mcomm.classify_community_status(
        size=3, strong_weight=0.5, total_weight=2.0) == WEAK      # S=0.5
    assert mcomm.classify_community_status(
        size=3, strong_weight=1.0, total_weight=2.0) == PROVEN    # S=1.0


def test_proven_strong_share_boundary():
    """S/T ниже 0.5 — WEAK; ровно 0.5 — PROVEN."""
    assert mcomm.classify_community_status(
        size=3, strong_weight=1.0, total_weight=2.0) == PROVEN
    assert mcomm.classify_community_status(
        size=3, strong_weight=1.0, total_weight=2.25) == WEAK
    assert mcomm.classify_community_status(
        size=3, strong_weight=1.0, total_weight=1.999) == PROVEN
    # Нет внутреннего веса вовсе — не доказано.
    assert mcomm.classify_community_status(
        size=3, strong_weight=0.0, total_weight=0.0) == WEAK


def test_status_uses_real_link_counts():
    """S и T считаются из настоящих классов связей (§6 веса)."""
    proven = mcomm.CommunityStats(
        node_count=3, confirmed_links=1, tentative_links=0, legacy_links=4,
        cooccurrence_links=0, density=0.5, last_activity=None)
    assert proven.strong_weight == 1.0
    assert proven.total_weight == 2.0          # 1.0 + 4×0.25
    assert proven.strong_share == 0.5
    assert mcomm.community_status(proven) == PROVEN

    weak = dataclasses.replace(proven, legacy_links=5)   # T = 2.25, доля 0.44
    assert mcomm.community_status(weak) == WEAK

    two_tentative = mcomm.CommunityStats(
        node_count=3, confirmed_links=0, tentative_links=2, legacy_links=0,
        cooccurrence_links=0, density=0.5, last_activity=None)
    assert two_tentative.strong_weight == 1.0
    assert mcomm.community_status(two_tentative) == PROVEN

    pair = dataclasses.replace(two_tentative, node_count=2)
    assert mcomm.community_status(pair) == WEAK


# ── §14.3: proven-набор в change_summary_json, без DDL ─────────────────────

async def _confirmed_fact(db, subject_ref: int, speaker: int) -> int:
    return await db.insert_graph_fact(
        CHAT, "Кирилл носит папаху", "chat_history", None, importance=5,
        subject_ref_id=subject_ref, speaker_author_id=speaker)


@pytest.mark.asyncio
async def test_build_stores_proven_ids_without_ddl(tmp_path):
    """Сборка пишет proven-набор и метрики в существующий JSON, без схемы."""
    db = await _db(tmp_path, "proven_ids.db")
    try:
        hub = await db.upsert_node(CHAT, "Кирилл", "user")
        topic_a = await db.upsert_node(CHAT, "Папаха", "topic")
        topic_b = await db.upsert_node(CHAT, "Самовар", "topic")
        weak_a = await db.upsert_node(CHAT, "Сосна", "topic")
        weak_b = await db.upsert_node(CHAT, "Берег", "topic")
        confirmed = await _confirmed_fact(db, hub, 42)
        await db.upsert_edge(hub, topic_a, "обсуждали", fact_id=confirmed)
        await db.upsert_edge(hub, topic_b, "упоминал", fact_id=None)
        await db.upsert_edge(weak_a, weak_b, "рядом", fact_id=None)

        user_version = (await _rows(db, "PRAGMA user_version"))[0]
        result = await mcomm.build_chat_communities(db, CHAT, now=1000)

        assert result.status == mcomm.STATUS_ACTIVE
        rows = await _rows(
            db, "SELECT change_summary_json FROM mca_community_builds "
                "WHERE build_id = ?", (result.build_id,))
        summary = json.loads(rows[0]["change_summary_json"])
        proven_ids = summary["proven_community_ids"]

        by_members = {frozenset(c.members): c for c in result.communities}
        proven_members = frozenset({hub, topic_a, topic_b})
        weak_members = frozenset({weak_a, weak_b})
        assert set(by_members) == {proven_members, weak_members}
        assert proven_ids == [by_members[proven_members].community_id]
        assert by_members[weak_members].community_id not in proven_ids

        entry = summary["proven_communities"][0]
        assert entry["community_id"] == by_members[proven_members].community_id
        assert entry["status"] == PROVEN
        assert entry["size"] == 3
        assert entry["strong_share"] == 0.8          # 1.0 / 1.25
        assert entry["density"] == 0.666667            # 2 пары из 3
        assert entry["basis"]
        assert result.provenance_counts["proven_communities"] == 1
        assert result.provenance_counts["weak_communities"] == 1

        # Никакого DDL: шаг схемы и набор таблиц/колонок не изменились.
        assert (await _rows(db, "PRAGMA user_version"))[0] == user_version
        # Голова схемы = 45 (v45 VMQ-V — колонки версии расшифровки; шаг
        # аддитивный и на сообщества/сборку не влияет).
        assert max(step.version
                   for step in DatabaseService.migration_steps()) == 45
        tables = {row["name"] for row in await _rows(
            db, "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "mca_community_builds" in tables
        # Никаких per-community таблиц: WEAK/PROVEN живёт в JSON сборки.
        assert {name for name in tables if "community" in name} == {
            "mca_community_builds", "mca_community_members"}
        columns = [row["name"] for row in await _rows(
            db, "PRAGMA table_info(mca_community_builds)")]
        assert columns == [
            "build_id", "chat_id", "algorithm", "algorithm_version",
            "params_json", "graph_revision", "node_count", "edge_count",
            "prev_build_id", "change_summary_json", "status", "started_at",
            "finished_at"]
    finally:
        await db.close()
