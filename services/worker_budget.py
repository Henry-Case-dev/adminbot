"""Раунд 10 (feature-gates-worker-budget, F-10 §5) — суточный бюджет фона.

`worker_budget (day DATE, scope 'global'|'chat:<id>', metric 'llm_calls'|
'llm_tokens', used, PK(day, scope, metric))` — единственный источник правды
PG (SQLite-воркеры пишут через runtime PgDatabase). День — WORKER_BUDGET_TZ
(Asia/Yekaterinburg). Лимиты — REGISTRY limits.worker_daily_* (горячие).
Деградация: global-исчерпание → скип тика воркера по priority_order
(сначала dream, потом lore, последней nostalgia); per-chat — скип чата.
Fail-open: PG down → consume()=True (воркеры НЕ останавливаются) + WARNING
с дедупом. Jitter тиков ≤ interval/3.
"""
import datetime
import logging

from zoneinfo import ZoneInfo

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

METRIC_CALLS = "llm_calls"
METRIC_TOKENS = "llm_tokens"

LIMIT_CALLS_GLOBAL = "limits.worker_daily_llm_calls_global"
LIMIT_TOKENS_GLOBAL = "limits.worker_daily_llm_tokens_global"
LIMIT_CALLS_PER_CHAT = "limits.worker_daily_llm_calls_per_chat"
LIMIT_TOKENS_PER_CHAT = "limits.worker_daily_llm_tokens_per_chat"
KEY_PRIORITY_ORDER = "limits.worker_priority_order"
KEY_JITTER = "limits.worker_budget_jitter_minutes"

DEFAULT_PRIORITY_ORDER = "nostalgia,lore,dream"   # первый падает первым
DEFAULT_JITTER_MINUTES = 5

# идентификаторы воркеров (для priority/деградации)
WORKER_NOSTALGIA = "nostalgia"
WORKER_LORE = "lore"
WORKER_DREAM = "dream"
# F3 (cognition-deep-sleep, spec §4): глубокий сон — самый дорогой и наименее
# критичный фон → в деградации падает ПЕРВЫМ (высший priority_of).
WORKER_DEEP_SLEEP = "deep_sleep"

WORKER_IDS: tuple[str, ...] = (WORKER_NOSTALGIA, WORKER_LORE, WORKER_DREAM,
                               WORKER_DEEP_SLEEP)

DAY_TZ = settings.WORKER_BUDGET_TZ or "Asia/Yekaterinburg"

UPSERT_SQL = (
    "INSERT INTO worker_budget (day, scope, metric, used) "
    "VALUES ($1, $2, $3, $4) "
    "ON CONFLICT (day, scope, metric) DO UPDATE "
    "SET used = worker_budget.used + EXCLUDED.used, updated_at = now() "
    "RETURNING used"
)
SELECT_SQL = (
    "SELECT day, scope, metric, used FROM worker_budget "
    "WHERE day = $1 AND scope = $2 ORDER BY metric"
)
SELECT_ALL_SQL = (
    "SELECT day, scope, metric, used FROM worker_budget "
    "WHERE day = $1 ORDER BY scope, metric"
)

_warning_dedup: set[str] = set()

# Runtime-PG (DI из bot.py): воркеры/API работают с ним без конструктора
# (сигнатуры сервисов НЕ меняем — прецедент hot_config.set_config_cache).
_runtime_pg = None


def set_worker_budget_pg(pg) -> None:
    global _runtime_pg
    _runtime_pg = pg


def _resolve_pg(pg):
    return pg if pg is not None else _runtime_pg


def today() -> datetime.date:
    try:
        return datetime.datetime.now(ZoneInfo(DAY_TZ)).date()
    except Exception:
        return datetime.date.today()


def _limit(key: str, default: int) -> int:
    try:
        return int(hot.get(key, default) or default)
    except Exception:
        return default


