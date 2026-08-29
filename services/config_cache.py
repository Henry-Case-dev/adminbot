"""Epic 85 (84.4) — ConfigCache: in-memory кэш bot_settings/ролей/админов.

Контракт 84.4:
  * init() — retry-loop + WARNING при недоступности PG (R6: бот жив,
    SQLite-функциональность не блокируется); грузит bot_settings →
    dict[key, JSON]; кэширует роли/админов; на ПУСТОЙ bot_settings
    самозасевает дефолты (84.12.3 belt-and-suspenders, через pg_db);
    сидит content.info_how_it_works из info_text.md (84.13.2, T-638).
  * get(key, default) — sync-чтение in-memory словаря (горячие точки).
  * set/upsert(key, value, category) — PG-апсерт + память под asyncio.Lock.
  * upsert/remove_admin, upsert/delete_role — операции RBAC (POST /api/admins|
    /api/roles): PG + reload кэша; без PG → ConfigCacheUnavailableError.
  * get_all() / get_permissions(role_name) / get_role(telegram_id) / reload().

Потокобезопасность: asyncio.Lock на запись; чтение — без блокировок
(атомарная замена словаря). Без POSTGRES_DSN/PG — деградация: кэш живёт
в памяти (set без БД), бот работает на settings-дефолтах (R1).
"""
import asyncio
import datetime
import json
import logging

from config.settings import settings
from services.param_catalog import normalize_value
from services.permissions import Permissions
from services.pg_db import PgDatabase

logger = logging.getLogger(__name__)

_INIT_RETRY_ATTEMPTS = 3
_INIT_RETRY_DELAY = 2.0

_INFO_KEY = "content.info_how_it_works"


