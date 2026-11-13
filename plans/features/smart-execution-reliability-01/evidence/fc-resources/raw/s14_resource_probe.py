"""S14 RED/GREEN probe: observable resource contract of factcheck retrieval.

Run from a project checkout with PYTHONPATH pointing at that checkout:
  python s14_resource_probe.py --json out.json

Exit code 0 always; JSON contains per-check ok/detail. RED on base means
several checks are false; GREEN on candidate means all are true.
"""
import argparse
import asyncio
import dataclasses
import json
import sys

RESULTS = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as exc:          # noqa: BLE001 - probe reports, not raises
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    RESULTS.append({"check": name, "ok": bool(ok), "detail": str(detail)})


def _claim(n):
    return " ".join(f"Факт номер {i} подтверждён изданием {i}."
                    for i in range(1, n + 1))


def _plan(fsp, n):
    claims = tuple(fsp.ClaimUnit(claim_id=f"c{i}",
                                 text=f"Факт номер {i} подтверждён изданием {i}.")
                   for i in range(1, n + 1))
    queries = tuple(fsp.SearchQuery(text=f"факт номер {i} подтверждён изданием {i}",
                                    intent=fsp.INTENT_ENTITY_CHECK,
                                    claim_id=f"c{i}")
                    for i in range(1, n + 1))
    return fsp.RetrievalPlan(queries=queries, needs_web=True,
                             needs_primary_fetch=False,
                             claim_text=" ".join(c.text for c in claims),
                             claims=claims, chat_id=-100777)


