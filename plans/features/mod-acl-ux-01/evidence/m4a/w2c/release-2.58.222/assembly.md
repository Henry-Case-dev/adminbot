# Release 2.58.222 — W2c + postdeploy card-height corrective

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-20 (+12:00)
**Branch:** `release/mod-acl-w2c-2.58.222`
**Base / rollback:** `d03027b1bc3811a0614c5a2e38342eb9e77c4ea5` (2.58.220, content `8e05e9a4d7ae7dafba6ab4efca405149264d5ba5`, schema 48, DDL 0)
**Approved fix:** `51bad063ff47750798b6419456862f83f7db3ca5` (`fix/mod-acl-w2c-card-height`; product fix `80955000806a0f5fc5a855e72a19b1ce1d039dc5`, candidate `67ef30cd`)
**Card-height review:** `dc552b009`, artifact sha256 `96438228d80369bd2bd132d1e1abf73eca7c9d9e2fb858be16c5ca7c48a3b1fc`, verdict `APPROVED_FOR_RELEASE_PREPARATION`
**Merge:** `a959bb61f582a3005dccf7ac61f7385b1f57c701` (parents `d03027b1` + `51bad063`, `--no-ff`, no conflicts)
**Bump/content tip:** `03abd668d76befe8bc36c47c41a8e8666d47e107` (content tree `e7681a80b3fe83f75a25577c0d755ad82c51a8cd`)
**Version:** 2.58.222
**Schema/DDL:** 48 / 0

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Release branch from deployed `d03027b1` | `release/mod-acl-w2c-2.58.222` created at base; tracked tree clean |
| 2 | `git merge --no-ff 51bad063` | `a959bb61f`; 0 conflicts; merge tree identical to fix (`git diff 51bad063..a959bb61f` empty) |
| 3 | Bump `2.58.220 -> 2.58.222` + standard pins | `03abd668d`; 30 files / 31 insertions / 31 deletions |
| 4 | Release evidence (this directory) | docs-only commit after content tip |

2.58.221 was deployed and rolled back: W2c Playwright failed 3 and M4A e2e 11 on card height 162/180 vs 132–164; production is back on 2.58.220. This release merges the reviewed one-line title clamp and re-cuts as 2.58.222.

## 2. Product delta review

`git diff --name-status d03027b1..51bad063 -- services handlers web/api config` is **empty**.
`git diff --name-status d03027b1..51bad063 -- web` is exactly the expected three product files:

- `web/app.js` (approved W2c candidate)
- `web/index.html` (approved W2c + `:title` on card title)
- `web/static/app.css` (approved W2c + one-line title clamp)

The card-height fix itself is only `web/static/app.css` +6/−1 and `web/index.html` +1/−1; `web/app.js` is untouched by the fix. No `plans/features/evol` evidence and no unrelated product files are in the release diff.

Other checks:

- `git diff --shortstat d03027b1..51bad063` = `41 files changed, 13489 insertions(+), 13 deletions(-)`.
- `git diff --shortstat d03027b1..03abd668d` = `71 files changed, 13520 insertions(+), 44 deletions(-)` (includes candidate tests/evidence and the card-height fix evidence).
- `git diff --shortstat a959bb61f..03abd668d` = `30 files changed, 31 insertions(+), 31 deletions(-)`.
- No backend/API/DDL/flags/prompts/storage delta; no new tables, routes, stores, models or schedulers.

## 3. Bump and invariants

- `APP_VERSION = "2.58.222"` with W2c + card-height changelog and `Prior 2.58.220`.
- Standard pins: `plans/docs/param-registry-round1025.meta.md`, 24 Python tests, 4 JS tests (escaped `2\.58\.222`). Exactly 30 files / 31 insertions / 31 deletions.
- Temp SQLite schema smoke: `user_version=48`, schema constant 48, `schema_migrations=48`; DDL delta 0.
- `git diff --check` and `git diff --check d03027b1..HEAD`: 0.
- Direct version-pin files: 5 files **132 passed / 0 failed**; 4 JS pins **0 failed**.

## 4. Tests

Full machine-readable record: `tests-2.58.222.json`; outputs under `test-output/`.

| Batch | Result |
|---|---|
| Card-height long content (4 media cards, chat scope) | **3 viewports (1680/1440/320), 0 failures**; 162.06 / titleH 18 for transcribe, video_summary, media_download, images; red before fix 179.56 / titleH 35 |
| W2c Playwright | **6 viewports (1680/1440/1280/768/390/320), 0 failures**; all 21 cards 162 at desktop, 132/146/162 at mobile; chips 16/44; split 1024/1152/1199 one column, 1200/1680 8/4; overflow 0 |
| M4A catalog e2e | **`M4A-CATALOG-E2E OK | failures=0`** |
| Node W2c 7 files | **0 fail** — M3 235, M4 catalog 207, params 64, review 75, W2a 141, W2b 356, W2c **84** |
| Affected Python | approved review **304 passed / 6 failed**; local expanded set **305 passed / 6 failed**, same six stale failures (one-test collection difference); 13-file subset 218/6, same six |
| Mutation title clamp removed | **KILLED**: 24 failures, 179.56 / titleH 35 at 1680/1440/320 |

The six affected-Python failures are the same baseline nodeids on `d03027b1`:
`test_webapp_nav_disclosure_ui` (2), `test_webapp_round1020_ui` (3), `test_webapp_f5_round1025` (1).
They are not hidden or counted as pass.

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: version `2.58.222`, `deployed_sha=03abd668d…`, previous `d03027b1…` / `2.58.220`, `release_branch=release/mod-acl-w2c-2.58.222`, `dirty_tracked=false`, exit 0. The previous manifest was reconstructed locally (`.deploy` git-ignored) and removed; production file was not read.
- `rollback.json`: target base/rollback `d03027b1`, schema 48/DDL 0, no migration, no data/settings action; rollback command and manifest/restart checks.
- `postdeploy-runbook-2.58.222.md`: health/version/schema/identity/journal/settings/disk checks plus W2c/M4A and Browser Use on the **media row** (162.06 target), titles ellipsis/full `:title`; **no S2/S3 TIME-03 probe**.

## 6. Residual / limitations

- No production access, SSH, deploy, live TMA or VERIFIED claim in this assembly.
- Card-height review nonblocking findings EVID-1/TEST-1/EVID-2/UX-1 remain backlog; the review is APPROVED_FOR_RELEASE_PREPARATION, not an independent 2.58.222 release verdict.
- Affected Python approved baseline 304/6; local expanded set 305/6 with the same six failures.
- Full 24-file version-pin Python batch was not completed; 5 direct pin files 132/0 and all 4 JS pins passed.
- Postdeploy observation remains a runbook step for the deploy lane; it is not owner QA.
