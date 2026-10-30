"""EVOL-021 — «Истории памяти»: смысл эпизодов и честная группа восстановления.

TEST-LIFECYCLE: CONTRACT (plans/current_task.md EVOL-021).

Проверяется:
  * форма компактной семантической карточки эпизода (заголовок, «что
    произошло», период, чат, участники, число связанных сообщений, полнота,
    проверка);
  * незавершённые эпизоды уходят в группу «Требуют восстановления» с НАСТОЯЩЕЙ
    причиной и числом затронутых записей — и не выдаются за новые истории;
  * техническая заглушка («Эпизод 1780…») не превращается в заголовок, сюжет
    не выдумывается;
  * старый эпизод, обнаруженный сегодня, помечается `discovered_old_event`;
  * два чата изолированы, карточка чужого чата недоступна;
  * открытие витрины не делает LLM-вызовов.
"""
import inspect
import json
import time

import pytest

from services import episode_diagnostics as ed
from services.database import DatabaseService

NOW = int(time.time())
DAY = 86400


async def _db():
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _episode(db, *, episode_id, chat_id=-100, title="", summary="",
                   claims=None, keys=None, participants=None,
                   start=None, end=None, discovered=None, updated=None):
    await db.db.execute(
        "INSERT INTO mca_episodes (episode_id, chat_id, title, summary, "
        "participants_json, event_start_ts, event_end_ts, discovered_at, "
        "updated_at, claims_json, message_keys_json, segment_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (episode_id, chat_id, title, summary,
         json.dumps(participants or [], ensure_ascii=False),
         start, end,
         discovered if discovered is not None else NOW - 3600,
         updated if updated is not None else NOW - 3600,
         json.dumps(claims or [], ensure_ascii=False),
         json.dumps(keys or []), f"seg-{episode_id}"))
    await db.db.commit()


async def _story(db, *, story_id, chat_id=-100, title="", summary="",
                 verification="unknown", state="open", excluded=0):
    await db.db.execute(
        "INSERT INTO mca_stories (story_id, chat_id, title, summary, "
        "participants_json, discovered_at, updated_at, claims_json, state, "
        "verification, excluded_from_retrieval, expected_version) "
        "VALUES (?, ?, ?, ?, '[]', ?, ?, '[]', ?, ?, ?, 1)",
        (story_id, chat_id, title, summary, NOW - 7200, NOW - 7200, state,
         verification, excluded))
    await db.db.commit()


async def _link(db, story_id, episode_id, order_no=0):
    await db.db.execute(
        "INSERT INTO mca_story_episode_links (story_id, episode_id, order_no) "
        "VALUES (?, ?, ?)", (story_id, episode_id, order_no))
    await db.db.commit()


