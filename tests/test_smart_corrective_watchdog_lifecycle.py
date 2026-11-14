"""SMART-CORRECTIVE-01 S5A-LIFECYCLE — truthful recovery outcome и lifecycle.

Покрывает owner-findings W-02/W-05/W-07 и частично W-03/W-10 (см.
`plans/features/smart-corrective-01/architecture-plan.md` §7.1–7.5):

* W-02: `takeover_recovered` эмитится только после ПОДТВЕРЖДЁННОГО перехода
  `running → queued`; отказ store / отсутствие store / припаркованная задача
  не дают success-события; discovered/attempted/recovered/failed/no_change
  различимы;
* W-03 (безопасная часть): takeover возвращает задачу в работу только при
  durable checkpoint и неисчерпанном `max_attempts`; attempt/max_attempts/
  next_retry_at сохраняются; `delivery_unknown` не повторяется слепо;
  дублированного enqueue/recovery нет;
* W-05: resolved-инцидент не переоткрывается молча (новая строка), авто-resolve
  только после терминального итога ВСЕХ связанных job; история и severity
  сохраняются; ручной resolve остаётся;
* W-07: `finish` без fencing-токена не переписывает припаркованную/
  терминальную задачу после takeover; токен текущего владельца работает;
* W-10 (partial): отказ/выключение incident-service наблюдаемы (log WARN +
  счётчики), без рекурсивного инцидента; created/updated/reopened/failed/
  disabled различимы.

TEST-LIFECYCLE: CONTRACT/REGRESSION (S5A-LIFECYCLE)
R17: только коды/числа/идентификаторы.
"""
import json
import logging
import time

import pytest

import services.database as dbmod
from services import mca_events as me
from services import mca_gates
from services import mca_incidents as inc
from services import mca_trace as mt
from services import mca_vision
from services import media_readiness as mr
from services import mca_watchdog as wd
from services.database import DatabaseService
from services.task_supervisor import (JOB_COMPLETED, JOB_FAILED,
                                      JOB_INTERRUPTED, JOB_QUEUED, JOB_RUNNING,
                                      TaskJobStore)


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


