"""Раунд 10 (multi-chat-rbac-byok, F-7 §5.2) — бюджет глобального ключа.

`chat_usage (chat_id, day DATE, metric, used, PK(chat_id, day, metric))`;
metric ∈ {'llm_calls','llm_tokens'}. Счётчик — в PG, на КОНЦЕ LLM-вызова
(1 вызов + фактические токены ответа, estimate len/4 — приблизительность
README-пометка), пред-проверка «used > limit → не тратить». Лимиты —
REGISTRY limits.chat_global_key_budget_tokens (100000) /
limits.chat_global_key_budget_requests (25). Лимит 0 = глобальный ключ
этому чату запрещён. День — WORKER_BUDGET_TZ (единая таймзона раунда).
"""
import datetime
import logging
from zoneinfo import ZoneInfo

from config.settings import settings

logger = logging.getLogger(__name__)

METRIC_CALLS = "llm_calls"
METRIC_TOKENS = "llm_tokens"

KEY_BUDGET_TOKENS = "limits.chat_global_key_budget_tokens"
KEY_BUDGET_REQUESTS = "limits.chat_global_key_budget_requests"

DAY_TZ = (settings.WORKER_BUDGET_TZ or "Asia/Yekaterinburg")

UPSERT_USAGE_SQL = (
    "INSERT INTO chat_usage (chat_id, day, metric, used) "
    "VALUES ($1, $2, $3, $4) "
    "ON CONFLICT (chat_id, day, metric) DO UPDATE "
    "SET used = chat_usage.used + EXCLUDED.used, updated_at = now() "
    "RETURNING used"
)
USAGE_SELECT_SQL = (
    "SELECT metric, used FROM chat_usage "
    "WHERE chat_id = $1 AND day = $2"
)


def _pool(pg):
    return getattr(pg, "pool", None) if pg is not None else None


def today() -> datetime.date:
    """Локальный день сервера (WORKER_BUDGET_TZ)."""
    try:
        return datetime.datetime.now(
            ZoneInfo(DAY_TZ)).date()
    except Exception:
        return datetime.date.today()


def _budget_limit_requests(default: int = 25) -> int:
    from services import hot_config as hot
    return int(hot.get(KEY_BUDGET_REQUESTS, default) or default)


def _budget_limit_tokens(default: int = 100000) -> int:
    from services import hot_config as hot
    return int(hot.get(KEY_BUDGET_TOKENS, default) or default)


async def register_usage(pg, chat_id: int, metric: str, amount: int = 1,
                         day: datetime.date | None = None) -> int:
    """Атомарный апсерт счётчика (первый вызов дня создаёт строку).
    Возвращает новое использованное значение. PG down → 0 + WARNING
    (fail-open: бот жив, счёт приблизительный)."""
    pool = _pool(pg)
    if pool is None:
        logger.warning("[chat_usage] PG down — счёт пропущен | chat=%s",
                       chat_id)
        return 0
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                UPSERT_USAGE_SQL, chat_id, day or today(), metric,
                max(0, int(amount)))
    except Exception:
        logger.warning("[chat_usage] register failed — fail-open | chat=%s",
                       chat_id, exc_info=True)
        return 0
    return int(row["used"]) if row is not None else 0


async def used_today(pg, chat_id: int) -> dict:
    """{metric: used} на сегодня (0 — строки нет/недоступен PG)."""
    pool = _pool(pg)
    if pool is None:
        return {}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(USAGE_SELECT_SQL, chat_id, today())
    except Exception:
        logger.warning("[chat_usage] read failed — fail-open | chat=%s",
                       chat_id, exc_info=True)
        return {}
    return {r["metric"]: int(r["used"]) for r in rows}


async def budget_exceeded(pg, chat_id: int,
                          tokens_estimate: int = 0) -> bool:
    """Суточный бюджет исчерпан (или 0-лимит = запрещён глобальный ключ)."""
    req_limit = _budget_limit_requests()
    tok_limit = _budget_limit_tokens()
    if req_limit <= 0 or tok_limit <= 0:
        return True
    used = await used_today(pg, chat_id)
    if int(used.get(METRIC_CALLS, 0)) >= req_limit:
        return True
    if int(used.get(METRIC_TOKENS, 0)) + max(0, int(tokens_estimate)) \
            > tok_limit:
        return True
    return False


def estimate_tokens(text: str | None) -> int:
    """Оценка токенов вызова (len/4) — приблизительность README (§5.2)."""
    return max(1, len(text or "") // 4)


async def report_call(pg, chat_id: int, tokens: int = 0) -> None:
    """Конец LLM-вызова на глобальном ключе: 1 вызов + токены."""
    await register_usage(pg, chat_id, METRIC_CALLS, 1)
    if tokens > 0:
        await register_usage(pg, chat_id, METRIC_TOKENS, tokens)


async def key_status(pg, chat_id: int) -> dict:
    """Статусы для GET /api/config/keys/status (F-7 §6)."""
    used = await used_today(pg, chat_id)
    return {
        "calls": {"used": int(used.get(METRIC_CALLS, 0)),
                  "limit": _budget_limit_requests()},
        "tokens": {"used": int(used.get(METRIC_TOKENS, 0)),
                   "limit": _budget_limit_tokens()},
    }
