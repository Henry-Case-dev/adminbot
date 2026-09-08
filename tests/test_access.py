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


# ═══ Ре-дизайн 10.2, BUG-6 (spec §3.2): ФЛАГИ-модель прав ═══

def test_default_matrix_flags_by_category():
    """spec §3.2.3: keys.* — пустые массивы (только global admin);
    prompts.* — [local_admin]/[local_admin]; остальное —
    [moderator, local_admin]/[local_admin]."""
    m = access_srv.default_matrix("keys.llm_api_key")
    assert m["view_roles"] == []
    assert m["edit_roles"] == []
    assert "hidden_from_local" not in m
    m2 = access_srv.default_matrix("prompts.direct_chat_system_prompt")
    assert m2["view_roles"] == ["local_admin"]
    assert m2["edit_roles"] == ["local_admin"]
    m3 = access_srv.default_matrix("limits.chat_cooldown_seconds")
    assert m3["view_roles"] == ["moderator", "local_admin"]
    assert m3["edit_roles"] == ["local_admin"]
    m4 = access_srv.default_matrix("models.llm_timeout")
    assert m4["view_roles"] == ["moderator", "local_admin"]
    m5 = access_srv.default_matrix("reactions.alan_user_id")
    assert m5["view_roles"] == ["moderator", "local_admin"]


def test_legacy_normalize_view_and_hidden_fold():
    """spec §3.2.2: legacy {view_min_role, edit_min_role,
    hidden_from_local} → {view_roles, edit_roles} на чтении."""
    m = access_srv._normalize_perms(
        {"view_min_role": "user", "edit_min_role": "moderator",
         "hidden_from_local": False})
    assert m["view_roles"] == ["user", "moderator", "local_admin"]
    assert m["edit_roles"] == ["moderator", "local_admin"]
    # hidden_from_local=true → local_admin фолдится из view (но edit-union
    # возвращает его, если он есть в edit: «запись подразумевает чтение»)
    m2 = access_srv._normalize_perms(
        {"view_min_role": "user", "edit_min_role": "local_admin",
         "hidden_from_local": True})
    assert m2["view_roles"] == ["user", "moderator", "local_admin"]
    assert m2["edit_roles"] == ["local_admin"]
    # legacy global_admin min-роль → только суперюзер (пустые массивы)
    m3 = access_srv._normalize_perms(
        {"view_min_role": "global_admin", "edit_min_role": "global_admin"})
    assert m3["view_roles"] == []
    assert m3["edit_roles"] == []


def test_effective_matrix_overrides_replace():
    """Override — ПОЛНЫЙ массив (replace) для новой формы; legacy-поля
    нормализуются на чтении (отсутствующее поле — из base-матрицы)."""
    eff = access_srv.effective_matrix(
        "limits.chat_cooldown_seconds",
        db_override={"view_roles": ["user"], "edit_roles": ["user"]},
        chat_override={"view_min_role": "moderator",
                       "hidden_from_local": True})
    # db: view [user] ∪ edit [user] = [user]; chat legacy поверх: view
    # rank>=moderator [moderator, local_admin] минус local_admin (fold) =
    # [moderator]; edit наследован из base [user]; union → [user, moderator]
    assert eff["view_roles"] == ["user", "moderator"]
    assert eff["edit_roles"] == ["user"]
    # новая форма override перекрывает дефолт
    eff2 = access_srv.effective_matrix(
        "limits.chat_cooldown_seconds",
        db_override={"view_roles": [], "edit_roles": []})
    assert eff2["view_roles"] == [] and eff2["edit_roles"] == []


