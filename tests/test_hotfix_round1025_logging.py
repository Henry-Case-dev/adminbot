"""ASAP-хотфикс round1025 (T-2467/T-2469) — честная диагностика LLM-фолбэка.

Проверяем, что финальный WARNING фолбэка несёт:
  * ТЕКСТ причины (repr при пустом str — httpx.ReadTimeout),
  * контекст provider (только hostname, R17) / model / timeout / attempts,
и что секреты в лог не утекают.
Логика ретраев (`_fallback_with_retries`) НЕ меняется.
"""
import logging

import httpx
import pytest

from services import llm_client as llm


class _FallbackStub:
    """Минимальный носитель полей метода `_fallback_with_retries`."""

    _fallback_max_retries = 0
    backoff_base = 0
    _backoff_cap = 0
    _fallback_timeout = 5.0
    _fallback_base_url = "https://nano-gpt.example/v1"
    _fallback_model = "deepseek-flash"

    def _get_fallback_client(self):          # pragma: no cover — не вызывается
        raise AssertionError("unexpected")

    async def _post_fallback(self, payload, path="/chat/completions", model=None):
        raise self._exc


class TestSafeErrorTextRound1025:
    def test_empty_str_falls_back_to_repr(self):
        text = llm._safe_exc_text(httpx.ReadTimeout(""))
        assert text                                # не пусто
        assert "ReadTimeout" in text

    def test_masks_secret_value(self):
        text = llm._safe_exc_text(RuntimeError("api_key=sk-secretvalue123"))
        assert "sk-secretvalue123" not in text
        assert "***" in text

    def test_provider_host_only(self):
        assert llm._provider_host("https://nano-gpt.example/v1") == \
            "nano-gpt.example"
        assert llm._provider_host("") == "-"


class TestFallbackLogRound1025:
    @pytest.mark.asyncio
    async def test_log_has_text_provider_model_timeout_attempts(self, caplog):
        stub = _FallbackStub()
        stub._exc = httpx.ReadTimeout("")
        with caplog.at_level(logging.WARNING, logger="services.llm_client"):
            result = await llm.LLMClient._fallback_with_retries(
                stub, {"model": "x", "messages": []})
        assert result is None
        text = caplog.text
        assert "LLM fallback failed" in text
        # T-2467: пустой str заменён на repr — лог не «ReadTimeout: »
        assert "ReadTimeout: ReadTimeout" in text
        assert "provider=nano-gpt.example" in text
        assert "model=deepseek-flash" in text
        assert "timeout=5.0" in text
        assert "attempts=1" in text
