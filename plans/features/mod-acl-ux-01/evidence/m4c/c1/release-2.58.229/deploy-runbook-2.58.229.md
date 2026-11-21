# Deploy runbook — 2.58.229 (MOD-ACL-UX-01 M4C C1)

Status: **REVIEW — do not deploy yet**. Production host `192.255.209.205`, checkout `/var/www/admin_bot`,
unit `admin_bot`. Old VPS `198.46.175.136` is decommissioned and is not a rollback target.

Open blocker before step 2: **`REL-229-PIN-01`** (see `assembly.md` §6). The C1 `web/api/routes.py` change needs the
conscious `ROUTES_SHA256_F11` re-pin and a Reviewer addendum. If that produces an additional commit, the SHA and
digests below no longer describe the deployed tree: re-run the assembly checks and update this runbook first.

## 1. Preconditions

- Release branch `release/mod-acl-m4c1-2.58.229`; content tip in this assembly `95485a609aeb559ffe88531635f345a3528f026b`
  (standard bump on the cherry-picked C1 product `3fdd560e9`; version 2.58.229, schema 48, DDL 0).
  The evidence commit after the content tip is docs-only.
- Reviewed candidate `eb305b6fe` (evidence tip `83a38a5be`, `feat/mod-acl-m4c1`); review addendum on master
  `b2f3d1889`, `APPROVED_FOR_RELEASE_PREPARATION` (F01/F02/F03 resolved, 18 C1 rows VERIFIED-eligible, SCN-01 RFL).
- Rollback/base `374dc60609986a9250170a34a48c93bf2ba85e29` (2.58.228, schema 48, DDL 0).
- Product bytes are byte-identical to the reviewed candidate (`git diff 83a38a5be 95485a609 -- web services` empty):
  `app.js 59a583fc…`, `index.html db30ba90…`, `app.css 8a55ed9d…`.
- No new flags, store, embedding, LLM prompt, hot-config, migration or DDL. Do not alter `.env`, persisted settings
  or chat overrides.
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy. Check free disk
  space before any backup/copy.
- SSH/fail2ban: one short recon connection is enough; check liveness over HTTPS (`/healthz`); no parallel connects,
  no auth retries in a loop.

## 2. Production preflight 6.4 — read-only `bot_roles` / `bot_admins`

Run on the host through the existing DB access, **read-only**, before any deploy step. No inserts, no updates,
no schema changes. Record the output verbatim in the deploy log.

```sql
-- (a) built-in role model: expect exactly 4 rows, all is_custom = false
SELECT role_name, is_custom, role_type, permissions
FROM bot_roles ORDER BY role_name;

-- (b) assignments: expect 3 rows
SELECT count(*) AS admins_total FROM bot_admins;

-- (c) custom role with access-section rights: expect 0 rows
SELECT role_name, permissions FROM bot_roles
WHERE is_custom
  AND (permissions->>'wildcard' = 'true'
       OR COALESCE(permissions->'sections', '[]'::jsonb) @> '["access"]'::jsonb);
```

Expected baseline: 4 built-in roles `admin` (`wildcard`, `global_admin`), `moderator`, `user`, `local_admin`
(`sections`: limits/flags/reactions/content/chat_lore); 3 assignments; query (c) returns no rows.

**Trigger:** if query (c) returns any row, a custom role with access rights exists on production — **stop** and run
**S1** (security review of the C1 read path and of that role's assignments) before any deploy. Do not “fix” it by
deleting rows during the deploy.

Repeat (b) after the restart; the count must be unchanged by the deploy (the deploy writes no `bot_admins` rows).

## 3. Deploy steps (only after separate deploy authorization and REL-229-PIN-01 closed)

1. Check free disk space before any backup/copy; do not start a full DB copy if space is insufficient.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (or checkout the authorized release commit).
4. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION` reads `2.58.229`.
5. Make the pre-deploy DB backup with the existing deploy-backup mechanism (keep the current rollback copy).
6. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no `--dry-run`).
   Confirm `version=2.58.229`, `effect=deploy`, `dirty_tracked=false`, `previous_sha` equals the previously deployed
   2.58.228 SHA (`374dc6060…`).
7. `sudo systemctl restart admin_bot`
8. Immediately run the checks in §4. Do not declare VERIFIED from this runbook alone; record the deployed SHA,
   effective configuration and actual observations.

## 4. Postdeploy checks (all read-only)

| Check | Expected |
|---|---|
| Local HTTP (on host, bypassing the proxy) | local `/healthz` returns 200 |
| Public HTTP `https://<host>/healthz` | 200 (separate row: proves TLS/proxy layer too) |
| Version | `APP_VERSION` reads `2.58.229` |
| Checkout identity | `git -C /var/www/admin_bot rev-parse HEAD` equals the manifest `deployed_sha` **exactly** (string equality, not prefix) |
| Deployed identity | existing identity probe reports `code=verified_deployed` (manifest/HEAD/version/process-start agree, `dirty=false`); any other code is recorded honestly, not assumed success |
| Schema | `user_version=48`; `schema_migrations` max/count 48; no migration/DDL applied |
| Process | `systemctl show -p NRestarts admin_bot` shows no new automatic restart after the deploy restart |
| Journal | `journalctl -u admin_bot --since <deploy time>` has no new fatal startup/migration/traceback entries |
| Settings/flags | existing effective values, persisted settings and chat overrides preserved; no new flags |
| Prompts/profiles (digests) | effective prompt documents/overrides and persisted settings documents have the **same digests** before and after the restart; this release has no prompt/write path |
| Roles API (read-only) | `GET /api/roles/tree`, `/api/roles`, `/api/admins` return 200 for the global admin session; row/role counts match preflight (a) and the real production model, not the stub fixture |
| Roles page (read-only UI smoke) | `#/access/roles` renders the roles list and the rights matrix; counters match the API payload; **no rename, no delete, no save, no toggle** is performed |
| Roles page (honest states) | no `0 из 0` / `нет 0` on any screen; a real 503/403 shows the honest refusal text; 404 list shows the primary retry control — these are confirmed pre-deploy on identical bytes (§4.1), not by forced production failures |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); free space adequate; remove temporary probe files |
| Temp artifacts | no probe DB, snapshot copy or test output left on production beyond the declared evidence |