async def _db(tmp_path, name="s5a_lifecycle.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _stale_running(store, jid: str, *, age: int = 9999) -> None:
    await store._db.db.execute(
        "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
        (int(time.time()) - age, jid))
    await store._db.db.commit()


async def _running_job(store, *, owner="qnd.test", kind="test.job",
                       max_attempts=1, checkpoint=False) -> str:
    jid = await store.enqueue(owner=owner, kind=kind,
                              max_attempts=max_attempts)
    assert await store.mark_running(jid) is True
    if checkpoint:
        await store.save_checkpoint(jid, cursor_token="c1", processed=3)
    await _stale_running(store, jid)
    return jid


async def _incident_rows(db):
    cursor = await db.db.execute(
        "SELECT * FROM mca_incidents ORDER BY first_ts, incident_id")
    return [dict(r) for r in await cursor.fetchall()]


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


def _has_success_recovered(captured) -> bool:
    return any(e.get("outcome") == "success"
               and e.get("reason_code") == "takeover_recovered"
               for e in _takeover_events(captured))


class TestTruthfulTakeoverOutcome:
    """W-02: попытка ≠ результат; success только по подтверждённому переходу."""

    @pytest.mark.asyncio
    async def test_durable_event_pipeline_has_no_false_recovered(
            self, tmp_path, monkeypatch):
        """Реальный `build_event`/durable `mca_events`: при отказе store нет
        ни одного success-`takeover_recovered`, а отказ виден как failed."""
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            await _running_job(store)

            async def _boom(*_a, **_kw):
                raise RuntimeError("store down")

            monkeypatch.setattr(TaskJobStore, "takeover_stale", _boom)
            await wd.sweep(d, job_store=store)
            assert await me.flush_events(d) >= 1
            cursor = await d.db.execute(
                "SELECT event_name, outcome, reason_code, level FROM "
                "mca_events WHERE event_name = 'WATCHDOG_TAKEOVER'")
            rows = [dict(r) for r in await cursor.fetchall()]
            assert rows, "takeover-событие не доехало до durable-контракта"
            assert not [r for r in rows
                        if r["reason_code"] == "takeover_recovered"]
            assert [r for r in rows if r["outcome"] == "failed"
                    and r["level"] == "ERROR"
                    and r["reason_code"] == "worker_lost"]
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_durable_event_pipeline_has_confirmed_recovered(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=3, checkpoint=True)
            await wd.sweep(d, job_store=store)
            assert await me.flush_events(d) >= 1
            cursor = await d.db.execute(
                "SELECT event_name, outcome, reason_code FROM mca_events "
                "WHERE event_name = 'WATCHDOG_TAKEOVER'")
            rows = [dict(r) for r in await cursor.fetchall()]
            recovered = [r for r in rows
                         if r["reason_code"] == "takeover_recovered"]
            assert len(recovered) == 1
            assert recovered[0]["outcome"] == "success"
            assert not [r for r in rows if r["outcome"] == "failed"]
            assert (await store.get(jid))["status"] == JOB_QUEUED
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_store_failure_never_emits_recovered(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store)
            captured = _capture_events(monkeypatch)

            async def _boom(*_a, **_kw):
                raise RuntimeError("store down")

            monkeypatch.setattr(TaskJobStore, "takeover_stale", _boom)
            result = await wd.sweep(d, job_store=store)

            assert result["takeover"]["discovered"] == [jid]
            assert result["takeover"]["attempted"] == [jid]
            assert result["takeover"]["recovered"] == []
            assert result["takeover"]["failed"] == [jid]
            assert result["recovered"] == []
            assert not _has_success_recovered(captured)
            failed = [e for e in _takeover_events(captured)
                      if e.get("outcome") == "failed"]
            assert failed and failed[0]["level"] == "ERROR"
            # Store упал до изменений — задача не объявлена восстановленной.
            row = await store.get(jid)
            assert row["status"] == JOB_RUNNING
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_missing_store_never_claims_recovery(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store)
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=None)

            assert result["takeover"]["no_change"] == [jid]
            assert result["takeover"]["attempted"] == []
            assert result["recovered"] == []
            assert not _has_success_recovered(captured)
            skipped = [e for e in _takeover_events(captured)
                       if e.get("outcome") == "skipped"]
            assert skipped and skipped[0]["level"] == "WARN"
            assert (await store.get(jid))["status"] == JOB_RUNNING
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_checkpoint_takeover_requeues_with_retry(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=3, checkpoint=True)
            before = await store.get(jid)
            captured = _capture_events(monkeypatch)
            now = int(time.time())
            result = await wd.sweep(d, job_store=store, now=now)

            row = await store.get(jid)
            assert row["status"] == JOB_QUEUED
            assert row["reason_code"] == "worker_lost"
            assert row["attempt"] == before["attempt"] == 1
            assert row["max_attempts"] == 3
            assert row["next_retry_at"] >= now
            assert row["fencing_token"] == before["fencing_token"] + 1
            assert result["takeover"]["recovered"] == [jid]
            assert result["recovered"] == [jid]
            assert result["takeover"]["failed"] == []
            events = _takeover_events(captured)
            assert len([e for e in events
                        if e.get("reason_code") == "takeover_recovered"]) == 1
            assert _has_success_recovered(captured)
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_without_checkpoint_parks_without_false_success(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=5)
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)

            row = await store.get(jid)
            assert row["status"] == JOB_INTERRUPTED
            assert row["reason_code"] == "checkpoint_missing"
            assert row["attempt"] == 1
            assert row["next_retry_at"] is None
            assert result["takeover"]["no_change"] == [jid]
            assert result["takeover"]["recovered"] == []
            assert not _has_success_recovered(captured)
            assert any(e.get("outcome") == "skipped" and e.get("level") == "WARN"
                       for e in _takeover_events(captured))
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_dangerous_without_checkpoint_is_failed_parked(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, owner="archive", max_attempts=5)
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)

            row = await store.get(jid)
            assert row["status"] == JOB_INTERRUPTED
            assert row["reason_code"] == "checkpoint_missing"
            assert result["takeover"]["failed"] == [jid]
            assert not _has_success_recovered(captured)
            assert any(e.get("outcome") == "failed" and e.get("level") == "ERROR"
                       for e in _takeover_events(captured))
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_attempts_exhausted_is_terminal(self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=1, checkpoint=True)
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)

            row = await store.get(jid)
            assert row["status"] == JOB_FAILED
            assert row["reason_code"] == "attempts_exhausted"
            assert row["error_code"] == "attempts_exhausted"
            assert row["finished_at"] is not None
            assert result["takeover"]["failed"] == [jid]
            assert not _has_success_recovered(captured)
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_outcomes_are_separated_per_job(self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            ok = await _running_job(store, owner="qnd.test", kind="a",
                                    max_attempts=3, checkpoint=True)
            danger = await _running_job(store, owner="archive", kind="b",
                                        max_attempts=5)
            parked = await _running_job(store, owner="qnd.other", kind="c",
                                        max_attempts=5)
            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)

            assert result["takeover"]["recovered"] == [ok]
            assert result["takeover"]["failed"] == [danger]
            assert result["takeover"]["no_change"] == [parked]
            assert sorted(result["takeover"]["discovered"]) == sorted(
                [ok, danger, parked])
            assert len(result["takeover"]["records"]) == 3
            events = _takeover_events(captured)
            assert len([e for e in events
                        if e.get("reason_code") == "takeover_recovered"]) == 1
            assert len([e for e in events if e.get("outcome") == "failed"]) == 1
            assert len([e for e in events
                        if e.get("outcome") == "skipped"]) == 1
        finally:
            await d.close()


