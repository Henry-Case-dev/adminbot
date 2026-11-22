# Release 2.58.232 — MOD-ACL-UX-01 M4C C2: read-only «Проверить доступ» (effective/preview)

**Status:** REVIEW / **READY_FOR_DELTA_REVIEW** (assembly complete; no deploy, no VERIFIED).
Кандидат `e20f58204` независимо **APPROVED_FOR_RELEASE_PREPARATION** (`review-r1.md` @ master
`a4d3ce033`, addendum_c4). Release-сборка, bump, manifest и runbook готовы; деплой и
deployed-byte/live-data binding — только отдельной авторизацией. Не заявлять VERIFIED до
фактического deployed SHA и production-наблюдений.
**Date:** 2026-11-22 12:06 (+12:00) / 2026-11-22 00:06 UTC
**Branch:** `release/mod-acl-m4c2-2.58.232`
**Base / rollback:** `7a4d5724da04fd34821584717d63657f6fc53a50` (2.58.231, schema 48, DDL 0)
**C2 candidate:** `e20f58204a9ebc377a4c061c475f4edb61777f19`, base `d86bf66d408266c928e24714c2f5779a4ddf8ebe` (2.58.230)
**Review:** `plans/features/mod-acl-ux-01/evidence/m4c/c2/review-r1.md` @ master `a4d3ce033`
(blob `c9623a4c4…`, sha256 `7c2f51f04d4d78c3c84f6449560a7f5f544c2257b356280acd4d64f8336ac8b7`,
34191 bytes) — addendum_c4 `APPROVED_FOR_RELEASE_PREPARATION`; C2-R1-5/6 backlog-only.
**Contract:** `plans/features/mod-acl-ux-01/evidence/m4c/c2-contract-2026-11-22.md` @ master
`a4d3ce033` (blob `59192a6b6…`, sha256 `0b9fdcef80bca3d3873dda1f743e381b82053932b4710d52cda542ecf68533cf`,
74117 bytes).
**Content tip (bump):** `0fcba327fab8111c666501ff75d00f4c3dcefae0`
**Version:** 2.58.232
**Schema/DDL:** 48 / 0
**Manifest dry-run:** `manifest-dry-run.json` (`deployed_sha = 0fcba327f…` = bump commit; docs
commit выше него, см. §6).

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | `workflow_housekeeping.py worktree-path` → `git worktree add <path> -b release/mod-acl-m4c2-2.58.232 7a4d5724d` → `register-worktree` | Worktree `…/mod-acl-ux-01-1e46be007668-266578a9`, clean at `7a4d5724d` |
| 2 | Cherry-pick `8e50b0fa3^..e20f58204` (5 commits, 0 merges, no force) | `9b677267d` C2a, `3f39e7468` C2b, `946cb7458` evidence, `535d88f25` R1 blockers, `fc7c6d4b6` c4; 0 conflicts |
| 3 | Patch-id check of every cherry-pick | 5/5 **identical** patch-ids (C2 bytes preserved) |
| 4 | Standard version wave 2.58.231 → 2.58.232 | `0fcba327f`; **32 files, 35 insertions / 35 deletions**; settings line rewritten with a new changelog entry |
| 5 | Checks on bumped tip `0fcba327f` | see §4; all assigned batches below |
| 6 | Manifest dry-run on `0fcba327f` | exit 0; version 2.58.232, previous `7a4d5724d`/2.58.231, `dirty_tracked=false`, `.deploy` reconstructed locally and removed |
| 7 | This evidence commit | docs-only; no product/test bytes change it |

- `git rev-list --merges 7a4d5724d..HEAD` = **0**; no rebase/new history of the deployed base.
- C2 file bytes are identical between the approved tip `e20f58204` and the release content tip:
  `git diff --name-only e20f58204 0fcba327f -- services/access.py services/access_errors.py
  services/access_preview.py services/chat_params.py services/roles.py web/api/access.py
  web/app.js web/index.html web/static/app.css tests/test_webapp_access_effective.py
  tests/js/mod_acl_ux_m4c2_*.js tools/ui_mod_acl_m4c2_preview_e2e.py
  plans/features/mod-acl-ux-01/evidence/m4c/c2` — **empty**.
