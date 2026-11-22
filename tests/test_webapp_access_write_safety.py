"""MOD-ACL-UX-01 M4C C3 — запись/409/audit/recheck (backend).

Контракт: plans/features/mod-acl-ux-01/evidence/m4c/c3-contract-2026-11-22.md
§5 (API), §6 (audit), §7 (recheck), §10.1.

Проверяется:
  * роли: revision в GET; create_only/expected_revision → 409
    role_exists/role_absent/revision_mismatch (удалённая роль не
    пересоздаётся); delete/rename stale → 409; no-token upsert — 200;
    оба токена — 422; audit ровно одна строка на реальную мутацию; no-op
    не пишет audit/не двигает ревизию;
  * глобальная матрица: updated_at из fresh snapshot; expect_absent/CAS 409;
    DELETE stale/absent; audit param_global; no-op без записи;
  * чатовый override: атомарный POST (CAS/expect_absent), DELETE reset
    только ключа (другие ключи/глобальная матрица/роли целы), 404
    profile/key, 409 token, значения не тронуты; audit param_chat;
  * audit read: 401/403, limit clamp, entity-фильтр, before_id,
    malformed:true, scope=chat (чужой DM → 403), no-secret;
  * audit fail-closed: ошибка вставки аудита откатывает мутацию (503);
  * recheck: конфликт → отзыв прав → 403 и второй записи нет; 503 при
    недоступном PG; allow → вторая запись; meme-settings — свой гейт;
  * S8-524: /api/memory/embeddings 403 non-global/401 без initData/200 admin;
  * lore/oversight не отдают field='access'.
"""
import copy
import hashlib
import hmac
import inspect
import json
import re
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services import access as access_srv
from services import acl_audit
from services import chat_lore_store
from services import chat_params
from services import roles as roles_srv
from services.config_cache import ConfigCache
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.api import memory_agi as memory_agi_mod
from web.api import routes as routes_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_M4C3_WRITE_SAFETY"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
LOCAL_ID = 7000000101
USER_ID = 999999999
CHAT_ID = -1001234567890
DM_ID = LOCAL_ID
OTHER_DM = 7000000999

KEY = "limits.search_max_symbols"
PARTIAL_KEY = "limits.summary_hybrid_context_chars"
PROMPT_KEY = "prompts.summary_system_prompt"
SECOND_KEY = "limits.summary_hybrid_context_tokens"
SENTINEL_PROMPT = "SENTINEL_PROMPT_TEXT_DO_NOT_LEAK"
SENTINEL_SECRET = "SENTINEL_SECRET_VALUE_DO_NOT_LEAK"
SENTINEL_LAST4 = "SENTINEL_LAST4_DO_NOT_LEAK"
SENTINEL_VALUE = "SENTINEL_VALUE_DO_NOT_LEAK"

ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False, "role_type": None},
    {"role_name": "moderator",
     "permissions": {"sections": ["limits"], "actions": []},
     "is_custom": False, "role_type": "moderator"},
    {"role_name": "local_admin",
     "permissions": {"sections": ["limits", "flags", "reactions", "content",
                                  "chat_lore"], "actions": []},
     "is_custom": False, "role_type": "local_admin"},
    {"role_name": "user", "permissions": {}, "is_custom": False,
     "role_type": "user"},
    {"role_name": "custom_access",
     "permissions": {"sections": ["access"], "params": [KEY]},
     "is_custom": True, "role_type": None},
]
ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin", "added_by": None},
    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
     "added_by": ADMIN_ID},
    {"telegram_id": LOCAL_ID, "role_name": "local_admin",
     "added_by": ADMIN_ID},
]
CHAT_ADMIN_ROWS = [
    {"chat_id": CHAT_ID, "telegram_id": LOCAL_ID,
     "role_name": "local_admin", "added_by": ADMIN_ID},
]


def _ts(seq: int) -> str:
    return f"2026-11-22T12:{seq // 60:02d}:{seq % 60:02d}+00:00"


def _profile(chat_id, params, seq=1):
    return {"chat_id": chat_id, "updated_at": _ts(seq),
            "chat_params": json.dumps(params), "gates_opt_in": False}


