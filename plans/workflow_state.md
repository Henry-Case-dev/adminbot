# Workflow State

Task: vmq-onto-01 (queue 4, P0) — corrected NEXT-02 build + map bookkeeping; self-diag-01 is delivered_awaiting_evidence
Task source: plans/owner_inputs/2026-11-12-queue-order-selfdiag-quantum.md + plans/owner_inputs/2026-11-13-selfdiag-stage-correct-closure.md
Status: in_progress
Primary phase: build
Active feature: vmq-onto-01
Active lanes: Builder ses_e2e072317ffcZMrD78uraomsl7 (corrected NEXT-02); PM ses_e2dff8767ffeZAd8PdMLd3e0fV (vmq map NEXT statuses)
Join barriers: corrected NEXT-02 candidate + valid paired measurement -> Reviewer -> release; NEXT-04 PENDING; NEXT-03 controlled REVIEW; NEXT-05 timings REVIEW; natural NEXT-01/TIME-09/V live postrelease.
Last verified: production 2.58.198 at 234776589c934024ed0e8dceba189fb9d70d3215 (schema 47, no DDL, rollback 25876167). Initiative DONE 114/114. Self-diag: 150 VERIFIED / 39 READY / 0 REVIEW / 0 PENDING; delivery PASS, acceptance pending future evidence. VMQ: 1/70; NEXT-03 controlled positive independently confirmed (fact:2242, 2023, stems=2, one row, period_kept=1, both policies); NEXT-04 PENDING (archive C2 lacks a positive lexical row); NEXT-05 timings pass; NEXT-02 FAILED (2026 share 61.63/61.84 vs 58.1; base retrieval produces the 2026 numerator; FTS/§2 tokenization mismatch; 15-question CI 50–73% covers the threshold); corrected Builder implementing FTS tokenization + bounded historical augmentation, threshold unchanged.
Next unlocks: corrected candidate + valid measurement -> Reviewer -> release -> natural postrelease observations; NEXT-04 remains PENDING unless a real archive row appears.
Next execution: awaiting_children
Review: pending
Deployment: verified 2.58.198 @ 23477658 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | initiative DONE 114/114; self-diag delivered 150/39/0/0; vmq 1/70; source 36/36, queue 40/40
Updated: 2026-11-13T11:03:39+12:00

## Facts

- NEXT-03 is confirmed only on the controlled question, not the original 17; the independent rerun on both policies leaves exactly one row fact:2242 (2023, stems=2), period_kept=1, despite_empty=1. NEXT-04 is PENDING; the archive C2 has no positive lexical row (10 lexical all shared=1; FTS top-64 old rows all shared=1); the synthetic fixture confirms the mechanism but is not archive evidence.
- NEXT-05 timings pass (32/32, knn 190–233 ms, fts 6–55 ms, p95 1172/1156 vs 1618); additive fields, no DDL.
- NEXT-02 real cause: FTS tokenizes short tokens; §2 drops <4 chars and requires 2 exact stems; 97/191 rows entered only via a discarded token; 0 lexical accepted; all rendered period rows KNN; 2026 numerator is base retrieval (56/56), base slice 78% 2026; corpus 65%; a single FTS fix gives ~2–3 rows vs needed +9; option-1 slot priority was a no-op. The 15-question metric CI 50–73% covers 58.1; the corrected contract requires a valid paired measurement and bounded historical augmentation without lowering the threshold.
- VMQ-V is already deployed (2.58.170) but has an evidence gap; V-01/V-03 `owner_action_required` must be false; the map's 952b9ebd is historical, current production 23477658. PM is fixing the map.
- Owner rules: stage-correct REVIEW before deploy; natural/stat/voluntary waits never block; no fake evidence; no owner QA; no new acceptance stage.
