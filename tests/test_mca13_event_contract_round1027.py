"""MCA Wave 0 (`mca-13-event-contract`) — контракт события §17 (v15).

Покрытие:
  * T-3767: структурированный JSON event §17.1 (поля, R17-safe, поля по типам);
  * T-3768: start + терминальный outcome; bounded буфер/`interrupted`;
  * T-3769: словарь reason_code §17.2 (не свести к skip; расширяемый);
  * T-3770: error metadata + агрегация (счётчик/первое-последнее/первый trace);
  * T-3771: маскирование R17;
  * T-3772: ретенция 90d + bounded буфер;
  * T-3773: метрики (UNKNOWN ≠ 0) + фильтры;
  * T-3775: kill-switch OFF-паритет.
"""
import asyncio
import time

import pytest

from services.database import DatabaseService
from services import mca_events as me
import services.mca_gates as gates


@pytest.fixture(autouse=True)
def _reset_buffer():
    me.reset_pending()
    yield
    me.reset_pending()


def _patch_settings(monkeypatch, **kw):
    for key, value in kw.items():
        monkeypatch.setattr(gates, key, lambda v=value: v, raising=False)


async def _db(tmp_path, name="mca13.db"):
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ── T-3767: схема события ──────────────────────────────────────────────────

def test_build_event_contract_fields():
    """SC-01: обязательные поля присутствуют; R17-safe."""
    ev = me.build_event(
        "SUMMARY_RUN", outcome=me.OUTCOME_SUCCESS, level=me.LEVEL_INFO,
        trace_id="run-1", chat_id=-100, component="summary", stage="l2_writer",
        reason_code="no_new_contribution", duration_ms=120, attempt=1,
        entity_ids=["7", "8"])
    assert ev["schema_version"] == me.SCHEMA_VERSION
    assert ev["event_name"] == "SUMMARY_RUN"
    assert ev["outcome"] == me.OUTCOME_SUCCESS
    assert ev["trace_id"] == "run-1"
    assert ev["reason_code"] == "no_new_contribution"
    assert ev["duration_ms"] == 120
    assert isinstance(ev["ts"], int)


def test_build_event_drops_unsafe_fields():
    """SC-01: небезопасные ключи/значения отбрасываются."""
    ev = me.build_event("X", outcome=me.OUTCOME_SUCCESS,
                        secret_token="sk-abcdef123456", note="some text here",
                        untrusted="drop me")
    assert "secret_token" not in ev
    assert "note" not in ev
    assert "untrusted" not in ev


def test_build_event_rejects_bad_outcome():
    assert me.build_event("X", outcome="whatever") is None
    assert me.build_event("", outcome=me.OUTCOME_SUCCESS) is None


def test_per_type_fields_present():
    """SC-05: поля по типам (retrieval) переносятся, CoT не запрашивается."""
    ev = me.build_event(
        "RETRIEVAL", outcome=me.OUTCOME_SKIPPED, component="retrieval",
        reason_code="no_relevant_memory", entity_ids=["11"],
        source_ref_json={"kind": "memory", "id": 11})
    assert ev["component"] == "retrieval"
    assert "source_ref_json" in ev
    assert "chain_of_thought" not in ev


def test_per_type_fields_decision_context_archive_dream():
    """SC-05/L-MCA13-3: решение/контекст/архив/сон несут свои поля §17.1."""
    cases = [
        ("DECISION", dict(component="decision", stage="decide",
                          reason_code="random_fallback", entity_ids=["1"],
                          usage_json={"tokens": 5})),
        ("CONTEXT", dict(component="context", stage="l1_builder",
                         entity_ids=["2"], duration_ms=12)),
        ("ARCHIVE", dict(component="archive",
                         reason_code="archive_checkpoint_saved",
                         source_ref_json={"cursor": "c1", "processed": 42})),
        ("DREAM", dict(component="dream", entity_ids=["3"], attempt=1)),
    ]
    for name, extra in cases:
        ev = me.build_event(name, outcome=me.OUTCOME_SUCCESS, **extra)
        assert ev is not None and ev["event_name"] == name
        assert "chain_of_thought" not in ev
        for key in extra:
            assert key in ev


# ── T-3769: reason_code ────────────────────────────────────────────────────

def test_reason_dictionary_has_minimum():
    """SC-06: базовый минимум §17.2 присутствует."""
    for code in ("no_relevant_memory", "already_answered", "queue_full",
                 "provider_unavailable", "archive_checkpoint_saved"):
        assert code in me.REASON_CODES


def test_unknown_reason_code_dropped_not_skip():
    """SC-06: неизвестный код не подменяется `skip`."""
    ev = me.build_event("X", outcome=me.OUTCOME_SKIPPED,
                        reason_code="totally_unknown_code")
    assert "reason_code" not in ev


