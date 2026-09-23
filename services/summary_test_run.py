"""S9 round1026 (ADR-1026-8 D2/D3/D5) — dry-run тест-контур «Тестирование» (§113).

Отдельный путь прогона пайплайна Эпика 2 **без побочных эффектов**:
``build_test_rows`` (read-only окно + S1/S2) → ``run_l1`` → ``build_fact_package``
→ ``run_l2`` → форматтер (rich/plain). Инвариант **0 публикаций / 0 изменений
памяти / 0 ``generate_image``** (D2): модуль физически не вызывает
``telegram_send.*`` / ``SummaryGenerator._deliver_*`` / ``_send_*`` /
``summary_memory.*`` / ``compress_and_purge`` / ``memorize_facts`` /
``get_window_messages`` / ``generate_image``. «Предпросмотр Rich Message» —
локальный рендер ``format_rich_html``/``format_plain_html`` (не отправка).

ON-путь (``L1 → пакет → L2``) включается **per-run** прямыми вызовами
``run_l1``/``run_l2`` (S3/S5 не зависят от ``SUMMARY_HYBRID_L2_ENABLED``):
глобальный kill-switch и per-chat override **не читаются и не пишутся**; ровно
**2** физических LLM-вызова (L1+L2). Телеметрия ``llm_usage_events`` (PG) —
операционная (не память/досье), источник метрик §112; при недоступности PG/
цены → «Нет данных» (не выдуманный ``$0``).

Fail-closed §106 (D5): коды ``TEST_*`` + R17-safe диагностика (этап/код/причина/
модель/host/HTTP-статус/попытки) — без ключей/текстов/сырых ответов. Публикация
и запись в память запрещены; повторов нет (retry-политика — у LLM-клиента).
"""
from __future__ import annotations

import dataclasses
import logging
import time

from config.settings import settings
from services import hot_config as hot
from services import usage_events
from services import web_runtime
from services.budget_limits import context_state
from services.database import row_get
from services.summary_article_formatter import (
    format_plain_html,
    format_rich_html,
)
from services.summary_context_restore import build_l1_payload
from services.summary_fact_package import build_fact_package
from services.summary_l1_clusterizer import provider_host as _host_of, run_l1
from services.summary_l2_writer import run_l2
# S7 (ADR-1026-9 D2/D5): этапные FORMAT_* переиспользуются тест-контуром.
from services.summary_run_log import log_format_complete, log_format_start

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# ── Коды fail-closed §106 (D5) ─────────────────────────────────────────────
TEST_NO_GENERATOR = "TEST_NO_GENERATOR"
TEST_WINDOW_EMPTY = "TEST_WINDOW_EMPTY"
TEST_L1_EMPTY = "TEST_L1_EMPTY"
TEST_L1_INVALID = "TEST_L1_INVALID"
TEST_L1_ERROR = "TEST_L1_ERROR"
TEST_PACKAGE_NOT_DELIVERABLE = "TEST_PACKAGE_NOT_DELIVERABLE"
TEST_L2_INVALID = "TEST_L2_INVALID"
TEST_L2_ERROR = "TEST_L2_ERROR"
TEST_LLM_UNAVAILABLE = "TEST_LLM_UNAVAILABLE"
TEST_FORMAT_ERROR = "TEST_FORMAT_ERROR"
# B-R1026S9-2: непредвиденное исключение оркестрации (catch-all API-слоя).
TEST_RUN_FAILED = "TEST_RUN_FAILED"

# ── Статусы тест-прогона (D3) ──────────────────────────────────────────────
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_INVALID = "invalid"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

# ── §112: честные метки (без выдуманных значений) ──────────────────────────
NO_DATA = "Нет данных"
UNLIMITED_LABEL = "Без лимита"
PUBLICATION_DRY_RUN = "не публиковалось (dry-run)"
COVER_NOT_GENERATED = "не генерировалась"

# §113/§4.3: per-message cap текста в предпросмотре (R17/объём).
PER_MESSAGE_CAP = 2000
WINDOW_HOURS_MIN = 1
WINDOW_HOURS_MAX = 720
# Паритет с `summary_generator._SUMMARY_CONTEXT_TOKEN_DEFAULT` (30000).
CONTEXT_TOKEN_DEFAULT = 30000

