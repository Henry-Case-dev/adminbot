"""Раунд 10.23 (F7, ADR-1023-7) — тесты аналитики токенов.

Покрытие (spec §6):
1. DDL PG: таблицы/индексы/сид цен (идемпотентность — см. test_pg_db).
2. Расчёт cost: известная цена → точный cost; неизвестная → 0 + price_known.
3. Запись/чтение usage-событий (только коды/числа, R17).
4. Сквозной correlation-id через tool-loop (Stage-1 → tool → Stage-2).
5. Fail-safe/fail-open: нет PG/ошибка → событие пропущено, бот жив.
6. Флаг TOKEN_ANALYTICS_ENABLED=OFF → no-op.
7. Ретенция: DELETE ... interval + дедуп.
8. API дашборда: latest (Flow node) + summary (day/week/month) + OFF-пусто.
"""
import datetime
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from unittest.mock import AsyncMock

from config.settings import Settings, settings
from services import llm_pricing, usage_events
from services import pg_db as pg_mod
from services.llm_client import LLMChatResult, LLMClient, LLMToolCall
from services.tool_loop import chat_with_tools
from web.api import analytics as analytics_api


# ── Фейковый PG (пул + соединение) ─────────────────────────────────────────

class _FakeConn:
    def __init__(self, price=None):
        self.price = price
        self.executed: list[tuple] = []
        self.fetchrow_calls: list[tuple] = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        if "llm_model_prices" in sql:
            if self.price is None:
                return None
            return {"input_usd_per_1m": Decimal(str(self.price[0])),
                    "output_usd_per_1m": Decimal(str(self.price[1]))}
        return None

    async def fetch(self, sql, *args):
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


def _fake_pg(price=None):
    conn = _FakeConn(price=price)
    return SimpleNamespace(pool=_FakePool(conn)), conn


@pytest.fixture(autouse=True)
def _reset_state():
    llm_pricing.invalidate()
    usage_events.reset_cleanup_state()
    yield
    llm_pricing.invalidate()
    usage_events.reset_cleanup_state()


# ── 1. DDL ─────────────────────────────────────────────────────────────────

class TestDdl:
    def test_usage_events_table_and_columns(self):
        ddl = " ".join(pg_mod.DDL_STATEMENTS)
        assert "CREATE TABLE IF NOT EXISTS llm_usage_events" in ddl
        table = next(s for s in pg_mod.DDL_STATEMENTS
                     if "CREATE TABLE IF NOT EXISTS llm_usage_events" in s)
        for column in ("correlation_id", "module", "step", "tool_name",
                       "source", "chat_id", "model", "input_tokens",
                       "output_tokens", "tokens_estimated", "cost_usd",
                       "price_known", "ts"):
            assert column in table
        assert "NUMERIC(12, 6)" in table

    def test_usage_events_indexes(self):
        ddl = " ".join(pg_mod.DDL_STATEMENTS)
        assert "idx_llm_usage_events_ts" in ddl
        assert "idx_llm_usage_events_corr" in ddl
        assert "idx_llm_usage_events_module_ts" in ddl

    def test_model_prices_table_and_seed(self):
        table = next(s for s in pg_mod.DDL_STATEMENTS
                     if "CREATE TABLE IF NOT EXISTS llm_model_prices" in s)
        assert "input_usd_per_1m" in table
        assert "output_usd_per_1m" in table
        seeds = [s for s in pg_mod.DDL_STATEMENTS
                 if "INSERT INTO llm_model_prices" in s]
        assert len(seeds) == 1
        assert "ON CONFLICT (model) DO NOTHING" in seeds[0]


# ── 2. Расчёт стоимости ────────────────────────────────────────────────────

