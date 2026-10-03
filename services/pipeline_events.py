"""ASAP-4 волна E (T-4440, spec §5 E.1, ADR-1028-7 D8) — стадийные события
пайплайна Саммари.

ЕДИНАЯ точка эмиссии стадий текстовой ветки (`SUMMARY_RUN_START →
SOURCE_WINDOW → L1 → L2 → L2_REVIEW → LEGACY_FALLBACK? → SUMMARY_RUN_DONE`)
через существующий транспорт mca-17a (`mca_trace.emit_stage` →
`mca_events.build_event` → durable `mca_events`). **Второго store/эмиттера
нет** (§61.11; события COVER_* ветки обложки живут в `cover_style_jobs`
через тот же `emit_stage`). Существующие human-логи (`summary_run_log`)
остаются как есть — логи и Analytics получают данные из одного structured
source (§61.12).

Kill-switch `SUMMARY_PIPELINE_EVENTS_ENABLED` (env-only, default ON, spec
§8.2): OFF → событий нет (бит-в-бит прежний контур), Run Inspector строит
вид из state-проекций (in-memory снапшоты + события COVER_*).

R17: наружу только id/числа/коды/enum; сырые тексты/промпты/ключи не
передаются. Fail-open: любая ошибка эмиссии не рвёт пайплайн.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── имена событий (свободная ось event_name mca-13 — словаря не требуют) ────
EV_SUMMARY_START = "SUMMARY_RUN_START"
EV_SOURCE_WINDOW = "SUMMARY_SOURCE_WINDOW"
EV_L1_STAGE = "SUMMARY_L1_STAGE"
EV_L2_STAGE = "SUMMARY_L2_STAGE"
EV_L2_REVIEW = "SUMMARY_L2_REVIEW"
EV_LEGACY_FALLBACK = "SUMMARY_LEGACY_FALLBACK"
EV_SUMMARY_DONE = "SUMMARY_RUN_DONE"
# ── ASAP 4.1 волна 2 (spec §7.3, ADR-1028-8 D8): аддитивные имена зоны A.
# Существующие имена НЕ переименовываются (совместимость mca_events/Analytics).
EV_SOURCE_WINDOW_READY = "SUMMARY_SOURCE_WINDOW_READY"
EV_CAPACITY_RESOLVED = "SUMMARY_CAPACITY_RESOLVED"
EV_EXECUTION_MODE_SELECTED = "SUMMARY_EXECUTION_MODE_SELECTED"
EV_SEGMENT_PLAN = "SUMMARY_SEGMENT_PLAN"
EV_SEGMENT_RESULT = "SUMMARY_SEGMENT_RESULT"
EV_SEGMENT_LEDGER = "SUMMARY_SEGMENT_LEDGER"

# ── ASAP 4.1 волна 4 (spec §4 D/§7.3; ADR-1028-8 D5): liveness события
# Supervisor'а. SUMMARY_L1_ACTIVITY / SUMMARY_WRITER_ACTIVITY — срезы
# активности LLM-стадий (execution mode / attempt / ttfa / watchdog);
# SUMMARY_LLM_SUPERVISOR — общий журнал решений (fallback/fuse/other ops).
EV_L1_ACTIVITY = "SUMMARY_L1_ACTIVITY"
EV_WRITER_ACTIVITY = "SUMMARY_WRITER_ACTIVITY"
EV_LLM_SUPERVISOR = "SUMMARY_LLM_SUPERVISOR"

# ── ASAP 4.1 волна 7 (зона G, T-4624; spec §7.3): оставшиеся имена перечня
# §42 ТЗ. Существующие имена НЕ переименовываются (совместимость
# mca_events/Analytics); append-only; fail-open эмиссия; R17 — только
# числа/коды/id (§43 ТЗ, 23507–23528).
EV_TEXT_READY = "SUMMARY_TEXT_READY"
EV_REVISION_RESULT = "SUMMARY_REVISION_RESULT"

# R17-safe коды причин (mca_events.REASON_CODES) — маппинг сырых причин.
_REASON_MAP = {
    # L1-контракт (summary_l1_contract).
    "too_many_facts": "too_many_facts",
    "too_many_threads": "too_many_threads",
    "too_many_facts_total": "too_many_facts_total",
    # Классы LLM-ошибок (type name / reason-строка).
    "LLMRateLimitError": "rate_limit",
    "LLMTimeoutError": "timeout",
    "LLMServerError": "provider_unavailable",
    "LLMError": "provider_unavailable",
    # ── ASAP 4.1 волна 4 (T-4615, spec D.5): READ-SIDE alias только —
    # совместимость СТАРЫХ логов/событий (2.58.46): old llm_client
    # time-budget строки читаются под новыми кодами. Новые эмиссии старого
    # кода для Summary-канала запрещены (rename под Supervisor'ом);
    # не-Summary потребители llm_client логируют как раньше.
    "total_budget_exceeded": "execution_deadline_exceeded",
    "budget_exhausted": "retry_time_budget_exhausted",
}

def events_enabled() -> bool:
    """Kill-switch волны E (spec §8.2): default ON; OFF → событий нет."""
    try:
        from config.settings import settings
        return bool(getattr(settings, "SUMMARY_PIPELINE_EVENTS_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return False


def map_reason(raw) -> str | None:
    """Сырая причина → код из `REASON_CODES` (неизвестное → None)."""
    text = str(raw or "").strip()
    if not text:
        return None
    code = _REASON_MAP.get(text)
    if code:
        return code
    from services.mca_events import REASON_CODES
    return text if text in REASON_CODES else None


def _emit(event_name: str, *, outcome: str, level: str, run_id,
          chat_id=None, stage: str | None = None, duration_ms=None,
          reason_code=None, status=None, model=None, provider=None,
          attempt=None, counts: dict | None = None) -> None:
    """Fail-open обёртка над `mca_trace.emit_stage` (единый transport)."""
    if not events_enabled():
        return
    try:
        from services import mca_trace as trace
        fields = {}
        if chat_id is not None:
            fields["chat_id"] = chat_id
        if duration_ms is not None:
            try:
                fields["duration_ms"] = max(0, int(float(duration_ms)))
            except (TypeError, ValueError):
                pass
        if attempt is not None:
            try:
                fields["attempt"] = int(attempt)
            except (TypeError, ValueError):
                pass
        if counts:
            # R17-safe числа/коды (bounded JSON — build_event сериализует
            # с sanitize и капом 2000).
            fields["usage_json"] = counts
        trace.emit_stage(
            event_name, outcome=outcome, level=level,
            component="summary", stage=stage,
            reason_code=map_reason(reason_code) if reason_code else None,
            status=status, model=model, provider=provider,
            **fields,
            **trace.span_fields(run_id=str(run_id or "") or None,
                                pipeline_type="summary"))
    except Exception:      # pragma: no cover - эмиссия не рвёт пайплайн
        return


def summary_start(run_id, *, chat_id, mode: str, manual: bool) -> None:
    """`SUMMARY_RUN_START` (outcome=start) — первая точка прогона."""
    _emit(EV_SUMMARY_START, outcome="start", level="INFO", run_id=run_id,
          chat_id=chat_id, stage="start",
          counts={"mode": str(mode or ""), "manual": bool(manual)})


def source_window(run_id, *, chat_id, messages: int) -> None:
    """`SUMMARY_SOURCE_WINDOW` — размер окна после чтения истории."""
    _emit(EV_SOURCE_WINDOW, outcome="success", level="INFO", run_id=run_id,
          chat_id=chat_id, stage="source",
          counts={"input_count": int(messages or 0)})


# ── ASAP 4.1 волна 2 (T-4603/T-4604/T-4606; spec §7.3): новые события зоны A.
# Аддитивные; существующие события не изменяются. R17: только counts/числа/
# enum/коды (без текстов сообщений/промптов/ключей). Fail-open как везде.

def source_window_ready(run_id, *, chat_id, counts: dict,
                        window_from=None, window_to=None) -> None:
    """`SUMMARY_SOURCE_WINDOW_READY` — SourceWindow создан (T-4603).

    counts: messages / durable (bool) — snapshot записан (kill-switch ON) /
    нет; window_from/to — UTC-мет границ окна (числа, R17)."""
    payload = dict(counts or {})
    payload.setdefault("messages", 0)
    if window_from is not None:
        payload["window_from"] = int(window_from)
    if window_to is not None:
        payload["window_to"] = int(window_to)
    _emit(EV_SOURCE_WINDOW_READY, outcome="success", level="INFO",
          run_id=run_id, chat_id=chat_id, stage="source", counts=payload)


def capacity_resolved(run_id, *, chat_id, provider=None, model=None,
                      counts: dict | None = None) -> None:
    """`SUMMARY_CAPACITY_RESOLVED` — effective capacity резолвится
    capacity engine'ом (T-4604/T-4605; причина в counts.reason, R17-код)."""
    _emit(EV_CAPACITY_RESOLVED, outcome="success", level="INFO",
          run_id=run_id, chat_id=chat_id, stage="capacity",
          provider=provider, model=model, counts=counts or {})


