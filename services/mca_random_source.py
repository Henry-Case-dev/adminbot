"""mca-10a (`mca-10a-random-source-anu`, ADR-1028-14 D1–D5, spec §2–§7) —
единственный контур поведенческой случайности: RandomSource (quantum |
pseudorandom), ANU-клиент, политика exploration, durable-запас/refill,
журнал draw, квота, честная активация и fallback.

Границы (вторые механизмы запрещены):
  * один сервис: `RandomSourceService` (async) + `ExplorationPolicy`
    (чистая логика + инъекция источника) + `CoreDreamRandomSource`
    (sync-адаптер стыка mca-06) + `AnuClient` (async) + `RandomStore`
    (v27-таблицы через `write_transaction`/DatabaseService);
  * события — только единый `emit_mca_event` (`mca_events`, компонент
    `random`, notable-only); second словарь/канал не создаётся;
  * запись — только общий write-механизм mca-01 (`write_transaction`);
  * фоновая задача refill — существующий `TaskSupervisor`/`task_jobs`
    (`owner="random.source"`, `coalesce_key="random.refill:<account>"`).

Инварианты (spec/ADR):
  * selected (настройка `memory.random_source`) ≠ effective (резолвится на
    каждом draw); режим переживает рестарты (bot_settings);
  * `fallback_to_pseudorandom` — пользовательская настройка, НЕ kill-switch;
  * rejection sampling `limit=(range//n)*n`, без modulo bias; n=1 — draw не
    расходуется; каждый draw — отдельное значение;
  * PRNG — stdlib `random.Random` (auto-seed; `randrange`/`random()`),
    реализация/версия фиксируются для диагностики; НЕ для ключей/токенов/
    security; своя криптография не пишется;
  * «выбор ≠ вердикт»: случайность выбирает материал/альтернативу, не
    истинность/права/уместность; недопустимые измерения не рандомизируются;
  * ANU-ключ никогда не попадает в логи/URL/события/таблицы (в v27 — только
    `key_fingerprint = sha256(key)[:12]`, сервер-only);
  * OFF-паритет: K1 OFF → ровно `mca_dream_random.default_source`; K2 OFF →
    ANU-запросов нет; K3 OFF → refill не запускается; K4 OFF → политика
    возвращает primary без probability-draw; каждый OFF = поведение 2.58.57
    для своего пути.

Kill-switches/env-лимиты (D11): `MCA_RANDOM_SOURCE_ENABLED`,
`MCA_RANDOM_QUANTUM_ENABLED`, `MCA_RANDOM_REFILL_ENABLED`,
`MCA_RANDOM_EXPLORATION_ENABLED` (default ON) + env-only
`MCA_RANDOM_CIRCUIT_FAILS`/`..._COOLDOWN_SECONDS`/`..._MIN_REQUEST_INTERVAL_
SECONDS`/`..._DRAW_RETENTION_DAYS`/`..._DRAW_MAX_ROWS`/`..._ANU_TRIAL_
MONTHLY_LIMIT`/`..._ANU_TRIAL_RPS`/`..._QUANTUM_HEX_BLOCK_SIZE` — резолв
per-call через `services.mca_gates` (никогда не бросает).
"""
from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import logging
import platform
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from config.settings import APP_VERSION, settings
from services import mca_dream_random, mca_events, mca_gates

logger = logging.getLogger(__name__)

# ── режимы/источники ────────────────────────────────────────────────────────
MODE_QUANTUM = "quantum"
MODE_PSEUDORANDOM = "pseudorandom"
MODES = (MODE_QUANTUM, MODE_PSEUDORANDOM)

SOURCE_IMPL_PRNG = "python-random-mt19937"
PROVIDER_ANU = "ANU Quantum Numbers"
PROVIDER_PRNG = "python-random"

# Purpose (закрытый набор 10a; расширение имён — санкция 10b).
PURPOSE_LESS_STUDIED = mca_dream_random.PURPOSE_LESS_STUDIED
PURPOSE_ACTIVATION_SELFCHECK = "activation_selfcheck"
PURPOSE_SLEEP_CONSOLIDATION = "sleep_after_consolidation"
# mca-10b (ADR-1028-17 D2/AM-1, санкция spec §13): санкционированное
# расширение закрытого набора ровно на 5 purpose. НОВЫХ probability-ключей
# нет — карта связывает purpose с существующими двумя гейтами (разговор /
# после сна); `ui_replay`/`ui_visualization` — НЕ purposes (read-only
# маркер/настройка; `choose()` отвергает неизвестный purpose).
PURPOSE_CONVERSATION_VARIANT = "conversation_variant"
PURPOSE_MEMORY_RECALL = "memory_recall"
PURPOSE_ARCHIVE_SAMPLE = "archive_sample"
PURPOSE_BELIEF_REVIEW = "belief_review"
PURPOSE_ASSOCIATION_PAIR = "association_pair"

# purpose → ключ вероятности (одна карта в одном месте; D6).
EXPLORATION_PROBABILITY_KEYS = {
    PURPOSE_LESS_STUDIED: "memory.random_exploration_probability",
    PURPOSE_SLEEP_CONSOLIDATION: "memory.random_sleep_exploration_probability",
    PURPOSE_CONVERSATION_VARIANT: "memory.random_exploration_probability",
    PURPOSE_MEMORY_RECALL: "memory.random_exploration_probability",
    PURPOSE_ARCHIVE_SAMPLE: "memory.random_sleep_exploration_probability",
    PURPOSE_BELIEF_REVIEW: "memory.random_sleep_exploration_probability",
    PURPOSE_ASSOCIATION_PAIR: "memory.random_sleep_exploration_probability",
}
EXPLORATION_PURPOSES = frozenset(EXPLORATION_PROBABILITY_KEYS)
INTERNAL_PURPOSES = frozenset({PURPOSE_ACTIVATION_SELFCHECK})

# Недопустимые измерения (D6/T-4967): не рандомизируются никогда. Координатор
# формирует только допустимые альтернативы; политика дополнительно отвергает
# явно объявленное недопустимое измерение с причиной `no_eligible_alternative`.
INELIGIBLE_MEASUREMENTS = frozenset({
    "truth", "identity", "source_assignment", "rights", "deletion",
    "direct_request", "financial_settings",
})

POLICY_VERSION = "mca10a-v1"
CANDIDATES_CAP = 50
SELECTION_META_CAP = 200
MAX_DRAW_ATTEMPTS = 32
JOURNAL_QUEUE_MAX = 256
DREAM_CHUNK_MIN = 8
DREAM_CHUNK_MAX = 64

# Настройки (pg_key; блок C добавляет каталог; рантайм читает через
# существующий read-path и fail-open на дефолт).
SETTING_SOURCE = "memory.random_source"
SETTING_FALLBACK = "memory.random_fallback_to_pseudorandom"
SETTING_EXPLORATION = "memory.random_exploration_probability"
SETTING_SLEEP_EXPLORATION = "memory.random_sleep_exploration_probability"
SETTING_KEY = "keys.random_quantum_api_key"
SETTING_ENDPOINT = "keys.random_quantum_endpoint"
SETTING_PLAN = "keys.random_quantum_plan"
SETTING_BATCH_LENGTH = "keys.random_quantum_batch_length"
SETTING_DATA_TYPE = "keys.random_quantum_data_type"
SETTING_TIMEOUT = "keys.random_quantum_request_timeout_seconds"
SETTING_LOW_WATERMARK = "keys.random_quantum_refill_low_watermark"
SETTING_BUFFER_MAX = "keys.random_quantum_buffer_max_values"

DEFAULT_SOURCE = MODE_QUANTUM
DEFAULT_FALLBACK = True
DEFAULT_EXPLORATION_PROBABILITY = 0.05
DEFAULT_BATCH_LENGTH = 1024
DEFAULT_DATA_TYPE = "uint16"
DEFAULT_TIMEOUT_SECONDS = 5
DEFAULT_LOW_WATERMARK = 256
DEFAULT_BUFFER_MAX = 2048
DEFAULT_PLAN = "Trial"
PLANS = ("Trial", "Paid", "Custom")

# ANU-контракт §14.3 (endpoint/header/defaults предзаполнены; owner вводит
# только ключ).
ANU_HOST = "api.quantumnumbers.anu.edu.au"
ANU_ENDPOINT = f"https://{ANU_HOST}"
ANU_HEADER = "x-api-key"
DATA_TYPES = frozenset({"uint8", "uint16", "hex8", "hex16"})
HEX_TYPES = frozenset({"hex8", "hex16"})
UINT_RANGES = {"uint8": 256, "uint16": 65536}
MIN_LENGTH = 1
MAX_LENGTH = 1024
MIN_HEX_SIZE = 1
MAX_HEX_SIZE = 10

# ANU-состояния (D9-контракт для витрины; выводится из mca_random_state).
ANU_STATE_DISABLED = "disabled"
ANU_STATE_UNCONFIGURED = "provider_unconfigured"
ANU_STATE_UNVERIFIED = "unverified"
ANU_STATE_ACTIVE = "active"
ANU_STATE_DEGRADED = "degraded"
ANU_STATE_QUOTA = "quota_exhausted"
_DEGRADED_REASONS = frozenset({
    "provider_unavailable", "auth_failed", "timeout", "validation_failed",
    "delivery_unknown", "rate_limit", "redirect_blocked", "client_error",
})


def _utc_period(now: float | None = None) -> str:
    """Период квоты `YYYY-MM` (UTC; account-global, не per-chat)."""
    ts = float(now if now is not None else time.time())
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")


def key_fingerprint(key: str) -> str:
    """Сервер-only детектор смены ключа: `sha256(key)[:12]` (НЕ ключ)."""
    try:
        return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:12]
    except Exception:      # pragma: no cover - защитная ветка
        return ""