class TestPricing:
    def test_known_price_exact_cost(self):
        cost, known = llm_pricing.compute_cost((0.27, 1.10), 4000, 600)
        # 4000/1e6*0.27 + 600/1e6*1.10 = 0.00108 + 0.00066
        assert known is True
        assert cost == pytest.approx(0.00174, abs=1e-9)

    def test_unknown_price_fail_safe(self):
        cost, known = llm_pricing.compute_cost(None, 4000, 600)
        assert cost == 0.0
        assert known is False

    def test_zero_tokens_known_price(self):
        cost, known = llm_pricing.compute_cost((1.0, 2.0), 0, 0)
        assert (cost, known) == (0.0, True)

    @pytest.mark.asyncio
    async def test_resolve_price_reads_and_caches(self):
        pg, conn = _fake_pg(price=(0.15, 0.60))
        price = await llm_pricing.resolve_price(pg, "m1")
        assert price == (0.15, 0.60)
        # второй вызов — из кэша (без нового SELECT)
        calls_before = len(conn.fetchrow_calls)
        assert await llm_pricing.resolve_price(pg, "m1") == (0.15, 0.60)
        assert len(conn.fetchrow_calls) == calls_before
        # invalidate → снова читаем
        llm_pricing.invalidate("m1")
        await llm_pricing.resolve_price(pg, "m1")
        assert len(conn.fetchrow_calls) == calls_before + 1

    @pytest.mark.asyncio
    async def test_resolve_price_unknown_model_none(self):
        pg, _ = _fake_pg(price=None)
        assert await llm_pricing.resolve_price(pg, "unknown") is None

    @pytest.mark.asyncio
    async def test_resolve_price_no_pg_none(self):
        assert await llm_pricing.resolve_price(None, "m") is None


# ── 3. Запись usage-событий ────────────────────────────────────────────────

class TestUsageEvents:
    def test_new_correlation_id_hex32(self):
        cid = usage_events.new_correlation_id()
        assert isinstance(cid, str) and len(cid) == 32
        assert cid != usage_events.new_correlation_id()
        int(cid, 16)          # валидный hex

    def test_resolve_token_counts_prefers_real_usage(self):
        tokens = usage_events.resolve_token_counts(
            {"prompt_tokens": 4000, "completion_tokens": 600},
            [{"content": "x"}], "y")
        assert tokens == (4000, 600, False)

    def test_resolve_token_counts_estimates_without_usage(self):
        in_t, out_t, estimated = usage_events.resolve_token_counts(
            None, [{"role": "user", "content": "abcdefghij"}], "ответ")
        assert estimated is True
        assert in_t > 0 and out_t > 0

    @pytest.mark.asyncio
    async def test_record_writes_enriched_row(self):
        pg, conn = _fake_pg(price=(0.27, 1.10))
        await usage_events.record(
            pg, module="direct_chat", step="stage1", correlation_id="abc",
            source="global", chat_id=5, model="m1",
            input_tokens=4000, output_tokens=600)
        inserts = [q for q in conn.executed if "INSERT INTO llm_usage_events" in q[0]]
        assert len(inserts) == 1
        args = inserts[0][1]
        # порядок колонок: corr, module, step, tool_name, source, chat_id, model,
        # input, output, estimated, cost, price_known
        assert args[0] == "abc"
        assert args[1] == "direct_chat"
        assert args[2] == "stage1"
        assert args[4] == "global"
        assert args[5] == 5
        assert args[7] == 4000 and args[8] == 600
        assert args[9] is False
        assert args[10] == pytest.approx(0.00174)
        assert args[11] is True

    @pytest.mark.asyncio
    async def test_record_unknown_price_flags(self):
        pg, conn = _fake_pg(price=None)
        await usage_events.record(
            pg, module="summary", step="stage2", correlation_id="c",
            model="no-price", input_tokens=100, output_tokens=50)
        args = [q for q in conn.executed
                if "INSERT INTO llm_usage_events" in q[0]][0][1]
        assert args[10] == 0.0          # cost_usd
        assert args[11] is False        # price_known=false

    @pytest.mark.asyncio
    async def test_record_fail_open_on_pg_error(self):
        class _Boom:
            def acquire(self):
                raise RuntimeError("pg down")

        await usage_events.record(
            SimpleNamespace(pool=_Boom()), module="x", step="single")
        # не должно бросить

    @pytest.mark.asyncio
    async def test_record_no_pg_is_noop(self):
        await usage_events.record(None, module="x", step="single")

    @pytest.mark.asyncio
    async def test_record_disabled_switch(self, monkeypatch):
        monkeypatch.setattr(Settings, "TOKEN_ANALYTICS_ENABLED", False)
        pg, conn = _fake_pg(price=(1.0, 1.0))
        await usage_events.record(pg, module="x", step="single",
                                  input_tokens=10, output_tokens=10)
        assert conn.executed == []

    def test_normalize_source(self):
        assert usage_events.normalize_source("byok") == "byok"
        assert usage_events.normalize_source("image") == "image"
        assert usage_events.normalize_source("hack") == "global"
        assert usage_events.normalize_source(None) == "global"


