# Workflow State

Task: vmq-onto-01 (queue 4, P0) — NEXT-02/05 build + NEXT-03/04 positive evidence; self-diag-01 is delivered_awaiting_evidence
Task source: plans/owner_inputs/2026-11-12-queue-order-selfdiag-quantum.md + plans/owner_inputs/2026-11-13-selfdiag-stage-correct-closure.md
Status: in_progress
Primary phase: build
Active feature: vmq-onto-01
Active lanes: Builder ses_e2e3d0b0fffePKLZU7a8MZv9oD (NEXT-02/05); Builder ses_e2e38efcaffemTSTahpb54HpM7 (NEXT-03/04 positive evidence)
Join barriers: NEXT-02/05 candidate + NEXT-03/04 positive evidence -> Reviewer -> release; natural NEXT-01/TIME-09/V live are postrelease observations.
Last verified: production 2.58.198 at 234776589c934024ed0e8dceba189fb9d70d3215 (schema 47, no DDL, rollback 25876167). Initiative DONE 114/114. Self-diag: 150 VERIFIED / 39 READY / 0 REVIEW / 0 PENDING; delivery PASS, acceptance pending future evidence. VMQ: 1/70 VERIFIED; VMQ-V already deployed (2.58.170) but evidence gap; NEXT-02 measured 2026-share regression; NEXT-05 telemetry absent; contract `architecture-next2.md` froze option 1; NEXT-03/04 Reviewer selected the narrow C2 reading and found no product defect but the positive qualification case is missing; evidence Builder is producing it on the same DB copy; NEXT-02/05 Builder running.
Next unlocks: NEXT-02/05 + positive evidence -> focused Reviewer -> release -> natural postrelease observations.
Next execution: awaiting_children
Review: pending
Deployment: verified 2.58.198 @ 23477658 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | initiative DONE 114/114; self-diag delivered 150/39/0/0; vmq 1/70; source 36/36, queue 40/40
Updated: 2026-11-13T10:01:11+12:00

## Facts

- Self-diag 2.58.198 at 23477658: 150/39/0/0, delivery PASS, acceptance pending future evidence; F3 visual/hard_rules confirmed on prod; golden 100; settings/RBAC/UI; secrets 0. The epic is not falsely DONE.
- VMQ NEXT-02/05 contract: option 1 (lexical priority, slots limit//5, year window before LIMIT, k=32, additive `knn_ms`/`fts_ms` in `usage_json.period_fill`, no DDL); thresholds delivery >=6/15, 2026 share <=58.1%, on-topic >=8/18, irrelevant <28%, p95 <=+400ms; cause of the 2026-share rise remains a hypothesis.
- NEXT-03/04 Reviewer: both tests pass but inject rows directly into `_rag_unified_rows`, bypassing the real two-foundations/lexical qualification; the raw archive had 0 protected period rows in all 34 empty blocks; C1 auto had no period rows; C2 auto had no lexical period row. NEXT-04 narrow reading: threshold only for lexical period rows; KNN rows judged by the reranker. Positive case still missing; evidence Builder is producing it on the same DB copy.
- Natural NEXT-01 (live vector turn), TIME-09 (Status/Analytics events), V-01/V-03 (real voice) are postrelease observations; IBM Q-* `blocked_external`; no owner QA. PM must fix `owner_action_required` V-01/V-03 and the vmq map deployment binding.
- Owner rules: stage-correct REVIEW before deploy; natural/stat/voluntary waits never block; no fake evidence; no owner QA; no new acceptance stage.
