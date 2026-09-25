# A5 `image-daily-limit-round1026` — Evidence (Builder, session 2)

- **Epic:** Эпик 3 «Agentic Intelligence», Wave 3 — A5
- **Risk:** R3 (ADR-1026-17 D12)
- **Baseline anchor:** `e8646af` (EPIC_ONLY; no per-feature tag)
- **Feature dir:** `plans/features/image-daily-limit-round1026/`
- **Release policy:** EPIC_ONLY — deploy DEFERRED to epic; no commit/tag/bump by Builder

## Remaining-action checklist (execute top → bottom)

- [x] **A. T-3599 tests** — `tests/test_image_daily_limit_round1026.py` (13 passed):
  - [x] A1 reserve→commit happy path — `TestA1HappyPath.test_reserve_commit_once`
  - [x] A2 SC-A5-04 race — `TestA2Race.test_two_concurrent_reserves_exactly_one`
  - [x] A3 deny no consume / release restores — `TestA3DenyRelease.test_deny_does_not_consume`, `.test_generation_failure_release_restores`
  - [x] A4 idempotency — `TestA4Idempotency.test_same_key_no_double_spend`, `.test_replay_denied_returns_prior_outcome`
  - [x] A5 delivery failure — `TestA5DeliveryFailure.test_send_failure_commits_and_no_second_generation`
  - [x] A6 per-chat TZ — `TestA6Timezone.test_day_and_next_reset_use_chat_tz`, `.test_limit_change_does_not_zero_used`
  - [x] A7 kill-switch OFF / fail-open — `TestA7KillSwitchFailOpen.*` (4 tests)
- [x] **B. T-3603 UI** — minimal in-flow mod_images:
  - [x] B1 additive fields: `services/worker_budget.py:463` `image_usage` per chat entry (from `image_usage_summary`: day/timezone/used/limit/source/next_reset_at/requests/success/errors/denied/delivery_failed/shared_used/shared_limit); shared row in `global.image_calls` (`worker_budget.py:471-480`). Endpoint `/api/workers/budget` unchanged (additive, R16).
  - [x] B2 display: `web/app.js` computed `imageUsage` (~3410) + methods `imageSourceLabel`/`imageResetLabel` (~4560); `WORKSPACE_TABS.mod_images` += `'limits'` (~590); `web/index.html` `data-image-limits` panel (~1462) in `mod_images` limits tab — дневной лимит/Used today N/M/source/reset/TZ + read-only shared-budget row.
  - [x] Web test: `tests/test_webapp_gates_api.py::TestWorkersBudget::test_image_usage_additive_fields` (10 passed)
- [x] **C. Verification** (numbers):
  - [x] C1 full pytest `.venv`: **9170 passed / 0 failed** (baseline 9156 + 14 new: 13 in test_image_daily_limit + 1 gates API)
  - [x] C2 JS: **47/47** (`node tests/js/*.js` all return 0, node v24.16.0)
  - [x] C3 catalog **470/427/445/101/99/21**; SQLite `user_version=12` (tests/test_database 127 passed; local_database.db copy is 0 — non-authoritative per A0); `git diff --check` exit 0
  - [x] C4 boundary `git diff --name-only e8646af`: no `summaries/*.py`, no prompts, APP_VERSION **2.58.30 unchanged**, A4/A6/A7 files absent. NOTE: `services/param_catalog.py`, `web/app.js`, `web/index.html` present — A5/D9-sanctioned; boundary tests in 6 other suites amended with A5 NOTE.
- [x] **C-fix: stale cross-feature tests updated to A5 sanctioned contract** (not scope expansion):
  - `test_summary_l2_writer.py`: Settings count 426→427
  - `test_summary_execution_graph_round1026.py` / `test_summary_publish_integration_round1026.py` / `test_summary_deploy_round1026.py` / `test_tool_coordinator_round1026.py` / `test_unified_image_request_round1026.py`: param_catalog (+ web/app.js,index.html) removed from forbidden-path lists, A5 NOTE
  - `test_unified_image_request_round1026.py`: `generate_and_send` excluded from AST-identity set (§104 core `generate` still SAME), `source` kwarg in stubs
  - `test_token_analytics_round1023.py`: `_fake_send` accepts `source`/`**kwargs`
  - `test_hotfix5_summary_cover_window_round1025.py`: per-chat image limit now catalog-resolved (D4)
  - `test_webapp_f5_round1025.py`: mod_images tabs include `'limits'`
- [x] **D. Artifacts**
  - [x] D1 evidence.md (this file) — file:line refs, commands+results, 14 invariants, R17/R18, blockers
  - [x] D2 threat-failure-analysis.md — 12 threats (threat → mechanism → code → named test)
  - [x] D3 tasks.md — T-3590..T-3603 [x] with one-line status; header replaced; T-3587..T-3589/T-3604..T-3607 untouched

## Status log

(populated as actions complete)

## Verification commands + actual results (C)

