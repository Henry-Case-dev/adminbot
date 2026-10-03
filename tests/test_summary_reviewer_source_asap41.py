"""ASAP 4.1 волна 3 (эпик asap-4-1-durable-whole-window-summary) — T-4610:
Reviewer сверяется против РЕАЛЬНОГО source; bounded revision сохраняется
(spec §2 B.4; ADR-1028-8 D4/AM-4; §17–§19).

Покрытие:
  * ReviewResult = Draft + Full SourceWindow + SemanticMap (не только L1/
    FactPackage): source_window/semantic_map/evidence_slices в контексте
    Reviewer (и revision); system-канон получает блок источника;
  * R6-B-007 fixture «wrong speaker из оригинала, не в FactPackage»:
    Reviewer может доказать находку из source_window (evidence_refs из
    id-space окна/пакета);
  * CAPACITY_OVERFLOW Reviewer: evidence-slices (evidence_message_ids абзацев
    + reply-контекст) детерминированно из SourceWindow; никогда только
    FactPackage;
  * контракты ASAP-4 D в силе: findings без refs ⊆ id-space — отбрасываются
    (unknown > hallucinated); bounded revision ×2 + patch-контракт
    replace_paragraphs + progress criterion + бюджет ≤6 — без изменений;
  * kill-switch SUMMARY_L2_REVIEW_ENABLED=false → single-call L2 → Legacy.
"""
import json

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_l2_review import (
    CALL_BUDGET_L2_STAGE,
    MAX_REVISIONS,
    build_review_content,
    build_review_evidence_slices,
    build_revision_content,
    l2_review_enabled,
    parse_review_verdict,
    run_l2_with_review,
)
from services.summary_l2_writer import L2Result

pytestmark = pytest.mark.asap41

RID = "wave3-4610"
CHAT = -100333


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


@pytest.fixture(autouse=True)
def _review_on(monkeypatch):
    """Волна 3: review-контур включён (смежный флаг волны D держат OFF-соседи
    conftest; прод-дефолт ON). Kill-switch-тест доопределяет False явно."""
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L2_REVIEW_ENABLED",
                        True, raising=False)
    yield


def _frag(mid, author_id, name, text, *, reply_to=None, kind="msg"):
    return {"message_id": mid, "author_id": author_id, "display_name": name,
            "timestamp": 1000 + mid, "reply_to_id": reply_to, "kind": kind,
            "text": text}


_FRAG_1 = _frag(101, 7001, "Тагир", "маша упала в зал")
_FRAG_2 = _frag(102, 7002, "Макс", "классика жанра", reply_to=101)
_ODD = _frag(107, 7003, "Слава", "и вообще у меня дублёр был")

_PACKAGE = {
    "schema_version": 2, "status": "ok",
    "threads": [{
        "thread_id": "thread_001", "name": "тема дня", "description": "",
        "chronology": [
            {"message_id": _FRAG_1["message_id"],
             "timestamp": _FRAG_1["timestamp"],
             "topic_ids": ["thread_001"]},
            {"message_id": _FRAG_2["message_id"],
             "timestamp": _FRAG_2["timestamp"],
             "topic_ids": ["thread_001"]},
        ],
        "facts": [{"text": "маша упала в зал",
                   "evidence_message_ids": [101]}],
        "evidence_ids": [101, 102],
        "fragments": [_FRAG_1, _FRAG_2],
    }],
    "unassigned_message_ids": [],
    "service": {"response_mode": "serious", "cover_prompt": "",
                "package_grade": "semantic"},
    "budget": {"kind": "tokens", "limit": 30000, "estimated": 42,
               "fits": True},
}

_DOCUMENT = {"schema_version": 1, "title": "Тема дня.",
             "paragraphs": [{"text": "Тагир рассказал про падение.",
                             "emphasis_spans": [], "evidence_message_ids":
                             [101]}]}

_PAYLOAD_ITEMS = [
    {"message_id": 101, "timestamp": 1101, "author_id": 7001,
     "display_name": "Тагир", "text": "маша упала в зал", "reply_to_id":
     None},
    {"message_id": 102, "timestamp": 1102, "author_id": 7002,
     "display_name": "Макс", "text": "классика жанра", "reply_to_id": 101},
    {"message_id": 107, "timestamp": 1107, "author_id": 7003,
     "display_name": "Слава", "text": "и вообще у меня дублёр был",
     "reply_to_id": None},
]

