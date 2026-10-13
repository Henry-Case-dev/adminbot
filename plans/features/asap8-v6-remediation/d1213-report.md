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

## 8. Остаточный риск

- `LIVE_UNVERIFIED` (владелец): прод-данные в run-cards (реальные funnel/coverage
  числа) и визуальный вкус владельца по compact-pill (OWNER_VISUAL_PENDING по
  размещению Save: pill снизу-справа + чип в шапке — оба разрешены §18I.13).
- Guard-диалоги используют native `window.confirm` — единообразно с существующим
  паттерном смены scope (F3); кастомная модалка Stay/Save/Discard — возможный
  следующий шаг без изменения контракта.

@Orchestrator — на строгую независимую ревью.
