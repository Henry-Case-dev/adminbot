"""Epic 60 (63.3, D245): прод-миграция v3 (user_version 2→3).
Запуск на ОСТАНОВЛЕННОМ боте:
venv/bin/python scripts/migrate_epic60_v3.py [db_path]  (default: settings.DB_PATH)
Идемпотентный (повторный запуск — no-op); печатает отчёт (user_version
до/после, новые таблицы, v3-колонки graph_facts). Прецеденты
migrate_graphrag_v2.py (Epic 46, 55.3) / migrate_direct_chat_v2.py (Epic 50).
"""
import asyncio
import sqlite3
import sys
from pathlib import Path

# Запуск из scripts/ добавляет в sys.path scripts/, а не корень репо —
# явно кладём корень, чтобы импортировался пакет services.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.database import DatabaseService  # noqa: E402

_V3_TABLES = (
    "throttle_state", "bot_replies", "user_prefs", "embedding_cache",
    "chat_running_summary", "graph_fact_compressions", "protected_facts",
)


def _read_user_version(db_path: str) -> int:
    """PRAGMA user_version отдельным соединением (прецедент REVISE S1
    migrate_direct_chat_v2.py)."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        return row[0] if row is not None else 0
    finally:
        conn.close()


async def _main() -> None:
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = __import__(
            "config.settings", fromlist=["settings"]).settings.DB_PATH
    before = _read_user_version(db_path)
    db = DatabaseService(db_path)
    await db.initialize()     # WAL + busy_timeout + synchronous + схема + миграции (→3)
    cursor = await db.db.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    after = row[0]
    cursor = await db.db.execute(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        f"({','.join('?' for _ in _V3_TABLES)})",
        _V3_TABLES,
    )
    tables = sorted(r["name"] for r in await cursor.fetchall())
    cursor = await db.db.execute("PRAGMA table_info(graph_facts)")
    gf_cols = {r["name"] for r in await cursor.fetchall()}
    v3_cols_ok = {"weight", "status", "last_confirmed_at", "supersedes"} <= gf_cols
    print(f"user_version: {before} -> {after}")
    print(f"v3 tables: {', '.join(tables)}")
    print(f"graph_facts v3 columns (weight/status/last_confirmed_at/supersedes): {v3_cols_ok}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
