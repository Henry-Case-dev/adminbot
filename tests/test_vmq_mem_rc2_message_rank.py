"""VMQ-MEM RC2 (D3): explicit-year message rank inside a bounded window."""
import datetime
import time

import pytest

from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.mca_retrieval_context import (
    RetrievalRequest,
    retrieve,
    year_time_bounds,
)
from services.summary_aliases import AliasResolver

CHAT = -1002661910336
UID = 42
TARGET_TEXT = "Ну вот был у меня конфликт с Олей, но оба себя нормально повели"
QUERY = "что известно о конфликте Корсара с Олей в 2025 году?"


def _ts(year, month, day, hour=12):
    return int(datetime.datetime(
        year, month, day, hour, tzinfo=datetime.timezone.utc).timestamp())


async def _db(tmp_path):
    db = DatabaseService(str(tmp_path / "rc2.db"))
    await db.initialize()
    return db


async def _seed(db):
    target = await db.save_smart_message(
        UID, CHAT, TARGET_TEXT, None, _ts(2025, 4, 5), "text", "Оля")
    # December 2025 messages match the OLD full query via "2025"/"году" but
    # carry no conflict/Olya content. They must not fill the new rank window.
    december = []
    for day in range(1, 21):
        december.append(await db.save_smart_message(
            UID, CHAT, f"в 2025 году всё спокойно, день {day}", None,
            _ts(2025, 12, day), "text", "Гений"))
    old_2024 = await db.save_smart_message(
        UID, CHAT, "в 2024 году был конфликт с Олей", None,
        _ts(2024, 6, 1), "text", "Гений")
    old_2026 = await db.save_smart_message(
        UID, CHAT, "в 2026 году был конфликт с Олей", None,
        _ts(2026, 1, 1), "text", "Гений")
    return target, december, old_2024, old_2026


async def _retrieve(db, rank: bool):
    bounds = year_time_bounds(2025)
    started = time.perf_counter()
    result = await retrieve(db, None, RetrievalRequest(
        chat_id=CHAT, query=QUERY, mode="history", top_k=8,
        channels=("lexical",), no_age_bias=True,
        time_from=bounds[0], time_to=bounds[1],
        lexical_time_window=True, lexical_window_rank=rank,
        include_self=True, include_direct_reply=True,
        memory_scope="auto"))
    return result, (time.perf_counter() - started) * 1000


def _message_ids(result):
    return [int(c.entity_id) for c in result.candidates or ()
            if c.entity_type == "message"]


@pytest.mark.asyncio
async def test_rc2_explicit_year_rank_finds_april_not_december(tmp_path):
    db = await _db(tmp_path)
    try:
        target, december, old_2024, old_2026 = await _seed(db)
        old_result, _old_ms = await _retrieve(db, False)
        old_ids = _message_ids(old_result)
        # RED: order="time" + full query returns December, not April target.
        assert target not in old_ids
        assert set(old_ids) & set(december)

        new_result, new_ms = await _retrieve(db, True)
        new_ids = _message_ids(new_result)
        # GREEN: narrow content match + rank inside the 2025 window.
        assert target in new_ids[:8]
        assert old_2024 not in new_ids
        assert old_2026 not in new_ids
        assert not (set(new_ids) & set(december))
        assert new_ms < 2000, new_ms
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rc2_build_old_episodes_uses_rank_window(tmp_path):
    db = await _db(tmp_path)
    try:
        target, december, _old_2024, _old_2026 = await _seed(db)
        service = DirectChatService(memory=None, db=db, llm=None,
                                    aliases=AliasResolver("{}"))
        block, stats = await service._build_old_episodes(
            CHAT, QUERY, [], {})
        assert block.startswith("<Old_Episode>")
        assert stats["year_window"] == [2025]
        assert stats["year_window_order"] == "rank"
        assert TARGET_TEXT[:40] in block
        assert stats["count"] >= 1
        assert stats["spans"]
    finally:
        await db.close()
