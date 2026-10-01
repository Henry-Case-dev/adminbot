"""MCA-22 (round 10.27, ADR-1028-6 D6/D9) — GraphRAG provenance enforcement
и correction/revalidation над СУЩЕСТВУЮЩЕЙ provenance-схемой (второй
статусный контур запрещён, Q11/D9).

C5 (§9 ТЗ):
* person-affecting edges (`user→user`/`user→topic`/relation/state) требуют
  при записи source assertion + SourceRef/EvidenceLink + speaker + subject
  + revision (+temporal где применимо);
* bare edge НЕ поднимается в confident (weight-cap + честный reason);
* legacy edges (`subject_ref_id IS NULL`) — НЕ удаляются, маркируются
  `legacy/unverified`, retrieval — weak hint (`provenance_backed=False`);
  повтор одного пересказа ≠ независимое подтверждение
  (`provenance.evidence_independent_count`);
* `supports/contradicts/supersedes` видны downstream (conflict-статусы).

C8 (§12/§22/§23 ТЗ):
* correction path: фразы-триггеры → `contradicts`-EvidenceLink
  (verification='tentative') + `conflict_status='conflicting'`;
  revalidation — существующий `reconstruct_fact_provenance` → `resolved`
  либо остаётся `conflicting`; disputed = проекция `conflicting`
  (новых enum-значений НЕ вводится);
* conflict arbitration (§22): source-backed > derived memory; old bot
  output не решает спор о факте мира;
* read policy (§23): disputed/conflicting факт не подаётся как confident
  personalization; old bot outputs — не personal facts.

Kill-switches: `MCA_CANONICAL_ATTRIBUTION_ENABLED` (мастер C5-веток),
`MCA_CORRECTION_REVALIDATION_ENABLED` (correction path; инертен при
мастере OFF). Уважаются `MCA_PROVENANCE_ENABLED`/`MCA_FACT_ATTRIBUTION_
ENABLED`.
"""
from __future__ import annotations

import dataclasses
import logging
import time

from services import mca_gates

logger = logging.getLogger(__name__)

# Уровни confidence bare-edge (§9: bare edge не становится уверенным
# персональным знанием).
EDGE_CONFIDENT = "confident"
EDGE_TENTATIVE = "tentative"
EDGE_LEGACY_UNVERIFIED = "legacy_unverified"

# Weight-cap для bare/person-affecting edges без полного provenance.
_BARE_EDGE_WEIGHT_CAP = 0.55


def canonical_attribution_enabled() -> bool:
    try:
        return mca_gates.canonical_attribution_enabled()
    except Exception:                                     # pragma: no cover
        return True


def correction_revalidation_enabled() -> bool:
    try:
        return mca_gates.correction_revalidation_enabled()
    except Exception:                                     # pragma: no cover
        return True


@dataclasses.dataclass(frozen=True)
class PersonEdgeVerdict:
    """Результат валидатора записи person-affecting edge (§9)."""

    allowed: bool
    confidence: str                  # confident|tentative|legacy_unverified
    weight_cap: float | None         # None = без ограничения
    reason_code: str | None          # диагностический код (mca-13 словарь)
    requires_source_assertion: bool


def validate_person_edge_write(
        *, speaker_entity_id: int | None, subject_entity_id: int | None,
        source_ref_id: int | None = None, revision: int | None = None,
        event_time: int | None = None,
        is_person_affecting: bool = True) -> PersonEdgeVerdict:
    """Валидатор записи person-affecting edge (§9; D6).

    Правило: edge, затрагивающий персону, требует source assertion
    (SourceRef/EvidenceLink) + speaker + subject + revision (+temporal
    где применимо). Bare edge разрешён к записи как legacy/unverified
    с weight-cap — НЕ как confident персональное знание. Удаление/скрытие
    данных не выполняется (legacy — маркировка, не зачистка).
    Gate canonical OFF → разрешено всё с baseline-семантикой (паритет)."""
    if not canonical_attribution_enabled() or not is_person_affecting:
        return PersonEdgeVerdict(
            allowed=True, confidence=EDGE_CONFIDENT, weight_cap=None,
            reason_code=None, requires_source_assertion=False)
    provenance_complete = (speaker_entity_id is not None
                           and subject_entity_id is not None
                           and source_ref_id is not None
                           and revision is not None)
    if provenance_complete:
        return PersonEdgeVerdict(
            allowed=True, confidence=EDGE_CONFIDENT, weight_cap=None,
            reason_code=None, requires_source_assertion=True)
    # Bare edge: запись не блокируется, но confidence ограничен.
    reason = ("subject_unresolved_skipped"
              if subject_entity_id is None
              else "insufficient_evidence")
    return PersonEdgeVerdict(
        allowed=True, confidence=EDGE_LEGACY_UNVERIFIED,
        weight_cap=_BARE_EDGE_WEIGHT_CAP, reason_code=reason,
        requires_source_assertion=True)


