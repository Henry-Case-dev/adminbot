"""Epic 67 (D266, Section 71.2) — VoiceTranscriber: контроллер-Стратегия.

Каскад Groq → OpenRouter, порядок = Primary → Fallback. Строго ОДНА попытка
на стратегию (никаких backoff/retry внутри); таймаут per-стратегии через
asyncio.wait_for поверх клиента. Ошибка/таймаут стратегии → сразу следующая.
Все легли → TranscriptionUnavailable; все ответили пусто (strip()=='') →
EmptyTranscript. Выбор фраз — хендлер (прецедент YoutubeSummarizerService).

Epic 79.5 (D295): добавлена очередь (asyncio.Semaphore) и per-strategy
rate limiter для защиты от Groq 429. Free Tier: 30 RPM (1 req/2s), whisper
20 RPM — MAX_CONCURRENCY=1, MIN_INTERVAL=2.0 по умолчанию.

Раунд 3 (T-692): (а) timeout параметризуем per-запрос — видео-вызовы
передают limits.video_stt_timeout_seconds (дефолт 120), голосовые — прежний
путь (timeout=None → strategy.timeout 10/15); (б) размерные гейты
провайдеров (strategy.max_upload_mb: > гейта → стратегия skipped с логом;
обе skipped → TranscriptionUnavailable); (в) ОДИН повтор стратегии на
транзиентные таймауты/5xx/транспорт (backoff 2с — прецедент
video_cascade_client._LEVEL_RETRY_BACKOFF).
"""
import asyncio
import logging
import os
import time
from pathlib import Path

from SmartModule.transcriber import GroqTranscriber, OpenRouterTranscriber

logger = logging.getLogger(__name__)

# Раунд 3 (T-692): backoff перед единственным повтором стратегии (FR-B10).
_TRANSCRIBE_RETRY_BACKOFF = 2.0

# Имена классов SDK/httpx с транзиентной природой (для повтора стратегии).
_TRANSIENT_NAME_MARKERS = ("connection", "timeout", "transport", "network",
                           "read", "write", "pool", "protocol")


class TranscriptionError(Exception):
    """База ошибок транскрипции (фразы выбирает хендлер)."""


class TranscriptionUnavailable(TranscriptionError):
    """Все стратегии упали (API-ошибка или таймаут) → пул VT_ALL_FAILED_PHRASES."""

    def __init__(self, file_path: str):
        # R17: логируем только имя файла (tempfile prefix `vt_`), не путь.
        safe_name = Path(file_path).name
        super().__init__(safe_name)


class EmptyTranscript(TranscriptionError):
    """Сервисы ответили без ошибок, но текст пуст (strip()=='') → VT_SILENCE_PHRASES."""

    def __init__(self, file_path: str):
        # R17: логируем только имя файла (tempfile prefix `vt_`), не путь.
        safe_name = Path(file_path).name
        super().__init__(safe_name)


