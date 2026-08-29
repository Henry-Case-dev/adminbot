"""Epic 42 — CheckupService (Section 51.6): логи → LLM-отчёт → cleanup.
Epic 60 (64.5, T-466): db+memory → data-секция <memory_health> в user-контенте.
Epic 61 (64.5 хотфикс, D250/T-501): секция метрик собирается ПЕРВОЙ с
резервом длины (логи режутся до MAX_INPUT − len(секции) — метрики всегда
живы); escape РОВНО ОДИН раз на финальной обёртке <system_logs>."""
import logging
import re
import time

from config.settings import settings
from services import hot_config as hot
from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE, CHECKUP_SYSTEM_PROMPT
from services.llm_client import LLMBadResponseError, LLMClient
from services.memory_health import collect_metrics
from services.summary_cleanup import cleanup_llm_text
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)

# Epic 49 (Section 57.5, D196): C0-управляющие, кроме \n (переносы логов) и
# \t; плюс DEL (0x7f). Каждый такой символ → ровно ОДИН пробел.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Epic 61 (64.5 хотфикс, D250/T-500): потолок секции метрик ДО расчёта бюджета
# логов (крайний случай «метрики разрослись»); бюджет логов гарантированно
# ≥ CHECKUP_MAX_INPUT_SYMBOLS − (2000 + обвязка) ≈ 9970.
_METRICS_MAX_SYMBOLS = 2000


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
        # T-619: промпт/лимиты/флаг метрик — горячие точки (фолбек settings)
        system_prompt = hot.get("prompts.checkup_system_prompt",
                                CHECKUP_SYSTEM_PROMPT)
        max_symbols = hot.get("limits.checkup_max_symbols",
                              settings.CHECKUP_MAX_SYMBOLS)
        max_input = hot.get("limits.checkup_max_input_symbols",
                            settings.CHECKUP_MAX_INPUT_SYMBOLS)
        metrics_enabled = hot.get("flags.checkup_memory_metrics_enabled",
                                  self.metrics_enabled)
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        if used_fallback:
            system += "\n\n" + CHECKUP_FALLBACK_NOTICE     # R42-2: ровно 1 раз
        # Epic 49 (57.5, D196): scrub C0 (гипотеза (б) — невалидные управляющие
        # символы raw-логов). Единая точка — здесь, ДО escape_xml_text.
        user_content = _CONTROL_CHARS_RE.sub(" ", logs_text)
        # Epic 61 (64.5 хотфикс, D250): метрики СНАЧАЛА + резерв длины —
        # потолок метрик ДО расчёта бюджета, затем логи режутся до
        # (CHECKUP_MAX_INPUT_SYMBOLS − len(секции)) → метрики всегда живы.
        metrics = ""
        if metrics_enabled and self.db is not None:
            try:
                metrics = await collect_metrics(self.db, self.memory)
            except Exception:
                logger.warning("[checkup] memory metrics failed", exc_info=True)
                metrics = ""
        if len(metrics) > _METRICS_MAX_SYMBOLS:
            metrics = metrics[:_METRICS_MAX_SYMBOLS]
        # БЕЗ предварительного escape (escape РОВНО ОДИН на обёртке ниже).
        metrics_section = (
            "\n\n<memory_health>\n" + metrics + "\n</memory_health>"
        ) if metrics else ""
        logs_budget = max_input - len(metrics_section)
        if len(user_content) > logs_budget:
            logger.warning(
                "[checkup] input truncated | chars=%d -> %d",
                len(user_content), logs_budget,
            )
            user_content = user_content[:logs_budget]
        body = user_content + metrics_section
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
