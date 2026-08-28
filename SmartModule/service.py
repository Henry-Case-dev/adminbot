"""Epic 67 (D266, Section 71.2) — VoiceTranscriber: контроллер-Стратегия.

Каскад Groq → OpenRouter, порядок = Primary → Fallback. Строго ОДНА попытка
на стратегию (никаких backoff/retry внутри); таймаут per-стратегии через
asyncio.wait_for поверх клиента. Ошибка/таймаут стратегии → сразу следующая.
Все легли → TranscriptionUnavailable; все ответили пусто (strip()=='') →
EmptyTranscript. Выбор фраз — хендлер (прецедент YoutubeSummarizerService).

Epic 79.5 (D295): добавлена очередь (asyncio.Semaphore) и per-strategy
rate limiter для защиты от Groq 429. Free Tier: 30 RPM (1 req/2s), whisper
20 RPM — MAX_CONCURRENCY=1, MIN_INTERVAL=2.0 по умолчанию.
"""
import asyncio
import logging
import time
from pathlib import Path

from SmartModule.transcriber import GroqTranscriber, OpenRouterTranscriber

logger = logging.getLogger(__name__)


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

    async def transcribe_voice(self, file_path: str, audio_format: str = "ogg") -> str:
        """file_path → расшифровка. audio_format ('ogg'/'mp4') — подсказка о
        модальности для стратегий, читающих формат из расширения файла.

        Epic 79.5 (D295): семафор гарантирует, что только max_concurrency
        запросов одновременно достигнут стратегиям.
        """
        async with self._semaphore:
            saw_failure = False
            for strategy in self._strategies:
                if not strategy.available:
                    logger.warning("[transcribe] %s skipped (no API key)", strategy.name)
                    continue
                try:
                    # СТРОГО 1 попытка каждый (без ретраев), wait_for — единая точка контроля.
                    text = await asyncio.wait_for(
                        strategy.transcribe(file_path), timeout=strategy.timeout)
                except asyncio.TimeoutError:
                    saw_failure = True
                    logger.warning("[transcribe] %s timeout (%ss)",
                                   strategy.name, strategy.timeout)
                except Exception as exc:
                    saw_failure = True
                    logger.warning("[transcribe] %s failed (%s)", strategy.name, exc)
                else:
                    stripped = (text or "").strip()
                    if stripped:
                        return stripped
            if saw_failure:
                raise TranscriptionUnavailable(file_path)
            raise EmptyTranscript(file_path)
