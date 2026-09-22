# Global Map (architectural memory)

## Round 10.25 F7 `permsoc-local-space-round1025` (§60–§67 PERMsoc — локальное пространство чата + серверные блок-гейты) — 23.09.2026, Step 6 @Scanner (T-2957; **итерации 2–3, финал**)

- **Новая подтверждённая зависимость (серверный слой):** `services/permsoc.py` (`block_enabled(chat_id, block)` → `feature_gates.gates_enabled`; `PermsocBlockGate(block)` — BaseFilter) → `services/feature_gates.py` (`permsoc_reactions`/`permsoc_schedule` ∈ `ALL_GATED_FEATURES`, `DEFAULT_BY_FEATURE=True`) → память `chat_params["gates"]` (Δ DDL=0, без каталога). Потребители: `handlers/{war_alert,common,vasya,slavik,alan,alan_greeting}.py` (добавочный `PermsocBlockGate("reactions")`) и `services/goodmorning_scheduler.py:_tick` (`block_enabled(chat_id,"schedule")` → no-send). Управление: `PUT/GET /api/chat/{id}/gates` (RBAC `permsoc*` → global admin; `who_can_toggle='global'`); доставка kill-switch — `GET /api/me.ui_flags["PERMSOC_BLOCK_GATES_ENABLED"]`.
- **Клиентский слой (presentation, zero-build):** `web/app.js` `PERMSOC_OWNER_BLOCKS` (6 блоков, key-level partition) / `PERMSOC_LOCAL_KEYS` guard / `permsocBlockGateOn`/`canToggleMaster`/`saveKostikProbability`; H-F7-1-fix `PERMSOC_BLOCK_SUBGROUPS`+`permsocRenderItems` (24 витринные подгруппы §62–§67); M-F7-2-fix `PERMSOC_LIST_WIDGET_KEYS`+`_normalizeConfigItems`+`listEditorProps` (списки ID Оли → `list-editor variant='ids'`); **H-F7-7-fix** `list-editor._numericList()/toStoredValue()` (чисто-числовые ID → `Number`, фразы Костика — строки; сервер `filters/olya_video.py` сравнивает int); `web/index.html` scope-шапка «PERMsoc · Только этот чат» + мастер §61; `services/param_catalog.py` не правится.
- **Аудит (итер.3, финал):** Critical 0 / High 0 / Medium 0 / Low 3 / Info 3. **Вердикт: к деплою — ДА** (@Reviewer итер.3 — Approved). Закрыто: **H-F7-7** (round-trip типа: `includes(-100123)===true`, `includes('-100123')===false`; pytest-эмуляция `OlyaVideoFilter` int→True/str→False; только ID-ключи Оли, Костик-фразы строками), **H-F7-1** (24 подгруппы в DOM), **M-F7-2** (`olyaListStructured={hasListBtn:True,hasTextarea:False}`), **L-F7-3** (no-chat `ownerCount=0`+banner), **L-F7-5** (4→6), **L-F7-8** («Лимит N ID/фраз»), **L-F7-9** (`evidence.md` §5 — D1 клиентский, серверный denylist = follow-up). Открыто (ноты, не блокеры): L-F7S-1 (серверный global-путь не отклоняет PERMsoc; не эскалация, global-admin-only), L-F7-4 (`dead_page_post_on_join` без рантайм-гейта — T-2939/2940), L-F7-6 (DM-мастер pre-existing). Отчёт: `plans/reports/round1025_f7_scanner_audit.md`. Инварианты ✔: Δ DDL=0, Δ каталога=0 (459/98/96/21/418), `APP_VERSION` 2.58.15, CSP/zero-build, R17/R18 (`pre-round1025-f7`), `git diff --check`=0. Прогоны @Scanner (итер.3): `node --check` OK, JS **38/38**, `pytest -q` **8374/0**, matrix **failures:0**.

## Round 10.25 F6 `memory-analytics-reorg-round1025` (§21–§30 «Аналитика»/adapter ExecutionGraph + §52–§59 «Память») — 23.09.2026, Step 6 @Scanner

- **Новая подтверждённая зависимость (клиентский слой, zero-build):** `web/index.html` (внешний `<script src="/static/execution_graph.js?v=__APP_VERSION__">` **ДО** `/web/app.js`) → `web/static/execution_graph.js` (`window.ExecutionGraph`, IIFE, без DOM/внешних ресурсов) → `web/app.js` (`methods.execGraphApi`, computeds `execTrace`/`execSummaryGraph`/`execTraceNodes`/`execAggregate`/`execPreview`, проекция `tokenFlowTree`) → `GET /api/analytics/usage/latest` (РЕЖИМ 1 — трассировка) и `GET /api/analytics/usage/summary?period=day|week|month` (РЕЖИМ 2 — агрегат). `web/api/analytics.py`/`services/**` — read-only, контракт не менялся.
- **Канонический контракт `ExecutionNode`** (`parentIds` — только линейная последовательность (первый/`tool` → `[]`, `parent_id` в БД нет), `status='unknown'`, `provider/durationMs/finishedAt=null`, `cost/costCurrency=null` при `price_known!==true`, `kind` enum `llm|algorithm|tool|format|publish|other`, `algorithm/format/publish` зарезервированы и **не эмитятся** из текущих данных).
- **CSS:** аддитивные `.token-flow__node--llm/--algorithm/--format/--publish/--other`, `.exec-detail` (desktop side-panel → mobile bottom-sheet через `@media max-width:767px`), `.exec-preview` — в `web/static/app.css`; единственный компонент `.token-flow` (вторая система визуализации не создаётся, §116/§111).
- **«Память»:** `HUBS_V2['#/memory']` — 3 раздела (`#/memory/rag`→«Настройки памяти», `#/memory/lore`→«Лор чатов», `#/memory/relations`→«Люди и связи»); presentation-подгруппы `MEMORY_SUBGROUPS`/`_memoryGroups`/`_memorySubgroupOf` (`web/app.js`) при `currentTab.id==='memory_rag'`; `services/param_catalog.py` не правится (Δ каталога = 0).
- **Честные состояния:** `fmtCost(v, known)` (`$0` только при `known!==false`, иначе «Нет данных»); «Стоимость LLM» отделена от «Ресурсов сервера»; «Безлимит (∞)» без бара. Блокировка `TOKEN_FLOW_NODEFLOW_ENABLED`/`TOKEN_ANALYTICS_ENABLED` сохранена; новый флаг не вводился (ADR-1025-19 D8).
- **Аудит (итер.2):** Critical 0 / High 0 / Medium 0 / Low 2 / Info 4. Закрыто: **H2** (поиск + статус-селект/`execStatusOptions`/adapter `searchHaystack`), **M-F6S-1** (`setExecMode`→`resetExecFilters`, `execAggregate` только `{module}`, «Сбросить» в обеих ветках), **L-F6S-3** (статус-селект), **L-F6S-4** (`aria-modal`+`.exec-detail-backdrop`+`Esc`), **L-F6S-5** (удалён мёртвый шов `memorySubgroup`), **H1 §52** (@Architect AMEND-1 `adr-1025-19a`, 3 карточки). Техдолг: L-F6S-1 (summary без `price_known`), L-F6S-2 (OFF-«Итого»). Отчёт: `plans/reports/round1025_f6_scanner_audit.md`. **Вердикт: к деплою — ДА.** Инварианты ✔: Δ DDL=0, Δ каталога=0 (459/98/96/21/418), `APP_VERSION` 2.58.14, CSP `script-src 'self'`/zero-build, R17/R18, `git diff --check`=0. Прогоны @Scanner: JS 37/37, F6 pytest 19, полный pytest 8334/1skip/5-env. Live-гейт T-2917 — PENDING OWNER.

## Round 10.25 F5 `module-workspace-tabs-round1025` (§46–§49/§84/§85) — 22.09.2026, Step 6 @Scanner (повторный)

- **База:** HEAD `12a55bb` (`pre-round1025-f5`) + рабочее дерево (правки не закоммичены). Отчёт: `plans/reports/round1025_f5_scanner_audit.md`; AI-карта: `plans/reports/round1025_f5_ai_map.md`. **0 Critical / 0 High / 0 Medium / 0 Low / 2 Info** → к деплою ДА (итер.1: [M-F5S-1] + [L-F5S-1..3] закрыты).
- **Новые связности (подтверждены):** шов F4 `openModuleWorkspace(m)` (`web/app.js`) **заменён** на `navigateTo('#/modules/<slug>')`; прежняя реализация `openModuleWindow(m)` сохранена как регресс-путь/fallback (`file://`, unit-стаб без hashchange, отсутствие workspace-определения). Это закрывает «точку входа F5», отмеченную в F4-секции ниже.
- **Динамический резолвер:** `parseWorkspaceRoute`/`parsePromptLibraryRoute`/`_wsModuleById` + `normalizeRoute`/`routeToTab`/`routeParent`/`routeDepth` (`web/app.js`) — маршруты `#/modules/<slug>[/<wt>[/<stage>/<key>]]` и `#/ai/prompts/<slug>[/<stage>[/<key>]]`; `routeToTab`= `m.tab` → RBAC (`canViewTab`) и kill-switch (`_flagTabHidden`) reuse без правок; `applyRoute` выводит производное `workspace` (door/tab/stage/promptKey) из hash, неизвестный slug → `#/modules`/`#/ai/prompts` + toast.
- **Новые витринные константы (Δ каталога = 0, только `web/**`):** `WORKSPACE_TABS`/`WORKSPACE_TAB_LABELS`/`MODULE_PROMPT_GROUPS`/`PROVIDER_GROUPS`/`MODULE_MODEL_BLOCKS`; `services/param_catalog.py` read-only (459/98/96/21/418).
- **§48 «один промпт — один источник»:** обе двери резолвят один `configItems`-элемент `prompts.*`; библиотечная дверь остаётся библиотекой (`#/ai/prompts/<slug>[/<stage>]/<key>`, M-F5S-1 fix) → редактор открывается и для `mod_summary`/`mod_sleep`; один write-path F0 (`saveConfigItem`→`persistItems`); новых хранилищ/эндпоинтов нет (reuse `POST /api/llm/test`,`/api/images/test`).
- **§49-карточка подключения (T-2714):** `buildConnectionCard`/`workspaceModelCards`/`connectionCard`/`toggleConnectionSettings`/`testConnection` — производная от `PROVIDER_BLOCKS` (название/назначение/основная/резервная модель/статус + «Проверить»/«Настроить»); секреты `keys.*` не читаются, открытие/раскрытие = 0 POST, «Проверить» → существующий `testBlock`.
- **Закрыто (итер.2):** [M-F5S-1] RESOLVED (probe PROBE-ALL-PASS на реальном `web/app.js`); [L-F5S-1] тач-цели ≥44px; [L-F5S-2] `role="group"` без `listitem`; [L-F5S-3] пустая дверь → `#/ai/prompts`.
- **Тесты/инварианты:** `node --check` OK; JS `MODULE-WORKSPACE-OK`/`PROMPTS-SINGLE-SOURCE-OK`/`MODELS-GROUPS-OK`/`JS-UNIT-OK` + `IMAGE-MODULE-OK` + hotfix7 OK; целевые pytest **19 passed**, регресс-пины **202 passed**; Δ DDL=0, Δ каталога=0, CSP/zero-build чист (без WebGL/новых API/библиотек); `APP_VERSION` **2.58.10**; `stash@{0}`/теги/бэкапы целы; маркер-тесты не ослаблены.

## Round 10.25 F4 `module-catalog-quickpanel-store-round1025` (§31–§45) — 22.09.2026, Step 6 @Scanner

- **База:** HEAD `b5f8348` + рабочее дерево (правки не закоммичены, включая rework iter2). Отчёт: `plans/reports/round1025_f4_scanner_audit.md`.
  **0 Critical / 0 High / 0 Medium / 2 Low / 3 Info** → к деплою — да.
- **Новые связности:** `ModuleConfigurationStore` (`web/app.js:4279-4573`) — тонкий слой над существующим `configItems` (`GET /api/config`),
  ключ `scope_type/scope_id/module_id` (`storeKey`) ↔ `scopeEpoch`/`_scopeGuard` (F3) ↔ канонический write-path F0 `persistItems`
  (`web/app.js:6297-6437`; ровно один POST на действие). Overlay `moduleOptimistic`/`modulePending`/`moduleSaveError` — единственная
  «оптимистичность» (структурный откат: `configItems[i].value` не мутируется до подтверждения).
- **Витрина ↔ серверный код:** `MODULES[].runtimeGate` (9 `global` / 4 `per_chat`) + `parentGate: flags.summary_enabled` (7 модулей)
  (`web/app.js:449-530`) ↔ аудит гейтов ADR-1025-14 §D3 ↔ `bot.py:752-786` (регистрация роутеров 0a–0i по глобальному
  `hot.get("flags.summary_enabled")`), `handlers/*`, `services/feature_gates.py`, `services/budget_gate.py`, `services/image_generation.py`.
- **Избранное (UI-предпочтение, не конфигурация):** `localStorage['adminbot.modules_quickpicks.v1'(:<telegram_id>)]`
  (`web/app.js:4575-4660`) ↔ панель `.module-quick` §34–§36. Закрепление — ноль серверных мутаций.
- **Точка входа F5:** шов `openModuleWorkspace(m)` (`web/app.js:4664-4666`) → существующая модалка `openModuleWindow(m)`
  (регресс-путь сохранён); новых маршрутов F4 не создаёт (F5 заменит реализацию шва).
- **Раскладка:** `.module-catalog` (`container-type: inline-size`) + изолированные `@container`-тиры `.module-list` ≤3/2/1 и
  `.module-quick` ≤4/2/1 (`app.css:1878-1902+`); общий triple-rule `.prov-grid/.module-list/.hub-grid` не изменён; тач-цель 44×44.
- **Проверки:** `node --check` OK; JS `MODULE-STORE-OK`/`MODULE-CATALOG-OK`/`JS-UNIT-OK`; целевые pytest **165 passed**;
  полный pytest **8229/0**; Δ DDL=0, Δ каталога=0 (459/98/96/21/418), CSP/zero-build чист; `stash@{0}`/теги/бэкапы целы.
- **Открытое (Low, не блокер):** `stickyFailedKeys` (F0) протекает между областями в счётчиках/фильтре [L-F4S-1];
  parent-gate проверяется по эффективному `value`, а не `global_value` [L-F4S-2]. Info: kill-switch `flags.dream_enabled`/
  `flags.nostalgia_enabled` вне `REGISTRY` (Δ каталога=0) — статус Сна/Ностальгии по нему не моделируется.

## Round 10.25 hotfix5 `summary-cover-window-round1025` (21.09.2026, Step 6 @Scanner)

- **Дифф `0e43c37..b3fb6a5`**, коммит `b3fb6a5`. Отчёт: `plans/reports/round1025_hotfix5_scanner_audit.md`.
  **0 Critical / 0 High / 1 Medium / 3 Low / 1 Info** → к деплою — да.
- **Новые связности:** env-only окно `IMAGE_ATTEMPT_TIMEOUT_SECONDS` (180 c) → `_image_attempt_timeout` →
  `generate(timeout=…)` (verbose-обложка) ↔ bounded-retry `IMAGE_GENERATION_MAX_ATTEMPTS`/
  `IMAGE_GENERATION_RETRY_BACKOFF_SECONDS` (`image_generation.py:326-352`, `:786-829`). Прежнее
  `IMAGE_REQUEST_TIMEOUT_SECONDS` (90 c) остаётся у `probe`/`generate`-default.
- **Бюджет:** `METRIC_IMAGE_CALLS` ↔ собственная ветка `worker_budget._metric_limit` (`:284-291`) от
  `WORKER_DAILY_IMAGE_CALLS_PER_CHAT/GLOBAL`; одно списание на запрос (`consume_budget=False` на попытках).
- **Планировщик:** `summary_scheduler._tick` кастует `chat_id` из PG к `int` до DM-фильтра/`generate_and_send`
  (per-chat override «Стиля обложки» резолвится) ↔ `summary_generator._resolve_cover_style_text`.
- **Проверки:** pytest **8124/0** (113.19 s), JS **24/24**, Δ DDL=0, Δ каталога=0, `stash@{0}` цел, zip в индексе нет.

## Round 10.25 <F2: дизайн-токены §8 + Liquid Glass v2 + фон §10> (21.09.2026, Step 6 @Scanner)

- **Дифф `f2328fb..HEAD`** (коммит `e895726`), фича `design-tokens-liquidglass-v2-round1025`.
  Отчёт: `plans/reports/round1025_f2_scanner_audit.md`. **0 Critical / 0 High / 3 Medium / 4 Low.**
- **Новые связности:** токены `--surface-*/--text-*/--teal/--warn/--err/--grad-*/--glass-*` (`app.css:5-56`)
  ↔ потребители `web/index.html` + `web/app.js` (палитра графика `app.js:6349`, фолбэки темы `telegram-init.js`);
  inline SVG `#lg-displace` (`index.html:27-42`, `feTurbulence→feGaussianBlur→feDisplacementMap`)
  ↔ `--glass-displace: url(#lg-displace)` ↔ `[data-glass="a"|"b"|"c"]` (`app.css:916-960`)
  ↔ `_liquidGlassSupported`/`reconcileLiquidGlass` (`app.js:7998-8027`).
- **Фон §10:** `@property --grad-angle` + `grad-spin`(75s)/`grad-drift`(105s) (`--grad-speed`/`--grad-speed-slow`)
  ↔ `html.lg-bg-paused` (`app.css:130-137`) ↔ `setBgPaused` внутри единственного `onVisibilityChange` (`app.js:8031`).
- **Проверки:** pytest **8096/0** (106.03 s), JS **24/24**, Δ DDL=0, Δ каталога=0, `git diff --check`=0, `stash@{0}` цел.
- **Открытое (Medium, не блокер):** необратимое понижение A→B + пропуск route-узлов [M-1]; оптимистичный детект
  WebKit может лишить blur панели `[data-glass="a"]` на iOS [M-2]; цена преломления не измерена [M-3].

## Round 10.25 <F1: IA v2 + app-shell> (21.09.2026, Step 6 @Scanner)

- **Diff `65e39fb..78e612a`** (коммиты `1ebbd7b`, `ff34115`, `b1c87b0`, фикс аудита `78e612a`). Фича `ia-shell-navigation-round1025`, Wave 1.
- **Итог (повторный аудит после `78e612a`): 0 Critical / 0 High.** Отчёт: `plans/reports/round1025_f1_scanner_audit.md`.
  Первично было 1 High / 2 Medium / 4 Low; всё закрыто.
- **H-1 (закрыт `78e612a`):** `bottomNavItems` (`web/app.js:1355-1371`) строит «Ещё» от `navItems` по `group`
  (`hasExtra = some(n.group !== 'public')`) — роли «только Память/Доступы/PERMsoc» на <768 получают шторку с пунктом.
  Тест поведенческий в `tests/js/round1025_ia_routing_test.js`; на `b1c87b0` падал бы (`bottom=[status,how]`).
- **M-1 (закрыт):** `_routeLabel` (`web/app.js:3339-3360`) берёт подпись из карточки хаба для маршрутов вне `TABS`
  (`#/ai/persona` → «Личность и стиль»), сырой hash не показывается.
- **M-2 (закрыт):** объём OFF (nav-scope: help-layout / matrix-table / «Аналитика» не откатываются) зафиксирован в ADR-1025-1 D5 и spec §6.4; «мёртвых» состояний нет.
- **Low:** L-1 (дубль `min-width`) и L-5 (пустые `.sidebar-sep`) закрыты; L-2/L-3/L-4 — техдолг в `tasks.md`.
- **Связи:** `NAV_MEMORY=memory` (`services/param_catalog.py` `NAV_ORDER/TAB_NAV`) ↔ `TABS[].menu:'memory'`
  ↔ `NAV_ITEMS_V2`/`HUBS_V2['#/memory']` (`web/app.js`) ↔ sidebar/drawer/bottom-nav (`web/index.html`+`app.css`)
  ↔ `ui_flags.IA_V2_ENABLED` (`web/api/routes.py` ← `config/settings.py`). Δ каталога=0, Δ DDL=0.
- **Факт (повторный прогон):** pytest **7996/0** (112.26s), JS **21/21**, Playwright-матрица **0 нарушений**;
  `git diff --check`=0, `node --check`=0; F0-слой (`persistItems/saveState/notify`) не тронут; `stash@{0}` (F1-WIP) цел.

## Round 10.25 «F0: конфигурация + устойчивость к database is locked» (20.09.2026, Step 6 @Scanner)

- **Diff `pre-round1025..HEAD`** (коммиты `c0cb8aa`…`9a5f265`). Фича F0
  (`f0-config-bugfixes-round1025`), P0 Wave 0.
- **Итог: 0 Critical / 1 High / 3 Medium / 8 Low / 6 Info.** Отчёт:
  `plans/reports/round1025_f0_scanner_audit.md`.
  **Вердикт: Шаг 7 заблокирован до закрытия H-1** (ложный успех `saveBlock`).
- **ПОВТОРНЫЙ АУДИТ (после `5dd2b0d`/`83fc4c4`): 0 Critical / 0 High / новых
  Medium 0 → к Шагу 7 (Merge) ДА.** Закрыты H-1 (`saveBlock` успех только при
  `state==='saved' && !failed && !skipped`), M-1 (`except BaseException` +
  rollback, retry только `locked`), M-3 (`server_value:null`+`secret:true` для
  `keys.*`), Low L-1/L-3/L-4/L-5/L-6. **M-2** отложен и зафиксирован
  (`f0-round1025-report.md:123`). Цифры: pytest **7946 passed** (106.27s), JS
  **19/19**; новые тесты падают на pre-fix `9a5f265` (3 failed / 25 passed + JS).
  Δ DDL=0, Δ каталога=0, промпты/`smart_cache` не тронуты, `git diff --check` = 0,
  секретов в диффе нет.
- **Ключевые связности раунда:**
  - **F0.5 DB-write:** `services/database.py::DatabaseService.write_transaction`
    (single-writer `self._lock` + bounded retry `_LOCK_RETRIES`/backoff,
    `_note_lock_exhausted`/`database_lock_exhausted_total`, `commit_if`) — единая
    обёртка для `insert_graph_fact(commit=True)`, `upsert_bot_reply`,
    `touch_graph_facts`; kill-switch `settings.DB_LOCK_RESILIENCE_ENABLED`
    (env-only ClassVar, Δ каталога = 0). Переведены также
    `services/persistent_throttling.py` (`_db_write`) и
    `services/summary_memory.py::_embed_cache_store` (сырой `db.db` убран, T-2449).
  - **F0.1 save-path:** `web/api/routes.py::_post_config_global` (2 прохода:
    валидация → per-key optimistic → `ConfigCache.set_many`, одна PG-транзакция);
    `services/chat_params.py` (`ChatParamsResult.revalidated/updated_at`,
    `ChatParamsConflict.conflicting`, `_patch_already_applied`/`_diff_patch`,
    in-process `_chat_write_lock` LRU + PG `pg_advisory_xact_lock`).
  - **Клиент:** `web/app.js::persistItems` — единая точка (guard in-flight по
    ключу, scope-split chat/global, 409-recovery), `saveState` computed +
    `sticky-save` (`data-save-state`), `notify`/`toast` (дедуп, очередь ≤3).
    Связь с **F9** `secrets-and-save-states-round1025` (F9 читает результат F0,
    UI-слой секретов — там).
  - **F0.3 анти-клише:** `services/anticliche_worker.py` — capacity vs per-run
    (`ANTICLICHE_MAX_PATTERNS_PER_RUN`), bounded rounds (`ANTICLICHE_MAX_ROUNDS`),
    merge-дедуп против БД (`_normalize_stored`), события `ANTI_CLICHE_*`;
    `web/api/anticliche.py` отдаёт `per_run`/`max_rounds` (аддитивно).
  - **F0.4:** safe-area тостов (`web/static/app.css`), «Подробнее» для длинных
    ошибок, per-field подсветка `is-save-failed`.

## Round 10.24 «Disaster Recovery: UI & Backend Bloat» (UPD2–UPD6, 20.09.2026, Step 6 @Scanner)

- **Baseline `00eab85` → HEAD `379cfdd`** (132 файла, +18264/−1016). 24 фичи F1–F24.
- **Итог: 0 Critical / 0 High / 0 Medium / 3 Low / 5 Info.** Отчёт:
  `plans/reports/round1024_scanner_audit.md`. Вердикт: Merge/деплой разрешён.
- **Ключевые связности раунда:**
  - **F20 (critical fix)** `web/api/routes.py::post_config` — разведены два namespace:
    `perm_overrides` (матрица прав → только `effective_matrix`) и `overrides`
    (значения per-chat → база merge). `services/chat_params.set_chat_params` заменяет
    только `overrides`+`meta`; `perm_overrides`/`gates`/`keys` неприкосновенны. Тот же
    merge-контракт в DELETE `/api/config/chat/{key}` и `services/chat_settings_seed.py`.
  - **F21** `services/budget_gate.py::budgets_enabled()` (chat→global→default ON,
    fail-open ON) → единая точка enforcement: `services/chat_usage.budget_snapshot`,
    `services/worker_budget.global_degradation_allows`/`consume`,
    `services/direct_chat_service._apply_context_budget`. Каталог-ключ
    `flags.budgets_enabled` на вкладке `mod_budgets`; учёт статистики при OFF сохранён.
  - **F22** `manage.py apply-chat-overrides` (merge current+patch) и
    `audit-chat-overrides` (READ-ONLY SELECT, R17-safe, fail-loud, `--strict`).
  - **F11** `/api/config/keys/own` получил scope `auto|global|chat`; global-ветка →
    `is_global_admin` + `chat_keys.is_global_secret` (`keys.image_api_key`, kill-switch
    `BYOK_IMAGE_KEY_ENABLED`) → глобальный слой `cache.set` + аудит в `chat_lore_history`
    (sentinel `chat_id=0`, только `***`). `services/image_generation.KEY_API_KEY`.
  - **F9** `services/disk_retention.py` — единый источник ротации (>1 DB-бэкапов
    запрещено, `imported_history_*.jsonl` immutable, content-sniff fail-closed,
    `apply_cleanup` re-classify + verify свежего бэкапа). Вызывается из
    `services/memory_backup._rotate` и `services/memory_rebuild.create_safety_backup`;
    CLI `manage.py disk audit|cleanup` (dry-run по умолчанию).
  - **F13/F14/F19** `services/media_marker.py` (диалект `[медиа: type tg:id]`) →
    `services/chat_context.format_chat_context` / `services/thread_chain.collect_thread_chain`
    / `direct_chat_service._build_current_question`; `services/native_media.py`
    (`resolve_reply_video`/`voice_media_message`/`download_to_tmp`) → `bot.py`
    `ToolDeps(transcriber=voice_service)` → `services/tool_router` нативные пути
    `summarize_video`/`download_media`, `transcribe_video` (10-й инструмент канона R9);
    командный форс-повтор `handlers/youtube.py` → `handlers/voice_transcription.force_repeat_from_reply`.
  - **F16** `handlers/youtube._process_youtube_summary`: A) тихая yt-dlp-загрузка →
    B) `media_share` + `summarize_media_url` → C) субтитровый фолбэк (L3-only;
    `YouTubeSummarizerService.summarize_cascade` больше не ходит мультимодалкой по
    watch-URL). Причина `YouTubeTranscriptUnavailableException.reason` (`age_restricted`)
    → отдельный пул фраз.
  - **F17** `services/smart_cache.py` — PRAGMA WAL/busy_timeout/synchronous + bounded
    retry на `database is locked` (kill-switch `SMART_CACHE_LOCK_RESILIENCE_ENABLED`).
  - **F18** `services/database.row_get` применён в `web/api/chat_lore._participant_names`
    (aiosqlite.Row без `.get` → терялись имена участников) и `web/api/oversight._feed_user_index`.
  - **F1** `LLMClient.generate_background(purpose/deadline/max_attempts)` (отдельный
    канал фонового graph-extract, чанки + единый батч-кап + per-chat счётчик фейлов);
    **F8** `dream_worker._run_persona_traits_step` (traits перед paradigm-ветками);
    **F2** `services/external_log.py` (`log_external_api`/`trace_step`/`log_dropped`).
  - **Каталог/UI:** GROUPS 98 (+`limits_anticliche`, +`flags_module_budgets`, перенос
    `flags_module_images` в новую `mod_images`); `GET /api/me.ui_flags` доставляет
    env-only kill-switch'и (F3/F4/F5/F6/F10/F11) во фронт без inline-скриптов.
- **Валидатор:** полный pytest **7911 passed / 0 failed** (103.71 s); SQLite **v12**
  (Δ=0), PG DDL **Δ=0**; канон инструментов **10**; `git diff --check` exit 0; секретов
  в диффе нет.

