# Deploy runbook — 2.58.227 (LVS L1 discovery: partial NanoGPT catalog card)

Status: **REVIEW**, no deploy performed in this assembly. Production host:
`192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`.
Old VPS `198.46.175.136` is decommissioned and is not a rollback target.

## 1. Preconditions

- Release branch: `release/lvs-l1-discovery-2.58.227`; content tip in this
  assembly: `ef204bb8369f4e1d85db8670fb1ce8407a0dfc31` (bump on product
  `77d863eb89c15f8dda27edd1568bf7e7a273896d`; version 2.58.227, schema 48,
  DDL 0). The evidence commit after the content tip is docs-only.
- Reviewed candidate: `77d863eb8` (`fix/lvs-l1-discovery`), review artifact on
  master `40638708c`, verdict `APPROVED_FOR_RELEASE_PREPARATION`.
- Rollback/base: `1cc019ad55bd26f465353ba97588cfc28ead859b` (2.58.226,
  schema 48, DDL 0).
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune
  the rollback copy. Check free disk space before any backup/copy.
- No new flags, store, embedding, LLM prompt, hot-config, migration or DDL.
  Do not alter `.env`, persisted settings or chat overrides.
- B3 (`web/*`), the P0 harness and unrelated tasks are not in this branch and
  must not be added or deployed with this release.
- SSH/fail2ban: one short recon connection is enough; check liveness over HTTPS
  (`/healthz`), do not retry auth in a loop or run parallel connection attempts.

## 2. Deploy steps (only after separate deploy authorization)

1. Check free disk space before any backup/copy; do not start a full DB copy if
   space is insufficient.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (or checkout the authorized
   release commit). The evidence commit after the content tip is docs-only; the
   deployed SHA shown by the manifest is the actual checked-out SHA.
4. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no`
   is empty; `APP_VERSION` reads `2.58.227`.
5. Make the pre-deploy DB backup with the existing deploy-backup mechanism
   (keep the current rollback copy).
6. Record the actual checkout manifest **before** restart:
   `python tools/release_manifest.py` (no `--dry-run`). Confirm
   `version=2.58.227`, `effect=deploy`, `dirty_tracked=false`, and
   `previous_sha` is the previously deployed 2.58.226 SHA.
7. `sudo systemctl restart admin_bot`
8. Immediately run the checks below. Do not declare VERIFIED from this runbook
   alone; record deployed SHA, effective configuration and actual observations.

## 3. Postdeploy checks

Every row below is **read-only**: no test message, no synthetic question, no
probe that writes to a chat, the DB or the prompt store.

| Check | Expected |
|---|---|
| Local HTTP (on host, bypassing the proxy) | local `/healthz` returns 200 |
| Public HTTP `https://<host>/healthz` | 200 (separate row: proves the TLS/proxy layer too, not just the app process) |
| Version | `APP_VERSION` reads `2.58.227` |
| Checkout identity | `git -C /var/www/admin_bot rev-parse HEAD` equals the manifest `deployed_sha` **exactly** (string equality; a prefix match is not enough) |
| Deployed identity | existing identity probe reports `code=verified_deployed` (manifest/HEAD/version/process-start agree, `dirty=false`); any other code (`local_unverified`, `mismatch`, `unknown`, `unavailable`) is recorded honestly and not assumed to mean success |
| Schema | `user_version=48`; `schema_migrations` max/count 48; no migration/DDL applied |
| Process | `systemctl show -p NRestarts admin_bot` shows no new automatic restart after the deploy restart |
| Journal | `journalctl -u admin_bot --since <deploy time>` has no new fatal startup/migration/traceback entries |
| Settings/flags | existing effective values, persisted settings and chat overrides preserved; no new flags in this release |
| Prompts/profiles (digests) | effective prompt documents and overrides (read-only via the existing `prompt_readback` view and the registry ledger) plus persisted settings documents have the **same digests** before and after the restart; this release contains no prompt/write path |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); free space is adequate; remove temporary probe files |
| Temp artifacts | no probe DB, snapshot copy or test output left on production beyond the declared evidence |

