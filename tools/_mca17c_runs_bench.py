"""Разовый замер read-агрегата /runs (TH-4/R-b): 500 runs × 8 событий.
Запуск: PYTHONPATH=. .venv\\Scripts\\python.exe tools/_mca17c_runs_bench.py
"""
import asyncio
import os
import tempfile
import time

from services import mca_events as me
from services.database import DatabaseService


async def main() -> None:
    me.reset_pending()
    path = os.path.join(tempfile.gettempdir(), "mca17c_bench.db")
    if os.path.exists(path):
        os.remove(path)
    db = DatabaseService(path)
    await db.initialize()
    for i in range(500):
        rid = f"bench-{i:05d}"
        for s in range(7):
            me.emit_mca_event("STAGE_DONE", outcome="success",
                              component="summary", stage=f"s{s}",
                              pipeline_run_id=rid,
                              pipeline_type="summary.window",
                              pipeline_version="1", span_id=f"{rid}-{s}",
                              event_sequence=s, chat_id=-100500)
        me.emit_mca_event("SUMMARY_RUN_DONE", outcome="success",
                          component="summary", pipeline_run_id=rid,
                          pipeline_type="summary.window",
                          pipeline_version="1")
        if i % 2 == 1:
            await me.flush_events(db)
    await me.flush_events(db)
    # коррелированные подзапросы = 2 на run — главный фактор; меряем
    from web.api.oversight_router import _scan_runs
    t0 = time.perf_counter()
    runs = await _scan_runs(db, since_ts=0, until_ts=0, pipeline_type=None,
                            model=None, chat_id=None)
    dt = time.perf_counter() - t0
    print(f"runs={len(runs)} scan_seconds={dt:.3f} "
          f"per_run_ms={dt * 1000 / max(1, len(runs)):.2f}")
    t0 = time.perf_counter()
    await db.db.execute(
        "SELECT outcome_kind, COUNT(*) FROM mca_experience_episodes "
        "WHERE created_at BETWEEN 0 AND 9999999999 GROUP BY outcome_kind")
    await db.db.execute(
        "SELECT status, COUNT(*) FROM mca_lessons GROUP BY status")
    dt2 = time.perf_counter() - t0
    print(f"funnel_aggregates_seconds={dt2:.4f} (пустые таблицы)")
    await db.close()
    me.reset_pending()
    if os.path.exists(path):
        os.remove(path)


if __name__ == "__main__":
    asyncio.run(main())
