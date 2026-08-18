"""Tests for services/jina_reader.py (T-289, R37-3, D127, Section 46.5/46.12).

httpx.MockTransport с monkeypatch-фабрикой httpx.AsyncClient (прецедент
test_search_aggregator.py). Ретраи ТОЛЬКО на 429/5xx/timeout (≤2, backoff
0.5·2ⁿ); 401/403/404 — мгновенный фейл; пустое тело → JinaReaderException.
"""
import httpx
import pytest

from services.jina_reader import JINA_BASE_URL, JinaReader, JinaReaderException

TARGET = "https://example.com/article"


def _make_reader(handler, monkeypatch, **kwargs):
    """JinaReader с httpx.MockTransport; requests — список (url, request)."""
    requests = []

    def _tracking_handler(request):
        requests.append((str(request.url), request))
        return handler(request)

    transport = httpx.MockTransport(_tracking_handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.jina_reader.httpx.AsyncClient", factory)
    reader = JinaReader(api_key=kwargs.pop("api_key", ""))
    reader.backoff_base = kwargs.pop("backoff_base", 0.0)   # без реальных sleep
    return reader, requests


def _ok_handler(body="markdown текст"):
    def handler(request):
        return httpx.Response(200, text=body, request=request)

    return handler


def _status_handler(*statuses):
    statuses = list(statuses)

    def handler(request):
        return httpx.Response(statuses.pop(0), text="", request=request)

    return handler


class TestSuccess:
    @pytest.mark.asyncio
    async def test_200_returns_markdown_and_url_and_headers(self, monkeypatch):
        """#12: текст; URL == r.jina.ai/{target}; X-Return-Format/X-Target-Selector."""
        reader, requests = _make_reader(_ok_handler("содержимое страницы"), monkeypatch)
        result = await reader.fetch_markdown(TARGET, 4000)
        assert result == "содержимое страницы"
        url, request = requests[0]
        assert url == f"{JINA_BASE_URL}/{TARGET}"
        assert request.headers["X-Return-Format"] == "markdown"
        assert request.headers["X-Target-Selector"] == "article, main, body"

    @pytest.mark.asyncio
    async def test_auth_header_with_api_key(self, monkeypatch):
        """#13a: Authorization Bearer при непустом ключе."""
        reader, requests = _make_reader(
            _ok_handler(), monkeypatch, api_key="secret-key"
        )
        await reader.fetch_markdown(TARGET, 4000)
        assert requests[0][1].headers["Authorization"] == "Bearer secret-key"

    @pytest.mark.asyncio
    async def test_no_auth_header_without_api_key(self, monkeypatch):
        """#13b: без ключа Authorization отсутствует."""
        reader, requests = _make_reader(_ok_handler(), monkeypatch, api_key="")
        await reader.fetch_markdown(TARGET, 4000)
        assert "Authorization" not in requests[0][1].headers

    @pytest.mark.asyncio
    async def test_truncate_to_max_symbols(self, monkeypatch):
        """#19: жёсткий срез до лимита."""
        reader, _ = _make_reader(_ok_handler("x" * 5000), monkeypatch)
        result = await reader.fetch_markdown(TARGET, 100)
        assert len(result) == 100


class TestInstantFail:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403, 404])
    async def test_auth_and_not_found_fail_immediately(self, monkeypatch, status):
        """#14: 401/403/404 → JinaReaderException, РОВНО 1 запрос (без ретраев)."""
        reader, requests = _make_reader(_status_handler(status), monkeypatch)
        with pytest.raises(JinaReaderException):
            await reader.fetch_markdown(TARGET, 4000)
        assert len(requests) == 1


class TestRetries:
    @pytest.mark.asyncio
    async def test_429_twice_then_200_success_three_requests(self, monkeypatch):
        """#15: 429,429,200 → успех, 3 запроса (2 ретрая)."""
        statuses = [429, 429, 200]
        reader, requests = _make_reader(
            lambda request: httpx.Response(
                statuses.pop(0), text="текст", request=request
            ),
            monkeypatch,
        )
        result = await reader.fetch_markdown(TARGET, 4000)
        assert result == "текст"
        assert len(requests) == 3

    @pytest.mark.asyncio
    async def test_500_three_times_fails_after_retries(self, monkeypatch):
        """#16: 500 ×3 → JinaReaderException, 3 запроса."""
        statuses = [500, 500, 500]
        reader, requests = _make_reader(
            lambda request: httpx.Response(
                statuses.pop(0), text="", request=request
            ),
            monkeypatch,
        )
        with pytest.raises(JinaReaderException):
            await reader.fetch_markdown(TARGET, 4000)
        assert len(requests) == 3

    @pytest.mark.asyncio
    async def test_502_after_one_429_exhausted(self, monkeypatch):
        statuses = [429, 502, 502]
        reader, requests = _make_reader(
            lambda request: httpx.Response(
                statuses.pop(0), text="", request=request
            ),
            monkeypatch,
        )
        with pytest.raises(JinaReaderException):
            await reader.fetch_markdown(TARGET, 4000)
        assert len(requests) == 3

    @pytest.mark.asyncio
    async def test_timeout_then_200_success(self, monkeypatch):
        """#17: timeout → 200: успех после ретрая."""
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.TimeoutException("timed out", request=request)
            return httpx.Response(200, text="после таймаута", request=request)

        reader, requests = _make_reader(handler, monkeypatch)
        result = await reader.fetch_markdown(TARGET, 4000)
        assert result == "после таймаута"
        assert len(requests) == 2

    @pytest.mark.asyncio
    async def test_all_timeouts_fail(self, monkeypatch):
        def handler(request):
            raise httpx.TimeoutException("timed out", request=request)

        reader, requests = _make_reader(handler, monkeypatch)
        with pytest.raises(JinaReaderException):
            await reader.fetch_markdown(TARGET, 4000)
        assert len(requests) == 3

    @pytest.mark.asyncio
    async def test_transport_error_fails_immediately(self, monkeypatch):
        def handler(request):
            raise httpx.ConnectError("no route", request=request)

        reader, requests = _make_reader(handler, monkeypatch)
        with pytest.raises(JinaReaderException):
            await reader.fetch_markdown(TARGET, 4000)
        assert len(requests) == 1


class TestEmptyBody:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("body", ["", "   ", "\n\t"])
    async def test_empty_body_raises_without_retry(self, monkeypatch, body):
        """#18: 200 с пустым/пробельным телом → JinaReaderException, 1 запрос."""
        reader, requests = _make_reader(_ok_handler(body), monkeypatch)
        with pytest.raises(JinaReaderException):
            await reader.fetch_markdown(TARGET, 4000)
        assert len(requests) == 1


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close_before_request_is_noop(self, monkeypatch):
        """#20a: close() до запроса — no-op."""
        reader, _ = _make_reader(_ok_handler(), monkeypatch)
        await reader.close()
        assert reader._client is None

    @pytest.mark.asyncio
    async def test_close_after_request_closes_client(self, monkeypatch):
        """#20b: close() после запроса — клиент закрыт."""
        reader, _ = _make_reader(_ok_handler(), monkeypatch)
        await reader.fetch_markdown(TARGET, 4000)
        assert reader._client is not None
        await reader.close()
        assert reader._client is None
