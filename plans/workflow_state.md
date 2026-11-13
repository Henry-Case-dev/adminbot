# Workflow State

Task: vmq-onto-01 (queue 4, P0) — NEXT-02 corrective candidate + M1 episodes build; self-diag-01 is delivered_awaiting_evidence
Task source: plans/owner_inputs/2026-11-12-queue-order-selfdiag-quantum.md + plans/owner_inputs/2026-11-13-selfdiag-stage-correct-closure.md + plans/owner_inputs/2026-11-13-vmq-next02-natural-retrieval-metric.md
Status: in_progress
Primary phase: build
Active feature: vmq-onto-01
Active lanes: Builder ses_e2d36bf94ffe557G6z1G6zaqXI (NEXT-02 final: §A FTS + NEXT-05 timings, no §B); Builder ses_e2d15dd9fffeC9TZGu3ulBs4ir (M1 episodes, disjoint files)
Join barriers: NEXT-02 candidate -> Reviewer quality verification -> release; M1 candidate -> Reviewer -> next slices (ONTO-A/B, M2, Q0, Q1, O, U, R).
Last verified: production 2.58.198 at 234776589c934024ed0e8dceba189fb9d70d3215 (schema 47, no DDL, rollback 25876167). Initiative DONE 114/114. Self-diag: 150 VERIFIED / 39 READY / delivery PASS. VMQ: 70 mandatory rows, 1 VERIFIED, 2 REVIEW, 1 FAILED, 66 PENDING; 66-row classification on 2.58.198: 54 REAL_GAP owner-mandated (source-anchored, 0 derived), 9 covered->REVIEW on binding, 1 postrelease (NEXT-01), 2 blocked_external (Q-04/QM-08). Missing body confirmed by Orchestrator: semantic_contracts.py, memory_episodes.py, ibm_quantum_driver.py, qan_pool.py, status-analytics.js absent; random providers only ANU+PRNG.
Next unlocks: NEXT-02 quality review -> release slice -> M1 review -> ONTO-A/B build -> M2 -> Q0/Q0-IBM -> Q1 -> O -> U -> R; future NEXT-01/TIME-09/V live nonblocking.
Next execution: awaiting_children
Review: pending
Deployment: verified 2.58.198 @ 23477658 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | initiative DONE 114/114; self-diag delivered 150/39/0/0; vmq 1/70 (54 owner-mandated gaps); source 36/36, queue 40/40
Updated: 2026-11-13T15:19:00+12:00

## Facts

- Owner decision 2026-11-13: natural retrieval + quality metric; no 2026 cap/year quotas/forced displacement; keep the real FTS fix; no large retrieval refactor or new mechanisms for the metric; year share diagnostic only; 17-question sample too small; finish only if no real mandatory defects.
- NEXT-02 final candidate: §A period-only FTS tokenization repair (real defect: FTS/§2 tokenization mismatch) + NEXT-05 additive knn_ms/fts_ms; §B (pool 33/slot priority) excluded as inert. Paired baseline/candidate quality measurement, strata old/multi-year/recent, no fresh degradation; 58.1 point not a gate.
- VMQ epic body is largely unimplemented: 54 owner-mandated REAL_GAP rows with source anchors (ONTO O-01..04, M-01..05, Q-01..09, QM-01..09, I-01..06, S-01..03, U-01..02, R-01..03, MEM evidence, TIME evidence, NEXT-04). Verified missing on 23477658: semantic_contracts.py, memory_episodes.py, ibm_quantum_driver.py, qan_pool.py, status-analytics.js; mca_random_source has only ANU+PRNG.
- Contracts ready: architecture-next2-quality.md, architecture-onto-ab.md (ARCH_ONTO_AB_READY; memory_contracts.py exists — reuse), architecture-m1-episodes.md (ARCH_M1_READY; mca_episodes.py/mca_episode_jobs.py exist — reuse, no DDL expected).
- NEXT-03 controlled positive confirmed (fact:2242); NEXT-04 PENDING (archive C2 lacks a positive lexical row). VMQ-V deployed 2.58.170 but evidence gap — bind or keep honest gap.
- Natural/future: NEXT-01 live vector turn, TIME-09 events, V-01..V-04 real voice; IBM blocked_external. No owner QA.
- Backlog: .gitignore:7, git log timeout, mca10b 643/644, cfg03 dead knob, two pre-existing RED, 5 direct_fallback_recompose RED, send_chunked_reply >4096 word, speech _chat_overrides fail-open, rejected_subject mixes lexical+KNN.
