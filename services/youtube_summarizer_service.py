"""Epic 37/46 — YoutubeSummarizerService (R37-7, D130, Sections 46.8/55.5).

Пайплайн (прецедент FactCheckService 42.6): движок транскрипта →
YOUTUBE_SYSTEM_PROMPT ({max_symbols} через .replace) → XML-контекст
<video_id>/<transcript> → LLMClient.generate → cleanup_llm_text (R37-7, ВСЕГДА,
ВНУТРИ сервиса, ДО чанкинга). Ошибки движка/LLM пробрасываются в хендлер —
фразы выбирает хендлер.

Epic 46 (55.5): после fetch_transcript — fire_and_forget-хук _memorize_youtube
(≤8000 симв. → сырые субтитры; иначе — нетоксичная LLM-выжимка ВНУТРИ фоновой
задачи) + гибридный RAG (get_rag_context по rag_query) префиксом user-контента.
memory=None / chat_id=None / rag_query пуст → ровно старое поведение.

Эпик 04.09.2026 (3.2, Часть 1): summarize_cascade — оркестратор каскада
L1 (video_primary_model) → L2 (video_fallback_model) → L3 (summarize —
субтитры). Каскад молча деградирует: любой сбой L1/L2 (VideoLevelError/
таймаут/пустой ответ) → WARNING + следующий уровень; исключения уровней
наружу не пробрасываются. video_client=None (или недоступен ключ) → ровно
старое поведение (сразу L3).
"""
import asyncio
import logging
import time
from typing import Awaitable, Callable

from config.settings import settings
from services import hot_config as hot
from services.llm_client import LLMBadResponseError, LLMClient
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, _memorize_youtube, fire_and_forget
from services.summary_xml import escape_xml_text
from services.video_cascade_client import OpenRouterVideoClient, VideoLevelError
from services.youtube_prompts import (
    YOUTUBE_SYSTEM_PROMPT,
    YOUTUBE_VIDEO_SYSTEM_PROMPT,
)
from services.youtube_transcript_engine import YouTubeTranscriptEngine

logger = logging.getLogger(__name__)


def _canonical_youtube_url(video_id: str) -> str:
    """Canonical-форма URL для OpenRouter (видео передаётся URL-ом, не файлом)."""
    return f"https://www.youtube.com/watch?v={video_id}"