class _Agg:
    def __init__(self, chunk):
        self.chunk = chunk
        self.calls = []

    async def search_relevant(self, query, max_symbols, relevance_terms=None,
                              timeout_budget=None, trace=None):
        self.calls.append(query)
        return self.chunk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    from services import factcheck_planner as fsp
    from services import temporal_factcheck as tf

    check("factory_base_seconds_120",
          lambda: (fsp._BUDGET_SECONDS_DEFAULT == 120.0,
                   fsp._BUDGET_SECONDS_DEFAULT))
    check("factory_max_seconds_600",
          lambda: (fsp._BUDGET_SECONDS_MAX == 600.0,
                   fsp._BUDGET_SECONDS_MAX))
    check("factory_refine_24",
          lambda: (fsp._REFINE_CALLS_DEFAULT == 24,
                   fsp._REFINE_CALLS_DEFAULT))
    check("factory_total_queries_64",
          lambda: (fsp._MAX_QUERIES_TOTAL_DEFAULT == 64,
                   fsp._MAX_QUERIES_TOTAL_DEFAULT))
    check("factory_search_chars_100k",
          lambda: (fsp._SEARCH_TEXT_BUDGET_CHARS == 100_000,
                   fsp._SEARCH_TEXT_BUDGET_CHARS))
    check("old_claim_hard_cap_removed",
          lambda: (not hasattr(fsp, "_CLAIM_UNITS_HARD_CAP"),
                   hasattr(fsp, "_CLAIM_UNITS_HARD_CAP")))

    def claim_tail():
        units = fsp.build_claim_units([], _claim(40))
        return len(units) == 40 and units[-1].text.endswith("изданием 40."), \
            len(units)
    check("claim_units_40_tail_kept", claim_tail)

    def temporal_tail():
        env = tf.TemporalClaimEnvelope(
            claim_id="c", chat_id=-100777, target_tg_message_id=1,
            target_revision=1, target_content_hash=None,
            trigger_tg_message_id=2, claim_text=_claim(40), claim_span=None,
            source_type="text", attribution={}, origin_type=None,
            origin_sender_user_id=None, origin_chat_id=None,
            origin_display_name=None, repost_received_at=None,
            original_published_at=None, original_published_precision=None,
            claim_period_from=None, claim_period_to=None,
            claim_period_precision=None, date_source="unknown",
            date_precision="unknown", date_timezone=None,
            date_uncertainty={}, requested_mode="contextual",
            analysis_as_of=1)
        parts = tf.decompose_claim(env)
        return len(parts) == 40 and parts[-1].part_id == "p40", len(parts)
    check("temporal_parts_40_tail_kept", temporal_tail)

    def temporal_queries():
        env = tf.TemporalClaimEnvelope(
            claim_id="c", chat_id=-100777, target_tg_message_id=1,
            target_revision=1, target_content_hash=None,
            trigger_tg_message_id=2, claim_text=_claim(10), claim_span=None,
            source_type="text", attribution={}, origin_type=None,
            origin_sender_user_id=None, origin_chat_id=None,
            origin_display_name=None, repost_received_at=None,
            original_published_at=None, original_published_precision=None,
            claim_period_from=None, claim_period_to=None,
            claim_period_precision=None, date_source="unknown",
            date_precision="unknown", date_timezone=None,
            date_uncertainty={}, requested_mode="contextual",
            analysis_as_of=1)
        parts = tf.decompose_claim(env)
        queries = tf.search_queries_for(parts, env)
        return len(queries) == 10, len(queries)
    check("temporal_queries_no_cap_2", temporal_queries)

    def limits_type():
        limits = fsp.FactcheckLimits()
        return (limits.budgets_enabled and limits.base_seconds == 120.0
                and limits.total_queries == 64 and limits.page_size == 20
                and limits.claim_portion == 32), limits.as_meta()
    check("factcheck_limits_factory_contract", limits_type)

    def off_limits():
        limits = fsp.FactcheckLimits(
            budgets_enabled=False, base_seconds=None, max_seconds=None,
            refine_calls=None, total_queries=None, search_text_chars=None,
            primary_fetches=None, excerpt_chars=None)
        return (limits.base_seconds is None and limits.total_queries is None
                and limits.search_text_chars is None), limits.as_meta()
    check("off_limits_have_no_caps", off_limits)

    def page_20():
        blocks = "\n\n".join(
            f"факт номер 1 подтверждён изданием 1 блок {i}\n"
            f"https://example.org/{i}" for i in range(1, 31))
        limits = fsp.FactcheckLimits(primary_fetches=None)
        outcome = asyncio.run(fsp.run_retrieval(
            _plan(fsp, 1), aggregator=_Agg(blocks), limits=limits,
            refine_calls=0))
        return outcome.refs_collected > 4, outcome.refs_collected
    check("page_size_more_than_old_4", page_20)

    def off_query_cap():
        limits = fsp.FactcheckLimits(
            budgets_enabled=False, base_seconds=None, max_seconds=None,
            refine_calls=None, total_queries=None, search_text_chars=None,
            primary_fetches=None, excerpt_chars=None)
        outcome = asyncio.run(fsp.run_retrieval(
            _plan(fsp, 40), aggregator=_Agg("Борщ рецепт\nhttps://t.example/1"),
            limits=limits))
        return outcome.queries_attempted > 64 and not outcome.budget_exhausted, \
            [outcome.queries_attempted, outcome.budget_exhausted]
    check("off_no_query_cap_64", off_query_cap)

    def off_text():
        big = "факт номер 1 подтверждён изданием 1 " * 5000
        limits = fsp.FactcheckLimits(
            budgets_enabled=False, base_seconds=None, max_seconds=None,
            refine_calls=None, total_queries=None, search_text_chars=None,
            primary_fetches=None, excerpt_chars=None)
        outcome = asyncio.run(fsp.run_retrieval(
            _plan(fsp, 1), aggregator=_Agg(big), limits=limits,
            refine_calls=0))
        return (outcome.search_text == big
                and outcome.search_text_truncated is False), \
            [len(outcome.search_text), outcome.search_text_truncated]
    check("off_no_char_budget", off_text)

    payload = {
        "total": len(RESULTS),
        "passed": sum(1 for r in RESULTS if r["ok"]),
        "failed": [r for r in RESULTS if not r["ok"]],
        "results": RESULTS,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
