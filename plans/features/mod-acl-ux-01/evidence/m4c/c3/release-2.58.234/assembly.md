# Release 2.58.234 — MOD-ACL-UX-01 M4C C3 «Запись, 409, audit, recheck»

**Status:** REVIEW / **FIXED (delta-review B01) — READY_FOR_RE_REVIEW** (деплой и VERIFIED не выполнялись).
**Date:** 2026-11-22 19:57 +12:00 / 07:57 UTC (первичная сборка 18:47 +12:00; correction — 19:57 +12:00)
**Branch:** `release/mod-acl-m4c3-2.58.234`
**Base:** `f232a3a30a79c074fc3d7fa75d8aa947720d76a4` (2.58.233, schema 48, PG DDL 0)
**Rollback:** prepared target **`be23f5eff7287b02e2e91d9b5a5af2b474198beb`**
(`rollback/mod-acl-m4c3-ddl-compatible`) при наличии `access`-строк; raw `f232a3a3` — только при
`access_rows=0` (см. §0/§5, proof `rollback-ddl-proof.md`).
**Delta review:** `plans/features/mod-acl-ux-01/evidence/m4c/c3/release-2.58.234/delta-review-r1.md`
@ master `f4a919988` — **NEEDS_FIXES** (B01 rollback DDL); исправление — §0.
**Candidate tip:** `0f808810d92fcb9116e2549c8106b5f360b9229c` (`feat/mod-acl-m4c3`);
коммиты `d4b9b190e` C3a, `a56713509` C3b, `7b242bde1` partial raw_value, `0f808810d` C3.1 B01/N01.
**Review:** `plans/features/mod-acl-ux-01/evidence/m4c/c3/review-r1.md` @ planning master `e96314dc7`
(23 557 B, sha256 `deac5a9f1e0d6a9d753c71139e043d736298786de93afe272a1d8d7d92f90756`) —
**APPROVED_FOR_RELEASE_PREPARATION** (R1.1, C3.1); `C3-R1-N02…N08` — backlog, не блокируют.
**Contract:** `plans/features/mod-acl-ux-01/evidence/m4c/c3-contract-2026-11-22.md` @ master `09e62ff7a`
(65 890 B, sha256 `3c8dcb7da6b689aee34ffddba9e36d3949482493b91b2389a045d57be202858c`).
**Content tip (pin completion):** `3b18ca1dd0a3e6c9c528bcbb1a2a975276dcf49f`
**Version:** 2.58.234
**Schema/DDL:** 48 / **1 PG DDL** (только CHECK `chat_lore_history.field` += `'access'`; SQLite 0)
**Manifest dry-run:** `manifest-dry-run.json` (`deployed_sha = 3b18ca1dd…`; docs-коммит выше него, см. §6).

## 0. Correction delta-review B01 — rollback-контракт DDL 1

**Проблема (подтверждена):** старый код `f232a3a3` на **каждом** старте делает
`DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` с **10** значениями. После любой audit-строки
`field='access'` PostgreSQL отклоняет ADD (SQLSTATE 23514), DROP уже закоммичен → CHECK
отсутствует; `ConfigCache.init()` перехватывает ошибку → `pg_available=False`, roles/admins
пусты, ACL-эндпоинты 503, владелец не global_admin. Поэтому raw `f232a3a3` **не является**
универсальной rollback-целью после первой ACL-записи.

**Исправление:** подготовлена rollback-совместимая цель от `f232a3a3` —
**`be23f5eff7287b02e2e91d9b5a5af2b474198beb`**, ветка `rollback/mod-acl-m4c3-ddl-compatible`.
Она содержит **только** изменение CHECK до 11 значений (`services/pg_db.py`, 1 insertion /
1 deletion); C3 feature-кода, UI и тестов поведения нет; `APP_VERSION` остаётся **2.58.233**.
`services/pg_db.py` цели **байт-идентичен** forward (`3b18ca1dd`) — blob
`0174c28b6abe8fd04385e97592f870c0629dd909`; 62 statement, новых объектов нет. Ветка запушена
без force.

