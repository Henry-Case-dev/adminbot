"""FCT-S4-EVIDENCE-VERDICT, U2 — вердикт и технический статус (28.11.2026).

Контракт: `plans/features/fc-trust-01/evidence/fct-s4-design-2026-11-28/s4-design.md`
(§2.1–§2.4, §4/U2) + decisions D1–D8 (D3 — `execution_status` на
`CheckedVerdict`, вычисляется оркестратором).

Проверяется наблюдаемое поведение:
* ложный верхний `mixed` из одностороннего PARTIAL невозможен (P0, FCT-193);
  CONFLICTING остаётся `mixed`;
* `execution_status`/`execution_cause`/`proof_basis` — отдельная ось,
  техническая причина не схлопывается в «недостаточно данных»;
* подтверждённые части при `partial` сохраняются;
* legacy RAG-контекст идёт типизированным `<chat_context>`, не сырым
  префиксом и не в `<search_results>`/`<evidence>` (FCT-315).
"""
from __future__ import annotations

import dataclasses
import types

import pytest

from config.settings import settings
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_service as fsvc
from services import temporal_factcheck as tf

CHAT_ID = -100777


# ── helpers ─────────────────────────────────────────────────────────────────

def _claim(text="Индекс S&P 500 упал на 2,1%.", claim_id="c1",
           **kwargs) -> fsp.ClaimUnit:
    return fsp.ClaimUnit(claim_id=claim_id, text=text, **kwargs)


def _coverage(claim, *, outcome, detail="", role="supports",
              evidence_id="ev-1") -> fsp.ClaimCoverage:
    ev = fsp.ClaimEvidence(
        claim_id=claim.claim_id, evidence_id=evidence_id,
        url="https://example.org/a", role=role, strength="direct",
        opened=True, basis=("entity",), snippet_only=False, independent=True,
        published_at_source="page", date_status="known")
    return fsp.ClaimCoverage(
        claim=claim, search_status="source_read", status_detail=detail,
        outcome=outcome, reason_code="", gap_note="", evidence=(ev,),
        citation_ids=(evidence_id,))


def _verdict(parts=(), factual="insufficient_evidence") -> tf.TemporalVerdict:
    return tf.TemporalVerdict(
        factual_verdict=factual, temporal_status="unknown",
        evaluated_period={}, assessment_mode="data_only", as_of=0,
        parts=tuple(parts))


def _retrieval(**kwargs) -> fsp.RetrievalOutcome:
    base = dict(evidence_map=None, search_text="", queries_attempted=1,
                queries_used=0, refs_collected=0, fetch_errors=0,
                budget_exhausted=False)
    base.update(kwargs)
    return fsp.RetrievalOutcome(**base)


# ── P0: PARTIAL ≠ mixed (FCT-193 / FC-04.5) ────────────────────────────────

