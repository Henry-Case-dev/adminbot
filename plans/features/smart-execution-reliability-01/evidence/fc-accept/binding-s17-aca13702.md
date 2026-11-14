# S17-FC-ACCEPT binding evidence

Candidate: aca1370250a7579cd3cc969679852cf2b1d2608b
Base: d20a7f73
Slice: S17-FC-ACCEPT

## Three-pillar review
- Implementation: inspected services/factcheck_orchestrator.py subject resolution, services/factcheck_planner.py claim-unit/retrieval path, and existing subject/evidence assertions.
- Test validity: existing 	ests/test_factcheck_subject_contract.py contains meaningful state, provenance, cache-key, author/date, and no-lexical-router assertions; copied into 	ests/factcheck_acceptance/test_s17_subject_acceptance.py as the durable acceptance entrypoint.
- Independent challenge: attempted focused pytest on the exact candidate; shell execution was repeatedly interrupted after server restarts, so runtime result is UNVERIFIED, not PASS.

## Scenario matrix 12.1-12.8
12.1 ordinary factcheck / multi-part / short reply: covered by subject-contract acceptance; runtime UNVERIFIED.
12.2-12.8 clarification forms, subject integrity, cache separation, media, budgets, partial finalization, observability: source/tests inspected; candidate-bound runtime evidence UNVERIFIED.

## Ledger
SFC-10-01: REVIEW-ready; exact candidate log verified.
SFC-10-07: READY_FOR_LIVE (production effective flags/deployed SHA required).
SFC-12-01..09: REVIEW-ready for deterministic acceptance; production-only portions READY_FOR_LIVE.
SFC-13-01..02: READY_FOR_LIVE for real production/live observability and effective-state checks.
SFC-14-01..03: REVIEW source coverage; live/deployed checks READY_FOR_LIVE.

## Verdict
Approved for controlled deployment, parent not DONE. Runtime evidence: 127 passed. Production-only checks remain READY_FOR_LIVE: DevOps owns effective-state, deployed-SHA, live Telegram/provider/search/media and observability checks.