def execution_mode_selected(run_id, *, chat_id, mode: str, reason: str,
                            counts: dict | None = None) -> None:
    """`SUMMARY_EXECUTION_MODE_SELECTED` — решение WHOLE_WINDOW /
    CAPACITY_OVERFLOW (+человеческая причина для Inspector-карточки)."""
    _emit(EV_EXECUTION_MODE_SELECTED, outcome="success", level="INFO",
          run_id=run_id, chat_id=chat_id, stage="capacity",
          status=str(mode or ""),
          counts={"reason": str(reason or ""), **(counts or {})})


def segment_plan(run_id, *, chat_id, segments: int,
                 counts: dict | None = None) -> None:
    """`SUMMARY_SEGMENT_PLAN` — план overflow-шардинга (число сегментов =
    ожидаемые L1-запросы; A.3: L1-запросов = число сегментов)."""
    _emit(EV_SEGMENT_PLAN, outcome="start", level="INFO", run_id=run_id,
          chat_id=chat_id, stage="l1_overflow",
          counts={"segments": int(segments or 0), **(counts or {})})


def segment_result(run_id, *, chat_id, segment: int, usable: bool,
                   reason_code=None, counts: dict | None = None) -> None:
    """`SUMMARY_SEGMENT_RESULT` — исход одного сегмента (restore виден)."""
    _emit(EV_SEGMENT_RESULT,
          outcome="success" if usable else "failed",
          level="INFO" if usable else "WARN",
          run_id=run_id, chat_id=chat_id, stage="l1_overflow",
          attempt=int(segment), reason_code=reason_code,
          status="ok" if usable else "failed",
          counts=counts or {})


