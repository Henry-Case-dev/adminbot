"""F11 round 10.24 (byok-image-key-round1024, ADR-1024-12) — безопасный путь
глобального ключа изображений.

Покрытие:
  * BYOK-whitelist НЕ расширен (`keys.image_api_key` — не per-chat), но ключ
    входит в allowlist ГЛОБАЛЬНЫХ секретов;
  * `PUT /api/config/keys/own` (global, без X-Chat-Id) → 200 + маска;
    значение в глобальном слое; raw никогда не в ответе; аудит;
  * права: не-global-admin → 403; не-global ключ → 422;
  * `GET /api/config` отдаёт только `{configured,last4}` (R17);
  * `DELETE` global-секрета → сброс глобального слоя + аудит;
  * kill-switch `BYOK_IMAGE_KEY_ENABLED=OFF` → global-ветка отключена.
"""
import hashlib
import hmac
import json
import logging
import time
import types
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import settings as settings_mod
from services import chat_keys
from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS_F11"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
USER_ID = 999999999
KEYS_EDITOR_ID = 424242425
ADMIN_NO_WILDCARD_ID = 424242426
CUSTOM_GA_ID = 424242427

IMAGE_KEY = "keys.image_api_key"
IMAGE_SECRET = "img-secret-value-9999"
CHAT_ID = -100500

_INDEX = (Path(".") / "web" / "index.html").read_text(encoding="utf-8")


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

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx

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

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


@pytest.fixture
def client(monkeypatch, tmp_path):
    cache, app = _make_app_client(monkeypatch, tmp_path)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


_ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False},
    {"role_name": "moderator",
     "permissions": {"sections": ["limits"]}, "is_custom": False},
    {"role_name": "user", "permissions": {}, "is_custom": False},
]
_ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
     "added_by": ADMIN_ID, "created_at": None},
]


