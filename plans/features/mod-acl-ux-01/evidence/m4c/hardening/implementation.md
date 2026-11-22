# MOD-ACL-UX-01 M4C ACL-hardening S1/S2/S3 — реализация и проверки

- Дата: **2026-11-22 14:07 +12:00 / 02:07 UTC**, роль Builder.
- Контракт: `plans/features/mod-acl-ux-01/evidence/m4c/acl-hardening-contract-2026-11-22.md`
  (planning `master` `1da5dd5b9`).
- Продуктовая база: **`462568ed7662cf5786a543bce8ecb6618e073c87` / 2.58.232**
  (`release/mod-acl-m4c2-2.58.232`).
- Ветка: **`feat/mod-acl-hardening`** от базы.
- **Product-кандидат: `3b9909447982eadffb0c20beb266870b21eb2a3a`** (S1+S2+S3);
  evidence/test tip — следующий коммит на ветке (product-блобы не меняет).
- Worktree: `WorkspaceData/worktrees/c742e4de9e92c489/mod-acl-hardening-94381b48d1f8-7037ebdf`
  (housekeeping `worktree-path` + `register-worktree`).
- Деплой/SSH/prod-DB/LLM не вызывались. `progress_scope.json` / `workflow_state.md` /
  `requirements-map.json` / `backlog.md` не менялись. VERIFIED не заявляется (нужен
  независимый Reviewer + отдельный deploy).

## 0. Итог

S1–S3 реализованы одним кандидатом. 5 write-маршрутов ролей/админов закрыты
effective-global-admin guard'ом; добавлены инварианты **назначенных** админов
(I2 последний wildcard, I1 последний effective-global) с семантикой `>0 → 0` и
per-app/loop-keyed `asyncio.Lock`; C2 preview честно разделяет read-consumers и
write-consumers; UI `#/access/admins` — read-only для non-global. DDL 0, schema 48,
route-set Δ=0, новые ACL/store/флаг не вводились. C3 не затронут и не дублируется.

## 1. Срез изменений (diff только разрешённые файлы)

Product-кандидат: **`3b9909447982eadffb0c20beb266870b21eb2a3a`** (коммит S1+S2+S3).
Ветка дополнительно содержит docs/test-коммит с evidence; product-блобы
`web/api/routes.py` и `services/roles.py` в нём не меняются (evidence/test tip
отличается только тестом legacy-admin положительного кейса и этим артефактом).

```text
 services/access_preview.py                   |  21 +-
 services/roles.py                            |  65 ++-
 tests/test_mca23_planned_vs_actual.py        |   6 +-
 tests/test_mod_acl_ux_m4c_acl_hardening.py   | 633 +++++++++++++++++++++++++++
 tests/test_round1025_f8_registry.py          |   9 +-
 tests/test_webapp_access_matrix_read.py      |   6 +-
 tools/ui_mod_acl_m4c_hardening_admins_e2e.py | 240 ++++++++++
 web/api/routes.py                            | 282 +++++++-----
 web/index.html                               |   8 +-
 9 files changed, 1153 insertions(+), 117 deletions(-)
```

### S1 — граница мутаций ACL (`web/api/routes.py`)

`POST /api/admins`, `POST /api/admins/remove`, `POST /api/roles`,
`DELETE /api/roles/{name}`, `POST /api/roles/{name}/rename`:
`Depends(requires_permission("access"))` → `Depends(requires_global_admin())`.
Read-маршруты (`GET /api/admins`, `GET /api/roles`, `GET /api/roles/tree`) не
тронуты — `section.access` сохранён. Отдельного правила «access → wildcard» нет
(источник закрыт: мутация). Superuser/builtin/usage/404/422/409/503 — прежние
коды и тексты; non-global получает 403 `"только для глобального админа"` до
любой записи.

### S2 — инварианты назначенных админов + сериализация

