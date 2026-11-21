# Release 2.58.230 — P0-EMBED-503-FAILOVER (5xx failover + MSI admission c5)

**Status:** REVIEW / READY_FOR_DEPLOY_PREPARATION (assembly rerun after c5; no deploy).
The c5 seam is independently **APPROVED_FOR_DEPLOY** (`428843093`, addendum to `delta-review-r1.md`),
but the release branch had to receive c5 and be re-run first. No VERIFIED claim is made before a real
deployed SHA and production observations.
**Date:** 2026-11-22 06:05 (+12:00) / 2026-11-21 18:05 UTC
**Branch:** `release/p0-embed-503-failover-2.58.230`
**Base / rollback:** `94e227a2c096f4cc7b987c3253563bf0df442d17` (2.58.229, schema 48, DDL 0)
**Reviewed c5:** code `1b7d4bf0471a10aaff5d4f0c40eacd77f707727d`, branch head
`5fa47ec00eeb8f892abee13310f2ae48ea046bef` (parent `d00a01b07`), source `fix/embed-503-failover`.
**Review:** r1 `373a39615` + c5 addendum `428843093` (`APPROVED_FOR_DEPLOY`, c5 seam only;
`REL230-F1` closed by MSI admission). File `delta-review-r1.md` is included in this release evidence.
**Content tip (product/test):** `f90c0e59357be6c7728251bbd19b323bef5630f0`
**Version:** 2.58.230 (unchanged; c5 is code/tests only, no bump)
**Schema/DDL:** 48 / 0

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Start from the prior 2.58.230 release branch | `50e01523e` (content `9d5cf5173`; c1 failover + standard bump) |
| 2 | Cherry-pick c5 code `1b7d4bf` | `f90c0e593`; patch-id **identical** (`23acd4bb…`); 6 files, +591/−184; 0 conflicts |
| 3 | Cherry-pick c5 evidence `5fa47ec0` | `109e710d3`; patch-id **identical** (`b845178e…`); admission-correction, RED/GREEN, mutations, implementation update |
| 4 | Cherry-pick review addendum `428843093` | `2714b5aed`; the branch lacked the earlier `delta-review-r1.md`, so the conflict was resolved by adding the full current document (360 lines). Blob `dc1fd647…` is byte-identical to `428843093:…/delta-review-r1.md` |
| 5 | Version bump | **not repeated**; `9d5cf5173` remains 32 files / 35 / 35, `APP_VERSION=2.58.230`; c5 does not touch `config/settings.py` |
| 6 | Checks on `f90c0e593` | see §4; all required batches below |
| 7 | Manifest dry-run on `f90c0e593` | `manifest-dry-run.json`; exit 0; version 2.58.230; previous `94e227a2c` / 2.58.229; `dirty_tracked=false`; `.deploy` removed |
| 8 | This evidence commit | docs-only; no product/test bytes change it |

No merge commits (`git rev-list --merges 94e227a2c..f90c0e593` = 0), no force operations, no rebase of
published history. The c5 code/test bytes are identical to the reviewed c5 commit (patch-id equality);
the c5 evidence commit is docs-only. Detailed c5 defect/RED/GREEN/mutation record:
`plans/features/p0-embed-503-failover/evidence/admission-correction.md` and
`tests-admission-msi-2026-11-22.{json,txt}`.

## 2. Product delta review (base `94e227a2c` → content tip `f90c0e593`)

| File | Net base→tip |
|---|---|
| `services/embedding_control_plane.py` | **241 / 80** (c1 + c5; c5 itself 95/59) |
| `services/summary_memory.py` | **142 / 1** (c1 write seam; c5 docstring only 4/5) |
| `tests/test_p0_embed_503_failover.py` | **342 / 0** (c1 suite; c5 removed the PCI-bound case, 0/111) |
| `tests/test_p0_embed_admission_msi.py` | **478 / 0** (new, 10 tests) |
| `tests/test_embed_identity_compat.py` | **9 / 7** |
| `tests/test_embed_identity_compat_restart_legacy.py` | **5 / 2** |
| `config/settings.py` | 1 / 1 (APP_VERSION/changelog from the prior bump only) |
| 31 non-settings bump files | 34 / 34 (version literals only, unchanged from `9d5cf5173`) |