_LLM_ERROR_REASONS = frozenset({"llm_error", "llm_timeout"})

_USAGE_SQL = (
    "SELECT step, COALESCE(SUM(input_tokens), 0) AS in_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS out_tokens, "
    "COALESCE(SUM(cost_usd), 0) AS cost, "
    "COALESCE(BOOL_AND(price_known), false) AS price_known, "
    "COUNT(*) AS calls "
    "FROM llm_usage_events WHERE correlation_id = $1 AND module = 'summary' "
    "GROUP BY step"
)

_STEP_MAP = {"l1_clusterizer": "l1", "l2_writer": "l2"}


@dataclasses.dataclass
class TestRunResult:
    """Результат dry-run тест-прогона (§4.2; R17-safe, без секретов/сырых ответов).

    ``publication`` всегда ``{"status": "not_published", "reason": "dry_run"}`` —
    тест-прогон ничего не публикует. ``artifacts`` — реальные объекты S1–S5;
    ``diagnostics`` — R17-safe коды по этапам; ``display`` — totals/усечение.
    """

    schema_version: int
    test_id: str
    status: str
    chat_id: int
    window: dict
    dry_run: bool
    publication: dict
    stages: dict
    artifacts: dict
    metrics: dict
    diagnostics: list
    display: dict

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


# ── Валидация/резолв входа ─────────────────────────────────────────────────

def resolve_window_hours(window) -> int:
    """``window`` → часы (1..720); ``None``/мусор → настроенное ``SUMMARY_WINDOW_HOURS``.

    Невалидное значение **клампится** (не падаем); это вход тест-прогона, а не
    публикация — консервативный безопасный дефолт.
    """
    raw = None
    if isinstance(window, dict):
        raw = window.get("hours")
    elif isinstance(window, (int, float)) and not isinstance(window, bool):
        raw = window
    if raw is None:
        raw = hot.get("limits.summary_window_hours", settings.SUMMARY_WINDOW_HOURS)
    try:
        hours = int(float(raw))
    except (TypeError, ValueError):
        hours = int(float(settings.SUMMARY_WINDOW_HOURS))
    return max(WINDOW_HOURS_MIN, min(WINDOW_HOURS_MAX, hours))


# ── Сериализация артефактов (§4.3, усечение срезами) ───────────────────────

def _message_view(row) -> dict:
    """Строка окна → R17-safe предпросмотр (cap 2000 символов с пометкой)."""
    text = row_get(row, "text")
    text = "" if text is None else str(text)
    truncated = len(text) > PER_MESSAGE_CAP
    return {
        "message_id": row_get(row, "tg_message_id"),
        "timestamp": row_get(row, "timestamp"),
        "author": row_get(row, "author_name"),
        "user_id": row_get(row, "user_id"),
        "reply_to_id": row_get(row, "reply_to_id"),
        "media_type": row_get(row, "media_type"),
        "text": text[:PER_MESSAGE_CAP],
        "truncated": truncated,
    }


def _clusters(l1_result) -> list:
    """Кластеры L1 (§95) — реальные треды канонизированного payload."""
    payload = getattr(l1_result, "payload", None)
    if not isinstance(payload, dict):
        return []
    threads = payload.get("threads")
    if not isinstance(threads, list):
        return []
    return [
        {
            "thread_id": t.get("thread_id"),
            "topic": t.get("topic"),
            "message_ids": list(t.get("message_ids") or []),
            "facts": [
                {"text": f.get("text"),
                 "evidence_message_ids": list(f.get("evidence_message_ids") or [])}
                for f in (t.get("facts") or []) if isinstance(f, dict)
            ],
        }
        for t in threads if isinstance(t, dict)
    ]


def _artifacts(rows_info: dict, l1_result, package_result, l2_result,
               rich: str, plain: str) -> dict:
    package = getattr(package_result, "package", None)
    document = getattr(l2_result, "document", None)
    return {
        "source": [_message_view(r) for r in rows_info.get("source") or []],
        "filtered": [_message_view(r) for r in rows_info.get("filtered") or []],
        "dropped": [_message_view(r) for r in rows_info.get("dropped") or []],
        "restored": [_message_view(r) for r in rows_info.get("restored") or []],
        "clusters": _clusters(l1_result),
        "package": package,
        "article": document,
        "rich_preview": rich,
        "plain_preview": plain,
    }


