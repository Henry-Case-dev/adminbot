"""F7 (раунд 10.23, ADR-1023-7 §2.7) — API дашборда аналитики токенов.

R16-аддитивно, read-side только PG (`llm_usage_events`/`llm_model_prices`).
RBAC — глобальный админ (образец `/api/workers/budget`). Fail-open: PG
недоступен или `TOKEN_ANALYTICS_ENABLED=OFF` → shape-совместимый пустой
ответ без ошибок. R17: наружу только коды/числа/токены, без промптов.

Эндпоинты:
* GET  /analytics/usage/latest   — дерево последнего вызова (Flow node);
* GET  /analytics/usage/summary  — агрегаты день/неделя/месяц (+ by_module);
* GET  /analytics/prices         — таблица цен;
* PUT  /analytics/prices         — upsert цены (admin-only);
* GET  /analytics/execution/latest — S8 (ADR-1026-10 D3): нормализованный
  граф одного прогона Саммари (узлы `algorithm`/`llm`/`format` + §112).

S8-эндпоинт аддитивен и read-only (R16: одна минимальная поверхность §111
«расширить backend adapter»). Publish-срез GATED (D1/D8): узлы
`kind="publish"` не эмитятся.
"""
import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from services import execution_graph_source, llm_pricing, usage_events
from web.api.deps import get_cache, requires_global_admin

logger = logging.getLogger(__name__)

analytics_router = APIRouter()

# Периоды дашборда: (окно в днях, единица бакета). Только фиксированный
# whitelist — единица подставляется в SQL литералом (без пользовательского
# ввода).
_PERIODS = {
    "day": (1, "hour"),
    "week": (7, "day"),
    "month": (30, "day"),
}

_SELECT_LATEST_SQL = (
    "SELECT correlation_id, ts FROM llm_usage_events "
    "ORDER BY ts DESC, id DESC LIMIT 1"
)
_SELECT_STEPS_SQL = (
    "SELECT ts, module, step, tool_name, source, model, input_tokens, "
    "output_tokens, tokens_estimated, cost_usd, price_known "
    "FROM llm_usage_events WHERE correlation_id = $1 ORDER BY ts ASC, id ASC"
)
# S8/`L-F6S-1` (ADR-1026-10 D4): аддитивный `price_known` = BOOL_AND(price_known)
# — агрегат честно показывает «Нет данных» вместо выдуманного `$0`, когда цена
# хотя бы одного события неизвестна. `COALESCE(..., true)` — пустое окно
# остаётся shape-совместимым (нет событий → нечего считать неизвестным).
_SELECT_TOTALS_SQL = (
    "SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, COUNT(*) AS calls, "
    "COALESCE(BOOL_AND(price_known), true) AS price_known "
    "FROM llm_usage_events WHERE ts >= now() - ($1::int * interval '1 day')"
)
_SELECT_BY_MODULE_SQL = (
    "SELECT module, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, COUNT(*) AS calls, "
    "COALESCE(BOOL_AND(price_known), true) AS price_known "
    "FROM llm_usage_events WHERE ts >= now() - ($1::int * interval '1 day') "
    "GROUP BY module ORDER BY cost_usd DESC, module ASC"
)
_SELECT_SERIES_SQL = (
    "SELECT date_trunc('{unit}', ts) AS bucket, "
    "COALESCE(SUM(cost_usd), 0) AS cost_usd, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, COUNT(*) AS calls, "
    "COALESCE(BOOL_AND(price_known), true) AS price_known "
    "FROM llm_usage_events WHERE ts >= now() - ($1::int * interval '1 day') "
    "GROUP BY bucket ORDER BY bucket ASC"
)
_SELECT_PRICES_SQL = (
    "SELECT model, input_usd_per_1m, output_usd_per_1m, currency, updated_at "
    "FROM llm_model_prices ORDER BY model ASC"
)
_UPSERT_PRICE_SQL = (
    "INSERT INTO llm_model_prices "
    "(model, input_usd_per_1m, output_usd_per_1m, currency, updated_at) "
    "VALUES ($1, $2, $3, $4, now()) "
    "ON CONFLICT (model) DO UPDATE SET "
    "input_usd_per_1m = EXCLUDED.input_usd_per_1m, "
    "output_usd_per_1m = EXCLUDED.output_usd_per_1m, "
    "currency = EXCLUDED.currency, updated_at = now()"
)

_EMPTY_TOTAL = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                "calls": 0}


class PriceBody(BaseModel):
    model: str
    input_usd_per_1m: float
    output_usd_per_1m: float
    currency: str = "USD"


