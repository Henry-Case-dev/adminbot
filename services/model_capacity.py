"""ASAP-3 (round 1028, ADR-1028-2 D1/D2) — model-aware capacity Direct Chat.

Нейтральный consumer-side модуль: физическое context-window модели и формула
полного payload-бюджета. Summary-пайплайн этот модуль НЕ импортирует и не
меняется (§0/D11); `resolve_context_tokens`/`safe_budget` из token_counter
сохраняют семантику ADR-1019-8 для всех не-direct потребителей.

D1 — источник окна (в порядке приоритета):
  1. env `CHAT_MODEL_CONTEXT_WINDOW` (override, priority above map);
  2. префикс-матч по карте известных моделей (`MODEL_CONTEXT_WINDOWS`);
  3. неизвестная модель → env `CHAT_UNKNOWN_MODEL_WINDOW` (default 16384,
     консервативный fallback) + однократный WARN на модель — источник решения
     виден в `CONTEXT_CAPACITY` (`window_source`), это НЕ «тихий hidden cap».

D2 — формула (safety-множитель применяется РОВНО ОДИН раз):
    window         = resolve_model_context_window(model)
    external       = оценка system+persona+tool schemas (MCA-07 REUSE,
                     передаётся вызывающим; fail-open 0)
    output_reserve = max(1024, int(window × limits.chat_budget_reserve_ratio))
    available      = safe_budget(window − external − output_reserve)
    budget         = policy(available, limits.chat_context_budget_tokens):
                       -1 → available (Unlimited, физический потолок)
                       0/None → min(available, 16000) (Dynamic)
                       >0 → min(available, cap) (явный cap)

Никогда не бросает (R3); все функции — чистые/без I/O, кроме логов.

═══════════════════════════════════════════════════════════════════════════
ASAP-3.1 (round 1028, ADR-1028-3 D1, spec раздел 3) — Model Capacity Resolver.
Структурированный резолв по реальной тройке `provider/base_url + model`:

  precedence (детерминированный, §4):
    1. developer_override — `models.chat_context_window_override` > 0
       (hot-first; env-слой — прежний `CHAT_MODEL_CONTEXT_WINDOW`);
    2. runtime — metadata фактического backend (адаптеры локальных рантаймов);
    3. provider_catalog — каталог провайдера (класс OpenRouter);
    4. registry — verified internal registry (наследник MODEL_CONTEXT_WINDOWS);
    5. fallback — консервативный аварийный путь (<=16384) + WARNING
       `MODEL_CAPACITY_FALLBACK` + метрика; НИКОГДА не «нормальный путь» (§8).

  `effective = min(runtime, provider/model)` (§5); локальный 16K при 128K
  используется полностью. Кэш по ключу provider/base_url/model/override c
  TTL (Q9): remote catalogs 24 ч (`MODEL_CAPACITY_CACHE_TTL_SECONDS`),
  локальные runtime-адаптеры — жёсткий потолок 300 с. Инвалидация §38: ключ
  включает model/base_url/override → их смена = новый ключ;
  `invalidate_capacity_cache()` — config reload / explicit refresh.

  Kill-switch `MODEL_CAPACITY_RESOLVER_ENABLED` (env-only, default ON):
  OFF → функции-legacy ниже работают байт-в-байт по-прежнему (карта + env +
  fallback 16384; прецедент DIRECT_CONTEXT_COMPOSER_ENABLED).

  Adapters (Q8, только по реальным классам подключений; fail-open, никогда
  не блокируют резолв — таймаут 2 с, ошибка = «адаптер недоступен»):
    * OpenRouter (host openrouter.ai) — GET /api/v1/models → `context_length`;
    * llama.cpp (локальный) — GET /props → `n_ctx`;
    * Ollama (порт 11434) — GET /api/ps → running `context_length`;
    * vLLM (локальный) — GET /model_info → `max_model_len` (config
      introspection); недоступен → registry + developer override (санкция
      spec Q8; НЕ выдумывать из имени модели).

  ASAP-3.2 (ADR-1028-5 D6/D7, T-4202/T-4203) — Text Capacity Resolver
  расширение:
    * NanoGPT (host nano-gpt.com) — ОТДЕЛЬНЫЙ provider adapter вместо
      registry guess: live/public каталог `GET /api/v1/models?detailed=true`
      (схема верифицирована по официальным docs: `context_length` /
      `max_output_tokens` per model) → source=`provider_catalog`;
      каталог недоступен → registry/fallback, Analytics честно показывает
      source (§53);
    * Direct DeepSeek (api.deepseek.com) — отдельная identity (не generic
      host); machine-readable context catalog нет → verified official
      registry entry, source=`verified_registry`, НЕ `provider_catalog`
      (§54);
    * OpenRouter adapter сохранён (§55); local runtime (llama.cpp/Ollama/
      vLLM) сохранён (§19);
    * Unknown provider — НЕ угадывается из URL (§56): лестница до
      conservative fallback, source виден потребителям (§8 badge);
    * Discovery timeout 2 с + TTL-кэш (Q9) — metadata fetch не задерживает
      user requests; failure НЕ блокирует generation (§57); повторные
      попытки — по TTL/инвалидации, не в hot path.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass

from config.settings import settings
from services import hot_config as hot
from services.token_counter import safe_budget

logger = logging.getLogger(__name__)

# ── D1: карта физических окон известных моделей (lower-case префикс-матч) ───
# Значения — консервативные публичные лимиты семейств; точная настройка под
# конкретный деплой — env `CHAT_MODEL_CONTEXT_WINDOW` (без релиза).
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # DeepSeek (V3/R1 — 128K, прецедент токенизатора проекта).
    "deepseek-chat": 131072,
    "deepseek-reasoner": 131072,
    "deepseek-r1": 131072,
    "deepseek-v3": 131072,
    "deepseek-v2": 131072,
    "deepseek-coder": 131072,
    # ASAP-3.1 (Q8.1): фактически используемые прод-модели (инцидент §74/§102:
    # nano-gpt `deepseek/deepseek-v4.1-flash`, fallback `deepseek-flash`) —
    # раньше не матчились и молча получали 16384.
    "deepseek-v4": 131072,
    "deepseek-flash": 131072,
    # OpenAI.
    "gpt-4o-mini": 128000,
    "gpt-4o": 128000,
    "gpt-4.1": 1047576,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    "o3-mini": 200000,
    "o4-mini": 200000,
    # Qwen.
    "qwen2.5": 131072,
    "qwen-2.5": 131072,
    "qwen-max": 32768,
    "qwen-plus": 131072,
    "qwen-turbo": 1000000,
    "qwen3": 131072,
    # Llama.
    "llama-3.3": 131072,
    "llama-3.1": 131072,
    "llama-3": 8192,
    # Claude (3+/4 — 200K).
    "claude-": 200000,
    # Gemini.
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash": 1048576,
    "gemini-2.0": 1048576,
    "gemini-1.5-pro": 2097152,
    "gemini-1.5-flash": 1048576,
    # Mistral.
    "mistral-large": 131072,
    "mistral-small": 131072,
    "codestral": 262144,
    # GLM / другие.
    "glm-4": 131072,
    "glm4": 131072,
    "kimi": 131072,
    "moonshot": 131072,
}

# Окно резолвится один раз на процесс (карта/env стабильны в рантайме);
# WARN «неизвестная модель» — ровно один раз на имя модели.
_WINDOW_CACHE: dict[str, tuple[int, str]] = {}
_WARNED_UNKNOWN: set[str] = set()

WINDOW_SOURCE_MAP = "model_map"
WINDOW_SOURCE_ENV = "env_override"
WINDOW_SOURCE_FALLBACK = "unknown_fallback"


def _env_override_window() -> int | None:
    """`CHAT_MODEL_CONTEXT_WINDOW` (env-only ClassVar); None/мусор → None."""
    try:
        value = getattr(settings, "CHAT_MODEL_CONTEXT_WINDOW", None)
        if value is None:
            return None
        window = int(value)
        return window if window > 0 else None
    except Exception:      # pragma: no cover - защитная ветка
        return None


def _unknown_window() -> int:
    """`CHAT_UNKNOWN_MODEL_WINDOW` (default 16384); мусор → дефолт."""
    try:
        window = int(getattr(settings, "CHAT_UNKNOWN_MODEL_WINDOW", 16384))
        return window if window > 0 else 16384
    except Exception:      # pragma: no cover - защитная ветка
        return 16384


def _match_model_window(model_name: str) -> int | None:
    """Префикс-матч по карте (lower-case); longest-prefix приоритет.

    ASAP-3.1: понимает формат `org/model` (OpenAI/OpenRouter-стиль,
    напр. `deepseek/deepseek-v4.1-flash` → суффикс `deepseek-v4.1-flash`)."""
    name = str(model_name or "").strip().lower()
    if not name:
        return None
    candidates = [name]
    if "/" in name:
        candidates.append(name.rsplit("/", 1)[1])
    for probe in candidates:
        best_key = ""
        best_window = None
        for key, window in MODEL_CONTEXT_WINDOWS.items():
            if probe.startswith(key) and len(key) > len(best_key):
                best_key = key
                best_window = int(window)
        if best_window is not None:
            return best_window
    return None


def resolve_model_context_window(model_name: str | None) -> tuple[int, str]:
    """D1: ``(window, window_source ∈ {model_map, env_override,
    unknown_fallback})``. Не бросает; результат кэшируется по имени модели
    (env в рантайме не меняется — hot-перезагрузка этих ClassVar не
    поддерживается проектом, прецедент `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`)."""
    name = str(model_name or "").strip()
    cache_key = name.lower()
    cached = _WINDOW_CACHE.get(cache_key)
    if cached is not None:
        return cached
    override = _env_override_window()
    if override is not None:
        result = (override, WINDOW_SOURCE_ENV)
    else:
        mapped = _match_model_window(name)
        if mapped is not None:
            result = (mapped, WINDOW_SOURCE_MAP)
        else:
            result = (_unknown_window(), WINDOW_SOURCE_FALLBACK)
            if name and name.lower() not in _WARNED_UNKNOWN:
                _WARNED_UNKNOWN.add(name.lower())
                logger.warning(
                    "model_capacity: unknown model %r — conservative "
                    "window=%d (CHAT_UNKNOWN_MODEL_WINDOW); настройте "
                    "CHAT_MODEL_CONTEXT_WINDOW для точного окна",
                    name, result[0])
    _WINDOW_CACHE[cache_key] = result
    return result


def resolve_effective_window(primary_model: str | None,
                             fallback_model: str | None) -> tuple[int, str]:
    """D1: для LLM-fallback-модели берётся **min** окно primary/fallback
    (композер не знает, каким финалом ответит провайдер — conservative).
    Источник — резолв primary (fallback только сужает; факт сужения виден
    в сравнении `window` с primary-окном в логе CONTEXT_CAPACITY)."""
    primary_window, source = resolve_model_context_window(primary_model)
    name = str(fallback_model or "").strip()
    if not name:
        return primary_window, source
    fallback_window, _ = resolve_model_context_window(name)
    if fallback_window > 0 and fallback_window < primary_window:
        return fallback_window, source
    return primary_window, source


# ── D2: формула полного payload (safety-множитель РОВНО ОДИН раз) ───────────

OUTPUT_RESERVE_FLOOR = 1024


def output_reserve_tokens(window: int, reserve_ratio: float | None = None
                          ) -> int:
    """Резерв вывода: ``max(1024, int(window × ratio))``; ratio — hot-ключ
    `limits.chat_budget_reserve_ratio` (default 0.10) либо явное значение."""
    if reserve_ratio is None:
        try:
            reserve_ratio = hot.get("limits.chat_budget_reserve_ratio",
                                    settings.CHAT_BUDGET_RESERVE_RATIO)
        except Exception:      # pragma: no cover - защитная ветка
            reserve_ratio = settings.CHAT_BUDGET_RESERVE_RATIO
    try:
        ratio = max(0.0, float(reserve_ratio))
    except (TypeError, ValueError):
        ratio = 0.10
    try:
        window = max(0, int(window))
    except (TypeError, ValueError):
        window = 0
    return max(OUTPUT_RESERVE_FLOOR, int(window * ratio))


def compute_available_budget(window: int, external_tokens: int,
                             reserve_ratio: float | None = None
                             ) -> tuple[int, int]:
    """D2: ``(available, output_reserve)``; ``available = safe_budget(window −
    external − reserve)`` — ЕДИНСТВЕННОЕ применение TOKEN_SAFETY_MULTIPLIER на
    весь расчёт (= tokenizer uncertainty reserve §4). Кламп снизу 1."""
    window = max(0, int(window or 0))
    external = max(0, int(external_tokens or 0))
    reserve = output_reserve_tokens(window, reserve_ratio)
    base = max(1, window - external - reserve)
    return max(1, safe_budget(base)), reserve


def apply_budget_policy(available: int, raw_budget,
                        dynamic_default: int | None = None
                        ) -> tuple[int, str]:
    """D2 policy-слой: ``-1`` → Unlimited (available); ``0``/``None`` →
    Dynamic (min(available, default)); ``>0`` → explicit cap. Возвращает
    ``(budget, policy_mode ∈ {unlimited, dynamic, cap})``."""
    available = max(1, int(available or 1))
    if dynamic_default is None:
        dynamic_default = int(getattr(settings, "CHAT_CONTEXT_BUDGET_TOKENS",
                                      16000) or 16000)
    if raw_budget is None:
        return min(available, max(1, int(dynamic_default))), "dynamic"
    try:
        value = int(raw_budget)
    except (TypeError, ValueError):
        return min(available, max(1, int(dynamic_default))), "dynamic"
    if value < 0:
        return available, "unlimited"
    if value == 0:
        return min(available, max(1, int(dynamic_default))), "dynamic"
    return min(available, value), "cap"


# ── ASAP 4.2 Step 2c-1 (T-4809, spec §4/R8-F-004): capability-aware reserve ──

RESERVE_SAFETY_MARGIN_FLOOR = 256


def capability_aware_output_reserve(*, effective_context: int,
                                    max_output_tokens: int | None = None,
                                    target_output: int = 4000,
                                    safety_margin_ratio: float | None = None,
                                    reserve_ratio: float | None = None) -> int:
    """Capability-aware output reserve (spec §4/R8-F-004).

    Учитывает `effective_context`, `max_output` (live metadata), `target_output`
    (ожидаемый размер ответа stage'а) и `safety_margin`:
      * известен `max_output` → `min(max_output, max(1024, target + margin))`;
      * `max_output` неизвестен → существующий `output_reserve_tokens`
        (ratio floor 1024) — «>=4000» не вечный механизм.
    Kill-switch OFF → строго `output_reserve_tokens` (байт-в-байт)."""
    if not capability_reserve_enabled():
        return output_reserve_tokens(effective_context, reserve_ratio)
    try:
        target = max(0, int(target_output or 0))
    except (TypeError, ValueError):
        target = 0
    try:
        cap_out = int(max_output_tokens) if max_output_tokens is not None \
            else None
    except (TypeError, ValueError):
        cap_out = None
    if not cap_out or cap_out <= 0:
        return output_reserve_tokens(effective_context, reserve_ratio)
    if safety_margin_ratio is None:
        try:
            safety_margin_ratio = float(getattr(
                settings, "SUMMARY_OUTPUT_RESERVE_SAFETY_RATIO", 0.02))
        except (TypeError, ValueError):
            safety_margin_ratio = 0.02
    try:
        ratio = max(0.0, float(safety_margin_ratio))
    except (TypeError, ValueError):
        ratio = 0.02
    try:
        window = max(0, int(effective_context or 0))
    except (TypeError, ValueError):
        window = 0
    margin = max(RESERVE_SAFETY_MARGIN_FLOOR, int(window * ratio))
    return max(OUTPUT_RESERVE_FLOOR, min(cap_out, target + margin))


def reserve_for_capacity(result, *,
                         target_output: int = 4000,
                         safety_margin_ratio: float | None = None,
                         reserve_ratio: float | None = None) -> int:
    """Reserve по `CapacityResult` (live `max_output_tokens` если есть).

    Устойчив к тест-дублям без `max_output_tokens` (getattr → None)."""
    return capability_aware_output_reserve(
        effective_context=getattr(result, "effective_context_window", 0),
        max_output_tokens=getattr(result, "max_output_tokens", None),
        target_output=target_output,
        safety_margin_ratio=safety_margin_ratio,
        reserve_ratio=reserve_ratio)


# ═══════════════════════════════════════════════════════════════════════════
# ── ASAP-3.1 (ADR-1028-3 D1): Model Capacity Resolver ──────────────────────

SOURCE_DEVELOPER_OVERRIDE = "developer_override"
SOURCE_RUNTIME = "runtime"
SOURCE_PROVIDER_CATALOG = "provider_catalog"
SOURCE_VERIFIED_REGISTRY = "verified_registry"
SOURCE_REGISTRY = "registry"
SOURCE_FALLBACK = "fallback"

# ── ASAP 4.1 (эпик asap-4-1-durable-whole-window-summary, T-4604/T-4605;
# spec §1 A.2 + ADR-1028-8 D2/AM-2 AMEND ADR-1028-3): решения режима входа
# Summary L1 по capacity. Два взаимоисключающих режима — единственное
# легитимное chunking-решение (`run_l1_capacity_first`).
MODE_WHOLE_WINDOW = "WHOLE_WINDOW"
MODE_CAPACITY_OVERFLOW = "CAPACITY_OVERFLOW"

PROVIDER_OPENROUTER = "openrouter"
PROVIDER_NANOGPT = "nanogpt"
PROVIDER_DEEPSEEK = "deepseek"
PROVIDER_OLLAMA = "ollama"
PROVIDER_LLAMA_CPP = "llamacpp"
PROVIDER_VLLM = "vllm"
PROVIDER_GENERIC = "generic"

# Локальные runtime-адаптеры — жёсткий TTL-потолок (Q9), независимо от env.
LOCAL_ADAPTER_TTL_SECONDS = 300
_ADAPTER_TIMEOUT_SECONDS = 2.0
# Fallback-результаты кэшируются коротко (не долбить недоступный endpoint).
_FALLBACK_TTL_SECONDS = 300

_PRIVATE_V4_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1$|localhost)")


def capacity_resolver_enabled() -> bool:
    """Kill-switch `MODEL_CAPACITY_RESOLVER_ENABLED` (env-only, default ON;
    резолв per-call; никогда не бросает). OFF → legacy-путь байт-в-байт."""
    try:
        return bool(getattr(settings, "MODEL_CAPACITY_RESOLVER_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def live_precedence_enabled() -> bool:
    """Kill-switch `SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED` (ASAP 4.2
    Step 2c-1, spec §4/AMEND ADR-1028-8 D2; env-only, default ON).

    ON  → override на УРОВНЕ 1; live metadata сильнее fresh cache/registry;
    OFF → прежний контур 2.58.47 (override на уровне 4) байт-в-байт."""
    try:
        return bool(getattr(
            settings, "SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def capability_reserve_enabled() -> bool:
    """Kill-switch `SUMMARY_OUTPUT_RESERVE_CAPABILITY_ENABLED` (ASAP 4.2
    Step 2c-1, spec §4/R8-F-004; env-only, default ON). OFF → прежний
    `output_reserve_tokens` (ratio floor 1024) байт-в-байт."""
    try:
        return bool(getattr(
            settings, "SUMMARY_OUTPUT_RESERVE_CAPABILITY_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


@dataclass(frozen=True)
class CapacityResult:
    """Структура §3: структурированный результат резолва capacity."""

    provider: str
    model: str
    declared_context_window: int | None
    runtime_context_window: int | None
    effective_context_window: int
    max_output_tokens: int | None
    source: str          # developer_override|runtime|provider_catalog|registry|fallback
    confidence: str      # verified|estimated|fallback
    resolved_at: float
    fallback_used: bool


# ── Метрики §50 (process-local + grep-able `direct_metric name=…`) ─────────
_CAPACITY_METRICS: dict[str, int] = {
    "capacity_fallback_total": 0,
    "capacity_manual_override_total": 0,
    "capacity_resolved_total": 0,
}


def capacity_metrics_snapshot() -> dict[str, int]:
    """Снимок счётчиков §50 (process-local; R17 — только числа)."""
    return dict(_CAPACITY_METRICS)


def _base_url_host(base_url: str) -> str:
    """R17-safe host из base_url (без пути/ключа/query); '' при ошибке."""
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(str(base_url or ""))
        return (parts.hostname or "").lower()
    except Exception:      # pragma: no cover - защитная ветка
        return ""


def _base_url_port(base_url: str) -> int | None:
    try:
        from urllib.parse import urlsplit
        return urlsplit(str(base_url or "")).port
    except Exception:      # pragma: no cover - защитная ветка
        return None


def detect_provider_class(base_url: str) -> str:
    """Класс провайдера по base_url (Q8; без сети, детерминированно).

    ASAP-3.2 (T-4202, ADR-1028-5 D6): NanoGPT и Direct DeepSeek — ОТДЕЛЬНЫЕ
    identity (не generic host): nano-gpt.com → live catalog adapter;
    api.deepseek.com → verified-registry identity (без machine-readable
    catalog — источник честно `verified_registry`, НЕ `provider_catalog`)."""
    host = _base_url_host(base_url)
    if not host:
        return PROVIDER_GENERIC
    if "openrouter" in host:
        return PROVIDER_OPENROUTER
    if "nano-gpt" in host:
        return PROVIDER_NANOGPT
    if host == "api.deepseek.com" or host.endswith(".deepseek.com"):
        return PROVIDER_DEEPSEEK
    port = _base_url_port(base_url)
    if port == 11434 or host == "ollama" or host.startswith("ollama."):
        return PROVIDER_OLLAMA
    if _PRIVATE_V4_RE.match(host) or host.endswith(".local"):
        return PROVIDER_LLAMA_CPP      # локальный runtime (пробуем /props)
    return PROVIDER_GENERIC


def _developer_override_window() -> int | None:
    """Override-слой §39: `models.chat_context_window_override` (hot-first;
    env-слой — прежний `CHAT_MODEL_CONTEXT_WINDOW`). 0/None = Auto;
    >0 = Developer override; `-1` НИКОГДА не capacity (только policy)."""
    try:
        value = hot.get("models.chat_context_window_override",
                        getattr(settings, "CHAT_MODEL_CONTEXT_WINDOW", None))
    except Exception:      # pragma: no cover - защитная ветка
        value = getattr(settings, "CHAT_MODEL_CONTEXT_WINDOW", None)
    if value is None:
        return None
    try:
        window = int(value)
    except (TypeError, ValueError):
        return None
    return window if window > 0 else None


def _ttl_for(provider_class: str) -> int:
    """Q9: remote catalogs — `MODEL_CAPACITY_CACHE_TTL_SECONDS` (default
    86400); локальные runtime-адаптеры — потолок 300 с."""
    try:
        ttl = int(getattr(settings, "MODEL_CAPACITY_CACHE_TTL_SECONDS",
                          86400))
    except Exception:      # pragma: no cover - защитная ветка
        ttl = 86400
    ttl = max(1, ttl)
    if provider_class in (PROVIDER_LLAMA_CPP, PROVIDER_OLLAMA,
                          PROVIDER_VLLM):
        return min(ttl, LOCAL_ADAPTER_TTL_SECONDS)
    return ttl


# ── Адаптеры (fail-open, таймаут 2 с, без внешней сети в тестах) ────────────

async def _http_get_json(url: str, *, headers: dict | None = None):
    """GET → JSON-словарь либо None (любая ошибка/таймаут = «недоступен»)."""
    try:
        import httpx
        async with httpx.AsyncClient(
                timeout=_ADAPTER_TIMEOUT_SECONDS, follow_redirects=True) as \
                client:
            response = await client.get(url, headers=headers or None)
            if response.status_code != 200:
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _strip_v1(base_url: str) -> str:
    """`http://h:port/v1` → `http://h:port` (для неперекрёстных endpoint'ов)."""
    raw = str(base_url or "").rstrip("/")
    return raw[:-3] if raw.endswith("/v1") else raw


async def _adapter_openrouter(base_url: str, model: str) -> int | None:
    """Каталог OpenRouter: `/api/v1/models` → `context_length` (по id)."""
    data = await _http_get_json("https://openrouter.ai/api/v1/models")
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    wanted = str(model or "").strip().lower()
    if not wanted:
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip().lower() == wanted:
            try:
                window = int(item.get("context_length"))
            except (TypeError, ValueError):
                return None
            return window if window > 0 else None
    return None


# Схема live/public каталога NanoGPT верифицирована по официальным docs
# (docs.nano-gpt.com/api-reference/endpoint/models, 01.10.2026):
# `GET /api/v1/models?detailed=true` → `{data: [{id, context_length,
# max_output_tokens, capabilities, ...}]}`; `context_length` — max input
# tokens (null if not available). Таймаут общий 2 с (`_http_get_json`).
def _nanogpt_catalog_urls(base_url: str) -> list[str]:
    """Кандидаты URL каталога: `{base}/models` (base уже `/api/v1`) + при
    отсутствии `/api` в base — канонический `{scheme}://{host}/api/v1/models`.
    Route НЕ выдумывается дальше этих двух документированных форм."""
    raw = str(base_url or "").rstrip("/")
    urls = [f"{raw}/models?detailed=true"]
    host = _base_url_host(raw)
    if host and "/api" not in raw:
        scheme = "https" if "://" in raw else "https"
        urls.append(f"{scheme}://{host}/api/v1/models?detailed=true")
    return urls


async def _adapter_nanogpt_catalog(base_url: str, model: str
                                   ) -> tuple[int, int | None] | None:
    """Каталог NanoGPT (§53): `(context_length, max_output_tokens | None)`
    по id; каталог недоступен/модели нет → None (→ registry/fallback с
    честным source в Analytics). НЕ бросает."""
    wanted = str(model or "").strip().lower()
    if not wanted:
        return None
    for url in _nanogpt_catalog_urls(base_url):
        data = await _http_get_json(url)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip().lower() != wanted:
                continue
            try:
                window = int(item.get("context_length"))
            except (TypeError, ValueError):
                return None          # модель есть, окна нет — честный miss
            if window <= 0:
                return None
            max_output = None
            try:
                candidate = int(item.get("max_output_tokens"))
                if candidate > 0:
                    max_output = candidate
            except (TypeError, ValueError):
                max_output = None
            return window, max_output
    return None


async def _adapter_llama_cpp(base_url: str, model: str) -> int | None:
    """llama.cpp: `/props` → `n_ctx` (runtime, не training maximum)."""
    root = _strip_v1(base_url)
    data = await _http_get_json(f"{root}/props")
    if not isinstance(data, dict):
        return None
    for candidate in (
            (data.get("default_generation_settings") or {}).get("n_ctx")
            if isinstance(data.get("default_generation_settings"), dict)
            else None,
            data.get("n_ctx"),
            (data.get("model_metadata") or {}).get("llama.context_length")
            if isinstance(data.get("model_metadata"), dict) else None,
    ):
        try:
            window = int(candidate)
        except (TypeError, ValueError):
            continue
        if window > 0:
            return window
    return None


async def _adapter_ollama(base_url: str, model: str) -> int | None:
    """Ollama: `/api/ps` → running model `context_length`."""
    root = _strip_v1(base_url)
    data = await _http_get_json(f"{root}/api/ps")
    items = data.get("models") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    wanted = str(model or "").strip().lower()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if wanted and name and not name.startswith(wanted.split(":")[0]):
            continue
        try:
            window = int(item.get("context_length"))
        except (TypeError, ValueError):
            continue
        if window > 0:
            return window
    return None


async def _adapter_vllm(base_url: str, model: str) -> int | None:
    """vLLM config introspection: `/model_info` → `max_model_len`."""
    for root in (str(base_url or "").rstrip("/"), _strip_v1(base_url)):
        if not root:
            continue
        data = await _http_get_json(f"{root}/model_info")
        if isinstance(data, dict):
            try:
                window = int(data.get("max_model_len"))
            except (TypeError, ValueError):
                continue
            if window > 0:
                return window
    return None


_LOCAL_ADAPTERS = {
    PROVIDER_LLAMA_CPP: _adapter_llama_cpp,
    PROVIDER_OLLAMA: _adapter_ollama,
}


# ── Кэш (ключ provider/base_url/model/override; TTL Q9) ────────────────────
# Инвалидация §38: model/base_url/override входят в ключ → их смена = промах;
# `invalidate_capacity_cache()` — config reload / explicit refresh.
_CACHE: dict[tuple, tuple[CapacityResult, float]] = {}


def invalidate_capacity_cache() -> int:
    """Полная инвалидация кэша capacity (config reload / explicit refresh,
    кнопка «Обновить» в Advanced diagnostics). Возвращает число записей."""
    count = len(_CACHE)
    _CACHE.clear()
    return count


def _capability_fingerprint(base_url: str) -> str:
    """Capability fingerprint ключа кеша (AMEND ADR-1028-3, spec A.2:
    «ключ = provider + base_url + model + capability fingerprint»).

    Fingerprint — стабильный дескриптор capability-зонда: provider class +
    endpoint (без scheme/query; R17 — не логируется). Смена endpoint'а
    каталога/base_url → промах кеша = честная переоценка (не устаревшее
    значение чужого endpoint'а)."""
    endpoint = str(base_url or "").strip()
    provider_class = detect_provider_class(endpoint)
    raw = f"{provider_class}|{endpoint}"
    try:
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    except Exception:      # pragma: no cover - hashlib не падает на str
        return provider_class[:12] or "generic"


def _cache_key(base_url: str, model: str, route: str | None = None) -> tuple:
    provider_class = detect_provider_class(base_url)
    return (provider_class, _base_url_host(base_url),
            str(model or "").strip().lower(), _developer_override_window(),
            _capability_fingerprint(base_url),
            str(route or "").strip().lower())


def invalidate_runtime_capacity(base_url: str, model: str,
                                *, reason: str = "runtime_context_error"
                                ) -> int:
    """Точечная инвалидация кеша по тройке provider/host/model
    (runtime 400/context-length error → переоценка в рамках run;
    spec §7/T-4605; fingerprint/override игнорируются — тройка суверенна).

    R17: provider host/model/reason — без ключей/URL-пути."""
    provider_class = detect_provider_class(base_url)
    host = _base_url_host(base_url)
    name = str(model or "").strip().lower()
    victim_keys = [key for key in _CACHE
                   if key[0] == provider_class and key[1] == host
                   and key[2] == name]
    for key in victim_keys:
        _CACHE.pop(key, None)
    if victim_keys:
        logger.warning(
            "MODEL_CAPACITY_CACHE_INVALIDATED | provider=%s | model=%s | "
            "entries=%d | reason=%s", provider_class, name,
            len(victim_keys), reason)
    return len(victim_keys)


def _warn_capacity_fallback(result: CapacityResult, base_url: str,
                            reason: str) -> None:
    """§8: fallback — аварийный путь, НЕ «нормальный»: WARNING
    `MODEL_CAPACITY_FALLBACK` (provider, model, base_url class,
    fallback_window, reason; R17 — без ключей/URL-пути) + счётчик."""
    _CAPACITY_METRICS["capacity_fallback_total"] += 1
    logger.warning(
        "MODEL_CAPACITY_FALLBACK | provider=%s | model=%s | base_url_class=%s "
        "| fallback_window=%d | reason=%s",
        result.provider, result.model,
        detect_provider_class(base_url), result.effective_context_window,
        reason)


async def resolve_capacity(base_url: str, model: str, *,
                           slot: str | None = None,
                           route: str | None = None) -> CapacityResult:
    """Структурированный резолв §3/§4 (async: runtime-адаптеры — HTTP).

    Precedence (ASAP 4.2 Step 2c-1, spec §4/AMEND ADR-1028-8 D2, при
    `SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED=ON`): developer_override →
    verified live provider/model metadata → verified route metadata →
    fresh provider cache → internal registry → conservative unknown.
    OFF → прежний контур 2.58.47 (runtime → catalog → registry → override →
    fallback) байт-в-байт. `effective = min(runtime, provider/model)` (§5).
    Никогда не бросает; `route` входит в cache key (`route/capability
    fingerprint`): смена route инвалидирует."""
    name = str(model or "").strip()
    provider_class = detect_provider_class(base_url)
    override = _developer_override_window()
    key = _cache_key(base_url, name, route)
    now = time.time()
    cached = _CACHE.get(key)
    if cached is not None:
        result, expires_at = cached
        if now < expires_at:
            # ON: stale family-registry cache не должен занижать live
            # capability → пере-резолв; fallback кэшируется коротко (300 с)
            # и остаётся authoritative (не долбить недоступный endpoint).
            skip_stale_registry = (
                live_precedence_enabled()
                and result.source == SOURCE_REGISTRY
                and provider_class in (PROVIDER_NANOGPT, PROVIDER_OPENROUTER,
                                       PROVIDER_LLAMA_CPP, PROVIDER_OLLAMA))
            if not skip_stale_registry:
                return result
            _CACHE.pop(key, None)      # stale registry — re-resolve live
        else:
            _CACHE.pop(key, None)

    result = await _resolve_uncached(provider_class, base_url, name,
                                     override, route=route)
    ttl = _FALLBACK_TTL_SECONDS if result.fallback_used else \
        _ttl_for(provider_class)
    _CACHE[key] = (result, now + ttl)
    # Наблюдаемость §49: событие на актуальный (cache-miss) резолв.
    try:
        from services.agentic_events import MODEL_CAPACITY_RESOLVED, \
            emit_agentic_event
        if result.source == SOURCE_DEVELOPER_OVERRIDE:
            _CAPACITY_METRICS["capacity_manual_override_total"] += 1
        _CAPACITY_METRICS["capacity_resolved_total"] += 1
        emit_agentic_event(
            MODEL_CAPACITY_RESOLVED, slot=slot or "unknown", provider=result.provider,
            model=name[:64] or "-", effective_window=result.effective_context_window,
            declared_window=result.declared_context_window,
            runtime_window=result.runtime_context_window,
            source=result.source, fallback_used=result.fallback_used)
    except Exception:      # fail-open: наблюдаемость не рвёт резолв
        pass
    return result


async def _resolve_uncached(provider_class: str, base_url: str, name: str,
                            override: int | None,
                            route: str | None = None) -> CapacityResult:
    """Одна итерация precedence (без кэша; никогда не бросает).

    ASAP 4.2 Step 2c-1 (spec §4/AMEND ADR-1028-8 D2): при
    `SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED=ON` цепочка — override
    (уровень 1) → live provider/model metadata → live route metadata →
    fresh provider cache (обрабатывается `resolve_capacity`) → internal
    registry → conservative unknown. OFF → прежний контур 2.58.47
    (runtime → catalog → registry → override → fallback) байт-в-байт."""
    now = time.time()
    live = live_precedence_enabled()
    # ── 1) developer override — уровень 1 (live precedence ON) ─────────────
    if live and override is not None:
        _CAPACITY_METRICS["capacity_manual_override_total"] += 1
        return CapacityResult(
            provider=provider_class, model=name,
            declared_context_window=None, runtime_context_window=None,
            effective_context_window=override, max_output_tokens=None,
            source=SOURCE_DEVELOPER_OVERRIDE, confidence="verified",
            resolved_at=now, fallback_used=False)
    runtime_window: int | None = None
    runtime_provider = provider_class
    # 2) runtime metadata — локальные рантаймы (llama.cpp/Ollama по классу;
    #    vLLM config introspection пробуется на локальных base_url).
    if provider_class == PROVIDER_LLAMA_CPP:
        runtime_window = await _adapter_llama_cpp(base_url, name)
        if runtime_window is None:
            # локальный vLLM/другой рантайм: config introspection (Q8.4).
            runtime_window = await _adapter_vllm(base_url, name)
            if runtime_window is not None:
                runtime_provider = PROVIDER_VLLM
    elif provider_class == PROVIDER_OLLAMA:
        runtime_window = await _adapter_ollama(base_url, name)
    elif provider_class == PROVIDER_OPENROUTER:
        # 3) provider catalog (класс OpenRouter) — context_length каталога.
        catalog_window = await _adapter_openrouter(base_url, name)
        if catalog_window is not None:
            result = CapacityResult(
                provider=provider_class, model=name,
                declared_context_window=catalog_window,
                runtime_context_window=None,
                effective_context_window=catalog_window,
                max_output_tokens=None, source=SOURCE_PROVIDER_CATALOG,
                confidence="verified", resolved_at=now, fallback_used=False)
            return result
    elif provider_class == PROVIDER_NANOGPT:
        # 3) provider catalog (§53, T-4202): live/public каталог NanoGPT —
        # context window + max output; недоступен → registry/fallback с
        # честным source (ниже). НЕ угадываем из имени (§56).
        catalog = await _adapter_nanogpt_catalog(base_url, name)
        if catalog is not None:
            catalog_window, max_output = catalog
            declared = _match_model_window(name)
            # T-4808: live precedence ON → live catalog суверенен, stale
            # registry НЕ занижает live capability (declared остаётся для
            # прозрачности); OFF → прежний min(live, registry).
            effective = catalog_window if (live or declared is None) \
                else min(catalog_window, declared)
            result = CapacityResult(
                provider=provider_class, model=name,
                declared_context_window=declared,
                runtime_context_window=None,
                effective_context_window=effective,
                max_output_tokens=max_output,
                source=SOURCE_PROVIDER_CATALOG,
                confidence="verified", resolved_at=now, fallback_used=False)
            return result
    # ── 3b) verified route metadata (live precedence ON) ───────────────────
    # Маршрут-специфичная metadata (например, endpoint-лимиты) — только из
    # верифицированного адаптера; без подтверждения слой честно пропускается.
    if live:
        route_result = await _resolve_route_metadata(
            provider_class, base_url, name, route)
        if route_result is not None:
            return route_result

    declared_window = _match_model_window(name)
    if runtime_window is not None:
        # §5: effective = min(runtime, known provider/model limit) — OFF.
        # T-4808: live precedence ON → runtime (live) суверенен, stale
        # registry не занижает.
        effective = runtime_window if (live or declared_window is None) \
            else min(runtime_window, declared_window)
        return CapacityResult(
            provider=runtime_provider, model=name,
            declared_context_window=declared_window,
            runtime_context_window=runtime_window,
            effective_context_window=effective, max_output_tokens=None,
            source=SOURCE_RUNTIME, confidence="verified", resolved_at=now,
            fallback_used=False)
    if declared_window is not None:
        if provider_class == PROVIDER_DEEPSEEK:
            # §54 (T-4202): Direct DeepSeek — отдельный identity; machine-
            # readable catalog нет → verified official registry entry,
            # source=`verified_registry` (НЕ `provider_catalog`, НЕ «generic
            # registry guess»).
            return CapacityResult(
                provider=provider_class, model=name,
                declared_context_window=declared_window,
                runtime_context_window=None,
                effective_context_window=declared_window,
                max_output_tokens=None, source=SOURCE_VERIFIED_REGISTRY,
                confidence="verified", resolved_at=now, fallback_used=False)
        return CapacityResult(
            provider=provider_class, model=name,
            declared_context_window=declared_window,
            runtime_context_window=None,
            effective_context_window=declared_window,
            max_output_tokens=None, source=SOURCE_REGISTRY,
            confidence="verified", resolved_at=now, fallback_used=False)

    # ── 4) developer override (уровень 4; legacy OFF-контур 2.58.47) ───────
    # применяется ТОЛЬКО когда live precedence OFF (AMEND ADR-1028-8 D2),
    # защищая цепочку перед консервативным fallback (уровень 5).
    if override is not None:
        return CapacityResult(
            provider=provider_class, model=name,
            declared_context_window=None, runtime_context_window=None,
            effective_context_window=override, max_output_tokens=None,
            source=SOURCE_DEVELOPER_OVERRIDE, confidence="verified",
            resolved_at=now, fallback_used=False)

    # 5) fallback — только аварийно (§8): 16384 + WARNING + badge.
    result = CapacityResult(
        provider=provider_class, model=name,
        declared_context_window=None, runtime_context_window=None,
        effective_context_window=_unknown_window(),
        max_output_tokens=None, source=SOURCE_FALLBACK,
        confidence="fallback", resolved_at=now, fallback_used=True)
    _warn_capacity_fallback(result, base_url,
                            "unknown_model_no_adapter_data")
    return result


async def _resolve_route_metadata(provider_class: str, base_url: str,
                                  model: str, route: str | None
                                  ) -> CapacityResult | None:
    """Верифицированный route-metadata слой (spec §4, уровень 3).

    Пока ни один верифицированный адаптер не экспонирует route-специфичное
    окно отдельно от model-каталога → честно None (слой присутствует в
    цепочке, но НЕ выдумывает значение). Расширяется при появлении
    подтверждённого endpoint-metadata без hardcode."""
    _ = provider_class, base_url, model, route
    return None


async def resolve_stage_window(base_url: str, model: str, *,
                               slot: str | None = None
                               ) -> tuple[int, str]:
    """Drop-in для потребителей: ``(effective_window, source)``.

    Kill-switch OFF → legacy-путь `resolve_model_context_window` байт-в-байт
    (карта + env + fallback 16384, источник model_map/env_override/
    unknown_fallback)."""
    if not capacity_resolver_enabled():
        return resolve_model_context_window(model)
    result = await resolve_capacity(base_url, model, slot=slot)
    return result.effective_context_window, result.source


def fallback_window_for_model(model: str) -> tuple[int, str]:
    """Окно fallback-модели БЕЗ сети (§14: resolve capacity fallback отдельно
    перед recompose). Runtime-адаптеры не вызываются — registry/env/fallback;
    для точного runtime-окна fallback'а используется `resolve_stage_window`."""
    if not capacity_resolver_enabled():
        return resolve_model_context_window(model)
    override = _developer_override_window()
    if override is not None:
        return override, SOURCE_DEVELOPER_OVERRIDE
    mapped = _match_model_window(str(model or ""))
    if mapped is not None:
        return mapped, SOURCE_REGISTRY
    return _unknown_window(), SOURCE_FALLBACK


# ═══════════════════════════════════════════════════════════════════════════
# ── ASAP 4.1 (эпик asap-4-1-durable-whole-window-summary) — capacity engine
# Summary: решение WHOLE_WINDOW | CAPACITY_OVERFLOW по ФАКТИЧЕСКОМУ
# serialized payload (T-4604, spec §1 A.2; ADR-1028-8 D2.2/D2.4) + re-plan
# при смене провайдера/окна (T-4605, §7/§27–§28; ADR-1028-8 D2.4).
#
# Правило структуры §6 ТЗ: учёт по реальному payload — system prompt +
# source JSON + semantic instructions + response schema + metadata +
# output reserve + provider framing overhead. Calling side (run_l1_
# capacity_first) считает serialized окно; здесь только решение:
# Никогда не бросает; Inspector-поля (R6-G-002) — прямо в результате:
# provider/model/effective window/serialized input/output reserve/mode/причина.

_REPLAN_SLOT = "summary.fallback_replan"


@dataclass(frozen=True)
class SummaryCapacityPlan:
    """Решение режима входа + Inspector-поля (R6-G-002; spec A.2)."""

    mode: str                       # WHOLE_WINDOW | CAPACITY_OVERFLOW
    reason: str                     # R17-safe причина (человеческая карта в Inspector)
    provider: str
    model: str
    effective_context_window: int
    required_input_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int       # effective − required − reserve (только знак важен)
    window_source: str
    confidence: str = "estimated"
    fallback_used: bool = False

    def as_event_counts(self) -> dict:
        """R17-safe counts для SUMMARY_CAPACITY_RESOLVED / MODE_SELECTED."""
        return {
            "mode": self.mode,
            "reason": self.reason,
            "effective_window": self.effective_context_window,
            "required_input_tokens": self.required_input_tokens,
            "reserved_output_tokens": self.reserved_output_tokens,
            "safety_margin_tokens": self.safety_margin_tokens,
            "window_source": self.window_source,
            "fallback_used": bool(self.fallback_used),
        }


def decide_summary_mode(*, provider: str, model: str,
                        effective_context_window: int,
                        required_input_tokens: int,
                        reserved_output_tokens: int,
                        window_source: str,
                        confidence: str = "estimated",
                        fallback_used: bool = False
                        ) -> SummaryCapacityPlan:
    """Чистое решение §6 ТЗ: `required + reserve ≤ effective → WHOLE_WINDOW`,
    иначе `CAPACITY_OVERFLOW` (единственный легитимный chunking-режим).
    Оценка вводится вызывающим контуром по ПОЛНОМУ serialized payload
    (не «только message.text» — fixture-контрпример запрещает)."""
    try:
        effective = max(0, int(effective_context_window or 0))
    except (TypeError, ValueError):
        effective = 0
    try:
        required = max(0, int(required_input_tokens or 0))
    except (TypeError, ValueError):
        required = 0
    try:
        reserved = max(0, int(reserved_output_tokens or 0))
    except (TypeError, ValueError):
        reserved = 0
    margin = effective - required - reserved
    if margin >= 0:
        mode, reason = MODE_WHOLE_WINDOW, "fits_effective_context"
    else:
        mode, reason = MODE_CAPACITY_OVERFLOW, \
            "serialized_payload_exceeds_effective_context"
    return SummaryCapacityPlan(
        mode=mode, reason=reason, provider=str(provider or ""),
        model=str(model or ""), effective_context_window=effective,
        required_input_tokens=required,
        reserved_output_tokens=reserved, safety_margin_tokens=int(margin),
        window_source=str(window_source or ""), confidence=confidence,
        fallback_used=bool(fallback_used))


async def replan_summary_capacity(*, base_url: str, model: str,
                                  required_input_tokens: int,
                                  reserved_output_tokens: int,
                                  current_mode: str,
                                  segment_artifacts_created: bool = False,
                                  ) -> SummaryCapacityPlan:
    """Re-plan при provider/model fallback (T-4605; spec §7/§27–§28).

    Resolve fallback capacity → compare required input (§44-C/D/E):
      * вмещает → тот же whole-window task (mode=WHOLE_WINDOW);
      * меньше → switch to CAPACITY_OVERFLOW (lossless, без потери
        coverage);
      * больше → допустим переход на whole-window, ЕСЛИ run ещё не создал
        сегментные артефакты (иначе — не ломаем созданный run, §44-E:
        reason=`segment_artifacts_exist`).
    Семантика задачи инвариантна — меняются только mode/strategy.
    Никогда не бросает (fail-open к conservative fallback)."""
    try:
        result = await resolve_capacity(base_url, model, slot=_REPLAN_SLOT)
        window_source = result.source
        effective = result.effective_context_window
        confidence = result.confidence
        fallback_used = result.fallback_used
    except Exception:      # pragma: no cover - защитная ветка
        window_source = SOURCE_FALLBACK
        effective = _unknown_window()
        confidence = "fallback"
        fallback_used = True
    plan = decide_summary_mode(
        provider=detect_provider_class(base_url), model=model,
        effective_context_window=effective,
        required_input_tokens=required_input_tokens,
        reserved_output_tokens=reserved_output_tokens,
        window_source=window_source, confidence=confidence,
        fallback_used=fallback_used)
    # Целевой апгрейд (§28: меньше → overflow; больше → whole-window допустим
    # ТОЛЬКО до создания сегментных артефактов).
    if plan.mode == MODE_WHOLE_WINDOW and current_mode \
            == MODE_CAPACITY_OVERFLOW and segment_artifacts_created:
        return SummaryCapacityPlan(
            mode=MODE_CAPACITY_OVERFLOW,
            reason="segment_artifacts_exist",
            provider=plan.provider, model=plan.model,
            effective_context_window=plan.effective_context_window,
            required_input_tokens=plan.required_input_tokens,
            reserved_output_tokens=plan.reserved_output_tokens,
            safety_margin_tokens=plan.safety_margin_tokens,
            window_source=plan.window_source, confidence=plan.confidence,
            fallback_used=plan.fallback_used)
    if plan.mode == MODE_WHOLE_WINDOW and current_mode \
            == MODE_CAPACITY_OVERFLOW and not segment_artifacts_created:
        return SummaryCapacityPlan(
            mode=MODE_WHOLE_WINDOW, reason="fits_after_fallback",
            provider=plan.provider, model=plan.model,
            effective_context_window=plan.effective_context_window,
            required_input_tokens=plan.required_input_tokens,
            reserved_output_tokens=plan.reserved_output_tokens,
            safety_margin_tokens=plan.safety_margin_tokens,
            window_source=plan.window_source, confidence=plan.confidence,
            fallback_used=plan.fallback_used)
    return plan


__all__ = [
    "MODEL_CONTEXT_WINDOWS", "WINDOW_SOURCE_MAP", "WINDOW_SOURCE_ENV",
    "WINDOW_SOURCE_FALLBACK", "OUTPUT_RESERVE_FLOOR",
    "resolve_model_context_window", "resolve_effective_window",
    "output_reserve_tokens", "compute_available_budget",
    "apply_budget_policy",
    "capability_aware_output_reserve", "reserve_for_capacity",
    "live_precedence_enabled", "capability_reserve_enabled",
    # ASAP-3.1 (ADR-1028-3): structured capacity resolver.
    "SOURCE_DEVELOPER_OVERRIDE", "SOURCE_RUNTIME", "SOURCE_PROVIDER_CATALOG",
    "SOURCE_VERIFIED_REGISTRY", "SOURCE_REGISTRY", "SOURCE_FALLBACK",
    "PROVIDER_OPENROUTER", "PROVIDER_NANOGPT", "PROVIDER_DEEPSEEK",
    "PROVIDER_OLLAMA", "PROVIDER_LLAMA_CPP",
    "PROVIDER_VLLM", "PROVIDER_GENERIC",
    "CapacityResult", "LOCAL_ADAPTER_TTL_SECONDS",
    "capacity_resolver_enabled", "detect_provider_class",
    "invalidate_capacity_cache", "capacity_metrics_snapshot",
    "resolve_capacity", "resolve_stage_window", "fallback_window_for_model",
    # ASAP 4.1 (эпик asap-4-1-durable-whole-window-summary): capacity engine
    # Summary (T-4604/T-4605).
    "MODE_WHOLE_WINDOW", "MODE_CAPACITY_OVERFLOW",
    "SummaryCapacityPlan", "decide_summary_mode", "replan_summary_capacity",
    "invalidate_runtime_capacity",
]
