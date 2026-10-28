"""P0 corrective 28.10.2026 — админ-тумблер «Exact Match Cache» (Модули →
Умный кэш) не сохраняется: тост «Сохранено 0 из 1; не сохранено:
Exact Match Cache» (прод 2.58.139).

Воспроизводит ТОЧНЫЙ payload TMA (saveModalEdits → persistItems →
POST /api/config): body = {items:[{key: 'flags.smart_cache_enabled',
value: bool}], updated_at} — глобальный scope (updated_at=null, без
X-Chat-Id) и chat-scope (X-Chat-Id + updated_at чата).

Контракты (REGRESSION):
1. POST /api/config для flags.smart_cache_enabled — 200, значение сохранено
   (и глобальный слой, и per-chat override).
2. Эффективный рантайм: hot.get('flags.smart_cache_enabled') отражает
   сохранённое значение БЕЗ рестарта; SmartCache._active(dedup=False)
   переключается; SmartCache.set() начинает писать.
3. Чтение UI: GET /api/config (глобальный и chat-scope) показывает
   актуальное состояние тумблера.
"""
import json
import datetime
import re
import sqlite3
import types

import pytest
from fastapi.testclient import TestClient

import services.chat_params as chat_params
import services.hot_config as hot_config
from services.config_cache import ConfigCache
from services.smart_cache import get_smart_cache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
ADMIN_ID = 5885953495
CHAT = -100460000000      # групповой чат (отрицательный id; положительный — DM)

FLAG_KEY = "flags.smart_cache_enabled"


def make_init_data(user_id: int = ADMIN_ID) -> str:
    import hashlib
    import hmac
    import time
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(),
                         hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + \
        f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


class _FakeConn:
    """bot_settings/roles/admins в памяти (паттерн test_webapp_api)."""

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


def _admin_cache() -> ConfigCache:
    conn = _FakeConn(
        # flags-строка как в проде: сид категорий создаёт row для ВСЕХ флагов
        # (pg_db.SEED_CATEGORIES включает flags; здесь — сам целевой ключ).
        settings_rows=[
            {"key": FLAG_KEY, "value": False, "category": "flags",
             "updated_at": "2026-10-28T00:00:00+00:00"},
            {"key": "limits.smart_cache_ttl_seconds", "value": 1800,
             "category": "limits", "updated_at": None},
        ],
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
        ],
    )
    return ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)


class _FakeChatParams:
    """chat_params in-memory (паттерн test_budget_overrides_merge)."""

    def __init__(self):
        self.store: dict[int, dict] = {}
        self._seq = 0

    def _root(self, chat_id) -> dict:
        return self.store.setdefault(int(chat_id), {
            "v": 1, "overrides": {}, "gates": {}, "keys": {},
            "perm_overrides": {}, "meta": {},
            "updated_at": "2026-10-28T00:00:00+00:00"})

    def seed(self, chat_id, *, overrides=None):
        root = self._root(chat_id)
        if overrides is not None:
            root["overrides"] = dict(overrides)
        return root

    async def get_all_chat_params(self, chat_id, pg=None):
        import copy
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
        import copy
        root = self._root(chat_id)
        current = root.get("updated_at")
        if expected_updated_at is not None and \
                expected_updated_at != current:
            raise chat_params.ChatParamsConflict(int(chat_id), current)
        for ns in ("overrides", "gates", "keys", "perm_overrides", "meta"):
            if ns in patch and isinstance(patch[ns], dict):
                root[ns] = copy.deepcopy(patch[ns])
        root["v"] = patch.get("v", 1)
        self._seq += 1
        root["updated_at"] = f"2026-10-28T10:00:{self._seq:02d}+00:00"
        return copy.deepcopy(root)


