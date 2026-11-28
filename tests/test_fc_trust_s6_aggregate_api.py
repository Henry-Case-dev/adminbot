"""FCT-S6 U3 — API сводных показателей (28.11.2026).

`GET /api/factcheck/temporal/aggregate` — global-admin, read-only,
период/лимит; тело полностью из `summarize_factcheck_aggregates` (S6-U2),
отсутствующие сигналы остаются `null`. UI — компактный блок в существующей
вкладке «Временной фактчек» (без нового раздела).

Проверяется: успешный ответ, период/лимит, пустые сигналы null, отказ без
прав (401/403), отсутствие секретов/текстов в теле, объявленный контракт
маршрутов (`tests/routes_contract.py`).
"""
from __future__ import annotations

import ast
import hashlib
import hmac
import json
import sqlite3
import time
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import services.lore_runtime as lore_runtime
import web.api.deps as deps_mod
import web.api.routes as routes_mod
from services.roles import Permissions

TEST_TOKEN = "123456:TEST-P0-TOKEN"
ADMIN_ID = 700001
USER_ID = 700002


def _init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={digest}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": _init_data(user_id)}


class _FakeCache:
    pg_available = False

    def __init__(self, admin_ids=(ADMIN_ID,)):
        self.admin_ids = set(admin_ids)

    def get_role(self, telegram_id):
        return "admin" if int(telegram_id) in self.admin_ids else "user"

    def roles(self):
        return {"admin": {"role_type": "global_admin", "permissions": {}},
                "user": {"role_type": "user", "permissions": {}}}

    def get_permissions_by_telegram_id(self, telegram_id):
        return None

    def get_permissions(self, role_name):
        return Permissions.from_dict({})


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _SyncDB:
    """Read-only адаптер: endpoint делает SELECT, БД — обычный sqlite3."""

    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    async def execute(self, sql, params=()):
        return _Cursor(self.conn.execute(sql, params).fetchall())

    def close(self):
        self.conn.close()


def _seed(path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            "CREATE TABLE mca_factcheck_runs (run_id TEXT, "
            "correlation_id TEXT, access_scope TEXT, created_at INTEGER, "
            "stage_trace TEXT);"
            "CREATE TABLE mca_factcheck_evidence (run_id TEXT, "
            "opened INTEGER, published_at INTEGER);"
            "CREATE TABLE mca_events (event_name TEXT, "
            "pipeline_run_id TEXT, entity_ids TEXT);")
        conn.execute(
            "INSERT INTO mca_factcheck_runs VALUES (?,?,?,?,?)",
            ("r1", "c1", "chat:1", 200,
             json.dumps([{"stage": "verdict", "outcome": "corrected"}])))
        conn.execute(
            "INSERT INTO mca_factcheck_runs VALUES (?,?,?,?,?)",
            ("r2", "c2", "chat:1", 300,
             json.dumps([{"stage": "verdict", "outcome": "validated"}])))
        conn.executemany(
            "INSERT INTO mca_factcheck_evidence VALUES (?,?,?)",
            [("r1", 0, None), ("r2", 1, 123)])
        conn.execute(
            "INSERT INTO mca_events VALUES (?,?,?)",
            ("factcheck_claims", "c1",
             json.dumps({"execution_status": "complete",
                         "execution_cause": ""})))
        conn.commit()
    finally:
        conn.close()


def _client(monkeypatch, db, *, admin_ids=(ADMIN_ID,)):
    monkeypatch.setattr(
        deps_mod, "settings",
        SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        routes_mod, "settings",
        SimpleNamespace(API_TOKEN=TEST_TOKEN), raising=False)
    cache = _FakeCache(admin_ids)
    monkeypatch.setattr(routes_mod, "get_cache", lambda request: cache)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    app = FastAPI()
    app.include_router(routes_mod.api_router, prefix="/api")
    return TestClient(app)


