# Release 2.58.230 — P0-EMBED-503-FAILOVER (embedding 5xx failover)

**Status:** REVIEW (assembly done; no deploy). Independent review of this release candidate is still
required; no VERIFIED claim is made.
**Date:** 2026-11-22 04:55 (+12:00) / 2026-11-21 16:55 UTC
**Branch:** `release/p0-embed-503-failover-2.58.230`
**Base / rollback:** `94e227a2c096f4cc7b987c3253563bf0df442d17` (2.58.229, schema 48, DDL 0)
**Reviewed candidate:** code `4ace0a3ae52c321edfd2ef425d933198b6d08377`, evidence tip
`d00a01b07eec2143f355dcba6067f92074e3d064` (`fix/embed-503-failover`, base `374dc6060`)
**Review:** `plans/features/p0-embed-503-failover/evidence/review-r1.md` (master `373a39615`),
`APPROVED_FOR_RELEASE_PREPARATION`; live-route evidence `f2540ac60`; owner input
`plans/owner_inputs/2026-11-22-p0-embed-503-failover.md` (sha256 `d23bf6f9…28f09`).
**Bump/content tip:** `9d5cf5173fcf835974205aeeef373766b14a18bd`
**Version:** 2.58.230
**Schema/DDL:** 48 / 0

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Worktree from base | `workflow_housekeeping.py worktree-path --epic p0-embed-503-failover-2.58.230` →
`git worktree add -b release/p0-embed-503-failover-2.58.230 94e227a2c` → `register-worktree`; 0 conflicts |
| 2 | Cherry-pick code `4ace0a3ae` | `a319431cf`; patch-id **identical** (`97cbf4ca…`); 3 files, +743/−23 |
| 3 | Cherry-pick evidence `019fedc64`, `d00a01b07` | `9053c8a42`, `f5e3c473f`; patch-ids identical
(`4f962dfa…`, `3d418585…`); implementation/red/mutation evidence only |
| 4 | Cherry-pick live route `f2540ac60` and review `373a39615` | `33d08beb9`, `f6d6d3a24`; patch-ids
identical (`15c187e3…`, `7d1b454f…`) |
| 5 | Planning/owner input from master | `2cfd20854`: `plan.md`, `requirements-map.json`, `slice-graph.json`,
`evidence/intake-2026-11-22.md`, owner input. `plans/progress_scope.json` and `plans/workflow_state.md`
were **not** changed in this lane |
| 6 | Standard bump 2.58.229 → 2.58.230 | `9d5cf5173`; **32 files / 35 insertions / 35 deletions**, same shape as 2.58.229 |
| 7 | Checks on the bumped tip | see §4 |
| 8 | Manifest dry-run on `9d5cf5173` | `manifest-dry-run.json`; exit 0; version 2.58.230; previous
`94e227a2c` / 2.58.229; `dirty_tracked=false`; `.deploy` removed |
| 9 | This evidence commit | docs-only, after the content tip |

The cherry-pick range contains **no merge commits** (`git rev-list --merges 94e227a2c..HEAD` = 0) and no
force operations. The changed product/test bytes are identical to the reviewed candidate:
`git diff 4ace0a3ae a319431cf -- services/embedding_control_plane.py services/summary_memory.py
tests/test_p0_embed_503_failover.py` is empty, and all five cherry-picked commits have identical
patch-ids. (`services/access.py` differs only because the 2.58.229 C1 change is part of the new base,
not this release.)

## 2. Product delta review (base `94e227a2c` → content tip `9d5cf5173`)

| File | Net base→tip |
|---|---|
| `services/embedding_control_plane.py` | **147 / 22** |
| `services/summary_memory.py` | **143 / 1** |
| `tests/test_p0_embed_503_failover.py` | **453 / 0** (new) |
| `config/settings.py` | 1 / 1 (APP_VERSION + changelog only) |
| 31 version-pin files (24 Python + 4 escaped JS + 2 e2e tools + registry stamp) | 34 / 34 (version literals only) |
| Evidence/planning under `plans/features/p0-embed-503-failover/` and owner input | 13 files (docs/JSON) |