> Архитектурная память Scanner. Не источник правды о коде — только карта связностей.
>
> **АКТУАЛЬНЫЙ baseline эпика 10.21 (`System 2 Reasoning & Memory Rebuild`, 18.09.2026, Step 6 @Scanner, re-audit):**
> HEAD `21cd54c` + рабочее дерево (6 фич F1–F6, не закоммичено). @Reviewer `Approved` (iter 3), полный pytest
> **6779 passed / 0 failed** (после пост-скан фиксов @Builder). Схема БД **v12** (Δ=0), каталог **Δ=0** (ClassVar-рубильники
> вне param_catalog). `git diff --check` — только LF/CRLF. **Статус: 0 Critical / 0 High / 0 Medium открыто** (S10.21-1/-2
> закрыты, как и Low S10.21-3/-4/-5/-6/-7/-9); осталось Low S10.21-8 (vec парадигм CLI) + 4 Info + 2 новых Low
> (N10.21-1 тест-покрытие, N10.21-2 бинарный `roster_incomplete`) → **раунд передаётся на Merge/деплой**.
> Отчёт: `plans/reports/round1021_scanner_audit.md` (§«Re-audit после пост-скан фиксов»). Детали карты — ниже.
>
> **ФИНАЛЬНЫЙ baseline эпика 10.18 (БАТЧИ 1–4: F1–F7, 15.09.2026):**
> HEAD `118a03c` + рабочее дерево (F7 settings-worker-sync, F1 betterstack-us-region-401,
> F2 sleep-manual-cascade-badges, F3 graph-density-scoring-stoplist, F4 graph-physics-stabilization,
> F5 metafact-penalty-extractor-prompt, F6 role-matrix-settings-actualization); прод `b6c153f`.
> pytest **6137 passed / 0 failed**; JS-гейты OK (`node --check`, `JS-UNIT-OK`, `VUE-MOUNT-OK`);
> `git diff --check` exit 0.
> Каталог-инвариант 10.18: **REGISTRY 436 / Settings 406 / categorized 411 / GROUPS 90 /
> mapped 88 / TAB_RULES 19 / CONFIG_TAB_TITLES 19** (+1 — F1 `BETTERSTACK_HOST`; F2–F6 — Δ=0).
> SQLite **v10** (F3: `edges.fact_id` + `idx_edges_fact_id`).
> **Статус скана: 0 Critical / 0 High по ВСЕМУ эпику → готов к @Reviewer/@PM → Merge/архивация/деплой**
> (открыто 1 Medium S10.18-30 + 2 Low S10.18-29/-35 + 11 Info; сводная таблица — отчёт §10.4).
> П.6 (Headroom) — OUT OF SCOPE репозитория, в коде ссылок нет.
>
> **АКТУАЛЬНЫЙ baseline эпика 10.19 (БАТЧ A: F1 + F8, 15.09.2026):** HEAD `fd6acc7` (10.18 COMPLETED+DEPLOYED,
> прод `16a8c0b`) + рабочее дерево (F1 betterstack-ingest-bearer-contract, F8 graphrag-memorize-robustness).
> pytest **6164 passed / 0 failed**; JS-гейты OK; `git diff --check` exit 0; каталог **436/406/411/90/88/19**
> (Δ Батча A = 0); SQLite **v10**. **Статус: 0 Critical / 0 High / 0 Medium → к Батчу B (F2 бюджеты) можно**
> (открыто 2 Low S10.19-1/-2 + 4 Info; перенос рисков 10.18 — S10.18-30 Medium и др.).
> Отчёт: `plans/reports/round10.19_scanner_audit.md`.
>
> **АКТУАЛЬНЫЙ baseline эпика 10.19 (БАТЧИ A–B, 15.09.2026):** HEAD `fd6acc7` + рабочее дерево
> (F1 betterstack-ingest-bearer-contract, F8 graphrag-memorize-robustness, F2 direct-chat-budget-unlimited).
> pytest **6195 passed / 0 failed**; JS-гейты OK; `git diff --check` exit 0; каталог **436/406/411/90/88/19**
> (Δ Батчей A/B = 0); SQLite **v10**. **Статус: 0 Critical / 0 High / 0 Medium → к Батчу C
> (F3 бюджеты-UI + сид настроек чатов) можно** (открыто 3 Low: S10.18-29, S10.19-7/-8 + 4 Info; риски 10.18 в основном
> закрыты фикс-проходом). Отчёт: `plans/reports/round10.19_scanner_audit.md` (§7 — Батч B).
>
> **ФИНАЛЬНЫЙ baseline эпика 10.19 (БАТЧИ A–E, 16.09.2026, после UPD4):** HEAD `fd6acc7` + рабочее дерево
> (F1 betterstack-ingest-bearer-contract, F8 graphrag-memorize-robustness, F2 direct-chat-budget-unlimited,
> F3 budget-settings-section, F4 direct-context-limit-expansion, F5 status-section-ui-merge,
> F6 media-files-avatars-sync, F7 memory-retention-health).
> pytest **6323 passed / 0 failed**; JS-гейты OK (`node --check`, `JS-UNIT-OK`, `VUE-MOUNT-OK`);
> `git diff --check` exit 0; каталог **437/407/412/92/90/20** (Δ Батча E = 0); **SQLite v11**
> (F7: `UNIQUE(chat_id, import_key)` + `import_checkpoints(path, chat_id)`; v10 — `edges.fact_id`).
> **Статус: 0 Critical / 0 High / 0 Medium открыто → эпик готов к Merge/архивации + двухэтапному деплою.**
> Открыто: 2 Low (S10.19-15 — двойной `key_status` в «Сводке»; S10.19-23 — fsync каталога архива) + S10.18-29 (Low)
> + 16 Info; обязательные @DevOps-гейты (dry-run → бэкап → SQL-чеклист → purge) — отчёт §10.5.
> Отчёт: `plans/reports/round10.19_scanner_audit.md` (§10 — Батч E + итог эпика).

## Round 10.23 — F1 target-message-marking / F2 factcheck-deep-context / F3 verbalizer-response-modes / F4 dynamic-anticliche-cache / F5 image-generation-tool / F6 summary-cover-rich-article / F7 token-analytics-dashboard / F8 ui-verbilizer-tabs / F9 help-ui-v5 (19.09.2026, HEAD `2e056e7`, 22 коммита) — карта связностей

> **Baseline скана Step 6 @Scanner:** pytest **7418 passed / 0 failed** (95.99 s); `node --check web/app.js` OK;
> `git diff 731a845..HEAD` = 118 файлов, +13192/−523. Секретов в диффе/трекаемых файлах нет. Каталог **457**
> (было 439: F2 +2 / F5 +5 / F6 +1 / F8 +10); Settings-поля **416**; `GROUPS 96`; `_TAB_BY_GROUP 94`.
> SQLite **v12 (не тронут)**, PG +3 таблицы. **Статус: 0 Critical / 0 High; 2 Medium (не блокеры) / 4 Low / 4 Info.**
> Отчёт: `plans/reports/round1023_scanner_audit.md`.

- **Кросс-фичевые общие файлы (ступени вливания):**
  - `services/system2_handoff.py` — **F3 → F6 → F7**: `RESPONSE_MODES`/`normalize_response_mode` (fail-safe `serious`),
    `parse_summary_handoff` (`{response_mode, digest, cover_prompt}`) + back-compat `validate_summary_digest`,
    `normalize_cover_prompt` (≤300, по границе слова); `response_mode` добавлен в `parse_factcheck_analysis`/
    `parse_direct_synthesis`.
  - `services/prompt_style_blocks.py` — **F3/F8**: `TYPOGRAPHY_BLOCK`, `MODE_{CASUAL,SERIOUS,DEEP_RESEARCH}_BLOCK`,
    `FORMAT_{PLAIN,PLAIN_TEXT,RICH}_BLOCK`, `compose_verbalizer_system(base, mode, channel, html_safe=)`,
    `channel_enabled_rules` override буллитов для `deep_research`; `resolve_prompt(pg_key, code_default)`
    (пустота/whitespace не обнуляет system-промпт, hot-get).
  - `services/param_catalog.py` — **F2 → F5 → F8**: `+2` (`factcheck_context_before/after`, legacy hidden),
    `+5` image-группа (`models_images`/`keys_images`/`flags_module_images`), `+1` `prompts.summary_cover_style`,
    `+10` Stage-1/2 + режимы (`prompts_verbilizer`); поле `ParamSpec.stage` (`synthesizer|verbalizer|mode`);
    phantom `content.dynamic_cliche_list` НЕ регистрируется (F4 хранит клише в PG-таблице).
  - `services/prompt_migrations.py` — **F1 → F2 → F3 → F4(no-op) → F6**: `PREV_SUMMARY_EDITOR_R1023[_F3/_F6]`,
    `PREV_FACTCHECK_ANALYST_R1023[_F2/_F3]`, PREV-слепки chat/direct verbalizer; `ROLLBACK_MIGRATIONS` снимает
    ровно последнюю ступень.
  - `web/app.js` + `web/index.html` — **F5 → F7 → F8 → F9**: блок «Генерация изображений» (checkbox GET + dependsOn
    ключа), «Token Metrics» (Flow node + графики), вкладка «Промпты» (табы режимов, секции по `stage`, монитор
    анти-клише через `/api/anticliche`), guide backup-UI. `tma-menu-freeze` не нарушен.
- **F1 `target-message-marking` (ADR-1023-1):** новый `services/target_marking.py` (`TARGET_MARKER[_CORE]`,
  `TARGET_INSTRUCTION_BLOCK`, `normalize_trigger_id`, `is_target_row`/`is_target_item_id`, `append_marker`);
  `summary_xml.XmlGroundingBuilder.build(..., trigger_message_id)` (маркер до `_escape`), `canonical_context.format_context_item(is_target=)`
  (дефолт False — прочие вызывающие не затронуты), `chat_context.format_chat_context(trigger_message_id=)`;
  правило в `CHAT_SYSTEM_PROMPT`/`SUMMARY_EDITOR_SYSTEM_PROMPT`/`FACTCHECK_ANALYST_SYSTEM_PROMPT`;
  анти-эхо — `outgoing_guard._TARGET_MARKER_RE`. Маркер ровно один раз (только `<Global_Context>` в direct; команда
  `/summary` в историю не пишется — ограничение зафиксировано).
- **F2 `factcheck-deep-context` (ADR-1023-2):** `database.get_messages_around` (anchor + before/after, ASC,
  fail-open → `get_recent_messages`); `handlers/factcheck._fetch_chat_context`/`_clamp_window`; `chat_context`
  keep-end бюджет с приоритетом якоря/`after`/`<reply_chains>` (обёртка учитывается, ≤ `max_chars`); новый
  `services/thread_chain.py` (общий граф реплаев, вынесен из direct); `render_reply_chains` (пометка «не доказательства»);
  `_trusted_text` БЕЗ chat_context (таймстампы не становятся grounding-якорями); `WEB_SEARCH_INSTRUCTION_BLOCK`;
  legacy `limits.factcheck_context_messages` → одноразовая DML-миграция в `before`.
- **F3 `verbalizer-response-modes` (ADR-1023-3):** роутер строго в Stage-1 JSON; `compose_verbalizer_system`
  + канальные блоки; `channel_enabled_rules` (`plain_no_tables` на plain, легальные таблицы на rich);
  `detect_plain_tables` (контекстная эвристика: HTML/ASCII/separator/≥2 pipe-строк) в `negative_constraints`;
  direct `deep_research` → safe-HTML «Летописца» (`_send_direct_answer(deep_research=True)`); kill-switch
  `SMART_VERBALIZER_MODES_ENABLED`.
- **F4 `dynamic-anticliche-cache` (ADR-1023-4):** PG `anticliche_cache` (singleton id=1, JSONB) — DDL/сид в
  `pg_db`; `services/anticliche_cache.py` (memoized `get_rules`, `fetch/write/apply_manual`, `re.escape`-компиляция
  фраз, `dyn_<sha1[:8]>`, R17-статусы); `services/anticliche_worker.py` (недельный `AntiClicheWorker`,
  бюджет `llm_calls`, guard пустого/эхо-результата — кэш не затирается); фикс S10.22-4b (lookbehind запятой,
  bare «языковая модель» не после «как»); API `web/api/anticliche.py` (GET/PUT/POST refresh, global admin).
- **F5 `image-generation-tool` (ADR-1023-5):** новый `services/image_generation.py` (`generate`/`generate_image`/
  `generate_and_send`/`maybe_handle_keyword`, POST `response_format=url` + b64-fallback, GET строго анонимный,
  ≤1 ретрай на 429/503, `IMAGE_MAX_BYTES`); tool `generate_image` 9-м в `tool_schemas` (после канонических 8;
  гейт сомкнут env∧каталог, анти-двойная генерация с пре-гейтом); `worker_budget.METRIC_IMAGE_CALLS`;
  egress `telegram_send.send_photo` (байты, без keyed-URL); `SecretMaskFilter` на console + httpx→WARNING.
- **F6 `summary-cover-rich-article` (ADR-1023-6):** `cover_prompt` в Stage-1 JSON; `SummaryDraft`;
  `_deliver_rich` (обложка F5 → `send_rich_message`) с тихим фолбэком и даунгрейдом rich→plain по содержимому
  (`downgrade_rich_to_plain`/`looks_rich`); `telegram_send.build_cover_article_html`/`build_cover_media`/
  `send_rich_message` (exactly-one-of html/markdown, sanitize ДО escape, media `tg://photo`); `_rich_media_supported()`.
- **F7 `token-analytics-dashboard` (ADR-1023-7, AMEND: DDL в PG):** `services/usage_events.py` (fail-open запись,
  ретенция opportunistic), `services/llm_pricing.py` (TTL-кэш цен, `compute_cost` fail-safe), DDL
  `llm_usage_events`/`llm_model_prices` + индексы + сид цен; `correlation_id` протянут Stage-1/tool/Stage-2
  (`llm_client.generate[_chat]`, `tool_loop`, все три оркестратора); API `web/api/analytics.py` (latest/summary/prices,
  global admin); UI «Token Metrics».
- **F8 `ui-verbilizer-tabs` (ADR-1023-8):** PG-редактируемые Stage-1/2 промпты + 3 режима + default-mode;
  `resolve_prompt` hot-get; UI-табы/секции по `stage`; монитор анти-клише; `stage` в `/api/config`.
- **F9 `help-ui-v5` (ADR-1023-9):** `INFO_CANON_VERSION 4→5` (info_text.md + секция «11. Генерация изображений»),
  `GUIDE_CANON_VERSION=2` + `guide_version_for` по содержимому, `KNOWN_GUIDE_SNAPSHOTS`; `InfoService.get_guide_backup`/
  `reset_guide`; маршруты `GET /api/info/guide/backup` + `POST /api/info/guide/reset` (RBAC `edit_info`).
- **Кросс-фичевые зависимости/риски (из аудита):** M1 — телеметрия изображений (пре-гейт F5 и обложка F6)
  не несёт родительский `correlation_id` → `usage/latest` (F7) отдаёт одиночную ноду image вместо дерева;
  M2 — `response_mode` (F3) попадает в Stage-2 JSON direct/factcheck (spec §3.1 требует обратного).
- **Инварианты целы:** physical-two-call (роутер в Stage-1), validator-loop без regex-реза, egress-реестр,
  imported-history/manual-overrides immutable, R16/R17/R18, `parse_mode=None`, порядок роутеров `bot.py`,
  RBAC новых эндпоинтов, идемпотентные PG-DDL, SQLite v12.

## Round 10.22 (UPD3) — F1 rebuild confirmed-cleanup / F2 KV-объект / F3–F5 System-2 two-call / F6 egress-guard / F7 справка v4 / F8 async rebuild досье (19.09.2026) — карта связностей

- **F1 `urgent-rebuild-dossiers-target-chat` (ADR-1022-1):** `services/memory_rebuild.py` — новый примитив
  `cleanup_confirmed_dossier_facts` (владелец F1; переиспользует F8): выборка ровно `kind='fact' AND
  status='confirmed' AND target_user` непустой (+`target_user=:name` для F8) keyset-пагинацией `id > after_id`;
  защита опор живых beliefs/парадигм `_belief_source_set` (обход всех `kind='belief'` keyset'ом, `source_ids` +
  `belief_meta.evidence`); порядок fail-closed `снимок → JSONL-архив (`memory_generated_confirmed_*.jsonl`,
  fsync) → сверка candidates==archived → guard-DELETE (`delete_generated_facts`: FTS→vec→`graph_facts`)`.
  `rebuild_dossiers` теперь: мемы/портреты → confirmed-cleanup → `pipeline(effective_window)`;
  `_effective_window = max(window_hours, ceil(age_hours)+24)` (R1b); инвариант `reset>0 & rebuilt==0 → rebuild_empty`
  + exit 1 (`manage._memory_exit_code`). CLI `manage.py memory rebuild-dossiers --target-chat` (shortcut =
  `--chat <target> --allow-target-chat`, `--all` цель исключает), окно по умолчанию 4320ч, кросс-процессный
  per-chat file-lock `dossier_rebuild_jobs.acquire_chat_lock` (общий с F8). `_guarded_delete` — bounded-retry на `locked`.
  Инварианты сохранены: `RAW_HISTORY_TABLES`/`assert_derived_table`/`_guarded_delete` не тронуты, overrides/beliefs/
  nodes/edges не мутируются. Принят R7 (удаление валидных confirmed компенсировано бэкап+JSONL; confirmed пайплайном не воссоздаются).
- **F2 `urgent-summary-aliases-ui` (R16):** `web/api/routes.py::_ensure_keyvalue_object` — точечно для `widget='keyvalue'`
  (`not secret`): строка-JSON распаковывается до 2 уровней → объект (иначе `{}` + WARNING); `web/app.js` KV-editor `sync`
  зеркалит распаковку. Другие `json`-виджеты (textarea) не затронуты; cache-bust `?v=__APP_VERSION__` без изменений.
- **F3/F4/F5 System-2 two-call (ADR-1022-3/4/5):** новый `services/system2_handoff.py` — общий контракт изоляции:
  `parse_json_object` (reasoning-стены/фенсы/raw_decode, усечение→None), `parse_factcheck_analysis`,
  `validate_summary_digest`, `parse_direct_synthesis`, `contains_system_ids` (fact/msg/`[ММ.ГГГГ |`), `redact_secrets` (R17).
  Цепочки: factcheck `FactCheckService.check_claim` → `_check_claim_two_call` (Аналитик JSON → Вербализатор; Stage-2
  видит только валидированный JSON); summary `SummaryGenerator._generate_two_call` (Редактор → Рассказчик);
  direct `DirectChatService._synthesize_direct_answer` (Синтезатор тулов → Вербализатор, только при непустом
  `raw.tool_trace`, не degraded, НЕ `lore_compiled`). Верификация ответа — `services/negative_constraints.verbalize_validated`
  (детектор клише → ≤2 полных регенерации, `CLICHE_RETRY_SYSTEM_PROMPT`); любой сбой/невалидный JSON → fallback на
  одиночный путь 10.21 (ответ не теряется). Kill-switch `SYSTEM2_{FACTCHECK,SUMMARY,DIRECT,VALIDATOR_LOOP}_ENABLED` (env-only).
- **F6 `telegram-send-regex-guard` (ADR-1022-6):** новый `services/outgoing_guard.py::sanitize_outgoing` — единая чистая
  функция egress (reasoning-теги + `\bfact:\d+\b`/`\bmsg:\d+\b`, no-op без паттернов, fail-closed `""`).
  `services/telegram_send.py` — обёртки `send_text`/`edit_text_safe` (chokepoint) + реестры `SEND_POINTS`/`SEND_ALLOWLIST`;
  переведены `smartmodule_utils._send_once` (все LLM-контуры: direct/factcheck/search/youtube/web/checkup) и
  `summary_generator` (_send_streaming/_send_chunked/_send_one_chunk/_send_ux). `services/negative_constraints.py` —
  детектор клише (коды правил, R17) + validator-loop; клише кодом НЕ вырезаются (вето владельца).
  `prompt_style_blocks`: `ANTI_BOT_BLOCK` п.7 + `PREV_ANTI_BOT_BLOCK`/`PREV_STYLE_BLOCKS_SUFFIX`; `PREV_*_R1022` в `PROMPT_MIGRATIONS`.
- **F7 `help-ui-system2` (ADR-1022-7):** `services/info_service.py` канон **v4** (`INFO_CANON_VERSION 3→4`), прежний v3 →
  `PREV_R1022_DEFAULT_INFO_TEXT` в `KNOWN_INFO_SNAPSHOTS`; только `<h1>/<h2>` + команды в `<blockquote>` (h3+ нет),
  байт-тест `info_text.md`. `config_cache._migrate_info_how_it_works_v1015` мигрирует v3→v4 идемпотентно; DOMPurify
  (default) пропускает h1/h2/blockquote; `.info-html`-стили в `web/static/app.css`.
- **F8 `dossier-rebuild-async-ui` (ADR-1022-8):** новый `services/dossier_rebuild_jobs.py` — `DossierRebuildJobStore`
  (JSON-стор `backups/dossier_jobs/dossier_rebuild_jobs.json`, `tmp`→`os.replace`+fsync, один писатель `asyncio.Lock`,
  retention 50/7д, активные не вытесняются, рестарт → `interrupted`), per-chat file-lock `acquire_chat_lock`
  (O_CREAT|O_EXCL + takeover-маркер + TTL), точечный снапшот производных юзера (`_USER_DERIVED_SQL`, JSONL+fsync) и
  `restore_user_snapshot`/`archive_user_derived`, раннер `run_dossier_rebuild` (snapshot → F1 confirmed-cleanup →
  `LoreWorker.rebuild_dossier_for_user` чанками с `progress_cb`/`cancel_cb` → done; при отмене `perform_rollback`
  идемпотентно). `LoreWorker.rebuild_dossier_for_user`/`_classify_chunked_user`/`_extract_chunk`/`_write_target_memes`
  — user-scoped (пишет только `target`: `dossier_portrait`+`chat_meme`); `count_window_messages`. API
  `web/api/chat_lore.py`: `POST .../dossier/{user_id}/rebuild` (202; 409 already_running/chat_locked), `GET .../rebuild/latest`
  (204), `GET .../rebuild/{job_id}`, `POST .../rebuild/{job_id}/cancel` (terminal retryable для `failed`+`rollback_failed`/
  частичной пересборки). RBAC `_require_chat`; job-view R17 (только числа/коды/basename); kill-switch `DOSSIER_REBUILD_UI_ENABLED`.
  UI `web/app.js` (`startDossierRebuild`/polling 2с/`resumeDossierRebuild`/`cancelDossierRebuild`) + карточка в `web/index.html`.
- **Инварианты:** порядок роутеров `bot.py` не менялся; каталог **Δ=0** (новые рубильники — env-only ClassVar);
  SQLite **v12**; `git diff --check` clean; секретов нет.
- **Статус скана (итерация 2, после пост-скан фиксов): 0 Critical / 0 High / 0 Medium / 0 Low / 0 Info открыто**
  (новая Info S10.22-4b — не блокер). Пост-скан фиксы, вошедшие в связи: F1 `_belief_source_set` → fail-closed
  (ошибка чтения beliefs пробрасывается, чат `read_error` пропускается, опоры не удаляются, `memory_rebuild.py:787-847`);
  F8 раннер `cleaned>0 & rebuilt==0` → `failed`/`rebuild_empty` + достижимый ручной откат (`dossier_rebuild_jobs.py:720-732`,
  `_rebuild_rollback_retryable` учитывает `cleaned>0`); `interrupted` исключён из `_ACTIVE_STATUSES` и prune-ится
  (`:41,295-312,371-379`) → новый старт разрешён; `restore_user_snapshot` фильтрует колонки по `PRAGMA table_info` (`:526-541`);
  F8 UI-флаг доступности: `latest` 404 при kill-switch → `dossierRebuildEnabled=false` (`app.js:2893-2909`, `index.html:2733`);
  F6 `as_ai` сужен до 1-го лица (negative lookbehind, `negative_constraints.py:50-59`); R17-лог summary без сырого текста
  (`summary_generator.py:290-296`). Валидатор: целевой pytest **187+339+70+88 passed**; JS-гейты `JS-UNIT-OK`/
  `DOSSIER-REBUILD-UNIT-OK`/help OK; `git diff --check` clean; v12; каталог 439/92/20 (Δ=0); справка байт-в-байт.
  Отчёт: `plans/reports/round1022_scanner_audit.md` (§«Re-audit после пост-скан фиксов»).

## Round 10.21 — F1 multilayer / F2 grounding+CoVe / F3 де-роботизация / F4 консолидация / F5 rebuild-sanitation / F6 UI-аудит (18.09.2026) — карта связностей

- **F1 `multilayer-memory-extraction` (ADR-1021-1):** `LoreWorker._classify_dossier` → ветвление по env-only
  `settings.MULTILAYER_EXTRACTION_ENABLED` (default True, ClassVar). Слой А (`LAYER_A_SYSTEM_PROMPT` +
  `parse_layer_a` + `filter_layer_a_candidates`) → Слой Б (`LAYER_B_SYSTEM_PROMPT` + `build_layer_b_user` +
  `parse_layer_b` + `validate_layer_b` с анти-цитатным `find_verbatim_quote`). Бюджет: прогноз `_budget_ok(calls=2)`,
  фактический retry/fallback добирается `_budget_extra_calls` (fail-open). Fallback: A невалиден → legacy 10.20;
  B упал → memes Слоя А без портрета. Персистенция: `DatabaseService.upsert_generated_dossier`/`get_generated_dossier`
  — `graph_facts.status='dossier_portrait'` (нулевой DDL), рендер `render_generated_portrait` (≤600). Изоляция от
  RAG/KNN/`get_persona_card`/`get_persona_names`/`get_dream_candidates`/`list_chat_memes` — через `status!='confirmed'`
  (FTS-ветка фильтрует статус, KNN — `by_id`), vec-строки портрет не получает. Приоритет `persona_dossier_overrides`
  в `web/api/chat_lore.py` (`portrait_source='manual'`) и `direct_chat_service._format_generated_portrait_block`.
- **F2 `factchecker-grounding-cove` (ADR-1021-2):** новый `services/grounding_validator.py` — `collect_allowed_anchors`
  (fact:ID/`ММ.ГГГГ`/ISO только из ДОВЕРЕННЫХ источников: RAG/`search_results`/`chat_context`/`tool_context`; `<claim>`/
  `<user_hint>` исключены — S10.21-5) + `strip_phantom_tags` (bracket с `fact:` режется целиком при несовпадении
  id/даты; дата-только метка без `fact:ID` тоже проверяется по контексту — S10.21-4; голые `fact:ID` — по токену;
  fail-open, логи counts). `FactCheckService.check_claim`:
  `tool_context` читается с `ToolLoopResult` ДО `cleanup_llm_text`; CoVe-блок `<reasoning>` снимается штатным
  `strip_reasoning_tags`. `ToolLoopResult.tool_context` — аддитивный атрибут (склейка выводов тулов, R17-safe).
- **F3 `de-robotization-negative-constraints` (ADR-1021-3):** новый `services/prompt_style_blocks.py`
  (`ANTI_BOT_BLOCK`/`ASYMMETRY_BLOCK`/`STYLE_BLOCKS_SUFFIX`, новый R46-4 без «уже проверял» + legacy-версия).
  8 канонов (`chat/checkup/search/summary/web/youtube/youtube_video/factcheck`) собираются как `base + suffix`;
  добавлены `PREV_*_R1021` в `PROMPT_MIGRATIONS` и обратный `ROLLBACK_MIGRATIONS` (`rollback_prompt_canons`,
  ручной runbook). `docs/canon/**` синхронны.
- **F4 `paradigm-thresholds-consolidation` (ADR-1021-4):** `memory_maintenance.consolidate` — CLI-only,
  `DreamWorker._write_paradigm` с дедупом `_deep_dedup_key`/`_paradigm_dedup_keys`, fail-closed без `db_path`
  (`allow_no_backup=False`), авто-бэкап+JSONL; `collect_paradigm_audit` (READ-ONLY по коду) + `memory_health`
  счётчики. `config_migrations.migrate_deep_sleep_thresholds` (20→6) — env-рубильник default OFF, вызов в `bot.py`
  после `migrate_context_limit_defaults`. **Закрыто Medium S10.21-1:** `consolidate` применяет per-chat кап
  `limits.deep_sleep_max_paradigms_per_run` (иначе `DEEP_SLEEP_MAX_PARADIGMS`) и ограничивает выборку `limits.deep_sleep_top_k`;
  **Low S10.21-8 (открыто):** парадигмы CLI без vec-эмбеддинга (`DreamWorker(memory=None)`).
