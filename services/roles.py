"""Раунд 10 (multi-chat-rbac-byok, F-7 §2) — иерархия ролей и доступы.

РОЛЬ-МОДЕЛЬ (Q1-решение @Architect): `bot_roles.role_type` — семантический
маркер 4 встроенных ролей ('global_admin'|'local_admin'|'moderator'|'user'),
NULL = custom (права — из их permissions, rank по содержимому). `permissions.py`
НЕ расширяется (остаётся чистым матчером 84.14.2) — иначе риск регресса
validate_permissions/guard_last_wildcard.

`access_for(telegram_id, chat_id)` — единая точка семантики (spec §2.3): два
gранта-источника:
  1) global-срез (bot_admins + bot_roles) — Global Admin / Moderator / User /
     Custom на все чаты;
  2) chat-срез (строка chat_admins(chat_id) с role_name) — local_admin /
     moderator ТОЛЬКО этого чата.
`rank` — ранг наибольшего (иерархия ROLE_TYPE_RANK). Custom без role_type:
wildcard → 4 (полный доступ), ненулевые группы прав → 2, иначе 1 (user).
"""
from dataclasses import dataclass

import hashlib
import json
import logging

from services.access_errors import AccessStorageUnavailable
from services.chat_params import is_dm_scope
from services.permissions import Permissions, RoleGuardError

logger = logging.getLogger(__name__)

ROLE_GLOBAL_ADMIN = "global_admin"
ROLE_LOCAL_ADMIN = "local_admin"
ROLE_MODERATOR = "moderator"
ROLE_USER = "user"

ROLE_TYPES: tuple[str, ...] = (
    ROLE_GLOBAL_ADMIN, ROLE_LOCAL_ADMIN, ROLE_MODERATOR, ROLE_USER,
)

# Иерархия ролей (spec §2.2): global_admin > local_admin > moderator > user.
ROLE_TYPE_RANK: dict[str, int] = {
    ROLE_GLOBAL_ADMIN: 4,
    ROLE_LOCAL_ADMIN: 3,
    ROLE_MODERATOR: 2,
    ROLE_USER: 1,
}

# Пресет local_admin (spec §2.1): без wildcard, без keys, без prompts-секции
# (промпты — через per-chat override «Использовать мой»), без models.
LOCAL_ADMIN_PRESET: dict[str, object] = {
    "sections": ["limits", "flags", "reactions", "content", "chat_lore"],
    "actions": [],
}

# Существующий сид-пресет moderator (не расширять — spec §2.1).
MODERATOR_PRESET: dict[str, object] = {
    "sections": ["limits"],
    "actions": ["control.restart", "control.stop", "control.start"],
}

# F-14 (dm-user-settings, spec §2.1): пресет DM-владельца (свои ЛС). Секции —
# per-chat-параметры (промпты/лимиты/флаги/реакции/контент/память), БЕЗ
# chat_lore (лор-API ЛС → 404 — изоляция П.5) и БЕЗ group-секций.
DM_OWNER_PRESET: dict[str, object] = {
    "sections": ["prompts", "limits", "flags", "reactions", "content",
                 "memory"],
    "actions": [],
}


def role_type_of(role_name: str | None, perms_data: dict | None,
                 role_type_col: str | None) -> str:
    """Type роли: колонка role_type (если есть) → None → custom-эвристика."""
    if role_type_col:
        return role_type_col
    if role_name == "admin":          # legacy-сид без role_type
        return ROLE_GLOBAL_ADMIN
    return "custom"


