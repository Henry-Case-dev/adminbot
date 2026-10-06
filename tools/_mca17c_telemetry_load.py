"""Разовый замер нагрузки телеметрии mca-17c (T-5194, spec §6/D16).

Воспроизводимый прогон: N терминальных+span событий через контракт
(build_event → flush_events), замер числа событий/роста хранилища,
bounded-буфера и writer-пути. Не pytest (запуск руками):
    .venv\\Scripts\\python.exe tools/_mca17c_telemetry_load.py
R17: секретов нет; файл временный (tools/_*).
"""
import asyncio
import os
import tempfile
import time

from services import mca_events as me
from services.database import DatabaseService

N_RUNS = 500
EV_PER_RUN = 8          # span-стадии + терминал → 4000 событий


async def main() -> None:
    me.reset_pending()
    path = os.path.join(tempfile.gettempdir(), "mca17c_load.db")
    if os.path.exists(path):
        os.remove(path)
    db = DatabaseService(path)
    await db.initialize()
    t0 = time.perf_counter()
    total = 0
    for i in range(N_RUNS):
        rid = f"loadrun-{i:05d}"
        for s in range(EV_PER_RUN - 1):
            me.emit_mca_event(
                "STAGE_DONE", outcome="success", component="summary",
                stage=f"stage{s}", pipeline_run_id=rid,
                pipeline_type="summary.window", pipeline_version="1",
                span_id=f"{rid}-{s}", event_sequence=s,
                duration_ms=100 + s, chat_id=-100500)
            total += 1
        me.emit_mca_event(
            "SUMMARY_RUN_DONE", outcome="success", component="summary",
            pipeline_run_id=rid, pipeline_type="summary.window",
            pipeline_version="1", duration_ms=900)
        total += 1
        # периодический flush — как фоновый контур в проде (flush-контур
        # забирает буфер до переполнения; здесь — каждые 2 runs).
        if i % 2 == 1:
            await me.flush_events(db)
    t_build = time.perf_counter() - t0
    pending_after_build = me.pending_size()
    t1 = time.perf_counter()
    await me.flush_events(db)
    t_flush = time.perf_counter() - t1
    size = os.path.getsize(path)
    print(f"events_built={total}")
    print(f"build_seconds={t_build:.3f}")
    print(f"flush_seconds={t_flush:.3f}")
    print(f"pending_after_build={pending_after_build} (cap={me._PENDING_MAX})")
    print(f"dropped_total={me.dropped_total()}")
    print(f"db_bytes={size}")
    print(f"db_bytes_per_event={size / total:.0f}")
    cur = await db.db.execute("SELECT COUNT(*) c FROM mca_events")
    row = await cur.fetchone()
    print(f"rows_in_db={row['c']}")
    await db.close()
    me.reset_pending()
    if os.path.exists(path):
        os.remove(path)


if __name__ == "__main__":
    asyncio.run(main())
