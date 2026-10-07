"""ASAP 5 (ADR-1028-25) — Summary-домен B1: T-5245…T-5247 + T-5267.

Покрывает design-freeze D2–D6 (spec §2):
  * D2 — server-owned таксономия FINDING_CODE_TAXONOMY (все 15 кодов,
    severity решает сервер по коду; unknown не blocking);
  * D3 — unusable server-gate: raw unusable terminal только с ≥2
    независимыми HARD findings или deterministic proof, иначе даунгрейд
    до needs_fixes (reason l2_unusable_gate в трейсе);
  * D4 — стагнация по fingerprint hard-finding
    (code+paragraph+sorted(refs)+target), бюджет ≤2 ревизий не растёт;
  * D5 — soft-only после bounded-цикла → degraded publish (не Legacy);
    hard unresolved → Legacy (fail-closed, INV-1);
  * D6 — Decision Trace сборщик витрины из существующих stage_events +
    final_policy (pipeline_analytics._decision_trace).
"""
import json

import pytest

from services.summary_l2_review import (
    CALL_BUDGET_L2_STAGE,
    FINDING_CODES,
    FINDING_CODE_DUPLICATE_EVENT,
    FINDING_CODE_MAJOR_TOPIC_OMITTED,
    FINDING_CODE_TAXONOMY,
    MAX_REVISIONS,
    REASON_L2_REVIEW_REJECTED,
    REASON_L2_REVIEW_UNUSABLE,
    REASON_L2_UNUSABLE_GATE,
    ReviewVerdict,
    _deterministic_findings_from_metrics,
    _deterministic_unusable_proof,
    _hard_fingerprints,
    _revalidate_metrics,
    _unusable_gate_accepts,
    finding_class,
    finding_severity,
    parse_review_verdict,
    run_l2_with_review,
)
from services.summary_l2_writer import L2Result, L2Slot

RID = "asap5-run-0001"
CHAT = -100267
SLOT = L2Slot("http://x", "m", "k", False)

# Loop-тесты идут с прод-дефолтами (review-флаги ON; conftest-изоляция
# не-asap4 тестов держит SUMMARY_L2_REVIEW_ENABLED=False).
pytestmark = pytest.mark.asap4


# ── Harness (тот же контракт, что test_summary_wave_d_asap4) ────────────────

def _frag(mid, author_id, name, text, reply_to=None, kind="message"):
    return {"message_id": mid, "author_id": author_id,
            "display_name": name, "timestamp": 1000 + mid,
            "reply_to_id": reply_to, "kind": kind, "text": text}


_DEF_FRAG_1 = _frag(101, 7001, "Тагир", "клиентка перепутала трубы")
_DEF_FRAG_2 = _frag(102, 7002, "Макс", "ну классика жанра", reply_to=101,
                    kind="reply")


def _package():
    return {
        "schema_version": 2, "status": "ok",
        "threads": [{
            "thread_id": "thread_001", "name": "тема дня",
            "description": "",
            "chronology": [
                {"message_id": f["message_id"], "timestamp": f["timestamp"],
                 "topic_ids": ["thread_001"]}
                for f in (_DEF_FRAG_1, _DEF_FRAG_2)],
            "facts": [
                {"text": "клиентка перепутала трубы",
                 "evidence_message_ids": [101]},
                {"text": "обсудили классику жанра",
                 "evidence_message_ids": [102]},
            ],
            "evidence_ids": [101, 102],
            "fragments": [_DEF_FRAG_1, _DEF_FRAG_2],
        }],
        "unassigned_message_ids": [],
        "service": {"response_mode": "serious", "cover_prompt": "",
                    "package_grade": "semantic"},
        "budget": {"kind": "tokens", "limit": 30000, "estimated": 42,
                   "fits": True},
    }


def _doc(*paragraphs):
    return {"schema_version": 1, "title": "Спор о трубах",
            "paragraphs": [{"text": t, "emphasis": None,
                            "emphasis_spans": [],
                            "evidence_message_ids": []}
                           for t in paragraphs]}


class WriterStub:
    def __init__(self, document):
        self.document = document
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        return json.dumps(self.document, ensure_ascii=False)


class StageStub:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses.pop(0)