- `pytest .venv -q` → **9170 passed / 0 failed** (180s). Baseline e8646af-era 9156/0; +14 = 13 `test_image_daily_limit_round1026.py` + 1 `test_webapp_gates_api.py::test_image_usage_additive_fields`.
- JS: `node tests/js/*.js` (47 files, node v24.16.0) → **47/47 exit 0**.
- Catalog: `REGISTRY 470 · GROUPS 101 · categorized 445 · _TAB_BY_GROUP 99 · Settings 427 · TAB_RULES 21` = **470/427/445/101/99/21** ✓.
- SQLite `user_version` → asserted **12** by `tests/test_database.py` (127 passed). `local_database.db` copy shows 0 — non-authoritative (A0 note).
- `git diff --check` → exit **0** (only LF→CRLF informational warnings).
- `APP_VERSION` → **2.58.30** (unchanged; no bump).
- Boundary `git diff --name-only e8646af`: no `summaries/*.py`, no prompt files, A4/A6/A7 files absent (`services/image_context_memory.py`/`user_context.py`/`url_factcheck.py` = False). Present: `services/param_catalog.py`, `web/app.js`, `web/index.html` (A5/D9-sanctioned).

## Epic inputs contributed by this feature (release-candidate)

- Code: `services/pg_db.py` (PG `image_reservation` +2 indexes), `services/worker_budget.py` (reserve/commit/release/journal/summary/meta), `services/image_generation.py` (`_reserve_or_consume`/`_commit_or_release`/`build_image_idem_key`), `config/settings.py` (`IMAGE_DAILY_LIMIT_ENABLED`, `IMAGE_RESERVATION_RETENTION_DAYS`), `services/param_catalog.py` (+1 ParamSpec/+1 GroupSpec), `web/app.js` + `web/index.html` (UI врезка).
- Tests: `tests/test_image_daily_limit_round1026.py` (new), `tests/test_webapp_gates_api.py` (web), plus contract updates in 7 cross-feature suites.
- Artifacts: this `evidence.md`, `threat-failure-analysis.md`.
- Deploy: **DEFERRED_TO_EPIC** (EPIC_ONLY) — no per-feature deploy/tag/bump.

## 14 acceptance invariants — status (one line each)

1. No double-spend/leak: **OK** — conditional UPSERT + idem PK; `TestA1/A2/A4`.
2. Rollback/outcome D7 (release on gen failure, commit+delivery_failed on success incl. delivery failure, no auto re-gen): **OK** — `TestA3/A5`.
3. Server atomicity no check-after-increment race: **OK** — shared+chat one transaction, denial rolls back shared; `TestA2Race` (limit=1 → exactly one).
4. Honest scope D4 (catalog default ≠ shared env quota; sentinel kept): **OK** — `image_limits`, `test_image_usage_additive_fields` (60 vs 200).
5. TZ/reset reuse chat TZ, calendar day, exact reset, limit change keeps used: **OK** — `TestA6Timezone`.
6. Extend existing worker_budget without second counter (ledger not counter): **OK** — `image_usage_summary` from journal; `used` from worker_budget.
7. Existing direct/tool paths no regress (2-call, A3 marker, cross-path): **OK** — full pytest + `test_unified_image_request`/`test_token_analytics` updated & green.
8. fail-open parity (D8) + honest WARNING dedup + no partial consumption: **OK** — `TestA7` `_BoomConn`.
9. §104 `generate_image` outside diff (provider/model/keys/prompts unchanged): **OK** — AST gate: `generate`/`generate_image(_verbose)` SAME vs e8646af.
10. UI §27/§50 sanctioned (T-3603 active): **OK** — `mod_images` limits panel + additive fields; no duplicate setting/panel.
11. Δ DDL sanctioned (PG table +2 indexes, idempotent; SQLite v12): **OK** — `test_pg_db` (127) + `test_database` v12.
12. R17/R18: **OK** — journal only id/code/day/flags; no content/prompts/URL/keys; tags/backups untouched; no commit.
13. Deploy DEFERRED (EPIC_ONLY): **OK** — no deploy/tag/bump; rollback = env kill-switch OFF / `git revert` e8646af; no DDL rollback needed.
14. Wave boundaries A4/A6/A7 respected: **OK** — files absent; canon 11; ADR-1013-3 N/A; A3 stub fields untouched.

## R17/R18 confirmation

- **R17:** `image_reservation` columns = `reservation_key, chat_id, source, message_id, day, status, error_code, delivery_failed` (no content). Idem key built from ids/enum only (`build_image_idem_key`), never from prompt/LLM/tool output. Logs contain only `chat`/`source`/`status`/`reason`/codes. No secrets/URLs/prompts in diff.
- **R18:** no commits/tags/branches created; backup tags, `.env.bak`, `stash` untouched; `plans/current_task.md` and the `OPENCODE_WORKFLOW_STATE_V1` block not modified.

## Blockers

None. 14 initially-failing cross-feature tests were stale against the A5 sanctioned contract and were updated to it (documented in "C-fix"); after the fix full suite = **9170/0**.
