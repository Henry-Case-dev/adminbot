"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D8/D9; spec §3.3/
§3.11/§3.13/§42–§48/§49–§52/§68–§70/§92) — Cover Style durable job + fail-soft
ladder + observability.

Durable job **REUSE** существующей инфраструктуры MCA (второй очереди НЕТ,
§42/Q6): `task_jobs` (v14) через `TaskJobStore`, `mca_pipeline_runs` (v19) +
`mca_events` (v15) через `mca_trace`/`mca_events`. State machine §42 маппится на
`task_jobs.status/reason_code/checkpoint_ref`; provider `task_id` (async) —
в payload/снимке состояния.

Style stage (§3.2/§23): нормализующий edit поверх готовой base cover —
capability-gated (§38), НЕ перегенерирует base при падении (§49).
Fail-soft ladder (§4/§49–§52): `styled → base(style_failed) → Rich без обложки
(base_failed) → plain(rich_failed)`.

R17: лог-поля — только whitelist (`prompt length/hash`, counts, длительности,
provider/model, task id); API key/полный prompt/raw Summary/приватные URL не
логируются.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field

from config.settings import settings
from services import cover_style_assets as assets
from services import cover_style_registry as registry
from services import image_capabilities as cap
from services import image_prompt_compiler as compiler
from services.cover_style_edit import EditResult, edit_image
from services.cover_style_pipeline import (
    KEY_STYLE_API_KEY,
    KEY_IMAGE_API_KEY,
    MODEL_MODE_CUSTOM,
    SLOT_SOURCE_CONNECTIONS_DEFAULT,
    SLOT_SOURCE_GLOBAL_IMAGE,
    SLOT_SOURCE_GLOBAL_STYLE,
    SLOT_SOURCE_PROFILE_CONNECTION,
    check_edit_allowed,
    cover_styles_enabled,
    pipeline_mode,
    resolve_effective_edit_capability,
    resolve_style_slot,
    resolve_style_slot_inherited,
    slot_capabilities,
    uses_style_stage,
)

logger = logging.getLogger(__name__)

# ── §44: события стадий ─────────────────────────────────────────────────────
COVER_PIPELINE_START = "COVER_PIPELINE_START"
COVER_BASE_SUBMITTED = "COVER_BASE_SUBMITTED"
COVER_BASE_RUNNING = "COVER_BASE_RUNNING"
COVER_BASE_SUCCEEDED = "COVER_BASE_SUCCEEDED"
COVER_BASE_FAILED = "COVER_BASE_FAILED"
# ASAP-4 волна B (spec §2 B.1, T-4415): selection snapshot на старте cover
# publication — до base generation и style edit (для medved_press видно до
# image API). R17-safe: только id/числа/enum.
COVER_STYLE_SELECTION = "COVER_STYLE_SELECTION"
COVER_STYLE_START = "COVER_STYLE_START"
COVER_STYLE_SUBMITTED = "COVER_STYLE_SUBMITTED"
COVER_STYLE_RUNNING = "COVER_STYLE_RUNNING"
COVER_STYLE_SUCCEEDED = "COVER_STYLE_SUCCEEDED"
COVER_STYLE_FAILED = "COVER_STYLE_FAILED"
# ASAP-4 волна B (spec §2 B.4, T-4419): видимый fail-open — ранний выход
# Style stage с отдельной причиной (ничего не молчит).
COVER_STYLE_SKIPPED = "COVER_STYLE_SKIPPED"
COVER_RICH_PUBLISH_START = "COVER_RICH_PUBLISH_START"
COVER_RICH_PUBLISH_SUCCEEDED = "COVER_RICH_PUBLISH_SUCCEEDED"
COVER_RICH_PUBLISH_FAILED = "COVER_RICH_PUBLISH_FAILED"
COVER_PLAIN_FALLBACK = "COVER_PLAIN_FALLBACK"
COVER_PIPELINE_DONE = "COVER_PIPELINE_DONE"

# ── §96: классификация cover-result ─────────────────────────────────────────
RESULT_STYLED = "styled"
RESULT_BASE = "base"
RESULT_NONE = "none"
RESULT_PLAIN = "plain_send_message"
REASON_STYLE_FAILED = "style_failed"
REASON_BASE_FAILED = "base_failed"
REASON_RICH_FAILED = "rich_failed"
# ── ASAP-4 волна B (spec §2 B.4, T-4419): distinct reason codes ранних
# выходов. Каждый — отдельный reason/event; `style_failed` остаётся
# umbrella'ом для provider-фейлов уже после реальной submission.
REASON_NO_STYLE = "no_style"
REASON_PROFILE_MISSING = "profile_missing"
REASON_DISABLED = "disabled"
REASON_CONNECTION_MISSING = "connection_missing"
REASON_REFERENCE_MISSING = "reference_missing"
REASON_CAPABILITY_UNKNOWN = "capability_unknown"
REASON_NOT_CONFIGURED = "not_configured"
REASON_NO_STYLE_STAGE = "style_stage_not_applicable"

# ── T-4619/T-4620 (spec §6 F.2/F.3; ADR-1028-8 D7.2): событие резолва
# Style-слота с ИСТОЧНИКОМ наследования (лестница §35 — точная причина
# видима, не generic `style_failed`).
COVER_STYLE_RESOLVE = "COVER_STYLE_RESOLVE"

# Конфигурационные/ранние причины — проходят в mca_events reason_code как
# есть (прод-факт Q14: `not_configured` больше не схлопывается в generic).
STYLE_REASON_CODES = frozenset({
    REASON_STYLE_FAILED, "edit_unsupported", REASON_NO_STYLE,
    REASON_PROFILE_MISSING, REASON_DISABLED, REASON_CONNECTION_MISSING,
    REASON_REFERENCE_MISSING, REASON_CAPABILITY_UNKNOWN,
    REASON_NOT_CONFIGURED, REASON_NO_STYLE_STAGE,
    "prompt_limit_exceeded", "route_unverified",
    # ASAP 4.4 (§2, T-4875): 400-too-long без числа и его bounded retry.
    "prompt_limit_unknown", "prompt_limit_unknown_after_retry",
})


def style_reason_code(reason: str) -> str:
    """mca_events `reason_code` без generic-схлопывания (§2 B.4).

    Конфигурационные/ранние причины — как есть; provider-фейлы после
    реальной submission (timeout/network/http_*) — umbrella `style_failed`
    (точная причина видна в `reason=` лога и meta.fail_reason).
    """
    reason = str(reason or "")
    return reason if reason in STYLE_REASON_CODES else REASON_STYLE_FAILED


# §43: человекочитаемые причины (run detail/Analytics; Wave E подключит UI).
REASON_DETAILS_RU = {
    REASON_NO_STYLE: "стиль не выбран («Без дополнительного стиля»)",
    REASON_PROFILE_MISSING: "профиль стиля не найден",
    REASON_DISABLED: "профиль стиля отключён",
    "edit_unsupported": ("модель не умеет редактировать готовые изображения"),
    REASON_CONNECTION_MISSING: ("подключение модели не найдено "
                                "(удалено или недоступно)"),
    REASON_REFERENCE_MISSING: ("референсы стиля недоступны "
                               "(нет в реестре/файл отсутствует/повреждён)"),
    REASON_CAPABILITY_UNKNOWN: ("возможности модели не определены "
                                "(capability source неизвестен)"),
    REASON_NOT_CONFIGURED: ("не настроены адрес/модель обработки "
                            "(Connections layer)"),
    REASON_NO_STYLE_STAGE: ("режим профиля без Style-стадии"),
    "prompt_limit_exceeded": ("инструкция стиля превышает лимит модели — "
                              "применена базовая обложка"),
    "prompt_limit_unknown": ("провайдер отклонил промпт как слишком длинный, "
                             "точный лимит не сообщён — применена базовая "
                             "обложка"),
    "prompt_limit_unknown_after_retry": ("промпт отклонён как слишком "
                                         "длинный даже после сокращения — "
                                         "применена базовая обложка"),
    "route_unverified": ("маршрут редактирования модели не подтверждён — "
                         "применена базовая обложка"),
    REASON_STYLE_FAILED: ("обработка стилем не завершилась "
                          "(ошибка провайдера)"),
}


def reason_detail_ru(reason: str) -> str:
    """Человекочитаемая причина по reason-коду (§43; R17-safe — только коды)."""
    return REASON_DETAILS_RU.get(str(reason or ""), "")


def style_skip_status(reason: str) -> str:
    """§43: формулировка run detail «Обработка стилем — не выполнена…»."""
    detail = reason_detail_ru(reason)
    if not detail:
        return ""
    return "Обработка стилем — не выполнена. Причина: %s." % detail

# ── §48/§75: человекочитаемые RU-статусы ────────────────────────────────────
RU_STYLE_FAILED = ("Обработка стилем не завершилась вовремя. "
                   "Использована базовая обложка.")
RU_BASE_FAILED = ("Базовая обложка не получилась. Статья отправлена без "
                  "изображения.")
RU_RICH_FAILED = ("Не удалось отправить оформленную статью. "
                  "Публикуем обычным сообщением.")

# ── §42: conceptual state machine ───────────────────────────────────────────
STATE_CREATED = "CREATED"
STATE_BASE_SUBMITTED = "BASE_SUBMITTED"
STATE_BASE_RUNNING = "BASE_RUNNING"
STATE_BASE_SUCCEEDED = "BASE_SUCCEEDED"
STATE_BASE_FAILED = "BASE_FAILED"
STATE_STYLE_SUBMITTED = "STYLE_SUBMITTED"
STATE_STYLE_RUNNING = "STYLE_RUNNING"
STATE_STYLE_SUCCEEDED = "STYLE_SUCCEEDED"
STATE_STYLE_FAILED = "STYLE_FAILED"
STATE_PUBLISH_RICH = "PUBLISH_RICH"
STATE_PUBLISH_PLAIN = "PUBLISH_PLAIN"
# ASAP 4.3 (§2.2, T-4842): стадия записи атомарной preview pair (между
# успешным style edit и терминальным completed). Аддитивно к §42.
STATE_SAVING_PREVIEW = "SAVING_PREVIEW"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"

