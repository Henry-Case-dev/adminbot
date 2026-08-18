"""Tests for services/web_content_extractor.py (T-298, R38-3, D134/D136, Section 47.6).

httpx.MockTransport с monkeypatch-фабрикой httpx.AsyncClient (прецедент
test_search_aggregator.py). trafilatura мокается целиком
через services.web_content_extractor.trafilatura (MagicMock + fake .extract —
работает и без установленного пакета). Каскад: trafilatura → Tavily /extract →
Exa /contents; успех уровня — СТРОГО >150 символов (ровно 150 → фолбек);
пустые ключи → skip с WARNING; ретраев внутри уровней НЕТ.
"""
import json
import logging

import httpx
import pytest
from unittest.mock import MagicMock

from services.web_content_extractor import (
    EXA_CONTENTS_URL,
    TAVILY_EXTRACT_URL,
    _USER_AGENT,
    WebContentExtractionFailedException,
    WebContentExtractor,
)

TARGET = "https://example.com/article"

TRAF_TEXT = "трафилатура: локально извлечённый контент страницы " * 4   # >150
TAVILY_TEXT = "tavily raw_content из облачного экстрактора " * 5         # >150
EXA_TEXT = "exa contents text от экса-бэкенда " * 5                      # >150


def _make_extractor(handler, monkeypatch, trafilatura_result=TRAF_TEXT, **kwargs):
    """WebContentExtractor с httpx.MockTransport; requests — список
    (url, request, body); get_calls — kwargs клиентских get/post-вызовов."""
    requests = []
    get_calls = []

    async def _tracking_handler(request):
        body = await request.aread()
        requests.append((str(request.url), request, body))
        return handler(request)

    transport = httpx.MockTransport(_tracking_handler)
    original = httpx.AsyncClient

    class _CapturingClient(httpx.AsyncClient):
        def get(self, url, **kw):
            get_calls.append(("GET", kw))
            return super().get(url, **kw)

        def post(self, url, **kw):
            get_calls.append(("POST", kw))
            return super().post(url, **kw)

    def factory(**kw):
        return _CapturingClient(transport=transport, **kw)

    monkeypatch.setattr("services.web_content_extractor.httpx.AsyncClient", factory)
    fake = MagicMock()
    fake.extract = MagicMock(return_value=trafilatura_result)
    monkeypatch.setattr("services.web_content_extractor.trafilatura", fake)
    extractor = WebContentExtractor(
        tavily_api_key=kwargs.pop("tavily_api_key", "tav-key"),
        exa_api_key=kwargs.pop("exa_api_key", "exa-key"),
    )
    return extractor, requests, fake, get_calls


def _ok_html_handler(body="<html><article>статья</article></html>"):
    def handler(request):
        return httpx.Response(200, text=body, request=request)

    return handler


def _status_handler(*statuses):
    statuses = list(statuses)

    def handler(request):
        return httpx.Response(statuses.pop(0), text="", request=request)

    return handler


def _json_handler(payload, status=200):
    def handler(request):
        return httpx.Response(status, json=payload, request=request)

    return handler


class TestTrafilaturaSuccess:
    @pytest.mark.asyncio
    async def test_success_single_get_with_ua_redirects_timeout(self, monkeypatch, caplog):
        """#1: РОВНО 1 запрос (GET target), UA Chrome/122, follow_redirects=True,
        timeout 10.0, результат == текст; INFO level ok | provider=trafilatura."""
        extractor, requests, fake, get_calls = _make_extractor(
            _ok_html_handler(), monkeypatch
        )
        with caplog.at_level(logging.INFO):
            result = await extractor.extract(TARGET, 4000)
        assert result == TRAF_TEXT
        assert len(requests) == 1
        assert requests[0][0] == TARGET
        assert requests[0][1].headers["User-Agent"] == _USER_AGENT
        method, kwargs = get_calls[0]
        assert method == "GET"
        assert kwargs["follow_redirects"] is True
        assert kwargs["timeout"].read == 10.0
        assert any("level ok" in r.message and "trafilatura" in r.message
                   for r in caplog.records)
        fake.extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_truncate_to_max_symbols(self, monkeypatch):
        """#2: max_symbols меньше текста → жёсткий срез len == max_symbols."""
        extractor, _, _, _ = _make_extractor(_ok_html_handler(), monkeypatch)
        result = await extractor.extract(TARGET, 60)
        assert len(result) == 60
        assert result == TRAF_TEXT[:60]