def test_view_flags_hide_lower_roles():
    from services.permissions import Permissions
    user = await_local_ctx_for(Permissions.from_dict({}), is_local_admin=False)
    mod = AccessCtx(role_global="moderator", role_chat=None,
                    perms_global=Permissions.from_dict(
                        {"sections": ["limits"]}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=2)
    la = await_local_ctx_for(Permissions.from_dict({}), is_local_admin=True)
    matrix = {"view_roles": ["moderator", "local_admin"],
              "edit_roles": ["local_admin"]}
    assert not access_srv.can_view_param(user, matrix)      # user — вне списка
    assert access_srv.can_view_param(mod, matrix)
    assert access_srv.can_view_param(la, matrix)
    # пустые view = только global admin
    strict = {"view_roles": [], "edit_roles": []}
    assert not access_srv.can_view_param(mod, strict)
    assert not access_srv.can_view_param(la, strict)


def test_hidden_fold_legacy_hides_local_admin():
    """Легаси hidden_from_local=true (edit не содержит local_admin) →
    локальный админ не видит ключ; модератор-грант — видит."""
    from services.permissions import Permissions
    mod = AccessCtx(role_global="moderator", role_chat=None,
                    perms_global=Permissions.from_dict(
                        {"sections": ["limits"]}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=2)
    la = await_local_ctx_for(Permissions.from_dict({}), is_local_admin=True)
    # edit_min_role=global_admin → edit_roles=[] → union не вернёт local_admin
    matrix = access_srv._normalize_perms(
        {"view_min_role": "user", "edit_min_role": "global_admin",
         "hidden_from_local": True})
    assert matrix["view_roles"] == ["user", "moderator"]
    assert matrix["edit_roles"] == []
    assert access_srv.can_view_param(mod, matrix)
    assert not access_srv.can_view_param(la, matrix)


def test_edit_by_flags_requires_chat_grant():
    """Фикс R1 (F-7 §2.3/§6): правка в chat-скоупе — только с грантом
    chat_admins; глобальный moderator без гранта — только чтение."""
    from services.permissions import Permissions
    mod = await_local_ctx_for(
        Permissions.from_dict({"sections": ["limits"]}), is_local_admin=False)
    matrix = {"view_roles": ["moderator", "local_admin"],
              "edit_roles": ["moderator", "local_admin"]}
    assert not access_srv.can_edit_param(mod, matrix)       # нет гранта → RO
    custom_ga = await_local_ctx_for(
        Permissions.from_dict({"wildcard": True}), is_local_admin=False)
    assert access_srv.can_edit_param(custom_ga, matrix)     # global admin


def test_edit_requires_chat_grant_and_flag():
    """chat-moderator грант правит по edit_roles; локальный админ — тоже;
    флаг без роли → нельзя; ключ + грант → можно."""
    from services.permissions import Permissions
    chat_mod = AccessCtx(role_global="moderator", role_chat="moderator",
                         perms_global=Permissions.from_dict(
                             {"sections": ["limits"]}),
                         perms_chat=Permissions.from_dict(
                             {"sections": ["limits"]}),
                         is_global_admin=False, is_local_admin=False, rank=2)
    matrix = {"view_roles": ["moderator", "local_admin"],
              "edit_roles": ["moderator", "local_admin"]}
    assert access_srv.can_edit_param(chat_mod, matrix)
    strict = {"view_roles": ["moderator", "local_admin"],
              "edit_roles": ["local_admin"]}
    assert not access_srv.can_edit_param(chat_mod, strict)  # флаг без роли
    local = AccessCtx(role_global="user", role_chat="local_admin",
                      perms_global=Permissions.from_dict({}),
                      perms_chat=Permissions.from_dict(
                          {"sections": ["limits"]}),
                      is_global_admin=False, is_local_admin=True, rank=3)
    assert access_srv.can_edit_param(local, strict)
    assert access_srv.can_view_param(chat_mod, matrix)      # чтение — можно


def test_eligible_type_custom_alias_by_rank():
    """spec §3.2.5: custom-роль → алиас по rank (4→неявный global,
    3→local_admin, 2→moderator, 1→user); грант чата — приоритетнее."""
    from services.permissions import Permissions
    for rank, expected in ((4, None), (3, "local_admin"),
                           (2, "moderator"), (1, "user")):
        ctx = AccessCtx(role_global="custom", role_chat=None,
                        perms_global=Permissions.from_dict({}),
                        perms_chat=Permissions.from_dict({}),
                        is_global_admin=(rank == 4), is_local_admin=False,
                        rank=rank)
        if rank == 4:
            assert ctx.is_global_admin
        else:
            assert access_srv.eligible_type(ctx) == expected
    ctx = AccessCtx(role_global="user", role_chat="moderator",
                    perms_global=Permissions.from_dict({}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=2)
    assert access_srv.eligible_type(ctx) == "moderator"


def await_local_ctx_for(perms, is_local_admin):
    """Имя сохранено для читаемости тестов; ctx — синхронный dataclass."""
    from services.roles import AccessCtx
    return AccessCtx(
        role_global="user", role_chat="local_admin" if is_local_admin else None,
        perms_global=perms, perms_chat=perms,
        is_global_admin=bool(perms.wildcard), is_local_admin=is_local_admin,
        rank=3 if is_local_admin else 2)
