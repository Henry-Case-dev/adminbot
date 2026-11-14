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
SFC-10-01: REVIEW-ready source/test evidence; runtime UNVERIFIED.
SFC-10-07: READY_FOR_LIVE (production effective flags/deployed SHA required).
SFC-12-01..09: REVIEW evidence exists in existing suites, but S17 focused runtime execution UNVERIFIED.
SFC-13-01..02: READY_FOR_LIVE for real production/live observability and effective-state checks.
SFC-14-01..03: REVIEW source coverage; live/deployed checks READY_FOR_LIVE.

## Verdict
Needs Fixes: mandatory candidate-bound runtime acceptance and postdeploy checks are not proven. Builder/Reviewer next action: rerun C:\\Code\\Python\\adminbot\\.venv\\Scripts\\python.exe -m pytest tests/factcheck_acceptance tests/test_factcheck_subject_contract.py tests/test_factcheck_resources.py tests/test_factcheck_evidence_delivery.py tests/test_factcheck_finalization.py -q in a stable runner, preserve output, then run the review gate. DevOps owns postdeploy effective-state/deployed-SHA checks.
