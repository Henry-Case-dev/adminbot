"""Epic 33/46 — FactCheckService: пайплайн фактчека (R33-3, Sections 42.6/55.5).

check_claim: SearchAggregator.search → FACTCHECK_SYSTEM_PROMPT (подстановка
{max_symbols} через .replace) → build_user_content → LLMClient.generate →
cleanup_llm_text (R33-7, ВСЕГДА). Ошибки поиска/LLM пробрасываются в хендлер
(AllSearchEnginesFailedException / LLMError) — фразы выбирает хендлер.

Epic 46 (55.5): после aggregator.search() — fire_and_forget-хук
memorize_facts(chat_id, results, "search_fact") + гибридный RAG префиксом
user-контента. memory=None / chat_id=None → ровно старое поведение.
"""
import logging
import time

from config.settings import settings
from services.factcheck_prompts import FACTCHECK_SYSTEM_PROMPT
from services.llm_client import LLMBadResponseError, LLMClient
from services.search_aggregator import SearchAggregator
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, fire_and_forget
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)


class FactCheckService:
    """Фактчек: поиск фактов по целевому тексту → LLM-вердикт → cleanup."""

    def __init__(self, aggregator: SearchAggregator, llm: LLMClient,
                 memory: MemoryManager | None = None) -> None:
        self.aggregator = aggregator
        self.llm = llm
        self.memory = memory

    async def check_claim(
        self,
        target_text: str,
        user_hint: str | None = None,
        forward_source: str | None = None,
        chat_id: int | None = None,
    ) -> str:
        """Фактчек-пайплайн:
        1) results = await self.aggregator.search(target_text, settings.FACTCHECK_MAX_SYMBOLS)
        2) system = FACTCHECK_SYSTEM_PROMPT.replace("{max_symbols}", str(settings.FACTCHECK_MAX_SYMBOLS))
        3) user = [rag] self.build_user_content(target_text, user_hint, forward_source, results)
        4) raw = await self.llm.generate([{system}, {user}])
        5) return cleanup_llm_text(raw)          # R33-7, ПОСТОЯННО
        Raises: AllSearchEnginesFailedException (поиск) / LLMError (LLM) — пробрасываются в хендлер."""
        results = await self.aggregator.search(
            target_text, settings.FACTCHECK_MAX_SYMBOLS
        )
        if self.memory is not None and chat_id is not None:
            fire_and_forget(
                self.memory.memorize_facts(chat_id, results, "search_fact"), "factcheck")
            rag = await self.memory.get_rag_context(chat_id, target_text)
        else:
            rag = ""
        system = FACTCHECK_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.FACTCHECK_MAX_SYMBOLS)
        )
        user = self.build_user_content(target_text, user_hint, forward_source, results)
        if rag:
            user = f"{rag}\n\n{user}"
        started = time.monotonic()
        raw = await self.llm.generate(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        logger.info(
            "factcheck LLM OK | out_chars=%d | latency_ms=%.0f",
            len(raw), (time.monotonic() - started) * 1000.0,
        )
        raw = cleanup_llm_text(raw)
        if not raw.strip():
            # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿
            # (хендлер). LLMBadResponseError — подкласс LLMError, но ветка
            # хендлера идёт ДО except LLMError (R13-эталоны не тронуты).
            raise LLMBadResponseError("factcheck: empty answer")
        return raw

    @staticmethod
    def build_user_content(
        target_text: str,
        user_hint: str | None,
        forward_source: str | None,
        search_results: str,
    ) -> str:
        """Контекст пользователя (42.6):
        # <claim>…</claim>  — всегда
        # <claim is_forward="true" forward_source="…">…</claim> — если forward_source задан
        #   (прецедент: атрибут is_forward в SYSTEM_PROMPT Epic 24/28)
        # <user_hint>…</user_hint> — только если user_hint задан
        # <search_results>…</search_results> — всегда
        # Все значения — через escape_xml_text (services/summary_xml.py)"""
        claim_text = escape_xml_text(target_text)
        if forward_source:
            claim = (
                f'<claim is_forward="true" '
                f'forward_source="{escape_xml_text(forward_source, quote=True)}">'
                f"{claim_text}</claim>"
            )
        else:
            claim = f"<claim>{claim_text}</claim>"
        parts = [claim]
        if user_hint:
            parts.append(f"<user_hint>{escape_xml_text(user_hint)}</user_hint>")
        parts.append(f"<search_results>{escape_xml_text(search_results)}</search_results>")
        return "\n\n".join(parts)
