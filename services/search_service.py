"""Epic 33 — SearchService: пайплайн смарт-поиска (R33-4, Section 42.6).

research: SearchAggregator.search → SEARCH_SYSTEM_PROMPT (подстановка
{max_symbols} через .replace) → XML-контекст <query>/<search_results> →
LLMClient.generate → cleanup_llm_text (R33-7, ВСЕГДА). Ошибки поиска/LLM
пробрасываются в хендлер — фразы выбирает хендлер.
"""
import logging
import time

from config.settings import settings
from services.llm_client import LLMClient
from services.search_aggregator import SearchAggregator
from services.search_prompts import SEARCH_SYSTEM_PROMPT
from services.summary_cleanup import cleanup_llm_text
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)


class SearchService:
    """Смарт-поиск: факты из каскада → LLM-выжимка → cleanup."""

    def __init__(self, aggregator: SearchAggregator, llm: LLMClient) -> None:
        self.aggregator = aggregator
        self.llm = llm

    async def research(self, query: str) -> str:
        """Смарт-поиск:
        1) results = await self.aggregator.search(query, settings.SEARCH_MAX_SYMBOLS)
        2) system = SEARCH_SYSTEM_PROMPT.replace("{max_symbols}", str(settings.SEARCH_MAX_SYMBOLS))
        3) user = "<query>…</query>\n\n<search_results>…</search_results>" (escape_xml_text)
        4) raw = await self.llm.generate([{system}, {user}])
        5) return cleanup_llm_text(raw)          # R33-7
        Raises: AllSearchEnginesFailedException / LLMError — пробрасываются."""
        results = await self.aggregator.search(query, settings.SEARCH_MAX_SYMBOLS)
        system = SEARCH_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.SEARCH_MAX_SYMBOLS)
        )
        user = (
            f"<query>{escape_xml_text(query)}</query>\n\n"
            f"<search_results>{escape_xml_text(results)}</search_results>"
        )
        started = time.monotonic()
        raw = await self.llm.generate(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        logger.info(
            "smartsearch LLM OK | out_chars=%d | latency_ms=%.0f",
            len(raw), (time.monotonic() - started) * 1000.0,
        )
        return cleanup_llm_text(raw)
