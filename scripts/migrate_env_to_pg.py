"""Epic 85 (84.12.2, T-637) — полный экспорт .env/settings → bot_settings.

Однократный ИДЕМПОТЕНТНЫЙ экспорт ВСЕХ регулируемых параметров (по каталогу
services/param_catalog.py) в PostgreSQL. Эффективное значение = settings-дефолт,
переопределённый env-строкой (ровно логика Settings: env-файл грузится ДО
импорта config.settings).

Запуск:
    python scripts/migrate_env_to_pg.py --dry-run
    python scripts/migrate_env_to_pg.py [--env-file .env] [--force]
        [--only-category limits,models] [--exclude-keys summary_,chat_]

Порядок на проде (84.12.3, Фаза 0): postgres healthy → --dry-run (сверка) →
без --force (сид ДО первого старта бота с фичей) → restart.

Флаги:
  --env-file PATH      файл окружения (дефолт CWD .env)
  --dry-run            печать плана БЕЗ записи (секреты — только configured)
  --force              перезапись существующих (DO UPDATE SET value, updated_at)
  --only-category X    фильтр категорий (через запятую)
  --exclude-keys a,b   исключить ключи по префиксу env-имени/PG-ключа

R17: значения секретов НИКОГДА не печатаются (ни в dry-run, ни в логах).
"""
import argparse
import asyncio
import getpass
import json
import logging
import os
import socket
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

logger = logging.getLogger(__name__)

UPSERT_DO_NOTHING = """
    INSERT INTO bot_settings (key, value, category)
    VALUES ($1, $2, $3)
    ON CONFLICT (key) DO NOTHING
"""
UPSERT_FORCE = """
    INSERT INTO bot_settings (key, value, category)
    VALUES ($1, $2, $3)
    ON CONFLICT (key) DO UPDATE
    SET value = EXCLUDED.value, category = EXCLUDED.category,
        updated_at = now()
"""


def _inserted_count(result: str | None) -> bool:
    """F17: строгий разбор command-tag «INSERT 0 n» — строка вставлена
    (n=1; при --force DO UPDATE тоже возвращает 0 1)."""
    parts = (result or "").split()
    return bool(
        len(parts) == 3 and parts[0].upper() == "INSERT"
        and parts[1].isdigit() and parts[2].isdigit()
        and int(parts[2]) == 1
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Экспорт .env/settings → bot_settings (PostgreSQL)")
    parser.add_argument("--env-file", default=".env",
                        help="путь к .env (дефолт: .env в CWD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="печать плана без записи в БД")
    parser.add_argument("--force", action="store_true",
                        help="перезапись существующих значений")
    parser.add_argument("--only-category", default="",
                        help="фильтр категорий через запятую")
    parser.add_argument("--exclude-keys", default="",
                        help="исключить ключи по префиксу (через запятую)")
    return parser.parse_args(argv)


def _build_plan(settings, args) -> list[dict]:
    """План экспорта: {pg_key, category, value, secret, env_name, source}."""
    from services.param_catalog import iter_migratable
    from services.pg_db import coerce_catalog_value

    only = {c.strip().lower() for c in args.only_category.split(",")
            if c.strip()}
    excludes = [e.strip().lower() for e in args.exclude_keys.split(",")
                if e.strip()]

    def excluded(spec) -> bool:
        for prefix in excludes:
            if (spec.env_name or "").lower().startswith(prefix) \
                    or spec.pg_key.lower().startswith(prefix):
                return True
        return False

    plan: list[dict] = []
    for spec in iter_migratable():
        if only and spec.category not in only:
            continue
        if excluded(spec):
            continue
        source = "env" if os.environ.get(spec.env_name) is not None else "default"
        raw = getattr(settings, spec.settings_field)
        value = coerce_catalog_value(spec, raw)
        plan.append({
            "pg_key": spec.pg_key,
            "category": spec.category,
            "env_name": spec.env_name,
            "value": value,
            "secret": spec.secret,
            "source": source,
        })
    return plan


def _masked(spec_row: dict) -> str:
    """R17: значение секрета НИКОГДА не печатается — только факт."""
    value = spec_row["value"]
    if spec_row["secret"]:
        return "configured" if value else "empty"
    if isinstance(value, str) and len(value) > 60:
        return f"{value[:57]}..."
    return json.dumps(value, ensure_ascii=False)


async def _run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # env-файл ДО импорта config.settings (логика Settings: env > дефолт).
    env_path = Path(args.env_file)
    if env_path.exists():
        load_dotenv(env_path, override=True)
        logger.info("[migrate] env loaded: %s", env_path)
    else:
        logger.warning("[migrate] env-файл не найден: %s (только дефолты)",
                       env_path)

    from config.settings import settings  # noqa: E402 (после load_dotenv)
    from services.pg_db import PgDatabase  # noqa: E402

    plan = _build_plan(settings, args)

    print(f"[migrate] план: {len(plan)} параметров")
    for row in plan:
        print(f"  [{row['category']}] {row['pg_key']} "
              f"<- {row['env_name']} (source={row['source']}, "
              f"value={_masked(row)})")

    if args.dry_run:
        print("[migrate] dry-run: записи НЕ выполнялись")
        return 0

    pg = PgDatabase()
    await pg.connect()
    if pg.pool is None:
        logger.error("[migrate] POSTGRES_DSN пуст/недоступен — экспорт невозможен")
        return 1
    await pg.init(seed_settings=False)  # только DDL (84.12.3: env > сид-дефолт)

    sql = UPSERT_FORCE if args.force else UPSERT_DO_NOTHING
    created = 0
    skipped = 0
    by_category: Counter = Counter()
    # F20: при --force перезаписи логируются с указанием источника (host/user)
    updated_by = f"{getpass.getuser()}@{socket.gethostname()}"
    async with pg.pool.acquire() as conn:
        for row in plan:
            result = await conn.execute(
                sql, row["pg_key"], json.dumps(row["value"]), row["category"])
            if _inserted_count(result):
                created += 1
                by_category[row["category"]] += 1
                if args.force:
                    logger.info("[migrate] force rewrite | key=%s | updated_by=%s",
                                row["pg_key"], updated_by)
            else:
                skipped += 1
    await pg.close()

    print(f"[migrate] created={created} skipped={skipped} (force={args.force})")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat}: {count}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    sys.exit(asyncio.run(_run()))
