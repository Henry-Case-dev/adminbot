"""FCT-S1-CONTRACT — аддитивные разрывы FCT-112/FCT-113 (Builder, 28.11.2026).

Покрывается ровно два разрыва контракта (contract-freeze §4/§6):

* **FCT-112** — `ClaimUnit` каждой существенной части несёт субъект,
  действие/отношение, объект, отрицание, автора, анкор источника и
  provenance; неизвестное остаётся unknown (`""`/`None`), а `plan.claim_anchors`
  строится ИЗ `ClaimUnit`, а не параллельным словарём.
* **FCT-113** — единая ось `assertion_kind` с четырьмя типами владельца +
  `unknown`; тип различается по СТРУКТУРНЫМ признакам (source_type конверта,
  существующий tool атрибуции), не по спискам слов (owner §2.2), доходит до
  `<claim_parts>` Analyst'а и `parts` вердикта, и положительный вывод при
  неустановленном типе (там, где тип важен) понижается.

Проверки поведенческие: настоящие `build_claim_units`/`build_retrieval_plan`/
`merge_claim_coverage`/`_temporal_user_payload`, без моков тестируемой логики.
"""
from __future__ import annotations

import dataclasses

import pytest

from services import factcheck_planner as fsp
from services import factcheck_service as fsvc
from services import temporal_factcheck as tf
from config.settings import settings
from services.factcheck_suitability import ClaimItem

CHAT_ID = -100777

CLAIM_MARKETS = "Индекс S&P 500 упал на 2,1% 30 октября 2026 года."
CLAIM_PLURAL = ("Ведомство одобрило программу. "
                "Правило действует с 2024 года.")
CLAIM_NEGATED = "Депутаты не приняли закон о бюджете."
CLAIM_PLAIN = "Килякетские дожди AcidLand выпали в июле."


def _item(text, *, source="literal", author=None, anchor=None, chat=None,
          claim_type="checkable_factual_claim"):
    return ClaimItem(text=text, claim_type=claim_type, verifiable=True,
                     source=source, author=author,
                     anchor_tg_message_id=anchor, anchor_chat_id=chat)


def _decision(items, *, scope="web", temporal_hint=False):
    from services.factcheck_suitability import (CHECKABLE_FACTUAL_CLAIM,
                                                DECISION_CHECKABLE,
                                                SuitabilityDecision)
    return SuitabilityDecision(
        decision=DECISION_CHECKABLE, claim_type=CHECKABLE_FACTUAL_CLAIM,
        claim_items=tuple(items), scope=scope, reason_code=None,
        confidence=0.9, target_ref={"target_tg_message_id": 7712},
        temporal_hint=temporal_hint)


def _coverage(claim, *, evidence_id="ev-1", role="supports", detail="verified",
              outcome="supported", status="source_read"):
    ev = fsp.ClaimEvidence(
        claim_id=claim.claim_id, evidence_id=evidence_id,
        url="https://example.org/a", role=role, strength="direct",
        opened=True, basis=("entity",), snippet_only=False,
        independence_group="", independent=True,
        published_at_source="page", date_status="known")
    return fsp.ClaimCoverage(
        claim=claim, search_status=status, status_detail=detail,
        outcome=outcome, reason_code="supported", gap_note="",
        evidence=(ev,), citation_ids=(evidence_id,))


def _verdict(parts, *, factual="supported"):
    return tf.TemporalVerdict(
        factual_verdict=factual, temporal_status="current",
        evaluated_period={}, assessment_mode="data_only", as_of=0,
        parts=tuple(parts))


@pytest.fixture
def planner_on():
    """План строится только при включённом planner'е (заводской OFF)."""
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    yield
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


# ── FCT-112: контракт части ClaimUnit ───────────────────────────────────────