- **F5 `memory-rebuild-sanitation` (ADR-1021-5):** новый `services/memory_rebuild.py` — единственный путь DELETE
  `_guarded_delete` + `assert_derived_table` (allowlist производных; `RAW_HISTORY_TABLES` блокируются всегда, в т.ч.
  через `extra`). `_safety_backup` (Backup API + fsync) → `_archive_generated_rows` (JSONL) → сверка
  `candidates==archived` → DELETE. `rebuild_dossiers` (chat_meme+dossier_portrait reset + pipeline F1), `sanitize_beliefs`
  (orphan/invalid_belief/hallucination), `_reset_overrides` только под `--include-overrides`. CLI `manage.py memory`
  (`_memory_scope`: `--all` без целевого, `--chat <target>` требует `--allow-target-chat`; дефолт apply, `--dry-run` —
  опция). Сырая история только READ. **Исправлено (S10.21-2/-3/-6):** `_chat_roster` = union `nodes` + `dossier_portrait` +
  `persona_dossier_overrides` (AliasResolver) с `independent`-счётчиком и гардом `roster_incomplete` (мемы вне неполного
  ростера не удаляются), `roster_size` в отчёте; `belief_sources` (`source_ids`+`evidence`) исключаются из orphan
  (reason `belief_source`); `memory audit` через `DatabaseService.initialize_readonly` (`mode=ro`, без DDL/WAL/создания
  файла). Осталось: Info S10.21-11/13 + Low N10.21-2 (бинарный гард ростера).
- **F6 `ui-audit-puppeteer` (ADR-1021-6):** Puppeteer MCP честно недоступен → fallback Playwright+Chromium
  (`tools/ui_audit_round1021.py`, фейковый stub, `sk_FAKE_*`); отчёт `UI_AUDIT_REPORT.md` + `tools/_ui_audit_raw.json`
  + `tools/_ui_audit_shots/`. Фиксы: F6-01 (`_syntheticGroup` из `computed` → `methods`), F6-02/L-4
  (`positionScopePanel` + `scopePanelStyle`). Регресс-зонды `tests/js/round1021_ui_audit_test.js`;
  `web/index.html` — блоки авто-портрета/паттернов/тем досье.
- **Инварианты:** порядок роутеров `bot.py` не тронут (только 2 вызова миграций), каталог Δ=0, SQLite v12, R16
  (аддитивные поля API), R17 (логи counts/коды), секретов нет; `backups/` gitignored (JSONL/бэкапы F5 не в репо).
  **Закрыто Low S10.21-9:** `tools/_ui_audit_shots/` (≈9.2 МБ) и `_ui_audit_raw.json` добавлены в `.gitignore`
  (`git check-ignore -v` подтверждает); в репо остаются только `tools/ui_audit_round1021.py` и `UI_AUDIT_REPORT.md`.

## Round 10.19 — БАТЧ E: F6 `media-files-avatars-sync` + F7 `memory-retention-health` (16.09.2026, после UPD4) — карта связностей

- **Retention импорта — деструктивный контур (F7/ADR-1019-6 D1/D1a/D2; ADR-1019-8 D5):**
  `services/retention_policy.py` — fail-**closed**: `source='error'` (chat-слой не читается) → purge запрещён;
  `enforce`-чат из данных сида → `seed_enforced` (hard-deny); **нечитаемый сид** → `seed_unavailable` → запрет
  (D-2.4); `<0`/мусор → глобальный дефолт (без рекурсии — D-2.1). **Единственный call-site purge** —
  `services/memory_maintenance.run_import_retention`: отмена целого прогона при любом `source='error'` (D-1);
  `chat_cutoffs` строится только из разрешённых чатов (структурный guard «0=вечно»); **обязательный архив**
  (`_archive_imported_history` → JSONL в `MEMORY_BACKUP_DIR`, `flush+os.fsync` в `to_thread`) ДО DELETE; сбой
  архивации → строки не удаляются; `chat_max_ids` (`id <= max_id`) + сверка `candidates != archived` →
  `archive_mismatch` (purge отменяется). `DatabaseService.purge_imported_history` — keyword-only `chat_cutoffs`
  (без дефолта), батчи, `_delete_fts_rows`, FTS-`DatabaseError` не блокирует основной DELETE. **Тройной env-гейт
  авто-крона** (`auto_purge_dry_run`): `IMPORT_RETENTION_ENABLED` (OFF) × `IMPORT_RETENTION_DRY_RUN` (ON) ×
  `IMPORT_RETENTION_BACKUP_CONFIRMED` (OFF); CLI `manage.py retention` — dry-run по умолчанию (`--apply` нужен),
  HTTP-триггера purge нет.
- **SQLite v11 (ADR-1019-6 D1b/D7; UPD3 п.2):** `DROP` глобального `idx_smart_messages_import_key` + `CREATE
  idx_smart_messages_chat_import_key UNIQUE(chat_id, import_key) WHERE import_key IS NOT NULL`; `import_checkpoints`
  rebuild `(path, chat_id)` (legacy → `chat_id=0`) в **одной транзакции**; `PRAGMA user_version=11` всегда;
  `_migrate_history_import_v7` больше не пересоздаёт глобальный UNIQUE после v11. **Проба @Scanner:** v=11, индексы/
  колонки корректны, legacy-строка сохранена, re-init идемпотентен, **один `import_key` в двух чатах → 2 строки**
  (кросс-чат дефект закрыт); FTS/vec не пересоздаются; `tools/history_import/checkpoints.py` — `get/set/done` c
  `chat_id` (default 0).
- **Универсальность (UPD4 п.1):** `services/vip_seed.py` → **`services/chat_settings_seed.py`**,
  `config/vip_chats.json` → **`config/chat_settings_seed.json`**, CLI `manage.py apply-chat-overrides`,
  мета-ключ `chat_settings_seed_version`, источник `seed_enforced`; код-путь generic, id — только в данных/тестах
  (+legacy `chat_lore`); «VIP» в коде нет; stale `__pycache__/vip_seed*.pyc` — untracked (gitignored).
- **F6 `media-files-avatars-sync` (ADR-1019-5):** `services/media_download.py` — `local_file_path` (traversal-guard
  `is_relative_to(root)`), общий `_read_local_source` (3 ретрая, R17-логи без `<bot_id>:<token>`/`exc_info`),
  `read_local_file_bytes` (чтение в `to_thread`); `fetch_media_to_tmp`/аватары — локальный путь первым, прежний
  `bot.download`/`download_file` как fallback; `services/media_integrity.py` — honest-контракт
  (`reliable:false`, `basis:'text_scan'`), bounded обход диска в `to_thread` (20k записей), R17-хвосты;
  `GET /api/status/media-health` (аддитивный, TTL 120с на chat_id, fail-open `{available:false}`), UI-блок по спеке
  опционален.
- **F7 health-метрики:** `GET /api/memory/health` — аддитивно `facts_overdue`, `facts_unconfirmed`,
  `smart_messages_total`, `deep_sleep_runs_total`, `storage{db_size_bytes,db_size_mb,disk_free_bytes}`; тяжёлые
  COUNT'ы под TTL 60с, `storage` — только `stat/disk_usage` (fail-open нули); UI «Здоровье памяти» отрисовывает
  метрики.
- **Открытые риски Батча E:** Low S10.19-23 (fsync каталога архива; файл синхронизируется, имя — нет);
  Info S10.19-22 (финальный purge без try/except при docstring «fail-open» — вызывающие защищены, HTTP-пути нет),
  S10.19-24 (архивы `imported_history_*.jsonl` не ротируются), S10.19-25 (запись архива в event loop),
  S10.19-26 (эвристические `orphan_files` при `reliable:false`), S10.19-27 (флейки-риск теста с локальным
  HTTP-сервером, Batch A), S10.19-21 (ARCHITECTURE: §41 добавлен для E; F4/F5-параграфы — за @Memory).
- Scan-отчёт (Батч E, §10): `plans/reports/round10.19_scanner_audit.md` — 0 Critical / 0 High / 0 Medium,
  1 Low (S10.19-23), 6 Info. **Итог эпика §10.4, @DevOps-гейты §10.5** (dry-run → бэкап → SQL-чеклист 8 overrides →
  v11 → live-проверка → purge по решению владельца). Валидатор: pytest **6323/0**, JS-гейты OK,
  `git diff --check` exit 0. **Вердикт: эпик готов к Merge/архивации/деплою.**


## Round 10.19 — БАТЧ D: F4 `direct-context-limit-expansion` + F5 `status-section-ui-merge` (16.09.2026, HEAD fd6acc7 + рабочее дерево) — карта связностей

- **Sentinel контекста (F4/ADR-1019-4 D3/D4 + ADR-1019-8 D2/D3):** `services/token_counter.py` —
  `resolve_context_tokens(token_value, token_default)`: `<0` → `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`
  (env-only ClassVar, 32000 — **вне каталога**, Settings 407 не растёт), `0/None/мусор` → `token_default`
  (кламп `max(1, …)` — D-8, отрицательный env-дефолт не превращается в `safe_budget(-1)=1`), `>0` → cap;
  `resolve_chat_limit` применяет его ко **всем** токенным значениям; chars-fallback (`None` + `*_CHARS` в env)
  переведён в **debug** как «аварийный путь». Потребители: `direct_chat_service` `_build_global_context` (`:2087`),
  `_render_thread`/branch (`:2196`, `:2219`), `_apply_context_budget` (бюджет: `unlimited` → агрегатное усечение
  НЕ применяется + `record_context_usage(..., limit=None, unlimited=True)` — D-7), `_check_context_config_invariant`,
  `summary_generator:172`, `oversight` (через `context_state`), `status_service` (D-7 → `limit: null, unlimited`).
  **S10.19-13 (High) CLOSED** — проба @Scanner: `-1 → ('tokens', 32000), budget 27826`; `0/None → 5000/4347`
  (было «1 токен»).
- **Агрегатное распределение (D1/D-1):** `global`/`thread` исключены из первого прохода урезания (они уже
  ограничены своими потолками в сборщиках) и участвуют только при фактическом `total > budget`; инвариант
  сравнивает **реально применяемые** доли (`effective = max(1, budget − fixed)`) с `safe_budget(cap)` — один
  WARNING на чат (Info S10.19-18: флаг «предупреждён» ставится до проверки → поздняя рассинхронизация не видна).
- **Дефолты и миграция:** `CHAT_GLOBAL_CONTEXT_MAX_TOKENS` 1000 → **5000**, `CHAT_THREAD_MAX_TOKENS` 500 → **3000**,
  `CHAT_CONTEXT_BUDGET_TOKENS` 4000 → **16000** (env + code + каталог-тексты); `config_migrations.migrate_context_limit_defaults`
  (`CONTEXT_LIMIT_MIGRATIONS` 1000/500/4000 → новые; только == прежнему дефолту, кастом — WARNING, отсутствует/PG down
  — skip); порядок в `bot.py`: dream → global budgets → context limits → `apply_chat_settings_seed` (сид per-chat, миграции
  глобально — пересечений нет).
- **сид настроек чатов `−1` (S10.19-13):** теперь «безлимит до потолка безопасности», контекст целевой чата не срезается
  (`test_chat_settings_seed_keeps_context_unlimited`).
- **Сводка (S10.19-14 Medium CLOSED):** `oversight._limits_metric(contour='worker')` при **пустом** `day_rows`
  резолвит лимит `chat → global → default` (`WORKER_DEFAULT_LIMITS` 60/300 000) вместо `limit=0` → больше нет
  ложного «фон: Запрещено» у «тихих» чатов (настоящий `0` в строке дня по-прежнему `forbidden`).
- **F5 `status-section-ui-merge` (T-1819…T-1824):** `web/index.html` — «Сердцебиение + Бот + Сервер» в одной
  карточке `.status-block` / `.status-block__grid` (мобила столбик, ≥768px 1.4fr-1fr-1.2fr), строка «Режим · версия»
  удалена; `web/static/app.css` — медиа-правки `.graph-search` (mobile компакт, desktop `max-width: 460px`,
  `grid-column` переведён из inline в класс → inline-стилей стало **43** против 44 в HEAD); API «Статуса»
  аддитивен (`unlimited`), поиск/подсветка/EKG/reduced-motion/CSP/self-host не тронуты.
- Scan-отчёт (Батч D, §9): `plans/reports/round10.19_scanner_audit.md` — **0 Critical / 0 High / 0 Medium**,
  1 Low (S10.19-15, перенос), 7 Info (S10.19-9…-12, -16…-21). Валидатор: pytest **6262/0**, JS-гейты OK,
  `git diff --check` exit 0. **Вердикт: к финальным F6 + F7 — можно.**


## Round 10.19 — БАТЧ C: F3 `budget-settings-section` (15.09.2026, HEAD fd6acc7 + рабочее дерево) — карта связностей

- **сид настроек чатов (ADR-1019-8 D4):** `services/chat_settings_seed.py` + `config/chat_settings_seed.json` (v1: retention `0` = вечно,
  бюджеты ключа/фона `−1`, контекст `−1`). Идемпотентно (patch → запись только при изменении, повтор — `skipped`),
  merge сохраняет чужие overrides/meta, `enforce`-ключи применяются всегда, не-enforce — при отсутствии/росте
  version/`force`; чтение root идёт **напрямую из PG** (`chat_params.get_all_chat_params(chat_id, pg=…)` — D-2,
  чтобы CLI без кэша не затирал namespace); fail-open; id — только в данных (в `services/*` новых хардкодов нет).
  Применение: `bot.py:944-953` (migration → seed) + `manage.py apply-chat-overrides [--force]`.
- **Retention-политика (ADR-1019-8 D5):** `services/retention_policy.py::imported_history_purge_allowed` —
  fail-closed (`ошибка → allowed=False`), `0` = вечно → purge запрещён, `<0`/мусор → глобальный дефолт + WARNING.
  Прод-call-site отсутствует (контракт для F7 — DB-слой purge не реализован; честно записано в docstring/ADR).
- **Сводка (ADR-1019-8 D6):** `services/oversight.py` — аддитивный `limits` на карточку чата: `key_budget`
  (direct-контур через `chat_usage.key_status`; контур задаётся явно — D-1), `worker_budget` (строки
  `worker_budget.get_usage(scope=chat:<id>)`), `context` (3 ключа; `0/None` → эффективный дефолт 1000/500/16000 —
  D-6, `−1` → `unlimited`), `storage` («Импорт: Вечно»/«N дней»); каждый под-объект fail-open (500 не бывает);
  старый `budget` сохранён. **Открытое High S10.19-13:** семантика контекстного семейства не реализована в
  потребителях — `resolve_chat_limit` + `safe_budget` дают `budget=1` для `−1`/`0` → `<Global_Context>`/ветка/сводка
  срезаются до 1 токена (сид активирует `−1` в проде до F4). **Medium S10.19-14:** worker-контур без строк за сутки
  рапортует `limit=0/forbidden` → UI «фон: Запрещено» для тихих чатов.
- **Каталог-Δ (ADR-1019-3 D1/D2, UPD3 п.2-4):** новые группы `limits_chat_key` (29) и `limits_chat_context` (30),
  новый ключ `IMPORT_HISTORY_RETENTION_DAYS` (limits/limits_memory), новая вкладка `mod_budgets` («Бюджеты»,
  nav=modules) + маршрут `#/modules/budgets`; переносы: бюджеты ключа и контекст-лимиты из «Прямого чата»,
  `limits_worker` из «Диагностики» → «Бюджеты». Итог: **437/407/412/92/90/20** (осиротевших ключей/групп нет,
  одна группа — один владелец).
- **Миграция дефолтов (S10.19-8, Батч B → закрыто в C):** `config_migrations.migrate_global_budget_defaults`
  (только значение == прежнему дефолту 25/100 000/35/100 000 → 100/500 000/60/300 000; кастом не трогаем), вызов в
  `bot.py` до сида настроек чатов.
- **UI:** тумблер «Безлимит по чату» (только в контексте чата; ON → `−1` всем 7 ключам одним POST; OFF → явные
  глобальные значения — Info S10.19-16), `budgetRatio` (limit≤0/∞ → 0 %), `limitsPairText`, `storageLabel`,
  пояснение «фон vs интеллект» + сентинел-таблица; карточка модуля без master-тумблера (бейдж «лимиты»).
- Scan-отчёт (Батч C, §8): `plans/reports/round10.19_scanner_audit.md` — **0 Critical / 1 High / 1 Medium / 1 Low /
  7 Info**. Валидатор: pytest **6232/0**, JS-гейты OK, `git diff --check` exit 0.
  **Вердикт: к Батчу D — БЛОКИРОВАН (High S10.19-13).**


## Round 10.19 — БАТЧ B: F2 `direct-chat-budget-unlimited` (15.09.2026, HEAD fd6acc7 + рабочее дерево) — карта связностей

- **Единый sentinel-модуль (T-1854, ADR-1019-2 D1 + ADR-1019-8 D2):** новый `services/budget_limits.py` —
  `FORBIDDEN=0` / `UNLIMITED=-1` (любое <0) + `budget_state` (`0/мусор → forbidden`, `<0 → unlimited`, `>0 → cap`),
  `is_forbidden`/`is_unlimited`; **семьи не взаимозаменяемы**: контекст `0 → unset` (`context_state`), retention
  `0 → eternal`, негатив → `invalid` (`retention_state`, fallback + WARNING). `context_state`/`retention_state` —
  заготовки F4/F7 (потребителей пока нет — Info S10.19-10).
- **Direct-контур (`services/chat_usage.py`):** `_limit_with_source(key, chat_id, default)` → per-chat резолв
  `resolve_setting_with_source` (`chat overrides → hot.get → env`; ADR-1018-7 D1) — до F2 читался только глобальный
  слой; `_exceeds(req, tok, used_calls, used_tokens, estimate)` → `'forbidden'|'calls'|'tokens'|None`;
  `budget_snapshot(pg, chat_id, tokens_estimate)` — единый снимок (`exceeded/exceeded_metric/used/limit/unlimited/
  forbidden/source/source_calls/source_tokens/day`), инвариант «`exceeded=True` ⇒ валидная метрика» (иначе ERROR +
  fail-open), PG-down → `exceeded=False`, но `forbidden`/`source` вычислены (D-4); `budget_exceeded` — обёртка;
  `key_status` += аддитивные `unlimited/forbidden/source` на метрику (R16).
- **Фон (`services/worker_budget.py`, AMEND D6/D-1/D-2):** `_metric_limit` стал **async** + per-chat резолв
  (`_scope_chat_id` из `chat:<id>` → `resolve_setting_cached`, дефолты `WORKER_DAILY_LLM_*`); `consume` —
  `0 → False` (запрет), `<0 → True` (учёт расхода написан), `>0 → used <= limit`; `allowed_workers` — `0 → все False`,
  `<0 → все True`, `>0 → матрица деградации`; `global_degradation_allows`/`get_usage`/`get_day_summary` сохранены
  (лимиты в строках теперь per-chat, флагов sentinel в строках нет — Info S10.19-11).
- **LLM-клиент (`services/llm_client.py`, D-5):** ветка budget использует **один** `budget_snapshot` и для решения,
  и для `details` (без повторного чтения usage/TOCTOU); порядок резолва ключа (свой → глобал-бюджет →
  свой-фоллбэк → sandbox) сохранён.
- **Дефолты (ADR-1019-2 D5, UPD3):** direct `CHAT_GLOBAL_KEY_BUDGET_*` 25/100 000 → **100/500 000**; фон per-chat
  `WORKER_DAILY_LLM_*_PER_CHAT` 35/100 000 → **60/300 000** (глобальный фон 200/500 000 без изменений); тексты
  каталога синхронны; `.env.example` дополнен. **Открытое Low S10.19-8:** PG-ключи засеяны старыми значениями
  (`ON CONFLICT DO NOTHING`) → новые дефолты не применятся без шага данных (@DevOps/F3-сид или идемпотентная
  миграция в стиле `migrate_dream_thresholds`). **Low S10.19-7:** `README.md:365,368` всё ещё печатает старые
  100 000/25 и 35/100 000 (+ «ручные прогоны из бюджета не выпадают» — superseded 10.18).
- **Фиксы Батча A перенесены:** S10.19-1 — `summary_memory._log_empty_valid` (валидный `[]` → rate-limited INFO с
  `empty_total`, memorize + крон-ветка); S10.19-2 — README:1046 («401 ожидается, ждёт T-1779») и ARCHITECTURE:687
  переписаны inline; 10.18-остатки — ×2-фаза `graph_snapshot` ускорена (`_belief_name_participates`: token-set +
  padded, замер Scanner **238 → ~66 мс** на 15k рёбер — S10.18-30), merge-путь переносит F5-пенальти (S10.18-35),
  F6-спека синхронизирована (S10.18-36, архив).
- **Инварианты Батча B:** каталог Δ=0 (436/406/411/90/88/19), DDL нет (SQLite v10), R16 (аддитивные поля
  `key_status`/`details`), R17 (details без секретов), fail-open PG в обоих контурах, изоляция direct ↔ фон
  (разные пространства ключей), хардкода целевой чат-id в бизнес-логике нет (только legacy `chat_lore` + `scripts/backfill_*`).
- Scan-отчёт (Батч B, §7): `plans/reports/round10.19_scanner_audit.md` — **0 Critical / 0 High / 0 Medium**,
  2 Low (S10.19-7/-8), 4 Info (S10.19-9…-12). Валидатор: pytest **6195/0**, JS-гейты OK, `git diff --check` exit 0.
  **Вердикт: к Батчу C (F3 бюджеты-UI + сид настроек чатов) — можно.**

## Round 10.19 — БАТЧ A: F1 `betterstack-ingest-bearer-contract` + F8 `graphrag-memorize-robustness` (15.09.2026, HEAD fd6acc7 + рабочее дерево) — карта связностей

- **F1 ingest-контракт (T-1780, ADR-1019-1, AMEND ADR-1018-1 D2/D4/D6/D8):** `services/betterstack_handler.py` —
  `self._url = f"https://{host}"` (токена в path НЕТ) + заголовок `Authorization: Bearer {source_token}` в каждом
  POST; `_HINT_401` удалён → словарь `_STATUS_HINTS` (401/402/403/406, R17-safe); `token_equals_sentry_public_key`
  больше не WARNING (unified US: Source Token ≡ public key) — только DEBUG в `bot.py`; старт-маркер без `last4`.
  **Редиректы запрещены:** `_NoRedirectHandler(HTTPRedirectHandler)` + единственный `_OPENER = build_opener(...)`
  → 3xx не фоллоуится (токен не форвардится на чужой `Location`, POST-тело не теряется, ложного `sent` нет) →
  `_mark_failed("status=3xx")` без ретрая. Сеть — через `_urlopen(request, timeout)` (точка подмены в тестах).
  Ретраи: 5xx/транспорт — ≤1 (`retried`-guard); **все 4xx, включая 429, — без ретрая**; 2xx (202) — успех.
  Счётчики `sent/failed/dropped` без двойного учёта; `close()` = stop → join → flush остатка.
  **Открытое Low S10.19-2:** `plans/ARCHITECTURE.md:687` тело пункта всё ещё описывает path-token/`last4`/WARNING
  (исправлено только хвостовой AMEND-пометкой); `README.md:1046` заявляет «401 уходит» как факт до живого
  curl-матрикса T-1779. **Info S10.19-6:** probe `path`-режим отправляет реальный токен в URL (ручная диагностика
  @DevOps, маскированный вывод). `logtail`-импортов 0; `requirements.txt` чист.
- **F8 устойчивость memorize (T-1846…T-1849, ADR-1019-7, AMEND F-15 §4):** `services/summary_memory.py` —
  `parse_fact_list_ex(raw, warn=True) -> (facts, status)` со статусами `PARSE_OK/PARSE_EMPTY_VALID/PARSE_INVALID`
  (`parse_fact_list` — совместимая обёртка); `invalid` включает и D-08-подслучай (валидный список, все элементы
  отсеяны `_validate_fact`); `_memorize_facts_inner` перехватывает `LLMError` первичного `_extract_facts` **внутри**
  → fallback → ровно 1 retry `_FACT_RETRY_SYSTEM_PROMPT` (`_safe_retry`) → при неудаче единый rate-limited
  WARNING `_log_memorize_lost` (`status/reason/lost_total/raw=_mask_llm_raw`); `empty_valid` retry не вызывает.
  Модульные bounded-словари `_memorize_warn_state`/`_memorize_lost_totals` (`_MEMORIZE_WARN_STATE_MAX=512`,
  эвикция старейших) + сентинел `None` (первое событие всегда WARNING); крон-ветка `_extract_and_save_graph` —
  только различение `[]`/невалид в лог, без ретраев; канон `FACT_EXTRACT_PROMPT` и `PROMPT_MIGRATIONS` не тронуты.
  **Открытое Low S10.19-1:** валидный `[]` теперь только DEBUG (ранее INFO «0 facts») → в прод-journald кейс
  «модель вернула пустой список» (исходный симптом) снова невидим; **Info S10.19-3:** `reason=not_json` неточен
  для D-08-подслучая; **Info S10.19-5:** верхний `except LLMError` в `memorize_facts` практически недостижим.
- **Инварианты Батча A:** каталог Δ=0 (436/406/411/90/88/19), DDL нет (SQLite v10), R16/R17, порядок роутеров
  `bot.py` не тронут, F5-срез (`subject/object`) и F7-контуры не затронуты (конфликтов мержа нет).
- Scan-отчёт (Батч A): `plans/reports/round10.19_scanner_audit.md` — **0 Critical / 0 High / 0 Medium**,
  2 Low (S10.19-1/-2), 4 Info; валидатор pytest **6164/0**, JS-гейты OK, `git diff --check` exit 0.
  **Вердикт: к Батчу B (F2 бюджеты) — можно.**





## Round 10.18 (2026-09-15, БАТЧ 1/3: F7 + F1, HEAD 118a03c + рабочее дерево) — карта связностей

> **⏱ Итерация 2 (после фиксов @Builder, тот же baseline):** закрыты S10.18-1…-9 и -11. Ключевые изменения карты:
> `database.count_dream_log/sum_dream_log_tokens` += `chat_id` → бюджет Сна per-chat; `_deep_tick` резолвит
> `trigger`/`deep_sleep_hour` **по чату-кандидату** (общий `_deep_candidate_chat_ids`); `feature_gates.master_fallback`
> (+`MASTER_FALLBACK_KEYS={"dream": …}`) подключён в `allowed_features`/`web/api/gates.py`/`oversight.py`/
> `web/api/oversight.py`; `cognition_status` += аддитивный `dream.effective` (и `dream_in` считается по нему);
> `_run` гейтит decay глобальным `_dream_master_on()`; manual-каскад — по `only_chat` и `_MANUAL_DEEP_CASCADE_MAX=1`;
> BetterStack без хоста → **ERROR**; `ChatParamsNotify.stop()` вызывается из `on_shutdown`, `_pending`-задачи
> удерживаются и отменяются. **Новый Medium S10.18-15:** `master_fallback` берёт default `DEFAULT_BY_FEATURE["dream"]=False`
> вместо `settings.DREAM_ENABLED` → при env `DREAM_ENABLED=true` и отсутствии DB-ключа статус показывает OFF, а воркер ON
> (воспроизведено). Детали — `plans/reports/round10.18_scanner_audit.md` §7.

- **F7 `settings-worker-sync` (T-1759…T-1764, P0)** — единый read-path настроек воркеров/статус-API.
  Новый `services/worker_settings.py`: `resolve_setting`/`resolve_setting_with_source`/`resolve_setting_cached`/
  `setting_source`; приоритет `chat_profiles.chat_params.overrides[key]` (каст = `chat_params._resolve_from_root`:
  `normalize_value` + `_cast_type_ok` + `math.isfinite`) → `hot.get(key)` (`ConfigCache`, in-memory) → env-дефолт.
  Сентинел `_global_with_source` использует `hot.get(key, _SENTINEL)`; проверено, что `_cast_to_type`
  (`param_catalog.py:1966-2034`) пропускает `object()`-сентинел без изменений (все 5 типов) → `source='default'`
  корректен. `setting_source` — best-effort без I/O (читает `ChatParamsCache._items` / `ConfigCache`).
- **DreamWorker ↔ accessor:** `_key_for(chat_id, name, default)` = `memory.dream_<name>` (chat → global → default);
  per-chat применён в `_process_chat` (`enabled`, `cluster_overlap_tokens`, `repeat_threshold`,
  `importance_sum_threshold`, `max_clusters_per_run`, `_window_open_for`, `_budget_reason_for`, `_daily_limit_for`),
  `_candidates` (`initial_window_hours`), `_maybe_deep_after_sleep` (`flags.deep_sleep_enabled` + `trigger`),
  `_run_deep_once` (`flags.deep_sleep_enabled`). Тик-слой осознанно глобальный: `min_new_facts_per_chat`,
  `max_chats_per_run`, `quiet_check_minutes` (`_run`/`get_dream_candidate_chats`).
  Старые sync-helpers `_window_open`/`_daily_limit`/`_budget_reason` удалены (S10.18-16, итерация 3); `_key()`
  сохранён (тик-слой/совместимость).
- **Гейты (kill-switch vs master):** `feature_gates.gates_enabled(chat_id, feature, root=None, *, fallback=None)` —
  порядок chat-gate → `_explicit_flag_value` (первый ключ `FLAG_KEYS`, `flags.<feature>_enabled`) → `fallback`
  (per-chat master `memory.dream_enabled`) → `_global_flag_value` → False. Воркер передаёт `fallback=enabled`
  (`dream_worker.py:587`). **Открытая связка (Medium S10.18-3):** `web/api/gates.py:68`, `allowed_features`,
  `oversight.py:172` вызывают без `fallback` → при per-chat master ON / global OFF показывают OFF, хотя воркер
  работает; `cognition_status.dream.enabled` не учитывает kill-switch.
