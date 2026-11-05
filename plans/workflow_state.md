# Workflow state

Task: REMOVE-LEGACY-REPHRASING-01 (released 2.58.159, DoD observation pending) + UNIFIED-REPLY (UR-A/B live, UR-C partial, UR-D..G open) + BEHAVIOR-GATES-SIMPLIFICATION-01 (BGS-01..04 shipped, 05..08 queued) + PVR-FC-CORRECTIVE-01 (queued) + EPIC-CM-VISUAL-01 (shipped, residual rows open)
Task source: plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md (primary corrective), 2026-11-05-unified-reply.md, 2026-11-05-behavior-gates-simplification.md, 2026-11-05-pvr-fc-corrective-01.md
Status: in_progress
Primary phase: release
Active feature: REMOVE-LEGACY-REPHRASING-01 (2.58.159 deployed; DoD observation pending on first real chat turns)
Active lanes: PM final bindings done (ses_e55d9fba…, ses_e560adb…); none running
Join barriers: DoD RLR-08 lines close on first real chat turns (turn_trace events) + prod observation; UI admin rows wait UR-F/PVR wave
Last verified: prod 2.58.159 @ 5e0cb201 (healthz 2.58.159, NRestarts 0, journal clean, rollback 40a62248 ready); live-model proof R-09 all 8 scenarios (JSON sha256 26cfe4d4…, 47e1e2c3); RLR map 141/162 VERIFIED, release gate errors=21 (4 UI wave UR-F/PVR: R-ADM.1/5/6/7; R-CONF.9 waits BGS-05, R-CONF.12 persona; R-PROC.6/7 process; 13 DoD lines await prod observation)
Next unlocks: (1) observe first real chat turns -> close R-DOD prod/report lines; (2) epic queue: UR-C-CLOCK, UR-D, UR-E, UR-F, BGS-05/06/07/08, PVR-FC
Next execution: awaiting_children
Review: approved (all RLR slices, R-09 live proof); pending (DoD final after prod observation)
Deployment: verified (2.58.159 @ 5e0cb201)
Human gate: none
Progress scope: plans/progress_scope.json | fresh (3540/5173 = 68%)
Updated: 2026-11-05T17:30:00+12:00
