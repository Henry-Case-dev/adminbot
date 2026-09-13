"""Раунд 10.14 (F2 persona-storage-core, spec §5) — тесты /api/persona.

TestClient + ConfigCache-стаб (как test_webapp_api). bot_persona-функции —
monkeypatch (маршрут-уровень: scope, RBAC, 422/403/409/503, health).
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services import bot_persona
from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_PERSONA_TESTS"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
PERSONA_EDITOR_ID = 555000111
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
    def __init__(self):
        self.queries = []

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        if "bot_roles" in sql:
            return [
                {"role_name": "admin", "permissions": {"wildcard": True},
                 "is_custom": False},
                {"role_name": "moderator",
                 "permissions": {"sections": ["limits"], "actions": []},
                 "is_custom": False},
                # H2: точечное право edit_persona (регистрируется в ACTIONS_TREE).
                {"role_name": "persona_editor",
                 "permissions": {"actions": ["edit_persona"]},
                 "is_custom": True},
                {"role_name": "user", "permissions": {}, "is_custom": False},
            ]
        if "bot_admins" in sql:
            return [{"telegram_id": ADMIN_ID, "role_name": "admin",
                     "added_by": None, "created_at": None},
                    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
                     "added_by": ADMIN_ID, "created_at": None},
                    {"telegram_id": PERSONA_EDITOR_ID,
                     "role_name": "persona_editor",
                     "added_by": ADMIN_ID, "created_at": None}]
        if "bot_settings" in sql:
            return [{"key": "flags.persona_enabled", "value": True,
                     "category": "flags", "updated_at": None}]
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
def client(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    cache = ConfigCache(pg=_FakePg(_FakeConn()), retry_attempts=1,
                        retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        yield test_client


@pytest.fixture
def calls(monkeypatch):
    """Заглушки bot_persona: фиксируют вызовы, возвращают детерминизм."""
    state = {"saved": [], "deleted": []}

    async def _resolve(chat_id):
        return bot_persona.BotPersona(name="Костик", biography="кот",
                                      overrides="циник", is_aware_ai=True,
                                      scope_chat_id=chat_id,
                                      is_global=chat_id is None,
                                      updated_at="2026-09-13T10:00:00+00:00")

    async def _traits(limit=50, chat_id=None):
        return [{"ts": 1757750400, "text": "шутит", "source": "deep_sleep"}]

    async def _save(chat_id, patch, *, expected_updated_at=None):
        state["saved"].append((chat_id, patch, expected_updated_at))
        return bot_persona.BotPersona(
            name=patch.get("name", "Костик"), biography="",
            overrides="", is_aware_ai=patch.get("is_aware_ai", True),
            scope_chat_id=chat_id, is_global=chat_id is None)

    async def _delete(chat_id):
        state["deleted"].append(chat_id)
        return True

    async def _health():
        return {"traits_count": 3, "last_trait_at": "2026-09-13T00:00:00",
                "extractor_status": "ok", "extractor_last_at": None,
                "last_trait_status": "ok"}

    monkeypatch.setattr(bot_persona, "resolve_bot_persona", _resolve)
    monkeypatch.setattr(bot_persona, "get_traits", _traits)
    monkeypatch.setattr(bot_persona, "save_persona", _save)
    monkeypatch.setattr(bot_persona, "delete_persona", _delete)
    monkeypatch.setattr(bot_persona, "get_persona_health", _health)
    return state


class TestGetPersona:
    def test_global_admin(self, client, calls):
        resp = client.get("/api/persona", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "global"
        assert body["chat_id"] is None
        assert body["is_global"] is True
        assert body["values"]["name"] == "Костик"
        assert body["persona_enabled"] is True
        assert body["updated_at"] == "2026-09-13T10:00:00+00:00"
        assert body["dynamic_traits"][0]["text"] == "шутит"

    def test_chat_scope(self, client, calls):
        resp = client.get(
            "/api/persona",
            headers={**_hdr(ADMIN_ID), "X-Chat-Id": "-100500"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "chat"
        assert body["chat_id"] == -100500

    def test_non_admin_global_403(self, client, calls):
        assert client.get("/api/persona",
                          headers=_hdr(MODERATOR_ID)).status_code == 403

    def test_edit_persona_action_view_global(self, client, calls):
        """R10.14-1: роль с action `edit_persona` читает и global-персону
        (согласовано с PUT global) — глобальный экран «Личность» достижим."""
        resp = client.get("/api/persona", headers=_hdr(PERSONA_EDITOR_ID))
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "global"
        assert body["chat_id"] is None
        assert body["is_global"] is True

    def test_edit_persona_action_view_chat(self, client, calls):
        """R10.14-1: chat-scope читается ролью-редактором (консистентность)."""
        resp = client.get(
            "/api/persona",
            headers={**_hdr(PERSONA_EDITOR_ID), "X-Chat-Id": "-100500"})
        assert resp.status_code == 200
        assert resp.json()["scope"] == "chat"

    def test_edit_persona_view_put_consistency(self, client, calls):
        """R10.14-1: GET/PUT симметричны в обоих скоупах (chat и global)."""
        for headers in (_hdr(PERSONA_EDITOR_ID),
                        {**_hdr(PERSONA_EDITOR_ID), "X-Chat-Id": "-100500"}):
            assert client.put("/api/persona", headers=headers,
                              json={"name": "x"}).status_code == 200
            assert client.get("/api/persona",
                              headers=headers).status_code == 200

    def test_chat_scope_persona_enabled_per_chat(self, client, calls,
                                                 monkeypatch):
        """R10.14-3: per-chat override флага отражается в GET-индикаторе."""
        from services import chat_params

        async def _cp(chat_id, key, default=None):
            assert chat_id == -100500
            return False

        monkeypatch.setattr(chat_params, "get_chat_param", _cp)
        resp = client.get(
            "/api/persona",
            headers={**_hdr(ADMIN_ID), "X-Chat-Id": "-100500"})
        assert resp.status_code == 200
        assert resp.json()["persona_enabled"] is False


class TestPutPersona:
    def test_global_admin_saves(self, client, calls):
        resp = client.put("/api/persona",
                          headers=_hdr(ADMIN_ID),
                          json={"name": "Костик", "is_aware_ai": False})
        assert resp.status_code == 200
        assert calls["saved"][0][0] is None
        assert calls["saved"][0][1] == {"name": "Костик",
                                        "is_aware_ai": False}

    def test_user_forbidden(self, client, calls):
        resp = client.put("/api/persona", headers=_hdr(USER_ID),
                          json={"name": "x"})
        assert resp.status_code == 403

    def test_moderator_chat_forbidden(self, client, calls):
        resp = client.put("/api/persona",
                          headers={**_hdr(MODERATOR_ID),
                                   "X-Chat-Id": "-100500"},
                          json={"name": "x"})
        assert resp.status_code == 403

    def test_edit_persona_action_grants_chat_access(self, client, calls):
        """H2: роль с зарегистрированным action `edit_persona` валидна и
        даёт доступ к правке персоны (override chat-scope)."""
        resp = client.put("/api/persona",
                          headers={**_hdr(PERSONA_EDITOR_ID),
                                   "X-Chat-Id": "-100500"},
                          json={"name": "Новый"})
        assert resp.status_code == 200
        assert calls["saved"][0][0] == -100500

    def test_edit_persona_action_grants_global_access(self, client, calls):
        """H2: action `edit_persona` покрывает и global-скоуп (spec §5)."""
        resp = client.put("/api/persona",
                          headers=_hdr(PERSONA_EDITOR_ID),
                          json={"name": "Новый"})
        assert resp.status_code == 200
        assert calls["saved"][0][0] is None

    def test_too_long_422(self, client, calls):
        resp = client.put("/api/persona", headers=_hdr(ADMIN_ID),
                          json={"biography": "x" * 8193})
        assert resp.status_code == 422

    def test_reset_global_422(self, client, calls):
        resp = client.put("/api/persona", headers=_hdr(ADMIN_ID),
                          json={"reset": True})
        assert resp.status_code == 422

    def test_conflict_409(self, client, monkeypatch, calls):
        async def _boom(chat_id, patch, *, expected_updated_at=None):
            raise bot_persona.PersonaConflict("2026-09-13T10:00:00+00:00")
        monkeypatch.setattr(bot_persona, "save_persona", _boom)
        resp = client.put("/api/persona", headers=_hdr(ADMIN_ID),
                          json={"name": "x",
                                "updated_at": "2000-01-01T00:00:00"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["current_updated_at"] == \
            "2026-09-13T10:00:00+00:00"


class TestDeletePersona:
    def test_reset_chat(self, client, calls):
        resp = client.request(
            "DELETE", "/api/persona",
            headers={**_hdr(ADMIN_ID), "X-Chat-Id": "-100500"})
        assert resp.status_code == 200
        assert calls["deleted"] == [-100500]

    def test_requires_chat_id(self, client, calls):
        resp = client.delete("/api/persona", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 422


class TestPersonaHealth:
    def test_admin_ok(self, client, calls):
        resp = client.get("/api/persona/health", headers=_hdr(ADMIN_ID))
        assert resp.status_code == 200
        assert resp.json()["traits_count"] == 3

    def test_user_forbidden(self, client, calls):
        assert client.get("/api/persona/health",
                          headers=_hdr(USER_ID)).status_code == 403


# ── H1: сквозной optimistic-протокол (без monkeypatch save/resolve) ─────────

class _PersonaConn:
    """Stateful personas-стор: GET отдаёт updated_at, PUT — RETURNING."""

    def __init__(self):
        self.personas: dict = {}
        self._seq = 0

    def _ts(self):
        self._seq += 1
        return f"2026-09-13T12:00:{self._seq:02d}+00:00"

    async def fetchrow(self, sql, *args):
        if "FROM personas" in sql:
            if "is_global = false" in sql:
                return self.personas.get(int(args[0]))
            if "is_global = true" in sql:
                return self.personas.get(None)
        if "INSERT INTO personas" in sql:
            if "VALUES (NULL, true" in sql:
                key, offset = None, 0
            else:
                key, offset = int(args[0]), 1
            self.personas[key] = {
                "name": args[offset], "biography": args[offset + 1],
                "system_prompt_overrides": args[offset + 2],
                "is_aware_ai": args[offset + 3], "updated_at": self._ts()}
            return {"updated_at": self.personas[key]["updated_at"]}
        return None

    async def fetch(self, sql, *args):
        return []

    async def execute(self, sql, *args):
        return "OK"


class _PersonaPool:
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


class TestOptimisticEndToEnd:
    def test_get_put_stale_409_and_fresh_ok(self, client):
        """H1: GET отдаёт токен → PUT с устаревшим токеном → 409; PUT со
        свежим токеном → 200 и новый токен (без monkeypatch save_persona)."""
        conn = _PersonaConn()
        conn.personas[None] = {
            "name": "Костик", "biography": "кот",
            "system_prompt_overrides": "", "is_aware_ai": True,
            "updated_at": "2026-09-13T11:00:00+00:00"}
        bot_persona.set_persona_pool(_PersonaPool(conn))
        try:
            r1 = client.get("/api/persona", headers=_hdr(ADMIN_ID))
            assert r1.status_code == 200
            token = r1.json()["updated_at"]
            assert token == "2026-09-13T11:00:00+00:00"

            r2 = client.put("/api/persona", headers=_hdr(ADMIN_ID),
                            json={"name": "Новый",
                                  "updated_at": "2000-01-01T00:00:00"})
            assert r2.status_code == 409
            assert r2.json()["detail"]["current_updated_at"] == token

            r3 = client.put("/api/persona", headers=_hdr(ADMIN_ID),
                            json={"name": "Новый", "updated_at": token})
            assert r3.status_code == 200
            assert r3.json()["values"]["name"] == "Новый"
            assert r3.json()["updated_at"] != token
        finally:
            bot_persona.reset_persona_pool()
