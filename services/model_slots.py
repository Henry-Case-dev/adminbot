"""ASAP-3.1 (round 1028, ADR-1028-3 D5, spec Q10/раздел 5) — Model Slots
registry: backend отдаёт готовую структуру активных text-model slots
(§18/§25 shape). Frontend НЕ вычисляет slots по хардкод-списку моделей (§13).

Состав первого релиза — spec Q10 (binding):
  * ``direct.primary``  — ``models.llm_base_url`` + ``models.llm_model_name``;
  * ``direct.fallback`` — fallback-пара Direct (если настроена; иначе слот
    не показывается);
  * ``summary.l1`` / ``summary.l2`` — слоты §82 (наследование от primary
    показывается компактной строкой, не дубликат);
  * ``summary.legacy``  — глобальная основная пара, ТОЛЬКО когда активен
    Legacy fallback контур (``flags.summary_legacy_fallback_enabled``);
  * ``intel.background`` — глобальная основная пара (dream/ностальгия/
    анти-клише worker-генерация), одной строкой;
  * ``intel.reflection`` — пара ``generate_worker('reflection')``, если
    отличима от основной.
  * decision/react выполняются моделью ``direct.primary`` — отдельный слот
    НЕ создаётся; image/STT/embeddings — вне text-context matrix (§13).

Один model id может быть в нескольких slots с разными auto budgets (§13).
Никогда не бросает (fail-open): ошибка одного слота → слот пропускается с
warning-полем; R17 — наружу только числа/enum/имена моделей (без ключей).
"""
from __future__ import annotations

import logging

from config.settings import settings
from services import hot_config as hot
from services import auto_budget as auto
from services import model_capacity as capacity

logger = logging.getLogger(__name__)


def _hot(key: str, default="") -> str:
    try:
        return str(hot.get(key, default) or "").strip()
    except Exception:      # pragma: no cover - защитная ветка
        return str(default or "").strip()


def _policy_mode_of(raw) -> str:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return "dynamic"
    if value < 0:
        return "unlimited"
    if value == 0:
        return "dynamic"
    return "cap"


async def _direct_policy_mode(chat_id: int | None) -> str:
    """Context Policy стадии Direct (per-chat → hot → default; −1/0/>0)."""
    try:
        from services.chat_params import get_chat_param
        raw = await get_chat_param(
            chat_id, "limits.chat_context_budget_tokens",
            hot.get("limits.chat_context_budget_tokens",
                    settings.CHAT_CONTEXT_BUDGET_TOKENS))
        return _policy_mode_of(raw)
    except Exception:      # pragma: no cover - защитная ветка
        return _policy_mode_of(getattr(settings,
                                       "CHAT_CONTEXT_BUDGET_TOKENS", 0))


def _observed(slot: str) -> dict:
    try:
        return auto.slot_observations_snapshot(slot)
    except Exception:      # pragma: no cover - защитная ветка
        return {}


def _summary_coverage() -> dict | None:
    try:
        from services.summary_l1_clusterizer import last_run_coverage
        return last_run_coverage()
    except Exception:      # pragma: no cover - защитная ветка
        return None


