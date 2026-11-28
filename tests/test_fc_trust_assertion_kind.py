"""FCT-113 U1 (28.11.2026) — тип утверждения части из смысловой стадии Analyst.

Контракт Architect (`evidence/fct-contract-decisions-2026-11-28/decisions.md`
§1): закрытый набор значений не меняется; `image_content` и
`public_statement_attribution` определяются провенансом и структурным
tool'ом, поэтому модель их не переопределяет; `decision_status` и
`normative_state_on_date` устанавливает существующий Analyst аддитивным
полем части.

Границы U1 (эти два файла): поле принимается и валидируется на единственном
входе модели (`verdict_from_payload`) и не теряется дальше. Окончательное
применение смыслового значения в `parts[]` вместе со структурным приоритетом
делает merge-стадия (U2, `factcheck_service.py`) — здесь она не переписана,
поэтому общий merge-инвариант проверяется только для структурных типов.

Проверки поведенческие: настоящий планировщик, настоящий
`verdict_from_payload` и настоящий `merge_claim_coverage`, без моков
проверяемой логики.
"""
from __future__ import annotations

import logging

import pytest

from services import factcheck_planner as fsp
from services import factcheck_service as fsvc
from services import temporal_factcheck as tf
from services.factcheck_suitability import ClaimItem

CHAT_ID = -100777
CLAIM_PLAIN = "Совет одобрил правило."
CLAIM_IMAGE = "Картинка показывает расписание на завтра 09:00."
CLAIM_QUOTE = "Дуров сказал про свободу."


# ── helpers ─────────────────────────────────────────────────────────────────

def _item(text, *, source="literal", author=None, anchor=None, chat=None,
          claim_type="checkable_factual_claim"):
    return ClaimItem(text=text, claim_type=claim_type, verifiable=True,
                     source=source, author=author,
                     anchor_tg_message_id=anchor, anchor_chat_id=chat)


def _envelope(text, *, source_type="text"):
    return tf.TemporalClaimEnvelope(
        claim_id="c1", chat_id=CHAT_ID, target_tg_message_id=7712,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=7713, claim_text=text, claim_span=None,
        source_type=source_type, attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="", analysis_as_of=0)


def _coverage(claim, *, evidence_id="ev-1", role="supports"):
    ev = fsp.ClaimEvidence(
        claim_id=claim.claim_id, evidence_id=evidence_id,
        url="https://example.org/a", role=role, strength="direct",
        opened=True, basis=("entity",), snippet_only=False,
        independence_group="", independent=True,
        published_at_source="page", date_status="known")
    return fsp.ClaimCoverage(
        claim=claim, search_status="source_read", status_detail="verified",
        outcome="supported", reason_code="supported", gap_note="",
        evidence=(ev,), citation_ids=(evidence_id,))


def _payload(assertion_kind, *, part_id="c1", verdict="supported",
             evidence_quotes=None):
    part = {"part_id": part_id, "factual_verdict": verdict,
            "evidence_refs": ["ev-1"]}
    if assertion_kind is not ...:
        part["assertion_kind"] = assertion_kind
    if evidence_quotes is not None:
        part["evidence_quotes"] = evidence_quotes
    return {"factual_verdict": verdict, "temporal_status": "current",
            "evaluated_period": {}, "parts": [part]}


# ── приём смысловых значений Analyst'а ─────────────────────────────────────

class TestAnalystSemanticKinds:

    @pytest.mark.parametrize("kind", [
        fsp.ASSERTION_DECISION_STATUS, fsp.ASSERTION_NORMATIVE_STATE])
    def test_semantic_kind_from_scripted_payload_is_accepted(self, kind):
        """Analyst ставит смысловой тип — значение доходит до parts[]."""
        verdict = tf.verdict_from_payload(
            _payload(kind), _envelope(CLAIM_PLAIN), allowed_refs={"ev-1"})
        assert verdict.parts[0]["assertion_kind"] == kind

    @pytest.mark.parametrize("value", [
        "bogus_kind", "", "image", 7, 3.5, None, True, ["decision_status"],
        {"kind": "decision_status"}])
    def test_out_of_set_or_non_string_becomes_unknown(self, value):
        """Значение вне набора и не-строка → honest unknown, без падения."""
        verdict = tf.verdict_from_payload(
            _payload(value), _envelope(CLAIM_PLAIN), allowed_refs={"ev-1"})
        assert verdict.parts[0]["assertion_kind"] == fsp.ASSERTION_KIND_UNKNOWN

    def test_explicit_unknown_is_not_guessed(self):
        verdict = tf.verdict_from_payload(
            _payload(fsp.ASSERTION_KIND_UNKNOWN), _envelope(CLAIM_PLAIN))
        assert verdict.parts[0]["assertion_kind"] == fsp.ASSERTION_KIND_UNKNOWN

    def test_missing_field_is_not_invented(self):
        """Аддитивность: поле не добавлено моделью — ключ не появляется."""
        verdict = tf.verdict_from_payload(_payload(...), _envelope(CLAIM_PLAIN))
        assert "assertion_kind" not in verdict.parts[0]

    @pytest.mark.parametrize("kind", [
        fsp.ASSERTION_PUBLIC_STATEMENT, fsp.ASSERTION_IMAGE_CONTENT])
    def test_structural_kind_from_model_is_rejected(self, kind, caplog):
        """Структурный тип моделью не выставляется: попытка → unknown + лог.

        Иначе модель обходила бы защиту «цитата без атрибуции → unknown →
        понижение»: объявив атрибуцию сама, она снимала бы понижение.
        """
        with caplog.at_level(logging.WARNING,
                             logger="services.temporal_factcheck"):
            verdict = tf.verdict_from_payload(
                _payload(kind), _envelope(CLAIM_PLAIN), allowed_refs={"ev-1"})
        assert verdict.parts[0]["assertion_kind"] == \
            fsp.ASSERTION_KIND_UNKNOWN
        messages = [record.getMessage() for record in caplog.records
                    if record.name == "services.temporal_factcheck"
                    and "assertion_kind" in record.getMessage()]
        assert messages, "конфликт структурного типа не записан в лог"
        assert "public_statement_attribution" in " ".join(messages) or \
            "image_content" in " ".join(messages)
        # новых reason-кодов нет: причина вердикта не подменяется конфликтом
        assert verdict.reason is None

    def test_rejected_kind_does_not_replace_valid_reason(self):
        payload = _payload("bogus_kind")
        payload["reason"] = "insufficient_evidence"
        verdict = tf.verdict_from_payload(payload, _envelope(CLAIM_PLAIN))
        assert verdict.reason == "insufficient_evidence"


