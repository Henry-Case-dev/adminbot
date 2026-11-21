# Release 2.58.229 — MOD-ACL-UX-01 M4C C1 (roles page / honest read states / whole-object preservation)

**Status:** REVIEW (assembly only; **not deploy-ready** until `REL-229-PIN-01` is resolved — see §6)
**Date:** 2026-11-22 02:52 (+12:00) / 2026-11-21 14:52 UTC
**Branch:** `release/mod-acl-m4c1-2.58.229`
**Base / rollback:** `374dc60609986a9250170a34a48c93bf2ba85e29` (2.58.228, schema 48, DDL 0)
**Reviewed candidate:** `eb305b6fe7b5f21a9707b7d6a2aff37f7bfb4435` (product, parent `c334b7578`), evidence tip `83a38a5be4a8ab50c3a5f9436d67ef90ee3f9534` (`feat/mod-acl-m4c1`)
**Review:** `plans/features/mod-acl-ux-01/evidence/m4c/c1/review-r1-addendum.md` (master `b2f3d1889`), verdict `APPROVED_FOR_RELEASE_PREPARATION`, F01/F02/F03 resolved, no new findings. Original r1: `review-r1.md` (master `a913f2b1e`).
**Content tip (bump):** `95485a609aeb559ffe88531635f345a3528f026b`
**Version:** 2.58.229
**Schema/DDL:** 48 / 0

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Worktree/branch from `374dc6060` | `workflow_housekeeping.py worktree-path --epic mod-acl-ux-01` → `git worktree add <path> -b release/mod-acl-m4c1-2.58.229 374dc6060` → `register-worktree`; 0 conflicts |
| 2 | Cherry-pick `422dbbd38^..83a38a5be` (7 commits, 0 merges, no force) | `61a7df0e8` C1.1, `86a072331` C1.2, `8131906a4` evidence, `b5a3b8938` limits, `bb53adc98` owner counts, `005d5ae2d` c3 F01/F02/F03, `3fdd560e9` evidence r1 |
| 3 | Product identity | `git diff 83a38a5be 3fdd560e9` = **empty**; release branch tree is byte-identical to the reviewed candidate tree |
| 4 | Standard bump 2.58.228 → 2.58.229 | `95485a609`; **32 files / 35 insertions / 35 deletions** (§3) |
| 5 | Tests on bumped tip `95485a609` | §4 — including one **new** pin-guard regression (`REL-229-PIN-01`) |
| 6 | Manifest dry-run | `manifest-dry-run.json`; exit 0; version 2.58.229; previous `374dc6060` / 2.58.228; `dirty_tracked=false`; `.deploy` removed immediately |
| 7 | Release evidence (this directory) | docs-only commit after `95485a609` |

The cherry-pick range contained **7** commits, not 4: the C1 branch carries C1.1/C1.2, two evidence commits, one limits-clarification
commit, the owner-counts commit and the c3 fixes. The whole range `422dbbd38^..83a38a5be` was applied; no merge commits were created.

## 2. Product delta review (base `374dc6060` → content tip `95485a609`)

| File | Net base→tip |
|---|---|
| `web/app.js` | **739 / 51** |
| `web/index.html` | **381 / 211** |
| `web/static/app.css` | **182 / 0** |
| `services/access.py` | **23 / 4** |
| `web/api/access.py` | **8 / 1** |
| `web/api/routes.py` | **12 / 0** (three honest 503 guards on `GET /api/admins`, `/api/roles`, `/api/roles/tree` when the cache is empty **and** PG is unavailable; no new endpoints) |
| `config/settings.py` | 1 / 1 (APP_VERSION + changelog line) |

Totals at the content tip: **77 files, 4069 insertions / 778 deletions**
(7 product, 35 tests, 4 tools, 31 planning/evidence files incl. the APP_VERSION stamp).

- New endpoints/fields/flags: **0** (`git diff … -- web services | grep '^+.*@api_router|@access_router'` empty).
- DDL/migrations/prompts: `git diff 374dc6060 HEAD -- migrations database.py prompts` = **empty**;
  no `CREATE/ALTER/DROP TABLE|INDEX` in the delta.
- Reviewed C1 delta is unchanged: the only difference between the candidate tip and the content tip is the version wave (§3).
- Served bytes of the bumped tip (identical to the reviewed candidate bytes):
  `web/app.js 59a583fca1b514e6bdb5f791faa268ffef6af16692aad1d199e14c4cb3f288ef`,
  `web/index.html db30ba904d60ab2cba5331089a880f00713f89c0ad2ad46eb7977fc8d385b79b`,
  `web/static/app.css 8a55ed9db3ed74e3605588daaf09ac5a2a44515817f920feed48074350ec008d`.

## 3. Bump and invariants

