"""Раунд 10 (multi-chat-rbac-byok, F-7 §3) — per-param права и матрица доступа.

`param_permissions` — ОТДЕЛЬНАЯ таблица (key → {"view_min_role","edit_min_role",
"hidden_from_local"}), НЕ runtime-конфиг (в ConfigCache/GET /api/config/дерево
ролей НЕ попадает). Строки в таблице НЕ сидятся: DEFAULT_MATRIX — в коде
(spec §3.1), БД-строки — точечные override'ы глобального админа.

Контракты:
  * default_matrix(spec) — дефолт по категории (см. таблицу spec §3.1);
  * effective_matrix(pg_key, db_override, chat_override) — дефолт ⊕ override'ы;
  * can_view_param(ctx, matrix) — видимость ключа (hidden_from_local +
    min-роль view);
  * can_edit_param(ctx, matrix) — min-роль edit по рангу (ROLE_TYPE_RANK);
  * can_access_chat(ctx) — доступ юзера к чату (Q3-семантика §2.3);
  * param_permissions-таблица: db_override_map(PG) + upsert/delete.

Полный резолв ctx — services/roles.access_for (не путать с одноимёнными
функциями web/api/deps.py — те без изменений).
"""
import json
import logging
import time

from services.param_catalog import CATEGORY_KEYS, CATEGORY_PROMPTS, get_by_pg_key
from services.roles import (
    ROLE_GLOBAL_ADMIN,
    ROLE_LOCAL_ADMIN,
    ROLE_MODERATOR,
    ROLE_USER,
    ROLE_TYPE_RANK,
    AccessCtx,
)

logger = logging.getLogger(__name__)

_DB_OVERRIDE_TTL = 60.0

SELECT_PERM_SQL = (
    "SELECT key, value FROM param_permissions ORDER BY key"
)
UPSERT_PERM_SQL = (
    "INSERT INTO param_permissions (key, value) VALUES ($1, $2) "
    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
    "updated_at = now()"
)
DELETE_PERM_SQL = "DELETE FROM param_permissions WHERE key = $1"

_db_override_cache: dict = {}
_db_override_cache_ts: float = 0.0


def reset_param_permissions_cache() -> None:
    """Сброс кэша DB-override (после PUT/NOTIFY; autouse-fixture тестов)."""
    global _db_override_cache, _db_override_cache_ts
    _db_override_cache = {}
    _db_override_cache_ts = 0.0


def can_access_chat(ctx: AccessCtx) -> bool:
    """Q3-семантика (§2.3): global admin — все чаты; грант chat_admins —
    local_admin/moderator чата; глобальный moderator — чтение; user — нет."""
    if ctx.is_global_admin:
        return True
    if ctx.role_chat in (ROLE_LOCAL_ADMIN, ROLE_MODERATOR):
        return True
    return ctx.rank >= ROLE_TYPE_RANK[ROLE_MODERATOR]


async def db_override_map(pg) -> dict[str, dict]:
    """Строки param_permissions → {key: matrix}; TTL 60 c; fail-open {}."""
    global _db_override_cache, _db_override_cache_ts
    now = time.monotonic()
    if _db_override_cache and (now - _db_override_cache_ts) < _DB_OVERRIDE_TTL:
        return _db_override_cache
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        return {}
    out = {}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(SELECT_PERM_SQL)
        for r in rows:
            value = r["value"]
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = {}
            if isinstance(value, dict):
                out[r["key"]] = value
    except Exception:
        logger.warning("[access] param_permissions недоступны — fail-open",
                       exc_info=True)
        return {}
    _db_override_cache = out
    _db_override_cache_ts = now
    return out


async def upsert_param_permission(pg, key: str, value: dict) -> None:
    """Запись override (INSERT ON CONFLICT) + сброс кэша."""
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        raise RuntimeError("PostgreSQL недоступен (пул отсутствует)")
    async with pool.acquire() as conn:
        await conn.execute(UPSERT_PERM_SQL, key, json.dumps(value))
    reset_param_permissions_cache()


async def delete_param_permission(pg, key: str) -> bool:
    """Удаление override (возврат к дефолту) + сброс кэша."""
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        raise RuntimeError("PostgreSQL недоступен (пул отсутствует)")
    async with pool.acquire() as conn:
        result = await conn.execute(DELETE_PERM_SQL, key)
    reset_param_permissions_cache()
    return bool(result and result.split()[-1] != "0")

# Домены ролей для валидации param_permissions (spec §3.1).
ROLE_TYPES: tuple[str, ...] = (ROLE_GLOBAL_ADMIN, ROLE_LOCAL_ADMIN,
                               ROLE_MODERATOR, ROLE_USER)

# КАТЕГОРИЯ → (view_min_role, edit_min_role, hidden_from_local) — spec §3.1.
_DEFAULT_EDIT_ROLES = {"prompts": ROLE_LOCAL_ADMIN}
_DEFAULT_HIDDEN_CATEGORIES = {CATEGORY_KEYS}


def default_matrix(pg_key: str, category: str | None = None) -> dict:
    """Эффективный дефолт для ключа (спецификация §3.1 таблица)."""
    spec = get_by_pg_key(pg_key)
    cat = category or (spec.category if spec else (pg_key or "").split(".")[0])
    if cat == CATEGORY_KEYS:
        return {"view_min_role": ROLE_GLOBAL_ADMIN,
                "edit_min_role": ROLE_GLOBAL_ADMIN,
                "hidden_from_local": True}
    if cat == CATEGORY_PROMPTS:
        return {"view_min_role": ROLE_USER,
                "edit_min_role": ROLE_LOCAL_ADMIN,
                "hidden_from_local": False}
    return {"view_min_role": ROLE_USER,
            "edit_min_role": ROLE_MODERATOR,
            "hidden_from_local": False}


def effective_matrix(pg_key: str, db_override: dict | None = None,
                     chat_override: dict | None = None) -> dict:
    """Дефолт ⊕ DB-override (param_permissions) ⊕ chat-override
    (chat_params.perm_overrides) — для GET/POST /api/config."""
    matrix = default_matrix(pg_key)
    for override in (db_override, chat_override):
        if not isinstance(override, dict):
            continue
        for field in ("view_min_role", "edit_min_role", "hidden_from_local"):
            value = override.get(field)
            if value is not None:
                matrix[field] = value
    return matrix


def can_view_param(ctx: AccessCtx, matrix: dict) -> bool:
    """Видимость ключа для юзера (спец §3.1: hidden_from_local + min-роль)."""
    if ctx.is_global_admin:
        return True
    if matrix.get("hidden_from_local") and ctx.is_local_admin:
        return False
    return ctx.rank >= ROLE_TYPE_RANK.get(matrix.get("view_min_role",
                                                     ROLE_USER) or ROLE_USER, 1)


def can_edit_param(ctx: AccessCtx, matrix: dict) -> bool:
    """Редактирование ключа в chat-скоупе (F-7 spec §2.3/§6, фикс R1).

    Глобальный модератор/кастом без chat-гранта в per-chat-контексте —
    ТОЛЬКО чтение: редактирование `chat_params` требует гранта chat_admins
    (local_admin|moderator на ЭТОТ чат) или ранга global admin. При наличии
    гранта — min-роль edit по матрице (chat-скоп)."""
    if ctx.is_global_admin:
        return True
    if ctx.role_chat not in (ROLE_LOCAL_ADMIN, ROLE_MODERATOR):
        return False
    min_role = matrix.get("edit_min_role", ROLE_MODERATOR) or ROLE_MODERATOR
    return ctx.rank >= ROLE_TYPE_RANK.get(min_role, 1)
