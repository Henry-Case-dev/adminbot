# MOD-ACL-UX-01 — выкладка 2.58.175 (M2 backend + M4 «Основные настройки»)

Компактный текущий артефакт выкладки. Только факты прогона и живой проверки.

## 1. Что выкачено

| Поле | Значение |
|---|---|
| Версия | `2.58.175` |
| Задеплоенный SHA | `3421399961c11a6b8d5441f3430a7bfb4e15ea0e` |
| Ветка | `release/2.58.175` (от `ac943f40`, immutable checkout по SHA) |
| Предыдущая версия | `2.58.174` @ `ac943f40` (release/2.58.174) |
| Сервер | `/var/www/admin_bot`, unit `admin_bot` |
| Схема | v46, без изменений (`services/database.py` вне diff) |
| Откат | `git checkout --detach ac943f40` + `systemctl restart admin_bot` + `backups/predeploy-258175.db` |

### Cherry-pick (порядок)

| # | SHA | Что |
|---|---|---|
| 1 | `97cfdef1` | M2: единый резолвер GLOBAL→CHAT (**добавлен: prerequisite**) |
| 2 | `3b1ba3b2` | M2: полное состояние capability и явный INHERIT |
| 3 | `dd52cbf9` | M2: CHAT OFF в полёте, инвентарь потребителей, края §10 |
| 4 | `0833035a` | M4: реальные параметры «Векторной памяти» |
| 5 | `7faa9d7c` | M4: самодостаточный JS-тест и переносимый стенд |
| 6 | `827d4a3b` | M4: сверка по JSON |
| 7 | `6e175ced` | M4: стенд отвечает на `/api/*` в `--serve-only` |
| — | `98bc424e` | **SELF-DIAG-01 D2 — НЕ включён (Needs Fixes)** |
| — | `53c78594` | уже в 2.58.174 |

**Поправка к плану релиза:** в выданном списке отсутствовал `97cfdef1` —
предварительный M2-коммит резолвера (`services/chat_params.py` +289,
`feature_gates.py`, `permsoc.py`, `worker_settings.py`,
`mca_experience_jobs.py`, `web/api/gates.py`, `web/api/memory_agi.py`,
`scripts/mod_acl_effective_state_report.py`,
`tests/test_mod_acl_ux_m2_resolver.py`). Без него `3b1ba3b2` не применяется:
это его предок (`git merge-base --is-ancestor 97cfdef1 3b1ba3b2` → 0) и его
отдельно ревьюированный кандидат (`evidence/m2/m2-evidence-97cfdef1.md`).
Cherry-pick `3b1ba3b2` на базу 2.58.174 падал ровно на отсутствующем блоке
резолвера в 4 файлах. Добавление `97cfdef1` — восстановление одобренного
содержимого M2, не посторонний код.

`dd52cbf9` (авторён поверх D2) применился **без конфликтов**: его файлы не
пересекаются с файлами `98bc424e`.

## 2. Доказательство исключения D2

`git diff --name-only ac943f40..34213999` — 83 файла: 58 содержательных
(коммиты M2/M4) + 25 файлов только с пинами версии
(`config/settings.py`, `plans/docs/param-registry-round1025.meta.md`,
`tests/*`), из них ни одного D2-файла:

```
services/diagnostic_policy.py      отсутствует
services/output_projection.py      отсутствует
services/telegram_role_check.py    отсутствует
services/access.py                 отсутствует
services/tool_router.py            отсутствует
handlers/checkup.py                отсутствует
web/api/access.py                  отсутствует
tests/test_diagnostic_policy.py    отсутствует
```

`rg -l 'diagnostic_policy|output_projection|telegram_role_check' services/ web/ handlers/`
в релизном дереве → пусто.

Содержимое релиза: M2 (`services/chat_params.py`, `feature_gates.py`,
`permsoc.py`, `worker_settings.py`, `worker_budget.py`,
`mca_experience_jobs.py`, `initiative_observer.py`, `meme_initiative.py`,
`memory_maintenance.py`, `nostalgia_worker.py`, `lore_worker.py`,
`summary_memory.py`, `mca_events.py`, `status_service.py`,
`module_registry.py`, `web/api/gates.py`, `web/api/routes.py`,
`web/api/memory_agi.py`), M4 (`web/app.js`, `web/index.html`) + тесты,
`tools/`, `docs/`, `scripts/`.

Контроль целостности: для всех 58 содержательных путей blob-объект в
`release/2.58.175` совпадает с `integ/unify-release` (единственное
исключение — `tests/test_round1025_f8_registry.py`, где разница только в
пине `APP_VERSION`: 2.58.175 против 2.58.172 в integ).

## 3. Pre-deploy прогоны (на точном релизном дереве)