def segment_ledger(run_id, *, chat_id, status: dict) -> None:
    """`SUMMARY_SEGMENT_LEDGER` — снапшот CoverageLedger (counts/percent;
    missing>0 ИЛИ fallback>0 (сегмент не восстановился) → честный degraded,
    уровень WARN, не masked-success; T-4606/spec §1 A.3)."""
    missing = int((status or {}).get("missing") or 0)
    fallback = int((status or {}).get("fallback") or 0)
    complete = bool((status or {}).get("assignment_lossless")) \
        and missing == 0 and fallback == 0
    _emit(EV_SEGMENT_LEDGER,
          outcome="success" if complete else "failed",
          level="INFO" if complete else "WARN",
          run_id=run_id, chat_id=chat_id, stage="l1_overflow",
          reason_code=None if complete else "coverage_ledger_missing",
          status="ok" if complete else "degraded",
          counts=status or {})


# ── ASAP 4.1 волна 4 (T-4612–T-4615, spec §4 D): события LLMExecutionSupervisor.
# R17: только числа/коды/enum/provider host (без текстов/промптов/ключей).
# Fail-open как везде.

_ACT_STAGE = {
    "l1": "l1",
    "writer": "l2",
    "reviewer": "l2_review",
    "revision": "l2_review",
    "legacy": "legacy",
}


def llm_activity(run_id, *, chat_id, operation: str, outcome: str,
                 level: str, counts: dict | None = None, attempt=None,
                 provider=None, model=None, status: str | None = None,
                 reason_code=None, duration_ms=None) -> None:
    """Активность supervised LLM-вызова (T-4613/T-4614).

    operation l1 → `SUMMARY_L1_ACTIVITY`; writer/reviewer/revision →
    `SUMMARY_WRITER_ACTIVITY`; прочие (legacy) → общий
    `SUMMARY_LLM_SUPERVISOR`. counts — R17-safe (mode/op/bucket/ttfa/
    http_attempts/deadline_source)."""
    op = str(operation or "").strip().lower()
    event = EV_L1_ACTIVITY if op == "l1" else (
        EV_WRITER_ACTIVITY if op in ("writer", "reviewer", "revision")
        else EV_LLM_SUPERVISOR)
    _emit(event, outcome=outcome, level=level, run_id=run_id,
          chat_id=chat_id, stage=_ACT_STAGE.get(op, op or "llm"),
          attempt=attempt, provider=provider, model=model, status=status,
          reason_code=reason_code, duration_ms=duration_ms,
          counts={"op": op, **(counts or {})})


def llm_supervisor(run_id, *, chat_id, operation: str, outcome: str,
                   level: str, counts: dict | None = None, attempt=None,
                   provider=None, model=None, status: str | None = None,
                   reason_code=None) -> None:
    """`SUMMARY_LLM_SUPERVISOR` — общий журнал решений Supervisor'а
    (fallback-решения, watchdog/fuse, прочие операции)."""
    _emit(EV_LLM_SUPERVISOR, outcome=outcome, level=level, run_id=run_id,
          chat_id=chat_id, stage=_ACT_STAGE.get(str(operation or ""),
                                                "llm"),
          attempt=attempt, provider=provider, model=model, status=status,
          reason_code=reason_code, counts=counts or {})