**Rollback-правило:**
1. Pre-rollback gate: `SELECT count(*) FROM chat_lore_history WHERE field='access'`.
2. `0` → raw `f232a3a3` разрешён (old DDL 10 значений проходит; проверено на scratch PG).
3. `>0` → raw **запрещён**: деплой prepared target `be23f5eff` **или** отдельно авторизованный
   metadata-only cleanup (`DELETE` только `field='access'`, с экспортом count/ids/хешей и
   повторной проверкой), после чего допустим raw. По умолчанию — prepared target.
4. Перед rollback — свежий PG backup `chat_lore_history` + ACL-таблиц; startup-верификация
   constraint/roles/admins; повторный startup идемпотентен.

**Доказательство:** `rollback-ddl-proof.md` / `rollback-ddl-proof.json` — реальный
PostgreSQL 18.7 (PGlite 0.5.17, локальный scratch, без production): raw old с `access`-строкой →
DROP ok, ADD **23514**, CHECK отсутствует; prepared target (62/62 statement дважды) → CHECK с
11 значениями, `access`-строка валидна; raw old при `access_rows=0` → успех. Формулировка
`C3-R1-N07` исправлена: raw rollback больше не заявлен совместимым.

Цель — **не релизный кандидат**: F8 byte-pin `PG_DB_SHA256_B07` на ней не обновлялся (иначе
пришлось бы менять тесты поведения), поэтому полный release-набор тестов на этой ветке не
запускается; её acceptance — DDL-proof и startup-совместимость, а не 2.58.234 test suite.

## 1. Assembly steps

| # | Step | Result |
|---|---|---|
| 1 | `workflow_housekeeping.py worktree-path` → `git worktree add <path> -b release/mod-acl-m4c3-2.58.234 f232a3a30` → `register-worktree` | Worktree `…/mod-acl-ux-01-1e46be007668-69c6e7a5`, clean at `f232a3a30` |
| 2 | Cherry-pick `d4b9b190e^..0f808810d` (4 commits, 0 merges, no force) | `b371d583a` C3a, `91bc28d4b` C3b, `ddc66d995` raw_value, `5bf340dd0` C3.1; 0 conflicts |
| 3 | Patch-id check of every cherry-pick | 4/4 **identical** (`b15588e8…`, `507ea33d…`, `abbaba31…`, `7c81aeeb…`) |
| 4 | Tree equality vs candidate before any extra work | `git diff 0f808810d 5bf340dd0` **empty** |
| 5 | Bump audit | `APP_VERSION = 2.58.234` уже внутри reviewed candidate (C3a); **обнаружен неполный пиновый wave**: 4 JS-теста и 2 tools остались на `2.58.233`; JS-пины при этом реально падали бы на `APP_VERSION = "2.58.234"` |
| 6 | Завершение пинового wave `3b18ca1dd` | **6 files, 8 insertions / 8 deletions**: `tests/js/round1025_hotfix{7,8,9,10}_*.js` (regex + ожидание UI-версии), `tools/ui_mod_acl_m4b2_status_e2e.py` (3 строки), `tools/ui_mod_acl_m4b3_status_e2e.py`; полный wave = **32 files / 35 / 35** |
| 7 | Checks on content tip `3b18ca1dd` | §4; все назначенные батчи ниже, включая 4/4 JS-пинов после завершения |
| 8 | Manifest dry-run on `3b18ca1dd` | exit 0; version 2.58.234, previous `f232a3a3…`/2.58.233, `dirty_tracked=false`, `.deploy` восстановлен локально и удалён |
| 9 | This evidence commit | docs-only; product/test/tool bytes не меняет |
| 10 | Delta-review B01 fix: rollback target | `be23f5eff` от `f232a3a3`, only `services/pg_db.py` 1/1, branch `rollback/mod-acl-m4c3-ddl-compatible`, pushed no force; proof `rollback-ddl-proof.md/json` |
| 11 | Correction docs commits | assembly/runbook/proof + stale test docstring (comment-only, assertions unchanged, C3 rerun 71); product bytes не меняет (deploy-time manifest — по фактическому HEAD, §6) |