| Набор | Команда | Результат |
|---|---|---|
| M2 батарея (resolver, capability_state, consumers, tristate, inflight, runtime_edges) | `pytest tests/test_mod_acl_ux_m2_*.py` | **65 passed** |
| gates/params/feature/permissions + M1/M3/M4 python | `pytest tests/test_mod_acl_ux_01_m1_acl_false_403.py … test_permissions.py` (14 файлов) | **208 passed** |
| experience + workers | 16 файлов (`test_mca16_experience_*`, `test_*_worker.py`, `test_settings_worker_sync_round1018.py`, …) | **376 passed** |
| status + config/hot-config | 14 файлов (`test_status_service.py`, `test_hot_config.py`, …) | **243 passed** |
| routes/registry/module-truth/mca20 | 10 файлов | **178 passed, 1 pre-existing failure** |
| JS | `node tests/js/*.js` | **105 pass / 8 fail (все pre-existing)** |
| M4 harness | `tools/ui_mod_acl_m4_embeddings_e2e.py` | **MOD-ACL-M4-EMBEDDINGS OK, fails=[]** |

Pre-existing (сверено на `de9addc5` = 2.58.174, те же ошибки):
`test_mca20_rework1_f1_f2.py::TestValidatorStage::test_evidence_injection_stays_data_not_instructions`
(падает и на базовой линии) и 8 JS: `asap6_wave2_ux_tabs`, `evol_cog_scene`,
`round1025_hotfix7/8/9/10`, `round1025_ia_routing`, `ur_ui_settings`
(например `TypeError: this._cogBlitLabel is not a function` в `web/app.js` —
воспроизводится на 2.58.174 байт-в-байт).

M4 harness подтвердил то, что увидит владелец: вкладки `['overview','settings']`,
группы «Основная нейросеть» 9 + «Отпечатки текста и длина» 16 = **25 реальных
параметров**, поиск, четыре честных состояния пустоты (`none/no-data/scope/filtered`).

## 4. Снапшот и деплой

| Шаг | Результат |
|---|---|
| Снапшот БД | `backups/predeploy-258175.db`, 1 901 146 112 B, sha256 `186dc9cd…363a` |
| Read-back снапшота | `quick_check=ok`, `user_version=46`, `schema_migrations=35`, таблиц 129 |
| Checkout | `git checkout --detach 34213999…`, worktree чистый |
| Рестарт | `systemctl restart admin_bot`, здоровье через **4 с** |

## 5. Post-deploy проверки

| Проверка | Значение |
|---|---|
| `/healthz` локально | `{"status":"ok","version":"2.58.175"}` |
| `/healthz` публично | `{"status":"ok","version":"2.58.175"}` |
| Сервис | `active`, `NRestarts=0`, MainPID 3439455, старт 14:03:01 UTC |
| `/web/app.js` файл в checkout | `f91ce8ec1ec6446a6fa9daf034a5df93750b8e31c1401ba5fd930b7b69dcca91` |
| `/web/app.js` отданный | `f91ce8ec…cca91`, 2 099 429 B, `cmp` → identical |
| `/web/app.js` было в 2.58.174 | `a47d09d44de013605c25b754e97d978dbfbd9a9a1f67df9a6d085850b588ff9e` — **отличается** |
| `/web/index.html` | отдаётся с подстановкой `__APP_VERSION__` → `?v=2.58.175` ×17, `2.58.174` ×0, `__APP_VERSION__` ×0 |
| Схема | `PRAGMA user_version=46`, `schema_migrations=35`, `quick_check=ok` — **без DDL** |
| Tracebacks с рестарта | **0** |
| Записи уровня err с рестарта | **0** («-- No entries --») |

## 6. Живые доказательства M2 (in-process, read-only, без отправок и без чужой личности)

Прогон на сервере интерпретатором юнита (`/var/www/admin_bot/venv/bin/python`),
только `SELECT`; оси зрителя (`can_read/can_edit/authorized`) намеренно `None`.
Чат: `-1002661910336`.

### 6.1 `GET /api/chat/{id}/gates` — эквивалент

| capability | gates[f] | chat_state | desired | source | global_value | effective_runtime | ready | reason_code |
|---|---|---|---|---|---|---|---|---|
| dream | true | inherit | true | global | true | true | true | null |
| lore_auto | true | inherit | true | global | true | true | true | null |
| nostalgia | true | inherit | true | global | true | true | true | null |
| permsoc | true | **on** | true | **chat** | **false** | true | null | null |
| permsoc_reactions | true | inherit | true | default | true | true | null | null |
| permsoc_schedule | true | inherit | true | default | true | true | null | null |

`observed = null`, `observed_at` = момент чтения, `pending_restart = false`,
`version = 2026-11-09T09:54:11.484800+00:00` для всех строк.

### 6.2 `opt_in` из `chat_profiles.gates_opt_in`

`opt_in(api) = true`, `SELECT gates_opt_in FROM chat_profiles WHERE chat_id=-1002661910336` → `true`, совпадение = **true**.

### 6.3 INHERIT идемпотентен

- Два независимых прохода чтения: `chat_profiles.updated_at` до и после —
  `2026-11-09 09:54:11.484800+00:00` (не изменился); `chat_lore_history`
  по чату 234 → 234.
