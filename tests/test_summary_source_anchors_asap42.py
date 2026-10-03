"""ASAP 4.2 Step 2a — targeted tests: Summary core (D1/AM-1; spec §1).

Покрытие (owner §49, Summary-часть):
  * anchor format/checksum/reject-mismatch/no-alias/immutability/reverse-map/
    build-asserts/R17 (T-4802);
  * L1 map v2: unassigned считает КОД (T-4803);
  * L1 invalid anchor repair вместо invalidate; structural fatal (T-4804);
  * L2 invalid evidence repair не убивает document; paragraph signal (T-4805);
  * ReviewResult reason-коды + targeted revision (T-4806);
  * один битый anchor НЕ убивает Hybrid document (integration-shape fixture).
"""
from __future__ import annotations

import dataclasses

import pytest

from services.summary_source_anchors import (
    AnchorEntry,
    SourceAnchorMap,
    anchors_enabled,
    build_anchor_map,
    l1_anchor_repair_enabled,
    l2_evidence_repair_enabled,
    l2_targeted_revision_enabled,
    make_anchor,
    normalize_anchor,
    run_fingerprint,
)
from services.summary_l1_repair import repair_l1_anchors
from services.summary_l1_semantic_map import (
    MAP_SCHEMA_VERSION_V2,
    REASON_BAD_SCHEMA_VERSION,
    REASON_UNKNOWN_FIELD,
    compute_unassigned_anchors,
    validate_semantic_map_v2,
)
from services.summary_l2_anchor_repair import (
    ReviewIssue,
    ReviewReason,
    build_targeted_revision_content,
    paragraphs_without_evidence,
    repair_l2_evidence,
    validate_review_result,
)
from services.summary_source_window import SummarySourceWindow

RUN_ID = "run-42a"
CHAT_ID = -100777


def _window(ids=(101, 102, 103, 104), *, run_id=RUN_ID):
    messages = tuple(
        {"message_id": i, "db_id": i + 10_000, "timestamp": i,
         "text": f"msg {i}"} for i in ids)
    return SummarySourceWindow(
        run_id=run_id, chat_id=CHAT_ID, window_from=ids[0] if ids else None,
        window_to=ids[-1] if ids else None, messages=messages,
        messages_json="[]", created_at=0)


def _map(ids=(101, 102, 103, 104), *, run_id=RUN_ID):
    return build_anchor_map(_window(ids, run_id=run_id))


def _topic(anchors, *, title="Тема", participants=("Имя",), hint="h"):
    return {"topic_id": "topic_001", "title": title,
            "source_anchors": list(anchors), "participants": list(participants),
            "short_hint": hint}


def _data(*, topics=(), events=(), relationships=None, unassigned_anchors=None,
          unassigned_message_ids=None):
    data = {"schema_version": MAP_SCHEMA_VERSION_V2, "topics": list(topics),
            "events": list(events)}
    if relationships is not None:
        data["relationships"] = relationships
    if unassigned_anchors is not None:
        data["unassigned_anchors"] = unassigned_anchors
    if unassigned_message_ids is not None:
        data["unassigned_message_ids"] = unassigned_message_ids
    return data


# ═══════════════════════════════════════════════════════════════════════════
# T-4802 — SourceAnchorMap
# ═══════════════════════════════════════════════════════════════════════════

def test_anchor_format_bijection_and_reverse_mapping():
    m = _map((101, 102, 103))
    assert m is not None
    assert len(m) == 3
    import re
    for anchor in m.source_anchors:
        assert re.match(r"^m[0-9A-Z]{4}-[0-9A-Z]{2}$", anchor)
    # биекция: 1 anchor ↔ 1 real id; обратный перевод возвращает TG ids.
    assert m.to_real_ids(m.source_anchors) == [101, 102, 103]
    assert m.real_id(m.anchor_for(102)) == 102
    # anchors не являются сырыми id и в публичный текст не попадают.
    assert m.source_anchors[0] != "101"
    assert all(str(i) not in m.source_anchors for i in (101, 102, 103))