class TestTrafilaturaFallbacks:
    @pytest.mark.asyncio
    async def test_trafilatura_none_falls_back_to_tavily(self, monkeypatch):
        """#3: extract → None → Tavily: запросы [target, TAVILY]; json-тело
        {"urls":[target],"api_key":…}; результат == raw_content."""
        handler = _json_handler({"results": [{"raw_content": TAVILY_TEXT}]})
        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        result = await extractor.extract(TARGET, 4000)
        assert result == TAVILY_TEXT
        assert [url for url, _, _ in requests] == [TARGET, TAVILY_EXTRACT_URL]
        assert json.loads(requests[1][2]) == {
            "urls": [TARGET], "api_key": "tav-key",
        }

    @pytest.mark.asyncio
    async def test_trafilatura_short_content_falls_back_to_tavily(self, monkeypatch):
        """#4: текст ≤150 → фолбек Tavily (порог в общем цикле extract())."""
        handler = _json_handler({"results": [{"raw_content": TAVILY_TEXT}]})
        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result="коротко"
        )
        result = await extractor.extract(TARGET, 4000)
        assert result == TAVILY_TEXT
        assert [url for url, _, _ in requests] == [TARGET, TAVILY_EXTRACT_URL]

    @pytest.mark.asyncio
    async def test_trafilatura_http_403_falls_back_to_tavily(self, monkeypatch):
        """#5: GET → 403 → фолбек Tavily (ретраев нет, РОВНО 1 GET)."""
        responses = [403, 200]
        payloads = [{}, {"results": [{"raw_content": TAVILY_TEXT}]}]

        def handler(request):
            return httpx.Response(
                responses.pop(0), json=payloads.pop(0), request=request
            )

        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        result = await extractor.extract(TARGET, 4000)
        assert result == TAVILY_TEXT
        assert [url for url, _, _ in requests] == [TARGET, TAVILY_EXTRACT_URL]

    @pytest.mark.asyncio
    async def test_trafilatura_timeout_falls_back_to_tavily(self, monkeypatch):
        """#6: httpx.TimeoutException на GET → фолбек Tavily, без ретраев."""

        def handler(request):
            if str(request.url) == TARGET:
                raise httpx.TimeoutException("timed out", request=request)
            return httpx.Response(
                200, json={"results": [{"raw_content": TAVILY_TEXT}]}, request=request
            )

        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        result = await extractor.extract(TARGET, 4000)
        assert result == TAVILY_TEXT
        assert [url for url, _, _ in requests] == [TARGET, TAVILY_EXTRACT_URL]

    @pytest.mark.asyncio
    async def test_trafilatura_extract_raises_falls_back_to_tavily(self, monkeypatch):
        """#7: trafilatura.extract raise (lxml-ошибка) → фолбек Tavily."""
        handler = _json_handler({"results": [{"raw_content": TAVILY_TEXT}]})
        extractor, requests, fake, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        fake.extract = MagicMock(side_effect=RuntimeError("lxml boom"))
        result = await extractor.extract(TARGET, 4000)
        assert result == TAVILY_TEXT
        assert [url for url, _, _ in requests] == [TARGET, TAVILY_EXTRACT_URL]


