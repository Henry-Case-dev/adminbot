# MOD-ACL-UX-01 — выкладка 2.58.175 (M2 backend + M4 «Основные настройки»)

Артефакт выкладки для леджера требований. Содержит только факты прогона, живой проверки и
проверки идентичности кода; ничего не «додумывает». Владелец карты — основной checkout (правило §8
`plan.md`); копия этих же фактов лежит на релизной ветке
(`release/2.58.175:plans/features/mod-acl-ux-01/evidence/m2/m2-deploy-2.58.175.md`, коммиты
`14ef564e`/`e4fc5a8c`), леджер читает эту копию.

## 1. Что выкачено

| Поле | Значение |
|---|---|
| Версия | `2.58.175` |
| Задеплоенный SHA | `3421399961c11a6b8d5441f3430a7bfb4e15ea0e` |
| Ветка | `release/2.58.175` (immutable checkout по SHA) |
| Предыдущий прод | `2.58.174` @ `ac943f40` (`release/2.58.174`) |
| Сервер | `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot` |
| Схема | `user_version=46`, `schema_migrations=35` — **без DDL** |
| Откат | `git checkout --detach ac943f40` + `systemctl restart admin_bot` + `backups/predeploy-258175.db` |

### 1.1. Состав выкладки (cherry-pick)

| # | SHA | Что |
|---|---|---|
| 1 | `97cfdef1` | M2: единый резолвер GLOBAL→CHAT (**ранее отревьюенный кандидат M2**) |
| 2 | `3b1ba3b2` | M2: полное состояние capability и явный INHERIT |
| 3 | `dd52cbf9` | M2: CHAT OFF в полёте, инвентарь потребителей, края §10 |
| 4 | `0833035a` | M4: реальные параметры «Векторной памяти» |
| 5 | `7faa9d7c` | M4: самодостаточный JS-тест и переносимый стенд |
| 6 | `827d4a3b` | M4: сверка по JSON |
| 7 | `6e175ced` | M4: стенд отвечает на `/api/*` в `--serve-only` |
| — | `98bc424e` | **SELF-DIAG-01 D2 — НЕ включён (Needs Fixes)** |

`97cfdef1` — предок `3b1ba3b2` (`git merge-base --is-ancestor` → 0) и отдельно отревьюенный
кандидат (`evidence/m2/m2-evidence-97cfdef1.md`): без него cherry-pick `3b1ba3b2` падал на
отсутствующем блоке резолвера в 4 файлах. Добавление `97cfdef1` — восстановление одобренного
содержимого M2, не посторонний код.

## 2. Исключение D2 (проверено в этом прогоне, а не принято на слово)

`git cat-file -e 34213999:<path>` по D2-файлам:

| Путь | В выкате 2.58.175 |
|---|---|
| `services/diagnostic_policy.py` | отсутствует |
| `services/output_projection.py` | отсутствует |
| `services/telegram_role_check.py` | отсутствует |
| `tests/test_diagnostic_policy.py` | отсутствует |

Существующие файлы, которые D2 правил на интеграционной линии, в выкате **не изменены** относительно
2.58.174 (блобы равны): `services/access.py` `2e70f6d3…`, `services/tool_router.py` `500669c8…`,
`handlers/checkup.py` `dc18b1e2…`, `web/api/access.py` `d29119da…`. То есть правки D2 не «протекли»
через общие файлы.

Отдельно: `git diff --name-only dd52cbf9 34213999 -- services/ web/ tests/test_mod_acl_ux_m2_` даёт
ровно 8 путей, и только два из них — содержательные изменения релиза (`web/app.js`, `web/index.html`,
работы M4); остальные шесть — D2-файлы, которых в выкате нет.

## 3. Основание привязки строк к SHA выкладки

Релизный коммит `34213999` — bump поверх отобранного содержимого: `git diff --name-only df7b6351 34213999`
даёт 26 файлов, все — `APP_VERSION`/README/F8-мета/version-пины тестов. Продуктовый код не менялся.

Код и тесты M2 в выкате **байт-идентичны** проверенному кандидату `dd52cbf9` (сравнение блобов
`git rev-parse <sha>:<path>`):

