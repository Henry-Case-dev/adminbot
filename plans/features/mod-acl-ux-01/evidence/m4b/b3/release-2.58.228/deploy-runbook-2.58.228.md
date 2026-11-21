# Deploy runbook — 2.58.228 (MOD-ACL-UX-01 M4B B3)

Status: **REVIEW**, no deploy performed in this assembly. Production host:
`192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`.
Old VPS `198.46.175.136` is decommissioned and is not a rollback target.

## 1. Preconditions

- Release branch: `release/mod-acl-m4b3-2.58.228`; content tip in this assembly:
  `ff8a596367dc2e576e7034b980f27cddfcbb4014` (standard bump on the cherry-picked
  product `237bf6103`; version 2.58.228, schema 48, DDL 0). The evidence commit
  after the content tip is docs-only.
- Reviewed candidate: `237bf6103` (`feat/mod-acl-m4b3`), review artifacts on
  master `d5b5cfa78` (r1, `NEEDS_FIXES`, blocker B3-R1-01) and `8e719c2ca`
  (addendum, `APPROVED_FOR_RELEASE_PREPARATION`, B3-R1-01 resolved).
- Rollback/base: `c8cf54c1ad92e8039928c531efe70efe141704bd` (2.58.227,
  schema 48, DDL 0).
- Product bytes are byte-identical to the reviewed candidate:
  `git diff 237bf6103..ff8a59636 -- web` is empty and the reviewed served
  sha256 are `app.js 37fd2f0c…`, `index.html d3e3d2b0…`, `app.css b6675a10…`.
- No new flags, store, embedding, LLM prompt, hot-config, migration or DDL.
  Do not alter `.env`, persisted settings or chat overrides.
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune
  the rollback copy. Check free disk space before any backup/copy.
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
   is empty; `APP_VERSION` reads `2.58.228`.
5. Make the pre-deploy DB backup with the existing deploy-backup mechanism
   (keep the current rollback copy).
6. Record the actual checkout manifest **before** restart:
   `python tools/release_manifest.py` (no `--dry-run`). Confirm
   `version=2.58.228`, `effect=deploy`, `dirty_tracked=false`, and
   `previous_sha` is the previously deployed 2.58.227 SHA (`c8cf54c1a…`).
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
| Version | `APP_VERSION` reads `2.58.228` |
| Checkout identity | `git -C /var/www/admin_bot rev-parse HEAD` equals the manifest `deployed_sha` **exactly** (string equality; a prefix match is not enough) |
| Deployed identity | existing identity probe reports `code=verified_deployed` (manifest/HEAD/version/process-start agree, `dirty=false`); any other code (`local_unverified`, `mismatch`, `unknown`, `unavailable`) is recorded honestly and not assumed to mean success |
| Schema | `user_version=48`; `schema_migrations` max/count 48; no migration/DDL applied |
| Process | `systemctl show -p NRestarts admin_bot` shows no new automatic restart after the deploy restart |
| Journal | `journalctl -u admin_bot --since <deploy time>` has no new fatal startup/migration/traceback entries |
| Settings/flags | existing effective values, persisted settings and chat overrides preserved; no new flags in this release |
| Prompts/profiles (digests) | effective prompt documents and overrides (read-only via the existing `prompt_readback` view and the registry ledger) plus persisted settings documents have the **same digests** before and after the restart; this release contains no prompt/write path |
| Memory API (read-only) | `GET /api/memory/expired-overview` still requires global admin; `facts_*` are additive numbers/`null` (never fabricated); `GET /api/memory/lessons` still serves the existing admin-scoped contract |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); free space is adequate; remove temporary probe files |
| Temp artifacts | no probe DB, snapshot copy or test output left on production beyond the declared evidence |

### 3.1 Behavioral acceptance — confirmed pre-deploy on identical bytes

**Do not send test messages to the working chats and do not run any live-chat
write check** after the deploy: no "test chat", no probe message, no synthetic
question in a real chat, no toggle changes.

The B3 behavior was confirmed **before** the deploy by the reviewed tests and
the Reviewer's Playwright/Browser Use run on candidate `237bf6103`; this branch
reproduces the same served bytes plus the version pin. The deploy is accepted
through **deployed-byte identity**, not through new production writes:

