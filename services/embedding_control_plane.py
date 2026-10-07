"""ASAP-4 волна A (T-4402…T-4411) — Embedding Control Plane.

Spec: `plans/features/asap-4-embedding-graphrag-cover-runtime/spec.md` §1
(зона A), ADR-1028-7 D1/AM-1/D2. Прод-основание: 21-аттемпный каскад
(`3×(3+2+2)`, prod-facts Q2/Q3), Retry-After капился 8s (Q4), keys одной
quota-группы бомбились по очереди (Q1/Q10), два full-rebuild стартовали в
одну секунду (Q6).

Контракты (всё env-only, default ON, OFF = бит-в-бит legacy):

* **Credential pool списком** (§4/§12, T-4402): primary
  (`keys.embedding_api_key`) + fallback_1/2 (`EMBEDDING_FALLBACK_API_KEY[2]`)
  + добавочные entries из `EMBEDDING_EXTRA_API_KEYS` (запятая/`;`). Никаких
  `..._API_KEY_3` и правок кода для четвёртого ключа.
* **Лестница quota group** (§5): provider/runtime metadata (если доступна) →
  connection metadata (developer label `EMBEDDING_QUOTA_GROUP_LABELS` /
  hot `keys.embedding_quota_group_labels`, формат `alias:group[,…]`) →
  `unknown`. Вычислять project из значения ключа ЗАПРЕЩЕНО (§5).
  **Safe default: все `unknown` — ОДНА общая группа** (прод-факт Q1: одна
  endpoint-точка; перебор ключей одной группы усиливает burst).
* **Key health** (§11): `healthy/cooldown/auth_failed/quota_exhausted/
  provider_unavailable/disabled`; 401/403 → `auth_failed` БЕЗ ретраев как
  429; auth-fail одного credential не отключает другие группы.
* **429 = scheduling signal** (§8): классификация RPM/TPM/daily/spend/unknown
  по status + Retry-After + безопасным полям тела (kind-коды, без содержимого
  запроса). Retry-After уважается: `min(provider_value, CEILING=300s)` —
  НЕ `min(30, 8)` (§9). Transport backoff остаётся только транспортом.
* **Quota-group cooldown** (§10): project-level 429 → `cooling_down` /
  `exhausted` + `next_allowed_at` (SQLite `embedding_quota_state`, v23);
  keys той же группы НЕ дёргаются другим ключом до истечения. Независимая
  группа (явный label) продолжает работать (§65).
* **EmbeddingExecutor** (§6/§7, T-4403): единственный владелец retry —
  attempt budget ≤4 логических попыток (1 начальная + ≤3 только на
  retryable: transport 5xx/timeout; 429 — перенос по `next_allowed_at`, НЕ
  «лобовая» попытка). Нижние слои — transport retry ≤1 (LLMClient.embed_once,
  retry_statuses=()). Ceiling логических HTTP-вызовов фиксируется тестом
  (fixture §64: не 21).
* **Priority scheduler** (§17–§21, T-4406): P0 query → P1 live write →
  P2 repair → P3 full rebuild; adaptive token-bucket reserve (P0/P1
  гарантированный bucket, P3 только surplus); AIMD concurrency (cold=1,
  success streak → +1, 429 → ÷2, group cooldown → 0) в developer bounds
  `EMBED_CONCURRENCY_MIN/MAX`; adaptive batch size (старт 32–50, границы
  env); burst pressure (RA ≤ 60s при concurrency=1 → ждать) ≠ quota
  unavailable (daily/spend или RA > 60s → group `exhausted`).
* **Provider-agnostic adapter** (§13–§16, T-4405): поверх существующего
  LLMClient (сеть/клиенты переиспользуются); `gemini-embedding-001` —
  input ≤ 2048 token/item, lossless сегментация со stable parent ref,
  silent truncation запрещён (§14); авто-переход на `-2` запрещён (§15);
  async Batch API — gated `EMBED_ASYNC_BATCH_ENABLED` (default OFF), не
  включается без live-верификации контракта.
* **Multi-worker lease** (§22/§23, T-4407): shared full-rebuild permit через
  существующую `task_jobs` + `write_transaction` (Redis запрещён): ≤1 active
  full-rebuild на deployment; `graph_facts_vec` и `smart_archive` не
  открывают quota-race; при конкуренции первым идёт меньший/застрявший.
* R17: ключи НИКОГДА не логируются — только алиасы/credential_id.

Δ SQLite DDL = v22→v23 additive (`embedding_quota_state` + 3 nullable
колонки реестра поколений — services/database.py); PG — no-op.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)

# ── Kill-switches (spec §8.2; env-only, default ON; OFF = бит-в-бит) ────────


def _flag(name: str, default: bool = True) -> bool:
    """Флаг из settings (env-only). Любая ошибка → default (fail-open ON:
    OFF-ветка проверяется тестами паритета явно)."""
    try:
        from config.settings import settings
        return bool(getattr(settings, name, default))
    except Exception:      # pragma: no cover — защитная ветка
        return default


def control_plane_enabled() -> bool:
    """Мастер-флаг зоны A. OFF → прежний embed-каскад llm_client +
    summary_memory (21-аттемпный) и прежний lifecycle rebuild."""
    return _flag("EMBED_CONTROL_PLANE_ENABLED", True)


def quota_group_cooldown_enabled() -> bool:
    """OFF → нет group cooldown (перебор ключей как сейчас)."""
    return _flag("EMBED_QUOTA_GROUP_COOLDOWN_ENABLED", True)


def quota_kind_parking_enabled() -> bool:
    """D1 (T-4503): OFF → kind не влияет на длительность паузы
    (`retry_after_seconds()` как в 2.58.45 — дефолт 20s для spend/daily без
    Retry-After, note/log прежнего формата)."""
    return _flag("EMBED_QUOTA_KIND_PARKING_ENABLED", True)


def resume_backoff_enabled() -> bool:
    """D2 (T-4503): OFF → задержки resume без нелинейности (дефолт-кулдаун
    как сейчас). Читается graphrag_rebuild'ом."""
    return _flag("EMBED_RESUME_BACKOFF_ENABLED", True)


def priority_scheduler_enabled() -> bool:
    """OFF → rebuild без приоритетов/reserve (как сейчас)."""
    return _flag("EMBED_PRIORITY_SCHEDULER_ENABLED", True)


def adaptive_concurrency_enabled() -> bool:
    """OFF → статические GRAPHRAG_REBUILD_BATCH/SLEEP (как сейчас)."""
    return _flag("EMBED_ADAPTIVE_CONCURRENCY_ENABLED", True)


def async_batch_enabled() -> bool:
    """ЕДИНСТВЕННЫЙ default-OFF флаг эпика (spec §8.2). Async Batch API не
    включается без live-верификации контракта (§16)."""
    return _flag("EMBED_ASYNC_BATCH_ENABLED", False)


# ── Приоритеты (§17) ────────────────────────────────────────────────────────


class Priority(IntEnum):
    P0_QUERY = 0       # online retrieval (query embed)
    P1_WRITE = 1       # live write / new fact
    P2_REPAIR = 2      # small repair / backfill / probe
    P3_REBUILD = 3     # full rebuild


# ── Модель credentials и quota groups (T-4402, spec A.1) ────────────────────

HEALTH_HEALTHY = "healthy"
HEALTH_COOLDOWN = "cooldown"
HEALTH_AUTH_FAILED = "auth_failed"
HEALTH_QUOTA_EXHAUSTED = "quota_exhausted"
HEALTH_PROVIDER_UNAVAILABLE = "provider_unavailable"
HEALTH_DISABLED = "disabled"
CREDENTIAL_HEALTH_STATES = frozenset({
    HEALTH_HEALTHY, HEALTH_COOLDOWN, HEALTH_AUTH_FAILED,
    HEALTH_QUOTA_EXHAUSTED, HEALTH_PROVIDER_UNAVAILABLE, HEALTH_DISABLED,
})

GROUP_HEALTHY = "healthy"
GROUP_COOLING = "cooling_down"
GROUP_EXHAUSTED = "exhausted"
GROUP_UNKNOWN = "unknown"

# unknown-группа: safe default — ВСЕ unknown credentials в ОДНОЙ группе
# (прод-факт Q1). Разделение — только явным developer label'ом (§5).
UNKNOWN_GROUP_ID = "unknown"


@dataclass(frozen=True)
class EmbeddingCredential:
    """Conf spec A.1. Ключ ХРАНИТСЯ только в памяти процесса (конфиг — не
    БД); наружу (логи/UI/события) идёт только `alias` (R17)."""
    alias: str
    api_key: str
    base_url: str
    model: str
    provider: str
    quota_group_id: str        # ladder §5: label или UNKNOWN_GROUP_ID
    quota_group_known: bool    # False → «Проект/квота: не определены» (UI)

    @property
    def credential_id(self) -> str:
        return self.alias


@dataclass
class EmbeddingQuotaGroup:
    """Conf spec A.1: state(healthy|cooling_down|exhausted|unknown),
    next_allowed_at, note."""
    quota_group_id: str
    state: str = GROUP_HEALTHY
    next_allowed_at: int = 0
    note: str = ""
    updated_at: int = 0


_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}:[A-Za-z0-9_.:-]{1,64}$")


def _settings_value(name: str, default):
    try:
        from config.settings import settings
        return getattr(settings, name, default)
    except Exception:      # pragma: no cover
        return default


def _hot_get(key: str, default):
    try:
        from services import hot_config
        return hot_config.get(key, default)
    except Exception:      # pragma: no cover
        return default


def parse_quota_group_labels(raw) -> dict[str, str]:
    """Developer label'ы (лестница §5 шаг 3): 'primary:g1, fallback_2:g2' →
    {alias: group}. Мусорные пары молча отбрасываются (config не роняет
    embed-путь); значения group не секретны, но в логи идут только counts."""
    labels: dict[str, str] = {}
    if isinstance(raw, dict):
        items = list(raw.items())
    else:
        text = str(raw or "").strip()
        if not text:
            return labels
        items = []
        for chunk in re.split(r"[;,]", text):
            chunk = chunk.strip()
            if not chunk or ":" not in chunk:
                continue
            alias, _, group = chunk.partition(":")
            items.append((alias.strip(), group.strip()))
    for alias, group in items:
        alias, group = str(alias).strip(), str(group).strip()
        if alias and group and _LABEL_PATTERN.match(f"{alias}:{group}"):
            labels[alias] = group
    return labels


def resolve_quota_group(alias: str, labels: dict[str, str]) -> tuple[str, bool]:
    """Лестница §5: (1) provider/runtime metadata — в текущем рантайме
    machine-readable project metadata недоступна (прод-факт Q1/Q8) → шаг
    пропускается; (2) connection metadata / developer label; (4) unknown →
    ОДНА общая группа (safe default). Вычисление project из значения ключа
    запрещено (§5) — ключ в резолве не участвует."""
    group = labels.get(alias)
    if group:
        return group, True
    return UNKNOWN_GROUP_ID, False


def _provider_of(base_url: str) -> str:
    """Provider-identity по host endpoint'а (REUSE семантики
    summary_memory._embedding_provider)."""
    try:
        from urllib.parse import urlsplit
        host = urlsplit(str(base_url or "")).hostname
        return host or "openai-compatible"
    except Exception:      # pragma: no cover
        return "openai-compatible"


def _is_gemini_endpoint(base_url: str) -> bool:
    host = _provider_of(base_url)
    return "generativelanguage" in host or "googleapis" in host


def build_credential_pool() -> list[EmbeddingCredential]:
    """Credential pool СПИСКОМ из существующей конфигурации (§4/§12).

    Entries: primary (hot `keys.embedding_api_key` → env
    `EMBEDDING_API_KEY`), fallback_1/fallback_2 (legacy env), затем
    добавочные из `EMBEDDING_EXTRA_API_KEYS` (запятая/`;`) — произвольный
    пул без правок кода. Ключи никогда не логируются (R17)."""
    labels = parse_quota_group_labels(_hot_get(
        "keys.embedding_quota_group_labels",
        _settings_value("EMBEDDING_QUOTA_GROUP_LABELS", "")))
    pool: list[EmbeddingCredential] = []
    base_url = str(_hot_get(
        "models.embedding_base_url",
        _settings_value("EMBEDDING_BASE_URL", "")) or "").strip()
    model = str(_hot_get(
        "models.embedding_model_name",
        _settings_value("EMBEDDING_MODEL_NAME", "")) or "").strip()
    provider = _provider_of(base_url)
    primary = str(_hot_get("keys.embedding_api_key",
                           _settings_value("EMBEDDING_API_KEY", "")) or "").strip()
    entries: list[tuple[str, str]] = []
    if primary:
        entries.append(("primary", primary))
    fb1 = str(_hot_get("keys.embedding_fallback_api_key",
                       _settings_value("EMBEDDING_FALLBACK_API_KEY", "")) or "").strip()
    fb2 = str(_hot_get("keys.embedding_fallback_api_key_2",
                       _settings_value("EMBEDDING_FALLBACK_API_KEY_2", "")) or "").strip()
    if fb1:
        entries.append(("fallback_1", fb1))
    if fb2:
        entries.append(("fallback_2", fb2))
    extra_raw = str(_hot_get("keys.embedding_extra_api_keys",
                             _settings_value("EMBEDDING_EXTRA_API_KEYS", "")) or "")
    for idx, key in enumerate(re.split(r"[;,]", extra_raw)):
        key = key.strip()
        if key:
            entries.append((f"extra_{idx + 1}", key))
    for alias, key in entries:
        group, known = resolve_quota_group(alias, labels)
        pool.append(EmbeddingCredential(
            alias=alias, api_key=key, base_url=base_url, model=model,
            provider=provider, quota_group_id=group,
            quota_group_known=known))
    return pool


# ── D3 (T-4503): честная диагностика «распределять некуда» ──────────────────

_ROTATION_HINT_RU = ("Задайте EMBEDDING_QUOTA_GROUP_LABELS или hot-ключ "
                     "keys.embedding_quota_group_labels (формат alias:group,...); "
                     "подхватывается без рестарта")
_ROTATION_WARN_COOLDOWN_S = 600.0
_last_rotation_warn = 0.0        # monotonic; in-memory rate-limit WARN


