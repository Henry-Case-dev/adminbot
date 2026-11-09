"""Раунд 10 (multi-chat-rbac-byok, F-7 §3) — per-param права и матрица доступа.

`param_permissions` — ОТДЕЛЬНАЯ таблица (key → права), НЕ runtime-конфиг
(в ConfigCache/GET /api/config/дерево ролей НЕ попадает). Строки в таблице НЕ
сидятся: DEFAULT_MATRIX — в коде (spec §3.2.3), БД-строки — точечные
override'ы глобального админа.

Ре-дизайн 10.2, BUG-6 (spec §3.2): ФЛАГИ-модель прав — {view_roles,
edit_roles} (массивы ДОМЕННЫХ ролей user/moderator/local_admin; global admin
— неявно всегда и в массивы не входит; пустые массивы = только суперюзер).
Легаси-строки {view_min_role, edit_min_role, hidden_from_local} мигрируют НА
ЧТЕНИИ (_normalize_perms); hidden_from_local фолдится в отсутствие local_admin
в view_roles. «Запись подразумевает чтение»: view_roles |= edit_roles.

Контракты:
  * default_matrix(spec) — дефолт по категории (таблица spec §3.2.3);
  * _normalize_perms/effective_matrix — нормализация (легаси→флаги) и
    дефолт ⊕ override'ы;
  * can_view_param(ctx, matrix) — видимость ключа (флаги view_roles);
  * can_edit_param(ctx, matrix) — редактирование (флаги edit_roles + грант
    chat_admins);
  * eligible_type(ctx) — роль по скоупу (custom → алиас по rank);
  * can_access_chat(ctx) — доступ юзера к чату (Q3-семантика §2.3);
  * param_permissions-таблица: db_override_map(PG) + upsert/delete.

Полный резолв ctx — services/roles.access_for (не путать с одноимёнными
функциями web/api/deps.py — те без изменений).
"""
import json
import logging
import time

from services.param_catalog import CATEGORY_KEYS, CATEGORY_PROMPTS, get_by_pg_key
from services.chat_params import is_dm_scope
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


def can_access_chat(ctx: AccessCtx, chat_id=None) -> bool:
    """Q3-семантика (§2.3): global admin — все чаты; грант chat_admins —
    local_admin/moderator чата; глобальный moderator — чтение; user — нет.
    F-14 (spec §2.2): аддитивный параметр chat_id — DM-скоуп (chat_id > 0):
    доступ ТОЛЬКО владельцу (is_dm_owner); глобальный админ в ЧУЖОМ ЛС →
    False → 403. Без chat_id — прежнее поведение (вызовы не меняются)."""
    if chat_id is not None and is_dm_scope(chat_id):
        return bool(ctx.is_dm_owner)
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

# Домены ролей для валидации param_permissions (spec §3.1 — legacy-путь).
ROLE_TYPES: tuple[str, ...] = (ROLE_GLOBAL_ADMIN, ROLE_LOCAL_ADMIN,
                               ROLE_MODERATOR, ROLE_USER)

# Ре-дизайн 10.2, BUG-6 (spec §3.2.3): домен флагов-ролей (НЕ global admin —
# тот неявный всегда; включение его в массив → 422 на API).
FLAG_ROLE_DOMAIN: tuple[str, ...] = (ROLE_USER, ROLE_MODERATOR,
                                     ROLE_LOCAL_ADMIN)
_FLAG_ROLE_DOMAIN_SET = frozenset(FLAG_ROLE_DOMAIN)
# Порядок «по возрастанию ранга» — для _roles_at_least.
_FLAG_ROLE_RANKED: tuple[str, ...] = (ROLE_USER, ROLE_MODERATOR,
                                      ROLE_LOCAL_ADMIN)


def _roles_at_least(min_role: str | None) -> list[str]:
    """Роли домена с рангом >= rank(min_role). global_admin (rank 4) → пусто
    (эквивалент «только суперюзер» — неявный)."""
    rank = ROLE_TYPE_RANK.get(min_role or ROLE_USER, 1)
    return [r for r in _FLAG_ROLE_RANKED if ROLE_TYPE_RANK[r] >= rank]