- `git rev-list --merges f232a3a30..HEAD` = **0**; история базы не перезаписывалась (no force).
- Product bytes идентичны reviewed candidate: `git diff 5bf340dd0 3b18ca1dd -- services web config`
  **empty**; после кандидата менялись только 6 тест/tool-файлов версии.
- Продуктовая часть кандидата не переписывалась: все правки — cherry-pick без конфликтов
  и механическое завершение version wave (без логики/ассертов продукта).

## 2. Product delta (base `f232a3a30` → content tip `3b18ca1dd`)

| Файл | Net base→tip | Роль |
|---|---|---|
| `services/pg_db.py` | **1 / 1** | CHECK `chat_lore_history.field` += `'access'` (superset) |
| `services/acl_audit.py` | 203 / 0 | **new**: allowlist builder/insert/parse; только metadata |
| `services/access.py` | 181 / 7 | updated_at/CAS для глобальной матрицы + audit в транзакции |
| `services/chat_params.py` | 145 / 0 | атомарный `set_perm_override` (FOR UPDATE → CAS/merge → UPDATE → NOTIFY → audit) |
| `services/config_cache.py` | 119 / 33 | audit в одной транзакции с ролями/админами |
| `services/roles.py` | 22 / 0 | pure `role_revision` |
| `services/chat_lore_store.py` | 26 / 3 | `exclude_fields` (скрыть `access` из lore) |
| `services/oversight.py` | 2 / 1 | исключение `field='access'` из oversight-таймлайна |
| `web/api/access.py` | 282 / 28 | `updated_at`/CAS, POST chat override, **DELETE** reset, **GET /api/access/audit** |
| `web/api/routes.py` | 229 / 15 | ревизии/409 ролей, recheck в retry, audit payload |
| `web/api/chat_lore.py` | 2 / 1 | фильтр `access` |
| `web/app.js` | 626 / 54 | матрица draft/save/409/per-item, роль 409, audit-панель, reset, `errText()` |
| `web/index.html` | 176 / 9 | save bar, конфликт-карточки, audit-панель, local-overrides |
| `web/static/app.css` | 39 / 0 | save bar/панель/карточки |
| `config/settings.py` | 1 / 1 | `APP_VERSION=2.58.234` + changelog |
| **Итого** | **15 files, 2054 / 153** | |

- Тесты/инструменты: **38 files, 2930 / 221**; evidence кандидата: 26 files, 2173 / 0.
  Всего base→content tip: **80 files, 7158 / 375**.
- Поведение C3: durable audit в **существующей** `chat_lore_history` (`field='access'`, schema-
  allowlist, без значений/prompt/last4); ревизии ролей (`role_revision`, `create_only`,
  `expected_revision` → 409 `role_exists|role_absent|revision_mismatch`); матрица с честным
  `updated_at`, CAS/`expect_absent` и save в UI (toggle меняет только draft, 409-карточка);
  чатовый override атомарный + `DELETE` «в наследование»; `GET /api/access/audit` (global admin,
  entity/limit/before_id, `malformed:true`); recheck в `_write_chat_overrides_with_retry`
  (чат `POST /api/config` — `can_edit_param` по `raw_value`/inherit; meme-settings — собственный
  гейт), отказ → 403 без второй записи, недоступность → 503; lore/oversight не показывают `access`.
- Вне C3 (не менялось): S1–S3 hardening, `access_preview.py`, ceiling/делегирование, wildcard
  для `user`, reserved names, долгие публикации/LLM, M6.

