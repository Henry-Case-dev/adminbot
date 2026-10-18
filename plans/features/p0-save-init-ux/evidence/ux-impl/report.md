# UX-IMPL — «Речь и характер» (P0A-UX): отчёт лейна

Дата: 2026-10-18. Лейн `UX-IMPL`, writer, без коммита (на ревью). База дерева:
`HEAD=1ce011af` + незакоммиченные правки лейна (см. sha12 ниже); чужие ханки
(`services/initiative_*`, карты, `plans/workflow_state.md`) не тронуты.

## 1. Файлы и sha256-12 (рабочая копия)

| Файл | sha12 |
|---|---|
| `web/index.html` | `c9fab0472bb5` |
| `web/app.js` | `51fec46b0a68` |
| `web/static/app.css` | `8e62b74d8934` |
| `web/api/speech.py` | `7e359935916d` |
| `web/api/memory_agi.py` | `72bc14f246ba` |
| `tests/ui_p0a_ux_speech_compact_e2e.py` (новый) | `458b24f2cecf` |
| `tests/test_soul1_w6_speech_ui.py` | `4162c79b41cb` |
| `tests/test_webapp_round1013_f5_ui.py` | `b079835177b7` |
| `tests/js/routing_test.js` | `3e1b372e48d7` |
| `tools/ui_soul1_w6_speech_e2e.py` | `342d097e5adc` |

## 2. Изменения по группам

### 2.1 Иерархия/витрина (§2, §4-C1/C2, TJ-3/TJ-4)
- 4 группы (`data-speech-groups`): «1. Характер», «2. Манера речи» (Выражение+Юмор),
  «3. Правила письма» (Стиль), «4. Дополнительно» (Примеры/Попробовать/Обучение/
  Все инструкции/Inspector/Возможности) — рендер из серверного payload
  (`speechShowcaseGroups()`), 10 карточек, анкеры `data-speech-card` сохранены.
- «Для разработчика» убран из витрины (TJ-4): те же данные строкой
  «Служебно: реестр …» в «Все инструкции» (`data-speech-registry`).
- Компактная шапка: ⟳-иконка (`restart_alt`) + текст ≥600px; имя чата скрыто
  ≤480px; бейдж наследования убран из шапки (источник — в разделах).
- Сетка: 320px — 1 колонка; 360–599px — ровно 2; ≥600 — авто.
  `.speech-card` 64px/10px, detail — 2 строки (line-clamp).
- TJ-3 (сервер, `web/api/speech.py`): detail карточек — человеческий
  («Действует компактная редакция · N зн.», «Правил: N · задано глобально» /
  «Правил пока нет — форма текста как обычно»).

### 2.2 Компактность/действия (§4 C3–C9)
- «Матрёшка» снята: подблоки `.speech-subblock` (юмор-проба, редактор примера,
  «Почему выбраны», политика, реакции, уроки).
- ⋯-меню раздела (`data-speech-menu`, паттерн `.more-menu-*`, z-index 55,
  закрытие backdrop/Esc/пункт): Обновить/Показать diff/Вернуть заводской/
  Предпросмотр на примерах/Заводская подборка/Наследовать глобальные настройки;
  в карточке примера — эталон/изменить/архив/удалить. Кнопка ⋯ — цель 44×44.
- Primary-кнопка одна на раздел (`.btn-accent`); сегмент-контрол редакций
  (≤599px — 2 равных таба); селектор «Куда сохранить» — по разделу.
- Редактор: автовысота (`data-autogrow`, `autoGrowEditor`, максимум 40vh,
  resize none), «Развернуть» (только ≤599px и landscape; на десктопе нет),
  полноэкранный режим с теми же v-model и «Сохранить».
- sticky-save панель (`data-speech-savebar`) при dirty/503/«Сохранено ✓»;
  safe-area и `--kb-offset`; `padding-bottom` экрана учитывает клавиатуру.

### 2.3 Техмусор (§3 TJ-1…TJ-21)
- «Действует: … — выбрана вами/заводская настройка/…» (TJ-1);
  «Последнее сохранение» + служебные ревизии/история в `<details>` (TJ-2/TJ-20);
  человеческие «Действие: …», id — в «Технических параметрах правила» (TJ-5);
  причина пропуска/причины исключений/сигналы/коды возможностей — словарями
  (TJ-7/8/15/16/17/18/19); сырые значения — в раскрытиях; «библиотека N»/JSON —
  в раскрытии (TJ-9/TJ-14); коды `humor_*` убраны из текста (TJ-13).
- Grep по `web/index.html`: `owner_setting`=0, `fac:`=0, `trailing_period`=0,
  `emoji.hard`=0, `write_error`=0, `document_default`=0, «Сбросить в inherited»=0;
  `inherited` — 2 вхождения вне раздела речи (другие экраны, пре-существующие).