# Маппинг state → task_jobs.status (§42).
TASK_STATUS_BY_STATE = {
    STATE_CREATED: "queued",
    STATE_BASE_SUBMITTED: "running",
    STATE_BASE_RUNNING: "running",
    STATE_BASE_SUCCEEDED: "running",
    STATE_BASE_FAILED: "running",
    STATE_STYLE_SUBMITTED: "running",
    STATE_STYLE_RUNNING: "running",
    STATE_STYLE_SUCCEEDED: "running",
    STATE_STYLE_FAILED: "running",
    STATE_PUBLISH_RICH: "running",
    STATE_PUBLISH_PLAIN: "running",
    STATE_SAVING_PREVIEW: "running",
    STATE_DONE: "completed",
    STATE_FAILED: "failed",
}

MODE_PRODUCTION = "production"
MODE_PREVIEW = "preview"

# ── §45: whitelist безопасных лог-полей ─────────────────────────────────────
SAFE_LOG_FIELDS = frozenset({
    "run_id", "job_id", "style_id", "style_revision", "issue_number",
    "connection_id", "provider", "model", "prompt_len", "prompt_hash",
    "reference_count", "duration_ms", "latency_ms", "provider_task_id",
    "status", "fallback", "fallback_mode", "outcome", "reason", "attempt",
    "async_used", "reference_paths", "mode", "resolve_source",
    # ASAP-4 волна B (spec §2 B.1/B.4/B.5, T-4415/T-4418/T-4419): snapshot,
    # integrity-метрики и prompt diagnostics — только id/числа/enum (R17).
    "selection_source", "enabled", "pipeline_mode", "capability_state",
    "reference_bytes_total", "instruction_chars", "brief_chars",
    "compiled_chars", "limit_unit", "issue_present",
    # ASAP 4.4 (§2, T-4873/T-4874): effective route/источник capability —
    # enum/числа (R17-safe).
    "edit_route", "limit_source", "limit_source_taxonomy", "capability_source",
    "limit_value",
})


def _pg():
    """PgDatabase из runtime-кэша (fail-open → None)."""
    try:
        from services import hot_config as hot
        cache = hot.get_config_cache()
        if cache is None:
            return None
        return getattr(cache, "pg", None)
    except Exception:
        return None


def _pool(pg=None):
    obj = pg if pg is not None else _pg()
    return getattr(obj, "pool", None) if obj is not None else None


def rich_degraded_enabled() -> bool:
    """§50/§51: разрешён degraded-режим «Rich без обложки» (env-only, default ON)."""
    try:
        return bool(getattr(settings, "COVER_RICH_DEGRADED_ENABLED", True))
    except Exception:
        return True


def snapshot_enabled() -> bool:
    """ASAP-4 волна B (spec §2/§8.2, ADR-1028-7 D6): kill-switch
    `COVER_STYLE_SNAPSHOT_ENABLED` (env-only, default ON).

    ON — selection snapshot + SELECTION event + видимый fail-open (distinct
    reason codes, SKIPPED events, provenance при всех исходах, issue counter
    только на реальные submissions). OFF — бит-в-бит прежний контур волны
    EXTRA/ASAP-3.2: без snapshot/SELECTION, тихие ранние выходы, прежний
    порядок вызовов (parity-тест)."""
    try:
        return bool(getattr(settings, "COVER_STYLE_SNAPSHOT_ENABLED", True))
    except Exception:
        return True


def prompt_hash(text: str) -> str:
    """Короткий R17-safe хэш промпта (для логов; §45)."""
    return hashlib.sha256(
        str(text or "").encode("utf-8")).hexdigest()[:16]


def safe_log_fields(**fields) -> dict:
    """Оставить только whitelisted поля (§45)."""
    return {k: v for k, v in fields.items()
            if k in SAFE_LOG_FIELDS and v is not None}


def emit_cover_event(event: str, *, outcome: str = "success",
                     level: int = logging.INFO, run_id: str | None = None,
                     job_id: str | None = None, chat_id: int | None = None,
                     model: str | None = None, provider: str | None = None,
                     duration_ms: int | None = None,
                     attempt: int | None = None,
                     reason_code: str | None = None,
                     status: str | None = None, **extra) -> None:
    """Стадийное событие §44: grep-able лог + best-effort MCA-эмиссия.

    Лог — R17-safe (whitelist §45). MCA-эмиссия fail-open: если контракт
    события отклонит поле — оно просто не попадает в событие.
    """
    fields = safe_log_fields(**extra)
    parts = ["%s=%s" % (k, v) for k, v in fields.items()]
    parts.append("status=%s" % (status or outcome))
    if chat_id is not None:
        parts.append("chat_id=%s" % chat_id)
    line = "%s | %s" % (event, " | ".join(parts))
    if level >= logging.ERROR:
        logger.error(line)
    elif level >= logging.WARNING:
        logger.warning(line)
    else:
        logger.info(line)
    try:
        from services import mca_trace as trace
        outcome_map = {"success": "success", "failed": "failed",
                       "start": "start", "skipped": "skipped",
                       "pending_external": "pending_external"}
        trace.emit_stage(
            event, outcome=outcome_map.get(outcome, "success"),
            level=("ERROR" if level >= logging.ERROR else
                   "WARN" if level >= logging.WARNING else "INFO"),
            component="cover", stage=status or outcome,
            model=model, provider=provider, duration_ms=duration_ms,
            attempt=attempt, reason_code=reason_code,
            **trace.span_fields(run_id=run_id, pipeline_type="summary.cover",
                                job_id=job_id))
    except Exception:
        return


# ── §47/§96: классификация + timeline ───────────────────────────────────────

def classify_cover_result(*, published_channel: str, cover_outcome: str,
                          cover_reason: str = "") -> dict:
    """Классифицировать результат публикации по §96 (для логов/UI).

    `cover_outcome` ∈ {styled, base, none}; `published_channel` ∈ {rich,
    plain}; `cover_reason` ∈ {"", style_failed, base_failed}.
    """
    if published_channel == "plain":
        return {"cover_result": RESULT_NONE, "publication": RESULT_PLAIN,
                "reason": REASON_RICH_FAILED, "fallback": "rich_failed"}
    if cover_outcome == RESULT_STYLED:
        return {"cover_result": RESULT_STYLED, "publication": "rich",
                "reason": "", "fallback": None}
    if cover_outcome == RESULT_BASE:
        return {"cover_result": RESULT_BASE, "publication": "rich",
                "reason": cover_reason or REASON_STYLE_FAILED,
                "fallback": cover_reason or REASON_STYLE_FAILED}
    return {"cover_result": RESULT_NONE, "publication": "rich",
            "reason": cover_reason or REASON_BASE_FAILED,
            "fallback": cover_reason or REASON_BASE_FAILED}


def build_timeline(*, text_ms=None, base_ms=None, style_ms=None,
                   rich_ms=None, base_ok=True, style_enabled=False,
                   style_ok=False, rich_ok=True) -> list[dict]:
    """Таймлайн §47 (для analytics/UI) — только факты, без выдуманных чисел."""
    def step(name, ok, ms):
        row = {"name": name, "ok": bool(ok)}
        if ms is not None:
            row["duration_ms"] = int(ms)
        return row

    rows = [step("Текст саммари", True, text_ms)]
    rows.append(step("Базовая обложка", base_ok, base_ms))
    if style_enabled:
        rows.append(step("Обработка стилем", style_ok, style_ms))
    rows.append(step("Публикация", rich_ok, rich_ms))
    return rows


def ru_status_for(outcome: str) -> str:
    """RU-статус пользователю по исходу (§48/§75)."""
    return {
        RESULT_BASE: RU_STYLE_FAILED,
        RESULT_NONE: RU_BASE_FAILED,
        RESULT_PLAIN: RU_RICH_FAILED,
    }.get(outcome, "")


# ── §68/§92: process-local latency/cost observability ───────────────────────

_LATENCY: dict[str, list[dict]] = {}
_COSTS: dict[str, dict] = {}


def _metrics_enabled() -> bool:
    try:
        return bool(getattr(settings, "COVER_STYLE_METRICS_ENABLED", True))
    except Exception:
        return True


def record_latency(model: str, stage: str, latency_ms: int, *,
                   timeout: bool = False, retry: bool = False,
                   provider_fallback: bool = False) -> None:
    """Записать наблюдение latency (§68). UNKNOWN ≠ 0: 0 ms — валидное значение."""
    if not _metrics_enabled():
        return
    key = "%s|%s" % (stage, model or "unknown")
    _LATENCY.setdefault(key, []).append({
        "ms": max(0, int(latency_ms or 0)),
        "timeout": bool(timeout), "retry": bool(retry),
        "provider_fallback": bool(provider_fallback)})


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[max(0, min(idx, len(ordered) - 1))]


def latency_stats() -> dict:
    """p50/p95/max/timeout/retry/provider-fallback по model/stage (§68)."""
    out: dict[str, dict] = {}
    for key, rows in _LATENCY.items():
        values = [r["ms"] for r in rows]
        out[key] = {
            "count": len(rows), "p50": _percentile(values, 50),
            "p95": _percentile(values, 95), "max": max(values) if values else 0,
            "timeout_count": sum(1 for r in rows if r["timeout"]),
            "retry_count": sum(1 for r in rows if r["retry"]),
            "provider_fallback_count": sum(
                1 for r in rows if r["provider_fallback"]),
        }
    return out


def record_cost(stage: str, cost_usd: float | None, *,
                mode: str = MODE_PRODUCTION) -> None:
    """Раздельно base/style/preview cost (§92); preview маркируется (§67)."""
    if not _metrics_enabled():
        return
    if cost_usd is None:
        return                          # UNKNOWN ≠ 0: не выдумываем стоимость
    bucket = _COSTS.setdefault(stage, {"production": 0.0, "preview": 0.0,
                                       "known": False})
    bucket[mode if mode in ("production", "preview") else "production"] \
        += float(cost_usd)
    bucket["known"] = True


