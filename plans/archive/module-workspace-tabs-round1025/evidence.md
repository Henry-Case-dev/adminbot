# F5 `module-workspace-tabs-round1025` — evidence (Step 4 @Builder)

> **Дата:** 22.09.2026. **Diff base:** HEAD `12a55bb` (baseline F5). **ADR:** ADR-1025-15.
> **APP_VERSION:** 2.58.10. **Δ DDL = 0.** **Δ каталога = 0.** Секреты не цитировались (R17/R18).
> **Итерация 2 (после @Reviewer, Changes requested — 4 пункта).**
> **Итерация 3 (после @Scanner, T-2738: M-F5S-1 + L-F5S-1..3) — см. §7.**
> **Итерация 4 (T-2714 карточка §49 + T-2703 Playwright-матрица + T-2733) — см. §8.**

## 1. Изменённые файлы

**Продукт (web/):**
- `web/app.js` — `WORKSPACE_TABS`/`routeSlug`/`WORKSPACE_TAB_LABELS`, `MODULE_PROMPT_GROUPS`,
  `PROVIDER_GROUPS` (6 групп §49), `MODULE_MODEL_BLOCKS`; динамический роутер
  (`parseWorkspaceRoute`/`isWorkspaceRoute`/`parsePromptLibraryRoute`/`_wsModuleById`,
  `_workspacePromptTabOf`/`_workspaceTabApplicable`, `normalizeRoute`/`routeToTab`/`routeParent`/`routeDepth`);
  `applyRoute` (неизвестный slug → витрина + toast; неприменимая вкладка → «Обзор»;
  **вторая дверь `#/ai/prompts/<slug>` — неизвестный модуль → `#/ai/prompts` + toast**);
  computed `workspace` (**две двери §48**: `door='modules'|'library'`, объект один),
  `workspaceModule`/`workspaceTab`/`workspaceTabs`/`workspacePromptFocus`/`workspacePromptList`/
  **`promptLibraryEntries`**/**`workspaceTestingBlocks`**/`workspaceCoverage`/
  `providerGrouped`/`workspaceModelGroups`; `currentTabGroups` (workspace-aware);
  methods `openModuleWorkspace` (навигация + fallback), `_workspaceNavAvailable`,
  `routeSlugOf`, `moduleBySlug`, `openWorkspaceTab`, `openWorkspacePrompt`,
  `openPromptLibrary` (**подключён к UI**), `_workspacePromptGroup`, `workspacePromptItems`,
  `workspaceGroupTab`, `_workspaceGroupsFor`, `workspaceTabHasContent`,
  `directStageCards`, `testDirectStage`; HUBS_V2['#/ai'] — 5 карточек §47.
- `web/index.html` — страница workspace (шапка + тумблер store F4 + табы),
  «Обзор», §85-стадии (честный placeholder), §84 L1/L2 карточки, §49 группы
  подключений (гейт `workspaceTab === 'models'`), §48 master-detail промптов,
  **`data-prompt-doors`** («из модуля → в библиотеку» / «из библиотеки → в модуль»),
  **`data-prompt-library-modules`** (вход в библиотеку из раздела ИИ),
  **`data-workspace-testing`** (реальные проверки подключений, reuse `testBlock`);
  generic empty-state не показывается на страницах workspace (`!workspaceModule`);
  llm_providers — 6 групп.
- `web/static/app.css` — раскладка `.workspace-prompt-lib` (3 зоны → mobile
  список/полный экран), тач-цель ≥44×44.

**Версия/доки:**
- `config/settings.py` — `APP_VERSION` 2.58.9 → **2.58.10**.
- `README.md` — `v2.58.9` → **v2.58.10** (cache-bust `?v=__APP_VERSION__` не меняется).
- `plans/reports/round1025_f5_ai_map.md` — карта раздела ИИ (T-2704/§117(1)).

**Тесты (новые):** `tests/js/round1025_f5_workspace_route_test.js`,
`tests/js/round1025_f5_models_test.js`,
`tests/js/round1025_f5_prompts_single_source_test.js`,
`tests/test_webapp_f5_round1025.py`.