- **Реактивность (T-1761):** `DreamWorker.start()` регистрирует `dream_tick` + `deep_sleep_tick` **ВСЕГДА**
  (`replace_existing=True`, `max_instances=1`, `coalesce=True`); решение — внутри тика/чата; `tick_minutes` и jitter
  фиксируются на старте (`applies on restart`). Побочно: `_run` всегда вызывает `_maybe_decay`,
  гейт только `flags.belief_decay_enabled` (Medium S10.18-4); чат-кандидаты читаются DB каждый тик (R2 spec).
- **Manual-каскад (задел F2/ADR-1018-2 D2/D4):** `_maybe_deep_after_sleep(…, manual=True)` игнорирует
  `flags.deep_sleep_enabled`/`trigger`; `_run_deep_all(manual=True)` не делает `break` после первого успеха;
  `_run_deep_once(manual=True)` пропускает cooldown/суточный лимит (Medium S10.18-5, ограничитель `_deep_budget_ok`).
- **LISTEN `chat_params_updated` (T-1764):** новый `services/chat_params_notify.py::ChatParamsNotify` — **отдельное**
  `asyncpg.connect` (у `Pool.add_listener` нет; Critical R10.18-1 закрыт) + `_init_connection`; backoff 1→60 c с
  сбросом; `finally` закрывает conn; колбэк sync → `asyncio.create_task(_safe_invalidate)` →
  `chat_params.invalidate_chat_from_notify(payload)` (fail-open). Монтаж — `bot.py::_start_chat_params_listener`
  (`:863-872`), вызов в `main()` сразу после `set_chat_params_cache` (`:900`); снятие — cancel в финальном
  `finally` `main()` (`:1005-1010`). `stop()` класса не вызывается (Low S10.18-7).
- **Статус-API (T-1762):** `web/api/memory_agi.py` — `deep_sleep_status` + `cognition_status` принимают
  `chat_id: Query() = None`, резолвят рубильники через `resolve_setting_with_source`, аддитивно отдают
  `source` (`chat|global|default`; в `cognition_status` — `{"dream":…, "deep_sleep":…}`), R16-совместимо.
- **F1 `betterstack-us-region-401` (T-1703…T-1711, P0)** — хост обязателен: `BetterStackHandler.__init__(host)`
  (`host=""`/whitespace → `ValueError`), `DEFAULT_HOST=""`; `bot.py` создаёт хендлер только при
  `LOGTAIL_SOURCE_TOKEN and BETTERSTACK_HOST` (иначе WARNING-маркер, fail-safe; Medium S10.18-6 — логи в панель
  полностью исчезнут, пока @DevOps не добавит переменную). Диагностика: `extract_sentry_public_key`
  (regex userinfo DSN) + `token_equals_sentry_public_key` (`hmac.compare_digest`) → WARNING без блокировки старта;
  attached-маркер `host + token_len + last4 + from=LOGTAIL_SOURCE_TOKEN` (R17-safe); `_HINT_401` про регион/токен.
  `BETTERSTACK_SOURCE_TOKEN` НЕ читается; `logtail-python` удалён из `requirements.txt` + smoke переведён на
  `BetterStackHandler`; новый `scripts/betterstack_host_token_probe.py` (host×token матрикс, dry-run, маскирование)
  + `tests/test_betterstack_probe.py`. Каталог: `BETTERSTACK_HOST` в `_INFRA_ENV_ONLY` (category None, secret False).
- **Статус находок 10.18 (итерация 2):** **CLOSED** — S10.18-1 (per-chat учёт расходов Сна, `chat_id` в
  `count_dream_log`/`sum_dream_log_tokens`), S10.18-2 (`trigger`/`hour` per-chat в `_deep_tick`), S10.18-3
  (`master_fallback` во всех статус-поверхностях + `dream.effective`), S10.18-4 (decay за `_dream_master_on()`),
  S10.18-5 (manual-каскад: `only_chat` + кап 1), S10.18-6 (ERROR без хоста), S10.18-7 (`stop()` в `on_shutdown`),
  S10.18-8/-9 (доки/спека), S10.18-10 (изоляция reload в тесте — restore в `finally`), S10.18-11 (`_pending`-ссылки +
  отмена). **CLOSED (итерация 3, fix @Builder):** S10.18-15 (env-дефолт `master_fallback` =
  `settings.DREAM_ENABLED`), S10.18-16 (мёртвые sync-хелперы `_window_open`/`_daily_limit`/`_budget_reason`
  удалены), S10.18-17 (`_deep_tick` предгейт `_deep_fixed_possible()` + `ChatParamsCache.has_any_override`).
  **OPEN (Info):**
  S10.18-12 (`NostalgiaWorker` — остаточный РАЗРЫВ spec §2.3, backlog T-1764), S10.18-13 (pre-existing фрагмент
  SSH-пароля в `plans/archive/security-rotation-finalize-round1016/spec.md:35`, R10.18-12, файл отслеживаемый),
  S10.18-18…-20 (`?deep=1` без капа; `tokens_per_day` без фильтра `kind`; `previous` kill-switch = effective).
- **Инварианты 10.18 (целы):** R16 (аддитивность `source`/`effective`), R17 (нет секретов: `last4`-маска,
  маскирование probe), fail-open PG/кэш (бот жив), порядок роутеров `bot.py`, `media/`/`.env` не в скоупе,
  DDL нет, SQLite v9 (`database.py` менялся только `WHERE chat_id` — без DDL), промпт-каноны не тронуты,
  каталог 436/406/411/90/88/19.
- Scan-отчёт: `plans/reports/round10.18_scanner_audit.md` (итерация 1: 0 Critical / **1 High** / 5 Medium / 5 Low /
  3 Info; **итерация 2: 0 Critical / 0 High, 1 Medium / 2 Low / 5 Info открыто; БАТЧ 2 разрешён**;
  pytest **6052/0**; каталог-интроспекция).

## Round 10.18 — БАТЧ 2/3: F2 `sleep-manual-cascade-badges` (15.09.2026, HEAD 118a03c + рабочее дерево) — карта связностей

- **Пороги Сна (T-1714/T-1769):** `config/settings.py:1091-1107` — code-дефолты 2/8/2/10/60/300000/10
  (`DREAM_REPEAT_THRESHOLD`, `DREAM_IMPORTANCE_SUM_THRESHOLD`, `DREAM_MIN_NEW_FACTS_PER_CHAT`,
  `DREAM_MAX_CLUSTERS_PER_RUN`, `DREAM_DISTILLATIONS_PER_DAY`, `DREAM_TOKENS_PER_DAY`,
  `DREAM_QUIET_CHECK_MINUTES`); анти-мусор (`CLUSTER_OVERLAP_TOKENS=2`, `INITIAL_WINDOW_HOURS=168`) не тронут.
  Новый `services/config_migrations.py::migrate_dream_thresholds(cache)` — идемпотентная DML-миграция
  (правит PG только при равенстве прежнему дефолту 3/12/5/5/30/60000/30; кастом → WARNING; missing → skip;
  PG down → skip), вызов в `bot.py:928-933` сразу после `migrate_prompt_canons`; `prompt_migrations.py` не тронут.
  **Открытая связка (Low S10.18-24):** fallback-константы `_FALLBACK_MIN_CLUSTER_SIZE=2`/`_FALLBACK_MIN_IMPORTANCE_SUM=8`
  теперь равны новым дефолтам → F3-fallback при дефолтах no-op.
- **Manual-приоритет (T-1715/T-1767/T-1771):** `_process_chat(..., manual=True)` — kill-switch
  `gates_enabled(chat_id,"dream", fallback=enabled)` обходится с аудитом `memory_dream_log(kind='skipped',
  status='gate_override')` + WARNING `[dream] manual override: gate dream`; суточные бюджеты/near-limit — обход с
  `status='budget_override'` (пре-аудит до цикла кластеров); `window_skip` обходится (как раньше);
  `_dream_budget_ok`/`_deep_budget_ok` при `manual=True` выполняют 4 независимых `worker_budget.consume`
  (global/chat × calls/tokens) и **не применяют verdict** (расход пишется, `PG down` → fail-open).
  Неприкосновенны: `_run_lock`/`_deep_lock`, `protected_facts`, ≥2 реальных `source_ids`, R17/fail-safe,
  `PERSONA_TRAITS_MAX`/дедуп, `flags.persona_enabled` (только WARNING `reason=persona_disabled`).
  Фича-флагов нет (grep `sleep_manual_priority_enabled`/`sleep_relaxed_thresholds_enabled` — 0).
- **Каскад (T-1716):** `run_once` → `_run` → `_maybe_deep_after_sleep(stats, manual=True, only_chat=chat_id)` →
  `_run_deep_all(manual=True)` (без `break`) → `_run_deep_once(manual=True)` → `_run_persona_traits_once(manual=True)`.
  Manual не гейтится `flags.deep_sleep_enabled`/`trigger`, не гейтится cooldown/`count_deep_attempts`;
  `only_chat` → ровно целевой чат, без цели — `_MANUAL_DEEP_CASCADE_MAX=1`. Единая форма результата
  `_deep_result(status, paradigms, tokens, traits)`; `run_once` отдаёт аддитивный
  `stats["cascade"] = {"deep": {...}, "traits": {"written": N}}`.
- **`_deep_tick` (R10.18-2/R10.18-17):** per-chat `memory.deep_sleep_trigger`+`deep_sleep_hour` по кандидатам
  (`_deep_candidate_chat_ids` — общий путь с `_run_deep_all(None)`); дешёвый предгейт `_deep_fixed_possible()`
  (глобальный 'fixed' ИЛИ `ChatParamsCache.has_any_override('memory.deep_sleep_trigger')`, in-memory).
  **Открытая связка (Medium S10.18-21):** предгейт видит только ПРОГРЕТЫЙ кэш (`_items`/`_override_keys_seen`) →
  per-chat `trigger='fixed'` при глобальном `after_sleep` может быть молча пропущен на «холодном» старте/после
  NOTIFY-инвалидации (частичный откат R10.18-2; тесты покрывают лишь warm-cache).
- **Диагностика Личности (T-1717/T-1770):** R17-safe reason-коды `no_self_facts`, `persona_disabled`,
  `budget_skip`, `llm_error`, `json_error`(+`raw_len`), `empty_response`, `all_duplicates`, `write_error`.
- **Бейджи/статус (T-1719/T-1720/T-1721):** `web/api/memory_agi.py:57-72` `_badge_active_until` (running вне окна →
  `now+_DREAM_RUN_TIMEOUT_SECONDS=900`; в окне → `min(конец окна, now+900)`); аддитивные `dream.manual`/
  `deep_sleep.manual` (+от F7 `effective`/`source`). Фронт: `dreamPhaseBadge`/`deepPhaseBadge` при `cognition==null` →
  `'—'`/`badge-muted` (S10.17-2 закрыт); `runDreamNow` → оптимистичная `active` + немедленный `loadCognition()` +
  `_retryCognition([1s,3s,8s])` + `restartCognitionPolling(5000, 120000)`. Общие хелперы
  `_startCognitionTimer(ms)`/`_restoreCognitionPolling()`/`stopCognitionPolling()` (снимает interval + restore);
  `setTab` вне «Статуса» → `stopCognitionPolling`.
  **Открытая связка (Medium S10.18-22):** `_restoreCognitionPolling` стартует базовые 15с БЕЗ проверки `activeTab`
  (а `closeModule` polling не снимает) → после ручного POST polling (6 GET/тик) идёт вне «Статуса» бессрочно, пока
  не сменится вкладка; обоснован только пока открыта модалка «Сон» (бейджи `index.html:1039-1040`); JS-тест
  фиксирует это поведение.
- **F7-совместимость:** per-chat учёт бюджетов (S10.18-1) сохранён; `dist_max`/`tok_max` резолвятся per-chat один
  раз до цикла кластеров (D8/T-1771). `feature_gates._master_fallback_default` → `settings.DREAM_ENABLED`
  (**S10.18-15 закрыт**). Удалены мёртвые sync-хелперы (**S10.18-16 закрыт**).
- **Инварианты Батча 2:** каталог Δ=0 (436/406/411/90/88/19), DDL нет (SQLite v9; v10 — только F3), R16-аддитивность
  (`cascade`/`manual`/`effective`/`source`), R17 (логи только chat_id/числа/длины), порядок роутеров `bot.py` не тронут.
- Scan-отчёт (Батч 2, §8): `plans/reports/round10.18_scanner_audit.md` — **0 Critical / 0 High**, 2 Medium
  (S10.18-21/-22), 4 Low, 8 Info; закрыты S10.18-15/-16/-17. Валидатор: pytest **6083/0**, JS-гейты OK,
  `git diff --check` exit 0. **Вердикт: к Батчу 3 (F3 граф + v10) — можно.**

## Round 10.18 — БАТЧ 3/4: F3 `graph-density-scoring-stoplist` + F4 `graph-physics-stabilization` (15.09.2026) — карта связностей

- **SQLite v10 (F3/T-1773, ADR-1018-3 D1):** `services/database.py` — `_SCHEMA_VERSION_EDGES_FACT_ID = 10`
  (текущая цель `user_version`; 9 — историческая ступень), `_SCHEMA_SQL.edges` += `fact_id INTEGER` (nullable),
  новый `_migrate_edges_fact_id_v10()` в цепочке `initialize()` после `_migrate_self_origin_v9()`: guard по
  `PRAGMA table_info(edges)` → `ALTER TABLE edges ADD COLUMN fact_id`; `CREATE INDEX IF NOT EXISTS idx_edges_fact_id`
  **вне guard и НЕ в `_SCHEMA_SQL`** (legacy-БД до миграции не имеет колонки); `PRAGMA user_version = 10` — безусловно,
  после индекса → частичный сбой самовосстанавливается. Данные/FTS5/vec не затрагиваются; обратный путь —
  DROP INDEX + DROP COLUMN + user_version=9 (docstring). Legacy-рёбра: `fact_id IS NULL` осознанно (backfill отклонён, A7).
- **Скоринг (F3/T-1728):** `graph_snapshot(chat_id, max_nodes=800, max_edges=2400, seed_nodes=150)` (новые дефолты;
  API `web/api/memory_agi.py:643` передаёт `GRAPH_MAX_NODES=800/GRAPH_MAX_EDGES=2400/GRAPH_SEED_NODES=150`).
  `score(node) = Σ COALESCE(graph_facts.importance, edges.weight)` по инцидентным рёбрам (`edges.fact_id` v10,
  `LEFT JOIN graph_facts f ON f.id = e.fact_id`); `degree` — отдельная метрика (фронт `_graphSignature`), не сортировка;
  tie-break `score DESC, degree DESC, id ASC`; кандидатный пул `max(seed×10, 2000)` + Python-ранжирование (D8).
  **Открытая связка (Medium S10.18-30):** ×2-фаза (per-node `re.search` по belief-блобу) доминирует в перфе
  (~176 мс при 200 beliefs; до секунд при тысячах) и выполняется в event loop на каждый `GET /api/memory/graph`
  (polling 15с / 5с при manual) — «SQL-часть» ≈59 мс на 15k рёбер совпадает с заявленным бюджетом, полный вызов ≈238 мс.
- **STOP_LIST (F3/T-1730):** новый `services/graph_stoplist.py` — `GRAPH_CENTER_STOPLIST`
  {видеосообщение, голосовое, сообщение, фото, кружочек, ссылка} (фильтр **только сидов**) и
  `METAFACT_PENALTY_STOPLIST` (+«стикер», −«сообщение») для переиспользования F5; `normalize_token`
  (casefold + ё→е + срез краевой пунктуации), `is_center_stopword`/`is_metafact_stopword`. Единый источник, Δ каталога = 0.
- **×2 за Убеждение/Парадигму (F3/T-1728, D4):** `_belief_participation_blob(chat_id)` — текст живых
  (`kind='belief'`, `status='confirmed'`, `supersedes IS NULL`) beliefs, casefold+ё→е; матч по **границам токенов**
  `(?<![\wё])re.escape(name)(?![\wё])` (substring исключён, многословные имена поддерживаются); fail-open → ×1.
- **Атомарность fact+edge (F3/T-1774, B3-5):** `insert_graph_fact(..., commit=False)` + `upsert_edge(..., fact_id=…,
  commit=False)` + единый `self.db.db.commit()`, `except → rollback; raise` (`services/summary_memory.py:1832-1852`);
  `upsert_edge` += `fact_id`/`commit`, `ON CONFLICT … fact_id = COALESCE(excluded.fact_id, edges.fact_id)`;
  cron-путь `_extract_and_save_graph` — осознанный `fact_id=NULL`; остальные 8 сайтов `insert_graph_fact` и все
  `upsert_edge` — дефолт `commit=True` (поведение не изменилось).
- **Плотность/Canvas:** 150 сидов → окрестность 1 шаг → рёбра только с обоими концами (S10.13-14) → очистка сирот →
  cap 800/2400 ПОСЛЕ расширения; `truncated` = cap узлов/рёбер/сироты (фронт «показаны не все»). Каталог Δ=0.
- **F4 `graph-physics-stabilization` (ADR-1018-4):** `web/app.js` — `GRAPH_PHYSICS_ITERATIONS=150`,
  `GRAPH_PHYSICS_DISABLE_ON_STABILIZE=true`; `net.once('stabilizationIterationsDone'|'stabilized')` →
  `setOptions({physics:{enabled:false}})` под guard **только по тождеству** `net === this.cognitionNetwork`
  (в self-host v9.1.9 нет `destroyed`/`isDestroyed`); `once` (не `on`) → нет накопления; `reducedMotion` → `physics:false`
  и слушатели не навешиваются; `renderCognitionGraph` → destroy-before-create + early-return по `_graphSignature`;
  поиск/подсветка/бейджи не тронуты.
- **S10.18-закрытия Батча 3:** S10.18-21 (предгейт `_deep_tick` удалён; `has_any_override`/`note_overrides` убраны
  из `chat_params.py`), S10.18-22 (`_restoreCognitionPolling` — 15с только на «Статусе»; `closeModule` вне вкладки
  гасит polling), S10.18-23 (маркеры `manual_run_active`/`manual_deep_active` + `_MANUAL_RUN_MARKER_SECONDS=900`),
  S10.18-24 (`_FALLBACK_MIN_IMPORTANCE_SUM=6` < дефолта 8), S10.18-25 (`0` = «без лимита» в near-limit),
  S10.18-26 (ретраи `_cognitionRetryTimers` снимаются; порядок restart→retry в `runDreamNow`).
  **Новый Low S10.18-29:** manual-каскад (`run_once(deep=False)`) не ставит `_manual_deep_until` → `deep_sleep.manual=False`
  и `active_until=None` во время deep-фазы каскада вне окна.
- **Инварианты Батча 3:** каталог Δ=0, SQLite v10 (миграция аддитивна/идемпотентна/обратима), R16 (`limits`
  в `/api/memory/graph` аддитивно; `id/label/group/degree` без изменений), R17 (STOP_LIST/×2 без текстов в логах),
  порядок роутеров `bot.py` не тронут.
- Scan-отчёт (Батч 3, §9): `plans/reports/round10.18_scanner_audit.md` — **0 Critical / 0 High**, 1 Medium
  (S10.18-30), 1 Low (S10.18-29), 8 Info. Валидатор: pytest **6104/0**, JS-гейты OK, `git diff --check` exit 0.
  **Вердикт: к Батчу 4 (F5 + F6) — можно.**

## Round 10.18 — БАТЧ 4/4: F5 `metafact-penalty-extractor-prompt` + F6 `role-matrix-settings-actualization` (15.09.2026) — карта связностей

- **F5 хард-лимит мета-фактов (T-1744, ADR-1018-5 D2/D3):** `services/graph_stoplist.py` +=
  `METAFACT_PENALTY_IMPORTANCE = 1`; `services/database.py::insert_graph_fact` += аддитивные
  `subject/object` (в конце сигнатуры → позиционная совместимость 8 call-сайтов сохранена) и после `imp`:
  `if is_metafact_stopword(subject) or is_metafact_stopword(object): imp = min(imp, 1)` — централизованно,
  перекрывает `rule_importance` и явный `importance`; `_memorize_facts_inner` передаёт `subject/object`
  (единственный покрытый путь — осознанное ограничение D2/spec §9 Q3). **Открытый Low S10.18-35:** эпи-мерж
  (`services/memory_maintenance.py:250-258`) ре-вычисляет importance от origin (chat_history → 4) → слитый
  мета-факт теряет пенальти.
- **F5 промпт-канон (T-1743, ADR-1013-3):** `services/summary_memory.py` — `PREV_FACT_EXTRACT_PROMPT`
  (байт-в-байт прежний, 649 симв., проверено AST-пробой) + новый `FACT_EXTRACT_PROMPT = PREV + 335-байтный
  аддитивный блок «ФОКУС НА СОДЕРЖАНИИ»`; `PROMPT_MIGRATIONS` **не расширен**; `EXTRACT_PROMPT`
  (`prompts.extract_system_prompt`, крон) не тронут; эталон — `plans/docs/canon/backlog.md` (байт-тест).
- **F5 RAG-множитель (T-1746, ADR-1018-5 D7/B4-1):** `_importance_factor(imp)=0.5+0.05·clamp(1..10)` ∈ [0.55, 1.0]
  (`summary_memory.py:235-249`), применяется в **обеих** ветках `_search_graph_facts` (FTS-фолбек `:2349-2351`,
  KNN `cosine×w_eff×factor` `:2410`) — ветки взаимоисключающи (двойного применения нет); `f.importance` добавлен
  в SELECT `search_graph_facts_fts` (`database.py:2637`) и `get_graph_fact_records` (`:3448`);
  MMR/дедуп/`touch`/resurrection используют тот же `score`; golden-путь — отдельный SQL-порог. **Info S10.18-37:**
  множитель меняет RAG-порядок для всех чатов (weight×decay → ×importance) — нужна живая проверка.
- **F6 nav-разметка матрицы (T-1752, ADR-1018-6 D1/D2/D3):** `services/param_catalog.py` — Python-метаданные
  `NAV_MODULES/NAV_AI/NAV_PERMSOC`, `NAV_TITLES`, `NAV_ORDER=("modules","ai","permsoc")`, `TAB_NAV` (все 19 вкладок),
  `tab_nav()`; `CONFIG_TAB_TITLES[TAB_PERMSOC]` = «PERMsoc» (дрейф устранён); `web/api/access.py::param_permissions_list`
  += аддитивные `nav/nav_title/nav_order` (R16; 403/форма прав не изменены); `web/app.js::matrixSections` группирует
  nav → секция (`TAB_SECTION_ORDER`, fallback `cat:<category>`) → группа → параметры, JS-зеркало
  `NAV_GROUP_ORDER`/`NAV_GROUP_TITLES` закреплено parity-тестом; `web/index.html` — вложенный шаблон.
  Фактически **4** nav-группы: 3 backend + «Прочее» (`it.nav || 'other'`) для 5 content-параметров с `tab=None`
  (`MEDIA_PUBLIC_BASE_URL`, `MEDIA_SHARE_DIR`, `content.info_how_it_works`, `content.intelligence_guide`,
  `content.no_key_reply`; проверено интроспекцией: nav-распределение 161/180/65/5 = 411). **Info S10.18-36:**
  spec §3.1 говорит «3 nav» — синхронизировать с ADR D4 (B4-info(a)).
- **Сквозная интеграция (F1–F7):** конфликтов между батчами нет — F3-скоринг (`Σ importance` в `graph_snapshot`)
  и F5-множитель живут в разных read-путях; мета-факты (imp=1) вносят минимум и в сиды F3, и в RAG F5, и не
  проходят гейты Сна (поведенческий тест); F4-физика рассчитана на плотность F3 (500–800); F7 per-chat accessor
  не конфликтует с F5/F6; F1 — единственный Δ каталога (+1).
- **Итоговые инварианты эпика 10.18:** каталог **436/406/411/90/88/19**, SQLite **v10**, R16 (все новые поля
  аддитивны), R17 (логи без секретов/текстов), fail-open, порядок роутеров `bot.py` не тронут.
- Scan-отчёт (Батч 4, §10 + итог эпика §10.4): `plans/reports/round10.18_scanner_audit.md` — Батч 4:
  **0 Critical / 0 High**, 1 Low (S10.18-35), 3 Info (S10.18-36/-37/-38). Валидатор: pytest **6137/0**,
  JS-гейты OK, `git diff --check` exit 0. **Вердикт эпика: 0 Critical / 0 High → к @Reviewer/@PM →
  Merge/архивация → деплой @DevOps** (открыто 1 Medium S10.18-30, 2 Low, 11 Info; блокеров нет).



## Round 10.17 (2026-09-14, F1–F5, HEAD 772f192 + рабочее дерево) — карта связностей

- **F1 miniapp-mobile-dns:** `web/app.py::_startup_diag` (scheme/host/path через `urlsplit`, R17) + явные
  `@app.head("/web/")`/`("/web/index.html")` +`GET/HEAD /healthz` (JSON `{status,version}`, `no-store`, CSP
  для HTML-роутов) — маршруты ДО `app.mount("/web", CacheControlStaticFiles)`; `handlers/menu.py:63-70`
  host-only лог. No-CDN гейт `tests/test_webapp_dns_round1017.py` (SCANNED + VENDOR_SCANNED ×6).
- **F2 tool-download-quality:** `services/tool_router.py::_download_media` (probe→меню→`needs_quality`) →
  `store/peek/pop_tool_download_pending` (`_TOOL_DL_PENDING[(chat_id,user_id)]`, TTL 600 c) ↔ callback
  `handlers/video_download.py::cb_tool_quality` (`tdq:`) — доводит `download(url, f"{quality}p")`; общий
  построитель меню `services/media_send.py::build_quality_keyboard/quality_menu_text/send_quality_menu`
  (Fast-Track `vd:` + tool `tdq:`); `QUALITY_ENUM` (`tools/video_downloader.py:105`) = JSON-Schema enum;
  SUPERSEDE ADR-1016-1 §2 п.3/§3 → ADR-1017-2. `_download_now` — direct/явное качество/bounded fallback.
- **F3 sleep-badge-countdown:** `web/app.js::fmtCountdown` (`:5116`) ← `dreamPhaseBadge`/`deepPhaseBadge`
  (`:1216`/`:1234`); `now = cognition.generated_at`; ветка `enabled=false→«выключен»` удалена (остаток без
  свечения); активная фаза — `glow` + `fmtClock(active_until)`. ADR-1017-3.
- **F4 ssh-rotation-cancelled:** docs-only, кода нет. CANCELLED: `README.md:74,387`, `plans/ARCHITECTURE.md:326,616,624,628`,
  `plans/backlog.md:95-97`, `archive/security-rotation-finalize-round1016/tasks.md:5`; **остаток S10.17-1** —
  архивная `spec.md` без banner (§8 «ротация обязательна в любом случае»).
- **F5 warnings-hygiene:** `web/api/avatars.py::_log_bot_api_failure` — 6 сайтов (fetch 142, chat 211,
  member 252, photos 273, global-name 323, global-photos 347): `TelegramBadRequest`→DEBUG (негатив кэш),
  транзиент→WARNING без трейса и без кэша, generic→WARNING+`exc_info`. brotli WONTFIX (build-time only;
  Caddy `zstd+gzip`).
- Scan-отчёт: `plans/reports/round10.17_scanner_audit.md` (0 Critical / 0 High / 1 Medium / 2 Low / 3 Info;
  валидатор pytest 6007/0, JS-гейты OK).

## Round 10.16 (2026-09-14, F1–F5, HEAD 18a9aa1 + рабочее дерево) — карта связностей
- **F1 download-fix:** `tools/video_downloader.py::VideoDownloader.download(url, quality=None, progress_cb)`
  (ветвление direct/YouTube/cobalt по URL; `_normalize_quality` None/auto/best/max/direct→`max`, `144…4320`);
  `DownloadError.reason` (safe-токен, `default_reason` у подклассов) → потребители
  `handlers/video_download.py` (`_fallback_phrases`/`_probe_error_phrase`/`_download_without_menu`)
  и `services/tool_router.py::_download_media` (DownloadError→`status:"error"`). Env-preflight:
  `download_env_summary`/`log_download_env_once` → `config.settings.get_ytdlp_pot_provider` (единый POT-источник).
  Горячий гейт `flags.download_enabled` перенесён из `bot.py` (startup) в `video_download_handler`;
  `bot.py` регистрирует `video_download_router` (4e) ВСЕГДА; `direct_chat._functional_module_active("download")`
  → `download_available()` (`_downloader is not None`, фактически всегда True).
  **Открытая связка (High S10.16-1):** `handlers/youtube.py::_download_or_phrase` логирует `str(exc)` —
  `DownloadError.args` несут `url={url}` → R17-утечка.
