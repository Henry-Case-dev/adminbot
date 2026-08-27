"""Epic 67 (D266, Section 71.2) — VoiceTranscriber: контроллер-Стратегия.

Каскад Groq → OpenRouter, порядок = Primary → Fallback. Строго ОДНА попытка
на стратегию (никаких backoff/retry внутри); таймаут per-стратегии через
asyncio.wait_for поверх клиента. Ошибка/таймаут стратегии → сразу следующая.
Все легли → TranscriptionUnavailable; все ответили пусто (strip()=='') →
EmptyTranscript. Выбор фраз — хендлер (прецедент YoutubeSummarizerService).
"""
import asyncio
import logging
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
    """Контроллер каскада транскрибаторов."""

    def __init__(self, strategies=None) -> None:
        self._strategies = tuple(
            strategies if strategies is not None
            else (GroqTranscriber(), OpenRouterTranscriber())
        )

    async def transcribe_voice(self, file_path: str, audio_format: str = "ogg") -> str:
        """file_path → расшифровка. audio_format ('ogg'/'mp4') — подсказка о
        модальности для стратегий, читающих формат из расширения файла."""
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
