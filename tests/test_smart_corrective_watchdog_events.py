"""SMART-CORRECTIVE-01 S5C-EVENTS — per-job `WATCHDOG_TAKEOVER` и fingerprint.

Покрывает owner-findings W-01/W-11 (architecture-plan §7.1/§7.3):

* W-01: на реально затронутую задачу эмитится ровно одно событие
  `WATCHDOG_TAKEOVER` с её identity (`job_id`, `entity_ids`, owner через
  `pipeline_type`, kind в разрешённом JSON-поле) и честным исходом
  `recovered|failed|no_change`; пустой batch не эмитит takeover; повторный
  проход по тому же batch не создаёт идентичных дублей; `mca_events`
  валидация сохраняет additive-поля и отвергает malformed события.
* W-11: fingerprint инцидента включает `kind` и `job_id`; два job одного
  owner разных kind дают два инцидента; title каждого называет свой job;
20-id bound `jobs_json` сохранён; исторические строки не backfill-ятся.

TEST-LIFECYCLE: CONTRACT/REGRESSION (S5C-EVENTS)
R17: только коды/числа/идентификаторы.
"""
import json
import time

import pytest

import services.database as dbmod
from services import mca_events as me
from services import mca_incidents as inc
from services import mca_trace as mt
from services import mca_watchdog as wd
from services.database import DatabaseService
from services.task_supervisor import JOB_QUEUED, JOB_RUNNING, TaskJobStore


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


