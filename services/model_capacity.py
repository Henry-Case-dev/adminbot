"""ASAP-3 (round 1028, ADR-1028-2 D1/D2) — model-aware capacity Direct Chat.

Нейтральный consumer-side модуль: физическое context-window модели и формула
полного payload-бюджета. Summary-пайплайн этот модуль НЕ импортирует и не
меняется (§0/D11); `resolve_context_tokens`/`safe_budget` из token_counter
сохраняют семантику ADR-1019-8 для всех не-direct потребителей.

D1 — источник окна (в порядке приоритета):
  1. env `CHAT_MODEL_CONTEXT_WINDOW` (override, priority above map);
  2. точное совпадение ID модели с реестром (`MODEL_CONTEXT_WINDOWS` /
     `MODEL_EXACT_WINDOWS`, namespace/suffix/alias нормализуются);
  3. неизвестная модель → env `CHAT_UNKNOWN_MODEL_WINDOW` (default 1 000 000,
     SMART-EXECUTION-RELIABILITY-01 stage D1) + однократный WARN на модель —
     источник решения виден в `CONTEXT_CAPACITY` (`window_source`). Это
     ПЛАНИРОВОЧНАЯ оценка, НЕ подтверждённая ёмкость провайдера; 16384 как
     универсальный unknown-fallback удалён. Семейные префиксы
     (`glm-4`/`deepseek-v4`) НЕ угадывают ёмкость незнакомой модели.

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

  precedence (SMART-EXECUTION-RELIABILITY-01 stage D2/D3, owner 14.11.2026;
  детерминированный, §4):
    0. proven_limit — подтверждённый физический предел фактического
       endpoint/model (structured context-overflow от провайдера). Выше
       owner override: override НЕ отменяет доказанный предел (конфликт
       виден в полях `override_value`/`clamped_by_proven_limit`);
    1. developer_override — `models.chat_context_window_override` > 0
       (hot-first; env-слой — прежний `CHAT_MODEL_CONTEXT_WINDOW`);
       planning input, confidence=`override` (НЕ provider-verified);
    2. runtime — metadata фактического backend (адаптеры локальных рантаймов);
    3. provider_catalog — каталог провайдера (класс OpenRouter/NanoGPT);
    4. verified cache — свежее значение того же provider/base_url/model/route
       (реализуется `resolve_capacity` до вызова `_resolve_uncached`);
    5. registry — ТОЧНОЕ совпадение ID с проверенным реестром (namespace/
       suffix/alias нормализуются; семейный префикс ёмкость не определяет);
    6. estimated_unknown — планировочные 1 000 000 (не provider-verified).
  Legacy-контур (kill-switch `MODEL_CAPACITY_RESOLVER_ENABLED=OFF`)
  сохраняет прежнюю цепочку runtime → catalog → registry(family map) →
  override → unknown, но unknown-окно — 1M (D1), не 16384.

  `effective = min(runtime, provider/model)` (§5); локальный 16K при 128K
  используется полностью. Кэш по ключу provider/base_url/model/override c
  TTL (Q9): remote catalogs 24 ч (`MODEL_CAPACITY_CACHE_TTL_SECONDS`),
  локальные runtime-адаптеры — жёсткий потолок 300 с. Инвалидация §38: ключ
  включает model/base_url/override → их смена = новый ключ;
  `invalidate_capacity_cache()` — config reload / explicit refresh.

  Kill-switch `MODEL_CAPACITY_RESOLVER_ENABLED` (env-only, default ON):
  OFF → функции-legacy ниже работают прежним контуром (карта + env +
  unknown-window: 1M estimated, НЕ 16384; прецедент
  DIRECT_CONTEXT_COMPOSER_ENABLED).

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
_WINDOW_CACHE: dict[tuple, tuple[int, str]] = {}
_WARNED_UNKNOWN: set[str] = set()

WINDOW_SOURCE_MAP = "model_map"
WINDOW_SOURCE_ENV = "env_override"
WINDOW_SOURCE_FALLBACK = "unknown_fallback"

#: Планировочное окно неизвестной модели (SMART-EXECUTION-RELIABILITY-01 D1):
#: это ОЦЕНКА, а не подтверждённая провайдером ёмкость. 16384 как
#: универсальный unknown-fallback удалён — он молча занижал реальные
#: 128K/1M-модели (инцидент с NanoGPT `z-ai/glm-5.3-flash-uncensored`).
UNKNOWN_WINDOW_DEFAULT = 1_000_000

#: Точный реестр известных ID моделей. Ключ — ID модели (namespace и
#: routing-суффиксы нормализуются в `_model_candidates`), поэтому ёмкость
#: определяется только точным совпадением, а НЕ семейным префиксом
#: (`glm-4` не даёт ёмкость `glm-5.3-*`). Значения — намеренно заданные
#: реальные лимиты конкретных моделей, они не перезаписываются 1M.
MODEL_EXACT_WINDOWS: dict[str, int] = dict(MODEL_CONTEXT_WINDOWS)

#: Routing/вариантные суффиксы, которые провайдеры добавляют к ID модели
#: (`:free`, `:nitro`, `@provider`); они не меняют ёмкость модели.
_ROUTING_SUFFIXES = (":free", ":nitro", ":thinking", ":online", ":extended",
                     ":floor", ":beta")


def _model_candidates(model_name: str | None) -> list[str]:
    """Нормализованные кандидаты ID: полный, basename, без routing-суффикса.

    Namespace провайдера (`z-ai/`) не входит в идентичность модели — каталоги
    отдают как `z-ai/glm-5.3-flash-uncensored`, так и `glm-5.3-flash-uncensored`.
    Никаких префиксных/семейных совпадений здесь не появляется."""
    raw = str(model_name or "").strip().lower().strip("/")
    if not raw:
        return []
    out: list[str] = []

    def _add(value: str) -> None:
        value = str(value or "").strip().strip("/")
        if value and value not in out:
            out.append(value)

    _add(raw)
    base = raw.rsplit("/", 1)[-1]
    _add(base)
    for value in (base, raw):
        for suffix in _ROUTING_SUFFIXES:
            if value.endswith(suffix):
                _add(value[: -len(suffix)])
        if "@" in value:
            _add(value.split("@", 1)[0])
    return out


def normalize_model_id(model_name: str | None) -> str:
    """Канонический ID модели для ключей кэша/сопоставления (lower, basename,
    без routing-суффикса). Пустое имя → ''. Никогда не бросает."""
    candidates = _model_candidates(model_name)
    if not candidates:
        return ""
    base = candidates[1] if len(candidates) > 1 else candidates[0]
    for suffix in _ROUTING_SUFFIXES:
        if base.endswith(suffix):
            return base[: -len(suffix)]
    if "@" in base:
        return base.split("@", 1)[0]
    return base


def _same_model_id(left: str | None, right: str | None) -> bool:
    """Совпадение ID с нормализацией namespace/routing-suffix (N1 ревью D).

    Обе стороны сравниваются канонически (`normalize_model_id`): иначе полный
    ID в кэше и короткий ID в `record_proven_limit`/инвалидации не совпали бы,
    и устаревший catalog-кэш продолжал бы затенять доказанный предел. Пустые
    имена сравниваются как прежде (сырой lower) — молча ничего не расширяем.
    """
    norm_left = normalize_model_id(left)
    norm_right = normalize_model_id(right)
    if norm_left and norm_right:
        return norm_left == norm_right
    return str(left or "").strip().lower() == str(right or "").strip().lower()


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
    """Планировочное окно неизвестной модели (`CHAT_UNKNOWN_MODEL_WINDOW`).

    Заводское значение — :data:`UNKNOWN_WINDOW_DEFAULT` (1 000 000). Любое
    отсутствие/ноль/ошибка кастования → 1M, НИКОГДА не 16384 (D1: не
    оставлять ситуации «в настройках 1M, а helper вернул 16384»)."""
    try:
        window = int(getattr(settings, "CHAT_UNKNOWN_MODEL_WINDOW",
                             UNKNOWN_WINDOW_DEFAULT))
    except Exception:      # pragma: no cover - защитная ветка
        return UNKNOWN_WINDOW_DEFAULT
    return window if window > 0 else UNKNOWN_WINDOW_DEFAULT


def _match_model_window(model_name: str) -> int | None:
    """LEGACY-путь (§D1): префикс-матч по карте (lower-case, longest-prefix).

    Используется ТОЛЬКО legacy-контуром (kill-switch OFF) и явно помечается
    `WINDOW_SOURCE_MAP`; в контракте по умолчанию ёмкость так не выводится
    (см. `_registry_exact_window`)."""
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


def _registry_exact_window(model_name: str) -> int | None:
    """Точное совпадение ID модели с проверенным реестром (D2, уровень 5).

    Namespace/routing-suffix нормализуются (`_model_candidates`), сам ID
    сравнивается ПОЛНОСТЬЮ: модель `glm-5.3-flash-uncensored` не получает
    ёмкость `glm-4` только из-за общего префикса."""
    for candidate in _model_candidates(model_name):
        window = MODEL_EXACT_WINDOWS.get(candidate)
        if window is not None:
            return int(window)
    return None


def _legacy_model_window(model_name: str) -> tuple[int, str]:
    """Legacy-контур (kill-switch OFF): env override → семейная карта →
    планировочное окно. Именно сюда ушло прежнее «16384» — теперь 1M."""
    override = _env_override_window()
    if override is not None:
        return override, WINDOW_SOURCE_ENV
    mapped = _match_model_window(model_name)
    if mapped is not None:
        return mapped, WINDOW_SOURCE_MAP
    return _unknown_window(), WINDOW_SOURCE_FALLBACK


def resolve_model_context_window(model_name: str | None) -> tuple[int, str]:
    """Синхронное окно модели: ``(window, window_source)``.

    Контракт по умолчанию (SMART D2): env override → ТОЧНЫЙ реестр →
    планировочные 1M estimated. Семейные префиксы ёмкость не определяют.
    Kill-switch OFF → прежний legacy-контур (карта семей + 1M unknown).
    Кэш per (модель, режим); env в рантайме не меняется (прецедент
    `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`)."""
    name = str(model_name or "").strip()
    mode = "legacy" if not capacity_resolver_enabled() else "exact"
    cache_key = (mode, name.lower())
    cached = _WINDOW_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if mode == "legacy":
        result = _legacy_model_window(name)
    else:
        override = _env_override_window()
        if override is not None:
            result = (override, WINDOW_SOURCE_ENV)
        else:
            mapped = _registry_exact_window(name)
            if mapped is not None:
                result = (mapped, WINDOW_SOURCE_MAP)
            else:
                result = (_unknown_window(), WINDOW_SOURCE_FALLBACK)
                if name.lower() not in _WARNED_UNKNOWN:
                    _WARNED_UNKNOWN.add(name.lower())
                    logger.warning(
                        "model_capacity: unknown model %r — planning "
                        "window=%d (CHAT_UNKNOWN_MODEL_WINDOW, estimated, "
                        "НЕ provider-verified); точное окно даст каталог "
                        "провайдера/реестр",
                        name, result[0])
    _WINDOW_CACHE[cache_key] = result
    return result


def _parse_stage_window(model_name: str | None) -> tuple[int, str]:
    """Внутренний резолв стадии: режим определяется kill-switch один раз."""
    if not capacity_resolver_enabled():
        return _legacy_model_window(model_name)
    return resolve_model_context_window(model_name)


def resolve_effective_window(primary_model: str | None,
                             fallback_model: str | None = None
                             ) -> tuple[int, str]:
    """Окно PRIMARY-цепочки (SMART D4: без preemptive-min по fallback).

    Fallback-модель резолвится ОТДЕЛЬНО в момент фактического перехода
    (`fallback_window_for_model`/`resolve_stage_window`), поэтому маленькое
    окно резервной модели больше не занижает весь primary-payload заранее.
    Legacy-контур (kill-switch OFF) сохраняет прежний консервативный min —
    это rollback-путь без recompose-адаптера."""
    if not capacity_resolver_enabled():
        primary_window, source = _legacy_model_window(primary_model)
        name = str(fallback_model or "").strip()
        if not name:
            return primary_window, source
        fallback_window, _ = _legacy_model_window(name)
        if 0 < fallback_window < primary_window:
            return fallback_window, source
        return primary_window, source
    return resolve_model_context_window(primary_model)



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
#: SMART-EXECUTION-RELIABILITY-01 D2/D6: подтверждённый физический предел
#: фактического endpoint/model (structured context-overflow от провайдера).
#: Выше owner override — доказанный предел не переопределяется планированием.
SOURCE_PROVEN_LIMIT = "proven_limit"
#: Планировочное окно неизвестной модели (1 000 000): НЕ provider-verified.
SOURCE_ESTIMATED_UNKNOWN = "estimated_unknown"

CONFIDENCE_VERIFIED = "verified"
CONFIDENCE_ESTIMATED = "estimated"
#: Явный owner override: planning input, НЕ подтверждённая ёмкость.
CONFIDENCE_OVERRIDE = "override"
CONFIDENCE_FALLBACK = "fallback"


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
    source: str          # proven_limit|developer_override|runtime|provider_catalog|
                         # verified_registry|registry|estimated_unknown|fallback
    confidence: str      # verified|estimated|override|fallback
    resolved_at: float
    fallback_used: bool
    # SMART-EXECUTION-RELIABILITY-01 D2: конфликт override ↔ доказанный
    # физический предел виден потребителю (оба значения + факт клампа).
    override_value: int | None = None
    proven_limit: int | None = None
    clamped_by_proven_limit: bool = False

    def as_window_meta(self) -> dict:
        """R17-safe поля для событий/логов (без ключей и текста запроса)."""
        return {
            "provider": self.provider,
            "model": self.model,
            "effective_window": self.effective_context_window,
            "declared_window": self.declared_context_window,
            "runtime_window": self.runtime_context_window,
            "max_output_tokens": self.max_output_tokens,
            "source": self.source,
            "confidence": self.confidence,
            "override_value": self.override_value,
            "proven_limit": self.proven_limit,
            "clamped_by_proven_limit": bool(self.clamped_by_proven_limit),
            "fallback_used": bool(self.fallback_used),
        }



# ── Метрики §50 (process-local + grep-able `direct_metric name=…`) ─────────
_CAPACITY_METRICS: dict[str, int] = {
    "capacity_fallback_total": 0,
    "capacity_manual_override_total": 0,
    "capacity_resolved_total": 0,
    "capacity_proven_limit_total": 0,
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
    item = catalog_item_for_model(items, model)
    if item is None:
        return None
    return _first_positive_int(item, _CATALOG_CONTEXT_FIELDS)



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


def _first_positive_int(item: dict, fields) -> int | None:
    """Первое положительное целое из документированных полей каталога."""
    for field in fields:
        try:
            value = int(item.get(field))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


#: Документированные поля ёмкости каталогов (NanoGPT: `context_length`,
#: `max_output_tokens`; часть ответов отдаёт `max_context_tokens`/
#: `max_completion_tokens`). Неизвестное поле НЕ угадывается.
_CATALOG_CONTEXT_FIELDS = ("context_length", "max_context_tokens",
                           "context_window", "max_input_tokens")
_CATALOG_OUTPUT_FIELDS = ("max_output_tokens", "max_completion_tokens")


def catalog_item_for_model(items: list, model: str) -> dict | None:
    """Точный item каталога для запрошенной модели (namespace/suffix/alias).

    Порядок (без семейных/префиксных догадок):
      1. полный нормализованный ID равен одному из кандидатов запроса;
      2. basename (ID без namespace провайдера) равен кандидату РОВНО у одного
         item'а — иначе неоднозначно → None (честный miss);
      3. два разных item'а с одним basename → None.
    """
    if not isinstance(items, list):
        return None
    wanted = _model_candidates(model)
    if not wanted:
        return None
    exact: list[dict] = []
    by_base: dict[str, list[dict]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "")
        candidates = _model_candidates(raw_id)
        if not candidates:
            continue
        if any(cand in wanted for cand in candidates):
            exact.append(item)
            continue
        base = normalize_model_id(raw_id)
        if base:
            by_base.setdefault(base, []).append(item)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None                      # несколько вариантов — не гадаем
    matches: list[dict] = []
    seen_ids: set[str] = set()
    for cand in wanted:
        for item in by_base.get(cand, ()):  # type: ignore[arg-type]
            item_id = str(item.get("id") or "")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            matches.append(item)
    if len(matches) == 1:
        return matches[0]
    return None


async def _adapter_nanogpt_catalog(base_url: str, model: str
                                   ) -> tuple[int, int | None] | None:
    """Каталог NanoGPT (§53, D3): `(context_length, max_output_tokens | None)`.

    Сопоставление — ТОЛЬКО точное (namespace/suffix/alias нормализуются,
    `catalog_item_for_model`); каталог недоступен / модели нет / формат
    неоднозначен → None (→ exact registry или 1M estimated с честным
    source; выдуманных записей и семейных догадок нет). НЕ бросает."""
    wanted = str(model or "").strip()
    if not wanted:
        return None
    for url in _nanogpt_catalog_urls(base_url):
        data = await _http_get_json(url)
        if not isinstance(data, dict):
            continue
        items = data.get("data")
        if not isinstance(items, list):
            items = data.get("models")
        if not isinstance(items, list):
            continue
        item = catalog_item_for_model(items, wanted)
        if item is None:
            continue
        window = _first_positive_int(item, _CATALOG_CONTEXT_FIELDS)
        if window is None:
            # Модель есть, документированного окна нет — честный miss
            # (следующий URL/слой), НЕ 0 и НЕ 16384.
            continue
        return window, _first_positive_int(item, _CATALOG_OUTPUT_FIELDS)
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

    N1 ревью D: сравнение ID — каноническое (`_same_model_id`), иначе запись
    под полным ID (`z-ai/...`) переживала бы инвалидацию по короткому и
    затеняла доказанный предел.

    R17: provider host/model/reason — без ключей/URL-пути."""
    provider_class = detect_provider_class(base_url)
    host = _base_url_host(base_url)
    name = normalize_model_id(model) or str(model or "").strip().lower()
    victim_keys = [key for key in _CACHE
                   if key[0] == provider_class and key[1] == host
                   and _same_model_id(key[2], model)]
    for key in victim_keys:
        _CACHE.pop(key, None)
    if victim_keys:
        logger.warning(
            "MODEL_CAPACITY_CACHE_INVALIDATED | provider=%s | model=%s | "
            "entries=%d | reason=%s", provider_class, name,
            len(victim_keys), reason)
    return len(victim_keys)


