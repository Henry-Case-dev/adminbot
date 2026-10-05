# deployment.md - mca-09-intents-initiative (prod 2.58.60)

**Feature:** `mca-09-intents-initiative` (T-5044) - Risk R3 - **status: VERIFIED**
**Completed:** 05.10.2026 (boot #1 08:31:03 UTC, ready 08:33:50 UTC; boot #2 08:39:30 UTC) - step @DevOps T-5044 (reviewer **Approved** T-5043 + addendum "F-2 resolved - micro-fix recheck"; binding: HEAD `28a05e2` + WTH-manifest `plans/reports/mca09_wth_manifest_review.txt` v2, 28 files).

## 1. Preflight (binding)

- HEAD local == `28a05e2` == origin/master (pre-push); review/pine + addendum "F-2 resolved" are present, verdict **Approved** unchanged.
- Candidate per manifest **27/28 files byte-for-byte = are recorded digests** (`sha256` recomputed per file, no drift); **1/28** - `plans/features/mca-09-intents-initiative/review.md`: recorded digest `ce16ec7b…` = **byte-for-byte prefix** of current file (addendum added post-snapshot - a declared process artifact in the manifest header, not code).
- **[P-1] Recipe of aggregate digest** `6d6b6d74…9e63a` is not reproduced @DevOps from the assembled body (291+ variants scanned incl. the documented mca-16 recipe `hash␣␣path`, LF/path-sorted/digest-sorted): the author's algorithm is not documented in the manifest. The operational gate of the binding from the mca-15 precedent is applied - per-file identity 28/28 against the review snapshot + declared delta. Not a blocker; at the next cycle - to duplicate the recipe into the manifest header.
- Prod pre-check: HEAD `6b3d421` (2.58.59), PID 3835578, active, NRestarts 0, `/healthz` 200 `2.58.59`; SQLite **v28** (schema_migrations 17, 108 tables; `mca_intents` absent), K1-K4 without env-overrides. Pre-counters: task_jobs 650, mca_events 10645, mca_bot_outputs 80, summary_runs 14, mca_random_draws 0, mca_intents ABSENT.

## 2. Version bump CA-11 + commits (explicit paths, not `git add -A`)

- **Bump 2.58.59→2.58.60**: `config/settings.py` `APP_VERSION` **2.58.60** + `README.md` header + F8 meta-pin `plans/docs/param-registry-round1025.meta.md` + **20 py release-pin files** (by convention, historical markdown in docstrings/comments is untouched).
- **feat `1db6931`** - 45 files (+4246/−37): 21 runtime/test manifest manifest files (`services/mca_intents.py`, `direct_chat_service.py`, `provenance.py`, `memory_maintenance.py`, `mca_gates.py`, `mca_events.py`, `mca_process_registry.py`, `database.py` v29 register MigrationStep(29), `status_service.py`, `nostalgia_worker.py`, `bot.py`, `config/settings.py`, 6 mca09 tests + `test_mca05…`, `test_mca16_experience_block_a…`, `test_status_service.py`) + bump-sweep + `tools/_mca09_release_bump.py`.
  - **[D-1] Matched release-sweep of mca-01 counter** (`tests/test_mca01_tx_task_supervisor_round1027.py`: allow `database.py` 168 → **171**, comment "+3 v29 mca-09 ADR-1028-16 D8/§11.1, L-MCA14-3"): a review defect (the manifest did not include this file; Reviewer's batches did not include mca-01). Without this, migration-frontier test red was being shipped. The delta = sanctioned v29 DDL (verified: 3 `commit` strictly within `_migrate_intents_v29`). Precedent of release-pin conventions of past deployments; done @DevOps (no product-code changes).
- **docs `d654a6a`** - 8 files: `plans/features/mca-09-intents-initiative/{spec.md, adr-1028-16-intents-initiative.md, threat-failure-analysis.md, tasks.md, requirements-map.md, evidence.md, review.md}` + reviewer WTH-manifest.
- deploy-doc: this file (after deploy).
- If not staged (`plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, untracked debris `node_modules/`, `package*.json`, `.playwright-mcp/`, `tools/_ui_asap43_*`, `plans/verification_cache.json`) ✔.

## 3. Prod-migration (mca-14, Δ DDL = v29)

- **Manual backup @DevOps BEFORE ff/restart:** `pre_migration_devops_20261005_082851.db` **1 385 230 336 B (1.385 GB)**, read-back sha256 OK (`96a7d8a4…`, source==copy), `user_version=28`.
- **Guard mca-14 at boot BEFORE applying (fail-closed):** `Oct 05 08:33:47 UTC services.memory_backup INFO: pre-migration copy created + read-back ok | target_version=28` → `/var/www/admin_bot/pre_migration_20261005_083120.db` **1 317 298 176 B (1.317 GB)** - rollback anchor.
  - Note: disk_retention rotated out both previous guards (mca-16 `pre_migration_20261005_055136.db`) and the manual DevOps copy with one pass by the "keep 2 newest" policy (expected action of the existing retention; the fact is recorded - the only current anchor is the mca-14 guard @v28; daily backups `/home/nik/backups` were not touched).
- **Migration v28→v29 applied:** journal `[database] migration v29: mca_intents` + `migration v29 applied | intents`; `PRAGMA user_version` **29**; `schema_migrations` **18** with a book entry **`(29, intents)` - exactly 1 time**; tables **108→109** (`mca_intents`); **4 declared indexes** (`idx_mca_intents_{dedup, chat_status_due, status_due, chat_kind_status}`; all UNIQUE `dedup_key` = `sqlite_autoindex…_1` from the PK) - full set per sanctions ADR-1028-16 D8/§11.1. `integrity_check` = ok.
- **Idempotency:** second restart (08:39:30 UTC, PID 3868248) - **no-op**: no DDL/guard actions in the journal (only INFO of prompt/config-migrations), `user_version 29`, sm 18, tables 109, book29=1, no new pre_migration in the boot window (the guard does not create a copy without pending migration); healthz 200 @2.58.60, NRestarts 0, ExecMainStatus 0.
- **PG - no-op** (`services/pg_db.py` outside candidate; Δ PG DDL = 0; at boot - regular pool/`DDL ok` without changes), sanctioned SQLite-only v29.

## 4. Health / smoke / kill-switches

- `/healthz` **200 `{"status":"ok","version":"2.58.60"}`** (boot #1 after migration 08:33:47, full readiness ~2.5 min: mca-14 guard 1.317 GB takes time); `/api/health` **200** (both boots); `/web/` **200**, served `app.js?v=2.58.60`.
- **Heartbeat-activation:** digest "Added job `MemoryMaintenanceService._tick_intent_heartbeat`" (K1/K2 default ON). No creation of intent/no state changes from DevOps (PENDING OWNER live-approach sanity maintained).
- `.env`/systemd: **0 env-overrides per K1 `MCA_INTENTS_ENABLED`/K2 `MCA_INTENT_HEARTBEAT_ENABLED`/K3 `MCA_INTENT_DECISION_ENABLED`/K4 `MCA_SEND_RECHECK_ENABLED`** → all **default ON**; env-limits by defaults (20/3/8/180/1800). Counter/override/config DevOps did not change.
- Logs: boot #1 - **0 ERROR/CRITICAL/Traceback deployment nature** (see [I-2]); boot #2 - 0 ERROR/CRITICAL/Traceback. **R17 = 0** (secrets are not in the code/journal; the delivery window did not leak them).

## 5. Data / counters / F8

- SQLite spot-checks (pre → post boot #1 → post boot #2): `task_jobs` 650→651→652 (live-works), `mca_events` 10645→10647→10666 (live), `mca_bot_outputs` 80→81→81, `summary_runs` 14=14, `mca_random_state` 1=1, `mca_random_draws` 0=0; the new table `mca_intents` = **0** (heartbeats work, but no owner candidates in the lives of real chats - the events stay empty; reading "not_run" is honest). Catalog **504** not touched (Δ catalog = 0; F8 `NOT_APPLICABLE`); counters F8 matches the sanction (registry-test local 155 passed).

## 6. Checks (without full suite)

| Check | Result |
|---|---|
| focused mca09 (6 files, .venv) | **78 passed / 0** (aligned with Reviewer recheck 77+1) |
| slice `-k test_mca` | **1195 passed / 1** - `test_registry_process_intent_initiative` - order-pollution false-positive (see [I-1]) |
| migration-frontier batch ×8 (`test_database`, `test_mca14_schema_additive…`, `test_history_migration_v7`, `test_migrate_direct_chat_v2_script`, `test_migrate_epic60_v3_script`, `test_mca05…`, `test_mca04b…`, `test_graphrag_database`) | **288 passed / 0** (after [D-1]) |
| affected batch (A7 + mca-07/08/13/17a/22, 9 files) | **625 passed / 0** |
| adjacent F8/status/mca05/mca16a | 155 passed |
| prod-venv (focused mca09, 2.58.60 checkout, before restart#2) | **78 passed / 0** (32.34 s) |

## 7. Findings/incidentals

- **[D-1] mca-01 counter-sweep** (deploy-owned, see §2) - it is mandatory to hold @Reviewer/PM visual: 3 added `commit` in `_migrate_intents_v29`, risk of product-code entry - zero.
- **[I-1] (Low, test-hygiene, not a blocker)** `test_mca09_intents_block_e::test_registry_process_intent_initiative` is flawed to settings-reload pollution (mca-01/13/17a make `importlib.reload(config.settings)` → a `type(settings)`-doublet; OFF-check catches a stale singleton → "implemented" instead of "disabled"). In isolation/Reviewer batches - green (78/78), only in a combined slice. Fix - to Builder backlog (doublet hygiene/test rationalization), NOT inside the current binding (manifest-pinned file).
- **[I-2] (Info, pre-existing)** one familiar serviceability-exception of embedding quota (`EmbeddingGroupCoolingDown` printed as Traceback during a live embed attempt 08:34:19, then memorize continues - fail-open known class from mca-16 review) + `tavily` 400-WARN partner fallback. Not related to mca-09 delta; no immediate prod risk; the "0 Traceback" criterion for boot #2 is satisfied fully.
- **[P-1]** recipe-aggregate digest of the reviewer's WTH-manifest - see §1.
- Retention rotated the bombs properly (§3) - a caution for future deploys: an individual DevOps backup IN the prod directory is not durable; E off-site/daily anchors are needed for a long store.

## 8. Rollback

- **Soft:** K1 `MCA_INTENTS_ENABLED=false` (+ additionally K2–K4) in env + restart - **OFF = bit-for-bit 2.58.59**: v29 is not read/written, the heartbeat job is not registered, candidates/events do not diverge, nostalgia - legacy; v29 is additive/inert (old code does not read it, but reverses are not required).
- **Cold:** `git revert` `1db6931` / checkout checkout `28a05e2` (=2.58.59; user_version 29 multivalid, old runner accepts it as the target); restore from `pre_migration_20261005_083120.db` is NOT required (v29 additive), an emergency restore anchor per R18.
- Live data in `mca_intents` (if candidate intents appear in the lives of owner chats before rollback) would be lost in a cold revert - fail-safe scope: the air path stops, archive events remain in `mca_events`.

## 9. Live-approach

**Live T-5045 - [PENDING OWNER]** (real chat, no simulation; turn heartbeat→candidate→decision scenario per spec §21/backlog; DevOps did not create intents and did not change states). Deploy machine confirms: **live T-5045 CAN proceed**.