class TestFCT112ClaimUnitContract:

    def test_old_constructor_keeps_unknown_defaults(self):
        """Обратная совместимость: старый конструктор работает, новое — unknown."""
        unit = fsp.ClaimUnit(claim_id="c1", text=CLAIM_MARKETS)
        assert unit.subject == ""
        assert unit.predicate == ""
        assert unit.object == ""
        assert unit.negation is None
        assert unit.author == ""
        assert unit.anchor_tg_message_id is None
        assert unit.anchor_chat_id is None
        assert unit.provenance == ()
        assert unit.assertion_kind == fsp.ASSERTION_KIND_UNKNOWN
        # старые ключи сериализации не потеряны, новые — аддитивны
        data = unit.as_dict()
        assert data["claim_id"] == "c1" and data["text"] == CLAIM_MARKETS
        assert "subject" in data and "assertion_kind" in data

    def test_build_claim_units_fills_subject_negation_and_provenance(self):
        units = fsp.build_claim_units([_item(CLAIM_MARKETS)], CLAIM_MARKETS)
        assert len(units) == 1
        unit = units[0]
        # единственная однозначная именованная сущность → субъект
        assert unit.subject == "S&P"
        # грамматическое отрицание: фраза без частицы → unknown, не False
        assert unit.negation is None
        # смыслового парсера нет: предикат/объект честно unknown
        assert unit.predicate == "" and unit.object == ""
        prov = unit.provenance_dict()
        assert prov["source"] == "literal"
        assert prov["from_glued_request"] == "no"
        assert prov["assertion_kind"] == fsp.ASSERTION_KIND_UNKNOWN

    def test_negation_is_grammatical_not_guessed(self):
        unit = fsp.build_claim_units([_item(CLAIM_NEGATED)], CLAIM_NEGATED)[0]
        assert unit.negation is True
        # «предложил/приняли» без частицы не выдумывают отрицание
        plain = fsp.build_claim_units([_item("Совет принял правило.")],
                                      "Совет принял правило.")[0]
        assert plain.negation is None

    def test_author_and_anchor_filled_from_item_provenance(self, planner_on):
        items = [_item(CLAIM_MARKETS, source="reply_to", author="Аня",
                       anchor=7712, chat=CHAT_ID)]
        plan = fsp.build_retrieval_plan(
            _decision(items), claim_text=CLAIM_MARKETS)
        assert plan is not None and plan.claims
        unit = plan.claims[0]
        assert unit.author == "Аня"
        assert unit.anchor_tg_message_id == 7712
        assert unit.anchor_chat_id == CHAT_ID
        assert unit.provenance_dict()["origin"] == "material"

    def test_part_without_author_keeps_empty_author(self, planner_on):
        items = [_item(CLAIM_MARKETS)]
        plan = fsp.build_retrieval_plan(
            _decision(items), claim_text=CLAIM_MARKETS)
        assert plan is not None and plan.claims
        assert plan.claims[0].author == ""
        assert plan.claims[0].provenance_dict()["author_known"] == "no"

    def test_claim_anchors_are_projection_of_claim_units(self, planner_on):
        """Анкоры строятся из ClaimUnit и переносят КАЖДОЕ поле.

        B-2 (review r1): прежнее сравнение с `_anchor_rows_from_units(claims)`
        было тавтологичным (та же реализация) и не ловило потерю значения.
        Теперь ожидаемые строки заданы литерально.
        """
        items = [_item("Ведомство одобрило программу.", author="Аня",
                       anchor=7710, chat=CHAT_ID),
                 _item("Правило действует с 2024 года.", author="Борис",
                       anchor=7711, chat=CHAT_ID)]
        plan = fsp.build_retrieval_plan(
            _decision(items), claim_text=CLAIM_PLURAL)
        assert plan is not None
        assert plan.claim_anchors == (
            {"claim_id": "c1", "anchor_tg_message_id": 7710,
             "anchor_chat_id": CHAT_ID, "author": "Аня",
             "source": "literal", "origin": "material"},
            {"claim_id": "c2", "anchor_tg_message_id": 7711,
             "anchor_chat_id": CHAT_ID, "author": "Борис",
             "source": "literal", "origin": "material"},
        )

    def test_request_origin_anchor_keeps_source_user_request(self, planner_on):
        """RV-S1-01 (review r1): литеральное значение `source` request-части.

        До фикса проекция анкоров теряла `source="user_request"` (в provenance
        оставался `""`), хотя `_claim_anchor_map` его ставил, а база
        `4cdd72e17` отдавала. Проверяем конкретные значения, не реализацию.
        """
        claim = "Правда ли, что тариф вырос?"
        plan = fsp.build_retrieval_plan(
            _decision([]), claim_text=claim, subject_origin="request",
            subject_request_text=claim, subject_anchor_tg_message_id=55,
            subject_anchor_chat_id=CHAT_ID, subject_author="Аня")
        assert plan is not None and plan.claim_anchors
        row = plan.claim_anchors[0]
        assert row["claim_id"] == "c1"
        assert row["anchor_tg_message_id"] == 55
        assert row["author"] == "Аня"
        assert row["source"] == "user_request"      # RV-S1-01
        assert row["origin"] == "user_request"
        unit = plan.claims[0]
        provenance = unit.provenance_dict()
        assert provenance["source"] == "user_request"
        assert provenance["origin"] == "user_request"
        assert provenance["anchor"] == "tg"

    def test_request_origin_anchor_records_chat(self, planner_on):
        """FCT-112: request-часть несёт и чат анкора (аддитивно к базе)."""
        claim = "Правда ли, что тариф вырос?"
        plan = fsp.build_retrieval_plan(
            _decision([]), claim_text=claim, subject_origin="request",
            subject_request_text=claim, subject_anchor_tg_message_id=55,
            subject_anchor_chat_id=CHAT_ID, subject_author="Аня")
        assert plan is not None and plan.claim_anchors
        assert plan.claim_anchors[0]["anchor_chat_id"] == CHAT_ID
        assert plan.claims[0].anchor_chat_id == CHAT_ID

    def test_unknown_author_is_never_filled_from_display_name(self, planner_on):
        """Мутация M-S1-1: display-name не становится автором части."""
        items = [_item(CLAIM_MARKETS, source="topic")]
        plan = fsp.build_retrieval_plan(
            _decision(items), claim_text=CLAIM_MARKETS,
            subject_author="ВладелецКанала")
        assert plan is not None
        assert plan.claims[0].author == ""