def _verdict(status, findings=None):
    return json.dumps({"status": status, "findings": findings or []},
                      ensure_ascii=False)


def _finding(code, index=0, refs=(101,), severity="blocking",
             instruction="исправь"):
    return {"code": code, "severity": severity, "paragraph_index": index,
            "evidence_refs": list(refs), "instruction": instruction}


def _patch(index_text_map, refs=None):
    return json.dumps({"replace_paragraphs": [
        {"index": i, "text": t,
         "evidence_message_ids": list((refs or {}).get(i, [101]))}
        for i, t in index_text_map.items()]}, ensure_ascii=False)


class RunContextStub:
    def __init__(self):
        self.stage_events = []


async def _run(writer_doc, reviewer_responses, revision_responses,
               ctx=None):
    return await run_l2_with_review(
        None, _package(), slot=SLOT, reviewer_slot=SLOT,
        correlation_id=RID, chat_id=CHAT,
        llm_call=WriterStub(writer_doc), reviewer_call=StageStub(
            reviewer_responses),
        revision_call=StageStub(revision_responses), ctx=ctx)


# ══ D2 — server-owned таксономия ════════════════════════════════════════════

def test_taxonomy_covers_all_15_codes_exactly_once():
    """D2: каждый из 15 FINDING_CODES имеет ровно один класс; soft —
    ровно duplicate_event + major_topic_omitted (can_force_legacy=no);
    hard — can_force_legacy=yes; demote-механики в таксономии нет."""
    assert set(FINDING_CODE_TAXONOMY) == set(FINDING_CODES)
    assert len(FINDING_CODE_TAXONOMY) == 15
    soft = {FINDING_CODE_DUPLICATE_EVENT, FINDING_CODE_MAJOR_TOPIC_OMITTED}
    for code, entry in FINDING_CODE_TAXONOMY.items():
        assert entry["class"] in ("hard", "soft")
        if code in soft:
            assert entry["class"] == "soft"
            assert entry["can_force_legacy"] is False
        else:
            assert entry["class"] == "hard"
            assert entry["can_force_legacy"] is True


def test_severity_server_owned_model_advisory():
    """D2/§16#3: severity решает сервер по коду. Модельный «critical» на
    soft-коде НЕ поднимает blocking; модельный «minor» на hard-коде НЕ
    понижает; unknown-код вообще отбрасывается (не blocking)."""
    # модель говорит «критично» на soft-коде → minor (server wins)
    v = parse_review_verdict(_verdict("needs_fixes", [
        _finding(FINDING_CODE_DUPLICATE_EVENT, severity="критично")]),
        package=_package())
    assert v.findings[0].severity == "minor"
    assert v.blocking_count == 0
    # модель говорит «minor» на hard-коде → blocking (demote запрещён)
    v2 = parse_review_verdict(_verdict("needs_fixes", [
        _finding("unsupported_number", severity="minor")]),
        package=_package())
    assert v2.findings[0].severity == "blocking"
    assert v2.blocking_count == 1
    # unknown severity-мусор на hard-коде → blocking (не модель решает)
    v3 = parse_review_verdict(_verdict("needs_fixes", [
        _finding("invented_name", severity="что-то иное")]),
        package=_package())
    assert v3.findings[0].blocking is True


def test_unknown_code_dropped_never_blocking():
    """D2/§16#3: код вне словаря → dropped_invalid (существующий путь),
    никогда не blocking; needs_fixes без валидных findings → approved."""
    v = parse_review_verdict(_verdict("needs_fixes", [
        _finding("made_up_severity_bomb", severity="blocking")]),
        package=_package())
    assert v.findings == ()
    assert v.dropped_findings == 1
    assert v.status == "approved"


def test_hard_finding_fingerprint_shape():
    """D4: идентичность hard-finding = code+paragraph+sorted(refs)."""
    v = ReviewVerdict(status="needs_fixes", findings=(
        type("F", (), {"code": "unsupported_number",
                       "severity": "blocking", "paragraph_index": 2,
                       "evidence_refs": (103, 101),
                       "instruction": "", "blocking": True})(),))
    assert _hard_fingerprints(v) == {("unsupported_number", 2, (101, 103))}
    # soft-код не входит в fingerprint-набор
    v_soft = ReviewVerdict(status="needs_fixes", findings=(
        type("F", (), {"code": FINDING_CODE_DUPLICATE_EVENT,
                       "severity": "minor", "paragraph_index": 0,
                       "evidence_refs": (101,), "instruction": "",
                       "blocking": False})(),))
    assert _hard_fingerprints(v_soft) == frozenset()


