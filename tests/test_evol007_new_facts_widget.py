"""EVOL-007 — виджет «Новые факты»: даты, свежесть, изоляция чатов, честные пустые состояния.

TEST-LIFECYCLE: CONTRACT (plans/current_task.md EVOL-007).
Фикстуры, без сети и Telegram.
"""
import json

import pytest

from services.database import DatabaseService
from services.memory_diagnostics import new_facts_widget


def _flags(*, extract=True):
    return {"global": {
        "graph_rag_enabled": extract,
        "dream_enabled": False,
        "deep_sleep_enabled": False,
        "persona_enabled": True,
    }}


async def _db():
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _fact(db, chat_id, text, name, *, created_at, event_at=None,
                confirmed_at=None, status="confirmed", expires_at=None):
    fact_id = await db.insert_graph_fact(
        chat_id, text, "chat_history", expires_at, target_user=name,
        status=status, message_timestamp=event_at)
    await db.db.execute(
        "UPDATE graph_facts SET created_at = ?, last_confirmed_at = ? "
        "WHERE id = ?",
        (created_at, confirmed_at, fact_id))
    await db.db.commit()
    return fact_id


async def _extract(db, chat_id, ts, outcome, reason=None, error_class=None):
    error_json = None
    if error_class:
        error_json = json.dumps({"type": error_class})
    await db.db.execute(
        "INSERT INTO mca_events (ts, level, event_name, outcome, chat_id, "
        "reason_code, error_json) VALUES (?, 'INFO', 'FACTS_EXTRACT', ?, ?, ?, ?)",
        (ts, outcome, chat_id, reason, error_json))
    await db.db.commit()


@pytest.mark.asyncio
async def test_widget_returns_real_dates_newest_first_without_substitution():
    db = await _db()
    try:
        await _fact(db, -100, "старый", "Аня", created_at=100,
                    event_at=10, confirmed_at=110)
        await _fact(db, -100, "новый", "Боря", created_at=300,
                    event_at=None, confirmed_at=None)
        await _fact(db, -100, "средний", "Вера", created_at=200,
                    event_at=200, confirmed_at=250)
        body = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=_flags())
        assert [item["fact"] for item in body["items"]] == [
            "новый", "средний", "старый"]
        newest, mid, oldest = body["items"]
        assert newest["created_at"] == 300
        assert newest["extracted_at"] == 300
        assert newest["extracted_at_source"] == "graph_facts.created_at"
        assert newest["message_timestamp"] is None
        assert newest["last_confirmed_at"] is None
        assert oldest["message_timestamp"] == 10
        assert oldest["message_timestamp"] != oldest["created_at"]
        assert oldest["last_confirmed_at"] == 110
        assert mid["created_at"] == 200
        assert body["ordered_by"] == "created_at_desc"
        assert body["empty_state"] is None
        assert body["scope"] == "chat"
        assert body["scope_label"] == "chat:-100"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_two_chats_never_mix_and_global_is_labeled():
    db = await _db()
    try:
        await _fact(db, -100, "только первый", "Аня", created_at=50,
                    event_at=40, confirmed_at=50)
        await _fact(db, -200, "только второй", "Боря", created_at=80,
                    event_at=70, confirmed_at=80)
        first = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=_flags())
        second = await new_facts_widget(
            db, chat_id=-200, now_ts=1000, flags=_flags())
        assert {item["fact"] for item in first["items"]} == {"только первый"}
        assert {item["chat_id"] for item in first["items"]} == {-100}
        assert {item["fact"] for item in second["items"]} == {"только второй"}
        assert first["scope_label"] == "chat:-100"
        assert second["scope_label"] == "chat:-200"
        both = await new_facts_widget(db, chat_id=None, now_ts=1000, flags=_flags())
        assert both["scope"] == "global"
        assert both["scope_label"] == "global"
        assert both["chat_id"] is None
        assert {item["fact"] for item in both["items"]} == {
            "только первый", "только второй"}
        assert [item["fact"] for item in both["items"]] == [
            "только второй", "только первый"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_empty_states_are_derived_not_invented():
    db = await _db()
    try:
        never = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=_flags(extract=True))
        assert never["items"] == []
        assert never["empty_state"] == "not_yet_run"
        assert never["last_successful_extract_at"] is None

        disabled = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=_flags(extract=False))
        assert disabled["empty_state"] == "disabled"
        assert disabled["updates_disabled"] is True
        assert disabled["extraction_enabled"] is False

        await _extract(db, -100, 400, "skipped", "no_new_contribution")
        no_new = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=_flags(extract=True))
        assert no_new["empty_state"] == "no_new_results"
        assert no_new["last_successful_extract_at"] == 400
        assert no_new["items"] == []

        await _extract(db, -200, 500, "success")
        empty = await new_facts_widget(
            db, chat_id=-200, now_ts=1000, flags=_flags(extract=True))
        assert empty["empty_state"] == "empty"
        assert empty["last_successful_extract_at"] == 500
        assert empty["items"] == []
        still = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=_flags(extract=True))
        assert still["last_successful_extract_at"] == 400
        assert still["empty_state"] == "no_new_results"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_no_new_pass_keeps_older_facts_and_honest_timestamp():
    db = await _db()
    try:
        await _fact(db, -100, "давний факт", "Аня", created_at=100,
                    event_at=90, confirmed_at=100)
        await _extract(db, -100, 900, "skipped", "no_new_contribution")
        body = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=_flags())
        assert [item["fact"] for item in body["items"]] == ["давний факт"]
        assert body["empty_state"] is None
        assert body["freshness"] == "no_new_results"
        assert body["last_successful_extract_at"] == 900
        assert body["items"][0]["created_at"] == 100
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_disabled_does_not_hide_existing_facts():
    db = await _db()
    try:
        await _fact(db, -100, "был до выключения", "Аня", created_at=20,
                    event_at=15, confirmed_at=20)
        body = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=_flags(extract=False))
        assert body["empty_state"] is None
        assert body["updates_disabled"] is True
        assert body["items"][0]["fact"] == "был до выключения"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_load_failed_does_not_fabricate_facts():
    class Boom:
        async def dossier_feed(self, **kwargs):
            raise RuntimeError("db down")

    body = await new_facts_widget(Boom(), chat_id=-100, flags=_flags())
    assert body["empty_state"] == "load_failed"
    assert body["items"] == []
    assert body["last_successful_extract_at"] is None
    assert body["scope_label"] == "chat:-100"


@pytest.mark.asyncio
async def test_widget_skips_expired_unconfirmed_and_other_chat():
    db = await _db()
    try:
        await _fact(db, -100, "живой", "Аня", created_at=30,
                    event_at=30, confirmed_at=30)
        await _fact(db, -100, "просрочен", "Аня", created_at=40,
                    event_at=40, confirmed_at=40, expires_at=10)
        await _fact(db, -100, "черновик", "Аня", created_at=50,
                    event_at=50, confirmed_at=50, status="unconfirmed")
        await _fact(db, -200, "чужой", "Боря", created_at=60,
                    event_at=60, confirmed_at=60)
        rows = await db.dossier_feed(limit=10, chat_id=-100, now_ts=100)
        assert [row["fact"] for row in rows] == ["живой"]
        assert "created_at" in rows[0]
        assert rows[0]["created_at"] == 30
    finally:
        await db.close()
