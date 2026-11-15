# SFC-12-09 Reviewer R1

**Approved** for pre-deployment review of exact candidate; production acceptance remains unverified pending a new release and clean canary. Requirements are not marked VERIFIED.

## Candidate
- Worktree: c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b-48e7aead
- Base: release/2.58.200 @ 13884daa; deployed baseline 0e4a144d
- Fix: 1e82806a; evidence HEAD: 470901584d87410f6eb6ffd8d00089f8299106cd
- Scope: SFC-12-09; seams SFC-12-02, SFC-13-01, SFC-12-07, SFC-5-10

## Implementation
Inspected services/factcheck_planner.py: _claim_units (around 542-630), build_claim_units (826-860), and _build_plan_inner (1047). subject_request_text is passed structurally into claim-unit creation; request sentences are normalized and terminal punctuation is stripped only for deduplication. A missing request sentence becomes a unit, while an already present sentence is not duplicated. Existing user_request anchor mapping is retained. No lexical list, flag, setting, DDL, sentence-boundary, or cutoff change was introduced; ordinary subject resolution is unchanged.

## Test validity
Read both changed contract files and their assertion bodies. They assert unit text/preservation, claim and query counts, request terms, user-request anchor/message id, ordinary query byte equality, and D/E/F parity. No tautology or planner-boundary mock found. Focused run: 14 passed, 78 deselected; narrower glued test: 1 passed, 45 deselected. The full requested suite was interrupted by environment restarts and was not independently completed.

## Independent challenge
Direct candidate check with no terminator returned two units: `_claim_units([], 'Материал без точки Есть ли страны?', request_text='Есть ли страны?')` -> material unit plus distinct request unit. Focused candidate tests passed 14/14, including duplicate suppression, ordinary parity and D/E/F. Candidate-bound offline 567-character reproduction reports base 2 units/2 queries/coverage 0.0 and fixed 3/3/0.692 with question terms and user_request anchor. Removing pass-through in a disposable copy was not completed because repeated pytest shell executions were interrupted; that mutation check is UNVERIFIED.

## Acceptance ledger
- SFC-12-09: REVIEW-supported; production UNVERIFIED pending new release and clean canary.
- SFC-12-02/SFC-13-01: focused parity showed no regression; not marked VERIFIED.
- SFC-12-07/SFC-5-10: no settings/DDL/flag change observed; runtime budget proof not marked VERIFIED.

## Findings
BACKLOG_ONLY: pre-existing `_claim_timeframe` month-prefix garbage (services/factcheck_planner.py around 747-786), documented in candidate investigation; unrelated to this fix. No IN_SCOPE blocker.

## Evidence pillars
- Implementation / contract: exact planner path, callers, anchor preservation and ordinary route inspected.
- Test validity: meaningful assertions for units, queries, anchors and parity inspected.
- Independent challenge: no-terminator input and focused 14-case runtime check observed; mutation challenge explicitly unverified.

Production requires a new release containing 1e82806a or descendant and a clean canary of the original scenario. Do not mark requirements VERIFIED.

### Follow-up mutation probe
A disposable `git archive HEAD` copy was created under the allocated WorkspaceData run and only the `build_claim_units` request_text pass-through was removed. The focused pytest process timed out at 90 seconds with SIGTERM before producing a result (the candidate was not modified). Therefore mutation-failure is UNVERIFIED, not claimed as passed. The candidate-focused 14/14 runtime evidence remains valid.

### Housekeeping
The mutation probe run is retained temporarily because the timeout reproduction is evidence; it must be closed after process-idle confirmation.
