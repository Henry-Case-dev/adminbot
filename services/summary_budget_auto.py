"""ASAP-3.1 (round 1028, ADR-1028-3 D3/Q4/Q5, spec §7/§77/§78) — Auto-семантика
гибридных бюджетов Summary L1/L2.

Контракт (§75–§78):
  * `limits.summary_hybrid_context_tokens` — НЕТРОНУТЫЙ канонический дефолт
    (30000) → **Auto** (0/null-семантика по существующей migration
    convention): физический бюджет = capacity выбранной L1/L2-модели через
    общий Auto Budget Resolver; legacy static 30000 НЕ создаёт artificial
    21001 cap (§112.41).
  * реально кастомное значение владельца (>0, ≠ дефолт) → **Developer manual
    cap** = «максимальный размер ОДНОГО L1-запроса» (§137), «Ручное
    ограничение включено»; custom-preservation (§78, «кастом владельца — НЕ
    трогаем»).
  * `…_chars` (chars-kind fallback) — legacy/emergency (§77): старый путь,
    из Auto НЕ поднимается; ключ сохраняется (Δ удалений = 0).
  * legacy `MAX_SUMMARY_PARTS` в Hybrid не используется — закреплено тестом.

Kill-switch'и: `AUTO_BUDGET_RESOLVER_ENABLED` и `MODEL_CAPACITY_RESOLVER_
ENABLED` (env-only, default ON) — любой OFF → прежняя статическая
арифметика (safe_budget(30000) − system − reserve) байт-в-байт.
Никогда не бросает (R3); R17 — наружу только числа/enum.
"""
from __future__ import annotations

import logging

from config.settings import settings
from services import model_capacity as capacity
from services import auto_budget as auto
from services.summary_hybrid_budget import (
    HYBRID_CONTEXT_TOKEN_DEFAULT,
    hybrid_input_budget,
    hybrid_output_reserve_tokens,
    resolve_hybrid_context_budget,
)

logger = logging.getLogger(__name__)

# Результат резолва режима бюджета (для логов/диагностики; R17-enum).
BUDGET_MODE_AUTO = "auto"
BUDGET_MODE_MANUAL_CAP = "manual_cap"
BUDGET_MODE_LEGACY_STATIC = "legacy_static"


def hybrid_manual_cap_tokens(*, hot_get=None, settings_obj=None) -> int | None:
    """``None`` = Auto; ``>0`` = Developer manual cap (размер ОДНОГО L1-запроса,
    §137). chars-kind → ``-1`` (legacy/emergency путь, §77)."""
    kind, limit = resolve_hybrid_context_budget(hot_get=hot_get,
                                                settings_obj=settings_obj)
    if kind != "tokens":
        return -1
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return None
    if limit <= 0:
        return None
    if limit == HYBRID_CONTEXT_TOKEN_DEFAULT:
        # Нетронутый канонический дефолт → Auto (миграция §78: default → Auto).
        return None
    return limit


async def resolve_l1_effective_budget(system_text: str, slot, *,
                                      hot_get=None,
                                      settings_obj=None) -> tuple[str, int,
                                                                 str]:
    """Эффективный бюджет входа L1: ``(kind, limit, budget_mode)``.

    Auto → capacity слота `summary.l1` через общий resolver (safety ×1,
    output reserve L1 4000, system tokens — mandatory). Manual cap →
    прежняя формула hybrid_input_budget. Legacy static (kill-switch OFF /
    chars) → прежний путь байт-в-байт. Никогда не бросает.
    """
    st = settings_obj or settings
    cap_tokens = hybrid_manual_cap_tokens(hot_get=hot_get, settings_obj=st)
    if cap_tokens == -1:
        # chars-fallback (emergency) — прежний путь целиком.
        kind, limit = resolve_hybrid_context_budget(hot_get=hot_get,
                                                    settings_obj=st)
        effective = hybrid_input_budget(
            kind, limit, system_text=system_text,
            output_reserve=hybrid_output_reserve_tokens(
                kind="l1", settings_obj=st))
        return kind, effective, BUDGET_MODE_LEGACY_STATIC
    if cap_tokens is not None:
        return ("tokens",
                hybrid_input_budget(
                    "tokens", cap_tokens, system_text=system_text,
                    output_reserve=hybrid_output_reserve_tokens(
                        kind="l1", settings_obj=st)),
                BUDGET_MODE_MANUAL_CAP)
    if not (auto.auto_budget_enabled()
            and capacity.capacity_resolver_enabled()):
        kind, limit = resolve_hybrid_context_budget(hot_get=hot_get,
                                                    settings_obj=st)
        effective = hybrid_input_budget(
            kind, limit, system_text=system_text,
            output_reserve=hybrid_output_reserve_tokens(
                kind="l1", settings_obj=st))
        return kind, effective, BUDGET_MODE_LEGACY_STATIC
    try:
        result = await auto.resolve_stage_budget(
            "summary.l1", base_url=slot.base_url, model=slot.model,
            mandatory_tokens=_count_tokens_safe(system_text))
        return "tokens", result.effective_input_budget, BUDGET_MODE_AUTO
    except Exception:      # fail-closed к прежнему статическому пути
        logger.warning("summary budget auto: resolve failed — legacy static",
                       exc_info=True)
        kind, limit = resolve_hybrid_context_budget(hot_get=hot_get,
                                                    settings_obj=st)
        effective = hybrid_input_budget(
            kind, limit, system_text=system_text,
            output_reserve=hybrid_output_reserve_tokens(
                kind="l1", settings_obj=st))
        return kind, effective, BUDGET_MODE_LEGACY_STATIC


