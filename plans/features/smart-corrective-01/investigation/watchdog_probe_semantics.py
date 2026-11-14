"""Read-only probe of deployed watchdog/incident semantics (dev codebase copy).

Deployed 2.58.200 code == DEV master services/mca_watchdog.py (sha256 match),
so local probes against the DEV tree exercise the shipped logic.

No production access, no schema change: temporary SQLite DBs only.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["MCA_TELEMETRY_SPOOL_PATH"] = os.path.join(HERE, "spool.jsonl")

import services.database as dbmod  # noqa: E402
from services import mca_events as me  # noqa: E402
from services import mca_gates  # noqa: E402
from services import mca_incidents as inc  # noqa: E402
from services import mca_trace as mt  # noqa: E402
from services import mca_watchdog as wd  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.task_supervisor import TaskJobStore  # noqa: E402

dbmod._LOCK_BACKOFF = 0.0
OUT: dict = {}


async def _db(name: str) -> DatabaseService:
    d = DatabaseService(os.path.join(HERE, name))
    await d.initialize()
    return d


async def _stale_job(store, owner: str, kind: str, age: int = 9999) -> str:
    jid = await store.enqueue(owner=owner, kind=kind)
    assert await store.mark_running(jid) is True
    now = int(time.time())
    await store._db.db.execute(
        "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?", (now - age, jid))
    await store._db.db.commit()
    return jid


async def _running_with_progress(store, owner: str, kind: str, *,
                                 hb_age: int, prog_age: int | None) -> str:
    jid = await store.enqueue(owner=owner, kind=kind)
    assert await store.mark_running(jid) is True
    now = int(time.time())
    await store._db.db.execute(
        "UPDATE task_jobs SET heartbeat_at = ?, progress_at = ? WHERE job_id = ?",
        (now - hb_age, (now - prog_age) if prog_age is not None else None, jid))
    await store._db.db.execute(
        "UPDATE task_jobs SET created_at = ? WHERE job_id = ?", (now - 7200, jid))
    await store._db.db.commit()
    return jid


async def _inc_rows(db):
    cur = await db.db.execute(
        "SELECT incident_id, fingerprint, pipeline_type, stage, severity, "
        "repeat_count, resolved_at, jobs_json FROM mca_incidents ORDER BY first_ts")
    return [dict(r) for r in await cur.fetchall()]


async def probe_a_event_payload_fields():
    """Does the emitted WATCHDOG_TAKEOVER actually carry job_ids?"""
    ev = me.build_event(
        "WATCHDOG_TAKEOVER", outcome="success", component="watchdog",
        stage="takeover", reason_code="takeover_recovered",
        job_ids=["jobA", "jobB"])
    OUT["A_build_event_keys"] = sorted(ev.keys()) if ev else None
    OUT["A_job_ids_survived"] = bool(ev and "job_ids" in ev)


async def probe_b_duplicate_emission():
    d = await _db("b_dup.db")
    captured: list[dict] = []

    async def cap(name, reason, **fields):
        captured.append({"event": name, "reason": reason, **fields})

    orig = wd._emit
    wd._emit = cap
    try:
        store = TaskJobStore(d)
        owners = [("asap8b01", "initiative.observe"), ("qnd.event", "initiative.event"),
                  ("mca16", "experience.review")]
        ids = [await _stale_job(store, o, k) for o, k in owners]
        res = await wd.sweep(d, job_store=store)
    finally:
        wd._emit = orig
    takeovers = [e for e in captured if e["event"] == "WATCHDOG_TAKEOVER"]
    OUT["B_stale"] = len(res["stale"])
    OUT["B_takeover_events"] = len(takeovers)
    OUT["B_takeover_payloads"] = [
        {"reason": e["reason"], "job_ids": e.get("job_ids")} for e in takeovers]
    OUT["B_recovered"] = res["recovered"]
    OUT["B_incidents_counter"] = res["incidents"]
    OUT["B_job_states"] = [(await store.get(i))["status"] for i in ids]
    OUT["B_incident_rows"] = [
        {k: r[k] for k in ("pipeline_type", "stage", "severity", "repeat_count",
                           "resolved_at", "jobs_json")}
        for r in await _inc_rows(d)]
    await d.close()


async def probe_c_failed_recovery_claims_success():
    d = await _db("c_fail.db")
    captured: list[dict] = []

    async def cap(name, reason, **fields):
        captured.append({"event": name, "reason": reason, **fields})

    orig_emit, orig_sweep = wd._emit, None
    wd._emit = cap
    try:
        store = TaskJobStore(d)
        jid = await _stale_job(store, "memory", "archive.rebuild")

        async def boom(*a, **kw):
            raise RuntimeError("injected recover_stale failure")

        store.recover_stale = boom  # type: ignore[assignment]
        res = await wd.sweep(d, job_store=store)
    finally:
        wd._emit = orig_emit
    takeovers = [e for e in captured if e["event"] == "WATCHDOG_TAKEOVER"]
    OUT["C_stale"] = res["stale"]
    OUT["C_recovered"] = res["recovered"]
    OUT["C_takeover_events"] = len(takeovers)
    OUT["C_takeover_reasons"] = [e["reason"] for e in takeovers]
    OUT["C_job_status_after_failed_recovery"] = (await store.get(jid))["status"]
    OUT["C_incident_count"] = len(await inc.active_incidents(d))
    await d.close()


async def probe_d_no_store_and_empty_recovery():
    d = await _db("d_nostore.db")
    captured: list[dict] = []

    async def cap(name, reason, **fields):
        captured.append({"event": name, "reason": reason, **fields})

    orig = wd._emit
    wd._emit = cap
    try:
        store = TaskJobStore(d)
        await _stale_job(store, "image", "media.image")
        res = await wd.sweep(d, job_store=None)   # no store -> no recovery
    finally:
        wd._emit = orig
    OUT["D_recovered"] = res["recovered"]
    OUT["D_takeovers"] = len([e for e in captured if e["event"] == "WATCHDOG_TAKEOVER"])
    await d.close()


async def probe_e_incident_lifecycle():
    d = await _db("e_lifecycle.db")
    store = TaskJobStore(d)
    jid = await _stale_job(store, "asap8b01", "initiative.observe")
    await wd.sweep(d, job_store=store)
    rows = await _inc_rows(d)
    OUT["E_after_takeover"] = [(r["stage"], r["severity"], r["repeat_count"],
                                r["resolved_at"]) for r in rows]
    # real job finishes successfully later (deployed callers do NOT pass fencing)
    await store.finish(jid, status="completed", reason_code=None)
    OUT["E_job_status_after_late_success"] = (await store.get(jid))["status"]
    OUT["E_active_incidents_after_success"] = len(await inc.active_incidents(d))
    # manual resolve, then a later takeover of the same owner reopens it
    ok = await inc.resolve(d, rows[0]["incident_id"], evidence="probe")
    OUT["E_manual_resolve_ok"] = ok
    OUT["E_active_after_manual_resolve"] = len(await inc.active_incidents(d))
    await _stale_job(store, "asap8b01", "initiative.observe")
    await wd.sweep(d, job_store=store)
    rows2 = await _inc_rows(d)
    OUT["E_after_reopen"] = [(r["stage"], r["severity"], r["repeat_count"],
                              r["resolved_at"]) for r in rows2]
    await d.close()


async def probe_f_progress_gap():
    d = await _db("f_progress.db")
    store = TaskJobStore(d)
    no_progress = await _running_with_progress(
        store, "asap8b01", "initiative.observe", hb_age=1, prog_age=None)
    with_progress = await _running_with_progress(
        store, "mca16", "experience.review", hb_age=1, prog_age=7200)
    stale = await wd.stale_jobs(d)
    stalled = await wd.progress_stalled_jobs(d)
    OUT["F_stale"] = [r["job_id"] for r in stale]
    OUT["F_stalled"] = [r["job_id"] for r in stalled]
    OUT["F_running_heartbeat_alive_no_progress_detected"] = any(
        r["job_id"] == no_progress for r in stalled + stale)
    OUT["F_worker_with_old_progress_detected"] = any(
        r["job_id"] == with_progress for r in stalled)
    await d.close()


async def probe_g_vision_watchdog_foreign_owner():
    try:
        from services import media_readiness as mr
    except ImportError:
        OUT["G_skipped"] = "media_readiness absent in this tree"
        return
    d = await _db("g_vision.db")
    store = TaskJobStore(d)
    jid = await _stale_job(store, "memory", "archive.rebuild", age=200)
    summary = await mr.watchdog_sweep(d, store=store)
    row = await store.get(jid)
    OUT["G_summary"] = {k: summary[k] for k in ("checked", "requeued", "terminal",
                                               "worker_lost", "stalled")}
    OUT["G_foreign_job_status"] = row["status"]
    OUT["G_foreign_job_reason"] = row["reason_code"]
    OUT["G_incidents_after_silent_foreign_takeover"] = len(
        await inc.active_incidents(d))
    await d.close()


async def probe_h_repeated_batches():
    d = await _db("h_repeat.db")
    store = TaskJobStore(d)
    # two stale jobs of the SAME owner in one batch -> one incident, +2 repeats
    await _stale_job(store, "vision.media", "vision.analyze")
    await _stale_job(store, "vision.media", "vision.analyze")
    res = await wd.sweep(d, job_store=store)
    rows = await _inc_rows(d)
    OUT["H_result_incidents_counter"] = res["incidents"]
    OUT["H_incident_rows"] = [(r["pipeline_type"], r["repeat_count"],
                               r["jobs_json"]) for r in rows]
    await d.close()


async def probe_k_progress_stall_incident():
    d = await _db("k_stall.db")
    store = TaskJobStore(d)
    jid = await _running_with_progress(
        store, "mca16", "experience.review", hb_age=1, prog_age=7200)
    await wd.sweep(d, job_store=store)
    rows = await _inc_rows(d)
    OUT["K_rows"] = [(r["pipeline_type"], r["stage"], r["severity"],
                      r["repeat_count"], r["jobs_json"]) for r in rows]
    OUT["K_job_status"] = (await store.get(jid))["status"]
    await d.close()


async def probe_i_queued_invisible():
    d = await _db("i_queued.db")
    store = TaskJobStore(d)
    jid = await store.enqueue(owner="summary", kind="summary.secondary")
    now = int(time.time())
    await d.db.execute("UPDATE task_jobs SET created_at = ?, updated_at = ? "
                       "WHERE job_id = ?", (now - 86400, now - 86400, jid))
    await d.db.commit()
    stale = await wd.stale_jobs(d)
    stalled = await wd.progress_stalled_jobs(d)
    store2 = TaskJobStore(d)
    overdue = await store2.overdue()
    OUT["I_queued_age_seconds"] = 86400
    OUT["I_stale"] = len(stale)
    OUT["I_stalled"] = len(stalled)
    OUT["I_overdue"] = len(overdue)
    OUT["I_telemetry_freshness"] = await wd.telemetry_freshness(d)
    await d.close()


async def main():
    await probe_a_event_payload_fields()
    await probe_b_duplicate_emission()
    await probe_c_failed_recovery_claims_success()
    await probe_d_no_store_and_empty_recovery()
    await probe_e_incident_lifecycle()
    await probe_f_progress_gap()
    await probe_g_vision_watchdog_foreign_owner()
    await probe_h_repeated_batches()
    await probe_i_queued_invisible()
    await probe_k_progress_stall_incident()
    print(json.dumps({"gates": {"watchdog": mca_gates.heartbeat_watchdog_enabled(),
                                "incidents": mca_gates.incidents_enabled()},
                      "results": OUT}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
