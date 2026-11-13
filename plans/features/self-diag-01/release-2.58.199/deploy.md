# Release 2.58.199 — deploy record

- Status: **DEPLOYED / engineering delivery PASS**; final acceptance pending the
  release gate and PM map reconciliation (see `release-gate.txt`).
- Date: 2026-11-13, server UTC 08:36 (deploy), checks through 08:44.
- Candidate: `d20a7f730715ba9e9cba7673c0557794979be339` on `release/2.58.199`
- Base: `234776589c934024ed0e8dceba189fb9d70d3215` (2.58.198, previous production)
- Train reviewed tip: `509ae75a55bb76e7dd2b3c305860d431424ad3fb`
  (code tip `7c5669e55a9ad62914dd721450b4302d967f4c93`; fixture fix `773417ff`)
- Superseded, never deployed: `131e2a7c` (blocked by the manifest fixture collision).
- Production surface: VPS `192.255.209.205`, unit `admin_bot` (user `adminbot`,
  group `root`), `/var/www/admin_bot`, health `https://admin-bot.duckdns.org/healthz`.

## Cumulative diff

`git diff --shortstat 23477658..d20a7f73`:

```
106 files changed, 41606 insertions(+), 146 deletions(-)
```

= 76 train files + 30 version-pin files, 0 overlap, 0 extra, 0 missing
(`cumulative-diff-files.txt`). The bump commit changes only version pins:
30 files / 31 lines, LF preserved.

## Pre-deploy verification (bumped candidate d20a7f73)

| Set | Result |
|---|---|
| Core research `test_selfdiag_corrective_research.py` | 28 passed |
| Core focused 10-file set | 330 passed |
| Identity + manifest (incl. fixture fix) | **58 passed** |
| VMQ M1 `test_vmq_m1_episode_contract.py` | 34 passed |
| VMQ NEXT-02 `test_memory_period_vector_leg.py` | 30 passed |
| Web-wide `tests/test_web*.py` (68 files) | 11 failed / 1541 passed — identical known baseline |
| Pin-file guard set (24 files) | 856 passed / 4 failed — same 4 fail on base `23477658` (pre-existing) |
| `py_compile` 62 changed `.py` files | exit 0 |

No new failure. Details: `predeploy-tests.md`.

## Production pre-state (2026-11-13T08:35:06Z)

- HEAD `23477658`, branch `release/2.58.198`, tracked/staged clean (one untracked
  `.cache/`; `git status` only `?? .cache/`).
- `APP_VERSION = "2.58.198"`, service active, `/healthz` 200
  `{"status":"ok","version":"2.58.198"}`, schema 47.
- `.deploy/release.json` absent (first manifest deploy).
- Journal (last hour before restart): 1 `Traceback`, 0 `attempt LOST`.

Data backup (retained on the server):

```
backups/pre_deploy_258199_20261113T083507Z.db
user_version=47  integrity=ok  bytes=2632986624
sha256=6c1a7fac1c984c6b0f00478a9501a5f63ea76caebe7c1255d906aa84afce246b
```

## Deploy sequence (single main session)

1. `git fetch --prune origin`; `origin/release/2.58.199` = `d20a7f73`.
2. `git switch -c release/2.58.199 --track origin/release/2.58.199`;
   `git pull --ff-only origin release/2.58.199`; HEAD asserted = `d20a7f73`.
3. **Before restart:** `venv/bin/python tools/release_manifest.py` →
   `.deploy/release.json` (schema 1):

   ```
   deployed_sha=d20a7f730715ba9e9cba7673c0557794979be339
   version=2.58.199  effect=deploy
   deployed_at=2026-11-13T08:36:16.759775Z
   previous_sha=null previous_version=null   (first manifest deploy)
   ```

   `chmod 0644`, `.deploy` owned by `adminbot`; readability verified with
   `sudo -u adminbot test -r .deploy/release.json` → 1.
4. `systemctl restart admin_bot`; poll: `502` on first tick, then `200`
   `{"status":"ok","version":"2.58.199"}`.

## Post-deploy verification

