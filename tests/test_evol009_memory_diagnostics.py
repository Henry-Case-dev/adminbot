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
    new_facts_widget,
    resolve_search,
    schedule_view,
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


async def _extract_pass(db, chat_id, ts, outcome, *, reason=None, usage=None,
                        stage="extract"):
    """Строка терминала FACTS_EXTRACT ровно в том виде, как её пишет
    `services/summary_memory.py` (usage_json = счётчики + исход прохода)."""
    usage_json = json.dumps(usage) if usage is not None else None
    await db.db.execute(
        "INSERT INTO mca_events (ts, level, event_name, outcome, chat_id, "
        "stage, reason_code, usage_json) VALUES (?, 'INFO', 'FACTS_EXTRACT', "
        "?, ?, ?, ?, ?)",
        (ts, outcome, chat_id, stage, reason, usage_json))
    await db.db.commit()


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


@pytest.mark.asyncio
async def test_extract_candidates_come_from_usage_json_not_unconfirmed_facts():
    db = await _db()
    try:
        # unconfirmed-факт — состояние фактов, а не число кандидатов прохода.
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
            "target_user, status) VALUES (-100, 'черновик', 'chat_history', "
            "80, 'Аня', 'unconfirmed')")
        await db.db.commit()
        await _extract_pass(db, -100, 100, "success", usage={
            "saved": 2, "skipped": 1, "deduped": 3, "superseded": 1,
            "text_only": 0, "outcome": "partial"})
        await _extract_pass(db, -100, 200, "success", usage={
            "saved": 1, "skipped": 0, "deduped": 0, "superseded": 0,
            "text_only": 1, "outcome": "text_only_vector_deferred"})
        body = await memory_health_diagnostics(
            db, chat_id=-100, now_ts=1000, flags=_flags())
        usage = body["extract_usage"]
        last = usage["last_terminal"]
        assert last["at"] == 200
        assert last["candidates"] == 1            # 1+0+0+0
        assert last["saved"] == 1
        assert last["deduped"] == 0
        assert last["text_only"] == 1
        assert last["pass_outcome"] == "text_only_vector_deferred"
        assert last["usage_present"] is True
        total = usage["total"]
        assert total["terminal_passes"] == 2
        assert total["candidates"] == 8           # 7 + 1
        assert total["saved"] == 3
        assert total["skipped"] == 1
        assert total["deduped"] == 3
        assert total["superseded"] == 1
        assert total["text_only"] == 1
        assert total["covers_all_passes"] is True
        assert body["counts"]["unconfirmed_facts"] == 1
        # Другой scope не получает чужих кандидатов.
        other = await memory_health_diagnostics(
            db, chat_id=-200, now_ts=1000, flags=_flags())
        assert other["extract_usage"]["last_terminal"] is None
        assert other["extract_usage"]["total"]["candidates"] is None
        assert other["extract_usage"]["total"]["terminal_passes"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_legacy_extract_row_without_usage_json_stays_unknown_not_zero():
    db = await _db()
    try:
        await _extract_pass(db, -100, 100, "success")   # старое событие
        body = await memory_health_diagnostics(
            db, chat_id=-100, now_ts=1000, flags=_flags())
        usage = body["extract_usage"]
        last = usage["last_terminal"]
        assert last["outcome"] == "success"
        assert last["usage_present"] is False
        assert last["candidates"] is None
        assert last["saved"] is None
        assert last["text_only"] is None
        assert last["pass_outcome"] is None
        total = usage["total"]
        assert total["terminal_passes"] == 1
        assert total["passes_with_usage"] == 0
        assert total["passes_without_usage"] == 1
        assert total["covers_all_passes"] is False
        assert total["candidates"] is None         # не 0
        assert total["saved"] is None
        # Смешанная история: сумма считается только по проходам с usage_json,
        # покрытие честно помечено.
        await _extract_pass(db, -100, 200, "success", usage={
            "saved": 2, "skipped": 0, "deduped": 1, "superseded": 0,
            "text_only": 0, "outcome": "success"})
        mixed = (await memory_health_diagnostics(
            db, chat_id=-100, now_ts=1000, flags=_flags()))["extract_usage"]
        assert mixed["last_terminal"]["usage_present"] is True
        assert mixed["last_terminal"]["candidates"] == 3
        assert mixed["total"]["candidates"] == 3
        assert mixed["total"]["passes_with_usage"] == 1
        assert mixed["total"]["passes_without_usage"] == 1
        assert mixed["total"]["covers_all_passes"] is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_failed_or_invalidated_pass_reports_candidates_with_zero_saved():
    db = await _db()
    try:
        await _extract_pass(db, -100, 100, "failed", reason="writer_failed",
                            usage={"saved": 0, "skipped": 3, "deduped": 0,
                                   "superseded": 0, "text_only": 0,
                                   "outcome": "write_failed"})
        await _extract_pass(db, -100, 200, "skipped",
                            reason="validation_failed",
                            usage={"saved": 0, "skipped": 2, "deduped": 1,
                                   "superseded": 0, "text_only": 0,
                                   "outcome": "validation_failed"})
        body = await memory_health_diagnostics(
            db, chat_id=-100, now_ts=1000, flags=_flags())
        usage = body["extract_usage"]
        last = usage["last_terminal"]
        assert last["outcome"] == "skipped"
        assert last["reason_code"] == "validation_failed"
        assert last["candidates"] == 3             # 0+2+1+0
        assert last["candidates"] != 0
        assert last["saved"] == 0
        assert last["skipped"] == 2
        assert last["deduped"] == 1
        total = usage["total"]
        assert total["candidates"] == 6
        assert total["saved"] == 0
        assert total["passes_with_usage"] == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_empty_state_reason_and_freshness_follow_real_last_pass():
    db = await _db()
    try:
        widget_flags = {"global": {
            "graph_rag_enabled": True, "dream_enabled": False,
            "deep_sleep_enabled": False, "persona_enabled": True}}
        await _extract_pass(db, -100, 500, "skipped",
                            reason="validation_failed", stage="gate")
        bare = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=widget_flags)
        assert bare["items"] == []
        assert bare["empty_state"] == "empty"
        assert bare["empty_state_reason"] == "empty:skipped:validation_failed"
        assert bare["freshness"] is None

        await db.insert_graph_fact(
            -100, "живой факт", "chat_history", None, target_user="Аня")
        await db.db.commit()
        await _extract_pass(db, -100, 600, "failed", reason="writer_failed")
        failed = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=widget_flags)
        assert [item["fact"] for item in failed["items"]] == ["живой факт"]
        assert failed["empty_state"] is None
        assert failed["freshness"] == "extract_failed"
        assert failed["last_extract"]["candidates"] is None

        await _extract_pass(db, -100, 700, "success", usage={
            "saved": 1, "skipped": 0, "deduped": 0, "superseded": 0,
            "text_only": 0, "outcome": "partial"})
        ok = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=widget_flags)
        assert ok["freshness"] == "has_items"
        assert ok["last_extract"]["candidates"] == 1

        await _extract_pass(db, -100, 800, "skipped",
                            reason="no_new_contribution")
        no_new = await new_facts_widget(
            db, chat_id=-100, now_ts=1000, flags=widget_flags)
        assert no_new["freshness"] == "no_new_results"
        assert no_new["empty_state"] is None
        assert no_new["empty_state_reason"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_schedule_deep_sleep_timezone_matches_its_own_day_math(monkeypatch):
    from services import hot_config
    values = {
        "limits.summary_timezone": "Asia/Tokyo",
        "limits.worker_budget_tz": "Europe/Berlin",
        "memory.dream_tick_minutes": 30,
    }
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: values.get(key, default))
    schedule = schedule_view()
    # deep_sleep считает сутки/час в WORKER_BUDGET_TZ (dream_worker._deep_tz_name)
    assert schedule["deep_sleep"]["timezone"] == "Europe/Berlin"
    assert schedule["deep_sleep"]["timezone_key"] == "limits.worker_budget_tz"
    assert schedule["sleep"]["timezone"] == "Asia/Tokyo"
    assert schedule["sleep"]["timezone_key"] == "limits.summary_timezone"
    assert schedule["extract"]["timezone"] == "Asia/Tokyo"
    assert schedule["extract"]["timezone_key"] == "limits.summary_timezone"
    assert schedule["deep_sleep"]["tick_minutes"] == 30
