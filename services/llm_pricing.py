"""F7 (раунд 10.23, ADR-1023-7 D3) — цены моделей и расчёт `cost_usd`.

Таблица цен `llm_model_prices` живёт в PG (её владелец — `services/pg_db.py`,
DDL/сид). Здесь — только чтение с in-process TTL-кэшем и чистая функция
расчёта стоимости.

Контракт (D3):
* `resolve_price(pg, model)` → `(input_usd_per_1m, output_usd_per_1m) | None`;
* `compute_cost(price, input_tokens, output_tokens)` → `(cost_usd, known)`;
* **fail-safe:** нет цены/нет строки/ошибка чтения → `None` → `cost_usd=0`,
  `price_known=false` (цену не выдумываем и не падаем);
* `invalidate(model=None)` — сброс кэша (после правки таблицы цен).

R17: только числа; ни ключей, ни промптов.
"""
import logging
import time

logger = logging.getLogger(__name__)

# In-process кэш: model -> ((in_price, out_price), monotonic_ts).
# TTL ограничивает «залипание» значений при правке таблицы из админки.
PRICE_CACHE_TTL_SECONDS = 300.0
_CACHE: dict[str, tuple[tuple[float, float], float]] = {}

SELECT_PRICE_SQL = (
    "SELECT input_usd_per_1m, output_usd_per_1m "
    "FROM llm_model_prices WHERE model = $1"
)


def invalidate(model: str | None = None) -> None:
    """Сброс кэша цен: конкретная модель либо весь кэш."""
    if model is None:
        _CACHE.clear()
    else:
        _CACHE.pop(str(model), None)


def _pool(pg):
    return getattr(pg, "pool", None) if pg is not None else None


def _as_float(value) -> float:
    """NUMERIC/Decimal/str → float; мусор → 0.0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def resolve_price(pg, model: str) -> tuple[float, float] | None:
    """Цена модели (USD за 1M токенов) или ``None`` (цены нет).

    Fail-safe (fail-open): PG недоступен/ошибка/пустая модель → ``None``.
    Значения кэшируются на `PRICE_CACHE_TTL_SECONDS`.
    """
    key = str(model or "").strip()
    if not key:
        return None
    cached = _CACHE.get(key)
    now = time.monotonic()
    if cached is not None and (now - cached[1]) < PRICE_CACHE_TTL_SECONDS:
        return cached[0]
    pool = _pool(pg)
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(SELECT_PRICE_SQL, key)
    except Exception:
        logger.warning("[llm_pricing] price read failed — fail-safe none | "
                       "model=%s", key, exc_info=True)
        return None
    if row is None:
        return None
    price = (_as_float(row["input_usd_per_1m"]),
             _as_float(row["output_usd_per_1m"]))
    _CACHE[key] = (price, now)
    return price


def compute_cost(price: tuple[float, float] | None,
                 input_tokens: int, output_tokens: int) -> tuple[float, bool]:
    """Стоимость вызова USD и флаг «цена известна».

    Формула: ``input/1e6*in_price + output/1e6*out_price`` (ADR-1023-7).
    Нет цены → ``(0.0, False)`` — fail-safe, без выдумывания значения.
    Округление до 6 знаков (`NUMERIC(12,6)`).
    """
    if not price:
        return 0.0, False
    try:
        in_price, out_price = float(price[0]), float(price[1])
        cost = (max(0, int(input_tokens)) / 1_000_000.0) * in_price \
            + (max(0, int(output_tokens)) / 1_000_000.0) * out_price
    except (TypeError, ValueError, IndexError):
        return 0.0, False
    return round(cost, 6), True