class FakeDB:
    """Мини-БД для C3: только таблицы/операции, которые реально трогает код."""

    def __init__(self):
        self.seq = 10
        self.roles = {}
        for r in ROLE_ROWS:
            self.roles[r["role_name"]] = {
                "permissions": copy.deepcopy(r["permissions"]),
                "is_custom": bool(r["is_custom"]),
                "role_type": r.get("role_type"),
            }
        self.admins = {a["telegram_id"]: a["role_name"] for a in ADMIN_ROWS}
        self.chat_admins = [dict(r) for r in CHAT_ADMIN_ROWS]
        self.profiles = {
            CHAT_ID: _profile(CHAT_ID, {
                "overrides": {KEY: 111, SECOND_KEY: 222,
                              PROMPT_KEY: SENTINEL_PROMPT},
                "perm_overrides": {
                    KEY: {"view_roles": ["moderator", "local_admin"],
                          "edit_roles": ["local_admin"]},
                    SECOND_KEY: {"view_roles": ["local_admin"],
                                 "edit_roles": ["local_admin"]},
                },
                "meta": {"updated_by": ADMIN_ID},
            }, seq=10),
            DM_ID: _profile(DM_ID, {
                "perm_overrides": {
                    KEY: {"view_roles": ["local_admin"],
                          "edit_roles": ["local_admin"]}},
                "overrides": {},
            }, seq=11),
        }
        self.param_perms = {
            SECOND_KEY: {
                "value": {"view_roles": ["moderator", "local_admin"],
                          "edit_roles": ["local_admin"]},
                "updated_at": _ts(20),
            },
        }
        self.history = []
        self.fail_audit = False

    def next_ts(self) -> str:
        self.seq += 1
        return _ts(self.seq)

    def add_history(self, chat_id, field, changed_by, old_value, new_value):
        row = {"id": len(self.history) + 1, "chat_id": chat_id,
               "field": field, "changed_by": changed_by,
               "old_value": old_value, "new_value": new_value,
               "created_at": self.next_ts()}
        self.history.append(row)
        return row


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db = db

    @staticmethod
    def _low(sql: str) -> str:
        return " ".join(str(sql).lower().split())

    def transaction(self):
        db = self.db
        snapshot = {
            "roles": copy.deepcopy(db.roles),
            "admins": copy.deepcopy(db.admins),
            "profiles": copy.deepcopy(db.profiles),
            "param_perms": copy.deepcopy(db.param_perms),
            "history": copy.deepcopy(db.history),
            "chat_admins": copy.deepcopy(db.chat_admins),
        }
        conn = self

        class _Tx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                if exc_type is not None:
                    db.roles = snapshot["roles"]
                    db.admins = snapshot["admins"]
                    db.profiles = snapshot["profiles"]
                    db.param_perms = snapshot["param_perms"]
                    db.history = snapshot["history"]
                    db.chat_admins = snapshot["chat_admins"]
                return False

        return _Tx()

    async def execute(self, sql, *args):
        low = self._low(sql)
        db = self.db
        if "insert into chat_lore_history" in low:
            if db.fail_audit and args[1] == "access":
                raise RuntimeError("audit insert failed")
            db.add_history(args[0], args[1], args[2], args[3], args[4])
            return "INSERT 0 1"
        if "insert into bot_admins" in low:
            db.admins[int(args[0])] = args[1]
            return "INSERT 0 1"
        if "delete from bot_admins" in low:
            existed = db.admins.pop(int(args[0]), None) is not None
            return "DELETE 1" if existed else "DELETE 0"
        if "update bot_admins set role_name" in low:
            for tid, name in list(db.admins.items()):
                if name == args[0]:
                    db.admins[tid] = args[1]
            return "UPDATE 1"
        if "insert into bot_roles" in low:
            if "select $2" in low:
                src = db.roles.get(args[0])
                if src is not None:
                    db.roles[args[1]] = copy.deepcopy(src)
            else:
                role = db.roles.setdefault(args[0], {})
                role["permissions"] = json.loads(args[1])
                role["is_custom"] = bool(args[2])
            return "INSERT 0 1"
        if "delete from bot_roles" in low:
            existed = db.roles.pop(args[0], None) is not None
            return "DELETE 1" if existed else "DELETE 0"
        if "update param_permissions set value" in low:
            row = db.param_perms.get(args[0])
            if row is not None:
                row["value"] = json.loads(args[1])
                row["updated_at"] = db.next_ts()
            return "UPDATE 1"
        if "insert into chat_admins" in low:
            db.chat_admins.append({"chat_id": args[0],
                                   "telegram_id": args[1],
                                   "role_name": args[2],
                                   "added_by": args[3]})
            return "INSERT 0 1"
        if "delete from chat_admins" in low:
            before = len(db.chat_admins)
            db.chat_admins = [
                r for r in db.chat_admins
                if not (r["chat_id"] == args[0]
                        and r["telegram_id"] == args[1])]
            return ("DELETE 1" if len(db.chat_admins) < before
                    else "DELETE 0")
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        low = self._low(sql)
        db = self.db
        if "from param_permissions" in low and low.startswith("select"):
            row = db.param_perms.get(args[0])
            return dict(row) if row else None
        if "insert into param_permissions" in low:
            row = {"key": args[0], "value": json.loads(args[1]),
                   "updated_at": db.next_ts()}
            db.param_perms[args[0]] = row
            return dict(row)
        if "update param_permissions" in low:
            row = db.param_perms.get(args[0])
            if row is None:
                return None
            if " and updated_at = " in low and str(row["updated_at"]) != str(args[2]):
                return None
            row["value"] = json.loads(args[1])
            row["updated_at"] = db.next_ts()
            return dict(row)
        if "delete from param_permissions" in low:
            row = db.param_perms.get(args[0])
            if row is None:
                return None
            if " and updated_at = " in low and str(row["updated_at"]) != str(args[1]):
                return None
            db.param_perms.pop(args[0], None)
            return dict(row)
        if "from chat_profiles" in low:
            row = db.profiles.get(args[0])
            if row is None:
                return None
            out = dict(row)
            out["chat_params"] = (json.loads(row["chat_params"])
                                  if isinstance(row["chat_params"], str)
                                  else row["chat_params"])
            return out
        if "update chat_profiles" in low:
            row = db.profiles.get(args[0])
            if row is None:
                return None
            if " and updated_at = " in low and str(row["updated_at"]) != str(args[2]):
                return None
            row["chat_params"] = args[1]
            row["updated_at"] = db.next_ts()
            out = dict(row)
            out["chat_params"] = json.loads(row["chat_params"])
            return out
        if "select count(*) as n from bot_admins" in low:
            n = sum(1 for r in db.admins.values() if r == args[0])
            return {"n": n}
        if "from chat_admins" in low:
            for r in db.chat_admins:
                if r["chat_id"] == args[0] and r["telegram_id"] == args[1]:
                    return dict(r)
            return None
        if "select 1 from chat_profiles" in low:
            return {"?column?": 1} if args[0] in db.profiles else None
        return None

    async def fetch(self, sql, *args):
        low = self._low(sql)
        db = self.db
        if "from chat_lore_history" in low:
            rows = [dict(r) for r in db.history if r["chat_id"] == args[0]]
            if "field = $2" in low:
                rows = [r for r in rows if r["field"] == args[1]]
            rest = list(args[2:])
            if "new_value like" in low:
                pattern = str(rest.pop(0))
                ent = pattern.replace('%"entity":"', "").replace('"%', "")
                rows = [r for r in rows if f'"entity":"{ent}"'
                        in (r.get("new_value") or "")]
            if "id <" in low:
                before = int(rest.pop(0))
                rows = [r for r in rows if int(r["id"]) < before]
            limit = int(args[-1])
            rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            return rows[:limit]
        if "from bot_settings" in low:
            return []
        if "from bot_roles" in low:
            return [{"role_name": name,
                     "permissions": json.dumps(role["permissions"]),
                     "is_custom": role["is_custom"],
                     "role_type": role.get("role_type")}
                    for name, role in sorted(db.roles.items())]
        if "from bot_admins" in low:
            return [{"telegram_id": tid, "role_name": role,
                     "added_by": None, "created_at": None}
                    for tid, role in sorted(db.admins.items())]
        if "from param_permissions" in low:
            return [{"key": k, "value": v["value"],
                     "updated_at": v["updated_at"]}
                    for k, v in sorted(db.param_perms.items())]
        if "from chat_admins" in low:
            return [dict(r) for r in db.chat_admins
                    if r["chat_id"] == args[0]]
        return []


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False

        return _CM()

    async def close(self):
        pass