def cost_summary() -> dict:
    """Свод cost по стадиям (§92): preview не смешивается с production."""
    return {stage: dict(vals) for stage, vals in _COSTS.items()}


def reset_metrics() -> None:
    """Сброс process-local метрик (тесты/диагностика)."""
    _LATENCY.clear()
    _COSTS.clear()


# ── §42/§43: durable job state (REUSE task_jobs/mca_pipeline_runs) ──────────

@dataclass
class CoverJobState:
    """Снимок состояния cover-джобы (персистится в checkpoint_ref/payload).

    Позволяет пережить restart: при асинхронном провайдере `provider_task_id`
    сохраняется, чтобы после рестарта продолжить polling и **не** создать
    новый платный task (§43).
    """

    state: str = STATE_CREATED
    provider_task_id: str | None = None
    style_id: str | None = None
    issue_number: int | None = None
    stages: list = field(default_factory=list)
    # ASAP 4.3 (§2.2, T-4842): безопасные diagnostics preview-джобы для
    # status-endpoint (без prompt/ключей) + provenance preview pair (§4).
    provider: str | None = None
    model: str | None = None
    mode: str | None = None
    base_asset_id: str | None = None
    preview_before_asset_id: str | None = None
    preview_after_asset_id: str | None = None
    preview_revision: int | None = None
    machine_reason: str | None = None
    human_message: str | None = None
    prompt_diagnostics: dict | None = None
    # ASAP 4.4 (§RC-D/T-4870): draft snapshot Test Style (style-affecting поля,
    # которые видел editor) + его fingerprint для promote (§RC-E/T-4872).
    # Snapshot — не профиль: в DB не сохраняется, живёт в durable job state.
    draft_snapshot: dict | None = None
    draft_fingerprint: str | None = None

    def mark(self, state: str, *, provider_task_id: str | None = None,
             note: str | None = None) -> None:
        self.state = state
        if provider_task_id is not None:
            self.provider_task_id = provider_task_id
        entry = {"state": state, "at": int(time.time())}
        if note:
            entry["note"] = note
        self.stages.append(entry)
        if len(self.stages) > 32:
            del self.stages[:-32]

    @property
    def task_status(self) -> str:
        return TASK_STATUS_BY_STATE.get(self.state, "running")

    def to_json(self) -> str:
        return json.dumps({
            "state": self.state, "provider_task_id": self.provider_task_id,
            "style_id": self.style_id, "issue_number": self.issue_number,
            "provider": self.provider, "model": self.model, "mode": self.mode,
            "base_asset_id": self.base_asset_id,
            "preview_before_asset_id": self.preview_before_asset_id,
            "preview_after_asset_id": self.preview_after_asset_id,
            "preview_revision": self.preview_revision,
            "machine_reason": self.machine_reason,
            "human_message": self.human_message,
            "prompt_diagnostics": self.prompt_diagnostics,
            "draft_snapshot": self.draft_snapshot,
            "draft_fingerprint": self.draft_fingerprint,
            "stages": self.stages[-32:]}, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None) -> "CoverJobState":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(
            state=str(data.get("state") or STATE_CREATED),
            provider_task_id=data.get("provider_task_id"),
            style_id=data.get("style_id"),
            issue_number=data.get("issue_number"),
            provider=data.get("provider"),
            model=data.get("model"),
            mode=data.get("mode"),
            base_asset_id=data.get("base_asset_id"),
            preview_before_asset_id=data.get("preview_before_asset_id"),
            preview_after_asset_id=data.get("preview_after_asset_id"),
            preview_revision=data.get("preview_revision"),
            machine_reason=data.get("machine_reason"),
            human_message=data.get("human_message"),
            prompt_diagnostics=(data.get("prompt_diagnostics")
                                if isinstance(data.get("prompt_diagnostics"),
                                              dict) else None),
            draft_snapshot=(data.get("draft_snapshot")
                            if isinstance(data.get("draft_snapshot"),
                                          dict) else None),
            draft_fingerprint=data.get("draft_fingerprint"),
            stages=list(data.get("stages") or []))


async def start_cover_job(db, *, chat_id: int, correlation_id: str | None = None,
                          payload: dict | None = None,
                          job_id: str | None = None,
                          coalesce_key: str | None = None,
                          kind: str = "cover_style") -> str | None:
    """Создать durable cover-джобу в существующей очереди (REUSE, §42).

    При `coalesce_key` возвращается `job_id` уже активной (queued/running)
    джобы — singleflight/restart-resume (§42/§43); новый платный task не
    создаётся повторно.
    """
    if db is None:
        return None
    jid = job_id or ("cov_" + uuid.uuid4().hex)
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return await store.enqueue(
            owner="summary", kind=kind, coalesce_key=coalesce_key,
            payload=json.dumps({"chat_id": chat_id,
                                "correlation_id": correlation_id,
                                **(payload or {})}, ensure_ascii=False),
            job_id=jid)
    except Exception:
        logger.warning("[cover_style_jobs] durable job start failed",
                       exc_info=True)
        return None


async def finish_cover_job(db, job_id: str | None, *, outcome: str,
                           reason_code: str | None = None,
                           checkpoint: CoverJobState | None = None) -> bool:
    """Терминальный исход durable cover-джобы (§42/§43)."""
    if db is None or not job_id:
        return False
    status = "completed" if outcome in (STATE_DONE, RESULT_STYLED,
                                        RESULT_BASE) else "failed"
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return await store.finish(
            job_id, status=status, reason_code=reason_code,
            result_ref=(checkpoint.to_json() if checkpoint else None))
    except Exception:
        logger.warning("[cover_style_jobs] durable job finish failed",
                       exc_info=True)
        return False


async def save_cover_state(db, job_id: str | None,
                           state: CoverJobState) -> bool:
    """Сохранить снимок состояния (restart recovery, §43)."""
    if db is None or not job_id:
        return False
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return bool(await store.save_checkpoint(
            job_id, cursor_token=state.to_json(), processed=len(state.stages),
            checkpoint_ref=state.state))
    except Exception:
        logger.warning("[cover_style_jobs] durable state save failed",
                       exc_info=True)
        return False


async def load_cover_state(db, job_id: str | None) -> CoverJobState | None:
    """Восстановить снимок состояния из `task_jobs` (None — нет/битый, §43)."""
    if db is None or not job_id:
        return None
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        checkpoint = await store.get_checkpoint(job_id)
    except Exception:
        return None
    if not checkpoint:
        return None
    raw = checkpoint.get("cursor")
    if not raw:
        return None
    return CoverJobState.from_json(raw)


async def get_cover_job(db, job_id: str | None) -> dict | None:
    """Строка durable cover-джобы из `task_jobs` (None — нет/PG недоступен)."""
    if db is None or not job_id:
        return None
    try:
        from services.task_supervisor import TaskJobStore
        return await TaskJobStore(db).get(job_id)
    except Exception:
        return None


async def requeue_cover_job(db, job_id: str | None, *,
                            reason_code: str | None = None) -> bool:
    """Вернуть терминальную cover-джобу в `queued` (новый цикл Test Style,
    §2.3/T-4843): та же строка — без второй очереди и дублей."""
    if db is None or not job_id:
        return False
    try:
        from services.task_supervisor import TaskJobStore
        return bool(await TaskJobStore(db).requeue(
            job_id, reason_code=reason_code))
    except Exception:
        return False


def cover_job_key(*, summary_run_id: str | None,
                  style_id: str | None) -> str:
    """Детерминированный `job_id` cover-джобы run+style (§42/§43).

    Один и тот же Summary-run + style → один durable job (restart-resume),
    а не новая строка/повторный платный task.
    """
    raw = "%s|%s" % (summary_run_id or "", style_id or "")
    return "cov_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


async def begin_cover_job(db, *, chat_id: int,
                          correlation_id: str | None = None,
                          style_id: str | None = None,
                          summary_run_id: str | None = None,
                          payload: dict | None = None,
                          kind: str = "cover_style",
                          initial_state: str = STATE_BASE_SUCCEEDED,
                          ) -> tuple[str | None, CoverJobState]:
    """Создать/переиспользовать durable cover-джобу (§42/§43).

    Возвращает `(job_id, state)`. При рестарте существующая джоба находится
    по детерминированному `job_id`/`coalesce_key`, а состояние (включая
    `provider_task_id`) восстанавливается из `task_jobs` — новый платный
    task **не** создаётся (§43, DoD-25).

    `initial_state` (ASAP 4.3, T-4842): production-путь стартует с
    `BASE_SUCCEEDED` (base уже готова до Style-джобы); Test Style preview —
    с `CREATED` (base генерируется внутри джобы).
    """
    if db is None:
        return None, CoverJobState(style_id=style_id)
    coalesce = ("cover_style:%s" % summary_run_id) if summary_run_id else None
    jid = cover_job_key(summary_run_id=summary_run_id, style_id=style_id)
    started = await start_cover_job(
        db, chat_id=chat_id, correlation_id=correlation_id,
        payload={"style_id": style_id, **(payload or {})},
        job_id=jid, coalesce_key=coalesce, kind=kind)
    state = await load_cover_state(db, started) if started else None
    if state is None:
        state = CoverJobState(style_id=style_id)
        # Base-стадия уже успешна к моменту запуска Style-джобы (§3.2/§49).
        state.mark(initial_state)
    return started, state


async def _persist_state(db, job_id: str | None,
                         state: CoverJobState | None) -> bool:
    if db is None or not job_id or state is None:
        return False
    return await save_cover_state(db, job_id, state)


# ── profile/selection helpers ───────────────────────────────────────────────

async def resolve_selected_style_id(chat_id: int) -> str:
    from services.cover_style_pipeline import resolve_selected_style_id as _r
    return await _r(chat_id)


async def load_profile(pg, style_id: str) -> dict | None:
    return await registry.get_profile_with_refs(pg, style_id)


