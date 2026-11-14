# Release 2.58.200 — deploy record (SMART-EXECUTION-RELIABILITY-01 + FACTCHECK-REQUEST-INTEGRITY v2)

- Status: **DEPLOYED**, immediate post-deploy checks green; acceptance mapping
  (`VERIFIED`/`READY_FOR_LIVE`) is PM/Orchestrator work — this record does not
  change any map status.
- Date: 2026-11-14, server UTC 05:18:47 (pre) → 05:19:35 (post checks).
- Candidate: `0e4a144db476a1535ae3a2b79a7cce30354ad866` on `release/2.58.200`
  (code tree = reviewed train tip `1d9cf251`, plus a version-pin-only bump).
- Reviewed train tip: `1d9cf251f30e2f0c5243a0a23aab3a43cdfc3029`
  (`smart/release-train-01`; merge log `evidence/release-train/merge-log-aca13702.md`).
- Base / rollback target: `d20a7f730715ba9e9cba7673c0557794979be339`
  (2.58.199, `release/2.58.199`).
- Production: VPS `192.255.209.205`, unit `admin_bot` (user `adminbot`),
  `/var/www/admin_bot`, `/healthz` on `https://admin-bot.duckdns.org`.
- Schema: `user_version=47` before and after; `[database] migrations: pending=[]`
  — **no DDL, no data migration**.

## Candidate composition

Post-approval delta (`1d9cf251..0e4a144d`) = **30 files / 31 lines**, only
version pins (`APP_VERSION`, `plans/docs/param-registry-round1025.meta.md`,
24 pytest pin files, 4 `tests/js` pin files). Cumulative diff from production
baseline `d20a7f73`: `387 files changed, 51189 insertions(+), 13522 deletions(-)`.

## Pre-deploy verification (bumped candidate `0e4a144d`)

| Set | Result |
|---|---|
| Feature/acceptance 17-file set (smart/sxr/caps/checkup/release_manifest) | **362 passed** |
| FACTCHECK acceptance/regression 15-file set | **276 passed** |
| Pin-guard set (24 files touched by the bump) | **856 passed / 4 failed** |
| Broad smoke 26-file set (budgets/tool-loop/router/evidence/direct/experience/catalog/webapp_api/self-diag/prompt-audit) | **1037 passed / 12 failed** |
| `py_compile` / clean tree | `git status --porcelain` = 0, `git diff --check` = 0 |

Both failure sets are **identical to the production baseline `d20a7f73`**
(reproduced on the 2.58.199 worktree in the same run): the 4 pin-guard failures
(`test_tool_coordinator_round1026` canon 18 tools, `test_unified_image_request_round1026`
canon + ancient diff allowlist) and the 12 broad-smoke failures
(`test_budget_*_round1024`, `test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface`)
fail on base too → **no new failures**. Pre-existing, backlog only.

Manifest producer dry check (local, bumped tree): `version=2.58.200`,
`deployed_sha=0e4a144d…`, `release_branch=release/2.58.200`, `dirty_tracked=false`.

## Deploy sequence (one main session; recon was one short session before)

1. Pre-state: HEAD `d20a7f73`, branch `release/2.58.199`, tracked tree clean
   (`?? .cache/` only), service active (pid 454989), `/healthz` 200 `2.58.199`,
   manifest `2.58.199`.
2. `git fetch --prune origin release/2.58.200` → `FETCH_HEAD` asserted =
   `0e4a144d`.
3. Data backup (disk had 32.5 GB free): `backups/pre_deploy_258200_20261114T051849Z.db`,
   3,015,938,048 bytes.
4. `git switch -c release/2.58.200 --track origin/release/2.58.200`; HEAD asserted
   = `0e4a144d`; `APP_VERSION` = `2.58.200`.
5. **Before restart**: `venv/bin/python tools/release_manifest.py` →
   `.deploy/release.json` schema 1, `chmod 0644`, `chown adminbot:adminbot`,
   readable as `adminbot` (rc=0).
6. `systemctl restart admin_bot` (rc=0). Health poll: tick1/tick2 empty (502
   during boot), tick3 `200 {"status":"ok","version":"2.58.200"}`.

## Post-deploy verification

