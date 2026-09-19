"""Раунд 10.24 (F20, T-2354…T-2357) — merge per-chat ЗНАЧЕНИЙ в
`POST /api/config` (+ `X-Chat-Id`).

Первопричина (ADR-1024-21): `web/api/routes.py` брал базу merge из
`root["perm_overrides"]` (матрица прав) вместо `root["overrides"]` (значения)
и полностью перезаписывал namespace `overrides`. Одиночный save из мини-аппа
(клиент шлёт ОДИН ключ за POST) стирал все прочие per-chat значения — у
целевого чата `-1002661910336` исчезали 8 seed-ключей, включая бюджет `-1`
(безлимит) → глобальный cap → заглушка «нет ключа».

Тесты гоняют РЕАЛЬНЫЙ роут `post_config`/`get_config`/`delete_chat_param`
через TestClient; подменяется только хранилище `services.chat_params`
(in-memory) — как в `tests/test_chat_settings_seed_round1019.py`.

Покрытие (spec §7):
  (a) два последовательных save — оба ключа целы;
  (b) seed-overrides (8 ключей, в т.ч. `-1`) выживают после UI-save;
  (c) паритет с DELETE;
  (d) `perm_overrides` не утекает в `overrides`, матрица прав применяется;
  (e) `updated_at`/409 и GET-метка;
  (f) `per_chat=false` (глобальный путь) не задевает per-chat;
  (g) GET показывает сохранённое (chat_source="chat", корректный global_value);
  (h) идемпотентность/«пустой» повтор — без history-строки;
  (i) пустой/некорректный ввод → 422.
"""
import copy
import hashlib
import hmac
import json
import time
import types
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import access as access_srv
from services import chat_params
from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
ADMIN_ID = 5885953495
CHAT = -1002661910336

# per_chat-ключи (limits.* не секретны → per_chat=True).
K1 = "limits.chat_cooldown_seconds"            # float
K2 = "limits.chat_context_budget_tokens"       # int
K3 = "limits.chat_thread_max_tokens"           # int
K_NEW = "limits.search_max_symbols"            # int
K_BUDGET = "limits.chat_global_key_budget_requests"   # int (seed, -1)
GLOBAL_KEY = "models.llm_timeout"              # per_chat=False

SEED_OVERRIDES = json.loads(
    Path("config/chat_settings_seed.json").read_text(encoding="utf-8")
)["chats"][0]["overrides"]


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
    return {"X-Telegram-Init-Data": make_init_data(user_id),
            "X-Chat-Id": str(CHAT)}


# ── PG/ConfigCache фейк (зеркало tests/test_webapp_api.py) ──────────────────

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
                return self

            async def __aexit__(self, *exc):
                return False

        return _Tx()

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
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


# ── in-memory chat_params фейк ──────────────────────────────────────────────

def _default_root() -> dict:
    return {"v": 1, "overrides": {}, "gates": {}, "keys": {},
            "perm_overrides": {}, "meta": {},
            "updated_at": "2026-09-20T10:00:00+00:00"}


class _FakeChatParams:
    """Хранилище chat_params: namespace-семантика как в `set_chat_params`
    (namespace заменяется ЦЕЛИКОМ, прочие сохраняются; history — только при
    изменении json)."""

    def __init__(self):
        self.store: dict[int, dict] = {}
        self.set_calls: list[int] = []
        self.history: list[dict] = []
        self._seq = 0

    def _root(self, chat_id) -> dict:
        return self.store.setdefault(int(chat_id), _default_root())

    def seed(self, chat_id, *, overrides=None, perm_overrides=None,
             meta=None, updated_at=None):
        root = self._root(chat_id)
        if overrides is not None:
            root["overrides"] = copy.deepcopy(overrides)
        if perm_overrides is not None:
            root["perm_overrides"] = copy.deepcopy(perm_overrides)
        if meta is not None:
            root["meta"] = copy.deepcopy(meta)
        if updated_at is not None:
            root["updated_at"] = updated_at
        return root

    async def get_all_chat_params(self, chat_id, pg=None):
        return copy.deepcopy(self._root(chat_id))

    async def get_chat_updated_at(self, chat_id):
        return self._root(chat_id).get("updated_at")

    async def ensure_scope_profile(self, chat_id, *, dm, pg=None):
        self._root(chat_id)
        return True

    async def set_chat_params(self, chat_id, patch, *, changed_by=None,
                              expected_updated_at=None, pg=None,
                              history_field="chat_params",
                              record_history=True):
        root = self._root(chat_id)
        current = root.get("updated_at")
        if expected_updated_at is not None and expected_updated_at != current:
            raise chat_params.ChatParamsConflict(int(chat_id), current)
        ns_names = ("overrides", "gates", "keys", "perm_overrides", "meta")
        old_json = json.dumps({n: root.get(n) for n in ns_names},
                              sort_keys=True, ensure_ascii=False)
        for ns in ns_names:
            if ns in patch and isinstance(patch[ns], dict):
                root[ns] = copy.deepcopy(patch[ns])
        root["v"] = patch.get("v", 1)
        new_json = json.dumps({n: root.get(n) for n in ns_names},
                              sort_keys=True, ensure_ascii=False)
        if record_history and old_json != new_json:
            self.history.append({"chat_id": int(chat_id),
                                 "field": history_field,
                                 "changed_by": changed_by})
        self._seq += 1
        root["updated_at"] = f"2026-09-20T10:00:{self._seq:02d}+00:00"
        self.set_calls.append(int(chat_id))
        return copy.deepcopy(root)


