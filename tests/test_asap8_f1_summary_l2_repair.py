"""ASAP 8 F1 — Summary L2 validator reliability (ТЗ §2, §19 S1–S4).

S1:  L2 paragraph 950 chars -> deterministic sentence split -> Hybrid
     survives (не Legacy).
S2:  пустой paragraph среди валидных -> удалить только пустой -> publish
     Hybrid.
S3:  invented evidence -> НЕ превращается в факт, fail-closed сохранён.
S4:  Analytics отличает attempted_invalid от not_run.

Плюс: гранулярная reason-модель (P0-S1), РОВНО ОДИН correction attempt
(§2.4), reason_group обратной совместимости, R17 (текст абзаца — никогда),
anchor-path alignment (rework REV-F1: split/drop не смещают source_anchors).

TEST-LIFECYCLE: CONTRACT owner=ASAP8/F1
Запуск: pytest tests/test_asap8_f1_summary_l2_repair.py
"""
from __future__ import annotations

import json

import pytest

from services.summary_l2_repair import (
    DOCUMENT_NO_PARAGRAPHS,
    PARAGRAPH_BAD_TYPE,
    PARAGRAPH_EMPTY,
    PARAGRAPH_EMPTY_AFTER_CLEANUP,
    PARAGRAPH_TOO_LONG,
    REASON_GROUPS,
    detect_paragraph_defects,
    is_correctionable,
    post_repair_reason,
    reason_group,
    repair_document,
)
from services.summary_l2_writer import (
    REASON_INVALID_EVIDENCE,
    REASON_INVALID_PARAGRAPH,
    REASON_TOO_MANY_PARAGRAPHS,
    STATUS_INVALID,
    STATUS_OK,
    run_l2,
    validate_l2_document,
)


# ── Фикстуры (id-space пакета: {101, 102, 103}) ─────────────────────────────

def _package(status: str = "ok") -> dict:
    return {
        "schema_version": 2,
        "status": status,
        "threads": [{
            "thread_id": "thread_001",
            "name": "Погода и планы",
            "description": "Обсуждали дождь и поездку.",
            "chronology": [
                {"message_id": 101, "timestamp": 1000,
                 "topic_ids": ["thread_001"]},
                {"message_id": 102, "timestamp": 1001,
                 "topic_ids": ["thread_001"]},
            ],
            "facts": [
                {"text": "На улице шёл сильный дождь",
                 "evidence_message_ids": [101]},
            ],
            "evidence_ids": [101, 102],
            "fragments": [
                {"message_id": 101, "author_id": 7001,
                 "display_name": "Вася", "timestamp": 1000,
                 "reply_to_id": None, "text": "На улице шёл сильный дождь"},
                {"message_id": 102, "author_id": 7002,
                 "display_name": "Петя", "timestamp": 1001,
                 "reply_to_id": 101, "text": "Поездку решили перенести"},
            ],
        }],
        "unassigned_message_ids": [103],
        "service": {"response_mode": "serious", "cover_prompt": "rain"},
        "budget": {"kind": "tokens", "limit": 30000, "estimated": 42,
                   "fits": True},
    }


def _long_paragraph() -> str:
    """Много-предложенческий абзац 900+ символов (S1)."""
    sentence = "В чате обсудили погоду, планы на выходные и поездку. "
    return (sentence * 18).strip()          # ~952 символа, ≥5 предложений


def _doc(paragraphs, title: str = "Дождливый день") -> dict:
    return {"schema_version": 1, "title": title, "paragraphs": paragraphs}