@pytest.fixture
def webapp(monkeypatch, tmp_path):
    """TestClient + in-memory chat_params + сброс hot после теста."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    cache = _admin_cache()
    cp = _FakeChatParams()
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
        test_client.cp = cp
        hot_config.set_config_cache(cache)
        yield test_client
    hot_config.set_config_cache(None)


# ── 1. Тумблер сохраняется (TMA payload) ────────────────────────────────────

def test_toggle_save_global_roundtrip(webapp):
    """Глобальный scope: persistItems шлёт updated_at=null, без X-Chat-Id."""
    resp = webapp.post("/api/config",
                       json={"items": [{"key": FLAG_KEY, "value": True}],
                             "updated_at": None},
                       headers=_hdr())
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == [FLAG_KEY]
    assert webapp.cache.get(FLAG_KEY) is True
    items = {i["key"]: i for i in webapp.get(
        "/api/config", headers=_hdr()).json()["items"]}
    assert items[FLAG_KEY]["value"] is True


def test_toggle_save_chat_scope_roundtrip(webapp):
    """Chat-scope: X-Chat-Id + updated_at → override чата, 200."""
    chat_root = webapp.cp.seed(CHAT)
    resp = webapp.post("/api/config",
                       json={"items": [{"key": FLAG_KEY, "value": True}],
                             "updated_at": chat_root["updated_at"]},
                       headers=_hdr() | {"X-Chat-Id": str(CHAT)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == [FLAG_KEY]
    assert webapp.cp.store[CHAT]["overrides"][FLAG_KEY] is True


# ── 2. Эффективный рантайм (hot, без рестарта) ─────────────────────────────

def test_toggle_effective_runtime_hot_after_save(webapp):
    """После глобального сохранения hot.get отражает новое значение;
    SmartCache._active(dedup=False) переключается; set() пишет."""
    assert hot_config.get(FLAG_KEY, False) is False
    resp = webapp.post("/api/config",
                       json={"items": [{"key": FLAG_KEY, "value": True}]},
                       headers=_hdr())
    assert resp.status_code == 200, resp.text
    assert hot_config.get(FLAG_KEY, False) is True
    sc = get_smart_cache()
    assert sc._active(dedup=False) is True


# ── 3. Чтение UI показывает актуальное состояние ────────────────────────────

def test_admin_reads_actual_state_after_chat_save(webapp):
    """GET с X-Chat-Id после chat-сохранения возвращает override-значение
    (chat_source='chat') — иначе тумблер возвращает старое состояние."""
    chat_root = webapp.cp.seed(CHAT)
    resp = webapp.post("/api/config",
                       json={"items": [{"key": FLAG_KEY, "value": True}],
                             "updated_at": chat_root["updated_at"]},
                       headers=_hdr() | {"X-Chat-Id": str(CHAT)})
    assert resp.status_code == 200, resp.text
    items = {i["key"]: i for i in webapp.get(
        "/api/config", headers=_hdr() | {"X-Chat-Id": str(CHAT)}
    ).json()["items"]}
    it = items[FLAG_KEY]
    assert it["value"] is True
    assert it["chat_source"] == "chat"


# ═══ ИНТЕГРАЦИЯ: реальный chat_params поверх temp-SQLite (паттерн
# test_p0_persistfix_speech_chat_scope). Тот же TMA-флоу, что в проде:
# loadConfig (GET с X-Chat-Id) → тумблер → persistItems (POST с updated_at,
# полученным из GET). Ловит рассинхрон optimistic-токена/путей записи,
# который фейк chat_params маскирует. ═══════════════════════════════════════

import sqlite3  # noqa: E402

_SQLITE_DDL = (
    """CREATE TABLE bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        category TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE chat_profiles (
        chat_id INTEGER PRIMARY KEY,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        chat_params TEXT DEFAULT '{}',
        gates_opt_in INTEGER DEFAULT 0,
        auto_enabled INTEGER DEFAULT 1,
        is_active INTEGER DEFAULT 1)""",
    """CREATE TABLE chat_lore_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        field TEXT,
        changed_by INTEGER,
        old_value TEXT,
        new_value TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE chat_admins (
        chat_id INTEGER,
        telegram_id INTEGER,
        role_name TEXT,
        added_by INTEGER,
        PRIMARY KEY (chat_id, telegram_id))""",
    """CREATE TABLE bot_roles (
        role_name TEXT PRIMARY KEY,
        permissions TEXT,
        is_custom INTEGER,
        role_type TEXT)""",
    """CREATE TABLE bot_admins (
        telegram_id INTEGER PRIMARY KEY,
        role_name TEXT,
        added_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
)