class TestPartialIsNotMixed:

    def test_partial_maps_to_insufficient_not_mixed(self):
        assert fsp.CLAIM_OUTCOME_TO_VERDICT[fsp.CLAIM_OUTCOME_PARTIAL] == \
            "insufficient_evidence"
        assert fsp.CLAIM_OUTCOME_TO_VERDICT[fsp.CLAIM_OUTCOME_CONFLICTING] == \
            "mixed"

    def test_one_sided_partial_does_not_produce_top_mixed(self):
        """PARTIAL = supports/qualifies БЕЗ contradicts → не «обе стороны»."""
        claim = _claim()
        cov = _coverage(claim, outcome=fsp.CLAIM_OUTCOME_PARTIAL,
                        role="supports", detail="partial")
        merged = fsvc.merge_claim_coverage(_verdict(), (cov,), ())
        assert merged.factual_verdict == "insufficient_evidence"
        assert merged.factual_verdict != "mixed"
        assert all(p.get("factual_verdict") != "mixed"
                   for p in merged.parts if isinstance(p, dict))

    def test_qualifies_only_partial_is_insufficient(self):
        claim = _claim()
        cov = _coverage(claim, outcome=fsp.CLAIM_OUTCOME_PARTIAL,
                        role="qualifies", detail="partial")
        merged = fsvc.merge_claim_coverage(_verdict(), (cov,), ())
        assert merged.factual_verdict == "insufficient_evidence"

    def test_conflicting_partial_evidence_is_mixed(self):
        claim = _claim()
        cov = dataclasses.replace(
            _coverage(claim, outcome=fsp.CLAIM_OUTCOME_CONFLICTING,
                      detail="evidence_conflicting"),
            evidence=(
                fsp.ClaimEvidence(claim_id="c1", evidence_id="ev-1",
                                  url="https://example.org/a", role="supports",
                                  strength="direct", opened=True,
                                  basis=("entity",), snippet_only=False),
                fsp.ClaimEvidence(claim_id="c1", evidence_id="ev-2",
                                  url="https://example.org/b",
                                  role="contradicts", strength="direct",
                                  opened=True, basis=("entity",),
                                  snippet_only=False)),
            citation_ids=("ev-1", "ev-2"))
        merged = fsvc.merge_claim_coverage(
            _verdict(factual="mixed"), (cov,), ())
        assert merged.factual_verdict == "mixed"
        assert any(p.get("factual_verdict") == "mixed"
                   for p in merged.parts if isinstance(p, dict))

    def test_negative_control_old_mapping_recreates_false_mixed(self,
                                                               monkeypatch):
        """Мутация «вернуть PARTIAL→mixed» обязана ломать контракт.

        Модель сказала supported, а evidence односторонний partial: при старом
        маппинге серверная часть становится `mixed` и агрегатор выдаёт ложный
        верхний `mixed`; при текущем — часть `insufficient`, верхний mixed
        невозможен."""
        claim = _claim()
        cov = _coverage(claim, outcome=fsp.CLAIM_OUTCOME_PARTIAL,
                        role="supports", detail="partial")
        old = dict(fsp.CLAIM_OUTCOME_TO_VERDICT)
        old[fsp.CLAIM_OUTCOME_PARTIAL] = "mixed"
        model_verdict = _verdict(factual="supported")
        # старый маппинг → ложный mixed
        monkeypatch.setattr(fsp, "CLAIM_OUTCOME_TO_VERDICT", old)
        broken = fsvc.merge_claim_coverage(model_verdict, (cov,), ())
        assert broken.factual_verdict == "mixed"
        # текущий маппинг → mixed нет, часть честно insufficient
        monkeypatch.undo()
        fixed = fsvc.merge_claim_coverage(model_verdict, (cov,), ())
        assert fixed.factual_verdict != "mixed"
        assert all(p.get("factual_verdict") != "mixed"
                   for p in fixed.parts if isinstance(p, dict))


# ── execution_status / execution_cause / proof_basis (FCT-601/603/305) ─────

