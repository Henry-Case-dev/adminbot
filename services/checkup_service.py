"""Epic 42 — CheckupService (Section 51.6): логи → LLM-отчёт → cleanup.
Epic 60 (64.5, T-466): db+memory → data-секция <memory_health> в user-контенте
(порядок: логи → метрики; единый потолок; R42-6 НЕ меняется)."""
import logging
import re
import time

from config.settings import settings
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE, CHECKUP_SYSTEM_PROMPT
from services.llm_client import LLMBadResponseError, LLMClient
from services.memory_health import collect_metrics
from services.summary_cleanup import cleanup_llm_text
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)

# Epic 49 (Section 57.5, D196): C0-управляющие, кроме \n (переносы логов) и
# \t; плюс DEL (0x7f). Каждый такой символ → ровно ОДИН пробел.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class CheckupService:
    """Канон SmartModule: system.replace({max_symbols}) → llm.generate →
    cleanup_llm_text (R33-7, ВСЕГДА). LLMError пробрасывается в хендлер.
    Epic 60 (64.5): метрики памяти подаются ДАННЫМИ в user-контент (без
    db/memory — ровно старое поведение; metrics_enabled=false — рубильник)."""

    def __init__(self, llm: LLMClient, db=None, memory=None,
                 metrics_enabled: bool = settings.CHECKUP_MEMORY_METRICS_ENABLED) -> None:
        self.llm = llm
        self.db = db
        self.memory = memory
        self.metrics_enabled = metrics_enabled

    async def checkup(self, logs_text: str, used_fallback: bool) -> str:
        """logs_text = результат fetcher.fetch(); used_fallback → скрытая
        приписка CHECKUP_FALLBACK_NOTICE в КОНЕЦ system-сообщения (51.4)."""
        system = CHECKUP_SYSTEM_PROMPT.replace(
            "{max_symbols}", str(settings.CHECKUP_MAX_SYMBOLS)
        )
        if used_fallback:
            system += "\n\n" + CHECKUP_FALLBACK_NOTICE     # R42-2: ровно 1 раз
        # Epic 49 (57.5, D196): scrub C0 (гипотеза (б) — невалидные управляющие
        # символы raw-логов) → потолок CHECKUP_MAX_INPUT_SYMBOLS (запас к окну
        # модели) → escape. Единая точка — здесь, ДО escape_xml_text.
        user_content = _CONTROL_CHARS_RE.sub(" ", logs_text)
        # Epic 60 (64.5): метрики ПЕРЕД потолком — единый потолок для обеих
        # секций; при переполнении режется ХВОСТ (метрики идут последними —
        # логи всегда приоритетнее, 64.10.2).
        metrics = ""
        if self.metrics_enabled and self.db is not None:
            try:
                metrics = await collect_metrics(self.db, self.memory)
            except Exception:
                logger.warning("[checkup] memory metrics failed", exc_info=True)
                metrics = ""
        body = user_content
        if metrics:
            body += "\n\n<memory_health>\n" + escape_xml_text(metrics) + "\n</memory_health>"
        if len(body) > settings.CHECKUP_MAX_INPUT_SYMBOLS:
            logger.warning(
                "[checkup] input truncated | chars=%d -> %d",
                len(body), settings.CHECKUP_MAX_INPUT_SYMBOLS,
            )
            body = body[:settings.CHECKUP_MAX_INPUT_SYMBOLS]
        user = f"<system_logs>{escape_xml_text(body)}</system_logs>"
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
        raw = cleanup_llm_text(raw)
        if not raw.strip():
            # Epic 60 (65.1, T-469): пустой ответ → молчание + 🗿 (хендлер
            # ничего не шлёт). Ветка хендлера ДО except LLMError.
            raise LLMBadResponseError("checkup: empty answer")
        return raw
