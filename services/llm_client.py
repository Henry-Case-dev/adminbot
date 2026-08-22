"""Epic 24 — OpenAI-compatible LLM client (R4/R5, Section 33.4).

One httpx.AsyncClient session per process (lazy creation, close() in on_shutdown).
Endpoints: POST {base_url}/chat/completions and POST {base_url}/embeddings.

Epic 47 (Section 56, D186/D187): ретраятся ВСЕ транзиентные ошибки —
httpx.TransportError (timeout/connect/read/write/pool/network/protocol) +
HTTP 408/425/429/5xx. Сон = `min(BASE*2**attempt, CAP) + U(0, JITTER)`;
для 429/5xx заголовок Retry-After приоритетнее backoff
(сон = min(header_seconds, CAP)); жёсткий total-budget
LLM_TOTAL_BUDGET = asyncio.timeout на всю _post; 401/403 → LLMAuthError
мгновенно. Единственный владелец ретраев — _post (56.4).

Epic 53 (Section 62, D216): классы LLMServerError/LLMTransportError (62.3.2),
диаг-лог финальных 5xx с body_5xx ≤500 (62.5), опциональный фоллбэк-провайдер
LLM_FALLBACK_* (62.4, пустые env = ровно старое поведение). CB живёт в
direct_chat_service (llm_client о нём НЕ знает — контракт 62.3).
"""
import asyncio
import logging
import random
import time

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

_BODY_MAX_CHARS = 500   # Epic 49 (57.4) / Epic 53 (62.5): тело 4xx/5xx-ответа в диагн-логе

# Epic 53 (62.1): худший случай generate = бюджет primary (60с) + фоллбэк без
# таймаута (до 30с per-request) ≈ 90с — противоречит цели «сократить ожидание».
# Фоллбэк ограничен фиксированным бюджетом 30с (как LLM_TIMEOUT).
_FALLBACK_TIMEOUT_SECONDS = 30.0


class LLMError(Exception):
    """Base error for all LLM client failures."""


class LLMAuthError(LLMError):
    """401/403 — invalid or missing API key."""


class LLMRateLimitError(LLMError):
    """429 — provider rate limit (retries exhausted)."""


class LLMTimeoutError(LLMError):
    """Request timed out (retries exhausted)."""


class LLMServerError(LLMError):
    """Epic 53 (62.3.2): исчерпание 5xx — устойчивый отказ апстрима.
    Текст без изменений: «LLM server error {code} after {N} attempts: {url}»."""