def _priority_order() -> tuple[str, ...]:
    raw = str(hot.get(KEY_PRIORITY_ORDER,
                      DEFAULT_PRIORITY_ORDER) or DEFAULT_PRIORITY_ORDER)
    order = []
    for token in str(raw).split(","):
        token = token.strip()
        if token in WORKER_IDS and token not in order:
            order.append(token)
    for wid in WORKER_IDS:
        if wid not in order:
            order.append(wid)
    return tuple(order)


def priority_of(worker_id: str) -> int:
    """0 = высший приоритет (последний падает), больший — падает раньше.
    Порядок по умолчанию: nostalgia(0) < lore(1) < dream(2)."""
    order = _priority_order()
    try:
        return order.index(worker_id)
    except ValueError:
        return len(order)


def workers_dropped(worker_ids: list[str]) -> list[str]:
    """Упорядоченный список деградации (первый — падает первым):
    обратный priority_order (по умолчанию: dream, lore, nostalgia)."""
    return sorted(set(worker_ids), key=priority_of, reverse=True)


def allowed_workers(worker_ids, used_calls: int, limit_calls: int) -> dict[str, bool]:
    """ФИКС R4 (F-10 §5.2): деградация при исчерпании global-лимита.
    Порядок падения — обратный priority_order по АБСОЛЮТНОЙ позиции
    (dream=0 → lore=1 → nostalgia=2): воркер выживает, пока
    used_calls < limit_calls + позиция_падения. Т.о. при used == limit
    падает dream; потом lore; последней nostalgia (у неё запас 1 тик).

    F3 (cognition-deep-sleep, spec §4): deep_sleep добавлен в WORKER_IDS и
    падает ПЕРВЫМ — на один тик раньше обычного «сна» (позиция -1), при этом
    НЕ сдвигая легаси-матрицу F-10 (dream=0/lore=1/nostalgia=2). Чистая
    функция — тестируется без PG."""
    absolute = {wid: i for i, wid in enumerate(
        workers_dropped([WORKER_NOSTALGIA, WORKER_LORE, WORKER_DREAM]))}
    # -1 → deep_sleep выпадает при used == limit - 1, когда dream ещё жив.
    absolute.setdefault(WORKER_DEEP_SLEEP, -1)
    out: dict[str, bool] = {}
    for wid in worker_ids:
        i = absolute.get(wid)
        if i is None:
            out[wid] = True
            continue
        out[wid] = used_calls < int(limit_calls) + i
    return out


async def global_degradation_allows(worker_id: str, pg=None) -> bool:
    """ФИКС R4: разрешён ли тик воркера текущим global-бюджетом
    (использует allowed_workers по фактическому used дня). Fail-open:
    PG/строка недоступна → True (воркеры не останавливаются, §1-4)."""
    try:
        rows = await get_usage(pg, scope="global")
    except Exception:
        _warn_once("deg", f"global usage недоступно — fail-open True | "
                          f"worker={worker_id}")
        return True
    row = next((r for r in rows if r["metric"] == METRIC_CALLS), None)
    if row is None:
        return True
    return bool(allowed_workers((worker_id,), row["used"], row["limit"])
                .get(worker_id, True))


def jitter_minutes() -> int:
    return max(0, int(_limit(KEY_JITTER, DEFAULT_JITTER_MINUTES)))


def jitter_active() -> bool:
    """Jitter применяется ТОЛЬКО при явно заданном ключе в кэше/БД
    (тесты без ключа — точные интервалы; прод с REGISTRY-сидом — да)."""
    try:
        return hot.get(KEY_JITTER, None) is not None
    except Exception:
        return False


async def _pool(pg):
    pg = _resolve_pg(pg)
    return getattr(pg, "pool", None) if pg is not None else None