async def load_selected_profile(chat_id: int, pg=None) -> dict | None:
    """Профиль выбранного per-chat стиля (или None → `Без дополнительного стиля`)."""
    style_id = await resolve_selected_style_id(chat_id)
    if not style_id:
        return None
    obj = pg if pg is not None else _pg()
    if _pool(obj) is None:
        return None
    return await registry.get_profile_with_refs(obj, style_id)


# ── ASAP-4 волна B: selection snapshot (spec §2 B.1, T-4415, ADR-1028-7 D6) ──

KEY_SELECTED_STYLE_PARAM = "prompts.summary_cover_style_id"


async def _selection_source(chat_id: int) -> str:
    """Источник выбора (§36): `chat` (per-chat override) | `global` | `none`.

    Зеркалит резолв `resolve_selected_style_id` (override чата → global),
    не вычисляя значение вторично из другого источника.
    """
    try:
        from services import chat_params as cp
        cache = cp.get_chat_params_cache()
        root = await cache.get_chat_params(chat_id) if cache else {}
        override = str((root.get("overrides") or {}).get(
            KEY_SELECTED_STYLE_PARAM) or "").strip()
        if override:
            return "chat"
        from services import hot_config as hot
        if str(hot.get(KEY_SELECTED_STYLE_PARAM, "") or "").strip():
            return "global"
    except Exception:
        return "none"
    return "none"


async def resolve_selection(chat_id: int, pg=None) -> dict:
    """ЕДИНАЯ точка резолва стиля на run (§36, R4-B-001).

    В начале cover publication фиксируется snapshot:
    `chat_id / selected_style_id / style_revision / selection_source
    (chat|global|none) / enabled / pipeline_mode` + профиль (internal carry,
    в событие не попадает). Повторная резолюция style ID в конце run
    запрещена — Style stage работает по этому снимку.
    """
    style_id = await resolve_selected_style_id(chat_id)
    source = "none"
    profile = None
    if style_id:
        source = await _selection_source(chat_id)
        obj = pg if pg is not None else _pg()
        if _pool(obj) is not None:
            try:
                profile = await registry.get_profile_with_refs(obj, style_id)
            except Exception:
                profile = None
    return {
        "chat_id": chat_id,
        "selected_style_id": style_id or None,
        "style_revision": (profile or {}).get("revision"),
        "selection_source": source,
        "enabled": bool((profile or {}).get("enabled")),
        "pipeline_mode": pipeline_mode(profile),
        "_profile": profile,
    }


def emit_style_selection(snapshot: dict, *, run_id: str | None = None) -> None:
    """`COVER_STYLE_SELECTION` (§37, R4-B-002): до base generation/style edit.

    R17-safe: только chat_id/id/revision/enum/bool. Для выбранного
    `medved_press` выбор виден до первого image API-вызова.
    """
    emit_cover_event(
        COVER_STYLE_SELECTION, outcome="start", run_id=run_id,
        chat_id=(snapshot or {}).get("chat_id"),
        style_id=(snapshot or {}).get("selected_style_id"),
        style_revision=(snapshot or {}).get("style_revision"),
        selection_source=(snapshot or {}).get("selection_source"),
        enabled=(snapshot or {}).get("enabled"),
        pipeline_mode=(snapshot or {}).get("pipeline_mode"))


async def selection_stage(chat_id: int, *, run_id: str | None = None,
                          pg=None) -> dict | None:
    """Snapshot + SELECTION event на старте cover publication (fail-open).

    Kill-switch OFF (или резолв недоступен) → None — вызывающий идёт по
    прежнему тихому контуру (бит-в-бит).
    """
    if not snapshot_enabled():
        return None
    try:
        snapshot = await resolve_selection(chat_id, pg=pg)
    except Exception:
        return None
    try:
        emit_style_selection(snapshot, run_id=run_id)
    except Exception:
        pass
    return snapshot


async def profile_for_snapshot(snapshot: dict,
                               pg=None) -> tuple[dict | None, str]:
    """Профиль из snapshot'а + причина раннего выхода ("" — причины нет).

    Раздельные причины (§2 B.4): `no_style` (ничего не выбран) /
    `profile_missing` (выбранный профиль удалён/PG недоступен) /
    `disabled` (профиль выключен). Режим без Style-стадии — НЕ fail: виден
    в SELECTION event (`pipeline_mode`).
    """
    snapshot = snapshot or {}
    style_id = str(snapshot.get("selected_style_id") or "").strip()
    if not style_id:
        return None, REASON_NO_STYLE
    profile = snapshot.get("_profile")
    if profile is None:
        obj = pg if pg is not None else _pg()
        if _pool(obj) is not None:
            try:
                profile = await registry.get_profile_with_refs(obj, style_id)
            except Exception:
                profile = None
    if profile is None:
        return None, REASON_PROFILE_MISSING
    if not profile.get("enabled"):
        return None, REASON_DISABLED
    return profile, ""


async def report_style_skip(snapshot: dict, *, summary_run_id: str | None,
                            reason: str,
                            base_asset_id: str | None = None) -> None:
    """Видимый fail-open (§42–§44, T-4419): SKIPPED event + provenance.

    Публикация не ломается (base уходит как есть), но причина видна:
    отдельный `COVER_STYLE_SKIPPED` с reason + human-перевод в логе.
    Потеря ВЫБРАННОГО стиля (profile_missing/disabled) — WARNING;
    `no_style` (ничего не выбрано — штатная конфигурация, источник виден в
    COVER_STYLE_SELECTION `selection_source=none`) — INFO без спама.
    Provenance base_fallback — только при выбранном стиле; issue counter
    НЕ расходуется (submission не было)."""
    snapshot = snapshot or {}
    detail = reason_detail_ru(reason)
    level = logging.INFO if reason == REASON_NO_STYLE else logging.WARNING
    emit_cover_event(
        COVER_STYLE_SKIPPED, outcome="skipped", level=level,
        run_id=summary_run_id, chat_id=snapshot.get("chat_id"),
        style_id=snapshot.get("selected_style_id"),
        style_revision=snapshot.get("style_revision"),
        reason=reason, reason_code=style_reason_code(reason),
        fallback=(REASON_STYLE_FAILED
                  if snapshot.get("selected_style_id") else None))
    if detail:
        (logger.warning if level >= logging.WARNING else logger.info)(
            "summary cover: style not applied | chat_id=%s | reason=%s | "
            "detail=%s", snapshot.get("chat_id"), reason, detail)
    if not snapshot.get("selected_style_id"):
        return
    await _record_provenance(
        _pg(), {
            "style_id": snapshot.get("selected_style_id"),
            "style_revision": snapshot.get("style_revision"),
            "issue_number": None,
            "base_asset_id": base_asset_id, "final_asset_id": None,
            "provider": "", "model": "",
        }, summary_run_id=summary_run_id, job_id=None, snapshot=None,
        status=registry.PROVENANCE_BASE, fallback_mode=reason,
        mode=MODE_PRODUCTION)


async def record_no_cover_provenance(snapshot: dict, *,
                                     summary_run_id: str | None) -> None:
    """§44: provenance `no_cover` — base generation не удалась (видимый исход).

    Только при выбранном стиле (есть что записать); fail-open.
    """
    snapshot = snapshot or {}
    if not snapshot.get("selected_style_id"):
        return
    await _record_provenance(
        _pg(), {
            "style_id": snapshot.get("selected_style_id"),
            "style_revision": snapshot.get("style_revision"),
            "issue_number": None,
            "base_asset_id": None, "final_asset_id": None,
            "provider": "", "model": "",
        }, summary_run_id=summary_run_id, job_id=None, snapshot=None,
        status=registry.PROVENANCE_NONE, fallback_mode=REASON_BASE_FAILED,
        mode=MODE_PRODUCTION)


async def _resolve_reference_paths(pg, profile: dict) -> list[str]:
    paths: list[str] = []
    obj = pg if pg is not None else _pg()
    for ref in (profile.get("references") or []):
        asset_id = ref.get("asset_id")
        if not asset_id or obj is None:
            continue
        try:
            asset = await registry.get_asset(obj, asset_id)
        except Exception:
            asset = None
        if not asset:
            continue
        disk_path = asset.get("disk_path")
        if disk_path and os.path.exists(str(disk_path)):
            paths.append(str(disk_path))
    return paths


# ── ASAP-4 волна B: reference integrity (spec §2 B.4 §45, T-4418, R4-B-010) ──

_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", {"image/png"}),
    (b"\xff\xd8", {"image/jpeg"}),
    (b"RIFF", {"image/webp"}),      # + "WEBP" по offset 8
)


def _image_signature_ok(head: bytes, mime: str) -> bool:
    """Магические байты соответствуют заявленному MIME (§45 «изображение
    читаемо»; R17-safe — проверяются байты, контент не логируется)."""
    if mime == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    for signature, mimes in _IMAGE_SIGNATURES:
        if head.startswith(signature) and mime in mimes:
            return True
    return False


async def _resolve_reference_details(pg, profile: dict) -> list[dict]:
    """Целостность референсов (§45): DB-row / файл / MIME / читаемость / байты.

    Возвращает по записи на каждый референс профиля (R17-safe: asset_id +
    булевы + размер, без контента). `path` — только у готовых к отправке.
    """
    obj = pg if pg is not None else _pg()
    details: list[dict] = []
    for ref in (profile.get("references") or []):
        entry = {"asset_id": ref.get("asset_id"), "db_row": False,
                 "file": False, "mime_ok": False, "readable": False,
                 "bytes": 0, "path": None}
        asset_id = ref.get("asset_id")
        if asset_id and obj is not None:
            try:
                asset = await registry.get_asset(obj, asset_id)
            except Exception:
                asset = None
            if asset:
                entry["db_row"] = True
                entry["mime_ok"] = str(asset.get("mime") or "") \
                    in assets.ALLOWED_MIME
                disk_path = asset.get("disk_path")
                if disk_path and os.path.exists(str(disk_path)):
                    entry["file"] = True
                    try:
                        with open(disk_path, "rb") as handle:
                            head = handle.read(16)
                        entry["bytes"] = os.path.getsize(disk_path)
                        entry["readable"] = _image_signature_ok(
                            head, str(asset.get("mime") or ""))
                        if entry["readable"]:
                            entry["path"] = str(disk_path)
                    except OSError:
                        entry["readable"] = False
        details.append(entry)
    return details