Totals base→content tip: **35 non-evidence files, 743+35 = 778 insertions / 23+35 = 58 deletions**,
plus 13 evidence/planning files. The exact five-commit candidate contributes 3 product/test files
(+743/−23); the bump contributes 32 files (+35/−35, with settings 1+1 already counted above).

- New endpoints/fields/flags: **0**. `git diff 94e227a2c..HEAD -- services handlers config` contains only
  `services/embedding_control_plane.py`, `services/summary_memory.py`, `config/settings.py`.
- DDL/migrations/prompts/web: `git diff 94e227a2c..HEAD -- migrations database.py prompts web` = **empty**.
- `APP_VERSION` parsed by AST = **2.58.230**; schema remains v48/DDL 0; no data action.
- Behavioral seam: per-operation exclusion on 5xx/timeout, credential/group cooldown with probe recovery,
  bounded single-leg retry, auth/quota semantics preserved, route-aware write admission through the existing
  `resolve_index_compat` (fallback vectors stay text-only + FTS until serviceable+compatible), and
  `summary_memory._embed` provenance. No new gate, breaker, queue, model, key, index or UI.

## 3. Bump and invariants

- `APP_VERSION = "2.58.230"` with a P0-EMBED-503-FAILOVER changelog entry and `Prior 2.58.229`;
  base noted as `94e227a2c (2.58.229)`.
- Version wave: **32 files / 35 / 35**, exactly the 2.58.229 reference shape: 24 Python version-pin files,
  4 escaped JS pins, `tools/ui_mod_acl_m4b2_status_e2e.py` (3 lines), `tools/ui_mod_acl_m4b3_status_e2e.py`
  (1 line), `plans/docs/param-registry-round1025.meta.md`, `config/settings.py`.
  `tools/ui_mod_acl_m4c1_roles_e2e.py` has no version pin; nothing was added.
- Every non-settings bump diff line matches only `2.58.229` → `2.58.230` (plain or escaped); verified
  programmatically: **0** non-version diff lines.
- BOM/CRLF preserved byte-level: all 32 bumped files keep their original BOM/line-ending profile (0
  mismatches). `config/settings.py` keeps UTF-8 BOM and its 3645 CRLF + 1 bare LF (the bare LF terminates
  the APP_VERSION changelog line).
- `git diff --check` rc=0; `node --check web/app.js` rc=0; `py_compile` of settings, both changed services,
  the new pytest file and both e2e tools rc=0.
- `git grep -n "2\.58\.229"` after the bump: only historical text (settings changelog, previous-release
  evidence directories and comments); no live version pin remains at 2.58.229.

## 4. Tests (bumped tip `9d5cf5173`)

Machine-readable record: `tests-2.58.230.json`; raw outputs under `test-output/`.

| Batch | Result |
|---|---|
| New `tests/test_p0_embed_503_failover.py` | **10 passed** (`10 passed in 11.96s`) |
| 15-file embedding/recovery/backfill/llm profile | **585 passed, 0 failed/errors/skipped**, 1 warning (`82.97s`) |
| Target frozen-pin tests (2) | **2 passed** (`test_routes_py_byte_freeze_pin_intact`, `test_routes_file_unchanged`) |
| Pin-guard, 24 Python version-pin files | **856 passed / 4 failed** — exactly the 4 known pre-existing IDs, separately reproduced on base `94e227a2c`: `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`, `test_canon_twelve_tools`, `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`, `TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` |
| JS version pins (hotfix7/8/9/10) | **4/4 rc=0**; `HOTFIX7/8/9/10-…-OK` |
| B1 status e2e | **138 checks / 0 failures**, `M4B-STATUS-E2E-OK` |
| B2 status e2e | **92 checks / 0 failures**, `M4B-B2-STATUS-E2E-OK` |
| B3 status e2e (web unchanged) | **131/131**, `M4B-B3-STATUS-E2E-OK`, 8 screenshots |
| Syntax | `node --check web/app.js` rc=0; `py_compile` rc=0 |

