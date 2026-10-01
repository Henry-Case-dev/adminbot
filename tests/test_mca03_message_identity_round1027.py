"""MCA Wave 1 (`mca-03-message-identity`, round 10.27) — контракт логической
идентичности/времени/ролей/версий (ADR-1027-4 D1–D12).

Покрытие:
  * v16: 18 nullable-колонок `smart_messages` + 3 таблицы + индексы; аддитивно/
    идемпотентно (повтор — no-op); duplicate pre-check → WARN
    `duplicate_identity_rows` без partial UNIQUE; bounded/resumable backfill;
    старые `id`/`timestamp`/FTS сохраняются;
  * канонический ключ `(chat_id, tg_message_id)`; namespace/source record;
    edit→версия; `unavailable/deleted` только по свидетельству; chat_id mapping;
  * kill-switch OFF = паритет baseline (`MCA_MESSAGE_IDENTITY_ENABLED`,
    `MCA_MESSAGE_REVISION_TRACKING_ENABLED`);
  * приёмки A07/A08/A11/A88 на обновлённых путях с ON.
"""
import asyncio
import datetime
import sqlite3

import pytest
from aiogram.types import Chat, Message, User

from services import mca_events, message_identity as mi
from services.database import (
    DatabaseService,
    _MESSAGE_IDENTITY_COLUMNS,
    _SCHEMA_VERSION_MESSAGE_IDENTITY,
)

CHAT_A = -1003000000001
CHAT_B = -1003000000002


def _target_version() -> int:
    return max(s.version for s in DatabaseService.migration_steps())


async def _fresh(tmp_path, name="mca03.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _insert_legacy(d, *, chat_id, text, ts, import_key=None, tg=None):
    """Прямая legacy-строка (новые v16-колонки остаются NULL = pre-backfill)."""
    cur = await d.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, import_key, tg_message_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (1, chat_id, text, ts, "text", "u", import_key, tg))
    row_id = cur.lastrowid
    if text:
        await d.db.execute(
            "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
            (row_id, text))
    await d.db.commit()
    return row_id


async def _downgrade_to_v15(d):
    """Смоделировать pre-v16: снять бронь версии/индексы/таблицы шага v16."""
    await d.db.execute("PRAGMA user_version = 15")
    await d.db.execute("DELETE FROM schema_migrations WHERE version = 16")
    await d.db.execute("DROP INDEX IF EXISTS idx_smart_messages_chat_tg_live_unique")
    await d.db.commit()


# ── T-3782: миграция v16 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v16_registered_fresh_target(tmp_path):
    d = await _fresh(tmp_path)
    try:
        assert _SCHEMA_VERSION_MESSAGE_IDENTITY == 16
        # MCA-17a (v19) — текущий head; v16-объекты сохранены.
        assert _target_version() >= 19  # реестр продолжает v20 (mca-04b)
        assert any(s.version == 16 and s.name == "message_identity"
                   for s in DatabaseService.migration_steps())
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 19
        cur = await d.db.execute(
            "SELECT name FROM schema_migrations WHERE version = 16")
        assert (await cur.fetchone())["name"] == "message_identity"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v16_columns_tables_indices(tmp_path):
    d = await _fresh(tmp_path, name="shape.db")
    try:
        cur = await d.db.execute("PRAGMA table_info(smart_messages)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert {name for name, _ in _MESSAGE_IDENTITY_COLUMNS} <= cols
        assert len(_MESSAGE_IDENTITY_COLUMNS) == 18
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] for r in await cur.fetchall()}
        assert {"message_source_records", "message_revisions",
                "chat_id_migrations"} <= tables
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")
        idx = {r["name"] for r in await cur.fetchall()}
        assert {"idx_smart_messages_chat_tg", "idx_smart_messages_chat_sent",
                "idx_smart_messages_chat_tg_live_unique",
                "idx_message_source_records_message",
                "idx_message_source_records_chat_tg",
                "idx_message_revisions_message"} <= idx
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v16_idempotent_reinitialize(tmp_path):
    d = await _fresh(tmp_path, name="idem.db")
    path = str(d.db_path)
    await d.close()
    d2 = DatabaseService(path)
    await d2.initialize()
    try:
        cur = await d2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version = 16")
        assert (await cur.fetchone())["c"] == 1
        cur = await d2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 19   # реестр >= v19 (v20 — mca-04b)
    finally:
        await d2.close()


