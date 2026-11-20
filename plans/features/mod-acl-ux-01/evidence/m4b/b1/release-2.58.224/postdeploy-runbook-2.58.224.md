# Postdeploy runbook — 2.58.224 (MOD-ACL-UX-01 M4B B1: пять лент «Статуса»)

Status: **REVIEW**, no deploy performed in assembly. Production host: `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`. Old VPS `198.46.175.136` is decommissioned and not a rollback target.

## 1. Preconditions

- Release branch: `release/mod-acl-m4b1-2.58.224`.
- Content/bump commit: `57e123db7c6c2a34d1fb873fe2cb595878bd2566` (version 2.58.224, schema 48, DDL 0).
- Approved candidate: product `5f8026b2fb9a1509c09df834b2154d8c3c71d393`, branch tip `b360cd8aa866a7892ede1754eaae23c6ebceb997`; review `review-r2.md` sha256 `9c500566…`, verdict `APPROVED_FOR_RELEASE_PREPARATION`.
- Rollback/base: `40fe603f0aac853af99656bac1934ec5f3d160f9` (2.58.223, content `9138f2ee8`).
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy.
- No new flags/store/embedding/LLM/DDL; do not alter `.env`, persisted settings or chat overrides.

## 2. Deploy steps (only after separate deploy authorization)

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot checkout` the authorized release commit (content commit or a later evidence-only commit on the same branch).
3. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION` reads `2.58.224`.
4. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no `--dry-run`).
5. `sudo systemctl restart admin_bot`
6. Immediately run the checks below. Do not declare VERIFIED from this runbook alone; record the deployed SHA and effective state.

## 3. Postdeploy checks

| Check | Expected |
|---|---|
| HTTP `https://<host>/healthz` | 200 |
| Version/identity | `2.58.224`; deployed SHA matches the manifest/checkout |
| Schema | `user_version=48`; no migration/DDL applied; `schema_migrations` remains 48 |
| Manifest/journal | deploy manifest present; no new fatal startup/migration errors |
| Settings/flags | existing effective values and chat overrides preserved; B1 adds no flags/settings |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); no temporary probe DB left |

### 3.1 B1 live matrix (MAC-S6-307 / MAC-AC-16 / FEED-01/02/03 / S15-03 / S15-15)

Use the deployed checkout and a real authenticated TMA session; record the deployed SHA, served-byte sha256 and screenshots bound to the API snapshot and scope.

| Check | Expected |
|---|---|
| 1440 / 1920 / 1280 | exactly 5 ribbons in one intel widget: facts, beliefs, paradigms, traits, dossier; grid 3 + 2; no page horizontal scroll |
| 768 | 5 ribbons in 2 + 2 + 1; switcher hidden |
| 390 / 320 | one ribbon + 5 tab controls (touch ≥44 px); dossier selectable via tab; no horizontal overflow |
| Dossier content | person-centric rows: one participant = one row, last record, count, chat label; no 1:1 duplicate of «Новые факты» |
| Dates/provenance | row date from `created_at` (not event/confirmation); origin/source visible in the record window |
| Detail | click opens the existing record window; «Досье субъекта» opens the existing dossier; no second modal/store |
| Pause/resume | auto vertical movement; wheel/swipe/focus pauses; resumes after idle; reduced-motion disables motion |
| Empty chat | selected chat with no dossier shows the honest «В выбранном чате…» line and no foreign names |
| Cross-scope (S15-03) | select Audit Chat with rows → `#/modules` → switch to Empty Chat → return `#/` before the delayed answer: old rows are NOT shown; only the new-scope empty/rows state appears |
| 503 dossier_feed | error reason shown (temporarily unavailable), not «0 записей»/empty |
| Existing 503/off/denied/empty contracts | unchanged (W3/F-1) |

Additional checks:
1. Run `tools/ui_mod_acl_m4b_status_e2e.py` on the deployed checkout; expected `M4B-STATUS-E2E-OK`, 138 checks, 0 failures (synthetic API stand; bind screenshots to the deployed SHA and API snapshot).
2. Browser Use on real Chrome desktop/390: 5 ribbons, 3+2 / 1, person rows, detail/provenance, cross-scope empty; no horizontal overflow.
3. Run the mandatory 24-file pytest set and the B1/W2a/W2c/W2b node files; expected 386 and 11/11 rc=0.
4. Natural 503/empty chat is RFL: do not fabricate a 503 or production data to satisfy it.
5. `MAC-S15-04` full resilience remains B3; `MAC-S0-11` remains partial until B2.

**Not required:** S2/S3 TIME-03 probe (this release has no TIME-03 product delta).

## 4. Rollback

1. `git -C /var/www/admin_bot reset --hard 40fe603f0aac853af99656bac1934ec5f3d160f9`
2. `python tools/release_manifest.py --effect rollback`
3. `sudo systemctl restart admin_bot`
4. Verify `/healthz` 200, version `2.58.223`, schema 48, settings unchanged, no new journal errors.
5. Data action: none. 2.58.224 has DDL 0 and schema 48; do not run schema downgrades or delete user data.

## 5. Known residual / limitations

- This assembly is REVIEW only: no production deploy, no live TMA, no VERIFIED claim.
- `MAC-S6-307`/`MAC-S15-03` remain not VERIFIED until the deployed-byte live matrix and Browser Use.
- w10/w15 full tools retain pre-existing non-B1 failures (module catalog, cog-map, adaptive prompt editor); B1-specific checks pass.
- Broad JS 122/3 and version pins 856/4 are the same pre-existing base failures, not caused by this release and not counted as pass.
- The visual diff tool `tools/ui_cmv_perf_parity.py` was not run; B1 intentionally changes the grid baseline (N09, release-lane decision).
