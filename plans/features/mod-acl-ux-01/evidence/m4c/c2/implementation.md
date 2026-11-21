# MOD-ACL-UX-01 — M4C **C2** implementation (read-only «Проверить доступ»/effective)

- Дата: **2026-11-22**, роль **Builder**, режим: реализация + собственные проверки.
  Деплой/SSH/LLM не вызывались; production не менялся.
- База: **`d86bf66d408266c928e24714c2f5779a4ddf8ebe`** (2.58.230, schema 48, PG DDL 0).
- Ветка: `feat/mod-acl-m4c2` (создана только от базы; C1/2.58.230-байты сохранены).
- Контракт: `evidence/m4c/c2-contract-2026-11-22.md` (§0, §4, §6, §8).
- Кандидат: **C2a `8e50b0fa3`** (backend read-model) + **C2b `bc742adc0`**
  (UI/evidence) + **c3** (corrective R1) + **c4** (R1-3 open/R1-9/R1-10).
  Один кандидат, внутренние коммиты; отдельный deploy не выполнялся.

## 1. Что реализовано

### C2a — backend read-model (только чтение)

| Файл | Изменение |
|---|---|
| `services/access_errors.py` | **new**: единый `AccessStorageUnavailable` (~15 строк); `services/access.py` реэкспортирует имя (C1-импорты не ломаются) |
| `services/roles.py` | `access_for(..., *, strict: bool = False)`: при `strict=True` холодный кэш (`cache is None` / пустой RAM + `pg_available=False`) и недоступный групповой chat-грант (пул None/исключение) → raise; DM-ветка без PG; default не изменён (D1) |
| `services/access.py` | `param_permissions_snapshot(pg)` — отдельный `SELECT key, value, updated_at`, **без** TTL-кэша и без его обновления; `normalize_permission_override(value)` — публичная обёртка `_normalize_perms` |
| `services/chat_params.py` | `read_chat_params_strict(chat_id, pg)` → `(root, updated_at, profile_present)`; pool None/ошибка → raise; runtime-кэш не мутируется |
| `services/access_preview.py` | **new** read-model: `evaluate` (person+scope), `chat_param_permissions`, `chat_admins`; слои/решения над существующими резолверами; web-импортов нет |
| `web/api/access.py` | три аддитивных GET + маппинг 401/403/404/422/503; F-C2-1 (strict auth матрицы) |
| `tests/test_webapp_access_effective.py` | **new**, 101 кейс (см. §4) |

Endpoint'ы (все GET, монтируются существующим `access_router`):

- `GET /api/access/effective?resource=&operation=[&telegram_id=&chat_id=]` —
  200 для валидного запроса; решение в теле (`allowed|denied|mixed|not_applicable`),
  не HTTP 403. 403 — только право вызывающего (чужой актор/DM/недоступный чат);
  404 — нет группового профиля; 422 — namespace/операция/`chat_id=0`; 503 — строгое
  чтение прав недоступно.
- `GET /api/access/chats/{chat_id}/param_permissions` — только известные
  `known_param_keys()` (622), `{view_roles, edit_roles, legacy}`, `filtered_out`,
  `updated_at` профиля; значения/промпты/`last4`/`overrides` не отдаются.
- `GET /api/access/chats/{chat_id}/admins` — только global admin; строки
  `chat_admins` (`telegram_id/role_name/added_by/created_at/display_name`).

