# Release 2.58.263 — deploy evidence (FC-TRUST-01 S3/S2)

Deployed 2026-11-27T21:48:50Z (service restart 21:48:52Z). Role: DevOps.
Host `192.255.209.205:/var/www/admin_bot`, sequential single SSH connections (6 total, all key-auth, no parallel sessions, no background processes).

## Authorisation and composition

- Reviewed candidate `a50bcaf6ab394d66de40513e64525a748b8729a3` (branch `fix/fct-s3-retrieval-2026-11-28`, tip `21d44458a`);
  evidence `review-r1/review-r1.md` sha256 `216d1d76…` — **APPROVED_FOR_RELEASE_PREPARATION**.
- Assembly: `assembly.md` — release branch `release/2.58.263`, 5 cherry-picked commits (`-x`) + version bump.
  After cherry-picks the tree was byte-identical to the candidate (`git diff a50bcaf6a HEAD` empty).
- Base (deployed): `c0db22aa9` = 2.58.262.

## Identity

| Field | Value |
|---|---|
| pre-deploy HEAD | `c0db22aa957da51ea39e75b24de3e0dbdc8c1509` (2.58.262, detached) |
| deployed_sha (actual HEAD) | `4cdd72e17ef418c3901497dcce717d53bda1a62f` |
| product tip (bump) | `ed935443e587405d9e14425505d6f4f6b14b7e86` |
| evidence tip (HEAD) | `4cdd72e17` (docs-only; `git diff --name-only ed935443e HEAD` outside `plans/` = 0) |
| note on tip | this deploy-evidence commit itself (`dd4c9da23`, docs-only) was created **after** the restart and is **not** deployed; production stays at `4cdd72e17`, which is what the manifest records. Product bytes at both commits are identical. |
| previous | `c0db22aa9` / 2.58.262 |
| checkout | `git fetch --prune origin release/2.58.263` + `git checkout --detach 4cdd72e17` (fast-forward from `c0db22aa9`); tracked-dirty 0 |
| changed paths | 92 files; `chown adminbot:adminbot` + `644`, `umask 022`; unreadable by service user = 0; `IMPORT_OK 2.58.263` |
| manifest | `effect=deploy`, `version=2.58.263`, `deployed_sha=4cdd72e17…`, `previous_sha=c0db22aa9…`, `previous_version=2.58.262`, `dirty_tracked=false`, `schema=1`, `deployed_at=2026-11-27T21:52:29.576520Z`, `deployer=devops` |

Byte identity to the reviewed candidate: the 4 product blobs are exactly `a50bcaf6a` —
`services/factcheck_service.py` `3e056460162e…`, `factcheck_context.py` `f7bbe5991c91…`,
`param_catalog.py` `d4b0a884c738…`, `factcheck_planner.py` `2ba5df49e40d…`;
product delta `239+/22−`, DDL 0 (see `assembly.md`, `raw/identity.txt`).

## Version — three sources

`config/settings.py` `APP_VERSION = "2.58.263"`; local `http://127.0.0.1:8000/healthz` →
`{"status":"ok","version":"2.58.263"}`; public `https://admin-bot.duckdns.org/healthz` → same.

## Unit

`active/running`, MainPID 1115581, `NRestarts=0`, one process, ExecMainStart `2026-11-27 21:48:52 UTC`.

## Routes pin / bundle

- host `sha256(web/api/routes.py)` = `b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a`
  (= `ROUTES_SHA256_F11`, = base; routes not touched by this release).
- `web/app.js` disk `3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a` (2739459 B)
  = served `https://admin-bot.duckdns.org/web/app.js` `3631e82d…` (2739459 B).
- `/web/` HTTP 200.

## Schema and preserved settings (PostgreSQL `bot_settings`)

`user_version=49` (sqlite, read-only). No migrations, DDL Δ=0.

| Metric | Before | After |
|---|---|---|
| `bot_settings` rows | **549** (documented pre-state from the 2.58.262 deploy evidence) | **558** |
| rows untouched (`updated_at < deploy`) | — | **549** |
| rows written by this deploy | — | **9** — exactly `limits.factcheck_{claim_portion,excerpt_chars,max_queries_total,page_size,primary_fetches,refine_calls,retrieval_seconds,retrieval_seconds_max,search_text_chars}` |
| `category='prompts'` rows | 29 (2.58.262 evidence) | **29** |
| `limits.factcheck_*` rows | 5 (pre-existing group members) | **14** (5 + 9 new) |

