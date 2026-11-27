"""SELF-DIAG-01 D6-19 (T7-T16): честная аналитика существующих источников."""

import json
import re
import time

import pytest

from handlers import checkup as checkup_handler
from services import mca_gates
from services import tool_router as tool_router_module
from services.database import DatabaseService
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from web.api import routes


async def _new_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _insert_incident(db, *, incident_id, subsystem, severity,
                           repeat=1, last_ts, acknowledged_at=None,
                           resolved_at=None):
    await db.db.execute(
        "INSERT INTO mca_incidents (incident_id, fingerprint, process_id, "
        "pipeline_type, severity, title, first_ts, last_ts, repeat_count, "
        "acknowledged_at, resolved_at, created_at, updated_at) "
        "VALUES (?, ?, 'watchdog.jobs', ?, ?, 't', ?, ?, ?, ?, ?, ?, ?)",
        (incident_id, incident_id, subsystem, severity, last_ts, last_ts,
         repeat, acknowledged_at, resolved_at, last_ts, last_ts))
    await db.db.commit()


async def _insert_event(db, *, ts, event_name, level="INFO", component=None,
                        source_ref_json=None):
    await db.db.execute(
        "INSERT INTO mca_events (ts, level, event_name, outcome, component, "
        "source_ref_json) VALUES (?, ?, ?, 'success', ?, ?)",
        (ts, level, event_name, component,
         (json.dumps(source_ref_json, ensure_ascii=False)
          if source_ref_json is not None else None)))
    await db.db.commit()


