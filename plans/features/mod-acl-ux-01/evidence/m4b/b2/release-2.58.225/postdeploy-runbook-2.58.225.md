# Postdeploy runbook — 2.58.225 (MOD-ACL-UX-01 M4B B2: observer + last call)

Status: **REVIEW**, no deploy performed in assembly. Production host: `192.255.209.205`, checkout `/var/www/admin_bot`, unit `admin_bot`. Old VPS `198.46.175.136` is decommissioned and not a rollback target.

## 1. Preconditions

- Release branch: `release/mod-acl-m4b2-2.58.225`.
- Content/bump commit: `75b92f31d17c11ff111708b19564cb9fef978f8f` (version 2.58.225, schema 48, DDL 0).
- Approved candidate: product `db92c73ce122ee09a461696ba4d0a8c69b07cbb6`, branch tip `09ef444d83eb6b3e6b1fcb89928c99c629c0a415`; review `review-r1.md` sha256 `e8b957b8…`, verdict `APPROVED_FOR_RELEASE_PREPARATION`; NB-1 fixed in evidence.
- Rollback/base: `275a1b7cd320f67e0ac089d8d5c4b14ca31dbcfa` (2.58.224, content `57e123db7`).
- Keep the pre-deploy backup and the existing deploy-backup pool; do not prune the rollback copy.
- No new flags/store/embedding/LLM/DDL; D1/D3 add read-only nullable fields only. Do not alter `.env`, persisted settings or chat overrides.

## 2. Deploy steps (only after separate deploy authorization)

1. `git -C /var/www/admin_bot fetch --prune`
2. `git -C /var/www/admin_bot checkout` the authorized release commit (content commit or a later evidence-only commit on the same branch).
3. Verify `git -C /var/www/admin_bot status --porcelain --untracked-files=no` is empty; `APP_VERSION` reads `2.58.225`.
4. Record the actual checkout manifest **before** restart: `python tools/release_manifest.py` (no `--dry-run`).
5. `sudo systemctl restart admin_bot`
6. Immediately run the checks below. Do not declare VERIFIED from this runbook alone; record the deployed SHA and effective state.

## 3. Postdeploy checks

| Check | Expected |
|---|---|
| HTTP `https://<host>/healthz` | 200 |
| Version/identity | `2.58.225`; deployed SHA matches the manifest/checkout |
| Schema | `user_version=48`; no migration/DDL applied; `schema_migrations` remains 48 |
| Manifest/journal | deploy manifest present; no new fatal startup/migration errors |
| Settings/flags | existing effective values and chat overrides preserved; B2 adds no flags/settings |
| Disk | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy pool keep=2); no temporary probe DB left |

### 3.1 B2 live matrix (MAC-S6-306/309/331-336/344-347, MAC-AC-14/15, S0-11, S15-01/02)

Use the deployed checkout and a real authenticated TMA session; record the deployed SHA, served-byte sha256 and screenshots bound to the API snapshot and scope.

| Check | Expected |
|---|---|
| Health ribbon (S6-306) | deployed version and server checked-at visible; no client clock substituted |
| Observer KPIs (S6-331) | exactly 6 independent KPI cells with window (`всего (durable)` / `24ч` / `сейчас (снимок)`), scope and snapshot; not 8-stage funnel |
| No pseudo-conversion (S6-332/FUN-01/AC-14) | no funnel grid/percentage; explicit "independent numbers, not conversion"; `same_cohort=false` from D3 |
| Two entities + explain (S6-333/S15-02) | intents and publications shown separately; D3 `domains.explain` explains 0 active intents vs N publications |
| Why now (S6-334) | top-5 clickable reasons plus full list; health is not presented as outcome |
| Decisions (S6-335) | last 3-5 decisions with date/action/reason/delivery; full ledger with refusals/deliveries in disclosure |
| Check initiative (S6-336) | persistent mock vs real explanation, trace in disclosure; dry-run never presented as a real send |
| Unknown (S6-344/S15-01/S0-11) | compact unknown with checked-at and reason, no empty square |
| Last call (S6-345/AC-15) | `ok|empty|unavailable`; 1-2 lines with time/module/model/result/latency/input-output/cost; cost only when price is known; `l1_failure_mode`/`l1_finish_reason`; correlation_id and Analytics link. Full trace page is still absent (D2) — keep these rows partial |
| Image-only (S6-346) | image-only named separately, mixed shows a separate image row; per-chat/global not mixed; natural event is RFL, do not fabricate |
| Independent heights (S6-347) | sleep and last-call panels have independent heights; no `min-height` 300-500 for empty/503 |
| 1920/1440/1280/768/390/320 | no horizontal overflow; KPI row and causes readable; touch targets ≥44 px |
| Scope isolation | switching chat/global does not show stale observer/exec data from another scope |
| 503/empty | compact honest line with reason, not a blank block and not "0" |

Additional checks:
1. Run `tools/ui_mod_acl_m4b2_status_e2e.py` on the deployed checkout; expected `M4B-B2-STATUS-E2E-OK`, 92 checks, 0 failures (synthetic API stand; bind screenshots to the deployed SHA and API snapshot).
2. Run `tools/ui_mod_acl_m4b_status_e2e.py`; expected `M4B-STATUS-E2E-OK`, 138 checks, 0 failures (B1 ribbons/grid unchanged).
3. Run `tools/ui_asap8_v63_w3_status_e2e.py`; expected `W3-STATUS-E2E-OK`. The tool rewrites tracked `w3-evidence-status` PNGs — restore them to HEAD after the run.
4. Run the mandatory 24-file pytest set, D1/D3 set (94) and targeted node files (6/6).
5. W10/W15 full tools keep the pre-existing module catalog/cog-map/adaptive failures; require 0 status/observer-related failures, not a full green.
6. `MAC-S6-345`/`MAC-AC-15` remain partial until a full trace page exists; `MAC-S6-346` natural image-only event is RFL; do not fabricate production data.
7. Browser Use on real Chrome desktop/390: 6 KPIs, no funnel, reasons/decisions, mock/real note, compact last call; no horizontal overflow.

**Not required:** S2/S3 TIME-03 probe (this release has no TIME-03 product delta).

## 4. Rollback

1. `git -C /var/www/admin_bot reset --hard 275a1b7cd320f67e0ac089d8d5c4b14ca31dbcfa`
2. `python tools/release_manifest.py --effect rollback`
3. `sudo systemctl restart admin_bot`
4. Verify `/healthz` 200, version `2.58.224`, schema 48, settings unchanged, no new journal errors.
5. Data action: none. 2.58.225 has DDL 0 and schema 48; do not run schema downgrades or delete user data.

## 5. Known residual / limitations

- This assembly is REVIEW only: no production deploy, no live TMA, no VERIFIED claim.
- Playwright/Browser Use checks use a local synthetic API stand, not deployed production bytes.
- `MAC-S6-345`/`MAC-AC-15` remain partial (no full trace page); `MAC-S6-346` image-only remains a deterministic stub (RFL).
- w10/w15 full tools retain pre-existing non-B2 failures; w15 count is environment-dependent (71-73) with 0 status/observer-related.
- Broad JS 124/3 and version pins 856/4 are the same pre-existing base failures, not caused by this release and not counted as pass.
- NB-3/NB-4/NB-5/NB-6/BL-1 are nonblocking follow-ups/B3, not fixed.
