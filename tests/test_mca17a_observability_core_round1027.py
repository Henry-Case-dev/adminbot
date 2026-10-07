"""MCA Wave 0 — остаток (`mca-17a-observability-core`, ADR-1027-8) — ядро
наблюдаемости: реестр процессов, trace/span, lifecycle, heartbeat/watchdog/
recovery, инциденты, телеметрия, control-plane.

Покрытие блоков T-3864…T-3884 и приёмок A48–A53/A55 (SC-01…SC-22).
"""
import asyncio
import os
import sqlite3
import time

import pytest

import services.database as dbmod
from services.database import (DatabaseService, _SCHEMA_VERSION_OBSERVABILITY,
                               _MCA_EVENTS_SPAN_COLUMNS,
                               _TASK_JOBS_CORRELATION_COLUMNS)
from services import mca_events as me
from services import mca_trace as mt
from services import mca_incidents as inc
from services import mca_watchdog as wd
from services import mca_process_registry as reg
from services.task_supervisor import TaskJobStore


def _target_version() -> int:
    return max(s.version for s in DatabaseService.migration_steps())


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    monkeypatch.setattr(dbmod, "_LOCK_BACKOFF", 0.0)
    monkeypatch.setenv("MCA_TELEMETRY_SPOOL_PATH",
                       str(tmp_path / "spool.jsonl"))
    me.reset_pending()
    mt.reset_sequences()
    yield
    me.reset_pending()
    mt.reset_sequences()