# ── Метрики §112 ───────────────────────────────────────────────────────────

def _fmt_int(value) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return NO_DATA


def _fmt_cost(value) -> str:
    try:
        return f"${float(value):.6f}"
    except (TypeError, ValueError):
        return NO_DATA


async def _collect_usage(pg, correlation_id: str) -> dict | None:
    """Токены/стоимость из ``llm_usage_events`` (PG) по ``correlation_id``.

    ``None`` — нет PG/телеметрия OFF/ошибка чтения → «Нет данных» (§112).
    ``cost`` известен только когда ``price_known`` у всех событий этапа.
    """
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None or not usage_events.is_enabled():
        return None
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_USAGE_SQL, correlation_id)
    except Exception:
        logger.warning(
            "SUMMARY_TEST_USAGE_READ_FAILED | run_id=%s — metrics=no_data",
            correlation_id)
        return None
    rows = list(rows or [])
    if not rows:
        # Нет событий (dedicated-слот/телеметрия не дошла) → «Нет данных»,
        # а не выдуманный $0 (§112/REQ-S9-09).
        return None
    out: dict = {"l1": None, "l2": None}
    total_in = total_out = 0
    total_cost = 0.0
    total_known = True
    for row in rows:
        step = _STEP_MAP.get(str(row["step"] or ""))
        if step is None:
            continue
        in_tokens = int(row["in_tokens"] or 0)
        out_tokens = int(row["out_tokens"] or 0)
        known = bool(row["price_known"])
        out[step] = {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "cost_usd": float(row["cost"] or 0.0) if known else None,
            "price_known": known,
            "calls": int(row["calls"] or 0),
        }
        total_in += in_tokens
        total_out += out_tokens
        if known:
            total_cost += float(row["cost"] or 0.0)
        else:
            total_known = False
    both_steps = bool(out["l1"]) and bool(out["l2"])
    out["total"] = {
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": round(total_cost, 6) if (total_known and both_steps)
        else None,
        "price_known": bool(total_known and both_steps),
    }
    return out


def _token_display(step_usage, key: str) -> str:
    if not step_usage:
        return NO_DATA
    value = step_usage.get(key)
    return _fmt_int(value) if value is not None else NO_DATA


def _cost_display(step_usage) -> str:
    if not step_usage or not step_usage.get("price_known"):
        return NO_DATA
    value = step_usage.get("cost_usd")
    return _fmt_cost(value) if value is not None else NO_DATA


def _budget_info() -> dict:
    """Бюджет контекста L2-входа: безлимит (`-1`) → «Без лимита» (§112).

    ``0``/``None`` (unset) → эффективный дефолт ``CONTEXT_TOKEN_DEFAULT``
    (паритет ``resolve_context_tokens``); ``>0`` → cap; ``<0`` → безлимит.
    """
    raw = hot.get("limits.summary_max_context_tokens",
                  getattr(settings, "SUMMARY_MAX_CONTEXT_TOKENS", None))
    state = context_state(raw)
    if state == "unlimited":
        return {"kind": "tokens", "unlimited": True, "display": UNLIMITED_LABEL}
    if state == "cap":
        return {"kind": "tokens", "unlimited": False,
                "display": f"{_fmt_int(raw)} токенов"}
    return {"kind": "tokens", "unlimited": False,
            "display": f"{_fmt_int(CONTEXT_TOKEN_DEFAULT)} токенов"}


