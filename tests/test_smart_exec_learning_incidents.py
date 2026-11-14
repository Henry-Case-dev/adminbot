"""SMART-EXECUTION-RELIABILITY-01 — I5: причины инцидентов asap8b01/qnd.event.

Owner input §I5: сам факт открытия инцидента не доказывает ошибку detector.
Для двух production-инцидентов (`pipeline_type=asap8b01` — owner
`initiative.observe`, `pipeline_type=qnd.event` — owner `initiative.event`)
реальная причина — watchdog-takeover прерванных пайплайнов при штатном
рестарте сервиса (2.58.192, 11.11.2026 19:05Z; см. binding evidence
`evidence/i-learning/binding-i56-*.md`). Инциденты законные:
`reason_code=worker_lost`, stage=takeover, severity ERROR; detector не
отключён, severity не занижена.

SMART-CORRECTIVE-01 S5A (W-05) уточняет lifecycle: инцидент НЕ закрывается
механически и остаётся активным, пока связанная задача припаркована
(`interrupted`); авто-resolve выполняется только после фактического
терминального итога всех связанных job, а закрытая строка не переоткрывается
молча (новое наблюдение = новая строка с сохранением истории/severity).

Тест фиксирует действующий контракт detector'а на реальном durable-пути
(TaskJobStore + mca_watchdog.sweep + mca_incidents) и защищает от «зелёной
панели»: понижение severity, самозакрытие без терминала job или молчаливый
reopen ломают тест.

TEST-LIFECYCLE: CONTRACT/REGRESSION (SXR-I5-01, S5A-LIFECYCLE)
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
        "repeat_count, resolved_at, resolution_evidence, fallback_used "
        "FROM mca_incidents ORDER BY first_ts")
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
    async def test_repeated_observation_of_same_job_updates_same_incident(
            self, tmp_path):
        """S5C/W-11: fingerprint включает job_id/kind — повторное наблюдение
        ТОЙ ЖЕ задачи обновляет её строку (repeat_count растёт, severity
        остаётся ERROR), без дубля и без закрытия инцидента."""
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            owner, kind = OWNERS[0]
            jid = await _stale_running_job(store, owner, kind)
            await wd.sweep(d, job_store=store)
            first = await _incident_rows(d)
            assert len(first) == 1
            first_id = first[0]["incident_id"]

            again = await inc.open_or_update(
                d, process_id="watchdog.jobs", pipeline_type=owner,
                stage="takeover", reason_code="worker_lost",
                severity=inc.SEVERITY_ERROR, job_id=jid, kind=kind,
                title=f"job {jid}: worker_lost")
            assert again["status"] == "updated"
            rows = await _incident_rows(d)
            assert len(rows) == 1
            assert rows[0]["incident_id"] == first_id
            assert rows[0]["repeat_count"] == 2
            assert rows[0]["severity"] == "ERROR"
            assert rows[0]["resolved_at"] is None
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_new_job_same_owner_kind_gets_own_incident(self, tmp_path):
        """S5C/W-11: другой job того же owner/kind — отдельный инцидент,
        старый не перезаписывается и остаётся активным до своего терминала."""
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            owner, kind = OWNERS[0]
            first_job = await _stale_running_job(store, owner, kind)
            await wd.sweep(d, job_store=store)
            second_job = await _stale_running_job(store, owner, kind)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 2
            assert len({r["fingerprint"] for r in rows}) == 2
            assert all(r["resolved_at"] is None for r in rows)
            assert first_job != second_job
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_incident_resolves_only_after_linked_job_terminal(
            self, tmp_path):
        """S5A/W-05: припаркованная задача держит инцидент активным; после
        фактического терминала — авто-resolve; новое наблюдение после
        закрытия создаёт новую строку, а не молча переоткрывает старую."""
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            owner, kind = OWNERS[0]
            jid = await _stale_running_job(store, owner, kind)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 1 and rows[0]["resolved_at"] is None
            first_id = rows[0]["incident_id"]

            # Условие ещё не исчезло (job припаркован) — инцидент активен.
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 1
            assert rows[0]["incident_id"] == first_id
            assert rows[0]["resolved_at"] is None

            # Фактический терминальный итог job → следующий sweep закрывает.
            assert await store.finish(jid, status="failed",
                                      reason_code="worker_lost",
                                      recovery=True) is True
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 1                       # история сохранена
            assert rows[0]["incident_id"] == first_id
            assert rows[0]["resolved_at"] is not None
            assert "jobs_terminal" in rows[0]["resolution_evidence"]
            assert rows[0]["severity"] == "ERROR"       # severity не снижена

            # Повторное наблюдение после закрытия: новая строка, старая
            # resolved-история не переоткрыта.
            await _stale_running_job(store, owner, kind)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 2
            old = [r for r in rows if r["incident_id"] == first_id][0]
            assert old["resolved_at"] is not None
            new = [r for r in rows if r["incident_id"] != first_id][0]
            assert new["resolved_at"] is None
        finally:
            await d.close()
