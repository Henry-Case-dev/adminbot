"""QND-NONDET §3 (owner corrective 2026-11-10) — вероятность публикации.

Заменяет «двойной гейт» (LLM почти всегда SILENT → QRNG только для редких
уже одобренных) на ОДНО вероятностное решение:

  * факторы считает сервер из фактических данных (релевантность, значимость,
    активность беседы, свежесть, качество памяти, недавние инициативы);
  * `S = Σ w_i f_i / Σ w_i`, `p = p_min + (p_max-p_min)*logistic((S-θ)/τ)`;
  * ОДИН draw `RandomSourceService` (`purpose="<механизм>_publication"`);
  * публикуем тогда и только тогда, когда значение действительно < p.

Порядок заморожен контрактом (§3 «Ordering is frozen»):
  ДО draw  — жёсткие лимиты, права/ACL, дневные капы, min_gap/антифлуд,
             лимит темы, дедуп, бюджет оценок, `publication_coordination.
             precheck` и сама семантическая оценка (молчание без
             `veto_reason` → `silence_cause=semantic_none`, БЕЗ draw);
  ПОСЛЕ    — бронь публикации, Writer, SendRecheck (только свежесть), отправка.

Этот модуль НЕ решает «уместно ли содержание» (это вердикт модели), НЕ
отправляет сообщения и НЕ вводит второй гейт: после `decide()` вернувшего
публикацию, никто не пере-решает уместность и не делает повторный draw.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

from services.semantic_schedule import (
    MECH_INITIATIVE,
    MECH_NOSTALGIA,
    MECHANISMS,
    TRIGGER_SCHEDULE,
    _emit,
    _num,
    EVENT_PUBLICATION,
    EVENT_RESULT,
)

logger = logging.getLogger(__name__)

# ── причины молчания (§3: фиксированный набор `silence_cause`) ─────────────
SILENCE_SEMANTIC_NONE = "semantic_none"
SILENCE_LIMITS = "limits"
SILENCE_DEDUP = "dedup"
SILENCE_SEND_RECHECK = "send_recheck"
SILENCE_RANDOM_MISS = "random_miss"
SILENCE_RANDOM_UNAVAILABLE = "random_unavailable"
SILENCE_MODULE_OFF = "module_off"

SILENCE_CAUSES: tuple[str, ...] = (
    SILENCE_SEMANTIC_NONE, SILENCE_LIMITS, SILENCE_DEDUP,
    SILENCE_SEND_RECHECK, SILENCE_RANDOM_MISS, SILENCE_RANDOM_UNAVAILABLE,
    SILENCE_MODULE_OFF,
)

# ── исходы решения (§5 `quantum_publication_decision.outcome`) ─────────────
OUTCOME_DELIVERED = "delivered"
OUTCOME_SILENT = "silent"
OUTCOME_BLOCKED_RANDOM = "blocked_random_unavailable"

# ── допустимые `veto_reason` семантического отказа (§3) ────────────────────
VETO_REASONS: frozenset[str] = frozenset({
    "no_substance", "not_appropriate", "unsafe", "direct_request",
    "addressed_elsewhere",
})

# ── факторы: имена §3 и их веса (`limits.qnd_w_*`) ─────────────────────────
FACTOR_KEYS: tuple[str, ...] = ("r", "s", "a", "t", "q", "n")
WEIGHT_PARAMS: dict[str, str] = {
    "r": "limits.qnd_w_relevance",
    "s": "limits.qnd_w_significance",
    "a": "limits.qnd_w_activity",
    "t": "limits.qnd_w_freshness",
    "q": "limits.qnd_w_memory",
    "n": "limits.qnd_w_recent",
}
DEFAULT_WEIGHTS: dict[str, float] = {
    "r": 1.0, "s": 0.8, "a": 0.6, "t": 0.5, "q": 0.7, "n": 0.4,
}

# ── прочие параметры модели (`limits.qnd_*`, редактируются в админке) ──────
DEFAULT_THETA = 0.50
DEFAULT_TAU = 0.18
DEFAULT_MEMORY_REFERENCE = 0.60
#: Горизонт свежести (`limits.qnd_freshness_horizon_seconds`) — код-дефолт.
_FRESHNESS_DEFAULT = 86400.0
DEFAULT_PUBLICATION_MIN: dict[str, float] = {
    MECH_NOSTALGIA: 0.05, MECH_INITIATIVE: 0.05,
}
DEFAULT_PUBLICATION_MAX: dict[str, float] = {
    MECH_NOSTALGIA: 0.85, MECH_INITIATIVE: 0.75,
}
#: Явные ключи границ вероятности по механизмам (см. CADENCE_PARAMS).
PUBLICATION_PARAMS: dict[str, tuple[str, str]] = {
    MECH_NOSTALGIA: ("limits.qnd_nostalgia_publication_min",
                     "limits.qnd_nostalgia_publication_max"),
    MECH_INITIATIVE: ("limits.qnd_initiative_publication_min",
                      "limits.qnd_initiative_publication_max"),
}

#: Per-chat `initiative.trigger_probability` — compat-мэппинг в `p_max`
#: (`migration_class=deprecated_compat`): дефолт 1.0 больше НЕ гейт.
KEY_TRIGGER_PROBABILITY = "initiative.trigger_probability"

#: Результаты публикации (§5 `quantum_publication_result.outcome`).
#: ВАЖНО (B3): `dedup` — ТОЛЬКО реальная дедупликация. Любое иное молчание
#: получает свой код, иначе витрина показывает выдуманную причину.
RESULT_DELIVERED = "delivered"
RESULT_DEDUP = "dedup"
RESULT_SEND_RECHECK = "send_recheck"
RESULT_CAP = "cap"
#: Семантический отказ модели/решения (содержательного повода нет).
RESULT_SEMANTIC_SILENT = "semantic_silent"
#: Смысловой слой недоступен (L1 не ответил / план не построен).
RESULT_SEMANTIC_UNAVAILABLE = "semantic_unavailable"
#: Решение было не «текст» (react/tool в текстовом контексте) — молчание.
RESULT_NOT_TEXT = "not_text"
#: Реакция выполнена (участие без текста).
RESULT_REACTED = "reacted"
#: Молчание с нераспознанной причиной — честный «прочее», а не `dedup`.
RESULT_SILENT_OTHER = "silent_other"

#: Причины, которые ДЕЙСТВИТЕЛЬНО означают дедупликацию.
DEDUP_REASONS = frozenset({
    "dedup", "context_duplicate", "direct_update_dedup_hit",
    "already_answered", "already_sent", "duplicate",
})
UNKNOWN_REASONS = frozenset({"", "silent", "unknown", "error"})


def publication_result_outcome(reason_code: str, *,
                               action: str = "",
                               decision_reason: str = "") -> str:
    """Код исхода для `quantum_publication_result` (B3).

    Маппинг ЯВНЫЙ и узкий: `dedup` отдаётся только реальным дедупликациям.
    Семантические отказы, недоступность смыслового слоя, «не текст» и реакция
    имеют собственные коды — иначе durable-витрина показывала бы выдуманную
    причину молчания (владелец это прямо запретил).
    """
    reason = str(reason_code or "").strip().lower()
    act = str(action or "").strip().lower()
    decided = str(decision_reason or "").strip().lower()
    if act == "react" or reason == "l1_react" or "react" in reason:
        return RESULT_REACTED
    if "recheck" in reason:
        return RESULT_SEND_RECHECK
    if reason in DEDUP_REASONS or decided in DEDUP_REASONS:
        return RESULT_DEDUP
    if reason == "delivery_not_text" or "not_text" in reason:
        return RESULT_NOT_TEXT
    if reason in ("l1_unavailable", "planner_outage") \
            or "unavailable" in reason:
        return RESULT_SEMANTIC_UNAVAILABLE
    if "cap" == reason or reason.startswith("cap_"):
        return RESULT_CAP
    if reason in ("l1_silent", "no_substance", "not_appropriate",
                  "addressed_elsewhere", "wrong_moment", "recent_reply",
                  "semantic_none"):
        return RESULT_SEMANTIC_SILENT
    if reason in UNKNOWN_REASONS:
        return RESULT_SEMANTIC_SILENT
    return RESULT_SILENT_OTHER


@dataclass
class PublicationDecision:
    """Возврат `decide()` — одна правда о вероятностном решении."""

    publish: bool = False
    probability: float = 0.0
    value: float | None = None
    source: str = ""
    provider: str | None = None
    draw_id: str | None = None
    fallback_reason: str | None = None
    policy_version: str = ""
    factors: dict = field(default_factory=dict)
    weights: dict = field(default_factory=dict)
    score: float = 0.0
    mechanism: str = ""
    chat_id: int | None = None
    trigger: str = TRIGGER_SCHEDULE
    candidate_ref: str = ""
    outcome: str = OUTCOME_SILENT
    silence_cause: str | None = None
    deferred: bool = False

    def as_dict(self) -> dict:
        return {
            "publish": bool(self.publish),
            "probability": self.probability,
            "value": self.value,
            "source": self.source,
            "provider": self.provider,
            "draw_id": self.draw_id,
            "fallback_reason": self.fallback_reason,
            "policy_version": self.policy_version,
            "factors": dict(self.factors or {}),
            "S": self.score,
            "mechanism": self.mechanism,
            "chat_id": self.chat_id,
            "trigger": self.trigger,
            "candidate_ref": self.candidate_ref,
            "outcome": self.outcome,
            "silence_cause": self.silence_cause,
            "deferred": bool(self.deferred),
        }


# ── детерминированные факторы (без случайности) ────────────────────────────

def clamp01(value) -> float | None:
    """Клампим фактор в [0,1]; `None` — данных нет (фактор выпадает)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(0.0, min(1.0, number))