@pytest.mark.asyncio
async def test_legacy_backfill_import_and_live(tmp_path):
    """SC-12/A11: backfill импорта (sent_at=timestamp) и live-legacy
    (sent_at=NULL, legacy_unverified); id/timestamp/FTS сохранены; повтор no-op."""
    d = await _fresh(tmp_path, name="backfill.db")
    path = str(d.db_path)
    imp_id = await _insert_legacy(d, chat_id=CHAT_A, text="история 2022",
                                  ts=1640000000, import_key="abc123")
    live_id = await _insert_legacy(d, chat_id=CHAT_A, text="живое",
                                   ts=1700000000, tg=None)
    await _downgrade_to_v15(d)
    await d.close()

    d2 = DatabaseService(path)
    await d2.initialize()
    try:
        cur = await d2.db.execute(
            "SELECT id, timestamp, sent_at, sent_at_source, source_kind, "
            "namespace, source_record_id, reply_to_kind, ingested_at "
            "FROM smart_messages WHERE id = ?", (imp_id,))
        imp = await cur.fetchone()
        assert imp["id"] == imp_id
        assert imp["timestamp"] == 1640000000          # legacy не тронут
        assert imp["sent_at"] == 1640000000
        assert imp["sent_at_source"] == "import_date"
        assert imp["source_kind"] == "import"
        assert imp["namespace"] == "legacy_import_v1"
        assert imp["source_record_id"] == "k:abc123"
        assert imp["ingested_at"] is None
        cur = await d2.db.execute(
            "SELECT id, timestamp, sent_at, sent_at_source, source_kind "
            "FROM smart_messages WHERE id = ?", (live_id,))
        live = await cur.fetchone()
        assert live["id"] == live_id
        assert live["timestamp"] == 1700000000
        assert live["sent_at"] is None
        assert live["sent_at_source"] == "legacy_unverified"
        assert live["source_kind"] == "live"
        cur = await d2.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages_fts "
            "WHERE smart_messages_fts MATCH 'история*'")
        assert (await cur.fetchone())["c"] == 1         # FTS сохранён
    finally:
        await d2.close()

    d3 = DatabaseService(path)
    await d3.initialize()
    try:
        cur = await d3.db.execute(
            "SELECT sent_at, sent_at_source FROM smart_messages WHERE id = ?",
            (imp_id,))
        again = await cur.fetchone()
        assert again["sent_at"] == 1640000000
        assert again["sent_at_source"] == "import_date"
    finally:
        await d3.close()


@pytest.mark.asyncio
async def test_duplicate_precheck_warns_no_unique(tmp_path, caplog):
    """SC-12: legacy-дубли live → partial UNIQUE НЕ создаётся, WARN
    `duplicate_identity_rows`, старые id сохранены."""
    d = await _fresh(tmp_path, name="dup.db")
    path = str(d.db_path)
    await d.db.execute("DROP INDEX IF EXISTS idx_smart_messages_chat_tg_live_unique")
    id1 = await _insert_legacy(d, chat_id=CHAT_A, text="д1", ts=1, tg=777)
    id2 = await _insert_legacy(d, chat_id=CHAT_A, text="д2", ts=2, tg=777)
    assert await d.count_duplicate_identity_rows() == 1
    await _downgrade_to_v15(d)
    await d.close()

    d2 = DatabaseService(path)
    await d2.initialize()
    try:
        cur = await d2.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_smart_messages_chat_tg_live_unique'")
        assert (await cur.fetchone()) is None       # UNIQUE не создан
        cur = await d2.db.execute(
            "SELECT id FROM smart_messages WHERE chat_id = ? AND "
            "tg_message_id = 777 ORDER BY id", (CHAT_A,))
        assert [r["id"] for r in await cur.fetchall()] == [id1, id2]
    finally:
        await d2.close()


@pytest.mark.asyncio
async def test_duplicate_warning_reason_registered():
    assert "duplicate_identity_rows" in mca_events.REASON_CODES
    ev = mca_events.build_event(
        "message_identity_migration", outcome="silent",
        reason_code="duplicate_identity_rows", stage="migrate_v16")
    assert ev is not None and ev["reason_code"] == "duplicate_identity_rows"


# ── T-3783/T-3784: каноническая идентичность, поля, время ──────────────────

