# Workflow State

Task: mod-acl-ux-01 (primary) plus queued MEMORY-08 S4/S5, VMQ-ONTO-01, SELF-DIAG-01
Task source: plans/owner_inputs/2026-11-09-mod-acl-ux-01.md (current_task.md L10016-L10747)
Status: in_progress
Primary phase: implementation
Active feature: mod-acl-ux-01 M2 canonical GLOBAL->CHAT resolver; M5A evidence closure
Active lanes: ses_e40b9e08effeQ074tWJ7jI8ppP (Builder: M2 resolver); ses_e40b9e08dffeOgd0B4siwuykfx (Reviewer: M5A 14 rows)
Join barriers: M2 commit -> review -> deploy; M5A per-row verdict -> bind rows via PM
Last verified: DEPLOYED 2.58.173 @ 17c3a05e (candidate adfd0d0c, parent bee14188, schema 46 unchanged, Δ DDL 0, NRestarts 0, 0 traceback): memory_agi.py and chat_lore.py now use the single canonical deps.user_is_global_admin evaluating role_type over 24 call sites, so a role_type=global_admin owner no longer gets a false 403 on Vector Memory/Embeddings while plain users, chat local admins and moderators still get 403, missing/broken initData gets 401 and cross-chat isolation is unchanged; live probe returned 401 on /api/memory/stats and /api/memory/embeddings with 404 on a nonexistent route as the control
Next unlocks: M2 verdict -> deploy -> before/after impact report on real chats; M5A rows bound -> M5A green; then M3 design freeze, M4A/M4B/M4C UI waves, M5B, M6
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
- 14 M5A §7/§15 rows had no per-row verdict; review in flight now.

## Invariants for the next lanes

- GLOBAL is only an inheritable default; chat tri-state INHERIT/ON/OFF; absent != OFF; stored values are never rewritten by a reader.
- One canonical resolver per capability; no second ACL, catalogue or store; secrets never surfaced.
- New functions are ON by default at first production deploy; disabling a flag is never a quality fix.
- Architect and Reviewer must judge design, Russian copy, real screens and behaviour, not only green tests.
- Deploy only by immutable SHA from a clean release branch; production is 2.58.173.
