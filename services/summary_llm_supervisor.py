"""ASAP 4.1 волна 4 (T-4612–T-4615, spec §4 зона D; ADR-1028-8 D5) —
LLMExecutionSupervisor: единый orchestration-owner исполнения LLM-вызовов
Summary-пайплайна (L1/semantic map, Writer, Reviewer, Revision, Legacy).

**Scope = Summary ТОЛЬКО** (AM-3, ADR-1028-8 D5.1): Direct/STT/image/
embeddings/lore/dream — свои каскады ``LLM_TIMEOUT``/``LLM_FALLBACK_*`` как
сегодня; их per-call контракт ``llm_client._post`` не смещается (новые
kwarg'и ``timeout``/``budget_reason_label``/``supervised_transport`` —
default None → байт-в-бит).

**Что демонтирует (§23 ТЗ):** вложенные retry-циклы
``stage retry × llm_client retry × provider retry × fallback retry`` —
одна orchestration-политика:

  один логический вызов → РОВНО один attempt-бюджет:
    ≤4 HTTP суммарно (задокументировано, закреплено тестом):
      1 primary (1 HTTP)
      + ≤1 primary transport retry      (внутри _post, max_retries=1)
      + ≤1 fallback-provider            (_post_fallback)
      + ≤1 fallback transport retry     (Supervisor)
  Логические бюджеты стадий сохраняются (ADR-1028-7 D3.3): L1 ≤2
  (вкл. semantic correction retry), L2 ≤6 — transport-ретраи в них не
  входят (каждый логический вызов — отдельный supervised attempt-бюджет).

**Execution modes (§24/§26 ТЗ, честная база):** текущий транспорт
``llm_client`` — sync-opaque (POST → wait → final response) → **Mode C**
реализован сразу; Mode A (async job) / Mode B (streaming) — контрактные
слоты, активируемые ТОЛЬКО при верифицированном провайдер-адаптере
(прецедент ``EMBED_ASYNC_BATCH_ENABLED`` default OFF до live-верификации;
owner-гейт PO-4). Capability-декларации — только из реальных данных
транспорта; «пинговать генерацию» выдуманным endpoint запрещено.

**Watchdog (§25/§29 ТЗ):** unhealthy = нет подтверждённой активности /
provider stalled — НЕ «прошло N секунд» wall-clock как health-метрика
(AMEND ADR-1024-6: ``LLM_TIMEOUT``/``LLM_TOTAL_BUDGET`` перестают быть
health-критерием Summary-пути). Mode C честно не имеет сигнала
внутри-запросной активности → watchdog = adaptive attempt-дедлайн
(телеметрия успешных длительностей per provider/model/operation/token-
bucket; cold defaults per mode) + hard fuse ``SUMMARY_LLM_HARD_DEADLINE_
SECONDS`` (developer deep, clamp [600, 7200]) как последний рубеж. Mode B
(slot) — inactivity/stall detection по последнему token/event/keepalive.

Паттерн-доноры: ``media_execution.py`` (adaptive окна/percentile-оценщик
только по успешным длительностям/capability-декларации) + executor-
прецедент ``embedding_control_plane.py`` (единый attempt-бюджет).

R17: наружу только числа/коды/enum/provider host; ключи/тексты/промпты
не логируются. Никогда не бросает вне LLMError-семантики вызывающих
контрактов (те же классы исключений, что прежний канал).
"""
from __future__ import annotations

import asyncio
import collections
import logging
import time
import uuid
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Execution modes (§24 ТЗ) ────────────────────────────────────────────────

MODE_SYNC = "sync"                      # Mode C — честная база
MODE_ASYNC_JOB = "async_job"            # Mode A — контрактный слот
MODE_STREAM = "streaming"               # Mode B — контрактный слот

# Attempt-потолок на логический вызов (ADR-1028-8 D5.3, закреплено тестом):
# 1 primary + ≤1 primary transport retry + ≤1 fallback + ≤1 fallback retry.
ATTEMPT_CEILING_HTTP = 4
PRIMARY_MAX_HTTP = 2                    # _post с max_retries=1
FALLBACK_MAX_HTTP = 2                   # _post_fallback × (1 + 1 transport)
TRANSPORT_MAX_RETRIES = 1               # нижний слой — только transport
RETRY_STATUSES = ()                     # статус-ретраи решает Supervisor

# ── Capability-декларации (§26 ТЗ; честные, из реальных данных) ─────────────


@dataclass(frozen=True)
class ProviderCapabilities:
    """Честная декларацияexecution-возможностей провайдера.

    Базовая реализация — из РЕАЛЬНОГО наблюдаемого транспорта: текущий
    ``llm_client`` делает POST /chat/completions и ждёт финальный ответ
    (нет SSE-чтения, нет job/status API, нет cancel) → ``opaque_sync_only``
    = True. Поля включаются ТОЛЬКО верифицированным адаптером (сейчас
    верифицированных нет); «пинговать генерацию» выдуманным endpoint
    запрещено (23093–23108)."""

    supports_streaming_liveness: bool = False
    supports_async_status: bool = False
    supports_cancel: bool = False
    opaque_sync_only: bool = True
    source: str = "sync_transport_observed"

    def as_counts(self) -> dict:
        return {
            "streaming_liveness": self.supports_streaming_liveness,
            "async_status": self.supports_async_status,
            "cancel": self.supports_cancel,
            "opaque_sync_only": self.opaque_sync_only,
            "declaration_source": self.source,
        }


