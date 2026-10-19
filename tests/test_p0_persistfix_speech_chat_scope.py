"""P0 save/init — PERSIST-FIX: реальный путь записи SOUL-1 в chat-скоупе.

TEST-LIFECYCLE: REGRESSION owner=P0-hotfix-2026-10-18/persist §2
(аудит `persistence-audit.md` §3.1–3.5, B4/B5).

До фикса все 10 chat-scope записей «Речи и характера» вызывали
`chat_params.set_chat_params(...)` БЕЗ пула → `ChatLorePgUnavailable`
(`chat_params.py:424`) → UI получал 409 `write_error`/`save_error`, 200
`ok:false`, 503 или 500. Существовавшие контрактные тесты подменяли сам
виновный вызов (`test_soul1_w6_speech_ui.py` monkeypatch set_chat_params),
поэтому дефект не ловился.

Здесь пути записи идут через РЕАЛЬНЫЕ `services.chat_params` /
`ConfigCache` поверх временной SQLite (asyncpg-совместимый shim; конвенция
репо — test_asap42_step3/test_asap8_v6_wa3) и реальный HTTP-стек
`speech_router` с TMA-auth. Никаких подмен `set_chat_params` нет — любая
запись без пула падает так же, как в проде.

RED (на до-фиксовом коде): core text → 503; core meta → 200 ok:false;
reset(mode=chat) → 500; expression/style/humor craft → 409/503; learning →
409 write_error; «сброс в inherited» → ложное «переопределения не было»;
unknown kind → тихая потеря правила при `applied:true`; «пул снят» →
тихий in-memory успех вместо явной ошибки.

GREEN (после фикса): read-after-write из хранилища по каждому типу
настроек (Core full/compact/meta, Expression, Style Policy rules+soft,
Humor craft, Learning, Examples policy), изоляция чатов, честные сбросы и
честная ошибка при недоступном хранилище.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import hmac
import json
import re
import sqlite3
import time
import types
import urllib.parse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import chat_params
from services import prompt_registry as pr
from services.config_cache import ConfigCache
from web.api import deps as deps_mod
from web.api.speech import speech_router

TEST_TOKEN = "123456:P0PERSIST_TOKEN"
ADMIN_ID = 5885953495
CHAT_A = -1007770001
CHAT_B = -1007770002

CORE_KEY = pr.CORE_DOC_KEY                 # character.core
STYLE_KEY = "style.policy"
EXPRESSION_KEY = "character.expression"
HUMOR_CRAFT_KEY = "humor.craft"
SELECTION_KEY = "humor.selection"
HUMOR_FEEDBACK_KEY = "humor.feedback"


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# temp-SQLite asyncpg-совместимый shim (тот же контур, что test_asap8_v6_wa3)
# ═══════════════════════════════════════════════════════════════════════════

_DDL = (
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


def create_schema(db: sqlite3.Connection) -> None:
    for stmt in _DDL:
        db.execute(stmt)


def seed_admin(db: sqlite3.Connection, telegram_id: int = ADMIN_ID,
               role: str = "admin") -> None:
    db.execute(
        "INSERT OR REPLACE INTO bot_roles "
        "(role_name, permissions, is_custom, role_type) "
        "VALUES (?, ?, 0, 'global_admin')",
        (role, json.dumps({"wildcard": True})))
    db.execute(
        "INSERT OR REPLACE INTO bot_admins (telegram_id, role_name, added_by) "
        "VALUES (?, ?, NULL)", (telegram_id, role))


def seed_profile(db: sqlite3.Connection, chat_id: int,
                 overrides: dict | None = None) -> None:
    db.execute(
        "INSERT OR REPLACE INTO chat_profiles (chat_id, chat_params) "
        "VALUES (?, ?)",
        (int(chat_id),
         json.dumps({"v": 1, "overrides": dict(overrides or {})})))


class _SqliteConn:
    """asyncpg-совместимый conn над реальным sqlite3.

    `$N`→`?` с пермутацией аргументов, `::type`-касты срезаются,
    `now()`→CURRENT_TIMESTAMP, `pg_notify`/advisory-lock перехватываются,
    jsonb-колонки возвращаются распарсенными (как asyncpg jsonb-кодек).
    `fail_on` — подстрока SQL, на которой операция падает (инъекция сбоя).
    """

    _CAST = re.compile(r"::\w+")
    _PARAM = re.compile(r"\$(\d+)")
    _NOW = re.compile(r"\bnow\(\)")
    _JSON_COLS = ("value", "chat_params", "permissions")

    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self.notifies: list[str] = []
        self.fail_on: str | None = None
        self.queries: list[tuple[str, tuple]] = []

    def _translate(self, sql: str, args: tuple):
        tsql = self._NOW.sub("CURRENT_TIMESTAMP", sql)
        tsql = self._CAST.sub("", tsql)
        order: list[int] = []

        def _repl(match: "re.Match[str]") -> str:
            order.append(int(match.group(1)))
            return "?"

        tsql = self._PARAM.sub(_repl, tsql)
        targs = tuple(
            args[n - 1].isoformat() if isinstance(args[n - 1], datetime.datetime)
            else args[n - 1]
            for n in order)
        return tsql, targs

    def _maybe_fail(self, sql: str) -> None:
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError(f"injected failure on: {self.fail_on}")

    def _row(self, cur) -> dict | None:
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        cur.close()
        if row is None:
            return None
        out = dict(zip(cols, row))
        for col in self._JSON_COLS:
            if isinstance(out.get(col), str):
                try:
                    out[col] = json.loads(out[col])
                except ValueError:
                    pass
        return out

    async def execute(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        if "pg_notify" in sql:
            self.notifies.append(str(args[0]) if args else "")
            return "SELECT 1"
        if "advisory" in sql:
            return "SELECT 1"
        self._maybe_fail(sql)
        tsql, targs = self._translate(sql, args)
        self._db.execute(tsql, targs)
        return "OK"

    async def fetchrow(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        if "advisory" in sql:
            return None
        self._maybe_fail(sql)
        tsql, targs = self._translate(sql, args)
        return self._row(self._db.execute(tsql, targs))

    async def fetch(self, sql: str, *args):
        self.queries.append((sql, tuple(args)))
        self._maybe_fail(sql)
        tsql, targs = self._translate(sql, args)
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
                    conn._db.execute("ROLLBACK")      # настоящий откат
                else:
                    conn._db.execute("COMMIT")
                return False

        return _Tx()


class SqlitePool:
    """asyncpg-совместимый пул: один реальный sqlite3-коннект."""

    def __init__(self, db: sqlite3.Connection):
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


class SqlitePg:
    """`cache.pg`-двойник: `.pool` — asyncpg-совместимый shim."""

    def __init__(self, db: sqlite3.Connection):
        self.pool = SqlitePool(db)

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


# ── чтение хранилища «как из БД» (приёмка read-after-write) ─────────────────

def stored_overrides(db: sqlite3.Connection, chat_id: int) -> dict:
    row = db.execute(
        "SELECT chat_params FROM chat_profiles WHERE chat_id = ?",
        (int(chat_id),)).fetchone()
    if row is None or not row[0]:
        return {}
    return dict((json.loads(row[0]) or {}).get("overrides") or {})


def stored_setting(db: sqlite3.Connection, key: str):
    row = db.execute("SELECT value FROM bot_settings WHERE key = ?",
                     (key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except ValueError:
        return row[0]


# ── TMA-auth (прецедент test_asap42_step3) ──────────────────────────────────

def make_init_data(token: str, user_id: int = ADMIN_ID) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A", "username": "a"},
                           separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, v) for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def _headers(chat_id: int | None = None,
             user_id: int = ADMIN_ID) -> dict:
    headers = {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN, user_id)}
    if chat_id is not None:
        headers["X-Chat-Id"] = str(int(chat_id))
    return headers


# ── окружение: реальные ConfigCache + chat_params + speech_router ───────────

@pytest.fixture()
def env(monkeypatch):
    db = sqlite3.connect(":memory:", isolation_level=None,
                         check_same_thread=False)
    create_schema(db)
    seed_admin(db)
    seed_profile(db, CHAT_A)
    seed_profile(db, CHAT_B)
    pg = SqlitePg(db)
    cache = ConfigCache(pg=pg)
    _run(cache._load_all())         # реальная загрузка из хранилища
    cache._pg_available = True
    cache._initialized = True
    # Процесс-глобал per-chat слоя — как в bot.py (ChatParamsCache(cache.pg)).
    chat_params.set_chat_params_cache(chat_params.ChatParamsCache(pg))
    # Оси контуров для управления обучением/ремеслом — ON (как в разборе P0).
    monkeypatch.setattr("services.mca_gates.humor_feedback_enabled",
                        lambda: True)
    monkeypatch.setattr("services.mca_gates.humor_craft_enabled", lambda: True)
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    app = FastAPI()
    app.state.cache = cache
    app.include_router(speech_router, prefix="/api")
    client = TestClient(app)
    try:
        yield types.SimpleNamespace(db=db, pg=pg, cache=cache, client=client,
                                    conn=pg.pool.conn)
    finally:
        chat_params.set_chat_params_cache(None)
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Core: текст (full/compact), meta, reset(mode=chat) — 3 отдельных дефекта
# ═══════════════════════════════════════════════════════════════════════════

def test_core_full_text_chat_scope_saved_and_readable(env):
    """Текст Core (chat): реальная запись + reread из хранилища + изоляция."""
    text = "Чат-редакция полной версии характера (PERSIST-FIX)."
    resp = env.client.post(
        f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}",
        headers=_headers(CHAT_A), json={"text": text, "scope": "chat"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["result"]["applied"] is True, body
    # read-after-write из БД (не из ответа API)
    doc = stored_overrides(env.db, CHAT_A)[CORE_KEY]
    assert doc["full_text"] == text
    assert int(doc.get("revision") or 0) >= 1
    # reread через API: чат — источник значения
    core = env.client.get("/api/speech/core",
                          headers=_headers(CHAT_A)).json()
    assert core["inheritance"] == "chat"
    assert core["editions"]["full"]["text"] == text
    assert core["editions"]["full"]["source"] == "chat"
    # изоляция: другой чат не тронут
    assert CORE_KEY not in stored_overrides(env.db, CHAT_B)


def test_core_compact_text_chat_scope_saved(env):
    """Компактная редакция: своё поле документа, независимо от полной."""
    resp = env.client.post(
        f"/api/speech/block/{pr.CORE_COMPACT_BLOCK_ID}",
        headers=_headers(CHAT_A),
        json={"text": "Коротко: по делу.", "scope": "chat"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["applied"] is True
    doc = stored_overrides(env.db, CHAT_A)[CORE_KEY]
    assert doc["compact_text"] == "Коротко: по делу."
    assert doc["detail_level"] == "compact"     # правка редакции делает её действующей
    assert CORE_KEY not in stored_overrides(env.db, CHAT_B)


def test_core_meta_chat_scope_returns_real_status(env):
    """`/core/meta` (chat): 200 только вместе с реальным применением."""
    resp = env.client.post("/api/speech/core/meta", headers=_headers(CHAT_A),
                           json={"detail_level": "compact", "scope": "chat"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True, body            # без искусственного 200 ok:false
    assert body["result"]["applied"] is True
    doc = stored_overrides(env.db, CHAT_A)[CORE_KEY]
    assert doc["detail_level"] == "compact"
    assert CORE_KEY not in stored_overrides(env.db, CHAT_B)


def test_core_reset_chat_mode_returns_200_and_restores_inheritance(env):
    """`reset(mode=chat)`: без 500; честный ok и возврат к наследованию."""
    write = env.client.post(f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}",
                            headers=_headers(CHAT_A),
                            json={"text": "Локальная редакция", "scope": "chat"})
    assert write.status_code == 200, write.text

    reset = env.client.post(
        f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}/reset",
        headers=_headers(CHAT_A), json={"mode": "chat"})
    assert reset.status_code == 200, reset.text
    body = reset.json()
    assert body["ok"] is True and body["inherits"] == "global", body
    assert CORE_KEY not in stored_overrides(env.db, CHAT_A)
    core = env.client.get("/api/speech/core",
                          headers=_headers(CHAT_A)).json()
    assert core["inheritance"] == "factory_default"   # исходное состояние
    assert core["editions"]["full"]["source"] in ("default", "code", "factory")

    # повторный сброс без переопределения — честный no-op, не ошибка
    again = env.client.post(
        f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}/reset",
        headers=_headers(CHAT_A), json={"mode": "chat"})
    assert again.status_code == 200, again.text
    assert again.json()["ok"] is False
    assert again.json()["result"]["reason"] == "no_chat_override"


# ═══════════════════════════════════════════════════════════════════════════
# Expression: запись, reread, сброс «в inherited», изоляция
# ═══════════════════════════════════════════════════════════════════════════

def test_expression_chat_write_readback_and_reset(env):
    before = env.client.get("/api/speech/expression",
                            headers=_headers(CHAT_A)).json()
    assert before["inheritance"] == "factory_default"

    resp = env.client.post("/api/speech/expression", headers=_headers(CHAT_A),
                           json={"values": {"wit": "high", "profanity": "off",
                                            "note": "P0"},
                                 "scope": "chat"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["applied"] is True
    doc = stored_overrides(env.db, CHAT_A)[EXPRESSION_KEY]
    assert doc["wit"] == "high" and doc["profanity"] == "off"
    assert doc["note"] == "P0"

    view = env.client.get("/api/speech/expression",
                          headers=_headers(CHAT_A)).json()
    assert view["inheritance"] == "chat" and view["chat_present"] is True
    assert view["document"]["wit"] == "high"
    # изоляция
    assert EXPRESSION_KEY not in stored_overrides(env.db, CHAT_B)

    reset = env.client.post("/api/speech/expression/reset-chat",
                            headers=_headers(CHAT_A))
    assert reset.status_code == 200, reset.text
    assert reset.json()["ok"] is True
    assert EXPRESSION_KEY not in stored_overrides(env.db, CHAT_A)
    after = env.client.get("/api/speech/expression",
                           headers=_headers(CHAT_A)).json()
    assert after["inheritance"] == "factory_default"   # возврат исходного

    again = env.client.post("/api/speech/expression/reset-chat",
                            headers=_headers(CHAT_A))
    assert again.status_code == 200
    assert again.json()["ok"] is False
    assert again.json()["reason"] == "no_chat_override"


def test_expression_allowed_alias_written_canonically(env):
    """ADD-EXP §1.3: read-alias `allowed` → `occasional` (без второго storage).

    Существующий путь записи сохраняет КАНОНИЧЕСКОЕ значение; read-after-write
    подтверждает это, а не имитирует успех.
    """
    resp = env.client.post("/api/speech/expression", headers=_headers(CHAT_A),
                           json={"values": {"profanity": "allowed"},
                                 "scope": "chat"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["applied"] is True
    doc = stored_overrides(env.db, CHAT_A)[EXPRESSION_KEY]
    assert doc["profanity"] == "occasional", \
        "alias не должен попадать в storage как есть"
    view = env.client.get("/api/speech/expression",
                          headers=_headers(CHAT_A)).json()
    assert view["values"]["profanity"] == "occasional"
    assert view["effective"]["profanity"] == {"value": "occasional",
                                              "source": "chat",
                                              "migrated": False}
    assert view["migration"] == {}, \
        "после канонического сохранения баннер миграции не нужен"


# ═══════════════════════════════════════════════════════════════════════════
# Style Policy: правила/привычки, unknown kind, сброс «в inherited»
# ═══════════════════════════════════════════════════════════════════════════
_STYLE_RULE = {"id": "trailing_period.hard.strip", "kind": "trailing_period",
               "strictness": "hard", "scope": "global", "enabled": True,
               "params": {"ellipsis": "strip"}, "reason": "P0 persist-test"}
_STYLE_SOFT = {"text": "Пиши короче", "scope": "global"}


def test_style_policy_chat_write_rules_soft_and_reset(env):
    before = env.client.get("/api/speech/style",
                            headers=_headers(CHAT_A)).json()
    assert before["document"]["inheritance"] == "factory_default"

    resp = env.client.post(
        "/api/speech/style", headers=_headers(CHAT_A),
        json={"document": {"rules": [_STYLE_RULE],
                           "soft_instructions": [_STYLE_SOFT]},
              "scope": "chat"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["result"]["applied"] is True, body
    assert body["result"]["rules"] == 1 and body["result"]["soft_instructions"] == 1
    # read-after-write из БД
    doc = stored_overrides(env.db, CHAT_A)[STYLE_KEY]
    assert doc["rules"][0]["kind"] == "trailing_period"
    assert doc["soft_instructions"][0]["text"] == "Пиши короче"
    # reread через API
    chat_view = env.client.get("/api/speech/style",
                               headers=_headers(CHAT_A)).json()
    assert chat_view["document"]["inheritance"] == "chat"
    assert any(r["kind"] == "trailing_period" for r in chat_view["rules"])
    # изоляция
    assert STYLE_KEY not in stored_overrides(env.db, CHAT_B)

    # «Сбросить в inherited»: реальный результат (не ложное «переопределения
    # не было»), затем честный no-op.
    reset = env.client.post("/api/speech/style/reset-chat",
                            headers=_headers(CHAT_A))
    assert reset.status_code == 200, reset.text
    assert reset.json()["ok"] is True, reset.text
    assert STYLE_KEY not in stored_overrides(env.db, CHAT_A)
    after = env.client.get("/api/speech/style",
                           headers=_headers(CHAT_A)).json()
    assert after["document"]["inheritance"] == "factory_default"

    again = env.client.post("/api/speech/style/reset-chat",
                            headers=_headers(CHAT_A))
    assert again.status_code == 200
    assert again.json()["ok"] is False
    assert again.json()["result"]["reason"] == "no_chat_override"


def test_style_chat_conflict_returns_409_without_data_loss(env):
    """Чужой optimistic-токен (chat): 409, документ не записан и не потерян."""
    first = env.client.post(
        "/api/speech/style", headers=_headers(CHAT_A),
        json={"document": {"rules": [_STYLE_RULE], "soft_instructions": []},
              "scope": "chat"})
    assert first.status_code == 200, first.text
    stored = stored_overrides(env.db, CHAT_A)[STYLE_KEY]

    stale = "2026-01-01T00:00:00+00:00"
    conflict = env.client.post(
        "/api/speech/style", headers=_headers(CHAT_A),
        json={"document": {"rules": [], "soft_instructions": []},
              "scope": "chat", "expected_updated_at": stale})
    assert conflict.status_code == 409, conflict.text
    # Ничего не перезаписано: прежний документ на месте (текст не потерян).
    assert stored_overrides(env.db, CHAT_A)[STYLE_KEY]["rules"] == \
        stored["rules"]


def test_style_unknown_kind_rule_is_explicit_error_not_silent_loss(env):
    """Неизвестный kind: явная ошибка, а не «Правила сохранены» без правила."""
    bad = {"id": "quotes.rule", "kind": "quotes", "strictness": "hard",
           "scope": "global", "params": {}, "reason": "P0 unknown-kind"}
    resp = env.client.post(
        "/api/speech/style", headers=_headers(CHAT_A),
        json={"document": {"rules": [bad], "soft_instructions": []},
              "scope": "chat"})
    assert resp.status_code == 409, resp.text          # валидация не подавлена
    detail = str(resp.json().get("detail") or "")
    assert "quotes" in detail                           # видно, что именно не так
    # правило НЕ потеряно тихо: хранилище не изменилось (нет partial-записи)
    assert STYLE_KEY not in stored_overrides(env.db, CHAT_A)


# ═══════════════════════════════════════════════════════════════════════════
# Humor craft и Learning: переключатели и обучение в chat-скоупе
# ═══════════════════════════════════════════════════════════════════════════

def test_humor_craft_chat_toggle_saved(env):
    resp = env.client.post("/api/speech/humor/craft", headers=_headers(CHAT_A),
                           json={"enabled": False, "scope": "chat"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    doc = stored_overrides(env.db, CHAT_A)[HUMOR_CRAFT_KEY]
    assert doc["enabled"] is False

    # возврат исходного значения (ремесло включено)
    back = env.client.post("/api/speech/humor/craft", headers=_headers(CHAT_A),
                           json={"enabled": True, "scope": "chat"})
    assert back.status_code == 200, back.text
    assert stored_overrides(env.db, CHAT_A)[HUMOR_CRAFT_KEY]["enabled"] is True
    assert HUMOR_CRAFT_KEY not in stored_overrides(env.db, CHAT_B)


def test_learning_pause_resume_reset_chat_scope(env):
    pause = env.client.post("/api/speech/learning/humor",
                            headers=_headers(CHAT_A), json={"action": "pause"})
    assert pause.status_code == 200, pause.text
    assert pause.json()["ok"] is True
    assert stored_overrides(env.db, CHAT_A)[HUMOR_FEEDBACK_KEY]["paused"] is True

    resume = env.client.post("/api/speech/learning/humor",
                             headers=_headers(CHAT_A), json={"action": "resume"})
    assert resume.status_code == 200, resume.text
    assert stored_overrides(env.db, CHAT_A
                            )[HUMOR_FEEDBACK_KEY]["paused"] is False

    reset = env.client.post("/api/speech/learning/humor",
                            headers=_headers(CHAT_A), json={"action": "reset"})
    assert reset.status_code == 200, reset.text
    assert reset.json()["ok"] is True
    doc = stored_overrides(env.db, CHAT_A)[HUMOR_FEEDBACK_KEY]
    assert doc.get("reset_at")                       # сброс реально записан
    assert HUMOR_FEEDBACK_KEY not in stored_overrides(env.db, CHAT_B)


def test_examples_policy_chat_scope_saved(env):
    resp = env.client.post("/api/speech/examples/policy",
                           headers=_headers(CHAT_A),
                           json={"max_items": 2, "scope": "chat"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    doc = stored_overrides(env.db, CHAT_A)[SELECTION_KEY]
    assert int(doc["max_items"]) == 2
    assert SELECTION_KEY not in stored_overrides(env.db, CHAT_B)


# ═══════════════════════════════════════════════════════════════════════════
# Недоступное хранилище: явная ошибка, не 200/ok:false и не тихий in-memory
# ═══════════════════════════════════════════════════════════════════════════

def test_no_pool_is_explicit_error_not_fake_success(env, monkeypatch):
    monkeypatch.setattr(env.cache, "_pg", types.SimpleNamespace(pool=None))

    # chat-scope: честная 5xx с человеческой причиной (не 409 «write_error»)
    chat = env.client.post("/api/speech/expression", headers=_headers(CHAT_A),
                           json={"values": {"wit": "high"}, "scope": "chat"})
    assert chat.status_code == 503, chat.text
    assert "write_error" not in json.dumps(chat.json())
    assert EXPRESSION_KEY not in stored_overrides(env.db, CHAT_A)

    # global-scope: запись НЕ считается успешной без постоянного хранилища
    glob = env.client.post(
        "/api/speech/style", headers=_headers(),
        json={"document": {"rules": [_STYLE_RULE], "soft_instructions": []},
              "scope": "global"})
    assert glob.status_code == 503, glob.text
    assert stored_setting(env.db, STYLE_KEY) is None
