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
  граф одного прогона Саммари (узлы `algorithm`/`llm`/`format`/`publish` +
  §112).

S8-эндпоинт аддитивен и read-only (R16: одна минимальная поверхность §111
«расширить backend adapter»). Publish-срез активирован в S6 (ADR-1026-11 D6):
узел `kind="publish"` строится только из реальных данных снапшота, статус —
реальный (`published_rich`/`published_text`/`failed`/`skipped`; нет данных →
`None`).
"""
import logging
import time
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
# MCA-23 (P2-B §35): агрегаты Direct-ответов за период — СУЩЕСТВУЮЩИЕ строки
# `llm_usage_events` (module='direct_chat'), одна строка на прогон
# (correlation_id). Второй телеметрии/DDL нет; осей плана (action/extent/
# delivery) в durable-событиях НЕТ — распределения за период честно `null`
# (см. `_response_empty_summary`), свежее in-memory окно отдаёт
# `execution_graph_source.response_recent_window()`.
_SELECT_RESPONSE_RUNS_SQL = (
    "SELECT correlation_id, COUNT(*) AS calls, "
    "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
    "SUM(cost_usd) FILTER (WHERE price_known) AS cost_known, "
    "COALESCE(BOOL_AND(price_known), true) AS price_known, "
    "COUNT(*) FILTER (WHERE step = 'tool') AS tool_calls, "
    "GREATEST(EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts))) * 1000.0, 0.0) "
    "AS span_ms, MIN(ts) AS first_ts "
    "FROM llm_usage_events WHERE module = 'direct_chat' "
    "AND ts >= now() - ($1::int * interval '1 day') "
    "GROUP BY correlation_id ORDER BY MIN(ts) DESC LIMIT 2000"
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
    (=``run_id``, D5); filter/format/publish/§112 — in-memory снапшот прогона
    (S7/S6). Публикация — реальный статус из снапшота (S6/D6; нет данных →
    ``None``). Fail-open: нет данных/PG down/телеметрия OFF → shape-совместимый
    пустой граф без ошибок UI (узлы только реальные, §24/§25/§30).
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


# ── MCA-23 (P2-B §35): агрегаты «Ответ (Pipeline)» — 24ч / 7 дней ───────────

_RESPONSE_PERIODS = {"24h": 1, "7d": 7}


def _response_empty_summary(period: str) -> dict:
    """Честная пустая форма (fail-open; нет событий → не выдумываем числа)."""
    return {
        "period": period, "days": _RESPONSE_PERIODS.get(period),
        "available": False, "runs": 0, "calls": 0,
        "tools_per_run": None, "multi_tool_rate": None,
        # Ошибки инструментов в `llm_usage_events` не пишутся → честно None.
        "tool_failure_rate": None,
        "tokens": {"input_tokens": 0, "output_tokens": 0},
        "cost_usd": None, "price_known": True,
        # Latency по span'у LLM-вызовов (первый→последний вызов прогона);
        # нет событий → None.
        "latency": {"p50_ms": None, "p95_ms": None,
                    "source": "llm_call_span"},
        # Распределения осей плана (action/extent/delivery) за период:
        # durable-осей в существующих событиях нет → честно None (§14 ASAP 6).
        "plan_axes": None,
        "recent": execution_graph_source.response_recent_window(),
        "note_ru": ("Распределения действий/объёма/доставки за период "
                    "недоступны: оси плана живут в in-memory окне "
                    "(«Свежие прогоны» ниже)."),
    }


def _p_value(values: list, q: float):
    if not values:
        return None
    data = sorted(float(v) for v in values if v is not None)
    if not data:
        return None
    if len(data) == 1:
        return round(data[0], 1)
    pos = q * (len(data) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    frac = pos - lo
    return round(data[lo] * (1 - frac) + data[hi] * frac, 1)


def _p95(values: list):
    return _p_value(values, 0.95)


def _p50(values: list):
    return _p_value(values, 0.5)


@analytics_router.get("/analytics/response/summary")
async def response_pipeline_summary(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    period: str = Query(default="24h"),
):
    """MCA-23 (§35): агрегаты Direct-ответов за 24ч/7д из СУЩЕСТВУЮЩИХ
    ``llm_usage_events`` (module='direct_chat') + свежее in-memory окно
    (``execution_graph_source.response_recent_window``). Read-only,
    аддитивный; вторая telemetry-модель не создаётся (§33). Fail-open:
    нет данных/PG down → честная пустая форма («—», не выдуманные %)."""
    period = str(period or "").strip().lower()
    days = _RESPONSE_PERIODS.get(period)
    if days is None:
        period = "24h"
        days = 1
    empty = _response_empty_summary(period)
    cache = get_cache(request)
    pool = _pool(cache)
    if pool is None or not usage_events.is_enabled():
        return empty
    try:
        async with pool.acquire() as conn:
            raw = await conn.fetch(_SELECT_RESPONSE_RUNS_SQL, days)
    except Exception:
        logger.warning("[analytics] response summary read failed — fail-open",
                       exc_info=True)
        return empty
    runs = len(raw)
    if not runs:
        return empty
    calls = in_toks = out_toks = tool_calls = 0
    cost = 0.0
    cost_known = True
    spans: list = []
    multi_tool_runs = 0
    for row in raw:
        c = _int(row["calls"])
        calls += c
        in_toks += _int(row["input_tokens"])
        out_toks += _int(row["output_tokens"])
        t = _int(row["tool_calls"])
        tool_calls += t
        if t > 1:
            multi_tool_runs += 1
        if _bool(row, "price_known", True):
            cost += _num(row["cost_known"])
        else:
            cost_known = False
        span = _num(row["span_ms"])
        if span is not None and span > 0:
            spans.append(span)
    return {
        "period": period, "days": days, "available": True,
        "runs": runs, "calls": calls,
        "tools_per_run": (round(tool_calls / runs, 2) if runs else None),
        "multi_tool_rate": (round(multi_tool_runs / runs, 4)
                            if runs else None),
        # Ошибки tool-вызовов в usage events не записываются → честный None.
        "tool_failure_rate": None,
        "tokens": {"input_tokens": in_toks, "output_tokens": out_toks},
        "cost_usd": (round(cost, 6) if (cost_known and cost > 0) else None),
        "price_known": cost_known,
        "latency": {"p50_ms": _p50(spans), "p95_ms": _p95(spans),
                    "source": "llm_call_span",
                    "label_ru": "между первым и последним LLM-вызовом прогона"},
        "plan_axes": None,
        "recent": execution_graph_source.response_recent_window(),
        "note_ru": ("Распределения действий/объёма/доставки за период "
                    "недоступны: оси плана живут в in-memory окне "
                    "(«Свежие прогоны» ниже)."),
    }


@analytics_router.get("/analytics/context-budgets")
async def context_budgets(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    chat_id: int | None = Query(default=None),
    refresh: int = Query(default=0),
):
    """ASAP-3.1 (ADR-1028-3, §24–§27, T-4075): автобюджеты активных слотов.

    Read-side view над Model Capacity + Stage Auto Budget Resolver (§37:
    единственный источник цифр — второй расчёт/usage store не создаётся,
    §24/§29/§50). Shape §25: ``{generated_at, chat_id, policy_mode, slots[]:
    {slot, label, provider, model, inherited_from, capacity{declared,
    effective, source, fallback_used}, budget{output_reserve, safety_reserve,
    auto_input_budget, manual_cap, effective_input_budget}, policy_mode,
    coverage_policy, observed{last, p50, p95, max, pressure_events,
    physical_overflow_events}}}`` + summary_coverage (§135) + warnings.
    Optional ``?chat_id=`` — per-chat Context Policy; ``?refresh=1`` —
    explicit refresh (инвалидация кэша capacity, §7/§38).
    Kill-switch ``ANALYTICS_CONTEXT_BUDGETS_ENABLED`` (default ON): OFF →
    404, остальная Аналитика не затронута (fail-open §73)."""
    from config.settings import settings as _settings
    if not bool(getattr(_settings, "ANALYTICS_CONTEXT_BUDGETS_ENABLED", True)):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="not_found")
    if refresh:
        try:
            from services import model_capacity as _mc
            _mc.invalidate_capacity_cache()
        except Exception:      # pragma: no cover - fail-open
            pass
    from services.model_slots import collect_slots
    return await collect_slots(chat_id=chat_id)


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


# ── ASAP-4 волна E (T-4441/T-4444, spec §5 E.2, §61.4–§61.10) — Run
# Inspector: один виджет/одни данные (§61.4), режимы latest|24h|7d. Источник
# — structured state (mca_events + in-memory снапшоты), НЕ human-логи
# (§61.12). Kill-switch `SUMMARY_PIPELINE_EVENTS_ENABLED` (spec §8.2): OFF →
# вид из state-проекций (durable-события не читаются, агрегаты честно
# «нет данных»). R17: только числа/коды/id; без ключей/промптов/сырого чата.

def _pipeline_db(request: Request):
    """SQLite DatabaseService (fail-open → None — не 503: виджет деградирует
    в «Нет данных», а не ошибкой)."""
    try:
        from services import lore_runtime
        return lore_runtime.get_lore_db()
    except Exception:
        return None


_EMPTY_TOTALS = {"total": 0, "healthy": 0, "degraded": 0, "failed": 0,
                 "incomplete": 0}


@analytics_router.get("/analytics/pipeline/inspector")
async def pipeline_inspector(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    mode: str = Query(default="latest"),
    run_id: str = Query(default=""),
):
    """Run Inspector (§61.4): один виджет — три режима одних данных.

    ``mode=latest`` — карта последнего запуска + список runs; ``24h``/
    ``7d`` — агрегаты per-stage (§61.5) + итоги runs + список. Drill-down
    по произвольному run_id — ``?run_id=`` (карта конкретного прогона).
    Fail-open: любые ошибки → shape-совместимый пустой ответ."""
    from services import pipeline_analytics as pa
    mode = str(mode or "latest").strip().lower()
    days = {"24h": 1, "7d": 7}.get(mode)
    db = _pipeline_db(request)
    try:
        if run_id:
            run = await pa.collect_run(db, str(run_id))
            runs = await pa.collect_runs_list(db, limit=12)
            return {"mode": mode or "latest", "run": run, "runs": runs,
                    "generated_at": int(time.time())}
        if days is not None:
            aggregate = await pa.collect_aggregate(db, days)
            runs = await pa.collect_runs_list(db, limit=12)
            return {"mode": mode, "window": aggregate.get("window"),
                    "aggregate": aggregate, "runs": runs,
                    "generated_at": int(time.time())}
        run = await pa.collect_latest(db)
        runs = await pa.collect_runs_list(db, limit=12)
        return {"mode": "latest", "run": run, "runs": runs,
                "generated_at": int(time.time())}
    except Exception:
        logger.warning("[analytics] pipeline inspector failed — fail-open",
                       exc_info=True)
        return {"mode": mode or "latest", "run": None, "runs": [],
                "aggregate": {"stages": {}, "totals": dict(_EMPTY_TOTALS)},
                "generated_at": int(time.time())}


@analytics_router.get("/analytics/pipeline/runs/{run_id}")
async def pipeline_run_detail(
    request: Request,
    run_id: str,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Drill-down по run_id (§61.9): timestamps стадий, provider/model,
    attempts, counts, coverage, стиль, публикация, message id, safe reason —
    БЕЗ ключей/полных промптов/reasoning/сырого чата (R17/§61.9)."""
    from services import pipeline_analytics as pa
    rid = str(run_id or "").strip()
    db = _pipeline_db(request)
    if not rid:
        return {"run": None, "generated_at": int(time.time())}
    try:
        run = await pa.collect_run(db, rid)
        return {"run": run, "generated_at": int(time.time())}
    except Exception:
        logger.warning("[analytics] pipeline run detail failed — fail-open",
                       exc_info=True)
        return {"run": None, "generated_at": int(time.time())}