# ── D6: подтверждённый физический предел endpoint/model + recovery ──────────
# Факт «провайдер сказал: не больше N токенов» сильнее любого каталога,
# кэша и owner override. Хранится process-local по
# (provider class, host, model, route); это НЕ новая таблица/БД (§K).


@dataclass(frozen=True)
class ProvenLimit:
    """Зафиксированный физический предел конкретного endpoint/model."""

    provider: str
    host: str
    model: str
    route: str
    limit_tokens: int
    max_output_tokens: int | None
    requested_tokens: int | None
    reason: str
    recorded_at: float


_PROVEN_LIMITS: dict[tuple, ProvenLimit] = {}
_PROVEN_LIMITS_MAX = 256


def _proven_key(base_url: str, model: str, route: str | None = None) -> tuple:
    return (detect_provider_class(base_url), _base_url_host(base_url),
            normalize_model_id(model), str(route or "").strip().lower())


def clear_proven_limits() -> int:
    """Сброс подтверждённых пределов (тесты; смена провайдера/деплоя)."""
    count = len(_PROVEN_LIMITS)
    _PROVEN_LIMITS.clear()
    return count


def proven_limit_for(base_url: str, model: str, *, route: str | None = None
                     ) -> int | None:
    """Подтверждённый физический предел для пары endpoint/model.

    ``base_url`` пуст → ищем по ID модели (единственное значение); разные
    пределы разных endpoint'ов не смешиваются (неоднозначно → None)."""
    model_key = normalize_model_id(model)
    if not model_key:
        return None
    if base_url:
        entry = _PROVEN_LIMITS.get(_proven_key(base_url, model, route))
        return entry.limit_tokens if entry is not None else None
    route_key = str(route or "").strip().lower()
    found = {entry.limit_tokens for entry in _PROVEN_LIMITS.values()
             if entry.model == model_key and entry.route == route_key}
    if len(found) == 1:
        return next(iter(found))
    return None