def l1_stage(run_id, *, chat_id, usable: bool, invalid_reason=None,
             duration_ms=None, threads=None, counts: dict | None = None) -> None:
    """`SUMMARY_L1_STAGE` — исход кластеризатора (ok/invalid).

    Волна 3 (T-4607/T-4608, R6-G-001): `counts` — честный срез semantic map
    (map_degraded/minimal-map) рядом с результатом; `None` — прежний срез
    (бит-в-бит)."""
    status = "ok" if usable else "failed"
    _emit(EV_L1_STAGE,
          outcome="success" if usable else "failed",
          level="INFO" if usable else "WARN",
          run_id=run_id, chat_id=chat_id, stage="l1",
          duration_ms=duration_ms, reason_code=None if usable
          else str(invalid_reason or "invalid"),
          status=status,
          counts={"threads": int(threads) if threads is not None else None,
                  **(counts or {})})


def l2_stage(run_id, *, chat_id, usable: bool, invalid_reason=None,
             duration_ms=None, paragraphs=None) -> None:
    """`SUMMARY_L2_STAGE` — исход писателя (ok/unusable)."""
    _emit(EV_L2_STAGE,
          outcome="success" if usable else "failed",
          level="INFO" if usable else "WARN",
          run_id=run_id, chat_id=chat_id, stage="l2",
          duration_ms=duration_ms,
          reason_code=None if usable
          else str(invalid_reason or "error"),
          status="ok" if usable else "failed",
          counts={"output_count": int(paragraphs)
                  if paragraphs is not None else None})


def l2_review(run_id, *, chat_id, metrics: dict) -> None:
    """`SUMMARY_L2_REVIEW` — исход bounded review loop (волна D).

    Статус лестницы: ok (first-pass approved) / repaired (после revision) /
    rejected (unusable → Legacy). Причина — доминирующий код review."""
    metrics = metrics or {}
    calls = int(metrics.get("l2_review_calls", 0) or 0)
    if calls <= 0:
        return
    final_approved = int(metrics.get("l2_final_approved", 0) or 0)
    rejected = int(metrics.get("l2_legacy_after_review", 0) or 0)
    degraded = int(metrics.get("l2_review_degraded", 0) or 0)
    if rejected:
        status, reason = "failed", "l2_review_rejected"
    elif degraded:
        status, reason = "degraded", "review_degraded"
    elif final_approved:
        status, reason = "ok", None
    else:
        status, reason = "repaired", "quote_attribution_repaired"
    _emit(EV_L2_REVIEW,
          outcome="failed" if rejected else "success",
          level="WARN" if rejected else "INFO",
          run_id=run_id, chat_id=chat_id, stage="l2_review",
          reason_code=reason, status=status,
          attempt=int(metrics.get("l2_revision_count", 0) or 0),
          counts={
              "first_pass_approved": int(
                  metrics.get("l2_first_pass_approved", 0) or 0),
              "revision_count": int(metrics.get("l2_revision_count", 0) or 0),
              "revision_fixed": int(
                  metrics.get("l2_revision_fixed_count", 0) or 0),
              "review_calls": calls,
          })


def legacy_fallback(run_id, *, chat_id, trigger: str, from_stage: str) -> None:
    """`SUMMARY_LEGACY_FALLBACK` — резервный контур спас run (§61.7)."""
    _emit(EV_LEGACY_FALLBACK, outcome="success", level="INFO", run_id=run_id,
          chat_id=chat_id, stage="legacy_fallback",
          reason_code="fallback_engaged", status="fallback",
          counts={"trigger": str(trigger or "")[:64],
                  "fallback_from": str(from_stage or "")[:32]})


def summary_done(run_id, *, chat_id, status: str, health: str | None,
                 duration_ms=None, reason_code=None,
                 counts: dict | None = None) -> None:
    """`SUMMARY_RUN_DONE` — терминальное событие прогона (§61.11-срез).

    `counts` — R17-safe агрегат: coverage/source_total/source_considered/
    publication/message_id/fallback/package_grade (числа/коды/enum)."""
    level = "INFO"
    if status == "failed":
        level = "ERROR"
    elif status in ("degraded", "empty"):
        level = "WARN"
    _emit(EV_SUMMARY_DONE,
          outcome="failed" if status == "failed" else "success",
          level=level,
          run_id=run_id, chat_id=chat_id, stage="done",
          duration_ms=duration_ms,
          reason_code=None if status == "ok" else str(reason_code or status),
          status=str(health or status),
          counts=counts or {})


