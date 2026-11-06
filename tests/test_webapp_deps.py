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


class TestTmaAuthMaxAge:
    """Фин. доработка DevOps: TMA_AUTH_MAX_AGE — свежесть initData."""

    def _app(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {"id": user.id}

        return app

    def test_default_24h(self, monkeypatch, fake_cache):
        monkeypatch.delenv("TMA_AUTH_MAX_AGE", raising=False)
        client = TestClient(self._app(fake_cache))
        stale = make_init_data(TEST_TOKEN, auth_date=int(time.time()) - 90000)
        assert client.get("/t", headers={"X-Telegram-Init-Data": stale}) \
            .status_code == 401

    def test_small_max_age_expires(self, monkeypatch, fake_cache):
        monkeypatch.setenv("TMA_AUTH_MAX_AGE", "10")
        client = TestClient(self._app(fake_cache))
        old = make_init_data(TEST_TOKEN, auth_date=int(time.time()) - 60)
        assert client.get("/t", headers={"X-Telegram-Init-Data": old}) \
            .status_code == 401

    def test_zero_disables_freshness_check(self, monkeypatch, fake_cache):
        monkeypatch.setenv("TMA_AUTH_MAX_AGE", "0")
        client = TestClient(self._app(fake_cache))
        # auth_date 2022 — просрочен, но max_age=0 → свежесть не проверяется
        stale = make_init_data(TEST_TOKEN, auth_date=1652249232)
        resp = client.get("/t", headers={"X-Telegram-Init-Data": stale})
        assert resp.status_code == 200

    def test_broken_value_falls_back_to_default(self, monkeypatch, fake_cache):
        monkeypatch.setenv("TMA_AUTH_MAX_AGE", "мусор")
        client = TestClient(self._app(fake_cache))
        stale = make_init_data(TEST_TOKEN, auth_date=int(time.time()) - 90000)
        assert client.get("/t", headers={"X-Telegram-Init-Data": stale}) \
            .status_code == 401


class TestTracePath:
    """path в fail-логе (без query)."""

    def test_fail_log_contains_path(self, fake_cache, monkeypatch):
        monkeypatch.setenv("DEBUG_TMA_TRACE", "1")
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/api/trace/path")
        async def t(user=Depends(get_tma_user)):
            return {}

        client = TestClient(app)
        with caplog_helper() as buffer:
            client.get("/api/trace/path")   # no initData → missing
        logs = buffer.getvalue()
        assert "tma-auth" in logs
        assert "path=/api/trace/path" in logs


class TestFrontNoContext:
    """Фин. доработка: заглушка без Telegram-контекста вместо 401-спама.
    Проверяем НЕ строковые совпадения имён, а реальный код: в retryInitData
    обязаны быть var self = this, self.loadConfig, блокировка при !me."""

    def _src(self):
        src = open("web/app.js", encoding="utf-8").read()
        # вырезать тело retryInitData
        start = src.index("retryInitData: function")
        end = src.index("},", start)
        return src[start:end], src

    def test_retry_binds_self_and_config(self):
        body, _ = self._src()
        assert "var self = this" in body
        assert "self.loadConfig()" in body
        assert "self.canViewTab('access')" in body
        assert "self.loadAdmins()" in body
        assert "self.loadRoles()" in body

    def test_retry_locks_when_me_missing(self):
        body, _ = self._src()
        assert "if (!me)" in body
        assert "self.authLocked = true" in body
        assert "self.authError" in body

    def test_retry_locks_without_context(self):
        body, _ = self._src()
        assert "if (!this.hasInitData())" in body
        assert "без Telegram-контекста" in body

    def test_mounted_subscribes_to_ready_event(self):
        _, src = self._src()
        assert "Telegram.WebApp.onEvent('ready'" in src

    def test_index_has_locked_banner(self):
        src = open("web/index.html", encoding="utf-8").read()
        assert 'v-if="authLocked"' in src
        assert "Попробовать снова" in src


class TestTmaAuthMaxAgeFinite:
    """nan/inf в TMA_AUTH_MAX_AGE → default 86400 (ревью-LOW)."""

    def _app(self, fake_cache):
        app = _app(fake_cache)
        from web.api.deps import get_tma_user

        @app.get("/t")
        async def t(user=Depends(get_tma_user)):
            return {"id": user.id}

        return app

    def test_nan_falls_back(self, monkeypatch, fake_cache):
        monkeypatch.setenv("TMA_AUTH_MAX_AGE", "nan")
        client = TestClient(self._app(fake_cache))
        stale = make_init_data(TEST_TOKEN, auth_date=int(time.time()) - 90000)
        assert client.get("/t", headers={"X-Telegram-Init-Data": stale}) \
            .status_code == 401

    def test_inf_falls_back(self, monkeypatch, fake_cache):
        monkeypatch.setenv("TMA_AUTH_MAX_AGE", "inf")
        client = TestClient(self._app(fake_cache))
        stale = make_init_data(TEST_TOKEN, auth_date=int(time.time()) - 90000)
        assert client.get("/t", headers={"X-Telegram-Init-Data": stale}) \
            .status_code == 401


class TestFrontFixes:
    """ФИКСЫ фронта 2026-09-03 — статические проверки кода (JS-тестов в
    проекте нет; node --check в CI-отчёте Builder)."""

    def test_mounted_autoloads_active_tab(self):
        src = open("web/app.js", encoding="utf-8").read()
        # ФИКС 1: после успешного auth вызывается per-tab loader активной
        # вкладки (было: loaders только в setTab → статус до переключения
        # не грузился). Встречается в mounted И retryInitData.
        assert src.count("self.setTab(self.activeTab)") >= 2

    def test_is_key_configured_handles_string_value(self):
        src = open("web/app.js", encoding="utf-8").read()
        # ФИКС 4: ключ как строка (право на значение/админ) = «настроен»
        assert "typeof v === 'object'" in src
        assert "typeof v === 'string'" in src
        assert "return !!v.configured" in src

    def test_select_dark_styling_present(self):
        # F4 10.16: CSS-канон вынесен из inline <style> в web/static/app.css.
        src = open("web/static/app.css", encoding="utf-8").read()
        # ФИКС 6: native <select> на тёмном фоне (было: белый UA-стиль)
        assert "select.field {" in src
        # Редизайн 10.5 (T-1098): тёмный фон — из токена --surface-3 (эталон).
        assert "background-color: var(--surface-3)" in src
        assert "select.field option {" in src

    def test_toggle_sends_items_payload(self):
        src = open("web/app.js", encoding="utf-8").read()
        # ФИКС 5: тумблер bool @change → saveConfigItem → POST {items:[{key,value}]}
        # 10.12: payload расширен updated_at/global-опцией — проверяем items-ядро.
        assert "items: [{ key: item.key, value: value }]" in src
        assert "@change=\"saveConfigItem(item)\"" in open(
            "web/index.html", encoding="utf-8").read()

    def test_grouping_logic_present(self):
        """84.24: фронт группирует параметры по item.group с порядком из
        groups[]; параметры без группы — «Прочее» в конце. После рефакторинга
        T25/3.5.1 пять категорийных шаблонов схлопнуты: группировка живёт в
        groupedForTab() (+ tabSourceForItem для правил sources вкладки) под
        generic-рендером index.html по currentTabGroups — проверяем его."""
        src = open("web/app.js", encoding="utf-8").read()
        assert "groupedForTab: function" in src
        assert "tabSourceForItem: function" in src
        assert "configGroups" in src
        assert "groupTitle: function" in src
        assert "'Прочее'" in src
        assert "configSearch" in src
        assert "clearConfigSearch: function" in src
        html = open("web/index.html", encoding="utf-8").read()
        assert "Поиск по параметрам…" in html
        assert "currentTabGroups" in html       # generic-рендер групп вкладки
        # описания: limits/flags — раскрывашка, prompts/keys/models — видно
        assert "<summary class=\"cursor-pointer select-none text-gray-500\">Что это?</summary>" in html
        assert "item.description" in html
        # 84.24-ревью: пустое состояние поиска; сброс поиска при setTab
        assert "Ничего не найдено по запросу" in html
        assert "if (this.configSearch) this.configSearch = ''" in src
        assert "limitsAndFlags" not in src        # мёртвый computed удалён


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

    VECTOR_TOKEN = "5768337691:AAH5YkoiEuPk8-FZa32hStHTqXiLPtAEhx8"
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


# ═══ ACL-контекст запуска Mini App (группа / диплинк) ═══════════════════════
#
# КОНТРАКТ (проверенные факты диагностики, не пересматриваются): авторизация
# TMA — ТОЛЬКО подписанный `user.id` (HMAC + свежесть auth_date + обязательный
# user); `chat_type`, `chat_instance`, `start_param` и payload запуска —
# ДАННЫЕ запуска, а не права. Чат-скоуп берётся из `chat_admins` по
# (user.id, chat_id); `initDataUnsafe` не участвует.
#
# Эти тесты закрывают конкретную дыру: групповой запуск или диплинк на чужой
# чат не должны расширять доступ. Мутации, от которых они обязаны краснеть:
#   * «данные запуска → chat_id/права» (launch chat попадает в скоуп);
#   * снятый role-check на привилегированной записи (admins/param_permissions);
#   * снятый chat-скоуп guard на реальном чтении чужого чата.

GROUP_CHAT_ID = -1001234567890      # группа, из которой «запущен» Mini App
FOREIGN_CHAT_ID = -1007777777777    # чат, куда ведёт диплинк (чужой)
NON_ADMIN_ID = 555444333            # авторизован, но без грантов
CHAT_ADMIN_ID = 700001              # local_admin ТОЛЬКО в GROUP_CHAT_ID


def make_launch_init_data(token: str, user_id: int, *,
                          chat_id: int | None = None,
                          chat_type: str | None = None,
                          chat_instance: str | None = None,
                          start_param: str | None = None,
                          auth_date: int | None = None,
                          hash_ok: bool = True,
                          tamper: dict | None = None) -> str:
    """Подписанный initData С данными запуска (группа/диплинк/чат).

    `tamper` — поля, подменяемые ПОСЛЕ подписи (подпись перестаёт сходиться),
    что и проверяет негатив-кейс «подпись важнее payload».
    """
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A", "username": "u"},
                           separators=(",", ":")),
    }
    if chat_type is not None:
        fields["chat_type"] = chat_type
    if chat_instance is not None:
        fields["chat_instance"] = chat_instance
    if start_param is not None:
        fields["start_param"] = start_param
    if chat_id is not None:
        fields["chat"] = json.dumps(
            {"id": chat_id, "type": chat_type or "group", "title": "G"},
            separators=(",", ":"))
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hash_ok:
        calc_hash = "0" * 64
    if tamper:
        fields.update(tamper)
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