@pytest.mark.asyncio
async def test_a07_two_chats_same_message_id_no_conflict(tmp_path):
    d = await _fresh(tmp_path, name="a07.db")
    try:
        id_a = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=1, text="первый", sent_at=100,
            tg_message_id=500)
        id_b = await mi.save_live_message(
            d, chat_id=CHAT_B, user_id=2, text="второй", sent_at=101,
            tg_message_id=500)
        assert id_a != id_b
        row_a = await d.get_smart_message_by_tg_id(CHAT_A, 500)
        row_b = await d.get_smart_message_by_tg_id(CHAT_B, 500)
        assert row_a["text"] == "первый" and row_b["text"] == "второй"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_live_identity_fields_and_roles(tmp_path):
    d = await _fresh(tmp_path, name="fields.db")
    try:
        mid = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=10, text="мнение", caption="подпись",
            sent_at=1700000000, ingested_at=1700000005, tg_message_id=42,
            reply_to_id=41, reply_to_author_id=20, quote_text="цитата",
            quote_author_id=30, forward_author_id=40, media_ref="photo:abc")
        row = await d.get_smart_message_by_tg_id(CHAT_A, 42)
        assert row["caption"] == "подпись"
        assert row["sent_at"] == 1700000000
        assert row["ingested_at"] == 1700000005
        assert row["sent_at_source"] == "telegram_date"
        assert row["source_kind"] == "live"
        assert row["reply_to_kind"] == "tg"
        assert row["current_revision"] == 1
        assert row["message_state"] == "active"
        roles = mi.roles({
            "user_id": row["user_id"],
            "reply_to_author_id": row["reply_to_author_id"],
            "quote_author_id": row["quote_author_id"],
            "forward_author_id": row["forward_author_id"]})
        assert roles[mi.ROLE_AUTHOR] == 10
        assert roles[mi.ROLE_REPLY_ADDRESSEE] == 20
        assert roles[mi.ROLE_QUOTED_AUTHOR] == 30
        assert roles[mi.ROLE_FORWARD_AUTHOR] == 40
        assert len({roles[k] for k in roles}) == 4      # роли не схлопнуты
        revs = await d.get_message_revisions(mid)
        assert [(r["revision_no"], r["revision_kind"]) for r in revs] == \
            [(1, "initial")]
        srcs = await d.get_message_source_records(mid)
        assert len(srcs) == 1
        assert srcs[0]["namespace"] == mi.LIVE_NAMESPACE
        assert srcs[0]["source_kind"] == "live"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_a88_two_same_name_users_not_merged_by_name(tmp_path):
    d = await _fresh(tmp_path, name="a88.db")
    try:
        id1 = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=111, text="я Макс", sent_at=1,
            author_name="Макс", tg_message_id=1)
        id2 = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=222, text="и я Макс", sent_at=2,
            author_name="Макс", tg_message_id=2)
        assert id1 != id2
        r1 = await d.get_smart_message_by_tg_id(CHAT_A, 1)
        r2 = await d.get_smart_message_by_tg_id(CHAT_A, 2)
        assert r1["user_id"] == 111 and r2["user_id"] == 222
        assert r1["author_name"] == r2["author_name"] == "Макс"
        assert mi.canonical_key(CHAT_A, 1) == (CHAT_A, 1)
        assert mi.canonical_key(CHAT_A, None) is None   # локальный ≠ TG
    finally:
        await d.close()


# ── T-3786: версии / свидетельства (A08) ───────────────────────────────────

