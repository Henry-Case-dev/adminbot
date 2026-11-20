# Postdeploy runbook — 2.58.221 (W2c navigation/layout/wireframe)

Status: **REVIEW**, no deploy performed in assembly. Production host: `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`. Old VPS `198.46.175.136` is decommissioned and not a rollback target.

## 1. Preconditions

- Release branch: `release/mod-acl-w2c-2.58.221`.
- Content commit: `1c75a1d8a2b1f573c44deabab4d38bfcbc20ddbe` (version 2.58.221, schema 48, DDL 0).
- Approved candidate: `67ef30cd120163132a2f2e894a0fe474bba9623d`; merge `c16c3566d4cb6d0cbd68c1f58eb4527380e49daf`.
- Rollback/base: `d03027b1bc3811a0614c5a2e38342eb9e77c4ea5` (2.58.220, content `8e05e9a4`).
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy.
- No new flags/store/embedding/LLM/DDL; do not alter `.env`, persisted settings or chat overrides.

## 2. Deploy steps (only after separate deploy authorization)

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot checkout` the authorized release commit (content commit or a later evidence-only commit on the same branch).
3. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION` reads `2.58.221`.
4. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no `--dry-run`).
5. `sudo systemctl restart admin_bot`
6. Immediately run the checks below. Do not declare VERIFIED from this runbook alone; record the deployed SHA and effective state.

## 3. Postdeploy checks

| Check | Expected |
|---|---|
| HTTP `https://<host>/healthz` | 200 |
| Version/identity | `2.58.221`; deployed SHA matches the manifest/checkout |
| Schema | `user_version=48`; no migration/DDL applied; `schema_migrations` remains 48 |
| Manifest/journal | deploy manifest present; no new fatal startup/migration errors |
| Settings/flags | existing effective values and chat overrides preserved; W2c adds no flags/settings |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); no temporary probe DB left |

### 3.1 W2c NAV-01 / LAY-01 / WF-01 (agents; not owner QA)

Use the local/real TMA with the same authenticated role and chat scope as before the release; record screenshots and measured values.

1. **NAV:** `#/modules` → submodule card (`stories`, `experience`, `random`, `character`) shows the parent chip; chip href is `#/memory/rag` for the first three and `#/permsoc` for `character`; chip click opens the parent surface, not the module card. On `#/memory/rag`/`#/permsoc` the owner row has `Настраивается в «…» →` and no duplicate submodule config fields. Catalog → module → subsection direct deep link opens the same tab after reload.
2. **LAY:** at 1440/1280 desktop sidebar is 190–220 px (216 nominal); complex/infrastructure content ≤1440; small/policy content 900–1000; at 768/390/320 one column, no horizontal overflow (`scrollWidth <= innerWidth + 1`), touch targets ≥44 (including catalog parent chip, workspace tabs/tri-state/inputs). `8/12 + 4/12` only on `#/modules/direct/models`; at 1024/1152/1199 the split is one column, at 1200/1680 it is 8/4.
3. **WF:** module page has one header/H1; complex overview shows 3–5 real events; advanced zone uses `Расширенные системные (N)`; class surfaces render (complex/small/infrastructure/maintenance).
4. Repeat the existing W2c Playwright tool on five viewports (1440/1280/768/390/320) plus 1680 and the 1024/1152/1199/1200 split checks; Browser Use: same routes, desktop 1440 and mobile 390. A failure in any check is a blocker, not a reason to disable the feature.

**Not required:** S2/S3 TIME-03 probe (this release has no TIME-03 product delta). Do not turn it into an owner QA obligation.

## 4. Rollback

1. `git -C /var/www/admin_bot reset --hard d03027b1bc3811a0614c5a2e38342eb9e77c4ea5`
2. `python tools/release_manifest.py --effect rollback`
3. `sudo systemctl restart admin_bot`
4. Verify `/healthz` 200, version `2.58.220`, schema 48, settings unchanged, no new journal errors.
5. Data action: none. 2.58.221 has DDL 0 and schema 48; do not run schema downgrades or delete user data.

## 5. Known residual / limitations

- This assembly is REVIEW only: no production deploy, no live TMA, no independent re-review verdict, no VERIFIED claim.
- Affected Python 218/6 and broad JS 124/4 have baseline-identical failures; they are not hidden or counted as pass.
- The cognition-map visual parity tool is nondeterministic; W2c was checked with targeted surface parity, proportions and Playwright/Browser Use screenshots.
