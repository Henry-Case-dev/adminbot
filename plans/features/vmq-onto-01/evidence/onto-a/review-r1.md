# VMQ-ONTO-A review R1

Verdict: Needs Fixes

Candidate: a7a576b1f1833da7be53f7bd75d25e1eaf815937; evidence tip 98e19074a7e3230a2fa0b1d090282794b0e0de25; base c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5.

Implementation: inspected classify_entity_type (services/semantic_contracts.py:350-415), project_identity (629-735), identity invariants, role/time/value projections (740-1213), and all 23 test bodies. UID-first, alias hint_ref, ambiguity, scope rejection, separate roles are implemented. However REQUIRED_TYPE_SIGNALS (124-130) does not require chat_scope for event/fact/topic.

Test validity: 23 focused tests assert real statuses, canonical/candidates, UID, roles, times, provenance, negative ValueErrors, DB counts, and resolver integration. Missing assertion: chat_scope must be required for every typed classification.

Independent challenge: py -3 direct probe classify_entity_type(event,event_time=1700000000) returned verified with signals time_anchor and no chat_id; fact with statement provenance likewise verifies without scope. This falsifies O-01.

Checks: py -3 -m pytest tests/test_semantic_contracts.py -q => 23 passed, 2 config warnings. Listed affected suites => 310 passed, 3 warnings. Disposable mutation _resolution_is_uid_proven return True => 3 failed, 20 passed (UID/name hint, common noun, alias hint); candidate untouched. Source diff audit found no second resolver/router/search/DB/ontology/LLM, DDL, relation persistence or retrieval changes.

Ledger: O-01 FAILED (chat scope gap); O-02 VERIFIED for implementation/tests (alias/common noun hint-only, same-name UID/scope distinction, ambiguity no canonical); forbidden boundaries VERIFIED by source audit only; production N/A.

Blocking finding: BLOCKER IN_SCOPE O-01. Builder must require TYPE_SIGNAL_CHAT_SCOPE or return unknown/tentative when absent, add no-scope event/fact/topic negative assertions, rerun focused and affected suites. Narrow recheck: direct no-scope event/fact are not verified and suites pass.

Housekeeping: disposable run probe-44b2738214 closed; retained by tool as protected/unknown. Candidate worktree retained for PM.
