"""FCT-192 U1 (28.11.2026) — детерминированная часть привязки claim↔passage.

Контракт Architect (`evidence/fct-contract-decisions-2026-11-28/decisions.md`
§2): (1) узкий year conflict в evidence-профиле `claim_relevance`: пассаж о
другом явном годе не подтверждает и не опровергает тезис, а квалифицирует
его (`qualifies`, basis `time:year_conflict`, strength `indirect`);
(2) аддитивное поле части Analyst'а `evidence_quotes {evidence_id: фраза}`,
форма которого приводится к контракту на входе вердикта.

Границы U1 (эти два файла): проверка дословного вхождения цитаты в
cited-пассаж и понижение непривязанных positive-частей делает merge-стадия
(U2, `factcheck_service.py`) — здесь она не переписана и не подменяется.

Проверки поведенческие: настоящий `claim_relevance` (production-решение о
роли), production-обёртка планировщика `_relevance_for` и настоящий
`verdict_from_payload`/`apply_validator`, без моков проверяемой логики.
"""
from __future__ import annotations

import pytest

from services import factcheck_planner as fsp
from services import search_aggregator as sa
from services import temporal_factcheck as tf

CHAT_ID = -100777

CLAIM_2025 = "ЭкоПром снизила выбросы на 12% в 2025 году."
PASSAGE_2024 = "ЭкоПром снизила выбросы на 12% в 2024 году."
PASSAGE_2025 = "ЭкоПром снизила выбросы на 12% в 2025 году."
#: кросс-язычный контроль: у тезиса год есть, у пассажа года нет
CLAIM_CROSS = "Индекс S&P 500 упал на 2,1% 30 октября 2026 года."
PASSAGE_CROSS = ("S&P 500 falls 2.1% on October 30 after the sell-off")


def _claim(timeframe="2025", *, text=CLAIM_2025):
    return fsp.ClaimUnit(claim_id="c1", text=text, metrics=("12%",),
                         entities=("ЭкоПром",), units=("percent",),
                         timeframe=timeframe,
                         claim_type="checkable_factual_claim")


def _relevance(passage, *, claim_text=CLAIM_2025, timeframe="2025",
               metrics=("12%",), entities=("ЭкоПром",), require_anchor=True):
    return sa.claim_relevance(
        passage, claim_text=claim_text, metrics=metrics, entities=entities,
        claim_type="checkable_factual_claim", timeframe=timeframe,
        require_anchor=require_anchor)


def _envelope(text):
    return tf.TemporalClaimEnvelope(
        claim_id="c1", chat_id=CHAT_ID, target_tg_message_id=7712,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=7713, claim_text=text, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="", analysis_as_of=0)


def _payload(*, assertion_kind=None, evidence_quotes=None,
             part_verdict="supported"):
    part = {"part_id": "c1", "factual_verdict": part_verdict,
            "evidence_refs": ["ev-1"]}
    if assertion_kind is not None:
        part["assertion_kind"] = assertion_kind
    if evidence_quotes is not None:
        part["evidence_quotes"] = evidence_quotes
    return {"factual_verdict": part_verdict, "temporal_status": "current",
            "evaluated_period": {}, "parts": [part]}


# ── year conflict (детерминированная eligibility) ──────────────────────────

class TestYearConflict:

    def test_passage_of_another_year_is_not_support(self):
        """Тезис 2025 против пассажа 2024: не supports, а qualifies."""
        rel = _relevance(PASSAGE_2024)
        assert rel.role == sa.EVIDENCE_ROLE_QUALIFIES
        assert rel.role != sa.EVIDENCE_ROLE_SUPPORTS
        assert "time:year_conflict" in rel.basis
        assert rel.strength == "indirect"
        # конфликт фиксируется как содержательный признак пассажа
        assert rel.anchor is True

    def test_same_year_still_supports(self):
        rel = _relevance(PASSAGE_2025)
        assert rel.role == sa.EVIDENCE_ROLE_SUPPORTS
        assert rel.strength == "direct"
        assert "time:year_conflict" not in rel.basis

    @pytest.mark.parametrize("passage", [
        "ЭкоПром снизила выбросы на 12% в 2023 году после проверки.",
        "ЭкоПром снизила выбросы на 12% в 2023–2024 годах по данным "
        "независимых наблюдателей.",
        "ЭкоПром снизила выбросы на 12% в 2024 году, хотя в 2019-м "
        "показатель рос.",
    ])
    def test_any_other_year_is_a_conflict(self, passage):
        rel = _relevance(passage)
        assert rel.role == sa.EVIDENCE_ROLE_QUALIFIES
        assert "time:year_conflict" in rel.basis

    def test_cross_language_without_year_is_unchanged(self):
        """Кросс-язычный кейс без года в пассаже — прежнее поведение."""
        rel = _relevance(PASSAGE_CROSS, claim_text=CLAIM_CROSS,
                         timeframe="30 октября 2026", metrics=("2,1%",),
                         entities=("S&P",))
        assert rel.role == sa.EVIDENCE_ROLE_SUPPORTS
        assert rel.strength == "direct"
        assert "time:year_conflict" not in rel.basis

    def test_claim_without_year_is_unchanged(self):
        """У тезиса нет года — год пассажа ничего не конфликтует."""
        rel = _relevance(PASSAGE_2024, timeframe="")
        assert rel.role == sa.EVIDENCE_ROLE_SUPPORTS
        assert "time:year_conflict" not in rel.basis

    def test_year_interval_of_the_claim_covers_passage_year(self):
        """Диапазон тезиса (2023–2025) не конфликтует с годом внутри него."""
        rel = _relevance(PASSAGE_2024, timeframe="2023–2025")
        assert rel.role == sa.EVIDENCE_ROLE_SUPPORTS
        assert "time:year_conflict" not in rel.basis

    def test_year_inside_url_is_not_a_passage_year(self):
        """Год из адреса пассажа — не утверждение источника."""
        rel = _relevance(PASSAGE_2025 + " https://eco.example/2024/report")
        assert rel.role == sa.EVIDENCE_ROLE_SUPPORTS
        assert "time:year_conflict" not in rel.basis

    def test_default_profile_keeps_previous_behaviour(self):
        """Профиль по умолчанию (direct_execution/evidence_policy) не изменён."""
        rel = _relevance(PASSAGE_2024, require_anchor=False)
        assert rel.role == sa.EVIDENCE_ROLE_SUPPORTS
        assert "time:year_conflict" not in rel.basis

    def test_planner_wrapper_passes_claim_timeframe(self):
        """Реальный вызов планировщика: тип пассажа определяется с годом тезиса."""
        ref = fsp.EvidenceRef(evidence_id="ev-1", url="https://eco.example/1",
                              support=PASSAGE_2024, source_kind="secondary")
        rel = fsp._relevance_for(ref, _claim("2025"))
        assert rel.role == sa.EVIDENCE_ROLE_QUALIFIES
        assert "time:year_conflict" in rel.basis