The 9 new rows were seeded with the code canon, not invented values:
`retrieval_seconds=120.0`, `retrieval_seconds_max=600.0`, `refine_calls=24`,
`max_queries_total=64`, `search_text_chars=100000`, `page_size=20`, `claim_portion=32`,
`primary_fetches=2`, `excerpt_chars=600`.
Because the seed is `ON CONFLICT DO NOTHING` and only 9 rows have a post-deploy `updated_at`,
**no existing setting was rewritten**. Other settings could not be compared by md5 to the
2.58.262 value: the pre-deploy md5 read failed (the `postgres` OS/PG role does not exist here),
so preservation is proven by the row-level `updated_at` check above (549 rows untouched), not by a
hash pair.

## Seeds / effective config for the new owner parameters

- `services.param_catalog.REGISTRY` = **668** entries; group `limits_factcheck` holds exactly the 9
  new keys (`raw/group-check.txt`; types int/float, `per_chat=true`,
  `code_source=services.factcheck_planner.FACTCHECK_*`).
- `GET /api/config` on the live origin answers **401** without a valid Telegram `initData`
  (auth enforced; the endpoint is up). The response body was **not** read: no authorized TMA session
  is available to this agent in this environment, and minting `initData` would mean impersonating the
  owner — not done. Group contents are therefore proven from the same data source the route uses
  (catalog + `bot_settings` rows, values above), not from an HTTP 200 payload.
- Startup journal shows the existing factcheck migration path running as `no-op`
  (`[factcheck_wide_context_migration] уже применено — no-op`) and no config/catalog errors.

## Journal window (21:48:50 → 22:03:27 UTC, 14.6 min)

794 lines. HTTP 5xx = **0**; `Traceback` = **0**; `CRITICAL` = 0; `NameError` = **0**; `KeyError` = **0**;
factcheck lines = 3, of which errors = **0**.
`ERROR` = **2**, both pre-existing `services.anticliche_worker - [pipeline] event=pipeline_step
component=anticliche step=fetch/refresh` (`sources_unavailable` pattern seen in earlier releases,
unrelated to this delta). `truncated_reasoning` = 0 in this window.

## Rollback (dry-run only, not executed)

Temporary detached worktree of `c0db22aa9` + current manifest:
`tools/release_manifest.py --effect rollback --dry-run` → **rc=0**

```json
{ "deployed_at": "2026-11-27T21:53:24.426177Z", "deployed_sha": "c0db22aa957da51ea39e75b24de3e0dbdc8c1509",
  "dirty_tracked": false, "effect": "rollback", "previous_sha": "4cdd72e17ef418c3901497dcce717d53bda1a62f",
  "previous_version": "2.58.263", "schema": 1, "version": "2.58.262" }
```

DDL Δ=0 ⇒ rollback is code-only (`git checkout --detach c0db22aa9` + restart). Worktree removed
(no `worktree list` leftovers beyond the main checkout).

## Disk

`df -h /` 99G total / 51G used / **43G avail (54%)** — unchanged before/after.
`disk audit`: forecast `bytes_per_day=1694796759`, `projected_30d=50843902775 (47.4 GiB)`, top
category `jsonl_retention`. `disk cleanup --apply`: `deleted=0 bytes_freed=0 skipped=0 errors=0`
(deploy pool keep=2 satisfied). No database copy was made (DDL 0).

## Corrections made during the run (honest)

Two environment assumptions in the first script were wrong and were fixed in follow-up connections:
`postgres` OS/PG role does not exist (PostgreSQL runs in Docker `adminbot-postgres`; used
`$POSTGRES_USER/$POSTGRES_DB` inside the container), and the service venv is `/var/www/admin_bot/venv`
(not `.venv`). The manifest was therefore regenerated with the real interpreter, and the rollback
dry-run repeated as root after `git safe.directory` rejected the root-owned temp worktree. The first
run's raw output is kept verbatim (`raw/deploy-run-1.txt`) rather than rewritten.

## Limitations

- `GET /api/config` body not read (401 without owner TMA session); see above.
- No live Direct/factcheck user turn was triggered in the window; the functional change is covered by
  the deployed-code suites (`201 passed` on the assembled tree) and `IMPORT_OK`.
- FCT-192 remains REVIEW (S4 residual), out of this release by review.

## Artefacts

Created on production: standard `.deploy/release.json` (regenerated) and the restarted process only.
Removed: temp journal files (`/tmp/j26263_*`), temp rollback worktree `/tmp/rb263_probe`.
Verified: `pgrep -af 'rb263|j26263'` = 0, `/tmp` leftovers = 0, `git worktree list` = main only.