# ── T-3768/T-3775: эмиссия + kill-switch ───────────────────────────────────

def test_emit_start_and_terminal():
    """SC-03: start и терминальный outcome эмитятся (лог + буфер)."""
    s = me.emit_mca_event("RUN", outcome=me.OUTCOME_START, trace_id="r1")
    t = me.emit_mca_event("RUN", outcome=me.OUTCOME_SUCCESS, trace_id="r1")
    assert s["outcome"] == me.OUTCOME_START
    assert t["outcome"] == me.OUTCOME_SUCCESS
    # только терминальное в буфере
    assert me.pending_size() == 1


def test_emit_off_parity_contract(monkeypatch):
    """SC-16/T-3775: `MCA_EVENT_CONTRACT_ENABLED=false` → no-op (паритет)."""
    _patch_settings(monkeypatch, event_contract_enabled=False)
    assert me.emit_mca_event("X", outcome=me.OUTCOME_SUCCESS) is None
    assert me.pending_size() == 0


def test_emit_never_raises():
    """Fail-open: некорректный вход не бросает."""
    assert me.emit_mca_event(None, outcome="bad") is None
    assert me.emit_mca_event("X", outcome=me.OUTCOME_SUCCESS, chat_id=object()) \
        is not None


def test_emit_log_reflects_level(caplog):
    """L-MCA13-2: WARN/ERROR логируются соответствующим уровнем, не INFO."""
    import logging

    with caplog.at_level(logging.WARNING, logger="services.mca_events"):
        me.emit_mca_event("X", outcome=me.OUTCOME_FAILED,
                          level=me.LEVEL_ERROR)
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_event_kill_switches_env_default_on(monkeypatch):
    """L-MCA13-4: env-чтение `Settings.MCA_EVENT_*`; default ON."""
    import importlib
    import config.settings as s

    monkeypatch.delenv("MCA_EVENT_CONTRACT_ENABLED", raising=False)
    monkeypatch.delenv("MCA_TELEMETRY_STORE_ENABLED", raising=False)
    importlib.reload(s)
    assert s.Settings.MCA_EVENT_CONTRACT_ENABLED is True
    assert s.Settings.MCA_TELEMETRY_STORE_ENABLED is True


# ── T-3772: bounded буфер + durable flush + ретенция ───────────────────────

@pytest.mark.asyncio
async def test_flush_persists_and_idempotent_buffer(tmp_path):
    """SC-12/SC-03: flush пишет терминальные в `mca_events`, буфер очищается."""
    d = await _db(tmp_path)
    try:
        me.emit_mca_event("RUN", outcome=me.OUTCOME_SUCCESS, trace_id="r2",
                         component="summary")
        me.emit_mca_event("RUN", outcome=me.OUTCOME_SKIPPED, trace_id="r2",
                         reason_code="already_answered", component="summary")
        written = await me.flush_events(d)
        assert written == 2
        assert me.pending_size() == 0
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM mca_events")
        assert (await cur.fetchone())["c"] == 2
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_flush_off_store_parity(tmp_path, monkeypatch):
    """SC-16: `MCA_TELEMETRY_STORE_ENABLED=false` → без durable-записи."""
    _patch_settings(monkeypatch, telemetry_store_enabled=False)
    d = await _db(tmp_path)
    try:
        me.emit_mca_event("RUN", outcome=me.OUTCOME_SUCCESS, trace_id="r3")
        # терминальные не буферизуются при OFF-store
        assert me.pending_size() == 0
        assert await me.flush_events(d) == 0
    finally:
        await d.close()


def test_buffer_bounded_with_visible_gap():
    """SC-12/A53: буфер bounded; переполнение → видимый dropped-счётчик."""
    for i in range(me._PENDING_MAX + 5):
        me.emit_mca_event("X", outcome=me.OUTCOME_SUCCESS, trace_id=f"r{i}")
    assert me.pending_size() == me._PENDING_MAX
    assert me.dropped_total() == 5


@pytest.mark.asyncio
async def test_retention_prune(tmp_path):
    """SC-11: старые терминальные удаляются; protected-компоненты остаются."""
    d = await _db(tmp_path)
    try:
        old = int(time.time()) - 100 * 86400
        await d.db.execute(
            "INSERT INTO mca_events (ts, level, event_name, outcome, "
            "component) VALUES (?,?,?,?,?)",
            (old, "INFO", "OLD", "success", "summary"))
        await d.db.execute(
            "INSERT INTO mca_events (ts, level, event_name, outcome, "
            "component) VALUES (?,?,?,?,?)",
            (old, "INFO", "PROT", "success", "memory_manual"))
        await d.db.commit()
        removed = await me.prune_events(d)
        assert removed == 1
        cur = await d.db.execute("SELECT event_name FROM mca_events")
        assert [r["event_name"] for r in await cur.fetchall()] == ["PROT"]
    finally:
        await d.close()