def _pool(cache):
    pg = getattr(cache, "pg", None)
    return getattr(pg, "pool", None) if pg is not None else None


def _num(value) -> float:
    """NUMERIC/Decimal → float (0.0 на мусоре)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bool(row, key, default=True) -> bool:
    """Значение BOOL-колонки; отсутствие ключа → безопасный default (True).

    Fake-пулы/старые ответы без `price_known` не должны падать (аддитивность).
    """
    try:
        return bool(row[key])
    except (KeyError, TypeError, IndexError):
        return default


def _step_row(row) -> dict:
    return {
        "ts": row["ts"].isoformat() if hasattr(row["ts"], "isoformat")
        else str(row["ts"]),
        "module": str(row["module"] or ""),
        "step": str(row["step"] or ""),
        "tool_name": str(row["tool_name"] or ""),
        "source": str(row["source"] or "global"),
        "model": str(row["model"] or ""),
        "input_tokens": _int(row["input_tokens"]),
        "output_tokens": _int(row["output_tokens"]),
        "tokens_estimated": bool(row["tokens_estimated"]),
        "cost_usd": _num(row["cost_usd"]),
        "price_known": bool(row["price_known"]),
    }


def _empty_latest() -> dict:
    return {"correlation_id": "", "ts": None, "steps": [],
            "total": dict(_EMPTY_TOTAL)}


def _empty_summary(period: str, days: int) -> dict:
    totals = dict(_EMPTY_TOTAL)
    totals["price_known"] = True        # S8/`L-F6S-1`: нет событий → нет $0
    return {"period": period, "since": f"{days}d", "totals": totals,
            "by_module": [], "series": []}


def _context_limit_info() -> dict:
    """§112: контекст-лимит Саммари; `-1`-sentinel → «Без лимита» (D4).

    R17-safe: только bool/подпись, без значений секретов.
    """
    try:
        from config.settings import settings
        from services import hot_config as hot
        from services.budget_limits import context_state
        raw = hot.get("limits.summary_max_context_tokens",
                      getattr(settings, "SUMMARY_MAX_CONTEXT_TOKENS", None))
        if context_state(raw) == "unlimited":
            return {"unlimited": True, "display": "Без лимита"}
        return {"unlimited": False, "display": None}
    except Exception:      # pragma: no cover - защитная ветка (fail-open)
        return {"unlimited": False, "display": None}


def _execution_response(run_id: str, snapshot, rows: list) -> dict:
    """Нормализованный граф прогона + §112 (fail-open shape, D3/D6)."""
    graph = execution_graph_source.build_graph(run_id, snapshot, rows)
    graph["metrics"]["context"] = _context_limit_info()
    return graph


@analytics_router.get("/analytics/usage/latest")
async def usage_latest(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Последний `correlation_id` и все его события по `ts` (Flow node)."""
    cache = get_cache(request)
    pool = _pool(cache)
    if pool is None or not usage_events.is_enabled():
        return _empty_latest()
    try:
        async with pool.acquire() as conn:
            head = await conn.fetchrow(_SELECT_LATEST_SQL)
            if head is None:
                return _empty_latest()
            corr = str(head["correlation_id"])
            rows = await conn.fetch(_SELECT_STEPS_SQL, corr)
    except Exception:
        logger.warning("[analytics] latest read failed — fail-open",
                       exc_info=True)
        return _empty_latest()
    steps = [_step_row(row) for row in rows]
    total = {
        "input_tokens": sum(s["input_tokens"] for s in steps),
        "output_tokens": sum(s["output_tokens"] for s in steps),
        "cost_usd": round(sum(s["cost_usd"] for s in steps), 6),
        "calls": len(steps),
    }
    return {"correlation_id": corr,
            "ts": (head["ts"].isoformat() if hasattr(head["ts"], "isoformat")
                   else str(head["ts"])),
            "steps": steps, "total": total}


