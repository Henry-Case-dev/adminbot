# Workflow State

Task: mod-acl-ux-01 (primary) plus queued MEMORY-08 S4/S5, VMQ-ONTO-01, SELF-DIAG-01
Task source: plans/owner_inputs/2026-11-09-mod-acl-ux-01.md (current_task.md L10016-L10747)
Status: in_progress
Primary phase: live defect repair (owner denied on Vector Memory) plus M2 completion
Active feature: mod-acl-ux-01 (M1 reopened by a live owner report, M2 partially complete, M5A/M5L shipped)
Active lanes: ses_e404c0024ffe6n4ZZ207Awg8AA (Reviewer: M2 completion 3b1ba3b2)
Active lanes: ses_e400398fbffeIPgvk7QzTob6EJ (Reviewer: M2 behaviours dd52cbf9)
Join barriers: M2 verdict -> PM binding -> M2 deploy; SELF-DIAG D2 verdict is BLOCKED by a provider balance failure, not by findings — D2 must not ship unreviewed
Last verified: PLATFORM FAILURE, recorded honestly: the SELF-DIAG D2 security review (98bc424e) aborted with "Insufficient balance" and produced no verdict. Nothing was approved; D2 stays UNVERIFIED and must not be deployed until an independent review actually runs. The same may affect the M2 behaviours review (dd52cbf9), still in flight. M2 behaviours themselves are committed and described as: in-flight OFF with a single side-effect rule and a fresh params read, publish guards at delivery start and immediately before the sender, blocked OFF results never queued, a documented consumer inventory with explicit out-of-domain readers plus a guard test, a deploy-surface note proving no DDL and schema frontier 46, and ten §10 scenarios (double click yields one POST with operation_id, 0 late overwrites over 40 measurements, memory-search OFF isolated per chat). Three deliberate changes await judgement: nostalgia test precondition plus negative, reason-code frontier 325 -> 330, and a re-approved byte-freeze for web/api/routes.py. Production 2.58.174 @ ac943f40 verified
Next unlocks: restore provider capacity -> D2 security review; M2 verdict -> bind -> deploy M2; then M4A UI against the frozen design
Next execution: awaiting_children
Review: approved (53c78594, 78a4e017, ebc5a23b); D2 blocked by provider; M2 behaviours in review
Deployment: verified (2.58.174 @ ac943f40, schema 46)
Last verified: 2.58.174 FULLY VERIFIED on production (ac943f40, release/2.58.174): HEAD matches, NRestarts 0, zero tracebacks (two ERROR lines are the anticliche worker's external-source failures, services/ byte-identical to 2.58.173), served app.js sha256 a47d09d4…ff9e equals both the checkout file and the git blob and differs from 2.58.173, schema still 46 with no new migration, the deployed bundle contains the pending-route mechanism and the server-truth admin check, and `git diff 17c3a05e..HEAD -- services handlers bot.py` is EMPTY on the server, so the incomplete M2 did not ship. Live observability proven with one unauthenticated GET /api/me: exactly one line `[api-status] method=GET path=/api/me status=401 user=- reason=missing_init_data`, no initData, no token, no query. M2 completion is now 3b1ba3b2: the rescue found four real defects in the earlier uncommitted work (opt-in read from a non-existent column causing false consent_required; legacy gates key derived from the ready axis producing a silent OFF; INHERIT broken under a stale optimistic token and resurrected on retry merge; identical-value write losing updated_at/NOTIFY) and one vacuous test replaced; under review now, with the deleted 409 test flagged for independent judgement
Next unlocks: M2 verdict -> row binding -> M2 deploy with live observation of ready/reason, opt_in, inherit idempotency and GLOBAL OFF + CHAT ON; owner recheck of Vector Memory remains pending
Next execution: awaiting_children
Review: approved (53c78594, 78a4e017, ebc5a23b); M2 completion in flight
Deployment: verified (2.58.174 @ ac943f40, schema 46)
Last verified: M2 IS ONLY PARTLY COMPLETE, stated honestly. Nine behaviour rows VERIFIED at 97cfdef1, three rows bound to the production impact report (reports/m2-impact-production-17c3a05e.md, sha256 f18dc7dc…a35f: 16 capabilities, 3 profiles including the owner's personal chat, 0 changed pairs, read-only proven by identical counters and schema 46), eleven catalogue/UI rows reassigned to M3/M4A with rationale. Scoped gate 54 -> 42 errors, all `mandatory not VERIFIED`; 27 genuine engineering gaps are being implemented now (state playback fields, ready composition, authorized axis, consent_required/permission_denied, gate-incompatibility diagnostics, explicit INHERIT write path, opt-in, consumer inventory, hot-config preservation, OFF/ON and the twelve §10 scenarios).
Next unlocks: cold-start verdict -> deploy batch -> owner recheck; M2 gaps -> full M2 verdict -> deploy M2 with the (currently zero-change) per-chat impact table; then M3/M4 waves, M5A row verdicts, SELF-DIAG D2, VMQ ONTO-A/B
Next execution: awaiting_children
Review: approved (adfd0d0c, c51933d0, d0127c29, b8617cbb, f71dfb56, 2779059b, 78a4e017); cold-start fix in flight; M2 conditional
Deployment: verified (2.58.173 @ 17c3a05e, schema 46); batch with the route fix not yet released
Human gate: none
Progress scope: plans/progress_scope.json | fresh (all 44 owner inputs reconciled)
Updated: 2026-11-09T21:05:00+12:00

## Queue state

- MOD-ACL-UX-01: M1 reopened by the owner's live report (fix in review), M2 partial, M5A/M5L shipped; M3 design freeze and M4A/B/C UI waves not started.
- MEMORY-08: S1-S3 shipped. S4 and S5 not started.
- VMQ-ONTO-01: VMQ-V shipped; L-01 needs one real owner voice message. ONTO-A/B and Q0 not started.
- SELF-DIAG-01: D1 shipped and verified live. D2 access policy is next.

## Deferred with reason

- M5A per-row verdict (14 §7/§15 rows): two consecutive provider aborts, no output, UNVERIFIED. Resume in smaller batches; do not retry in the same window.

## Owner-side, non-blocking

- After the batch ships: open Vector Memory in the Mini App, check «Модули» → card → «Настроить», «Аналитика → Память и интеллект», F5 on the module address, and a plain non-admin account still denied.
- One real voice message to close VOICE L-01.
- Time-gated: archive cursor/coverage after the fresh backlog drains, then first contradiction demotion and first live application.

## Invariants

- GLOBAL is only an inheritable default; chat tri-state INHERIT/ON/OFF; absent != OFF; readers never rewrite stored values.
- One canonical resolver per capability; no second ACL, catalogue or store; secrets never surfaced anywhere.
- New functions ON by default at first production deploy; disabling a flag is never a quality fix.
- Architect and Reviewer judge design, Russian copy, real screens and behaviour, not only green tests.
- Deploy only by immutable SHA from a clean release branch. Production is 2.58.173.