def _metrics(rows_info: dict, l1_result, package_result, l2_result,
             usage: dict | None, duration_ms: float) -> dict:
    fm = rows_info.get("filter_metrics") or {}
    l1_usage = (usage or {}).get("l1")
    l2_usage = (usage or {}).get("l2")
    total_usage = (usage or {}).get("total")
    return {
        "source_count": rows_info.get("source_count", 0),
        "filtered_count": rows_info.get("filtered_count", 0),
        "restored_count": rows_info.get("restored_count", 0),
        "drop_percent": fm.get("drop_percent"),
        "filter_status": fm.get("status"),
        "threads_count": getattr(l1_result, "threads_count", 0),
        "facts_count": getattr(l1_result, "facts_count", 0),
        "tokens": {
            "l1": {"input": _token_display(l1_usage, "input_tokens"),
                   "output": _token_display(l1_usage, "output_tokens")},
            "l2": {"input": _token_display(l2_usage, "input_tokens"),
                   "output": _token_display(l2_usage, "output_tokens")},
            "total": {"input": _token_display(total_usage, "input_tokens"),
                      "output": _token_display(total_usage, "output_tokens")},
        },
        "cost": {
            "l1": _cost_display(l1_usage),
            "l2": _cost_display(l2_usage),
            "total": _cost_display(total_usage),
        },
        "duration_ms": round(duration_ms, 1),
        "budget": _budget_info(),
        "cover_status": COVER_NOT_GENERATED,
        "publication_status": PUBLICATION_DRY_RUN,
    }


# ── Диагностика (R17-safe) ─────────────────────────────────────────────────

def _diag(stage: str, code: str, reason: str | None = None, *,
          model: str = "", base_url: str = "", http_status=None,
          attempts=None) -> dict:
    return {
        "stage": stage,
        "code": code,
        "reason": reason,
        "model": str(model or ""),
        "provider_host": _host_of(base_url) if base_url else "",
        "http_status": http_status,
        "attempts": attempts,
    }


def _llm_error_code(stage: str, reason: str | None) -> str:
    if str(reason or "") in _LLM_ERROR_REASONS:
        return TEST_LLM_UNAVAILABLE
    return TEST_L1_ERROR if stage == "l1" else TEST_L2_ERROR


# ── Каркас результата ──────────────────────────────────────────────────────

def _empty_metrics() -> dict:
    """§112: контракт-валидные «пустые» метрики для error-путей (B-R1026S9-2).

    Ключи полностью совпадают с ``_metrics`` — UI/JS могут безопасно читать
    ``tokens``/``cost``/``budget``/``drop_percent`` даже когда прогон не дошёл
    до метрик; неизвестное — «Нет данных», без выдуманных ``$0``.
    """
    return {
        "source_count": 0,
        "filtered_count": 0,
        "restored_count": 0,
        "drop_percent": None,
        "filter_status": None,
        "threads_count": 0,
        "facts_count": 0,
        "tokens": {
            "l1": {"input": NO_DATA, "output": NO_DATA},
            "l2": {"input": NO_DATA, "output": NO_DATA},
            "total": {"input": NO_DATA, "output": NO_DATA},
        },
        "cost": {"l1": NO_DATA, "l2": NO_DATA, "total": NO_DATA},
        "duration_ms": 0.0,
        "budget": _budget_info(),
        "cover_status": COVER_NOT_GENERATED,
        "publication_status": PUBLICATION_DRY_RUN,
    }


def _empty_artifacts() -> dict:
    """§113: контракт-валидные «пустые» артефакты для error-путей."""
    return {
        "source": [], "filtered": [], "dropped": [], "restored": [],
        "clusters": [], "package": None, "article": None,
        "rich_preview": "", "plain_preview": "",
    }


def _empty_display() -> dict:
    return {"truncated_display": False, "has_more": False, "totals": {}}


def _base_result(*, test_id: str, chat_id: int, window: dict,
                 status: str) -> TestRunResult:
    return TestRunResult(
        schema_version=SCHEMA_VERSION,
        test_id=test_id,
        status=status,
        chat_id=chat_id,
        window=window,
        dry_run=True,
        publication={"status": "not_published", "reason": "dry_run"},
        stages={},
        artifacts=_empty_artifacts(),
        metrics=_empty_metrics(),
        diagnostics=[],
        display=_empty_display(),
    )


