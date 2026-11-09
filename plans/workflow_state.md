# Workflow State

Task: mod-acl-ux-01 (primary) plus queued MEMORY-08 S4/S5, VMQ-ONTO-01, SELF-DIAG-01
Task source: plans/owner_inputs/2026-11-09-mod-acl-ux-01.md (current_task.md L10016-L10747)
Status: blocked
Primary phase: independent reviews blocked by provider capacity
Active feature: mod-acl-ux-01 M2 (committed, unreviewed); self-diag-01 D2 (committed, unreviewed)
Active lanes: none — both reviewer sessions aborted with "Insufficient balance"
Join barriers: provider capacity must return before any review can run; no review means no approval and no deploy
Last verified: TWO REVIEWER SESSIONS ABORTED on a provider balance error and produced no verdict: SELF-DIAG D2 (98bc424e) and MOD-ACL M2 behaviours (dd52cbf9). Nothing was approved, nothing was rejected; both are UNVERIFIED. All work is preserved: integration branch tip dd52cbf9 with a clean product tree (0 dirty product files), production 2.58.174 @ ac943f40 fully verified, schema 46, NRestarts 0.
Next unlocks: after capacity returns — D2 security review, then M2 behaviours review, then PM row binding and the M2 deploy with live observation; M4A UI follows the frozen M3 design
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