**Маркеры (атомарно с кодом, не ослаблены; итерация 2 — усилены):**
- `tests/js/round1025_f5_workspace_route_test.js` — добавлены (b2) вторая дверь
  `#/ai/prompts/<slug>[/<stage>]`, (d2) «Тестирование» без контента,
  (g2) покрытие падает при потере вкладки.
- `tests/js/round1025_f5_prompts_single_source_test.js` — добавлен (a2)
  «обе двери → один объект configItems».
- `tests/test_webapp_f5_round1025.py` — усилены `test_dynamic_workspace_resolver`
  и `test_applyroute_handles_unknown_slug`; добавлен
  `test_prompt_library_second_door_and_testing_tab`.
- `tests/js/routing_test.js` — template-гейт зон → `providerGrouped`/`g.blocks`.
- `tests/test_webapp_round1011_ui.py` — `test_zones` → grouped-структура.
- `tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js`,
  `tests/test_scope_selector_round1025.py`, `tests/test_webapp_hotfix6_round1025.py`,
  `tests/test_webapp_hotfix7_round1025.py`, `tests/test_webapp_design_tokens_round1025.py`
  — пины версии 2.58.9 → 2.58.10.
- `tests/test_webapp_js_unit.py` — регистрация 3 новых JS-раннеров (аддитивно).
- F4-маркеры `tests/js/round1025_f4_module_store_test.js` (m) и
  `tests/js/round1025_f4_catalog_ui_test.js` (f) **остались зелёными без правок**
  (fallback-путь `openModuleWindow` сохранён; `return this.openModuleWindow(m)` на месте).

## 2. Прогоны (факт, итерация 2)

| Проверка | Команда | Результат |
|---|---|---|
| Синтаксис JS | `node --check web/app.js`; `node --check web/static/telegram-init.js` | оба OK |
| F5 workspace | `node tests/js/round1025_f5_workspace_route_test.js` | `MODULE-WORKSPACE-OK` |
| F5 models §49 | `node tests/js/round1025_f5_models_test.js` | `MODELS-GROUPS-OK` |
| F5 prompts | `node tests/js/round1025_f5_prompts_single_source_test.js` | `PROMPTS-SINGLE-SOURCE-OK` |
| Регресс JS | `routing_test.js` (`JS-UNIT-OK`), `round1024_prompts_ui_test.js`, `round1024_image_module_test.js`, `round1025_f4_catalog_ui_test.js`, `round1025_f4_module_store_test.js`, `round1025_hotfix7_shell_glass_heartbeat_test.js` | все OK |
| F5 pytest | `py -3 -m pytest tests/test_webapp_f5_round1025.py -q` | **17 passed** |
| Полный pytest | `py -3 -m pytest -q` | **8243 passed, 1 skipped, 5 failed** |
| Diff whitespace | `git diff --check` | OK |

**5 failed — пред-существующая проблема окружения, НЕ регресс F5:**
`tests/test_outgoing_guard_round1022.py` (2) и `tests/test_summary_cover_round1023.py` (3)
падают на `ImportError: cannot import name 'InputRichMessageMedia' from 'aiogram.types'`
(установленная версия aiogram). Файлы F5 не касается (backend/telegram-send);
воспроизводится в изоляции.

**Примечание к прошлому evidence:** ранее указано «8241 passed» — фактическое
число на baseline было 8242, после итерации 2 — **8243** (+1 новый pytest-тест).

## 3. Покрытые приёмочные сценарии (§9.1 spec)

1. §46 workspace: `#/modules/factcheck` → `activeTab=mod_factcheck`, тумблер из store F4, применимые вкладки (unit).
2. §48 единый источник: обе двери (**`#/modules/factcheck/synthesizer`** и **`#/ai/prompts/factcheck/synthesizer`**) → один и тот же объект `configItems`; правка видна в обеих; копий нет (JS a2).
3. §49 модель: `blockFieldValue` возвращает сохранённое значение; 0 POST при открытии; повторное открытие не мутирует.
4. §49 «Проверить»: spy `/api/llm/test` и `/api/images/test`; маска секрета не уходит (R17).
5. §84: L1/L2 карточки (`directStageCards`); mobile 1 колонка + 44px (CSS).
6. §85: вкладки `prep/clusterizer/writer` — честный placeholder без цифр.
7. Навигация: deep-link `#/modules/factcheck/synthesizer/<key>`, «назад» по иерархии (depth 0/1/2), неизвестный slug → `#/modules` + toast; **неизвестный модуль в двери библиотеки → `#/ai/prompts` + toast**.
8. §47/§48 «вторая дверь» из раздела ИИ: `data-prompt-library-modules` → `openPromptLibrary(m[, stage])` → `#/ai/prompts/<slug>[/<stage>]` → тот же config-item (JS b2/a2).
9. §4.3 п.2 / T-2700: вкладка «Тестирование» рендерится только при наличии тестируемых подключений (`workspaceTestingBlocks`, reuse `testBlock`); пустая не показывается; deep-link на пустую → дефолт «Обзор» (JS d2).

