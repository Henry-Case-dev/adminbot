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
import re
import time

from dataclasses import dataclass

import httpx

from config.settings import settings
from services import hot_config as hot
from services.status_service import status as status_service

logger = logging.getLogger(__name__)

_BODY_MAX_CHARS = 500   # Epic 49 (57.4) / Epic 53 (62.5): тело 4xx/5xx-ответа в диагн-логе
_AUTH_BODY_MAX_CHARS = 200   # Задача 2 (01.09.2026): тело 401/403 в LLMAuthError

# R17: маскировка потенциальных секретов в телах ошибок провайдера.
# (а) ключ-значение: api key/key/token/secret/authorization (пробел допустим,
# \b-границы) + (б) известные префиксы ключей в ЛЮБОМ контексте
# (sk-/sk-or-/gsk_/tvly-/xoxb- и т.п.) + (в) Bearer <токен>.
# JSON-форма (ревью-блокер 01.09.2026): '"key" : "value"' — опциональная
# кавычка ДО двоеточия тоже в сепараторе; значение в кавычках — целиком.
# Ревью-фикс: re.IGNORECASE — bearer/basic в любом регистре + Token/Api-Key
# (контракт log_ring.py, там Bearer уже IGNORECASE). \b сохраняет guard:
# 'pot_token'/'access_token' НЕ маскируются (граница слова).
_SECRET_PAIR_RE = re.compile(
    r'(\b(?:api[\s_-]?key|key|token|secret|authorization)\b)'
    r'(\s*"?\s*[:=]\s*"?)(?!Bearer\b|Basic\b)([^"\s,}]{4,})',
    re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(
    r'(?<![A-Za-z0-9])(?:sk|gsk|tvly|xoxb)[_-][A-Za-z0-9_-]{8,}',
    re.IGNORECASE)
_BEARER_RE = re.compile(r'(\bBearer\s+)[^\s,}"\']+', re.IGNORECASE)
_BASIC_RE = re.compile(r'(\bBasic\s+)[^\s,}"\']+', re.IGNORECASE)


def _mask_secrets(text: str) -> str:
    """Маскировка секретов (R17): Bearer/Basic <токен> (сначала — иначе
    пара authorization: Bearer … съест 'Bearer' как значение), пары
    ключ=значение (в т.ч. JSON-форма '"key": "value"'), префикс-ключи
    (sk-…/gsk_…/tvly-…/xoxb-…) → ***. Префикс bearer/basic сохраняется
    в исходном регистре (контракт log_ring.py)."""
    masked = _BEARER_RE.sub(r"\1***", text)
    masked = _BASIC_RE.sub(r"\1***", masked)
    masked = _SECRET_PAIR_RE.sub(r"\1\2***", masked)
    return _SECRET_VALUE_RE.sub("***", masked)


def _sanitize_snippet(text: str, max_chars: int = _AUTH_BODY_MAX_CHARS) -> str:
    """Обрезанное (≤200) тело ответа с маскировкой секретов — для
    LLMAuthError/диаг-логов 401/403 (R17). Пусто/не str → ""."""
    if not text:
        return ""
    masked = _mask_secrets(text)
    masked = masked.replace("\n", " ").replace("\r", " ").strip()
    return masked[:max_chars]


async def _aclose(client: httpx.AsyncClient) -> None:
    try:
        await client.aclose()
    except Exception:  # pragma: no cover — закрытие старого клиента не критично
        pass

# Epic 53 (62.1): худший случай generate = бюджет primary + фоллбэк.
# Epic 64: бюджет фоллбэка больше НЕ константа 30с — настройка
# LLM_FALLBACK_TIMEOUT_SECONDS (дефолт 120с: реальный запрос к DeepSeek
# занимает ~15с; при ретраях 30с не хватало даже на две попытки).


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


# ── Эпик 04.09.2026 (3.3): результат generate_chat (Tool Calling) ──────────

@dataclass(frozen=True)
class LLMToolCall:
    """Один tool_call из ответа модели (3.3)."""

    id: str            # tool_call_id для role:"tool"
    name: str
    arguments: str     # JSON-строка аргументов (парсит исполнитель)

    def as_openai_dict(self) -> dict:
        """Сериализация для повторного запроса (assistant.tool_calls)."""
        return {"id": self.id, "type": "function",
                "function": {"name": self.name, "arguments": self.arguments}}


@dataclass(frozen=True)
class LLMChatResult:
    """Разобранный ответ /chat/completions (generate_chat)."""

    content: str | None        # текст финального ответа (None при tool_calls)
    tool_calls: list[LLMToolCall] | None
    finish_reason: str | None


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
        # Embed-фоллбэк (EMBEDDING_FALLBACK_*): НЕЗАВИСИМ от chat-фоллбэка
        # LLM_FALLBACK_* (62.4) — только для /embeddings.
        embed_fallback_base_url: str = settings.EMBEDDING_FALLBACK_BASE_URL,
        embed_fallback_api_key: str = settings.EMBEDDING_FALLBACK_API_KEY,
        embed_fallback_model: str = settings.EMBEDDING_FALLBACK_MODEL,
        embed_fallback_timeout: float = settings.EMBEDDING_FALLBACK_TIMEOUT_SECONDS,
        embed_fallback_max_retries: int = settings.EMBEDDING_FALLBACK_MAX_RETRIES,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._chat_model = chat_model
        self._embed_model = embed_model
        # Миграция read-пути (2026-09-03): таймауты/ретраи читаются через
        # hot.get ВНУТРИ __init__ (в дефолтах бейкдились при импорте) —
        # значения из админки действуют при создании клиента.
        self._timeout = hot.get("models.llm_timeout", timeout)
        self._max_retries = hot.get("models.llm_max_retries", max_retries)
        # Epic 53 (62.4): фоллбэк активен ТОЛЬКО при всех трёх параметрах;
        # частичная конфигурация → WARNING (R17: только факты, без значений),
        # пустые env = ровно старое поведение.
        self._fallback_base_url = (hot.get("models.llm_fallback_base_url",
                                           fallback_base_url)
                                   or fallback_base_url or "").strip()
        self._fallback_model = (hot.get("models.llm_fallback_model",
                                        fallback_model)
                                or fallback_model or "").strip()
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
        self.backoff_base = hot.get("models.llm_retry_backoff_base", settings.LLM_RETRY_BACKOFF_BASE)
        self._backoff_cap = hot.get("models.llm_retry_backoff_cap", settings.LLM_RETRY_BACKOFF_CAP)
        self._jitter_max = hot.get("models.llm_retry_jitter_max", settings.LLM_RETRY_JITTER_MAX)
        self._budget = hot.get("models.llm_total_budget", settings.LLM_TOTAL_BUDGET)
        # Epic 64: бюджет фоллбэка — настройка (было жёстко 30с), плюс ретраи
        # транзиентных отказов самого фоллбэка.
        self._fallback_timeout = hot.get("models.llm_fallback_timeout_seconds", settings.LLM_FALLBACK_TIMEOUT_SECONDS)
        self._fallback_max_retries = hot.get("models.llm_fallback_max_retries", settings.LLM_FALLBACK_MAX_RETRIES)
        # Embed-фоллбэк (раунд 5): активен ТОЛЬКО при base_url + api_key;
        # пустая модель → primary embed-модель. Параметры infra (категория
        # None в param_catalog) — горячего каталога/admin-кэша у них НЕТ.
        self._embed_fallback_base_url = (embed_fallback_base_url or "").strip()
        self._embed_fallback_api_key = (embed_fallback_api_key or "").strip()
        self._embed_fallback_model = ((embed_fallback_model or "").strip()
                                      or self._embed_model)
        self._embed_fallback_timeout = embed_fallback_timeout
        self._embed_fallback_max_retries = embed_fallback_max_retries
        self._embed_fallback_active = bool(self._embed_fallback_base_url) and \
            bool(self._embed_fallback_api_key)
        self._client: httpx.AsyncClient | None = None
        self._client_key: str | None = None
        self._fallback_client: httpx.AsyncClient | None = None
        self._fallback_key: str | None = None
        self._embed_fallback_client: httpx.AsyncClient | None = None

    def _current_api_key(self) -> str:
        """T-619 (84.4): ключ читается из ConfigCache на ВЫЗОВ; ключа нет в
        БД → значение из .env/settings (ровно старое поведение до миграции)."""
        return hot.get("keys.llm_api_key", self._api_key) or ""

    def _current_fallback_key(self) -> str:
        return hot.get("keys.llm_fallback_api_key",
                       self._fallback_api_key) or ""

    @staticmethod
    def _close_async(client: httpx.AsyncClient) -> None:
        """Закрытие старого клиента при смене ключа (fire-and-forget)."""
        try:
            asyncio.create_task(_aclose(client))
        except RuntimeError:
            pass                     # нет running loop — GC подберёт

    def _get_client(self) -> httpx.AsyncClient:
        key = self._current_api_key()
        if self._client is not None and key != self._client_key:
            self._close_async(self._client)
            self._client = None
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={"Authorization": f"Bearer {key}"},
            )
            self._client_key = key
        return self._client

    def _get_fallback_client(self) -> httpx.AsyncClient:
        """Epic 53 (62.4): ленивый клиент фоллбэка, тот же таймаут-срез.
        T-619: ключ фоллбэка — горячая точка (пересоздание при смене)."""
        key = self._current_fallback_key()
        if self._fallback_client is not None and key != self._fallback_key:
            self._close_async(self._fallback_client)
            self._fallback_client = None
        if self._fallback_client is None:
            self._fallback_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={"Authorization": f"Bearer {key}"},
            )
            self._fallback_key = key
        return self._fallback_client

    def _get_embed_fallback_client(self) -> httpx.AsyncClient:
        """Ленивый клиент embed-фоллбэка: свой Bearer-ключ
        (EMBEDDING_FALLBACK_API_KEY), per-request таймаут
        EMBEDDING_FALLBACK_TIMEOUT_SECONDS (паттерн _get_client, без hot-ротации
        — ключ infra, только .env)."""
        if self._embed_fallback_client is None:
            self._embed_fallback_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._embed_fallback_timeout,
                                       connect=10.0),
                headers={"Authorization":
                         f"Bearer {self._embed_fallback_api_key}"},
            )
        return self._embed_fallback_client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._fallback_client is not None:
            await self._fallback_client.aclose()
            self._fallback_client = None
        if self._embed_fallback_client is not None:
            await self._embed_fallback_client.aclose()
            self._embed_fallback_client = None

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
                    # Epic 85 (84.11.2): замер латентности для /api/status
                    status_service.record_llm(
                        "deepseek", latency_ms,
                        None if status < 500 else f"status={status}")
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
                        # Задача 2 (01.09.2026): диаг-лог + тело в исключении
                        # (обрезанное, секреты замаскированы — R17), чтобы
                        # 403 «insufficient balance» был диагностируемым.
                        snippet = _sanitize_snippet(response.text)
                        logger.error(
                            "LLM HTTP %d | url=%s | body_auth=%r",
                            status, url, snippet,
                        )
                        raise LLMAuthError(
                            f"LLM auth failed ({status}): {url}"
                            f"{f' | body={snippet}' if snippet else ''}"
                        )
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
                    # Epic 60 (64.7, T-468): фактический лимит — usage из
                    # API-ответа (источник истины для бюджетов/метрик);
                    # парсинг fail-open (нет usage в ответе → нет лога).
                    try:
                        data = response.json()
                    except Exception:
                        data = None
                    if isinstance(data, dict):
                        usage = data.get("usage")
                        if isinstance(usage, dict):
                            logger.info(
                                "LLM usage in=%d out=%d",
                                int(usage.get("prompt_tokens") or 0),
                                int(usage.get("completion_tokens") or 0),
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

    async def _post_fallback(self, payload: dict, path: str = "/chat/completions",
                             model: str | None = None) -> httpx.Response:
        """Epic 53 (62.4): РОВНО одна попытка на фоллбэке, БЕЗ ретраев.

        Тот же payload, model заменён на LLM_FALLBACK_MODEL (или переданную —
        для /embeddings используется primary embed-модель на фоллбэк-базе).
        Ошибки (транспорт/не-2xx) разбирает вызывающий — проброс исходного
        исключения primary.
        """
        client = self._get_fallback_client()
        url = f"{self._fallback_base_url.rstrip('/')}{path}"
        fallback_payload = dict(payload)
        fallback_payload["model"] = model or self._fallback_model
        return await client.post(url, json=fallback_payload)

    async def _fallback_with_retries(self, payload: dict) -> httpx.Response | None:
        """Epic 64: фоллбэк с ретраями транзиентных отказов (429/5xx/транспорт).

        Детерминированные не-200 (400/401/403/404…) НЕ ретраятся. По исчерпании
        попыток логируется СТАРЫЙ формат «LLM fallback failed | error=…»
        (диаг-контракт Betterstack) и возвращается None → вызывающий пробрасывает
        ИСХОДНОЕ исключение primary.
        """
        total_attempts = self._fallback_max_retries + 1
        last_error = "unknown"
        for attempt in range(total_attempts):
            if attempt > 0:
                if self.backoff_base > 0:
                    await asyncio.sleep(
                        min(self.backoff_base * (2 ** (attempt - 1)),
                            self._backoff_cap))
                logger.warning(
                    "LLM fallback retry | attempt=%d/%d | reason=%s",
                    attempt + 1, total_attempts, last_error,
                )
            try:
                async with asyncio.timeout(self._fallback_timeout):
                    fb_resp = await self._post_fallback(payload)
            except Exception as fb_exc:
                last_error = f"{type(fb_exc).__name__}: {fb_exc}"
                continue
            if fb_resp.status_code == 200:
                return fb_resp
            last_error = f"status={fb_resp.status_code}"
            if not (fb_resp.status_code == 429 or 500 <= fb_resp.status_code < 600):
                break
        logger.warning("LLM fallback failed | error=%s", last_error)
        return None

    async def _post_embed_fallback(self, payload: dict) -> httpx.Response:
        """Одна попытка POST {embed_fallback}/embeddings на клиенте
        embed-фоллбэка; model — _embed_fallback_model (пустая при
        конструировании → primary embed-модель)."""
        client = self._get_embed_fallback_client()
        url = f"{self._embed_fallback_base_url.rstrip('/')}/embeddings"
        fallback_payload = dict(payload)
        fallback_payload["model"] = self._embed_fallback_model
        return await client.post(url, json=fallback_payload)

    async def _embed_fallback_with_retries(self,
                                           payload: dict) -> httpx.Response | None:
        """Embed-фоллбэк с ретраями транзиентных отказов
        (429/5xx/транспорт; EMBEDDING_FALLBACK_MAX_RETRIES), общий таймаут
        попытки EMBEDDING_FALLBACK_TIMEOUT_SECONDS (asyncio.timeout).
        Детерминированные не-200 (400/401/403/404…) НЕ ретраятся (break).
        По исчерпании попыток — WARNING «LLM fallback failed | kind=embed |
        error=…» (диаг-контракт Betterstack) и None → вызывающий пробрасывает
        ИСХОДНОЕ исключение primary."""
        total_attempts = self._embed_fallback_max_retries + 1
        last_error = "unknown"
        for attempt in range(total_attempts):
            if attempt > 0:
                if self.backoff_base > 0:
                    await asyncio.sleep(
                        min(self.backoff_base * (2 ** (attempt - 1)),
                            self._backoff_cap))
                logger.warning(
                    "LLM embed fallback retry | attempt=%d/%d | reason=%s",
                    attempt + 1, total_attempts, last_error)
            try:
                async with asyncio.timeout(self._embed_fallback_timeout):
                    fb_resp = await self._post_embed_fallback(payload)
            except Exception as fb_exc:
                last_error = f"{type(fb_exc).__name__}: {fb_exc}"
                continue
            if fb_resp.status_code == 200:
                return fb_resp
            last_error = f"status={fb_resp.status_code}"
            if not (fb_resp.status_code == 429 or 500 <= fb_resp.status_code < 600):
                break
        logger.warning("LLM fallback failed | kind=embed | error=%s", last_error)
        return None

    async def generate(self, messages: list[dict[str, str]],
                       temperature: float | None = None) -> str:
        """POST /chat/completions → choices[0].message.content.

        Epic 60 (65.8, T-476): temperature — опциональный kwarg; None →
        ключ в payload НЕ добавляется (ровно старое поведение для всех
        остальных вызовов; дефолт провайдера).

        Epic 53 (62.4): при LLMError primary (кроме LLMBadResponseError) и
        активном фоллбэке — 1 попытка на фоллбэке; фейл фоллбэка → проброс
        ИСХОДНОГО исключения primary (CB-классификация работает по классу).

        Эпик 04.09.2026 (3.3): контракт {model, messages[, temperature]}
        НЕ меняется — tools уходят ТОЛЬКО новым generate_chat (FR-10).
        """
        payload = {"model": self._chat_model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        try:
            response = await self._post("/chat/completions", payload)
        except LLMError as exc:
            if not self._fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            logger.warning("LLM fallback attempt | primary_error=%s", exc)
            fb_response = await self._fallback_with_retries(payload)
            if fb_response is None:
                raise exc from None
            response = fb_response
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

    async def generate_chat(self, messages, *, temperature: float | None = None,
                            tools: list[dict] | None = None,
                            tool_choice: str | dict = "auto") -> "LLMChatResult":
        """POST /chat/completions с tools/tool_choice (Эпик 04.09.2026, 3.3).

        Контракт {model, messages}: температура — как в generate (None →
        ключа нет); tools/tool_choice добавляются в payload ТОЛЬКО когда
        tools передан. Ретраи/фоллбэк _post/_fallback_with_retries — как в
        generate (payload сквозной). Парсинг: content (может быть None при
        tool_calls) + tool_calls + finish_reason. Легаси generate() НЕ
        меняется (0 регрессий, FR-10/AC-2.1).
        """
        payload = {"model": self._chat_model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        try:
            response = await self._post("/chat/completions", payload)
        except LLMError as exc:
            if not self._fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            logger.warning("LLM fallback attempt | primary_error=%s", exc)
            fb_response = await self._fallback_with_retries(payload)
            if fb_response is None:
                raise exc from None
            response = fb_response
            logger.warning("LLM fallback OK | model=%s", self._fallback_model)
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMBadResponseError("chat/completions: invalid JSON response") from exc
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMBadResponseError(
                "chat/completions: no choices[0] in response"
            ) from exc
        message = choice.get("message") or {}
        content = message.get("content")
        tool_calls = None
        raw_calls = message.get("tool_calls")
        if raw_calls:
            parsed = []
            for call in raw_calls:
                try:
                    function = call.get("function") or {}
                    name = str(function.get("name", "") or "").strip()
                    if not name:
                        logger.warning(
                            "LLM generate_chat: malformed tool_call skipped | model=%s",
                            self._chat_model)
                        continue
                    parsed.append(LLMToolCall(
                        id=str(call.get("id", "")),
                        name=name,
                        arguments=str(function.get("arguments", "") or ""),
                    ))
                except (KeyError, TypeError, AttributeError):
                    logger.warning(
                        "LLM generate_chat: malformed tool_call skipped | model=%s",
                        self._chat_model)
            if parsed:
                tool_calls = parsed
        if content is None and not tool_calls:
            raise LLMBadResponseError("chat/completions: empty content (no tool_calls)")
        logger.info(
            "LLM generate_chat OK | model=%s | out_chars=%s | tool_calls=%d",
            self._chat_model,
            len(str(content)) if content is not None else "-",
            len(tool_calls) if tool_calls else 0,
        )
        content_text = content if (isinstance(content, str) and content.strip()) else None
        return LLMChatResult(
            content=content_text,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """POST /embeddings → data[i].embedding. Raises LLMError on any failure (R3).

        Embed-фоллбэк (EMBEDDING_FALLBACK_*, независим от chat-фоллбэка
        62.4): при LLMError primary (кроме LLMBadResponseError) и активном
        embed-фоллбэке — попытки на {EMBEDDING_FALLBACK_BASE_URL}/embeddings
        с ретраями транзиентных отказов (EMBEDDING_FALLBACK_MAX_RETRIES);
        фейл фоллбэка → проброс ИСХОДНОГО исключения primary (KNN→FTS-каскад
        в summary_memory решает деградацию)."""
        if not texts:
            return []
        try:
            response = await self._post(
                "/embeddings",
                {"model": self._embed_model, "input": texts},
            )
        except LLMError as exc:
            if not self._embed_fallback_active or isinstance(exc, LLMBadResponseError):
                raise
            logger.warning(
                "LLM embed fallback attempt | primary_error=%s",
                f"{type(exc).__name__}: {exc}",
            )
            fb_response = await self._embed_fallback_with_retries(
                {"input": texts})
            if fb_response is None:
                raise exc from None
            response = fb_response
            logger.warning("LLM embed fallback OK | model=%s",
                           self._embed_fallback_model)
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
