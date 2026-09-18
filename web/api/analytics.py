"""F7 (раунд 10.23, ADR-1023-7 §2.7) — API дашборда аналитики токенов.

R16-аддитивно, read-side только PG (`llm_usage_events`/`llm_model_prices`).
RBAC — глобальный админ (образец `/api/workers/budget`). Fail-open: PG
недоступен или `TOKEN_ANALYTICS_ENABLED=OFF` → shape-совместимый пустой
ответ без ошибок. R17: наружу только коды/числа/токены, без промптов.

Эндпоинты:
* GET  /analytics/usage/latest   — дерево последнего вызова (Flow node);
* GET  /analytics/usage/summary  — агрегаты день/неделя/месяц (+ by_module);
* GET  /analytics/prices         — таблица цен;
* PUT  /analytics/prices         — upsert цены (admin-only).
"""
import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from services import llm_pricing, usage_events
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
_SELECT_TOTALS_SQL = (
    "SELECT COALESCE(SUM(cost_usd), 0) AS cost_usd, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, COUNT(*) AS calls "
    "FROM llm_usage_events WHERE ts >= now() - ($1::int * interval '1 day')"
)
_SELECT_BY_MODULE_SQL = (
    "SELECT module, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, COUNT(*) AS calls "
    "FROM llm_usage_events WHERE ts >= now() - ($1::int * interval '1 day') "
    "GROUP BY module ORDER BY cost_usd DESC, module ASC"
)
_SELECT_SERIES_SQL = (
    "SELECT date_trunc('{unit}', ts) AS bucket, "
    "COALESCE(SUM(cost_usd), 0) AS cost_usd, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, COUNT(*) AS calls "
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
    return {"period": period, "since": f"{days}d", "totals": dict(_EMPTY_TOTAL),
            "by_module": [], "series": []}


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
    }
    by_module = [{
        "module": str(row["module"] or ""),
        "cost_usd": _num(row["cost_usd"]),
        "input_tokens": _int(row["input_tokens"]),
        "output_tokens": _int(row["output_tokens"]),
        "calls": _int(row["calls"]),
    } for row in module_rows]
    series = [{
        "bucket": (row["bucket"].isoformat()
                   if hasattr(row["bucket"], "isoformat")
                   else str(row["bucket"])),
        "cost_usd": _num(row["cost_usd"]),
        "input_tokens": _int(row["input_tokens"]),
        "output_tokens": _int(row["output_tokens"]),
        "calls": _int(row["calls"]),
    } for row in series_rows]
    return {"period": period, "since": f"{days}d", "totals": totals,
            "by_module": by_module, "series": series}


@analytics_router.get("/analytics/prices")
async def prices_list(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Таблица цен моделей (для обслуживания из мини-аппа)."""
    cache = get_cache(request)
    pool = _pool(cache)
    if pool is None:
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
    if pool is None:
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
