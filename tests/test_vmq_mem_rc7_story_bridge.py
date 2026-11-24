"""VMQ-MEM RC7 (B2 narrowed): new-story → episode links → message anchors.

Проверяет production-путь: `mca_episodes.story_message_anchors` и
`DirectChatService._build_old_episodes` на настоящем SQLite. Legacy 5–16
mapping — RFL-7: не воссоздаётся, пустой мост честно остаётся пустым.
"""
import asyncio
import datetime
import types
from unittest.mock import MagicMock

import pytest

from services import direct_chat_service as dcs
from services import mca_gates
from services import mca_retrieval_context as rc
from services.database import DatabaseService, EPISODE_UNKNOWN_OUTCOME
from services.direct_chat_service import DirectChatService
from services.mca_episodes import EpisodeRepository, story_message_anchors
from services.summary_aliases import AliasResolver
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT = -1002661910336
T_2024 = int(datetime.datetime(
    2024, 6, 1, 12, tzinfo=datetime.timezone.utc).timestamp())
T_2025 = int(datetime.datetime(
    2025, 6, 1, 12, tzinfo=datetime.timezone.utc).timestamp())
NOW = T_2025 + 3600


class _NoMemory:
    async def retrieve_fact_candidates(self, *a, **k):
        return []


async def _make_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _seed_message(db, text, ts, *, tg_id, author="Лёха"):
    return await db.save_smart_message(
        42, CHAT, text, None, ts, "text", author, message_id=tg_id)


async def _seed_story(db, *, keys, title="Дроны над полем",
                      summary="Самоделка и обломки", seg="rc7-seg"):
    repo = EpisodeRepository(db)
    episode_id = await repo.insert_episode(
        chat_id=CHAT, title="Эпизод", summary=summary,
        participants=["42"], claims=[], event_start=T_2024,
        event_end=T_2025, outcome=EPISODE_UNKNOWN_OUTCOME,
        outcome_known=False, open_questions=[], message_keys=keys,
        seg_key=seg, extraction_version="rc7", now=NOW)
    assert episode_id
    story_id, _vid, _created = await repo.upsert_story(
        chat_id=CHAT, title=title, summary=summary, participants=["42"],
        claims=[], event_start=T_2024, event_end=T_2025,
        outcome=EPISODE_UNKNOWN_OUTCOME, state="open",
        verification="unknown", open_questions=[],
        episode_ids=[episode_id], extractor_version="rc7", now=NOW)
    return story_id


def _service(db) -> DirectChatService:
    memory = _NoMemory()
    router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory,
                                 aliases=None, db=db))
    return DirectChatService(memory, db, MagicMock(),
                             AliasResolver("{}"), tool_router=router)


@pytest.fixture
def gates_on(monkeypatch):
    monkeypatch.setattr(mca_gates, "retrieval_context_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "episodes_compiler_facade_enabled",
                        lambda: True)


@pytest.mark.asyncio
async def test_story_bridge_returns_message_anchors(gates_on):
    db = await _make_db()
    try:
        # Тексты НЕ содержат слова запроса: exact/lexical не дадут якорей,
        # единственный путь к строкам — story→episode→message_keys.
        await _seed_message(db, "мы запустили самоделку в поле", T_2024,
                            tg_id=201)
        await _seed_message(db, "потом нашли обломки у реки", T_2025,
                            tg_id=202)
        story_id = await _seed_story(
            db, keys=[f"{CHAT}:tg:201", f"{CHAT}:tg:202"])
        anchors = await story_message_anchors(db, CHAT, [story_id])
        assert anchors == {story_id: ["tg:201", "tg:202"]}

        block, stats = await _service(db)._build_old_episodes(
            CHAT, "дроны", [], {})
        assert block.startswith("<Old_Episode>")
        assert "самоделку в поле" in block
        assert "обломки у реки" in block
        assert stats["count"] >= 1
        assert stats["story_anchor_candidates"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_story_bridge_skips_missing_message_keys(gates_on):
    db = await _make_db()
    try:
        await _seed_message(db, "живая строка", T_2024, tg_id=301)
        story_id = await _seed_story(
            db, keys=[f"{CHAT}:tg:999999", f"{CHAT}:tg:301"],
            seg="rc7-missing")
        anchors = await story_message_anchors(db, CHAT, [story_id])
        # Несуществующая строка не превращается в якорь.
        assert anchors == {story_id: ["tg:301"]}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_story_without_links_or_keys_returns_empty(gates_on):
    db = await _make_db()
    try:
        story_id = await _seed_story(db, keys=[], seg="rc7-nokeys")
        # Нет ключей эпизода — нет моста.
        assert await story_message_anchors(db, CHAT, [story_id]) == {}
        # Нет самих links (store без связи) — тоже честно пусто.
        await db.db.execute(
            "DELETE FROM mca_story_episode_links WHERE story_id = ?",
            (story_id,))
        await db.db.commit()
        assert await story_message_anchors(db, CHAT, [story_id]) == {}
        block, stats = await _service(db)._build_old_episodes(
            CHAT, "дроны", [], {})
        assert block == ""
        assert stats["count"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_legacy_lore_story_has_no_invented_anchor(gates_on):
    db = await _make_db()
    try:
        await _seed_message(db, "старая строка", T_2024, tg_id=401)
        legacy_id = await db.upsert_lore_story(
            CHAT, "дроны-legacy", "Дроны над полем",
            "старый рассказ 5-16", T_2024)
        block, stats = await _service(db)._build_old_episodes(
            CHAT, "дроны", [], {})
        # RFL-7: legacy-история без новых links/keys — пусто, без выдумки.
        assert block == ""
        assert stats["count"] == 0
        assert await story_message_anchors(
            db, CHAT, [str(legacy_id)]) == {}
        # Никакого нового mapping/backfill не создано.
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM mca_story_legacy_links")
        assert (await cursor.fetchone())["n"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_episode_priority_does_not_replace_facade(gates_on):
    db = await _make_db()
    try:
        assert mca_gates.episodes_compiler_facade_enabled() is True
        # E1 (subject-threshold) не менялся этим инкрементом.
        assert rc.PERIOD_MIN_SHARED_STEMS == 2
        story_id = await _seed_story(db, keys=[], seg="rc7-facade")
        from services.mca_episodes import list_stories_for_retrieval
        rows = await list_stories_for_retrieval(db, CHAT)
        assert any(str(row.get("id")) == story_id
                   and row.get("kind") == "story" for row in rows)
    finally:
        await db.close()