def map_value_to_index(value: int, n: int, value_range: int) -> int | None:
    """Rejection sampling `limit=(range//n)*n` (без modulo bias).

    `None` — значение отвергнуто (или диапазон меньше n — честный отказ,
    без тихой подмены). `n == 1` → 0 (вызывающий не расходует draw)."""
    try:
        n = int(n)
        value = int(value)
        value_range = int(value_range)
    except (TypeError, ValueError):
        return None
    if n <= 0 or value_range <= 0:
        return None
    if n == 1:
        return 0
    limit = (value_range // n) * n
    if limit <= 0 or value < 0 or value >= value_range:
        return None
    if value >= limit:
        return None
    return value % n


def batch_value_range(data_type: str, values) -> int:
    """Диапазон значений партии для rejection sampling.

    uint8/uint16 — точный power-of-two диапазон. hex8/hex16 — консервативный
    power-of-two по максимальному значению партии (≤ фактического диапазона;
    для uniform-партии из 1024 значений совпадает с точным с вероятностью
    1 − 2^-1024; меньший диапазон статистически безопасен — только больше
    отказов, без bias)."""
    if data_type in UINT_RANGES:
        return UINT_RANGES[data_type]
    try:
        top = max(int(v) for v in values)
    except Exception:
        return 0
    return 1 << max(1, top.bit_length())


def _candidate_id(candidate) -> str:
    """ID кандидата для журнала (R17-safe: только идентификаторы)."""
    if isinstance(candidate, dict):
        raw = candidate.get("id")
    else:
        raw = getattr(candidate, "id", None)
    if raw is None:
        raw = candidate if isinstance(candidate, (str, int)) else None
    return str(raw)[:120] if raw is not None else ""


def _same_candidate(a, b) -> bool:
    """Сравнение «тот же основной» для пула без основного (identity/ID)."""
    if a is b:
        return True
    try:
        if a == b:
            return True
    except Exception:
        pass
    ca, cb = _candidate_id(a), _candidate_id(b)
    return bool(ca) and ca == cb


# ── ошибки/партии ANU ───────────────────────────────────────────────────────
class AnuError(Exception):
    """Ошибка ANU-контура: код (reason_code), очищенная причина, sent.

    `sent=True` ⇔ запрос реально ушёл на сервер (квота могла быть израсходована;
    таймаут после отправки учитывается как `unknown`, не success/failed).
    `reason` — R17-safe (ключ замаскирован), в логи/события не попадает сырым."""

    def __init__(self, code: str, reason: str = "", *, retryable: bool = False,
                 sent: bool = False, retry_after: int | None = None) -> None:
        self.code = str(code)
        self.reason = str(reason)[:160]
        self.retryable = bool(retryable)
        self.sent = bool(sent)
        self.retry_after = retry_after
        super().__init__(f"code={self.code} | reason={self.reason}")


@dataclass
class AnuBatch:
    """Валидная партия реальных чисел ANU (после schema/тип/диапазон/длина)."""

    values: list
    data_type: str
    length: int
    provider: str = PROVIDER_ANU
    latency_ms: int | None = None


@dataclass
class _HttpResponse:
    status: int
    headers: dict
    text: str


def validate_endpoint(url: str) -> str:
    """Origin-guard ANU (не SSRF): только https + точный host + без
    userinfo/порта/пути/query. Иное → `scheme_not_allowed`/`invalid_url`
    (коды mca-02), запрос не выполняется, ключ не отправляется."""
    raw = str(url or "").strip()
    if not raw:
        raise AnuError("invalid_url", "empty endpoint", sent=False)
    try:
        parts = urlsplit(raw)
    except Exception:
        raise AnuError("invalid_url", "unparsable endpoint", sent=False)
    if parts.scheme.lower() != "https":
        raise AnuError("scheme_not_allowed",
                       f"scheme={parts.scheme or 'none'}", sent=False)
    if parts.username or parts.password:
        raise AnuError("invalid_url", "userinfo not allowed", sent=False)
    host = (parts.hostname or "").lower()
    if host != ANU_HOST:
        raise AnuError("invalid_url", f"host not allowed: {host}", sent=False)
    try:
        port = parts.port
    except ValueError:
        raise AnuError("invalid_url", "bad port", sent=False)
    if port not in (None, 443):
        raise AnuError("invalid_url", "port not allowed", sent=False)
    if (parts.path or "") not in ("", "/"):
        raise AnuError("invalid_url", "path not allowed", sent=False)
    if parts.query or parts.fragment:
        raise AnuError("invalid_url", "query/fragment not allowed", sent=False)
    return ANU_ENDPOINT


def _parse_retry_after(headers) -> int | None:
    raw = None
    try:
        for k, v in (headers or {}).items():
            if str(k).lower() == "retry-after":
                raw = v
                break
    except Exception:
        raw = None
    if raw is None:
        return None
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return max(0, min(seconds, 3600))


def _clean_error_text(raw, key: str = "") -> str:
    """Очистить error-поле провайдера: маска ключа + sanitize + bound."""
    text = str(raw or "").replace("\n", " ").replace("\r", " ").strip()
    if key and key in text:
        text = text.replace(key, "***")
    try:
        from services.log_ring import sanitize
        text = sanitize(text)
    except Exception:
        pass
    return text[:160] or "provider error"


async def _default_http_get(url: str, headers: dict, params: dict,
                            timeout: float) -> _HttpResponse:
    """Дефолтный GET через httpx: TLS-верификация по умолчанию,
    `follow_redirects=False` (ключ не уходит по redirect)."""
    import httpx
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        resp = await client.get(url, headers=headers, params=params)
        return _HttpResponse(
            status=int(resp.status_code),
            headers={str(k).lower(): v for k, v in resp.headers.items()},
            text=resp.text)


class AnuClient:
    """Клиент ANU (доверенный провайдер; SafeFetcher не дублируется).

    Контракт §14.3: GET `https://api.quantumnumbers.anu.edu.au`, header
    `x-api-key`, query `length` 1–1024, `type` uint8/uint16/hex8/hex16,
    `size` только для hex (1–10). Валидация HTTPS/TLS/JSON/schema/success/
    типа/диапазона/длины. Таймаут; backoff с учётом Retry-After; circuit
    breaker (3 fails → open на 60 c → half-open один probe); 401/403 →
    `auth_failed` без цикла; 429 → `quota_exhausted` без запроса на каждое
    сообщение (min interval). In-memory (рестарт допустим; последняя причина
    durable в `mca_random_state`). Ключ не логируется и не попадает в URL."""

    def __init__(self, *, http_get: Callable | None = None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 min_interval: float = 1.0, circuit_fails: int = 3,
                 circuit_cooldown: float = 60.0, clock: Callable | None = None
                 ) -> None:
        self._http_get = http_get or _default_http_get
        self._timeout = float(timeout)
        self._min_interval = float(min_interval)
        self._circuit_fails = max(1, int(circuit_fails))
        self._cooldown = float(circuit_cooldown)
        self._clock = clock or time.monotonic
        self._fails = 0
        self._open_until = 0.0
        self._probe_used = False
        self._last_request_at: float | None = None
        self._next_allowed_at = 0.0

    # ── конфигурация (hot-значения читает сервис per-call) ─────────────────
    def configure(self, *, timeout: float, min_interval: float,
                  circuit_fails: int, circuit_cooldown: float) -> None:
        self._timeout = float(timeout)
        self._min_interval = max(0.0, float(min_interval))
        self._circuit_fails = max(1, int(circuit_fails))
        self._cooldown = max(1.0, float(circuit_cooldown))

    def status(self) -> dict:
        return {
            "fails": int(self._fails),
            "circuit_open_until": float(self._open_until),
            "next_allowed_at": float(self._next_allowed_at),
            "last_request_at": self._last_request_at,
        }

    def available(self) -> bool:
        now = self._clock()
        return now >= self._open_until and now >= self._next_allowed_at

    # ── breaker/backoff ────────────────────────────────────────────────────
    def _note_failure(self, now: float, retry_after: int | None) -> None:
        self._fails += 1
        backoff = min(self._cooldown, float(2 ** min(self._fails, 6)))
        if retry_after:
            backoff = max(backoff, float(retry_after))
        self._next_allowed_at = now + backoff
        if self._fails >= self._circuit_fails:
            self._open_until = now + self._cooldown
            self._probe_used = False

    def _note_success(self) -> None:
        self._fails = 0
        self._open_until = 0.0
        self._probe_used = False
        self._next_allowed_at = 0.0

    # ── fetch ──────────────────────────────────────────────────────────────
    async def fetch(self, *, key: str, length: int = DEFAULT_BATCH_LENGTH,
                    data_type: str = DEFAULT_DATA_TYPE,
                    endpoint: str = ANU_ENDPOINT,
                    size: int | None = None) -> AnuBatch:
        if not key:
            raise AnuError("provider_unconfigured", "no api key", sent=False)
        try:
            length = int(length)
        except (TypeError, ValueError):
            raise AnuError("validation_failed", "bad length", sent=False)
        if not (MIN_LENGTH <= length <= MAX_LENGTH):
            raise AnuError("validation_failed",
                           f"length out of range: {length}", sent=False)
        data_type = str(data_type or "")
        if data_type not in DATA_TYPES:
            raise AnuError("validation_failed",
                           f"unknown data type: {data_type[:20]}", sent=False)
        if data_type in HEX_TYPES:
            try:
                size = int(size if size is not None else 1)
            except (TypeError, ValueError):
                raise AnuError("validation_failed", "bad size", sent=False)
            if not (MIN_HEX_SIZE <= size <= MAX_HEX_SIZE):
                raise AnuError("validation_failed",
                               f"size out of range: {size}", sent=False)
        else:
            if size is not None:
                raise AnuError("validation_failed",
                               "size only for hex types", sent=False)
            size = None
        url = validate_endpoint(endpoint)   # origin-guard ДО любого запроса
        now = self._clock()
        if now < self._open_until:
            raise AnuError("provider_unavailable", "circuit_open",
                           retryable=True, sent=False)
        if now < self._next_allowed_at:
            raise AnuError("rate_limit", "backoff", retryable=True, sent=False)
        if (self._last_request_at is not None
                and now - self._last_request_at < self._min_interval):
            raise AnuError("rate_limit", "min_interval", retryable=True,
                           sent=False)
        if self._open_until and not self._probe_used:
            self._probe_used = True      # half-open: ровно один probe
        params: dict[str, Any] = {"length": length, "type": data_type}
        if size is not None:
            params["size"] = size
        headers = {ANU_HEADER: str(key)}     # ключ только в заголовке
        self._last_request_at = now
        try:
            resp = await self._http_get(url, headers, params, self._timeout)
        except asyncio.TimeoutError:
            self._note_failure(now, None)
            raise AnuError("timeout", "request timeout", retryable=True,
                           sent=True)
        except Exception as exc:  # транспорт; ключ в текст не попадает
            name = type(exc).__name__
            is_timeout = "Timeout" in name
            # ConnectTimeout/PoolTimeout — запрос не ушёл (не тратим квоту);
            # Read/WriteTimeout — ушёл (честный unknown через timeout).
            sent = is_timeout and "Connect" not in name and "Pool" not in name
            self._note_failure(now, None)
            raise AnuError("timeout" if is_timeout else "provider_unavailable",
                           f"transport error: {name}",
                           retryable=True, sent=sent)
        status = int(getattr(resp, "status", 0) or 0)
        resp_headers = getattr(resp, "headers", {}) or {}
        text = str(getattr(resp, "text", "") or "")
        if 300 <= status < 400:
            self._note_failure(now, None)
            raise AnuError("redirect_blocked", f"http {status}",
                           sent=True)
        if status in (401, 403):
            self._note_failure(now, None)
            raise AnuError("auth_failed", f"http {status}", sent=True)
        if status == 429:
            retry_after = _parse_retry_after(resp_headers)
            self._note_failure(now, retry_after)
            raise AnuError("quota_exhausted", "http 429", retryable=True,
                           sent=True, retry_after=retry_after)
        if status != 200:
            self._note_failure(now, None)
            code = "provider_unavailable" if status >= 500 else "client_error"
            raise AnuError(code, f"http {status}", retryable=(status >= 500),
                           sent=True)
        try:
            payload = json.loads(text)
        except Exception:
            self._note_failure(now, None)
            raise AnuError("validation_failed", "invalid json", sent=True)
        values = self._validate_payload(payload, length=length,
                                        data_type=data_type, size=size,
                                        key=key)
        self._note_success()
        return AnuBatch(values=values, data_type=data_type, length=length)

    def _validate_payload(self, payload, *, length: int, data_type: str,
                          size: int | None, key: str) -> list:
        def _bad(reason: str):
            self._note_failure(self._clock(), None)
            return AnuError("validation_failed", reason, sent=True)

        if not isinstance(payload, dict):
            raise _bad("schema: not an object")
        if payload.get("success") is not True:
            raise _bad(_clean_error_text(
                payload.get("error") or payload.get("message")
                or "success=false", key))
        ptype = str(payload.get("type") or "")
        if ptype != data_type:
            raise _bad(f"type mismatch: {ptype[:20] or 'missing'}")
        try:
            plen = int(payload.get("length"))
        except (TypeError, ValueError):
            raise _bad("length missing")
        if plen != length:
            raise _bad(f"length mismatch: {plen}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise _bad("data not a list")
        if len(data) != length:
            raise _bad(f"data length: {len(data)}")
        out: list[int] = []
        for item in data:
            if data_type == "uint8" or data_type == "uint16":
                value = self._as_uint(item, UINT_RANGES[data_type] - 1)
                if value is None:
                    raise _bad(f"{data_type} out of range")
                out.append(value)
                continue
            if not isinstance(item, str):
                raise _bad("hex item not a string")
            raw = item.strip().lower()
            expected = int(size or 1) * (2 if data_type == "hex8" else 4)
            if len(raw) != expected or any(
                    c not in "0123456789abcdef" for c in raw):
                raise _bad("hex item invalid")
            out.append(int(raw, 16))
        return out

    @staticmethod
    def _as_uint(item, maximum: int) -> int | None:
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            value = item
        elif isinstance(item, str) and item.strip().isdigit():
            value = int(item.strip())
        else:
            return None
        return value if 0 <= value <= maximum else None


# ── durable-стор v27 (только через write_transaction mca-01) ───────────────
_DRAW_COLS = (
    "draw_id", "created_at", "chat_id", "purpose", "source", "provider",
    "batch_id", "value", "candidates_json", "pool_size", "probability",
    "policy_version", "selected_id", "fallback_reason", "config_version",
)
_INSERT_DRAW_SQL = (
    "INSERT OR IGNORE INTO mca_random_draws ("
    + ", ".join(_DRAW_COLS) + ") VALUES (" + ",".join("?" * len(_DRAW_COLS))
    + ")")


@dataclass
class ReservedDraw:
    value: int
    index: int | None
    rejected: bool
    batch_id: str
    provider: str
    data_type: str
    draw_id: str
    value_range: int
    created_at: int


@dataclass
class ReservedChunkValue:
    value: int
    draw_id: str
    batch_id: str
    provider: str
    data_type: str
    value_range: int


class RandomStore:
    """Доступ к v27-таблицам (batches/draws/quota_state/state).

    Каждая запись — `DatabaseService.write_transaction` (единый write-механизм
    mca-01, single-writer). Watermark: `reserved_upto` инкрементируется в ТОЙ
    ЖЕ транзакции, что и journal-запись, ДО использования значения — crash
    может потерять выданное, но повторная выдача исключена."""

    def __init__(self, db) -> None:
        self._db = db

    # ── batches ────────────────────────────────────────────────────────────
    async def insert_batch(self, batch: AnuBatch, *,
                           created_at: int | None = None) -> str:
        batch_id = uuid.uuid4().hex
        values = [int(v) for v in batch.values]
        values_json = json.dumps(values, separators=(",", ":"))
        created = int(created_at if created_at is not None else time.time())

        async def _body(conn):
            await conn.execute(
                "INSERT OR IGNORE INTO mca_random_batches (batch_id, provider, "
                "data_type, length, values_json, reserved_upto, consumed_upto, "
                "source, created_at) VALUES (?,?,?,?,?,0,0,'quantum',?)",
                (batch_id, batch.provider, batch.data_type, len(values),
                 values_json, created))
            return batch_id

        return await self._db.write_transaction(
            _body, op_name="random_batch_insert")

    async def reserve_remaining(self) -> int:
        cursor = await self._db.db.execute(
            "SELECT COALESCE(SUM(length - reserved_upto), 0) AS r "
            "FROM mca_random_batches WHERE reserved_upto < length")
        row = await cursor.fetchone()
        return int(row["r"] if row is not None else 0)

    async def last_batch_info(self) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT batch_id, provider, data_type, length, reserved_upto, "
            "consumed_upto, created_at FROM mca_random_batches "
            "ORDER BY created_at DESC, batch_id DESC LIMIT 1")
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def reserve_chunk(self, k: int) -> list[ReservedChunkValue]:
        """Durably зарезервировать bounded chunk значений (D7, mca-06).

        Watermark фиксируется до использования: crash → значения потеряны,
        повторно не выдаются. Журнал для chunk пишется на flush (async-вход)."""
        k = max(0, int(k))
        if k <= 0:
            return []

        async def _body(conn):
            cursor = await conn.execute(
                "SELECT batch_id, provider, data_type, values_json, "
                "reserved_upto, length FROM mca_random_batches "
                "WHERE reserved_upto < length ORDER BY created_at, batch_id "
                "LIMIT 1")
            row = await cursor.fetchone()
            if row is None:
                return []
            try:
                values = json.loads(row["values_json"])
            except Exception:
                return []
            start = int(row["reserved_upto"])
            length = int(row["length"])
            take = min(k, max(0, length - start))
            if (take <= 0 or not isinstance(values, list)
                    or len(values) < start + take):
                return []
            updated = await conn.execute(
                "UPDATE mca_random_batches SET reserved_upto = reserved_upto + ? "
                "WHERE batch_id = ? AND reserved_upto = ?",
                (take, row["batch_id"], start))
            if int(updated.rowcount or 0) != 1:
                return []
            value_range = batch_value_range(row["data_type"], values)
            return [
                ReservedChunkValue(
                    value=int(values[pos]), draw_id=uuid.uuid4().hex,
                    batch_id=row["batch_id"], provider=row["provider"],
                    data_type=row["data_type"], value_range=value_range)
                for pos in range(start, start + take)]

        return list(await self._db.write_transaction(
            _body, op_name="random_reserve_chunk"))

    async def reserve_draw(self, *, n: int | None,
                           meta: dict) -> ReservedDraw | None:
        """Одна транзакция: watermark +1 (до использования) + journal-запись.

        `n=None` — probability-draw (value/range); `n>=2` — index-draw
        (rejection sampling; отвергнутое значение тоже журналируется честно).
        `None` — запаса нет (честная деградация у вызывающего)."""
        created = int(time.time())

        async def _body(conn):
            cursor = await conn.execute(
                "SELECT batch_id, provider, data_type, values_json, "
                "reserved_upto, length FROM mca_random_batches "
                "WHERE reserved_upto < length ORDER BY created_at, batch_id "
                "LIMIT 1")
            row = await cursor.fetchone()
            if row is None:
                return None
            try:
                values = json.loads(row["values_json"])
            except Exception:
                return None
            start = int(row["reserved_upto"])
            if not isinstance(values, list) or len(values) <= start:
                return None
            value = int(values[start])
            updated = await conn.execute(
                "UPDATE mca_random_batches SET reserved_upto = reserved_upto + 1, "
                "consumed_upto = consumed_upto + 1 "
                "WHERE batch_id = ? AND reserved_upto = ?",
                (row["batch_id"], start))
            if int(updated.rowcount or 0) != 1:
                return None
            value_range = batch_value_range(row["data_type"], values)
            draw_id = uuid.uuid4().hex
            if n is None:
                index, rejected = None, False
                journal_value: Any = (value / value_range
                                      if value_range > 0 else 0.0)
            else:
                index = map_value_to_index(value, int(n), value_range)
                rejected = index is None
                journal_value = value
            await conn.execute(_INSERT_DRAW_SQL, (
                draw_id, created, meta.get("chat_id"),
                meta.get("purpose"), MODE_QUANTUM, row["provider"],
                row["batch_id"], journal_value,
                meta.get("candidates_json"), meta.get("pool_size"),
                meta.get("probability"), meta.get("policy_version"),
                (None if (n is None or rejected) else str(index)),
                meta.get("fallback_reason"), meta.get("config_version")))
            return ReservedDraw(
                value=value, index=index, rejected=rejected,
                batch_id=row["batch_id"], provider=row["provider"],
                data_type=row["data_type"], draw_id=draw_id,
                value_range=value_range, created_at=created)

        return await self._db.write_transaction(_body, op_name="random_draw")

    # ── journal ────────────────────────────────────────────────────────────
    async def journal_draw(self, record: dict) -> bool:
        async def _body(conn):
            cursor = await conn.execute(
                _INSERT_DRAW_SQL,
                tuple(record.get(c) for c in _DRAW_COLS))
            return cursor.rowcount

        return bool(await self._db.write_transaction(
            _body, op_name="random_draw_journal"))

    async def journal_many(self, records: list[dict]) -> int:
        if not records:
            return 0

        async def _body(conn):
            written = 0
            for record in records:
                cursor = await conn.execute(
                    _INSERT_DRAW_SQL,
                    tuple(record.get(c) for c in _DRAW_COLS))
                written += int(cursor.rowcount or 0)
                batch_id = record.get("batch_id")
                if batch_id:
                    await conn.execute(
                        "UPDATE mca_random_batches SET consumed_upto = "
                        "consumed_upto + 1 WHERE batch_id = ? AND "
                        "consumed_upto < length", (batch_id,))
            return written

        return int(await self._db.write_transaction(
            _body, op_name="random_journal_flush"))

    async def recent_draws(self, *, limit: int = 20,
                           chat_id: int | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        sql = ("SELECT " + ", ".join(_DRAW_COLS)
               + " FROM mca_random_draws ")
        params: list[Any] = []
        if chat_id is not None:
            sql += "WHERE chat_id = ? "
            params.append(int(chat_id))
        sql += "ORDER BY created_at DESC, draw_id DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.db.execute(sql, tuple(params))
        return [dict(r) for r in await cursor.fetchall()]

    async def journal_stats(self) -> dict:
        cursor = await self._db.db.execute(
            "SELECT source, COUNT(*) AS c FROM mca_random_draws "
            "GROUP BY source")
        stats = {"quantum": 0, "pseudorandom": 0}
        for row in await cursor.fetchall():
            stats[str(row["source"])] = int(row["c"])
        return stats

    async def prune(self, *, retention_days: int, max_rows: int) -> int:
        """Bounded-ретенция журнала/партий (env-only; GEN-R8)."""
        cutoff = int(time.time()) - max(1, int(retention_days)) * 86400
        keep = max(1, int(max_rows))

        async def _body(conn):
            removed = 0
            cursor = await conn.execute(
                "DELETE FROM mca_random_draws WHERE created_at < ?", (cutoff,))
            removed += int(cursor.rowcount or 0)
            cursor = await conn.execute(
                "DELETE FROM mca_random_draws WHERE draw_id IN ("
                "SELECT draw_id FROM mca_random_draws ORDER BY created_at "
                "DESC, draw_id DESC LIMIT -1 OFFSET ?)", (keep,))
            removed += int(cursor.rowcount or 0)
            cursor = await conn.execute(
                "DELETE FROM mca_random_batches WHERE reserved_upto >= length "
                "AND created_at < ?", (cutoff,))
            removed += int(cursor.rowcount or 0)
            return removed

        return int(await self._db.write_transaction(
            _body, op_name="random_prune") or 0)

    # ── quota (account-global, не per-chat) ────────────────────────────────
    async def quota_record(self, *, account_key: str, period: str,
                           outcome: str, manual: bool = False,
                           reason: str | None = None) -> None:
        """Period-aware запись квоты (spec §14.3/D3: account_key+period).

        Смена `period` (новый месяц UTC) сбрасывает счётчики прошлого периода
        ДО инкремента — «оценка» не залипает на исчерпании; 429 остаётся
        авторитетной причиной (`last_reason`), `unknown ≠ failed` не меняется."""
        column = {"success": "success", "failed": "failed",
                  "unknown": "unknown"}.get(outcome, "failed")
        now = int(time.time())
        success_at = now if column == "success" else None
        failure_at = now if column in ("failed", "unknown") else None
        same = "mca_random_quota_state.period = excluded.period"

        async def _body(conn):
            await conn.execute(
                "INSERT INTO mca_random_quota_state (account_key, period, "
                "success, failed, unknown, manual_checks, last_success_at, "
                "last_failure_at, last_reason, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(account_key) DO UPDATE SET period=excluded.period, "
                f"success=(CASE WHEN {same} THEN mca_random_quota_state.success "
                "ELSE 0 END) + excluded.success, "
                f"failed=(CASE WHEN {same} THEN mca_random_quota_state.failed "
                "ELSE 0 END) + excluded.failed, "
                f"unknown=(CASE WHEN {same} THEN mca_random_quota_state.unknown "
                "ELSE 0 END) + excluded.unknown, "
                f"manual_checks=(CASE WHEN {same} THEN "
                "mca_random_quota_state.manual_checks ELSE 0 END) + "
                "excluded.manual_checks, "
                f"last_success_at=CASE WHEN {same} THEN "
                "COALESCE(excluded.last_success_at, "
                "mca_random_quota_state.last_success_at) "
                "ELSE excluded.last_success_at END, "
                f"last_failure_at=CASE WHEN {same} THEN "
                "COALESCE(excluded.last_failure_at, "
                "mca_random_quota_state.last_failure_at) "
                "ELSE excluded.last_failure_at END, "
                f"last_reason=CASE WHEN {same} THEN "
                "COALESCE(excluded.last_reason, "
                "mca_random_quota_state.last_reason) "
                "ELSE excluded.last_reason END, "
                "updated_at=excluded.updated_at",
                (str(account_key), str(period),
                 1 if column == "success" else 0,
                 1 if column == "failed" else 0,
                 1 if column == "unknown" else 0,
                 1 if manual else 0, success_at, failure_at,
                 (str(reason)[:160] if reason else None), now))
            return True

        await self._db.write_transaction(_body, op_name="random_quota")

    async def quota_get(self, *, account_key: str) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT account_key, period, success, failed, unknown, "
            "manual_checks, last_success_at, last_failure_at, last_reason, "
            "updated_at FROM mca_random_quota_state WHERE account_key = ?",
            (str(account_key),))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    # ── activation state (одна строка scope='anu') ─────────────────────────
    async def get_state(self) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT scope, key_fingerprint, activation_batch_id, activated_at, "
            "last_fallback_reason, last_fallback_at, updated_at "
            "FROM mca_random_state WHERE scope = 'anu'")
        row = await cursor.fetchone()
        return dict(row) if row is not None else None

    async def write_state(self, **fields) -> None:
        """Частичный upsert: обновляются ТОЛЬКО переданные колонки."""
        allowed = ("key_fingerprint", "activation_batch_id", "activated_at",
                   "last_fallback_reason", "last_fallback_at")
        updates = {k: v for k, v in fields.items() if k in allowed}
        now = int(time.time())

        async def _body(conn):
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                params = list(updates.values()) + [now]
                cursor = await conn.execute(
                    f"UPDATE mca_random_state SET {sets}, updated_at = ? "
                    "WHERE scope = 'anu'", tuple(params))
                if int(cursor.rowcount or 0) > 0:
                    return True
            columns = ["scope", "updated_at"] + list(updates.keys())
            values = ["anu", now] + list(updates.values())
            await conn.execute(
                "INSERT OR REPLACE INTO mca_random_state ("
                + ", ".join(columns) + ") VALUES ("
                + ",".join("?" * len(columns)) + ")", tuple(values))
            return True

        await self._db.write_transaction(_body, op_name="random_state")


