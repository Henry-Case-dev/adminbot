"""UR-18 (UNIFIED-REPLY §7): структурированный результат LLM Completion.

Контракт слайса:
* ``generate()`` продолжает возвращать тот же ``str`` (байт-в-байт) для всех
  существующих потребителей;
* ``generate_with_metadata()`` отдаёт ``LLMCompletion`` с finish_reason,
  provider/model, usage, max_output_tokens_sent, attempt, correlation_id и
  диагностикой fallback;
* отсутствующее поле finish_reason → ``unknown``, НЕ ``stop``;
* finish_reason переживает fallback (ответила фоллбэк-нога — её статус и её
  модель/провайдер в метаданных, отказ primary в цепочке);
* ``usage`` отсутствует → ``None`` (не нули);
* ``max_output_tokens_sent`` — ровно ``max_tokens`` из ОТПРАВЛЕННОГО тела.

Тесты используют тот же fake-уровень, что и tests/test_llm_client.py:
httpx.MockTransport (реальный HTTP-слой клиента, без сети).
"""

import json

import httpx
import pytest

from services.llm_client import LLMCompletion, LLMClient

_UNSET = object()

FB = dict(
    fallback_base_url="https://fallback.test/v1",
    fallback_model="fb-model",
    fallback_api_key="fb-key",
)


def _make_client(handler, monkeypatch, **kwargs):
    """LLMClient на httpx.MockTransport; backoff-сон отключён.

    Пустые fallback/embed-параметры по умолчанию — изоляция от env
    (тот же приём, что в tests/test_llm_client.py)."""
    params = dict(
        fallback_base_url="", fallback_model="", fallback_api_key="",
        embed_fallback_base_url="", embed_fallback_api_key="",
        embed_fallback_model="", embed_fallback_api_key_2="",
    )
    params.update(kwargs)
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    client = LLMClient(
        "https://api.test/v1", "test-key", "chat-model", "embed-model",
        **params,
    )
    client.backoff_base = 0
    return client


def _completion(request, content="ответ", finish_reason=_UNSET,
                usage=_UNSET):
    choice = {"message": {"content": content}}
    if finish_reason is not _UNSET:
        choice["finish_reason"] = finish_reason
    body = {"choices": [choice]}
    if usage is not _UNSET:
        body["usage"] = usage
    return httpx.Response(200, json=body, request=request)


def _ok_handler(**kwargs):
    def handler(request):
        return _completion(request, **kwargs)
    return handler


MSGS = [{"role": "user", "content": "q"}]


class TestGenerateStaysString:
    """Возврат `str` для всех прежних потребителей не изменился."""

    @pytest.mark.asyncio
    async def test_generate_returns_same_string_as_before(self, monkeypatch):
        client = _make_client(_ok_handler(content="привет чат"), monkeypatch)
        result = await client.generate(MSGS)
        assert result == "привет чат"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_generate_and_metadata_agree_on_text(self, monkeypatch):
        """Один и тот же fake-ответ → одинаковый текст у обоих путей."""
        client = _make_client(_ok_handler(content="единый текст"), monkeypatch)
        text = await client.generate(MSGS)
        completion = await client.generate_with_metadata(MSGS)
        assert isinstance(completion, LLMCompletion)
        assert text == completion.text == "единый текст"

    @pytest.mark.asyncio
    async def test_empty_content_still_raises_like_before(self, monkeypatch):
        """Прежняя ошибка пустого контента не подменяется метаданными."""
        from services.llm_client import LLMBadResponseError

        client = _make_client(_ok_handler(content="   "), monkeypatch)
        with pytest.raises(LLMBadResponseError):
            await client.generate(MSGS)