async def profile_diagnostics(pg, profile: dict, *,
                              connection: dict | None = None) -> dict:
    """Чек-лист полей профиля §41 (T-4418, R4-B-006) — R17-safe.

    profile_id/revision/enabled/pipeline_mode/connection/provider/model/
    capability image_edit/reference count/file readable/instruction/counter.
    Секретов нет (api_key не читается вовсе — только наличие записи
    подключения резолвится выше по `connection_status`).
    """
    profile = profile or {}
    # ASAP 4.4 (§2/T-4873): diagnostics/Inspector — тот же effective resolver,
    # что UI meta/production (лестница §35), а не отдельный sync-контур.
    resolved = await resolve_effective_edit_capability(
        profile=profile, connection=connection, pg=pg,
        operation=cap.OPERATION_EDIT)
    slot = resolved["slot"]
    caps = resolved["capabilities"]
    refs = await _resolve_reference_details(pg, profile)
    return {
        "profile_id": profile.get("profile_id"),
        "revision": profile.get("revision"),
        "enabled": bool(profile.get("enabled")),
        "pipeline_mode": pipeline_mode(profile),
        "connection_id": slot.get("connection_id"),
        "connection_configured": bool(slot.get("configured")),
        "custom_unresolved": bool(slot.get("custom_unresolved")),
        "provider": slot.get("provider") or "",
        "model": slot.get("model") or "",
        "resolve_source": resolved.get("resolve_source") or "",
        "edit_route": resolved.get("route") or "",
        "capability_image_edit": caps.image_edit,
        "capability_source": caps.source,
        "limit_source": caps.prompt_limit.source,
        "limit_source_taxonomy": cap.prompt_limit_source_taxonomy(
            caps.prompt_limit.source),
        "limit_value": caps.prompt_limit.value if caps.prompt_limit.known
        else None,
        "references": {
            "configured": len(profile.get("references") or []),
            "ready": sum(1 for d in refs if d.get("readable")),
            "bytes_total": sum(d.get("bytes") or 0 for d in refs),
            "details": refs,
        },
        "instruction_chars": len(str(profile.get("instruction") or "")),
        "counter_enabled": bool(profile.get("counter_enabled")),
        "counter_value": profile.get("counter_value"),
    }


# ── prompt compilation (§19–§21) ────────────────────────────────────────────

def compile_style_prompt(profile: dict, *, issue_display: str,
                         capabilities, base_style_prompt: str = "",
                         brief=None, minimal: bool = False
                         ) -> compiler.CompiledPrompt:
    """Собрать priority-aware prompt Style Edit (§19–§21).

    P0 — runtime-инварианты (номер выпуска, запрет дубликатов) — не режется;
    P1 — инструкция стиля профиля и base style prompt (§19: «base style
    prompt»); P2 — описания референсов (режется первым). Динамический
    `CoverBrief` (§21) передаётся как сюжетная часть и масштабируется под
    остаток capability.

    `minimal=True` (ASAP 4.4/T-4875, adaptive retry без известного лимита):
    только P0+P1 инварианты — P2 (refs/brief) и P3 НЕ добавляются, чтобы
    retry был реально короче и не терял обязательную механику.
    """
    components = [
        compiler.PromptComponent(
            ("Сохрани номер выпуска «%s». Не добавляй дубликатов уже "
             "присутствующих на обложке элементов." % issue_display),
            priority=compiler.P0, label="runtime_invariants"),
        compiler.PromptComponent(profile.get("instruction") or "",
                                 priority=compiler.P1, label="style_instruction"),
    ]
    base_style = str(base_style_prompt or "").strip()
    if base_style:
        components.append(compiler.PromptComponent(
            base_style, priority=compiler.P1, label="base_style_prompt"))
    if minimal:
        return compiler.compile_prompt(components, capabilities=capabilities)
    refs = profile.get("references") or []
    if refs:
        ref_text = "; ".join(
            "%s: %s" % (r.get("label") or "reference",
                        r.get("description") or "")
            for r in refs)
        components.append(compiler.PromptComponent(
            ref_text, priority=compiler.P2, label="references"))
    brief_text = brief.render() if brief is not None else ""
    return compiler.compile_prompt(components, capabilities=capabilities,
                                   budget_component=brief_text)


def _prompt_breakdown(compiled) -> dict:
    """§9 (T-4849): Style/Context/Refs/System из component-lens компилятора."""
    lens = dict(getattr(compiled, "components", {}) or {})
    style = int(lens.get("style_instruction", 0)) \
        + int(lens.get("base_style_prompt", 0))
    return {
        "style_chars": style,
        "context_chars": int(lens.get("cover_brief", 0)),
        "refs_chars": int(lens.get("references", 0)),
        "system_chars": int(lens.get("runtime_invariants", 0)),
    }


# ── heartbeat (§46) ─────────────────────────────────────────────────────────

def heartbeat_interval() -> float:
    try:
        value = float(getattr(settings, "COVER_STYLE_HEARTBEAT_SECONDS", 30.0))
    except (TypeError, ValueError):
        value = 30.0
    return max(5.0, min(value, 120.0))


async def _run_with_heartbeat(factory, *, interval: float, event: str,
                              run_id: str | None, job_id: str | None,
                              model: str, provider: str):
    """Дождаться корутины, логируя heartbeat раз в `interval` (§46, без спама)."""
    task = asyncio.ensure_future(factory())
    started = time.monotonic()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if task in done:
                return task.result()
            emit_cover_event(
                event, outcome="pending_external", run_id=run_id,
                job_id=job_id, model=model, provider=provider,
                duration_ms=int((time.monotonic() - started) * 1000),
                status=event.replace("COVER_", "").lower())
    except asyncio.CancelledError:
        task.cancel()
        raise


def _asset_id_of(path: str | None) -> str | None:
    """Content-addressed `asset_id` изображения (§30): sha256 → `cas_<hex[:32]>`.

    Не пишет файл/PG (bounded, §2.1 — cover-байты транзиентны): даёт стабильный
    идентификатор для provenance `base_asset_id`/`final_asset_id`.
    """
    if not path:
        return None
    try:
        from services.cover_style_assets import asset_id_for
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return asset_id_for(digest.hexdigest())
    except OSError:
        return None


def _write_temp_image(content: bytes) -> str | None:
    try:
        fd, path = tempfile.mkstemp(prefix="covstyle_", suffix=".jpg")
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        return path
    except Exception:
        logger.warning("[cover_style_jobs] temp write failed — fail-open")
        return None


def _resolve_api_key() -> str:
    try:
        from services import hot_config as hot
        value = hot.get(KEY_STYLE_API_KEY, getattr(
            settings, "IMAGE_STYLE_API_KEY", ""))
    except Exception:
        value = getattr(settings, "IMAGE_STYLE_API_KEY", "")
    return str(value or "")


# ── Style stage (§3.2/§23/§38/§49) ──────────────────────────────────────────