class _LaunchConn:
    """Мини-подделка asyncpg-коннекта: chat_admins / chat_profiles / журнал."""

    def __init__(self, chat_admins: dict, profiles):
        self.chat_admins = dict(chat_admins)     # {(chat_id, tg): role_name}
        self.profiles = set(profiles)
        self.executed: list[tuple] = []

    async def fetchrow(self, sql, *args):
        if "FROM chat_admins" in sql:
            role = self.chat_admins.get((args[0], args[1]))
            return {"role_name": role} if role is not None else None
        if "FROM chat_profiles" in sql:
            return {"exists": 1} if args[0] in self.profiles else None
        raise AssertionError(f"неожиданный fetchrow: {sql}")

    async def fetch(self, sql, *args):
        assert "FROM chat_profiles p" in sql
        user_id = args[0]
        return [{"chat_id": cid, "is_active": True,
                 "chat_role": self.chat_admins.get((cid, user_id))}
                for cid in sorted(self.profiles)]

    async def execute(self, sql, *args):
        self.executed.append((sql.split("(")[0][:48], args))
        return "OK"

    def transaction(self):
        class _Tx:
            async def __aenter__(self_):
                return self_

            async def __aexit__(self_, *exc):
                return False

        return _Tx()


class _LaunchPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self_):
                return conn

            async def __aexit__(self_, *exc):
                return False

        return _CM()


