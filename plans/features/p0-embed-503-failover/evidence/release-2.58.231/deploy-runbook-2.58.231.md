# Deploy runbook — 2.58.231 (P0-EMBED-503-FAILOVER postdeploy park + bounded spend-group probe)

Status: **REVIEW / READY_FOR_DEPLOY_PREPARATION — deploy only by separate authorization**. No deploy,
SSH, provider call, DB write or key/model/settings change was performed in this lane.
Production host `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`.
Old VPS `198.46.175.136` is decommissioned and is not a rollback target.

## 1. Preconditions

- Release branch `release/p0-embed-postdeploy-2.58.231`.
- Content tip (product/test bytes) `08d213b5f4456d609ffb01d2528d34d43de74c6d`: code cherry-pick
  `7171a227d93fdb990c591a65fc0a33bd110ce092` + evidence `fe5ab2c5e` + standard bump 2.58.230 → 2.58.231.
  Version 2.58.231, schema 48, DDL 0.
- Reviewed candidate: code `7171a227d`, tip `fe5ab2c5e`, review `postdeploy-fix-review-r1.md`
  (`APPROVED_FOR_RELEASE_PREPARATION`; D1/D2/D3 closed; N01/N02 nonblocking). Do not deploy an
  un-reviewed retry or the old 2.58.230 bytes.
- Rollback/base `d86bf66d408266c928e24714c2f5779a4ddf8ebe` (2.58.230, schema 48, DDL 0).
- Product scope: `services/embedding_control_plane.py`, `tests/test_p0_embed_503_failover.py`, the
  version wave and docs. No new flags, endpoints, migrations, prompts, models, indexes, UI or keys.
  Do not alter `.env`, persisted settings, chat overrides, embedding keys or model during the deploy.
- Keep the pre-deploy backup and the existing deploy-backup pool (`keep=2`); do not prune the rollback
  copy. Check free disk before any full DB copy; if space is insufficient, do not start the copy.
- SSH/fail2ban: one short recon connection; liveness over HTTPS (`/healthz`); no parallel connects and
  no auth retries in a loop.
- No reindex, no mass backfill, no cache flush and no forced 503 in this runbook.

## 2. Production preflight — embedding profiles + MSI (read-only, no secret values)

Record **only** alias, endpoint host/path, model, dimension, preprocessing, MSI/space, quota group and
key presence/source; **never** print key values, tokens, full headers or private text.

| Alias | Expected profile (forensic `postdeploy-2026-11-22.md`, deployed 2.58.230) |
|---|---|
| `primary` | `apinet.cloud` `/v1`, `gemini-embedding-001`, quota group `apinet_paid`, key present |
| `fallback_1` | `generativelanguage.googleapis.com` `/v1beta/openai`, `gemini-embedding-001`, quota group `google_free_1`, key present |
| `fallback_2` | `generativelanguage.googleapis.com` `/v1beta/openai`, `gemini-embedding-001`, quota group `google_free_2`, key present |

Checks:

1. Effective control plane: `EMBED_CONTROL_PLANE_ENABLED` ON; quota-group cooldown/parking/resume
   backoff/priority scheduler/adaptive concurrency ON; async batch OFF; admission ON. Record from the
   runtime process environment and `config.settings`.
2. Hot/persisted profiles and key presence for all three aliases; values distinct; source (hot/env)
   recorded without the secret. `_ATTEMPT_BUDGET=4`, provider-unavailable cooldown 60 s.
3. Model-space identity (MSI) from model/revision/dims/preprocessing for the configured profiles;
   confirm the live `graph_facts_vec` active generation and the profile MSI are equal (forensic MSI
   `e540d4ad890e121d` at 2.58.230). `conn`/PCI is provenance, not an admission gate.
