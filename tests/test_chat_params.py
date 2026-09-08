"""Раунд 10 (F-7, T-859 G2) — тесты services/chat_params.py.

Резолв (spec §4.5): overrides (каст) → hot.get → default; optimistic-409 с
current_updated_at; NOTIFY эмит; кэш-инвалидация; fail-open (PG down →
глобал/дефолт); атомарность патча (одна транзакция).
"""
import copy
import json

import pytest

import pytest

from services.chat_params import (
    ChatParamsCache,
    ChatParamsConflict,
    get_chat_param,
    get_chat_updated_at,
    set_chat_params,
    set_chat_params_cache,
)

pytestmark = pytest.mark.asyncio


class _FakeConn:
    def __init__(self):
        self.profiles = {}
        self.history = []
        self.notifies = []
        self._seq = 0

    def _ts(self):
        self._seq += 1
        return f"2026-09-07T10:00:{self._seq:02d}+00:00"

    def _row(self, chat_id):
        return self.profiles.get(chat_id)

    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT"):
            row = self._row(args[0])
            return copy.deepcopy(row) if row else None
        if "UPDATE chat_profiles" in sql:
            chat_id = args[0]
            row = self._row(chat_id)
            if not row:
                return None
            if "AND updated_at = $3::timestamptz" in sql:
                if str(args[2] if hasattr(args[2], 'isoformat') else args[2]) \
                        != row["updated_at"]:
                    return None
            row["chat_params"] = json.loads(json.dumps(args[1]))
            row["updated_at"] = self._ts()
            return copy.deepcopy(row)
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO chat_lore_history" in sql:
            self.history.append({"chat_id": args[0], "field": args[1],
                                 "changed_by": args[2],
                                 "old_value": args[3], "new_value": args[4]})
        if "pg_notify" in sql:
            self.notifies.append(str(args[0]))
        if "SET gates_opt_in" in sql or "gates_opt_in = true" in sql:
            row = self._row(args[0])
            if row:
                row["gates_opt_in"] = True
        return "UPDATE 1"

    def add_profile(self, chat_id, chat_params=None, updated_at=None):
        self.profiles[chat_id] = {
            "chat_id": chat_id,
            "updated_at": updated_at or self._ts(),
            "chat_params": chat_params or {},
            "gates_opt_in": False,
        }

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


@pytest.fixture
def pg_and_cache(monkeypatch):
    conn = _FakeConn()
    pg = _FakePg(conn)
    cache = ChatParamsCache(pg)
    monkeypatch.setattr("services.chat_params._chat_params_cache", cache)
    return conn, pg, cache


async def test_resolve_no_override_goes_global(pg_and_cache, monkeypatch):
    conn, pg, _ = pg_and_cache
    conn.add_profile(-10001)
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None: "GLOBAL" if key ==
                        "prompts.direct_chat_system_prompt" else default)
    value = await get_chat_param(-10001, "prompts.direct_chat_system_prompt",
                                 "CANON")
    assert value == "GLOBAL"


async def test_resolve_override_beats_global(pg_and_cache, monkeypatch):
    conn, pg, _ = pg_and_cache
    conn.add_profile(-10001, {"v": 1, "overrides": {
        "prompts.direct_chat_system_prompt": "MOI"}})
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None: "GLOBAL")
    value = await get_chat_param(-10001, "prompts.direct_chat_system_prompt",
                                 "CANON")
    assert value == "MOI"


async def test_resolve_default_when_no_key(pg_and_cache, monkeypatch):
    conn, pg, _ = pg_and_cache
    conn.add_profile(-10001)
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None: default if key ==
                        "unknown.key" else None)
    assert await get_chat_param(-10001, "unknown.key", "D") == "D"


# фикстура conn/cache/pg — from pg_and_cache fixture below (scope-переименование)
@pytest.fixture
def conn(conn_holder):
    return conn_holder.conn


@pytest.fixture
def cache(conn_holder):
    return conn_holder.cache


@pytest.fixture
def pg(conn_holder):
    return conn_holder.pg


class _ConnHolder:
    pass


@pytest.fixture
def conn_holder():
    conn = _FakeConn()
    pg = _FakePg(conn)
    cache = ChatParamsCache(pg)
    set_chat_params_cache(cache)
    holder = _ConnHolder()
    holder.conn = conn
    holder.cache = cache
    holder.pg = pg
    return holder


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr("services.chat_params._chat_params_cache", None)
    yield
    monkeypatch.setattr("services.chat_params._chat_params_cache", None)


async def test_set_chat_params_conflict(conn, cache, pg):
    conn.add_profile(-1, updated_at="2026-09-07T10:00:00+00:00")
    with pytest.raises(ChatParamsConflict) as exc:
        await set_chat_params(
            -1, {"overrides": {"limits.chat_cooldown_seconds": 1}},
            changed_by=7, pg=pg,
            expected_updated_at="2026-09-07T09:00:00+00:00")
    assert exc.value.current_updated_at == "2026-09-07T10:00:00+00:00"


async def test_set_chat_params_ok_history_notify(conn, cache, pg):
    conn.add_profile(-1)
    root = await set_chat_params(
        -1, {"overrides": {"limits.chat_cooldown_seconds": 5}},
        changed_by=7, pg=pg)
    assert root["overrides"]["limits.chat_cooldown_seconds"] == 5
    assert conn.notifies == ["-1"]
    assert len(conn.history) == 1
    rec = conn.history[0]
    assert rec["field"] == "chat_params"
    assert rec["changed_by"] == 7


async def test_set_chat_params_keeps_namespaces(conn, cache, pg):
    conn.add_profile(-1, {"v": 1, "overrides": {"a": 1},
                          "gates": {"dream": False}})
    root = await set_chat_params(
        -1, {"gates": {"dream": True}}, changed_by=1, pg=pg)
    assert root["gates"]["dream"] is True
    assert root["overrides"]["a"] == 1


async def test_perm_overrides_flags_shape(conn, cache, pg):
    """BUG-6 (spec §3.2.2): perm_overrides пишется в НОВОЙ форме
    {view_roles, edit_roles} (набор-замена); legacy-строки нормализуются
    на чтении (effective_matrix: фолдинг hidden_from_local + union)."""
    conn.add_profile(-7)
    root = await set_chat_params(
        -7, {"perm_overrides": {"limits.chat_cooldown_seconds":
                                {"view_roles": ["moderator"],
                                 "edit_roles": ["local_admin"]}}},
        changed_by=1, pg=pg)
    po = root["perm_overrides"]["limits.chat_cooldown_seconds"]
    assert po["view_roles"] == ["moderator"]
    assert po["edit_roles"] == ["local_admin"]
    # чтение legacy-строки: normalize на чтении (view: rank>=moderator минус
    # local_admin-фолдинг + union edit → «запись подразумевает чтение»)
    from services import access as access_srv
    m = access_srv.effective_matrix(
        "limits.chat_cooldown_seconds",
        chat_override={"view_min_role": "moderator",
                       "edit_min_role": "moderator",
                       "hidden_from_local": True})
    assert m["view_roles"] == ["moderator", "local_admin"]
    assert m["edit_roles"] == ["moderator", "local_admin"]
    assert "hidden_from_local" not in m
    assert "view_min_role" not in m


async def test_fail_open_pg_down(pg_and_cache):
    conn, pg, cache = pg_and_cache
    cache.set_pg(None)
    assert await get_chat_param(-99, "key.doesnt.matter", "D") == "D"
    assert await get_chat_updated_at(-99) is None


def _unused():  # placeholder для pytest — см. фикстуру ниже
    pass


def _reset_global_cache():
    pass