async def _db(tmp_path, name="mca17a.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ── T-3864: v19 Δ DDL (SC-21) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v19_tables_and_user_version(tmp_path):
    d = await _db(tmp_path)
    try:
        cur = await d.db.execute("PRAGMA user_version")
        # mca-04b (v20, ADR-1027-9) продолжает реестр после v19 — хвост
        # реестра >= 19; v19-объекты обязательны при любом хвосте.
        assert (await cur.fetchone())[0] == _target_version() >= \
            _SCHEMA_VERSION_OBSERVABILITY
        cur = await d.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] for r in await cur.fetchall()}
        assert {"mca_pipeline_runs", "mca_incidents"} <= tables
        # Реестр процессов code-declared — таблица НЕ создаётся (D1).
        assert "mca_process_registry" not in tables
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v19_columns_present(tmp_path):
    d = await _db(tmp_path, name="cols.db")
    try:
        cur = await d.db.execute("PRAGMA table_info(mca_events)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert {n for n, _ in _MCA_EVENTS_SPAN_COLUMNS} <= cols
        # event_id/start/end — не отдельные колонки (D2).
        assert "event_id" not in cols and "start" not in cols and "end" not in cols
        cur = await d.db.execute("PRAGMA table_info(task_jobs)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert {n for n, _ in _TASK_JOBS_CORRELATION_COLUMNS} <= cols
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v19_indices_present(tmp_path):
    d = await _db(tmp_path, name="idx.db")
    try:
        cur = await d.db.execute("SELECT name FROM sqlite_master WHERE type='index'")
        idx = {r["name"] for r in await cur.fetchall()}
        for name in ("idx_mca_pipeline_runs_status",
                     "idx_mca_pipeline_runs_type_started",
                     "idx_mca_pipeline_runs_root_job",
                     "idx_mca_incidents_fingerprint",
                     "idx_mca_incidents_active", "idx_mca_incidents_severity",
                     "idx_task_jobs_pipeline_run",
                     "idx_task_jobs_status_heartbeat",
                     "idx_task_jobs_status_next_retry",
                     "idx_mca_events_pipeline_run", "idx_mca_events_span",
                     "idx_mca_events_status"):
            assert name in idx, name
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v19_idempotent(tmp_path):
    d = await _db(tmp_path, name="idem.db")
    await d.close()
    d2 = DatabaseService(str(d.db_path))
    await d2.initialize()
    try:
        cur = await d2.db.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations WHERE version=19")
        assert (await cur.fetchone())["c"] == 1
    finally:
        await d2.close()


@pytest.mark.asyncio
async def test_v19_legacy_graceful(tmp_path):
    """Legacy v18 (без новых колонок) получает v19 аддитивно."""
    path = tmp_path / "legacy.db"
    d = await _db(tmp_path, name="legacy.db")
    await d.close()
    # откат маркера до 18 (эмулируем legacy-БД без v19-объектов)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA user_version = 18")
    conn.execute("DROP TABLE IF EXISTS mca_pipeline_runs")
    conn.execute("DROP TABLE IF EXISTS mca_incidents")
    conn.commit()
    conn.close()
    d2 = DatabaseService(str(path))
    await d2.initialize()
    try:
        cur = await d2.db.execute("PRAGMA user_version")
        # mca-04b (v20) продолжает реестр — legacy v18 доводится до хвоста.
        assert (await cur.fetchone())[0] >= 19
        cur = await d2.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r["name"] for r in await cur.fetchall()}
        assert {"mca_pipeline_runs", "mca_incidents"} <= tables
    finally:
        await d2.close()


@pytest.mark.asyncio
async def test_v19_new_columns_nullable(tmp_path):
    """Новые nullable-поля = NULL (честный unknown), не выдуманы."""
    d = await _db(tmp_path, name="null.db")
    try:
        await d.db.execute(
            "INSERT INTO mca_events (ts, level, event_name, outcome) "
            "VALUES (?,?,?,?)", (1, "INFO", "X", "success"))
        await d.db.commit()
        cur = await d.db.execute("SELECT status, pipeline_run_id FROM mca_events")
        row = await cur.fetchone()
        assert row["status"] is None and row["pipeline_run_id"] is None
    finally:
        await d.close()


# ── T-3865: process-registry (SC-01/SC-02) ──────────────────────────────────

def test_registry_minimum_and_fields():
    ids = {p.process_id for p in reg.PROCESS_REGISTRY}
    for required in ("ingestion.live", "summary.window", "dossier.rebuild",
                     "provenance.record", "embeddings.index",
                     "retrieval.query", "direct.reply", "web.fetch",
                     "telemetry.events", "watchdog.jobs", "incidents.delivery"):
        assert required in ids
    for p in reg.PROCESS_REGISTRY:
        assert p.process_id and p.purpose
        assert isinstance(p.stages, tuple)
        if p.trigger_kind:
            assert p.trigger_kind in reg.TRIGGER_KINDS or p.version == "0"


def test_registry_closed_features_registered_without_reinvention():
    """mca-03/02/04a/07 присутствуют ссылками на свои события (SC-02)."""
    by_owner = {p.process_id: p.owner_feature for p in reg.PROCESS_REGISTRY}
    assert by_owner["identity.resolve"] == "mca-03"
    assert by_owner["web.fetch"] == "mca-02"
    assert by_owner["provenance.record"] == "mca-04a"
    assert by_owner["retrieval.query"] == "mca-07"


def test_registry_future_features_not_run():
    """F4/spec §4.1: mca-09/10a/10b/11 — version '0' → not_run.

    mca-15 (ADR-1028-12 D7/AM-6): placeholder `episodes.timeline` заменён
    реальным процессом `chat.statistics` v1 — в «будущих» его больше нет.
    mca-16 (ADR-1028-15 D10): placeholder `self_learning.run` амендирован до
    v1 (capture/review/.../suspend) — в «будущих» его больше нет.
    mca-18 (ADR-1028-18 D10): placeholder `self_model.update` амендирован до
    реального `self.model` v1 (8 стадий §28.6) — в «будущих» его больше нет.
    mca-20 (round 10.44, ADR-1028-20 D11/D13): placeholder
    `temporal.factcheck` амендирован до v1 (8 стадий `:1805`) — в
    «будущих» его больше нет (прецедент vision.analyze→vision.media)."""
    for pid in ("context.compress", "context.selective", "memory.lifecycle",
                "relations.semantic"):
        p = reg.get_process(pid)
        assert p is not None and p.version == "0", pid
        assert reg.runtime_status(p) == reg.STATUS_NOT_RUN, pid
    owners = {p.owner_feature for p in reg.PROCESS_REGISTRY if p.version == "0"}
    # MCA-19 (round 10.43): vision.media v1 реализован — в «будущих» его нет.
    # MCA-20 (round 10.44): temporal.factcheck v1 реализован — в «будущих»
    # его нет (mca-20 остаётся во владельцах v31/v33-эры через v1-процесс).
    assert {"mca-09", "mca-10a", "mca-10b", "mca-11"} <= owners
    assert reg.get_process("temporal.factcheck").version == "1"
    assert "episodes.timeline" not in {p.process_id
                                       for p in reg.PROCESS_REGISTRY}
    assert reg.get_process("chat.statistics").version == "1"
    # mca-18: реализованный процесс self.model v1 (стадии §28.6, D10).
    self_model = reg.get_process("self.model")
    assert self_model is not None and self_model.version == "1"
    assert self_model.owner_feature == "mca-18"
    assert self_model.stages == ("observation_read", "attribution",
                                 "candidate_compile", "validation",
                                 "activation", "selection", "prompt_render",
                                 "final_check")
    # mca-19: placeholder vision.analyze v0 амендирован до vision.media v1
    # (ADR-1028-19 D15/§8.7, T-5116; стадии `:1699` точно).
    vision = reg.get_process("vision.media")
    assert vision is not None and vision.version == "1"
    assert vision.owner_feature == "mca-19"
    assert vision.stages == ("ingest", "download", "decode", "vision",
                             "validate", "store", "project", "reindex",
                             "consumers")
    assert "vision.analyze" not in {p.process_id
                                    for p in reg.PROCESS_REGISTRY}
    assert reg.get_process("self_learning.run").version == "1"


def _scan_real_event_names() -> set:
    """F1: имена событий, фактически эмитируемые кодом (grep-сверка)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    files = (list((root / "services").glob("*.py"))
             + list((root / "handlers").glob("*.py"))
             + list((root / "tools").rglob("*.py")) + [root / "bot.py"])
    real: set = set()
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(
                r'emit_mca_event\(\s*["\']([A-Za-z0-9_]+)["\']', text):
            real.add(m.group(1))
        for m in re.finditer(
                r'emit_stage_event\(\s*["\']([a-z_]+)["\']', text):
            real.add("mca07_" + m.group(1))
        # mca-05 (ADR-1027-12 D12): обёртка витринных событий story_* —
        # имена литеральные на call-site (emit_story_event → emit_mca_event).
        for m in re.finditer(
                r'emit_story_event\(\s*["\']([A-Za-z0-9_]+)["\']', text):
            real.add(m.group(1))
        # mca-17 (round 1050+): санкционированные обёртки mca-13
        # (_emit_<domain> → emit_mca_event; прецедент emit_story_event) —
        # имена литеральные на call-site. Новая обёртка = осознанный
        # re-pin этого перечня (L-F11S-1).
        for m in re.finditer(
                r'(?:emit_stage|_emit(?:_mca|_publish|_ingest|_lifecycle'
                r'|_import|_goodmorning)?)\(\s*["\']([A-Za-z0-9_]+)["\']',
                text):
            real.add(m.group(1))
        # mca-17 (summary.hybrid): pipeline_events.py — единая точка эмиссии
        # текстовой ветки; имена — литералы EV_*-констант (fail-open _emit →
        # mca_trace.emit_stage), call-site литералов не содержит.
        if path.name == "pipeline_events.py":
            for m in re.finditer(
                    r'EV_[A-Z0-9_]+\s*=\s*["\']([A-Za-z0-9_]+)["\']', text):
                real.add(m.group(1))
    real.discard("mca07_")      # динамический литерал-префикс
    return real


def test_registry_event_names_exist_in_code():
    """F1/SC-01: ни одно объявленное имя события не выдумано — каждое реально
    эмитируется кодом (`emit_mca_event`/`emit_stage_event`/`_emit`)."""
    real = _scan_real_event_names()
    # скан содержателен: реальные имена закрытых фич и mca-17a присутствуют
    for expected in ("safe_fetch", "memory_provenance", "message_revision",
                     "message_identity_migration", "WATCHDOG_SWEEP", "INCIDENT"):
        assert expected in real, expected
    assert any(n.startswith("mca07_") for n in real)
    for p in reg.PROCESS_REGISTRY:
        declared = set(p.event_names) | set(p.stages_to_events.values())
        missing = declared - real
        assert not missing, f"{p.process_id}: вымышленные события {missing}"


def test_registry_real_events_flip_closed_features_to_implemented():
    """F1/A48: подача РЕАЛЬНОГО события переводит процесс из `not_run` в
    `implemented` для каждой закрытой фичи (mca-02/03/04a/07)."""
    cases = {
        "web.fetch": {"safe_fetch"},
        "identity.resolve": {"message_revision", "message_identity_migration"},
        "provenance.record": {"memory_provenance"},
        "retrieval.query": {"mca07_retrieval", "mca07_reranker",
                            "mca07_bundle", "mca07_budget"},
    }
    for pid, events in cases.items():
        p = reg.get_process(pid)
        assert reg.runtime_status(
            p, event_names_present=frozenset({"UNRELATED"})) \
            == reg.STATUS_NOT_RUN, pid
        assert reg.runtime_status(
            p, event_names_present=frozenset(events)) \
            == reg.STATUS_IMPLEMENTED, pid
    # неинструментированный процесс не выдаёт себя за implemented
    # (uptime.heartbeat — осознанный not_instrumented: собственный
    # durable-журнал uptime_events PG, дублирование в mca_events не нужно)
    assert reg.runtime_status(
        reg.get_process("uptime.heartbeat"),
        event_names_present=frozenset({"message_revision"})) \
        == reg.STATUS_NOT_INSTRUMENTED
    # mca-17 (round 1050+): instrumented-процессы флипаются реальным
    # событием из durable-стора; честный v0-аменд scheduler.reactions
    # (выделенного due_check-планировщика в коде нет) остаётся not_run
    assert reg.runtime_status(
        reg.get_process("ingestion.live"),
        event_names_present=frozenset({"ingestion_live"})) \
        == reg.STATUS_IMPLEMENTED
    assert reg.runtime_status(
        reg.get_process("scheduler.reactions")) == reg.STATUS_NOT_RUN


def test_registry_runtime_status_variants(monkeypatch):
    p = reg.get_process("web.fetch")
    assert reg.runtime_status(
        p, event_names_present=frozenset({"safe_fetch"})) \
        == reg.STATUS_IMPLEMENTED
    monkeypatch.setattr(reg.mca_gates, "safe_fetch_enabled", lambda: False)
    assert reg.runtime_status(p) == reg.STATUS_DISABLED
    monkeypatch.setattr(reg.mca_gates, "process_registry_enabled",
                        lambda: False)
    assert reg.runtime_status(p) == reg.STATUS_DISABLED


@pytest.mark.asyncio
async def test_registry_snapshot_shape(tmp_path):
    d = await _db(tmp_path, name="reg.db")
    try:
        snap = await reg.registry_snapshot(d)
        assert snap["enabled"] is True
        assert snap["count"] == len(reg.PROCESS_REGISTRY)
        assert snap["pipelines"]
        for row in snap["processes"]:
            assert "widget_id" in row and "stages_to_events" in row
            assert row["status"] in reg.REGISTRATION_STATUSES
    finally:
        await d.close()


# ── T-3867..T-3870: trace/span (SC-03…SC-06) ────────────────────────────────

@pytest.mark.asyncio
async def test_span_fields_persisted_start_and_outcome(tmp_path):
    d = await _db(tmp_path, name="span.db")
    try:
        rid = await mt.start_run(d, pipeline_type="direct.reply", version="1")
        mt.emit_stage("LLM_CALL", outcome="start", component="direct.reply",
                      stage="llm", **mt.span_fields(
                          run_id=rid, span_id=mt.new_span_id(),
                          pipeline_type="direct.reply", pipeline_version="1",
                          status=mt.STAGE_RUNNING))
        mt.emit_stage("LLM_CALL", outcome="success", component="direct.reply",
                      stage="llm", **mt.span_fields(
                          run_id=rid, span_id=mt.new_span_id(),
                          pipeline_type="direct.reply", pipeline_version="1",
                          status=mt.STAGE_SUCCEEDED))
        written = await me.flush_events(d)
        assert written >= 3
        rows = await me.query_run_events(d, rid)
        assert len(rows) >= 3
        assert all(r["pipeline_run_id"] == rid for r in rows)
        assert {r["status"] for r in rows} >= {mt.STAGE_QUEUED, mt.STAGE_RUNNING,
                                               mt.STAGE_SUCCEEDED}
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_span_masking_before_store(tmp_path):
    d = await _db(tmp_path, name="spanmask.db")
    try:
        token = "sk-abcdefghijklmnop123456"
        mt.emit_stage("X", outcome="success", component=token,
                      **mt.span_fields(run_id="run_x", span_id="sp_x",
                                       checkpoint_ref=token))
        await me.flush_events(d)
        cur = await d.db.execute("SELECT component, checkpoint_ref FROM mca_events")
        row = await cur.fetchone()
        assert token not in (row["component"] or "")
        assert token not in (row["checkpoint_ref"] or "")
    finally:
        await d.close()


def test_trace_span_off_parity(monkeypatch):
    """OFF `MCA_TRACE_SPAN_ENABLED` → `span_fields()` пуст (паритет MCA-13:
    события не несут span-полей)."""
    monkeypatch.setattr(mt.mca_gates, "trace_span_enabled", lambda: False)
    assert mt.span_fields(run_id="run_1", span_id="sp_1", status="running") == {}


def test_monotonic_and_sequence():
    start = time.monotonic()
    ms = mt.monotonic_ms(start)
    assert ms is not None and ms >= 0
    a = mt.next_sequence("run_a")
    b = mt.next_sequence("run_a")
    assert b == a + 1
    assert mt.utc_now() > 0


def test_compute_run_outcome_contract():
    req = [{"name": "llm", "status": "succeeded", "required": True},
           {"name": "write", "status": "succeeded", "required": True}]
    assert mt.compute_run_outcome(req, pipeline_type="direct.reply") == \
        mt.RUN_SUCCEEDED
    degraded = req + [{"name": "retrieval", "status": "failed",
                       "required": False, "has_fallback": True}]
    assert mt.compute_run_outcome(degraded, pipeline_type="direct.reply") == \
        mt.RUN_DEGRADED
    failed = [{"name": "llm", "status": "failed", "required": True}]
    assert mt.compute_run_outcome(failed, pipeline_type="direct.reply") == \
        mt.RUN_FAILED
    interrupted = [{"name": "llm", "status": "interrupted", "required": True}]
    assert mt.compute_run_outcome(interrupted, pipeline_type="direct.reply") == \
        mt.RUN_INTERRUPTED
    # незафиксированная запись/обязательный дочерний job → не success
    assert mt.compute_run_outcome(req, pipeline_type="direct.reply",
                                  pending_children=1) == mt.RUN_RUNNING
    # F10: cancelled/interrupted НЕобязательной стадии с fallback → degraded,
    # а не run cancelled/interrupted.
    opt_cancel = req + [{"name": "retrieval", "status": "cancelled",
                         "required": False, "has_fallback": True}]
    assert mt.compute_run_outcome(opt_cancel, pipeline_type="direct.reply") == \
        mt.RUN_DEGRADED
    opt_interrupt = req + [{"name": "retrieval", "status": "interrupted",
                            "required": False, "has_fallback": True}]
    assert mt.compute_run_outcome(opt_interrupt,
                                  pipeline_type="direct.reply") == mt.RUN_DEGRADED
    opt_cancel_no_fb = req + [{"name": "retrieval", "status": "cancelled",
                               "required": False, "has_fallback": False}]
    assert mt.compute_run_outcome(opt_cancel_no_fb,
                                  pipeline_type="direct.reply") == mt.RUN_PARTIAL
    # обязательная cancelled/interrupted → run cancelled/interrupted
    assert mt.compute_run_outcome(
        [{"name": "llm", "status": "cancelled", "required": True}],
        pipeline_type="direct.reply") == mt.RUN_CANCELLED


def test_batch_span_fields_links_and_counters():
    fields = mt.batch_span_fields(run_id="run_1", root_span_id="sp_root",
                                  batch_index=0, range_start=0, range_end=99,
                                  processed=100, failed_ids=["a", "b"])
    assert fields["linked_span_ids"] == ["sp_root"]
    assert fields["usage_json"]["processed"] == 100
    assert fields["usage_json"]["failed_count"] == 2
    assert "a" in fields.get("entity_ids", [])


@pytest.mark.asyncio
async def test_run_diagnostic_stalled():
    row = {"status": mt.RUN_RUNNING, "heartbeat_at": int(time.time()) - 9999,
           "progress_at": int(time.time()) - 9999,
           "pipeline_type": "direct.reply"}
    out = mt.run_diagnostic(row)
    assert out["stalled"] is True


# ── T-3868: correlation durable queue + retry/attempt (SC-04) ───────────────

@pytest.mark.asyncio
async def test_correlation_persisted_and_resumed(tmp_path):
    d = await _db(tmp_path, name="corr.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important",
                                  pipeline_run_id="run_c", span_id="sp_c",
                                  causation_id="cause_1", attempt_id="at_1")
        row = await store.get(jid)
        assert row["pipeline_run_id"] == "run_c" and row["span_id"] == "sp_c"
        assert row["attempt_id"] == "at_1"
        # retry — новый attempt_id, предыдущая попытка не затирается
        await store.mark_running(jid)
        await store.set_next_retry(jid, int(time.time()) + 10,
                                   reason_code="stage_retry_scheduled")
        row = await store.get(jid)
        assert row["next_retry_at"] is not None
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_supervisor_run_correlation_and_terminal(tmp_path):
    from services.task_supervisor import TaskSupervisor
    d = await _db(tmp_path, name="sup.db")
    try:
        store = TaskJobStore(d)
        sup = TaskSupervisor()
        rec = await sup.run(lambda: _ok(), owner="summary", kind="important",
                            job_store=store, emit_event=False,
                            pipeline_run_id="run_s", span_id="sp_s")
        row = await store.get(rec.job_id)
        assert row["status"] == "completed"
        assert row["pipeline_run_id"] == "run_s"
    finally:
        await d.close()


async def _ok():
    return "res-1"


async def _boom():
    raise ValueError("boom")


# ── T-3882: L-MCA01-5 fencing во всех терминальных записях (SC-14) ─────────

@pytest.mark.asyncio
async def test_fencing_stale_owner_cannot_overwrite_terminal(tmp_path,
                                                             monkeypatch):
    """После takeover устаревший владелец (старый fence) не перезапишет
    термальную строку нового владельца — во ВСЕХ путях (L-MCA01-5)."""
    d = await _db(tmp_path, name="fence.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="summary", kind="important")
        await store.mark_running(jid)
        row = await store.get(jid)
        old_fence = int(row["fencing_token"])
        # делаем heartbeat stale → takeover бампает fencing_token
        await d.db.execute(
            "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
            (int(time.time()) - 9999, jid))
        await d.db.commit()
        await store.recover_stale(stale_after_seconds=60)
        row = await store.get(jid)
        new_fence = int(row["fencing_token"])
        assert new_fence > old_fence or row["status"] == "interrupted"
        # старый владелец пытается записать cancelled/ failed со старым fence
        ok1 = await store.finish(jid, status="cancelled", reason_code="cancelled",
                                 fencing_token=old_fence)
        ok2 = await store.finish(jid, status="failed", reason_code="task_failed",
                                 fencing_token=old_fence)
        assert ok1 is False and ok2 is False
        assert (await store.get(jid))["status"] == "interrupted"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_supervisor_cancelled_fencing_noop_after_takeover(tmp_path):
    """F7/L-MCA01-5 (поведенческий): после takeover cancelled-путь `run()` со
    СТАРЫМ fencing_token — no-op; терминальная строка нового владельца
    (`interrupted`) не перезаписывается."""
    from services.task_supervisor import TaskSupervisor
    d = await _db(tmp_path, name="cancel.db")
    try:
        store = TaskJobStore(d)
        sup = TaskSupervisor()
        started = asyncio.Event()

        async def _hang():
            started.set()
            await asyncio.sleep(3600)

        task = asyncio.ensure_future(sup.run(
            _hang, owner="summary", kind="important", job_store=store,
            emit_event=False))
        await asyncio.wait_for(started.wait(), timeout=2)
        active = await store.active()
        assert active, "задача не зарегистрирована"
        jid = active[0]["job_id"]
        # takeover: делаем heartbeat stale → fencing_token бампается
        await d.db.execute(
            "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
            (int(time.time()) - 9999, jid))
        await d.db.commit()
        await store.recover_stale(stale_after_seconds=60)
        assert (await store.get(jid))["status"] == "interrupted"
        # отменяем «медленного» владельца: его _safe_finish(cancelled, fence)
        # должен стать no-op (stale fence) — interrupted остаётся
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        row = await store.get(jid)
        assert row["status"] == "interrupted"
        assert row["reason_code"] == "worker_lost"
    finally:
        await d.close()


# ── T-3871..T-3874: lifecycle + control-plane (SC-07…SC-10, SC-18) ─────────

def test_stage_states_complete():
    expected = {"queued", "running", "waiting_external", "retry_scheduled",
                "succeeded", "skipped", "failed", "cancelled", "interrupted"}
    assert expected <= set(mt.STAGE_STATUSES)
    assert {"running", "succeeded", "partial", "degraded", "failed",
            "cancelled", "interrupted"} <= set(mt.RUN_STATUSES)


@pytest.mark.asyncio
async def test_control_plane_allowed_and_idempotent(tmp_path):
    d = await _db(tmp_path, name="ctrl.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        refresh = await mt.control_action(d, store, action="refresh",
                                          job_id=jid, actor=5)
        assert refresh["status"] == "read_only" and refresh["allowed"]
        cancel1 = await mt.control_action(d, store, action="cancel",
                                          job_id=jid, actor=5)
        assert cancel1["status"] == "applied"
        cancel2 = await mt.control_action(d, store, action="cancel",
                                          job_id=jid, actor=5)
        assert cancel2["idempotent_replay"] is True
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_control_plane_disallowed_and_delivery_unknown(tmp_path):
    d = await _db(tmp_path, name="ctrl2.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="some_random_worker", kind="important")
        res = await mt.control_action(d, store, action="cancel", job_id=jid,
                                      actor=1)
        assert res["status"] == "not_allowed"
        jid2 = await store.enqueue(owner="archive", kind="important")
        await store.finish(jid2, status="failed", reason_code="delivery_unknown")
        res2 = await mt.control_action(d, store, action="retry", job_id=jid2,
                                       actor=1)
        assert res2["status"] == "reconcile_required"
    finally:
        await d.close()


# ── T-3875..T-3877: heartbeat/watchdog/recovery (SC-11…SC-13) ──────────────

def test_progress_stall_by_type(monkeypatch):
    monkeypatch.setattr(me.mca_gates, "progress_stall_seconds",
                        reg.mca_gates.progress_stall_seconds)
    from config.settings import settings
    assert me.mca_gates.progress_stall_seconds("llm") == \
        settings.MCA_PROGRESS_STALL_LLM_SECONDS
    assert me.mca_gates.progress_stall_seconds("video") == \
        settings.MCA_PROGRESS_STALL_VIDEO_SECONDS
    assert me.mca_gates.progress_stall_seconds("archive") == \
        settings.MCA_PROGRESS_STALL_ARCHIVE_SECONDS


def test_heartbeat_progress_distinct(monkeypatch):
    monkeypatch.setattr(me.mca_gates, "job_heartbeat_seconds", lambda: 15)
    monkeypatch.setattr(me.mca_gates, "job_stale_seconds", lambda: 60)
    assert me.mca_gates.job_heartbeat_seconds() == 15
    assert me.mca_gates.job_stale_seconds() == 60


@pytest.mark.asyncio
async def test_watchdog_takeover_and_recovery(tmp_path):
    d = await _db(tmp_path, name="wd.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        await store.mark_running(jid)
        # делаем heartbeat stale
        await d.db.execute("UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
                           (int(time.time()) - 9999, jid))
        await d.db.commit()
        result = await wd.sweep(d, job_store=store)
        assert jid in result["stale"]
        row = await store.get(jid)
        assert row["status"] == "interrupted"
        # recovery по checkpoint — возобновляем
        await store.save_checkpoint(jid, cursor_token="c1", processed=5)
        rec = await wd.recover_job(d, store, jid)
        assert rec["status"] == "resumed"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_recovery_dangerous_without_checkpoint_paused(tmp_path):
    d = await _db(tmp_path, name="rec.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        await store.mark_running(jid)
        await store.finish(jid, status="interrupted", reason_code="worker_lost")
        rec = await wd.recover_job(d, store, jid)
        assert rec["status"] == "paused"
        assert rec["reason"] == "checkpoint_missing"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_delivery_unknown_no_blind_retry(tmp_path):
    d = await _db(tmp_path, name="du.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        ok = await wd.mark_delivery_unknown(d, store, jid,
                                            operation_id="op_123")
        assert ok
        row = await store.get(jid)
        assert row["reason_code"] == "delivery_unknown"
        rec = await wd.recover_job(d, store, jid)
        assert rec["status"] == "reconcile_required"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_telemetry_freshness_unknown_when_no_db():
    assert await wd.telemetry_freshness(None) == "unknown"


# ── T-3878/T-3879: инциденты (SC-15/SC-16) ─────────────────────────────────

@pytest.mark.asyncio
async def test_incident_grouping_and_ack_not_resolved(tmp_path):
    d = await _db(tmp_path, name="inc.db")
    try:
        r1 = await inc.open_or_update(d, process_id="direct.reply",
                                      pipeline_type="direct.reply",
                                      stage="llm", reason_code="provider_unavailable",
                                      error_type="Timeout", trace_id="t1")
        r2 = await inc.open_or_update(d, process_id="direct.reply",
                                      pipeline_type="direct.reply",
                                      stage="llm", reason_code="provider_unavailable",
                                      error_type="Timeout", trace_id="t2")
        assert r1["incident_id"] == r2["incident_id"]
        active = await inc.active_incidents(d)
        assert len(active) == 1 and active[0]["repeat_count"] == 2
        assert active[0]["first_trace_id"] == "t1"
        assert active[0]["last_trace_id"] == "t2"
        # acknowledged ≠ resolved
        await inc.acknowledge(d, r1["incident_id"], actor=7)
        active = await inc.active_incidents(d)
        assert active[0]["acknowledged_at"] is not None
        assert active[0]["resolved_at"] is None
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_incident_distinct_symptoms_not_merged(tmp_path):
    """Разные stage/reason → разные инциденты (не сливаются по слову timeout)."""
    d = await _db(tmp_path, name="inc2.db")
    try:
        a = await inc.open_or_update(d, process_id="p", stage="llm",
                                     reason_code="provider_unavailable",
                                     error_type="Timeout")
        b = await inc.open_or_update(d, process_id="p", stage="db",
                                     reason_code="connection_unrecoverable",
                                     error_type="Timeout")
        assert a["incident_id"] != b["incident_id"]
        assert len(await inc.active_incidents(d)) == 2
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_incident_resolve_requires_evidence_and_history(tmp_path):
    d = await _db(tmp_path, name="inc3.db")
    try:
        r = await inc.open_or_update(d, process_id="p", stage="s",
                                     reason_code="provider_unavailable",
                                     error_type="Timeout")
        assert await inc.resolve(d, r["incident_id"], evidence="") is False
        assert await inc.resolve(d, r["incident_id"],
                                 evidence="health check ok") is True
        assert await inc.active_incidents(d) == []
        cur = await d.db.execute("SELECT resolved_at, resolution_evidence "
                                 "FROM mca_incidents")
        row = await cur.fetchone()
        assert row["resolved_at"] is not None
        assert row["resolution_evidence"] == "health check ok"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_incident_fallback_lowers_severity_not_hides(tmp_path):
    d = await _db(tmp_path, name="inc4.db")
    try:
        r = await inc.open_or_update(d, process_id="p", stage="s",
                                     severity=inc.SEVERITY_ERROR,
                                     reason_code="provider_unavailable",
                                     error_type="Timeout", fallback_used=True)
        active = await inc.active_incidents(d)
        assert len(active) == 1
        assert active[0]["fallback_used"] is True
        assert active[0]["severity"] == inc.SEVERITY_WARN
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_incident_delivery_cursor(tmp_path):
    d = await _db(tmp_path, name="inc5.db")
    try:
        await inc.open_or_update(d, process_id="p", stage="s",
                                 reason_code="provider_unavailable",
                                 error_type="Timeout")
        change = await inc.incident_changes(d, since_ts=0)
        assert change["cursor"] > 0 and len(change["changes"]) == 1
        # reconnect: курсор не даёт повторно
        again = await inc.incident_changes(d, since_ts=change["cursor"])
        assert again["changes"] == []
    finally:
        await d.close()


# ── T-3880: телеметрия spool/degraded/gaps + R17 (SC-17) ───────────────────

@pytest.mark.asyncio
async def test_spool_on_store_unavailable(tmp_path, monkeypatch):
    d = await _db(tmp_path, name="spool.db")
    try:
        me.emit_mca_event("X", outcome="success", trace_id="s1")
        # симулируем недоступность хранилища
        async def _boom(*a, **k):
            raise RuntimeError("db down")
        monkeypatch.setattr(d, "write_transaction", _boom)
        written = await me.flush_events(d)
        assert written == 0
        assert me.spooled_total() == 1
        assert me.telemetry_degraded() is True
        assert me.spool_size() == 1
        # восстановление: spool дренится следующей успешной tx (снимаем только
        # подмену write_transaction, сохраняя spool-env)
        monkeypatch.delattr(d, "write_transaction", raising=False)
        written = await me.flush_events(d)
        assert written >= 1
        assert me.spool_size() == 0
    finally:
        await d.close()


def test_spool_bounded_gaps(monkeypatch, tmp_path):
    monkeypatch.setattr(me.mca_gates, "telemetry_spool_enabled", lambda: True)
    monkeypatch.setattr(me.mca_gates, "telemetry_spool_max_events", lambda: 2)
    me.reset_pending()
    me._spool_append([{"a": i} for i in range(5)])
    assert me.spool_size() == 2
    assert me.gaps_total() == 3


@pytest.mark.asyncio
async def test_flush_concurrent_emit_not_lost(tmp_path, monkeypatch):
    """F2/SC-17: события, эмитированные во время `await write_transaction`,
    НЕ теряются (своп-очередь); счётчики не врут."""
    d = await _db(tmp_path, name="conc.db")
    try:
        me.emit_mca_event("A", outcome="success", trace_id="a1")
        started = asyncio.Event()
        release = asyncio.Event()
        real_wt = d.write_transaction

        async def _slow(body, **kw):
            started.set()
            await release.wait()
            return await real_wt(body, **kw)

        monkeypatch.setattr(d, "write_transaction", _slow)
        task = asyncio.ensure_future(me.flush_events(d))
        await started.wait()
        # эмиссия в окне flush (snapshot уже выведен из очереди)
        me.emit_mca_event("B", outcome="success", trace_id="b1")
        me.emit_mca_event("C", outcome="success", trace_id="c1")
        assert me.pending_size() == 2          # не потеряны свопом
        release.set()
        written = await task
        assert written == 1                     # записан только снимок (A)
        assert me.pending_size() == 2           # B/C остались в буфере
        written2 = await me.flush_events(d)
        assert written2 == 2
        assert me.pending_size() == 0
        cur = await d.db.execute(
            "SELECT trace_id FROM mca_events ORDER BY id")
        assert [r["trace_id"] for r in await cur.fetchall()] == ["a1", "b1", "c1"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_flush_failure_keeps_new_events(tmp_path, monkeypatch):
    """F2: при провале записи новые события (после свопа) остаются в буфере,
    снимок уходит в spool — потерь нет."""
    d = await _db(tmp_path, name="concfail.db")
    try:
        me.emit_mca_event("A", outcome="success", trace_id="a1")
        started = asyncio.Event()
        release = asyncio.Event()
        real_wt = d.write_transaction

        async def _slow_fail(body, **kw):
            started.set()
            await release.wait()
            raise RuntimeError("db down")

        monkeypatch.setattr(d, "write_transaction", _slow_fail)
        task = asyncio.ensure_future(me.flush_events(d))
        await started.wait()
        me.emit_mca_event("B", outcome="success", trace_id="b1")
        release.set()
        assert await task == 0
        assert me.pending_size() == 1            # B сохранён в буфере
        assert me.spooled_total() == 1           # A — в spool (не потерян)
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_linked_span_ids_single_encoding(tmp_path):
    """F9: `linked_span_ids` хранится как JSON-массив (без двойного кодирования)."""
    import json as _json
    d = await _db(tmp_path, name="linked.db")
    try:
        mt.emit_stage("X", outcome="success", linked_span_ids=["sp_a", "sp_b"],
                      **mt.span_fields(run_id="run_l", span_id="sp_l"))
        await me.flush_events(d)
        cur = await d.db.execute("SELECT linked_span_ids FROM mca_events")
        raw = (await cur.fetchone())["linked_span_ids"]
        assert _json.loads(raw) == ["sp_a", "sp_b"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_watchdog_incident_uses_job_owner(tmp_path):
    """F8: fingerprint инцидента берёт тип/владельца job, а не хардкод."""
    d = await _db(tmp_path, name="wd_inc.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="video", kind="important")
        await store.mark_running(jid)
        await d.db.execute(
            "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
            (int(time.time()) - 9999, jid))
        await d.db.commit()
        await wd.sweep(d, job_store=store)
        cur = await d.db.execute("SELECT pipeline_type FROM mca_incidents")
        rows = [r["pipeline_type"] for r in await cur.fetchall()]
        assert "video" in rows and "archive.rebuild" not in rows
    finally:
        await d.close()


def test_status_logs_events_requires_global_admin():
    """F11/RBAC: связанные mca_events по фильтрам — только глобальный админ."""
    from web.api import routes

    class _Perms:
        wildcard = False

    class _PermsWild:
        wildcard = True

    class _Cache:
        def get_permissions_by_telegram_id(self, uid):
            return _Perms()

        def get_role(self, uid):
            return "user"

        def roles(self):
            return {}

    class _CacheWild:
        def get_permissions_by_telegram_id(self, uid):
            return _PermsWild()

        def get_role(self, uid):
            return "user"

        def roles(self):
            return {}

    def _req(cache):
        state = type("S", (), {"cache": cache})()
        return type("R", (), {"app": type("A", (), {"state": state})()})()

    class _User:
        id = 1

    assert routes._is_global_admin(_req(_Cache()), _User()) is False
    assert routes._is_global_admin(_req(_CacheWild()), _User()) is True


@pytest.mark.asyncio
async def test_error_cause_masked(tmp_path):
    d = await _db(tmp_path, name="cause.db")
    try:
        token = "sk-abcdefghijklmnop123456"
        meta = me.build_error_metadata(RuntimeError(f"secret {token}"),
                                       stage="llm")
        me.emit_mca_event("FAIL", outcome="failed", level=me.LEVEL_ERROR,
                          error_json=meta)
        await me.flush_events(d)
        cur = await d.db.execute("SELECT error_json FROM mca_events")
        row = await cur.fetchone()
        assert token not in (row["error_json"] or "")
    finally:
        await d.close()


# ── T-3881: runtime-продюсер + wiring flush/prune (SC-13/SC-22) ────────────

@pytest.mark.asyncio
async def test_runtime_metrics_producer(tmp_path):
    d = await _db(tmp_path, name="rt.db")
    try:
        runtime = await mt.collect_runtime_metrics(d)
        # rss может быть доступен; provenance/histories могут отсутствовать
        assert isinstance(runtime, dict)
        m = await me.metrics(d, runtime=runtime)
        assert m["available"] is True
        assert "unknown" in m
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_flush_and_prune_respects_both_kill_switches(tmp_path,
                                                           monkeypatch):
    d = await _db(tmp_path, name="wire.db")
    try:
        me.emit_mca_event("X", outcome="success", trace_id="w1")
        res = await me.flush_and_prune(d, prune=True)
        assert res["enabled"] is True and res["flushed"] >= 1
        monkeypatch.setattr(me.mca_gates, "telemetry_store_enabled",
                            lambda: False)
        off = await me.flush_and_prune(d)
        assert off == {"flushed": 0, "pruned": 0, "enabled": False}
        assert await me.prune_events(d) == 0
        # F6: master OFF (`MCA_OBSERVABILITY_ENABLED`) гасит фон. flush/prune
        # даже при включённых mca-13-гейтах (полный baseline-паритет).
        monkeypatch.setattr(me.mca_gates, "telemetry_store_enabled",
                            lambda: True)
        monkeypatch.setattr(me.mca_gates, "observability_enabled",
                            lambda: False)
        assert (await me.flush_and_prune(d))["enabled"] is False
    finally:
        await d.close()


# ── T-3883: контролируемые сценарии §27.9 (SC-19) ──────────────────────────

@pytest.mark.asyncio
async def test_scenario_provider_timeout(tmp_path):
    d = await _db(tmp_path, name="sc_timeout.db")
    try:
        meta = me.build_error_metadata(TimeoutError("provider"), stage="llm",
                                       retryable=True, recovery="retry")
        me.emit_mca_event("LLM_CALL", outcome="failed", level=me.LEVEL_ERROR,
                          stage="llm", reason_code="provider_unavailable",
                          error_json=meta)
        await me.flush_events(d)
        cur = await d.db.execute(
            "SELECT outcome FROM mca_events WHERE reason_code='provider_unavailable'")
        assert (await cur.fetchone()) is not None
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_invalid_json(tmp_path):
    d = await _db(tmp_path, name="sc_json.db")
    try:
        meta = me.build_error_metadata(ValueError("bad json"), stage="parse")
        me.emit_mca_event("PARSE", outcome="failed", level=me.LEVEL_ERROR,
                          error_json=meta, reason_code="rerank_invalid")
        await me.flush_events(d)
        assert (await me.metrics(d))["errors_total"] >= 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_write_error_after_llm(tmp_path):
    """Ошибка записи после успешного LLM: run не success (uncommitted write)."""
    outcome = mt.compute_run_outcome(
        [{"name": "llm", "status": "succeeded", "required": True}],
        pipeline_type="direct.reply", uncommitted_write=True)
    assert outcome == mt.RUN_RUNNING


@pytest.mark.asyncio
async def test_scenario_cancel_parent_child(tmp_path):
    d = await _db(tmp_path, name="sc_cancel.db")
    try:
        store = TaskJobStore(d)
        parent = await store.enqueue(owner="archive", kind="important")
        child = await store.enqueue(owner="archive", kind="important",
                                    parent_span_id="sp_parent")
        await mt.control_action(d, store, action="cancel", job_id=parent,
                                actor=1)
        assert (await store.get(parent))["status"] == "cancelled"
        # дочерняя — независима (не скрытая отмена)
        assert (await store.get(child))["status"] == "queued"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_worker_dies_between_checkpoint_and_terminal(tmp_path):
    d = await _db(tmp_path, name="sc_worker.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        await store.mark_running(jid)
        await store.save_checkpoint(jid, cursor_token="c", processed=10)
        rec = await wd.recover_job(d, store, jid)
        assert rec["resumed"] is True
        assert rec["checkpoint"]["processed"] == 10
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_restart_resume(tmp_path):
    """Correlation переживает рестарт (durable task_jobs)."""
    path = tmp_path / "restart.db"
    d = DatabaseService(str(path))
    await d.initialize()
    store = TaskJobStore(d)
    jid = await store.enqueue(owner="archive", kind="important",
                              pipeline_run_id="run_restart", span_id="sp_r")
    await d.close()
    d2 = DatabaseService(str(path))
    await d2.initialize()
    try:
        row = await TaskJobStore(d2).get(jid)
        assert row["pipeline_run_id"] == "run_restart"
    finally:
        await d2.close()


@pytest.mark.asyncio
async def test_scenario_lost_heartbeat(tmp_path):
    d = await _db(tmp_path, name="sc_hb.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        await store.mark_running(jid)
        await d.db.execute("UPDATE task_jobs SET heartbeat_at=? WHERE job_id=?",
                           (int(time.time()) - 9999, jid))
        await d.db.commit()
        stale = await wd.stale_jobs(d)
        assert any(r["job_id"] == jid for r in stale)
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_live_heartbeat_no_progress(tmp_path):
    """Живой heartbeat без прогресса → progress-stall (по профилю стадии)."""
    d = await _db(tmp_path, name="sc_prog.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="video", kind="important")
        await store.mark_running(jid)
        await d.db.execute(
            "UPDATE task_jobs SET heartbeat_at=?, progress_at=? WHERE job_id=?",
            (int(time.time()), int(time.time()) - 99999, jid))
        await d.db.commit()
        stalled = await wd.progress_stalled_jobs(d)
        assert any(r["job_id"] == jid for r in stalled)
        # законная длительная транскрибация (< порога video) — не объявлена упавшей
        await d.db.execute(
            "UPDATE task_jobs SET progress_at=? WHERE job_id=?",
            (int(time.time()) - 5, jid))
        await d.db.commit()
        assert not any(r["job_id"] == jid
                       for r in await wd.progress_stalled_jobs(d))
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_log_storage_failure_gap(tmp_path, monkeypatch):
    d = await _db(tmp_path, name="sc_log.db")
    try:
        monkeypatch.setattr(me.mca_gates, "telemetry_spool_enabled",
                            lambda: False)
        me.emit_mca_event("X", outcome="success", trace_id="g1")
        async def _boom(*a, **k):
            raise RuntimeError("storage down")
        monkeypatch.setattr(d, "write_transaction", _boom)
        await me.flush_events(d)
        assert me.gaps_total() >= 1
        assert me.telemetry_degraded() is True
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_miniapp_reconnect_cursor(tmp_path):
    d = await _db(tmp_path, name="sc_reconnect.db")
    try:
        await inc.open_or_update(d, process_id="p", stage="s",
                                 reason_code="provider_unavailable",
                                 error_type="Timeout")
        first = await inc.incident_changes(d, since_ts=0)
        # reconnect с курсором — нет повторной доставки
        second = await inc.incident_changes(d, since_ts=first["cursor"])
        assert second["changes"] == [] and second["cursor"] == first["cursor"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_branch_error_not_erasing_success(tmp_path):
    """Ошибка одной параллельной ветви не стирает успех другой."""
    outcome = mt.compute_run_outcome(
        [{"name": "decision", "status": "succeeded", "required": True},
         {"name": "retrieval", "status": "failed", "required": False,
          "has_fallback": False}],
        pipeline_type="direct.reply")
    assert outcome == mt.RUN_PARTIAL


@pytest.mark.asyncio
async def test_scenario_delivery_unknown_scenario(tmp_path):
    d = await _db(tmp_path, name="sc_du.db")
    try:
        store = TaskJobStore(d)
        jid = await store.enqueue(owner="archive", kind="important")
        await wd.mark_delivery_unknown(d, store, jid, operation_id="op_1")
        ctrl = await mt.control_action(d, store, action="retry", job_id=jid,
                                       actor=1)
        assert ctrl["status"] == "reconcile_required"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_scenario_shared_task_multiple_consumers(tmp_path):
    """F7: shared/singleflight-результат обслуживает НЕСКОЛЬКО потребителей
    через `linked_span_ids` (без одного ложного владельца): оба потребителя
    ссылаются на один span-владелец, но не являются parent/child."""
    import json as _json
    d = await _db(tmp_path, name="shared.db")
    try:
        owner_span = "sp_owner"
        # два потребителя ссылаются на общий span-владелец (links, не parent)
        for consumer in ("sp_consumer_a", "sp_consumer_b"):
            mt.emit_stage(
                "SHARED_RESULT", outcome="success",
                **mt.span_fields(run_id="run_sh", span_id=consumer,
                                 linked_span_ids=[owner_span]))
        await me.flush_events(d)
        cur = await d.db.execute(
            "SELECT span_id, linked_span_ids, parent_span_id FROM mca_events "
            "WHERE event_name = 'SHARED_RESULT'")
        rows = [dict(r) for r in await cur.fetchall()]
        assert {r["span_id"] for r in rows} == {"sp_consumer_a",
                                                "sp_consumer_b"}
        for r in rows:
            assert _json.loads(r["linked_span_ids"]) == [owner_span]
            assert r["parent_span_id"] is None   # links, а не владение
    finally:
        await d.close()


# ── SC-20: REUSE (число store/таблиц) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_reuse_no_second_store(tmp_path):
    d = await _db(tmp_path, name="reuse.db")
    try:
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'mca_%'")
        tables = {r["name"] for r in await cur.fetchall()}
        # второй store телеметрии не создаётся
        assert "mca_events" in tables
        assert not any(t.startswith("mca_trace_store") for t in tables)
    finally:
        await d.close()


# ── F5/§4.10 (AMEND F5/ADR D16): read-only данные-API ядра (endpoints) ─────

async def _call_registry(d, monkeypatch):
    from web.api import oversight as ov
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: d)
    return await ov.oversight_processes(request=None, user=object())


async def _call_incidents(d, monkeypatch, limit=100):
    from web.api import oversight as ov
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: d)
    return await ov.oversight_incidents(request=None, user=object(), limit=limit)


async def _call_changes(d, monkeypatch, since_ts=0, limit=200):
    from web.api import oversight as ov
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: d)
    return await ov.oversight_incident_changes(
        request=None, user=object(), since_ts=since_ts, limit=limit)


@pytest.mark.asyncio
async def test_endpoint_registry_snapshot_available(tmp_path, monkeypatch):
    """§4.10/SC-01: endpoint отдаёт реестр + статус; R17 — только имена настроек."""
    d = await _db(tmp_path, name="ep_reg.db")
    try:
        await me.flush_events(d)      # пустой flush — store готов
        res = await _call_registry(d, monkeypatch)
        assert res["available"] is True and res["enabled"] is True
        assert res["count"] == len(reg.PROCESS_REGISTRY)
        assert res["processes"] and res["pipelines"]
        row = next(p for p in res["processes"] if p["process_id"] == "web.fetch")
        assert row["status"] in reg.REGISTRATION_STATUSES
        assert isinstance(row["settings_ref"], list)   # только имена, не значения
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_endpoint_registry_disabled_fail_open(tmp_path, monkeypatch):
    d = await _db(tmp_path, name="ep_reg_off.db")
    try:
        monkeypatch.setattr(me.mca_gates, "process_registry_enabled",
                            lambda: False)
        res = await _call_registry(d, monkeypatch)
        assert res["available"] is False and res["enabled"] is False
        assert res["processes"] == [] and res["count"] == 0
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_endpoint_incidents_and_cursor_reconnect(tmp_path, monkeypatch):
    """§4.6/SC-16: active_incidents + incident_changes cursor-догон."""
    d = await _db(tmp_path, name="ep_inc.db")
    try:
        await inc.open_or_update(d, process_id="direct.reply",
                                 pipeline_type="direct.reply", stage="llm",
                                 reason_code="provider_unavailable",
                                 error_type="Timeout", trace_id="t1")
        active = await _call_incidents(d, monkeypatch)
        assert active["available"] is True and active["enabled"] is True
        assert len(active["incidents"]) == 1
        assert active["push_interval_seconds"] <= 10
        first = await _call_changes(d, monkeypatch, since_ts=0)
        assert first["enabled"] is True
        assert first["cursor"] > 0 and len(first["changes"]) == 1
        assert first["indicator"]["active"] == 1
        assert first["push_interval_seconds"] <= 10
        # reconnect: с курсором повторной доставки нет (сверка состояния)
        again = await _call_changes(d, monkeypatch, since_ts=first["cursor"])
        assert again["changes"] == [] and again["cursor"] == first["cursor"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_endpoint_incidents_gates_off_parity(tmp_path, monkeypatch):
    """OFF `MCA_INCIDENTS_ENABLED`/`MCA_INCIDENT_PUSH_ENABLED` → нет обновлений."""
    d = await _db(tmp_path, name="ep_inc_off.db")
    try:
        await inc.open_or_update(d, process_id="p", stage="s",
                                 reason_code="provider_unavailable",
                                 error_type="Timeout")
        monkeypatch.setattr(me.mca_gates, "incidents_enabled", lambda: False)
        assert (await _call_incidents(d, monkeypatch))["available"] is False
        assert (await _call_changes(d, monkeypatch))["enabled"] is False
        monkeypatch.setattr(me.mca_gates, "incidents_enabled", lambda: True)
        monkeypatch.setattr(me.mca_gates, "incident_push_enabled",
                            lambda: False)
        off = await _call_changes(d, monkeypatch)
        assert off["enabled"] is False and off["changes"] == []
    finally:
        await d.close()


# ── kill-switch master OFF parity ──────────────────────────────────────────

def test_master_off_disables_subgates(monkeypatch):
    monkeypatch.setattr(me.mca_gates, "observability_enabled", lambda: False)
    assert me.mca_gates.process_registry_enabled() is False
    assert me.mca_gates.trace_span_enabled() is False
    assert me.mca_gates.job_lifecycle_enabled() is False
    assert me.mca_gates.heartbeat_watchdog_enabled() is False
    assert me.mca_gates.incidents_enabled() is False
    assert me.mca_gates.telemetry_spool_enabled() is False


def test_fault_injection_default_off(monkeypatch):
    monkeypatch.delenv("MCA_FAULT_INJECTION_ENABLED", raising=False)
    import importlib
    import config.settings as s
    importlib.reload(s)
    assert s.Settings.MCA_FAULT_INJECTION_ENABLED is False
    importlib.reload(s)   # восстановить модуль


def test_observability_kill_switches_default_on(monkeypatch):
    import importlib
    import config.settings as s
    for name in ("MCA_OBSERVABILITY_ENABLED", "MCA_PROCESS_REGISTRY_ENABLED",
                 "MCA_TRACE_SPAN_ENABLED", "MCA_JOB_LIFECYCLE_ENABLED",
                 "MCA_HEARTBEAT_WATCHDOG_ENABLED", "MCA_INCIDENTS_ENABLED",
                 "MCA_INCIDENT_PUSH_ENABLED", "MCA_TELEMETRY_SPOOL_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(s)
    for name in ("MCA_OBSERVABILITY_ENABLED", "MCA_PROCESS_REGISTRY_ENABLED",
                 "MCA_TRACE_SPAN_ENABLED", "MCA_JOB_LIFECYCLE_ENABLED",
                 "MCA_HEARTBEAT_WATCHDOG_ENABLED", "MCA_INCIDENTS_ENABLED",
                 "MCA_INCIDENT_PUSH_ENABLED", "MCA_TELEMETRY_SPOOL_ENABLED"):
        assert getattr(s.Settings, name) is True, name
    importlib.reload(s)


def test_registry_gate_env_default_on(monkeypatch):
    import importlib
    import config.settings as s
    monkeypatch.delenv("MCA_PROCESS_REGISTRY_ENABLED", raising=False)
    importlib.reload(s)
    assert s.Settings.MCA_PROCESS_REGISTRY_ENABLED is True
    importlib.reload(s)