async def run_style_job(*, chat_id: int, base_image_path: str | None,
                        profile: dict | None, summary_run_id: str | None,
                        correlation_id: str | None = None,
                        job_id: str | None = None, pg=None, db=None,
                        capabilities=None, discovery: dict | None = None,
                        endpoints: dict | None = None,
                        reference_paths: list | None = None,
                        edit_call=None, mode: str = MODE_PRODUCTION,
                        state: CoverJobState | None = None,
                        summary_text: str | None = None,
                        base_style_prompt: str | None = None) -> dict:
    """Выполнить Style Edit поверх готовой base cover (нормализатор, §23).

    Возвращает meta-словарь. При любом сбое `applied=False`,
    `reason="style_failed"` — вызывающий публикует **сохранённую base cover**
    (base НЕ перегенерируется, §49).

    §19/§21: prompt собирается из base style prompt + dynamic cover brief
    (компактный сюжет из Summary-prose `summary_text`), инструкции профиля,
    runtime-номера выпуска и описаний референсов — `compile_style_prompt`.

    ASAP-4 волна B (spec §2 B.4/B.5, T-4418/T-4419; `snapshot_enabled()`):
    ON — pre-execution конфигурационные фейлы (`connection_missing`/
    `edit_unsupported`/`not_configured`/`reference_missing`) выходят РАНЬШЕ
    assignment'а номера выпуска (counter не расходуется на не-submission),
    reference integrity §45 + метрики, prompt diagnostics §46; mca_events
    `reason_code` не схлопывается в generic `style_failed`. OFF — прежний
    порядок и прежние события бит-в-бит (parity-тест).
    """
    started = time.monotonic()
    _wb = snapshot_enabled()
    # §43 restart-resume: восстановить state из durable `task_jobs`, если он не
    # передан вызывающим (process-local состояние сброшено рестартом).
    if state is None and db is not None and job_id:
        state = await load_cover_state(db, job_id)
    if state is not None and state.state == STATE_DONE:
        # Полностью завершённая (опубликованная) джоба — новый заход, не resume.
        state = CoverJobState(style_id=state.style_id)
    meta = {
        "applied": False, "styled_path": None, "outcome": RESULT_BASE,
        "reason": "", "fail_reason": "", "message": "",
        "style_id": (profile or {}).get("profile_id"),
        "style_revision": (profile or {}).get("revision"),
        "issue_number": None, "provider": "", "model": "",
        "duration_ms": 0, "cost_usd": None, "provider_task_id": None,
        "async_used": False, "mode": mode,
        "base_asset_id": None, "final_asset_id": None,
        # Wave B (аддитивные диагностические ключи; None/OFF — не заполнено).
        "capability_state": None, "reference_bytes_total": 0,
        "reference_details": None, "prompt_diagnostics": None,
    }
    if not cover_styles_enabled():
        meta["reason"] = "cover_styles_disabled"
        meta["outcome"] = RESULT_BASE
        return meta
    if not profile:
        meta["reason"] = "no_style"
        meta["outcome"] = RESULT_BASE
        return meta
    if not base_image_path:
        meta["reason"] = REASON_BASE_FAILED
        meta["outcome"] = RESULT_NONE
        return meta

    # ── ASAP-3.2 (§103–§105, D14): connection_id — настоящий FK; запись
    # подключения (base_url/api_key) резолвится из реестра Connections.
    _connection = None
    obj0 = pg if pg is not None else _pg()
    if profile and profile.get("model_mode") == MODEL_MODE_CUSTOM \
            and str(profile.get("connection_id") or "").strip() \
            and obj0 is not None:
        try:
            _connection = await registry.get_connection(
                obj0, str(profile.get("connection_id")).strip())
        except Exception:
            _connection = None
    # T-4619 (spec §6 F.2; ADR-1028-8 D7.2): лестница наследования §35.
    # Явно настроенный слот/подключение — байт-в-бит (регресс); пустой
    # глобальный слот при «По умолчанию (глобальная настройка)» →
    # Connections default → global default image provider+model.
    # Kill-switch OFF → resolve_style_slot (байт-в-бит 2.58.46).
    slot = await resolve_style_slot_inherited(
        profile=profile, connection=_connection, pg=obj0)
    _inherit_conn = slot.pop("_connection", None)
    if _inherit_conn is not None:
        _connection = _inherit_conn
    _resolve_source = str(slot.get("resolve_source")
                          or SLOT_SOURCE_GLOBAL_STYLE)
    slot.pop("resolve_source", None)
    if _wb and slot.get("custom_unresolved"):
        # §40/B.4: профиль указывает на подключение, записи которого нет
        # (удалено/PG недоступен) — ранний выход с честной причиной;
        # default-слот молча не подставляется (edit уходит не на ту точку).
        return await _style_failed(
            meta, state, reason=REASON_CONNECTION_MISSING,
            message=("Подключение модели не найдено. Проверьте «Настроить "
                     "подключения →» в профиле стиля."),
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            started=started, db=db)
    # §104: пер-подключение api_key (профиль секретов не хранит);
    # default-слот → прежний ключ `keys.image_style_api_key`; наследованный
    # global-image слот (T-4619 leg 3c) → ключ глобального image-провайдера
    # `keys.image_api_key` (тот же провайдер, что сгенерировал base cover).
    def _resolve_api_key() -> str:
        if _connection is not None:
            return str(_connection.get("api_key") or "")
        if _resolve_source == SLOT_SOURCE_GLOBAL_IMAGE:
            try:
                from services import hot_config as hot
                value = hot.get(KEY_IMAGE_API_KEY, getattr(
                    settings, "IMAGE_API_KEY", ""))
            except Exception:
                value = getattr(settings, "IMAGE_API_KEY", "")
            return str(value or "")
        try:
            from services import hot_config as hot
            value = hot.get(KEY_STYLE_API_KEY, getattr(
                settings, "IMAGE_STYLE_API_KEY", ""))
        except Exception:
            value = getattr(settings, "IMAGE_STYLE_API_KEY", "")
        return str(value or "")
    meta["provider"] = slot.get("provider") or ""
    meta["model"] = slot.get("model") or ""
    meta["resolve_source"] = _resolve_source
    # ASAP 4.4 (§2/T-4873): route — тем же резолвером, что UI meta/budget
    # (единый provider+base_url+model+route+operation); fail-open → "".
    edit_route = ""
    if slot.get("configured"):
        try:
            from services import cover_style_edit as _edit_mod
            edit_route = str(await _edit_mod.resolve_edit_route(
                slot.get("base_url") or "", slot.get("model") or "") or "")
        except Exception:
            edit_route = ""
    meta["edit_route"] = edit_route
    # T-4619/T-4620: `COVER_STYLE_RESOLVE` — источник резолва слота
    # (лестница §35: profile_connection/connections_default/global_image/
    # global_style_slot); R17-safe (id/enum/bool).
    emit_cover_event(
        COVER_STYLE_RESOLVE, outcome="start", run_id=correlation_id,
        job_id=job_id, chat_id=chat_id, model=meta["model"],
        provider=meta["provider"], style_id=meta["style_id"],
        connection_id=slot.get("connection_id"),
        resolve_source=_resolve_source,
        configured=bool(slot.get("configured")))
    emit_cover_event(COVER_STYLE_START, outcome="start", run_id=correlation_id,
                     job_id=job_id, chat_id=chat_id, model=meta["model"],
                     provider=meta["provider"], style_id=meta["style_id"],
                     style_revision=meta["style_revision"])
    if state is not None:
        # ASAP 4.3 (§2.2): безопасные provider/model для status-endpoint
        # preview-джобы (persist вместе со stage-переходом).
        state.provider = meta["provider"] or None
        state.model = meta["model"] or None
        state.mode = mode
        state.mark(STATE_STYLE_SUBMITTED)
        await _persist_state(db, job_id, state)

    caps = capabilities
    if caps is None:
        # T-4619: capabilities резолвятся по ФИНАЛЬНОМУ (унаследованному)
        # слоту, а не по базовому глобальному (registry §36 — единый
        # резолвер; для базового слота результат идентичен прежнему).
        # ASAP 4.4 (§2/T-4873): route входит в capability key — тот же, что
        # в UI (один источник истины).
        caps = cap.resolve_capabilities(
            slot.get("provider") or "", slot.get("base_url") or "",
            slot.get("model") or "", discovery=discovery, endpoints=endpoints,
            route=edit_route or None,
            # ASAP 4.3 (§7, T-4847): capability per operation (style stage —
            # image_edit), manual override — высший приоритет.
            operation=cap.OPERATION_EDIT)
    meta["capability_state"] = getattr(caps, "image_edit", None)
    allowed, message = check_edit_allowed(profile=profile, capabilities=caps)
    if not allowed:
        # §38: модель без image_edit — API не вызывается, base публикуется.
        return await _style_failed(
            meta, state, reason="edit_unsupported", message=message,
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            started=started, db=db)

    obj = pg if pg is not None else _pg()
    ref_details = None
    reference_bytes_total = 0
    if _wb:
        # §B.5 (T-4419): pre-execution конфигурационные проверки — ДО
        # assignment'а выпуска (counter расходуется только на submission).
        if not slot.get("configured"):
            # Прод-факт Q14: `not_configured` за 72 мс — без edit API;
            # честный reason без расхода нумерации (§45 owner'а).
            return await _style_failed(
                meta, state, reason=REASON_NOT_CONFIGURED,
                message=("Модель обработки не настроена. Откройте «Настроить "
                         "подключения →» и выберите модель с поддержкой "
                         "edit."),
                run_id=correlation_id, job_id=job_id, chat_id=chat_id,
                started=started, db=db)
        if reference_paths is None:
            # §45 (T-4418): DB-row/file/MIME/readable до edit; метрики
            # `reference_count`/`reference_bytes_total` — без контента.
            ref_details = await _resolve_reference_details(obj, profile)
            reference_paths = [d["path"] for d in ref_details
                               if d.get("path") and d.get("readable")]
            reference_bytes_total = sum(d.get("bytes") or 0
                                        for d in ref_details)
            if (profile.get("references") or []) and not reference_paths:
                return await _style_failed(
                    meta, state, reason=REASON_REFERENCE_MISSING,
                    message=("Референсы стиля недоступны. Загрузите референс "
                             "заново."),
                    run_id=correlation_id, job_id=job_id, chat_id=chat_id,
                    started=started, db=db)
    meta["reference_bytes_total"] = reference_bytes_total
    meta["reference_details"] = ref_details
    ref_paths = reference_paths

    # §27/§28: pin номера выпуска к Summary run (production).
    issue_no = None
    if mode == MODE_PRODUCTION and profile.get("counter_enabled") \
            and summary_run_id and obj is not None:
        try:
            issue_no = await registry.resolve_issue_number(
                obj, profile["profile_id"], summary_run_id)
        except Exception:
            issue_no = None
    meta["issue_number"] = issue_no
    counter_format = profile.get("counter_format") or registry.SEEDED_COUNTER_FORMAT
    # §RC-C/T-4869: preview (и production без назначенного номера) показывают
    # текущий next_issue_number; counter при этом не расходуется.
    issue_display = (registry.format_issue(counter_format, issue_no)
                     if issue_no is not None
                     else registry.preview_issue_display(
                         counter_format, registry.next_issue_number(profile)))
    if not _wb:
        # OFF (legacy): прежний порядок — refs резолвятся после issue.
        ref_paths = reference_paths
        if ref_paths is None:
            ref_paths = await _resolve_reference_paths(obj, profile)
    snapshot = registry.build_revision_snapshot(
        profile, issue_number=issue_no, capabilities=caps.as_dict(),
        slot=slot)
    # §21: dynamic cover brief из Summary-prose (компактный сюжет).
    brief = compiler.brief_from_text(summary_text)
    meta["base_asset_id"] = _asset_id_of(base_image_path)
    compiled = compile_style_prompt(
        profile, issue_display=issue_display, capabilities=caps,
        base_style_prompt=base_style_prompt or "", brief=brief)
    if _wb:
        # §46 (T-4418): prompt compilation diagnostics (safe-числа/флаги).
        brief_text = brief.render() if brief is not None else ""
        meta["prompt_diagnostics"] = {
            "instruction_chars": len(str(profile.get("instruction") or "")),
            "brief_chars": len(brief_text),
            "issue_present": bool(issue_display in compiled.prompt),
            "references_count": len(ref_paths),
            "compiled_chars": len(compiled.prompt),
            # T-4816: Inspector `Original N / Resolved limit M / Compiled K`.
            "original_chars": int(compiled.original_len or 0),
            "resolved_limit": compiled.resolved_limit,
            "original_style_prompt_chars": len(str(
                base_style_prompt or "")),
            "exceeded": bool(compiled.exceeded),
            "overflow_reason": compiled.reason or "",
            "limit_unit": (str(compiled.limit) if compiled.limit is not None
                           else "unknown") + ":" + str(compiled.unit),
            "dropped_sections": list(compiled.dropped),
            # ASAP 4.3 (§9, T-4849): breakdown Style/Context/Refs/System из
            # фактически собранных компонент (units compiled prompt).
            **_prompt_breakdown(compiled),
            # ASAP 4.4 (§2, T-4873/T-4874): effective route + источник
            # capability/лимита для Inspector (R17-safe: enum/число).
            "edit_route": edit_route,
            "capability_source": caps.source,
            "limit_source": caps.prompt_limit.source,
            "limit_source_taxonomy": cap.prompt_limit_source_taxonomy(
                caps.prompt_limit.source),
            "limit_value": (caps.prompt_limit.value
                            if caps.prompt_limit.known else None),
        }
    if _wb:
        # §46: безопасные diagnostics в событии (числа/флаги, R17-safe).
        diag = meta.get("prompt_diagnostics") or {}
        emit_cover_event(
            COVER_STYLE_SUBMITTED, outcome="start", run_id=correlation_id,
            job_id=job_id, chat_id=chat_id, model=meta["model"],
            provider=meta["provider"], prompt_len=len(compiled.prompt),
            prompt_hash=prompt_hash(compiled.prompt),
            reference_count=len(ref_paths), issue_number=issue_no,
            reference_bytes_total=reference_bytes_total,
            capability_state=meta.get("capability_state"),
            instruction_chars=diag.get("instruction_chars"),
            brief_chars=diag.get("brief_chars"),
            compiled_chars=diag.get("compiled_chars"),
            limit_unit=diag.get("limit_unit"),
            issue_present=diag.get("issue_present"),
            edit_route=diag.get("edit_route"),
            limit_source=diag.get("limit_source"),
            limit_source_taxonomy=diag.get("limit_source_taxonomy"),
            capability_source=diag.get("capability_source"),
            fallback=(",".join(compiled.dropped)
                      if compiled.dropped else None))
    else:
        emit_cover_event(
            COVER_STYLE_SUBMITTED, outcome="start", run_id=correlation_id,
            job_id=job_id, chat_id=chat_id, model=meta["model"],
            provider=meta["provider"], prompt_len=len(compiled.prompt),
            prompt_hash=prompt_hash(compiled.prompt),
            reference_count=len(ref_paths), issue_number=issue_no,
            fallback=(",".join(compiled.dropped)
                      if compiled.dropped else None))

    # ── T-4815: P0+P1 не помещаются в resolved limit → НЕ режем строковыми
    # ножницами; Base Cover публикуется с понятной причиной (§3). ────────────
    if getattr(compiled, "exceeded", False):
        meta["prompt_diagnostics"] = {
            **(meta.get("prompt_diagnostics") or {}),
            "overflow_reason": "prompt_limit_exceeded",
        }
        emit_cover_event(
            COVER_STYLE_FAILED, outcome="failed", level=logging.WARNING,
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            model=meta["model"], provider=meta["provider"],
            reason="prompt_limit_exceeded", reason_code="prompt_limit_exceeded",
            style_id=meta["style_id"], issue_number=issue_no)
        return await _style_failed(
            meta, state, reason="prompt_limit_exceeded",
            message="Стиль не применён: инструкция превышает лимит модели.",
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            started=started, db=db)

    caller = edit_call
    if caller is None:
        caller = edit_image
    # §23 (T-4199): stage-aware key политики — preview и edit имеют разные
    # latency-распределения. Тестовые double `edit_call` могут не принимать
    # kwargs `operation`/`route` → совместимость через inspect (аддитивно).
    edit_operation = ("preview" if mode == MODE_PREVIEW else "edit")
    try:
        import inspect as _inspect
        _params = _inspect.signature(caller).parameters
        accepts_operation = "operation" in _params
        accepts_route = "route" in _params
    except (TypeError, ValueError):
        accepts_operation = False
        accepts_route = False

    def _call(prompt_text=None):
        use_prompt = compiled.prompt if prompt_text is None else prompt_text
        extra: dict = {}
        if accepts_operation:
            extra["operation"] = edit_operation
        if accepts_route:
            # ASAP 4.4 (§2/T-4873): тот же resolved route, что показывает UI.
            extra["route"] = edit_route or None
        return caller(use_prompt,
                      base_image_path=base_image_path,
                      reference_paths=ref_paths,
                      base_url=slot.get("base_url"),
                      model=slot.get("model"), api_key=_resolve_api_key(),
                      capabilities=caps, chat_id=chat_id,
                      correlation_id=correlation_id,
                      existing_task_id=(state.provider_task_id
                                        if state else None),
                      **extra)

    try:
        result = await _run_with_heartbeat(
            _call, interval=heartbeat_interval(), event=COVER_STYLE_RUNNING,
            run_id=correlation_id, job_id=job_id, model=meta["model"],
            provider=meta["provider"])
    except Exception as exc:
        result = EditResult(ok=False, reason=type(exc).__name__,
                            model=meta["model"], provider=meta["provider"])
    if not isinstance(result, EditResult):        # защита от моков-заглушек
        result = EditResult(ok=bool(getattr(result, "ok", False)),
                            content=getattr(result, "content", None),
                            reason=str(getattr(result, "reason", "error")),
                            task_id=getattr(result, "task_id", None),
                            async_used=bool(getattr(result, "async_used", False)),
                            latency_ms=int(getattr(result, "latency_ms", 0)),
                            meta=dict(getattr(result, "meta", {}) or {}))
    # ── T-4814/T-4875: provider limit → cache/recompile → РОВНО ОДИН bounded
    # retry на весь style stage. Известный N (`prompt_limit`): recompile под
    # лимит; unknown (`prompt_limit_unknown`, 400-too-long без числа):
    # semantic compiler сбрасывает P2/P3, сохраняя P0/P1 инварианты. Второй
    # paid call уходит ТОЛЬКО если prompt реально стал короче (ASAP 4.3
    # §7.1/§8 T-4848); скрытого multi-paid loop нет.
    result_meta = dict(getattr(result, "meta", {}) or {})
    if not result.ok and result.reason in ("prompt_limit",
                                           "prompt_limit_unknown"):
        try:
            if result.reason == "prompt_limit" and result_meta.get(
                    "prompt_limit"):
                if cap.dynamic_prompt_limit_enabled():
                    pl = result_meta["prompt_limit"]
                    cap.record_runtime_limit(
                        meta.get("provider") or "", slot.get("base_url") or "",
                        meta.get("model") or "",
                        result_meta.get("route"), int(pl.get("value") or 0),
                        str(pl.get("unit") or "chars"))
                    caps_retry = cap.resolve_capabilities(
                        meta.get("provider") or "", slot.get("base_url") or "",
                        meta.get("model") or "",
                        route=result_meta.get("route"),
                        operation=edit_operation)
                    recompiled = compile_style_prompt(
                        profile, issue_display=issue_display,
                        capabilities=caps_retry,
                        base_style_prompt=base_style_prompt or "",
                        brief=brief)
                    shorter = len(recompiled.prompt) < len(compiled.prompt)
                    retry_ok = (not getattr(recompiled, "exceeded", False)
                                and shorter)
                    meta["prompt_limit_retry"] = {
                        "resolved_limit": pl.get("value"),
                        "unit": pl.get("unit"),
                        "recompiled_chars": len(recompiled.prompt),
                        "retry_sent": bool(retry_ok),
                    }
                    if not retry_ok:
                        # Bounded retry: exceeded/не короче → второй paid call не
                        # отправляется; честная причина в diagnostics.
                        meta["prompt_limit_retry"]["skipped"] = (
                            "exceeded" if getattr(recompiled, "exceeded", False)
                            else "not_shorter")
                        meta["prompt_diagnostics"] = {
                            **(meta.get("prompt_diagnostics") or {}),
                            "overflow_reason": "prompt_limit_exceeded",
                        }
                        result = EditResult(ok=False, reason="prompt_limit",
                                            model=meta["model"],
                                            provider=meta["provider"],
                                            meta=result.meta)
                    else:
                        emit_cover_event(
                            COVER_STYLE_SUBMITTED, outcome="retry",
                            run_id=correlation_id, job_id=job_id,
                            chat_id=chat_id, model=meta["model"],
                            provider=meta["provider"],
                            prompt_len=len(recompiled.prompt),
                            prompt_hash=prompt_hash(recompiled.prompt),
                            resolved_limit=pl.get("value"),
                            retry_reason="prompt_limit")
                        try:
                            result = await _run_with_heartbeat(
                                lambda: _call(recompiled.prompt),
                                interval=heartbeat_interval(),
                                event=COVER_STYLE_RUNNING,
                                run_id=correlation_id, job_id=job_id,
                                model=meta["model"], provider=meta["provider"])
                        except Exception as exc:
                            result = EditResult(
                                ok=False, reason=type(exc).__name__,
                                model=meta["model"], provider=meta["provider"])
            elif result.reason == "prompt_limit_unknown":
                # T-4875: без числа — P2/P3 сбрасываются, P0/P1 (номер
                # выпуска, запрет дублей, стиль/роли) сохраняются.
                recompiled = compile_style_prompt(
                    profile, issue_display=issue_display,
                    capabilities=caps, base_style_prompt=base_style_prompt
                    or "", brief=None, minimal=True)
                shorter = len(recompiled.prompt) < len(compiled.prompt)
                retry_info = {
                    "original_chars": len(compiled.prompt),
                    "recompiled_chars": len(recompiled.prompt),
                    "retry_sent": bool(shorter),
                }
                if not shorter:
                    # Идентичный/не короче — resend запрещён (деньги впустую).
                    retry_info["skipped"] = "not_shorter"
                else:
                    emit_cover_event(
                        COVER_STYLE_SUBMITTED, outcome="retry",
                        run_id=correlation_id, job_id=job_id, chat_id=chat_id,
                        model=meta["model"], provider=meta["provider"],
                        prompt_len=len(recompiled.prompt),
                        prompt_hash=prompt_hash(recompiled.prompt),
                        retry_reason="prompt_limit_unknown")
                    try:
                        result = await _run_with_heartbeat(
                            lambda: _call(recompiled.prompt),
                            interval=heartbeat_interval(),
                            event=COVER_STYLE_RUNNING, run_id=correlation_id,
                            job_id=job_id, model=meta["model"],
                            provider=meta["provider"])
                    except Exception as exc:
                        result = EditResult(
                            ok=False, reason=type(exc).__name__,
                            model=meta["model"], provider=meta["provider"])
                    if result.ok:
                        # Успешный adaptive retry → route-specific
                        # learned_safe_ceiling (source runtime_safe; НЕ
                        # выдаётся за exact provider max).
                        ceiling = len(recompiled.prompt)
                        retry_info["learned_safe_ceiling"] = ceiling
                        retry_info["ceiling_source"] = "runtime_safe"
                        if cap.dynamic_prompt_limit_enabled():
                            cap.record_runtime_safe_ceiling(
                                meta.get("provider") or "",
                                slot.get("base_url") or "",
                                meta.get("model") or "",
                                result_meta.get("route") or edit_route or None,
                                ceiling, cap.UNIT_CHARS)
                    elif result.reason in ("prompt_limit_unknown",
                                           "prompt_limit"):
                        # Повторный too-long после сокращения — честная
                        # причина, без generic bad_request и без второго retry.
                        result = EditResult(
                            ok=False,
                            reason="prompt_limit_unknown_after_retry",
                            model=meta["model"], provider=meta["provider"],
                            meta=dict(getattr(result, "meta", {}) or {}))
                meta["prompt_limit_unknown_retry"] = retry_info
        except Exception:
            logger.debug("[cover_style_jobs] prompt-limit retry failed",
                         exc_info=True)
    meta["provider_task_id"] = result.task_id
    meta["async_used"] = bool(result.async_used)
    record_latency(meta["model"], "style_edit", result.latency_ms,
                   timeout=(result.reason == "timeout"),
                   retry=False,
                   provider_fallback=False)
    if state is not None and result.task_id:
        state.provider_task_id = result.task_id
        # §43: provider task_id персистится немедленно — рестарт возобновит
        # polling этой же задачи и не создаст новый платный task.
        state.mark(STATE_STYLE_RUNNING, provider_task_id=result.task_id)
        await _persist_state(db, job_id, state)

    if result.ok and result.content:
        path = _write_temp_image(result.content)
        if path is not None:
            meta.update(applied=True, styled_path=path, outcome=RESULT_STYLED,
                        reason="", duration_ms=_elapsed(started),
                        final_asset_id=_asset_id_of(path))
            if state is not None:
                state.mark(STATE_STYLE_SUCCEEDED,
                           provider_task_id=result.task_id)
                await _persist_state(db, job_id, state)
            emit_cover_event(
                COVER_STYLE_SUCCEEDED, outcome="success", run_id=correlation_id,
                job_id=job_id, chat_id=chat_id, model=meta["model"],
                provider=meta["provider"], duration_ms=meta["duration_ms"],
                provider_task_id=result.task_id, async_used=result.async_used,
                style_id=meta["style_id"], style_revision=meta["style_revision"],
                issue_number=issue_no)
            await _record_provenance(
                obj, meta, summary_run_id=summary_run_id, job_id=job_id,
                snapshot=snapshot, status=registry.PROVENANCE_STYLED,
                fallback_mode="", mode=mode)
            return meta
        result = EditResult(ok=False, reason="temp_write_failed",
                            model=meta["model"], provider=meta["provider"])

    meta["fail_reason"] = result.reason
    await _record_provenance(
        obj, meta, summary_run_id=summary_run_id, job_id=job_id,
        snapshot=snapshot, status=registry.PROVENANCE_BASE,
        fallback_mode=REASON_STYLE_FAILED, mode=mode)
    return await _style_failed(
        meta, state, reason=result.reason, message="",
        run_id=correlation_id, job_id=job_id, chat_id=chat_id,
        started=started, db=db)


