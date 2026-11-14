"""SMART-CORRECTIVE-01 S5D-OBSERVABILITY — отказы incident service и счётчики
sweep (owner finding W-10; architecture-plan §7.5; owner input §9.2 E; AC-24).

Покрывает:

* отказ регистрации инцидента — и исключение, и честный `status=failed` от
  `mca_incidents.open_or_update` — логируется watchdog-логгером, эмитит WARN
  `WATCHDOG_INCIDENT_FAILURE` и увеличивает локальный счётчик `failed`;
  повторного `open_or_update` нет, рекурсивный инцидент не создаётся;
* счётчики различают `created|updated|reopened|failed|disabled` (bounded
  фиксированный набор ключей);
* существующий `WATCHDOG_SWEEP` публикует bounded `usage_json` с исходами
  discovered/attempted/recovered/failed/no_change, диагностикой
  overdue/queued/running_contract и накопленными totals — в существующем
  event/analytics-канале, без нового trace-хранилища и DDL;
* recovery-truth (queued/attempt/fencing) от отказа регистрации не меняется.

TEST-LIFECYCLE: CONTRACT/REGRESSION (S5D-OBSERVABILITY)
R17: только коды/числа/идентификаторы.
"""
import json
import logging
import time

import pytest

import services.database as dbmod
from services import mca_events as me
from services import mca_incidents as inc
from services import mca_trace as mt
from services import mca_watchdog as wd
from services.database import DatabaseService
from services.task_supervisor import JOB_QUEUED, TaskJobStore


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


async def _db(tmp_path, name="s5d_observability.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _make_running(store, *, owner="qnd.test", kind="test.job",
                        max_attempts=3, checkpoint=True,
                        heartbeat_age=None, progress_age=None,
                        deadline_in=None) -> str:
    jid = await store.enqueue(
        owner=owner, kind=kind, max_attempts=max_attempts,
        deadline_at=(int(time.time()) + deadline_in)
        if deadline_in is not None else None)
    assert await store.mark_running(jid) is True
    if checkpoint:
        await store.save_checkpoint(jid, cursor_token="c1", processed=3)
    now = int(time.time())
    if heartbeat_age is not None:
        await store._db.db.execute(
            "UPDATE task_jobs SET heartbeat_at = ?, updated_at = ? "
            "WHERE job_id = ?", (now - int(heartbeat_age), now, jid))
    if progress_age is not None:
        await store._db.db.execute(
            "UPDATE task_jobs SET progress_at = ? WHERE job_id = ?",
            (now - int(progress_age), jid))
    await store._db.db.commit()
    return jid


async def _queued_job(store, *, owner="mca16", kind="experience.review",
                      age=9999) -> str:
    jid = await store.enqueue(owner=owner, kind=kind)
    now = int(time.time())
    await store._db.db.execute(
        "UPDATE task_jobs SET created_at = ?, updated_at = ? "
        "WHERE job_id = ?", (now - int(age), now - int(age), jid))
    await store._db.db.commit()
    return jid