def _norm_roles(value) -> list[str]:
    """Массив флагов-ролей: домен-фильтр, без дублей."""
    if not isinstance(value, (list, tuple)):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for r in value:
        if r in _FLAG_ROLE_DOMAIN_SET and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _normalize_perms(value: dict, base: dict | None = None) -> dict:
    """Легаси {view_min_role, edit_min_role, hidden_from_local} →
    {view_roles, edit_roles} (миграция НА ЧТЕНИИ; БД не трогаем).

    Правила (spec §3.2.2):
      * view_roles = роли с rank >= rank(view_min_role);
      * edit_roles = роли с rank >= rank(edit_min_role);
      * hidden_from_local=true → из view_roles удаляется local_admin
        (фолдинг: НЕ отдельный флаг);
      * «запись подразумевает чтение»: view_roles |= edit_roles.
    base — текущая матрица (дефолт/предыдущий override): legacy-поле,
    отсутствующее в перекрытии, наследуется из base (поле-мерж, как было)."""
    if not isinstance(value, dict):
        return {"view_roles": [], "edit_roles": []}
    base = base or {}
    if "view_roles" in value or "edit_roles" in value:
        # новая форма (или гибрид) — сохраняем как есть + union
        vr = (_norm_roles(value["view_roles"]) if "view_roles" in value
              else list(base.get("view_roles") or []))
        er = (_norm_roles(value["edit_roles"]) if "edit_roles" in value
              else list(base.get("edit_roles") or []))
    else:
        vr = (_roles_at_least(value.get("view_min_role"))
              if "view_min_role" in value
              else list(base.get("view_roles") or []))
        er = (_roles_at_least(value.get("edit_min_role"))
              if "edit_min_role" in value
              else list(base.get("edit_roles") or []))
        if value.get("hidden_from_local") and ROLE_LOCAL_ADMIN in vr:
            vr = [r for r in vr if r != ROLE_LOCAL_ADMIN]
    view_roles_set = set(vr) | set(er)
    edit_roles_set = set(er)
    return {
        # единый доменный порядок (user → moderator → local_admin): ответы
        # нормализованы детерминированно независимо от порядка в теле/БД
        "view_roles": [r for r in _FLAG_ROLE_RANKED if r in view_roles_set],
        "edit_roles": [r for r in _FLAG_ROLE_RANKED if r in edit_roles_set],
    }


def default_matrix(pg_key: str, category: str | None = None) -> dict:
    """Эффективный дефолт для ключа (spec §3.2.3 таблица флагов).

    | Категория | view_roles | edit_roles |
    | keys.*    | []         | []         | (только global admin)
    | prompts.* | [local_admin] | [local_admin] |
    | остальные (limits/flags/reactions/content/memory/models) |
                | [moderator, local_admin] | [local_admin] |
    """
    spec = get_by_pg_key(pg_key)
    cat = category or (spec.category if spec else (pg_key or "").split(".")[0])
    if cat == CATEGORY_KEYS:
        return {"view_roles": [], "edit_roles": []}
    if cat == CATEGORY_PROMPTS:
        return {"view_roles": [ROLE_LOCAL_ADMIN],
                "edit_roles": [ROLE_LOCAL_ADMIN]}
    return {"view_roles": [ROLE_MODERATOR, ROLE_LOCAL_ADMIN],
            "edit_roles": [ROLE_LOCAL_ADMIN]}


def effective_matrix(pg_key: str, db_override: dict | None = None,
                     chat_override: dict | None = None) -> dict:
    """Дефолт ⊕ DB-override (param_permissions) ⊕ chat-override
    (chat_params.perm_overrides) — для GET/POST /api/config.

    Override — ПОЛНЫЙ массив (replace): нормализованный {view_roles,
    edit_roles} перекрывает дефолт целиком; legacy-поля нормализуются
    (отсутствующие поля наследуются из base-матрицы);
    «запись подразумевает чтение»: view_roles |= edit_roles."""
    matrix = default_matrix(pg_key)
    for override in (db_override, chat_override):
        if not isinstance(override, dict) or not override:
            continue
        normalized = _normalize_perms(override, matrix)
        matrix = {
            "view_roles": list(normalized["view_roles"]),
            "edit_roles": list(normalized["edit_roles"]),
        }
    return matrix