def error_result(*, test_id: str, chat_id: int, window: dict | None = None,
                 status: str = STATUS_ERROR, code: str = TEST_RUN_FAILED,
                 reason: str = "run_failed") -> TestRunResult:
    """Контракт-валидный error-результат с диагностикой (B-R1026S9-2).

    Используется API-слоем для непредвиденных исключений ``_execute``: UI
    всегда получает полные ``metrics``/``artifacts``/``display`` и видимую
    диагностику (§5.3/§7), а не ``undefined.l1``.
    """
    result = _base_result(test_id=test_id, chat_id=int(chat_id),
                          window=window or {}, status=status)
    result.diagnostics.append(_diag("init", code, reason))
    return result


def empty_payload(*, test_id: str, status: str, chat_id: int) -> dict:
    """Пустой контракт-валидный payload без результата (running/edge, D4).

    Гарантирует наличие ``metrics``/``artifacts``/``display`` (B-R1026S9-2):
    клиент при polling никогда не получает неполную структуру.
    """
    result = _base_result(test_id=test_id, chat_id=int(chat_id),
                          window={}, status=status)
    return present_result(result)


def _has_more(artifacts: dict, totals: dict) -> bool:
    for key, total in totals.items():
        if len(artifacts.get(key) or []) < total:
            return True
    return False


def _finalize(result: TestRunResult, *, rows_info=None, l1_result=None,
              package_result=None, l2_result=None, usage=None,
              rich="", plain="", started=None) -> TestRunResult:
    if rows_info is not None:
        result.artifacts = _artifacts(
            rows_info, l1_result, package_result, l2_result, rich, plain)
    result.metrics = _metrics(
        rows_info or {}, l1_result, package_result, l2_result, usage,
        (time.perf_counter() - started) * 1000.0 if started else 0.0)
    totals = {
        "source": (rows_info or {}).get("source_count", 0),
        "filtered": (rows_info or {}).get("filtered_count", 0),
    }
    result.display = {
        "truncated_display": any(
            m.get("truncated") for m in (result.artifacts.get("source") or [])),
        "has_more": _has_more(result.artifacts, totals),
        "totals": totals,
    }
    return result


# ── Ядро dry-run ───────────────────────────────────────────────────────────

