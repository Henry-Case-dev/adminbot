"""F7 (раунд 10.23, ADR-1023-7) — телеметрия LLM-событий в PG + сквозной
`correlation_id`.

Пишем обогащённую запись на каждый LLM-вызов: `module`, `step`,
`input_tokens`, `output_tokens`, `cost_usd`, `timestamp`, `correlation_id`
(§2.1/§2.5 ADR). Бюджетный контур (`chat_usage`/`worker_budget`,
`source='global'`) здесь НЕ затрагивается — он живёт отдельно.

Инварианты:
* **fail-open**: любая ошибка аналитики (нет PG, битый ответ) не влияет на
  ответ пользователю — только WARNING;
* **R17**: пишутся/логируются только коды/числа/токены, без промптов и
  секретов;
* **ретенция**: opportunistic-очистка по `TOKEN_ANALYTICS_RETENTION_DAYS`
  (env-only) с дедупом по времени (не чаще `CLEANUP_INTERVAL_SECONDS`).

Схема таблиц — `services/pg_db.py` (`llm_usage_events`, `llm_model_prices`).
"""
import logging
import time
import uuid

from config.settings import settings
from services import llm_pricing
from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

# source-домен (ADR-1023-7 D5) — только аналитика; бюджетный контур не трогаем.
SOURCES = ("global", "chat", "byok", "worker", "image")

INSERT_SQL = (
    "INSERT INTO llm_usage_events "
    "(correlation_id, module, step, tool_name, source, chat_id, model, "
    " input_tokens, output_tokens, tokens_estimated, cost_usd, price_known) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)"
)
DELETE_SQL = (
    "DELETE FROM llm_usage_events "
    "WHERE ts < now() - ($1::int * interval '1 day')"
)

# Дедуп opportunistic-очистки: monotonic-метка последнего DELETE.
CLEANUP_INTERVAL_SECONDS = 3600.0
_last_cleanup: float = 0.0


def is_enabled() -> bool:
    """Мастер-рубильник телеметрии (env-only, default ON)."""
    return bool(getattr(settings, "TOKEN_ANALYTICS_ENABLED", True))


def retention_days() -> int:
    """Горизонт хранения событий (дни); мусор/0 → безопасный дефолт 90."""
    try:
        value = int(getattr(settings, "TOKEN_ANALYTICS_RETENTION_DAYS", 90))
    except (TypeError, ValueError):
        return 90
    return value if value > 0 else 90


def new_correlation_id() -> str:
    """Новый сквозной id ответа (UUID4 hex, без дефисов)."""
    return uuid.uuid4().hex


def _pool(pg):
    return getattr(pg, "pool", None) if pg is not None else None


def normalize_source(source: str | None) -> str:
    """Безопасный source аналитики (вне домена → 'global')."""
    value = str(source or "").strip().lower()
    return value if value in SOURCES else "global"


def resolve_token_counts(usage, messages, content) -> tuple[int, int, bool]:
    """Реальные токены из `usage` ответа либо честная оценка.

    Возвращает `(input_tokens, output_tokens, tokens_estimated)`.
    `usage` API-ответа — источник истины (`prompt_tokens`/`completion_tokens`);
    при их отсутствии считаем `token_counter.count_tokens` (fallback len·0.3)
    и помечаем `tokens_estimated=true` (§2.1).
    """
    if isinstance(usage, dict):
        raw_in = usage.get("prompt_tokens")
        raw_out = usage.get("completion_tokens")
        try:
            real_in = int(raw_in) if raw_in is not None else 0
            real_out = int(raw_out) if raw_out is not None else 0
        except (TypeError, ValueError):
            real_in, real_out = 0, 0
        if real_in > 0 or real_out > 0:
            return max(0, real_in), max(0, real_out), False
    text = "\n".join(str((m or {}).get("content") or "")
                     for m in (messages or []))
    return count_tokens(text), count_tokens(content or ""), True


async def record(pg, *, module: str, step: str,
                 correlation_id: str | None = None,
                 source: str = "global",
                 chat_id: int | None = None,
                 model: str = "",
                 tool_name: str = "",
                 input_tokens: int = 0,
                 output_tokens: int = 0,
                 tokens_estimated: bool = False) -> None:
    """Записать usage-событие (fail-open).

    `cost_usd` считается по реальным токенам и цене модели; при неизвестной
    цене — `0` + `price_known=false`. Ошибка/PG down → событие пропущено,
    бот жив. Off-switch (`TOKEN_ANALYTICS_ENABLED=OFF`) → no-op.
    """
    if not is_enabled():
        return
    pool = _pool(pg)
    if pool is None:
        return
    try:
        in_tokens = max(0, int(input_tokens))
        out_tokens = max(0, int(output_tokens))
        price = await llm_pricing.resolve_price(pg, model)
        cost_usd, price_known = llm_pricing.compute_cost(
            price, in_tokens, out_tokens)
        await conn_insert(
            pool,
            corr=(correlation_id or new_correlation_id()),
            module=str(module or "llm"),
            step=str(step or "single"),
            tool_name=str(tool_name or ""),
            source=normalize_source(source),
            chat_id=chat_id,
            model=str(model or ""),
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            tokens_estimated=bool(tokens_estimated),
            cost_usd=cost_usd,
            price_known=price_known,
        )
    except Exception:
        logger.warning(
            "[usage_events] record failed — fail-open | module=%s | step=%s",
            module, step, exc_info=True)
        return
    await maybe_cleanup(pool)


async def conn_insert(pool, *, corr, module, step, tool_name, source, chat_id,
                      model, input_tokens, output_tokens, tokens_estimated,
                      cost_usd, price_known) -> None:
    """Низкоуровневый INSERT (вынесен для читаемости/тестируемости)."""
    async with pool.acquire() as conn:
        await conn.execute(
            INSERT_SQL, corr, module, step, tool_name, source, chat_id, model,
            int(input_tokens), int(output_tokens), bool(tokens_estimated),
            float(cost_usd), bool(price_known))


async def maybe_cleanup(pool, *, force: bool = False) -> bool:
    """Opportunistic-очистка старых событий (ретенция). Возвращает факт DELETE.

    Дедуп: не чаще `CLEANUP_INTERVAL_SECONDS` (если `force=False`). Fail-open:
    ошибка удаления не влияет на запись/ответ.
    """
    global _last_cleanup
    now = time.monotonic()
    if not force and (now - _last_cleanup) < CLEANUP_INTERVAL_SECONDS:
        return False
    _last_cleanup = now
    try:
        async with pool.acquire() as conn:
            await conn.execute(DELETE_SQL, retention_days())
        return True
    except Exception:
        logger.warning("[usage_events] retention cleanup failed — fail-open",
                       exc_info=True)
        return False


def reset_cleanup_state() -> None:
    """Сброс дедупа очистки (для тестов/детерминизма)."""
    global _last_cleanup
    _last_cleanup = 0.0