async def _style_failed(meta: dict, state, *, reason: str, message: str,
                        run_id, job_id, chat_id, started, db=None) -> dict:
    meta.update(applied=False, styled_path=None, outcome=RESULT_BASE,
                reason=REASON_STYLE_FAILED, fail_reason=reason,
                message=message, duration_ms=_elapsed(started))
    if state is not None:
        state.mark(STATE_STYLE_FAILED, note=reason)
        await _persist_state(db, job_id, state)
    if snapshot_enabled():
        # ASAP-4 волна B (§2 B.4): mca_events reason_code перестаёт
        # схлопывать конкретную причину в generic `style_failed`
        # (прод-факт Q14: `not_configured` был невидим в Analytics).
        code = style_reason_code(reason)
    else:
        code = (reason if reason in ("style_failed", "edit_unsupported")
                else REASON_STYLE_FAILED)
    emit_cover_event(
        COVER_STYLE_FAILED, outcome="failed", level=logging.WARNING,
        run_id=run_id, job_id=job_id, chat_id=chat_id, model=meta["model"],
        provider=meta["provider"], duration_ms=meta["duration_ms"],
        reason=reason, fallback=REASON_STYLE_FAILED,
        reason_code=code,
        style_id=meta["style_id"], issue_number=meta.get("issue_number"))
    return meta


