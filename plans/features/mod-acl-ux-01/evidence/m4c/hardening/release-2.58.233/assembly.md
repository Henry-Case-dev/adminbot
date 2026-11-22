# Release 2.58.233 — MOD-ACL-UX-01 M4C ACL-hardening S1/S2/S3

**Status:** REVIEW / **READY_FOR_DELTA_REVIEW** (assembly complete; no deploy, no VERIFIED).
Кандидат `c67fd490f` независимо **APPROVED_FOR_RELEASE_PREPARATION** (`review-r1.md` @ planning
master `3b7041024`); `M4C-HARD-R1-N01` — backlog-only. Release-сборка, bump, manifest и runbook
готовы; деплой и deployed-byte/live-data binding — только отдельной авторизацией. Не заявлять
VERIFIED до фактического deployed SHA и production-наблюдений.
**Date:** 2026-11-22 14:53 (+12:00) / 2026-11-22 02:53 UTC
**Branch:** `release/mod-acl-hardening-2.58.233`
**Base / rollback:** `462568ed7662cf5786a543bce8ecb6618e073c87` (2.58.232, schema 48, DDL 0)
**Candidate tip:** `c67fd490ff11f7c72bdd6cf82bef5513a8b29b3f`; product
`3b9909447982eadffb0c20beb266870b21eb2a3a` (base `462568ed7`)
**Review:** `plans/features/mod-acl-ux-01/evidence/m4c/hardening/review-r1.md` @ master `3b7041024`
(blob `dc7f2a36…`, sha256 `1796a5c7eae5f7b2248ae1b4a0de8ce0e1fd726c63c50248927a0a534a094fb3`,
18517 bytes) — APPROVED_FOR_RELEASE_PREPARATION; routes re-pin `453e17f8…`.
**Contract:** `plans/features/mod-acl-ux-01/evidence/m4c/acl-hardening-contract-2026-11-22.md`
@ master `1da5dd5b9` (blob `3e390808…`, sha256
`94ab8f1df4faf278fcc7fd58ab945a295d2cfb4c8d5c6bce3e9be2138d2a3eab`, 50303 bytes).
**Content tip (bump):** `aada3af8308149b989c543fa575b22c5736c17df`
**Version:** 2.58.233
**Schema/DDL:** 48 / 0
**Manifest dry-run:** `manifest-dry-run.json` (`deployed_sha = aada3af83…` = bump commit; docs
commit выше него, см. §5).

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | `workflow_housekeeping.py worktree-path` → `git worktree add <path> -b release/mod-acl-hardening-2.58.233 462568ed7` → `register-worktree` | Worktree `…/mod-acl-hardening-2-58-233-6be596e06fd2-8e3c6257`, clean at `462568ed7` |
| 2 | Cherry-pick `3b9909447^..c67fd490f` (3 commits, 0 merges, no force) | `12d25b566` S1/S2/S3, `97fcdad04` evidence, `7f88dfb4a` tests/evidence; 0 conflicts |
| 3 | Patch-id check of every cherry-pick | 3/3 **identical** patch-ids (candidate bytes preserved) |
| 4 | Tree equality vs candidate before bump | `git diff c67fd490f 7f88dfb4a` **empty**; tree `079fe5ab0…` both |
| 5 | Standard version wave 2.58.232 → 2.58.233 | `aada3af83`; **32 files, 35 insertions / 35 deletions**; settings line rewritten with a new changelog entry; `APP_VERSION` = 2.58.233 |
| 6 | Checks on bumped tip `aada3af83` | see §3/§4; all assigned batches below |
| 7 | Manifest dry-run on `aada3af83` | exit 0; version 2.58.233, previous `462568ed7`/2.58.232, `dirty_tracked=false`, `.deploy` reconstructed locally and removed |
| 8 | This evidence commit | docs-only; no product/test bytes change it |

- `git rev-list --merges 462568ed7..HEAD` = **0**; no rebase/new history of the deployed base.
- Product bytes are identical to the reviewed candidate:
  `git diff --stat c67fd490f..HEAD -- services web` — **empty**.
  The only changes after the candidate are the 32 version-literal files (bump wave).