@pytest.mark.asyncio
async def test_a08_edit_creates_revision_updates_fts(tmp_path):
    d = await _fresh(tmp_path, name="edit.db")
    try:
        mca_events.reset_pending()
        mid = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=1, text="старый текст", sent_at=10,
            tg_message_id=99)
        assert await mi.record_edit(d, chat_id=CHAT_A, tg_message_id=99,
                                    text="новый текст", edited_at=20) == mid
        row = await d.get_smart_message_by_tg_id(CHAT_A, 99)
        assert row["text"] == "новый текст"
        assert row["current_revision"] == 2
        assert row["edited_at"] == 20
        revs = await d.get_message_revisions(mid)
        assert [(r["revision_no"], r["revision_kind"], r["text"])
                for r in revs] == [(1, "initial", "старый текст"),
                                   (2, "edit", "новый текст")]
        cur = await d.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages_fts "
            "WHERE smart_messages_fts MATCH 'новый*'")
        assert (await cur.fetchone())["c"] == 1
        cur = await d.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages_fts "
            "WHERE smart_messages_fts MATCH 'старый*'")
        assert (await cur.fetchone())["c"] == 0          # устаревшая не найдена
        # идемпотентность: тот же текст версию не плодит
        await mi.record_edit(d, chat_id=CHAT_A, tg_message_id=99,
                             text="новый текст")
        assert len(await d.get_message_revisions(mid)) == 2
        assert any(ev.get("reason_code") == "source_revision_changed"
                   for ev in mca_events._pending)
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_a08_unavailable_only_by_evidence(tmp_path):
    d = await _fresh(tmp_path, name="state.db")
    try:
        mid = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=1, text="t", sent_at=1,
            tg_message_id=7)
        assert await mi.set_message_state(
            d, message_id=mid, state="deleted", evidence=None) is False
        row = await d.get_smart_message_by_tg_id(CHAT_A, 7)
        assert row["message_state"] == "active"           # не изменено
        assert await mi.set_message_state(
            d, message_id=mid, state="deleted",
            evidence="service:delete_message") is True
        row = await d.get_smart_message_by_tg_id(CHAT_A, 7)
        assert row["message_state"] == "deleted"
        assert row["state_evidence"] == "service:delete_message"
        revs = await d.get_message_revisions(mid)
        assert revs[-1]["revision_kind"] == "deleted"
        assert revs[-1]["evidence_kind"] == "service:delete_message"
        # отсутствие события статус не меняет (только по свидетельству)
        assert await mi.set_message_state(
            d, message_id=mid, state="active", evidence="x") is False
    finally:
        await d.close()


# ── T-3787: mapping chat_id (D6) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_id_migration_explicit_only(tmp_path):
    d = await _fresh(tmp_path, name="chatid.db")
    try:
        assert await mi.register_chat_id_migration(
            d, old_chat_id=-100, new_chat_id=-200,
            evidence="migrate_to_chat_id") is True
        assert await mi.resolve_chat_id(d, -100) == -200
        assert await mi.resolve_chat_id(d, -200) == -200   # нет «по имени»
        # без свидетельства — отказ
        assert await mi.register_chat_id_migration(
            d, old_chat_id=-300, new_chat_id=-400, evidence="") is False
        # цикл не зацикливает резолвер
        await mi.register_chat_id_migration(
            d, old_chat_id=-200, new_chat_id=-100, evidence="loop")
        assert await mi.resolve_chat_id(d, -100) in (-100, -200)
    finally:
        await d.close()


# ── T-3794: kill-switch OFF = паритет baseline ─────────────────────────────

@pytest.mark.asyncio
async def test_identity_off_legacy_parity(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "identity_enabled", lambda: False)
    d = await _fresh(tmp_path, name="off.db")
    try:
        mid = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=1, text="legacy", sent_at=100,
            ingested_at=200, tg_message_id=55)
        row = await d.get_smart_message_by_tg_id(CHAT_A, 55)
        assert row["id"] == mid
        assert row["source_kind"] is None          # новых полей нет
        assert row["sent_at"] is None
        assert row["current_revision"] is None
        assert await d.get_message_source_records(mid) == []
        assert await d.get_message_revisions(mid) == []
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_revision_tracking_off_parity(tmp_path, monkeypatch):
    d = await _fresh(tmp_path, name="revoff.db")
    try:
        mid = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=1, text="v1", sent_at=1,
            tg_message_id=8)
        monkeypatch.setattr(mi, "revision_tracking_enabled", lambda: False)
        assert await mi.record_edit(d, chat_id=CHAT_A, tg_message_id=8,
                                    text="v2") == 0
        row = await d.get_smart_message_by_tg_id(CHAT_A, 8)
        assert row["text"] == "v1"                 # правка не применена
        assert len(await d.get_message_revisions(mid)) == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_loader_identity_off_parity(tmp_path, monkeypatch):
    """T-3794: `identity` OFF → импорт legacy-INSERT (новые поля NULL,
    source records не пишутся)."""
    import json

    from services import mca_gates
    from tools.history_import.loader import import_history_fts

    export = tmp_path / "off.json"
    export.write_text(json.dumps({
        "id": -1007, "type": "private_group",
        "messages": [{"id": 1, "type": "message",
                      "date_unixtime": "1640995200", "from": "A",
                      "from_id": "user1", "text": "legacy import"}]},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mca_gates, "message_identity_enabled", lambda: False)
    db_path = str(tmp_path / "imp_off.db")
    d = DatabaseService(db_path)
    await d.initialize()
    await d.close()
    summary = await import_history_fts(db_path, [str(export)], CHAT_A,
                                       batch_size=100)
    assert summary["inserted"] == 1
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT source_kind, sent_at, namespace, current_revision "
            "FROM smart_messages").fetchone()
        assert row["source_kind"] is None
        assert row["sent_at"] is None
        assert row["namespace"] is None
        assert row["current_revision"] is None
        assert conn.execute(
            "SELECT COUNT(*) FROM message_source_records").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_observer_identity_off_parity(tmp_path, monkeypatch):
    """T-3794: observer OFF → legacy `save_smart_message`, без новых полей."""
    from handlers import summary as summary_mod
    from services.summary_aliases import AliasResolver

    monkeypatch.setattr(mi, "identity_enabled", lambda: False)
    d = await _fresh(tmp_path, name="obs_off.db")
    try:
        summary_mod.setup_summary(None, d, AliasResolver(""), bot_id=None)
        await summary_mod.summary_observer(
            _real_message(1, "legacy live", CHAT_A, message_id=321))
        row = await d.get_smart_message_by_tg_id(CHAT_A, 321)
        assert row["text"] == "legacy live"
        assert row["source_kind"] is None
        assert row["sent_at"] is None
        assert row["current_revision"] is None
    finally:
        summary_mod.setup_summary(None, None, None, bot_id=None)
        await d.close()