| Check | Observed |
|---|---|
| HEAD / branch | `d20a7f73` / `release/2.58.199` |
| `APP_VERSION` | 2.58.199 |
| Service | active, `ExecMainStartTimestamp` 08:36:18 UTC, pid 454989 |
| `/healthz` | 200 `{"status":"ok","version":"2.58.199"}` |
| Schema | 47 (no DDL/migrations) |
| Manifest | present, readable by `adminbot` |
| Identity (`collect_identity`, running pid) | `code=verified_deployed`, `deployed_sha == checkout_sha == d20a7f73`, `dirty=false`, version provenance `{runtime: 2.58.199, manifest: 2.58.199, consistent: true}`, sources `release_manifest/git_head/git_cli/runtime_app_version/process_start` |
| Journal as service user | `sudo -u adminbot journalctl -u admin_bot -n 50` rc=0 |
| Tracebacks / `attempt LOST` | 0 / 0 in the 15 minutes after restart (pre: 1 / 0 in the prior hour) |
| Deployed-build tests | `test_checkup_contract.py` + `test_selfdiag_corrective_research.py` + `test_self_diag_golden.py`: **108 passed**; golden alone: **39 passed** |
| Settings parity | `bot_settings` 547 rows, `chat_profiles` 3 rows; max `updated_at` 2026-11-11 / 2026-11-12 — both before deploy; SQLite meme tables byte-hash identical before/after. See `settings-parity.md` |

## Live API smoke (`GET /api/status/self-diagnosis`, loopback:8000)

- Missing initData → **401**; invalid signature → **401**.
- Authorized admin (`ADMIN_USER_ID`, valid HMAC): **200**; runtime version
  2.58.199, pid 454989, `deployed_sha`/`checkout_sha` = `d20a7f73`; fields
  `analytics, available, chat_id, code_check, generated_at, integrations,
  jobs, missing_evidence, resources, runtime, sources, storage_text, window`.
- TTL: immediate second call ~1 ms (cache hit); after 31 s ~116 ms (fresh).
- Secret scan over the response: no API-token value, no `Bearer`, `api_key`,
  `bot_token`, `Authorization:`.
- Honest counters: `logs.errors`, `media.stt`, `telegram.delivery` returned
  `status=not_checked` with `facts=null` — no fake zero.
- RBAC: `bot_server_state` is `PUBLIC_TECH`, so a regular user receives the
  public snapshot by design; protected prompt content is not exposed by this
  endpoint. The hard rule `denied_prompt_content_member` was exercised in the
  policy engine for a member actor.
- `prompt_readback`: service-level `prepare` in a standalone process has no
  app cache/PG role layer, so it returned an honest `denied`/`unverified`
  (`denied_prompt_content_member` / `denied_auth_unverified`) instead of an
  allowed body. The allowed and denied branches are covered by the deployed
  contract tests (108 passed). **No Telegram message, prompt body or LLM call
  was sent/produced during smoke.**

## Release gate (not green — acceptance bookkeeping)

`requirements_gate.py check --stage release --candidate d20a7f73 --deployed-commit d20a7f73`
exits **1**: `stage=release inventory=183 manual=53 scoped=189 errors=429`.
Map statuses: 114 `VERIFIED`, 47 `PENDING`, 22 `READY_FOR_LIVE`; the map still
has `deployed_commit=23477658` / `deployed_version=2.58.198`. Inventory errors
are source-item drift (`L001xx ... gone or edited`), not a production failure.
Full output: `release-gate.txt`. Acceptance/PM must reconcile the map; this
record does not claim epic DONE.

## Rollback readiness

See `rollback.md`. Documented rollback target: `25876167` (2.58.197), code-only,
schema 47, data unchanged. Immediate pre-state for a fast revert is `23477658`
(2.58.198). No rollback was executed; the service stayed healthy.

## Incidental production observations (outside this train)

- Four stale guard tests in `test_tool_coordinator_round1026.py` /
  `test_unified_image_request_round1026.py` fail identically on base `23477658`
  (18 tools vs expected 17; `web/` diff allowlist vs ancient
  `pre-round1026-a1`). Pre-existing, backlog only.
- `AntiClicheWorker` at 08:41:21 logged `provider_unavailable` / `fetch_error`
  for `wikipedia` (source fetch). No antcliche code in this train; external
  provider issue, backlog only. Service continued normally.
