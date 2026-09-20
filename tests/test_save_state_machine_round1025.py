"""F0.1 (раунд 10.25, ADR-1025-2) — идемпотентный 409-контракт и
единая state-machine сохранения (серверная часть).

Проверяем:
  * D-409-1 idempotent short-circuit: токен устарел, но значения уже
    совпадают → 200 revalidated=true (не ChatParamsConflict);
  * D-409-4 честный 409: реальный конфликт → `conflicting`
    `[{key, your_value, server_value}]`;
  * сравнение значений (int/float) и diff-хелперы;
  * D-409-2 сериализация: `_chat_write_lock` — один лок на chat_id.

Тесты падают на старом коде (там 0 строк UPDATE → всегда ChatParamsConflict).
"""
import copy
import json

import pytest

from services import chat_params
from services.chat_params import (
    ChatParamsCache,
    ChatParamsConflict,
    _diff_patch,
    _patch_already_applied,
    _same_value,
    set_chat_params,
)

_KEY = "limits.chat_cooldown_seconds"


class _FakeConn:
    def __init__(self):
        self.profiles = {}
        self.history = []
        self.notifies = []
        self.advisory = []
        self._seq = 0

    def _ts(self):
        self._seq += 1
        return f"2026-09-07T10:00:{self._seq:02d}+00:00"

    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT"):
            row = self.profiles.get(args[0])
            return copy.deepcopy(row) if row else None
        if "UPDATE chat_profiles" in sql:
            chat_id = args[0]
            row = self.profiles.get(chat_id)
            if not row:
                return None
            if "AND updated_at = $3::timestamptz" in sql:
                exp = args[2]
                exp = exp.isoformat() if hasattr(exp, "isoformat") else exp
                if exp != row["updated_at"]:
                    return None
            row["chat_params"] = (json.loads(args[1])
                                  if isinstance(args[1], str)
                                  else copy.deepcopy(args[1]))
            row["updated_at"] = self._ts()
            return copy.deepcopy(row)
        return None

    async def execute(self, sql, *args):
        if "advisory" in sql:
            self.advisory.append(args[0])
        if "INSERT INTO chat_lore_history" in sql:
            self.history.append({"chat_id": args[0], "field": args[1],
                                 "changed_by": args[2], "old_value": args[3],
                                 "new_value": args[4]})
        if "pg_notify" in sql:
            self.notifies.append(str(args[0]))
        return "UPDATE 1"

    def transaction(self):
        inner = self

        class _Tx:
            async def __aenter__(self):
                return inner

            async def __aexit__(self, *exc):
                return False

        return _Tx()

    def add_profile(self, chat_id, chat_params_=None, updated_at=None):
        self.profiles[chat_id] = {
            "chat_id": chat_id,
            "updated_at": updated_at or self._ts(),
            "chat_params": chat_params_ or {},
            "gates_opt_in": False,
        }


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        inner = self

        class _CM:
            async def __aenter__(self):
                return inner._conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, conn):
        self.pool = _FakePool(conn)


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    monkeypatch.setattr("services.chat_params._chat_params_cache", None)
    yield
    monkeypatch.setattr("services.chat_params._chat_params_cache", None)


@pytest.fixture
def conn():
    return _FakeConn()


@pytest.fixture
def pg(conn):
    return _FakePg(conn)


# ── Хелперы ─────────────────────────────────────────────────────────────────

def test_same_value_numeric_equivalence():
    assert _same_value(5, 5.0)
    assert _same_value("a", "a")
    assert not _same_value(True, 1)          # bool не приравнивается к числу
    assert not _same_value(5, 6)


def test_patch_already_applied_and_diff():
    patch = {"overrides": {"a": 1, "b": 2}, "meta": {"updated_by": 7}}
    cur = {"overrides": {"a": 1, "b": 3}}
    assert _patch_already_applied(
        {"overrides": {"a": 1}}, cur) is True
    assert _patch_already_applied(patch, cur) is False
    diff = _diff_patch(patch, cur)
    assert diff == [{"key": "b", "your_value": 2, "server_value": 3}]


# ── D-409-1 idempotent short-circuit ────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotent_short_circuit_already_applied(conn, pg):
    conn.add_profile(-1, {"v": 1, "overrides": {_KEY: 5}},
                     updated_at="2026-09-07T10:00:00+00:00")
    # Токен устарел (не совпадает) — но значение уже на сервере.
    root = await set_chat_params(
        -1, {"overrides": {_KEY: 5}}, changed_by=7, pg=pg,
        expected_updated_at="2026-09-07T09:00:00+00:00")
    assert root["overrides"][_KEY] == 5
    assert root.revalidated is True
    assert conn.notifies == []          # ничего не менялось — без NOTIFY
    assert conn.history == []


# ── D-409-4 честный 409 с conflicting ───────────────────────────────────────

@pytest.mark.asyncio
async def test_real_conflict_reports_conflicting(conn, pg):
    conn.add_profile(-1, {"v": 1, "overrides": {_KEY: 5}},
                     updated_at="2026-09-07T10:00:00+00:00")
    with pytest.raises(ChatParamsConflict) as exc:
        await set_chat_params(
            -1, {"overrides": {_KEY: 9}}, changed_by=7, pg=pg,
            expected_updated_at="2026-09-07T09:00:00+00:00")
    assert exc.value.conflicting == [
        {"key": _KEY, "your_value": 9, "server_value": 5}]
    assert exc.value.current_updated_at == "2026-09-07T10:00:00+00:00"


@pytest.mark.asyncio
async def test_conflict_lists_only_changed_keys(conn, pg):
    conn.add_profile(-2, {"v": 1, "overrides": {"a": 1, "b": 1}},
                     updated_at="2026-09-07T10:00:00+00:00")
    with pytest.raises(ChatParamsConflict) as exc:
        await set_chat_params(
            -2, {"overrides": {"a": 1, "b": 2}}, changed_by=7, pg=pg,
            expected_updated_at="2026-09-07T09:00:00+00:00")
    # 'a' совпадает — в conflicting только 'b'
    assert [c["key"] for c in exc.value.conflicting] == ["b"]


# ── D-409-2 сериализация ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_write_lock_is_stable_per_chat():
    l1 = await chat_params._chat_write_lock(-55)
    l2 = await chat_params._chat_write_lock(-55)
    l3 = await chat_params._chat_write_lock(-56)
    assert l1 is l2
    assert l1 is not l3


@pytest.mark.asyncio
async def test_normal_write_emits_notify_and_history(conn, pg):
    conn.add_profile(-3, {"v": 1, "overrides": {}})
    root = await set_chat_params(
        -3, {"overrides": {_KEY: 5}}, changed_by=7, pg=pg)
    assert root["overrides"][_KEY] == 5
    assert root.revalidated is False
    assert conn.notifies == ["-3"]
    assert len(conn.history) == 1
    assert conn.advisory == ["-3"]        # D-409-2: advisory-lock вызван


# ── F0.2: scope-изоляция (чат A ≠ чат B) ────────────────────────────────────

@pytest.mark.asyncio
async def test_scope_isolation_chat_a_not_b(conn, pg):
    conn.add_profile(-1, {"v": 1, "overrides": {_KEY: 5}})
    conn.add_profile(-2, {"v": 1, "overrides": {_KEY: 9}})
    await set_chat_params(-1, {"overrides": {_KEY: 7}}, changed_by=1, pg=pg)
    assert conn.profiles[-1]["chat_params"]["overrides"][_KEY] == 7
    assert conn.profiles[-2]["chat_params"]["overrides"][_KEY] == 9