def _make_app_client(monkeypatch, tmp_path,
                     role_rows=None, admin_rows=None):
    """Сборка TestClient с фейковым PG и заданными ролями/админами."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "info.md"),
                              ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(
        settings_rows=[
            {"key": IMAGE_KEY, "value": IMAGE_SECRET,
             "category": "keys", "updated_at": None},
            {"key": "keys.llm_api_key", "value": "sk_deepseek_123456",
             "category": "keys", "updated_at": None},
        ],
        role_rows=role_rows if role_rows is not None else _ROLE_ROWS,
        admin_rows=admin_rows if admin_rows is not None else _ADMIN_ROWS,
    )
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    return cache, create_app(cache)


@pytest.fixture
def keys_editor_client(monkeypatch, tmp_path):
    """Роль с `sections:['keys']` (без wildcard): поле image-ключа должно быть
    недоступно (паритет UI↔бэкенд, Finding H)."""
    roles = _ROLE_ROWS + [{"role_name": "keys_editor",
                           "permissions": {"sections": ["keys"]},
                           "is_custom": False}]
    admins = _ADMIN_ROWS + [{"telegram_id": KEYS_EDITOR_ID,
                             "role_name": "keys_editor",
                             "added_by": ADMIN_ID, "created_at": None}]
    cache, app = _make_app_client(monkeypatch, tmp_path, roles, admins)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


@pytest.fixture
def admin_no_wildcard_client(monkeypatch, tmp_path):
    """Роль `admin` БЕЗ wildcard (legacy-role_type → global_admin): раньше
    фронт бросал TypeError, бэкенд считает её глобальным админом."""
    roles = [{"role_name": "admin", "permissions": {}, "is_custom": False},
             {"role_name": "user", "permissions": {}, "is_custom": False}]
    admins = [{"telegram_id": ADMIN_NO_WILDCARD_ID, "role_name": "admin",
               "added_by": None, "created_at": None}]
    cache, app = _make_app_client(monkeypatch, tmp_path, roles, admins)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


@pytest.fixture
def custom_global_admin_client(monkeypatch, tmp_path):
    """Custom-роль с `role_type=global_admin` без wildcard: backend разрешает
    (200), фронт по эффективному флагу тоже должен разрешать (M1)."""
    roles = _ROLE_ROWS + [{"role_name": "ga_custom",
                           "permissions": {"sections": ["keys"]},
                           "is_custom": True, "role_type": "global_admin"}]
    admins = _ADMIN_ROWS + [{"telegram_id": CUSTOM_GA_ID,
                             "role_name": "ga_custom",
                             "added_by": ADMIN_ID, "created_at": None}]
    cache, app = _make_app_client(monkeypatch, tmp_path, roles, admins)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


def _audit_rows(client) -> list:
    conn = client.cache.pg.pool._conn
    return [args for sql, args in conn.queries
            if "INSERT INTO chat_lore_history" in sql]


# ═══ Контракт allowlist ════════════════════════════════════════════════════

class TestAllowlists:
    def test_per_chat_whitelist_not_expanded(self):
        """ADR-1024-12 D2: per-chat BYOK не расширяем — image-ключ НЕ в
        BYOK-whitelist (backend не резолвит per-chat image-ключ)."""
        assert chat_keys.is_whitelisted(IMAGE_KEY) is False
        assert chat_keys.is_whitelisted("keys.llm_api_key") is True

    def test_global_secret_allowlist(self):
        assert chat_keys.is_global_secret(IMAGE_KEY) is True
        assert chat_keys.is_global_secret("keys.llm_api_key") is False
        assert IMAGE_KEY in chat_keys.global_secret_keys()

    def test_flag_off_disables_global_secret(self, monkeypatch):
        """Kill-switch: OFF → global-ветка отключена (allowlist буквально пуст)."""
        # Тип берём у живого синглтона: иные тесты делают
        # `importlib.reload(config.settings)` и класс-идентичность сдвигается.
        monkeypatch.setattr(type(settings_mod.settings),
                            "BYOK_IMAGE_KEY_ENABLED", False)
        assert chat_keys.global_secret_keys() == frozenset()
        assert chat_keys.is_global_secret(IMAGE_KEY) is False

    def test_me_exposes_ui_flag(self, client):
        """ADR-1024-13: kill-switch доставляется во фронт через /api/me."""
        resp = client.get("/api/me", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["ui_flags"]["BYOK_IMAGE_KEY_ENABLED"] is True
        # M1: эффективный глобальный админ — единый источник прав UI↔бэкенд.
        assert body["is_global_admin"] is True


# ═══ PUT global ════════════════════════════════════════════════════════════

class TestGlobalPut:
    def test_put_global_scope_saves_to_global_layer_and_masks(self, client):
        resp = client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "brand-new-image-key",
                  "scope": "global"},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"key_name": IMAGE_KEY, "configured": True,
                        "last4": "-key"}
        # R17: raw-значения нет в ответе.
        assert "brand-new-image-key" not in resp.text
        # значение — в глобальном слое (то же хранилище, что читает
        # image_generation._resolve_str).
        assert client.cache.get(IMAGE_KEY) == "brand-new-image-key"
        # аудит записан, значение в истории — маска.
        audit = _audit_rows(client)
        assert audit and audit[-1][1] == chat_keys._HISTORY_FIELD
        assert audit[-1][3] == "***" and "brand-new" not in str(audit[-1])

    def test_put_auto_without_chat_id_uses_global(self, client):
        """scope отсутствует (auto) + нет X-Chat-Id + global-allowlist."""
        resp = client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "auto-global-key"},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert client.cache.get(IMAGE_KEY) == "auto-global-key"

    def test_put_global_forbidden_for_non_admin(self, client):
        for uid in (USER_ID, MODERATOR_ID):
            resp = client.put(
                "/api/config/keys/own",
                json={"key_name": IMAGE_KEY, "value": "x", "scope": "global"},
                headers=_hdr(uid))
            assert resp.status_code == 403, uid
        # ключ не изменился.
        assert client.cache.get(IMAGE_KEY) == IMAGE_SECRET

    def test_put_global_rejects_non_global_key(self, client):
        resp = client.put(
            "/api/config/keys/own",
            json={"key_name": "keys.llm_api_key", "value": "x",
                  "scope": "global"},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_put_unknown_scope_422(self, client):
        resp = client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "x", "scope": "wat"},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_put_chat_scope_without_chat_id_422(self, client):
        resp = client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "x", "scope": "chat"},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_per_chat_image_key_rejected(self, client):
        """Per-chat image-ключ backend'ом не поддерживается → 422."""
        resp = client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "x"},
            headers=_hdr(ADMIN_ID, chat_id=CHAT_ID))
        assert resp.status_code == 422

    def test_put_flag_off_disables_branch(self, client, monkeypatch):
        monkeypatch.setattr(type(settings_mod.settings),
                            "BYOK_IMAGE_KEY_ENABLED", False)
        resp = client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "x", "scope": "global"},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422
        assert client.cache.get(IMAGE_KEY) == IMAGE_SECRET


