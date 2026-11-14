# S6-ACTIVATION review-r1

Decision: Approved for predeploy review. This is not production acceptance and does not mark requirements VERIFIED.

Candidate: HEAD fd2b4bb017d27f101c76fa02b412f7764153226d; behavior commit 1a945ec5b5c47ff18d30c5782ee91e63a5e23441; base 0beed63d; worktree is the delegated candidate worktree.

Implementation: Inspected the diff and the changed path in services/prompt_registry.py, services/checkup_prompts.py, services/prompt_release_policy.py, and delivery consumers. Only the checkup label/seal changed to checkup-p0-24-10-mixed-state; seal 3140bb364044, factory bytes, and PREV bytes are unchanged. Existing EVOL-016 activation plus the deployed guard preserve global/chat behavior, manual bytes, and baseline precedence.

Test validity: Read assertions in tests/test_smart_corrective_checkup_label_activation.py and updated delivery tests. They assert real cache/store/revision rows, action/detail codes, hashes and bodies, history, notifications, no-op, isolation, and route telemetry; no tautologies or mocks of the release boundary. Focused suite: 28 passed; selected registry/guard suite: 229 passed, 2 skipped. py_compile and git diff --check passed.

Independent challenge: In a disposable copy, reverted only label/seal to checkup-p0-24-10 and ran the focused suites: 5 failed, 23 passed. Failures covered label contract, global activation, stale global value, manual revision count, and route delivery. Candidate manual-preservation, baseline, and second-release no-op checks passed.

Acceptance ledger: all executable S6 rows have candidate-bound REVIEW evidence and are not VERIFIED; postdeploy outcomes are UNVERIFIED. No FAILED or N/A_WITH_REASON in this slice.

Mandatory postdeploy evidence: real bot-process release log with activation and factory_revision_applied=fac:<sha12(checkup-p0-24-10-mixed-state)>; real checkup in a chat without override showing factory/3462/no Betterstack or 401/new prompt_base_hash; affected manual chat showing factory_superseded_manual with unchanged SHA/body. No production access was used and these must not be marked VERIFIED here.

Findings: none blocking for predeploy review. Incidental pytest warnings about unknown timeout options are outside this slice.

Next action: route this exact candidate through deploy gate; DevOps records deployed SHA and postdeploy evidence. If a postdeploy check fails, return the exact failure to Builder and retain the last verified release.