# ── 7. Ретенция ────────────────────────────────────────────────────────────

class TestRetention:
    @pytest.mark.asyncio
    async def test_cleanup_delete_sql_with_days(self, monkeypatch):
        monkeypatch.setattr(Settings, "TOKEN_ANALYTICS_RETENTION_DAYS", 30)
        pg, conn = _fake_pg(price=None)
        done = await usage_events.maybe_cleanup(pg.pool, force=True)
        assert done is True
        deletes = [q for q in conn.executed if "DELETE FROM llm_usage_events" in q[0]]
        assert len(deletes) == 1
        assert deletes[0][1] == (30,)

    @pytest.mark.asyncio
    async def test_cleanup_deduplicated(self):
        pg, conn = _fake_pg(price=None)
        assert await usage_events.maybe_cleanup(pg.pool, force=False) is True
        # без force повтор в пределах интервала — no-op
        assert await usage_events.maybe_cleanup(pg.pool, force=False) is False
        deletes = [q for q in conn.executed if "DELETE FROM llm_usage_events" in q[0]]
        assert len(deletes) == 1

    def test_retention_days_safe_default(self, monkeypatch):
        monkeypatch.setattr(Settings, "TOKEN_ANALYTICS_RETENTION_DAYS", 0)
        assert usage_events.retention_days() == 90


# ── 4. Сквозной correlation-id через tool-loop ─────────────────────────────

class _CapLLM:
    def __init__(self):
        self.calls = []

    async def generate_chat(self, messages, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(id="c1", name="query_chat_memory",
                                        arguments='{"query": "x"}')],
                finish_reason="tool_calls")
        return LLMChatResult(content="финал", tool_calls=None,
                             finish_reason="stop")


class _Router:
    async def dispatch(self, name, arguments, ctx):
        return "tool-out"


class TestCorrelationThroughToolLoop:
    @pytest.mark.asyncio
    async def test_stage1_then_tool_share_correlation_id(self):
        llm = _CapLLM()
        ctx = SimpleNamespace()
        out = await chat_with_tools(
            llm, [{"role": "user", "content": "q"}],
            tools=[{"type": "function"}], router=_Router(), ctx=ctx,
            module="direct_chat", correlation_id="corr-1")
        assert str(out) == "финал"
        assert len(llm.calls) == 2
        assert llm.calls[0]["step"] == "stage1"
        assert llm.calls[1]["step"] == "tool"
        assert all(c["correlation_id"] == "corr-1" for c in llm.calls)
        assert all(c["module"] == "direct_chat" for c in llm.calls)

    @pytest.mark.asyncio
    async def test_backward_compat_without_kwargs(self):
        llm = _CapLLM()
        out = await chat_with_tools(
            llm, [{"role": "user", "content": "q"}],
            tools=[{"type": "function"}], router=_Router(), ctx=SimpleNamespace())
        assert str(out) == "финал"
        assert llm.calls[0]["correlation_id"] is None