- **F2 guide-delivery:** `services/config_cache.py::_migrate_info_how_it_works_v1015` (+`_write_info_canon`) ↔
  `services/info_service.py::canon_drift/normalize_canon/KNOWN_INFO_SNAPSHOTS/DEFAULT_INFO_TEXT` (INFO_CANON_VERSION=2);
  маркер `canon_delivered_version`; write-path PG-only (`InfoService.save_text`/`reset_canon`) ↔
  `web/api/routes.py` (`POST /api/info`, `POST /api/info/reset-canon` RBAC `edit_info`) и `handlers/info.py::cmd_edit_info`;
  UI `web/app.js::resetInfoCanon`. `info_text.md` — read-only сид. **Открытая связка (Medium S10.16-2):**
  форс-доставка неизвестного текста не сохраняет `prev_html`.
- **F3 audit:** единый `services/database.py::parse_belief_meta` ← делегаты `dream_worker._belief_meta` /
  `summary_memory._belief_base_weight`; `graph_stats.archived_beliefs` NOT LIKE-фильтр парадигм;
  `services/command_prefix.py::split_prefix_anywhere(text, url_before=None)` ← `handlers/youtube.py`/`handlers/web.py`
  (`_has_video_target`); `handlers/direct_chat.py` gating download. Смоук-набор `tests/test_smoke_round1016_*.py`.
- **F4 miniapp:** `web/index.html` → self-host `web/static/vendor/*` (vue 3.5.42 / chart 4.5.1 / telegram-web-app.js /
  tailwind prebuilt + `tailwind.config.js` / `tailwind.input.css`), `web/static/app.css` (вынесен из inline `<style>`),
  `web/static/telegram-init.js`; CSP `_CSP_HTML` в `web/app.py` (`script-src 'self' 'unsafe-eval'` — full-сборка Vue,
  `frame-ancestors` Telegram); `/static/app.css` роут с подстановкой `?v=` (`_render_app_css`).
- **F5 security:** `plans/features/security-rotation-finalize-round1016/ssh-rotation-checklist.md`,
  `plans/reports/round10.16_security_scan.md`; `plans/current_task.md` untracked (`.gitignore:70`).
- Scan-отчёт: `plans/reports/round10.16_scanner_audit.md` (0 Critical / 1 High / 1 Medium / 6 Low / 3 Info).

## Stack
- **aiogram 3.31** (polling) + **FastAPI** webapp (`web/app.py`) + **asyncpg** (PG) + **aiosqlite** (memory v8). APP_VERSION=2.51.0.
- **httpx** for LLM/API calls, **sqlite-vec** (optional) for vector search, **FTS5** built-in fallback.
- **uvicorn** single event loop (R2: no threads, `loop="auto"`).

## Core Architecture

### Entry Point: `bot.py`
- **Router registration order (CRITICAL - DO NOT CHANGE):**
  1. `summary_observer_router` (0a) - catch-all, saves ALL messages, returns UNHANDLED
  2. `summary_router` (0b) - /summary command
  3. `factcheck_router` (0c) - fact-check replies
  4. `search_router` (0d) - smart search
  5. `youtube_router` (0e) - YouTube URL processing
  6. `web_router` (0f) - web URL processing
  7. `checkup_router` (0g) - checkup triggers
  8. `direct_chat_router` (0h) - reply/mention to bot
  9. `voice_transcription_router` (0i) - voice/video transcription
  10. `admin_commands_router` - admin test commands
  11. `menu_router` - /menu command
  12. `debug_config_router` - hidden diagnostics
  13. `info_router` - /info + /edit_info
  14. `slava_presence_router` - ChatMemberUpdated (Slava return detection)
  15. `alan_greeting_router` - ChatMemberUpdated (Alan greeting video)
  16. `chat_lifecycle_router` - ChatMemberUpdated (bot lifecycle + migrate)
  17. `kostik_router` - user ID 350803143
  18. `alan_router` - user ID 138811255 (reply engine, every 10 msgs)
  17. `dead_page_router` - reposts from @d_pages
  18. `dead_page_delete_router` - reply/quote on deleted repost
  19. `war_alert_router` - keyword + channel repost alerts
  20. `common_router` - otboy/danger/selfdev/work/mimic
  21. `olya_router` - video from @ole4444444ka
  22. `video_download_router` - "скачай <url>" trigger
  23. `slavik_router` - user ID 479167456 (catch-all)
  24. `vasya_router` - text filters, no user restriction

### Configuration System
- **`config/settings.py`** - frozen `Settings` dataclass, reads from `.env` + env vars. Helper functions: `_env_int`, `_env_float`, `_env_bool`, `_env_str`, `_env_duration`, `_env_int_tuple`, `_env_int_min`, `_env_float_min`, `_env_int_optional`.
- **`services/hot_config.py`** - `hot.get(pg_key, default)` runtime hot-config over PG. Two-tier typing: catalog-aware coercion (`_coerce`).
- **`services/config_cache.py`** - `ConfigCache`: in-memory cache of `bot_settings`, `bot_roles`, `bot_admins`. `init()` with retry + fail-open (R6: PG down → WARNING, bot works on settings defaults). Asyncio.Lock on writes. Hot-reload via POST /api/config.
- **`services/chat_params.py`** (Round 10) - per-chat override layer: `chat_params` JSONB + `gates_opt_in` + `chat_keys` (BYOK). `ChatParamsCache` with NOTIFY listener.

### RBAC & Permissions
- **`services/permissions.py`** - pure matcher (`Permissions` class, bitmask-style flags).
- **`services/roles.py`** / **`services/access.py`** - RBAC v2: `role_type` (built-in vs custom), `access_for` (global/chat/both), `can_edit_param`.
- **`services/param_catalog.py`** - `REGISTRY` of 392 `ParamSpec` (91 groups) — 10.6. Fields: `per_chat`, `progressive_level`. Single source of truth for config metadata (`TAB_RULES` 19 вкладок).

### Database Layer
- **`services/database.py`** - SQLite (aiosqlite). Tables:
  - Core: `user_presence`, `message_counters`, `dead_page_posts`, `channel_state`, `relay_album_map`
  - SmartModule Summary (Epic 24): `smart_messages` (+ FTS5), `smart_archive_facts` (+ FTS5), `smart_archive` (sqlite-vec, lazy), `nodes`, `edges`, `graph_facts` (+ CHECK origin, `importance`, `source_ids`, `kind`, `belief_meta`, `weight`, `confirmed_at`, `expires_at`), `graph_facts_vec` (sqlite-vec), `embedding_cache`, `compression_log`, `user_memory`
  - DirectChat (Epic 50): `throttle_state`, `bot_replies`
  - Video (Round 3): `video_origins`
- **`services/pg_db.py`** - PostgreSQL (asyncpg). Idempotent DDL + seeds. Tables:
  - Config: `bot_settings` (key, value JSONB, category, updated_at), `bot_roles` (role_name, permissions JSONB, is_custom, role_type), `bot_admins` (telegram_id, role_name, added_by, created_at)
  - Uptime: `uptime_events`
  - Chat Lore (Round 7): `chat_profiles` (chat_id PK, manual_lore, auto_lore, auto_enabled, auto_period_hours, auto_window_hours, is_active, last_auto_at, updated_at, **relations JSONB**, **relations_enabled**, **chat_params JSONB**, **gates_opt_in**), `chat_lore_history`, `chat_links`, `chat_admins` (chat_id, telegram_id, added_by, created_at, **role_name**)
  - RBAC (Round 10): `param_permissions`, `chat_keys` (BYOK), `chat_usage` (daily budget), `worker_budget` (daily ledger)
  - Migrations: ALTER TABLE ... ADD COLUMN IF NOT EXISTS for additive deltas

### LLM Client (`services/llm_client.py`)
- Single `httpx.AsyncClient` per process (lazy, `close()` in `on_shutdown`).
- Endpoints: `/chat/completions`, `/embeddings` (OpenAI-compatible).
- **Epic 47**: Retries ALL transient errors (httpx.TransportError + HTTP 408/425/429/5xx). Exponential backoff + jitter. `Retry-After` header priority for 429/5xx. Hard total budget: `LLM_TOTAL_BUDGET` via `asyncio.timeout`. 401/403 → `LLMAuthError` immediately.
- **Epic 53**: `LLMServerError`/`LLMTransportError` classes. Optional fallback provider (`LLM_FALLBACK_*`). Circuit Breaker lives in `direct_chat_service` (llm_client knows nothing about it).
- **Epic 67**: `VoiceTranscriber` (Groq Whisper / OpenRouter) with shared `asyncio.Semaphore` (`GROQ_MAX_CONCURRENCY`).

### SmartModule (Epic 24/26/33/37/42/50/60/67)
- **Summary (Epic 24)**: Three-level memory (L1 window, L2 FTS5-RAG, L3 archive + vec). `SummaryGenerator`, `MemoryManager`, `SummarySchedulerService`.
- **GraphRAG v2 (Epic 46)**: `memorize_facts` (Fact Extractor, canon R46-2), hybrid RAG (`build_rag_context`, canon R46-4), fire-and-forget hooks, vec reactivation, backfill.
- **Epic 60 (Phases A-D)**: Graph dedup (cosine thresholds), episode merge, time-decay, user quota, fact touch, int8 vec compression.
- **FactCheck + SmartSearch (Epic 33)**: `SearchAggregator` (Tavily/Exa), `FactCheckService`, `SearchService`.
- **YouTube + Web (Epic 37)**: `YouTubeTranscriptEngine` (failover: transcript-api → yt-dlp → Cobalt), `WebContentExtractor`, `YoutubeSummarizerService`, `WebSummarizerService`, `OpenRouterVideoClient` (L1/L2 video cascade).
- **Checkup (Epic 42)**: `CheckupService` + `CheckupLogsFetcher` (Betterstack SQL API + journalctl fallback).
- **DirectChat (Epic 50)**: `DirectChatService` with tools (`ToolRouter`), persistent throttle (`PersistentThrottle`), dedup cache (`smart_cache`), ChatLoreCache injection.
- **VoiceTranscriber (Epic 67)**: Shared instance with YouTube media branch.

### Background Workers
- **SchedulerService** - dead page relay scheduling
- **SummarySchedulerService** - daily summary generation (starts BEFORE polling)
- **GoodmorningSchedulerService** - daily goodmorning media
- **MemoryBackupService** - daily VACUUM INTO + text export
- **MemoryMaintenanceService** - episode merge + fact review (JobStore)
- **UptimeHeartbeatService** - 60s heartbeat to `uptime_events`
- **LoreWorker** (Round 7) - auto-lore generation from chat messages (PG profiles)
- **DreamWorker** (Round 9) - "sleep": beliefs from recurring facts (SQLite state)
- **NostalgiaWorker** (Round 9) - "golden layer" nostalgia (1 year ago facts)
- **RelationsService** (Round 9) - users_meta lazy recompute + manual merge from PG

### Web Layer (TMA, Vue 3 global, no build)
- `web/app.py` - FastAPI app, creates `ConfigCache` + `ControlService`
- `web/index.html` + `web/app.js` - SPA, no build step
- API routes: `web/api/` (access, chat_lore, avatars, oversight, config, admins, roles, params, permissions, keys, usage, status, logs, direct_chat, relations, workers, system)
- Chat selector: GET `/api/access/chats` + `X-Chat-Id` header
- 6 пунктов навигации (10.8): Статус / Справка / Модули / ИИ / PERMsoc / Доступы
  (+ хаб «Доступы»: подразделы Матрица ролей / Локальные админы / Роли — route-driven модалки)

### Deploy
- `deploy_v2.9.2.py` - prod deploy (DDL + backfills)
- `scripts/backfill_*` - backfill scripts
- Prod: 198.46.175.136:/var/www/admin_bot (systemd admin_bot)
- `docker-compose.yml` / `docker/` - local PG
- `ControlService` flag-file stop mechanism (Epic 85)

### Security Notes
- Raw API keys NEVER logged (R17); `/api/config` masks secrets `{configured,last4}`
- `BetterStackHandler` custom (logtail 0.4.0 had silent drops)
- `log_ring` in-memory ring buffer for `/api/status/logs` (secret masking in emit)
- fail2ban/ufw/SSH hardening on prod
- BYOK (Bring Your Own Key) per-chat via `chat_keys` (Round 10)

## Key Data Flows

### Message Processing
```
Update → Dispatcher → Router chain (fixed order)
  → summary_observer (save to smart_messages, UNHANDLED)
  → summary / factcheck / search / youtube / web / checkup / direct_chat / voice
  → admin / menu / debug / info
  → slava_presence / alan_greeting / chat_lifecycle (ChatMemberUpdated)
  → kostik / alan / dead_page / dead_page_delete / war_alert
  → common (otboy/danger/selfdev/work/mimic)
  → olya / video_download / slavik / vasya
```

### Config Read Path
```
Service → hot.get(pg_key, settings.DEFAULT)
  → ConfigCache.get(key) [sync, in-memory]
  → if miss: settings.DEFAULT
  → PG writes via ConfigCache.set() + hot-reload
```

### LLM Call Path
```
Handler → LLMClient._post()
  → retry loop (transient errors only)
  → asyncio.timeout(LLM_TOTAL_BUDGET)
  → 401/403 → LLMAuthError
  → 5xx exhausted → LLMServerError
  → TransportError exhausted → LLMTransportError
  → (optional) fallback provider
```

### Worker Budget (Round 10)
```
worker_budget.consume(scope, metric, cost)
  → PG ledger (worker_budget table)
  → Priority: nostalgia → lore → dream
  → Degradation when budget exceeded
```

## Module Dependencies (High-Level)
```
bot.py
├── config.settings
├── services.hot_config
├── services.config_cache (ConfigCache)
├── services.database (DatabaseService)
├── services.pg_db (PgDatabase)
├── services.llm_client (LLMClient)
├── services.summary_memory (MemoryManager)
├── services.summary_generator (SummaryGenerator)
├── services.direct_chat_service (DirectChatService)
├── services.lore_* (ChatLoreStore/Cache/Notify/Worker)
├── services.dream_worker (DreamWorker)
├── services.nostalgia_worker (NostalgiaWorker)
├── services.user_relations (RelationsService)
├── services.worker_budget
├── services.oversight
├── services.memory_backup
├── services.memory_maintenance
├── services.search_aggregator (SearchAggregator)
├── services.factcheck_service
├── services.youtube_* / web_*
├── services.voice_transcriber
├── handlers.* (23 routers)
├── web.app (FastAPI)
└── services.control_service (ControlService)
```

## Recent Changes (from git status)
- Round 10.3 (uncommitted, HEAD d30b203): F-13/F-14/F-15 — см. full_audit_results.md «Round 10.3».
- `plans/reports/` - audit infrastructure

## Round 10.3 map additions (F-13/F-14/F-15)

- **DM-скоуп** = `chat_id > 0 && chat_id == telegram_id` (`services/chat_params.py::is_dm_scope` —
  единственный идентификатор). DM-профили = строки `chat_profiles(chat_id=user.id)` (ноль DDL).
- **`services/roles.py`**: `AccessCtx.is_dm_owner: bool = False` (в конец полей); DM-ветка в
  `access_for` ДО chat_admins-лукапа: role_chat=None, perms_chat=`DM_OWNER_PRESET`
  (sections: prompts/limits/flags/reactions/content/memory; БЕЗ chat_lore), rank=max(ранг,3).
- **`services/access.py`**: `can_access_chat(ctx, chat_id=None)` — аддитивный chat_id: DM →
  только is_dm_owner (global admin в чужом ЛС → False). `eligible_type`: is_dm_owner →
  local_admin. `can_edit_param`: ветка is_dm_owner после is_global_admin, до role_chat-гейта.
- **`services/chat_params.py`**: `ensure_scope_profile(chat_id, dm=True)` (INSERT ON CONFLICT,
  auto_enabled=false, is_active=true, gates_opt_in=false) — перед первым write DM;
  `get_chat_param_defaulted(chat_id, key, fallback)` (override→cast→fallback, БЕЗ hot.get);
  `chat_summary_enabled(chat_id)` — группа: hot.get (байт-в-байт); ЛС: defaulted False.
- **Саммари-гейт S1/S2/S3**: summary_memory.get_window_messages (~:1291),
  direct_chat_service._build_global_context (~:1707), summary_scheduler._tick (skip chat_id>0).
  bot.py:613-643 — НЕ тронут. L3/GraphRAG — не гейтится.
- **Изоляция DM**: chat_lore_store LIST_ACTIVE_CHATS_SQL/LIST_ACTIVE_CHAT_IDS_SQL/list_profiles +
  oversight PROFILE_COLS_SQL + web/api/access CHATS_FOR_USER_SQL — WHERE chat_id < 0;
  web/api/chat_lore._require_chat → is_dm_scope → 404; gates PUT DM → 403 (GET read-only 200).
- **TMA**: /api/access/chats + /me синтезируют DM-строку {chat_id: user.id, title: «Личные
  сообщения», access:'dm', is_dm:true} для любого авторизованного; GET /api/config X-Chat-Id=ЛС:
  keys.* скрыты (не global admin), models.* — read-only справка (per_chat=False), ctx.is_dm=true.
- **Фронт**: единый select-селектор (F-13 AC-1; бейдж `#id`/`ЛС #id`); configError-баннер
  (403/503/сеть, MED-021) с «⟳ Повторить»; `<template v-for>` + v-if на дочернем div (AC-3);
  z-index sidebar 45 (AC-5); isDmCtx()/canViewTab-DM-ветка (config кроме permsoc)/canEditConfig-DM
  (все кроме keys.*)/resetChatOverride (+isDmCtx). BYOK-блок покрывает DM без изменений.
- **F-15**: `NoApiKeyForChat(chat_id, reason, details=None)` — details-снапшот (resolve_path/day/
  used/limit — R17); BYOK-фоллбэк: повторное чтение своего ключа ПОСЛЕ budget_exceeded (1 доп.
  SELECT, usage не тратится); WARNING `[direct] no key — sandbox answer | details=…`;
  summary_memory: `_mask_llm_raw` (500 симв., секрет-паттерны), WARNING memorize c raw-фрагментом;
  `_fallback_parse_facts` (JSON-в-тексте/тройки/csv/ёлочки/тире); 1 ретрай жёстким промптом
  `_FACT_RETRY_SYSTEM_PROMPT` ТОЛЬКО в _memorize_facts_inner (крон _extract_and_save_graph — нет).

## Round 10.4 map additions (A/B/C/D/E/F/G/H, HEAD 1410a68 + working tree)

- **Per-chat read-path (G-3) — расширение `get_chat_param` точки** (async, кэш 120с+NOTIFY):
  `direct_chat_service._build_user_content` (budget-гейт `flags.chat_context_budgets_enabled` +
  база `limits.chat_context_budget_tokens` → `_apply_context_budget(blocks, enabled, tokens)`),
  `_active_participants` (map hours/cap), `_build_global_context` (global_context_limit/max_tokens/
  max_chars, level2_max_chars), `_collect_thread_chain` (thread_max_depth),
  новый **`_thread_limit(chat_id)`** (thread_max_tokens/max_chars → `_render_thread` 3-й параметр,
  None → старое поведение), `summary_generator.generate` (summary_rag_l2_limit/
  max_context_tokens/max_context_chars), `summary_memory` get_window_messages (summary_max_window_
  messages), get_rag_context (graph_rag_facts_limit/context_max_chars), _compress_and_purge/
  _compress_purge_extract_only (full_memory_retention_days/summary_compress_batch), memorize
  edge_weight_increment, _purge_archive (archive_memory_retention_days).
- **G-2**: `chat_params._resolve_from_root` — после normalize_value проверка `_cast_type_ok`
  + `math.isfinite` для float (NaN/inf/мусор → hot.get-фолбэк; AC-G4).
- **B-12**: `summary_aliases.build_alias_resolver(chat_id)` — per-chat алиасы (override →
  глобальные; fail-open глобальные; НЕ зависит от summary_enabled). ↓ ДОСЛОВНО НЕ доведён до
  инжекта `<user_relations>` — documented limitation (user_relations.py), кандидат F-5.
- **B-7/B-8**: ParamSpec += `select_options/select_labels` (tuple, дефолт ()); запись
  `CHAT_TEMPERATURE_PRESET_DEFAULT` — widget select ("precise"/"balanced"/"chatty" +
  labels); применяется через dataclasses.replace после _build_registry (REGISTRY 383 без роста).
  Append-метка: `_SELECT_WIDGET_PRESETS`.
- **TAB_RULES (каталог)**: 10 вкладок-частей: llm_providers — 4 секции (повтор MODELS/KEYS),
  limits — except расширен (mimic/deadpage/media/lore/user_aliases/relations и флаги),
  memory_rag (infinite) + memory_dream + memory_nostalgia, reactions_triggers (4),
  permsoc (11+2+4), modules_switches, chat_lore (limits_lore+flags_lore — правило НЕ-config
  вкладки), people_names (limits_user_aliases), relations (limits_relations+flags_relations).
  `_TAB_BY_GROUP`: 72 группы (как HEAD; content_info/content_media — никогда не были на
  конфиг-вкладках). NEW правил: NONE потеряно/добавлено.
- **Фронт**: TABS-зеркало (new: memory_dream/memory_nostalgia/people_names/relations/
  modules_switches; chat_lore += sources), `flatGroupRank` (порядок ПРАВИЛ → витрина;
  fallback catFirst; для вкладок без повтора категорий = старой категориальной),
  `sectionTitle` (заголовок секции — раз на секцию; только у llm_providers),
  `chatLoreTab()`/`relationsTab()` (TABS-записи для groupedForTab конфиг-частей),
  setTab: relations-автозагрузка (не DM), сброс лор-профиля при уходе с chat_lore,
  relations-методы: relChat = activeTab==='chat_lore' ? p.chat_id : activeChatId.
- **B-9 (routes.py)**: GET items += select_options/select_labels (None для не-select);
  POST-валидация опций в ОБЕИХ ветках (per-chat :413-417 и _post_config_global :671-675).
- **H-2 (chat_lore.py list_relations)**: username-обогащение ВСЕМ строкам (Semaphore(5), gather),
  photo — только топ-50 (второй проход; кэши avatars 1ч); `_RELATIONS_SEMAPHORE_LIMIT=5`.
- **backfill_104_chat_flags.py (B-4)** / **backfill_104_overrides.py (G-5)**: ensure_scope_profile
  dm=False + set_chat_params (запись только отсутствующих ключей; expected_updated_at=None;
  --dry-run). Overrides: 14 × множитель (скрипт; 2 ключа с Settings=None — SKIP: см. отчёт).
- **Скрипты/отчёты**: plans/reports/round10.4_review_fixes.md — отчёт ревью-фиксов Builder.

## Round 10.5 map additions (tma-relume-redesign, HEAD 0bdf272 + working tree)

- **Каталог**: `services/param_catalog.py` += `_MODELS_PG_ONLY` (4 PG-only записи:
  `models.groq_base_url`, `models.groq_transcribe_model`, `models.openrouter_base_url`,
  `models.openrouter_transcribe_model`; group `models_extra_providers`, `settings_field=None`,
  `code_source` = код-литерал). Итог: **REGISTRY 387 / GROUPS 74 / Settings 359**.
  Сид в PG — `pg_db._seed_settings` (resolve_code_source → `INSERT … ON CONFLICT DO NOTHING`,
  safe migration: существующие keys.* не перезатрёт).
- **Key-availability (B1/OD8/OD12/OD19)**: новый `services/key_history.py` — `KeyHistory`
  (in-memory `deque(maxlen=288)`, 5-мин слот, персист `var/status_key_history.json`,
  атомарный `tmp`+`os.replace`, права 0o600/0o700, allowlist `module_id/provider/model/
  samples{ts,ok,http_status}`). Singleton `services.status_service.key_history`.
  `status_service.llm_registry()` += `module_id/module_title/model_source`; `_build_llm_card`
  → `key_history.record(...)`; `build_snapshot` → `key_history.maybe_save()` (1/5 мин).
  API: `GET /api/status/key-history` (any TMA user) → `key_history.api_payload()`.
  `conftest.py` — M6: `STATUS_KEY_HISTORY_FILE` → temp (тесты не пишут в `var/`).
- **Data-driven модели (OD11/OD16)**: `groq_transcriber`/`openrouter_transcriber`/
  `video_cascade_client` читают `models.*_base_url`/`models.*_transcribe_model` через
  `hot.get(pg_key, <прежний литерал>)`; клиенты инвалидируются и по смене base_url
  (`_client_base`). Литералы — документированный дефолт (safe migration).
- **Rename/Delete ролей (OD15)**: `web/api/routes.py` — `DELETE /api/roles/{name}`,
  `POST /api/roles/{name}/rename` (superuser→403, builtin→409, занятая/wildcard→409);
  `services/config_cache.py` — `rename_role` (транзакция: INSERT SELECT + UPDATE bot_admins
  + scrub + DELETE), `role_usage`, `_scrub_param_permissions` (DML-only, ноль DDL).
  `get_roles` += `role_type`. UI: `canEditRole`/`isSuperuserRole`/`renameRole`/`deleteRole`.
- **Матрица ролей (OD10)**: `web/api/access.py::param_permissions_list` +=
  `tab/tab_title/group/group_title/group_order/category/title/secret`; UI
  `loadMatrix/matrixSections` (секция = config-вкладка `TAB_SECTION_ORDER`, группы по
  `group_order`, read/write `user/moderator/local_admin`). Только global admin.
- **Hash-роутер + navbar/hub (OD1/OD13/T-1099/T-1100)**: `web/app.js` — `ROUTE_TO_TAB`/
  `TAB_TO_ROUTE`/`ROUTE_PARENT`/`ROOT_ROUTES`/`HUBS`/`NAV_ITEMS` (6 пунктов эталона),
  `normalizeRoute` (только `#/`), `initialRoute` (`#/`→sessionStorage→`#/`),
  `hashchange` — единственный применитель, `applyRoute` (hub-aware RBAC), `goBack`
  (по parent, без history.back), `initBackButton` (`BackButton.onClick` 1 раз, guard
  Bot API 6.1+), `syncBackButton` (depth>0 → show). `__TMA_BACK__=true`, `__TMA_DEEPLINK__=false`.
- **Scope-switcher (OD7/T-1127)**: `scopeKind/scopeLabel/scopeOptions/scopeTrigger*`,
  `toggleScope/scopeMove/scopePickFocused/pickScope/isScopeSelected/ensureScopeAvatars`;
  `setActiveChat` += `scopeEpoch++` + сброс chat-scoped состояния + relations-reload.
  Все chat-scoped загрузчики — `_scopeGuard(epoch)` в success/catch/finally (R1/R2/R3).
- **Дизайн-токены (OD4/OD5)**: `web/index.html` — токен-слой (`--surface-*`, `--teal-500`
  и пр.), `@property --grad-angle inherits:false`, `grad-spin`/`grad-drift`,
  `prefers-reduced-motion`/`prefers-contrast`; удалён hardcode `#8b5cf6/#3b82f6/#2b2b40`.
  `@font-face` Material Symbols Rounded (субсет `web/static/fonts/material-symbols-rounded.woff2`
  13 428 B + LICENSE); `app.js ICONS` — 26 PUA-кодов (сверено с код-каноном и cmap субсета).
  Self-host `web/static/vendor/dompurify-3.4.15.min.js`; `sanitizeHtml` fail-CLOSED.
  `web/app.py` монтирует `/static` (`CacheControlStaticFiles`, RuntimeError-guard).
- **Гигиена**: `.gitignore` += `relumesite_example/`, `MaterialSymbolsRounded*.woff2`,
  `var/`, `build/`; `scripts/build_font_subset.py` + `scripts/requirements-font.txt`
  (build-time only, `fonttools`/`brotli` НЕ в runtime).
- **Отчёты**: `plans/reports/round10.5_scanner_audit.md` (0 блокеров / 0 major,
  2 minor + 5 info); `full_audit_results.md` §Round 10.5; `audit_backlog.md` (10.5).

## Round 10.6 map additions (tma-ia-modules-rework, HEAD be7b85b + working tree)

- **Каталог**: `services/param_catalog.py` — REGISTRY **392** / GROUPS **91** /
  Settings **364** / mapped **89**; `TAB_RULES` (19 вкладок) + `CONFIG_TAB_TITLES` (19) +
  `_TAB_BY_GROUP` (89). Расщепления: `limits_media`→`limits_media_permsoc`(7)+
  `limits_transcribe`(6)+`limits_video_summary`(3)+`limits_media_download`(1);
  `limits_persons`→`limits_alan`(3)+`limits_kostik`(1); `limits_youtube_web`→
  `limits_youtube`(2)+`limits_web`(2); `limits_cooldowns`→0; `flags_modules`→7 групп
  (`flags_module_*`, checkup→`flags_service`); `flags_chat_behavior`→7 + `flags_summary` +
  `flags_permsoc_behavior`; `reactions_persons`→2 + `reactions_alan`(3) + `reactions_kostik`(1);
  `limits_chat_budgets`→10 (flags+9), `limits_chat`→25; NEW `limits_rag`(2)→`memory_rag`.
  5 NEW master-флагов: `FACTCHECK_ENABLED`/`SEARCH_ENABLED`/`VIDEO_SUMMARY_ENABLED`/
  `WEBPAGE_ENABLED`/`CHECKUP_ENABLED` (default True; `_FLAGS`). PG-ключи/значения НЕ мигрируют.