def record_proven_limit(base_url: str, model: str, limit_tokens: int, *,
                        route: str | None = None,
                        reason: str = "provider_context_overflow",
                        max_output_tokens: int | None = None,
                        requested_tokens: int | None = None
                        ) -> ProvenLimit | None:
    """Зафиксировать физический предел и сбросить устаревшие окна.

    Только положительное целое; мусор → None (ничего не записываем).
    Инвалидация: свежий cache value и sync-кэш этого model больше не
    используются — следующий резолв вернёт `proven_limit`."""
    try:
        limit = int(limit_tokens)
    except (TypeError, ValueError):
        return None
    if limit <= 0:
        return None
    key = _proven_key(base_url, model, route)
    entry = ProvenLimit(
        provider=key[0], host=key[1], model=key[2], route=key[3],
        limit_tokens=limit,
        max_output_tokens=(int(max_output_tokens)
                           if max_output_tokens and int(max_output_tokens) > 0
                           else None),
        requested_tokens=(int(requested_tokens)
                          if requested_tokens and int(requested_tokens) > 0
                          else None),
        reason=str(reason or "provider_context_overflow")[:64],
        recorded_at=time.time())
    if len(_PROVEN_LIMITS) >= _PROVEN_LIMITS_MAX and key not in _PROVEN_LIMITS:
        # FIFO-вытеснение: физические факты не растут без предела.
        oldest = min(_PROVEN_LIMITS, key=lambda k: _PROVEN_LIMITS[k].recorded_at)
        _PROVEN_LIMITS.pop(oldest, None)
    _PROVEN_LIMITS[key] = entry
    # Свежий каталог/кэш мог быть больше доказанного предела.
    invalidate_runtime_capacity(base_url, model, reason=entry.reason)
    for cache_key in [k for k in _WINDOW_CACHE
                      if _same_model_id(k[1], entry.model)]:
        _WINDOW_CACHE.pop(cache_key, None)
    _CAPACITY_METRICS["capacity_proven_limit_total"] += 1
    logger.warning(
        "MODEL_CAPACITY_PROVEN_LIMIT | provider=%s | model=%s | route=%s | "
        "limit=%d | requested=%s | reason=%s",
        entry.provider, entry.model, entry.route or "-", entry.limit_tokens,
        entry.requested_tokens, entry.reason)
    return entry


