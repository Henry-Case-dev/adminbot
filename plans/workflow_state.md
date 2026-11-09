# Workflow State

Task: mod-acl-ux-01 (primary) plus queued MEMORY-08 S4/S5, VMQ-ONTO-01, SELF-DIAG-01
Task source: plans/owner_inputs/2026-11-09-mod-acl-ux-01.md (current_task.md L10016-L10747)
Status: in_progress
Primary phase: live defect repair (owner denied on Vector Memory) with M2 in flight
Active feature: mod-acl-ux-01 M1 acceptance reopened; M2 canonical GLOBAL->CHAT resolver
Active lanes: ses_e40ae0c96ffe5ck1vdStihqHwA (DevOps: prod facts for the denial); ses_e40ae0c92ffe2rTm4OYsomqmJi (Builder: gate map); ses_e40b9e08effeQ074tWJ7jI8ppP (Builder: M2 resolver)
Join barriers: prod facts + gate map -> targeted fix -> review -> deploy -> owner recheck; M2 commit -> review; M5A per-row verdict -> bind rows
Last verified: OWNER REPORTED the real regression: the Vector Memory section still denies access after 2.58.173, Telegram ID 5885953495. M1 is therefore NOT accepted on unit tests alone; its rows must be reopened by PM once the denying gate is identified. Recorded verbatim in plans/owner_inputs/2026-11-09-vector-memory-denied-live.md (sha256 D7048A7C…6E0A). 2.58.173 @ 17c3a05e is otherwise healthy (schema 46, NRestarts 0, 0 traceback) and its code-level fix is real but evidently insufficient: another gate denies the owner
Next unlocks: denial root cause -> minimal fix -> independent review -> deploy -> owner recheck of the same section; then M2 verdict/deploy, M5A row binding, M3/M4 waves
Next execution: awaiting_children
Review: approved (adfd0d0c, c51933d0, d0127c29, b8617cbb, f71dfb56, 2779059b); M5A rows in review
Deployment: verified (2.58.173 @ 17c3a05e, schema 46)
Human gate: none
Progress scope: plans/progress_scope.json | stale
Updated: 2026-11-09T19:46:00+12:00

## Queue state

- MOD-ACL-UX-01: M0 baseline, M1 ACL false-403 and M5A/M5L experience work are done and shipped; M2 is the first backend stage that changes user-visible effective state.
- MEMORY-08: S1-S3 shipped (read model, search endpoint, omnibox with gate ON). S4 (focus/ego-network/back-stack/inspector/context actions) and S5 (gold set >=60, p50/p95, cursor_stale rate, screenshots) are not started.
- VMQ-ONTO-01: VMQ-V voice shipped; L-01 needs one real owner voice message. ONTO-A/B and Q0 not started.
- SELF-DIAG-01: D1 shipped and verified live (systemd invocation aa277a53..., no provider client in the fetcher). D2 access policy is next.

## Owner-side and time-gated items

- Owner: open Vector Memory and Embeddings in the Mini App under the real Telegram ID; a second non-admin account must still be denied. Non-blocking for engineering.
- Owner: one real voice message to close VOICE L-01 (transcript_status=ready, revision>=1, non-empty text, Writer block).
- Time: archive cursor/coverage appears after the fresh backlog drains (~2 days, backlog 15,628 rows). Then first contradiction demotion, first re-confirmation +0.1, first live application.
- 14 M5A §7/§15 rows had no per-row verdict; two reviewer attempts aborted at the provider with no output, so they are UNVERIFIED and deliberately deferred (not failed, not accepted) until the owner-facing denial is resolved. Do not retry a third time in the same window; split the rows into smaller batches when resumed.

## Deferred, with reason

- M5A per-row verdict (14 rows): two consecutive provider aborts; no verdict was produced and nothing was counted.

## Invariants for the next lanes

- GLOBAL is only an inheritable default; chat tri-state INHERIT/ON/OFF; absent != OFF; stored values are never rewritten by a reader.
- One canonical resolver per capability; no second ACL, catalogue or store; secrets never surfaced.
- New functions are ON by default at first production deploy; disabling a flag is never a quality fix.
- Architect and Reviewer must judge design, Russian copy, real screens and behaviour, not only green tests.
- Deploy only by immutable SHA from a clean release branch; production is 2.58.173.