## 3. Bump and invariants

- `APP_VERSION` import = **2.58.234**; `plans/docs/param-registry-round1025.meta.md` = 2.58.234.
- Version wave = **32 files / 35 insertions / 35 deletions** — все пины, включая 4 escaped JS
  (`2\.58\.234`), F8-версию (1/1) и 2 tools; сверено скриптом по 32 файлам (см.
  `test-output/bump-bytes.txt`). `test_round1025_f8_registry.py` в общем diff 14/184: сверх
  version-строки — осознанные C3 re-pins и route-set, не bump.
- BOM/CRLF: **0** profile-несовпадений по 32 файлам; `config/settings.py` сохраняет UTF-8 BOM +
  3645 CRLF. Уточнение (delta-review N03): 22 из остальных 31 файлов **уже имели** UTF-8 BOM в
  базе, остальные — LF без BOM; волна не меняла профили ни в одном файле (machine-артефакт
  `test-output/bump-bytes.txt`: `profile_mismatches=0`).
- `git grep 2.58.233` по tracked вне planning/evidence: только исторические ссылки —
  changelog `settings.py` («База: f232a3a3 (2.58.233)…») и комментарий `services/access.py`
  о неизменном legacy-поведении 2.58.233. Живых пинов нет.
- Route set: `@api_router` **76 → 76**; `@access_router` **19 → 21** (+chat override DELETE,
  +audit GET); C2 write-route 9 → 10 с NOTE в тесте (осознанно, не ослабление).
- Пины: `PG_DB_SHA256_B07 = 469775c2a363f5550e80a10b6717cec62c7cc7fce541bbc0a9e34f0437dc9dcd`,
  `ROUTES_SHA256_F11 = 9ac3a8a60fe85eb4ca9af20f2e2be0c3b84b12a23b6c03fa6690ae41a3d4f4bf` —
  совпадают с байтами `services/pg_db.py` / `web/api/routes.py` (осознанный re-pin, NOTE L-F11S-1).
- C2-инварианты: `services/access_preview.py`, `web/api/deps.py`, `services/permissions.py`,
  `web/api/memory_agi.py`, `services/database.py`, `tools/ui_mod_acl_m4c1/m4c2` — **байт-идентичны
  базе** (blob equality). Второго ACL/store/DDL-набора нет; `chat_lore_history` — существующая
  таблица, чатовый override — существующий `perm_overrides`.
- `git diff --check f232a3a30..HEAD` rc=0; `node --check web/app.js` rc=0; `py_compile`
  изменённых Python/tools rc=0.

## 4. Tests on content tip `3b18ca1dd`