class TestTavilyFallbacks:
    @pytest.mark.asyncio
    async def test_tavily_500_falls_back_to_exa(self, monkeypatch):
        """#8: Tavily 500 → Exa: запросы [target, TAVILY, EXA]; хедер x-api-key;
        результат == results[0]["text"]."""

        def handler(request):
            if str(request.url) == TAVILY_EXTRACT_URL:
                return httpx.Response(500, json={}, request=request)
            if str(request.url) == EXA_CONTENTS_URL:
                return httpx.Response(
                    200, json={"results": [{"text": EXA_TEXT}]}, request=request
                )
            return httpx.Response(200, text="<html></html>", request=request)

        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        result = await extractor.extract(TARGET, 4000)
        assert result == EXA_TEXT
        assert [url for url, _, _ in requests] == [
            TARGET, TAVILY_EXTRACT_URL, EXA_CONTENTS_URL,
        ]
        assert requests[2][1].headers["x-api-key"] == "exa-key"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {"results": []},
            {"results": [{"raw_content": "   "}]},
            {"results": [{"raw_content": ""}]},
        ],
    )
    async def test_tavily_empty_raw_content_falls_back_to_exa(self, monkeypatch, payload):
        """#9: пустые results / пробельный / пустой raw_content → фолбек Exa."""

        def handler(request):
            if str(request.url) == TAVILY_EXTRACT_URL:
                return httpx.Response(200, json=payload, request=request)
            if str(request.url) == EXA_CONTENTS_URL:
                return httpx.Response(
                    200, json={"results": [{"text": EXA_TEXT}]}, request=request
                )
            return httpx.Response(200, text="<html></html>", request=request)

        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        result = await extractor.extract(TARGET, 4000)
        assert result == EXA_TEXT
        assert [url for url, _, _ in requests] == [
            TARGET, TAVILY_EXTRACT_URL, EXA_CONTENTS_URL,
        ]

    @pytest.mark.asyncio
    async def test_tavily_non_json_response_falls_back_to_exa(self, monkeypatch):
        """#18b: Tavily отвечает не-JSON → json() падает → фолбек Exa."""

        def handler(request):
            if str(request.url) == TAVILY_EXTRACT_URL:
                return httpx.Response(200, text="not json", request=request)
            return httpx.Response(
                200, json={"results": [{"text": EXA_TEXT}]}, request=request
            )

        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        result = await extractor.extract(TARGET, 4000)
        assert result == EXA_TEXT
        assert [url for url, _, _ in requests] == [
            TARGET, TAVILY_EXTRACT_URL, EXA_CONTENTS_URL,
        ]


class TestAllLevelsFailed:
    @pytest.mark.asyncio
    async def test_all_three_levels_fail_raises(self, monkeypatch):
        """#10 (сценарий ТЗ №4): все уровни падают →
        WebContentExtractionFailedException, сообщение содержит url."""
        extractor, requests, _, _ = _make_extractor(
            _status_handler(500, 500, 500), monkeypatch, trafilatura_result=None
        )
        with pytest.raises(WebContentExtractionFailedException) as exc_info:
            await extractor.extract(TARGET, 4000)
        assert TARGET in str(exc_info.value)
        assert [url for url, _, _ in requests] == [
            TARGET, TAVILY_EXTRACT_URL, EXA_CONTENTS_URL,
        ]

    @pytest.mark.asyncio
    async def test_exa_empty_text_all_failed(self, monkeypatch):
        """#18a: Exa вернул пустой text → все уровни упали → исключение."""

        def handler(request):
            if str(request.url) == TAVILY_EXTRACT_URL:
                return httpx.Response(500, json={}, request=request)
            if str(request.url) == EXA_CONTENTS_URL:
                return httpx.Response(
                    200, json={"results": [{"text": " "}]}, request=request
                )
            return httpx.Response(200, text="<html></html>", request=request)

        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        with pytest.raises(WebContentExtractionFailedException):
            await extractor.extract(TARGET, 4000)
        assert len(requests) == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("length,expected_provider", [(150, "tavily"), (151, None)])
    async def test_threshold_150_fail_151_success(
        self, monkeypatch, length, expected_provider
    ):
        """#11: ровно 150 → фейл уровня → Tavily; 151 → успех trafilatura."""
        handler = _json_handler({"results": [{"raw_content": TAVILY_TEXT}]})
        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result="x" * length
        )
        result = await extractor.extract(TARGET, 4000)
        if length == 150:
            assert result == TAVILY_TEXT
            assert [url for url, _, _ in requests] == [TARGET, TAVILY_EXTRACT_URL]
        else:
            assert result == "x" * 151
            assert len(requests) == 1


