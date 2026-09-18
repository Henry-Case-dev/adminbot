"""Раунд 10.23 (F7, ADR-1023-7 §2.7, review iter1) — интеграционные/RBAC
тесты API аналитики токенов.

По образцу `tests/test_webapp_gates_api.py`: реальный `TestClient(create_app)`,
проверяем 401 (без initData), 403 (не глобальный админ), 200 (admin) для
`/api/analytics/usage/latest|summary|prices` и `PUT /analytics/prices`;
плюс инвалидация in-process кэша цен на PUT.
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from services import llm_pricing
from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_ANALYTICS"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
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


def _roles():
    return [
        {"role_name": "admin", "permissions": {"wildcard": True},
         "is_custom": False, "role_type": "global_admin"},
        {"role_name": "moderator",
         "permissions": {"sections": ["limits"]},
         "is_custom": False, "role_type": "moderator"},
        {"role_name": "user", "permissions": {}, "is_custom": False,
         "role_type": "user"},
    ]


def _admins():
    return [
        {"telegram_id": ADMIN_ID, "role_name": "admin",
         "added_by": None, "created_at": "2026-09-07T00:00:00+00:00"},
        {"telegram_id": MODERATOR_ID, "role_name": "moderator",
         "added_by": ADMIN_ID, "created_at": "2026-09-07T00:00:01+00:00"},
    ]


class _FakeConn:
    """PG-заглушка: RBAC (bot_roles/bot_admins) + аналитика."""

    def __init__(self):
        self.executed = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

    async def fetchrow(self, sql, *args):
        if "ORDER BY ts DESC" in sql:
            return {"correlation_id": "cid-1",
                    "ts": "2026-09-19T12:00:00+00:00"}
        if "COUNT(*) AS calls" in sql:
            return {"cost_usd": Decimal("1.5"), "input_tokens": 100,
                    "output_tokens": 50, "calls": 3}
        return None

    async def fetch(self, sql, *args):
        if "FROM bot_roles" in sql:
            return list(_roles())
        if "FROM bot_admins" in sql:
            return list(_admins())
        if "correlation_id = $1" in sql:
            return [{"ts": "2026-09-19T12:00:00+00:00", "module": "direct_chat",
                     "step": "stage1", "tool_name": "", "source": "global",
                     "model": "deepseek-v4-flash", "input_tokens": 4000,
                     "output_tokens": 600, "tokens_estimated": False,
                     "cost_usd": Decimal("0.00174"), "price_known": True}]
        if "GROUP BY module" in sql:
            return [{"module": "direct_chat", "cost_usd": Decimal("1.5"),
                     "input_tokens": 100, "output_tokens": 50, "calls": 3}]
        if "date_trunc" in sql:
            return [{"bucket": "2026-09-19T12:00:00+00:00",
                     "cost_usd": Decimal("1.5"), "input_tokens": 100,
                     "output_tokens": 50, "calls": 3}]
        if "FROM llm_model_prices" in sql:
            return [{"model": "deepseek-v4-flash",
                     "input_usd_per_1m": Decimal("0.27"),
                     "output_usd_per_1m": Decimal("1.10"),
                     "currency": "USD"}]
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    llm_pricing.invalidate()
    conn = _FakeConn()
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        tc.conn = conn
        yield tc
    llm_pricing.invalidate()


class TestAnalyticsRbac:
    def test_401_without_init_data(self, client):
        assert client.get("/api/analytics/usage/latest").status_code == 401
        assert client.get("/api/analytics/usage/summary").status_code == 401
        assert client.get("/api/analytics/prices").status_code == 401

    def test_admin_latest_200(self, client):
        resp = client.get("/api/analytics/usage/latest", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["correlation_id"] == "cid-1"
        assert body["steps"][0]["step"] == "stage1"
        assert body["total"]["input_tokens"] == 4000

    def test_admin_summary_200(self, client):
        resp = client.get("/api/analytics/usage/summary?period=day",
                          headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["period"] == "day"
        assert body["totals"]["calls"] == 3
        assert body["by_module"][0]["module"] == "direct_chat"

    def test_admin_prices_200(self, client):
        resp = client.get("/api/analytics/prices", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["prices"][0]["model"] == "deepseek-v4-flash"

    def test_moderator_403(self, client):
        for path in ("/api/analytics/usage/latest",
                     "/api/analytics/usage/summary",
                     "/api/analytics/prices"):
            assert client.get(path, headers=_hdr(MODERATOR_ID)).status_code == 403

    def test_user_403(self, client):
        assert client.get("/api/analytics/usage/latest",
                          headers=_hdr(USER_NO_ROLE)).status_code == 403

    def test_put_prices_requires_admin(self, client):
        resp = client.put("/api/analytics/prices",
                          json={"model": "m", "input_usd_per_1m": 1.0,
                                "output_usd_per_1m": 2.0},
                          headers=_hdr(USER_NO_ROLE))
        assert resp.status_code == 403


class TestAnalyticsPricesPut:
    def test_put_ok_and_invalidates_cache(self, client):
        llm_pricing._CACHE["deepseek-v4-flash"] = ((9.0, 9.0), 1e18)
        resp = client.put(
            "/api/analytics/prices",
            json={"model": "deepseek-v4-flash", "input_usd_per_1m": 0.5,
                  "output_usd_per_1m": 2.0},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "deepseek-v4-flash" not in llm_pricing._CACHE
        assert any("INSERT INTO llm_model_prices" in sql
                   for sql, _args in client.conn.executed)