class TestAggregateApi:
    def test_success_period_and_null_signals(self, tmp_path, monkeypatch):
        path = tmp_path / "agg_api.db"
        _seed(path)
        db = _SyncDB(path)
        try:
            client = _client(monkeypatch, db)
            resp = client.get(
                "/api/factcheck/temporal/aggregate",
                params={"since": 100, "until": 400, "limit": 10},
                headers=_hdr())
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["runs"] == 2
            assert body["period"] == {"since": 100, "until": 400}
            assert body["execution_status"] == {"complete": 1, "unknown": 1}
            assert body["execution_cause"] is None
            assert body["snippet_only_share"] == 0.5
            assert body["date_unknown_share"] == 0.5
            assert body["verdict_mismatch_share"] == 0.5
            assert body["entity_collision_share"] is None
            assert body["media_partial_share"] is None
            assert body["truncated"] is False
        finally:
            db.close()

    def test_limit_and_bounds(self, tmp_path, monkeypatch):
        path = tmp_path / "agg_limits.db"
        _seed(path)
        db = _SyncDB(path)
        try:
            client = _client(monkeypatch, db)
            ok = client.get(
                "/api/factcheck/temporal/aggregate", params={"limit": 1},
                headers=_hdr())
            assert ok.status_code == 200
            assert ok.json()["runs"] == 1        # newest-first (r2, 300)
            assert ok.json()["truncated"] is True
            for bad in ({"limit": 0}, {"limit": 101}, {"since": -1},
                        {"since": 10, "until": 5}):
                resp = client.get(
                    "/api/factcheck/temporal/aggregate", params=bad,
                    headers=_hdr())
                assert resp.status_code == 422, (bad, resp.text)
        finally:
            db.close()

    def test_requires_auth_and_global_admin(self, tmp_path, monkeypatch):
        path = tmp_path / "agg_rbac.db"
        _seed(path)
        db = _SyncDB(path)
        try:
            client = _client(monkeypatch, db)
            assert client.get(
                "/api/factcheck/temporal/aggregate").status_code == 401
            denied = client.get(
                "/api/factcheck/temporal/aggregate", headers=_hdr(USER_ID))
            assert denied.status_code == 403
            assert denied.json().get("detail")
        finally:
            db.close()

    def test_no_secrets_or_private_text_in_body(self, tmp_path, monkeypatch):
        path = tmp_path / "agg_secret.db"
        _seed(path)
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(
                "ALTER TABLE mca_factcheck_runs ADD COLUMN claim_text TEXT")
            conn.execute(
                "UPDATE mca_factcheck_runs SET claim_text = ? "
                "WHERE run_id = 'r1'", ("SECRET-CLAIM-TEXT",))
            conn.commit()
        finally:
            conn.close()
        db = _SyncDB(path)
        try:
            client = _client(monkeypatch, db)
            resp = client.get(
                "/api/factcheck/temporal/aggregate", headers=_hdr())
            assert resp.status_code == 200
            text = resp.text
            for token in ("SECRET-CLAIM-TEXT", "api_key", "token",
                          "secret", "password", "http://", "https://"):
                assert token not in text, token
        finally:
            db.close()


class TestRoutesPin:
    def test_routes_contract_intact_with_new_endpoint(self):
        # routes.py не пинится sha256 (устранён механический re-pin
        # FCT-S6 U3). Контракт объявляет новый endpoint явно:
        # GET /api/factcheck/temporal/aggregate с global-admin проверкой.
        from tests.routes_contract import assert_routes_contract_intact
        assert_routes_contract_intact()
        from tests.routes_contract import load_manifest
        rows = [r for r in load_manifest()["routes"]
                if r["path"] == "/factcheck/temporal/aggregate"]
        assert len(rows) == 1
        assert rows[0]["methods"] == ["GET"]
        assert rows[0]["init_data"] is True
        assert "requires_global_admin" in rows[0]["checks"] or \
            "_ctx_global_admin" in rows[0]["checks"]


class TestUiStructure:
    """Без живого браузера: разметка/лоадер присутствуют, JS синтаксически
    валиден. Живой Playwright-сценарий требует MiniApp-сессии (initData),
    поэтому здесь структурная проверка — честно отмечено в evidence."""

    def test_existing_temporal_tab_has_compact_summary_block(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "web" / "app.js").read_text(encoding="utf-8")
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        assert "temporalAggregate: null" in js
        assert "loadTemporalAggregate: function" in js
        assert "/api/factcheck/temporal/aggregate?limit=100" in js
        assert "temporalAggregateText: function" in js
        assert "data-fc-aggregate" in html
        assert "temporalAggregateText()" in html
        # оговорка для отсутствующего сигнала — без выдуманного нуля
        assert "не измеряется" in js

    def test_app_js_syntax_valid(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if node is None:
            pytest.skip("node недоступен для синтаксической проверки")
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [node, "--check", str(root / "web" / "app.js")],
            capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr[:2000]


class TestFactoryFlag:
    def test_factory_default_v2_is_enabled(self):
        """Правило проекта 09.11.2026: готовый путь ON по умолчанию.
        Проверяется именно литерал завода в `Settings` (AST), а не
        effective-значение окружения/БД."""
        path = (Path(__file__).resolve().parent.parent
                / "config" / "settings.py")
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        default = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name != "Settings":
                continue
            for item in node.body:
                if not isinstance(item, ast.AnnAssign):
                    continue
                target = item.target
                if getattr(target, "id", "") != \
                        "FACTCHECK_PIPELINE_V2_ENABLED":
                    continue
                call = item.value
                if isinstance(call, ast.Call) and len(call.args) >= 2:
                    default = ast.literal_eval(call.args[1])
        assert default is True

    def test_hot_override_preserved(self, monkeypatch):
        """Сохранённое значение (hot/PG) не перезаписывается дефолтом."""
        from services import factcheck_orchestrator as orch
        from services import hot_config as hot
        from config.settings import settings
        old = settings.FACTCHECK_PIPELINE_V2_ENABLED
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
        try:
            monkeypatch.setattr(hot, "get",
                                lambda key, default=None: False
                                if key == "flags.factcheck_pipeline_v2"
                                else default)
            assert orch.pipeline_v2_enabled() is False
            monkeypatch.setattr(hot, "get",
                                lambda key, default=None: default)
            assert orch.pipeline_v2_enabled() is True
        finally:
            object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)
