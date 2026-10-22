"""Аудит 23.10.2026 — ревизия L2 покрывает ВСЕ абзацы с находками.

RCA `plans/features/_audit-2026-10-23/summary-review-rca.md`:
  * ревизия чинила только ``anchor_issues[0]`` (один абзац), максимум 2
    ревизии при 4–15 находках в 7–12 абзацах → rejected предопределён
    арифметикой (10/10 rejected с revision_count=2);
  * ``unusable``-gate (D3) при ≥2 hard в ≥2 абзацах — отдельное поведение,
    оно НЕ ослабляется;
  * вердикт/коды/blocking не durable → инцидент нельзя разобрать.

Покрытие (F1 + F2 + мусорный quote-hint):
  1) 5 находок в 3 абзацах → одна batch-ревизия чинит все → approved;
  2) анти-тест: ревизия «не исправила» → по-прежнему rejected
     (планка re-review/anchor-валидации не снижена);
  3) unusable при ≥2 hard-кодах в ≥2 абзацах остаётся терминальным без
     единой ревизии;
  4) durable SUMMARY_L2_STAGE несёт вердикт/коды/blocking/revision_fixed
     на approved И rejected путях;
  5) ``quote_unverified_count`` не подаётся находкой, когда repair-счётчики
     уже закрыли все цитаты (RCA §3 «мусорный hint»).

TEST-LIFECYCLE: CONTRACT owner=AUDIT-23.10/F1-F2
TEST-LIFECYCLE: REGRESSION owner=AUDIT-23.10/revision-single-paragraph
Запуск: pytest tests/test_summary_l2_review_multi_paragraph.py
"""
from __future__ import annotations

import json

import pytest

from services.summary_l2_review import (
    REASON_L2_REVIEW_REJECTED,
    REASON_L2_REVIEW_UNUSABLE,
    _deterministic_findings_from_metrics,
    run_l2_with_review,
)
from services.summary_l2_writer import L2Slot
from services.summary_source_anchors import build_anchor_map
from services.summary_source_window import build_source_window

pytestmark = pytest.mark.asap41

CHAT_ID = -100777

_FLAGS_ON = (
    "SUMMARY_SOURCE_ANCHORS_ENABLED",
    "SUMMARY_L1_ANCHOR_REPAIR_ENABLED",
    "SUMMARY_L2_EVIDENCE_REPAIR_ENABLED",
    "SUMMARY_L2_TARGETED_REVISION_ENABLED",
    "SUMMARY_L2_REVIEW_ENABLED",
    "SUMMARY_REVISION_PATCH_ENABLED",
)


def _flag(monkeypatch, name, value):
    import config.settings as _cs
    import services.summary_l2_review as _rev
    import services.summary_l2_writer as _wr
    from config.settings import Settings
    classes = {Settings, type(_cs.settings), type(_rev.settings),
               type(_wr.settings)}
    for _cls in classes:
        monkeypatch.setattr(_cls, name, value, raising=False)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in _FLAGS_ON:
        _flag(monkeypatch, name, True)


def _package():
    return {
        "schema_version": 2, "status": "ok",
        "threads": [{"thread_id": "t", "name": "T", "description": "",
                     "chronology": [], "facts": [], "fragments": []}],
        "service": {"response_mode": "serious", "cover_prompt": ""},
        "unassigned_message_ids": [],
    }


def _rows(count, *, start=101):
    return [
        {"id": start + i, "tg_message_id": start + i,
         "user_id": 10 + (i % 3), "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} и продолжение мысли",
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


def _anchor_env(run_id="audit-l2-batch"):
    window = build_source_window(run_id, CHAT_ID, _rows(5))
    am = build_anchor_map(window)
    return am, [e.anchor for e in am.entries]


def _doc(anchors):
    return {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0]]},
        {"text": "P1.", "source_anchors": [anchors[1]]},
        {"text": "P2.", "source_anchors": [anchors[2]]},
        {"text": "P3 без находок.", "source_anchors": [anchors[3]]},
    ]}


class _Writer:
    def __init__(self, document):
        self.document = document
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        return json.dumps(self.document, ensure_ascii=False)


