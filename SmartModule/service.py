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

from config.settings import settings
from SmartModule.transcriber import GroqTranscriber, OpenRouterTranscriber
from SmartModule.transcriber.audio_prep import extract_audio_for_stt

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

        Хотфикс-3 (T-2495, ADR-1025-7 D3): ДО размерного гейта файл > лимитов
        провайдеров сжимается (ogg/opus mono 16 kHz), при необходимости —
        чанкинг; покрывает И видео, И ГС/кружки (единая точка). Kill-switch
        ``STT_AUDIO_COMPRESS_ENABLED`` (env-only, default ON); OFF → прежний
        размерный гейт байт-в-байт.

        Review fix M-1: подготовка (ffmpeg) выполняется ДО входа в семафор —
        слот STT не держится на время сжатия/чанкинга.
        Review fix (partial): при чанкинге сбой одной части не теряет уже
        расшифрованные — склеиваем частичный результат (`reason=partial`).

        Epic 79.5 (D295): семафор гарантирует, что только max_concurrency
        запросов одновременно достигнут стратегиям.
        """
        # M-1: тяжёлая prep (ffmpeg, до ~300с) — ВНЕ семафора STT.
        prep = await self._prepare_for_stt(file_path)
        sources = (list(prep.paths) if prep is not None and prep.paths
                   else [file_path])
        try:
            async with self._semaphore:
                parts: list[str] = []
                failures = 0
                for index, src in enumerate(sources):
                    try:
                        text = await self._transcribe_one(
                            src, audio_format, timeout)
                    except TranscriptionUnavailable:
                        failures += 1
                        logger.warning(
                            "[transcribe] chunk failed | index=%d/%d",
                            index + 1, len(sources))
                        continue
                    if text:
                        parts.append(text)
                joined = " ".join(parts).strip()
                if joined:
                    if failures:
                        # Частичный успех: отдаём то, что расшифровали
                        # (не теряем результат удачных частей).
                        logger.info(
                            "[transcribe] partial transcript | reason=partial "
                            "| ok=%d | failed=%d | total=%d",
                            len(parts), failures, len(sources))
                    return joined
                if failures:
                    raise TranscriptionUnavailable(file_path)
                raise EmptyTranscript(file_path)
        finally:
            if prep is not None:
                prep.cleanup()

    async def _prepare_for_stt(self, file_path: str):
        """Сжатие/чанкинг до гейтов (T-2494/T-2495). ``None`` — без подготовки.

        Сжатие нужно только когда файл НЕ влезает ни в одну доступную стратегию
        (``size_mb > max(limits)``) — иначе гейт-цикл сам выберет подходящую
        стратегию (review fix L-2). Нет ffmpeg или сбой сжатия → ``None`` →
        прежний честный размерный гейт (не тихий провал). Никогда не бросает."""
        if not bool(getattr(settings, "STT_AUDIO_COMPRESS_ENABLED", True)):
            return None                       # OFF → байт-в-байт прежний гейт
        target_mb = self._compress_target_mb(file_path)
        if not target_mb or target_mb <= 0:
            return None
        try:
            prep = await extract_audio_for_stt(file_path, target_mb)
        except Exception:                     # pragma: no cover - defensive
            logger.warning("[transcribe] audio prep failed — original used | "
                           "file=%s", Path(file_path).name, exc_info=True)
            return None
        if not prep.paths:
            logger.info("[transcribe] audio prep unavailable | reason=%s | "
                        "orig_mb=%.1f", prep.reason, prep.orig_mb)
            return None
        if prep.reason != "unchanged":
            logger.info(
                "[transcribe] audio prep | reason=%s | orig_mb=%.1f | "
                "result_mb=%.1f | parts=%d", prep.reason, prep.orig_mb,
                prep.result_mb, len(prep.paths))
        return prep

    def _compress_target_mb(self, file_path: str) -> float | None:
        """Целевой размер (МБ) для сжатия. ``None`` — сжатие не нужно.

        Review fix L-2: сжимаем ТОЛЬКО если файл не влезает ни в одну
        доступную стратегию (``size_mb > max(limits)``) — файл 20–25 МБ,
        влезающий в более мягкий гейт (напр. Groq 25), не пересжимается.
        Цель — самый строгий гейт ``min(limits)``, чтобы сработали все
        стратегии. Есть стратегия без гейта / файл в пределах — ``None``."""
        limits: list[float] = []
        for strategy in self._strategies:
            if not getattr(strategy, "available", False):
                continue
            try:
                limit = float(getattr(strategy, "max_upload_mb", 0) or 0)
            except (TypeError, ValueError):    # pragma: no cover - defensive
                limit = 0.0
            if limit <= 0:
                return None                    # есть стратегия без гейта
            limits.append(limit)
        if not limits:
            return None
        size_mb = _file_size_mb(file_path)
        if size_mb <= 0 or size_mb <= max(limits):
            return None
        return min(limits)

    async def _transcribe_one(self, file_path: str, audio_format: str,
                              timeout: float | None) -> str:
        """Каскад стратегий по ОДНОМУ файлу. Пустая расшифровка → ``""``;
        все стратегии упали/скипнуты → ``TranscriptionUnavailable``.

        Вызывается под уже взятым семафором (``transcribe_voice``)."""
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
        return ""


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