### 4.1 Behavioral acceptance — confirmed pre-deploy on identical bytes

**Do not send test messages to the working chats and do not run any live-chat/LLM check** after the deploy: no “test
chat”, no probe message, no synthetic question in a real chat, no toggle, role rename, delete or save.

The C1 behavior was confirmed before the deploy by the reviewed tests, the Playwright e2e (7 viewports + 401/403/404/503
+ non-global) and the Reviewer's Browser Use run on candidate `eb305b6fe`; this branch reproduces the same served bytes
plus the version wave. The deploy is accepted through **deployed-byte identity**, not through new production writes:

```
git -C /var/www/admin_bot rev-parse HEAD            # == manifest deployed_sha
git -C /var/www/admin_bot diff --name-only <content-tip>..HEAD -- \
    web services config handlers database.py migrations prompts
```

must be empty apart from the docs-only evidence commit. If the product diff is not empty, the running bytes are not
the accepted bytes: stop and escalate instead of “verifying” behavior on production.

Pre-deploy confirmed expectations (from `tests-2.58.229.json`, on the identical served bytes):

| Check | Confirmed by | Expected on production |
|---|---|---|
| Counters are honest under error/non-global | C1 e2e `error-*` rows | refusal text, never `0 из 0`; a real zero only after a successful empty response |
| Used-role delete is blocked | `F02@<viewport>` all 7 viewports | delete disabled, rename enabled, usage note with the actual assignment count |
| Superuser is read-only on this page | node + Playwright + Browser Use | save/delete disabled for `admin` |
| 404 list retry | `error-tree-404` → `retryList=true`, `retryRolesDelta=1` | real reload of the role list, selected role preserved |
| Whole-object role preservation | node editor-preserve suite | an empty section never erases `wildcard`/`sections`/`chat_lore`/unknown keys |
| Layout/touch | 7 viewports, no h-scroll, no nested scrollers | same at 320/390/768/1280/1440/1920 |

`MAC-S8-SCN-01` (live non-global/TMA session) remains **RFL** — not part of this assembly, not owner QA, and it is
never claimed as VERIFIED from this runbook.

## 5. Rollback

1. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; preserve untracked runtime data.
   Do not delete user data, backups or unknown files.
2. `git -C /var/www/admin_bot reset --hard 374dc60609986a9250170a34a48c93bf2ba85e29` (or an equivalent authorized
   checkout of the same commit).
3. `python tools/release_manifest.py --effect rollback`
4. `sudo systemctl restart admin_bot`
5. Verify `/healthz` 200, version `2.58.228`, schema 48, settings unchanged, no new journal errors.
6. Data action: **none**. 2.58.229 has DDL 0 and schema 48; no schema downgrade, no row deletion. Roles/admins rows
   created by an operator through the UI are ordinary data and are not reverted by a code rollback; the previous
   frontend/API behavior is restored as-is.
7. Keep the pre-deploy backup and rollback copy until the release is stable.

## 6. Known residual / limitations

- This assembly is REVIEW only: no deploy, no live Telegram/TMA/LLM check, no VERIFIED claim.
- `REL-229-PIN-01` (stale `ROUTES_SHA256_F11` byte-freeze) is open; deploy is blocked until the re-pin is reviewed
  and this runbook's SHA/digests are refreshed.
- C1 e2e used served bytes with API stubs and `TMA_STUB`, not a live TMA session; Browser Use coverage is the
  Reviewer's run on the same bytes.
- Pre-existing failures: 3 JS suites, 1 Python test, 4 pin-guard node IDs — listed in `assembly.md`/`tests-2.58.229.json`,
  not counted as passes.
- C2/C3 (effective/preview/chat-override/audit/revisions/409 UI, S1/S2/S3 guards, `#/access/admins|local`) are out of
  scope and are not verified by this release.
- The Reviewer's non-blocking backlog (B01–B06) stays backlog-only; no code change here.