Machine-readable: `tests-2.58.234.json`; raw: `test-output/`.
Python `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, Node `v24.16.0`, pytest `9.1.1`,
Playwright (bundled Chromium).

| Batch | Result |
|---|---|
| C3 `test_acl_audit` + `test_webapp_access_write_safety` + `test_acl_legacy_inventory` | **71 passed, 0 failed** (26.26 s) |
| Focused C3a (11 файлов, как tests.md кандидата) | **576 passed, 0 failed** (40.36 s) |
| C1 `test_webapp_access_matrix_read.py` | **17 passed, 0 failed** (20.23 s) |
| C2 `test_webapp_access_effective.py` | **124 passed, 0 failed** (15.46 s) |
| Hardening `test_mod_acl_ux_m4c_acl_hardening.py` | **63 passed, 0 failed** (6.75 s) |
| F11 `test_webapp_f11_round1025.py` | **33 passed, 0 failed** (3.61 s) |
| Pin-guard, 24 Python-файла с `2.58.234` | **856 passed, 4 failed** (73.81 s) — те же 4 node-id, что на базе `f232a3a30` (baseline 4 failed, 8.38 s): `test_tool_coordinator_round1026.py::TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`, `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`, `::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`; не pass, не регрессия C3 |
| Node (11 файлов) | **11/11 rc=0**: C3 WRITE, C1 ROLES-PAGE, C1 EDITOR-PRESERVE, C2 PREVIEW, C2 ADMINS-SEED, M3 235 проверок, methods-dup, HOTFIX7/8/9/10; `node --check web/app.js` rc=0 |
| C3 Playwright `ui_mod_acl_m4c3_write_e2e.py` | **PASS 0 failures**; 1440/1280/768/390/320; save PUT=3/3, role POST, audit GET, local DELETE, 409/reapply, h-scroll 0; `e2e-report` |
| C1 Playwright `ui_mod_acl_m4c1_roles_e2e.py` | **PASS 0 failure(s)** |
| C2 Playwright `ui_mod_acl_m4c2_preview_e2e.py` | **PASS 0 failure(s)** |
| B1 `ui_mod_acl_m4b_status_e2e.py` | `{"ok": true, "checks": 138, "failures": []}` |
| B2 `ui_mod_acl_m4b2_status_e2e.py` | `{"ok": true, "checks": 92, "failures": []}` (после завершения пина: stub/ожидание = 2.58.234) |
| B3 `ui_mod_acl_m4b3_status_e2e.py` | `{"ok": true, "checks": 131, "failures": [], "screenshots": 8}` |
| SQLite schema smoke (temp DB) | target **48**, `user_version=48`, `schema_migrations` 48/48, 101 таблица, `quick_check=ok`, `chat_lore_history` в SQLite **нет** |
| DDL statements | **62**; 1 с `'access'`; `CREATE TABLE` 29 / `CREATE INDEX` 19 — как в базе, новых объектов нет |
| Frozen files / pins / route set | §3; все проверки зелёные |

E2E запускались на локальном стенде (`127.0.0.1`, отдельные порты 8861–8863/8856–8858),
скриншоты/отчёты — во временном каталоге, не в репозитории. Это **не** live TMA.

## 5. DDL 1 и план миграции

Единственная DDL-дельта (PostgreSQL, `services/pg_db.py`, 1 строка):

```sql
ALTER TABLE chat_lore_history DROP CONSTRAINT IF EXISTS chat_lore_history_field_check;
ALTER TABLE chat_lore_history ADD CONSTRAINT chat_lore_history_field_check
  CHECK (field IN ('manual','auto','auto_enabled','auto_period_hours',
                   'auto_window_hours','remap','chat_admin','chat_params',
                   'chat_keys','gates','access'));