# ── FCT-113: единая ось assertion_kind ─────────────────────────────────────

class TestFCT113AssertionKind:

    def test_axis_is_closed_with_five_values(self):
        assert set(fsp.ASSERTION_KINDS) == {
            "public_statement_attribution", "decision_status",
            "normative_state_on_date", "image_content", "unknown"}
        assert fsp.ASSERTION_KIND_UNKNOWN in fsp.ASSERTION_KINDS

    def test_attribution_tool_marks_public_statement(self):
        units = fsp.build_claim_units(
            [_item("Политик Иванов предложил повысить налог.")],
            "Политик Иванов предложил повысить налог.",
            attribution_detected=True)
        assert units[0].assertion_kind == fsp.ASSERTION_PUBLIC_STATEMENT
        assert units[0].assertion_kind != fsp.ASSERTION_DECISION_STATUS
        assert units[0].assertion_kind != fsp.ASSERTION_NORMATIVE_STATE
        # атрибуция публичного заявления не запрещена и не «шум»
        assert units[0].provenance_dict()["assertion_signal"] == "yes"

    @pytest.mark.parametrize("source_type,expected", [
        ("caption", fsp.ASSERTION_IMAGE_CONTENT),
        ("ocr", fsp.ASSERTION_IMAGE_CONTENT),
        ("text", fsp.ASSERTION_KIND_UNKNOWN),
        ("free_text", fsp.ASSERTION_KIND_UNKNOWN),
    ])
    def test_image_claim_kind_comes_from_structural_source_type(
            self, source_type, expected):
        units = fsp.build_claim_units(
            [_item("Картинка показывает расписание на завтра.")],
            "Картинка показывает расписание на завтра.",
            claim_source_type=source_type)
        assert units[0].assertion_kind == expected

    @pytest.mark.parametrize("kind", [
        fsp.ASSERTION_DECISION_STATUS, fsp.ASSERTION_NORMATIVE_STATE])
    def test_established_kind_hint_is_preserved(self, kind):
        units = fsp.build_claim_units(
            [_item("Совет одобрил правило.")], "Совет одобрил правило.",
            assertion_kind_hint=kind)
        assert units[0].assertion_kind == kind

    def test_unknown_hint_does_not_invent_type(self):
        units = fsp.build_claim_units(
            [_item(CLAIM_MARKETS)], CLAIM_MARKETS,
            assertion_kind_hint="not_a_kind")
        assert units[0].assertion_kind == fsp.ASSERTION_KIND_UNKNOWN

    def test_quote_without_attribution_is_sensitive_unknown(self):
        """Цитата без установленной атрибуции: тип важен и не установлен."""
        items = [_item("Дуров сказал про свободу.", source="quote")]
        units = fsp.build_claim_units(items, "Дуров сказал про свободу.")
        unit = units[0]
        assert unit.assertion_kind == fsp.ASSERTION_KIND_UNKNOWN
        assert unit.provenance_dict()["assertion_signal"] == "yes"
        assert fsvc._claim_assertion_unresolved(unit) is True

    def test_plain_claim_is_not_sensitive(self):
        units = fsp.build_claim_units([_item(CLAIM_PLAIN)], CLAIM_PLAIN)
        assert units[0].assertion_kind == fsp.ASSERTION_KIND_UNKNOWN
        assert fsvc._claim_assertion_unresolved(units[0]) is False


