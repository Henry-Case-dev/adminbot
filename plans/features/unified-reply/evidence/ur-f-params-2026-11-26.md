# UR-F — закрытие четырёх PENDING-строк (UR-RES-07, UR-22, UR-21, UR-29)

- База: production base `b01138b556572e55802755960cf4437eb3ff3b06` (2.58.248).
- Ветка: `feat/ur-f-params`; worktree — `WorkspaceData/worktrees/…/ur-f-params-…`
  (registered, unit `UR-F`, epic `ur-f-params`).
- Срез: `plans/features/unified-reply/slice-graph.json` → `UR-F`
  (write scope: `web/app.js`, `web/index.html`, `services/param_catalog.py`,
  `tests/js/*`, `tests/test_ur_ui_effective_config.py`).
- Дата: 26.11.2026. Session: `ses_dec6afb12ffeEPyBweIB86AjMp`.

## Исходное состояние строк на базе (до правок)

| Строка | Состояние на `b01138b55` | Фактическая причина PENDING |
|---|---|---|
| UR-21 | Каркас есть: `eff`-мета, бейджи no-op/legacy, группы. Но `limits.chat_context_fill_ratio` (no-op, не триггер с UR-12) и `limits.chat_current_question_max_chars` (символьный потолок снят SXR-C2-01) оставались **редактируемыми** в «Ответах в чате». Плюс клиент сам решал применимость списком ключей `UI21_ITEM_UI {hidden/readonly}`. | Не выполнено «не читаемое рантаймом скрыто из пользовательского редактирования»; клиент дублировал политику backend. |
| UR-22 | `/api/config` отдаёт `effective_value/source/eff`; `source` различает PG-строку и дефолт. Но `readonly` для legacy/no-op и скрытие поля задавались **фронтовым списком ключей**, а строка режима «Инициатива» брала KV-флаг, игнорируя env-ось backend-гейта (`MCA_INTENTS_ENABLED`). | Frontend угадывал применимость в двух местах. |
| UR-29 | Одно IANA-поле, поиск, серверные часы, offset/DST, наследование, Save/Reset на `mod_time`; `CHAT_TIMEZONE/SUMMARY_TIMEZONE/GOODMORNING_TZ` скрыты. | Реализация уже была; не хватало доказательства единственности поверхности на текущей базе. |
| UR-RES-07 | Раздел «Ответы в чате» = `mod_direct` (overview/inspector/settings); режимы — из effective-config, инспектор отдаёт блоки собранного контекста. | Не хватало доказательства «действующий режим» на базе (инициатива показывала KV-флаг) + содержимого последнего контекста в API-тесте. |

RED на базе (кандидатские тесты против кода `b01138b55`, прогон в
`WorkspaceData/runs/…/probe-b08779e091/base`):

```
tests/test_ur_ui_effective_config.py — 9 failed, 27 passed
  FAILED test_dead_keys_hidden_but_registry_readable
  FAILED test_dead_keys_not_promised_working
  FAILED test_renamed_rows_honest
  FAILED test_effective_meta_honest (нет оси readonly)
  FAILED test_dead_keys_absent_from_config_and_params_meta
  FAILED test_visible_fields_have_effective_meta (нет оси readonly)
  FAILED test_readonly_axis_is_backend_contract
  FAILED test_noop_hidden_legacy_marked
         AssertionError: no-op остаётся редактируемым: limits.chat_context_fill_ratio
  FAILED test_every_visible_field_carries_eff (eff без readonly)
tests/js/unified_ui21_test.js — AssertionError: UR-22: readonly — из item.eff.readonly
tests/js/ur_ui_settings_test.js — AssertionError: UR-22: бейдж режима берёт статус
                                  из backend-гейта
```

Дополнительно на базе `tests/js/ur_ui_settings_test.js` падал на устаревшем
статическом `MODULES` (после MOD-ACL-UX-01 карточки приходят из DTO) и на
зависимости часов от календарной даты прогона; оба места приведены к
детерминированному контракту (DTO-инъекция, `fetchedAt = now`).

## Что изменено

### 1. Backend — единственный источник применимости (`services/param_catalog.py`)

- В `_UR_F_WITHOUT_RUNTIME_READER` добавлены:
  - `CHAT_CONTEXT_FILL_RATIO` — поле «заполнение окна» убрано (UR-21,
    не триггер конспекта с UR-12; значение остаётся читаемым по PG-ключу);
  - `CHAT_CURRENT_QUESTION_MAX_CHARS` — лимит вопроса убран (UR-21.01;
    символьный потолок снят SXR-C2-01, полный текст доходит до L1/Writer).