| Путь | Блоб |
|---|---|
| `services/chat_params.py` | `02bc7bed…` = `02bc7bed…` |
| `services/feature_gates.py` | `2c4fe6dd…` |
| `services/permsoc.py` | `2272038c…` |
| `web/api/gates.py` | `11e801af…` |
| `tests/test_mod_acl_ux_m2_resolver.py` | `11af9246…` |
| `tests/test_mod_acl_ux_m2_capability_state.py` | `d0348d2f…` |
| `tests/test_mod_acl_ux_m2_consumers.py` | `7fa06a41…` |
| `tests/test_mod_acl_ux_m2_inflight.py` | `3ca9deb0…` |
| `tests/test_mod_acl_ux_m2_runtime_edges.py` | `cc11005f…` |
| `tests/test_mod_acl_ux_m2_tristate_write.py` | `ac93b700…` |
| `tests/test_mod_acl_ux_01_m1_acl_false_403.py` | `3a66c7f1…` |

Поэтому строки M2, доказанные на `dd52cbf9`, сохраняют силу и на выкаченном SHA; в карте к каждой
такой строке добавлена привязка `candidate_commit = 34213999…` с этим основанием в `observation`,
исходные записи на `dd52cbf9` не переписаны и не удалены. То же основание — для строк M1: их guard-код
в выкате не менялся (`git diff ac943f40 34213999 -- web/api/memory_agi.py web/api/deps.py
web/api/chat_lore.py` → только 4 строки комментариев в `memory_agi.py`, логика та же).

## 4. Пост-деплой факты (живая проверка DevOps на этом релизе)

| Проверка | Факт |
|---|---|
| `/healthz` локально | `{"status":"ok","version":"2.58.175"}` |
| `/healthz` публично | `{"status":"ok","version":"2.58.175"}` |
| Сервис | `active`, `NRestarts=0` |
| Traceback с рестарта | **0** |
| Записи уровня err с рестарта | **0** |
| `/web/app.js` отданный | sha256 `f91ce8ec1ec6446a6fa9daf034a5df93750b8e31c1401ba5fd930b7b69dcca91`, 2 099 429 B |
| `/web/app.js` в checkout `34213999` | `f91ce8ec…cca91`, 2 099 429 B — **совпадает** (пересчитано в этом прогоне по git-объекту) |
| `/web/app.js` в 2.58.174 `ac943f40` | `a47d09d4…8ff9e`, 2 091 920 B — **отличается** |
| `/web/index.html` | подстановка `?v=2.58.175`; `2.58.174` — 0 вхождений, `__APP_VERSION__` — 0 |
| Схема после рестарта | `PRAGMA user_version=46`, `schema_migrations=35`, `quick_check=ok` — DDL не выполнялся |
| Снапшот перед выкладом | `backups/predeploy-258175.db`, 1 901 146 112 B, sha256 `186dc9cd…363a`, read-back `quick_check=ok`/`user_version=46` совпал |

## 5. Живая проверка M2 на выкаченном SHA (read-only, без отправок и без чужой личности)

Прогон интерпретатором юнита на сервере, только `SELECT`; оси зрителя (`can_read/can_edit/authorized`)
намеренно `None`. Чат `-1002661910336`.

### 5.1. Эквивалент `GET /api/chat/{id}/gates`

| capability | gates[f] | chat_state | desired | source | global_value | effective_runtime | ready | reason_code |
|---|---|---|---|---|---|---|---|---|
| dream | true | inherit | true | global | true | true | true | null |
| lore_auto | true | inherit | true | global | true | true | true | null |
| nostalgia | true | inherit | true | global | true | true | true | null |
| permsoc | true | **on** | true | **chat** | **false** | true | null | null |
| permsoc_reactions | true | inherit | true | default | true | true | null | null |
| permsoc_schedule | true | inherit | true | default | true | true | null | null |

`observed = null`, `pending_restart = false`, `version = 2026-11-09T09:54:11.484800+00:00` для всех строк.

### 5.2. `opt_in`

`opt_in(api) = true` = `SELECT gates_opt_in FROM chat_profiles WHERE chat_id=-1002661910336` → `true`.
Совпадение подтверждено.

### 5.3. INHERIT идемпотентен

