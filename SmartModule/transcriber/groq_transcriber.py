"""Epic 67 (D266, Section 71.2) — Groq whisper-large-v3 через OpenAI-SDK.

Epic 79.5 (D295): retry с экспоненциальным backoff + honor Retry-After header.
Groq Free Tier: 30 RPM (1 req/2s), whisper 20 RPM → MIN_INTERVAL=2.0s default.
429 → honor Retry-After (секунды) → fallback к экспоненциальному backoff.
"""
import asyncio
import logging
import time

from openai import AsyncOpenAI

from config.settings import settings
from SmartModule.transcriber.base import BaseTranscriber

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_TRANSCRIBE_MODEL = "whisper-large-v3"


class GroqTranscriber(BaseTranscriber):
    """Primary-стратегия: audio.transcriptions.create (OpenAI-compatible).

    Epic 79.5 (D295): встроенный retry на 429 с backoff.
    """

    name = "groq"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = settings.GROQ_API_KEY if api_key is None else api_key
        self.timeout = settings.GROQ_TIMEOUT
        self._max_retries = settings.GROQ_MAX_RETRIES
        self._min_interval = settings.GROQ_MIN_INTERVAL
        self._last_request_time: float = 0.0
        # AsyncOpenAI(api_key="") кидает OpenAIError — клиент строим только
        # при наличии ключа; пустой ключ = стратегия недоступна.
        self._client: AsyncOpenAI | None = (
            AsyncOpenAI(
                base_url=GROQ_BASE_URL,
                api_key=self._api_key,
                timeout=self.timeout,
            )
            if self._api_key
            else None
        )

    @property
    def available(self) -> bool:
        return bool(self._client)

    @staticmethod
    def _retry_after_seconds(exc) -> float | None:
        """Извлекает retry-after из ответа Groq (429). R17: не логируем токен."""
        resp = getattr(exc, "response", None)
        if resp is None:
            return None
        # OpenAI SDK: resp.headers (urllib-style mapping)
        headers = getattr(resp, "headers", None) or {}
        val = headers.get("retry-after") or headers.get("x-ratelimit-reset-requests")
        if val is None:
            return None
        try:
            # Формат может быть: секунды ("2") или время ("2m59.56s")
            s = str(val).strip()
            if "s" in s:
                parts = s.replace("m", ":").replace("s", "").split(":")
                if len(parts) == 2:
                    return float(parts[0]) * 60 + float(parts[1])
            return float(s)
        except (ValueError, TypeError):
            return None

    async def _sleep_with_interval(self) -> None:
        """Epic 79.5 (D295): минимальный интервал между запросами к Groq."""
        elapsed = time.monotonic() - self._last_request_time
        wait = max(0.0, self._min_interval - elapsed)
        if wait > 0:
            await asyncio.sleep(wait)

    async def transcribe(self, file_path: str) -> str:
        """С retry на 429 (exponential backoff + honor Retry-After).

        R17: API ключ никогда не логируется. Ошибки логируются как тип
        исключения + retry-after (если есть), без URL или тела ответа.
        """
        if self._client is None:
            raise RuntimeError("GroqTranscriber: GROQ_API_KEY is not configured")

        attempts = 0
        while True:
            attempts += 1
            await self._sleep_with_interval()
            self._last_request_time = time.monotonic()
            try:
                with open(file_path, "rb") as fh:
                    response = await self._client.audio.transcriptions.create(
                        model=GROQ_TRANSCRIBE_MODEL, file=fh)
                return getattr(response, "text", "") or ""
            except Exception as exc:
                # 429 Too Many Requests → honor Retry-After или экспоненциальный backoff
                is_429 = _is_rate_limit_error(exc)
                if is_429 or _is_client_error(exc):
                    if attempts < self._max_retries:
                        retry_after = self._retry_after_seconds(exc)
                        if retry_after is None:
                            # Экспоненциальный backoff: 2s → 4s → 8s
                            backoff = 2.0 * (2 ** (attempts - 1))
                        else:
                            backoff = max(retry_after, self._min_interval)
                        logger.warning(
                            "[transcribe] groq retry %d/%d | backoff=%.1fs | %s",
                            attempts, self._max_retries, backoff,
                            type(exc).__name__)
                        await asyncio.sleep(backoff)
                        continue
                    logger.warning(
                        "[transcribe] groq exhausted retries (%d) | %s",
                        attempts, type(exc).__name__)
                raise


def _is_rate_limit_error(exc: Exception) -> bool:
    """Проверяет, является ли ошибка 429 Too Many Requests."""
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if status == 429:
        return True
    # OpenAI SDK: можно также проверить тип ошибки в теле
    err = getattr(exc, "body", None) or {}
    err_obj = err.get("error", {}) if isinstance(err, dict) else None
    if err_obj and err_obj.get("type") == "insufficient_quota":
        return True
    return False


def _is_client_error(exc: Exception) -> bool:
    """Проверяет, является ли ошибка клиентской (4xx, не 429).

    4xx-ошибки (400/401/403/404) — retry бессмысленен (не rate limit).
    Возвращаем True ТОЛЬКО для ошибок, которые могут быть временными
    в контексте rate limiting (например, транзиентные 4xx от Groq).
    """
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if status and 400 <= status < 500 and status != 429:
        # 401/403 — конфигурационные ошибки, retry не поможет
        # 400/404 — ошибки запроса, retry не поможет
        return False
    return False