- Patch-id mapping (original → release):
  `8e50b0fa3→9b677267d` `49470d53…`; `bc742adc0→3f39e7468` `001068a2…`;
  `ba8b93121→946cb7458` `ac1104dc…`; `ece63acac→535d88f25` `67ef6a34…`;
  `e20f58204→fc7c6d4b6` `4eac2f8e…` — all match.

## 2. Product delta (base `7a4d5724d` → content tip `0fcba327f`)

C2 product/test/tool: **4890 / 10** across 13 files; 32 version-wave files; 33 C2 evidence files.

| File | Net base→tip |
|---|---|
| `services/access_preview.py` | **904 / 0** (new read-model/layers/validation) |
| `services/access_errors.py` | 15 / 0 (new `AccessStorageUnavailable`) |
| `services/access.py` | 67 / 2 (`param_permissions_snapshot`, `normalize_permission_override`, re-export) |
| `services/roles.py` | 27 / 3 (`access_for(..., strict=False)` + raise branches, additive) |
| `services/chat_params.py` | 30 / 0 (`read_chat_params_strict`, additive, no cache) |
| `web/api/access.py` | 169 / 2 (3 GET + auth/error mapping + F-C2-1) |
| `web/app.js` | 484 / 3 (preview state/methods, stale generation, noActor-after-admins, 3 gate marker lines) |
| `web/index.html` | 189 / 0 (preview inside factual gates, subtitle) |
| `web/static/app.css` | 59 / 0 (form/layers/mobile stack/touch) |
| `tests/test_webapp_access_effective.py` | 1374 / 0 (new, 124 tests) |
| `tests/js/mod_acl_ux_m4c2_preview_test.js` | 630 / 0 (new) |
| `tests/js/mod_acl_ux_m4c2_admins_seed_test.js` | 135 / 0 (new) |
| `tools/ui_mod_acl_m4c2_preview_e2e.py` | 807 / 0 (new) |
| 32 version-wave files | 35 / 35 (version literals only; settings line + new changelog entry) |
| C2 evidence (`plans/…/m4c/c2/**`) | docs/screenshots (no product bytes) |

- Behavior (reviewed c4): read-only effective/preview «Проверить доступ» в «Фактических гейтах»
  по существующим ACL-владельцам (`roles.access_for(strict=True)`, `permissions`, `access.*`,
  `chat_params.read_chat_params_strict`, `access.param_permissions_snapshot`) — без второго
  ACL/store и без новых write-путей. Три аддитивных GET; strict-режим отдаёт **503** вместо
  ложного deny; значения/промпты/hidden-ключи не раскрываются (no-leak sentinel).
- Section honesty (C2-R1-3/R1-9/R1-10 closed): `section.access` — реальный role+ceiling guard и
  только реальные `/api/roles|/api/admins` consumers; `section.limits/content/keys/…` — coverage
  через `deps.can_edit_param`/`can_view_key_value` без выдуманного endpoint-guard; chat/DM
  `section.*` (кроме `chat_lore`) — `not_applicable` (scope_capability); `/api/cover*` больше не
  числится в role consumers `section.access`.
- UI honesty: смена actor/scope/resource инвалидирует in-flight ответы; `noActor` — только после
  успешной загрузки назначений; non-admin видит только self; 401/403/404/422/503 — разными
  карточками; preview не добавляет POST/PUT/DELETE; 9 write-декораторов `access_router`
  сохранены.
- C1 18 rows remain **VERIFIED-bound** to deployed 2.58.229 (C1 binding 2026-11-22); C2 не
  понижает C1 read part (`MAC-S8-522`) и `MAC-AC-13`.
