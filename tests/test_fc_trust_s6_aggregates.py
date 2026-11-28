"""FCT-S6 U2 — агрегаты сохранённых прогонов (28.11.2026).

Источник: `plans/features/fc-trust-01/evidence/fct-s5-s6-scoping-2026-11-28/
scoping.md` §S6 + D-S6-2 (счётчики выводятся из существующих сигналов).

Проверяется чистый read-only агрегатор:
* runs/evidence/события `factcheck_claims` → распределения, доли, период/лимит;
* отсутствующий сигнал (`entity_collision`, `media_partial`, нет событий/дат) —
  честно `None`, не выдуманный 0;
* функция детерминирована и не делает записи; HTTP/UI не подключены.
"""
from __future__ import annotations

import json

import pytest

from services import temporal_factcheck as tf
from services.database import DatabaseService


def _run(run_id, correlation_id, created_at, verdict_outcome=None,
         stage=None):
    trace = []
    if verdict_outcome is not None:
        trace.append({"stage": "verdict", "outcome": verdict_outcome})
    if stage is not None:
        trace.append({"stage": "deliver", "outcome": stage})
    return {"run_id": run_id, "correlation_id": correlation_id,
            "created_at": created_at,
            "stage_trace": json.dumps(trace) if trace else None}


def _event(pipeline_run_id, status, cause=""):
    return {"event_name": "factcheck_claims",
            "pipeline_run_id": pipeline_run_id,
            "entity_ids": json.dumps({"execution_status": status,
                                      "execution_cause": cause})}


def _evidence(run_id, opened, published_at):
    return {"run_id": run_id, "opened": opened,
            "published_at": published_at}


def _aggregate():
    fn = getattr(tf, "aggregate_factcheck_snapshots", None)
    assert fn is not None, "чистый агрегатор отсутствует"
    return fn


class TestPureAggregates:
    def test_known_distributions_and_shares(self):
        runs = [_run("r3", "c3", 300, "success"),
                _run("r2", "c2", 200, "validated"),
                _run("r1", "c1", 100, "corrected")]
        events = [_event("c1", "technical_unverified", "rate_limit"),
                  _event("c2", "complete", ""),
                  _event("c3", "partial", "provider_error")]
        evidence = [_evidence("r1", 1, None),
                    _evidence("r2", 0, 123),
                    _evidence("r3", 0, None),
                    _evidence("r3", 1, 456)]
        result = _aggregate()(runs, evidence, events)
        assert result["runs"] == 3
        assert result["evidence_rows"] == 4
        assert result["execution_status"] == {
            "complete": 1, "partial": 1, "technical_unverified": 1}
        assert result["execution_cause"] == {
            "rate_limit": 1, "provider_error": 1}
        assert result["snippet_only_share"] == 0.5
        assert result["date_unknown_share"] == 0.5
        assert result["verdict_mismatch_share"] == pytest.approx(1 / 3)
        # durable-поля для этих сигналов нет — честный None
        assert result["entity_collision_share"] is None
        assert result["media_partial_share"] is None
        assert result["truncated"] is False

    def test_run_without_event_is_unknown_status(self):
        runs = [_run("r1", "c1", 1, "validated"),
                _run("r2", "c2", 2, "validated")]
        result = _aggregate()(runs, (), [_event("c1", "complete")])
        assert result["execution_status"] == {"complete": 1, "unknown": 1}
        assert result["execution_cause"] is None

    def test_no_signal_is_none_not_zero(self):
        runs = [_run("r1", None, 1)]
        result = _aggregate()(runs, (), ())
        assert result["execution_status"] is None
        assert result["execution_cause"] is None
        assert result["snippet_only_share"] is None
        assert result["date_unknown_share"] is None
        assert result["verdict_mismatch_share"] is None
        assert result["entity_collision_share"] is None
        assert result["media_partial_share"] is None

    def test_limit_marks_truncated_and_keeps_newest_first(self):
        runs = [_run("r3", "c3", 300), _run("r2", "c2", 200),
                _run("r1", "c1", 100)]
        result = _aggregate()(runs, limit=2)
        assert result["runs"] == 2
        assert result["truncated"] is True
        assert result["limit"] == 2

    def test_only_snippet_known_rows_in_denominator(self):
        runs = [_run("r1", "c1", 1)]
        evidence = [_evidence("r1", None, 123),   # старая схема: opened NULL
                    _evidence("r1", 0, 123)]
        result = _aggregate()(runs, evidence, ())
        assert result["snippet_only_share"] == 1.0
        assert result["date_unknown_share"] == 0.0