- Подписи обоих ключей больше не обещают поведения: «не действует / не
  читает / выведен из пользовательского редактирования».
- `effective_meta("limits.chat_current_question_max_chars")` сохраняет
  `no_op` + честную причину (значение читаемо для диагностики).
- Новая ось контракта `eff.readonly`: те же ключи, что раньше фронтовый
  `UI21_ITEM_UI` помечал readonly (compat-капы/доли + два снятых поля),
  объявлены в `_EFFECTIVE_READONLY`; новых запретов нет — политика
  перенесена на backend. Ось точечная: например
  `limits.chat_running_summary_tail` (legacy, но читается fallback) остаётся
  редактируемым — огульного правила «legacy = readonly» нет.

Итог: ни одного редактируемого `no_op` в группах «Ответов в чате»;
`legacy`-поля остаются видимыми и помеченными (`eff.status=legacy`).

### 2. Frontend не угадывает (`web/app.js`, `web/index.html`)

- `UI21_ITEM_UI` больше не содержит `hidden`/`readonly`: остались только
  презентационные `advanced`. `__uiReadonly` выводится из
  `item.eff.readonly` (backend-контракт); скрытие выполняет backend.
- `directModesView()` для «Инициативы» использует backend-гейт модуля:
  `moduleModeStatus()` берёт `state.desired/effective_runtime/source` и
  `gate.effective/source`; env-блокировка показывается как
  «включено, но заблокировано: аварийный переключатель сервера», бейдж —
  «заблокировано». Старый payload без DTO — прежняя семантика `item`.
- Никаких новых классификаторов, эндпоинтов, лимитов и жёстко
  захардкоженных списков ключей не добавлено.

### 3. Тесты

- `tests/test_ur_ui_effective_config.py` (36 passed):
  - `TestDirectGroupApplicability` — все поля групп mod_direct несут
    `status/active_consumer/units/reason_inactive/readonly`; no-op скрыты,
    legacy помечены; ось `readonly` — точечная и backend-ная; снятые поля
    отсутствуют в `/api/config`;
  - `TestEffectiveConfigSource` — одинаковое значение (8000) в явной
    global-строке и синтетическом дефолте различается ТОЛЬКО источником
    (`global` vs `default`) — UI не может вывести это из KV;
  - `TestTimeSingleSurface` — ровно один `data-time-zone-input` в разметке,
    legacy-пояса скрыты, `/api/config/time` несёт
    `iana/source/now_local/as_of_utc/utc_offset/weekday/is_dst/configured`;
  - `TestTurnDiagnostics.test_last_assembled_context_content` — блоки
    последнего собранного контекста (kind/даты/source IDs/причина пропуска)
    и потери приходят из существующей трассы `direct_turn_selection`.
- `tests/js/unified_ui21_test.js` — readonly из `item.eff.status`, клиент не
  скрывает ключи сам (UR-22).
- `tests/js/ur_ui_settings_test.js` — карточка «Время» из DTO, детерминированные
  часы, гейт инициативы (blocked/active), источник действующего режима.
- `tests/test_cfg03_param_audit.py` — точный пин скрытых ключей обновлён на
  два новых (документированный список, не ослабление).
- `tools/ui_urf_visual_e2e.py` — визуальная приёмка: два снятых поля в
  `deadTitles`, одно IANA-поле и отсутствие вторых поясов на экране «Время»,
  бейдж/строка «Инициативы» из backend-гейта.
- `tests/js/ur_ui_settings_test.js` — убрана зависимость от календарной даты
  (`timeStateFetchedAt = Date.now()`) и от статического `MODULES`; тест
  по-прежнему проверяет серверную арифметику часов и DTO-реестр.

## Проверки (кандидат)

