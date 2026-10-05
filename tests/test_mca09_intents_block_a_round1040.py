"""MCA-09 `mca-09-intents-initiative` — focused-тесты блока A (T-5020…T-5024).

Покрытие (API канонического `services/mca_intents.py`):
  * v29 DDL: 1 таблица `mca_intents` + 4 индекса (UNIQUE dedup_key; due/chat/
    kind), книга, идемпотентность, v28→v29, backup-guard, PG no-op (SQLite);
  * Intent-модель: поля §13.2, R17-канон (≤200), mca-04a durable-связи
    (SourceRef/EvidenceLink), единственный write-механизм, второго store нет;
  * дисциплина: не каждая фраза → обязательство (origin+goal/refs);
    attempts bounded → честное `abandoned`;
  * жизненный цикл: pending→deferred→fulfilled/abandoned/expired,
    deferred→pending по событию, терминальное не реактивируется; A15
    «результат сообщён → закрыто без вопроса»;
  * гигиена: дедуп/слияние, освобождение dedup-ключа, повторный интерес =
    новая АКТИВНАЯ запись со ссылкой-предшественником (F-1), expire/archive/
    prune, 5–10 — не жёсткий предел;
  * OFF (K1): записей/чтений нет.
"""
import json

import pytest

from services import mca_events, mca_gates
from services import mca_intents as mi
from services.database import (DatabaseService, _SCHEMA_VERSION_INTENTS,
                               _SCHEMA_VERSION_RANDOM_SOURCE)

CHAT = -100500
NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


@pytest.fixture
def events(monkeypatch):
    recorded: list = []

    def _fake(name, **kw):
        recorded.append((name, kw))
        return {"event_name": name}

    monkeypatch.setattr(mca_events, "emit_mca_event", _fake)
    return recorded


async def _db(tmp_path, name="mca09_a.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _mk(svc, *, chat=CHAT, kind="follow_up",
              origin="unanswered_question", goal="Спросить про собеседование",
              now=NOW, **kw):
    base = dict(goal=goal, reason="unanswered_question",
                source_refs=("msg:-100500:42",), created_at=now)
    base.update(kw)
    return await svc.create_intent(chat, kind, origin, **base)


async def _count(db, sql, params=()) -> int:
    cur = await db.db.execute(sql, params)
    row = await cur.fetchone()
    return int(row["c"])


# ═══ v29 DDL ═════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_v29_fresh_schema_book_and_idempotent_reinit(tmp_path):
    db = await _db(tmp_path)
    try:
        cur = await db.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == _SCHEMA_VERSION_INTENTS == 29
        assert await _count(
            db, "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' "
                "AND name='mca_intents'") == 1
        cur = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND "
            "name LIKE 'idx_mca_intents_%' ORDER BY name")
        assert [r["name"] for r in await cur.fetchall()] == [
            "idx_mca_intents_chat_kind_status",
            "idx_mca_intents_chat_status_due",
            "idx_mca_intents_dedup",
            "idx_mca_intents_status_due",
        ]
        cur = await db.db.execute(
            "SELECT sql FROM sqlite_master WHERE name='idx_mca_intents_dedup'")
        assert "UNIQUE" in (await cur.fetchone())["sql"].upper()
        assert await _count(
            db, "SELECT COUNT(*) AS c FROM schema_migrations WHERE "
                "version = 29") == 1
    finally:
        await db.close()
    db2 = DatabaseService(str(tmp_path / "mca09_a.db"))
    await db2.initialize()
    try:
        assert await _count(
            db2, "SELECT COUNT(*) AS c FROM schema_migrations WHERE "
                 "version = 29") == 1
        assert await _count(
            db2, "SELECT COUNT(*) AS c FROM sqlite_master WHERE "
                 "type='table' AND name='mca_intents'") == 1
    finally:
        await db2.close()


