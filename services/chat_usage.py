"""F2 (T-1854, ADR-1019-2 D1/D2/D4 + ADR-1019-8 D2) — бюджет глобального
ключа direct-чата: sentinel-семантика, per-chat резолв, диагностируемый снимок.

`chat_usage (chat_id, day DATE, metric, used, PK(chat_id, day, metric))`;
metric ∈ {'llm_calls','llm_tokens'}. Счётчик — в PG, на КОНЦЕ LLM-вызова
(1 вызов + фактические токены ответа, estimate len/4 — приблизительность
README-пометка), пред-проверка «used > limit → не тратить».

Лимиты — per-chat резолв `limits.chat_global_key_budget_*`:
    `chat_params.overrides` (каст по каталогу) → глобальный `hot.get` →
    env-дефолт `settings.CHAT_GLOBAL_KEY_BUDGET_*` (ADR-1018-7 D1).
До F2 читался **только** глобальный слой → per-chat override не работал.

Sentinel (`services/budget_limits.py`): `0` = запрет, `<0` = безлимит,
`>0` = cap. День — WORKER_BUDGET_TZ (единая таймзона раунда). Fail-open:
PG/резолв недоступны → бот жив, sandbox без доказанной причины не включается.
"""
import datetime
import logging
from zoneinfo import ZoneInfo

from config.settings import settings
from services import budget_limits

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


def _env_default(key: str) -> int:
    """Env-дефолт лимита (консервативный предохранитель, НЕ безлимит)."""
    if key == KEY_BUDGET_REQUESTS:
        return int(getattr(settings, "CHAT_GLOBAL_KEY_BUDGET_REQUESTS", 100))
    return int(getattr(settings, "CHAT_GLOBAL_KEY_BUDGET_TOKENS", 500000))


async def _limit_with_source(key: str, chat_id: int | None,
                             default: int | None = None) -> tuple[int, str]:
    """(limit, source) — per-chat резолв `chat → global → default`.

    `resolve_setting_with_source` — source-возвращающий двойник
    `worker_settings.resolve_setting_cached` (F7/ADR-1018-7 D1): обе функции
    идут через один `_resolve_full` (override чата с кастом по каталогу →
    глобальный слой → env-дефолт); отличается только debug-логом `_cached`.
    `chat_id=None` → только глобальный слой/дефолт. Fail-open: резолв/каст
    упал → env-дефолт, source='default' (бот жив)."""
    env_default = int(default) if default is not None else _env_default(key)
    try:
        from services.worker_settings import resolve_setting_with_source
        value, source = await resolve_setting_with_source(
            key, chat_id=chat_id, default=env_default)
        return int(value), source
    except (TypeError, ValueError):
        logger.warning("[chat_usage] limit cast failed — default | key=%s", key)
        return env_default, "default"
    except Exception:
        logger.warning("[chat_usage] limit resolve failed — default | key=%s",
                       key, exc_info=True)
        return env_default, "default"


async def _budget_limit_requests(chat_id: int | None = None,
                                 default: int | None = None) -> int:
    """Cap вызовов общего ключа для чата (per-chat резолв; `<0` = безлимит)."""
    value, _ = await _limit_with_source(KEY_BUDGET_REQUESTS, chat_id, default)
    return value


async def _budget_limit_tokens(chat_id: int | None = None,
                               default: int | None = None) -> int:
    """Cap токенов общего ключа для чата (per-chat резолв; `<0` = безлимит)."""
    value, _ = await _limit_with_source(KEY_BUDGET_TOKENS, chat_id, default)
    return value


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


def _exceeds(req_limit, tok_limit, used_calls, used_tokens,
             estimate: int = 0) -> str | None:
    """Что именно исчерпано: `'forbidden'|'calls'|'tokens'|None`.

    `0` (любая метрика) = запрет общего ключа чату → 'forbidden' (канон F-7).
    Отрицательный лимит = безлимит по метрике. Иначе — `used_calls >= cap`
    (calls) либо `used_tokens + estimate > cap` (tokens)."""
    if budget_limits.is_forbidden(req_limit) \
            or budget_limits.is_forbidden(tok_limit):
        return "forbidden"
    if not budget_limits.is_unlimited(req_limit) and used_calls >= req_limit:
        return "calls"
    if not budget_limits.is_unlimited(tok_limit) \
            and used_tokens + max(0, int(estimate)) > tok_limit:
        return "tokens"
    return None


_EXCEEDED_METRICS = ("forbidden", "calls", "tokens")


def _aggregate_source(exceeded_metric: str | None, req_source: str,
                      tok_source: str) -> str:
    """Один `source` для снимка: источник сработавшей метрики, иначе общий."""
    if exceeded_metric == "calls":
        return req_source
    if exceeded_metric == "tokens":
        return tok_source
    return req_source if req_source == tok_source else "mixed"


def _snapshot(*, day, exceeded, exceeded_metric, used_calls, used_tokens,
              limit_calls, limit_tokens, unlimited, forbidden, source,
              source_calls, source_tokens) -> dict:
    return {
        "day": str(day),
        "exceeded": bool(exceeded),
        "exceeded_metric": exceeded_metric,
        "used_calls": int(used_calls),
        "limit_calls": int(limit_calls),
        "used_tokens": int(used_tokens),
        "limit_tokens": int(limit_tokens),
        "unlimited": bool(unlimited),
        "forbidden": bool(forbidden),
        "source": source,
        "source_calls": source_calls,
        "source_tokens": source_tokens,
    }