# ── evidence_quotes: форма аддитивного поля части ──────────────────────────

class TestEvidenceQuotesForm:

    def test_verbatim_quote_is_preserved(self):
        verdict = tf.verdict_from_payload(
            _payload(evidence_quotes={"ev-1": "  снизила выбросы на 12%  "}),
            _envelope(CLAIM_2025), allowed_refs={"ev-1"})
        assert verdict.parts[0]["evidence_quotes"] == {
            "ev-1": "снизила выбросы на 12%"}

    @pytest.mark.parametrize("quotes", [
        "снизила выбросы на 12%",            # не словарь
        ["ev-1", "снизила выбросы"],         # не словарь
        None,
        7,
    ])
    def test_non_dict_quotes_are_dropped(self, quotes):
        verdict = tf.verdict_from_payload(
            _payload(evidence_quotes=quotes), _envelope(CLAIM_2025),
            allowed_refs={"ev-1"})
        assert "evidence_quotes" not in verdict.parts[0]

    @pytest.mark.parametrize("phrase", [5, None, True, ["фраза"], {"t": "x"}])
    def test_non_string_phrase_is_dropped(self, phrase):
        verdict = tf.verdict_from_payload(
            _payload(evidence_quotes={"ev-1": phrase}),
            _envelope(CLAIM_2025), allowed_refs={"ev-1"})
        assert "evidence_quotes" not in verdict.parts[0]

    def test_empty_phrase_is_dropped(self):
        verdict = tf.verdict_from_payload(
            _payload(evidence_quotes={"ev-1": "   "}),
            _envelope(CLAIM_2025), allowed_refs={"ev-1"})
        assert "evidence_quotes" not in verdict.parts[0]

    def test_quote_for_foreign_evidence_is_dropped(self):
        """ID выдержки вне текущего прогона не становится основанием."""
        verdict = tf.verdict_from_payload(
            _payload(evidence_quotes={"ev-9": "снизила выбросы на 12%"}),
            _envelope(CLAIM_2025), allowed_refs={"ev-1"})
        assert "evidence_quotes" not in verdict.parts[0]

    def test_mixed_quotes_keep_only_current_run_evidence(self):
        verdict = tf.verdict_from_payload(
            _payload(evidence_quotes={"ev-1": "снизила выбросы на 12%",
                                      "ev-9": "чужая выдержка"}),
            _envelope(CLAIM_2025), allowed_refs={"ev-1"})
        assert verdict.parts[0]["evidence_quotes"] == {
            "ev-1": "снизила выбросы на 12%"}

    def test_quotes_survive_validator_correction(self):
        """Перепроверка validator'ом не стирает цитаты-основания."""
        env = _envelope(CLAIM_2025)
        verdict = tf.verdict_from_payload(
            _payload(evidence_quotes={"ev-1": "снизила выбросы на 12%"}),
            env, allowed_refs={"ev-1"})
        corrected, applied = tf.apply_validator(
            verdict, {"agree": False, "corrected_factual_verdict": "mixed"},
            env)
        assert applied is True
        assert corrected.parts[0]["evidence_quotes"] == {
            "ev-1": "снизила выбросы на 12%"}

    def test_quotes_do_not_change_part_verdict(self):
        """U1 не оценивает привязку: статус части решает merge-стадия (U2)."""
        verdict = tf.verdict_from_payload(
            _payload(evidence_quotes={"ev-9": "чужая выдержка"}),
            _envelope(CLAIM_2025), allowed_refs={"ev-1"})
        assert verdict.parts[0]["factual_verdict"] == "supported"
