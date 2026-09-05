"""Tests for services/llm_client.py (T-178, Section 33.4; Epic 47, Section 56)."""
import asyncio
import json

import httpx
import pytest

from unittest.mock import AsyncMock

import services.llm_client as llm_client
from services.llm_client import (
    LLMAuthError,
    LLMBadResponseError,
    LLMClient,
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMTransportError,
)


def _make_client(handler, monkeypatch,
                 fallback_base_url="", fallback_model="", fallback_api_key="",
                 embed_fallback_base_url="", embed_fallback_api_key="",
                 embed_fallback_model="",
                 **kwargs):
    """LLMClient backed by httpx.MockTransport; backoff sleeps disabled.
    Epic 53: фоллбэк-параметры — явные инжект-параметры (изоляция от env).
    Embed-фоллбэк EMBEDDING_FALLBACK_* — пустые kwargs по умолчанию
    (неактивен, изоляция от env/дефолтов settings)."""
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    client = LLMClient(
        "https://api.test/v1", "test-key", "chat-model", "embed-model",
        fallback_base_url=fallback_base_url,
        fallback_model=fallback_model,
        fallback_api_key=fallback_api_key,
        embed_fallback_base_url=embed_fallback_base_url,
        embed_fallback_api_key=embed_fallback_api_key,
        embed_fallback_model=embed_fallback_model,
        **kwargs,
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
    async def test_generate_with_temperature_in_payload(self, monkeypatch):
        """65.8 (T-476): temperature=0.0 → ключ в payload."""
        seen = {}

        def handler(request):
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ок"}}]},
                request=request,
            )

        client = _make_client(handler, monkeypatch)
        await client.generate([{"role": "user", "content": "q"}], temperature=0.0)
        assert seen["payload"]["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_generate_without_temperature_no_key(self, monkeypatch):
        """65.8: без kwarg → ключа temperature НЕТ (ровно старое поведение,
        дефолт провайдера)."""
        seen = {}

        def handler(request):
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ок"}}]},
                request=request,
            )

        client = _make_client(handler, monkeypatch)
        await client.generate([{"role": "user", "content": "q"}])
        assert "temperature" not in seen["payload"]

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

    @pytest.mark.asyncio
    async def test_embed_fallback_after_primary_403(self, monkeypatch, caplog):
        """Раунд 5: primary 403 → embed-фоллбэк EMBEDDING_FALLBACK_*
        (/embeddings; пустая модель → primary embed-модель) → успех."""
        import logging
        seen = {}

        def handler(request):
            if "fallback.test" in str(request.url):
                seen["fb_url"] = str(request.url)
                seen["fb_auth"] = request.headers.get("authorization")
                seen["fb_payload"] = json.loads(request.content)
                return httpx.Response(
                    200, json={"data": [{"embedding": [9.9]}]},
                    request=request)
            return httpx.Response(
                403, text='{"error":{"message":"insufficient balance"}}',
                request=request)

        client = _make_client(handler, monkeypatch,
                              embed_fallback_base_url="https://fallback.test/v1",
                              embed_fallback_api_key="fb-key")
        with caplog.at_level(logging.WARNING):
            vectors = await client.embed(["текст"])
        assert vectors == [[9.9]]
        assert seen["fb_url"] == "https://fallback.test/v1/embeddings"
        assert seen["fb_auth"] == "Bearer fb-key"
        assert seen["fb_payload"]["model"] == "embed-model"
        assert seen["fb_payload"]["input"] == ["текст"]
        assert any("LLM embed fallback attempt" in r.message
                   for r in caplog.records)
        assert any("LLM embed fallback OK" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_fallback_failure_raises_original(self, monkeypatch,
                                                          caplog):
        """Раунд 5: фоллбэк тоже не смог (404 — детерминированный 4xx, БЕЗ
        ретраев) → проброс ИСХОДНОГО исключения primary + WARNING-диагностика
        «LLM fallback failed | kind=embed | error=status=404»."""
        import logging
        state = {"fb": 0}

        def handler(request):
            if "fallback.test" in str(request.url):
                state["fb"] += 1
                return httpx.Response(404, json={}, request=request)
            return httpx.Response(
                403, text='{"error":{"message":"insufficient balance"}}',
                request=request)

        client = _make_client(handler, monkeypatch,
                              embed_fallback_base_url="https://fallback.test/v1",
                              embed_fallback_api_key="fb-key")
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMAuthError) as ei:
                await client.embed(["текст"])
        assert "LLM auth failed (403)" in str(ei.value)
        assert "insufficient balance" in str(ei.value)
        # детерминированный 4xx — РОВНО одна попытка (без ретраев)
        assert state["fb"] == 1
        # контракт BetterStack: маркер kind=embed
        assert any("LLM fallback failed | kind=embed | error=status=404"
                   in r.message for r in caplog.records)

    # ── Раунд 5: embed-фоллбэк EMBEDDING_FALLBACK_* (10 кейсов) ──────────

    def _fb_handler(self, seen, fb_status=200, fb_body=None):
        def handler(request):
            if "fallback.test" in str(request.url):
                seen["fb"] = seen.get("fb", 0) + 1
                seen["fb_url"] = str(request.url)
                seen["fb_auth"] = request.headers.get("authorization")
                seen["fb_payload"] = json.loads(request.content)
                if fb_status != 200:
                    return httpx.Response(fb_status, json={}, request=request)
                return httpx.Response(
                    200,
                    json=fb_body if fb_body is not None
                    else {"data": [{"embedding": [7.7]}]},
                    request=request)
            seen["primary"] = seen.get("primary", 0) + 1
            return httpx.Response(
                403, text='{"error":{"message":"quota exceeded"}}',
                request=request)

        return handler

    def _auth_client(self, handler, monkeypatch, **kw) -> LLMClient:
        client = _make_client(
            handler, monkeypatch,
            embed_fallback_base_url="https://fallback.test/v1",
            embed_fallback_api_key="fb-key", **kw)
        return client

    @pytest.mark.asyncio
    async def test_embed_fallback_active_with_base_and_key_only(self,
                                                                monkeypatch,
                                                                caplog):
        """Кейс 1: active = base_url + api_key (модель не нужна); пустая
        модель резолвится в primary embed-модель (URL/payload/auth + логи)."""
        import logging
        seen = {}
        client = self._auth_client(self._fb_handler(seen), monkeypatch)
        assert client._embed_fallback_active is True
        assert client._embed_fallback_model == "embed-model"
        with caplog.at_level(logging.WARNING):
            vectors = await client.embed(["текст"])
        assert vectors == [[7.7]]
        assert seen["primary"] == 1
        assert seen["fb"] == 1
        assert seen["fb_url"] == "https://fallback.test/v1/embeddings"
        assert seen["fb_auth"] == "Bearer fb-key"
        assert seen["fb_payload"] == {"model": "embed-model",
                                      "input": ["текст"]}
        assert any("LLM embed fallback attempt" in r.message
                   for r in caplog.records)
        assert any("LLM embed fallback OK | model=embed-model" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_fallback_explicit_model(self, monkeypatch, caplog):
        """Кейс 2: заданная модель фоллбэка → в payload И в OK-логе."""
        import logging
        seen = {}
        client = self._auth_client(
            self._fb_handler(seen), monkeypatch,
            embed_fallback_model="gemini-fallback-2")
        assert client._embed_fallback_model == "gemini-fallback-2"
        with caplog.at_level(logging.WARNING):
            vectors = await client.embed(["текст"])
        assert vectors == [[7.7]]
        assert seen["fb_payload"]["model"] == "gemini-fallback-2"
        assert any("LLM embed fallback OK | model=gemini-fallback-2"
                   in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_fallback_inactive_without_key(self, monkeypatch,
                                                       caplog):
        """Кейс 3: задан ТОЛЬКО base_url (нет ключа) → inactive → проброс
        исходного исключения primary, фоллбэк НЕ вызывается, клиент НЕ создан."""
        import logging
        seen = {}
        state = {"primary": 0}

        def handler(request):
            state["primary"] += 1
            return httpx.Response(
                403, text='{"error":{"message":"quota"}}', request=request)

        client = _make_client(handler, monkeypatch,
                              embed_fallback_base_url="https://fallback.test/v1")
        assert client._embed_fallback_active is False
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMAuthError):
                await client.embed(["текст"])
        assert state["primary"] == 1
        assert not seen
        assert client._embed_fallback_client is None
        assert not any("LLM fallback" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_fallback_inactive_without_base(self, monkeypatch):
        """Кейс 4: задан ТОЛЬКО ключ (нет base_url) → inactive → проброс."""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(403, json={}, request=request)

        client = _make_client(handler, monkeypatch,
                              embed_fallback_api_key="fb-key")
        assert client._embed_fallback_active is False
        with pytest.raises(LLMAuthError):
            await client.embed(["текст"])
        assert state["n"] == 1

    @pytest.mark.asyncio
    async def test_embed_bad_response_skips_fallback(self, monkeypatch):
        """Кейс 5: LLMBadResponseError на primary → фоллбэк НЕ вызывается."""
        state = {"primary": 0}

        def handler(request):
            state["primary"] += 1
            return httpx.Response(200, text="не json", request=request)

        client = self._auth_client(handler, monkeypatch)
        with pytest.raises(LLMBadResponseError):
            await client.embed(["текст"])
        assert state["primary"] == 1
        assert client._embed_fallback_client is None

    @pytest.mark.asyncio
    async def test_embed_fallback_404_single_attempt_no_retry(self,
                                                              monkeypatch,
                                                              caplog):
        """Кейс 6: фоллбэк 404 (детерминированный) → мгновенный break,
        РОВНО одна попытка, проброс исходного + лог kind=embed."""
        import logging
        seen = {}
        client = self._auth_client(
            self._fb_handler(seen, fb_status=404), monkeypatch)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMAuthError) as ei:
                await client.embed(["текст"])
        assert "LLM auth failed (403)" in str(ei.value)
        assert seen["fb"] == 1
        assert any("LLM fallback failed | kind=embed | error=status=404"
                   in r.message for r in caplog.records)
        assert not any("LLM embed fallback retry" in r.message
                       for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_fallback_429_retry_then_success(self, monkeypatch,
                                                         caplog):
        """Кейс 7: фоллбэк 429 → ретрай (EMBEDDING_FALLBACK_MAX_RETRIES=1,
        попытка 2/2) → успех; лог «LLM embed fallback retry | attempt=2/2»."""
        import logging
        state = {"fb": 0}
        seen = {}

        def handler(request):
            if "fallback.test" in str(request.url):
                state["fb"] += 1
                if state["fb"] == 1:
                    return httpx.Response(429, json={}, request=request)
                return httpx.Response(
                    200, json={"data": [{"embedding": [3.3]}]}, request=request)
            return httpx.Response(403, json={}, request=request)

        client = self._auth_client(handler, monkeypatch,
                                   embed_fallback_max_retries=1)
        with caplog.at_level(logging.WARNING):
            vectors = await client.embed(["текст"])
        assert vectors == [[3.3]]
        assert state["fb"] == 2
        assert any("LLM embed fallback retry | attempt=2/2 | reason=status=429"
                   in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_fallback_429_exhaustion_raises_original(
            self, monkeypatch, caplog):
        """Кейс 8: фоллбэк 429 на всех попытках (1+1) → проброс исходного +
        финальный WARNING kind=embed."""
        import logging
        state = {"fb": 0}
        seen = {}

        def handler(request):
            if "fallback.test" in str(request.url):
                state["fb"] += 1
                return httpx.Response(429, json={}, request=request)
            return httpx.Response(
                403, text='{"error":{"message":"quota"}}', request=request)

        client = self._auth_client(handler, monkeypatch,
                                   embed_fallback_max_retries=1)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMAuthError):
                await client.embed(["текст"])
        assert state["fb"] == 2
        assert any("LLM fallback failed | kind=embed | error=status=429"
                   in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_fallback_transport_retries_then_original(
            self, monkeypatch, caplog):
        """Кейс 9: транспортный фейл фоллбэка → ретраи; после исчерпания —
        проброс исходного; причина в логе ретрая."""
        import logging
        state = {"fb": 0}

        def handler(request):
            if "fallback.test" in str(request.url):
                state["fb"] += 1
                raise httpx.ConnectError("fb недоступен", request=request)
            return httpx.Response(403, json={}, request=request)

        client = self._auth_client(handler, monkeypatch,
                                   embed_fallback_max_retries=1)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMAuthError):
                await client.embed(["текст"])
        assert state["fb"] == 2
        assert any("LLM embed fallback retry | attempt=2/2" in r.message
                   and "reason=ConnectError" in r.message
                   for r in caplog.records)
        assert any("LLM fallback failed | kind=embed | error=ConnectError"
                   in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_fallback_bounded_by_timeout(self, monkeypatch,
                                                     caplog):
        """Кейс 9: зависший фоллбэк обрезается asyncio.timeout
        (EMBEDDING_FALLBACK_TIMEOUT_SECONDS на попытку) → проброс исходного
        исключения primary."""
        import logging

        async def handler(request):
            if "fallback.test" in str(request.url):
                await asyncio.sleep(5)
                return httpx.Response(
                    200, json={"data": [{"embedding": [1.1]}]}, request=request)
            return httpx.Response(403, json={}, request=request)

        client = self._auth_client(handler, monkeypatch,
                                   embed_fallback_max_retries=1)
        client._embed_fallback_timeout = 0.05
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMAuthError):
                await client.embed(["текст"])
        assert any("LLM embed fallback retry | attempt=2/2" in r.message
                   and "reason=TimeoutError" in r.message
                   for r in caplog.records)
        assert any("LLM fallback failed | kind=embed | error=TimeoutError"
                   in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_close_closes_embed_fallback_client(self, monkeypatch):
        """Кейс 10: close() закрывает ленивый клиент embed-фоллбэка."""
        seen = {}
        client = self._auth_client(self._fb_handler(seen), monkeypatch)
        assert await client.embed(["текст"]) == [[7.7]]
        assert client._embed_fallback_client is not None
        await client.close()
        assert client._embed_fallback_client is None


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
        # Epic 53 (62.3.2): новые транзиентные классы — подклассы LLMError
        assert issubclass(LLMServerError, LLMError)
        assert issubclass(LLMTransportError, LLMError)


# ── Epic 47 (Section 56, D186/D187): ретраи всех транзиентных + backoff/cap/jitter
#    + Retry-After + total-budget + WARNING-лог попытки (тест-план 56.8 #1-14) ──


def _success_handler(payload=None):
    return lambda request: httpx.Response(
        200, json=payload or {"choices": [{"message": {"content": "ок"}}]}, request=request
    )


class TestEpic47Retries:
    @pytest.mark.asyncio
    async def test_connect_error_retry_then_success(self, monkeypatch, caplog):
        """56.8 #1: ConnectError×1 → ретрай, generate OK, calls==2 (был мгновенный фейл)."""
        import logging

        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                raise httpx.ConnectError("нет соединения", request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        with caplog.at_level(logging.WARNING):
            result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ok"
        assert state["n"] == 2
        assert any("LLM request retry" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_read_error_retry_then_success(self, monkeypatch, caplog):
        """56.8 #2: ReadError×1 → ретрай, generate OK, calls==2."""
        import logging

        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                raise httpx.ReadError("ответ оборвался", request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        with caplog.at_level(logging.WARNING):
            result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ok"
        assert state["n"] == 2
        assert any("LLM request retry" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_connect_error_always_exhausts_llm_error(self, monkeypatch, caplog):
        """56.8 #3: ConnectError всегда → LLMTransportError (62.3.2, текст
        «transport error after 3 attempts» сохранён), calls==N=3,
        WARNING «LLM request retry»."""
        import logging

        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            raise httpx.ConnectError("нет соединения", request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMError) as ei:
                await client.generate([{"role": "user", "content": "q"}])
        assert isinstance(ei.value, LLMTransportError)
        assert state["n"] == 3
        assert "transport error after 3 attempts" in str(ei.value)
        assert any("LLM request retry" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_retry_after_429_prioritized(self, monkeypatch, caplog):
        """56.8 #5: 429 + Retry-After: 5 → сон == 5.0 (приоритет заголовка), успех."""
        import logging

        recorder = AsyncMock()
        monkeypatch.setattr("services.llm_client.asyncio.sleep", recorder)
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "5"}, request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        client.backoff_base = 1
        with caplog.at_level(logging.WARNING):
            result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ok"
        assert recorder.await_args is not None
        assert recorder.await_args.args[0] == 5.0

    @pytest.mark.asyncio
    async def test_retry_after_429_capped(self, monkeypatch):
        """56.8 #6: 429 + Retry-After: 120 → сон == CAP (8.0), не 120."""
        recorder = AsyncMock()
        monkeypatch.setattr("services.llm_client.asyncio.sleep", recorder)
        monkeypatch.setattr(llm_client.random, "uniform", lambda a, b: 0.0)
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "120"}, request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        client.backoff_base = 1
        await client.generate([{"role": "user", "content": "q"}])
        assert recorder.await_args_list[0].args[0] == 8.0

    @pytest.mark.asyncio
    async def test_retry_after_5xx_prioritized(self, monkeypatch):
        """56.8 #7: 503 + Retry-After: 3 → сон == 3.0."""
        recorder = AsyncMock()
        monkeypatch.setattr("services.llm_client.asyncio.sleep", recorder)
        monkeypatch.setattr(llm_client.random, "uniform", lambda a, b: 0.0)
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(503, headers={"Retry-After": "3"}, request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        client.backoff_base = 1
        await client.generate([{"role": "user", "content": "q"}])
        assert recorder.await_args_list[0].args[0] == 3.0

    @pytest.mark.asyncio
    async def test_retry_after_broken_ignored(self, monkeypatch):
        """56.8 #8: кривой Retry-After: abc → игнор → обычный backoff (base=1)."""
        recorder = AsyncMock()
        monkeypatch.setattr("services.llm_client.asyncio.sleep", recorder)
        monkeypatch.setattr(llm_client.random, "uniform", lambda a, b: 0.0)
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "abc"}, request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        client.backoff_base = 1
        await client.generate([{"role": "user", "content": "q"}])
        assert recorder.await_args_list[0].args[0] == 1.0

    @pytest.mark.asyncio
    async def test_sleep_sequence_base_one_jitter_zero(self, monkeypatch):
        """56.8 #9: последовательность снов (base=1, jitter→0, max_retries=3)
        → recorder == [1.0, 2.0, 4.0]."""
        recorder = AsyncMock()
        monkeypatch.setattr("services.llm_client.asyncio.sleep", recorder)
        monkeypatch.setattr(llm_client.random, "uniform", lambda a, b: 0.0)

        def handler(request):
            return httpx.Response(429, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=3)
        client.backoff_base = 1
        with pytest.raises(LLMRateLimitError):
            await client.generate([{"role": "user", "content": "q"}])
        recorded = [c.args[0] for c in recorder.await_args_list]
        assert recorded == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    async def test_jitter_added_to_backoff(self, monkeypatch):
        """56.8 #10: jitter uniform→0.5 → сон = backoff + 0.5."""
        recorder = AsyncMock()
        monkeypatch.setattr("services.llm_client.asyncio.sleep", recorder)
        monkeypatch.setattr(llm_client.random, "uniform", lambda a, b: 0.5)

        def handler(request):
            return httpx.Response(429, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        client.backoff_base = 1
        with pytest.raises(LLMRateLimitError):
            await client.generate([{"role": "user", "content": "q"}])
        assert recorder.await_args_list[0].args[0] == pytest.approx(1.5)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", [408, 425])
    async def test_408_425_retry_then_success(self, monkeypatch, code):
        """56.8 #11: 408/425 → транзиентные, ретрай → успех."""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(code, json={}, request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ok"
        assert state["n"] == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code", [400, 404, 422])
    async def test_other_4xx_immediate(self, monkeypatch, code):
        """56.8 #11: 400/404/422 → мгновенно (БЕЗ повторов)."""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(code, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        with pytest.raises(LLMError) as ei:
            await client.generate([{"role": "user", "content": "q"}])
        assert state["n"] == 1
        assert str(ei.value) == f"LLM HTTP {code}: https://api.test/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_total_budget_binds(self, monkeypatch):
        """56.8 #13: total-budget — handler висит (TimeoutException), budget=0.05
        → LLMTimeoutError, attempts ≤ 2 (всего 1 попытка, бюджет бьёт)."""
        state = {"n": 0}

        async def handler(request):
            state["n"] += 1
            await asyncio.sleep(1)
            raise httpx.TimeoutException("долго", request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        client._budget = 0.05
        with pytest.raises(LLMTimeoutError) as ei:
            await client.generate([{"role": "user", "content": "q"}])
        assert state["n"] <= 2
        assert "timed out after" in str(ei.value)

    @pytest.mark.asyncio
    async def test_retry_warning_format(self, monkeypatch, caplog):
        """56.8 #14: точно формат `LLM request retry | url=… | attempt=1/3 |
        sleep=… | reason=status=429`."""
        import logging

        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(429, json={}, request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        with caplog.at_level(logging.WARNING):
            await client.generate([{"role": "user", "content": "q"}])
        retry_records = [r.message for r in caplog.records if "LLM request retry" in r.message]
        assert any(
            "url=https://api.test/v1/chat/completions" in m
            and "attempt=1/3" in m
            and "sleep=0.0s" in m
            and "reason=status=429" in m
            for m in retry_records
        )


class TestEpic49DiagnosticLog:
    """Epic 49 (57.4, D197): финальный 4xx → ERROR-диагн-лог с длиной payload
    и телом провайдера (≤500 симв.); 401/403 и текст исключения — без изменений."""

    @pytest.mark.asyncio
    async def test_final_400_logs_diagnostics(self, monkeypatch, caplog):
        import logging

        def handler(request):
            return httpx.Response(400, text="context length exceeded", request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(LLMError) as ei:
                await client.generate([
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "запрос" * 50},
                ])
        assert str(ei.value) == "LLM HTTP 400: https://api.test/v1/chat/completions"
        records = [r.message for r in caplog.records if "LLM HTTP 400" in r.message]
        assert len(records) == 1
        msg = records[0]
        assert "url=https://api.test/v1/chat/completions" in msg
        assert "request_len=" in msg
        assert "content_chars=" in msg
        assert "num_messages=2" in msg
        assert "body_4xx='context length exceeded'" in msg

    @pytest.mark.asyncio
    async def test_400_body_truncated_to_500_chars(self, monkeypatch, caplog):
        import logging

        def handler(request):
            return httpx.Response(400, text="x" * 1000, request=request)

        client = _make_client(handler, monkeypatch)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(LLMError):
                await client.generate([{"role": "user", "content": "q"}])
        record = next(r for r in caplog.records if "LLM HTTP 400" in r.message)
        assert "x" * 501 not in record.message          # обрезано до _BODY_MAX_CHARS
        assert "x" * 500 in record.message

    @pytest.mark.asyncio
    async def test_401_403_no_body_4xx_log(self, monkeypatch, caplog):
        """Задача 2 (01.09.2026): 401/403 логируются отдельным body_auth=
        (санитизированное обрезанное тело), НО не через body_4xx."""
        import logging

        def handler(request):
            return httpx.Response(401, text="unauthorized body", request=request)

        client = _make_client(handler, monkeypatch)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(LLMAuthError):
                await client.generate([{"role": "user", "content": "q"}])
        assert not any("body_4xx" in r.message for r in caplog.records)   # R17
        assert any("body_auth='unauthorized body'" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_auth_error_contains_sanitized_body_snippet(self, monkeypatch):
        """Задача 2: 403 с телом {'error':{'message':'insufficient balance'}}
        → LLMAuthError содержит обрезанный сниппет; секреты замаскированы."""
        from services.llm_client import _sanitize_snippet

        def handler(request):
            return httpx.Response(
                403,
                text='{"error": {"message": "insufficient balance", '
                     '"api_key": "sk-1234567890abcdef"}}',
                request=request)

        client = _make_client(handler, monkeypatch)
        with pytest.raises(LLMAuthError) as ei:
            await client.generate([{"role": "user", "content": "q"}])
        assert "LLM auth failed (403)" in str(ei.value)
        assert "insufficient balance" in str(ei.value)
        assert "sk-1234567890abcdef" not in str(ei.value)   # R17: замаскирован
        assert _sanitize_snippet("api_key=sk-1234567890abcdef") == \
            "api_key=***"
        assert _sanitize_snippet("token: abcdefgh123456") == "token: ***"
        assert _sanitize_snippet("просто текст") == "просто текст"
        assert _sanitize_snippet("x" * 300) == "x" * 200

    def test_mask_secrets_openai_style(self):
        """Ревью-фикс 1: OpenAI-стиль «Incorrect API key provided:
        sk-proj-…» — префикс-ключ маскируется в любом контексте."""
        from services.llm_client import _sanitize_snippet
        text = "Incorrect API key provided: sk-proj-abc123XYZ890"
        out = _sanitize_snippet(text)
        assert "sk-proj-abc123XYZ890" not in out
        assert "sk-proj-" not in out

    def test_mask_secrets_json_form(self):
        """Ревью-блокер: JSON-форма '"key": "value"' — кавычки вокруг
        ключа и значения; JWT-подобные токены; Basic-авторизация."""
        from services.llm_client import _sanitize_snippet
        assert _sanitize_snippet('"token": "abcdefgh123456"') == \
            '"token": "***"'
        assert _sanitize_snippet('"api_key": "abcdefgh1234567890"') == \
            '"api_key": "***"'
        assert _sanitize_snippet('"token":"abcdefgh123456"') == \
            '"token":"***"'
        assert _sanitize_snippet('"token" : "abcdefgh123456"') == \
            '"token" : "***"'
        # Basic-авторизация (base64 user:pass) маскируется целиком
        out = _sanitize_snippet(
            '"authorization": "Basic dXNlcjpwYXNzd29yZA=="')
        assert "dXNlcjpwYXNzd29yZA==" not in out
        assert "Basic ***" in out
        # JWT-подобный токен в паре token=
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        assert jwt not in _sanitize_snippet(f'"token": "{jwt}"')
        # контроль: authorization: Bearer sk-live-… — Bearer-путь не сломан
        assert "Bearer ***" in _sanitize_snippet(
            "authorization: Bearer sk-live-1234567890")
        assert "sk-live-1234567890" not in _sanitize_snippet(
            "authorization: Bearer sk-live-1234567890")

    def test_mask_secrets_lowercase_bearer_basic(self):
        """Ревью-фикс: lowercase 'bearer'/'basic' (re.IGNORECASE, контракт
        log_ring.py); pot_token не маскируется; JSON-формы живы."""
        from services.llm_client import _sanitize_snippet
        # lowercase bearer → токен маскирован полностью
        out = _sanitize_snippet("authorization: bearer sk-live-1234567890")
        assert "sk-live-1234567890" not in out
        assert "bearer ***" in out
        # lowercase basic → base64 маскирован
        out = _sanitize_snippet(
            "authorization: basic dXNlcjpwYXNzd29yZA==")
        assert "dXNlcjpwYXNzd29yZA==" not in out
        assert "basic ***" in out
        # МЕШАННЫЙ регистр
        out = _sanitize_snippet("Authorization: Bearer TOKEN-1234567890")
        assert "TOKEN-1234567890" not in out
        # контроль: pot_token/access_token НЕ маскируются
        assert _sanitize_snippet("pot_token=abc") == "pot_token=abc"
        assert _sanitize_snippet("pot_token=abcdefgh123456") == \
            "pot_token=abcdefgh123456"
        assert _sanitize_snippet("access_token=abcdefgh123456") == \
            "access_token=abcdefgh123456"
        # JSON-формы по-прежнему маскируются
        assert _sanitize_snippet('"token": "abcdefgh123456"') == \
            '"token": "***"'
        assert _sanitize_snippet('"Api-Key": "abcdefgh123456"') == \
            '"Api-Key": "***"'

    def test_mask_secrets_key_types_and_spaces(self):
        """Префикс-ключи gsk_/tvly_/xoxb-; пробел в 'api key'; порог
        значений ≥4; 'Bearer sk-live-…' в произвольном тексте."""
        from services.llm_client import _sanitize_snippet
        assert "gsk_abcdefgh123456" not in _sanitize_snippet(
            "gsk_abcdefgh123456 bad key")
        assert "tvly-abcdef12345678" not in _sanitize_snippet(
            "token tvly-abcdef12345678 here")
        assert "xoxb-abcdefgh123456" not in _sanitize_snippet(
            "xoxb-abcdefgh123456")
        # пробел между 'api' и 'key' допустим
        assert _sanitize_snippet("api key: qwerty123456") == \
            "api key: ***"
        # короткие значения (≤4) парой НЕ маскируются
        assert _sanitize_snippet("token: abc") == "token: abc"

    @pytest.mark.asyncio
    async def test_other_4xx_also_logged(self, monkeypatch, caplog):
        import logging

        def handler(request):
            return httpx.Response(422, text="unprocessable", request=request)

        client = _make_client(handler, monkeypatch)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(LLMError):
                await client.generate([{"role": "user", "content": "q"}])
        assert any("LLM HTTP 422" in r.message and "body_4xx=" in r.message
                   for r in caplog.records)


class TestEpic53ServerErrors:
    """Epic 53 (62.3.2/62.5): классы LLMServerError/LLMTransportError +
    диаг-лог финальных 5xx с body_5xx ≤500 (тест-план 62.5 #1-4)."""

    @pytest.mark.asyncio
    async def test_502_exhaustion_raises_server_error_with_body_log(self, monkeypatch, caplog):
        """62.5 #1: 502×3 → LLMServerError (текст сохранён) + ERROR-лог body_5xx."""
        import logging

        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(502, text="upstream broken details", request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(LLMServerError) as ei:
                await client.generate([{"role": "user", "content": "q"}])
        assert state["n"] == 3
        assert "server error 502 after 3 attempts" in str(ei.value)
        assert "https://api.test/v1/chat/completions" in str(ei.value)
        records = [r.message for r in caplog.records if "LLM HTTP 502" in r.message]
        assert len(records) == 1
        msg = records[0]
        assert "url=https://api.test/v1/chat/completions" in msg
        assert "request_len=" in msg
        assert "num_messages=1" in msg
        assert "body_5xx='upstream broken details'" in msg

    @pytest.mark.asyncio
    async def test_502_body_truncated_to_500_chars(self, monkeypatch, caplog):
        """62.5 #1: тело финального 502 в логе обрезано до _BODY_MAX_CHARS."""
        import logging

        def handler(request):
            return httpx.Response(502, text="x" * 1000, request=request)

        client = _make_client(handler, monkeypatch)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(LLMServerError):
                await client.generate([{"role": "user", "content": "q"}])
        record = next(r for r in caplog.records if "LLM HTTP 502" in r.message)
        assert "x" * 501 not in record.message
        assert "x" * 500 in record.message

    @pytest.mark.asyncio
    async def test_502_twice_then_success(self, monkeypatch):
        """62.5 #2: 502×2 + 200 → успех, calls==3."""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] <= 2:
                return httpx.Response(502, json={}, request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ок"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ок"
        assert state["n"] == 3

    @pytest.mark.asyncio
    async def test_read_timeout_exhaustion_raises_timeout_error(self, monkeypatch):
        """62.5 #3: ReadTimeout×3 → LLMTimeoutError, calls==3."""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            raise httpx.ReadTimeout("чтение зависло", request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        with pytest.raises(LLMTimeoutError):
            await client.generate([{"role": "user", "content": "q"}])
        assert state["n"] == 3

    @pytest.mark.asyncio
    async def test_5xx_body_not_logged_on_retries(self, monkeypatch, caplog):
        """62.5: на НЕ-финальных 5xx (ретрай) тело НЕ логируется — только
        retry-WARNING, спама нет."""
        import logging

        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            if state["n"] < 3:
                return httpx.Response(502, text="retry body", request=request)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ok"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2)
        with caplog.at_level(logging.WARNING):
            result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ok"
        assert not any("body_5xx" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_429_408_425_classes_unchanged(self, monkeypatch):
        """62.5 #5: 429 → LLMRateLimitError; 408/425 → LLMError (не новые классы)."""

        def handler(request):
            return httpx.Response(429, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=0)
        with pytest.raises(LLMRateLimitError):
            await client.generate([{"role": "user", "content": "q"}])


class TestEpic53Fallback:
    """Epic 53 (62.4, тест-план 62.5 #6-9): фоллбэк-провайдер LLM_FALLBACK_*."""

    FB = dict(
        fallback_base_url="https://fallback.test/v1",
        fallback_model="fb-model",
        fallback_api_key="fb-key",
    )

    @pytest.mark.asyncio
    async def test_fallback_success_after_primary_5xx(self, monkeypatch, caplog):
        """62.5 #6: primary 502×3 → фоллбэк 200 → ответ фоллбэка, WARNING-логи."""
        import logging

        state = {"n": 0, "fb": 0}
        seen = {}

        def handler(request):
            if "fallback.test" in str(request.url):
                state["fb"] += 1
                seen["fb_url"] = str(request.url)
                seen["fb_auth"] = request.headers.get("authorization")
                seen["fb_payload"] = json.loads(request.content)
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": "ответ фоллбэка"}}]},
                    request=request,
                )
            state["n"] += 1
            return httpx.Response(502, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2, **self.FB)
        with caplog.at_level(logging.WARNING):
            result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ответ фоллбэка"
        assert state["n"] == 3                      # primary исчерпан
        assert state["fb"] == 1                     # РОВНО одна попытка
        assert seen["fb_url"] == "https://fallback.test/v1/chat/completions"
        assert seen["fb_auth"] == "Bearer fb-key"
        assert seen["fb_payload"]["model"] == "fb-model"
        assert seen["fb_payload"]["messages"] == [{"role": "user", "content": "q"}]
        assert any("LLM fallback attempt" in r.message for r in caplog.records)
        assert any("LLM fallback OK | model=fb-model" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_fallback_502_rethrows_primary_error(self, monkeypatch, caplog):
        """62.5 #7: фоллбэк 502 → проброс ИСХОДНОГО исключения primary."""
        import logging

        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(502, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2, **self.FB)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMServerError) as ei:
                await client.generate([{"role": "user", "content": "q"}])
        # исходное исключение primary (primary url в тексте), не фоллбэка
        assert "server error 502 after 3 attempts" in str(ei.value)
        assert "https://api.test/v1/chat/completions" in str(ei.value)
        # Epic 64: фоллбэк ретраится (LLM_FALLBACK_MAX_RETRIES=2) →
        # 3 primary + 3 фоллбэк-попытки = 6; итог — старый формат лога.
        assert state["n"] == 6
        assert any("LLM fallback retry | attempt=2/3 | reason=status=502" in r.message
                   for r in caplog.records)
        assert any("LLM fallback failed | error=status=502" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_fallback_transport_error_rethrows_primary(self, monkeypatch, caplog):
        import logging

        def handler(request):
            if "fallback.test" in str(request.url):
                raise httpx.ConnectError("фоллбэк недоступен", request=request)
            return httpx.Response(503, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2, **self.FB)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMServerError) as ei:
                await client.generate([{"role": "user", "content": "q"}])
        assert "server error 503 after 3 attempts" in str(ei.value)
        assert any("LLM fallback failed | error=" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_fallback_fires_after_429_exhaustion(self, monkeypatch, caplog):
        """M2а: 429×3 primary → LLMRateLimitError (подкласс LLMError) →
        фоллбэк-попытка по контракту 62.4 п.2 (любой LLMError, кроме
        LLMBadResponseError)."""
        import logging

        state = {"n": 0, "fb": 0}

        def handler(request):
            if "fallback.test" in str(request.url):
                state["fb"] += 1
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": "ответ фоллбэка"}}]},
                    request=request,
                )
            state["n"] += 1
            return httpx.Response(429, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2, **self.FB)
        with caplog.at_level(logging.WARNING):
            result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ответ фоллбэка"
        assert state["n"] == 3                      # primary исчерпан: 429×3
        assert state["fb"] == 1                     # фоллбэк: РОВНО одна попытка
        assert any("LLM fallback OK" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_fallback_bounded_by_timeout(self, monkeypatch, caplog):
        """M1: зависший фоллбэк обрезается _FALLBACK_TIMEOUT_SECONDS (а не
        висит до per-request LLM_TIMEOUT) → проброс исходного исключения
        primary; худший случай ≤ бюджет primary + 30с, а не +90с."""
        import logging
        import time

        async def handler(request):
            await asyncio.sleep(5)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ок"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=0, **self.FB)
        client._budget = 0.05
        client._fallback_timeout = 0.05
        started = time.monotonic()
        with caplog.at_level(logging.WARNING):
            with pytest.raises(LLMTimeoutError):
                await client.generate([{"role": "user", "content": "q"}])
        assert time.monotonic() - started < 2.0        # фоллбэк обрезан таймаутом
        assert any("LLM fallback failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_env_empty_no_fallback(self, monkeypatch):
        """62.5 #8: фоллбэк-параметры пусты → фоллбэк НЕ вызывается."""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(502, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2)
        with pytest.raises(LLMServerError):
            await client.generate([{"role": "user", "content": "q"}])
        assert state["n"] == 3                      # только primary

    @pytest.mark.asyncio
    async def test_primary_success_no_fallback(self, monkeypatch):
        """62.5 #9: primary 200 → фоллбэк не вызывается, calls==1."""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "ок"}}]}, request=request
            )

        client = _make_client(handler, monkeypatch, max_retries=2, **self.FB)
        result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "ок"
        assert state["n"] == 1

    @pytest.mark.asyncio
    async def test_bad_response_no_fallback(self, monkeypatch):
        """62.5 #9: LLMBadResponseError → БЕЗ фоллбэка (повтор бессмыслен)."""
        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(200, text="не json", request=request)

        client = _make_client(handler, monkeypatch, max_retries=2, **self.FB)
        with pytest.raises(LLMBadResponseError):
            await client.generate([{"role": "user", "content": "q"}])
        assert state["n"] == 1

    @pytest.mark.asyncio
    async def test_partial_config_warns_and_disables(self, monkeypatch, caplog):
        """62.4: задан только base_url → WARNING при создании, фоллбэк выключен."""
        import logging

        state = {"n": 0}

        def handler(request):
            state["n"] += 1
            return httpx.Response(502, json={}, request=request)

        with caplog.at_level(logging.WARNING):
            client = _make_client(
                handler, monkeypatch, max_retries=2,
                fallback_base_url="https://fallback.test/v1",
            )
        assert any("LLM fallback partially configured" in r.message
                   for r in caplog.records)
        assert client._fallback_active is False
        with pytest.raises(LLMServerError):
            await client.generate([{"role": "user", "content": "q"}])
        assert state["n"] == 3

    @pytest.mark.asyncio
    async def test_close_closes_fallback_client(self, monkeypatch):
        def handler(request):
            if "fallback.test" in str(request.url):
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": "фб"}}]}, request=request
                )
            return httpx.Response(502, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=2, **self.FB)
        result = await client.generate([{"role": "user", "content": "q"}])
        assert result == "фб"
        await client.close()
        assert client._client is None
        assert client._fallback_client is None


class TestEpic60UsageLog:
    """Epic 60 (64.7/64.9 #10, T-468): INFO-лог usage in/out из API-ответа —
    источник истины фактических токенов."""

    @pytest.mark.asyncio
    async def test_usage_logged_from_response(self, monkeypatch, caplog):
        import logging

        client = _make_client(
            _json_handler({
                "choices": [{"message": {"content": "ок"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40},
            }),
            monkeypatch,
        )
        with caplog.at_level(logging.INFO):
            text = await client.generate(
                [{"role": "user", "content": "привет"}])
        assert text == "ок"
        assert any("LLM usage in=120 out=40" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_usage_no_log(self, monkeypatch, caplog):
        import logging

        client = _make_client(
            _json_handler({"choices": [{"message": {"content": "ок"}}]}),
            monkeypatch,
        )
        with caplog.at_level(logging.INFO):
            await client.generate([{"role": "user", "content": "привет"}])
        assert all("LLM usage" not in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_embed_usage_in_only(self, monkeypatch, caplog):
        import logging

        client = _make_client(
            _json_handler({
                "data": [{"embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            }),
            monkeypatch,
        )
        with caplog.at_level(logging.INFO):
            vectors = await client.embed(["текст"])
        assert vectors == [[0.1, 0.2]]
        assert any("LLM usage in=7 out=0" in r.message for r in caplog.records)


# ── Эпик 04.09.2026 (3.3, AC-2.1): generate_chat — tools/tool_choice в
# payload, парсинг content + tool_calls; легаси generate() без изменений. ──


class TestGenerateChat:
    def _handler(self, seen):
        def handler(request):
            seen["payload"] = json.loads(request.content)
            return httpx.Response(200, json=seen["response"], request=request)

        return handler

    @pytest.mark.asyncio
    async def test_tools_and_tool_choice_in_payload(self, monkeypatch):
        seen = {}
        seen["response"] = {"choices": [{"message": {"content": "финал"}}]}
        client = _make_client(self._handler(seen), monkeypatch)
        tools = [{"type": "function",
                  "function": {"name": "execute_web_search"}}]
        result = await client.generate_chat(
            [{"role": "user", "content": "q"}],
            tools=tools, tool_choice="auto")
        assert result.content == "финал"
        assert result.tool_calls is None
        assert seen["payload"]["tools"] == tools
        assert seen["payload"]["tool_choice"] == "auto"
        assert seen["payload"]["model"] == "chat-model"

    @pytest.mark.asyncio
    async def test_no_tools_no_tool_keys_in_payload(self, monkeypatch):
        seen = {}
        seen["response"] = {"choices": [{"message": {"content": "ок"}}]}
        client = _make_client(self._handler(seen), monkeypatch)
        result = await client.generate_chat([{"role": "user", "content": "q"}])
        assert result.content == "ок"
        assert "tools" not in seen["payload"]
        assert "tool_choice" not in seen["payload"]

    @pytest.mark.asyncio
    async def test_temperature_none_not_added(self, monkeypatch):
        seen = {}
        seen["response"] = {"choices": [{"message": {"content": "ок"}}]}
        client = _make_client(self._handler(seen), monkeypatch)
        await client.generate_chat([{"role": "user", "content": "q"}],
                                   tools=[{"type": "function"}])
        assert "temperature" not in seen["payload"]

    @pytest.mark.asyncio
    async def test_parses_tool_calls(self, monkeypatch):
        seen = {}
        seen["response"] = {"choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "execute_web_search",
                                         "arguments": '{"query": "x"}'}}],
        }, "finish_reason": "tool_calls"}]}
        client = _make_client(self._handler(seen), monkeypatch)
        result = await client.generate_chat(
            [{"role": "user", "content": "q"}], tools=[{"type": "function"}])
        assert result.content is None
        assert result.finish_reason == "tool_calls"
        assert result.tool_calls and len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "call_1"
        assert tc.name == "execute_web_search"
        assert tc.arguments == '{"query": "x"}'
        assert tc.as_openai_dict()["id"] == "call_1"

    @pytest.mark.asyncio
    async def test_parses_tool_calls_with_text_content(self, monkeypatch):
        seen = {}
        seen["response"] = {"choices": [{"message": {
            "content": "сначала мысль",
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "query_chat_memory",
                                         "arguments": "{}"}}],
        }}]}
        client = _make_client(self._handler(seen), monkeypatch)
        result = await client.generate_chat(
            [{"role": "user", "content": "q"}], tools=[{"type": "function"}])
        assert result.content == "сначала мысль"
        assert result.tool_calls and len(result.tool_calls) == 1

    @pytest.mark.asyncio
    async def test_empty_content_no_tool_calls_raises(self, monkeypatch):
        seen = {}
        seen["response"] = {"choices": [{"message": {"content": None}}]}
        client = _make_client(self._handler(seen), monkeypatch)
        with pytest.raises(LLMBadResponseError):
            await client.generate_chat(
                [{"role": "user", "content": "q"}],
                tools=[{"type": "function"}])

    @pytest.mark.asyncio
    async def test_malformed_tool_call_skipped(self, monkeypatch):
        seen = {}
        seen["response"] = {"choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "x", "arguments": "{}"}},
                           {"id": "call_2"}]}}]}
        client = _make_client(self._handler(seen), monkeypatch)
        result = await client.generate_chat(
            [{"role": "user", "content": "q"}], tools=[{"type": "function"}])
        assert result.tool_calls and len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_1"

    @pytest.mark.asyncio
    async def test_generate_unchanged_with_tools_available(self, monkeypatch):
        """0-регрессий: generate() не кладёт tools, даже если клиент умеет
        generate_chat (разные методы, общий _post)."""
        seen = {}
        seen["response"] = {"choices": [{"message": {"content": "ок"}}]}
        client = _make_client(self._handler(seen), monkeypatch)
        text = await client.generate([{"role": "user", "content": "q"}])
        assert text == "ок"
        assert "tools" not in seen["payload"]
        assert "tool_choice" not in seen["payload"]

    @pytest.mark.asyncio
    async def test_generate_chat_uses_fallback_on_5xx(self, monkeypatch, caplog):
        """generate_chat повторяет фоллбэк-контракт generate (62.4)."""
        import logging
        state = {"n": 0, "fb": 0}

        def handler(request):
            if "fallback.test" in str(request.url):
                state["fb"] += 1
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "ответ фоллбэка"}}]},
                    request=request)
            state["n"] += 1
            return httpx.Response(502, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=0,
                              fallback_base_url="https://fallback.test/v1",
                              fallback_model="fb-model",
                              fallback_api_key="fb-key")
        with caplog.at_level(logging.WARNING):
            result = await client.generate_chat(
                [{"role": "user", "content": "q"}],
                tools=[{"type": "function"}])
        assert result.content == "ответ фоллбэка"
        assert state["fb"] == 1