- Patch-id mapping (original → release):
  `3b9909447→12d25b566` `9758517…`; `523b137df→97fcdad04` `ec8641d…`;
  `c67fd490f→7f88dfb4a` `2e60bc6…` — all match.

## 2. Product delta (base `462568ed7` → content tip `aada3af83`)

Product/test/tool delta (`services web tests tools`): **1205 / 150** across 38 files — reviewed
candidate product/tests/tool plus version literals in 30 test/tool files. Плюс `config/settings.py`,
`plans/docs/param-registry-round1025.meta.md` и candidate evidence (27 files, 1123 / 2).
Итого base→content tip: **65 files, 2328 / 152**.

| File | Net base→tip |
|---|---|
| `web/api/routes.py` | **179 / 103** (5 guards → `requires_global_admin()`; S2 I1/I2 guard in `post_admins`/`remove_admin`/`post_roles`; per-app `_acl_mutation_lock` around snapshot→guard→write→reload) |
| `services/roles.py` | 64 / 1 (аддитивные pure-helpers `is_effective_global_admin_role`, `assigned_global_admin_ids`, `assigned_wildcard_admin_ids`, `guard_admin_lockout`) |
| `services/access_preview.py` | 14 / 7 (только `consumers` metadata `section.access`: role-layer = read-GET; ceiling-layer += 5 write-маршрутов; guard-подпись S1) |
| `web/index.html` | 6 / 2 (`#/access/admins`: `v-if="isGlobalAdmin"` на «Удалить»/add-блоке, подпись `data-admins-readonly` «Только просмотр»; LF сохранён) |
| `tests/test_mod_acl_ux_m4c_acl_hardening.py` | 652 / 0 (new; 63 tests: negative-матрица, takeover, S2-сценарии, anti-drift, concurrency) |
| `tools/ui_mod_acl_m4c_hardening_admins_e2e.py` | 240 / 0 (new Playwright e2e admins-модалки) |
| `tests/test_webapp_access_matrix_read.py` | 4 / 2 (только docstring «S1 закрыт»; assertions не менялись) |
| `tests/test_mca23_planned_vs_actual.py`, `tests/test_round1025_f8_registry.py` | re-pin `ROUTES_SHA256_F11 = 453e17f8a1cd29d54fcdb187a6c6ccac53673426d3c284e6db2672acdeb604a5` (NOTE L-F11S-1, Δ routes=0) |
| 32 version-wave files | 35 / 35 (version literals only; settings line + new changelog entry) |
| `plans/docs/param-registry-round1025.meta.md` | 1 / 1 (версия в meta) |

- Behavior (reviewed candidate): мутации ролей/глобальных админов — только effective global admin
  (`role_type=global_admin` | `wildcard` | legacy имя `admin`) на 5 write-маршрутах; чтение
  ролей/админов/дерева остаётся `section.access`. Lockout-инварианты по **назначенным** админам:
  I2 (последний wildcard-админ) и I1 (последний effective-global админ), блокируется только переход
  `>0 → 0`; применяются в `post_admins`, `remove_admin`, `post_roles` (снятие wildcard с роли).
  `guard_last_wildcard` (role-level), `len(admins)<=1`, superuser/builtin/usage guards сохранены.
- Concurrency: per-app `asyncio.Lock` (`app.state`, loop-keyed) охватывает снимок → guard → запись →
  reload в 5 write-маршрутах. Это достаточно **только для одного процесса**; single-process
  preflight обязателен в runbook (§0/§2) — при >1 процессе деплой останавливается и эскалируется
  Architect.
- Honesty: `services/access_preview.py` изменён только в `consumers`/guard-подписи, чтобы preview
  не утверждал несуществующий write-путь; resolver/layers/decision/response/strict не менялись.
  Admins-модалка для non-global показывает список без add/remove (честный read-only).
- No flags: S1/S2 действуют безусловно; «factory-off» состояния нет. C1/C2 страницы и `web/app.js`
  не перестраивались.

## 3. Bump and invariants

- `APP_VERSION` AST/string/import = **2.58.233**; `plans/docs/param-registry-round1025.meta.md`
  pinned `2.58.233`; JS regex pins use `2\.58\.233` (4 files); tools pins 233.
