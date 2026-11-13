# Workflow State

Task: smart-execution-reliability-01 (queue 1, P0) — core waves + FACTCHECK amendment as final stage group
Task source: plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md + plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2-full.md
Status: in_progress
Primary phase: build
Active feature: smart-execution-reliability-01
Active lanes: Builder ses_e2af337dcffefvOtAdSuwhIacI (A+B resume); Builder ses_e2af30078ffehpl2cfxujbQaLf (D resume); Builder ses_e2af2d747ffeWeLjEX2lWodsci (F resume); Reviewer ses_e2af29347ffe2MpD731Z4vZmvK (C1 review ab42343e); PM ses_e2aefa2b4ffetaPmkyT5RnZgfj (FACTCHECK amendment mapping into SMART)
Join barriers: wave-1 handoffs -> review -> wave 2 (C2/C3, G, E, I1/I2/I4) -> H -> FACTCHECK slices -> acceptance L1-L8 + 12.1-12.8 -> one release + smoke.
Last verified: production 2.58.199 at d20a7f73 (schema 47, no DDL, rollback 25876167); recon committed; SMART map 99 reqs/13 slices (all PENDING); C1 candidate ab42343e under review; A+B/D/F partial work resumed in place after repeated server restarts.
Next unlocks: C1 review + A/B/D/F handoffs -> wave 2 -> H -> FACTCHECK mapping/build -> one release.
Next execution: awaiting_children
Review: C1 pending; A/B/D/F pending
Deployment: verified 2.58.199 @ d20a7f73 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | SMART 0/99 (factcheck amendment mapping pending); self-diag 147/41/16/2; vmq 1/6/0/63; queue 40/40 complete
Updated: 2026-11-14T01:25:00+12:00

## Facts

- FACTCHECK-REQUEST-INTEGRITY v2 FULL is an amendment INSIDE SMART (§0/§10.1), not a separate task; the standalone registration was removed, queue restored to 40/40. It executes after the SMART core stages. Full source captured verbatim (current_task.md 13311-14702, 1392 lines, sha 767BAF0A…); the earlier truncated capture is superseded history.
- Amendment essentials: normal "фактчек" without clarification is complete (no extra focus LLM call); clarification is part of the request (A–G acceptance cases, never lexical rules); source material/request/subject stay distinct across all stages; fix `_claim_units` literal `claim_text` check without losing provenance; cache identity by subject; new factory defaults 120 s/600 s/24/64 (policy at budgets ON only), 100k chars/20 results/32 claim units as portion sizes, not hard caps or minimum research; budgets OFF disables enforcement; no new factcheck/search engine/budget system; acceptance 12.1–12.8; DoD 14–15.
- Server restarts killed A+B/D/F sessions repeatedly; uncommitted work survived in the same worktrees and is being completed in place (commits early). C1 is complete and under review.
- Wave-1 scopes remain disjoint; expected integration conflicts on settings.py/direct_execution.py between A+B and D must be resolved additively and re-reviewed.
