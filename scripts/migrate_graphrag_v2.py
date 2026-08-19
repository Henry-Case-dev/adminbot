"""Epic 46 (55.3): прод-миграция GraphRAG v2. Запуск на ОСТАНОВЛЕННОМ боте:
venv/bin/python scripts/migrate_graphrag_v2.py [db_path]  (default: settings.DB_PATH)
Идемпотентный; печатает отчёт (user_version до/после, колонки)."""
import asyncio
import sys
from pathlib import Path

# Запуск из scripts/ добавляет в sys.path scripts/, а не корень репо —
# явно кладём корень, чтобы импортировался пакет services.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.database import DatabaseService


async def _main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    db = DatabaseService(db_path) if db_path else DatabaseService(
        __import__("config.settings", fromlist=["settings"]).settings.DB_PATH)
    await db.initialize()                    # busy_timeout + WAL + схема + _migrate_graphrag_v2
    cursor = await db.db.execute("PRAGMA user_version")
    row = await cursor.fetchone()
    print(f"user_version = {row[0]}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(_main())