async def _record_provenance(pg, meta, *, summary_run_id, job_id, snapshot,
                             status, fallback_mode, mode) -> None:
    if pg is None:
        return
    try:
        await registry.record_provenance(pg, {
            "summary_run_id": summary_run_id, "job_id": job_id,
            "style_id": meta.get("style_id"),
            "style_revision": meta.get("style_revision"),
            "issue_number": meta.get("issue_number"),
            "base_asset_id": meta.get("base_asset_id"),
            "final_asset_id": meta.get("final_asset_id"),
            "provider": meta.get("provider"), "model": meta.get("model"),
            "connection_id": (snapshot or {}).get("connection_id"),
            "reference_asset_ids": (snapshot or {}).get("reference_asset_ids"),
            "status": status, "fallback_mode": fallback_mode, "mode": mode,
        })
    except Exception:
        logger.debug("[cover_style_jobs] provenance record failed",
                     exc_info=True)


async def run_style_preview(*, profile: dict, base_image_path: str,
                            reference_paths: list | None = None, pg=None,
                            capabilities=None, discovery: dict | None = None,
                            endpoints: dict | None = None, edit_call=None,
                            db=None, job_id: str | None = None,
                            state: CoverJobState | None = None,
                            correlation_id: str | None = None) -> dict:
    """`Протестировать стиль` (§65/§66/§67): ТОЛЬКО Style Edit job.

    Не создаёт Summary, не расходует production counter (mode=preview),
    логируется с `mode=preview` (не смешивается со статистикой production).

    ASAP 4.3 (T-4843): preview идёт через тот же durable-контур, что
    production — `db`/`job_id`/`state` прокидываются в `run_style_job`
    (прежде helpers были no-op из-за отсутствия db/job_id).
    """
    meta = await run_style_job(
        chat_id=0, base_image_path=base_image_path, profile=profile,
        summary_run_id=None, correlation_id=correlation_id, pg=pg,
        db=db, job_id=job_id, state=state,
        capabilities=capabilities, discovery=discovery, endpoints=endpoints,
        reference_paths=reference_paths, edit_call=edit_call, mode=MODE_PREVIEW)
    meta["preview_issue"] = registry.preview_issue_display(
        (profile or {}).get("counter_format")
        or registry.SEEDED_COUNTER_FORMAT,
        registry.next_issue_number(profile))
    return meta


def _elapsed(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


__all__ = [
    "COVER_PIPELINE_START", "COVER_BASE_SUBMITTED", "COVER_BASE_RUNNING",
    "COVER_BASE_SUCCEEDED", "COVER_BASE_FAILED", "COVER_STYLE_SELECTION",
    "COVER_STYLE_SKIPPED", "COVER_STYLE_START", "COVER_STYLE_RESOLVE",
    "COVER_STYLE_SUBMITTED", "COVER_STYLE_RUNNING", "COVER_STYLE_SUCCEEDED",
    "COVER_STYLE_FAILED", "COVER_RICH_PUBLISH_START",
    "COVER_RICH_PUBLISH_SUCCEEDED", "COVER_RICH_PUBLISH_FAILED",
    "COVER_PLAIN_FALLBACK", "COVER_PIPELINE_DONE", "RESULT_STYLED",
    "RESULT_BASE", "RESULT_NONE", "RESULT_PLAIN", "REASON_STYLE_FAILED",
    "REASON_BASE_FAILED", "REASON_RICH_FAILED", "REASON_NO_STYLE",
    "REASON_PROFILE_MISSING", "REASON_DISABLED", "REASON_CONNECTION_MISSING",
    "REASON_REFERENCE_MISSING", "REASON_CAPABILITY_UNKNOWN",
    "REASON_NOT_CONFIGURED", "REASON_NO_STYLE_STAGE", "RU_STYLE_FAILED",
    "RU_BASE_FAILED", "RU_RICH_FAILED", "CoverJobState", "start_cover_job",
    "finish_cover_job", "save_cover_state", "load_cover_state",
    "get_cover_job", "requeue_cover_job",
    "begin_cover_job", "cover_job_key", "run_style_job",
    "run_style_preview", "classify_cover_result", "build_timeline",
    "record_latency", "latency_stats", "record_cost", "cost_summary",
    "reset_metrics", "emit_cover_event", "prompt_hash", "compile_style_prompt",
    "snapshot_enabled", "resolve_selection", "emit_style_selection",
    "selection_stage", "profile_for_snapshot", "report_style_skip",
    "record_no_cover_provenance", "style_reason_code", "reason_detail_ru",
    "style_skip_status", "profile_diagnostics", "resolve_selected_style_id",
]
