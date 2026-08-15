"""Tests for services/llm_client.py (T-178, Section 33.4)."""
import json

import httpx
import pytest

from services.llm_client import (
    LLMAuthError,
    LLMBadResponseError,
    LLMClient,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)


def _make_client(handler, monkeypatch, **kwargs):
    """LLMClient backed by httpx.MockTransport; backoff sleeps disabled."""
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    client = LLMClient(
        "https://api.test/v1", "test-key", "chat-model", "embed-model", **kwargs
    )
    client.backoff_base = 0
    return client


def _json_handler(payload):
    def handler(request):
        return httpx.Response(200, json=payload, request=request)

    return handler


class TestGenerate:
    @pytest.mark.asyncio
    async def test_generate_success(self, monkeypatch):
        client = _make_client(
            _json_handler({"choices": [{"message": {"content": "привет чат"}}]}),
            monkeypatch,
        )
        result = await client.generate(
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
        )
        assert result == "привет чат"

    @pytest.mark.asyncio
    async def test_generate_request_shape(self, monkeypatch):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ок"}}]},
                request=request,
            )

        client = _make_client(handler, monkeypatch)
        await client.generate([{"role": "user", "content": "q"}])
        assert seen["url"] == "https://api.test/v1/chat/completions"
        assert seen["auth"] == "Bearer test-key"
        assert seen["payload"]["model"] == "chat-model"
        assert seen["payload"]["messages"] == [{"role": "user", "content": "q"}]

    @pytest.mark.asyncio
    async def test_generate_401_raises_auth(self, monkeypatch):
        client = _make_client(
            lambda request: httpx.Response(401, json={}, request=request), monkeypatch
        )
        with pytest.raises(LLMAuthError):
            await client.generate([{"role": "user", "content": "q"}])

    @pytest.mark.asyncio
    async def test_generate_403_raises_auth(self, monkeypatch):
        client = _make_client(
            lambda request: httpx.Response(403, json={}, request=request), monkeypatch
        )
        with pytest.raises(LLMAuthError):
            await client.generate([{"role": "user", "content": "q"}])

    @pytest.mark.asyncio
    async def test_generate_429_retry_then_success(self, monkeypatch):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, json={}, request=request)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "после ретрая"}}]},
                request=request,
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "после ретрая"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_generate_429_always_raises_rate_limit(self, monkeypatch):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        with pytest.raises(LLMRateLimitError):
            await client.generate([{"role": "user", "content": "q"}])
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_generate_500_retry_then_success(self, monkeypatch):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] < 2:
                return httpx.Response(500, json={}, request=request)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ок"}}]},
                request=request,
            )

        client = _make_client(handler, monkeypatch, max_retries=3)
        result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ок"

    @pytest.mark.asyncio
    async def test_generate_timeout_raises_timeout_error(self, monkeypatch):
        def handler(request):
            raise httpx.TimeoutException("timed out", request=request)

        client = _make_client(handler, monkeypatch, max_retries=1)
        with pytest.raises(LLMTimeoutError):
            await client.generate([{"role": "user", "content": "q"}])

    @pytest.mark.asyncio
    async def test_generate_bad_json_raises_bad_response(self, monkeypatch):
        client = _make_client(
            lambda request: httpx.Response(200, text="не json", request=request),
            monkeypatch,
        )
        with pytest.raises(LLMBadResponseError):
            await client.generate([{"role": "user", "content": "q"}])

    @pytest.mark.asyncio
    async def test_generate_missing_content_raises_bad_response(self, monkeypatch):
        client = _make_client(_json_handler({"choices": [{"message": {}}]}), monkeypatch)
        with pytest.raises(LLMBadResponseError):
            await client.generate([{"role": "user", "content": "q"}])

    @pytest.mark.asyncio
    async def test_generate_empty_content_raises_bad_response(self, monkeypatch):
        client = _make_client(
            _json_handler({"choices": [{"message": {"content": "   "}}]}), monkeypatch
        )
        with pytest.raises(LLMBadResponseError):
            await client.generate([{"role": "user", "content": "q"}])


class TestEmbed:
    @pytest.mark.asyncio
    async def test_embed_success(self, monkeypatch):
        payload = {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
        client = _make_client(_json_handler(payload), monkeypatch)
        vectors = await client.embed(["a", "b"])
        assert vectors == [[0.1, 0.2], [0.3, 0.4]]

    @pytest.mark.asyncio
    async def test_embed_request_shape(self, monkeypatch):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200, json={"data": [{"embedding": [1.0]}]}, request=request
            )

        client = _make_client(handler, monkeypatch)
        await client.embed(["текст"])
        assert seen["url"] == "https://api.test/v1/embeddings"
        assert seen["payload"] == {"model": "embed-model", "input": ["текст"]}

    @pytest.mark.asyncio
    async def test_embed_empty_texts(self, monkeypatch):
        client = _make_client(lambda r: httpx.Response(500), monkeypatch)
        assert await client.embed([]) == []

    @pytest.mark.asyncio
    async def test_embed_bad_json_raises_bad_response(self, monkeypatch):
        client = _make_client(
            lambda request: httpx.Response(200, text="нет", request=request), monkeypatch
        )
        with pytest.raises(LLMBadResponseError):
            await client.embed(["a"])

    @pytest.mark.asyncio
    async def test_embed_auth_error(self, monkeypatch):
        client = _make_client(
            lambda request: httpx.Response(401, json={}, request=request), monkeypatch
        )
        with pytest.raises(LLMAuthError):
            await client.embed(["a"])

    @pytest.mark.asyncio
    async def test_embed_transport_error(self, monkeypatch):
        def handler(request):
            raise httpx.ConnectError("нет соединения", request=request)

        client = _make_client(handler, monkeypatch)
        with pytest.raises(LLMError):
            await client.embed(["a"])


class TestMisc:
    @pytest.mark.asyncio
    async def test_close_does_not_raise_before_any_request(self, monkeypatch):
        client = _make_client(lambda r: httpx.Response(200), monkeypatch)
        await client.close()

    @pytest.mark.asyncio
    async def test_close_after_request(self, monkeypatch):
        client = _make_client(
            _json_handler({"choices": [{"message": {"content": "x"}}]}), monkeypatch
        )
        await client.generate([{"role": "user", "content": "q"}])
        await client.close()
        assert client._client is None

    def test_error_hierarchy(self):
        assert issubclass(LLMAuthError, LLMError)
        assert issubclass(LLMRateLimitError, LLMError)
        assert issubclass(LLMTimeoutError, LLMError)
        assert issubclass(LLMBadResponseError, LLMError)
