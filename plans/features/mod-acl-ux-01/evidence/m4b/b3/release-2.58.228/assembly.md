# Release 2.58.228 — MOD-ACL-UX-01 M4B B3 (compact memory / live experience feed / honest lessons)

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-21 (+12:00)
**Branch:** `release/mod-acl-m4b3-2.58.228`
**Base / rollback:** `c8cf54c1ad92e8039928c531efe70efe141704bd` (2.58.227, schema 48, DDL 0)
**Reviewed candidate:** `237bf6103d03cb603ca6e02b634c374431ef8654` (`feat/mod-acl-m4b3`, base `1cc019ad5`, 2.58.226)
**Review:** `review-r1.md` (master `d5b5cfa78`, verdict `NEEDS_FIXES`, blocker B3-R1-01) + `review-r1-addendum.md` (master `8e719c2ca`, verdict `APPROVED_FOR_RELEASE_PREPARATION`, B3-R1-01 resolved, EB-1 closed)
**Bump / content tip:** `ff8a596367dc2e576e7034b980f27cddfcbb4014`
**Version:** 2.58.228
**Schema/DDL:** 48 / 0

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Worktree/branch from `c8cf54c1a` | `release/mod-acl-m4b3-2.58.228` via `workflow_housekeeping.py worktree-path` + `git worktree add -b` + `register-worktree` |
| 2 | Cherry-pick `35f4fd882^..237bf6103` (5 commits) | `1728b832b` (c1), `29636846e` (c2), `62b8a6a05` (c3), `1b92b5823` (nested-scroll guard), `579b2c5cd` (c4 B3-R1-01); **0 conflicts**, 0 merge commits, no force |
| 3 | Product identity | `git diff 237bf6103..ff8a59636 -- web` = **empty**; served sha256 `app.js 37fd2f0c…`, `index.html d3e3d2b0…`, `app.css b6675a10…` — byte-identical to the reviewed c4 candidate |
| 4 | Standard bump 2.58.227 → 2.58.228 | `ff8a59636`; **32 files / 35 insertions / 35 deletions** (see §3) |
| 5 | Tests on bumped tip `ff8a59636` | node 12/12; focused pytest 65/0; JS pins 6/6; pin-guard 856/4 (same 4 on base); broad sweep 3033/40 (5/40 reproduced on base); B1 138/0; B2 92/0; B3 131/131; node --check + py_compile rc=0 |
| 6 | Manifest dry-run at content tip | `manifest-dry-run.json`; exit 0; version 2.58.228; previous `c8cf54c1a` / 2.58.227; `dirty_tracked=false`; `.deploy` removed |
| 7 | Release evidence (this directory) | docs-only commit after `ff8a59636` |

No merge commit: the branch is based directly on `c8cf54c1a` and contains only the
five reviewed B3 commits, the standard bump and this docs-only evidence.
`git diff 237bf6103..ff8a59636 -- web` and `-- services handlers database.py
migrations prompts` are empty; the only backend-adjacent file is
`web/api/memory_overview.py` (additive read-only D6 fields reviewed with the candidate).

## 2. Product delta review

| File | Net base→bump |
|---|---|
| `web/app.js` | **683 / 36** |
| `web/index.html` | **234 / 31** |
| `web/static/app.css` | **82 / 0** |
| `web/api/memory_overview.py` | **56 / 0** (additive `facts_*` in the existing read-only GET `/api/memory/expired-overview`; `_require_global_admin` kept, `chat_id` bound as a parameter) |
| `tools/ui_mod_acl_m4b3_status_e2e.py` | **1057 / 0** (new B3 e2e) |
| `config/settings.py` | 1 / 1 (APP_VERSION/changelog) |
| `plans/docs/param-registry-round1025.meta.md` | 1 / 1 (APP_VERSION stamp) |
| tests | 35 files, **1161 / 41** |

Totals at the bump tip: **43 files, 3278 insertions / 113 deletions**.

- B3 content (12 files) is exactly **3244 / 79**, the reviewed candidate delta:
  4 web files, 7 test files, 1 tool; 0 unexpected product files.
- Bump is 34 / 34 across 31 files plus 1 / 1 inside `tools/ui_mod_acl_m4b3_status_e2e.py`
  (a live pin, see §3) = **35 / 35**.
- `git diff c8cf54c1a..HEAD -- services config handlers database.py migrations prompts web/api/memory_agi.py`
  = only `config/settings.py` (version bump).
- DDL check over the full range (`CREATE/ALTER/DROP TABLE|INDEX`, `ENABLE_`,
  `add_argument`) = **empty**; no new flags, routes, migrations, prompts or storage.
- `git diff 237bf6103..HEAD -- tests` = 29 files: 28 version-pin files
  (24 Python + 4 escaped JS, 29 pin lines) and `tests/test_lvs_l1_discovery_partial.py`
  (+243), which is 2.58.227 content already present on the base and absent from
  the B3 branch by construction. No test logic changed by the bump.
- APP_VERSION parsed by AST: **`2.58.228`**; no merge commits in `c8cf54c1a..HEAD`.

## 3. Bump and invariants

- `APP_VERSION = "2.58.228"` with a full M4B B3 changelog entry and
  `Prior 2.58.227`; base noted as `c8cf54c1a (2.58.227)`.
- Live pins swept: 28 plain-text files + 4 escaped JS pins
  (`round1025_hotfix7/8/9/10`) = **32 pin files**, plus the B3 e2e tool
  `PROD_VERSION = "2.58.226" → "2.58.228"` (the tool was created on the B3 branch
  after the 2.58.227 wave, so it still carried the stale branch-birth pin).
  This is why the wave is 32 files / 35 lines instead of the 31 / 34 of the
  226→227 reference: one extra live pin.
