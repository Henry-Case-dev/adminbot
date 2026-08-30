"""Epic 85 (T-616, 84.6) — тесты TMA-auth зависимостей (HMAC-initData).

HMAC-вектор генерируется по официальному алгоритму Telegram
(https://docs.telegram-mini-apps.com/platform/init-data):
secret_key = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN);
hash = hex(HMAC_SHA256(data_check_string, secret_key)) — проверяются
корректный/некорректный hash, свежесть auth_date (24 ч), источники
initData (header/query/JSON), requires_permission (403), неизвестный
Telegram ID → пустая user-роль.
"""
import hashlib
import hmac
import json
import logging
import time
import types
import urllib.parse
from contextlib import contextmanager

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from services.permissions import Permissions

TEST_TOKEN = "123456:TEST_TOKEN_FOR_HMAC_VECTOR"


@contextmanager
def caplog_helper():
    """Поймать INFO-логи (tma-auth) на время запроса (список строк)."""
    import io
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setLevel(logging.INFO)
    logger_deps = logging.getLogger("web.api.deps")
    logger_deps.setLevel(logging.INFO)
    logger_deps.addHandler(handler)
    try:
        yield buffer
    finally:
        logger_deps.removeHandler(handler)
        handler.close()


# ── инициализация моков без импорта deps-модуля наверх ──────────────────────
from web.api import deps as deps_mod  # noqa: E402


