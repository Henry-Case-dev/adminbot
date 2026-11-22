"""MOD-ACL-UX-01 M4C — ACL-hardening S1/S2/S3 (security).

Контракт: plans/features/mod-acl-ux-01/evidence/m4c/
acl-hardening-contract-2026-11-22.md §3–§5.

S1 — 5 write-маршрутов ролей/админов (`POST /api/admins`,
`POST /api/admins/remove`, `POST /api/roles`, `DELETE /api/roles/{name}`,
`POST /api/roles/{name}/rename`) требуют effective global admin
(`requires_global_admin`), а не `section.access`. Read-маршруты остаются
под `section.access`.

S2 — инварианты по **назначенным** админам: I2 (последний wildcard-админ) и
I1 (последний effective-global админ), только переход `>0 → 0`; check +
write в одной per-app критической секции.

БД не поднимается: `_Db` — мини-хранилище bot_roles/bot_admins с разбором
DML существующих методов `ConfigCache` (upsert/remove/rename/delete +
reload). Это не мок проверяемого поведения: статусы и итоговое состояние
ролей/админов читаются после реального выполнения маршрута.
"""
import asyncio
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import httpx
import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from services.permissions import Permissions, RoleGuardError
from services import roles as roles_srv
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_M4C_ACL_HARDENING"

OWNER_ID = 5885953495          # роль `admin` (legacy-имя, wildcard)
GLOBAL_TYPE_ID = 880000111     # role_type=global_admin, права ПУСТЫЕ (I1 без I2)
CUSTOM_ACCESS_ID = 880000333   # custom-роль: sections ["access"]
MODERATOR_ID = 880000555
LOCAL_ADMIN_ID = 880000888
PLAIN_USER_ID = 880000666
WILDCARD_CUSTOM_ID = 880000777  # custom-роль только с wildcard
NEW_ADMIN_ID = 880000999

ROLES = {
    "admin": {"permissions": {"wildcard": True}, "is_custom": False,
              "role_type": None},
    "global_type": {"permissions": {}, "is_custom": False,
                    "role_type": "global_admin"},
    "moderator": {"permissions": {"sections": ["limits"],
                                  "actions": ["control.restart"]},
                  "is_custom": False, "role_type": "moderator"},
    "local_admin": {"permissions": {"sections": ["limits", "flags"]},
                    "is_custom": False, "role_type": "local_admin"},
    "user": {"permissions": {}, "is_custom": False, "role_type": "user"},
    "custom_access": {"permissions": {"sections": ["access"]},
                      "is_custom": True, "role_type": None},
    "wildcard_custom": {"permissions": {"wildcard": True},
                        "is_custom": True, "role_type": None},
    "custom_role": {"permissions": {"sections": ["limits"]},
                    "is_custom": True, "role_type": None},
}

ADMINS = {
    OWNER_ID: "admin",
    GLOBAL_TYPE_ID: "global_type",
    CUSTOM_ACCESS_ID: "custom_access",
    MODERATOR_ID: "moderator",
    LOCAL_ADMIN_ID: "local_admin",
    PLAIN_USER_ID: "user",
    WILDCARD_CUSTOM_ID: "wildcard_custom",
}

WRITE_ROUTES = (
    ("post", "/api/admins", {"telegram_id": NEW_ADMIN_ID, "role_name": "user"}),
    ("post", "/api/admins/remove", {"telegram_id": MODERATOR_ID}),
    ("post", "/api/roles", {"role_name": "route_probe",
                            "permissions": {"sections": ["limits"]}}),
    ("delete", "/api/roles/custom_role", None),
    ("post", "/api/roles/custom_role/rename", {"new_name": "custom_role2"}),
)


def make_init_data(user_id: int = OWNER_ID) -> str:
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