# ── структурный приоритет на выходе вердикта ───────────────────────────────

class TestStructuralPrecedence:

    def test_image_claim_keeps_image_kind_against_model_value(self):
        """Медиа-тезис: тип из провенанса не переопределяется моделью.

        Даже принятое смысловое значение Analyst'а (`decision_status`) не
        меняет структурный `image_content` в `parts[]`.
        """
        claim = fsp.ClaimUnit(
            claim_id="c1", text=CLAIM_IMAGE,
            assertion_kind=fsp.ASSERTION_IMAGE_CONTENT)
        verdict = tf.verdict_from_payload(
            _payload(fsp.ASSERTION_DECISION_STATUS), _envelope(CLAIM_IMAGE),
            allowed_refs={"ev-1"})
        # на входе вердикта смысловое значение принято ...
        assert verdict.parts[0]["assertion_kind"] == \
            fsp.ASSERTION_DECISION_STATUS
        # ... но провенанс побеждает в части вердикта
        merged = fsvc.merge_claim_coverage(verdict, (_coverage(claim),), ())
        assert merged.parts[0]["assertion_kind"] == \
            fsp.ASSERTION_IMAGE_CONTENT

    def test_model_attribution_cannot_unlock_sensitive_quote(self):
        """Цитата без атрибуции: модель не снимает понижение своим типом."""
        claim = fsp.ClaimUnit(
            claim_id="c1", text=CLAIM_QUOTE,
            provenance=(("source", "quote"),
                        ("assertion_signal", "yes"),
                        ("assertion_kind", fsp.ASSERTION_KIND_UNKNOWN)))
        verdict = tf.verdict_from_payload(
            _payload(fsp.ASSERTION_PUBLIC_STATEMENT), _envelope(CLAIM_QUOTE),
            allowed_refs={"ev-1"})
        merged = fsvc.merge_claim_coverage(verdict, (_coverage(claim),), ())
        assert merged.parts[0]["assertion_kind"] == \
            fsp.ASSERTION_KIND_UNKNOWN
        assert merged.factual_verdict == "insufficient_evidence"
        assert "assertion_kind_unknown" in (merged.uncertainty or {})


# ── измеримое acceptance: четыре fixtures → четыре значения ────────────────

class TestFourOwnerFixtures:

    def test_four_fixtures_produce_all_four_owner_values(self):
        """Четыре тезиса владельца дают четыре разных значения оси.

        Источник значения у каждого типа свой (провенанс/структурный tool —
        для атрибуции и изображения; существующий Analyst — для статуса
        решения и нормы на дату), и ни одно значение не дублирует другое.
        """
        attribution = fsp.build_claim_units(
            [_item("Политик Иванов предложил повысить налог.")],
            "Политик Иванов предложил повысить налог.",
            attribution_detected=True)[0]
        image = fsp.build_claim_units(
            [_item(CLAIM_IMAGE)], CLAIM_IMAGE, claim_source_type="ocr")[0]

        decision = tf.verdict_from_payload(
            _payload(fsp.ASSERTION_DECISION_STATUS),
            _envelope("Ведомство одобрило программу."),
            allowed_refs={"ev-1"}).parts[0]["assertion_kind"]
        normative = tf.verdict_from_payload(
            _payload(fsp.ASSERTION_NORMATIVE_STATE),
            _envelope("Правило действует с 01.01.2027."),
            allowed_refs={"ev-1"}).parts[0]["assertion_kind"]

        produced = {
            "public_statement_attribution": attribution.assertion_kind,
            "decision_status": decision,
            "normative_state_on_date": normative,
            "image_content": image.assertion_kind,
        }
        assert produced == {
            "public_statement_attribution": fsp.ASSERTION_PUBLIC_STATEMENT,
            "decision_status": fsp.ASSERTION_DECISION_STATUS,
            "normative_state_on_date": fsp.ASSERTION_NORMATIVE_STATE,
            "image_content": fsp.ASSERTION_IMAGE_CONTENT,
        }
        assert len(set(produced.values())) == 4
        assert fsp.ASSERTION_KIND_UNKNOWN not in set(produced.values())
