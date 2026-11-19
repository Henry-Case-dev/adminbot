# Release 2.58.220 — TIME-03 natural memory

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-20 (+12:00)
**Branch:** `release/time03-natural-2.58.220`
**Base / rollback:** `0fce97a14338521a24d94f560e896ebcb19f9492` (2.58.219, content `f80cba08ff6c444395753e77885ea2e37e2f308f`, schema 48, DDL 0)
**Approved candidate:** `da7908982d0b36ff677f57f17c631ebf2585a870` (`vmq/time03-r5`)
**Merge:** `44bb28539d751d0a2e2942782c94c472670720bc` (parents `0fce97a14` + `da7908982`, `--no-ff`, no conflicts)
**Bump/content tip:** `8e05e9a4d7ae7dafba6ab4efca405149264d5ba5`
**Version:** 2.58.220
**Schema/DDL:** 48 / 0
**Decision:** `plans/features/vmq-onto-01/evidence/mem07/time03-final-release-decision.md` (sha256 `981bfa38…`, commit `099c41734`, **RELEASE_WITH_BACKLOG**, release_blocker false, verified false)
**Review:** `plans/features/vmq-onto-01/evidence/mem07/time03-r5-review-r1.md` (sha256 `2dbb8680…`, `APPROVED_FOR_MINIMAL_REAL_PROBE`)
**Probe/harness:** `1acc82270` / `0eb027f65846386412f292e9eba922da80ce0f09`

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Release worktree from deployed `0fce97a14` | branch created; tracked tree clean |
| 2 | `git merge --no-ff da7908982` | `44bb28539`; `ort` strategy, 0 conflicts, 19 files |
| 3 | Bump `2.58.219 -> 2.58.220` + standard pins | `8e05e9a4d`; 30 files / 31 insertions / 31 deletions |
| 4 | Release evidence (this directory) | docs-only commit after content tip |

## 2. Product delta review

`git diff --name-status 0fce97a14..da7908982 -- services handlers web/api web/static config` returned exactly the expected TIME-03 product set (5 files, no unrelated):

- `services/database.py`
- `services/direct_chat_service.py`
- `services/mca_retrieval_context.py`
- `services/summary_memory.py`
- `services/turn_trace.py`

The full base→candidate diff also contains only TIME-03 tests/fixture (19 files total including the 5 product files); no handlers/web/config product changes on the candidate.

`git diff da7908982..8e05e9a4d -- services handlers web/api web/static` is empty; the only candidate→release config delta is `config/settings.py` (version/changelog). `git diff --shortstat 0fce97a14..8e05e9a4d` = **49 files, +2859 / −358**.

Product hashes at the content tip:

| File | Blob | sha256 |
|---|---|---|
| `services/database.py` | `dc736070a9c17d2a25d88d2ffd90bdd40bf44915` | `cac5f1ff89c638a9b8c8ccf47880ca5b0a65b650e18d59ba9e5fdca25c2044ab` |
| `services/direct_chat_service.py` | `b6e3d9dbbdb3c95326ecee1e9830f0d2f71709b7` | `ff3fbbdccd3dadd6eb10aaf5d6d96be154bf93ad3593fc741263e3ba8f736e02` |
| `services/mca_retrieval_context.py` | `3ddfe1fbd25dd320a85f864bdc0693b8c4a8a5b6` | `f17ed99f6dd027563b025aa4b8e8ef91088b01f55971ee4cb5a7032550590871` |
| `services/summary_memory.py` | `03722fbd30a5f848cf65bd07cc0b471565cd93a6` | `70313b94872c29c30e3c18a4c10c992094e52c9c15101892109c008561532f36` |
| `services/turn_trace.py` | `72733671a7ef2437d8e3271d583ccc9e2c2c4791` | `fce183912102a6788b7bdc26cc8cff78e2da980e2d281c5cb4d8a608e979d9ff` |

## 3. Bump and invariants

- `APP_VERSION = "2.58.220"` with TIME-03 changelog and `Prior 2.58.219`.
- Standard pins: `plans/docs/param-registry-round1025.meta.md`, 24 Python tests, 4 JS tests (escaped `2\.58\.220`). Exactly 30 files / 31 insertions / 31 deletions.
- `gen_param_registry_round1025.py --check`: OK, registry 648, map complete, TSV/map idempotent.
- No new flags/store/embedding/LLM; no `CREATE/ALTER/DROP` in the product diff; schema 48, DDL 0; apinet untouched.
- `git diff --check` and `git diff --check 0fce97a14..HEAD`: 0; `node --check` on four changed JS pins and `web/app.js`: 0.
- Temp SQLite: `APP_VERSION=2.58.220`, `user_version=48`, schema constant 48, `schema_migrations=48`.

## 4. Tests

Full machine-readable record: `tests-2.58.220.json`.

| Batch | Result |
|---|---|
| targeted r5 25 | **25 passed / 0 failed** (45 deselected) |
| affected 15 files | **366 passed / 0 failed** |
| mandatory 24 files | **386 tests / 0 failures / 0 errors / 0 skipped** |
| broad 40 files | **1141 tests / 0 failures / 0 errors / 0 skipped**, 6 pre-existing nodeids deselected |
| JS baseline comparison | candidate **119/4** vs base `0fce97a14` **119/4**, same four files, 0 regressions |
| mutation R4-F0 gate forced open | killed: `assert 13 == 3` |
| mutation S4 current gate closed | killed: required `{15172,18330,20419}` missing |

The six pre-existing broad nodeids are unchanged from r5 review: five `test_direct_fallback_recompose_asap32.py` nodes plus `test_direct_l1_corrective_r1.py::test_build_l1_context_bot_replies_caps_and_limit`; same causes fail on the base. They are not hidden or counted as pass.

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: version `2.58.220`, `deployed_sha=8e05e9a4d…`, previous `0fce97a14…`/`2.58.219`, `release_branch=release/time03-natural-2.58.220`, `dirty_tracked=false`, exit 0. The previous manifest was reconstructed locally (`.deploy` is git-ignored) and removed; production file was not read.
- `rollback.json`: target base/rollback `0fce97a14`, schema 48/DDL 0, no migration, no data action; rollback command and manifest/restart checks.
- `postdeploy-runbook-2.58.220.md`: health/version/schema/identity/journal/settings/chat-scope/disk checks and rollback path; a targeted real S2/S3/S4 probe is **not required** by `RELEASE_WITH_BACKLOG`, but the residual is recorded.

## 6. Residual / limitations

- S2/S3 real probe remains `not_executed/reference_unreachable` (`row:1653613`, `row:53`); not a pass.
- S4 current/stale safety passed; S4 2026 episode, S1 3-year edge, S5 fact anchors, S6 second 2022 anchor and vector semantics remain backlog.
- Broad suite is the 40-file sampled set, not the full 21k suite.
- No production access, SSH, deploy, live turn or VERIFIED claim in this assembly. `2.58.220` is prepared only.
