"""S16 probe: наблюдаемое поведение финализации фактчека на базе 9a89e3da.

Сценарии:
  A. Whole-message check: предмет = весь материал (subject.origin=material).
  B. Request-part check: пользователь просит конкретный ответ на часть.
  C. Technical interruption (budget) + собранный evidence + отказ вербализатора.
  D. Утечка служебных enum/ID/OCR в пользовательскую речь.
  E. Пропорциональность: короткий факт vs сложная публикация (max_symbols).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json

import services.temporal_factcheck as tf
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services.factcheck_service import FactCheckService


ANALYST = json.dumps({
    "factual_verdict": "insufficient_evidence",
    "temporal_status": "unknown",
    "evaluated_period": {"from": None, "to": None},
    "reason": None,
    "parts": [],
}, ensure_ascii=False)
VALIDATOR = json.dumps(
    {"agree": True, "corrected_factual_verdict": None,
     "corrected_temporal_status": None, "note": "ok"},
    ensure_ascii=False)


class LLM:
    def __init__(self, *, verbalizer="", fail_verbalize=False):
        self.verbalizer = verbalizer
        self.fail_verbalize = fail_verbalize
        self.calls = []

    async def generate(self, messages, *, step="", **_kw):
        user = messages[-1]["content"]
        self.calls.append((step, messages, user))
        if step in ("temporal_verdict", "temporal_fallback"):
            return ANALYST
        if step == "temporal_validator":
            return VALIDATOR
        if self.fail_verbalize:
            raise RuntimeError("verbalizer down")
        return self.verbalizer or "Ответ (test)."


def _env(claim_text, *, request_part=None):
    return tf.TemporalClaimEnvelope(
        claim_id="tcl-s16", chat_id=1, target_tg_message_id=10,
        target_revision=1, target_content_hash="h1",
        trigger_tg_message_id=11, claim_text=claim_text,
        claim_span=None, source_type="text", attribution={"author": "A"},
        origin_type="channel", origin_sender_user_id=None,
        origin_chat_id=-777, origin_display_name="A",
        repost_received_at=1760000000, original_published_at=1665277000,
        original_published_precision="day", claim_period_from=None,
        claim_period_to=None, claim_period_precision=None,
        date_source="telegram_origin", date_precision="day",
        date_timezone=None, date_uncertainty={}, requested_mode="contextual",
        analysis_as_of=1760000000, request_text=request_part,
        material_claim_text=claim_text)


def _ref(i):
    return orch.EvidenceRef(
        evidence_id=f"ev-{i}", url=f"https://source{i}.example/page",
        support=f"Подтверждающая выдержка {i}: факт задокументирован.",
        source_kind="secondary", published_at=1665277000, claims=("c1",))


def _outcome(refs, *, budget_exhausted=False):
    text = "фрагмент выдачи " * 50
    return fsp.RetrievalOutcome(
        evidence_map=orch.EvidenceMap(
            refs=tuple(refs), allowlist=tuple(r.evidence_id for r in refs)),
        search_text=text, queries_attempted=2, queries_used=2,
        refs_collected=len(refs), fetch_errors=0,
        budget_exhausted=budget_exhausted,
        stop_reason="budget" if budget_exhausted else "complete")


async def scenario(name, *, claim_text, llm, refs=(), budget=False,
                   request_part=None, material=None):
    service = FactCheckService(aggregator=None, llm=llm)
    env = _env(claim_text, request_part=request_part)
    if material is not None:
        env = dataclasses.replace(env, material_claim_text=material)
    out = _outcome(refs, budget_exhausted=budget) if refs else None
    run = await service.check_claim_envelope(env, retrieval=out)
    print("=" * 70)
    print(name)
    print("-" * 70)
    print("VERDICT:", run.verdict.factual_verdict, "| reason:", run.verdict.reason)
    print("TEXT:", run.verdict_text[:600])
    print("STEPS:", [c[0] for c in llm.calls])
    for step, messages, user in llm.calls:
        if step in ("temporal_verdict", "temporal_verbalize"):
            print(f"--- {step} payload (first 900) ---")
            print(messages[-1]["content"][:900])
    return run


async def main():
    # A. whole message
    llm = LLM(verbalizer="Проверил всё сообщение: факты не подтверждаются.")
    await scenario("A whole message", claim_text="Утверждение целиком: X "
                   "сделал Y в 2021 году.", llm=llm,
                   refs=[_ref(1), _ref(2)])
    # B. related part
    llm = LLM(verbalizer="Конкретно про второе утверждение: оно не подтверждается.")
    await scenario("B related part", claim_text="Правда ли, что курс вырос вдвое?",
                   request_part="Правда ли, что курс вырос вдвое?", llm=llm,
                   refs=[_ref(1)],
                   material="Курс вырос вдвое. Инфляция осталась низкой.")
    # C. technical interruption + evidence + verbalizer down
    llm = LLM(fail_verbalize=True)
    await scenario("C budget + evidence + verbalizer down",
                   claim_text="Утверждение при бюджетном прерывании.", llm=llm,
                   refs=[_ref(1), _ref(2), _ref(3)], budget=True)
    # C2. technical interruption + NO evidence + verbalizer down
    llm = LLM(fail_verbalize=True)
    await scenario("C2 budget + no evidence + verbalizer down",
                   claim_text="Утверждение без evidence.", llm=llm)
    # D. leak of service enums / ids / ocr into verbalizer output
    leak = ("factual_verdict=insufficient_evidence; ev-1; claim c1; "
            "OCR: «текст с картинки»; parts p1 p2; reason_code=source_missing")
    llm = LLM(verbalizer=leak)
    run = await scenario("D leak", claim_text="Утверждение.", llm=llm,
                         refs=[_ref(1)])
    pres = orch.build_presentation(run_to_verdict(run))
    print("PRESENTATION TEXT:", pres.text[:400])
    # D2. digit-free enum leak + raw OCR container
    leak2 = ("factual_verdict=insufficient_evidence; reason_code=source_missing; "
             "внутренняя схема. <chat_context note=\"OCR dump\">сырой "
             "OCR-текст с картинки</chat_context>")
    llm = LLM(verbalizer=leak2)
    run = await scenario("D2 leak digit-free", claim_text="Утверждение.", llm=llm,
                         refs=[_ref(1)])
    pres = orch.build_presentation(run_to_verdict(run))
    print("PRESENTATION TEXT:", pres.text[:400])

    # E. proportional length: short fact vs long publication (same LLM)
    short = LLM(verbalizer="Коротко: не подтверждается.")
    await scenario("E1 short fact", claim_text="2+2=5", llm=short,
                   refs=[_ref(1)])
    long_text = "Сложная публикация. " * 120
    longrun = LLM(verbalizer="Подробный разбор " * 80)
    await scenario("E2 long publication", claim_text=long_text, llm=longrun,
                   refs=[_ref(1), _ref(2)])


def run_to_verdict(run):
    refs = tuple(
        orch.EvidenceRef(
            evidence_id=str(r.get("evidence_id") or ""),
            url=r.get("url"),
            support=str(r.get("support") or ""),
            source_kind=str(r.get("source_kind") or "secondary"),
            published_at=r.get("published_at"),
            claims=((str(r.get("claim_part")),)
                    if r.get("claim_part") else ()))
        for r in (run.evidence_rows or ()))
    return orch.CheckedVerdict(
        verdict_text=run.verdict_text, route="envelope_temporal",
        factual_verdict=run.verdict.factual_verdict,
        temporal_status=run.verdict.temporal_status,
        evaluated_period=run.verdict.evaluated_period,
        uncertainty=run.verdict.uncertainty,
        evidence=orch.EvidenceMap(refs=refs,
                                  allowlist=tuple(r.evidence_id for r in refs)),
        reason_code=run.verdict.reason, as_of=run.verdict.as_of,
        fallback_used=run.fallback_used,
        evidence_refs=tuple(run.verdict.evidence_refs or ()),
        parts=tuple(run.verdict.parts or ()))


if __name__ == "__main__":
    asyncio.run(main())
