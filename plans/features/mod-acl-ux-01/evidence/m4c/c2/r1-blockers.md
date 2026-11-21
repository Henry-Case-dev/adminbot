# M4C C2 — corrective R1: blocker fixes C2-R1-1/2/3/7 (RED → GREEN)

- Кандидат c3: ветка `feat/mod-acl-m4c2`, база `d86bf66d4`, предыдущий tip
  `ba8b93121` (C2a `8e50b0fa3`, C2b `bc742adc0`).
- Правки только C2 seam: `web/app.js`, `services/access_preview.py`,
  C2-тесты/инструменты/evidence. `routes.py`/`deps.py`/`permissions.py`/
  `pg_db.py`/`param_catalog.py`/`config_cache.py`/settings не тронуты,
  DDL 0, write/new ACL нет.
- RED снят на байтах `ba8b93121` (product-файлы временно возвращены
  `git checkout`, тесты новые), затем фикс восстановлен.

## C2-R1-1 — stale in-flight result

**RED (`node tests/js/mod_acl_ux_m4c2_preview_test.js` на `ba8b93121`):**

```
AssertionError [ERR_ASSERTION]: смена actor снимает loading старого запроса
true !== false
  at main (... mod_acl_ux_m4c2_preview_test.js:392)
RED_EXIT=1
```

Проявление: запрос, начатый для актора A, завершался уже после выбора B и
писал `result` A под выбором B; `loading` оставался true.

**Fix:** generation-токены `_seq/_adminsSeq/_overridesSeq`; любой ввод
(actor/scope/role/resource/reset) вызывает `_previewInvalidate()` —
инкремент всех токенов + снятие `loading`; late-ответ сверяет свой generation
и игнорируется. `previewLoadChatAdmins/previewLoadChatOverrides` имеют
собственные generation (поздний ответ старого scope не применяется).

**GREEN:**

```
node tests/js/mod_acl_ux_m4c2_preview_test.js
MOD-ACL-UX-M4C2-PREVIEW-OK
```

Проверено: late effective после смены actor/resource не перезаписывает
`result`; `loading` снимается; новый запрос применяет свой ответ; late
chat overrides/admins старого scope не применяются.

## C2-R1-2 — key.* не зеркалил /api/config

**RED (`pytest -k "TestKeyConfigSemantics or TestLayerHonesty ..."` на
`ba8b93121`):**

```
FAILED ...::TestKeyConfigSemantics::test_all_non_secret_keys_visible_to_any_authenticated
FAILED ...::TestKeyConfigSemantics::test_hidden_key_is_denied_even_for_admin
FAILED ...::TestLayerHonesty::test_every_layer_is_real_guard_or_visibility
7 failed, 2 passed, 106 deselected
```

Факты: 8 non-secret ключей категории keys (`embedding_quota_group_labels`,
`random_quantum_endpoint/plan/batch_length/data_type/
request_timeout_seconds/refill_low_watermark/buffer_max_values`) реально
читаются любым валидным TMA (GET /api/config не маскирует non-secret), preview
давал `denied`; hidden `keys.random_quantum_provider` реально скрыт в GET и
даёт 422 на POST, preview давал `allowed` (view+edit).

**Fix (без нового ACL):** preview повторяет фактическую логику `/api/config`:
hidden → hard-deny `hidden_parameter` (view и edit); secret → только admin;
non-secret view → `allowed/global_config_all`; edit — provider-ключи только
admin, прочие — `can_view_key_value(key.<key>)`; chat — `not_applicable/
keys_via_byok` (как C2-контракт). `422` не выдаётся за allowed (hard deny).

**GREEN:** `pytest tests/test_webapp_access_effective.py` → **115 passed**
(включая 8 non-secret × user/moderator/admin, hidden admin view/edit + 422
non-admin, provider/non-provider edit, custom key grant, role_type admin без
bypass, DM/chat key not_applicable).

## C2-R1-3 — несуществующие section guards

**RED:** те же section-тесты + layer-honesty:

```
FAILED ...::TestEffectiveLayers::test_moderator_section_limits_is_visibility_only
FAILED ...::TestEffectiveLayers::test_user_section_limits_visibility_denied
FAILED ...::TestEffectiveLayers::test_chat_lore_global_not_applicable_chat_guard
FAILED ...::TestEffectiveLayers::test_chat_other_section_not_applicable
FAILED ...::TestLayerHonesty::test_every_layer_is_real_guard_or_visibility
```

Старые слои показывали `requires_permission("<section>")` и consumers
`/api/roles`,`/api/admins` для `limits`/`chat_lore`/др., которых в `routes.py`
нет (реальные гварды: только `access`, `edit_info`, `action.*`; `chat_lore` —
membership через `chat_lore.can_access_chat`).

**Fix:** реальный route-guard остался только у `section.access`
(`deps.requires_permission("access")` + inline `is_global_admin`); у прочих
секций — честный слой `applies_to=ui_visibility` с guard
`ui visibility (...; отдельного route guard нет)` и пустыми consumers;
`section.chat_lore` в группе — реальный `chat_access` (membership), global/DM —
`not_applicable`. `decision` для секций без route guard — `not_applicable`
(видимость ≠ endpoint-право).

**GREEN:** 115 passed; `TestLayerHonesty` проверяет: каждый не-visibility слой
имеет guard из allowlist реальных функций/гвардов и непустые consumers; каждый
visibility-слой — `ui visibility`, без `requires_permission`, без consumers;
в исходнике нет `requires_permission("<section>")` для limits/content/…/chat_lore.

## C2-R1-7 — преждевременный noActor

**RED (`node tests/js/mod_acl_ux_m4c2_admins_seed_test.js` на `ba8b93121`):**

```
AssertionError [ERR_ASSERTION]: noActor до /api/admins запрещён
true !== false
  at main (... mod_acl_ux_m4c2_admins_seed_test.js:83)
RED_EXIT=1
```

Проявление: `admins=[]` до загрузки трактовалось как «назначений нет»; роль
admin показывала «Роль не назначена», кнопка disabled; после `/api/admins`
reseed не выполнялся.

**Fix:** флаг `adminsLoaded` (false до завершения `/api/admins`, true в
`finally`); `previewSeedActor` выставляет `noActor` только при
`adminsLoaded && !adminsLoading && !adminsError`; `loadAdmins` вызывает seed
до и после загрузки; ошибка 403/503 не выдаётся за «роль не назначена».

**GREEN:**

```
node tests/js/mod_acl_ux_m4c2_admins_seed_test.js
MOD-ACL-UX-M4C2-ADMINS-SEED-OK
```

Проверено: до загрузки noActor=false, actor `self`; после загрузки actor-list
содержит назначенного admin, кнопка активна; известное пустое назначение →
noActor; `adminsError` → не noActor. Playwright: in-flight `/api/admins`
на 1440/1280 (задержка 2.5 c на клиенте) — noActor нет, run disabled нет,
после ответа actor-list обновлён, `section.access` → allowed;
скриншот `preview-admins-inflight-1440x900.png`.

## C2-R1-4 (nonblocking) — чужие админы в actor-select

`previewRoleActors` возвращает [] для non-admin (backend и так 403; утечки не
было, теперь и UI не показывает). Node-проверка: non-admin options = только
«Я».

## C2-R1-5/6

Backlog, не расширялись.

## Прогоны после фикса (кратко; детали — tests-*.txt)

| Проверка | Результат |
|---|---|
| новый Python файл | **115 passed** |
| focused (10 файлов) | **334 passed, 2 failed** — оба pre-existing (`prompt_field_audit`, `hubs_matrix_ui`) |
| C1 `test_webapp_access_matrix_read` | 17/17 |
| node C2 основной + admins-seed | PASS |
| node sweep | 132 run / 3 fail (те же 3 pre-existing) |
| C1 roles e2e | PASS 0 failures |
| C2 preview e2e | PASS 0 failures (+ in-flight admins 1440/1280) |
| Browser Use | 1440/1280/390/320: allowed, no h-scroll, mobile 44/1 колонка |
| B1/B2/B3 | 138/0, 92/0, 131/131 |
| pin-guard (24) | 856/4 — те же 4 pre-existing |
| `node --check`, `py_compile` | rc=0 |
