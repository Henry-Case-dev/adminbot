# Review S13-FC-REQUEST - candidate bc2ac583

## Verdict

**Needs Fixes**.

Blocking: git diff --check d20a7f730715ba9e9cba7673c0557794979be339..bc2ac583 fails with numerous trailing whitespace in services/factcheck_orchestrator.py (first lines 273-301, through 1817). Remove trailing whitespace in changed code/tests, rerun diff check and focused tests.

## Three pillars

- **Implementation:** inspected the diff in the requested handlers/services, tracing CheckSubject through suitability/context, envelope, planner/_claim_units, attribution and legacy/temporal branches. Fingerprint enters envelope/cache slice. No new mandatory stage or lexical classifier observed. media_readiness only carries durable full-request context.
- **Test validity:** read assertions in tests/test_factcheck_subject_contract.py. Focused suite: 39 passed (one leaked aiosqlite warning). Context/planner subset: 28 passed. Wider subset was interrupted by server restart and is not evidence.
- **Independent challenge:** standalone request must not inherit material date/author or another subject cache. Observed original_published_at=None, material date retained, request anchor=TRIGGER_TG, different subjects yield distinct keys/cache miss, normalized whitespace reuses the same subject.

## Ledger

S13-FC-REQUEST mandatory rows remain PENDING/UNVERIFIED pending whitespace repair and independent review gate. Focused behavioral evidence is verified only as test evidence, not final map acceptance. Failed: diff cleanliness. Unverified: broad impacted subset, review gate, final map acceptance, postdeploy evidence. N/A: none.

## Scope and routing

Candidate bc2ac583; evidence head 2d6b5a8d; base d20a7f730715ba9e9cba7673c0557794979be339. No DDL, migration, flag or production write observed. Browser/UI check does not apply.

Builder: remove trailing whitespace, rerun diff check and focused suite, then broad subset and independent re-review. Do not edit maps/statuses.