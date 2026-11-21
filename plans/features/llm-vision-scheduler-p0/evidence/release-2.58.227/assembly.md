# Release 2.58.227 — LVS L1 discovery: partial NanoGPT catalog card (LVS-L1-07/08/10)

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-21 (+12:00)
**Branch:** `release/lvs-l1-discovery-2.58.227`
**Base / rollback:** `1cc019ad55bd26f465353ba97588cfc28ead859b` (2.58.226, schema 48, DDL 0)
**Product:** `77d863eb89c15f8dda27edd1568bf7e7a273896d` (`fix/lvs-l1-discovery`)
**Bump tip:** `ef204bb8369f4e1d85db8670fb1ce8407a0dfc31`
**Version:** 2.58.227
**Schema/DDL:** 48 / 0

Independent review: `plans/features/llm-vision-scheduler-p0/evidence/l1-discovery-2026-11-21/review-r1.md`
on master `40638708cb21609a42f8c314fbad16efd01c7d0c`, sha256
`2ff44c571c3aff4f3855bb6e8ee04e82d840ffb54455ce901356bb18f1f4714b`
(24 124 bytes), verdict **APPROVED_FOR_RELEASE_PREPARATION** for the candidate
`77d863eb8`. Covered IDs: **LVS-L1-07**, **LVS-L1-08**, **LVS-L1-10**.
Non-blocking observations in that review: **LVS-L1-R1-N01..N04**
(`BACKLOG_ONLY`; not changed in this release).

The review artifact lives on master and is not in this branch's ancestry; it is
referenced by commit and sha256 above. This assembly does not claim a release
VERIFIED verdict.

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Worktree via installed `workflow_housekeeping.py worktree-path` + `git worktree add` + `register-worktree` | `WorkspaceData/worktrees/c742e4de9e92c489/llm-vision-scheduler-p0-09bee2fc3ea3-a2bf0286`; branch from `77d863eb8`; no sibling checkout |
| 2 | Branch ancestry | base `1cc019ad5` -> `77d863eb8` (product) -> `ef204bb83` (bump); **2 commits, 0 merge commits** before this docs-only evidence commit |
| 3 | Standard bump `2.58.226 -> 2.58.227` | `ef204bb83`; **31 files / 34 insertions / 34 deletions** |
| 4 | Product scope | only `services/model_capacity.py` (+91/-19) and new `tests/test_lvs_l1_discovery_partial.py` (243 lines); no B3/`web/*`, no P0 harness, no other task |
| 5 | Tests on bumped tip | new file 7/0; mandatory 10 files 339/0; adjacent capacity 135/0; consumers 168/0; pin guard 856/4 (same 4 on base); JS pins 4/4; fallback file 5F/3P identical on base |
| 6 | Manifest dry-run | exit 0; version 2.58.227; `deployed_sha` `ef204bb83`; previous `1cc019ad5` / 2.58.226 (seeded local previous-manifest input, removed afterwards); `dirty_tracked=false` |
| 7 | Release evidence (this directory) | docs-only commit after `ef204bb83` |

The branch contains exactly the reviewed product commit, the standard version
bump and this evidence. The P0 harness and B3 changes are intentionally absent.

## 2. Product delta

| File | Insertions | Deletions |
|---|---:|---:|
| `services/model_capacity.py` | 91 | 19 |
| `tests/test_lvs_l1_discovery_partial.py` | 243 | 0 (new) |

Product behavior:

- A partial NanoGPT catalog card (no `context_length`, but with
  `max_output_tokens`/`max_completion_tokens`, capability flags, or a declared
  output field) is no longer discarded. Its real output/capability/output-field
  data reaches `CapacityResult`/`ModelCapability`; the additive
  `max_output_source` field names the provenance only when output is really
  present.
- The context window remains the exact registry value or an honest
  `estimated_unknown` planning estimate. 1M is **not** promoted to verified;
  `declared_context_window` is not fabricated; the model is not disabled or
  substituted.
- A full card with a window still takes precedence over a partial card when
  documented catalog URLs disagree. The window-only
  `_adapter_nanogpt_catalog` wrapper keeps its previous contract.
- No change to route budgets, cache key, API surfaces, DDL, migrations, flags,
  hot-config, prompts, `web`, `handlers` or the prompt/LLM call path.

`git diff --name-only 1cc019ad5..HEAD -- services config handlers web`
= `services/model_capacity.py` + `config/settings.py` (bump only).
`-- database.py migrations prompts chat_prompts.py` = empty.
`-- web` = empty. Schema constant and migrations are byte-identical to the
deployed base (schema 48, DDL 0).

## 3. Bump and invariants

- `APP_VERSION = "2.58.227"` with the 2.58.227 release note and
  `Prior 2.58.226`; only line 3599 of `config/settings.py` changed.
- Standard pins: `plans/docs/param-registry-round1025.meta.md`, 24 Python test
  files (polygon has two lines), 4 escaped JS pins, and
  `tools/ui_mod_acl_m4b2_status_e2e.py` (three pins). Exactly
  **31 files / 34 insertions / 34 deletions**, matching the `bafbd0863`
  225->226 wave shape.
- Every non-settings bump diff is byte-identical to its previous content after
  reversing `2.58.227 -> 2.58.226` (including the escaped `2\.58\.227` JS form);
  `settings.py` differs only by the version and prepended release note.
