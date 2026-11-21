# Deploy runbook — 2.58.230 (P0-EMBED-503-FAILOVER, c5 MSI admission)

Status: **REVIEW / READY_FOR_DEPLOY_PREPARATION — c5 seam APPROVED_FOR_DEPLOY, release branch rerun
complete; deploy only by separate authorization**. No deploy, SSH, provider call, DB write or key/model
change was performed in this lane.
Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`.
Old VPS `198.46.175.136` is decommissioned and is not a rollback target.

## 1. Preconditions

- Release branch `release/p0-embed-503-failover-2.58.230`.
- Content tip (product/test bytes) `f90c0e59357be6c7728251bbd19b323bef5630f0`: c5 code cherry-pick
  `1b7d4bf0471a10aaff5d4f0c40eacd77f707727d` on top of the c1 failover + 2.58.230 bump. Version 2.58.230,
  schema 48, DDL 0. Evidence/review commits above the content tip are docs-only.
- Reviewed c5: code `1b7d4bf`, branch head `5fa47ec00eeb8f892abee13310f2ae48ea046bef` (parent
  `d00a01b07`); review addendum `428843093` = `APPROVED_FOR_DEPLOY` for the c5 seam. `REL230-F1` closed by
  MSI admission. The prior PCI-bound candidate must **not** be deployed.
- Rollback/base `94e227a2c096f4cc7b987c3253563bf0df442d17` (2.58.229, schema 48, DDL 0).
- Product scope: `services/embedding_control_plane.py`, `services/summary_memory.py` (docstring only in
  c5), `tests/test_p0_embed_503_failover.py`, `tests/test_p0_embed_admission_msi.py`,
  `tests/test_embed_identity_compat.py`, `tests/test_embed_identity_compat_restart_legacy.py`.
  No new flags, endpoints, migrations, prompts, models, indexes, UI or key changes. `config/settings.py`
  carries only the already-reviewed 2.58.230 version stamp. Do not alter `.env`, persisted settings, chat
  overrides, embedding keys or model during the deploy.
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy. Check free
  disk space before any backup/copy; if space is insufficient, do not start a full DB copy.
- SSH/fail2ban: one short recon connection is enough; check liveness over HTTPS (`/healthz`); no parallel
  connects, no auth retries in a loop.

## 2. Production preflight — embedding profiles + MSI (read-only, no secret values)

Record **only** alias, endpoint host/path, model, dimension, preprocessing, MSI/space, quota group and
key presence/source; **never** print key values, tokens, full headers or private text.

| Alias | Expected profile (from live-route evidence `f2540ac60`, 2.58.228) |
|---|---|
| `primary` | `apinet.cloud` `/v1`, `gemini-embedding-001`, quota group `apinet_paid`, key present |
| `fallback_1` | `generativelanguage.googleapis.com` `/v1beta/openai`, `gemini-embedding-001`, quota group `google_free_1`, key present |
| `fallback_2` | `generativelanguage.googleapis.com` `/v1beta/openai`, `gemini-embedding-001`, quota group `google_free_2`, key present |

Checks:

1. Effective control-plane switch/cooldowns: read `EMBED_CONTROL_PLANE_ENABLED` (default ON), cooldown/
   priority/adaptive values, async batch OFF — from the runtime process environment and `config.settings`.
2. Hot/persisted profile rows and key presence for all three aliases; values distinct
   (`primary != fallback_1 != fallback_2`); source recorded (hot/env) without the secret.
3. Compute/record the model-space identity (MSI) from model/revision/dims/preprocessing for the configured
   profiles. Confirm the live `graph_facts_vec` active generation space and the current profile MSI are the
   same before the deploy (`e540d4ad890e121d` in the 2.58.228 evidence). `conn`/PCI is provenance only.
4. Read-only backlog baseline T0: `graph_facts` eligible, `graph_facts_vec` rows, missing eligible,
   missing recent 24 h, `smart_archive` source/vec rows, 24 h `EMBED_API_DEFERRED` batches and
   `facts_text_only`. Use the deployed `services.embedding_control_plane.embeddings_backlog_panel` or
   equivalent read-only query.
5. `apinet` remains an external 503 source. Do not declare it fixed, do not rotate keys or change the model.
6. Deployment evidence must use the actual authorized SHA. The content tip is `f90c0e593`; if a later
   docs-only evidence/review commit is checked out, the host manifest records that HEAD and the product diff
   from `f90c0e593` must be empty.

## 3. Deploy steps (only after separate deploy authorization)

1. Check free disk space; keep the current rollback copy.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (or checkout the authorized release commit).
4. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION`
   reads `2.58.230`; `git rev-parse HEAD` equals the authorized release SHA; the product/test diff from
   `f90c0e593` is empty.
5. Make the pre-deploy DB backup with the existing deploy-backup mechanism (keep the current rollback copy).
6. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no
   `--dry-run`). Confirm `version=2.58.230`, `effect=deploy`, `dirty_tracked=false`, `previous_sha` equals
   the previously deployed 2.58.229 SHA (`94e227a2c…`), and that `deployed_sha` is the actual host HEAD.
