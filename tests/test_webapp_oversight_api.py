"""Раунд 10 (F-12, T-919-API) — тесты API-матрицы Oversight.

401 без initData; 403 moderator/user/local; 404 неизвестный чат;
тело summary — без сырых ключей (R17-греп-тест на сервисном уровне).
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

TEST_TOKEN = "123456:TEST_TOKEN_OVERSIGHT"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079


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
    def __init__(self):
        self.profiles = {
            -100: {"chat_id": -100,
                   "updated_at": "2026-09-07T01:00:00+00:00",
                   "chat_params": {"v": 1, "gates": {}, "keys": {
                       "allow_global": True}, "meta": {}},
                   "gates_opt_in": False},
        }

    async def execute(self, sql, *args):
        return "UPDATE 1"

    async def fetch(self, sql, *args):
        if "FROM bot_roles" in sql:
            return [
                {"role_name": "admin", "permissions": {"wildcard": True},
                 "is_custom": False, "role_type": "global_admin"},
                {"role_name": "moderator",
                 "permissions": {"sections": ["limits"]},
                 "is_custom": False, "role_type": "moderator"},
            ]
        if "FROM bot_admins" in sql:
            return [
                {"telegram_id": ADMIN_ID, "role_name": "admin",
                 "added_by": None, "created_at": "2026-09-07T00:00:00+00:00"},
                {"telegram_id": MODERATOR_ID, "role_name": "moderator",
                 "added_by": ADMIN_ID,
                 "created_at": "2026-09-07T00:00:01+00:00"},
            ]
        return []

    async def fetchrow(self, sql, *args):
        if "FROM chat_profiles" in sql:
            profile = self.profiles.get(args[0])
            return dict(profile) if profile is not None else None
        if "UPDATE chat_profiles" in sql:
            profile = self.profiles.get(args[0])
            if profile is None:
                return None
            if "AND updated_at =" in sql and args[2]:
                current = profile["updated_at"]
                expected = args[2].isoformat().replace("+00:00", "+00:00")
                if current != expected:
                    return None           # optimistic-конфликт → 409
            profile["chat_params"] = json.loads(args[1])
            return dict(profile)
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx


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

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)
        self.closed = False

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        self.closed = True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    conn = _FakeConn()
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    import asyncio
    asyncio.run(cache.init())             # роли/админы из fake-PG
    from services import chat_params as cp_srv
    cp_srv.set_chat_params_cache(cp_srv.ChatParamsCache(cache.pg))
    app = create_app(cache)
    try:
        with TestClient(app) as tc:
            tc.cache = cache
            tc.conn = conn
            yield tc
    finally:
        cp_srv.set_chat_params_cache(None)


class TestAuthMatrix:
    def test_401_without_init_data(self, client):
        resp = client.get("/api/oversight/summary")
        assert resp.status_code == 401

    def test_403_moderator(self, client):
        resp = client.get("/api/oversight/summary", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_403_unknown_user(self, client):
        resp = client.get("/api/oversight/summary", headers=_hdr(424242424))
        assert resp.status_code == 403

    def test_403_global_key_post_by_moderator(self, client):
        resp = client.post(
            "/api/oversight/chat/-100/global_key",
            headers=_hdr(MODERATOR_ID),
            json={"allow": False})
        assert resp.status_code == 403

    def test_404_killswitch_unknown_chat(self, client):
        """ФИКС S-F12 (spec §4): неизвестный chat_id → 404 (409 — только
        конфликты версии)."""
        resp = client.post(
            "/api/oversight/chat/-100500/killswitch",
            headers=_hdr(ADMIN_ID),
            json={"feature": "dream", "enabled": False})
        assert resp.status_code == 404

    def test_404_global_key_unknown_chat(self, client):
        resp = client.post(
            "/api/oversight/chat/-100500/global_key",
            headers=_hdr(ADMIN_ID),
            json={"allow": False})
        assert resp.status_code == 404

    def test_killswitch_existing_chat_returns_updated_at(self, client):
        """ФИКС S-F12: killswitch-ответ несёт АКТУАЛЬНЫЙ updated_at
        (из chat_profiles — optimistic-токен модалки, а не всегда None)."""
        resp = client.post(
            "/api/oversight/chat/-100/killswitch",
            headers=_hdr(ADMIN_ID),
            json={"feature": "dream", "enabled": False})
        assert resp.status_code == 200
        body = resp.json()
        assert body["feature"] == "dream"
        assert body["enabled"] is False
        assert body["previous"] is False
        assert body["updated_at"] == "2026-09-07T01:00:00+00:00"

    def test_global_key_existing_chat_returns_updated_at(self, client):
        resp = client.post(
            "/api/oversight/chat/-100/global_key",
            headers=_hdr(ADMIN_ID),
            json={"allow": False, "expected_updated_at":
                  "2026-09-07T01:00:00+00:00"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["allow"] is False
        assert body["previous"] is True
        assert body["updated_at"] == "2026-09-07T01:00:00+00:00"

    def test_global_key_409_on_stale_version(self, client):
        """409 остаётся ТОЛЬКО для конфликта версии (optimistic)."""
        resp = client.post(
            "/api/oversight/chat/-100/global_key",
            headers=_hdr(ADMIN_ID),
            json={"allow": False, "expected_updated_at":
                  "2000-01-01T00:00:00+00:00"})
        assert resp.status_code == 409