class TestEmptyKeys:
    @pytest.mark.asyncio
    async def test_empty_tavily_key_skips_to_exa(self, monkeypatch, caplog):
        """#12: пустой tavily_api_key → skip → Exa: запросы [target, EXA],
        WARNING level skipped."""
        handler = _json_handler({"results": [{"text": EXA_TEXT}]})
        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None, tavily_api_key=""
        )
        with caplog.at_level(logging.WARNING):
            result = await extractor.extract(TARGET, 4000)
        assert result == EXA_TEXT
        assert [url for url, _, _ in requests] == [TARGET, EXA_CONTENTS_URL]
        assert any("level skipped" in r.message and "tavily" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_both_keys_empty_trafilatura_fails_raises(self, monkeypatch):
        """#13: оба ключа пустые + trafilatura фейл → исключение; к Tavily/Exa
        НЕ обращаемся (только GET target)."""
        extractor, requests, _, _ = _make_extractor(
            _ok_html_handler(), monkeypatch,
            trafilatura_result=None, tavily_api_key="", exa_api_key="",
        )
        with pytest.raises(WebContentExtractionFailedException):
            await extractor.extract(TARGET, 4000)
        assert [url for url, _, _ in requests] == [TARGET]

    @pytest.mark.asyncio
    async def test_whitespace_key_treated_as_empty(self, monkeypatch):
        """#14: ключ "   " == пустой → skip."""
        handler = _json_handler({"results": [{"text": EXA_TEXT}]})
        extractor, requests, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None, tavily_api_key="   "
        )
        result = await extractor.extract(TARGET, 4000)
        assert result == EXA_TEXT
        assert [url for url, _, _ in requests] == [TARGET, EXA_CONTENTS_URL]


class TestLifecycleAndLogs:
    def test_log_config_warns_on_empty_keys(self, caplog):
        """#15: log_config() → WARNING при пустых ключах."""
        extractor = WebContentExtractor(tavily_api_key="", exa_api_key="")
        with caplog.at_level(logging.WARNING):
            extractor.log_config()
        assert any("TAVILY_API_KEY" in r.message for r in caplog.records)
        assert any("EXA_API_KEY" in r.message for r in caplog.records)

    def test_log_config_silent_with_keys(self, caplog):
        extractor = WebContentExtractor(tavily_api_key="k", exa_api_key="k")
        with caplog.at_level(logging.WARNING):
            extractor.log_config()
        assert caplog.records == []

    @pytest.mark.asyncio
    async def test_close_before_any_request_is_noop(self, monkeypatch):
        """#16a: close() до запроса — no-op."""
        extractor, _, _, _ = _make_extractor(_ok_html_handler(), monkeypatch)
        await extractor.close()
        assert extractor._client is None

    @pytest.mark.asyncio
    async def test_close_after_request_closes_client(self, monkeypatch):
        """#16b: close() после запроса — клиент закрыт."""
        extractor, _, _, _ = _make_extractor(_ok_html_handler(), monkeypatch)
        await extractor.extract(TARGET, 4000)
        assert extractor._client is not None
        await extractor.close()
        assert extractor._client is None

    @pytest.mark.asyncio
    async def test_level_logs_failed_then_ok(self, monkeypatch, caplog):
        """#17: WARNING level failed → fallback (trafilatura) + INFO level ok
        (tavily) с latency_ms/chars."""
        handler = _json_handler({"results": [{"raw_content": TAVILY_TEXT}]})
        extractor, _, _, _ = _make_extractor(
            handler, monkeypatch, trafilatura_result=None
        )
        with caplog.at_level(logging.INFO):
            await extractor.extract(TARGET, 4000)
        failed = [r for r in caplog.records
                  if "level failed" in r.message and "trafilatura" in r.message]
        assert failed and failed[0].levelno == logging.WARNING
        ok = [r for r in caplog.records
              if "level ok" in r.message and "tavily" in r.message]
        assert ok and ok[0].levelno == logging.INFO
        assert "latency_ms=" in ok[0].message
        assert "chars=" in ok[0].message