4. Read-only backlog baseline **T0** immediately before the restart: `graph_facts` eligible,
   `graph_facts_vec` rows, eligible without vec, recent 24 h without vec, `smart_archive` source/vec,
   24 h `EMBED_API_DEFERRED` batches, `facts_text_only`. Forensic values at 2026-11-21 21:20Z (2.58.230)
   were: eligible 29,708; vec 31,814; missing 4,860; recent 24 h missing 1,463; deferred 37;
   `facts_text_only` 148. Use the actual pre-restart snapshot — these numbers shift with traffic.
5. `embedding_quota_state`: `google_free_1/google_free_2` expected `exhausted`,
   `next_allowed_at=2026-11-22T00:05:00Z`, note `parked kind=spend est=utc_day_end`; `primary` and the
   `fallback_*` group rows are historical/past. Do not edit these rows.
6. `apinet` remains an external 503 source; Google keys were live 200/3072 at 21:22Z even though the
   process considered both groups exhausted. Do not rotate keys and do not change the model.
7. Deployment evidence must use the actual authorized SHA. The content tip is `08d213b5f`; if the
   docs evidence commit is checked out, the host manifest records that HEAD and the product/test diff
   from `08d213b5f` must be empty.

## 3. Deploy steps (only after separate deploy authorization)

1. Check free disk space; keep the current rollback copy.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (or checkout the authorized release commit).
4. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION`
   reads `2.58.231`; `git rev-parse HEAD` equals the authorized release SHA; the product/test diff from
   `08d213b5f` is empty.
5. Make the pre-deploy DB backup with the existing deploy-backup mechanism (keep the rollback copy).
6. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no
   `--dry-run`). Confirm `version=2.58.231`, `effect=deploy`, `dirty_tracked=false`, `previous_sha`
   equals the previously deployed 2.58.230 SHA (`d86bf66d4…`), and `deployed_sha` is the actual host HEAD.
7. `sudo systemctl restart admin_bot`
8. Immediately run §4 and §5. Do not declare VERIFIED from this runbook alone; record the deployed SHA,
   effective configuration and actual observations.

## 4. Postdeploy checks (read-only unless explicitly noted)

| Check | Expected |
|---|---|
| Local HTTP (on host, bypassing the proxy) | local `/healthz` returns 200 |
| Public HTTP `https://<host>/healthz` | 200 (proves TLS/proxy layer too) |
| Version | `APP_VERSION` reads `2.58.231` |
| Checkout identity | `git -C /var/www/admin_bot rev-parse HEAD` equals the manifest `deployed_sha` **exactly** (string equality, not prefix) |
| Deployed identity | existing identity probe reports `code=verified_deployed`; any other code is recorded honestly, not assumed success |
| Product diff | `git -C /var/www/admin_bot diff --name-only 08d213b5f..HEAD -- services handlers config web migrations database.py prompts` is empty (docs commits may differ) |
| Schema | `user_version=48`; `schema_migrations` max/count 48; no migration/DDL applied |
| Process | exactly one bot process; `systemctl show -p NRestarts admin_bot` shows no new automatic restart after the deploy restart |
| Journal | `journalctl -u admin_bot --since <deploy time>` has no new fatal startup/migration/traceback entries |
| Settings/flags | effective values, persisted settings and chat overrides preserved; no new flags |
| Prompts/profiles (digests) | effective prompt/settings documents have the **same digests** before and after the restart; this release has no prompt change |
| Embedding profiles | all three aliases still present with the same host/model/quota group; keys present, not printed; no key/model change |
| MSI/space | active `graph_facts_vec` generation and current profile MSI are equal; `conn`/PCI recorded as provenance only |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); free space adequate |
| Temp artifacts | no probe DB, snapshot copy or test output left on production beyond the declared evidence (P0-PROD-DISK-01) |

## 5. Post-deploy embedding recovery proof (minimal, bounded, once)

Purpose: observe the deployed corrective once — the park/deferral and the bounded spend-group probe —
not to re-test providers or repair apinet. No mass checks, reindexing, cache flush, key rotation,
model change or full backfill.