def test_checksum_mismatch_rejected():
    # Map строится кодом, поэтому битый checksum воспроизводим только на
    # прямом AnchorEntry (defense-in-depth проверки §1 инвариант 4/5).
    fingerprint = run_fingerprint(RUN_ID, CHAT_ID, 101, 104)
    bad = dataclasses.replace(
        build_anchor_map(_window()),
        entries=(AnchorEntry(anchor=make_anchor(0, 101, fingerprint),
                             ordinal=0, real_message_id=101),),
        source_count=1)
    # подменим stored anchor на anchor с неверным checksum для того же ordinal
    wrong = "m0000-ZZ"
    tampered = dataclasses.replace(
        bad, entries=(AnchorEntry(anchor=wrong, ordinal=0,
                                  real_message_id=101),))
    check = tampered.validate(wrong)
    assert not check.ok
    assert tampered.resolve(wrong) is None


def test_typo_does_not_alias_other_message():
    m = _map(tuple(range(101, 120)))          # 19 сообщений (ordinal 0..18)
    anchor_11 = m.source_anchors[11]          # ordinal 11 (m000B-…)
    # классическая опечатка m000B → m0012: ordinal-цифры меняются, checksum
    # остаётся от ordinal 11 → anchor невалиден и НЕ равен anchor ordinal 12.
    body = "m0012" + anchor_11[5:]
    assert body != m.source_anchors[12]
    assert not m.is_valid(body)
    assert m.resolve(body) is None


def test_build_asserts_duplicate_real_ids_fail_open():
    # дубль real id в окне → нарушение build-assert → fail-open (None).
    messages = ({"message_id": 101, "db_id": None, "timestamp": 1},
                {"message_id": 101, "db_id": None, "timestamp": 2})
    window = SummarySourceWindow(run_id=RUN_ID, chat_id=CHAT_ID,
                                 window_from=1, window_to=2,
                                 messages=tuple(messages), messages_json="[]",
                                 created_at=0)
    assert build_anchor_map(window) is None


def test_anchor_normalization_case_insensitive():
    m = _map((101,))
    anchor = m.source_anchors[0]
    assert normalize_anchor(anchor.lower()) == anchor
    assert m.is_valid(anchor.lower())
    assert normalize_anchor("garbage") is None
    assert normalize_anchor(123) is None


def test_kill_switches_resolve_default_on():
    # env-only default ON, резолв не бросает.
    assert anchors_enabled() is True
    assert l1_anchor_repair_enabled() is True
    assert l2_evidence_repair_enabled() is True
    assert l2_targeted_revision_enabled() is True


def test_map_is_frozen_and_immutable():
    m = _map((101, 102))
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.source_count = 5
    # мутирование возвращённого контейнера не трогает карту
    anchors = list(m.source_anchors)
    anchors.pop()
    assert len(m) == 2
    # повторное построение на том же окне байт-идентично
    assert _map((101, 102)).entries == m.entries


# ═══════════════════════════════════════════════════════════════════════════
# T-4803 — unassigned считает код
# ═══════════════════════════════════════════════════════════════════════════

def test_unassigned_computed_by_code_ignores_llm():
    m = _map((101, 102, 103, 104))
    a0, a1, a2, a3 = m.source_anchors
    data = _data(topics=[_topic([a0, a1])],
                 # LLM-значение заведомо неверное + legacy-поле.
                 unassigned_anchors=[a0], unassigned_message_ids=[999])
    res = validate_semantic_map_v2(data, m)
    assert res.usable
    assert res.payload["unassigned_anchors"] == [a2, a3]
    assert res.unassigned_count == 2


def test_compute_unassigned_anchors_union_topics_events_relations():
    m = _map((101, 102, 103, 104))
    a0, a1, a2, a3 = m.source_anchors
    payload = {"topics": [_topic([a0])],
               "events": [{"kind": "k", "source_anchors": [a1]}],
               "relationships": [{"type": "reply", "source_anchors": [a2]}]}
    assert compute_unassigned_anchors(payload, m) == [a3]