# ── T-3770: ошибки/агрегация ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_aggregate_keeps_count_and_first_trace(tmp_path):
    """SC-08/SC-09: агрегат даёт счётчик/первое-последнее/первый trace."""
    d = await _db(tmp_path)
    try:
        for i in range(3):
            err = me.build_error_metadata(ValueError("boom"), stage="l2",
                                          retryable=False, recovery="skip")
            me.emit_mca_event(
                "L2_FAILED", outcome=me.OUTCOME_FAILED, level=me.LEVEL_ERROR,
                trace_id="trace-1", component="summary", error_json=err)
        await me.flush_events(d)
        cur = await d.db.execute(
            "SELECT count, first_trace_id FROM mca_event_aggregates")
        row = await cur.fetchone()
        assert row["count"] == 3
        assert row["first_trace_id"] == "trace-1"
        # факт продолжения сбоя виден (count > 1)
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM mca_events")
        assert (await cur.fetchone())["c"] == 3
    finally:
        await d.close()


def test_error_metadata_has_cause_and_masked_stack():
    """SC-08: тип/cause/стадия/retryability/masked stack."""
    try:
        try:
            raise KeyError("inner")
        except KeyError as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as exc:
        meta = me.build_error_metadata(exc, stage="stage1", retryable=True,
                                       recovery="retry")
    assert meta["type"] == "RuntimeError"
    assert meta["cause"] == "KeyError"
    assert meta["retryable"] is True
    assert "stack" in meta


# ── T-3771: маскирование ───────────────────────────────────────────────────

def test_masking_of_secrets_in_event_and_log(caplog):
    """B-MCA13-1/SC-10: секретоподобное значение в строковом (`component`) и
    JSON-поле (`source_ref_json`) маскируется ДО лога (caplog) и события."""
    import logging

    token = "sk-abcdefghijklmnop123456"
    with caplog.at_level(logging.INFO, logger="services.mca_events"):
        ev = me.emit_mca_event(
            "X", outcome=me.OUTCOME_SUCCESS, component=token,
            source_ref_json={"note": f"token {token} here"})
    assert ev is not None
    assert token not in ev["component"] and "***" in ev["component"]
    assert token not in ev["source_ref_json"]
    # лог-строка (структурный лог-канал) не содержит сырой секрет
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert token not in joined
    assert "***" in joined


@pytest.mark.asyncio
async def test_masking_persisted_durable_mca_events(tmp_path):
    """B-MCA13-1/SC-10: в durable `mca_events` секрет не попадает ни в
    строковом, ни в JSON-поле (маскирование до записи в стор)."""
    d = await _db(tmp_path, name="mask.db")
    try:
        token = "sk-abcdefghijklmnop123456"
        me.emit_mca_event("X", outcome=me.OUTCOME_SUCCESS, component=token,
                          source_ref_json={"note": f"token {token} here"})
        written = await me.flush_events(d)
        assert written == 1
        cur = await d.db.execute(
            "SELECT component, source_ref_json FROM mca_events")
        row = await cur.fetchone()
        assert token not in (row["component"] or "")
        assert token not in (row["source_ref_json"] or "")
        assert "***" in row["component"]
    finally:
        await d.close()


# ── T-3773: метрики/фильтры ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_unknown_not_zero_when_unavailable():
    """SC-13: недоступная телеметрия → `available=False`, не 0/здоровье."""
    m = await me.metrics(None)
    assert m["available"] is False
    assert m["events_total"] is None
    assert m["degraded_share"] is None
    assert len(m["metrics"]) == len(me._METRIC_GROUPS)
    assert all(not g["available"] for g in m["metrics"].values())


