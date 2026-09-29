"""ASAP-3.1 (round 1028, ADR-1028-3 D2, spec раздел 4) — Stage Auto Budget
Resolver: единая точка расчёта входного бюджета LLM-стадии поверх Model
Capacity Resolver (§9–§12, §133).

Формула (safety reserve применяется РОВНО ОДИН раз — инвариант инцидента
39371→27826, ADR-1028-2):

    direct.*   : available = safe_budget(window − mandatory − output_reserve)
    summary.*  : available = safe_budget(window) − mandatory − output_reserve

    auto_input_budget = available
    effective_input_budget = policy(available, manual_cap/policy_raw)

Output reserve stage-aware (§11): 1) фактический ``max_tokens`` стадии;
2) stage-policy (Summary L1/L2 — существующие env `SUMMARY_L1/L2_OUTPUT_
RESERVE_TOKENS` 4000/6000 объявляются дефолтами policy; Direct — прежний
ratio-слой `max(1024, window×ratio)`); 3) floor 1024.

Stage policy metadata (§133) живёт здесь (не в разбросанных ``if summary``):
``summary.l1 → exhaustive/chunk_all``; ``summary.l2 → exhaustive/
hierarchical_reduce``; ``direct.primary → relevance_composed/priority_
reduce``; ``direct.fallback → как primary с recompose``.

Kill-switch `AUTO_BUDGET_RESOLVER_ENABLED` (env-only, default ON; резолв
per-call): OFF → потребители идут прежними per-stage путями байт-в-байт
(Direct D2; Summary static hybrid 30000-путь). Никогда не бросает (R3);
R17: наружу только числа/enum — raw текст не логируется.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

from config.settings import settings
from services import hot_config as hot
from services import model_capacity as capacity
from services.token_counter import safe_budget

logger = logging.getLogger(__name__)

OUTPUT_RESERVE_FLOOR = 1024

# ── Stage policy metadata (§133) ───────────────────────────────────────────
COVERAGE_EXHAUSTIVE = "exhaustive"
COVERAGE_RELEVANCE_COMPOSED = "relevance_composed"
OVERFLOW_CHUNK_ALL = "chunk_all"
OVERFLOW_HIERARCHICAL_REDUCE = "hierarchical_reduce"
OVERFLOW_PRIORITY_REDUCE = "priority_reduce"


@dataclass(frozen=True)
class StagePolicy:
    """Метаданные стадии (Q10/§133): назначение, coverage/overflow policy,
    человекочитаемый label, источник output reserve."""

    slot: str
    label: str
    coverage_policy: str
    overflow_strategy: str
    output_reserve_env: str | None   # имя Settings-поля stage-policy резерва
    arithmetic: str                  # "direct" | "summary" (порядок safety)


STAGE_POLICIES: dict[str, StagePolicy] = {
    "direct.primary": StagePolicy(
        "direct.primary", "Прямые ответы", COVERAGE_RELEVANCE_COMPOSED,
        OVERFLOW_PRIORITY_REDUCE, None, "direct"),
    "direct.fallback": StagePolicy(
        "direct.fallback", "Прямые ответы (резервная модель)",
        COVERAGE_RELEVANCE_COMPOSED, OVERFLOW_PRIORITY_REDUCE, None,
        "direct"),
    "summary.l1": StagePolicy(
        "summary.l1", "Саммари: кластеризатор (L1)", COVERAGE_EXHAUSTIVE,
        OVERFLOW_CHUNK_ALL, "SUMMARY_L1_OUTPUT_RESERVE_TOKENS", "summary"),
    "summary.l2": StagePolicy(
        "summary.l2", "Саммари: писатель статьи (L2)", COVERAGE_EXHAUSTIVE,
        OVERFLOW_HIERARCHICAL_REDUCE, "SUMMARY_L2_OUTPUT_RESERVE_TOKENS",
        "summary"),
    "summary.legacy": StagePolicy(
        "summary.legacy", "Саммари: Legacy-контур", COVERAGE_EXHAUSTIVE,
        OVERFLOW_CHUNK_ALL, None, "summary"),
    "intel.background": StagePolicy(
        "intel.background", "Фоновая память (dream/ностальгия/анти-клише)",
        COVERAGE_RELEVANCE_COMPOSED, OVERFLOW_PRIORITY_REDUCE, None,
        "direct"),
    "intel.reflection": StagePolicy(
        "intel.reflection", "Рефлексия (self-reflection)",
        COVERAGE_RELEVANCE_COMPOSED, OVERFLOW_PRIORITY_REDUCE, None,
        "direct"),
}


def stage_policy(slot: str) -> StagePolicy | None:
    return STAGE_POLICIES.get(str(slot or ""))


def auto_budget_enabled() -> bool:
    """Kill-switch `AUTO_BUDGET_RESOLVER_ENABLED` (env-only, default ON;
    резолв per-call; никогда не бросает). OFF → прежние per-stage бюджеты."""
    try:
        return bool(getattr(settings, "AUTO_BUDGET_RESOLVER_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _stage_output_reserve(policy: StagePolicy, window: int,
                          max_output_tokens: int | None) -> int:
    """§11: 1) фактический max_tokens; 2) stage-policy (Summary L1 4000 /
    L2 6000; Direct — ratio-слой D2); 3) floor 1024."""
    try:
        if max_output_tokens is not None and int(max_output_tokens) > 0:
            return max(OUTPUT_RESERVE_FLOOR, int(max_output_tokens))
    except (TypeError, ValueError):
        pass
    if policy.output_reserve_env:
        try:
            value = int(getattr(settings, policy.output_reserve_env, 0))
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    if policy.arithmetic == "direct":
        return capacity.output_reserve_tokens(window)
    return OUTPUT_RESERVE_FLOOR


@dataclass(frozen=True)
class BudgetResult:
    """Структура §9: полный breakdown бюджета стадии (числа ТЗ — пример
    структуры, не defaults)."""

    stage: str
    model: str
    context_window: int
    mandatory_tokens: int
    output_reserve: int
    safety_reserve: int
    auto_input_budget: int
    policy_mode: str          # unlimited|dynamic|cap|auto
    manual_cap: int | None
    effective_input_budget: int
    source: str               # capacity source (developer_override|runtime|…)

    def as_event_fields(self) -> dict:
        return {
            "slot": self.stage, "context_window": self.context_window,
            "mandatory_tokens": self.mandatory_tokens,
            "output_reserve": self.output_reserve,
            "safety_reserve": self.safety_reserve,
            "effective_input_budget": self.effective_input_budget,
            "policy_mode": self.policy_mode,
        }


async def resolve_stage_budget(
        stage: str, *, base_url: str, model: str,
        mandatory_tokens: int = 0, max_output_tokens: int | None = None,
        manual_cap: int | None = None, policy_raw=None,
        dynamic_default: int | None = None,
        marker_overhead: int = 0) -> BudgetResult:
    """Единый расчёт бюджета стадии (§9/§10). Никогда не бросает.

    ``policy_raw`` — per-chat/raw policy-значение стадии (Direct: −1/0/>0 из
    `limits.chat_context_budget_tokens`; Summary: manual cap >0 = размер
    ОДНОГО L1-запроса, §137). ``marker_overhead`` — Δ маркеров chunk-границ
    (Summary, вычитается после safety — паритет прежнего порядка Q5).
    """
    policy = STAGE_POLICIES.get(str(stage or ""))
    if policy is None:
        policy = StagePolicy(str(stage or "unknown"), str(stage or "unknown"),
                             COVERAGE_RELEVANCE_COMPOSED,
                             OVERFLOW_PRIORITY_REDUCE, None, "direct")
    try:
        mandatory = max(0, int(mandatory_tokens or 0))
    except (TypeError, ValueError):
        mandatory = 0
    try:
        markers = max(0, int(marker_overhead or 0))
    except (TypeError, ValueError):
        markers = 0

    window, source = await capacity.resolve_stage_window(
        base_url, model, slot=policy.slot)
    window = max(0, int(window or 0))
    reserve = _stage_output_reserve(policy, window, max_output_tokens)

    # ── Safety reserve РОВНО ОДИН раз (единая точка `safe_budget`) ─────────
    if policy.arithmetic == "direct":
        base = max(1, window - mandatory - reserve)
        available = max(1, safe_budget(base))
        safety = max(0, base - available)
    else:
        base = safe_budget(window)
        safety = max(0, window - base)
        available = max(1, base - mandatory - reserve - markers)
    auto_budget = available

    # ── Policy-слой (−1/0/>0; manual cap = размер одного запроса, §137) ────
    cap_value: int | None = None
    try:
        if manual_cap is not None and int(manual_cap) > 0:
            cap_value = int(manual_cap)
    except (TypeError, ValueError):
        cap_value = None
    raw_value: int | None = None
    try:
        raw_value = None if policy_raw is None else int(policy_raw)
    except (TypeError, ValueError):
        raw_value = None

    if raw_value is not None and raw_value < 0:
        effective, mode = auto_budget, "unlimited"
    elif cap_value is not None:
        effective, mode = min(auto_budget, cap_value), "cap"
    elif cap_value is None and raw_value is not None and raw_value > 0:
        effective, mode = min(auto_budget, raw_value), "cap"
        cap_value = raw_value
    elif policy.arithmetic == "direct":
        # §35 (T-4063): Dynamic 16000 — OPERATIONAL SOFT TARGET, не hard
        # scissors: если P0/P1/релевантный материал превышает target, но
        # помещается в physical window — он НЕ режется ради target. Поэтому
        # effective = полный physical auto-бюджет; таргет остаётся рабочим
        # ориентиром стадии (middle top-K/селекция), не потолком аллокации.
        # OFF (kill-switch) → прежний hard-cap путь потребителя (паритет).
        effective, mode = auto_budget, "dynamic"
    else:
        effective, mode = auto_budget, "auto"

    result = BudgetResult(
        stage=policy.slot, model=str(model or ""), context_window=window,
        mandatory_tokens=mandatory, output_reserve=reserve,
        safety_reserve=safety, auto_input_budget=auto_budget,
        policy_mode=mode, manual_cap=cap_value,
        effective_input_budget=max(1, int(effective)), source=source)
    # Наблюдаемость §49 (fail-open; R17 — только числа/enum).
    try:
        from services.agentic_events import AUTO_CONTEXT_BUDGET, \
            emit_agentic_event
        emit_agentic_event(AUTO_CONTEXT_BUDGET,
                           **result.as_event_fields(), model=model[:64] or "-",
                           source=source)
    except Exception:
        pass
    return result


# ── Наблюдаемость использования слотов (§50, process-local, без raw) ───────
# p50/p95/last/max input tokens per slot + pressure/overflow счётчики.
# ПЕРВОЙ системы usage не дублирует: это read-side витрина над числами
# существующих событий/диагностики (§24/§50: второй usage store запрещён).
_OBS_WINDOW = 512
_slot_observations: dict[str, deque] = {}
_slot_pressure: dict[str, int] = {}
_slot_overflow: dict[str, int] = {}


def record_slot_observation(slot: str, input_tokens: int) -> None:
    """Записать фактический/оценочный input токены стадии (после запроса —
    provider-reported actual приоритетнее estimate, §12)."""
    key = str(slot or "")
    if not key:
        return
    try:
        value = max(0, int(input_tokens))
    except (TypeError, ValueError):
        return
    bucket = _slot_observations.setdefault(
        key, deque(maxlen=_OBS_WINDOW))
    bucket.append(value)


def record_slot_pressure(slot: str, *, physical_overflow: bool = False) -> None:
    key = str(slot or "")
    if not key:
        return
    _slot_pressure[key] = _slot_pressure.get(key, 0) + 1
    if physical_overflow:
        _slot_overflow[key] = _slot_overflow.get(key, 0) + 1


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1,
                max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def slot_observations_snapshot(slot: str) -> dict:
    """``{last, p50, p95, max, count, pressure_events,
    physical_overflow_events}`` для слота (§25 observed)."""
    key = str(slot or "")
    values = list(_slot_observations.get(key) or [])
    return {
        "last": values[-1] if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": max(values) if values else None,
        "count": len(values),
        "pressure_events": int(_slot_pressure.get(key, 0)),
        "physical_overflow_events": int(_slot_overflow.get(key, 0)),
    }


__all__ = [
    "OUTPUT_RESERVE_FLOOR", "COVERAGE_EXHAUSTIVE",
    "COVERAGE_RELEVANCE_COMPOSED", "OVERFLOW_CHUNK_ALL",
    "OVERFLOW_HIERARCHICAL_REDUCE", "OVERFLOW_PRIORITY_REDUCE",
    "StagePolicy", "STAGE_POLICIES", "BudgetResult", "stage_policy",
    "auto_budget_enabled", "resolve_stage_budget", "record_slot_observation",
    "record_slot_pressure", "slot_observations_snapshot",
]
