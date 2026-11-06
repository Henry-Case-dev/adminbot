# Workflow State

Task: EVOL queue plus EPIC-MEMORY-COGNITIVE-02, MENU-01, RCI and FactCheck clean publication
Task source: plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md, plans/owner_inputs/2026-11-07-context-integrity-factcheck-clean-publication.md
Status: in_progress
Primary phase: pre-release build plus first memory slice review
Active feature: release 2.58.162 scope decided (Variant 1); MEMORY-01 in review
Active lanes: ses_e4d3d73a8ffeon5yEtTOzwZ1KR (DevOps: release build, waiting my go); ses_e4d4bff78ffezMGE6uWaAo0voZ (pin re-approval on current tip); ses_e4d5bb3f7ffeLhdTcQ7xYu5yQ0 (PVR-04 final e2e on db0036a3); ses_e4d3c642effeUtPx0hOHgJrreN (MEMORY-01 Reviewer 5666c0a4)
Line policy: ONE line `integ/unify-release` @ ba8d2b72 (contains release a563ee31 as ancestor, MENU-01 5a503cb4, FactCheck fix 428259e2, observability d8feb2a0, ACL tests 670addc3, pin re-approval 6f38ba37, contracts rev4)
Scope decision (orchestration, not an owner gate): 2.58.162 ships the whole unified line under Variant 1, and the changelog must name the extra content - UR-26.3/26.4/26.5 payload observability and the UR-C-CLOCK deferred-generator refresh, all independently reviewed and bound. No re-cut of persona_short_reply from an older base.
Release prerequisites: pin re-approval merged; full suite run on the release commit; whole-candidate review of the diff vs a563ee31 before deploy; env MINI_APP_REGISTRATION_CONFIRMED=1 + MINI_APP_DEEP_LINK_MODE=main; deploy outside +/-120s of a slot boundary (next boundary 00:00Z)
Verified: prod 2.58.161 @ a563ee31 healthy and unchanged; no migration in this batch (schema stays v42); MENU-01 code Approved; ACL slice Approved; observability Approved (RCI-06 bound); pin re-approval Approved; contracts rev4 unblocked MEMORY-04 and MEM-08-S3; MEMORY-01 candidate 5666c0a4 is two new files, 64 tests, existing files untouched
Next unlocks: (1) MEMORY-01 verdict -> merge; (2) PVR-04 verdict -> merge or fix; (3) pin re-approval -> merge -> release build; (4) whole-candidate review -> deploy 2.58.162 -> postdeploy checks incl. group /menu deep link and initData/ACL runtime evidence
Next execution: awaiting_children
Review: MEMORY-01 in review; PVR-04 Needs Fixes being fixed; release whole-candidate review pending build
Deployment: prod 2.58.161 @ a563ee31 (unchanged); 2.58.162 planned after the sequence above
Human gate: none
Progress scope: plans/progress_scope.json | fresh 2026-11-07 08:58 (13/44 tasks, 289/448 stages, 3749/5340 = 70%); recount after release binding
Updated: 2026-11-07T15:00:00+12:00
