"""MOD-ACL-UX-01 M4C C2 — read-only «Проверить доступ»/effective.

Контракт: plans/features/mod-acl-ux-01/evidence/m4c/c2-contract-2026-11-22.md
§4, §5, §7.1.

Проверяется:
  * `GET /api/access/effective`: person+scope (self/делегировано global
    admin), слои роль→потолок→чат→матрица→секрет→возможность→поверхность,
    DM только владельцу, групповой профиль 404, chat_id=0/422;
  * strict: холодный кэш/PG down → 503 (не «deny»/не «default»); seeded +
    PG down: section/action global 200, param/key global 503, chat 503;
  * F-C2-1: auth-check матрицы strict → cold+PG down 503, seeded non-global
    403, seeded admin 503 на strict-read;
  * `GET /api/access/chats/{id}/param_permissions`: только известные 622
    ключа, `legacy`-нормализация, `filtered_out`, свежее чтение, no-leak;
  * `GET /api/access/chats/{id}/admins`: role_name/added_by/created_at/
    display_name, 403/404/503;
  * анти-дрейф: `layers`/decision сверяются с ФАКТИЧЕСКИМИ функциями
    (`deps.*`, `access.can_view_param/can_edit_param/can_access_chat`,
    `routes._persona_*`, `speech._library_can_edit`) на том же ctx;
  * доказательство делегирования: monkeypatch примитивов меняет решение
    (своего матчера нет);
  * только чтение: ни одного write-маршрута не добавлено.

Harness повторяет C1 (`test_webapp_access_matrix_read.py`) без его правки.
"""
import asyncio
import hashlib
import hmac
import inspect
import json
import re
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services import access as access_srv
from services import access_preview as preview_srv
from services import roles as roles_srv
from services.config_cache import ConfigCache
from services.param_catalog import REGISTRY, get_by_pg_key
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.api import routes as routes_mod
from web.api import speech as speech_mod
from web.app import create_app

TEST_TOKEN = "123456:TEST_TOKEN_FOR_M4C2_EFFECTIVE"
ADMIN_ID = 5885953495
GLOBAL_ROLE_ID = 700000001
MODERATOR_ID = 1313107079
LOCAL_ID = 700000002
CUSTOM_ID = 424242424
CUSTOM_CONTENT_ID = 700000003
HUMOR_ID = 700000004
MODERATOR2_ID = 700000005
CUSTOM_KEYS_ID = 700000006
USER_ID = 999999999
CHAT_ID = -1001234567890
CHAT_NO_PROFILE = -1009999999999
CHAT_EMPTY_PROFILE = -1007777777777

SENTINEL_DB = "SENTINEL_DB_VALUE_DO_NOT_LEAK"
SENTINEL_PROMPT = "SENTINEL_PROMPT_TEXT_DO_NOT_LEAK"
SENTINEL_SECRET = "SENTINEL_SECRET_VALUE_DO_NOT_LEAK"
SENTINEL_META = "SENTINEL_META_DO_NOT_LEAK"