- **c5 delta alone:** 6 files, **+591/−184**; no config/web/DDL/prompts/handlers changes.
  `summary_memory.py` is docstring-only in c5 (4/5); c5 does not change its AST after docstring removal.
- **No new** flags, endpoints, migrations, prompts, models, indexes, UI or key changes. `migrations`,
  `database.py`, `prompts`, `web`, `handlers` are empty in the release delta; only `config/settings.py`
  carries the unchanged 2.58.230 version stamp.
- **Admission correction (c5):** `admission_valid()` keys on `space` (MSI), not `conn` (PCI); `conn` is
  provenance. Historical PCI-keyed admission is reused for the same model space.
  `resolve_index_compat()` returns `compatible/serviceable` for equal MSI (`ADMITTED_COMPATIBLE` if a
  durable admission exists, otherwise `INSTANT_COMPATIBLE`), `incompatible` for a real MSI/dimension
  mismatch, and only when active MSI is unavailable with saved vectors signals **one** bounded
  `compat_probe` (`msi_unavailable`). Success persists a durable space admission; failure stays text-only.
  Write/backfill gates continue to pass only `serviceable + compatible`; canary DRIFT still blocks.
  No new identity mechanism, no reindex, no model/key change.

## 3. Bump and invariants

- Version remains **2.58.230**; `APP_VERSION` AST = 2.58.230; the standard bump `9d5cf5173` is unchanged
  (32 files / 35 insertions / 35 deletions). c5 did not require a bump and did not touch settings/changelog.
- BOM/CRLF profiles remain as in the prior assembly for all bumped files; c5 code/tests are LF.
- `git diff --check` for the code/evidence delta is clean apart from preserved raw-log whitespace;
  `node --check web/app.js` rc=0; `py_compile` of settings, both services, both new tests and both e2e tools
  rc=0.
- No live version pin at 2.58.229; `git grep` outside previous evidence finds only the historical
  settings changelog.

## 4. Tests (content tip `f90c0e593`)

Machine-readable record: `tests-2.58.230.json`; raw outputs under `test-output/`.

| Batch | Result |
|---|---|
| New `tests/test_p0_embed_admission_msi.py` | **10 passed** (`10 passed in 10.51s`) |
| Updated `tests/test_p0_embed_503_failover.py` | **9 passed** (`9 passed in 4.63s`) |
| 19-file embedding/admission/recovery/backfill profile | **657 passed, 0 failed/errors/skipped, 1 deselected** (`82.63s`) |
| Deselected pre-existing | `tests/test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced` (reproduced on base `d00a01b07`; unrelated warning coalescing) |
| Target frozen-pin tests (2) | **2 passed** |
| Pin-guard, 24 Python version-pin files | **856 passed / 4 failed** — same 4 pre-existing IDs, no candidate-caused pin breach |
| B1 status e2e | **138 checks / 0 failures**, `M4B-STATUS-E2E-OK` |
| B2 status e2e | **92 checks / 0 failures**, `M4B-B2-STATUS-E2E-OK` |
| B3 status e2e | Run 1: 131 checks / 1 failure `detail_closed`; **identical re-run: 131/131, 0 failures**, `M4B-B3-STATUS-E2E-OK` (known timing flake; both reports retained) |
| JS version pins (hotfix7/8/9/10) | **4/4 rc=0** |
| Syntax | `node --check` rc=0; `py_compile` rc=0 |

RED reference (c5 evidence, independently reproduced by Reviewer): on base `d00a01b07` the new admission
suite is **6 failed / 4 passed** — same-MSI INSTANT, historical PCI admission, same-MSI write+semantic,
backfill, and no-MSI probe cases fail; guard cases pass. This release run did not re-run RED from the
release branch; the c5 RED log is `tests-red-base-msi-2026-11-22.txt`.

### 4.1 KNN / semantic result (the owner acceptance criterion)

`test_same_msi_different_pci_writes_and_semantic_search` passed and asserts:
- primary `apinet_paid` returns 503 → `fallback_1` `google_free_1` returns 200 (calls `k-primary`, `k-fb1`);
- `graph_facts_vec == 1` — the fallback vector is actually written, not only HTTP 200;
- real sqlite-vec KNN `SELECT fact_id FROM graph_facts_vec WHERE embedding MATCH ? AND k = ?` returns the
  new fact id;
