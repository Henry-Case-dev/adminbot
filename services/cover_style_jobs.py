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
from services import cover_style_registry as registry
from services import image_prompt_compiler as compiler
from services.cover_style_edit import EditResult, edit_image
from services.cover_style_pipeline import (
    KEY_STYLE_API_KEY,
    check_edit_allowed,
    cover_styles_enabled,
    resolve_style_slot,
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
COVER_STYLE_START = "COVER_STYLE_START"
COVER_STYLE_SUBMITTED = "COVER_STYLE_SUBMITTED"
COVER_STYLE_RUNNING = "COVER_STYLE_RUNNING"
COVER_STYLE_SUCCEEDED = "COVER_STYLE_SUCCEEDED"
COVER_STYLE_FAILED = "COVER_STYLE_FAILED"
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
    "async_used", "reference_paths", "mode",
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
            stages=list(data.get("stages") or []))


async def start_cover_job(db, *, chat_id: int, correlation_id: str | None = None,
                          payload: dict | None = None,
                          job_id: str | None = None,
                          coalesce_key: str | None = None) -> str | None:
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
            owner="summary", kind="cover_style", coalesce_key=coalesce_key,
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
                          ) -> tuple[str | None, CoverJobState]:
    """Создать/переиспользовать durable cover-джобу (§42/§43).

    Возвращает `(job_id, state)`. При рестарте существующая джоба находится
    по детерминированному `job_id`/`coalesce_key`, а состояние (включая
    `provider_task_id`) восстанавливается из `task_jobs` — новый платный
    task **не** создаётся (§43, DoD-25).
    """
    if db is None:
        return None, CoverJobState(style_id=style_id)
    coalesce = ("cover_style:%s" % summary_run_id) if summary_run_id else None
    jid = cover_job_key(summary_run_id=summary_run_id, style_id=style_id)
    started = await start_cover_job(
        db, chat_id=chat_id, correlation_id=correlation_id,
        payload={"style_id": style_id, **(payload or {})},
        job_id=jid, coalesce_key=coalesce)
    state = await load_cover_state(db, started) if started else None
    if state is None:
        state = CoverJobState(style_id=style_id)
        # Base-стадия уже успешна к моменту запуска Style-джобы (§3.2/§49).
        state.mark(STATE_BASE_SUCCEEDED)
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


# ── prompt compilation (§19–§21) ────────────────────────────────────────────