| Check | Observed |
|---|---|
| HEAD / branch / dirty | `0e4a144d` / `release/2.58.200` / 1 (`?? .cache/`) |
| `APP_VERSION` | 2.58.200 |
| Service | active, `ExecMainStartTimestamp` 2026-11-14 05:18:59 UTC, pid 709883 |
| `/healthz` | 200 `{"status":"ok","version":"2.58.200"}` |
| Manifest | `deployed_sha=0e4a144d…`, `version=2.58.200`, `effect=deploy`, `previous_sha=d20a7f73…`, `previous_version=2.58.199`, `release_branch=release/2.58.200`, `dirty_tracked=false` |
| Schema | `user_version=47`, `journal_mode=wal`; migrations `pending=[]` |
| Service-user journal | `sudo -u adminbot journalctl -u admin_bot` rc=0 |
| Tracebacks / ERROR since start | 0 / 0 (1 pre-existing WARNING: `summary_memory … FTS-only (A06) … source empty`) |
| Startup | `pg_available=True`, polling started as `@PERMsoc_bot`, schedulers started, `webapp lifespan started` |
| Disk after backup | 29.6 GB free |

## Effective configuration after deploy (read-only readback)

- Factory/env layer (`config.settings`): `CHAT_UNKNOWN_MODEL_WINDOW=1000000`,
  `MCA_TOOL_MAX_TOTAL_CALLS=0`, `MCA_TOOL_MAX_METERED_CALLS=0`,
  `MCA_TOOL_MAX_SAME_CALL=0`, `MCA_TOOL_CHAIN_TIMEOUT_SECONDS=0.0`,
  `TOOL_CHAIN_LIMITS_ENABLED=True`, `BUDGETS_ENABLED=True` (factory only).
  No `MCA_*`/`BUDGETS_ENABLED`/`CHAT_UNKNOWN_MODEL_WINDOW` overrides in `.env`.
- Persisted master switch: `bot_settings['flags.budgets_enabled'] = false`
  (2026-10-25, unchanged). Per-chat overrides unchanged:
  group1 `false`, group2 `false`, DM absent → **effective budgets OFF in all three chats**.
- Capacity for the chat-path model `z-ai/glm-5.3-flash-uncensored`:
  legacy sync resolver `(1000000, unknown_fallback)` (no more 16384), async
  provider catalog `effective_context_window=1048576`, `max_output_tokens=32768`,
  `source=provider_catalog`, `confidence=verified`, `fallback_used=false`.
- Preserved settings: `bot_settings` rows 547 → 548 — the only new row is
  `prompts.factcheck_subject_system_prompt` (factory text of the new service
  prompt, category `prompts`); no row owned by the user was updated.
  `chat_profiles` max `updated_at` unchanged (2026-11-13 11:07:51Z); override key
  counts unchanged (8 / 31 / 5); `models.llm_model_name` / `llm_base_url` rows
  unchanged (2026-11-11 / 2026-09-12). Config migrations logged
  `CONFIG_MIGRATION_CUSTOM_PRESERVED` for context budget and image model/base_url.

## Rollback

See `rollback.md`. Target `d20a7f73` (2.58.199), code-only; schema 47, data not
rolled back; pre-deploy DB copy retained on the server.

## Release gate state (acceptance bookkeeping, not a production defect)

`requirements_gate.py check --stage deploy --candidate 0e4a144d… --repo .` on
`requirements-map.json` exits **1** with
`stage=deploy inventory=509 manual=359 scoped=828 errors=829` and
`FAIL: candidate mismatch; map candidate_commit must match --candidate`
(the map still records candidate `d20a7f73`). This is the documented
multi-candidate binding state: PM/Orchestrator rebind map evidence to the
deployed SHA `0e4a144d` and then run the release/delivery gates. Nothing was
edited in the map by DevOps. Compact output: `gate-state-before-rebind.txt`.

## Residual (not claimed as verified here)

Live/post-deploy-only proof remains for PM binding on `0e4a144d`:
real LLM payload/evidence completeness in a live request, Telegram delivery
canary, real provider responses/search, live checkup with continuation, and the
factcheck request-integrity scenarios in the live chat path. No Telegram message
and no paid LLM call was produced by this deploy check. No secrets were printed;
chat ids are replaced by `CHAT1..3`.