- Каноническое состояние: **5 из 6** capability в настоящем INHERIT
  (`dream, lore_auto, nostalgia, permsoc_reactions, permsoc_schedule`) —
  записи нет ни в `chat_params.gates`, ни в `overrides["flags.*_enabled"]`.
  Для них повторный INHERIT даёт `new_overrides == base_overrides` → ветка
  `noop_inherit`: `set_chat_params` не вызывается, а `pg_notify` живёт только
  внутри `_apply_chat_patch` (путь реальной записи) → NOTIFY не появляется,
  `updated_at` не двигается.
- `permsoc` здесь — **единственное** исключение: у чата есть явная запись
  (`chat_params.gates["permsoc"] = true`), поэтому «наследовать» для него —
  реальное удаление записи, а не no-op. Это ожидаемое поведение, не дефект.
- Записей не выполнялось: проба делает только `SELECT`; число строк истории и
  `updated_at` подтверждают отсутствие записи.

### 6.4 Глобальные флаги и «GLOBAL OFF + CHAT ON»

Настроенные глобальные значения (effective `bot_settings`): `flags.permsoc_enabled = false`,
`flags.dream_enabled / lore_auto_enabled / nostalgia_enabled = true`,
`permsoc_reactions`/`permsoc_schedule` — заводской default ON без записи.
Env-оси: `MCA_EXPERIENCE_LESSONS_ENABLED`, `MCA_INTENTS_ENABLED`,
`MCA_RANDOM_SOURCE_ENABLED`, `MCA_SELF_MODEL_ENABLED`,
`MCA_STORIES_VITRINA_ENABLED`, `MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED`,
`MCA_VISION_ENABLED` — все `true`.

Чат `-1002661910336` при глобальном OFF: `gates["permsoc"] = true`,
`source = chat`, `effective_runtime = true` — **остаётся ON**. Глобальный OFF
не является родительским veto.

## 7. Статус gate (`requirements_gate.py check --stage release --slice M2`)

`stage=release inventory=279 manual=99 scoped=54 errors=41` → **не зелёный**.
Причины (не правились — карта принадлежит PM):

1. `candidate_commit`/`deployed_commit`/`deployment_evidence` в карте всё ещё
   описывают 2.58.172 (`bee14188`); фактический деплой — `34213999` / 2.58.175.
2. Девять строк M2 в `PENDING` (см. §8), из них семь `live_required: true`.
3. Зависимость M1 не помечена `VERIFIED`, хотя 2.58.173 выкачен.

## 8. Что из живых строк M2 закрывается сейчас, а что требует события

| Строка | Вывод |
|---|---|
| `MAC-AC-03` (сохранённые значения/ключи/история пережили деплой) | **Можно закрывать**: DDL=0, `user_version` 46→46, `schema_migrations` 35→35, `updated_at` и история чата не сдвинулись |
| `MAC-S10-01` (GLOBAL + CHAT inherit / явные override) | **Частично**: inherit→global и chat ON при GLOBAL OFF доказаны; явного chat OFF среди gated-capability нет |
| `MAC-AC-02` (truth table в живом runtime) | **Частично**: разрешение доказано; «глобальное OFF не скрывает чатовый control» — свойство UI |
| `MAC-S2-81` (enabled без сигнала = «работа не подтверждена») | **Частично**: `ready=true` при `observed=null` есть в ответе; отрисовка строки — UI |
| `MAC-S10-04` (три смены чата без поздней перезаписи) | **Нужен живой UI-прогон** |
| `MAC-S10-20` (отложенный результат не публикуется в выключенный чат) | **Нужно реальное событие чата** |
| `MAC-AC-04` (чатовое OFF прекращает вызов и публикацию) | **Нужно реальное событие чата** |
| `MAC-S15-12` (после GLOBAL OFF→ON свой OFF остаётся OFF) | **Нужно реальное событие/смена флага** |
| `MAC-S15-1-01` (`403` чужого scope ≠ глобальный OFF) | **Нужен живой auth/UI-прогон** |

Примечание: в `binding_note` карты упомянуты «пятнадцать live-строк M2»; после
переназначения одиннадцати строк каталога/UI в M3/M4A и закрытия части строк
в текущей карте остаётся **9 PENDING** (7 с `live_required: true`), 31 из 40
строк M2 — `VERIFIED`.

## 9. Шаги владельца

1. Mini App → карточка модуля «Векторная память» → «Настроить»: ожидается
   вкладка **«Основные настройки»** с реальными параметрами (25 штук: 9
   «Основная нейросеть» + 16 «Отпечатки текста и длина») вместо пустоты.
2. Поиск по параметрам внутри карточки — по названию/ключу.
3. **F5 / повторный вход** в Mini App: версия в адресах ресурсов должна быть
   `?v=2.58.175` (кэш Telegram WebView сбрасывается).
4. Обычный (не админ) пользователь по-прежнему **не видит** раздел «Модули» и
   получает 403 на админ-API — выдачи не расширены.