#: Структурированные коды провайдеров, означающие «контекст не влез».
CONTEXT_OVERFLOW_CODES = frozenset({
    "context_length_exceeded",
    "context_window_exceeded",
    "maximum_context_length_exceeded",
    "context_too_long",
    "prompt_too_long",
    "input_too_long",
    "request_too_large",
    "string_above_max_length",
    "too_many_tokens",
    "max_tokens_exceeded",
})

#: Текстовые маркеры «контекст не влез» (только при их наличии извлекаем
#: числа — иначе любая 400-ошибка дала бы ложный предел).
_CONTEXT_OVERFLOW_HINTS = (
    "context length", "context window", "maximum context", "context_length",
    "prompt is too long", "reduce the length of the messages",
    "too many tokens", "exceeds the context", "input is too long",
    "request too large", "string_above_max_length",
)

_LIMIT_TOKEN_PATTERNS = (
    re.compile(r"maximum context length is\s+([\d][\d,]*)", re.I),
    re.compile(r"context length of only\s+([\d][\d,]*)", re.I),
    re.compile(r"max(?:imum)? context (?:length|size|window)\s*"
               r"(?:is|of|:|=)?\s*([\d][\d,]*)", re.I),
    re.compile(r"context (?:length|window)\s*(?:is|of|:|=)\s*([\d][\d,]*)"
               r"\s*tokens", re.I),
    re.compile(r"limit(?:ed)? (?:is|of|to)?\s*([\d][\d,]*)\s*tokens", re.I),
    re.compile(r"([\d][\d,]*)\s*tokens?\s*(?:maximum|max)\b", re.I),
)
_REQUESTED_TOKEN_PATTERNS = (
    re.compile(r"you requested\s+([\d][\d,]*)", re.I),
    re.compile(r"resulted in\s+([\d][\d,]*)", re.I),
    re.compile(r"requested\s+([\d][\d,]*)\s*tokens", re.I),
    re.compile(r"prompt(?: is)?\s+too long:\s*([\d][\d,]*)", re.I),
    re.compile(r"([\d][\d,]*)\s*tokens\s*(?:>|greater than)", re.I),
)
_CONTEXT_NUMERIC_FIELDS = ("limit", "context_length", "max_context_tokens",
                           "context_window", "maximum_context_length",
                           "max_tokens_allowed")
_REQUESTED_NUMERIC_FIELDS = ("requested", "requested_tokens", "prompt_tokens",
                             "input_tokens", "num_tokens", "tokens")
_OUTPUT_NUMERIC_FIELDS = ("max_output_tokens", "max_completion_tokens",
                          "max_tokens")


def _to_int(value) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, str):
            value = value.replace(",", "").replace("_", "").strip()
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


@dataclass(frozen=True)
class ContextOverflowInfo:
    """Разобранная причина context length exceeded (§D6)."""

    code: str
    structured: bool
    limit_tokens: int | None
    requested_tokens: int | None
    max_output_tokens: int | None
    model: str
    detail: str


def _error_payloads(exc: BaseException) -> list:
    """Возможные носители структурированной ошибки у исключения (in-memory).

    `body` прикладывает `llm_client` для 4xx (обрезанный, НЕ логируется);
    `args`/`str(exc)` — текст; `error_body`/`payload` — словари адаптеров."""
    payloads: list = []
    for attr in ("error_body", "payload", "body"):
        value = getattr(exc, attr, None)
        if value is None:
            continue
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", "replace")
            except Exception:      # pragma: no cover - защитная ветка
                continue
        if isinstance(value, (dict, list, str)):
            payloads.append(value)
    for value in getattr(exc, "args", ()) or ():
        if isinstance(value, (dict, str)):
            payloads.append(value)
    return payloads


def _iter_error_dicts(payload) -> list[dict]:
    """Найти словари ошибки в т.ч. внутри JSON-строк и вложенных `error`."""
    out: list[dict] = []
    stack = [payload]
    while stack and len(out) < 8:
        node = stack.pop()
        if isinstance(node, str):
            text = node.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    import json
                    node = json.loads(text)
                except Exception:
                    continue
            else:
                continue
        if isinstance(node, list):
            stack.extend(node[:4])
            continue
        if not isinstance(node, dict):
            continue
        out.append(node)
        for key in ("error", "details", "data", "response", "innererror"):
            child = node.get(key)
            if isinstance(child, (dict, list)):
                stack.append(child)
    return out


