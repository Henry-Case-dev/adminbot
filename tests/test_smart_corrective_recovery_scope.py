"""SMART-CORRECTIVE-01 S5B-RECOVERY — owner/kind-скоуп recovery, heartbeat,
progress/overdue и queued-диагностика.

Покрывает owner-findings W-03/W-04/W-06/W-08/W-09 (см.
`plans/features/smart-corrective-01/architecture-plan.md` §7.2/§7.4):

* W-04: `recover_stale` ограничен owner/kind — vision-watchdog не прерывает
  чужие `running`-задачи; свои vision-задачи восстанавливаются;
* W-06: `MCA_JOB_HEARTBEAT_SECONDS` реально используется производителями
  (`TaskSupervisor.run`, initiative observer, vision worker) — живая долгая
  задача не считается потерявшей владельца; media-job получает явный
  `deadline_at`;
* W-08: `mark_running` ставит baseline `progress_at` по контракту kind;
  `progress_at IS NULL` больше не делает job невидимой; пороги прогресса
  берутся по kind (`llm/video/archive/default`); `overdue()` участвует в
  takeover и диагностике;
* W-09: queued-задачи классифицируются (scheduled retry / ожидание срока /
  специализированный владелец / зависание) и НЕ забираются takeover'ом;
* W-03: после recovery действует bounded-политика attempt/max_attempts,
  `delivery_unknown` защищён (после S5A guards), дублей работы/доставки нет.

TEST-LIFECYCLE: CONTRACT/REGRESSION (S5B-RECOVERY)
R17: только коды/числа/идентификаторы.
"""
import json
import time

import pytest

import services.database as dbmod
from services import mca_events as me
from services import mca_gates
from services import mca_trace as mt
from services import mca_vision
from services import media_execution as mx
from services import media_readiness as mr
from services import mca_watchdog as wd
from services.database import DatabaseService
from services.task_supervisor import (JOB_INTERRUPTED, JOB_QUEUED,
                                      JOB_RUNNING, JobHeartbeat,
                                      TaskJobStore, TaskSupervisor,
                                      heartbeat_period_seconds)


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


async def _db(tmp_path, name="s5b_recovery.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _make_running(store, *, owner: str, kind: str, payload=None,
                        max_attempts: int = 3, heartbeat_age: int | None = None,
                        progress_age: int | None = None,
                        deadline_in: int | None = None,
                        job_id: str | None = None) -> str:
    jid = await store.enqueue(
        owner=owner, kind=kind, job_id=job_id, max_attempts=max_attempts,
        payload=(json.dumps(payload) if payload is not None else None),
        deadline_at=(int(time.time()) + deadline_in)
        if deadline_in is not None else None)
    assert await store.mark_running(jid) is True
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


async def _row(store, jid):
    return await store.get(jid)


async def _incidents(db):
    cursor = await db.db.execute("SELECT * FROM mca_incidents")
    return [dict(r) for r in await cursor.fetchall()]