def pool_rotation_diagnosis(pool: list[EmbeddingCredential]) -> dict:
    """D3: чистый диагноз распределения пула (R17-safe: только счётчики/
    group-id). `degenerate` = группы не известны ИЛИ |groups| == 1 →
    распределять некуда (safe default «все ключи = одна группа» не выдаётся
    за ротацию)."""
    groups = sorted({c.quota_group_id for c in pool})
    known = any(c.quota_group_known for c in pool)
    degenerate = (not known) or len(groups) <= 1
    return {"keys": len(pool), "groups": groups, "known": known,
            "degenerate": degenerate}


def _maybe_warn_degenerate_rotation(diagnosis: dict) -> bool:
    """D3: WARN `embedding pool rotation=none | ...` — не чаще 1 раза /
    10 мин (in-memory rate-limit; под мастер-флагом зоны, D5). True —
    залогировано. Возврат значения — для тестов."""
    global _last_rotation_warn
    if not diagnosis or not diagnosis.get("degenerate"):
        return False
    if not int(diagnosis.get("keys") or 0):
        return False                      # пустой пул — не про ротацию
    if not control_plane_enabled():
        return False
    now = time.monotonic()
    if now - _last_rotation_warn < _ROTATION_WARN_COOLDOWN_S:
        return False
    _last_rotation_warn = now
    groups = ",".join(str(g) for g in diagnosis.get("groups") or []) or "unknown"
    logger.warning(
        "embedding pool rotation=none | group=%s | keys=%d | "
        "hint=EMBEDDING_QUOTA_GROUP_LABELS",
        groups, int(diagnosis["keys"]))
    return True


def _rotation_panel_block(diagnosis: dict) -> dict:
    """D3-контракт панели: `rotation: none | grouped` + hint. R17-safe
    (alias/счётчики; group-id — не секрет)."""
    degenerate = bool(diagnosis.get("degenerate"))
    return {
        "status": "none" if degenerate else "grouped",
        "keys": int(diagnosis.get("keys") or 0),
        "groups": [str(g) for g in (diagnosis.get("groups") or [])],
        "degenerate": degenerate,
        "hint": _ROTATION_HINT_RU if degenerate else "",
    }


# ── 429 classification (T-4404, §8/§9) ──────────────────────────────────────

RATE_RPM = "rpm"
RATE_TPM = "tpm"
RATE_DAILY = "daily_project"
RATE_SPEND = "spend"
RATE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class RateLimitInfo:
    kind: str                    # RATE_* (классификация §8)
    retry_after_s: float | None  # provider-declared delay (сек)
    quota_metric: str = ""       # безопасный код из тела (не содержимое)


# Безопасные маркеры тела 429 (kind-коды провайдера, НЕ содержимое запроса).
_TPM_MARKERS = ("tokens per minute", "tpm", "token_per_minute")
_RPM_MARKERS = ("requests per minute", "per minute", "rpm")
_DAILY_MARKERS = ("per day", "daily", "rpd", "requests_per_day")
_SPEND_MARKERS = ("billing", "spend", "budget", "balance")


def _parse_retry_after(headers) -> float | None:
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except Exception:
        return None
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def classify_rate_limit(status: int, headers=None, body: str | None = None
                        ) -> RateLimitInfo:
    """§8: 429 = scheduling signal. Классификация по status + Retry-After +
    безопасным маркерам тела. Тело сканируется на kind-маркеры, НЕ на
    содержимое запроса; в логи идёт только kind/метрика."""
    retry_after = _parse_retry_after(headers)
    text = (body or "").lower()[:2000]
    metric = ""
    kind = RATE_UNKNOWN
    for marker in _SPEND_MARKERS:
        if marker in text:
            kind, metric = RATE_SPEND, marker
            break
    if kind == RATE_UNKNOWN:
        for marker in _DAILY_MARKERS:
            if marker in text:
                kind, metric = RATE_DAILY, marker
                break
    if kind == RATE_UNKNOWN:
        for marker in _TPM_MARKERS:
            if marker in text:
                kind, metric = RATE_TPM, marker
                break
    if kind == RATE_UNKNOWN:
        for marker in _RPM_MARKERS:
            if marker in text:
                kind, metric = RATE_RPM, marker
                break
    return RateLimitInfo(kind=kind, retry_after_s=retry_after,
                         quota_metric=metric)


def retry_after_seconds(info: RateLimitInfo) -> float:
    """§9: честный Retry-After — `min(provider_value, HARD_CEILING=300s)`.
    Нет provider-значения → developer bound
    `EMBED_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS` (прод-факт Q4: Gemini часто
    не отдаёт header — дефолт-кулдаун вместо 0)."""
    ceiling = float(_settings_value("EMBED_RETRY_AFTER_CEILING_SECONDS", 300.0))
    if info.retry_after_s is not None:
        return max(0.0, min(float(info.retry_after_s), ceiling))
    return float(_settings_value(
        "EMBED_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS", 20.0))