@analytics_router.get("/analytics/usage/summary")
async def usage_summary(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    period: str = Query(default="day"),
):
    """Агрегаты за день/неделю/месяц: totals + by_module + series."""
    period = str(period or "day").strip().lower()
    days, unit = _PERIODS.get(period, _PERIODS["day"])
    if period not in _PERIODS:
        period = "day"
    cache = get_cache(request)
    pool = _pool(cache)
    if pool is None or not usage_events.is_enabled():
        return _empty_summary(period, days)
    try:
        async with pool.acquire() as conn:
            totals_row = await conn.fetchrow(_SELECT_TOTALS_SQL, days)
            module_rows = await conn.fetch(_SELECT_BY_MODULE_SQL, days)
            series_rows = await conn.fetch(
                _SELECT_SERIES_SQL.format(unit=unit), days)
    except Exception:
        logger.warning("[analytics] summary read failed — fail-open",
                       exc_info=True)
        return _empty_summary(period, days)
    totals = {
        "input_tokens": _int(totals_row["input_tokens"]),
        "output_tokens": _int(totals_row["output_tokens"]),
        "cost_usd": _num(totals_row["cost_usd"]),
        "calls": _int(totals_row["calls"]),
        "price_known": _bool(totals_row, "price_known", True),
    }
    by_module = [{
        "module": str(row["module"] or ""),
        "cost_usd": _num(row["cost_usd"]),
        "input_tokens": _int(row["input_tokens"]),
        "output_tokens": _int(row["output_tokens"]),
        "calls": _int(row["calls"]),
        "price_known": _bool(row, "price_known", True),
    } for row in module_rows]
    series = [{
        "bucket": (row["bucket"].isoformat()
                   if hasattr(row["bucket"], "isoformat")
                   else str(row["bucket"])),
        "cost_usd": _num(row["cost_usd"]),
        "input_tokens": _int(row["input_tokens"]),
        "output_tokens": _int(row["output_tokens"]),
        "calls": _int(row["calls"]),
        "price_known": _bool(row, "price_known", True),
    } for row in series_rows]
    return {"period": period, "since": f"{days}d", "totals": totals,
            "by_module": by_module, "series": series}


@analytics_router.get("/analytics/execution/latest")
async def execution_latest(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    run_id: str = Query(default=""),
):
    """S8 (ADR-1026-10 D3): нормализованный граф одного прогона Саммари.

    Источники: LLM-узлы — PG ``llm_usage_events`` по ``correlation_id``
    (=``run_id``, D5); filter/format/§112 — in-memory снапшот прогона (S7).
    Публикация — ``gated`` (D1/D8). Fail-open: нет данных/PG down/телеметрия
    OFF → shape-совместимый пустой граф без ошибок UI (узлы только реальные,
    §24/§25/§30).
    """
    cache = get_cache(request)
    pool = _pool(cache)
    rid = str(run_id or "").strip()
    if not rid:
        rid = execution_graph_source.latest_run_id() or ""
    if not rid:
        return _execution_response("", None, [])
    snapshot = execution_graph_source.get_run(rid)
    rows: list = []
    if pool is not None and usage_events.is_enabled():
        try:
            async with pool.acquire() as conn:
                raw = await conn.fetch(_SELECT_STEPS_SQL, rid)
            rows = [_step_row(row) for row in raw]
        except Exception:
            logger.warning("[analytics] execution read failed — fail-open",
                           exc_info=True)
            rows = []
    return _execution_response(rid, snapshot, rows)


@analytics_router.get("/analytics/prices")
async def prices_list(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Таблица цен моделей (для обслуживания из мини-аппа)."""
    cache = get_cache(request)
    pool = _pool(cache)
    # review iter1: мастер-флаг OFF → управление ценами тоже выключено
    # (контракт spec §2.7 «эндпоинты возвращают пустой/shape-совместимый ответ»).
    if pool is None or not usage_events.is_enabled():
        return {"prices": []}
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_PRICES_SQL)
    except Exception:
        logger.warning("[analytics] prices read failed — fail-open",
                       exc_info=True)
        return {"prices": []}
    return {"prices": [{
        "model": str(row["model"] or ""),
        "input_usd_per_1m": _num(row["input_usd_per_1m"]),
        "output_usd_per_1m": _num(row["output_usd_per_1m"]),
        "currency": str(row["currency"] or "USD"),
    } for row in rows]}


@analytics_router.put("/analytics/prices")
async def prices_upsert(
    request: Request,
    payload: PriceBody,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Upsert цены модели (admin-only); сбрасывает in-process кэш цен."""
    cache = get_cache(request)
    pool = _pool(cache)
    if pool is None or not usage_events.is_enabled():
        return {"ok": False, "model": payload.model}
    model = str(payload.model or "").strip()
    if not model:
        return {"ok": False, "model": ""}
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                _UPSERT_PRICE_SQL, model,
                max(0.0, float(payload.input_usd_per_1m)),
                max(0.0, float(payload.output_usd_per_1m)),
                str(payload.currency or "USD"))
    except Exception:
        logger.warning("[analytics] price upsert failed | model=%s", model,
                       exc_info=True)
        return {"ok": False, "model": model}
    llm_pricing.invalidate(model)
    logger.info("[analytics] price upsert | model=%s by=%s", model, user.id)
    return {"ok": True, "model": model}
