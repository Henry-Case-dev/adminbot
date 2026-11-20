# Release 2.58.224 — MOD-ACL-UX-01 M4B B1: пять лент «Статуса»

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-20 (+12:00)
**Branch:** `release/mod-acl-m4b1-2.58.224`
**Base / rollback:** `40fe603f0aac853af99656bac1934ec5f3d160f9` (2.58.223, schema 48, DDL 0)
**Approved candidate:** product `5f8026b2fb9a1509c09df834b2154d8c3c71d393`, branch tip `b360cd8aa866a7892ede1754eaae23c6ebceb997`
**Reviewer r2:** `review-r2.md`, sha256 `9c5005663e58b4e140c5323144ed4ca681ed358c8beb092e367c567e79dd7e34`, verdict `APPROVED_FOR_RELEASE_PREPARATION`
**Bump / content tip:** `57e123db7c6c2a34d1fb873fe2cb595878bd2566`
**Version:** 2.58.224
**Schema/DDL:** 48 / 0

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Branch already based on `40fe603f` | `release/mod-acl-m4b1-2.58.224`; product candidate `5f8026b2f`, reviewed tip `b360cd8aa` |
| 2 | Standard bump `2.58.223 -> 2.58.224` | `57e123db7`; **30 files / 31 insertions / 31 deletions** |
| 3 | Product delta checks | web files unchanged since `b360cd8aa`; only `config/settings.py` outside tests/meta |
| 4 | Tests on bumped tip | mandatory 386; B1/W2a/W2c/W2b; 6-file 9F/171P; broad 122/3; B1 e2e 138/0; w10/w15 B1 subset |
| 5 | Schema smoke | target 48, user_version 48, schema_migrations max/count 48, DDL 0 |
| 6 | Manifest dry-run at content tip | `manifest-dry-run.json`; exit 0; previous 40fe603f/2.58.223 |
| 7 | Release evidence (this directory) | docs-only commit after content tip |

No merge commit: the feature branch is based directly on `40fe603f` and contains
the reviewed product/tests plus the standard bump. Bump does not touch `web/`
(`git diff b360cd8aa..57e123db7 -- web` is empty).

## 2. Product delta review

| File | Net base→bump | Commit-sum (r0 + r1) |
|---|---|---|
| `web/app.js` | **271 / 80** | **283 / 92** (r0 246/76 + r1 37/16) |
| `web/index.html` | 63 / 76 | 63 / 76 |
| `web/static/app.css` | 35 / 138 | 35 / 138 |
| `config/settings.py` | 1 / 1 (APP_VERSION/changelog) | — |

- Branch-sum arithmetic for `web/app.js` is `+283/-92` (the reviewer/owner figure). The
  net `git diff` is `271/80` because the r1 edits replace some lines introduced by r0
  in the same hunks; product files are unchanged since `b360cd8aa`.
- `git diff --name-only 40fe603f..57e123db7 -- web` = only `web/app.js`,
  `web/index.html`, `web/static/app.css`.
- `git diff --name-only 40fe603f..57e123db7 -- services handlers web/api database.py migrations`
  = **empty** (no backend/API/DDL/flags/prompts/storage).
- `config` delta = only `config/settings.py` (APP_VERSION/changelog).
- Feature: five live Status ribbons in one widget; person-centric Dossier projection of
  the existing `/api/oversight/dossier_feed`; bottom ticker/card and dead model/CSS
  removed; grid 3+2 / 2+2+1 / 1 + tabs; shared scroll/pause/resume/detail/provenance;
  a11y tablist/aria-current/roving tabindex/touch 44; scope-keyed dossier snapshot with
  epoch+generation (no cross-scope stale rows).

## 3. Bump and invariants

- `APP_VERSION = "2.58.224"` with the M4B B1 changelog entry and `Prior 2.58.223`.
- Standard pins: `plans/docs/param-registry-round1025.meta.md`, 24 Python tests,
  4 JS tests (escaped `2\.58\.224`). Exactly **30 files / 31 insertions / 31 deletions**.