async def _db(tmp_path, name="s5c_events.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _stale_running(store, jid: str, *, age: int = 9999) -> None:
    await store._db.db.execute(
        "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
        (int(time.time()) - age, jid))
    await store._db.db.commit()


async def _running_job(store, *, owner="qnd.test", kind="test.job",
                       max_attempts=3, checkpoint=True) -> str:
    jid = await store.enqueue(owner=owner, kind=kind,
                              max_attempts=max_attempts)
    assert await store.mark_running(jid) is True
    if checkpoint:
        await store.save_checkpoint(jid, cursor_token="c1", processed=3)
    await _stale_running(store, jid)
    return jid


def _capture_events(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    def _fake(event_name, *, outcome, level="INFO", **fields):
        captured.append({"event_name": event_name, "outcome": outcome,
                         "level": level, **fields})
        return {"event_name": event_name, "outcome": outcome}

    monkeypatch.setattr(mt, "emit_stage", _fake)
    return captured


def _takeover_events(captured):
    return [e for e in captured if e.get("event_name") == "WATCHDOG_TAKEOVER"]


async def _incident_rows(db):
    cursor = await db.db.execute(
        "SELECT * FROM mca_incidents ORDER BY first_ts, incident_id")
    return [dict(r) for r in await cursor.fetchall()]


class TestPerJobTakeoverEvents:
    """W-01: одно событие на затронутую задачу, без агрегатных дублей."""

    @pytest.mark.asyncio
    async def test_three_stale_jobs_emit_one_event_per_job_with_identity(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jobs = [await _running_job(store, owner="qnd.test",
                                       kind="test.job", max_attempts=3)
                    for _ in range(3)]
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)

            assert sorted(result["takeover"]["recovered"]) == sorted(jobs)
            events = _takeover_events(captured)
            assert len(events) == 3
            assert {e.get("job_id") for e in events} == set(jobs)
            for event in events:
                jid = event["job_id"]
                assert event["outcome"] == "success"
                assert event["reason_code"] == "takeover_recovered"
                assert event["level"] == "INFO"
                assert event["stage"] == "takeover"
                assert event["entity_ids"] == [jid]
                assert event["pipeline_type"] == "qnd.test"
                assert event["status"] == "recovered"
                assert event["attempt"] == 1
                assert event["error_json"]["kind"] == "test.job"
                assert event["error_json"]["action"] == "requeued"
                assert event["error_json"]["fencing_token"] == 1
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_same_batch_is_not_reemitted_on_next_sweep(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            for _ in range(3):
                await _running_job(store, owner="qnd.test",
                                   kind="test.job", max_attempts=3)
            captured = _capture_events(monkeypatch)
            await wd.sweep(d, job_store=store)
            first = _takeover_events(captured)
            assert len(first) == 3
            # Повторный проход: те же задачи уже queued — идентичных
            # takeover-событий «из-за размера stale batch» больше нет.
            await wd.sweep(d, job_store=store)
            assert len(_takeover_events(captured)) == len(first)
            assert len({e["job_id"] for e in first}) == len(first)
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_mixed_batch_carries_matching_truthful_outcomes(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            ok = await _running_job(store, owner="qnd.test", kind="ok",
                                    max_attempts=3, checkpoint=True)
            danger = await _running_job(store, owner="archive", kind="backup",
                                        max_attempts=5, checkpoint=False)
            parked = await _running_job(store, owner="qnd.other", kind="parked",
                                        max_attempts=5, checkpoint=False)
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)

            assert result["takeover"]["recovered"] == [ok]
            assert result["takeover"]["failed"] == [danger]
            assert result["takeover"]["no_change"] == [parked]
            events = {e["job_id"]: e for e in _takeover_events(captured)}
            assert set(events) == {ok, danger, parked}
            assert (events[ok]["outcome"], events[ok]["status"],
                    events[ok]["level"]) == ("success", "recovered", "INFO")
            assert (events[danger]["outcome"], events[danger]["status"],
                    events[danger]["level"]) == ("failed", "failed", "ERROR")
            assert (events[parked]["outcome"], events[parked]["status"],
                    events[parked]["level"]) == ("skipped", "no_change", "WARN")
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_empty_batch_emits_no_takeover(self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)
            assert result["stale"] == []
            assert _takeover_events(captured) == []
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_missing_store_emits_per_job_no_change(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, owner="qnd.test", kind="test.job")
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=None)

            assert result["takeover"]["no_change"] == [jid]
            events = _takeover_events(captured)
            assert len(events) == 1
            event = events[0]
            assert event["job_id"] == jid
            assert event["outcome"] == "skipped"
            assert event["level"] == "WARN"
            assert event["status"] == "no_change"
            assert event["error_json"]["action"] == "store_unavailable"
            assert (await store.get(jid))["status"] == JOB_RUNNING
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_failed_outcome_event_is_error_with_identity(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, owner="archive", kind="backup",
                                     max_attempts=5, checkpoint=False)
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)

            assert result["takeover"]["failed"] == [jid]
            events = _takeover_events(captured)
            assert len(events) == 1
            event = events[0]
            assert event["job_id"] == jid
            assert event["outcome"] == "failed"
            assert event["level"] == "ERROR"
            assert event["status"] == "failed"
            assert event["error_json"]["reason"] == "checkpoint_missing"
            assert (await store.get(jid))["status"] != JOB_QUEUED
        finally:
            await d.close()


class TestEventPayloadContract:
    """W-01: mca_events validation принимает additive-поля, malformed — нет."""

    def test_build_event_keeps_per_job_additive_fields(self):
        event = me.build_event(
            "WATCHDOG_TAKEOVER", outcome="success", level="INFO",
            component="watchdog", stage="takeover",
            reason_code="takeover_recovered", job_id="job-123",
            entity_ids=["job-123"], pipeline_type="qnd.test",
            status="recovered", attempt=1,
            error_json={"kind": "test.job", "fencing_token": 2})
        assert event is not None
        assert event["job_id"] == "job-123"
        assert json.loads(event["entity_ids"]) == ["job-123"]
        assert event["pipeline_type"] == "qnd.test"
        assert event["status"] == "recovered"
        assert event["attempt"] == 1
        assert json.loads(event["error_json"])["kind"] == "test.job"

    def test_build_event_rejects_malformed_payloads(self):
        assert me.build_event("WATCHDOG_TAKEOVER",
                              outcome="not-an-outcome") is None
        assert me.build_event("WATCHDOG_TAKEOVER", outcome="success",
                              error_json={"bad": object()}) is None
        # Неизвестное поле не превращается в новый контракт — отбрасывается.
        dropped = me.build_event("WATCHDOG_TAKEOVER", outcome="success",
                                 job_ids=["job-123"])
        assert dropped is not None and "job_ids" not in dropped
        # job_id обязан быть id-строкой; dict не проходит валидацию.
        bad_id = me.build_event("WATCHDOG_TAKEOVER", outcome="success",
                                job_id={"x": 1})
        assert bad_id is not None and "job_id" not in bad_id

    @pytest.mark.asyncio
    async def test_durable_event_rows_carry_job_identity(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jobs = [await _running_job(store, owner="qnd.test",
                                       kind="test.job", max_attempts=3)
                    for _ in range(3)]
            await wd.sweep(d, job_store=store)
            assert await me.flush_events(d) >= 3
            cursor = await d.db.execute(
                "SELECT event_name, outcome, reason_code, level, job_id, "
                "entity_ids, pipeline_type, status, attempt, error_json, "
                "stage, component FROM mca_events "
                "WHERE event_name = 'WATCHDOG_TAKEOVER'")
            rows = [dict(r) for r in await cursor.fetchall()]
            assert len(rows) == 3
            assert {r["job_id"] for r in rows} == set(jobs)
            for row in rows:
                assert json.loads(row["entity_ids"]) == [row["job_id"]]
                assert row["pipeline_type"] == "qnd.test"
                assert row["status"] == "recovered"
                assert row["attempt"] == 1
                assert row["stage"] == "takeover"
                assert row["component"] == "watchdog"
                assert json.loads(row["error_json"])["kind"] == "test.job"
                assert row["outcome"] == "success"
                assert row["reason_code"] == "takeover_recovered"
                assert row["level"] == "INFO"
        finally:
            await d.close()


class TestIncidentFingerprint:
    """W-11: kind/job_id в fingerprint; title не замерзает на первом job."""

    def test_fingerprint_includes_kind_and_job_id_and_is_stable(self):
        base = inc.compute_fingerprint(
            process_id="watchdog.jobs", pipeline_type="qnd.test",
            stage="takeover", reason_code="worker_lost")
        assert base == inc.compute_fingerprint(
            process_id="watchdog.jobs", pipeline_type="qnd.test",
            stage="takeover", reason_code="worker_lost")
        by_kind_1 = inc.compute_fingerprint(
            process_id="watchdog.jobs", pipeline_type="qnd.test",
            stage="takeover", reason_code="worker_lost",
            kind="kind.one", job_id="job-1")
        by_kind_2 = inc.compute_fingerprint(
            process_id="watchdog.jobs", pipeline_type="qnd.test",
            stage="takeover", reason_code="worker_lost",
            kind="kind.two", job_id="job-1")
        by_job_2 = inc.compute_fingerprint(
            process_id="watchdog.jobs", pipeline_type="qnd.test",
            stage="takeover", reason_code="worker_lost",
            kind="kind.one", job_id="job-2")
        assert base != by_kind_1
        assert by_kind_1 != by_kind_2
        assert by_kind_1 != by_job_2
        assert "kind.one" in by_kind_1 and "job-1" in by_kind_1

    @pytest.mark.asyncio
    async def test_two_jobs_same_owner_different_kind_two_incidents(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            j1 = await _running_job(store, owner="qnd.test", kind="kind.one",
                                    max_attempts=5, checkpoint=False)
            j2 = await _running_job(store, owner="qnd.test", kind="kind.two",
                                    max_attempts=5, checkpoint=False)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 2
            by_job = {json.loads(r["jobs_json"])[0]: r for r in rows}
            assert set(by_job) == {j1, j2}
            for jid, row in by_job.items():
                own_kind = "kind.one" if jid == j1 else "kind.two"
                assert own_kind in row["fingerprint"]
                assert jid in row["fingerprint"]
                assert row["title"].startswith(f"job {jid}:")
                assert json.loads(row["jobs_json"]) == [jid]
        finally:
            await d.close()

    def test_jobs_json_retains_20_id_bound(self):
        existing = json.dumps([f"job-{i}" for i in range(20)])
        updated = inc._job_append(existing, "job-20")
        data = json.loads(updated)
        assert len(data) == 20
        assert data[-1] == "job-20"
        assert "job-0" not in data

    @pytest.mark.asyncio
    async def test_historical_incident_row_is_not_modified(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            now = int(time.time())
            legacy_fp = "watchdog.jobs|qnd.legacy|takeover|worker_lost||"
            await d.db.execute(
                "INSERT INTO mca_incidents (incident_id, fingerprint, "
                "process_id, pipeline_type, stage, severity, title, first_ts, "
                "last_ts, repeat_count, jobs_json, chats_json, fallback_used, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("inc_legacy_event_row", legacy_fp, "watchdog.jobs",
                 "qnd.legacy", "takeover", "ERROR", "legacy title",
                 now - 100, now - 50, 3, json.dumps(["legacy_missing_job"]),
                 "[]", 0, now - 100, now - 50))
            await d.db.commit()

            jid = await _running_job(store, owner="qnd.legacy", kind="k",
                                     max_attempts=5)
            await wd.sweep(d, job_store=store)

            rows = await _incident_rows(d)
            legacy = [r for r in rows
                      if r["incident_id"] == "inc_legacy_event_row"][0]
            assert legacy["fingerprint"] == legacy_fp    # без backfill
            assert legacy["title"] == "legacy title"
            assert legacy["repeat_count"] == 3
            assert legacy["resolved_at"] is None
            new_rows = [r for r in rows
                        if r["incident_id"] != "inc_legacy_event_row"]
            assert len(new_rows) == 1
            assert jid in new_rows[0]["fingerprint"]
            assert "k" in new_rows[0]["fingerprint"]
        finally:
            await d.close()
