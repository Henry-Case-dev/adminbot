"""Epic 24 — OpenAI-compatible LLM client (R4/R5, Section 33.4).

One httpx.AsyncClient session per process (lazy creation, close() in on_shutdown).
Endpoints: POST {base_url}/chat/completions and POST {base_url}/embeddings.
Retry: 429/5xx/timeout → up to max_retries with backoff 0.5s * 2**n; 401/403 → LLMAuthError.
"""
import asyncio
import logging
import time

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base error for all LLM client failures."""


class LLMAuthError(LLMError):
    """401/403 — invalid or missing API key."""


class LLMRateLimitError(LLMError):
    """429 — provider rate limit (retries exhausted)."""


class LLMTimeoutError(LLMError):
    """Request timed out (retries exhausted)."""


class LLMBadResponseError(LLMError):
    """Malformed JSON or missing content in a 2xx response."""


class LLMClient:
    """Provider-agnostic async client for chat completions and embeddings."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        chat_model: str,
        embed_model: str,
        timeout: float = settings.LLM_TIMEOUT,
        max_retries: int = settings.LLM_MAX_RETRIES,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._chat_model = chat_model
        self._embed_model = embed_model
        self._timeout = timeout
        self._max_retries = max_retries
        self.backoff_base = 0.5  # tests may set to 0 to avoid real sleeps
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, path: str, payload: dict) -> httpx.Response:
        """POST with retry on 429/5xx/timeout; auth errors raised immediately."""
        client = self._get_client()
        url = f"{self._base_url}{path}"
        request_len = len(str(payload))
        for attempt in range(self._max_retries + 1):
            started = time.monotonic()
            try:
                response = await client.post(url, json=payload)
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    await asyncio.sleep(self.backoff_base * (2 ** attempt))
                    continue
                logger.error("LLM timeout | url=%s attempt=%d", url, attempt)
                raise LLMTimeoutError(f"LLM request timed out: {url}") from exc
            except httpx.HTTPError as exc:
                logger.error("LLM transport error | url=%s: %s", url, exc)
                raise LLMError(f"LLM transport error: {exc}") from exc

            latency_ms = (time.monotonic() - started) * 1000.0
            if response.status_code == 429:
                if attempt < self._max_retries:
                    await asyncio.sleep(self.backoff_base * (2 ** attempt))
                    continue
                raise LLMRateLimitError(
                    f"LLM rate limited (429) after {self._max_retries + 1} attempts: {url}"
                )
            if 500 <= response.status_code < 600:
                if attempt < self._max_retries:
                    await asyncio.sleep(self.backoff_base * (2 ** attempt))
                    continue
                raise LLMError(
                    f"LLM server error {response.status_code} after "
                    f"{self._max_retries + 1} attempts: {url}"
                )
            if response.status_code in (401, 403):
                raise LLMAuthError(f"LLM auth failed ({response.status_code}): {url}")
            if response.status_code >= 400:
                raise LLMError(f"LLM HTTP {response.status_code}: {url}")
            logger.info(
                "LLM request OK | url=%s | status=%d | latency_ms=%.0f | in=%d chars | out=%d chars",
                url, response.status_code, latency_ms, request_len, len(response.content),
            )
            return response
        raise LLMError(f"LLM request failed after retries: {url}")

    async def generate(self, messages: list[dict[str, str]]) -> str:
        """POST /chat/completions → choices[0].message.content."""
        response = await self._post(
            "/chat/completions",
            {"model": self._chat_model, "messages": messages},
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError("chat/completions: invalid JSON response") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMBadResponseError(
                "chat/completions: no choices[0].message.content in response"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMBadResponseError("chat/completions: empty content")
        logger.info(
            "LLM generate OK | model=%s | out_chars=%d", self._chat_model, len(content)
        )
        return content

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """POST /embeddings → data[i].embedding. Raises LLMError on any failure (R3)."""
        if not texts:
            return []
        response = await self._post(
            "/embeddings",
            {"model": self._embed_model, "input": texts},
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError("embeddings: invalid JSON response") from exc
        try:
            vectors = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise LLMBadResponseError("embeddings: no data[].embedding in response") from exc
        logger.info(
            "LLM embed OK | model=%s | texts=%d", self._embed_model, len(vectors)
        )
        return vectors