# ── R17 / контракт событий ─────────────────────────────────────────────────

def test_r17_event_drops_raw_context():
    mca_events.reset_pending()
    ev = mca_events.build_event(
        "message_revision", outcome="success",
        reason_code="source_revision_changed", text="секретный текст",
        password="hunter2", component="identity")
    assert ev is not None
    assert "text" not in ev and "password" not in ev
    assert ev["component"] == "identity"
    assert ev["reason_code"] == "source_revision_changed"


# ── Producers на обновлённых путях (observer / edited handler) ─────────────

def _real_message(user_id, text, chat_id, *, message_id=12345, caption=None,
                  date=None):
    return Message(
        message_id=message_id,
        date=date or datetime.datetime(2024, 5, 1, 12, 0, 0),
        chat=Chat(id=chat_id, type="group"),
        from_user=User(id=user_id, is_bot=False, first_name="Тест"),
        text=text,
        caption=caption,
    )


@pytest.mark.asyncio
async def test_observer_live_writes_identity(tmp_path):
    from handlers import summary as summary_mod
    from services.summary_aliases import AliasResolver

    d = await _fresh(tmp_path, name="obs.db")
    try:
        summary_mod.setup_summary(None, d, AliasResolver(""), bot_id=None)
        msg = _real_message(321, "привет из чата", CHAT_A, message_id=777)
        await summary_mod.summary_observer(msg)
        row = await d.get_smart_message_by_tg_id(CHAT_A, 777)
        assert row["text"] == "привет из чата"
        assert row["source_kind"] == "live"
        assert row["sent_at"] == int(msg.date.timestamp())   # дата события
        assert row["ingested_at"] is not None                # время записи
        assert row["sent_at_source"] == "telegram_date"
        assert row["timestamp"] == row["ingested_at"]        # legacy = запись
        assert row["sent_at"] < row["ingested_at"]           # две даты отличны
    finally:
        summary_mod.setup_summary(None, None, None, bot_id=None)
        await d.close()


@pytest.mark.asyncio
async def test_observer_sent_at_is_telegram_date_not_ingest_time(tmp_path):
    """B-MCA03-2/SC-06/A11: позднее доставленное live-сообщение имеет две
    разные даты: `sent_at` = message.date, `ingested_at` = момент записи."""
    import time as _time
    from handlers import summary as summary_mod
    from services.summary_aliases import AliasResolver

    d = await _fresh(tmp_path, name="obs_time.db")
    try:
        summary_mod.setup_summary(None, d, AliasResolver(""), bot_id=None)
        event_date = datetime.datetime(2022, 1, 1, 3, 0, 0)
        before = int(_time.time())
        msg = _real_message(321, "найдено сегодня", CHAT_A, message_id=901,
                            date=event_date)
        await summary_mod.summary_observer(msg)
        after = int(_time.time())
        row = await d.get_smart_message_by_tg_id(CHAT_A, 901)
        assert row["sent_at"] == int(event_date.timestamp())   # 2022 (Telegram)
        assert row["sent_at_source"] == "telegram_date"
        assert before <= row["ingested_at"] <= after           # время записи
        assert row["sent_at"] < row["ingested_at"]             # две даты
        assert row["timestamp"] == row["ingested_at"]          # legacy = запись
        assert row["timestamp"] != row["sent_at"]
    finally:
        summary_mod.setup_summary(None, None, None, bot_id=None)
        await d.close()


