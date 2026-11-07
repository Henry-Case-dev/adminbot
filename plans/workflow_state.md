# Workflow State

Task: EVOL queue plus EPIC-MEMORY-COGNITIVE-02, MENU-01, RCI and FactCheck clean publication
Task source: plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md, plans/owner_inputs/2026-11-07-context-integrity-factcheck-clean-publication.md
Status: in_progress
Primary phase: post-release observation plus memory epic implementation
Active feature: 2.58.162 deployed and verified; MENU-01 live rows awaiting a natural group /menu invocation
Active lanes: none blocking; next dispatch = merge MEMORY-03 and bind its rows
Deployment: prod 2.58.162 @ 8af1b10a (branch release/2.58.162, pushed tip ed2b059d = docs-only above the deployed commit). healthz 2.58.162, NRestarts 0, tracebacks 0, SQLite user_version 42 unchanged, slot_claims present, served app.js sha256 705a28cd... identical to 2.58.161 (web/** untouched), gate REG_CONFIRMED=True MODE=main SHORT_NAME empty, bot username PERMsoc_bot valid, zero `mca_event unmapped` and zero `short_reply: raw context stripped`, ledger 1395 rows and no write errors. Rollback = a563ee31 + restart; MINI_APP_* inert on old code; .env backup .env.bak-258162-20261107005407
Release content: MENU-01 group deep link + honest fallback; FactCheck ambiguous-context fix; FactCheck ambiguity observability (real reason codes, unmapped marker, clarify reply in ledger); TMA group-launch ACL tests; UR-26.3/26.4/26.5 payload observability; summary deferred-generator clock refresh; MEMORY-01 inert types. No migration, schema v42
Review record: whole-candidate Approved on ba24268d (106 files, nothing unreviewed, database.py/summary_memory.py/mca_retrieval_context.py byte-identical to prod); targeted Approved on 8af1b10a (raw-context stripper now only strips diagnostic forms; ordinary phrases byte-identical)
Failure classification: 93 release failures -> 87-88 reproduce on a563ee31 (pre-existing debt, individually verified), 5 caused by the version bump/env-only settings and fixed (4 JS version pins + catalog coverage exclusion backed by a new closed pin), 1 parametrised id uncollectable on both lines
Binding done: MENU-01 7 VERIFIED + 3 READY_FOR_LIVE (01.6/01.9/01.10 need an observed real group /menu launch), RCI-01..06 VERIFIED, MEMORY-01 VERIFIED
Open next: (1) merge MEMORY-03 640cd818 into the line and bind MEM-03.3/03.4/03.9; (2) MEMORY-02 identity with schema v43; (3) PVR-04 blocker fixes verdict; (4) observe a natural group /menu to close MENU-01.6/9/10; (5) MEMORY-04 destructive episode merge rewrite; (6) MEM-08-S3 client corrections
Next unlocks: MM03 merge -> map binding -> MEMORY-02 (v43 additive) -> MEMORY-06 retrieval -> MEMORY-08-S1..S5
Next execution: runnable
Review: approved (whole release + targeted fix); MEMORY-03 approved by review, pending merge/binding
Human gate: none
Progress scope: plans/progress_scope.json | fresh 2026-11-07 10:28 (13/44 tasks, 291/448 stages, 3756/5341 = 70%); recount after merge bindings
Updated: 2026-11-07T23:05:00+12:00