- `APP_VERSION = "2.58.229"` with a full M4C C1 changelog entry and `Prior 2.58.228`; base noted as `374dc6060 (2.58.228)`.
- Live pins swept: 28 plain-text files (24 Python + 4 escaped JS pins in `round1025_hotfix7/8/9/10`) +
  2 e2e tools (`m4b2` ×3, `m4b3` ×1) + the registry stamp + `config/settings.py` = **32 files / 35 / 35**,
  the same shape as the 2.58.228 reference (no extra live pin appeared).
- **New C1 e2e tool `tools/ui_mod_acl_m4c1_roles_e2e.py` has no version pin at all** (no `PROD_VERSION`, no `/api/status`
  stub, no `2.58.*` literal); there is nothing to add or re-pin there. The roles page does not render the app version.
- Every non-settings bump diff is a version literal only (`2.58.228`→`2.58.229`, incl. escaped `2\.58\.228`);
  verified programmatically (0 lines outside the version pattern).
- BOM/CRLF preserved byte-level: `config/settings.py` keeps UTF-8 BOM and 3645 CRLF + 1 bare final LF, unchanged from base;
  all 32 bumped files keep their original BOM/line-ending profile (0 mismatches).
- `git diff --check` rc=0; `node --check web/app.js` rc=0; `py_compile` of settings, the three changed Python product files,
  the C1 pytest file, the three e2e tools rc=0.
- `git grep -n "2\.58\.228"` after the bump: only historical text — the settings changelog (`Prior 2.58.228`, base note),
  two `web/app.js` data-defect comments, one comment in `tests/js/mod_acl_ux_m4c1_editor_preserve_test.js`,
  the C1 candidate evidence JSON bodies and the previous-release evidence directories. No live pin at 2.58.228.
- No production, SSH, DB, LLM, settings or chat-override writes; no deploy.

## 4. Tests (bumped tip `95485a609`)

Machine-readable record: `tests-2.58.229.json`; raw outputs: `tests-2.58.229.txt`, `test-output/`.

| Batch | Result |
|---|---|
| C1 Node suites (`mod_acl_ux_m4c1_roles_page_test.js`, `mod_acl_ux_m4c1_editor_preserve_test.js`) | **2/2 PASS** (`MOD-ACL-UX-M4C1-ROLES-PAGE-OK`, `MOD-ACL-UX-M4C1-EDITOR-PRESERVE-OK`) |
| Node sweep `tests/js/*.js` (130 suites + helper, `node --check` all) | **127 pass / 3 fail**, `NODE_CHECK_OK`; failing set `evol_cog_scene_test.js`, `round1025_ia_routing_test.js`, `ur_ui_settings_test.js` — all three reproduced rc=1 on base `374dc6060`, pre-existing |
| Focused pytest (9 files, C1-adjacent) | **320 passed / 1 failed** — `test_webapp_hubs_matrix_ui.py::TestReviewerMinorsR1R4::test_r4_custom_modules_removed`, pre-existing on base |
| New `tests/test_webapp_access_matrix_read.py` | **17/17 passed** |
| JS pins (4 hotfix version pins + 2 C1 suites) | **6/6 exit 0** |
| Pin-guard, 24 Python files on the bumped tip | **854 passed / 6 failed** — 4 known pre-existing (`TestBounds::test_forbidden_paths_out_of_diff`, `TestBounds::test_canon_twelve_tools`, `TestToolDescriptionU21::test_canon_unchanged`, `TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`) **+ 2 NEW** (`test_mca17c_invariants_round1047.py::test_routes_py_byte_freeze_pin_intact`, `test_round1025_f8_registry.py::TestFrozenInvariants::test_routes_file_unchanged`) |
| Pin-guard, same 2 new node IDs on base `374dc6060` | **2 passed** → the two failures are introduced by the C1 `web/api/routes.py` change, not by the bump (see §6) |
| B1 status e2e | **138 checks / 0 failures**, `M4B-STATUS-E2E-OK` |
| B2 status e2e | **92 checks / 0 failures**, `M4B-B2-STATUS-E2E-OK` |
| B3 status e2e | **131/131**, `M4B-B3-STATUS-E2E-OK`, 8 screenshots; first run 130/131 with the known `detail_closed` timing flake, identical re-run 131/131 |
| C1 Playwright e2e (`ui_mod_acl_m4c1_roles_e2e.py`) | **PASS, 0 failures**; report `test-output/c1/shots/report.json` |
| Syntax | `node --check` rc=0; `py_compile` rc=0 |

C1 e2e assertions on the bumped tip (from `report.json`): 7 viewports 1920/1440/1280/768/390/360/320 with
`scrollWidth == innerWidth`, no horizontal scroll, no nested scrollers; 1440/1920: `roles=5`, `sections=12`,
`matrixGroups=121`, `622 из 622`; `F02@<viewport>` delete disabled / rename enabled / usage note
«Удаление недоступно: роль назначена 1 админ(ам) — сначала переназначьте.»; `error-roles-401/403/503` →
`rolesCount=null`, `error-matrix-403/503/non-global` → `matrixCount=null` + forbidden card, `has_0_iz_0=false` in
every error case; `error-tree-404` → `retryList=true`, `retryRolesDelta=1` (real `/api/roles` retry).

