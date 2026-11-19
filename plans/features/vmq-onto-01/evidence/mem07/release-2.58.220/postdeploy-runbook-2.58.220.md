# Postdeploy runbook — 2.58.220 (TIME-03)

Status: **REVIEW**, no deploy performed in assembly. Production host: `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`. Old VPS `198.46.175.136` is decommissioned and not a rollback target.

## 1. Preconditions

- Release branch: `release/time03-natural-2.58.220`.
- Content commit: `8e05e9a4d7ae7dafba6ab4efca405149264d5ba5` (version 2.58.220, schema 48, DDL 0).
- Rollback/base: `0fce97a14338521a24d94f560e896ebcb19f9492` (2.58.219, content `f80cba08`).
- Decision: `plans/features/vmq-onto-01/evidence/mem07/time03-final-release-decision.md` (sha256 `981bfa38…`, `RELEASE_WITH_BACKLOG`).
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy.
- No new flags/store/embedding/LLM/DDL; do not alter `.env`, persisted settings or chat overrides.

## 2. Deploy steps (only after separate deploy authorization)

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot checkout` the authorized release commit (content commit or a later evidence-only commit on the same branch).
3. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION` reads `2.58.220`.
4. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no `--dry-run`).
5. `sudo systemctl restart admin_bot`
6. Immediately run the checks below. Do not declare VERIFIED from this runbook alone; record the deployed SHA and effective state.

## 3. Postdeploy checks

| Check | Expected |
|---|---|
| HTTP `https://<host>/healthz` | 200 |
| Version/identity | `2.58.220`; deployed SHA matches the manifest/checkout |
| Schema | `user_version=48`; no migration/DDL applied; `schema_migrations` remains 48 |
| Manifest/journal | deploy manifest present; no new fatal startup/migration errors |
| Settings/flags | existing effective values and chat overrides preserved; TIME-03 adds no flags |
| Retrieval smoke | a normal question still returns a bounded RAG block; no crash/empty regression; old episode/current paths degrade honestly |
| Chat/access scope | all refs within the same chat/ACL; no cross-chat refs |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); no temporary probe DB left |

Do not treat a missing/unknown value as zero or success; record `unknown`/`not_checked` honestly.

## 4. Rollback

1. `git -C /var/www/admin_bot reset --hard 0fce97a14338521a24d94f560e896ebcb19f9492`
2. `python tools/release_manifest.py --effect rollback`
3. `sudo systemctl restart admin_bot`
4. Verify `/healthz` 200, version `2.58.219`, schema 48, settings unchanged, no new journal errors.
5. Data action: none. 2.58.220 has DDL 0 and schema 48; do not run schema downgrades or delete user data.

## 5. Known residual (RELEASE_WITH_BACKLOG, not a deploy blocker)

- S2/S3 real probe was `not_executed/reference_unreachable` (imported/unindexed anchors `row:1653613`, `row:53`); not a product pass, not VERIFIED.
- S4 critical current/stale safety passed; S4 2026 episode coverage remains a backlog gap.
- S1 3-year edge, S5 fact anchors, S6 second 2022 anchor, vector semantics and sampled-not-full suite remain backlog.
- A targeted real S2/S3/S4 probe is **not required** for this release under the decision; do not turn it into an owner QA obligation.