- **Runtime-гейты (A1)**: `handlers/factcheck.py:169`, `search.py:109`, `web.py:104`,
  `checkup.py:77` — `hot.get("flags.*_enabled", settings.*)` → `UNHANDLED`;
  `youtube.py:1019` — только `request.mode == "summary"` (transcript продолжает работать).
  `bot.py` порядок роутеров НЕ тронут; `services/database.py`/`pg_db.py` без диффа
  (SQLite v8, ноль PG-DDL; seed новых флагов = `true` через `_seed_settings`).
- **`POST /api/llm/test` (T-1210/A4/D4)**: `web/api/routes.py:1225` (`LlmTestRequest:126`),
  `requires_global_admin`, rate-limit `(user,block)` ≥5с → 429, TTL-прунинг `_LLM_TEST_LAST`;
  `reset_llm_test_rate_limit()` — тест-точка. Логика — `services/llm_probe.py`:
  `_safe_base` (https/loopback-http), `sanitize_error` (R17), `KNOWN_BLOCKS`
  (`direct_main/direct_fallback/transcribe_groq/transcribe_openrouter/
  video_summary_openrouter/embeddings/search_keys[:tavily|:exa]/media_share/
  checkup_betterstack`; `llm_guard` намеренно отсутствует), `_probe_search`
  (Exa/Tavily фиксированные endpoints).
- **TMA-каркас**: `web/app.js` — `MODULES` (11: self-flag `toggleKey` + `tab`),
  `PROVIDER_BLOCKS` (9 блоков по модулям; `testable:false` у `embeddings`/`llm_guard`;
  `perFieldTest` у `search_keys`), `accessOpen ∈ {null,'roles','local','admins'}` +
  `setAccess`, `activeModule/activeModuleGroups/_syntheticGroup('content','content_media')`,
  `openModuleWindow/closeModule/_ensureModuleData` (Сон/Ностальгия-панели в модалке),
  глобальный Esc (`_onKeydown`), `ROUTE_ALIAS` (legacy hash → канон через `replaceState`),
  `TAB_SECTION_ORDER` 19, `TAB_TO_ROUTE`/`ROUTE_TO_TAB` без удалённых роутов;
  `NAV_ITEMS` 6, `iconGlyph` Material. `web/index.html` — sidebar/☰/MENU_ORDER удалены,
  `.navbar-band`/`.nav-label`, `.app-shell`/`.scroll-area`/`.fullscreen-mode`,
  модуль-карточки + модалка, prov-блоки + test-кнопка, аккордеон `acc-*`,
  `#/how` и матрица — Material-иконки. DM `canEditConfig` учитывает `per_chat===false`
  (R10.5-2 closed); `initBackButton` на `ready` (R10.5-1 closed).
- **PERMsoc**: 10 миселённых ключей → М5(6)/М6(3)/М7(1); Леха=Леха (`reactions_alan`+
  `limits_alan`), Костик (`reactions_kostik`+`limits_kostik`) — раздельно; `flags_media`
  остаётся в PERMsoc. `keys_youtube`→М6; `models_checkup`/`keys_betterstack`→М9.
- **Находки**: `plans/reports/round10.6_scanner_audit.md` (0 блокеров/0 major;
  3 minor: R10.6-1 LLM-дубль редакторов, R10.6-2 https-SSRF, R10.6-3 422-эхо `api_key`;
  3 info).

## Round 10.7 map additions (admin-ui-bugfixes-round107, HEAD 2ccf558 + working tree)

- **TMA scope-производные (1a)**: `web/app.js` — 6 `scope*` (`scopeKind/scopeLabel/
  scopeOptions/scopeTriggerTitle/scopeTriggerInitial/scopeTriggerAvatar`) перенесены из
  `methods` (~:1313-1371) в `computed` (`:914-974`). Потребители — только property-доступ
  (`{{ scopeLabel }}`, `scopeOptions.length`, `scopeOptions[i]` в `scopeMove`
  `:2097`/`scopePickFocused` `:2103`); вызовов `()` нет. Исправляет рендер
  `function () { [native code] }` и клавиатурную scope-навигацию. `scopeEpoch`-гварды не тронуты.
- **CSS шапки/навбара (`web/index.html`)**: `header.header-sticky` (0,1,1) + horizontal
  `env(safe-area-inset-left/right)` (1b); компактный user block `w-6/gap-1.5/text-xs/
  max-w-[7rem]` (1c); `.nav-label` `word-break:keep-all` + `-webkit-line-clamp:2` +
  `text-overflow:ellipsis` + `0.625rem` (1d); scoped `.keys-avail .avail-list`
  `table-layout:fixed` + ширины 34/18/30/8/10% + ellipsis + `:title` (2a); `.clipboard-ghost`
  `opacity:0` + `contain:strict` (без `visibility:hidden`) (3a); `.log-level/.log-ts/.log-logger/
  .log-msg` + `.log-panel .log-code` (3b); `.log-copied` (3c).
- **Логи (`web/app.js`)**: `fmtLogTime` (`:3285`) HH:MM:SS (полный ts — в `:title` через
  `fmtLogTs`); `copyText` — `focus({preventScroll:true})`, `execCommand` по boolean,
  `ta.remove()`+обнуление `window.__adminbotClipGhost` в `finally` (`:3309-3342`);
  `copyLogRow(log,i)` + `copiedIndex`/`copiedTimer` 800 мс + `.log-copied` (`:3344-3353`);
  `copyAllLogs` — `self.logText(l)`.
- **ICONS (R106-5)**: удалены 6 мёртвых ключей (`account_balance_wallet/stop_circle/
  theater_comedy/toggle_off/toggle_on/speed`); осталось 20; независимая проверка `fontTools`
  — все 20 PUA-кодов в cmap субсета (26 глифов), ребилд шрифта не нужен. `test_font_subset`
  теперь проверяет `\ue887` (`help`).
- **Uptime (2b, `services/status_service.py`)**: `_bucketize` (`:260-301`) — непрерывная
  5-мин сетка от `min(buckets)` до `now_slot` включительно; пустые слоты `status="down"`
  (нет heartbeat ⇒ простой); `[]` при пустых rows; `ts < since` отсекается; `[-288:]`.
  `build_snapshot` → `last_heartbeat` = ts последнего `up`-бакета, иначе `None`
  (`:376-378`). `uptime_heartbeat.py:26` не тронут (пишет только `'up'`; down деривится).
  Фронт `renderUptimeChart` не менялся (`down→0`, `spanGaps:false`).
- **Находки 10.7**: `plans/reports/round10.7_scanner_audit.md` (0 блокеров/0 major;
  1 minor: R10.7-1 граничный ложный `down`/`last_heartbeat` до ~60 с после 5-мин границы;
  3 info: R10.7-2 `[-288:]` может отсечь единственный ранний `up`; R10.7-3 `copiedTimer`
  не чистится при смене вкладки; R10.7-4 `test_font_subset` не сверяет cmap WOFF2).
  R10.6-5 закрыт; R10.6-1/2/3 открыты (кандидаты 10.8).

## Round 10.8 map additions (admin-ui-round108, HEAD 636a75d + working tree)

- **Имена разделов (видимые подписи, route-ключи НЕ менялись)**: `NAV_ITEMS`/`TABS`/`HUBS`
  (`#/how`→«Справка», `#/ai`→«ИИ», `#/permsoc`→«PERMsoc», `#/access`→«Доступы»,
  `#/oversight`→«Сводка»); каталог-группа `flags_permsoc` («Функции PERMsoc: рубильники»)
  НЕ переименована.
- **Иконки/субсет (ADR-002)**: `web/app.js ICONS` **37** (20 базовых + 17 новых 10.8;
  6 мёртвых 10.7 удалены) == `scripts/build_font_subset.py ICON_NAMES` (37). PUA —
  из GSUB reverse-cmap (`build/icon_codepoints.json`). Маркер идемпотентности =
  `sha256(src_sha + "|" + ",".join(ICON_NAMES))` (`_marker_key`). Субсет
  `web/static/fonts/material-symbols-rounded.woff2` 18 388 B, cmap = ровно 37 PUA-кодов.
  `test_font_subset`: Test A (паритет), Test B (cmap через `fontTools`), C (нет
  pictographic-emoji в `web/`), D (6 мёртвых имён) — **R10.7-4 закрыт**.
- **Логи (`web/app.js`/`web/index.html`)**: блочная раскладка — `div.log-code` →
  `div.log-row` → `div.log-head` (flex-wrap) + `div.log-msg` (width:100%, pre-wrap,
  overflow-wrap:anywhere); жёсткие `.log-level{min-width:4.5rem}`/`.log-ts{width:8ch}`/
  `.log-logger{max-width:8rem}` и Tailwind `break-all` удалены; toggle — Material
  `chevron_right`/`expand_more` ТОЛЬКО при `log.exc_text` (иначе `log-toggle-spacer`),
  `@click.stop`, `:aria-expanded`; `fmtLogTime` = `DD.MM HH:MM:SS` (`fmtLogTs` — `:title`);
  `setTab` чистит `copiedTimer`/`copiedIndex` (**R10.7-3 закрыт**). Контракт `/api/logs`,
  `logText`/`copyAllLogs`/ghost-fallback — без изменений.
- **«Доступы» (ADR-001)**: `accessOpen ∈ {null,'roles','local','admins'}` — производная hash
  в `applyRoute` (`route.indexOf('#/access/')===0 ? substring : null`; не-access маршрут
  обнуляет → нет stale-окна). `openAccessWindow(id)`/`closeAccessWindow()` (`setAccess`
  удалён), `isAccessOpen` сохранён. Разметка: 3 `hub-card`-плитки + 3 взаимоисключающих
  `modal-backdrop` (роли/локальные/роли-назначения), id `sec-roles/sec-matrix/sec-local/
  sec-admins` сохранены; `#/access` — hub-карточки без `section`; `ROUTE_PARENT`
  `#/access/*`→`#/access` (BackButton/`goBack`), RBAC (`canViewTab`, `isGlobalAdmin`,
  `canEditRole`) сохранён. «Администраторы»→«Роли».
- **Шапка**: внешний дубль GLOBAL-бейджа удалён; `{{ scopeLabel }}` — ровно 1 раз внутри
  trigger; computed `scopeLabel`/`isChatContext()` сохранены.
- **README**: «Самое важное для пользователя» + «Управление и деплой» наверх; changelog
  10.3–10.8 под единственным `<details>`; шапка v2.52.0 / 5073 / раунд 10.8.
- **Находки 10.8**: `plans/reports/round10.8_scanner_audit.md` (0 блокеров/0 major;
  2 minor: R10.8-1 Esc не закрывает access-окна при фокусе вне модалки; R10.8-5
  `APP_VERSION`=2.51.0 vs README v2.52.0 (`/api/status`) + `@font-face`-URL не версионирован,
  `.woff2` `max-age=86400` → старый субсет в кэше до 24 ч → tofu новых иконок; 3 info:
  R10.8-2 stale-комментарий `section`/осиротевшая ветка `openHubCard`; R10.8-3 мёртвый
  `TABS.icon`/`visibleTabs`/`tabMat` (pre-existing); R10.8-4 backlog-статус «ПЛАНИРОВАНИЕ»).
- **Открыто** (кандидаты 10.9): R10.7-1/-2 (`services/status_service.py` gap-fill);
  R10.6-1 (дубль generic-рендера `llm_providers`); R10.6-2/-3 (SSRF/422-эхо `api_key`).

## Round 10.9 map additions (admin-ui-round109, HEAD 51f308b + working tree)

- **PERMsoc owner-блоки (ADR-109-4)**: `web/app.js PERMSOC_OWNER_BLOCKS` — 4 блока
  (`slavik`/`olya`/`mimic`/`common`); один тумблер в `<summary>` (`PERMSOC_TOGGLE_KEYS`
  исключает 4 флага из тела). Принадлежность: `key∈owner.keys` → `group∈owner.groups &&
  key∉∪owner.keys` → `common`. Backend: новый `SLAVIK_ENABLED` (default **True**) +
  `PermsocModule("slavik", …, sub_flag_key="flags.slavik_enabled")` +
  `DEFAULT_SUB_FLAGS[...] = True`. `reactions_persons` удалена (GROUP 91→90),
  `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`. Переключение:
  `toggleOwner` (common+чат → `togglePermsoc`/`gates.permsoc`; иначе `saveConfigItem`).
  Сводка 5 модулей (`permsocModuleBadge`) переехала внутрь «Общего».
- **Скролл (п.3)**: `web/app.js _preserveScroll(fn)` — снимок/restore
  `document.scrollingElement` **и** `main.scroll-area` (fullscreen TMA) в `$nextTick`;
  обёрнуты все save-пути. `web/index.html`: спиннер только при
  `configLoading && !configItems.length` (ре-фетч не подменяет карточки). `setTab`-сброс вверх не тронут.
- **Одностраничный dashboard/health (ADR-109-3)**: `web/index.html` — ОДИН блок
  «Доступность ключей» (`llmGroups` из `/api/status.llm` по `group_id`): 4 группы
  (`llm_functions`/`transcription`/`video_summary`/`embeddings`). `status_service.llm_registry`
  отдаёт `module_id/module_title/group_*/display_name/provider=host(base_url)/model/key/
  latency_key/kind`; `_check_health(module_id,…)` → `llm_probe.probe_openai`:
  `kind="chat"` `/chat/completions`, `"embeddings"` `/embeddings`, `"stt"` (только `stt_groq`)
  `/audio/transcriptions` (multipart, `_silent_wav`); таймаут 5с; кэш по `module_id`
  (2xx 60с / ошибки 10с, stale-200 нет); статусы `ok|error|timeout|unreachable|not_configured`.
  `stt_openrouter` — `kind="chat"` (input_audio через `chat.completions`). Старый блок
  переименован в «История доступности ключей».
- **Кастомные имена моделей (ADR-109-1)**: 7 `ParamSpec` `models.*_display_name` (+Settings)
  — первое поле каждого provider-блока (`PROVIDER_BLOCKS`), глобальные; питают dashboard
  через `_display()`. REGISTRY 392→400, Settings 364→372.
- **«Тяжёлые фичи» (п.5) / «Бюджет фона» (п.6, ADR-109-5)**: карточки с «Модулей» удалены;
  per-chat `dream/nostalgia/lore_auto` — только в «Сводке» (модалка → `toggleKillswitch`);
  «Бюджет фона (день)» — полоса в `#/oversight`, источник `loadBudgetInfo()` из `loadOversight`.
  Backend `worker_budget.py`/endpoint без изменений.
- **Итоговые инварианты 10.9**: REGISTRY **400** / GROUPS **90** / Settings **372** /
  mapped **88** / TAB_RULES **19** / CONFIG_TAB_TITLES **19**.
- **Находки 10.9**: `plans/reports/round10.9_scanner_audit.md` (0 блокеров/0 major/0 medium;
  3 low: R10.9-1 `model_source` запасных записей снова «code»; R10.9-2 `EMBEDDING_FALLBACK_*`
  из settings + display-name исчезает без env-ключа; R10.9-3 stale docstring `status_service`;
  3 info: R10.9-4 health-кэш по `module_id`; R10.9-5 doc `_LLM_BLOCKS`/`ConnectTimeout`;
  R10.9-6 backlog-статус).
## Round 10.10 map additions (admin-ui-round1010, HEAD da85b60 + working tree)

- **Fullscreen-шапка (п.1, CSS-only)**: `web/index.html` — новое правило
  `.fullscreen-mode header.header-sticky { padding-{top,right,left}: calc(base + max(env(safe-area-inset-*),
  var(--tg-content-safe-area-inset-*), var(--tg-safe-area-inset-*))) }` (Bot API 8.0 device/content
  safe-area CSS-переменные). Специфичность `(0,2,1)` перекрывает Tailwind `px-4 py-3` и `@media`.
  10.7 (горизонтальный env-safe-area) и 10.9 (`.fullscreen-mode .scroll-area`) не тронуты; JS не менялся.
- **Mobile key-chart (п.2, render-only)**: `web/app.js` — константы `SAMPLE_BUCKET=300` (==
  `services/key_history.SAMPLE_BUCKET_SECONDS`) и `MIN_BUCKETS=12`; чистая `keyHistoryChartModel(providers)`
  (дорожки `lane+0.75/0.25`, `y.max=laneCount+0.2`, временная сетка от `endBucket` с cap
  `MAX_HISTORY_POINTS` и полом `MIN_BUCKETS`, пропуск=null, `pointRadius:3` при ≤1 сэмпле,
  `height=max(120,44+lanes*22)`); `renderKeyHistoryChart` → `maintainAspectRatio:false` + `$nextTick`;
  реактивное `keyHistoryChartHeight` биндится на обёртку `.keys-chart` (`web/index.html`).
  Контракт `GET /api/status/key-history` (`api_payload`) НЕ изменён.
- **«Провайдеры» (п.3)**: `web/index.html` — `:value="blockFieldValue(f)"` + `@input` вместо
  `v-model="blockDrafts[f.key]"`; `web/app.js` — `blockFieldValue` возвращает `''` для пустого
  черновика (не откат), `blockDrafts`/`blockResults` сбрасываются в `loadConfig` (success) и
  `setActiveChat`; `saveBlock`/MINOR-3 (`null`=не трогать, `''`=очистить) без изменений.
- **DM heavy-modules OFF (п.4, DATA)**: `services/chat_params.py` — единые константы
  `_DM_DISABLED_GATES={"dream":False,"nostalgia":False}` и `_DM_DISABLED_OVERRIDES={memory.dream_enabled,
  memory.nostalgia_enabled, flags.summary_enabled, flags.chat_running_summary_enabled}`;
  `ensure_scope_profile(dm=True)` вставляет v-1-лейаут с этими дефолтами (INSERT ON CONFLICT, 0 DDL).
  Новый `scripts/disable_dm_heavy_modules.py` — dry-run (default)/`--apply`/`--chat-id`/`--snapshot-out`/
  `--restore`; raw `SELECT ... chat_profiles WHERE chat_id>0 AND is_active ORDER BY chat_id`; запись
  только через `set_chat_params` (merged overrides/gates, namespace-replace); snapshot только
  overrides/gates до записи (abort при ошибке), пустой патч = no-op (идемпотентность), `--restore`
  не трогает `meta`; partial-failure → exit 1. Групповой путь и `bot.py` (F-14) не тронуты.
- **«Роли»: enrichment (п.5)**: `web/api/avatars.py` — новый `global_user_display_info(user_id)`
  (`bot.get_chat(user_id)` → first/last → username без `@`; фото через общий `_user_photo_cache` +
  `getUserProfilePhotos(limit=1)`; RAM-TTL 1ч (`_user_name_cache`), fail-open; транзиентные
  `TelegramRetryAfter`/`TelegramNetworkError` НЕ негатив-кэшируются — паттерн BUG-4). `web/api/routes.py`
  `GET /api/admins` (`requires_permission("access")`) — обогащение КОПИЙ строк (`dict(a)`) через
  `asyncio.gather`+`Semaphore(5)`, поля `display_name`/`photo_file_id`, старые поля сохранены.
  Фронт `web/app.js` — `loadAdmins` грузит blob-аватары (`loadAvatar('user', id, admin)`), `adminInitial`;
  `web/index.html` — аватар/инициал + `display_name||username`, ID `text-[10px] text-gray-500 font-mono`,
  селектор `w-24`, ID-инпут `flex-1 min-w-0`, кнопка `shrink-0`.
- **Инварианты 10.10**: REGISTRY **400** / GROUPS **90** / Settings **372** / mapped **88** /
  TAB_RULES **19** / CONFIG_TAB_TITLES **19**; ноль PG-DDL; SQLite **v8**; `bot.py`/`media/`/`.env`
  не тронуты; секретов нет; Headroom в коде отсутствует (п.6 out of scope).
- **Находки 10.10**: `plans/reports/round10.10_scanner_audit.md` (0 blocker/0 high/0 medium;
  3 low: R10.10-1 staged-отчёт скрипта, R10.10-2 `meta.note` вне snapshot, R10.10-3 chart-return
  без destroy; 2 info: R10.10-4 аватары админов, R10.10-5 дубль `adminInitial`).

## Round 10.11 map additions (llm-providers-refactor-round1011, HEAD ec5dd1f + working tree)

- **Каталог-Δ (ADR-1011-2)**: `services/param_catalog.py` — 4 embed-фоллбэк-записи переведены
  из `_INFRA` (category=None) в first-class: `models.embedding_fallback_base_url` /
  `models.embedding_fallback_model` (category `models`, group `models_embeddings`),
  `keys.embedding_fallback_api_key` / `keys.embedding_fallback_api_key_2` (category `keys`,
  group `keys_llm`, `secret=True`). `EMBEDDING_FALLBACK_TIMEOUT_SECONDS`/`_MAX_RETRIES` остались
  infra. Инварианты: REGISTRY **400** / GROUPS **90** / Settings **372** / mapped **88** /
  TAB_RULES **19**; categorized **372→376**, infra **28→24** (models 42 / keys 15). Обязательный
  деплой-шаг — идемпотентный `scripts/migrate_env_to_pg.py --only-category models,keys` (DML,
  `ON CONFLICT DO NOTHING`), до него «Проверить» работает через settings-дефолт.
- **Сохранённый ключ в probe (ADR-1011-1)**: `services/llm_probe.py` — карта
  `_BLOCK_SAVED_KEY` (block→pg_key для direct/transcribe/video/embeddings/search_keys/media_share),
  `_saved_api_key(block)` = `hot.get(pg_key, settings_default)`; в `probe_block` резолв только
  при пустом/пробельном `api_key` (явный draft приоритетнее). Резолв внутренний (R17: сырой ключ
  не эхо/не логируется); UI `web/app.js` — `blockFieldConfigured`/`last4ByKey` + hint
  «Ключ сохранён (••••last4)», `:value="blockFieldValue(f)"` (секреты не префиллятся).
  `video_fallback`/`embeddings_main`/`_fallback1`/`_fallback2` добавлены в
  `KNOWN_BLOCKS`/`_EMBEDDING_BLOCKS` (kind=`embeddings`).
- **Read-path embed-фоллбэка**: `services/llm_client.py:293-309` и
  `services/status_service.py:257-287` читают 4 записи через `hot.get` с прежними
  settings-дефолтами (паритет без кэша). `VIDEO_FALLBACK_MODEL` — каталожный code-default.
- **UI «LLM Провайдеры» (2.2–2.5)**: `web/app.js` — computed `providerConnectionBlocks`
  (zone≠advanced) / `providerAdvancedBlocks` (zone=advanced) в секции `computed:`; блок
  `video_fallback` сразу под `video_summary_openrouter`; `embeddings.subBlocks` = ровно 3
  (main/f1/f2, у каждого Base URL+Модель+Ключ+«Проверить»); `llm_guard`/`search_keys`/
  `media_share` → `zone:'advanced'`; `providerCoveredKeys` рекурсивно покрывает subBlocks.
  `web/index.html` — зона «Подключения» сверху, `<component :is=details/div>` + `<summary>`
  «Расширенные настройки» внизу (generic-группы внутри), subBlocks-рендер, key-hint,
  nav-icon 22px/центрированные hub-сетки (`max-width:64rem`), профиль `shrink-0`.
- **Chart key-history (ADR-1011-3)**: `web/app.js` `keyHistoryChartModel` — точки
  `{x: bucket*1000, y: lane|null}`, поля `xMin`/`xMax`; dataset `spanGaps:true` + `stepped:true`;
  `renderKeyHistoryChart` — `parsing:false`, X `type:'linear'` c min/max и `ticks.callback`
  HH:MM (без chartjs-adapter). Серверный контракт `api_payload`/`services/key_history.py`
  НЕ изменён.
- **Инварианты 10.11**: **ноль новых PG-DDL**; SQLite **v8**; `bot.py` router order и `media/`/
  `.env` не тронуты; секреты не коммитятся; **Headroom-ссылок в коде нет**; тесты — pytest 5168/0,
  `node --check`/`JS-UNIT-OK`/`git diff --check` чисты.
- **Находки 10.11**: `plans/reports/round10.11_scanner_audit.md` (0 blocker/0 high/0 medium;
  3 low: R10.11-1 nested `<details>` делят localStorage-ключ, R10.11-2 `embedding_fallback_model`
  status vs runtime, R10.11-3 устаревшие `.env`-подсказки; 3 info: R10.11-4 probe+caller base_url,
  R10.11-5 мёртвый `destroy`, R10.11-6 нет headless Chart.js-теста).

## Round 10.12 map additions (providers-kostik-round1012, HEAD 32d1aa9 + working tree)

- **Embed/direct decoupling (ADR-1012-1 D1 + OD-1)**: `config/settings.py` — `LLM_BASE_URL` code-default
  `https://nano-gpt.com/api/v1`; новые `EMBEDDING_BASE_URL` (`https://apinet.cloud/v1`) и
  `EMBEDDING_API_KEY` (`""`); новые каталог-ключи `models.embedding_base_url` (models/`models_embeddings`),
  `keys.embedding_api_key` (keys/`keys_llm`, secret). `services/llm_client.py` — `LLMClient.__init__`
  принимает `embed_base_url`/`embed_api_key`; `_embed_base_url` (пусто → chat-base), `_embed_api_key`,
  `_current_embed_api_key()` (hot → captured → `_current_api_key()`); `embed()` → `_post(base_url=_embed_base_url,
  channel="embed")`; отдельный httpx-кэш `_embed_client`/`_get_embed_client` (закрытие в `close()`);
  chat-путь/ретраи/fallback-каскад `EMBEDDING_FALLBACK_*` не тронуты. `bot.py` — 4/4 точки DI
  (`:316,491,525,557`), router order не тронут. `services/status_service.py` — `emb_base` из
  `models.embedding_base_url`, `emb_key` = embed-ключ `or` llm-ключ; `emb_main` больше не алиасит `main_base`;
  `stt_openrouter` → новый `models.openrouter_transcribe_display_name` (видео остаётся на
  `models.openrouter_display_name`). `services/llm_probe.py` — `_BLOCK_SAVED_KEY` primary-embed →
  `keys.embedding_api_key`, `_saved_api_key` зеркалит runtime-фолбэк на `keys.llm_api_key` (Google-фоллбэки нет).
- **422 global-save fix (ADR-1012-1 D2)**: `web/app.js` `api()` поддержал `options.global === true` →
  без `X-Chat-Id` (флаг не утекает в `fetch`); `saveBlock`/`saveConfigItem` для `per_chat=false` шлют
  global-ветку (`updated_at:null`), смешанный блок → 2 последовательных запроса. Серверный гейт
  `web/api/routes.py:414-417` и DM read-only (`canEditConfig`, R10.5-2) НЕ ослаблены (routes.py вне диффа);
  global-путь проверяет права сервером. **Известный неполный путь: `saveKeyItem` (`web/app.js:3092-3112`)
  не переведён** → см. R10.12-1.
- **Merged provider-блоки + подпись (ADR-1012-1 §2)**: `web/app.js` `PROVIDER_BLOCKS` — 4 parent-блока
  `direct`/`transcription`/`video_summary`/`embeddings` с `subBlocks` (id'ы `direct_main`/`direct_fallback`/
  `transcribe_groq`/`transcribe_openrouter`/`video_summary_openrouter`/`video_fallback` сохранены);
  `blockDisplayName(x)` = значение первого поля `role==='' && *display_name`, иначе `x.modules`;
  `providerCoveredKeys` рекурсивно покрывает новые ключи; `web/index.html` — `{{ blockDisplayName(b) }}` /
  `{{ blockDisplayName(sb) }}`, advanced = `modules`; STT/summary свопа нет.
- **Kostik reply-list (ADR-1012-1 D3/D4)**: `config/settings.py` `DEFAULT_KOSTIK_REPLIES` (14 фраз) +
  `KOSTIK_REPLIES`/`KOSTIK_ENABLED`; каталог `reactions.kostik_replies` (json/widget=`list`/per_chat true),
  `flags.kostik_enabled` (flags/`flags_permsoc`, default True); `services/permsoc.py` —
  `PermsocModule('kostik').sub_flag_key = "flags.kostik_enabled"` + `DEFAULT_SUB_FLAGS` True;
  `handlers/kostik.py` — литерал удалён, `hot.get("reactions.kostik_replies", settings.KOSTIK_REPLIES)` +
  `_resolve_replies` (list/tuple/JSON/мусор → непустые str), пустой список → молчание; alias `KOSTIK_REPLIES`
  сохранён; owner-блок «Костик» (ID + фразы + вероятность `limits.kostik_reply_probability`) + виджет
  `list-editor` (`web/app.js:4915-4968`, `web/index.html:3176-3206`, обе generic-ветки desktop/compact).
- **Инварианты 10.12**: REGISTRY **405** / GROUPS **90** / Settings **377** / mapped **88** / TAB_RULES **19** /
  categorized **381**; **ноль новых PG-DDL**; SQLite **v8**; `bot.py` router order, `media/`, `.env`
  не тронуты; секретов нет; **Headroom-ссылок в коде нет**; тесты — pytest 5210/0, `node --check`/
  `JS-UNIT-OK`/`git diff --check` чисты.
