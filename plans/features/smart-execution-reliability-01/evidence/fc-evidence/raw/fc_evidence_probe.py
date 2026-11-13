"""S15-FC-EVIDENCE probe: сквозная доставка evidence до analyst/validator.

Прогон воспроизводит сборку payload'ов на фактическом кандидате и печатает
JSON с измерениями по звену «evidence → analyst payload»:

* сколько refs собрано retrieval'ом и сколько строк доставлено;
* сколько символов поддержки реально попало в payload;
* какие caps сработали (support-обрезка, число строк);
* виден ли scope/portion (search_text) аналитику;
* размер payload и ёмкость фактического маршрута (capacity resolver);
* что уходит в БД (`record_temporal_run`), чтобы сравнить с payload.

Запуск (из корня worktree):

    python plans/features/smart-execution-reliability-01/evidence/fc-evidence/raw/fc_evidence_probe.py

Ничего не пишет в БД и сеть; LLM/агрегатор — заглушки.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.getcwd())

import services.temporal_factcheck as tf  # noqa: E402
from services import factcheck_orchestrator as orch  # noqa: E402
from services import factcheck_planner as fsp  # noqa: E402
from services import model_capacity as mc  # noqa: E402
from services.factcheck_service import FactCheckService  # noqa: E402

ANALYST_OK = json.dumps({
    "factual_verdict": "insufficient_evidence",
    "temporal_status": "unknown",
    "evaluated_period": {"from": None, "to": None},
    "reason": "probe",
    "parts": [],
}, ensure_ascii=False)
VALIDATOR_AGREE = json.dumps(
    {"agree": True, "corrected_factual_verdict": None,
     "corrected_temporal_status": None, "note": "ok"},
    ensure_ascii=False)


class RoutedLLM:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def generate(self, messages, **kwargs):
        step = str(kwargs.get("step") or "")
        self.calls.append((step, messages[1]["content"]))
        if step in ("temporal_verdict", "temporal_fallback"):
            return ANALYST_OK
        if step == "temporal_validator":
            return VALIDATOR_AGREE
        return "Проверка: данных недостаточно (probe)."


def _env():
    return tf.TemporalClaimEnvelope(
        claim_id="tcl-s15", chat_id=1, target_tg_message_id=10,
        target_revision=1, target_content_hash="h1",
        trigger_tg_message_id=11,
        claim_text="В стране X традиция существует без внешнего влияния",
        claim_span=None, source_type="text", attribution={"author": "A"},
        origin_type="channel", origin_sender_user_id=None,
        origin_chat_id=-777, origin_display_name="A",
        repost_received_at=1760000000, original_published_at=1665277000,
        original_published_precision="day", claim_period_from=None,
        claim_period_to=None, claim_period_precision=None,
        date_source="telegram_origin", date_precision="day",
        date_timezone=None, date_uncertainty={}, requested_mode="contextual",
        analysis_as_of=1760000000)


def _refs(n: int, support_chars: int):
    refs = []
    for i in range(n):
        body = (f"Источник {i}: традиция в стране X documented practice "
                f"без внешнего влияния. ") + ("данные " * (support_chars // 6))
        refs.append(orch.EvidenceRef(
            evidence_id=f"ev-{i + 1}",
            url=f"https://source{i}.example/page",
            support=body[:support_chars],
            source_kind="secondary",
            published_at=1665277000,
            claims=("c1",)))
    return tuple(refs)


def _coverage(parts: int):
    rows = []
    for i in range(parts):
        unit = fsp.ClaimUnit(
            claim_id=f"c{i + 1}", text=f"часть тезиса {i + 1}",
            claim_type=fsp.CLAIM_TYPE_FACT)
        rows.append(fsp.ClaimCoverage(
            claim=unit,
            search_status=fsp.CLAIM_SEARCH_SEARCHED,
            status_detail=fsp.CLAIM_STATUS_PARTIAL,
            outcome=fsp.CLAIM_OUTCOME_PARTIAL,
            evidence=(fsp.ClaimEvidence(
                claim_id=unit.claim_id, evidence_id="ev-1",
                url="https://source0.example/page",
                role=fsp.EVIDENCE_ROLE_SUPPORTS, note="probe",
                opened=True),),
            citation_ids=("ev-1",),
            queries_count=1, candidates=1, opened=1))
    return tuple(rows)


def _outcome(refs, *, search_chars: int, portions: int, coverage=()):
    text = ("фрагмент выдачи " * (search_chars // 16))[:search_chars]
    return fsp.RetrievalOutcome(
        evidence_map=orch.EvidenceMap(
            refs=tuple(refs),
            allowlist=tuple(r.evidence_id for r in refs)),
        search_text=text,
        queries_attempted=8, queries_used=8, refs_collected=len(refs),
        fetch_errors=0, budget_exhausted=False, provider_failures=0,
        empty_results=0, irrelevant_results=0,
        claims=coverage,
        stop_reason="sufficient_evidence",
        search_text_portions=tuple([text] * portions),
        search_text_total_chars=len(text) * portions,
        search_text_truncated=portions > 1)


class CaptureDB:
    def __init__(self):
        self.evidence = None

    async def record_factcheck_run(self, payload):
        self.run = payload

    async def record_factcheck_evidence(self, run_id, rows, *, max_rows=20):
        self.evidence = {"rows": len(rows), "max_rows": max_rows,
                         "supports": [len(str(r.get("support") or ""))
                                      for r in rows]}
        return len(rows[:max(0, int(max_rows))])


def _section_chars(payload: str, tag: str) -> int:
    start = payload.find(f"<{tag}>")
    end = payload.find(f"</{tag}>")
    if start < 0 or end < 0:
        return 0
    return end - start


def _evidence_id_count(payload: str) -> int:
    return payload.count("[ev-")


async def run_case(name: str, *, n_refs: int, support_chars: int,
                   search_chars: int, portions: int, claims: int):
    llm = RoutedLLM()
    service = FactCheckService(aggregator=None, llm=llm)
    outcome = _outcome(_refs(n_refs, support_chars),
                       search_chars=search_chars, portions=portions,
                       coverage=_coverage(claims))
    run = await service.check_claim_envelope(_env(), retrieval=outcome)
    db = CaptureDB()
    await tf.record_temporal_run(db, run, scope="global")

    by_step = {}
    for step, user in llm.calls:
        by_step.setdefault(step, []).append(user)
    analyst = by_step.get("temporal_verdict", [""])[0]
    validator = by_step.get("temporal_validator", [""])[0]
    verbalizer = by_step.get("temporal_verbalize", [""])[0]

    window_tokens, window_source = mc.resolve_evidence_window_tokens()
    budget_chars = mc.evidence_window_for_tokens(window_tokens)

    return {
        "case": name,
        "input": {
            "refs": n_refs,
            "support_chars_each": support_chars,
            "refs_total_chars": sum(len(r.support) for r in outcome.evidence_map.refs),
            "search_text_chars": len(outcome.search_text),
            "search_text_portions": len(outcome.search_text_portions),
            "claims": claims,
        },
        "delivery": {
            "analyst_evidence_rows": _evidence_id_count(analyst),
            "analyst_evidence_section_chars": _section_chars(analyst, "evidence"),
            "analyst_payload_chars": len(analyst),
            "validator_evidence_rows": _evidence_id_count(validator),
            "validator_evidence_section_chars": _section_chars(validator, "evidence"),
            "validator_payload_chars": len(validator),
            "verbalizer_payload_chars": len(verbalizer),
            "search_text_in_analyst": bool(outcome.search_text
                                           and outcome.search_text[:200] in analyst),
            "evidence_meta_present": "<evidence_delivery" in analyst,
        },
        "capacity": {
            "resolved_window_tokens": window_tokens,
            "window_source": window_source,
            "evidence_budget_chars": budget_chars,
            "capacity_used": False,
        },
        "db": {
            "evidence_rows": (db.evidence or {}).get("rows"),
            "db_max_rows": (db.evidence or {}).get("max_rows"),
            "support_chars_stored": (db.evidence or {}).get("supports"),
        },
        "run_evidence_rows": len(run.evidence_rows),
        "run_evidence_support_chars": [len(str(r.get("support") or ""))
                                       for r in run.evidence_rows],
    }


async def main():
    results = [
        await run_case("wide-60refs", n_refs=60, support_chars=2000,
                       search_chars=100_000, portions=1, claims=8),
        await run_case("fb-single", n_refs=1, support_chars=420,
                       search_chars=400, portions=1, claims=4),
        await run_case("small-3refs", n_refs=3, support_chars=500,
                       search_chars=3000, portions=1, claims=2),
    ]
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