- Standard wave is exactly **32 files / 35 / 35** (`git diff --stat HEAD~1 HEAD`), matching the
  previous-release wave. BOM/CRLF/LF profile verified against the base blob for all 32 files:
  **0 mismatches**; `settings.py` keeps UTF-8 BOM + 3645 CRLF.
- `git grep` finds no live `2.58.232` pin outside historical evidence/planning: the only remaining
  hit is the settings changelog (`База: 462568ed7 (2.58.232). Prior 2.58.232 - …`) inside the new
  entry plus historical `plans/features/**/evidence/**`, `plans/backlog.md`, maps and
  `progress_scope.json`/`workflow_state.md` (not modified here).
- `web/api/routes.py` route set unchanged: `api_router` decorators base=76, release=76; both F8
  pins re-pointed to `453e17f8a1cd29d5…`. `web/api/access.py` byte-identical (9 write decorators).
- Byte-identical to base: `web/api/access.py`, `web/api/deps.py`, `services/permissions.py`,
  `services/access.py`, `services/config_cache.py`, `services/pg_db.py`, `services/database.py`,
  `services/param_catalog.py`, `web/app.js` (sha1 in `test-output/invariants.txt`) → schema **48 /
  DDL 0**; no flags/prompts/models/keys/chat overrides changed.
- `node --check web/app.js` rc=0; `py_compile` changed Python rc=0.
- `git diff --check 462568ed7..HEAD` reports two **pre-existing** trailing-whitespace lines in
  approved candidate evidence text (`evidence/m4c/hardening/test-output/focused.txt:26`,
  `pin-guard.txt:305`); they are not modified in the release lane (changing candidate evidence
  bytes would invalidate the review). `git diff --check` for the bump commit itself is clean.
- PEP/BOM/CRLF: `web/index.html` (candidate change) keeps LF and its existing BOM/encoding profile;
  settings.py BOM/CRLF preserved by the bump.

## 4. Tests on bumped tip `aada3af83`

Machine-readable: `tests-2.58.233.json`; compact: `tests-2.58.233.txt`; raw outputs: `test-output/`.

| Batch | Result |
|---|---|
| `tests/test_mod_acl_ux_m4c_acl_hardening.py` | **63 passed**, 1 warning (6.34 s) |
| C1 `tests/test_webapp_access_matrix_read.py` | **17 passed**, 1 warning (4.57 s) |
| C2 `tests/test_webapp_access_effective.py` | **124 passed**, 1 warning (14.52 s) |
| Route pins (`test_round1025_f8_registry.py` + `test_mca23_planned_vs_actual.py`) | **53 passed** (4.73 s) |
| Focused 10-file (contract §5.3 + C1-adjacent) | **334 passed, 2 failed** (22.16 s) — exactly the two pre-existing node IDs: `prompt_field_audit` reachable surface, `hubs_matrix_ui` r4_custom_modules_removed |
| Pin-guard, 24 Python version-pin files | **856 passed, 4 failed** (71.08 s) — same four pre-existing node IDs as 2.58.232/candidate evidence |
| Node suites (9 scripts) | 9/9 rc=0 (M4C2 preview/admins, M4C1 roles/editor, methods-dup, hotfix7–10) |
| Hardening admins Playwright | **PASS 0 failures**; 1440×900/390×844; non-global 0 remove/0 add + «Только просмотр», global controls present |
| C1 Playwright e2e | **PASS 0 failures** |
| C2 Playwright e2e | **PASS 0 failures** |
| B1 / B2 / B3 | **138/0**, **92/0**, **131/131** (8 screenshots) |
| Schema smoke (temp SQLite) | target 48, `user_version=48`, `schema_migrations` max/count 48, tables 101 |
| Syntax | `py_compile` rc=0; `node --check` rc=0; route decorators 76 |
| Bump profile | 32 files, BOM/CRLF/LF identical, 0 mismatches |
| Post-changelog version pins | 58 passed (4.11 s) after the final settings comment edit; imported `APP_VERSION == "2.58.233"` |

Notes:
- The two focused failures and four pin-guard failures are identical node IDs to the 2.58.232
  assembly (334/2, 856/4) and to the candidate evidence; the affected tests/paths are not touched
  by S1/S2/S3 beyond the version literal.
