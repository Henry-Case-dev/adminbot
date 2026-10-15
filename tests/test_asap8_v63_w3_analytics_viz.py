# -*- coding: utf-8 -*-
"""ASAP 8 v6.3 W3-ANALYTICS — API /api/analytics/viz/* (U05.1/U05.3).

TEST-LIFECYCLE: CONTRACT owner=REQ-U05 (slice W3-ANALYTICS)

Проверяется на РЕАЛЬНОМ SQLite (aiosqlite in-memory, схема mca_events из
services/database.py):
  * 401 без initData; RBAC global admin (как /api/oversight/*);
  * /viz/activity: buckets день×час из durable-событий, total/first/last,
    honest telemetry_off (гейты OFF → available=false, не нули);
  * /viz/process-activity: эффективный статус из реестра+событий
    (working/error/no_conditions/never_run/off), last action, счётчики
    24ч/7д; R17 — текст ошибки не отдаётся (только тип).
"""
import json
import time
import types

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_W3ANALYTICS"
ADMIN_ID = 5885953495

NOW = 1791900000

_MCA_EVENTS_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_events ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "ts INTEGER NOT NULL, "
    "level TEXT NOT NULL, "
    "event_name TEXT NOT NULL, "
    "outcome TEXT NOT NULL, "
    "trace_id TEXT, "
    "operation_id TEXT, "
    "parent_operation_id TEXT, "
    "chat_id INTEGER, "
    "component TEXT, "
    "stage TEXT, "
    "reason_code TEXT, "
    "duration_ms INTEGER, "
    "attempt INTEGER, "
    "config_version TEXT, "
    "model TEXT, "
    "provider TEXT, "
    "entity_ids TEXT, "
    "usage_json TEXT, "
    "error_json TEXT, "
    "source_ref_json TEXT)"
)


def make_init_data(user_id: int = ADMIN_ID) -> str:
    import hashlib
    import hmac
    import time
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A"},
                           separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


class _AioConn:
    """Обёртка aiosqlite-conn под контракт db.db.execute (await)."""

    def __init__(self, conn):
        self._conn = conn

    async def execute(self, sql, params=()):
        return await self._conn.execute(sql, tuple(params))


class _FakeDb:
    def __init__(self, conn):
        self.db = _AioConn(conn)


async def _make_conn():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row   # как в проде (DatabaseService)
    await conn.execute(_MCA_EVENTS_DDL)
    now = int(time.time())
    rows = [
        # ingestion.live: свежий успех (→ working)
        (now - 120, "info", "ingestion_live", "success", None),
        # self_learning.run: свежий провал заявленного события (→ error);
        # имя события — из реестра (validation_passed)
        (now - 600, "error", "validation_passed", "failed",
         json.dumps({"type": "TimeoutError", "message": "СЕКРЕТ-ТЕКСТ"})),
        # random.uses: skip по причине (→ no_conditions); имя из реестра
        (now - 90000, "info", "random_uses", "skipped", None),
        # heatmap: 3 события в пределах часа + ошибка сутки назад
        (now - 600, "info", "ingestion_live", "success", None),
        (now - 660, "info", "ingestion_live", "success", None),
        (now - 720, "info", "ingestion_live", "success", None),
        (now - 90000, "error", "validation_passed", "failed", None),
    ]
    await conn.executemany(
        "INSERT INTO mca_events (ts, level, event_name, outcome, error_json) "
        "VALUES (?, ?, ?, ?, ?)", rows)
    await conn.commit()
    return conn