class VoiceTranscriber:
    """Контроллер каскада транскрибаторов.

    Epic 79.5 (D295): использует asyncio.Semaphore для ограничения
    конкуренции за LLM API. По умолчанию MAX_CONCURRENCY=1 (строго
    последовательно — типично для Free Tier с 30 RPM).
    """

    def __init__(self, strategies=None, max_concurrency: int = 1) -> None:
        self._strategies = tuple(
            strategies if strategies is not None
            else (GroqTranscriber(), OpenRouterTranscriber())
        )
        # Epic 79.5 (D295): очередь для сериализации конкурентных запросов.
        # MAX_CONCURRENCY=1 → один запрос к LLM за раз (Free Tier безопасен).
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def transcribe_voice(self, file_path: str, audio_format: str = "ogg", *,
                               timeout: float | None = None) -> str:
        """file_path → расшифровка. audio_format ('ogg'/'mp4') — подсказка о
        модальности для стратегий, читающих формат из расширения файла.

        Раунд 3 (T-692, FR-B10): timeout — per-запрос таймаут ОДНОЙ стратегии
        (видео-ветки передают limits.video_stt_timeout_seconds=120; голосовые
        — None → strategy.timeout как раньше). Файл больше гейта стратегии
        (max_upload_mb) → стратегия skipped с логом; обе skipped →
        TranscriptionUnavailable (файл не пуст — EmptyTranscript не подходит).
        Один повтор стратегии на транзиентные (таймаут/5xx/транспорт),
        backoff _TRANSCRIBE_RETRY_BACKOFF.

        Epic 79.5 (D295): семафор гарантирует, что только max_concurrency
        запросов одновременно достигнут стратегиям.
        """
        async with self._semaphore:
            saw_failure = False
            saw_skip = False
            for strategy in self._strategies:
                if not strategy.available:
                    logger.warning("[transcribe] %s skipped (no API key)",
                                   strategy.name)
                    continue
                effective = float(timeout) if timeout is not None \
                    else float(strategy.timeout)
                max_mb = float(getattr(strategy, "max_upload_mb", None) or 0)
                if max_mb > 0:
                    size_mb = _file_size_mb(file_path)
                    if size_mb > max_mb:
                        logger.warning(
                            "[transcribe] %s skipped (file %d MB > limit %d MB)",
                            strategy.name, int(size_mb), int(max_mb))
                        saw_skip = True
                        continue
                for attempt in (1, 2):        # 1 стартовая + 1 повтор (FR-B10)
                    try:
                        text = await asyncio.wait_for(
                            strategy.transcribe(file_path, timeout=effective),
                            timeout=effective)
                    except asyncio.TimeoutError:
                        saw_failure = True
                        if attempt == 1:
                            logger.warning(
                                "[transcribe] %s timeout (%.0fs) → retry once",
                                strategy.name, effective)
                            await asyncio.sleep(_TRANSCRIBE_RETRY_BACKOFF)
                            continue
                        logger.warning(
                            "[transcribe] %s timeout (%.0fs) after retry",
                            strategy.name, effective)
                        break                 # следующая стратегия
                    except Exception as exc:
                        saw_failure = True
                        if attempt == 1 and _is_transient_strategy_error(exc):
                            logger.warning(
                                "[transcribe] %s transient (%s) → retry once",
                                strategy.name, type(exc).__name__)
                            await asyncio.sleep(_TRANSCRIBE_RETRY_BACKOFF)
                            continue
                        logger.warning("[transcribe] %s failed (%s)",
                                       strategy.name, exc)
                        break                 # следующая стратегия
                    else:
                        stripped = (text or "").strip()
                        if stripped:
                            return stripped
                        break                 # пустой ответ: без повтора
            if saw_failure or saw_skip:
                raise TranscriptionUnavailable(file_path)
            raise EmptyTranscript(file_path)


def _file_size_mb(file_path: str) -> float:
    try:
        return os.path.getsize(file_path) / (1024.0 * 1024.0)
    except OSError:
        logger.warning("[transcribe] stat failed | file=%s",
                       Path(file_path).name, exc_info=True)
        return 0.0


def _is_transient_strategy_error(exc: Exception) -> bool:
    """Транзиентный класс ошибки стратегии (таймаут/5xx/транспорт) — повторить.
    4xx (в т.ч. 400/403 роутера) НЕ транзиентны — их уже ретраит сама стратегия
    (OpenRouter 3 попытки, Groq 429-политика)."""
    status = getattr(exc, "status_code", None)
    if status is not None and 500 <= int(status) < 600:
        return True
    name = type(exc).__name__.lower()
    if any(marker in name for marker in _TRANSIENT_NAME_MARKERS):
        return True
    try:
        import httpx
        if isinstance(exc, httpx.TransportError):
            return True
    except Exception:  # pragma: no cover — httpx всегда доступен
        pass
    return False