def declare_execution_capabilities(provider: str = "", model: str = ""
                                   ) -> ProviderCapabilities:
    """Capability discovery из реальных данных (не декларативно).

    Реестр верифицированных адаптеров пуст: синхронно-опаковый транспорт —
    единственный наблюдаемый факт → Mode C. Включение Mode A/B-флагов без
    верифицированного адаптера НЕ меняет режим (честные декларации)."""
    _ = provider, model       # пока декларация транспорт-уровня
    streaming = False
    async_status = False
    try:
        # Слоты Mode A/B активируются ТОЛЬКО вместе с верифицированным
        # адаптером; реестр адаптеров пока пуст → флаги не дают режима
        # (честное отражение фактического состояния транспорта).
        streaming = False
        async_status = False
    except Exception:      # pragma: no cover - защитная ветка
        pass
    return ProviderCapabilities(
        supports_streaming_liveness=streaming,
        supports_async_status=async_status,
        supports_cancel=False,
        opaque_sync_only=not (streaming or async_status),
        source="sync_transport_observed")


def select_execution_mode(caps: ProviderCapabilities) -> str:
    """Режим Supervisor'а СЛЕДУЕТ декларации (T-4613): async job → Mode A;
    streaming → Mode B; иначе honest Mode C. Слоты требуют и флага, и
    верифицированной декларации. Читает ТЕ ЖЕ настройки, что и весь модуль
    (import-time binding — reload `config.settings` тест-хелперами не
    рассинхронизирует класс)."""
    if caps.supports_async_status and bool(
            getattr(settings, "SUMMARY_LLM_ASYNC_MODE_ENABLED", False)):
        return MODE_ASYNC_JOB
    if caps.supports_streaming_liveness and bool(
            getattr(settings, "SUMMARY_LLM_STREAMING_MODE_ENABLED", False)):
        return MODE_STREAM
    return MODE_SYNC


# ── Adaptive watchdog: клампы/cold defaults (spec D.4; media _f-паттерн) ────

HARD_DEADLINE_CLAMP = (600.0, 7200.0)
INACTIVITY_CLAMP = (60.0, 900.0)