class FakePg:
    def __init__(self, conn):
        self.pool = FakePool(conn)

    async def connect(self):
        pass

    async def init(self):
        pass

    async def close(self):
        pass


class NoPoolPg:
    pool = None

    async def connect(self):
        raise ConnectionError("PG down")

    async def init(self):
        raise ConnectionError("PG down")

    async def close(self):
        pass


def _seed_cache(cache, db: FakeDB) -> ConfigCache:
    roles_map = {}
    perms_map = {}
    for name, role in db.roles.items():
        roles_map[name] = {
            "permissions": copy.deepcopy(role["permissions"]),
            "is_custom": role["is_custom"],
            "role_type": role.get("role_type"),
        }
        perms_map[name] = Permissions.from_dict(role["permissions"])
    cache._roles = roles_map
    cache._permissions = perms_map
    cache._admins = dict(db.admins)
    cache._admins_full = {
        tid: {"telegram_id": tid, "role_name": role,
              "added_by": None, "created_at": None}
        for tid, role in db.admins.items()}
    cache._pg_available = True
    cache._initialized = True
    return cache


def _cache(db: FakeDB) -> ConfigCache:
    cache = ConfigCache(pg=FakePg(FakeConn(db)), retry_attempts=1,
                        retry_delay=0)
    return _seed_cache(cache, db)


def _cold_cache() -> ConfigCache:
    cache = ConfigCache(pg=NoPoolPg(), retry_attempts=1, retry_delay=0)
    cache._roles = {}
    cache._permissions = {}
    cache._admins = {}
    cache._admins_full = {}
    cache._pg_available = False
    return cache


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(),
                         hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


@pytest.fixture(autouse=True)
def _reset_matrix_cache():
    access_srv.reset_param_permissions_cache()
    yield
    access_srv.reset_param_permissions_cache()


@pytest.fixture
def monkey_settings(monkeypatch):
    fake = types.SimpleNamespace(API_TOKEN=TEST_TOKEN,
                                 ADMIN_USER_ID=ADMIN_ID)
    monkeypatch.setattr(deps_mod, "settings", fake)
    monkeypatch.setattr(routes_mod, "settings", fake, raising=False)
    monkeypatch.setattr(memory_agi_mod, "settings", fake, raising=False)


def _client(cache, monkey_settings):
    client = TestClient(create_app(cache))
    client.cache = cache
    return client


def _role(db, name):
    return db.roles[name]


def _audit_rows(db):
    return [r for r in db.history if r["field"] == "access"]


# ═══ 1. Роли: revision/409/audit ═════════════════════════════════════════════

