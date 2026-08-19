"""Epic 42 — CheckupService (Section 51.6): логи → LLM-отчёт → cleanup."""
import logging
import time

from config.settings import settings
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE, CHECKUP_SYSTEM_PROMPT
from services.llm_client import LLMClient
from services.summary_cleanup import cleanup_llm_text
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)


class CheckupService:
    """Канон SmartModule: system.replace({max_symbols}) → llm.generate →
    cleanup_llm_text (R33-7, ВСЕГДА). LLMError пробрасывается в хендлер."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def checkup(self, logs_text: str, used_fallback: bool) -> str:
        """logs_text = результат fetcher.fetch(); used_fallback → скрытая
        приписка CHECKUP_FALLBACK_NOTICE в КОНЕЦ system-сообщения (51.4)."""
        system = CHECKUP_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.CHECKUP_MAX_SYMBOLS)
        )
        if used_fallback:
            system += "\n\n" + CHECKUP_FALLBACK_NOTICE     # R42-2: ровно 1 раз
        user = f"<system_logs>{escape_xml_text(logs_text)}</system_logs>"
        started = time.monotonic()
        raw = await self.llm.generate(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        logger.info(
            "checkup LLM OK | out_chars=%d | latency_ms=%.0f | used_fallback=%s",
            len(raw), (time.monotonic() - started) * 1000.0, used_fallback,
        )
        return cleanup_llm_text(raw)
