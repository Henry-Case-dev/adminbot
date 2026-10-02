"""ASAP-3.2 (round1029, ADR-1028-5 D4/D5; T-4196…T-4200) — Media Adapter +
adaptive Media Execution Policy + durable media state.

§13: реальное состояние job/generation важнее arbitrary wall-clock timeout;
hard ceiling — ПОСЛЕДНИЙ рубеж, не первый механизм «модель умерла». Порядок:
provider async job/status → streaming/progress → sync alive + local
heartbeat → adaptive deadline по успешным наблюдениям → hard safety ceiling.

Состав:

1. **ImageProviderAdapter** (D4, §15–§18/§20–§21): provider-agnostic контракт
   `discover_models / discover_capabilities / submit_generation / submit_edit /
   supports_async_job / supports_status / supports_stream / supports_cancel /
   get_status / get_result / cancel`. Core pipeline НЕ привязан к NanoGPT
   route names; detection по host. Adapters: **NanoGPT** (OpenAI-compatible
   `POST /images/generations` — маршрут уже используется прод-кодом;
   async/status capability ТОЛЬКО из верифицированного capability-поля —
   «task_id route» НЕ изобретается, §16); **OpenRouter** (programmatic
   capability metadata из публичного каталога `/api/v1/models` — маршрут уже
   используется `model_capacity`; execution route НЕ выдумывается — честный
   `route_unverified`); **generic sync** (OpenAI-compatible POST
   `/images/generations`/GET-режим — безопасный fallback, §18).

2. **MediaExecutionPolicy** (D5, §22–§28): один resolver для ВСЕХ image ops;
   key `provider+model+operation` (generate ≠ edit ≠ preview); ЧЕТЫРЕ окна —
   connect / read-inactivity / poll-request / **total generation deadline**.
   При remote job/status — deadline = safety ceiling (получение RUNNING/
   progress обновляет liveness); sync-only (remote_progress = none, ответ
   приходит только в конце) — read-окно = total deadline (сокет молчит до
   готовности — это НЕ признак смерти; fake ping запрещён §14).
   Adaptive-оценщик строится ТОЛЬКО по успешным длительностям (§26: timeout →
   растущий deadline → новый timeout — запрещённая петля; timeout/failures —
   отдельные reliability signals). Формула: `clamp(max(cold_default,
   p95×safety), min_deadline, hard_ceiling)`. Cold defaults — developer-level
   env (90/180/240 — migration evidence, §27).

3. **Durable media state** (§29): долгие ops → durable job на REUSE
   `task_jobs` (v14, Δ SQLite DDL = 0; прецедент cover_style_jobs §42/§43);
   поля §29 — operation/provider/model/provider_job_id/status/submitted_at/
   last_progress_at/deadline_at/attempt/result_asset/failure_reason.

4. **Restart recovery** (§30): известен provider job ID → resume polling
   (НЕ повторный платный submit); sync-only без recovery → честный
   `unknown_after_disconnect`; автоматический платный retry без policy/
   idempotency — запрещён.

5. **Image fallback** (§31): ТОЛЬКО после terminal primary failure
   (честно RUNNING primary НЕ переключается); deadline пересчитывается под
   fallback; prompt recompile — cap по capabilities fallback-модели.

Observability (§35): `MEDIA_JOB_SUBMITTED/PROGRESS/HEARTBEAT/SUCCEEDED/
FAILED/DEADLINE_EXCEEDED/RECOVERED/FALLBACK` — REUSE `emit_mca_event`
(mca-13); safe fields: operation/provider/model/elapsed/remote status/
job-id hash/adaptive deadline/policy source. НЕ логируются keys/prompts/
image bytes.

Kill-switch `MEDIA_EXECUTION_POLICY_ENABLED` (env-only, default ON):
OFF → прежние окна 90/180/240 байт-в-байт (rollback §80).
"""
from __future__ import annotations

import collections
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger(__name__)

# ── §14: честная capability удалённого прогресса (fake ping запрещён) ───────
REMOTE_PROGRESS_JOB_STATUS = "job_status"
REMOTE_PROGRESS_STREAMING = "streaming"
REMOTE_PROGRESS_NONE = "none"

# ── §22/§23: операции (stage-aware key provider+model+operation) ────────────
OPERATION_GENERATE = "generate"
OPERATION_EDIT = "edit"
OPERATION_PREVIEW = "preview"