def summary_done_from_ctx(ctx) -> None:
    """`SUMMARY_RUN_DONE` из RunContext (S7) — единая точка в `finally`.

    R17-safe срез: только числа/коды/enum (§61.11: coverage/publication/
    fallback/package_grade). Duck-typed (legacy-тесты с object.__new__
    не должны падать — обёрнуто в try)."""
    try:
        if ctx is None or not getattr(ctx, "run_id", None):
            return
        pub_status = getattr(ctx, "publish_status", None)
        pub_channel = getattr(ctx, "publish_channel", None)
        publication = None
        if pub_status == "ok":
            publication = str(pub_channel or "text")
        elif pub_status == "failed":
            publication = "failed"
        counts = {
            "coverage": (round(float(ctx.source_coverage), 4)
                         if getattr(ctx, "source_coverage", None) is not None
                         else None),
            "source_total": getattr(ctx, "source_total", None),
            "source_considered": getattr(ctx, "source_considered", None),
            "publication": publication,
            "message_id": getattr(ctx, "publish_message_id", None),
            "fallback": str(getattr(ctx, "fallback", "none") or "none"),
            "package_grade": getattr(ctx, "package_grade", None),
            "pipeline_health": getattr(ctx, "pipeline_health", None),
        }
        counts = {k: v for k, v in counts.items() if v is not None}
        summary_done(
            ctx.run_id, chat_id=getattr(ctx, "chat_id", None),
            status=str(getattr(ctx, "status", "") or "ok"),
            health=getattr(ctx, "pipeline_health", None),
            duration_ms=ctx.duration_ms(),
            reason_code=getattr(ctx, "reason", None),
            counts=counts)
    except Exception:      # pragma: no cover - эмиссия не рвёт пайплайн
        return


# ── ASAP 4.1 волна 7 (зона G, T-4624; spec §7.3) — оставшиеся события
# перечня §42 ТЗ. Аддитивно; существующие имена не трогаются. R17:
# числа/коды/safe id (§43 ТЗ); fail-open как везде.

def text_ready(run_id, *, chat_id, counts: dict | None = None,
               stage: str = "l2") -> None:
    """`SUMMARY_TEXT_READY` — approved text snapshot зафиксирован
    (checkpoint TEXT_READY §20; snapshot-источник cover-ветки T-4618)."""
    _emit(EV_TEXT_READY, outcome="success", level="INFO", run_id=run_id,
          chat_id=chat_id, stage=stage, counts={"text_ready": 1,
                                                **(counts or {})})


def revision_result(run_id, *, chat_id, attempt: int, usable: bool,
                    repair_target: str | None = None,
                    reason_code=None, counts: dict | None = None) -> None:
    """`SUMMARY_REVISION_RESULT` — исход одной revision-попытки bounded
    review loop (≤2; patch/full-doc виден). §42 ТЗ REVISION_START/RESULT."""
    _emit(EV_REVISION_RESULT,
          outcome="success" if usable else "failed",
          level="INFO" if usable else "WARN",
          run_id=run_id, chat_id=chat_id, stage="l2_review",
          attempt=max(0, int(attempt or 0)),
          reason_code=reason_code,
          status="ok" if usable else "failed",
          counts={"repair_target": str(repair_target or ""),
                  **(counts or {})})


__all__ = [
    "EV_SUMMARY_START", "EV_SOURCE_WINDOW", "EV_L1_STAGE", "EV_L2_STAGE",
    "EV_L2_REVIEW", "EV_LEGACY_FALLBACK", "EV_SUMMARY_DONE",
    "EV_SOURCE_WINDOW_READY", "EV_CAPACITY_RESOLVED",
    "EV_EXECUTION_MODE_SELECTED", "EV_SEGMENT_PLAN", "EV_SEGMENT_RESULT",
    "EV_SEGMENT_LEDGER", "EV_L1_ACTIVITY", "EV_WRITER_ACTIVITY",
    "EV_LLM_SUPERVISOR", "EV_TEXT_READY", "EV_REVISION_RESULT",
    "events_enabled", "map_reason", "summary_start", "source_window",
    "source_window_ready", "capacity_resolved", "execution_mode_selected",
    "segment_plan", "segment_result", "segment_ledger",
    "llm_activity", "llm_supervisor",
    "l1_stage", "l2_stage", "l2_review", "legacy_fallback", "summary_done",
    "summary_done_from_ctx", "text_ready", "revision_result",
]