- Playwright/Browser Use ran on the local deterministic stand with API stubs and `TMA_STUB`, not
  live TMA; candidate evidence already contains the Browser Use screenshot/report. No production
  access was used.

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: `deployed_sha=aada3af83…` (content/bump tip), `version=2.58.233`,
  `previous_sha=462568ed7…` / `2.58.232`, `release_branch=release/mod-acl-hardening-2.58.233`,
  `dirty_tracked=false`, exit 0. The `.deploy` previous-manifest input was reconstructed locally
  (git-ignored) and removed; production files were not read.
- Rollback/base: `462568ed7` (2.58.232), schema 48/DDL 0; no migration/data/settings action.
  Rollback restores the previous (pre-hardening) ACL boundary — apply only for a proven candidate
  regression, then re-issue the fix.
- `deploy-runbook-2.58.233.md`: **single-process preflight first** (`systemctl show admin_bot
  -p MainPID -p NRestarts`, `pgrep -af bot.py`; >1 process → stop/escalate Architect), then
  read-only production preflight (`bot_roles` 4 / `bot_admins` 3 / `chat_admins` 1, custom
  access/wildcard 0; unexpected global/wildcard → no deploy), backup keep=2, manifest actual HEAD,
  restart, local/public health, version/identity, schema 48/DDL 0, `NRestarts`, journal,
  settings/prompt digests, ACL data digests unchanged, served bytes, `POST /api/admins` без
  initData → 401, read-only GET при доступной сессии (иначе RFL), 0 ERROR, disk
  `audit`/`cleanup --apply`, no live-chat/LLM, rollback `462568ed7`.

## 6. Commits

```
aada3af83 chore(release): 2.58.233 - bump APP_VERSION и пинов версии (ACL hardening)
7f88dfb4a test(acl): legacy-admin positive write case + evidence sync (M4C S1/S2/S3)
97fcdad04 docs(evidence): M4C ACL-hardening S1/S2/S3 implementation, RED/mutations, UI (M4C)
12d25b566 fix(acl): role/admin mutations global-admin-only + last-admin invariants (M4C S1/S2/S3)
```

The docs/evidence commit is created after this table; `git log --oneline 462568ed7..HEAD` is the
authoritative list. No merge commits, no force operations.

## 7. Evidence digests

| Artifact | Bytes | sha256 |
|---|---|---|
| `tests-2.58.233.json` | 11033 | `2f51a564c89687d16c82673585c6f7a7b93f04c7d6e54160320c8f6ca878bbff` |
| `tests-2.58.233.txt` | 2690 | `e30419b2ce79c55ae1455f070a9b5136f231290cc9143050aea770705af5fc89` |
| `manifest-dry-run.json` | 1560 | `42dfbf867ab927da54d052dba1f63f68f0e9d04f0e28bf8edd5e24b86b9296b5` |
| `deploy-runbook-2.58.233.md` | 14486 | `21b383cc24a7506f700ea7c05c3e642fb33ff61035917a142156627b98f77e19` |

Review/contract digests are canonical git blobs on planning master (§ header); they are not
duplicated into the release branch.

## 8. Residual / limitations

- No production access, SSH, deploy, live TMA or VERIFIED claim in this assembly. Playwright/
  Browser Use used the local deterministic stand with API stubs and `TMA_STUB`; visual/layout
  proof applies to candidate bytes, production semantics are not claimed.
- **Single-process precondition not verified here** (no production access): mandatory pre-deploy
  step; the per-app lock does not give global atomicity across processes.
- `M4C-HARD-R1-N01` (post_admins role pre-check outside the ACL lock → FK error/500 on concurrent
  `delete_role`) remains BACKLOG_ONLY; S1/S2 security boundary and lockout invariants are not
  affected. Not fixed in the release lane (would invalidate the reviewed candidate).
- Live non-global TMA (SCN-01) remains **RFL**, not owner QA. Positive owner write is not executed
  in production (deterministic tests cover it). C3 (revisions/409, durable audit, chat-override
  DELETE, recheck, DDL 1) is out of scope.
- The two evidence-text trailing-whitespace lines and the six pre-existing test node IDs are
  documented above; no assertion was weakened to make a suite green.
