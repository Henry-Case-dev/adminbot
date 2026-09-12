"""Раунд 10 (F-10, T-901) — тесты services/feature_gates.py +
services/worker_budget.py.

gates: явный > глобальный > False; auto_opt_in при первом включении
тяжёлой; конфликт 409-протокола (set_feature_gate → ChatParamsConflict).
budget: consume-порог (лимит 10 → 11-й False), новый день — авто-сброс
(дневной ключ меняет day), per-chat/global независимы, деградация по
priority_order, jitter-диапазон, fail-open (PG down → consume=True).
"""
import datetime
import json

import pytest

from services import feature_gates, worker_budget


class _FakeConn:
    def __init__(self):
        self.rows = {}                       # (day, scope, metric) -> used
        self.profiles = {}

    async def fetch(self, sql, *args):
        day = args[0]
        out = [{"day": day.isoformat() if isinstance(day, datetime.date)
                else day, "scope": k[1], "metric": k[2], "used": v}
               for k, v in self.rows.items() if k[0] == day]
        if len(args) > 1:
            out = [r for r in out if r["scope"] == args[1]]
        return out

    async def fetchrow(self, sql, *args):
        if "INSERT INTO worker_budget" in sql or "worker_budget" in sql \
                and "RETURNING" in sql:
            key = (args[0], args[1], args[2])
            self.rows[key] = self.rows.get(key, 0) + int(args[3])
            return {"used": self.rows[key]}
        if "UPDATE chat_profiles" in sql:
            chat_id = args[0]
            row = self.profiles.get(chat_id)
            if row is None:
                return None
            row["chat_params"] = json.loads(args[1])
            return dict(row)
        if "FROM chat_profiles" in sql:
            return self.profiles.get(args[0])
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO worker_budget" in sql:
            key = (args[0], args[1], args[2])
            self.rows[key] = self.rows.get(key, 0) + int(args[3])
            return "INSERT 1"
        if "UPDATE chat_profiles" in sql and "gates_opt_in" in sql:
            row = self.profiles.get(args[0])
            if row:
                row["gates_opt_in"] = True
            return "UPDATE 1"
        if "UPDATE chat_profiles" in sql:
            row = self.profiles.get(args[0])
            if row:
                row["chat_params"] = json.loads(args[1])
            return "UPDATE 1"
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


def _aw(value):
    async def _inner():
        return value
    return _inner()


@pytest.mark.asyncio
async def test_gates_chain_explicit_beats_global(monkeypatch):
    root = {"v": 1, "gates": {"dream": True}}
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None: False)
    assert await feature_gates.gates_enabled(-100, "dream", root=root) is True
    root2 = {"v": 1, "gates": {"dream": False}}
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None: True)
    assert await feature_gates.gates_enabled(-100, "dream",
                                             root=root2) is False


@pytest.mark.asyncio
async def test_gates_default_false_when_missing(monkeypatch):
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None: True)
    assert await feature_gates.gates_enabled(-100, "dennis",
                                             root={}) is False
    assert await feature_gates.gates_enabled(-100, "lore_auto",
                                             root={"v": 1}) is True


@pytest.mark.asyncio
async def test_unknown_feature_raises(conn_holder2):
    with pytest.raises(ValueError):
        await feature_gates.set_feature_gate(-1, "dennis", True,
                                             pg=conn_holder2.pg)


@pytest.mark.asyncio
async def test_set_feature_gate_writes_history(conn_holder2):
    conn, pg = conn_holder2.conn, conn_holder2.pg
    conn.profiles[-100] = {"chat_id": -100, "updated_at": "2026-09-07T01:00:00+00:00",
                           "chat_params": {"v": 1, "gates": {}},
                           "gates_opt_in": False}
    root = await feature_gates.set_feature_gate(
        -100, "dream", True, changed_by=5, pg=pg)
    assert root["gates"]["dream"] is True
    assert conn.profiles[-100]["gates_opt_in"] is True   # auto_opt_in


@pytest.mark.asyncio
async def test_worker_consume_limit(monkeypatch, conn_holder2):
    conn, pg = conn_holder2.conn, conn_holder2.pg
    monkeypatch.setattr(worker_budget.hot, "get",
                        lambda key, default=None:
                        10 if key == "limits.worker_daily_llm_calls_per_chat"
                        else default)
    scope = "chat:-100"
    ok = True
    for _ in range(11):
        ok = await worker_budget.consume(pg, scope, "llm_calls", 1)
    assert ok is False


@pytest.mark.asyncio
async def test_global_per_chat_independent(monkeypatch, conn_holder2):
    conn, pg = conn_holder2.conn, conn_holder2.pg
    monkeypatch.setattr(worker_budget.hot, "get", lambda key, default=None: 5)
    for _ in range(6):
        await worker_budget.consume(pg, "chat:-1", "llm_calls", 1)
    assert await worker_budget.consume(pg, "chat:-1", "llm_calls", 1) is False
    for _ in range(6):
        await worker_budget.consume(pg, "global", "llm_calls", 1)
    assert await worker_budget.consume(pg, "global", "llm_calls", 1) is False
    assert await worker_budget.consume(pg, "chat:-2", "llm_calls", 1) is True


@pytest.mark.asyncio
async def test_fail_open_pg_down(monkeypatch):
    assert await worker_budget.consume(None, "global", "llm_calls", 1) is True
    assert await worker_budget.get_usage(None) == []