# ── результаты draw/политики ────────────────────────────────────────────────
@dataclass
class DrawResult:
    """Результат draw. `deferred=True` — значение не выдано (необязательное
    действие откладывается с честной причиной; чат не блокируется)."""

    index: int | None = None
    value: int | float | None = None
    source: str = MODE_PSEUDORANDOM
    selected_source: str = MODE_QUANTUM
    provider: str | None = None
    batch_id: str | None = None
    draw_id: str | None = None
    fallback_reason: str | None = None
    reason: str | None = None
    deferred: bool = False
    source_impl: str | None = None
    policy_version: str | None = None
    attempts: int = 1


@dataclass
class PolicyChoice:
    """Нейтральный результат политики 10a (контракт 10b — ExplorationRequest/
    Result создаёт mca-10b; второй контракт здесь не создаётся)."""

    primary: Any
    selected: Any
    explored: bool = False
    reason: str | None = None
    pool: list = field(default_factory=list)
    pool_ids: list = field(default_factory=list)
    draw_ids: list = field(default_factory=list)
    probability: float = DEFAULT_EXPLORATION_PROBABILITY
    policy_version: str = POLICY_VERSION
    source: str | None = None
    fallback_reason: str | None = None
    deferred: bool = False


# ── политика exploration (чистая логика + инъекция источника) ───────────────
class ExplorationPolicy:
    """`choose(primary, alternatives, *, probability, chat_id, purpose,
    policy_version) -> PolicyChoice` (D6/T-4967).

    Семантика:
      * одна probability-проверка на автономную ситуацию (не сумма 5%);
        при успехе — ровно один целостный выбор альтернативы (отдельный draw);
      * exploration-пул БЕЗ основного варианта; нет допустимых альтернатив →
        основной + `no_eligible_alternative` (без draw);
      * равномерный выбор из альтернатив; `policy_version` в журнале;
      * недопустимые измерения не рандомизируются;
      * K4 OFF → primary без probability-draw (причина `disabled`);
      * выбор не обходит уместность/проверку перед отправкой (их выполняет
        потребитель; политика их не подменяет и не отключает)."""

    def __init__(self, source) -> None:
        self._source = source    # RandomSourceService | fake (DI для тестов)

    async def choose(self, primary, alternatives, *, probability: float | None
                     = None, chat_id=None, purpose: str,
                     policy_version: str | None = None,
                     measurement: str | None = None) -> PolicyChoice:
        pv = str(policy_version or POLICY_VERSION)
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_exploration_enabled():
            return PolicyChoice(primary=primary, selected=primary,
                                reason="disabled", policy_version=pv)
        if measurement and str(measurement) in INELIGIBLE_MEASUREMENTS:
            return PolicyChoice(primary=primary, selected=primary,
                                reason="no_eligible_alternative",
                                policy_version=pv)
        if str(purpose or "") not in EXPLORATION_PURPOSES:
            return PolicyChoice(primary=primary, selected=primary,
                                reason="no_eligible_alternative",
                                policy_version=pv)
        pool = [alt for alt in (alternatives or [])
                if not _same_candidate(alt, primary)]
        if not pool:
            return PolicyChoice(primary=primary, selected=primary,
                                reason="no_eligible_alternative",
                                policy_version=pv)
        p = await self._probability(probability, purpose)
        prob_draw = await self._source.draw_probability(
            chat_id=chat_id, purpose=purpose, policy_version=pv,
            probability=p)
        if prob_draw is None or prob_draw.deferred or prob_draw.value is None:
            reason = (prob_draw.reason if prob_draw is not None
                      else "provider_unavailable")
            return PolicyChoice(primary=primary, selected=primary,
                                reason=reason, pool=pool,
                                pool_ids=[_candidate_id(a) for a in pool],
                                probability=p, policy_version=pv,
                                source=(prob_draw.source if prob_draw else None),
                                fallback_reason=(prob_draw.fallback_reason
                                                 if prob_draw else None),
                                deferred=True)
        draw_ids = [d for d in (prob_draw.draw_id,) if d]
        try:
            value = float(prob_draw.value)
        except (TypeError, ValueError):
            value = 1.0
        if value >= p:
            return PolicyChoice(primary=primary, selected=primary,
                                pool=pool,
                                pool_ids=[_candidate_id(a) for a in pool],
                                draw_ids=draw_ids, probability=p,
                                policy_version=pv, source=prob_draw.source,
                                fallback_reason=prob_draw.fallback_reason)
        sel_draw = await self._source.draw_index(
            len(pool), chat_id=chat_id, purpose=purpose, policy_version=pv,
            candidates=[_candidate_id(a) for a in pool], probability=p)
        if sel_draw is None or sel_draw.deferred or sel_draw.index is None:
            reason = (sel_draw.reason if sel_draw is not None
                      else "provider_unavailable")
            return PolicyChoice(primary=primary, selected=primary,
                                reason=reason, pool=pool,
                                pool_ids=[_candidate_id(a) for a in pool],
                                draw_ids=draw_ids, probability=p,
                                policy_version=pv,
                                source=(sel_draw.source if sel_draw else None),
                                fallback_reason=(sel_draw.fallback_reason
                                                 if sel_draw else None),
                                deferred=True)
        index = max(0, min(int(sel_draw.index), len(pool) - 1))
        if sel_draw.draw_id:
            draw_ids.append(sel_draw.draw_id)
        return PolicyChoice(primary=primary, selected=pool[index],
                            explored=True, pool=pool,
                            pool_ids=[_candidate_id(a) for a in pool],
                            draw_ids=draw_ids, probability=p,
                            policy_version=pv, source=sel_draw.source,
                            fallback_reason=sel_draw.fallback_reason)

    async def _probability(self, probability: float | None,
                           purpose: str) -> float:
        if probability is not None:
            try:
                return min(1.0, max(0.0, float(probability)))
            except (TypeError, ValueError):
                pass
        key = EXPLORATION_PROBABILITY_KEYS.get(
            str(purpose or ""), SETTING_EXPLORATION)
        value = await _read_memory_setting(key, None,
                                           DEFAULT_EXPLORATION_PROBABILITY)
        return _as_probability(value, DEFAULT_EXPLORATION_PROBABILITY)