def _capture_events(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    def _fake(event_name, *, outcome, level="INFO", **fields):
        captured.append({"event_name": event_name, "outcome": outcome,
                         "level": level, **fields})
        return {"event_name": event_name, "outcome": outcome}

    monkeypatch.setattr(mt, "emit_stage", _fake)
    return captured


def _events(captured, name: str) -> list[dict]:
    return [e for e in captured if e.get("event_name") == name]


async def _incident_rows(db):
    cursor = await db.db.execute(
        "SELECT * FROM mca_incidents ORDER BY first_ts, incident_id")
    return [dict(r) for r in await cursor.fetchall()]


class TestIncidentRegistrationFailure:
    """W-10/AC-24: отказ наблюдаем, но не создаёт рекурсивный инцидент."""

    @pytest.mark.asyncio
    async def test_returned_failed_status_is_warned_logged_and_counted(
            self, tmp_path, monkeypatch, caplog):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(store, heartbeat_age=9999)
            calls = {"n": 0}

            async def _failed(*_a, **_kw):
                calls["n"] += 1
                return {"status": "failed", "incident_id": None,
                        "fingerprint": "fp", "severity": None,
                        "error": "OperationalError"}

            monkeypatch.setattr(inc, "open_or_update", _failed)
            before = wd.incident_outcome_totals()
            captured = _capture_events(monkeypatch)
            with caplog.at_level(logging.WARNING,
                                 logger="services.mca_watchdog"):
                result = await wd.sweep(d, job_store=store)

            assert calls["n"] == 1                    # без retry/рекурсии
            assert result["incident_outcomes"]["failed"] == 1
            assert result["incidents"] == 0
            assert await _incident_rows(d) == []       # инцидент не создан
            after = wd.incident_outcome_totals()
            assert after["failed"] == before["failed"] + 1
            assert any("incident registration failed" in rec.message
                       for rec in caplog.records)

            warn = _events(captured, "WATCHDOG_INCIDENT_FAILURE")
            assert len(warn) == 1
            event = warn[0]
            assert event["outcome"] == "failed"
            assert event["level"] == "WARN"
            assert event["job_id"] == jid
            assert event["pipeline_type"] == "qnd.test"
            assert event["stage"] == "takeover"
            assert event["error_json"]["type"] == "OperationalError"
            assert event["error_json"]["kind"] == "test.job"

            sweep_events = _events(captured, "WATCHDOG_SWEEP")
            assert len(sweep_events) == 1
            assert sweep_events[0]["usage_json"]["incident"]["failed"] == 1

            # recovery-truth не зависит от отказа регистрации инцидента
            assert result["takeover"]["recovered"] == [jid]
            assert (await store.get(jid))["status"] == JOB_QUEUED
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_raised_exception_is_warned_logged_and_counted(
            self, tmp_path, monkeypatch, caplog):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(store, heartbeat_age=9999)
            calls = {"n": 0}

            async def _boom(*_a, **_kw):
                calls["n"] += 1
                raise RuntimeError("incident db down")

            monkeypatch.setattr(inc, "open_or_update", _boom)
            captured = _capture_events(monkeypatch)
            with caplog.at_level(logging.WARNING,
                                 logger="services.mca_watchdog"):
                result = await wd.sweep(d, job_store=store)

            assert calls["n"] == 1
            assert result["incident_outcomes"]["failed"] == 1
            assert await _incident_rows(d) == []
            assert any("incident registration failed" in rec.message
                       for rec in caplog.records)
            warn = _events(captured, "WATCHDOG_INCIDENT_FAILURE")
            assert len(warn) == 1
            assert warn[0]["level"] == "WARN"
            assert warn[0]["error_json"]["type"] == "RuntimeError"
            assert warn[0]["job_id"] == jid
            # recovery выполнена, отказ регистрации её не отменяет
            assert result["takeover"]["recovered"] == [jid]
            assert (await store.get(jid))["status"] == JOB_QUEUED
        finally:
            await d.close()


class TestIncidentOutcomeCounters:
    """W-10: counter keys различают created/updated/reopened/failed/disabled."""

    @pytest.mark.asyncio
    async def test_created_updated_reopened_failed_are_distinct(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            await _queued_job(store)
            before = wd.incident_outcome_totals()

            created = await wd.sweep(d, job_store=store)
            assert created["incident_outcomes"]["created"] == 1
            assert created["incidents"] == 1

            updated = await wd.sweep(d, job_store=store)
            assert updated["incident_outcomes"]["updated"] == 1
            assert updated["incidents"] == 0

            rows = await _incident_rows(d)
            assert len(rows) == 1
            assert await inc.resolve(d, rows[0]["incident_id"],
                                     evidence="verified by S5D test")

            reopened = await wd.sweep(d, job_store=store)
            assert reopened["incident_outcomes"]["reopened"] == 1
            assert reopened["incidents"] == 1
            assert len(await _incident_rows(d)) == 2   # история сохранена

            async def _failed(*_a, **_kw):
                return {"status": "failed", "error": "OperationalError"}

            monkeypatch.setattr(inc, "open_or_update", _failed)
            failed = await wd.sweep(d, job_store=store)
            assert failed["incident_outcomes"]["failed"] == 1
            assert failed["incident_outcomes"]["created"] == 0
            assert failed["incident_outcomes"]["updated"] == 0
            assert failed["incidents"] == 0

            after = wd.incident_outcome_totals()
            assert after["created"] - before["created"] == 1
            assert after["updated"] - before["updated"] == 1
            assert after["reopened"] - before["reopened"] == 1
            assert after["failed"] - before["failed"] == 1
            assert after["disabled"] == before["disabled"]
            assert set(after) == {"created", "updated", "reopened", "failed",
                                  "disabled"}
        finally:
            await d.close()


class TestSweepDiagnosticsExposure:
    """S5D: существующий WATCHDOG_SWEEP публикует bounded outcome-счётчики."""

    @pytest.mark.asyncio
    async def test_sweep_event_exposes_outcome_and_diagnostic_counters(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            recovered = [
                await _make_running(store, heartbeat_age=9999)
                for _ in range(2)]
            await _make_running(store, owner="vision.media",
                                kind="vision.media", checkpoint=False,
                                heartbeat_age=1)
            await _queued_job(store)                  # queued hang
            now = int(time.time())
            overdue = await store.enqueue(owner="qnd.test", kind="test.job")
            await d.db.execute(
                "UPDATE task_jobs SET deadline_at = ? WHERE job_id = ?",
                (now - 100, overdue))
            await d.db.commit()

            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)

            events = _events(captured, "WATCHDOG_SWEEP")
            assert len(events) == 1
            usage = events[0]["usage_json"]
            assert usage["stale"] == 2
            assert sorted(result["takeover"]["recovered"]) == sorted(recovered)
            assert usage["takeover"] == {
                "discovered": 2, "attempted": 2, "recovered": 2,
                "failed": 0, "no_change": 0}
            assert usage["takeover_records"] == 2
            assert usage["incident"] == result["incident_outcomes"]
            # 2 stale-job + 1 queued hang создают инциденты
            assert usage["incident"]["created"] == 3
            assert usage["incidents"] == 3
            assert usage["overdue"] == {"running": 0, "queued": 1}
            assert usage["queued"]["hang"] == 1
            assert usage["queued"]["overdue"] == 1
            assert usage["running_contract"] == {"heartbeat_only": 1,
                                                 "deadline_bounded": 0}
            assert set(usage["takeover_totals"]) == {"recovered", "failed",
                                                     "no_change"}
            assert set(usage["incident_totals"]) == {
                "created", "updated", "reopened", "failed", "disabled"}
            assert set(usage["reconcile"]) == {
                "checked", "resolved", "pending", "inconclusive", "failed"}

            # ровно одно итоговое событие на проход
            await wd.sweep(d, job_store=store)
            assert len(_events(captured, "WATCHDOG_SWEEP")) == 2
        finally:
            await d.close()


class TestAnalyticsDurability:
    """S5D: счётчики и WARN отказа доходят до существующего mca_events."""

    @pytest.mark.asyncio
    async def test_sweep_summary_is_durable_with_usage_json(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            await _make_running(store, heartbeat_age=9999)
            await wd.sweep(d, job_store=store)
            assert await me.flush_events(d) >= 1
            cursor = await d.db.execute(
                "SELECT event_name, outcome, level, component, stage, "
                "usage_json FROM mca_events "
                "WHERE event_name = 'WATCHDOG_SWEEP'")
            rows = [dict(r) for r in await cursor.fetchall()]
            assert len(rows) == 1
            row = rows[0]
            assert row["outcome"] == "success"
            assert row["level"] == "INFO"
            assert row["component"] == "watchdog"
            assert row["stage"] == "sweep"
            usage = json.loads(row["usage_json"])
            assert usage["takeover"]["recovered"] == 1
            assert usage["incident"]["created"] == 1
            assert usage["running_contract"] == {"heartbeat_only": 0,
                                                 "deadline_bounded": 0}
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_incident_failure_warn_event_is_durable(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(store, heartbeat_age=9999)

            async def _failed(*_a, **_kw):
                return {"status": "failed", "error": "OperationalError"}

            monkeypatch.setattr(inc, "open_or_update", _failed)
            await wd.sweep(d, job_store=store)
            assert await me.flush_events(d) >= 1
            cursor = await d.db.execute(
                "SELECT event_name, outcome, level, component, stage, job_id, "
                "error_json FROM mca_events "
                "WHERE event_name = 'WATCHDOG_INCIDENT_FAILURE'")
            rows = [dict(r) for r in await cursor.fetchall()]
            assert len(rows) == 1
            row = rows[0]
            assert row["outcome"] == "failed"
            assert row["level"] == "WARN"
            assert row["component"] == "watchdog"
            assert row["stage"] == "takeover"
            assert row["job_id"] == jid
            assert json.loads(row["error_json"])["type"] == "OperationalError"
        finally:
            await d.close()