## 4. Инварианты

- Δ DDL = 0 (миграции/`services/**`/`web/api/**`/`handlers/**`/`bot.py` вне диффа — `git diff --stat` пуст по этим путям).
- Δ каталога = 0 — `test_catalog_delta_zero` (459/98/96/21/418) зелёный; `services/param_catalog.py` не тронут.
- CSP/zero-build: без новых библиотек/CDN/import/`require`; WebGL-контекст не создаётся.
- R16: новых эндпоинтов нет; reuse `/api/llm/test`, `/api/images/test`.
- R17/R18: секреты не логируются/не цитируются; `plans/current_task.md` не трогался.

## 5. Не подтверждено / открыто

- **Адаптивность-матрица 320–1440 (T-2703/T-2721/T-2726)** — Playwright/TMA WebView в
  среде @Builder недоступны; CSS-раскладка и тач-цели заявлены, overflow не измерялся.
- **§49 карточка (T-2714)** — поля «название/назначение/основная/резервная модель/
  статус/Проверить/Настроить»; в workspace-карточках реально представлены название/
  модель/источник/«Проверить»; явные «резервная модель»/«Настроить»-раскрытие не
  выделены отдельными элементами (reuse существующего рендера блока).
- **Витринная проверка в реальном Telegram WebView** — за владельцем (live-гейт).

## 6. Red→green ключевых проб (T-2733, итерация 2)

Метод: копия `web/app.js` → временная мутация (регресс) → прогон маркера (ожидается
падение) → восстановление из копии (byte-identical) → маркер снова зелёный.
Мутации не коммитятся; `Compare-Object` подтвердил идентичность восстановленного файла.

| # | Проба (требование) | Мутация (регресс) | Красный результат | Зелёный после |
|---|---|---|---|---|
| 1 | §9.3 покрытие (T-2702/T-2733) | в `workspaceCoverage` убран гейт `_workspaceTabApplicable(m, wt)` (m.tabs не учтён) | `AssertionError: g2: потеря вкладки «Модели» → параметр помечен потерянным` (exit 1) | `MODULE-WORKSPACE-OK` |
| 2 | §48 вторая дверь (T-2709) | из `routeToTab` убран `if (parsePromptLibraryRoute(r)) return 'prompts';` | `AssertionError: b2: routeToTab(#/ai/prompts/<slug>) == prompts` — `actual: 'status'` (exit 1) | `MODULE-WORKSPACE-OK` |
| 3 | §49 «не менять модель» (T-2717/T-2728) | `blockFieldValue` подставляет `'default-model'` вместо сохранённого | `AssertionError: e: сохранённая модель прочитана как есть` — `actual 'default-model' vs 'saved-model-XYZ'` (exit 1) | `MODELS-GROUPS-OK` |
| 4 | §48 «один источник» (T-2727) | `workspacePromptItems` возвращает клиентские копии | `AssertionError: a2: обе двери → ОДИН объект configItems (не копия)` (exit 1) | `PROMPTS-SINGLE-SOURCE-OK` |
| 5 | T-2700 «только применимые вкладки» | `workspaceTabHasContent('testing')` → безусловный `true` | `AssertionError: d2: пустое «Тестирование» скрыто` — `true !== false` (exit 1) | `MODULE-WORKSPACE-OK` |

Все пять проб: красный при регрессе → зелёный на текущем коде. Требуется независимое
подтверждение @Reviewer/@Scanner (T-2733 остаётся открытым).