1. **Why the restart matters.** `credential_health` is in-memory only; the restart clears the day-long
   credential cooldown left by the 18:39Z spend-429. Persisted `embedding_quota_state` stays
   `exhausted` until `00:05Z` with note `parked kind=spend est=utc_day_end`; `load_group_states()`
   restores that note. Do **not** edit `embedding_quota_state` or any credential health by hand.
2. **Expected probe path.** `MemoryManager.initialize()` performs a P2 `_embed(["probe"])`; if `"probe"`
   is not in the embed cache the sequence is: primary 503 **once** → primary parked → exactly one probe
   of the first spend-parked Google group (`google_free_1`) → live 200 → `embed group probe recovered |
   group=google_free_1` → `set_group_state(healthy, probe_ok)` → `fire_and_forget` backfill. If init
   does not fire it, the first `embed_recovery_tick` (≤600 s) with backlog > 0 performs the same
   bounded P2 path. The probe throttle is **per group / 900 s**, not global; `google_free_2` may remain
   parked — one healthy leg is sufficient.
3. **Real vector + semantic KNN proof (required).** Record T0 `graph_facts_vec` rows before the restart,
   then T1 after the backfill: the counter must **increase** above T0 (forensic 2.58.230 baseline:
   31,814 with 4,860 eligible facts missing). Take one fact that was just backfilled (or one existing
   text-only fact recovered through the same path) and run the deployed read-only KNN:
   `SELECT fact_id FROM graph_facts_vec WHERE embedding MATCH ? AND k = ?`; the returned id must be the
   backfilled/new fact id. Do not count an HTTP 200 as proof. Record the alias/host that served, MSI,
   vector length, `graph_facts` eligible without vec before/after and the 24 h deferred/text-only
   counters. A decrease is observation, not attribution to one call.
4. **Journal expectations.** One `embed transport error | alias=primary` for the operation (not a
   series of four), one Google probe line, `embed group probe recovered`, then backfill/`re-embedded`
   activity; no `embed rate limit` spam; no repeated primary 503 per logical operation. Record the
   actual lines, not a paraphrase.
5. **Honest external failure.** If Google returns 429/5xx during the probe, the group stays parked, the
   credential gets its cooldown, no retry happens inside the operation, and the next attempt is not
   earlier than 900 s. Report the actual status class as external degradation and do **not** claim
   VERIFIED or a fixed Google quota. `apinet` 503 remains external and is not declared fixed.
6. **Prohibitions.** No manual group-state/credential edits, no model/key/settings changes, no reindex
   or mass embed, no forced 503, no retry loop to “prove” fallback, no LLM chat calls. At most one
   bounded probe/backfill cycle and one controlled KNN query. If no safe single-row write path exists,
   record observation only and do not claim semantic restoration.
7. **N01 caveat.** In the **same process** after a future spend-429, the probe does not bypass the
   credential cooldown; recovery then waits for cooldown expiry. That is not universal self-heal and
   must not be reported as such. N02: multi-key-per-group probing is not covered live (prod has one key
   per Google group).

Stop conditions: any fatal startup/migration/traceback, identity mismatch, schema/DDL change,
key/model/settings change, unexpected mass embed traffic, a provider call that is not the single
bounded probe, or a regressed previously verified path. Roll back if the deployed bytes/identity do
not match.

## 6. Rollback

- Code rollback target: `d86bf66d408266c928e24714c2f5779a4ddf8ebe` (2.58.230, schema 48, DDL 0).
- No migration/data action is required. In-memory credential/group-probe state is not reverted; text-only
  rows and persisted `embedding_quota_state` written by ordinary traffic remain.
- After rollback: verify local/public health, identity, `APP_VERSION=2.58.230`, schema 48/DDL 0,
  `NRestarts`, journal, unchanged embedding profiles/keys/settings, and remove temporary probe artifacts.
  Do not delete the deploy backup or probe evidence before the rollback is verified.