async def resolve_l2_effective_budget(system_text: str, slot, *,
                                      hot_get=None,
                                      settings_obj=None) -> tuple[str, int,
                                                                 str]:
    """Аналог L1 для слота `summary.l2` (reserve 6000)."""
    st = settings_obj or settings
    cap_tokens = hybrid_manual_cap_tokens(hot_get=hot_get, settings_obj=st)
    if cap_tokens == -1:
        kind, limit = resolve_hybrid_context_budget(hot_get=hot_get,
                                                    settings_obj=st)
        effective = hybrid_input_budget(
            kind, limit, system_text=system_text,
            output_reserve=hybrid_output_reserve_tokens(
                kind="l2", settings_obj=st))
        return kind, effective, BUDGET_MODE_LEGACY_STATIC
    if cap_tokens is not None:
        return ("tokens",
                hybrid_input_budget(
                    "tokens", cap_tokens, system_text=system_text,
                    output_reserve=hybrid_output_reserve_tokens(
                        kind="l2", settings_obj=st)),
                BUDGET_MODE_MANUAL_CAP)
    if not (auto.auto_budget_enabled()
            and capacity.capacity_resolver_enabled()):
        kind, limit = resolve_hybrid_context_budget(hot_get=hot_get,
                                                    settings_obj=st)
        effective = hybrid_input_budget(
            kind, limit, system_text=system_text,
            output_reserve=hybrid_output_reserve_tokens(
                kind="l2", settings_obj=st))
        return kind, effective, BUDGET_MODE_LEGACY_STATIC
    try:
        result = await auto.resolve_stage_budget(
            "summary.l2", base_url=slot.base_url, model=slot.model,
            mandatory_tokens=_count_tokens_safe(system_text))
        return "tokens", result.effective_input_budget, BUDGET_MODE_AUTO
    except Exception:      # pragma: no cover - fail-closed к статике
        logger.warning("summary budget auto L2: resolve failed — legacy",
                       exc_info=True)
        kind, limit = resolve_hybrid_context_budget(hot_get=hot_get,
                                                    settings_obj=st)
        effective = hybrid_input_budget(
            kind, limit, system_text=system_text,
            output_reserve=hybrid_output_reserve_tokens(
                kind="l2", settings_obj=st))
        return kind, effective, BUDGET_MODE_LEGACY_STATIC


def _count_tokens_safe(text: str) -> int:
    try:
        from services.token_counter import count_tokens
        return max(0, int(count_tokens(text or "")))
    except Exception:      # pragma: no cover - защитная ветка
        return 0


async def resolve_l2_package_budget() -> tuple[str, int, str]:
    """Бюджет L2-пакета (FactPackage → L2 вход) в Auto-семантике.

    ``(kind, limit, budget_mode)``; Auto → capacity слота `summary.l2` через
    общий resolver (safe_budget(window) − tokens(L2 system) − reserve 6000).
    Вызывается из генератора (async-контекст) и передаётся в
    ``build_fact_package``/``build_fallback_package`` явным ``budget``.
    Никогда не бросает."""
    st = settings
    cap_tokens = hybrid_manual_cap_tokens(hot_get=None, settings_obj=st)
    try:
        from services.summary_l2_writer import resolve_l2_slot_safe
        slot = resolve_l2_slot_safe()
    except Exception:      # pragma: no cover - защитная ветка
        slot = None
    if cap_tokens == -1 or cap_tokens is not None \
            or not (auto.auto_budget_enabled()
                    and capacity.capacity_resolver_enabled()) \
            or slot is None:
        # Legacy/manual-cap → прежняя единая точка (static hybrid).
        from services.summary_fact_package import resolve_fact_package_budget
        kind, effective = resolve_fact_package_budget()
        mode = (BUDGET_MODE_LEGACY_STATIC if cap_tokens is None or cap_tokens == -1
                else BUDGET_MODE_MANUAL_CAP)
        return kind, effective, mode
    try:
        from services.summary_prompts import SUMMARY_L2_WRITER_SYSTEM_PROMPT
        system_text = SUMMARY_L2_WRITER_SYSTEM_PROMPT
    except Exception:      # pragma: no cover - защитная ветка
        system_text = ""
    try:
        result = await auto.resolve_stage_budget(
            "summary.l2", base_url=slot.base_url, model=slot.model,
            mandatory_tokens=_count_tokens_safe(system_text))
        return "tokens", result.effective_input_budget, BUDGET_MODE_AUTO
    except Exception:
        from services.summary_fact_package import resolve_fact_package_budget
        kind, effective = resolve_fact_package_budget()
        return kind, effective, BUDGET_MODE_LEGACY_STATIC


__all__ = [
    "BUDGET_MODE_AUTO", "BUDGET_MODE_MANUAL_CAP", "BUDGET_MODE_LEGACY_STATIC",
    "hybrid_manual_cap_tokens", "resolve_l1_effective_budget",
    "resolve_l2_effective_budget", "resolve_l2_package_budget",
]
