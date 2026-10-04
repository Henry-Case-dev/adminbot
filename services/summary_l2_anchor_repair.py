"""ASAP 4.2 D1 (AM-1; spec §1, R8-C/R8-D) — L2 evidence repair +
structured Reviewer verdict + targeted Writer revision (AnchorSpace).

Проблема (BL-3): один невалидный evidence-ref убивает весь L2 document
(``document=None`` → Legacy). Решение: evidence нормализуется/чистится
локально, абзац ОСТАЁТСЯ; абзац без evidence после repair — сигнал Reviewer,
НЕ уничтожение документа. ``document=None`` только при неремонтируемой
структуре.

Reviewer возвращает структурированный verdict (R8-D-001):
``paragraph_id``, ``reason`` из фиксированного набора, ``source_anchors[]``,
``repair_instruction``. Writer на revision получает ТОЛЬКО проблемный
paragraph + нужные source excerpts + проблему (bounded; R8-D-002).

Kill-switches (env-only; OFF = прежний контур 2.58.47):
``SUMMARY_L2_EVIDENCE_REPAIR_ENABLED``, ``SUMMARY_L2_TARGETED_REVISION_ENABLED``.

Модуль **чистый** (0 LLM/0 БД/0 сети/0 системных часов), детерминирован,
вход не мутируется. R17: наружу только коды/числа/anchors (внутренние).
"""
from __future__ import annotations

import copy
import dataclasses
import enum
import logging

from services.summary_source_anchors import (
    SourceAnchorMap,
    l2_evidence_repair_enabled,
    l2_targeted_revision_enabled,
)

logger = logging.getLogger(__name__)


# ── Reviewer reason-коды (owner §24124 enum; R17-safe) ─────────────────────

class ReviewReason(str, enum.Enum):
    WRONG_SPEAKER = "wrong_speaker"
    BAD_QUOTE = "bad_quote"
    BAD_NUMBER_DATE = "bad_number_date"
    UNSUPPORTED = "unsupported"
    LOST_REPLY = "lost_reply"
    NO_EVIDENCE = "no_evidence"
    MIXED_PEOPLE = "mixed_people"


REVIEW_REASONS = frozenset(reason.value for reason in ReviewReason)

# Соответствие owner-кодам существующих Reviewer findings (summary_l2_review)
# — совместимость без второго канона.
REASON_TO_FINDING_CODE: dict = {
    ReviewReason.WRONG_SPEAKER.value: "wrong_person_attribution",
    ReviewReason.BAD_QUOTE.value: "quote_speaker_mismatch",
    ReviewReason.BAD_NUMBER_DATE.value: "unsupported_number",
    ReviewReason.UNSUPPORTED.value: "unsupported_claim",
    ReviewReason.LOST_REPLY.value: "reply_attribution_error",
    ReviewReason.NO_EVIDENCE.value: "unsupported_claim",
    ReviewReason.MIXED_PEOPLE.value: "wrong_person_attribution",
}

STATUS_APPROVED = "approved"
STATUS_NEEDS_FIXES = "needs_fixes"
STATUS_UNUSABLE = "unusable"
REVIEW_STATUSES = frozenset({STATUS_APPROVED, STATUS_NEEDS_FIXES,
                             STATUS_UNUSABLE})


# ── Evidence repair (R8-C-001) ─────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class EvidenceRepairReport:
    """R17-safe счётчики L2 evidence repair (AM-5/D6)."""

    paragraphs_count: int = 0
    evidence_refs_total: int = 0
    invalid_refs_repaired: int = 0
    paragraphs_without_evidence: int = 0
    document_kept: bool = False

    def as_log_fields(self) -> dict:
        return dataclasses.asdict(self)