class TestExecutionStatus:

    def test_closed_axes(self):
        assert set(orch.EXECUTION_STATUSES) == {
            "complete", "partial", "technical_unverified", "unknown"}
        assert set(orch.EXECUTION_CAUSES) <= {
            "provider_error", "provider_timeout", "rate_limit",
            "deadline_exceeded", "resource_limit", "source_unreadable",
            "source_extract_failed", "cancelled", "claim_unidentified"}

    def test_all_substantive_is_complete(self):
        claims = (
            _coverage(_claim(claim_id="c1"),
                      outcome=fsp.CLAIM_OUTCOME_CONFIRMED),
            _coverage(_claim("Второй тезис.", claim_id="c2"),
                      outcome=fsp.CLAIM_OUTCOME_INSUFFICIENT, role="qualifies"),
        )
        status, cause, basis = orch.derive_execution_state(
            retrieval=_retrieval(), claims=claims)
        assert status == orch.EXECUTION_COMPLETE
        assert cause == ""
        assert basis == "evidence"

    def test_checked_and_technical_is_partial(self):
        claims = (
            _coverage(_claim(claim_id="c1"),
                      outcome=fsp.CLAIM_OUTCOME_CONFIRMED),
            _coverage(_claim("Не проверено.", claim_id="c2"),
                      outcome=fsp.CLAIM_OUTCOME_TECHNICAL,
                      detail="rate_limit"),
        )
        status, cause, _basis = orch.derive_execution_state(
            retrieval=_retrieval(), claims=claims)
        assert status == orch.EXECUTION_PARTIAL
        assert cause == "rate_limit"

    def test_only_technical_is_technical_unverified_with_exact_cause(self):
        claims = (
            _coverage(_claim(claim_id="c1"),
                      outcome=fsp.CLAIM_OUTCOME_TECHNICAL,
                      detail="rate_limit"),
        )
        status, cause, _basis = orch.derive_execution_state(
            retrieval=_retrieval(), claims=claims)
        assert status == orch.EXECUTION_TECHNICAL_UNVERIFIED
        # причина не схлопывается в «недоступность провайдера»/дедлайн
        assert cause == "rate_limit"
        assert cause != "provider_unavailable"
        assert cause != "deadline_exceeded"

    def test_resource_limit_cause_is_not_deadline(self):
        claims = (_coverage(_claim(), outcome=fsp.CLAIM_OUTCOME_TECHNICAL,
                            detail="resource_limit"),)
        status, cause, _ = orch.derive_execution_state(
            retrieval=_retrieval(), claims=claims)
        assert status == orch.EXECUTION_TECHNICAL_UNVERIFIED
        assert cause == "resource_limit"
        assert cause != "deadline_exceeded"

    def test_global_deadline_cause_preserved(self):
        claims = (_coverage(_claim(), outcome=fsp.CLAIM_OUTCOME_TECHNICAL,
                            detail="deadline_exceeded"),)
        _, cause, _ = orch.derive_execution_state(
            retrieval=_retrieval(), claims=claims)
        assert cause == "deadline_exceeded"

    def test_provider_down_without_parts_is_technical_unverified(self):
        status, cause, _ = orch.derive_execution_state(
            retrieval=_retrieval(stop_reason="providers_unavailable",
                                 provider_failures=2),
            claims=(), parts=())
        assert status == orch.EXECUTION_TECHNICAL_UNVERIFIED
        assert cause == "provider_error"

    def test_cancelled_run_cause(self):
        status, cause, _ = orch.derive_execution_state(
            retrieval=_retrieval(stop_reason="cancelled", cancelled=True),
            claims=(), parts=())
        assert status == orch.EXECUTION_TECHNICAL_UNVERIFIED
        assert cause == "cancelled"

    def test_no_retrieval_and_no_parts_is_unknown(self):
        status, cause, _ = orch.derive_execution_state(
            retrieval=None, claims=(), parts=())
        assert status == orch.EXECUTION_UNKNOWN
        assert cause == ""

    def test_proof_basis_logical_from_existing_basis_marker(self):
        status, cause, basis = orch.derive_execution_state(
            retrieval=_retrieval(),
            claims=(_coverage(_claim(), outcome=fsp.CLAIM_OUTCOME_CONFIRMED),),
            uncertainty={"basis_calculation": "5%"})
        assert basis == "logical"
        assert status == orch.EXECUTION_COMPLETE


