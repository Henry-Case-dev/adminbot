# F6 `memory-analytics-reorg-round1025` — evidence (Step 4 @Builder)

- **Дата:** 2026-09-23. **Diff base:** HEAD `f103992` (рабочее дерево, без commit).
- **APP_VERSION:** `2.58.13` → `2.58.14`.
- **ADR:** `adr-1025-19-execution-graph-adapter-and-memory-section.md` (D1–D8).
- **Не коммичено:** изменения только в рабочем дереве; `plans/current_task.md` не тронут (untracked/read-only).

## Изменённые/новые файлы

**Новые:**
- `web/static/execution_graph.js` — adapter `window.ExecutionGraph` (нормализация/фильтр/детализация; не источник данных, не DOM).
- `tests/js/round1025_f6_execution_graph_test.js` — unit adapter (маркер `F6-EXECGRAPH-OK`).
- `tests/js/round1025_f6_analytics_memory_test.js` — §21–§29/§52–§59/§75/§76/§116 (маркер `F6-ANALYTICS-MEMORY-OK`).
- `tests/test_webapp_f6_round1025.py` — статические инварианты фронтенда + read-only analytics API (19 тестов).
- `plans/features/memory-analytics-reorg-round1025/evidence.md` — этот файл.

**Изменённые:**
- `web/app.js` — adapter-backed `tokenFlowTree`; режимы `execMode`/`setExecMode`; фильтры §27 (`execTraceNodes`, `execAggregate`, опции); детали (`execDetail`, `selectExecNode`, `closeExecDetail`); превью (`execPreview`, `loadExecPreview`); `fmtCost(v, known)` (§28) + `execCostLabel`/`fmtTokensCell`/`execStatusLabel`; 5 подгрупп «Память» (`MEMORY_SUBGROUPS`, `_memorySubgroupOf`, `memorySubgroupChips` computed, `_memoryGroups`); `HUBS_V2['#/memory']` — 3 раздела.
- `web/index.html` — переключатель 4 режимов; трассировка/агрегат (взаимоисключающие ветки); фильтры; detail overlay на корне `#app`; превью «Последний вызов» на Статусе; подгруппы «Разделы памяти»; `<script src="/static/execution_graph.js">` до `app.js`.
- `web/static/app.css` — аддитивно `.token-flow__node--llm/--algorithm/--format/--publish/--other`, `.exec-detail` (side-panel/bottom-sheet), `.exec-preview`.
- `config/settings.py`, `README.md` — bump `2.58.14`.
- Маркер-тесты версии/структуры (атомарно): `tests/js/{round1024_nodeflow,round1025_hotfix7/8/9/10,round1025_ia_routing,routing}_test.js`, `tests/test_{scope_selector,webapp_design_tokens,webapp_hotfix6/7/8/9/10}_round1025.py`, `tests/test_webapp_js_unit.py` (+2 новых JS-теста).
- `plans/features/memory-analytics-reorg-round1025/tasks.md` — чекбоксы T-2870…T-2910.

## Что реализовано (A–H)

- **A:** «Аналитика» (`#/oversight`) дополнена картой вызовов и превью Статуса §21; переименование «Сводка»→«Аналитика» (F1) не дублируется.
- **B:** adapter `ExecutionGraph`: `fromTrace/fromSummary/filter/detail`; `ExecutionNode` — `id=correlation_id:index`, `parentIds` только подтверждённая линейная последовательность (`tool`/первый → `[]`), `status='unknown'`, `durationMs/finishedAt/provider=null`, `cost=null` при `price_known!==true`; `kind` enum `llm|algorithm|tool|format|publish|other`; `algorithm/format/publish` зарезервированы и **не эмитятся** из текущих данных.
- **C:** два несмешиваемых режима §26 (`Последний вызов` ← `/usage/latest`; `День/Неделя/Месяц` ← `/usage/summary`).
- **D:** desktop side-panel / mobile bottom-sheet; фильтры на «Аналитике»: **поиск** + модуль/модель/этап/статус (H2, Step 4b); превью Статуса фильтров не получает.
- **E:** `$0` только для подтверждённого нуля, иначе «Нет данных»; блок «Стоимость LLM» отделён от «Ресурсов сервера»; «Безлимит (∞)» без заполненного прогресса (существующая ветка сохранена).
- **F:** mobile — вертикальная последовательность; bottom-sheet `width:390, y=590` (viewport 390×844).
- **G:** «Память» — 3 раздела (Настройки памяти / Лор чатов / Люди и связи); настройки памяти в 5 подгруппах (Поиск/Граф знаний/Хранение/Ночной синтез/Отношения/Прочее); рендеры `relations`/`chat_lore`/`memory_rag` сохранены; `services/param_catalog.py` не тронут.
- **H:** тесты §75/§76/§116; инварианты проверены.
- **Bump:** `2.58.14` + `?v=__APP_VERSION__` (script tag adapter) + README.

## Step 4b — правки по review @Reviewer / аудиту @Scanner (Step 5–6)

Дифф-база та же (HEAD `f103992`, worktree). Backend/миграции/каталог не тронуты.

- **H2 (§27, High) — поиск и фильтр «статус».** В блок фильтров «Аналитики» добавлены
  поле поиска (`v-model="execFilterQuery"`) и `select` статуса (`v-model="execFilterStatus"`,
  опции — `execStatusOptions` из реальных статусов узлов, сейчас честно «нет данных»).
  Adapter `ExecutionGraph.filter` расширен полем `query` (подстрока без регистра по
  label/этапу/module/model/toolName/source; ничего не выдумывает). Фильтры — только
  на «Аналитике»; превью Статуса их не получает.
