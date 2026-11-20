# Release 2.58.225 — MOD-ACL-UX-01 M4B B2: observer KPI/decisions + compact last call

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-21 (+12:00)
**Branch:** `release/mod-acl-m4b2-2.58.225`
**Base / rollback:** `275a1b7cd320f67e0ac089d8d5c4b14ca31dbcfa` (2.58.224, schema 48, DDL 0)
**Approved candidate:** product `db92c73ce122ee09a461696ba4d0a8c69b07cbb6`, branch tip `09ef444d83eb6b3e6b1fcb89928c99c629c0a415`
**Reviewer B2 r1:** `review-r1.md`, sha256 `e8b957b8c625ab179cdd356e7fdd6b3911a292e90b2707d13a22508b5f6ca8ff`, verdict `APPROVED_FOR_RELEASE_PREPARATION`; required-before-release NB-1 fixed in evidence
**NB evidence fix:** `bebe11e327cbbb58539e169fef72faee8928c378` (docs only)
**Bump / content tip:** `75b92f31d17c11ff111708b19564cb9fef978f8f`
**Version:** 2.58.225
**Schema/DDL:** 48 / 0

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Branch based on `275a1b7c` | `release/mod-acl-m4b2-2.58.225`; product `db92c73ce`, reviewed tip `09ef444d8` |
| 2 | NB-1/NB-2 evidence corrections | `bebe11e32`; 42 insertions / 8 deletions in `tests.json` + `implementation.md` only |
| 3 | Standard bump `2.58.224 -> 2.58.225` | `75b92f31d`; **30 files / 31 insertions / 31 deletions** |
| 4 | Product delta checks | product scope empty since `09ef444d8`; tests diff is 29/29 version-pin lines only |
| 5 | Tests on bumped tip | mandatory 386; node 6/6; D1/D3 94; broad 127/124/3; pins 856/4 + 4/0; B1 e2e 138/0; B2 e2e 92/0; W3 OK; W10 3 pre-existing; W15 73/72 with 0 status-related |
| 6 | Schema smoke | target 48, user_version 48, schema_migrations max/count 48, DDL 0 |
| 7 | Manifest dry-run at content tip | `manifest-dry-run.json`; exit 0; version 2.58.225; previous `275a1b7c` / 2.58.224; dirty false |
| 8 | Release evidence (this directory) | docs-only commit after content tip |

No merge commit: the branch is based directly on `275a1b7c` and contains the
reviewed product/tests, the NB evidence fix and the standard bump. The bump
does not touch `web/`: `git diff 09ef444d8..75b92f31d -- web` is empty.

## 2. Product delta review

| File | Net base→bump |
|---|---|
| `web/app.js` | **262 / 78** |
| `web/index.html` | **249 / 107** |
| `web/static/app.css` | **32 / 15** |
| `web/api/analytics.py` | **39 / 1** |
| `web/api/memory_overview.py` | **38 / 0** |
| `config/settings.py` | 1 / 1 (APP_VERSION/changelog) |

- `git diff 09ef444d8..75b92f31d -- web services handlers web/api database.py migrations prompts tools` = **empty**
  (product/backend unchanged since the approved candidate).
- `git diff 09ef444d8..75b92f31d -- tests` = 29 removed / 29 added lines; every pair differs
  solely by `2.58.224 -> 2.58.225` (24 Python pins, 4 escaped JS pins, polygon file has two lines).
  So the literal `web tests tools` range contains only the mandatory version-pin rewrites;
  no test logic, assertion or fixture changed.
- `git diff 275a1b7c..75b92f31d -- services handlers database.py migrations prompts` = **empty**
  (no backend/DDL/flags/prompts/storage).
- Feature: observer without a pseudo-funnel — 6 independent KPIs with window/scope/snapshot,
  top-5 clickable reasons, decisions + full ledger, D3 two-entity explain, mock/real check;
  compact last call `ok|empty|unavailable` with latency/error/finish, honest price and
  image-only; D1/D3 add read-only nullable fields only.

## 3. Bump and invariants