def _f(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(getattr(settings, name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


def hard_deadline_seconds() -> float:
    """Hard fuse — developer deep env-only (clamp [600, 7200]); последний
    рубеж, НЕ health-метрика (AMEND ADR-1024-6)."""
    return _f("SUMMARY_LLM_HARD_DEADLINE_SECONDS", 3600.0,
              *HARD_DEADLINE_CLAMP)


def inactivity_threshold_seconds() -> float:
    """Порог неактивности watchdog'а (clamp [60, 900]); adaptive-оценщик
    поверх телеметрии поднимает attempt-дедлайн выше floor'а."""
    return _f("SUMMARY_LLM_INACTIVITY_SECONDS", 300.0, *INACTIVITY_CLAMP)


def _cold_defaults(mode: str) -> tuple[float, float]:
    """Cold defaults (ttfa, generation) per execution mode (spec D.4:
    ``SUMMARY_LLM_*_COLD_DEFAULTS``). Sync — реализованный режим; async/
    stream — контрактные слоты (читают свои ключи при активации)."""
    m = str(mode or MODE_SYNC)
    ttfa = _f(f"SUMMARY_LLM_COLD_TTFA_{m.upper()}_SECONDS", 120.0, 30.0,
              3600.0)
    gen = _f(f"SUMMARY_LLM_COLD_GENERATION_{m.upper()}_SECONDS", 900.0,
             60.0, 3600.0)
    return ttfa, gen


# ── Telemetry (§29 ТЗ; process-local; оценка ТОЛЬКО по успешным) ────────────

_MAX_SAMPLES = 32
_MAX_KEYS = 256
_OBS: dict[tuple, dict] = {}
_RECENT_STATES: collections.deque = collections.deque(maxlen=64)


def _token_bucket(tokens: int | None) -> str:
    """Input-token bucket (§29): размер входа влияет на expected duration."""
    try:
        n = max(0, int(tokens or 0))
    except (TypeError, ValueError):
        n = 0
    if n < 8192:
        return "tok_s"
    if n < 32768:
        return "tok_m"
    if n < 131072:
        return "tok_l"
    if n < 524288:
        return "tok_xl"
    return "tok_max"


def _obs_key(provider: str, model: str, operation: str, bucket: str) -> tuple:
    return (str(provider or "")[:80], str(model or "")[:80],
            str(operation or "")[:16], str(bucket or "")[:8])


def _evict_obs() -> None:
    while len(_OBS) > _MAX_KEYS:
        _OBS.pop(next(iter(_OBS)))


def record_outcome(provider: str, model: str, operation: str, *,
                   token_bucket: str, ok: bool, duration_s: float | None,
                   ttfa_s: float | None = None, timeout: bool = False,
                   queue_s: float | None = None) -> None:
    """Наблюдение исхода логического вызова: успешная длительность →
    adaptive-оценщик; timeout/failure — отдельные reliability signals
    (НЕ обучают дедлайн — правило §26 media_execution)."""
    key = _obs_key(provider, model, operation, token_bucket)
    bucket = _OBS.get(key)
    if bucket is None:
        bucket = {"ok": collections.deque(maxlen=_MAX_SAMPLES),
                  "ttfa": collections.deque(maxlen=_MAX_SAMPLES),
                  "queue": collections.deque(maxlen=_MAX_SAMPLES),
                  "timeouts": 0, "failures": 0, "total": 0}
        _OBS[key] = bucket
        _evict_obs()
    bucket["total"] += 1
    if timeout:
        bucket["timeouts"] += 1
    if ok and duration_s is not None and duration_s > 0:
        bucket["ok"].append(float(duration_s))
        if ttfa_s is not None and ttfa_s > 0:
            bucket["ttfa"].append(float(ttfa_s))
        if queue_s is not None and queue_s >= 0:
            bucket["queue"].append(float(queue_s))
    elif not ok and not timeout:
        bucket["failures"] += 1


def _percentile(values, q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return float(ordered[idx])


def resolve_attempt_deadline(provider: str, model: str, operation: str, *,
                             token_bucket: str, mode: str = MODE_SYNC
                             ) -> tuple[float, str]:
    """Adaptive attempt-дедлайн watchdog'а (spec D.4; REUSE паттерна
    ``media_execution.resolve_windows``). Никогда не бросает.

    * нет достаточных наблюдений → cold default generation per mode;
    * есть → p95 успешных длительностей × safety, но НЕ ниже floor'ов
      (cold default / порог неактивности);
    * потолок — hard fuse (последний рубеж)."""
    _ttfa, cold_gen = _cold_defaults(mode)
    inactivity = inactivity_threshold_seconds()
    source = "cold_default"
    estimate = cold_gen
    key = _obs_key(provider, model, operation, token_bucket)
    bucket = _OBS.get(key)
    min_samples = max(1, int(_f("SUMMARY_LLM_ADAPTIVE_MIN_SAMPLES", 3, 1, 100)))
    if bucket is not None and len(bucket["ok"]) >= min_samples:
        p95 = _percentile(list(bucket["ok"]), 0.95)
        safety = _f("SUMMARY_LLM_ADAPTIVE_SAFETY_FACTOR", 1.5, 1.0, 10.0)
        if p95 is not None:
            estimate = max(estimate, p95 * safety)
            source = "adaptive_p95"
    deadline = max(cold_gen, estimate, inactivity)
    deadline = min(deadline, hard_deadline_seconds())
    return deadline, source


def telemetry_snapshot() -> dict:
    """R17-safe снапшот телеметрии (p50/p95/счётчики; для Inspector зоны G)."""
    out: dict = {}
    for key, bucket in _OBS.items():
        ok = list(bucket["ok"])
        out["|".join(key)] = {
            "samples": len(ok),
            "p50_s": _percentile(ok, 0.50),
            "p95_s": _percentile(ok, 0.95),
            "max_s": max(ok) if ok else None,
            "ttfa_p50_s": _percentile(list(bucket["ttfa"]), 0.50),
            "queue_p50_s": _percentile(list(bucket["queue"]), 0.50),
            "timeouts": bucket["timeouts"],
            "failures": bucket["failures"],
        }
    return out


def reset_telemetry() -> None:
    """Тест-хелпер: очистка process-local наблюдений."""
    _OBS.clear()
    _RECENT_STATES.clear()


# ── Attempt state (§23 ТЗ: владение supervisor'ом) ──────────────────────────

STATE_WAITING = "waiting"
STATE_RUNNING = "running"
STATE_FALLBACK = "fallback"
STATE_OK = "ok"
STATE_FAILED = "failed"
STATE_STALLED = "stalled"


@dataclass
class SupervisedCallState:
    """Единый владелец исполнения (§23 ТЗ, 22993–23020)."""

    request_id: str
    provider: str
    model: str
    operation: str
    mode: str
    started_at: float                    # monotonic
    state: str = STATE_WAITING
    attempt: int = 0                     # логические попытки (primary/fallback)
    fallback: bool = False
    http_attempts: int = 0               # верхняя граница supervised-ноги (≤2)
    last_activity_at: float = field(default_factory=time.monotonic)
    attempt_started_at: float = field(default_factory=time.monotonic)
    token_bucket: str = "tok_s"
    deadline: float = 0.0
    deadline_source: str = "cold_default"
    stalled: bool = False
    queue_ms: float | None = None
    ttfa_ms: float | None = None
    duration_ms: float | None = None
    reason: str | None = None

    def snapshot(self) -> dict:
        """R17-safe срез (Inspector зоны G читает structured state)."""
        now = time.monotonic()
        return {
            "request_id": self.request_id,
            "operation": self.operation,
            "mode": self.mode,
            "state": self.state,
            "attempt": self.attempt,
            "fallback": self.fallback,
            "http_attempts": self.http_attempts,
            "provider": self.provider,
            "model": self.model,
            "token_bucket": self.token_bucket,
            "deadline_source": self.deadline_source,
            "stalled": self.stalled,
            "age_s": round(max(0.0, now - self.started_at), 3),
            "reason": self.reason,
        }


# ── Наблюдаемость (аддитивные события; R17-safe; fail-open) ────────────────


def _emit_activity(state: SupervisedCallState, run_id, *, chat_id,
                   outcome: str, level: str, counts: dict,
                   reason_code: str | None = None, status: str | None = None
                   ) -> None:
    try:
        from services import pipeline_events
        pipeline_events.llm_activity(
            run_id, chat_id=chat_id, operation=state.operation,
            outcome=outcome, level=level, counts=counts,
            attempt=state.attempt, provider=state.provider,
            model=state.model, status=status or state.state,
            reason_code=reason_code, duration_ms=state.duration_ms)
    except Exception:      # pragma: no cover - эмиссия не рвёт пайплайн
        pass


# ── Watchdog-правила (T-4613: first-activity / stall / generation) ──────────

def evaluate_watchdog(state: SupervisedCallState, *, now: float,
                      mode: str, attempt_deadline: float,
                      inactivity: float) -> str | None:
    """Чистое решение watchdog'а → None (жив) | 'stalled' | 'deadline'.

    * streaming (Mode B):真正的 inactivity/stall — нет token/event/keepalive
      дольше порога; elapsed НЕ убивает живой поток;
    * sync (Mode C — честная база): внутри-запросная активность ненаблюдаема
      → liveness-эквивалент = attempt-дедлайн (adaptive/cold);
    * fuse-уровень жёстче (hard deadline) — отдельная ветка (не здесь)."""
    if mode == MODE_STREAM:
        if (now - state.last_activity_at) > inactivity:
            return "stalled"
        return None
    # Sync (Mode C): liveness-эквивалент — attempt-дедлайн ОТ СТАРТА ТЕКУЩЕЙ
    # попытки (не логического вызова — fallback-нога получает своё окно).
    if (now - state.attempt_started_at) >= attempt_deadline:
        return "stalled" if state.state == STATE_RUNNING else "deadline"
    return None


# ── Контракт transport-конtracts для supervised попыток ─────────────────────


def transport_contract(deadline: float) -> dict:
    """Per-call контракт для supervised попытки (ADR-1028-8 D5.2):
    нижний слой — ТОЛЬКО transport (max_retries=1, retry_statuses=())."""
    return {
        "budget": float(deadline),
        "max_retries": TRANSPORT_MAX_RETRIES,
        "retry_statuses": RETRY_STATUSES,
        "timeout": float(deadline),
        "budget_reason_label": "summary_supervised",
    }


def _payload_tokens(messages) -> int:
    """Оценка required_input по ФАКТИЧЕСКОМУ serialized payload (не «только
    message.text»: считаются все message-контенты системных/пользовательских
    ролей — тот же estimator, что у стадий)."""
    try:
        from services.token_counter import count_tokens
        total = 0
        for m in messages or ():
            total += count_tokens(str((m or {}).get("content") or ""))
        return total
    except Exception:      # pragma: no cover - оценщик не рвёт вызов
        return 0


def _http_status_of(exc: BaseException) -> int | None:
    try:
        from services.summary_run_log import http_status_of
        return http_status_of(exc)
    except Exception:
        return None


# ── Ядро: исполнение логического вызова под supervisor'ом ───────────────────


def supervisor_enabled() -> bool:
    """Kill-switch зоны D (env-only, default ON; OFF → прежний контур
    llm_client байт-в-бит — каскады/тайминги/старые reason-коды 2.58.46)."""
    try:
        return bool(getattr(settings, "SUMMARY_LLM_SUPERVISOR_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


async def _parse_completion(response, *, label: str) -> tuple[str, dict]:
    """Парсинг ответа — тот же контракт, что ``generate``/``_dedicated_generate``
    (LLMBadResponseError на кривой форме)."""
    try:
        data = response.json()
    except ValueError as exc:
        raise _bad_response(f"{label}: invalid JSON response") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise _bad_response(f"{label}: no choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise _bad_response(f"{label}: empty content")
    usage = data.get("usage") if isinstance(data, dict) else None
    return content, (usage if isinstance(usage, dict) else None)


def _bad_response(message: str):
    from services.llm_client import LLMBadResponseError
    return LLMBadResponseError(message)


async def _primary_attempt(llm, state: SupervisedCallState, *, messages,
                           payload, slot, chat_id, module, step,
                           correlation_id, deadline: float):
    """Primary-нога: РОВНО одна supervised-попытка (≤2 HTTP transport).

    * dedicated слот → ``_post`` per-call с транспорт-контрактом;
    * глобальный слот → ``generate`` с supervised_transport (per-call
      контракт + ВЫКЛЮЧЕННЫЙ внутренний fallback-каскад; analytics/
      global-usage — паритет прежнего канала)."""
    state.state = STATE_RUNNING
    state.last_activity_at = time.monotonic()
    state.attempt_started_at = state.last_activity_at
    if state.queue_ms is None:
        state.queue_ms = (state.last_activity_at - state.started_at) * 1000.0
    contract = transport_contract(deadline)
    if slot is not None and bool(getattr(slot, "dedicated", False)):
        response = await llm._post(  # noqa: SLF001 - документированный мост S3
            "/chat/completions", payload, api_key=slot.api_key,
            base_url=slot.base_url,
            budget=contract["budget"], max_retries=contract["max_retries"],
            retry_statuses=contract["retry_statuses"],
            timeout=contract["timeout"],
            budget_reason_label=contract["budget_reason_label"])
        # http_attempts — верхняя граница supervised-ноги (≤2: 1 primary +
        # ≤1 transport-retry); точный подсчёт HTTP делает transport-тест.
        state.http_attempts += PRIMARY_MAX_HTTP
        state.last_activity_at = time.monotonic()
        content, usage = await _parse_completion(
            response, label=f"summary {state.operation}")
        return content, usage, str(slot.model or "")
    # Глобальный слот: генерируем через generate (key/analytics-паритет),
    # но с supervised transport-контрактом.
    content = await llm.generate(
        messages, module=module, step=step, correlation_id=correlation_id,
        supervised_transport=contract)
    # http_attempts — верхняя граница supervised-ноги (≤2); точный подсчёт
    # HTTP делает transport-тест (real attempt-count внутри _post).
    state.http_attempts += PRIMARY_MAX_HTTP
    state.last_activity_at = time.monotonic()
    return content, None, str(getattr(llm, "_chat_model", "") or "")


async def _fallback_attempt(llm, state: SupervisedCallState, *, payload,
                            primary_exc, deadline: float):
    """Fallback-нога Supervisor'а (§27–§28): resolve fallback capacity →
    compare required input → вмещает → тот же whole-window task (≤2 HTTP:
    1 fallback + ≤1 transport-retry); не вмещает → НЕ отправлять oversized
    (честный отказ + capacity-событие)."""
    from services import model_capacity as mc
    fb_base = str(getattr(llm, "_fallback_base_url", "") or "")
    fb_model = str(getattr(llm, "_fallback_model", "") or "")
    required = _payload_tokens(payload.get("messages") or [])
    reserve = _reserve_for_operation(state.operation)
    state.state = STATE_FALLBACK
    state.fallback = True
    state.attempt += 1
    state.last_activity_at = time.monotonic()
    state.attempt_started_at = state.last_activity_at
    try:
        plan = await mc.replan_summary_capacity(
            base_url=fb_base, model=fb_model, required_input_tokens=required,
            reserved_output_tokens=reserve,
            current_mode=mc.MODE_WHOLE_WINDOW)
    except Exception:      # pragma: no cover - re-plan fail-open
        plan = None
    if plan is not None and plan.mode == mc.MODE_CAPACITY_OVERFLOW:
        # §27: перед fallback нельзя автоматически отправлять тот же payload,
        # если тот не вмещается. Честный отказ БЕЗ oversized-отправки
        # (покрытие окна сохраняется вызывающим fail-soft контуром).
        try:
            from services import pipeline_events
            run_id = state.request_id.split(":", 1)[0]
            pipeline_events.capacity_resolved(
                run_id, chat_id=None, provider=fb_base or None,
                model=fb_model or None,
                counts={**plan.as_event_counts(),
                        "reason": "fallback_capacity_smaller",
                        "supervised": True})
        except Exception:      # pragma: no cover
            pass
        logger.warning(
            "SUMMARY supervisor: fallback capacity smaller — no oversized "
            "send | op=%s | required=%d | effective=%d | reason=%s",
            state.operation, required, plan.effective_context_window,
            plan.reason)
        state.reason = "fallback_capacity_smaller"
        raise primary_exc from None
    # Отправка: одна попытка + один transport-retry (никогда больше).
    # Не-2xx статусы — НЕ транспорт (ретраятся только transport-ошибки,
    # как и в первичной ноге: retry_statuses=()); классификация — та же.
    from services.llm_client import (
        LLMError,
        LLMRateLimitError,
        LLMServerError,
        LLMAuthError,
    )
    last_exc: BaseException | None = None
    for http_i in range(FALLBACK_MAX_HTTP):
        try:
            response = await llm._post_fallback(payload, timeout=deadline)
            state.http_attempts += 1
            state.last_activity_at = time.monotonic()
            status = getattr(response, "status_code", None)
            if isinstance(status, int) and status >= 400:
                if status == 429:
                    raise LLMRateLimitError(
                        f"summary fallback rate limited (429)")
                if 500 <= status < 600:
                    raise LLMServerError(
                        f"summary fallback server error {status}")
                if status in (401, 403):
                    raise LLMAuthError(f"summary fallback auth ({status})")
                raise LLMError(f"summary fallback HTTP {status}")
            content, usage = await _parse_completion(
                response, label="summary fallback")
            return content, usage, fb_model or None
        except LLMError:
            raise            # статус-класс — без transport-ретрая
        except (asyncio.TimeoutError,) as exc:
            last_exc = exc
            state.last_activity_at = time.monotonic()
            if http_i + 1 < FALLBACK_MAX_HTTP:
                continue
            break
        except Exception as exc:  # noqa: BLE001 - transport-retry leg
            last_exc = exc
            state.http_attempts += 1
            state.last_activity_at = time.monotonic()
            transport_retryable = isinstance(exc, _transport_error_classes())
            if transport_retryable and http_i + 1 < FALLBACK_MAX_HTTP:
                continue
            break
    state.reason = state.reason or "fallback_failed"
    if isinstance(last_exc, asyncio.TimeoutError):
        from services.llm_client import LLMTimeoutError
        raise LLMTimeoutError(
            f"summary fallback attempt timed out: op={state.operation}"
        ) from last_exc
    if isinstance(last_exc, Exception):
        raise last_exc
    raise primary_exc from None


def _transport_error_classes() -> tuple:
    try:
        import httpx
        return (httpx.TransportError,)
    except Exception:      # pragma: no cover
        return (Exception,)


async def _run_with_watchdog(attempt_coro, state: SupervisedCallState, *,
                             mode: str, attempt_deadline: float,
                             inactivity: float):
    """Исполнить попытку под живым watchdog-поллером (T-4613/T-4614).

    Поллер РЕАЛЬНО работает во время запроса: evaluate_watchdog →
    * stalled — нет подтверждённой активности (streaming-слот: нет
      token/event/keepalive дольше порога; sync: attempt-дедлайн, честный
      эквивалент неактивности для opaque-транспорта) → cancel попытки →
      LLMTimeoutError(provider_stalled) → finite fallback (§45);
    * отмена supervisor'а извне (hard fuse) НЕ маскируется — проброс."""
    task = asyncio.ensure_future(attempt_coro)
    interval = max(1.0, min(5.0, attempt_deadline / 10.0))

    async def _watch() -> None:
        while not task.done():
            await asyncio.sleep(interval)
            verdict = evaluate_watchdog(
                state, now=time.monotonic(), mode=mode,
                attempt_deadline=attempt_deadline, inactivity=inactivity)
            if verdict:
                state.stalled = True
                state.reason = state.reason or (
                    "provider_stalled" if verdict == "stalled"
                    else "execution_deadline_exceeded")
                task.cancel()
                return

    watch = asyncio.ensure_future(_watch())
    try:
        return await task
    except asyncio.CancelledError:
        if state.stalled:
            from services.llm_client import LLMTimeoutError
            raise LLMTimeoutError(
                f"summary supervised: no confirmed activity (stall) "
                f"op={state.operation} mode={state.mode}") from None
        raise      # внешняя отмена (hard fuse/loop) — не маскируем
    finally:
        watch.cancel()


def _reserve_for_operation(operation: str) -> int:
    try:
        from services.summary_hybrid_budget import hybrid_output_reserve_tokens
        return hybrid_output_reserve_tokens(
            kind="l1" if operation == "l1" else "l2", settings_obj=settings)
    except Exception:      # pragma: no cover - защитная ветка
        return 4000


async def execute_supervised(llm, *, messages, operation: str,
                             correlation_id=None, chat_id=None,
                             module: str | None = None, step: str | None = None,
                             slot=None) -> tuple[str, dict | None]:
    """Исполнить ОДИН логический LLM-вызов Summary-пайплайна под
    supervisor'ом (attempt-потолок ≤4 HTTP; watchdog; fallback-решение
    с capacity re-plan; R17-safe события).

    Контракт результата — тот же, что у прежних каналов: ``(content,
    usage|None)``; классы исключений — те же (LLMError-семантика вызывающих
    fail-soft веток не смещается)."""
    if llm is None:
        raise _bad_response("summary supervisor: no llm client")
    started = time.perf_counter()
    caps = declare_execution_capabilities()
    mode = select_execution_mode(caps)
    model = (str(getattr(slot, "model", "") or "") if slot is not None
             and bool(getattr(slot, "dedicated", False))
             else str(getattr(llm, "_chat_model", "") or ""))
    provider = (str(getattr(slot, "base_url", "") or "") if slot is not None
                and bool(getattr(slot, "dedicated", False))
                else str(getattr(llm, "_base_url", "") or ""))
    try:
        provider_host = _provider_host(provider)
    except Exception:
        provider_host = provider
    state = SupervisedCallState(
        request_id=f"{str(correlation_id or 'run')[:48]}:{operation}:"
                   f"{uuid.uuid4().hex[:8]}",
        provider=provider_host, model=model, operation=operation, mode=mode,
        started_at=time.monotonic())
    state.token_bucket = _token_bucket(_payload_tokens(messages))
    deadline, deadline_source = resolve_attempt_deadline(
        provider_host, model, operation, token_bucket=state.token_bucket,
        mode=mode)
    state.deadline = deadline
    state.deadline_source = deadline_source
    payload = {"model": (slot.model if slot is not None
                         and bool(getattr(slot, "dedicated", False))
                         else getattr(llm, "_chat_model", "")),
               "messages": messages}
    _RECENT_STATES.append(state)
    _emit_activity(state, correlation_id, chat_id=chat_id, outcome="start",
                   level="INFO", counts={"mode": mode, "op": operation,
                                         "bucket": state.token_bucket,
                                         "deadline_source": deadline_source,
                                         "deadline_s": round(deadline, 1),
                                         **caps.as_counts()})
    fuse = hard_deadline_seconds()
    inactivity = inactivity_threshold_seconds()
    primary_exc: BaseException | None = None
    duration = 0.0
    try:
        async with asyncio.timeout(fuse):
            try:
                state.attempt = 1
                content, usage, used_model = await _run_with_watchdog(
                    _primary_attempt(
                        llm, state, messages=messages, payload=payload,
                        slot=slot, chat_id=chat_id, module=module, step=step,
                        correlation_id=correlation_id, deadline=deadline),
                    state, mode=mode, attempt_deadline=deadline,
                    inactivity=inactivity)
                duration = (time.perf_counter() - started)
                state.state = STATE_OK
                state.reason = None
                _record_ok(state, provider=state.provider, model=used_model,
                           duration_s=duration, chat_id=chat_id)
                return content, usage
            except _no_api_key_class():
                # Паритет generate: без ключа — немедленно, без fallback.
                state.state = STATE_FAILED
                state.reason = "provider_unconfigured"
                raise
            except _bad_response_class() as exc:
                # Паритет прежнего канала: BadResponse (пустой/кривой ответ)
                # НЕ уходит в provider-fallback (generate/_dedicated).
                state.state = STATE_FAILED
                state.reason = "bad_response"
                _record_fail(state, provider=state.provider, model=model,
                             duration_s=time.perf_counter() - started,
                             timeout=False, chat_id=chat_id)
                raise
            except LLMErrorBase() as exc:
                primary_exc = exc
            except _transport_error_class() as exc:
                # Необработанный транспорт (вне LLMError) — классифицируем.
                from services.llm_client import LLMTransportError
                primary_exc = LLMTransportError(
                    f"summary supervisor: transport error: {exc}")
    except asyncio.TimeoutError:
        # Hard fuse — последний рубеж (§25): execution_deadline_exceeded.
        state.state = STATE_STALLED
        state.stalled = True
        state.reason = "execution_deadline_exceeded"
        duration = time.perf_counter() - started
        _record_fail(state, provider=state.provider, model=model,
                     duration_s=duration, timeout=True, chat_id=chat_id)
        _emit_activity(state, correlation_id, chat_id=chat_id,
                       outcome="failed", level="WARN",
                       reason_code="execution_deadline_exceeded",
                       counts={"fuse": True,
                               "http_attempts": state.http_attempts})
        from services.llm_client import LLMTimeoutError
        raise LLMTimeoutError(
            f"summary supervised: hard deadline fuse exceeded "
            f"({fuse:.0f}s) op={operation}") from None
    if primary_exc is None:      # pragma: no cover - defensive
        from services.llm_client import LLMError
        primary_exc = LLMError("summary supervisor: primary failed")
    # Runtime 400/context-length → инвалидация capacity-кеша + переоценка
    # в рамках run (T-4605/T-4612; единая orchestration-политика).
    _status = _http_status_of(primary_exc)
    if _status in (400, 404, 413):
        try:
            from services import model_capacity as _mc
            base_for_cap = (str(getattr(slot, "base_url", "") or "")
                            if slot is not None
                            and bool(getattr(slot, "dedicated", False))
                            else str(getattr(llm, "_base_url", "") or ""))
            invalidated = _mc.invalidate_runtime_capacity(
                base_for_cap, model, reason="runtime_context_error")
            try:
                from services import pipeline_events
                pipeline_events.capacity_resolved(
                    str(correlation_id or "run"), chat_id=chat_id,
                    provider=_provider_host(base_for_cap) or None,
                    model=model or None,
                    counts={"reason": "capacity_cache_invalidated",
                            "http_status": _status,
                            "invalidated": int(invalidated or 0),
                            "supervised": True})
            except Exception:      # pragma: no cover
                pass
            logger.info(
                "SUMMARY supervisor: capacity invalidated (runtime %d) | "
                "op=%s | model=%s", _status, operation, model)
        except Exception:      # pragma: no cover - fail-open
            pass
    # ── Fallback-решение Supervisor'а (§27) ────────────────────────────────
    state.reason = state.reason or _reason_of(primary_exc)
    _record_fail(state, provider=state.provider, model=model,
                 duration_s=time.perf_counter() - started,
                 timeout=_is_timeout_exc(primary_exc), chat_id=chat_id)
    _emit_activity(state, correlation_id, chat_id=chat_id, outcome="failed",
                   level="WARN", reason_code=state.reason,
                   counts={"http_attempts": state.http_attempts,
                           "phase": "primary"})
    active = bool(getattr(llm, "_fallback_active", False))
    has_fallback = hasattr(llm, "_post_fallback")
    if not active or not has_fallback:
        state.state = STATE_FAILED
        # Попытки исчерпаны (fallback недоступен/выключен) — честная
        # финальная причина §30 (ADR-1028-8 D5.6).
        _emit_activity(state, correlation_id, chat_id=chat_id,
                       outcome="failed", level="WARN",
                       reason_code="retry_time_budget_exhausted",
                       counts={"http_attempts": state.http_attempts,
                               "fallback": False,
                               "attempts_exhausted": True,
                               "primary_reason": state.reason})
        raise primary_exc
    try:
        async with asyncio.timeout(max(1.0, fuse - (time.perf_counter()
                                                    - started))):
            content, usage, used_model = await _run_with_watchdog(
                _fallback_attempt(llm, state, payload=payload,
                                  primary_exc=primary_exc,
                                  deadline=min(deadline,
                                               hard_deadline_seconds())),
                state, mode=mode, attempt_deadline=max(
                    1.0, min(deadline, fuse - (time.perf_counter()
                                               - started))),
                inactivity=inactivity)
        duration = time.perf_counter() - started
        state.state = STATE_OK
        state.reason = None
        _record_ok(state, provider=str(getattr(llm, "_fallback_base_url", "")
                                       or ""), model=used_model or "",
                   duration_s=duration, chat_id=chat_id,
                   extra_counts={"fallback": True})
        return content, usage
    except _bad_response_class() as exc:
        state.state = STATE_FAILED
        state.reason = "bad_response"
        _emit_activity(state, correlation_id, chat_id=chat_id,
                       outcome="failed", level="WARN", reason_code=state.reason,
                       counts={"http_attempts": state.http_attempts,
                               "fallback": True})
        raise
    except asyncio.TimeoutError:
        state.state = STATE_STALLED
        state.stalled = True
        state.reason = "execution_deadline_exceeded"
        _record_fail(state, provider=state.provider, model=model,
                     duration_s=time.perf_counter() - started, timeout=True,
                     chat_id=chat_id)
        _emit_activity(state, correlation_id, chat_id=chat_id,
                       outcome="failed", level="WARN",
                       reason_code="execution_deadline_exceeded",
                       counts={"http_attempts": state.http_attempts,
                               "fallback": True})
        from services.llm_client import LLMTimeoutError
        raise LLMTimeoutError(
            f"summary supervised: hard deadline fuse exceeded (fallback) "
            f"op={operation}") from None
    except LLMErrorBase() as exc:
        state.state = STATE_FAILED
        state.reason = state.reason or _reason_of(exc)
        # Попытки исчерпаны (primary + fallback failed; fuse не тронут) —
        # честная финальная причина §30 (ADR-1028-8 D5.6).
        _emit_activity(state, correlation_id, chat_id=chat_id,
                       outcome="failed", level="WARN",
                       reason_code="retry_time_budget_exhausted",
                       counts={"http_attempts": state.http_attempts,
                               "fallback": True,
                               "attempts_exhausted": True,
                               "primary_reason": state.reason})
        raise
    except _transport_error_class() as exc:
        from services.llm_client import LLMTransportError
        state.state = STATE_FAILED
        state.reason = "provider_unavailable"
        # Попытки исчерпаны (fallback transport-нога без ответа).
        _emit_activity(state, correlation_id, chat_id=chat_id,
                       outcome="failed", level="WARN",
                       reason_code="retry_time_budget_exhausted",
                       counts={"http_attempts": state.http_attempts,
                               "fallback": True,
                               "attempts_exhausted": True})
        raise LLMTransportError(
            f"summary supervised: fallback transport error: {exc}") from exc
    finally:
        state.duration_ms = (time.perf_counter() - started) * 1000.0


def _bad_response_class():
    from services.llm_client import LLMBadResponseError
    return LLMBadResponseError


def _no_api_key_class():
    from services.llm_client import NoApiKeyForChat
    return NoApiKeyForChat


def _transport_error_class():
    try:
        import httpx
        return (httpx.TransportError,)
    except Exception:      # pragma: no cover
        return (Exception,)


def LLMErrorBase():
    from services.llm_client import LLMError
    return LLMError


def _is_timeout_exc(exc: BaseException) -> bool:
    try:
        from services.llm_client import LLMTimeoutError
        return isinstance(exc, LLMTimeoutError)
    except Exception:      # pragma: no cover
        return False


def _reason_of(exc: BaseException) -> str:
    """R17-safe причина (маппинг в REASON_CODES — pipeline_events.map_reason)."""
    if _is_timeout_exc(exc):
        return "timeout"
    name = type(exc).__name__
    return {
        "LLMRateLimitError": "rate_limit",
        "LLMServerError": "provider_unavailable",
        "LLMAuthError": "auth_failed",
    }.get(name, "provider_unavailable")


def _record_ok(state: SupervisedCallState, *, provider, model, duration_s,
               chat_id, extra_counts: dict | None = None) -> None:
    # Mode C: первый подтверждённый признак активности = финальный ответ —
    # ttfa честно равен полной длительности (выдуманных пингов нет).
    state.ttfa_ms = duration_s * 1000.0
    state.duration_ms = duration_s * 1000.0
    record_outcome(provider, model, state.operation,
                   token_bucket=state.token_bucket, ok=True,
                   duration_s=duration_s, ttfa_s=duration_s,
                   queue_s=(state.queue_ms / 1000.0
                            if state.queue_ms is not None else None))
    _emit_activity(state, state.request_id.split(":", 1)[0],
                   chat_id=chat_id, outcome="success", level="INFO",
                   counts={"http_attempts": state.http_attempts,
                           "ttfa_ms": round(state.ttfa_ms),
                           "duration_ms": round(state.duration_ms),
                           "deadline_source": state.deadline_source,
                           **(extra_counts or {})})


def _record_fail(state: SupervisedCallState, *, provider, model, duration_s,
                 timeout: bool, chat_id) -> None:
    state.duration_ms = duration_s * 1000.0
    record_outcome(provider, model, state.operation,
                   token_bucket=state.token_bucket, ok=False,
                   duration_s=None, timeout=timeout,
                   queue_s=(state.queue_ms / 1000.0
                            if state.queue_ms is not None else None))


def _provider_host(base_url: str) -> str:
    try:
        from urllib.parse import urlsplit
        return urlsplit(str(base_url or "")).hostname or ""
    except Exception:      # pragma: no cover
        return ""


def recent_states() -> list[dict]:
    """Последние supervised-состояния (R17-safe; Inspector зоны G)."""
    return [state.snapshot() for state in _RECENT_STATES]


def make_wrapped(llm, slot, correlation_id, *, operation: str,
                 module: str | None = None, step: str | None = None):
    """Вернуть supervised-callable с контрактом ``call(messages) -> str |
    (str, usage)`` — либо None (supervisor OFF → прежний канал байт-в-бит).

    Точка интеграции — существующие ``_make_llm_call`` (кластеризатор/
    writer/reviewer/revision) и ``_llm_generate``/narrator генератора."""
    if not supervisor_enabled():
        return None

    async def _call(messages):
        return await execute_supervised(
            llm, messages=list(messages or []), operation=operation,
            correlation_id=correlation_id,
            chat_id=None,
            module=module, step=step,
            slot=slot)

    return _call


__all__ = [
    "MODE_SYNC", "MODE_ASYNC_JOB", "MODE_STREAM",
    "ATTEMPT_CEILING_HTTP", "PRIMARY_MAX_HTTP", "FALLBACK_MAX_HTTP",
    "TRANSPORT_MAX_RETRIES", "RETRY_STATUSES",
    "ProviderCapabilities", "declare_execution_capabilities",
    "select_execution_mode", "supervisor_enabled",
    "hard_deadline_seconds", "inactivity_threshold_seconds",
    "resolve_attempt_deadline", "record_outcome", "telemetry_snapshot",
    "reset_telemetry", "evaluate_watchdog", "transport_contract",
    "execute_supervised", "make_wrapped", "recent_states",
    "SupervisedCallState", "STATE_STALLED",
]