# ══ D3 — unusable server-gate ═══════════════════════════════════════════════

def test_gate_units_deterministic_proof_and_independence():
    """(а) ≥2 независимых hard (разные коды И разные targets);
    (б) deterministic proof — ТОЛЬКО от живых unresolved-блокеров (W1-A):
    история УСПЕШНЫХ ремонтов (quote_reason_codes /
    quote_repair_reason_codes) proof'ом НЕ является. Одна находка/одна
    мишень/дублирующийся код — НЕ terminal."""
    # (а) passes: 2 кода × 2 абзаца
    v_ok = ReviewVerdict(status="unusable", findings=(
        type("F", (), {"code": "unsupported_number", "paragraph_index": 0,
                       "evidence_refs": (101,), "blocking": True})(),
        type("F", (), {"code": "invented_name", "paragraph_index": 1,
                       "evidence_refs": (102,), "blocking": True})(),))
    assert _unusable_gate_accepts(v_ok, {}) is True
    # (а) fails: 2 hard, но ОДИН paragraph target
    v_same_target = ReviewVerdict(status="unusable", findings=(
        type("F", (), {"code": "unsupported_number", "paragraph_index": 0,
                       "evidence_refs": (101,), "blocking": True})(),
        type("F", (), {"code": "invented_name", "paragraph_index": 0,
                       "evidence_refs": (102,), "blocking": True})(),))
    assert _unusable_gate_accepts(v_same_target, {}) is False
    # (а) fails: единственная hard находка
    v_one = ReviewVerdict(status="unusable", findings=(
        type("F", (), {"code": "unsupported_number", "paragraph_index": 0,
                       "evidence_refs": (101,), "blocking": True})(),))
    assert _unusable_gate_accepts(v_one, {}) is False
    # (б) W1-A: ремонт-история НЕ proof — успешно отремонтированная цитата
    # не отправляет валидный документ в Legacy.
    repaired_metrics = {
        "quote_repair_reason_codes": ["quote_speaker_mismatch",
                                      "quote_attribution_repaired"],
        "quote_unresolved_blockers": [],
        "quote_reason_codes": ["quote_speaker_mismatch",
                               "quote_attribution_repaired"],
    }
    assert _deterministic_unusable_proof(repaired_metrics) is False
    assert _unusable_gate_accepts(
        ReviewVerdict(status="unusable", findings=()),
        repaired_metrics) is False
    # непустой quote_reason_codes из ремонтов сам по себе — тоже НЕ proof
    assert _deterministic_unusable_proof(
        {"quote_reason_codes": ["quote_text_not_found",
                                "quote_attribution_repaired"]}) is False
    # (б) живой неустранённый блокер → proof (hard safety не ослаблен)
    assert _deterministic_unusable_proof(
        {"quote_unresolved_blockers": ["quote_text_not_found"]}) is True
    assert _deterministic_unusable_proof({}) is False
    assert _unusable_gate_accepts(
        ReviewVerdict(status="unusable", findings=()),
        {"quote_unresolved_blockers": ["quote_speaker_mismatch"]}) is True
    # soft findings не считаются evidence-квотой
    v_soft = ReviewVerdict(status="unusable", findings=(
        type("F", (), {"code": FINDING_CODE_DUPLICATE_EVENT,
                       "paragraph_index": 0, "evidence_refs": (101,),
                       "blocking": False})(),
        type("F", (), {"code": FINDING_CODE_MAJOR_TOPIC_OMITTED,
                       "paragraph_index": 1, "evidence_refs": (102,),
                       "blocking": False})(),))
    assert _unusable_gate_accepts(v_soft, {}) is False


