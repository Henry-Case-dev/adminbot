"""QND-NONDET §5 — честный снимок фактической недетерминистики.

Только РЕАЛЬНЫЕ данные: durable-строки `semantic_schedule` и durable-события
`mca_events` (component `qnd`). Ни одно число здесь не вычисляется из
«предположения»: нет событий — ноль/«нет данных», а не красивая оценка.

Правило честности (контракт §5): если в окне нет ни одного квантового
значения (`draws_quantum == 0`), блок НЕ имеет права говорить «работает»:
`status_word_allowed=False`, `headline` — «квантовый источник не
использовался» / «fallback». Отсутствующий знаменатель — `share=None`
(«нет данных»), а не выдуманный процент.

Читатели — существующие роутеры (`/api/status`, vitality/публикации);
собственной таблицы метрик не заводится: имя метрики = durable-событие.
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_HOURS = 24
#: Окно Аналитики допускает 48 ч (существующее ограничение роутеров).
MAX_WINDOW_HOURS = 48
#: Сколько последних решений показывать в таблице кандидатов.
DECISIONS_LIMIT = 20
#: Сколько строк истории интервалов отдавать (гистограмма остаётся живой).
HISTORY_LIMIT = 60

QUANTUM_SOURCES = frozenset({"quantum"})
FALLBACK_SOURCES = frozenset({"pseudorandom"})


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load(payload):
    if isinstance(payload, dict):
        return payload
    try:
        data = json.loads(payload or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _source_bucket(source: str) -> str:
    value = str(source or "").lower()
    if value in QUANTUM_SOURCES:
        return "quantum"
    if value in FALLBACK_SOURCES:
        return "fallback"
    return "unavailable"


def _histogram(delays: list[int], *, buckets: int = 6) -> list[dict]:
    """Гистограмма интервалов из фактических draw (пусто — пусто)."""
    values = sorted(int(d) for d in delays if int(d) > 0)
    if not values:
        return []
    lo, hi = values[0], values[-1]
    if lo == hi:
        return [{"from": lo, "to": hi, "count": len(values)}]
    width = max(1, (hi - lo + buckets - 1) // buckets)
    out = []
    edge = lo
    while edge <= hi:
        upper = edge + width - 1
        count = len([v for v in values if edge <= v <= upper])
        if count:
            out.append({"from": edge, "to": upper, "count": count})
        edge = upper + 1
    return out


async def _rows(db, sql: str, params=()) -> list[dict]:
    try:
        cursor = await db.db.execute(sql, params)
        return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        logger.warning("[qnd] diagnostics read failed", exc_info=True)
        return []


async def collect_quantum(db, *, chat_id: int | None = None,
                          hours: int = DEFAULT_WINDOW_HOURS,
                          now: int | None = None) -> dict:
    """Снимок §5 по механизмам: сроки, источник draw, решения, доставки."""
    stamp = int(now if now is not None else time.time())
    try:
        window_hours = max(1, min(MAX_WINDOW_HOURS, int(hours or
                                                        DEFAULT_WINDOW_HOURS)))
    except (TypeError, ValueError):
        window_hours = DEFAULT_WINDOW_HOURS
    since = stamp - window_hours * 3600
    out: dict = {"now": stamp, "hours": window_hours, "mechanisms": {}}
    for mechanism in ("nostalgia", "initiative"):
        out["mechanisms"][mechanism] = await _mechanism_block(
            db, mechanism, chat_id=chat_id, since=since, now=stamp)
    return out


async def _mechanism_block(db, mechanism: str, *, chat_id, since: int,
                           now: int) -> dict:
    from services import semantic_schedule as sched
    chat_clause = " AND chat_id = ?" if chat_id is not None else ""
    params: list = [mechanism]
    if chat_id is not None:
        params.append(int(chat_id))

    schedule_rows = await _rows(
        db,
        "SELECT chat_id, next_due_ts, last_check_ts, last_draw_ts, "
        "lo_seconds, hi_seconds, u, delay_seconds, source, provider, draw_id, "
        "fallback_reason, missed_count, scan_requested_at, settings_hash "
        "FROM semantic_schedule WHERE mechanism = ?" + chat_clause
        + " ORDER BY next_due_ts ASC LIMIT 32", tuple(params))

    event_params: list = [f"{since}", mechanism]
    if chat_id is not None:
        event_params.append(int(chat_id))
    events = await _rows(
        db,
        "SELECT event_name, outcome, ts, usage_json FROM mca_events "
        "WHERE component = 'qnd' AND event_name IN "
        "('quantum_schedule_draw','quantum_schedule_due',"
        "'quantum_evaluation','quantum_publication_decision',"
        "'quantum_publication_result','initiative_event_signal') "
        "AND ts >= ? AND json_extract(usage_json, '$.mechanism') = ?"
        + chat_clause + " ORDER BY ts DESC LIMIT 500", tuple(event_params))

    draws: list[dict] = []
    dues: list[dict] = []
    evaluations: list[dict] = []
    decisions: list[dict] = []
    results: list[dict] = []
    signals: dict[str, int] = {}
    for row in events:
        payload = _load(row.get("usage_json"))
        name = str(row.get("event_name") or "")
        if name == "quantum_schedule_draw":
            draws.append(payload)
        elif name == "quantum_schedule_due":
            dues.append(payload)
        elif name == "quantum_evaluation":
            evaluations.append(payload)
        elif name == "quantum_publication_decision":
            decisions.append(payload)
        elif name == "quantum_publication_result":
            results.append(payload)
        else:
            key = str(payload.get("decision") or "")
            if key:
                signals[key] = signals.get(key, 0) + 1

    sources = {"quantum": 0, "fallback": 0, "unavailable": 0}
    for draw in draws:
        sources[_source_bucket(draw.get("source"))] += 1
    for decision in decisions:
        sources[_source_bucket(decision.get("source"))] += 1
    draws_quantum = sources["quantum"]

    deliveries = len([r for r in results
                      if str(r.get("outcome")) == "delivered"])
    published = len([d for d in decisions if _int(d.get("hit")) == 1])
    silent = len([d for d in decisions if _int(d.get("hit")) == 0])
    deferred = len([d for d in decisions
                    if str(d.get("outcome")) == "blocked_random_unavailable"])
    silence_by_cause: dict[str, int] = {}
    for decision in decisions:
        cause = str(decision.get("silence_cause") or "")
        if cause:
            silence_by_cause[cause] = silence_by_cause.get(cause, 0) + 1
    triggers = {"schedule": 0, "event": 0}
    for item in evaluations:
        trigger = str(item.get("trigger") or "")
        if trigger in triggers:
            triggers[trigger] += 1

    last_draw = draws[0] if draws else {}
    last_check = max((_int(r.get("last_check_ts")) for r in schedule_rows),
                     default=0)
    next_due_values = [_int(r.get("next_due_ts")) for r in schedule_rows
                       if _int(r.get("next_due_ts")) > 0]
    next_due = min(next_due_values) if next_due_values else 0

    if draws_quantum > 0:
        allowed = True
        headline = "квантовый источник используется"
    elif sources["unavailable"] > 0 or sources["fallback"] > 0:
        allowed = False
        headline = ("квантовый источник не использовался — "
                    + ("fallback" if sources["fallback"] else "недоступен"))
    else:
        allowed = False
        headline = "нет данных: розыгрышей в окне не было"

    return {
        "mechanism": mechanism,
        "chats": len(schedule_rows),
        "last_check_ts": last_check or None,
        "next_due_ts": next_due or None,
        "next_due_in_seconds": (max(0, next_due - now) if next_due else None),
        "last_draw": {
            "ts": _int(last_draw.get("ts") or 0) or None,
            "source": str(last_draw.get("source") or ""),
            "provider": last_draw.get("provider"),
            "u": last_draw.get("u"),
            "delay_seconds": last_draw.get("delay_seconds"),
            "next_due_ts": last_draw.get("next_due_ts"),
            "draw_id": last_draw.get("draw_id"),
            "fallback_reason": last_draw.get("fallback_reason"),
        },
        "source_shares": {
            "quantum": sources["quantum"],
            "fallback": sources["fallback"],
            "unavailable": sources["unavailable"],
        },
        "draws_quantum": draws_quantum,
        "draws_total": len(draws),
        "interval_histogram": _histogram(
            [_int(d.get("delay_seconds")) for d in draws])[-6:],
        "intervals": [
            {"ts": d.get("ts"), "delay_seconds": d.get("delay_seconds"),
             "u": d.get("u"), "source": d.get("source")}
            for d in draws[:HISTORY_LIMIT]],
        "evaluations": {"schedule": triggers["schedule"],
                        "event": triggers["event"],
                        "total": len(evaluations)},
        "publications": {
            "decisions": len(decisions),
            "published": published,
            "silent": silent,
            "deferred": deferred,
            "deliveries": deliveries,
            "silence_by_cause": silence_by_cause,
        },
        "scheduled_due": {
            "total": len(dues),
            "executed": len([d for d in dues if d.get("executed")]),
            "skipped": len([d for d in dues if not d.get("executed")]),
            "stale": len([d for d in dues
                          if str(d.get("reason_code")) == "stale_deadline"]),
            "settings_rescaled": len(
                [d for d in dues
                 if str(d.get("reason_code")) == "settings_rescaled"]),
            "lease_held": len([d for d in dues
                               if str(d.get("reason_code")) == "lease_held"]),
        },
        "event_signals": signals,
        "candidates": [
            {"ts": d.get("ts"), "candidate_ref": d.get("candidate_ref"),
             "p": d.get("p"), "u": d.get("u"), "hit": d.get("hit"),
             "outcome": d.get("outcome"),
             "silence_cause": d.get("silence_cause"),
             "source": d.get("source"), "trigger": d.get("trigger")}
            for d in decisions[:DECISIONS_LIMIT]],
        "rows": schedule_rows[:8],
        "honesty": {
            "status_word_allowed": allowed,
            "headline": headline,
            "draws_quantum": draws_quantum,
            "denominator": len(draws) + len(decisions),
        },
    }