class TestExecutionFieldsWiring:
    """Поля реально доезжают до CheckedVerdict обеих веток (D3)."""

    @pytest.mark.asyncio
    async def test_envelope_branch_sets_fields_and_keeps_parts(self):
        claim = _claim()
        cov_ok = _coverage(claim, outcome=fsp.CLAIM_OUTCOME_CONFIRMED)
        cov_tech = _coverage(_claim("Не проверено.", claim_id="c2"),
                             outcome=fsp.CLAIM_OUTCOME_TECHNICAL,
                             detail="rate_limit")
        parts = ({"part_id": "c1", "text": claim.text,
                  "factual_verdict": "supported", "evidence_refs": ["ev-1"]},)
        run = types.SimpleNamespace(
            verdict_text="вывод",
            verdict=tf.TemporalVerdict(
                factual_verdict="supported", temporal_status="current",
                evaluated_period={}, assessment_mode="data_only", as_of=0,
                parts=parts),
            evidence_rows=(), fallback_used=False)

        class _Svc:
            async def check_claim_envelope(self, envelope, **kw):
                return run

        tf_stub = types.SimpleNamespace(
            record_temporal_run=_async_noop)
        verdict = await orch._run_envelope_branch(
            types.SimpleNamespace(chat_id=CHAT_ID), _Svc(), db=None, bot=None,
            envelope=object(), feed="", tf=tf_stub, mca_gates=None,
            retrieval=_retrieval(claims=(cov_ok, cov_tech)))
        assert verdict.execution_status == orch.EXECUTION_PARTIAL
        assert verdict.execution_cause == "rate_limit"
        assert verdict.proof_basis == "evidence"
        # подтверждённая часть сохранена
        assert verdict.parts[0]["factual_verdict"] == "supported"

    @pytest.mark.asyncio
    async def test_legacy_branch_sets_fields(self):
        class _Svc:
            async def check_claim(self, *a, **kw):
                return "legacy текст"

        verdict = await orch._run_legacy_branch(
            types.SimpleNamespace(chat_id=CHAT_ID, target_text="тезис",
                                  user_hint=None, forward_source=None),
            _Svc(), "", retrieval=_retrieval(
                claims=(_coverage(_claim(), outcome=(
                    fsp.CLAIM_OUTCOME_TECHNICAL)),)))
        assert verdict.route == "legacy_single"
        assert verdict.execution_status == \
            orch.EXECUTION_TECHNICAL_UNVERIFIED
        assert verdict.execution_cause  # причина установлена


async def _async_noop(*args, **kwargs):
    return None


# ── FCT-504: envelope с датой и без даты — одна доказательная логика ───────