@pytest.mark.asyncio
async def test_ready_episode_has_compact_semantic_shape():
    db = await _db()
    try:
        await _episode(
            db, episode_id="ep-ready", chat_id=-100,
            title="Спор про деплой",
            summary="Обсуждали порядок выкладки и отката",
            claims=[{"text": "Решили сначала откат, потом деплой"}],
            keys=[f"-100:tg:{1000 + i}" for i in range(3)],
            participants=["1", "2", "3", "4", "5", "6", "7"],
            start=NOW - 7200, end=NOW - 5400)
        await _story(db, story_id="st-1", title="Спор про деплой",
                     summary="Порядок выкладки", verification="verified")
        await _link(db, "st-1", "ep-ready")

        body = await ed.episode_feed(db, -100, now=NOW)
        assert body["state"] == "ok"
        assert body["total_ready"] == 1
        assert body["total_episodes"] == 1
        item = body["items"][0]
        assert item["episode_id"] == "ep-ready"
        assert item["chat_id"] == -100
        assert item["title"] == "Спор про деплой"
        assert item["title_source"] == "pipeline"
        assert item["what_happened"].startswith("Обсуждали порядок")
        assert item["event_period"]["start"] == NOW - 7200
        assert item["event_period"]["end"] == NOW - 5400
        assert item["event_period"]["known"] is True
        assert item["participants"]["primary"] == ["1", "2", "3", "4", "5"]
        assert item["participants"]["others_count"] == 2
        assert item["linked_messages"]["count"] == 3
        assert item["linked_messages"]["known"] is True
        assert item["completeness"] == ed.COMPLETENESS_READY
        assert item["verification"]["status"] == "verified"
        assert item["verification"]["source"] == "story"
        assert item["story"]["linked"] is True
        assert item["retrievable"] is True
        assert item["needs_recovery"] is False
        assert item["discovery_kind"] == ed.DISCOVERY_TODAY
        # Сводка восстановления пуста — без выдуманных записей.
        assert body["requires_recovery"]["count"] == 0

        card = await ed.episode_card(db, -100, "ep-ready", now=NOW)
        assert card is not None
        assert card["episode_id"] == "ep-ready"
        assert card["title"] == "Спор про деплой"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stub_title_is_not_renamed_into_a_story():
    db = await _db()
    try:
        await _episode(db, episode_id="ep-stub", title="Эпизод 1780282318",
                       keys=[f"-100:tg:{i}" for i in range(3)],
                       participants=["1"], start=NOW - 5 * DAY,
                       end=NOW - 5 * DAY)
        body = await ed.episode_feed(db, -100, now=NOW)
        assert body["items"] == []
        assert body["requires_recovery"]["count"] == 1
        item = body["requires_recovery"]["by_reason"][0]
        assert item["reason"] == ed.REASON_SUMMARY_NOT_BUILT
        assert item["count"] == 1
        assert item["reason_label"]

        group = await ed.recovery_group(db, -100, now=NOW)
        assert group["count"] == 1
        assert group["group_label"] == "Требуют восстановления"
        entry = group["items"][0]
        # Заглушка не становится заголовком истории.
        assert entry["title"] is None
        assert entry["status"] == ed.RECOVERY_PENDING
        assert entry["reason"] == ed.REASON_SUMMARY_NOT_BUILT
        assert group["note"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_no_sources_means_unrecoverable_with_real_reason():
    db = await _db()
    try:
        await _episode(db, episode_id="ep-nosrc", title="", summary="",
                       keys=[], claims=[], start=NOW - 30 * DAY,
                       end=NOW - 30 * DAY)
        group = await ed.recovery_group(db, -100, now=NOW)
        assert group["count"] == 1
        entry = group["items"][0]
        assert entry["reason"] == ed.REASON_NO_SOURCE_MESSAGES
        assert entry["status"] == ed.RECOVERY_UNRECOVERABLE
        assert entry["linked_messages"]["known"] is False
        assert "ключи источников не сохранены" in entry["reason_label"]
        assert group["state"] == "ok"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_title_falls_back_to_real_context_not_decoration():
    db = await _db()
    try:
        await _episode(db, episode_id="ep-claim", title="История 1650000000",
                       claims=[{"text": "Договорились перенести релиз"}],
                       keys=["-100:tg:7"], start=NOW - 4000,
                       end=NOW - 3000)
        body = await ed.episode_feed(db, -100, now=NOW)
        item = body["items"][0]
        assert item["title"] == "Договорились перенести релиз"
        assert item["title_source"] == "first_claim"
        assert item["needs_recovery"] is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_old_event_discovered_today_is_marked_discovered():
    db = await _db()
    try:
        await _episode(db, episode_id="ep-old", title="Старый разговор",
                       summary="Обсуждали событие месячной давности",
                       claims=[{"text": "Обсуждали событие"}],
                       keys=["-100:tg:9"],
                       start=NOW - 40 * DAY, end=NOW - 40 * DAY,
                       discovered=NOW - 1800)
        body = await ed.episode_feed(db, -100, now=NOW)
        item = body["items"][0]
        assert item["discovery_kind"] == ed.DISCOVERY_OLD_EVENT
        assert item["discovery_label"] == "Обнаружено сегодня (событие ранее)"
        assert item["discovered_at"] == NOW - 1800
        assert item["event_period"]["end"] == NOW - 40 * DAY
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_two_chats_are_isolated_and_foreign_card_is_hidden():
    db = await _db()
    try:
        await _episode(db, episode_id="ep-a", chat_id=-100,
                       title="Чат А", summary="Событие в чате А",
                       claims=[{"text": "Событие в чате А"}],
                       keys=["-100:tg:1"], start=NOW - 1000, end=NOW - 900)
        await _episode(db, episode_id="ep-b1", chat_id=-200,
                       title="Чат Б", summary="Событие в чате Б",
                       claims=[{"text": "Событие в чате Б"}],
                       keys=["-200:tg:2"], start=NOW - 800, end=NOW - 700)
        await _episode(db, episode_id="ep-b2", chat_id=-200, title="",
                       keys=[], start=NOW - 600, end=NOW - 500)

        first = await ed.episode_feed(db, -100, now=NOW)
        second = await ed.episode_feed(db, -200, now=NOW)
        assert [i["episode_id"] for i in first["items"]] == ["ep-a"]
        assert [i["episode_id"] for i in second["items"]] == ["ep-b1"]
        assert first["requires_recovery"]["count"] == 0
        assert second["requires_recovery"]["count"] == 1
        assert first["scope"] == "chat:-100"
        assert second["scope"] == "chat:-200"

        # Карточка чужого чата недоступна — изоляция не зависит от роутера.
        assert await ed.episode_card(db, -200, "ep-a", now=NOW) is None
        assert await ed.episode_card(db, -100, "ep-a", now=NOW) is not None
        group_b = await ed.recovery_group(db, -200, now=NOW)
        assert [i["episode_id"] for i in group_b["items"]] == ["ep-b2"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_verification_and_retrieval_come_from_linked_story_only():
    db = await _db()
    try:
        await _episode(db, episode_id="ep-x", title="Тема",
                       summary="Что-то произошло",
                       claims=[{"text": "Что-то произошло"}],
                       keys=["-100:tg:11"], start=NOW - 900, end=NOW - 800)
        body = await ed.episode_feed(db, -100, now=NOW)
        item = body["items"][0]
        assert item["verification"]["status"] == "not_linked"
        assert item["verification"]["source"] == "none"
        assert item["retrievable"] is None

        await _story(db, story_id="st-x", title="Тема", summary="Итог",
                     verification="tentative", excluded=1)
        await _link(db, "st-x", "ep-x")
        body2 = await ed.episode_feed(db, -100, now=NOW)
        item2 = body2["items"][0]
        assert item2["verification"]["status"] == "tentative"
        assert item2["retrievable"] is False
        assert item2["story"]["excluded_from_retrieval"] is True
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_empty_archive_is_honest_empty_state():
    db = await _db()
    try:
        body = await ed.episode_feed(db, -100, now=NOW)
        assert body["state"] == "empty"
        assert body["items"] == []
        assert body["last_build"]["last_build_at"] is None
        assert body["last_build"]["backfill_state"] in (None, "not_run")
        group = await ed.recovery_group(db, -100, now=NOW)
        assert group["count"] == 0
        assert group["state"] == "empty"
    finally:
        await db.close()


def test_summary_view_makes_no_llm_calls():
    """Витрина эпизодов не имеет LLM-пути: ни импорта клиента, ни generate."""
    source = inspect.getsource(ed)
    assert "llm_client" not in source
    assert "generate(" not in source
    assert "chat_with_tools" not in source