def parse_context_overflow_error(exc: BaseException, *,
                                 text: str | None = None
                                 ) -> ContextOverflowInfo | None:
    """Разобрать структурированную ошибку провайдера «context exceeded».

    Возвращает `ContextOverflowInfo` только если есть маркер переполнения
    контекста (код или фраза). Числа берутся из структурированных полей,
    затем из текста; отсутствующее число остаётся None (uncertain) — мы НЕ
    выдумываем ёмкость. Никогда не бросает и не ходит в сеть."""
    try:
        payloads = _error_payloads(exc)
        if text:
            payloads.append(text)
        payloads.append(str(exc))
        code = ""
        model = ""
        limit = None
        requested = None
        max_output = None
        structured = False
        detail = ""
        blobs: list[str] = []
        for payload in payloads:
            if isinstance(payload, str):
                blobs.append(payload)
            for node in _iter_error_dicts(payload):
                structured = True
                raw_code = node.get("code") or node.get("type") or ""
                code = code or str(raw_code or "").strip()
                if not model:
                    model = str(node.get("model") or "").strip()
                for field in _CONTEXT_NUMERIC_FIELDS:
                    if limit is None:
                        limit = _to_int(node.get(field))
                for field in _REQUESTED_NUMERIC_FIELDS:
                    if requested is None:
                        requested = _to_int(node.get(field))
                for field in _OUTPUT_NUMERIC_FIELDS:
                    if max_output is None:
                        max_output = _to_int(node.get(field))
                message = node.get("message")
                if isinstance(message, str):
                    blobs.append(message)
        lowered = " ".join(blobs).lower()
        code_key = code.lower()
        hinted = (code_key in CONTEXT_OVERFLOW_CODES
                  or any(hint in lowered for hint in _CONTEXT_OVERFLOW_HINTS))
        if not hinted:
            return None
        if limit is None:
            for pattern in _LIMIT_TOKEN_PATTERNS:
                match = pattern.search(" ".join(blobs).replace(",", ""))
                if match:
                    limit = _to_int(match.group(1))
                    if limit is not None:
                        break
        if requested is None:
            for pattern in _REQUESTED_TOKEN_PATTERNS:
                match = pattern.search(" ".join(blobs).replace(",", ""))
                if match:
                    requested = _to_int(match.group(1))
                    if requested is not None:
                        break
        if not code:
            code = "context_length_exceeded"
        detail = (code_key or "context_length_exceeded")[:48]
        return ContextOverflowInfo(
            code=code[:48], structured=structured,
            limit_tokens=limit, requested_tokens=requested,
            max_output_tokens=max_output,
            model=model[:96], detail=detail)
    except Exception:      # pragma: no cover - парсер не рвёт обработку ошибки
        return None


#: Ограниченное восстановление: одна повторная сборка payload на запрос.
CONTEXT_RECOVERY_MAX_ATTEMPTS = 1


@dataclass(frozen=True)
class ContextRecoveryPlan:
    """Решение о восстановлении текущего запроса (§D6, bounded)."""

    info: ContextOverflowInfo
    limit_tokens: int
    budget_tokens: int
    output_reserve: int
    attempt: int
    max_attempts: int
    uncertain: bool
    preserve_tool_evidence: bool
    reason: str

    def as_event_counts(self) -> dict:
        return {
            "reason": self.reason,
            "limit_tokens": self.limit_tokens,
            "budget_tokens": self.budget_tokens,
            "output_reserve": self.output_reserve,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "uncertain": bool(self.uncertain),
        }


def recovery_budget_tokens(limit_tokens: int, *,
                           output_reserve_tokens: int = 0,
                           protocol_reserve_tokens: int = 0) -> int:
    """Входной бюджет под доказанный предел: `safe_budget(limit − reserves)`.

    Окно — физический предел, max_output — отдельная величина (D5): резерв
    ответа и protocol overhead вычитаются, но НЕ превращаются в 16384.
    Никогда не бросает; минимум 1."""
    try:
        limit = max(1, int(limit_tokens))
    except (TypeError, ValueError):
        return 1
    try:
        reserve = max(0, int(output_reserve_tokens or 0))
    except (TypeError, ValueError):
        reserve = 0
    try:
        protocol = max(0, int(protocol_reserve_tokens or 0))
    except (TypeError, ValueError):
        protocol = 0
    base = max(1, limit - reserve - protocol)
    return max(1, int(safe_budget(base)))


def note_context_overflow(exc: BaseException, *, base_url: str, model: str,
                          route: str | None = None,
                          output_reserve_tokens: int | None = None,
                          protocol_reserve_tokens: int = 0,
                          attempt: int = 0,
                          max_attempts: int = CONTEXT_RECOVERY_MAX_ATTEMPTS
                          ) -> tuple[ContextOverflowInfo | None,
                                     ContextRecoveryPlan | None]:
    """Разобрать context-overflow, обновить capacity и дать план recovery.

    * структурированный предел найден → фиксируется как `proven_limit`
      (выше каталога/override), инвалидируется устаревший кэш;
    * предел не раскрыт → `uncertain=True`, budget=0: вызывающий идёт
      существующим адаптивным путём (recompose/fallback), без 16384;
    * `attempt >= max_attempts` → plan=None (никаких бесконечных платных
      повторов); info возвращается для наблюдаемости/остановки.
    Сеть не используется: миллионный probe запрещён (§D6).
    Никогда не бросает."""
    info = parse_context_overflow_error(exc)
    if info is None:
        return None, None
    try:
        target_model = str(model or info.model or "")
        reserve = 0
        try:
            reserve = max(0, int(output_reserve_tokens or 0))
        except (TypeError, ValueError):
            reserve = 0
        if reserve <= 0:
            reserve = output_reserve_tokens_for_stage()
        limit = info.limit_tokens or 0
        if limit <= 0:
            return info, None if attempt >= max_attempts else ContextRecoveryPlan(
                info=info, limit_tokens=0, budget_tokens=0,
                output_reserve=int(reserve or 0),
                attempt=int(attempt) + 1, max_attempts=int(max_attempts),
                uncertain=True, preserve_tool_evidence=True,
                reason="limit_not_disclosed")
        record_proven_limit(
            base_url, target_model, limit, route=route,
            max_output_tokens=info.max_output_tokens,
            requested_tokens=info.requested_tokens,
            reason=info.code or "provider_context_overflow")
        if attempt >= max_attempts:
            return info, None
        budget = recovery_budget_tokens(
            limit, output_reserve_tokens=reserve or 0,
            protocol_reserve_tokens=protocol_reserve_tokens)
        return info, ContextRecoveryPlan(
            info=info, limit_tokens=limit, budget_tokens=budget,
            output_reserve=int(reserve or 0), attempt=int(attempt) + 1,
            max_attempts=int(max_attempts), uncertain=False,
            preserve_tool_evidence=True, reason="proven_limit_recorded")
    except Exception:      # pragma: no cover - recovery не рвёт обработку
        return info, None