def _evidence_report(*, kept: bool, paragraphs: int = 0, refs: int = 0,
                     invalid: int = 0, no_evidence: int = 0
                     ) -> EvidenceRepairReport:
    return EvidenceRepairReport(
        paragraphs_count=paragraphs, evidence_refs_total=refs,
        invalid_refs_repaired=invalid,
        paragraphs_without_evidence=no_evidence, document_kept=kept)


def repair_l2_evidence(document, anchor_map: SourceAnchorMap
                       ) -> tuple[dict | None, EvidenceRepairReport]:
    """Починить evidence-anchors документа (R8-C-001).

    ``normalize → remove invalid → paragraph remains``. Абзац без evidence
    после repair СОХРАНЯЕТСЯ (reviewer signal), документ не убивается.
    ``None`` — только неремонтируемая структура (не-dict, ``paragraphs`` не
    список, пустой список, не-dict абзац). Вход НЕ мутируется."""
    if not isinstance(document, dict):
        return None, _evidence_report(kept=False)
    paragraphs = document.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        return None, _evidence_report(kept=False)

    repaired = copy.deepcopy(document)
    out: list = []
    refs_total = 0
    invalid = 0
    no_evidence = 0
    for para in paragraphs:
        if not isinstance(para, dict):
            return None, _evidence_report(kept=False)
        raw = para.get("source_anchors")
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            return None, _evidence_report(kept=False)
        anchors: list = []
        for token in raw:
            check = anchor_map.validate(token) if anchor_map is not None \
                else None
            if check is None or not check.ok:
                invalid += 1
                continue
            if check.anchor not in anchors:
                anchors.append(check.anchor)
        item = dict(para)
        item["source_anchors"] = anchors
        # legacy numeric refs в anchor-space не носитель — снимаем.
        item.pop("evidence_message_ids", None)
        refs_total += len(anchors)
        if not anchors:
            no_evidence += 1
        out.append(item)
    repaired["paragraphs"] = out
    return repaired, _evidence_report(kept=True, paragraphs=len(out),
                                      refs=refs_total, invalid=invalid,
                                      no_evidence=no_evidence)


def paragraphs_without_evidence(document) -> list:
    """Индексы абзацев без evidence — reviewer signal (не kill)."""
    result: list = []
    if not isinstance(document, dict):
        return result
    for index, para in enumerate(document.get("paragraphs") or []):
        if not isinstance(para, dict):
            continue
        anchors = para.get("source_anchors")
        if not anchors:
            result.append(index)
    return result


# ── Structured Reviewer verdict (R8-D-001) ─────────────────────────────────

@dataclasses.dataclass(frozen=True)
class ReviewIssue:
    """Валидированная находка Reviewer (AnchorSpace)."""

    paragraph_id: int
    reason: str
    source_anchors: tuple
    repair_instruction: str

    @property
    def finding_code(self) -> str:
        return REASON_TO_FINDING_CODE.get(self.reason, "unsupported_claim")


@dataclasses.dataclass(frozen=True)
class ReviewResult:
    """Структурированный вердикт Reviewer (R8-D-001; enum reason-кодов)."""

    status: str
    issues: tuple
    dropped_invalid: int = 0

    @property
    def blocking(self) -> int:
        return len(self.issues)

    @property
    def by_paragraph(self) -> dict:
        out: dict = {}
        for issue in self.issues:
            out.setdefault(issue.paragraph_id, []).append(issue)
        return out


