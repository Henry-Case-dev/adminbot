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
    # ER-08 (02.11.2026): L1-планировщик — своя стадия, чтобы его бюджет
    # выводился из РЕАЛЬНОГО окна L1-модели, а не копился из код-константы.
    # Арифметика та же, что у Direct (safety reserve один раз).
    "direct.l1": StagePolicy(
        "direct.l1", "Direct: L1-планировщик (компактный контекст)",
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


# ═══════════════════════════════════════════════════════════════════════════
# ASAP-EVIDENCE-ROUTING-01 v3 (§3 Retrieve, §4.4 Preserve): окно read-only
# tool-вызова вместо 4000/8000 как «потолка качества».
#
# Три источника лимита в порядке приоритета (первый непустой побеждает):
#   1. per-call бюджет композера (`ToolContext.evidence_budget_chars`) —
#      уже net-of-output-reserve, поэтому output reserve здесь НЕ вычитается
#      повторно (C4: один резерв, один раз, в композере);
#   2. входной бюджет стадии в токенах (`BudgetResult.effective_input_budget`)
#      → символы × доли окна;
#   3. реальное окно модели (`model_capacity.resolve_evidence_window_tokens`)
#      → тот же расчёт; `window_source=unknown_fallback` честно помечается.
# 4000 (поиск) и 8000 (статья) остаются ТОЛЬКО legacy-дефолтом для вызовов
# без бюджета при выключенном kill-switch и как нижний пол поиска.
# ═══════════════════════════════════════════════════════════════════════════

#: Нижняя граница полезности поисковой выдачи: индекс кандидатов (несколько
#: URL со сниппетами) обязан помещаться даже на самом маленьком окне.
SEARCH_RESULT_SOFT_FLOOR = 4000

#: Технический предел ОДНОГО tool-результата (класс C: защита от лавины).
#: Hot-ключ `limits.tool_result_hard_ceiling_chars`. Это не «качество».
TOOL_RESULT_HARD_CEILING_DEFAULT = 200_000

#: Класс C: сколько символов документа вообще извлекает reader перед
#: секционным отбором. Hot `limits.article_extract_ceiling_chars`.
ARTICLE_EXTRACT_CEILING_DEFAULT = 120_000

#: Запас над per-call бюджетом evidence: индекс кандидатов/контекст вокруг
#: выдержки полезно видеть целиком (контракт §4.3: `budget × 1.25`).
EVIDENCE_TOOL_BUDGET_GROW = 1.25

#: Legacy-дефолты вызовов без бюджета (прежнее поведение, класс E снят с
#: роли потолка: используются только при динамике OFF / отсутствии окна).
LEGACY_SEARCH_MAX_SYMBOLS = 4000
LEGACY_ARTICLE_MAX_SYMBOLS = 8000

#: Доля окна модели, которую СУММАРНО могут занять tool-результаты одного хода
#: (hot `limits.evidence_tool_turn_share`, дефолт ниже). Защита от лавины:
#: 4 раунда × 2 вызова не должны вытеснить system/reply/OCR из окна.
TOOL_EVIDENCE_TURN_SHARE_DEFAULT = 0.40


def _hot_int(key: str, default: int, *, minimum: int = 1) -> int:
    """Целое из hot-каталога с дефолтом (мусор → дефолт; никогда не бросает)."""
    try:
        value = int(hot.get(key, default))
    except Exception:      # pragma: no cover - защитная ветка
        return int(default)
    return value if value >= minimum else int(default)


@dataclass(frozen=True)
class EvidenceToolWindow:
    """Лимит одного tool-результата + его наблюдаемый источник (§8 «Контракт
    замера»: effective_limit/source/why доступны без реконструкции)."""

    kind: str                  # "search" | "article"
    effective_limit: int        # символов можно доставить
    source: str                 # call_budget | window | legacy
    budget_chars: int = 0       # бюджет evidence (симв.), от которого считали
    window_tokens: int = 0
    window_source: str = ""     # источник окна (model_capacity)
    hard_ceiling: int = 0
    floor: int = 0
    turn_capped: bool = False   # лимит урезан остатком хода (защита от лавины)
    turn_remaining_chars: int = 0

    @property
    def capacity_source(self) -> str:
        """Источник ёмкости для событий: window|legacy (+ window_source)."""
        if self.source == "legacy":
            return "legacy"
        return "window"

    def as_event_fields(self) -> dict:
        return {
            "tool_kind": self.kind,
            "effective_limit": self.effective_limit,
            "source": self.source,
            "budget_chars": self.budget_chars,
            "window_tokens": self.window_tokens,
            "window_source": self.window_source,
            "capacity_source": self.capacity_source,
        }


def _kind_defaults(kind: str) -> tuple[int, int]:
    """``(floor, legacy_limit)`` для вида результата."""
    if str(kind or "") == "search":
        return SEARCH_RESULT_SOFT_FLOOR, LEGACY_SEARCH_MAX_SYMBOLS
    return 0, LEGACY_ARTICLE_MAX_SYMBOLS


def _turn_share() -> float:
    """Доля окна на суммарные tool-результаты хода (hot-ключ, мусор → дефолт)."""
    try:
        value = float(hot.get("limits.evidence_tool_turn_share",
                              TOOL_EVIDENCE_TURN_SHARE_DEFAULT))
    except Exception:      # pragma: no cover - защитная ветка
        return TOOL_EVIDENCE_TURN_SHARE_DEFAULT
    if value <= 0.0 or value > 1.0:
        return TOOL_EVIDENCE_TURN_SHARE_DEFAULT
    return value


def resolve_evidence_tool_window(
        kind: str, *, call_budget_chars: int | None = None,
        input_budget_tokens: int | None = None,
        model: str | None = None,
        hard_ceiling: int | None = None,
        turn_spent_chars: int = 0) -> EvidenceToolWindow:
    """Лимит одного tool-вызова (search/article). Никогда не бросает.

    ``output_reserve_tokens`` здесь отсутствует НАМЕРЕННО (C4): резерв вывода
    вычитается один раз в композере, per-call бюджет приходит уже чистым.

    ``turn_spent_chars`` — сколько evidence уже доставлено инструментами в
    этом ходе: суммарная доля окна ограничена (``TOOL_EVIDENCE_TURN_SHARE``),
    иначе 4 раунда по 2 вызова вытеснили бы system/reply/OCR из окна."""
    floor, legacy = _kind_defaults(kind)
    ceiling = int(hard_ceiling) if hard_ceiling else _hot_int(
        "limits.tool_result_hard_ceiling_chars",
        TOOL_RESULT_HARD_CEILING_DEFAULT)
    ceiling = max(1, ceiling)
    if not capacity.evidence_window_dynamic_enabled():
        return EvidenceToolWindow(
            kind=str(kind or ""), effective_limit=min(legacy, ceiling),
            source="legacy", hard_ceiling=ceiling, floor=floor)
    window_tokens, window_source = capacity.resolve_evidence_window_tokens(
        model)
    window_chars = capacity.chars_for_tokens(window_tokens)
    try:
        spent = max(0, int(turn_spent_chars or 0))
    except (TypeError, ValueError):
        spent = 0
    turn_budget = int(window_chars * _turn_share())
    turn_remaining = (max(0, turn_budget - spent) if turn_budget > 0 else None)
    # 1) per-call бюджет композера (уже без output reserve).
    try:
        budget = int(call_budget_chars or 0)
    except (TypeError, ValueError):
        budget = 0
    if budget > 0:
        limit = int(budget * EVIDENCE_TOOL_BUDGET_GROW)
        limited = min(limit, ceiling)
        capped = turn_remaining is not None and limited > turn_remaining
        if capped:
            limited = max(floor, turn_remaining)
        return EvidenceToolWindow(
            kind=str(kind or ""), effective_limit=max(floor, min(limited,
                                                                ceiling)),
            source="call_budget", budget_chars=budget,
            window_tokens=window_tokens, window_source=window_source,
            hard_ceiling=ceiling, floor=floor, turn_capped=capped,
            turn_remaining_chars=int(turn_remaining or 0))
    # 2) входной бюджет стадии (токены) — уже net-of-reserve.
    try:
        tokens = int(input_budget_tokens or 0)
    except (TypeError, ValueError):
        tokens = 0
    budget_chars = (capacity.chars_for_tokens(tokens) if tokens > 0
                    else window_chars)
    if budget_chars <= 0:
        return EvidenceToolWindow(
            kind=str(kind or ""), effective_limit=min(legacy, ceiling),
            source="legacy", window_tokens=window_tokens,
            window_source=window_source, hard_ceiling=ceiling, floor=floor)
    derived = capacity.evidence_window_for_tokens(
        budget_chars // max(1, capacity.CHARS_PER_TOKEN_ESTIMATE),
        floor=floor, ceiling=ceiling)
    limited = max(floor, min(int(derived), ceiling))
    capped = turn_remaining is not None and limited > turn_remaining
    if capped:
        limited = max(floor, turn_remaining)
    return EvidenceToolWindow(
        kind=str(kind or ""), effective_limit=max(floor, min(limited, ceiling)),
        source="window", budget_chars=budget_chars,
        window_tokens=window_tokens, window_source=window_source,
        hard_ceiling=ceiling, floor=floor, turn_capped=capped,
        turn_remaining_chars=int(turn_remaining or 0))


def article_extract_ceiling() -> tuple[int, str]:
    """Класс C: сколько символов документа извлекает reader до отбора секции.

    ``(ceiling, source)``; hot `limits.article_extract_ceiling_chars` →
    ``source="hot"``, иначе заводской дефолт → ``source="default"``."""
    try:
        raw = hot.get("limits.article_extract_ceiling_chars", None)
    except Exception:      # pragma: no cover - защитная ветка
        raw = None
    try:
        value = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        value = 0
    if value > 0:
        return value, "hot"
    return ARTICLE_EXTRACT_CEILING_DEFAULT, "default"



__all__ = [
    "OUTPUT_RESERVE_FLOOR", "COVERAGE_EXHAUSTIVE",
    "COVERAGE_RELEVANCE_COMPOSED", "OVERFLOW_CHUNK_ALL",
    "OVERFLOW_HIERARCHICAL_REDUCE", "OVERFLOW_PRIORITY_REDUCE",
    "StagePolicy", "STAGE_POLICIES", "BudgetResult", "stage_policy",
    "auto_budget_enabled", "resolve_stage_budget", "record_slot_observation",
    "record_slot_pressure", "slot_observations_snapshot",
    # ASAP-EVIDENCE-ROUTING-01 v3 (§3/§4.3): окно read-only tool-вызова.
    "SEARCH_RESULT_SOFT_FLOOR", "TOOL_RESULT_HARD_CEILING_DEFAULT",
    "ARTICLE_EXTRACT_CEILING_DEFAULT", "EVIDENCE_TOOL_BUDGET_GROW",
    "TOOL_EVIDENCE_TURN_SHARE_DEFAULT",
    "EvidenceToolWindow", "resolve_evidence_tool_window",
    "article_extract_ceiling",
]
