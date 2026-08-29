"""Epic 38/46 — WebSummarizerService (R38-3, Sections 47.5/55.5).

Пайплайн (прецедент FactCheckService 42.6): WebContentExtractor →
WEBPAGE_SYSTEM_PROMPT ({max_symbols} через .replace) → XML-контекст
<webpage url="…"> → LLMClient.generate → cleanup_llm_text (R37-7, ВСЕГДА,
ВНУТРИ сервиса, ДО чанкинга). Ошибки экстрактора/LLM пробрасываются
в хендлер — фразы выбирает хендлер.

Epic 46 (55.5): после extractor.extract — fire_and_forget-хук
memorize_facts(chat_id, markdown, "web_content") + гибридный RAG
(get_rag_context по rag_query) префиксом user-контента. memory=None /
chat_id=None / rag_query пуст → ровно старое поведение.
"""
import logging
import time

from config.settings import settings
from services import hot_config as hot
from services.llm_client import LLMBadResponseError, LLMClient
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, fire_and_forget
from services.summary_xml import escape_xml_text
from services.web_content_extractor import WebContentExtractor
from services.web_prompts import WEBPAGE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class WebSummarizerService:
    """Web: страница через WebContentExtractor (trafilatura→Tavily→Exa) →
    LLM-выжимка в токсичном стиле → cleanup."""

    def __init__(self, extractor: WebContentExtractor, llm: LLMClient,
                 memory: MemoryManager | None = None) -> None:
        self.extractor = extractor
        self.llm = llm
        self.memory = memory

    async def summarize(self, url: str, chat_id: int | None = None,
                        rag_query: str | None = None) -> str:
        """1) markdown = await self.extractor.extract(url,
           settings.WEBPAGE_MAX_SYMBOLS)
        2) system = WEBPAGE_SYSTEM_PROMPT.replace("{max_symbols}",
                                                  str(settings.WEBPAGE_MAX_SYMBOLS))
        3) user = [rag] f'<webpage url="{escape_xml_text(url, quote=True)}">\n'
                  f'{escape_xml_text(markdown)}\n</webpage>'
                  (quote=True — прецедент factcheck build_user_content, 42.6)
        4) raw = await self.llm.generate([{system}, {user}])
        5) return cleanup_llm_text(raw)          # R37-7, ПОСТОЯННО
        Raises: WebContentExtractionFailedException / LLMError —
        пробрасываются."""
        # T-619: лимит и промпт — горячие точки (фолбек settings)
        max_symbols = hot.get("limits.webpage_max_symbols",
                              settings.WEBPAGE_MAX_SYMBOLS)
        system_prompt = hot.get("prompts.webpage_system_prompt",
                                WEBPAGE_SYSTEM_PROMPT)
        markdown = await self.extractor.extract(url, max_symbols)
        if self.memory is not None and chat_id is not None:
            fire_and_forget(
                self.memory.memorize_facts(chat_id, markdown, "web_content"), "web")
        rag = await self.memory.get_rag_context(chat_id, rag_query) if (
            self.memory and chat_id is not None and rag_query) else ""
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        user = (f"{rag}\n\n" if rag else "") + (
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
        raw = cleanup_llm_text(raw)
        if not raw.strip():
            # Epic 60 (65.1, T-469): пустой ответ → молчание + 🗿 (хендлер).
            raise LLMBadResponseError("web summarizer: empty answer")
        return raw