def activity_factor(rate_mps, target_mps) -> float | None:
    """`a = min(1, rate / limits.qnd_activity_target_mps)`."""
    rate = clamp01(rate_mps)
    try:
        target = float(target_mps or 0.0)
    except (TypeError, ValueError):
        target = 0.0
    if rate is None or target <= 0:
        return None
    return max(0.0, min(1.0, float(rate_mps) / target))


def freshness_factor(age_seconds, horizon_seconds) -> float | None:
    """`t = 1 - min(1, age / limits.qnd_freshness_horizon_seconds)`."""
    try:
        horizon = float(horizon_seconds or 0.0)
        age = max(0.0, float(age_seconds or 0.0))
    except (TypeError, ValueError):
        return None
    if horizon <= 0:
        return None
    return max(0.0, 1.0 - min(1.0, age / horizon))


def memory_quality_factor(score, reference) -> float | None:
    """`q = top retrieval score / limits.qnd_memory_quality_reference`."""
    value = clamp01(score)
    try:
        ref = float(reference or 0.0)
    except (TypeError, ValueError):
        ref = 0.0
    if value is None or ref <= 0:
        return None
    return max(0.0, min(1.0, float(score) / ref))


def recent_factor(sent_in_window, max_per_day) -> float | None:
    """`n = min(1, sent / max(1, max_replies_per_day))`."""
    try:
        sent = max(0.0, float(sent_in_window or 0.0))
        cap = float(max_per_day or 0.0)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, sent / max(1.0, cap)))


