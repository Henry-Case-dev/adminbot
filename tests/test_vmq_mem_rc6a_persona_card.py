"""VMQ-MEM RC6a (C2): persona card fact metadata and alias/canon links."""
import datetime

import pytest

from services import mca_retrieval_context as mrc
from services import provenance
from services.database import DatabaseService
from services.mca_retrieval_context import RetrievalRequest, _relations_projection

CHAT = -1002661910336
UID = 42


def _ts(year):
    return int(datetime.datetime(
        year, 6, 1, tzinfo=datetime.timezone.utc).timestamp())


async def _db():
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _add_fact(db, text, *, year=2024, target="Леха", ref=None,
                    tg=None):
    return await db.insert_graph_fact(
        CHAT, text, "chat_history", None, target_user=target,
        message_timestamp=_ts(year), subject_ref_id=ref,
        tg_message_id=tg)


@pytest.mark.asyncio
async def test_card_facts_keep_order_and_add_metadata():
    db = await _db()
    try:
        ref_id = await provenance.resolve_source_ref(
            db, provenance.user_source_ref(CHAT, UID))
        first = await _add_fact(db, "Леха любит кофе", year=2024,
                                ref=ref_id, tg=101)
        second = await _add_fact(db, "Леха любит чай", year=2025)
        await _add_fact(db, "Леха без даты", year=2026)
        card = await db.get_persona_card(
            CHAT, "Леха", 20, _ts(2026), user_id=UID)
        facts = card["facts"]
        meta = card["facts_meta"]
        assert len(facts) == len(meta) == 3
        # Existing list/order/strings are preserved.
        assert [item["fact"] for item in meta] == facts
        assert "Леха любит кофе" in facts
        assert "Леха любит чай" in facts
        by_fact = {item["fact"]: item for item in meta}
        assert by_fact["Леха любит кофе"]["message_timestamp"] == _ts(2024)
        assert by_fact["Леха любит кофе"]["created_at"] is not None
        assert by_fact["Леха любит кофе"]["source_ref_id"] == ref_id
        assert by_fact["Леха любит кофе"]["tg_message_id"] == 101
        assert by_fact["Леха любит чай"]["message_timestamp"] == _ts(2025)
        assert by_fact["Леха без даты"]["message_timestamp"] == _ts(2026)
        assert first and second
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_alias_canon_links_and_exact_name():
    db = await _db()
    try:
        exact = await db.upsert_node(CHAT, "Леха", "user")
        alias = await db.upsert_node(CHAT, "леха вдовин", "user")
        topic = await db.upsert_node(CHAT, "кофе", "topic")
        await db.upsert_edge(exact, topic, "любит")
        await db.upsert_edge(alias, topic, "обсуждает")

        exact_card = await db.get_persona_card(
            CHAT, "Леха", 20, _ts(2026))
        assert any(link["source_name"] == "Леха" for link in exact_card["links"])

        alias_only = await db.get_persona_card(
            CHAT, "Леха", 20, _ts(2026),
            alias_names=("леха вдовин",))
        names = {link["source_name"] for link in alias_only["links"]}
        assert "леха вдовин" in names
        assert "Леха" in names
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_relations_projection_passes_alias_names():
    db = await _db()
    try:
        await db.upsert_node(CHAT, "леха вдовин", "user")
        topic = await db.upsert_node(CHAT, "кофе", "topic")
        # Alias-only node: exact "Леха" has no node.
        await db.upsert_edge(
            (await db.upsert_node(CHAT, "леха вдовин", "user")),
            topic, "обсуждает")
        req = RetrievalRequest(
            chat_id=CHAT, query="Леха", subject_names=("леха вдовин",),
            include_relations=True)
        relations = await _relations_projection(db, req, 10)
        assert relations
        assert any("леха вдовин" in item["text"] for item in relations)
        # E1 threshold untouched by RC6a.
        assert mrc.PERIOD_MIN_SHARED_STEMS == 2
    finally:
        await db.close()
