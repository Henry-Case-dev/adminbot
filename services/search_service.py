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

# Epic 65: LLM-реранкинг выдачи (Anthropic Contextual Retrieval: rerank даёт
# крупнейший прирост поверх контекста). Компактный утилитарный промпт — НЕ канон.
_RERANK_SYSTEM_PROMPT = (
    "Ты — фильтр поисковой выдачи. Тебе даны запрос и сырые результаты поиска. "
    "Верни ТОЛЬКО фрагменты результатов, реально релевантные запросу, склеенные "
    "в один связный текст (можно сокращать формулировки, но не выдумывать факты). "
    "Ничего не комментируй. Если релевантного нет вообще — верни пустую строку."
)

# Экономия: если после реранка осталось слишком мало — считаем промахом и
# возвращаем исходную выдачу (fail-open, урок BiCon-Gate'26 про семантический дрейф).
_RERANK_MIN_CHARS = 300


def _rerank_usable(original: str, reranked: str) -> bool:
    """Epic 65 (pure): использовать ли результат реранка."""
    return bool(reranked) and len(reranked.strip()) >= _RERANK_MIN_CHARS \
        and len(reranked.strip()) < len(original)


class SearchService:
    """Смарт-поиск: факты из каскада → LLM-выжимка → cleanup."""

    def __init__(self, aggregator: SearchAggregator, llm: LLMClient,
                 memory: MemoryManager | None = None) -> None:
        self.aggregator = aggregator
        self.llm = llm
        self.memory = memory

    async def research(self, query: str, chat_id: int | None = None,
                       chat_context: str | None = None) -> str:
        """Смарт-поиск:
        1) results = await self.aggregator.search(query, settings.SEARCH_MAX_SYMBOLS)
        1b) Epic 65: LLM-реранкинг выдачи (SEARCH_RERANK_ENABLED, fail-open)
        2) system = SEARCH_SYSTEM_PROMPT.replace("{max_symbols}", str(settings.SEARCH_MAX_SYMBOLS))
        3) user = [rag] [chat_context] "<query>…</query>\n\n<search_results>…</search_results>"
        4) raw = await self.llm.generate([{system}, {user}])
        5) return cleanup_llm_text(raw)          # R33-7
        Raises: AllSearchEnginesFailedException / LLMError — пробрасываются."""
        results = await self.aggregator.search(query, settings.SEARCH_MAX_SYMBOLS)
        if settings.SEARCH_RERANK_ENABLED and results.strip():
            results = await self._rerank_results(query, results)
        if self.memory is not None and chat_id is not None:
            fire_and_forget(
                self.memory.memorize_facts(chat_id, results, "search_fact"), "search")
            rag = await self.memory.get_rag_context(chat_id, query)   # 55.6, никогда не бросает
        else:
            rag = ""
        system = SEARCH_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.SEARCH_MAX_SYMBOLS)
        )
        ctx_block = f"{chat_context}\n\n" if chat_context else ""
        user = (f"{rag}\n\n" if rag else "") + ctx_block + (
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

    async def _rerank_results(self, query: str, results: str) -> str:
        """Epic 65: LLM-фильтр выдачи. Fail-open: любая ошибка/слишком короткий
        ответ → исходные результаты (WARNING). Никогда не бросает."""
        try:
            reranked = await self.llm.generate(
                [
                    {"role": "system", "content": _RERANK_SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"<query>{escape_xml_text(query)}</query>\n\n"
                        f"<search_results>{escape_xml_text(results)}</search_results>"
                    )},
                ]
            )
        except Exception as exc:
            logger.warning("smartsearch rerank failed — original results | error=%s", exc)
            return results
        reranked = cleanup_llm_text(reranked)
        if _rerank_usable(results, reranked):
            logger.info("smartsearch rerank OK | %d -> %d chars",
                        len(results), len(reranked))
            return reranked
        logger.info("smartsearch rerank skipped (thin output) | %d -> %d chars",
                    len(results), len(reranked or ""))
        return results