def role_revision(role_name: str, permissions: dict | None,
                  role_type: str | None, is_custom: bool) -> str:
    """MOD-ACL-UX-01 M4C C3: детерминированная ревизия прав роли (DDL 0).

    Одна чистая функция для GET и POST: канонический permissions
    (`Permissions.from_dict(...).to_dict()` — отсортированные массивы),
    role_type и is_custom в json с sort_keys/компактными разделителями →
    sha256 hex. Никакого второго ACL/стора и никаких чтений БД.
    """
    payload = {
        "role_name": role_name,
        "permissions": Permissions.from_dict(permissions).to_dict(),
        "role_type": role_type,
        "is_custom": bool(is_custom),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def rank_of_type(role_type: str, perms: Permissions | None = None) -> int:
    """Ранг роли. Custom (role_type=None): wildcard → 4, ненулевые группы →
    2 (moderator), иначе 1 (user). Встроенные — по ROLE_TYPE_RANK."""
    if role_type is not None and role_type in ROLE_TYPE_RANK:
        return ROLE_TYPE_RANK[role_type]
    if perms is not None:
        if perms.wildcard:
            return 4
        if perms.sections or perms.actions or perms.params or perms.keys:
            return 2
    return 1


def is_effective_global_admin_role(role_name: str | None,
                                   role_data: dict | None) -> bool:
    """MOD-ACL-UX-01 M4C S2: роль — effective global admin.

    Ровно канон `web.api.deps.user_is_global_admin`: `role_type ==
    "global_admin"`, legacy-имя роли `admin` или `permissions.wildcard`.
    Второй ACL/матчер не вводится — функция читает тот же cache-снимок.
    """
    if role_name is None:
        return False
    if role_name == "admin":
        return True
    role_type = role_data.get("role_type") if isinstance(role_data, dict) else None
    if role_type_of(role_name, role_data, role_type) == ROLE_GLOBAL_ADMIN:
        return True
    perms_data = role_data.get("permissions") if isinstance(role_data, dict) else None
    return Permissions.from_dict(perms_data).wildcard


def assigned_global_admin_ids(roles: dict, admins: dict) -> set[int]:
    """I1: telegram_id **назначенных** админов с effective-global ролью."""
    roles = roles or {}
    return {
        telegram_id for telegram_id, role_name in (admins or {}).items()
        if is_effective_global_admin_role(role_name, roles.get(role_name))
    }


def assigned_wildcard_admin_ids(roles: dict, admins: dict) -> set[int]:
    """I2: telegram_id назначенных админов, чья роль несёт wildcard."""
    roles = roles or {}
    out: set[int] = set()
    for telegram_id, role_name in (admins or {}).items():
        role_data = roles.get(role_name)
        perms_data = (role_data.get("permissions")
                      if isinstance(role_data, dict) else None)
        if Permissions.from_dict(perms_data).wildcard:
            out.add(telegram_id)
    return out


def guard_admin_lockout(before_roles: dict, before_admins: dict,
                        after_roles: dict, after_admins: dict) -> None:
    """MOD-ACL-UX-01 M4C S2: не допустить потери последнего назначенного
    администратора с полным доступом (I2) или последнего effective-global
    администратора (I1).

    Блокируется только переход `>0 → 0`: уже деградированное состояние (0 в
    before) не мешает восстановлению, а случайное/злонамеренное обнуление —
    блокируется. I2 проверяется первой — сообщение «полным доступом»
    сохраняется для существующего 409-контракта. Нарушение → RoleGuardError
    (409 на уровне API, как у guard_last_wildcard).
    """
    if assigned_wildcard_admin_ids(before_roles, before_admins) \
            and not assigned_wildcard_admin_ids(after_roles, after_admins):
        raise RoleGuardError(
            "нельзя оставить систему без администратора с полным доступом")
    if assigned_global_admin_ids(before_roles, before_admins) \
            and not assigned_global_admin_ids(after_roles, after_admins):
        raise RoleGuardError(
            "нельзя оставить систему без глобального администратора")


@dataclass(frozen=True)
class AccessCtx:
    """Срез прав пользователя (spec §2.2)."""

    role_global: str            # 'global_admin'|'moderator'|'user'|'custom'|None
    role_chat: str | None       # 'local_admin'|'moderator'|None (нет гранта)
    perms_global: Permissions
    perms_chat: Permissions
    is_global_admin: bool
    is_local_admin: bool        # role_chat == 'local_admin'
    rank: int                   # max(rank_global, rank_chat)
    # F-14 (dm-user-settings, spec §2.1): владелец СВОИХ ЛС (chat_id ==
    # telegram_id и chat_id > 0). Дефолт False — позиционные конструкторы
    # тестов не ломаются.
    is_dm_owner: bool = False

    @property
    def effective_permissions(self) -> Permissions:
        """Union perms_global ∪ perms_chat (для chat-скоупа)."""
        return _union_permissions(self.perms_global, self.perms_chat)


CHAT_ADMIN_ROLE_SQL = (
    "SELECT role_name FROM chat_admins WHERE chat_id = $1 AND telegram_id = $2"
)


def _user_permissions(cache, telegram_id: int) -> Permissions:
    """Права юзера; неизвестный ID → пустые права (роль user, 84.6-канон)."""
    if cache is None:
        return Permissions.from_dict({})
    perms = cache.get_permissions_by_telegram_id(telegram_id)
    if perms is None:
        user_role = cache.get_permissions("user")
        return user_role if user_role is not None else Permissions.from_dict({})
    return perms


def _role_type_of(cache, role_name: str | None) -> str:
    """Type глобальной роли: role_type-колонка (ConfigCache.roles() несёт
    role_type из _load_all — jsonb-объект роли) либо legacy-эвристика."""
    if role_name is None:
        return ROLE_USER
    role_data = cache.roles().get(role_name) if cache is not None else None
    role_type = None
    if isinstance(role_data, dict):
        role_type = role_data.get("role_type")
    return role_type_of(role_name, role_data, role_type)


async def access_for(telegram_id: int, chat_id: int | None = None,
                     cache=None, *, strict: bool = False) -> AccessCtx:
    """Q3-ядро (spec §2.3): глобальный срез + грант chat_admins.

    Роли:
      * Global Admin (role_type global_admin или wildcard) → всё, все чаты;
      * строка chat_admins(chat_id, 'local_admin') → пресет local_admin в
        ЭТОМ чате (chat-scope);
      * строка chat_admins(chat_id, 'moderator') → пресет moderator в ЭТОМ
        чате;
      * глобальный moderator → глобальный срез без изменений; в
        per-chat контексте — только чтение;
      * user/никто → read-only;
      * Custom (role_type NULL) — права по их permissions (существующий
        матчинг); rank по 2.2.
    access_for без chat_id → только глобальный срез. Fail-open: PG/кэш
    недоступен → глобальный срез + role_chat=None (chat-грант не виден),
    бот жив (spec §1.2-4).

    MOD-ACL-UX-01 M4C C2 (D1, аддитивно): ``strict=True`` превращает
    ровно те же две fail-open ветки в явный отказ:
      * кэш так и не получен, либо RAM-снимок ролей пуст и
        ``cache.pg_available`` False (холодный старт) → raise;
      * групповой chat-грант: пула нет или чтение упало → raise вместо
        warn+None (DM-ветка по-прежнему не требует PG).
    Default ``strict=False`` не меняет runtime-поведение бота.
    """
    if cache is None:
        from services import hot_config as hot
        cache = hot.get_config_cache()
    if strict and cache is None:
        raise AccessStorageUnavailable(
            "кэш прав недоступен: роль актора не читается")
    if strict and not cache.roles() and not cache.pg_available:
        raise AccessStorageUnavailable(
            "кэш прав пуст и PostgreSQL недоступен: роль актора не читается")
    role_name = cache.get_role(telegram_id) if cache is not None else None
    perms_global = _user_permissions(cache, telegram_id)
    role_global_type = _role_type_of(cache, role_name)
    is_global_admin = (role_global_type == ROLE_GLOBAL_ADMIN) or perms_global.wildcard

    role_chat: str | None = None
    perms_chat = Permissions.from_dict({})
    # F-14 (dm-user-settings, spec §2.1): DM-ветка — ДО группового
    # chat_admins-лукапа и БЕЗ обращений к PG (fail-open: PG down →
    # DM-владелец работает — локальный срез). Свой ЛС (chat_id > 0 и
    # chat_id == telegram_id): is_dm_owner=True, role_chat=None (НЕ путать
    # с group local_admin — is_local_admin остаётся False, F-11-меню
    # group-секции не открывает), perms_chat = DM_OWNER_PRESET.
    is_dm_owner = False
    if chat_id is not None and chat_id == telegram_id \
            and is_dm_scope(chat_id):
        is_dm_owner = True
        perms_chat = Permissions.from_dict(DM_OWNER_PRESET)
    elif chat_id is not None and cache is not None:
        try:
            pg = getattr(cache, "pg", None)
            pool = getattr(pg, "pool", None) if pg is not None else None
            if pool is None:
                if strict:
                    raise AccessStorageUnavailable(
                        "PostgreSQL недоступен: chat-грант не читается")
            else:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        CHAT_ADMIN_ROLE_SQL, chat_id, telegram_id)
                if row is not None and row["role_name"] in (ROLE_LOCAL_ADMIN,
                                                            ROLE_MODERATOR):
                    role_chat = row["role_name"]
                    perms_chat = Permissions.from_dict(
                        LOCAL_ADMIN_PRESET if role_chat == ROLE_LOCAL_ADMIN
                        else MODERATOR_PRESET)
        except AccessStorageUnavailable:
            raise
        except Exception as exc:
            if strict:
                raise AccessStorageUnavailable(
                    "PostgreSQL недоступен: chat-грант не читается") from exc
            logger.warning(
                "[roles] chat-грант недоступен — fail-open | user=%s chat=%s",
                telegram_id, chat_id, exc_info=True)
            role_chat = None

    if is_global_admin:
        rank = 4
    elif is_dm_owner:
        # DM-владелец: rank = max(ранг роли, local_admin=3)
        rank = max(rank_of_type(role_global_type, perms_global),
                   ROLE_TYPE_RANK[ROLE_LOCAL_ADMIN])
    elif role_chat is not None:
        rank = ROLE_TYPE_RANK[role_chat]
    else:
        rank = rank_of_type(role_global_type, perms_global)

    return AccessCtx(
        role_global=role_global_type,
        role_chat=role_chat,
        perms_global=perms_global,
        perms_chat=perms_chat,
        is_global_admin=is_global_admin,
        is_local_admin=(role_chat == ROLE_LOCAL_ADMIN),
        rank=rank,
        is_dm_owner=is_dm_owner,
    )


def _union_permissions(a: Permissions, b: Permissions) -> Permissions:
    """Объединение двух Permissions (frozen — через from_dict)."""
    return Permissions.from_dict({
        "sections": sorted(set(a.sections) | set(b.sections)),
        "params": sorted(set(a.params) | set(b.params)),
        "keys": sorted(set(a.keys) | set(b.keys)),
        "actions": sorted(set(a.actions) | set(b.actions)),
        "wildcard": a.wildcard or b.wildcard,
    })


def effective_permissions(ctx: AccessCtx) -> Permissions:
    """Union perms_global ∪ perms_chat (для chat-скоупа)."""
    return _union_permissions(ctx.perms_global, ctx.perms_chat)