@pytest.fixture
def webapp(monkeypatch, tmp_path):
    """TestClient на реальных роутах + in-memory chat_params."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    conn = _FakeConn(
        settings_rows=[
            {"key": K1, "value": 30.0, "category": "limits",
             "updated_at": "2026-09-20T00:00:00+00:00"},
            {"key": K2, "value": 4000, "category": "limits",
             "updated_at": None},
            {"key": K3, "value": 2000, "category": "limits",
             "updated_at": None},
            {"key": K_BUDGET, "value": 100, "category": "limits",
             "updated_at": None},
            {"key": K_NEW, "value": 8000, "category": "limits",
             "updated_at": None},
            {"key": GLOBAL_KEY, "value": 30.0, "category": "models",
             "updated_at": None},
        ],
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "user", "permissions": {}, "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-09-20T00:00:00+00:00"},
        ],
    )
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    cp = _FakeChatParams()
    access_srv.reset_param_permissions_cache()
    monkeypatch.setattr(chat_params, "get_all_chat_params",
                        cp.get_all_chat_params)
    monkeypatch.setattr(chat_params, "set_chat_params", cp.set_chat_params)
    monkeypatch.setattr(chat_params, "get_chat_updated_at",
                        cp.get_chat_updated_at)
    monkeypatch.setattr(chat_params, "ensure_scope_profile",
                        cp.ensure_scope_profile)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield types.SimpleNamespace(client=test_client, cp=cp, cache=cache)


def _post(webapp, key, value, *, updated_at=None):
    payload = {"items": [{"key": key, "value": value}]}
    if updated_at is not None:
        payload["updated_at"] = updated_at
    return webapp.client.post("/api/config", json=payload,
                              headers=_hdr())


class TestPerChatOverridesMerge:
    # (a) два последовательных save — оба ключа целы
    def test_two_sequential_saves_preserve_all_keys(self, webapp):
        webapp.cp.seed(CHAT, overrides={K1: 11.0})
        resp1 = _post(webapp, K2, 22)
        assert resp1.status_code == 200, resp1.text
        assert resp1.json()["updated"] == [K2]
        resp2 = _post(webapp, K3, 33)
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["updated"] == [K3]
        overrides = webapp.cp.store[CHAT]["overrides"]
        assert overrides == {K1: 11.0, K2: 22, K3: 33}, overrides

    # (b) seed-overrides (в т.ч. -1) выживают после UI-save
    def test_seed_overrides_survive_ui_save(self, webapp):
        webapp.cp.seed(CHAT, overrides=dict(SEED_OVERRIDES))
        resp = _post(webapp, K_NEW, 7777)
        assert resp.status_code == 200, resp.text
        overrides = webapp.cp.store[CHAT]["overrides"]
        for key, value in SEED_OVERRIDES.items():
            assert overrides.get(key) == value, (key, overrides.get(key))
        assert overrides[K_BUDGET] == -1        # безлимит не потерян
        assert overrides[K_NEW] == 7777
        assert len(overrides) == len(SEED_OVERRIDES) + 1

    # (c) паритет с DELETE
    def test_delete_parity_removes_exactly_one(self, webapp):
        webapp.cp.seed(CHAT, overrides={K1: 11.0})
        assert _post(webapp, K2, 22).status_code == 200
        assert _post(webapp, K3, 33).status_code == 200
        resp = webapp.client.delete(f"/api/config/chat/{K2}",
                                    headers=_hdr())
        assert resp.status_code == 200, resp.text
        overrides = webapp.cp.store[CHAT]["overrides"]
        assert overrides == {K1: 11.0, K3: 33}, overrides
        # повторный DELETE того же → 404
        again = webapp.client.delete(f"/api/config/chat/{K2}",
                                     headers=_hdr())
        assert again.status_code == 404

    # (d) perm_overrides не утекает в overrides и по-прежнему используется
    def test_perm_overrides_not_leaked_and_matrix_used(
            self, webapp, monkeypatch):
        perm = {K2: {"view_roles": ["moderator"],
                     "edit_roles": ["moderator"]}}
        webapp.cp.seed(CHAT, overrides={K3: 999}, perm_overrides=perm)
        seen: dict = {}
        real = access_srv.effective_matrix

        def _spy(pg_key, db_override=None, chat_override=None):
            seen[pg_key] = chat_override
            return real(pg_key, db_override, chat_override)

        monkeypatch.setattr(access_srv, "effective_matrix", _spy)
        resp = _post(webapp, K2, 7)
        assert resp.status_code == 200, resp.text
        overrides = webapp.cp.store[CHAT]["overrides"]
        # значение ключа = 7, НЕ матрица прав; K3 цел
        assert overrides == {K3: 999, K2: 7}, overrides
        # perm_overrides без изменений
        assert webapp.cp.store[CHAT]["perm_overrides"] == perm
        # в effective_matrix пришёл именно chat_override из perm_overrides
        assert seen[K2] == perm[K2]

    # (d') матрица прав по-прежнему гейтит запись (403)
    def test_permission_gate_still_blocks_403(self, webapp, monkeypatch):
        monkeypatch.setattr(access_srv, "can_edit_param",
                            lambda ctx, matrix: False)
        resp = _post(webapp, K2, 7)
        assert resp.status_code == 403, resp.text
        assert webapp.cp.store.get(CHAT, {}).get("overrides", {}) == {}

    # (e) updated_at / 409
    def test_updated_at_conflict_and_ok(self, webapp):
        webapp.cp.seed(CHAT, overrides={}, updated_at="T0")
        bad = _post(webapp, K2, 22, updated_at="WRONG")
        assert bad.status_code == 409, bad.text
        assert bad.json()["detail"]["code"] == "conflict"
        assert webapp.cp.store[CHAT]["overrides"] == {}
        current = webapp.cp.store[CHAT]["updated_at"]
        ok = _post(webapp, K2, 22, updated_at=current)
        assert ok.status_code == 200, ok.text
        assert webapp.cp.store[CHAT]["overrides"] == {K2: 22}

    # (f) глобальный путь не задевает per-chat
    def test_global_path_untouched_per_chat(self, webapp):
        webapp.cp.seed(CHAT, overrides={K1: 5.0})
        resp = webapp.client.post(
            "/api/config",
            json={"items": [{"key": GLOBAL_KEY, "value": 45.0}]},
            headers={"X-Telegram-Init-Data": make_init_data(ADMIN_ID)})
        assert resp.status_code == 200, resp.text
        assert webapp.cp.store[CHAT]["overrides"] == {K1: 5.0}

    # (g) GET показывает сохранённое
    def test_get_shows_saved_chat_value(self, webapp):
        webapp.cp.seed(CHAT, overrides={K1: 11.0})
        resp = webapp.client.get("/api/config", headers=_hdr())
        assert resp.status_code == 200, resp.text
        items = {i["key"]: i for i in resp.json()["items"]}
        item = items[K1]
        assert item["chat_source"] == "chat"
        assert item["value"] == 11.0
        assert item["global_value"] == 30.0
        assert item["per_chat"] is True

    # (h) идемпотентность: повтор того же значения — без history-строки
    def test_idempotent_repeat_no_history(self, webapp):
        # meta уже с нашим updated_by → первый POST — истинный no-op
        webapp.cp.seed(CHAT, overrides={K2: 22},
                       meta={"updated_by": ADMIN_ID})
        first = _post(webapp, K2, 22)
        assert first.status_code == 200, first.text
        assert webapp.cp.history == []          # json не изменился
        history_len = len(webapp.cp.history)
        second = _post(webapp, K2, 22)
        assert second.status_code == 200, second.text
        assert len(webapp.cp.history) == history_len
        assert webapp.cp.store[CHAT]["overrides"] == {K2: 22}

    # (i) пустой / некорректный ввод
    def test_invalid_inputs_422(self, webapp):
        empty = webapp.client.post("/api/config", json={"items": []},
                                   headers=_hdr())
        assert empty.status_code == 422
        unknown = _post(webapp, "limits.no_such_key_xyz", 1)
        assert unknown.status_code == 422
        secret = _post(webapp, "keys.llm_api_key", "sk-x")
        assert secret.status_code == 422