def output_reserve_tokens_for_stage() -> int:
    """Резерв ответа по умолчанию для recovery (floor 1024).

    max_output — отдельная величина от окна (D5): здесь только минимальный
    protocol/output-reserve, без процентов «на качество»."""
    return OUTPUT_RESERVE_FLOOR


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

    Precedence (SMART-EXECUTION-RELIABILITY-01 D2/D6):
    proven physical limit → developer override (planning input, capped by the
    proven limit) → runtime metadata → provider catalog → fresh verified
    cache (этот уровень реализует сам `resolve_capacity`) → exact registry →
    1M estimated/unknown. OFF-kill-switch → прежний контур 2.58.47
    (runtime → catalog → registry → override → unknown 1M, не 16384).
    `effective = min(runtime, exact registry)` для metadata без live
    precedence; family-префиксы ёмкость не определяют. Никогда не бросает;
    `route` входит в cache key (смена route инвалидирует)."""
    name = str(model or "").strip()
    provider_class = detect_provider_class(base_url)
    override = _developer_override_window()
    key = _cache_key(base_url, name, route)
    now = time.time()
    cached = _CACHE.get(key)
    if cached is not None:
        result, expires_at = cached
        if now < expires_at:
            # ON: stale registry/estimate не должен занижать (или завышать)
            # live capability → пере-резолв; fallback/estimate кэшируются
            # коротко (300 с) и не долбят недоступный endpoint.
            skip_stale = (
                live_precedence_enabled()
                and result.source == SOURCE_REGISTRY
                and provider_class in (PROVIDER_NANOGPT, PROVIDER_OPENROUTER,
                                       PROVIDER_LLAMA_CPP, PROVIDER_OLLAMA))
            if not skip_stale:
                return result
            _CACHE.pop(key, None)      # stale registry/estimate — re-resolve
        else:
            _CACHE.pop(key, None)

    result = await _resolve_uncached(provider_class, base_url, name,
                                     override, route=route)
    short_lived = result.fallback_used or result.source in (
        SOURCE_ESTIMATED_UNKNOWN, SOURCE_FALLBACK)
    ttl = _FALLBACK_TTL_SECONDS if short_lived else _ttl_for(provider_class)
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

    D2-порядок: proven_limit (0) → override при live (1) → runtime (2) →
    provider catalog (3) → route metadata (3b) → exact registry (5) →
    legacy override при OFF (6) → 1M estimated (7).

    Owner override — planning input: он не отменяет доказанный физический
    предел (конфликт виден в `override_value`/`clamped_by_proven_limit`) и
    НЕ маркируется provider-verified (`confidence="override"`)."""
    now = time.time()
    live = live_precedence_enabled()
    override_value = override
    # ── 0) proven physical limit (D6): сильнее каталога, кэша и override ───
    proven = proven_limit_for(base_url, name, route=route)
    if proven is not None:
        if override is not None and 0 < override <= proven:
            _CAPACITY_METRICS["capacity_manual_override_total"] += 1
            return CapacityResult(
                provider=provider_class, model=name,
                declared_context_window=proven, runtime_context_window=None,
                effective_context_window=override, max_output_tokens=None,
                source=SOURCE_DEVELOPER_OVERRIDE,
                confidence=CONFIDENCE_OVERRIDE, resolved_at=now,
                fallback_used=False, override_value=override,
                proven_limit=proven, clamped_by_proven_limit=False)
        clamped = override is not None and override > proven
        return CapacityResult(
            provider=provider_class, model=name,
            declared_context_window=proven, runtime_context_window=None,
            effective_context_window=proven, max_output_tokens=None,
            source=SOURCE_PROVEN_LIMIT, confidence=CONFIDENCE_VERIFIED,
            resolved_at=now, fallback_used=False,
            override_value=(override if clamped else None),
            proven_limit=proven, clamped_by_proven_limit=bool(clamped))
    # ── 1) developer override — уровень 1 (live precedence ON) ─────────────
    if live and override is not None:
        _CAPACITY_METRICS["capacity_manual_override_total"] += 1
        return CapacityResult(
            provider=provider_class, model=name,
            declared_context_window=None, runtime_context_window=None,
            effective_context_window=override, max_output_tokens=None,
            source=SOURCE_DEVELOPER_OVERRIDE, confidence=CONFIDENCE_OVERRIDE,
            resolved_at=now, fallback_used=False,
            override_value=override_value)
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
            declared = _registry_exact_window(name) or catalog_window
            effective = catalog_window if (live or declared is None) \
                else min(catalog_window, declared)
            return CapacityResult(
                provider=provider_class, model=name,
                declared_context_window=declared,
                runtime_context_window=None,
                effective_context_window=effective,
                max_output_tokens=None, source=SOURCE_PROVIDER_CATALOG,
                confidence=CONFIDENCE_VERIFIED, resolved_at=now,
                fallback_used=False)
    elif provider_class == PROVIDER_NANOGPT:
        # 3) provider catalog (§53, D3): live/public каталог NanoGPT —
        # context window + max output; точное сопоставление ID
        # (namespace/suffix/alias), без семейных догадок. Miss → exact
        # registry → 1M estimated (ниже).
        catalog = await _adapter_nanogpt_catalog(base_url, name)
        if catalog is not None:
            catalog_window, max_output = catalog
            declared = _registry_exact_window(name) or catalog_window
            # T-4808: live precedence ON → live catalog суверенен, exact
            # registry НЕ занижает live capability (declared — для
            # прозрачности); OFF → прежний min(live, registry).
            effective = catalog_window if (live or declared is None) \
                else min(catalog_window, declared)
            return CapacityResult(
                provider=provider_class, model=name,
                declared_context_window=declared,
                runtime_context_window=None,
                effective_context_window=effective,
                max_output_tokens=max_output,
                source=SOURCE_PROVIDER_CATALOG,
                confidence=CONFIDENCE_VERIFIED, resolved_at=now,
                fallback_used=False)
    # ── 3b) verified route metadata (live precedence ON) ───────────────────
    # Маршрут-специфичная metadata (например, endpoint-лимиты) — только из
    # верифицированного адаптера; без подтверждения слой честно пропускается.
    if live:
        route_result = await _resolve_route_metadata(
            provider_class, base_url, name, route)
        if route_result is not None:
            return route_result

    # ── 5) exact registry (D2): только ТОЧНЫЙ ID, без семейных префиксов ────
    declared_window = _registry_exact_window(name)
    if runtime_window is not None:
        # §5: effective = min(runtime, exact provider/model limit) — OFF.
        # T-4808: live precedence ON → runtime (live) суверенен, exact
        # registry не занижает.
        effective = runtime_window if (live or declared_window is None) \
            else min(runtime_window, declared_window)
        return CapacityResult(
            provider=runtime_provider, model=name,
            declared_context_window=declared_window,
            runtime_context_window=runtime_window,
            effective_context_window=effective, max_output_tokens=None,
            source=SOURCE_RUNTIME, confidence=CONFIDENCE_VERIFIED,
            resolved_at=now, fallback_used=False)
    if declared_window is not None:
        if provider_class == PROVIDER_DEEPSEEK:
            # §54 (T-4202): Direct DeepSeek — отдельный identity; machine-
            # readable catalog нет → verified official registry entry,
            # source=`verified_registry` (НЕ `provider_catalog`).
            return CapacityResult(
                provider=provider_class, model=name,
                declared_context_window=declared_window,
                runtime_context_window=None,
                effective_context_window=declared_window,
                max_output_tokens=None, source=SOURCE_VERIFIED_REGISTRY,
                confidence=CONFIDENCE_VERIFIED, resolved_at=now,
                fallback_used=False)
        return CapacityResult(
            provider=provider_class, model=name,
            declared_context_window=declared_window,
            runtime_context_window=None,
            effective_context_window=declared_window,
            max_output_tokens=None, source=SOURCE_REGISTRY,
            confidence=CONFIDENCE_VERIFIED, resolved_at=now,
            fallback_used=False)

    # ── 6) developer override (уровень 4; legacy OFF-контур 2.58.47) ───────
    # применяется ТОЛЬКО когда live precedence OFF (AMEND ADR-1028-8 D2).
    if override is not None:
        return CapacityResult(
            provider=provider_class, model=name,
            declared_context_window=None, runtime_context_window=None,
            effective_context_window=override, max_output_tokens=None,
            source=SOURCE_DEVELOPER_OVERRIDE, confidence=CONFIDENCE_OVERRIDE,
            resolved_at=now, fallback_used=False, override_value=override_value)

    # ── 7) 1M estimated/unknown (D1): планировочная оценка, не verified ────
    window = _unknown_window()
    if not live:
        # Legacy-контур OFF: прежнее аварийное поведение (badge fallback),
        # но окно — 1M, не 16384 (D1 применяется и к legacy resolver'у).
        result = CapacityResult(
            provider=provider_class, model=name,
            declared_context_window=None, runtime_context_window=None,
            effective_context_window=window,
            max_output_tokens=None, source=SOURCE_FALLBACK,
            confidence=CONFIDENCE_FALLBACK, resolved_at=now,
            fallback_used=True)
        _warn_capacity_fallback(result, base_url,
                                "unknown_model_no_adapter_data")
        return result
    if name and normalize_model_id(name) not in _WARNED_UNKNOWN:
        _WARNED_UNKNOWN.add(normalize_model_id(name))
        logger.warning(
            "MODEL_CAPACITY_UNKNOWN_ESTIMATE | provider=%s | model=%s | "
            "planning_window=%d | source=estimated_unknown — НЕ "
            "provider-verified (каталог/реестр не дали значения)",
            provider_class, name[:64], window)
    return CapacityResult(
        provider=provider_class, model=name,
        declared_context_window=None, runtime_context_window=None,
        effective_context_window=window,
        max_output_tokens=None, source=SOURCE_ESTIMATED_UNKNOWN,
        confidence=CONFIDENCE_ESTIMATED, resolved_at=now,
        fallback_used=False)



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


