"""Epic 33/46 — SearchService: пайплайн смарт-поиска (R33-4, Sections 42.6/55.5).

research: SearchAggregator.search → SEARCH_SYSTEM_PROMPT (подстановка
{max_symbols} через .replace) → XML-контекст <query>/<search_results> →
LLMClient.generate → cleanup_llm_text (R33-7, ВСЕГДА). Ошибки поиска/LLM
пробрасываются в хендлер — фразы выбирает хендлер.

Epic 46 (55.5): после aggregator.search() — fire_and_forget-хук
memorize_facts(chat_id, results, "search_fact") (raw-результаты поиска, НЕ
LLM-ответ) + гибридный RAG (get_rag_context) префиксом user-контента.
memory=None / chat_id=None → ровно старое поведение.
"""
import logging
import time

from config.settings import settings
from services.llm_client import LLMBadResponseError, LLMClient
from services.search_aggregator import SearchAggregator
from services.search_prompts import SEARCH_SYSTEM_PROMPT
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, fire_and_forget
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)


class SearchService:
    """Смарт-поиск: факты из каскада → LLM-выжимка → cleanup."""

    def __init__(self, aggregator: SearchAggregator, llm: LLMClient,
                 memory: MemoryManager | None = None) -> None:
        self.aggregator = aggregator
        self.llm = llm
        self.memory = memory

    async def research(self, query: str, chat_id: int | None = None) -> str:
        """Смарт-поиск:
        1) results = await self.aggregator.search(query, settings.SEARCH_MAX_SYMBOLS)
        2) system = SEARCH_SYSTEM_PROMPT.replace("{max_symbols}", str(settings.SEARCH_MAX_SYMBOLS))
        3) user = [rag] "<query>…</query>\n\n<search_results>…</search_results>" (escape_xml_text)
        4) raw = await self.llm.generate([{system}, {user}])
        5) return cleanup_llm_text(raw)          # R33-7
        Raises: AllSearchEnginesFailedException / LLMError — пробрасываются."""
        results = await self.aggregator.search(query, settings.SEARCH_MAX_SYMBOLS)
        if self.memory is not None and chat_id is not None:
            fire_and_forget(
                self.memory.memorize_facts(chat_id, results, "search_fact"), "search")
            rag = await self.memory.get_rag_context(chat_id, query)   # 55.6, никогда не бросает
        else:
            rag = ""
        system = SEARCH_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.SEARCH_MAX_SYMBOLS)
        )
        user = (f"{rag}\n\n" if rag else "") + (
            f"<query>{escape_xml_text(query)}</query>\n\n"
            f"<search_results>{escape_xml_text(results)}</search_results>")
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
        raw = cleanup_llm_text(raw)
        if not raw.strip():
            # Epic 60 (65.1, T-469): пустой ответ → молчание + 🗿 (хендлер).
            raise LLMBadResponseError("smartsearch: empty answer")
        return raw