def classify_fact_provenance(fact_row) -> str:
    """Классификация факта/edge для retrieval/read-policy (§9/§23).

    `provenance_backed` — есть subject_ref_id + speaker;
    `legacy_unverified` — иначе (не удалять, weak hint)."""
    try:
        subject_ref = fact_row.get("subject_ref_id")
        speaker = fact_row.get("speaker_author_id")
        if subject_ref not in (None, "") and speaker not in (None, ""):
            return EDGE_CONFIDENT
        if subject_ref not in (None, ""):
            return EDGE_TENTATIVE
        return EDGE_LEGACY_UNVERIFIED
    except Exception:                                     # pragma: no cover
        return EDGE_LEGACY_UNVERIFIED


def independent_roots_count(links: list[dict]) -> int:
    """Unique evidence roots (REUSE `provenance.evidence_independent_count`):
    повтор одного пересказа НЕ считается независимым подтверждением."""
    try:
        from services.provenance import evidence_independent_count
        return int(evidence_independent_count(links or []))
    except Exception:                                     # pragma: no cover
        return 0


# ── C8: correction/revalidation ─────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class CorrectionPlan:
    """План correction path (D9): что связать и какие статусы выставить."""

    triggered: bool
    trigger_text: str | None
    target_fact_ids: tuple[int, ...]
    evidence_link_type: str = "contradicts"
    verification: str = "tentative"
    conflict_status: str = "conflicting"
    reason_code: str | None = None


def plan_correction(*, message_text: str | None,
                    target_fact_ids: tuple[int, ...] = (),
                    now: int | None = None) -> CorrectionPlan:
    """Детерминированный план коррекции по фразам-триггерам (§12).

    User correction — СИЛЬНЫЙ СИГНАЛ на revalidation, НЕ абсолютная истина:
    создаётся contradicting-evidence (contradicts + tentative + conflicting),
    пере-проверка source решает исход (`resolved` либо остаётся
    `conflicting`). «Исправлено» НЕ пишется, если есть только противоречащее
    утверждение. Gate OFF → план не срабатывает (обычный диалог — паритет)."""
    if not correction_revalidation_enabled():
        return CorrectionPlan(triggered=False, trigger_text=None,
                              target_fact_ids=tuple(target_fact_ids))
    try:
        from services.claim_envelope import (
            is_correction_phrase, is_deny_phrase,
        )
    except Exception:                                     # pragma: no cover
        return CorrectionPlan(triggered=False, trigger_text=None,
                              target_fact_ids=tuple(target_fact_ids))
    text = str(message_text or "")
    triggered = is_correction_phrase(text) or is_deny_phrase(text)
    if not triggered:
        return CorrectionPlan(triggered=False, trigger_text=None,
                              target_fact_ids=tuple(target_fact_ids))
    return CorrectionPlan(
        triggered=True, trigger_text=text[:160] if text else None,
        target_fact_ids=tuple(int(f) for f in target_fact_ids),
        evidence_link_type="contradicts", verification="tentative",
        conflict_status="conflicting",
        reason_code="correction_revalidation_queued")


def read_policy_rank(fact_row) -> int:
    """Read policy (§23): ранга достоверности для персонализации.

    3 = verified/current + provenance; 2 = attributed tentative
    (подаётся только маркированно); 1 = disputed/conflicting
    (НЕ confident персонализация); 0 = legacy/unverified (weak hint).
    Old bot outputs в персонализацию не попадают (вызывающий фильтрует
    origin ∈ BOT_ORIGINS)."""
    cls = classify_fact_provenance(fact_row)
    try:
        from services.provenance import is_self_referential_origin
        if is_self_referential_origin(fact_row.get("origin")):
            return 0                    # бот сам про себя — не персонализация
    except Exception:                                     # pragma: no cover
        pass
    if cls == EDGE_CONFIDENT:
        status = str(fact_row.get("status") or "")
        return 3 if status == "confirmed" else 2
    if cls == EDGE_TENTATIVE:
        return 2
    return 1 if str(fact_row.get("conflict_status") or "") == "conflicting" \
        else 0
