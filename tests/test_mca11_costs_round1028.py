"""MCA-11 `mca-11-tools-costs` — focused блок B (T-4950…T-4952).

Покрытие: учёт расходов (unknown ≠ 0), разрезы чат/операция/trigger/модель/
provider (существующий леджер `llm_usage_events` + агрегатор
`execution_graph_source`), единицы/область/значение/причина лимитов,
точка записи embeddings (K3-gated).
"""
import hashlib
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from config.settings import Settings, settings
from services import execution_graph_source as egs
from services import llm_pricing, tool_result, usage_events
from services.llm_client import LLMClient


# ── фейковый PG (пул + соединение) ──────────────────────────────────────────

class _FakeConn:
    def __init__(self, price=None):
        self.price = price
        self.executed: list[tuple] = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

    async def fetchrow(self, sql, *args):
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


# ── T-4950: unknown ≠ 0 ─────────────────────────────────────────────────────

class TestUnknownNotZero:
    def test_compute_cost_unknown_is_not_zero_claim(self):
        assert llm_pricing.compute_cost(None, 100, 50) == (0.0, False)
        cost, known = llm_pricing.compute_cost((0.15, 0.60), 1000, 100)
        assert known is True and cost == pytest.approx(0.00021)

    def test_price_version_known_and_unknown(self):
        assert llm_pricing.price_version("m", None) == "unknown"
        version = llm_pricing.price_version("m", (0.15, 0.60))
        expected = hashlib.sha1("m|0.15|0.6".encode("utf-8")).hexdigest()[:12]
        assert version == f"price:{expected}"
        assert llm_pricing.price_version("m", (0.15, 0.60)) == version

    @pytest.mark.asyncio
    async def test_record_unknown_price_row(self):
        pg, conn = _fake_pg(price=None)
        await usage_events.record(pg, module="embedding", step="embed",
                                  source="embedding", model="no-price",
                                  input_tokens=100, output_tokens=0)
        args = [q for q in conn.executed
                if "INSERT INTO llm_usage_events" in q[0]][0][1]
        assert args[4] == "embedding"
        assert args[10] == 0.0          # placeholder, не заявление о цене
        assert args[11] is False        # price_known=false → unknown

    def test_usage_detail_unknown_not_zero(self):
        detail = tool_result.usage_detail(
            {"input_tokens": 0, "output_tokens": 0, "cost_usd": None,
             "price_known": False, "source": "image"},
            source="image")
        assert detail["cost_usd"] is None
        assert detail["price_known"] is False
        assert detail["price_version"] == "unknown"
        assert detail["currency"] == "USD"
        assert detail["source"] == "image"
        assert detail["tokens_estimated"] is False

    def test_aggregate_unknown_cost_is_none_not_zero(self):
        """Единственный агрегатор (`execution_graph_source`) честно даёт None."""
        node = egs._agentic_text_generation_node("run-1", [{
            "step": "single", "input_tokens": 10, "output_tokens": 5,
            "cost_usd": 0.0, "price_known": False, "model": "m"}])
        assert node is not None
        assert node["cost"] is None
        assert node["priceKnown"] is False

    def test_aggregate_known_cost_present(self):
        node = egs._agentic_text_generation_node("run-1", [{
            "step": "single", "input_tokens": 10, "output_tokens": 5,
            "cost_usd": 0.25, "price_known": True, "model": "m"}])
        assert node["cost"] == 0.25
        assert node["priceKnown"] is True


# ── T-4950: разрезы/точки записи ────────────────────────────────────────────

