"""EVOL-008/009 — состояние циклов памяти и админская диагностика.

TEST-LIFECYCLE: CONTRACT (plans/current_task.md EVOL-008, EVOL-009).
Фикстуры, без сети и Telegram. Прогоны не запускаются.
"""
import json

import pytest

from services.database import DatabaseService
from services.memory_diagnostics import (
    memory_cycle_status,
    memory_health_diagnostics,
    resolve_search,
)


def _flags(**overrides):
    base = {
        "graph_rag_enabled": True,
        "dream_enabled": True,
        "deep_sleep_enabled": True,
        "persona_enabled": True,
    }
    base.update(overrides)
    return {"global": base}


async def _db():
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _dream(db, chat_id, run_at, kind, status):
    await db.db.execute(
        "INSERT INTO memory_dream_log (chat_id, run_at, kind, tokens, status) "
        "VALUES (?, ?, ?, 0, ?)",
        (chat_id, run_at, kind, status))
    await db.db.commit()


async def _event(db, chat_id, ts, name, outcome, reason=None, error_class=None):
    error_json = json.dumps({"type": error_class}) if error_class else None
    await db.db.execute(
        "INSERT INTO mca_events (ts, level, event_name, outcome, chat_id, "
        "reason_code, error_json) VALUES (?, 'WARN', ?, ?, ?, ?, ?)",
        (ts, name, outcome, chat_id, reason, error_json))
    await db.db.commit()