class _SqliteConn:
    """asyncpg-совместимый conn над sqlite3 (сокращённый shim persistfix)."""

    _CAST = re.compile(r"::\w+")
    _PARAM = re.compile(r"\$(\d+)")
    _JSON_COLS = ("value", "chat_params", "permissions")

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self.now_increment = 0

    def _translate(self, sql: str, args: tuple):
        order: list[int] = []

        def _repl(match: "re.Match[str]") -> str:
            order.append(int(match.group(1)))
            return "?"

        tsql = self._CAST.sub("", sql)
        tsql = self._PARAM.sub(_repl, tsql)
        targs = tuple(
            args[n - 1].isoformat(sep=" ")
            if isinstance(args[n - 1], datetime.datetime) else args[n - 1]
            for n in order)
        return tsql, targs

    def _row(self, cur) -> dict | None:
        row = cur.fetchone()
        cur.close()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        out = dict(zip(cols, row))
        for col in self._JSON_COLS:
            if isinstance(out.get(col), str):
                try:
                    out[col] = json.loads(out[col])
                except ValueError:
                    pass
        return out

    def _prepare(self, sql: str, args: tuple) -> tuple[str, tuple]:
        # updated_at = now() → монотонный литерал-таймстамп (секундная
        # гранулярность SQLite сделала бы подряд-записи неотличимыми;
        # продовой PG now() полон микросекунд).
        self.now_increment += 1
        total = 12 * 3600 + self.now_increment
        stamp = (f"2026-10-28 {total // 3600:02d}:"
                 f"{(total % 3600) // 60:02d}:{total % 60:02d}"
                 f".{self.now_increment * 1000:06d}")
        sql = sql.replace("updated_at = now()",
                          f"updated_at = '{stamp}'", 1)
        # datetime-аргументы → 'YYYY-MM-DD HH:MM:SS' (формат CURRENT_TIMESTAMP
        # SQLite; PG сравнивает timestamptz по значению — шим эмулирует это
        # единым текстовым форматом).
        return self._translate(sql, args)

    async def execute(self, sql: str, *args):
        if "pg_notify" in sql or "advisory" in sql:
            return "SELECT 1"
        tsql, targs = self._prepare(sql, args)
        self._db.execute(tsql, targs)
        return "OK"

    async def fetchrow(self, sql: str, *args):
        if "advisory" in sql:
            return None
        tsql, targs = self._prepare(sql, args)
        return self._row(self._db.execute(tsql, targs))

    async def fetch(self, sql: str, *args):
        tsql, targs = self._prepare(sql, args)
        cur = self._db.execute(tsql, targs)
        cols = [d[0] for d in cur.description]
        rows = []
        for raw in cur.fetchall():
            out = dict(zip(cols, raw))
            for col in self._JSON_COLS:
                if isinstance(out.get(col), str):
                    try:
                        out[col] = json.loads(out[col])
                    except ValueError:
                        pass
            rows.append(out)
        cur.close()
        return rows

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                conn._db.execute("BEGIN")
                return conn

            async def __aexit__(self, exc_type, exc, tb):
                if exc_type is not None:
                    conn._db.execute("ROLLBACK")
                else:
                    conn._db.execute("COMMIT")
                return False

        return _Tx()


class _SqlitePool:
    def __init__(self, db):
        self.conn = _SqliteConn(db)

    @property
    def pool(self):
        return self

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _SqlitePg:
    def __init__(self, db):
        self.pool = _SqlitePool(db)

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


@pytest.fixture
def webapp_sqlite(monkeypatch, tmp_path):
    """Реальный ConfigCache + реальный chat_params (ChatParamsCache) поверх
    temp-SQLite; групповой чат с профилем. ТМА-флоу loadConfig→save."""
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    db = sqlite3.connect(":memory:", isolation_level=None,
                         check_same_thread=False)
    for stmt in _SQLITE_DDL:
        db.execute(stmt)
    db.execute(
        "INSERT INTO bot_roles (role_name, permissions, is_custom, role_type) "
        "VALUES ('admin', ?, 0, 'global_admin')",
        (json.dumps({"wildcard": True}),))
    db.execute("INSERT INTO bot_admins (telegram_id, role_name, added_by) "
               "VALUES (?, 'admin', NULL)", (ADMIN_ID,))
    db.execute(
        "INSERT INTO chat_profiles (chat_id, chat_params) VALUES (?, ?)",
        (CHAT, json.dumps({"v": 1, "overrides": {}, "meta": {}})))
    # bot_settings: сид флага как в проде
    db.execute(
        "INSERT INTO bot_settings (key, value, category) VALUES (?, ?, ?)",
        (FLAG_KEY, json.dumps(False), "flags"))
    db.execute(
        "INSERT INTO bot_settings (key, value, category) VALUES (?, ?, ?)",
        ("limits.smart_cache_ttl_seconds", json.dumps(1800), "limits"))

    pg = _SqlitePg(db)
    cache = ConfigCache(pg=pg, retry_attempts=1, retry_delay=0)
    cache._pg_available = True
    cache._initialized = True
    _run(cache._load_all())         # реальная загрузка из хранилища
    chat_params.set_chat_params_cache(chat_params.ChatParamsCache(pg))
    app = create_app(cache)
    try:
        with TestClient(app) as test_client:
            test_client.cache = cache
            test_client.db = db
            test_client.sqlite_conn = pg.pool.conn
            hot_config.set_config_cache(cache)
            yield test_client
    finally:
        hot_config.set_config_cache(None)
        chat_params.set_chat_params_cache(None)
        db.close()


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _sqlite_now(conn) -> str:
    row = conn._db.execute(
        "SELECT updated_at FROM chat_profiles WHERE chat_id = ?",
        (CHAT,)).fetchone()
    return row[0]