def _iso(value) -> str | None:
    """datetime/iso-строка → ISO-строка (None при отсутствии)."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _deleted_count(result: str | None) -> bool:
    """F17: строгий разбор command-tag «DELETE n» (никакого split()[-1])."""
    parts = (result or "").split()
    return bool(
        len(parts) == 2 and parts[0].upper() == "DELETE"
        and parts[1].isdigit() and int(parts[1]) > 0
    )


class ConfigCacheUnavailableError(RuntimeError):
    """Операция требует PostgreSQL, но он недоступен (R6 → 503 на уровне API)."""


class ConfigCache:
    """Единый in-memory кэш конфигурации поверх PostgreSQL (asyncpg)."""

    def __init__(self, dsn: str | None = None,
                 pg: PgDatabase | None = None,
                 retry_attempts: int = _INIT_RETRY_ATTEMPTS,
                 retry_delay: float = _INIT_RETRY_DELAY):
        self._pg = pg or PgDatabase(dsn=dsn)
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay = retry_delay
        self._lock = asyncio.Lock()
        self._settings: dict[str, object] = {}
        self._settings_updated_at: dict[str, str | None] = {}
        self._loaded_at: str | None = None          # 84.18.8: время загрузки RAM из PG
        self._roles: dict[str, dict] = {}          # role_name → {permissions, is_custom}
        self._permissions: dict[str, Permissions] = {}
        self._admins: dict[int, str] = {}          # telegram_id → role_name
        self._admins_full: dict[int, dict] = {}    # + added_by/created_at (F7)
        self._pg_available = False
        self._initialized = False

    @property
    def pg_available(self) -> bool:
        return self._pg_available

    @property
    def pg(self) -> PgDatabase:
        """PgDatabase (heartbeat/status — uptime_events)."""
        return self._pg

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def loaded_at(self) -> str | None:
        """84.18.8: ISO-время последней загрузки RAM из PG (None — PG down)."""
        return self._loaded_at

    async def init(self) -> None:
        """Загрузка при старте (R6: PG down → WARNING, бот НЕ блокируется)."""
        if self._initialized:
            return
        for attempt in range(1, self._retry_attempts + 1):
            try:
                await self._pg.connect()
                await self._pg.init()          # DDL + сиды + стартовый bot_settings
                await self._load_all()
                self._pg_available = True
                await self._seed_info_key()    # 84.13.2 (T-638): сид из info_text.md
                self._initialized = True
                logger.info("[config_cache] initialized: settings=%d roles=%d "
                            "admins=%d", len(self._settings), len(self._roles),
                            len(self._admins))
                return
            except Exception:
                logger.warning(
                    "[config_cache] PG недоступен (попытка %d/%d) — бот "
                    "работает на settings-дефолтах (R6)",
                    attempt, self._retry_attempts, exc_info=True)
                await asyncio.sleep(self._retry_delay)
        self._initialized = True
        logger.warning("[config_cache] init завершён БЕЗ PostgreSQL: "
                       "in-memory только")

    async def _load_all(self) -> None:
        """Полная перезагрузка из PG (подключает пул pg)."""
        pool = self._pg.pool
        if pool is None:
            return
        async with pool.acquire() as conn:
            settings_rows = await conn.fetch(
                "SELECT key, value, category, updated_at FROM bot_settings")
            role_rows = await conn.fetch(
                "SELECT role_name, permissions, is_custom FROM bot_roles")
            admin_rows = await conn.fetch(
                "SELECT telegram_id, role_name, added_by, created_at "
                "FROM bot_admins")
        settings_map = {
            r["key"]: normalize_value(r["key"], r["value"])
            for r in settings_rows
        }
        settings_updated = {
            r["key"]: _iso(r.get("updated_at")) for r in settings_rows}
        roles_map = {
            r["role_name"]: {
                "permissions": r["permissions"], "is_custom": r["is_custom"],
            }
            for r in role_rows
        }
        admins_map = {r["telegram_id"]: r["role_name"] for r in admin_rows}
        admins_full = {
            r["telegram_id"]: {
                "telegram_id": r["telegram_id"],
                "role_name": r["role_name"],
                "added_by": r.get("added_by"),
                "created_at": _iso(r.get("created_at")),
            }
            for r in admin_rows
        }
        async with self._lock:
            self._settings = settings_map
            self._settings_updated_at = settings_updated
            self._loaded_at = datetime.datetime.now(
                datetime.timezone.utc).isoformat()   # 84.18.8
            self._roles = roles_map
            self._admins = admins_map
            self._admins_full = admins_full
            self._permissions = {
                name: Permissions.from_dict(role["permissions"])
                for name, role in roles_map.items()
            }

    async def _seed_info_key(self) -> None:
        """84.13.2: ключа content.info_how_it_works нет → сид из info_text.md
        (текущее содержимое, которое видят пользователи) → PG. Файл-фолбек
        остаётся в InfoService (PG down)."""
        if _INFO_KEY in self._settings:
            return
        try:
            with open(settings.INFO_TEXT_FILE, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            logger.warning("[config_cache] info seed skipped: файл не читается",
                           exc_info=True)
            return
        if not text.strip():
            return
        value = {
            "html": text,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_by": settings.ADMIN_USER_ID,
        }
        await self.set(_INFO_KEY, value, "content")
        logger.info("[config_cache] seeded %s | chars=%d | updated_by=%s",
                    _INFO_KEY, len(text), value["updated_by"])

    # ── sync-чтение (горячие точки) ────────────────────────────────────────

    def get(self, key: str, default=None):
        """Синхронное чтение значения по ключу bot_settings."""
        return self._settings.get(key, default)

    def get_all(self) -> dict:
        """Снапшот всех bot_settings (копия — не мутировать)."""
        return dict(self._settings)

    def get_role(self, telegram_id: int) -> str | None:
        return self._admins.get(telegram_id)

    def get_permissions(self, role_name: str) -> Permissions | None:
        """Permissions-объект роли (None — роли нет)."""
        return self._permissions.get(role_name)

    def get_permissions_by_telegram_id(self, telegram_id: int) \
            -> Permissions | None:
        role_name = self._admins.get(telegram_id)
        if role_name is None:
            return None
        return self._permissions.get(role_name)

    def roles(self) -> dict:
        """Снапшот ролей (для API/guard'ов)."""
        return dict(self._roles)

    def admins(self) -> dict:
        """Снапшот админов: telegram_id → role_name."""
        return dict(self._admins)

    def admins_full(self) -> list[dict]:
        """F7: полные карточки админов (telegram_id/role_name/added_by/
        created_at) для GET /api/admins. При деградации — пусто."""
        return sorted(self._admins_full.values(),
                      key=lambda a: a["telegram_id"])

    def get_updated_at(self, key: str) -> str | None:
        """F7: updated_at bot_settings (из PG; in-memory set — None)."""
        return self._settings_updated_at.get(key)

    # ── запись ─────────────────────────────────────────────────────────────

    async def set(self, key: str, value, category: str) -> None:
        """Апсерт bot_settings: PG + in-memory (asyncio.Lock).
        ХОТФИКС: значение нормализуется по типу каталога — единообразие
        при hot-reload (API уже типизирует, но не доверяем форме)."""
        value = normalize_value(key, value)
        async with self._lock:
            self._settings[key] = value
            self._settings_updated_at.pop(key, None)   # in-memory → null
            if not self._pg_available or self._pg.pool is None:
                logger.debug("[config_cache] set in-memory only (PG down): %s", key)
                return
            async with self._pg.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO bot_settings (key, value, category)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, category = EXCLUDED.category,
                        updated_at = now()
                    """,
                    key, json.dumps(value), category,
                )
        logger.info("[config_cache] set | key=%s | category=%s", key, category)

    async def upsert(self, key: str, value, category: str) -> None:
        """Синоним set (контракт T-613)."""
        await self.set(key, value, category)

    # ── RBAC-операции (POST /api/admins|/api/roles) ────────────────────────

    def _require_pg(self) -> None:
        if not self._pg_available or self._pg.pool is None:
            raise ConfigCacheUnavailableError("PostgreSQL недоступен (R6)")

    async def upsert_admin(self, telegram_id: int, role_name: str,
                           added_by: int | None) -> None:
        """Назначить/сменить роль Telegram ID + reload кэша (84.5)."""
        self._require_pg()
        async with self._pg.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_admins (telegram_id, role_name, added_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (telegram_id) DO UPDATE
                SET role_name = EXCLUDED.role_name,
                    added_by = EXCLUDED.added_by
                """,
                telegram_id, role_name, added_by,
            )
        await self.reload()
        logger.info("[config_cache] admin upserted: %s → %s (by=%s)",
                    telegram_id, role_name, added_by)

    async def remove_admin(self, telegram_id: int) -> bool:
        """Удалить Telegram ID из bot_admins + reload. False — его не было."""
        self._require_pg()
        async with self._pg.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM bot_admins WHERE telegram_id = $1", telegram_id)
        removed = _deleted_count(result)
        await self.reload()
        logger.info("[config_cache] admin removed: %s (removed=%s)",
                    telegram_id, removed)
        return removed

    async def upsert_role(self, role_name: str, permissions: dict,
                          is_custom: bool) -> None:
        """Создать/обновить роль + reload (84.14.4: правка любых ролей)."""
        self._require_pg()
        async with self._pg.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_roles (role_name, permissions, is_custom)
                VALUES ($1, $2, $3)
                ON CONFLICT (role_name) DO UPDATE
                SET permissions = EXCLUDED.permissions
                """,
                role_name, json.dumps(permissions), is_custom,
            )
        await self.reload()
        logger.info("[config_cache] role upserted: %s (is_custom=%s)",
                    role_name, is_custom)

    async def delete_role(self, role_name: str) -> bool:
        """Удалить роль + reload. False — роли не было."""
        self._require_pg()
        async with self._pg.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM bot_roles WHERE role_name = $1", role_name)
        removed = _deleted_count(result)
        await self.reload()
        logger.info("[config_cache] role deleted: %s (removed=%s)",
                    role_name, removed)
        return removed

    async def reload(self) -> None:
        """Перезагрузка всех таблиц из PG (после POST /api/admins|roles)."""
        if not self._pg_available:
            logger.warning("[config_cache] reload: PG недоступен — no-op")
            return
        await self._load_all()
        logger.info("[config_cache] reloaded: settings=%d roles=%d admins=%d",
                    len(self._settings), len(self._roles), len(self._admins))

    async def close(self) -> None:
        await self._pg.close()