class _Seq:
    """Последовательные ответы канала; последний повторяется; пишет вход."""

    def __init__(self, seq):
        self.seq = list(seq)
        self.calls: list = []

    async def __call__(self, messages):
        self.calls.append(messages)
        if len(self.seq) > 1:
            return self.seq.pop(0)
        return self.seq[0]

    @property
    def user_payloads(self):
        return [json.loads(m[1]["content"].split("\n", 1)[1])
                for m in self.calls]


def _issue(paragraph_id, anchors, reason, instruction="исправь"):
    return {"paragraph_id": paragraph_id, "reason": reason,
            "source_anchors": list(anchors),
            "repair_instruction": instruction}


def _reviewer_json(status, issues=None):
    return json.dumps({"status": status, "issues": list(issues or [])},
                      ensure_ascii=False)


def _batch_revision(anchors, paragraphs=(0, 1, 2)):
    return json.dumps({"replace_paragraphs": [
        {"paragraph_id": index, "text": f"P{index} fixed.",
         "source_anchors": [anchors[index]]}
        for index in paragraphs]}, ensure_ascii=False)


def _five_findings_three_paragraphs(anchors):
    """5 находок в 3 абзацах, 4 разных hard-кода (RCA §1: findings 4–15)."""
    return [
        _issue(0, [anchors[0]], "bad_quote"),
        _issue(0, [anchors[1]], "unsupported"),
        _issue(1, [anchors[1]], "bad_number_date"),
        _issue(1, [anchors[2]], "unsupported"),
        _issue(2, [anchors[3]], "lost_reply"),
    ]


async def _run(*, am, doc, reviewer, revision, run_id):
    return await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id=run_id, chat_id=CHAT_ID, llm_call=_Writer(doc),
        reviewer_call=reviewer, revision_call=revision, anchor_map=am)


# ══ F1: одна ревизия покрывает ВСЕ абзацы с находками ══════════════════════

@pytest.mark.asyncio
async def test_five_findings_in_three_paragraphs_approved_after_one_revision():
    am, anchors = _anchor_env("audit-batch-a")
    doc = _doc(anchors)
    reviewer = _Seq([
        _reviewer_json("needs_fixes",
                       _five_findings_three_paragraphs(anchors)),
        _reviewer_json("approved"),
    ])
    revision = _Seq([_batch_revision(anchors)])
    res = await _run(am=am, doc=doc, reviewer=reviewer, revision=revision,
                     run_id="audit-batch-a")

    assert res.usable, res.invalid_reason
    assert res.metrics["l2_review_findings_total"] == 5
    assert res.metrics["l2_revision_count"] == 1        # один вызов на всё
    assert res.metrics["l2_revision_calls"] == 1
    assert res.metrics["l2_final_approved"] == 1
    assert res.metrics["l2_legacy_after_review"] == 0
    # Все три абзаца с находками переписаны, четвёртый не тронут.
    assert [p["text"] for p in res.document["paragraphs"]] == [
        "P0 fixed.", "P1 fixed.", "P2 fixed.", "P3 без находок."]
    # Запрос ревизии — batch-скоуп со всеми тремя абзацами (не только первый).
    payload = revision.user_payloads[0]
    assert payload["revision_scope"] == "multiple_paragraphs"
    assert [p["paragraph_id"] for p in payload["paragraphs"]] == [0, 1, 2]
    # Ни один абзац вне заявленных находок не попал в запрос.
    assert "P3 без находок." not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_batch_revision_that_does_not_fix_is_still_rejected():
    """Анти-тест: планка не снижена. Ревизия применилась (документ
    изменился), но находки те же → stagnation → rejected, не approved."""
    am, anchors = _anchor_env("audit-batch-b")
    doc = _doc(anchors)
    findings = _five_findings_three_paragraphs(anchors)
    reviewer = _Seq([_reviewer_json("needs_fixes", findings)])   # всегда
    revision = _Seq([_batch_revision(anchors)])
    res = await _run(am=am, doc=doc, reviewer=reviewer, revision=revision,
                     run_id="audit-batch-b")

    assert res.usable is False
    assert res.invalid_reason == REASON_L2_REVIEW_REJECTED
    assert res.metrics["l2_final_approved"] == 0
    assert res.metrics["l2_legacy_after_review"] == 1
    assert res.metrics["l2_revision_count"] == 1     # ревизия реально была
    assert res.metrics["l2_revision_fixed_count"] == 0
    assert res.metrics.get("l2_stagnation_fingerprint") == 1


