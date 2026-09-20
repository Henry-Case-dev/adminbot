"""Хотфикс-3 (round10.25, T-2500/T-2501, ADR-1025-7 D4) — LLM-таймауты:
R17-safe причина + fail-fast дефолт + метрика доли таймаутов/fallback.

Падают на старом коде: не было `llm_stats()`, в логе таймаута не было
`reason=ReadTimeout`, а дефолт `LLM_FALLBACK_TIMEOUT_SECONDS` был 120с.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from config.settings import Settings
from services import llm_client as lc
from services.llm_client import LLMClient, LLMTimeoutError, llm_stats


def _client(**kw) -> LLMClient:
    client = LLMClient(base_url="https://provider.example", api_key="k",
                       chat_model="m", embed_model="e", timeout=5.0,
                       max_retries=1, fallback_base_url="", fallback_model="",
                       fallback_api_key="")
    client.backoff_base = 0            # без реальных пауз между попытками
    for key, value in kw.items():
        setattr(client, key, value)
    return client


class _TimeoutClient:
    """httpx-клиент, всегда роняющий ReadTimeout."""

    async def post(self, *a, **k):
        raise httpx.ReadTimeout("read timed out")


class TestTimeoutObservability:
    def test_stats_shape(self):
        stats = llm_stats()
        assert set(stats) >= {"requests", "timeouts", "fallbacks",
                              "timeout_share"}
        assert isinstance(stats["timeout_share"], float)

    @pytest.mark.asyncio
    async def test_timeout_increments_metric_and_logs_reason(
            self, monkeypatch, caplog):
        client = _client()
        monkeypatch.setattr(client, "_get_client",
                            lambda key=None: _TimeoutClient())
        before = llm_stats()["timeouts"]

        with caplog.at_level("ERROR", logger=lc.__name__):
            with pytest.raises(LLMTimeoutError):
                await client._post("/chat/completions",
                                   {"model": "m", "messages": []},
                                   api_key="k")

        after = llm_stats()["timeouts"]
        assert after == before + 1
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "reason=ReadTimeout" in joined
        assert "provider=provider.example" in joined

    @pytest.mark.asyncio
    async def test_fallback_increments_metric_and_is_labeled(
            self, monkeypatch, caplog):
        client = _client()
        client._fallback_active = True
        client._fallback_model = "fb-model"
        monkeypatch.setattr(client, "_post_with_key",
                            AsyncMock(side_effect=LLMTimeoutError("primary")))
        fb = SimpleNamespace(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "fb text"}}]})
        monkeypatch.setattr(client, "_fallback_with_retries",
                            AsyncMock(return_value=fb))
        before = llm_stats()["fallbacks"]

        with caplog.at_level("WARNING", logger=lc.__name__):
            text = await client.generate([{"role": "user", "content": "hi"}])

        assert text == "fb text"
        assert llm_stats()["fallbacks"] == before + 1
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "LLM fallback attempt" in joined


class TestFailFastDefault:
    def test_fallback_timeout_reduced_to_60(self):
        # T-2500: fail-fast — бюджет фоллбэка снижен 120 → 60с.
        assert Settings.LLM_FALLBACK_TIMEOUT_SECONDS == 60.0