- `APP_VERSION = "2.58.225"` with the M4B B2 changelog entry and `Prior 2.58.224`.
- Standard pins: `plans/docs/param-registry-round1025.meta.md`, 24 Python tests,
  4 JS tests (escaped `2\.58\.225`). Exactly **30 files / 31 insertions / 31 deletions**.
- BOM/CRLF preserved byte-level: 0 mismatches across all 30 files; `settings.py` keeps
  UTF-8 BOM + 3645 CRLF.
- `git diff --check -- web tests tools` rc=0; `node --check web/app.js` rc=0,
  `py_compile` green. The full-range diff still contains evidence trailing whitespace
  (NB-1) — docs-only, not a product change.
- Temp SQLite schema smoke: target 48, `user_version=48`, `schema_migrations`
  max/count 48, journal `wal`, DDL delta 0.

## 4. Tests

Machine-readable record: `tests-2.58.225.json`; outputs under `test-output/`.

| Batch | Result |
|---|---|
| Mandatory 24-file pytest | **386 passed, 0 failed** |
| Targeted node B2 + W3/W5/F6/B1 | **6/6 rc=0** |
| Python D1/D3 + regression | **94 passed, 0 failed** (NB-1 recount) |
| Broad JS `tests/js/*_test.js` | **127 files, 124 passed, 3 failed** — `evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings` (baseline) |
| Version pins 24 Python | **856 passed / 4 failed** — same 4 pre-existing pin-guard node IDs as 2.58.224 |
| Version pins 4 JS | **4/4 rc=0** |
| B1 Playwright e2e | **138 checks, 0 failures** |
| B2 Playwright e2e | **92 checks, 0 failures**; 1920/1440/1280/768/390/320 |
| W3 status e2e | **W3-STATUS-E2E-OK**; observer_kpis, no funnel, observed 420, liveness, domains explain, entities; console_errors=[] |
| W10 sections e2e | **3 pre-existing** module catalog/scoped-toggle failures |
| W15 composition e2e | **0 status/observer-related**; 73 and 72 failures in two runs, Reviewer independent recount 71 — pre-existing cog-map/adaptive/prompt-editor only, environment-dependent |
| Schema smoke | **48 / 48 / 48**, DDL 0 |

The W3 tool rewrote four tracked `w3-evidence-status` PNGs during the run; they were
restored to HEAD immediately and are not part of this assembly.

Base pre-existing failures (not counted as pass): 3 broad-JS files, 4 Python pin guards,
3 W10 checks and the W15 full-tool set. `tools/ui_cmv_perf_parity.py` was not run.

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: version `2.58.225`, `deployed_sha=75b92f31d…`
  (content/bump tip), previous `275a1b7c…` / 2.58.224,
  `release_branch=release/mod-acl-m4b2-2.58.225`, `dirty_tracked=false`, exit 0.
  `.deploy` was reconstructed locally (git-ignored) and removed; production files
  were not read.
- `rollback.json`: rollback/base `275a1b7c`, 2.58.224, schema 48/DDL 0, no
  migration, no data/settings action; rollback command and manifest/restart checks.
- `postdeploy-runbook-2.58.225.md`: health/version/schema/identity/journal/
  settings/disk checks plus the B2 live matrix (6 KPIs, no funnel, reasons,
  decisions/ledger, D3 explain, mock/real check, last-call ok/empty/503/image-only,
  scope isolation) and Browser Use desktop/390.

## 6. Evidence corrections and residual

- **NB-1 (fixed):** D1/D3 counter `110 -> 94`; `git diff --check` scoped to
  `-- web tests tools`, full-range evidence whitespace documented.
- **NB-2 (fixed):** W15 candidate count `72 -> 71` with an environment-dependent note.
- **NB-3, NB-4, NB-5, NB-6, BL-1:** nonblocking follow-ups/B3, **not fixed** in this
  candidate or assembly.
- No production access, SSH, deploy, live TMA or VERIFIED claim in this assembly.
- `MAC-S6-345`/`MAC-AC-15` remain partial (no full trace page); `MAC-S6-346`
  image-only is a deterministic stub until a natural event (RFL).
- w10/w15 full tools retain pre-existing non-B2 failures; w15 count varies 71-73
  across stands, with zero status/observer-related failures.
