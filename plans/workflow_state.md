# Workflow State

Task: existing EVOL queue plus EPIC-MEMORY-COGNITIVE-02, MENU-01, EVOL-REPLY-CONTEXT-INTEGRITY-01 and FactCheck clean publication
Task source: plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md, plans/owner_inputs/2026-11-07-context-integrity-factcheck-clean-publication.md
Status: in_progress
Primary phase: integration to the production line plus runtime diagnosis
Active feature: porting MENU-01 and the FactCheck fix onto evol/impl; case trace; Mini App runtime evidence; PVR-04 review
Active lanes: ses_e4d63f508ffe5ZYXIfq2wpDRuq (integration onto evol/impl); ses_e4d6625c1ffe3bZ1egfWTtgKxP (case trace from project DB/history); ses_e4d6625c0ffe9NpogSnZfc6NDk (initData/ACL code evidence); ses_e4d65b09dffeJgprwSehh7YP1Q (runtime launch evidence); ses_e4d689386ffehSocz2LnRxAD89 (PVR-04 Reviewer 350cb228)
Line divergence (verified): master lacks web/api/cognitive_map.py, web/static/cognitive-map.js, services/chat_clock.py and migrations v41-v42; all shipping work must land on evol/impl (tip 2c1af33e). factcheck_orchestrator.py, its cfg06 test and config/settings.py differ between lines; handlers/menu.py and tests/test_menu.py are identical
Join barriers: MENU-01 code approved at 14400b73 (master base) but must be re-verified after the port; FactCheck fix 1703ff46 needs port + independent review on the ported SHA; PVR-04 pending verdict; contracts.md frozen, MEMORY-01 may start only after the contract check
Policy correction: PENDING_EXTERNAL only for proven unreachable dependencies. Agents must exhaust local DB/history/diagnostics; NOT_VERIFIED (insufficient evidence) and CONFIRMED_MISSING (proven absent setting) stay distinct. MENU-01 registration is owner-confirmed present, so no owner action is outstanding there
Last verified: prod 2.58.161 @ a563ee31 (healthz 2.58.161; migration v42; rollback 2.58.160 @ 309f69c2); MENU-01 map 7 VERIFIED + 3 runtime-pending with review gate errors=0; earlier bound: UR-C-SCHED, FC-BACKEND 27, PVR-BACKEND 25, PVR-UI 6, UR-23.4, UR-26.3/26.4/26.5
Next unlocks: (1) integration SHA -> re-run gates -> bind ported candidates; (2) case trace -> confirm loss stage on real data -> close RCI-01; (3) runtime launch evidence -> close MENU-01.6/9/10; (4) PVR-04 verdict -> bind; (5) contract check -> start MEMORY-01
Next execution: awaiting_children
Review: in flight (PVR-04 350cb228); MENU-01 code approved on master base, ported review pending
Deployment: current prod 2.58.161 @ a563ee31 (verified; rollback 2.58.160 @ 309f69c2)
Human gate: none
Progress scope: plans/progress_scope.json | fresh 2026-11-07 08:43 (11/30 tasks, 229/329 stages, 2571/3029 required = 85%; 12 postdeploy waits)
Updated: 2026-11-07T09:45:00+12:00