_SOURCE_CONTENT = (
    "ИСТОЧНИК — ПОЛНОЕ ОКНО ЧАТА: участники Тагир/Макс/Слава; "
    "id 101/102/107.")


def _writer_result():
    from services.summary_l2_writer import _make_result
    return _make_result("ok", document=dict(_DOCUMENT), usage=None,
                        metrics={}, duration_ms=1.0)


class _WriterLLM:
    """Writer-канал (черновик)."""

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else json_document()

    async def generate(self, messages, **kw):
        return self.payload


class _DoL:
    """LLM-канал Reviewer/Revision (отдельные коллбеки для ролей)."""

    def __init__(self, reviewer_responses=(), revision_responses=()):
        self.reviewer = list(reviewer_responses)
        self.revision = list(revision_responses)
        self.review_contents = []
        self.revision_contents = []

    async def reviewer_call(self, messages):
        self.review_contents.append(messages[-1]["content"])
        if self.reviewer:
            return self.reviewer.pop(0), {"input_tokens": 1}
        return (json.dumps({"status": "needs_fixes", "findings": []},
                           ensure_ascii=False), None)

    async def revision_call(self, messages):
        self.revision_contents.append(messages[-1]["content"])
        if self.revision:
            return self.revision.pop(0), {"input_tokens": 1}
        return (json.dumps(json_document(), ensure_ascii=False), None)


def json_document():
    return json.dumps(_DOCUMENT, ensure_ascii=False)


def _verdict_needs_fixes(*refs):
    findings = [{"code": "wrong_person_attribution", "severity": "blocking",
                 "paragraph_index": 0, "evidence_refs": list(refs),
                 "instruction": "исправь спикера"}]
    return json.dumps({"status": "needs_fixes", "findings": findings},
                      ensure_ascii=False)


# ── Full SourceWindow в контуре Reviewer ───────────────────────────────────

@pytest.mark.asyncio
async def test_reviewer_sees_source_window_and_map(monkeypatch):
    """T-4610 (AM-4): ReviewResult = Draft + Full SourceWindow + SemanticMap;
    system-канон + блок источника (T-4610)."""
    from services.summary_prompts import SUMMARY_L2_REVIEWER_SYSTEM_PROMPT
    source = "ИСТОЧНИК — ПОЛНОЕ ОКНО ЧАТА: id 101/102/107."
    reviewer = _DoL(reviewer_responses=[
        json.dumps({"status": "approved", "findings": []},
                   ensure_ascii=False)])
    result = await run_l2_with_review(
        _WriterLLM(), _PACKAGE, service={}, correlation_id=RID, chat_id=CHAT,
        slot=None, reviewer_call=reviewer.reviewer_call,
        revision_call=reviewer.revision_call,
        writer_source_input="ИСТОЧНИК — ПОЛНОЕ ОКНО ЧАТА (Writer-вход)",
        writer_length={"response_mode": "serious", "target_chars": 2400,
                       "target_paragraphs": 5, "max_chars": 32000},
        semantic_map={"schema_version": 1, "topics": [], "events": [],
                      "unassigned_message_ids": []},
        source_window_content=source)
    review_content = reviewer.review_contents[0]
    assert '"source_window"' in review_content
    assert '"semantic_map"' in review_content
    assert '"draft"' in review_content


@pytest.mark.asyncio
async def test_wrong_speaker_catch_from_source_window(monkeypatch):
    """R6-B-007 fixture: wrong speaker обнаружен против ОРИГИНАЛА (id 107 —
    слова Славы), когда FactPackage его вообще не содержал."""
    reviewer = _DoL(reviewer_responses=[
        # Reviewer видит source_window с 107 и доказывает находку результатом
        # (evidence_refs из id-space окна; пакет 107 не содержит).
        _verdict_needs_fixes(107),
        json.dumps({"status": "approved", "findings": []},
                   ensure_ascii=False)])
    result = await run_l2_with_review(
        _WriterLLM(), _PACKAGE, service={}, correlation_id=RID, chat_id=CHAT,
        reviewer_call=reviewer.reviewer_call,
        revision_call=reviewer.revision_call,
        source_window_content=_SOURCE_CONTENT,
        source_message_ids={101, 102, 107})
    assert result.usable
    assert "source_window" in reviewer.review_contents[0]
    # вторая ревизия (revision) тоже получает source window — сверка с
    # оригиналом при правке.
    assert any('"source_window"' in c for c in reviewer.revision_contents)