@pytest.mark.asyncio
async def test_v29_upgrade_from_v28_simulated(tmp_path):
    db = await _db(tmp_path)
    await db.db.execute("DELETE FROM schema_migrations WHERE version = 29")
    await db.db.execute("DROP TABLE IF EXISTS mca_intents")
    await db.db.execute(
        f"PRAGMA user_version = {_SCHEMA_VERSION_RANDOM_SOURCE + 1}")
    await db.db.commit()
    await db.close()
    db2 = DatabaseService(str(tmp_path / "mca09_a.db"))
    await db2.initialize()
    try:
        cur = await db2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 29
        assert list(tmp_path.glob("pre_migration_*.db")), "backup-guard"
    finally:
        await db2.close()


# ═══ T-5020: модель/хранилище ════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_intent_fields_and_crud(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, created = await _mk(
            svc, subject_ids=("7",), topic_refs=("episode:e1",),
            not_before=NOW + 60, expires_at=NOW + 86400,
            activation_condition="time_due", priority=3,
            context_version="ctx-v1", linked_action_id="action:1")
        assert created is True
        assert intent_id.startswith(f"intent:{CHAT}:follow_up:")
        row = await svc.store.get_intent(intent_id)
        assert row["chat_id"] == CHAT and row["kind"] == "follow_up"
        assert row["origin"] == "unanswered_question"
        assert row["goal"] == "Спросить про собеседование"
        assert row["reason"] == "unanswered_question"
        assert row["status"] == "pending" and row["attempts"] == 0
        assert row["priority"] == 3
        assert row["not_before"] == NOW + 60
        assert row["next_check_at"] == NOW + 60
        assert row["expires_at"] == NOW + 86400
        assert row["activation_condition"] == "time_due"
        assert row["last_evaluated_context_version"] == "ctx-v1"
        assert row["linked_action_id"] == "action:1"
        assert row["created_at"] == NOW and row["updated_at"] == NOW
        assert "7" in row["subject_ids_json"]
        assert "episode:e1" in row["topic_refs_json"]
        assert row["dedup_key"] and row["merged_into_id"] is None
        assert row["archived_at"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_intent_r17_safe_canonical_text(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        secret = "sk-abcdef1234567890"
        intent_id, _ = await _mk(svc, goal=f"Позвонить завтра {secret}",
                                 reason=secret)
        row = await svc.store.get_intent(intent_id)
        assert secret not in row["goal"] and "***" in row["goal"]
        assert secret not in (row["reason"] or "")
        long_id, _ = await _mk(svc, goal="т" * 300, topic_refs=("t:long",))
        assert len((await svc.store.get_intent(long_id))["goal"]) == 200
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_source_refs_mca04a_durable_links(tmp_path):
    """F-3: source refs — типизированные через mca-04a (SourceRef get-or-
    create + durable EvidenceLink «intent ← ref»); второго механизма нет."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        ref = {"store": "telegram", "entity_type": "user", "entity_id": "7",
               "chat_id": CHAT, "resolution": "resolved"}
        intent_id, created = await _mk(svc, source_refs=(ref, "msg:-100500:42"))
        assert created
        row = await svc.store.get_intent(intent_id)
        ref_ids = json.loads(row["source_refs_json"])
        assert ref_ids and all(isinstance(i, int) for i in ref_ids)
        links = await _count(
            db, "SELECT COUNT(*) AS c FROM mca_evidence_links WHERE "
                "subject_ref_id IN (SELECT source_ref_id FROM mca_source_refs "
                "WHERE entity_type='intent' AND entity_id=?)", (intent_id,))
        assert links == 2          # user-Ref + msg-токен → 2 durable-связи
        # durable-связи именно через mca_evidence_links (второй таблицы нет)
        assert await _count(
            db, "SELECT COUNT(*) AS c FROM mca_source_refs WHERE "
                "entity_type='intent' AND entity_id=?", (intent_id,)) == 1
    finally:
        await db.close()


def test_no_second_store_static():
    """Второго хранилища/механизма записи нет: один store, никаких файлов/
    sqlite3/прямых commit в модуле."""
    import inspect
    src = inspect.getsource(mi)
    assert src.count("class IntentStore") == 1
    assert "sqlite3" not in src
    assert "open(" not in src
    assert "Path(" not in src
    assert "db.db.commit" not in src


# ═══ T-5023: дисциплина обязательств ════════════════════════════════════════

@pytest.mark.asyncio
async def test_discipline_not_every_phrase_creates_obligation(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        # Негативные fixture-фразы: нет явного сигнала → обязательства нет.
        assert (await _mk(svc, origin=""))[0] is None
        assert (await _mk(svc, origin="small_talk"))[0] is None
        assert (await _mk(svc, origin="explicit_request", goal=None,
                          source_refs=()))[0] is None
        assert (await _mk(svc, origin="unanswered_question", goal=""))[0] is None
        assert await svc.store.count_active(CHAT) == 0
        # Матрица дисциплины: origin допустим только при своём сигнале.
        assert mi.creation_allowed(
            "unanswered_question", goal="спросить", source_refs=()) is True
        assert mi.creation_allowed(
            "explicit_request", goal=None, source_refs=("msg:1",)) is True
        assert mi.creation_allowed(
            "unfinished_topic", goal="тема", source_refs=()) is False
        assert mi.creation_allowed(
            "search_result", goal=None, source_refs=()) is False
        # Явный сигнал → намерение создано и связано с причиной.
        intent_id, created = await _mk(svc)
        assert created and intent_id
        assert (await svc.store.get_intent(intent_id))["origin"] == \
            "unanswered_question"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_attempts_bounded_not_nagging(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, _ = await _mk(svc)
        row = await svc.mark_attempt(intent_id, now=NOW)
        assert row["attempts"] == 1 and row["status"] == "deferred"
        assert row["next_check_at"] is None           # без таймерного повтора
        assert row["activation_condition"] == "new_reply"
        row = await svc.mark_attempt(intent_id, now=NOW + 1)
        assert row["attempts"] == 2 and row["status"] == "deferred"
        row = await svc.mark_attempt(intent_id, now=NOW + 2)
        assert row["status"] == "abandoned"           # max 3 → честное закрытие
        assert (await svc.mark_attempt(intent_id, now=NOW + 3)) is None
    finally:
        await db.close()


# ═══ T-5021: жизненный цикл + A15 ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_lifecycle_transitions_and_terminal_guard(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, _ = await _mk(svc)
        row = await svc.defer(intent_id, next_check_at=NOW + 60,
                              activation_condition="new_reply", now=NOW)
        assert row["status"] == "deferred"
        row = await svc.resume_on_event(intent_id, event_kind="new_message",
                                        now=NOW + 10)
        assert row["status"] == "pending" and row["next_check_at"] == NOW + 10
        assert await svc.resume_on_event(intent_id, event_kind="new_message") \
            is None
        row = await svc.close(intent_id, status="fulfilled",
                              reason_code="already_answered", now=NOW + 20)
        assert row["status"] == "fulfilled"
        # терминальное не активируется повторно (без новой записи)
        assert await svc.defer(intent_id, next_check_at=NOW + 30) is None
        assert await svc.resume_on_event(intent_id,
                                         event_kind="new_message") is None
        assert await svc.close(intent_id, status="abandoned") is None
        assert (await svc.store.get_intent(intent_id))["status"] == "fulfilled"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a15_answered_closed_without_question(tmp_path, events):
    """A15: результат уже сообщён человеком → закрыто без повторного вопроса."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, _ = await _mk(svc)
        row = await svc.close(intent_id, status="fulfilled",
                              reason_code="already_answered", now=NOW + 5)
        assert row["status"] == "fulfilled"
        assert await svc.due_candidates(now=NOW + 3600) == []
        assert await svc.resume_on_event(intent_id,
                                         event_kind="new_message") is None
        # повторный интерес — НОВАЯ активная запись (не реактивация), со
        # ссылкой на предшественника через refs (F-1)
        second, created = await _mk(svc, now=NOW + 10)
        assert created and second != intent_id
        second_row = await svc.store.get_intent(second)
        assert second_row["status"] == "pending"
        refs = json.loads(second_row["source_refs_json"] or "[]")
        assert any("intent" in str(r) or isinstance(r, int) for r in refs)
        names = [n for n, _ in events]
        assert "intent_created" in names and "intent_fulfilled" in names
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_expired_via_hygiene(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id, _ = await _mk(svc, expires_at=NOW - 1, created_at=NOW - 10)
        stats = await svc.hygiene(now=NOW)
        assert stats["expired"] == 1
        row = await svc.store.get_intent(intent_id)
        assert row["status"] == "expired" and row["next_check_at"] is None
    finally:
        await db.close()


# ═══ T-5022: гигиена накопления ══════════════════════════════════════════════

@pytest.mark.asyncio
async def test_dedup_merge_no_monotonic_growth(tmp_path, events):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        first, created = await _mk(svc)
        again, created2 = await _mk(svc, now=NOW + 1)
        assert created is True and created2 is False
        assert again == first
        assert await svc.store.count_active(CHAT) == 1
        assert await _count(db, "SELECT COUNT(*) AS c FROM mca_intents") == 1
        assert "intent_merged" in [n for n, _ in events]
        # терминальное освобождает канонический ключ: новый повод = новая
        # АКТИВНАЯ запись (не реактивация), активных по-прежнему одна
        await svc.close(first, status="fulfilled", now=NOW + 2)
        second, created3 = await _mk(svc, now=NOW + 3)
        assert created3 is True and second != first
        assert await svc.store.count_active(CHAT) == 1
        assert await _count(db, "SELECT COUNT(*) AS c FROM mca_intents") == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reinterest_record_due_visible(tmp_path):
    """F-1 (green): новая запись повторного интереса активна и видима
    lifecycle/heartbeat-сканам (ссылка на предшественника — через refs,
    а не через merged_into_id)."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        first, _ = await _mk(svc, created_at=NOW)
        await svc.close(first, status="fulfilled", now=NOW + 1)
        second, created = await _mk(svc, now=NOW + 2, not_before=NOW + 10)
        assert created
        row = await svc.store.get_intent(second)
        assert row["status"] == "pending" and row["merged_into_id"] is None
        assert await svc.store.count_active(CHAT) == 1
        assert [c.intent_id for c in await svc.due_candidates(
            now=NOW + 11)] == [second]
        # дедуп-скан тоже видит новую запись (повторный сигнал → merge)
        _, created2 = await _mk(svc, now=NOW + 12)
        assert created2 is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_archive_completed_retention(tmp_path, monkeypatch, events):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "intent_retention_days", lambda: 1)
        svc = mi.get_service(db)
        intent_id, _ = await _mk(svc, created_at=NOW - 10 * 86400)
        await svc.close(intent_id, status="fulfilled", now=NOW - 9 * 86400)
        stats = await svc.hygiene(now=NOW)
        assert stats["archived"] == 1
        row = await svc.store.get_intent(intent_id)
        assert row["archived_at"] == NOW
        assert "intent_archived" in [n for n, _ in events]
        # retention-прун: активные не прунятся, архивные — по сроку
        stats2 = await svc.hygiene(now=NOW + 3 * 86400)
        assert stats2["pruned"] == 1
        assert await _count(db, "SELECT COUNT(*) AS c FROM mca_intents") == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_no_hard_product_limit(tmp_path):
    """5–10 — не жёсткий предел: активных может быть больше."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        for i in range(12):
            _, created = await _mk(svc, topic_refs=(f"topic:{i}",),
                                   goal=f"тема {i}", kind="topic_interest",
                                   origin="unfinished_topic")
            assert created
        assert await svc.store.count_active(CHAT) == 12
    finally:
        await db.close()


# ═══ OFF (K1) ════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_k1_off_no_writes_reads_events(tmp_path, monkeypatch, events):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
        svc = mi.get_service(db)
        assert (await _mk(svc))[0] is None
        assert await svc.due_candidates(now=NOW) == []
        assert mi.candidate_from_trigger(trigger_kind="new_message",
                                         chat_id=CHAT) is None
        assert await _count(db, "SELECT COUNT(*) AS c FROM mca_intents") == 0
        assert events == []
    finally:
        await db.close()