Семантика (сверено с фактическими guard'ами, не «роль-как-актор»):

- **person+scope**: актор и scope — собственные селекторы preview, `X-Chat-Id`
  шапки не используется; `{global:true}` + explicit `chat_id` в query.
- `section.access`: `role` (grant `requires_permission`/global-admin canon) +
  `global_admin_ceiling` (inline `is_global_admin`). Расхождение (custom с
  `section.access`) → **mixed** — фактическое состояние, S1 остаётся C3.
- `section.chat_lore` global — `not_applicable` (серверного ресурса нет, только
  видимость вкладки); chat — guard `chat_admins` membership/DM; DM — 404-изоляция
  (`not_applicable`).
- прочие `section.*` global — **реальное покрытие** секции:
  `applies_to=coverage`, decision allowed/denied по
  `deps.user_has_permission(section.<id>)`, guard —
  `deps.can_edit_param/can_view_key_value (section coverage)`, consumer —
  глобальный `POST /api/config` (C2-R1-3). Никакого фиктивного
  `requires_permission("<section>")`.
- `section.*` в chat/DM (включая `section.access`) — `not_applicable`:
  chat-scoped endpoint'а для секции нет (`scope_capability`, честная причина);
  глобальный scope того же ресурса считается по факту (C2-R1-9).
- `param.*` global view — F-C2-3: non-secret читается любым валидным TMA
  (`global_config_all`), secret — только admin; hidden — hard-deny для всех
  (`hidden_parameter`, GET его не отдаёт).
- `param.*` global edit — **только** `param.<key>` матчер (F-C2-2/D3: без
  admin-bypass); `role_type=global_admin` без wildcard → denied.
- `param.*` chat view — `chat_access` + secret + `can_view_param(effective_matrix)`
  + hidden; edit — `chat_access` + `chat_grant` + `can_edit_param` + `per_chat` +
  hidden. `can_view_param/can_edit_param` вызываются как есть (второго матчера нет).
- `key.*` global — точное зеркало `/api/config` (C2-R1-2): hidden — hard-deny
  view/edit (`hidden_parameter`; POST → 422); non-secret view — `allowed/
  global_config_all` для любого TMA; secret view — только admin; edit —
  provider-ключи только admin, прочие `can_view_key_value(key.<key>)`; chat —
  `not_applicable/keys_via_byok`.
- `action.*` — точное зеркало `deps.requires_permission`/`bypass`,
  `routes._persona_can_edit/_persona_has_edit_action`, `speech._library_can_edit`
  (в chat humor право `edit_humor_library` НЕ участвует — только persona/content).
- `decision`: `denied` при hard-deny; `mixed` — только где расходятся разные
  guard-поверхности одного ресурса (section.access); `not_applicable` — нет
  применимых guard/coverage-слоёв. Для chat-edit без гранта — `denied`, не
  «частично» (контракт §4.5 + тест-план §7.1 п.1).
- `overrides`: только param/key; `present`/`updated_at` (глобальный —
  `param_permissions.updated_at`, чатовый — профиль), `author_recorded: false`
  (audit — C3). `title/secret/hidden` — только при global-admin-вызывающем.
- strict: любая непрочитанная часть → 503 `access_storage_unavailable`; seeded +
  PG down: section/action global 200, param/key global 503, chat 503.
- F-C2-1: `GET /api/access/param_permissions` auth-check через `access_for(strict=True)`:
  холодный кэш + PG down → 503, seeded non-global → 403 (без strict-read),
  seeded admin → 503 на strict-read матрицы. Нормальный путь не изменён.

### C2b — UI (существующая вкладка «Фактические гейты»)

- `web/index.html`: блок `[data-preview]` **первым** в `[data-roles-pane="gates"]`
  (до статического списка), подзаголовок «Справочник гейтов». Новой вкладки нет;
  внутри preview только select/input/button — **0 чекбоксов**.
- `web/app.js`: `preview` state + методы `previewRun/previewReset/
  previewActorOptions/previewScopeOptions/previewResourceKind/
  previewDecisionLabel/previewLayerLabel/previewLoadChatOverrides/previewSeedActor`
  (+ `previewOnRoleChange/ActorChange/ScopeChange`, `previewLoadChatAdmins`,
  `previewMarkStale`, `previewChatOverridesList`, `previewErrorHint`).
  Смена роли/scope при наличии результата → 1 пересчёт; ввод ресурса → только
  stale-очистка (0 запросов на символ). Роль без назначений → `no-actor`
  («не на ком проверить»), без симуляции. Каждый слой — отдельная карточка
  (label/decision/reason/required/matched/guard/consumers/source), не один бейдж.
  Перекрытия чата — только admin+group chat; 403 → скрыто с подписью, 503 —
  error-карточка. Три строки «Фактических гейтов» исправлены по §6.6 (маркеры C1
  сохранены).
- `web/static/app.css`: `.roles-preview*` (glass-карточка формы, вертикальные слои,
  `overflow-wrap`, mobile <768 — одна колонка, тач ≥44, без h-scroll).
- `tests/js/mod_acl_ux_m4c2_preview_test.js`, `tools/ui_mod_acl_m4c2_preview_e2e.py`
  (C1-инструмент не менялся; стенд импортирует его стабы и добавляет 3 endpoint'а).

## 2. Инварианты (проверено)

1. **Только чтение**: число write-декораторов `access.py` = **9** (baseline,
   тест `test_new_routes_are_get_only`); preview не содержит POST/PUT/DELETE.
   `@access_router.get("/effective")` и два чатовых GET — аддитивны.
2. Guard'ы не ослаблены: матрица/гранты/чатовые override'ы остаются global-admin;
   `section.access`-гейты ролей/админов не тронуты; `superuser/last-admin` — без
   изменений.
3. `web/api/routes.py`, `web/api/deps.py`, `services/permissions.py`,
   `services/pg_db.py`, `services/param_catalog.py`, `services/config_cache.py`
   — **не изменены** (`git diff --name-only d86bf66d4..CANDIDATE`); re-pin не
   требуется.
4. DDL **0**, schema 48; `bot_roles/bot_admins/chat_admins/param_permissions/
   chat_params` не пишутся; runtime-кэши preview-чтением не мутируются.
5. F-C2-1/F-C2-2/F-C2-3 отражены как факты (не «исправление политики»).
6. S1/S2/S3 и write/assign/409/audit — не входят (C3); preview показывает
   фактическое `mixed` для custom `section.access`, не заявляет новую политику.

## 3. Diff-состав

`git diff --numstat d86bf66d4..bc742adc0` (product/tests/tools; evidence — отдельный коммит):

```
services/access.py                    67/2
services/access_errors.py             15/0   (new)
services/access_preview.py           844/0   (new)
services/chat_params.py               30/0
services/roles.py                     27/3
web/api/access.py                    169/2
tests/test_webapp_access_effective.py 1113/0 (new)
web/app.js                           434/3  (preview state/methods + 3 строки гейтов)
web/index.html                       189/0  (preview-блок в gates + «Справочник гейтов»)
web/static/app.css                    59/0  (form/layers/mobile)
tests/js/mod_acl_ux_m4c2_preview_test.js 489/0 (new)
tools/ui_mod_acl_m4c2_preview_e2e.py    751/0 (new)
plans/features/mod-acl-ux-01/evidence/m4c/c2/** (evidence)
```

`web/api/routes.py`, `web/api/deps.py`, `services/permissions.py`,
`services/pg_db.py`, `services/param_catalog.py`, `services/config_cache.py` —
**0 строк** (не изменены).

Corrective c3 (поверх C2b): `services/access_preview.py` +94/−53,
`web/app.js` +54/−4, C2-тесты/инструмент/evidence; product-файлы вне C2 seam —
0 строк.

Corrective c4: `services/access_preview.py` (section coverage/scope) +
C2-тесты/evidence; остальные product-файлы — 0 строк.

## 4. Проверки (фактические результаты)

Результаты после corrective R4 (R1-3 open/R1-9/R1-10; RED/GREEN — `r1-c4.md`;
предыдущие — `r1-blockers.md`).

| Проверка | Результат |
|---|---|
| `pytest tests/test_webapp_access_effective.py` | **124 passed** |
| Focused pytest (10 C1-adjacent файлов) | **334 passed, 2 failed** — `test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface` и `test_webapp_hubs_matrix_ui::test_r4_custom_modules_removed`, оба воспроизведены на чистой базе `d86bf66d4` (pre-existing) |
| C1 `test_webapp_access_matrix_read.py` | **17 passed** (не изменялся) |
| `node tests/js/mod_acl_ux_m4c1_roles_page_test.js` | PASS |
| `node tests/js/mod_acl_ux_m4c2_preview_test.js` | PASS |
| `node tests/js/app_methods_dup_keys_guard_test.js` | PASS |
| Node sweep `tests/js/*.js` | **132 run, 3 fail** (`evol_cog_scene_test`, `round1025_ia_routing_test`, `ur_ui_settings_test`); все 3 rc=1 на чистой базе `d86bf66d4` |
| Playwright C1 roles e2e (7 viewport) | **PASS, 0 failures** (инструмент/тесты не менялись; C1-скриншоты восстановлены) |
| Playwright C2 preview e2e (6 viewport + ошибки + in-flight admins) | **PASS, 0 failures**; `shots/report.json`, 12 скриншотов |
| Browser Use (реальный Chrome) | 1440×900 / 1280×800 / 390×844 / 320×568: `section.access` allowed, h-scroll 0, mobile 1 колонка/тач 44; 4 скриншота |
| B1 / B2 / B3 e2e | **138/0**, **92/0**, **131/131** (маркеры OK) |
| pin-guard (24 version-pin файла) | **856 passed, 4 failed** — те же 4 pre-existing node id, что в C1 evidence (не C2) |
| `node --check web/app.js`, `py_compile` | rc=0 |
| Мутации RED/GREEN | 5/5 (см. `mutation-redgreen.txt`) |

## 4b. Corrective R1 (c3) — блокеры ревью

Полные RED/GREEN — `r1-blockers.md`. Кратко:

- **C2-R1-1 (stale in-flight):** generation-токены `_seq/_adminsSeq/
  _overridesSeq`; любое изменение входа инвалидирует запросы и снимает
  `loading`; поздние ответы effective/chat admins/chat overrides игнорируются.
  RED: `смена actor снимает loading... true !== false` на `ba8b93121`.
- **C2-R1-2 (key.*):** 8 non-secret ключей — `allowed` (как GET /api/config);
  hidden `keys.random_quantum_provider` — hard-deny view/edit (реально GET
  скрывает, POST 422); edit — provider/admin vs `can_view_key_value`; 422 не
  выдаётся за allowed. RED: 7 failed до фикса.
- **C2-R1-3 (section guards):** у `section.access` — реальный
  `requires_permission("access")`+ceiling; у прочих секций — честный
  `ui_visibility`-слой без fake guard/consumers; `chat_lore` в группе —
  реальный membership. `TestLayerHonesty` проверяет каждую строку.
- **C2-R1-7 (noActor):** `adminsLoaded` + reseed до/после `/api/admins`;
  кнопка disabled только `loading||noActor`; ошибка 403/503 ≠ «не назначена».
  RED: `noActor до /api/admins запрещён` на `ba8b93121`.
- **C2-R1-4 (nonblocking):** non-admin actor-select = только «Я».
- C2-R1-5/6 — backlog, не расширялись.

## 4c. Corrective c4 — R1-3 open / R1-9 / R1-10

Полные RED/GREEN — `r1-c4.md`.

- **R1-3 (open):** покрытие секций восстановлено как факт: global
  `section.limits/content/keys/…` → `coverage`-слой с реальными
  `deps.can_edit_param/can_view_key_value` и consumer `POST /api/config`;
  `moderator limits` снова `allowed`; `_expected_decision` сверяется с
  `deps.user_has_permission(section.<id>)` (без ослабления). Фиктивных
  `requires_permission("<section>")` нет.
- **R1-9 (new blocking):** chat/DM `section.*` (включая `access`) —
  `not_applicable` (`scope_capability`, «chat-scoped section endpoint
  отсутствует»); глобальный scope — по факту. Anti-drift +4 chat/DM кейса.
- **R1-10 (nonblocking):** из consumers `section.access` убран
  `GET/POST /api/cover/*` (часть cover-служебных — `requires_global_admin()`);
  остались только roles/admins, тест проверяет.

## 5. Мутации (RED на кандидате, GREEN после отката)

1. global param-edit `_match_detail` → `rank>=2`: anti-drift `MODERATOR/CONTENT/edit` FAIL.
2. `roles.access_for`: `strict=False` в теле: cold 503 и F-C2-1 cold FAIL.
3. `chat_grant` слой переименован: inheritance-тест FAIL.
4. `filtered_out`: diag./unknown попадают в items: sparse/filtered FAIL.
5. `title` без admin-гейта: non-global no-leak FAIL.

Полные node id — `mutation-redgreen.txt`.

## 6. Ограничения (честно)

- **Production preflight `bot_roles`/`bot_admins`** (contract §0.1 п.2, C1 §6.4) —
  **deploy-stage**: Builder не имеет production-доступа; при появлении custom-роли
  с `section.access`, назначенной не-владельцу, до любого deploy C2 нужен
  S1-hardening (сейчас C2 только показывает `mixed`, не исправляет).
- Live TMA non-global/local_admin/user/custom-сеанс — **RFL**, не owner QA;
  e2e/UI проверены на локальном стенде (`TMA_STUB`, стабы из реального каталога),
  не на production-БД. Реальная семантика решения покрыта Python-тестами и
  анти-дрейфом.
- `MAC-S8-505/523` остаются **PENDING** до C3 (audit «кто менял», recheck/долгий
  запрос); C2 даёт preview-часть и evidence, не понижает строки.
- B3 — известный тайминг-флейк `detail_closed`; финальный прогон 131/131.
- Версия не поднималась (2.58.230), release assembly — отдельный этап.

## 7. Evidence

`plans/features/mod-acl-ux-01/evidence/m4c/c2/`:
`implementation.md`, `tests-python.txt`, `tests-node.txt`, `tests-e2e.txt`,
`pin-guard.txt`, `mutation-redgreen.txt`, `browseruse.json`,
`regression-b1.json`, `regression-b2.json`, `regression-b3.json`,
`shots/` (Playwright report + 9 скриншотов, 2 Browser Use).

## 8. Что осталось C3 / hardening

- ACL-hardening до C3: **S1** (мутации ролей/админов — global admin/ceiling),
  **S2** (guard последнего назначенного wildcard), **S3** (superuser wildcard
  server-side), negative RBAC.
- C3: ревизии/409, dirty/save bar, durable audit (`access`, DDL 1), `DELETE`
  чатового override, recheck, `S8-LEG-01` endpoint-инвентарь, `updated_at` в
  матрице, negative initData/RBAC, live RFL.
- Write/assign/«войти как»/второй ACL/DDL — не добавлялись.