def _identity(**overrides) -> dict:
    payload = {
        "check": "source_identity", "revision_kind": "checkout",
        "version_verified": False, "deployed_sha": None,
        "checkout_sha": None, "sha_match": None, "reason": None,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_negative_control_empty_sources_no_invented_numbers():
    db = await _new_db()
    since = int(time.time()) - 86400
    try:
        blocks = await routes._self_diag_extras(db, since)
        assert blocks["db_growth"]["available"] is True
        assert blocks["db_growth"]["measured"] is False
        assert blocks["db_growth"]["db_growth_bytes"] is None
        assert blocks["db_growth"]["wal_growth_bytes"] is None
        assert blocks["golden_eval"]["false_diagnosis"] is None
        assert blocks["golden_eval"]["reason"] == "no_golden_run_recorded"
        assert blocks["code_checks"]["wrong_sha_reads"] is None
        assert blocks["code_checks"]["sha_verified_reads"] is None
        assert blocks["observed_vs_hypothesis"]["observed_share"] is None
        assert blocks["observed_vs_hypothesis"]["observed"] is None
        assert blocks["observed_vs_hypothesis"]["hypothesis"] is None
        assert blocks["observed_vs_hypothesis"]["hypothesis_available"] is False
        assert blocks["observed_vs_hypothesis"]["reason"] == \
            "no_diagnostic_runs_in_window"
        # Дискриминирующий контроль: сериализованный payload не содержит
        # подставленного нуля ни в одном из неизмеренных полей.
        wire = json.loads(json.dumps(blocks, ensure_ascii=False))
        for value in (
                wire["db_growth"]["db_growth_bytes"],
                wire["db_growth"]["wal_growth_bytes"],
                wire["golden_eval"]["false_diagnosis"],
                wire["code_checks"]["wrong_sha_reads"],
                wire["observed_vs_hypothesis"]["observed_share"],
                wire["observed_vs_hypothesis"]["observed"]):
            assert value is None, f"выдуманный ноль вместо null: {value!r}"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_incidents_grouped_by_subsystem():
    db = await _new_db()
    now = int(time.time())
    since = now - 86400
    try:
        await _insert_incident(db, incident_id="i1", subsystem="jobs_a",
                               severity="ERROR", repeat=3, last_ts=now - 100)
        await _insert_incident(db, incident_id="i2", subsystem="jobs_a",
                               severity="WARN", repeat=1, last_ts=now - 200,
                               acknowledged_at=now - 150)
        await _insert_incident(db, incident_id="i3", subsystem="summary",
                               severity="INFO", repeat=2, last_ts=now - 300)
        await _insert_incident(db, incident_id="i4", subsystem="summary",
                               severity="ERROR", repeat=1, last_ts=now - 40,
                               acknowledged_at=now - 30,
                               resolved_at=now - 20)
        await _insert_incident(db, incident_id="i5", subsystem="old",
                               severity="ERROR", repeat=9, last_ts=now - 90000,
                               resolved_at=now - 89900)
        await _insert_event(db, ts=now - 10, event_name="x", level="ERROR",
                            component="db")
        await _insert_event(db, ts=now - 20, event_name="x", level="ERROR",
                            component="db")
        await _insert_event(db, ts=now - 30, event_name="x", level="ERROR",
                            component="llm")
        await _insert_event(db, ts=now - 40, event_name="x", level="WARN",
                            component="db")
        await _insert_event(db, ts=now - 90000, event_name="x", level="ERROR",
                            component="old")
        block = await routes._self_diag_incidents(db, since)
        assert block["available"] is True and block["measured"] is True
        assert block["active"] == 3
        assert block["unacknowledged"] == 2
        assert block["in_window"] == 4
        by_subsystem = {row["subsystem"]: row for row in block["by_subsystem"]}
        assert set(by_subsystem) == {"jobs_a", "summary"}
        assert by_subsystem["jobs_a"]["active"] == 2
        assert by_subsystem["jobs_a"]["unacknowledged"] == 1
        assert by_subsystem["jobs_a"]["repeats"] == 4
        assert by_subsystem["jobs_a"]["worst_severity"] == "ERROR"
        assert by_subsystem["summary"]["active"] == 1
        assert by_subsystem["summary"]["repeats"] == 2
        assert by_subsystem["summary"]["worst_severity"] == "INFO"
        errors = {row["component"]: row["errors"]
                  for row in block["errors_by_component"]}
        assert errors == {"db": 2, "llm": 1}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_incidents_disabled_gate_returns_unavailable(monkeypatch):
    db = await _new_db()
    try:
        monkeypatch.setattr(mca_gates, "incidents_enabled", lambda: False)
        block = await routes._self_diag_incidents(db, 0)
        assert block["available"] is False
        assert block["reason"] == "incidents_disabled"
        assert block["active"] is None
        assert block["unacknowledged"] is None
        assert block["in_window"] is None
        assert block["by_subsystem"] == []
        assert block["errors_by_component"] == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_golden_run_aggregated_from_latest_event():
    db = await _new_db()
    now = int(time.time())
    try:
        await _insert_event(
            db, ts=now - 500, event_name="self_diag_golden_run",
            component="self_diag", source_ref_json={
                "schema": 1, "case_total": 37, "passed": 30, "failed": 7,
                "false_diagnosis": 7, "false_diagnosis_ids": ["old"],
                "by_category": {"negative": 7}, "code_sha": "a" * 40})
        latest = {
            "schema": 1, "case_total": 37, "passed": 36, "failed": 1,
            "false_diagnosis": 1,
            "false_diagnosis_ids": [f"G{i:02d}" for i in range(25)],
            "by_category": {"negative": 1, "style": 2},
            "code_sha": "b" * 40,
        }
        await _insert_event(
            db, ts=now - 10, event_name="self_diag_golden_run",
            component="self_diag", source_ref_json=latest)
        block = await routes._self_diag_golden_eval(db, now - 86400)
        assert block["available"] is True and block["measured"] is True
        assert block["run_ts"] == now - 10
        assert block["case_total"] == 37
        assert block["passed"] == 36
        assert block["failed"] == 1
        assert block["false_diagnosis"] == 1
        assert len(block["false_diagnosis_ids"]) == 20
        assert block["by_category"] == {"negative": 1, "style": 2}
        assert block["code_sha"] == "b" * 40
        assert block["schema"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_claims_share_from_instrumented_events():
    db = await _new_db()
    now = int(time.time())
    try:
        await _insert_event(
            db, ts=now - 10, event_name="checkup_triggered",
            component="checkup", source_ref_json={"claims": {
                "observed": 4, "correlated": 1, "not_checked": 2,
                "unknown": 0}})
        await _insert_event(
            db, ts=now - 20, event_name="inspect_runtime_called",
            component="self_diag", source_ref_json={"claims": {
                "observed": 2, "correlated": 0, "not_checked": 1,
                "unknown": 0}})
        # События без claims и чужие имена не входят в знаменатель.
        await _insert_event(db, ts=now - 30, event_name="checkup_triggered",
                            component="checkup")
        await _insert_event(
            db, ts=now - 40, event_name="get_bot_health_called",
            component="self_diag", source_ref_json={"claims": {
                "observed": 99, "correlated": 0, "not_checked": 0}})
        block = await routes._self_diag_observed_vs_hypothesis(db, now - 86400)
        assert block["runs"] == 2
        assert block["observed"] == 6
        assert block["correlated"] == 1
        assert block["not_checked"] == 3
        assert block["observed_share"] == 0.6
        assert block["measured"] is True
        assert block["hypothesis"] is None
        assert block["hypothesis_available"] is False
        assert block["hypothesis_share"] is None
        assert block["note"] == "no_hypothesis_producer"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_wrong_sha_detected_from_read_events():
    db = await _new_db()
    now = int(time.time())
    try:
        await _insert_event(
            db, ts=now - 10, event_name="read_source_verified",
            source_ref_json=_identity(
                deployed_sha="a" * 40, checkout_sha="b" * 40,
                sha_match=False, version_verified=False))
        await _insert_event(
            db, ts=now - 20, event_name="code_unavailable",
            source_ref_json=_identity(reason="commit_mismatch"))
        await _insert_event(
            db, ts=now - 30, event_name="read_source_verified",
            source_ref_json=_identity(
                deployed_sha="c" * 40, checkout_sha="c" * 40,
                sha_match=True, version_verified=True))
        await _insert_event(
            db, ts=now - 40, event_name="read_source_verified",
            source_ref_json=_identity(
                revision_kind="deployed_files", version_verified=False))
        await _insert_event(
            db, ts=now - 50, event_name="read_source_verified",
            source_ref_json={"not_identity": True})
        block = await routes._self_diag_code_checks(db, now - 86400)
        assert block["available"] is True and block["measured"] is True
        assert block["reads"] == 4
        assert block["wrong_sha_reads"] == 2
        assert block["sha_verified_reads"] == 1
        assert block["sha_unproven_reads"] == 1
        assert block["mismatch_reasons"] == {"commit_mismatch": 1}

        empty = await _new_db()
        try:
            none_block = await routes._self_diag_code_checks(empty, 0)
            assert none_block["available"] is True
            assert none_block["measured"] is False
            assert none_block["reason"] == "no_reads_in_window"
            assert none_block["reads"] is None
            assert none_block["wrong_sha_reads"] is None
        finally:
            await empty.close()
    finally:
        await db.close()


def _capture_emit(monkeypatch) -> list:
    captured: list = []

    def _fake_emit(event_name, **fields):
        captured.append((event_name, fields))
        return {"event_name": event_name}

    monkeypatch.setattr(tool_router_module._mca_events, "emit_mca_event",
                        _fake_emit)
    return captured


def test_emit_read_source_outcome_attaches_identity(monkeypatch):
    captured = _capture_emit(monkeypatch)
    router = ToolRouter(ToolDeps(None, None))
    payload = json.dumps({
        "status": "ok", "verified": True, "read_level": "parsed",
        "provenance": {
            "deployed_sha": "a" * 40, "checkout_sha": "b" * 40,
            "revision_kind": "checkout", "version_verified": False,
        },
    })
    router._emit_read_source_outcome(
        payload, ToolContext(1, "q"), 12)
    assert [name for name, _ in captured] == ["read_source_verified"]
    ref = captured[0][1]["source_ref_json"]
    assert ref["check"] == "source_identity"
    assert ref["sha_match"] is False
    assert ref["deployed_sha"] == "a" * 40
    assert ref["checkout_sha"] == "b" * 40
    assert ref["revision_kind"] == "checkout"
    assert ref["version_verified"] is False
    assert set(ref) == {"check", "revision_kind", "version_verified",
                        "deployed_sha", "checkout_sha", "sha_match", "reason"}
    wire = json.dumps(captured[0][1], ensure_ascii=False)
    assert "/" not in wire and "http" not in wire

    captured.clear()
    router._emit_read_source_outcome(json.dumps({
        "status": "unavailable", "error": "commit_not_available",
        "reason": "requested_commit_unavailable"}), ToolContext(1, "q"), 5)
    assert [name for name, _ in captured] == ["code_unavailable"]
    assert captured[0][1]["source_ref_json"]["reason"] == \
        "requested_commit_unavailable"


def test_emit_inspect_event_counts_claim_kinds(monkeypatch):
    captured = _capture_emit(monkeypatch)
    page = {
        "status": "ok", "probe": "logs.errors", "latency_ms": 7,
        "claims": [
            {"kind": "observed", "statement": "СЕКРЕТ-ТЕКСТ-1"},
            {"kind": "correlated", "statement": "СЕКРЕТ-ТЕКСТ-2"},
            {"kind": "observed", "statement": "СЕКРЕТ-ТЕКСТ-3"},
        ],
    }
    ToolRouter._emit_inspect_event(ToolContext(5, "q"), page)
    assert captured[0][0] == "inspect_runtime_called"
    ref = captured[0][1]["source_ref_json"]
    assert ref == {"claims": {"observed": 2, "correlated": 1,
                              "not_checked": 0, "unknown": 0}}
    assert "СЕКРЕТ" not in json.dumps(captured[0][1], ensure_ascii=False)


def test_emit_checkup_event_adds_claim_counts(monkeypatch):
    captured = _capture_emit(monkeypatch)
    bundle = {
        "status": "complete",
        "sources": [{"source_id": "logs.errors"}],
        "not_checked": [],
        "claims": [
            {"kind": "observed", "statement": "ТЕКСТ-ОТЧЁТА"},
            {"kind": "not_checked", "statement": "ТЕКСТ-ПРОМПТА"},
        ],
    }
    checkup_handler.emit_checkup_event(
        outcome="success", chat_id=10, status="report_sent",
        duration_ms=100, bundle=bundle, telemetry={"prompt_source": "db"})
    assert captured[0][0] == "checkup_triggered"
    ref = captured[0][1]["source_ref_json"]
    assert ref["claims"] == {"observed": 1, "correlated": 0,
                             "not_checked": 1, "unknown": 0}
    assert ref["bundle_status"] == "complete"
    wire = json.dumps(captured[0][1], ensure_ascii=False)
    assert "ТЕКСТ-ОТЧЁТА" not in wire and "ТЕКСТ-ПРОМПТА" not in wire


@pytest.mark.asyncio
async def test_samples_series_bounded_to_window():
    db = await _new_db()
    now = int(time.time())
    try:
        rows = [(now - 400 + index, 100 + index) for index in range(400)]
        await db.write_transaction(
            lambda conn: _bulk_samples(conn, rows),
            op_name="test_bulk_samples")
        block = await routes._self_diag_samples_block(db, now - 86400)
        assert block["available"] is True
        assert len(block["samples"]) == 288
        ts_values = [row["ts"] for row in block["samples"]]
        assert ts_values == sorted(ts_values)
        db_growth, queue_growth = routes._self_diag_growth_blocks(block)
        assert db_growth["sample_count"] == 288
        assert queue_growth["sample_count"] == 288
        assert queue_growth["current"]["oldest_age_seconds"] == 42
        assert block["process_segments"] == 1
    finally:
        await db.close()


async def _bulk_samples(conn, rows):
    for ts, value in rows:
        await conn.execute(
            "INSERT INTO self_diag_samples (ts, pid, process_started_at, "
            "db_bytes, wal_bytes, disk_free_bytes, queue_depth, "
            "queue_age_seconds, sample_source) VALUES (?, 777, 1, ?, 10, "
            "1000, ?, 42, 'maintenance_tick')", (ts, value, value % 5))