### 2.4 Сохранение (§5) и scope (§6)
- `speechErrText` (коды write_error/save_error/document_invalid/
  config_cache_unavailable → человеческие причины) + `speechSaveFail`
  (409-валидация — текст detail как есть + «исправьте…»; 409-конфликт —
  «обновите данные»; 422 — «Выберите чат…»; 503 — «Повторить сохранение»;
  403/401 как прежде). Все speech-обработчики переведены с `loreErrText`.
- Dirty: Core — по редакциям (`coreFull/coreCompact`), бейдж называет редакцию
  («черновик не сохранён — полная и компактная редакция»); бейдж в шапке
  «Есть несохранённые изменения: N»; «Сохранено ✓ HH:MM» (10 с / до ввода);
  sticky-save панель.
- Scope: `speechScope` на раздел + `speechScopeTouched`; дефолт по области;
  «только этот чат» disabled без чата; при открытии раздела с chat-переопределением
  источник — чат (core/style/expression/humor/examples); правка чата не меняет
  глобальное (сервер) и не переключает другие разделы; тосты «Сохранено для
  этого чата «X» / для всех чатов».
- §6.4: `resetSpeechState()` в `setActiveChat` (после guard) — черновики/данные
  разделов НЕ переезжают в другой чат; `hasUnsavedEdits` видит речь
  (dirty-флаги + открытая форма примера) → `_dirtyLeaveGuard` предупреждает.
- «Наследовать глобальные настройки» (переименование) видно только при
  фактическом переопределении; тосты §6.1 дословно.

### 2.5 Ностальгия (§10)
- `web/api/memory_agi.py`: `_scenario_active(last_ts, now, silence_sec)` (та же
  формула, что у воркера `services/nostalgia_worker.py`) + поля `active`/
  `scenario` в payload (прежние поля не изменены).
- `nostalgiaLabel()`: cooldown → active → ready; legacy-payload без `active`
  сохраняет «Тишина: N/M мин» / «Готова к вбросу».
- Общий хелпер в `services/nostalgia_worker.py` НЕ выносился: стоп-условие
  лейна запрещает правки `services/**`; формула зафиксирована тестом.

## 3. Прогоны (все — на текущей рабочей копии)

| Прогон | Результат | Артефакт |
|---|---|---|
| NEW `tests/ui_p0a_ux_speech_compact_e2e.py` | **failures=0, POST=21** (6 вьюпортов; save/503/409/scope/chat-switch/редакции/meta/откат/юмор+обучение/CRUD примеров/read-only) | `e2e-report.json`, `shots/` (34 PNG) |
| W6 deep-инструмент `tools/ui_soul1_w6_speech_e2e.py` (адаптирован) | **failures=0, POST=16, shots=94** (8 вьюпортов, все 10 разделов, интеракции 390/1440) | `w6-after/ui-report.json`, `w6-after/shots/` |
| MOB `tests/ui_speech_mobile_entry_e2e.py` | **failures=0** (320/390/1280) | stdout |
| `pytest tests/test_soul1_w6_speech_ui.py` | **23 passed** (22 было; +1 новый EXTRA-тест) | stdout |
| JS-sweep `node tests/js/*_test.js` | **87/0** | stdout |
| `pytest tests/test_webapp_round1013_f5_ui.py tests/test_p0_persistfix_speech_chat_scope.py` | **38 passed** | stdout |
| RED-before (мой e2e на webworktree HEAD) | FAIL «групп витрины: 0», затем отсутствие `[data-speech-menu='core']` — новый контракт отсутствовал | `red-before.txt`, `shots-before/` |
| Browser Use (живой осмотр) | портрет 390 (витрина/раздел/dirty/меню/после сохранения «Сохранено ✓ 23:33»), landscape 844×390 (3 кол., «Развернуть» видна), desktop 1280×900 (4 кол., «Развернуть» скрыта); overflow 0, minTap 44 | `live/*.png` (8 шт.) |
| Glass `tests/ui_soul1_glass_tiera_e2e.py verify` | **идентично до/после: 46 FAIL** (`lens_edge_*` на header/sidebar/картах — пре-существующее, воспроизводится на HEAD) | `glass-before.txt`, `glass-after.txt` |

Перед/после (витрина, старый/новый): `shots-before/entry_speech_390.png` →
`shots/store_390.png` (+ `live/live_store_390.png`).

## 4. Чеклист §9 (30 пунктов)

