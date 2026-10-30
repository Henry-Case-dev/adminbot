"""EVOL-007/008/009: виджет «Новые факты» и диагностика здоровья памяти.

Только чтение существующих таблиц (`graph_facts`, `mca_events`,
`memory_dream_log`) и уже заведённых флагов. Второй телеметрический
стор не создаётся. Расписание не меняется, прогоны не запускаются.
FTS/vector-поиск не трогается: доступность только читается.

Даты не подменяются и не выдумываются. NULL остаётся NULL.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Пустые состояния виджета — ровно те, что требует EVOL-007.
EMPTY_OK = None
EMPTY_EMPTY = "empty"
EMPTY_DISABLED = "disabled"
EMPTY_NO_NEW = "no_new_results"
EMPTY_LOAD_FAILED = "load_failed"
EMPTY_NOT_YET = "not_yet_run"

# Свежесть показанных фактов относительно последнего прохода экстракции.
# «has_items» не выдаётся, если последний проход упал или был пропущен.
FRESH_HAS_ITEMS = "has_items"
FRESH_EXTRACT_FAILED = "extract_failed"
FRESH_EXTRACT_SKIPPED = "extract_skipped"
FRESH_UNKNOWN = "unknown"

# Успешный проход экстракции: факты записаны ИЛИ честный «новых нет».
# failed / disabled-skip успехом не считаются.
_EXTRACT_EVENT = "FACTS_EXTRACT"
# Исходы самого прохода (`usage_json.outcome`, services/summary_memory.py,
# таблица outcome_map) — все они дают mca-outcome 'success'.
_SUCCESS_OUTCOMES = ("success", "all_duplicates", "partial",
                     "text_only_vector_deferred")
_NO_NEW_REASON = "no_new_contribution"
# Счётчики прохода экстракции из usage_json (summary_memory.py:3759-3761).
_EXTRACT_COUNT_KEYS = ("saved", "skipped", "deduped", "superseded")

_MEMORY_ERROR_EVENTS = (
    "FACTS_EXTRACT",
    "EMBED_API_FAILED",
    "EMBED_API_DEFERRED",
    "sleep_dream",
    "persona_traits",
)

# Ключ флага → (hot/pg key, settings attribute).
_FLAG_SPEC = {
    "graph_rag_enabled": ("flags.graph_rag_enabled", "GRAPH_RAG_ENABLED"),
    "dream_enabled": ("memory.dream_enabled", "DREAM_ENABLED"),
    "deep_sleep_enabled": ("flags.deep_sleep_enabled", "DEEP_SLEEP_ENABLED"),
    "persona_enabled": ("flags.persona_enabled", "PERSONA_ENABLED"),
}

_TIMESTAMP_SOURCES = {
    "created_at": "graph_facts.created_at",
    "extracted_at": "graph_facts.created_at",
    "message_timestamp": "graph_facts.message_timestamp",
    "last_confirmed_at": "graph_facts.last_confirmed_at",
    "note": (
        "Отдельной колонки extracted_at нет: время записи экстракции — "
        "created_at. Дату события (message_timestamp) и подтверждения "
        "(last_confirmed_at) им не подменяем; NULL остаётся NULL."
    ),
}


def _scope(chat_id: int | None) -> tuple[str, str, int | None]:
    if chat_id is None:
        return "global", "global", None
    cid = int(chat_id)
    return "chat", f"chat:{cid}", cid


def _scope_clause(chat_id: int | None, *, column: str = "chat_id"
                  ) -> tuple[str, list]:
    if chat_id is None:
        return "", []
    return f" AND {column} = ?", [int(chat_id)]


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_class(raw) -> str | None:
    """Класс из error_json.type. Тело ошибки не возвращаем (может быть текст)."""
    if not raw:
        return None
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None
    value = data.get("type")
    if isinstance(value, str) and value and len(value) <= 80 and " " not in value:
        return value
    return None


def _settings_default(attr: str) -> bool:
    from config.settings import settings
    return bool(getattr(settings, attr))


def _usage_dict(raw) -> dict | None:
    """usage_json события как словарь. Нет/битый — None (не пустой словарь)."""
    if raw in (None, ""):
        return None
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
    return data if isinstance(data, dict) else None


def _usage_counts(usage: dict | None) -> dict:
    """Счётчики прохода из usage_json (summary_memory.py:3759-3761).

    `candidates` = saved + skipped + deduped + superseded. Нет usage_json —
    все счётчики None: неизвестно, а не ноль.
    """
    def num(key: str) -> int | None:
        if usage is None:
            return None
        return _int_or_none(usage.get(key))

    counts: dict = {key: num(key) for key in _EXTRACT_COUNT_KEYS}
    counts["text_only"] = num("text_only")
    values = [counts[key] for key in _EXTRACT_COUNT_KEYS]
    counts["candidates"] = (
        sum(values) if all(value is not None for value in values) else None)
    counts["usage_present"] = usage is not None
    pass_outcome = (usage or {}).get("outcome")
    counts["pass_outcome"] = (
        str(pass_outcome) if isinstance(pass_outcome, str) and pass_outcome
        else None)
    return counts


def _pass_ok(last: dict) -> bool:
    """Проход считается успешным по mca-исходу и (если известен) usage-исходу."""
    if last.get("outcome") != "success":
        return False
    pass_outcome = last.get("pass_outcome")
    if pass_outcome is None:
        return True                     # старое событие без usage_json
    return str(pass_outcome) in _SUCCESS_OUTCOMES


async def _live_flag(name: str, chat_id: int | None) -> tuple[bool, str]:
    """Глобальный/per-chat флаг без сети, если кэш чата не прогрет.

    `worker_settings` при отсутствии ChatParamsCache сразу возвращает
    глобальный слой и source='error' (чат-слой не читался). Это не
    «выключено»: значение — hot/settings, источник честно помечен.
    """
    key, attr = _FLAG_SPEC[name]
    default = _settings_default(attr)
    try:
        from services.worker_settings import resolve_setting_with_source
        value, source = await resolve_setting_with_source(
            key, chat_id=chat_id, default=default)
        return bool(value), str(source or "default")
    except Exception:
        logger.debug("[memory_diagnostics] flag read failed | key=%s",
                     key, exc_info=True)
        try:
            from services import hot_config as hot
            return bool(hot.get(key, default)), "hot_fallback"
        except Exception:
            return default, "settings_default"


def _injected_flag(flags: dict, name: str, chat_id: int | None
                   ) -> tuple[bool, str] | None:
    chats = flags.get("chats") or {}
    if chat_id is not None:
        row = chats.get(chat_id)
        if row is None:
            row = chats.get(str(chat_id))
        if isinstance(row, dict) and name in row:
            return bool(row[name]), "chat"
    global_flags = flags.get("global") or {}
    if name in global_flags:
        return bool(global_flags[name]), "global"
    return None


async def resolve_flags(chat_id: int | None, flags: dict | None
                        ) -> tuple[dict, dict]:
    """{name: bool}, {name: source}. Инъекция `flags` не ходит в PG."""
    values: dict[str, bool] = {}
    sources: dict[str, str] = {}
    for name in _FLAG_SPEC:
        injected = None if flags is None else _injected_flag(flags, name, chat_id)
        if injected is not None:
            values[name], sources[name] = injected
        else:
            values[name], sources[name] = await _live_flag(name, chat_id)
    return values, sources


def schedule_view() -> dict:
    """Реальное расписание из кода. Джобы не регистрируются и не тикают.

    Цифры по умолчанию — `config.settings` (env). Крон сводки и cooldown
    глубокого сна — литералы планировщиков, не горячие ключи.
    """
    from config.settings import settings
    try:
        from services.dream_worker import _DEEP_SLEEP_MIN_INTERVAL_HOURS
        cooldown = int(_DEEP_SLEEP_MIN_INTERVAL_HOURS)
    except Exception:
        cooldown = 20
    try:
        from services import hot_config as hot
        tz = hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)
        tick = hot.get("memory.dream_tick_minutes", settings.DREAM_TICK_MINUTES)
        # Сутки/час глубокого сна считаются в WORKER_BUDGET_TZ
        # (dream_worker.py:542-547, `_deep_tz_name`), а не в SUMMARY_TIMEZONE.
        deep_tz = hot.get("limits.worker_budget_tz", settings.WORKER_BUDGET_TZ)
    except Exception:
        tz = settings.SUMMARY_TIMEZONE
        tick = settings.DREAM_TICK_MINUTES
        deep_tz = getattr(settings, "WORKER_BUDGET_TZ", tz)
    return {
        "extract": {
            "mode": "event_driven_and_summary_cron",
            "summary_cron": "hour=0,6,12,18 minute=0",
            "timezone": str(tz or "UTC"),
            "timezone_key": "limits.summary_timezone",
            "gate": "flags.graph_rag_enabled",
            "note": (
                "memorize_facts вызывается с живых хуков (сообщение, поиск, "
                "youtube, web, direct) и из конвейера сводки. Отдельного "
                "крона экстракции нет. Крон сводки — 4 раза в сутки "
                "(summary_scheduler.py), и он тоже вызывает memorize_facts, "
                "если флаг графа включён."
            ),
        },
        "sleep": {
            "job_id": "dream_tick",
            "trigger": "interval",
            "tick_minutes": int(tick or 0),
            "window_start_hour": int(settings.DREAM_WINDOW_START_HOUR),
            "window_end_hour": int(settings.DREAM_WINDOW_END_HOUR),
            "timezone": str(tz or "UTC"),
            "timezone_key": "limits.summary_timezone",
            "gate": "memory.dream_enabled",
            "jobs_always_registered": True,
            "note": (
                "Джоб регистрируется всегда; решение «работать» — внутри тика "
                "по флагу. Дистилляция — в окне [start, end) local. "
                "Изменение интервала применяется при рестарте процесса."
            ),
        },
        "deep_sleep": {
            "job_id": "deep_sleep_tick",
            "trigger": "interval",
            "tick_minutes": int(tick or 0),
            "trigger_mode_default": str(settings.DEEP_SLEEP_TRIGGER),
            "fixed_hour_default": int(settings.DEEP_SLEEP_HOUR),
            "cooldown_hours": cooldown,
            "timezone": str(deep_tz or tz or "UTC"),
            "timezone_key": "limits.worker_budget_tz",
            "gate": "flags.deep_sleep_enabled",
            "default_enabled": bool(settings.DEEP_SLEEP_ENABLED),
            "note": (
                "По умолчанию флаг выключен. trigger=after_sleep запускается "
                "после обычного сна; trigger=fixed — в свой local-час "
                "(WORKER_BUDGET_TZ, как в dream_worker._deep_tz_name; "
                "SUMMARY_TIMEZONE здесь не применяется). Ordinary-sleep master "
                "глубокий сон не блокирует: у него свой флаг."
            ),
        },
        "personality": {
            "job_id": None,
            "invoked_by": "dream_worker._run_persona_traits_step",
            "gate": "flags.persona_enabled",
            "default_enabled": bool(settings.PERSONA_ENABLED),
            "note": (
                "Отдельного планировщика нет. Шаг вызывается из глубокого сна. "
                "Включённый persona_enabled при выключенном Deep Sleep не "
                "запускает обновление — это never-run, не disabled."
            ),
        },
    }


async def _fetchone(db, sql: str, params: list) -> dict | None:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def _fetchall(db, sql: str, params: list) -> list[dict]:
    cursor = await db.db.execute(sql, params)
    return [dict(row) for row in await cursor.fetchall()]


async def _table_exists(db, name: str) -> bool:
    row = await _fetchone(
        db, "SELECT 1 AS ok FROM sqlite_master WHERE type='table' AND name=?",
        [name])
    return row is not None


def _widget_item(row: dict) -> dict:
    created = _int_or_none(row.get("created_at"))
    return {
        "chat_id": int(row.get("chat_id") or 0),
        "name": row.get("name"),
        "fact": row.get("fact"),
        "id": _int_or_none(row.get("id")),
        "kind": row.get("kind"),
        "created_at": created,
        "extracted_at": created,
        "extracted_at_source": "graph_facts.created_at",
        "message_timestamp": _int_or_none(row.get("message_timestamp")),
        "last_confirmed_at": _int_or_none(row.get("last_confirmed_at")),
    }


def _load_failed(chat_id: int | None, *, reason: str) -> dict:
    scope, label, cid = _scope(chat_id)
    return {
        "scope": scope,
        "scope_label": label,
        "chat_id": cid,
        "items": [],
        "ordered_by": "created_at_desc",
        "empty_state": EMPTY_LOAD_FAILED,
        "empty_state_reason": reason,
        "extraction_enabled": None,
        "extraction_enabled_source": None,
        "updates_disabled": None,
        "last_successful_extract_at": None,
        "last_extract": None,
        "freshness": None,
        "timestamp_sources": dict(_TIMESTAMP_SOURCES),
    }


async def facts_extract_status(db, chat_id: int | None) -> dict:
    """Последний терминал FACTS_EXTRACT и время успешного прохода.

    Успех = outcome=success ИЛИ skipped/no_new_contribution (LLM отработал,
    новых фактов нет). start/failed/disabled успехом не являются.
    """
    clause, params = _scope_clause(chat_id)
    last = await _fetchone(
        db,
        "SELECT ts, outcome, reason_code, stage, usage_json, error_json "
        "FROM mca_events "
        "WHERE event_name = ? AND outcome != 'start'" + clause +
        " ORDER BY ts DESC, id DESC LIMIT 1",
        [_EXTRACT_EVENT, *params])
    success = await _fetchone(
        db,
        "SELECT MAX(ts) AS ts FROM mca_events "
        "WHERE event_name = ? AND ("
        "outcome = 'success' OR (outcome = 'skipped' AND reason_code = ?))"
        + clause,
        [_EXTRACT_EVENT, _NO_NEW_REASON, *params])
    terminal = last is not None
    last_extract = None
    if last is not None:
        counts = _usage_counts(_usage_dict(last.get("usage_json")))
        last_extract = {
            "at": _int_or_none(last.get("ts")),
            "outcome": last.get("outcome"),
            "reason_code": last.get("reason_code") or None,
            "error_class": _error_class(last.get("error_json")),
            "stage": last.get("stage") or None,
            "pass_outcome": counts["pass_outcome"],
            "usage_present": counts["usage_present"],
            "candidates": counts["candidates"],
            "saved": counts["saved"],
            "skipped": counts["skipped"],
            "deduped": counts["deduped"],
            "superseded": counts["superseded"],
            "text_only": counts["text_only"],
        }
    return {
        "has_terminal": terminal,
        "last_successful_extract_at": (
            _int_or_none(success.get("ts")) if success else None),
        "last_extract": last_extract,
    }


def _empty_state(items: list, *, enabled: bool, status: dict) -> str | None:
    if items:
        return None
    if not enabled:
        return EMPTY_DISABLED
    if not status.get("has_terminal"):
        return EMPTY_NOT_YET
    last = status.get("last_extract") or {}
    if (last.get("outcome") == "skipped"
            and last.get("reason_code") == _NO_NEW_REASON):
        return EMPTY_NO_NEW
    return EMPTY_EMPTY


def _empty_state_reason(empty: str | None, status: dict) -> str | None:
    """Причина пустоты с реальным исходом последнего прохода.

    «Пусто» само по себе не объясняет сбой: если последний проход был
    пропущен по валидации или упал, причина это называет
    (`empty:skipped:validation_failed`, `empty:failed:writer_failed`).
    """
    if empty is None:
        return None
    if empty not in (EMPTY_EMPTY, EMPTY_NO_NEW):
        return empty
    last = status.get("last_extract") or {}
    parts = [empty]
    outcome = last.get("outcome")
    if outcome and outcome != "success":
        parts.append(str(outcome))
    code = last.get("reason_code")
    if code:
        parts.append(str(code))
    return ":".join(parts)


def _freshness(items: list, status: dict) -> str | None:
    """Свежесть фактов по последнему проходу экстракции, без натяжек.

    «has_items» — только когда проход реально успешен. Провал, пропуск по
    другой причине и неизвестное состояние называются своими словами.
    """
    if not items:
        return None
    if status.get("events_unavailable"):
        return FRESH_UNKNOWN
    last = status.get("last_extract") or {}
    if not last:
        return FRESH_UNKNOWN
    if _pass_ok(last):
        return FRESH_HAS_ITEMS
    if (last.get("outcome") == "skipped"
            and last.get("reason_code") == _NO_NEW_REASON):
        return EMPTY_NO_NEW
    if last.get("outcome") == "failed":
        return FRESH_EXTRACT_FAILED
    if last.get("outcome") == "skipped":
        return FRESH_EXTRACT_SKIPPED
    return FRESH_UNKNOWN


async def new_facts_widget(db, *, chat_id: int | None = None,
                           limit: int = 16, now_ts: int | None = None,
                           flags: dict | None = None) -> dict:
    """Контракт виджета «Новые факты» (EVOL-007).

    Факты не выдумываются. Два чата не смешиваются, если задан chat_id.
    Global явно подписан. Пустое состояние выводится из флага и событий,
    а не из пустого списка само по себе.
    """
    scope, label, cid = _scope(chat_id)
    try:
        rows = await db.dossier_feed(limit=limit, chat_id=cid, now_ts=now_ts)
    except Exception:
        logger.warning("[memory_diagnostics] dossier_feed failed",
                       exc_info=True)
        return _load_failed(cid, reason="dossier_feed_failed")
    items = [_widget_item(row) for row in rows or []]
    if cid is not None:
        items = [item for item in items if int(item["chat_id"]) == cid]
    try:
        values, sources = await resolve_flags(cid, flags)
        enabled = bool(values["graph_rag_enabled"])
        enabled_source = sources["graph_rag_enabled"]
    except Exception:
        logger.warning("[memory_diagnostics] extract flag unreadable",
                       exc_info=True)
        if not items:
            return _load_failed(cid, reason="extract_flag_unreadable")
        enabled = None
        enabled_source = "unreadable"
    try:
        status = await facts_extract_status(db, cid)
    except Exception:
        logger.warning("[memory_diagnostics] extract status unreadable",
                       exc_info=True)
        if not items:
            failed = _load_failed(cid, reason="extract_status_unreadable")
            failed["extraction_enabled"] = enabled
            failed["extraction_enabled_source"] = enabled_source
            failed["updates_disabled"] = (enabled is False)
            return failed
        status = {
            "has_terminal": None,
            "last_successful_extract_at": None,
            "last_extract": None,
            "events_unavailable": True,
        }
    empty = _empty_state(items, enabled=bool(enabled), status=status) \
        if enabled is not None and status.get("has_terminal") is not None \
        else (None if items else EMPTY_LOAD_FAILED)
    if items:
        empty = None
    return {
        "scope": scope,
        "scope_label": label,
        "chat_id": cid,
        "items": items,
        "ordered_by": "created_at_desc",
        "empty_state": empty,
        "empty_state_reason": _empty_state_reason(empty, status),
        "extraction_enabled": enabled,
        "extraction_enabled_source": enabled_source,
        "updates_disabled": (enabled is False),
        "last_successful_extract_at": status.get("last_successful_extract_at"),
        "last_extract": status.get("last_extract"),
        "freshness": _freshness(items, status),
        "events_unavailable": bool(status.get("events_unavailable")),
        "timestamp_sources": dict(_TIMESTAMP_SOURCES),
    }


def _stage(name: str, *, enabled: bool, source: str,
           last_success_at: int | None, last_error_at: int | None,
           last_error_class: str | None, last_error_reason: str | None,
           extra: dict | None = None) -> dict:
    if not enabled:
        state = "disabled"
    elif last_success_at is None and last_error_at is None:
        state = "never_run"
    else:
        state = "ran"
    body = {
        "stage": name,
        "state": state,
        "enabled": bool(enabled),
        "enabled_source": source,
        "last_success_at": last_success_at,
        "last_error_at": last_error_at,
        "last_error_class": last_error_class,
        "last_error_reason": last_error_reason,
    }
    if extra:
        body.update(extra)
    return body


async def _dream_marks(db, chat_id: int | None) -> list[dict]:
    clause, params = _scope_clause(chat_id)
    return await _fetchall(
        db,
        "SELECT kind, status, MAX(run_at) AS ts FROM memory_dream_log "
        "WHERE 1=1" + clause + " GROUP BY kind, status",
        params)


def _mark(rows: list[dict], kind: str, statuses: tuple[str, ...]) -> int | None:
    best = None
    for row in rows:
        if row.get("kind") != kind:
            continue
        if statuses and str(row.get("status") or "") not in statuses:
            continue
        ts = _int_or_none(row.get("ts"))
        if ts is not None and (best is None or ts > best):
            best = ts
    return best


async def _event_extrema(db, event_name: str, chat_id: int | None) -> dict:
    clause, params = _scope_clause(chat_id)
    success = await _fetchone(
        db,
        "SELECT MAX(ts) AS ts FROM mca_events "
        "WHERE event_name = ? AND outcome = 'success'" + clause,
        [event_name, *params])
    failed = await _fetchone(
        db,
        "SELECT ts, reason_code, error_json FROM mca_events "
        "WHERE event_name = ? AND outcome = 'failed'" + clause +
        " ORDER BY ts DESC, id DESC LIMIT 1",
        [event_name, *params])
    return {
        "success_at": _int_or_none(success.get("ts")) if success else None,
        "error_at": _int_or_none(failed.get("ts")) if failed else None,
        "error_class": _error_class(failed.get("error_json")) if failed else None,
        "error_reason": (failed.get("reason_code") or None) if failed else None,
    }


def _later(a: int | None, b: int | None) -> int | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _pick_error(log_at: int | None, event: dict, *, log_reason: str
                ) -> tuple[int | None, str | None, str | None]:
    """Берём более позднее реальное событие. Класс старого mca-события
    не приписываем более новому журналу, где класса нет."""
    event_at = event.get("error_at")
    if log_at is None and event_at is None:
        return None, None, None
    if event_at is not None and (log_at is None or event_at >= log_at):
        return event_at, event.get("error_class"), event.get("error_reason")
    return log_at, None, log_reason


async def _one_cycle(db, chat_id: int | None, flags: dict | None) -> dict:
    scope, label, cid = _scope(chat_id)
    values, sources = await resolve_flags(cid, flags)
    rows = await _dream_marks(db, cid)
    persona_events = await _event_extrema(db, "persona_traits", cid)
    sleep_events = await _event_extrema(db, "sleep_dream", cid)

    sleep_success = _later(
        _mark(rows, "run", ("ok",)),
        _mark(rows, "distilled", ("ok",)))
    sleep_success = _later(sleep_success, sleep_events["success_at"])
    sleep_error_at, sleep_error_class, sleep_error_reason = _pick_error(
        _mark(rows, "error", ()), sleep_events, log_reason="dream_log_error")

    deep_success = _mark(rows, "deep_run", ("ok",))
    deep_error_at = _mark(rows, "deep_skip", ("error",))
    deep_error_class = None
    deep_error_reason = "error" if deep_error_at is not None else None

    persona_success = _later(
        _mark(rows, "deep_traits", ("done",)),
        persona_events["success_at"])
    persona_error_at, persona_error_class, persona_error_reason = _pick_error(
        _mark(rows, "deep_traits", ("error",)), persona_events,
        log_reason="deep_traits_error")

    persona_extra = {"invoked_by": "deep_sleep"}
    if (values["persona_enabled"] and not values["deep_sleep_enabled"]
            and persona_success is None and persona_error_at is None):
        persona_extra["not_invoked_because"] = "deep_sleep_disabled"

    return {
        "scope": scope,
        "scope_label": label,
        "chat_id": cid,
        "schedule": schedule_view(),
        "stages": {
            "sleep": _stage(
                "sleep", enabled=values["dream_enabled"],
                source=sources["dream_enabled"],
                last_success_at=sleep_success,
                last_error_at=sleep_error_at,
                last_error_class=sleep_error_class,
                last_error_reason=sleep_error_reason),
            "deep_sleep": _stage(
                "deep_sleep", enabled=values["deep_sleep_enabled"],
                source=sources["deep_sleep_enabled"],
                last_success_at=deep_success,
                last_error_at=deep_error_at,
                last_error_class=deep_error_class,
                last_error_reason=deep_error_reason),
            "personality": _stage(
                "personality", enabled=values["persona_enabled"],
                source=sources["persona_enabled"],
                last_success_at=persona_success,
                last_error_at=persona_error_at,
                last_error_class=persona_error_class,
                last_error_reason=persona_error_reason,
                extra=persona_extra),
        },
    }


async def memory_cycle_status(db, *, chat_id: int | None = None,
                              chat_ids: list[int] | None = None,
                              flags: dict | None = None) -> dict:
    """EVOL-008: состояние Sleep / Deep Sleep / Personality.

    Не запускает воркеры и не пишет в журнал. disabled и never_run
    различаются: выключенный флаг — disabled даже без строк; включённый
    флаг без единого прогона — never_run.
    """
    body = await _one_cycle(db, chat_id, flags)
    if chat_ids:
        per_chat = {}
        for raw in chat_ids:
            cid = int(raw)
            per_chat[str(cid)] = await _one_cycle(db, cid, flags)
        body["per_chat"] = per_chat
    return body


async def _skip_counts(db, chat_id: int | None) -> dict:
    clause, params = _scope_clause(chat_id)
    extract_rows = await _fetchall(
        db,
        "SELECT COALESCE(reason_code, '') AS reason, COUNT(*) AS c "
        "FROM mca_events WHERE event_name = ? AND outcome = 'skipped'"
        + clause + " GROUP BY reason_code",
        [_EXTRACT_EVENT, *params])
    dream_rows = await _fetchall(
        db,
        "SELECT kind, COALESCE(status, '') AS status, COUNT(*) AS c "
        "FROM memory_dream_log WHERE kind IN ('skipped', 'deep_skip')"
        + clause + " GROUP BY kind, status",
        params)
    unconfirmed = await _fetchone(
        db,
        "SELECT COUNT(*) AS c FROM graph_facts WHERE status = 'unconfirmed'"
        + clause,
        params)
    return {
        "extract_skipped_by_reason": {
            str(row["reason"] or "unknown"): int(row["c"])
            for row in extract_rows
        },
        "dream_skipped_by_status": {
            f"{row['kind']}:{row['status'] or 'unknown'}": int(row["c"])
            for row in dream_rows
        },
        "unconfirmed_facts": int(unconfirmed["c"]) if unconfirmed else 0,
    }


async def _extract_usage(db, chat_id: int | None) -> dict:
    """EVOL-009: число кандидатов прохода экстракции из `usage_json`.

    Пишет их сам проход (`services/summary_memory.py:3759-3761` →
    `mca_events.usage_json`). `candidates` = saved + skipped + deduped +
    superseded, плюс `text_only` и исход прохода отдельно. Старое событие
    без usage_json — None (честное «неизвестно»), не ноль.
    `unconfirmed_facts` кандидатами не считается: это состояние фактов.
    """
    clause, params = _scope_clause(chat_id)
    rows = await _fetchall(
        db,
        "SELECT ts, outcome, reason_code, stage, usage_json FROM mca_events "
        "WHERE event_name = ? AND outcome != 'start'" + clause +
        " ORDER BY ts DESC, id DESC",
        [_EXTRACT_EVENT, *params])
    last_terminal = None
    if rows:
        head = rows[0]
        body = {
            "at": _int_or_none(head.get("ts")),
            "outcome": head.get("outcome"),
            "reason_code": head.get("reason_code") or None,
            "stage": head.get("stage") or None,
        }
        body.update(_usage_counts(_usage_dict(head.get("usage_json"))))
        last_terminal = body
    keys = (*_EXTRACT_COUNT_KEYS, "text_only", "candidates")
    sums = {key: 0 for key in keys}
    seen: set[str] = set()
    with_usage = 0
    for row in rows:
        usage = _usage_dict(row.get("usage_json"))
        if usage is None:
            continue
        with_usage += 1
        counts = _usage_counts(usage)
        for key in keys:
            value = counts.get(key)
            if value is None:
                continue
            sums[key] += value
            seen.add(key)
    total = {
        "terminal_passes": len(rows),
        "passes_with_usage": with_usage,
        "passes_without_usage": len(rows) - with_usage,
        # Покрывает ли сумма все проходы scope. False — сумма только по
        # проходам с usage_json, и это не «ноль» по остальным.
        "covers_all_passes": (len(rows) - with_usage) == 0,
    }
    for key in keys:
        total[key] = sums[key] if (with_usage and key in seen) else None
    return {"last_terminal": last_terminal, "total": total}


async def _recent_error(db, chat_id: int | None) -> dict | None:
    clause, params = _scope_clause(chat_id)
    placeholders = ",".join("?" * len(_MEMORY_ERROR_EVENTS))
    event = await _fetchone(
        db,
        "SELECT ts, event_name, outcome, reason_code, error_json "
        "FROM mca_events WHERE outcome = 'failed' "
        f"AND event_name IN ({placeholders})" + clause +
        " ORDER BY ts DESC, id DESC LIMIT 1",
        [*_MEMORY_ERROR_EVENTS, *params])
    dream = await _fetchone(
        db,
        "SELECT run_at, kind, status FROM memory_dream_log "
        "WHERE (kind = 'error' OR status = 'error')" + clause +
        " ORDER BY run_at DESC, id DESC LIMIT 1",
        params)
    event_ts = _int_or_none(event.get("ts")) if event else None
    dream_ts = _int_or_none(dream.get("run_at")) if dream else None
    if event_ts is None and dream_ts is None:
        return None
    if dream_ts is not None and (event_ts is None or dream_ts > event_ts):
        return {
            "at": dream_ts,
            "source": "memory_dream_log",
            "event_name": dream.get("kind"),
            "error_class": None,
            "reason_code": dream.get("status") or dream.get("kind"),
        }
    return {
        "at": event_ts,
        "source": "mca_events",
        "event_name": event.get("event_name") if event else None,
        "error_class": _error_class(event.get("error_json")) if event else None,
        "reason_code": (event.get("reason_code") or None) if event else None,
    }


async def _search_tables(db, chat_id: int | None, now_ts: int) -> dict:
    fts = await _table_exists(db, "graph_facts_fts")
    vec = await _table_exists(db, "graph_facts_vec")
    backlog = None
    backlog_reason = None
    if not vec:
        backlog_reason = "vec_table_absent"
    else:
        clause, params = _scope_clause(chat_id)
        try:
            row = await _fetchone(
                db,
                "SELECT COUNT(*) AS c FROM graph_facts "
                "WHERE (expires_at IS NULL OR expires_at > ?) "
                "AND id NOT IN (SELECT fact_id FROM graph_facts_vec)"
                + clause,
                [int(now_ts), *params])
            backlog = int(row["c"]) if row else None
        except Exception:
            logger.debug("[memory_diagnostics] backlog query failed",
                         exc_info=True)
            backlog = None
            backlog_reason = "backlog_query_failed"
    return {
        "fts_table": fts,
        "vec_table": vec,
        "indexing_backlog": backlog,
        "indexing_backlog_reason": backlog_reason,
    }


async def latest_new_fact_at(db, chat_id: int | None, now_ts: int
                             ) -> int | None:
    clause, params = _scope_clause(chat_id)
    row = await _fetchone(
        db,
        "SELECT MAX(created_at) AS ts FROM graph_facts "
        "WHERE status = 'confirmed' AND target_user IS NOT NULL "
        "AND fact IS NOT NULL AND fact != '' "
        "AND (expires_at IS NULL OR expires_at > ?)" + clause,
        [int(now_ts), *params])
    return _int_or_none(row.get("ts")) if row else None


def resolve_search(*, fts_table: bool, vec_table: bool,
                   vector_runtime: bool | None) -> dict:
    """FTS-fallback не выдаётся за работающие embeddings.

    vector_runtime=None — проверка не выполнялась: vector_ok остаётся false.
    Таблицы vec нет — vector_ok false даже если runtime-заглушка сказала true.
    """
    runtime_ok = bool(vector_runtime) if vector_runtime is not None else False
    vector_available = bool(vec_table and runtime_ok)
    fts_available = bool(fts_table)
    if vector_available:
        mode = "vector"
    elif fts_available:
        mode = "fts_only"
    else:
        mode = "unavailable"
    return {
        "fts_available": fts_available,
        "vector_available": vector_available,
        "vector_runtime_known": vector_runtime is not None,
        "embeddings_working": vector_available,
        "search_mode": mode,
    }


async def memory_health_diagnostics(
        db, *, chat_id: int | None = None,
        now_ts: int | None = None,
        flags: dict | None = None,
        vector_runtime: bool | None = None,
        vector_probe: Callable[[], Any] | None = None) -> dict:
    """EVOL-009: админская диагностика памяти (данные, не UI).

    `vector_probe` — внедряемая проверка runtime embeddings (тесты подменяют).
    Если проба не передана, runtime считается неизвестным и embeddings_working
    остаётся false: наличие только FTS не означает, что векторы работают.
    """
    scope, label, cid = _scope(chat_id)
    ts = int(now_ts if now_ts is not None else time.time())
    if vector_probe is not None and vector_runtime is None:
        try:
            probed = vector_probe()
            if hasattr(probed, "__await__"):
                probed = await probed
            vector_runtime = bool(probed)
        except Exception:
            logger.debug("[memory_diagnostics] vector probe failed",
                         exc_info=True)
            vector_runtime = False
    tables = await _search_tables(db, cid, ts)
    search = resolve_search(
        fts_table=tables["fts_table"],
        vec_table=tables["vec_table"],
        vector_runtime=vector_runtime)
    # Жёсткий инвариант: fts_only никогда не выглядит как рабочие embeddings.
    if search["search_mode"] != "vector":
        search["embeddings_working"] = False
        search["vector_available"] = False
    cycle = await _one_cycle(db, cid, flags)
    extract = await facts_extract_status(db, cid)
    return {
        "scope": scope,
        "scope_label": label,
        "chat_id": cid,
        "last_successful_extract_at": extract["last_successful_extract_at"],
        "last_extract": extract["last_extract"],
        "last_sleep_success_at": cycle["stages"]["sleep"]["last_success_at"],
        "last_deep_sleep_success_at": (
            cycle["stages"]["deep_sleep"]["last_success_at"]),
        "last_personality_update_at": (
            cycle["stages"]["personality"]["last_success_at"]),
        "last_new_fact_at": await latest_new_fact_at(db, cid, ts),
        "counts": await _skip_counts(db, cid),
        "extract_usage": await _extract_usage(db, cid),
        "search": search,
        "indexing_backlog": tables["indexing_backlog"],
        "indexing_backlog_reason": tables["indexing_backlog_reason"],
        "recent_error": await _recent_error(db, cid),
        "stages": cycle["stages"],
    }
