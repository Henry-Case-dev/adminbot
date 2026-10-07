"""ASAP 4.4 Z5 — Hybrid Summary L2 closure (T-4876/T-4877, §6 tests #14–#18).

Покрытие:
  #14 deterministic findings пересчитываются после успешной revision;
  #15 stale finding не возвращается Reviewer после исправления;
  #16 invalid targeted revision reason виден в stage diagnostics
      (review_attempt/verdict/finding_codes/blocking_count/paragraph_ids/
       revision_target/revision_result/revision_failure_reason/
       deterministic_validation_codes);
  #17 bounded цикл остаётся bounded (≤MAX_REVISIONS/≤MAX_REVIEWS/≤budget);
  #18 Reviewer strictness/evidence fail-closed не ослаблены;
  + regression: named-механизм T-4877 — targeted revision payload schema
    (nested echo shape / evidence_message_ids) больше не сжигает обе
    revision и не уводит run в Legacy.

Все LLM-каналы инжектируются (llm_call/reviewer_call/revision_call) —
0 сетевых/платных вызовов. R17: только коды/числа/индексы.
"""
from __future__ import annotations

import json

import pytest

from services.summary_l2_review import (
    MAX_REVIEWS,
    MAX_REVISIONS,
    REASON_L2_REVIEW_REJECTED,
    REASON_L2_REVIEW_UNUSABLE,
    run_l2_with_review,
)
from services.summary_l2_writer import L2Slot
from services.summary_source_anchors import build_anchor_map
from services.summary_source_window import build_source_window

pytestmark = [pytest.mark.asap4, pytest.mark.asap41]

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


def _rows(count, *, start=101, text_size=16):
    return [
        {"id": start + i, "tg_message_id": start + i,
         "user_id": 10 + (i % 3), "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} " * (text_size // 4),
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


def _anchor_env(run_id="asap44-l2"):
    rows = _rows(4)
    window = build_source_window(run_id, CHAT_ID, rows)
    am = build_anchor_map(window)
    anchors = [e.anchor for e in am.entries]
    return rows, am, anchors


class _Writer:
    def __init__(self, document):
        self.document = document
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        return json.dumps(self.document, ensure_ascii=False)


class _Seq:
    """Последовательные ответы канала; последний повторяется."""

    def __init__(self, seq):
        self.seq = list(seq)
        self.calls: list = []

    async def __call__(self, messages):
        self.calls.append(messages)
        if len(self.seq) > 1:
            return self.seq.pop(0)
        return self.seq[0]


class RunContextStub:
    def __init__(self):
        self.stage_events = []


def _issue(paragraph_id, anchors, reason="no_evidence", instruction="fix"):
    return {"paragraph_id": paragraph_id, "reason": reason,
            "source_anchors": list(anchors),
            "repair_instruction": instruction}


def _reviewer_json(status, issues=None):
    return json.dumps({"status": status, "issues": list(issues or [])},
                      ensure_ascii=False)


def _review_content_payload(reviewer_messages, index):
    """JSON-хвост user-контента Reviewer (после строки-инструкции)."""
    content = reviewer_messages[index][1]["content"]
    return json.loads(content.split("\n", 1)[1])


def _doc_with_p0_no_evidence(anchors):
    return {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": []},
        {"text": "P1.", "source_anchors": [anchors[1]]},
    ]}


# ══ #14 — deterministic findings пересчитываются после revision ════════════

@pytest.mark.asyncio
async def test_14_deterministic_findings_recomputed_after_revision():
    _, am, anchors = _anchor_env("asap44-l2-14")
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": []},          # без evidence
        {"text": "P1.", "source_anchors": []},          # без evidence
    ]}
    reviewer = _Seq([
        _reviewer_json("needs_fixes",
                       [_issue(0, [anchors[0]], reason="no_evidence")]),
        _reviewer_json("approved"),
    ])
    revision = _Seq([json.dumps(
        {"text": "P0 fixed.", "source_anchors": [anchors[2]]},
        ensure_ascii=False)])
    res = await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id="asap44-l2-14", chat_id=CHAT_ID,
        llm_call=_Writer(doc), reviewer_call=reviewer,
        revision_call=revision, anchor_map=am)
    assert res.usable
    assert res.metrics["l2_revision_count"] == 1
    # Ревью #2 получило findings, пересчитанные от ТЕКУЩЕГО документа:
    # исправленный абзац #0 больше без evidence, абзац #1 всё ещё без него.
    findings = _review_content_payload(reviewer.calls, 1)[
        "deterministic_findings"]
    codes = [f["code"] for f in findings]
    assert codes == ["paragraphs_without_evidence"]
    assert findings[0].get("count") == 1          # было 2 (stale) → стало 1


