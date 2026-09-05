"""Раунд 7 (chat-lore-management-v2, T-782, G1) — сид легаси-лора в PG.

Идемпотентный перенос константы `CHAT_LORE_2661910336` (services/chat_lore.py,
дословно) в `manual_lore` профиля `-1002661910336` (spec §3.12/FR-10):

    INSERT INTO chat_profiles (chat_id, manual_lore, auto_enabled, is_active)
    VALUES ($1, $текст, TRUE, TRUE)
    ON CONFLICT (chat_id) DO NOTHING

Правила:
  * строка уже есть и manual_lore НЕПУСТОЙ → НЕ затирать (ручные правки
    приоритетнее; отчёт existing-manual-not-empty);
  * повторный прогон — no-op (skipped);
  * без side-эффектов на SQLite (RUNTIME WARNING: SQLite не трогаем);
  * NOTIFY после INSERT не требуется (кэш пуст до старта бота; §3.12).

Запуск (шаг @DevOps при деплое, I2):
    python scripts/seed_chat_lore.py
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.chat_lore import (  # noqa: E402
    CHAT_LORE_2661910336,
    CHAT_LORE_TARGET_CHAT_ID,
)

logger = logging.getLogger(__name__)

SEED_INSERT_SQL = """
    INSERT INTO chat_profiles (chat_id, manual_lore, auto_enabled, is_active)
    VALUES ($1, $2, TRUE, TRUE)
    ON CONFLICT (chat_id) DO NOTHING
"""


async def seed_chat_lore(pg=None) -> dict:
    """Идемпотентный сид легаси-лора. `pg` — PgDatabase/мок (для тестов);
    None → собственный коннект по POSTGRES_DSN + идемпотентный DDL.

    Возврат: {"chat_id", "status": inserted|skipped|existing-manual-not-empty,
    "inserted": bool}. Fail: исключение (собственный коннект невозможен →
    RuntimeError)."""
    chat_id = CHAT_LORE_TARGET_CHAT_ID
    text = CHAT_LORE_2661910336
    own = pg is None
    if own:
        from services.pg_db import PgDatabase
        pg = PgDatabase()
        await pg.connect()
        if pg.pool is None:
            raise RuntimeError(
                "[seed_chat_lore] POSTGRES_DSN пуст/недоступен — сид невозможен")
        await pg.init(seed_settings=False)   # только DDL (идемпотентно)
    try:
        async with pg.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT manual_lore FROM chat_profiles WHERE chat_id = $1",
                chat_id)
            if row is not None and (row["manual_lore"] or "").strip():
                logger.info(
                    "[seed_chat_lore] существующий непустой manual_lore — "
                    "НЕ затираю | chat_id=%s", chat_id)
                return {"chat_id": chat_id,
                        "status": "existing-manual-not-empty",
                        "inserted": False}
            result = await conn.execute(SEED_INSERT_SQL, chat_id, text)
            inserted = _inserted(result)
            status = "inserted" if inserted else "skipped"
            logger.info(
                "[seed_chat_lore] %s | chat_id=%s | chars=%d",
                status, chat_id, len(text))
            return {"chat_id": chat_id, "status": status,
                    "inserted": inserted}
    finally:
        if own:
            await pg.close()


async def seed_chat_lore_profile(store) -> dict:
    """Функция для тестов/деплоя: сид через ChatLoreStore (pg из store.pg).
    Тот же идемпотентный сид, что и seed_chat_lore(pg)."""
    return await seed_chat_lore(store.pg)


def _inserted(tag: str | None) -> bool:
    """Разбор command-tag «INSERT 0 1» → вставлена строка."""
    parts = (tag or "").split()
    return (len(parts) == 3 and parts[0].upper() == "INSERT"
            and parts[1].isdigit() and parts[2].isdigit()
            and int(parts[2]) > 0)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Сид легаси-лора чата -1002661910336 в PG (chat_profiles)")
    parser.add_argument("--verbose", action="store_true",
                        help="INFO-логирование (дефолт: WARNING)")
    return parser.parse_args(argv)


async def _run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    try:
        report = await seed_chat_lore()
    except Exception as exc:
        print(f"[seed_chat_lore] ОШИБКА: {exc}", file=sys.stderr)
        return 1
    print(f"[seed_chat_lore] chat_id={report['chat_id']} | "
          f"status={report['status']} | inserted={report['inserted']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
