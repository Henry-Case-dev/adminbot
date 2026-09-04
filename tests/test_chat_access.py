"""Раунд 4 (T-715/AC-D5, spec 3.4.4) — RBAC-матрица services/chat_access.py.

Мок ConfigCache: роль есть/нет/PG down (cache None)/ADMIN_USER_ID;
is_admin/is_moderator/privilege. PG-роли читаются из RAM-кэша
(get_role); фолбэк — только settings.ADMIN_USER_ID.
"""
import pytest

from config.settings import settings
from services import chat_access
from services import hot_config as hot


class _Cache:
    """Минимальный мок ConfigCache (только get_role)."""

    def __init__(self, roles):
        self._roles = dict(roles)

    def get_role(self, telegram_id):
        return self._roles.get(telegram_id)

    def get(self, key, default=None):
        return default


@pytest.fixture
def cache(monkeypatch):
    """hot-кэш с ролью-словарём; после теста — восстановление (None)."""
    old = hot.get_config_cache()
    state = {"roles": {}}

    def _set(roles):
        state["roles"] = dict(roles)
        hot.set_config_cache(_Cache(state["roles"]))

    yield _set
    hot.set_config_cache(old)


ADMIN = settings.ADMIN_USER_ID
MODERATOR_ID = 1313107079        # сид pg_db DEFAULT_ADMINS: moderator
OTHER_MOD_ID = 134812796         # второй moderator-сид
PLAIN = 555444333


class TestIsAdmin:
    def test_admin_user_id_always_admin_even_pg_down(self, cache):
        """PG down/кэш пуст → ADMIN_USER_ID остаётся админом (R6)."""
        cache({})
        assert chat_access.is_admin(ADMIN)
        assert chat_access.is_moderator(ADMIN)
        assert chat_access.privilege(ADMIN) == "admin"

    def test_role_admin_from_cache(self, cache):
        cache({PLAIN: "admin"})
        assert chat_access.is_admin(PLAIN)
        assert chat_access.privilege(PLAIN) == "admin"

    def test_no_cache_at_all_admin_only(self):
        """hot-кэш вообще не инициализирован → только ADMIN_USER_ID."""
        old = hot.get_config_cache()
        hot.set_config_cache(None)
        try:
            assert chat_access.privilege(ADMIN) == "admin"
            assert chat_access.privilege(PLAIN) == "user"
        finally:
            hot.set_config_cache(old)

    def test_plain_user_not_admin(self, cache):
        cache({})
        assert not chat_access.is_admin(PLAIN)
        assert chat_access.privilege(PLAIN) == "user"


class TestIsModerator:
    def test_moderator_role(self, cache):
        cache({MODERATOR_ID: "moderator"})
        assert chat_access.is_moderator(MODERATOR_ID)
        assert not chat_access.is_admin(MODERATOR_ID)
        assert chat_access.privilege(MODERATOR_ID) == "moderator"

    def test_moderator_includes_admin(self, cache):
        cache({})
        assert chat_access.is_moderator(ADMIN)
        assert chat_access.privilege(ADMIN) == "admin"

    def test_admin_role_not_moderator_role_name(self, cache):
        """Админ-роль ≠ moderator-роль: privilege='admin', а не 'moderator'."""
        cache({PLAIN: "admin"})
        assert chat_access.privilege(PLAIN) == "admin"

    def test_other_moderator_seed_id(self, cache):
        cache({OTHER_MOD_ID: "moderator"})
        assert chat_access.privilege(OTHER_MOD_ID) == "moderator"

    def test_unknown_role_name_is_user(self, cache):
        """Роль есть, но не admin/moderator (напр. 'user') → без привилегий."""
        cache({PLAIN: "user"})
        assert not chat_access.is_admin(PLAIN)
        assert not chat_access.is_moderator(PLAIN)
        assert chat_access.privilege(PLAIN) == "user"

    def test_missing_role_is_user(self, cache):
        cache({})
        assert not chat_access.is_moderator(PLAIN)
        assert chat_access.privilege(PLAIN) == "user"
