# Release 2.58.221 — MOD-ACL-UX-01 M4A W2c

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-20 (+12:00)
**Branch:** `release/mod-acl-w2c-2.58.221`
**Base / rollback:** `d03027b1bc3811a0614c5a2e38342eb9e77c4ea5` (2.58.220, content `8e05e9a4d7ae7dafba6ab4efca405149264d5ba5`, schema 48, DDL 0)
**Approved candidate:** `67ef30cd120163132a2f2e894a0fe474bba9623d` (branch `release/mod-acl-w2c-2.58.221`)
**Merge:** `c16c3566d4cb6d0cbd68c1f58eb4527380e49daf` (parents `d03027b1` + `67ef30cd`, `--no-ff`, no conflicts)
**Bump/content tip:** `1c75a1d8a2b1f573c44deabab4d38bfcbc20ddbe` (content tree `2c80f26fc2a8fb7a9242b5355810eda09bd05f40`)
**Version:** 2.58.221
**Schema/DDL:** 48 / 0
**Review input:** `review-r2.md` (re-review input only; no independent APPROVED verdict recorded)

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Release branch from deployed `d03027b1` | `assemble/mod-acl-w2c-2.58.221` created at base; tracked tree clean |
| 2 | `git merge --no-ff 67ef30cd` | `c16c3566d`; 0 conflicts; merge tree identical to candidate (`git diff 67ef30cd..c16c3566d` empty) |
| 3 | Bump `2.58.220 -> 2.58.221` + standard pins | `1c75a1d8`; 30 files / 31 insertions / 31 deletions |
| 4 | Release evidence (this directory) | docs-only commit after content tip |

The candidate/release ref is the same branch name in this line; the assembly merge is
explicit (`--no-ff`) from the deployed base, so the release branch contains the
approved candidate as the second parent without rewriting history.

## 2. Product delta review

`git diff --name-status d03027b1..67ef30cd -- services handlers web/api config` is
**empty** (no backend/API/config delta). `git diff --name-status d03027b1..67ef30cd -- web`
is exactly the expected three product files:

- `web/app.js`
- `web/index.html`
- `web/static/app.css`

The candidate has **no version bump**: `git diff d03027b1..67ef30cd -- config` is empty and
`APP_VERSION` remains `2.58.220` on `67ef30cd`. The release content adds only
`config/settings.py` (2.58.221 + W2c changelog), the registry meta, 24 Python pins and
4 JS escaped pins.

Note on the literal pathspec: a check that includes `web/static` will see
`web/static/app.css` — that file is one of the three intentional W2c product files,
not an unrelated change. The backend/API set (`services handlers web/api config`) is empty.

Other checks:

- `git diff --shortstat d03027b1..67ef30cd` = `28 files changed, 7562 insertions(+), 11 deletions(-)`.
- `git diff --shortstat d03027b1..1c75a1d8` = `58 files changed, 7593 insertions(+), 42 deletions(-)`.
- `git diff --shortstat c16c3566d..1c75a1d8` = `30 files changed, 31 insertions(+), 31 deletions(-)`.
- No backend/API/DDL/flags/prompts/storage delta; no new tables, routes, stores, models or schedulers.

## 3. Bump and invariants

- `APP_VERSION = "2.58.221"` with W2c changelog and `Prior 2.58.220`.
- Standard pins: `plans/docs/param-registry-round1025.meta.md`, 24 Python tests, 4 JS tests (escaped `2\.58\.221`). Exactly 30 files / 31 insertions / 31 deletions.
- `gen_param_registry_round1025.py --check`: exit 0; registry 648, map complete, R17-clean, TSV/map idempotent.
- Temp SQLite schema smoke: `user_version=48`, schema constant 48, `schema_migrations=48`; DDL delta 0.
- `git diff --check` and `git diff --check d03027b1..HEAD`: 0.
- No `CREATE/ALTER/DROP` in the product delta; no backend product files changed.

## 4. Tests

Full machine-readable record: `tests-2.58.221.json`; raw command outputs under `test-output/`.

| Batch | Result |
|---|---|
| Node W2c 7 files | **0 fail** — M3 235, M4 catalog 207, module params 64, review fixes 75, W2a 141, W2b 356, W2c 83 |
| JS version pins 4 | **0 fail** |
| W2c Playwright | **6 viewports (1680/1440/1280/768/390/320), 0 failures**; catalog chips 44 at 768/390/320; card heights 132/146/162; split 1024/1152/1199 one column, 1200/1680 8/4; no overflow |
| M4A catalog e2e | **`M4A-CATALOG-E2E OK | failures=0`** |
| Affected Python 13 files | **218 passed / 6 failed**; same 6 on base `d03027b1` (baseline-identical) |
| Standard version-pins 24 files | **856 passed / 4 failed**; same 4 on base `d03027b1` (stale tool canon/forbidden-path tests) |
| Broad JS | candidate **124 / 4 fail**; base **123 / 4 fail**, same four files; **0 regressions** |
| Mutations | F1 killed (TypeError in both tests); F2 killed (3 viewports, chip 16); F3 killed (12 failure lines at 1024/1152/1199) |

The 6 affected-Python and 4 standard-pin failures are not hidden and are not counted as
pass; they reproduce on the base and are outside W2c. The broad JS failures are the same
four stale files on base and candidate.

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: version `2.58.221`, `deployed_sha=1c75a1d8…`, previous
  `d03027b1…` / `2.58.220`, `release_branch=release/mod-acl-w2c-2.58.221`,
  `dirty_tracked=false`, exit 0. The previous manifest was reconstructed locally
  (`.deploy` is git-ignored) and removed; production file was not read.
- `rollback.json`: target base/rollback `d03027b1`, schema 48/DDL 0, no migration,
  no data/settings action; rollback command and manifest/restart checks.
- `postdeploy-runbook-2.58.221.md`: health/version/schema/identity/journal/settings/disk
  checks and W2c NAV/LAY/WF Playwright + Browser Use checks; **no S2/S3 TIME-03 probe**
  (this release has no TIME-03 product delta).

## 6. Residual / limitations

- No production access, SSH, deploy, live TMA or VERIFIED claim in this assembly.
- Independent W2c re-review verdict is not recorded; `review-r2.md` is input only.
- Affected Python has 6 baseline-identical failures; standard 24-pin batch has 4
  baseline-identical failures; broad JS has 4 baseline-identical failures.
- The cognition-map visual parity tool is nondeterministic; W2c used targeted surface
  parity, measured proportions and Playwright/Browser Use screenshots.
- Postdeploy observation remains a runbook step for the deploy lane; it is not owner QA.
