"""M4C C1 — strict-чтение матрицы и честные 401/403/404/503.

Контракт: plans/features/mod-acl-ux-01/evidence/m4c/c1-contract-2026-11-21.md
§5.2–5.4, §8.1.
  * GET /api/access/param_permissions: strict — PG down/исключение → 503,
    НЕ 200 с дефолтной матрицей; global admin + рабочий пул → 200/622.
  * runtime db_override_map(strict=False) остаётся fail-open (бот жив).
  * cold GET /api/roles|/api/admins|/api/roles/tree → 503; непустой кэш
    (runtime-снимок) при pg=None → прежний 200.
  * superuser rename/delete 403, неизвестная роль 404, занятая/встроенная 409,
    последний админ/wildcard 409 — существующие guards не изменены.
  * custom-роль с section.access: /api/roles доступны, матрица — 403
    (S1 закрыт: чтение остаётся section.access; write-мутации ACL —
    global-admin-only, см. tests/test_mod_acl_ux_m4c_acl_hardening.py).
"""
import asyncio
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services import access as access_srv
from services.config_cache import ConfigCache
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_M4C1_READ"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
CUSTOM_ID = 424242424
USER_ID = 999999999

ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False, "role_type": None},
    {"role_name": "moderator",
     "permissions": {"sections": ["limits"],
                     "actions": ["control.restart", "control.stop",
                                 "control.start"]},
     "is_custom": False, "role_type": "moderator"},
    {"role_name": "user", "permissions": {}, "is_custom": False,
     "role_type": "user"},
    {"role_name": "custom_access",
     "permissions": {"sections": ["access"]},
     "is_custom": True, "role_type": None},
]
ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-11-21T00:00:00+00:00"},
    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
     "added_by": ADMIN_ID, "created_at": "2026-11-21T00:00:01+00:00"},
    {"telegram_id": CUSTOM_ID, "role_name": "custom_access",
     "added_by": ADMIN_ID, "created_at": "2026-11-21T00:00:02+00:00"},
]


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


class _FakeConn:
    def __init__(self, perm_rows=()):
        self._perm_rows = list(perm_rows)
        self.fetch_raises = False

    async def fetch(self, sql, *args):
        if self.fetch_raises:
            raise RuntimeError("PG fetch failed")
        if "bot_settings" in sql:
            return []
        if "bot_roles" in sql:
            return ROLE_ROWS
        if "bot_admins" in sql:
            return ADMIN_ROWS
        if "param_permissions" in sql:
            return self._perm_rows
        return []

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self_inner):
                return self

            async def __aexit__(self_inner, *exc):
                return False

        return _Tx()


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self_inner):
                return self._conn

            async def __aexit__(self_inner, *exc):
                return False

        return _CM()

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self):
        pass

    async def close(self):
        pass


class _NoPoolPg:
    """PG-объект без пула: cold start / обрыв соединения."""

    pool = None

    async def connect(self):
        raise ConnectionError("PG down")

    async def init(self):
        raise ConnectionError("PG down")

    async def close(self):
        pass


def _seed_cache(cache, *, with_pg: bool = True,
                role_rows=None, admin_rows=None) -> ConfigCache:
    """Заполнить RAM-снапшот так же, как _load_all (без init/lifespan)."""
    role_rows = ROLE_ROWS if role_rows is None else role_rows
    admin_rows = ADMIN_ROWS if admin_rows is None else admin_rows
    roles_map = {}
    perms_map = {}
    for r in role_rows:
        perms = r.get("permissions") or {}
        roles_map[r["role_name"]] = {
            "permissions": perms,
            "is_custom": r.get("is_custom", False),
            "role_type": r.get("role_type"),
        }
        perms_map[r["role_name"]] = Permissions.from_dict(perms)
    admins_map = {a["telegram_id"]: a["role_name"] for a in admin_rows}
    cache._roles = roles_map
    cache._permissions = perms_map
    cache._admins = admins_map
    cache._admins_full = {
        a["telegram_id"]: dict(a) for a in admin_rows
    }
    cache._pg_available = bool(with_pg)
    cache._initialized = True
    return cache


@pytest.fixture(autouse=True)
def _reset_matrix_cache():
    access_srv.reset_param_permissions_cache()
    yield
    access_srv.reset_param_permissions_cache()