# ── sync-адаптер стыка mca-06 (без fork пайплайна) ──────────────────────────
class CoreDreamRandomSource:
    """`DreamRandomSource` (mca-06): `pick(candidates, *, chat_id, purpose, k)`.

    `pick` — sync, без I/O: маппинг durably зарезервированных значений в
    индексы (rejection sampling) для quantum либо stdlib `random.Random`
    (auto-seed) для pseudorandom. Журнал draw пишется bounded-очередью и
    флашится на следующем async-входе сервиса (crash до флаша: значения
    потеряны, повторно не выдаются; журнал — для завершённых решений).
    `selection_meta` совместим с mca-06 и аддитивен; для quantum `seed=null`
    (честно). «Выбор ≠ вердикт»: вердикт downstream — только по доказательствам.
    """

    def __init__(self, *, pipeline_run_id: int | None = None,
                 chat_id: int | None = None, source: str = MODE_QUANTUM,
                 provider: str | None = None, batch_id: str | None = None,
                 data_type: str = DEFAULT_DATA_TYPE, values=(),
                 draw_ids=(), fallback: bool = False,
                 fallback_reason: str | None = None,
                 journal_sink: Callable[[dict], None] | None = None) -> None:
        self.pipeline_run_id = pipeline_run_id
        self.chat_id = chat_id
        self.source = str(source)
        self.provider = provider
        self.batch_id = batch_id
        self.data_type = str(data_type)
        self.values = [int(v) for v in values]
        self.draw_ids = [str(d) for d in draw_ids]
        self.fallback = bool(fallback)
        self.fallback_reason = fallback_reason
        self._journal_sink = journal_sink

    def pick(self, candidates, *, chat_id, purpose: str, k: int
             ) -> tuple[list, dict]:
        pool = list(candidates or [])
        n = len(pool)
        k = max(0, min(int(k), n))
        picked: list[int] = []
        used: list[tuple[int, str | None, int | None]] = []  # value, draw_id, idx
        if k > 0 and n > 0:
            if self.source == MODE_QUANTUM:
                value_range = batch_value_range(self.data_type, self.values)
                for pos, value in enumerate(self.values):
                    if len(picked) >= k:
                        break
                    draw_id = (self.draw_ids[pos]
                               if pos < len(self.draw_ids) else None)
                    index = map_value_to_index(int(value), n, value_range)
                    used.append((int(value), draw_id, index))
                    if index is None or index in picked:
                        continue
                    picked.append(index)
            else:
                rng = random.Random()      # auto-seed; не для security
                picked = sorted(rng.sample(range(n), k))
                for index in picked:
                    used.append((int(index), uuid.uuid4().hex, int(index)))
        else:
            picked = []
        picked = sorted(picked)
        items = [pool[i] for i in picked]
        meta: dict[str, Any] = {
            "source": ("quantum" if self.source == MODE_QUANTUM
                       else "pseudorandom"),
            "purpose": str(purpose),
            "seed": None,
            "k": int(k),
            "pool": int(n),
            "picked": [int(i) for i in picked][:SELECTION_META_CAP],
            "provider": (self.provider if self.source == MODE_QUANTUM
                         else PROVIDER_PRNG),
            "batch_id": (self.batch_id if self.source == MODE_QUANTUM
                         else None),
            "draw_ids": [d for _, d, _ in used if d][:SELECTION_META_CAP],
            "fallback": bool(self.fallback),
            "fallback_reason": self.fallback_reason,
            "source_impl": (SOURCE_IMPL_PRNG if self.source != MODE_QUANTUM
                            else "anu-quantum"),
            "reserved": len(self.values),
            "used": len(used),
        }
        if self._journal_sink is not None and used:
            candidates_json = json.dumps(
                [_candidate_id(c) for c in pool[:CANDIDATES_CAP]],
                ensure_ascii=False)
            for value, draw_id, index in used:
                try:
                    self._journal_sink({
                        "draw_id": draw_id or uuid.uuid4().hex,
                        "created_at": int(time.time()),
                        "chat_id": (int(chat_id)
                                    if chat_id is not None else None),
                        "purpose": str(purpose)[:120],
                        "source": meta["source"],
                        "provider": meta["provider"],
                        "batch_id": meta["batch_id"],
                        "value": int(value),
                        "candidates_json": candidates_json,
                        "pool_size": int(n),
                        "probability": None,
                        "policy_version": POLICY_VERSION,
                        "selected_id": (str(index) if index is not None
                                        else None),
                        "fallback_reason": self.fallback_reason,
                        "config_version": APP_VERSION,
                    })
                except Exception:      # sink fail-safe: pick не рвём
                    break
        return items, meta


