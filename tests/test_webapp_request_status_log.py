"""Наблюдаемость отказов: одна R17-safe строка на non-2xx под `/api/*`.

Прод-инцидент: uvicorn `log_level="warning"` + Caddy без access-log → отказ
Mini App не привязать к пути/статусу/юзеру (в журнале только успешные
`[tma-auth]` и 401, ни одного 403). Гейты (реальный `create_app` +
TestClient):

  * 403 через реальное приложение → РОВНО одна строка с method/path/status/
    telegram_id и reason=permission_denied; initData/токен/hash не утекли;
  * 401 без initData → reason=missing_init_data, user=- (нет id);
  * 2xx → строки нет (нулевая стоимость здорового пути);
  * 500 → exc=<тип>, без тела/сообщения исключения и без трейсбека;
  * путь нормализован: шаблон маршрута, никакого query string и конкретных
    числовых id.
"""
import hashlib
import hmac
import json
import logging
import re
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services.permissions import Permissions
from web.api import deps as deps_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_HMAC_VECTOR"
USER_ID = 5885953495
LOGGER_NAME = "web.request_status"
PREFIX = "[api-status]"

# Строгий формат строки 4xx: только allowlisted поля, ничего свободного.
_LINE_RE = re.compile(
    r"^\[api-status\] method=[A-Z]+ path=/api/\S* status=4\d\d "
    r"user=(-|\d+) reason=[a-z_]+$")