class LLMTransportError(LLMError):
    """Epic 53 (62.3.2): исчерпание не-timeout httpx.TransportError.
    Текст без изменений: «LLM transport error after {N} attempts: …»."""


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
        fallback_base_url: str = settings.LLM_FALLBACK_BASE_URL,
        fallback_model: str = settings.LLM_FALLBACK_MODEL,
        fallback_api_key: str = settings.LLM_FALLBACK_API_KEY,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._chat_model = chat_model
        self._embed_model = embed_model
        self._timeout = timeout
        self._max_retries = max_retries
        # Epic 53 (62.4): фоллбэк активен ТОЛЬКО при всех трёх параметрах;
        # частичная конфигурация → WARNING (R17: только факты, без значений),
        # пустые env = ровно старое поведение.
        self._fallback_base_url = (fallback_base_url or "").strip()
        self._fallback_model = (fallback_model or "").strip()
        self._fallback_api_key = (fallback_api_key or "").strip()
        configured = (bool(self._fallback_base_url), bool(self._fallback_model),
                      bool(self._fallback_api_key))
        self._fallback_active = all(configured)
        if any(configured) and not all(configured):
            logger.warning(
                "LLM fallback partially configured — disabled | base=%s model=%s key=%s",
                *configured,
            )
        # Epic 47 (D186): backoff base/cap/jitter + total budget (56.3/56.4).
        # Test-hook: tests may set `client.backoff_base = 0` → сон 0 (jitter тоже 0).
        self.backoff_base = settings.LLM_RETRY_BACKOFF_BASE
        self._backoff_cap = settings.LLM_RETRY_BACKOFF_CAP
        self._jitter_max = settings.LLM_RETRY_JITTER_MAX
        self._budget = settings.LLM_TOTAL_BUDGET
        self._fallback_timeout = _FALLBACK_TIMEOUT_SECONDS
        self._client: httpx.AsyncClient | None = None
        self._fallback_client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    def _get_fallback_client(self) -> httpx.AsyncClient:
        """Epic 53 (62.4): ленивый клиент фоллбэка, тот же таймаут-срез."""
        if self._fallback_client is None:
            self._fallback_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={"Authorization": f"Bearer {self._fallback_api_key}"},
            )
        return self._fallback_client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._fallback_client is not None:
            await self._fallback_client.aclose()
            self._fallback_client = None

    def _sleep_seconds(
        self,
        attempt: int,
        status: int | None = None,
        headers: httpx.Headers | None = None,
    ) -> float:
        """Epic 47 (56.3): сон перед retry.

        Retry-After (429/5xx, парсится как float, ≥0) приоритетнее обычного
        backoff; значение капится LLM_RETRY_BACKOFF_CAP. Кривой/отрицательный
        header либо статус ≠ 429/5xx → обычный backoff
        `min(BASE*2**attempt, CAP) + U(0, JITTER)`. backoff_base == 0 → сон 0.
        """
        if self.backoff_base == 0:
            return 0.0
        if status is not None and (status == 429 or 500 <= status < 600):
            raw = headers.get("Retry-After") if headers is not None else None
            if raw is not None:
                try:
                    header_seconds = float(raw)
                except (TypeError, ValueError):
                    header_seconds = -1.0
                if header_seconds >= 0:
                    return min(header_seconds, self._backoff_cap)
        base_sleep = min(self.backoff_base * (2 ** attempt), self._backoff_cap)
        return base_sleep + random.uniform(0, self._jitter_max)

    async def _post(self, path: str, payload: dict) -> httpx.Response:
        """POST with retry on all transient errors; auth errors raised immediately.

        Единственный владелец LLM-ретраев (56.4, D187). Жёсткий дедлайн всей
        _post — asyncio.timeout(LLM_TOTAL_BUDGET) (56.4).
        """
        client = self._get_client()
        url = f"{self._base_url}{path}"
        request_len = len(str(payload))
        total_attempts = self._max_retries + 1
        started_total = time.monotonic()
        budget_exceeded = False
        try:
            async with asyncio.timeout(self._budget):
                for attempt in range(total_attempts):
                    if attempt > 0 and (time.monotonic() - started_total) >= self._budget:
                        budget_exceeded = True
                        break                   # попытка не стартует (56.4)
                    started = time.monotonic()
                    try:
                        response = await client.post(url, json=payload)
                    except httpx.TransportError as exc:
                        # Транзиентное (timeout/connect/read/.../protocol) → ретрай
                        if attempt < self._max_retries:
                            sleep = self._sleep_seconds(attempt)
                            logger.warning(
                                "LLM request retry | url=%s | attempt=%d/%d | sleep=%.1fs | reason=%s",
                                url, attempt + 1, total_attempts, sleep,
                                f"{type(exc).__name__}: {exc}",
                            )
                            await asyncio.sleep(sleep)
                            continue
                        if isinstance(exc, httpx.TimeoutException):
                            logger.error("LLM timeout | url=%s attempt=%d", url, attempt)
                            raise LLMTimeoutError(
                                f"LLM request timed out after {total_attempts} attempts: {url}"
                            ) from exc
                        raise LLMTransportError(
                            f"LLM transport error after {total_attempts} attempts: {exc}: {url}"
                        ) from exc
                    except httpx.HTTPError as exc:
                        # Не-транспортное (InvalidURL и пр.) → мгновенно
                        raise LLMError(f"LLM HTTP client error: {exc}") from exc

                    status = response.status_code
                    latency_ms = (time.monotonic() - started) * 1000.0
                    if status in (408, 425, 429) or 500 <= status < 600:
                        if attempt < self._max_retries:
                            sleep = self._sleep_seconds(attempt, status, response.headers)
                            logger.warning(
                                "LLM request retry | url=%s | attempt=%d/%d | sleep=%.1fs | reason=%s",
                                url, attempt + 1, total_attempts, sleep, f"status={status}",
                            )
                            await asyncio.sleep(sleep)
                            continue
                        if status == 429:
                            raise LLMRateLimitError(
                                f"LLM rate limited (429) after {total_attempts} attempts: {url}"
                            )
                        if status in (408, 425):
                            raise LLMError(f"LLM HTTP {status}: {url}")
                        # Epic 53 (62.5): диаг-лог финального 5xx ДО raise
                        # LLMServerError — инцидентный сигнал Betterstack. R17:
                        # url без query/секретов, заголовки не логируются,
                        # тело ≤ _BODY_MAX_CHARS. На ретраях тело НЕ логируем.
                        logger.error(
                            "LLM HTTP %d | url=%s | request_len=%d | content_chars=%d | num_messages=%d | body_5xx=%r",
                            status, url, request_len,
                            sum(len(str(m.get("content", ""))) for m in payload.get("messages", [])),
                            len(payload.get("messages", [])),
                            response.text[:_BODY_MAX_CHARS],
                        )
                        raise LLMServerError(
                            f"LLM server error {status} after "
                            f"{total_attempts} attempts: {url}"
                        )
                    if status in (401, 403):
                        raise LLMAuthError(f"LLM auth failed ({status}): {url}")
                    if status >= 400:
                        # Epic 49 (57.4, D197): детерминированное отклонение провайдера —
                        # инцидентный сигнал в Betterstack. R17: url без query/секретов,
                        # тело ≤ 500 симв., заголовки не логируются.
                        logger.error(
                            "LLM HTTP %d | url=%s | request_len=%d | content_chars=%d | num_messages=%d | body_4xx=%r",
                            status, url, request_len,
                            sum(len(str(m.get("content", ""))) for m in payload.get("messages", [])),
                            len(payload.get("messages", [])),
                            response.text[:_BODY_MAX_CHARS],
                        )
                        raise LLMError(f"LLM HTTP {status}: {url}")
                    logger.info(
                        "LLM request OK | url=%s | status=%d | latency_ms=%.0f | in=%d chars | out=%d chars",
                        url, status, latency_ms, request_len, len(response.content),
                    )
                    return response
        except asyncio.TimeoutError:
            raise LLMTimeoutError(
                f"LLM request timed out after {total_attempts} attempts: {url}"
            ) from None
        if budget_exceeded:
            raise LLMTimeoutError(
                f"LLM request timed out after {total_attempts} attempts: {url}"
            )
        raise LLMError(f"LLM request failed after retries: {url}")

    async def _post_fallback(self, payload: dict) -> httpx.Response:
        """Epic 53 (62.4): РОВНО одна попытка на фоллбэке, БЕЗ ретраев.

        Тот же messages-payload, model заменён на LLM_FALLBACK_MODEL.
        Ошибки (транспорт/не-2xx) разбирает вызывающий — проброс исходного
        исключения primary.
        """
        client = self._get_fallback_client()
        url = f"{self._fallback_base_url.rstrip('/')}/chat/completions"
        fallback_payload = dict(payload)
        fallback_payload["model"] = self._fallback_model
        return await client.post(url, json=fallback_payload)

    async def generate(self, messages: list[dict[str, str]]) -> str:
        """POST /chat/completions → choices[0].message.content.

        Epic 53 (62.4): при LLMError primary (кроме LLMBadResponseError) и
        активном фоллбэке — 1 попытка на фоллбэке; фейл фоллбэка → проброс
        ИСХОДНОГО исключения primary (CB-классификация работает по классу).
        """
        payload = {"model": self._chat_model, "messages": messages}
        try:
            response = await self._post("/chat/completions", payload)
        except LLMError as exc:
            if not self._fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            logger.warning("LLM fallback attempt | primary_error=%s", exc)
            try:
                async with asyncio.timeout(self._fallback_timeout):
                    fallback_response = await self._post_fallback(payload)
                    fallback_status = fallback_response.status_code
            except Exception as fallback_exc:
                logger.warning("LLM fallback failed | error=%s", fallback_exc)
                raise exc from None
            if fallback_status != 200:
                logger.warning(
                    "LLM fallback failed | error=status=%d", fallback_status
                )
                raise exc
            response = fallback_response
            logger.warning("LLM fallback OK | model=%s", self._fallback_model)
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