class _LaunchPg:
    def __init__(self, conn):
        self.pool = _LaunchPool(conn)


class _LaunchCache:
    """ConfigCache-стаб: роли 84.6 + pg-заглушка для chat_admins/chat_profiles."""

    def __init__(self, admins: dict, chat_admins: dict | None = None,
                 profiles=()):
        self._roles = {
            "admin": {"permissions": {"wildcard": True},
                      "role_type": "global_admin"},
            "local_admin": {"permissions": {"sections": ["limits"]},
                            "role_type": "local_admin"},
            "user": {"permissions": {}, "role_type": "user"},
        }
        self._admins = dict(admins)
        self.conn = _LaunchConn(chat_admins or {}, profiles)
        self.pg = _LaunchPg(self.conn)

    def get_role(self, telegram_id):
        return self._admins.get(telegram_id)

    def get_permissions_by_telegram_id(self, telegram_id):
        role = self.get_role(telegram_id)
        if role is None or role not in self._roles:
            return None
        return Permissions.from_dict(self._roles[role].get("permissions", {}))

    def get_permissions(self, role_name):
        role = self._roles.get(role_name)
        if role is None:
            return None
        return Permissions.from_dict(role.get("permissions", {}))

    def roles(self):
        return dict(self._roles)


@pytest.fixture
def launch_cache():
    """NON_ADMIN — без грантов; CHAT_ADMIN — local_admin в GROUP_CHAT_ID."""
    return _LaunchCache(
        {NON_ADMIN_ID: "user", CHAT_ADMIN_ID: "user"},
        chat_admins={(GROUP_CHAT_ID, CHAT_ADMIN_ID): "local_admin"},
        profiles={GROUP_CHAT_ID, FOREIGN_CHAT_ID},
    )


