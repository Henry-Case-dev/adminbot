"""Эпик 04.09.2026 (3.2) — мультимодальный видео-клиент OpenRouter (video_url).

Клиент каскада «перескажи видос»: L1 (models.video_primary_model) → L2
(models.video_fallback_model) → L3 (субтитры, старый путь). Этот модуль —
ТОЛЬКО мультимодальный запрос на уровне одного видео.

Образец: SmartModule/transcriber/openrouter_transcriber.py — AsyncOpenAI,
base_url https://openrouter.ai/api/v1, ключ — горячая точка
keys.openrouter_api_key с фолбеком на settings, ленивая пересборка клиента
при смене ключа ИЛИ models.video_timeout_seconds (W1: hot-изменение
таймаута подхватывается без рестарта), R17-логика (тело ответа провайдера
НЕ логируется).

Политика ретрая уровня (FR-6/AC-1.4): 1 стартовая попытка + 1 повтор ТОЛЬКО
на транзиентное (HTTP 429/5xx/транспорт, backoff 2с); 400/401/402/403/404/
415/422 и прочие не-2xx — мгновенный VideoLevelError('status=…'); пустой/
None content — VideoLevelError('empty content'). Все исключения уровней
наружу не пробрасываются — их классифицирует каскад (youtube_summarizer_service).
"""
import asyncio
import logging
import time

from openai import AsyncOpenAI

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Backoff перед единственным повтором уровня (FR-6): фиксированные 2с.
_LEVEL_RETRY_BACKOFF = 2.0

# Транзиентные статусы для повтора уровня (429/5xx; остальное — сразу вниз).
_TRANSIENT_429 = 429


class VideoLevelError(Exception):
    """Один уровень каскада упал (обёртка: HTTP-статус/класс исключения).

    reason: str — 'status=429' | 'timeout' | 'transport: ReadTimeout'
    | 'empty content' | ...
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class OpenRouterVideoClient:
    """Мультимодальный клиент OpenRouter на видео (content: video_url)."""

    name = "openrouter_video"

    def __init__(self, api_key: str | None = None) -> None:
        # T-619 (84.4): ключ — горячая точка на КАЖДЫЙ вызов (фолбек settings);
        # models.video_timeout_seconds — тоже hot: AsyncOpenAI собирается с
        # фиксированным timeout, поэтому клиент пересобирается при изменении
        # ключа ИЛИ таймаута (W1).
        self._default_key = settings.OPENROUTER_API_KEY if api_key is None else api_key
        self._client: AsyncOpenAI | None = None
        self._client_key: str | None = None
        self._client_timeout: float | None = None

    @property
    def _current_api_key(self) -> str:
        return hot.get("keys.openrouter_api_key", self._default_key) or ""

    @property
    def _current_timeout(self) -> float:
        return hot.get("models.video_timeout_seconds",
                       settings.VIDEO_TIMEOUT_SECONDS)

    def _get_client(self) -> AsyncOpenAI | None:
        """Ленивая пересборка при смене ключа ИЛИ таймаута (hot-reload,
        T-619 + W1-фикс: models.video_timeout_seconds читается на каждый
        вызов, а не фиксируется при сборке клиента)."""
        key = self._current_api_key
        if not key:
            self._client = None
            self._client_key = None
            self._client_timeout = None
            return None
        timeout = self._current_timeout
        if (self._client is None or key != self._client_key
                or timeout != self._client_timeout):
            self._client = AsyncOpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=key,
                timeout=timeout,
            )
            self._client_key = key
            self._client_timeout = timeout
        return self._client

    @property
    def available(self) -> bool:
        """Пустой keys.openrouter_api_key → мультимодальный уровень выключен
        (каскад сразу уходит на субтитры, прецедент D104)."""
        return bool(self._current_api_key)

    @staticmethod
    def _retryable_status(status: int | None) -> bool:
        return status is not None and (status == _TRANSIENT_429 or 500 <= status < 600)

    @staticmethod
    def _classify_exception(exc: Exception) -> str:
        """Причина уровня по исключению OpenAI-SDK/httpx (R17: тело НЕ логируется)."""
        status = getattr(exc, "status_code", None)
        if status is not None:
            return f"status={status}"
        return f"transport: {type(exc).__name__}"

    async def summarize(self, *, model: str, video_url: str,
                        system_prompt: str, user_text: str,
                        timeout: float) -> str:
        """→ текст выжимки. Пустой/None content → VideoLevelError('empty content').
        Ретрай уровня (≤1 повтор) — только транзиентное (429/5xx/транспорт,
        backoff 2с); таймаут уровня/детерминированные не-2xx — мгновенно вниз."""
        client = self._get_client()
        if client is None:
            raise VideoLevelError("no openrouter key")
        started = time.monotonic()
        for attempt in range(1, 3):            # 1 стартовая + 1 повтор (FR-6)
            try:
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": [
                                {"type": "text", "text": user_text},
                                {"type": "video_url", "video_url": {"url": video_url}},
                            ]},
                        ],
                    ),
                    timeout=timeout,
                )
                content = (response.choices[0].message.content
                           if response.choices else None)
                if not content or not str(content).strip():
                    raise VideoLevelError("empty content")
                logger.info(
                    "[video cascade] client OK | model=%s | out_chars=%d | "
                    "latency_ms=%.0f",
                    model, len(str(content)),
                    (time.monotonic() - started) * 1000.0,
                )
                return str(content)
            except VideoLevelError as exc:
                if exc.reason == "empty content":
                    raise                 # повтор бессмыслен (AC-1.4)
                reason, retryable = exc.reason, False
            except asyncio.TimeoutError:
                reason, retryable = "timeout", False
            except Exception as exc:      # HTTP/транспорт OpenAI-SDK/httpx
                reason = self._classify_exception(exc)
                status = getattr(exc, "status_code", None)
                retryable = self._retryable_status(status) or self._transport_error(exc)
            if retryable and attempt == 1:
                logger.warning(
                    "[video cascade] level retry 1 | model=%s | reason=%s",
                    model, reason,
                )
                await asyncio.sleep(_LEVEL_RETRY_BACKOFF)
                continue
            raise VideoLevelError(reason)

    @staticmethod
    def _transport_error(exc: Exception) -> bool:
        """Транспортный класс (httpx/OpenAI-SDK): connect/read/write/…-ошибки."""
        name = type(exc).__name__.lower()
        if any(marker in name for marker in ("connection", "timeout", "transport",
                                             "network", "read", "write", "pool",
                                             "protocol")):
            return True
        try:
            import httpx
            if isinstance(exc, httpx.TransportError):
                return True
        except Exception:  # pragma: no cover — httpx всегда доступен
            pass
        return False