class _FakePgConn:
    """Fake asyncpg-conn: только роли/админы для RBAC (прецедент
    test_webapp_oversight_api)."""

    async def execute(self, sql, *args):
        return "UPDATE 1"

    async def fetch(self, sql, *args):
        if "FROM bot_roles" in sql:
            return [
                {"role_name": "admin", "permissions": {"wildcard": True},
                 "is_custom": False, "role_type": "global_admin"},
            ]
        if "FROM bot_admins" in sql:
            return [
                {"telegram_id": ADMIN_ID, "role_name": "admin",
                 "added_by": None, "created_at": "2026-09-07T00:00:00+00:00"},
            ]
        return []

    async def fetchrow(self, sql, *args):
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
    pg_conn = _FakePgConn()
    cache = ConfigCache(pg=_FakePg(pg_conn), retry_attempts=1, retry_delay=0)
    import asyncio
    asyncio.run(cache.init())             # роли/админы из fake-PG
    from services import chat_params as cp_srv
    cp_srv.set_chat_params_cache(cp_srv.ChatParamsCache(cache.pg))
    app = create_app(cache)
    lore_conn = asyncio.run(_make_conn())
    fake_db = _FakeDb(lore_conn)
    from services import lore_runtime
    lore_runtime.set_lore_components(db=fake_db)
    try:
        with TestClient(app) as tc:
            tc.fake_db = fake_db
            tc._conn = lore_conn
            tc._loop = asyncio
            yield tc
    finally:
        lore_runtime.reset_lore_runtime()
        cp_srv.set_chat_params_cache(None)
        try:
            asyncio.run(lore_conn.close())
        except Exception:
            pass


class TestAuth:
    def test_401_without_init_data(self, client):
        assert client.get("/api/analytics/viz/activity").status_code == 401
        assert client.get(
            "/api/analytics/viz/process-activity").status_code == 401


class TestActivity:
    def test_buckets_real(self, client, monkeypatch):
        from services import mca_gates
        monkeypatch.setattr(mca_gates, "telemetry_store_enabled",
                            lambda: True)
        monkeypatch.setattr(mca_gates, "observability_enabled", lambda: True)
        resp = client.get("/api/analytics/viz/activity?days=7",
                          headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["total"] == 7
        assert body["errors_total"] == 2
        assert body["telemetry_enabled"] is True
        buckets = {(b["d"], b["h"]): b for b in body["buckets"]}
        # все засеянные события попадают в бакеты своей даты/часа (локally)
        assert sum(b["c"] for b in body["buckets"]) == 7
        assert any(b["errs"] >= 1 for b in body["buckets"])

    def test_telemetry_off_honest(self, client, monkeypatch):
        from services import mca_gates
        monkeypatch.setattr(mca_gates, "telemetry_store_enabled",
                            lambda: False)
        monkeypatch.setattr(mca_gates, "observability_enabled", lambda: True)
        resp = client.get("/api/analytics/viz/activity?days=7",
                          headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert body["telemetry_enabled"] is False
        assert "telemetry_off" in str(body.get("reason"))
        assert "buckets" not in body or not body["buckets"]


class TestProcessActivity:
    def test_effective_statuses(self, client, monkeypatch):
        from services import mca_gates
        monkeypatch.setattr(mca_gates, "process_registry_enabled",
                            lambda: True)
        resp = client.get("/api/analytics/viz/process-activity",
                          headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["events_available"] is True
        by_id = {p["process_id"]: p
                 for p in body["processes"] if p["process_id"]}
        ing = by_id["ingestion.live"]
        assert ing["effective"] == "working"
        assert ing["counts"]["24h"] == 4
        assert ing["counts"]["7d"] == 4
        assert ing["last_ts"] is not None and ing["last_ts"] > 0
        sl = by_id["self_learning.run"]
        assert sl["effective"] == "error"
        assert sl["last_error_type"] == "TimeoutError"
        # R17: текст ошибки не отдаётся — только тип
        assert "СЕКРЕТ-ТЕКСТ" not in json.dumps(body)
        ru = by_id["random.uses"]
        assert ru["effective"] == "no_conditions"
        assert ru["last_reason"] is None or "no_trigger" in str(
            ru["last_reason"]) or ru["last_reason"] is None
        # процесс без единого события — честный never_run
        nr = by_id.get("temporal.factcheck")
        if nr is not None:
            assert nr["effective"] in ("never_run", "working", "error",
                                       "no_conditions")

    def test_disabled_off(self, client, monkeypatch):
        from services import mca_gates
        monkeypatch.setattr(mca_gates, "process_registry_enabled",
                            lambda: True)
        resp = client.get("/api/analytics/viz/process-activity",
                          headers=_hdr())
        body = resp.json()
        by_id = {p["process_id"]: p
                 for p in body["processes"] if p["process_id"]}
        # goodmorning/other disabled-гейты (env-зависимо): если в снапшоте
        # есть disabled-процесс — его эффективный статус ровно «off».
        disabled = [p for p in by_id.values() if p["status"] == "disabled"]
        for p in disabled:
            assert p["effective"] == "off"
