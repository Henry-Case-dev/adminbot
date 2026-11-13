# Workflow State

Task: vmq-onto-01 (queue 4, P0) — final NEXT-02 candidate under owner quality contract; self-diag-01 is delivered_awaiting_evidence
Task source: plans/owner_inputs/2026-11-12-queue-order-selfdiag-quantum.md + plans/owner_inputs/2026-11-13-selfdiag-stage-correct-closure.md + plans/owner_inputs/2026-11-13-vmq-next02-natural-retrieval-metric.md
Status: in_progress
Primary phase: build
Active feature: vmq-onto-01
Active lanes: Builder ses_e2d36bf94ffe557G6z1G6zaqXI (final §A+NEXT-05 candidate from 23477658, no §B); PM ses_e2d368b41ffev0le1hbX6i0jmP (66-row reconciliation under owner decision)
Join barriers: final candidate + row classification -> Reviewer quality verification -> release; future observations nonblocking.
Last verified: production 2.58.198 at 234776589c934024ed0e8dceba189fb9d70d3215 (schema 47, no DDL, rollback 25876167). Initiative DONE 114/114. Self-diag: 150 VERIFIED / 39 READY / 0 REVIEW / 0 PENDING; delivery PASS, acceptance pending future evidence. VMQ: 1/70 VERIFIED, NEXT-03 controlled REVIEW, NEXT-05 timings REVIEW, NEXT-02 FAILED (60.92/62.20% vs 58.1), 66 PENDING under reclassification; §A real FTS tokenization repair confirmed, §B inert and excluded; owner forbids 2026 cap/year quotas/forced displacement and made year share diagnostic-only.
Next unlocks: final candidate -> Reviewer quality verification (M 2.58.198 release) -> PV ep closure decision -> next P0 queue task.
Next execution: awaiting_children
Review: pending
Deployment: verified 2.58.198 @ 23477658 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | initiative DONE 114/114; self-diag delivered 150/39/0/0; vmq 1/70; source 36/36, queue 40/40
Updated: 2026-11-13T14:45:00+12:00

## Facts

- Owner decision 2026-11-13 (vmq NEXT-02): natural retrieval + valid quality metric. Forbidden: artificial 2026 cap, year quotas, forced displacement of fresh relevant facts, threshold lowering, new retrieval mechanisms for the metric, large retrieval refactor. Keep the real FTS fix. Year share = diagnostic. 17-question sample too small (CI 49–71 covers 58.1). Architect revises contract, Reviewer verifies quality, then finish the epic if no real mandatory defects.
- Quality contract `architecture-next2-quality.md`: final candidate = §A period-only FTS tokenization repair + NEXT-05 additive `knn_ms`/`fts_ms`; §B pool-33/slot-priority excluded; paired baseline/candidate on same corpus/queries; old/multi-year/recent strata; no fresh degradation.
- NEXT-02 measured FAIL remains historical fact (60.92/62.20 vs 58.1 point; CI covers threshold; corpus 65% 2026; base slice 78%). Not a gate anymore; not rewritten as PASS.
- NEXT-03 controlled positive independently confirmed (fact:2242, 2023, stems=2, one row, both policies). NEXT-04 PENDING: archive C2 has no positive lexical row; synthetic fixture is not archive evidence.
- VMQ-V deployed in 2.58.170 @ 42f068df but `evidence/vmq-v/` missing — bind deployed evidence or keep honest gap. V-01/V-03 `owner_action_required=false` (agents observe).
- Natural/future: NEXT-01 live vector turn, TIME-09 Status/Analytics events, V-01..V-04 real voice; IBM `blocked_external`. No owner QA.
- Backlog: `.gitignore:7`, git log timeout, mca10b 643/644, cfg03 dead knob, two pre-existing RED, 5 `direct_fallback_recompose` RED, send_chunked_reply word >4096, speech `_chat_overrides` fail-open, `rejected_subject` mixes lexical+KNN.