def _as_new_matrix(matrix: dict) -> dict:
    """Защита: матрица в новой форме — как есть; легаси — нормализуется."""
    if not isinstance(matrix, dict):
        return {"view_roles": [], "edit_roles": []}
    if "view_roles" in matrix or "edit_roles" in matrix:
        return _normalize_perms(matrix)
    return _normalize_perms(matrix)


def eligible_type(ctx: AccessCtx) -> str | None:
    """Роль по скоупу (spec §3.2.5): role_chat (грант) — если задан, иначе
    role_global; custom/неизвестная роль → алиас по rank: 4→global_admin
    (неявный), 3→local_admin, 2→moderator, 1→user.
    F-14 (spec §2.2): DM-владелец (role_chat=None!) → local_admin — иначе
    view/edit-матрицы per_chat-ключей ([moderator, local_admin] /
    [local_admin]) вернули бы False всегда."""
    if ctx.is_dm_owner:
        return ROLE_LOCAL_ADMIN
    role = ctx.role_chat or ctx.role_global
    if role in _FLAG_ROLE_DOMAIN_SET:
        return role
    if ctx.rank >= ROLE_TYPE_RANK[ROLE_LOCAL_ADMIN]:
        return ROLE_LOCAL_ADMIN
    if ctx.rank >= ROLE_TYPE_RANK[ROLE_MODERATOR]:
        return ROLE_MODERATOR
    return ROLE_USER


def can_view_param(ctx: AccessCtx, matrix: dict) -> bool:
    """Видимость ключа (spec §3.2.5): global admin → True; иначе
    eligible_type(ctx) в view_roles (hidden_from_local-фолдинг уже в
    нормализации — absence local_admin)."""
    if ctx.is_global_admin:
        return True
    m = _as_new_matrix(matrix)
    return eligible_type(ctx) in m.get("view_roles", [])


def can_edit_param(ctx: AccessCtx, matrix: dict) -> bool:
    """Редактирование ключа в chat-скоупе (F-7 spec §2.3/§6, фикс R1).

    Глобальный модератор/кастом без chat-гранта в per-chat-контексте —
    ТОЛЬКО чтение: редактирование `chat_params` требует гранта chat_admins
    (local_admin|moderator на ЭТОТ чат) или ранга global admin. При наличии
    гранта — eligible_type(ctx) в edit_roles (флаги модели).
    F-14 (spec §2.2): ветка is_dm_owner — ПОСЛЕ is_global_admin и ДО
    role_chat-гейта (у DM-владельца role_chat=None): per_chat-ключи
    (limits/flags/reactions/content/memory/prompts — edit_roles
    [local_admin]) → True; keys.* (дефолт-матрица []/[]) → False (R17:
    ключи — только BYOK-путь /api/config/keys/own)."""
    if ctx.is_global_admin:
        return True
    if ctx.is_dm_owner:
        m = _as_new_matrix(matrix)
        return eligible_type(ctx) in m.get("edit_roles", [])
    if ctx.role_chat not in (ROLE_LOCAL_ADMIN, ROLE_MODERATOR):
        return False
    m = _as_new_matrix(matrix)
    return eligible_type(ctx) in m.get("edit_roles", [])


# ═══════════════════════════════════════════════════════════════════════════
# SELF-DIAG-01 D2 — матрица диагностических возможностей.
#
# ТОТ ЖЕ слой прав, а не второй ACL: строки живут в существующей таблице
# `param_permissions` под префиксом `diag.<capability>`, чат-скоуп — в
# существующем `chat_params.perm_overrides` тем же ключом. Дефолт (таблица
# роль×класс из ТЗ §7.2) — в коде `services.diagnostic_policy`, здесь только
# нормализация/хранение/чтение перекрытий.
# ═══════════════════════════════════════════════════════════════════════════

#: Префикс ключей диагностической матрицы в общем сторе прав.
DIAG_KEY_PREFIX = "diag."

