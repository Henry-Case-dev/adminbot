"""Раунд 10 (F-10 §7, T-898 API-матрица + фикс R2) — API-тесты бюджет-рута.

GET /api/workers/budget: global admin — всё; local admin/moderator с
грантом — global + свои чаты; любая роль без гранта → 403 (фикс R2);
401 без initData.
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_GATES"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
LOCAL_ID = 424242424
USER_NO_ROLE = 999999999


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
    """PG-заглушка: bot_roles/bot_admins/chat_admins/worker_budget."""

    def __init__(self, grants: dict[int, set[int]], budget_rows: list,
                 roles, admins):
        self.grants = grants
        self.budget_rows = budget_rows
        self._roles = roles
        self._admins = admins
        self.notifies = []

    async def execute(self, sql, *args):
        if "pg_notify" in sql:
            self.notifies.append(args)
        return "UPDATE 1"

    async def fetch(self, sql, *args):
        if "FROM bot_roles" in sql:
            return list(self._roles)
        if "FROM bot_admins" in sql:
            return list(self._admins)
        if "FROM chat_admins" in sql:
            tg_id = args[0]
            return [{"chat_id": c} for c in sorted(self.grants.get(tg_id, set()))]
        if "FROM worker_budget" in sql and "day = $1" in sql:
            day = args[0]
            if len(args) > 1:                     # SELECT_SQL (day, scope)
                return [r for r in self.budget_rows
                        if r["day"] == str(day) and r["scope"] == args[1]]
            return [r for r in self.budget_rows if r["day"] == str(day)]
        return []

    async def fetchrow(self, sql, *args):
        if "FROM chat_admins" in sql:
            chat_id, tg_id = args[0], args[1]
            if chat_id in self.grants.get(tg_id, set()):
                return {"role_name": "local_admin"}
            return None
        if "INSERT INTO worker_budget" in sql:
            return {"used": 0}
        return None


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

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


def _roles():
    return [
        {"role_name": "admin", "permissions": {"wildcard": True},
         "is_custom": False, "role_type": "global_admin"},
        {"role_name": "moderator",
         "permissions": {"sections": ["limits"]},
         "is_custom": False, "role_type": "moderator"},
        {"role_name": "local_admin",
         "permissions": {"sections": ["limits", "flags", "reactions",
                                      "content", "chat_lore"]},
         "is_custom": False, "role_type": "local_admin"},
        {"role_name": "user", "permissions": {}, "is_custom": False,
         "role_type": "user"},
    ]


def _admins():
    return [
        {"telegram_id": ADMIN_ID, "role_name": "admin",
         "added_by": None, "created_at": "2026-09-07T00:00:00+00:00"},
        {"telegram_id": MODERATOR_ID, "role_name": "moderator",
         "added_by": ADMIN_ID, "created_at": "2026-09-07T00:00:01+00:00"},
        {"telegram_id": LOCAL_ID, "role_name": "local_admin",
         "added_by": ADMIN_ID, "created_at": "2026-09-07T00:00:02+00:00"},
    ]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    from services import worker_budget
    day = str(worker_budget.today())
    conn = _FakeConn(
        grants={LOCAL_ID: {-1001}, MODERATOR_ID: set()},
        budget_rows=[
            {"day": day, "scope": "global", "metric": "llm_calls",
             "used": 42},
            {"day": day, "scope": "global", "metric": "llm_tokens",
             "used": 1000},
            {"day": day, "scope": "chat:-1001", "metric": "llm_calls",
             "used": 5},
            {"day": day, "scope": "chat:-2002", "metric": "llm_calls",
             "used": 7},
        ], roles=_roles(), admins=_admins())
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        tc.cache = cache
        tc.conn = conn
        yield tc


class TestWorkersBudget:
    def test_401_without_init_data(self, client):
        assert client.get("/api/workers/budget").status_code == 401

    def test_global_admin_sees_all(self, client):
        resp = client.get("/api/workers/budget", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["global"]["calls"]["used"] == 42
        assert body["global"]["calls"]["limit"] == 200
        scopes = {c["scope"] for c in body["chats"]}
        assert scopes == {"chat:-1001", "chat:-2002"}

    def test_moderator_without_grants_403(self, client):
        """ФИКС R2: глобальный moderator без chat-грантов → 403."""
        resp = client.get("/api/workers/budget", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_user_403(self, client):
        resp = client.get("/api/workers/budget", headers=_hdr(USER_NO_ROLE))
        assert resp.status_code == 403

    def test_local_admin_without_grants_403(self, client):
        """ФИКС R2: локальный админ БЕЗ грантов → 403 (нет — значит 403)."""
        client.conn.grants = {LOCAL_ID: set()}
        resp = client.get("/api/workers/budget", headers=_hdr(LOCAL_ID))
        assert resp.status_code == 403

    def test_local_admin_with_grant_filters_chats(self, client):
        """Грант-админ чата видит global + только свой чат (F-10 §7)."""
        resp = client.get("/api/workers/budget", headers=_hdr(LOCAL_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["global"]["calls"]["used"] == 42
        scopes = {c["scope"] for c in body["chats"]}
        assert scopes == {"chat:-1001"}, body


# ═══ F-14 (T-956, spec §3.2): gates в DM-скоупе — READ-only ════════════════

class TestDmGates:
    """DM-скоуп (X-Chat-Id = свой user.id): GET 200 READ
    (who_can_toggle='global'), PUT → 403 (гейты — только global admin и
    только группы; feature_gates без дифов); чужой ЛС → 403."""

    def test_gates_get_dm_owner_read_200(self, client):
        resp = client.get(f"/api/chat/{USER_NO_ROLE}/gates",
                          headers=_hdr(USER_NO_ROLE))
        assert resp.status_code == 200
        body = resp.json()
        assert body["chat_id"] == USER_NO_ROLE
        who = body["who_can_toggle"]
        assert all(v == "global" for v in who.values())

    def test_gates_put_dm_403(self, client):
        resp = client.put(f"/api/chat/{USER_NO_ROLE}/gates",
                          json={"feature": "slavik", "enabled": True},
                          headers=_hdr(USER_NO_ROLE))
        assert resp.status_code == 403

    def test_gates_get_foreign_dm_403(self, client):
        """Глобальный админ в чужом ЛС → 403 (can_access_chat False)."""
        resp = client.get(f"/api/chat/{USER_NO_ROLE}/gates",
                          headers=_hdr(ADMIN_ID))
        assert resp.status_code == 403
