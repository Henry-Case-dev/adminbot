# 2.58.199 — pre-deploy test record (candidate d20a7f73)

Interpreter: `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (pytest 9.1.1)
Worktree: `.../WorkspaceData/worktrees/c742e4de9e92c489/2-58-199-train-8ec228d101d0-704ae241`
Candidate: `d20a7f730715ba9e9cba7673c0557794979be339`
Base `23477658`; train `509ae75a` (code tip `7c5669e5`; fixture fix `773417ff`).

## Bump

- `APP_VERSION = "2.58.199"` with release note + `Prior 2.58.198`.
- 30 files / 31 lines: 26 py/meta pins + 4 JS escaped `2\.58\.198`.
- `git diff --shortstat` for the bump: `30 files changed, 31 insertions(+), 31 deletions(-)`.
- Cumulative vs base: `106 files changed, 41606 insertions(+), 146 deletions(-)`
  = 76 train + 30 pins, no overlap, no extra/missing.
- LF preserved; no line-ending rewrite (numstat 1/1 per file, polygon 2/2).

## Decisive sets

| Set | Command | Result |
|---|---|---|
| Identity + manifest | `pytest tests/test_deploy_identity.py tests/test_release_manifest.py -q` | **58 passed** (19.97 s) |
| Core research | `pytest tests/test_selfdiag_corrective_research.py -q` | **28 passed** (7.42 s) |
| Core focused | new + checkup service/handlers/contract + tool_router/schemas + source_reader + direct_l1 corrective/l1d + asap7 direct_l1 | **330 passed** (42.82 s) |
| VMQ M1 | `pytest tests/test_vmq_m1_episode_contract.py -q` | **34 passed** (9.98 s) |
| VMQ NEXT-02 | `pytest tests/test_memory_period_vector_leg.py -q` | **30 passed** (7.32 s) |
| Web-wide | `pytest tests/test_web*.py -q` (68 files) | **11 failed / 1541 passed** (191.79 s) — identical known identities |
| Pin guards | 24 pin files | **856 passed / 4 failed** — same 4 on base `23477658` |
| Compile | `py_compile` over 62 changed `.py` | exit 0 |

Known web failures (same as the recorded base baseline):
`test_history_shows_activation_date`,
`test_no_magic_z_index_outside_decorative_in_card`,
`test_close_and_fullscreen_buttons`,
`test_s3_scheduler_skips_dm_positive_ids_behavioral`,
`TestNavigationSnapshot::test_tabs_ids_and_order_unchanged` (2 files),
`test_navbar_legacy_and_v2`, `test_examples_from_tz`,
`test_no_english_jargon`, `test_app_version_matches_readme`,
`test_navbar_and_modules_unchanged`.

Web tests rewrite tracked PNG evidence; the incidental modifications were
reverted (`git restore`), worktree clean afterwards.

## Pin-guard pre-existing failures (verified on base)

- `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
- `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

Stale guards over `pre-round1026-a1` and an older tool count (actual 18 vs 17);
not caused by the train or the bump. Backlog only.