7. `sudo systemctl restart admin_bot`
8. Immediately run §4 and §5. Do not declare VERIFIED from this runbook alone; record the deployed SHA,
   effective configuration and actual observations.

## 4. Postdeploy checks (read-only unless explicitly noted)

| Check | Expected |
|---|---|
| Local HTTP (on host, bypassing the proxy) | local `/healthz` returns 200 |
| Public HTTP `https://<host>/healthz` | 200 (separate row: proves TLS/proxy layer too) |
| Version | `APP_VERSION` reads `2.58.230` |
| Checkout identity | `git -C /var/www/admin_bot rev-parse HEAD` equals the manifest `deployed_sha` **exactly** (string equality, not prefix) |
| Deployed identity | existing identity probe reports `code=verified_deployed`; any other code is recorded honestly, not assumed success |
| Product diff | `git -C /var/www/admin_bot diff --name-only f90c0e593..HEAD -- services handlers config web migrations database.py prompts` is empty (docs-only commits may differ) |
| Schema | `user_version=48`; `schema_migrations` max/count 48; no migration/DDL applied |
| Process | `systemctl show -p NRestarts admin_bot` shows no new automatic restart after the deploy restart |
| Journal | `journalctl -u admin_bot --since <deploy time>` has no new fatal startup/migration/traceback entries |
| Settings/flags | existing effective values, persisted settings and chat overrides preserved; no new flags |
| Prompts/profiles (digests) | effective prompt/settings documents have the **same digests** before and after the restart; this release has no prompt change |
| Embedding profiles | all three aliases still present with the same host/model/quota group; keys present, not printed; no key/model change |
| MSI/space | active `graph_facts_vec` generation and current profile MSI are equal; `conn`/PCI is recorded as provenance, not used as an admission gate |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); free space adequate; remove temporary probe files |
| Temp artifacts | no probe DB, snapshot copy or test output left on production beyond the declared evidence |

## 5. Post-deploy live embedding check (minimal, bounded; vector + semantic proof)

Purpose: observe the **deployed** c5 path once, not to re-test providers or repair apinet. Do not run mass
checks, reindexing, cache flushes, key rotation, model changes or a full backfill.

1. Make **one** minimal logical embedding call through the deployed control plane (the deployed
   `get_executor(...).embed([...])` path or the app's existing embedding entrypoint), neutral short ASCII
   text, one text, no manual retry loop, bounded wait/timeout. Failover to the next independent leg is
   allowed only on 5xx/timeout.
2. Record UTC time, `last_served_credential()` alias/provider/model/host/quota group, HTTP status/class,
   vector length and latency. Do not force a 503 or repeat the call to “prove” fallback. If primary
   succeeds, record primary; if fallback serves, record the actual alias and do not claim apinet is fixed.
3. **Semantic/vector proof (required by c5):** using the existing deployed write/read path, prove at most one
   new fact or one existing text-only fact receives a real vector and is found by the real sqlite-vec KNN
   query — not merely an HTTP 200. A safe bounded check may:
   - use one existing text-only fact and the existing recovery/backfill path, or
   - insert one neutral controlled fact through the normal memory write path,
   then run one `SELECT fact_id FROM graph_facts_vec WHERE embedding MATCH ? AND k = ?` (or the deployed
   equivalent) and record the returned id, `graph_facts_vec` count change, alias/host and MSI.
   If no safe single-row path exists, record observation only and do **not** claim semantic restoration.
   Do not mass-embed, do not reindex, do not alter rows outside the one controlled fact.
4. Read the same read-only backlog counters as T0 (graph/archive missing eligible, recent missing,
   deferred batches/facts_text_only) and record T1. Counts are observation; do not attribute a decrease to
   one call.
5. Only if the deployed build exposes a **safe bounded** `embed_recovery_tick` (hard batch/time limit,
   idempotent, no key/model change, no mass reindex) may one bounded run be executed. Otherwise do not run
   recovery/backfill beyond the single controlled row in step 3; record that only observation was possible.
6. Do not claim Google PCI admission. c5's contract is MSI/model-space equality; `conn` is provenance. A
   live 200/3072 vector is functional evidence; the semantic KNN hit is the product proof. Do not mix
   `SCN-01`/402 scenarios with this release.

Stop conditions: any fatal startup/migration/traceback, identity mismatch, schema/DDL change, key/model
change, unexpected mass embed traffic, or a provider call that is not the single bounded probe. Roll back to
`94e227a2c` if the deployed bytes/identity do not match, or if a previously verified path regresses.

## 6. Rollback

- Code rollback target: `94e227a2c096f4cc7b987c3253563bf0df442d17` (2.58.229, schema 48, DDL 0).
- No migration/data action is required. Runtime embedding cooldown state and text-only rows written by
  ordinary traffic are not reverted by a code rollback.
- After rollback: verify local/public health, identity, `APP_VERSION=2.58.229`, schema 48/DDL 0,
  `NRestarts`, journal, and that the embedding profiles/keys/settings are unchanged. Do not delete the
  deploy backup or probe evidence before the rollback is verified.
