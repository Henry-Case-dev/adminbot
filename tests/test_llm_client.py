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
        """56.8 #3: ConnectError всегда → LLMError (класс сохранён), calls==N=3,
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
        assert "x" * 501 not in record.message          # обрезано до _4XX_BODY_MAX_CHARS
        assert "x" * 500 in record.message

    @pytest.mark.asyncio
    async def test_401_403_no_body_log(self, monkeypatch, caplog):
        import logging

        def handler(request):
            return httpx.Response(401, text="unauthorized body", request=request)

        client = _make_client(handler, monkeypatch)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(LLMAuthError):
                await client.generate([{"role": "user", "content": "q"}])
        assert not any("body_4xx" in r.message for r in caplog.records)   # R17

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
