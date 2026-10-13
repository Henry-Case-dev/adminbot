# D12 + D13 — UI wave отчёт (lane UI-D1213, ASAP 8 v6)

- База: HEAD `2e40615` (2.58.77). Коммитить НЕ велено — кандидат в рабочем дереве.
- Скоуп: web/app.js, web/index.html, web/static/app.css, tests/js/* (новый + 15 пере-пинов),
  tools/ui_asap8_v6_d1213_e2e.py (новый Playwright e2e, прецедент p1-d091011).
- `services/status_service.py` НЕ менялся: durable-агрегаты уже есть
  (F6 intent_snapshot, F4 pipeline inspector, D05 experience funnel,
  durable-оси L1 из `llm_usage_events`); врать поверх них не требовалось.

## 1. Route inventory (D13 — проверен КАЖДЫЙ маршрут/модалка/редактор)

| Поверхность | Save-модель после D13 |
|---|---|
| `#/` Статус | read-only; save-бара нет; виджеты D12 (run-card инициативы/уроков, сон ×1, пульс) |
| `#/status/graph` | read-only viewer |
| `#/oversight` (табы overview/processes/runs/incidents/memory/models/summary/logs) | read-only аналитика; «Цены моделей» — построчные actions (не dirty-форма); на «Саммари» — Unified Run Card прогона |
| `#/how` Справка | read-only |
| `#/modules` витрина | тумблеры модулей — мгновенный autosave по server-ack (module optimistic+rollback, F0) |
| `#/modules/budgets`, `#/modules/images`, `#/modules/vision` | config-ветка: dirty → компактный sticky-save + чип в шапке; clean → ничего |
| `#/modules/<slug>` (20 workspace-модулей) | модалка: footer со sticky-save — dirty-only; ESC/backdrop/✕/«Закрыть» → dirty-guard |
| `#/permsoc` | read-only телеметрия; правки — через ParamSpec → config-путь |
| `#/ai/llm` Модели и подключения | provider-блоки: blockDrafts → sticky-save; ключи — saveKeyItem по ack; тест подключения — action |
| `#/ai/prompts` (+`/ai/prompts/<slug>`) | промпт-редакторы → sticky-save (dirty-only) |
| `#/ai/smart-cache`, `#/ai/names` | config-ветка → sticky-save |
| `#/ai/persona` | personaDraft + инлайн «Сохранить» (существующий); вход в dirty-guard через hasUnsavedEdits |
| `#/memory/rag` | config-ветка → sticky-save; таблица уроков — actions (suspend/correct) |
| `#/memory/lore` | ручной/авто-лор — inline Save; админы чата — actions; история — модалка read-only |
| `#/memory/relations` | 409-диалог с сохранением черновика (existing) |
| `#/access` (+`/access/roles`,`/access/local`,`/access/admins`) | окна-модалки: назначение админов — actions; роль-эдитор — свой action-footer; матрица — inline autosave |
| Модалки: confirmAction, dossier, roleEditor, loreHistory, lore409, temporalDetail, oversightDetail, permPicker | dossier — footer dirty-only + pending-черновик при закрытии (D01-паттерн); остальные — read-only/action-бары |
| Cover style editor (full-screen) | ОДИН Save + unsaved-индикатор (ASAP-3.2, не менялся) |

## 2. D13 — universal save contract + mobile shell (реализовано)

1. **Постоянный футер удалён ВЕЗДЕ.** `sticky-save` монтируется только при
   `dirty/saving/failed/error/conflict` (`v-if="visible"`; clean/loading → элемента
   нет в DOM). Reserved spacer (`.sticky-spacer` ×2 в index.html + CSS) удалён.
   Панель — компактный pill (`fit-content; margin-left:auto`), не full-width.
   Футер досье — dirty-only. Модалки с «Закрыть» — без Save-бара в clean.
2. **Компактный Save в шапке.** `header-save-chip` (row 1): clean → отсутствует;
   dirty → `[N · Сохранить]`; saving → «Сохранение…»; error/conflict → остаётся
   с подсветкой; success → исчезает (тост F0). Единый стейт-машина root.saveState.
3. **Autosave по server-ack** — механика F0 сохранена (persistItems/saveKeyItem,
   rollback, failed-подсветка, 409-draft). Новое юнит-доказательство: неудачное
   сохранение НЕ сдвигает baseline (черновик жив) — `asap8_d1213_save_contract_test.js`.
4. **Уход с dirty-страницы защищает черновик** (`_dirtyLeaveGuard`, переиспользует
   hasUnsavedEdits; сообщение называет область + число полей — §18I.3):
   applyRoute (вся hash-навигация), closeModule (ESC/backdrop/✕), setActiveChat
   (переупаковано на guard). Отказ → маршрут откатывается (replaceState).
5. **Mobile shell:** bottom-nav и шторка «Ещё» удалены полностью (разметка,
   computeds bottomNavItems/mobileMoreItems/moreOpen, CSS, glass-селекторы).
   Верхняя компактная `mobile-topnav` (row 2 шапки, <768): горизонтальный скролл,
   тот же канонический реестр `navItems`, что desktop sidebar. Ландшафт
   ≤500px высоты — компактный ряд; в 768–1199 (крупный ландшафт) — существующий
   drawer-shell без нижних баров. Desktop (≥1200) не изменён. reduced-motion учтён.

## 3. D12 — truthful data model + виджеты (реализовано на существующих данных)

**Data-first (проверено, не переписано):** durable-семантика стадий уже пишется
(F4 pipeline_events/mca_events: success/repaired/fallback/failed/skipped/running/
pending; C06A intent_snapshot: not_run/restricted/disabled + funnel + top_block_reason;
D05: noticed→candidate→validated→active→applied→success/failure/unknown). In-memory
окно `response_recent_window` уже честно помечено (`window_note_ru` «по последним
прогонам в памяти (≤20, ~15 минут)», UI показывает метку на «Свежих прогонах»);
за 24ч/7д читаются durable `llm_usage_events.plan_meta` (ASAP 7 F2).

**Unified Run Card** (новый примитив `run-card`, props-driven, §18I.11):
- `runCardSummary` (F4 `/api/analytics/pipeline/runs/latest`): run ID, scope чата,
  health-бейдж, latency, evidence (considered/total + %), fallback, публикация
  (rich/plain), счётчики стадий, honest «Источник: durable события…», link в Запуски.
- `runCardInitiative` (C06A): воронка «Возможности → Намерения → К исполнению →
  Решения → Отправлено» (5 стадий, бары по max), стадия останова подсвечена,
  top blocker человеческим текстом, последний heartbeat-тик, honest source hint.
- `runCardExperience` (D05): «Замечено → Уроки → Проверено → Применено → Помогло»
  + «Не помогло»/«Неизвестно» отдельными строками (unknown ≠ провал) + usefulness.
- Синтетических шкал нет (тест запрещает IQ/score в рендере).

**Виджеты:** Пульс бота — существующий блок Сердцебиение+Бот+Сервер сохранён
(sparkline не тронут); Сон — ровно ОДИН детальный виджет, бейджи «Мониторинга
Интеллекта» стали кнопками (клик → скролл к авторитетному виджету, активная фаза
подсвечена не только цветом); Инициатива и Уроки — run-card на Статусе
(`data-initiative-funnel`, `data-experience-funnel`); funnel грузится на Статусе
через существующий `oversightLoadFunnel` (вторая телеметрия не создаётся).

## 4. Отложено (осознанно, с данными)

| Виджет | Статус | Данные |
|---|---|---|
| §18I.12-C «Цикл памяти» flow | отложено | факты/истории/уроки счётчики есть (memory health + stories counters); парадигмы — cognition; нужен компактный flow-рендер |
| §18I.12-H/I/J Sankey/latency/cost waterfall | отложено | per-stage latency/tokens в F4 payload есть (nodes latency_ms, usage) — рендер-работа, не data |
| §18I.12-L durable heatmap (час/день) | отложено | durable-события есть (mca_events); нужен часовой bucket-эндпоинт (агрегация на фронте от 12 runs — слабая выборка) |
| §18I.12-M dependency map | отложено | реестр PROCESS_REGISTRY есть; граф потребителей Random — инвентаризация рёбер |
| §18I.12-O factcheck date timeline | отложено | evidence_refs с датами (D10) в temporal payload; рендер-работа |
| §18I.12-P overrides map виджет на Статусе | отложено | `/api/config/overrides-map` (D07) готов; виджет — компактный рендер существующей вкладки «Доступы» |
| Analytics 5 табов §18I.9 переименование | отложено | текущие 8 табов покрывают те же вопросы; переименование — владельческий naming-pass (D14) |

## 5. Acceptance evidence

| Пункт | Доказательство |
|---|---|
| node --check web/app.js | OK |
| JS-тесты | 78/78 passed (15 пере-пинов под новый контракт + новый CONTRACT-тест `asap8_d1213_save_contract_test.js`, TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/D12+D13) |
| pytest смежные | 375 passed (webapp_f4/f5/f6/f11, design_tokens, status_section_ui_merge, c06a_status_ui, f6_initiative, oversight, webapp_api, status_service) |
| Playwright e2e | `tools/ui_asap8_v6_d1213_e2e.py` → **D1213-E2E-OK**: 34/34 чека, console errors = 0. Clean config/Статус → `.sticky-save`=0, чипа нет; typing → pill «Изменено: 1» + чип «1·Сохранить»; guard-диалог называет область+число; отказ → маршрут цел, черновик жив; согласие → уход. Mobile 390: topnav есть, bottom-nav/more-sheet нет, без h-overflow. Landscape 667×375 (mobile): topnav h=38px, без overflow; 844×390 (compact): без нижних баров, drawer-кнопка сверху. Run Cards: инициатива 5 стадий, уроки 7 строк+Полезность, Summary: run id/evidence 9/10/fallback/scope. Скриншоты: `evidence/d1213_*.png` (7 шт Playwright) |
| Browser Use (реальный Chrome, стаб-сервер 8803) | clean: sticky=0/chip=0; dirty: pill «Изменено: 1…» + chip «1·Сохранить»; guard-msg «…(1) для „Audit Chat"…»; cancel → 0/0; mobile: topnav 8 разделов (Статус|Справка|Модули|ИИ|Память|Аналитика|Доступы|PERMsoc), bottom-nav=0, overflow нет; landscape: nav_h=38, overflow нет; Run Card Summary: run id/chat/деградация/9-10/fallback/pipeline_events/stages=5. Скриншоты `evidence/d1213_bu_*.png` (6 шт) |

## 6. Изменённые файлы (кандидат, не закоммичен)

- web/app.js (+421/−…): sticky-save v-if/visible, headerSaveChip, mobileTopnavItems,
  _dirtyLeaveGuard (applyRoute/closeModule/setActiveChat), удаление bottomNavItems/
  mobileMoreItems/moreOpen, компонент run-card + 3 проекции, loadStatus → oversightLoadFunnel,
  scrollToSleepWidget, null-safe sleep-бейджи.
- web/index.html: чип в шапке, mobile-topnav (row 2), удаление bottom-nav/more-sheet/spacers,
  dossier footer dirty-only, run-card вставки (pipeline/инициатива/уроки), sleep-бейджи-кнопки.
- web/static/app.css: compact pill sticky-save, header-save-chip, run-card/funnel стили,
  mobile-topnav + landscape + reduced-motion, удаление bottom-nav/more-sheet/sticky-spacer.
- tests/js: +1 новый CONTRACT-тест, 15 обновлённых пинов (осознанная ревизия контракта
  §18I.13/§18I.14 — старые пины закрепляли удалённое владельцем решение).
- tools/ui_asap8_v6_d1213_e2e.py (новый e2e-харнесс, reuse ui_round1025_matrix).

## 7. Incidental findings

- `related-nonblocking`: sleep-бейджи «Мониторинга Интеллекта» не имели клика к
  детальному виджету (§18I.12-D) — закрыто в этом лейне (кнопки + скролл).
- `uncertain` (pre-existing, стаб-артефакт?): в e2e-пробе на `#/ai/llm` заполнение
  первого bound-поля визуально отражалось в трёх инпутах блока (Название/Адрес/Модель),
  при этом dirty-count = 1. В проде значения приходят из каталога; поведение dirty-машины
  корректно. Рекомендую отдельную проверку владельцем на живых данных.
- `unrelated/pre-existing`: блок «Граф связей» с vis-network на Статусе грузится
  лениво и в стабе пуст (0 узлов) — вне скоупа; F4 «Последние запуски» пуст в стабе
  («Запусков ещё не было») — корректный honest empty state.

## 8. Shell pin reissue (34) — финальный полный sweep

Полный pytest-прогон до re-pin: **34 failed / 13321 passed**. Все 34
классифицированы; после переиздания — см. финальные числа ниже.

### 8.1 Пины старого shell-контракта → переизданы на D13 (30)

Все — класс (a): закрепляли bottom-nav/more-sheet/постоянный sticky-save/
spacer/канон bottomNavItems — решения, удалённые владельцем в §18I.13/§18I.14.
Desktop-инварианты (sidebar 208–224, glass-токены, reduced-motion, F0 write-path)
в каждом сохранены и не ослаблены.

| # | Тест | Что пинил | Re-pin (D13) |
|---|---|---|---|
| 1 | test_asap42_step2c2_miniapp_seeds::TestMoreSheetClosedContract | more-sheet unmount+transition-CSS | полное отсутствие more-sheet/bottom-nav/moreOpen в DOM и CSS; mobile-topnav присутствует |
| 2 | test_frontend_tab_mapping::TestJsMirror::test_ia_v2_shell_markers | `class="bottom-nav"` в HTML | bottom-nav отсутствует; mobile-topnav присутствует; legacy dead-menu по-прежнему запрещён |
| 3 | test_hotfix4_…::TestBottomPanelInViewport::test_bottom_nav_offset_var_with_fallback | CSS потребляет нижний offset | ни одно CSS-правило не потребляет `--tg-viewport-bottom-offset`; stable-height (единый источник высоты) сохранён |
| 4 | test_hotfix4_…::test_more_sheet_uses_same_offset | правило .more-sheet с offset | правило отсутствует |
| 5 | test_hotfix4_…::TestBottomNavOrder::test_bottom_nav_starts_status_how_and_priority_admin | bottomNavItems-канон (4 пункта) | bottomNavItems удалён; mobileTopnavItems = `return this.navItems` (канон един) |
| 6 | test_hotfix4_…::TestBottomNavOrder::test_more_items_no_duplicate_how | mobileMoreItems (шторка) | mobileMoreItems удалён; Память/Доступы достижимы напрямую |
| 7 | test_ia_shell::TestShellMarkers::test_sidebar_drawer_bottom_nav | bottom-nav+more-sheet маркеры | отсутствие + mobile-topnav; sidebar-инварианты (1200px, ia-v2) сохранены |
| 8 | test_ia_shell::test_mobile_shell_and_breakpoints | bottomNavItems/mobileMoreItems | удалены; mobileTopnavItems присутствует |
| 9 | test_ia_shell::test_hotfix4_bottom_nav_order_and_viewport_offset | offset в HTML + порядок | offset не потребляется web/*; viewport-fit=cover сохранён |
| 10 | test_round106_ia_smoke::TestNavShell::test_no_legacy_sidebar_dead_menu | `class="bottom-nav"` | отсутствие + mobile-topnav; legacy dead-menu по-прежнему нет |
| 11 | test_webapp_f9_round1025::TestD5SaveBarVisual::test_last_field | `.sticky-spacer` в CSS | spacer отсутствует; scroll-padding/margin сохранены |
| 12 | test_webapp_hotfix6::TestAreaA::test_panels_in_allow_list | bottom-nav/more-sheet в shell-слое | shell-слой: sidebar/drawer/шапка + mobile-topnav |
| 13 | test_webapp_hotfix6::TestAreaA::test_panels_glass_and_fallback | .bottom-nav/.more-sheet в CSS+fallback | правила отсутствуют; fallback-набор sidebar/drawer/шапки сохранён |
| 14 | test_webapp_hotfix6::TestAreaB::test_nav_and_sheet_use_offset | CSS использует offset | offset не потребляется; computeBottomOffset в TG сохранён |
| 15 | test_webapp_hotfix6::TestAreaB::test_nav_order_untouched | bottomNavItems | удалён; канон navItems един (mobileTopnavItems) |
| 16 | test_webapp_hotfix7::TestAreaA_Layout::test_two_explicit_modes | .bottom-nav flex-child | .mobile-topnav flex-child в потоке шапки, не fixed |
| 17 | test_webapp_hotfix7::TestAreaC_GlassShell::test_shell_panels_use_shell_layer | bottom-nav/more-sheet в shell-панелях | sidebar/drawer/шапка + mobile-topnav; specular/shadow-токены сохранены |
| 18 | test_webapp_hotfix7::TestAreaD_FlagsAcceptance::test_ia_and_nav_untouched | bottomNavItems | удалён; sidebarGroups сохранены |
| 19 | test_webapp_hotfix10::TestHeight::test_more_sheet_single_offset | single-offset правила шторки | правило удалено; инвариант удержан отсутствием потребления offset |
| 20 | test_webapp_hubs_matrix_ui::TestNavbarAndHubs::test_six_nav_items | `class="bottom-nav"` | отсутствие + mobile-topnav; app-drawer/shellNavTo сохранены |
| 21 | test_webapp_nav_disclosure_ui::TestMenu::test_no_sidebar_dead_menu | `class="bottom-nav"` | отсутствие + mobile-topnav; dead-menu по-прежнему нет |
| 22 | test_webapp_ui_rework_round1020::TestStickySave::test_sticky_rule | `margin: 0` (full-width) | compact-pill: `margin-left:auto` + `width:fit-content`; sticky/bottom/glass/safe-area инварианты сохранены |
| 23 | test_webapp_ui_rework_round1020::TestStickySave::test_sticky_spacer_reserves_space | spacer-резерв ×2 | spacer отсутствует (CSS+DOM); sticky-save `v-if="visible"` |
| 24 | test_webapp_ui_rework_round1020::TestStickySave::test_panel_inside_modal_actions_markup | досье-футер всегда в DOM | досье-футер dirty-only (`v-if` по dossierDraft); ветки config/modules/access сохранены |
| 25 | test_webapp_hotfix8::TestShellV3::test_panels_shell_not_lens_a | bottom-nav/more-sheet в shell-слое | sidebar + mobile-topnav в shell-слое; линза A только у контента |
| 26 | test_webapp_hotfix8::TestShellV3::test_sidebar_width_and_radii | 18px-радиусы нижних панелей | правила удалены; sidebar width/padding 208–224 не ослаблен |
| 27 | test_webapp_hotfix8::TestFlagsAcceptance::test_ia_and_store_untouched | bottomNavItems | удалён; mobileTopnavItems + sidebarGroups + computeBottomOffset сохранены |
| 28 | test_webapp_hotfix9::TestGeometry::test_flex_column_and_nav | .bottom-nav правило | .mobile-topnav правило (flex-child, не fixed, без offset); единая модель высоты сохранена |
| 29 | test_webapp_hotfix9::TestModal::test_modal_dom_actions | досье-футер adjacency | dirty-only досье-футер (v-if); modal-actions static/static-правила сохранены |
| 30 | test_webapp_hotfix9::TestFlagsAcceptance::test_persist_and_ia_untouched | bottomNavItems | удалён; persistItems F0 + mobileTopnavItems сохранены |

### 8.2 Остальные 4 — не shell (выяснено полным прогоном)

| # | Тест | Классификация | Действие |
|---|---|---|---|
| 31 | test_scope_selector_round1025::TestReturnGlobal::test_reset_uses_delete_override_endpoint | (a′) устаревший пин-граница блока: нижняя граница `applyRoute` захватила 5 `this.api(` из D07-методов overrides-map (loadOverrideMap и др., вставлены коммитом 2ef6189 ДО лейна; подтверждено stash-прогоном на HEAD) | re-pin: граница тела метода = следующий метод `loadOverrideMap`; инвариант «ровно одна DELETE-мутация» сохранён |
| 32 | test_scope_selector_round1025::TestSwitchGuard::test_switch_warns_on_unsaved | (a) пин старой реализации seam: `this.hasUnsavedEdits()` инлайн в setActiveChat → D13 вынес guard в `_dirtyLeaveGuard` (общий с applyRoute/closeModule) | re-pin: `this._dirtyLeaveGuard(` до присваивания activeChatId + hasUnsavedEdits/window.confirm внутри общего guard'а; контракт (confirm с областью/числом, отказ = stay) сохранён |
| 33 | test_asap5_paradigms_diagnostics::test_bootstrap_cooldown_bypass_then_cap | **pre-existing, чужая зона** (services/asap5 paradigms diagnostics; gate=None). Подтверждено stash-прогоном: падает на HEAD без диффа лейна; services лейном не трогались | не чиню (вне WRITE_SCOPE — чужие зоны); эскалация владельцу asap5/D09-зоны |
| 34 | test_direct_chat_concurrency::TestDirectChatConcurrency::test_third_handle_waits_for_slot_at_n2 | **pre-existing, чужая зона** (services/direct_chat_service; llm.call_count 9 vs 3 — семантика счётчика разошлась с D04/WaveC-оркестратором). Подтверждено stash-прогоном на HEAD | не чиню (вне WRITE_SCOPE — direct_*); эскалация владельцу Direct-зоны |

### 8.3 Финальный прогон

- 15 пере-пиннутых py-файлов: **416 passed, 0 failed**.
- scope_selector_round1025 (после re-pin #31/#32): 21 passed (вместе с
  #33/#34 в одном прогоне — 2 pre-existing чужих зон).
- JS standalone: 78/78 (без изменений в этом раунде).
- **Полный sweep после re-pin: 3 failed / 13352 passed** — все 34 пункта
  лейна закрыты (0 осталось). Остаточные 3, все вне зоны D12/D13:
  * #33 test_asap5_paradigms_diagnostics (pre-existing, stash-пруф на HEAD);
  * #34 test_direct_chat_concurrency (pre-existing, stash-пруф на HEAD);
  * test_nostalgia_worker::test_nostalgia_uses_background_role — **(c) flaky**:
    services/nostalgia_worker лейном не трогались; standalone на кандидате
    И на HEAD — 5/5 passed (падает только под нагрузкой полного прогона,
    order/timing-зависимость детектора background-role). Эскалация
    владельцам соответствующих зон; в «0 failed лейна» не входят.

Граница соблюдена: desktop sidebar (208–224), glass-токены/эстетика,
reduced-motion, F0 write-path, канон navItems, досье-гвард — сохранены;
инварианты вне D13 не ослаблены (пины #26/#28/#29 переизданы с явным
сохранением исходных инвариантов).

## 9. Остаточный риск

- `LIVE_UNVERIFIED` (владелец): прод-данные в run-cards (реальные funnel/coverage
  числа) и визуальный вкус владельца по compact-pill (OWNER_VISUAL_PENDING по
  размещению Save: pill снизу-справа + чип в шапке — оба разрешены §18I.13).
- Guard-диалоги используют native `window.confirm` — единообразно с существующим
  паттерном смены scope (F3); кастомная модалка Stay/Save/Discard — возможный
  следующий шаг без изменения контракта.
- Pre-existing #33/#34 (чужие зоны, см. §8.2) и flaky nostalgia (§8.3) —
  эскалированы владельцам asap5/D09, Direct/D04 и Nostalgia; в полный
  «0 failed» лейна не входят.

@Orchestrator — на строгую независимую ревью.