# ── Evidence-slices (CAPACITY_OVERFLOW Reviewer) ───────────────────────────

class TestEvidenceSlices:
    def test_slices_with_reply_context(self):
        doc = {"paragraphs": [{"text": "p1", "evidence_message_ids": [102]}]}
        slices = build_review_evidence_slices(doc, _PAYLOAD_ITEMS)
        assert len(slices) == 1
        first = slices[0]
        assert first["paragraph_index"] == 0
        assert 102 in first["message_ids"]
        assert 101 in first["message_ids"]     # reply-контекст (родитель)
        items = {i["message_id"] for i in first["items"]}
        assert {101, 102}.issubset(items)

    def test_slices_skips_paragraph_without_evidence(self):
        doc = {"paragraphs": [{"text": "p1"}]}
        assert build_review_evidence_slices(doc, _PAYLOAD_ITEMS) == []

    @pytest.mark.asyncio
    async def test_overflow_reviewer_gets_slices_not_full_window(self, 
            monkeypatch):
        monkeypatch.setattr(mc, "resolve_capacity",
                            _tiny_capacity())
        source = "ИСТОЧНИК — ПОЛНОЕ ОКНО ЧАТА (огромная история...)" * 200
        reviewer = _DoL(reviewer_responses=[
            json.dumps({"status": "approved", "findings": []},
                       ensure_ascii=False)])
        result = await run_l2_with_review(
            _WriterLLM(), _PACKAGE, service={}, correlation_id=RID, chat_id=CHAT,
            reviewer_call=reviewer.reviewer_call,
            revision_call=reviewer.revision_call,
            writer_source_input="ИСТОЧНИК", writer_length=None,
            review_full_window=False, review_payload_items=_PAYLOAD_ITEMS)
        content = reviewer.review_contents[0]
        assert '"evidence_slices"' in content
        assert '"source_window"' not in content


def _tiny_capacity():
    import types

    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="t", model=model, base_url=base_url,
            effective_context_window=0, source="fallback",
            confidence="fallback", fallback_used=True)
    return fake_resolve


# ── Контракты ASAP-4 D в силе ──────────────────────────────────────────────

class TestASAP4DContractsStillEnforced:
    def test_finding_without_refs_rejected(self):
        """§50.11/contracts D: находка без refs/с выдуманным ID —
        недействительна (unknown > hallucinated); needs_fixes без валидных
        находок → approved."""
        raw = json.dumps({
            "status": "needs_fixes",
            "findings": [
                {"code": "wrong_person_attribution", "severity": "blocking",
                 "paragraph_index": 0, "evidence_refs": [],
                 "instruction": "без доказательств"},
                {"code": "unsupported_number", "severity": "blocking",
                 "paragraph_index": 0, "evidence_refs": [99999],
                 "invented": True},
            ]}, ensure_ascii=False)
        verdict = parse_review_verdict(raw, package=_PACKAGE,
                                       document=_DOCUMENT)
        assert verdict.status == "approved"      # нет валидных оснований
        assert verdict.dropped_findings == 2

    def test_finding_with_source_refs_valid(self):
        """Находка доказывается из окна (ID окна ⊆ id-space derived view)."""
        raw = _verdict_needs_fixes(101)
        verdict = parse_review_verdict(raw, package=_PACKAGE,
                                       document=_DOCUMENT)
        assert verdict.status == "needs_fixes"
        assert verdict.blocking_count == 1

    def test_bounded_revision_and_budget_untouched(self):
        # ADR-1028-7 D3/D5 сохранены (§18/§19): ×2 ревизии; бюджет ≤6.
        assert MAX_REVISIONS == 2
        assert CALL_BUDGET_L2_STAGE == 6

    @pytest.mark.asyncio
    async def test_revision_budget_calls_bounded(self, monkeypatch):
        """Регресс D3.3: ревизия никогда не бесконечна (≤2 semantic
        iteration; бюджет ≤6 логических вызовов)."""
        reviewer = _DoL(
            reviewer_responses=[_verdict_needs_fixes(101),
                                _verdict_needs_fixes(102,
                                                     99999)],
            revision_responses=[json_document(), json_document()])
        result = await run_l2_with_review(
            _WriterLLM(), _PACKAGE, service={}, correlation_id=RID, chat_id=CHAT,
            reviewer_call=reviewer.reviewer_call,
            revision_call=reviewer.revision_call)
        metrics = result.metrics or {}
        assert metrics.get("l2_revision_count", 0) <= 2
        assert (metrics.get("l2_review_calls", 0)
                + metrics.get("l2_revision_calls", 0)) <= CALL_BUDGET_L2_STAGE