async def budget_snapshot(pg, chat_id: int, tokens_estimate: int = 0) -> dict:
    """Единый снимок бюджета direct-чата (T-1793, ADR-1019-2 D4).

    Ключи: `exceeded`, `exceeded_metric` ('forbidden'|'calls'|'tokens'|None),
    `used_calls/limit_calls`, `used_tokens/limit_tokens`, `unlimited`,
    `forbidden`, `source` (+`source_calls`/`source_tokens`), `day`.

    **Инвариант диагностируемости:** `exceeded=True` подразумевает определённый
    `exceeded_metric` из допустимого набора; иначе — ERROR-лог и fail-open
    (`exceeded=False`) → `reason=budget` без доказанной метрики невозможен.
    Fail-open: резолв лимитов/чтение usage недоступны → `exceeded=False`
    (в sandbox без доказанной причины не уходим; `unlimited=False`)."""
    day = today()
    req_limit, req_source = await _limit_with_source(KEY_BUDGET_REQUESTS,
                                                     chat_id)
    tok_limit, tok_source = await _limit_with_source(KEY_BUDGET_TOKENS, chat_id)
    forbidden = (budget_limits.is_forbidden(req_limit)
                 or budget_limits.is_forbidden(tok_limit))
    unlimited = (budget_limits.is_unlimited(req_limit)
                 and budget_limits.is_unlimited(tok_limit))
    try:
        used = await used_today(pg, chat_id)
    except Exception:
        logger.warning("[chat_usage] usage read failed — fail-open | chat=%s",
                       chat_id, exc_info=True)
        used = None
    if used is None:
        # Fail-open (PG down): exceeded сбрасываем (в sandbox без доказанной
        # причины не уходим), но вычисленный `forbidden`/`source` сохраняем —
        # `0`-лимит виден независимо от доступности PG (снимок не противоречит
        # себе; D-4 ревью Батча B).
        return _snapshot(
            day=day, exceeded=False, exceeded_metric=None,
            used_calls=0, used_tokens=0, limit_calls=req_limit,
            limit_tokens=tok_limit, unlimited=False, forbidden=forbidden,
            source=_aggregate_source(None, req_source, tok_source),
            source_calls=req_source, source_tokens=tok_source)
    used_calls = int(used.get(METRIC_CALLS, 0))
    used_tokens = int(used.get(METRIC_TOKENS, 0))
    metric = _exceeds(req_limit, tok_limit, used_calls, used_tokens,
                      tokens_estimate)
    if metric is not None and metric not in _EXCEEDED_METRICS:
        # Внутренняя несогласованность: превышение без валидной метрики —
        # НЕ отправляем в sandbox (fail-open), но громко диагностируем.
        logger.error(
            "[chat_usage] inconsistent budget state | chat=%s | metric=%r | "
            "used_calls=%s/%s | used_tokens=%s/%s — fail-open",
            chat_id, metric, used_calls, req_limit, used_tokens, tok_limit)
        metric = None
    exceeded = metric is not None
    return _snapshot(
        day=day, exceeded=exceeded, exceeded_metric=metric,
        used_calls=used_calls, used_tokens=used_tokens, limit_calls=req_limit,
        limit_tokens=tok_limit, unlimited=unlimited, forbidden=forbidden,
        source=_aggregate_source(metric, req_source, tok_source),
        source_calls=req_source, source_tokens=tok_source)


async def budget_exceeded(pg, chat_id: int,
                          tokens_estimate: int = 0) -> bool:
    """Суточный бюджет исчерпан (или `0`-лимит = запрещён глобальный ключ).

    Обёртка над `budget_snapshot` — единый источник диагностики (T-1793)."""
    snapshot = await budget_snapshot(pg, chat_id, tokens_estimate)
    return bool(snapshot["exceeded"])


def estimate_tokens(text: str | None) -> int:
    """Оценка токенов вызова (len/4) — приблизительность README (§5.2)."""
    return max(1, len(text or "") // 4)


async def report_call(pg, chat_id: int, tokens: int = 0) -> None:
    """Конец LLM-вызова на глобальном ключе: 1 вызов + токены."""
    await register_usage(pg, chat_id, METRIC_CALLS, 1)
    if tokens > 0:
        await register_usage(pg, chat_id, METRIC_TOKENS, tokens)


async def key_status(pg, chat_id: int) -> dict:
    """Статусы для GET /api/config/keys/status (F-7 §6; R16-аддитивно:
    добавлены `unlimited`/`forbidden`/`source` на метрику)."""
    snapshot = await budget_snapshot(pg, chat_id)

    def _metric(used, limit, source):
        return {
            "used": int(used),
            "limit": int(limit),
            "unlimited": budget_limits.is_unlimited(limit),
            "forbidden": budget_limits.is_forbidden(limit),
            "source": source,
        }

    return {
        "calls": _metric(snapshot["used_calls"], snapshot["limit_calls"],
                         snapshot["source_calls"]),
        "tokens": _metric(snapshot["used_tokens"], snapshot["limit_tokens"],
                          snapshot["source_tokens"]),
    }
