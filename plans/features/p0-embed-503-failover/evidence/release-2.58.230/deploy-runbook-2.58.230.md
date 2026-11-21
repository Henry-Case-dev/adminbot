# Deploy runbook — 2.58.230 (P0-EMBED-503-FAILOVER)

Status: **REVIEW — assembly complete, ready for independent release review and a separately authorized
deploy**. No deploy, SSH, provider call, DB write or key/model change was performed in this lane.
Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`.
Old VPS `198.46.175.136` is decommissioned and is not a rollback target.

## 1. Preconditions

- Release branch `release/p0-embed-503-failover-2.58.230`; content tip in this assembly
  `9d5cf5173fcf835974205aeeef373766b14a18bd` (code `4ace0a3ae` cherry-picked, evidence cherry-picks,
  standard bump). Version 2.58.230, schema 48, DDL 0. The evidence commit after the content tip is docs-only.
- Reviewed candidate `4ace0a3ae` (evidence tip `d00a01b07`, `fix/embed-503-failover`, base `374dc6060`);
  review r1 on master `373a39615` = `APPROVED_FOR_RELEASE_PREPARATION`; live-route evidence `f2540ac60`.
- Rollback/base `94e227a2c096f4cc7b987c3253563bf0df442d17` (2.58.229, schema 48, DDL 0).
- Product scope is exactly `services/embedding_control_plane.py`, `services/summary_memory.py` and the new
  `tests/test_p0_embed_503_failover.py`; `config/settings.py` changes only APP_VERSION/changelog. No new
  flags, endpoints, migrations, prompts, models, indexes, UI or key changes. Do not alter `.env`, persisted
  settings, chat overrides or embedding keys/model during the deploy.
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy. Check free
  disk space before any backup/copy; if space is insufficient, do not start a full DB copy.
- SSH/fail2ban: one short recon connection is enough; check liveness over HTTPS (`/healthz`); no parallel
  connects, no auth retries in a loop.

## 2. Production preflight — embedding config profiles (read-only, no secret values)

Run on the host through the existing config access. Record **only** alias, endpoint host/path, model,
quota group and key presence/source; **never** print key values, tokens, full headers or private text.

| Alias | Expected profile (from live-route evidence `f2540ac60`, 2.58.228) |
|---|---|
| `primary` | `apinet.cloud` `/v1`, `gemini-embedding-001`, quota group `apinet_paid`, key present |
| `fallback_1` | `generativelanguage.googleapis.com` `/v1beta/openai`, `gemini-embedding-001`, quota group `google_free_1`, key present |
| `fallback_2` | `generativelanguage.googleapis.com` `/v1beta/openai`, `gemini-embedding-001`, quota group `google_free_2`, key present |

Checks:

1. Effective control-plane switch and cooldowns: read `EMBED_CONTROL_PLANE_ENABLED` (default ON),
   cooldown/priority/adaptive values, async batch OFF; confirm from the runtime process environment and
   `config.settings`, not from a guessed default.
2. Hot/persisted embedding profile rows and key presence are present for all three aliases; values are
   distinct (`primary != fallback_1 != fallback_2`); source is recorded (hot/env) without the secret.
3. `resolve_index_compat(graph_facts_vec)` is `compatible`, `serviceable=true` for the configured primary
   identity; do not “fix” a failing gate by writing admission rows.
4. Existing text-only backlog baseline (read-only; use the deployed
   `services.embedding_control_plane.embeddings_backlog_panel` or equivalent read-only query):
   `graph_facts` eligible, `graph_facts_vec` rows, missing eligible, missing recent 24 h, `smart_archive`
   source/vec rows, 24 h `EMBED_API_DEFERRED` batches and `facts_text_only`. Record T0 before restart.
5. `apinet` remains an external 503 source. Do not declare it fixed by this deploy, and do not use the
   deploy to test keys or rotate them.

## 3. Deploy steps (only after separate deploy authorization)

1. Check free disk space; keep the current rollback copy.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (or checkout the authorized release commit).
4. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION`
   reads `2.58.230`; `git rev-parse HEAD` equals the authorized release SHA.
5. Make the pre-deploy DB backup with the existing deploy-backup mechanism (keep the current rollback copy).
6. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no
   `--dry-run`). Confirm `version=2.58.230`, `effect=deploy`, `dirty_tracked=false`, `previous_sha` equals
   the previously deployed 2.58.229 SHA (`94e227a2c…`).