# ── сервис ──────────────────────────────────────────────────────────────────
def _as_mode(value, default: str = DEFAULT_SOURCE) -> str:
    text = str(value or "").strip().lower()
    return text if text in MODES else default


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_probability(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:       # NaN
        return default
    return min(1.0, max(0.0, number))


def _as_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < minimum or number > maximum:
        return default
    return number


async def _read_memory_setting(key: str, chat_id, default):
    """Единственный read-path настроек (`worker_settings.resolve_setting`);
    fail-open: ошибка чтения → дефолт (бот жив), значение в лог не попадает."""
    try:
        from services.worker_settings import resolve_setting
        return await resolve_setting(key, chat_id=chat_id, default=default)
    except Exception:
        logger.warning("[random_source] setting read failed — default | "
                       "key=%s", key)
        return default


def _hot_setting(key: str, default):
    """Глобальный слой (bot_settings/ConfigCache) с fail-open на дефолт."""
    try:
        from services import hot_config as hot
        value = hot.get(key, None)
    except Exception:
        value = None
    return default if value is None else value


class RandomSourceService:
    """Единственный сервис RandomSource (D1–D5)."""

    def __init__(self, db=None, *, client: AnuClient | None = None,
                 auto_refill: bool = True) -> None:
        self.db = db
        self._store = RandomStore(db) if db is not None else None
        self._client = client
        self._client_pinned = client is not None
        self._auto_refill = bool(auto_refill)
        self._policy = ExplorationPolicy(source=self)
        self._journal_queue: collections.deque = collections.deque(
            maxlen=JOURNAL_QUEUE_MAX)
        self._journal_dropped = 0
        self._transition_key: str | None = None
        self._refill_task: asyncio.Task | None = None
        self._check_lock = asyncio.Lock()
        self._check_task: asyncio.Task | None = None
        self._check_key: str | None = None
        self._last_latency_ms: int | None = None
        self._last_refill_reason: str | None = None

    # ── DI/жизненный цикл ──────────────────────────────────────────────────
    def bind_db(self, db) -> None:
        self.db = db
        self._store = RandomStore(db) if db is not None else None

    def set_client(self, client: AnuClient | None) -> None:
        self._client = client
        self._client_pinned = client is not None

    def _get_client(self) -> AnuClient:
        if self._client is None:
            self._client = AnuClient(
                timeout=self._timeout_seconds(),
                min_interval=mca_gates.random_min_request_interval_seconds(),
                circuit_fails=mca_gates.random_circuit_fails(),
                circuit_cooldown=float(
                    mca_gates.random_circuit_cooldown_seconds()))
        elif not self._client_pinned:
            self._client.configure(
                timeout=self._timeout_seconds(),
                min_interval=mca_gates.random_min_request_interval_seconds(),
                circuit_fails=mca_gates.random_circuit_fails(),
                circuit_cooldown=float(
                    mca_gates.random_circuit_cooldown_seconds()))
        return self._client

    # ── настройки (per-call; hot; валидация на чтении) ─────────────────────
    async def selected_mode(self, chat_id=None) -> str:
        raw = await _read_memory_setting(SETTING_SOURCE, chat_id,
                                         DEFAULT_SOURCE)
        mode = _as_mode(raw, DEFAULT_SOURCE)
        if mode != str(raw or "").strip().lower() and str(raw or "").strip():
            logger.warning("[random_source] invalid mode — default | "
                           "value=%s", str(raw)[:20])
        return mode

    async def fallback_enabled(self, chat_id=None) -> bool:
        raw = await _read_memory_setting(SETTING_FALLBACK, chat_id,
                                         DEFAULT_FALLBACK)
        return _as_bool(raw, DEFAULT_FALLBACK)

    async def exploration_probability(self, purpose: str,
                                      chat_id=None) -> float:
        key = EXPLORATION_PROBABILITY_KEYS.get(str(purpose or ""),
                                                SETTING_EXPLORATION)
        raw = await _read_memory_setting(key, chat_id,
                                         DEFAULT_EXPLORATION_PROBABILITY)
        return _as_probability(raw, DEFAULT_EXPLORATION_PROBABILITY)

    def _resolve_key(self) -> str:
        raw = _hot_setting(SETTING_KEY, None)
        if raw is None:
            raw = getattr(settings, "RANDOM_QUANTUM_API_KEY", "") or ""
        return str(raw or "").strip()

    def _endpoint(self) -> str:
        return str(_hot_setting(SETTING_ENDPOINT, ANU_ENDPOINT) or "").strip()

    def _plan(self) -> str:
        raw = str(_hot_setting(SETTING_PLAN, DEFAULT_PLAN) or "").strip()
        return raw if raw in PLANS else DEFAULT_PLAN

    def _batch_length(self) -> int:
        return _as_int(_hot_setting(SETTING_BATCH_LENGTH, DEFAULT_BATCH_LENGTH),
                       DEFAULT_BATCH_LENGTH, MIN_LENGTH, MAX_LENGTH)

    def _data_type(self) -> str:
        raw = str(_hot_setting(SETTING_DATA_TYPE, DEFAULT_DATA_TYPE)
                  or "").strip().lower()
        return raw if raw in DATA_TYPES else DEFAULT_DATA_TYPE

    def _timeout_seconds(self) -> float:
        return float(_as_int(_hot_setting(SETTING_TIMEOUT,
                                          DEFAULT_TIMEOUT_SECONDS),
                             DEFAULT_TIMEOUT_SECONDS, 1, 30))

    def _low_watermark(self) -> int:
        buffer_max = self._buffer_max()
        return _as_int(_hot_setting(SETTING_LOW_WATERMARK,
                                    DEFAULT_LOW_WATERMARK),
                       DEFAULT_LOW_WATERMARK, 1, buffer_max)

    def _buffer_max(self) -> int:
        return _as_int(_hot_setting(SETTING_BUFFER_MAX, DEFAULT_BUFFER_MAX),
                       DEFAULT_BUFFER_MAX, 256, 8192)

    def _account_key(self) -> str:
        return f"anu:{self._plan().lower()}"

    # ── журнал (bounded-очередь sync-pick + flush на async-входе) ──────────
    def _enqueue_journal(self, record: dict) -> None:
        try:
            if len(self._journal_queue) >= JOURNAL_QUEUE_MAX:
                self._journal_dropped += 1
            self._journal_queue.append(record)
        except Exception:          # pragma: no cover - защитная ветка
            pass

    async def flush_journal(self) -> int:
        if not self._journal_queue or self._store is None:
            return 0
        batch = list(self._journal_queue)
        self._journal_queue.clear()
        try:
            return await self._store.journal_many(batch)
        except Exception:
            logger.warning("[random_source] journal flush failed | "
                           "count=%d", len(batch), exc_info=True)
            for record in batch:
                self._enqueue_journal(record)
            return 0

    def journal_queue_depth(self) -> int:
        return len(self._journal_queue)

    # ── события (notable-only, единый emit_mca_event) ──────────────────────
    def _emit(self, event_name: str, *, outcome: str, level: str = "INFO",
              reason_code: str | None = None, **fields) -> None:
        if not mca_gates.random_source_enabled():
            return
        try:
            mca_events.emit_mca_event(
                event_name, outcome=outcome, level=level,
                component="random", reason_code=reason_code, **fields)
        except Exception:          # pragma: no cover - fail-open
            return

    def _note_transition(self, *, key: str, reason: str,
                         deferred: bool = False) -> None:
        """Один notable-переход (не на каждый draw): random_fallback."""
        if self._transition_key == key:
            return
        self._transition_key = key
        self._emit("random_fallback", outcome=mca_events.OUTCOME_SILENT,
                   level=mca_events.LEVEL_WARN,
                   reason_code="random_fallback" if not deferred else reason,
                   stage="fallback",
                   entity_ids={"blocker": reason, "deferred": bool(deferred)})

    def _note_quantum_success(self) -> None:
        self._transition_key = None

    # ── резолв selected/effective (без расхода значений) ───────────────────
    async def resolve_effective(self, chat_id=None) -> tuple[str, str | None]:
        """(effective, blocker). quantum — только при K1/K2 ON, выбранном
        quantum и непустом durable-запасе; иначе pseudorandom + причина
        (None — выбран pseudorandom явно)."""
        selected = await self.selected_mode(chat_id)
        if selected == MODE_PSEUDORANDOM:
            return MODE_PSEUDORANDOM, None
        if not mca_gates.random_quantum_enabled():
            return MODE_PSEUDORANDOM, "disabled"
        remaining = await self._reserve_remaining()
        if remaining > 0:
            return MODE_QUANTUM, None
        return MODE_PSEUDORANDOM, await self._provider_blocker()

    async def _reserve_remaining(self) -> int:
        if self._store is None:
            return 0
        try:
            return await self._store.reserve_remaining()
        except Exception:
            logger.warning("[random_source] reserve read failed", exc_info=True)
            return 0

    async def _provider_blocker(self) -> str:
        state = await self._read_state()
        if state and state.get("last_fallback_reason"):
            return str(state["last_fallback_reason"])
        if not self._resolve_key():
            return "provider_unconfigured"
        if state is None or not state.get("activated_at") \
                or state.get("key_fingerprint") != \
                key_fingerprint(self._resolve_key()):
            return "provider_unavailable"
        return "provider_unavailable"

    async def _read_state(self) -> dict | None:
        if self._store is None:
            return None
        try:
            return await self._store.get_state()
        except Exception:
            return None

    # ── draw-API (async; 10b/09 — потребители) ─────────────────────────────
    async def draw_index(self, n: int, *, chat_id=None, purpose: str = "",
                         policy_version: str | None = None,
                         candidates=None, probability: float | None = None
                         ) -> DrawResult:
        """Равномерный индекс 0..n-1 (rejection sampling; n=1 — без расхода).

        `candidates` — опциональные ID пула (только для журнала; cap 50);
        `probability` — порог политики (только для журнала, T-4969).
        Каждый draw — отдельное значение; повторное использование запрещено."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 0
        selected = await self.selected_mode(chat_id)
        pv = str(policy_version or POLICY_VERSION)
        if n <= 0:
            return DrawResult(index=None, deferred=True,
                              reason="validation_failed",
                              selected_source=selected, policy_version=pv)
        if n == 1:
            return DrawResult(index=0, value=None, source=selected,
                              selected_source=selected, policy_version=pv,
                              reason=(None if mca_gates.random_source_enabled()
                                      else "disabled"))
        if not mca_gates.random_source_enabled():
            return DrawResult(index=None, deferred=True, reason="disabled",
                              selected_source=selected, policy_version=pv)
        effective, blocker = await self.resolve_effective(chat_id)
        if effective == MODE_QUANTUM:
            result = await self._quantum_index_draw(
                n, chat_id=chat_id, purpose=purpose, policy_version=pv,
                candidates=candidates, probability=probability)
            if result is not None:
                self._note_quantum_success()
                return result
            blocker = await self._provider_blocker()
        fallback = await self.fallback_enabled(chat_id)
        if blocker is None or fallback:
            if blocker is not None:
                self._note_transition(key=f"prng:{blocker}", reason=blocker)
                await self._mark_fallback(blocker)
            return await self._prng_index_draw(
                n, chat_id=chat_id, purpose=purpose, policy_version=pv,
                fallback_reason=blocker, candidates=candidates,
                probability=probability)
        self._note_transition(key=f"defer:{blocker}", reason=blocker,
                              deferred=True)
        return DrawResult(index=None, deferred=True, reason=blocker,
                          source=MODE_PSEUDORANDOM, selected_source=selected,
                          fallback_reason=blocker, policy_version=pv)

    async def draw_probability(self, *, chat_id=None, purpose: str = "",
                               policy_version: str | None = None,
                               probability: float | None = None) -> DrawResult:
        """Равномерная величина [0,1) (отдельное значение на каждую проверку).

        `probability` — порог политики (только для журнала, T-4969)."""
        selected = await self.selected_mode(chat_id)
        pv = str(policy_version or POLICY_VERSION)
        if not mca_gates.random_source_enabled():
            return DrawResult(value=None, deferred=True, reason="disabled",
                              selected_source=selected, policy_version=pv)
        effective, blocker = await self.resolve_effective(chat_id)
        if effective == MODE_QUANTUM:
            result = await self._quantum_probability_draw(
                chat_id=chat_id, purpose=purpose, policy_version=pv,
                probability=probability)
            if result is not None:
                self._note_quantum_success()
                return result
            blocker = await self._provider_blocker()
        fallback = await self.fallback_enabled(chat_id)
        if blocker is None or fallback:
            if blocker is not None:
                self._note_transition(key=f"prng:{blocker}", reason=blocker)
                await self._mark_fallback(blocker)
            return await self._prng_probability_draw(
                chat_id=chat_id, purpose=purpose, policy_version=pv,
                fallback_reason=blocker, probability=probability)
        self._note_transition(key=f"defer:{blocker}", reason=blocker,
                              deferred=True)
        return DrawResult(value=None, deferred=True, reason=blocker,
                          source=MODE_PSEUDORANDOM, selected_source=selected,
                          fallback_reason=blocker, policy_version=pv)

    async def choose(self, primary, alternatives, *, probability: float | None
                     = None, chat_id=None, purpose: str,
                     policy_version: str | None = None,
                     measurement: str | None = None) -> PolicyChoice:
        return await self._policy.choose(
            primary, alternatives, probability=probability, chat_id=chat_id,
            purpose=purpose, policy_version=policy_version,
            measurement=measurement)

    # ── внутренние draw-пути ───────────────────────────────────────────────
    def _meta(self, *, chat_id, purpose, policy_version, probability=None,
              pool_size=None, candidates=None,
              fallback_reason=None) -> dict:
        return {
            "chat_id": int(chat_id) if chat_id is not None else None,
            "purpose": str(purpose or "")[:120],
            "policy_version": str(policy_version or POLICY_VERSION)[:120],
            "probability": probability,
            "pool_size": pool_size,
            "candidates_json": (
                json.dumps(list(candidates)[:CANDIDATES_CAP],
                           ensure_ascii=False)
                if candidates else None),
            "fallback_reason": fallback_reason,
            "config_version": APP_VERSION,
        }

    async def _quantum_index_draw(self, n: int, *, chat_id, purpose,
                                  policy_version, candidates=None,
                                  probability=None) -> DrawResult | None:
        if self._store is None:
            return None
        pool_candidates = (list(candidates)[:CANDIDATES_CAP]
                           if candidates is not None
                           else list(range(min(n, CANDIDATES_CAP))))
        meta = self._meta(chat_id=chat_id, purpose=purpose,
                          policy_version=policy_version, pool_size=n,
                          candidates=pool_candidates, probability=probability)
        attempts = 0
        for _ in range(MAX_DRAW_ATTEMPTS):
            reserved = await self._store.reserve_draw(n=n, meta=meta)
            if reserved is None:
                return None
            attempts += 1
            if reserved.index is not None:
                return DrawResult(
                    index=int(reserved.index), value=int(reserved.value),
                    source=MODE_QUANTUM, selected_source=MODE_QUANTUM,
                    provider=reserved.provider, batch_id=reserved.batch_id,
                    draw_id=reserved.draw_id, source_impl="anu-quantum",
                    policy_version=str(policy_version or POLICY_VERSION),
                    attempts=attempts)
        return DrawResult(index=None, deferred=True,
                          reason="validation_failed",
                          source=MODE_QUANTUM, provider=PROVIDER_ANU,
                          attempts=attempts,
                          policy_version=str(policy_version or POLICY_VERSION))

    async def _quantum_probability_draw(self, *, chat_id, purpose,
                                        policy_version,
                                        probability=None) -> DrawResult | None:
        if self._store is None:
            return None
        meta = self._meta(chat_id=chat_id, purpose=purpose,
                          policy_version=policy_version,
                          probability=probability)
        reserved = await self._store.reserve_draw(n=None, meta=meta)
        if reserved is None:
            return None
        return DrawResult(value=float(reserved.value) / float(
            reserved.value_range or 1), source=MODE_QUANTUM,
            selected_source=MODE_QUANTUM, provider=reserved.provider,
            batch_id=reserved.batch_id, draw_id=reserved.draw_id,
            source_impl="anu-quantum",
            policy_version=str(policy_version or POLICY_VERSION))

    async def _prng_index_draw(self, n: int, *, chat_id, purpose,
                               policy_version,
                               fallback_reason=None,
                               candidates=None, probability=None) -> DrawResult:
        rng = random.Random()          # auto-seed; версия фиксируется ниже
        index = int(rng.randrange(n))
        pool_candidates = (list(candidates)[:CANDIDATES_CAP]
                           if candidates is not None
                           else list(range(min(n, CANDIDATES_CAP))))
        draw_id = await self._journal_prng(
            chat_id=chat_id, purpose=purpose, policy_version=policy_version,
            value=index, selected_id=str(index), pool_size=n,
            candidates=pool_candidates, probability=probability,
            fallback_reason=fallback_reason)
        return DrawResult(index=index, value=index, source=MODE_PSEUDORANDOM,
                          selected_source=await self.selected_mode(chat_id),
                          provider=PROVIDER_PRNG, draw_id=draw_id,
                          source_impl=SOURCE_IMPL_PRNG,
                          fallback_reason=fallback_reason,
                          policy_version=str(policy_version or POLICY_VERSION))

    async def _prng_probability_draw(self, *, chat_id, purpose,
                                     policy_version,
                                     fallback_reason=None,
                                     probability=None) -> DrawResult:
        rng = random.Random()
        value = float(rng.random())
        draw_id = await self._journal_prng(
            chat_id=chat_id, purpose=purpose, policy_version=policy_version,
            value=value, selected_id=None, pool_size=None, candidates=None,
            probability=probability, fallback_reason=fallback_reason)
        return DrawResult(value=value, source=MODE_PSEUDORANDOM,
                          selected_source=await self.selected_mode(chat_id),
                          provider=PROVIDER_PRNG, draw_id=draw_id,
                          source_impl=SOURCE_IMPL_PRNG,
                          fallback_reason=fallback_reason,
                          policy_version=str(policy_version or POLICY_VERSION))

    async def _journal_prng(self, *, chat_id, purpose, policy_version, value,
                            selected_id, pool_size, candidates,
                            fallback_reason, probability=None) -> str | None:
        if self._store is None:
            return None
        draw_id = uuid.uuid4().hex
        record = {
            "draw_id": draw_id,
            "created_at": int(time.time()),
            "chat_id": int(chat_id) if chat_id is not None else None,
            "purpose": str(purpose or "")[:120],
            "source": MODE_PSEUDORANDOM,
            "provider": PROVIDER_PRNG,
            "batch_id": None,
            "value": float(value),
            "candidates_json": (
                json.dumps(list(candidates)[:CANDIDATES_CAP],
                           ensure_ascii=False) if candidates else None),
            "pool_size": pool_size,
            "probability": probability,
            "policy_version": str(policy_version or POLICY_VERSION)[:120],
            "selected_id": selected_id,
            "fallback_reason": fallback_reason,
            "config_version": APP_VERSION,
        }
        try:
            await self._store.journal_draw(record)
        except Exception:
            logger.warning("[random_source] prng journal failed",
                           exc_info=True)
            return None
        return draw_id

    async def _mark_fallback(self, reason: str) -> None:
        if self._store is None:
            return
        try:
            await self._store.write_state(last_fallback_reason=str(reason)[:160],
                                          last_fallback_at=int(time.time()))
        except Exception:
            logger.warning("[random_source] fallback state write failed",
                           exc_info=True)

    # ── ANU: fetch/активация/refill/квота ──────────────────────────────────
    async def _fetch_batch(self, key: str, *, manual: bool) -> AnuBatch:
        data_type = self._data_type()
        size = (mca_gates.random_quantum_hex_block_size()
                if data_type in HEX_TYPES else None)
        client = self._get_client()
        started = time.monotonic()
        batch = await client.fetch(
            key=key, length=self._batch_length(), data_type=data_type,
            endpoint=self._endpoint(), size=size)
        batch.latency_ms = int((time.monotonic() - started) * 1000)
        self._last_latency_ms = batch.latency_ms
        return batch

    async def _record_quota_result(self, outcome: str, *,
                                   manual: bool, reason: str | None = None
                                   ) -> None:
        if self._store is None:
            return
        try:
            await self._store.quota_record(
                account_key=self._account_key(), period=_utc_period(),
                outcome=outcome, manual=manual, reason=reason)
        except Exception:
            logger.warning("[random_source] quota write failed", exc_info=True)

    async def _record_quota_error(self, exc: AnuError, *, manual: bool
                                  ) -> None:
        if not exc.sent:
            return                 # запрос не ушёл — квота не расходовалась
        outcome = "unknown" if exc.code == "timeout" else "failed"
        await self._record_quota_result(outcome, manual=manual,
                                        reason=exc.code)

    async def _confirm_activation(self, batch_id: str) -> bool:
        """Внутренний self-check через адаптер (один draw purpose
        `activation_selfcheck`, без отправки сообщения в чат) + active."""
        if self._store is None:
            return False
        chunk = await self._store.reserve_chunk(1)
        if not chunk:
            return False
        item = chunk[0]
        adapter = CoreDreamRandomSource(
            pipeline_run_id=None, chat_id=0, source=MODE_QUANTUM,
            provider=item.provider, batch_id=item.batch_id,
            data_type=item.data_type, values=[item.value],
            draw_ids=[item.draw_id], journal_sink=self._enqueue_journal)
        items, _meta = adapter.pick(
            ["activation_selfcheck_a", "activation_selfcheck_b"],
            chat_id=0, purpose=PURPOSE_ACTIVATION_SELFCHECK, k=1)
        await self.flush_journal()
        if not items:
            return False
        key = self._resolve_key()
        await self._store.write_state(
            key_fingerprint=key_fingerprint(key),
            activation_batch_id=str(batch_id), activated_at=int(time.time()),
            last_fallback_reason=None, last_fallback_at=None)
        self._note_quantum_success()
        self._emit("random_activation", outcome=mca_events.OUTCOME_SUCCESS,
                   reason_code="quantum_activated", stage="activate",
                   provider=PROVIDER_ANU,
                   entity_ids={"batch_id": str(batch_id)},
                   duration_ms=self._last_latency_ms)
        return True

    async def activate(self, *, manual: bool = True) -> dict:
        """Проверка соединения с ключом → валидная партия → зачисление →
        self-check → `quantum_activated` → effective quantum. HTTP 200 без
        проверки содержимого, mock и fallback активацией НЕ являются."""
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return {"state": ANU_STATE_DISABLED, "activated": False,
                    "blocker": None, "key_present": False}
        if self._store is None:
            return {"state": ANU_STATE_DEGRADED, "activated": False,
                    "blocker": "provider_unavailable", "key_present": False}
        key = self._resolve_key()
        if not key:
            await self._mark_state_failure("provider_unconfigured")
            self._emit("random_activation", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN,
                       reason_code="provider_unconfigured", stage="activate")
            return {"state": ANU_STATE_UNCONFIGURED, "activated": False,
                    "blocker": "provider_unconfigured", "key_present": False}
        fingerprint = key_fingerprint(key)
        state = await self._read_state()
        if (state and state.get("key_fingerprint")
                and state.get("key_fingerprint") != fingerprint):
            # смена ключа → unverified до успешной проверки (не healthy)
            if self._store is not None:
                await self._store.write_state(
                    key_fingerprint=fingerprint, activation_batch_id=None,
                    activated_at=None, last_fallback_reason=None,
                    last_fallback_at=None)
        try:
            batch = await self._fetch_batch(key, manual=manual)
        except AnuError as exc:
            await self._record_quota_error(exc, manual=manual)
            await self._mark_state_failure(exc.code, fingerprint=fingerprint)
            self._emit("random_activation", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN, reason_code=exc.code,
                       stage="activate", provider=PROVIDER_ANU,
                       error_json={"type": "AnuError", "code": exc.code,
                                   "retryable": exc.retryable,
                                   "sent": exc.sent})
            return {"state": await self.anu_state(), "activated": False,
                    "blocker": exc.code, "reason": exc.reason,
                    "key_present": True}
        await self._record_quota_result("success", manual=manual)
        batch_id = await self._store.insert_batch(batch)
        activated = await self._confirm_activation(batch_id)
        if not activated:
            self._emit("random_activation", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN,
                       reason_code="validation_failed", stage="activate",
                       provider=PROVIDER_ANU)
            return {"state": await self.anu_state(), "activated": False,
                    "blocker": "validation_failed", "key_present": True}
        return {"state": ANU_STATE_ACTIVE, "activated": True,
                "blocker": None, "key_present": True, "batch_id": batch_id,
                "length": len(batch.values), "latency_ms": batch.latency_ms}

    async def _mark_state_failure(self, reason: str, *,
                                  fingerprint: str | None = None) -> None:
        if self._store is None:
            return
        fields: dict[str, Any] = {
            "last_fallback_reason": str(reason)[:160],
            "last_fallback_at": int(time.time()),
        }
        if fingerprint:
            fields["key_fingerprint"] = fingerprint
        try:
            await self._store.write_state(**fields)
        except Exception:
            logger.warning("[random_source] state write failed", exc_info=True)

    async def test_connection(self, draft_key: str | None = None, *,
                              manual: bool = True) -> dict:
        """Backend-проверка подключения (кнопка — блок C): status/latency/
        дата/размер партии/очищенная ошибка. Draft-ключ (POST body) не
        сохраняется и не логируется; проверочные числа зачисляются в запас;
        неизвестный ключ не показывается healthy до успешной проверки.

        Singleflight (T-4977): повторные клики с тем же ключом, пока проверка
        в полёте, получают ОДИН общий результат (один запрос к провайдеру);
        клик с изменённым ключом дожидается текущей проверки и запускает
        свою (min interval провайдера не даёт лавины)."""
        key = str(draft_key or "").strip() or self._resolve_key()
        async with self._check_lock:
            if (self._check_task is not None
                    and not self._check_task.done()
                    and self._check_key == key):
                task = self._check_task          # coalesce: тот же ключ
            else:
                task = asyncio.create_task(self._run_check(key, manual=manual))
                self._check_task = task
                self._check_key = key
        try:
            result = await task
        except Exception as exc:      # неожиданный сбой — честный ответ, не 500
            logger.warning("[random_source] check failed | error=%s",
                           type(exc).__name__)
            result = {"healthy": False, "blocker": "provider_unavailable",
                      "key_present": bool(key), "persisted": False}
        finally:
            if task.done() and self._check_task is task:
                self._check_task = None
        return dict(result) if isinstance(result, dict) else result

    async def _run_check(self, key: str, *, manual: bool) -> dict:
        """Одна фактическая проверка (ключ уже разрешён вызывающим)."""
        if not key:
            return {"healthy": False, "blocker": "provider_unconfigured",
                    "key_present": False, "persisted": False}
        stored = self._resolve_key()
        if stored and key == stored:
            result = await self.activate(manual=manual)
            return {"healthy": bool(result.get("activated")),
                    "blocker": result.get("blocker"),
                    "reason": result.get("reason"),
                    "key_present": True, "persisted": True,
                    "state": result.get("state"),
                    "length": result.get("length"),
                    "latency_ms": result.get("latency_ms"),
                    "checked_at": int(time.time())}
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return {"healthy": False, "blocker": "disabled",
                    "key_present": bool(key), "persisted": False}
        try:
            batch = await self._fetch_batch(key, manual=manual)
        except AnuError as exc:
            await self._record_quota_error(exc, manual=manual)
            return {"healthy": False, "blocker": exc.code,
                    "reason": exc.reason, "key_present": True,
                    "persisted": False}
        await self._record_quota_result("success", manual=manual)
        if self._store is not None:
            await self._store.insert_batch(batch)   # не тратим запрос
        return {"healthy": True, "blocker": None, "key_present": True,
                "persisted": False, "length": len(batch.values),
                "latency_ms": batch.latency_ms,
                "checked_at": int(time.time())}

    async def refill_if_needed(self, *, force: bool = False) -> dict:
        """Фоновое пополнение партиями (не запрос на каждый draw).

        Singleflight через `TaskSupervisor.run(owner="random.source",
        kind="refill", coalesce_key="random.refill:<account>")` + durable
        `task_jobs`; watermark/buffer_max bounded; K3 OFF → не запускается."""
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return {"status": "disabled"}
        if not mca_gates.random_refill_enabled() and not force:
            return {"status": "disabled", "reason": "refill_disabled"}
        key = self._resolve_key()
        if not key:
            await self._mark_state_failure("provider_unconfigured")
            return {"status": "blocked", "reason": "provider_unconfigured"}
        if self._store is None or self.db is None:
            return {"status": "blocked", "reason": "provider_unavailable"}
        remaining = await self._reserve_remaining()
        buffer_max = self._buffer_max()
        # Пол партии: при buffer_max < batch_length одна партия всё же
        # помещается (иначе запас нечем заполнить); bound = max(...).
        limit_max = max(buffer_max, self._batch_length())
        if not force:
            if remaining >= limit_max:
                return {"status": "skipped", "reason": "buffer_full",
                        "remaining": remaining}
            if remaining >= self._low_watermark():
                return {"status": "skipped", "reason": "watermark_ok",
                        "remaining": remaining}
        if remaining > 0 and remaining + self._batch_length() > limit_max:
            return {"status": "skipped", "reason": "buffer_full",
                    "remaining": remaining}
        from services.task_supervisor import (QueueFullError, TaskJobStore,
                                              get_task_supervisor)
        supervisor = get_task_supervisor()
        job_store = TaskJobStore(self.db)
        coalesce = f"random.refill:{self._account_key()}"
        try:
            # kind="refill" (D2): TaskSupervisor трактует его как
            # второстепенный класс — при переполнении bounded-очереди job
            # отклоняется с видимой причиной `queue_full` (singleflight
            # coalesce_key защищает от дублей; следующий draw/старт повторит).
            record = await supervisor.run(
                lambda: self._do_refill(key), owner="random.source",
                kind="refill", coalesce_key=coalesce,
                job_store=job_store)
        except QueueFullError:
            logger.info("[random_source] refill queue full — deferred | "
                        "account=%s", self._account_key())
            return {"status": "deferred", "reason": "queue_full"}
        except Exception as exc:
            logger.warning("[random_source] refill job failed | error=%s",
                           type(exc).__name__, exc_info=True)
            return {"status": "failed", "reason": "provider_unavailable"}
        return {"status": record.status, "job_id": record.job_id,
                "task_id": record.task_id, "reason": self._last_refill_reason}

    async def _do_refill(self, key: str) -> dict:
        try:
            batch = await self._fetch_batch(key, manual=False)
        except AnuError as exc:
            await self._record_quota_error(exc, manual=False)
            await self._mark_state_failure(exc.code,
                                           fingerprint=key_fingerprint(key))
            self._last_refill_reason = exc.code
            self._emit("random_batch", outcome=mca_events.OUTCOME_FAILED,
                       level=mca_events.LEVEL_WARN, reason_code=exc.code,
                       stage="receive", provider=PROVIDER_ANU,
                       error_json={"type": "AnuError", "code": exc.code,
                                   "retryable": exc.retryable,
                                   "sent": exc.sent})
            return {"ok": False, "reason": exc.code}
        await self._record_quota_result("success", manual=False)
        batch_id = await self._store.insert_batch(batch)
        self._last_refill_reason = None
        self._emit("random_batch", outcome=mca_events.OUTCOME_SUCCESS,
                   reason_code=None, stage="receive",
                   provider=PROVIDER_ANU,
                   entity_ids={"batch_id": batch_id},
                   duration_ms=batch.latency_ms)
        state = await self._read_state()
        fingerprint = key_fingerprint(key)
        if (state is None or not state.get("activated_at")
                or state.get("key_fingerprint") != fingerprint):
            # первая валидная партия с этим ключом — активация через self-check
            await self._confirm_activation(batch_id)
        else:
            await self._store.write_state(
                last_fallback_reason=None, last_fallback_at=None)
            self._note_quantum_success()
        await self._prune_bounded()
        return {"ok": True, "batch_id": batch_id, "length": len(batch.values)}

    async def _prune_bounded(self) -> None:
        if self._store is None:
            return
        try:
            await self._store.prune(
                retention_days=mca_gates.random_draw_retention_days(),
                max_rows=mca_gates.random_draw_max_rows())
        except Exception:
            logger.warning("[random_source] prune failed", exc_info=True)

    async def startup(self) -> dict:
        """Один refill/активация при старте (K1/K2 ON, key_present):
        state unverified/новый ключ → активация; active + запас < watermark →
        обычный refill; иначе no-op. Fail-open (ошибка не роняет старт)."""
        try:
            if not mca_gates.random_source_enabled() or \
                    not mca_gates.random_quantum_enabled():
                return {"status": "disabled"}
            if not self._resolve_key():
                await self._mark_state_failure("provider_unconfigured")
                return {"status": "blocked",
                        "reason": "provider_unconfigured"}
            state = await self._read_state()
            fingerprint = key_fingerprint(self._resolve_key())
            active = bool(state and state.get("activated_at")
                          and state.get("key_fingerprint") == fingerprint)
            remaining = await self._reserve_remaining()
            if not active:
                result = await self.activate(manual=False)
                return {"status": "activated" if result.get("activated")
                        else "blocked",
                        "reason": result.get("blocker"),
                        "state": result.get("state")}
            if remaining < self._low_watermark():
                result = await self.refill_if_needed()
                return {"status": result.get("status"),
                        "reason": result.get("reason")}
            return {"status": "ok", "remaining": remaining}
        except Exception:
            logger.warning("[random_source] startup failed — fail-open",
                           exc_info=True)
            return {"status": "error", "reason": "provider_unavailable"}

    # ── статус/видимость (контракт для блоков D/mca-17c) ───────────────────
    async def anu_state(self) -> str:
        if not mca_gates.random_source_enabled() or \
                not mca_gates.random_quantum_enabled():
            return ANU_STATE_DISABLED
        key = self._resolve_key()
        if not key:
            return ANU_STATE_UNCONFIGURED
        state = await self._read_state()
        if (state is None or not state.get("activated_at")
                or state.get("key_fingerprint") != key_fingerprint(key)):
            return ANU_STATE_UNVERIFIED
        reason = str(state.get("last_fallback_reason") or "")
        if reason == "quota_exhausted":
            return ANU_STATE_QUOTA
        if reason in _DEGRADED_REASONS:
            return ANU_STATE_DEGRADED
        return ANU_STATE_ACTIVE

    async def status_snapshot(self, chat_id=None) -> dict:
        """R17-safe статус (без ключа/сырого текста): selected/effective,
        состояние ANU, запас, последнее пополнение, счётчики, fallback."""
        selected = await self.selected_mode(chat_id)
        effective, blocker = await self.resolve_effective(chat_id)
        state = await self._read_state() or {}
        last_batch = None
        stats = {"quantum": 0, "pseudorandom": 0}
        quota = None
        if self._store is not None:
            try:
                last_batch = await self._store.last_batch_info()
                stats = await self._store.journal_stats()
                quota = await self._store.quota_get(
                    account_key=self._account_key())
            except Exception:
                pass
        return {
            "selected_source": selected,
            "effective_source": effective,
            "fallback_reason": blocker,
            "anu_state": await self.anu_state(),
            "key_present": bool(self._resolve_key()),
            "key_fingerprint": state.get("key_fingerprint"),
            "reserve_remaining": await self._reserve_remaining(),
            "buffer_max": self._buffer_max(),
            "low_watermark": self._low_watermark(),
            "last_batch": last_batch,
            "draws": stats,
            "quota": quota,
            "last_fallback_reason": state.get("last_fallback_reason"),
            "last_fallback_at": state.get("last_fallback_at"),
            "activated_at": state.get("activated_at"),
            "plan": self._plan(),
            "policy_version": POLICY_VERSION,
            "source_impl": SOURCE_IMPL_PRNG,
            "python_version": platform.python_version(),
        }

    async def quota_snapshot(self) -> dict:
        """Квота ANU (глобальная, не per-chat): локальный учёт; точный остаток
        — только при авторитетных данных, иначе честная «оценка».

        Period-aware (F-1): если durable-строка относится к прошлому периоду,
        снимок показывает нулевые счётчики текущего периода (read-only, без
        записи) — «оценка» не залипает на исчерпании прошлого месяца."""
        plan = self._plan()
        period = _utc_period()
        row = None
        if self._store is not None:
            try:
                row = await self._store.quota_get(
                    account_key=self._account_key())
            except Exception:
                row = None
        row = row or {}
        stale = str(row.get("period") or "") != period
        success = 0 if stale else int(row.get("success") or 0)
        failed = 0 if stale else int(row.get("failed") or 0)
        unknown = 0 if stale else int(row.get("unknown") or 0)
        manual = 0 if stale else int(row.get("manual_checks") or 0)
        used = success + failed + unknown + manual
        limit = (mca_gates.random_anu_trial_monthly_limit()
                 if plan == "Trial" else None)
        remaining = (max(0, int(limit) - used)
                     if limit is not None else None)
        return {
            "account_key": self._account_key(),
            "period": period,
            "plan": plan,
            "success": success, "failed": failed, "unknown": unknown,
            "manual_checks": manual, "used": used,
            "limit": limit, "remaining": remaining,
            "estimate": True,     # авторитетных данных провайдера нет
            "last_success_at": None if stale else row.get("last_success_at"),
            "last_failure_at": None if stale else row.get("last_failure_at"),
            "last_reason": None if stale else row.get("last_reason"),
        }

    async def recent_draws(self, *, limit: int = 20,
                           chat_id: int | None = None) -> list[dict]:
        """Журнал draw (R17-safe: числа/ID/коды, без сырого текста)."""
        if self._store is None:
            return []
        try:
            return await self._store.recent_draws(limit=limit,
                                                  chat_id=chat_id)
        except Exception:
            return []

    # ── стык mca-06 (D7): async-фабрика + sync pick ────────────────────────
    async def build_dream_source(self, pipeline_run_id: int | None,
                                 *, k_hint: int = 10, chat_id=None):
        """K1 ON: core-адаптер с durably зарезервированным bounded chunk;
        fallback OFF + пусто → None (mca-06-семантика: ранжированный путь)."""
        await self.flush_journal()
        selected = await self.selected_mode(chat_id)
        if selected == MODE_PSEUDORANDOM:
            return CoreDreamRandomSource(
                pipeline_run_id=pipeline_run_id, chat_id=chat_id,
                source=MODE_PSEUDORANDOM, provider=PROVIDER_PRNG,
                journal_sink=self._enqueue_journal)
        if not mca_gates.random_quantum_enabled():
            return await self._dream_fallback(pipeline_run_id, chat_id,
                                              "disabled")
        chunk_size = min(max(2 * int(k_hint) + 4, DREAM_CHUNK_MIN),
                         DREAM_CHUNK_MAX)
        if self._store is not None:
            try:
                chunk = await self._store.reserve_chunk(chunk_size)
            except Exception:
                logger.warning("[random_source] dream reserve failed",
                               exc_info=True)
                chunk = []
            if chunk:
                first = chunk[0]
                return CoreDreamRandomSource(
                    pipeline_run_id=pipeline_run_id, chat_id=chat_id,
                    source=MODE_QUANTUM, provider=first.provider,
                    batch_id=first.batch_id, data_type=first.data_type,
                    values=[c.value for c in chunk],
                    draw_ids=[c.draw_id for c in chunk],
                    journal_sink=self._enqueue_journal)
        blocker = await self._provider_blocker()
        if self._auto_refill:
            self._schedule_refill()
        return await self._dream_fallback(pipeline_run_id, chat_id, blocker)

    async def _dream_fallback(self, pipeline_run_id, chat_id, blocker):
        if await self.fallback_enabled(chat_id):
            self._note_transition(key=f"prng:{blocker}", reason=blocker)
            await self._mark_fallback(blocker)
            return CoreDreamRandomSource(
                pipeline_run_id=pipeline_run_id, chat_id=chat_id,
                source=MODE_PSEUDORANDOM, provider=PROVIDER_PRNG,
                fallback=True, fallback_reason=blocker,
                journal_sink=self._enqueue_journal)
        self._note_transition(key=f"defer:{blocker}", reason=blocker,
                              deferred=True)
        return None

    def _schedule_refill(self) -> None:
        if not (mca_gates.random_source_enabled()
                and mca_gates.random_quantum_enabled()
                and mca_gates.random_refill_enabled()):
            return
        if self._store is None or self.db is None:
            return
        if self._refill_task is not None and not self._refill_task.done():
            return
        if not self._resolve_key():
            return

        async def _runner():
            try:
                await self.refill_if_needed()
            except Exception:
                logger.warning("[random_source] background refill failed",
                               exc_info=True)

        try:
            self._refill_task = asyncio.create_task(_runner())
        except RuntimeError:       # нет running loop (sync-контекст)
            self._refill_task = None


# ── модульный синглтон + точки входа ────────────────────────────────────────
_service: RandomSourceService | None = None


def get_service(db=None) -> RandomSourceService:
    global _service
    if _service is None:
        _service = RandomSourceService(db)
    elif db is not None and _service.db is None:
        _service.bind_db(db)
    return _service


def bind_db(db) -> RandomSourceService:
    return get_service(db)


def reset_service() -> None:
    """Сброс синглтона (тесты)."""
    global _service
    _service = None


async def startup() -> dict:
    """Точка входа старта бота (fail-open; K1/K2 OFF → no-op)."""
    return await get_service().startup()


async def for_dream(pipeline_run_id: int | None, *, k_hint: int = 10,
                    chat_id=None):
    """Async-фабрика стыка mca-06 (D7). K1 OFF → ровно `default_source`
    (бит-в-бит 2.58.57); ошибка контура → детерминированный default."""
    try:
        if not mca_gates.random_source_enabled():
            return mca_dream_random.default_source(pipeline_run_id)
        return await get_service().build_dream_source(
            pipeline_run_id, k_hint=k_hint, chat_id=chat_id)
    except Exception:
        logger.warning("[random_source] for_dream failed — deterministic "
                       "default", exc_info=True)
        return mca_dream_random.default_source(pipeline_run_id)
