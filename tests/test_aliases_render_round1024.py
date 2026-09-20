"""F10 round 10.24 (aliases-render-real-fix-round1024, ADR-1024-11) —
контракт рендера `limits.summary_aliases` (widget='keyvalue').

Покрытие:
  * `GET /api/config` для владельца отдаёт `widget='keyvalue'` и `value`-объект
    (не строку/не пустоту) — вход KV-редактора;
  * per-chat override → эффективное `value` = override, `chat_source='chat'`,
    `global_value` — объект глобального слоя (D3);
  * kill-switch `ALIASES_KEYSVALUE_RENDER_ENABLED` доставляется через
    `GET /api/me.ui_flags` (default ON; OFF по env-флагу);
  * `manage.py diag aliases` — READ-ONLY (SQL-трасса: только SELECT) и
    R17-безопасен (форма/число ключей, без значений).

Реальный render/реактивность KV-редактора — `tests/js/round1024_aliases_render_test.js`.
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import manage
from config import settings as settings_mod
from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS_F10"
ADMIN_ID = 5885953495
CHAT_ID = -100500
ALIASES_KEY = "limits.summary_aliases"
GLOBAL_ALIASES = {"138811255": "Леха", "350803143": "Костик"}

_INDEX = (Path(".") / "web" / "index.html").read_text(encoding="utf-8")
_APP_JS = (Path(".") / "web" / "app.js").read_text(encoding="utf-8")


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


def _hdr(user_id: int = ADMIN_ID, chat_id: int | None = None) -> dict:
    headers = {"X-Telegram-Init-Data": make_init_data(user_id)}
    if chat_id is not None:
        headers["X-Chat-Id"] = str(chat_id)
    return headers


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self.queries = []
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return None

    async def fetch(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


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

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


_ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False},
    {"role_name": "user", "permissions": {}, "is_custom": False},
]
_ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "info.md"),
                              ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(
        settings_rows=[
            {"key": ALIASES_KEY, "value": dict(GLOBAL_ALIASES),
             "category": "limits", "updated_at": None},
        ],
        role_rows=_ROLE_ROWS, admin_rows=_ADMIN_ROWS)
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


def _aliases_item(body) -> dict:
    return next(it for it in body["items"] if it["key"] == ALIASES_KEY)


class TestConfigApiContract:
    def test_global_item_is_keyvalue_object(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        item = _aliases_item(resp.json())
        assert item["widget"] == "keyvalue"
        assert isinstance(item["value"], dict)
        assert item["value"] == GLOBAL_ALIASES
        assert item["chat_source"] == ""
        assert item["global_value"] is None

    def test_double_encoded_passthrough_is_object(self, client):
        """Backend `_ensure_keyvalue_object` — вход редактора всегда объект."""
        from web.api.routes import _ensure_keyvalue_object
        raw = json.dumps(GLOBAL_ALIASES)
        assert _ensure_keyvalue_object(raw) == GLOBAL_ALIASES
        assert _ensure_keyvalue_object(json.dumps(raw)) == GLOBAL_ALIASES

    def test_chat_override_is_effective_with_source(self, client, monkeypatch):
        override = {"1": "Иван"}

        async def _fake_chat_params(chat_id, pg=None):
            return {"overrides": {ALIASES_KEY: dict(override)}, "meta": {}}

        monkeypatch.setattr("services.chat_params.get_all_chat_params",
                            _fake_chat_params)
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID, CHAT_ID))
        assert resp.status_code == 200
        item = _aliases_item(resp.json())
        assert item["widget"] == "keyvalue"
        assert item["value"] == override          # эффективное значение
        assert item["chat_source"] == "chat"      # индикатор источника
        assert isinstance(item["global_value"], dict)
        assert item["global_value"] == GLOBAL_ALIASES

    def test_chat_without_override_is_global(self, client, monkeypatch):
        async def _fake_chat_params(chat_id, pg=None):
            return {"overrides": {}, "meta": {}}

        monkeypatch.setattr("services.chat_params.get_all_chat_params",
                            _fake_chat_params)
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID, CHAT_ID))
        assert resp.status_code == 200
        item = _aliases_item(resp.json())
        assert item["value"] == GLOBAL_ALIASES
        assert item["chat_source"] == ""

    def test_ui_flag_delivered_default_on(self, client):
        resp = client.get("/api/me", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        flags = resp.json()["ui_flags"]
        assert flags["ALIASES_KEYSVALUE_RENDER_ENABLED"] is True

    def test_ui_flag_off_by_env(self, client, monkeypatch):
        monkeypatch.setattr(type(settings_mod.settings),
                            "ALIASES_KEYSVALUE_RENDER_ENABLED", False)
        resp = client.get("/api/me", headers=_hdr(ADMIN_ID))
        assert resp.json()["ui_flags"]["ALIASES_KEYSVALUE_RENDER_ENABLED"] is False


class TestDiagReadOnly:
    class _DiagConn:
        def __init__(self, overrides):
            self.queries = []
            self._overrides = overrides

        async def fetchrow(self, sql, *args):
            self.queries.append(sql)
            if "bot_settings" in sql:
                return {"key": ALIASES_KEY, "value": json.dumps(GLOBAL_ALIASES)}
            if "chat_profiles" in sql:
                return {"chat_id": args[0],
                        "chat_params": {"overrides": dict(self._overrides),
                                        "meta": {}}}
            return None

    def _run(self, chat_ids, *, overrides):
        import asyncio
        conn = self._DiagConn(overrides)
        pg = _FakePg(conn)
        report = asyncio.run(manage._collect_aliases_diag(pg, chat_ids=chat_ids))
        return conn, report

    def test_shape_and_no_values_leak(self):
        conn, report = self._run([CHAT_ID],
                                 overrides={ALIASES_KEY: {"1": "Иван"}})
        assert report["key"] == ALIASES_KEY
        assert report["widget"] == "keyvalue"
        assert report["global_present"] is True
        # R17: только форма/число ключей — самих имён нет в выводе.
        assert report["global"]["effective_keys"] == 2
        assert report["global"]["encoded_as_string"] is True
        assert report["global"]["double_encoded"] is True
        assert "Леха" not in json.dumps(report, ensure_ascii=False)
        chat = report["chats"][0]
        assert chat["override_present"] is True
        assert chat["override"]["effective_keys"] == 1
        assert chat["api_value_keys"] == 1
        assert chat["api_global_value_keys"] == 2
        assert chat["api_chat_source"] == "chat"
        assert "Иван" not in json.dumps(report, ensure_ascii=False)

    def test_no_override_global_value_matches_global(self):
        """Review iter1 (Medium): chat БЕЗ override — `global_value` в diag
        обязан быть объектом глобального слоя (паритет с `GET /api/config`,
        routes.py:442/450/459-462), а не None."""
        conn, report = self._run([CHAT_ID], overrides={})
        chat = report["chats"][0]
        assert chat["override_present"] is False
        assert chat["override"] is None
        assert chat["api_chat_source"] == ""
        assert report["global"]["effective_keys"] == 2
        assert chat["api_global_value_keys"] == report["global"]["effective_keys"]
        assert chat["api_value_keys"] == report["global"]["effective_keys"]
        # Без chat_id глобальный слой остаётся None (не chat-скоуп).
        _, no_chat = self._run([], overrides={})
        assert no_chat["chats"] == []

    def test_scalar_json_not_double_encoded(self):
        """Review iter1 (Low): скалярный JSON-строкой — не «двойное кодирование»."""
        shape = manage._aliases_shape(json.dumps(123))
        assert shape["encoded_as_string"] is True
        assert shape["double_encoded"] is False
        assert shape["effective_keys"] == 0

    def test_only_select_statements(self):
        conn, _ = self._run([CHAT_ID],
                            overrides={ALIASES_KEY: {"1": "Иван"}})
        assert conn.queries, "диагностика должна выполнить SELECT-запросы"
        for sql in conn.queries:
            head = sql.strip().upper()
            assert head.startswith("SELECT"), f"не-read-only SQL: {sql!r}"
            for forbidden in ("UPDATE", "DELETE", "INSERT", "ALTER", "DROP"):
                assert forbidden not in head, f"мутация в read-only: {sql!r}"


class TestStaticWiring:
    """Статические маркеры фикса (динамика — в JS render-тесте)."""

    def test_key_on_kv_editor(self):
        assert ":key=\"item.key + ':' + configVersion\"" in _INDEX

    def test_root_iconglyph_in_kv_template(self):
        start = _INDEX.index('id="kv-editor-tpl"')
        end = _INDEX.index("</script>", start)
        kv_tpl = _INDEX[start:end]
        assert "root.iconGlyph('delete')" in kv_tpl
        assert "{{ iconGlyph(" not in kv_tpl

    def test_deep_immediate_watch_and_config_version(self):
        assert "deep: true" in _APP_JS
        assert "immediate: true" in _APP_JS
        assert "configVersion++" in _APP_JS
        assert "ALIASES_KEYSVALUE_RENDER_ENABLED" in _APP_JS