- `MAC-S8-520` / `MAC-S8-PREV-01`: **PENDING deploy/live-data binding** (C2 code acceptance
  пройдена); `MAC-S8-523` / `MAC-S8-505` — PENDING C3; `BL-M4C-PREVIEW-FAILOPEN` — closed;
  C2-R1-5/6 — backlog-only; SCN-01 / live non-global TMA — **RFL**, не owner QA.

## 3. Bump and invariants

- `APP_VERSION` AST/string/import = **2.58.232**; `plans/docs/param-registry-round1025.meta.md`
  pinned `2.58.232`; JS regex pins use `2\.58\.232` (4 files); tools pins 232.
- Standard wave is exactly **32 files / 35 / 35** (`git show --stat 0fcba327f`), matching the
  previous-release wave. BOM/CRLF/LF profile verified against the parent blob for all 32 files:
  **0 mismatches**; `settings.py` keeps UTF-8 BOM + 3645 CRLF.
- `git grep` finds no live `2.58.231` pin outside historical evidence: remaining references are
  the settings changelog ("Prior 2.58.231", "База: 7a4d5724d (2.58.231)") and
  `plans/features/p0-embed-503-failover/evidence/release-2.58.231/**`. Remaining `2.58.230`
  references are code comments/docstrings and old evidence, not pins.
- `web/api/routes.py`, `web/api/deps.py`, `services/permissions.py`, `services/pg_db.py`,
  `services/param_catalog.py`, `services/config_cache.py`, `services/database.py`, `migrations`
  are identical to base; schema remains **48 / DDL 0**; no flags/prompts/models/keys/chat
  overrides changed.
- `node --check web/app.js` rc=0; `py_compile` changed Python rc=0.
- `git diff --check 7a4d5724d..HEAD` reports one **pre-existing** trailing-whitespace line in
  `services/access_preview.py:350` from the approved candidate; it is **not modified** in the
  release lane (changing candidate bytes would invalidate the review). `git diff --check` for the
  bump commit itself is clean.

## 4. Tests on bumped tip `0fcba327f`

Machine-readable: `tests-2.58.232.json`; raw outputs: `test-output/`.

| Batch | Result |
|---|---|
| `tests/test_webapp_access_effective.py` | **124 passed**, 1 warning (17.44 s) |
| `tests/test_webapp_access_matrix_read.py` (C1) | **17 passed**, 1 warning (4.70 s) |
| Focused 10-file (contract §7.4 + C1-adjacent) | **334 passed, 2 failed** (23.62 s) — exactly the two pre-existing node IDs: `prompt_field_audit` reachable surface, `hubs_matrix_ui` r4_custom_modules_removed |
| Pin-guard, 24 Python version-pin files | **856 passed, 4 failed** (73.74 s) — same four pre-existing node IDs as C1/C2 evidence; routes.py unchanged, no re-pin |
| Node C2 | preview PASS rc=0; admins-seed PASS rc=0 |
| Node C1 | roles-page PASS rc=0; methods-dup-keys guard OK rc=0 |
| JS version pins | 4/4 rc=0 (`2\.58\.232`) |
| C2 Playwright e2e | **PASS 0 failures**; 6 viewports + in-flight `/api/admins` 1440/1280 |
| C1 Playwright e2e | **PASS 0 failures**; C1 unchanged |
| B1 / B2 / B3 | **138/0**, **92/0**, **131/0** (8 screenshots in B3) |
| Schema smoke (temp SQLite) | target 48, `user_version=48`, `schema_migrations` max/count 48, tables 101 |
| Syntax | `py_compile` rc=0; `node --check` rc=0 |
| Bump profile | 32 files, BOM/CRLF/LF identical, 0 mismatches |

**Additional observation — `tools/ui_round1025_matrix.py` (not declared green):** base
`7a4d5724d` = **131 failures, 0 TypeError**; candidate 2.58.232 = **134 failures**, of which
**+3** are `console/pageerror` at 390x844 / 430x932 / 768x1024:
`TypeError: Cannot read properties of undefined (reading 'length')` at
`previewResourceSuggestions` (`web/app.js:33749`). The matrix `_stub_for()` returns `{}` for the
unstubbed `/api/roles/tree`; C2 reads `t.sections.length` without an array guard. The real
endpoint returns `sections` (C1/C2 e2e stubs do), so it is not reproduced with the endpoint shape
and no live breakage is claimed. Recorded as an **OPEN delta-review observation**; the release
lane does not rewrite approved candidate code. The other 131 matrix failures are identical to
base (stale F11/workspace/glass expectations).