class TestSlices:
    def test_sources_include_embedding_and_media(self):
        assert "embedding" in usage_events.SOURCES
        assert "media" in usage_events.SOURCES
        assert usage_events.normalize_source("embedding") == "embedding"
        assert usage_events.normalize_source("media") == "media"
        # Существующие источники не изменились.
        assert {"global", "chat", "byok", "worker", "image"} <= \
            set(usage_events.SOURCES)

    def test_k3_gate_default_on(self):
        assert usage_events.cost_accounting_enabled() is True
        assert tool_result.cost_accounting_enabled() is True

    def test_k3_off_gate(self, monkeypatch):
        monkeypatch.setattr(Settings, "MCA_COST_ACCOUNTING_ENABLED", False)
        assert usage_events.cost_accounting_enabled() is False

    def test_single_analytics_collector_reused(self):
        """Второй сборщик запрещён: аналитика читает существующие контуры."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        analytics = (root / "web/api/analytics.py").read_text(encoding="utf-8")
        assert "execution_graph_source" in analytics
        assert "usage_events" in analytics
        assert "GROUP BY module" in analytics
        # Разрез виден по существующим строкам: source/model/chat_id/step.
        assert "source, model" in analytics
        assert "chat_id" in analytics
        # Агрегаты честные: BOOL_AND(price_known) — unknown не ноль.
        assert "BOOL_AND(price_known)" in analytics

    def test_reason_code_cost_unknown_exactly_one(self):
        from services import mca_events
        assert "cost_unknown" in mca_events.REASON_CODES
        assert list(mca_events.REASON_CODES).count("cost_unknown") == 1


class TestEmbeddingWritePoint:
    def _client(self, handler, monkeypatch):
        transport = httpx.MockTransport(handler)
        original = httpx.AsyncClient

        def factory(**kw):
            return original(transport=transport, **kw)

        monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
        client = LLMClient("https://api.test/v1", "k", "chat-model",
                           "embed-model")
        client.backoff_base = 0
        return client

    @pytest.mark.asyncio
    async def test_embed_records_usage_event(self, monkeypatch):
        def handler(request):
            assert str(request.url).endswith("/embeddings")
            return httpx.Response(200, json={
                "data": [{"embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 120},
            }, request=request)

        client = self._client(handler, monkeypatch)
        from unittest.mock import AsyncMock
        record = AsyncMock()
        monkeypatch.setattr("services.usage_events.record", record)
        vectors = await client.embed(["привет"])
        assert vectors == [[0.1, 0.2]]
        assert record.await_count == 1
        kwargs = record.await_args.kwargs
        assert kwargs["source"] == "embedding"
        assert kwargs["module"] == "embedding"
        assert kwargs["step"] == "embed"
        assert kwargs["model"] == "embed-model"
        assert kwargs["input_tokens"] == 120
        assert kwargs["output_tokens"] == 0
        assert kwargs["tokens_estimated"] is False

    @pytest.mark.asyncio
    async def test_embed_without_usage_estimates(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json={
                "data": [{"embedding": [1.0]}]}, request=request)

        client = self._client(handler, monkeypatch)
        from unittest.mock import AsyncMock
        record = AsyncMock()
        monkeypatch.setattr("services.usage_events.record", record)
        await client.embed(["некоторый текст"])
        kwargs = record.await_args.kwargs
        assert kwargs["tokens_estimated"] is True
        assert kwargs["input_tokens"] > 0

    @pytest.mark.asyncio
    async def test_k3_off_no_new_write_point(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json={
                "data": [{"embedding": [1.0]}],
                "usage": {"prompt_tokens": 10}}, request=request)

        monkeypatch.setattr(Settings, "MCA_COST_ACCOUNTING_ENABLED", False)
        client = self._client(handler, monkeypatch)
        from unittest.mock import AsyncMock
        record = AsyncMock()
        monkeypatch.setattr("services.usage_events.record", record)
        await client.embed(["текст"])
        assert record.await_count == 0

    @pytest.mark.asyncio
    async def test_analytics_failure_does_not_break_embed(self, monkeypatch):
        def handler(request):
            return httpx.Response(200, json={
                "data": [{"embedding": [2.0]}]}, request=request)

        client = self._client(handler, monkeypatch)
        from unittest.mock import AsyncMock
        monkeypatch.setattr("services.usage_events.record",
                            AsyncMock(side_effect=RuntimeError("boom")))
        assert await client.embed(["x"]) == [[2.0]]


# ── T-4951: единицы/область/значение/причина ────────────────────────────────

class TestUnitsScopeReason:
    def test_limit_kinds_distinguish_purposes(self):
        finance = tool_result.limit_record("money", 1.5,
                                           "financial_limit_reached")
        assert finance == {"kind": "money", "unit": "usd",
                           "scope": "operation", "value": 1.5,
                           "reason": "financial_limit_reached"}
        assert tool_result.limit_record("context_tokens", 10)["unit"] == "tokens"
        assert tool_result.limit_record("concurrency", 2)["unit"] == "slots"
        assert tool_result.limit_record("payload_size", 10)["unit"] == "bytes"
        assert tool_result.limit_record("tool_chain_deadline", 3)["unit"] == \
            "seconds"
        assert tool_result.limit_record("antispam", 1)["unit"] == "events"
        assert tool_result.limit_record("freshness", 5)["unit"] == "seconds"
        # Финансы не смешаны с вызовами/токенами/deadline.
        units = {tool_result.limit_record(k, 1)["unit"]
                 for k in ("money", "tool_calls", "context_tokens",
                           "tool_chain_deadline", "antispam")}
        assert units == {"usd", "calls", "tokens", "seconds", "events"}

    def test_chain_limit_record_reason_and_value(self):
        record = tool_result.limit_record("tool_calls", 6, "chain_call_limit")
        assert record["unit"] == "calls" and record["scope"] == "chain"
        assert record["value"] == 6 and record["reason"] == "chain_call_limit"

    def test_usage_detail_price_version_passthrough(self):
        detail = tool_result.usage_detail(
            {"input_tokens": 5, "output_tokens": 2, "cost_usd": 0.1,
             "price_known": True, "source": "global"},
            price_version="price:abc123", tokens_estimated=True)
        assert detail["price_version"] == "price:abc123"
        assert detail["cost_usd"] == 0.1
        assert detail["price_known"] is True
        assert detail["tokens_estimated"] is True
