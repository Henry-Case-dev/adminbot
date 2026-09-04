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
"""
import logging

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

_ROLE_ADMIN = "admin"
_ROLE_MODERATOR = "moderator"


def _cache():
    """ConfigCache | None (до init — только ADMIN_USER_ID, R6-фолбэк)."""
    return hot.get_config_cache()


def role_of(telegram_id: int) -> str | None:
    """Роль telegram_id из RAM-кэша (PG down/нет кэша → None)."""
    cache = _cache()
    if cache is None:
        return None
    try:
        return cache.get_role(int(telegram_id))
    except Exception:
        logger.warning("chat_access: get_role failed — admin-only fallback",
                       exc_info=True)
        return None


def is_admin(telegram_id: int) -> bool:
    """settings.ADMIN_USER_ID всегда админ; иначе — роль 'admin' из кэша."""
    try:
        if int(telegram_id) == int(settings.ADMIN_USER_ID):
            return True
    except (TypeError, ValueError):
        pass
    return role_of(telegram_id) == _ROLE_ADMIN


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
