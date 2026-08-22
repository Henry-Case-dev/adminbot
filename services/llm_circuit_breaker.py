"""Epic 53 (Section 62.3, D216) — Circuit Breaker для direct_chat LLM-вызовов.

Конечный автомат:
    CLOSED ──(threshold транзиентных фейлов подряд)──▶ OPEN (кулдаун)
    OPEN ──(кулдаун истёк)──▶ HALF_OPEN (ровно ОДНА пробная генерация)
    HALF_OPEN ──успех──▶ CLOSED (полный сброс счётчика)
    HALF_OPEN ──фейл──▶ OPEN (новый кулдаун)

Параметры: failure_threshold (LLM_CB_FAILURE_THRESHOLD, default 3 — совпадает
с числом HTTP-попыток одного generate), cooldown_seconds
(LLM_CB_COOLDOWN_SECONDS, default 300.0). Транзиентные классы (инкремент):
LLMTimeoutError / LLMServerError / LLMTransportError; 429/4xx/auth НЕ
инкрементят (апстрим жив / детерминированный отказ).

In-memory, однопоточный event loop (прецедент DirectChatThrottle) —
asyncio.Lock не нужен; time.monotonic(); рестарт сбрасывает CB (принято,
прецедент CooldownTracker). Скоуп: ТОЛЬКО direct_chat — llm_client о CB не
знает (контракт 62.3); фоновые пайплайны (memorize/summary) CB не используют
(62.1 в.7).
"""
import logging
import time

logger = logging.getLogger(__name__)

STATE_CLOSED = "CLOSED"
STATE_OPEN = "OPEN"
STATE_HALF_OPEN = "HALF_OPEN"


class LLMCircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 300.0) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._state = STATE_CLOSED
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        return self._state

    def allow_request(self) -> bool:
        """CLOSED → True. OPEN (кулдаун не истёк) → False. OPEN (истёк) →
        HALF_OPEN — сам этот вызов и есть пробная генерация (True ровно один
        раз). HALF_OPEN → False до результата пробы (on_success/on_failure)."""
        now = time.monotonic()
        if self._state == STATE_CLOSED:
            return True
        if self._state == STATE_OPEN:
            if self._opened_at is None or now - self._opened_at < self._cooldown:
                return False
            self._state = STATE_HALF_OPEN
            logger.info(
                "LLM CB half-open | cooldown expired, probe allowed | cooldown=%.0fs",
                self._cooldown,
            )
            return True
        # HALF_OPEN: пробная генерация уже выдана — отказ до её результата
        return False

    def on_success(self) -> None:
        """Полный сброс: CLOSED, failures=0 (1 успех достаточно, 62.3.1)."""
        self._state = STATE_CLOSED
        self._failures = 0
        self._opened_at = None

    def on_failure(self) -> None:
        """Транзиентный фейл → failures += 1; >= threshold → OPEN + новый
        кулдаун (в т.ч. фейл half-open-пробы → снова OPEN)."""
        self._failures = min(self._failures + 1, self._threshold)
        if self._failures >= self._threshold:
            self._state = STATE_OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "LLM CB opened | failures=%d/%d | cooldown=%.0fs",
                self._failures, self._threshold, self._cooldown,
            )
