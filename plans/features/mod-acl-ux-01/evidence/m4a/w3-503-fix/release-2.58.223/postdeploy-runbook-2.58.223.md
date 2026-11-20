# Postdeploy runbook — 2.58.223 (W3/F-1: 503 vs disabled)

Status: **REVIEW**, no deploy performed in assembly. Production host: `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`. Old VPS `198.46.175.136` is decommissioned and not a rollback target.

## 1. Preconditions

- Release branch: `release/mod-acl-w3-503-2.58.223`.
- Content/bump commit: `9138f2ee821aceb897cd69d3a768d5969852751c` (version 2.58.223, schema 48, DDL 0).
- Approved candidate: `afe9beb2478fb19f435319cb07e0aa3264b2bb87`; merge `6057bd5bbc791c78ae8102c3d143ea4de1c7a186`.
- Rollback/base: `26b8880c64283457434fdbec58f65e0dd3eafd25` (2.58.222, content `03abd668d`).
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy.
- No new flags/store/embedding/LLM/DDL; do not alter `.env`, persisted settings or chat overrides.

## 2. Deploy steps (only after separate deploy authorization)

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot checkout` the authorized release commit (content commit or a later evidence-only commit on the same branch).
3. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION` reads `2.58.223`.
4. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no `--dry-run`).
5. `sudo systemctl restart admin_bot`
6. Immediately run the checks below. Do not declare VERIFIED from this runbook alone; record the deployed SHA and effective state.

## 3. Postdeploy checks

| Check | Expected |
|---|---|
| HTTP `https://<host>/healthz` | 200 |
| Version/identity | `2.58.223`; deployed SHA matches the manifest/checkout |
| Schema | `user_version=48`; no migration/DDL applied; `schema_migrations` remains 48 |
| Manifest/journal | deploy manifest present; no new fatal startup/migration errors |
| Settings/flags | existing effective values and chat overrides preserved; W3/F-1 adds no flags/settings |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); no temporary probe DB left |

### 3.1 W3/F-1 live matrix (MAC-S10-16)

Use the deployed checkout and a real authenticated TMA session; record the deployed SHA, served-byte sha256 and screenshots. The history surface must distinguish all five causes:

| Cause | Expected DOM state | Expected text |
|---|---|---|
| 0 events | `data-overview-history-state="empty"` | `Записей пока нет.` |
| 403 | `denied` | `…нет доступа (403)` |
| 503 | `unavailable` | `…временно недоступен (503). Повторите попытку.` |
| disabled / `available:false` | `off` | `…функция выключена.` — **без** `503` |
| stale 409 | `[data-workspace-conflict]` | `Настройка изменилась в другом окне` |

Additional checks:
1. On HTTP 503 the deep link `#/modules/<slug>/history` **stays** on the panel, shows `data-module-history-state="unavailable"` and a retry control; it must not redirect to bare and must not show «0 событий».
2. `available:false` / `enabled:false` stays `off`; the text must not claim 503.
3. 403 keeps `denied`; empty keeps `empty`; a network/parse error keeps `error`.
4. Run `tools/ui_mod_acl_m4_catalog_e2e.py` on the deployed checkout (`M4A-CATALOG-E2E OK | failures=0`) and the existing W2b/W2a suites.
5. Browser Use on real Chrome desktop/390: same selectors/texts, no horizontal overflow, panel/retry usable.
6. Real non-editor 403 (`MAC-S2-84`) still needs a real authenticated non-editor session; do not fabricate initData.

**Not required:** S2/S3 TIME-03 probe (this release has no TIME-03 product delta).

## 4. Rollback

1. `git -C /var/www/admin_bot reset --hard 26b8880c64283457434fdbec58f65e0dd3eafd25`
2. `python tools/release_manifest.py --effect rollback`
3. `sudo systemctl restart admin_bot`
4. Verify `/healthz` 200, version `2.58.222`, schema 48, settings unchanged, no new journal errors.
5. Data action: none. 2.58.223 has DDL 0 and schema 48; do not run schema downgrades or delete user data.

## 5. Known residual / limitations

- This assembly is REVIEW only: no production deploy, no live TMA, no VERIFIED claim.
- `MAC-S10-16` remains not VERIFIED until the deployed-byte live matrix and Browser Use.
- Pin baseline 856/4 and broad JS 124/4 are the same four pre-existing failures on `26b8880c`; they are not caused by this release and are not counted as pass.
- The local e2e uses a synthetic API stub; production Linux/TMA still needs the checks above.
- The `(CRLF)` wording in the candidate `implementation.md` line 46 is an erroneous non-blocking note; the actual deployed/checkout bytes are LF and the recorded hashes `108f440f…`/`c3ceb1b5…` are correct.
