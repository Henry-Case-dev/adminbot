# Release 2.58.231 — P0-EMBED-503-FAILOVER postdeploy corrective (park 5xx leg + bounded spend-group probe)

**Status:** REVIEW / READY_FOR_DEPLOY_PREPARATION (assembly complete; no deploy). The postdeploy
candidate is independently **APPROVED_FOR_RELEASE_PREPARATION** (`postdeploy-fix-review-r1.md`,
master `73a6ca8f0`): D1/D2/D3 closed; N01/N02 nonblocking. No VERIFIED claim before a real deployed
SHA and production observations.
**Date:** 2026-11-22 10:18 (+12:00) / 2026-11-21 22:18 UTC
**Branch:** `release/p0-embed-postdeploy-2.58.231`
**Base / rollback:** `d86bf66d408266c928e24714c2f5779a4ddf8ebe` (2.58.230, schema 48, DDL 0)
**Candidate:** code `7171a227d93fdb990c591a65fc0a33bd110ce092`, tip
`fe5ab2c5ebda9fc1a174f97c90647fa7a502dc9e`, source `fix/embed-postdeploy-park`.
**Version:** 2.58.231
**Schema/DDL:** 48 / 0
**Manifest dry-run:** `manifest-dry-run.json` (deployed_sha = `08d213b5f…` = bump commit; docs commit above it, see §6).

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | `git worktree add <worktree-path> -b release/p0-embed-postdeploy-2.58.231 d86bf66d4`; registered | worktree `/…/p0-embed-503-failover-4b793b62d746-0acd5437`, clean |
| 2 | Cherry-pick code `7171a227d` | `8ca1371d3`; patch-id **identical** `c5cd4094…`; 2 files, +577/−32; 0 conflicts |
| 3 | Cherry-pick evidence `fe5ab2c5e` | `05b80b9a4`; patch-id **identical** `88fe3ef4…`; 1 docs file, +199 |
| 4 | Standard version wave 2.58.230 → 2.58.231 | `08d213b5f`; **32 files, 35 insertions / 35 deletions**; settings line rewritten with a new changelog entry |
| 5 | Checks on bumped tip `08d213b5f` | see §4; all batches below |
| 6 | Manifest dry-run on `08d213b5f` | exit 0; version 2.58.231, previous `d86bf66d4`/2.58.230, `dirty_tracked=false`, `.deploy` removed |
| 7 | This evidence commit | docs-only; no product/test bytes change it |

`git rev-list --merges d86bf66d4..HEAD` = **0**; no force operations, no rebase of published history.
The 2.58.230 release worktree stayed at `d86bf66d4`; C2 `feat/mod-acl-m4c2` stayed at `ba8b93121` —
neither was used or modified (`git diff --name-only d86bf66d4..HEAD` has no `mod-acl`/`m4c2` path).

## 2. Product delta (base `d86bf66d4` → content tip `08d213b5f`)

| File | Net base→tip |
|---|---|
| `services/embedding_control_plane.py` | **253 / 28** |
| `tests/test_p0_embed_503_failover.py` | **324 / 4** |
| `config/settings.py` | 1 / 1 (version stamp + changelog) |
| 31 other standard-wave files | 34 / 34 (version literals only) |
| `plans/…/evidence/postdeploy-fix.md` | 199 / 0 (docs) |

- **Fix behavior (reviewed D1/D2/D3):** a 5xx/timeout embedding leg is parked/deferred even when no
  other leg is currently usable (no return to the per-operation primary storm); a genuinely
  single-credential pool keeps the honest bounded transport behaviour. A P2_REPAIR-only bounded probe
  (one per quota group per 900 s) may re-test a `spend`/`daily_project` parked group without manual
  state edits; P0/P1/P3 respect cooldown; 429/5xx keeps the group parked; 401/403 and code defects
  are not swallowed. No change to MSI admission, model/key, routes, prompts, handlers, web or DDL.
