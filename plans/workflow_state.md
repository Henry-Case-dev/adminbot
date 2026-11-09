# Workflow State

Task: mod-acl-ux-01 (primary) plus queued MEMORY-08 S4/S5, VMQ-ONTO-01, SELF-DIAG-01
Task source: plans/owner_inputs/2026-11-09-mod-acl-ux-01.md (current_task.md L10016-L10747)
Status: in_progress
Primary phase: independent reviews (security and behaviour)
Active feature: self-diag-01 D2 + mod-acl-ux-01 M2 behaviours
Active lanes: ses_e3fb6c463ffe1xlsgO1YXSVW8E (Reviewer: D2 98bc424e); ses_e3fb6c463ffd9GcMCGI9YEdmRj (Reviewer: M2 dd52cbf9)
Join barriers: D2 verdict -> deploy + live Telegram acceptance; M2 verdict -> PM binding -> deploy with live observation
Last verified: provider capacity restored; both reviews restarted as fresh sessions after the earlier balance aborts (that abort was a platform failure and produced no verdict, so nothing had been approved). Committed work unchanged: integration branch tip dd52cbf9 with a clean product tree, D2 at 98bc424e, production 2.58.174 @ ac943f40 (schema 46, NRestarts 0, fully verified). M2 ledger stood at 23/54 VERIFIED before the behaviours commit; D2 has 40 tests and no review yet.
Next unlocks: D2 verdict -> deploy; M2 verdict -> bind rows -> deploy M2 then observe the live rows; M4A UI against the frozen M3 design
Next execution: none
Review: approved (53c78594, 78a4e017, ebc5a23b); D2 and M2 behaviours UNVERIFIED due to the provider block
Deployment: verified (2.58.174 @ ac943f40, schema 46)
Human gate: none
Progress scope: plans/progress_scope.json | fresh (all 44 owner inputs reconciled)
Updated: 2026-11-09T23:32:00+12:00

## What is done and safe

- Production 2.58.174: the module-route access fix (Vector Memory opens for the owner), the cold-start fix, and the non-2xx observability line. Verified in depth: served bundle matches the commit byte-for-byte, zero tracebacks, schema unchanged, and zero services/ changes so no incomplete work shipped.
- MOD-ACL M2: canonical resolver, tri-state with explicit INHERIT write, separated axes, reason codes, in-flight OFF without replay, consumer inventory, deploy surface note, ten §10 scenarios. Ledger 23/54 verified before the latest behaviours commit.
- SELF-DIAG D2: diagnostic access policy with hard rules before the matrix, live chat-admin verification, revocation before publication, secrets denied everywhere.
- M3 design frozen with its three highest risks recorded.

## Blocked, with the exact reason

- Reviews of 98bc424e and dd52cbf9: provider balance. Do not approve or deploy either commit until an independent review actually runs.
- Deferred earlier for the same honest reason: 14 M5A §7/§15 rows (two provider aborts).

## Owner-side, non-blocking

- Four-step check of Vector Memory on 2.58.174: Modules card → «Настроить»; Analytics → memory panel; F5 on the module address; a plain non-admin account must still be denied.
- One real voice message to close VOICE L-01.
- Time-gated: archive cursor and coverage after the fresh backlog drains, then the first contradiction demotion and the first live application.

## Invariants

- GLOBAL is only an inheritable default; chat tri-state INHERIT/ON/OFF; absent != OFF; readers never rewrite stored values.
- One canonical resolver per capability; hard denies precede any policy matrix; no second ACL, catalogue or store.
- Secrets are never surfaced to anyone, including the owner, in any channel.
- New functions ON by default at first production deploy; disabling a flag is never a quality fix.
- Deploy only by immutable SHA from a clean release branch. Production is 2.58.174.
