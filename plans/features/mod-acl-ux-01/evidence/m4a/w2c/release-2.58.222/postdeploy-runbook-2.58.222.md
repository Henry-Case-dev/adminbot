# Postdeploy runbook — 2.58.222 (W2c + card-height corrective)

Status: **REVIEW**, no deploy performed in assembly. Production host: `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`. Old VPS `198.46.175.136` is decommissioned and not a rollback target.

## 1. Preconditions

- Release branch: `release/mod-acl-w2c-2.58.222`.
- Content commit: `03abd668d76befe8bc36c47c41a8e8666d47e107` (version 2.58.222, schema 48, DDL 0).
- Approved fix: `51bad063ff47750798b6419456862f83f7db3ca5`; merge `a959bb61f582a3005dccf7ac61f7385b1f57c701`.
- Rollback/base: `d03027b1bc3811a0614c5a2e38342eb9e77c4ea5` (2.58.220, content `8e05e9a4`).
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy.
- No new flags/store/embedding/LLM/DDL; do not alter `.env`, persisted settings or chat overrides.

## 2. Deploy steps (only after separate deploy authorization)

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot checkout` the authorized release commit (content commit or a later evidence-only commit on the same branch).
3. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION` reads `2.58.222`.
4. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no `--dry-run`).
5. `sudo systemctl restart admin_bot`
6. Immediately run the checks below. Do not declare VERIFIED from this runbook alone; record the deployed SHA and effective state.

## 3. Postdeploy checks

| Check | Expected |
|---|---|
| HTTP `https://<host>/healthz` | 200 |
| Version/identity | `2.58.222`; deployed SHA matches the manifest/checkout |
| Schema | `user_version=48`; no migration/DDL applied; `schema_migrations` remains 48 |
| Manifest/journal | deploy manifest present; no new fatal startup/migration errors |
| Settings/flags | existing effective values and chat overrides preserved; W2c/card-height adds no flags/settings |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); no temporary probe DB left |

### 3.1 W2c NAV-01 / LAY-01 / WF-01 + card-height

Use the local/real TMA with the same authenticated role and chat scope as before the release; record screenshots and measured values. Run the existing `tools/ui_mod_acl_m4a_w2c_e2e.py` (6 viewports) and `tools/ui_mod_acl_m4_catalog_e2e.py` on the deployed checkout, plus the long-content card-height probe or an equivalent real chat-scope check.

1. **Media row card height:** TMA catalog in chat scope with real data. `mod_transcribe`, `mod_video_summary`, `mod_media_download`, `mod_images` and the whole media row must be **132–164 px**; measured target 162.06 at 1680/1440/320. A 179.56/180 result is a blocker (missing title clamp). The title must be one line with ellipsis; `:title` must expose the full title.
2. **NAV:** catalog → module → subsection direct deep link; parent chip `Часть «Памяти»` → `#/memory/rag`, `Часть «PERMsoc»` → `#/permsoc`; parent surface has owner links and no duplicate submodule fields.
3. **LAY:** sidebar 190–220 px; complex/infrastructure ≤1440; small/policy 900–1000; 8/12+4/12 only on `#/modules/direct/models`; 1024/1152/1199 one column, 1200/1680 8/4; touch ≥44; no horizontal overflow.
4. **WF:** one header/H1; complex overview 3–5 real events; `Расширенные системные (N)`; body/status interactions unaffected.
5. **Browser Use:** same routes on real Chrome at 1680/1440/320; verify media-row heights, ellipsis/full `:title`, chat labels not clipped, no page horizontal overflow. Record screenshots.
6. **M4A e2e:** `M4A-CATALOG-E2E OK | failures=0`, including the 409/badge/D2/mobile-height checks.

**Not required:** S2/S3 TIME-03 probe (this release has no TIME-03 product delta).

## 4. Rollback

1. `git -C /var/www/admin_bot reset --hard d03027b1bc3811a0614c5a2e38342eb9e77c4ea5`
2. `python tools/release_manifest.py --effect rollback`
3. `sudo systemctl restart admin_bot`
4. Verify `/healthz` 200, version `2.58.220`, schema 48, settings unchanged, no new journal errors.
5. Data action: none. 2.58.222 has DDL 0 and schema 48; do not run schema downgrades or delete user data.

## 5. Known residual / limitations

- This assembly is REVIEW only: no production deploy, no live TMA, no VERIFIED claim.
- Affected Python approved baseline is 304/6; local expanded set is 305/6 with the same six stale failures (one-test collection difference). No new failures.
- Card-height long-content titles are realistic but synthetic; production Linux fonts are covered only by this postdeploy check.
- W2c rows remain REVIEW until deployed-byte evidence and final acceptance.