- BOM/CRLF preserved: `config/settings.py` remains UTF-8 BOM + 3645 CRLF plus
  one pre-existing bare LF; no other file changed encoding/line endings.
- `git diff --check -- services config tests tools` rc=0.
- `py_compile` of `services/model_capacity.py` and `config/settings.py` rc=0.
  `node --check` not run: `web/` is untouched.
- All live occurrences of the version pin are `2.58.227`; remaining `2.58.226`
  strings are historical evidence, the `Prior 2.58.226`/base reference inside
  the `settings.py` release note, and archived historical records — not live
  pins.
- `plans/progress_scope.json` and `plans/workflow_state.md` were not changed.

## 4. Tests (bumped tip)

Machine-readable record: `tests-2.58.227.json`; raw result lines:
`tests-2.58.227.txt`. Environment: Python 3.12.0, pytest 9.1.1, Node v24.16.0,
Windows; `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` for pytest runs.

| Batch | Result |
|---|---|
| `tests/test_lvs_l1_discovery_partial.py` | **7 passed, 0 failed** (9.16 s) |
| Mandatory 10 files (capacity + L1 + llm client + new file) | **339 passed, 0 failed** (71.42 s) |
| Adjacent capacity, 6 files | **135 passed, 0 failed** (55.61 s) |
| Consumers `test_llm_client.py`, `test_asap7_direct_l1.py`, `test_direct_l1_l1d_contract.py` | **168 passed, 0 failed** (9.14 s) |
| Pin guard, 24 Python version-pin files | **856 passed, 4 failed** (76.27 s); the same 4 node IDs fail on base `1cc019ad5` (856 passed, 4 failed, 78.01 s) |
| JS pins, 4 files | **4/4 OK** (`HOTFIX7/8/9/10` markers) |
| `tests/test_direct_fallback_recompose_asap32.py` | **5 failed, 3 passed** (20.17 s); identical 5 node IDs on base (5 failed, 3 passed, 20.42 s) — pre-existing |
| `py_compile` model_capacity/settings | rc=0 |

Pre-existing pin-guard failures (same on base, not counted as passes):

- `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
- `tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

Pre-existing fallback-recompose failures (identical node IDs on base; cause:
test doubles `_fallback_with_retries` do not accept the `sent=` keyword):

- `test_chat_recomposed_under_fallback_budget_tools_kept`
- `test_chat_no_adapter_primary_sized_payload_fallback`
- `test_chat_adapter_failure_loud_oversized_diagnostic`
- `test_generate_adapter_error_loud_and_payload_intact`
- `test_generate_adapter_invalid_shape_loud`

The review's independent RED is also recorded: the new file is 2 failed / 5
passed on base `1cc019ad5` and 7 passed on candidate `77d863eb8`; the two RED
assertions are the partial-card output values (`None == 4096`,
`None == 2048`). This assembly relied on that reviewed RED and re-ran the green
set on the bumped tip.

## 5. Manifest and runbook

- `manifest-dry-run.json`: exit 0; `deployed_sha`
  `ef204bb8369f4e1d85db8670fb1ce8407a0dfc31` (bump tip), version `2.58.227`,
  previous `1cc019ad55bd26f465353ba97588cfc28ead859b` / `2.58.226`,
  `release_branch` `release/lvs-l1-discovery-2.58.227`, `dirty_tracked=false`,
  `effect=deploy`, `deployer=builder-release-prep`.
  A fresh worktree has no `.deploy/`, so the previous-manifest input
  (deployed base SHA/version) was seeded locally for the dry run and removed
  immediately afterwards; no `.deploy/` remains and production files were not
  read. DevOps must run `release_manifest.py` on the actual checked-out SHA
  after pull: the honest `deployed_sha` is `git rev-parse HEAD` there.
- `deploy-runbook-2.58.227.md`: backup/disk, manifest, restart,
  health/version/schema/identity/NRestarts/journal/settings/prompt-digest/disk
  checks, read-only deployed-byte identity, and rollback to
  `1cc019ad5` / 2.58.226 (no schema downgrade; schema 48 unchanged).

## 6. Limitations and residual

- No production access, SSH, deploy, live Telegram, provider call or
  effective-state run in this assembly. The verdict is
  `APPROVED_FOR_RELEASE_PREPARATION`, not release VERIFIED.
- Live rows **LVS-L1-32**, **LVS-OUT-01..05** and **LVS-EXEC-09** are not part
  of this release: they need live provider/deployed-byte close-out and remain
  outside this candidate.
- The external provider HTTP **402** limitation is unchanged and is not
  presented as a pass; no answer-quality or provider-availability claim is made.
- Real NanoGPT/OpenRouter catalog responses outside the documented fixture
  shapes are not verified. The adapter keeps the reviewed behavior: unknown
  shapes are ignored honestly, not guessed.
- Review non-blocking `LVS-L1-R1-N01..N04` stay backlog-only and are not
  implementation scope here: OFF+override partial nuance, OpenRouter partial
  symmetry, the weak `route.usable` assertion note, and the PM write-scope/map
  record note.
- Pre-existing test failures listed in §4 remain; they are not caused by this
  delta and are not counted as passes.
- No UI/visual change: this is backend capacity discovery plus tests, so no
  Playwright/Browser Use run is applicable.
- B3 (`web/*`), the P0 harness and unrelated tasks are intentionally excluded.