# ══ #15 — stale finding не возвращается после исправления ═══════════════════

@pytest.mark.asyncio
async def test_15_stale_finding_not_returned_after_fix():
    _, am, anchors = _anchor_env("asap44-l2-15")
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": []},          # без evidence
        {"text": "P1.", "source_anchors": [anchors[1]]},
    ]}
    reviewer = _Seq([
        _reviewer_json("needs_fixes",
                       [_issue(0, [anchors[1]], reason="no_evidence")]),
        _reviewer_json("approved"),
    ])
    revision = _Seq([json.dumps(
        {"text": "P0 fixed.", "source_anchors": [anchors[2]]},
        ensure_ascii=False)])
    res = await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id="asap44-l2-15", chat_id=CHAT_ID,
        llm_call=_Writer(doc), reviewer_call=reviewer,
        revision_call=revision, anchor_map=am)
    assert res.usable
    assert res.document["paragraphs"][0]["source_anchors"] == [anchors[2]]
    findings = _review_content_payload(reviewer.calls, 1)[
        "deterministic_findings"]
    assert findings == []                     # stale finding исчез


# ══ #16 — invalid revision reason в stage diagnostics ═══════════════════════

@pytest.mark.asyncio
async def test_16_invalid_revision_reason_in_stage_diagnostics():
    _, am, anchors = _anchor_env("asap44-l2-16")
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": []},
        {"text": "P1.", "source_anchors": [anchors[1]]},
    ]}
    reviewer = _Seq([
        _reviewer_json("needs_fixes",
                       [_issue(0, [anchors[1]], reason="bad_quote")]),
    ])
    revision = _Seq(["не json"])
    ctx = RunContextStub()
    res = await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id="asap44-l2-16", chat_id=CHAT_ID,
        llm_call=_Writer(doc), reviewer_call=reviewer,
        revision_call=revision, anchor_map=am, ctx=ctx)
    assert not res.usable
    assert res.invalid_reason == REASON_L2_REVIEW_REJECTED
    reviews = [e for e in ctx.stage_events if e["stage"] == "l2_reviewer"]
    revs = [e for e in ctx.stage_events if e["stage"] == "revision"]
    assert reviews and revs
    assert reviews[0]["review_attempt"] == 1
    assert reviews[0]["verdict"] == "needs_fixes"
    assert reviews[0]["finding_codes"] == ["quote_speaker_mismatch"]
    assert reviews[0]["blocking_count"] == 1
    assert reviews[0]["paragraph_ids"] == [0]
    assert isinstance(reviews[0]["deterministic_validation_codes"], list)
    assert revs[0]["revision_target"] == "targeted"
    assert revs[0]["revision_result"] == "invalid"
    assert revs[0]["revision_failure_reason"] == "revision_invalid_json"


# ══ #17 — bounded цикл остаётся bounded ═════════════════════════════════════

@pytest.mark.asyncio
async def test_17_bounded_cycle_stays_bounded():
    _, am, anchors = _anchor_env("asap44-l2-17")
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0]]},
        {"text": "P1.", "source_anchors": [anchors[1]]},
    ]}
    reviewer = _Seq([_reviewer_json(
        "needs_fixes", [_issue(0, [anchors[0]], reason="unsupported")])])
    revision = _Seq(["не json"])                 # обе revision сгорают
    writer = _Writer(doc)
    res = await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id="asap44-l2-17", chat_id=CHAT_ID,
        llm_call=writer, reviewer_call=reviewer,
        revision_call=revision, anchor_map=am)
    assert not res.usable and res.invalid_reason == REASON_L2_REVIEW_REJECTED
    assert res.metrics["l2_review_calls"] <= MAX_REVIEWS
    assert res.metrics["l2_revision_calls"] <= MAX_REVISIONS
    assert len(revision.calls) == MAX_REVISIONS
    assert len(reviewer.calls) <= MAX_REVIEWS
    assert writer.calls == 1


# ══ #18 — Reviewer strictness/evidence fail-closed не ослаблены ════════════

@pytest.mark.asyncio
async def test_18_reviewer_strictness_not_weakened_dropped_evidence():
    _, am, anchors = _anchor_env("asap44-l2-18a")
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0]]},
    ]}
    # Находка с выдуманным anchor отбрасывается → основания для revision нет.
    reviewer = _Seq([_reviewer_json(
        "needs_fixes", [_issue(0, ["mZZZZ-99"], reason="bad_quote")])])
    revision = _Seq([json.dumps({"text": "x", "source_anchors": []},
                                ensure_ascii=False)])
    res = await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id="asap44-l2-18a", chat_id=CHAT_ID,
        llm_call=_Writer(doc), reviewer_call=reviewer,
        revision_call=revision, anchor_map=am)
    assert res.usable
    assert res.metrics["l2_revision_count"] == 0     # strictness: нет basis
    assert revision.calls == []