@pytest.fixture
def monkey_settings(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


def _client(cache, monkey_settings):
    # Без `with TestClient`: lifespan не зовёт cache.init(), и cold-состояние
    # (пустой RAM, pg_available=False) остаётся ровно тем, что задано.
    client = TestClient(create_app(cache))
    client.cache = cache
    return client


def _live_cache(conn=None, *, with_pg=True, role_rows=None,
                admin_rows=None) -> ConfigCache:
    pg = _FakePg(conn or _FakeConn()) if with_pg else _NoPoolPg()
    cache = ConfigCache(pg=pg, retry_attempts=1, retry_delay=0)
    return _seed_cache(cache, with_pg=with_pg,
                       role_rows=role_rows, admin_rows=admin_rows)


# ── 1. Strict matrix ────────────────────────────────────────────────────────

class TestStrictMatrix:
    def test_pool_none_is_503_not_default_matrix(self, monkey_settings):
        cache = _live_cache(with_pg=False)      # seeded RAM, но PG пул None
        client = _client(cache, monkey_settings)
        resp = client.get("/api/access/param_permissions", headers=_hdr())
        assert resp.status_code == 503
        assert "items" not in resp.json(), "503 не подменяется дефолтной матрицей"

    def test_fetch_raises_is_503(self, monkey_settings):
        conn = _FakeConn()
        conn.fetch_raises = True
        cache = _live_cache(conn)
        client = _client(cache, monkey_settings)
        resp = client.get("/api/access/param_permissions", headers=_hdr())
        assert resp.status_code == 503

    def test_global_admin_with_pool_gets_622(self, monkey_settings):
        from services.param_catalog import REGISTRY
        cache = _live_cache()
        client = _client(cache, monkey_settings)
        resp = client.get("/api/access/param_permissions", headers=_hdr())
        assert resp.status_code == 200
        items = resp.json()["items"]
        categorized = [s for s in REGISTRY.values() if s.category is not None]
        assert len(items) == len(categorized) == 622
        assert items["limits.search_max_symbols"]["default"] is True

    def test_non_global_is_403_before_strict_read(self, monkey_settings):
        conn = _FakeConn()
        conn.fetch_raises = True        # строгое чтение НЕ должно вызываться
        cache = _live_cache(conn)
        client = _client(cache, monkey_settings)
        resp = client.get("/api/access/param_permissions",
                          headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_missing_init_data_401(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert client.get("/api/access/param_permissions").status_code == 401

    def test_runtime_fail_open_unchanged(self):
        """strict=False (runtime effective_matrix/can_view) — прежний {}."""
        assert asyncio.run(
            access_srv.db_override_map(_NoPoolPg(), strict=False)) == {}
        conn = _FakeConn()
        conn.fetch_raises = True
        assert asyncio.run(
            access_srv.db_override_map(_FakePg(conn), strict=False)) == {}

    def test_strict_success_updates_runtime_cache(self):
        conn = _FakeConn([
            {"key": "limits.search_max_symbols",
             "value": {"view_roles": ["moderator"], "edit_roles": []}},
        ])
        pg = _FakePg(conn)
        strict_map = asyncio.run(access_srv.db_override_map(pg, strict=True))
        assert strict_map["limits.search_max_symbols"]["view_roles"] == ["moderator"]
        # runtime-путь после успешного strict-чтения видит тот же снимок.
        assert asyncio.run(access_srv.db_override_map(pg, strict=False)) == strict_map


# ── 2. Cold 503 vs seeded 200 ──────────────────────────────────────────────

class TestColdReads:
    def test_cold_roles_admins_tree_503(self, monkey_settings):
        # Guard доступа должен пропустить пользователя (иначе это 403 раньше
        # маршрута). Проверяем именно новую cold-ветку маршрута:
        # roles()/admins() пусты, pg_available=False.
        roles_cold = ConfigCache(pg=_NoPoolPg(), retry_attempts=1, retry_delay=0)
        roles_cold._roles = {}
        roles_cold._admins = {ADMIN_ID: "admin"}
        roles_cold._permissions = {
            "admin": Permissions.from_dict({"wildcard": True})}
        roles_cold._admins_full = {
            ADMIN_ID: ADMIN_ROWS[0]}
        roles_cold._pg_available = False
        client = _client(roles_cold, monkey_settings)
        assert client.get("/api/roles", headers=_hdr()).status_code == 503
        assert client.get("/api/roles/tree", headers=_hdr()).status_code == 503

        admins_cold = ConfigCache(pg=_NoPoolPg(), retry_attempts=1, retry_delay=0)
        admins_cold._roles = {}
        admins_cold._admins = {}
        admins_cold._admins_full = {}
        admins_cold._permissions = {
            "user": Permissions.from_dict({"sections": ["access"]})}
        admins_cold._pg_available = False
        client = _client(admins_cold, monkey_settings)
        assert client.get("/api/admins", headers=_hdr()).status_code == 503

    def test_seeded_cache_without_pg_is_200(self, monkey_settings):
        """Runtime-снимок в RAM: 200 (последний успешный снапшот), не 503."""
        cache = _seed_cache(ConfigCache(pg=_NoPoolPg()), with_pg=False)
        client = _client(cache, monkey_settings)
        roles = client.get("/api/roles", headers=_hdr())
        assert roles.status_code == 200
        assert {r["role_name"] for r in roles.json()["roles"]} == {
            "admin", "moderator", "user", "custom_access"}
        admins = client.get("/api/admins", headers=_hdr())
        assert admins.status_code == 200
        assert len(admins.json()["admins"]) == 3

    def test_tree_existing_role_200_missing_role_404(self, monkey_settings):
        cache = _seed_cache(ConfigCache(pg=_NoPoolPg()), with_pg=False)
        client = _client(cache, monkey_settings)
        ok = client.get("/api/roles/tree?role_name=moderator", headers=_hdr())
        assert ok.status_code == 200
        assert any(s["id"] == "limits" for s in ok.json()["sections"])
        missing = client.get("/api/roles/tree?role_name=nope", headers=_hdr())
        assert missing.status_code == 404

    def test_cold_403_not_masked_by_503(self, monkey_settings):
        """Без права access — 403 (guard отрабатывает раньше cold-проверки)."""
        cache = _seed_cache(ConfigCache(pg=_NoPoolPg()), with_pg=False,
                            role_rows=[], admin_rows=[])
        client = _client(cache, monkey_settings)
        assert client.get("/api/roles", headers=_hdr(USER_ID)).status_code == 403


# ── 3. Guards не изменены ──────────────────────────────────────────────────

class TestRoleGuardsUnchanged:
    def test_superuser_delete_rename_403(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert client.delete("/api/roles/admin", headers=_hdr()).status_code == 403
        assert client.post("/api/roles/admin/rename", headers=_hdr(),
                           json={"new_name": "root"}).status_code == 403

    def test_builtin_delete_rename_409(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert client.delete("/api/roles/moderator",
                             headers=_hdr()).status_code == 409
        assert client.post("/api/roles/moderator/rename", headers=_hdr(),
                           json={"new_name": "mod2"}).status_code == 409

    def test_unknown_role_404(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert client.delete("/api/roles/nope", headers=_hdr()).status_code == 404
        assert client.get("/api/roles/tree?role_name=nope",
                          headers=_hdr()).status_code == 404

    def test_last_admin_409(self, monkey_settings):
        cache = _seed_cache(
            ConfigCache(pg=_NoPoolPg()), with_pg=False,
            role_rows=ROLE_ROWS,
            admin_rows=[ADMIN_ROWS[0]])
        client = _client(cache, monkey_settings)
        resp = client.post("/api/admins/remove", headers=_hdr(),
                           json={"telegram_id": ADMIN_ID})
        assert resp.status_code == 409
        assert "последн" in resp.json()["detail"]

    def test_last_wildcard_admin_409(self, monkey_settings):
        # Два админа, второй без wildcard: удаление единственного wildcard
        # запрещено существующим guard'ом (не новый C1-путь).
        cache = _seed_cache(ConfigCache(pg=_NoPoolPg()), with_pg=False,
                            role_rows=ROLE_ROWS,
                            admin_rows=[ADMIN_ROWS[0], ADMIN_ROWS[1]])
        client = _client(cache, monkey_settings)
        resp = client.post("/api/admins/remove", headers=_hdr(),
                           json={"telegram_id": ADMIN_ID})
        assert resp.status_code == 409
        assert "полным доступом" in resp.json()["detail"]

    def test_section_access_role_matrix_403(self, monkey_settings):
        """custom_access имеет section.access → /api/roles 200, матрица 403.
        S1 закрыт (M4C ACL-hardening): чтение ролей/админов остаётся
        section.access, мутации — global-admin-only; C1 не расширяет и
        не ослабляет сервер."""
        cache = _live_cache()
        client = _client(cache, monkey_settings)
        roles = client.get("/api/roles", headers=_hdr(CUSTOM_ID))
        assert roles.status_code == 200
        matrix = client.get("/api/access/param_permissions",
                            headers=_hdr(CUSTOM_ID))
        assert matrix.status_code == 403
