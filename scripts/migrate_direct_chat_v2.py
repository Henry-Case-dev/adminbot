"""Epic 50 (58.7, D201): прод-миграция DirectChat v2 (user_version 1→2).
Запуск на ОСТАНОВЛЕННОМ боте:
venv/bin/python scripts/migrate_direct_chat_v2.py [db_path]  (default: settings.DB_PATH)
Идемпотентный; печатает отчёт (user_version до/после). Прецедент
migrate_graphrag_v2.py (Epic 46, 55.3).

REVISE S1: user_version ДО initialize читается ОТДЕЛЬНЫМ sqlite3-соединением
(DatabaseService.db ещё None до initialize — AttributeError).
"""
import asyncio
import sqlite3
import sys
from pathlib import Path

# Запуск из scripts/ добавляет в sys.path scripts/, а не корень репо —
# явно кладём корень, чтобы импортировался пакет services.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.database import DatabaseService  # noqa: E402


def _read_user_version(db_path: str) -> int:
    """PRAGMA user_version отдельным соединением (не через DatabaseService —
    до initialize у него нет коннекшена). Для несуществующего файла sqlite3
    создаёт пустую БД (user_version 0) — initialize создаст остальное."""
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
    await db.initialize()     # busy_timeout + WAL + схема + миграции (1→2)
    cursor = await db.db.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    after = row[0]
    cursor = await db.db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'")
    row = await cursor.fetchone()
    has_bot_direct = bool(row and row["sql"] and "bot_direct_reply" in row["sql"])
    cursor = await db.db.execute("PRAGMA table_info(smart_messages)")
    tg_column = any(r["name"] == "tg_message_id" for r in await cursor.fetchall())
    print(f"user_version: {before} -> {after}")
    print(f"graph_facts CHECK includes 'bot_direct_reply': {has_bot_direct}")
    print(f"smart_messages.tg_message_id present: {tg_column}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
