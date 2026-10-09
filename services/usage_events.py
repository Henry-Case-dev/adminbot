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
import re
import time
import uuid

from config.settings import settings
from services import llm_pricing
from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

# source-домен (ADR-1023-7 D5) — только аналитика; бюджетный контур не трогаем.
# MCA-11 (ADR-1028-13 D4/AM-2, код-only): +embedding (точка записи — успешный
# `llm_client.embed`) и +media (при записи медиа-провайдеров; image уже пишет
# source='image' как раньше — существующие строки не переклассифицируются).
SOURCES = ("global", "chat", "byok", "worker", "image", "embedding", "media")

INSERT_SQL = (
    "INSERT INTO llm_usage_events "
    "(correlation_id, module, step, tool_name, source, chat_id, model, "
    " input_tokens, output_tokens, tokens_estimated, cost_usd, price_known, "
    " plan_meta) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)"
)
# ── ASAP 7 (F2, §1.10): R17-whitelist plan_meta (те же enum-оси L1, что в
# agentic-событии L1_PLAN: action/response_act/extent/tone/bucket/confidence/
# capabilities requested-resolved/inherited/fallback/latency/input_chars/
# model/source). Неизвестные ключи и «небезопасные» значения отбрасываются —
# свободный текст/промпты в durable-колонку не попадают (§1.10/R17).
PLAN_META_FIELDS = frozenset({
    "action", "response_act", "extent", "tone", "bucket", "confidence",
    "capabilities", "tools", "inherited", "fallback", "latency_ms",
    "input_chars", "model", "source",
})
_PLAN_META_LIST_FIELDS = frozenset({"capabilities", "tools"})
_PLAN_META_NUM_FIELDS = frozenset(
    {"confidence", "latency_ms", "input_chars"})
_IDENT_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-:.]{0,64}$")
_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-./:]{0,64}$")
_PLAN_META_MAX_BYTES = 2048   # bounded durable-колонка (одна строка JSON)
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


def cost_accounting_enabled() -> bool:
    """K3 ``MCA_COST_ACCOUNTING_ENABLED`` (env-only, default ON; MCA-11 D4).

    Гейтит ТОЛЬКО новые точки записи (embeddings/медиа) и usage-детализацию;
    существующие записи LLM/изображений не трогает (K3 OFF → паритет
    существующей аналитики)."""
    return bool(getattr(settings, "MCA_COST_ACCOUNTING_ENABLED", True))


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


def sanitize_plan_meta(plan_meta) -> dict | None:
    """R17-фильтр plan_meta (§1.10): только whitelist-оси L1 и безопасные
    значения (enum-коды без пробелов ≤64, числа, bool, списки idents).
    Небезопасное/неизвестное → drop; пустой результат → ``None`` (NULL).
    Никогда не бросает."""
    if not isinstance(plan_meta, dict):
        return None
    safe: dict = {}
    for key, value in plan_meta.items():
        if key not in PLAN_META_FIELDS or value is None:
            continue
        if key in _PLAN_META_LIST_FIELDS:
            if isinstance(value, (list, tuple, set)):
                items = [str(v) for v in value
                         if isinstance(v, str)
                         and _IDENT_VALUE_RE.match(str(v))]
                if items:
                    safe[key] = ",".join(items)[:256]
            elif isinstance(value, str) and _IDENT_VALUE_RE.match(value):
                safe[key] = value
            continue
        if key in _PLAN_META_NUM_FIELDS:
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                safe[key] = value
            continue
        if isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, int):
            safe[key] = value
        elif key == "model":
            if isinstance(value, str) and _MODEL_VALUE_RE.match(value):
                safe[key] = value
        elif isinstance(value, str) and _IDENT_VALUE_RE.match(value):
            safe[key] = value
    if not safe:
        return None
    try:
        import json as _json
        if len(_json.dumps(safe, ensure_ascii=False)) > _PLAN_META_MAX_BYTES:
            # Bounded-гвард: неожиданно большой payload → честный drop
            # (не усечённый мусор).
            return None
    except Exception:
        return None
    return safe


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
                 tokens_estimated: bool = False,
                 plan_meta: dict | None = None) -> None:
    """Записать usage-событие (fail-open).

    `cost_usd` считается по реальным токенам и цене модели; при неизвестной
    цене — `0` + `price_known=false`. Ошибка/PG down → событие пропущено,
    бот жив. Off-switch (`TOKEN_ANALYTICS_ENABLED=OFF`) → no-op.

    ASAP 7 (F2, §1.10): опциональный ``plan_meta`` — R17-whitelist enum-осей
    L1 (см. ``PLAN_META_FIELDS``); неизвестные поля/значения отбрасываются,
    пустой результат → NULL. Читатель durable-осей — SQL-агрегат
    ``execution_graph_source`` (module='direct_chat' AND step='l1_planner').
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
            plan_meta=sanitize_plan_meta(plan_meta),
        )
    except Exception:
        logger.warning(
            "[usage_events] record failed — fail-open | module=%s | step=%s",
            module, step, exc_info=True)
        return
    await maybe_cleanup(pool)


async def conn_insert(pool, *, corr, module, step, tool_name, source, chat_id,
                      model, input_tokens, output_tokens, tokens_estimated,
                      cost_usd, price_known, plan_meta=None) -> None:
    """Низкоуровневый INSERT (вынесен для читаемости/тестируемости).

    ``plan_meta`` — уже санитизированный dict (``sanitize_plan_meta``) или
    None → NULL (asyncpg jsonb-кодек кодирует dict сам, но явный json.dumps
    держит контракт строкой независимо от кодеков пула)."""
    import json as _json
    async with pool.acquire() as conn:
        await conn.execute(
            INSERT_SQL, corr, module, step, tool_name, source, chat_id, model,
            int(input_tokens), int(output_tokens), bool(tokens_estimated),
            float(cost_usd), bool(price_known),
            (_json.dumps(plan_meta, ensure_ascii=False)
             if isinstance(plan_meta, dict) else None))


async def maybe_cleanup(pool, *, force: bool = False) -> bool:
    """Opportunistic-очистка старых событий (ретенция). Возвращает факт DELETE.

    Дедуп: не чаще `CLEANUP_INTERVAL_SECONDS` (если `force=False`). Fail-open:
    ошибка удаления не влияет на запись/ответ. Метка дедупа ставится ТОЛЬКО
    после успешного `DELETE` — сбой PG не «залипает» на час (review iter1).
    """
    global _last_cleanup
    now = time.monotonic()
    if not force and (now - _last_cleanup) < CLEANUP_INTERVAL_SECONDS:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(DELETE_SQL, retention_days())
    except Exception:
        logger.warning("[usage_events] retention cleanup failed — fail-open",
                       exc_info=True)
        return False
    _last_cleanup = time.monotonic()
    return True


def reset_cleanup_state() -> None:
    """Сброс дедупа очистки (для тестов/детерминизма)."""
    global _last_cleanup
    _last_cleanup = 0.0