No test logic was changed by the bump; only version literals.

## 5. Rows bound by this assembly

- **18 C1 rows VERIFIED-eligible** after independent review (14 bound at r1 + 4 newly eligible after F01/F02):
  MAC-S0-10, MAC-S5-293, MAC-S8-502, MAC-S8-503, MAC-S8-504, MAC-S8-521, MAC-S8-522, MAC-S15-09, MAC-S15-13,
  MAC-S15-1-08, MAC-S8-PAGE-01, MAC-S8-PAGE-02, MAC-S8-LAY-01, MAC-AC-13, MAC-S4-175, MAC-S5-294, MAC-S8-501, MAC-S8-SEC-01.
  Eligibility is binding for release preparation only; **no row is VERIFIED before an actual deploy** and
  production-bound evidence.
- **SCN-01** (live non-global/TMA session) — **RFL**: local stand only, not owner QA, no VERIFIED claim.
- **C2/C3 out of scope**: effective/preview/chat-override/audit/revisions/409 UI, S1/S2/S3 guards and
  `#/access/admins|local` are not changed by this release.
- Production read-only preflight 6.4 (`bot_roles`/`bot_admins`) — **mandatory for the deploy step** (§7 of the runbook),
  not executed in this lane (no production access by Builder).

## 6. Open finding — REL-229-PIN-01 (blocking deploy)

**Defect:** C1 changed `web/api/routes.py` (+12: three honest 503 guards) but did not re-pin the intentional
byte-freeze baseline `ROUTES_SHA256_F11` (`tests/test_round1025_f8_registry.py`, consumed by
`test_mca17c_invariants_round1047.py::test_routes_py_byte_freeze_pin_intact`). Both freeze tests pass on base
`374dc6060` and fail on the C1 tip; the C1 lane never ran them (its focused pytest set did not include these files).

**Evidence:** `test-output/pin-guard-tip.txt`, `tests-2.58.229.json` (`pin_guard.*`), base re-run of the two node IDs
(2 passed) in `test-output/pin-guard-base.txt`.

**Why not fixed here:** the project’s own rule for this pin is a *conscious* re-pin (`L-F11S-1`), i.e. a product/test
change that needs its own reviewed commit; it is outside the version-only bump scope of this lane and must not be
performed unilaterally by the release builder.

**Sanctioned remedy (for the C1 owner + independent Reviewer):** add one c4 commit on `feat/mod-acl-m4c1`
re-pinning `ROUTES_SHA256_F11` to the new digest with a rationale comment (the delta is three `503` guards, no
endpoints/fields/flags/DDL), extend the C1 evidence with a pin-guard run, get a Reviewer addendum, then cherry-pick
that one commit onto this release branch (bump stays valid) and re-run the 24-file pin-guard (expected 856/4).
Until then this branch must **not** be deployed.

## 7. Manifest, rollback, runbook

- `manifest-dry-run.json`: exit 0; `deployed_sha=95485a609…` (content tip), `version=2.58.229`,
  `previous_sha=374dc6060…`, `previous_version=2.58.228`, `release_branch=release/mod-acl-m4c1-2.58.229`,
  `dirty_tracked=false`, `effect=deploy`, `deployer=builder-release-prep`. The previous-manifest input was seeded
  locally in git-ignored `.deploy/` and removed immediately; no production file was read.
- Rollback/base: `374dc6060` (2.58.228), schema 48, DDL 0; no migration, no data action. `bot_roles`/`bot_admins`
  rows written by an operator during 2.58.229 are ordinary UI data and are not reverted by a code rollback.
- `deploy-runbook-2.58.229.md`: preflight 6.4 (read-only `bot_roles`/`bot_admins`), backup, manifest **before**
  restart, restart, local/public health, identity, schema 48/DDL 0, `NRestarts`, journal, prompt/settings digests
  pre==post, disk `audit` + `cleanup --apply`, rollback to `374dc6060`; no live-chat/LLM check.

## 8. Limitations

- REVIEW only: no production deploy, no SSH, no live Telegram/TMA/provider call, no settings or DB writes, no VERIFIED claim.
- `REL-229-PIN-01` open (§6) — the only regression vs base and a deploy blocker.
- C1 e2e is served bytes + API stubs from the real `param_catalog`/`module_registry` with `TMA_STUB`, not a live TMA
  session; live non-global/TMA observation remains RFL and is not owner QA.
- B3 `detail_closed` timing flake reproduced once (130/131) and cleared on the identical re-run (131/131); not C1-related.
- The C1 evidence screenshots under `m4c/c1/shots/` were produced from the same served bytes; the release lane keeps
  only the report JSON to stay compact.
- `requirements_gate.py check --stage plan` is not applicable on this release branch (`requirements-map.json` is a
  planning-master artifact); the Reviewer’s addendum records the same boundary.
- Pre-existing failures (3 JS, 1 Python, 4 pin-guard) are not counted as passes; each is re-verified on base.