@pytest.mark.asyncio
async def test_repaired_quote_history_not_legacy_on_raw_unusable():
    """W1-A (RED на старом коде): usable-документ с одной УСПЕШНО
    отремонтированной цитатой (repair-история попадает в
    quote_reason_codes) + raw unusable вердикт ревьюера → НЕ Legacy:
    deterministic proof от ремонт-истории не считается, гейт даунгрейдит
    до needs_fixes → 0 findings → degraded publish, документ выживает."""
    doc = _doc('Лёха: "клиентка перепутала трубы".', "Тема закрылась.")
    res = await _run(doc, [_verdict("unusable")], [])
    assert res.usable is True
    assert res.invalid_reason is None
    # цитата действительно была отремонтирована (история ремонтов не пуста)
    assert res.metrics.get("quotes_repaired") == 1
    assert "quote_attribution_repaired" in (
        res.metrics.get("quote_reason_codes") or [])
    assert res.metrics.get("quote_unresolved_blockers") == []
    assert res.metrics.get("l2_legacy_after_review", 0) == 0
    assert res.metrics.get("l2_unusable_gate_downgrades") == 1
    assert res.metrics.get("l2_review_degraded") == 1
    assert res.metrics.get("l2_review_degraded_reason") == \
        REASON_L2_UNUSABLE_GATE


@pytest.mark.asyncio
async def test_unresolved_blocker_is_deterministic_proof_terminal(monkeypatch):
    """W1-A (RED на старом коде): живой неустранённый блокер
    (quote_unresolved_blockers — future-proof: валидатор перестал
    reject'ить документ с проблемой) → deterministic proof работает:
    raw unusable → terminal Legacy (hard safety сохранён)."""
    import services.summary_l2_review as rev

    async def _writer_with_blocker(llm, package, **kwargs):
        return L2Result(
            status="ok", document=_doc("Пункт один.", "Пункт два."),
            invalid_reason=None, usage=None,
            metrics={"quote_unresolved_blockers": ["quote_text_not_found"]},
            duration_ms=0.0)

    monkeypatch.setattr(rev, "_writer_call", _writer_with_blocker)
    res = await _run(_doc("Пункт один.", "Пункт два."),
                     [_verdict("unusable")], [])
    assert res.usable is False
    assert res.invalid_reason == REASON_L2_REVIEW_UNUSABLE
    assert res.metrics.get("l2_unusable_gate") == 1
    assert res.metrics.get("l2_legacy_after_review") == 1


def test_deterministic_findings_exclude_repair_history():
    """W1-A: ревьюер НЕ получает историю ремонтов (в т.ч.
    quote_attribution_repaired, которого нет в FINDING_CODES) как
    deterministic findings; только живые unresolved-блокеры."""
    history = _deterministic_findings_from_metrics({
        "quote_reason_codes": ["quote_speaker_mismatch",
                               "quote_attribution_repaired"],
        "quote_repair_reason_codes": ["quote_speaker_mismatch",
                                      "quote_attribution_repaired"],
        "quote_unresolved_blockers": [],
    })
    assert [f["code"] for f in history] == []
    blocker = _deterministic_findings_from_metrics({
        "quote_reason_codes": ["quote_text_not_found",
                               "quote_attribution_repaired"],
        "quote_repair_reason_codes": ["quote_text_not_found",
                                      "quote_attribution_repaired"],
        "quote_unresolved_blockers": ["quote_text_not_found"],
    })
    assert [f["code"] for f in blocker] == ["quote_text_not_found"]


def test_revalidate_metrics_failure_keeps_last_known_metrics(monkeypatch):
    """W1-A: исключение пересчёта НЕ стирает deterministic proof молча —
    возвращаются последние известные metrics (fallback) + warning."""
    import services.summary_l2_review as rev

    def _boom(document, package):
        raise RuntimeError("revalidate boom")

    monkeypatch.setattr(rev, "validate_l2_document", _boom)
    last = {"quote_unresolved_blockers": ["quote_text_not_found"],
            "quote_reason_codes": ["quote_text_not_found"]}
    out = rev._revalidate_metrics({}, {}, anchor_mode=False, anchor_map=None,
                                  fallback=last)
    assert out.get("quote_unresolved_blockers") == ["quote_text_not_found"]
    # без fallback поведение прежнее defensive: пустой dict, не исключение
    assert rev._revalidate_metrics({}, {}, anchor_mode=False, anchor_map=None,
                                   fallback=None) == {}


