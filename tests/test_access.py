"""Раунд 10 (F-7, T-859 G2) — тесты services/roles.py + services/access.py.

Матрица access_for (spec §2.3): global admin — всё/all чаты; строка
chat_admins → local_admin/модератор этого чата; глобальный moderator —
глобальный срез (per-chat — только чтение); user — пусто; не-член → без
gранта. Ранг/матрицы канон: rank ≥ min-роль view/edit.
"""
import pytest

from services import access as access_srv
from services.roles import (
    AccessCtx,
    ROLE_LOCAL_ADMIN,
    ROLE_TYPE_RANK,
    access_for,
)


class _FakeCache:
    """ConfigCache-заглушка (роли/админы + pg для chat_admins)."""

    def __init__(self, roles, admins, pg=None):
        self._roles = roles
        self._admins = admins
        self.pg = pg

    def get_role(self, telegram_id):
        return self._admins.get(telegram_id)

    def get_permissions_by_telegram_id(self, telegram_id):
        role = self.get_role(telegram_id)
        if role is None or role not in self._roles:
            return None
        from services.permissions import Permissions
        return Permissions.from_dict(
            self._roles[role].get("permissions", {}))

    def get_permissions(self, role_name):
        from services.permissions import Permissions
        role = self._roles.get(role_name)
        if role is None:
            return None
        return Permissions.from_dict(role.get("permissions", {}))

    def roles(self):
        return dict(self._roles)


class _FakeConn:
    def __init__(self, admins):
        self.admins = admins   # {(chat_id, tg_id): role_name}

    async def fetchrow(self, sql, *args):
        assert "FROM chat_admins" in sql
        out = self.admins.get((args[0], args[1]))
        return {"role_name": out} if out is not None else None


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)


_ROLES = {
    "admin": {"permissions": {"wildcard": True}, "is_custom": False,
              "role_type": "global_admin"},
    "moderator": {"permissions": {"sections": ["limits"], "actions": [
        "control.restart"]}, "is_custom": False, "role_type": "moderator"},
    "user": {"permissions": {}, "is_custom": False, "role_type": "user"},
    "local_admin": {"permissions": {"sections": ["limits", "flags",
                                                 "reactions", "content",
                                                 "chat_lore"], "actions": []},
                    "is_custom": False, "role_type": "local_admin"},
}


@pytest.mark.asyncio
async def _cache_for(admins, chat_admins):
    pg = _FakePg(_FakeConn(chat_admins))
    return _FakeCache(_ROLES, admins, pg)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_global_admin_all_chats():
    cache = await _cache_for({5885953495: "admin"}, {})
    ctx = await access_for(5885953495, -10001, cache=cache)
    assert ctx.is_global_admin
    assert ctx.rank == 4
    assert ctx.role_chat is None
    assert access_srv.can_access_chat(ctx)


@pytest.mark.asyncio
async def test_user_no_grants_read_only():
    cache = await _cache_for({}, {})
    ctx = await access_for(12345, -10001, cache=cache)
    assert not ctx.is_global_admin
    assert ctx.role_chat is None
    assert not access_srv.can_access_chat(ctx)
    assert ctx.rank == 1


@pytest.mark.asyncio
async def test_chat_admin_row_local_admin_grant():
    cache = await _cache_for({}, {( -10001, 777): "local_admin"})
    ctx = await access_for(777, -10001, cache=cache)
    assert ctx.is_local_admin
    assert ctx.role_chat == "local_admin"
    assert ctx.rank == ROLE_TYPE_RANK[ROLE_LOCAL_ADMIN]
    assert ctx.perms_chat.sections >= {"limits", "flags", "reactions",
                                       "content", "chat_lore"}
    assert access_srv.can_access_chat(ctx)


@pytest.mark.asyncio
async def test_chat_moderator_grant():
    cache = await _cache_for({}, {(-10001, 555): "moderator"})
    ctx = await access_for(555, -10001, cache=cache)
    assert ctx.role_chat == "moderator"
    assert not ctx.is_local_admin
    assert access_srv.can_access_chat(ctx)


@pytest.mark.asyncio
async def test_chat_grant_outside_chat_is_empty():
    cache = await _cache_for({}, {(-10001, 777): "local_admin"})
    ctx = await access_for(777, -20002, cache=cache)
    assert ctx.role_chat is None
    assert not ctx.is_local_admin
    assert ctx.rank == 1


@pytest.mark.asyncio
async def test_global_moderator_read_access():
    cache = await _cache_for({1313107079: "moderator"}, {})
    ctx = await access_for(1313107079, -10001, cache=cache)
    assert ctx.rank == 2
    assert access_srv.can_access_chat(ctx)      # чтение — разрешено
    assert not ctx.is_local_admin