def make_init_data(token: str, user_id: int = USER_ID,
                   auth_date: int | None = None) -> str:
    """Валидный initData по канону Telegram (как в test_webapp_deps)."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None
                         else int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "nik"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


class _StubCache:
    """Минимальный ConfigCache-стаб: роль по умолчанию `user` (без прав)."""

    def __init__(self):
        self.is_initialized = True
        self.pg_available = False

    async def init(self):  # pragma: no cover - вызывается только если не init
        self.is_initialized = True

    def get_role(self, telegram_id):
        return "user"

    def roles(self):
        return {"user": {"permissions": {}, "is_custom": False}}

    def get_permissions(self, role_name):
        return Permissions.from_dict({})

    def get_permissions_by_telegram_id(self, telegram_id):
        return None


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    # create_app → web.api.deps читает settings.API_TOKEN: подменяем объект.
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


@pytest.fixture
def lines(caplog):
    """Собрать строки ТОЛЬКО нашего логгера (INFO — 4xx, WARNING — 5xx)."""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    def _collect():
        return [r.getMessage() for r in caplog.records
                if r.name == LOGGER_NAME and
                r.getMessage().startswith(PREFIX)]

    return _collect


@pytest.fixture
def client():
    app = create_app(_StubCache())
    with TestClient(app) as test_client:
        yield test_client


def _hdr(init_data: str) -> dict:
    return {"X-Telegram-Init-Data": init_data}


class TestDenialsAreVisible:
    def test_403_logs_one_line_with_path_status_and_user(self, client, lines):
        """Реальный /api/admins: у роли user нет права `access` → 403."""
        init_data = make_init_data(TEST_TOKEN)
        resp = client.get(
            "/api/admins",
            headers={**_hdr(init_data),
                     "Authorization": "Bearer SUPER_SECRET_BEARER_TOKEN",
                     "Cookie": "session=SECRET_COOKIE_VALUE"},
            params={"token": "SECRET_IN_QUERY"})
        assert resp.status_code == 403

        emitted = lines()
        assert len(emitted) == 1, emitted
        line = emitted[0]
        # Ровно одна строка строгого формата: только allowlisted поля.
        assert _LINE_RE.match(line), line
        assert "method=GET" in line
        assert "path=/api/admins" in line
        assert "status=403" in line
        assert f"user={USER_ID}" in line
        assert "reason=permission_denied" in line
        # Redaction: ни initData, ни hash/подписи, ни токена бота/носителя,
        # ни cookie, ни query string.
        assert init_data not in line
        assert "hash=" not in line
        assert "auth_date" not in line
        assert TEST_TOKEN not in line
        assert "SUPER_SECRET_BEARER_TOKEN" not in line
        assert "SECRET_COOKIE_VALUE" not in line
        assert "SECRET_IN_QUERY" not in line
        assert "X-Telegram-Init-Data" not in line
        assert "Authorization" not in line
        assert "Cookie" not in line
        assert "?" not in line

    def test_401_missing_init_data_reason_without_user(self, client, lines):
        resp = client.get("/api/me")
        assert resp.status_code == 401

        emitted = lines()
        assert len(emitted) == 1, emitted
        line = emitted[0]
        assert "path=/api/me" in line
        assert "status=401" in line
        assert "user=-" in line
        assert "reason=missing_init_data" in line

    def test_401_invalid_init_data_has_reason(self, client, lines):
        bad = make_init_data(TEST_TOKEN).replace("hash=", "hash=0")
        resp = client.get("/api/me", headers=_hdr(bad))
        assert resp.status_code == 401
        line = lines()[0]
        assert "reason=invalid_init_data" in line
        assert "user=-" in line

    def test_403_not_global_admin_reason(self, client, lines):
        """requires_global_admin: свой reason-код, отличимый от permission_denied."""
        init_data = make_init_data(TEST_TOKEN)
        resp = client.get("/api/youtube/proxy/health", headers=_hdr(init_data))
        assert resp.status_code == 403
        line = lines()[0]
        assert f"user={USER_ID}" in line
        assert "status=403" in line
        assert "reason=not_global_admin" in line


class TestHealthyPathIsSilent:
    def test_2xx_produces_no_line(self, client, lines):
        # /api/health — 2xx под /api: строки быть не должно (нулевая цена).
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health").status_code == 200
        assert lines() == []

    def test_non_api_paths_are_not_logged(self, client, lines):
        """Вне /api/* middleware не пишет ничего (0 стоимости и 0 шума)."""
        assert client.get("/healthz").status_code == 200
        assert client.get("/media/junk-file.mp4").status_code == 404
        assert client.get("/web/").status_code == 200
        assert lines() == []


class TestServerErrors:
    def test_500_logs_exception_type_only(self, lines):
        app = create_app(_StubCache())

        @app.get("/api/_probe_boom")
        async def _boom():
            raise RuntimeError("super-secret-body-text")

        with TestClient(app, raise_server_exceptions=False) as test_client:
            resp = test_client.get("/api/_probe_boom")
        assert resp.status_code == 500

        emitted = lines()
        assert len(emitted) == 1, emitted
        line = emitted[0]
        assert "path=/api/_probe_boom" in line
        assert "status=500" in line
        assert "exc=RuntimeError" in line
        # Никакого дублирования сообщения/трейсбека в нашей строке.
        assert "super-secret-body-text" not in line
        assert "Traceback" not in line


class TestPathNormalization:
    def test_route_template_replaces_numeric_ids(self, client, lines):
        """/api/avatar/user/<id> → шаблон `/api/avatar/{kind}/{tid}`."""
        init_data = make_init_data(TEST_TOKEN)
        resp = client.get(f"/api/avatar/user/{USER_ID}",
                          headers=_hdr(init_data),
                          params={"token": "TOP_SECRET_QUERY"})
        assert resp.status_code == 404  # бот в тестах не подключён

        line = lines()[0]
        assert "path=/api/avatar/{kind}/{tid}" in line
        assert "status=404" in line
        # Конкретный числовой id в PATH не попадает (он есть только в user=).
        path_field = line.split("path=", 1)[1].split(" status=", 1)[0]
        assert str(USER_ID) not in path_field
        assert "TOP_SECRET_QUERY" not in line
        assert "token=" not in line
        assert "?" not in line

    def test_unmatched_api_path_logged_without_query(self, client, lines):
        resp = client.get("/api/nope/123",
                          params={"initData": "SECRET_IN_QUERY"})
        assert resp.status_code == 404
        line = lines()[0]
        assert "path=/api/nope/123" in line
        assert "SECRET_IN_QUERY" not in line
        assert "?" not in line

    def test_mounted_root_path_still_logged(self, lines):
        """Приложение за префиксом прокси (root_path) логирует path=/api/..."""
        app = create_app(_StubCache())
        with TestClient(app, root_path="/tma") as test_client:
            assert test_client.get("/api/me").status_code == 401
        line = lines()[0]
        assert "path=/api/me" in line
        assert "/tma/api" not in line