# ═══ GET / маскировка ══════════════════════════════════════════════════════

class TestMaskingReads:
    def test_global_get_keys_own_returns_mask_no_raw(self, client):
        resp = client.get("/api/config/keys/own", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        row = [k for k in keys if k.get("key_name") == IMAGE_KEY]
        assert len(row) == 1
        assert row[0]["configured"] is True
        assert row[0]["last4"] == "9999"
        assert IMAGE_SECRET not in resp.text

    def test_global_get_keys_own_forbidden_for_non_admin(self, client):
        resp = client.get("/api/config/keys/own", headers=_hdr(USER_ID))
        assert resp.status_code == 403

    def test_get_config_masks_image_key(self, client):
        """UPD2 п.9: общий GET /api/config отдаёт только {configured,last4}."""
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        items = {i["key"]: i for i in resp.json()["items"]}
        assert IMAGE_KEY in items
        assert items[IMAGE_KEY]["value"] == {"configured": True,
                                             "last4": "9999"}
        assert IMAGE_SECRET not in resp.text

    def test_no_raw_after_save_anywhere(self, client):
        """После сохранения raw не появляется ни в GET /api/config,
        ни в GET /api/config/keys/own."""
        client.put("/api/config/keys/own",
                   json={"key_name": IMAGE_KEY, "value": "leaky-raw-abcdef",
                         "scope": "global"},
                   headers=_hdr(ADMIN_ID))
        assert "leaky-raw-abcdef" not in client.get(
            "/api/config", headers=_hdr(ADMIN_ID)).text
        assert "leaky-raw-abcdef" not in client.get(
            "/api/config/keys/own", headers=_hdr(ADMIN_ID)).text


# ═══ DELETE global ═════════════════════════════════════════════════════════

class TestGlobalDelete:
    def test_delete_global_resets_layer_and_audits(self, client):
        resp = client.delete(f"/api/config/keys/own/{IMAGE_KEY}",
                             headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json() == {"removed": True}
        # глобальный слой сброшен (configured:false).
        assert not client.cache.get(IMAGE_KEY)
        audit = _audit_rows(client)
        assert audit and audit[-1][1] == chat_keys._HISTORY_FIELD
        assert audit[-1][4] == ""          # new_value — пусто

    def test_delete_global_forbidden_non_admin(self, client):
        resp = client.delete(f"/api/config/keys/own/{IMAGE_KEY}",
                             headers=_hdr(USER_ID))
        assert resp.status_code == 403
        assert client.cache.get(IMAGE_KEY) == IMAGE_SECRET

    def test_delete_non_global_without_chat_422(self, client):
        resp = client.delete("/api/config/keys/own/keys.llm_api_key",
                             headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422


# ═══ Паритет прав UI↔бэкенд (review iter1, Finding H) ══════════════════════

class TestRbacParity:
    def test_keys_section_role_cannot_save_global_secret(
            self, keys_editor_client):
        """Роль с `sections:['keys']` без wildcard НЕ глобальный админ →
        safe-эндпоинт 403 (UI зеркалит: поле disabled, см. JS-тест)."""
        resp = keys_editor_client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "x", "scope": "global"},
            headers=_hdr(KEYS_EDITOR_ID))
        assert resp.status_code == 403
        assert keys_editor_client.cache.get(IMAGE_KEY) == IMAGE_SECRET

    def test_keys_section_role_sees_no_global_key_in_config(
            self, keys_editor_client):
        """Секция `keys` не открывает глобальный секрет и на чтении."""
        resp = keys_editor_client.get("/api/config",
                                      headers=_hdr(KEYS_EDITOR_ID))
        assert resp.status_code == 200
        items = {i["key"]: i for i in resp.json()["items"]}
        assert IMAGE_KEY not in items

    def test_global_admin_saves_ok(self, client):
        resp = client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "rbac-ok-key",
                  "scope": "global"},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert client.cache.get(IMAGE_KEY) == "rbac-ok-key"

    def test_keys_editor_me_flag_false(self, keys_editor_client):
        """UI получит is_global_admin=false → поле disabled (паритет)."""
        body = keys_editor_client.get("/api/me",
                                      headers=_hdr(KEYS_EDITOR_ID)).json()
        assert body["is_global_admin"] is False

    def test_admin_role_without_wildcard_is_global(self, admin_no_wildcard_client):
        """Роль `admin` без wildcard: legacy-role_type → global_admin.
        /api/me.is_global_admin=true и safe-эндпоинт 200 — паритет с UI
        (H1: computed как значение, без TypeError)."""
        body = admin_no_wildcard_client.get(
            "/api/me", headers=_hdr(ADMIN_NO_WILDCARD_ID)).json()
        assert body["is_global_admin"] is True
        resp = admin_no_wildcard_client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "admin-nw-key",
                  "scope": "global"},
            headers=_hdr(ADMIN_NO_WILDCARD_ID))
        assert resp.status_code == 200
        assert admin_no_wildcard_client.cache.get(IMAGE_KEY) == "admin-nw-key"

    def test_custom_global_admin_role_allowed(self, custom_global_admin_client):
        """Custom `role_type=global_admin` без wildcard: backend 200,
        `/api/me.is_global_admin=true` — UI не запрещает лишнего (M1)."""
        body = custom_global_admin_client.get(
            "/api/me", headers=_hdr(CUSTOM_GA_ID)).json()
        assert body["is_global_admin"] is True
        resp = custom_global_admin_client.put(
            "/api/config/keys/own",
            json={"key_name": IMAGE_KEY, "value": "custom-ga-key",
                  "scope": "global"},
            headers=_hdr(CUSTOM_GA_ID))
        assert resp.status_code == 200
        assert custom_global_admin_client.cache.get(IMAGE_KEY) == "custom-ga-key"


