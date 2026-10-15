# W3-MODULES-UI — отчёт Builder-полосы (B06 UI / B07 UI / B01.4 UI)

HEAD на старте: `2d95689`. Коммит НЕ делался (запрещено брифом). Все изменения
— в рабочем дереве. Параллельный лейн W3-ANALYTICS (oversight-секции) не
задет: все правки `web/index.html` — модульные/workspace-секции (строки
~417–500 шапка/обзор workspace, ~713–770 settings-интро, ~3670–3720 карточка
каталога); oversight-блоки (4100+), cover-editor, status, шапка — без моих строк.

---

## 1. Реализации

### B06 UI — переключатели управляют runtime; Summary per-chat честно

- **`web/app.js::MODULES`** — `mod_summary.runtimeGate: 'global'` →
  `'per_chat'` (B06.1: витрина = единому резолверу
  `services/summary_scheduler.summary_effective_enabled`; комментарий на
  месте). Следствия (автоматически, через существующую таблицу §43):
  - chat override ON при global OFF → состояние «Включён», notice
    «Включено для этой области (глобально выключено)» — лжи «не работает /
    не влияет» больше нет;
  - chat override OFF → «Выключено в этом чате» (источник — чат);
  - inherit → без ⚠-шума (значение показано состоянием + «Источник»);
  - карточка ушла из blocked/inert-классификации, счётчики/фильтры честны.
- **`moduleChatToggleReadonly(m)`** — B06.2: на chat/dm-scope тумблер
  read-only у global-only карточек (`runtimeGate==='global'`: Direct,
  Фактчек, Поиск, Транскрипт, Выжимка, Медиа, Веб, Диагностика,
  Инициатива-мастер); на global-области активен; per_chat-карточки
  (Summary/Sleep/Ностальгия/Бюджеты/Images/Vision + реестр experience) —
  активны всегда.
- **`moduleGlobalHint`** — человекочитаемая причина read-only («Управляется
  глобально — общий рубильник для всех чатов»), не ⚠-проблема.
- **`setModuleState`** — гвард 1b: global-only карточка на chat/dm-scope →
  `{ok:false, error:'global-only'}` БЕЗ серверной мутации (инертный
  override не создаётся ни UI, ни программно; backend 422 прикрывает только
  models/keys/temporal).
- **`configureModuleGlobally(m)`** — «Настроить глобально»: существующий
  scope-канал `setActiveChat(null)` (dirty-guard/epoch/reload внутри);
  скрыта у не-глобального админа (toast-предупреждение).
- **`index.html`** — карточка каталога: read-only тумблер (тот же hitbox
  w-11/h-6, класс `is-readonly`), хинт, кнопка «Настроить глобально»;
  workspace-head: бейдж «глобальный рубильник» + read-only + кнопка;
  модалка параметров: read-only тумблер. Каноны scope-смены/409/role deny
  не тронуты (persistItems/conflict-ветки без изменений).
- **Обзор workspace Summary** (`data-summary-runtime-note`) — честная
  env-ось: «Аварийная ось: env SUMMARY_EMERGENCY_DISABLE — если выставлена,
  сводки заблокированы во всех чатах, важнее любых тумблеров». Ограничение
  зафиксировано честно: UI не читает env (нет API-поля) — фактическое
  состояние оси показывает только сервер; динамические источники
  (global default / chat override) показываются существующим
  `moduleSourceText` + notice-таблицей.

### B07 UI — Temporal: секция Фактчека, НЕ карточка

- **`TABS mod_factcheck.sources`** + `{category:'temporal',
  groups:['temporal_factcheck']}` — зеркало серверного TAB_RULES (правило
  уже было в `param_catalog.py::TAB_RULES`, JS-зеркало отставало → группа
  не рендерилась). Группа попадает на settings-вкладку workspace
  (`workspaceGroupTab`: category temporal → 'settings').
- **`index.html`** — интро-блок «Время и источники»
  (`data-factcheck-temporal-intro`) на settings-вкладке Фактчека: честное
  объяснение гейта `temporal.tool_enabled` (что включает/что НЕ выключает),
  env-оси — аварийные.
- **Display-оверрайды (Δ каталога = 0, прецедент PERMSOC_LIST_WIDGET_KEYS)**
  в `_normalizeConfigItems`: `temporal.tool_enabled` → «Проверять дату и
  актуальность» + объяснение («…самa привязка сообщений к датам и выбор
  режима не отключаются… Аварийный env-рубильник
  MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED действует независимо»);
  группа `temporal_factcheck` → «Время и источники» (название раздела ТЗ)
  через `groupTitle`/`groupDescription` (map `CONFIG_GROUP_DISPLAY`).
  Режимы (select ×4, каталоговые RU-подписи) и TTL ×2 рендерит общий
  generic-ридер.