async def _seed(db):
    runs = [
        ("r1", "c1", 100, json.dumps([{"stage": "verdict",
                                       "outcome": "corrected"}])),
        ("r2", "c2", 200, json.dumps([{"stage": "verdict",
                                       "outcome": "validated"}])),
        ("r3", "c3", 300, json.dumps([{"stage": "verdict",
                                       "outcome": "success"}])),
    ]
    for run_id, corr, made, trace in runs:
        await db.db.execute(
            "INSERT INTO mca_factcheck_runs (run_id, correlation_id, "
            "access_scope, created_at, updated_at, stage_trace) "
            "VALUES (?,?,?,?,?,?)", (run_id, corr, "chat:1", made, made,
                                     trace))
    for run_id, url, published_at, opened in (
            ("r1", "https://a/1", None, 1),
            ("r2", "https://a/2", 123, 0),
            ("r3", "https://a/3", None, 0),
            ("r3", "https://a/4", 456, 1)):
        await db.db.execute(
            "INSERT INTO mca_factcheck_evidence (run_id, url, published_at, "
            "opened, created_at) VALUES (?,?,?,?,?)",
            (run_id, url, published_at, opened, 500))
    for corr, status, cause in (("c1", "technical_unverified", "rate_limit"),
                                ("c2", "complete", ""),
                                ("c3", "partial", "provider_error")):
        await db.db.execute(
            "INSERT INTO mca_events (ts, level, event_name, outcome, "
            "pipeline_run_id, entity_ids) VALUES (?,?,?,?,?,?)",
            (600, "INFO", "factcheck_claims", "success", corr,
             json.dumps({"execution_status": status,
                         "execution_cause": cause})))
    await db.db.commit()


class TestStoredAggregates:
    @pytest.mark.asyncio
    async def test_summary_over_seeded_runs(self, tmp_path):
        fn = getattr(tf, "summarize_factcheck_aggregates", None)
        assert fn is not None, "read-only сводка отсутствует"
        db = DatabaseService(str(tmp_path / "agg.db"))
        await db.initialize()
        try:
            await _seed(db)
            result = await fn(db, since_ts=150, until_ts=300, limit=500)
            assert result["period"] == {"since": 150, "until": 300}
            assert result["runs"] == 2
            assert result["execution_status"] == {"complete": 1, "partial": 1}
            assert result["execution_cause"] == {"provider_error": 1}
            # evidence r2 + r3 (r1 вне периода): opened 0,0,1 → 2/3
            assert result["snippet_only_share"] == pytest.approx(2 / 3)
            # published_at None у одной из трёх строк
            assert result["date_unknown_share"] == pytest.approx(1 / 3)
            assert result["verdict_mismatch_share"] == 0.0
            assert result["entity_collision_share"] is None
            assert result["media_partial_share"] is None
            assert result["truncated"] is False
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_limit_truncates_and_reports(self, tmp_path):
        fn = getattr(tf, "summarize_factcheck_aggregates", None)
        assert fn is not None
        db = DatabaseService(str(tmp_path / "agg_limit.db"))
        await db.initialize()
        try:
            await _seed(db)
            result = await fn(db, limit=1)
            assert result["runs"] == 1
            assert result["truncated"] is True
            # newest-first: r3 (partial), а не r1
            assert result["execution_status"] == {"partial": 1}
            assert result["execution_cause"] == {"provider_error": 1}
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_malformed_event_payload_is_ignored(self, tmp_path):
        fn = getattr(tf, "summarize_factcheck_aggregates", None)
        assert fn is not None
        db = DatabaseService(str(tmp_path / "agg_bad.db"))
        await db.initialize()
        try:
            await _seed(db)
            await db.db.execute(
                "INSERT INTO mca_events (ts, level, event_name, outcome, "
                "pipeline_run_id, entity_ids) VALUES (?,?,?,?,?,?)",
                (700, "INFO", "factcheck_claims", "success", "c1",
                 "not-json"))
            await db.db.commit()
            result = await fn(db, limit=500)
            # первый валидный сигнал c1 сохраняется (setdefault), мусор не рвёт
            assert result["execution_status"]["technical_unverified"] == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_db_none_returns_honest_none(self):
        fn = getattr(tf, "summarize_factcheck_aggregates", None)
        assert fn is not None
        result = await fn(None, limit=10)
        assert result["runs"] == 0
        assert result["execution_status"] is None
        assert result["snippet_only_share"] is None
        assert result["entity_collision_share"] is None