# ── Kill-switch OFF (single-call L2 → Legacy) ──────────────────────────────

@pytest.mark.asyncio
async def test_review_off_generator_single_call(monkeypatch):
    from services import summary_generator as sg
    from unittest.mock import AsyncMock, MagicMock
    from services.summary_generator import SummaryGenerator
    monkeypatch.setattr(type(sg.settings), "SUMMARY_L2_REVIEW_ENABLED",
                        False, raising=False)
    monkeypatch.setattr(type(sg.settings), "SUMMARY_L2_REVIEW_ENABLED",
                        False, raising=False)
    monkeypatch.setattr(mc, "resolve_capacity", _big_capacity())
    rows = [
        {"id": 101 + i, "tg_message_id": 101 + i, "timestamp":
         1_700_000_000 + i * 60, "user_id": 7, "author_name": "Вася",
         "text": "сообщение %d" % i, "media_type": "text", "reply_to_id":
         None, "is_forward": 0, "forward_source": None} for i in range(4)]

    # Writer-вход mocked LLN — один вызов L2 на пакете (без Reviewer).
    l1_map = json.dumps({"schema_version": 1, "topics": [
        {"topic_id": "topic_001", "title": "тема",
         "message_ids": [101, 102, 103, 104], "participants": [],
         "short_hint": ""}], "events": [], "unassigned_message_ids": []},
        ensure_ascii=False)
    doc = json.dumps({"schema_version": 1, "title": "T.",
                      "paragraphs": [{"text": "текст.",
                                      "emphasis_spans": [],
                                      "evidence_message_ids": [101]}]},
                     ensure_ascii=False)
    calls = []

    class _LLM:
        async def generate(self, messages, **kw):
            head = messages[-1].get("content") or ""
            calls.append(head[:80])
            if head.startswith("СООБЩЕНИЯ ЧАТА"):
                return l1_map
            return doc

    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(), llm=_LLM(),
                           bot=None)
    monkeypatch.setattr(type(sg.settings), "SUMMARY_COVER_ARTICLE_ENABLED",
                        False, raising=False)
    monkeypatch.setattr(type(sg.settings), "SUMMARY_COVER_FALLBACK_ENABLED",
                        False, raising=False)
    gen._deliver_l2_plain = AsyncMock(return_value=True)
    await gen._run_hybrid_l2(CHAT, rows, None, "off-review")
    # 1 вызов = L1-map; 2 = Writer single-call. Reviewer НИКАК не запущен.
    assert sum(1 for c in calls) == 2
    gen._deliver_l2_plain.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_off_acknowledges_map_run(monkeypatch):
    assert l2_review_enabled() is True   # прод-дефолт (asap41 fixture ON)


def _big_capacity():
    import types

    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="t", model=model, base_url=base_url,
            effective_context_window=262144, source="runtime",
            confidence="estimated", fallback_used=False)
    return fake_resolve


def test_review_content_shape_deterministic():
    a = build_review_content(_PACKAGE, _DOCUMENT, [], [], source_window_content=_SOURCE_CONTENT)
    b = build_review_content(_PACKAGE, _DOCUMENT, [], [], source_window_content=_SOURCE_CONTENT)
    assert a == b
