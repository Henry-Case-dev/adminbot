"""VMQ-MEM RC5a (C1): producer attribution for durable personal facts."""
import datetime

import pytest

from services.database import DatabaseService
from services.summary_memory import MemoryManager, fact_durability_decision

CHAT = -1002661910336
UID = 42
NOW = int(datetime.datetime(
    2024, 6, 1, tzinfo=datetime.timezone.utc).timestamp())


class _AttachHost:
    """Minimal producer host: only db/canon are used by the attachment."""

    def __init__(self, db):
        self.db = db
        self.aliases = None

    def _canon_fact_name(self, name):
        return str(name or "")


async def _db():
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _insert_fact(db, text, subject="Леха", **kwargs):
    return await db.insert_graph_fact(
        CHAT, text, "chat_history", None, subject=subject,
        object="кофе", **kwargs)


def test_durability_decision_marks_explicit_nonpersonal_kind():
    durable = {"subject": "Леха", "subject_type": "world",
               "predicate": "любит", "object": "кофе",
               "kind": "durable_fact"}
    world = {"subject": "Путин", "subject_type": "world",
             "predicate": "заявил", "object": "о встрече",
             "kind": "world_news"}
    quote = {"subject": "автор канала", "subject_type": "world",
             "predicate": "сказал", "object": "ставка вырастет",
             "kind": "quote"}
    assert fact_durability_decision(durable).get(
        "nonpersonal_kind", "") == ""
    assert fact_durability_decision(world)["nonpersonal_kind"] == "world_news"
    assert fact_durability_decision(quote)["nonpersonal_kind"] == "quote"


@pytest.mark.asyncio
async def test_new_personal_fact_with_subject_ref_is_not_world():
    db = await _db()
    try:
        await db.save_smart_message(
            UID, CHAT, "Леха любит кофе", None, NOW, "text", "Леха",
            message_id=100)
        fact_id = await _insert_fact(db, "Леха любит кофе")
        host = _AttachHost(db)
        await MemoryManager._attach_fact_provenance(
            host, CHAT, fact_id, "chat_history", "Леха", None, None, {},
            declared_method="world_knowledge",
            declared_kind="world_knowledge")
        cursor = await db.db.execute(
            "SELECT attribution_method, assertion_kind, subject_ref_id "
            "FROM graph_facts WHERE id=?", (fact_id,))
        row = await cursor.fetchone()
        assert row["subject_ref_id"] is not None
        assert row["attribution_method"] in ("third_party", "self_report")
        assert row["assertion_kind"] != "world_knowledge"
        assert row["attribution_method"] != "world_knowledge"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_explicit_world_news_stays_world_and_existing_rows_unchanged():
    db = await _db()
    try:
        await db.save_smart_message(
            UID, CHAT, "Леха любит кофе", None, NOW, "text", "Леха",
            message_id=100)
        legacy_id = await _insert_fact(
            db, "Леха любит кофе (старая строка)",
            attribution_method="world_knowledge",
            assertion_kind="world_knowledge")
        new_id = await _insert_fact(db, "Леха любит чай")
        host = _AttachHost(db)
        await MemoryManager._attach_fact_provenance(
            host, CHAT, new_id, "chat_history", "Леха", None, None, {},
            declared_method="world_knowledge",
            declared_kind="world_knowledge",
            nonpersonal_kind="world_news")
        cursor = await db.db.execute(
            "SELECT attribution_method, assertion_kind, subject_ref_id "
            "FROM graph_facts WHERE id=?", (new_id,))
        row = await cursor.fetchone()
        assert row["attribution_method"] == "world_knowledge"
        assert row["assertion_kind"] == "world_knowledge"
        # Existing row is not rewritten by the new-fact producer.
        cursor = await db.db.execute(
            "SELECT attribution_method, assertion_kind "
            "FROM graph_facts WHERE id=?", (legacy_id,))
        legacy = await cursor.fetchone()
        assert legacy["attribution_method"] == "world_knowledge"
        assert legacy["assertion_kind"] == "world_knowledge"
    finally:
        await db.close()