@pytest.mark.asyncio
async def test_observer_edited_handler_creates_revision(tmp_path):
    from handlers import summary as summary_mod
    from services.summary_aliases import AliasResolver

    d = await _fresh(tmp_path, name="obsedit.db")
    try:
        summary_mod.setup_summary(None, d, AliasResolver(""), bot_id=None)
        await summary_mod.summary_observer(
            _real_message(321, "версия 1", CHAT_A, message_id=888))
        await summary_mod.summary_observer_edited(
            _real_message(321, "версия 2", CHAT_A, message_id=888))
        row = await d.get_smart_message_by_tg_id(CHAT_A, 888)
        assert row["text"] == "версия 2"
        assert row["current_revision"] == 2
        revs = await d.get_message_revisions(row["id"])
        assert [r["revision_kind"] for r in revs] == ["initial", "edit"]
    finally:
        summary_mod.setup_summary(None, None, None, bot_id=None)
        await d.close()


# ── T-3790/3791: импорт (A11) через loader ────────────────────────────────

@pytest.mark.asyncio
async def test_a11_import_via_loader_two_dates(tmp_path):
    import json

    from tools.history_import.loader import import_history_fts

    export = tmp_path / "chat_2022.json"
    export.write_text(json.dumps({
        "id": -1005001, "name": "oldchat", "type": "private_group",
        "messages": [
            {"id": 11, "type": "message", "date_unixtime": "1640995200",
             "from": "Макс", "from_id": "user1", "text": "сообщение 2022"},
            {"id": 12, "type": "message", "date_unixtime": "1640995300",
             "from": "Макс", "from_id": "user1",
             "reply_to_message_id": 11, "text": "ответ 2022"},
        ]}, ensure_ascii=False), encoding="utf-8")

    db_path = str(tmp_path / "imp.db")
    d = DatabaseService(db_path)
    await d.initialize()
    await d.close()
    summary = await import_history_fts(db_path, [str(export)], CHAT_A,
                                       batch_size=100)
    assert summary["inserted"] == 2
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT timestamp, sent_at, ingested_at, sent_at_source, "
            "source_kind, namespace, source_record_id, reply_to_kind "
            "FROM smart_messages WHERE source_record_id = '12'").fetchone()
        assert row["sent_at"] == 1640995300            # дата события 2022
        assert row["timestamp"] == 1640995300
        assert row["sent_at_source"] == "import_date"
        assert row["source_kind"] == "import"
        assert row["namespace"].startswith("import:-1005001:")  # per-dataset
        assert row["namespace"] != "legacy_import_v1"
        assert row["reply_to_kind"] == "export"
        assert row["ingested_at"] is not None
        assert row["ingested_at"] != row["sent_at"]    # две даты различимы
        cnt = conn.execute(
            "SELECT COUNT(*) FROM message_source_records").fetchone()[0]
        assert cnt == 2
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_import_two_exports_same_record_ids_keep_provenance(tmp_path):
    """B-MCA03-1: два экспорта с пересекающимися record-id → все вхождения
    сохранены (namespace per-dataset), provenance не теряется."""
    import json

    from tools.history_import.loader import import_history_fts

    def _write(name, text1, text2, header_id):
        p = tmp_path / name
        p.write_text(json.dumps({
            "id": header_id, "name": name, "type": "private_group",
            "messages": [
                {"id": 1, "type": "message", "date_unixtime": "1640995200",
                 "from": "A", "from_id": "user1", "text": text1},
                {"id": 2, "type": "message", "date_unixtime": "1640995300",
                 "from": "B", "from_id": "user2", "text": text2},
            ]}, ensure_ascii=False), encoding="utf-8")
        return str(p)

    # Одинаковая шапка (export-id) и одинаковые record-id, но разное содержимое.
    e1 = _write("exp_a.json", "экспорт A id1", "экспорт A id2", -1005001)
    e2 = _write("exp_b.json", "экспорт B id1", "экспорт B id2", -1005001)

    db_path = str(tmp_path / "imp2.db")
    d = DatabaseService(db_path)
    await d.initialize()
    await d.close()
    summary = await import_history_fts(db_path, [e1, e2], CHAT_A,
                                       batch_size=100)
    assert summary["inserted"] == 4
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM smart_messages").fetchone()[0] == 4
        rows = conn.execute(
            "SELECT namespace, local_record_id FROM message_source_records "
            "ORDER BY namespace, local_record_id").fetchall()
        assert len(rows) == 4                       # не потеряны
        namespaces = {r["namespace"] for r in rows}
        assert len(namespaces) == 2                 # различны per-dataset
        assert all(ns.startswith("import:") for ns in namespaces)
        assert sorted({r["local_record_id"] for r in rows}) == ["1", "2"]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_import_and_live_share_one_canonical_source(tmp_path):
    """M-MCA03-4/SC-03: импортная и live-копии с общим `(chat_id, tg)` связаны
    с одним canonical source; обе копии различимы по `source_kind`."""
    d = await _fresh(tmp_path, name="link.db")
    try:
        imp_id = await _insert_legacy(d, chat_id=CHAT_A, text="импорт",
                                      ts=100, tg=555)
        await d.insert_message_source_record(
            message_id=imp_id, namespace="import:x", local_record_id="1",
            tg_message_id=555, chat_id=CHAT_A, source_kind="import")
        live_id = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=1, text="импорт", sent_at=50,
            tg_message_id=555)
        assert live_id == imp_id                    # один canonical source
        cur = await d.db.execute(
            "SELECT COUNT(*) AS c FROM smart_messages "
            "WHERE chat_id = ? AND tg_message_id = ?", (CHAT_A, 555))
        assert (await cur.fetchone())["c"] == 1
        srcs = await d.get_message_source_records(imp_id)
        assert {s["source_kind"] for s in srcs} == {"import", "live"}
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_existing_row_backfills_sent_at_on_changed_update(tmp_path):
    """M-MCA03-5: changed-ветка update тоже заполняет `sent_at`/`ingested_at`
    (pre-v16 NULL → честно заполнено), legacy `timestamp` не тронут."""
    d = await _fresh(tmp_path, name="bf_changed.db")
    try:
        await _insert_legacy(d, chat_id=CHAT_A, text="старое", ts=1700000000,
                             tg=556)
        mid = await mi.save_live_message(
            d, chat_id=CHAT_A, user_id=1, text="новое", sent_at=1600000000,
            ingested_at=1700000123, tg_message_id=556)
        row = await d.get_smart_message_by_tg_id(CHAT_A, 556)
        assert row["id"] == mid
        assert row["text"] == "новое"
        assert row["sent_at"] == 1600000000         # заполнено в changed-ветке
        assert row["ingested_at"] == 1700000123
        assert row["sent_at_source"] == "telegram_date"
        assert row["timestamp"] == 1700000000       # legacy не переименован
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_chat_migrated_wiring_records_chat_id_mapping(tmp_path):
    """M-MCA03-3/REQ-MCA03-06: `on_chat_migrated` пишет `chat_id_migrations`
    по подтверждённому Telegram-метаданному."""
    from handlers import chat_lifecycle as cl

    d = await _fresh(tmp_path, name="lc.db")

    class _FakeStore:
        def __init__(self):
            self.link = None

        async def add_link(self, old, new):
            self.link = (old, new)

        async def migrate_profile(self, **kwargs):
            return {"ok": True}

    store = _FakeStore()
    cl.setup_chat_lifecycle(store, bot_id=1, db=d)
    old_id, new_id = -100400, -100500
    msg = Message(
        message_id=1,
        date=datetime.datetime(2024, 5, 1, 12, 0, 0),
        chat=Chat(id=old_id, type="group"),
        from_user=User(id=99, is_bot=False, first_name="X"),
        migrate_to_chat_id=new_id,
    )
    try:
        await cl.on_chat_migrated(msg)
        assert store.link == (old_id, new_id)
        assert await mi.resolve_chat_id(d, old_id) == new_id
    finally:
        cl.setup_chat_lifecycle(None, bot_id=None, db=None)
        await d.close()