@pytest.mark.asyncio
async def test_18_reviewer_unusable_without_evidence_not_terminal():
    """ASAP 5 D3/§16#5 (SUPERSEDE raw-unusable fail-closed): unusable без
    findings/deterministic proof — НЕ terminal: gate даунгрейдит до
    needs_fixes (трейс-событие l2_unusable_gate), 0 findings →
    deterministic-валидный черновик публикуется degraded."""
    _, am, anchors = _anchor_env("asap44-l2-18b")
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0]]},
    ]}
    ctx = RunContextStub()
    reviewer = _Seq([_reviewer_json("unusable")])
    res = await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id="asap44-l2-18b", chat_id=CHAT_ID,
        llm_call=_Writer(doc), reviewer_call=reviewer,
        revision_call=_Seq([""]), anchor_map=am, ctx=ctx)
    assert res.usable
    assert res.metrics["l2_review_degraded"] == 1
    assert res.metrics["l2_unusable_gate_downgrades"] == 1
    gate_events = [e for e in ctx.stage_events
                   if e.get("reason_code") == "l2_unusable_gate"]
    assert gate_events, "даунгрейд гейта виден в трейсе (D3/D17)"


# ══ named-механизм T-4877: targeted revision schema ═════════════════════════

@pytest.mark.asyncio
async def test_targeted_revision_accepts_nested_echo_shape():
    """Reviser может вернуть абзац во вложенном контейнере
    (`paragraph`/`revised_paragraph` — эхо запроса); это НЕ должно сжигать
    обе revision и уводить run в Legacy."""
    _, am, anchors = _anchor_env("asap44-l2-schema-a")
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0]]},
        {"text": "P1.", "source_anchors": [anchors[1]]},
    ]}
    reviewer = _Seq([
        _reviewer_json("needs_fixes",
                       [_issue(0, [anchors[0]], reason="bad_quote")]),
        _reviewer_json("approved"),
    ])
    revision = _Seq([json.dumps({
        "revision_scope": "single_paragraph",
        "paragraph_id": 0,
        "paragraph": {"text": "P0 fixed.",
                      "source_anchors": [anchors[2]]},
    }, ensure_ascii=False)])
    res = await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id="asap44-l2-schema-a", chat_id=CHAT_ID,
        llm_call=_Writer(doc), reviewer_call=reviewer,
        revision_call=revision, anchor_map=am)
    assert res.usable
    assert res.metrics["l2_revision_count"] == 1
    assert res.document["paragraphs"][0]["text"] == "P0 fixed."
    assert res.document["paragraphs"][0]["source_anchors"] == [anchors[2]]
    assert res.document["paragraphs"][1]["text"] == "P1."


@pytest.mark.asyncio
async def test_targeted_revision_maps_evidence_message_ids():
    """`evidence_message_ids` (real id) в targeted-ответе маппится в
    anchor-space, а не молча теряется/сжигает revision."""
    rows, am, anchors = _anchor_env("asap44-l2-schema-b")
    real_id = rows[2]["tg_message_id"]
    doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
        {"text": "P0.", "source_anchors": [anchors[0]]},
        {"text": "P1.", "source_anchors": [anchors[1]]},
    ]}
    reviewer = _Seq([
        _reviewer_json("needs_fixes",
                       [_issue(0, [anchors[0]], reason="bad_number_date")]),
        _reviewer_json("approved"),
    ])
    revision = _Seq([json.dumps({"replace_paragraphs": [
        {"index": 0, "text": "P0 fixed.",
         "evidence_message_ids": [real_id]}]}, ensure_ascii=False)])
    res = await run_l2_with_review(
        None, _package(), slot=L2Slot("http://x", "m", "k", False),
        reviewer_slot=L2Slot("http://x", "m", "k", False),
        correlation_id="asap44-l2-schema-b", chat_id=CHAT_ID,
        llm_call=_Writer(doc), reviewer_call=reviewer,
        revision_call=revision, anchor_map=am)
    assert res.usable
    assert res.metrics["l2_revision_count"] == 1
    assert res.document["paragraphs"][0]["text"] == "P0 fixed."
    assert res.document["paragraphs"][0]["source_anchors"] == [anchors[2]]