async def run_summary_test(chat_id, window, *, allow_cover=False,
                           correlation_id=None, generator=None,
                           pg=None) -> TestRunResult:
    """Dry-run прогон пайплайна Эпика 2 (§113) без побочных эффектов (D2).

    ``generator`` — ``SummaryGenerator`` (``None`` → ``web_runtime``); нет
    генератора → ``status="error"``, код ``TEST_NO_GENERATOR`` (API → 503).
    ``pg`` — пул PG для метрик §112 (``None`` → «Нет данных»). ``allow_cover``
    принимается для совместимости контракта, но **не** генерирует обложку:
    генерация — только отдельным эндпоинтом подтверждения (D3/§4.5).
    """
    started = time.perf_counter()
    correlation_id = correlation_id or usage_events.new_correlation_id()
    test_id = correlation_id
    hours = resolve_window_hours(window)
    now_ts = int(time.time())
    since_ts = now_ts - hours * 3600
    window_info = {"hours": hours, "from_ts": since_ts, "to_ts": now_ts,
                   "messages": 0}
    result = _base_result(test_id=test_id, chat_id=int(chat_id),
                          window=window_info, status=STATUS_ERROR)

    if generator is None:
        generator = web_runtime.get_summary_generator()
    if generator is None:
        result.status = STATUS_ERROR
        result.diagnostics.append(_diag("init", TEST_NO_GENERATOR,
                                        "no_summary_generator"))
        return result

    llm = getattr(generator, "llm", None)
    model = str(getattr(llm, "_chat_model", "") or "")
    base_url = str(getattr(llm, "_base_url", "") or "")

    try:
        rows_info = await generator.build_test_rows(
            int(chat_id), since_ts=since_ts, correlation_id=correlation_id)
    except Exception as exc:
        # S7 (T-3400, L-R1026S9-8): R17 — без traceback/сырых текстов; только
        # тип ошибки (диагностика кода — в diagnostics, §109-детали — в TEST_*).
        logger.warning(
            "SUMMARY_TEST_WINDOW_FAILED | run_id=%s | chat_id=%s | error_type=%s",
            correlation_id, chat_id, type(exc).__name__)
        result.status = STATUS_ERROR
        result.diagnostics.append(_diag(
            "filter", TEST_WINDOW_EMPTY, "window_read_error",
            model=model, base_url=base_url))
        return result

    window_info["messages"] = rows_info.get("source_count", 0)
    fm = rows_info.get("filter_metrics") or {}
    result.stages["filter"] = {
        "status": fm.get("status") or ("ok" if rows_info.get("source") else "empty"),
        "source_count": rows_info.get("source_count", 0),
        "saved_count": fm.get("saved_count", rows_info.get("filtered_count", 0)),
        "restored_count": rows_info.get("restored_count", 0),
        "drop_percent": fm.get("drop_percent"),
        "duration_ms": fm.get("duration_ms"),
    }

    # §106: пустое окно → LLM не вызывается.
    if not rows_info.get("source"):
        result.status = STATUS_EMPTY
        result.diagnostics.append(_diag(
            "filter", TEST_WINDOW_EMPTY, "window_empty",
            model=model, base_url=base_url))
        return _finalize(result, rows_info=rows_info, started=started)

    # S3: L1 «Кластеризатор» (ровно 1 LLM-вызов).
    l1_result = await run_l1(
        llm=llm, rows=rows_info.get("filtered") or [], chat_id=int(chat_id),
        correlation_id=correlation_id)
    result.stages["l1"] = {
        "status": getattr(l1_result, "status", None),
        "threads": getattr(l1_result, "threads_count", 0),
        "facts": getattr(l1_result, "facts_count", 0),
        "auto_unassigned": getattr(l1_result, "auto_unassigned_count", 0),
        "truncated": getattr(l1_result, "truncated", False),
        "model": model,
        "duration_ms": getattr(l1_result, "duration_ms", None),
    }
    if not l1_result.usable:
        status = getattr(l1_result, "status", STATUS_ERROR)
        reason = getattr(l1_result, "invalid_reason", None)
        if status == "empty":
            result.status = STATUS_SKIPPED
            code = TEST_L1_EMPTY
        elif status == "invalid":
            result.status = STATUS_INVALID
            code = TEST_L1_INVALID
        else:
            result.status = STATUS_ERROR
            code = _llm_error_code("l1", reason)
        result.diagnostics.append(_diag(
            "l1", code, reason, model=model, base_url=base_url))
        return _finalize(result, rows_info=rows_info, l1_result=l1_result,
                         started=started)

    # S4: пакет фактов §96 (0 LLM).
    payload_items = build_l1_payload(rows_info.get("filtered") or [],
                                     int(chat_id))
    package_result = build_fact_package(
        l1_result, payload_items, correlation_id=correlation_id)
    pm = getattr(package_result, "metrics", {}) or {}
    result.stages["package"] = {
        "status": getattr(package_result, "status", None),
        "reason": getattr(package_result, "reason", None),
        "threads": pm.get("threads_count", 0),
        "facts": pm.get("facts_count", 0),
        "fragments": pm.get("fragments_count", 0),
        "duration_ms": pm.get("duration_ms"),
    }
    if not package_result.deliverable:
        result.status = STATUS_SKIPPED
        result.diagnostics.append(_diag(
            "package", TEST_PACKAGE_NOT_DELIVERABLE,
            getattr(package_result, "reason", None) or "not_deliverable",
            model=model, base_url=base_url))
        return _finalize(result, rows_info=rows_info, l1_result=l1_result,
                         package_result=package_result, started=started)

    # S5: L2 «Писатель» (ровно 1 LLM-вызов) — ON per-run, флаг не читается.
    service = (package_result.package or {}).get("service") or {}
    l2_result = await run_l2(
        llm, package_result.package, service=service,
        correlation_id=correlation_id, chat_id=int(chat_id))
    result.stages["l2"] = {
        "status": getattr(l2_result, "status", None),
        "reason": getattr(l2_result, "invalid_reason", None),
        "paragraphs": len((getattr(l2_result, "document", None) or {})
                          .get("paragraphs") or []),
        "model": model,
        "duration_ms": getattr(l2_result, "duration_ms", None),
    }
    if not l2_result.usable:
        status = getattr(l2_result, "status", STATUS_ERROR)
        reason = getattr(l2_result, "invalid_reason", None)
        if status == "empty":
            result.status = STATUS_SKIPPED
            code = TEST_L2_INVALID
        elif status == "invalid":
            result.status = STATUS_INVALID
            code = TEST_L2_INVALID
        else:
            result.status = STATUS_ERROR
            code = _llm_error_code("l2", reason)
        result.diagnostics.append(_diag(
            "l2", code, reason, model=model, base_url=base_url))
        return _finalize(result, rows_info=rows_info, l1_result=l1_result,
                         package_result=package_result, l2_result=l2_result,
                         started=started)

    # Форматтер §105 (локальный рендер, без отправки).
    # S7 (ADR-1026-9 D2/D5): этапные FORMAT_START/COMPLETE — тот же run_id;
    # ошибка остаётся тест-кодом TEST_FORMAT_ERROR (§113), не FORMAT_ERROR.
    document = l2_result.document
    paragraphs = len((document or {}).get("paragraphs") or [])
    rich = plain = ""
    format_started = log_format_start(
        run_id=correlation_id, chat_id=int(chat_id), channel="rich")
    try:
        rich = format_rich_html(document)
        plain = format_plain_html(document)
        log_format_complete(
            run_id=correlation_id, chat_id=int(chat_id), channel="rich",
            paragraphs=paragraphs, started=format_started)
        result.stages["format"] = {"status": "ok", "rich_len": len(rich),
                                   "plain_len": len(plain)}
    except Exception as exc:
        # L-R1026S7-3 (R17-хардненинг, как T-3400): без traceback/сырых
        # текстов — только тип ошибки и стабильный reason.
        logger.warning(
            "SUMMARY_TEST_FORMAT_ERROR | run_id=%s | chat_id=%s | "
            "error_type=%s | reason=formatter_error",
            correlation_id, chat_id, type(exc).__name__)
        try:
            plain = format_plain_html(document)
        except Exception:
            plain = ""
        result.stages["format"] = {"status": "error", "rich_len": 0,
                                   "plain_len": len(plain)}
        result.diagnostics.append(_diag(
            "format", TEST_FORMAT_ERROR, "formatter_error",
            model=model, base_url=base_url))

    result.stages["cover"] = {"status": "not_generated"}
    result.stages["publication"] = {"status": "not_published",
                                    "reason": "dry_run"}
    result.status = STATUS_OK
    usage = await _collect_usage(pg, correlation_id)
    return _finalize(result, rows_info=rows_info, l1_result=l1_result,
                     package_result=package_result, l2_result=l2_result,
                     usage=usage, rich=rich, plain=plain, started=started)


