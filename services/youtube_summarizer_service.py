"""Epic 37 — YoutubeSummarizerService (R37-7, D130, Section 46.8).

Пайплайн (прецедент FactCheckService 42.6): движок транскрипта →
YOUTUBE_SYSTEM_PROMPT ({max_symbols} через .replace) → XML-контекст
<video_id>/<transcript> → LLMClient.generate → cleanup_llm_text (R37-7, ВСЕГДА,
ВНУТРИ сервиса, ДО чанкинга). Ошибки движка/LLM пробрасываются в хендлер —
фразы выбирает хендлер.
"""
import logging
import time

from config.settings import settings
from services.llm_client import LLMClient
from services.summary_cleanup import cleanup_llm_text
from services.summary_xml import escape_xml_text
from services.youtube_prompts import YOUTUBE_SYSTEM_PROMPT
from services.youtube_transcript_engine import YouTubeTranscriptEngine

logger = logging.getLogger(__name__)


class YoutubeSummarizerService:
    """YouTube: субтитры → LLM-выжимка в токсичном стиле → cleanup."""

    def __init__(self, engine: YouTubeTranscriptEngine, llm: LLMClient) -> None:
        self.engine = engine
        self.llm = llm

    async def summarize(self, video_id: str) -> str:
        """1) transcript = await self.engine.fetch_transcript(video_id,
                                                              settings.YOUTUBE_MAX_SYMBOLS)
        2) system = YOUTUBE_SYSTEM_PROMPT.replace("{max_symbols}",
                                                  str(settings.YOUTUBE_MAX_SYMBOLS))
        3) user = f"<video_id>{video_id}</video_id>\n\n"
                  f"<transcript>{escape_xml_text(transcript)}</transcript>"
                  (escape_xml_text из services/summary_xml.py; D130: заголовок НЕ нужен,
                  video_id — отдельным тегом для grounding)
        4) raw = await self.llm.generate([{system}, {user}])
        5) return cleanup_llm_text(raw)          # R37-7, ПОСТОЯННО
        Raises: YouTubeTranscriptUnavailableException / LLMError — пробрасываются."""
        transcript = await self.engine.fetch_transcript(
            video_id, settings.YOUTUBE_MAX_SYMBOLS
        )
        system = YOUTUBE_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.YOUTUBE_MAX_SYMBOLS)
        )
        user = (
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
        return cleanup_llm_text(raw)