- **Находки 10.12**: `plans/reports/round10.12_scanner_audit.md` (0 blocker/0 high/0 medium; 2 low:
  R10.12-1 `saveKeyItem` не переведён на global-save, R10.12-5 дубль title/modules у parent-блоков;
  3 info: R10.12-2 stale docstring `llm_probe`, R10.12-3 `KOSTIK_ENABLED` вне `.env.example`,
  R10.12-4 index-key в `list-editor`).
- **Когнитивный слой 10.13 (F1–F8) — сквозные связи readonly-слоя.** Данные-центр: `graph_facts`
  (`kind` ∈ 'fact'/'belief'; `status` без CHECK: `confirmed`/`archived_belief`/`chat_meme`;
  `belief_meta` JSON: `base_weight`, `type='paradigm'`, `dedup_key`, `archived_at`,
  `resurrections`, `last_reinforced_fact_id`/`meme`), `memory_dream_log.kind`
  (`run`/`distilled`/`skipped`/`error`/`window_skip`/`decay_run`/`deep_run`/`deep_skip`/`resurrect`).
  Декай-гейт — `memory_dream_log(kind='decay_run', chat_id=0)`; deep-гейт — `kind='deep_run'`;
  reboot-персистентность телеметрии контекста — НЕТ (`_PROCESS_ACCOUNTING` in-memory).
  Маркерные точки: `summary_memory._fact_prefix` (rax-author, **без escape_xml_text**),
  `_knn_graph_facts` (архив: penalty к score + resurrection), `graph_activation_facts` (архив → L1 при
  наличии связки 2–3 узлов), `dream_worker._maybe_deep_after_sleep`/`_deep_tick` (after_sleep/fixed),
  `LLMClient.generate_worker(role)` (history/background → intel_*), `lore_worker._classify_dossier`
  (мемы `chat_meme`), `direct_chat_service.build_persona_card` (блоки [Факты]/[Мемы]).
  Frontend/F5: `web/api/memory_agi.py` (`cognition/status`, `graph`, `stats`, `timeline`,
  `deep-sleep`, `health`), `web/app.js` (`loadCognition`/polling 15s с паузой hidden, vis-network
  lazy self-host, `_graphSignature` anti-rerender), `web/index.html` (EKG SVG + ленты).
- **Находки 10.13**: `plans/reports/round10.13_scanner_audit.md` (0 critical; **1 high** S10.13-1 —
  неэкранированный `target_user` в RAG-промпте; 4 medium: deep-sleep cooldown/кап обходятся на
  неуспешных прогонах, F2-decay включает F3-парадигмы, реаниматор не в телеметрии, F5-ленты
  убеждений/парадигм вне chat-scope; 9 low).
- **Сквозной паттерн (10.11→10.13): флаги «OFF = байт-в-байт» неполны.** При OFF изменения
  остаются в промпт-канонах (`lore_prompts` ироническая заметка безусловна) и в данных
  (архивные beliefs видны KNN-путём при выключенном `belief_decay_enabled`); аналогично
  probe «Проверить» не зеркалит runtime-фолбэк `generate_worker`.

## Round 10.14 map additions (самосознание и личность бота, HEAD 2edc65b + working tree)

- **Новый сквозной слой `bot_self_reply` (F1).** SQLite user_version **8→9** (`database.py:53-97,907-995`):
  `_migrate_self_origin_v9` — rebuild `graph_facts` (16 колонок 1:1, id сохранены → FTS5
  `content='graph_facts'` и vec0 `rowid=fact_id` валидны без пересоздания; guard по `'bot_self_reply' in sql`,
  `PRAGMA user_version=9` вне guard; 5 индексов v8 пересозданы; откат `UPDATE origin='bot_direct_reply'`).
  Origin-исключения self: `list_new_confirmed_facts`, `search_golden_facts_fts`, `get_live_graph_facts`,
  `find_exact_dup_groups`, `graph_stats.facts` (+ новый счётчик `bot_self_replies`), `_DREAM_SOURCE_ORIGINS`.
  RAG: `search_graph_facts_fts`/`_search_graph_facts`/`_knn_graph_facts`/`_vec_candidates`/`_filter_vec_rows`
  получили `include_self` (default False = невидим чужим пайплайнам; direct-путь `get_rag_facts(include_self=True)`).
  `memorize_self_reply` (вес `limits.graph_fact_weight_bot`, важность 2, `target_user=NULL`, TTL как direct) +
  LLM-экстрактор `services/self_reflection.py::extract_self_essence` (роль `reflection` → фоллбэк на main) +
  «честная» метка `_ORIGIN_LABELS['bot_self_reply']` и анти-эхо `_SELF_ECHO_INSTRUCTION` в `_build_rag_block`.
- **Persona-ядро (F2): PG-таблицы `personas`/`persona_traits` + singleton `persona_state`.** Scope
  first-class (`is_global`+`chat_id`, CHECK, partial-unique, FK `chat_profiles(chat_id)` ON DELETE CASCADE).
  `services/bot_persona.py` — резолв per-chat→global→empty (fail-open), `build_persona_prompt_block`
  (хвост system prompt; `is_aware_ai=false` → `_NO_AI_DISCLOSURE_BLOCK`), UPSERT/optimistic `updated_at` (409),
  `append_traits` (дедуп casefold + FIFO-cap `PERSONA_TRAITS_MAX`), in-memory name-cache для sync-триггера
  (`handlers/direct_chat.py:147-155`). API `GET/PUT/DELETE /api/persona` + `GET /api/persona/health`
  (`web/api/routes.py:1356-1530`). Каталог-Δ +1 (`flags.persona_enabled`, per_chat, default True).
  Трейты генерирует `dream_worker._run_persona_traits_once` (`PERSONA_EVOLUTION_PROMPT`/`build_persona_user`/
  `parse_persona_traits` в `dream_prompts.py`).