async def activity_factor_for(db, chat_id, *, now: int | None = None):
    """`a` из фактического темпа чата (тот же источник, что у расписания)."""
    stamp = int(now if now is not None else time.time())
    try:
        from services import initiative_observer as observer
        rate = float(await observer.recent_message_rate(
            db, int(chat_id), now=stamp) or 0.0)
    except Exception:
        return None
    target = await _num(chat_id, "limits.qnd_activity_target_mps", 0.02,
                        minimum=1e-6)
    return activity_factor(rate, target)


# ── сборка вероятности ─────────────────────────────────────────────────────

async def resolve_settings(chat_id) -> dict:
    """Веса/порог/крутизна/p_min/p_max — только `limits.qnd_*`."""
    weights = {}
    for key, param in WEIGHT_PARAMS.items():
        weights[key] = await _num(chat_id, param, DEFAULT_WEIGHTS[key],
                                  minimum=0.0)
    theta = await _num(chat_id, "limits.qnd_publication_theta",
                       DEFAULT_THETA)
    tau = await _num(chat_id, "limits.qnd_publication_tau", DEFAULT_TAU,
                     minimum=0.01)
    reference = await _num(chat_id, "limits.qnd_memory_quality_reference",
                           DEFAULT_MEMORY_REFERENCE, minimum=1e-6)
    return {"weights": weights, "theta": theta, "tau": tau,
            "memory_reference": reference}


