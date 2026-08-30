"""Epic 85 (T-631/T-641, 84.11.4/84.15.2) — тесты эндпоинтов Статус и Control.

Публичность /api/status|/api/status/logs для ЛЮБОЙ валидной TMA-роли
(RBAC-исключение), маскировка секретов уже в ring; /api/control/*: 202
admin+moderator, 403 user, 401 без initData, дебаунс 429, dev-start 409.
"""
import hashlib
import hmac
import json
import logging
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from services.control_service import ControlService
from services.log_ring import get_log_ring
from services.permissions import Permissions
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_STATUS_API"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
USER_ID = 999999999


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


class _FakePg:
    pool = None

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
    # /api/status: psutil-метрики и health-ping мокаем (без реальной сети)
    monkeypatch.setattr(
        "services.status_service.StatusService._server_metrics",
        staticmethod(lambda: {"cpu_percent": 3.0}))

    async def _fake_ping(base, key):
        return {"ok": True, "status": "ok", "http_status": 200,
                "latency_ms": 1.0, "checked_at": "t"}

    monkeypatch.setattr(
        "services.status_service.StatusService._ping_models",
        staticmethod(_fake_ping))

    cache = ConfigCache.__new__(ConfigCache)
    cache._pg = _FakePg()
    cache._settings = {
        "keys.llm_api_key": "",
        "keys.groq_api_key": "",
        "keys.openrouter_api_key": "",
        "models.llm_fallback_base_url": "",
        "models.llm_fallback_model": "",
    }
    cache._roles = {
        "admin": {"permissions": {"wildcard": True}, "is_custom": False},
        "moderator": {"permissions": {
            "sections": ["limits"],
            "actions": ["control.restart", "control.stop", "control.start"],
        }, "is_custom": False},
        "user": {"permissions": {}, "is_custom": False},
    }
    cache._permissions = {
        name: Permissions.from_dict(role["permissions"])
        for name, role in cache._roles.items()
    }
    cache._admins = {ADMIN_ID: "admin", MODERATOR_ID: "moderator"}
    cache._pg_available = False
    cache._initialized = True

    # llm_registry читает hot_config → подключаем ТЕСТОВЫЙ кэш (без реальных
    # ключей из .env)
    from services import hot_config as hot
    hot.set_config_cache(cache)

    control = ControlService(mode="dev", exec_delay=0.01)
    app = create_app(cache, control=control)
    with TestClient(app) as test_client:
        yield test_client
    hot.set_config_cache(None)


def _ring_emit(message: str, level=logging.ERROR, logger_name="test"):
    record = logging.LogRecord(
        name=logger_name, level=level, pathname="x", lineno=1,
        msg=message, args=(), exc_info=None)
    get_log_ring().emit(record)


class TestStatusEndpoint:
    def test_status_public_for_all_roles(self, client):
        for uid in (ADMIN_ID, MODERATOR_ID, USER_ID):
            resp = client.get("/api/status", headers=_hdr(uid))
            assert resp.status_code == 200, uid
            body = resp.json()
            assert set(body) == {"bot", "server", "llm", "uptime"}
            assert body["bot"]["mode"] == "polling"
            assert body["bot"]["version"]
            assert body["server"]["cpu_percent"] == 3.0

    def test_status_requires_tma_auth(self, client):
        assert client.get("/api/status").status_code == 401

    def test_status_500_on_builder_failure(self, client, monkeypatch):
        """84.21.1: билдер упал → 500 (не вечный спиннер на фронте)."""
        async def _boom(cache=None):
            raise RuntimeError("snapshot exploded")

        from services.status_service import status as status_singleton
        monkeypatch.setattr(status_singleton, "build_snapshot", _boom)
        with TestClient(client.app, raise_server_exceptions=False) as raw:
            resp = raw.get("/api/status", headers=_hdr(USER_ID))
        assert resp.status_code == 500

    def test_front_has_error_copy_for_any_non_ok(self):
        """84.21.1: в app.js loadStatus есть текст для не-401/не-403 ошибок."""
        src = open("web/app.js", encoding="utf-8").read()
        assert "Не удалось получить статус сервера" in src

    def test_status_requires_tma_auth(self, client):
        assert client.get("/api/status").status_code == 401

    def test_status_llm_keys_masked(self, client):
        resp = client.get("/api/status", headers=_hdr(USER_ID))
        cards = resp.json()["llm"]
        assert cards
        for card in cards:
            key = card["key"]
            assert set(key) == {"configured", "last4"}
            health = card["health"]
            assert set(health) >= {"ok", "status", "http_status",
                                   "latency_ms", "checked_at"}


class TestStatusLogsEndpoint:
    def test_logs_public_for_all_roles(self, client):
        _ring_emit("проверка логов", level=logging.INFO)
        for uid in (ADMIN_ID, MODERATOR_ID, USER_ID):
            resp = client.get("/api/status/logs", headers=_hdr(uid))
            assert resp.status_code == 200, uid
            body = resp.json()
            assert "count" in body and "logs" in body

    def test_logs_require_tma_auth(self, client):
        assert client.get("/api/status/logs").status_code == 401

    def test_logs_masked_in_buffer(self, client):
        # sk-/gsk_-префиксы и Bearer маскируются regex'ами (84.11.1, R17)
        _ring_emit("Authorization: Bearer sk-abcdef123456789 "
                   "gsk_groq_token_xyz123")
        resp = client.get("/api/status/logs", headers=_hdr(USER_ID),
                          params={"level": "ALL"})
        payload = json.dumps(resp.json()["logs"], ensure_ascii=False)
        assert "abcdef123456789" not in payload
        assert "gsk_groq_token_xyz123" not in payload
        assert "***" in payload

    def test_level_filter(self, client):
        _ring_emit("только-для-debug", level=logging.DEBUG)
        _ring_emit("важная-ошибка", level=logging.ERROR)
        resp = client.get("/api/status/logs", headers=_hdr(USER_ID),
                          params={"level": "ERROR"})
        messages = [e["message"] for e in resp.json()["logs"]]
        assert "важная-ошибка" in messages
        assert "только-для-debug" not in messages

    def test_limit(self, client):
        for i in range(5):
            _ring_emit(f"запись-{i}", level=logging.INFO)
        resp = client.get("/api/status/logs", headers=_hdr(USER_ID),
                          params={"level": "ALL", "limit": 3})
        assert resp.json()["count"] == 3


class TestControlEndpoints:
    def test_restart_202_for_admin_and_moderator(self, client):
        for uid, expected in ((ADMIN_ID, 202), (MODERATOR_ID, 202)):
            resp = client.post("/api/control/restart", headers=_hdr(uid))
            assert resp.status_code == expected, uid
            if expected == 202:
                body = resp.json()
                assert body["action"] == "restart"
                assert body["mode"] == "dev"
            # сброс дебаунса между вызовами (30с в проде — здесь тест-изоляция)
            client.app.state.control._last_call = None

    def test_control_403_for_user(self, client):
        for path in ("/api/control/restart", "/api/control/stop",
                     "/api/control/start"):
            resp = client.post(path, headers=_hdr(USER_ID))
            assert resp.status_code == 403, path

    def test_control_401_without_init_data(self, client):
        assert client.post("/api/control/restart").status_code == 401

    def test_debounce_429(self, client):
        first = client.post("/api/control/restart", headers=_hdr(ADMIN_ID))
        assert first.status_code == 202
        second = client.post("/api/control/stop", headers=_hdr(ADMIN_ID))
        assert second.status_code == 429

    def test_dev_start_409(self, client):
        resp = client.post("/api/control/start", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 409
        assert "dev" in resp.json()["detail"]