The 15-file profile is: `test_p0_embed_503_failover.py`, `test_embedding_control_plane_asap4.py`,
`test_embed_fallback_slots_routing.py`, `test_asap8_f8_embeddings.py`, `test_embed_identity_compat.py`,
`test_embed_identity_compat_restart_legacy.py`, `test_asap5_embedding_identity.py`,
`test_asap6_embedding_generations.py`, `test_soul1_w7_embedding_primary_slot.py`, `test_summary_memory.py`,
`test_llm_client.py`, `test_asap44_graphrag_batch_breaker.py`, `test_graphrag_memory.py`,
`test_mca17_summary_instrumentation.py`, `test_asap8_v6_p1_d09_memory.py`, with `--timeout=180`.
Recovery/backfill coverage is inside `test_summary_memory.py` (`test_reactivation_after_embed_recovery`,
`test_backfill_reembeds_and_is_idempotent`, failure/idempotency variants). The 4 pin-guard failures are
recorded explicitly, reproduced on base and are **not** counted as passes.

## 5. Requirements bound by this assembly

Eligibility is for release preparation only; **no requirement is VERIFIED before a real deploy and
production-bound evidence**. Statuses carried from review r1 (`review-r1.md`):

| ID | Review status |
|---|---|
| `E503-FAILOVER-01` | PASS_CODE_DEPLOY_PENDING |
| `E503-AUTH-01` | PASS |
| `E503-IDENTITY-01` | PASS_CODE_LIVE_ADMISSION_UNKNOWN |
| `E503-RECOVERY-01` | REVIEW_LIVE_BEFORE_AFTER_PENDING |
| `E503-DIAG-01` | PASS_CODE |
| `E503-ACCEPT-MATRIX-01` | REVIEW_LIVE_HALF_PENDING |
| `E503-EXCLUSIONS-01` | PASS_SCOPE_DEPLOY_PENDING |
| `E503-ROUTE-01` | EXTERNAL_EVIDENCE_f2540ac60_NOT_RERUN |
| `E503-REPORT-01` | PENDING_FINAL_REPORT |

Non-blocking findings `E503-R1-N01` (read/query path still uses configured identity) and
`E503-R1-N02` (extra alias not primary needs durable admission) are **BACKLOG_ONLY** and do not block
this candidate. `SCN-01` is not involved and is not mixed into this release. `apinet` 503 remains an
external fact and is **not** declared fixed. Google PCI admission remains **unproven** by the existing
gate; a live 200/3072 vector is functional evidence, not admission.

## 6. Manifest, rollback, runbook

- `manifest-dry-run.json`: exit 0; `deployed_sha=9d5cf5173…`, `version=2.58.230`,
  `previous_sha=94e227a2c…`, `previous_version=2.58.229`,
  `release_branch=release/p0-embed-503-failover-2.58.230`, `dirty_tracked=false`, `effect=deploy`,
  `deployer=builder-release-prep`. The previous-manifest input was seeded locally in git-ignored `.deploy/`
  and removed immediately; no production file was read.
- Rollback/base: `94e227a2c` (2.58.229), schema 48, DDL 0; no migration, no data action. Embedding cooldown
  state and any text-only rows written by an operator are ordinary runtime data, not reverted by a code
  rollback.
- `deploy-runbook-2.58.230.md`: preflight embedding config profiles (present, no secret values), backup,
  manifest before restart, restart, local/public health, identity, schema 48/DDL 0, `NRestarts`, journal,
  digests, disk `audit` + `cleanup --apply`, rollback to `94e227a2c`, and the bounded post-deploy live
  embedding check.

## 7. Limitations

- REVIEW only: no deploy, SSH, live provider call, settings/DB write, key/model change, or VERIFIED claim.
- No new visual/interactive Browser Use acceptance was performed: the diff contains no UI/web/config/handler
  change. B1/B2/B3 are existing served-byte regression checks (Playwright-based tools) and are not a claim
  about a live TMA session.
- The 15-file profile is targeted, not the whole ~10k-test repository. Pre-existing unrelated failures are
  not counted as this release's passes.
- B1/B2/B3 screenshots were produced by the e2e tools but removed from the release lane to keep the artifact
  compact; the complete e2e report JSON files are retained and contain the check/failure data.
- The live-route evidence is external (`f2540ac60`, 2.58.228). It was not rerun from this lane. The
  post-deploy check in the runbook is deliberately minimal and must not claim apinet is fixed.
- `requirements_gate.py check --stage plan` is a planning-master operation; this release branch carries the
  planning map for traceability but does not mutate the shared `progress_scope.json` / `workflow_state.md`.