# ═══ Reload + R17-логи (review iter1, Finding M/spec §6) ════════════════════

class TestReloadAndLogs:
    def test_reload_shows_configured_mask(self, client):
        """После PUT «перезагрузка» (свежий GET /api/config) показывает
        {configured:true,last4}, а не пусто — ключ не потерян."""
        client.put("/api/config/keys/own",
                   json={"key_name": IMAGE_KEY, "value": "reload-secret-4321",
                         "scope": "global"},
                   headers=_hdr(ADMIN_ID))
        items = {i["key"]: i
                 for i in client.get("/api/config",
                                     headers=_hdr(ADMIN_ID)).json()["items"]}
        assert items[IMAGE_KEY]["value"] == {"configured": True,
                                             "last4": "4321"}

    def test_logs_never_contain_raw(self, client, caplog):
        """R17: raw-значение не попадает ни в одну лог-запись (PUT/GET/DELETE)."""
        sentinel = "log-sentinel-raw-987654"
        with caplog.at_level(logging.INFO):
            client.put("/api/config/keys/own",
                       json={"key_name": IMAGE_KEY, "value": sentinel,
                             "scope": "global"},
                       headers=_hdr(ADMIN_ID))
            client.get("/api/config", headers=_hdr(ADMIN_ID))
            client.get("/api/config/keys/own", headers=_hdr(ADMIN_ID))
            client.delete(f"/api/config/keys/own/{IMAGE_KEY}",
                          headers=_hdr(ADMIN_ID))
        assert sentinel not in caplog.text
        assert all(sentinel not in r.getMessage() for r in caplog.records)


# ═══ UI-разметка заглушки (spec §3.3) ═══════════════════════════════════════

class TestIndexMarkup:
    def test_installed_badge_present(self):
        assert "Ключ установлен" in _INDEX
        assert "f.globalSecret && blockFieldConfigured(f)" in _INDEX

    def test_global_secret_admin_only_hint(self):
        assert "f.globalSecret && !canEditConfig(f.key)" in _INDEX
        assert "только глобальный администратор" in _INDEX