class TestFinishReason:
    @pytest.mark.asyncio
    async def test_length_is_reported_as_length(self, monkeypatch):
        client = _make_client(
            _ok_handler(finish_reason="length"), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.finish_reason == "length"
        assert completion.finish_reason_raw == "length"
        assert completion.is_truncated is True

    @pytest.mark.asyncio
    async def test_stop_is_reported_as_stop(self, monkeypatch):
        client = _make_client(_ok_handler(finish_reason="stop"), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.finish_reason == "stop"
        assert completion.is_truncated is False

    @pytest.mark.asyncio
    async def test_missing_field_is_unknown_not_stop(self, monkeypatch):
        client = _make_client(_ok_handler(), monkeypatch)   # поля нет вовсе
        completion = await client.generate_with_metadata(MSGS)
        assert completion.finish_reason == "unknown"
        assert completion.finish_reason != "stop", "незнакомое ≠ stop"
        assert completion.finish_reason_raw is None
        assert completion.is_truncated is False

    @pytest.mark.asyncio
    async def test_null_field_is_unknown(self, monkeypatch):
        client = _make_client(_ok_handler(finish_reason=None), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.finish_reason == "unknown"
        assert completion.finish_reason_raw is None

    @pytest.mark.asyncio
    async def test_non_string_field_is_unknown(self, monkeypatch):
        client = _make_client(_ok_handler(finish_reason=123), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.finish_reason == "unknown"

    @pytest.mark.asyncio
    async def test_provider_token_normalized_but_raw_kept(self, monkeypatch):
        """Провайдерский регистр нормализуется, сырое значение сохраняется."""
        client = _make_client(
            _ok_handler(finish_reason=" MAX_TOKENS "), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.finish_reason == "max_tokens"
        assert completion.finish_reason_raw == "MAX_TOKENS"
        assert completion.is_truncated is True

    @pytest.mark.asyncio
    async def test_unknown_provider_token_preserved(self, monkeypatch):
        """Незнакомое значение не переписывается в stop/length."""
        client = _make_client(
            _ok_handler(finish_reason="content_filter"), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.finish_reason == "content_filter"
        assert completion.is_truncated is False


class TestUsage:
    @pytest.mark.asyncio
    async def test_usage_returned_as_is(self, monkeypatch):
        usage = {"prompt_tokens": 120, "completion_tokens": 40,
                 "total_tokens": 160}
        client = _make_client(_ok_handler(usage=usage), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.usage == usage

    @pytest.mark.asyncio
    async def test_usage_absent_is_none_not_zeros(self, monkeypatch):
        client = _make_client(_ok_handler(), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.usage is None


class TestMaxOutputTokensSent:
    @pytest.mark.asyncio
    async def test_value_equals_request_body(self, monkeypatch):
        seen = {}

        def handler(request):
            seen["payload"] = json.loads(request.content)
            return _completion(request)

        client = _make_client(handler, monkeypatch)
        completion = await client.generate_with_metadata(
            MSGS, max_output_tokens=1234)
        assert seen["payload"]["max_tokens"] == 1234
        assert completion.max_output_tokens_sent == 1234

    @pytest.mark.asyncio
    async def test_absent_key_is_none(self, monkeypatch):
        seen = {}

        def handler(request):
            seen["payload"] = json.loads(request.content)
            return _completion(request)

        client = _make_client(handler, monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert "max_tokens" not in seen["payload"]
        assert completion.max_output_tokens_sent is None

    @pytest.mark.asyncio
    async def test_non_positive_is_not_sent_and_none(self, monkeypatch):
        seen = {}

        def handler(request):
            seen["payload"] = json.loads(request.content)
            return _completion(request)

        client = _make_client(handler, monkeypatch)
        completion = await client.generate_with_metadata(
            MSGS, max_output_tokens=0)
        assert "max_tokens" not in seen["payload"]
        assert completion.max_output_tokens_sent is None


class TestPrimaryMetadata:
    @pytest.mark.asyncio
    async def test_primary_hop_named_honestly(self, monkeypatch):
        client = _make_client(
            _ok_handler(finish_reason="stop"), monkeypatch)
        completion = await client.generate_with_metadata(
            MSGS, correlation_id="corr-42")
        assert completion.model == "chat-model"
        assert completion.provider == "api.test"
        assert completion.attempt == 1
        assert completion.fallback_used is False
        assert completion.fallback_chain == ()
        assert completion.correlation_id == "corr-42"

    @pytest.mark.asyncio
    async def test_missing_correlation_id_is_not_invented(self, monkeypatch):
        client = _make_client(_ok_handler(), monkeypatch)
        completion = await client.generate_with_metadata(MSGS)
        assert completion.correlation_id is None


class TestFallbackMetadata:
    """Primary отказ → ответила fallback-нога: метаданные про неё же."""

    @pytest.mark.asyncio
    async def test_metadata_names_answering_fallback_and_records_primary(
            self, monkeypatch):
        seen = {}

        def handler(request):
            url = str(request.url)
            if "fallback.test" in url:
                seen["fb"] = json.loads(request.content)
                return _completion(
                    request, content="ответ фоллбэка", finish_reason="length",
                    usage={"prompt_tokens": 10, "completion_tokens": 5})
            seen["primary"] = json.loads(request.content)
            return httpx.Response(502, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=0, **FB)
        completion = await client.generate_with_metadata(MSGS)

        assert completion.text == "ответ фоллбэка"
        # Ответила именно fallback-нога — её модель/провайдер в метаданных.
        assert seen["fb"]["model"] == "fb-model"
        assert completion.model == "fb-model"
        assert completion.provider == "fallback.test"
        assert completion.attempt == 2
        assert completion.fallback_used is True
        # finish_reason не потерян при fallback (пришёл от ответившей ноги).
        assert completion.finish_reason == "length"
        assert completion.usage == {"prompt_tokens": 10, "completion_tokens": 5}
        # Отказ primary сохранён в цепочке.
        assert len(completion.fallback_chain) == 1
        hop = completion.fallback_chain[0]
        assert hop.channel == "primary"
        assert hop.model == "chat-model"
        assert hop.provider == "api.test"
        assert hop.error_type == "LLMServerError"
        assert hop.succeeded is False
        assert hop.error            # R17-safe причина, не пустая
        assert "test-key" not in hop.error

    @pytest.mark.asyncio
    async def test_generate_string_unchanged_in_fallback(self, monkeypatch):
        """Текстовый фасад в fallback-сценарии отдаёт тот же str."""

        def handler(request):
            if "fallback.test" in str(request.url):
                return _completion(request, content="ответ фоллбэка")
            return httpx.Response(502, json={}, request=request)

        client = _make_client(handler, monkeypatch, max_retries=0, **FB)
        assert await client.generate(MSGS) == "ответ фоллбэка"

    @pytest.mark.asyncio
    async def test_max_output_tokens_sent_follows_actual_fallback_body(
            self, monkeypatch):
        """max_output_tokens_sent = ровно отправленное тело, а не запрос.

        Fallback-recompose снял max_tokens → в отправленном теле ключа нет,
        значит метаданные обязаны сказать None (а не 999 из primary-payload).
        """
        seen = {}

        def handler(request):
            if "fallback.test" in str(request.url):
                seen["fb"] = json.loads(request.content)
                return _completion(request)
            seen["primary"] = json.loads(request.content)
            return httpx.Response(502, json={}, request=request)

        def adapter(payload):
            adapted = dict(payload)
            adapted.pop("max_tokens", None)
            return adapted

        client = _make_client(handler, monkeypatch, max_retries=0, **FB)
        completion = await client.generate_with_metadata(
            MSGS, max_output_tokens=999, fallback_payload_adapter=adapter)

        assert seen["primary"]["max_tokens"] == 999
        assert "max_tokens" not in seen["fb"]
        assert completion.max_output_tokens_sent is None
        assert completion.attempt == 2