## 7. Итерация 3 (@Scanner T-2738: M-F5S-1 + L-F5S-1..3)

**M-F5S-1 (Medium, блокер).** Причина: библиотечная дверь для модулей без
объявленной промпт-вкладки (`mod_summary`, `mod_sleep`) строила
`#/modules/<slug>/prompts/<key>`; `applyRoute` отбрасывал неприменимую вкладку на
`#/modules/<slug>` → `tab='overview'` → редактор не открывался (данные не терялись).

Исправление (`web/app.js`, минимальное, без правки `m.tab`/каталога):
- `parsePromptLibraryRoute` расширен до `#/ai/prompts/<slug>[/<stage>[/<promptKey>]]`;
  ключ `prompts.*` в слоте stage распознаётся однозначно (префикс `prompts.`),
  поэтому модуль без stage (`cover_style`, `system_prompt`) тоже адресуем.
- `workspace()` для `door='library'` пробрасывает `promptKey` (короткая форма
  stage→key действует только для `door='modules'`).
- `openWorkspacePrompt` учитывает дверь: из библиотеки остаётся в библиотеке
  (`#/ai/prompts/<slug>[/<stage>]/<key>`), а не строит маршрут на несуществующую
  вкладку модуля. Модульная дверь (`door='modules'`) не изменена.
- `routeParent` библиотеки ведёт `key → stage → slug → #/ai/prompts`.
- «Один промпт — один источник» сохранён: обе двери резолвят тот же config-item
  `prompts.*` (`workspacePromptItems`/`_workspacePromptGroup` без копий).

**L-F5S-3** (`applyRoute`): известный модуль без `MODULE_PROMPT_GROUPS` →
`#/ai/prompts` (чистая библиотека, без «пустой двери»). Проверка статическая — не
зависит от загрузки конфига (нет ложного редиректа до `loadConfig`).

**L-F5S-2** (`web/index.html`): дерево промптов — `<aside role="group"
aria-label="Промпты">`, кнопки без `role="listitem"` (валидная разметка).

**L-F5S-1** (`web/static/app.css`, `@media max-width:767px`):
`[data-workspace-tabs] button { min-height: 44px; }` + `.prompt-tree-item`.

**Тесты (обновлены/добавлены):**
- `tests/js/round1025_f5_prompts_single_source_test.js` — новая проба (g):
  `#/ai/prompts/summary` → редактор (не «Обзор»); клик по промпту без stage →
  `#/ai/prompts/summary/<key>`; со stage → `#/ai/prompts/summary/verbalizer/<key>`;
  фокус — тот же объект `configItems`; `applyRoute` маршрут не отбрасывает;
  factcheck через библиотеку тоже сохранён. `mkPromptsCtx(items, gid)` — параметр группы.
- `tests/js/round1025_f5_workspace_route_test.js` — новая проба (b3): `#/ai/prompts/budgets` → `#/ai/prompts`.
- `tests/test_webapp_f5_round1025.py` — новый `test_prompt_library_focus_empty_door_and_touch_aria`
  (M-F5S-1 грамматика/дверь, L-F5S-1/2/3 статически). **18 passed** (+1).

**Прогоны (итерация 3, факт):**

| Проверка | Команда | Результат |
|---|---|---|
| Синтаксис JS | `node --check web/app.js`; `node --check web/static/telegram-init.js` | `APPJS-OK`; `TELEGRAM-INIT-OK` |
| F5 prompts (M-F5S-1) | `node tests/js/round1025_f5_prompts_single_source_test.js` | `PROMPTS-SINGLE-SOURCE-OK` |
| F5 workspace (L-F5S-3) | `node tests/js/round1025_f5_workspace_route_test.js` | `MODULE-WORKSPACE-OK` |
| Все `tests/js/*.js` (32 файла) | цикл `node <file>` | все `exit=0` |
| F5 pytest | `py -3 -m pytest tests/test_webapp_f5_round1025.py -q` | **18 passed** |
| Целевые регресс-пины | `test_webapp_js_unit`, `test_round106_ia_smoke`, `test_webapp_back_button`, `test_webapp_hubs_matrix_ui`, `test_prompts_round1024`, `test_webapp_round1011_ui` | **151 passed** |
| Полный pytest | `py -3 -m pytest -q` | **8244 passed / 1 skipped / 5 failed** |
| Diff whitespace | `git diff --check` | exit 0 (только CRLF-предупреждения) |
| Δ backend/DDL | `git diff --stat -- services/ web/api/ handlers/ bot.py migrations/` | пусто; `services/param_catalog.py` не изменён |
| Δ каталога | `test_catalog_delta_zero` | 459/98/96/21/418 — passed |