# ── LLMClient: реальные токены + проброс correlation-id ────────────────────

def _client(handler, monkeypatch):
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    client = LLMClient("https://api.test/v1", "k", "chat-model", "embed-model")
    client.backoff_base = 0
    return client


class TestLLMClientAnalytics:
    @pytest.mark.asyncio
    async def test_generate_records_real_usage(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "ок"}}],
                "usage": {"prompt_tokens": 4000, "completion_tokens": 600},
            }, request=request)

        client = _client(handler, monkeypatch)
        record = AsyncMock()
        monkeypatch.setattr(
            "services.usage_events.record", record)
        await client.generate(
            [{"role": "user", "content": "hi"}], module="direct_chat",
            step="stage1", correlation_id="cid-9")
        assert record.await_count == 1
        kwargs = record.await_args.kwargs
        assert kwargs["correlation_id"] == "cid-9"
        assert kwargs["module"] == "direct_chat"
        assert kwargs["step"] == "stage1"
        assert kwargs["input_tokens"] == 4000
        assert kwargs["output_tokens"] == 600
        assert kwargs["tokens_estimated"] is False

    @pytest.mark.asyncio
    async def test_generate_fallback_estimates_without_usage(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "ответ"}}]}, request=request)

        client = _client(handler, monkeypatch)
        record = AsyncMock()
        monkeypatch.setattr("services.usage_events.record", record)
        await client.generate([{"role": "user", "content": "привет"}])
        kwargs = record.await_args.kwargs
        assert kwargs["tokens_estimated"] is True
        assert kwargs["input_tokens"] > 0
        assert kwargs["step"] == "single"       # default

    @pytest.mark.asyncio
    async def test_analytics_failure_does_not_break_generate(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "ок"}}]}, request=request)

        client = _client(handler, monkeypatch)
        monkeypatch.setattr("services.usage_events.record",
                            AsyncMock(side_effect=RuntimeError("boom")))
        out = await client.generate([{"role": "user", "content": "q"}])
        assert out == "ок"


# ── 5. Бюджетный контур не сломан ──────────────────────────────────────────

class TestBudgetUntouched:
    def test_chat_usage_report_call_source_global_unchanged(self):
        # `_record_global_usage` по-прежнему пропускает только source='global'
        import inspect
        from services.llm_client import LLMClient as C
        src = inspect.getsource(C._record_global_usage)
        assert 'source != "global"' in src
        # аналитика — отдельный метод, бюджетный не переписан
        assert "_record_analytics" in inspect.getsource(C)


# ── 8. API дашборда ────────────────────────────────────────────────────────

class _ApiConn:
    def __init__(self, *, latest=None, steps=None, totals=None,
                 modules=None, series=None, prices=None):
        self.latest = latest
        self.steps = steps or []
        self.totals = totals
        self.modules = modules or []
        self.series = series or []
        self.prices = prices or []

    async def fetchrow(self, sql, *args):
        if "ORDER BY ts DESC" in sql:
            return self.latest
        if "COUNT(*) AS calls" in sql:
            return self.totals
        return None

    async def fetch(self, sql, *args):
        if "correlation_id = $1" in sql:
            return self.steps
        if "GROUP BY module" in sql:
            return self.modules
        if "date_trunc" in sql:
            return self.series
        if "FROM llm_model_prices" in sql:
            return self.prices
        return []

    async def execute(self, sql, *args):
        return "OK"


class _ApiPool:
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


def _api_request(pool):
    cache = SimpleNamespace(pg=SimpleNamespace(pool=pool))
    app = SimpleNamespace(state=SimpleNamespace(cache=cache))
    return SimpleNamespace(app=app)


def _ts():
    return datetime.datetime(2026, 9, 19, 12, 0, 0)


