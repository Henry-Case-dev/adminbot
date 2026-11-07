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


# ── MEMORY-03 (C-2): класс происхождения основания ребра (§2.2/§2.3) ───────

# Значения = `memory_contracts.OriginClass` (единый словарь, без дубля).
ORIGIN_EXPLICIT_DIRECT = "explicit_direct"
ORIGIN_REPORTED_THIRD_PARTY = "reported_third_party"
ORIGIN_QUOTE_FORWARD = "quote_forward"
ORIGIN_DERIVED_WITH_LINEAGE = "derived_with_lineage"
ORIGIN_COOCCURRENCE = "cooccurrence"
ORIGIN_LEGACY_UNKNOWN = "legacy_unknown"

# Методы прямой ссылки (§2.3: `supports` с basis) — это `explicit_direct`.
_DIRECT_REFERENCE_METHODS = frozenset({
    "direct_reference", "reply_context", "thread_context",
})
# Каналы с явной цепочкой (§2.2): `derived_with_lineage`, не догадка.
_LINEAGE_CHANNELS = frozenset({"dream", "dossier_layer_a", "dossier_layer_b"})
_SUPPORTING_LINK_TYPES = frozenset({"derived_from", "supports"})
# Собственные выводы бота (§2.2/R-3): производное, не подтверждение.
_BOT_ORIGINS = frozenset({"bot_self_reply", "bot_direct_reply"})


def classify_origin_class(*, entity_type: str | None, source_row,
                          link_type: str = "", method: str = "unknown",
                          verification: str = "unknown",
                          basis: str | None = None) -> str:
    """Класс происхождения по §2.2 (сигналы строки) и §2.3 (семантика связи).

    Только выводимое из существующих полей; нет сигнала → `legacy_unknown`
    («Происхождение не установлено»), без догадок по тексту/эмодзи/длине.

    Колонки per-table (§2.2): `smart_messages.forward_source` — display-строка,
    `graph_facts.forward_from` — provenance факта. Перекрёстного чтения нет.

    **`graph_fact` классифицируется ТОЛЬКО по своей строке.** Семантика
    evidence-связи (`link_type`/`method`/`verification`) не может «выдать»
    факту класс `explicit_direct`: атрибуция факта живёт в его колонках, и
    правило «verified support ⇒ подтверждение» относится к источнику-сообщению,
    а не к факту (иначе факт без атрибуции или пересказ становились бы
    независимым корнем — F1).
    """
    row = source_row if isinstance(source_row, dict) else {}
    is_fact = entity_type == "graph_fact"

    # (1) quote/forward — репост не приписывается переславшему (R-9).
    if entity_type == "message":
        if bool(row.get("is_forward")) or str(row.get("forward_source") or "").strip():
            return ORIGIN_QUOTE_FORWARD
    elif is_fact:
        if (str(row.get("forward_from") or "").strip()
                or str(row.get("perspective") or "") == "quoted"):
            return ORIGIN_QUOTE_FORWARD
    # (2) пересказ третьего лица. `perspective='other'` — утверждение о другом
    # человеке, а не речь автора (§2.2, F1).
    if (str(row.get("perspective") or "") in ("other", "third_party")
            or str(row.get("attribution_method") or "") == "third_party"):
        return ORIGIN_REPORTED_THIRD_PARTY
    # (3) прямое утверждение автора: `perspective='self'` — единственный
    # строковый сигнал, которого достаточно без внешней сверки. Случай
    # `perspective IS NULL` требует подтверждения авторства сохранённым
    # сообщением и решается вызывающим, у которого есть БД
    # (`relation_evidence._fact_origin_class`); сам классификатор без БД
    # консервативен и не выдаёт `explicit_direct` по одному `attribution_method`.
    if (str(row.get("perspective") or "") == "self"
            and str(row.get("attribution_method") or "")
            in ("self_report", "direct_evidence")):
        return ORIGIN_EXPLICIT_DIRECT
    # (4) производное с явной цепочкой: собственный вывод бота (R-3),
    # world_knowledge (утверждение о мире, не о человеке — не подтверждение
    # авторства), каналы dream/dossier.
    if (str(row.get("origin") or "") in _BOT_ORIGINS
            or str(row.get("attribution_method") or "") == "world_knowledge"
            or str(row.get("provenance_channel") or "") in _LINEAGE_CHANNELS
            or str(row.get("origin") or "") == "derived_belief"):
        return ORIGIN_DERIVED_WITH_LINEAGE
    if is_fact:
        # Атрибуции нет — честный `legacy_unknown`; link-семантика факту класс
        # не назначает (F1).
        return ORIGIN_LEGACY_UNKNOWN
    # (5) соседство в реплике ≠ утверждение (§2.3, R-11).
    if link_type == "mentions":
        return ORIGIN_COOCCURRENCE
    # (5b) явная семантика репоста/цитаты в самой связи (§2.3 basis).
    if link_type == "derived_from" and str(basis or "") in ("forward", "quote"):
        return ORIGIN_QUOTE_FORWARD
    # (6) прямая ссылка на сохранённое сообщение (verified + basis).
    if (link_type in _SUPPORTING_LINK_TYPES
            and str(method or "") in _DIRECT_REFERENCE_METHODS
            and verification == "verified"):
        return ORIGIN_EXPLICIT_DIRECT
    # (6b) проверенное подтверждение без противоречащих сигналов строки —
    # утверждение источника (иначе источник, который УЖЕ считается независимым
    # корнем, получил бы `legacy_unknown` и «исчез» бы из карточки, разойдясь
    # со счётчиком). `legacy_unknown` по §2.2 — ребро без evidence-связи.
    if link_type in _SUPPORTING_LINK_TYPES and verification == "verified":
        return ORIGIN_EXPLICIT_DIRECT
    # (7) `derived_from` с явными method/basis (lineage обязателен).
    if link_type == "derived_from" and str(method or "") not in ("", "unknown"):
        return ORIGIN_DERIVED_WITH_LINEAGE
    return ORIGIN_LEGACY_UNKNOWN


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