def _cached_verified_window(base_url: str, model: str,
                            route: str | None = None
                            ) -> tuple[int, str] | None:
    """Свежее ВЕРИФИЦИРОВАННОЕ значение того же provider/base_url/model/route.

    D2-уровень 4: sync-потребители (tool-окно, fallback recompose) не ходят
    в сеть, но обязаны видеть уже подтверждённую ёмкость (каталог/рантайм/
    proven), а не планировочные 1M. Route входит в область совпадения
    (контракт D2: «cached value только того же endpoint+model+route»):
    значение, посчитанное для другого route того же endpoint'а, не наследуется
    (sync-путь без route видит только route-less записи)."""
    model_key = normalize_model_id(model)
    if not model_key:
        return None
    provider_class = detect_provider_class(base_url)
    host = _base_url_host(base_url)
    route_key = str(route or "").strip().lower()
    now = time.time()
    for key, (result, expires_at) in list(_CACHE.items()):
        if now >= expires_at:
            continue
        if key[0] != provider_class:
            continue
        if normalize_model_id(key[2]) != model_key \
                and str(key[2]).strip().lower() != str(model or "").strip().lower():
            continue
        if base_url and key[1] != host:
            continue
        if str(key[5] if len(key) > 5 else "").strip().lower() != route_key:
            continue
        if result.source in (SOURCE_FALLBACK, SOURCE_ESTIMATED_UNKNOWN):
            continue
        return (result.effective_context_window, result.source)
    return None


async def resolve_stage_window(base_url: str, model: str, *,
                               slot: str | None = None
                               ) -> tuple[int, str]:
    """Drop-in для потребителей: ``(effective_window, source)``.

    Kill-switch OFF → legacy-контур (`_legacy_model_window`: семейная карта +
    env + 1M unknown — НЕ 16384)."""
    if not capacity_resolver_enabled():
        return _legacy_model_window(model)
    result = await resolve_capacity(base_url, model, slot=slot)
    return result.effective_context_window, result.source


def fallback_window_for_model(model: str) -> tuple[int, str]:
    """Окно fallback-модели БЕЗ сети (D4: resolve fallback отдельно перед
    recompose). Runtime-адаптеры и каталоги не вызываются: proven limit →
    developer override → exact registry → 1M estimated. Семейные префиксы
    ёмкость не определяют. Для точного runtime-окна fallback'а используется
    `resolve_stage_window`."""
    if not capacity_resolver_enabled():
        return _legacy_model_window(model)
    proven = proven_limit_for("", str(model or ""))
    override = _developer_override_window()
    if proven is not None:
        if override is not None and 0 < override <= proven:
            return override, SOURCE_DEVELOPER_OVERRIDE
        return proven, SOURCE_PROVEN_LIMIT
    if override is not None:
        return override, SOURCE_DEVELOPER_OVERRIDE
    mapped = _registry_exact_window(str(model or ""))
    if mapped is not None:
        return mapped, SOURCE_REGISTRY
    return _unknown_window(), SOURCE_ESTIMATED_UNKNOWN


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


# ═══════════════════════════════════════════════════════════════════════════
# ASAP-EVIDENCE-ROUTING-01 v3 (§3 Retrieve / §4.4 Dynamic Evidence Window):
# окно ОДНОГО read-only tool-вызова выводится из РЕАЛЬНОГО окна модели, а не
# из магических 4000/8000. Здесь только арифметика «доля окна → символы»;
# политика стадии и предохранители — в `services/auto_budget.py`
# (`resolve_evidence_tool_window`), чтобы не заводить второй бюджетный движок.
#
# Ограничение честно: резолв здесь синхронный (registry/env/fallback уровня
# D1). Live-metadata провайдера остаётся async в `resolve_capacity` и
# используется композером; tool-путь не должен ждать discovery (2 с) ради
# одного вызова. Значение `window_source` показывает, откуда взято окно.

#: Доля входного бюджета модели, которую может занять ОДИН tool-результат.
#: Hot-ключ `limits.evidence_tool_window_share` (дефолт ниже). Это не «потолок
#: качества», а ограничитель лавины: несколько вызовов идут в одном окне.
EVIDENCE_WINDOW_SHARE_DEFAULT = 0.20