async def publication_bounds(chat_id, mechanism: str) -> tuple[float, float]:
    """`(p_min, p_max)` механизма; явный per-chat override → `p_max`."""
    min_key, max_key = PUBLICATION_PARAMS[mechanism]
    p_min = await _num(chat_id, min_key,
                       DEFAULT_PUBLICATION_MIN[mechanism], minimum=0.0)
    p_max = await _num(chat_id, max_key,
                       DEFAULT_PUBLICATION_MAX[mechanism], minimum=0.0)
    p_min = min(1.0, p_min)
    p_max = min(1.0, max(p_min, p_max))
    override = await _explicit_trigger_probability(chat_id)
    if override is not None:
        p_max = min(1.0, max(p_min, float(override)))
    return p_min, p_max


async def _explicit_trigger_probability(chat_id) -> float | None:
    """Явный (чатовый) `initiative.trigger_probability` как `p_max`.

    Заводской 1.0 больше не гейт: учитывается ТОЛЬКО пользовательский выбор
    (`source == "chat"`). Ошибка резолва → None (поведение по модели §3).
    """
    try:
        from services import chat_params
        value, source = await chat_params.get_chat_param_sourced(
            int(chat_id), KEY_TRIGGER_PROBABILITY, None)
    except Exception:
        return None
    if source != "chat" or value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def weighted_score(factors: dict, weights: dict) -> tuple[float, dict]:
    """`S = Σ w f / Σ w`; отсутствующий фактор выпадает вместе со своим весом."""
    used_factors: dict = {}
    total = 0.0
    weight_sum = 0.0
    for key in FACTOR_KEYS:
        value = clamp01((factors or {}).get(key))
        if value is None:
            continue
        weight = max(0.0, float(weights.get(key) or 0.0))
        used_factors[key] = value
        total += weight * value
        weight_sum += weight
    if weight_sum <= 0:
        return 0.0, used_factors
    return total / weight_sum, used_factors


def probability(score: float, *, p_min: float, p_max: float,
                theta: float, tau: float) -> float:
    """`p = p_min + (p_max-p_min)*logistic((S-θ)/τ)`, зажатая в `[0,1]`."""
    try:
        x = (float(score) - float(theta)) / max(0.01, float(tau))
    except (TypeError, ValueError):
        return float(p_min)
    if x >= 60:
        logistic = 1.0
    elif x <= -60:
        logistic = 0.0
    else:
        logistic = 1.0 / (1.0 + math.exp(-x))
    value = float(p_min) + (float(p_max) - float(p_min)) * logistic
    return max(0.0, min(1.0, value))


def _source(db, source):
    """Единственный контур случайности (или DI-источник теста)."""
    if source is not None:
        return source
    from services.semantic_schedule import _default_source
    return _default_source(db)


