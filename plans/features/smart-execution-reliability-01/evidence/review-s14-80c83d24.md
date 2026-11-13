# Independent review S14-FC-RESOURCES

**Decision:** Approved for controlled deployment, parent not DONE.
**Candidate:** 80c83d24; evidence HEAD 140e8cd7; base c00caf62.

## Three pillars

**Implementation:** inspected FactcheckLimits/resolvers in services/factcheck_planner.py:1328-1543 and run_retrieval:1938-2392, _assemble:1248-1263, temporal_factcheck.py:958-1130. Confirmed S1 master -> chat -> global -> default, ON 120/600/24/64/100000/20/32, OFF removal of product deadline/query/refine/char/fetch caps, 100k portions with tail, 32 portions with tail, 20 page size, stop_reason and provenance. External caps temporal_max_evidence_per_run=20, support[:1200], _server_parts[:4] remain S15/S16. No new admin key/panel, DDL or migration.

**Test validity:** read all assertions in tests/test_factcheck_resources.py (20 tests); they exercise real retrieval and assert outputs/state, not tautologies or mocks of run_retrieval. Focused run: 20 passed. Candidate broad factcheck evidence: 822 passed, 1 failed, 4 errors; base: 801 passed, 2 failed, 4 errors. Four setup errors and validator failure repeat on base; network irrelevant-case is flaky and passed on candidate.

**Independent challenge:** mutation evidence independently inspected: restored 8000 cap, hidden total 12, temporal portion 8 and evidence-ref cap 12 each made targeted tests red. Candidate probe reports 14/14. The >32 claim/tail and search_text_portions join contract are asserted; local focused run observed 20 passed.

## Acceptance ledger

SFC-5-01 VERIFIED; SFC-5-02 VERIFIED; SFC-5-03 VERIFIED; SFC-5-04 VERIFIED; SFC-5-05 VERIFIED; SFC-5-06 VERIFIED; SFC-5-07 VERIFIED predeploy; SFC-5-08 VERIFIED; SFC-5-09 VERIFIED; SFC-5-10 READY_FOR_LIVE; SFC-6-01 VERIFIED; SFC-6-02 VERIFIED; SFC-6-03 VERIFIED; SFC-6-04 VERIFIED; SFC-6-05 VERIFIED; SFC-6-06 VERIFIED; SFC-10-04 VERIFIED; SFC-13-03 READY_FOR_LIVE.

Summary: 16 VERIFIED, 2 READY_FOR_LIVE, 0 FAILED.

## Checks and residuals

Executed: pytest tests/test_factcheck_resources.py -q -> 20 passed in 3.36s. Reused green probe 14/14, audit-candidate JSON, mutation logs, focused/base logs, and empty git diff-check. No UI change; visual checks N/A. No parallel lenses.

Postdeploy: DevOps must verify effective flags.budgets_enabled, saved chat/global overrides, ON factory values and OFF removal of enforcement on deployed SHA, plus production metrics distinguishing sufficient evidence/no progress/provider failure/technical limit/ON budget. Until then SFC-5-10 and SFC-13-03 remain READY_FOR_LIVE; parent is not DONE.

Broad-suite cooldown setup errors and unrelated validator escaping are BACKLOG_ONLY/pre-existing, not S14 blockers. Next action: controlled deploy exact candidate 80c83d24, bind deployed evidence, run release gate.
