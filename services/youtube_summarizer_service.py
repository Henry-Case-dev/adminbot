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
"""
import logging
import time
from typing import Awaitable, Callable

from config.settings import settings
from services.llm_client import LLMBadResponseError, LLMClient
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, _memorize_youtube, fire_and_forget
from services.summary_xml import escape_xml_text
from services.youtube_prompts import YOUTUBE_SYSTEM_PROMPT
from services.youtube_transcript_engine import YouTubeTranscriptEngine

logger = logging.getLogger(__name__)


class YoutubeSummarizerService:
    """YouTube: субтитры → LLM-выжимка в токсичном стиле → cleanup."""

    def __init__(self, engine: YouTubeTranscriptEngine, llm: LLMClient,
                 memory: MemoryManager | None = None) -> None:
        self.engine = engine
        self.llm = llm
        self.memory = memory

    async def summarize(
        self,
        video_id: str,
        on_retry: Callable[[int, int], Awaitable[None]] | None = None,
        chat_id: int | None = None,
        rag_query: str | None = None,
    ) -> str:
        """R41-2/D156: on_retry пробрасывается в движок как есть
        (None — ретраи без уведомлений). Остальной пайплайн — 46.8/55.5."""
        transcript = await self.engine.fetch_transcript(
            video_id, settings.YOUTUBE_MAX_SYMBOLS, on_retry=on_retry
        )
        if self.memory is not None and chat_id is not None:
            fire_and_forget(
                _memorize_youtube(self.memory, chat_id, transcript), "youtube")
        rag = await self.memory.get_rag_context(chat_id, rag_query) if (
            self.memory and chat_id is not None and rag_query) else ""
        system = YOUTUBE_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.YOUTUBE_MAX_SYMBOLS)
        )
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