@pytest.mark.asyncio
async def test_unusable_gate_two_hard_two_paragraphs_stays_terminal():
    """>=2 hard разных кодов в >=2 разных абзацах → Legacy без ревизий
    (поведение D3 сохранено; F1 его не трогает)."""
    am, anchors = _anchor_env("audit-batch-c")
    reviewer = _Seq([_reviewer_json("unusable", [
        _issue(0, [anchors[0]], "bad_quote"),        # quote_speaker_mismatch
        _issue(1, [anchors[1]], "bad_number_date"),  # unsupported_number
    ])])
    revision = _Seq(["НЕ ДОЛЖНО ВЫЗЫВАТЬСЯ"])
    res = await _run(am=am, doc=_doc(anchors), reviewer=reviewer,
                     revision=revision, run_id="audit-batch-c")

    assert res.usable is False
    assert res.invalid_reason == REASON_L2_REVIEW_UNUSABLE
    assert res.metrics["l2_unusable_gate"] == 1
    assert res.metrics["l2_review_calls"] == 1
    assert res.metrics["l2_revision_count"] == 0
    assert revision.calls == []


# ══ Batch-аппликатор: bounded scope, атомарность, anchor-валидация ═════════

def test_apply_targeted_revision_batch_rejects_out_of_scope_paragraph():
    from services.summary_l2_review import apply_targeted_revision_batch
    am, anchors = _anchor_env("audit-batch-d")
    doc = _doc(anchors)
    payload = json.dumps({"replace_paragraphs": [
        {"paragraph_id": 3, "text": "P3 переписан.",   # не заявлен находкой
         "source_anchors": [anchors[3]]}]}, ensure_ascii=False)
    revised, reason = apply_targeted_revision_batch(
        doc, payload, anchor_map=am, package=_package(),
        allowed_paragraph_ids={0, 1, 2})
    assert revised is None
    assert reason == "revision_invalid_patch"
    # атомарно: исходный документ не изменён
    assert [p["text"] for p in doc["paragraphs"]][3] == "P3 без находок."


def test_apply_targeted_revision_batch_applies_all_allowed_paragraphs():
    from services.summary_l2_review import apply_targeted_revision_batch
    am, anchors = _anchor_env("audit-batch-e")
    doc = _doc(anchors)
    revised, reason = apply_targeted_revision_batch(
        doc, _batch_revision(anchors), anchor_map=am, package=_package(),
        allowed_paragraph_ids={0, 1, 2})
    assert reason is None
    assert [p["text"] for p in revised["paragraphs"]] == [
        "P0 fixed.", "P1 fixed.", "P2 fixed.", "P3 без находок."]
    assert revised["paragraphs"][0]["source_anchors"] == [anchors[0]]
    assert revised["paragraphs"][3]["source_anchors"] == [anchors[3]]


# ══ F2: durable вердикт/коды/blocking в SUMMARY_L2_STAGE ═══════════════════

def _capture_l2_stage(monkeypatch, metrics, *, usable, status):
    from services import pipeline_events
    captured = {}

    def _fake_emit(event_name, **kwargs):
        captured["event_name"] = event_name
        captured.update(kwargs)

    monkeypatch.setattr(pipeline_events, "_emit", _fake_emit)
    pipeline_events.l2_stage(
        "run-audit-f2", chat_id=CHAT_ID, usable=usable,
        invalid_reason=None if usable else "l2_review_rejected",
        duration_ms=10.0, paragraphs=4, status=status, metrics=metrics,
        reviewer_reject=not usable)
    return captured


def test_durable_l2_stage_carries_review_diagnosis_on_approved_path(
        monkeypatch):
    metrics = {
        "l2_review_last_verdict": "approved",
        "l2_review_blocking": 0,
        "l2_review_finding_codes": [],
        "l2_revision_count": 1,
        "l2_revision_fixed_count": 5,
    }
    captured = _capture_l2_stage(monkeypatch, metrics, usable=True,
                                 status="ok")
    counts = captured["counts"]
    assert counts["review_verdict"] == "approved"
    assert counts["review_blocking"] == 0
    assert counts["revision_fixed"] == 5