- **Детализация Фактчека** — блок «Проверки во времени (детализация)»
  (`data-factcheck-temporal`) на Обзоре workspace: reuse существующих
  `loadTemporalRuns`/`openTemporalDetail` + общий evidence-модал (те же
  данные, что в «Аналитике» → «Память и интеллект»; `/api/factcheck/
  temporal/runs` — global-admin). `loadTemporalRuns` вызывается из
  `_ensureModuleData` для `mod_factcheck` (лениво, ~30с кэш). Для не
  глобального админа — честная подсказка «Журнал проверок … доступен
  владельцу бота»; 403 → fail-open «проверок пока нет» (канон MCA-20, без
  выдуманных данных).
- **Карточки «Временная проверка» в витрине НЕТ** — покрыто тестом:
  `MODULES` не содержит temporal-карточек; `f3ApplyModuleRegistry` со
  hidden-спекой карточку не добавляет (негатив-контроль: visible-спека —
  добавляет).

### B01.4 UI — per-chat профиль частоты Инициативы

- Карта модуля уже подтягивала группы: `TABS mod_initiative` →
  `flags_intent` (settings) + `limits_intent` (limits); ключи каталога
  (W1) рендерятся generic-ридером. Проверено тестом: `initiative.enabled`
  («Инициатива в этом чате») на «Основных настройках», профиль + тонкие
  лимиты на «Лимитах».
- **`initiative.frequency_profile`** — сырой текстовый input заменён на
  select «Редко / Нормально / Активно» (`rare/normal/active`) —
  presentation-оверрайд в `_normalizeConfigItems`
  (`INITIATIVE_PROFILE_SELECT`); POST-валидация каталога для str-ключа
  значения пропускает, резолвер наблюдателя читает канон.
- **`flags.initiative_observer_enabled`** — жаргонная подпись «Наблюдатель
  инициативы (обычный чат)» → «Автономные реплики в обычных чатах» +
  честное описание (оценка порциями с бюджетом, env-ось).
- Мастер `flags.initiative_enabled` остаётся global (read-only на чате,
  «Настроить глобально»); per-chat управление — отдельный ключ
  `initiative.enabled` в настройках (архитектура B01 сохранена).
- Тонкие лимиты (min gap, макс/сутки, окно дня, макс на тему, мин сообщений,
  интервал оценок, суточный бюджет оценок) — из каталога, подписи уже
  человекочитаемые; отображение сверено (расхождений не найдено, кроме
  профиля/наблюдателя — исправлены).

### U08.4 / каноны

Тумблеры не меняют hitbox (тот же peer-разметка; e2e `elementFromPoint` в
центре тумблера — его input); «Настроить»/«Настроить глобально» кликабельны;
подписи без жаргона (FORBIDDEN_JARGON-канон соблюдён: «fact_check»,
«наблюдатель», «inert» в UI-текстах отсутствуют).

---

## 2. Изменённые файлы (владельческие, этой полосы)

- `web/app.js` — runtimeGate Summary; TABS-зеркало temporal;
  `CONFIG_ITEM_DISPLAY_OVERRIDES` / `INITIATIVE_PROFILE_SELECT` /
  `CONFIG_GROUP_DISPLAY`; `_normalizeConfigItems` (+п.4); `groupTitle`/
  `groupDescription`; `moduleChatToggleReadonly`/`moduleGlobalHint`/
  `configureModuleGlobally`; гвард `setModuleState`; `_ensureModuleData`
  (factcheck → `loadTemporalRuns`).
- `web/index.html` — карточка каталога (read-only/хинт/кнопка); workspace
  head; модалка; обзор Summary (env-ось) и Фактчека (temporal-runs блок);
  settings-интро «Время и источники»; маркер `data-temporal-run-btn`.
- `web/static/app.css` — append-блок `/* ═══ W3-MODULES-UI ═══ */`
  (read-only курсор/приглушение без смены hitbox, хинт, тач-цель кнопки,
  усечение строк детализации).
- НОВЫЙ тест `tests/js/asap8_v63_w3_modules_ui_test.js` — TEST-LIFECYCLE:
  CONTRACT owner=REQ-B06/REQ-B07/REQ-B01-4 (UI-часть).
- Обновлён `tests/js/round1025_f4_module_store_test.js` (секция (o)):
  контракт B06 — Summary chat-ON при global OFF работает (blocked-семантика
  сохранена у global-only Direct) + `moduleChatToggleReadonly`. Замена
  зафиксирована в заголовке теста (зелёный тест защищал устаревший
  контракт «Summary global», B06 его изменил — обновлены тест и
  реализация вместе).
- Обновлён `tests/test_webapp_f4_round1025.py`
  (`test_runtime_gate_metadata_complete`): счётчик per_chat-карточек
  5→6, global 10→9 (тот же B06-перевод Summary).
- НОВЫЙ e2e `tools/ui_asap8_w3_modules_e2e.py` (Playwright,
  детерминированный; стабы API, R17).

## 3. Тесты и evidence

