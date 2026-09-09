"""F-14 (dm-user-settings, T-954, spec §2) — DM-права (roles/access).

Матрица: свой id + X-Chat-Id=свой id → is_dm_owner=True / rank=3 /
role_chat=None / DM-пресет (sections без chat_lore и group-секций);
чужой положительный chat_id → is_dm_owner=False; глобальный админ в чужом
ЛС → can_access_chat False (403); can_edit_param: per_chat-ключи True,
keys.* → False; eligible_type(DM) == local_admin; is_local_admin НЕ
выставляется; fail-open (PG down → DM-владелец работает — локальный срез).

Регресс: is_dm_owner=False дефолт (позиционные конструкторы AccessCtx),
can_access_chat без chat_id — прежняя семантика.
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
    """ConfigCache-заглушка (как в test_access.py)."""

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


class _NoPgCache(_FakeCache):
    """PG down: pg=None → DM-ветка обязана работать (локальный срез)."""

    def __init__(self, roles, admins):
        super().__init__(roles, admins, pg=None)


_ROLES = {
    "admin": {"permissions": {"wildcard": True}, "is_custom": False,
              "role_type": "global_admin"},
    "user": {"permissions": {}, "is_custom": False, "role_type": "user"},
}


@pytest.mark.asyncio
async def _cache_for(admins, chat_admins, roles=None, pg_down=False):
    pg = None if pg_down else _FakePg(_FakeConn(chat_admins))
    if pg_down:
        return _NoPgCache(roles or _ROLES, admins)
    return _FakeCache(roles or _ROLES, admins, pg)


# ═══ is_dm_owner: свой / чужой / global admin ═══

@pytest.mark.asyncio
async def test_dm_owner_own_chat():
    """Свой id + X-Chat-Id=свой id (>0) → is_dm_owner=True, rank=3,
    role_chat=None, DM-пресет (БЕЗ chat_lore и group-секций)."""
    cache = await _cache_for({123456: "user"}, {})
    ctx = await access_for(123456, 123456, cache=cache)
    assert ctx.is_dm_owner
    assert ctx.rank == ROLE_TYPE_RANK[ROLE_LOCAL_ADMIN]
    assert ctx.role_chat is None
    assert not ctx.is_local_admin            # НЕ group local_admin
    assert not ctx.is_global_admin
    sections = set(ctx.perms_chat.sections)
    assert sections == {"prompts", "limits", "flags", "reactions",
                        "content", "memory"}
    assert "chat_lore" not in sections


@pytest.mark.asyncio
async def test_dm_not_owner_for_foreign_positive_chat():
    cache = await _cache_for({123456: "user"}, {})
    ctx = await access_for(123456, 999888, cache=cache)
    assert not ctx.is_dm_owner
    assert ctx.role_chat is None
    assert not access_srv.can_access_chat(ctx, 999888)


@pytest.mark.asyncio
async def test_global_admin_foreign_dm_denied():
    """Глобальный админ в ЧУЖОМ ЛС: can_access_chat(chat_id) → False (403)."""
    cache = await _cache_for({5885953495: "admin"}, {})
    ctx = await access_for(5885953495, 999888, cache=cache)
    assert ctx.is_global_admin
    assert not ctx.is_dm_owner
    assert not access_srv.can_access_chat(ctx, 999888)
    # без chat_id (группа/глобал) — прежнее поведение: True
    assert access_srv.can_access_chat(ctx)


@pytest.mark.asyncio
async def test_global_admin_own_dm_is_owner():
    """Глобальный админ в СВОЁМ ЛС — тоже владелец (DM-строка для любого)."""
    cache = await _cache_for({5885953495: "admin"}, {})
    ctx = await access_for(5885953495, 5885953495, cache=cache)
    assert ctx.is_global_admin and ctx.is_dm_owner
    assert access_srv.can_access_chat(ctx, 5885953495)


@pytest.mark.asyncio
async def test_dm_owner_fail_open_pg_down():
    """PG down → DM-владелец работает (локальный срез, без обращений к PG)."""
    cache = await _cache_for({123456: "user"}, {}, pg_down=True)
    ctx = await access_for(123456, 123456, cache=cache)
    assert ctx.is_dm_owner
    assert ctx.rank == 3
    assert "prompts" in ctx.perms_chat.sections


@pytest.mark.asyncio
async def test_dm_owner_can_access_group_still_denied():
    """DM-владелец НЕ получает прав на группы (грантов нет → False)."""
    cache = await _cache_for({123456: "user"}, {})
    ctx = await access_for(123456, 123456, cache=cache)
    assert access_srv.can_access_chat(ctx, 123456)     # свой ЛС
    ctx_group = await access_for(123456, -10001, cache=cache)
    assert not access_srv.can_access_chat(ctx_group, -10001)


# ═══ eligible_type / can_view / can_edit (матрицы) ═══

@pytest.mark.asyncio
async def test_eligible_type_dm_owner_is_local_admin():
    cache = await _cache_for({123456: "user"}, {})
    ctx = await access_for(123456, 123456, cache=cache)
    assert access_srv.eligible_type(ctx) == ROLE_LOCAL_ADMIN


@pytest.mark.asyncio
async def test_can_edit_param_dm_matrix():
    """DM-владелец: per_chat-ключи (limits/flags/reactions/content/memory/
    prompts — edit_roles [local_admin]) → True; keys.* ([]/[]) → False (R17:
    ключи — только BYOK-путь); view — как local_admin."""
    cache = await _cache_for({123456: "user"}, {})
    ctx = await access_for(123456, 123456, cache=cache)
    m_per_chat = access_srv.default_matrix("limits.chat_cooldown_seconds")
    assert access_srv.can_edit_param(ctx, m_per_chat)
    m_prompt = access_srv.default_matrix("prompts.direct_chat_system_prompt")
    assert access_srv.can_edit_param(ctx, m_prompt)
    assert access_srv.can_view_param(ctx, m_prompt)
    m_keys = access_srv.default_matrix("keys.llm_api_key")
    assert not access_srv.can_edit_param(ctx, m_keys)
    assert not access_srv.can_view_param(ctx, m_keys)
    m_models = access_srv.default_matrix("models.llm_timeout")
    assert access_srv.can_view_param(ctx, m_models)      # read-only справка
    # models.* — per_chat=False: доступ на матрице есть, но POST /api/config
    # отдаёт 422 «ключ нельзя переносить на уровень чата» (существующий гейт
    # routes.py — НЕ 403; серверный контракт не меняется)


# ═══ Регресс-инварианты ═══

def test_access_ctx_default_is_dm_owner_false():
    from services.permissions import Permissions
    ctx = AccessCtx(role_global="user", role_chat=None,
                    perms_global=Permissions.from_dict({}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=1)
    assert ctx.is_dm_owner is False


def test_can_access_chat_legacy_signature():
    """can_access_chat(ctx) без chat_id — прежняя семантика (глобальные
    вызовы не меняются)."""
    from services.permissions import Permissions
    mod = AccessCtx(role_global="moderator", role_chat=None,
                    perms_global=Permissions.from_dict(
                        {"sections": ["limits"]}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=2)
    assert access_srv.can_access_chat(mod)              # moderator — чтение
