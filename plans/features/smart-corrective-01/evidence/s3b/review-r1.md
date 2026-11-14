# S3B-INPUT review R1 
Candidate 1bbe767d3a060e6b8ab56bbd1ccff1b0f4879977; base 7c1e1afb. 
Worktree retained; scope includes services/checkup_service.py, services/diagnostic_collector.py, config/settings.py and tests. 
Implementation: inspected _InputBudget/_resolve_input_budget, _assemble_input, significance packing, truncation markers, history hint, CheckupService and collector call-site. Physical capacity reserves system/tools/answer/round; operator cap is budget-gate ON only; report length is prompt-only; collector expansion is minimal and preserves probe limits. 
Test validity: read 20 new tests, 4 changed checkup tests and selfdiag dynamic-anchor assertions. They assert payload content, markers, ordering, capacity/collector behavior, settings and tool schemas; no vacuous assertions found. 
Independent challenge: 20 passed, focus 385 passed, final 650 passed, integration 338 passed. Pre-existing set: 9 failed, 233 passed, same named classes claimed in handoff; no new failure observed. 
Requested mutation probes were not completed: git archive to tar failed with bad header checksum, and the follow-up archive command was rejected by PowerShell parser before execution. No mutation result is claimed. 
Falsification outcomes from candidate tests: OFF facts beyond 3000 survive; metrics are not fixed-clipped; OFF ignores operator cap; significance/order and whole-line markers pass; report length does not alter research payload; collector OFF/ON/saved-value pass. 
Map ledger at REVIEW only, never VERIFIED: SC-INP-CHECK, NOLOSS, REPORT, LOGWINDOW, CHUNKLOSS, FIX, OFF, CAPACITY, PRIORITY, TAIL, NOCONST, NOFULL, SETTINGS, NORESET, FIND-01..04 and TAX-01..07. 
Accepted scope expansion: services/diagnostic_collector.py call-site was explicitly reconciled by PM in slice graph/map/plan and is reviewed as part of S3B. 
BLOCKER IN_SCOPE PM/Orchestrator: exact requirements review gate failed: requirements_gate.py --stage review --slice S3B-INPUT --candidate 1bbe767d3a060e6b8ab56bbd1ccff1b0f4879977 returned errors=483; missing owner input source and source inventory drift. Reconcile immutable source/map/evidence binding and rerun exact gate. 
Verdict: Needs Fixes. Runtime behavior survived focused tests; mandatory stage-correct map gate is not passing, so approval is prohibited. 
Probe allocation: C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a\probe-eff8b6dece.