LIMITS_KEY = "limits.search_max_symbols"
GLOBAL_OVERRIDE_KEY = "limits.summary_hybrid_context_tokens"
PROMPT_KEY = "prompts.summary_system_prompt"
CONTENT_KEY = "content.info_how_it_works"
NO_PERCHAT_KEY = "models.llm_model_name"
KEY_KEY = "keys.groq_api_key"
HIDDEN_KEY = "limits.chat_timezone"
NONSECRET_KEY = "keys.embedding_quota_group_labels"
NONSECRET_PROVIDER_KEY = "keys.random_quantum_endpoint"
HIDDEN_KEY_KEY = "keys.random_quantum_provider"
NONSECRET_KEYS = (
    "keys.embedding_quota_group_labels",
    "keys.random_quantum_endpoint",
    "keys.random_quantum_plan",
    "keys.random_quantum_batch_length",
    "keys.random_quantum_data_type",
    "keys.random_quantum_request_timeout_seconds",
    "keys.random_quantum_refill_low_watermark",
    "keys.random_quantum_buffer_max_values",
)


ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False, "role_type": None},
    {"role_name": "root_ops",
     "permissions": {"sections": ["limits"], "actions": []},
     "is_custom": False, "role_type": "global_admin"},
    {"role_name": "moderator",
     "permissions": {"sections": ["limits"],
                     "actions": ["control.restart", "control.stop",
                                 "control.start"]},
     "is_custom": False, "role_type": "moderator"},
    {"role_name": "local_admin",
     "permissions": {"sections": ["limits", "flags", "reactions", "content",
                                  "chat_lore"], "actions": []},
     "is_custom": False, "role_type": "local_admin"},
    {"role_name": "user", "permissions": {}, "is_custom": False,
     "role_type": "user"},
    {"role_name": "custom_access", "permissions": {"sections": ["access"]},
     "is_custom": True, "role_type": None},
    {"role_name": "custom_content", "permissions": {"sections": ["content"]},
     "is_custom": True, "role_type": None},
    {"role_name": "custom_humor",
     "permissions": {"actions": ["edit_humor_library"]},
     "is_custom": True, "role_type": None},
    {"role_name": "custom_keys",
     "permissions": {"keys": ["keys.embedding_quota_group_labels"]},
     "is_custom": True, "role_type": None},
]
ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-11-22T00:00:00+00:00"},
    {"telegram_id": GLOBAL_ROLE_ID, "role_name": "root_ops",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:01+00:00"},
    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:02+00:00"},
    {"telegram_id": LOCAL_ID, "role_name": "local_admin",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:03+00:00"},
    {"telegram_id": CUSTOM_ID, "role_name": "custom_access",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:04+00:00"},
    {"telegram_id": CUSTOM_CONTENT_ID, "role_name": "custom_content",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:05+00:00"},
    {"telegram_id": HUMOR_ID, "role_name": "custom_humor",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:06+00:00"},
    {"telegram_id": USER_ID, "role_name": "user",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:07+00:00"},
    {"telegram_id": MODERATOR2_ID, "role_name": "moderator",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:08+00:00"},
    {"telegram_id": CUSTOM_KEYS_ID, "role_name": "custom_keys",
     "added_by": ADMIN_ID, "created_at": "2026-11-22T00:00:09+00:00"},
]

CHAT_ADMIN_ROWS = [
    {"chat_id": CHAT_ID, "telegram_id": LOCAL_ID,
     "role_name": "local_admin", "added_by": ADMIN_ID,
     "created_at": "2026-11-22T01:00:00+00:00"},
    {"chat_id": CHAT_ID, "telegram_id": MODERATOR_ID,
     "role_name": "moderator", "added_by": ADMIN_ID,
     "created_at": "2026-11-22T01:00:01+00:00"},
]

PERM_ROWS = [
    {"key": GLOBAL_OVERRIDE_KEY,
     "value": {"view_roles": ["moderator", "local_admin"],
               "edit_roles": ["local_admin"], "_leak": SENTINEL_DB},
     "updated_at": "2026-11-22T09:00:00+00:00"},
]

LEGACY_CHAT_OVERRIDE = {"view_min_role": "user"}
CHAT_OVERRIDES = {
    LIMITS_KEY: LEGACY_CHAT_OVERRIDE,
    "diag.capability_x": {"view_roles": ["local_admin"]},
    "unknown.not_a_param": {"view_roles": ["user"]},
}


def _profile(chat_id, params, updated_at="2026-11-22T10:00:00+00:00"):
    return {"chat_id": chat_id, "updated_at": updated_at,
            "chat_params": params, "gates_opt_in": False}


PROFILES = {
    CHAT_ID: _profile(CHAT_ID, {
        "overrides": {
            CONTENT_KEY: SENTINEL_PROMPT,
            KEY_KEY: SENTINEL_SECRET,
        },
        "perm_overrides": dict(CHAT_OVERRIDES),
        "meta": {"note": SENTINEL_META},
    }),
    CHAT_EMPTY_PROFILE: _profile(
        CHAT_EMPTY_PROFILE, {"perm_overrides": {}},
        updated_at="2026-11-22T11:00:00+00:00"),
    USER_ID: _profile(USER_ID, {"perm_overrides": {}, "overrides": {}}),
}


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
    def __init__(self, perm_rows=()):
        self._perm_rows = list(perm_rows)
        self.fetch_raises = False
        self.fetchrow_raises = False

    async def fetch(self, sql, *args):
        if self.fetch_raises:
            raise RuntimeError("PG fetch failed")
        low = sql.lower()
        if "param_permissions" in low:
            return self._perm_rows
        if "chat_admins" in low:
            chat_id = args[0] if args else None
            return [r for r in CHAT_ADMIN_ROWS if r["chat_id"] == chat_id]
        if "bot_settings" in low:
            return []
        if "bot_roles" in low:
            return ROLE_ROWS
        if "bot_admins" in low:
            return ADMIN_ROWS
        return []

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        if self.fetchrow_raises:
            raise RuntimeError("PG fetchrow failed")
        low = sql.lower()
        if "chat_profiles" in low:
            return PROFILES.get(args[0])
        if "chat_admins" in low:
            chat_id, telegram_id = args[0], args[1]
            for r in CHAT_ADMIN_ROWS:
                if (r["chat_id"] == chat_id
                        and r["telegram_id"] == telegram_id):
                    return r
            return None
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self_inner):
                return self

            async def __aexit__(self_inner, *exc):
                return False

        return _Tx()


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self_inner):
                return self._conn

            async def __aexit__(self_inner, *exc):
                return False

        return _CM()

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

    async def init(self):
        pass

    async def close(self):
        pass


class _NoPoolPg:
    """PG-объект без пула: cold start / обрыв соединения."""

    pool = None

    async def connect(self):
        raise ConnectionError("PG down")

    async def init(self):
        raise ConnectionError("PG down")

    async def close(self):
        pass


def _seed_cache(cache, *, with_pg: bool = True,
                role_rows=None, admin_rows=None) -> ConfigCache:
    """Заполнить RAM-снапшот так же, как _load_all (без init/lifespan)."""
    role_rows = ROLE_ROWS if role_rows is None else role_rows
    admin_rows = ADMIN_ROWS if admin_rows is None else admin_rows
    roles_map = {}
    perms_map = {}
    for r in role_rows:
        perms = r.get("permissions") or {}
        roles_map[r["role_name"]] = {
            "permissions": perms,
            "is_custom": r.get("is_custom", False),
            "role_type": r.get("role_type"),
        }
        perms_map[r["role_name"]] = Permissions.from_dict(perms)
    cache._roles = roles_map
    cache._permissions = perms_map
    cache._admins = {a["telegram_id"]: a["role_name"] for a in admin_rows}
    cache._admins_full = {a["telegram_id"]: dict(a) for a in admin_rows}
    cache._pg_available = bool(with_pg)
    cache._initialized = True
    return cache


def _live_cache(conn=None, *, with_pg=True) -> ConfigCache:
    pg = _FakePg(conn or _FakeConn(PERM_ROWS)) if with_pg else _NoPoolPg()
    cache = ConfigCache(pg=pg, retry_attempts=1, retry_delay=0)
    return _seed_cache(cache, with_pg=with_pg)


def _cold_cache() -> ConfigCache:
    cache = ConfigCache(pg=_NoPoolPg(), retry_attempts=1, retry_delay=0)
    cache._roles = {}
    cache._permissions = {}
    cache._admins = {}
    cache._admins_full = {}
    cache._pg_available = False
    return cache


@pytest.fixture(autouse=True)
def _reset_matrix_cache():
    access_srv.reset_param_permissions_cache()
    yield
    access_srv.reset_param_permissions_cache()


@pytest.fixture
def monkey_settings(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(routes_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN),
                        raising=False)


def _client(cache, monkey_settings):
    client = TestClient(create_app(cache))
    client.cache = cache
    return client


def _effective(client, *, actor=None, caller=ADMIN_ID, chat_id=None,
               resource="section.access", operation="view", headers=False):
    params = {"resource": resource, "operation": operation}
    if chat_id is not None:
        params["chat_id"] = chat_id
    if actor is not None and actor != caller:
        params["telegram_id"] = actor
    hdrs = _hdr(caller) if not headers else None
    return client.get("/api/access/effective", params=params, headers=hdrs)


def _effective_actor(client, actor, *, caller=ADMIN_ID, chat_id=None,
                     resource="section.access", operation="view"):
    params = {"resource": resource, "operation": operation,
              "telegram_id": actor}
    if chat_id is not None:
        params["chat_id"] = chat_id
    return client.get("/api/access/effective", params=params,
                      headers=_hdr(caller))


def _layer(data, layer_id):
    for layer in data["layers"]:
        if layer["id"] == layer_id:
            return layer
    return None


# ── 1. Effective: слои и фактические решения ────────────────────────────────

class TestEffectiveLayers:
    def test_admin_section_access_allowed_both_layers(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["preview"] is True and data["mode"] == "self"
        assert data["decision"] == "allowed"
        assert [l["id"] for l in data["layers"]] == [
            "role", "global_admin_ceiling"]
        assert _layer(data, "role")["decision"] == "allowed"
        assert _layer(data, "role")["reason"] == "wildcard"
        assert _layer(data, "global_admin_ceiling")["decision"] == "allowed"
        assert data["evaluated_at"].endswith("Z")
        assert data["resolver"] == preview_srv.RESOLVER
        assert data["note"] == "Предварительная проверка. Права не изменены."

    def test_custom_section_access_is_mixed(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        data = _effective_actor(client, CUSTOM_ID).json()
        assert data["decision"] == "mixed"
        assert _layer(data, "role")["decision"] == "allowed"
        assert _layer(data, "role")["reason"] == "section"
        assert _layer(data, "global_admin_ceiling")["decision"] == "denied"
        assert data["actor"]["role_type"] == "custom"

    def test_moderator_section_limits_is_visibility_only(self, monkey_settings):
        """C2-R1-3: у section.limits нет route guard — только видимость раздела."""
        client = _client(_live_cache(), monkey_settings)
        data = _effective_actor(client, MODERATOR_ID,
                                resource="section.limits").json()
        assert data["decision"] == "not_applicable"
        layer = _layer(data, "role")
        assert layer["applies_to"] == "ui_visibility"
        assert layer["decision"] == "allowed"      # грант секции виден
        assert layer["matched"] == "section.limits"
        assert layer["guard"].startswith("ui visibility")
        assert layer["consumers"] == []
        assert 'requires_permission("limits")' not in layer["guard"]

    def test_user_section_limits_visibility_denied(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        data = _effective_actor(client, USER_ID,
                                resource="section.limits").json()
        assert data["decision"] == "not_applicable"
        layer = _layer(data, "role")
        assert layer["decision"] == "denied"
        assert layer["reason"] == "no_match"
        assert layer["applies_to"] == "ui_visibility"

    def test_global_param_view_is_readable_by_any_auth(self, monkey_settings):
        """F-C2-3: глобальный non-secret GET /api/config доступен всем."""
        client = _client(_live_cache(), monkey_settings)
        data = _effective(client, actor=None, caller=USER_ID,
                          resource="param." + CONTENT_KEY).json()
        assert data["decision"] == "allowed"
        surface = _layer(data, "config_surface")
        assert surface["reason"] == "global_config_all"
        assert _layer(data, "role")["decision"] == "not_applicable"
        # title/secret/hidden — только global-admin-вызывающему.
        assert data["resource"]["title"] is None
        assert data["resource"]["secret"] is None
        assert data["resource"]["hidden"] is None
        # А admin-вызывающий видит метаданные каталога.
        admin = _effective(client, resource="param." + CONTENT_KEY).json()
        assert admin["resource"]["title"]
        assert admin["resource"]["secret"] is False

    def test_moderator_global_param_edit_denied_without_grant(self,
                                                              monkey_settings):
        """D3/F-C2-2: глобальная запись — только право param.<key>, без bypass."""
        client = _client(_live_cache(), monkey_settings)
        data = _effective_actor(
            client, MODERATOR_ID, resource="param." + CONTENT_KEY,
            operation="edit").json()
        assert data["decision"] == "denied"
        role = _layer(data, "role")
        assert role["guard"] == "web.api.deps.can_edit_param(%s)" % CONTENT_KEY
        assert role["reason"] == "no_match"

    def test_role_type_global_admin_without_wildcard(self, monkey_settings):
        """role_type=global_admin проходит section-гейты, но не param.<key>."""
        client = _client(_live_cache(), monkey_settings)
        sec = _effective_actor(client, GLOBAL_ROLE_ID,
                               resource="section.access").json()
        assert sec["decision"] == "allowed"
        assert _layer(sec, "role")["reason"] == "role_type"
        param = _effective_actor(
            client, GLOBAL_ROLE_ID, resource="param." + CONTENT_KEY,
            operation="edit").json()
        assert param["decision"] == "denied"
        allowed = _effective_actor(
            client, GLOBAL_ROLE_ID, resource="param.limits.summary_hybrid_context_tokens",
            operation="edit").json()
        assert allowed["decision"] == "allowed"   # секция limits покрывает param

    def test_moderator_chat_view_allowed_edit_denied(self, monkey_settings):
        """MAC-S8-505 наследование: view по матрице, edit — нужен грант."""
        client = _client(_live_cache(), monkey_settings)
        view = _effective_actor(client, MODERATOR2_ID, chat_id=CHAT_ID,
                                resource="param." + LIMITS_KEY).json()
        assert view["decision"] == "allowed"
        assert view["scope"] == {
            "kind": "chat", "chat_id": CHAT_ID, "title": None,
            "chat_role": None, "profile_present": True}
        assert _layer(view, "chat_access")["decision"] == "allowed"
        edit = _effective_actor(client, MODERATOR2_ID, chat_id=CHAT_ID,
                                resource="param." + LIMITS_KEY,
                                operation="edit").json()
        assert edit["decision"] == "denied"
        assert _layer(edit, "chat_grant")["decision"] == "denied"
        assert _layer(edit, "chat_grant")["reason"] == "no_grant"

    def test_local_admin_chat_view_and_edit_allowed(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        for op in ("view", "edit"):
            data = _effective_actor(client, LOCAL_ID, chat_id=CHAT_ID,
                                    resource="param." + LIMITS_KEY,
                                    operation=op).json()
            assert data["decision"] == "allowed", op
            assert _layer(data, "chat_matrix")["source"] == "chat_override", op
            if op == "edit":
                assert _layer(data, "chat_grant")["reason"] == "local_admin"

    def test_dm_owner_allowed_own_settings(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective(client, actor=None, caller=USER_ID,
                          chat_id=USER_ID, resource="param." + LIMITS_KEY,
                          operation="edit")
        data = resp.json()
        assert resp.status_code == 200
        assert data["decision"] == "allowed"
        assert data["scope"]["kind"] == "dm"
        assert data["scope"]["title"] == "Личные сообщения"
        assert data["actor"]["is_dm_owner"] is True

    def test_custom_content_chat_persona_allowed_global_denied(
            self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        chat = _effective_actor(
            client, CUSTOM_CONTENT_ID, chat_id=CHAT_ID,
            resource="action.edit_persona", operation="execute").json()
        assert chat["decision"] == "allowed"
        assert _layer(chat, "scope_capability")["decision"] == "allowed"
        assert _layer(chat, "role")["decision"] == "denied"
        glob = _effective_actor(
            client, CUSTOM_CONTENT_ID, resource="action.edit_persona",
            operation="execute").json()
        assert glob["decision"] == "denied"

    def test_humor_library_chat_uses_persona_path_only(self, monkey_settings):
        """chat-ветка `_library_can_edit` не читает edit_humor_library."""
        client = _client(_live_cache(), monkey_settings)
        data = _effective_actor(
            client, HUMOR_ID, chat_id=CHAT_ID,
            resource="action.edit_humor_library", operation="execute").json()
        assert data["decision"] == "denied"
        glob = _effective_actor(
            client, HUMOR_ID, resource="action.edit_humor_library",
            operation="execute").json()
        assert glob["decision"] == "allowed"
        assert _layer(glob, "role")["reason"] == "action"

    def test_chat_lore_global_not_applicable_chat_guard(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        glob = _effective(client, resource="section.chat_lore").json()
        assert glob["decision"] == "not_applicable"
        vis = _layer(glob, "role")
        assert vis["applies_to"] == "ui_visibility"
        assert vis["consumers"] == []
        assert vis["guard"].startswith("ui visibility")
        assert 'requires_permission("chat_lore")' not in vis["guard"]
        chat = _effective_actor(client, LOCAL_ID, chat_id=CHAT_ID,
                                resource="section.chat_lore").json()
        assert chat["decision"] == "allowed"
        assert _layer(chat, "chat_access")["decision"] == "allowed"
        moderator = _effective_actor(client, MODERATOR_ID, chat_id=CHAT_ID,
                                     resource="section.chat_lore").json()
        assert moderator["decision"] == "allowed"   # грант chat_admins
        user = _effective_actor(client, USER_ID, chat_id=CHAT_ID,
                                resource="section.chat_lore").json()
        assert user["decision"] == "denied"
        assert _layer(user, "chat_access")["hard"] is True

    def test_chat_other_section_not_applicable(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        data = _effective_actor(client, MODERATOR_ID, chat_id=CHAT_ID,
                                resource="section.limits").json()
        assert data["decision"] == "not_applicable"
        layer = _layer(data, "role")
        assert layer["applies_to"] == "ui_visibility"
        assert layer["consumers"] == []
        assert layer["guard"].startswith("ui visibility")

    def test_key_chat_not_applicable(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        data = _effective_actor(client, ADMIN_ID, chat_id=CHAT_ID,
                                resource="key." + KEY_KEY,
                                operation="edit").json()
        assert data["decision"] == "not_applicable"
        assert _layer(data, "scope_capability")["reason"] == "keys_via_byok"

    def test_global_key_view_and_edit(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        admin = _effective(client, resource="key." + KEY_KEY).json()
        assert admin["decision"] == "allowed"
        assert _layer(admin, "secret_policy")["decision"] == "allowed"
        mod = _effective_actor(client, MODERATOR_ID,
                               resource="key." + KEY_KEY).json()
        assert mod["decision"] == "denied"
        assert _layer(mod, "secret_policy")["hard"] is True
        edit = _effective_actor(client, MODERATOR_ID,
                                resource="key." + KEY_KEY,
                                operation="edit").json()
        assert edit["decision"] == "denied"
        assert _layer(edit, "role")["guard"].startswith(
            "web.api.deps.can_view_key_value")


class TestKeyConfigSemantics:
    """C2-R1-2: preview зеркалит фактический GET/POST /api/config для keys."""

    def test_all_non_secret_keys_visible_to_any_authenticated(
            self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert len(NONSECRET_KEYS) == 8
        for key in NONSECRET_KEYS:
            for caller in (USER_ID, MODERATOR_ID, ADMIN_ID):
                data = _effective(client, actor=None, caller=caller,
                                  resource="key." + key).json()
                assert data["decision"] == "allowed", (key, caller)
                surface = _layer(data, "config_surface")
                assert surface["reason"] == "global_config_all", (key, caller)
                assert surface["guard"].startswith("web.api.routes.get_config")
                assert _layer(data, "role")["decision"] == "not_applicable"

    def test_hidden_key_is_denied_even_for_admin(self, monkey_settings):
        """hidden: GET исключает; POST → 422; preview не выдаёт allowed."""
        client = _client(_live_cache(), monkey_settings)
        for op in ("view", "edit"):
            data = _effective(client, resource="key." + HIDDEN_KEY_KEY,
                              operation=op).json()
            assert data["decision"] == "denied", op
            layer = _layer(data, "config_surface")
            assert layer["reason"] == "hidden_parameter", op
            assert layer["hard"] is True, op
            assert "GET /api/config" in layer["consumers"]
            assert data["resource"]["hidden"] is True
        # non-admin: hidden-ресурс не принимается (422, как и для param.*)
        resp = _effective(client, actor=None, caller=MODERATOR_ID,
                          resource="key." + HIDDEN_KEY_KEY)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "unknown_resource"

    def test_non_secret_key_edit_uses_actual_right(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        mod = _effective_actor(client, MODERATOR_ID,
                               resource="key." + NONSECRET_KEY,
                               operation="edit").json()
        assert mod["decision"] == "denied"
        assert _layer(mod, "role")["reason"] == "no_match"
        keys_role = _effective_actor(client, CUSTOM_KEYS_ID,
                                     resource="key." + NONSECRET_KEY,
                                     operation="edit").json()
        assert keys_role["decision"] == "allowed"
        assert _layer(keys_role, "role")["reason"] == "key"
        provider_grant = _effective_actor(
            client, CUSTOM_KEYS_ID,
            resource="key." + NONSECRET_PROVIDER_KEY, operation="edit").json()
        assert provider_grant["decision"] == "denied"
        assert _layer(provider_grant, "role")["guard"].startswith(
            "web.api.routes.post_config_global (provider key)")
        provider_admin = _effective(
            client, resource="key." + NONSECRET_PROVIDER_KEY,
            operation="edit").json()
        assert provider_admin["decision"] == "allowed"
        # role_type=global_admin без wildcard: у can_view_key_value нет bypass.
        role_type_admin = _effective_actor(
            client, GLOBAL_ROLE_ID, resource="key." + NONSECRET_KEY,
            operation="edit").json()
        assert role_type_admin["decision"] == "denied"


# Допустимые строки guard'ов: только реальные функции/гварды продукта.
_REAL_GUARD_MARKERS = (
    'web.api.deps.requires_permission("access")',
    'web.api.deps.requires_permission("edit_info")',
    'web.api.deps.requires_permission("action.control.restart")',
    'web.api.deps.requires_permission("action.control.stop")',
    'web.api.deps.requires_permission("action.control.start")',
    'web.api.deps.requires_permission("action.debug.config")',
    "is_global_admin (inline)",
    "access.can_access_chat",
    "access.can_view_param",
    "access.can_edit_param",
    "web.api.deps.can_edit_param",
    "web.api.deps.can_view_key_value",
    "web.api.routes._persona_has_edit_action",
    "web.api.routes._persona_can_edit",
    "web.api.speech._library_can_edit",
    "web.api.chat_lore.can_access_chat",
    "web.api.routes.get_config",
    "web.api.routes.post_config",
    "web.api.deps.user_has_permission (не вызывается)",
)


def _guard_is_real(guard: str) -> bool:
    return any(marker in guard for marker in _REAL_GUARD_MARKERS)


class TestLayerHonesty:
    """C2-R1-3: каждый слой — реальный guard ИЛИ явная section visibility."""

    def test_every_layer_is_real_guard_or_visibility(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        requests = [
            (ADMIN_ID, None, "section.access", "view"),
            (CUSTOM_ID, None, "section.access", "view"),
            (MODERATOR_ID, None, "section.limits", "view"),
            (USER_ID, None, "section.limits", "view"),
            (ADMIN_ID, None, "section.chat_lore", "view"),
            (ADMIN_ID, CHAT_ID, "section.chat_lore", "view"),
            (MODERATOR_ID, CHAT_ID, "param." + LIMITS_KEY, "view"),
            (LOCAL_ID, CHAT_ID, "param." + LIMITS_KEY, "edit"),
            (ADMIN_ID, None, "param." + HIDDEN_KEY, "view"),
            (ADMIN_ID, None, "key." + KEY_KEY, "view"),
            (ADMIN_ID, None, "key." + NONSECRET_KEY, "view"),
            (ADMIN_ID, None, "key." + HIDDEN_KEY_KEY, "view"),
            (ADMIN_ID, None, "action.edit_info", "execute"),
            (MODERATOR_ID, None, "action.control.restart", "execute"),
            (CUSTOM_CONTENT_ID, CHAT_ID, "action.edit_persona", "execute"),
        ]
        checked = 0
        for actor, chat_id, resource, operation in requests:
            if actor == ADMIN_ID and chat_id is None:
                data = _effective(client, resource=resource,
                                  operation=operation).json()
            else:
                data = _effective_actor(client, actor, chat_id=chat_id,
                                        resource=resource,
                                        operation=operation).json()
            for layer in data["layers"]:
                checked += 1
                if layer["applies_to"] == "ui_visibility":
                    assert layer["guard"].startswith("ui visibility"), layer
                    assert layer["consumers"] == [], layer
                    assert "requires_permission" not in layer["guard"], layer
                else:
                    assert _guard_is_real(layer["guard"]), layer
                    assert layer["consumers"], layer
        assert checked >= 20

    def test_no_fabricated_section_guard_strings(self):
        source = inspect.getsource(preview_srv)
        for sid in ("limits", "content", "prompts", "models", "keys",
                    "flags", "reactions", "memory", "temporal", "chat_lore"):
            assert 'requires_permission("%s")' % sid not in source, sid


# ── 2. Ресурсы/операции: 422 без «тихого allow» ────────────────────────────

class TestResourceValidation:
    @pytest.mark.parametrize("resource,operation,code", [
        ("wat.thing", "view", "unknown_resource"),
        ("section.nope", "view", "unknown_resource"),
        ("section.access", "edit", "invalid_operation"),
        ("action.edit_info", "view", "invalid_operation"),
        ("param.nope.nope", "view", "unknown_resource"),
        ("param." + KEY_KEY, "view", "use_key_namespace"),
        ("key." + LIMITS_KEY, "view", "unknown_resource"),
        ("param." + CONTENT_KEY, "execute", "invalid_operation"),
        ("param." + CONTENT_KEY, "apply", "invalid_operation"),
    ])
    def test_422_codes(self, monkey_settings, resource, operation, code):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective_actor(client, USER_ID, resource=resource,
                                operation=operation)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == code

    def test_hidden_param_non_admin_is_422(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective(client, actor=None, caller=MODERATOR_ID,
                          resource="param." + HIDDEN_KEY)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "unknown_resource"

    def test_hidden_param_admin_gets_hard_deny(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        spec = get_by_pg_key(HIDDEN_KEY)
        assert spec is not None and spec.hidden
        data = _effective(client, resource="param." + HIDDEN_KEY).json()
        assert data["decision"] == "denied"
        surface = _layer(data, "config_surface")
        assert surface["reason"] == "hidden_parameter" and surface["hard"] is True
        assert data["resource"]["hidden"] is True

    def test_chat_id_zero_is_422(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective(client, chat_id=0)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "invalid_chat_id"


# ── 3. Strict/503: «не прочитано» ≠ «нет прав» ────────────────────────────

class TestStrictStorage:
    def test_cold_cache_pg_down_all_three_503(self, monkey_settings):
        cache = _cold_cache()
        client = _client(cache, monkey_settings)
        assert _effective(client, headers=False).status_code == 503
        assert client.get("/api/access/chats/%d/param_permissions" % CHAT_ID,
                          headers=_hdr(ADMIN_ID)).status_code == 503
        assert client.get("/api/access/chats/%d/admins" % CHAT_ID,
                          headers=_hdr(ADMIN_ID)).status_code == 503
        assert client.get("/api/access/param_permissions",
                          headers=_hdr(ADMIN_ID)).status_code == 503

    def test_seeded_pg_down_section_action_200_param_503(self,
                                                        monkey_settings):
        client = _client(_live_cache(with_pg=False), monkey_settings)
        assert _effective(client, resource="section.access").status_code == 200
        assert _effective(client, resource="action.edit_info",
                          operation="execute").status_code == 200
        param = _effective(client, resource="param." + CONTENT_KEY)
        assert param.status_code == 503
        assert param.json()["detail"]["code"] == "access_storage_unavailable"
        key = _effective(client, resource="key." + KEY_KEY)
        assert key.status_code == 503

    def test_chat_scope_pg_down_503(self, monkey_settings):
        client = _client(_live_cache(with_pg=False), monkey_settings)
        resp = _effective_actor(client, ADMIN_ID, chat_id=CHAT_ID,
                                resource="param." + LIMITS_KEY)
        assert resp.status_code == 503
        dm = _effective(client, actor=None, caller=USER_ID, chat_id=USER_ID,
                        resource="param." + LIMITS_KEY)
        assert dm.status_code == 503

    def test_f_c2_1_matrix_auth_strict_cold_503(self, monkey_settings):
        client = _client(_cold_cache(), monkey_settings)
        resp = client.get("/api/access/param_permissions", headers=_hdr())
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "access_storage_unavailable"

    def test_f_c2_1_seeded_non_global_403(self, monkey_settings):
        conn = _FakeConn(PERM_ROWS)
        conn.fetch_raises = True       # strict-read матрицы не должен вызываться
        client = _client(_live_cache(conn), monkey_settings)
        assert client.get("/api/access/param_permissions",
                          headers=_hdr(MODERATOR_ID)).status_code == 403

    def test_f_c2_1_seeded_admin_503_on_strict_read(self, monkey_settings):
        client = _client(_live_cache(with_pg=False), monkey_settings)
        resp = client.get("/api/access/param_permissions", headers=_hdr())
        assert resp.status_code == 503


# ── 4. Auth: self/делегирование/DM/группа ──────────────────────────────────

class TestEffectiveAuth:
    def test_missing_init_data_401(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert _effective(client, headers=True).status_code == 401

    def test_self_ok(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert _effective(client, actor=None,
                          caller=MODERATOR_ID).status_code == 200

    def test_delegated_non_admin_403(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective_actor(client, USER_ID, caller=MODERATOR_ID,
                                resource="section.limits")
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "delegated_requires_global_admin"

    def test_delegated_admin_200_mode_delegated(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective_actor(client, USER_ID)
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "delegated"
        assert data["actor"]["telegram_id"] == USER_ID

    def test_foreign_dm_403(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective(client, chat_id=USER_ID, resource="param." + LIMITS_KEY)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "dm_owner_only"

    def test_group_without_profile_404(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective(client, chat_id=CHAT_NO_PROFILE)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "chat_not_found"

    def test_non_admin_caller_without_chat_access_403(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = _effective_actor(client, USER_ID, caller=USER_ID,
                                chat_id=CHAT_ID, resource="param." + LIMITS_KEY)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "chat_forbidden"


# ── 5. Chat override GET ───────────────────────────────────────────────────

class TestChatParamPermissionsGet:
    def _get(self, client, chat_id=CHAT_ID, user=ADMIN_ID):
        return client.get("/api/access/chats/%d/param_permissions" % chat_id,
                          headers=_hdr(user))

    def test_sparse_items_legacy_and_filtered(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = self._get(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["chat_id"] == CHAT_ID
        assert data["profile_present"] is True
        assert data["updated_at"].startswith("2026-11-22T10:00:00")
        assert list(data["items"]) == [LIMITS_KEY]
        item = data["items"][LIMITS_KEY]
        assert item["legacy"] is True
        assert item["view_roles"] == ["user", "moderator", "local_admin"]
        assert item["edit_roles"] == []          # _normalize_perms без base
        assert data["filtered_out"] == 2       # diag.* + неизвестный ключ

    def test_empty_profile_is_200_not_404(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        data = self._get(client, chat_id=CHAT_EMPTY_PROFILE).json()
        assert data["profile_present"] is True
        assert data["items"] == {}
        assert data["filtered_out"] == 0

    def test_fresh_read_ignores_cache(self, monkey_settings):
        conn = _FakeConn(PERM_ROWS)
        cache = _live_cache(conn)
        client = _client(cache, monkey_settings)
        assert self._get(client).json()["items"][LIMITS_KEY]["view_roles"] == [
            "user", "moderator", "local_admin"]
        PROFILES[CHAT_ID]["chat_params"]["perm_overrides"][LIMITS_KEY] = {
            "view_roles": [], "edit_roles": []}
        try:
            fresh = self._get(client).json()
        finally:
            PROFILES[CHAT_ID]["chat_params"]["perm_overrides"][LIMITS_KEY] = (
                LEGACY_CHAT_OVERRIDE)
        assert fresh["items"][LIMITS_KEY]["view_roles"] == []
        assert fresh["items"][LIMITS_KEY]["legacy"] is False

    def test_non_admin_403_and_foreign_dm_403(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert self._get(client, user=MODERATOR_ID).status_code == 403
        assert self._get(client, chat_id=USER_ID).status_code == 403

    def test_group_without_profile_404(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = self._get(client, chat_id=CHAT_NO_PROFILE)
        assert resp.status_code == 404

    def test_pg_down_503(self, monkey_settings):
        client = _client(_live_cache(with_pg=False), monkey_settings)
        resp = self._get(client)
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "access_storage_unavailable"

    def test_no_values_prompts_or_last4(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        body = json.dumps(self._get(client).json(), ensure_ascii=False)
        for sentinel in (SENTINEL_PROMPT, SENTINEL_SECRET, SENTINEL_META,
                         SENTINEL_DB, "last4"):
            assert sentinel not in body
        assert "overrides" not in body


# ── 6. Chat admins GET ─────────────────────────────────────────────────────

class TestChatAdminsGet:
    def _get(self, client, chat_id=CHAT_ID, user=ADMIN_ID):
        return client.get("/api/access/chats/%d/admins" % chat_id,
                          headers=_hdr(user))

    def test_rows_only_allowed_fields(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        resp = self._get(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["chat_id"] == CHAT_ID
        assert [r["telegram_id"] for r in data["admins"]] == [
            LOCAL_ID, MODERATOR_ID]
        for row in data["admins"]:
            assert set(row) == {"telegram_id", "role_name", "added_by",
                                "created_at", "display_name"}
        assert data["admins"][0]["role_name"] == "local_admin"
        assert data["admins"][0]["added_by"] == ADMIN_ID
        assert data["admins"][0]["created_at"].startswith("2026-11-22T01:00:00")

    def test_non_admin_403(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert self._get(client, user=MODERATOR_ID).status_code == 403

    def test_group_without_profile_404(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        assert self._get(client, chat_id=CHAT_NO_PROFILE).status_code == 404

    def test_pg_down_503(self, monkey_settings):
        client = _client(_live_cache(with_pg=False), monkey_settings)
        assert self._get(client).status_code == 503


# ── 7. Анти-дрейф: preview ↔ фактические guard-функции ────────────────────

def _ctx(actor, chat_id=None):
    return asyncio.run(roles_srv.access_for(actor, chat_id, cache=_cache_for_ad()))


_AD_CACHE = {"cache": None}


def _cache_for_ad():
    if _AD_CACHE["cache"] is None:              # pragma: no cover — guard
        raise RuntimeError("anti-drift cache не инициализирован")
    return _AD_CACHE["cache"]


def _expected_decision(cache, actor, chat_id, resource, operation):
    """Независимый расчёт из ФАКТИЧЕСКИХ функций продукта (не из preview)."""
    kind, rest = resource.split(".", 1)
    ctx = asyncio.run(roles_srv.access_for(actor, chat_id, cache=cache))
    if kind == "section":
        if chat_id is None:
            if rest != "access":
                # У прочих section.* нет route guard'а — только видимость.
                return "not_applicable"
            allowed = deps_mod.user_has_permission(cache, actor,
                                                   "section.access")
            ceiling = deps_mod.user_is_global_admin(cache, actor)
            if allowed and ceiling:
                return "allowed"
            if not allowed and not ceiling:
                return "denied"
            return "mixed"
        if rest == "chat_lore":
            if chat_id > 0:
                return "not_applicable"
            allowed = (deps_mod.user_is_global_admin(cache, actor)
                       or ctx.role_chat in ("local_admin", "moderator"))
            return "allowed" if allowed else "denied"
        return "not_applicable"
    if kind == "action":
        if rest == "edit_persona":
            return "allowed" if routes_mod._persona_can_edit(
                ctx, is_global=chat_id is None) else "denied"
        if rest == "edit_humor_library":
            return "allowed" if speech_mod._library_can_edit(
                cache, types.SimpleNamespace(id=actor), ctx,
                chat_id=chat_id) else "denied"
        required = {"control.restart": "action.control.restart",
                    "control.stop": "action.control.stop",
                    "control.start": "action.control.start",
                    "debug.config": "action.debug.config",
                    "edit_info": "edit_info"}[rest]
        return "allowed" if deps_mod.user_has_permission(
            cache, actor, required) else "denied"
    spec = get_by_pg_key(rest)
    assert spec is not None
    if kind == "key":
        if chat_id is not None:
            return "not_applicable"
        if spec.hidden:
            return "denied"
        if operation == "view":
            if spec.secret:
                return "allowed" if deps_mod.user_is_global_admin(
                    cache, actor) else "denied"
            return "allowed"      # non-secret GET /api/config — всем
        from services import mca_random_source
        if rest in mca_random_source.PROVIDER_KEY_SETTINGS:
            return "allowed" if deps_mod.user_is_global_admin(
                cache, actor) else "denied"
        return "allowed" if deps_mod.can_view_key_value(
            cache, actor, rest) else "denied"
    # param.*
    if chat_id is None:
        if operation == "view":
            if spec.secret:
                return "allowed" if deps_mod.user_is_global_admin(
                    cache, actor) else "denied"
            return "denied" if spec.hidden else "allowed"
        allowed = deps_mod.can_edit_param(cache, actor, rest) and not spec.hidden
        return "allowed" if allowed else "denied"
    if spec.hidden:
        return "denied"
    if not access_srv.can_access_chat(ctx, chat_id):
        return "denied"
    db_override = next((r["value"] for r in PERM_ROWS if r["key"] == rest), None)
    chat_override = ((PROFILES[chat_id]["chat_params"].get("perm_overrides")
                      or {}).get(rest))
    matrix = access_srv.effective_matrix(rest, db_override, chat_override)
    if operation == "view":
        if spec.secret and not ctx.is_global_admin:
            return "denied"
        return "allowed" if access_srv.can_view_param(ctx, matrix) else "denied"
    if not spec.per_chat:
        return "denied"
    return "allowed" if access_srv.can_edit_param(ctx, matrix) else "denied"


ANTI_DRIFT_CASES = [
    (ADMIN_ID, None, "section.access", "view"),
    (CUSTOM_ID, None, "section.access", "view"),
    (MODERATOR_ID, None, "section.access", "view"),
    (GLOBAL_ROLE_ID, None, "section.access", "view"),
    (MODERATOR_ID, None, "section.limits", "view"),
    (USER_ID, None, "section.limits", "view"),
    (USER_ID, None, "param." + CONTENT_KEY, "view"),
    (MODERATOR_ID, None, "param." + CONTENT_KEY, "view"),
    (MODERATOR_ID, None, "param." + CONTENT_KEY, "edit"),
    (ADMIN_ID, None, "param." + GLOBAL_OVERRIDE_KEY, "edit"),
    (MODERATOR_ID, None, "param." + GLOBAL_OVERRIDE_KEY, "edit"),
    (LOCAL_ID, None, "param." + GLOBAL_OVERRIDE_KEY, "edit"),
    (GLOBAL_ROLE_ID, None, "param." + GLOBAL_OVERRIDE_KEY, "edit"),
    (ADMIN_ID, None, "param." + HIDDEN_KEY, "view"),
    (MODERATOR_ID, None, "key." + KEY_KEY, "view"),
    (ADMIN_ID, None, "key." + KEY_KEY, "view"),
    (MODERATOR_ID, None, "key." + KEY_KEY, "edit"),
    (USER_ID, None, "key." + NONSECRET_KEY, "view"),
    (MODERATOR_ID, None, "key." + NONSECRET_KEY, "view"),
    (ADMIN_ID, None, "key." + NONSECRET_KEY, "view"),
    (MODERATOR_ID, None, "key." + NONSECRET_KEY, "edit"),
    (CUSTOM_KEYS_ID, None, "key." + NONSECRET_KEY, "edit"),
    (ADMIN_ID, None, "key." + NONSECRET_PROVIDER_KEY, "edit"),
    (CUSTOM_KEYS_ID, None, "key." + NONSECRET_PROVIDER_KEY, "edit"),
    (ADMIN_ID, None, "key." + HIDDEN_KEY_KEY, "view"),
    (ADMIN_ID, None, "key." + HIDDEN_KEY_KEY, "edit"),
    (MODERATOR_ID, None, "action.control.restart", "execute"),
    (USER_ID, None, "action.control.restart", "execute"),
    (ADMIN_ID, None, "action.edit_info", "execute"),
    (CUSTOM_CONTENT_ID, None, "action.edit_persona", "execute"),
    (CUSTOM_CONTENT_ID, None, "action.edit_humor_library", "execute"),
    (HUMOR_ID, None, "action.edit_humor_library", "execute"),
    (MODERATOR_ID, CHAT_ID, "section.limits", "view"),
    (MODERATOR_ID, CHAT_ID, "section.chat_lore", "view"),
    (LOCAL_ID, CHAT_ID, "section.chat_lore", "view"),
    (USER_ID, CHAT_ID, "section.chat_lore", "view"),
    (MODERATOR_ID, CHAT_ID, "param." + LIMITS_KEY, "view"),
    (MODERATOR_ID, CHAT_ID, "param." + LIMITS_KEY, "edit"),
    (LOCAL_ID, CHAT_ID, "param." + LIMITS_KEY, "view"),
    (LOCAL_ID, CHAT_ID, "param." + LIMITS_KEY, "edit"),
    (ADMIN_ID, CHAT_ID, "param." + NO_PERCHAT_KEY, "edit"),
    (LOCAL_ID, CHAT_ID, "param." + NO_PERCHAT_KEY, "edit"),
    (ADMIN_ID, CHAT_ID, "key." + KEY_KEY, "view"),
    (LOCAL_ID, CHAT_ID, "key." + KEY_KEY, "edit"),
    (CUSTOM_CONTENT_ID, CHAT_ID, "action.edit_persona", "execute"),
    (MODERATOR_ID, CHAT_ID, "action.edit_persona", "execute"),
    (HUMOR_ID, CHAT_ID, "action.edit_humor_library", "execute"),
    (LOCAL_ID, CHAT_ID, "action.edit_humor_library", "execute"),
    (USER_ID, USER_ID, "param." + LIMITS_KEY, "view"),
    (USER_ID, USER_ID, "param." + LIMITS_KEY, "edit"),
]


class TestAntiDrift:
    @pytest.mark.parametrize("actor,chat_id,resource,operation",
                             ANTI_DRIFT_CASES)
    def test_preview_matches_actual_guards(self, monkey_settings, actor,
                                           chat_id, resource, operation):
        cache = _live_cache()
        _AD_CACHE["cache"] = cache
        try:
            expected = _expected_decision(cache, actor, chat_id, resource,
                                          operation)
            client = _client(cache, monkey_settings)
            # DM-скоуп доступен только владельцу (даже admin не смотрит чужой
            # ЛС) → проверяющий = сам актор; групповой чат — global admin.
            if chat_id is not None and chat_id > 0:
                caller = actor
            else:
                caller = ADMIN_ID if chat_id is not None else actor
            if caller == actor:
                resp = _effective(client, actor=None, caller=caller,
                                  chat_id=chat_id, resource=resource,
                                  operation=operation)
            else:
                resp = _effective_actor(client, actor, caller=caller,
                                        chat_id=chat_id, resource=resource,
                                        operation=operation)
            assert resp.status_code == 200, resp.text
            assert resp.json()["decision"] == expected, (
                resource, operation, actor, chat_id)
        finally:
            _AD_CACHE["cache"] = None


# ── 8. Делегирование: своего матчера нет ──────────────────────────────────

class TestDelegationProof:
    def test_role_decision_uses_shared_matcher(self, monkey_settings,
                                               monkeypatch):
        cache = _live_cache()
        client = _client(cache, monkey_settings)
        before = _effective_actor(client, MODERATOR_ID,
                                  resource="action.control.restart",
                                  operation="execute").json()
        assert before["decision"] == "allowed"
        monkeypatch.setattr(preview_srv, "match_permission",
                            lambda perms, required: False)
        after = _effective_actor(client, MODERATOR_ID,
                                 resource="action.control.restart",
                                 operation="execute").json()
        assert after["decision"] == "denied"

    def test_chat_view_uses_shared_can_view_param(self, monkey_settings,
                                                  monkeypatch):
        cache = _live_cache()
        client = _client(cache, monkey_settings)
        before = _effective_actor(client, MODERATOR_ID, chat_id=CHAT_ID,
                                  resource="param." + LIMITS_KEY).json()
        assert before["decision"] == "allowed"
        monkeypatch.setattr(access_srv, "can_view_param",
                            lambda ctx, matrix: False)
        after = _effective_actor(client, MODERATOR_ID, chat_id=CHAT_ID,
                                 resource="param." + LIMITS_KEY).json()
        assert after["decision"] == "denied"

    def test_chat_edit_uses_shared_can_edit_param(self, monkey_settings,
                                                  monkeypatch):
        cache = _live_cache()
        client = _client(cache, monkey_settings)
        before = _effective_actor(client, LOCAL_ID, chat_id=CHAT_ID,
                                  resource="param." + LIMITS_KEY,
                                  operation="edit").json()
        assert before["decision"] == "allowed"
        monkeypatch.setattr(access_srv, "can_edit_param",
                            lambda ctx, matrix: False)
        after = _effective_actor(client, LOCAL_ID, chat_id=CHAT_ID,
                                 resource="param." + LIMITS_KEY,
                                 operation="edit").json()
        assert after["decision"] == "denied"

    def test_preview_has_no_second_acl(self):
        source = inspect.getsource(preview_srv)
        for name in ("can_view_param", "can_edit_param", "effective_matrix",
                     "default_matrix", "requires_permission",
                     "class Permissions"):
            assert not re.search(r"def\s+%s\s*\(" % name, source), name
        assert "from web" not in source, "read-model без web-импортов"


# ── 9. No-leak ─────────────────────────────────────────────────────────────

class TestNoLeak:
    def test_effective_has_no_stored_values_or_prompts(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        bodies = []
        bodies.append(_effective_actor(
            client, ADMIN_ID, chat_id=CHAT_ID,
            resource="param." + CONTENT_KEY, operation="view").json())
        bodies.append(_effective_actor(
            client, MODERATOR_ID, resource="param." + GLOBAL_OVERRIDE_KEY,
            operation="edit").json())
        bodies.append(_effective_actor(
            client, ADMIN_ID, chat_id=CHAT_ID, resource="key." + KEY_KEY,
            operation="edit").json())
        body = json.dumps(bodies, ensure_ascii=False)
        for sentinel in (SENTINEL_PROMPT, SENTINEL_SECRET, SENTINEL_META,
                         SENTINEL_DB, "last4"):
            assert sentinel not in body
        for data in bodies:
            if data["overrides"]:
                assert data["overrides"]["global"]["author_recorded"] is False
                assert data["overrides"]["chat"]["author_recorded"] is False

    def test_overrides_present_and_moment(self, monkey_settings):
        client = _client(_live_cache(), monkey_settings)
        data = _effective(client, resource="param." + GLOBAL_OVERRIDE_KEY,
                          operation="edit").json()
        assert data["overrides"]["global"]["present"] is True
        assert data["overrides"]["global"]["updated_at"].startswith(
            "2026-11-22T09:00:00")
        assert data["overrides"]["chat"]["present"] is False
        chat = _effective_actor(client, LOCAL_ID, chat_id=CHAT_ID,
                                resource="param." + LIMITS_KEY,
                                operation="edit").json()
        assert chat["overrides"]["chat"]["present"] is True
        assert chat["overrides"]["global"]["present"] is False


# ── 10. Read-only инвариант ────────────────────────────────────────────────

class TestReadOnlyInvariant:
    def test_new_routes_are_get_only(self):
        import web.api.access as access_mod
        source = inspect.getsource(access_mod)
        assert source.count('@access_router.get("/effective")') == 1
        assert source.count(
            '@access_router.get("/chats/{chat_id}/param_permissions")') == 1
        assert source.count('@access_router.get("/chats/{chat_id}/admins")') == 1
        writes = re.findall(r"@access_router\.(post|put|delete|patch)\(",
                            source)
        assert len(writes) == 9, writes   # baseline C1/C2: write-маршруты не добавлены

    def test_no_second_storage_in_preview(self):
        source = inspect.getsource(preview_srv)
        for token in ("INSERT INTO", "UPDATE chat_", "UPDATE param_",
                      "DELETE FROM", "CREATE TABLE"):
            assert token.lower() not in source.lower(), token
        assert ".execute(" not in source, "read-model не пишет в хранилище"
