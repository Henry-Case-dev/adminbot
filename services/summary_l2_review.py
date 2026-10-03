"""ASAP-4 волна D (epic `asap-4-embedding-graphrag-cover-runtime`) — Hybrid
L2 Writer/Reviewer bounded revision loop (spec §4 D.4/D.5, ADR-1028-7 D3/D5;
T-4431/T-4432; ТЗ §50.1–§50.2, §50.10–§50.29, §50.57–§50.58).

SUPERSEDE (ADR-1028-7 D3): прежний контракт «L2 correction retry НЕ
вводится» заменён владельцем (§50.1) на **bounded semantic revision ×2**:
Draft → Review → (NEEDS_FIXES) → Revision #1 → Validate+Review →
(NEEDS_FIXES, progress ok) → Revision #2 → Final Review → APPROVED | LEGACY.
Принцип §50.2 «сломалась плитка — не сносим дом»: локальная находка чинит
минимальный участок, а не уносит статью в Legacy.

Call budget (ADR-1028-7 D3.3, §50.57): L2-стадия ≤ **6** логических
LLM-вызовов (writer 1 + reviewer ≤3 + revision ≤2; happy=2, rev1=4,
rev2=6; Legacy-прямой = writer 1 + Legacy L; k = L1-чанки; transport-ретраи
в budget не входят). Потолок закреплён тестом (golden M/J).

Semantic Reviewer (§50.10–§50.17, §50.26–§50.28):
  * вход — FactPackage + roster + evidence index + draft + deterministic
    findings; выход — ТОЛЬКО structured verdict
    ``{status: approved|needs_fixes|unusable, findings: [{code, severity,
    paragraph_index, evidence_refs, instruction}]}``; новую статью не пишет;
  * НЕ источник истины (§50.11): finding валиден только с refs ⊆ id-space
    пакета (или deterministic rule); invalid findings отбрасываются;
    needs_fixes без единой валидной находки = approved (нет основания);
  * codes §50.12 (15 шт.); style vs fact §50.26 (мат/сарказм/ирония не
    бракуются); modality/числа/timeline — high-risk;
  * model slot §50.28: наследует L2; hot-override
    ``models.summary_l2_reviewer_*`` / ``keys.summary_l2_reviewer_api_key``
    (пусто → наследование, безопасный default, Δ каталога = 0).

Revision (§50.22–§50.25, ADR D5): patch-контракт
``{"replace_paragraphs": [{index, text, evidence_message_ids}]}`` — primary;
full-document revision — escape-hatch (findings > 50% абзацев, патч дважды
невалиден, kill-switch OFF). Preserve-инструкция §50.22. Progress criterion
§50.25: blocking findings не уменьшились → сразу safe fallback (Legacy),
без бесконечного repair. После второй итерации autonomous-циклов нет.

review_degraded (§50.29, ADR-1028-7 D3.5): reviewer outage (LLM-ошибка/
timeout/невалидный вердикт) НЕ теряет хороший документ: deterministic
validator остаётся источником safety; при валидных evidence refs и
пройденных deterministic checks документ публикуется как degraded
(``review_degraded=1`` + ``pipeline_health=degraded``); fixed в stage
events как degraded, не success.

Kill-switches (spec §8.2; env-only, default ON):
  * ``SUMMARY_L2_REVIEW_ENABLED`` — OFF: L2 без Reviewer/Revision
    (invalid → Legacy немедленно, бит-в-бит; генератор вообще не вызывает
    этот модуль);
  * ``SUMMARY_REVISION_PATCH_ENABLED`` — OFF: revision полным документом
    (если master ON; обе ветки bounded).

Метрики §50.58 (в L2Result.metrics → лог ``L2_REVIEW``/``L2_COMPLETE``):
``l2_first_pass_approved / l2_review_findings_total / l2_revision_count /
l2_revision_fixed_count / l2_revision_new_findings / l2_final_approved /
l2_legacy_after_review`` (+ ``l2_review_calls``/``l2_revision_calls``/
``l2_review_degraded``). Все значения — числа/коды (R17-safe).

Чистых LLM-вызовов здесь ровно сколько насчитал budget; сетевой канал —
существующий транзит ``summary_l2_writer`` (dedicated slot/LLMClient).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time

from config.settings import settings
from services.summary_l2_writer import (
    L2Result,
    L2Slot,
    _make_llm_call,
    _normalise_call_result,
    build_participant_roster,
    build_l2_input,
    empty_result,
    error_result,
    invalid_result,
    package_message_id_space,
    resolve_l2_slot_safe,
    validate_l2_document,
)
from services.summary_prompts import (
    SUMMARY_L2_REVIEWER_SOURCE_BLOCK,
    SUMMARY_L2_REVIEWER_SYSTEM_PROMPT,
    SUMMARY_L2_REVISER_SYSTEM_PROMPT,
)
from services.system2_handoff import parse_json_object

logger = logging.getLogger(__name__)

MODULE = "summary"
STEP = "l2_review"

# ── Kill-switches (spec §8.2) ──────────────────────────────────────────────


def l2_review_enabled() -> bool:
    """``SUMMARY_L2_REVIEW_ENABLED`` (env-only, default ON; per-call). OFF →
    прежний single-call L2 (invalid → Legacy немедленно, бит-в-бит)."""
    try:
        return bool(getattr(settings, "SUMMARY_L2_REVIEW_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def revision_patch_enabled() -> bool:
    """``SUMMARY_REVISION_PATCH_ENABLED`` (env-only, default ON). OFF →
    revision полным документом (master ON; деградация НЕ до Legacy)."""
    try:
        return bool(getattr(settings, "SUMMARY_REVISION_PATCH_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


# ── Bounded budget (ADR-1028-7 D3.3; §50.57) ───────────────────────────────

CALL_BUDGET_L2_STAGE = 6       # writer 1 + reviewer ≤3 + revision ≤2
MAX_REVISIONS = 2
MAX_REVIEWS = 3

# ── Findings §50.12 (минимальный набор) ────────────────────────────────────

FINDING_CODE_UNSUPPORTED_CLAIM = "unsupported_claim"
FINDING_CODE_WRONG_PERSON = "wrong_person_attribution"
FINDING_CODE_QUOTE_TEXT_NOT_FOUND = "quote_text_not_found"
FINDING_CODE_QUOTE_SPEAKER_UNRESOLVED = "quote_speaker_unresolved"
FINDING_CODE_QUOTE_SPEAKER_MISMATCH = "quote_speaker_mismatch"
FINDING_CODE_QUOTE_SOURCE_AMBIGUOUS = "quote_source_ambiguous"
FINDING_CODE_FORWARD_ATTRIBUTION = "forward_attribution_error"
FINDING_CODE_REPLY_ATTRIBUTION = "reply_attribution_error"
FINDING_CODE_UNSUPPORTED_NUMBER = "unsupported_number"
FINDING_CODE_TIMELINE = "timeline_inconsistency"
FINDING_CODE_CONTRADICTION = "contradiction_with_package"
FINDING_CODE_INVENTED_NAME = "invented_name"
FINDING_CODE_DUPLICATE_EVENT = "duplicate_event"
FINDING_CODE_MAJOR_TOPIC_OMITTED = "major_topic_omitted"
FINDING_CODE_FACTUAL_OVERSTATEMENT = "factual_overstatement"

FINDING_CODES: frozenset[str] = frozenset({
    FINDING_CODE_UNSUPPORTED_CLAIM,
    FINDING_CODE_WRONG_PERSON,
    FINDING_CODE_QUOTE_TEXT_NOT_FOUND,
    FINDING_CODE_QUOTE_SPEAKER_UNRESOLVED,
    FINDING_CODE_QUOTE_SPEAKER_MISMATCH,
    FINDING_CODE_QUOTE_SOURCE_AMBIGUOUS,
    FINDING_CODE_FORWARD_ATTRIBUTION,
    FINDING_CODE_REPLY_ATTRIBUTION,
    FINDING_CODE_UNSUPPORTED_NUMBER,
    FINDING_CODE_TIMELINE,
    FINDING_CODE_CONTRADICTION,
    FINDING_CODE_INVENTED_NAME,
    FINDING_CODE_DUPLICATE_EVENT,
    FINDING_CODE_MAJOR_TOPIC_OMITTED,
    FINDING_CODE_FACTUAL_OVERSTATEMENT,
})

VERDICT_APPROVED = "approved"
VERDICT_NEEDS_FIXES = "needs_fixes"
VERDICT_UNUSABLE = "unusable"
VERDICT_STATUSES = frozenset(
    {VERDICT_APPROVED, VERDICT_NEEDS_FIXES, VERDICT_UNUSABLE})

SEVERITY_BLOCKING = "blocking"
SEVERITY_MINOR = "minor"

# Причины fail-closed исходов ревизии (R17-safe коды;Legacy-триггеры —
# только из перечня §50.2: «Writer не дал документа / пакет непригоден /
# после bounded revision остались blocking errors / противоречие широко /
# runtime не дал закончить» — все пять покрыты ветками ниже).
REASON_L2_REVIEW_REJECTED = "l2_review_rejected"
REASON_L2_REVIEW_UNUSABLE = "l2_review_unusable"
# Degraded-маркер (§50.29/ADR D3.5): не reason-фейл, а флаг в metrics.
METRIC_REVIEW_DEGRADED = "l2_review_degraded"


@dataclasses.dataclass(frozen=True)
class ReviewFinding:
    """Валидированная находка Reviewer (§50.10/§50.11)."""

    code: str
    severity: str
    paragraph_index: int | None
    evidence_refs: tuple[int, ...]
    instruction: str

    @property
    def blocking(self) -> bool:
        return self.severity == SEVERITY_BLOCKING


@dataclasses.dataclass(frozen=True)
class ReviewVerdict:
    """Результат ревизии: статус + валидированные findings + диагностика."""

    status: str
    findings: tuple[ReviewFinding, ...]
    raw_status: str = "ok"          # ok | invalid | error
    reason: str | None = None       # R17-safe код при outage
    dropped_findings: int = 0

    @property
    def outage(self) -> bool:
        """Reviewer runtime-fail (§50.29): ошибка/невалидный вердикт."""
        return self.raw_status != "ok"

    @property
    def blocking_count(self) -> int:
        return sum(1 for f in self.findings if f.blocking)


# ── Слот Reviewer (§50.28: наследует L2, safe default) ─────────────────────


def resolve_l2_reviewer_slot(*, hot_get=None, settings_obj=None) -> L2Slot:
    """Слот L2 Reviewer: hot ``models.summary_l2_reviewer_*`` /
    ``keys.summary_l2_reviewer_api_key``; пусто → НАСЛЕДУЕТ слот L2 (§50.28,
    безопасный default без нового обязательного конфига). Не бросает
    (ошибки резолва L2-слота — callers через :class:`L2SlotError` контракт)."""
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    st = settings_obj or settings

    def _read(key: str, field: str) -> str:
        return str(hot_get(key, getattr(st, field, "")) or "").strip()

    base = _read("models.summary_l2_reviewer_base_url",
                 "SUMMARY_L2_REVIEWER_BASE_URL")
    model = _read("models.summary_l2_reviewer_model_name",
                  "SUMMARY_L2_REVIEWER_MODEL_NAME")
    key = _read("keys.summary_l2_reviewer_api_key",
                "SUMMARY_L2_REVIEWER_API_KEY")
    if not (base or model or key):
        return resolve_l2_slot_safe(hot_get=hot_get, settings_obj=st)
    # Частичный override добирается из L2-слота (не из глобальной модели).
    l2 = resolve_l2_slot_safe(hot_get=hot_get, settings_obj=st)
    return L2Slot(
        base_url=base or l2.base_url,
        model=model or l2.model,
        api_key=key or l2.api_key,
        dedicated=True)


# ── Вердикт Reviewer: разбор + валидация (§50.10/§50.11) ───────────────────


def parse_review_verdict(raw, *, package, document=None) -> ReviewVerdict:
    """Строгий разбор вердикта: неизвестные/невалидные findings ОТБРАСЫВАЮТСЯ
    (§50.11 «invalid findings отбрасываются; unknown > hallucinated»).

    Правила валидации finding: код ∈ §50.12; paragraph_index — int в границах
    документа; evidence_refs непустые И ⊆ id-space пакета (доказательственная
    база: пустой список или отсутствующее поле = находка без доказательств —
    отбрасывается так же, как выдуманный ID; R17-safe лог
    ``L2_REVIEW_FINDING_DROPPED``); severity нормализуется (unknown →
    blocking — консервативно для progress criterion). Статус вне трёх
    допустимых → invalid verdict (outage-путь §50.29). needs_fixes без
    единой валидной находки → approved (нет основания). Не бросает.
    """
    data = parse_json_object(str(raw or ""))
    if not isinstance(data, dict):
        return ReviewVerdict(status=VERDICT_UNUSABLE, findings=(),
                             raw_status="invalid",
                             reason="review_invalid_json")
    status = str(data.get("status") or "").strip().lower()
    if status not in VERDICT_STATUSES:
        return ReviewVerdict(status=VERDICT_UNUSABLE, findings=(),
                             raw_status="invalid",
                             reason="review_invalid_status")
    id_space = package_message_id_space(package)
    paragraphs = (document or {}).get("paragraphs") or []
    dropped = 0
    findings: list[ReviewFinding] = []
    raw_findings = data.get("findings")
    if isinstance(raw_findings, list):
        for item in raw_findings:
            if not isinstance(item, dict):
                dropped += 1
                continue
            code = str(item.get("code") or "").strip()
            if code not in FINDING_CODES:
                dropped += 1
                continue
            index = item.get("paragraph_index")
            if isinstance(index, bool) or not isinstance(index, int):
                index = None
            elif index < 0 or (paragraphs and index >= len(paragraphs)):
                dropped += 1
                continue
            refs: list[int] = []
            invalid_ref = False
            for ref in item.get("evidence_refs") or []:
                if isinstance(ref, bool) or not isinstance(ref, int):
                    invalid_ref = True
                    break
                if ref not in id_space:
                    invalid_ref = True
                    break
                if ref not in refs:
                    refs.append(ref)
            if invalid_ref or not refs:
                # §50.11: finding валиден только с refs ⊆ package —
                # выдуманный ID И ПУСТЫЕ/ОТСУТСТВУЮЩИЕ evidence_refs
                # (находка без доказательств) отбрасываются одинаково;
                # такая находка не порождает ревизию (unknown >
                # hallucinated). Rework-1 T-4438 (M-ASAP4-D1).
                dropped += 1
                logger.info(
                    "L2_REVIEW_FINDING_DROPPED | code=%s | cause=%s",
                    code, "invalid_ref" if invalid_ref else "missing_refs")
                continue
            severity = str(item.get("severity") or "").strip().lower()
            if severity not in (SEVERITY_BLOCKING, SEVERITY_MINOR):
                severity = SEVERITY_BLOCKING
            instruction = str(item.get("instruction") or "").strip()
            findings.append(ReviewFinding(
                code=code, severity=severity, paragraph_index=index,
                evidence_refs=tuple(refs), instruction=instruction[:500]))
    if status == VERDICT_NEEDS_FIXES and not findings:
        # §50.11: все находки отброшены → основания нет → approved.
        status = VERDICT_APPROVED
    return ReviewVerdict(status=status, findings=tuple(findings),
                         raw_status="ok", dropped_findings=dropped)


def _review_verdict_error(reason: str) -> ReviewVerdict:
    return ReviewVerdict(status=VERDICT_UNUSABLE, findings=(),
                         raw_status="error", reason=reason)


# ── Входы Reviewer/Revision (компактный JSON, детерминированный порядок) ───


def build_review_content(package, document, roster, deterministic_findings,
                         *, emphasize=None, source_window_content=None,
                         semantic_map=None, evidence_slices=None) -> str:
    """User-контент Reviewer: пакет (тот же компактный формат, что Writer),
    roster, draft, deterministic findings. ``emphasize`` — подмножество
    индексов абзацев для повторного ревизии (дифф-контекст, ADR D5 п.2).

    ASAP 4.1 волна 3 (T-4610, spec §2 B.4; ADR-1028-8 D4/AM-4) — аддитивно:
      * ``source_window_content`` — Full SourceWindow (serialized; Reviewer
        сверяет attribution/quotes/числа/reply/major topics против РЕАЛЬНОГО
        source, R6-B-007);
      * ``evidence_slices`` — CAPACITY_OVERFLOW: evidence-slices абзацев
        (paragraph ``evidence_message_ids[]`` + reply-контекст,
        разворачиваемые детерминированно из SourceWindow) + segment maps
        для completeness — никогда только FactPackage;
      * ``semantic_map`` — карта структурных подсказок (Draft + Full
        SourceWindow + SemanticMap)."""
    content = {
        "package_json": build_l2_input(package),
        "participants": roster,
        "draft": document,
        "deterministic_findings": list(deterministic_findings or []),
    }
    if source_window_content:
        content["source_window"] = str(source_window_content)
    if semantic_map:
        content["semantic_map"] = semantic_map
    if evidence_slices:
        content["evidence_slices"] = list(evidence_slices)
    if emphasize is not None:
        content["review_focus_paragraphs"] = sorted(emphasize)
    body = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return ("ПРОВЕРЬ СТАТЬЮ ПО ПАКЕТУ ФАКТОВ (компактный JSON; верни только "
            "вердикт):\n" + body)


def build_revision_content(package, document, findings, *, full_doc: bool,
                           deterministic_note: str | None = None,
                           source_window_content=None,
                           semantic_map=None) -> str:
    """User-контент Revision (§50.22): original draft + FactPackage +
    конкретные findings + разрешённый evidence set + preserve-инструкция.

    ``full_doc=False`` — patch-контракт ADR D5: ``{"replace_paragraphs":
    [{index, text, evidence_message_ids}]}``; ``full_doc=True`` — полный
    документ §99 (escape-hatch: findings > 50% абзацев / патч дважды
    невалиден / kill-switch OFF). Волна 3 (T-4610): source window/map —
    аддитивные секции (исправление сверяется с оригиналом).
    """
    compact_findings = [
        {"code": f.code, "severity": f.severity,
         "paragraph_index": f.paragraph_index,
         "evidence_refs": list(f.evidence_refs),
         "instruction": f.instruction}
        for f in findings
    ]
    content = {
        "package_json": build_l2_input(package),
        "draft": document,
        "findings": compact_findings,
        "preserve": ("Исправь только необходимые места. Сохрани все "
                     "корректные абзацы. Не добавляй новых фактов, имён, "
                     "чисел или цитат. Не переписывай статью целиком без "
                     "необходимости."),
    }
    if deterministic_note:
        content["deterministic_note"] = deterministic_note
    if source_window_content:
        content["source_window"] = str(source_window_content)
    if semantic_map:
        content["semantic_map"] = semantic_map
    if full_doc:
        content["output_format"] = (
            'Верни СТРОГО JSON-документ статьи целиком: {"schema_version": 1,'
            ' "title": "...", "paragraphs": [{"text": "...", '
            '"emphasis_spans": [...], "evidence_message_ids": [...]}]'
            " — с исправлениями по замечаниям, всё остальное без изменений.")
    else:
        content["output_format"] = (
            'Верни СТРОГО JSON ТОЛЬКО с заменяемыми абзацами: '
            '{"replace_paragraphs": [{"index": 0, "text": "новый текст '
            'абзаца", "evidence_message_ids": [123]}]} — index = 0-based '
            "номер абзаца черновика; текст полная замена этого абзаца; "
            "остальные абзацы НЕ возвращай и не меняй.")
    body = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return "ВНЕСИ ИСПРАВЛЕНИЯ ПО ЗАМЕЧАНИЯМ (компактный JSON):\n" + body


# ── Применение ревизии (patch ADR D5 / full-doc) ───────────────────────────

def build_review_evidence_slices(document, payload_items) -> list:
    """CAPACITY_OVERFLOW Reviewer (T-4610, spec §2 B.4): evidence-slices
    абзацев против оригинала — paragraph ``evidence_message_ids[]`` +
    reply-контекст (родители ответов, один уровень), разворачиваемые
    детерминированно из SourceWindow. Никогда только FactPackage.

    Абзацы без evidence не получают slice (их поверхность — пакет). Не
    бросает."""
    item_map: dict = {}
    for item in payload_items or []:
        if not isinstance(item, dict):
            continue
        mid = item.get("message_id")
        if isinstance(mid, int) and not isinstance(mid, bool) \
                and mid not in item_map:
            item_map[mid] = item
    slices: list = []
    paragraphs = (document or {}).get("paragraphs") or []
    for index, paragraph in enumerate(paragraphs):
        if not isinstance(paragraph, dict):
            continue
        ids: list = []
        for ref in paragraph.get("evidence_message_ids") or []:
            if isinstance(ref, int) and not isinstance(ref, bool) \
                    and ref in item_map and ref not in ids:
                ids.append(ref)
        if not ids:
            continue
        for mid in list(ids):
            parent = (item_map.get(mid) or {}).get("reply_to_id")
            if isinstance(parent, int) and not isinstance(parent, bool) \
                    and parent in item_map and parent not in ids:
                ids.append(parent)
        slices.append({
            "paragraph_index": index,
            "message_ids": ids,
            "items": [item_map[mid] for mid in ids],
        })
    return slices


def apply_revision_patch(document, payload, *, package) -> tuple[dict | None,
                                                                  str | None]:
    """Валидировать и применить patch-ответ (``replace_paragraphs``).

    Правила: список dict'ов; index — 0-based существующий абзац ЛИБО
    ``len(paragraphs)`` (дописать ОДИН абзац в конец — natural fix для
    major_topic_omitted в patch-режиме; остальные абзацы по-прежнему
    не трогаются); text — непустая строка; evidence_message_ids (алиас
    ``evidence_refs``) — только ID из пакета. НЕТронутые абзацы сохраняются
    байт-в-байт (принцип §50.2). Финальный документ проходит ПОЛНУЮ
    детерминированную валидацию (``validate_l2_document``) — invalid patch
    → ``(None, reason)``. Не бросает.
    """
    data = parse_json_object(str(payload or ""))
    if not isinstance(data, dict):
        return None, "revision_invalid_json"
    replacements = data.get("replace_paragraphs")
    if not isinstance(replacements, list) or not replacements:
        return None, "revision_invalid_patch"
    paragraphs = [dict(p) for p in (document or {}).get("paragraphs") or []]
    touched: set[int] = set()
    for item in replacements:
        if not isinstance(item, dict):
            return None, "revision_invalid_patch"
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int) \
                or not 0 <= index <= len(paragraphs) or index in touched:
            return None, "revision_invalid_patch"
        touched.add(index)
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            return None, "revision_invalid_patch"
        refs = item.get("evidence_message_ids", item.get("evidence_refs"))
        if refs is None:
            refs = []
        if not isinstance(refs, list):
            return None, "revision_invalid_patch"
        entry = {"text": text, "emphasis_spans": [],
                 "evidence_message_ids": refs}
        if index == len(paragraphs):
            paragraphs.append(entry)       # append для omitted topic
        else:
            paragraphs[index] = entry
    revised = {"schema_version": 1,
               "title": str((document or {}).get("title") or ""),
               "paragraphs": paragraphs}
    if (document or {}).get("finale"):
        revised["finale"] = document["finale"]
    canonical, _metrics = validate_l2_document(revised, package)
    if canonical is None:
        return None, "revision_invalid_patch"
    return canonical, None


def apply_full_revision(payload, *, package) -> tuple[dict | None,
                                                      str | None]:
    """Валидировать full-document revision (escape-hatch): тот же §99-
    документ через полную детерминированную валидацию. Не бросает."""
    data = parse_json_object(str(payload or ""))
    if not isinstance(data, dict):
        return None, "revision_invalid_json"
    canonical, _metrics = validate_l2_document(data, package)
    if canonical is None:
        return None, "revision_invalid_document"
    return canonical, None


# ── Метрики §50.58 ─────────────────────────────────────────────────────────


def _review_metrics() -> dict:
    return {
        "l2_first_pass_approved": 0,
        "l2_review_findings_total": 0,
        "l2_revision_count": 0,
        "l2_revision_fixed_count": 0,
        "l2_revision_new_findings": 0,
        "l2_final_approved": 0,
        "l2_legacy_after_review": 0,
        "l2_review_calls": 0,
        "l2_revision_calls": 0,
        METRIC_REVIEW_DEGRADED: 0,
        "l2_review_dropped_findings": 0,
    }


def _log_review(*, run_id, chat_id, metrics, status, reason=None) -> None:
    logger.info(
        "L2_REVIEW | run_id=%s | chat_id=%s | status=%s | "
        "first_pass_approved=%d | findings_total=%d | revision_count=%d | "
        "revision_fixed=%d | revision_new=%d | final_approved=%d | "
        "legacy_after_review=%d | review_calls=%d | revision_calls=%d | "
        "degraded=%d | dropped_findings=%d | reason=%s",
        run_id or "none", chat_id, status,
        int(metrics.get("l2_first_pass_approved", 0)),
        int(metrics.get("l2_review_findings_total", 0)),
        int(metrics.get("l2_revision_count", 0)),
        int(metrics.get("l2_revision_fixed_count", 0)),
        int(metrics.get("l2_revision_new_findings", 0)),
        int(metrics.get("l2_final_approved", 0)),
        int(metrics.get("l2_legacy_after_review", 0)),
        int(metrics.get("l2_review_calls", 0)),
        int(metrics.get("l2_revision_calls", 0)),
        int(metrics.get(METRIC_REVIEW_DEGRADED, 0)),
        int(metrics.get("l2_review_dropped_findings", 0)),
        reason or "-")


def _stage_event(stage, *, attempt, status, reason_code=None,
                 started=None, input_count=None, output_count=None,
                 provider=None, model=None, fallback_target=None,
                 repair_target=None) -> dict:
    """Append-only stage event (§50.54; R17-safe: числа/коды/id)."""
    return {
        "stage": stage,
        "attempt": int(attempt),
        "status": status,
        "reason_code": reason_code,
        "started_at": started,
        "finished_at": time.time(),
        "input_count": input_count,
        "output_count": output_count,
        "provider": provider,
        "model": model,
        "fallback_target": fallback_target,
        "repair_target": repair_target,
    }


def _record(ctx, event: dict) -> None:
    """Append-only в RunContext.stage_events (если ctx передан)."""
    if ctx is None:
        return
    try:
        events = getattr(ctx, "stage_events", None)
        if isinstance(events, list):
            events.append(event)
    except Exception:      # pragma: no cover - best-effort
        pass


# ── Канал LLM (тот же транзит, что Writer) ─────────────────────────────────


def _extract_usage(value):
    from services.summary_l2_writer import _extract_usage as _impl
    return _impl(value)


async def _call_llm(llm, slot: L2Slot, messages, *, correlation_id,
                    llm_call=None, operation: str = "reviewer") -> tuple[str, dict]:
    """Один логический вызов через существующий канал Writer (dedicated
    slot/глобальная модель). Возвращает ``(raw, usage)``; сетевые ошибки —
    наверх (LLMError/Exception).

    ASAP 4.1 волна 4 (T-4612): ``operation`` — честная метка supervised
    вызова (reviewer/revision) для LLMExecutionSupervisor (ADR-1028-8 D5)."""
    if llm_call is not None:
        raw_value = await llm_call(messages)
        raw, usage = _normalise_call_result(raw_value)
        return raw, (usage if isinstance(usage, dict) else {})
    call = _make_llm_call(llm, slot, correlation_id, operation=operation)
    raw_value = await call(messages)
    raw, usage = _normalise_call_result(raw_value)
    return raw, (usage if isinstance(usage, dict) else {})


# ── Bounded loop (§50.24/§50.25; ADR D3/D5) ────────────────────────────────

async def run_l2_with_review(llm, package, *, service=None,
                             correlation_id=None, chat_id=None,
                             slot=None, reviewer_slot=None,
                             llm_call=None, reviewer_call=None,
                             revision_call=None, ctx=None,
                             writer_source_input=None, writer_length=None,
                             semantic_map=None, source_window_content=None,
                             evidence_slices=None, review_full_window=True,
                             review_payload_items=None,
                             source_message_ids=None) -> L2Result:
    """L2-стадия с bounded review: Draft → Validate → Review → (×2 Revision)
    → APPROVED | Legacy | review_degraded.

    Writer — существующий ``run_l2`` (ровно 1 вызов + детерминированная
    валидация/repair внутри). Reviewer/Revision — этот модуль. Потолок
    логических вызовов ``CALL_BUDGET_L2_STAGE=6`` закреплён проверкой перед
    каждым вызовом. Kill-switch ``SUMMARY_L2_REVIEW_ENABLED=OFF``: вызывающий
    (генератор) не заходит сюда — бит-в-бит прежний single-call путь.

    ASAP 4.1 волна 3 (T-4610, spec §2 B.4; ADR-1028-8 D4/AM-4) — аддитивно:
      * ``writer_source_input``/``writer_length`` — WriterInput от Full
        SourceWindow (T-4609);
      * ``source_window_content`` — Full SourceWindow в контексте Reviewer
        (system-канон + блок источника);
      * ``evidence_slices`` — overflow-поверхность (slices против оригинала);
      * ``semantic_map`` — структурные подсказки (ReviewResult = Draft +
        Full SourceWindow + SemanticMap).
    Bounded revision ×2 / patch-контракт / progress criterion — БЕЗ изменений.

      * ``review_full_window``/``review_payload_items`` — overflow-режим
        Reviewer: slices строятся от evidence черновика детерминированно из
        SourceWindow (никогда только FactPackage);
      * ``source_message_ids`` — id-space РЕАЛЬНОГО окна: находки/revision
        могут доказываться refs из окна (id-window ⊇ пакета; R6-B-007).

    Возвраты:
      * ``ok`` + документ — approved (first-pass или после ревизии);
      * ``ok`` + ``l2_review_degraded=1`` — reviewer outage при пройденной
        deterministic-валидации (§50.29/ADR D3.5: publish degraded);
      * ``invalid`` ``l2_review_rejected`` — blocking findings не сошли после
        bounded revision / бюджет исчерпан / нет прогресса (§50.25) →
        вызывающий идёт в Legacy (перечень §50.2);
      * ``invalid`` ``l2_review_unusable`` — вердикт unusable (статья широко
        противоречит пакету) → Legacy немедленно;
      * writer-фейл (не usable) возвращается как есть — прежняя семантика.
    """
    started = time.perf_counter()

    def _elapsed() -> float:
        return (time.perf_counter() - started) * 1000.0

    # 1. Writer (вызов #1) — прежний контракт без изменений.
    draft = await _writer_call(llm, package, service=service,
                               correlation_id=correlation_id, chat_id=chat_id,
                               slot=slot, llm_call=llm_call,
                               source_input=writer_source_input,
                               length=writer_length)
    if not draft.usable:
        return draft
    if not l2_review_enabled():
        # Defense-in-depth: генератор уже не заходит сюда при OFF.
        return draft

    document = draft.document
    # T-4610 (R6-B-007): при переданных id окна ReviewResult сверяется
    # против пакета ∪ РЕАЛЬНОГО окна (refs из source валидны).
    run_package = package
    if source_message_ids:
        try:
            from services.summary_fact_view import ensure_full_id_space
            run_package = ensure_full_id_space(package, source_message_ids)
        except Exception:      # fail-open (augment не блокирует review)
            run_package = package
    roster = build_participant_roster(package)
    metrics = _review_metrics()
    # Duck-typing: тестовые/альтернативные writer-результаты могут не нести
    # полный L2Result-контракт (metrics/usage) — читаем защитно.
    draft_metrics = getattr(draft, "metrics", None) or {}
    metrics.update(dict(draft_metrics))
    try:
        reviewer = reviewer_slot or resolve_l2_reviewer_slot()
    except Exception as exc:      # слот-ошибка = reviewer outage (§50.29)
        return _degraded_or_legacy(draft, document, metrics,
                                   reason="reviewer_slot_failed",
                                   correlation_id=correlation_id,
                                   chat_id=chat_id, exc=exc)

    source_review_system = SUMMARY_L2_REVIEWER_SYSTEM_PROMPT
    if source_window_content or evidence_slices:
        source_review_system = (
            SUMMARY_L2_REVIEWER_SYSTEM_PROMPT
            + SUMMARY_L2_REVIEWER_SOURCE_BLOCK)
    if evidence_slices is None and not review_full_window \
            and review_payload_items:
        # T-4610 (spec §2 B.4, CAPACITY_OVERFLOW Reviewer): полный window не
        # влезает → evidence-slices абзацев (evidence_message_ids +
        # reply-контекст) разворачиваются детерминированно из SourceWindow;
        # никогда только FactPackage.
        evidence_slices = build_review_evidence_slices(
            document, review_payload_items)
        if evidence_slices:
            source_review_system = (
                SUMMARY_L2_REVIEWER_SYSTEM_PROMPT
                + SUMMARY_L2_REVIEWER_SOURCE_BLOCK)
            logger.info(
                "L2_REVIEW_EVIDENCE_SLICES | run_id=%s | chat_id=%s | "
                "slices=%d", correlation_id or "none", chat_id,
                len(evidence_slices))

    deterministic_findings = _deterministic_findings(draft)
    calls = 1                     # writer
    revisions_done = 0
    patch_failures = 0
    last_revision_burned = False
    prev_blocking: int | None = None
    first_blocking: int | None = None
    seen_codes: set[str] = set()
    first_findings_total = 0
    current_doc = document
    last_verdict: ReviewVerdict | None = None
    dropped_total = 0

    while True:
        # ── Review (≤3 за стадию) ───────────────────────────────────────
        if metrics["l2_review_calls"] >= MAX_REVIEWS \
                or calls >= CALL_BUDGET_L2_STAGE:
            break
        review_started = time.time()
        try:
            raw, _usage = await _call_llm(
                llm, reviewer,
                [{"role": "system",
                  "content": source_review_system},
                 {"role": "user",
                  "content": build_review_content(
                      package, current_doc, roster, deterministic_findings,
                      source_window_content=source_window_content,
                      semantic_map=semantic_map,
                      evidence_slices=evidence_slices)}],
                 correlation_id=correlation_id, llm_call=reviewer_call,
                 operation="reviewer")
        except Exception as exc:  # noqa: BLE001 - outage-путь §50.29
            _record(ctx, _stage_event(
                "l2_reviewer", attempt=metrics["l2_review_calls"] + 1,
                status="error", reason_code=type(exc).__name__,
                started=review_started, input_count=len(current_doc.get(
                    "paragraphs") or [])))
            return _degraded_or_legacy(
                draft, current_doc, metrics,
                reason=f"reviewer_{type(exc).__name__}",
                correlation_id=correlation_id, chat_id=chat_id, exc=exc)
        calls += 1
        metrics["l2_review_calls"] += 1
        verdict = parse_review_verdict(raw, package=run_package,
                                       document=current_doc)
        dropped_total += verdict.dropped_findings
        if verdict.outage:
            _record(ctx, _stage_event(
                "l2_reviewer", attempt=metrics["l2_review_calls"],
                status="degraded", reason_code=verdict.reason,
                started=review_started))
            return _degraded_or_legacy(
                draft, current_doc, metrics, reason=verdict.reason or
                "reviewer_invalid_verdict",
                correlation_id=correlation_id, chat_id=chat_id)
        _record(ctx, _stage_event(
            "l2_reviewer", attempt=metrics["l2_review_calls"],
            status=verdict.status,
            reason_code=f"findings={len(verdict.findings)}",
            started=review_started,
            input_count=len(current_doc.get("paragraphs") or [])))
        last_verdict = verdict
        if verdict.status == VERDICT_APPROVED:
            break
        if verdict.status == VERDICT_UNUSABLE:
            # Статья широко противоречит пакету (§50.2) → Legacy немедленно.
            metrics["l2_legacy_after_review"] = 1
            metrics["l2_review_dropped_findings"] = dropped_total
            _log_review(run_id=correlation_id, chat_id=chat_id,
                        metrics=metrics, status="unusable",
                        reason=REASON_L2_REVIEW_UNUSABLE)
            return invalid_result(REASON_L2_REVIEW_UNUSABLE,
                                  duration_ms=_elapsed(),
                                  metrics=metrics)
        # ── NEEDS_FIXES: решения о ревизии (§50.24/§50.25) ──────────────
        if first_findings_total == 0:
            first_findings_total = len(verdict.findings)
            metrics["l2_review_findings_total"] = first_findings_total
            first_blocking = verdict.blocking_count
        else:
            # §50.58: НОВЫЕ коды замечаний после первой ревизии (считаются
            # ДО обновления seen_codes — иначе собственные коды вердикта
            # затирают дифф).
            new_now = len({f.code for f in verdict.findings} - seen_codes)
            metrics["l2_revision_new_findings"] = max(
                int(metrics.get("l2_revision_new_findings", 0)), new_now)
        seen_codes.update(f.code for f in verdict.findings)
        blocking_now = verdict.blocking_count
        if revisions_done >= MAX_REVISIONS:
            break                       # autonomous-циклов больше нет
        if calls >= CALL_BUDGET_L2_STAGE:
            break                       # бюджет исчерпан
        # §50.25: blocking findings не уменьшились → safe fallback. НО:
        # сожжённая ревизия (patch не прошёл deterministic-валидацию) — НЕ
        # попытка исправления (документ не менялся) → единственная
        # full-doc-ретриа допустима, пока есть бюджет (≤2 ревизий).
        if (prev_blocking is not None and blocking_now >= prev_blocking
                and not last_revision_burned):
            break
        prev_blocking = blocking_now
        # ── Revision (≤2, patch primary / full-doc escape-hatch) ────────
        paragraphs_now = current_doc.get("paragraphs") or []
        findings_paragraphs = {f.paragraph_index for f in verdict.findings
                               if f.paragraph_index is not None}
        # ADR D5: full-doc escape-hatch — findings покрывают СТРОГО >50%
        # абзацев, ИЛИ патч уже провалил deterministic-валидацию.
        # Интерпретация (б) «дважды невалидный патч» при бюджете ×2:
        # первая невалидная попытка патча активирует full-doc на следующей
        # (последней) ревизии — иначе «дважды» съело бы весь бюджет на
        # заведомо сломанный режим (потолок ≤2 ревизий не меняется).
        findings_majority = bool(paragraphs_now) and \
            len(findings_paragraphs) * 2 > len(paragraphs_now)
        use_full_doc = (
            (not revision_patch_enabled())
            or patch_failures >= 1
            or findings_majority)
        revision_started = time.time()
        try:
            raw_rev, _usage = await _call_llm(
                llm, reviewer,
                [{"role": "system",
                  "content": SUMMARY_L2_REVISER_SYSTEM_PROMPT},
                 {"role": "user",
                  "content": build_revision_content(
                      package, current_doc, verdict.findings,
                      full_doc=use_full_doc,
                      source_window_content=source_window_content,
                      semantic_map=semantic_map)}],
                 correlation_id=correlation_id, llm_call=revision_call,
                 operation="revision")
        except Exception as exc:  # noqa: BLE001 - revision outage
            _record(ctx, _stage_event(
                "revision", attempt=revisions_done + 1, status="error",
                reason_code=type(exc).__name__, started=revision_started,
                repair_target="patch" if not use_full_doc else "full_doc"))
            return _degraded_or_legacy(
                draft, current_doc, metrics,
                reason=f"revision_{type(exc).__name__}",
                correlation_id=correlation_id, chat_id=chat_id, exc=exc)
        calls += 1
        metrics["l2_revision_calls"] += 1
        revisions_done += 1
        metrics["l2_revision_count"] = revisions_done
        if use_full_doc:
            revised, reason = apply_full_revision(raw_rev,
                                                  package=run_package)
            repair_target = "full_doc"
        else:
            revised, reason = apply_revision_patch(current_doc, raw_rev,
                                                   package=run_package)
            repair_target = "patch"
        _record(ctx, _stage_event(
            "revision", attempt=revisions_done,
            status="ok" if revised is not None else "invalid",
            reason_code=reason, started=revision_started,
            input_count=len(paragraphs_now),
            output_count=len((revised or {}).get("paragraphs") or []),
            repair_target=repair_target))
        # T-4624 (spec §7.3; §42 ТЗ): SUMMARY_REVISION_RESULT — каждый
        # шаг bounded revision виден в mca_events (attempt/patch-target,
        # R17-числа). Fail-open; gated реальным transport'ом.
        try:
            from services import pipeline_events as _pe
            _pe.revision_result(
                correlation_id, chat_id=chat_id, attempt=revisions_done,
                usable=revised is not None, repair_target=repair_target,
                reason_code=None if revised is not None
                else str(reason or "revision_invalid"))
        except Exception:      # pragma: no cover - эмиссия не рвёт
            pass
        if revised is None:
            # Невалидная ревизия активирует full-doc escape-hatch (ADR D5);
            # сам документ не меняется, прогресс-критерий на сгоревшую
            # ревизию не срабатывает (см. выше).
            if repair_target == "patch":
                patch_failures += 1
            last_revision_burned = True
            continue
        last_revision_burned = False
        if repair_target == "patch":
            patch_failures = 0
        current_doc = revised

    # ── Итог цикла ──────────────────────────────────────────────────────
    if last_verdict is not None and last_verdict.status == VERDICT_APPROVED:
        metrics["l2_final_approved"] = 1
        if first_findings_total == 0 and metrics["l2_revision_count"] == 0:
            metrics["l2_first_pass_approved"] = 1
        else:
            # §50.58: сколько blocking-находок первой ревизии закрыто.
            metrics["l2_revision_fixed_count"] = max(
                0, (first_blocking or 0) - last_verdict.blocking_count)
        metrics["l2_review_dropped_findings"] = dropped_total
        _log_review(run_id=correlation_id, chat_id=chat_id, metrics=metrics,
                    status="approved")
        return _ok_result(current_doc, metrics, draft, _elapsed())
    # NEEDS_FIXES после исчерпания bounded-цикла → safe fallback (§50.2/§50.24).
    metrics["l2_legacy_after_review"] = 1
    metrics["l2_review_dropped_findings"] = dropped_total
    _log_review(run_id=correlation_id, chat_id=chat_id, metrics=metrics,
                status="rejected", reason=REASON_L2_REVIEW_REJECTED)
    return invalid_result(REASON_L2_REVIEW_REJECTED,
                          duration_ms=_elapsed(), metrics=metrics)


async def _writer_call(llm, package, *, service, correlation_id, chat_id,
                       slot, llm_call, source_input=None, length=None) -> L2Result:
    from services.summary_l2_writer import run_l2
    return await run_l2(llm, package, service=service,
                        correlation_id=correlation_id, chat_id=chat_id,
                        slot=slot, llm_call=llm_call,
                        source_input=source_input, length=length)


def _deterministic_findings(draft: L2Result) -> list[dict]:
    """Детерминированные находки для контекста Reviewer (§50.10; из метрик
    deterministic-валидатора draft — codes/числа, без текстов)."""
    findings: list[dict] = []
    metrics = getattr(draft, "metrics", None) or {}
    for code in metrics.get("quote_reason_codes") or []:
        findings.append({"source": "deterministic", "code": code})
    for key in ("quote_unverified_count", "ids_stripped_count",
                "emphasis_dropped_count", "paragraphs_without_evidence"):
        value = metrics.get(key)
        if isinstance(value, int) and value > 0:
            findings.append({"source": "deterministic", "code": key,
                             "count": value})
    return findings


def _ok_result(document, metrics: dict, draft: L2Result,
               duration_ms: float) -> L2Result:
    merged = dict(metrics)
    usage = getattr(draft, "usage", None)
    return L2Result(status="ok", document=document,
                    invalid_reason=None, usage=usage, metrics=merged,
                    duration_ms=duration_ms)


def _degraded_or_legacy(draft: L2Result, document, metrics: dict, *,
                        reason: str, correlation_id, chat_id,
                        exc: BaseException | None = None) -> L2Result:
    """Reviewer outage → fail-soft (§50.29, ADR-1028-7 D3.5).

    Deterministic validator уже прошёл (draft usable = структурно валиден,
    evidence refs валидны, цитаты/ID/length проверены) → документ
    публикуется как ``review_degraded`` (metrics + WARN); не терять хороший
    документ из-за reviewer-таймаута. NB: «недоказуемый factual support →
    Legacy» покрывает deterministic-слой — сюда попадают только документы,
    его прошедшие.
    """
    logger.warning(
        "L2_REVIEW_DEGRADED | run_id=%s | chat_id=%s | reason=%s — "
        "publish degraded (deterministic checks passed)",
        correlation_id or "none", chat_id, reason)
    metrics[METRIC_REVIEW_DEGRADED] = 1
    _log_review(run_id=correlation_id, chat_id=chat_id, metrics=metrics,
                status="degraded", reason=reason)
    try:
        duration = float(draft.duration_ms)
    except (TypeError, AttributeError):
        duration = 0.0
    return _ok_result(document, metrics, draft, duration)


# ── Экспорт minimal surface для тестов/генератора ──────────────────────────

__all__ = [
    "CALL_BUDGET_L2_STAGE",
    "FINDING_CODES",
    "METRIC_REVIEW_DEGRADED",
    "MAX_REVISIONS",
    "REASON_L2_REVIEW_REJECTED",
    "REASON_L2_REVIEW_UNUSABLE",
    "ReviewFinding",
    "ReviewVerdict",
    "apply_full_revision",
    "apply_revision_patch",
    "build_participant_roster",
    "build_review_content",
    "build_review_evidence_slices",
    "build_revision_content",
    "l2_review_enabled",
    "parse_review_verdict",
    "resolve_l2_reviewer_slot",
    "revision_patch_enabled",
    "run_l2_with_review",
    "empty_result",
    "error_result",
    "invalid_result",
]
