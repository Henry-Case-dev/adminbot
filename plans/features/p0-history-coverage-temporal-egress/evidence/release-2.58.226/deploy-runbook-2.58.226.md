# Deploy runbook — 2.58.226 (P0-HC: history coverage / temporal evidence / Telegram egress)

Status: **REVIEW**, no deploy performed in this assembly. Production host:
`192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`.
Old VPS `198.46.175.136` is decommissioned and is not a rollback target.

## 1. Preconditions

- Release branch: `release/p0-hc-2.58.226`; content/bump tip in this assembly:
  `bafbd0863d7c8bb157abe3428463eedd9fa0079f` (version 2.58.226, schema 48, DDL 0).
- Product: `4bb7e593c5d4b085290ff7f034f0f1b28b0233bb`; reviewed test delta:
  `e26ebc16311f83d4df5ec265ce2933ee19e11440`.
- Rollback/base: `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d` (2.58.225, schema 48, DDL 0).
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune
  the rollback copy.
- No new flags, store, embedding, LLM prompt, migration or DDL. Do not alter
  `.env`, persisted settings or chat overrides.
- The acceptance harness (`tools/p0_hc_acceptance.py`,
  `tests/test_p0_hc_acceptance.py`) is not in this branch and must not be added
  or run from it: it pins `CANDIDATE_SHA`/`EXPECTED_RELEASE` and its prior
  acceptance result stays on `p0/hc-accept`.
- SSH/fail2ban: one short recon connection is enough; check liveness over HTTPS
  (`/healthz`), do not retry auth in a loop or run parallel connection attempts.

## 2. Deploy steps (only after separate deploy authorization)

1. Check free disk space before any backup/copy; do not start a full DB copy if
   space is insufficient.
2. `git -C /var/www/admin_bot fetch --prune`
3. `git -C /var/www/admin_bot pull --ff-only` (or checkout the authorized release
   commit). The evidence commit after the content tip is docs-only; the deployed
   SHA shown by the manifest is the actual checked-out SHA.
4. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is
   empty; `APP_VERSION` reads `2.58.226`.
5. Make the pre-deploy DB backup with the existing deploy-backup mechanism
   (keep the current rollback copy).
6. Record the actual checkout manifest **before** restart:
   `python tools/release_manifest.py` (no `--dry-run`). Confirm `version=2.58.226`,
   `effect=deploy`, `dirty_tracked=false`, and `previous_sha` is the previously
   deployed 2.58.225 SHA.
7. `sudo systemctl restart admin_bot`
8. Immediately run the checks below. Do not declare VERIFIED from this runbook
   alone; record deployed SHA, effective configuration and actual observations.

## 3. Postdeploy checks

| Check | Expected |
|---|---|
| HTTP `https://<host>/healthz` | 200 |
| Version/identity | `2.58.226`; `deployed_sha` matches the manifest and the actual checkout |
| Schema | `user_version=48`; `schema_migrations` max/count 48; no migration/DDL applied |
| Process | `systemctl show -p NRestarts admin_bot` shows no new automatic restart after the deploy restart |
| Journal | `journalctl -u admin_bot --since <deploy time>` has no new fatal startup/migration/traceback entries |
| Settings/flags | existing effective values, persisted settings and chat overrides preserved; no new flags in this release |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); free space is adequate; remove temporary probe files |
| Temp artifacts | no probe DB, snapshot copy or test output left on production beyond the declared evidence |

### 3.1 P0 read-only postdeploy matrix

Use the deployed checkout and an authorized test chat; record deployed SHA,
observed timestamps and message IDs, but do not copy user message text into the
evidence.

| Check | Expected |
|---|---|
| Period question, duration | e.g. “что было за последний час / вчера” resolves to the exact `from..to` window from `turn_as_of`, not to an FTS query over arbitrary hours |
| Period header | range-first response exposes `window_kind/window_from/window_to/as_of/clamped/requested/available/processed/remaining/has_next/incomplete` honestly |
| Empty / unresolved | “что было 5 минут назад” (empty) and an unparseable period-like phrase (unresolved) return an explicit honest status, not fabricated history or silent FTS substitution |
| Reply edge | a message that is a reply displays `ответ на tg:<id>` in context and reaches the Writer payload; absent reply metadata keeps the old bytes |
| Edit metadata | an edited message displays `ред. <UTC>` with a single UTC scale and the chat-zone legend; the model is not shown `created_at` as the event time |
| Plain Telegram egress | literal text with `*`, `_`, `\`, backticks or Windows paths is delivered as plain text: no `parse_mode`, no raw HTML, no lost characters |
| Structural Telegram egress | headings/quotes/lists/fences/bold/links are delivered as safe HTML exactly once; no raw `**`/backticks, no duplicate send, long answers are chunked safely |
| Failure path | a partial Telegram API failure converts only the affected chunk to plain, does not resend prior chunks and does not call the LLM again |
| Logs/trace | one send path per answer; no second delivery, no unhandled traceback, no secret or full prompt in logs |

The deeper acceptance scenarios (history partial/ingestion gap, DST today,
forwarded-old-quote identity, external provider rows) remain owned by the prior
acceptance evidence and the independent review; do not fabricate them from this
runbook.

## 4. Rollback

1. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is
   empty; preserve untracked runtime data. Do not delete user data, backups or
   unknown files.
2. `git -C /var/www/admin_bot reset --hard 1b7d43333b5be8fcbceff2fc82ff8436e5947e9d`
   (or an equivalent authorized checkout of the same commit).
3. `python tools/release_manifest.py --effect rollback`
4. `sudo systemctl restart admin_bot`
5. Verify `/healthz` 200, version `2.58.225`, schema 48, settings unchanged and
   no new journal errors.
6. Data action: none. 2.58.226 has DDL 0 and schema 48; do not run schema
   downgrades or delete user data. Keep the pre-deploy backup and rollback copy
   until the release is stable.

## 5. Known residual / limitations

- This assembly is REVIEW only: no production deploy, no live Telegram check,
  no VERIFIED claim.
- Pre-existing test failures listed in `assembly.md`/`tests-2.58.226.json` are not
  caused by this delta and are not counted as passes.
- `HC-ACC-FREE-SPEECH` / `HC-ACC-NO-OBJECTIVITY` remain `not_executed` because the
  external provider returns HTTP 402; do not present a static check as answer
  quality proof.
- The release branch intentionally excludes the acceptance harness; its pinned
  candidate/release values must not be weakened to fit the bump.
