"""Раунд 10.27 (MCA Wave 0, `mca-13-event-contract`) — контракт события §17.

Единая система наблюдаемости §17 (ADR-1027-2 D1–D11): структурированный JSON
event (`start` + терминальный `outcome`), стабильный расширяемый словарь
`reason_code` §17.2, ошибки/агрегация §17.3, маскирование R17, ретенция
14d/90d, метрики §17.4.

Границы (REUSE, вторая система запрещена):
  * точка эмиссии — расширение существующего `services/agentic_events.py`
    (этот модуль — его контрактный слой, не второй emitter);
  * durable-стор — `mca_events`/`mca_event_aggregates` (v15, единственный;
    `mca-17a` читает ЕГО);
  * подробные start/стадии — структурный лог (bounded ring + файл/journald);
  * запись — через общий write-механизм `mca-01` (`write_transaction`).

Kill-switch (env-only, default ON, per-call, не бросают):
  * `MCA_EVENT_CONTRACT_ENABLED` — OFF → контракт не активен;
  * `MCA_TELEMETRY_STORE_ENABLED` — OFF → без durable-персистенции;
  * существующий `AGENTIC_EVENTS_ENABLED` уважается.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import tempfile
import time

from services import mca_gates
from services.agentic_events import _safe_value
from services.log_ring import sanitize

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "2"

# ── уровни/исходы (§17.1) ───────────────────────────────────────────────────
LEVEL_INFO = "INFO"
LEVEL_WARN = "WARN"
LEVEL_ERROR = "ERROR"
LEVELS = frozenset({LEVEL_INFO, LEVEL_WARN, LEVEL_ERROR})

OUTCOME_START = "start"
OUTCOME_SUCCESS = "success"
OUTCOME_SILENT = "silent"
OUTCOME_SKIPPED = "skipped"
OUTCOME_FAILED = "failed"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_PENDING_EXTERNAL = "pending_external"
OUTCOME_INTERRUPTED = "interrupted"
TERMINAL_OUTCOMES = frozenset({
    OUTCOME_SUCCESS, OUTCOME_SILENT, OUTCOME_SKIPPED, OUTCOME_FAILED,
    OUTCOME_CANCELLED, OUTCOME_PENDING_EXTERNAL, OUTCOME_INTERRUPTED,
})
ALL_OUTCOMES = frozenset(TERMINAL_OUTCOMES | {OUTCOME_START})

# ── словарь reason_code §17.2 (базовый минимум 27 + алиасы расширения) ───────
REASON_CODES = frozenset({
    "no_relevant_memory", "ambiguous_identity", "source_missing",
    "source_revision_changed", "insufficient_evidence",
    "contradictory_evidence", "already_answered", "wrong_moment",
    "no_new_contribution", "intent_not_due", "intent_expired",
    "intent_closed", "stale_context", "no_eligible_alternative",
    "queue_coalesced", "queue_full", "deadline_exceeded", "tool_step_limit",
    "provider_unavailable", "provider_unconfigured", "random_fallback",
    "delivery_unknown", "financial_limit_disabled", "financial_limit_reached",
    "context_compacted", "archive_checkpoint_saved",
    "cleanup_deferred_dependency_unverified",
    # дополнительные коды, используемые кодом волны 0 (расширение разрешено).
    "worker_lost", "lock_exhausted", "rollback_failed",
    "connection_unrecoverable", "queue_rejected",
    # расширение MCA-03/10.27 (WARN при legacy-дублях identity, ADR-1027-4 D7).
    "duplicate_identity_rows",
    # расширение MCA-02/10.27 (SafeFetcher: SSRF/redirect/egress/лимиты,
    # ADR-1027-5 D7/D12; §17.2 — словарь расширяемый).
    "scheme_not_allowed", "credentials_in_url", "invalid_url",
    "destination_blocked", "metadata_endpoint_blocked", "redirect_blocked",
    "too_many_redirects", "resolve_failed", "too_many_bytes",
    "decompressed_too_large", "safe_fetch_timeout", "egress_guard_unavailable",
    "client_error",
    # расширение MCA-04a/10.27 (provenance: связь/резолв/восстановление/
    # конфликт/невалидное evidence — ADR-1027-6 D12; §17.2 расширяемый).
    "provenance_linked", "provenance_unresolved", "evidence_invalid",
    "provenance_reconstructed", "provenance_conflict",
    # расширение MCA-07/10.27 (retrieval/reranker/bundle/budget/summary —
    # ADR-1027-7 D11; §17.2 расширяемый; ровно 10 кодов из spec §4.9).
    "retrieval_empty", "rerank_invalid", "rerank_timeout", "budget_exceeded",
    "context_overflow", "embedding_generation_changed",
    "summary_stale_dropped", "answer_cache_disabled", "exact_match_used",
    "episodes_used",
    # расширение MCA-17a/10.27 (ADR-1027-8 D3/§4.9): стадии/run/heartbeat/
    # takeover/recovery/spool/incidents/fallback/deny/idempotent-replay.
    "stage_queued", "stage_waiting_external", "stage_retry_scheduled",
    "stage_skipped", "run_partial", "run_degraded", "run_stalled",
    "heartbeat_stale", "progress_stall", "takeover_recovered",
    "recovery_from_checkpoint", "checkpoint_missing", "telemetry_degraded",
    "telemetry_gap", "spool_exhausted", "incident_opened",
    "incident_acknowledged", "incident_resolved", "incident_reopened",
    "fallback_engaged", "job_not_allowed", "action_idempotent_replay",
    # расширение EXTRA/10.28 (cover style pipeline, ADR-1028-4 D9; §96):
    # fallback ladder + capability-gated style stage; §17.2 расширяемый.
    "style_failed", "base_failed", "rich_failed", "edit_unsupported",
    "cover_style_unavailable",
    # расширение mca-04b/10.27 (dossier rebuild: стадии/состояния/каскад —
    # ADR-1027-9 D11/D3; §17.2 расширяемый; interrupted/cancelled/
    # evidence_invalid/provenance_unresolved/embedding_generation_changed
    # переиспользуются из блоков выше).
    # H-2 (review round 1): честная финализация по spec §3.2 — коды
    # `model_unavailable` (недоступность модели) и `parse_error` добавлены
    # в словарь явно (комментарий раньше ошибочно считал их существующими).
    "model_unavailable", "parse_error",
    "dossier_rebuild_started", "dossier_batch_processed",
    "dossier_paused_budget", "dossier_interrupted", "dossier_partial_range",
    "dossier_reclassified", "dossier_staging_activated",
    "dossier_generation_superseded", "dossier_cascade_scheduled",
    "dossier_identity_unresolved",
    # H-1 (review round 1): персистентация кандидатов прерванного прогона
    # в staging до паузы не удалась — пауза молча теряла бы сегмент
    # (честный failed вместо paused).
    "dossier_pending_staging_failed",
    # расширение mca-05/10.27 (episodes/stories: стадии пайплайна/склейки/
    # legacy-маппинг/backfill/перепроверка — ADR-1027-12, санкции §Санкции;
    # §17.2 расширяемый; parse_error/model_unavailable/evidence_invalid/
    # provenance_unresolved/source_revision_changed/cancelled/
    # insufficient_evidence/contradictory_evidence переиспользуются из
    # блоков выше). Финальный набор +10.
    "episode_extracted", "story_segment_empty",
    "story_continuation_confirmed", "story_continuation_rejected",
    "story_contradiction_found", "story_legacy_unmapped",
    "story_backfill_paused_budget", "story_source_recheck_queued",
    "story_merged", "story_split",
    # расширение mca-22/10.27 (FINAL INTEGRATION: freshness/quote/claim/
    # ledger/correction — ADR-1028-6 D10; §17.2 расширяемый; имена событий
    # `DIRECT_*` — свободная ось event_name mca-13, словаря не требуют).
    "direct_update_dedup_hit", "direct_final_replay_blocked",
    "direct_fresh_generation", "direct_freshness_retry",
    "direct_intermediate_cache_hit", "quote_resolved", "quote_ambiguous",
    "quote_unresolved", "subject_unresolved_skipped",
    "correction_revalidation_queued", "bot_output_recorded",
    "bot_output_undelivered_skipped",
})

# ── контракт полей §17.1 ────────────────────────────────────────────────────
# R17-safe типы (id/числа/enum/короткие строки) — реиспользуем валидатор
# `agentic_events._safe_value` (единый whitelist-механизм).
_ID_FIELDS = frozenset({
    "trace_id", "operation_id", "parent_operation_id", "chat_id",
    "message_id", "trigger_ref", "entity_id",
    # v19 (`mca-17a`): span-контракт §27.3 — идентификаторы/link-safe строки.
    "pipeline_run_id", "span_id", "parent_span_id", "job_id", "attempt_id",
    "causation_id", "checkpoint_ref",
})
_NUMERIC_FIELDS = frozenset({
    "duration_ms", "attempt", "cost_usd", "input_tokens", "output_tokens",
    "queue_depth", "queue_age_ms",
    # v19 (`mca-17a`): sequence/heartbeat/progress/deadline (unix/счётчик).
    "event_sequence", "heartbeat_at", "progress_at", "deadline_at",
})
_CODE_FIELDS = frozenset({
    "level", "outcome", "component", "stage", "reason_code", "config_version",
    "model", "provider", "status",
    # v19 (`mca-17a`): тип/версия pipeline (§27.3).
    "pipeline_type", "pipeline_version",
})
_JSON_FIELDS = frozenset({
    "entity_ids", "usage_json", "error_json", "source_ref_json",
    # v19 (`mca-17a`): JSON-массив linked span id (§27.3).
    "linked_span_ids",
})
_SHORT_FIELDS = frozenset({"event_name"})

ALLOWED_FIELDS = (
    _ID_FIELDS | _NUMERIC_FIELDS | _CODE_FIELDS | _JSON_FIELDS
    | _SHORT_FIELDS | frozenset({"schema_version", "ts"})
)

# ── bounded in-memory буфер терминальных событий (A53: неограниченный запрещён)
_PENDING_MAX = 256
_pending: "collections.deque[dict]" = collections.deque(maxlen=_PENDING_MAX)
# Счётчик отброшенных при переполнении буфера (видимый gap/degraded, A53).
_dropped_total = 0

# ── ограниченный дисковый spool (§27.7/D11) ─────────────────────────────────
# При недоступном хранилище события уходят в bounded JSONL-spool (не в
# бесконечный RAM); переполнение → видимые `gaps`. Счётчики недоставленных/
# потерянных + `telemetry_degraded` отдаются адаптером метрик.
_spooled_total = 0
_gaps_total = 0
_degraded = False


def _spool_path() -> str:
    """Путь spool-файла (env `MCA_TELEMETRY_SPOOL_PATH` либо tempdir)."""
    path = os.getenv("MCA_TELEMETRY_SPOOL_PATH")
    if path:
        return path
    return os.path.join(tempfile.gettempdir(), "adminbot_mca_events_spool.jsonl")


def dropped_total() -> int:
    """Число событий, потерянных из-за переполнения bounded-буфера (A53)."""
    return _dropped_total


def spooled_total() -> int:
    """Число событий, отложенных в дисковый spool (не потерянных)."""
    return _spooled_total


def gaps_total() -> int:
    """Число событий, потерянных из-за исчерпания spool/буфера (A53)."""
    return _gaps_total


def telemetry_degraded() -> bool:
    """Телеметрия деградирована (flush падал/spool непуст) — A53."""
    return _degraded


def spool_size() -> int:
    path = _spool_path()
    try:
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return 0


def pending_size() -> int:
    return len(_pending)


def reset_pending() -> None:
    """Очистить буфер и счётчики spool (тесты)."""
    global _dropped_total, _spooled_total, _gaps_total, _degraded
    _pending.clear()
    _dropped_total = 0
    _spooled_total = 0
    _gaps_total = 0
    _degraded = False


def _spool_append(events: list[dict]) -> None:
    """Дописать события в bounded spool; переполнение → drop oldest (gaps)."""
    global _spooled_total, _gaps_total, _degraded
    if not mca_gates.telemetry_spool_enabled():
        _degraded = True
        _gaps_total += len(events)
        return
    max_events = mca_gates.telemetry_spool_max_events()
    path = _spool_path()
    try:
        existing: list[str] = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                existing = [line for line in fh if line.strip()]
        lines = existing + [json.dumps(e, ensure_ascii=False) for e in events]
        if len(lines) > max_events:
            drop = len(lines) - max_events
            _gaps_total += drop
            lines = lines[drop:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
        os.replace(tmp, path)
        _spooled_total += len(events)
        _degraded = True
    except Exception:
        # Spool недоступен → не бесконечный RAM-буфер: считаем как gap.
        _gaps_total += len(events)
        _degraded = True


def _read_spool_events() -> list[dict]:
    """Прочитать события из spool (JSONL); битые строки пропускаются."""
    path = _spool_path()
    events: list[dict] = []
    try:
        if not os.path.exists(path):
            return events
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if isinstance(ev, dict):
                        events.append(ev)
                except Exception:
                    continue
    except Exception:
        return events
    return events


def _clear_spool() -> None:
    try:
        path = _spool_path()
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass





def _sanitize_str(value: str, limit: int = 200) -> str:
    """R17: маскировать секреты и усечь; пробелы допустимы (это лог-контракт)."""
    text = str(value)
    if len(text) > limit:
        text = text[:limit]
    return sanitize(text)


def build_event(event_name: str, *, outcome: str, level: str = LEVEL_INFO,
                **fields) -> dict | None:
    """Собрать R17-safe событие контракта §17.1 (или `None` при невалидном).

    Обязательные: `event_name`, `outcome`. Небезопасные ключи/значения
    отбрасываются. `ts` — UTC unix; `trace_id` = run_id/correlation_id."""
    try:
        name = _safe_value("event_name", event_name)
        if not name:
            return None
        if outcome not in ALL_OUTCOMES:
            return None
        if level not in LEVELS:
            level = LEVEL_INFO
        event: dict = {
            "schema_version": SCHEMA_VERSION,
            "ts": int(time.time()),
            "event_name": name,
            "outcome": outcome,
            "level": level,
        }
        for key, value in fields.items():
            if key in ("event_name", "outcome", "level", "schema_version",
                       "ts"):
                continue
            if key not in ALLOWED_FIELDS:
                continue
            if key in _JSON_FIELDS:
                if value is None:
                    continue
                # B-MCA13-1: сериализованный JSON проходит sanitize() —
                # секретоподобные значения в контейнере маскируются.
                event[key] = sanitize(
                    json.dumps(value, ensure_ascii=False))[:2000]
                continue
            if key in _SHORT_FIELDS:
                if isinstance(value, str) and value.strip():
                    event[key] = _sanitize_str(value, 120)
                continue
            if key in _NUMERIC_FIELDS:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                event[key] = value
                continue
            if key in _CODE_FIELDS:
                if key == "reason_code":
                    event[key] = str(value) if value in REASON_CODES else None
                    if event[key] is None:
                        event.pop(key, None)
                    continue
                clean = _safe_value(key, value)
                if clean is not None:
                    # B-MCA13-1: строковые code/enum-поля тоже маскируются —
                    # value может быть regex-совместимым секретом (token).
                    event[key] = _sanitize_str(str(clean), 120)
                continue
            if key in _ID_FIELDS:
                clean = _safe_value(key, value)
                if clean is not None:
                    event[key] = _sanitize_str(str(clean), 120)
        return event
    except Exception:      # fail-open: контракт не рвёт поток
        return None


def _emit_log(event: dict) -> None:
    """Структурная строка лога (R17-safe; start и все стадии).

    B-MCA13-1: строка дополнительно проходит `sanitize()` (defense-in-depth).
    L-MCA13-2: уровень события отражается в логе (WARN/ERROR не как INFO)."""
    try:
        parts = [f"{k}={v}" for k, v in event.items()
                 if k not in ("schema_version",)]
        line = sanitize("mca_event=%s | %s" % (
            event.get("event_name"), " | ".join(parts)))
        level = str(event.get("level") or LEVEL_INFO).upper()
        if level == LEVEL_ERROR:
            logger.error(line)
        elif level == LEVEL_WARN:
            logger.warning(line)
        else:
            logger.info(line)
    except Exception:      # pragma: no cover
        return


def emit_mca_event(event_name: str, *, outcome: str,
                   level: str = LEVEL_INFO, **fields) -> dict | None:
    """Fail-open точка эмиссии контракта §17.1 (по ADR-1027-2 D2).

    Синхронная, никогда не бросает: kill-switch → сборка события → лог →
    (если терминальный и телеметрия ON) bounded-буфер под durable-write.
    Дurable-запись выполняет `flush_events(db)` (фоново/на shutdown) через
    общий write-механизм `mca-01`, чтобы не блокировать hot-path."""
    try:
        if not mca_gates.event_contract_enabled():
            return None
        event = build_event(event_name, outcome=outcome, level=level, **fields)
        if event is None:
            return None
        _emit_log(event)
        # Буфер durable-персистенции: терминальные события (MCA-13) + любые
        # span-события (start/стадии §27.3 — начало/переходы run обязательны,
        # §27.7). При OFF `MCA_TRACE_SPAN_ENABLED` span-полей нет → поведение
        # ровно как в baseline (только терминальные).
        is_span = bool(event.get("pipeline_run_id") or event.get("span_id"))
        if ((event["outcome"] in TERMINAL_OUTCOMES or is_span)
                and mca_gates.telemetry_store_enabled()):
            global _dropped_total
            if len(_pending) >= _PENDING_MAX:
                _dropped_total += 1      # видимый gap (A53), не молчаливая потеря
            _pending.append(event)
        return event
    except Exception:      # fail-open: поток не рвём
        return None


_MCA_EVENTS_INSERT_COLS = (
    "ts", "level", "event_name", "outcome", "trace_id", "operation_id",
    "parent_operation_id", "chat_id", "component", "stage", "reason_code",
    "duration_ms", "attempt", "config_version", "model", "provider",
    "entity_ids", "usage_json", "error_json", "source_ref_json",
    "pipeline_run_id", "pipeline_type", "pipeline_version", "span_id",
    "parent_span_id", "linked_span_ids", "job_id", "attempt_id",
    "causation_id", "event_sequence", "status", "heartbeat_at", "progress_at",
    "deadline_at", "checkpoint_ref",
)
_MCA_EVENTS_INSERT_SQL = (
    "INSERT INTO mca_events (" + ", ".join(_MCA_EVENTS_INSERT_COLS)
    + ") VALUES (" + ",".join("?" * len(_MCA_EVENTS_INSERT_COLS)) + ")")


async def _insert_event(conn, ev: dict) -> None:
    """Вставить событие (v19-колонки, nullable=честный unknown)."""
    await conn.execute(_MCA_EVENTS_INSERT_SQL,
                       tuple(ev.get(c) for c in _MCA_EVENTS_INSERT_COLS))


async def flush_events(db) -> int:
    """Слить буфер (+spool) событий в `mca_events` (+агрегаты).

    Одна короткая транзакция через write-механизм `mca-01`. Возвращает число
    записанных событий. При недоступном хранилище — ограниченный дисковый
    spool + `telemetry_degraded`/`gaps` (§27.7); бесконечный RAM-буфер
    запрещён. Fail-safe: ошибка БД не роняет вызывающего.

    B-MCA17A-2/F2: буфер **своп-очереди** — снимок и очистка выполняются
    синхронно (без `await` между ними; event-loop однопоточный), поэтому
    события, эмитированные другой корутиной во время `await write_transaction`,
    попадают в УЖЕ пустую очередь и не теряются. Никакого `_pending.clear()`
    после `await` (прежний тихий drop)."""
    global _degraded
    if db is None:
        return 0
    enabled = mca_gates.telemetry_store_enabled()
    if not enabled:
        return 0
    # Снапшот + очистка — синхронно (атомарно относительно event loop).
    pending = list(_pending)
    _pending.clear()
    spool_events = _read_spool_events()
    batch = spool_events + pending
    if not batch:
        _degraded = _dropped_total > 0 or _gaps_total > 0
        return 0

    async def _body(conn):
        written = 0
        for ev in batch:
            await _insert_event(conn, ev)
            written += 1
            if ev.get("level") == LEVEL_ERROR and ev.get("error_json"):
                await _upsert_aggregate(conn, ev)
        return written

    try:
        written = await db.write_transaction(_body, op_name="mca_events_flush")
    except Exception:
        logger.warning("[mca_events] flush failed — events -> bounded spool",
                       exc_info=True)
        # Снимок уже снят из очереди; новые события (после свопа) остаются.
        _spool_append(pending)
        return 0
    # Успех: очистить spool (снимок очереди уже выведен из буфера свопом).
    if spool_events:
        _clear_spool()
    _degraded = _dropped_total > 0 or _gaps_total > 0
    return written


async def _upsert_aggregate(conn, ev: dict) -> None:
    """Агрегат повторяющейся ошибки (fingerprint) — сбой НЕ исчезает (D6)."""
    try:
        fingerprint = ":".join([
            str(ev.get("event_name") or ""),
            str(ev.get("component") or ""),
            str(ev.get("reason_code") or ""),
            _error_type(ev.get("error_json")),
        ])[:200]
        await conn.execute(
            "INSERT INTO mca_event_aggregates (fingerprint, count, first_ts, "
            "last_ts, first_trace_id, first_error_json) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(fingerprint) DO UPDATE SET "
            "count = count + 1, last_ts = excluded.last_ts",
            (fingerprint, 1, ev.get("ts"), ev.get("ts"),
             ev.get("trace_id"), ev.get("error_json")))
    except Exception:      # pragma: no cover - агрегат не должен рвать flush
        return


def _error_type(error_json) -> str:
    try:
        data = json.loads(error_json) if isinstance(error_json, str) \
            else (error_json or {})
        return str(data.get("type") or "")[:64]
    except Exception:
        return ""


def build_error_metadata(exc: BaseException, *, stage: str | None = None,
                         retryable: bool | None = None,
                         recovery: str | None = None) -> dict:
    """§17.3: тип/очищенный stack/cause chain/стадия/retryability/восстановление.

    R17: stack маскируется; сырые значения не переносятся."""
    import traceback
    try:
        cleaned = sanitize("".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)))
        cause = exc.__cause__ or exc.__context__
        return {
            "type": type(exc).__name__,
            "stack": cleaned[:2000],
            "cause": type(cause).__name__ if cause is not None else None,
            "stage": stage,
            "retryable": retryable,
            "recovery": recovery,
        }
    except Exception:      # pragma: no cover
        return {"type": type(exc).__name__}


# ── ретенция / чтение / метрики (v15) ───────────────────────────────────────

async def prune_events(db) -> int:
    """Ретенция терминальных событий `MCA_TERMINAL_EVENT_RETENTION_DAYS` (90d).

    События ручного изменения и происхождение памяти этой ротацией **не**
    удаляются (у них `component` из protected-набора — см. §17.3). Уважает
    kill-switch `MCA_TELEMETRY_STORE_ENABLED` (OFF → no-op)."""
    if db is None or not mca_gates.telemetry_store_enabled():
        return 0
    days = mca_gates.terminal_event_retention_days()
    cutoff = int(time.time()) - days * 86400
    protected = ("memory_manual", "memory_provenance")

    async def _body(conn):
        placeholders = ",".join("?" for _ in protected)
        cursor = await conn.execute(
            "DELETE FROM mca_events WHERE ts < ? AND (component IS NULL OR "
            f"component NOT IN ({placeholders}))",
            (cutoff, *protected))
        await conn.execute(
            "DELETE FROM mca_event_aggregates WHERE last_ts < ?", (cutoff,))
        return cursor.rowcount

    return int(await db.write_transaction(_body, op_name="mca_events_prune")
               or 0)


async def query_events(db, *, trace_id=None, chat_id=None, component=None,
                       reason_code=None, pipeline_run_id=None, span_id=None,
                       status=None, limit: int = 200,
                       offset: int = 0) -> list[dict]:
    """Фильтры §17.4/§27.3 (bounded LIMIT + серверная пагинация `offset`).

    Дополнительно (carry-over §94.5/SC-14): `pipeline_run_id`/`span_id`/
    `status` — связь событий по ID/sequence, а не по timestamp."""
    if db is None:
        return []
    clauses, params = [], []
    if trace_id is not None:
        clauses.append("trace_id = ?"); params.append(trace_id)
    if chat_id is not None:
        clauses.append("chat_id = ?"); params.append(chat_id)
    if component is not None:
        clauses.append("component = ?"); params.append(component)
    if reason_code is not None:
        clauses.append("reason_code = ?"); params.append(reason_code)
    if pipeline_run_id is not None:
        clauses.append("pipeline_run_id = ?"); params.append(pipeline_run_id)
    if span_id is not None:
        clauses.append("span_id = ?"); params.append(span_id)
    if status is not None:
        clauses.append("status = ?"); params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(1000, int(limit))))
    params.append(max(0, int(offset)))
    order = ("ORDER BY pipeline_run_id, event_sequence"
             if pipeline_run_id is not None else "ORDER BY ts DESC")
    cursor = await db.db.execute(
        f"SELECT * FROM mca_events{where} {order} LIMIT ? OFFSET ?", params)
    return [dict(r) for r in await cursor.fetchall()]


async def query_run_events(db, run_id: str, *, limit: int = 500) -> list[dict]:
    """Связанные события одного run в порядке `event_sequence` (§27.3)."""
    return await query_events(db, pipeline_run_id=run_id, limit=limit)


# ── background-контур: wiring flush/prune (carry-over §94.5 п.4) ────────────
# Уважает ОБА kill-switch (`MCA_EVENT_CONTRACT_ENABLED` + `MCA_TELEMETRY_STORE_ENABLED`).
# Reassessment триггера «конкуренция записи» (§94.5 п.5): подключение flush в
# worker-loop активирует кандидат R2→R3 — запись батчей конкурирует за
# single-writer lock с direct flow (зафиксировано в evidence/threat).

_telemetry_task = None
_telemetry_stop = None
_full_flush_count = 0


def _telemetry_enabled() -> bool:
    # F6 (master-aware): `MCA_OBSERVABILITY_ENABLED` OFF → фоновый контур
    # flush/prune выключен (точный паритет baseline; carry-over mca-13 сам по
    # себе не запускает запись без mca-17a). Уважаются ОБА mca-13-гейта.
    return (mca_gates.observability_enabled()
            and mca_gates.event_contract_enabled()
            and mca_gates.telemetry_store_enabled())


async def flush_and_prune(db, *, prune: bool = False) -> dict:
    """Один проход фонового контура: flush (+ периодически prune). Fail-open."""
    if db is None or not _telemetry_enabled():
        return {"flushed": 0, "pruned": 0, "enabled": False}
    flushed = await flush_events(db)
    pruned = await prune_events(db) if prune else 0
    return {"flushed": flushed, "pruned": pruned, "enabled": True}


async def telemetry_loop(db, *, flush_interval_seconds: int = 60,
                         prune_every: int = 60, stop_event=None) -> None:
    """Периодический flush (+ редкий prune) в фоне (не на hot-path)."""
    global _full_flush_count
    iterations = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            iterations += 1
            await flush_and_prune(db, prune=(iterations % max(1, prune_every)
                                            == 0))
            _full_flush_count = iterations
        except Exception:
            logger.warning("[mca_events] telemetry loop iteration failed",
                           exc_info=True)
        try:
            if stop_event is not None:
                try:
                    await asyncio.wait_for(stop_event.wait(),
                                           timeout=flush_interval_seconds)
                    return
                except asyncio.TimeoutError:
                    continue
            await asyncio.sleep(flush_interval_seconds)
        except asyncio.CancelledError:
            return


def start_telemetry_flusher(db, *, flush_interval_seconds: int = 60,
                            prune_every: int = 60):
    """Запустить фоновый flush/prune (идемпотентно); OFF-гейт → None."""
    global _telemetry_task, _telemetry_stop
    if db is None or not _telemetry_enabled():
        return None
    if _telemetry_task is not None and not _telemetry_task.done():
        return _telemetry_task
    _telemetry_stop = asyncio.Event()
    _telemetry_task = asyncio.create_task(
        telemetry_loop(db, flush_interval_seconds=flush_interval_seconds,
                       prune_every=prune_every, stop_event=_telemetry_stop))
    return _telemetry_task


async def stop_telemetry_flusher(db=None) -> None:
    """Остановить фоновый контур (shutdown); финальный flush."""
    global _telemetry_task, _telemetry_stop
    if _telemetry_stop is not None:
        _telemetry_stop.set()
    if _telemetry_task is not None:
        try:
            await asyncio.wait_for(_telemetry_task, timeout=5)
        except Exception:
            _telemetry_task.cancel()
    _telemetry_task = None
    _telemetry_stop = None
    if db is not None and _telemetry_enabled():
        try:
            await flush_events(db)
        except Exception:
            pass


# ── §17.4: единый адаптер метрик витрины ────────────────────────────────────

# Группы §17.4 (ADR-1027-2 D9). Поле без источника → `available=False` и
# значения `None`: UNKNOWN отображается как «неизвестно», не 0/здоровье.
_METRIC_GROUPS = (
    "tasks", "lock", "cache", "providers", "degradations", "provenance",
    "memory", "archive", "initiatives", "delivery", "random", "cost",
    "downloads", "runtime",
)

# Защитный потолок разбора `usage_json` (bounded; витрина не читает весь стор).
_USAGE_SCAN_LIMIT = 1000


def _metric_group(available: bool = False, **values) -> dict:
    group = {"available": bool(available)}
    group.update(values)
    return group


def _unknown_metrics() -> dict:
    metrics = {name: _metric_group() for name in _METRIC_GROUPS}
    metrics["degradations"] = _metric_group(
        dropped_total=dropped_total(), spooled_total=spooled_total(),
        gaps_total=gaps_total(), degraded=telemetry_degraded())
    return metrics


async def _row(db, sql: str, params=()):
    """Одна строка или `None` (fail-open: адаптер не рвёт витрину)."""
    try:
        cursor = await db.db.execute(sql, params)
        return await cursor.fetchone()
    except Exception:
        return None


async def _rows(db, sql: str, params=()) -> list | None:
    try:
        cursor = await db.db.execute(sql, params)
        return await cursor.fetchall()
    except Exception:
        return None


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def metrics(db, *, runtime: dict | None = None) -> dict:
    """§17.4: единый адаптер метрик витрины (ADR-1027-2 D9).

    Источники: durable `mca_events` + `task_jobs` (SQLite), in-process
    счётчики `services.database` (`lock exhausted/retry`) и опциональный
    `runtime`-словарь живых источников (`cache_entries`, `rss_mb`,
    `downloads`, `provenance_coverage`, `histories`/`episodes`), который
    поставляет вызывающий контур (MCA-17a). Поле без источника → `None` и
    `available=False`: UNKNOWN ≠ 0/здоровье. Никогда не бросает.
    """
    runtime = runtime or {}
    result: dict = {
        "available": False,
        "source": "mca_events",
        "events_total": None,
        "errors_total": None,
        "degraded_total": None,
        "dropped_total": dropped_total(),
        "spooled_total": spooled_total(),
        "gaps_total": gaps_total(),
        "telemetry_degraded": telemetry_degraded(),
        "degraded_share": None,
        "metrics": _unknown_metrics(),
        "unknown": list(_METRIC_GROUPS),
    }
    if db is None:
        return result
    try:
        row = await _row(db, "SELECT COUNT(*) AS c FROM mca_events")
        if row is None:
            return result
        total = int(row["c"])
        errors = _int_or_none(
            (await _row(db, "SELECT COUNT(*) AS c FROM mca_events "
                            "WHERE level = ?", (LEVEL_ERROR,)))["c"]) or 0
        interrupted = _int_or_none(
            (await _row(db, "SELECT COUNT(*) AS c FROM mca_events "
                            "WHERE outcome = ?",
                        (OUTCOME_INTERRUPTED,)))["c"]) or 0
        dropped = dropped_total()
        result.update({
            "available": True,
            "events_total": total,
            "errors_total": int(errors),
            "degraded_total": int(interrupted),
            "dropped_total": int(dropped),
        })
        if total > 0:
            result["degraded_share"] = round(
                (int(interrupted) + int(dropped)) / total, 6)

        groups: dict = result["metrics"]

        # tasks/archive — durable очередь `task_jobs` (v14, `mca-01`).
        status_rows = await _rows(
            db, "SELECT status, COUNT(*) AS c FROM task_jobs GROUP BY status")
        if status_rows is not None:
            counts = {str(r["status"]): int(r["c"]) for r in status_rows}
            queued = counts.get("queued", 0)
            oldest = await _row(
                db, "SELECT MIN(created_at) AS m FROM task_jobs "
                    "WHERE status = 'queued'")
            queue_age = None
            if oldest is not None and oldest["m"] is not None:
                queue_age = max(0, int(time.time()) - int(oldest["m"]))
            groups["tasks"] = _metric_group(
                True, active=counts.get("running", 0), pending=queued,
                queue_depth=queued, queue_age_seconds=queue_age)
            archive_active = _int_or_none((await _row(
                db, "SELECT COUNT(*) AS c FROM task_jobs WHERE owner = "
                    "'archive' AND status IN ('queued', 'running')"))["c"])
            archive_rows = await _rows(
                db, "SELECT payload FROM task_jobs WHERE owner = 'archive' "
                    "AND status IN ('queued', 'running')")
            processed = 0
            have_processed = False
            for item in archive_rows or []:
                try:
                    data = json.loads(item["payload"])
                except Exception:
                    continue
                if isinstance(data, dict) and data.get("processed") is not None:
                    try:
                        processed += int(data["processed"])
                        have_processed = True
                    except (TypeError, ValueError):
                        continue
            groups["archive"] = _metric_group(
                True, active_jobs=int(archive_active or 0),
                processed=(processed if have_processed else None))

        # lock — in-process счётчики F0.5/MCA-01 (`services.database`).
        try:
            from services.database import (database_lock_exhausted_total,
                                           database_lock_retry_total)
            groups["lock"] = _metric_group(
                True, exhausted_total=database_lock_exhausted_total(),
                retry_total=database_lock_retry_total())
        except Exception:
            pass

        # providers — реальные latency/ошибки из терминальных событий.
        provider = await _row(
            db, "SELECT COUNT(*) AS c, "
                "SUM(CASE WHEN outcome = ? THEN 1 ELSE 0 END) AS e, "
                "AVG(duration_ms) AS a, MAX(duration_ms) AS m "
                "FROM mca_events WHERE provider IS NOT NULL "
                "AND provider != ''", (OUTCOME_FAILED,))
        if provider is not None and int(provider["c"] or 0) > 0:
            avg = provider["a"]
            groups["providers"] = _metric_group(
                True, requests=int(provider["c"]),
                errors=int(provider["e"] or 0),
                latency_avg_ms=(round(float(avg), 3)
                                if avg is not None else None),
                latency_max_ms=_int_or_none(provider["m"]))

        # initiatives/delivery/random — распределение причин и исходов.
        reason_rows = await _rows(
            db, "SELECT reason_code, COUNT(*) AS c FROM mca_events "
                "WHERE reason_code IS NOT NULL GROUP BY reason_code "
                "ORDER BY c DESC LIMIT 50")
        if reason_rows is not None and total > 0:
            reasons = {str(r["reason_code"]): int(r["c"])
                       for r in reason_rows}
            groups["initiatives"] = _metric_group(
                True, silence_reasons=reasons)
            groups["random"] = _metric_group(
                True, fallback_total=reasons.get("random_fallback", 0),
                sources=None)
        delivery_rows = await _rows(
            db, "SELECT outcome, COUNT(*) AS c FROM mca_events "
                "WHERE component = 'delivery' GROUP BY outcome")
        if delivery_rows:
            groups["delivery"] = _metric_group(
                True, results={str(r["outcome"]): int(r["c"])
                               for r in delivery_rows})

        # cost — только реально переданный `usage_json` (bounded-скан).
        usage_rows = await _rows(
            db, "SELECT component, usage_json FROM mca_events "
                "WHERE usage_json IS NOT NULL LIMIT ?", (_USAGE_SCAN_LIMIT,))
        by_category: dict = {}
        have_cost = False
        for item in usage_rows or []:
            try:
                data = json.loads(item["usage_json"])
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            cost = data.get("cost_usd", data.get("cost"))
            if isinstance(cost, bool) or not isinstance(cost, (int, float)):
                continue
            category = str(item["component"] or "unknown")
            by_category[category] = round(
                by_category.get(category, 0.0) + float(cost), 6)
            have_cost = True
        if have_cost:
            groups["cost"] = _metric_group(True, by_category=by_category)

        groups["degradations"] = _metric_group(
            True, interrupted=int(interrupted), dropped=int(dropped),
            spooled=spooled_total(), gaps=gaps_total(),
            degraded=telemetry_degraded(),
            share=result["degraded_share"])

        # Живые источники, поставляемые вызывающим контуром (MCA-17a).
        if runtime.get("cache_entries") is not None:
            groups["cache"] = _metric_group(
                True, entries=int(runtime["cache_entries"]))
        if runtime.get("provenance_coverage") is not None:
            groups["provenance"] = _metric_group(
                True, coverage=float(runtime["provenance_coverage"]))
        if (runtime.get("histories") is not None
                or runtime.get("episodes") is not None):
            groups["memory"] = _metric_group(
                True, histories=runtime.get("histories"),
                episodes=runtime.get("episodes"))
        if runtime.get("downloads") is not None:
            downloads = runtime.get("downloads") or {}
            groups["downloads"] = _metric_group(
                True, count=downloads.get("count"),
                bytes=downloads.get("bytes"))
        if runtime.get("rss_mb") is not None:
            groups["runtime"] = _metric_group(
                True, rss_mb=float(runtime["rss_mb"]))

        result["unknown"] = [name for name, group in groups.items()
                             if not group.get("available")]
        return result
    except Exception:      # fail-open: витрина не рвёт поток
        return result