- BOM/CRLF preserved byte-level: `config/settings.py` keeps UTF-8 BOM and
  3645 CRLF + 1 bare final LF, unchanged from base; no line-ending or BOM
  change in any bumped file.
- `git diff --check` rc=0; `node --check web/app.js` rc=0; `py_compile` of
  `config/settings.py`, `web/api/memory_overview.py`, the B3 e2e tool and the
  B3 pytest files rc=0.
- `git grep -n "2\.58\.227"` after the bump: only `config/settings.py`
  (base/`Prior` history inside the changelog line) and previous-release evidence
  directories. No live pin remains at 2.58.227.
- No production, SSH, DB, LLM, settings or chat-override writes; no deploy.

## 4. Tests

Machine-readable record: `tests-2.58.228.json`; raw outputs under `test-output/`.

| Batch | Result |
|---|---|
| Node (12 files, including new `m4b3_experience_feed_test.js`) | **12/12 exit 0** |
| Focused pytest (6 B3-adjacent files) | **65 passed, 1 warning** |
| JS pins (4 hotfix version pins + 2 B3 JS suites) | **6/6 exit 0** |
| Pin-guard 24 Python files on bumped tip | **856 passed / 4 failed** |
| Pin-guard same 24 files on base `c8cf54c1a` | **856 / 4**, identical node IDs |
| Broad web/memory sweep, 135 files | **3033 passed / 40 failed** |
| Same 40 on base | 5 selected failures reproduced identically on `c8cf54c1a`; full 40 listed in `test-output/sweep-tip-failures.txt` |
| B1 status e2e (served bytes, 6 viewports) | **138 checks, 0 failures**, `M4B-STATUS-E2E-OK` |
| B2 status e2e | **92 checks, 0 failures**, `M4B-B2-STATUS-E2E-OK` |
| B3 status e2e | **131/131**, `M4B-B3-STATUS-E2E-OK`, 8 screenshots, console clean |
| Syntax | `node --check` rc=0; `py_compile` rc=0 |

The 4 pin-guard failures are the known pre-existing node IDs
(`test_tool_coordinator_round1026.py::TestBounds::{test_forbidden_paths_out_of_diff,
test_canon_twelve_tools}`, `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`,
`TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`) — reproduced on the
base, not counted as pass. The 40 sweep failures are pre-existing
(nav-snapshot/module-name/version-readme/jargon/W10-W15 catalog) and are not
caused by B3; 5 were re-run on `c8cf54c1a` with identical failures.

B3 served-byte identity in the e2e report: `app.js 37fd2f0c…`,
`index.html d3e3d2b0…`, `app.css b6675a10…` — the reviewed c4 hashes. Snapshot
`aa3c10f3…` is the deterministic **synthetic stub**; it differs from the
candidate-era `9573eeb7…` only because the stub status now reports version
2.58.228 (the fixture carries `PROD_VERSION`). No production-derived snapshot
was taken.

Side effect (not part of the release): the broad sweep's W10 tests rewrote 28
tracked PNG/JSON evidence files under `plans/features/evol/audit/evidence/`.
They were restored to HEAD immediately (`git status` clean) and are not included.

## 5. Rows bound by this assembly

- **14 rows candidate-bound REVIEW** (not VERIFIED): MAC-S6-308, MAC-S6-MEM-01,
  MAC-S6-REST-01, MAC-S7-FEED-04, MAC-S7-FEED-01, MAC-S7-FEED-02, MAC-S7-FEED-03,
  MAC-AC-18, MAC-S6-311, MAC-S6-310, MAC-S15-04, MAC-S15-05, MAC-S15-07, MAC-S15-11.
- **MAC-S6-SCN-01** — READY_FOR_LIVE / RFL, not VERIFIED (no production-derived
  snapshot / live TMA in this lane).
- **D2 parked, not in this release:** MAC-S6-345, MAC-AC-15 (PENDING).
- **4 RFL untouched:** MAC-S6-307, MAC-S15-03, MAC-S6-FEED-03, MAC-S6-346.
- No row is VERIFIED before an actual deploy and production-bound evidence.

## 6. Manifest, rollback, runbook

- `manifest-dry-run.json`: exit 0; `deployed_sha=ff8a59636…` (content/bump tip),
  `version=2.58.228`, `previous_sha=c8cf54c1a…`, `previous_version=2.58.227`,
  `release_branch=release/mod-acl-m4b3-2.58.228`, `dirty_tracked=false`,
  `effect=deploy`, `deployer=builder-release-prep`. The previous-manifest input
  was seeded locally (git-ignored `.deploy/`) and removed immediately; no
  production files were read.
- Rollback/base: `c8cf54c1a` (2.58.227), schema 48, DDL 0; no migration, no data
  action.
- `deploy-runbook-2.58.228.md`: deploy steps, read-only post-deploy checks
  (health/version/identity/schema/journal/settings/disk), the B3 UI acceptance
  matrix confirmed pre-deploy on identical bytes, and rollback.

## 7. Limitations

- REVIEW only: no production deploy, no SSH, no live Telegram/TMA/provider call,
  no settings or DB writes, no VERIFIED claim.
- B3 e2e is served bytes + a deterministic synthetic stub, not a live TMA
  session; the Reviewer's Browser Use run (1920/1440/390/360) was performed on
  the same candidate bytes (identical served sha256), not re-run in this lane.
- Production-derived `/api/status` + `/api/memory/*` snapshot was not captured
  (task boundary); MAC-S6-SCN-01 remains RFL.
- The 40 broad-sweep and 4 pin-guard failures are pre-existing; only 5 of 40
  were re-run on the base, the remaining 35 are inherited from the base by
  file content (B3 does not touch those files).
- `tools/ui_cmv_perf_parity.py` was not run in this assembly.
