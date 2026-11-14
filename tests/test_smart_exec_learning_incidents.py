"""SMART-EXECUTION-RELIABILITY-01 — I5: причины инцидентов asap8b01/qnd.event.

Owner input §I5: сам факт открытия инцидента не доказывает ошибку detector.
Для двух production-инцидентов (`pipeline_type=asap8b01` — owner
`initiative.observe`, `pipeline_type=qnd.event` — owner `initiative.event`)
реальная причина — watchdog-takeover прерванных пайплайнов при штатном
рестарте сервиса (2.58.192, 11.11.2026 19:05Z; см. binding evidence
`evidence/i-learning/binding-i56-*.md`). Инциденты законные:
`reason_code=worker_lost`, stage=takeover, severity ERROR; detector не
отключён, severity не занижена, инциденты не закрываются автоматически.

Тест фиксирует действующий контракт detector'а на реальном durable-пути
(TaskJobStore + mca_watchdog.sweep + mca_incidents) и защищает от «зелёной
панели»: понижение severity или самозакрытие инцидента ломает тест.

TEST-LIFECYCLE: CONTRACT/REGRESSION (SXR-I5-01)
R17: только коды/числа, без текстов сообщений.
"""
import time

import pytest

import services.database as dbmod
from services import mca_events as me
from services import mca_gates
from services import mca_incidents as inc
from services import mca_trace as mt
from services import mca_watchdog as wd
from services.database import DatabaseService
from services.task_supervisor import TaskJobStore

OWNERS = (("asap8b01", "initiative.observe"),
          ("qnd.event", "initiative.event"))


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


async def _db(tmp_path) -> DatabaseService:
    d = DatabaseService(str(tmp_path / "i5_incidents.db"))
    await d.initialize()
    return d


async def _stale_running_job(store, owner: str, kind: str):
    """Job, каким его видит startup-watchdog после рестарта: running, но
    heartbeat давно не обновлялся (процесс-владелец убит)."""
    jid = await store.enqueue(owner=owner, kind=kind)
    assert await store.mark_running(jid) is True
    await store._db.db.execute(
        "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
        (int(time.time()) - 9999, jid))
    await store._db.db.commit()
    return jid


async def _incident_rows(db):
    cursor = await db.db.execute(
        "SELECT incident_id, fingerprint, pipeline_type, stage, severity, "
        "repeat_count, resolved_at, fallback_used FROM mca_incidents "
        "ORDER BY first_ts")
    return [dict(row) for row in await cursor.fetchall()]


class TestIncidentCauses:
    @pytest.mark.asyncio
    async def test_restart_takeover_of_initiative_jobs_is_real_error(
            self, tmp_path):
        """asap8b01/qnd.event: takeover убитого рестартом процесса — законный
        ERROR worker_lost, а не дефект detector; инциденты не закрываются."""
        d = await _db(tmp_path)
        try:
            assert mca_gates.incidents_enabled() is True
            assert mca_gates.heartbeat_watchdog_enabled() is True
            store = TaskJobStore(d)
            jobs = {}
            for owner, kind in OWNERS:
                jobs[owner] = await _stale_running_job(store, owner, kind)

            result = await wd.sweep(d, job_store=store)
            assert result["incidents"] >= 2
            for owner, _kind in OWNERS:
                assert (await store.get(jobs[owner]))["status"] == "interrupted"

            rows = await _incident_rows(d)
            assert {row["pipeline_type"] for row in rows} == {
                "asap8b01", "qnd.event"}
            for row in rows:
                assert row["stage"] == "takeover"
                assert row["severity"] == "ERROR"      # severity не занижена
                assert row["resolved_at"] is None      # не закрыт автоматически
                assert row["fallback_used"] == 0

            # ack ≠ resolved: просмотр не закрывает инцидент.
            await inc.acknowledge(d, rows[0]["incident_id"], actor=7)
            assert len(await inc.active_incidents(d)) == 2
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_repeated_takeover_updates_same_incident_without_closing(
            self, tmp_path):
        """Повторный takeover того же owner'а — та же строка (fingerprint),
        repeat_count растёт, severity остаётся ERROR, инцидент не resolved."""
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            owner, kind = OWNERS[0]
            await _stale_running_job(store, owner, kind)
            await wd.sweep(d, job_store=store)
            first = await _incident_rows(d)
            assert len(first) == 1
            first_id = first[0]["incident_id"]

            await _stale_running_job(store, owner, kind)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 1                       # не второй инцидент
            assert rows[0]["incident_id"] == first_id
            assert rows[0]["repeat_count"] == 2
            assert rows[0]["severity"] == "ERROR"
            assert rows[0]["resolved_at"] is None
        finally:
            await d.close()