- BOM/CRLF preserved byte-level: settings.py keeps UTF-8 BOM + 3645 CRLF; the
  other files keep their existing BOM/line endings (no count changed). 0 mismatches.
- `node --check web/app.js` rc=0; `git diff --check 40fe603f..57e123db7` rc=0.
- Temp SQLite schema smoke: target 48, `user_version=48`,
  `schema_migrations` max/count 48, DDL delta 0.

## 4. Tests

Machine-readable record: `tests-2.58.224.json`; outputs under `test-output/`.

| Batch | Result |
|---|---|
| Mandatory 24-file pytest | **386 passed, 0 failed** |
| B1 node + asap6 + W2a/W2c/W2b | **11/11 rc=0**: B1 marker, ASAP-UI02, DOSSIER-FEED, F11, SOUL1, JS-UNIT, EVOL-001-005, WAVE2-UX-TABS, W2a 141, W2c 84, W2b 397 |
| 6-file Python contract | **9 failed / 171 passed** — exactly the base 9, 0 candidate-only |
| Broad JS (`tests/js/*_test.js`) | **125 files, 122 passed, 3 failed** — `evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings` (base pre-existing) |
| Version pins (24 Python / 4 JS) | **856 passed / 4 failed** (same 4 base pin guards); JS pins **4/4** |
| B1 Playwright e2e | **138 checks, 0 failures** (includes F03 cross-scope) |
| w10 affected flow | B1 checks green; 3 pre-existing module/catalog failures only |
| w15 B1 subset (Status dossier + record + Analytics absence) | **0 failures** at 1280/390 |
| Schema smoke | **48 / 48 / 48**, DDL 0 |

Base 9 failures in the 6-file set (same on candidate):
`TestEvol027Catalog` (4), `test_live_render_sections_e2e` (1),
`test_role_classes_have_no_literal_geometry` (1), `TestNavigationSnapshot` (2),
`TestHumanReadableLabels::test_examples_from_tz` (1).

Version-pin baseline failures (same 4 node IDs on base `40fe603f`):

- `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
- `tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

The B1 e2e proves 5 sections, 3+2 / 2+2+1 / 1, person rows, detail/provenance,
pause/resume, reduced-motion, empty/503, and the F03 cross-scope regression.

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: version `2.58.224`, `deployed_sha=57e123db7…`
  (content/bump tip), previous `40fe603f…` / `2.58.223`,
  `release_branch=release/mod-acl-m4b1-2.58.224`, `dirty_tracked=false`, exit 0.
  `.deploy` was reconstructed locally (git-ignored) and removed; production files
  were not read.
- `rollback.json`: rollback/base `40fe603f`, 2.58.223, schema 48/DDL 0, no
  migration, no data/settings action; rollback command and manifest/restart checks.
- `postdeploy-runbook-2.58.224.md`: health/version/schema/identity/journal/
  settings/disk checks plus the B1 live matrix (5 ribbons, 3+2/2+2+1/1,
  person dossier, detail/provenance, empty/503, cross-scope S15-03) and
  Browser Use desktop/390.

## 6. Residual / limitations

- No production access, SSH, deploy, live TMA or VERIFIED claim in this assembly.
- `MAC-S6-307`/`MAC-S15-03` remain not VERIFIED until the deployed-byte live run;
  natural 503/empty chat is RFL.
- w10/w15 full tools retain pre-existing non-B1 failures (module catalog, cog-map,
  adaptive prompt editor); B1-specific checks pass. w15 candidate 72 vs base 73;
  candidate subset has no dossier/record failure.
- `MAC-S15-04` full resilience remains B3; `MAC-S0-11` remains partial until B2.
- `tools/ui_cmv_perf_parity.py` visual diff is not part of this assembly (N09);
  the B1 grid change intentionally invalidates the old baseline — release-lane decision.