def _hdr(user_id: int = OWNER_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


# ── мини-хранилище (реальные DML ConfigCache, без PostgreSQL) ──────────────

class _Db:
    def __init__(self, roles=None, admins=None):
        self.roles = {name: dict(spec)
                      for name, spec in (roles or ROLES).items()}
        self.admins = dict(ADMINS if admins is None else admins)
        self.added_by = {tg: None for tg in self.admins}

    def snapshot(self):
        """Полный снимок состояния для «ничего не изменилось»."""
        return (json.dumps(self.roles, sort_keys=True),
                json.dumps(self.admins, sort_keys=True))


class _Conn:
    def __init__(self, db: _Db):
        self.db = db

    async def fetch(self, sql, *args):
        if "FROM bot_settings" in sql:
            return []
        if "FROM bot_roles" in sql:
            return [
                {"role_name": name,
                 "permissions": json.dumps(spec.get("permissions") or {}),
                 "is_custom": spec.get("is_custom", False),
                 "role_type": spec.get("role_type")}
                for name, spec in self.db.roles.items()
            ]
        if "FROM bot_admins" in sql:
            return [
                {"telegram_id": tg, "role_name": role,
                 "added_by": self.db.added_by.get(tg), "created_at": None}
                for tg, role in self.db.admins.items()
            ]
        if "FROM param_permissions" in sql:
            return []
        return []

    async def fetchrow(self, sql, *args):
        if "count(*) AS n FROM bot_admins" in sql:
            role_name = args[0]
            return {"n": sum(1 for r in self.db.admins.values()
                             if r == role_name)}
        return None

    async def execute(self, sql, *args):
        # Реальный PG-вызов уступает event loop; fake без await делал бы
        # конкурентные запросы строго последовательными и маскировал гонку.
        await asyncio.sleep(0)
        stmt = " ".join(sql.split())
        if stmt.startswith("INSERT INTO bot_admins"):
            telegram_id, role_name, added_by = args
            self.db.admins[int(telegram_id)] = role_name
            self.db.added_by[int(telegram_id)] = added_by
            return "INSERT 0 1"
        if stmt.startswith("DELETE FROM bot_admins"):
            telegram_id = int(args[0])
            existed = self.db.admins.pop(telegram_id, None) is not None
            self.db.added_by.pop(telegram_id, None)
            return "DELETE 1" if existed else "DELETE 0"
        if stmt.startswith("INSERT INTO bot_roles"):
            if "SELECT" in stmt:            # rename_role: копия роли
                old_name, new_name = args
                source = self.db.roles.get(old_name)
                if source is not None:
                    self.db.roles[new_name] = dict(source)
                return "INSERT 0 1"
            role_name, permissions, is_custom = args
            existing = self.db.roles.get(role_name) or {}
            self.db.roles[role_name] = {
                "permissions": (json.loads(permissions)
                                if isinstance(permissions, str)
                                else permissions),
                "is_custom": bool(is_custom),
                "role_type": existing.get("role_type"),
            }
            return "INSERT 0 1"
        if stmt.startswith("UPDATE bot_admins SET role_name"):
            old_name, new_name = args
            for telegram_id, role_name in list(self.db.admins.items()):
                if role_name == old_name:
                    self.db.admins[telegram_id] = new_name
            return "UPDATE 1"
        if stmt.startswith("DELETE FROM bot_roles"):
            existed = self.db.roles.pop(args[0], None) is not None
            return "DELETE 1" if existed else "DELETE 0"
        if stmt.startswith("UPDATE param_permissions"):
            return "UPDATE 0"
        return "INSERT 0 1"

    def transaction(self):
        class _Tx:
            async def __aenter__(self_inner):
                return self

            async def __aexit__(self_inner, *exc):
                return False

        return _Tx()


class _Pool:
    def __init__(self, conn: _Conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self_inner):
                return self_inner._pool._conn

            async def __aexit__(self_inner, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _Pg:
    def __init__(self, conn: _Conn):
        self._pool = _Pool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self):
        pass

    async def close(self):
        pass


def _seed(cache: ConfigCache, db: _Db) -> None:
    """RAM-снимок как после `_load_all`; lifespan не переинициализирует."""
    cache._roles = {
        name: {"permissions": dict(spec.get("permissions") or {}),
               "is_custom": bool(spec.get("is_custom", False)),
               "role_type": spec.get("role_type")}
        for name, spec in db.roles.items()
    }
    cache._permissions = {
        name: Permissions.from_dict(role["permissions"])
        for name, role in cache._roles.items()
    }
    cache._admins = dict(db.admins)
    cache._admins_full = {
        tg: {"telegram_id": tg, "role_name": role,
             "added_by": None, "created_at": None}
        for tg, role in db.admins.items()
    }
    cache._settings = {}
    cache._settings_updated_at = {}
    cache._pg_available = True
    cache._initialized = True


@pytest.fixture(autouse=True)
def _api_token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


@pytest.fixture
def make_client():
    """Фабрика клиента: свой store на тест, реальный ConfigCache + reload."""
    def _make(roles=None, admins=None):
        db = _Db(roles=roles, admins=admins)
        cache = ConfigCache(pg=_Pg(_Conn(db)), retry_attempts=1, retry_delay=0)
        _seed(cache, db)
        client = TestClient(create_app(cache))
        client.cache = cache
        client.db = db
        return client
    return _make


def _call(client, method, path, payload, user_id):
    if method == "delete":
        return client.delete(path, headers=_hdr(user_id))
    return client.post(path, json=payload, headers=_hdr(user_id))


# ── S1: write-граница ──────────────────────────────────────────────────────

class TestS1NonGlobalWritesForbidden:
    @pytest.mark.parametrize("actor", [CUSTOM_ACCESS_ID, MODERATOR_ID,
                                       LOCAL_ADMIN_ID, PLAIN_USER_ID])
    @pytest.mark.parametrize("method,path,payload", WRITE_ROUTES)
    def test_non_global_403_on_all_write_routes(
            self, make_client, actor, method, path, payload):
        client = make_client()
        before = client.db.snapshot()
        resp = _call(client, method, path, payload, actor)
        assert resp.status_code == 403, (actor, path, resp.text)
        assert client.db.snapshot() == before, "403 не должен менять состояние"

    @pytest.mark.parametrize("method,path,payload", WRITE_ROUTES)
    def test_missing_init_data_401(self, make_client, method, path, payload):
        client = make_client()
        if method == "delete":
            resp = client.delete(path)
        else:
            resp = client.post(path, json=payload)
        assert resp.status_code == 401

    @pytest.mark.parametrize("actor", [OWNER_ID, GLOBAL_TYPE_ID,
                                       WILDCARD_CUSTOM_ID])
    @pytest.mark.parametrize("method,path,payload", WRITE_ROUTES)
    def test_effective_global_admin_not_403(
            self, make_client, actor, method, path, payload):
        """global_admin по role_type / wildcard / legacy-имени — не 403."""
        client = make_client()
        resp = _call(client, method, path, payload, actor)
        assert resp.status_code != 403, (actor, path, resp.text)
        assert resp.status_code in (200, 404, 409, 422, 503), resp.text

    def test_legacy_admin_name_with_empty_perms_not_403(self, make_client):
        """legacy-имя `admin`, role_type=NULL, права ПУСТЫЕ → не 403.

        Путь проходит только по имени роли (`deps.user_is_global_admin`),
        не по wildcard/role_type — отдельная строка S1-матрицы."""
        legacy_id = 880001444
        roles = {**ROLES,
                 "admin": {"permissions": {}, "is_custom": False,
                           "role_type": None}}
        client = make_client(roles=roles,
                             admins={legacy_id: "admin",
                                     MODERATOR_ID: "moderator"})
        resp = client.post("/api/admins",
                           json={"telegram_id": NEW_ADMIN_ID,
                                 "role_name": "user"},
                           headers=_hdr(legacy_id))
        assert resp.status_code == 200, resp.text
        assert client.db.admins[NEW_ADMIN_ID] == "user"

    def test_read_paths_remain_section_access(self, make_client):
        """S1 закрывает только мутации: custom `section.access` читает."""
        client = make_client()
        for path in ("/api/admins", "/api/roles", "/api/roles/tree"):
            resp = client.get(path, headers=_hdr(CUSTOM_ACCESS_ID))
            assert resp.status_code == 200, (path, resp.text)
        assert client.get("/api/admins",
                          headers=_hdr(PLAIN_USER_ID)).status_code == 403

    def test_two_step_takeover_blocked(self, make_client):
        """Демоция владельца + самоповышение — оба шага 403, состояние цело."""
        client = make_client()
        before = client.db.snapshot()
        step1 = client.post("/api/admins",
                            json={"telegram_id": OWNER_ID, "role_name": "user"},
                            headers=_hdr(CUSTOM_ACCESS_ID))
        step2 = client.post("/api/admins",
                            json={"telegram_id": CUSTOM_ACCESS_ID,
                                  "role_name": "admin"},
                            headers=_hdr(CUSTOM_ACCESS_ID))
        assert step1.status_code == 403, step1.text
        assert step2.status_code == 403, step2.text
        assert client.db.snapshot() == before
        assert client.db.admins[OWNER_ID] == "admin"
        assert client.db.admins[CUSTOM_ACCESS_ID] == "custom_access"

    def test_self_role_edit_escalation_blocked(self, make_client):
        """custom `section.access` не может выдать себе wildcard/models."""
        client = make_client()
        before = client.db.roles["custom_access"]
        resp = client.post(
            "/api/roles",
            json={"role_name": "custom_access",
                  "permissions": {"wildcard": True}},
            headers=_hdr(CUSTOM_ACCESS_ID))
        assert resp.status_code == 403, resp.text
        assert client.db.roles["custom_access"] == before

    def test_local_admin_chat_grant_still_403(self, make_client):
        """Глобальная роль local_admin (и chat-грант) не даёт ACL-мутаций."""
        client = make_client()
        resp = client.post("/api/admins",
                           json={"telegram_id": NEW_ADMIN_ID,
                                 "role_name": "admin"},
                           headers=_hdr(LOCAL_ADMIN_ID))
        assert resp.status_code == 403
        assert NEW_ADMIN_ID not in client.db.admins

    def test_dm_owner_without_global_role_403(self, make_client):
        """DM-владелец (свой ЛС) без global-роли — 403 (грант не глобальный)."""
        client = make_client()
        resp = client.post(
            "/api/admins",
            json={"telegram_id": PLAIN_USER_ID, "role_name": "admin"},
            headers={**_hdr(PLAIN_USER_ID), "X-Chat-Id": str(PLAIN_USER_ID)})
        assert resp.status_code == 403
        assert client.db.admins[PLAIN_USER_ID] == "user"


# ── S2: инварианты назначенных админов ─────────────────────────────────────

class TestS2AdminLockoutInvariants:
    def test_last_wildcard_admin_reassign_to_user_409(self, make_client):
        """§5.2-1: единственный global/wildcard admin → `user` → 409."""
        client = make_client(admins={OWNER_ID: "admin", MODERATOR_ID: "moderator"})
        before = client.db.snapshot()
        resp = client.post(
            "/api/admins",
            json={"telegram_id": OWNER_ID, "role_name": "user"},
            headers=_hdr(OWNER_ID))
        assert resp.status_code == 409, resp.text
        assert "полным доступом" in resp.json()["detail"]
        assert client.db.snapshot() == before

    def test_last_global_type_admin_remove_409(self, make_client):
        """§5.2-2: global по role_type без wildcard — старый код пропускал."""
        client = make_client(
            admins={GLOBAL_TYPE_ID: "global_type", MODERATOR_ID: "moderator"})
        before = client.db.snapshot()
        resp = client.post("/api/admins/remove",
                           json={"telegram_id": GLOBAL_TYPE_ID},
                           headers=_hdr(GLOBAL_TYPE_ID))
        assert resp.status_code == 409, resp.text
        assert "глобального администратора" in resp.json()["detail"]
        assert client.db.snapshot() == before

    def test_last_global_type_admin_reassign_to_user_409(self, make_client):
        """I1 ловит и upsert-демоцию role_type=global_admin без wildcard."""
        client = make_client(
            admins={GLOBAL_TYPE_ID: "global_type", MODERATOR_ID: "moderator"})
        before = client.db.snapshot()
        resp = client.post(
            "/api/admins",
            json={"telegram_id": GLOBAL_TYPE_ID, "role_name": "user"},
            headers=_hdr(GLOBAL_TYPE_ID))
        assert resp.status_code == 409, resp.text
        assert "глобального администратора" in resp.json()["detail"]
        assert client.db.snapshot() == before

    def test_last_wildcard_admin_remove_409(self, make_client):
        client = make_client(admins={OWNER_ID: "admin", MODERATOR_ID: "moderator"})
        before = client.db.snapshot()
        resp = client.post("/api/admins/remove",
                           json={"telegram_id": OWNER_ID},
                           headers=_hdr(OWNER_ID))
        assert resp.status_code == 409, resp.text
        assert "полным доступом" in resp.json()["detail"]
        assert client.db.snapshot() == before

    def test_two_global_admins_demote_one_200(self, make_client):
        """§5.2-4: второй global admin остаётся — over-block отсутствует."""
        client = make_client(admins={OWNER_ID: "admin",
                                     GLOBAL_TYPE_ID: "global_type"})
        resp = client.post(
            "/api/admins",
            json={"telegram_id": GLOBAL_TYPE_ID, "role_name": "user"},
            headers=_hdr(OWNER_ID))
        assert resp.status_code == 200, resp.text
        assert client.db.admins[GLOBAL_TYPE_ID] == "user"
        assert client.db.admins[OWNER_ID] == "admin"

    def test_role_edit_lockout_two_wildcard_roles_409(self, make_client):
        """§5.2-5: role-guard пропускает (2 wildcard-роли), I2 ловит."""
        client = make_client(
            roles={**ROLES, "admin": {"permissions": {"wildcard": True},
                                      "is_custom": False, "role_type": None},
                   "wildcard_custom": {"permissions": {"wildcard": True},
                                       "is_custom": True, "role_type": None}},
            admins={OWNER_ID: "wildcard_custom", MODERATOR_ID: "moderator"})
        before = client.db.roles["wildcard_custom"]
        resp = client.post(
            "/api/roles",
            json={"role_name": "wildcard_custom",
                  "permissions": {"sections": ["limits"]}},
            headers=_hdr(OWNER_ID))
        assert resp.status_code == 409, resp.text
        assert "полным доступом" in resp.json()["detail"]
        assert client.db.roles["wildcard_custom"] == before

    def test_role_edit_safe_when_other_wildcard_admin_remains_200(self, make_client):
        """§5.2-6: владелец назначен и на вторую wildcard-роль — 200."""
        second_id = 880001222
        client = make_client(
            admins={OWNER_ID: "wildcard_custom", second_id: "admin"})
        resp = client.post(
            "/api/roles",
            json={"role_name": "wildcard_custom",
                  "permissions": {"sections": ["limits"]}},
            headers=_hdr(OWNER_ID))
        assert resp.status_code == 200, resp.text
        assert not client.db.roles["wildcard_custom"]["permissions"].get(
            "wildcard")
        # Второй назначенный wildcard-админ сохраняет wildcard.
        assert client.db.roles["admin"]["permissions"] == {"wildcard": True}

    def test_remove_last_admin_row_409_unchanged(self, make_client):
        """§5.2-7: существующий guard «последний админ» не изменён."""
        client = make_client(admins={OWNER_ID: "admin"})
        resp = client.post("/api/admins/remove",
                           json={"telegram_id": OWNER_ID},
                           headers=_hdr(OWNER_ID))
        assert resp.status_code == 409
        assert "последнего админа" in resp.json()["detail"]

    def test_assign_new_telegram_id_200(self, make_client):
        """§5.2-8: инварианты не убывают — новая строка разрешена."""
        client = make_client()
        resp = client.post("/api/admins",
                           json={"telegram_id": NEW_ADMIN_ID,
                                 "role_name": "moderator"},
                           headers=_hdr(OWNER_ID))
        assert resp.status_code == 200, resp.text
        assert client.db.admins[NEW_ADMIN_ID] == "moderator"

    def test_superuser_admin_wildcard_strip_409(self, make_client):
        """§5.2-9: rename/delete admin — 403; снятие wildcard — 409."""
        client = make_client(admins={OWNER_ID: "admin"})
        assert client.delete("/api/roles/admin",
                             headers=_hdr(OWNER_ID)).status_code == 403
        assert client.post("/api/roles/admin/rename",
                           json={"new_name": "boss"},
                           headers=_hdr(OWNER_ID)).status_code == 403
        resp = client.post("/api/roles",
                           json={"role_name": "admin",
                                 "permissions": {"sections": ["limits"]}},
                           headers=_hdr(OWNER_ID))
        assert resp.status_code == 409, resp.text
        assert client.db.roles["admin"]["permissions"] == {"wildcard": True}

    def test_compound_lockout_rejected(self, make_client):
        """Демоция владельца + отдельное удаление единственного админа."""
        client = make_client(admins={OWNER_ID: "admin", MODERATOR_ID: "moderator"})
        demote = client.post(
            "/api/admins",
            json={"telegram_id": OWNER_ID, "role_name": "moderator"},
            headers=_hdr(OWNER_ID))
        assert demote.status_code == 409, demote.text
        assert client.db.admins[OWNER_ID] == "admin"


# ── S2: анти-дрейф helper'а и no-decrease ──────────────────────────────────

class TestS2HelperAntiDrift:
    def test_is_effective_global_admin_role_matches_deps(self, make_client):
        """§5.2-10: helper считает global-админа так же, как deps."""
        client = make_client()
        cache = client.cache
        checked = 0
        for telegram_id, role_name in cache.admins().items():
            expected = deps_mod.user_is_global_admin(cache, telegram_id)
            actual = roles_srv.is_effective_global_admin_role(
                role_name, cache.roles().get(role_name))
            assert actual is expected, (telegram_id, role_name)
            checked += 1
        assert checked == len(cache.admins())

    def test_i1_and_i2_are_distinct(self):
        """role_type=global_admin без wildcard даёт I1, но не I2."""
        roles = {
            "global_type": {"permissions": {}, "role_type": "global_admin"},
            "admin": {"permissions": {"wildcard": True}, "role_type": None},
            "plain": {"permissions": {}, "role_type": "user"},
        }
        admins = {1: "global_type", 2: "admin", 3: "plain"}
        assert roles_srv.assigned_global_admin_ids(roles, admins) == {1, 2}
        assert roles_srv.assigned_wildcard_admin_ids(roles, admins) == {2}

    def test_no_decrease_allows_repair_from_zero(self):
        """Уже деградированное состояние (0) не блокирует восстановление."""
        roles = {"admin": {"permissions": {"wildcard": True}},
                 "user": {"permissions": {}}}
        before_admins = {1: "user"}
        after_admins = {1: "admin"}
        roles_srv.guard_admin_lockout(
            roles, before_admins, roles, after_admins)   # не raise

    def test_guard_raises_i2_before_i1(self):
        roles = {"admin": {"permissions": {"wildcard": True}}}
        with pytest.raises(RoleGuardError) as exc:
            roles_srv.guard_admin_lockout(
                roles, {1: "admin"}, roles, {})
        assert "полным доступом" in str(exc.value)

    def test_lock_is_per_app_and_loop_keyed(self, make_client):
        """Lock кэшируется на app.state в пределах loop и пересоздаётся
        при смене event loop (module-global ломал бы тесты/второй app)."""
        from web.api import routes as routes_mod

        client = make_client()
        app = client.app

        class _Req:
            pass

        async def _twice():
            req = _Req()
            req.app = app
            first = routes_mod._acl_mutation_lock(req)
            second = routes_mod._acl_mutation_lock(req)
            assert first is second
            return first

        first_loop_lock = asyncio.run(_twice())
        second_loop_lock = asyncio.run(_twice())
        assert first_loop_lock is not second_loop_lock


# ── S2: конкурентность (реальная сериализация) ─────────────────────────────

class TestS2Concurrency:
    def test_concurrent_self_demotions_leave_one_wildcard_admin(self, make_client):
        """M5: без lock обе демоции проходят по одному снимку → 0 админов.

        Оба запроса идут от одного стабильного global-админа
        (role_type=global_admin), поэтому I1 не срабатывает: исключительно
        I2 + сериализация решают исход."""
        second_id = 880001333
        client = make_client(admins={OWNER_ID: "admin",
                                     second_id: "wildcard_custom",
                                     GLOBAL_TYPE_ID: "global_type"})
        app = create_app(client.cache)

        async def _run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                    transport=transport, base_url="http://test") as client_:
                return await asyncio.gather(
                    client_.post("/api/admins",
                                 json={"telegram_id": OWNER_ID,
                                       "role_name": "user"},
                                 headers=_hdr(GLOBAL_TYPE_ID)),
                    client_.post("/api/admins",
                                 json={"telegram_id": second_id,
                                       "role_name": "user"},
                                 headers=_hdr(GLOBAL_TYPE_ID)),
                )

        responses = asyncio.run(_run())
        assert sorted(r.status_code for r in responses) == [200, 409], [
            (r.status_code, r.text) for r in responses]
        wildcard_admins = roles_srv.assigned_wildcard_admin_ids(
            client.cache.roles(), client.cache.admins())
        assert len(wildcard_admins) == 1