def _launch_app(cache, monkeypatch):
    """Реальные роутеры /api/access/* + реальный chat-scope guard (без бота)."""
    from web.api import access as access_mod
    from web.api.access import access_router
    from web.api.mechanism_diagnostics import mechanism_diagnostics_router

    async def _display_info(chat_id):
        return {}

    monkeypatch.setattr(access_mod, "chat_display_info", _display_info)
    app = _app(cache)
    # префиксы — как в web/app.py (реальные пути /api/access/* и /api/*)
    app.include_router(access_router, prefix="/api/access")
    app.include_router(mechanism_diagnostics_router, prefix="/api")
    return app


class TestGroupOriginLaunchContext:
    """Групповой/диплинковый запуск Mini App не расширяет доступ."""

    def test_signed_launch_payload_has_no_chat_scope_on_user(self):
        """Подписанный group-запуск парсится, но единственный источник прав —
        `user` — не несёт chat-полей: chat_type/chat_instance/start_param/chat
        остаются данными запуска."""
        from aiogram.utils.web_app import safe_parse_webapp_init_data
        raw = make_launch_init_data(
            TEST_TOKEN, NON_ADMIN_ID, chat_id=GROUP_CHAT_ID,
            chat_type="group", chat_instance="ci-opaque-abc",
            start_param=str(FOREIGN_CHAT_ID))
        parsed = safe_parse_webapp_init_data(token=TEST_TOKEN, init_data=raw)
        assert parsed.chat_type == "group"
        assert parsed.chat_instance == "ci-opaque-abc"
        assert parsed.start_param == str(FOREIGN_CHAT_ID)
        assert parsed.chat.id == GROUP_CHAT_ID
        assert parsed.user.id == NON_ADMIN_ID
        for attr in ("chat_id", "chat", "chat_type", "chat_instance",
                     "start_param"):
            assert not hasattr(parsed.user, attr)

    def test_group_origin_me_matches_private_launch(self, launch_cache,
                                                    monkeypatch):
        """/api/access/me с групповым запуском == приватный запуск: тот же
        ответ, никакого лишнего чата/роли."""
        client = TestClient(_launch_app(launch_cache, monkeypatch))
        private = client.get("/api/access/me", headers={
            "X-Telegram-Init-Data":
                make_init_data(TEST_TOKEN, user_id=NON_ADMIN_ID)})
        group = client.get("/api/access/me", headers={
            "X-Telegram-Init-Data": make_launch_init_data(
                TEST_TOKEN, NON_ADMIN_ID, chat_id=GROUP_CHAT_ID,
                chat_type="group", chat_instance="ci-1",
                start_param=str(GROUP_CHAT_ID))})
        assert private.status_code == 200 and group.status_code == 200
        assert private.json() == group.json()
        body = group.json()
        assert body["role_chat"] is None
        assert body["is_local_admin"] is False
        assert body["is_global_admin"] is False
        assert body["rank"] == 1
        # единственный чат — свой ЛС; «запущенной» группы в скоупе НЕТ
        assert body["chats"] == [{"chat_id": NON_ADMIN_ID, "role": "dm"}]

    def test_group_origin_chats_list_has_no_launch_chat(self, launch_cache,
                                                        monkeypatch):
        """Селектор чатов: группа запуска и чужие чаты не появляются; активный
        X-Chat-Id не даёт роли без строки chat_admins."""
        client = TestClient(_launch_app(launch_cache, monkeypatch))
        hdr = {"X-Telegram-Init-Data": make_launch_init_data(
            TEST_TOKEN, NON_ADMIN_ID, chat_id=GROUP_CHAT_ID,
            chat_type="group", chat_instance="ci-2")}
        resp = client.get("/api/access/chats", headers=hdr)
        assert resp.status_code == 200
        assert [c["chat_id"] for c in resp.json()] == [NON_ADMIN_ID]
        me = client.get("/api/access/me",
                        headers={**hdr, "X-Chat-Id": str(GROUP_CHAT_ID)})
        assert me.status_code == 200
        assert me.json()["role_chat"] is None
        assert me.json()["is_local_admin"] is False

    def test_start_param_does_not_widen_chat_read(self, launch_cache,
                                                  monkeypatch):
        """Диплинк (start_param) на чужой чат: реальный chat-scope guard
        отдаёт 403, админский слой — тоже 403."""
        client = TestClient(_launch_app(launch_cache, monkeypatch))
        hdr = {"X-Telegram-Init-Data": make_launch_init_data(
            TEST_TOKEN, NON_ADMIN_ID, chat_id=GROUP_CHAT_ID,
            chat_type="group", chat_instance="ci-3",
            start_param=str(FOREIGN_CHAT_ID))}
        diag = client.get("/api/initiative/mechanism-diagnostics",
                          headers={**hdr, "X-Chat-Id": str(FOREIGN_CHAT_ID)})
        assert diag.status_code == 403
        own = client.get("/api/initiative/mechanism-diagnostics",
                         headers={**hdr, "X-Chat-Id": str(GROUP_CHAT_ID)})
        assert own.status_code == 403
        assert client.get("/api/access/param_permissions",
                          headers=hdr).status_code == 403

    def test_non_admin_privileged_write_403_group_and_private(
            self, launch_cache, monkeypatch):
        """Привилегированная запись (грант chat_admins) — 403 и с групповым,
        и с приватным запуском; журнал пуст (ничего не записано)."""
        client = TestClient(_launch_app(launch_cache, monkeypatch))
        body = {"telegram_id": NON_ADMIN_ID, "role_name": "local_admin"}
        group = client.post(
            f"/api/access/chats/{GROUP_CHAT_ID}/admins", json=body,
            headers={"X-Telegram-Init-Data": make_launch_init_data(
                TEST_TOKEN, NON_ADMIN_ID, chat_id=GROUP_CHAT_ID,
                chat_type="group", chat_instance="ci-4")})
        private = client.post(
            f"/api/access/chats/{GROUP_CHAT_ID}/admins", json=body,
            headers={"X-Telegram-Init-Data":
                     make_init_data(TEST_TOKEN, user_id=NON_ADMIN_ID)})
        assert group.status_code == 403 and private.status_code == 403
        assert launch_cache.conn.executed == []

    def test_chat_grant_rights_equal_for_group_and_private_launch(
            self, launch_cache, monkeypatch):
        """Носитель гранта chat_admins получает одинаковые права при групповом
        и приватном запуске; на чат без гранта — 403."""
        client = TestClient(_launch_app(launch_cache, monkeypatch))
        private_hdr = {
            "X-Telegram-Init-Data":
                make_init_data(TEST_TOKEN, user_id=CHAT_ADMIN_ID),
            "X-Chat-Id": str(GROUP_CHAT_ID)}
        group_hdr = {
            "X-Telegram-Init-Data": make_launch_init_data(
                TEST_TOKEN, CHAT_ADMIN_ID, chat_id=GROUP_CHAT_ID,
                chat_type="group", chat_instance="ci-5"),
            "X-Chat-Id": str(GROUP_CHAT_ID)}
        private = client.get("/api/access/me", headers=private_hdr)
        group = client.get("/api/access/me", headers=group_hdr)
        assert private.status_code == 200 and group.status_code == 200
        assert private.json() == group.json()
        assert group.json()["role_chat"] == "local_admin"
        assert group.json()["is_local_admin"] is True
        assert group.json()["rank"] == 3
        foreign = client.get(
            "/api/initiative/mechanism-diagnostics",
            headers={**group_hdr, "X-Chat-Id": str(FOREIGN_CHAT_ID)})
        assert foreign.status_code == 403

    def test_group_origin_auth_failures_stay_401(self, launch_cache,
                                                 monkeypatch):
        """Негатив для group-origin payload: просроченный auth_date, битая
        подпись и подмена поля после подписи — 401 (и на записи тоже)."""
        monkeypatch.delenv("TMA_AUTH_MAX_AGE", raising=False)
        client = TestClient(_launch_app(launch_cache, monkeypatch))
        stale = make_launch_init_data(
            TEST_TOKEN, NON_ADMIN_ID, chat_id=GROUP_CHAT_ID,
            chat_type="group", chat_instance="ci-6",
            auth_date=int(time.time()) - 90000)
        bad_hash = make_launch_init_data(
            TEST_TOKEN, NON_ADMIN_ID, chat_id=GROUP_CHAT_ID,
            chat_type="group", chat_instance="ci-6", hash_ok=False)
        tampered = make_launch_init_data(
            TEST_TOKEN, NON_ADMIN_ID, chat_id=GROUP_CHAT_ID,
            chat_type="group", chat_instance="ci-6", start_param="own",
            tamper={"start_param": str(FOREIGN_CHAT_ID)})
        for raw in (stale, bad_hash, tampered):
            resp = client.get("/api/access/me",
                              headers={"X-Telegram-Init-Data": raw})
            assert resp.status_code == 401, raw[:80]
        denied = client.post(
            f"/api/access/chats/{GROUP_CHAT_ID}/admins",
            json={"telegram_id": NON_ADMIN_ID, "role_name": "local_admin"},
            headers={"X-Telegram-Init-Data": tampered})
        assert denied.status_code == 401
