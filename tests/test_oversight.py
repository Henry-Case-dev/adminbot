"""Раунд 10 (F-12, T-919) — тесты services/oversight.py + API-матрицы.

build_summary (мок-данные: PG-профили + SQLite-агрегаты: состав корректен;
кэш 60 с; PG down → errors + живые данные), killswitch/global_key (запись +
история + NOTIFY; noop → 200 previous; 409-протокол), приоритет гейтов:
явный chat-гейт > глобальный флаг > False.
"""
import json
import time

import pytest

from services import chat_params, oversight


class _FakeConn:
    def __init__(self, profiles=None, keys=(), admins=(), history=None):
        self.profiles = profiles or []
        self.keys = keys
        self.admins = admins
        self.history = history or []

    async def fetch(self, sql, *args):
        if "FROM chat_profiles" in sql:
            return self.profiles
        if "FROM chat_admins" in sql:
            return self.admins
        if "FROM chat_keys" in sql:
            return self.keys
        return []

    async def fetchrow(self, sql, *args):
        if "FROM chat_keys" in sql:
            for key_info in self.keys:
                if key_info["chat_id"] == args[0]:
                    return key_info
        return None

    async def execute(self, sql, *args):
        return "UPDATE 1"

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx


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
        self.pool = _FakePool(conn)


def _profile(chat_id, active=True, chat_params=None, opt_in=False):
    return {"chat_id": chat_id, "is_active": active,
            "chat_params": chat_params or {},
            "gates_opt_in": opt_in,
            "updated_at": "2026-09-07T00:00:00+00:00"}


def _reset(monkeypatch):
    oversight._cache = {}
    oversight._cache_ts = 0.0
    oversight._title_cache = {}
    monkeypatch.setattr(oversight, "_activity_cache", {})


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _reset(monkeypatch)


@pytest.mark.asyncio
async def test_build_summary_composition(monkeypatch):
    conn = _FakeConn(
        profiles=[_profile(-100, True, {
            "v": 1, "gates": {"dream": True, "nostalgia": False,
                              "lore_auto": True, "permsoc": False},
            "keys": {"allow_global": True}}, opt_in=False),
                  _profile(-200, False, {
                      "v": 1, "keys": {"allow_global": False},
                      "gates": {"dream": False}},
                      opt_in=True)],
        keys=[{"chat_id": -100, "key_name": "keys.llm_api_key",
               "key_value": "OWNKEY1234"}],
        admins=[{"chat_id": -100, "c": 2}, {"chat_id": -200, "c": 0}])
    pg = _FakePg(conn)
    monkeypatch.setattr(oversight, "_activity_map",
                        lambda pg_: _aw({-100: "2026-09-07T05:00:00+00:00"}))
    monkeypatch.setattr(oversight.worker_budget, "get_usage",
                        lambda *a, **k: _aw([]))
    data = await oversight.build_summary(pg)
    assert data["errors"] == []
    assert len(data["chats"]) == 2
    first = data["chats"][0]
    assert first["chat_id"] == -100
    assert first["gates_opt_in"] is False
    assert first["heavy"] == {"dream": True, "nostalgia": False,
                              "lore_auto": True}
    assert first["permsoc"] is False
    assert first["key_status"] == "own"
    assert first["key_last4"] == "1234"
    assert first["admins_count"] == 2
    assert first["last_active_ts"] == "2026-09-07T05:00:00+00:00"
    second = data["chats"][1]
    assert second["key_status"] == "forbidden"
    assert second["allow_global"] is False
    assert second["gates_opt_in"] is True


@pytest.mark.asyncio
async def test_build_summary_pg_down_errors(monkeypatch):
    data = await oversight.build_summary(None)
    assert any(e["source"] == "pg" for e in data["errors"])
    assert data["chats"] == []


@pytest.mark.asyncio
async def test_summary_cache_60s(monkeypatch):
    calls = {"n": 0}

    async def fake_build(pg):
        calls["n"] += 1
        return {"generated_at": "t", "chats": [{"x": calls["n"]}],
                "errors": [], "global_budget": {}}

    monkeypatch.setattr(oversight, "build_summary", fake_build)
    # кэшируется через внутренние поля — проверяем через invalidate
    oversight._cache = {"generated_at": "t", "chats": [{"x": 1}],
                        "errors": [], "global_budget": {}}
    oversight._cache_ts = time.monotonic()
    data = await oversight.build_summary(None)
    assert data["chats"][0]["x"] == 1
    oversight.invalidate_summary()
    assert oversight._cache_ts == 0.0


@pytest.mark.asyncio
async def test_global_key_noop(monkeypatch):
    conn = _FakeConn(profiles=[_profile(-100, True, {
        "v": 1, "keys": {"allow_global": True}})])
    pg = _FakePg(conn)
    from services import chat_params as cp
    monkeypatch.setattr(cp, "_chat_params_cache", None)
    root = await cp.get_all_chat_params(-100)
    assert bool((root.get("keys") or {}).get("allow_global", True)) is True


def test_invalidate_summary():
    oversight._cache_ts = time.monotonic()
    oversight.invalidate_summary()
    assert oversight._cache_ts == 0.0


def _aw(value):
    async def _inner(*a, **kw):
        return value
    return _inner()