class TestRolesRevision:
    def test_get_roles_has_revision(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.get("/api/roles", headers=_hdr())
        assert resp.status_code == 200
        by_name = {r["role_name"]: r for r in resp.json()["roles"]}
        assert "revision" in by_name["custom_access"]
        assert by_name["custom_access"]["revision"] == \
            roles_srv.role_revision(
                "custom_access",
                by_name["custom_access"]["permissions"],
                by_name["custom_access"]["role_type"],
                by_name["custom_access"]["is_custom"])

    def test_create_only_conflict_role_exists(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        before = copy.deepcopy(_role(db, "custom_access"))
        resp = client.post("/api/roles", headers=_hdr(), json={
            "role_name": "custom_access", "permissions": {"sections": ["flags"]},
            "create_only": True})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["reason"] == "role_exists"
        assert detail["current_revision"]
        assert detail["current"]["permissions"] == Permissions.from_dict(
            before["permissions"]).to_dict()
        assert _role(db, "custom_access") == before
        assert _audit_rows(db) == []

    def test_expected_revision_does_not_recreate_absent_role(
            self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.post("/api/roles", headers=_hdr(), json={
            "role_name": "deleted_role", "permissions": {},
            "expected_revision": "0" * 64})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["reason"] == "role_absent"
        assert detail["current_revision"] is None
        assert "deleted_role" not in db.roles
        assert _audit_rows(db) == []

    def test_stale_revision_rejects_update(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        before = copy.deepcopy(_role(db, "custom_access"))
        resp = client.post("/api/roles", headers=_hdr(), json={
            "role_name": "custom_access",
            "permissions": {"sections": ["flags"]},
            "expected_revision": "f" * 64})
        assert resp.status_code == 409
        assert resp.json()["detail"]["reason"] == "revision_mismatch"
        assert _role(db, "custom_access") == before
        assert _audit_rows(db) == []

    def test_both_tokens_422(self, monkey_settings):
        client = _client(_cache(FakeDB()), monkey_settings)
        resp = client.post("/api/roles", headers=_hdr(), json={
            "role_name": "x", "permissions": {},
            "create_only": True, "expected_revision": "a" * 64})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "ambiguous_tokens"

    def test_no_token_upsert_compat_and_audit(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.post("/api/roles", headers=_hdr(), json={
            "role_name": "custom_access",
            "permissions": {"sections": ["flags", "limits"]}})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["revision"] == roles_srv.role_revision(
            "custom_access", body["permissions"], body.get("role_type"),
            body["is_custom"])
        rows = _audit_rows(db)
        assert len(rows) == 1
        event = json.loads(rows[0]["new_value"])
        assert event["entity"] == "role" and event["op"] == "update"
        assert event["after"]["added"]["sections"] == ["flags", "limits"]
        assert rows[0]["old_value"] == ""
        assert rows[0]["chat_id"] == 0
        assert rows[0]["changed_by"] == ADMIN_ID

    def test_role_noop_does_not_write_audit(self, monkey_settings):
        db = FakeDB()
        cache = _cache(db)
        client = _client(cache, monkey_settings)
        role = cache.roles()["custom_access"]
        resp = client.post("/api/roles", headers=_hdr(), json={
            "role_name": "custom_access",
            "permissions": role["permissions"],
            "expected_revision": roles_srv.role_revision(
                "custom_access", role["permissions"], role.get("role_type"),
                role["is_custom"])})
        assert resp.status_code == 200
        assert resp.json()["unchanged"] is True
        assert _audit_rows(db) == []

    def test_delete_stale_revision_409(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.delete("/api/roles/custom_access",
                             headers=_hdr(),
                             params={"expected_revision": "0" * 64})
        assert resp.status_code == 409
        assert resp.json()["detail"]["reason"] == "revision_mismatch"
        assert "custom_access" in db.roles
        assert _audit_rows(db) == []

    def test_rename_stale_revision_409(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.post("/api/roles/custom_access/rename",
                           headers=_hdr(),
                           json={"new_name": "renamed",
                                 "expected_revision": "0" * 64})
        assert resp.status_code == 409
        assert resp.json()["detail"]["reason"] == "revision_mismatch"
        assert "custom_access" in db.roles
        assert "renamed" not in db.roles

    def test_delete_and_rename_audit(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        revision = roles_srv.role_revision(
            "custom_access", _role(db, "custom_access")["permissions"],
            _role(db, "custom_access").get("role_type"),
            _role(db, "custom_access")["is_custom"])
        resp = client.post("/api/roles/custom_access/rename", headers=_hdr(),
                           json={"new_name": "custom_renamed",
                                 "expected_revision": revision})
        assert resp.status_code == 200, resp.text
        rows = _audit_rows(db)
        assert json.loads(rows[-1]["new_value"])["op"] == "rename"
        resp = client.delete("/api/roles/custom_renamed", headers=_hdr())
        assert resp.status_code == 200, resp.text
        rows = _audit_rows(db)
        event = json.loads(rows[-1]["new_value"])
        assert event["op"] == "delete"
        assert event["before"]["sections"] == ["access"]
        assert "custom_renamed" not in db.roles


# ═══ 2. Глобальная матрица: updated_at/CAS/audit ════════════════════════════

class TestGlobalMatrix:
    def test_get_includes_fresh_updated_at(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.get("/api/access/param_permissions", headers=_hdr())
        assert resp.status_code == 200
        item = resp.json()["items"][SECOND_KEY]
        assert item["updated_at"].startswith("2026-11-22T12:00:20")
        assert item["default"] is False

    def test_get_legacy_partial_override_keeps_effective_semantics(
            self, monkey_settings):
        """C3: updated_at читается из snapshot, но effective_matrix по-прежнему
        получает СЫРОЕ легаси-значение (missing-поля наследуют дефолт)."""
        db = FakeDB()
        db.param_perms[SECOND_KEY] = {
            "value": {"view_min_role": "moderator"},
            "updated_at": "2026-11-22T12:10:00+00:00",
        }
        client = _client(_cache(db), monkey_settings)
        item = client.get("/api/access/param_permissions",
                          headers=_hdr()).json()["items"][SECOND_KEY]
        # view_min_role=moderator → [moderator, local_admin]; edit не задан →
        # наследуется из дефолта (local_admin), view |= edit.
        assert item["view_roles"] == ["moderator", "local_admin"]
        assert item["edit_roles"] == ["local_admin"]
        assert item["updated_at"].startswith("2026-11-22T12:10:00")

    def test_expect_absent_conflict_override_exists(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.put("/api/access/param_permissions/" + SECOND_KEY,
                          headers=_hdr(),
                          json={"view_roles": ["user"],
                                "expect_absent": True})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["reason"] == "override_exists"
        assert detail["current"]["view_roles"] == ["moderator", "local_admin"]
        assert _audit_rows(db) == []

    def test_cas_mismatch_conflict(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.put("/api/access/param_permissions/" + SECOND_KEY,
                          headers=_hdr(),
                          json={"view_roles": ["user"],
                                "expected_updated_at": _ts(999)})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["reason"] == "revision_mismatch"
        assert detail["current_updated_at"].startswith("2026-11-22T12:00:20")
        assert db.param_perms[SECOND_KEY]["value"]["view_roles"] == \
            ["moderator", "local_admin"]

    def test_cas_success_updated_at_and_audit(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        token = db.param_perms[SECOND_KEY]["updated_at"]
        resp = client.put("/api/access/param_permissions/" + SECOND_KEY,
                          headers=_hdr(),
                          json={"view_roles": ["user"],
                                "expected_updated_at": token})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["view_roles"] == ["user"]
        assert body["updated_at"] and body["updated_at"] != token
        rows = _audit_rows(db)
        assert len(rows) == 1
        event = json.loads(rows[0]["new_value"])
        assert event["entity"] == "param_global"
        assert event["key"] == SECOND_KEY
        assert event["before"]["view_roles"] == ["moderator", "local_admin"]
        assert event["after"]["view_roles"] == ["user"]
        # Секретов/значений нет.
        assert SENTINEL_PROMPT not in rows[0]["new_value"]
        assert "last4" not in rows[0]["new_value"]

    def test_noop_no_audit_and_token_unchanged(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        token = db.param_perms[SECOND_KEY]["updated_at"]
        resp = client.put("/api/access/param_permissions/" + SECOND_KEY,
                          headers=_hdr(),
                          json={"view_roles": ["moderator", "local_admin"],
                                "edit_roles": ["local_admin"],
                                "expected_updated_at": token})
        assert resp.status_code == 200
        assert resp.json()["unchanged"] is True
        assert db.param_perms[SECOND_KEY]["updated_at"] == token
        assert _audit_rows(db) == []

    def test_delete_stale_absent_and_404(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.delete("/api/access/param_permissions/" + SECOND_KEY,
                             headers=_hdr(),
                             params={"expected_updated_at": _ts(999)})
        assert resp.status_code == 409
        assert resp.json()["detail"]["reason"] == "revision_mismatch"
        assert SECOND_KEY in db.param_perms
        resp = client.delete("/api/access/param_permissions/limits.nope",
                             headers=_hdr(),
                             params={"expected_updated_at": _ts(1)})
        assert resp.status_code == 409
        assert resp.json()["detail"]["reason"] == "override_absent"
        resp = client.delete("/api/access/param_permissions/limits.nope",
                             headers=_hdr())
        assert resp.status_code == 404

    def test_delete_success_audit_reset(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        token = db.param_perms[SECOND_KEY]["updated_at"]
        resp = client.delete("/api/access/param_permissions/" + SECOND_KEY,
                             headers=_hdr(),
                             params={"expected_updated_at": token})
        assert resp.status_code == 200, resp.text
        assert SECOND_KEY not in db.param_perms
        event = json.loads(_audit_rows(db)[-1]["new_value"])
        assert event["op"] == "reset" and event["after"] is None

    def test_ambiguous_tokens_422(self, monkey_settings):
        client = _client(_cache(FakeDB()), monkey_settings)
        resp = client.put("/api/access/param_permissions/" + SECOND_KEY,
                          headers=_hdr(),
                          json={"view_roles": ["user"], "expect_absent": True,
                                "expected_updated_at": _ts(1)})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "ambiguous_tokens"


# ═══ 3. Чатовый override: атомарность/CAS/reset/audit ═══════════════════════

def _chat_url(chat_id=CHAT_ID, key=KEY):
    return (f"/api/access/chats/{chat_id}/param_permissions/"
            + urllib.parse.quote(key, safe="."))


class TestChatOverride:
    def test_cas_conflict_only_key_no_values(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        before = copy.deepcopy(db.profiles[CHAT_ID])
        resp = client.post(_chat_url(), headers=_hdr(), json={
            "view_roles": ["user"], "expected_updated_at": _ts(999)})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["conflicting"] == [KEY]
        assert "your_value" not in json.dumps(detail)
        assert "server_value" not in json.dumps(detail)
        assert db.profiles[CHAT_ID] == before
        assert _audit_rows(db) == []

    def test_expect_absent_existing(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.post(_chat_url(), headers=_hdr(), json={
            "view_roles": ["user"], "expect_absent": True})
        assert resp.status_code == 409
        assert resp.json()["detail"]["reason"] == "override_exists"
        assert _audit_rows(db) == []

    def test_post_success_audit_and_other_keys_intact(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        token = db.profiles[CHAT_ID]["updated_at"]
        resp = client.post(_chat_url(), headers=_hdr(), json={
            "view_roles": ["user"], "expected_updated_at": token})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["updated_at"] and body["updated_at"] != token
        params = json.loads(db.profiles[CHAT_ID]["chat_params"])
        assert params["perm_overrides"][KEY] == {
            "view_roles": ["user"], "edit_roles": []}
        assert SECOND_KEY in params["perm_overrides"]
        assert params["overrides"][SECOND_KEY] == 222
        event = json.loads(_audit_rows(db)[-1]["new_value"])
        assert event["entity"] == "param_chat" and event["key"] == KEY
        assert event["before"]["edit_roles"] == ["local_admin"]
        assert SENTINEL_PROMPT not in _audit_rows(db)[-1]["new_value"]

    def test_noop_unchanged(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        token = db.profiles[CHAT_ID]["updated_at"]
        resp = client.post(_chat_url(), headers=_hdr(), json={
            "view_roles": ["moderator", "local_admin"],
            "edit_roles": ["local_admin"],
            "expected_updated_at": token})
        assert resp.status_code == 200
        assert resp.json()["unchanged"] is True
        assert db.profiles[CHAT_ID]["updated_at"] == token
        assert _audit_rows(db) == []

    def test_delete_reset_only_key(self, monkey_settings):
        db = FakeDB()
        roles_before = copy.deepcopy(db.roles)
        params_before = copy.deepcopy(db.param_perms)
        client = _client(_cache(db), monkey_settings)
        token = db.profiles[CHAT_ID]["updated_at"]
        resp = client.delete(_chat_url(), headers=_hdr(),
                             params={"expected_updated_at": token})
        assert resp.status_code == 200, resp.text
        params = json.loads(db.profiles[CHAT_ID]["chat_params"])
        assert KEY not in params["perm_overrides"]
        assert SECOND_KEY in params["perm_overrides"]
        assert params["overrides"][KEY] == 111   # значения не тронуты
        assert db.roles == roles_before
        assert db.param_perms == params_before
        event = json.loads(_audit_rows(db)[-1]["new_value"])
        assert event["op"] == "reset" and event["after"] is None

    def test_delete_404_key_and_profile(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.delete(_chat_url(key="limits.nope"), headers=_hdr())
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "override_absent"
        resp = client.delete(_chat_url(chat_id=-1009999999999), headers=_hdr())
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "chat_profile_absent"

    def test_delete_stale_token_409(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.delete(_chat_url(), headers=_hdr(),
                             params={"expected_updated_at": _ts(999)})
        assert resp.status_code == 409
        assert resp.json()["detail"]["reason"] == "revision_mismatch"
        assert KEY in json.loads(
            db.profiles[CHAT_ID]["chat_params"])["perm_overrides"]

    def test_post_profile_absent_404(self, monkey_settings):
        db = FakeDB()
        client = _client(_cache(db), monkey_settings)
        resp = client.post(_chat_url(chat_id=-1009999999999),
                           headers=_hdr(), json={"view_roles": ["user"]})
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "chat_profile_absent"


# ═══ 4. Audit read ══════════════════════════════════════════════════════════

def _seed_audit(db, entity, op, **kwargs):
    event = acl_audit.build_event(entity=entity, op=op, **kwargs)
    db.add_history(0, "access", ADMIN_ID, "",
                   acl_audit.serialize_event(event))


class TestAuditRead:
    def test_401_without_init_data(self, monkey_settings):
        client = _client(_cache(FakeDB()), monkey_settings)
        assert client.get("/api/access/audit").status_code == 401

    def test_403_non_admin(self, monkey_settings):
        client = _client(_cache(FakeDB()), monkey_settings)
        resp = client.get("/api/access/audit", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_entity_filter_limit_and_before(self, monkey_settings):
        db = FakeDB()
        _seed_audit(db, "role", "update", role_name="custom_access",
                    before={"view_roles": []}, after={"added": {}})
        _seed_audit(db, "admin", "create", telegram_id=42,
                    after={"role_name": "moderator"})
        _seed_audit(db, "param_global", "reset", key=SECOND_KEY,
                    before={"view_roles": ["user"]})
        client = _client(_cache(db), monkey_settings)
        data = client.get("/api/access/audit", headers=_hdr()).json()
        assert data["scope"] == "global" and data["chat_id"] is None
        assert len(data["items"]) == 3
        assert data["has_more"] is False
        filtered = client.get("/api/access/audit", headers=_hdr(),
                              params={"entity": "admin"}).json()
        assert [i["entity"] for i in filtered["items"]] == ["admin"]
        assert filtered["items"][0]["telegram_id"] == 42
        # limit clamp: 0 → 1, 999 → ≤200
        one = client.get("/api/access/audit", headers=_hdr(),
                         params={"limit": 0}).json()
        assert len(one["items"]) == 1 and one["has_more"] is True
        many = client.get("/api/access/audit", headers=_hdr(),
                          params={"limit": 999}).json()
        assert len(many["items"]) <= 200
        last_id = data["items"][0]["id"]
        older = client.get("/api/access/audit", headers=_hdr(),
                           params={"before_id": last_id}).json()
        assert all(i["id"] < last_id for i in older["items"])
        assert older["has_more"] is False

    def test_malformed_row_is_visible(self, monkey_settings):
        db = FakeDB()
        db.add_history(0, "access", ADMIN_ID, "", "{not-json")
        _seed_audit(db, "role", "delete", role_name="x",
                    before={"sections": []})
        client = _client(_cache(db), monkey_settings)
        data = client.get("/api/access/audit", headers=_hdr()).json()
        malformed = [i for i in data["items"] if i.get("malformed")]
        assert len(malformed) == 1
        assert malformed[0]["before"] is None
        assert malformed[0]["after"] is None

    def test_scope_chat_foreign_dm_403_and_self_dm_ok(self, monkey_settings):
        db = FakeDB()
        _seed_audit(db, "param_chat", "reset", key=KEY)
        db.history[-1]["chat_id"] = ADMIN_ID
        client = _client(_cache(db), monkey_settings)
        resp = client.get("/api/access/audit", headers=_hdr(ADMIN_ID),
                          params={"scope": "chat", "chat_id": OTHER_DM})
        assert resp.status_code == 403
        resp = client.get("/api/access/audit", headers=_hdr(ADMIN_ID),
                          params={"scope": "chat", "chat_id": ADMIN_ID})
        assert resp.status_code == 200
        assert resp.json()["items"][0]["key"] == KEY
        # global admin — свой/чужой ЛС: чужой DM всё равно 403.
        resp = client.get("/api/access/audit", headers=_hdr(ADMIN_ID),
                          params={"scope": "chat", "chat_id": DM_ID})
        assert resp.status_code == 403

    def test_scope_chat_requires_chat_id_and_valid_entity(self,
                                                          monkey_settings):
        client = _client(_cache(FakeDB()), monkey_settings)
        assert client.get("/api/access/audit", headers=_hdr(),
                          params={"scope": "chat"}).status_code == 422
        assert client.get("/api/access/audit", headers=_hdr(),
                          params={"entity": "bogus"}).status_code == 422
        assert client.get("/api/access/audit", headers=_hdr(),
                          params={"scope": "bogus"}).status_code == 422

    def test_no_secret_or_prompt_in_audit(self, monkey_settings):
        db = FakeDB()
        # Даже если историческое событие несёт лишние поля, ответ их не
        # отдаёт: parse_event отбрасывает всё вне allowlist.
        dirty = json.dumps({
            "v": 1, "entity": "param_chat", "op": "set", "key": KEY,
            "before": {"view_roles": ["user"], "edit_roles": []},
            "after": {"view_roles": ["local_admin"], "edit_roles": []},
            "prompt": SENTINEL_PROMPT, "value": SENTINEL_VALUE,
            "last4": SENTINEL_LAST4})
        db.add_history(0, "access", ADMIN_ID, "", dirty)
        db.add_history(0, "access", ADMIN_ID, "", SENTINEL_SECRET)
        client = _client(_cache(db), monkey_settings)
        body = client.get("/api/access/audit", headers=_hdr()).text
        for sentinel in (SENTINEL_PROMPT, SENTINEL_VALUE, SENTINEL_LAST4,
                         SENTINEL_SECRET):
            assert sentinel not in body

    def test_503_when_pg_down(self, monkey_settings):
        client = _client(_cold_cache(), monkey_settings)
        resp = client.get("/api/access/audit", headers=_hdr())
        assert resp.status_code == 503


# ═══ 5. Audit fail-closed ═══════════════════════════════════════════════════

class TestAuditFailClosed:
    def test_role_mutation_rolls_back(self, monkey_settings):
        db = FakeDB()
        db.fail_audit = True
        client = _client(_cache(db), monkey_settings)
        before = copy.deepcopy(_role(db, "custom_access"))
        resp = client.post("/api/roles", headers=_hdr(), json={
            "role_name": "custom_access",
            "permissions": {"sections": ["flags"]}})
        assert resp.status_code == 503
        assert _role(db, "custom_access") == before
        assert _audit_rows(db) == []

    def test_global_param_rolls_back(self, monkey_settings):
        db = FakeDB()
        db.fail_audit = True
        client = _client(_cache(db), monkey_settings)
        before = copy.deepcopy(db.param_perms[SECOND_KEY])
        resp = client.put("/api/access/param_permissions/" + SECOND_KEY,
                          headers=_hdr(),
                          json={"view_roles": ["user"]})
        assert resp.status_code == 503
        assert db.param_perms[SECOND_KEY] == before

    def test_chat_override_rolls_back(self, monkey_settings):
        db = FakeDB()
        db.fail_audit = True
        client = _client(_cache(db), monkey_settings)
        before = copy.deepcopy(db.profiles[CHAT_ID])
        resp = client.post(_chat_url(), headers=_hdr(),
                           json={"view_roles": ["user"]})
        assert resp.status_code == 503
        assert db.profiles[CHAT_ID] == before


# ═══ 6. Recheck ═════════════════════════════════════════════════════════════

class TestRecheck:
    @pytest.mark.asyncio
    async def test_retry_recheck_denies_before_second_write(self, monkeypatch):
        calls = []

        async def fake_set(*args, **kwargs):
            calls.append(kwargs)
            raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))

        async def deny():
            raise RuntimeError("denied")

        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        with pytest.raises(RuntimeError):
            await routes_mod._write_chat_overrides_with_retry(
                CHAT_ID, {"a": 1}, {"updated_by": 1},
                types.SimpleNamespace(pg=object()),
                expected_updated_at=_ts(1), recheck=deny)
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_retry_recheck_allows_second_write(self, monkeypatch):
        calls = []

        async def fake_set(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))
            return chat_params.ChatParamsResult({}, updated_at=_ts(6))

        async def allow():
            return None

        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        monkeypatch.setattr(chat_params, "get_all_chat_params",
                            lambda *a, **k: _async({"overrides": {}}))
        result = await routes_mod._write_chat_overrides_with_retry(
            CHAT_ID, {"a": 1}, {"updated_by": 1},
            types.SimpleNamespace(pg=object()),
            expected_updated_at=_ts(1), recheck=allow)
        assert result.updated_at == _ts(6)
        assert len(calls) == 2
        assert calls[1]["expected_updated_at"] is None

    def test_post_config_recheck_denies_403_no_second_write(
            self, monkey_settings, monkeypatch):
        db = FakeDB()
        cache = _cache(db)
        client = _client(cache, monkey_settings)
        calls = []
        original_access_for = roles_srv.access_for
        state = {"n": 0}

        async def access_for(telegram_id, chat_id=None, cache=None,
                            strict=False):
            if chat_id == CHAT_ID and telegram_id == LOCAL_ID:
                state["n"] += 1
                if state["n"] == 1:
                    return await original_access_for(
                        telegram_id, chat_id, cache=cache, strict=strict)
                # Права отозваны между конфликтом и retry.
                return roles_srv.AccessCtx(
                    role_global="user", role_chat=None,
                    perms_global=Permissions.from_dict({}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=1)
            return await original_access_for(
                telegram_id, chat_id, cache=cache, strict=strict)

        async def fake_set(*args, **kwargs):
            calls.append(kwargs)
            raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))

        monkeypatch.setattr(roles_srv, "access_for", access_for)
        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        resp = client.post("/api/config", headers={
            **_hdr(LOCAL_ID), "X-Chat-Id": str(CHAT_ID)},
            json={"items": [{"key": KEY, "value": 777}],
                  "updated_at": _ts(1)})
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "denied"
        assert resp.json()["detail"]["keys"] == [KEY]
        assert len(calls) == 1

    def test_post_config_recheck_503_when_pg_down(
            self, monkey_settings, monkeypatch):
        db = FakeDB()
        cache = _cache(db)
        client = _client(cache, monkey_settings)
        original_access_for = roles_srv.access_for
        state = {"n": 0}

        async def access_for(telegram_id, chat_id=None, cache=None,
                            strict=False):
            if chat_id == CHAT_ID and telegram_id == LOCAL_ID:
                state["n"] += 1
                if state["n"] == 1:
                    return await original_access_for(
                        telegram_id, chat_id, cache=cache, strict=strict)
                raise access_srv.AccessStorageUnavailable("PG down")
            return await original_access_for(
                telegram_id, chat_id, cache=cache, strict=strict)

        async def fake_set(*args, **kwargs):
            raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))

        monkeypatch.setattr(roles_srv, "access_for", access_for)
        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        resp = client.post("/api/config", headers={
            **_hdr(LOCAL_ID), "X-Chat-Id": str(CHAT_ID)},
            json={"items": [{"key": KEY, "value": 777}],
                  "updated_at": _ts(1)})
        assert resp.status_code == 503, resp.text

    @pytest.mark.parametrize("partial", [
        {"view_min_role": "moderator"},
        {"view_roles": ["moderator"]},
        {"hidden_from_local": True},
    ])
    def test_c31_partial_override_no_false_403(
            self, monkey_settings, monkeypatch, partial):
        """C3-R1-B01: recheck обязан считать матрицу по raw-значению.

        Partial override (legacy view-only / hidden-only / new-form только
        view_roles) наследует edit_roles из дефолта при request-time guard;
        нормализованный snapshot.value edit_roles теряет → ложный 403.
        Права НЕ менялись: обе проверки local_admin, запись должна пройти.
        """
        db = FakeDB()
        db.param_perms[PARTIAL_KEY] = {
            "value": copy.deepcopy(partial),
            "updated_at": _ts(20),
        }
        cache = _cache(db)
        client = _client(cache, monkey_settings)
        calls = []

        async def fake_set(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))
            return chat_params.ChatParamsResult({}, updated_at=_ts(6))

        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        resp = client.post("/api/config", headers={
            **_hdr(LOCAL_ID), "X-Chat-Id": str(CHAT_ID)},
            json={"items": [{"key": PARTIAL_KEY, "value": 777}],
                  "updated_at": _ts(1)})
        assert resp.status_code == 200, resp.text
        assert len(calls) == 2, "retry должен выполнить вторую запись"
        assert calls[1]["expected_updated_at"] is None

    @pytest.mark.parametrize("partial", [
        {"view_min_role": "moderator"},
        {"view_roles": ["moderator"]},
        {"hidden_from_local": True},
    ])
    def test_c31_partial_override_real_revoke_still_403(
            self, monkey_settings, monkeypatch, partial):
        """Тот же partial override, но права реально отозваны: 403, 1 запись."""
        db = FakeDB()
        db.param_perms[PARTIAL_KEY] = {
            "value": copy.deepcopy(partial),
            "updated_at": _ts(20),
        }
        cache = _cache(db)
        client = _client(cache, monkey_settings)
        calls = []
        original_access_for = roles_srv.access_for
        state = {"n": 0}

        async def access_for(telegram_id, chat_id=None, cache=None,
                            strict=False):
            if chat_id == CHAT_ID and telegram_id == LOCAL_ID:
                state["n"] += 1
                if state["n"] == 1:
                    return await original_access_for(
                        telegram_id, chat_id, cache=cache, strict=strict)
                return roles_srv.AccessCtx(
                    role_global="user", role_chat=None,
                    perms_global=Permissions.from_dict({}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=1)
            return await original_access_for(
                telegram_id, chat_id, cache=cache, strict=strict)

        async def fake_set(*args, **kwargs):
            calls.append(kwargs)
            raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))

        monkeypatch.setattr(roles_srv, "access_for", access_for)
        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        resp = client.post("/api/config", headers={
            **_hdr(LOCAL_ID), "X-Chat-Id": str(CHAT_ID)},
            json={"items": [{"key": PARTIAL_KEY, "value": 777}],
                  "updated_at": _ts(1)})
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "denied"
        assert resp.json()["detail"]["keys"] == [PARTIAL_KEY]
        assert len(calls) == 1

    def test_c31_inherit_retry_rechecks_rights(
            self, monkey_settings, monkeypatch):
        """C3-R1-N01: inherit-only retry не должен писать после отзыва прав."""
        db = FakeDB()
        cache = _cache(db)
        client = _client(cache, monkey_settings)
        calls = []
        original_access_for = roles_srv.access_for
        state = {"n": 0}

        async def access_for(telegram_id, chat_id=None, cache=None,
                            strict=False):
            if chat_id == CHAT_ID and telegram_id == LOCAL_ID:
                state["n"] += 1
                if state["n"] == 1:
                    return await original_access_for(
                        telegram_id, chat_id, cache=cache, strict=strict)
                return roles_srv.AccessCtx(
                    role_global="user", role_chat=None,
                    perms_global=Permissions.from_dict({}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=1)
            return await original_access_for(
                telegram_id, chat_id, cache=cache, strict=strict)

        async def fake_get_all(*args, **kwargs):
            return {"overrides": {KEY: 111}, "meta": {}}

        async def fake_set(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))
            return chat_params.ChatParamsResult({}, updated_at=_ts(6))

        monkeypatch.setattr(roles_srv, "access_for", access_for)
        monkeypatch.setattr(chat_params, "get_all_chat_params", fake_get_all)
        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        resp = client.post("/api/config", headers={
            **_hdr(LOCAL_ID), "X-Chat-Id": str(CHAT_ID)},
            json={"items": [{"key": KEY, "mode": "inherit"}],
                  "updated_at": _ts(1)})
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "denied"
        assert resp.json()["detail"]["keys"] == [KEY]
        assert len(calls) == 1

    def test_c31_inherit_retry_unchanged_rights_succeeds(
            self, monkey_settings, monkeypatch):
        """N01-парная: неизменные права → retry проходит ровно один раз."""
        db = FakeDB()
        cache = _cache(db)
        client = _client(cache, monkey_settings)
        calls = []

        async def fake_get_all(*args, **kwargs):
            return {"overrides": {KEY: 111}, "meta": {}}

        async def fake_set(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))
            return chat_params.ChatParamsResult({}, updated_at=_ts(6))

        monkeypatch.setattr(chat_params, "get_all_chat_params", fake_get_all)
        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        resp = client.post("/api/config", headers={
            **_hdr(LOCAL_ID), "X-Chat-Id": str(CHAT_ID)},
            json={"items": [{"key": KEY, "mode": "inherit"}],
                  "updated_at": _ts(1)})
        assert resp.status_code == 200, resp.text
        assert len(calls) == 2
        assert calls[1]["expected_updated_at"] is None

    def test_meme_settings_recheck_own_gate(
            self, monkey_settings, monkeypatch):
        db = FakeDB()
        cache = _cache(db)
        client = _client(cache, monkey_settings)
        calls = []
        original_access_for = roles_srv.access_for
        state = {"n": 0}

        async def access_for(telegram_id, chat_id=None, cache=None,
                            strict=False):
            if chat_id == CHAT_ID and telegram_id == LOCAL_ID:
                state["n"] += 1
                if state["n"] == 1:
                    return await original_access_for(
                        telegram_id, chat_id, cache=cache, strict=strict)
                return roles_srv.AccessCtx(
                    role_global="user", role_chat=None,
                    perms_global=Permissions.from_dict({}),
                    perms_chat=Permissions.from_dict({}),
                    is_global_admin=False, is_local_admin=False, rank=1)
            return await original_access_for(
                telegram_id, chat_id, cache=cache, strict=strict)

        async def fake_set(*args, **kwargs):
            calls.append(kwargs)
            raise chat_params.ChatParamsConflict(CHAT_ID, _ts(5))

        monkeypatch.setattr(roles_srv, "access_for", access_for)
        monkeypatch.setattr(chat_params, "set_chat_params", fake_set)
        resp = client.post("/api/initiative/meme-settings",
                           headers={**_hdr(LOCAL_ID),
                                    "X-Chat-Id": str(CHAT_ID)},
                           json={"enabled": True, "updated_at": _ts(1)})
        assert resp.status_code == 403, resp.text
        assert len(calls) == 1


def _async(value):
    async def _inner():
        return value
    return _inner()


# ═══ 7. S8-524: embeddings guard (negative matrix) ══════════════════════════

class TestEmbeddingsGuard:
    def test_401_without_init_data(self, monkey_settings):
        client = _client(_cache(FakeDB()), monkey_settings)
        assert client.get("/api/memory/embeddings").status_code == 401

    @pytest.mark.parametrize("user_id", [MODERATOR_ID, LOCAL_ID, USER_ID])
    def test_403_for_non_global(self, monkey_settings, user_id):
        client = _client(_cache(FakeDB()), monkey_settings)
        assert client.get("/api/memory/embeddings",
                          headers=_hdr(user_id)).status_code == 403

    def test_200_for_global_admin(self, monkey_settings, monkeypatch):
        monkeypatch.setattr(memory_agi_mod, "_db_or_503",
                            lambda: object())
        client = _client(_cache(FakeDB()), monkey_settings)
        resp = client.get("/api/memory/embeddings", headers=_hdr())
        assert resp.status_code == 200
        assert "vector_memory" in resp.json()


# ═══ 8. Lore/oversight: field='access' скрыт ════════════════════════════════

class TestLoreFilter:
    @pytest.mark.asyncio
    async def test_history_excludes_access_in_sql(self, monkeypatch):
        calls = []

        class _Conn:
            async def fetch(self, sql, *args):
                calls.append((sql, args))
                return []

        class _Store(chat_lore_store.ChatLoreStore):
            def __init__(self):
                self._pool_obj = _Pool(_Conn())

            def _pool(self):
                return self._pool_obj

        class _Pool:
            def __init__(self, conn):
                self.conn = conn

            def acquire(self):
                conn = self.conn

                class _CM:
                    async def __aenter__(self_inner):
                        return conn

                    async def __aexit__(self_inner, *exc):
                        return False

                return _CM()

        store = _Store()
        await store.history(CHAT_ID, limit=5, exclude_fields=("access",))
        sql, args = calls[0]
        assert "field <> ALL" in sql
        assert args[1] == ["access"]
        assert args[2] == 5
        # Недопустимое поле не подставляется в SQL.
        calls.clear()
        await store.history(CHAT_ID, limit=5,
                            exclude_fields=("access; DROP TABLE",))
        sql, args = calls[0]
        assert "field <> ALL" not in sql

    def test_call_sites_exclude_access(self):
        import services.oversight as oversight
        import web.api.chat_lore as chat_lore_api
        assert 'exclude_fields=("access",)' in inspect.getsource(
            chat_lore_api.get_history)
        assert 'exclude_fields=("access",)' in inspect.getsource(
            oversight)
