"""Tests for services/search_aggregator.py (T-251, Section 42.3/42.10).

httpx.MockTransport-прецедент test_llm_client._make_client. DDG-уровень
мокается через services.search_aggregator.DDGS (sync-класс duckduckgo-search
8.x; AsyncDDGS удалён в PR#268 — не существует).
"""
import logging

import httpx
import pytest

from services.search_aggregator import (
    EXA_URL,
    TAVILY_URL,
    AllSearchEnginesFailedException,
    SearchAggregator,
)

TAVILY_HITS = {
    "results": [
        {"title": "Тайтл 1", "content": "Снипет 1", "url": "https://t.example/1"},
        {"title": "Тайтл 2", "content": "Снипет 2", "url": "https://t.example/2"},
    ]
}

EXA_HITS = {
    "results": [
        {
            "title": "Экса титл",
            "url": "https://e.example/1",
            "text": "Экса снипет",
        }
    ]
}

DDG_HITS = [
    {"title": "ДДГ титл", "href": "https://d.example/1", "body": "ДДГ снипет"},
]


class _FakeDDGS:
    """Sync-DDGS (уровень 3, duckduckgo-search 8.x) — context manager."""

    def __init__(self, timeout=None):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, query, max_results=5):
        return DDG_HITS


def _make_aggregator(handler, monkeypatch, **kwargs):
    """SearchAggregator с httpx.MockTransport (прецедент test_llm_client)."""
    requests = []

    def _tracking_handler(request):
        requests.append((str(request.url), request))
        return handler(request)

    transport = httpx.MockTransport(_tracking_handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.search_aggregator.httpx.AsyncClient", factory)
    aggregator = SearchAggregator(
        tavily_api_key=kwargs.pop("tavily_api_key", "tav-key"),
        exa_api_key=kwargs.pop("exa_api_key", "exa-key"),
        **kwargs,
    )
    return aggregator, requests


def _json_handler(payload, status=200):
    def handler(request):
        return httpx.Response(status, json=payload, request=request)

    return handler


def _error_handler(status):
    def handler(request):
        return httpx.Response(status, json={}, request=request)

    return handler


class TestCascade:
    @pytest.mark.asyncio
    async def test_tavily_success_single_request_and_format(self, monkeypatch):
        aggregator, requests = _make_aggregator(_json_handler(TAVILY_HITS), monkeypatch)
        result = await aggregator.search("запрос", 4000)
        assert requests[0][0] == TAVILY_URL
        assert len(requests) == 1
        assert result == "Тайтл 1\nСнипет 1\nhttps://t.example/1\n\nТайтл 2\nСнипет 2\nhttps://t.example/2"

    @pytest.mark.asyncio
    async def test_truncation_to_max_symbols(self, monkeypatch):
        aggregator, requests = _make_aggregator(_json_handler(TAVILY_HITS), monkeypatch)
        result = await aggregator.search("запрос", 30)
        assert len(result) == 30
        assert result == "Тайтл 1\nСнипет 1\nhttps://t.example/1"[:30]

    @pytest.mark.asyncio
    async def test_tavily_timeout_falls_back_to_exa(self, monkeypatch):
        def mixed_handler(request):
            if "tavily" in str(request.url):
                raise httpx.TimeoutException("timed out", request=request)
            return httpx.Response(200, json=EXA_HITS, request=request)

        aggregator, requests = _make_aggregator(mixed_handler, monkeypatch)
        result = await aggregator.search("запрос", 4000)
        assert [url for url, _ in requests] == [TAVILY_URL, EXA_URL]
        assert result == "Экса титл\nЭкса снипет\nhttps://e.example/1"

    @pytest.mark.asyncio
    async def test_tavily_500_falls_back_to_exa(self, monkeypatch):
        responses = [500, 200]
        payloads = [{}, EXA_HITS]

        def mixed_handler(request):
            status = responses.pop(0)
            payload = payloads.pop(0)
            return httpx.Response(status, json=payload, request=request)

        aggregator, requests = _make_aggregator(mixed_handler, monkeypatch)
        result = await aggregator.search("запрос", 4000)
        assert [url for url, _ in requests] == [TAVILY_URL, EXA_URL]
        assert "Экса снипет" in result

    @pytest.mark.asyncio
    async def test_tavily_401_falls_back_to_exa(self, monkeypatch):
        responses = [401, 200]
        payloads = [{}, EXA_HITS]

        def mixed_handler(request):
            return httpx.Response(responses.pop(0), json=payloads.pop(0), request=request)

        aggregator, requests = _make_aggregator(mixed_handler, monkeypatch)
        result = await aggregator.search("запрос", 4000)
        assert [url for url, _ in requests] == [TAVILY_URL, EXA_URL]
        assert "Экса снипет" in result

    @pytest.mark.asyncio
    async def test_tavily_empty_results_falls_back_to_exa(self, monkeypatch):
        responses = [200, 200]
        payloads = [{"results": []}, EXA_HITS]

        def mixed_handler(request):
            return httpx.Response(responses.pop(0), json=payloads.pop(0), request=request)

        aggregator, requests = _make_aggregator(mixed_handler, monkeypatch)
        result = await aggregator.search("запрос", 4000)
        assert [url for url, _ in requests] == [TAVILY_URL, EXA_URL]
        assert "Экса снипет" in result

    @pytest.mark.asyncio
    async def test_tavily_and_exa_fail_falls_back_to_ddg(self, monkeypatch):
        monkeypatch.setattr("services.search_aggregator.DDGS", _FakeDDGS)
        handler = _error_handler(500)
        aggregator, requests = _make_aggregator(handler, monkeypatch)
        result = await aggregator.search("запрос", 4000)
        assert [url for url, _ in requests] == [TAVILY_URL, EXA_URL]
        assert result == "ДДГ титл\nДДГ снипет\nhttps://d.example/1"

    @pytest.mark.asyncio
    async def test_ddg_empty_results_then_all_failed(self, monkeypatch):
        class _EmptyDDGS(_FakeDDGS):
            def text(self, query, max_results=5):
                return []

        monkeypatch.setattr("services.search_aggregator.DDGS", _EmptyDDGS)
        aggregator, requests = _make_aggregator(_error_handler(500), monkeypatch)
        with pytest.raises(AllSearchEnginesFailedException):
            await aggregator.search("запрос", 4000)
        assert len(requests) == 2  # tavily + exa; DDG без HTTP

    @pytest.mark.asyncio
    async def test_empty_tavily_key_skips_level(self, monkeypatch, caplog):
        aggregator, requests = _make_aggregator(
            _json_handler(EXA_HITS), monkeypatch, tavily_api_key=""
        )
        with caplog.at_level(logging.INFO):
            result = await aggregator.search("запрос", 4000)
        assert [url for url, _ in requests] == [EXA_URL]
        assert result == "Экса титл\nЭкса снипет\nhttps://e.example/1"
        assert any("level skipped" in r.message and "tavily" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_empty_exa_key_skips_level(self, monkeypatch, caplog):
        responses = [500]
        payloads = [{}]

        def mixed_handler(request):
            return httpx.Response(responses.pop(0), json=payloads.pop(0), request=request)

        monkeypatch.setattr("services.search_aggregator.DDGS", _FakeDDGS)
        aggregator, requests = _make_aggregator(
            mixed_handler, monkeypatch, exa_api_key=""
        )
        with caplog.at_level(logging.INFO):
            result = await aggregator.search("запрос", 4000)
        assert [url for url, _ in requests] == [TAVILY_URL]
        assert result == "ДДГ титл\nДДГ снипет\nhttps://d.example/1"
        assert any("level skipped" in r.message and "exa" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_both_keys_empty_goes_straight_to_ddg(self, monkeypatch):
        monkeypatch.setattr("services.search_aggregator.DDGS", _FakeDDGS)
        aggregator, requests = _make_aggregator(
            _error_handler(500), monkeypatch, tavily_api_key="", exa_api_key=""
        )
        result = await aggregator.search("запрос", 4000)
        assert requests == []
        assert result == "ДДГ титл\nДДГ снипет\nhttps://d.example/1"

    @pytest.mark.asyncio
    async def test_whitespace_only_key_treated_as_empty(self, monkeypatch):
        aggregator, requests = _make_aggregator(
            _json_handler(EXA_HITS), monkeypatch, tavily_api_key="   "
        )
        await aggregator.search("запрос", 4000)
        assert [url for url, _ in requests] == [EXA_URL]


class TestLifecycle:
    def test_log_config_warns_on_empty_keys(self, caplog):
        aggregator = SearchAggregator(tavily_api_key="", exa_api_key="")
        with caplog.at_level(logging.WARNING):
            aggregator.log_config()
        assert any("TAVILY_API_KEY" in r.message for r in caplog.records)
        assert any("EXA_API_KEY" in r.message for r in caplog.records)

    def test_log_config_silent_with_keys(self, caplog):
        aggregator = SearchAggregator(tavily_api_key="k", exa_api_key="k")
        with caplog.at_level(logging.WARNING):
            aggregator.log_config()
        assert caplog.records == []

    @pytest.mark.asyncio
    async def test_close_before_any_request_is_noop(self, monkeypatch):
        aggregator, _ = _make_aggregator(_error_handler(500), monkeypatch)
        await aggregator.close()
        assert aggregator._client is None

    @pytest.mark.asyncio
    async def test_close_after_request_closes_client(self, monkeypatch):
        aggregator, _ = _make_aggregator(_json_handler(TAVILY_HITS), monkeypatch)
        await aggregator.search("запрос", 4000)
        assert aggregator._client is not None
        await aggregator.close()
        assert aggregator._client is None
