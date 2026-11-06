# Workflow State

Task: EVOL queue plus EPIC-MEMORY-COGNITIVE-02, MENU-01, RCI (Reply→FactCheck context) and FactCheck clean publication
Task source: plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md, plans/owner_inputs/2026-11-07-context-integrity-factcheck-clean-publication.md
Status: in_progress
Primary phase: pre-release integration and review
Active feature: unified line integ/unify-release (release 2.58.161 + ported MENU-01 + FactCheck fix + ACL tests)
Active lanes: ses_e4d5bb3f7ffeLhdTcQ7xYu5yQ0 (PVR-04 blocker fixes); ses_e4d5606baffeOhzac6ZlhlBzFG (pre-existing pin/CSS test fixes); ses_e4d4f998dffee2Ye2NnL2xagux (observability Reviewer d8feb2a0); ses_e4d4e4f7effepw9AODyuhaS3bi (contracts revision 3)
Line policy: ONE line. `integ/unify-release` (d806ba1f) contains release a563ee31 as ancestor plus ported MENU-01 (5a503cb4), FactCheck fix (428259e2) and ACL tests (670addc3). New work merges here; nothing ships from master or from a bare release branch.
Verified in this line: 168 tests green across menu, factcheck orchestrator, webapp deps, UR-26 payloads, scheduler, PVR backend, FC corrective; tree clean
Checked facts: MENU-01 code approved (reviewer's 8 counterexamples); 8077 successful initData validations, 3 identities, 17 non-admin, 15 missing-initData rejections; production case chat -1002661910336 reconstructed with real IDs; Main Mini App registered (has_main_web_app=true, menu button web_app, t.me?startapp resolves to Open App)
Next unlocks: (1) approvals for PVR-04 fix, observability d8feb2a0, pin fixes -> merge into unified line; (2) contracts revision 3 -> A0 re-audit of summary_memory/database/mca_retrieval_context on this line -> MEMORY-01; (3) release 2.58.162 with MENU-01 + FactCheck fix + ACL tests + env MINI_APP_REGISTRATION_CONFIRMED=1, MINI_APP_DEEP_LINK_MODE=main; (4) postdeploy: real group /menu renders the deep-link button, observe a real startapp launch, non-admin 403 in logs
Next execution: awaiting_children
Review: MENU-01 code Approved; ACL slice Approved; port Approved (code) after doc fixes; PVR-04 Needs Fixes in progress; observability in review
Deployment: prod 2.58.161 @ a563ee31 (unchanged, healthy); planned 2.58.162 from this unified line after approvals
Human gate: none
Progress scope: plans/progress_scope.json | fresh 2026-11-07 08:58 on dev line (13/44 tasks, 289/448 stages, 3749/5340 = 70%); recount after release binding
Updated: 2026-11-07T12:20:00+12:00