## 5. Manifest, rollback, runbook

- `manifest-dry-run.json`: `deployed_sha=0fcba327f…` (content/bump tip), `version=2.58.232`,
  `previous_sha=7a4d5724d…` / `2.58.231`, `release_branch=release/mod-acl-m4c2-2.58.232`,
  `dirty_tracked=false`, exit 0. The `.deploy` previous-manifest input was reconstructed locally
  (git-ignored) and removed; production files were not read.
- Rollback/base: `7a4d5724d` (2.58.231), schema 48/DDL 0; no migration/data/settings action.
- `deploy-runbook-2.58.232.md`: production preflight read-only `bot_roles`/`bot_admins`
  (expected 4 built-ins / 3 assignments / 0 custom `section.access`; a custom `section.access`
  role → S1 signal, stop before deploy), backup keep=2, manifest actual HEAD, restart,
  local/public health, version/identity, schema 48/DDL 0, `NRestarts`, journal, settings/prompt
  digests, served bytes, C2 read-only preview matrix, disk `audit`/`cleanup --apply`, no
  live-chat/LLM, SCN-01 RFL, rollback.

## 6. Commits

```
0fcba327f chore(release): 2.58.232 - bump APP_VERSION и пинов версии (M4C C2)
fc7c6d4b6 fix(access): C2 c4 - section coverage parity + chat/DM scope not_applicable
535d88f25 fix(access): C2 R1 blockers - stale in-flight, key/config parity, honest section guards, noActor after admins
946cb7458 evidence(access): M4C C2 read-model/UI proof (tests, e2e, mutations, BU)
3f39e7468 feat(access-ui): C2b «Проверить доступ» preview in factual gates
9b677267d feat(access): C2a read-only effective/preview read-model (strict ACL reads)
```

The docs/evidence commit is created after this table; `git log --oneline 7a4d5724d..HEAD` is the
authoritative list. No merge commits, no force operations.

## 7. Evidence digests

| Artifact | Bytes | sha256 |
|---|---|---|
| `tests-2.58.232.json` | 9724 | `2da2d00ed87f79fb73fa09b45175864d66b997c4ae4dd08c17ee411fbe3f61cb` |
| `tests-2.58.232.txt` | 5281 | `217e0798e25c3b21df241bea42a4261ae5fb5e44bb1a5a480b6d60523c9579a8` |
| `manifest-dry-run.json` | 2269 | `b753e15cb9c351c83402474562c1c0f994fa54d6b3c5eebafba819a3349312a0` |
| `deploy-runbook-2.58.232.md` | 12717 | `49015701a756813e5cc23dadecd692ffdc89807517ab40066ce1291599a7ac3b` |

Review/contract digests are canonical git blobs on master `a4d3ce033` (§ header); they are not
duplicated into the release branch.

## 8. Residual / limitations

- No production access, SSH, deploy, live TMA or VERIFIED claim in this assembly. Playwright/
  Browser Use used the local deterministic stand with API stubs and `TMA_STUB`; visual/layout
  proof applies to candidate bytes, production semantics are not claimed.
- `ui_round1025_matrix` has 131 pre-existing failures on base and +3 C2 harness-only console
  errors; it is not green and is explicitly flagged for delta review (see §4).
- C2-R1-5/C2-R1-6 remain backlog-only; C3 (S8-523/S8-505: recheck/save, durable audit/who
  changed, revisions/409) and S1 hardening are out of C2 scope.
- `MAC-S8-520` / `MAC-S8-PREV-01` stay PENDING until deployed-byte and live-data binding; live
  non-global TMA and SCN-01 remain RFL, not owner QA.