def compile_style_prompt(profile: dict, *, issue_display: str,
                         capabilities, base_style_prompt: str = "",
                         brief=None) -> compiler.CompiledPrompt:
    """Собрать priority-aware prompt Style Edit (§19–§21).

    P0 — runtime-инварианты (номер выпуска, запрет дубликатов) — не режется;
    P1 — инструкция стиля профиля и base style prompt (§19: «base style
    prompt»); P2 — описания референсов (режется первым). Динамический
    `CoverBrief` (§21) передаётся как сюжетная часть и масштабируется под
    остаток capability.
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
    """
    started = time.monotonic()
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

    slot = resolve_style_slot(profile=profile)
    meta["provider"] = slot.get("provider") or ""
    meta["model"] = slot.get("model") or ""
    emit_cover_event(COVER_STYLE_START, outcome="start", run_id=correlation_id,
                     job_id=job_id, chat_id=chat_id, model=meta["model"],
                     provider=meta["provider"], style_id=meta["style_id"],
                     style_revision=meta["style_revision"])
    if state is not None:
        state.mark(STATE_STYLE_SUBMITTED)
        await _persist_state(db, job_id, state)

    caps = capabilities
    if caps is None:
        caps = slot_capabilities(profile=profile, discovery=discovery,
                                 endpoints=endpoints)
    allowed, message = check_edit_allowed(profile=profile, capabilities=caps)
    if not allowed:
        # §38: модель без image_edit — API не вызывается, base публикуется.
        return await _style_failed(
            meta, state, reason="edit_unsupported", message=message,
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            started=started, db=db)

    # §27/§28: pin номера выпуска к Summary run (production).
    issue_no = None
    obj = pg if pg is not None else _pg()
    if mode == MODE_PRODUCTION and profile.get("counter_enabled") \
            and summary_run_id and obj is not None:
        try:
            issue_no = await registry.resolve_issue_number(
                obj, profile["profile_id"], summary_run_id)
        except Exception:
            issue_no = None
    meta["issue_number"] = issue_no
    counter_format = profile.get("counter_format") or registry.SEEDED_COUNTER_FORMAT
    issue_display = (registry.format_issue(counter_format, issue_no)
                     if issue_no is not None
                     else registry.preview_issue_display(counter_format))

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
    emit_cover_event(
        COVER_STYLE_SUBMITTED, outcome="start", run_id=correlation_id,
        job_id=job_id, chat_id=chat_id, model=meta["model"],
        provider=meta["provider"], prompt_len=len(compiled.prompt),
        prompt_hash=prompt_hash(compiled.prompt),
        reference_count=len(ref_paths), issue_number=issue_no,
        fallback=(",".join(compiled.dropped) if compiled.dropped else None))

    caller = edit_call
    if caller is None:
        caller = edit_image

    def _call():
        return caller(compiled.prompt, base_image_path=base_image_path,
                      reference_paths=ref_paths, base_url=slot.get("base_url"),
                      model=slot.get("model"), api_key=_resolve_api_key(),
                      capabilities=caps, chat_id=chat_id,
                      correlation_id=correlation_id,
                      existing_task_id=(state.provider_task_id if state else None))

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
                            latency_ms=int(getattr(result, "latency_ms", 0)))
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
    emit_cover_event(
        COVER_STYLE_FAILED, outcome="failed", level=logging.WARNING,
        run_id=run_id, job_id=job_id, chat_id=chat_id, model=meta["model"],
        provider=meta["provider"], duration_ms=meta["duration_ms"],
        reason=reason, fallback=REASON_STYLE_FAILED,
        reason_code=(reason if reason in ("style_failed", "edit_unsupported")
                     else REASON_STYLE_FAILED),
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
                            endpoints: dict | None = None, edit_call=None
                            ) -> dict:
    """`Протестировать стиль` (§65/§66/§67): ТОЛЬКО Style Edit job.

    Не создаёт Summary, не расходует production counter (mode=preview),
    логируется с `mode=preview` (не смешивается со статистикой production).
    """
    meta = await run_style_job(
        chat_id=0, base_image_path=base_image_path, profile=profile,
        summary_run_id=None, correlation_id=None, pg=pg,
        capabilities=capabilities, discovery=discovery, endpoints=endpoints,
        reference_paths=reference_paths, edit_call=edit_call, mode=MODE_PREVIEW)
    meta["preview_issue"] = registry.preview_issue_display(
        (profile or {}).get("counter_format")
        or registry.SEEDED_COUNTER_FORMAT)
    return meta


def _elapsed(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


__all__ = [
    "COVER_PIPELINE_START", "COVER_BASE_SUBMITTED", "COVER_BASE_RUNNING",
    "COVER_BASE_SUCCEEDED", "COVER_BASE_FAILED", "COVER_STYLE_START",
    "COVER_STYLE_SUBMITTED", "COVER_STYLE_RUNNING", "COVER_STYLE_SUCCEEDED",
    "COVER_STYLE_FAILED", "COVER_RICH_PUBLISH_START",
    "COVER_RICH_PUBLISH_SUCCEEDED", "COVER_RICH_PUBLISH_FAILED",
    "COVER_PLAIN_FALLBACK", "COVER_PIPELINE_DONE", "RESULT_STYLED",
    "RESULT_BASE", "RESULT_NONE", "RESULT_PLAIN", "REASON_STYLE_FAILED",
    "REASON_BASE_FAILED", "REASON_RICH_FAILED", "RU_STYLE_FAILED",
    "RU_BASE_FAILED", "RU_RICH_FAILED", "CoverJobState", "start_cover_job",
    "finish_cover_job", "save_cover_state", "load_cover_state",
    "begin_cover_job", "cover_job_key", "run_style_job",
    "run_style_preview", "classify_cover_result", "build_timeline",
    "record_latency", "latency_stats", "record_cost", "cost_summary",
    "reset_metrics", "emit_cover_event", "prompt_hash", "compile_style_prompt",
]