**5 failed** — те же пред-существующие env-падения (`InputRichMessageMedia` из
установленного `aiogram`), файлы 10.22/10.23, вне диффа F5; новых падений нет
(baseline итерации 2 — 8243 passed, +1 новый pytest = 8244).

**Red→green новой пробы (M-F5S-1):** временная мутация `openWorkspacePrompt`
(`if (ws.door === 'library')` → `if (false)`) → проба (g) падает:
`actual '#/modules/summary/prompts/prompts.summary_cover_style'`,
`expected '#/ai/prompts/summary/prompts.summary_cover_style'` (exit 1).
Восстановление из копии — SHA256 идентичен (`C37FF6C8…D48DE7`), маркер снова
`PROMPTS-SINGLE-SOURCE-OK`. Требует независимого подтверждения @Reviewer/@Scanner (T-2733).

**Покрытые сценарии итерации 3:** M-F5S-1 `mod_summary` (библиотека → редактор),
`mod_sleep` (проба (g): `#/ai/prompts/sleep` → `#/ai/prompts/sleep/prompts.compress_system_prompt`
→ редактор, фокус — выбранный объект), `mod_factcheck`
(библиотека → stage+key). L-F5S-3 статически и JS.

**Не проверено итерацией 3:** live Telegram WebView (за владельцем, T-2742);
адаптивность-матрица 320–1440 (Playwright/TMA недоступны в среде @Builder).

## 8. Итерация 4 (T-2714 + T-2703 + T-2733)

### 8.1. T-2714 — карточка подключения (§49)

**Файлы:** `web/app.js`, `web/index.html`, `web/static/app.css`,
`tests/js/round1025_f5_models_test.js`, `tests/test_webapp_f5_round1025.py`.

- `web/app.js`: `data.connectionSettingsOpen: {}`; функция `buildConnectionCard(ctx, b)`
  (значения **только** из `PROVIDER_BLOCKS`/`models_*` через `blockFieldValue`;
  читается поле `role === 'model'`, `role === 'api_key'` не читается), computed
  `workspaceModelCards`, методы `connectionCard`/`toggleConnectionSettings`/
  `testConnection` (reuse `testBlock`).
- `web/index.html`: вкладка «Модели» → карточки `data-connection-card` с полями
  `data-conn-field="title|purpose|primary-model|fallback-model|status"`,
  кнопками `data-conn-test` («Проверить») и `data-conn-configure` («Настроить»);
  «Настроить» раскрывает существующую форму (`data-connection-settings`, reuse
  `saveBlock`). Ключи как значения не выводятся (F9/§46).
- `web/static/app.css`: `.conn-card/.conn-facts/.conn-fact`; тач-цели табов и
  карточек ≥44px.

**§49 «не менять сохранённую модель при открытии» сохранён:** карточка/форма
только читают `blockFieldValue`; раскрытие не пишет (0 POST).

### 8.2. T-2703 — адаптивность workspace (Playwright/Chromium, фактический прогон)

Chromium в среде **доступен**: `.venv` (`playwright 1.62.0`) + `ms-playwright/chromium-1234`.
Расширен существующий `tools/ui_round1025_matrix.py` (атомарно, без нового харнесса):
`F5_ROUTES = ('#/modules/factcheck', '#/modules/factcheck/models',
'#/modules/direct/models', '#/modules/summary')` + проба `F5_PROBE_JS` и
`_f5_failures` (overflow страницы, `data-workspace-head`, контейнер табов,
тач-цели табов/«Проверить»/«Настроить» ≥44px).

**Команда:** `.venv\Scripts\python.exe tools/ui_round1025_matrix.py`
**Результат:** `[matrix] failures: 0` (10 вьюпортов × 17 маршрутов;
артефакт `tools/_ui_round1025_raw.json`, скриншоты `tools/_ui_round1025_shots/`).

