"""Раунд 10 (feature-gates-worker-budget, F-10 §5) — суточный бюджет фона.

`worker_budget (day DATE, scope 'global'|'chat:<id>', metric 'llm_calls'|
'llm_tokens', used, PK(day, scope, metric))` — единственный источник правды
PG (SQLite-воркеры пишут через runtime PgDatabase). День — WORKER_BUDGET_TZ
(Asia/Yekaterinburg). Лимиты — REGISTRY limits.worker_daily_* (горячие),
резолв per-chat (`chat_params.overrides` → глобальный слой → env-дефолт;
ADR-1018-7 D1). Sentinel-семантика бюджета (ADR-1019-8 §D2): `0 = запрет`,
`<0 = безлимит` (расход пишется, cap не применяется), `>0 = cap`
(`services/budget_limits.py`).
Деградация: global-исчерпание → скип тика воркера по priority_order
(сначала dream, потом lore, последней nostalgia); per-chat — скип чата.
Fail-open: PG down → consume()=True (воркеры НЕ останавливаются) + WARNING
с дедупом. Jitter тиков ≤ interval/3.
"""
import datetime
import logging

from zoneinfo import ZoneInfo

from config.settings import settings
from services import budget_gate
from services import budget_limits
from services import hot_config as hot

logger = logging.getLogger(__name__)

METRIC_CALLS = "llm_calls"
METRIC_TOKENS = "llm_tokens"
# Раунд 10.23 (F5, ADR-1023-5 §D4): платный вызов генерации изображения
# индексируется вызовами (не токенами). Хотфикс-5 (round10.25): отдельная
# env-only ветка лимита (`WORKER_DAILY_IMAGE_CALLS_PER_CHAT/GLOBAL`), чтобы
# обложка саммари не конкурировала за общий дневной лимит LLM чата; новых
# каталоговых ключей нет (Δ каталога = 0).
METRIC_IMAGE_CALLS = "image_calls"

