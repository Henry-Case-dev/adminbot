# FC anchor independent review R1

- Candidate: `4852c67c7fc82fad39a832059c17122e3828861b` (code/tests `b0f6ec79`, base `0beed63d`, worktree `sc/fc-anchor`). Scope: SFC-12-09 residual only. No production access; no requirements marked VERIFIED.

## Proof pillars

- **Implementation:** inspected `services/factcheck_orchestrator.py:1805-1823` and `services/factcheck_planner.py:439-459,1129-1257`. The full `subject.material_text` is additive; anchor terms are derived by `_claim_terms` from material, prepended after the existing `[:10]` selection, and applied to glued-question units plus narrowed material units (`material_anchor_lost`). Ordinary/request-only/material-only branches are guarded by structural predicates. No flags, DDL, settings, or budget changes in candidate diff. The controlled-aggregator guard is implemented in `run_retrieval` and asserted by the test.
- **Test validity:** read both mirrored contract files (`tests/test_factcheck_subject_contract.py` and `tests/factcheck_acceptance/test_s17_subject_acceptance.py`, identical new bodies). Assertions check exact before/after query terms, order/source, unchanged negative branches, full-material seam, and outcome/citations/off-topic count for the aggregator; no vacuous assertions or boundary mocks of the planner. The orchestrator seam test is source-level, so it proves wiring text rather than executing `_run_inner`; this is a limited gap, not a blocker given the planner/integration tests.
- **Independent challenge:** ran the recorded probe: before `c1=она распространена...`, `c2=Франция Великобритания...`; after `c1=женское обрезание древняя она...`, `c2=женское обрезание древняя Франция...`, query count remains 2 and claims remain unchanged. Ran the focused mirrored suite: **112 passed**. Independently loaded the provided no-anchor mutation plugin: **4 failed, 6 passed**, exactly the four anchor-dependent assertions; this falsifies a false-green implementation. Additional planner/orchestrator/acceptance run: **105 passed**. One attempted wildcard command was invalid (`pytest` does not expand that pattern); it is not treated as test evidence.

## Acceptance ledger (review scope)

- SFC-12-09 query anchor for glued question: **REVIEW-supported / not production VERIFIED**.
- Full material passed additively from orchestrator: **REVIEW-supported / not production VERIFIED**.
- Anchor material-derived and prepended before term cut: **REVIEW-supported / not production VERIFIED**.
- Conditional narrowed-material behavior and ordinary/request-only/material-only parity: **REVIEW-supported / not production VERIFIED**.
- Irrelevant controlled aggregator cannot confirm question claim: **REVIEW-supported / not production VERIFIED**.
- Postdeploy `original_production_scenario` on 2.58.203: **UNVERIFIED here**. The referenced clean isolated postdeploy proof exists in the handoff context, but exact raw `material_part`/`request_part` JSON boundaries were reconstructed rather than replayed; no production access was used in this review. Live metrics (`claims_with_direct_evidence`, `direct_answer_on_question`) remain postdeploy evidence.

## Findings

- **Nonblocking / evidence limitation:** `test_orchestrator_passes_full_material_to_plan` uses `inspect.getsource` rather than executing the seam. Keep as supplemental wiring evidence; a future integration test could capture the planner call, but no current contract failure was observed.
- No IN_SCOPE implementation blockers found. The controlled aggregator is synthetic/offline by design and does not prove a real provider result; this is correctly limited to review evidence, not production acceptance.

## Verdict

**Approved** for this exact predeploy candidate at the review stage only; this is not a production acceptance and does not mark SFC-12-09 VERIFIED. The postdeploy proof note is preserved: a clean isolated `original_production_scenario` was reported on 2.58.203, but the exact JSON boundary was reconstructed, not replayed.

The retained worktree must remain available to Orchestrator/DevOps for candidate integration and postdeploy checks.