@pytest.mark.asyncio
async def test_unusable_without_evidence_downgraded_not_legacy():
    """§16#5 (RED на старом коде: raw unusable → Legacy немедленно):
    unusable без findings и без deterministic proof → даунгрейд до
    needs_fixes → ремонта нет (0 findings) → deterministic-валидный
    черновик публикуется degraded, а НЕ выбрасывается в Legacy."""
    res = await _run(_doc("Абзац один.", "Абзац два."),
                     [_verdict("unusable")], [])
    assert res.usable is True
    assert res.invalid_reason is None
    assert res.metrics.get("l2_review_degraded") == 1
    assert res.metrics.get("l2_unusable_gate_downgrades") == 1
    assert res.metrics.get("l2_legacy_after_review", 0) == 0
    # reason гейта виден в metrics-диагностике
    assert res.metrics.get("l2_review_degraded_reason") == "l2_unusable_gate"


@pytest.mark.asyncio
async def test_unusable_gate_downgrade_goes_to_bounded_repair():
    """D3: unusable с одной hard-находкой → даунгрейд (не terminal) →
    findings идут в bounded repair → после ремонта approved."""
    doc = _doc("Абзац один.", "Абзац два.")
    res = await _run(doc, [
        _verdict("unusable", [_finding("unsupported_number", index=0)]),
        _verdict("approved"),
    ], [_patch({0: "Исправленный абзац один."})])
    assert res.usable is True
    assert res.invalid_reason is None
    assert res.metrics.get("l2_unusable_gate_downgrades") == 1
    assert res.metrics.get("l2_revision_count") == 1
    assert res.metrics.get("l2_final_approved") == 1


@pytest.mark.asyncio
async def test_unusable_with_two_independent_hard_findings_terminal():
    """§16#6: подтверждённая HARD corruption (2 независимые находки)
    проходит гейт → Legacy немедленно, без ревизий (fail-closed)."""
    res = await _run(_doc("Абзац один.", "Абзац два."), [
        _verdict("unusable", [
            _finding("unsupported_number", index=0),
            _finding("invented_name", index=1, refs=(102,))]),
    ], [])
    assert res.usable is False
    assert res.invalid_reason == REASON_L2_REVIEW_UNUSABLE
    assert res.metrics.get("l2_legacy_after_review") == 1
    assert res.metrics.get("l2_unusable_gate") == 1


# ══ D4 — стагнация по fingerprint ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_stagnation_same_fingerprint_breaks_without_rev2():
    """§16#9 (RED на старом коде только по причине; count-критерий дал бы
    тот же break): тот же hard-fingerprint после repair → break с
    reason l2_stagnation_fingerprint, ревизия #2 не вызывается."""
    ctx = RunContextStub()
    res = await _run(_doc("Абзац один.", "Абзац два."), [
        _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
        _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
    ], [_patch({0: "Исправленный абзац один."})], ctx=ctx)
    assert res.usable is False
    assert res.invalid_reason == REASON_L2_REVIEW_REJECTED
    assert res.metrics.get("l2_stagnation_fingerprint") == 1
    # ревизия ровно одна (бюджет не сгорает в повторных попытках)
    assert res.metrics.get("l2_revision_count") == 1
    stagnated = [e for e in ctx.stage_events
                 if e.get("reason_code") == "l2_stagnation_fingerprint"]
    assert stagnated, "стагнация должна быть видна в stage_events трейсе"


@pytest.mark.asyncio
async def test_old_fixed_plus_new_found_is_progress_not_stagnation():
    """§16#8 (RED на старом коде: count 1>=1 → break без rev2):
    старая находка исправлена + найдена новая = ПРОГРЕСС по fingerprint
    → bounded repair продолжается (ревизия #2 в рамках ≤2)."""
    res = await _run(_doc("Абзац один.", "Абзац два."), [
        _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
        _verdict("needs_fixes", [
            _finding("invented_name", index=1, refs=(102,))]),
        _verdict("approved"),
    ], [_patch({0: "Исправленный абзац один."}),
        _patch({1: "Исправленный абзац два."}, refs={1: [102]})])
    assert res.usable is True
    assert res.invalid_reason is None
    assert res.metrics.get("l2_revision_count") == 2
    assert res.metrics.get("l2_final_approved") == 1
    assert res.metrics.get("l2_stagnation_fingerprint", 0) == 0