def test_unassigned_empty_and_invalid_input_safe():
    m = _map((101, 102))
    all_anchors = list(m.source_anchors)
    # пустой/некорректный вход не ломает: всё уходит в unassigned.
    assert compute_unassigned_anchors(None, m) == all_anchors
    assert compute_unassigned_anchors({"topics": "x"}, m) == all_anchors
    assert compute_unassigned_anchors({"topics": [None, 5]}, m) == all_anchors


# ═══════════════════════════════════════════════════════════════════════════
# T-4804 — L1 invalid anchor repair (не invalidate)
# ═══════════════════════════════════════════════════════════════════════════

def test_l1_invalid_anchor_repaired_not_invalid():
    m = _map((101, 102, 103))
    a0, a1, _ = m.source_anchors
    data = _data(topics=[_topic([a0, "mZZZZ-99"])],
                 events=[{"kind": "спор", "source_anchors": [a1]}])
    res = validate_semantic_map_v2(data, m)
    assert res.usable, res.reason
    assert res.anchors_repaired == 1
    assert res.payload["topics"][0]["source_anchors"] == [a0]
    assert res.payload["events"][0]["source_anchors"] == [a1]
    assert res.payload["unassigned_anchors"] == [m.source_anchors[2]]


def test_l1_repair_drops_only_empty_dependent_container():
    m = _map((101, 102))
    a0, _ = m.source_anchors
    data = _data(topics=[_topic(["mZZZZ-99"])],
                 events=[{"kind": "k", "source_anchors": [a0]}])
    res = validate_semantic_map_v2(data, m)
    assert res.usable
    assert res.topics_count == 0 and res.events_count == 1


def test_l1_all_broken_no_structure_is_empty():
    m = _map((101,))
    data = _data(topics=[_topic(["bad-anchor"])], events=[])
    res = validate_semantic_map_v2(data, m)
    assert not res.usable              # полезной структуры не осталось
    assert res.payload is None


def test_l1_no_texts_in_output():
    m = _map((101, 102))
    res = validate_semantic_map_v2(
        _data(topics=[_topic([m.source_anchors[0]])]), m)
    serialized = repr(res.payload)
    assert "msg 101" not in serialized and "msg 102" not in serialized


def test_l1_structural_invalid_still_fatal():
    m = _map((101,))
    assert validate_semantic_map_v2(
        {"schema_version": 1, "topics": [], "events": []}, m
    ).reason == REASON_BAD_SCHEMA_VERSION
    assert validate_semantic_map_v2(
        {"schema_version": MAP_SCHEMA_VERSION_V2, "topics": "x", "events": []},
        m).payload is None
    bad_field = _data(topics=[{"topic_id": "t", "title": "T",
                               "message_ids": [101], "participants": []}])
    assert validate_semantic_map_v2(bad_field, m).reason == REASON_UNKNOWN_FIELD


def test_repair_l1_anchors_report_and_determinism():
    m = _map((101, 102, 103))
    a0, a1, _ = m.source_anchors
    data = _data(topics=[_topic([a0, "mZZZZ-99"])],
                 events=[{"kind": "k", "source_anchors": [a1]}])
    repaired, report = repair_l1_anchors(data, m)
    assert report.anchors_generated == 3
    assert report.anchors_repaired == 1
    assert report.anchors_dropped == 1
    assert report.unassigned_count == 1
    # чистота + детерминизм
    second, report2 = repair_l1_anchors(data, m)
    assert second == repaired and report2 == report


# ═══════════════════════════════════════════════════════════════════════════
# T-4805 — L2 evidence repair не убивает document
# ═══════════════════════════════════════════════════════════════════════════

def _document(paragraphs):
    return {"schema_version": 1, "title": "Статья", "paragraphs": paragraphs,
            "finale": ""}


def test_l2_invalid_evidence_repair_keeps_paragraph():
    m = _map((101, 102, 103))
    a0, a1, _ = m.source_anchors
    doc = _document([
        {"text": "p0", "source_anchors": [a0, "mZZZZ-99"]},
        {"text": "p1", "source_anchors": [a1]},
    ])
    repaired, report = repair_l2_evidence(doc, m)
    assert repaired is not None
    assert report.document_kept
    assert report.paragraphs_count == 2
    assert report.invalid_refs_repaired == 1
    assert repaired["paragraphs"][0]["source_anchors"] == [a0]
    assert repaired["paragraphs"][0]["text"] == "p0"      # абзац сохранён
    assert report.paragraphs_without_evidence == 0


