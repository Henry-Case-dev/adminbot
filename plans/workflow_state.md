# Workflow State

Task: existing EVOL queue plus EPIC-MEMORY-COGNITIVE-02, MENU-01, EVOL-REPLY-CONTEXT-INTEGRITY-01 and FactCheck clean publication
Task source: plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md, plans/owner_inputs/2026-11-07-context-integrity-factcheck-clean-publication.md
Status: in_progress
Primary phase: self-diagnosis plus independent review
Active feature: FactCheck case reconstruction, Mini App registration state, PVR-04 review, Reply-context fix, memory contracts
Active lanes: ses_e4d6625c1ffe3bZ1egfWTtgKxP (DevOps: case trace from DB/history); ses_e4d6625c0ffe9NpogSnZfc6NDk (Builder: real Mini App registration state); ses_e4d689386ffehSocz2LnRxAD89 (PVR-04 Reviewer 350cb228); ses_e4d6bd0a2ffeJmlQzFc7Em3tfx (Reply-context builder RCI-02..04); ses_e4d6badebffe6i6qMl41vzdKVy (Architect memory contracts)
Join barriers: MENU-01 code rows already bound to approved 14400b73 (6 VERIFIED, 4 READY_FOR_LIVE) - live rows must be re-classified from registration-state evidence, not assumed missing; production case must be located from project data before any external request
Policy correction: PENDING_EXTERNAL is reserved for proven unreachable dependencies. NOT_VERIFIED (insufficient evidence) and CONFIRMED_MISSING (proven absent setting) are distinct and must not be conflated; agents must exhaust local DB/history/diagnostics first
Last verified: prod 2.58.161 @ a563ee31 (healthz 2.58.161; migration v42; rollback 2.58.160 @ 309f69c2); MENU-01 code part Approved on 14400b73 with 6 rows bound; earlier bound: UR-C-SCHED, FC-BACKEND 27, PVR-BACKEND 25, PVR-UI 6, UR-23.4, UR-26.3/26.4/26.5
Next unlocks: (1) case trace -> fix + Reviewer -> bind RCI rows; (2) registration state -> re-classify MENU-01.4/6/9/10 honestly; (3) PVR-04 verdict -> bind proven rows; (4) contracts.md -> start MEMORY-01
Next execution: awaiting_children
Review: in flight (PVR-04 350cb228); MENU-01 code approved
Deployment: current prod 2.58.161 @ a563ee31 (verified; rollback 2.58.160 @ 309f69c2)
Human gate: none
Progress scope: plans/progress_scope.json | fresh 2026-11-07 08:36 (11/30 tasks, 229/329 stages, 2564/3029 required = 84%; recounted after MENU bind in next checkpoint)
Updated: 2026-11-07T09:15:00+12:00