- Два независимых чтения: `chat_profiles.updated_at` до и после — `2026-11-09 09:54:11.484800+00:00`
  (не изменился); `chat_lore_history` по чату 234 → 234.
- 5 из 6 capability в настоящем INHERIT (`dream, lore_auto, nostalgia, permsoc_reactions,
  permsoc_schedule`): записей нет ни в `chat_params.gates`, ни в `overrides`. Для них повторный INHERIT
  даёт `new_overrides == base_overrides` → ветка `noop_inherit`: `set_chat_params` не вызывается,
  `pg_notify` живёт только внутри `_apply_chat_patch` → NOTIFY не появляется, `updated_at` не
  двигается.
- `permsoc` — единственное исключение: у чата есть явная запись (`chat_params.gates["permsoc"] = true`),
  поэтому «наследовать» для него = реальное удаление записи, а не no-op. Ожидаемое поведение.
- Записей не выполнялось: проба делает только `SELECT`; число строк истории и `updated_at`
  подтверждают отсутствие записи.

### 5.4. Глобальные значения и «GLOBAL OFF + CHAT ON»

Effective `bot_settings`: `flags.permsoc_enabled = false`; `flags.dream_enabled / lore_auto_enabled /
nostalgia_enabled = true`; `permsoc_reactions`/`permsoc_schedule` — заводской default ON без записи.
Env-оси `MCA_*` — все `true`.

Чат `-1002661910336` при глобальном OFF: `gates["permsoc"] = true`, `source = chat`,
`effective_runtime = true` — **остаётся ON**. Глобальный OFF не является родительским veto.

## 6. Что этот выкат доказывает, а что нет

Доказано живыми наблюдениями на `34213999`: truth table в двух случаях (`GLOBAL ON + INHERIT → ON`;
`GLOBAL OFF + CHAT ON → ON, source=chat`), `opt_in` совпадает с `chat_profiles`, INHERIT идемпотентен,
сохранённые значения и история не переписаны, схема без DDL.

Не доказано и остаётся `PENDING` (точные условия — в карте): остальные пары truth table
(`GLOBAL OFF + INHERIT`, `GLOBAL ON + CHAT ON`, чатовый OFF), `observed` по реальным событиям, shared
scheduler при GLOBAL OFF, «три смены чата без поздней перезаписи», отложенный результат в выключенный
чат, живой UI-прогон и реальное событие чата для `MAC-AC-04`/`MAC-S15-12`/`MAC-S15-1-01`.

## 7. Владелец

Владелец на этом релизе подтвердил в корневом чате, что раздел «Векторная память» открывается
(дословно: «раздел векторной памяти открылся»), и отдельно сообщил, что настроек в нём нет. Вторая
часть — отдельный фронтенд-дефект, который исправлен в этом же релизе (работы M4 п.1.1 #4–#7);
доказательство — `evidence/m4a/m4-module-settings-2.58.175.md`, где тот же дефект воспроизведён на
базовом коммите. Подтверждение доступа относится к M1 и разобрано в
`evidence/m1/m1-owner-live-confirmation-2.58.175.md`.

## 8. Гейт на момент этой сверки (кандидат = выкат = `34213999`)

| Прогон | Результат | Категории остатка |
|---|---|---|
| `check --stage plan` | `inventory=279 manual=99 scoped=0 errors=0` | — |
| `check --stage release --slice M2` | `scoped=54 errors=30` | 15 строк самого среза `PENDING` (truth table TT-2/TT-3/TT-5/TT-6, AX-05, SHARED-01, S2-81, S10-01, AC-02, AC-04, S10-04, S10-20, S15-12, S15-1-01, сводная M2-01) + 15 строк зависимости M1 без привязанного доказательства |
| `check --stage release --slice M4A` | `scoped=35 errors=82` | 31 строка самого среза `PENDING` + 51 строка зависимостей (M3 — 20, M2 — 15, M1 — 15, M0 — 1) |
| Клерical-ошибки (candidate mismatch, missing artifact, sha) | **0** | — |

То есть по M2 свелись все 36 прежних ошибок привязки и 15 прежних «нет доказательства»: остаток —
только живая матрица флагов и строки, требующие реального события чата или живого UI. По M4A остаток
не клерical, а содержательный: срез собран частично (одна вкладка одного модуля).