@pytest.mark.asyncio
async def test_cycle_status_distinguishes_disabled_from_never_run():
    db = await _db()
    try:
        off = await memory_cycle_status(
            db, chat_id=-100,
            flags=_flags(dream_enabled=False, deep_sleep_enabled=False,
                         persona_enabled=False))
        assert off["stages"]["sleep"]["state"] == "disabled"
        assert off["stages"]["deep_sleep"]["state"] == "disabled"
        assert off["stages"]["personality"]["state"] == "disabled"
        assert off["stages"]["sleep"]["last_success_at"] is None
        assert off["scope_label"] == "chat:-100"

        idle = await memory_cycle_status(
            db, chat_id=-100,
            flags=_flags(dream_enabled=True, deep_sleep_enabled=True,
                         persona_enabled=True))
        assert idle["stages"]["sleep"]["state"] == "never_run"
        assert idle["stages"]["deep_sleep"]["state"] == "never_run"
        assert idle["stages"]["personality"]["state"] == "never_run"
        assert idle["stages"]["sleep"]["enabled"] is True
        assert "not_invoked_because" not in idle["stages"]["personality"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_personality_enabled_but_deep_sleep_off_is_never_run_not_disabled():
    db = await _db()
    try:
        body = await memory_cycle_status(
            db, chat_id=-100,
            flags=_flags(dream_enabled=False, deep_sleep_enabled=False,
                         persona_enabled=True))
        persona = body["stages"]["personality"]
        assert persona["state"] == "never_run"
        assert persona["enabled"] is True
        assert persona["not_invoked_because"] == "deep_sleep_disabled"
        assert body["stages"]["deep_sleep"]["state"] == "disabled"
        assert body["schedule"]["personality"]["job_id"] is None
        assert body["schedule"]["extract"]["summary_cron"] == "hour=0,6,12,18 minute=0"
        assert body["schedule"]["deep_sleep"]["default_enabled"] is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_cycle_status_reports_real_success_and_error_without_mixing_chats():
    db = await _db()
    try:
        await _dream(db, -100, 1000, "run", "ok")
        await _dream(db, -100, 1100, "deep_run", "ok")
        await _dream(db, -100, 1200, "deep_traits", "done")
        await _dream(db, -200, 2000, "error", "error")
        await _event(db, -200, 2100, "persona_traits", "failed",
                     reason="model_unavailable", error_class="LLMTimeoutError")
        body = await memory_cycle_status(
            db, chat_id=None, chat_ids=[-100, -200], flags=_flags())
        first = body["per_chat"]["-100"]["stages"]
        second = body["per_chat"]["-200"]["stages"]
        assert first["sleep"]["state"] == "ran"
        assert first["sleep"]["last_success_at"] == 1000
        assert first["deep_sleep"]["last_success_at"] == 1100
        assert first["personality"]["last_success_at"] == 1200
        assert first["sleep"]["last_error_at"] is None
        assert second["sleep"]["last_success_at"] is None
        assert second["sleep"]["last_error_at"] == 2000
        assert second["sleep"]["last_error_class"] is None
        assert second["sleep"]["last_error_reason"] == "dream_log_error"
        assert second["personality"]["last_error_at"] == 2100
        assert second["personality"]["last_error_class"] == "LLMTimeoutError"
        assert second["personality"]["last_error_reason"] == "model_unavailable"
        assert second["personality"]["last_success_at"] is None
        assert body["scope_label"] == "global"
    finally:
        await db.close()


def test_fts_only_is_never_reported_as_embeddings_working():
    fts_only = resolve_search(fts_table=True, vec_table=False, vector_runtime=True)
    assert fts_only["fts_available"] is True
    assert fts_only["vector_available"] is False
    assert fts_only["embeddings_working"] is False
    assert fts_only["search_mode"] == "fts_only"
    unknown = resolve_search(fts_table=True, vec_table=True, vector_runtime=None)
    assert unknown["embeddings_working"] is False
    assert unknown["search_mode"] == "fts_only"
    down = resolve_search(fts_table=True, vec_table=True, vector_runtime=False)
    assert down["embeddings_working"] is False
    assert down["search_mode"] == "fts_only"


@pytest.mark.asyncio
async def test_diagnostics_reads_real_fields_and_does_not_fake_vector():
    db = await _db()
    try:
        await db.insert_graph_fact(
            -100, "факт", "chat_history", None, target_user="Аня")
        await db.db.execute(
            "UPDATE graph_facts SET created_at = 77 WHERE chat_id = -100")
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
            "target_user, status) VALUES (-100, 'черновик', 'chat_history', "
            "80, 'Аня', 'unconfirmed')")
        await db.db.execute(
            "INSERT INTO mca_events (ts, level, event_name, outcome, chat_id, "
            "reason_code) VALUES (90, 'INFO', 'FACTS_EXTRACT', 'skipped', "
            "-100, 'no_new_contribution')")
        await db.db.execute(
            "INSERT INTO mca_events (ts, level, event_name, outcome, chat_id, "
            "reason_code, error_json) VALUES (95, 'ERROR', 'EMBED_API_FAILED', "
            "'failed', -100, 'code_defect', ?)",
            (json.dumps({"type": "NameError"}),))
        await db.db.commit()
        body = await memory_health_diagnostics(
            db, chat_id=-100, now_ts=1000, flags=_flags(),
            vector_runtime=True)
        assert body["scope_label"] == "chat:-100"
        assert body["last_successful_extract_at"] == 90
        assert body["last_new_fact_at"] == 77
        assert body["counts"]["unconfirmed_facts"] == 1
        assert body["counts"]["extract_skipped_by_reason"]["no_new_contribution"] == 1
        assert body["search"]["fts_available"] is True
        assert body["search"]["embeddings_working"] is False
        assert body["search"]["search_mode"] == "fts_only"
        assert body["search"]["vector_available"] is False
        assert body["indexing_backlog"] is None
        assert body["indexing_backlog_reason"] == "vec_table_absent"
        assert body["recent_error"]["error_class"] == "NameError"
        assert body["recent_error"]["reason_code"] == "code_defect"
        assert body["recent_error"]["event_name"] == "EMBED_API_FAILED"
        other = await memory_health_diagnostics(
            db, chat_id=-200, now_ts=1000, flags=_flags(),
            vector_runtime=False)
        assert other["last_new_fact_at"] is None
        assert other["recent_error"] is None
        assert other["counts"]["unconfirmed_facts"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_backlog_is_a_real_count_only_when_vec_table_exists():
    db = await _db()
    try:
        await db.db.execute(
            "CREATE TABLE graph_facts_vec (fact_id INTEGER)")
        await db.insert_graph_fact(
            -100, "без вектора", "chat_history", None, target_user="Аня")
        await db.insert_graph_fact(
            -100, "с вектором", "chat_history", None, target_user="Боря")
        cursor = await db.db.execute(
            "SELECT id FROM graph_facts WHERE fact = 'с вектором'")
        row = await cursor.fetchone()
        await db.db.execute(
            "INSERT INTO graph_facts_vec (fact_id) VALUES (?)", (row["id"],))
        await db.db.commit()
        body = await memory_health_diagnostics(
            db, chat_id=-100, now_ts=10**10, flags=_flags(),
            vector_runtime=True)
        assert body["search"]["embeddings_working"] is True
        assert body["search"]["search_mode"] == "vector"
        assert body["indexing_backlog"] == 1
        fts_fallback = await memory_health_diagnostics(
            db, chat_id=-100, now_ts=10**10, flags=_flags(),
            vector_runtime=False)
        assert fts_fallback["search"]["embeddings_working"] is False
        assert fts_fallback["search"]["search_mode"] == "fts_only"
        assert fts_fallback["indexing_backlog"] == 1
    finally:
        await db.close()