#: Символов на токен для оценки (консервативно для русского текста).
CHARS_PER_TOKEN_ESTIMATE = 4


def chars_for_tokens(tokens: int | None) -> int:
    """Оценка символов по числу токенов (0/мусор → 0). Никогда не бросает."""
    try:
        return max(0, int(tokens or 0)) * CHARS_PER_TOKEN_ESTIMATE
    except (TypeError, ValueError):
        return 0


def evidence_window_share() -> float:
    """Доля окна на один tool-вызов: hot `limits.evidence_tool_window_share`.

    Мусор/отрицательное значение → дефолт (никогда не бросает)."""
    try:
        raw = hot.get("limits.evidence_tool_window_share",
                      EVIDENCE_WINDOW_SHARE_DEFAULT)
        share = float(raw)
    except Exception:      # pragma: no cover - защитная ветка
        return EVIDENCE_WINDOW_SHARE_DEFAULT
    if share <= 0.0 or share > 1.0:
        return EVIDENCE_WINDOW_SHARE_DEFAULT
    return share


def evidence_window_for_tokens(window_tokens: int | None, *,
                               share: float | None = None,
                               floor: int = 0,
                               ceiling: int | None = None) -> int:
    """Сколько символов одного tool-результата допускает окно модели.

    ``clamp(int(window_chars × share), floor, ceiling)``; ``ceiling`` не
    задан → без верхнего обрезателя (физический предел задаёт вызывающая
    стадия: `TOOL_RESULT_HARD_CEILING`)."""
    window_chars = chars_for_tokens(window_tokens)
    if window_chars <= 0:
        return max(0, int(floor or 0))
    ratio = evidence_window_share() if share is None else max(0.0, float(share))
    value = int(window_chars * ratio)
    value = max(int(floor or 0), value)
    if ceiling is not None and int(ceiling) > 0:
        value = min(value, int(ceiling))
    return max(0, value)


def resolve_evidence_window_tokens(model: str | None = None,
                                   base_url: str | None = None
                                   ) -> tuple[int, str]:
    """``(window_tokens, window_source)`` синхронного пути (tool-окно).

    SMART D2: модель — ФАКТИЧЕСКИ назначенная стадии (не «всегда главная»),
    ``base_url`` — её endpoint. Порядок без сети:
    proven_limit → verified cache этого endpoint/model → env override →
    exact registry → 1M estimated (``unknown_fallback``, оценка).
    Неизвестная модель больше НЕ получает 16384."""
    name = str(model or "").strip()
    if not name:
        try:
            name = str(hot.get("models.llm_model_name",
                               getattr(settings, "LLM_MODEL_NAME", "")) or "")
        except Exception:      # pragma: no cover - защитная ветка
            name = str(getattr(settings, "LLM_MODEL_NAME", "") or "")
    endpoint = str(base_url or "").strip()
    if not capacity_resolver_enabled():
        return _legacy_model_window(name)
    proven = proven_limit_for(endpoint, name)
    if proven is not None:
        override = _developer_override_window()
        if override is not None and 0 < override <= proven:
            return override, SOURCE_DEVELOPER_OVERRIDE
        return proven, SOURCE_PROVEN_LIMIT
    if endpoint:
        cached = _cached_verified_window(endpoint, name)
        if cached is not None:
            return cached
    return resolve_model_context_window(name)



def evidence_window_dynamic_enabled() -> bool:
    """Kill-switch `EVIDENCE_WINDOW_DYNAMIC_ENABLED` (env-only ClassVar,
    default ON; резолв per-call; никогда не бросает). OFF → вызывающий
    потребитель обязан идти прежним legacy-путём (фиксированные 4000/8000)
    байт-в-байт."""
    try:
        return bool(getattr(settings, "EVIDENCE_WINDOW_DYNAMIC_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


__all__ = [
    "MODEL_CONTEXT_WINDOWS", "MODEL_EXACT_WINDOWS", "UNKNOWN_WINDOW_DEFAULT",
    "WINDOW_SOURCE_MAP", "WINDOW_SOURCE_ENV",
    "WINDOW_SOURCE_FALLBACK", "OUTPUT_RESERVE_FLOOR",
    "normalize_model_id", "catalog_item_for_model",
    "resolve_model_context_window", "resolve_effective_window",
    "output_reserve_tokens", "compute_available_budget",
    "apply_budget_policy",
    "capability_aware_output_reserve", "reserve_for_capacity",
    "live_precedence_enabled", "capability_reserve_enabled",
    # ASAP-3.1 (ADR-1028-3): structured capacity resolver.
    "SOURCE_DEVELOPER_OVERRIDE", "SOURCE_RUNTIME", "SOURCE_PROVIDER_CATALOG",
    "SOURCE_VERIFIED_REGISTRY", "SOURCE_REGISTRY", "SOURCE_FALLBACK",
    "SOURCE_PROVEN_LIMIT", "SOURCE_ESTIMATED_UNKNOWN",
    "CONFIDENCE_VERIFIED", "CONFIDENCE_ESTIMATED", "CONFIDENCE_OVERRIDE",
    "CONFIDENCE_FALLBACK",
    "PROVIDER_OPENROUTER", "PROVIDER_NANOGPT", "PROVIDER_DEEPSEEK",
    "PROVIDER_OLLAMA", "PROVIDER_LLAMA_CPP",
    "PROVIDER_VLLM", "PROVIDER_GENERIC",
    "CapacityResult", "LOCAL_ADAPTER_TTL_SECONDS",
    "capacity_resolver_enabled", "detect_provider_class",
    "invalidate_capacity_cache", "capacity_metrics_snapshot",
    "resolve_capacity", "resolve_stage_window", "fallback_window_for_model",
    # SMART-EXECUTION-RELIABILITY-01 D2/D6: proven physical limit + recovery.
    "ProvenLimit", "proven_limit_for", "record_proven_limit",
    "clear_proven_limits",
    "ContextOverflowInfo", "parse_context_overflow_error",
    "ContextRecoveryPlan", "note_context_overflow",
    "recovery_budget_tokens", "CONTEXT_RECOVERY_MAX_ATTEMPTS",
    "CONTEXT_OVERFLOW_CODES",
    # ASAP 4.1 (эпик asap-4-1-durable-whole-window-summary): capacity engine
    # Summary (T-4604/T-4605).
    "MODE_WHOLE_WINDOW", "MODE_CAPACITY_OVERFLOW",
    "SummaryCapacityPlan", "decide_summary_mode", "replan_summary_capacity",
    "invalidate_runtime_capacity",
    # ASAP-EVIDENCE-ROUTING-01 v3: окно одного tool-вызова из реального окна.
    "EVIDENCE_WINDOW_SHARE_DEFAULT", "CHARS_PER_TOKEN_ESTIMATE",
    "chars_for_tokens", "evidence_window_share",
    "evidence_window_for_tokens", "resolve_evidence_window_tokens",
    "evidence_window_dynamic_enabled",
]