# Job-статусы durable-джобы (§29).
MJ_SUBMITTED = "submitted"
MJ_RUNNING = "running"
MJ_SUCCEEDED = "succeeded"
MJ_FAILED = "failed"
MJ_UNKNOWN = "unknown_after_disconnect"

_MEDIA_KIND = "media_job"
_MEDIA_OWNER = "image"

# SQLite DatabaseService binding (bot.on_startup); None → durable-слой
# fail-open пропускается (in-memory state), события/логи остаются.
_DB_REF = None


def bind_db(db) -> None:
    """Привязать SQLite DatabaseService для durable media jobs (§29)."""
    global _DB_REF
    _DB_REF = db


def bound_db():
    return _DB_REF


def media_policy_enabled() -> bool:
    try:
        return bool(getattr(settings, "MEDIA_EXECUTION_POLICY_ENABLED", True))
    except Exception:      # pragma: no cover
        return True


def _f(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(getattr(settings, name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


# ── Окна политики (§28: четыре различных окна) ──────────────────────────────

@dataclass(frozen=True)
class MediaWindows:
    """Результат резолва политики (§28)."""

    connect_timeout: float
    read_inactivity: float
    poll_request: float
    total_deadline: float
    source: str                     # cold_default | adaptive_p95 | legacy_static
    remote_progress: str            # job_status | streaming | none
    provider: str = ""
    model: str = ""
    operation: str = ""

    def as_dict(self) -> dict:
        return {
            "connect_timeout": self.connect_timeout,
            "read_inactivity": self.read_inactivity,
            "poll_request": self.poll_request,
            "total_deadline": self.total_deadline,
            "source": self.source,
            "remote_progress": self.remote_progress,
        }

    def httpx_timeout(self):
        """httpx.Timeout по окнам (connect/read/pool), либо float (legacy).

        Для sync-only (remote_progress=none) read = total_deadline: ответ
        приходит одним концом — молчание сокета НЕ признак смерти (§14/§28).
        Для job/streaming-провайдеров read — окно ОТДЕЛЬНОГО запроса/чанка;
        живость джобы обновляет liveness и НЕ ограничена этим окном."""
        if not media_policy_enabled():
            return None
        try:
            import httpx
        except Exception:      # pragma: no cover
            return None
        read = self.total_deadline if \
            self.remote_progress == REMOTE_PROGRESS_NONE \
            else self.read_inactivity
        return httpx.Timeout(connect=self.connect_timeout, read=read,
                             write=self.connect_timeout,
                             pool=self.connect_timeout)


def httpx_timeout_for(provider: str, model: str, operation: str,
                      *, remote_progress: str = REMOTE_PROGRESS_NONE):
    """Единая точка: окна политики → httpx.Timeout (None → legacy float)."""
    if not media_policy_enabled():
        return None
    return resolve_windows(provider, model, operation,
                           remote_progress=remote_progress).httpx_timeout()


# ── Estimator: ТОЛЬКО успешные длительности (§26) + reliability signals ─────

_MAX_SAMPLES = 32
_MAX_KEYS = 256
_OBS: dict[tuple[str, str, str], dict] = {}


def _obs_key(provider: str, model: str, operation: str) -> tuple:
    return (str(provider or "")[:80], str(model or "")[:80],
            str(operation or "")[:20])


def _evict_obs() -> None:
    while len(_OBS) > _MAX_KEYS:
        _OBS.pop(next(iter(_OBS)))


def record_media_outcome(provider: str, model: str, operation: str, *,
                         ok: bool, duration_s: float | None = None,
                         timeout: bool = False) -> None:
    """Наблюдение исхода: успешная длительность → estimator; timeout/failure —
    отдельные reliability signals (НЕ обучают deadline, §26)."""
    key = _obs_key(provider, model, operation)
    bucket = _OBS.get(key)
    if bucket is None:
        bucket = {"ok": collections.deque(maxlen=_MAX_SAMPLES),
                  "timeouts": 0, "failures": 0, "total": 0}
        _OBS[key] = bucket
        _evict_obs()
    bucket["total"] += 1
    if timeout:
        bucket["timeouts"] += 1
    if ok and duration_s is not None and duration_s > 0:
        bucket["ok"].append(float(duration_s))
    elif not ok and not timeout:
        bucket["failures"] += 1


def _percentile(values, q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return float(ordered[idx])


def media_policy_snapshot() -> dict:
    """Снимок наблюдений политики (§35/§36: p50/p95/счётчики; R17-safe)."""
    out: dict = {}
    for key, bucket in _OBS.items():
        ok = list(bucket["ok"])
        out["|".join(key)] = {
            "samples": len(ok),
            "p50_s": _percentile(ok, 0.50),
            "p95_s": _percentile(ok, 0.95),
            "max_s": max(ok) if ok else None,
            "timeouts": bucket["timeouts"],
            "failures": bucket["failures"],
        }
    return out


# ── Cold defaults (§27: developer-level; 90/180/240 — migration evidence) ───

def _cold_default(operation: str) -> tuple[float, str]:
    """Cold-start deadline. migration evidence: существующие env-окна веток
    остаются источником дефолта соответствующей операции (одна истина вместо
    трёх независимых: standalone 90→180-окно попытки, style 240)."""
    if operation == OPERATION_EDIT:
        return _f("MEDIA_COLD_DEADLINE_EDIT_SECONDS", 240.0, 30.0, 3600.0), \
            "cold_default"
    if operation == OPERATION_PREVIEW:
        return _f("MEDIA_COLD_DEADLINE_PREVIEW_SECONDS", 240.0, 30.0,
                  3600.0), "cold_default"
    # generate: legacy env-окно попытки (default 180 c, hotfix-5) как нижняя
    # граница cold-дефолта — env-переопределение остаётся рабочим.
    legacy = _f("IMAGE_ATTEMPT_TIMEOUT_SECONDS", 180.0, 1.0, 600.0)
    cold = _f("MEDIA_COLD_DEADLINE_GENERATE_SECONDS", 180.0, 1.0, 3600.0)
    return max(legacy, cold), "cold_default"


def resolve_windows(provider: str, model: str, operation: str, *,
                    remote_progress: str = REMOTE_PROGRESS_NONE
                    ) -> MediaWindows:
    """Единый adaptive resolver (§22–§28). Не бросает."""
    provider = str(provider or "")[:80]
    model = str(model or "")[:80]
    operation = str(operation or OPERATION_GENERATE)[:20]
    cold, source = _cold_default(operation)
    bucket = _OBS.get(_obs_key(provider, model, operation))
    if bucket is not None and len(bucket["ok"]) >= \
            max(1, int(_f("MEDIA_ADAPTIVE_MIN_SAMPLES", 5, 1, 100))):
        p95 = _percentile(list(bucket["ok"]), 0.95)
        safety = _f("MEDIA_ADAPTIVE_SAFETY_FACTOR", 1.5, 1.0, 10.0)
        if p95 is not None:
            total = max(cold, p95 * safety)
            source = "adaptive_p95"
        else:
            total = cold
    else:
        total = cold
    total = max(_f("MEDIA_MIN_DEADLINE_SECONDS", 60.0, 1.0, 600.0),
                min(total, _f("MEDIA_HARD_SAFETY_CEILING_SECONDS", 900.0,
                              30.0, 7200.0)))
    connect = _f("MEDIA_CONNECT_TIMEOUT_SECONDS", 15.0, 1.0, 120.0)
    inactivity = _f("MEDIA_INACTIVITY_TIMEOUT_SECONDS", 60.0, 5.0, 600.0)
    poll = _f("MEDIA_POLL_TIMEOUT_SECONDS", 30.0, 1.0, 300.0)
    return MediaWindows(connect_timeout=connect,
                        read_inactivity=inactivity, poll_request=poll,
                        total_deadline=total, source=source,
                        remote_progress=remote_progress,
                        provider=provider, model=model, operation=operation)


# ── ImageProviderAdapter (D4; §15–§18) ──────────────────────────────────────

@dataclass
class MediaSubmitResult:
    """Результат submit_generation/submit_edit (fail-open контракт)."""

    ok: bool
    content: bytes | None = None
    reason: str = "error"
    provider_job_id: str | None = None
    remote_progress: str = REMOTE_PROGRESS_NONE
    latency_ms: int = 0


class ImageProviderAdapter:
    """Provider-agnostic контракт (§15). Базовые реализации честные:
    async/status/stream/cancel НЕ поддерживаются, пока capability не
    подтверждена верифицированным источником (§16: route не изобретается)."""

    name = "generic"
    remote_progress = REMOTE_PROGRESS_NONE
    supports_async_job = False
    supports_status = False
    supports_stream = False
    supports_cancel = False

    def __init__(self, base_url: str) -> None:
        self.base_url = str(base_url or "").rstrip("/")

    # discovery ------------------------------------------------------------
    async def discover_models(self) -> list[dict] | None:
        return None                     # honest: нет верифицированного каталога

    async def discover_capabilities(self, model: str):
        """`ImageModelCapabilities` по capability-цепочке image_capabilities
        (§21: unknown остаётся честным unknown)."""
        try:
            from services import image_capabilities as cap
            return cap.resolve_capabilities(self.name, self.base_url,
                                            str(model or ""))
        except Exception:
            return None

    # execution ------------------------------------------------------------
    async def submit_generation(self, *, prompt: str, model: str,
                                timeout=None) -> MediaSubmitResult:
        started = time.monotonic()
        try:
            from services import image_generation as ig
            get_mode = bool(getattr(settings, "IMAGE_GET_MODE", False))
            key = ig._resolve_str(ig.KEY_API_KEY,
                                  getattr(settings, "IMAGE_API_KEY", "") or "")
            max_bytes = int(getattr(settings, "IMAGE_MAX_BYTES",
                                    9 * 1024 * 1024))
            effective_timeout = timeout
            if effective_timeout is None and media_policy_enabled():
                effective_timeout = resolve_windows(
                    self.name, model, OPERATION_GENERATE,
                    remote_progress=self.remote_progress).httpx_timeout()
            if get_mode:
                content = await ig._generate_get(
                    ig._host_from_base(self.base_url), model, prompt,
                    timeout if effective_timeout is None
                    else effective_timeout, max_bytes)
            else:
                content = await ig._generate_post(
                    self.base_url, model, prompt, key,
                    timeout if effective_timeout is None
                    else effective_timeout, max_bytes)
            return MediaSubmitResult(
                ok=True, content=content, reason="ok",
                remote_progress=self.remote_progress,
                latency_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:
            from services.image_generation import reason_from_exception
            return MediaSubmitResult(
                ok=False, reason=reason_from_exception(exc),
                remote_progress=self.remote_progress,
                latency_ms=int((time.monotonic() - started) * 1000))

    async def submit_edit(self, *, prompt: str, model: str,
                          image_paths: list, **kwargs) -> MediaSubmitResult:
        # Единая точка edit-исполнения — cover_style_edit (§3.2); adapter
        # маршрутизирует ТОЛЬКО capability-verified async (env-шаблоны —
        # migration evidence, НЕ целевой contract, D4).
        try:
            from services import cover_style_edit as cse
            result = await cse.edit_image(
                prompt, base_image_path=(image_paths[0] if image_paths
                                         else None),
                reference_paths=list(image_paths[1:]),
                base_url=self.base_url, model=model, **kwargs)
            return MediaSubmitResult(
                ok=bool(result.ok), content=result.content,
                reason=result.reason, provider_job_id=result.task_id,
                remote_progress=(REMOTE_PROGRESS_JOB_STATUS
                                 if result.async_used
                                 else self.remote_progress),
                latency_ms=result.latency_ms)
        except Exception as exc:
            return MediaSubmitResult(ok=False, reason=type(exc).__name__[:40])

    async def get_status(self, job_id: str):    # noqa: ARG002
        return None                        # честный unknown (нет контракта)

    async def get_result(self, job_id: str):    # noqa: ARG002
        return None

    async def cancel(self, job_id: str) -> bool:    # noqa: ARG002
        return False


class NanoGPTImageAdapter(ImageProviderAdapter):
    """NanoGPT (§16): OpenAI-compatible image endpoints — ЕДИНСТВЕННЫЕ
    маршруты, подтверждённые прод-кодом (`/api/v1/image-models?detailed=true`,
    `/api/v1/images/models/{model}/endpoints`, `POST /images/generations`).
    Async/status capability — ТОЛЬКО из верифицированного capability-источника;
    `task_id`-route по аналогии НЕ изобретается (§16/§91). До live-верификации
    — sync path с честным `remote_progress = none`."""

    name = "nanogpt"

    async def discover_models(self) -> list[dict] | None:
        try:
            import httpx
            root = self.base_url or "https://nano-gpt.com/api/v1"
            timeout = httpx.Timeout(connect=_f("MEDIA_CONNECT_TIMEOUT_SECONDS",
                                               15.0, 1.0, 60.0),
                                    read=30.0, write=15.0, pool=15.0)
            async with httpx.AsyncClient(timeout=timeout,
                                         follow_redirects=True) as client:
                resp = await client.get(
                    f"{str(root).rstrip('/')}/image-models",
                    params={"detailed": "true"})
                if resp.status_code != 200:
                    return None
                data = resp.json()
            items = data.get("data") if isinstance(data, dict) else None
            return items if isinstance(items, list) else None
        except Exception:
            return None

    async def discover_capabilities(self, model: str):
        """§21/Q4: discovery вызывается автоматически — каталог NanoGPT
        реально fetch'ится (TTL-кеш image_capabilities), без переданного
        готового dict."""
        try:
            from services import image_capabilities as cap
            models = await self.discover_models()
            entry = None
            for item in models or []:
                if isinstance(item, dict) and \
                        str(item.get("id") or "") == str(model or ""):
                    entry = item
                    break
            if entry is None:
                return cap.resolve_capabilities(self.name, self.base_url,
                                                str(model or ""))
            endpoints = await self._discover_endpoints(model)
            return cap.resolve_capabilities(
                self.name, self.base_url, str(model or ""),
                discovery=entry, endpoints=endpoints)
        except Exception:
            return None

    async def _discover_endpoints(self, model: str) -> dict | None:
        try:
            import httpx
            root = self.base_url or "https://nano-gpt.com/api/v1"
            timeout = httpx.Timeout(connect=15.0, read=30.0, write=15.0,
                                    pool=15.0)
            async with httpx.AsyncClient(timeout=timeout,
                                         follow_redirects=True) as client:
                resp = await client.get(
                    f"{str(root).rstrip('/')}/images/models/"
                    f"{str(model or '')}/endpoints")
                if resp.status_code != 200:
                    return None
                data = resp.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None


class OpenRouterImageAdapter(ImageProviderAdapter):
    """OpenRouter (§17): programmatic capability metadata из публичного
    каталога `/api/v1/models` (маршрут уже используется `model_capacity` —
    НЕ hardcode counts/resolutions по имени). Execution route НЕ выдумывается:
    до верификации — честный `route_unverified` (caller остаётся на
    generic-sync пути)."""

    name = "openrouter"

    async def discover_models(self) -> list[dict] | None:
        try:
            import httpx
            timeout = httpx.Timeout(connect=15.0, read=30.0, write=15.0,
                                    pool=15.0)
            async with httpx.AsyncClient(timeout=timeout,
                                         follow_redirects=True) as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models")
                if resp.status_code != 200:
                    return None
                data = resp.json()
            items = data.get("data") if isinstance(data, dict) else None
            return items if isinstance(items, list) else None
        except Exception:
            return None


_ADAPTERS: dict[str, type] = {}


def detect_adapter(base_url: str) -> ImageProviderAdapter:
    """Provider detection по host (§20 shared detection; без сети)."""
    host = ""
    try:
        from urllib.parse import urlsplit
        raw = str(base_url or "").strip()
        host = (urlsplit(raw if "://" in raw else "//" + raw).hostname
                or "").lower()
    except Exception:
        host = ""
    if "nano-gpt" in host:
        return NanoGPTImageAdapter(base_url)
    if "openrouter" in host:
        return OpenRouterImageAdapter(base_url)
    return ImageProviderAdapter(base_url)


# ── Durable media jobs (§29; REUSE task_jobs, ΔDDL = 0) ─────────────────────

@dataclass
class MediaJobState:
    """Снимок состояния media-джобы (§29; персистится в `task_jobs`)."""

    operation: str = OPERATION_GENERATE
    provider: str = ""
    model: str = ""
    base_url: str = ""
    provider_job_id: str | None = None
    status: str = MJ_SUBMITTED
    submitted_at: int = 0
    last_progress_at: int | None = None
    deadline_at: int | None = None
    attempt: int = 0
    result_asset: str | None = None
    failure_reason: str | None = None
    chat_id: int | None = None
    correlation_id: str | None = None
    stages: list = field(default_factory=list)

    def mark(self, status: str, *, provider_job_id: str | None = None,
             note: str | None = None) -> None:
        self.status = status
        self.last_progress_at = int(time.time())
        if provider_job_id is not None:
            self.provider_job_id = provider_job_id
        entry = {"status": status, "at": self.last_progress_at}
        if note:
            entry["note"] = str(note)[:80]
        self.stages.append(entry)
        if len(self.stages) > 32:
            del self.stages[:-32]

    def to_json(self) -> str:
        return json.dumps({
            "operation": self.operation, "provider": self.provider,
            "model": self.model, "base_url": self.base_url,
            "provider_job_id": self.provider_job_id,
            "status": self.status, "submitted_at": self.submitted_at,
            "last_progress_at": self.last_progress_at,
            "deadline_at": self.deadline_at, "attempt": self.attempt,
            "result_asset": self.result_asset,
            "failure_reason": self.failure_reason, "chat_id": self.chat_id,
            "correlation_id": self.correlation_id,
            "stages": self.stages[-32:]}, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw) -> "MediaJobState | None":
        if not raw:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        return cls(
            operation=str(data.get("operation") or OPERATION_GENERATE),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            base_url=str(data.get("base_url") or ""),
            provider_job_id=data.get("provider_job_id"),
            status=str(data.get("status") or MJ_SUBMITTED),
            submitted_at=int(data.get("submitted_at") or 0),
            last_progress_at=data.get("last_progress_at"),
            deadline_at=data.get("deadline_at"),
            attempt=int(data.get("attempt") or 0),
            result_asset=data.get("result_asset"),
            failure_reason=data.get("failure_reason"),
            chat_id=data.get("chat_id"),
            correlation_id=data.get("correlation_id"),
            stages=list(data.get("stages") or []))


def media_job_key(operation: str, provider: str, model: str,
                  prompt_hash: str) -> str:
    """Детерминированный job_id (restart находит ту же джобу, §42-прецедент)."""
    raw = "%s|%s|%s|%s" % (operation, provider, model, prompt_hash)
    return "med_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()[:16]


def _emit(event: str, outcome: str, *, level: str = "info", **fields):
    """Fail-open MEDIA_JOB_* события (§35; REUSE mca-13, R17-safe)."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(event, outcome=outcome, level=level,
                       component="media_execution", **fields)
    except Exception:
        pass


def _job_hash_id(job_id: str) -> str:
    return hashlib.sha256(str(job_id).encode("utf-8")).hexdigest()[:12]


async def begin_media_job(db, *, operation: str, provider: str, model: str,
                          prompt: str, chat_id: int | None = None,
                          correlation_id: str | None = None,
                          deadline_s: float | None = None,
                          job_id: str | None = None,
                          base_url: str = "",
                          ) -> tuple[str | None, MediaJobState]:
    """Создать/переиспользовать durable media-джобу (§29/§43-прецедент).

    Coalesce_key детерминирован по (operation, provider, model, prompt):
    параллельный/рестартовый повтор находит АКТИВНУЮ джобу (dedup v14) и
    продолжает её — новый платный submit не создаётся. `job_id` уникален
    на подачу (завершённые джобы не переиспользуются); после рестарта
    активная джоба находится сканом `recover_media_jobs`, а не ключом.
    db=None / ошибка → (None, in-memory state) — fail-open."""
    state = MediaJobState(
        operation=operation, provider=provider, model=model,
        base_url=str(base_url or ""), status=MJ_SUBMITTED,
        submitted_at=int(time.time()),
        deadline_at=(int(time.time()) + int(deadline_s)
                     if deadline_s else None),
        chat_id=chat_id, correlation_id=correlation_id)
    coalesce = "media_job:" + media_job_key(operation, provider, model,
                                            prompt_hash(prompt))
    jid = job_id or ("med_" + uuid.uuid4().hex)
    if db is None:
        return None, state
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        jid = await store.enqueue(
            owner=_MEDIA_OWNER, kind=_MEDIA_KIND, job_id=jid,
            coalesce_key=coalesce, payload=state.to_json(), max_attempts=1)
        checkpoint = await store.get_checkpoint(jid)
        restored = MediaJobState.from_json(
            (checkpoint or {}).get("cursor")) if checkpoint else None
        if restored is not None:
            state = restored
    except Exception:
        logger.warning("[media] durable job start failed — fail-open",
                       exc_info=True)
    _emit("MEDIA_JOB_SUBMITTED", "start", operation=operation,
          provider=provider[:60], model=model[:60],
          job_hash=_job_hash_id(jid) if jid else None,
          chat_id=chat_id, deadline_s=deadline_s)
    return jid, state


async def save_media_job(db, job_id: str | None, state: MediaJobState) -> bool:
    """Персистить снимок (checkpoint; рестарт возобновляет, §30)."""
    if db is None or not job_id:
        return False
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        ok = bool(await store.save_checkpoint(
            job_id, cursor_token=state.to_json(),
            processed=len(state.stages), checkpoint_ref=state.status))
        if ok:
            await store.heartbeat(job_id)
            _emit("MEDIA_JOB_HEARTBEAT", "progress",
                  operation=state.operation, provider=state.provider[:60],
                  model=state.model[:60], job_hash=_job_hash_id(job_id),
                  remote_status=state.status[:40])
        return ok
    except Exception:
        logger.warning("[media] durable job save failed — fail-open",
                       exc_info=True)
        return False


async def finish_media_job(db, job_id: str | None, state: MediaJobState, *,
                           outcome: str) -> bool:
    """Терминальный исход durable media-джобы (succeeded/failed/unknown)."""
    if db is None or not job_id:
        return False
    state.mark(outcome)
    if outcome == MJ_SUCCEEDED:
        _emit("MEDIA_JOB_SUCCEEDED", "success", operation=state.operation,
              provider=state.provider[:60], model=state.model[:60],
              job_hash=_job_hash_id(job_id), elapsed_ms=None,
              chat_id=state.chat_id)
    elif outcome == MJ_UNKNOWN:
        _emit("MEDIA_JOB_FAILED", "failed", level="warning",
              operation=state.operation, provider=state.provider[:60],
              model=state.model[:60], job_hash=_job_hash_id(job_id),
              reason_code=MJ_UNKNOWN, chat_id=state.chat_id)
    else:
        _emit("MEDIA_JOB_FAILED", "failed", level="warning",
              operation=state.operation, provider=state.provider[:60],
              model=state.model[:60], job_hash=_job_hash_id(job_id),
              reason_code=str(state.failure_reason or "failed")[:60],
              chat_id=state.chat_id)
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return bool(await store.finish(
            job_id,
            status="completed" if outcome == MJ_SUCCEEDED else "failed",
            reason_code=state.failure_reason or outcome,
            result_ref=state.to_json()))
    except Exception:
        logger.warning("[media] durable job finish failed — fail-open",
                       exc_info=True)
        return False


async def recover_media_jobs(db) -> dict:
    """Restart recovery (§30, T-4198): активные media-джобы после рестарта.

    * известен provider job ID (+ provider поддерживает status) → resume
      polling (событие `MEDIA_JOB_RECOVERED`); повторный платный submit НЕ
      выполняется;
    * sync-only без job ID → честный `unknown_after_disconnect` (джоба
      закрывается failed/unknown, автоматический платный retry запрещён).
    """
    summary = {"resumed": 0, "unknown_after_disconnect": 0, "active": 0}
    if db is None:
        return summary
    try:
        cursor = await db.db.execute(
            "SELECT job_id, payload FROM task_jobs WHERE kind = ? AND "
            "status IN ('queued', 'running') ORDER BY created_at",
            (_MEDIA_KIND,))
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return summary
    for row in rows:
        raw = row.get("payload")
        state = MediaJobState.from_json(raw)
        # Checkpoint-cursor — самый СВЕЖий снимок состояния (его пишет
        # `save_media_job`); приоритетен над identity-полями payload'а.
        # Прецедент cover_style; после L-EXTRA-6 (merge вместо overwrite,
        # asap-4 волна B) payload содержит И identity-поля, И cursor —
        # раньше здесь полагались на то, что checkpoint затирает payload.
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            cursor = (data or {}).get("cursor") \
                if isinstance(data, dict) else None
            state = MediaJobState.from_json(cursor) or state
        except (ValueError, TypeError):
            pass
        if state is None or (not state.provider and not state.model):
            continue
        summary["active"] += 1
        adapter = detect_adapter(state.base_url or state.provider)
        if state.provider_job_id and getattr(adapter, "supports_status",
                                             False):
            # resume polling: provider job сохранён; polling продолжит
            # владелец контекста/будущий worker — платный submit запрещён.
            summary["resumed"] += 1
            _emit("MEDIA_JOB_RECOVERED", "progress",
                  operation=state.operation, provider=state.provider[:60],
                  model=state.model[:60],
                  job_hash=_job_hash_id(row["job_id"]),
                  remote_status=str(state.status)[:40])
            logger.info("MEDIA_JOB_RECOVERED | operation=%s | model=%s | "
                        "resume by provider job id (no resubmit)",
                        state.operation, state.model[:60])
            continue
        # sync-only, оборван рестартом: честный unknown, БЕЗ платного retry.
        state.failure_reason = MJ_UNKNOWN
        state.mark(MJ_UNKNOWN, note="restart_no_recovery")
        summary["unknown_after_disconnect"] += 1
        await finish_media_job(db, str(row["job_id"]), state,
                               outcome=MJ_UNKNOWN)
        logger.warning("MEDIA_JOB_FAILED | operation=%s | model=%s | "
                       "reason=unknown_after_disconnect (sync-only, no "
                       "provider job id — no paid resubmit)",
                       state.operation, state.model[:60])
    return summary


# ── Image fallback (§31) ────────────────────────────────────────────────────

def fallback_target() -> tuple[str, str] | None:
    """(base_url, model) fallback-провайдера либо None (не настроен)."""
    try:
        base_url = str(getattr(settings, "IMAGE_FALLBACK_BASE_URL", "") or
                       "").strip()
        model = str(getattr(settings, "IMAGE_FALLBACK_MODEL", "") or "").strip()
        if base_url and model:
            return base_url, model
    except Exception:
        pass
    return None


async def maybe_media_fallback(prompt: str, *, chat_id: int | None,
                               primary_reason: str,
                               primary_running: bool = False,
                               operation: str = OPERATION_GENERATE,
                               correlation_id: str | None = None):
    """§31: terminal primary failure → fallback provider/model.

    НЕ переключается, пока primary честно RUNNING (`primary_running=True` →
    None). Deadline пересчитывается под fallback key; prompt recompile —
    cap по capabilities fallback-модели. Возвращает `GenerationResult` или
    None (fallback не настроен/не разрешён/не удался)."""
    if primary_running:
        return None
    target = fallback_target()
    if target is None:
        return None
    base_url, model = target
    adapter = detect_adapter(base_url)
    windows = resolve_windows(adapter.name, model, operation,
                              remote_progress=adapter.remote_progress)
    effective = windows.httpx_timeout() if media_policy_enabled() else None
    compiled = prompt
    try:
        caps = await adapter.discover_capabilities(model)
        limit = getattr(caps, "prompt_limit", None) if caps else None
        if limit is not None and getattr(limit, "known", False) and \
                limit.value and len(compiled) > int(limit.value):
            compiled = compiled[: int(limit.value)]   # recompile под caps §31
    except Exception:
        pass
    _emit("MEDIA_JOB_FALLBACK", "start", operation=operation,
          provider=adapter.name[:60], model=model[:60],
          reason_code=str(primary_reason)[:60],
          deadline_s=windows.total_deadline, chat_id=chat_id)
    logger.warning("MEDIA_JOB_FALLBACK | operation=%s | primary_reason=%s | "
                   "fallback=%s/%s | deadline=%.0fs", operation,
                   primary_reason, adapter.name, model[:60],
                   windows.total_deadline)
    result = await adapter.submit_generation(
        prompt=compiled, model=model,
        timeout=(effective if effective is not None
                 else windows.total_deadline))
    record_media_outcome(adapter.name, model, operation,
                         ok=bool(result.ok),
                         duration_s=(result.latency_ms / 1000.0
                                     if result.ok else None),
                         timeout=(result.reason == "timeout"))
    return result


__all__ = [
    "REMOTE_PROGRESS_JOB_STATUS", "REMOTE_PROGRESS_STREAMING",
    "REMOTE_PROGRESS_NONE", "OPERATION_GENERATE", "OPERATION_EDIT",
    "OPERATION_PREVIEW", "MJ_SUBMITTED", "MJ_RUNNING", "MJ_SUCCEEDED",
    "MJ_FAILED", "MJ_UNKNOWN",
    "MediaWindows", "MediaSubmitResult", "MediaJobState",
    "ImageProviderAdapter", "NanoGPTImageAdapter", "OpenRouterImageAdapter",
    "media_policy_enabled", "resolve_windows", "httpx_timeout_for",
    "record_media_outcome", "media_policy_snapshot", "detect_adapter",
    "begin_media_job", "save_media_job", "finish_media_job",
    "recover_media_jobs", "media_job_key", "prompt_hash",
    "fallback_target", "maybe_media_fallback",
]
