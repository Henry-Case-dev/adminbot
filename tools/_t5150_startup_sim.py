# -*- coding: utf-8 -*-
"""T-5150r startup simulation: prod-подобный старт v32 -> v33 с полным логом
миграционной цепочки (guard -> DDL -> book). Прецедент _t5126_prod_dbcheck.py.

Локальная имитация прод-старта T-5150: БД с данными (умеренный объём),
user_version=32, книга с применённой v32 — затем РЕАЛЬНЫЙ
`DatabaseService.initialize()` (наш backup-guard с VACUUM INTO + read-back
и шаг v33). Вывод: полный INFO-след раннера + верификация user_version/book.
Повторный прогон — no-op (идемпотентность retry-деплоя).

Usage: python tools/_t5150_startup_sim.py [--rows N] [--keep]
Лог: plans/features/mca-20-temporal-factcheck/startup_sim_t5150r.log
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "plans/features/mca-20-temporal-factcheck/startup_sim_t5150r.log"


def _build_v32_db(path: Path, rows: int) -> None:
    """Прод-подобная БД: схема + книга v32 + объём данных в smart_messages."""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    try:
        from services.database import DatabaseService, _SCHEMA_MIGRATIONS_DDL
        conn.executescript(DatabaseService._SCHEMA_SQL)
        conn.execute(_SCHEMA_MIGRATIONS_DDL)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at, "
            "checksum) VALUES (32, 'media_vision', strftime('%s','now'), '')")
        conn.execute("PRAGMA user_version = 32")
        now = int(time.time())
        batch = [(i, -100000 - (i % 50), f"msg-{i} " + "x" * 400, now - i)
                 for i in range(rows)]
        conn.executemany(
            "INSERT INTO smart_messages (user_id, chat_id, text, timestamp) "
            "VALUES (?, ?, ?, ?)", batch)
        conn.commit()
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"[sim] v32 DB built: rows={rows} size={size_mb:.1f}MB "
              f"user_version=32 book=media_vision")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=60000,
                    help="строк smart_messages в v32-БД (объём для VACUUM)")
    ap.add_argument("--keep", action="store_true", help="не удалять sim-БД")
    args = ap.parse_args()

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")])

    db_path = ROOT / "_t5150_sim_prodlike.db"
    _build_v32_db(db_path, args.rows)

    from services.database import DatabaseService

    for attempt in (1, 2):
        print(f"[sim] ===== initialize() run #{attempt} =====")
        svc = DatabaseService(str(db_path))
        t0 = time.monotonic()
        try:
            import asyncio
            asyncio.run(svc.initialize())
            dur = time.monotonic() - t0
            loop = asyncio.new_event_loop()
            try:
                uv = loop.run_until_complete(
                    _fetchone(svc, "PRAGMA user_version"))
                book = loop.run_until_complete(_fetchall(
                    svc, "SELECT version, name FROM schema_migrations "
                         "WHERE version >= 32 ORDER BY version"))
            finally:
                loop.close()
            print(f"[sim] run #{attempt}: initialize OK in {dur:.1f}s | "
                  f"user_version={uv[0]} | book>=32: "
                  f"{[tuple(r) for r in book]}")
        finally:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(svc.close())
            finally:
                loop.close()
    if not args.keep and db_path.exists():
        db_path.unlink()
    print(f"[sim] full log -> {LOG_PATH}")
    return 0


async def _fetchone(svc, sql):
    cur = await svc.db.execute(sql)
    return await cur.fetchone()


async def _fetchall(svc, sql):
    cur = await svc.db.execute(sql)
    return await cur.fetchall()


if __name__ == "__main__":
    sys.exit(main())