```
git -C /var/www/admin_bot rev-parse HEAD            # == manifest deployed_sha
git -C /var/www/admin_bot diff --name-only <content-tip>..HEAD -- \
    web services config handlers database.py migrations prompts
```

must be empty (the release evidence commit on top of the content tip is
docs-only). If that diff is not empty, the running bytes are not the accepted
bytes: stop and escalate instead of "verifying" the behavior on production.

If a read-only production verification lane is separately authorized, it may
open the Mini App in an existing owner session without any writes and record:

| Check | Where confirmed | Expected |
|---|---|---|
| Memory summary | reviewed candidate tests + B3 e2e 131/131 on identical bytes | 5 semantic tiles in one row: active facts `42 · 24h: 6 · 7d: 19`, needs recheck `3`, expired `7`, beliefs `4`, last update with full timestamp in `title`/`aria`; tech counters inside `<details>`, no right-side number ledger |
| QRNG honesty | same | `последний квантовый батч` on success; `последний откат` without the word `успех` when only fallback exists; `—` when absent (no invented success) |
| Experience/lessons feed | same | 144 px window, both tracks, one row per event, no duplicates, no horizontal scroll, no third nested scroll container at 1920/1440/390/360; `действует` only when server `applied===true`; foreign lesson not active |
| Feed resilience | same | wheel/touch/hover/focus/new-items/modal pause/reduced-motion do not jump the feed to the start |
| Honest empty/fail states | same | 503 on `/api/status` -> `unknown` + last successful screen response time, no zero experience; global 503 does not render the experience card; `facts_* = null` -> `—` with reason, not `0` |
| Lessons track states | same (B3-R1-01 c4) | 503 -> `Состояние уроков неизвестно` + last successful lessons response (`ещё не было` if none); loading -> `Уроки загружаются…`; idle -> `Уроки ещё не загружались`; `Уроков пока нет` only after a successful empty response |
| Ordering | same | sleep -> last LLM call -> budgets; dynamic card heights, no inline height fixes |
| Scope | same | lessons request carries `chat_id`; foreign lesson never shown as active |

Live `MAC-S6-SCN-01` remains **READY_FOR_LIVE / RFL**: a production-derived
snapshot or live TMA observation is not part of this assembly and must be
recorded separately if it is ever collected. No live row is claimed here.

## 4. Rollback

1. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is
   empty; preserve untracked runtime data. Do not delete user data, backups or
   unknown files.
2. `git -C /var/www/admin_bot reset --hard c8cf54c1ad92e8039928c531efe70efe141704bd`
   (or an equivalent authorized checkout of the same commit).
3. `python tools/release_manifest.py --effect rollback`
4. `sudo systemctl restart admin_bot`
5. Verify `/healthz` 200, version `2.58.227`, schema 48, settings unchanged and
   no new journal errors.
6. Data action: none. 2.58.228 has DDL 0 and schema 48; do not run schema
   downgrades or delete user data. Keep the pre-deploy backup and rollback copy
   until the release is stable.
7. The B3 UI delta is web-only (`web/app.js`, `web/index.html`,
   `web/static/app.css`, additive `facts_*` on an existing read-only endpoint);
   rollback restores the previous UI and the previous API payload with no data
   migration.

## 5. Known residual / limitations

- This assembly is REVIEW only: no production deploy, no live Telegram/TMA
  check, no VERIFIED claim.
- B3 e2e used served candidate bytes with a deterministic synthetic stub; the
  Reviewer's Browser Use run used the same bytes (identical served sha256), not
  a live TMA session.
- Pre-existing test failures listed in `assembly.md`/`tests-2.58.228.json` are
  not caused by this delta and are not counted as passes.
- Review non-blocking B3-R1-NB2..NB5 and NB-1 font clipping remain backlog-only;
  no code change here.
- 14 B3 rows stay candidate-bound REVIEW until deploy + production-bound
  evidence; `MAC-S6-SCN-01` stays RFL; `MAC-S6-345`/`MAC-AC-15` (D2) and the
  four RFL rows are not part of this release.