- **JS**: `node tests/js/asap8_v63_w3_modules_ui_test.js` →
  **W3-MODULES-UI-OK** (B06 3 фикстуры резолва + read-only-матрица +
  гвард-без-POST + «Настроить глобально»; B07 TABS-зеркало/workspace-мэппинг/
  подписи/hidden-фильтр; B01 карта модулей + select-контракт);
  `round1025_f4_module_store_test.js` → MODULE-STORE-OK; полный прогон
  `tests/js/*_test.js` (85 файлов) — **0 failures**.
- **Python** (смежные контракты): `test_webapp_f4_round1025.py +
  test_asap8_v63_b06_summary_scope.py + test_asap8_v63_b07_temporal_factcheck.py
  + test_asap8_v63_b01_initiative_observer.py` → **62 passed**;
  `test_webapp_api.py + test_asap8_v63_b04_edit_contract.py` → **180 passed**.
- **Playwright e2e**: `tools/ui_asap8_w3_modules_e2e.py` →
  **W3-MODULES-E2E-OK**, 42/42 проверок, console_errors: [].
  Покрытие: Summary chat-scope (тумблер активен в 3 фикстурах, текст
  причины = резолв, POST с X-Chat-Id); global-only read-only + хинт +
  «Настроить глобально» → область «Весь бот», 0 POST (инертный override не
  создаётся); фактчек-секция: «Время и источники», режимы-select ×4, TTL,
  сохранение POST→reload; детализация runs → общий evidence-модал; 403 →
  fail-open честно; не-владелец → без кнопки/запроса, честная подсказка;
  B01 профиль select меняется и сохраняется (POST→reload), per-chat гейт и
  observer-подпись на месте; hitbox/кликабельность; 320/390 —
  `scrollWidth <= innerWidth+1` на «Модулях» и настройках Фактчека.
  Скриншоты: `plans/features/asap8-v6-3-live-correction/w3-evidence-modules/`
  (глобальный каталог, chat-scope, обзор Фактчека, 390, 320).
- **Browser Use (реальный Chrome, CDP)** — визуальный осмотр живого рендера
  на том же фикс-сервере: chat-scope каталог (read-only тумблеры
  приглушены, хинты и кнопки на месте, счётчики 15/2/13/0), Фактчек →
  Основные настройки («Время и источники» + «Проверять дату и
  актуальность» + select режимов), Инициатива (гейт «Инициатива в этом
  чате» активен, мастер read-only + бейдж «глобальный рубильник», профиль
  Редко/Нормально/Активно), переполнения нет.

## 4. Честные ограничения

- **Emergency-ось Summary** (`SUMMARY_EMERGENCY_DISABLE`) не читается UI —
  API-поля нет (env читается сервером per-call). Показана статичной честной
  подсказкой на Обзоре; динамические источники (chat/global) — через
  существующие `chat_source`/`global_value`. LIVE_UNVERIFIED (прод-env).
- **Детализация evidence** — reuse существующего runs-API (RBAC global
  admin) и общего модала; отдельной поверхности «для всех» не создавалось
  (доступ честно объясняется подсказкой).
- **Существующие инертные chat-override глобальных флагов** в БД (созданные
  до B06) UI не чистит — состояние остаётся честным
  (blocked/inert-классификация + существующий сброс через конфиг-вкладку).
- «скрыт»-бейдж на параметрах в стаб-окружении — артефакт стаба
  (`view_roles: []` в CONFIG_STUB), в проде роли приходят сервером;
  равномерно по всем элементам, к этой полосе отношения не имеет.

## 5. Побочные находки (incidental)

1. **related-nonblocking**: `services/module_registry.py` помечает
   `runtime_gate="global"` для sleep/nostalgia/vision, хотя их мастер-ключи
   реально читаются per-chat (`mca_gates._dream_setting_layer(chat_id…)`,
   `gates_enabled(chat_id,"nostalgia")`). Витрина (per_chat) соответствует
   коду, registry-декларация — нет; W1-тест пинит registry-значение.
   Несоответствие словарей — на усмотрение Архитектора, UI не блокирует.
2. **related-nonblocking**: каталог пропускает chat-POST для любых
   flags-ключей (`per_chat=True` по категории), то есть инертный override
   глобального флага сервер создаёт и сейчас — B06.2 закрыт на слое UI
   (гвард) для карточек; для некарточных ключей защиты нет (вне полосы).
3. **uncertain**: кнопка закрытия temporal-модала не имеет класса
   `.modal-close` (просто «Закрыть») — тест-селектор скорректирован на
   текст; продуктового дефекта нет.

## 6. PENDING-live (владелец, после деплоя)

- Живой чат: Summary chat-override реально меняет сводки (матрица DoD B06
  уже покрыта интеграционно на backend-лейне; живой прогон — postdeploy).
- Прод-проверка env-оси `SUMMARY_EMERGENCY_DISABLE` и подсказки на Обзоре.
- Прод-проверка 401/403 на `/api/factcheck/temporal/runs` из UI Фактчека.

@Orchestrator — к строгому независимому ревью.
