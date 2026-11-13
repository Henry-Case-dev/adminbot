# 2.58.199 — pre-deploy test record

Interpreter: `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (pytest 9.1.1)
Worktree: `.../WorkspaceData/worktrees/c742e4de9e92c489/2-58-199-train-8ec228d101d0-704ae241`
Candidate: `131e2a7c` (branch `release/2.58.199`, base `23477658`, train `f999f865`)

## Bump

- `config/settings.py`: `APP_VERSION = "2.58.199"` (release note updated, `Prior 2.58.198` kept).
- 29 pin files updated (26 py/meta + 4 JS escaped `2\.58\.198`; polygon has 2 lines).
- `git diff --shortstat`: `30 files changed, 31 insertions(+), 31 deletions(-)`.
- Cumulative vs base: `106 files changed, 41565 insertions(+), 146 deletions(-)`
  = 76 train files + 30 pin files, no overlap, no extra/missing paths.

## Decisive sets

| Set | Command | Result | Exit |
|---|---|---|---|
| Core research | `pytest tests/test_selfdiag_corrective_research.py -q` | **28 passed** (5.30 s) | 0 |
| Core focused | `pytest tests/test_selfdiag_corrective_research.py tests/test_checkup_service.py tests/test_checkup_handlers.py tests/test_checkup_contract.py tests/test_tool_router.py tests/test_tool_schemas.py tests/test_evol_source_reader.py tests/test_direct_l1_corrective_r1.py tests/test_direct_l1_l1d_contract.py tests/test_asap7_direct_l1.py -q` | **330 passed** (39.20 s) | 0 |
| Identity + manifest | `pytest tests/test_deploy_identity.py tests/test_release_manifest.py -q` | **2 failed, 56 passed** (19.05 s) | 1 |
| VMQ M1 | `pytest tests/test_vmq_m1_episode_contract.py -q` | **34 passed** (7.43 s) | 0 |
| VMQ NEXT-02 | `pytest tests/test_memory_period_vector_leg.py -q` | **30 passed** (6.26 s) | 0 |
| Web-wide | `pytest tests/test_web*.py -q` (68 files) | **11 failed, 1541 passed** (192.67 s) | 1 (known baseline) |

Known web failures (identical identities to the recorded base baseline):
`test_history_shows_activation_date`, `test_no_magic_z_index_outside_decorative_in_card`,
`test_close_and_fullscreen_buttons`, `test_s3_scheduler_skips_dm_positive_ids_behavioral`,
`TestNavigationSnapshot::test_tabs_ids_and_order_unchanged` (x2 files),
`test_navbar_legacy_and_v2`, `test_examples_from_tz`, `test_no_english_jargon`,
`test_app_version_matches_readme`, `test_navbar_and_modules_unchanged`.
Web tests rewrite tracked PNG evidence; the 48 incidental modifications were reverted
(`git restore`), worktree clean afterwards.

## Identity/manifest failure (blocker)

```
FAILED tests/test_release_manifest.py::test_previous_release_is_taken_from_existing_manifest
FAILED tests/test_release_manifest.py::test_rollback_manifest_points_to_previous_running_version
E  AssertionError: git commit -q -m deploy two rc=1: On branch main
E  nothing to commit, working tree clean
tests\test_release_manifest.py:35: AssertionError
```

Cause: the fixture's synthetic second version is the literal `"2.58.199"`, equal to the new
`APP_VERSION`; `_repo()` already wrote 2.58.199, so `_commit(version="2.58.199")` produces no
diff.

Control run at the pre-bump tip `f999f865` (detached checkout, same interpreter):
`58 passed in 20.01s`.

Validated remedy (scratch only, reverted): derive the second version from `APP_VERSION`
(`_next_patch`); `58 passed in 19.50s`. Patch saved as `manifest-fixture-fix.patch`.

## Pin-file guard set (pre-existing, not caused by this train)

`pytest tests/test_decision_making_round1026.py ... tests/test_webapp_round1026_polygon.py`
(24 pin files): **856 passed, 4 failed**. The same four fail at base `23477658`:

- `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools` (18 tools vs expected 17)
- `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

They are stale guards over an ancient baseline (`pre-round1026-a1`) and an older tool count,
not regressions of 2.58.199. Reported separately, outside this release's acceptance.

## Compile

`python -m py_compile` over the 62 changed `.py` files: exit 0.
