# Release 2.58.199 — deploy record

- Status: **BLOCKED_PREDEPLOY** (production not touched; no SSH connection used)
- Date: 2026-11-13 (local)
- Base / current production: `234776589c934024ed0e8dceba189fb9d70d3215` (2.58.198)
- Train reviewed tip: `f999f865cf53aa9fe005fa9d0fad51827f707a18`
- Train code tip: `7c5669e55a9ad62914dd721450b4302d967f4c93`
- Release candidate (base + train + version bump): `131e2a7c65519d21dde7a047005c7ce1ec61f597`
  on branch `release/2.58.199` (worktree
  `.../WorkspaceData/worktrees/c742e4de9e92c489/2-58-199-train-8ec228d101d0-704ae241`)
- Rollback target (unchanged, not needed): `25876167` (2.58.197), schema 47, data untouched

## Why blocked

The mandatory pre-deploy identity/manifest set fails **on the bumped candidate only**:

```
python -m pytest tests/test_deploy_identity.py tests/test_release_manifest.py -q
2 failed, 56 passed
FAILED tests/test_release_manifest.py::test_previous_release_is_taken_from_existing_manifest
FAILED tests/test_release_manifest.py::test_rollback_manifest_points_to_previous_running_version
```

Root cause: `tests/test_release_manifest.py` builds a temporary checkout whose version
defaults to `APP_VERSION`, then commits a synthetic "second deploy" with the literal
`"2.58.199"`. That literal now equals the new `APP_VERSION`, so the fixture commit has no
diff (`git commit ... nothing to commit, working tree clean`) and the test aborts before
exercising the producer. The same two tests pass on the pre-bump tip `f999f865` (58 passed),
which proves the failure is introduced by the version bump, not by product behavior.

No product/application defect was observed: the train's code/test sets pass (see
`predeploy-tests.md`). But the explicit pre-deploy rule "any new failure = stop" applies,
and changing test code is outside DevOps write scope.

## Proposed minimal fix (validated locally, NOT committed)

`manifest-fixture-fix.patch` (1 file, +11/−4) makes the synthetic "second deploy" version
derive from `APP_VERSION` (`_next_patch`) instead of a hardcoded release number, keeping the
same assertions. With the patch applied to a scratch copy of `131e2a7c`:
`58 passed`. The patch was then reverted; the candidate branch remains exactly `131e2a7c`.

Owner of the fix: Builder → independent Reviewer (test-contract change). After approval,
DevOps resumes at deploy admission and steps 3–7.

## Verification already performed (details in `predeploy-tests.md`)

| Check | Result |
|---|---|
| Cumulative diff vs `23477658` | 106 files = 76 train + 30 pins, 0 extra, 0 missing |
| Bump commit content | 30 files / 31 lines, only version pins, LF preserved |
| Core research `test_selfdiag_corrective_research.py` | 28 passed |
| Core focused 10-file set | 330 passed |
| Identity + manifest | **2 failed / 56 passed** (blocker) |
| VMQ M1 `test_vmq_m1_episode_contract.py` | 34 passed |
| VMQ NEXT-02 `test_memory_period_vector_leg.py` | 30 passed |
| Web-wide `tests/test_web*.py` (68 files) | 11 failed / 1541 passed — identical to known baseline |
| Pin-file guard set | 856 passed / 4 failed — same 4 fail on base `23477658` (pre-existing) |
| `py_compile` over 62 changed `.py` files | exit 0 |

## Production state

Production remains on the last verified release:
`23477658` / `APP_VERSION 2.58.198`, schema 47. No files were pulled, no service restarted,
no manifest written, no settings/prompts touched. Deploy channel untouched (0 SSH
connections), so the fail2ban budget is intact.

## Next action

Orchestrator: dispatch Builder with `manifest-fixture-fix.patch` (or equivalent), Review the
one-file delta, then return to DevOps for the same deploy plan. Do not mark the epic DONE;
the release gate/PM own final acceptance.