def validate_review_result(data, anchor_map: SourceAnchorMap, *,
                           paragraph_count: int | None = None) -> ReviewResult:
    """Разобрать/валидировать структурированный вердикт Reviewer (R8-D-001).

    Находки без refs / с выдуманными anchors отбрасываются (unknown >
    hallucinated): ``source_anchors`` фильтруются против ``anchor_map``;
    если не осталось ни одного валидного anchor → issue dropped. Невалидный
    reason → dropped. Не бросает."""
    if not isinstance(data, dict):
        return ReviewResult(status=STATUS_UNUSABLE, issues=(),
                            dropped_invalid=0)
    status = str(data.get("status") or "").strip().lower()
    if status not in REVIEW_STATUSES:
        status = STATUS_UNUSABLE
    dropped = 0
    issues: list = []
    raw_issues = data.get("issues")
    if isinstance(raw_issues, list):
        for item in raw_issues:
            if not isinstance(item, dict):
                dropped += 1
                continue
            reason = str(item.get("reason") or "").strip().lower()
            if reason not in REVIEW_REASONS:
                dropped += 1
                continue
            pid = item.get("paragraph_id")
            if isinstance(pid, bool) or not isinstance(pid, int):
                dropped += 1
                continue
            if paragraph_count is not None and paragraph_count > 0 \
                    and (pid < 0 or pid >= paragraph_count):
                dropped += 1
                continue
            anchors: list = []
            for token in item.get("source_anchors") or []:
                check = anchor_map.validate(token) if anchor_map is not None \
                    else None
                if check is None or not check.ok:
                    continue
                if check.anchor not in anchors:
                    anchors.append(check.anchor)
            if not anchors:
                dropped += 1
                continue
            instruction = str(item.get("repair_instruction")
                              or item.get("instruction") or "").strip()
            issues.append(ReviewIssue(
                paragraph_id=pid, reason=reason,
                source_anchors=tuple(anchors),
                repair_instruction=instruction[:500]))
    if status == STATUS_NEEDS_FIXES and not issues:
        status = STATUS_APPROVED
    return ReviewResult(status=status, issues=tuple(issues),
                        dropped_invalid=dropped)


# ── Targeted Writer revision (R8-D-002) ────────────────────────────────────

def build_targeted_revision_content(*, paragraph, paragraph_id: int,
                                    issue: ReviewIssue,
                                    source_excerpts, title: str = ""
                                    ) -> str:
    """User-контент targeted revision: ТОЛЬКО проблемный paragraph + нужные
    source excerpts + проблема (bounded; whole-article regen не вызывается).

    ``source_excerpts`` — real source excerpts нужных anchors (R8-D-002/003)."""
    import json
    payload = {
        "revision_scope": "single_paragraph",
        "paragraph_id": int(paragraph_id),
        "problem": {
            "reason": issue.reason,
            "source_anchors": list(issue.source_anchors),
            "repair_instruction": issue.repair_instruction,
        },
        "paragraph": paragraph,
        "source_excerpts": list(source_excerpts or []),
        "preserve": ("Исправь ТОЛЬКО этот абзац. Сохрани остальные абзацы "
                     "неизменно. Не добавляй новых фактов, имён, чисел или "
                     "цитат; опирайся на source_excerpts."),
        # T-4877: output schema пиннится явно (иначе любая другая форма
        # ответа сгорает как revision_invalid_patch и обе revision → Legacy).
        "output_format": (
            'Верни СТРОГО JSON одного объекта: {"text": "полный '
            'исправленный текст абзаца", "source_anchors": ["m0000-A1"]}. '
            "source_anchors — массив anchors ТОЛЬКО из source_excerpts/"
            "problem (без реальных message_id). Не оборачивай в "
            "paragraph/replace_paragraphs, не возвращай другие абзацы."),
    }
    if title:
        payload["article_title"] = str(title)
    return ("ВЕРНИ ИСПРАВЛЕННЫЙ АБЗАЦ (компактный JSON):\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


__all__ = [
    "ReviewReason", "REVIEW_REASONS", "REASON_TO_FINDING_CODE",
    "STATUS_APPROVED", "STATUS_NEEDS_FIXES", "STATUS_UNUSABLE",
    "REVIEW_STATUSES", "EvidenceRepairReport", "repair_l2_evidence",
    "paragraphs_without_evidence", "ReviewIssue", "ReviewResult",
    "validate_review_result", "build_targeted_revision_content",
    "l2_evidence_repair_enabled", "l2_targeted_revision_enabled",
]