@pytest.mark.asyncio
async def test_metrics_and_filters(tmp_path):
    d = await _db(tmp_path)
    try:
        me.emit_mca_event("A", outcome=me.OUTCOME_SUCCESS, trace_id="t1",
                          component="summary")
        me.emit_mca_event("B", outcome=me.OUTCOME_FAILED, level=me.LEVEL_ERROR,
                          trace_id="t2", component="retrieval")
        await me.flush_events(d)
        m = await me.metrics(d)
        assert m["events_total"] == 2
        assert m["errors_total"] == 1
        rows = await me.query_events(d, component="summary")
        assert len(rows) == 1 and rows[0]["event_name"] == "A"
        rows = await me.query_events(d, trace_id="t2")
        assert len(rows) == 1 and rows[0]["event_name"] == "B"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_metrics_covers_17_4_groups_with_unknown(tmp_path):
    """B-MCA13-2/SC-13: единый адаптер отдаёт все группы §17.4; источники без
    продюсера — UNKNOWN (`available=False`, значения `None`), не 0/здоровье."""
    d = await _db(tmp_path, name="metrics_groups.db")
    try:
        m = await me.metrics(d)
        assert m["available"] is True
        assert m["events_total"] == 0
        assert m["degraded_share"] is None      # нет событий → UNKNOWN, не 0
        groups = m["metrics"]
        assert set(groups) == set(me._METRIC_GROUPS)
        assert groups["tasks"]["available"] is True
        assert groups["tasks"]["pending"] == 0  # реальный ноль очереди
        assert groups["lock"]["available"] is True
        assert groups["degradations"]["available"] is True
        for name in ("cache", "provenance", "memory", "downloads", "runtime"):
            assert groups[name]["available"] is False
            assert name in m["unknown"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_metrics_computes_real_groups_from_store(tmp_path):
    """B-MCA13-2/SC-13: реальные группы считаются из `mca_events`/`task_jobs`;
    живые источники (cache/RSS/provenance/downloads) — из runtime-контура."""
    from services.task_supervisor import TaskJobStore

    d = await _db(tmp_path, name="metrics_real.db")
    try:
        me.emit_mca_event("LLM_CALL", outcome=me.OUTCOME_SUCCESS,
                          component="summary", provider="openai", model="gpt",
                          duration_ms=100, reason_code="already_answered",
                          usage_json={"cost_usd": 0.25})
        me.emit_mca_event(
            "LLM_CALL", outcome=me.OUTCOME_FAILED, level=me.LEVEL_ERROR,
            component="summary", provider="openai", duration_ms=300,
            reason_code="random_fallback",
            error_json=me.build_error_metadata(ValueError("x"), stage="call"))
        me.emit_mca_event("DELIVERY", outcome=me.OUTCOME_SUCCESS,
                          component="delivery",
                          reason_code="delivery_unknown")
        assert await me.flush_events(d) == 3
        store = TaskJobStore(d)
        running = await store.enqueue(owner="archive", kind="important")
        await store.mark_running(running)
        await store.save_checkpoint(running, cursor_token="c", processed=42)
        await store.enqueue(owner="summary", kind="important")
        m = await me.metrics(d)
        g = m["metrics"]
        assert m["events_total"] == 3 and m["errors_total"] == 1
        assert g["providers"]["available"] is True
        assert g["providers"]["requests"] == 2
        assert g["providers"]["errors"] == 1
        assert g["providers"]["latency_avg_ms"] == 200.0
        assert g["tasks"]["active"] == 1 and g["tasks"]["pending"] == 1
        assert g["archive"]["active_jobs"] == 1
        assert g["archive"]["processed"] == 42
        assert g["random"]["fallback_total"] == 1
        assert g["initiatives"]["silence_reasons"]["already_answered"] == 1
        assert g["delivery"]["results"]["success"] == 1
        assert g["cost"]["by_category"]["summary"] == 0.25
        m2 = await me.metrics(d, runtime={
            "cache_entries": 5, "rss_mb": 128.5, "provenance_coverage": 0.75,
            "histories": 3, "episodes": 9,
            "downloads": {"count": 2, "bytes": 1000}})
        g2 = m2["metrics"]
        assert g2["cache"]["entries"] == 5
        assert g2["runtime"]["rss_mb"] == 128.5
        assert g2["provenance"]["coverage"] == 0.75
        assert g2["memory"]["histories"] == 3
        assert g2["memory"]["episodes"] == 9
        assert g2["downloads"]["bytes"] == 1000
        assert "provenance" not in m2["unknown"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_query_events_reason_filter_and_limit(tmp_path):
    """SC-14: фильтры по reason + bounded LIMIT."""
    d = await _db(tmp_path, name="filters2.db")
    try:
        for _ in range(3):
            me.emit_mca_event("X", outcome=me.OUTCOME_SKIPPED,
                              component="summary",
                              reason_code="already_answered")
        me.emit_mca_event("Y", outcome=me.OUTCOME_SUCCESS,
                          component="retrieval",
                          reason_code="no_relevant_memory")
        await me.flush_events(d)
        rows = await me.query_events(d, reason_code="already_answered")
        assert len(rows) == 3
        rows = await me.query_events(d, component="retrieval", limit=1)
        assert len(rows) == 1 and rows[0]["event_name"] == "Y"
    finally:
        await d.close()
