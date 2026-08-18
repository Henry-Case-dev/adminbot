"""Epic 37 — WebSummarizerService (R37-7, Section 46.8).

Пайплайн (прецедент FactCheckService 42.6): Jina Reader →
WEBPAGE_SYSTEM_PROMPT ({max_symbols} через .replace) → XML-контекст
<webpage url="…"> → LLMClient.generate → cleanup_llm_text (R37-7, ВСЕГДА,
ВНУТРИ сервиса, ДО чанкинга). Ошибки ридера/LLM пробрасываются в хендлер —
фразы выбирает хендлер.
"""
import logging
import time

from config.settings import settings
from services.jina_reader import JinaReader
from services.llm_client import LLMClient
from services.summary_cleanup import cleanup_llm_text
from services.summary_xml import escape_xml_text
from services.web_prompts import WEBPAGE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class WebSummarizerService:
    """Web: страница через Jina → LLM-выжимка в токсичном стиле → cleanup."""

    def __init__(self, reader: JinaReader, llm: LLMClient) -> None:
        self.reader = reader
        self.llm = llm

    async def summarize(self, url: str) -> str:
        """1) markdown = await self.reader.fetch_markdown(url, settings.WEBPAGE_MAX_SYMBOLS)
        2) system = WEBPAGE_SYSTEM_PROMPT.replace("{max_symbols}",
                                                  str(settings.WEBPAGE_MAX_SYMBOLS))
        3) user = f'<webpage url="{escape_xml_text(url, quote=True)}">\n'
                  f'{escape_xml_text(markdown)}\n</webpage>'
                  (quote=True — прецедент factcheck build_user_content, 42.6)
        4) raw = await self.llm.generate([{system}, {user}])
        5) return cleanup_llm_text(raw)          # R37-7, ПОСТОЯННО
        Raises: JinaReaderException / LLMError — пробрасываются."""
        markdown = await self.reader.fetch_markdown(
            url, settings.WEBPAGE_MAX_SYMBOLS
        )
        system = WEBPAGE_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.WEBPAGE_MAX_SYMBOLS)
        )
        user = (
            f'<webpage url="{escape_xml_text(url, quote=True)}">\n'
            f"{escape_xml_text(markdown)}\n</webpage>"
        )
        started = time.monotonic()
        raw = await self.llm.generate(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        logger.info(
            "web summarizer LLM OK | out_chars=%d | latency_ms=%.0f",
            len(raw), (time.monotonic() - started) * 1000.0,
        )
        return cleanup_llm_text(raw)