`services/roles.py` (аддитивные pure-helper'ы, без второго ACL):

- `is_effective_global_admin_role` — канон `deps.user_is_global_admin`
  (`role_type == "global_admin"` ИЛИ legacy имя `admin` ИЛИ `wildcard`);
- `assigned_global_admin_ids` (I1) / `assigned_wildcard_admin_ids` (I2);
- `guard_admin_lockout(before_roles, before_admins, after_roles, after_admins)` —
  I2 затем I1, только переход `>0 → 0`; `RoleGuardError` (409):
  `"нельзя оставить систему без администратора с полным доступом"` /
  `"нельзя оставить систему без глобального администратора"`.

Точки применения (снимок → guard → запись → reload в одной критической секции):

| Мутация | before → after |
|---|---|
| `post_admins` | admins с заменой/добавлением target; roles неизменны |
| `remove_admin` | admins без target; сохранён `len(admins) <= 1` → 409 |
| `post_roles` | roles с заменой target (permissions/role_type); сохранён role-level `guard_last_wildcard` |

`delete_role`/`rename_role`: guard-логика не менялась (superuser 403 / builtin 409 /
usage 409 / collision 409), обе операции в той же критической секции.
`guard_last_wildcard`, `role_type`/`is_custom` и матчер permissions не менялись.

`_acl_mutation_lock(request)` — лениво на `request.app.state` как `(loop, Lock)`,
пересоздаётся при смене event loop (module-global `asyncio.Lock` ломал бы тесты и
второй app). Это сериализация существующих мутаций, не новый store/ACL.

### S3 — честность preview/UI, negative-матрица, pins

- `services/access_preview.py` — **только metadata `consumers`** для `section.access`:
  role-layer = read-GET (`GET /api/roles`, `GET /api/roles/tree`, `GET /api/admins`);
  ceiling-layer = 3 маршрута `access.py` + 5 write-маршрутов; guard-подпись
  `requires_global_admin() (S1: мутации ACL)`; комментарий «S1 закрыт».
  Resolver/layers/decision/response/strict/anti-drift не менялись (`mixed` для custom
  `section.access` прежний).
- `web/index.html` — `#/access/admins`: `v-if="isGlobalAdmin"` на «Удалить» и на блоке
  add; подпись `data-admins-readonly` «Только просмотр» для non-global. Список,
  аватары/бейджи, модалка и `#/access/roles` не менялись; BOM нет, LF сохранены
  (`+4` строки net).
- `tests/test_webapp_access_matrix_read.py` — обновлены только docstring'и
  («S1 закрыт; read остаётся 200»), assertions не менялись.
- `routes.py` re-pin в **обоих** F8-пинах с NOTE (L-F11S-1): канон
  `tests/test_round1025_f8_registry.py` (`ROUTES_SHA256_F11 = 453e17f8…`) и зеркало
  `tests/test_mca23_planned_vs_actual.py`; rationale — S1-guards, Δ routes=0.

## 2. RED / GREEN

RED на базе `462568ed` (тот же candidate test-файл, отдельный worktree на базе):
`19 failed, 44 passed` — падают non-global write (custom `section.access`),
two-step takeover, self-role-edit, last-wildcard/global (upsert/remove),
role-edit lockout, superuser wildcard strip, concurrency; на базе две
одновременные демоции дают `[200, 200]` и 0 wildcard-админов.
Полный лог: `test-output/red-base.txt`.

GREEN на кандидате: `tests/test_mod_acl_ux_m4c_acl_hardening.py` — **63 passed**
(матрица 401/403 по 4 non-global акторам × 5 маршрутов, DM, takeover, 5 S2-сценариев,
anti-drift, I1/I2-раздельность, no-decrease-repair, concurrency [200, 409]).
Положительный кейс S1-матрицы «legacy-имя `admin`, `role_type=NULL`, пустые права →
не 403» проходит и на базе (там `user_has_permission` уже пропускал global admin) —
это non-regression проверка отсутствия ложного 403, а не RED-кейс.
Лог: `test-output/new-tests.txt`.

### Mutations (каждая убита; `test-output/mutations.txt`)

| ID | Мутация | Результат |
|---|---|---|
| M1 | один write-маршрут назад на `requires_permission("access")` | KILLED (non-global 403 тест) |
| M2 | убран I2 | KILLED (role-edit lockout + wildcard remove/reassign + concurrency) |
| M3 | убран I1 | KILLED (last-global-type remove/reassign) |
| M4 | no-decrease заменён role-count-only | KILLED (role-edit lockout: 2 wildcard-роли остаются) |
| M5 | lock заменён no-op | KILLED (concurrency: `[200, 200]`, 0 wildcard-админов) |

M5 потребовал усилить fake-PG: `execute()` уступает event loop (`await asyncio.sleep(0)`),
иначе конкурентные запросы шли строго последовательно и гонка маскировалась
(первая версия теста M5 переживала). После усиления тест дискриминирующий и на
базе, и на мутации.

## 3. Регрессия и инварианты (кандидат `3b9909447`)

| Проверка | Результат | Артефакт |
|---|---|---|
| C1 `tests/test_webapp_access_matrix_read.py` | **17 passed** | `test-output/c1.txt` |
| C2 `tests/test_webapp_access_effective.py` | **124 passed** | `test-output/c2.txt` |
| focused 10-file (§5.3) | **334 passed, 2 failed** (те же pre-existing node id, что в 2.58.232: `test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface`, `test_webapp_hubs_matrix_ui::TestReviewerMinorsR1R4::test_r4_custom_modules_removed`) | `test-output/focused.txt` |
| pin-guard, 24 version-pin files | **856 passed, 4 failed** — те же 4 pre-existing: `test_tool_coordinator_round1026::TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`, `test_unified_image_request_round1026::TestToolDescriptionU21::test_canon_unchanged`, `::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` | `test-output/pin-guard.txt` |
| base control pin-guard на `462568ed` | **856 passed, 4 failed** — те же node id (независимый контроль) | `test-output/red-base.txt` |
| node: M4C2 preview / M4C2 admins seed / M4C1 roles page / methods-dup / hotfix10 | все rc=0 | `test-output/node.txt` |
| e2e C1 (`tools/ui_mod_acl_m4c1_roles_e2e.py`) | PASS: 0 failure(s) | `test-output/e2e-c1.txt` |
| e2e C2 (`tools/ui_mod_acl_m4c2_preview_e2e.py`) | PASS: 0 failure(s) | `test-output/e2e-c2.txt` |
| B1/B2/B3 | 138/0, 92/0, 131/131 (screenshots 8) | `test-output/e2e-b{1,2,3}.txt` |
| schema smoke (temp SQLite) | `TARGET 48 user_version 48 schema_migrations True max 48 count 48 tables 101 journal wal` | `test-output/schema-smoke.txt` |
| py_compile + `node --check web/app.js` | rc=0; route decorators candidate=76 = base=76 | `test-output/syntax.txt` |

Байт-идентичность базе (blob sha1, `test-output/invariants.txt`):
`web/api/access.py`, `web/api/deps.py`, `services/permissions.py`,
`services/access.py`, `services/config_cache.py`, `services/pg_db.py`, `web/app.js`.
`services/database.py` не изменялся → schema 48; `services/pg_db.py` не изменялся →
PostgreSQL **DDL 0**. C1 write-маршрутов `web/api/access.py` = 9 (файл не тронут;
их 403/не-403 регрессия покрыта C1/C2 и pin-guard).

## 4. UI (визуальный контракт)

Playwright `tools/ui_mod_acl_m4c_hardening_admins_e2e.py` (локальный стенд, API-стабы
C1, `TMA_STUB`; НЕ live TMA) — **PASS 0 failure(s)**, `shots/report.json`:

| Режим | 1440×900 | 390×844 |
|---|---|---|
| non-global | 4 строки админов, 0 «Удалить», 0 add-блока, «Только просмотр» видима, h-scroll нет | то же; `scrollWidth=390` |
| global | 4 строки, 4 «Удалить», add-блок (ID/select/«Назначить»), подписи «Только просмотр» нет | то же |

Скриншоты: `shots/admins-{non-global,global}-{1440x900,390x844}.png` (4 файла).

**Browser Use** (локальный Chrome по CDP, тот же стенд `--serve`, non_global=1):
модалка `#/access/admins` открыта, 4 строки (`5885953495, 1313107079, 777000111,
777000222`), кнопок 0, add нет, подпись «Только просмотр», `scrollWidth == vw`.
Скриншот: `shots/browseruse-admins-non-global.png`. C1-страница ролей и C2-preview
не перестраивались; их e2e — PASS (§3).

## 5. Конфигурация / флаги

Флагов/настроек активации нет: S1/S2 действуют безусловно для всех чатов и сред;
factory-off состояния не существует. Effective-state = код кандидата. Откат — только
код/релиз (предыдущий `462568ed` / 2.58.232).

## 6. Single-process precondition (deploy, не выполнено здесь)

`bot.py` поднимает `uvicorn.server.serve()` в **одном** event loop (комментарий
`bot.py:1503-1504`: `uvicorn.run()` и потоки запрещены, R2), systemd unit —
`ExecStart=…/python bot.py`, без workers. Per-app `asyncio.Lock` достаточен **только
при одном процессе**. Перед деплоем DevOps обязан подтвердить single-process
(read-only): `systemctl show admin_bot -p MainPID -p NRestarts`, `pgrep -af bot.py`
ровно один процесс; **если процессов >1 — остановиться и эскалировать Architect**
(per-process lock не даёт глобальной атомарности; альтернатива — PostgreSQL advisory
lock, отдельное решение, не скрытая правка). Здесь это не проверялось: SSH/prod не
разрешены заданием.

## 7. Handoff / границы

- **Не сделано (вне задания):** bump `APP_VERSION` 2.58.233 и волна version-pins;
  deploy/rollback/postdeploy live-проверки; независимое ревью; Arbiter; production
  preflight (`bot_roles` 4 / `bot_admins` 3 / `chat_admins` 1). Кандидат — content-tip
  на версии 2.58.232; bump-wave выполняется на release-assembly шаге (как C2:
  candidate → bump commit).
- **Не проверено честно:** live non-global TMA/real-user сессия (RFL, не owner QA);
  реальные POST-клики в UI (серверная граница доказана deterministic-тестами);
  multi-process deployment (см. §6).
- **Reviewer-подсказка (counterexamples):** two-step takeover
  (`POST /api/admins {owner,"user"}` → `{self,"admin"}`), last-global-type remove при
  втором админе, role-edit lockout (2 wildcard-роли, единственный admin на custom),
  concurrent demotions. Все — в `tests/test_mod_acl_ux_m4c_acl_hardening.py`.
- C3 (revisions/409-протокол, durable audit, chat-override DELETE, recheck,
  legacy-inventory, DDL 1, dirty/save UI) не дублируется и остаётся отдельным
  эпиком после 2.58.233.

## 8. Артефакты

- `test-output/` — new-tests, c1, c2, focused, pin-guard (+ files), node, syntax,
  schema-smoke, invariants, red-base, mutations, e2e-{hardening-admins,c1,c2,b1,b2,b3}.
- `shots/` — 4 Playwright PNG + 1 Browser Use PNG + `report.json`.