- **UI: special-screen «Личность» (#/ai/persona, вне TABS; `canViewTab`/`ROUTE_TO_TAB`/`ROUTE_PARENT`),
  3-я лента «Эволюция характера» (F4), метрики в «Сводке». TABS=19 не тронут.**
- **Гайд (F6): `content.intelligence_guide` (PG-only) + dedicated `GET/POST /api/info/guide` +
  Markdown-редактор/предпросмотр (`renderGuideMarkdown`→`sanitizeHtml`), self-host DOMPurify,
  идемпотентный сид `config_cache._seed_intelligence_guide` из `plans/docs/intelligence_user_guide.md`
  (абсолютный путь через `Path(__file__).parents[1]`).**
- **F8: третье выделенное подключение `intel_reflection`** (каталог `models.intel_reflection_*` /
  `keys.intel_reflection_api_key`, роль воркера `reflection` в `LLMClient._WORKER_ROLE_PREFIX`,
  probe `intel_reflection_main`, provider-блок в UI).
- **F5 (scope-audit): R10.9-4 инвалидация health-кэша** (`status_service.invalidate_health_cache`;
  `models.*`/`keys.*` → clear; вызовы в `_post_config_global`, BYOK put/delete) + `inventory.tsv` 411 строк.
- **F7:** порядок статус-карточек Сводка→Сердцебиение→Бот→Сервер→Мониторинг→Доступность→История.
- **Находки 10.14**: `plans/reports/round10.14_scanner_audit.md` — **0 Critical / 0 High / 2 Medium /
  5 Low / 2 Info**. Medium: R10.14-1 RBAC view/edit `edit_persona` (PUT global есть, GET global 403 →
  global-экран редактора недостижим, спека F2 §5 GET «auth TMA»); R10.14-2 traits-LLM не учитывается
  в `worker_budget`/deep-sleep-капе (спека F2 §3.4 п.5). НЕ блокируют шаг 7.
- **Сквозной паттерн (10.14): «двухканальные» dedicated-API со своим scope/RBAC нужно сверять
  view↔edit парой, а не по отдельности.** `_persona_can_edit` и `_persona_can_view` разошлись:
  write-путь мягче read-пути. Тот же класс — любые будущие special-screen API.

## Round 10.15 map additions (graph/sleep/nostalgia/tools, HEAD 798e044 + working tree, 9 фич F1–F9)

- **F6 — обязательный префикс (новый слой роутинга команд).** Новые модули:
  `services/command_registry.py` (канон `FUNCTIONAL_COMMANDS` 17 триггеров + `BARE_COMMANDS`
  `чекап`/`фактчек`; `_HEAD`/`_TAIL` word-boundaries; `group_of`/`matches_group`/
  `has_trigger_word`) и `services/command_prefix.py` (`active_name` ← sync-кэш
  `bot_persona.get_cached_global_name()` под гейтом `flags.persona_enabled`; `split_prefix`
  якорён к началу строки; `split_prefix_anywhere` = поиск префикса в любом месте +
  позиция токена для link-first; `functional_group`/`name_mentioned`). Триггер системы = непустое
  Имя (флага `command_prefix_enabled` НЕТ). Префиксные хендлеры 0d–0g/4e снимают префикс через
  `split_prefix`; youtube/web = `matches_group` ИЛИ (`has_trigger_word` + URL) ИЛИ link-first
  (`split_prefix_anywhere` + URL до обращения), иначе `UNHANDLED`; `direct_chat`
  (`_FUNCTIONAL_FLAGS`/`_functional_module_active`) сдаёт `UNHANDLED` только при активном воркере.
  **Итерация 2: R10.15-1/-3 закрыты**; **остаточные Low:** link-first привязан к первому вхождению
  имени (R10.15-10); «триггер anywhere + любой http-URL» консьюмит речь с не-media ссылкой
  (R10.15-11); yield по hot-флагу vs startup-регистрация 4e (R10.15-4, follow-up).
- **F1 — граф-выборка.** `database.graph_snapshot` переписан на CTE Degree Centrality
  (`re` UNION ALL индексированных выборок → `deg` GROUP BY → `seed` top-50 → `adj` 1-hop → `cand`)
  + очистка сирот + рёбра строго с обоими концами + `truncated`; `seed_nodes=50` (API-константа
  `GRAPH_SEED_NODES`). `graph_stats`/JSON-контракт/`degree` не тронуты.
- **F5 — оконная семантика бейджей.** `web/api/memory_agi.cognition_status` += `dream.active/
  active_until` и `deep_sleep.active/active_until` (хелперы `_local_hour`/`_in_hour_window`,
  wrap через полночь; `enabled=false` гасит активность — H1). Фронт `dreamPhaseBadge`/
  `deepPhaseBadge` («через/до/идёт/выключен»); статистика графа перенесена из «Модулей» в
  «Сводку» (без дубля), `loadCognitionStats` удалён; `.intel-header` медиа-столбик.
- **F3 — разблокировка Сна.** `dream_worker`: `_sleep_fallback_active` (нет `distilled` за 3 дня →
  пороги 2/8), детект раз на тик в `process_all` → `_process_chat(fallback_active=…)`,
  `[Sleep] … Skipped` на WARNING / `Passed` на INFO (видно в дефолтном фильтре логов).
- **F4 — ностальгия.** `nostalgia_prompts`: ревамп `NOSTALGIA_PROMPT` + `PREV_NOSTALGIA_PROMPT`-слепок;
  `build_nostalgia_user(year, golden, lore, memes)` (капы 600/10/120). `nostalgia_worker._llm_once`
  инжектит лор (`ChatLoreStore.get_profile`: manual→auto) и мемы (`db.list_chat_memes`), fail-open;
  окно «год назад» 2→10 (`NOSTALGIA_YEAR_BACK_DAYS_WINDOW`).
- **F8/F9 — tool-сет 7.** `services/tool_schemas.py` += `summarize_video`/`download_media`/
  `get_bot_health`/`get_recent_history`. `ToolDeps` += `video/downloader/health/db/download_cooldown`,
  `ToolContext` += `bot/reply_to_message_id/user_id`; `bot.py` прокидывает существующие инстансы.
  `_download_media` шлёт MP4 через новый `services/media_send.send_media` (success только после
  отправки) и применяет общий кулдаун 4e через lazy-провайдер `handlers.video_download.
  get_download_cooldown` (итерация 2, R10.15-9); `_get_bot_health` = путь 0g **под гейтом
  `flags.checkup_enabled`** (итерация 2, R10.15-2); `_get_recent_history` = depth
  (`database.get_recent_messages`) либо query (FTS + окно 12ч; fallback на `ctx.query` при пустых
  аргументах, R10.15-6), R17-логи только count/out_chars.
- **F7 — гайд.** Новый канон `DEFAULT_INFO_TEXT` ↔ `info_text.md` (байт-в-байт) под реестр F6;
  `PREV_DEFAULT_INFO_TEXT`-слепок + идемпотентная DML-миграция
  `config_cache._migrate_info_how_works_v1015` (перезапись только при точном совпадении со слепком;
  ручные правки → WARNING + пропуск). `PROMPT_MIGRATIONS` не тронут.
- **Находки 10.15:** `plans/reports/round10.15_scanner_audit.md` — итерация 1: **0 Critical / 0 High /
  3 Medium / 6 Low / 3 Info**; итерация 2 (после фиксов @Builder): **0 Critical / 0 High / 0 Medium /
  3 Low / 3 Info**; открытых Critical/High/Medium нет.

## Round 10.20 (T-1915) — карта связностей (diff-based, HEAD 2f3e1f0 + worktree)
- **Статус скана: итерация 1 — 0 Critical / 1 High (S10.20-1) / 7 Medium / 9 Low / 5 Info → финал (re-audit §10, 16.09.2026): 0 Critical / 0 High / 0 Medium / 0 Low (open) / 5 Info. Блокер S10.20-1 закрыт.**
- **Новые узлы:** `services/canonical_context.py` — единственная точка рендера контекста
  (`format_context_item`/`strip_context_header`/`resolve_item_id`/`format_chat_time`) + реестр
  `CONTEXT_POINTS` (14 точек) → потребляют: `direct_chat_service` (точки 2/3, `_line_markers`),
  `summary_memory` (RAG-строки, `_fact_tokens`), `tool_router` (dig/history), `chat_context`,
  `summary_generator` (archive), `lore_compiler_service`.
- **`services/context_middleware.py`** — обёртка `truncate_keep_header` ← `direct_chat_service._truncate_block`/
  `_apply_context_budget` (неразрывная связка «метаданные > бюджет»).
- **`services/lore_compiler_service.py`** ← `tool_router._compile_lore_story` (8-й тул, гейт
  `flags.lore_compiler_enabled`) → `db.lore_graph_slice` + `db.lore_dense_dialogs` + `db.get/upsert_lore_story`
  (`lore_stories`, без бампа `user_version`) → `ctx.lore_compiled/lore_story` → `direct_chat_service`
  (локальный `parse_mode=HTML` + `escape_lore_html` + plain-фолбэк). **`factcheck_service` тоже получил
  `compile_lore_story`, но `ctx.lore_compiled` не читает** (S10.20-4).
- **`services/reply_postprocess.py`** → `tool_loop` (финал/деградация), `direct_chat` (chokepoint),
  `summary_cleanup.cleanup_llm_text` (factcheck/summary/поиск/видео) — единый срез reasoning-черновиков.
- **`ToolLoopResult` (str-подкласс)** → `direct_chat_service` (degraded-логирование, `str(raw)`-совместимость);
  `LLMChatResult.reasoning` — телеметрия без потребителей.
- **Provenance `graph_facts.tg_message_id/forward_from`** (миграция v11→v12, `_SCHEMA_SQL` + guard) →
  `memorize_facts` (17/17) → 6-кортежи `_search_graph_facts`/`_knn_graph_facts` →
  `_format_origin_labeled_line`/`build_rag_context` (канон-заголовок) → `order_rag_facts_asc` (D206, после дедупа).
- **Мини-апп:** `web/app.js` sticky-save (`dirtyItems`/`dirtyKeyItems`/`saveModalEdits`) ↔ `configSnapshot` ↔
  `loadConfig`; `dossier_feed` (API global-admin, поллинг 45 с) → тикер «Живой ленты»; модалка досье →
  `PUT/GET /api/chat_lore/{chat_id}/dossier/{user_id}` (`persona_dossier_overrides`, RBAC `_require_chat`; хендлеры — `web/api/chat_lore.py::put_dossier`/`get_dossier`, фид — `web/api/oversight.py::dossier_feed` ← `services/database.py::dossier_feed`).
  **Разрыв (S10.20-1, High) — ЗАКРЫТ (re-audit 16.09.2026):** `<sticky-save>` добавлен в конец ветки
  `currentTabIsConfig` (`web/index.html:704`); панели также в модалке «Модулей» (:967), ветке «Доступы»
  (:1549) и футере модалки досье (:2694); тесты проверяют панель В КАЖДОЙ ветке.
- **Техдолг/CLI/каноны:** `manage.py retention` (dry-run по временному снапшоту через SQLite backup API; `--apply` — `DatabaseService.initialize_existing()`, WAL/busy_timeout без DDL); `services/memory_maintenance._archive_imported_history` += `_fsync_directory` (POSIX; win32 no-op); `services/reply_postprocess.py` (reasoning-стриппер) ← `summary_cleanup.cleanup_llm_text`; канон-консистентность: `docs/canon/architecture.md` (CHAT/FACTCHECK/LORE_STORY/TOOL_SCHEMAS EN) + `docs/canon/backlog.md` (R11 v4 summary «архив ≠ свежее»); `services/canonical_context.py::CONTEXT_POINTS` (14) — генератор инвентарного теста «нет голого текста».
- **Статус после re-audit (16.09.2026): 0 Critical / 0 High / 0 Medium / 0 Low (open) / 5 Info.**
  Все S10.20-2…-16 закрыты; S10.20-12 (ADR-1020-3) и S10.20-17 (RBAC-паритет) — приняты обоснованно.
  Валидатор: pytest **6546 passed / 0 failed**; JS-гейты `JS-UNIT-OK`/`VUE-MOUNT-OK`; `git diff --check` clean.
## Round 10.20 UPD3 (T-1941, 17.09.2026, HEAD a67f83d + worktree → деплой `ec93c3d`) — карта связностей UI-rework
- **Статус скана: 0 Critical / 0 High / 1 Medium / 3 Low / 3 Info** (блокеров нет). **Финал (T-1936-fix2):** M-1/L-1/L-2 **закрыты**; @Reviewer **APPROVED** (Re-review итерация 2). Отчёты: `plans/reports/round1020_ui_rework_scanner_audit.md`, `plans/reports/round1020_ui_rework_reviewer.md`. Архитектура: `plans/ARCHITECTURE.md` §46.
- **Новые узлы (frontend-only, backend/API/каталог Δ=0):**
  - `web/static/app.css` — единый glass-set (`.card`, `.modal-card`, `.module-card`, `.hub-card`, `.prov-block`,
    `details.advanced`, `.scope-panel`, `.glass-panel`, `.oversight-panel`) ← `--glass-bg rgba(20,25,30,.5)` + `--glass-blur blur(16px)`;
    `.prov-grid`/`.module-list`/`.hub-grid` — только раскладка `repeat(auto-fit,minmax(320px,1fr))` (без фона/blur);
    `.sticky-save` + `.modal-card{flex-col;max-height:min(90dvh,46rem)}` + `.modal-body{overflow-y:auto;scroll-padding-bottom}`
    (у `.scroll-area` — только `scroll-padding-bottom`, **без** `padding-bottom`; место над панелью резервирует `.sticky-spacer` — закрытие M-1);
    градиент `--grad-d #FF8A3D` + `--grad-speed 6s` (wash = `body::before` conic + `#app{z-index:1}`).
  - `web/app.js` — `SECRET_MASK`/`isSecretMask`/`hasSecretMask` (композит `маска+ввод` = маска) ← `_seedSecretMasks()`
    (вызов из `loadConfig`/`_snapshotConfig`/`cancelModalEdits`/`saveKeyItem`) → guard'ы `saveKeyItem`/`saveBlock`/`dirtyKeyItems`/`testBlock`/`testField`;
    `SECRET_MASK_HINT` — понятная подсказка при композите вместо вводящего в заблуждение «Уже сохранено» (L-2).
  - `web/index.html` — **условный** `@focus="f.secret && $event.target.select()"`/`@mouseup` на 3 provider-инпутах (L-1: не-секретные не блокируются); `prov-grid` для ветки «ИИ»; `<sticky-save>` внутрь
    `.modal-body` и футера досье + **`.sticky-spacer`** перед панелью в config/access-ветках (M-1); снят inline `max-height`.
- **Новые тесты:** `tests/js/round1020_ui_rework_test.js` (JS-UNIT-OK), `tests/test_webapp_ui_rework_round1020.py`
  (каскад-резолвер/селекторы); обновлены `round1020_ui_test.js`, `test_webapp_api.py::TestStatic`,
  `test_webapp_round1020_ui.py`, `test_webapp_round109_ui.py`, `test_webapp_avatars_ui.py`.
- **Проверенные связки:** UI `testBlock`/`testField` (пустой `api_key`) ← `services/llm_probe.py:308-311::probe_block`
  (резолв сохранённого ключа); `/api/config` маскирует секреты `{configured,last4}` (`web/api/routes.py:231-240`) ←
  `blockFieldValue` → `SECRET_MASK`.
- **Finding M-1 (Medium) — ЗАКРЫТ (T-1936-fix2):** было `.scroll-area:has(> .sticky-save){padding-bottom:88px}` — смещал
  content-box, из-за чего sticky-панель в fullscreen config-вкладках «висела» на 88px выше низа вьюпорта (Chromium: `bandBelow=88`).
  Стало: `padding-bottom:0` + `scroll-padding-bottom:var(--sticky-save-h)` + спейсер `.sticky-spacer` перед `<sticky-save>` (`bandBelow=0` на scrollTop 0/1000/max).
- **Изменённые `web/*` (Δ backend/API/каталог=0):** `web/static/app.css`, `web/app.js`, `web/index.html`.
- **Валидатор (финал):** pytest **6574 passed / 0 failed** (baseline 6546 → +28); JS-гейты `JS-UNIT-OK`×2 / `VUE-MOUNT-OK` / routing OK; `node --check web/app.js` OK; red→green (19 failed/7 passed → 26 passed); `git diff --check` clean. **✅ Деплой: commit `ec93c3d`** — прод-`/web/static/app.css` подтверждён (`blur(16px)`/`rgba(20,25,30,0.5)`/`#FF8A3D`/`6s`/`sticky-spacer`/`Cache-Control: no-store`); сервер `racknerd-f4e3456` — `systemctl` active, MainPID **2738993**, NRestarts=0; SQLite `user_version=12`; каталог-Δ=0. **⏸ Открыто (не блокеры):** живые WebView, скриншоты §7.5.

## Round 10.25 — ASAP hotfix `hotfix-media-tma-round1025` (медиа/транскрибация + cache-bust TMA), Step 6 @Scanner (21.09.2026)

- Diff `7c38f70..ee23e47` (коммиты `8b16c4a`, `ee23e47`). Отчёт: `plans/reports/round1025_hotfix_scanner_audit.md`.
- Итог: Critical 0 / High 0 / Medium 2 / Low 4 / Info 4. Вердикт: к Шагу 7/9 — ДА. Факт: pytest 7976 passed / 0 failed (109.17s, 1 pre-existing warning); JS 19/19; новые тесты хотфикса 30 passed.
- Новые связи:
  - `docker-compose.yml` (сервис `telegram-bot-api`, env `TELEGRAM_LOCAL`) → образ `append_flag_from_env` → `--local`; тот же env читает хост-процесс (`config.settings.load_dotenv` + `handlers/youtube.py::telegram_local_mode_enabled`) — паритет 1:1 (непустое = local).
  - `handlers/youtube.py::effective_video_max_size_mb` = min(configured, 2000|20) → ранний гейт `_process_video_media` (нативный TG-файл); ссылочные ветки (yt-dlp) → `_configured_video_max_size_mb`.
  - `services/smartmodule_phrases.py::video_too_big_phrase` — единственный рендер `{limit}` → `handlers/youtube.py::_too_big_phrase` (4 call-sites); новый пул `VIDEO_MEDIA_PROVIDER_TIMEOUT_PHRASES` — ветка таймаута fetch.
  - `services/media_download.py::local_file_path` → `_is_within_root` (resolve + is_relative_to): принимает относительный (root/<bot_id:token>/<path>) и абсолютный ТОЛЬКО внутри `TELEGRAM_API_FILES_DIR`; общий `_read_local_source` (youtube/voice/avatars `web/api/avatars.py`).
  - `_safe_exc_text`: `handlers/youtube.py` (masker = `services.log_ring.sanitize`) и `services/llm_client.py` (masker = `_mask_secrets`) → диаг-WARNING; `llm_client._provider_host` — только hostname (R17).
  - Cache-bust: `config.settings.APP_VERSION` (2.58.1) → `web/app.py::_render_index`/`_render_app_css` → `web/index.html` `?v=` (app.js/app.css/tailwind/telegram-init/@font-face).
- Инварианты: Δ DDL=0, Δ каталога=0, F0/Эпик2 не тронуты, F1-WIP в `stash@{0}` цел (25 файлов / +971), zip не в git, `git diff --check` exit 0.
- Латентные риски: M-1 (лог сырого absolute `file_path` может нести `<bot_id>:<token>`; в проде маскируется SecretMaskFilter/sanitize), M-2 (`TELEGRAM_LOCAL` vs `DOWNLOAD_ENABLED` — два рубильника; `.env.example`/README без `TELEGRAM_LOCAL`).

## Round 10.25 P0 hotfix2 `fea2daa` (render `stickyFieldFailed` + container→host путь Bot API), Step 6 @Scanner (21.09.2026)

- **Diff `78e612a..fea2daa`.** Отчёт: `plans/reports/round1025_hotfix2_scanner_audit.md`.
- **Итог: Critical 0 / High 0 / Medium 2 / Low 3 → к деплою — ДА.** pytest **8003 passed / 0 failed** (117.37 s); JS **21/21**.
- **P0-1 (render):** `web/app.js` `stickyFieldFailed` перенесён computed→methods (тело не менялось) — `web/index.html:851,970` вызывает его как функцию; computed-геттер давал boolean → `TypeError` → пустые `#/ai/llm`, `#/ai/names`, `#/ai/smart-cache`, `#/memory/rag`.
- **P0-2 (путь):** `services/media_download.py::normalize_api_file_path` — контейнерный `/var/lib/telegram-bot-api/<bot_id>:<token>/…` → `settings.TELEGRAM_API_FILES_DIR/<bot_id>:<token>/…`; относительный → `root/<bot_id:token>/<path>`; иной абсолютный как есть; guard `_is_within_root` (resolve+is_relative_to) сохранён, fail-closed → `bot.download`. Новый `read_host_file_bytes` → `web/api/avatars.py` (host-чтение до прежнего `download_file` fallback).
- **Связь:** `services/media_download.py` ↔ `web/api/avatars.py` (общий helper), ↔ `handlers/{youtube,voice_transcription,video_download}.py` и `services/native_media.py` (через `fetch_media_to_tmp`).
- **Остаточное (не блокер):** M-1 лог сырого `file_path` в `_read_local_source` достижим на контейнерном пути (маскируется `SecretMaskFilter`); M-2 трейсбек `bot.download_file` в avatars может нести токен (фильтр маскирует только `msg`, не `exc_info`).
- Инварианты: Δ DDL=0, Δ каталога=0, F0/Эпик2 не тронуты, `stash@{0}` цел, zip не в git, `git diff --check`=0.

## Round 10.25 hotfix3 `hotfix3-summary-stt-anticliche-round1025` (working tree, база `fe0f7bb`), Step 6 @Scanner (21.09.2026)

- **Изменения не закоммичены** (диффа `fe0f7bb..HEAD` нет). Отчёт: `plans/reports/round1025_hotfix3_scanner_audit.md`.
- **Итог: Critical 0 / High 0 / Medium 2 / Low 4 / Info 1 → к деплою — ДА.** pytest **8037 passed / 0 failed** (100.28 s); JS **22/22**.
- **Новые связи:**
  - `services/summary_generator.py::_run` → `_resolve_cover_prompt(draft, text)` → `_deliver_rich`/`_deliver_plain` (строго либо/либо, не двойная отправка); фолбэк Stage-1 при `SUMMARY_COVER_FALLBACK_ENABLED` (env-only `ClassVar`, default ON) даёт детерминированную обложку `_derive_fallback_cover_prompt` (без доп. LLM).
  - `services/system2_handoff.py::parse_summary_handoff_ex` (reason: `empty`/`invalid_json`/`invalid_digest`/`ok`) ← обёртка `parse_summary_handoff`.
  - `SmartModule/service.py::VoiceTranscriber` → `audio_prep.extract_audio_for_stt` (ffmpeg ogg/opus 16k mono + segment-чанкинг) — единая точка для видео и ГС; kill-switch `STT_AUDIO_COMPRESS_ENABLED` (env-only `ClassVar`).
  - `web/api/anticliche.py` → `anticliche_worker.build_patterns_report` (manual=True не фильтрует хардкод, помечает `hardcoded_flagged`) → `web/app.js::saveCliche` (честное «Сохранено N из M», канон 120).
  - `services/llm_client.py::llm_stats` (`requests/timeouts/fallbacks/timeout_share`) + `reason=<класс>`/`provider=<host>` в логах таймаутов.
- **Техдолг:** M-1 prep внутри STT-семафора (до ~15 мин держит слот); M-2 `LLM_FALLBACK_TIMEOUT_SECONDS` — per-attempt, не бюджет цепочки (риск ложных таймаутов); L-1 temp-каталог `stt_seg_*` не удаляется; L-2 лишний ffmpeg для 20–25 МБ при доступном Groq; L-3 нет теста baseline `SYSTEM2_SUMMARY_ENABLED=False`; L-4 JS-тест grep-based.
- **Инварианты:** Δ DDL=0, Δ каталога=0 (418, флаги `ClassVar`), `stash@{0}` цел, zip не в git, `git diff --check`=0.

## Round 10.25 hotfix4 `hotfix4-cover-nav-shell-round1025` (21.09.2026, Step 6 @Scanner)

- **Diff `5f624cd..HEAD`** (`55f286f`, `072800a`, `f458b8c`). Отчёт: `plans/reports/round1025_hotfix4_scanner_audit.md`.
- **Итог: Critical 0 / High 0 / Medium 1 / Low 5** → к деплою да. pytest **8065/0** (106.91 s), JS ок, matrix 0.
- **Новые связи:**
  - `services/summary_generator.py::resolve_cover_style`/`cover_style_markers` ← `hot.get('prompts.summary_cover_style')` → `compose_cover_image_prompt` (порядок style→visual, кап 500/1000 без изменений); пустой `draft.cover_prompt` → `_derive_fallback_cover_prompt` (rich-путь, не тихий plain).
  - `services/summary_prompts.py::PREV_SUMMARY_EDITOR_R1025_HOTFIX4` (== прод-канон до hotfix4) → `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS` (ступень канона Редактора, идемпотентный откат).
  - `web/static/telegram-init.js` (`--tg-viewport-bottom-offset` = `innerHeight − viewportStableHeight`) → `web/static/app.css` `.bottom-nav`/`.more-sheet` `bottom` (+ CSS-фолбэк `100dvh − stable-height`); `viewport-fit=cover` в `web/index.html`.
  - `web/app.js::bottomNavItems`/`mobileMoreItems` ← `navItems` (status+how публичные) → bottom-nav ≤4, «Ещё» только при скрытых непубличных; `mobileMoreItems` без дубля «Справки» и без inline-раздела.
- **Техдолг:** M-1 JS-тест дублирует формулу offset (тавтология, `tests/js/round1025_hotfix4_shell_test.js:47-53`); L-1 нет guard `stableH>0`; L-2 CSS-фолбэк на `dvh` (старые WebKit); L-3 `has_heading` по подстрокам; L-4 `viewport-fit=cover` не гейтится OFF; L-5 импорт приватных хелперов из hotfix3-тестов.
- **Инварианты:** Δ DDL=0, Δ каталога=0, `stash@{0}` цел, секретов/zip в diff нет, `git diff --check`=0.
- **Матрица верифицирована как детектор:** с навязанным `.bottom-nav{bottom:0}` → 56 failures (панель под видимой областью), baseline → 0.


## Round 10.25 F3 `global-scope-selector-round1025` (`76a6c40`), Step 6 @Scanner (21.09.2026)

- **Diff `5dcc6bd..76a6c40`.** Отчёт: `plans/reports/round1025_f3_scanner_audit.md`.
- **Итог: Critical 0 / High 0 / Medium 1 / Low 4 / Info 3 — к деплою да.**
- Связи: `web/index.html` (`.scope-wrap`/`.scope-trigger`/`.scope-panel`, `.scope-tech`) → `web/app.js` (`scopeKind`, `configSourceLabel`/`configSourceTitle`/`configItemNotice`, `hasUnsavedEdits`) → `scopeEpoch`/`_scopeGuard` (`loadConfig`, `persistItems`) → `resetChatOverride` → `DELETE /api/config/chat/{key}` (`web/api/routes.py:852`) → `chat_params.set_chat_params` (merge overrides/meta). `web/static/app.css` §70 mobile. `config.settings.APP_VERSION=2.58.6`.
- M-F3-1 (`web/app.js:2472-2482` + `2538`): guard не покрывает `blockDrafts` (llm_providers) — вероятна тихая потеря черновика при смене scope.
- Инварианты: Δ DDL=0, Δ каталога=0 (459), `stash@{0}` цел, zip не в git, `git diff --check`=0. pytest 8142/5/1 (5 — env aiogram InputRichMessageMedia), JS SCOPE-SELECTOR-OK, matrix не воспроизведён (нет playwright).

## Round 10.25 ПАКЕТ F2+hotfix5+F3 (финал), Step 6 @Scanner (22.09.2026)

- **Диапазон `f2328fb..HEAD` (`3caddeb`).** Отчёт: `plans/reports/round1025_package_scanner_audit.md`.
  Финалы: F2 `d2df8ca`, hotfix5 `412f844`, F3 `4f31197` (ревью-фиксы `0f227a5`/`d2df8ca`, `cbaec05`/`412f844`, `fb49f29`/`4f31197`).
- **Итог: Critical 0 / High 0 / Medium 1 / Low 5 / Info 4 → к деплою — ДА.** pytest **8146 passed / 5 failed / 1 skipped**
  (5 — env aiogram InputRichMessageMedia, файлы вне пакета), целевые 152 passed, JS 25/25. Δ DDL=0, Δ каталога=0, `stash@{0}` цел.
- **Новые/уточнённые связи:**
  - `web/app.js::reconcileLiquidGlass` → ставит/снимает `data-glass-downgraded` (НЕ переписывает opt-in `data-glass`);
    CSS `app.css:978 [data-glass="a"][data-glass-downgraded="1"]` → blur без преломления (обратимо A↔B).
  - `web/app.js::_lgSchedule` (троттлинг ≥250 мс) ← `MutationObserver(#app)` + `ResizeObserver(allow-узлы)` + watch
    `activeTab`→`$nextTick` + `_onResize` + `onVisibilityChange` (возврат из hidden); disconnect в `beforeUnmount`.
  - `web/app.js::_liquidGlassSupported` → UA-gate `AppleWebKit && !/Chrome|Chromium|Edg|OPR/` (общий WKWebView → уровень B).
  - `services/image_generation.py::generate_image_verbose` → `asyncio.wait_for(generate(..., retry=False), timeout=окно)`;
    `retry=False` → `_request_with_retry(max_retries=0)` (внутренний HTTP-повтор выключен на период обложки);
    `is_transient_reason` ограничивает внешний повтор `timeout/network/unreachable/429/502/503/504`.
  - `services/image_generation.py::_consume_budget` → `worker_budget.consume(scope="global")` + `consume(scope="chat:<id>")`
    (ОБА контура `image_calls`; отказ global → per-chat не тратится; env-only, `_metric_limit` не зовёт каталог).
  - `web/app.js::hasUnsavedEdits` ← `blockDrafts`/`ownKeyDraft`/`personaDraft`(vs `personaMeta.values`)/`dossierDraft`(vs `manual_traits`).
  - `web/app.js::resetChatOverride` → паритет с `web/api/routes.py:868-876` (`isGlobalAdmin || isDmCtx() || isLocalAdminCtx()`);
    кнопка `.btn-reset-global` (селектор стабильный, `flex-shrink:1/min-width:0` — критичный mobile-overflow закрыт).
- **Техдолг/остаток:** M10.25F2-3 (цена преломления не измерена; A на 3 узлах); L10.25F2-1 (sticky-header alpha без blur);
  L10.25F2-2 (тавтологичный `"240" in APP_JS`); L10.25F2-4 (README-счётчик); NEW-L1 (iOS Edge `EdgiOS` не гейтится);
  NEW-L2 (`_initLiquidGlassObserver` после стартового reconcile); I-3 (`_onResize` без троттлинга); I-4 (inset box-shadow понижённого A).
- **Инварианты:** Δ DDL=0, Δ каталога=0, `stash@{0}` цел, zip/секретов нет, `git diff --check`=0; matrix не воспроизведён (нет playwright).
- **Регрессий нет:** handlers/bot/database/media/F0/Эпик2 вне диффа; JS 25/25 OK; 5 pytest-падений предсуществующие (env).

## Round 10.25 hotfix6 `hotfix6-webview-shell-heartbeat-round1025` (22.09.2026, Step 6 @Scanner)

- **Изменения НЕ закоммичены** — аудит рабочего дерева относительно HEAD `441e8f7`. Отчёт: `plans/reports/round1025_hotfix6_scanner_audit.md`.
- **Итог: Critical 0 / High 0 / Medium 1 / Low 3 / Info 3 → к деплою — ДА.**
- **Новые/уточнённые связи:**
  - `web/index.html:37` inline-SVG `#lg-lens` (`feTurbulence`+`feGaussianBlur`+`feDisplacementMap`) ← `web/static/app.css:57 --glass-displace:url(#lg-lens)` → `[data-glass="a"]::before` (`app.css:1064-1082`, `z-index:-1`+`isolation:isolate`, radial-mask edge-весовка) — линза лежит ПОД контентом; `backdrop-filter:url()` удалён везде.
  - `web/app.js::_liquidGlassSupported` (`:8449`) → feature-detect `CSS.supports('filter','url(#lg-lens)')` (UA-gate снят) → `reconcileLiquidGlass` (`:8481`) ведёт `data-glass-tier`/`data-glass-reason`/`data-glass-downgraded`; бюджет `_lensMaxNodes` (`:8465`, `UI_LENS_MAX_NODES=6`, `config/settings.py:711`).
  - Стекло A2: `data-glass="a"` на `.app-sidebar`/`.app-drawer`/`header.main-header`/`.bottom-nav`/`.more-sheet` (`index.html:53/3311/89/3346/3362`) + blur-подложка в CSS (`app.css:1564+`); `@supports not(backdrop-filter)` — непрозрачный fallback всех панелей (`app.css:1162`).
  - `web/static/telegram-init.js::computeBottomOffset` (`:36-50`, `window.__computeTgBottomOffset`) → `--tg-viewport-bottom-offset = max(innerHeight−stableHeight, contentSafeAreaInset.bottom, safeAreaInset.bottom)` (`:72-77`) → `.bottom-nav`/`.more-sheet` `bottom`.
  - `web/app.js::heartbeatSample` (`:6512`, телеметрия из `/api/status`, `s.uptime.generated_at`) → `_heartbeatTransition` (`:6440`, EMA+dwell+гистерезис 0.70/0.65 · 0.90/0.85, `missing/stale→UNKNOWN`, `bot.state≠running→CRITICAL`) → `heartbeat` computed (`:1722`); OFF-путь `heartbeatLegacy` (`:1746`) байт-в-байт; Canvas 2D+rAF `startHeartbeatCanvas`/`_hbFrame`/`_hbDraw` (`:6589-6668`, только вкладка «Статус», пауза на hidden) ← `UI_HEARTBEAT_CANVAS_ENABLED`.
  - `web/app.js::heartCompactV2`-гейт `headerCompactV2` (`:1820`) → двухстрочная шапка D (`.header-scope-row`, `header-fs-btn` ⛶ ≥44×44) + `_initHeaderHeight` (`:8564`, ResizeObserver → `--header-h`) → `app.css:817 scroll-padding-top`.
  - `config/settings.py:695-712` env-only ClassVar-флаги (`UI_GLASS_TIER_OVERRIDE`/`UI_HEARTBEAT_CANVAS_ENABLED`/`UI_HEADER_COMPACT_V2`/`UI_LENS_MAX_NODES`) → `web/api/routes.py:383-392` (`/api/me.ui_flags`, аддитивно/R17-safe). `APP_VERSION=2.58.7`.
- **Medium:** M-H6-1 — перф-цена foreground SVG-линзы на реальных WebKit/iOS не измерена (UA-gate снят, кап 6; преемник M10.25F2-3), не блокер.
- **Low:** L-H6-1 canvas `role="img"`+интерактив и висячий `aria-describedby="hb-tip"`; L-H6-2 линза скролл-контейнера скроллится с контентом; L-H6-3 комментарий stale-порога (2×30с vs 120000мс).
- **Инварианты:** Δ DDL=0, Δ каталога=0 (флаги ClassVar), `backdrop-filter:url(` в `web/**` отсутствует, маркер-тесты F2/F3/hotfix4 атомарны и усилены, `APP_VERSION` 2.58.7 синхронен (`?v=`/README/тесты), `stash@{0}`/теги целы, `.env`/zip/скриншотов в диффе нет, `git diff --check`=0. JS HOTFIX6-LENS-HEARTBEAT-SHELL-OK/hotfix4/design-tokens OK; целевые pytest 119 passed. Matrix не воспроизведён (нет playwright).
- **Верифицировано чисто:** каскад `position` (панели остаются `fixed`, шапка `sticky`), CSP/zero-build (один inline-SVG, без data-URI/WebGL/новых зависимостей), rAF/observer дисциплина, F0/F1/F2/F3/hotfix3-5 совместимы.

## Round 10.25 hotfix7 `hotfix7-shell-glass-heartbeat-round1025` (UPD «Срочный фикс фронта») (22.09.2026, Step 6 @Scanner)

- **Изменения НЕ закоммичены** — аудит рабочего дерева относительно HEAD `5a5465c` (`pre-round1025-hotfix7`, == `origin/master`). Отчёт: `plans/reports/round1025_hotfix7_scanner_audit.md`; AA — `plans/reports/round1025_hotfix7_contrast.md`; матрица — `plans/reports/round1025_hotfix7_ui_report.md`.
- **Итог: Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → к деплою — ДА.**
- **Новые/уточнённые связи:**
  - `web/static/app.css:75` base `--shell-h:100vh` + `:99-103` `@supports (height:100dvh) and (height:min(100dvh,100dvh)){--shell-h:min(100dvh,var(--tg-viewport-stable-height,100dvh))}` → `.app-shell` normal (`min-height:var(--shell-h)`, `height:auto`, `overflow:visible`) и `.fullscreen-mode` (`height/max-height:var(--shell-h)`, `min-height:0`, `overflow:hidden`); откат `.app-shell.shell-layout-legacy[.fullscreen-mode]` ← computed `shellLayoutV2` (`web/app.js:1830`) ← class-binding `web/index.html:50` ← env `UI_SHELL_LAYOUT_V2`.
  - Новый серо-графитовый слой `--shell-bg/-bg-strong/-border(-color)/-highlight(-soft)/-shadow/-blur/-specular/-texture` + `--card-shadow` (`app.css:79-89`) → `.app-sidebar`/`.app-drawer`/`header.header-sticky`/`.bottom-nav`/`.more-sheet`; карточки остаются на `--glass-bg`; `@supports not(backdrop-filter)` (`:1235`, shell→`--shell-bg-strong`); откат `.app-shell.shell-glass-legacy` ← `shellGlassV2` (`app.js:1827`) ← `UI_SHELL_GLASS_V2`.
  - Premium heartbeat: `_hbDraw` (`app.js:6850`) роутит `heartbeatPremium` (`:1836`, `UI_HEARTBEAT_PREMIUM`) → `_hbDrawPremium`/`_hbEcg`/`_hbPalette`/`_hbDrawGrid` (ECG sweep-wipe, цвет из `--ok/--warn/--err/--text-3`, glow `.45/.60/.85/0`) либо `_hbDrawLegacy` (canvas-legacy) ← `UI_HEARTBEAT_CANVAS_ENABLED` OFF → legacy SVG. DPR-cap 2; семантика `_heartbeatTransition`/`heartbeatSample` не тронута.
  - `config/settings.py:715-732` env-only `ClassVar` (`UI_SHELL_GLASS_V2`/`UI_HEARTBEAT_PREMIUM`/`UI_SHELL_LAYOUT_V2`, default ON) → `web/api/routes.py:395-397` (`/api/me.ui_flags`, аддитивно/R17-safe) → `.env.example`. `APP_VERSION=2.58.8`.
  - `tools/ui_round1025_matrix.py` — `MODES` 5 режимов, `F7_PROBE_JS`/`_hotfix7_failures` (shell≠card computed, `body::before` ≤.32, `urlBackdropFilter`=0, `hbVisible`, `f2ShellH`/`__f2_broken`), шина `Telegram.WebApp.onEvent/__emit` + `fullscreen_changed`.
- **Low:** L-H7-1 (@supports-фолбэк shell перекрыт каскадом, pre-existing, AA-безопасно 6.46:1); L-H7-2 (OFF-путь: header рамка+тень, DPR-cap в legacy); L-H7-3 (specular∩texture worst-case 4.44:1 для `--text-2`).
- **Инварианты:** Δ DDL=0, Δ каталога=0 (459/98/96/21/418, флаги вне `REGISTRY`), `backdrop-filter:url(`=0, WebGL=0, CSP/zero-build (specular/texture — CSS-градиенты), `APP_VERSION` 2.58.8 синхронен (`?v=__APP_VERSION__`/README/пины), `stash@{0}`/теги `pre-round1025*`/`.env.bak.round1025-hotfix7` целы, `.env`/zip/скриншотов в индексе нет, `git diff --check`=0. IA F1/hotfix4, F0 `persistItems`, store §37–§42, fullscreen-sync ADR-1024-24, deny-list tier C не тронуты; палитра §8/фон §10 сохранены (opacity wash .42→.30, `--glass-shadow` .75→.55).
- **Independent прогоны:** pytest **8207/0**, целевые **156 passed** + nav **28 passed**, `node --check` OK, JS hotfix7 + все `tests/js/*.js` PASS. Матрица в среде @Scanner не перезапускалась (опора на @Builder `failures: 0`) — Info.
- **Верифицировано чисто:** фолбэк `--shell-h` корректен (custom properties не валидируются при разборе; base `100vh` всегда + апгрейд строго в `@supports`); XSS/rAF/observer дисциплина; OFF-пути флагов независимы (функционально, с косметическими отклонениями L-H7-2). Live-гейт T-2682 (реальный Telegram WebView + FPS) открыт.

## Round 10.25 hotfix8 `hotfix8-shell-glass-aurora-round1025` (22.09.2026, Step 6 @Scanner, UPD2)

- **Найдено независимо** — аудит рабочего дерева относительно HEAD `a1e6db3` (`pre-round1025-hotfix8`); правки не закоммичены (bump 2.58.11 — Block G). Отчёт: `plans/reports/round1025_hotfix8_scanner_audit.md`; AA — `plans/reports/round1025_hotfix8_contrast.md`; UI — `plans/reports/round1025_hotfix8_ui_report.md`.
- **Вердикт: Critical 0 / High 0 / Medium 0 / Low 3 / Info 3 → к деплою (блокеров нет).** Обязательный live-гейт T-2776 (реальный Telegram WebView, FPS blob/safe-area) — по ADR, не новый блокер.
- **Новые зависимости/связи (подтверждены):**
  - `web/index.html` статичный `.aurora-bg` (5 `.aurora-blob` + `.aurora-grain`, `aria-hidden`, `z-index:0`) ↔ `web/static/app.css` (`body::before`/`body::after`/`.aurora-bg`, keyframes `aurora-flow`/`aurora-flow-rev`/`aurora-morph`/`aurora-blob-1..4`; `@media reduced-motion`; `prefers-contrast`) ↔ `web/app.js::_syncBgLayer` → `html.bg-wash-legacy` (legacy conic `body::before`).
  - Shell v3 §4: `data-glass="shell"` на sidebar/header/drawer/bottom-nav/more-sheet ↔ `app.css [data-glass="shell"]` (+ нейтральный `::after` sheen ≤.05, `#lg-lens`) ↔ `.app-shell.shell-v3`/`shell-v3-off` ↔ `web/app.js` computed `shellV3`/`auroraBgEnabled`.
  - `config/settings.py` env-only `ClassVar` `UI_SHELL_V3`/`UI_AURORA_BG_ENABLED` (default ON) → `web/api/routes.py` `/api/me.ui_flags` (bool) → `.env.example`. Δ каталога = 0.
- **Low:** L-H8S-1 перф-риск aurora (blur 64px + анимация `border-radius`/`background-position`, покрыт T-2776); L-H8S-2 mobile `.78` не ассертится матрицей, `None`-панель = pass; L-H8S-3 AA worst-case по одному blob (запас 7.33:1). **Info:** bump 2.58.11 в Block G; ослабление F2-чекера намеренно (есть `test_f2_checker_rejects_static_background`); `border-top:0` shorthand сбрасывает цвет рамки шапки (width 0).
- **Инварианты:** Δ DDL=0, Δ каталога=0 (459/98/96/21/418), CSP/zero-build (нет CDN/inline/WebGL/`backdrop-filter:url(`/новых библиотек), R17/R18 чисто (тег `pre-round1025-hotfix8`→`a1e6db3`, `.env.bak.round1025-hotfix8`, `stash@{0}` цел), `git diff --check`=0, `.env`/zip/PNG не в индексе. IA F1/F5 §61/F4 §37–§42/F0/F3, `computeBottomOffset`/hotfix4, fullscreen-sync ADR-1024-24, deny-list tier C, карточные `--glass-*` — не тронуты. pytest 78 passed (target) / JS-маркеры OK / matrix failures 0.

## Round 10.25 hotfix9 `hotfix9-shell-liquidglass-darkaurora-round1025` (22.09.2026, Step 6 @Scanner, UPD3) — NOT READY (High)

- **Зависимости/структура (новое, подтверждено):** vendored same-origin `@liquidglassjs/core 0.5.3` + `ogl 1.0.11` (`web/static/vendor/{liquidglass.core.0.5.3.min.js|liquidglass.core.0.5.3.css|ogl.1.0.11.min.js}`, IIFE-глобали `LiquidGlass`/`OGL`, SHA-256 сверены) → `<link>/<script src>` в `web/index.html` (CSP `script-src 'self'`) → `web/static/glass.js` (`window.__LiquidGlass.sync`, `mountGlass` на `.scope-trigger/.header-fs-btn/.status-block`, frost-fallback) и `web/static/aurora-flow.js` (`window.__AuroraFlow`, OGL fragment shader + Canvas2D-fallback, `#aurora-flow-canvas`) ← `web/app.js` `_syncGlassLib`/`_syncBgLayer`/`_bgPaused`. Сборка вне рантайма: `tools/vendor/{package.json,package-lock.json,build.mjs}` (esbuild 0.25.9; `node_modules` gitignored; root `package.json` НЕТ).
- **Геометрия shell (ADR-1025-17 D1):** единый источник `--app-usable-height` (`app.css:74`, `@supports 100dvh:107`; inline из `telegram-init.js:82–84` = `innerHeight − computeBottomOffset(...)`) + алиас `--shell-h:var(--app-usable-height)`; flex-колонка `.app-shell.shell-mobile:not(.shell-layout-legacy)`/fullscreen (`:1005`), `main.scroll-area` — единственный скроллер (`:1022`), `.bottom-nav` в потоке (`position:relative`, safe-area один раз), header `flex:0 0 auto`. Роллбэк `.shell-layout-legacy` сохранён.
- **Фон/стекло:** `html.aurora-flow-v2` ↔ `__AuroraFlow.start/stop`, `stop` не убирает canvas ([L-H9S-1]); `footer.modal-actions`/`.modal-head` (`app.css:1531+`), SaveBar вынесен из sticky — **в модульной модалке структурно не достигнуто (H-H9S-1)**.
- **Флаги:** env-only `UI_SHELL_FLEX_V3/UI_SHELL_GRAPHITE_V3/UI_LIQUID_GLASS_LIB/UI_AURORA_FLOW_V2` (default ON) → `/api/me.ui_flags` → computed `shellFlexV3/shellGraphiteV3/liquidGlassLib/auroraFlowV2`; Δ каталога=0. `UI_SHELL_V3` остался без потребителя ([L-H9S-2]).
- **Открытые findings:** H-H9S-1 (High, блокирует), L-H9S-1..3 (Low), I-H9S-1..2. Деталь: `plans/reports/round1025_hotfix9_scanner_audit.md`.

## Round 10.25 hotfix9 `hotfix9-shell-liquidglass-darkaurora-round1025` — повторный аудит (22.09.2026, Step 6 @Scanner, UPD3) — SCANNED

- **Статус: H-H9S-1 + M-H9R-1 + L-H9S-1..2..3 закрыты; новых Critical/High/Medium нет.**
- **Подтверждённые связи:** `web/index.html:1920` — `footer.modal-actions` сиблинг `.modal-body` (парсер, все 5 футеров) → SaveBar в flex-колонке модалки pinned (`.modal-actions{flex:0 0 auto}`, `.modal-actions > .sticky-save{position:static}`). `web/static/aurora-flow.js` context-loss → `attach2dFallback()` (свежий canvas, `mode='canvas2d'`) + `detachCanvas()` в `stop()` (`UI_AURORA_FLOW_V2=OFF`). `web/app.js:2462–2468` `shellGraphiteV3 = UI_SHELL_GRAPHITE_V3 && UI_SHELL_V3` (legacy-алиас). `.status-block` без `data-glass="a"`.
- **Открытые findings:** нет блокирующих; Info I-H9S-1..3. Деталь: `plans/reports/round1025_hotfix9_scanner_audit.md`.
- **Инварианты:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418); `APP_VERSION` 2.58.12; CSP same-origin; `--shell-texture`=0; `backdrop-filter:url(`=0; vendored SHA-256 3/3; R17/R18; `git diff --check`=0; pytest 8291/0.

## Round 10.25 hotfix10 `hotfix10-liquidglass-rollback-shell-geometry-round1025` (22.09.2026, Step 6 @Scanner, UPD4) — SCANNED

- **Статус:** Critical 0 / High 0 / Medium 0 / Low 1 / Info 2; блокеров нет. Отчёт: `plans/reports/round1025_hotfix10_scanner_audit.md`.
- **Зависимости/связи (подтверждено):** `web/static/glass.js` `SELECTOR='[data-glass-surface]'` — единственная цель (TARGETS `.scope-trigger/.header-fs-btn/.status-block` удалён); функциональные цели стекла не получают. `[data-glass-surface]` (единственный экземпляр — `web/index.html:3271`, сетка «Статус») ← `web/static/app.css .glass-surface` (контракт: `isolation`, `contain:layout paint`, `pointer-events:none`, тёмная `--glass-paper:var(--surface-1)`) ← `web/app.js::_syncGlassLib` ← env-only `UI_LIQUID_GLASS_LIB` (default OFF) через `/api/me.ui_flags`.
- **Фон (ADR-1025-18 D5):** `web/static/aurora-flow.js` `measure()` по `documentElement.clientWidth/Height`, `gl.viewport`/`uRes` из drawing buffer, `ResizeObserver(documentElement)`, экспорт `__AuroraFlow.resize` ← `web/app.js` `_auroraResize()` в `_onResize`/`setFullscreenFromTma`(rAF)/`_onVV`(visualViewport, с cleanup).
- **Main/высота:** подложка `--work-surface-bg` на `main.scroll-area` (desktop `max-width`/центрирование сняты, лимит 1100 px на `.module-list/.module-quick-wrap/.module-toolbar`); `.fullscreen-mode .scroll-area` без второго safe-area; `.more-sheet` один offset (`--tg-viewport-bottom-offset`).
- **Открытые findings:** L-H10-1 (Low, не блокирует): пустой 44 px `.glass-surface` при OFF; I-H10-1/I-H10-2 (Info).
- **Инварианты:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418); `APP_VERSION` 2.58.13; CSP same-origin; `--shell-texture`=0; `backdrop-filter:url(`=0; R17/R18 (тег `pre-round1025-hotfix10`, `stash@{0}`); `git diff --check`=0; pytest 8314/0.

## Round 10.25 hotfix10 — повторный аудит после фиксов (22.09.2026, Step 6 @Scanner, UPD4) — SCANNED

- **Статус:** Critical 0 / High 0 / Medium 0 / Low 0 / Info 1; H-1 + L-H10-1 + L-1 + L-2 закрыты; блокеров нет. Отчёт: `plans/reports/round1025_hotfix10_scanner_audit.md`.
- **H-1 CLOSED:** `web/static/app.css main.scroll-area{grid-auto-rows:max-content}` → grid-строка с `.status-block` (`overflow:hidden`) не сжимается; матрица @Scanner `failures:0`, `scrollH==clientH` на 320/360/390/430 + fullscreen, hit-тесты `.hb-canvas`/`__bot`/`__server` `self=true`.
- **L-1 CLOSED:** `web/static/glass.js::clearAttrs` снимает `data-glass`/`data-uid`/inline `--g-*`; **L-2 CLOSED:** `.env.example` (`UI_LIQUID_GLASS_LIB (default OFF)` + `[data-glass-surface]`); **L-H10-1 CLOSED:** `web/index.html v-if="liquidGlassLib"` (OFF → `surfaceCount=0`).
- **Инварианты:** Δ DDL=0; Δ каталога=0 (459/98/96/21/418); `APP_VERSION` 2.58.13; CSP same-origin; `--shell-texture`=0; `backdrop-filter:url(`=0; маркер-тесты не ослаблены; R17/R18; `git diff --check`=0; pytest 8319/0; матрица failures 0.
