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
LOCAL_ADMIN_ID = 424242424


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

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        # F-14 (DM): chat_params/set_chat_params — профилей в фейке нет →
        # ensure_scope_profile логируется, set_chat_params даёт 409 (0 строк)
        return None

    def transaction(self):
        """set_chat_params: транзакция (фейк — no-op commit)."""

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
            {"key": "keys.llm_api_key", "value": "sk_deepseek_123456",
             "category": "keys", "updated_at": None},
            {"key": "models.llm_timeout", "value": 30.0, "category": "models",
             "updated_at": None},
            {"key": "limits.chat_temperature_preset_default", "value": "balanced",
             "category": "limits", "updated_at": None},
            {"key": "content.info_how_it_works",
             "value": {"html": "<h1>Как это работает</h1>",
                       "updated_at": "2026-08-30T00:00:00+00:00",
                       "updated_by": ADMIN_ID},
             "category": "content"},
            {"key": "memory.infinite_retention", "value": False,
             "category": "memory", "updated_at": None},
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


@pytest.fixture
def local_admin_client(monkeypatch, tmp_path):
    """Отдельный клиент: глобальная роль юзера — local_admin (F-7 §1.2-2
    «локальный админ НЕ видит глобальный ключ»; фикс S1 — глобальный путь)."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(
            INFO_TEXT_FILE=str(tmp_path / "info_text.md"),
            ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(
        settings_rows=[
            {"key": "limits.search_max_symbols", "value": 8000,
             "category": "limits", "updated_at": None},
            {"key": "keys.llm_api_key", "value": "sk_deepseek_123456",
             "category": "keys", "updated_at": None},
        ],
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "local_admin",
             "permissions": {"sections": ["limits", "flags", "reactions",
                                          "content", "chat_lore"], "actions": []},
             "is_custom": False, "role_type": "local_admin"},
            {"role_name": "user", "permissions": {}, "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
            {"telegram_id": LOCAL_ADMIN_ID, "role_name": "local_admin",
             "added_by": ADMIN_ID,
             "created_at": "2026-08-30T00:00:02+00:00"},
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

    def test_media_endpoint_not_under_tma_auth_and_masks_junk(self, client):
        """Раунд 3 (T-687/FR-B2): GET /media — БЕЗ TMA-авторизации (подпись+
        TTL+uuid); мусорный file_id → маска-404 (не 401/500, без traversal)."""
        assert client.get("/media/не-валид.mp4").status_code == 404
        assert client.get("/media/../etc/passwd").status_code == 404
        assert client.get("/media/%2e%2e/x.mp4").status_code == 404
        assert client.get("/media/" + "f" * 32 + ".gif").status_code == 404

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
    """84.12.4 + ФИКС 2026-09-03: значения секретов — ЕДИНЫЙ контракт:
    {"configured","last4"} для ВСЕХ ролей (полное значение не отдаём даже
    админу; замена ключа — только через POST /api/config).

    ФИКС S1 (F-7 §1.2-2): секреты на глобальном пути — ТОЛЬКО глобальному
    админу; local admin/moderator/user не видят глобальный ключ НИ в каком
    виде (в т.ч. last4) — entries keys.* полностью исключаются."""

    def test_admin_sees_masked_secret_too(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        key_item = items["keys.groq_api_key"]
        assert key_item["value"] == {"configured": True, "last4": "1234"}
        assert "gsk_secret_key_1234" not in json.dumps(resp.json())

    def test_moderator_does_not_see_global_keys_at_all(self, client):
        """S1: модератор — НОЛЬ следов глобального ключа (нет даже last4)."""
        resp = client.get("/api/config", headers=_hdr(MODERATOR_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        assert "keys.groq_api_key" not in items
        assert "keys.llm_api_key" not in items

    def test_user_role_does_not_see_global_keys(self, client):
        """S1: user — ключи-секреты отсутствуют, в т.ч. keys.llm_api_key."""
        resp = client.get("/api/config", headers=_hdr(USER_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        assert "keys.groq_api_key" not in items
        assert "keys.llm_api_key" not in items

    def test_local_admin_sees_no_last4_global_key(self, local_admin_client):
        """S1: локальный админ на глобальном пути — keys-секция исключена
        полностью (глобальный ключ НЕ в любом виде, F-7 §1.2-2)."""
        resp = local_admin_client.get("/api/config", headers=_hdr(LOCAL_ADMIN_ID))
        assert resp.status_code == 200
        items = {i["key"]: i for i in resp.json()["items"]}
        assert "keys.llm_api_key" not in items

    def test_no_secret_strings_anywhere_in_response(self, client):
        """ФИКС: во всём ответе /api/config нет значений-строк с полными
        ключами (sk_/gsk_ префиксы и известные секреты)."""
        for role in (ADMIN_ID, MODERATOR_ID, USER_ID):
            resp = client.get("/api/config", headers=_hdr(role))
            blob = resp.text
            assert "gsk_secret_key_1234" not in blob
            assert "sk_deepseek_123456" not in blob
            items = {i["key"]: i for i in resp.json()["items"]}
            for item in items.values():
                if item.get("secret"):
                    assert isinstance(item["value"], dict)
                    assert set(item["value"]) <= {"configured", "last4"}

    def test_non_secret_visible_to_all(self, client):
        resp = client.get("/api/config", headers=_hdr(USER_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        assert items["limits.search_max_symbols"]["value"] == 8000


class TestConfigGroups8424:
    """84.24 (02.09.2026): groups[] + group/description в items + сортировка."""

    def test_groups_metadata_in_response(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        data = resp.json()
        groups = {g["id"]: g for g in data["groups"]}
        # категории, присутствующие в items (fixture: limits/keys/models/content)
        assert "limits_alan" in groups
        assert "keys_llm" in groups
        assert "models_main" in groups
        assert "content_info" in groups
        g = groups["limits_alan"]
        assert g["title"] == "Леха: лимиты"
        assert g["category"] == "limits"
        assert g["order"] == 1
        assert g["description"].strip()
        # сортировка по order
        orders = [g["order"] for g in data["groups"]]
        assert orders == sorted(orders)

    def test_items_have_group_and_description(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        it = items["limits.search_max_symbols"]
        assert it["group"] == "limits_search"
        assert it["description"].strip()
        assert it["title"] == "Длина ответа поиска, символов"
        assert it["type"] == "int"
        assert it["secret"] is False
        assert "value" in it and "category" in it      # старые поля живы

    def test_items_sorted_by_category_group_order_title(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = resp.json()["items"]
        # ключи стабильной сортировки (категория, порядок группы, title)
        order_key = []
        for it in items:
            g = next((x for x in resp.json()["groups"] if x["id"] == it["group"]), None)
            order_key.append((it["category"], g["order"] if g else 999, it["title"]))
        assert order_key == sorted(order_key)

    def test_secret_items_masked_and_grouped(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        key_item = items["keys.groq_api_key"]
        assert key_item["group"] == "keys_groq"
        assert key_item["value"] == {"configured": True, "last4": "1234"}
        assert "gsk_secret_key_1234" not in resp.text

    def test_items_have_widget_field(self, client):
        """Эпик 04.09.2026 (FR-28): GET /api/config отдаёт widget у каждого
        item ("" дефолт; "keyvalue" — KV-редактор summary_aliases)."""
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        it = items["limits.search_max_symbols"]
        assert it["widget"] == ""
        # у всех items поле widget присутствует
        assert all("widget" in i for i in resp.json()["items"])

    def test_summary_aliases_widget_keyvalue_and_json_roundtrip(self, client):
        """FR-28: summary_aliases отдаётся с widget=keyvalue; POST объектом
        JSON сохраняет dict (json-тип каталога), значение горячо читается."""
        aliases = {"138811255": "Леха", "350803143": "Костик"}
        resp = client.post("/api/config",
                           json={"items": [{"key": "limits.summary_aliases",
                                            "value": aliases}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json() == {"updated": ["limits.summary_aliases"]}
        stored = client.cache.get("limits.summary_aliases")
        assert stored == aliases                      # dict, не строка
        assert isinstance(stored, dict)
        resp2 = client.get("/api/config", headers=_hdr(ADMIN_ID))
        item = {i["key"]: i for i in resp2.json()["items"]}["limits.summary_aliases"]
        assert item["widget"] == "keyvalue"
        assert item["value"] == aliases


class TestMemoryRetentionToggle:
    """Фаза 2 (T-755): memory.infinite_retention в GET /api/config, POST-toggle
    админом, moderator — 403 (нет секции memory), секция «Память» в ролях."""

    def _get_item(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        return {i["key"]: i for i in resp.json()["items"]} \
            ["memory.infinite_retention"]

    def test_get_returns_bool_with_metadata(self, client):
        item = self._get_item(client)
        assert item["value"] is False
        assert item["type"] == "bool"
        assert item["category"] == "memory"
        assert item["group"] == "memory_infinite"
        assert item["title"] == "Бессрочное хранение памяти"
        assert "бессрочно" in (item["description"] or "").lower()
        assert item["secret"] is False
        groups = {g["id"]: g for g in
                  client.get("/api/config", headers=_hdr(ADMIN_ID))
                  .json()["groups"]}
        assert groups["memory_infinite"]["title"] == "Бессрочное хранение"
        assert groups["memory_infinite"]["category"] == "memory"

    def test_post_admin_toggles_true(self, client):
        resp = client.post(
            "/api/config",
            json={"items": [{"key": "memory.infinite_retention",
                             "value": True}]},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json() == {"updated": ["memory.infinite_retention"]}
        assert client.cache.get("memory.infinite_retention") is True
        assert self._get_item(client)["value"] is True

    def test_post_moderator_denied_403(self, client):
        resp = client.post(
            "/api/config",
            json={"items": [{"key": "memory.infinite_retention",
                             "value": True}]},
            headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_roles_tree_has_memory_section(self, client):
        resp = client.get("/api/roles/tree", headers=_hdr(ADMIN_ID))
        body = resp.json()
        sections = {s["id"]: s for s in body["sections"]}
        memory = sections["memory"]
        assert memory["title"] == "Память"
        keys = [p["key"] for p in memory["params"]]
        assert "memory.infinite_retention" in keys
        item = next(p for p in memory["params"]
                    if p["key"] == "memory.infinite_retention")
        assert item["type"] == "bool"


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


class TestPromptsValidationRound4:
    """Раунд 4 (T-719/T-720, FR-E2/FR-E3, spec 3.5.2): серверный 422 пустых
    prompts/content; промпты с кавычками/переносами/HTML — байт-в-байт;
    пустая '' у models — валидна (ступень отключена)."""

    PROMPT_KEY = "prompts.factcheck_system_prompt"

    def test_prompt_with_quotes_newlines_html_saved_byte_for_byte(self, client):
        text = ('Проверяй факты. Отвечай с "кавычками" и «ёлочками».\n'
                "Вторая строка: <b>жирный</b> & спецсимволы — как есть.\n"
                "Третья: 'одинарные' и `обратные` кавычки.")
        resp = client.post("/api/config",
                           json={"items": [{"key": self.PROMPT_KEY,
                                            "value": text}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"updated": [self.PROMPT_KEY]}
        assert client.cache.get(self.PROMPT_KEY) == text

    def test_empty_prompt_422(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": self.PROMPT_KEY,
                                            "value": ""}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422
        assert "не может быть пустым" in resp.json()["detail"]
        assert client.cache.get(self.PROMPT_KEY) is None

    def test_whitespace_prompt_422(self, client):
        resp = client.post("/api/config",
                           json={"items": [{"key": self.PROMPT_KEY,
                                            "value": "   \n\t  "}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422
        assert "не может быть пустым" in resp.json()["detail"]

    def test_null_prompt_value_422(self, client):
        """null → _coerce ValueError (существующий путь) → 422."""
        resp = client.post("/api/config",
                           json={"items": [{"key": self.PROMPT_KEY,
                                            "value": None}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422

    def test_empty_model_string_is_valid(self, client):
        """AC-E2: пустая '' у models.video_primary_model → 200 (ступень
        отключена — легитимный сценарий youtube_summarizer_service)."""
        key = "models.video_primary_model"
        resp = client.post("/api/config",
                           json={"items": [{"key": key, "value": ""}]},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200, resp.text
        assert client.cache.get(key) == ""

    def test_prompts_tab_render_str_and_category(self, client):
        """Фронт знает category=prompts и type=str (для тоста E1)."""
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        items = {i["key"]: i for i in resp.json()["items"]}
        item = items.get(self.PROMPT_KEY)
        # сид-ключа в фикстуре нет — items содержит только строки PG-фикстуры;
        # при отсутствии — проверяем каталог напрямую (фронт-контракт).
        from services.param_catalog import get_by_pg_key
        spec = get_by_pg_key(self.PROMPT_KEY)
        assert spec is not None and spec.type == "str"
        assert spec.category == "prompts"


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

    def test_get_admins_display_enrichment_fail_open(self, client):
        """10.10 (п.5, ADR-1010-3): /api/admins обогащается display_name/
        photo_file_id через global_user_display_info; без бота — None
        (fail-open) и старые поля на месте."""
        resp = client.get("/api/admins", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        for admin in resp.json()["admins"]:
            assert "display_name" in admin
            assert "photo_file_id" in admin
            assert admin["display_name"] is None
            assert admin["photo_file_id"] is None
            assert "role_name" in admin
            assert "added_by" in admin
            assert "created_at" in admin

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

    # ── OD15/T-1141 (раунд 10.5): rename/delete с защитой superuser ──
    def test_delete_superuser_role_403(self, client):
        resp = client.delete("/api/roles/admin", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 403

    def test_delete_unknown_role_404(self, client):
        resp = client.delete("/api/roles/nope", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 404

    def test_rename_superuser_role_403(self, client):
        resp = client.post("/api/roles/admin/rename",
                           json={"new_name": "boss"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 403

    def test_rename_unknown_role_404(self, client):
        resp = client.post("/api/roles/nope/rename",
                           json={"new_name": "x"},
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 404

    def test_rename_forbidden_for_non_global(self, client):
        resp = client.post("/api/roles/moderator/rename",
                           json={"new_name": "mod2"},
                           headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

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

    def test_key_env_name_resolves(self, client):
        """84.20.4: key=SEARCH_MAX_SYMBOLS (env-имя, upper) → 200 + item.name."""
        for raw in ("SEARCH_MAX_SYMBOLS", "search_max_symbols"):
            resp = client.get("/api/debug/config",
                              params={"key": raw},
                              headers=_hdr(ADMIN_ID))
            assert resp.status_code == 200, raw
            body = resp.json()
            assert body["item"]["key"] == "limits.search_max_symbols"
            assert body["item"]["name"] == "SEARCH_MAX_SYMBOLS"

    def test_key_unknown_404(self, client):
        resp = client.get("/api/debug/config",
                          params={"key": "НЕ_СУЩЕСТВУЕТ"},
                          headers=_hdr(ADMIN_ID))
        assert resp.status_code == 404
        assert "не найден" in resp.json()["detail"]

    def test_full_dump_names_present(self, client):
        resp = client.get("/api/debug/config", headers=_hdr(ADMIN_ID))
        items = resp.json()["items"]
        assert items
        by_key = {i["key"]: i for i in items}
        assert by_key["limits.search_max_symbols"]["name"] \
            == "SEARCH_MAX_SYMBOLS"
        assert by_key["keys.groq_api_key"]["name"] == "GROQ_API_KEY"
        # pg-флаг для content-ключа
        assert by_key["content.info_how_it_works"].get("pg_only") is True


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
        # Редизайн 10.5 (T-1098): анимированные градиенты на токенах эталона.
        assert "@property --grad-angle" in text          # OD4: inherits:false
        assert "animation: grad-drift" in text           # page-wash (T2)
        assert "conic-gradient(from var(--grad-angle)" in text
        assert "@media (prefers-reduced-motion: reduce)" in text
        assert "--surface-1:#161616" in text             # палитра эталона
        assert "backdrop-filter: blur(20px) saturate(140%)" in text
        assert "Telegram.WebApp" in text
        # Инцидент «Миниапп открыт без Telegram-контекста»: официальный
        # SDK ОБЯЗАН грузиться — без telegram-web-app.js window.Telegram
        # отсутствует → initData никогда не появляется → authLocked.
        assert ('<script src="https://telegram.org/js/'
                'telegram-web-app.js"></script>') in text

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

    def test_index_version_query_param(self, client):
        """84.21.2 + 10.8 (R10.8-5): app.js И woff2-субсет подключаются с
        ?v=__APP_VERSION__ → реальная версия (cache-bust субсета шрифта,
        который отдаётся с max-age=86400)."""
        resp = client.get("/web/")
        text = resp.text
        assert "__APP_VERSION__" not in text              # заглушка заменена
        assert "/web/app.js?v=2.54.0" in text
        assert "/static/fonts/material-symbols-rounded.woff2?v=2.54.0" in text
        # URL субсета с версией реально отдаётся 200 (query не ломает static).
        font = client.get(
            "/static/fonts/material-symbols-rounded.woff2?v=2.54.0")
        assert font.status_code == 200
        assert font.content[:4] == b"wOF2"

    def test_cache_control_headers(self, client):
        """84.21.2: html/js — no-cache; остальное — public max-age."""
        html = client.get("/web/")
        app_js = client.get("/web/app.js")
        assert "no-cache" in html.headers["cache-control"]
        assert "no-cache, no-store, must-revalidate" in app_js.headers["cache-control"]

    def test_cache_control_on_304(self, client):
        """Блокер ревью: Cache-Control одинаков на 200 и 304
        (If-None-Match + ETag → 304, заголовок НЕ теряется)."""
        first = client.get("/web/app.js")
        etag = first.headers.get("etag")
        assert etag, "Starlette должен отдавать ETag"
        resp = client.get("/web/app.js", headers={"If-None-Match": etag})
        assert resp.status_code == 304
        assert "no-cache, no-store, must-revalidate" \
            in resp.headers.get("cache-control", "")
        # обычные файлы (без no-cache) — тоже header на 304
        image = None  # картинок нет в web/ — проверяем только js-кейс


class TestParamPermissionFlagsApi:
    """Ре-дизайн 10.2, BUG-6 (spec §3.2.4): GET/PUT/DELETE
    /api/access/param_permissions — новая форма {view_roles, edit_roles};
    legacy-тело принимается; глобальный админ в массивах → 422."""

    def test_config_items_carry_flag_lists(self, client):
        """GET /api/config: items несут view_roles/edit_roles (новая форма);
        legacy-поля (view_min_role/edit_min_role/hidden_from_local) НЕ
        отдаются (spec §3.2.4)."""
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        items = {i["key"]: i for i in resp.json()["items"]}
        it = items["limits.search_max_symbols"]
        assert it["view_roles"] == ["moderator", "local_admin"]
        assert it["edit_roles"] == ["local_admin"]
        assert "view_min_role" not in it
        assert "edit_min_role" not in it
        assert "hidden_from_local" not in it
        key = items["keys.groq_api_key"]
        assert key["view_roles"] == [] and key["edit_roles"] == []
        # content-ключ (не-секрет, общая категория-дефолт) — флаги как в §3.2.3
        cat = items["content.info_how_it_works"]
        assert cat["view_roles"] == ["moderator", "local_admin"]
        assert cat["edit_roles"] == ["local_admin"]

    def test_param_permissions_get_empty_matrix(self, client):
        resp = client.get("/api/access/param_permissions", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert "limits.search_max_symbols" in items
        m = items["limits.search_max_symbols"]
        assert m["view_roles"] == ["moderator", "local_admin"]
        assert m["edit_roles"] == ["local_admin"]
        assert m["default"] is True
        assert "view_min_role" not in m
        assert "hidden_from_local" not in m
        kk = items["keys.llm_api_key"]
        assert kk["view_roles"] == [] and kk["edit_roles"] == []

    def test_param_permissions_matrix_metadata_and_coverage(self, client):
        """OD10/T-1130 + Reviewer D4: матрица покрывает ВСЕ категорийные
        параметры и группируется по СЕКЦИЯМ мини-аппа (tab/tab_title)."""
        from services.param_catalog import REGISTRY
        categorized = [s for s in REGISTRY.values() if s.category is not None]
        resp = client.get("/api/access/param_permissions", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == len(categorized) == 372
        m = items["limits.search_max_symbols"]
        assert m["category"] == "limits"
        assert m["group"] == "limits_search"
        assert m["group_title"] and m["title"]
        assert "group_order" in m and "secret" in m
        # D4: секция = config-вкладка мини-аппа, а не внутренняя категория.
        assert m["tab"] == "mod_search"
        assert m["tab_title"] == "Поиск"
        assert items["models.llm_base_url"]["tab"] == "llm_providers"
        assert items["models.llm_base_url"]["tab_title"] == "LLM Провайдеры"
        assert items["keys.groq_api_key"]["tab"] == "llm_providers"
        assert items["prompts.summary_system_prompt"]["tab"] == "prompts"
        assert items["prompts.summary_system_prompt"]["tab_title"] == "Промпты"
        # у каждого параметра секция-метаданные присутствуют (key есть)
        for key, it in items.items():
            assert "tab" in it and "tab_title" in it, key

    def test_put_flags_new_shape(self, client):
        from services import access as access_srv
        access_srv.reset_param_permissions_cache()
        resp = client.put(
            "/api/access/param_permissions/limits.search_max_symbols",
            headers=_hdr(ADMIN_ID),
            json={"view_roles": ["moderator"], "edit_roles": ["local_admin"]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["view_roles"] == ["moderator", "local_admin"]  # view |= edit
        assert body["edit_roles"] == ["local_admin"]

    def test_put_legacy_body_normalized_response(self, client):
        resp = client.put(
            "/api/access/param_permissions/limits.search_max_symbols",
            headers=_hdr(ADMIN_ID),
            json={"view_min_role": "moderator",
                  "edit_min_role": "moderator",
                  "hidden_from_local": True})
        assert resp.status_code == 200
        body = resp.json()
        # legacy хранится как есть, но ответ — нормализованная новая форма
        # (view: rank>=moderator минус local_admin-folding → [moderator],
        # затем union edit_roles: «запись подразумевает чтение»)
        assert body["view_roles"] == ["moderator", "local_admin"]
        assert body["edit_roles"] == ["moderator", "local_admin"]

    def test_put_global_admin_flag_422(self, client):
        resp = client.put(
            "/api/access/param_permissions/limits.search_max_symbols",
            headers=_hdr(ADMIN_ID),
            json={"view_roles": ["global_admin"], "edit_roles": ["user"]})
        assert resp.status_code == 422
        resp2 = client.put(
            "/api/access/param_permissions/limits.search_max_symbols",
            headers=_hdr(ADMIN_ID),
            json={"view_roles": ["user"], "edit_roles": ["global_admin"]})
        assert resp2.status_code == 422

    def test_put_forbidden_for_non_global_admin(self, client):
        resp = client.put(
            "/api/access/param_permissions/limits.search_max_symbols",
            headers=_hdr(MODERATOR_ID),
            json={"view_roles": ["user"], "edit_roles": ["user"]})
        assert resp.status_code == 403
        resp2 = client.delete(
            "/api/access/param_permissions/limits.search_max_symbols",
            headers=_hdr(MODERATOR_ID))
        assert resp2.status_code == 403

    def test_delete_resets_to_default(self, client):
        """DELETE оверрайда → 200 {reset: true}; нет строки → 404."""
        resp = client.delete(
            "/api/access/param_permissions/limits.search_max_symbols",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json() == {"key": "limits.search_max_symbols",
                               "reset": True}

    def test_delete_404_without_row(self, client, monkeypatch):
        from services import access as access_srv
        async def _gone(*args, **kwargs):
            return False
        monkeypatch.setattr(access_srv, "delete_param_permission", _gone)
        resp = client.delete(
            "/api/access/param_permissions/limits.search_max_symbols",
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 404


# ═══ F-14 (dm-user-settings, T-956, spec §3.2) — DM-контракты ═══════════════

def _dmh(user_id: int) -> dict:
    """TMA-заголовки + X-Chat-Id = user_id (свой ЛС)."""
    return {**_hdr(user_id), "X-Chat-Id": str(user_id)}


class TestDmScopeApi:
    """DM-скоуп (X-Chat-Id = свой user.id): синтез DM-строки в списках,
    GET /api/config 200 (ctx.is_dm, keys скрыты, models read-only),
    POST → ensure_scope_profile перед записью (409 в фейке — профиля нет),
    чужой ЛС (даже global admin) → 403, keys/own — только владелец."""

    def test_access_chats_has_dm_row_for_plain_user(self, client):
        resp = client.get("/api/access/chats", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        rows = resp.json()
        dm = [r for r in rows if r.get("is_dm")]
        assert len(dm) == 1
        row = dm[0]
        assert row["chat_id"] == USER_ID
        assert row["title"] == "Личные сообщения"
        assert row["access"] == "dm"
        assert row["is_active"] is True
        assert row["photo_file_id"] is None

    def test_access_chats_has_dm_row_for_global_admin(self, client):
        resp = client.get("/api/access/chats", headers=_hdr(ADMIN_ID))
        rows = resp.json()
        assert any(r.get("is_dm") and r["chat_id"] == ADMIN_ID
                   for r in rows)

    def test_access_me_includes_dm_chat(self, client):
        resp = client.get("/api/access/me", headers=_hdr(USER_ID))
        assert resp.status_code == 200
        chats = resp.json()["chats"]
        assert {"chat_id": USER_ID, "role": "dm"} in chats

    def test_get_config_dm_own_200(self, client):
        resp = client.get("/api/config", headers=_dmh(USER_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["ctx"]["is_dm"] is True
        assert body["ctx"]["is_local_admin"] is False
        items = {i["key"]: i for i in body["items"]}
        # keys.* скрыты (канон «не global admin»), models — read-only справка
        assert "keys.llm_api_key" not in items
        assert "keys.groq_api_key" not in items
        assert "models.llm_timeout" in items
        assert "limits.search_max_symbols" in items

    def test_get_config_dm_foreign_dm_403(self, client):
        """Глобальный админ в ЧУЖОМ ЛС → 403 (can_access_chat False)."""
        resp = client.get("/api/config",
                          headers={**_hdr(ADMIN_ID),
                                   "X-Chat-Id": str(USER_ID)})
        assert resp.status_code == 403

    def test_post_config_dm_ensures_profile_first(self, client):
        """POST в свой ЛС: ensure_scope_profile(dm=True) вызывается ПЕРЕД
        записью (профиля в фейке нет → 409 «профиля нет», не 500)."""
        payload = {"items": [{"key": "prompts.direct_chat_system_prompt",
                              "value": "промпт своих ЛС"}]}
        resp = client.post("/api/config", json=payload,
                           headers=_dmh(USER_ID))
        assert resp.status_code == 409
        conn = client.cache.pg.pool._conn
        inserts = [args for sql, args in conn.queries
                   if "INSERT INTO chat_profiles" in sql]
        assert len(inserts) >= 1
        chat_id, auto_enabled, is_active, _params, gates_opt_in = inserts[0]
        assert chat_id == USER_ID
        assert auto_enabled is False          # LoreWorker не тронет
        assert is_active is True
        assert gates_opt_in is False

    def test_post_config_dm_keys_422(self, client):
        """keys.* в POST /api/config → 422 (существующий канон, НЕ 403)."""
        payload = {"items": [{"key": "keys.llm_api_key", "value": "sk-xx"}]}
        resp = client.post("/api/config", json=payload,
                           headers=_dmh(USER_ID))
        assert resp.status_code == 422

    def test_keys_own_dm_owner_allowed(self, client):
        resp = client.get("/api/config/keys/own",
                          headers=_dmh(USER_ID))
        assert resp.status_code == 200
        assert resp.json() == {"keys": []}

    def test_keys_own_foreign_dm_403(self, client):
        resp = client.get("/api/config/keys/own",
                          headers={**_hdr(ADMIN_ID),
                                   "X-Chat-Id": str(USER_ID)})
        assert resp.status_code == 403

    def test_delete_chat_param_dm_foreign_403(self, client):
        resp = client.delete("/api/config/chat/limits.chat_cooldown_seconds",
                             headers={**_hdr(ADMIN_ID),
                                      "X-Chat-Id": str(USER_ID)})
        assert resp.status_code == 403


# ═══ Раунд 10.4 (ревью-фиксы): select-виджет температуры end-to-end ═══════

class TestSelectWidgetTemperature:
    """B-7/B-8 + ревью-фикс: GET отдаёт select_options/select_labels;
    POST валидирует опцию (422 в ОБЕИХ ветках); не-select — None."""

    def test_get_config_serializes_temperature_options(self, client):
        resp = client.get("/api/config", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        items = {i["key"]: i for i in resp.json()["items"]}
        t = items["limits.chat_temperature_preset_default"]
        assert t["widget"] == "select"
        assert t["select_options"] == ["precise", "balanced", "chatty"]
        assert t["select_labels"] == ["Точный", "Сбалансированный",
                                      "Болтливый"]
        # не-select ключи — None (не пустой список!)
        assert items["limits.search_max_symbols"]["select_options"] is None
        assert items["limits.search_max_symbols"]["select_labels"] is None

    def test_post_global_valid_option_200(self, client):
        payload = {"items": [{"key": "limits.chat_temperature_preset_default",
                              "value": "chatty"}]}
        resp = client.post("/api/config", json=payload, headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert "limits.chat_temperature_preset_default" in \
            resp.json()["updated"]

    def test_post_global_invalid_option_422(self, client):
        payload = {"items": [{"key": "limits.chat_temperature_preset_default",
                              "value": "супер_болтливый"}]}
        resp = client.post("/api/config", json=payload, headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422
        assert "недопустимая опция" in resp.text

    def test_post_per_chat_invalid_option_422(self, client):
        """Per-chat ветка — та же валидация (инвариант B-9)."""
        payload = {"items": [{"key": "limits.chat_temperature_preset_default",
                              "value": "bad"}]}
        resp = client.post("/api/config", json=payload, headers=_dmh(USER_ID))
        assert resp.status_code == 422
        assert "недопустимая опция" in resp.text

    def test_post_per_chat_valid_option_passes_validation(self, client):
        """Валидная опция в per-chat ветке проходит валидацию и уходит в
        запись (фейк-профиля нет → 409 конфликт, НЕ 422)."""
        payload = {"items": [{"key": "limits.chat_temperature_preset_default",
                              "value": "balanced"}]}
        resp = client.post("/api/config", json=payload, headers=_dmh(USER_ID))
        assert resp.status_code == 409
        assert "недопустимая опция" not in resp.text


class TestKeyHistoryApi:
    """B1/OD8 + OD12/OD19 (T-1128/T-1129/T-1140): leak-safe история ключей."""

    def test_key_history_allowlist(self, client):
        resp = client.get("/api/status/key-history", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"version", "generated_at", "providers"}
        for prov in body["providers"]:
            assert set(prov.keys()) <= {
                "module_id", "module_title", "provider", "model", "samples"}
            for sample in prov["samples"]:
                assert set(sample.keys()) == {"ts", "ok", "http_status"}

    def test_status_llm_has_module_metadata(self, client):
        resp = client.get("/api/status", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        llm = resp.json()["llm"]
        assert llm, "llm[] непуст"
        for card in llm:
            assert card["module_id"] and card["provider"]
            assert "model_source" in card
            assert set(card["key"].keys()) <= {"configured", "last4"}


class TestLlmTestEndpoint:
    """Раунд 10.6 (T-1210/A4): POST /api/llm/test — global admin, rate-limit, R17."""

    BODY = {"block": "direct_main", "base_url": "https://api.example/v1",
            "model": "m-1", "api_key": "sk-super-secret"}

    def test_non_global_admin_403(self, client):
        resp = client.post("/api/llm/test", json=self.BODY,
                           headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_admin_ok_then_rate_limit_429(self, client, monkeypatch):
        from services import llm_probe
        from web.api import routes

        async def fake_probe(block, base_url, model, api_key):
            return {"ok": True, "http_status": 200, "latency_ms": 7,
                    "model": model}

        monkeypatch.setattr(llm_probe, "probe_block", fake_probe)
        routes.reset_llm_test_rate_limit()
        resp = client.post("/api/llm/test", json=self.BODY,
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True and body["http_status"] == 200
        assert "sk-super-secret" not in resp.text   # R17: ключ не эхо
        resp2 = client.post("/api/llm/test", json=self.BODY,
                            headers=_hdr(ADMIN_ID))
        assert resp2.status_code == 429

    def test_error_sanitized(self, client, monkeypatch):
        from services import llm_probe
        from web.api import routes

        async def fake_probe(block, base_url, model, api_key):
            return {"ok": False, "http_status": 401, "latency_ms": 3,
                    "model": model,
                    "error": llm_probe.sanitize_error(
                        "bad key sk-super-secret", api_key)}

        monkeypatch.setattr(llm_probe, "probe_block", fake_probe)
        routes.reset_llm_test_rate_limit()
        resp = client.post("/api/llm/test", json=self.BODY,
                           headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "sk-super-secret" not in resp.text

    @pytest.mark.parametrize("block", [
        "direct_main", "direct_fallback", "transcribe_groq",
        "transcribe_openrouter", "video_summary_openrouter", "search_keys",
        "search_keys:tavily", "search_keys:exa"])
    def test_each_block_reaches_probe(self, client, monkeypatch, block):
        """MAJOR-1: каждый (сетевой) блок реально доходит до probe_block."""
        from services import llm_probe
        from web.api import routes

        seen = {}

        async def fake_probe(b, base_url, model, api_key):
            seen["block"] = b
            return {"ok": True, "http_status": 200, "latency_ms": 1,
                    "model": model}

        monkeypatch.setattr(llm_probe, "probe_block", fake_probe)
        routes.reset_llm_test_rate_limit()
        resp = client.post(
            "/api/llm/test",
            json={"block": block, "base_url": "https://api.example/v1",
                  "model": "m", "api_key": "k"},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert seen["block"] == block

    def test_malformed_does_not_echo_api_key(self, client):
        """R10.6-3 (R17): Pydantic-422 не должен эхоить api_key (`input`)."""
        secret = "sk-SUPER-SECRET-LEAK-123"
        resp = client.post(
            "/api/llm/test",
            json={"block": "direct_main", "api_key": [secret]},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422
        assert secret not in resp.text
        body = json.dumps(resp.json())
        assert "input" not in body
        assert "ctx" not in body
        # loc/msg сохранены — клиенту понятно, ЧТО не так.
        assert resp.json()["detail"]

    def test_generic_validation_422_sanitized(self, client):
        """R10.6-3: обработчик app-wide — любой 422 без `input`/`ctx`."""
        secret = "sk-GENERIC-LEAK-999"
        resp = client.post(
            "/api/config",
            json={"items": {"secret": secret}},
            headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422
        assert secret not in resp.text
        body = json.dumps(resp.json())
        assert "input" not in body
        assert "ctx" not in body