class YoutubeSummarizerService:
    """YouTube: субтитры → LLM-выжимка в токсичном стиле → cleanup."""

    def __init__(self, engine: YouTubeTranscriptEngine, llm: LLMClient,
                 memory: MemoryManager | None = None,
                 video_client: OpenRouterVideoClient | None = None) -> None:
        self.engine = engine
        self.llm = llm
        self.memory = memory
        self.video_client = video_client

    async def summarize_cascade(
        self,
        video_id: str,
        on_retry: Callable[[int, int], Awaitable[None]] | None = None,
        chat_id: int | None = None,
        rag_query: str | None = None,
    ) -> str:
        """L1 (primary) → L2 (fallback) → L3 (субтитры). Всегда возвращает текст.

        Мультимодальный путь пропускается целиком, если видео-клиент не задан
        или недоступен (пустой keys.openrouter_api_key) — WARNING + L3.
        Успех L1/L2 возвращается без сообщений юзеру об уровнях (кэширует
        хендлер). Ошибки/пустые ответы L1/L2 молча уводят на следующий уровень.
        """
        max_symbols = hot.get("limits.youtube_max_symbols",
                              settings.YOUTUBE_MAX_SYMBOLS)
        timeout = hot.get("models.video_timeout_seconds",
                          settings.VIDEO_TIMEOUT_SECONDS)
        if self.video_client is None or not self.video_client.available:
            logger.warning(
                "[video cascade] disabled (no openrouter key) — subtitles path "
                "| video_id=%r", video_id)
            return await self.summarize(video_id, on_retry=on_retry,
                                        chat_id=chat_id, rag_query=rag_query)
        rag = ""
        if self.memory is not None and chat_id is not None and rag_query:
            try:
                rag = await self.memory.get_rag_context(chat_id, rag_query)
            except Exception:
                logger.warning(
                    "[video cascade] rag build failed — fail-open | video_id=%r",
                    video_id, exc_info=True)
        video_system = hot.get("prompts.youtube_video_system_prompt",
                               YOUTUBE_VIDEO_SYSTEM_PROMPT)
        system = video_system.replace("{max_symbols}", str(max_symbols))
        user = ((f"{rag}\n\n" if rag else "") +
                f"<video_id>{video_id}</video_id>\n\n"
                f"Смотри видео и сделай выжимку по правилам.")
        video_url = _canonical_youtube_url(video_id)
        for level, key, settings_attr in (
                ("L1", "models.video_primary_model", settings.VIDEO_PRIMARY_MODEL),
                ("L2", "models.video_fallback_model", settings.VIDEO_FALLBACK_MODEL),
        ):
            model = str(hot.get(key, settings_attr) or "").strip()
            if not model:                             # пусто = ступень отключена
                logger.warning(
                    "[video cascade] %s skipped (empty model) | video_id=%r",
                    level, video_id)
                continue
            started = time.monotonic()
            try:
                raw = await asyncio.wait_for(
                    self.video_client.summarize(
                        model=model, video_url=video_url,
                        system_prompt=system, user_text=user, timeout=timeout),
                    timeout=timeout)
            except VideoLevelError as exc:
                logger.warning(
                    "[video cascade] %s failed → next | model=%s video_id=%r "
                    "| reason=%s", level, model, video_id, exc)
                continue
            except asyncio.TimeoutError:
                logger.warning(
                    "[video cascade] %s timeout (%.0fs) → next | model=%s "
                    "video_id=%r", level, timeout, model, video_id)
                continue
            text = cleanup_llm_text(raw)
            if not text.strip():
                logger.warning(
                    "[video cascade] %s empty answer → next | model=%s video_id=%r",
                    level, model, video_id)
                continue
            logger.info(                                # R41-5
                "[video cascade] OK | level=%s model=%s video_id=%r "
                "out_chars=%d latency_ms=%.0f",
                level, model, video_id, len(text),
                (time.monotonic() - started) * 1000.0)
            return text                                # успех L1/L2 — кэш хендлера
        logger.warning(
            "[video cascade] L1+L2 unavailable → subtitles (L3) | video_id=%r",
            video_id)
        return await self.summarize(video_id, on_retry=on_retry,
                                    chat_id=chat_id, rag_query=rag_query)

    async def summarize(
        self,
        video_id: str,
        on_retry: Callable[[int, int], Awaitable[None]] | None = None,
        chat_id: int | None = None,
        rag_query: str | None = None,
    ) -> str:
        """R41-2/D156: on_retry пробрасывается в движок как есть
        (None — ретраи без уведомлений). Остальной пайплайн — 46.8/55.5."""
        # T-619: лимит и промпт — горячие точки (фолбек settings)
        max_symbols = hot.get("limits.youtube_max_symbols",
                              settings.YOUTUBE_MAX_SYMBOLS)
        system_prompt = hot.get("prompts.youtube_system_prompt",
                                YOUTUBE_SYSTEM_PROMPT)
        transcript = await self.engine.fetch_transcript(
            video_id, max_symbols, on_retry=on_retry
        )
        if self.memory is not None and chat_id is not None:
            fire_and_forget(
                _memorize_youtube(self.memory, chat_id, transcript), "youtube")
        rag = await self.memory.get_rag_context(chat_id, rag_query) if (
            self.memory and chat_id is not None and rag_query) else ""
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        user = (f"{rag}\n\n" if rag else "") + (
            f"<video_id>{video_id}</video_id>\n\n"
            f"<transcript>{escape_xml_text(transcript)}</transcript>"
        )
        started = time.monotonic()
        raw = await self.llm.generate(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        logger.info(
            "youtube summarizer LLM OK | out_chars=%d | latency_ms=%.0f",
            len(raw), (time.monotonic() - started) * 1000.0,
        )
        raw = cleanup_llm_text(raw)
        if not raw.strip():
            # Epic 60 (65.1, T-469): пустой ответ → молчание + 🗿 (хендлер).
            raise LLMBadResponseError("youtube summarizer: empty answer")
        return raw

    async def summarize_transcript(self, *, chat_id: int,
                                   transcript: str) -> str:
        """Bugfix 04.09.2026 (Часть 1, FR-6): выжимка по расшифровке
        ЛОКАЛЬНОГО видео-файла (нативные TG-видео). Канон — тот же
        prompts.youtube_system_prompt (текстовая расшифровка). Возвращает
        cleanup-текст; пустой ответ → LLMBadResponseError (хендлер молчит+🗿).

        Раунд 3 (FR-B9/T-691): «честная выжимка» — RAG-подмес из user-контента
        УБРАН полностью (источник «о чём видео» — только сам транскрипт;
        поведение 02:45 «ответ про память» исключено). chat_id сохранён в
        сигнатуре (совместимость вызовов)."""
        max_symbols = hot.get("limits.youtube_max_symbols",
                              settings.YOUTUBE_MAX_SYMBOLS)
        system_prompt = hot.get("prompts.youtube_system_prompt",
                                YOUTUBE_SYSTEM_PROMPT)
        capped = str(transcript or "")[:max_symbols]   # прецедент: движок режет
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        user = ("<video_id>tg-file</video_id>\n\n"
                f"<transcript>{escape_xml_text(capped)}</transcript>")
        started = time.monotonic()
        raw = await self.llm.generate([
            {"role": "system", "content": system},
            {"role": "user", "content": user}])
        logger.info(
            "youtube file-summary LLM OK | in_chars=%d out_chars=%d | "
            "latency_ms=%.0f", len(capped), len(raw),
            (time.monotonic() - started) * 1000.0,
        )
        raw = cleanup_llm_text(raw)
        if not raw.strip():
            raise LLMBadResponseError("youtube file summary: empty answer")
        return raw

    async def summarize_media_url(self, *, chat_id: int, video_url: str,
                                  label: str = "tg-file") -> str:
        """Раунд 3 (3.2.1, T-689): L1→L2 мультимодального каскада по
        ПРОИЗВОЛЬНОМУ video_url (опубликованный файл / прямая ссылка).
        Субтитров (L3) нет — провал обеих моделей = VideoLevelError наружу
        (хендлер делает STT-фолбек). RAG-контекст НЕ подмешивается (B5:
        честная выжимка — только по реальному контенту видео).
        Логи: R17 — URL/подпись не логируются, только label-хвост."""
        max_symbols = hot.get("limits.youtube_max_symbols",
                              settings.YOUTUBE_MAX_SYMBOLS)
        timeout = hot.get("models.video_timeout_seconds",
                          settings.VIDEO_TIMEOUT_SECONDS)
        if self.video_client is None or not self.video_client.available:
            logger.warning(
                "[video cascade] file L1/L2 disabled (no openrouter key) "
                "| label=%s", label)
            raise VideoLevelError("no openrouter key")
        video_system = hot.get("prompts.youtube_video_system_prompt",
                               YOUTUBE_VIDEO_SYSTEM_PROMPT)
        system = video_system.replace("{max_symbols}", str(max_symbols))
        user = (f"<video_id>{label}</video_id>\n\n"
                "посмотри ролик по ссылке и перескажи, что в нём происходит.")
        last_reason = "file cascade empty"
        for level, key, settings_attr in (
                ("L1", "models.video_primary_model", settings.VIDEO_PRIMARY_MODEL),
                ("L2", "models.video_fallback_model", settings.VIDEO_FALLBACK_MODEL),
        ):
            model = str(hot.get(key, settings_attr) or "").strip()
            if not model:                             # пусто = ступень отключена
                logger.warning(
                    "[video cascade] %s skipped (empty model) | label=%s",
                    level, label)
                continue
            started = time.monotonic()
            try:
                raw = await asyncio.wait_for(
                    self.video_client.summarize(
                        model=model, video_url=video_url,
                        system_prompt=system, user_text=user, timeout=timeout),
                    timeout=timeout)
            except VideoLevelError as exc:
                last_reason = str(exc)
                logger.warning(
                    "[video cascade] %s failed → next | model=%s label=%s "
                    "| reason=%s", level, model, label, exc)
                continue
            except asyncio.TimeoutError:
                last_reason = "timeout"
                logger.warning(
                    "[video cascade] %s timeout (%.0fs) → next | model=%s "
                    "label=%s", level, timeout, model, label)
                continue
            text = cleanup_llm_text(raw)
            if not text.strip():
                last_reason = "empty answer"
                logger.warning(
                    "[video cascade] %s empty answer → next | model=%s label=%s",
                    level, model, label)
                continue
            logger.info(                                # R41-5
                "[video cascade] file OK | level=%s model=%s label=%s "
                "out_chars=%d latency_ms=%.0f",
                level, model, label, len(text),
                (time.monotonic() - started) * 1000.0)
            return text                                # успех L1/L2
        raise VideoLevelError(f"{last_reason} | label={label}")
