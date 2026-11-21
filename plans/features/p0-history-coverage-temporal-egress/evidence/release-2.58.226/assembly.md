# Release 2.58.226 — P0-HC: history coverage / temporal evidence / Telegram egress

**Status:** REVIEW (assembly only; not deployed, not VERIFIED)
**Date:** 2026-11-21 (+12:00)
**Branch:** `release/p0-hc-2.58.226`
**Product tip:** `e26ebc16311f83d4df5ec265ce2933ee19e11440` (test-only delta on `4bb7e593c5d4b085290ff7f034f0f1b28b0233bb`)
**Base / rollback:** `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d` (2.58.225, schema 48, DDL 0)
**Bump / content tip:** `bafbd0863d7c8bb157abe3428463eedd9fa0079f`
**Version:** 2.58.226
**Schema/DDL:** 48 / 0

Independent review: `plans/features/p0-history-coverage-temporal-egress/evidence/accept/review-harness-r2.md`
at master `ccf41c1edad223d4bf6162db94d99e1c5fe2f68a` (addendum commit), sha256
`f7aba14d0c8145f18dc2babb06aa540bf455edbd00e2984bc79f5d376e7cc8c9`
(26 454 bytes), verdict **APPROVED_FOR_RELEASE_PREPARATION** for the delta.
The main body of the same artifact first returned NEEDS_FIXES; the addendum closes
`HC-ACC-R2-F1` (five stale pre-B Thread/Branch test oracles) after the test-only
`e26ebc163` (+12/−12, `tests/test_direct_chat.py` only). Product bytes are unchanged
since `4bb7e593c`. `HC-ACC-R2-F2/F5/F6` were already closed; the non-blocking
`HC-ACC-R2-N1..N4`, carried `HC-ACC-R1-N1/N2` and the external 402 rows
(`HC-ACC-FREE-SPEECH`, `HC-ACC-NO-OBJECTIVITY`) remain non-blocking and **not**
VERIFIED.

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | Worktree via installed `workflow_housekeeping.py worktree-path` + `git worktree add` + `register-worktree` | `WorkspaceData/worktrees/c742e4de9e92c489/release-p0-hc-2-58-226-c7ff08520e12-3b02cfca`; branch from `e26ebc163`; no sibling checkout |
| 2 | Branch ancestry | 22 commits from `1b7d43333` to the content tip; **0 merge commits**; acceptance harness not in the branch |
| 3 | Standard bump `2.58.225 -> 2.58.226` | `bafbd0863`; **31 files / 34 insertions / 34 deletions** |
| 4 | Product scope | 11 P0 product files (`+2451/−98`) + `config/settings.py` bump only; no DDL/migrations/prompts/flags/second retrieval |
| 5 | Tests on bumped tip | focused 306/0; direct_chat 161/0; pin guard 856/4 (4 pre-existing); JS 6/6; broad 1547/17 + 2 errors (all pre-existing) |
| 6 | Manifest dry-run at content tip | exit 0; version 2.58.226; previous `1b7d43333` / 2.58.225; dirty false |
| 7 | Release evidence (this directory) | docs-only commit after `bafbd0863` |

The branch contains no acceptance harness. `tools/p0_hc_acceptance.py` and
`tests/test_p0_hc_acceptance.py` stay on `p0/hc-accept`: they pin
`CANDIDATE_SHA`/`EXPECTED_RELEASE` and would be blocked by the bump. This is
intentional and is not a missing product test.

## 2. Product delta

| File | Insertions | Deletions |
|---|---:|---:|
| `services/canonical_context.py` | 53 | 5 |
| `services/database.py` | 4 | 1 |
| `services/direct_chat_service.py` | 562 | 41 |
| `services/direct_l1.py` | 13 | 1 |
| `services/mca_retrieval_context.py` | 104 | 10 |
| `services/prompt_style_blocks.py` | 6 | 1 |
| `services/summary_memory.py` | 44 | 6 |
| `services/telegram_markup.py` | 849 | 0 |
| `services/thread_chain.py` | 37 | 2 |
| `services/tool_router.py` | 776 | 30 |
| `services/tool_schemas.py` | 3 | 1 |
| **P0 product total** | **2451** | **98** |

- `git diff --name-only 1b7d43333..HEAD -- services config handlers web`
  = the 11 files above + `config/settings.py` (bump only). No other product path.
- `git diff --name-only 1b7d43333..HEAD -- database.py migrations prompts chat_prompts.py services/telegram_send.py`
  = empty. `services/database.py` adds only `sent_at, edited_at, reply_to_author_id`
  to three read-only SELECT lists; no DDL, index, ORDER BY or migration.
- `git diff --name-only 1b7d43333..HEAD -- web` = empty.
- Product behavior: closed period grammar (duration, yesterday/today, local
  day/interval, date ranges, bare units) resolved from `turn_as_of` in the chat
  IANA zone with DST; range-first `get_recent_history` with exact
  `from/to/available/processed/remaining/has_next/incomplete`, honest
  `empty`/`unresolved`, no FTS substitution; real `sent_at`/`edited_at`/reply
  edge reach context and Writer with a single UTC scale and legend, not
  `created_at`; ordinary Direct answers keep literal text plain and send
  structural Markdown as safe HTML (escape, link, tag-safe chunking, one-chunk
  plain fallback) without a second send path.
- Schema invariant: `_SCHEMA_VERSION_RANDOM_BATCH_PROVENANCE = 48` is byte-identical
  at `1b7d43333` and `HEAD`; `migrations/` is untouched; DDL 0.

