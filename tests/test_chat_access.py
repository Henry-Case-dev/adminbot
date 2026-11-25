"""Раунд 4 (T-715/AC-D5, spec 3.4.4) — RBAC-матрица services/chat_access.py.

Мок ConfigCache: роль есть/нет/PG down (cache None)/ADMIN_USER_ID;
is_admin/is_moderator/privilege. PG-роли читаются из RAM-кэша
(get_role); фолбэк — только settings.ADMIN_USER_ID.

MAC-S4-174 (M1-B): «глобальный админ» — общий канон с админкой
(`role_type=global_admin`, legacy `admin`, wildcard). Снимок ролей мока
повторяет форму реального `ConfigCache.roles()`
(`{role: {permissions, is_custom, role_type}}`) — иначе проверять канон
было бы не на чем. Межслойный паритет с `web.api.deps` — в
`tests/test_mod_acl_ux_01_m1_predicate.py`.
"""
import pytest

from config.settings import settings
from services import chat_access
from services import hot_config as hot


class _Cache:
    """Мок ConfigCache: get_role + roles() (форма как у настоящего кэша)."""

    def __init__(self, roles, role_data=None):
        self._roles = dict(roles)
        self._role_data = dict(role_data or {})

    def get_role(self, telegram_id):
        return self._roles.get(telegram_id)

    def roles(self):
        return dict(self._role_data)

    def get(self, key, default=None):
        return default


@pytest.fixture
def cache(monkeypatch):
    """hot-кэш с ролью-словарём; после теста — восстановление (None)."""
    old = hot.get_config_cache()
    state = {"roles": {}, "data": {}}

    def _set(roles, role_data=None):
        state["roles"] = dict(roles)
        state["data"] = dict(role_data or {})
        hot.set_config_cache(_Cache(state["roles"], state["data"]))

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


class TestGlobalAdminCanon:
    """MAC-S4-174: бот задаёт вопрос «глобальный админ» тем же каноном."""

    def test_role_type_global_admin_is_admin(self, cache):
        """Роль другого имени с role_type=global_admin — админ и в чате."""
        cache({PLAIN: "owner_global"},
              {"owner_global": {"permissions": {}, "is_custom": False,
                                "role_type": "global_admin"}})
        assert chat_access.is_global_admin(PLAIN)
        assert chat_access.is_admin(PLAIN)
        assert chat_access.privilege(PLAIN) == "admin"

    def test_wildcard_role_is_admin(self, cache):
        cache({PLAIN: "wildcard_custom"},
              {"wildcard_custom": {"permissions": {"wildcard": True},
                                   "is_custom": True, "role_type": None}})
        assert chat_access.is_global_admin(PLAIN)
        assert chat_access.privilege(PLAIN) == "admin"

    def test_specific_sections_are_not_global_admin(self, cache):
        """Права на конкретные секции не делают роль глобальным админом."""
        cache({PLAIN: "custom_access"},
              {"custom_access": {"permissions": {"sections": ["access"]},
                                 "is_custom": True, "role_type": None}})
        assert not chat_access.is_global_admin(PLAIN)
        assert chat_access.privilege(PLAIN) == "user"