LIMIT_CALLS_GLOBAL = "limits.worker_daily_llm_calls_global"
LIMIT_TOKENS_GLOBAL = "limits.worker_daily_llm_tokens_global"
LIMIT_CALLS_PER_CHAT = "limits.worker_daily_llm_calls_per_chat"
LIMIT_TOKENS_PER_CHAT = "limits.worker_daily_llm_tokens_per_chat"
# A5 (ADR-1026-17 D4): «глобальный дневной лимит изображений» = значение по
# умолчанию для per-chat лимита (каталог, наследование chat → global → env);
# НЕ смешивается с shared-квотой `WORKER_DAILY_IMAGE_CALLS_GLOBAL` (env-only).
LIMIT_IMAGE_DAILY = "limits.image_daily_limit"
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
# A5 (ADR-1026-17 D2): УСЛОВНЫЙ атомарный резерв — инкремент выполняется
# ТОЛЬКО если used < limit (`WHERE worker_budget.used < $4`); при исчерпании
# RETURNING пуст → отказ БЕЗ расхода квоты (check-after-increment-гонка/
# утечка baseline устранены). amount строго 1 (§28: 1 результат = 1 генерация).
RESERVE_INCREMENT_SQL = (
    "INSERT INTO worker_budget (day, scope, metric, used) "
    "VALUES ($1, $2, $3, 1) "
    "ON CONFLICT (day, scope, metric) DO UPDATE "
    "SET used = worker_budget.used + 1, updated_at = now() "
    "WHERE worker_budget.used < $4 "
    "RETURNING used"
)
# A5 (D7): откат ONE резерва при release (без ниже нуля; аддитивный апсерт
# гарантирует существование строки, GREATEST не даёт уйти в минус).
# INSERT-ветка кладёт 0 (release без prior-reserve НЕ создаёт расход —
# defensive; рабочий путь всегда UPDATE после резерва).
RESERVE_RELEASE_SQL = (
    "INSERT INTO worker_budget (day, scope, metric, used) "
    "VALUES ($1, $2, $3, 0) "
    "ON CONFLICT (day, scope, metric) DO UPDATE "
    "SET used = GREATEST(worker_budget.used - 1, 0), updated_at = now() "
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

# ── A5 (ADR-1026-17 D1/D3): журнал резервов изображений (ledger в PG) ────────
# reservation_key — PK/UNIQUE idem-ключ `{chat_id}:{message_id}:{source}`;
# status ∈ reserved/committed/released/denied; R17: только id/коды/числа.
RESERVATION_INSERT_SQL = (
    "INSERT INTO image_reservation "
    "(reservation_key, chat_id, source, message_id, day, status) "
    "VALUES ($1, $2, $3, $4, $5, 'reserved') "
    "ON CONFLICT (reservation_key) DO NOTHING "
    "RETURNING reservation_key"
)
RESERVATION_SELECT_SQL = (
    "SELECT status, error_code FROM image_reservation "
    "WHERE reservation_key = $1"
)
# A5 (D7): release читает journaled-день/chat/created_at — точный откат того же
# дня, что и резерв (защита от смены суток между reserve и release).
RESERVATION_RELEASE_SELECT_SQL = (
    "SELECT status, day, chat_id, created_at FROM image_reservation "
    "WHERE reservation_key = $1"
)
RESERVATION_STATUS_SQL = (
    "UPDATE image_reservation "
    "SET status = $2, error_code = $3, updated_at = now() "
    "WHERE reservation_key = $1"
)
# A5 (D7): release — только из terminal-safe 'reserved' (иначе НЕ откатываем
# счётчики: двойной release/после commit запрещены — идемпотентность D3).
RESERVATION_RELEASE_SQL = (
    "UPDATE image_reservation "
    "SET status = 'released', error_code = $2, updated_at = now() "
    "WHERE reservation_key = $1 AND status = 'reserved' "
    "RETURNING reservation_key"
)
# A5 (D7): commit — только из 'reserved'/'committed' (denied/released не
# «воскрешаются» в committed; повторный commit (delivery_failed) разрешён).
RESERVATION_DELIVERY_SQL = (
    "UPDATE image_reservation "
    "SET status = $2, delivery_failed = $3, updated_at = now() "
    "WHERE reservation_key = $1 AND status IN ('reserved', 'committed')"
)
# Усечение журнала: строки старше N дней (retention D3; day < cutoff).
RESERVATION_PURGE_SQL = (
    "DELETE FROM image_reservation WHERE day < $1"
)
# Агрегаты §28 (SC-A5-07) ИЗ ЖУРНАЛА — не второй счётчик: статусы дня чата.
RESERVATION_DAY_SQL = (
    "SELECT status, COUNT(*) AS n, "
    "COALESCE(SUM(CASE WHEN delivery_failed THEN 1 ELSE 0 END), 0) AS df "
    "FROM image_reservation WHERE chat_id = $1 AND day = $2 "
    "GROUP BY status"
)
SELECT_ROW_SQL = (
    "SELECT day, scope, metric, used FROM worker_budget "
    "WHERE day = $1 AND scope = $2 AND metric = $3"
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
    функция — тестируется без PG.

    Sentinel-бюджета (ADR-1019-8 §D2): `0` = запрет (все падают),
    `<0` = безлимит (все живы), `>0` = cap (матрица деградации)."""
    if budget_limits.is_forbidden(limit_calls):
        return {wid: False for wid in worker_ids}
    if budget_limits.is_unlimited(limit_calls):
        return {wid: True for wid in worker_ids}
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
    PG/строка недоступна → True (воркеры не останавливаются, §1-4).

    F21 (ADR-1024-22 D4): master-рубильник бюджетов приоритетен — при OFF
    (`flags.budgets_enabled=false`, скоп `global`) фон не ограничивается
    совсем: возвращаем True ДО чтения usage, чтобы предохранитель деградации
    не скипал тики. Fail-open ON: ошибка резолва флага → деградация как
    прежде."""
    if not await budget_gate.budgets_enabled(None):
        return True
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
    """Атомарный апсерт счётчика. False = лимит превышен или запрещён (`0`);
    `<0` = безлимит (расход пишется, cap не применяется); PG down → True
    (fail-open: воркер не останавливается) + WARNING с дедупом.
    `scope` — 'global' | 'chat:<id>'. pg=None → runtime-PG."""
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
    # F21 (ADR-1024-22 §D4): UPSERT уже выполнен (учёт всегда ведётся) —
    # master OFF ниже снимает только enforcement (лимит не применяется,
    # `_metric_limit` при OFF не вызывается).
    if not await budget_gate.budgets_enabled(_scope_chat_id(scope)):
        return True
    limit = await _metric_limit(scope, metric)
    if budget_limits.is_forbidden(limit):
        return False                       # 0 = расход запрещён
    if budget_limits.is_unlimited(limit):
        return True                        # <0 = безлимит (учёт уже записан)
    return used <= limit


def _scope_chat_id(scope: str | None) -> int | None:
    """chat_id из scope `'chat:<id>'`; global/мусор → None (глобальный слой)."""
    if not scope or not str(scope).startswith("chat:"):
        return None
    try:
        return int(str(scope).split(":", 1)[1])
    except (TypeError, ValueError):
        return None


async def _resolve_limit(key: str, *, chat_id: int | None, default: int) -> int:
    """Лимит per-chat (`overrides` → global → env-дефолт; ADR-1018-7 D1).

    Sentinel-значения (`0`/`<0`) проходят как есть — семантику применяет
    `budget_limits` (ADR-1019-8 §D2). Fail-open: ошибка резолва/каста →
    env-дефолт (воркеры не встают)."""
    try:
        from services.worker_settings import resolve_setting_cached
        value = await resolve_setting_cached(key, chat_id=chat_id,
                                             default=default)
        return int(value)
    except (TypeError, ValueError):
        _warn_once(f"cast:{key}", f"limit cast failed — default | key={key}")
        return int(default)
    except Exception:
        _warn_once(f"resolve:{key}",
                   f"limit resolve failed — default | key={key}")
        return int(default)


async def _metric_limit(scope: str, metric: str) -> int:
    """Суточный лимит метрики (per-chat для scope `'chat:<id>'`).

    Sentinel (ADR-1019-8 §D2): `0` = запрет, `<0` = безлимит, `>0` = cap.

    Хотфикс-5: `image_calls` получил СОБСТВЕННУЮ env-only ветку (Δ каталога = 0) —
    прежде реюзал `limits.worker_daily_llm_calls_*` и обложка саммари могла не
    создаться (`reason=budget`) из-за общего лимита чата."""
    chat_id = _scope_chat_id(scope)
    if metric == METRIC_IMAGE_CALLS:
        global_env = getattr(settings, "WORKER_DAILY_IMAGE_CALLS_GLOBAL", 200)
        if scope == "global":
            # Shared-квота остаётся env-only (не смешивается с дефолтом, §30).
            try:
                return int(global_env)
            except (TypeError, ValueError):
                return 200
        # A5 (ADR-1026-17 D4, gap §26/§30 fix): per-chat лимит резолвится
        # через каталожный ключ `limits.image_daily_limit` (chat → global →
        # env-дефолт `WORKER_DAILY_IMAGE_CALLS_PER_CHAT`); sentinel
        # `0`/<0`/>0` сохранён. Отсутствие ключа → env-дефолт (совместимость
        # baseline hotfix-5); ошибка резолва → env-дефолт (fail-open).
        default = getattr(settings, "WORKER_DAILY_IMAGE_CALLS_PER_CHAT", 60)
        return await _resolve_limit(LIMIT_IMAGE_DAILY, chat_id=chat_id,
                                    default=default)
    if metric == METRIC_CALLS:
        if scope == "global":
            key, default = LIMIT_CALLS_GLOBAL, \
                settings.WORKER_DAILY_LLM_CALLS_GLOBAL
        else:
            key, default = LIMIT_CALLS_PER_CHAT, \
                settings.WORKER_DAILY_LLM_CALLS_PER_CHAT
    elif scope == "global":
        key, default = LIMIT_TOKENS_GLOBAL, \
            settings.WORKER_DAILY_LLM_TOKENS_GLOBAL
    else:
        key, default = LIMIT_TOKENS_PER_CHAT, \
            settings.WORKER_DAILY_LLM_TOKENS_PER_CHAT
    return await _resolve_limit(key, chat_id=chat_id, default=default)


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
            "limit": await _metric_limit(r["scope"], r["metric"]),
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
    async def _pair(m: str) -> dict:
        u = global_usages.get(m)
        return {"used": u["used"] if u else 0,
                "limit": await _metric_limit("global", m)}
    chat_entries = []
    for scope, metrics in sorted(chats.items()):
        chat_id = _scope_chat_id(scope)
        # A5 (spec §6.3/D5/D9, R16-аддитивно): image-врезка UI §27 —
        # источник/день/время сброса для метрики image_calls.
        image_meta = await _image_meta_safe(chat_id)
        # A5 (T-3603/R16-аддитивно): §28-агрегаты и shared-строка UI —
        # из журнала `image_reservation` (не второй счётчик, D6).
        image_usage = await image_usage_summary(pg, chat_id)
        chat_entries.append({
            "scope": scope,
            "calls": {"used": metrics.get(METRIC_CALLS, {}).get("used", 0),
                      "limit": await _metric_limit(scope, METRIC_CALLS)},
            "tokens": {"used": metrics.get(METRIC_TOKENS, {}).get("used", 0),
                       "limit": await _metric_limit(scope, METRIC_TOKENS)},
            # Раунд 10.23 (F5, review iter1 Finding 8): виден расход на
            # генерацию изображений (метрика image_calls).
            "image_calls": {
                "used": metrics.get(METRIC_IMAGE_CALLS, {}).get("used", 0),
                "limit": await _metric_limit(scope, METRIC_IMAGE_CALLS),
                **image_meta},
            "image_usage": image_usage,
        })
    out = {
        "day": str(today()),
        "timezone": DAY_TZ,
        "global": {"calls": await _pair(METRIC_CALLS),
                   "tokens": await _pair(METRIC_TOKENS),
                   # A5 (spec §6.3, D5/R16): аддитивные day/timezone/
                   # next_reset_at/source для image_calls (shared-бюджет —
                   # WORKER_BUDGET_TZ; source='env' — env-only, D4).
                   "image_calls": {
                       **await _pair(METRIC_IMAGE_CALLS),
                       "day": str(today()),
                       "timezone": DAY_TZ,
                       "next_reset_at": image_next_reset(None).isoformat(),
                       "source": "env",
                   }},
        "chats": chat_entries,
        "priorities": list(_priority_order()),
    }
    return out


# ── A5 (ADR-1026-17 D4/D5/D2/D3/D6/D7/D8) — резерв/журнал/учёт ───────────────

import dataclasses  # noqa: E402 — a5-секция модуля (аддитивно)


@dataclasses.dataclass(frozen=True)
class ImageReserveResult:
    """Исход атомарного резерва изображения (spec §6.2, ADR-1026-17 D2/D3).

    * ``ok`` — True = резерв выполнен (либо replay уже committed/reserved
      ключа), False = отказ (лимит / replay прежнего отказа).
      Fail-open PG-down возвращает ok=True reason='failopen'.
    * ``reason`` — ``ok`` | ``already`` | ``limit_global`` | ``limit_chat``
      | ``failopen``.
    * ``status`` — статус строки журнала: reserved/committed/released/denied
      ('' при failopen — журнал не писался).
    * ``error_code`` — journaled-код прежнего отказа при replay
      (released/denied); иначе ``""``."""

    ok: bool
    reason: str
    status: str = ""
    error_code: str = ""


def _chat_tz_name(chat_id: int | None) -> str:
    """Раунд 10.26 (A5/D5): имя tz чата — прецедент `_chat_timezone`
    (tool_router.py:1480–1500): per-chat override `limits.chat_timezone` из
    НЕДОРОГОГО in-memory слоя ChatParamsCache (setting_source-семантика) →
    global `CHAT_TIMEZONE` → fallback `limits.summary_timezone`/
    `SUMMARY_TIMEZONE`; невалидное → UTC через `resolve_timezone` (reuse).
    Синхронный best-effort: рассинхрон с PG-слоем возможен в окне TTL (120с)
    кэша — документировано (evidence Q-A5-01)."""
    from services.canonical_context import resolve_timezone
    fallback = str(hot.get("limits.summary_timezone",
                           getattr(settings, "SUMMARY_TIMEZONE", "")) or "")
    global_tz = str(hot.get("limits.chat_timezone",
                            getattr(settings, "CHAT_TIMEZONE", "")) or "")
    tz = global_tz
    if chat_id is not None:
        try:
            from services.chat_params import get_chat_params_cache
            cache = get_chat_params_cache()
            items = getattr(cache, "_items", None) if cache is not None \
                else None
            entry = items.get(int(chat_id)) if isinstance(items, dict) \
                else None
            root = entry[1] if entry is not None else None
            override = (root or {}).get("overrides", {}).get(
                "limits.chat_timezone")
            if override:
                tz = str(override)
        except Exception:
            tz = global_tz
    return resolve_timezone(tz, fallback=fallback or "UTC")


def image_day(chat_id: int | None) -> datetime.date:
    """Календарный день лимита изображений (D5): chat:<id> — в TZ чата;
    global — в WORKER_BUDGET_TZ (`today()`). НЕ «24 ч от первого запроса»."""
    tz_name = _chat_tz_name(chat_id) if chat_id is not None else DAY_TZ
    try:
        return datetime.datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return datetime.date.today()


def image_timezone(chat_id: int | None) -> str:
    """Имя tz дневного дня (chat → WORKER_BUDGET_TZ) — для UI §27."""
    return _chat_tz_name(chat_id) if chat_id is not None else DAY_TZ


def image_next_reset(chat_id: int | None) -> datetime.datetime:
    """Точное время следующего сброса: следующая полуночь дня (0:00) в
    актуальной tz (§31, «показывать точное время следующего сброса»)."""
    tz_name = image_timezone(chat_id)
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = datetime.timezone.utc
    now = datetime.datetime.now(zone)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    nxt = start + datetime.timedelta(days=1)
    try:
        return nxt.astimezone(zone)
    except Exception:  # pragma: no cover — DST-edge fallback
        return now


def _retention_days() -> int:
    try:
        return max(1, int(getattr(settings,
                                  "IMAGE_RESERVATION_RETENTION_DAYS", 30)))
    except (TypeError, ValueError):
        return 30


_last_purge_day: str = ""


async def _maybe_purge_reservations(pool) -> None:
    """Opportunistic-purge журнала ≤1/сутки/процесс (D3 retention 30д).
    Best-effort: сбой disable освещается (fail-open), не роняет reserve."""
    global _last_purge_day
    marker = str(today())
    if _last_purge_day == marker:
        return
    _last_purge_day = marker
    try:
        cutoff = today() - datetime.timedelta(days=_retention_days())
        async with pool.acquire() as conn:
            await conn.execute(RESERVATION_PURGE_SQL, cutoff)
    except Exception:
        logger.debug("[worker_budget] reservation purge skipped (fail-open)")


async def reserve_image(pg, *, chat_id: int | None, idem_key: str, source: str,
                        message_id=None) -> ImageReserveResult:
    """Атомарный резерв одной генерации изображения (ADR-1026-17 D2/D3).

    ОДНА транзакция PG: (i) INSERT idem-строки журнала (PK reservation_key);
    (ii) условный инкремент shared-бюджета (scope='global'); (iii) условный
    инкремент per-chat (`scope='chat:<id>'`). Резерв проходит, только если
    ОБА контура под капом (или безлимит `<0`); forbidden `0` — отказ без
    записи. Отказ per-chat откатывает shared-инкремент (та же транзакция —
    нет частичного расхода, requirement D8). Отказ по лимиту НЕ расходует
    квоту (SC-A5-01); при остатке 1 ровно один из двух параллельных
    резервов проходит (SC-A5-04, серверная атомарность — client-side
    счётчик НЕ источник истины). Replay {возможно} уже существующего ключа
    возвращает прежний исход и НЕ списывает квоту повторно (SC-A5-02).
    Fail-open: нет pool/ошибка PG → ok=True reason='failopen' + честный
    WARNING с дедупом (паритет baseline, транзакция исключает частичный расход)."""
    if not idem_key:
        idem_key = f"{chat_id}:{message_id}:{source}"
    pool = await _pool(pg)
    if pool is None:
        _warn_once("reserve_nopool", "PG down — fail-open reserve=True | "
                                     f"scope=chat:{chat_id} "
                                     f"metric={METRIC_IMAGE_CALLS}")
        return ImageReserveResult(ok=True, reason="failopen", status="")
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Master-рубильник бюджетов — инвариант D8 (учёт вне скопа
                # reserve не ведётся; legacy consume даёт идентичный результат).
                if not await budget_gate.budgets_enabled(chat_id
                                                         and int(chat_id)
                                                         or None):
                    return ImageReserveResult(ok=True, reason="ok",
                                              status="")
                # A5/D5: ДЕНЬ SHARED-бюджета = today() (WORKER_BUDGET_TZ) —
                # НЕ день чата (иначе shared-счётчик фрагментируется по TZ
                # чатов и release (today()) откатывает другой день). День
                # per-chat и journaled-day = календарный день чата (D5).
                shared_day = today()
                chat_day = image_day(chat_id) if chat_id is not None \
                    else shared_day
                row = await conn.fetchrow(RESERVATION_INSERT_SQL, idem_key,
                                          chat_id, source, message_id, chat_day)
                if row is None:
                    # Replay: ключ уже существует → прежний исход (D3).
                    prev = await conn.fetchrow(RESERVATION_SELECT_SQL,
                                               idem_key)
                    prev_status = str(prev["status"]) if prev else "reserved"
                    prev_error = str(prev["error_code"]) if prev else ""
                    # committed/reserved → ok (already); released/denied →
                    # прежний отказ (без повторного списания).
                    return ImageReserveResult(
                        ok=prev_status in ("committed", "reserved"),
                        reason="already", status=prev_status,
                        error_code=prev_error)
                # Shared-бюджет: 0=запрет / <0=безлимит / >0=cap (sentinel).
                shared_limit = await _metric_limit("global",
                                                   METRIC_IMAGE_CALLS)
                shared_row = None
                if budget_limits.is_forbidden(shared_limit):
                    await conn.execute(RESERVATION_STATUS_SQL, idem_key,
                                       "denied", "limit_global")
                    return ImageReserveResult(ok=False,
                                              reason="limit_global",
                                              status="denied")
                if budget_limits.is_unlimited(shared_limit):
                    shared_row = await conn.fetchrow(UPSERT_SQL, shared_day,
                                                     "global",
                                                     METRIC_IMAGE_CALLS, 1)
                else:
                    shared_row = await conn.fetchrow(
                        RESERVE_INCREMENT_SQL, shared_day, "global",
                        METRIC_IMAGE_CALLS, int(shared_limit))
                if shared_row is None:
                    await conn.execute(RESERVATION_STATUS_SQL, idem_key,
                                       "denied", "limit_global")
                    return ImageReserveResult(ok=False,
                                              reason="limit_global",
                                              status="denied")
                if chat_id is None:
                    return ImageReserveResult(ok=True, reason="ok",
                                              status="reserved")
                chat_limit = await _metric_limit(
                    f"chat:{int(chat_id)}", METRIC_IMAGE_CALLS)
                if budget_limits.is_forbidden(chat_limit):
                    # D2: отказ per-chat → откат shared-инкремента В ТОЙ ЖЕ
                    # транзакции (иначе утечка shared-квоты baseline) +
                    # status='denied'.
                    await conn.execute(RESERVE_RELEASE_SQL, shared_day,
                                       "global", METRIC_IMAGE_CALLS)
                    await conn.execute(RESERVATION_STATUS_SQL, idem_key,
                                       "denied", "limit_chat")
                    return ImageReserveResult(ok=False,
                                              reason="limit_chat",
                                              status="denied")
                if not budget_limits.is_unlimited(chat_limit):
                    crow = await conn.fetchrow(
                        RESERVE_INCREMENT_SQL, chat_day,
                        f"chat:{int(chat_id)}", METRIC_IMAGE_CALLS,
                        int(chat_limit))
                    if crow is None:
                        # Лимит чата исчерпан: журналируем denied, откатываем
                        # shared-инкремент (D2 «без частичного расхода») —
                        # return из async with = COMMIT, поэтому откат явный.
                        await conn.execute(RESERVE_RELEASE_SQL, shared_day,
                                           "global", METRIC_IMAGE_CALLS)
                        await conn.execute(RESERVATION_STATUS_SQL, idem_key,
                                           "denied", "limit_chat")
                        return ImageReserveResult(ok=False,
                                                  reason="limit_chat",
                                                  status="denied")
        await _maybe_purge_reservations(pool)
        return ImageReserveResult(ok=True, reason="ok", status="reserved")
    except Exception:
        # D8: fail-open паритет baseline; транзакция целиком откатилась —
        # НЕТ частичного расхода и НЕТ журнала (документированный tradeoff).
        _warn_once("reserve_err",
                   f"reserve failed — fail-open=True | "
                   f"scope=chat:{chat_id} metric={METRIC_IMAGE_CALLS}")
        return ImageReserveResult(ok=True, reason="failopen", status="")


async def commit_image(pg, idem_key: str, *, delivery_failed: bool = False) \
        -> None:
    """Успех генерации → расход ПРЕДВАРИТЕЛЬНО резервируемого времени
    сохраняется (D7). Порядок: commit ДО отправки (§28: расход уже состоялся,
    даже если доставка сломается — тогда ставится флаг delivery_failed).
    Best-effort: ошибка PG не роняет чат (R17-лог)."""
    pool = await _pool(pg)
    if pool is None or not idem_key:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(RESERVATION_DELIVERY_SQL, idem_key,
                               "committed", bool(delivery_failed))
    except Exception:
        logger.warning("[worker_budget] commit_image failed (fail-open) | "
                       "reason=%s", "delivery_failed" if delivery_failed
                       else "commit")


async def release_image(pg, idem_key: str,
                        *, error_code: str = "generation_failed",
                        chat_id: int | None = None) -> None:
    """Сбой генерации (результат не создан) → резерв освобождается и квота
    возвращается в рамках одной транзакции (D7): shared + chat откатываются
    на 1 (не ниже 0, GREATEST), статус = released. Best-effort (fail-open).

    A5/D7-идемпотентность: откат выполняется ТОЛЬКО при переходе
    ``reserved → released`` (guard в SQL + RETURNING) — двойной release или
    release после commit НЕ трогают счётчики. День/chat берутся из ЖУРНАЛА
    строки резерва ( journaled-day = день чата на момент резерва; shared-день
    — из ``created_at`` в WORKER_BUDGET_TZ) — откат всегда попадает в тот же
    день, что и инкремент, даже при смене суток между reserve и release.
    ``chat_id`` — fallback, если journaled chat_id пуст."""
    pool = await _pool(pg)
    if pool is None or not idem_key:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                info = await conn.fetchrow(RESERVATION_RELEASE_SELECT_SQL,
                                           idem_key)
                if info is None:
                    return                    # строки нет — нечего откатывать
                claimed = await conn.fetchrow(
                    RESERVATION_RELEASE_SQL, idem_key,
                    str(error_code or "")[:64])
                if claimed is None:
                    return                    # уже released/committed/denied
                journaled_day = info["day"]
                j_chat = info["chat_id"]
                created = info["created_at"]
                # shared-день = день резерва в WORKER_BUDGET_TZ (D5).
                try:
                    shared_day = (created if created.tzinfo else
                                  created.replace(
                                      tzinfo=ZoneInfo(DAY_TZ))
                                  ).astimezone(ZoneInfo(DAY_TZ)).date()
                except Exception:
                    shared_day = today()
                await conn.execute(RESERVE_RELEASE_SQL, shared_day, "global",
                                   METRIC_IMAGE_CALLS)
                effective_chat = int(j_chat) if j_chat is not None \
                    else (int(chat_id) if chat_id is not None else None)
                if effective_chat is not None:
                    await conn.execute(RESERVE_RELEASE_SQL, journaled_day,
                                       f"chat:{effective_chat}",
                                       METRIC_IMAGE_CALLS)
    except Exception:
        logger.warning("[worker_budget] release_image failed (fail-open) | "
                       "metric=%s", METRIC_IMAGE_CALLS)


async def image_limits(chat_id: int | None) -> tuple[int, int, str]:
    """(shared_env_limit, per_chat_limit, per_chat_source) — контракт
    spec §6.2 (A5/D4): shared = env-only ``WORKER_DAILY_IMAGE_CALLS_GLOBAL``
    (НЕ смешивается с дефолтом), per-chat = каталожный
    ``limits.image_daily_limit`` (chat → global → env 60), source ∈
    chat/global/default. Sentinel сохраняется (0/<0/>0)."""
    shared = await _metric_limit("global", METRIC_IMAGE_CALLS)
    default = getattr(settings, "WORKER_DAILY_IMAGE_CALLS_PER_CHAT", 60)
    # Per-chat-слой: для chat_id — через каталог (D4); без чата — глобальный
    # слой каталога/дефолт (источник отличается, лимит-ключ тот же).
    per_chat = await _resolve_limit(LIMIT_IMAGE_DAILY, chat_id=chat_id,
                                    default=default)
    source = "default"
    try:
        from services.worker_settings import resolve_setting_with_source
        _v, source = await resolve_setting_with_source(
            LIMIT_IMAGE_DAILY, chat_id=chat_id, default=None)
    except Exception:
        source = "default"
    return int(shared), int(per_chat), str(source or "default")


async def image_usage_summary(pg, chat_id) -> dict:
    """Агрегаты §28 (SC-A5-07) ИЗ ЖУРНАЛА `image_reservation` + usage
    `worker_budget` (spec §6.2, D1/D6 — НЕ второй счётчик):
    {day, timezone, used, limit, source, next_reset_at, shared_used,
    shared_limit, requests, success, errors, denied, delivery_failed,
    expenses} (расходы = 'N/A' — провайдер не отдаёт стоимость,
    документировано; D6)."""
    chat_id = int(chat_id)
    day = image_day(chat_id)
    used = 0
    pool = await _pool(pg)
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(SELECT_ROW_SQL, day,
                                          f"chat:{chat_id}",
                                          METRIC_IMAGE_CALLS)
            used = int(row["used"]) if row else 0
        except Exception:
            used = 0
    meta = await _image_meta_safe(chat_id)
    summary = {
        "day": str(day),
        "timezone": image_timezone(chat_id),
        "used": used,
        "limit": await _metric_limit(f"chat:{chat_id}",
                                     METRIC_IMAGE_CALLS),
        "source": meta.get("source", "default"),
        "next_reset_at": image_next_reset(chat_id).isoformat(),
        "shared_used": None,
        "shared_limit": await _metric_limit("global", METRIC_IMAGE_CALLS),
        "requests": 0, "success": 0, "errors": 0, "denied": 0,
        "delivery_failed": 0,
        # §28 «фактические расходы, если доступны» — N/A (D6): провайдер
        # не отдаёт стоимость генерации.
        "expenses": "N/A",
    }
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(RESERVATION_DAY_SQL, chat_id, day)
                grow = await conn.fetchrow(SELECT_ROW_SQL, today(), "global",
                                           METRIC_IMAGE_CALLS)
            for r in rows or []:
                st = str(r["status"])
                n = int(r["n"])
                if st == "committed":
                    summary["success"] += n
                elif st == "released":
                    summary["errors"] += n
                elif st == "denied":
                    summary["denied"] += n
                # §28 «запросов» = ВСЕ резерв-попытки дня (включая denied —
                # отказ по лимиту тоже запрос); denied/успех/ошибки —
                # раздельные под-счётчики (D6).
                summary["requests"] += n
                summary["delivery_failed"] += int(r["df"] or 0)
            if grow is not None:
                summary["shared_used"] = int(grow["used"])
        except Exception:
            pass
    return summary


async def _image_meta_safe(chat_id: int | None) -> dict:
    """Аддитивные meta-поля image-врезки UI §27 (R16): day/timezone/
    next_reset_at/source. Fail-open: пустая карта (schema стабильна).
    Источник для UI — строго chat/global/default: при 'error' (chat-слой
    недоступен, fail-open значение) честно перерезолвиваем глобальный слой
    (тот же value-фолбэк), чтобы не показывать служебный 'error'."""
    try:
        from services.worker_settings import resolve_setting_with_source
        _value, source = await resolve_setting_with_source(
            LIMIT_IMAGE_DAILY, chat_id=chat_id, default=None)
        if source not in ("chat", "global", "default"):
            # chat-слой fail-open: значение уже из global/default-ветки —
            # уточняем истинный источник без chat-слоя.
            _v2, source = await resolve_setting_with_source(
                LIMIT_IMAGE_DAILY, chat_id=None, default=None)
            if source not in ("global", "default"):
                source = "default"
        return {"source": source, "day": str(image_day(chat_id)),
                "timezone": image_timezone(chat_id),
                "next_reset_at": image_next_reset(chat_id).isoformat()}
    except Exception:
        return {}


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