| Проверка | Команда | Результат |
|---|---|---|
| Python, строки UR-F | `pytest tests/test_ur_ui_effective_config.py -q` | 36 passed |
| Python, каталог/аудит/срезы | `pytest tests/test_param_catalog.py tests/test_cfg03_param_audit.py tests/test_ur_11_single_owner.py tests/test_ur_12_summary_watermark.py tests/test_ur_context_selection.py tests/test_ur_c_clock.py tests/test_ur_ui_effective_config.py -q` | 201 passed, 1 pre-existing failed (`test_visible_dead_knobs_are_exactly_documented`: 4 несвязанных ключа graph/dig были вне списка и до правок) |
| Python, инспектор/срезы | `pytest tests/test_webapp_api.py tests/test_ur_f_inspector_step1.py … test_ur_e_speech.py -q` | 361 passed, 1 pre-existing failed (`test_ur_f_inspector_step1::test_identical_quotes_credit_only_the_surviving_item`, `FakeDB` — падает и на базе) |
| JS, строки | `node tests/js/ur_ui_settings_test.js`, `node tests/js/unified_ui21_test.js` | `UR-F-UI-OK`, `UNIFIED-UI21-OK` |
| JS, весь каталог | `node tests/js/*_test.js` (149 файлов) | 7 failed — все 7 идентично падают на базе `b01138b55` (`_cogBlitLabel`, `_embedModelSwapGuard`, oversity/menu-пины) |
| Визуал (Playwright) | `python tools/ui_urf_visual_e2e.py --out …/visual` | `URF-VISUAL-OK`; desktop 1440 + mobile 390; console errors = 0; `zoneInputCount=1`, `legacyTzFields=0`, `initiativeBadge=заблокировано` |
| Синтаксис | `py_compile` (3 файла), `node --check web/app.js` | OK |

Конфигурация: effective-config читается из `services/param_catalog.py`
(заводские дефолты) и `bot_settings` (PG-строки); per-chat override — из
`chat_profiles`. Визуальный прогон использует реальные `web/app.js` и
`web/index.html` с детерминированными API-стабами (реальная отправка в
Telegram не выполняется). Секреты не читались и не логировались.

## Состояние строк (для биндинга)

| Строка | Результат | Доказательство |
|---|---|---|
| **UR-21** | implemented (два снятых поля убраны из редактирования; клиент не дублирует политику; все поля группы несут мету, no-op скрыты, legacy помечены) | `tests/test_ur_ui_effective_config.py::TestDirectGroupApplicability` (4 теста), `TestCatalogHonesty`; `tests/js/unified_ui21_test.js`; Playwright `direct-settings/direct-limits` — `deadFound=[]`, hScroll=false |
| **UR-22** | implemented (readonly из `eff.readonly`; режим инициативы из backend-гейта; `source` различает строку PG и дефолт при одинаковом значении) | `TestEffectiveConfigSource`, `TestDirectGroupApplicability::test_readonly_axis_is_backend_contract`, `test_every_visible_field_carries_eff`; `tests/js/ur_ui_settings_test.js` п.6; Playwright `modes-*` (бейдж «заблокировано») |
| **UR-29** | already satisfied with proof (одно editable IANA-поле с поиском, серверные часы, offset/DST, наследование, Save/Reset; вторых часовых поясов нет) | `TestTimeSingleSurface` (4 теста), `TestTimeSurface`; Playwright `time-desktop-1440`/`time-mobile-390`: `zoneInputCount=1`, `legacyTzFields=0`, часы тикают от серверной базы |
| **UR-RES-07** | already satisfied with proof + honest mode fix (действующий режим/источник; содержимое последнего контекста в инспекторе; декоративных no-op-полей нет) | `TestTurnDiagnostics::test_last_assembled_context_content` + существующие `test_chain_view_maps_all_stages`; `tests/js/ur_ui_settings_test.js` п.3–5; Playwright `modes-*`, `inspector-*`; `deadFound=[]` |

## Остаточное / честные ограничения

- `tests/test_cfg03_param_audit.py::test_visible_dead_knobs_are_exactly_documented`
  и `tests/test_ur_f_inspector_step1.py::test_identical_quotes_credit_only_the_surviving_item`
  падают на базе `b01138b55` и после правок; к строкам этого среза не
  относятся, не исправлялись (не расширял scope).
- 7 падений JS-каталога — базовые (проверено прогоном тех же тестов на
  снапшоте `b01138b55`), к UR-F не относятся.
- Browser Use в этом прогоне не использовался: Playwright покрыл desktop
  1440 и mobile 390 на реальных `web/app.js`/`web/index.html` с чистой
  консолью; визуальный контракт существующих экранов не менялся, кроме
  честного бейджа инициативы и исчезновения двух мёртвых полей.
- `WORKER_BUDGET_TZ` остаётся отдельной настройкой фонового дня бюджетов
  (читается `worker_budget`/`dream_worker`); это не второй часовой пояс
  чата: chat-путь бюджета идёт через `ChatClock`
  (`resolve_chat_timezone_sync`).
- `feature_gate`/`last_applied_turn` в `/api/config` по-прежнему не
  отдаются (принятый honest gap UR-22.1); для режима инициативы использован
  уже существующий `modules[].gate`/`state`, без нового эндпоинта.