Фактические измерения workspace-маршрутов с карточками:

| Вьюпорт | overflow | tabsWrap | тач: табы | тач: «Проверить» | тач: «Настроить» |
|---|---|---|---|---|---|
| 320×700 | false | 0 | 44 | 44 | 44 |
| 390×844 | false | 0 | 44 | 44 | 44 |
| 768×1024 | false | 0 | 44 | 44 | 44 |
| 1024×768 | false | 0 | 44 | 44 | 44 |
| 1280×800 | false | 0 | 44 | 44 | 44 |
| 1440×900 | false | 0 | 44 | 44 | 44 |

Табы workspace: `tabsCount = 7` (Фактчек) / `8` (Сводки) на всех вьюпортах;
`tabsWrap = 0` — контейнер табов не создаёт горизонтального скролла.
Это **измеренный** результат Chromium, но **не** замена живой приёмки в Telegram
WebView (T-2742).

### 8.3. T-2733 — независимый red→green

Независимо подтверждён `review.md` (итер.2, @Reviewer Approved) — таблица
«Независимый red→green» (мутации b2/d2/g2/a/e, restore byte-identical); @Scanner
итер.3 закрыл M-F5S-1 со своим red→green (`evidence.md` §7).

Дополнительно red→green новых проб T-2714 (копия `web/app.js` → мутация →
прогон → restore; SHA256 восстановленного файла `EA886C07…D73584` идентичен):

| # | Проба | Мутация | Красный | Зелёный после |
|---|---|---|---|---|
| 1 | (g) T-2714 §49 fallback-модель | `var fallback = subs.length > 1 ? subs[1] : null;` → `null` | `AssertionError: g: резервная модель — из существующего subBlock (Ф11)` (exit 1) | `MODELS-GROUPS-OK` |
| 2 | T-2714 «ключи не читаются» | в `buildConnectionCard` добавлено чтение `role === 'api_key'` | pytest `test_connection_card_fields_and_disclosure` FAILED | F5 pytest **19 passed** |
| 3 | (h) T-2714 «Настроить» | `… = !this.connectionSettingsOpen[b.id]` → `= false` | `AssertionError: h: «Настроить» раскрывает существующую форму` (exit 1) | `MODELS-GROUPS-OK` |
| 4 | (i) T-2714 «Проверить» → `testBlock` | `var target = (card && card.testTarget) ? card.testTarget : b;` → `var target = b;` | `AssertionError: i: «Проверить» делегирует в testBlock` — `actual ['direct']` (exit 1) | `MODELS-GROUPS-OK` |

### 8.4. Прогоны итерации 4 (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Синтаксис JS | `node --check web/app.js` | OK |
| F5 models §49 (T-2714) | `node tests/js/round1025_f5_models_test.js` | `MODELS-GROUPS-OK` |
| F5 workspace/prompts | `node tests/js/round1025_f5_workspace_route_test.js`; `…prompts_single_source…` | `MODULE-WORKSPACE-OK`; `PROMPTS-SINGLE-SOURCE-OK` |
| Все `tests/js/*.js` | цикл `node <file>` | 0 падений |
| F5 pytest | `py -3 -m pytest tests/test_webapp_f5_round1025.py -q` | **19 passed** (+1 новый T-2714) |
| Целевые пины | F5 + design_tokens + round1011_ui + prompts_round1024 + hotfix6/7 | **150 passed** |
| Полный pytest | `py -3 -m pytest -q` | **8245 passed / 1 skipped / 5 failed** (те же env `InputRichMessageMedia`) |
| Playwright §71 | `.venv\Scripts\python.exe tools/ui_round1025_matrix.py` | **failures: 0** |
| Diff whitespace | `git diff --check` | exit 0 (только CRLF-предупреждения) |
| Δ backend/DDL | `git diff --stat -- services/ web/api/ handlers/ bot.py migrations/` | пусто; `services/param_catalog.py` не изменён |
| Δ каталога | `test_catalog_delta_zero` | 459/98/96/21/418 — passed |

**Не проверено:** живой Telegram WebView (T-2742, за владельцем).