async def collect_slots(*, chat_id: int | None = None) -> dict:
    """Собрать активные слоты (§25 shape): ``{generated_at, chat_id,
    policy_mode, slots: [...]}``. Никогда не бросает; capacity fallback
    виден в каждом слоте (warning + source)."""
    import time
    primary_base = _hot("models.llm_base_url", getattr(settings,
                                                       "LLM_BASE_URL", ""))
    primary_model = _hot("models.llm_model_name",
                         getattr(settings, "LLM_MODEL_NAME", ""))
    fb_base = _hot("models.llm_fallback_base_url")
    fb_model = _hot("models.llm_fallback_model")
    policy_mode = await _direct_policy_mode(chat_id)
    slots: list[dict] = []
    warnings: list[str] = []

    async def _slot_entry(slot: str, label: str, base_url: str, model: str,
                          *, inherited_from: str | None = None,
                          policy: str | None = None,
                          note: str | None = None) -> None:
        try:
            budget = await auto.resolve_stage_budget(
                slot, base_url=base_url, model=model, mandatory_tokens=0)
            slots.append({
                "slot": slot,
                "label": label,
                "provider": capacity.detect_provider_class(base_url),
                "model": model,
                "inherited_from": inherited_from,
                "note": note,
                "capacity": {
                    "declared": budget.context_window,
                    "runtime": None,
                    "effective": budget.context_window,
                    "source": budget.source,
                    "fallback_used": budget.source
                    == capacity.SOURCE_FALLBACK,
                },
                "budget": {
                    "mandatory_tokens": 0,
                    "output_reserve": budget.output_reserve,
                    "safety_reserve": budget.safety_reserve,
                    "auto_input_budget": budget.auto_input_budget,
                    "manual_cap": budget.manual_cap,
                    "effective_input_budget":
                        budget.effective_input_budget,
                },
                "policy_mode": policy or "auto",
                "coverage_policy": (auto.stage_policy(slot).coverage_policy
                                    if auto.stage_policy(slot) else None),
                "overflow_strategy": (
                    auto.stage_policy(slot).overflow_strategy
                    if auto.stage_policy(slot) else None),
                "observed": _observed(slot),
            })
            if budget.source == capacity.SOURCE_FALLBACK:
                warnings.append(
                    "capacity_fallback:%s" % slot)
        except Exception as exc:      # fail-open: слот с ошибкой не рушит всё
            logger.warning("model_slots: slot %s failed — skipped | %s",
                           slot, type(exc).__name__)
            warnings.append("slot_error:%s" % slot)

    # 1. Direct primary (+ policy Direct).
    if primary_model:
        await _slot_entry("direct.primary", "Прямые ответы", primary_base,
                          primary_model, policy=policy_mode)
    # 2. Direct fallback — слот только если пара настроена (§19).
    if fb_model:
        await _slot_entry("direct.fallback",
                          "Прямые ответы (резервная модель)",
                          fb_base or primary_base, fb_model,
                          policy=policy_mode)
    # 3/4. Summary L1/L2 — наследование компактной строкой (§14/§19).
    try:
        from services.summary_l1_clusterizer import resolve_l1_slot
        l1 = resolve_l1_slot()
        inherited_l1 = None if l1.dedicated else "direct.primary"
        await _slot_entry("summary.l1", "Саммари: кластеризатор (L1)",
                          l1.base_url, l1.model,
                          inherited_from=inherited_l1)
    except Exception as exc:      # pragma: no cover
        warnings.append("slot_error:summary.l1")
        logger.warning("model_slots: summary.l1 failed | %s",
                       type(exc).__name__)
    try:
        from services.summary_l2_writer import resolve_l2_slot_safe
        l2 = resolve_l2_slot_safe()
        inherited_l2 = None if l2.dedicated else "direct.primary"
        await _slot_entry("summary.l2", "Саммари: писатель статьи (L2)",
                          l2.base_url, l2.model,
                          inherited_from=inherited_l2)
    except Exception as exc:      # pragma: no cover
        warnings.append("slot_error:summary.l2")
        logger.warning("model_slots: summary.l2 failed | %s",
                       type(exc).__name__)
    # 5. summary.legacy — ТОЛЬКО когда активен Legacy fallback контур.
    try:
        legacy_on = bool(hot.get(
            "flags.summary_legacy_fallback_enabled",
            getattr(settings, "SUMMARY_LEGACY_FALLBACK_ENABLED", True)))
    except Exception:      # pragma: no cover
        legacy_on = False
    if legacy_on and primary_model:
        await _slot_entry("summary.legacy", "Саммари: Legacy-контур",
                          primary_base, primary_model,
                          inherited_from="direct.primary")
    # 6. intel.background — глобальная основная пара, одной строкой.
    if primary_model:
        await _slot_entry("intel.background",
                          "Фоновая память (dream/ностальгия/анти-клише)",
                          primary_base, primary_model,
                          inherited_from="direct.primary")
    # 7. intel.reflection — только если пара отличима (§19).
    try:
        slug = "intel_reflection"
        r_base = _hot(f"models.{slug}_base_url")
        r_model = _hot(f"models.{slug}_model_name")
        if r_model and (r_model != primary_model
                        or (r_base and r_base != primary_base)):
            await _slot_entry("intel.reflection", "Рефлексия (self-reflection)",
                              r_base or primary_base, r_model)
    except Exception:      # pragma: no cover - защитная ветка
        pass

    coverage = _summary_coverage()
    return {
        "generated_at": time.time(),
        "chat_id": chat_id,
        "policy_mode": policy_mode,
        "slots": slots,
        "warnings": warnings,
        "summary_coverage": coverage,
        "capacity_metrics": capacity.capacity_metrics_snapshot(),
        "react_metrics": _react_metrics(),
    }


def _react_metrics() -> dict:
    try:
        from services.direct_llm_react import react_metrics_snapshot
        return react_metrics_snapshot()
    except Exception:      # pragma: no cover - защитная ветка
        return {}


__all__ = ["collect_slots"]
