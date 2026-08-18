"""Epic 37 — Jina Reader (R37-3, D127, Section 46.5)."""
import asyncio
import logging
import time

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

JINA_BASE_URL = "https://r.jina.ai"
_TIMEOUT = 30.0          # D127: per-request (общий)
_CONNECT_TIMEOUT = 10.0
_MAX_RETRIES = 2         # D127: только 429/5xx/timeout
_BACKOFF_BASE = 0.5      # 0.5 * 2**n (прецедент LLMClient.backoff_base)


class JinaReaderException(Exception):
    """Любой отказ Jina (404/403/timeout/пустой ответ/транспорт). → пул 5.7."""


class JinaReader:
    def __init__(self, api_key: str = settings.JINA_API_KEY) -> None:
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self.backoff_base = _BACKOFF_BASE   # tests may set to 0 to avoid real sleeps

    def _get_client(self) -> httpx.AsyncClient:
        """Ленивый клиент: httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT,
        connect=_CONNECT_TIMEOUT)) (прецедент SearchAggregator._get_client)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(_TIMEOUT, connect=_CONNECT_TIMEOUT)
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        """{"X-Return-Format": "markdown",
        "X-Target-Selector": "article, main, body"} +
        {"Authorization": f"Bearer {self._api_key}"} ТОЛЬКО если ключ непустой."""
        headers = {
            "X-Return-Format": "markdown",
            "X-Target-Selector": "article, main, body",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def fetch_markdown(self, target_url: str, max_symbols: int) -> str:
        """GET {JINA_BASE_URL}/{target_url} с ретраями (таблица ниже) →
        тело как текст; пустое/пробельное тело → JinaReaderException
        («пустая страница»); успех → text[:max_symbols] (жёсткий срез).
        INFO-логи: latency_ms + chars (прецедент SearchAggregator)."""
        client = self._get_client()
        url = f"{JINA_BASE_URL}/{target_url}"
        for attempt in range(_MAX_RETRIES + 1):
            started = time.monotonic()
            try:
                response = await client.get(url, headers=self._headers())
            except httpx.TimeoutException as exc:
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(self.backoff_base * (2 ** attempt))
                    continue
                raise JinaReaderException(
                    f"Jina timeout after retries | url={url}"
                ) from exc
            except httpx.HTTPError as exc:
                raise JinaReaderException(
                    f"Jina transport error | url={url} ({exc})"
                ) from exc

            latency_ms = (time.monotonic() - started) * 1000.0
            status = response.status_code
            if status == 200:
                text = response.text
                if not text.strip():
                    raise JinaReaderException(f"Jina empty page | url={url}")
                logger.info(
                    "JinaReader OK | url=%s | latency_ms=%.0f | chars=%d",
                    target_url, latency_ms, len(text),
                )
                return self._truncate(text, max_symbols)
            if status in (401, 403, 404):
                # пейволл/закрытость не лечатся ретраями — мгновенный фейл (D127)
                raise JinaReaderException(f"Jina HTTP {status} | url={url}")
            if status == 429 or 500 <= status < 600:
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(self.backoff_base * (2 ** attempt))
                    continue
                raise JinaReaderException(
                    f"Jina HTTP {status} after retries | url={url}"
                )
            raise JinaReaderException(f"Jina HTTP {status} | url={url}")
        raise JinaReaderException(f"Jina failed after retries | url={url}")  # pragma: no cover

    async def close(self) -> None:
        """Закрыть ленивый клиент (on_shutdown)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _truncate(text: str, max_symbols: int) -> str:
        """text[:max_symbols] (прецедент SearchAggregator._truncate)."""
        return text[:max_symbols]