def test_durable_l2_stage_carries_review_diagnosis_on_rejected_path(
        monkeypatch):
    metrics = {
        "l2_review_last_verdict": "needs_fixes",
        "l2_review_blocking": 3,
        "l2_review_finding_codes": [
            "quote_speaker_mismatch", "unsupported_claim",
            "unsupported_number"],
        "l2_revision_count": 2,
        "l2_revision_fixed_count": 2,
    }
    captured = _capture_l2_stage(monkeypatch, metrics, usable=False,
                                 status="invalid")
    counts = captured["counts"]
    assert captured["status"] == "failed"
    assert counts["review_verdict"] == "needs_fixes"
    assert counts["review_blocking"] == 3
    assert counts["review_finding_codes"] == [
        "quote_speaker_mismatch", "unsupported_claim", "unsupported_number"]
    assert counts["revision_fixed"] == 2
    # R17: только коды, никаких текстов/промптов.
    assert all(len(str(code)) < 64 for code in counts["review_finding_codes"])


def test_durable_codes_capped_at_eight(monkeypatch):
    codes = [f"code_{i}" for i in range(12)]
    captured = _capture_l2_stage(
        monkeypatch,
        {"l2_review_last_verdict": "needs_fixes", "l2_review_blocking": 12,
         "l2_review_finding_codes": codes},
        usable=False, status="invalid")
    assert len(captured["counts"]["review_finding_codes"]) == 8


@pytest.mark.asyncio
async def test_rejected_run_metrics_carry_durable_verdict_and_codes():
    """Сквозной rejected-run: metrics, попадающие в SUMMARY_L2_STAGE,
    содержат вердикт/blocking/коды и корректный revision_fixed."""
    am, anchors = _anchor_env("audit-batch-f")
    findings = _five_findings_three_paragraphs(anchors)
    reviewer = _Seq([_reviewer_json("needs_fixes", findings)])
    revision = _Seq([_batch_revision(anchors)])
    res = await _run(am=am, doc=_doc(anchors), reviewer=reviewer,
                     revision=revision, run_id="audit-batch-f")
    assert res.usable is False
    assert res.metrics["l2_review_last_verdict"] == "needs_fixes"
    assert res.metrics["l2_review_blocking"] == 5
    assert res.metrics["l2_review_finding_codes"] == [
        "quote_speaker_mismatch", "reply_attribution_error",
        "unsupported_claim", "unsupported_number"]
    assert res.metrics["l2_revision_fixed_count"] == 0


# ══ Мусорный deterministic-hint: quote_unverified_count ════════════════════

def test_quote_unverified_hint_dropped_when_repairs_close_accounting():
    """41 цитата: 0 verified, 39 repaired, 2 removed → в документе кавычек
    для проверки не осталось; исторический счётчик не является находкой."""
    findings = _deterministic_findings_from_metrics({
        "quotes_total": 41, "quotes_verified": 0,
        "quotes_repaired": 39, "quotes_removed": 2,
        "quote_unverified_count": 41,
        "quote_unresolved_blockers": [],
    })
    assert findings == []


def test_quote_unverified_hint_kept_for_live_gap_or_blockers():
    """Не скрываем сигнал, если учёт не закрыт или есть живой блокер."""
    gap = _deterministic_findings_from_metrics({
        "quotes_total": 41, "quotes_verified": 0,
        "quotes_repaired": 39, "quotes_removed": 0,
        "quote_unverified_count": 41,
    })
    assert [f["code"] for f in gap] == ["quote_unverified_count"]
    blocker = _deterministic_findings_from_metrics({
        "quotes_total": 1, "quotes_verified": 0,
        "quotes_repaired": 0, "quotes_removed": 0,
        "quote_unverified_count": 1,
        "quote_unresolved_blockers": ["quote_text_not_found"],
    })
    assert [f["code"] for f in blocker] == [
        "quote_text_not_found", "quote_unverified_count"]
    # legacy/OFF-путь без accounting-полей — сигнал сохраняется.
    legacy = _deterministic_findings_from_metrics(
        {"quote_unverified_count": 1})
    assert [f["code"] for f in legacy] == ["quote_unverified_count"]