class ScriptedLLM:
    """Очередь ответов; пишет messages каждой попытки (проверка correction)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.messages_seen: list = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.messages_seen.append(messages)
        return self.responses.pop(0)


class _SlotStub:
    base_url = "https://api.test"
    model = "l2-model"
    api_key = "secret-key-xyz"
    dedicated = False


# ── Гранулярная детекция (P0-S1) ────────────────────────────────────────────

class TestDetect:
    def test_too_long_detected_with_chars(self):
        text = _long_paragraph()
        defects = detect_paragraph_defects(_doc([{"text": text}]), _package())
        codes = [d.code for d in defects]
        assert PARAGRAPH_TOO_LONG in codes
        too_long = next(d for d in defects if d.code == PARAGRAPH_TOO_LONG)
        assert too_long.index == 0
        assert too_long.chars == len(text)

    def test_empty_paragraph_and_document_level(self):
        defects = detect_paragraph_defects(
            _doc([{"text": "   "}, {"text": "Нормальный абзац."}]),
            _package())
        assert [d.code for d in defects] == [PARAGRAPH_EMPTY]

    def test_all_empty_flags_document_no_paragraphs(self):
        defects = detect_paragraph_defects(
            _doc([{"text": ""}, {"text": "fact:101 msg:102"}]), _package())
        codes = {d.code for d in defects}
        assert codes == {PARAGRAPH_EMPTY, PARAGRAPH_EMPTY_AFTER_CLEANUP,
                         DOCUMENT_NO_PARAGRAPHS}
        doc_level = next(d for d in defects
                         if d.code == DOCUMENT_NO_PARAGRAPHS)
        assert doc_level.index == -1

    def test_empty_list_document_no_paragraphs(self):
        defects = detect_paragraph_defects(_doc([]), _package())
        assert [d.code for d in defects] == [DOCUMENT_NO_PARAGRAPHS]

    def test_bad_type_text(self):
        defects = detect_paragraph_defects(
            _doc([{"text": 123}]), _package())
        assert [d.code for d in defects] == [PARAGRAPH_BAD_TYPE]

    def test_clean_paragraph_no_defects(self):
        defects = detect_paragraph_defects(
            _doc([{"text": "В чате обсудили погоду и планы."}]), _package())
        assert defects == []

    def test_no_repair_for_invented_evidence_s3(self):
        """S3 (unit): invented refs не ремонтируются — ни один repair-механизм
        не «домывает» evidence вне id-space пакета."""
        doc = _doc([{"text": "Абзац.",
                     "evidence_message_ids": [101, 999999]}])
        defects = detect_paragraph_defects(doc, _package())
        assert defects == []          # paragraph-дефектов нет
        repaired, actions = repair_document(doc, _package())
        assert repaired is None and actions == []
        canonical, metrics = validate_l2_document(doc, _package())
        assert canonical is None
        assert metrics["reason"] == REASON_INVALID_EVIDENCE
        assert metrics["reason_group"] == "invalid_evidence"


# ── Deterministic repair ────────────────────────────────────────────────────

class TestRepair:
    def test_split_preserves_all_text_s1_unit(self):
        text = _long_paragraph()
        doc = _doc([{"text": text, "emphasis": None,
                     "evidence_message_ids": [101]}])
        repaired, actions = repair_document(doc, _package())
        assert repaired is not None
        parts = [p["text"] for p in repaired["paragraphs"]]
        assert len(parts) >= 2
        # весь текст сохранён (не trim): склейка частей = исходный текст
        assert " ".join(parts) == text
        # части влезают в лимит, refs наследуются (shared evidence)
        assert all(len(p) <= 900 for p in parts)
        assert all(p.get("evidence_message_ids") == [101]
                   for p in repaired["paragraphs"])
        assert actions and actions[0]["action"] == "split_paragraph"
        assert actions[0]["parts"] == len(parts)

    def test_drop_only_empty_paragraph_s2_unit(self):
        doc = _doc([{"text": "Первый абзац."},
                    {"text": "   "},
                    {"text": "Третий абзац."}])
        repaired, actions = repair_document(doc, _package())
        texts = [p["text"] for p in repaired["paragraphs"]]
        assert texts == ["Первый абзац.", "Третий абзац."]
        assert actions == [{"action": "drop_paragraph",
                            "code": PARAGRAPH_EMPTY, "index": 1}]

    def test_single_sentence_over_limit_not_split_no_trim(self):
        """§28.2: >900 chars просто trim — ЗАПРЕЩЕНО; одиночное предложение
        остаётся как есть (correctionable), текст не теряется."""
        text = "х" * 950
        repaired, actions = repair_document(
            _doc([{"text": text}]), _package())
        assert repaired is not None
        assert repaired["paragraphs"][0]["text"] == text
        assert actions[0]["action"] == "split_skipped_single_sentence"

    def test_all_empty_returns_none_document_no_paragraphs(self):
        repaired, actions = repair_document(
            _doc([{"text": ""}, {"text": "msg:101"}]), _package())
        assert repaired is None
        reason = post_repair_reason(
            detect_paragraph_defects(_doc([{"text": ""}]), _package()),
            actions)
        assert reason == DOCUMENT_NO_PARAGRAPHS

    def test_input_not_mutated(self):
        doc = _doc([{"text": _long_paragraph()}, {"text": ""}])
        import copy
        snapshot = copy.deepcopy(doc)
        repair_document(doc, _package())
        assert doc == snapshot


# ── Валидатор: repair внутри канонизации ────────────────────────────────────

class TestValidateWithRepair:
    def test_s1_validator_repairs_too_long(self):
        canonical, metrics = validate_l2_document(
            _doc([{"text": _long_paragraph(), "emphasis": None}]),
            _package())
        assert canonical is not None
        assert metrics["status"] == STATUS_OK
        assert metrics["paragraphs_count"] >= 2
        assert any(a["action"] == "split_paragraph"
                   for a in metrics["repair_actions"])
        assert metrics["repairs_applied"] == 1
        assert metrics["reason"] == "ok"

    def test_s2_validator_drops_empty_keeps_rest(self):
        canonical, metrics = validate_l2_document(
            _doc([{"text": "Первый абзац."},
                  {"text": "  "},
                  {"text": "Третий абзац."}]),
            _package())
        assert canonical is not None
        texts = [p["text"] for p in canonical["paragraphs"]]
        assert texts == ["Первый абзац.", "Третий абзац."]
        assert metrics["repair_actions"] == [
            {"action": "drop_paragraph", "code": PARAGRAPH_EMPTY, "index": 1}]

    def test_granular_reason_single_sentence_over_limit(self):
        canonical, metrics = validate_l2_document(
            _doc([{"text": "х" * 950}]), _package())
        assert canonical is None
        # umbrella НЕ потерян: reason_group == invalid_paragraph (совместимость)
        assert metrics["reason"] == PARAGRAPH_TOO_LONG
        assert metrics["reason_group"] == REASON_INVALID_PARAGRAPH
        assert metrics["reason_code"] == PARAGRAPH_TOO_LONG
        assert metrics["paragraph_index"] == 0
        assert metrics["chars"] == 950

    def test_granular_reason_document_no_paragraphs(self):
        canonical, metrics = validate_l2_document(_doc([]), _package())
        assert canonical is None
        assert metrics["reason"] == DOCUMENT_NO_PARAGRAPHS
        assert metrics["reason_group"] == REASON_INVALID_PARAGRAPH
        assert is_correctionable(metrics["reason"])

    def test_granular_reason_empty_after_cleanup(self):
        canonical, metrics = validate_l2_document(
            _doc([{"text": "Первый."},
                  {"text": "fact:101 msg:102 [12.3456|"},
                  {"text": "Третий."}]),
            _package())
        assert canonical is not None
        texts = [p["text"] for p in canonical["paragraphs"]]
        assert texts == ["Первый.", "Третий."]
        assert metrics["repair_actions"][0]["code"] \
            == PARAGRAPH_EMPTY_AFTER_CLEANUP

    def test_s3_invalid_evidence_fail_closed_not_repaired(self):
        doc = _doc([{"text": _long_paragraph(),
                     "evidence_message_ids": [101, 424242]}])
        canonical, metrics = validate_l2_document(doc, _package())
        # Разбивка repair-абзаца применена, НО invented evidence ловит
        # revalidate — документ отвергнут целиком, факт из вымысла не
        # создан (fail-closed, S3).
        assert canonical is None
        assert metrics["reason"] == REASON_INVALID_EVIDENCE
        assert metrics["reason_group"] == "invalid_evidence"
        # ремонт коснулся только too_long-абзаца; evidence-ссылки ремонт
        # не модифицировал (в actions — только split, без refs вообще)
        assert [(a["action"], a["index"])
                for a in metrics["repair_actions"]] == [("split_paragraph", 0)]
        assert all("evidence_message_ids" not in a
                   for a in metrics["repair_actions"])

    def test_repair_then_invalid_evidence_still_fail_closed(self):
        """Порядок repair → validate: repair чинит абзацы, но invented
        evidence ловит revalidate — факт из вымысла не создаётся."""
        doc = _doc([{"text": _long_paragraph(), "emphasis": None},
                    {"text": "Нормальный.",
                     "evidence_message_ids": [777]}])
        canonical, metrics = validate_l2_document(doc, _package())
        assert canonical is None
        assert metrics["reason"] == REASON_INVALID_EVIDENCE


# ── reason-модель: группы обратной совместимости ────────────────────────────

class TestReasonGroups:
    def test_paragraph_codes_map_to_invalid_paragraph(self):
        for code in (PARAGRAPH_BAD_TYPE, PARAGRAPH_EMPTY, PARAGRAPH_TOO_LONG,
                     PARAGRAPH_EMPTY_AFTER_CLEANUP, DOCUMENT_NO_PARAGRAPHS,
                     "invalid_paragraph"):
            assert reason_group(code) == "invalid_paragraph"

    def test_fail_closed_codes_keep_own_groups(self):
        assert reason_group("invalid_evidence") == "invalid_evidence"
        assert reason_group("quote_attribution") == "quote_attribution"
        assert reason_group("invalid_json") == "structural"
        assert reason_group("too_long") == "structural"
        assert reason_group("что-то новое") == "structural"

    def test_correctionable_matrix(self):
        assert is_correctionable(DOCUMENT_NO_PARAGRAPHS)
        assert is_correctionable(PARAGRAPH_TOO_LONG)
        assert is_correctionable("invalid_evidence")
        assert is_correctionable("quote_attribution")
        assert is_correctionable("invalid_json")
        assert not is_correctionable(REASON_TOO_MANY_PARAGRAPHS)
        assert not is_correctionable("too_long")
        assert not is_correctionable("llm_error")
        assert set(REASON_GROUPS)  # словарь не пуст


# ── S1/S2 через run_l2: Hybrid выживает (не Legacy) ─────────────────────────

class TestRunL2HybridSurvives:
    @pytest.mark.asyncio
    async def test_s1_long_paragraph_split_hybrid_survives(self):
        llm = ScriptedLLM([json.dumps(
            _doc([{"text": _long_paragraph(), "emphasis": None}]),
            ensure_ascii=False)])
        result = await run_l2(llm, _package(), slot=_SlotStub(),
                              correlation_id="s1", chat_id=-100)
        assert result.usable, result.invalid_reason
        assert result.status == STATUS_OK
        assert len(result.document["paragraphs"]) >= 2
        # deterministic repair бесплатен: РОВНО 1 вызов L2, без correction
        assert llm.calls == 1
        assert result.metrics["l2_calls"] == 1
        assert result.metrics["correction_used"] is False

    @pytest.mark.asyncio
    async def test_s2_empty_paragraph_dropped_publishes_hybrid(self):
        llm = ScriptedLLM([json.dumps(
            _doc([{"text": "Первый абзац."},
                  {"text": ""},
                  {"text": "Третий абзац."}]),
            ensure_ascii=False)])
        result = await run_l2(llm, _package(), slot=_SlotStub(),
                              correlation_id="s2", chat_id=-100)
        assert result.usable, result.invalid_reason
        texts = [p["text"] for p in result.document["paragraphs"]]
        assert texts == ["Первый абзац.", "Третий абзац."]
        assert llm.calls == 1

    @pytest.mark.asyncio
    async def test_s3_invented_evidence_not_published(self):
        """S3: invented evidence — fail-closed (документ не публикуется),
        correction-попытка не «домывает» ссылку."""
        llm = ScriptedLLM([
            json.dumps(_doc([{"text": "Абзац один.",
                              "evidence_message_ids": [101, 555555]}]),
                       ensure_ascii=False),
            json.dumps(_doc([{"text": "Абзац один.",
                              "evidence_message_ids": [101, 555555]}]),
                       ensure_ascii=False),
        ])
        result = await run_l2(llm, _package(), slot=_SlotStub(),
                              correlation_id="s3", chat_id=-100)
        assert not result.usable
        assert result.status == STATUS_INVALID
        assert result.invalid_reason == REASON_INVALID_EVIDENCE
        # РОВНО ОДИН correction attempt (attempt + correction = 2)
        assert llm.calls == 2
        assert result.metrics["correction_used"] is True
        assert result.metrics["l2_calls"] == 2
        assert result.document is None


# ── РОВНО ОДИН correction attempt (§2.4) ────────────────────────────────────

class TestCorrectionAttempt:
    @pytest.mark.asyncio
    async def test_correction_recovers_document(self):
        """Post-repair остаток (одиночное предложение >900) → ровно один
        correction → валидный документ публикуется."""
        bad = _doc([{"text": "х" * 950}])
        good = _doc([{"text": "Первый абзац."},
                     {"text": "Второй абзац."}])
        llm = ScriptedLLM([
            json.dumps(bad, ensure_ascii=False),
            json.dumps(good, ensure_ascii=False),
        ])
        result = await run_l2(llm, _package(), slot=_SlotStub(),
                              correlation_id="corr1", chat_id=-100)
        assert result.usable
        assert llm.calls == 2
        assert result.metrics["l2_calls"] == 2
        assert result.metrics["correction_used"] is True
        # machine reason в user-контенте correction-попытки (R17: код/числа)
        correction_user = llm.messages_seen[1][1]["content"]
        assert "paragraph_too_long" in correction_user
        assert "paragraph_index: 0" in correction_user
        assert "х" * 50 not in correction_user      # текст абзаца — НИКОГДА

    @pytest.mark.asyncio
    async def test_correction_fails_closed_after_one_attempt(self):
        bad = json.dumps(_doc([{"text": "х" * 950}]), ensure_ascii=False)
        llm = ScriptedLLM([bad, bad])
        result = await run_l2(llm, _package(), slot=_SlotStub(),
                              correlation_id="corr2", chat_id=-100)
        assert not result.usable
        assert llm.calls == 2                        # без циклов
        assert result.invalid_reason == PARAGRAPH_TOO_LONG
        assert result.metrics["l2_calls"] == 2

    @pytest.mark.asyncio
    async def test_no_correction_for_structural_rejects(self):
        """too_many_paragraphs / LLMError — НЕ correctionable: ровно 1 вызов."""
        paragraphs = [{"text": f"Абзац {i}.", "emphasis": None}
                      for i in range(499)]
        llm = ScriptedLLM([json.dumps(_doc(paragraphs=paragraphs),
                                      ensure_ascii=False)])
        result = await run_l2(llm, _package(), slot=_SlotStub())
        assert result.status == STATUS_INVALID
        assert result.invalid_reason == REASON_TOO_MANY_PARAGRAPHS
        assert llm.calls == 1
        assert result.metrics["l2_calls"] == 1
        assert result.metrics["correction_used"] is False

    @pytest.mark.asyncio
    async def test_correction_transport_error_fail_closed_first_reason(self):
        from services.llm_client import LLMError

        class FailSecond:
            calls = 0

            async def generate(self, messages, **kwargs):
                FailSecond.calls += 1
                if FailSecond.calls == 1:
                    return json.dumps(_doc([{"text": "х" * 950}]),
                                      ensure_ascii=False)
                raise LLMError("correction transport boom")

        result = await run_l2(FailSecond(), _package(), slot=_SlotStub())
        assert not result.usable
        assert FailSecond.calls == 2
        assert result.invalid_reason == PARAGRAPH_TOO_LONG
        assert result.metrics["correction_used"] is True


# ── S4: attempted_invalid ≠ not_run (телеметрия + Analytics) ────────────────

def _ev(name, outcome=None, status=None, reason_code=None, usage=None):
    import json as _json
    return {"event_name": name, "outcome": outcome, "status": status,
            "reason_code": reason_code,
            "usage_json": _json.dumps(usage) if usage else None}


class TestS4AttemptedInvalid:
    def test_l2_stage_event_carries_granular_fields(self, monkeypatch):
        """SUMMARY_L2_STAGE: honest status=attempted_invalid + granular
        counts (reason_code/paragraph_index/chars/l2_calls/correction_used/
        repair_actions; текст абзаца — НИКОГДА)."""
        from services import pipeline_events
        captured = {}

        def _fake_emit(event_name, **kwargs):
            captured["event_name"] = event_name
            captured.update(kwargs)

        monkeypatch.setattr(pipeline_events, "_emit", _fake_emit)
        pipeline_events.l2_stage(
            "run-s4", chat_id=-100, usable=False,
            invalid_reason=PARAGRAPH_TOO_LONG,
            duration_ms=1234.0, paragraphs=0,
            status=STATUS_INVALID,
            metrics={"reason_code": PARAGRAPH_TOO_LONG,
                     "reason_group": "invalid_paragraph",
                     "paragraph_index": 2, "chars": 950,
                     "l2_calls": 2, "correction_used": True,
                     "repair_actions": [{"action": "split_paragraph",
                                         "code": PARAGRAPH_TOO_LONG,
                                         "index": 2, "parts": 1}]})
        assert captured["event_name"] == "SUMMARY_L2_STAGE"
        # transport enum: outcome=failed, honest-исход в status
        assert captured["outcome"] == "failed"
        assert captured["status"] == "attempted_invalid"
        counts = captured["counts"]
        assert counts["reason_code"] == PARAGRAPH_TOO_LONG
        assert counts["reason_group"] == "invalid_paragraph"
        assert counts["paragraph_index"] == 2
        assert counts["chars"] == 950
        assert counts["l2_calls"] == 2
        assert counts["correction_used"] is True
        assert counts["repair_actions"][0]["action"] == "split_paragraph"

    def test_durable_stage_status_mapping(self):
        from services.summary_l2_writer import L2Result
        from services.summary_generator import _l2_durable_status

        ok = L2Result(status="ok", document={}, invalid_reason=None,
                      usage=None, metrics={}, duration_ms=0.0)
        reviewer_reject = L2Result(
            status="invalid", document=None,
            invalid_reason="l2_review_rejected", usage=None, metrics={},
            duration_ms=0.0)
        validator_invalid = L2Result(
            status="invalid", document=None,
            invalid_reason=PARAGRAPH_TOO_LONG, usage=None, metrics={},
            duration_ms=0.0)
        transport = L2Result(status="error", document=None,
                             invalid_reason="llm_error", usage=None,
                             metrics={}, duration_ms=0.0)
        assert _l2_durable_status(ok) == "ok"
        assert _l2_durable_status(reviewer_reject) == "ok"
        assert _l2_durable_status(validator_invalid) == "attempted_invalid"
        assert _l2_durable_status(transport) == "failed"

    def test_analytics_distinguishes_attempted_invalid_from_not_run(self):
        """S4: attempted_invalid виден как отдельный honest-исход (узел L2,
        ось L2 accepted), а не «не выполнено» и не отсутствие стадии."""
        from services.pipeline_analytics import (
            STATE_FAILED,
            STATE_SUCCESS,
            _classify,
            build_run_view,
        )
        usage = {"coverage": 100.0, "source_total": 865,
                 "source_considered": 865}
        events = [
            _ev("SUMMARY_SOURCE_WINDOW", outcome="success",
                usage={"input_count": 865}),
            _ev("SUMMARY_L1_STAGE", outcome="success", status="ok",
                usage={"threads": 12}),
            _ev("SUMMARY_L2_STAGE", outcome="failed",
                status="attempted_invalid",
                reason_code=None,
                usage={"output_count": 0, "stage_status": "attempted_invalid",
                       "reason_code": PARAGRAPH_TOO_LONG,
                       "reason_group": "invalid_paragraph",
                       "paragraph_index": 3, "chars": 950,
                       "l2_calls": 2, "correction_used": True,
                       "repair_actions": [{"action":
                                           "split_skipped_single_sentence",
                                           "index": 3}]}),
            _ev("SUMMARY_RUN_DONE", outcome="success", status="ok",
                usage=usage),
        ]
        view = build_run_view("run-s4", {}, events)
        # узел L2: honest «выполнено, отвергнуто валидатором»
        writer = next(n for n in view["nodes"] if n["key"] == "l2")
        assert writer["state"] == STATE_FAILED
        assert any("отвергнуто валидатором" in str(d.get("v") or "")
                   for d in writer["detail"])
        assert any("paragraph_too_long" in str(d.get("v") or "")
                   for d in writer["detail"])
        # ось L2 accepted: отвергнут, не ok и не отсутствует
        breakdown = view["coverage_breakdown"]
        assert breakdown["l2_accepted"]["result"] == "attempted_invalid"
        assert breakdown["l2_accepted"]["accepted"] == 0
        assert breakdown["l2_accepted"]["reason_code"] == PARAGRAPH_TOO_LONG
        assert breakdown["l2_accepted"]["correction_used"] is True
        # Final-ось (Legacy-overwrite) живёт отдельно
        assert breakdown["final"]["total"] == 865
        # not_run: без L2-события оси l2_accepted и узла нет
        view_not_run = build_run_view("run-s4-empty", {}, [])
        not_run_breakdown = view_not_run["coverage_breakdown"] or {}
        assert "l2_accepted" not in not_run_breakdown
        assert not [n for n in view_not_run["nodes"] if n["key"] == "l2"]

    def test_classify_counts_attempted_invalid_as_failed_node(self):
        from services.pipeline_analytics import (
            STATE_FAILED,
            STATE_SUCCESS,
            _classify,
        )
        group, state = _classify("SUMMARY_L2_STAGE", {
            "outcome": "failed", "status": "attempted_invalid"})
        assert group == "l2"
        assert state == STATE_FAILED
        group, state = _classify("SUMMARY_L2_STAGE", {
            "outcome": "success", "status": "ok"})
        assert state == STATE_SUCCESS


# ── Золотая совместимость: обычные статьи не затронуты ──────────────────────

class TestGoldenCompatibility:
    @pytest.mark.asyncio
    async def test_valid_document_single_call_no_repair_noise(self):
        llm = ScriptedLLM([json.dumps(
            _doc([{"text": "В чате обсудили погоду и планы.",
                   "emphasis": None}]), ensure_ascii=False)])
        result = await run_l2(llm, _package(), slot=_SlotStub())
        assert result.usable
        assert llm.calls == 1
        assert result.metrics["repair_actions"] == []
        assert result.metrics["repairs_applied"] == 0
        assert result.metrics["correction_used"] is False

    def test_structural_rejects_untouched(self):
        bad = _doc([{"text": "ок", "x": 1}])          # unknown field
        canonical, metrics = validate_l2_document(bad, _package())
        assert canonical is None
        assert metrics["reason"] == "unknown_field"
        assert metrics.get("repair_actions") is None


# ── REV-F1 rework: anchor-path alignment ────────────────────────────────────
# Прод-дефолт — anchor-space L2 (SUMMARY_SOURCE_ANCHORS_ENABLED +
# SUMMARY_L2_EVIDENCE_REPAIR_ENABLED): validate_l2_document_anchors
# пробрасывает source_anchors из repaired_paras в канонические абзацы.
# F1-repair меняет число абзацев (split/drop) — без проекции zip молча
# терял текст и смещал якоря. Здесь: split-части наследуют якоря исходника,
# drop исключает якоря, любой рассинхрон — fail-closed.

_CHAT_ID = -100777


def _anchor_flag(monkeypatch, name, value):
    import config.settings as _cs
    import services.summary_l2_writer as _wr
    from config.settings import Settings
    for _cls in {Settings, type(_cs.settings), type(_wr.settings)}:
        monkeypatch.setattr(_cls, name, value, raising=False)


@pytest.fixture()
def _anchor_env(monkeypatch):
    """Anchor-space ON для L2 (review-модуль не участвует: run_l2 напрямую)."""
    _anchor_flag(monkeypatch, "SUMMARY_SOURCE_ANCHORS_ENABLED", True)
    _anchor_flag(monkeypatch, "SUMMARY_L2_EVIDENCE_REPAIR_ENABLED", True)


def _anchor_rows(count, *, start=101):
    return [
        {"id": start + i, "tg_message_id": start + i,
         "user_id": 10 + (i % 3), "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} и немного продолжения мысли ",
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


def _anchor_map(count=3):
    from services.summary_source_anchors import build_anchor_map
    from services.summary_source_window import build_source_window
    window = build_source_window("f1-anchor-run", _CHAT_ID,
                                 _anchor_rows(count))
    am = build_anchor_map(window)
    return am, [e.anchor for e in am.entries]


class _Writer:
    def __init__(self, document):
        self.document = document

    async def __call__(self, messages):
        return json.dumps(self.document, ensure_ascii=False)


def _anchor_package():
    return {
        "schema_version": 2, "status": "ok",
        "threads": [{"thread_id": "t", "name": "T", "description": "",
                     "chronology": [], "facts": [], "fragments": []}],
        "service": {"response_mode": "serious", "cover_prompt": ""},
        "unassigned_message_ids": [],
    }


class TestAnchorRepairAlignment:
    """Anchor-путь: repair не смещает source_anchors и не теряет текст
    (REGRESSION REV-F1: zip(canonical, repaired_paras) после split/drop)."""

    @pytest.mark.asyncio
    async def test_anchor_split_publishes_all_parts_with_source_anchors(
            self, _anchor_env):
        """Probe (a): too_long абзац (2+ предложений) → split: опубликованы
        ВСЕ части, склейка == исходный текст, якоря частей = якоря исходного
        абзаца (shared evidence), соседние абзацы не смещены."""
        from services.summary_l2_writer import L2Slot, run_l2
        am, anchors = _anchor_map(3)
        long_text = _long_paragraph()
        doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
            {"text": "Первый абзац.", "source_anchors": [anchors[0]]},
            {"text": long_text, "source_anchors": [anchors[1]]},
            {"text": "Третий абзац.", "source_anchors": [anchors[2]]},
        ]}
        slot = L2Slot("http://x", "m", "k", False)
        res = await run_l2(None, _anchor_package(), slot=slot,
                           llm_call=_Writer(doc), anchor_map=am)
        assert res.usable, res.invalid_reason
        assert res.metrics.get("evidence_anchor_space") == 1
        paras = res.document["paragraphs"]
        texts = [p["text"] for p in paras]
        # ВСЕ части опубликованы: 1 + 2 части split + 1 (не 3 с потерей)
        assert len(texts) == 4, texts
        assert " ".join(texts[1:3]) == long_text          # текст без потерь
        assert paras[0]["text"] == "Первый абзац."
        assert paras[3]["text"] == "Третий абзац."
        # якоря: части split наследуют якоря исходного абзаца; сосед — свой
        assert paras[0]["source_anchors"] == [anchors[0]]
        assert paras[1]["source_anchors"] == [anchors[1]]
        assert paras[2]["source_anchors"] == [anchors[1]]
        assert paras[3]["source_anchors"] == [anchors[2]]

    @pytest.mark.asyncio
    async def test_anchor_drop_empty_does_not_shift_anchors(
            self, _anchor_env):
        """Probe (b): [paraA(m0000), пустой(m0001), paraC(m0002)] → пустой
        удалён, paraC несёт СВОЙ якорь m0002 (не смещённый m0001)."""
        from services.summary_l2_writer import L2Slot, run_l2
        am, anchors = _anchor_map(3)
        doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
            {"text": "Абзац А.", "source_anchors": [anchors[0]]},
            {"text": "   ", "source_anchors": [anchors[1]]},
            {"text": "Абзац C.", "source_anchors": [anchors[2]]},
        ]}
        slot = L2Slot("http://x", "m", "k", False)
        res = await run_l2(None, _anchor_package(), slot=slot,
                           llm_call=_Writer(doc), anchor_map=am)
        assert res.usable, res.invalid_reason
        paras = res.document["paragraphs"]
        assert [p["text"] for p in paras] == ["Абзац А.", "Абзац C."]
        assert paras[0]["source_anchors"] == [anchors[0]]
        assert paras[1]["source_anchors"] == [anchors[2]]   # НЕ anchors[1]

    @pytest.mark.asyncio
    async def test_anchor_alignment_mismatch_fails_closed(self, _anchor_env,
                                                          monkeypatch):
        """Защита: любой рассинхрон проекции repair с канонизацией →
        fail-closed (документ со смещёнными якорями не публикуется)."""
        from services import summary_l2_writer as wr
        am, anchors = _anchor_map(3)
        doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
            {"text": "Абзац А.", "source_anchors": [anchors[0]]},
            {"text": "Абзац Б.", "source_anchors": [anchors[1]]},
        ]}
        # сломанная проекция (имитация внутреннего бага) → рассинхрон длин
        monkeypatch.setattr(wr, "_repair_projection",
                            lambda *a, **k: [(0, "split", 5)])
        slot = wr.L2Slot("http://x", "m", "k", False)
        res = await wr.run_l2(None, _anchor_package(), slot=slot,
                              llm_call=_Writer(doc), anchor_map=am)
        assert not res.usable
        assert res.status == STATUS_INVALID
        assert res.document is None
        assert res.invalid_reason == "internal_error"

    @pytest.mark.asyncio
    async def test_anchor_identity_document_unchanged(self, _anchor_env):
        """Без repairable-дефектов anchor-путь байт-в-байт прежний
        (совместимость существующих wiring-тестов)."""
        from services.summary_l2_writer import L2Slot, run_l2
        am, anchors = _anchor_map(2)
        doc = {"schema_version": 1, "title": "Статья", "paragraphs": [
            {"text": "P0.", "source_anchors": [anchors[0], "mZZZZ-99"]},
            {"text": "P1.", "source_anchors": [anchors[1]]},
        ]}
        slot = L2Slot("http://x", "m", "k", False)
        res = await run_l2(None, _anchor_package(), slot=slot,
                           llm_call=_Writer(doc), anchor_map=am)
        assert res.usable
        assert res.document["paragraphs"][0]["source_anchors"] == [anchors[0]]
        assert res.document["paragraphs"][0]["text"] == "P0."
        assert res.document["paragraphs"][1]["source_anchors"] == [anchors[1]]
        assert res.metrics["invalid_refs_repaired"] == 1
        assert res.metrics["evidence_anchor_space"] == 1
