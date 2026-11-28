"""FCT-U1-R1-F1 repro: 4-значная сумма/количество не должна быть годом.

Реальный путь: `search_aggregator.claim_relevance(require_anchor=True)` +
сквозь `factcheck_service.merge_claim_coverage` (наблюдаемый вердикт части).

Запуск:
  .venv/Scripts/python.exe plans/features/fc-trust-01/evidence/\
fct-u1-2026-11-28/raw/probe_f1_repro.py
"""
from __future__ import annotations

import json

from services import factcheck_planner as fsp
from services import factcheck_service as fsvc
from services import search_aggregator as sa
from services import temporal_factcheck as tf

CHAT_ID = -100777

CLAIM_2024 = "ЭкоПром снизила выбросы на 12% в 2024 году."
#: пассаж ревью r1 §4 F1: 2025 — цена билета, года в пассаже нет
PASSAGE_AMOUNT = ("Билет на выставку стоит 2025 рублей, выбросы ЭкоПром "
                  "снизились на 12%.")
PASSAGE_MILLIONS = ("Билет на выставку стоит 2025 млн рублей, выбросы "
                    "ЭкоПром снизились на 12%.")
PASSAGE_USD = "Билет на выставку стоит $2025 млн, выбросы ЭкоПром снизились на 12%."
PASSAGE_TONS = ("ЭкоПром снизила выбросы на 12%, сэкономлено 2025 тыс. тонн.")
PASSAGE_AMOUNT_AND_YEAR = ("Билет на выставку стоит 2025 рублей, а в 2023 году "
                           "выбросы ЭкоПром снизились на 12%.")
PASSAGE_REAL_OTHER_YEAR = "ЭкоПром снизила выбросы на 12% в 2023 году."
PASSAGE_SAME_YEAR = "ЭкоПром снизила выбросы на 12% в 2024 году."


def _claim(text=CLAIM_2024, timeframe="2024"):
    return fsp.ClaimUnit(claim_id="c1", text=text, metrics=("12%",),
                         entities=("ЭкоПром",), units=("percent",),
                         timeframe=timeframe,
                         claim_type="checkable_factual_claim")


def _relevance(passage, timeframe="2024"):
    return sa.claim_relevance(
        passage, claim_text=CLAIM_2024, metrics=("12%",),
        entities=("ЭкоПром",), claim_type="checkable_factual_claim",
        timeframe=timeframe, require_anchor=True)


def _envelope(text=CLAIM_2024):
    return tf.TemporalClaimEnvelope(
        claim_id="c1", chat_id=CHAT_ID, target_tg_message_id=7712,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=7713, claim_text=text, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_at_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="", analysis_as_of=0)


def _merged(rel):
    claim = _claim()
    ev = fsp.ClaimEvidence(
        claim_id="c1", evidence_id="ev-1", url="https://eco.example/1",
        role=rel.role, strength=rel.strength, opened=True, basis=rel.basis,
        snippet_only=False, independent=True, published_at_source="page",
        date_status="known")
    cov = fsp.ClaimCoverage(
        claim=claim, search_status="source_read", status_detail="verified",
        outcome=fsp.CLAIM_OUTCOME_CONFIRMED, reason_code="", gap_note="",
        evidence=(ev,), citation_ids=("ev-1",))
    model = tf.TemporalVerdict(
        factual_verdict="supported", temporal_status="current",
        evaluated_period={}, assessment_mode="data_only", as_of=0,
        parts=({"part_id": "c1", "factual_verdict": "supported",
                "evidence_refs": ["ev-1"]},))
    return fsvc.merge_claim_coverage(model, (cov,), ())


for label, passage in (
        ("amount_rub", PASSAGE_AMOUNT),
        ("amount_million_rub", PASSAGE_MILLIONS),
        ("amount_usd_million", PASSAGE_USD),
        ("amount_thousand_tons", PASSAGE_TONS),
        ("amount_plus_other_year", PASSAGE_AMOUNT_AND_YEAR),
        ("real_other_year", PASSAGE_REAL_OTHER_YEAR),
        ("same_year", PASSAGE_SAME_YEAR),
):
    rel = _relevance(passage)
    merged = _merged(rel)
    part = merged.parts[0] if merged.parts else {}
    print(json.dumps({
        "case": label,
        "role": rel.role,
        "strength": rel.strength,
        "basis": list(rel.basis),
        "merged_factual": merged.factual_verdict,
        "part_factual": part.get("factual_verdict"),
        "part_gap_note": part.get("gap_note", ""),
        "part_status_detail": part.get("status_detail", ""),
    }, ensure_ascii=False))