class TestFCT113PropagationToAnalystAndVerdict:

    def test_claim_part_payload_carries_assertion_kind(self):
        unit = fsp.ClaimUnit(
            claim_id="c1", text="Совет одобрил правило.",
            assertion_kind=fsp.ASSERTION_DECISION_STATUS)
        cov = _coverage(unit)
        part = tf.ClaimPart(part_id="p1", text="Совет одобрил правило.")
        assert fsvc._assertion_kind_for_part(part, (cov,)) == \
            fsp.ASSERTION_DECISION_STATUS
        other = tf.ClaimPart(part_id="p2", text="Совсем другой тезис.")
        assert fsvc._assertion_kind_for_part(other, (cov,)) == \
            fsp.ASSERTION_KIND_UNKNOWN

    def test_media_part_matches_unit_by_stripped_thesis(self):
        """Медиа-часть несёт служебную обёртку OCR, ClaimUnit — нет.

        Матч по тезису без обёртки обязателен: иначе image_content не доходил
        бы до `<claim_parts>` именно у медиа-тезисов."""
        unit = fsp.ClaimUnit(
            claim_id="c1", text="Расписание на завтра 09:00.",
            assertion_kind=fsp.ASSERTION_IMAGE_CONTENT)
        cov = _coverage(unit)
        part = tf.ClaimPart(
            part_id="p1",
            text=("Текст с изображения (OCR, не слова автора): "
                  "Расписание на завтра 09:00."))
        assert fsvc._assertion_kind_for_part(part, (cov,)) == \
            fsp.ASSERTION_IMAGE_CONTENT

    def test_verdict_part_metadata_carries_assertion_kind_and_anchor(self):
        unit = fsp.ClaimUnit(
            claim_id="c1", text="Совет одобрил правило.",
            author="Аня", anchor_tg_message_id=7712,
            assertion_kind=fsp.ASSERTION_DECISION_STATUS)
        cov = _coverage(unit)
        verdict = _verdict([{"part_id": "c1", "text": unit.text,
                             "factual_verdict": "supported",
                             "evidence_refs": ["ev-1"]}])
        merged = fsvc.merge_claim_coverage(verdict, (cov,), ())
        part = merged.parts[0]
        assert part["assertion_kind"] == fsp.ASSERTION_DECISION_STATUS
        assert part["anchor_tg_message_id"] == 7712
        assert part["author"] == "Аня"

    def test_positive_verdict_degrades_when_kind_unresolved(self):
        """FCT-113: unknown-тип там, где он важен, не даёт положительного вывода."""
        unit = fsp.ClaimUnit(
            claim_id="c1", text="Дуров сказал про свободу.",
            provenance=(("source", "quote"),
                        ("assertion_signal", "yes"),
                        ("assertion_kind", "unknown")))
        cov = _coverage(unit)
        verdict = _verdict([{"part_id": "c1", "text": unit.text,
                             "factual_verdict": "supported",
                             "evidence_refs": ["ev-1"]}])
        merged = fsvc.merge_claim_coverage(verdict, (cov,), ())
        assert merged.factual_verdict == "insufficient_evidence"
        assert "assertion_kind_unknown" in (merged.uncertainty or {})

    def test_ordinary_claim_positive_is_not_degraded(self):
        """Обычный факт не блокируется unknown-типом: его держит evidence.

        Это защита от регрессии: массовое понижение всех положительных
        выводов сделало бы проверку фактов нерабочей."""
        unit = fsp.ClaimUnit(claim_id="c1", text=CLAIM_MARKETS)
        cov = _coverage(unit)
        verdict = _verdict([{"part_id": "c1", "text": unit.text,
                             "factual_verdict": "supported",
                             "evidence_refs": ["ev-1"]}])
        merged = fsvc.merge_claim_coverage(verdict, (cov,), ())
        assert merged.factual_verdict == "supported"
        assert "assertion_kind_unknown" not in (merged.uncertainty or {})

    def test_known_kind_positive_is_not_degraded(self):
        unit = fsp.ClaimUnit(
            claim_id="c1", text="Совет одобрил правило.",
            assertion_kind=fsp.ASSERTION_DECISION_STATUS)
        cov = _coverage(unit)
        verdict = _verdict([{"part_id": "c1", "text": unit.text,
                             "factual_verdict": "supported",
                             "evidence_refs": ["ev-1"]}])
        merged = fsvc.merge_claim_coverage(verdict, (cov,), ())
        assert merged.factual_verdict == "supported"


class TestFCT113EndToEndPlanToParts:

    def test_plan_to_analyst_payload_end_to_end(self, planner_on):
        """Настоящий план (image/caption) → настоящий <claim_parts> payload'а."""
        claim = "Картинка показывает расписание на завтра."
        items = [_item(claim)]
        plan = fsp.build_retrieval_plan(
            _decision(items), claim_text=claim, claim_source_type="ocr")
        assert plan is not None
        unit = plan.claims[0]
        assert unit.assertion_kind == fsp.ASSERTION_IMAGE_CONTENT

        env = _envelope(claim)
        parts = tf.decompose_claim(env)
        payload = fsvc.FactCheckService(aggregator=None, llm=None) \
            ._temporal_user_payload(env, parts, (), None, coverage=(
                _coverage(unit),))
        assert "<claim_parts>" in payload
        assert fsp.ASSERTION_IMAGE_CONTENT in payload


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
