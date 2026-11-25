"""Раунд 4 (T-715, FR-D4, spec 3.4.4) — лёгкий RBAC-модуль привилегий в чате.

Синхронные хелперы поверх ConfigCache (RAM — services/config_cache.py:234-255:
`get_role(telegram_id)` → role_name | None; `admins()` → {telegram_id: role}).
Никаких новых PG-запросов в горячем пути. Фолбэк (R6): кэш не инициализирован
(тесты/ранний старт) или PG недоступен → ролей в RAM нет → привилегирован
только settings.ADMIN_USER_ID.

Роли: 'admin' и 'moderator' (bot_roles/bot_admins, pg_db.py:73-91 —
DEFAULT_ROLES admin/moderator/user; DEFAULT_ADMINS: 5885953495=admin,
1313107079/134812796=moderator). is_moderator включает и админа
(модер = moderator-роль; админ тоже подходит).

MAC-S4-174 (MOD-ACL-UX-01 M1-B) — «глобальный админ» здесь и в админке это
ОДИН канон, а не два правила: `is_global_admin` читает тот же предикат
`services.roles.is_effective_global_admin_role` (role_type `global_admin`,
legacy-имя роли `admin` или `permissions.wildcard`), что и
`web/api/deps.user_is_global_admin`. До этого исправления бот знал только
строку роли `admin`, поэтому глобальный админ Mini App с ролью другого имени
(`role_type=global_admin`) или wildcard-роль считался в чате обычным
пользователем (`direct_chat_service.privilege` → "user",
`mca_style_scope._has_chat_admin_rights` → отказ).

`is_admin` = этот канон ИЛИ `settings.ADMIN_USER_ID` — единственное
намеренное расширение бот-стороны: фолбэк R6, при котором владелец сохраняет
админку в чате при пустом кэше/недоступном PG. В `web/api/deps` такого
клауза нет (владелец там проходит по wildcard сид-роли).
"""
import logging

from config.settings import settings
from services import hot_config as hot
from services.roles import is_effective_global_admin_role

logger = logging.getLogger(__name__)

_ROLE_MODERATOR = "moderator"


def _cache():
    """ConfigCache | None (до init — только ADMIN_USER_ID, R6-фолбэк)."""
    return hot.get_config_cache()


def _role_from(cache, telegram_id: int) -> str | None:
    """Роль telegram_id из переданного снимка кэша (PG down/нет кэша → None)."""
    if cache is None:
        return None
    try:
        return cache.get_role(int(telegram_id))
    except Exception:
        logger.warning("chat_access: get_role failed — admin-only fallback",
                       exc_info=True)
        return None


def role_of(telegram_id: int) -> str | None:
    """Роль telegram_id из RAM-кэша (PG down/нет кэша → None)."""
    return _role_from(_cache(), telegram_id)


def is_global_admin(telegram_id: int) -> bool:
    """Единый канон «глобальный админ» для чата (MAC-S4-174).

    Разбор роли не дублируется: решение принимает
    `services.roles.is_effective_global_admin_role` — та же функция, что
    описывает канон админки (`role_type=global_admin`, legacy `admin`,
    wildcard). Сбой чтения ролей → False (fail-closed, горячий путь бота не
    падает). Роль и её данные читаются с одного снимка кэша.
    """
    cache = _cache()
    role = _role_from(cache, telegram_id)
    if role is None:
        return False
    try:
        role_data = cache.roles().get(role)
    except Exception:
        logger.warning("chat_access: roles() failed — не админ (fail-closed)",
                       exc_info=True)
        return False
    return is_effective_global_admin_role(role, role_data)


def is_admin(telegram_id: int) -> bool:
    """Владелец (R6-фолбэк) или глобальный админ по общему канону."""
    try:
        if int(telegram_id) == int(settings.ADMIN_USER_ID):
            return True
    except (TypeError, ValueError):
        pass
    return is_global_admin(telegram_id)


def is_moderator(telegram_id: int) -> bool:
    """Админ тоже подходит; иначе — роль 'moderator' из кэша."""
    return is_admin(telegram_id) or role_of(telegram_id) == _ROLE_MODERATOR


def privilege(telegram_id: int) -> str:
    """'admin' | 'moderator' | 'user'."""
    if is_admin(telegram_id):
        return "admin"
    if is_moderator(telegram_id):
        return "moderator"
    return "user"