- **No new** flags, endpoints, migrations, prompts, models, indexes, UI or key changes. `migrations`,
  `database.py`, `prompts`, `web`, `handlers` are empty in the release delta; the only config file is
  `config/settings.py` with the version stamp/changelog.
- `apinet` 503 remains external and is **not** fixed; Google 429/quota remains external. N01: a
  same-process spend-429 credential cooldown still blocks probe until expiry — the postdeploy incident
  is covered because a restart clears the in-memory cooldown, not because the probe is a universal
  self-heal. N02: a second healthy credential of the same group can be skipped; prod has one key per
  Google group, so it is not exercised live.

## 3. Bump and invariants

- `APP_VERSION` AST/string = **2.58.231**; the standard wave is exactly **32 files / 35 / 35**
  (`git show --stat 08d213b5f`), matching the previous-release wave; `plans/docs/param-registry-round1025.meta.md`
  pins `2.58.231`; JS regex pins use `2\.58\.231` (4 files).
- BOM/CRLF profiles were verified against the parent blob for all 32 files: identical BOM presence and
  identical CR/LF counts (settings keeps UTF-8 BOM and CRLF).
- `git grep` outside historical evidence finds no live `2.58.230` pin: remaining references are the
  settings historical changelog ("Prior 2.58.230", base note), one RED docstring in the candidate test
  and the previous release evidence (`release-2.58.230/`, `postdeploy-fix.md`).
- `git diff --check` rc=0; `node --check web/app.js` rc=0; `py_compile` of 29 changed .py files rc=0.
- No migration/DDL; schema remains 48 / DDL 0; no settings/keys/models/chat overrides touched.

## 4. Tests (bumped tip `08d213b5f`)

Machine-readable record: `tests-2.58.231.json`; raw outputs under `test-output/`.

| Batch | Result |
|---|---|
| New `tests/test_p0_embed_503_failover.py` | **19 passed** (11.97 s) |
| `tests/test_p0_embed_admission_msi.py` | **10 passed** (5.10 s) |
| 19-file embedding/admission/recovery/backfill profile | **667 passed, 0 failed/errors/skipped, 1 deselected** (66.14 s, 1 non-failing warning) |
| Deselected pre-existing | `tests/test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced` |
| Pin-guard, 24 Python version-pin files | **856 passed / 4 failed** (74.94 s) |
| Pin-guard base control `d86bf66d4` | **856 passed / 4 failed — exactly the same 4 IDs** (84.21 s) |
| B1 status e2e | **138 checks / 0 failures**, `M4B-STATUS-E2E-OK` |
| B2 status e2e | **92 checks / 0 failures**, `M4B-B2-STATUS-E2E-OK` |
| B3 status e2e | **131 checks / 0 failures**, 8 screenshots, `M4B-B3-STATUS-E2E-OK` |
| JS version pins (hotfix7/8/9/10) | **4/4 rc=0** |
| Syntax | `node --check` rc=0; `py_compile` 29 files rc=0 |

The 4 pin failures are the same pre-existing IDs on base (`test_forbidden_paths_out_of_diff`,
`test_canon_twelve_tools`, `test_canon_unchanged`, `test_forbidden_paths_out_of_diff_vs_baseline`);
the candidate-touched files among them differ from base only by the version literal. Base control was
run in a temporary detached `d86bf66d4` worktree that was removed after the run (no force).

RED and mutations were not duplicated here: candidate RED `11 failed / 8 passed` on base is in
`postdeploy-fix.md` and was independently reproduced by Reviewer (`postdeploy-fix-review-r1.md` §5.5);
M1–M3 were Builder mutations with file restoration (same evidence).

### 4.1 Semantic/vector acceptance (carried by the reviewed suite)

`test_same_msi_different_pci_writes_and_semantic_search` (from the 2.58.230 MSI admission wave, still
green 10/10) and the new probe/backfill cases assert the product path: admitted same-MSI fallback →
real `graph_facts_vec` row → real sqlite-vec KNN hit; probe backfill writes a vector and a repeat is
idempotent; different MSI/dimension stays text-only. Local proof only; live production
`graph_facts_vec` growth, KNN hit and backlog are deploy checks (§5 of the runbook).

