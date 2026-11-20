# Release 2.58.223 — W3/F-1: 503 `unavailable` vs disabled `off`

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-20 (+12:00)
**Branch:** `release/mod-acl-w3-503-2.58.223`
**Base / rollback:** `26b8880c64283457434fdbec58f65e0dd3eafd25` (2.58.222, schema 48, DDL 0)
**Approved candidate:** `afe9beb2478fb19f435319cb07e0aa3264b2bb87` (`fix/mod-acl-w3-503`; product `0a8571acc9f3bfff3fcf5f6f8ce8b53a0c2ff8c8`)
**Reviewer addendum:** `plans/features/mod-acl-ux-01/evidence/m4a/w3-503-fix/review-r1-hash-addendum.md`, sha256 `7e7751f1134cd93fbc1a2f88b563ca56efc2a326b84ba069cdb9a92262ef278d`, verdict `APPROVED_FOR_RELEASE_PREPARATION`
**Merge:** `6057bd5bbc791c78ae8102c3d143ea4de1c7a186` (`--no-ff`, parents `26b8880c` + `afe9beb24`, 0 conflicts)
**Bump / content tip:** `9138f2ee821aceb897cd69d3a768d5969852751c`
**Version:** 2.58.223
**Schema/DDL:** 48 / 0

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Release branch from `26b8880c` | `release/mod-acl-w3-503-2.58.223`; tracked tree clean |
| 2 | `git merge --no-ff afe9beb24` | `6057bd5bb`; 0 conflicts; `git diff afe9beb24..6057bd5bb` empty |
| 3 | Bump `2.58.222 -> 2.58.223` + standard pins | `9138f2ee8`; 30 files / 31 insertions / 31 deletions |
| 4 | Tests on bumped tip | all required sets; see §4 |
| 5 | Manifest dry-run at content tip | `manifest-dry-run.json`; exit 0 |
| 6 | Release evidence (this directory) | docs-only commit after content tip |

## 2. Product delta review

- `git diff --numstat 26b8880c..9138f2ee8 -- web/app.js web/index.html` = `16 7 web/app.js`, `14 3 web/index.html` — exactly the approved W3/F-1 product.
- `git diff --name-only 26b8880c..9138f2ee8 -- web` = only `web/app.js`, `web/index.html`.
- `git diff 0a8571acc..afe9beb24 -- web tests tools` is **empty** (candidate tip is docs-only).
- `git diff 6057bd5bb..9138f2ee8 -- web` is **empty** (the bump did not touch `web/`).
- `git diff --name-only 26b8880c..9138f2ee8 -- services handlers web/api database.py migrations` is **empty**.
- `git diff --name-only 26b8880c..9138f2ee8 -- config` = only `config/settings.py` (APP_VERSION/changelog).
- No backend/API/DDL/flags/prompts/storage delta; no new tables, routes, stores, models or schedulers.

## 3. Bump and invariants

- `APP_VERSION = "2.58.223"` with a W3/F-1 changelog entry and `Prior 2.58.222`.
- Standard pins: `plans/docs/param-registry-round1025.meta.md`, 24 Python tests, 4 JS tests (escaped `2\.58\.223`). Exactly **30 files / 31 insertions / 31 deletions**.
- BOM/CRLF preserved: byte-level replacements; 0 BOM/line-ending mismatches across the 30 files (settings.py keeps its UTF-8 BOM; all CRLF counts unchanged).
- Temp SQLite schema smoke: `_SCHEMA_VERSION_RANDOM_BATCH_PROVENANCE=48`, `user_version=48`, `schema_migrations` max/count 48; DDL delta 0.
- `node --check web/app.js` rc=0; `git diff --check 26b8880c..9138f2ee8` rc=0.

## 4. Tests

Machine-readable record: `tests-2.58.223.json`; outputs under `test-output/`.

| Batch | Result |
|---|---|
| Node history (W2b) | **397 проверок**, rc=0 |
| 7 mod-acl node files | **235 / 141 / 397 / 84 / 207 / 64 / 75**, all rc=0 |
| Pytest 5 files (catalog, m3 routes, module params, m1 ACL, webapp JS unit) | **83 passed** |
| Mandatory pytest set (24 files: M4A/M2/M2.1 + f8 + mca23 + webapp JS unit) | **386 passed, 0 failed** |
| Version pins (24 Python files) | **856 passed, 4 failed** — exact baseline node IDs below; base `26b8880c` fails the same 4 |
| 4 JS version pins | **4 passed**, rc=0 |
| Broad JS sweep (`tests/js/**/*_test.js`, 124 files) | **120 passed, 4 failed** — `asap6_wave2_ux_tabs`, `evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings` (same baseline) |
| M4A catalog e2e | **`M4A-CATALOG-E2E OK | failures=0`** |
| Schema smoke | **48 / 48 / 48**, DDL 0 |

Baseline pin failures (reproduced on base `26b8880c`, same node IDs):

- `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
- `tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
- `tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
- `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`

The e2e matrix proves the MAC-S10-16 causes are distinct: `empty` / `denied` / `unavailable` / `off` / stale 409 banner, with texts `Записей пока нет.`, `…(403)`, `…временно недоступен (503)…`, `…функция выключена.`, `Настройка изменилась в другом окне`. A 503 deep link stays on the history panel with `panelState=unavailable` and a retry control.

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: version `2.58.223`, `deployed_sha=9138f2ee8…` (content/bump tip), previous `26b8880c…` / `2.58.222`, `release_branch=release/mod-acl-w3-503-2.58.223`, `dirty_tracked=false`, exit 0. `.deploy` was reconstructed locally (git-ignored) and removed; production files were not read.
- Procedure note: the first prior-manifest write used a UTF-8 BOM and the script honestly returned `previous_* = null`; it was redone with a BOM-less JSON and the recorded manifest has the correct previous fields.
- `rollback.json`: target base/rollback `26b8880c`, 2.58.222, schema 48/DDL 0, no migration, no data/settings action; rollback command and manifest/restart checks.
- `postdeploy-runbook-2.58.223.md`: health/version/schema/identity/journal/settings/disk checks plus the W3 live matrix (0/403/503/409/disabled), deep-link 503 behaviour and Browser Use desktop/390.

## 6. Reviewer addendum and hash wording

`review-r1-hash-addendum.md` (sha256 `7e7751f1…`) confirmed the candidate values and resolved `W3-F1-R1-EVID-01`. It corrected the wording: the deployed/checkout bytes are **LF** (`web/app.js`: CRLF 0 / LF 45504; `web/index.html`: CRLF 0 / LF 19278); the `(CRLF)` label at `implementation.md` line 46 is an erroneous note. The values `108f440f…` / `c3ceb1b5…` are correct and the candidate is unchanged (`afe9beb24`); the wording fix is non-blocking and is **not** applied to the candidate artifact.

## 7. Residual / limitations

- No production access, SSH, deploy, live TMA or VERIFIED claim in this assembly.
- `MAC-S10-16` remains not VERIFIED until a deployed-byte live run (real non-editor 403, induced 503/stale/disabled) and Browser Use; this is the W3 postdeploy condition, not owner QA.
- The local e2e is Playwright/Chromium on a synthetic API stub; it does not replace the live TMA matrix.
- F-2/F-3 from `mac-s10-16.md` (verbatim §7.3 copy, 404 screen) are out of this corrective scope.
- The four pin failures and the four broad-JS failures are pre-existing epic-scope guards, reproduced on `26b8880c`; they are not counted as pass and not caused by this release.