@pytest.mark.asyncio
async def test_budget_ceiling_not_increased():
    """§4.5/INV-2: fingerprint-механика не увеличивает число LLM-циклов
    (потолок ≤6 вызовов стадии и ≤2 ревизий закреплён)."""
    doc = _doc("Абзац один.", "Абзац два.")
    reviewer = StageStub([
        _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
        _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
    ])
    revision = StageStub([_patch({0: "Исправленный абзац один."})])
    res = await run_l2_with_review(
        None, _package(), slot=SLOT, reviewer_slot=SLOT,
        correlation_id=RID, chat_id=CHAT, llm_call=WriterStub(doc),
        reviewer_call=reviewer, revision_call=revision)
    m = res.metrics
    assert m["l2_revision_calls"] <= MAX_REVISIONS
    assert 1 + m["l2_review_calls"] + m["l2_revision_calls"] \
        <= CALL_BUDGET_L2_STAGE


# ══ D5 — soft-only → degraded publish; hard → Legacy ════════════════════════

@pytest.mark.asyncio
async def test_soft_only_after_cycle_publishes_degraded_not_legacy():
    """§16#4 (RED на старом коде: любой needs_fixes → REJECTED → Legacy):
    soft-only набор после исчерпания bounded-цикла → документ
    (deterministic-валиден) публикуется degraded, а не выбрасывается."""
    res = await _run(_doc("Абзац один.", "Абзац два."), [
        _verdict("needs_fixes", [
            _finding(FINDING_CODE_DUPLICATE_EVENT, index=0)]),
        _verdict("needs_fixes", [
            _finding(FINDING_CODE_DUPLICATE_EVENT, index=0)]),
    ], [_patch({0: "Исправленный абзац один."})])
    assert res.usable is True
    assert res.invalid_reason is None
    assert res.metrics.get("l2_review_degraded") == 1
    assert res.metrics.get("l2_legacy_after_review", 0) == 0
    assert res.document["paragraphs"][0]["text"] == \
        "Исправленный абзац один."


@pytest.mark.asyncio
async def test_hard_unresolved_after_cycle_still_fail_closed():
    """§16#6 (INV-1): hard-находка не ушла после bounded repair →
    Legacy (REASON_L2_REVIEW_REJECTED) — fail-closed не ослаблен."""
    res = await _run(_doc("Абзац один.", "Абзац два."), [
        _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
        _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
    ], [_patch({0: "Исправленный абзац один."})])
    assert res.usable is False
    assert res.invalid_reason == REASON_L2_REVIEW_REJECTED
    assert res.metrics.get("l2_legacy_after_review") == 1


@pytest.mark.asyncio
async def test_reviewer_outage_still_publishes_degraded():
    """§16#10: reviewer outage при deterministic-валидном черновике →
    degraded publish (существующая fail-soft механика сохранена)."""
    res = await _run(_doc("Абзац один."), ["не json"], [])
    assert res.usable is True
    assert res.metrics.get("l2_review_degraded") == 1


# ══ D6 — Decision Trace сборщик (pipeline_analytics) ════════════════════════

def test_decision_trace_builds_five_sections_from_existing_events():
    """D6: трасса собирается из существующих stage_events (snapshot) +
    durable stage-строк (final_policy) — без новых LLM-вызовов."""
    from services.pipeline_analytics import _decision_trace
    snapshot = {"stage_events": [
        {"stage": "l2_reviewer", "attempt": 1, "status": "needs_fixes",
         "verdict": "needs_fixes", "finding_codes": ["unsupported_number"],
         "blocking_count": 1, "paragraph_ids": [0]},
        {"stage": "revision", "attempt": 1, "status": "ok",
         "repair_target": "patch", "revision_result": "ok"},
        {"stage": "revision", "attempt": 2, "status": "stagnated",
         "reason_code": "l2_stagnation_fingerprint",
         "revision_result": "ok"},
    ]}
    rows = [
        {"stage": "l1", "status": "degraded_map_fallback",
         "reason_code": "semantic_map_unavailable"},
        {"stage": "l2", "status": "ok", "reason_code": None},
        {"stage": "l2_review", "status": "failed",
         "reason_code": "l2_review_rejected"},
        {"stage": "final_policy", "status": "LEGACY_FALLBACK",
         "reason_code": "l2_review_rejected"},
    ]
    trace = _decision_trace(snapshot, rows)
    assert trace is not None
    assert trace["l1"]["status"] == "degraded_map_fallback"
    assert trace["writer"]["status"] == "ok"
    assert len(trace["review_iterations"]) == 1
    assert trace["review_iterations"][0]["finding_codes"] == \
        ["unsupported_number"]
    assert len(trace["revision_iterations"]) == 2
    assert trace["revision_iterations"][1]["reason_code"] == \
        "l2_stagnation_fingerprint"
    assert trace["final_policy"]["status"] == "LEGACY_FALLBACK"
    assert trace["final_policy"]["reason_code"] == "l2_review_rejected"