async def decide(db, *, mechanism: str, chat_id, factors: dict,
                 candidate_ref: str = "", source=None,
                 trigger: str = TRIGGER_SCHEDULE,
                 now: int | None = None,
                 budget_left: int | None = None) -> PublicationDecision:
    """ОДНО вероятностное решение публикации (§3).

    Возвращает `PublicationDecision`; `publish=True` — окончательное решение
    (никакой последующий компонент не пере-решает уместность и не делает
    второй draw). `publish=False` содержит `silence_cause` и фактический
    источник значения.
    """
    stamp = int(now if now is not None else time.time())
    settings = await resolve_settings(chat_id)
    weights = settings["weights"]
    p_min, p_max = await publication_bounds(chat_id, mechanism)
    score, used = weighted_score(factors, weights)
    p = probability(score, p_min=p_min, p_max=p_max,
                    theta=settings["theta"], tau=settings["tau"])
    decision = PublicationDecision(
        probability=p, factors=dict(factors or {}),
        weights=dict(weights), score=score, mechanism=str(mechanism),
        chat_id=int(chat_id), trigger=str(trigger or ""),
        candidate_ref=str(candidate_ref or ""),
    )
    _emit(
        "quantum_evaluation", mechanism=mechanism, chat_id=chat_id,
        payload={
            "mechanism": str(mechanism), "chat_id": int(chat_id),
            "trigger": str(trigger or ""),
            "candidate_ref": str(candidate_ref or ""),
            "factors": {k: round(float(v), 6) for k, v in used.items()},
            "S": round(float(score), 6),
            "budget_left": (None if budget_left is None
                            else int(budget_left)),
        },
        outcome="success")

    src = _source(db, source)
    result = None
    if src is not None:
        try:
            result = await src.draw_probability(
                chat_id=int(chat_id),
                purpose=f"{mechanism}_publication", probability=p)
        except Exception:
            logger.warning("[qnd] publication draw failed | chat=%s mech=%s",
                           chat_id, mechanism, exc_info=True)
            result = None
    value = getattr(result, "value", None)
    deferred = (result is None
                or bool(getattr(result, "deferred", False))
                or value is None)
    decision.source = str(getattr(result, "source", "") or "")
    decision.provider = getattr(result, "provider", None)
    decision.draw_id = getattr(result, "draw_id", None)
    decision.fallback_reason = getattr(result, "fallback_reason", None)
    decision.policy_version = str(
        getattr(result, "policy_version", "") or "")
    if deferred:
        decision.publish = False
        decision.deferred = True
        decision.outcome = OUTCOME_BLOCKED_RANDOM
        decision.silence_cause = SILENCE_RANDOM_UNAVAILABLE
        decision.source = decision.source or "unavailable"
        if not decision.fallback_reason:
            decision.fallback_reason = str(
                getattr(result, "reason", "") or "provider_unavailable")
    else:
        try:
            u = float(value)
        except (TypeError, ValueError):
            u = 1.0
        decision.value = u
        decision.publish = bool(u < p)
        decision.outcome = (OUTCOME_DELIVERED if decision.publish
                            else OUTCOME_SILENT)
        decision.silence_cause = (None if decision.publish
                                  else SILENCE_RANDOM_MISS)

    _emit(
        EVENT_PUBLICATION, mechanism=mechanism, chat_id=chat_id,
        payload={
            "mechanism": str(mechanism), "chat_id": int(chat_id),
            "trigger": str(trigger or ""),
            "candidate_ref": str(candidate_ref or ""),
            "factors": {k: round(float(v), 6) for k, v in used.items()},
            "S": round(float(score), 6),
            "p": round(float(p), 6),
            "u": (None if decision.value is None
                  else round(float(decision.value), 9)),
            "hit": int(bool(decision.publish)),
            "outcome": decision.outcome,
            "silence_cause": decision.silence_cause,
            "source": decision.source,
            "provider": decision.provider,
            "draw_id": decision.draw_id,
            "fallback_reason": decision.fallback_reason,
            "policy_version": decision.policy_version,
        },
        outcome=("success" if decision.publish else "silent"),
        reason_code=("random_miss" if decision.silence_cause
                     == SILENCE_RANDOM_MISS else None))
    return decision


def record_result(mechanism: str, chat_id, *, outcome: str,
                  reason_code: str = "", latency_ms: int | None = None,
                  trigger: str = TRIGGER_SCHEDULE) -> None:
    """Durable-событие `quantum_publication_result` (§5)."""
    _emit(
        EVENT_RESULT, mechanism=mechanism, chat_id=chat_id,
        payload={
            "mechanism": str(mechanism), "chat_id": int(chat_id),
            "trigger": str(trigger or ""),
            "outcome": str(outcome or ""),
            "reason_code": str(reason_code or ""),
            "latency_ms": (None if latency_ms is None else int(latency_ms)),
        },
        outcome="success")