class TestFencingTerminalWriters:
    """W-07: finish без токена не воскрешает задачу после takeover."""

    @pytest.mark.asyncio
    async def test_no_token_finish_cannot_revive_after_takeover(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=3, checkpoint=True)
            await wd.sweep(d, job_store=store)
            assert (await store.get(jid))["status"] == JOB_QUEUED

            # Устаревший владелец без токена — no-op, задача остаётся queued.
            assert await store.finish(jid, status=JOB_COMPLETED) is False
            assert (await store.get(jid))["status"] == JOB_QUEUED
            # Устаревший токен (до takeover) — тоже no-op.
            assert await store.finish(jid, status=JOB_COMPLETED,
                                      fencing_token=0) is False
            assert (await store.get(jid))["status"] == JOB_QUEUED
            # Новый владелец: claim увеличивает attempt и сохраняет token.
            assert await store.mark_running(jid) is True
            row = await store.get(jid)
            assert row["status"] == JOB_RUNNING
            assert await store.finish(jid, status=JOB_COMPLETED,
                                      fencing_token=row["fencing_token"]) is True
            assert (await store.get(jid))["status"] == JOB_COMPLETED
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_active_state_finish_without_token_still_works(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await store.enqueue(owner="summary", kind="important")
            assert await store.mark_running(jid) is True
            assert await store.finish(jid, status=JOB_COMPLETED,
                                      reason_code="ok") is True
            assert (await store.get(jid))["status"] == JOB_COMPLETED
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_no_token_cannot_overwrite_terminal_record(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await store.enqueue(owner="summary", kind="important")
            await store.mark_running(jid)
            assert await store.finish(jid, status=JOB_COMPLETED) is True
            # Поздняя запись без токена не переписывает терминальный итог.
            assert await store.finish(jid, status=JOB_FAILED,
                                      reason_code="late") is False
            row = await store.get(jid)
            assert row["status"] == JOB_COMPLETED
            assert row["reason_code"] != "late"
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_explicit_recovery_path_can_finalize_interrupted(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=5)
            await wd.sweep(d, job_store=store)
            assert (await store.get(jid))["status"] == JOB_INTERRUPTED
            assert await store.finish(jid, status=JOB_FAILED,
                                      reason_code="recovery_exhausted",
                                      recovery=True) is True
            assert (await store.get(jid))["status"] == JOB_FAILED
        finally:
            await d.close()


class TestRecoverySafety:
    """W-03 (безопасная часть): recovery использует существующий контракт."""

    @pytest.mark.asyncio
    async def test_delivery_unknown_not_retried_by_takeover(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=3, checkpoint=True)
            await d.db.execute(
                "UPDATE task_jobs SET reason_code = 'delivery_unknown', "
                "error_code = 'delivery_unknown' WHERE job_id = ?", (jid,))
            await d.db.commit()
            result = await wd.sweep(d, job_store=store)

            row = await store.get(jid)
            assert row["status"] == JOB_INTERRUPTED
            # F-S5A-01: защитный маркер сохраняется при снятии lease, иначе
            # recover_job снова увидит «worker_lost» и возобновит side effect.
            assert row["reason_code"] == "delivery_unknown"
            assert row["next_retry_at"] is None
            assert result["takeover"]["no_change"] == [jid]
            assert result["takeover"]["records"][0]["action"] == \
                "reconcile_required"
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_delivery_unknown_takeover_cannot_be_resumed(
            self, tmp_path, monkeypatch):
        """F-S5A-01: takeover → recover_job не возобновляет delivery_unknown.

        Даже при наличии durable checkpoint задача остаётся припаркованной:
        повтор side-effect операции/доставки запрещён; recover_job возвращает
        reconcile-required и не переводит строку в queued/running."""
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=5, checkpoint=True)
            await d.db.execute(
                "UPDATE task_jobs SET reason_code = 'delivery_unknown', "
                "error_code = 'delivery_unknown' WHERE job_id = ?", (jid,))
            await d.db.commit()
            before = await store.get(jid)

            captured = _capture_events(monkeypatch)
            result = await wd.sweep(d, job_store=store)
            assert result["takeover"]["no_change"] == [jid]
            assert result["takeover"]["recovered"] == []
            row = await store.get(jid)
            assert row["status"] == JOB_INTERRUPTED
            assert row["reason_code"] == "delivery_unknown"
            assert row["fencing_token"] == before["fencing_token"] + 1
            assert row["next_retry_at"] is None

            rec = await wd.recover_job(d, store, jid)
            assert rec["status"] == "reconcile_required"
            assert rec["reason"] == "delivery_unknown"
            assert rec["resumed"] is False
            row = await store.get(jid)
            assert row["status"] == JOB_INTERRUPTED
            assert row["reason_code"] == "delivery_unknown"
            assert row["next_retry_at"] is None
            # Никакого «успешного» recovery-события/перехода не эмитировано.
            assert not [e for e in captured
                        if e.get("reason_code")
                        == "recovery_from_checkpoint"]
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_requeued_job_has_no_duplicate_active_row(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await store.enqueue(owner="qnd.test", kind="k",
                                      coalesce_key="s5a-dup",
                                      max_attempts=3)
            await store.mark_running(jid)
            await store.save_checkpoint(jid, cursor_token="c", processed=1)
            await _stale_running(store, jid)
            await wd.sweep(d, job_store=store)
            # Повторный enqueue того же coalesce-key не создаёт дубль.
            again = await store.enqueue(owner="qnd.test", kind="k",
                                        coalesce_key="s5a-dup",
                                        max_attempts=3)
            assert again == jid
            assert len(await store.active()) == 1
        finally:
            await d.close()


class TestDeliveryUnknownDurableGuards:
    """F-S5A-02/03: ни один resume/retry/re-arm не обходит delivery_unknown."""

    @staticmethod
    async def _mark_delivery_unknown(db, jid: str, *, mode: str) -> None:
        reason = "delivery_unknown" if mode in ("both", "reason") else None
        error = "delivery_unknown" if mode in ("both", "error") else None
        await db.db.execute(
            "UPDATE task_jobs SET reason_code = ?, error_code = ? "
            "WHERE job_id = ?", (reason, error, jid))
        await db.db.commit()

    @pytest.mark.asyncio
    async def test_recover_stale_preserves_delivery_unknown_marker(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, max_attempts=3)
            await self._mark_delivery_unknown(d, jid, mode="both")
            lost = await store.recover_stale(stale_after_seconds=60)
            assert jid in lost
            row = await store.get(jid)
            assert row["status"] == JOB_INTERRUPTED
            assert row["reason_code"] == "delivery_unknown"
            assert row["error_code"] == "delivery_unknown"
            assert row["fencing_token"] == 1
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_resume_primitives_refuse_delivery_unknown_markers(
            self, tmp_path):
        for mode in ("both", "reason", "error"):
            d = await _db(tmp_path, name=f"s5a_prim_{mode}.db")
            try:
                store = TaskJobStore(d)
                jid = await store.enqueue(owner="qnd.test", kind="k")
                await store.mark_running(jid)
                await store.finish(jid, status=JOB_FAILED)
                await self._mark_delivery_unknown(d, jid, mode=mode)
                before = await store.get(jid)

                assert await store.requeue(
                    jid, reason_code="stage_retry_scheduled") is False
                assert await store.set_next_retry(
                    jid, int(time.time()) + 30,
                    reason_code="stage_retry_scheduled") is False
                assert await store.finish(
                    jid, status=JOB_QUEUED, reason_code="resume",
                    recovery=True) is False
                row = await store.get(jid)
                assert row["status"] == JOB_FAILED
                assert row["reason_code"] == before["reason_code"]
                assert row["error_code"] == before["error_code"]
                assert row["next_retry_at"] is None

                # Даже строка, оказавшаяся queued (например, raw-запись), не
                # может быть claim'нута в running при защитном маркере.
                jid2 = await store.enqueue(owner="qnd.test", kind="k2")
                await self._mark_delivery_unknown(d, jid2, mode=mode)
                assert await store.mark_running(jid2) is False
                assert (await store.get(jid2))["status"] == JOB_QUEUED
            finally:
                await d.close()

    @pytest.mark.asyncio
    async def test_media_recovery_path_cannot_requeue_delivery_unknown(
            self, tmp_path):
        """F-S5A-02: caller-supplied reason не отменяет durable-маркер."""
        d = await _db(tmp_path, name="s5a_media.db")
        try:
            store = TaskJobStore(d)
            jid = await store.enqueue(owner="vision.media",
                                      kind=mca_vision.VISION_JOB_KIND,
                                      max_attempts=4)
            await store.mark_running(jid)
            await self._mark_delivery_unknown(d, jid, mode="both")
            await _stale_running(store, jid)
            fence_before = int((await store.get(jid))["fencing_token"] or 0)

            summary = await mr.watchdog_sweep(
                d, store=store, kind=mca_vision.VISION_JOB_KIND)
            row = await store.get(jid)
            assert summary["worker_lost"] == 1
            assert summary["requeued"] == 0
            assert summary["actions"][0]["action"] == "none"
            assert summary["actions"][0]["reason"] == "delivery_unknown"
            assert summary["actions"][0]["status"] == "reconcile_required"
            assert row["status"] == JOB_INTERRUPTED
            assert row["reason_code"] == "delivery_unknown"
            assert row["error_code"] == "delivery_unknown"
            assert row["next_retry_at"] is None
            assert int(row["fencing_token"] or 0) == fence_before + 1

            # Прямой вызов с «обычной» caller-reason тоже не возобновляет.
            action = await mr.recover_job(d, store, jid,
                                          reason="worker_lost")
            assert action["action"] == "none"
            assert action["status"] == "reconcile_required"
            assert (await store.get(jid))["status"] == JOB_INTERRUPTED
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_control_retry_and_resume_block_delivery_unknown(
            self, tmp_path):
        """F-S5A-03: guard проверяет reason_code И error_code, retry и resume."""
        for mode in ("both", "reason", "error"):
            d = await _db(tmp_path, name=f"s5a_ctrl_{mode}.db")
            try:
                store = TaskJobStore(d)
                jid = await store.enqueue(owner="archive", kind="important")
                await store.mark_running(jid)
                assert await store.finish(jid, status=JOB_FAILED) is True
                await self._mark_delivery_unknown(d, jid, mode=mode)
                for action in ("retry", "resume"):
                    res = await mt.control_action(
                        d, store, action=action, job_id=jid, actor=1)
                    assert res["status"] == "reconcile_required", (mode, action)
                row = await store.get(jid)
                assert row["status"] == JOB_FAILED
                assert row["reason_code"] == (
                    "delivery_unknown" if mode in ("both", "reason") else None)
                assert row["error_code"] == (
                    "delivery_unknown" if mode in ("both", "error") else None)
            finally:
                await d.close()


class TestIncidentLifecycle:
    """W-05: авто-resolve по фактическому терминалу; resolved не reopen молча."""

    @pytest.mark.asyncio
    async def test_auto_resolve_only_after_all_linked_jobs_terminal(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            j1 = await _running_job(store, owner="qnd.test", kind="k",
                                    max_attempts=3, checkpoint=True)
            j2 = await _running_job(store, owner="qnd.test", kind="k",
                                    max_attempts=3, checkpoint=True)
            # Оба stale — один инцидент (fingerprint owner/stage/reason).
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 1
            incident_id = rows[0]["incident_id"]
            assert rows[0]["resolved_at"] is None
            assert set(json.loads(rows[0]["jobs_json"])) == {j1, j2}

            # Один job завершён, второй ещё queued → инцидент активен.
            assert await store.mark_running(j1) is True
            jr = await store.get(j1)
            assert await store.finish(j1, status=JOB_COMPLETED,
                                      fencing_token=jr["fencing_token"]) is True
            result = await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert rows[0]["incident_id"] == incident_id
            assert rows[0]["resolved_at"] is None
            assert result["incident_reconcile"]["pending"] == 1

            # Второй job терминален → следующий sweep закрывает инцидент.
            assert await store.mark_running(j2) is True
            jr2 = await store.get(j2)
            assert await store.finish(j2, status=JOB_FAILED,
                                      reason_code="terminal",
                                      fencing_token=jr2["fencing_token"]) is True
            result = await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 1                       # история сохранена
            assert rows[0]["incident_id"] == incident_id
            assert rows[0]["resolved_at"] is not None
            assert "jobs_terminal" in rows[0]["resolution_evidence"]
            assert rows[0]["severity"] == "ERROR"       # severity не снижена
            assert result["incident_reconcile"]["resolved"] == 1
            assert await inc.active_incidents(d) == []
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_interrupted_job_keeps_incident_active(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _running_job(store, owner="qnd.test", kind="k",
                                     max_attempts=5)
            await wd.sweep(d, job_store=store)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 1
            assert rows[0]["resolved_at"] is None
            assert (await store.get(jid))["status"] == JOB_INTERRUPTED
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_missing_linked_job_is_inconclusive(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            r = await inc.open_or_update(
                d, process_id="watchdog.jobs", pipeline_type="qnd.test",
                stage="takeover", reason_code="worker_lost",
                severity=inc.SEVERITY_ERROR, job_id="no_such_job")
            assert r["status"] == "created"
            result = await inc.reconcile_linked_incidents(
                d, store, process_id="watchdog.jobs")
            assert result["inconclusive"] == 1
            assert result["resolved"] == 0
            assert len(await inc.active_incidents(d)) == 1
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_resolved_incident_not_silently_reopened(self, tmp_path):
        d = await _db(tmp_path)
        try:
            kwargs = dict(process_id="watchdog.jobs",
                          pipeline_type="qnd.test", stage="takeover",
                          reason_code="worker_lost",
                          severity=inc.SEVERITY_ERROR, job_id="job-x")
            first = await inc.open_or_update(d, **kwargs)
            assert first["status"] == "created"
            assert await inc.resolve(d, first["incident_id"],
                                     evidence="verified manual") is True
            # Повторное наблюдение того же fingerprint не переоткрывает
            # строку: создаётся НОВАЯ, старая история/evidence нетронуты.
            second = await inc.open_or_update(d, **kwargs)
            assert second["status"] == "reopened"
            assert second["incident_id"] != first["incident_id"]
            rows = await _incident_rows(d)
            assert len(rows) == 2
            old = [r for r in rows
                   if r["incident_id"] == first["incident_id"]][0]
            assert old["resolved_at"] is not None
            assert old["resolution_evidence"] == "verified manual"
            assert old["repeat_count"] == 1
            active = await inc.active_incidents(d)
            assert len(active) == 1
            assert active[0]["incident_id"] == second["incident_id"]
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_new_cycle_after_auto_resolve_keeps_history(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            owner, kind = "qnd.test", "k"
            j1 = await _running_job(store, owner=owner, kind=kind,
                                    max_attempts=5)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 1
            first_id = rows[0]["incident_id"]
            # Терминальный итог job (recovery-путь) → авто-resolve.
            assert await store.finish(j1, status=JOB_FAILED,
                                      reason_code="closed", recovery=True)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert rows[0]["resolved_at"] is not None
            # Новый stale-job того же owner — новая строка, старая закрыта.
            await _running_job(store, owner=owner, kind=kind, max_attempts=5)
            await wd.sweep(d, job_store=store)
            rows = await _incident_rows(d)
            assert len(rows) == 2
            old = [r for r in rows if r["incident_id"] == first_id][0]
            assert old["resolved_at"] is not None
        finally:
            await d.close()


class TestIncidentServiceObservability:
    """W-10 (partial): отказ/выключение наблюдаемы, без рекурсии."""

    @pytest.mark.asyncio
    async def test_failure_is_logged_and_counted_without_recursion(
            self, tmp_path, monkeypatch, caplog):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            await _running_job(store, owner="qnd.test", kind="k",
                               max_attempts=5)
            before = wd.incident_outcome_totals()["failed"]

            async def _boom(*_a, **_kw):
                raise RuntimeError("incident db down")

            monkeypatch.setattr(inc, "open_or_update", _boom)
            with caplog.at_level(logging.WARNING,
                                 logger="services.mca_watchdog"):
                result = await wd.sweep(d, job_store=store)

            assert result["incident_outcomes"]["failed"] == 1
            assert result["incidents"] == 0
            assert await _incident_rows(d) == []      # рекурсии нет
            assert wd.incident_outcome_totals()["failed"] == before + 1
            assert any("incident registration failed" in rec.message
                       for rec in caplog.records)
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_disabled_is_distinguished_from_failed(
            self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            await _running_job(store, owner="qnd.test", kind="k",
                               max_attempts=5)
            monkeypatch.setattr(mca_gates, "incidents_enabled",
                                lambda: False)
            result = await wd.sweep(d, job_store=store)
            assert result["incident_outcomes"]["disabled"] == 1
            assert result["incident_outcomes"]["failed"] == 0
            assert result["incidents"] == 0
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_created_and_updated_counters(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            await _running_job(store, owner="qnd.test", kind="k1",
                               max_attempts=5)
            await _running_job(store, owner="qnd.test", kind="k2",
                               max_attempts=5)
            result = await wd.sweep(d, job_store=store)
            # Одна строка инцидента (owner/stage/reason), не два "new".
            assert result["incident_outcomes"]["created"] == 1
            assert result["incident_outcomes"]["updated"] == 1
            assert result["incidents"] == 1
            rows = await _incident_rows(d)
            assert len(rows) == 1
            assert rows[0]["repeat_count"] == 2
        finally:
            await d.close()