```

- `'access'` — **расширение** множества: все существующие строки удовлетворяют новому CHECK,
  ADD не может упасть на данных; DROP/ADD идемпотентны; `DDL_STATEMENTS` = 62, новых
  таблиц/колонок/индексов нет; SQLite остаётся 48 (таблицы нет, миграция не нужна).
- `PgDatabase.init()` применяет DDL до обслуживания запросов. Перед DDL — **PG backup**
  `chat_lore_history` + ACL-таблиц (SQLite backup DDL не покрывает); startup-верификация,
  constraint/DISTINCT-проверки и rollback — в `postdeploy-runbook-2.58.234.md` §2/§5.
- **Rollback:** raw `f232a3a30` **не совместим** с `access`-строками: old startup снова ставит
  CHECK с 10 значениями, ADD падает 23514 после DROP → CHECK отсутствует, PG-кэш ролей/админов
  пуст (ACL 503). Правило: `access_rows=0` → raw разрешён; `>0` → prepared target
  `be23f5eff…` (`rollback/mod-acl-m4c3-ddl-compatible`, только CHECK 11 значений) или отдельно
  авторизованный metadata-only cleanup, не raw. Audit-строки при prepared target остаются
  валидными; downgrade CHECK и ручной DDL не выполняются. `C3-R1-N07` переформулирован: на
  prepared target старый lore/oversight может показать `access`-строки сырым JSON (косметика,
  без секретов/потери данных) — это не причина откладывать откат.

## 6. Manifest, rollback, runbook

- `manifest-dry-run.json`: exit 0; `deployed_sha=3b18ca1dd…` (content tip), `version=2.58.234`,
  `previous_sha=f232a3a3…`, `previous_version=2.58.233`,
  `release_branch=release/mod-acl-m4c3-2.58.234`, `dirty_tracked=false`.
  Предыдущий `.deploy/release.json` восстановлен локально из документированного deployed-состояния
  (production-файл не читался), после прогона `.deploy` удалён; tracked tree clean.
- Деплой обязан записать manifest по **фактическому** checkout SHA (evidence-коммит или его tip):
  product bytes идентичны content tip. Correction-коммиты меняют только `plans/` (+ comment-only
  docstring в `tests/test_acl_audit.py`, assertions не менялись); dry-run `manifest-dry-run.json`
  остаётся на content tip `3b18ca1dd`, фактический HEAD фиксируется deploy-временем
  (version/previous/dirty не меняются).
- Rollback: raw `f232a3a30` (2.58.233) — только при `access_rows=0`; иначе prepared target
  `be23f5eff…` (`rollback/mod-acl-m4c3-ddl-compatible`, branch tip, не raw), см. §0 и §5
  runbook. Перед rollback — PG backup; DDL/данные/настройки не откатываются, wipe не выполняется.
- Runbook `postdeploy-runbook-2.58.234.md`: single-process preflight, ACL 4/3/1/0, backup,
  manifest actual HEAD, restart, health/version/identity/schema/DDL/`NRestarts`/journal/digests,
  served bytes, `POST /api/admins` 401, audit GET 401/403 без initData, reset/409 read-only
  boundary, disk audit/cleanup, запрет live-chat/LLM/positive writes, RFL.

## 7. Residual и ограничения

- **Review R1.1** принял C3; `C3-R1-N02…N08` — backlog; **N07 переформулирован** (§0/§5):
  raw rollback после `access`-строк не заявлен совместимым.
- **Delta-review R1:** B01 исправлен (prepared target + proof). Nonblocking остаются **N01**
  (reset 37×118@320 / 44×68@390 / 74×31@1440 — pre-existing, dedup с `C3-R1-N04`), **N02**
  (forward preflight усилен ожидаемым constraint + `DISTINCT field`), **N03** (BOM-фраза
  исправлена: 22 из 31 уже с BOM), **N04** (косметика «1 перекрытий»/пробел — backlog).
  Ни один не расширяется до правок продукта.
- **RFL** (не owner QA, не блокер): натуральный двухоконный 409/натуральный отзыв в середине
  долгого запроса; реальная local_admin TMA-сессия для embeddings-403; live TMA не проверялась.
- DDL/rollback доказаны на **PostgreSQL 18.7** (PGlite 0.5.17, локальный scratch): raw old +
  `access` → 23514/CHECK absent; prepared target 62/62 дважды → CHECK 11, строка валидна;
  `access_rows=0` → raw old успешен. Production-применение и constraint проверяются postdeploy.
- VERIFIED по строкам карты не заявлялся; deployed SHA/effective-state не проверялись.
- В этой сборке: без SSH, deploy, LLM, production-данных и positive ACL-writes; временные
  артефакты — в `%TEMP%\opencode` (proof JSON/md — в evidence), worktree clean.

## 8. Cleanup

- Временные каталоги (`temp\opencode\m4c3-258234`, `temp\opencode\pgproof`,
  `temp\opencode\m4c3_release_*.py`, `schema-smoke.db`) — вне репозитория; proof перенесён в
  evidence, после сдачи временные каталоги удаляются.
- В worktree нет новых tracked/untracked файлов кроме evidence-папки; production не
  затрагивался; фоновых процессов не осталось.