## 5. Requirements bound by this assembly

Eligibility is for release preparation only; **no requirement is VERIFIED before a real deploy and
production-bound evidence**. D1/D2/D3 from the postdeploy review are closed.

| ID | Status after the corrective |
|---|---|
| `E503-FAILOVER-01` | PASS_CODE_DEPLOY_PENDING (park/deferred when alternatives unusable) |
| `E503-AUTH-01` | PASS (single-credential honest transport; no spin) |
| `E503-IDENTITY-01` | PASS_CODE (MSI admission unchanged; live observation pending) |
| `E503-RECOVERY-01` | PASS_CODE (bounded P2 spend-group probe; live T0/T1 pending) |
| `E503-DIAG-01` | PASS_CODE |
| `E503-ACCEPT-MATRIX-01` | PASS_CODE (vector + semantic KNN locally; live pending) |
| `E503-EXCLUSIONS-01` | PASS_SCOPE_DEPLOY_PENDING |
| `E503-ROUTE-01` | EXTERNAL_EVIDENCE_NOT_RERUN (`apinet` 503 external) |
| `E503-REPORT-01` | PENDING_FINAL_REPORT |

Non-blocking: `EMBED-POSTDEPLOY-R1-N01` (same-process spend-429 probe waits for cooldown/restart; not
universal self-heal) and `EMBED-POSTDEPLOY-R1-N02` (second healthy credential of one group may be
skipped; one leg per prod group). `REL230-N04`/`N05` and `E503-R1-N01` remain backlog-only.

## 6. Manifest, rollback, runbook

- `manifest-dry-run.json`: exit 0; `deployed_sha=08d213b5f…` (bump commit), `version=2.58.231`,
  `previous_sha=d86bf66d4…`, `previous_version=2.58.230`, `release_branch=release/p0-embed-postdeploy-2.58.231`,
  `dirty_tracked=false`, `effect=deploy`, `deployer=builder-release-prep`. The prior-manifest input was
  seeded locally in git-ignored `.deploy/` from the documented 2.58.230 state and removed immediately;
  no production file was read. The docs evidence commit above the bump is docs-only; the host must
  record the **actual HEAD** at deploy (the product diff from `08d213b5f` must be empty).
- Rollback/base: `d86bf66d4` (2.58.230), schema 48, DDL 0; no migration/data action. In-memory
  credential/group-probe state is not reverted by a code rollback; `embedding_quota_state` rows stay
  as persisted.
- `deploy-runbook-2.58.231.md`: preflight profiles, backup, manifest actual HEAD, restart,
  health/identity/schema/DDL/NRestarts/journal/digests/disk, and the bounded post-deploy proof:
  restart clears the in-memory credential cooldown; the existing `embed_recovery_tick`/P2 backfill must
  perform one probe of a spend-parked group; verify real `graph_facts_vec` growth, a KNN hit on the
  backfilled/new row and backlog before/after. If Google returns 429/5xx the group stays parked and
  the run reports honest external degradation. No manual group-state edits, no model/key/settings
  changes, no reindex.

## 7. Limitations

- REVIEW/preparation only: no deploy, SSH, live provider call, DB/settings/key/model write, or
  VERIFIED claim.
- Local vector/KNN proof uses deterministic test fixtures, not production data; live
  `graph_facts_vec`/KNN/backlog remain for the deploy runbook.
- `apinet` 503 and Google 429/quota are external facts; the corrective neither fixes apinet nor
  cancels the actual spend.
- The 19-file profile is targeted, not the whole ~10k test repository; the single deselected test is
  pre-existing and named explicitly, not counted as a pass.
- B3 `detail_closed` timing flake was not observed here (first run 131/131 green); this is the same
  served-byte suite as prior releases, not a live TMA session. No visual change is part of this release.
