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
"""
from __future__ import annotations

import logging

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
    """Префикс-матч по карте (lower-case); longest-prefix приоритет."""
    name = str(model_name or "").strip().lower()
    if not name:
        return None
    best_key = ""
    best_window = None
    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if name.startswith(key) and len(key) > len(best_key):
            best_key = key
            best_window = int(window)
    return best_window


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


__all__ = [
    "MODEL_CONTEXT_WINDOWS", "WINDOW_SOURCE_MAP", "WINDOW_SOURCE_ENV",
    "WINDOW_SOURCE_FALLBACK", "OUTPUT_RESERVE_FLOOR",
    "resolve_model_context_window", "resolve_effective_window",
    "output_reserve_tokens", "compute_available_budget",
    "apply_budget_policy",
]
