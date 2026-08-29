"""Epic 85 (T-617/T-638, 84.5) — тесты REST-эндпоинтов /api/*.

TestClient + ConfigCache-стаб (роли/админы в памяти; PG-операции — мок пула
как в test_config_cache). Покрытие: health/me/config (маскировка секретов
84.12.4), POST /api/config (per-key права, типизация 422, hot-reload),
admins/roles (guard 409, валидация 422), roles/tree (checked-отметки),
info GET/POST (edit_info, лимит 32768, 422 пустой).
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
from services.permissions import Permissions
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
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


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self.queries = []
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
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
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    # F5: POST /api/info пишет через InfoService.save_text → файл-зеркало
    # должен указывать на tmp (не перезаписывать реальный info_text.md)
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(
            INFO_TEXT_FILE=str(tmp_path / "info_text.md"),
            ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(
        settings_rows=[
            {"key": "limits.search_max_symbols", "value": 8000,
             "category": "limits", "updated_at": "2026-08-30T01:00:00+00:00"},
            {"key": "keys.groq_api_key", "value": "gsk_secret_key_1234",
             "category": "keys", "updated_at": None},
            {"key": "models.llm_timeout", "value": 30.0, "category": "models",
             "updated_at": None},
            {"key": "content.info_how_it_works",
             "value": {"html": "<h1>Как это работает</h1>",
                       "updated_at": "2026-08-30T00:00:00+00:00",
                       "updated_by": ADMIN_ID},
             "category": "content"},
        ],
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "moderator",
             "permissions": {"sections": ["limits"],
                             "actions": ["control.restart", "control.stop",
                                         "control.start"]},
             "is_custom": False},
            {"role_name": "user", "permissions": {}, "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
            {"telegram_id": MODERATOR_ID, "role_name": "moderator",
             "added_by": ADMIN_ID,
             "created_at": "2026-08-30T00:00:01+00:00"},
        ],
    )
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


class TestHealthAndMe:
    def test_health_no_auth(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_me_admin(self, client):
        resp = client.get("/api/me", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["telegram_id"] == ADMIN_ID
        assert body["role_name"] == "admin"
        assert body["permissions"] == {"wildcard": True}

    def test_me_unknown_id_defaults_user_role(self, client):
        resp = client.get("/api/me", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        assert resp.json()["role_name"] == "user"

    def test_me_without_init_data_401(self, client):
        assert client.get("/api/me").status_code == 401


class TestConfigMasking:
    """84.12.4: значения секретов — только configured/last4 (без права)."""

    def test_admin_sees_full_secret(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        assert items["keys.groq_api_key"]["value"] == "gsk_secret_key_1234"

    def test_moderator_sees_masked_secret(self, client):
        resp = client.get("/api/config", headers=_hdr(MODERATOR_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        key_item = items["keys.groq_api_key"]
        assert key_item["secret"] is True
        assert key_item["value"]["configured"] is True
        assert key_item["value"]["last4"] == "1234"
        assert "secret" not in json.dumps(key_item["value"])

    def test_user_role_sees_masked(self, client):
        resp = client.get("/api/config", headers=_hdr(USER_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        assert items["keys.groq_api_key"]["value"]["configured"] is True

    def test_non_secret_visible_to_all(self, client):
        resp = client.get("/api/config", headers=_hdr(USER_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        assert items["limits.search_max_symbols"]["value"] == 8000


class TestConfigPost:
    def test_admin_can_update_and_hot_reload(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.search_max_symbols",
                                            "value": 12345}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json() == {"updated": ["limits.search_max_symbols"]}
        # hot-reload: кэш обновился мгновенно
        assert client.cache.get("limits.search_max_symbols") == 12345
        resp2 = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp2.json()["items"]}
        assert items["limits.search_max_symbols"]["value"] == 12345

    def test_moderator_updates_limits_allowed(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.checkup_max_symbols",
                                            "value": 2000}]},
                           headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 200

    def test_moderator_updates_models_denied_403(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": "models.llm_timeout",
                                            "value": 60}]},
                           headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_user_role_denied_403(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.search_max_symbols",
                                            "value": 1}]},
                           headers=_hdr(USER_ID))
        assert resp.status_code == 403

    def test_unknown_key_422(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.no_such_key",
                                            "value": 1}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_wrong_type_422(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.search_max_symbols",
                                            "value": "не число"}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_empty_items_422(self, client):
        resp = client.post("/api/config", json={"items": []},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_string_number_coerced(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.search_max_symbols",
                                            "value": "777"}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert client.cache.get("limits.search_max_symbols") == 777

    def test_param_right_allows_edit(self, client):
        """F2: роль с params:["limits.search_max_symbols"] (без секции
        limits) получает 200 на конкретный параметр."""
        client.cache._roles["param_editor"] = {
            "permissions": {"params": ["limits.search_max_symbols"]},
            "is_custom": True}
        client.cache._permissions["param_editor"] = Permissions.from_dict(
            {"params": ["limits.search_max_symbols"]})
        client.cache._admins[555] = "param_editor"
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.search_max_symbols",
                                            "value": 31337}]},
                           headers=_hdr(555))
        assert resp.status_code == 200
        assert client.cache.get("limits.search_max_symbols") == 31337

    def test_param_right_other_param_denied_403(self, client):
        """F2 (негатив): param-право на ДРУГОЙ ключ → 403."""
        client.cache._roles["param_editor"] = {
            "permissions": {"params": ["limits.search_max_symbols"]},
            "is_custom": True}
        client.cache._permissions["param_editor"] = Permissions.from_dict(
            {"params": ["limits.search_max_symbols"]})
        client.cache._admins[555] = "param_editor"
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.checkup_max_symbols",
                                            "value": 1}]},
                           headers=_hdr(555))
        assert resp.status_code == 403

    def test_config_post_pg_down_503(self, client):
        """F18: без PG значение не персистентно → честный 503."""
        client.cache._pg_available = False
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.search_max_symbols",
                                            "value": 1}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 503


class TestAdmins:
    def test_get_admins_access_only(self, client):
        assert client.get("/api/admins", headers=_hdr(USER_ID)).status_code == 403
        resp = client.get("/api/admins", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        admins = {a["telegram_id"]: a["role_name"]
                  for a in resp.json()["admins"]}
        assert admins == {ADMIN_ID: "admin", MODERATOR_ID: "moderator"}

    def test_assign_role_unknown_role_422(self, client):
        resp = client.post("/api/admins",
                           json={"telegram_id": 12345, "role_name": "ghost"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_assign_role_ok(self, client):
        resp = client.post("/api/admins",
                           json={"telegram_id": 12345, "role_name": "user"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["role_name"] == "user"

    def test_remove_last_wildcard_admin_409(self, client):
        resp = client.post("/api/admins/remove",
                           json={"telegram_id": ADMIN_ID},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 409

    def test_remove_unknown_admin_404(self, client):
        resp = client.post("/api/admins/remove",
                           json={"telegram_id": 123456},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 404

    def test_rbac_ops_pg_down_503(self, client, monkeypatch):
        client.cache._pg_available = False
        assert client.post(
            "/api/admins",
            json={"telegram_id": 1, "role_name": "user"},
            headers=_hdr(ADMIN_ID)).status_code == 503
        assert client.post(
            "/api/admins/remove",
            json={"telegram_id": MODERATOR_ID},
            headers=_hdr(ADMIN_ID)).status_code == 503
        assert client.post(
            "/api/roles",
            json={"role_name": "x", "permissions": {}},
            headers=_hdr(ADMIN_ID)).status_code == 503

    def test_get_admins_full_cards(self, client):
        """F7: added_by/created_at довыдаются (при деградации — null)."""
        resp = client.get("/api/admins", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        admins = {a["telegram_id"]: a for a in resp.json()["admins"]}
        assert admins[ADMIN_ID]["added_by"] is None
        assert admins[ADMIN_ID]["created_at"] == "2026-08-30T00:00:00+00:00"
        assert admins[MODERATOR_ID]["added_by"] == ADMIN_ID

    def test_remove_last_admin_409(self, client):
        """F8: нельзя удалить ПОСЛЕДНЕГО админа (не только wildcard-роль)."""
        client.cache._admins = {ADMIN_ID: "admin"}
        client.cache._admins_full = {ADMIN_ID: {
            "telegram_id": ADMIN_ID, "role_name": "admin",
            "added_by": None, "created_at": None}}
        resp = client.post("/api/admins/remove",
                           json={"telegram_id": ADMIN_ID},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 409

    def test_config_items_include_updated_at(self, client):
        """F7: updated_at из PG в GET /api/config."""
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        assert items["limits.search_max_symbols"]["updated_at"] \
            == "2026-08-30T01:00:00+00:00"
        assert items["keys.groq_api_key"]["updated_at"] is None


class TestRoles:
    def test_get_roles(self, client):
        resp = client.get("/api/roles", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        roles = {r["role_name"]: r for r in resp.json()["roles"]}
        assert set(roles) == {"admin", "moderator", "user"}
        assert roles["admin"]["permissions"] == {"wildcard": True}

    def test_create_custom_role(self, client):
        resp = client.post(
            "/api/roles",
            json={"role_name": "viewer",
                  "permissions": {"sections": ["limits"]}},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["is_custom"] is True

    def test_unknown_section_422(self, client):
        resp = client.post(
            "/api/roles",
            json={"role_name": "x", "permissions": {"sections": ["nope"]}},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_unknown_action_422(self, client):
        resp = client.post(
            "/api/roles",
            json={"role_name": "x",
                  "permissions": {"actions": ["control.destroy"]}},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_strip_wildcard_from_last_admin_role_409(self, client):
        resp = client.post(
            "/api/roles",
            json={"role_name": "admin",
                  "permissions": {"sections": ["limits"]}},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 409

    def test_update_keeps_is_custom_flag(self, client):
        # moderator — системная роль: is_custom остаётся false
        resp = client.post(
            "/api/roles",
            json={"role_name": "moderator",
                  "permissions": {"sections": ["limits", "models"]},
                  "is_custom": True},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["is_custom"] is False

    def test_roles_tree(self, client):
        resp = client.get("/api/roles/tree", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        section_ids = {s["id"] for s in body["sections"]}
        assert "limits" in section_ids and "keys" in section_ids \
            and "access" in section_ids
        action_ids = {a["id"] for a in body["actions"]}
        assert action_ids == {"edit_info", "control.restart", "control.stop",
                              "control.start", "debug.config"}
        limits = next(s for s in body["sections"] if s["id"] == "limits")
        assert any(p["key"] == "limits.search_max_symbols"
                   for p in limits["params"])

    def test_roles_tree_checked_for_role(self, client):
        resp = client.get("/api/roles/tree",
                          params={"role_name": "moderator"},
                          headers=_hdr(ADMIN_ID))
        body = resp.json()
        limits = next(s for s in body["sections"] if s["id"] == "limits")
        assert limits["checked"] is True
        keys = next(s for s in body["sections"] if s["id"] == "keys")
        assert keys["checked"] is False
        actions = {a["id"]: a for a in body["actions"]}
        assert actions["control.restart"]["checked"] is True
        assert actions["edit_info"]["checked"] is False

    def test_roles_tree_unknown_role_404(self, client):
        resp = client.get("/api/roles/tree",
                          params={"role_name": "ghost"},
                          headers=_hdr(ADMIN_ID))
        assert resp.status_code == 404


class TestInfo:
    def test_get_info_public_any_role(self, client):
        for uid in (ADMIN_ID, MODERATOR_ID, USER_ID):
            resp = client.get("/api/info", headers=_hdr(uid))
            assert resp.status_code == 200
            assert resp.json()["html"] == "<h1>Как это работает</h1>"
            assert resp.json()["updated_by"] == ADMIN_ID

    def test_get_info_requires_tma_auth(self, client):
        assert client.get("/api/info").status_code == 401

    def test_post_info_admin_ok(self, client):
        resp = client.post("/api/info", json={"html": "<h1>Новое</h1>"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["updated_by"] == ADMIN_ID
        value = client.cache.get("content.info_how_it_works")
        assert value["html"] == "<h1>Новое</h1>"

    def test_post_info_non_admin_403(self, client):
        resp = client.post("/api/info", json={"html": "<h1>x</h1>"},
                           headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_post_info_empty_422(self, client):
        resp = client.post("/api/info", json={"html": "   "},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_post_info_too_large_422(self, client):
        resp = client.post("/api/info", json={"html": "a" * 32769},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_get_info_non_dict_value(self, client):
        """Значение в кэше — строка (не сид-объект) → html=строке, 200."""
        client.cache._settings["content.info_how_it_works"] = "<b>plain</b>"
        resp = client.get("/api/info", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        assert resp.json()["html"] == "<b>plain</b>"
        assert resp.json()["updated_at"] is None

    def test_post_info_save_failure_500(self, client, monkeypatch):
        async def _boom(key, value, category):
            raise RuntimeError("db gone")

        monkeypatch.setattr(client.cache, "set", _boom)
        resp = client.post("/api/info", json={"html": "<h1>x</h1>"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 500

    def test_post_info_pg_down_503(self, client):
        """F18: PG down → 503 (значение не было бы персистентным)."""
        client.cache._pg_available = False
        resp = client.post("/api/info", json={"html": "<h1>x</h1>"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 503


class TestControlRouteEdge:
    def test_control_unavailable_503(self, client):
        client.app.state.control = None
        resp = client.post("/api/control/restart", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 503


class TestDebugConfigEndpoint:
    """84.18.5 / DoD п.18: 401/403/200-матрица; дамп читает ТОЛЬКО RAM:
    прямая правка «БД» дамп не меняет, cache.set() — меняет; маскировка."""

    def test_401_without_init_data(self, client):
        assert client.get("/api/debug/config").status_code == 401

    def test_403_for_non_admin(self, client):
        resp = client.get("/api/debug/config", headers=_hdr(USER_ID))
        assert resp.status_code == 403
        # moderator тоже не имеет debug.config (только control.* + limits)
        resp = client.get("/api/debug/config", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_200_admin_wildcard(self, client):
        resp = client.get("/api/debug/config", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["pid"] > 0
        assert body["meta"]["app_version"]
        assert "keys_total" in body["meta"]
        items = {i["key"]: i for i in body["items"]}
        assert items["limits.search_max_symbols"]["source"] == "memory-cache"

    def test_200_role_with_debug_action_right(self, client):
        client.cache._roles["debugger"] = {
            "permissions": {"actions": ["debug.config"]}, "is_custom": True}
        client.cache._permissions["debugger"] = Permissions.from_dict(
            {"actions": ["debug.config"]})
        client.cache._admins[777] = "debugger"
        resp = client.get("/api/debug/config", headers=_hdr(777))
        assert resp.status_code == 200

    def test_secrets_masked_even_for_admin(self, client):
        resp = client.get("/api/debug/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        key_item = items["keys.groq_api_key"]
        assert key_item["value"] == {"configured": True, "last4": "1234"}
        assert "gsk_secret_key" not in str(resp.json())

    def test_dump_not_changed_by_direct_db_write(self, client):
        """Дамп — RAM: правка строк «БД» (fake rows) НЕ меняет дамп."""
        before = client.cache.get("limits.search_max_symbols")
        # имитация прямой записи в PG в обход кэша
        client.cache._pg._pool._conn._settings_rows = [
            {"key": "limits.search_max_symbols", "value": 999999,
             "category": "limits", "updated_at": None}]
        resp = client.get("/api/debug/config",
                          params={"key": "limits.search_max_symbols"},
                          headers=_hdr(ADMIN_ID))
        assert resp.json()["item"]["value"] == before

    def test_dump_changes_after_cache_set(self, client):
        """DoD п.18: cache.set() → RAM обновлён → дамп меняется."""
        import asyncio

        async def _set():
            await client.cache.set("limits.search_max_symbols", 424242,
                                   "limits")

        asyncio.run(_set())
        resp = client.get("/api/debug/config",
                          params={"key": "limits.search_max_symbols"},
                          headers=_hdr(ADMIN_ID))
        assert resp.json()["item"]["value"] == 424242
        assert resp.json()["item"]["source"] == "memory-cache"

    def test_key_filter_and_settings_fallback(self, client):
        resp = client.get("/api/debug/config",
                          params={"key": "limits.factcheck_max_symbols"},
                          headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert "item" in body and "items" not in body
        # ключа нет в RAM фикстуры → settings-fallback
        assert body["item"]["source"] == "settings-fallback"


class TestQuotedJsonbRoles:
    """ПРОД-ИНЦИДЕНТ (B): bot_roles.permissions (jsonb) приходит СТРОКОЙ
    '{"wildcard": true}' — после фикса админ получает wildcard, /api/me
    отдаёт permissions ОБЪЕКТОМ, /api/debug/config → 200 (не 403)."""

    @pytest.fixture
    def quoted_client(self, monkeypatch, tmp_path):
        monkeypatch.setattr(deps_mod, "settings",
                            types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
        monkeypatch.setattr(
            "services.info_service.settings",
            types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "i.md"),
                                  ADMIN_USER_ID=ADMIN_ID))
        conn = _FakeConn(
            settings_rows=[
                {"key": "models.llm_base_url",
                 "value": '"https://apinet.cloud/v1"', "category": "models",
                 "updated_at": None},
            ],
            role_rows=[
                # permissions — СТРОКА JSON-текста, как из jsonb без кодека
                {"role_name": "admin",
                 "permissions": '{"wildcard": true}', "is_custom": False},
                {"role_name": "user", "permissions": '{}',
                 "is_custom": False},
            ],
            admin_rows=[
                {"telegram_id": ADMIN_ID, "role_name": "admin",
                 "added_by": None, "created_at": None},
            ],
        )
        cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
        app = create_app(cache)
        with TestClient(app) as test_client:
            test_client.cache = cache
            yield test_client

    def test_me_returns_permissions_object(self, quoted_client):
        resp = quoted_client.get("/api/me", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["permissions"], dict), body["permissions"]
        assert body["permissions"] == {"wildcard": True}
        assert body["role_name"] == "admin"

    def test_debug_config_200_for_admin_with_string_permissions(
            self, quoted_client):
        """B: раньше wildcard терялся → 403 на /api/debug/config."""
        resp = quoted_client.get("/api/debug/config", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["meta"]["pid"] > 0

    def test_config_values_unquoted_for_admin(self, quoted_client):
        resp = quoted_client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        assert items["models.llm_base_url"]["value"] == "https://apinet.cloud/v1"

    def test_roles_endpoint_permissions_object(self, quoted_client):
        resp = quoted_client.get("/api/roles", headers=_hdr(ADMIN_ID))
        roles = {r["role_name"]: r for r in resp.json()["roles"]}
        assert roles["admin"]["permissions"] == {"wildcard": True}
        assert isinstance(roles["admin"]["permissions"], dict)


class TestStatic:
    def test_root_redirects_to_web(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/web/"

    def test_web_index_served(self, client):
        resp = client.get("/web/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        text = resp.text
        # фронтенд фазы 4 (T-620): Vue-приложение + CSS-канон 84.7
        assert '<div id="app"' in text
        assert "vue.global.prod.js" in text
        assert "cdn.tailwindcss.com" in text
        assert "dompurify" in text
        assert "chart.js" in text
        assert "linear-gradient(-45deg" in text          # анимированный фон
        assert "animation: gradient 15s ease infinite" in text
        assert "backdrop-filter: blur(20px) saturate(140%)" in text
        assert "Telegram.WebApp" in text

    def test_web_app_js_served(self, client):
        resp = client.get("/web/app.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]
        text = resp.text
        # все fetch-URL'ы фронта существуют в routes (сверка T-644-чеклист)
        for url in ("/api/me", "/api/config", "/api/admins",
                    "/api/admins/remove", "/api/roles", "/api/roles/tree",
                    "/api/status", "/api/status/logs", "/api/info",
                    "/api/control/"):
            assert url in text, url
        assert "X-Telegram-Init-Data" in text            # 84.6: header на каждый fetch
        assert "DOMPurify" in text                        # 84.13.5
        assert "indeterminate" in text                    # дерево чекбоксов 84.14.4

    def test_web_index_replaces_stub(self, client):
        """T-618-заглушка заменена полным фронтендом фазы 4."""
        resp = client.get("/web/")
        assert "Админка скоро будет" not in resp.text
