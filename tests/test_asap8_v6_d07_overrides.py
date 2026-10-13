"""D07 (ASAP 8 v6, Wave C) — карта per-chat overrides (global-view popover).

v5 §9B.2/§9B.3 + v6 §C D07: global view должен показывать, КАКИЕ чаты
переопределили параметр, с быстрыми действиями. Backend-контракт
GET /api/config/overrides-map:

  (a) global admin видит ВСЕ чаты с override (группы + свои ЛС);
  (b) `?key=` — только заданный ключ;
  (c) RBAC: не-админ (rank 1, без грантов) → 403; чат без гранта не виден
      (настройки других чатов не утекают);
  (d) local admin (только chat-grant) видит СВОЙ чат, чужие — нет;
  (e) каталог-фильтр: только per_chat-ключи; секреты/keys.* НЕ возвращаются
      НИКОГДА (R17) — легаси-мусор в chat_params наружу не идёт;
  (f) PG down → 503 (fail-closed, не пустой список);
  (g) source='chat' у каждой строки (owner-контракт v5 §9B.1).

TEST-LIFECYCLE: CONTRACT owner=D07 (web/api/routes.py::config_overrides_map)
"""
import json
import time
import hashlib
import hmac
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod
from web.api import routes as routes_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079
USER_ID = 999999999
LOCAL_ADMIN_ID = 424242424

CHAT_A = -1002001
CHAT_B = -1002002
CHAT_FOREIGN = -1002003
DM_ADMIN = ADMIN_ID            # свои ЛС глобального админа
KEY_LIMITS = "limits.search_max_symbols"
KEY_FLAGS = "memory.infinite_retention"
KEY_LEGACY_NOT_PER_CHAT = "models.llm_timeout"     # models — строго глобально
KEY_SECRET_LEGACY = "keys.llm_api_key"             # секрет — никогда наружу


def make_init_data(user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


# chat_admins-гранты: (chat_id, telegram_id) → role_name
_GRANTS = {
    (CHAT_A, LOCAL_ADMIN_ID): "local_admin",
    (CHAT_FOREIGN, LOCAL_ADMIN_ID): None,   # чужой чат — гранта нет
}


class _Conn:
    """Fake-пул: bot_* для ConfigCache + chat_profiles с эмуляцией LEFT JOIN
    chat_admins (роль конкретного telegram_id подставляется на чтении)."""

    def __init__(self, *, profile_rows=()):
        self._settings_rows = [
            {"key": KEY_LIMITS, "value": 8000, "category": "limits",
             "updated_at": "2026-08-30T01:00:00+00:00"},
            {"key": KEY_FLAGS, "value": False, "category": "memory",
             "updated_at": None},
            {"key": KEY_LEGACY_NOT_PER_CHAT, "value": 30.0,
             "category": "models", "updated_at": None},
            {"key": KEY_SECRET_LEGACY, "value": "sk_deepseek_123456",
             "category": "keys", "updated_at": None},
        ]
        self._role_rows = [
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "moderator",
             "permissions": {"sections": ["limits"],
                             "actions": ["control.restart"]},
             "is_custom": False},
            {"role_name": "user", "permissions": {}, "is_custom": False},
        ]
        self._admin_rows = [
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
            {"telegram_id": MODERATOR_ID, "role_name": "moderator",
             "added_by": ADMIN_ID,
             "created_at": "2026-08-30T00:00:01+00:00"},
        ]
        self._profile_rows = list(profile_rows)
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        if "chat_profiles" in sql:
            # эмуляция LEFT JOIN chat_admins по telegram_id = $1
            tid = args[0] if args else None
            out = []
            for r in self._profile_rows:
                role = _GRANTS.get((r["chat_id"], tid))
                row = dict(r)
                row["chat_role"] = role
                out.append(row)
            return out
        return []

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        if "chat_admins" in sql and "chat_profiles" not in sql:
            # CHAT_ADMIN_ROLE_SQL: WHERE chat_id = $1 AND telegram_id = $2
            role = _GRANTS.get((args[0], args[1]))
            return {"role_name": role} if role else None
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

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "UPDATE 0"


