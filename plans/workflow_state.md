# Workflow State

Task: smart-execution-reliability-01 (queue 1, P0) — wave 1 rebuild after server restarts; factcheck-request-integrity queued 2
Task source: plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md + plans/owner_inputs/2026-11-14-factcheck-request-integrity-v2.md
Status: in_progress
Primary phase: build
Active feature: smart-execution-reliability-01
Active lanes: Builder ses_e2af337dcffefvOtAdSuwhIacI (A+B resume in smart/ab, 13 dirty files); Builder ses_e2af30078ffehpl2cfxujbQaLf (D resume in smart/d-capacity, 19 dirty); Builder ses_e2af2d747ffeWeLjEX2lWodsci (F resume in smart/f-github, 4 dirty); Reviewer ses_e2af29347ffe2MpD731Z4vZmvK (C1 review of ab42343e)
Join barriers: wave-1 candidates -> review -> wave 2 (C2/C3 evidence, G finalization, E local-first, I1/I2/I4) -> SELF-DIAG H -> acceptance L1-L8 -> one release; then FACTCHECK-REQUEST-INTEGRITY.
Last verified: production 2.58.199 at d20a7f73 (schema 47, no DDL, rollback 25876167); recon committed; map 99 reqs/13 slices; C1 candidate ab42343e (SourceReader caps removed, safety kept; 479 tests; under review). A+B/D/F partial work preserved in their worktrees after repeated server restarts and are being finished in place.
Next unlocks: C1 review + A/B/D/F handoffs -> wave 2 -> H -> release; factcheck amendment mapping after SMART.
Next execution: awaiting_children
Review: C1 pending; A/B/D/F pending
Deployment: verified 2.58.199 @ d20a7f73 (schema 47, no DDL); rollback 25876167
Human gate: none
Progress scope: plans/progress_scope.json | SMART 0/99 (map, all PENDING); self-diag 147/41/16/2; vmq 1/6/0/63; factcheck queued 2; queue 41/41 complete; intake pending factcheck
Updated: 2026-11-14T01:30:00+12:00

## Facts

- Server restarted repeatedly; the sessions for A+B, D and F were terminated by the platform ("will not be resumed automatically"), but their uncommitted work survived in the same worktrees and is being completed in place. C1 completed and is under independent review.
- New owner input captured verbatim: FACTCHECK-REQUEST-INTEGRITY v2, `current_task.md` 13311-13724, sha256 A35EED9F...; the source ends mid-sentence at 13724 (section 4.5 cache) — recorded honestly, nothing invented. Owner order: execute immediately after SMART. Queue position 2, P0, no competing epics.
- Factcheck amendment essentials: normal "фактчек" without clarification is a complete request (no extra focus LLM call); clarification after the command is part of the request; scenarios A-G are acceptance cases, not lexical rules; keep source material/request/subject distinct through suitability, temporal envelope, decomposition, retrieval plan, coverage, attribution, analyst, validator, verbalizer, renderer, cache; fix the `claim_text`/`claim_items` literal check without dropping provenance; temporal/cache/provenance integrity; no new factcheck/search engine/budget system.
- SMART contract and recon facts unchanged: budgets OFF everywhere but tool-chain limits active; capacity 16384 vs 1048576 split; SafeFetch single-snapshot peer mismatch; I2 real backlog; I4 sha256-prefix codes.
- Wave-1 write scopes: smart/ab (budget_gate/tool_loop/direct_execution/settings), smart/d-capacity (model_capacity/settings capacity keys/llm_client/auto_budget/direct_execution), smart/f-github (safe_fetch + tests), smart/c-source (source_reader + tests). Cross-branch conflicts on settings.py/direct_execution.py are expected at integration and must be resolved additively with re-review.