def _utc_day_end(now: float | None = None) -> int:
    """Конец текущих суток UTC (следующий UTC-midnight, epoch-секунды)."""
    ts = int(now if now is not None else time.time())
    return ((ts // 86400) + 1) * 86400


def _quota_parking_seconds(info: RateLimitInfo) -> tuple[float, bool, str]:
    """D1 (T-4503, design-fix): kind-aware длительность quota-паузы.

    Возвращает `(delay_s, parked, est)`:
    * kind spend/daily + есть Retry-After → `retry_after_seconds()` (RA с
      ceiling 300s, AM-1-политика уважения провайдера сохранена) — `parked=0`;
    * kind spend/daily + RA нет (прод-кейс Gemini) → парковка до ОЦЕНКИ
      reset: конец текущих суток UTC + `EMBED_QUOTA_RESET_MARGIN_SECONDS`
      (default 300s), `est='utc_day_end'`. Env-оверрайд
      `EMBED_QUOTA_RESET_HORIZON_SECONDS` > 0 → фиксированный горизонт
      (`est='horizon'`, если владельцу эмпирически известен реальный reset —
      у Gemini он не UTC-midnight, честно это не asserting). Верхний cap
      `EMBED_QUOTA_PARK_MAX_SECONDS` (default 86400);
    * rpm/tpm/rate/unknown — прежняя семантика `retry_after_seconds()`
      (RA-capped 300s / default 20s), `parked=0`.

    Kill-switch `EMBED_QUOTA_KIND_PARKING_ENABLED=OFF` → kind не влияет на
    длительность: `retry_after_seconds()` для всех kinds (бит-в-бит 2.58.45).
    """
    if not quota_kind_parking_enabled():
        return retry_after_seconds(info), False, ""
    if info.kind in (RATE_SPEND, RATE_DAILY):
        if info.retry_after_s is not None:
            # RA присутствует у spend/daily (нетипично): провайдер точнее
            # нашей эвристики — уважается RA, парковка НЕ применяется.
            return retry_after_seconds(info), False, ""
        now = time.time()
        cap = max(1.0, float(_settings_value(
            "EMBED_QUOTA_PARK_MAX_SECONDS", 86400.0)))
        horizon = float(_settings_value(
            "EMBED_QUOTA_RESET_HORIZON_SECONDS", 0.0) or 0.0)
        if horizon > 0:
            delay, est = horizon, "horizon"
        else:
            margin = max(0.0, float(_settings_value(
                "EMBED_QUOTA_RESET_MARGIN_SECONDS", 300.0)))
            delay = (_utc_day_end(now) + margin) - now
            est = "utc_day_end"
        return max(0.0, min(delay, cap)), True, est
    return retry_after_seconds(info), False, ""


def is_quota_unavailable(info: RateLimitInfo, concurrency: int) -> bool:
    """§21: burst pressure ≠ quota unavailable. Burst = 429 с RA ≤ 60s при
    concurrency=1 (просто ждать). Quota unavailable: daily/spend-класс или
    RA > 60s — не лечится concurrency → group `exhausted`."""
    ceiling = float(_settings_value("EMBED_BURST_PRESSURE_MAX_RA_SECONDS", 60.0))
    if info.kind in (RATE_DAILY, RATE_SPEND):
        return True
    ra = info.retry_after_s
    if ra is not None and ra > ceiling:
        return True
    if ra is None and info.kind in (RATE_TPM, RATE_UNKNOWN):
        # Нет header и нет kind-маркера — консервативно burst (дефолт-кулдаун
        # короче минуты); concurrency=1 + повтор → следующий 429 классифицируется
        # снова. Прод-факт Q4: Gemini 429 обычно без RA — фиксация exhausted
        # на 20с-дефолте была бы ложной.
        return False
    return False


# ── Registry: quota groups (SQLite v23) + credential health (in-memory) ─────


class QuotaGroupRegistry:
    """Runtime-состояние quota-групп (spec A.1 DDL: SQLite
    `embedding_quota_state`, v23) + in-memory health credentials.

    DB — coordination между рестартами/процессами; in-memory — горячий путь
    (без чтения БД на каждый embed). Fail-open: ошибки БД не роняют embed
    (WARNING, работает in-memory состояние)."""

    def __init__(self) -> None:
        self._groups: dict[str, EmbeddingQuotaGroup] = {}
        self._cred_health: dict[str, tuple[str, float]] = {}
        self._rate_events: list[float] = []          # 429-метки (окно 10 мин)
        self._db: object | None = None

    def reset_runtime(self) -> None:
        """Сброс in-memory состояния (тесты/переконфигурация); DB-сторона
        не трогается."""
        self._groups.clear()
        self._cred_health.clear()
        self._rate_events.clear()

    def bind_db(self, db) -> None:
        self._db = db

    # ── credential health (in-memory; §11) ──

    def credential_health(self, alias: str) -> str:
        state, until = self._cred_health.get(alias, (HEALTH_HEALTHY, 0.0))
        if state == HEALTH_COOLDOWN and until and time.time() >= until:
            return HEALTH_HEALTHY
        return state

    def mark_credential(self, alias: str, state: str,
                        cooldown_s: float = 0.0) -> None:
        if state not in CREDENTIAL_HEALTH_STATES:
            return
        self._cred_health[alias] = (
            state, time.time() + max(0.0, cooldown_s) if state == HEALTH_COOLDOWN else 0.0)

    def usable_credentials(self, pool: list[EmbeddingCredential],
                           group_id: str) -> list[EmbeddingCredential]:
        """Healthy credentials группы (cooldown/auth_failed/disabled
        исключаются; 401/403 ≠ 429 — auth_failed без ретраев)."""
        return [c for c in pool
                if c.quota_group_id == group_id
                and self.credential_health(c.alias) == HEALTH_HEALTHY]

    # ── quota groups (§10; DB + mirror) ──

    def group_state(self, group_id: str) -> EmbeddingQuotaGroup:
        return self._groups.get(group_id) or EmbeddingQuotaGroup(
            quota_group_id=group_id)

    def group_blocked(self, group_id: str, now: int | None = None) -> bool:
        """True, если группа cooling_down/exhausted и next_allowed_at не
        истёк (тот же group не дёргается другим ключом — §10)."""
        if not quota_group_cooldown_enabled():
            return False
        group = self.group_state(group_id)
        if group.state in (GROUP_COOLING, GROUP_EXHAUSTED):
            now = int(time.time()) if now is None else now
            if group.next_allowed_at and now < group.next_allowed_at:
                return True
            # Окно истекло → авто-восстановление (fail-open healthy).
            self._set_group_local(group_id, GROUP_HEALTHY, 0,
                                  "cooldown_expired")
        return False

    def _set_group_local(self, group_id: str, state: str,
                         next_allowed_at: int, note: str) -> None:
        self._groups[group_id] = EmbeddingQuotaGroup(
            quota_group_id=group_id, state=state,
            next_allowed_at=int(next_allowed_at), note=note[:200],
            updated_at=int(time.time()))

    async def set_group_state(self, group_id: str, state: str,
                              next_allowed_at: int, note: str) -> None:
        """§10: `quota_group.state = cooling_down/exhausted`,
        `next_allowed_at = …` — в SQLite (v23) + in-memory mirror."""
        self._set_group_local(group_id, state, next_allowed_at, note)
        db = self._db
        if db is None:
            return
        try:
            now = int(time.time())

            async def _body(conn):
                await conn.execute(
                    "INSERT INTO embedding_quota_state (quota_group_id, "
                    "state, next_allowed_at, note, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(quota_group_id) DO "
                    "UPDATE SET state = excluded.state, next_allowed_at = "
                    "excluded.next_allowed_at, note = excluded.note, "
                    "updated_at = excluded.updated_at",
                    (group_id, state, int(next_allowed_at), note[:200], now))

            await db.write_transaction(_body, op_name="embed_quota_state")
        except Exception:
            logger.warning(
                "embed quota-state persist failed | group=%s | state=%s",
                group_id, state, exc_info=True)

    async def load_group_states(self) -> None:
        """Восстановление состояния групп из БД (restart during pause §68)."""
        db = self._db
        if db is None:
            return
        try:
            cursor = await db.db.execute(
                "SELECT quota_group_id, state, next_allowed_at, note, "
                "updated_at FROM embedding_quota_state")
            rows = await cursor.fetchall()
            for row in rows:
                state = str(row["state"] or GROUP_HEALTHY)
                if state not in (GROUP_COOLING, GROUP_EXHAUSTED,
                                 GROUP_UNKNOWN, GROUP_HEALTHY):
                    state = GROUP_UNKNOWN
                self._groups[str(row["quota_group_id"])] = EmbeddingQuotaGroup(
                    quota_group_id=str(row["quota_group_id"]), state=state,
                    next_allowed_at=int(row["next_allowed_at"] or 0),
                    note=str(row["note"] or ""),
                    updated_at=int(row["updated_at"] or 0))
        except Exception:
            logger.warning("embed quota-state load failed", exc_info=True)

    # ── 429-метрики (панель §32: «429 за 10 минут») ──

    def record_rate_limit(self) -> None:
        now = time.monotonic()
        self._rate_events.append(now)
        cutoff = now - 600.0
        self._rate_events = [t for t in self._rate_events if t >= cutoff]

    def rate_limits_last_10m(self) -> int:
        cutoff = time.monotonic() - 600.0
        return sum(1 for t in self._rate_events if t >= cutoff)


REGISTRY = QuotaGroupRegistry()


# ── AIMD concurrency + adaptive batch (T-4406, §19/§20) ─────────────────────


class AdaptiveController:
    """AIMD в developer bounds: cold start = CONCURRENCY_MIN; success streak
    → +1 (медленно); 429 → ÷2 (резко); group cooldown → 0 (pause)."""

    def __init__(self) -> None:
        self._limit: int | None = None       # None → ещё не инициализирован
        self._success_streak = 0
        self._batch: int | None = None
        self._batch_shrink_streak = 0

    @property
    def concurrency_limit(self) -> int:
        if not adaptive_concurrency_enabled():
            return max(1, int(_settings_value("EMBED_CONCURRENCY_MAX", 4)))
        if self._limit is None:
            self._limit = max(1, int(_settings_value("EMBED_CONCURRENCY_MIN", 1)))
        return self._limit

    def on_success(self) -> None:
        if not adaptive_concurrency_enabled():
            return
        self._success_streak += 1
        # «медленно»: +1 за стабильную серию (streak из 20 успешных батчей)
        if self._success_streak >= 20:
            self._success_streak = 0
            ceiling = max(1, int(_settings_value("EMBED_CONCURRENCY_MAX", 4)))
            self._limit = min(ceiling, self.concurrency_limit + 1)

    def on_rate_limit(self) -> None:
        if not adaptive_concurrency_enabled():
            return
        self._success_streak = 0
        floor = max(1, int(_settings_value("EMBED_CONCURRENCY_MIN", 1)))
        self._limit = max(floor, self.concurrency_limit // 2)

    def pause(self) -> None:
        """Group cooldown → 0 (полная пауза выдачи слотов)."""
        if not adaptive_concurrency_enabled():
            return
        self._limit = 0
        self._success_streak = 0

    def unpause(self) -> None:
        if self._limit == 0:
            self._limit = max(1, int(_settings_value("EMBED_CONCURRENCY_MIN", 1)))

    # ── batch size (§20) ──
    # Семантика: developer-конфиг `GRAPHRAG_REBUILD_BATCH` — СТАРТ и ПОТОЛОК
    # (старт 32–50 на проде — spec A.4); AIMD только сжимает батч при 429-
    # частоте (÷2, пол EMBED_BATCH_MIN) и медленно восстанавливает к
    # потолку на успешных батчах. Выше developer-значения не растём.

    @property
    def batch_size(self) -> int:
        static = max(1, int(_settings_value("GRAPHRAG_REBUILD_BATCH", 50)))
        if not adaptive_concurrency_enabled():
            return static
        if self._batch is None:
            hi = max(1, int(_settings_value("EMBED_BATCH_MAX", 50)))
            self._batch = min(static, hi)
        return self._batch

    def on_batch_success(self, size: int) -> None:
        if not adaptive_concurrency_enabled():
            return
        self._batch_shrink_streak = 0
        if self._batch is not None and size >= self._batch:
            static = max(1, int(_settings_value("GRAPHRAG_REBUILD_BATCH", 50)))
            self._batch = min(static, self._batch + 4)

    def on_batch_rate_limit(self) -> None:
        if not adaptive_concurrency_enabled():
            return
        # Floor AIMD не выше developer-конфига: static batch — старт и
        # потолок (см. batch_size), EMBED_BATCH_MIN не может поднять батч
        # выше сконфигурированного.
        static = max(1, int(_settings_value("GRAPHRAG_REBUILD_BATCH", 50)))
        lo = min(max(1, int(_settings_value("EMBED_BATCH_MIN", 8))), static)
        self._batch_shrink_streak += 1
        self._batch = max(lo, self.batch_size // 2)

    def reset(self) -> None:
        """Сброс AIMD-состояния (тесты/переконфигурация): следующий вызов
        пересеивает batch/concurrency из developer-конфига."""
        self._limit = None
        self._success_streak = 0
        self._batch = None
        self._batch_shrink_streak = 0

    def snapshot(self) -> dict:
        return {"concurrency_limit": self.concurrency_limit,
                "batch_size": self.batch_size}


CONTROLLER = AdaptiveController()


# ── Priority scheduler: permits c reserve (T-4406, §17/§18) ─────────────────


class _Permit:
    def __init__(self, priority: Priority) -> None:
        self.priority = priority
        self.released = False


class PriorityScheduler:
    """Выдача слотов concurrency с adaptive reserve (§17/§18): P0–P1 имеют
    гарантированный bucket (адмитятся при любом свободном слоте); P3 (full
    rebuild) потребляет только surplus — адмитится когда capacity свободна
    И нет ожидающих/активных P0–P2 (idle-capacity). Приход P0/P1 мгновенно
    замораживает выдачу новых P3-слотов (preemption на границе слотов);
    group cooldown блокирует приоритеты одинаково через `group_blocked` —
    429 на P0/P1 → P3 не адмитится до next_allowed_at (§18). Без магических
    процентов: reserve выражен семантикой приоритета, не долей лимита.
    Scheduler OFF → один статический лимит для всех (как сейчас)."""

    def __init__(self) -> None:
        self._active_high = 0        # P0–P2
        self._active_p3 = 0          # P3 (full rebuild)
        self._waiting_high = 0
        self._cond: asyncio.Condition | None = None

    def _ensure_cond(self) -> asyncio.Condition:
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    def _limit(self) -> int:
        return max(1, CONTROLLER.concurrency_limit)

    def effective_limit(self, priority: Priority) -> int:
        """Диагностика/панель: при ON — AIMD-лимит (P3-Delta — surplus-
        семантика, см. класс); при OFF — единый статический лимит."""
        return self._limit()

    def snapshot(self) -> dict:
        return {"active_high": self._active_high, "active_p3": self._active_p3,
                "waiting_high": self._waiting_high,
                "limit": self._limit()}

    async def acquire(self, priority: Priority, group_id: str,
                      *, max_wait_s: float | None = None) -> _Permit:
        """Взять слот. Группа cooling/exhausted → ожидание до `max_wait_s`
        (None — без ожидания), затем `EmbeddingGroupCoolingDown` (caller
        решает: P0 → FTS-fallback, P3 → pause job). Конкурентность — AIMD-
        лимит; P3 — только idle-capacity (см. docstring класса)."""
        deadline = None if max_wait_s is None else time.monotonic() + max(0.0, max_wait_s)
        cond = self._ensure_cond()
        is_p3 = (priority >= Priority.P3_REBUILD
                 and priority_scheduler_enabled())
        if not is_p3:
            self._waiting_high += 1
        try:
            while True:
                if REGISTRY.group_blocked(group_id):
                    now = int(time.time())
                    next_allowed = REGISTRY.group_state(group_id).next_allowed_at
                    wait_need = max(0.0, float(next_allowed - now))
                    if deadline is None or time.monotonic() + wait_need > deadline:
                        raise EmbeddingGroupCoolingDown(
                            group_id=group_id, next_allowed_at=next_allowed)
                    async with cond:
                        try:
                            await asyncio.wait_for(cond.wait(),
                                                   timeout=min(wait_need, 1.0) or 0.05)
                        except asyncio.TimeoutError:
                            pass
                    continue
                active = self._active_high + self._active_p3
                if is_p3:
                    can_take = (active < self._limit()
                                and self._active_high == 0
                                and self._waiting_high == 0)
                else:
                    can_take = active < self._limit()
                if can_take:
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    raise EmbeddingConcurrencyBusy(
                        f"embed scheduler busy | priority={priority.name}")
                async with cond:
                    try:
                        await asyncio.wait_for(cond.wait(), timeout=0.25)
                    except asyncio.TimeoutError:
                        pass
        finally:
            if not is_p3:
                self._waiting_high -= 1
        if is_p3:
            self._active_p3 += 1
        else:
            self._active_high += 1
        return _Permit(priority)

    def release(self, permit: _Permit) -> None:
        if permit.released:
            return
        permit.released = True
        if permit.priority >= Priority.P3_REBUILD:
            self._active_p3 = max(0, self._active_p3 - 1)
        else:
            self._active_high = max(0, self._active_high - 1)
        self._notify()

    def _notify(self) -> None:
        cond = self._cond
        if cond is None:
            return
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:     # pragma: no cover
            return
        if loop.is_running():

            async def _notify_all():
                async with cond:
                    cond.notify_all()

            asyncio.ensure_future(_notify_all())


SCHEDULER = PriorityScheduler()


# ── Исключения контракта ────────────────────────────────────────────────────


class EmbeddingControlPlaneError(Exception):
    """Базовое исключение контрол-плейна (не LLMError — не путать с
    legacy-иерархией llm_client)."""


class EmbeddingGroupCoolingDown(EmbeddingControlPlaneError):
    def __init__(self, *, group_id: str, next_allowed_at: int) -> None:
        super().__init__(
            f"embedding quota group cooling down: {group_id} "
            f"until {next_allowed_at}")
        self.group_id = group_id
        self.next_allowed_at = next_allowed_at


class EmbeddingConcurrencyBusy(EmbeddingControlPlaneError):
    pass


class EmbeddingBudgetExhausted(EmbeddingControlPlaneError):
    """Исчерпан attempt budget (≤4) — наверх (FTS-fallback / pause)."""


# ── T-4878 (ASAP 4.4): terminal serviceability states для batch-policy ─────
# `EmbeddingGroupCoolingDown` (группа cooling/parked) и `EmbeddingBudgetExhausted`
# (бюджет исчерпан / нет usable credential) — состояние известно и не
# изменится внутри того же logical batch: повторный embed бессмысленен.

_SERVICEABILITY_ERRORS = (EmbeddingGroupCoolingDown,
                          EmbeddingBudgetExhausted)


def is_serviceability_error(exc: BaseException) -> bool:
    """True — known control-plane serviceability state (retry в том же batch
    не имеет смысла). False — transient/неизвестная ошибка: её по-прежнему
    видно со stacktrace (не маскируем)."""
    return isinstance(exc, _SERVICEABILITY_ERRORS)


# ── Provider-agnostic adapter (T-4405, §13–§16) ─────────────────────────────


class EmbeddingProviderAdapter:
    """Контракт spec A.3: capabilities / batch_limits / token_limit_per_item /
    embed_batch / quota_metadata / classify_error. Реализация ПОВЕРХ
    существующего LLMClient (сеть/клиенты переиспользуются, §13) — через
    `LLMClient.embed_once` (один credential, без каскада, transport retry
    ≤1)."""

    name = "base"

    def __init__(self, llm) -> None:
        self._llm = llm

    def capabilities(self) -> dict:
        return {"sync_batch": True, "async_batch": False,
                "provider": self.name}

    def batch_limits(self) -> int:
        """Provider batch limit (sync /embeddings)."""
        return max(1, int(_settings_value("EMBED_BATCH_MAX", 50)))

    def token_limit_per_item(self) -> int:
        return max(128, int(_settings_value(
            "EMBED_DEFAULT_TOKEN_LIMIT_PER_ITEM", 2048)))

    def quota_metadata(self) -> dict:
        """(1) лестницы §5: machine-readable quota metadata, если безопасно
        доступна. Базовый адаптер метаданных не имеет — честный None."""
        return {}

    def classify_error(self, exc: Exception, headers=None,
                       body: str | None = None) -> RateLimitInfo:
        return classify_rate_limit(429, headers, body)

    async def embed_batch(self, credential: EmbeddingCredential,
                          texts: list[str]) -> list[list[float]]:
        """ОДИН HTTP-вызов одного credential (без каскада). 429 →
        LLMRateLimitError наверх немедленно (retry_statuses=())."""
        return await self._llm.embed_once(
            texts, api_key=credential.api_key,
            base_url=credential.base_url, model=credential.model,
            max_retries=1,        # transport retry ≤1 (A.2)
            retry_statuses=(),    # 429/5xx — наверх, без нижнеуровневых ретраев
        )


class GeminiEmbeddingAdapter(EmbeddingProviderAdapter):
    """Gemini Developer API / OpenAI-compat endpoint (generativelanguage).
    `gemini-embedding-001`: input ≤ 2048 token/item (§14); lossless
    сегментация до embed; авто-переход на `-2` ЗАПРЕЩЁН (§15 — модель
    берётся из конфига как есть)."""

    name = "gemini"

    def token_limit_per_item(self) -> int:
        # §14: официальный input limit gemini-embedding-001 = 2048 token/item.
        return 2048

    def capabilities(self) -> dict:
        caps = super().capabilities()
        caps["model"] = str(getattr(self._llm, "_embed_model", "") or "")
        caps["lossless_segmentation"] = True
        caps["auto_model_migration"] = False
        return caps


class OpenAICompatibleEmbeddingAdapter(EmbeddingProviderAdapter):
    """OpenAI-compatible /embeddings (другой provider / staging-fixture §35).
    Scheduler НЕ написан только под 429 Google — классификация/пул общие."""

    name = "openai-compatible"


def select_adapter(base_url: str, llm) -> EmbeddingProviderAdapter:
    if _is_gemini_endpoint(base_url):
        return GeminiEmbeddingAdapter(llm)
    return OpenAICompatibleEmbeddingAdapter(llm)


# ── Lossless segmentation (§14; T-4405) ─────────────────────────────────────

# Приблизительная оценка токенов: провайдер-agnostic conservative 4 char/token
# (для русскоязычного текста занижает токены редко; сегментация режет С
# запасом — silent truncation запрещён, ложный oversized — безопасное
# событие: текст уйдёт двумя сегментами).
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def segment_text_lossless(text: str, token_limit: int) -> list[str]:
    """Lossless-сегментация ≤ token_limit на сегмент: абзацы → предложения →
    жёсткий char-разрез. Конкатенация сегментов == исходный текст (без
    потерь, без перестановок). Silent truncation ЗАПРЕЩЁН (§14)."""
    text = str(text or "")
    if not text:
        return [""]
    max_chars = max(_CHARS_PER_TOKEN, token_limit * _CHARS_PER_TOKEN)
    if len(text) <= max_chars:
        return [text]
    segments: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            segments.append(remaining)
            break
        window = remaining[:max_chars]
        cut = window.rfind("\n\n")
        if cut < max_chars // 2:
            cut = window.rfind(". ")
        if cut < max_chars // 2:
            cut = max_chars
        else:
            cut += 1
        segments.append(remaining[:cut])
        remaining = remaining[cut:]
    return segments


def _mean_pool(vectors: list[list[float]]) -> list[float]:
    """Lossless-сборка parent-вектора из сегментных (среднее, нормированное
    на число сегментов — каждый сегмент вносит полный свой сигнал; stable
    parent ref: результат соответствует родительскому item 1:1)."""
    if len(vectors) == 1:
        return vectors[0]
    dim = len(vectors[0])
    acc = [0.0] * dim
    for vec in vectors:
        for i in range(min(dim, len(vec))):
            acc[i] += float(vec[i])
    n = float(len(vectors))
    return [v / n for v in acc]


# ── EmbeddingExecutor (T-4403, spec A.2; ADR-1028-7 D1.2) ───────────────────

# Attempt budget (ADR-1028-7 D2): 1 начальная + до 3 retry (transport
# 5xx/timeout). 429 — перенос по next_allowed_at, НЕ «лобовая» попытка —
# но не бесконечно: одна пере-подача после cooldown на logical request.
_ATTEMPT_BUDGET = 4
# Transport backoff (§9: min(1·2ⁿ, 8)) — ТОЛЬКО транспортный механизм, в
# quota-cooldown не участвует. Developer/test hook: 0 → сон 0.
_TRANSPORT_BACKOFF_BASE = 1.0
_TRANSPORT_BACKOFF_CAP = 8.0


@dataclass
class ExecutionStats:
    http_calls: int = 0        # логические HTTP-вызовы (ceiling теста §64)
    attempts: int = 0          # попытки в бюджете (429-defer не считает)
    deferred: int = 0          # 429-переносов по next_allowed_at
    credentials_used: list = field(default_factory=list)


class EmbeddingExecutor:
    """ЕДИНСТВЕННЫЙ владелец retry-policy (spec A.2): один logical request =
    одна orchestration policy. Знает: batch, provider, quota group,
    credential list, attempt budget, rate-limit cooldown, priority.

    Демонтаж самостоятельных policy (§A.2):
    * `summary_memory._embed_api` (3 внешних попытки) — при ON вызывает
      executor вместо собственного цикла;
    * embed-fallback каскад `llm_client.embed` (2 ключа × 2) — не вызывается;
      credential'ы перебирает executor с учётом quota-групп.
    OFF (EMBED_CONTROL_PLANE_ENABLED=false) → оба старых контура бит-в-бит.
    """

    def __init__(self, llm, registry: QuotaGroupRegistry | None = None,
                 scheduler: PriorityScheduler | None = None) -> None:
        self._llm = llm
        self._registry = registry or REGISTRY
        self._scheduler = scheduler or SCHEDULER
        self._pool: list[EmbeddingCredential] | None = None
        self._adapters: dict[str, EmbeddingProviderAdapter] = {}

    # ── pool/adapter (лениво, конфиг читается на вызов — hot-config живой) ──

    def pool(self) -> list[EmbeddingCredential]:
        self._pool = build_credential_pool()
        return self._pool

    def adapter_for(self, base_url: str) -> EmbeddingProviderAdapter:
        adapter = self._adapters.get(base_url)
        if adapter is None:
            adapter = select_adapter(base_url, self._llm)
            self._adapters[base_url] = adapter
        return adapter

    # ── главный контракт ──

    async def embed(self, texts: list[str], *, priority: Priority,
                    max_wait_s: float | None = None,
                    stats: ExecutionStats | None = None) -> list[list[float]]:
        """Логический embed-батч. Бросает:
        * `EmbeddingGroupCoolingDown` — все доступные группы cooling/exhausted
          дольше max_wait (P0 → FTS-fallback; P3 → pause job);
        * LLMAuthError (401/403) — terminal (auth_failed, без ретраев);
        * `EmbeddingBudgetExhausted` — исчерпаны ≤4 попытки на retryable.
        429 при burst-pressure: ожидание cooldown (bounded max_wait) и одна
        пере-подача; при quota-unavailable: group exhausted + тот же контракт
        ожидания (P3 ждёт — pause-цикл, P0 отступает к FTS)."""
        if not texts:
            return []
        stats = stats or ExecutionStats()
        pool = self.pool()
        if not pool:
            # Ключей не сконфигурировано вовсе: оркестрировать нечего —
            # делегируем существующему клиенту (ровно прежний primary-only
            # путь; 21-каскад невозможен без fallback-ключей). Контракт
            # «единственный retry-owner» применяется к пулу credential'ов.
            return await self._llm.embed(list(texts))
        # D3 (T-4503): вырожденный пул (одна unknown-группа) репортится
        # честно — WARN ≤1/10 мин, без фейковой ротации.
        _maybe_warn_degenerate_rotation(pool_rotation_diagnosis(pool))

        budget_left = _ATTEMPT_BUDGET
        defers = 0
        # 429-defer не считается «лобовой» попыткой (перенос по
        # next_allowed_at), но и не бесконечен: ротация ограничена размером
        # пула (каждый ключ группы максимум одна пере-подача) + 1.
        max_defers = max(2, len(pool))
        last_error: Exception | None = None

        while budget_left > 0:
            credential = self._pick_credential(pool)
            if credential is None:
                # Все ключи непригодны. Группа cooling → контракт ожидания
                # (acquire бросит CoolingDown по max_wait); группы здоровы,
                # но usable-ключей нет (auth_failed/disabled) → честный
                # терминал без спина.
                if not self._registry.group_blocked(pool[0].quota_group_id) \
                        and not any(
                            self._registry.group_blocked(c.quota_group_id)
                            for c in pool):
                    raise EmbeddingBudgetExhausted(
                        "no usable embedding credential "
                        "(auth_failed/disabled)")
                permit = await self._scheduler.acquire(
                    priority, pool[0].quota_group_id, max_wait_s=max_wait_s)
                self._scheduler.release(permit)
                continue
            try:
                permit = await self._scheduler.acquire(
                    priority, credential.quota_group_id, max_wait_s=max_wait_s)
            except EmbeddingGroupCoolingDown:
                # Группа выбранного credential'а cooling → взять другой
                # (независимая группа §65); больше некого — наверх.
                if self._pick_credential(pool) is None:
                    raise
                continue
            try:
                adapter = self.adapter_for(credential.base_url)
                vectors = await self._call_with_segmentation(
                    adapter, credential, texts, stats)
                self._on_success(credential, len(texts))
                return vectors
            except EmbeddingControlPlaneError:
                raise
            except Exception as exc:
                last_error = exc
                handled = await self._on_error(
                    exc, pool, credential.quota_group_id, priority, stats)
                if handled == "auth":
                    raise
                if handled == "defer":
                    # 429: перенос по next_allowed_at (НЕ лобовая попытка).
                    stats.deferred += 1
                    defers += 1
                    if defers > max_defers:
                        # Ротация пула исчерпана — наверх (caller решает
                        # FTS/pause).
                        raise EmbeddingGroupCoolingDown(
                            group_id=credential.quota_group_id,
                            next_allowed_at=self._registry.group_state(
                                credential.quota_group_id).next_allowed_at,
                        ) from exc
                    continue
                # transport retryable (5xx/timeout): счётная попытка.
                budget_left -= 1
                if budget_left <= 0:
                    break
                await asyncio.sleep(min(
                    _TRANSPORT_BACKOFF_BASE * (2 ** (stats.attempts - 1)),
                    _TRANSPORT_BACKOFF_CAP))
            finally:
                self._scheduler.release(permit)

        raise EmbeddingBudgetExhausted(
            f"embedding attempt budget exhausted "
            f"(budget={_ATTEMPT_BUDGET})") from last_error

    # ── внутреннее ──

    def _pick_credential(self,
                         pool: list[EmbeddingCredential]) -> EmbeddingCredential | None:
        """Первый usable credential: ключ healthy И его группа не cooling
        (§10: тот же group не дёргается другим ключом; независимая группа —
        можно перейти к ней, §10/§65)."""
        for credential in pool:
            if self._registry.credential_health(credential.alias) != HEALTH_HEALTHY:
                continue
            if self._registry.group_blocked(credential.quota_group_id):
                continue
            return credential
        return None

    async def _call_with_segmentation(
            self, adapter: EmbeddingProviderAdapter,
            credential: EmbeddingCredential, texts: list[str],
            stats: ExecutionStats) -> list[list[float]]:
        """Один HTTP-вызов на батч + lossless сегментация oversized items
        (§14): сегменты уходят в тех же вызовах (stable parent ref), parent-
        вектор собирается mean-pool'ом. Batch-план строится по provider
        batch_limit; превышение → дополнительные вызовы (все считаются в
        stats.http_calls)."""
        limit = adapter.token_limit_per_item()
        flat_texts: list[str] = []
        owner: list[int] = []                     # flat-pos → item_idx
        for idx, text in enumerate(texts):
            segments = segment_text_lossless(text, limit)
            for _seg in segments:
                owner.append(idx)
            flat_texts.extend(segments)

        batch_limit = min(adapter.batch_limits(),
                          max(1, CONTROLLER.batch_size))
        collected: dict[int, list[list[float]]] = {}
        for start in range(0, len(flat_texts), batch_limit):
            chunk = flat_texts[start:start + batch_limit]
            stats.http_calls += 1
            stats.attempts += 1
            stats.credentials_used.append(credential.alias)
            vectors = await adapter.embed_batch(credential, chunk)
            if len(vectors) != len(chunk):
                raise EmbeddingControlPlaneError(
                    f"embeddings: vectors={len(vectors)} != inputs={len(chunk)}")
            for offset, vector in enumerate(vectors):
                collected.setdefault(owner[start + offset], []).append(vector)
        return [_mean_pool(segments) for segments in
                (collected.get(i, []) for i in range(len(texts)))]

    async def _on_error(self, exc: Exception, pool: list[EmbeddingCredential],
                        group_id: str, priority: Priority,
                        stats: ExecutionStats) -> str:
        """Классификация ошибки (§8/§11). Возвращает 'auth' | 'defer' |
        'transport'. Логирует ТОЛЬКО тип/код/класс — без содержимого запроса
        и без значений ключей (R17)."""
        name = type(exc).__name__
        # 401/403 → auth_failed credential'а, БЕЗ ретраев как 429 (§11);
        # auth-fail одного credential не отключает другие группы.
        if "Auth" in name:
            current = stats.credentials_used[-1] if stats.credentials_used else None
            if current:
                self._registry.mark_credential(current, HEALTH_AUTH_FAILED)
            logger.warning(
                "embed credential auth_failed | alias=%s | error=%s",
                current, name)
            return "auth"
        if "RateLimit" in name or "429" in str(exc)[:120]:
            headers = getattr(exc, "headers", None)
            body = getattr(exc, "body", None)
            info = classify_rate_limit(
                429, headers, body if isinstance(body, str) else None)
            # D1 (T-4503): kind-aware длительность — spend/daily без RA
            # паркуется до оценки reset (конец суток UTC+margin), RA
            # уважается (ceiling 300s), rpm/tpm/burst — прежняя семантика.
            delay, parked, park_est = _quota_parking_seconds(info)
            quota_unavailable = is_quota_unavailable(info, 1)
            state = GROUP_EXHAUSTED if quota_unavailable else GROUP_COOLING
            next_allowed = int(time.time() + delay)
            self._registry.record_rate_limit()
            # Per-credential health (§11): текущий ключ в cooldown на время
            # паузы — при OFF group-cooldown следующий выбор уходит на другой
            # ключ той же группы (перебор как сейчас), при ON группу не дёргаем
            # вообще до next_allowed_at.
            current = stats.credentials_used[-1] if stats.credentials_used else None
            if current:
                self._registry.mark_credential(current, HEALTH_COOLDOWN,
                                               cooldown_s=delay)
            if quota_group_cooldown_enabled():
                # D1-честность: парковка-оценка отличима от точного RA
                # (`parked ... est=...` vs `429 ... ra=...`) — панель/логи не
                # выдают оценку за точный срок.
                if parked:
                    note = f"parked kind={info.kind} est={park_est}"
                else:
                    note = f"429 kind={info.kind} ra={info.retry_after_s}"
                await self._registry.set_group_state(
                    group_id, state, next_allowed, note)
            else:
                # Cooldown OFF → перебор ключей как сейчас (без group-паузы).
                self._registry._set_group_local(group_id, GROUP_HEALTHY, 0,
                                                "cooldown_disabled")
            # AIMD: 429 → ÷2 (резко); batch ÷2; P3-заморозка — через group
            # cooldown (та же группа) — preemption по next_allowed_at (§18).
            CONTROLLER.on_rate_limit()
            CONTROLLER.on_batch_rate_limit()
            if quota_kind_parking_enabled():
                logger.warning(
                    "embed rate limit | group=%s | state=%s | kind=%s | "
                    "retry_after=%s | cooldown_s=%.1f | parked=%d | "
                    "429_last_10m=%d",
                    group_id, state, info.kind,
                    info.retry_after_s, delay, 1 if parked else 0,
                    self._registry.rate_limits_last_10m())
            else:
                # L-4504-3: parking OFF → байт-формат лога 2.58.45
                # (постоянное `parked=0` из лога убрано).
                logger.warning(
                    "embed rate limit | group=%s | state=%s | kind=%s | "
                    "retry_after=%s | cooldown_s=%.1f | "
                    "429_last_10m=%d",
                    group_id, state, info.kind,
                    info.retry_after_s, delay,
                    self._registry.rate_limits_last_10m())
            return "defer"
        # Transport 5xx/timeout → счётная retry-попытка. Per-key health НЕ
        # трогаем: транспортный сбой — сторона провайдера/сети, а не ключа;
        # retry того же logical request обязан идти по тому же пулу (иначе
        # single-credential пул спиновал бы вечно).
        logger.warning("embed transport error | error=%s", name)
        return "transport"

    def _on_success(self, credential: EmbeddingCredential, items: int) -> None:
        self._registry.mark_credential(credential.alias, HEALTH_HEALTHY)
        CONTROLLER.on_success()
        CONTROLLER.on_batch_success(items)


EXECUTOR: EmbeddingExecutor | None = None


def get_executor(llm=None) -> EmbeddingExecutor:
    global EXECUTOR
    if EXECUTOR is None or (llm is not None and EXECUTOR._llm is not llm):
        EXECUTOR = EmbeddingExecutor(llm)
    return EXECUTOR


# ── Priority-контекст для call-site'ов (summary_memory) ─────────────────────

_current_priority: contextvars.ContextVar[Priority] = contextvars.ContextVar(
    "embed_priority", default=Priority.P1_WRITE)


def set_priority(priority: Priority):
    """Контекст приоритета для вложенных вызовов `_embed` (rebuild job
    выставляет P3 на весь цикл батчей). Возвращает token для reset."""
    return _current_priority.set(priority)


def reset_priority(token) -> None:
    _current_priority.reset(token)


def current_priority() -> Priority:
    return _current_priority.get()


async def execute_embed(llm, texts: list[str], *,
                        priority: Priority | None = None,
                        max_wait_s: float | None = None) -> list[list[float]]:
    """Точка входа из summary_memory (`_embed_api` при ON):Executor с
    fallback на cooldown-исключение наверх (caller решает деградацию)."""
    executor = get_executor(llm)
    return await executor.embed(
        texts, priority=priority or current_priority(),
        max_wait_s=max_wait_s)


# ── Multi-worker lease (T-4407, §22/§23) ────────────────────────────────────

_LEASE_KIND = "embedding_rebuild_lease"
_LEASE_COALESCE = "embedding_full_rebuild_permit"
_LEASE_STALE_SECONDS = 900      # 15 мин без heartbeat → takeover


class RebuildLease:
    """Shared permit на deployment через существующую `task_jobs` +
    `write_transaction` (REUSE mca-01; Redis ЗАПРЕЩЁН — §22): ≤1 active
    full-rebuild на deployment → `graph_facts_vec` и `smart_archive` не
    стартуют full-rebuild одновременно (прод-факт Q6). Process-local
    semaphores недостаточны при втором процессе — lease в DB покрывает."""

    def __init__(self, db) -> None:
        self._db = db
        self.job_id: str | None = None
        self._heartbeat_at = 0.0

    async def acquire(self, holder_index: str) -> bool:
        try:
            from services.task_supervisor import TaskJobStore
            import uuid
            store = TaskJobStore(self._db)
            jid = f"lease-{uuid.uuid4().hex[:16]}"

            async def _body(conn):
                await conn.execute(
                    "INSERT OR IGNORE INTO task_jobs (job_id, owner, kind, "
                    "coalesce_key, payload, status, attempt, max_attempts, "
                    "generation, fencing_token, created_at, updated_at, "
                    "heartbeat_at) VALUES (?, 'memory', ?, ?, ?, 'running', "
                    "0, 1, 0, 0, ?, ?, ?)",
                    (jid, _LEASE_KIND, _LEASE_COALESCE,
                     json.dumps({"holder_index": holder_index},
                                ensure_ascii=False),
                     int(time.time()), int(time.time()), int(time.time())))

            await self._db.write_transaction(_body, op_name="embed_lease_acquire")
            cursor = await self._db.db.execute(
                "SELECT job_id, payload, heartbeat_at, updated_at FROM "
                "task_jobs WHERE kind = ? AND coalesce_key = ? AND "
                "status = 'running' LIMIT 1",
                (_LEASE_KIND, _LEASE_COALESCE))
            row = await cursor.fetchone()
            if row is None:
                return False
            if str(row["job_id"]) != jid:
                # Чужой lease: stale → takeover (restart прошлого процесса).
                try:
                    payload = json.loads(row["payload"] or "{}")
                except ValueError:
                    payload = {}
                hb_at = int(row["heartbeat_at"] or 0)
                if hb_at <= 0:
                    hb_at = int(row["updated_at"] or 0)
                if hb_at <= 0:
                    hb_at = int(payload.get("acquired_at") or 0)
                age = int(time.time()) - hb_at
                if age < _LEASE_STALE_SECONDS:
                    return False
                ok = await self._takeover(str(row["job_id"]), jid,
                                          holder_index)
                if ok:
                    self.job_id = jid
                    self._heartbeat_at = time.monotonic()
                return ok
            self.job_id = jid
            self._heartbeat_at = time.monotonic()
            return True
        except Exception:
            logger.warning("embed lease acquire failed", exc_info=True)
            return False

    async def _takeover(self, old_jid: str, new_jid: str,
                        holder_index: str) -> bool:
        now = int(time.time())

        async def _body(conn):
            await conn.execute(
                "UPDATE task_jobs SET status = 'finished', reason_code = "
                "'stale_takeover', finished_at = ?, updated_at = ? "
                "WHERE job_id = ? AND status = 'running'",
                (now, now, old_jid))
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO task_jobs (job_id, owner, kind, "
                "coalesce_key, payload, status, attempt, max_attempts, "
                "generation, fencing_token, created_at, updated_at, "
                "heartbeat_at) VALUES (?, 'memory', ?, ?, ?, 'running', "
                "0, 1, 0, 0, ?, ?, ?)",
                (new_jid, _LEASE_KIND, _LEASE_COALESCE,
                 json.dumps({"holder_index": holder_index},
                            ensure_ascii=False),
                 now, now, now))
            return cursor.rowcount

        try:
            await self._db.write_transaction(_body, op_name="embed_lease_takeover")
            cursor = await self._db.db.execute(
                "SELECT job_id FROM task_jobs WHERE kind = ? AND "
                "coalesce_key = ? AND status = 'running' LIMIT 1",
                (_LEASE_KIND, _LEASE_COALESCE))
            row = await cursor.fetchone()
            return row is not None and str(row["job_id"]) == new_jid
        except Exception:
            logger.warning("embed lease takeover failed", exc_info=True)
            return False

    async def heartbeat(self) -> None:
        if self.job_id is None:
            return
        now = int(time.time())
        try:
            async def _body(conn):
                await conn.execute(
                    "UPDATE task_jobs SET heartbeat_at = ?, updated_at = ? "
                    "WHERE job_id = ? AND status = 'running'",
                    (now, now, self.job_id))

            await self._db.write_transaction(_body, op_name="embed_lease_hb")
        except Exception:
            logger.warning("embed lease heartbeat failed", exc_info=True)

    async def release(self) -> None:
        if self.job_id is None:
            return
        jid, self.job_id = self.job_id, None
        now = int(time.time())
        try:
            async def _body(conn):
                await conn.execute(
                    "UPDATE task_jobs SET status = 'finished', "
                    "reason_code = 'released', finished_at = ?, "
                    "updated_at = ? WHERE job_id = ? AND status = 'running'",
                    (now, now, jid))

            await self._db.write_transaction(_body, op_name="embed_lease_release")
        except Exception:
            logger.warning("embed lease release failed", exc_info=True)

    @staticmethod
    async def holder(db) -> dict | None:
        """Текущий держатель permit (для панели/диагностики)."""
        try:
            cursor = await db.db.execute(
                "SELECT job_id, payload, heartbeat_at, updated_at FROM "
                "task_jobs WHERE kind = ? AND coalesce_key = ? AND "
                "status = 'running' LIMIT 1", (_LEASE_KIND, _LEASE_COALESCE))
            row = await cursor.fetchone()
            if row is None:
                return None
            try:
                payload = json.loads(row["payload"] or "{}")
            except ValueError:
                payload = {}
            return {"job_id": str(row["job_id"])[:16],
                    "holder_index": str(payload.get("holder_index") or ""),
                    "heartbeat_at": int(row["heartbeat_at"] or 0)}
        except Exception:
            return None


# ── Log/UI hygiene (T-4410, §31) + панели (T-4411, §32/§63) ─────────────────

_STATE_LOG_COOLDOWN_S = 300.0
_last_state_log: dict[str, float] = {}


def coalesced_state_log(key: str, message: str, *, level: int = 20,
                        force: bool = False, **fields) -> bool:
    """§31: `paused_rate_limit` не спамит WARNING — state-transition лог +
    coalesced periodic status (≤1 на 5 мин на ключ). True — залогировано."""
    now = time.monotonic()
    last = _last_state_log.get(key, 0.0)
    if not force and now - last < _STATE_LOG_COOLDOWN_S:
        return False
    _last_state_log[key] = now
    suffix = " | " + " | ".join(f"{k}={v}" for k, v in fields.items()) \
        if fields else ""
    logger.log(level, "%s%s", message, suffix)
    return True


def group_state_lines() -> list[dict]:
    """R17-safe снимок групп (панель §32 «Embedding provider»)."""
    out = []
    for group_id, group in REGISTRY._groups.items():
        out.append({
            "quota_group": group_id if group_id != UNKNOWN_GROUP_ID
            else "не определены",
            "state": group.state,
            "next_allowed_at": group.next_allowed_at,
            "note": group.note,
        })
    if not out:
        out.append({"quota_group": "не определены", "state": GROUP_UNKNOWN,
                    "next_allowed_at": 0, "note": ""})
    return out


def provider_panel() -> dict:
    """Панель «Embedding provider» (§32): provider/model, credentials=N,
    независимых групп 1/2/неизвестно, текущая concurrency/batch, 429 за
    10 минут. Только aliases — без секретов (§63)."""
    pool = build_credential_pool()
    groups = {c.quota_group_id for c in pool}
    known = {c.quota_group_id for c in pool if c.quota_group_known}
    unknown = groups - known
    adapter = (EXECUTOR.adapter_for(pool[0].base_url)
               if EXECUTOR is not None and pool
               else None)
    # D3 (T-4503): честный диагноз распределения — «rotation: none» + hint
    # при вырожденном пуле; подхват labels живьём (пул строится на вызов).
    rotation = _rotation_panel_block(pool_rotation_diagnosis(pool))
    _maybe_warn_degenerate_rotation(pool_rotation_diagnosis(pool))
    return {
        "provider": pool[0].provider if pool else "не настроен",
        "model": pool[0].model if pool else "",
        "credentials": len(pool),
        "credential_aliases": [c.alias for c in pool],
        "quota_groups_total": len(groups),
        "quota_groups_known": len(known),
        "quota_groups_unknown": len(unknown),
        "quota_group_display": (
            "не определены" if not known
            else f"{len(groups)}" if not unknown
            else f"{len(groups)} (часть не определена)"),
        "concurrency": CONTROLLER.snapshot()["concurrency_limit"],
        "batch_size": CONTROLLER.snapshot()["batch_size"],
        "rate_limits_10m": REGISTRY.rate_limits_last_10m(),
        "async_batch_enabled": async_batch_enabled(),
        "adapter": adapter.name if adapter else None,
        "rotation": rotation,
        "groups": group_state_lines(),
    }


def _safe_int(value) -> int | None:
    """Число или None (панель §62: progress/updated_at; fail-open)."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _human_status(job_status: str, reason: str | None) -> str:
    mapping = {
        "queued": "в очереди",
        "building": "сборка индекса",
        "running": "сборка индекса",
        "checkpoint": "сохранение прогресса",
        "paused": "пауза (оператор)",
        "paused_rate_limit": "пауза из-за лимита провайдера",
        "paused_provider": "пауза: провайдер недоступен",
        "validating": "проверка индекса",
        "validated": "проверка пройдена",
        "validation_failed": "проверка не пройдена (векторы сохранены)",
        "active": "активен",
        "activated": "активен",
        "failed": "ошибка",
        "cancelled": "отменено",
        "finished": "завершено",
    }
    if reason == "knn_source_empty":
        return "проверка не пройдена: пустой источник"
    return mapping.get(job_status, job_status)


async def vector_memory_panel(db) -> dict:
    """Панель «Векторная память» (§32): per index — статус по-русски,
    готовность %, next attempt, источник поиска (FTS5/KNN). Только
    structured state (task_jobs + реестр поколений), не логи (T-4411).
    D10/T-5255 (asap5-final-fixes): + `total` (eligible-строки источника)
    — «Vector rebuild in progress N/M»; + `resume_ticker` (жив ли тик
    future-resume — диагностика resume-gap §13)."""
    out: dict = {"indexes": [], "lease": await RebuildLease.holder(db),
                 "resume_ticker": False}
    try:
        from services.graphrag_rebuild import (_INDEX_SPECS, _source_empty,
                                               _source_total)
        out["resume_ticker"] = True   # импорт жив; факт старта — см. поле ниже
        try:
            from services.graphrag_rebuild import ticker_active
            out["resume_ticker"] = ticker_active()
        except Exception:
            pass
        source_specs = dict(_INDEX_SPECS)
        source_empty = _source_empty
        source_total = _source_total
    except Exception:
        source_specs = {}
        source_empty = None
        source_total = None
    try:
        cursor = await db.db.execute(
            "SELECT coalesce_key, status, reason_code, payload, updated_at "
            "FROM task_jobs WHERE kind = 'graphrag_rebuild' "
            "ORDER BY created_at DESC LIMIT 16")
        jobs = [dict(r) for r in await cursor.fetchall()]
        seen: set[str] = set()
        for job in jobs:
            try:
                payload = json.loads(job.get("payload") or "{}")
            except ValueError:
                payload = {}
            index = str(payload.get("index") or "")
            if not index or index in seen:
                continue
            seen.add(index)
            status = str(job.get("status") or "")
            reason = str(job.get("reason_code") or "") or None
            entry = {
                "index": index,
                "status": status,
                "status_ru": _human_status(status, reason),
                "reason_code": reason,
                "next_attempt_at": 0,
                "search_source": "FTS5",
                # §62 (волна E, T-4446-карточка): прогресс/checkpoint и время
                # последней активности job (structured state task_jobs).
                "processed": _safe_int(payload.get("processed")),
                "updated_at": _safe_int(job.get("updated_at")),
                # D10/T-5255: знаменатель «N/M» (eligible-строки источника).
                "total": None,
                "source_empty": None,
            }
            if source_total is not None and index in source_specs:
                try:
                    entry["total"] = await source_total(db, index)
                    if source_empty is not None:
                        entry["source_empty"] = await source_empty(db, index)
                except Exception:
                    pass
            gen = await db.get_generation_by_fingerprint(
                index, str(payload.get("fingerprint") or ""))
            if gen is not None:
                processed = int(payload.get("processed") or 0)
                entry["generation"] = int(gen.get("generation") or 0)
                entry["pause_reason"] = gen.get("pause_reason")
                entry["next_allowed_at"] = gen.get("next_allowed_at")
                entry["attempts_total"] = int(gen.get("attempts_total") or 0)
                if entry["next_allowed_at"]:
                    entry["next_attempt_at"] = int(entry["next_allowed_at"])
            # ASAP 6 §8/13J: additive-поля — ACTIVE-поколение и честный класс
            # совместимости текущего конфига с ним (backend-часть; UI уже
            # предупреждает). Fail-open: нет реестра/поколения → поля None.
            entry["namespace"] = None
            entry["active_generation"] = None
            entry["compat_class"] = None
            try:
                active = await db.get_active_embedding_generation(index)
            except Exception:
                active = None
            if active is not None:
                entry["namespace"] = str(active.get("namespace") or "default")
                entry["active_generation"] = int(
                    active.get("generation") or 0)
                try:
                    fp_now = profile_identity(
                        resolve_embedding_profiles()["primary"])
                    entry["compat_class"] = classify_identity_compatibility(
                        current_identity=fp_now,
                        stored_identity=str(
                            active.get("fingerprint") or ""),
                        stored_dim=active.get("dims"),
                        canary_verdict=(canary_verdict_cached(fp_now)
                                        or None))
                except Exception:
                    entry["compat_class"] = None
            out["indexes"].append(entry)
    except Exception:
        logger.warning("vector memory panel failed", exc_info=True)
    return out


# ── D11 (asap5-final-fixes, T-5256/T-5257, 13C.1–13C.4, ADR-1028-25) ────────
# Три честных профиля embeddings (Primary / Fallback 1 / Fallback 2),
# identity-отпечаток канонического JSON (sha256[:16]), canary-проба
# косинусной близостью и одна server-side классификация совместимости.
# R17: значения ключей не читаются и не логируются — только факты конфига.

# Классы совместимости (одна server-side классификация для backend/MiniApp).
COMPAT_INSTANT = "INSTANT_COMPATIBLE"        # identity совпала (key/quota/route)
COMPAT_REINDEX = "REINDEX_REQUIRED"          # та же размерность, другая identity
COMPAT_DIMENSION = "INCOMPATIBLE_DIMENSION"  # размерность разная
COMPAT_UNKNOWN = "COMPATIBILITY_UNKNOWN"     # не доказано — fail-safe

# Вердикты canary-пробы.
CANARY_STABLE = "stable"
CANARY_DRIFT = "drift"
CANARY_UNKNOWN = "unknown"

# Пороги косинусной близости canary (frozen D11/Q6).
CANARY_MEAN_MIN = 0.98
CANARY_MIN_SIMILARITY = 0.95

# 3 фиксированные non-sensitive строки-пробы (frozen D11; без данных чатов).
CANARY_TEXTS = (
    "adminbot canary alpha 0123 stabilis",
    "проба стабильности отпечатков текста (asap5)",
    "vector identity probe -- 42 fixed line",
)

# task/mode + нормализация — часть identity (не меняются между вызовами).
EMBEDDING_TASK_MODE = "text-embedding/retrieval.v1"
EMBEDDING_NORMALIZATION = "as-returned-v1"   # вектора хранятся как вернул API


def _profile_hot(key: str, default: str = "") -> str:
    """hot.get c настройко-дефолтом (env-слой): absent PG-ключ → settings."""
    try:
        from services import hot_config as hot
        return str(hot.get(key, default) or "").strip()
    except Exception:      # pragma: no cover - защитная ветка
        return str(default or "").strip()


def _settings_default(field: str, default: str = "") -> str:
    try:
        from config.settings import settings
        return str(getattr(settings, field, default) or "").strip()
    except Exception:      # pragma: no cover
        return default


@dataclass(frozen=True)
class EmbeddingProfile:
    """Честный профиль подключения embeddings (13C.1): независимые
    base_url/model/quota_group; `inherited` — F2 наследует Fallback 1
    (режим по умолчанию миграции, честно помечен в статусе/UI)."""
    alias: str                 # primary | fallback_1 | fallback_2
    base_url: str
    model: str
    quota_group: str
    inherited: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.base_url) and bool(self.model)


def _profile_quota_group(alias: str, override: str) -> str:
    if override:
        return override
    try:
        labels = parse_quota_group_labels(_profile_hot(
            "keys.embedding_quota_group_labels"))
        group, _known = resolve_quota_group(alias, labels)
        return group
    except Exception:      # pragma: no cover
        return GROUP_UNKNOWN


def resolve_embedding_profiles() -> dict:
    """13C.1: три честных профиля. Primary — как раньше. Fallback 1 —
    новые ключи (`models.embedding_fallback1_*`), пусто → легаси-значения
    общего фолбэка (`models.embedding_fallback_*` — они становятся
    значениями Fallback 1, миграция без потери credentials). Fallback 2 —
    новые ключи `models.embedding_fallback2_*`; пусто → наследование
    Fallback 1 (режим по умолчанию, `inherited=true` — честная пометка;
    ключ у F2 всегда свой: `keys.embedding_fallback_api_key_2`).
    Никогда не бросает."""
    primary_base = _profile_hot("models.embedding_base_url",
                                _settings_default("EMBEDDING_BASE_URL"))
    primary_model = _profile_hot("models.embedding_model_name",
                                 _settings_default("EMBEDDING_MODEL_NAME"))
    # Легаси-общие значения обоих фолбэков → значения Fallback 1
    # (settings-дефолт = env-слой — паритет llm_client/status_service).
    legacy_base = _profile_hot("models.embedding_fallback_base_url",
                               _settings_default("EMBEDDING_FALLBACK_BASE_URL"))
    legacy_model = _profile_hot("models.embedding_fallback_model",
                                _settings_default("EMBEDDING_FALLBACK_MODEL"))
    fb1_base_new = _profile_hot("models.embedding_fallback1_base_url")
    fb1_model_new = _profile_hot("models.embedding_fallback1_model")
    fb1_base = fb1_base_new or legacy_base
    fb1_model = fb1_model_new or legacy_model
    fb2_base = _profile_hot("models.embedding_fallback2_base_url")
    fb2_model = _profile_hot("models.embedding_fallback2_model")
    fb2_inherit = not (fb2_base or fb2_model)
    eff_fb2_base = fb2_base or fb1_base
    eff_fb2_model = fb2_model or fb1_model
    return {
        "primary": EmbeddingProfile(
            alias="primary", base_url=primary_base, model=primary_model,
            quota_group=_profile_quota_group("primary",
                                             _profile_hot(
                                                 "models.embedding_quota_group"))),
        "fallback_1": EmbeddingProfile(
            alias="fallback_1", base_url=fb1_base, model=fb1_model,
            quota_group=_profile_quota_group("fallback_1",
                                             _profile_hot(
                                                 "models.embedding_fallback1_quota_group")),
            inherited=not (fb1_base_new or fb1_model_new)),
        "fallback_2": EmbeddingProfile(
            alias="fallback_2", base_url=eff_fb2_base, model=eff_fb2_model,
            quota_group=_profile_quota_group("fallback_2",
                                             _profile_hot(
                                                 "models.embedding_fallback2_quota_group")),
            inherited=fb2_inherit),
    }


def embedding_identity_v2(*, provider_family: str, endpoint_host: str,
                          model: str, revision: str | None = None,
                          dimension: int | None = None,
                          dimension_override: int | None = None,
                          task_mode: str = EMBEDDING_TASK_MODE,
                          normalization: str = EMBEDDING_NORMALIZATION,
                          material_params: dict | None = None) -> str:
    """D11/Q6: identity-отпечаток = sha256[:16] канонического JSON
    {provider family, resolved endpoint host, resolved model + revision,
    dimension (+override), task/mode, normalization, материальные параметры}.
    key/quota/timeout/route identity НЕ меняют (канонический состав).
    Каноничность: sort_keys + компактные сепараторы + UTF-8."""
    payload = {
        "provider_family": str(provider_family or "").strip().lower(),
        "endpoint_host": str(endpoint_host or "").strip().lower(),
        "model": str(model or "").strip(),
        "revision": str(revision or "").strip(),
        "dimension": int(dimension) if dimension else None,
        "dimension_override": (int(dimension_override)
                               if dimension_override else None),
        "task_mode": str(task_mode),
        "normalization": str(normalization),
        "params": {str(k): str(v) for k, v in
                   sorted((material_params or {}).items())},
    }
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def profile_identity(profile: EmbeddingProfile,
                     dimension: int | None = None) -> str:
    """Identity-отпечаток профиля (канонический JSON D11)."""
    host = ""
    try:
        from urllib.parse import urlsplit
        host = urlsplit(profile.base_url or "").hostname or ""
    except Exception:      # pragma: no cover
        host = ""
    return embedding_identity_v2(
        provider_family=_provider_of(profile.base_url) if profile.base_url
        else "",
        endpoint_host=host,
        model=profile.model,
        dimension=dimension,
    )


def classify_identity_compatibility(*, current_identity: str,
                                    stored_identity: str | None,
                                    current_dim: int | None = None,
                                    stored_dim: int | None = None,
                                    canary_verdict: str | None = None) -> str:
    """13C.4/§8.2 (ASAP 6): одна server-side классификация (backend +
    MiniApp). Семантика спеки:
    - dimension расходится → INCOMPATIBLE_DIMENSION;
    - identity-отпечатки РАЗНЫЕ (другой model/host/revision — это ДОКАЗАННО
      другое пространство) → REINDEX_REQUIRED, canary не требуется;
    - identity совпала: canary STABLE → INSTANT_COMPATIBLE (провайдер
      доказал то же пространство); canary нет/unknown → fail-safe
      COMPATIBILITY_UNKNOWN (floating-alias риск — не «наверное совместимо»);
    - canary DRIFT при той же identity → REINDEX_REQUIRED (§8.6).
    same dimension сам по себе НИКОГДА не даёт INSTANT."""
    if current_dim and stored_dim and int(current_dim) != int(stored_dim):
        return COMPAT_DIMENSION
    if canary_verdict == CANARY_DRIFT:
        return COMPAT_REINDEX
    if not stored_identity:
        return COMPAT_UNKNOWN
    if str(stored_identity) == str(current_identity):
        return (COMPAT_INSTANT if canary_verdict == CANARY_STABLE
                else COMPAT_UNKNOWN)
    return COMPAT_REINDEX


def _cosine(a: list[float], b: list[float]) -> float:
    """Косинусная близость (canary, D11: НЕ byte-hash float-векторов)."""
    try:
        if not a or not b or len(a) != len(b):
            return 0.0
        num = sum(float(x) * float(y) for x, y in zip(a, b))
        da = sum(float(x) * float(x) for x in a) ** 0.5
        db_ = sum(float(y) * float(y) for y in b) ** 0.5
        if da <= 0.0 or db_ <= 0.0:
            return 0.0
        return num / (da * db_)
    except Exception:      # pragma: no cover
        return 0.0


def _canary_cache_key(identity_fp: str, text: str) -> str:
    """Ключ embedding_cache для canary-строки (та же формула, что
    summary_memory._embed_cache_key: H(identity \\x00 casefold+strip))."""
    base = str(text).casefold().strip()
    material = f"{identity_fp}\x00{base}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


async def embedding_canary_check(llm, db, identity_fp: str, *,
                                 embed_fn=None, profile=None) -> dict:
    """Canary floating-alias (D11/Q6): 3 фиксированные строки; эталоны —
    в существующем `embedding_cache` под identity_fingerprint профиля;
    сверка КОСИНУСОМ (mean < 0.98 или min < 0.95 → drift). Недоступность
    провайдера/БД → `unknown` (fail-safe: без writes в active). Никогда
    не бросает. `embed_fn(texts)->vectors` — точка подмены в тестах."""
    out = {"verdict": CANARY_UNKNOWN, "mean": None, "min": None,
           "checked": 0, "stored": 0, "identity": str(identity_fp)[:16]}
    try:
        vectors: list[list[float]] | None = None
        if embed_fn is not None:
            vectors = list(await embed_fn(list(CANARY_TEXTS)))
        elif llm is not None:
            vectors = list(await llm.embed(list(CANARY_TEXTS)))
        if vectors is None or len(vectors) != len(CANARY_TEXTS) \
                or not all(v for v in vectors):
            return out
        # 1) Эталоны из embedding_cache (identity-колонки уже в схеме).
        stored: dict[int, list[float]] = {}
        try:
            for idx, text in enumerate(CANARY_TEXTS):
                key = _canary_cache_key(identity_fp, text)
                cursor = await db.db.execute(
                    "SELECT vector, dim FROM embedding_cache "
                    "WHERE text_hash = ? AND identity_fingerprint = ?",
                    (key, identity_fp))
                row = await cursor.fetchone()
                if row is not None:
                    stored[idx] = json.loads(str(row["vector"]))
        except Exception:
            stored = {}
        # 2) Недостающие эталоны — записать (перезапись той же identity
        #    обновляет эталон: это canary-хранилище, не пользовательские
        #    векторы; после смены identity ключи другие — смешивания нет).
        fresh: dict[int, list[float]] = {}
        for idx, vec in enumerate(vectors):
            if idx not in stored:
                fresh[idx] = vec
        try:
            now = time.time()
            provider = profile.base_url if profile is not None else ""
            model = profile.model if profile is not None else ""
            for idx, vec in fresh.items():
                key = _canary_cache_key(identity_fp, CANARY_TEXTS[idx])
                dim = len(vec)
                await db.db.execute(
                    "INSERT INTO embedding_cache(text_hash, text, vector, "
                    "dim, created_at, last_used_at, provider, model, "
                    "preprocessing_version, endpoint_fingerprint, "
                    "identity_fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(text_hash) DO UPDATE SET vector=excluded."
                    "vector, dim=excluded.dim, last_used_at=excluded."
                    "last_used_at, provider=excluded.provider, model=excluded."
                    "model, identity_fingerprint=excluded.identity_fingerprint",
                    (key, CANARY_TEXTS[idx], json.dumps(vec), dim, now, now,
                     str(provider)[:120] or None, str(model)[:120] or None,
                     None, None, identity_fp))
            await db.db.commit()
            out["stored"] = len(fresh)
        except Exception:
            out["stored"] = 0   # кэш недоступен → сверка только в памяти
        # 3) Сверка косинусом свежих против эталонных.
        sims: list[float] = []
        for idx, vec in enumerate(vectors):
            if idx not in stored:
                continue
            sims.append(_cosine(vec, stored[idx]))
        out["checked"] = len(sims)
        if not sims:
            note_canary_verdict(str(identity_fp), out["verdict"])
            return out          # первых эталонов ещё нет — unknown, не «ок»
        mean = sum(sims) / len(sims)
        low = min(sims)
        out["mean"] = round(float(mean), 6)
        out["min"] = round(float(low), 6)
        if mean < CANARY_MEAN_MIN or low < CANARY_MIN_SIMILARITY:
            out["verdict"] = CANARY_DRIFT
        else:
            out["verdict"] = CANARY_STABLE
        note_canary_verdict(str(identity_fp), out["verdict"])
        return out
    except Exception:
        logger.warning("embedding canary check failed — unknown", exc_info=True)
        return out


# ── D12 (asap5-final-fixes, T-5258, 13D/13E/13H): migration jobs ────────────
# Migration job'ы — в существующем `task_jobs` (kind='embedding_migration',
# checkpoint/cursor по прецеденту graphrag-rebuild); generation-isolated
# storage — через существующий shadow/swap `_activate` (build в shadow
# `{index}_g{generation}` → атомарная активация одной транзакцией,
# graphrag_rebuild.py). Destructive ALTER/resize запрещён (ΔDDL=0).

MIGRATION_JOB_KIND = "embedding_migration"
MIGRATION_OWNER = "memory"

# ── ASAP 6 §8 (P1): multi-chat/namespace-safe embedding generations ─────────
# §8.1: (namespace, semantic_index) → ровно одна ACTIVE generation (v34).
# §8.2: классы совместимости — server-side по embedding identity (NOT dims).
# §8.3: global model change → новый default для новых чатов; существующие
#       pinned до controlled migration (один Save не перевекторизует молча).
# §8.4: per-chat/namespace override → target generation только этого scope.
# §8.5: смена target во время rebuild → SUPERSEDED, stale worker не promote.
# §8.6: provider alias drift → canary гейтит запись в ACTIVE (FTS fail-soft).

# Namespace по умолчанию: существующие данные (легаси-строки v34) и все
# легаси-вызовы живут в 'default' — retrieval/память не ломаются.
DEFAULT_NAMESPACE = "default"


def shadow_table_name(index_name: str, generation: int) -> str:
    """Имя shadow-таблицы поколения (та же конвенция, что graphrag)."""
    return f"{index_name}_g{int(generation)}"


# ── §8.6: canary-гейт записи (process-level кэш вердиктов) ──────────────────
# DRIFT блокирует запись векторов в ACTIVE на TTL (провайдер молча поменял
# space под тем же alias); свежий STABLE снимает блок. UNKNOWN/нет пробы —
# НЕ блокирует steady-state (fingerprint identity остаётся первичным гейтом).

_CANARY_TTL_SECONDS = 6 * 3600
_CANARY_VERDICTS: dict[str, tuple[str, float]] = {}
_CANARY_BLOCK_LOG: dict[str, float] = {}
_CANARY_BLOCK_LOG_COOLDOWN_S = 600.0


def note_canary_verdict(identity_fp: str, verdict: str, *,
                        now: float | None = None) -> None:
    """Запомнить вердикт canary для identity (пишется и из
    `embedding_canary_check`). Никогда не бросает."""
    try:
        _CANARY_VERDICTS[str(identity_fp or "")] = (
            str(verdict or CANARY_UNKNOWN),
            float(now if now is not None else time.time()))
    except Exception:
        pass


def canary_verdict_cached(identity_fp: str, *,
                          now: float | None = None) -> str:
    """Свежий (в пределах TTL) вердикт canary; '' — пробы нет/устарела."""
    try:
        entry = _CANARY_VERDICTS.get(str(identity_fp or ""))
        if entry is None:
            return ""
        verdict, ts = entry
        age = float(now if now is not None else time.time()) - float(ts)
        if age < 0 or age > _CANARY_TTL_SECONDS:
            return ""
        return str(verdict)
    except Exception:
        return ""


def canary_blocks_writes(identity_fp: str, *, now: float | None = None) -> bool:
    """§8.6: TRUE только при доказанном drift (canary DRIFT в пределах TTL)."""
    return canary_verdict_cached(identity_fp, now=now) == CANARY_DRIFT


def _note_canary_block_event(index_name: str, identity_fp: str, *,
                             now: float | None = None) -> None:
    """Коалисированное событие о блокировке записи (не спамим, §8.6)."""
    try:
        ts = float(now if now is not None else time.time())
        key = f"{index_name}:{identity_fp}"
        prev = _CANARY_BLOCK_LOG.get(key)
        if prev is not None and (ts - prev) < _CANARY_BLOCK_LOG_COOLDOWN_S:
            return
        _CANARY_BLOCK_LOG[key] = ts
        try:
            from services.mca_retrieval_context import emit_stage_event
            emit_stage_event(
                "vector_write", "skipped",
                reason_code="embedding_generation_changed",
                model=str(identity_fp)[:16],
                extra="canary_drift")
        except Exception:
            pass
        logger.warning(
            "embedding canary DRIFT — vector writes blocked for ACTIVE "
            "(FTS fail-soft) | index=%s identity=%s", index_name,
            str(identity_fp)[:16])
    except Exception:
        pass


# ── §8.1: ownership-resolve (O(1) по (namespace, index)) ────────────────────

async def resolve_active_generation(db, index_name: str, *,
                                    namespace: str = DEFAULT_NAMESPACE,
                                    ) -> dict | None:
    """ACTIVE-поколение (namespace, index) — единственный авторитет сёрвинга
    (§8.1). Легаси-данные (namespace 'default') резолвятся тем же путём.
    Fail-open: нет метода/ошибка → None."""
    get = getattr(db, "get_active_embedding_generation", None)
    if get is None:
        return None
    try:
        return await get(str(index_name),
                         namespace=str(namespace or DEFAULT_NAMESPACE))
    except TypeError:
        # тест-двойники/легаси-обёртки без namespace-параметра
        try:
            return await get(str(index_name))
        except Exception:
            return None
    except Exception:
        return None


# ── §8.2/§8.3: честный план смены модели (backend-часть UI-предупреждения) ──

async def plan_embedding_change(db, *, index_name: str,
                                current_identity: str,
                                current_dims: int | None = None,
                                namespace: str = DEFAULT_NAMESPACE,
                                canary_verdict: str | None = None,
                                ) -> dict:
    """Классификация смены embedding-конфига против ACTIVE поколения
    (namespace, index) — §8.2/13C.4. НЕ меняет ничего (только честный план):
    - INSTANT_COMPATIBLE → identity совпала (key/quota/route) — reindex не
      нужен, та же generation продолжается (13D.2);
    - REINDEX_REQUIRED / INCOMPATIBLE_DIMENSION / COMPATIBILITY_UNKNOWN →
      in-place смена ЗАПРЕЩЕНА (13D.3): нужна новая target-generation,
      ACTIVE остаётся сёрвить до promotion (§8.4).
    Никогда не бросает."""
    active = await resolve_active_generation(db, index_name,
                                             namespace=namespace)
    if active is None:
        return {"index": index_name, "namespace": namespace,
                "compat": COMPAT_UNKNOWN, "reindex_required": True,
                "action": "register_active", "active": None,
                "canary_verdict": canary_verdict}
    verdict = canary_verdict or canary_verdict_cached(str(current_identity))
    compat = classify_identity_compatibility(
        current_identity=str(current_identity),
        stored_identity=str(active.get("fingerprint") or ""),
        current_dim=(int(current_dims) if current_dims else None),
        stored_dim=active.get("dims"),
        canary_verdict=verdict or None)
    instant = compat == COMPAT_INSTANT
    return {"index": index_name, "namespace": namespace,
            "compat": compat, "reindex_required": not instant,
            "action": "none" if instant else "target_generation",
            "active": {
                "generation_id": str(active.get("generation_id") or ""),
                "generation": active.get("generation"),
                "fingerprint": active.get("fingerprint"),
                "dims": active.get("dims"),
                "status": active.get("status"),
            },
            "canary_verdict": verdict or CANARY_UNKNOWN}


# ── §8.4/§8.5: controlled migration (target-generation, supersede) ──────────

async def begin_embedding_migration(db, *, index_name: str,
                                    target_fingerprint: str,
                                    namespace: str = DEFAULT_NAMESPACE,
                                    provider=None, model=None, dims=None,
                                    preprocessing_version=None,
                                    endpoint_fingerprint=None,
                                    config_revision: str | None = None,
                                    total: int | None = None,
                                    ) -> dict:
    """Контролируемый старт миграции identity в scope (namespace, index).

    §8.3/13F.1: НЕ трогает ACTIVE другого identity (один Save не переводит
    память молча). §8.5/13G.2: если ACTIVE уже с target-identity — no-op
    (A→B→A без бессмысленного rebuild); иначе предыдущие незавершённые
    targets → SUPERSEDED (stale worker не сможет promote) и регистрируется
    новая target-generation (`building`) + migration job (coalesce по
    namespace+index+target). ACTIVE остаётся active до promotion.
    Никогда не бросает (fail-open → {"action": "failed"})."""
    ns = str(namespace or DEFAULT_NAMESPACE)
    try:
        active = await resolve_active_generation(db, index_name, namespace=ns)
        if active is not None and \
                str(active.get("fingerprint") or "") == str(target_fingerprint):
            # §8.5 A→B→A: active уже целевой — rebuild не нужен.
            return {"action": "none", "reason": "already_active",
                    "index": index_name, "namespace": ns,
                    "generation": active.get("generation")}
        # §8.5 B→SUPERSEDED: незавершённые targets ИНОГО identity — вон.
        superseded = 0
        sup = getattr(db, "supersede_building_generations", None)
        if sup is not None:
            superseded = await sup(index_name, namespace=ns,
                                   keep_fingerprint=str(target_fingerprint))
        # §8.5 (не плодить дубли): незавершённая target ТОГО ЖЕ identity
        # (повторный Save/рестарт) — reuse, новая строка/job не создаются.
        row = None
        by_fp = getattr(db, "get_generation_by_fingerprint", None)
        if by_fp is not None:
            try:
                row = await by_fp(index_name, str(target_fingerprint),
                                  namespace=ns)
            except TypeError:
                row = None
        if row is not None and str(row.get("status") or "") in (
                "building", "building_target", "catching_up", "ready"):
            gen = int(row.get("generation") or 0)
            if gen <= 0:
                return {"action": "failed", "index": index_name,
                        "namespace": ns, "superseded": superseded}
            # revision строки — авторитет (payload обязан совпадать с ней)
            config_revision = str(row.get("config_revision") or "") or \
                config_revision
            job_id = await enqueue_embedding_migration(
                db, index_name=index_name,
                source_generation=int((active or {}).get("generation") or 0),
                target_generation=gen, fingerprint=str(target_fingerprint),
                total=int(total or 0), namespace=ns,
                config_revision=config_revision)
            logger.info("embedding migration reused | index=%s ns=%s "
                        "target_gen=%d status=%s", index_name, ns, gen,
                        row.get("status"))
            return {"action": "building", "index": index_name, "namespace": ns,
                    "target_generation": gen,
                    "generation_id": str(row.get("generation_id") or ""),
                    "superseded": int(superseded),
                    "active_generation": (active or {}).get("generation"),
                    "job_id": job_id, "reused": True}
        gen = await db.register_embedding_target_generation(
            index_name, str(target_fingerprint), provider=provider,
            model=model, dims=dims,
            preprocessing_version=preprocessing_version,
            endpoint_fingerprint=endpoint_fingerprint, namespace=ns,
            config_revision=config_revision)
        if gen is None:
            return {"action": "failed", "index": index_name,
                    "namespace": ns, "superseded": superseded}
        row = await db.get_generation_by_fingerprint(
            index_name, str(target_fingerprint), namespace=ns)
        job_id = await enqueue_embedding_migration(
            db, index_name=index_name,
            source_generation=int((active or {}).get("generation") or 0),
            target_generation=int(gen), fingerprint=str(target_fingerprint),
            total=int(total or 0), namespace=ns,
            config_revision=config_revision)
        logger.info(
            "embedding migration started | index=%s ns=%s target_gen=%s "
            "superseded=%d active=%s", index_name, ns, gen, superseded,
            (active or {}).get("generation"))
        return {"action": "building", "index": index_name, "namespace": ns,
                "target_generation": int(gen),
                "generation_id": str((row or {}).get("generation_id") or ""),
                "superseded": int(superseded),
                "active_generation": (active or {}).get("generation"),
                "job_id": job_id}
    except Exception:
        logger.warning("begin_embedding_migration failed | index=%s",
                       index_name, exc_info=True)
        return {"action": "failed", "index": index_name,
                "namespace": str(namespace or DEFAULT_NAMESPACE)}


async def enqueue_embedding_migration(db, *, index_name: str,
                                      source_generation: int,
                                      target_generation: int,
                                      fingerprint: str,
                                      total: int,
                                      namespace: str = DEFAULT_NAMESPACE,
                                      config_revision: str | None = None,
                                      ) -> str | None:
    """Зарегистрировать migration job (task_jobs, REUSE v14, ΔDDL=0).
    Coalesce по namespace+index+target — повторный вызов не плодит дубли.
    Payload содержит namespace/config_revision — stale-worker guard §8.5."""
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        ns = str(namespace or DEFAULT_NAMESPACE)
        return await store.enqueue(
            owner=MIGRATION_OWNER, kind=MIGRATION_JOB_KIND,
            coalesce_key=f"embedding_migration:{ns}:{index_name}:"
                         f"{int(target_generation)}",
            payload=json.dumps({
                "index": index_name,
                "namespace": ns,
                "source_generation": int(source_generation),
                "target_generation": int(target_generation),
                "fingerprint": str(fingerprint),
                "config_revision": str(config_revision or ""),
                "total": int(total),
            }, ensure_ascii=False))
    except Exception:
        logger.warning("embedding migration enqueue failed | index=%s",
                       index_name, exc_info=True)
        return None


async def migration_jobs_snapshot(db, *, limit: int = 16) -> list[dict]:
    """Снимок migration job'ов (structured state; дляobservability 13M)."""
    out: list[dict] = []
    try:
        cursor = await db.db.execute(
            "SELECT job_id, status, reason_code, payload, progress_at, "
            "created_at, updated_at FROM task_jobs WHERE kind = ? "
            "ORDER BY created_at DESC LIMIT ?", (MIGRATION_JOB_KIND,
                                                 int(limit)))
        for row in await cursor.fetchall():
            job = dict(row)
            try:
                job["payload"] = json.loads(job.pop("payload") or "{}")
            except ValueError:
                job["payload"] = {}
            out.append(job)
    except Exception:
        logger.warning("embedding migration snapshot failed", exc_info=True)
    return out


async def _migration_live_swap(memory, index_name: str, shadow: str,
                               fp: str):
    """Физический swap live↔shadow для namespace 'default' (§13H/13E.3) —
    ТОТ ЖЕ контракт, что graphrag `_activate` (§3/§66): внутри транзакции
    re-check identity, DROP live → CREATE по каноническому DDL → копия
    ТОЛЬКО строк с живым source-фактом (анти-orphan) → DROP shadow.
    DDL в SQLite транзакционен: откат возвращает прежнюю таблицу (raw
    `graph_facts`/`smart_archive_facts` не трогаются — R18). Возвращает
    callback для `db.promote_embedding_generation(data_swap=...)` либо
    None (индекс вне _INDEX_SPECS)."""
    try:
        from services.graphrag_rebuild import (_INDEX_SPECS, _live_ddl)
        if index_name not in _INDEX_SPECS:
            return None
        spec = _INDEX_SPECS[index_name]
        live = spec["live"]
        int8 = bool(memory._vec_int8)
        insert_cols = spec["insert_cols"] + (", embedding_i8" if int8 else "")
        copy_cols = spec["copy_cols"] + (", embedding_i8" if int8 else "")
        live_sql = _live_ddl(memory, index_name)

        async def _swap(conn):
            # M-ASAP32-2: re-check identity ВНУТРИ транзакции — смена конфига
            # в окне validate→promote откатывает всю promotion (stale worker).
            if memory._identity_fingerprint() != fp:
                raise RuntimeError("fingerprint_changed")
            await conn.execute(f"DROP TABLE IF EXISTS {live}")
            await conn.execute(live_sql)
            await conn.execute(
                f"INSERT INTO {live}({insert_cols}) SELECT {copy_cols} "
                f"FROM {shadow} WHERE fact_id IN "
                f"(SELECT id FROM {spec['source']})")
            await conn.execute(f"DROP TABLE IF EXISTS {shadow}")

        return _swap
    except Exception:
        logger.warning("migration live swap prepare failed | index=%s",
                       index_name, exc_info=True)
        return None


async def _migration_fetch_missing(memory, spec: dict, shadow: str,
                                   limit: int) -> list[dict]:
    """Delta catch-up (13E.2): source-строки, ОТСУТСТВУЮЩИЕ в shadow
    (вставлены после прохода курсора с меньшим id — курсор их не догнал).
    Анти-join по факту (тот же приём, что validate-фаза graphrag), bounded
    LIMIT, порядок по id. Никогда не бросает (ошибка → [])."""
    try:
        now = int(time.time())
        sql = (f"SELECT {spec['source_cols']} FROM {spec['source']} "
               f"WHERE id NOT IN (SELECT fact_id FROM {shadow}) ")
        params: list = []
        if spec.get("eligible_ts"):
            sql += "AND (expires_at IS NULL OR expires_at > ?) "
            params.append(now)
        sql += "ORDER BY id LIMIT ?"
        params.append(max(1, int(limit)))
        cursor = await memory.db.db.execute(sql, tuple(params))
        return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        logger.warning("migration delta fetch failed", exc_info=True)
        return []


async def _migration_coverage_missing(db, spec: dict, shadow: str) -> int:
    """Число eligible-source-строк без вектора в shadow — promotion gate
    13E.2 (пока > 0, promoting запрещён). Никогда не бросает (ошибка → -1,
    трактуется как «не покрыто»)."""
    try:
        now = int(time.time())
        sql = (f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id NOT IN "
               f"(SELECT fact_id FROM {shadow})")
        params: list = []
        if spec.get("eligible_ts"):
            sql += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(now)
        cursor = await db.db.execute(sql, tuple(params))
        row = await cursor.fetchone()
        return int(row["c"]) if row is not None else -1
    except Exception:
        return -1


async def run_embedding_migration_chunk(memory, db, job_id: str, *,
                                        embed_fn=None) -> dict:
    """Один чекпоинт-чанк migration job'а (13E.1: resumable/chunked — никаких
    one-shot jobs): source-строки под cursor → embed под текущий fingerprint →
    INSERT в generation-isolated shadow `{index}_g{gen}` (существующие хелперы
    graphrag, ΔDDL=0) → checkpoint. §8.5 (ASAP 6): ПЕРЕД каждым чанком строка
    target-поколения перечитывается — superseded/cancelled/failed target и
    config_revision-mismatch = stale worker (job завершается, writes/promote
    запрещены). §8.4/13E.2: после прохода курсора — delta catch-up (анти-join
    source↔shadow), promotion ТОЛЬКО при full coverage; promotion — атомарная
    (`db.promote_embedding_generation`): namespace 'default' — физический
    swap live↔shadow + реестр в одной транзакции (readers не смешивают),
    иные namespace — атомарный реестр-указатель (сёрвинг не-default —
    будущее §8.7). Возвращает {processed, remaining, done, phase, promoted}
    (никогда не бросает)."""
    out: dict = {"processed": 0, "remaining": 0, "done": False,
                 "phase": None, "promoted": False}
    store = None
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        cursor = await db.db.execute(
            "SELECT payload, status FROM task_jobs WHERE job_id = ?",
            (str(job_id),))
        row = await cursor.fetchone()
        if row is None:
            return out
        try:
            payload = json.loads(str(row["payload"]) or "{}")
        except ValueError:
            payload = {}
        index_name = str(payload.get("index") or "")
        generation = int(payload.get("target_generation") or 0)
        ns = str(payload.get("namespace") or DEFAULT_NAMESPACE)
        config_revision = str(payload.get("config_revision") or "")
        if not index_name or generation <= 0:
            return out
        from services.graphrag_rebuild import (_INDEX_SPECS, _adaptive_batch_size,
                                               _create_shadow, _fetch_batch,
                                               _insert_shadow_rows,
                                               _shadow_name)
        if index_name not in _INDEX_SPECS:
            return out
        spec = _INDEX_SPECS[index_name]
        shadow = _shadow_name(index_name, generation)
        # ── §8.5: stale-worker guard — перечитали target перед работой ────
        gen_row = None
        get_gen = getattr(db, "get_embedding_generation", None)
        if get_gen is not None:
            gen_row = await get_gen(index_name, generation, namespace=ns)
        if gen_row is not None:
            status = str(gen_row.get("status") or "")
            if status in ("superseded", "cancelled"):
                await store.finish(str(job_id), status="cancelled",
                                   reason_code="embedding_generation_changed")
                out["phase"] = "superseded"
                return out
            if status == "failed":
                await store.finish(str(job_id), status="failed",
                                   reason_code="fingerprint_changed")
                out["phase"] = "failed"
                return out
            if config_revision and str(gen_row.get("config_revision")
                                       or "") != config_revision:
                # конфиг поменялся под работающим worker'ом — promote/write
                # запрещены (13G.1).
                await store.finish(str(job_id), status="failed",
                                   reason_code="fingerprint_changed")
                out["phase"] = "stale_worker"
                return out
            if status == "active":
                await store.finish(str(job_id), status="completed")
                out["done"] = True
                out["promoted"] = True
                out["phase"] = "already_active"
                return out
            # машина 13E: building → building_target (осознанный старт).
            if status == "building":
                await db.set_embedding_generation_status(
                    str(gen_row["generation_id"]), "building_target")
                status = "building_target"
        elif gen_row is None and getattr(db, "get_embedding_generation",
                                         None) is not None:
            # строка обязана существовать (target регистрируется до job'а);
            # отсутствие = target удалён/superseded извне — честный отказ.
            await store.finish(str(job_id), status="cancelled",
                               reason_code="embedding_generation_changed")
            out["phase"] = "missing_target"
            return out
        last_id = 0
        processed_before = 0
        try:
            cp = await store.get_checkpoint(str(job_id))
            if cp and cp.get("cursor"):
                cur = json.loads(str(cp["cursor"]))
                last_id = int(cur.get("last_id") or 0)
                processed_before = int(cur.get("processed") or 0)
                out["phase"] = str(cur.get("phase") or "backfill")
        except Exception:
            last_id = 0
        await _create_shadow(memory, index_name, shadow)

        async def _embed_insert(batch: list[dict]) -> bool:
            texts = [str(b["fact"]) for b in batch]
            if embed_fn is not None:
                vectors = list(await embed_fn(texts))
            else:
                vectors = list(await memory._embed(texts))
            if len(vectors) != len(batch):
                return False
            await _insert_shadow_rows(memory, spec, shadow, batch, vectors)
            return True

        # ── Фаза A (backfill): cursor-скан source ─────────────────────────
        batch = await _fetch_batch(memory, spec, last_id)
        if batch:
            if not await _embed_insert(batch):
                return out
            processed = processed_before + len(batch)
            await store.save_checkpoint(
                str(job_id),
                cursor_token=json.dumps({"last_id": int(batch[-1]["id"]),
                                         "processed": processed,
                                         "phase": "backfill"}),
                processed=processed,
                checkpoint_ref=f"cp:embedding_migration:{index_name}:"
                               f"{generation}")
            out["processed"] = len(batch)
            out["phase"] = "backfill"
            cur = await db.db.execute(
                f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id > ?",
                (int(batch[-1]["id"]),))
            out["remaining"] = int((await cur.fetchone())["c"])
            out["done"] = out["remaining"] == 0
            return out
        # Курсор дошёл до конца → переход к delta (13E.2).
        if gen_row is not None and str(gen_row.get("status")) == \
                "building_target":
            await db.set_embedding_generation_status(
                str(gen_row["generation_id"]), "catching_up")
            gen_row = dict(gen_row, status="catching_up")
        out["phase"] = "catching_up"
        # ── Фаза B (delta catch-up): source-строки вне shadow ─────────────
        try:
            delta_limit = max(int(_adaptive_batch_size()), 8)
        except Exception:
            delta_limit = 64
        delta = await _migration_fetch_missing(memory, spec, shadow,
                                               delta_limit)
        if delta:
            if not await _embed_insert(delta):
                return out
            out["processed"] = len(delta)
            await store.save_checkpoint(
                str(job_id),
                cursor_token=json.dumps({"last_id": last_id,
                                         "processed": processed_before,
                                         "phase": "catching_up"}),
                processed=processed_before,
                checkpoint_ref=f"cp:embedding_migration:{index_name}:"
                               f"{generation}")
            return out
        # ── Promotion gate 13E.2: promotion только при full coverage ──────
        missing = await _migration_coverage_missing(db, spec, shadow)
        if missing != 0:
            out["remaining"] = max(0, missing)
            return out
        if gen_row is None:
            return out
        gid = str(gen_row["generation_id"])
        if str(gen_row.get("status")) == "catching_up":
            if not await db.set_embedding_generation_status(gid, "ready"):
                return out
            gen_row = dict(gen_row, status="ready")
        if str(gen_row.get("status")) != "ready":
            return out
        fp = str(gen_row.get("fingerprint") or "")
        swap = None
        if ns == DEFAULT_NAMESPACE:
            swap = await _migration_live_swap(memory, index_name, shadow, fp)
            if swap is None:
                # live-swap подготовить не удалось — promotion БЕЗ физической
                # смены storage означала бы mixed-space сёрвинг (запрещено
                # §8.2). Честный отказ: job остаётся в ready, retry следующим
                # чанком; readers продолжают читать old ACTIVE.
                logger.error("embedding migration: live swap unavailable — "
                             "promotion refused | index=%s gen=%d",
                             index_name, generation)
                out["phase"] = "promote_blocked"
                return out
        promoted = await db.promote_embedding_generation(
            index_name, gid, namespace=ns, expected_fingerprint=fp,
            expected_config_revision=(config_revision or None),
            data_swap=swap)
        if promoted:
            await store.finish(str(job_id), status="completed")
            out["done"] = True
            out["promoted"] = True
            out["phase"] = "promoted"
        else:
            # гонка/смена конфига между ready и promote — без partial-состояний.
            await store.finish(str(job_id), status="cancelled",
                               reason_code="embedding_generation_changed")
            out["phase"] = "promote_refused"
        return out
    except Exception:
        logger.warning("embedding migration chunk failed | job=%s",
                       str(job_id)[:16], exc_info=True)
        return out


__all__ = [
    "Priority", "EmbeddingCredential", "EmbeddingQuotaGroup",
    "EmbeddingProviderAdapter", "GeminiEmbeddingAdapter",
    "OpenAICompatibleEmbeddingAdapter", "EmbeddingExecutor",
    "QuotaGroupRegistry", "AdaptiveController", "PriorityScheduler",
    "RebuildLease", "RateLimitInfo",
    "UNKNOWN_GROUP_ID", "GROUP_UNKNOWN",
    "control_plane_enabled", "quota_group_cooldown_enabled",
    "quota_kind_parking_enabled", "resume_backoff_enabled",
    "priority_scheduler_enabled", "adaptive_concurrency_enabled",
    "async_batch_enabled", "build_credential_pool",
    "parse_quota_group_labels", "resolve_quota_group",
    "pool_rotation_diagnosis", "classify_rate_limit",
    "retry_after_seconds", "is_quota_unavailable",
    "segment_text_lossless", "estimate_tokens", "execute_embed",
    "get_executor", "set_priority", "reset_priority", "current_priority",
    "REGISTRY", "CONTROLLER", "SCHEDULER", "coalesced_state_log",
    "provider_panel", "vector_memory_panel",
    "EmbeddingGroupCoolingDown", "EmbeddingConcurrencyBusy",
    "EmbeddingBudgetExhausted", "EmbeddingControlPlaneError",
    "is_serviceability_error",
    # D11/D12 (asap5-final-fixes, T-5256…T-5258)
    "EmbeddingProfile", "resolve_embedding_profiles", "profile_identity",
    "embedding_identity_v2", "classify_identity_compatibility",
    "COMPAT_INSTANT", "COMPAT_REINDEX", "COMPAT_DIMENSION", "COMPAT_UNKNOWN",
    "CANARY_STABLE", "CANARY_DRIFT", "CANARY_UNKNOWN", "CANARY_TEXTS",
    "embedding_canary_check", "MIGRATION_JOB_KIND",
    "enqueue_embedding_migration", "migration_jobs_snapshot",
    "run_embedding_migration_chunk", "shadow_table_name",
    # ASAP 6 §8 (multi-chat/namespace-safe generations)
    "DEFAULT_NAMESPACE", "resolve_active_generation", "plan_embedding_change",
    "begin_embedding_migration", "note_canary_verdict",
    "canary_verdict_cached", "canary_blocks_writes",
]