class _Pool:
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


class _Pg:
    def __init__(self, conn):
        self._pool = _Pool(conn)
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


def _profile(chat_id: int, overrides: dict) -> dict:
    """Форма строки реального SQL: chat_id + jsonb `overrides` (asyncpg
    отдаёт jsonb как str) + chat_role из LEFT JOIN (подставляется на
    чтении)."""
    return {"chat_id": chat_id,
            "overrides": json.dumps(overrides),
            "chat_role": None}


PROFILES = [
    _profile(CHAT_A, {KEY_LIMITS: False, KEY_SECRET_LEGACY: "sk_leak_9876",
                      KEY_LEGACY_NOT_PER_CHAT: 60.0}),
    _profile(CHAT_B, {KEY_LIMITS: 12000, KEY_FLAGS: True}),
    # свои ЛС админа: overrides в DM-скоупе
    _profile(DM_ADMIN, {KEY_LIMITS: 5000}),
    # чужие ЛС (позитивный id ≠ админ) — не видит НИКТО, кроме владельца
    _profile(1312, {KEY_LIMITS: 1}),
    # свои ЛС plain user 777000 (видит только их, §F-14)
    _profile(777000, {KEY_LIMITS: 1}),
    # чужой чат БЕЗ override — не попадает в выдачу по определению
    _profile(CHAT_FOREIGN, {}),
]


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(
            INFO_TEXT_FILE=str(tmp_path / "info_text.md"),
            ADMIN_USER_ID=ADMIN_ID))
    conn = _Conn(profile_rows=PROFILES)
    cache = ConfigCache(pg=_Pg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as test_client:
        test_client.cache = cache
        test_client.conn = conn
        yield test_client


class TestOverridesMap:
    def test_global_admin_sees_all_chats_and_own_dm(self, client):
        resp = client.get("/api/config/overrides-map", headers=_hdr())
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        by_chat = {}
        for it in items:
            by_chat.setdefault(it["chat_id"], []).append(it)
        # (a) обе группы + свои ЛС; чужие ЛС и чат без override — нет
        assert CHAT_A in by_chat and CHAT_B in by_chat
        assert DM_ADMIN in by_chat
        assert 1312 not in by_chat            # чужие ЛС не утекают
        assert CHAT_FOREIGN not in by_chat    # нет override — строки нет
        # (g) source='chat' у каждой строки
        assert all(it["source"] == "chat" for it in items)
        # (e) R17: секрет-ключ и не-per_chat легаси НЕ возвращаются никогда
        keys_out = {it["key"] for it in items}
        assert KEY_SECRET_LEGACY not in keys_out
        assert KEY_LEGACY_NOT_PER_CHAT not in keys_out
        # значения per_chat-ключей честные
        a = {it["key"]: it["value"] for it in by_chat[CHAT_A]}
        assert a[KEY_LIMITS] is False
        b = {it["key"]: it["value"] for it in by_chat[CHAT_B]}
        assert b[KEY_LIMITS] == 12000 and b[KEY_FLAGS] is True
        # access/title
        assert by_chat[CHAT_A][0]["access"] == "global_admin"
        assert by_chat[CHAT_A][0]["is_dm"] is False
        dm_row = by_chat[DM_ADMIN][0]
        assert dm_row["is_dm"] is True and dm_row["access"] == "dm"
        assert dm_row["chat_title"] == "Личные сообщения"
        # title-фолбэк для групп (Bot API в тесте недоступен)
        assert by_chat[CHAT_A][0]["chat_title"] == f"Чат {CHAT_A}"

    def test_key_filter_returns_only_requested_key(self, client):
        resp = client.get("/api/config/overrides-map",
                          params={"key": KEY_LIMITS}, headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["key"] == KEY_LIMITS
        items = body["items"]
        assert items and all(it["key"] == KEY_LIMITS for it in items)
        assert {it["chat_id"] for it in items} == {
            CHAT_A, CHAT_B, DM_ADMIN}

    def test_plain_user_403(self, client):
        resp = client.get("/api/config/overrides-map", headers=_hdr(USER_ID))
        assert resp.status_code == 403

    def test_plain_user_own_dm_override_visible(self, client):
        """Plain user видит ТОЛЬКО свои ЛС (F-14) — и не 403, если строка
        есть; чужие чаты по-прежнему не утекают."""
        own_dm = 777000
        resp = client.get("/api/config/overrides-map",
                          headers=_hdr(own_dm))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(it["chat_id"] == own_dm for it in items)

    def test_plain_user_without_own_rows_403(self, client):
        resp = client.get("/api/config/overrides-map",
                          headers=_hdr(777001))   # своих override нет
        assert resp.status_code == 403

    def test_local_admin_grant_sees_only_his_chat(self, client):
        """(d) chat-grant local_admin: свой чат виден, чужие — нет."""
        resp = client.get("/api/config/overrides-map",
                          headers=_hdr(LOCAL_ADMIN_ID))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items, "свой чат с override обязан быть виден"
        assert {it["chat_id"] for it in items} == {CHAT_A}
        assert all(it["access"] == "local_admin" for it in items)

    def test_global_moderator_sees_nothing(self, client):
        """Глобальный moderator (rank 2): доступ к эндпоинту есть, но чатов
        с грантами нет → пустой список (паритет с /api/access/chats)."""
        resp = client.get("/api/config/overrides-map",
                          headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_pg_down_503(self, client, monkeypatch):
        class _Broken:
            @property
            def pool(self):
                return None

        monkeypatch.setattr(client.cache, "_pg", _Broken())
        resp = client.get("/api/config/overrides-map", headers=_hdr())
        assert resp.status_code == 503

    def test_query_failure_503(self, client, monkeypatch):
        class _PoolBoom:
            def acquire(self):
                class _CM:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *exc):
                        return False

                    async def fetch(self, sql, *a):
                        raise RuntimeError("pg gone")

                return _CM()

        class _PgBoom:
            pool = _PoolBoom()

        monkeypatch.setattr(client.cache, "_pg", _PgBoom())
        resp = client.get("/api/config/overrides-map", headers=_hdr())
        assert resp.status_code == 503

    def test_overrides_rows_never_leak_other_chats_for_dm_owner(self, client):
        """F-14: global admin в ЧУЖОМ ЛС → 403 (existing gate); карта чужих
        ЛС не отдаётся и админу (1312 отсутствует — см. тест (a)). Здесь
        фиксируем контракт SQL: запрос идёт в chat_profiles c telegram_id
        текущего пользователя (гранты считаются на сервере, не клиенте)."""
        client.get("/api/config/overrides-map", headers=_hdr())
        map_queries = [q for q, _ in client.conn.queries
                       if "chat_profiles" in q and "bot_settings" not in q]
        assert map_queries, "ожидается запрос карты overrides"
        assert "chat_admins" in map_queries[-1]


class TestContractGuard:
    def test_owner_contract_global_save_never_touches_chat_override(self):
        """REGRESSION-пин (v5 §9B.1): глобальный save идёт в bot_settings
        (cache.set_many), chat override живёт в chat_profiles.overrides —
        разные хранилища; `_post_config_global` не принимает chat_id.
        Пин защищает ownership-границу: путь записи глобального значения
        физически не имеет доступа к chat override."""
        import inspect
        src = inspect.getsource(routes_mod._post_config_global)
        assert "chat_params" not in src, (
            "глобальный save не должен писать chat_params (owner-contract)")
        assert "set_chat_params" not in src
