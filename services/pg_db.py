"""Epic 85 (84.3/84.14.1) — PostgreSQL-коннектор (asyncpg, без ORM).

Идемпотентный DDL при старте (CREATE TABLE IF NOT EXISTS) + сиды
(INSERT … ON CONFLICT DO NOTHING): роли v2 (84.14.3), КРИТИЧНЫЕ telegram_id
(84.3), стартовый bot_settings по каталогу services/param_catalog.py
(84.12.3 belt-and-suspenders: дефолты категорий models/limits/flags/reactions/
memory из settings + prompts из код-канонов; секреты НЕ сидятся — пусто =
уровень каскада выключен, ровно старое поведение пустого .env). Существующие
значения bot_settings НИКОГДА не перезаписываются (ON CONFLICT DO NOTHING).
"""
import importlib
import json
import logging
import os

import asyncpg

from config.settings import settings
from services.param_catalog import (
    CATEGORY_FLAGS,
    CATEGORY_LIMITS,
    CATEGORY_MEMORY,
    CATEGORY_MODELS,
    CATEGORY_PROMPTS,
    CATEGORY_REACTIONS,
    ParamSpec,
    REGISTRY,
)

logger = logging.getLogger(__name__)

# ── DDL (идемпотентный; канон 84.3 + дельта 84.14.1) ────────────────────────
DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS bot_settings (
        key        TEXT PRIMARY KEY,
        value      JSONB NOT NULL,
        category   TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bot_settings_category"
    " ON bot_settings (category)",
    """
    CREATE TABLE IF NOT EXISTS bot_roles (
        role_name   TEXT PRIMARY KEY,
        permissions JSONB NOT NULL DEFAULT '{}',
        is_custom   BOOLEAN NOT NULL DEFAULT false
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bot_admins (
        telegram_id BIGINT PRIMARY KEY,
        role_name   TEXT NOT NULL REFERENCES bot_roles (role_name)
                    ON UPDATE CASCADE ON DELETE RESTRICT,
        added_by    BIGINT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bot_admins_role ON bot_admins (role_name)",
    # ── Epic 85 (84.11.3, T-627): график аптайма (heartbeat 60с) ──
    """
    CREATE TABLE IF NOT EXISTS uptime_events (
        id      BIGSERIAL PRIMARY KEY,
        ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
        status  TEXT NOT NULL DEFAULT 'up'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_uptime_events_ts ON uptime_events (ts)",
)

# ── Сиды ────────────────────────────────────────────────────────────────────
# Роли v2 (84.14.3): permissions-объект вместо плоского массива 84.3.
DEFAULT_ROLES: tuple[dict, ...] = (
    {"role_name": "admin", "permissions": {"wildcard": True}, "is_custom": False},
    {
        "role_name": "moderator",
        "permissions": {
            "sections": ["limits"],
            "actions": ["control.restart", "control.stop", "control.start"],
        },
        "is_custom": False,
    },
    {"role_name": "user", "permissions": {}, "is_custom": False},
)

# КРИТИЧНО (84.3/84.14.3): telegram_id БЕЗ изменений.
DEFAULT_ADMINS: tuple[tuple[int, str], ...] = (
    (5885953495, "admin"),
    (1313107079, "moderator"),
    (134812796, "moderator"),
)

INSERT_ROLE_SQL = """
    INSERT INTO bot_roles (role_name, permissions, is_custom)
    VALUES ($1, $2, $3)
    ON CONFLICT (role_name) DO NOTHING
"""
INSERT_ADMIN_SQL = """
    INSERT INTO bot_admins (telegram_id, role_name, added_by)
    VALUES ($1, $2, NULL)
    ON CONFLICT (telegram_id) DO NOTHING
"""
INSERT_SETTING_SQL = """
    INSERT INTO bot_settings (key, value, category)
    VALUES ($1, $2, $3)
    ON CONFLICT (key) DO NOTHING
"""

# Категории belt-and-suspenders сида дефолтов (84.12.3): БЕЗ ключей-секретов.
# memory (фаза 2, T-755): стартовый сид memory.infinite_retention=false.
SEED_CATEGORIES: frozenset[str] = frozenset(
    {CATEGORY_PROMPTS, CATEGORY_MODELS, CATEGORY_LIMITS, CATEGORY_FLAGS,
     CATEGORY_REACTIONS, CATEGORY_MEMORY}
)


def coerce_catalog_value(spec: ParamSpec, value):
    """Приведение значения Settings к JSONB-совместимому виду (84.12.2)."""
    if value is None:
        return None
    if spec.type == "json":
        if isinstance(value, (tuple, list, set)):
            return [v for v in value]
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value
    if spec.type == "bool":
        return bool(value)
    if spec.type == "int":
        # Толерантно (2026-09-03): пустая строка/мусор → None, не падаем
        # (напр. YOUTUBE_TRANSCRIPT_PROXY_RETRIES уходит в сид как "").
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    if spec.type == "float":
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    return value


def resolve_code_source(source: str):
    """«module.attr» → значение код-канона (промпты)."""
    module_name, attr = source.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr)