def test_tma_flow_get_then_save_chat_scope_sqlite(webapp_sqlite):
    """Честный TMA-флоу: GET /api/config (X-Chat-Id) → POST с тем же
    updated_at → 200, override записан, повторный GET показывает ON."""
    client = webapp_sqlite
    chat_headers = _hdr() | {"X-Chat-Id": str(CHAT)}
    # 1) loadConfig
    first = client.get("/api/config", headers=chat_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    token = body.get("updated_at")
    assert token, "GET должен вернуть updated_at профиля (optimistic-токен)"
    # 2) тумблер ON + «Сохранить изменения»
    resp = client.post("/api/config",
                       json={"items": [{"key": FLAG_KEY, "value": True}],
                             "updated_at": token},
                       headers=chat_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == [FLAG_KEY]
    # 3) перечитать UI
    second = client.get("/api/config", headers=chat_headers).json()
    items = {i["key"]: i for i in second["items"]}
    assert items[FLAG_KEY]["value"] is True
    assert items[FLAG_KEY]["chat_source"] == "chat"
    stored = json.loads(client.db.execute(
        "SELECT chat_params FROM chat_profiles WHERE chat_id = ?",
        (CHAT,)).fetchone()[0])
    assert stored["overrides"][FLAG_KEY] is True


def test_tma_flow_toggle_off_then_on_sqlite(webapp_sqlite):
    """Два сохранения подряд (OFF→ON→OFF) — как реальный владелец: каждый
    следующий POST берёт свежий токен из предыдущего ответа."""
    client = webapp_sqlite
    chat_headers = _hdr() | {"X-Chat-Id": str(CHAT)}
    token = client.get("/api/config", headers=chat_headers).json()["updated_at"]
    r1 = client.post("/api/config",
                     json={"items": [{"key": FLAG_KEY, "value": True}],
                           "updated_at": token}, headers=chat_headers)
    assert r1.status_code == 200, r1.text
    token2 = r1.json()["updated_at"] or client.get(
        "/api/config", headers=chat_headers).json()["updated_at"]
    r2 = client.post("/api/config",
                     json={"items": [{"key": FLAG_KEY, "value": False}],
                           "updated_at": token2}, headers=chat_headers)
    assert r2.status_code == 200, r2.text
    stored = json.loads(client.db.execute(
        "SELECT chat_params FROM chat_profiles WHERE chat_id = ?",
        (CHAT,)).fetchone()[0])
    assert stored["overrides"][FLAG_KEY] is False


# ═══ ROOT-CAUSE РЕГРЕССИИ: конкурентная запись → устаревший optimistic-токен.
# До фикса: 409 + провал тумблера («Сохранено 0 из 1», прод 2.58.139).
# После фикса: одна ограниченная попытка перечитывает СВЕЖИЙ root и мержит
# патч поверх — чужие ключи не теряются, тумблер применяется. ═══════════════

def test_stale_token_toggle_still_applies_and_preserves_concurrent_write(
        webapp_sqlite):
    """Конкурентная запись сдвинула updated_at ПОСЛЕ loadConfig → тумблер со
    старым токеном применяется (200), чужая конкурентная правка сохранена."""
    import asyncio
    client = webapp_sqlite
    chat_headers = _hdr() | {"X-Chat-Id": str(CHAT)}
    # 1) UI читает конфиг (токен T1)
    token = client.get("/api/config", headers=chat_headers).json()["updated_at"]
    # 2) «Бот»/вторая вкладка пишет ДРУГОЙ ключ (updated_at → T2)
    from services import chat_params as cp_mod
    asyncio.run(cp_mod.set_chat_params(
        CHAT, {"overrides": {"limits.search_max_symbols": 555},
               "meta": {"note": "concurrent"}},
        changed_by=None, pg=client.cache.pg))
    # 3) Владелец переключает тумблер со СТАРЫМ токеном T1
    resp = client.post("/api/config",
                       json={"items": [{"key": FLAG_KEY, "value": True}],
                             "updated_at": token}, headers=chat_headers)
    assert resp.status_code == 200, resp.text
    stored = json.loads(client.db.execute(
        "SELECT chat_params FROM chat_profiles WHERE chat_id = ?",
        (CHAT,)).fetchone()[0])
    # тумблер применён
    assert stored["overrides"][FLAG_KEY] is True
    # чужая конкурентная правка НЕ потеряна (merge на свежий root)
    assert stored["overrides"]["limits.search_max_symbols"] == 555


def test_missing_group_profile_first_write_ensures_and_saves(webapp_sqlite):
    """Групповой чат без chat_profiles-строки (join-событие потеряно):
    первая запись создаёт профиль (как DM-ветка F-14) и сохраняет тумблер.
    До фикса: вечный мусорный 409 «профиля нет»."""
    client = webapp_sqlite
    chat_headers = _hdr() | {"X-Chat-Id": str(CHAT)}
    client.db.execute("DELETE FROM chat_profiles WHERE chat_id = ?", (CHAT,))
    resp = client.post("/api/config",
                       json={"items": [{"key": FLAG_KEY, "value": True}],
                             "updated_at": None}, headers=chat_headers)
    assert resp.status_code == 200, resp.text
    row = client.db.execute(
        "SELECT chat_params FROM chat_profiles WHERE chat_id = ?",
        (CHAT,)).fetchone()
    assert row is not None
    assert json.loads(row[0])["overrides"][FLAG_KEY] is True


# ═══ Эффективный рантайм SmartCache.get: рубильник — горячая точка (T-619),
# тот же паттерн, что get_dedup/_sweep_ttl; settings остаётся дефолтом. ═══

class _Cfg:
    def __init__(self, values):
        self._v = dict(values)

    def get(self, key, default=None):
        return self._v.get(key, default)


def test_smart_cache_get_follows_hot_flag(tmp_path, monkeypatch):
    """hot ON при settings OFF → get обслуживает; hot OFF при settings ON →
    get None (рубильник из админки работает в обе стороны)."""
    import services.hot_config as hot
    from services.smart_cache import SmartCache

    async def _noop_sweep(self):
        return 60

    monkeypatch.setattr(SmartCache, "_sweep_ttl", _noop_sweep)
    sc = SmartCache()
    sc._db = None

    async def _fake_ensure_db():
        return object()          # _read не должен вызываться при OFF

    monkeypatch.setattr(sc, "_ensure_db", _fake_ensure_db)

    async def _fail_read(key, ttl_seconds):   # pragma: no cover
        raise AssertionError("read при OFF не должен выполняться")

    monkeypatch.setattr(sc, "_read", _fail_read)

    # settings OFF (конфест-дефолт) + hot ON
    hot.set_config_cache(_Cfg({"flags.smart_cache_enabled": True,
                               "limits.smart_cache_ttl_seconds": 60}))
    try:
        assert hot.get("flags.smart_cache_enabled", False) is True

        async def _ok_read(key, ttl_seconds):
            return "cached-answer"

        monkeypatch.setattr(sc, "_read", _ok_read)
        # event loop для get
        import asyncio
        assert asyncio.run(sc.get("k")) == "cached-answer"

        # hot OFF при settings ON
        monkeypatch.setattr("services.smart_cache.settings",
                            types.SimpleNamespace(
                                SMART_CACHE_ENABLED=True,
                                SMART_CACHE_TTL_SECONDS=60),
                            raising=False)
        hot.set_config_cache(_Cfg({"flags.smart_cache_enabled": False}))
        assert asyncio.run(sc.get("k")) is None
    finally:
        hot.set_config_cache(None)