def test_decision_trace_none_without_data():
    from services.pipeline_analytics import _decision_trace
    assert _decision_trace({}, []) is None


# ══ D1 — L1 трёхуровневая семантика в витрине (Inspector) ═══════════════════

def _ev(name, outcome=None, status=None, reason_code=None, usage=None):
    return {"event_name": name, "outcome": outcome, "status": status,
            "reason_code": reason_code,
            "usage_json": json.dumps(usage or {}) if usage else None}


def test_inspector_l1_degraded_distinct_from_terminal():
    """§16#1-2: L1 failed + Writer-стадия была → degraded_map_fallback
    (Writer продолжил от полного окна/fallback package); L1 failed без
    Writer'а → failed_terminal. Красный крест — только terminal."""
    from services.pipeline_analytics import build_run_view
    base_events = [
        _ev("SUMMARY_L1_STAGE", outcome="failed", status="failed",
            reason_code="parse_error", usage={"threads": 0}),
    ]
    # terminal: Writer не стартовал
    view = build_run_view("r1", {}, list(base_events))
    assert view["coverage_breakdown"]["l1"]["result"] == "failed_terminal"
    l1_node = next(n for n in view["nodes"] if n["key"] == "l1")
    assert l1_node["state"] == "failed"
    # degraded: Writer продолжил (L2-событие есть)
    events = base_events + [
        _ev("SUMMARY_L2_STAGE", outcome="success", status="ok",
            usage={"output_count": 9}),
    ]
    view2 = build_run_view("r2", {}, events)
    br = view2["coverage_breakdown"]
    assert br["l1"]["result"] == "degraded_map_fallback"
    l1_node2 = next(n for n in view2["nodes"] if n["key"] == "l1")
    assert l1_node2["state"] == "fallback"
    assert l1_node2["state"] != "failed"
    # любой detail поясняет продолжение Writer'а
    assert any("Writer" in str(d.get("v") or "") or
               "писатель" in str(d.get("v") or "").lower()
               for d in l1_node2["detail"])


def test_inspector_writer_done_on_reviewer_rejection():
    """D5: reviewer-rejection не превращает Writer в «не выполнено» —
    документ написан; отказ на узле Проверки."""
    from services.pipeline_analytics import build_run_view
    events = [
        _ev("SUMMARY_L1_STAGE", outcome="success", status="ok",
            usage={"threads": 3}),
        _ev("SUMMARY_L2_STAGE", outcome="failed", status="failed",
            reason_code="l2_review_rejected", usage={"output_count": 9}),
        _ev("SUMMARY_L2_REVIEW", status="failed",
            reason_code="l2_review_rejected"),
    ]
    view = build_run_view("r3", {}, events)
    writer = next(n for n in view["nodes"] if n["key"] == "l2")
    assert writer["state"] != "failed"
    review = next(n for n in view["nodes"] if n["key"] == "l2_review")
    assert review["state"] == "fallback"


def test_reason_ru_honest_unusable_text():
    """D5: RU-текст l2_review_unusable описывает Reviewer semantic
    unusable, а не parse-failure писателя; новые коды витрины переведены."""
    from services.pipeline_analytics import REASONS_RU, reason_ru
    text = REASONS_RU.get("l2_review_unusable") or ""
    assert "писателя не удалось" not in text
    assert "eviewer" in text or "роверк" in text
    assert reason_ru("l2_unusable_gate")
    assert reason_ru("l2_stagnation_fingerprint")