7. `sudo systemctl restart admin_bot`
8. Immediately run §4 and §5. Do not declare VERIFIED from this runbook alone; record the deployed SHA,
   effective configuration and actual observations.

## 4. Postdeploy checks (all read-only)

| Check | Expected |
|---|---|
| Local HTTP (on host, bypassing the proxy) | local `/healthz` returns 200 |
| Public HTTP `https://<host>/healthz` | 200 (separate row: proves TLS/proxy layer too) |
| Version | `APP_VERSION` reads `2.58.230` |
| Checkout identity | `git -C /var/www/admin_bot rev-parse HEAD` equals the manifest `deployed_sha` **exactly** (string equality, not prefix) |
| Deployed identity | existing identity probe reports `code=verified_deployed`; any other code is recorded honestly, not assumed success |
| Schema | `user_version=48`; `schema_migrations` max/count 48; no migration/DDL applied |
| Process | `systemctl show -p NRestarts admin_bot` shows no new automatic restart after the deploy restart |
| Journal | `journalctl -u admin_bot --since <deploy time>` has no new fatal startup/migration/traceback entries |
| Settings/flags | existing effective values, persisted settings and chat overrides preserved; no new flags |
| Prompts/profiles (digests) | effective prompt/settings documents have the **same digests** before and after the restart; this release has no prompt/write path |
| Embedding profiles | all three aliases still present with the same host/model/quota group; keys present, not printed; no key/model change |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); free space adequate; remove temporary probe files |
| Temp artifacts | no probe DB, snapshot copy or test output left on production beyond the declared evidence |

## 5. Post-deploy live embedding check (minimal, bounded)

Purpose: observe the **deployed control plane** once, not to re-test providers or repair apinet. Do not run
mass checks, reindexing, backfill, cache flushes, key rotation or model changes.

1. Make **one** minimal logical embedding call through the deployed control plane (the deployed
   `get_executor(...).embed([...])` path or the app's existing embedding entrypoint), neutral short ASCII
   text, one text, no manual retry loop, bounded wait/timeout. The candidate’s failover must be allowed to
   select the next independent leg only if the previous leg returns 5xx/timeout.
2. Record: UTC time, `last_served_credential()` alias/provider/model/host/quota group, HTTP status/class,
   vector length and latency. **Do not** force a 503 or repeat the call to “prove” fallback. If primary
   succeeds, record that primary served; if fallback serves, record the actual alias and do not claim
   apinet is fixed. A 503 on every leg is an honest failure and must not be rewritten as success.
3. Read the same read-only backlog counters as preflight T0 (graph/archive missing eligible, recent missing,
   deferred batches/facts_text_only) and record T1. Counts are observation only; do not attribute a
   decrease to this one call.
4. Only if the deployed build exposes a **safe bounded** `embed_recovery_tick` (hard batch/time limit,
   idempotent, no key/model change, no mass reindex) may one bounded run be executed. Otherwise do not run
   recovery/backfill; record that only observation was possible.
5. Google PCI admission remains **unproven** unless a durable compatible verdict for the actual Google
   connection is obtained through the existing canary/probe/admission mechanism. A live 200/3072 vector is
   functional evidence, not admission. Do not write admission rows by hand and do not mix `SCN-01`/402
   scenarios with this release.

Stop conditions: any fatal startup/migration/traceback, identity mismatch, schema/DDL change, key/model
change, unexpected mass embed traffic, or a provider call that is not the single bounded probe. Roll back to
`94e227a2c` if the deployed bytes or identity do not match, or if the release introduces a regression in an
already-verified path.

## 6. Rollback

- Code rollback target: `94e227a2c096f4cc7b987c3253563bf0df442d17` (2.58.229, schema 48, DDL 0).
- No migration/data action is required. Runtime embedding cooldown state and text-only rows written by
  ordinary traffic are not reverted by a code rollback.
- After rollback: verify local/public health, identity, `APP_VERSION=2.58.229`, schema 48/DDL 0,
  `NRestarts`, journal, and that the embedding profiles/keys/settings are unchanged. Do not delete the
  deploy backup or probe evidence before the rollback is verified.