# ── ПРОД-ИНЦИДЕНТ (A): asyncpg отдаёт jsonb СТРОКОЙ JSON-текста (с кавычками).
# Каноническое решение — кодеки json/jsonb на КАЖДОМ соединении пула:
# читаем объекты (dict/list/str/int) вместо сериализованных строк.
# Encoder ИДЕМПОТЕНТНЫЙ: str (уже JSON, напр. json.dumps в INSERT-ах) проходит
# как есть — миграция/сиды не задваивают кавычки. ────────────────────────────

def _json_encoder(value) -> str:
    """Сериализация параметра: str — как есть (уже JSON), иначе json.dumps."""
    if isinstance(value, str):
        return value
    return json.dumps(value)


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Init-колбэк пула (и прямых соединений): регистрация кодеков json/jsonb."""
    for codec in ("json", "jsonb"):
        await conn.set_type_codec(
            codec, encoder=_json_encoder, decoder=json.loads,
            schema="pg_catalog")


class PgDatabase:
    """asyncpg-пул + идемпотентный DDL/сиды. Без ORM (84.3)."""

    def __init__(self, dsn: str | None = None, pool: asyncpg.Pool | None = None):
        self._dsn = dsn or os.getenv("POSTGRES_DSN")
        self._pool = pool
        self._connected = False

    @property
    def dsn(self) -> str | None:
        return self._dsn

    @property
    def pool(self) -> asyncpg.Pool | None:
        return self._pool

    async def connect(self) -> None:
        """Создать пул (min 1, max 10). Инъекция пула — для юнит-тестов.
        init-колбэк: json/jsonb-кодеки на каждом соединении пула."""
        if self._pool is not None:
            self._connected = True
            return
        if not self._dsn:
            logger.warning("[pg_db] POSTGRES_DSN пуст — PostgreSQL недоступен")
            return
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=10,
            command_timeout=10,
            init=_init_connection,
        )
        self._connected = True
        logger.info("[pg_db] asyncpg pool created (json/jsonb codecs)")

    async def init(self, seed_settings: bool = True) -> None:
        """DDL + сиды. Идемпотентно (повторный запуск без ошибок).
        seed_settings=False — только DDL + роли/админы (миграция .env должна
        выполниться ДО старта, чтобы env-значения не проиграли дефолтному
        сиду: 84.12.3, деплой-чеклист Фаза 0)."""
        if self._pool is None:
            logger.warning("[pg_db] init skipped: pool отсутствует")
            return
        async with self._pool.acquire() as conn:
            for statement in DDL_STATEMENTS:
                await conn.execute(statement)
            logger.info("[pg_db] DDL ok (4 таблицы + индексы)")
            await self._seed_roles(conn)
            await self._seed_admins(conn)
            if seed_settings:
                await self._seed_settings(conn)

    async def _seed_roles(self, conn) -> None:
        for role in DEFAULT_ROLES:
            await conn.execute(
                INSERT_ROLE_SQL,
                role["role_name"],
                json.dumps(role["permissions"]),
                role["is_custom"],
            )
        logger.info("[pg_db] roles seeded: %s",
                    [r["role_name"] for r in DEFAULT_ROLES])

    async def _seed_admins(self, conn) -> None:
        for telegram_id, role_name in DEFAULT_ADMINS:
            await conn.execute(INSERT_ADMIN_SQL, telegram_id, role_name)
        logger.info("[pg_db] admins seeded: %s",
                    [a[0] for a in DEFAULT_ADMINS])

    async def _seed_settings(self, conn) -> None:
        """Стартовый bot_settings по каталогу (84.12.3): дефолты настроек
        (не секреты) + prompts из код-канонов. ON CONFLICT DO NOTHING."""
        count = 0
        for spec in REGISTRY.values():
            if spec.category is None or spec.category not in SEED_CATEGORIES:
                continue
            if spec.code_source is not None:
                try:
                    value = resolve_code_source(spec.code_source)
                except Exception:
                    logger.warning("[pg_db] code_source не резолвится: %s | %s",
                                   spec.pg_key, spec.code_source, exc_info=True)
                    continue
            elif spec.settings_field is not None and not spec.secret:
                value = coerce_catalog_value(
                    spec, getattr(settings, spec.settings_field))
            else:
                continue  # секреты НЕ сидятся (пусто = уровень выключен)
            await conn.execute(
                INSERT_SETTING_SQL, spec.pg_key, json.dumps(value), spec.category)
            count += 1
        logger.info("[pg_db] starter bot_settings seeded: %d (ON CONFLICT DO NOTHING)",
                    count)

    async def close(self) -> None:
        pool = self._pool
        self._pool = None
        if pool is not None:
            await pool.close()
        self._connected = False
        logger.info("[pg_db] pool closed")