#: Действия диагностических возможностей (просмотр/запуск/редактирование).
DIAG_ACTIONS: tuple[str, ...] = ("view", "run", "edit")

#: Действие → поле матрицы.
DIAG_ACTION_FIELD: dict[str, str] = {
    "view": "view_roles",
    "run": "run_roles",
    "edit": "edit_roles",
}

#: Домен ролей диагностической матрицы. global_admin (project_owner) —
#: неявный и всегда разрешён (кроме абсолютных запретов класса), moderator
#: в диагностике не участвует: роль `chat_admin` подтверждается только
#: онлайн-проверкой Telegram и отображается строкой local_admin.
DIAG_ROLE_DOMAIN: tuple[str, ...] = (ROLE_USER, ROLE_LOCAL_ADMIN)


def diag_perm_key(capability_id: str) -> str:
    """Ключ строки общего стора прав для диагностической возможности."""
    return f"{DIAG_KEY_PREFIX}{capability_id}"


def is_diag_perm_key(key: str) -> bool:
    return isinstance(key, str) and key.startswith(DIAG_KEY_PREFIX)


def capability_of_diag_key(key: str) -> str:
    return key[len(DIAG_KEY_PREFIX):] if is_diag_perm_key(key) else key


def normalize_diag_matrix(value: dict, base: dict | None = None) -> dict:
    """Нормализация перекрытия {view_roles, run_roles, edit_roles}.

    Домен — `DIAG_ROLE_DOMAIN` (неизвестные и global_admin отбрасываются);
    «запуск/редактирование подразумевают просмотр»: view_roles ⊇ run_roles ∪
    edit_roles. `base` — текущая матрица (наследование отсутствующих полей).
    """
    base = base or {}
    if not isinstance(value, dict):
        return {"view_roles": [], "run_roles": [], "edit_roles": []}

    def _field(name: str) -> list[str]:
        if name not in value:
            return list(base.get(name) or [])
        raw = value.get(name)
        if not isinstance(raw, (list, tuple)):
            return []
        return [r for r in DIAG_ROLE_DOMAIN if r in set(raw)]

    run_roles = _field("run_roles")
    edit_roles = _field("edit_roles")
    view_roles = _field("view_roles")
    allowed = set(view_roles) | set(run_roles) | set(edit_roles)
    return {
        "view_roles": [r for r in DIAG_ROLE_DOMAIN if r in allowed],
        "run_roles": run_roles,
        "edit_roles": edit_roles,
    }


async def diag_global_overrides(pg) -> dict[str, dict]:
    """Перекрытия {capability_id: normalized matrix} из общего стора прав."""
    rows = await db_override_map(pg)
    out: dict[str, dict] = {}
    for key, value in rows.items():
        if not is_diag_perm_key(key):
            continue
        out[capability_of_diag_key(key)] = normalize_diag_matrix(value)
    return out


async def upsert_diag_matrix(pg, capability_id: str, matrix: dict) -> dict:
    """Записать перекрытие диагностической матрицы (та же таблица прав)."""
    normalized = normalize_diag_matrix(matrix)
    await upsert_param_permission(pg, diag_perm_key(capability_id), normalized)
    return normalized


async def delete_diag_matrix(pg, capability_id: str) -> bool:
    """Сбросить перекрытие к дефолту класса (404-семантика у вызывающего)."""
    return await delete_param_permission(pg, diag_perm_key(capability_id))


async def diag_chat_overrides(chat_id: int | None,
                              pg=None) -> dict[str, dict]:
    """Чат-скоуп перекрытия диагностической матрицы (perm_overrides)."""
    if chat_id is None:
        return {}
    from services import chat_params
    try:
        root = await chat_params.get_all_chat_params(int(chat_id), pg=pg)
    except Exception:                                  # pragma: no cover
        logger.warning("[access] chat perm_overrides недоступны — дефолт | "
                       "chat=%s", chat_id, exc_info=True)
        return {}
    raw = (root or {}).get("perm_overrides") or {}
    out: dict[str, dict] = {}
    for key, value in raw.items():
        if not is_diag_perm_key(key):
            continue
        out[capability_of_diag_key(key)] = normalize_diag_matrix(value)
    return out