class _VerdictLLM:
    """Минимальный фейк: Analyst JSON → validator agree → текст."""

    def __init__(self, verdict: dict):
        self.verdict = verdict

    async def generate(self, messages, **kw):
        import json
        step = kw.get("step")
        if step in ("temporal_verdict", "temporal_fallback"):
            return json.dumps(self.verdict, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps({"agree": True}, ensure_ascii=False)
        return "Краткий вывод."


def _env(claim: str, *, published=None, period=None) -> tf.TemporalClaimEnvelope:
    return tf.TemporalClaimEnvelope(
        claim_id="c1", chat_id=CHAT_ID, target_tg_message_id=7712,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=7713, claim_text=claim, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=published, original_published_precision=None,
        claim_period_from=(period[0] if period else None),
        claim_period_to=(period[1] if period else None),
        claim_period_precision=None, date_source=("telegram_message"
                                                  if published else "unknown"),
        date_precision="day" if published else "unknown",
        date_timezone=None, date_uncertainty={}, requested_mode="",
        analysis_as_of=0)


class TestFCT504EnvelopeDateParity:

    @pytest.mark.asyncio
    async def test_same_payload_with_and_without_date_keeps_evidence_logic(self):
        """Одинаковый смысл с датой и без: evidence/parts логика та же.

        Различаться могут только temporal_status/evaluated_period — отдельная
        ось дат; вердикт и привязка evidence не переизобретаются."""
        claim = "Индекс S&P 500 упал на 2,1% 30 октября 2026 года."
        ref = fsp.EvidenceRef(evidence_id="ev-1",
                              url="https://example.org/a",
                              support="S&P 500 fell 2.1% on October 30",
                              claims=("c1",))
        outcome = _retrieval(
            evidence_map=fsp.EvidenceMap(refs=(ref,), allowlist=("ev-1",)),
            search_text="S&P 500 fell 2.1%", queries_used=1)
        llm = _VerdictLLM({
            "factual_verdict": "supported", "temporal_status": "current",
            "parts": [{"part_id": "p1", "text": claim,
                       "factual_verdict": "supported",
                       "evidence_refs": ["ev-1"]}]})
        service = fsvc.FactCheckService(aggregator=None, llm=llm)
        with_date = await service.check_claim_envelope(
            _env(claim, published=1798761600,
                 period=(1767225600, 1798761600)), retrieval=outcome)
        no_date = await service.check_claim_envelope(
            _env(claim), retrieval=outcome)
        assert (with_date.verdict.factual_verdict
                == no_date.verdict.factual_verdict == "supported")
        assert [p.get("factual_verdict") for p in with_date.verdict.parts] == \
            [p.get("factual_verdict") for p in no_date.verdict.parts]
        assert [r.get("evidence_id") for r in with_date.evidence_rows] == \
            [r.get("evidence_id") for r in no_date.evidence_rows]
        # дата — отдельная ось: она может различаться, доказательная логика нет
        assert with_date.verdict.temporal_status == \
            no_date.verdict.temporal_status


# ── FCT-315: RAG — типизированный <chat_context>, не доказательство ───────

class _FakeLLM:
    def __init__(self):
        self.payloads: list[str] = []

    async def generate(self, messages, **kw):
        self.payloads.append(str(messages[1]["content"]))
        return "Ответ проверки."


class _FakeMemory:
    def __init__(self, rag: str):
        self.rag = rag
        self.asked = 0

    async def memorize_facts(self, *args, **kwargs):
        return None

    async def get_rag_context(self, *args, **kwargs):
        self.asked += 1
        return self.rag


class TestProofBasisAndSnippetOnly:
    """S4 U2: basis только из использованного evidence; сниппет не доказательство."""

    def test_snippet_only_never_backs_positive(self):
        claim = _claim()
        snippet = fsp.ClaimEvidence(
            claim_id="c1", evidence_id="ev-1", url="https://example.org/a",
            role="supports", strength="indirect", opened=False,
            basis=("entity",), snippet_only=True, full_text_available=False,
            published_at_source="", date_status="unknown")
        cov = dataclasses.replace(
            _coverage(claim, outcome=fsp.CLAIM_OUTCOME_CONFIRMED),
            evidence=(snippet,), citation_ids=("ev-1",))
        model = _verdict(
            parts=({"part_id": "c1", "text": claim.text,
                    "factual_verdict": "supported",
                    "evidence_refs": ["ev-1"]},),
            factual="supported")
        merged = fsvc.merge_claim_coverage(model, (cov,), ())
        assert merged.factual_verdict == "insufficient_evidence"
        assert merged.parts[0]["factual_verdict"] == "insufficient_evidence"

    def test_open_direct_support_keeps_positive(self):
        claim = _claim()
        cov = _coverage(claim, outcome=fsp.CLAIM_OUTCOME_CONFIRMED)
        model = _verdict(
            parts=({"part_id": "c1", "text": claim.text,
                    "factual_verdict": "supported",
                    "evidence_refs": ["ev-1"]},),
            factual="supported")
        merged = fsvc.merge_claim_coverage(model, (cov,), ())
        assert merged.factual_verdict == "supported"
        assert merged.parts[0]["factual_verdict"] == "supported"

    def test_checked_verdict_proof_basis_default_is_evidence(self):
        v = orch.CheckedVerdict(verdict_text="x", route="legacy_single")
        assert v.proof_basis == "evidence"
        assert v.execution_status == "unknown"      # совместимость
        assert v.execution_cause == ""


class TestFCT1002ConcurrentChatsIsolation:

    @pytest.mark.asyncio
    async def test_two_chats_concurrently_do_not_share_evidence_or_parts(self):
        """Одновременные прогоны разных чатов не смешивают evidence/claims."""
        import asyncio

        claim_a = "Индекс S&P 500 упал на 2,1%."
        claim_b = "Nasdaq потерял 3,4%."
        ref_a = fsp.EvidenceRef(evidence_id="ev-a",
                                url="https://example.org/a",
                                support="S&P 500 fell 2.1%", claims=("c1",))
        ref_b = fsp.EvidenceRef(evidence_id="ev-b",
                                url="https://example.org/b",
                                support="Nasdaq dropped 3.4%", claims=("c1",))
        outcome_a = _retrieval(
            evidence_map=fsp.EvidenceMap(refs=(ref_a,), allowlist=("ev-a",)),
            search_text="S&P 500 fell 2.1%", queries_used=1,
            claims=(_coverage(_claim(claim_a),
                              outcome=fsp.CLAIM_OUTCOME_CONFIRMED),))
        outcome_b = _retrieval(
            evidence_map=fsp.EvidenceMap(refs=(ref_b,), allowlist=("ev-b",)),
            search_text="Nasdaq dropped 3.4%", queries_used=1,
            claims=(_coverage(_claim(claim_b),
                              outcome=fsp.CLAIM_OUTCOME_CONFIRMED),))
        service = fsvc.FactCheckService(
            aggregator=None, llm=_VerdictLLM({
                "factual_verdict": "supported", "temporal_status": "current"}))
        run_a, run_b = await asyncio.gather(
            service.check_claim_envelope(_env(claim_a), retrieval=outcome_a),
            service.check_claim_envelope(_env(claim_b), retrieval=outcome_b))
        assert {r.get("evidence_id") for r in run_a.evidence_rows} == {"ev-a"}
        assert {r.get("evidence_id") for r in run_b.evidence_rows} == {"ev-b"}
        texts_a = " ".join(str(p.get("text")) for p in run_a.verdict.parts)
        texts_b = " ".join(str(p.get("text")) for p in run_b.verdict.parts)
        assert "S&P" in texts_a and "Nasdaq" not in texts_a
        assert "Nasdaq" in texts_b and "S&P" not in texts_b


class TestFCT315ChatRagIsTypedContext:

    @pytest.mark.asyncio
    async def test_rag_goes_into_typed_chat_context(self):
        old = getattr(settings, "SYSTEM2_FACTCHECK_ENABLED", True)
        object.__setattr__(settings, "SYSTEM2_FACTCHECK_ENABLED", False)
        try:
            rag = "Ранее в чате обсуждали: тариф вырос на 7%."
            llm = _FakeLLM()
            memory = _FakeMemory(rag)
            service = fsvc.FactCheckService(
                aggregator=types.SimpleNamespace(), llm=llm, memory=memory)
            await service._check_claim_pipeline(
                "Правда ли, что тариф вырос?", chat_id=CHAT_ID,
                search_results=("Внешняя выдача: тариф вырос на 7% "
                                "(example.org)."))
        finally:
            object.__setattr__(settings, "SYSTEM2_FACTCHECK_ENABLED", old)
        payload = llm.payloads[-1]
        # 1) RAG внутри типизированного <chat_context> с пометкой «не
        #    доказательство»
        assert "<chat_context" in payload
        assert "НЕ внешнее доказательство" in payload
        before, _, after = payload.partition("</chat_context>")
        assert rag in before
        # 2) RAG не пошёл сырым префиксом user-content
        assert not payload.lstrip().startswith(rag)
        # 3) RAG не оказался в поисковой выдаче
        search_block = payload.partition("<search_results>")[2]
        assert rag not in search_block
        # 4) внешняя выдача остаётся в <search_results>
        assert "Внешняя выдача" in search_block

    def test_merge_user_context_keeps_both_typed_blocks(self):
        merged = fsvc._merge_user_context(
            "<chat_context note='a'>feed</chat_context>",
            "<chat_context note='b'>rag</chat_context>")
        assert merged.startswith("<chat_context")
        assert merged.count("<chat_context") == 2
        assert "feed" in merged and "rag" in merged
        assert fsvc._merge_user_context("", None) is None