## 3. Bump and invariants

- `APP_VERSION = "2.58.226"` with the 2.58.226 changelog entry and `Prior 2.58.225`.
- Standard pins: `plans/docs/param-registry-round1025.meta.md`, 24 Python test files
  (polygon has two lines), 4 escaped JS pins, and `tools/ui_mod_acl_m4b2_status_e2e.py`
  (three pins that did not exist in the 2.58.225 wave). Exactly **31 files / 34 / 34**.
- Every non-settings diff is byte-identical to the previous file after reversing
  `2.58.226 -> 2.58.225` (including the escaped JS form); `settings.py` differs only
  by the new version and prepended release note. Verified programmatically.
- BOM/CRLF preserved: `settings.py` remains UTF-8 BOM + 3645 CRLF (one bare LF);
  no other file changed its encoding/line endings.
- `git diff --check -- services config tests tools` rc=0; `py_compile` of the 11
  product modules + `settings.py` rc=0; `node --check web/app.js` rc=0.
- `plans/progress_scope.json` and `plans/workflow_state.md` were not changed.

## 4. Tests (bumped tip)

Machine-readable record: `tests-2.58.226.json`; raw result lines: `tests-2.58.226.txt`.
Environment: Python 3.12.0, pytest 9.1.1, Node v24.16.0, Windows.

| Batch | Result |
|---|---|
| P0 focused/affected, 7 files | **306 passed, 0 failed** (52.23 s); includes `test_p0_hc_*` and history pages/segments/isolation |
| `tests/test_direct_chat.py` | **161 passed, 0 failed** (14.43 s) |
| Pin guard, 24 Python version-pin files | **856 passed, 4 failed** (72.68 s); same 4 node IDs fail on base `1b7d43333` (4 failed, 10.39 s) |
| JS set, 6 files | **6/6 rc=0, 0 failed**; HOTFIX7/8/9/10, MOD-ACL W2b history, ASAP3 Direct context markers |
| Broad Direct/context, 16 files | **519 passed, 6 failed** (165.41 s); all 6 reproduce on base (6 failed, 3.53 s) |
| Broad history/related, 17 files | **409 passed, 10 failed, 2 errors** (31.02 s); same 10+2 reproduce on base (109 passed, 10 failed, 2 errors, 10.84 s) |
| Broad memory/tool/db/clock, 14 files | **540 passed, 1 failed** (138.48 s); same failure reproduces on base (1 failed) |
| `tests/test_summary_memory.py` alone | **79 passed, 0 failed** (9.02 s) |
| Schema/compile checks | temp SQLite smoke: target/user_version 48, `schema_migrations` max/count 48, journal `wal`, DDL 0; py_compile and node check green |

Pre-existing failures reproduced on base `1b7d43333` (not counted as pass):
the 4 pin-guard node IDs (`test_tool_coordinator_round1026.py` x2,
`test_unified_image_request_round1026.py` x2), 5 fallback-recompose tests and
`test_direct_l1_corrective_r1.py::test_build_l1_context_bot_replies_caps_and_limit`,
8 `test_history_w4_fixes.py` banner/boundary tests, `test_history_cli.py::TestCliFts::test_scope_is_required`,
`test_verbilizer_response_modes_round1023.py::TestTwoCallModes::test_summary_kill_switch_off_prev_narrator`
plus its 2 unicode-parametrized fixture errors, and
`test_ur_c_clock.py::TestFallbackAdapterClock::test_generous_budget_keeps_block_intact_same_asof`
(already documented as pre-existing at A/B tips).

A single combined broad invocation hit the repository's 60 s `pytest-timeout`
in async teardown on Windows; the same files were therefore run in three
deterministic groups plus `test_summary_memory.py` alone. No file changed its
result between the combined and split runs.

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: exit 0; `deployed_sha` `bafbd0863d7c8bb157abe3428463eedd9fa0079f`
  (content/bump tip), `version` 2.58.226, `previous_sha`
  `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d`, `previous_version` 2.58.225,
  `release_branch` `release/p0-hc-2.58.226`, `dirty_tracked` false,
  `effect` deploy, `deployer` builder-release-prep. `.deploy/` was reconstructed
  locally (git-ignored) and removed; production files were not read.
- The evidence commit after `bafbd0863` is docs-only. DevOps must run
  `release_manifest.py` on the actual checked-out SHA after pull; the honest
  `deployed_sha` is whatever `git rev-parse HEAD` returns there.
- `deploy-runbook-2.58.226.md`: backup, manifest, restart, health/version/schema/
  identity/NRestarts/journal/disk/settings checks, P0 post-deploy read-only checks,
  and rollback to `1b7d43333` / 2.58.225 (no schema downgrade; same schema 48).

## 6. Limitations and residual

- No production access, SSH, deploy, live Telegram or VERIFIED claim in this
  assembly; the review verdict is only `APPROVED_FOR_RELEASE_PREPARATION`.
- The acceptance harness is excluded from this branch by design (see §1); its
  pinned candidate/release values must not be “fixed” by weakening assertions.
- The independent review artifact lives on master and is not in the candidate
  ancestry; it is referenced by commit and sha256 above.
- `HC-ACC-FREE-SPEECH` / `HC-ACC-NO-OBJECTIVITY` remain `not_executed` (external
  provider HTTP 402) and are not promoted here.
- Pre-existing test failures listed in §4 remain; they are not release blockers
  for this delta but are not counted as passes either.
- No UI/visual change: this delta is Direct/backend/Telegram payload behavior,
  so no Playwright/Browser Use run was required for release preparation.
