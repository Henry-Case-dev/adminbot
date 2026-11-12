# Workflow State

Task: self-diag-01 (queue 3, P0) — D6 final integration; p0-init-meme-ux-diag is DONE
Task source: plans/owner_inputs/2026-11-12-queue-order-selfdiag-quantum.md + plans/owner_inputs/2026-11-13-selfdiag-stage-correct-closure.md
Status: in_progress
Primary phase: build
Active feature: self-diag-01
Active lanes: Builder ses_e2fdafe9afferLZnhnoGHYg75k (D6: integrate D3+D5, checkup wiring, prompt_readback registration, inspect_runtime analytics/UI)
Join barriers: D6 candidate -> focused Reviewer -> one self-diag release from 2.58.197 -> production verification -> D7 -> DONE -> vmq-onto-01.
Last verified: production 2.58.197 at 2587616759de31283585ffc105c91e7193c2e89e (schema 47, no DDL, rollback c134f93d). Initiative epic DONE: 114/114 (77/77), final release gate errors=0; PB-LLM natural event is non-blocking `WO-258197-PB-LLM-LIVE`. Self-diag: D1 17/17 VERIFIED; D3 34 REVIEW / 2 PENDING (EVD-01 D6, SEM-08 live; B1 security fix 278c19e0 approved, 80/1325); D4-A/B 13 REVIEW / 6 PENDING; D5 15 REVIEW / 6 PENDING; D6 building; D7 PENDING.
Next unlocks: D6 candidate -> Reviewer -> one self-diag release -> bind D1/D3/D4/D5/D6 to deployed SHA -> D7 -> DONE -> vmq-onto-01.
Next execution: awaiting_children
Review: pending
Deployment: verified 2.58.197 @ 25876167 (schema 47, no DDL); rollback c134f93d
Human gate: none
Progress scope: plans/progress_scope.json | initiative DONE 114/114; self-diag D1 17/17, D3 34 REVIEW, D4 13 REVIEW, D5 15 REVIEW, D6 build; source 36/36, queue 40/40
Updated: 2026-11-13T02:30:00+12:00

## Facts

- Stage-correct protocol: REVIEW with candidate-bound independent approval + implementation evidence passes before deployment; production VERIFIED only after deployment; delivery parks genuine future proof; natural/stat/voluntary waits never block.
- D3 B1 security fix: raw `flags.self_diag_repo_origin` with userinfo/token is normalized via existing `source_reader.normalize_repo_origin`; bundle/page/tool result only owner/name; invalid non-empty → None + `invalid_repo_origin`; 80/1325 tests; Reviewer Approved. EVD-12/14 REVIEW.
- D6 must integrate D3 (278c19e0) and D5 (c7b90b26) on top of D4-B 722ccfc5, register `prompt_readback` in `TOOL_CALLING_TOOLS`/`ToolRouter.dispatch`/`diagnostic_policy.prompts.tool_names`, preserve `inspect_runtime` as the 17th tool, wire explicit checkup to `collect_for_checkup()`, render `inspect_runtime` analytics/UI on existing surfaces, and add D6 tests (`tests/test_checkup_contract.py` etc.). No new page/agent/LLM/store/DDL.
- D6/D7 are the last slices; D7 is the golden/delivery evidence, including live Telegram/VPS checks that can be deferred postdeploy under the delivery stage if genuinely future and nonblocking.
- Backlog: `.gitignore:7` deploy_*.py; git log timeout; two pre-existing RED; `TOOL_CATEGORIES` default; send_chunked_reply word >4096; speech `_chat_overrides` fail-open; D3 invalid/empty regression coverage. No critical in-scope defects after B1.
- Owner rules: agents verify, never the owner; no new human gates/queues; no OFF/SHADOW; preserve settings/prompts/models; every fix names the violated requirement; one final map reconciliation.