def present_result(result: TestRunResult, *, offset: int = 0,
                   limit: int = 50) -> dict:
    """Срез артефактов для API (пагинация ``offset``/``limit``, §4.3).

    Полные артефакты остаются в store; наружу — окно ``limit`` (по умолчанию 50)
    с явными ``display.totals``/``has_more``. Тексты уже усечены до 2000 симв.
    """
    data = result.as_dict()
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        limit = 50
    # B-R1026S9-2: контракт-валидность ответа — даже «пустой»/error-результат
    # всегда отдаёт полные metrics/artifacts/display (UI не падает на undefined).
    metrics = data.get("metrics")
    if not isinstance(metrics, dict) or "tokens" not in metrics:
        metrics = _empty_metrics()
    else:
        merged_metrics = _empty_metrics()
        merged_metrics.update(metrics)
        data["metrics"] = merged_metrics
        metrics = merged_metrics
    data["metrics"] = metrics
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = _empty_artifacts()
    else:
        merged_artifacts = _empty_artifacts()
        merged_artifacts.update(artifacts)
        artifacts = merged_artifacts
    sliced: dict = {}
    total_all = 0
    for key, value in artifacts.items():
        if isinstance(value, list):
            total_all += len(value)
            sliced[key] = value[offset:offset + limit]
        else:
            sliced[key] = value
    data["artifacts"] = sliced
    data["display"] = {
        "truncated_display": bool((data.get("display") or {})
                                  .get("truncated_display")),
        "has_more": total_all > offset + limit,
        "offset": offset,
        "limit": limit,
        "totals": (data.get("display") or {}).get("totals", {}),
    }
    return data