@pytest.mark.asyncio
async def test_custom_role_rank_by_content():
    custom = {"custom_role": {"permissions": {"params": [
        "limits.chat_cooldown_seconds"]}, "is_custom": True, "role_type": None}}
    pg = _FakePg(_FakeConn({}))
    cache = _FakeCache(custom, {42: "custom_role"}, pg)
    ctx = await access_for(42, -1, cache=cache)
    assert ctx.role_global == "custom"
    assert ctx.rank == 2
    cache2 = _FakeCache(
        {"empty_custom": {"permissions": {}, "is_custom": True}},
        {43: "empty_custom"}, pg)
    ctx2 = await access_for(43, -1, cache=cache2)
    assert ctx2.rank == 1


def test_rank_map():
    assert ROLE_TYPE_RANK == {"global_admin": 4, "local_admin": 3,
                              "moderator": 2, "user": 1}


def test_default_matrix_by_category():
    m = access_srv.default_matrix("keys.llm_api_key")
    assert m["view_min_role"] == "global_admin"
    assert m["edit_min_role"] == "global_admin"
    assert m["hidden_from_local"] is True
    m2 = access_srv.default_matrix("prompts.direct_chat_system_prompt")
    assert m2["view_min_role"] == "user"
    assert m2["edit_min_role"] == "local_admin"
    m3 = access_srv.default_matrix("limits.chat_cooldown_seconds")
    assert m3["edit_min_role"] == "moderator"
    assert m3["hidden_from_local"] is False


def test_effective_matrix_overrides():
    base = access_srv.default_matrix("limits.chat_cooldown_seconds")
    eff = access_srv.effective_matrix(
        "limits.chat_cooldown_seconds",
        db_override={"edit_min_role": "global_admin"},
        chat_override={"view_min_role": "local_admin",
                       "hidden_from_local": True})
    assert eff["edit_min_role"] == "global_admin"
    assert eff["view_min_role"] == "local_admin"
    assert eff["hidden_from_local"] is True


def test_hidden_from_local_hides():
    from services.permissions import Permissions
    la = Permissions.from_dict({"sections": ["limits"]})
    ctx = await_local_ctx_for(la, is_local_admin=True)
    matrix = {"view_min_role": "user", "edit_min_role": "moderator",
              "hidden_from_local": True}
    assert not access_srv.can_view_param(ctx, matrix)
    clear = dict(matrix, hidden_from_local=False)
    assert access_srv.can_view_param(ctx, clear)


def test_view_rank_below_min_hidden():
    from services.permissions import Permissions
    ctx = await_local_ctx_for(Permissions.from_dict({}), is_local_admin=False)
    matrix = {"view_min_role": "global_admin", "edit_min_role": "moderator",
              "hidden_from_local": False}
    assert not access_srv.can_view_param(ctx, matrix)


def test_edit_by_min_role():
    from services.permissions import Permissions
    # ФИКС R1 (F-7 §2.3/§6): редактирование в chat-скоупе требует chat-грант
    # (chat_admins); глобальный moderator/custom БЕЗ гранта — только чтение.
    mod = await_local_ctx_for(
        Permissions.from_dict({"sections": ["limits"]}), is_local_admin=False)
    matrix = {"view_min_role": "user", "edit_min_role": "moderator",
              "hidden_from_local": False}
    assert not access_srv.can_edit_param(mod, matrix)       # нет гранта → RO
    custom_ga = await_local_ctx_for(
        Permissions.from_dict({"wildcard": True}), is_local_admin=False)
    assert access_srv.can_edit_param(custom_ga, matrix)     # global admin


def test_edit_requires_chat_grant():
    """ФИКС R1: chat-moderator ГРАНТ редактирует по min-роли; локальный
    админ чата — тоже; без гранта (глобальный модератор) — нельзя."""
    from services.permissions import Permissions
    chat_mod = AccessCtx(role_global="moderator", role_chat="moderator",
                         perms_global=Permissions.from_dict(
                             {"sections": ["limits"]}),
                         perms_chat=Permissions.from_dict(
                             {"sections": ["limits"]}),
                         is_global_admin=False, is_local_admin=False, rank=2)
    matrix = {"view_min_role": "user", "edit_min_role": "moderator",
              "hidden_from_local": False}
    assert access_srv.can_edit_param(chat_mod, matrix)
    strict = {"view_min_role": "user", "edit_min_role": "local_admin",
              "hidden_from_local": False}
    assert not access_srv.can_edit_param(chat_mod, strict)  # min-роль выше
    local = AccessCtx(role_global="user", role_chat="local_admin",
                      perms_global=Permissions.from_dict({}),
                      perms_chat=Permissions.from_dict(
                          {"sections": ["limits"]}),
                      is_global_admin=False, is_local_admin=True, rank=3)
    assert access_srv.can_edit_param(local, strict)
    assert access_srv.can_view_param(chat_mod, matrix)      # чтение — можно


def await_local_ctx_for(perms, is_local_admin):
    """Имя сохранено для читаемости тестов; ctx — синхронный dataclass."""
    from services.roles import AccessCtx
    return AccessCtx(
        role_global="user", role_chat="local_admin" if is_local_admin else None,
        perms_global=perms, perms_chat=perms,
        is_global_admin=bool(perms.wildcard), is_local_admin=is_local_admin,
        rank=3 if is_local_admin else 2)