def test_l2_paragraph_without_evidence_is_signal_not_kill():
    m = _map((101,))
    doc = _document([
        {"text": "p0", "source_anchors": []},
        {"text": "p1", "source_anchors": [m.source_anchors[0]]},
    ])
    repaired, report = repair_l2_evidence(doc, m)
    assert repaired is not None
    assert report.paragraphs_without_evidence == 1
    assert paragraphs_without_evidence(repaired) == [0]


def test_l2_unrepairable_structure_returns_none():
    m = _map((101,))
    assert repair_l2_evidence("not-a-doc", m)[0] is None
    assert repair_l2_evidence({"paragraphs": "x"}, m)[0] is None
    assert repair_l2_evidence({"paragraphs": []}, m)[0] is None
    assert repair_l2_evidence({"paragraphs": [None]}, m)[0] is None


def test_bad_anchor_does_not_kill_hybrid_document():
    """Все evidence битые → document остаётся (не None→Legacy), абзацы —
    reviewer signal (R8-C-001 / R8-N-002 integration-shape)."""
    m = _map((101, 102))
    doc = _document([
        {"text": "a", "source_anchors": ["mZZZZ-99"]},
        {"text": "b", "source_anchors": ["not-anchor"]},
    ])
    repaired, report = repair_l2_evidence(doc, m)
    assert repaired is not None
    assert report.document_kept
    assert report.paragraphs_count == 2
    assert report.invalid_refs_repaired == 2
    assert paragraphs_without_evidence(repaired) == [0, 1]


# ═══════════════════════════════════════════════════════════════════════════
# T-4806 — Reviewer verdict + targeted revision
# ═══════════════════════════════════════════════════════════════════════════

def test_review_result_reason_codes_and_drops():
    m = _map((101, 102))
    a0, _ = m.source_anchors
    data = {"status": "needs_fixes", "issues": [
        {"paragraph_id": 0, "reason": ReviewReason.WRONG_SPEAKER.value,
         "source_anchors": [a0], "repair_instruction": "fix speaker"},
        {"paragraph_id": 1, "reason": "bogus_reason",
         "source_anchors": [a0], "repair_instruction": "x"},
        {"paragraph_id": 0, "reason": ReviewReason.BAD_QUOTE.value,
         "source_anchors": ["mZZZZ-99"], "repair_instruction": "no refs"},
    ]}
    res = validate_review_result(data, m, paragraph_count=2)
    assert res.status == "needs_fixes"
    assert len(res.issues) == 1
    assert res.dropped_invalid == 2
    assert res.issues[0].reason == ReviewReason.WRONG_SPEAKER.value
    assert res.issues[0].finding_code == "wrong_person_attribution"


def test_review_result_approved_when_no_valid_issue():
    m = _map((101,))
    data = {"status": "needs_fixes", "issues": [
        {"paragraph_id": 0, "reason": "bogus", "source_anchors": []}]}
    res = validate_review_result(data, m)
    assert res.status == "approved" and res.issues == ()


def test_targeted_revision_is_single_paragraph_and_bounded():
    m = _map((101, 102))
    a0, _ = m.source_anchors
    issue = ReviewIssue(paragraph_id=0, reason=ReviewReason.BAD_QUOTE.value,
                        source_anchors=(a0,), repair_instruction="fix quote")
    content = build_targeted_revision_content(
        paragraph={"text": "p0", "source_anchors": [a0]}, paragraph_id=0,
        issue=issue, source_excerpts=[{"anchor": a0, "text": "hi"}],
        title="Статья")
    assert "single_paragraph" in content
    assert a0 in content
    assert "ДРУГОЙ АБЗАЦ" not in content
    assert "source_excerpts" in content


def test_review_reason_enum_complete():
    assert {r.value for r in ReviewReason} == {
        "wrong_speaker", "bad_quote", "bad_number_date", "unsupported",
        "lost_reply", "no_evidence", "mixed_people"}
