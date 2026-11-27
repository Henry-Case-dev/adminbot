"""Discriminating experiment: does a CPU-heavy SQL on aiosqlite's shared
connection stall the asyncio event loop (GIL held during sqlite3_step)?

Run with the project venv. No repo imports needed.
"""
import asyncio
import time

import aiosqlite

HEAVY = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c "
         "WHERE x < {n}) SELECT count(*) FROM c")


async def main() -> None:
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    await conn.executemany("INSERT INTO t (v) VALUES (?)",
                           [("x" * 100,) for _ in range(50)])
    await conn.commit()

    stop = False
    gaps: list[float] = []

    async def ticker(interval: float = 0.02) -> None:
        loop = asyncio.get_running_loop()
        last = loop.time()
        while not stop:
            await asyncio.sleep(interval)
            now = loop.time()
            gaps.append(now - last)
            last = now

    async def heavy_query() -> tuple[int, float]:
        t0 = time.perf_counter()
        cur = await conn.execute(HEAVY.format(n=60_000_000))
        await cur.fetchall()
        return 0, time.perf_counter() - t0

    task = asyncio.create_task(ticker())
    _, dur = await heavy_query()
    stop = True
    await task
    print(f"heavy_sql_seconds={dur:.2f} ticks={len(gaps)} "
          f"max_loop_gap={max(gaps):.3f}s p95={sorted(gaps)[max(0, int(len(gaps) * 0.95) - 1)]:.3f}s")
    print("VERDICT:", "LOOP-BLOCKED-BY-SQL" if max(gaps) > 0.5 * dur
          else "loop free during SQL")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