async def consume(pg, scope: str, metric: str, amount: int = 1) -> bool:
    """Атомарный апсерт счётчика. False = лимит превышен (или лимит 0);
    PG down → True (fail-open: воркер не останавливается) + WARNING с
    дедупом. `scope` — 'global' | 'chat:<id>'. pg=None → runtime-PG."""
    if not metric:
        return True
    pool = await _pool(pg)
    if pool is None:
        _warn_once("nopool", f"PG down — fail-open consume=True | "
                             f"scope={scope} metric={metric}")
        return True
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(UPSERT_SQL, today(), scope, metric,
                                      max(0, int(amount)))
        used = int(row["used"]) if row else 0
    except Exception:
        _warn_once("err", f"consume failed — fail-open=True | scope={scope} "
                          f"metric={metric}")
        return True
    limit = _metric_limit(scope, metric)
    if limit <= 0:
        return False                       # лимит 0 = запрещено
    return used <= limit


def _metric_limit(scope: str, metric: str) -> int:
    if metric == METRIC_CALLS:
        if scope == "global":
            return _limit(LIMIT_CALLS_GLOBAL, 200)
        return _limit(LIMIT_CALLS_PER_CHAT, 35)
    if scope == "global":
        return _limit(LIMIT_TOKENS_GLOBAL, 500000)
    return _limit(LIMIT_TOKENS_PER_CHAT, 100000)


async def get_usage(pg=None, scope: str | None = None,
                    day: datetime.date | None = None) -> list[dict]:
    """Строки дня: {day, scope, metric, used, limit}. pg=None → runtime-PG."""
    pool = await _pool(pg)
    if pool is None:
        return []
    day = day or today()
    try:
        async with pool.acquire() as conn:
            if scope is None:
                rows = await conn.fetch(SELECT_ALL_SQL, day)
            else:
                rows = await conn.fetch(SELECT_SQL, day, scope)
    except Exception:
        return []
    out = []
    for r in rows:
        out.append({
            "day": str(r["day"]),
            "scope": r["scope"],
            "metric": r["metric"],
            "used": int(r["used"]),
            "limit": _metric_limit(r["scope"], r["metric"]),
        })
    return out


async def get_day_summary(pg=None) -> dict:
    """Для GET /api/workers/budget и F-12: {day, timezone, global, chats,
    priorities}."""
    rows = await get_usage(pg)
    global_usages = {}
    chats = {}
    for r in rows:
        if r["scope"] == "global":
            global_usages[r["metric"]] = r
        else:
            chats.setdefault(r["scope"], {})[r["metric"]] = r
    def _pair(m: str) -> dict:
        u = global_usages.get(m)
        return {"used": u["used"] if u else 0,
                "limit": _metric_limit("global", m)}
    out = {
        "day": str(today()),
        "timezone": DAY_TZ,
        "global": {"calls": _pair(METRIC_CALLS),
                   "tokens": _pair(METRIC_TOKENS)},
        "chats": [
            {"scope": scope,
             "calls": {"used": metrics.get(METRIC_CALLS, {}).get("used", 0),
                       "limit": _metric_limit(scope, METRIC_CALLS)},
             "tokens": {"used": metrics.get(METRIC_TOKENS, {}).get("used", 0),
                        "limit": _metric_limit(scope, METRIC_TOKENS)}}
            for scope, metrics in sorted(chats.items())
        ],
        "priorities": list(_priority_order()),
    }
    return out


def estimate_tokens(text: str | None) -> int:
    """Оценка токенов (len/4) — приблизительность README (§5.2)."""
    return max(1, len(text or "") // 4)


def _warn_once(key: str, message: str) -> None:
    if key in _warning_dedup:
        return
    if len(_warning_dedup) > 8:
        _warning_dedup.clear()
    _warning_dedup.add(key)
    logger.warning("[worker_budget] %s", message)


def jitter_safe(interval_minutes: int, jitter: int | None = None) -> int:
    """Jitter капится ≤ interval/3 (риск 10.4: шире интервала — частота
    падает в 2 раза)."""
    jitter = jitter_minutes() if jitter is None else jitter
    cap = max(0, int(interval_minutes) // 3)
    return min(max(0, int(jitter)), cap)