- **M-F6S-1 (Medium) — утечка фильтров в «Период».** `setExecMode` при смене режима
  вызывает `resetExecFilters()`; `execAggregate` применяет ТОЛЬКО `{module}`
  (model/stage/status/query к агрегату не применяются). Кнопка «Сбросить» доступна и в
  агрегате при активном фильтре.
- **L-F6S-3** — закрыт вместе с H2 (select «статус»).
- **L-F6S-4** — `.exec-detail`: `aria-modal="true"`, подложка `.exec-detail-backdrop`
  (`@click.self`), закрытие по `Esc` через `escClose()`.
- **L-F6S-5** — мёртвый шов удалён (`card.memorySubgroup`, `:key` без него);
  `memorySubgroup` сбрасывается при входе в карточку хаба (`openHubCard`).
- **Техдолг (осознанно НЕ чинится в F6, R16 — сервер не менять):** L-F6S-1
  (`fromSummary` `priceKnown:true` при неизвестной агрегатной цене) и L-F6S-2
  (OFF-ветка kill-switch не byte-identical) — зафиксированы в `review.md`/аудите.

Изменённые файлы Step 4b: `web/static/execution_graph.js`, `web/app.js`, `web/index.html`,
`web/static/app.css`, `tests/js/round1025_f6_execution_graph_test.js`,
`tests/js/round1025_f6_analytics_memory_test.js`, `tests/test_webapp_f6_round1025.py`.

## Прогоны (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Синтаксис | `node --check web/app.js`; `node --check web/static/execution_graph.js` | OK |
| JS-тесты (все) | `node tests/js/<N>.js` × 37 | **37/37 PASS** (0 fail) |
| Adapter | `node tests/js/round1025_f6_execution_graph_test.js` | `F6-EXECGRAPH-OK` |
| F6 §21–§116 | `node tests/js/round1025_f6_analytics_memory_test.js` | `F6-ANALYTICS-MEMORY-OK` |
| pytest (полный) | `py -3 -m pytest -q` | **8334 passed, 1 skipped, 5 failed** (Step 4b) |
| pytest (F6) | `py -3 -m pytest tests/test_webapp_f6_round1025.py -q` | 19 passed |
| Playwright-матрица | `.venv/Scripts/python.exe tools/ui_round1025_matrix.py` | **failures: 0** (10 viewports) |
| Playwright F6-filters | temp-проба (H2 поиск/статус, M-F6S-1 сброс, L-F6S-4 Esc/backdrop, desktop+mobile) | `[f6-probe] OK — failures: 0` |
| git diff | `git diff --check` | OK (нет whitespace-ошибок) |
| Δ DDL | `git diff --stat -- services handlers migrate_history migrations alembic web/api` | пусто (0) |
| Δ каталога | `services/param_catalog.py` не изменён | 0 |

**5 pytest-фейлов — не F6:** `tests/test_outgoing_guard_round1022.py` (2) и `tests/test_summary_cover_round1023.py` (3), ошибка `summary cover: rich fallback ImportError` (отсутствует опциональная TG-зависимость). Подтверждено прогоном на baseline (`git stash` → те же 5 падений), к web/analytics/memory отношения не имеют.

## Покрытые acceptance-сценарии (D8/§75/§76/§116)

- adapter: одно-/двухслойный (`single`, `stage1→stage2`), `tool` (`parentIds=[]`), неизвестный `step`→`other`, отсутствие полей→`null`, `price_known=false`→`cost=null`, подтверждённый ноль→`cost=0`, агрегат `by_module/series`, фильтры, enum-расширяемость.
- §75: 4 режима; выбор L1/L2/модели/модуля; **поиск** и фильтр **статуса** (H2);
  **сброс фильтров при смене режима** (M-F6S-1); неизвестная стоимость; безлимит;
  отсутствие фиктивных этапов; mobile; **Esc/клик по подложке закрывают detail**
  (L-F6S-4).
- §76: маркеры «Интеллект и Память»/убеждения/парадигмы/лента досье/сон/бейджи на месте, `cognition*` не поглощён аналитикой.
- §116: единственный `.token-flow`; adapter — не DOM; CSP/zero-build (нет внешних граф-библиотек/`http(s)://`); `backdrop-filter: url(` = 0.

## Ограничения / не верифицировано

1. **Живые данные и Telegram WebView (T-2917)** — PENDING OWNER/DevOps: Playwright-проба использует стаб-ответы `/analytics/*`; реальный PG-пайплайн владельцем не подтверждён.
2. **§52 3 карточки vs 5 имён** — ЗАКРЫТО @Architect решением **AMEND-1** (`adr-1025-19a`, вариант A): принята структура из 3 карточек + карта «Досье»/«Факты»; код не менялся (см. `spec.md` D6, `tasks.md` T-2895).
3. **§59 «Умный кэш»** и **§57/§58** — поведение сохранено, но отдельного UX-переноса/переделки алгоритма relations/lore не делалось (вне Δ-инвариантов): проверено, что рендеры и данные не потеряны.
4. `background`/`shell`/`glass` не менялись; `TOKEN_FLOW_NODEFLOW_ENABLED=OFF` → прежние плоские бейджи (kill-switch сохранён); новый флаг не вводился.

## Handoff

Step 4b (правки по review/аудиту) выполнен: H2, M-F6S-1, L-F6S-3/4/5 закрыты;
L-F6S-1/L-F6S-2 — техдолг (R16). Step 5: **@Reviewer** — независимая перепроверка
H2/M-F6S-1/Lows, adapter-контракта (§24/§25/§28), двух режимов (§26), границы F11
(§21/D5), памяти (§52–§56, AMEND-1, Δ каталога=0) и маркер-тестов.