- after primary recovers, a second fact is written through primary (`graph_facts_vec == 2`) and the first
  semantic hit remains, so the old vector is not lost.

Companion cases: `test_text_only_backfill_recovers_via_same_msi_fallback` recovers a text-only fact through
the same-MSI fallback idempotently (`1` vector, repeat `0`, semantic hit); `test_different_msi_is_text_only`
and `test_dimension_mismatch_is_text_only` keep `graph_facts_vec == 0`; `test_no_msi_probe_*` performs
exactly one bounded probe on old rows and either persists a durable space admission (`13` vectors + hit) or
stays text-only (`12` vectors).

## 5. Requirements bound by this assembly

Eligibility is for release preparation only; **no requirement is VERIFIED before a real deploy and
production-bound evidence**. `REL230-F1` is closed by c5.

| ID | Status after c5 |
|---|---|
| `E503-FAILOVER-01` | PASS_CODE_DEPLOY_PENDING |
| `E503-AUTH-01` | PASS |
| `E503-IDENTITY-01` | PASS_CODE (MSI admission; live production observation pending) |
| `E503-RECOVERY-01` | PASS_CODE (same-MSI write/backfill; live T0/T1 pending) |
| `E503-DIAG-01` | PASS_CODE |
| `E503-ACCEPT-MATRIX-01` | PASS_CODE (vector + semantic KNN locally proven; live pending) |
| `E503-EXCLUSIONS-01` | PASS_SCOPE_DEPLOY_PENDING |
| `E503-ROUTE-01` | EXTERNAL_EVIDENCE_f2540ac60_NOT_RERUN |
| `E503-REPORT-01` | PENDING_FINAL_REPORT |

Non-blocking: `REL230-N01` (manifest is now regenerated on the new content tip `f90c0e593`; deploy must
still record the actual host HEAD), `REL230-N02` (B3 `detail_closed` timing flake; identical re-run green,
web bytes unchanged from base), `REL230-N03` (pin failure evidence is environment-dependent; no
candidate-caused pin breach), `REL230-N04` (`E503-R1-N02` must be re-scoped from PCI to MSI+canary; backlog
only), `REL230-N05` (per-fallback-alias canary hardening; backlog only). `E503-R1-N01` remains
backlog-only. `REL230-F1` is closed, not a blocker.

`apinet` 503 remains an external fact and is **not** declared fixed. Google PCI admission is **not**
claimed; c5's contract is MSI/model-space equality with `conn` as provenance, plus a bounded probe only
when MSI metadata is unavailable.

## 6. Manifest, rollback, runbook

- `manifest-dry-run.json`: exit 0; `deployed_sha=f90c0e593…` (new content tip), `version=2.58.230`,
  `previous_sha=94e227a2c…`, `previous_version=2.58.229`,
  `release_branch=release/p0-embed-503-failover-2.58.230`, `dirty_tracked=false`, `effect=deploy`,
  `deployer=builder-release-prep`. The previous-manifest input was seeded locally in git-ignored `.deploy/`
  and removed immediately; no production file was read.
- Rollback/base: `94e227a2c` (2.58.229), schema 48, DDL 0; no migration/data action.
- `deploy-runbook-2.58.230.md`: preflight profiles (no secret values), backup, manifest before restart,
  restart, local/public health, identity, schema 48/DDL 0, `NRestarts`, journal, digests, disk
  `audit` + `cleanup --apply`, rollback to `94e227a2c`, and the bounded post-deploy check with a real
  semantic KNN hit, T0/T1 text-only counters, actual served alias/host.

## 7. Limitations

- REVIEW/preparation only: no deploy, SSH, live provider call, DB/settings/key/model write, or VERIFIED claim.
- The semantic KNN hit is proven on local sqlite-vec with deterministic vectors (the product path), not on
  production data. Live production KNN/text-only T0→T1 remains for the deploy runbook.
- Live-route evidence `f2540ac60` is external (2.58.228) and was not rerun; apinet 503 remains external.
- B3 `detail_closed` flaked once and cleared on the identical re-run; both reports are retained. This is the
  known timing flake, not a candidate regression (web bytes unchanged).
- The 19-file profile is targeted, not the whole ~10k test repository; the single deselected test is
  pre-existing and named explicitly, not counted as a pass.
- No new visual/UI change; B1/B2/B3 are served-byte regressions with existing stubs, not a live TMA session.