class TestScopedRecovery:
    """W-04: чужой running-job не трогается, vision-job восстанавливается."""

    @pytest.mark.asyncio
    async def test_vision_watchdog_leaves_foreign_running_job_untouched(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            foreign = await _make_running(
                store, owner="memory", kind="graphrag_rebuild",
                payload={"cursor": "c1", "processed": 5}, heartbeat_age=9000,
                progress_age=9000)
            before = await _row(store, foreign)

            summary = await mr.watchdog_sweep(d, store=store)

            after = await _row(store, foreign)
            # чужой job жив и не получил fencing/терминал/инцидент молча
            assert after["status"] == JOB_RUNNING
            assert after["fencing_token"] == before["fencing_token"]
            assert after["reason_code"] is None
            assert summary["worker_lost"] == 0
            assert await _incidents(d) == []

            # прицельный scoped-recover_stale тоже не берёт чужой kind
            lost = await store.recover_stale(
                stale_after_seconds=60,
                kinds=(mca_vision.VISION_JOB_KIND,))
            assert foreign not in lost
            assert (await _row(store, foreign))["status"] == JOB_RUNNING
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_scoped_recover_stale_requeues_only_matching_kind(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            vision = await _make_running(
                store, owner="vision.media", kind=mca_vision.VISION_JOB_KIND,
                payload={"asset_id": "a1", "chat_id": 1}, max_attempts=4,
                heartbeat_age=9000)
            memory = await _make_running(
                store, owner="memory", kind="embedding_migration",
                payload={"cursor": "c2"}, heartbeat_age=9000)

            lost = await store.recover_stale(
                stale_after_seconds=60,
                kinds=(mca_vision.VISION_JOB_KIND,))
            assert lost == [vision]
            assert (await _row(store, vision))["status"] == JOB_INTERRUPTED
            assert (await _row(store, memory))["status"] == JOB_RUNNING

            # owner-скоуп работает независимо от kind-скоупа
            lost_by_owner = await store.recover_stale(
                stale_after_seconds=60, owners=("memory",))
            assert lost_by_owner == [memory]
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_vision_watchdog_recovers_its_own_stale_job(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(
                store, owner="vision.media", kind=mca_vision.VISION_JOB_KIND,
                payload={"asset_id": "a2", "chat_id": 1}, max_attempts=4,
                heartbeat_age=9000)
            before = await _row(store, jid)

            summary = await mr.watchdog_sweep(d, store=store)

            after = await _row(store, jid)
            assert summary["worker_lost"] == 1
            assert summary["requeued"] == 1
            assert after["status"] == JOB_QUEUED
            assert after["next_retry_at"] is not None
            assert int(after["fencing_token"]) > int(before["fencing_token"])
            # дублированной работы нет: ровно одна активная строка
            active = await store.active()
            assert [r["job_id"] for r in active] == [jid]
            # старый владелец не может завершить отобранную задачу
            assert await store.finish(
                jid, status="completed",
                fencing_token=before["fencing_token"]) is False
        finally:
            await d.close()


class TestHeartbeatContract:
    """W-06: документированный интервал heartbeat реально применяется."""

    def test_heartbeat_period_uses_documented_setting(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "job_heartbeat_seconds", lambda: 7)
        assert heartbeat_period_seconds() == 7
        monkeypatch.setattr(mca_gates, "job_heartbeat_seconds", lambda: 0)
        assert heartbeat_period_seconds() == 1     # нижняя граница

    @pytest.mark.asyncio
    async def test_mark_running_sets_progress_baseline_by_kind(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            progress_job = await _make_running(
                store, owner="asap8b01", kind="initiative.observe")
            row = await _row(store, progress_job)
            assert row["progress_at"] is not None
            assert int(row["progress_at"]) >= int(row["heartbeat_at"]) - 1

            for kind, owner in ((mca_vision.VISION_JOB_KIND, "vision.media"),
                                ("media_job", "image"),
                                ("meme.pending_publish", "meme.initiative")):
                jid = await _make_running(store, owner=owner, kind=kind)
                assert (await _row(store, jid))["progress_at"] is None, kind
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_supervisor_run_keeps_heartbeat_alive(self, tmp_path,
                                                        monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            sup = TaskSupervisor()
            monkeypatch.setattr(mca_gates, "job_heartbeat_seconds", lambda: 1)
            beats = {"n": 0}
            real_heartbeat = store.heartbeat

            async def counting_heartbeat(job_id, **kwargs):
                beats["n"] += 1
                return await real_heartbeat(job_id, **kwargs)

            monkeypatch.setattr(store, "heartbeat", counting_heartbeat)

            async def _slow():
                await __import__("asyncio").sleep(1.3)
                return "done"

            rec = await sup.run(_slow, owner="asap8b01",
                                kind="initiative.observe", job_store=store,
                                emit_event=False)
            row = await _row(store, rec.job_id)
            assert row["status"] == "completed"
            assert beats["n"] >= 1, "периодический heartbeat не выполнялся"
            assert int(row["heartbeat_at"]) >= int(row["created_at"])
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_live_supervised_job_is_not_marked_stale(self, tmp_path,
                                                           monkeypatch):
        """W-06 acceptance: живая долгая задача с heartbeat не помечается
        stale и не забирается takeover'ом."""
        import asyncio
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            sup = TaskSupervisor()
            monkeypatch.setattr(mca_gates, "job_heartbeat_seconds", lambda: 1)
            started = asyncio.Event()

            async def _slow():
                started.set()
                await asyncio.sleep(1.6)
                return "done"

            task = asyncio.ensure_future(sup.run(
                _slow, owner="asap8b01", kind="initiative.observe",
                job_store=store, emit_event=False))
            await asyncio.wait_for(started.wait(), timeout=2)
            await asyncio.sleep(1.3)          # > 1 периода heartbeat
            result = await wd.sweep(d, job_store=store)
            active = await store.active()
            jid = active[0]["job_id"]
            assert jid not in result["stale"]
            assert jid not in result["takeover"]["discovered"]
            assert (await store.get(jid))["status"] == JOB_RUNNING
            await task
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_job_heartbeat_stops_on_exit(self, tmp_path, monkeypatch):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(store, owner="asap8b01",
                                      kind="initiative.observe")
            monkeypatch.setattr(mca_gates, "job_heartbeat_seconds", lambda: 1)
            hb = JobHeartbeat.start(store, jid, interval_seconds=1)
            assert hb is not None
            await __import__("asyncio").sleep(1.1)
            await hb.stop()
            beats_after_stop = hb.beats
            await __import__("asyncio").sleep(1.2)
            assert hb.beats == beats_after_stop     # фон не продолжается
            assert hb._task is None
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_media_job_carries_explicit_deadline(self, tmp_path):
        d = await _db(tmp_path)
        try:
            jid, state = await mx.begin_media_job(
                d, operation="image_generate", provider="p", model="m",
                prompt="p", chat_id=1, deadline_s=120)
            assert jid
            row = await TaskJobStore(d).get(jid)
            assert row is not None
            assert row["deadline_at"] is not None
            assert int(row["deadline_at"]) > int(time.time())
        finally:
            await d.close()


class TestProgressAndOverdue:
    """W-08: контракт прогресса по kind, видимость NULL-progress, overdue."""

    @pytest.mark.asyncio
    async def test_null_progress_running_job_detected_by_kind_contract(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            stalled_job = await _make_running(
                store, owner="asap8b01", kind="initiative.observe")
            await d.db.execute(
                "UPDATE task_jobs SET progress_at = NULL, created_at = ? "
                "WHERE job_id = ?", (int(time.time()) - 9999, stalled_job))
            await d.db.commit()
            heartbeat_only = await _make_running(
                store, owner="vision.media", kind=mca_vision.VISION_JOB_KIND,
                heartbeat_age=1)

            stalled = await wd.progress_stalled_jobs(d)
            ids = {r["job_id"] for r in stalled}
            assert stalled_job in ids          # NULL progress больше не «невидим»
            assert heartbeat_only not in ids   # долгий внешний вызов — не stalled

            contract = await wd.running_contract_jobs(d)
            hb_ids = {r["job_id"] for r in contract["heartbeat_only"]}
            assert heartbeat_only in hb_ids
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_progress_thresholds_are_kind_specific(self, tmp_path,
                                                         monkeypatch):
        from config.settings import settings
        assert mca_gates.job_progress_stall_seconds("initiative.observe") == \
            settings.MCA_PROGRESS_STALL_LLM_SECONDS
        assert mca_gates.job_progress_stall_seconds("graphrag_rebuild") == \
            settings.MCA_PROGRESS_STALL_ARCHIVE_SECONDS
        assert mca_gates.job_progress_stall_seconds("media_job") == \
            settings.MCA_PROGRESS_STALL_DEFAULT_SECONDS
        # прежний stage-контракт mca_trace сохранён
        assert mca_gates.progress_stall_seconds("llm") == \
            settings.MCA_PROGRESS_STALL_LLM_SECONDS

        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            llm_job = await _make_running(
                store, owner="asap8b01", kind="initiative.observe",
                progress_age=settings.MCA_PROGRESS_STALL_LLM_SECONDS + 60)
            archive_job = await _make_running(
                store, owner="memory", kind="graphrag_rebuild",
                progress_age=settings.MCA_PROGRESS_STALL_LLM_SECONDS + 60)
            stalled = {r["job_id"] for r in await wd.progress_stalled_jobs(d)}
            assert llm_job in stalled           # llm-порог превышен
            assert archive_job not in stalled   # archive-порог (3600) не превышен
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_overdue_running_job_drives_takeover(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(
                store, owner="asap8b01", kind="initiative.observe",
                payload={"cursor": "c1", "processed": 2}, max_attempts=3,
                heartbeat_age=1, deadline_in=-60)
            before = await _row(store, jid)
            assert before["status"] == JOB_RUNNING

            result = await wd.sweep(d, job_store=store)

            after = await _row(store, jid)
            assert jid in result["overdue"]["running"]
            assert after["status"] == JOB_QUEUED
            assert after["reason_code"] == "deadline_exceeded"
            assert after["next_retry_at"] is not None
            assert int(after["fencing_token"]) == int(
                before["fencing_token"]) + 1
            assert jid in result["takeover"]["recovered"]
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_overdue_queued_job_is_diagnosed_not_taken_over(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await store.enqueue(
                owner="image", kind="media_job", max_attempts=1,
                payload=json.dumps({"cursor": "x"}),
                deadline_at=int(time.time()) - 120)
            before = await _row(store, jid)

            result = await wd.sweep(d, job_store=store)

            after = await _row(store, jid)
            assert after["status"] == JOB_QUEUED
            assert after["fencing_token"] == before["fencing_token"]
            assert jid in [i["job_id"] for i in result["queued"]["overdue"]]
            assert jid not in result["takeover"]["recovered"]
        finally:
            await d.close()


class TestQueuedDiagnosis:
    """W-09: диагностические корзины без takeover/requeue."""

    @pytest.mark.asyncio
    async def test_queued_buckets_distinguish_wait_retry_dependency_hang(
            self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            now = int(time.time())
            retry = await store.enqueue(owner="asap8b01",
                                        kind="initiative.observe",
                                        next_retry_at=now + 120)
            deadline = await store.enqueue(owner="image", kind="media_job",
                                           deadline_at=now + 300)
            owner_managed = await store.enqueue(
                owner="vision.media", kind=mca_vision.VISION_JOB_KIND)
            young = await store.enqueue(owner="mca16",
                                        kind="experience.review")
            hang = await store.enqueue(owner="mca16",
                                       kind="experience.review")
            await d.db.execute(
                "UPDATE task_jobs SET created_at = ?, updated_at = ? "
                "WHERE job_id IN (?, ?)",
                (now - 9999, now - 9999, owner_managed, hang))
            await d.db.commit()

            buckets = wd.classify_queued_jobs(await wd.queued_jobs(d), now=now)
            assert [i["job_id"] for i in buckets["scheduled_retry"]] == [retry]
            assert [i["job_id"] for i in buckets["deadline_pending"]] == \
                [deadline]
            assert owner_managed in [i["job_id"]
                                     for i in buckets["owner_managed"]]
            assert young in [i["job_id"] for i in buckets["normal_wait"]]
            assert [i["job_id"] for i in buckets["hang"]] == [hang]

            # полный sweep: диагностика есть, состояния не меняются
            result = await wd.sweep(d, job_store=store)
            for jid in (retry, deadline, owner_managed, young, hang):
                row = await _row(store, jid)
                assert row["status"] == JOB_QUEUED
                assert int(row["fencing_token"] or 0) == 0
            assert hang in [i["job_id"] for i in result["queued"]["hang"]]
            queued_incidents = [r for r in await _incidents(d)
                                if r["stage"] == "queued"]
            assert len(queued_incidents) == 1
            assert queued_incidents[0]["severity"] == "WARN"
            assert "stage_queued" in str(queued_incidents[0]["fingerprint"])
            assert hang in json.loads(queued_incidents[0]["jobs_json"])
            assert result["takeover"]["recovered"] == []
        finally:
            await d.close()


class TestBoundedRecoverySafety:
    """W-03 (совместно с S5A): bounded attempts и защита delivery_unknown."""

    @pytest.mark.asyncio
    async def test_takeover_respects_attempt_bounds_on_overdue(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            exhausted = await _make_running(
                store, owner="asap8b01", kind="initiative.observe",
                payload={"cursor": "c1"}, max_attempts=2, heartbeat_age=9000)
            await d.db.execute(
                "UPDATE task_jobs SET attempt = 2 WHERE job_id = ?",
                (exhausted,))
            await d.db.commit()

            result = await wd.sweep(d, job_store=store)
            row = await _row(store, exhausted)
            assert row["status"] == "failed"
            assert row["reason_code"] == "attempts_exhausted"
            assert exhausted in result["takeover"]["failed"]
            assert exhausted not in result["takeover"]["recovered"]
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_delivery_unknown_survives_scope_and_overdue(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(
                store, owner="vision.media", kind=mca_vision.VISION_JOB_KIND,
                payload={"asset_id": "a9", "chat_id": 1}, max_attempts=4,
                heartbeat_age=9000, deadline_in=-60)
            await d.db.execute(
                "UPDATE task_jobs SET reason_code = 'delivery_unknown', "
                "error_code = 'delivery_unknown' WHERE job_id = ?", (jid,))
            await d.db.commit()
            before = await _row(store, jid)

            await wd.sweep(d, job_store=store)
            await mr.watchdog_sweep(d, store=store)

            row = await _row(store, jid)
            assert row["status"] == JOB_INTERRUPTED
            assert row["reason_code"] == "delivery_unknown"
            assert row["error_code"] == "delivery_unknown"
            assert int(row["fencing_token"]) > int(before["fencing_token"])
            assert row["next_retry_at"] is None
            # слепого повтора доставки нет: resume запрещён guard'ом
            action = await mr.recover_job(d, store, jid, reason="worker_lost")
            assert action["status"] == "reconcile_required"
            assert (await _row(store, jid))["status"] == JOB_INTERRUPTED
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_error_only_delivery_unknown_blocks_overdue_takeover(
            self, tmp_path):
        """F-S5B-01 (Reviewer blocker): маркер только в `error_code` даёт тот
        же запрет recovery/requeue, что и маркер в `reason_code`.

        Точный сценарий ревью: checkpoint + stale heartbeat + истёкший
        `deadline_at` + `reason_code=NULL` + `error_code='delivery_unknown'`.
        `takeover_stale(include_overdue=True)` не должен вернуть
        recovered/requeued, стирать маркер или ставить `next_retry_at`;
        scoped `recover_stale` обязан сохранить маркер в обоих полях."""
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(
                store, owner="vision.media", kind=mca_vision.VISION_JOB_KIND,
                payload={"asset_id": "a10", "chat_id": 1}, max_attempts=5,
                heartbeat_age=9000, deadline_in=-120)
            await d.db.execute(
                "UPDATE task_jobs SET reason_code = NULL, "
                "error_code = 'delivery_unknown' WHERE job_id = ?", (jid,))
            await d.db.commit()
            before = await _row(store, jid)
            assert before["reason_code"] is None

            # (1) прямой overdue-takeover: маркер в error_code блокирует requeue
            records = await store.takeover_stale(
                stale_after_seconds=60, retry_delay_seconds=15,
                include_overdue=True)
            record = next(r for r in records if r["job_id"] == jid)
            row = await _row(store, jid)
            assert record["outcome"] == "no_change"
            assert record["action"] == "reconcile_required"
            assert record["reason"] == "delivery_unknown"
            assert row["status"] == JOB_INTERRUPTED
            assert row["reason_code"] == "delivery_unknown"
            assert row["error_code"] == "delivery_unknown"
            assert row["next_retry_at"] is None
            assert int(row["fencing_token"]) == int(
                before["fencing_token"]) + 1

            # (2) полный sweep не «восстанавливает» строку повторно
            result = await wd.sweep(d, job_store=store)
            row = await _row(store, jid)
            assert row["status"] == JOB_INTERRUPTED
            assert row["error_code"] == "delivery_unknown"
            assert row["next_retry_at"] is None
            assert jid not in result["takeover"]["recovered"]
            assert (await wd.recover_job(d, store, jid))["status"] == \
                "reconcile_required"
            assert (await _row(store, jid))["status"] == JOB_INTERRUPTED

            # (3) lease-revocation (scoped recover_stale) тоже сохраняет маркер
            jid2 = await _make_running(
                store, owner="vision.media", kind=mca_vision.VISION_JOB_KIND,
                payload={"asset_id": "a11", "chat_id": 1}, max_attempts=5,
                heartbeat_age=9000)
            await d.db.execute(
                "UPDATE task_jobs SET reason_code = NULL, "
                "error_code = 'delivery_unknown' WHERE job_id = ?", (jid2,))
            await d.db.commit()
            lost = await store.recover_stale(
                stale_after_seconds=60, kinds=(mca_vision.VISION_JOB_KIND,))
            assert jid2 in lost
            row2 = await _row(store, jid2)
            assert row2["status"] == JOB_INTERRUPTED
            assert row2["reason_code"] == "delivery_unknown"
            assert row2["error_code"] == "delivery_unknown"
            assert (await mr.recover_job(d, store, jid2,
                                         reason="worker_lost")
                    )["status"] == "reconcile_required"
            assert (await _row(store, jid2))["status"] == JOB_INTERRUPTED
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_takeover_never_duplicates_active_work(self, tmp_path):
        d = await _db(tmp_path)
        try:
            store = TaskJobStore(d)
            jid = await _make_running(
                store, owner="asap8b01", kind="initiative.observe",
                payload={"cursor": "c1"}, max_attempts=4, heartbeat_age=9000,
                job_id="fixed-job-1")
            result = await wd.sweep(d, job_store=store)
            assert result["takeover"]["recovered"] == [jid]
            again = await store.enqueue(
                owner="asap8b01", kind="initiative.observe",
                coalesce_key=None)
            assert again != jid                 # новый enqueue — новая строка
            active = [r["job_id"] for r in await store.active()]
            assert active.count(jid) == 1        # восстановление не размножило job
        finally:
            await d.close()