### 3.1 Behavioral acceptance — confirmed pre-deploy, never by live probing

**Do not send test messages to the working chats and do not run any live-chat
check** after the deploy: no "test chat", no probe message, no synthetic
question in a real chat.

The L1 discovery behavior of this delta was confirmed **before** the deploy by
the reviewed tests and the independent probe on candidate `77d863eb8`, and the
same bytes plus the version pin are reproduced in this branch. The deploy is
accepted through **deployed-byte identity**, not through new production probing:

```
git -C /var/www/admin_bot rev-parse HEAD            # == manifest deployed_sha
git -C /var/www/admin_bot diff --name-only <content-tip>..HEAD -- \
    services config handlers web database.py migrations prompts
```

must be empty (the release evidence commit on top of the content tip is
docs-only). If that diff is not empty, the running bytes are not the accepted
bytes: stop and escalate instead of "verifying" the behavior on production.

| Check | Where confirmed | Expected |
|---|---|---|
| Partial NanoGPT card (output only) | reviewed candidate tests + probe (identical product bytes) | window stays `estimated_unknown` 1M with `window_estimated=true`; `max_output_tokens` is the real catalog value (e.g. 4096); `max_output_source=provider_catalog`; no fabricated `context_length` |
| Partial card (capabilities only) | same | real reasoning/tools/json caps preserved; window remains an honest estimate; model not substituted or disabled |
| Partial card (output field only) | same | declared `output_token_field`/`output_field_source=provider_catalog` preserved; output absent honestly when not declared |
| Full card with window | same | full catalog window remains `verified` and still takes precedence over a partial card; registry/override/proven precedence unchanged |
| Empty/unknown card | same | honest discovery miss; L1 route remains usable with model unchanged, `context_source=estimated_unknown`, timeout 180/deadline 360 |
| Cache/key path | same | cache key unchanged; repeated resolve uses the existing TTL; no new HTTP/LLM/DB path |
| L1 route budgets | same | partial output correctly bounds the L1 response budget; no 512/15 fallback; no new global state/locks |

Live rows **LVS-L1-32**, **LVS-OUT-01..05** and **LVS-EXEC-09** are **not**
covered by this runbook; they require a separate live/provider close-out and are
not claimed here. The external provider HTTP **402** limitation is likewise
unchanged and is not a pass.

## 4. Rollback

1. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is
   empty; preserve untracked runtime data. Do not delete user data, backups or
   unknown files.
2. `git -C /var/www/admin_bot reset --hard 1cc019ad55bd26f465353ba97588cfc28ead859b`
   (or an equivalent authorized checkout of the same commit).
3. `python tools/release_manifest.py --effect rollback`
4. `sudo systemctl restart admin_bot`
5. Verify `/healthz` 200, version `2.58.226`, schema 48, settings unchanged and
   no new journal errors.
6. Data action: none. 2.58.227 has DDL 0 and schema 48; do not run schema
   downgrades or delete user data. Keep the pre-deploy backup and rollback copy
   until the release is stable.

## 5. Known residual / limitations

- This assembly is REVIEW only: no production deploy, no live Telegram/provider
  check, no VERIFIED claim.
- Post-deploy is read-only by contract (§3.1): no test messages in working chats
  and no live-chat probing; behavioral confirmation stays with the pre-deploy
  reviewed tests/probe plus deployed-byte identity.
- Pre-existing test failures listed in `assembly.md`/`tests-2.58.227.json` are not
  caused by this delta and are not counted as passes.
- Review non-blocking `LVS-L1-R1-N01..N04` remain `BACKLOG_ONLY`; no code change
  here.
- B3 (`web/*`), the P0 harness and unrelated tasks are intentionally excluded.
- No UI/visual change: this delta is backend capacity discovery plus tests, so
  no Playwright/Browser Use run is required for release preparation.