def make_init_data(token: str, user_id: int = 5885953495,
                   username: str = "nik", auth_date: int | None = None,
                   hash_ok: bool = True) -> str:
    """Валидный/невалидный initData по канону Telegram."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": username}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hash_ok:
        calc_hash = "0" * 64
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


@pytest.fixture
def fake_cache():
    """ConfigCache-стаб с ролями/админами (без PG-инициализации)."""
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
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
    cache._admins = {5885953495: "admin", 1313107079: "moderator"}
    cache._pg_available = False
    cache._initialized = True
    return cache


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    # settings — frozen dataclass: подменяем весь объект (deps читает только токен)
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


def _app(cache):
    app = FastAPI()
    app.state.cache = cache
    return app


class TestInitDataValidation:
    def test_valid_header_accepted(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {"id": user.id}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN)
        resp = client.get("/t", headers={"X-Telegram-Init-Data": init_data})
        assert resp.status_code == 200
        assert resp.json()["id"] == 5885953495

    def test_bad_hash_rejected_401(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN, hash_ok=False)
        resp = client.get("/t", headers={"X-Telegram-Init-Data": init_data})
        assert resp.status_code == 401

    def test_missing_init_data_401(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {}

        client = TestClient(app)
        assert client.get("/t").status_code == 401

    def test_expired_auth_date_401(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {}

        client = TestClient(app)
        stale = make_init_data(TEST_TOKEN,
                               auth_date=int(time.time()) - 90000)
        resp = client.get("/t", headers={"X-Telegram-Init-Data": stale})
        assert resp.status_code == 401

    def test_query_param_fallback(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {"id": user.id}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN)
        resp = client.get("/t", params={"initData": init_data})
        assert resp.status_code == 200

    def test_json_body_fallback(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.post("/t")
        async def t(user=Depends(get_tma_user)):
            return {"id": user.id}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN)
        resp = client.post("/t", json={"initData": init_data})
        assert resp.status_code == 200

    def test_json_body_invalid_json_401(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.post("/t")
        async def t(user=Depends(get_tma_user)):
            return {}

        client = TestClient(app)
        resp = client.post("/t", content=b"{broken", headers={
            "Content-Type": "application/json"})
        assert resp.status_code == 401

    def test_json_body_not_dict_401(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.post("/t")
        async def t(user=Depends(get_tma_user)):
            return {}

        client = TestClient(app)
        resp = client.post("/t", json=["not", "a", "dict"])
        assert resp.status_code == 401

    def test_no_user_field_401(self, fake_cache):
        """Валидный hash, но без user → 401 (no user in init data)."""
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {}

        fields = {"auth_date": str(int(time.time())), "query_id": "AAHkFg"}
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                          hashlib.sha256).digest()
        calc_hash = hmac.new(secret, data_check.encode(),
                             hashlib.sha256).hexdigest()
        init_data = urllib.parse.urlencode(sorted(fields.items())) \
            + f"&hash={calc_hash}"
        client = TestClient(app)
        resp = client.get("/t", headers={"X-Telegram-Init-Data": init_data})
        assert resp.status_code == 401

    def test_tma_context_sets_state(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import tma_context

        @app.get("/t2")
        async def t2(user=Depends(tma_context)):
            return {}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN, user_id=1313107079)
        resp = client.get("/t2", headers={"X-Telegram-Init-Data": init_data})
        assert resp.status_code == 200


class TestRequiresPermission:
    def test_admin_wildcard_allowed(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import requires_permission

        @app.get("/t")
        async def t(user=Depends(requires_permission("access"))):
            return {}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN, user_id=5885953495)
        resp = client.get("/t", headers={"X-Telegram-Init-Data": init_data})
        assert resp.status_code == 200

    def test_moderator_limits_allowed_access_denied(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import requires_permission

        @app.get("/t1")
        async def t1(user=Depends(requires_permission("param.limits.x"))):
            return {}

        @app.get("/t2")
        async def t2(user=Depends(requires_permission("access"))):
            return {}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN, user_id=1313107079)
        hdr = {"X-Telegram-Init-Data": init_data}
        assert client.get("/t1", headers=hdr).status_code == 200
        assert client.get("/t2", headers=hdr).status_code == 403

    def test_unknown_telegram_id_empty_role(self, fake_cache):
        """84.6: неизвестный ID → user-роль с пустыми правами (не 500)."""
        app = _app(fake_cache)
        from web.api.deps import get_tma_user, tma_context

        @app.get("/me")
        async def me(user=Depends(get_tma_user)):
            return {}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN, user_id=777777777)
        resp = client.get("/me", headers={"X-Telegram-Init-Data": init_data})
        assert resp.status_code == 200

    def test_unknown_id_post_denied_403(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import requires_permission

        @app.post("/t")
        async def t(user=Depends(requires_permission("access"))):
            return {}

        client = TestClient(app)
        init_data = make_init_data(TEST_TOKEN, user_id=777777777)
        resp = client.post("/t", headers={"X-Telegram-Init-Data": init_data})
        assert resp.status_code == 403


class TestMaskingHelper:
    def test_key_value_visible_only_with_key_right(self, fake_cache):
        from web.api.deps import can_view_key_value
        # admin wildcard → полный доступ
        assert can_view_key_value(fake_cache, 5885953495, "keys.groq_api_key")
        # moderator: нет секции keys → нет
        assert not can_view_key_value(fake_cache, 1313107079, "keys.groq_api_key")
        # moderator: секция limits покрывает limits-параметр
        assert can_view_key_value(fake_cache, 1313107079,
                                  "limits.search_max_symbols")
        # неизвестный ID → нет
        assert not can_view_key_value(fake_cache, 777, "keys.groq_api_key")


class TestTmaTrace:
    """84.21.4: диагностический лог авторизации ЗА ФЛАГОМ DEBUG_TMA_TRACE
    (без содержимого initData — только длина/результат)."""

    def _app_with_trace(self, fake_cache, monkeypatch):
        monkeypatch.setenv("DEBUG_TMA_TRACE", "1")
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {"id": user.id}

        return app

    def test_trace_logged_on_success(self, fake_cache, monkeypatch):
        app = self._app_with_trace(fake_cache, monkeypatch)
        client = TestClient(app)
        with caplog_helper() as buffer:
            resp = client.get("/t",
                              headers={"X-Telegram-Init-Data":
                                       make_init_data(TEST_TOKEN)})
        assert resp.status_code == 200
        logs = buffer.getvalue()
        assert "tma-auth" in logs and "valid=True" in logs
        # 3: роль/пермишены/источник в трассировке
        assert "role=admin" in logs
        assert "perm=wildcard" in logs
        assert "src=header" in logs

    def test_trace_logged_on_expired(self, fake_cache, monkeypatch):
        app = self._app_with_trace(fake_cache, monkeypatch)
        client = TestClient(app)
        with caplog_helper() as buffer:
            stale = make_init_data(TEST_TOKEN,
                                   auth_date=int(time.time()) - 90000)
            resp = client.get("/t",
                              headers={"X-Telegram-Init-Data": stale})
        assert resp.status_code == 401
        logs = buffer.getvalue()
        assert "tma-auth" in logs and "expired" in logs
        assert "src=header" in logs

    def test_trace_disabled_by_default(self, fake_cache, monkeypatch):
        monkeypatch.delenv("DEBUG_TMA_TRACE", raising=False)
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {"id": user.id}

        client = TestClient(app)
        with caplog_helper() as buffer:
            client.get("/t", headers={"X-Telegram-Init-Data":
                                      make_init_data(TEST_TOKEN)})
        assert "tma-auth" not in buffer.getvalue()


class TestOfficialHmacVector:
    """F9: ОПУБЛИКОВАННЫЙ вектор из официальной документации Telegram
    (https://docs.telegram-mini-apps.com/platform/init-data):

    query_id=AAHdF6IQAAAAAN0XohDhrOrc
    user={"id":279058397,"first_name":"Vladislav","last_name":"Kibenko",
          "username":"vdkfrost","language_code":"ru","is_premium":true}
    auth_date=1662771648
    hash=c501b71e775f74ce10e377dea85a7ea24ecd640b223ea86dfe453e0eaed2e2b2

    Проверяем алгоритм aiogram (check_webapp_signature) на этом векторе —
    сверка с публичным эталоном, а не с собственным генератором."""

    VECTOR_TOKEN = "***"
    VECTOR_HASH = ("c501b71e775f74ce10e377dea85a7ea24ecd640b223ea86d"
                   "fe453e0eaed2e2b2")

    def _init_data(self, hash_value=None) -> str:
        fields = {
            "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
            "user": '{"id":279058397,"first_name":"Vladislav",'
                    '"last_name":"Kibenko","username":"vdkfrost",'
                    '"language_code":"ru","is_premium":true}',
            "auth_date": "1662771648",
        }
        return urllib.parse.urlencode(fields) \
            + "&hash=" + (hash_value or self.VECTOR_HASH)

    def test_published_vector_valid(self):
        from aiogram.utils.web_app import safe_parse_webapp_init_data
        parsed = safe_parse_webapp_init_data(
            token=self.VECTOR_TOKEN, init_data=self._init_data())
        assert parsed.user.id == 279058397
        assert parsed.user.username == "vdkfrost"
        assert parsed.user.first_name == "Vladislav"
        assert parsed.auth_date.timestamp() == 1662771648

    def test_published_vector_tampered_hash_rejected(self):
        from aiogram.utils.web_app import safe_parse_webapp_init_data
        with pytest.raises(ValueError):
            safe_parse_webapp_init_data(
                token=self.VECTOR_TOKEN,
                init_data=self._init_data(hash_value="0" * 64))
