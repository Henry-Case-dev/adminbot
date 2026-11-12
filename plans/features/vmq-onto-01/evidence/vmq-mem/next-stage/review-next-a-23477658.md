# Independent review: VMQ-NEXT-03 / VMQ-NEXT-04

Candidate: production `234776589c934024ed0e8dceba189fb9d70d3215` (2.58.198, `release/2.58.198`). Bound to this tree; current `master` is divergent. No product, production, settings, or map changes were made.

## Per-row verdict

| Requirement | Verdict | Evidence and remaining condition |
|---|---|---|
| VMQ-NEXT-03 | PENDING | Focused tests pass and contain positive downstream examples, but inject rows at `_rag_unified_rows`; they do not establish the lexical two-distinct-shared-stems predicate or pool admission. Archive evidence has 0 protected rows in all 34 blocks, making 0 empty blocks conditional on a protected in-pool row vacuous. Needed: same-candidate archive/copy run with an actual 2023-2024 lexical result, product-computed `stems_shared >= 2` in the pool, and `{"selected":[]}` leaving it in the final block; report conditional empty-block count. |
| VMQ-NEXT-04 | PENDING | Selected C2 reading: only lexical period-fill rows are subject to the two-shared-stems threshold; KNN rows are judged by reranking, per `next-stage-design.md` sections 2/4 and the owner's settled interpretation in the map. C1 auto is 0 period rows in both measured runs. C2 auto has 0 lexical period rows, so its threshold result is vacuous. Needed: same-candidate archive/copy run with a C2-auto lexical period row and product-computed `stems_shared` from payload, demonstrating none has `<2`. |

## Measurement review

Read `measure-2026-11-12.md` and raw per-block output. They bind measurement code to `c087253d` (2.58.188), not this review candidate; reused only as facts about that recorded run.

- Empty-verdict archive run: 34/34 blocks empty under both doubles. Protected lexical period rows before/after: 0. Empty blocks with a protected row already in the pool: 0/0, explicitly vacuous. Twenty blocks had KNN period rows in pool and empty selection removed them; this is a different, expected subject-to-rerank case.
- C1 auto: 0 period rows on both runs; measured result.
- C2 auto: 0 period rows and 4 current-year rows on both runs. Under selected lexical-only reading the threshold was not exercised; no positive lexical-row observation.
- Historical delivery on 15 questions: 8/15 historical and 7/15 auto, versus stated 10.11 baseline 6/15 and 6/15; 12.11 baseline remeasurement is 4/15 and 5/15. New measurement improved versus both baselines; repeat runs matched. This does not prove all other NEXT requirements.
- Reranker enabled in measurement, but production model identity was not checked against local `.env`; this limits provider-parity claims, not the counts observed in that harness.

## Test audit and execution

On exact candidate worktree:

`py -m pytest -q -p no:cacheprovider tests/test_memory_period_vector_leg.py::TestBlockIntegration::test_empty_verdict_keeps_row_model_never_saw tests/test_memory_period_vector_leg.py::TestPeriodKeptTelemetry::test_period_kept_despite_empty_stays_separate`

Result: 2 passed in 10.25s. Pytest warned that config options `timeout` and `timeout_method` are unknown in this environment.

The first test asserts a synthetic 2023 `Ремонт ванной` row with `period_fill=True, subject_proxy="stems"` survives empty rerank, while injected current and KNN rows do not; it confirms reranker saw KNN but not lexical. The second asserts a synthetic 2023 lexical row remains and logs `period_kept=1`, `period_kept_despite_empty=1`. These meaningful assertions verify the downstream consumer with a protected row supplied. Neither fixture has `stems_shared`, computes stems from query/text, or invokes lexical retrieval/filter/pool production. They do not prove the complete NEXT-03 contract or NEXT-04 positive C2 boundary.

## Three evidence pillars

- **Implementation:** Inspected `_build_rag_block` consumer path exercised by both tests, the stubbed `_rag_unified_rows` boundary, and settled rule in `next-stage-design.md` sections 2/4: threshold applies only to lexical period rows; KNN is reranker-judged. Tests bypass lexical qualification.
- **Test validity:** Both requested tests executed and assert block content and telemetry, including KNN judged vs injected stems row not judged. Non-vacuous for downstream consumer, insufficient for producer/acceptance seam because pool input is mocked.
- **Independent challenge:** Checked raw archive rows against conditional denominator: all 34 empty blocks had `protected=0`; C1 auto had no period row; C2 auto had no lexical/period row. Positive conditions were not exercised. Targeted run independently confirms injected-row consumer only.

## Verdict

Both rows remain **PENDING / UNVERIFIED for complete acceptance**, not failed product behavior. Missing evidence: positive input through real lexical qualification and pool path, with year and product-computed shared-stem count, observed after empty rerank (NEXT-03) and under C2 auto (NEXT-04). No Builder action is warranted absent a demonstrated product defect. Next action: bounded evidence rerun on existing read-only archive-copy harness ensuring the positive cases occur. No production event is requested or inferred.

## Housekeeping

Targeted pytest was foreground and ended. Candidate worktree is under managed `WorkspaceData/worktrees/`, retained pending parent review handoff. No browser, server, or other subprocess remains active.