class TestAnalyticsApi:
    @pytest.mark.asyncio
    async def test_latest_flow_node(self):
        conn = _ApiConn(
            latest={"correlation_id": "cid", "ts": _ts()},
            steps=[
                {"ts": _ts(), "module": "direct_chat", "step": "stage1",
                 "tool_name": "", "source": "global", "model": "m",
                 "input_tokens": 4000, "output_tokens": 600,
                 "tokens_estimated": False,
                 "cost_usd": Decimal("0.00174"), "price_known": True},
                {"ts": _ts(), "module": "direct_chat", "step": "stage2",
                 "tool_name": "", "source": "global", "model": "m",
                 "input_tokens": 600, "output_tokens": 200,
                 "tokens_estimated": False,
                 "cost_usd": Decimal("0.0003"), "price_known": True},
            ])
        res = await analytics_api.usage_latest(_api_request(_ApiPool(conn)),
                                               user=SimpleNamespace(id=1))
        assert res["correlation_id"] == "cid"
        assert len(res["steps"]) == 2
        assert res["total"]["input_tokens"] == 4600
        assert res["total"]["cost_usd"] == pytest.approx(0.00204)
        # R17: никакого сырого текста — только коды/числа
        assert set(res["steps"][0]) >= {"module", "step", "input_tokens"}

    @pytest.mark.asyncio
    async def test_latest_empty_when_no_events(self):
        conn = _ApiConn(latest=None)
        res = await analytics_api.usage_latest(_api_request(_ApiPool(conn)),
                                               user=SimpleNamespace(id=1))
        assert res["correlation_id"] == ""
        assert res["steps"] == []

    @pytest.mark.asyncio
    async def test_summary_day(self):
        conn = _ApiConn(
            totals={"cost_usd": Decimal("1.5"), "input_tokens": 100,
                    "output_tokens": 50, "calls": 3},
            modules=[{"module": "direct_chat", "cost_usd": Decimal("1.5"),
                      "input_tokens": 100, "output_tokens": 50, "calls": 3}],
            series=[{"bucket": _ts(), "cost_usd": Decimal("1.5"),
                     "input_tokens": 100, "output_tokens": 50, "calls": 3}])
        res = await analytics_api.usage_summary(
            _api_request(_ApiPool(conn)), user=SimpleNamespace(id=1),
            period="day")
        assert res["period"] == "day"
        assert res["totals"]["calls"] == 3
        assert res["by_module"][0]["module"] == "direct_chat"
        assert res["series"][0]["cost_usd"] == 1.5

    @pytest.mark.asyncio
    async def test_summary_unknown_period_falls_back_to_day(self):
        conn = _ApiConn(totals={"cost_usd": 0, "input_tokens": 0,
                                "output_tokens": 0, "calls": 0})
        res = await analytics_api.usage_summary(
            _api_request(_ApiPool(conn)), user=SimpleNamespace(id=1),
            period="bogus")
        assert res["period"] == "day"

    @pytest.mark.asyncio
    async def test_off_returns_empty_shape(self, monkeypatch):
        monkeypatch.setattr(Settings, "TOKEN_ANALYTICS_ENABLED", False)
        conn = _ApiConn(latest={"correlation_id": "x", "ts": _ts()})
        req = _api_request(_ApiPool(conn))
        latest = await analytics_api.usage_latest(req, user=SimpleNamespace(id=1))
        summary = await analytics_api.usage_summary(
            req, user=SimpleNamespace(id=1), period="week")
        assert latest == {"correlation_id": "", "ts": None, "steps": [],
                          "total": {"input_tokens": 0, "output_tokens": 0,
                                    "cost_usd": 0.0, "calls": 0}}
        assert summary["totals"]["calls"] == 0
        assert summary["period"] == "week"

    @pytest.mark.asyncio
    async def test_no_pg_returns_empty(self):
        res = await analytics_api.usage_latest(
            _api_request(None), user=SimpleNamespace(id=1))
        assert res["steps"] == []