def test_priority_order_default():
    assert worker_budget.priority_of("nostalgia") == 0
    assert worker_budget.priority_of("lore") == 1
    assert worker_budget.priority_of("dream") == 2
    # F3 (cognition-deep-sleep): deep_sleep — наименее критичный фон, падает
    # первым (priority_of=3; в _priority_order — после легаси-воркеров).
    assert worker_budget.priority_of("deep_sleep") == 3
    # ФИКС R4: порядок деградации — обратный приоритету (первый = первый
    # падает): dream → lore → nostalgia (F-10 §5.2).
    assert worker_budget.workers_dropped(["dream", "nostalgia", "lore"]) == \
        ["dream", "lore", "nostalgia"]
    assert worker_budget._priority_order() == \
        ("nostalgia", "lore", "dream", "deep_sleep")


def test_allowed_workers_degradation_matrix():
    """ФИКС R4 (F-10 §5.2): allowed_workers — чистая матрица деградации."""
    ids = ("nostalgia", "lore", "dream")
    # бюджет не исчерпан — все живы
    assert all(worker_budget.allowed_workers(ids, 9, 10).values())
    # used == limit: dream падает ПЕРВЫМ, lore/nostalgia ещё живы
    state = worker_budget.allowed_workers(ids, 10, 10)
    assert state == {"nostalgia": True, "lore": True, "dream": False}
    # used == limit + 1: падает и lore (последней — nostalgia)
    state2 = worker_budget.allowed_workers(ids, 11, 10)
    assert state2 == {"nostalgia": True, "lore": False, "dream": False}
    # used == limit + 2: все пали
    state3 = worker_budget.allowed_workers(ids, 12, 10)
    assert state3 == {"nostalgia": False, "lore": False, "dream": False}


def test_deep_sleep_drops_before_dream():
    """F3/ISSUE-6: deep_sleep падает ПЕРВЫМ — на тик раньше обычного «сна»,
    при этом легаси-матрица F-10 (dream/lore/nostalgia) не сдвигается."""
    state = worker_budget.allowed_workers(("dream", "deep_sleep"), 9, 10)
    assert state == {"dream": True, "deep_sleep": False}
    state2 = worker_budget.allowed_workers(
        ("nostalgia", "lore", "dream", "deep_sleep"), 10, 10)
    assert state2 == {"nostalgia": True, "lore": True, "dream": False,
                      "deep_sleep": False}


@pytest.mark.asyncio
async def test_global_degradation_allows_reads_usage(monkeypatch, conn_holder2):
    conn, pg = conn_holder2.conn, conn_holder2.pg
    monkeypatch.setattr(
        worker_budget.hot, "get",
        lambda key, default=None:
        10 if key == "limits.worker_daily_llm_calls_global" else default)
    for _ in range(11):
        await worker_budget.consume(pg, "global", "llm_calls", 1)
    # used=11 > limit=10 → dream и lore уже выпали, nostalgia ещё жива
    assert await worker_budget.global_degradation_allows("dream", pg) is False
    assert await worker_budget.global_degradation_allows("lore", pg) is False
    assert await worker_budget.global_degradation_allows("nostalgia",
                                                        pg) is True


@pytest.mark.asyncio
async def test_global_degradation_fail_open():
    """PG down → True (воркеры не останавливаются), §1-4."""
    assert await worker_budget.global_degradation_allows("dream", None) is True


@pytest.mark.asyncio
async def test_dream_budget_denied_by_degradation_before_consume(monkeypatch):
    """ФИКС R4: при исчерпании global-лимита (used > limit) воркер dream
    скипается ДО consume — LLM-вызов не происходит (fake PG budget state)."""
    async def fake_usage(pg=None, scope=None):
        return [{"day": "2026-09-08", "scope": "global",
                 "metric": "llm_calls", "used": 11, "limit": 10}]
    monkeypatch.setattr(worker_budget, "get_usage", fake_usage)
    calls = []

    async def fake_consume(pg=None, scope="global", metric="llm_calls",
                           amount=1):
        calls.append((scope, metric, amount))
        return True

    monkeypatch.setattr(worker_budget, "consume", fake_consume)
    from services.dream_worker import _dream_budget_ok
    ok = await _dream_budget_ok(-10001, "некоторый текст")
    assert ok is False
    assert calls == []                       # деградация ДО бюджет-conсюма


@pytest.mark.asyncio
async def test_nostalgia_budget_allowed_then_consumes(monkeypatch):
    """ФИКС R4: nostalgia — высший приоритет: при used=limit+1 она жива."""
    async def fake_usage(pg=None, scope=None):
        return [{"day": "2026-09-08", "scope": "global",
                 "metric": "llm_calls", "used": 11, "limit": 10}]
    monkeypatch.setattr(worker_budget, "get_usage", fake_usage)
    calls = []

    async def fake_consume(pg=None, scope="global", metric="llm_calls",
                           amount=1):
        calls.append((scope, metric, amount))
        return True

    monkeypatch.setattr(worker_budget, "consume", fake_consume)
    from services.nostalgia_worker import NostalgiaWorker
    ok = await NostalgiaWorker._nostalgia_budget_ok(-10002, "текст ностальгии")
    assert ok is True
    assert calls[0][0] == "global"           # consume состоялся


def test_jitter_capped(monkeypatch):
    monkeypatch.setattr(worker_budget.hot, "get",
                        lambda key, default=None: 5)
    assert worker_budget.jitter_safe(30) == 5
    assert worker_budget.jitter_safe(9) == 3            # interval/3 cap
    assert worker_budget.jitter_safe(3) == 1
    assert worker_budget.jitter_safe(0) == 0


@pytest.fixture
def conn_holder2(request):
    class Holder:
        pass
    holder = Holder()
    conn = _FakeConn()
    holder.conn = conn
    holder.pg = _FakePg(conn)
    return holder