1–5 (Core: полная/компактная, раздельные черновики, режим/вкл, diff+заводской,
история/откат) — **e2e `core-extras` + W6-интеракции** (POST block/core.meta/
reset/rollback, ввод не теряется).
6–9 (Стиль: шаблоны/toggle/scope/убрать, привычки+счётчик, предпросмотр,
`details`) — **W6-интеракции** (шаблон, счётчик, toggle/scope/«Убрать»,
привычки, предпросмотр 4 строки) + детали в DOM.
10 (Expression контролы/сохранение/наследование) — W6-интеракции (сохранение),
тексты «Наследовать…» — контракт-тест.
11 (Юмор: ремесло/приёмы/фильтр/проверка) — **e2e `humor-learning`** (3 POST +
проба в диагностике).
12 (Примеры CRUD/фильтры/подборка/«Почему»/политика) — **e2e `examples`**
(add/approve/archive/delete с confirm/seed/why/policy+scope).
13 (Попробовать) — W6-интеракции (POST try + карточка).
14 (Обучение: реакции/уроки) — **e2e `humor-learning`** (pause реакций + suspend урока).
15 (Все инструкции: поиск/блок/сохранение/заводской/история) — W6-интеракции
(поиск, открытие блока, save, «Заводской вариант» + план), откат — e2e.
16 (Inspector две ветки) — W6-интеракции.
17 (Возможности/коды подписаны) — W6 + контракт-тест (`speechCapabilityReasonText`).
18 (успех: dirty гаснет только у сохранённого, «Сохранено ✓», тост) — e2e.
19 (409-валидация: detail как есть, без «конфликта версии», черновик жив) — e2e.
20 (503: человеческий текст + «Повторить сохранение», ввод жив) — e2e.
21 (смена раздела/чата с черновиком) — W6 (черновик при навигации) + e2e (guard).
22 (смена чата: данные нового чата, чужое не отправляется) — **e2e `scope`**
(REGRESSION: диалог guard, сброс на витрину, текст чата B, 0 POST при смене).
23 (перезагрузка MiniApp: значения на месте) — read-after-write вызывает
`loadSpeechSection(force)`; серверный round-trip — зона PERSIST-FIX (их тесты
зелёные); симуляции полной перезагрузки в браузере нет.
24 (scope chat не меняет глобальное; тост с чатом; наследование) — e2e (POST
scope=chat, раздельность разделов, тост); серверная часть — persist-fix тесты.
25 (права: read-only, disabled) — **e2e `readonly`** (readOnly=true, кнопки disabled).
26 (нет гориз. скролла/перекрытий на 6 вьюпортах) — e2e + W6 (overflow==0).
27 («Развернуть» мобильно/landscape; на десктопе нет) — e2e + live-осмотр.
28 (4 группы; 2 колонки 360–412; 1 на 320) — e2e + W6 + live.
29 (Browser Use: живой осмотр) — выполнено (см. таблицу).
30 (glass/полигон/палитра) — `glass-before/after.txt` идентичны 46/46 —
изменения лейна не влияют; CSS-диф только `.speech-*`.

## 5. Остатки/риски

- **Технический долг §10**: формула сценария A/B продублирована в
  `web/api/memory_agi.py` (вместо общего хелпера в `services/nostalgia_worker.py` —
  стоп-условие лейна). Связка закреплена тестом
  `test_nostalgia_scenario_flag_matches_worker_formula`; консолидация — отдельная
  малая задача для бэкенд-лейна.
- **Пре-существующий дрейф W6-fixture**: `plans/features/soul-1/evidence/w6/
  api-fixture.json` не содержит `examples.starter/telemetry/ab`, из-за чего
  W6-инструмент красный и на HEAD (`Cannot read properties of undefined
  (reading 'expected')`). Шаблон сделан устойчивым к отсутствующим
  метаданным (реальные payload'ы W4 всегда их отдают); сам fixture —
  чужая зона, не правился.
- Glass `lens_edge_*` FAIL — пре-существующее/environmental (46/46 идентично
  до и после; не в `.speech-*`).
- Визуальные KEEP-контракты: палитра/стекло/линза/полигон не менялись
  (CSS-диф — только `.speech-*`; W6-скриншоты glass-экранов в `w6-after/shots`).

## 6. Инцидентные находки

1. `tests/ui_p0a_ux_speech_compact_e2e.py` использует стабы матрицы round1025 —
   без них boot падал (`headerSaveChip`), это особенность харнесса, не продукта.
2. `tools/ui_soul1_w6_speech_e2e.py` сохранён с осознанными правками клик-путей
   (§4-C1 сетка, ⋯-меню, TJ-5 id — в деталях) и повышенной устойчивостью к
   fixture; чужой evidence-каталог soul-1 не перезаписывался (раннер пишет
   в `plans/features/p0-save-init-ux/evidence/ux-impl/w6-after/`).
