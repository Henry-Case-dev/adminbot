# F11 `status-showcase-dashboard-round1025` — evidence

## T-3063 [@DevOps] — точка отката + бэкап + baseline (ДО правок)

**Статус:** ✅ выполнено 2026-09-23 07:12 (+12:00, WC). Только точка отката/бэкап/baseline — прод не затрагивался.

- **HEAD:** `25cc19c61ef4b02e887c04ecbffea21e7dc9b46b` (`25cc19c`), ветка `master` — совпадает с ожидаемым.
- **Тег отката:** `pre-round1025-f11` (**annotated**) → `25cc19c`; **запушен** в `origin`
  (`git ls-remote --tags`: `3a5b67b8… refs/tags/pre-round1025-f11` + peeled `25cc19c61e… ^{}`).
- **Бэкап:** `var/backups/f11-round1025-20260923-071210/` — `source.tar` (1177600 B) с
  `web/index.html`, `web/app.js`, `web/static/app.css`, `web/api/routes.py`; целостность **4/4 MATCH**
  (`git hash-object --no-filters` == `git rev-parse HEAD:<path>`). Полный отчёт — `BASELINE.md` в каталоге бэкапа.
- **`.env` бэкап:** `.env.bak.round1025-f11` — 7131 B == `.env`, sha256 совпадает, gitignored; содержимое не печаталось (R17).
- **Baseline:** `APP_VERSION` **2.58.16**; pytest **8427/0/0** (1 warning, 113.47 s — отклонение от Step-0 8421/0/1 skip, см. BASELINE.md);
  JS **40/40 PASS**; `node --check web/app.js` rc=0; `database is locked`=0; **Δ DDL=0**;
  **Δ каталога=0** (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / `_SETTINGS_FIELDS` 418).
- **Гигиена/R18:** в git ничего не коммитилось; `deploy_commands.txt` не тронут (852 B);
  `stash@{0}` сохранён; теги/бэкапы не удалялись. Изменения в рабочем дереве — только `plans/**`.
- **Логи:** `var/backups/f11-round1025-20260923-071210/pytest-T3063.log`, `js-T3063.log`.

## T-3064/T-3065/T-3066 [@Architect/@PM] — spec/ADR/reconciliation (ДО правок)

**Статус:** ✅ выполнено (Step 2). `spec.md` (169 строк), ADR-1025-23 (Accepted, 84 строки), `tasks.md` сверен — расхождений нет. Все открытые вопросы (1)–(5) закрыты решениями D1–D7.

## T-3067…T-3090 [@Builder] — блоки A–H (реализация витрины «Статус»)

**Статус:** ✅ реализовано 2026-09-23. Δ DDL=0, Δ каталога=0, `current_task.md` не коммитился/не менялся, секреты не выводились.

### Изменённые/новые файлы
- `web/index.html` — контейнер `.status-grid` (12 кол.), обёртки `.sg-*`, Hero `.status-hero` (5), метрики `.status-block` (7) с честными `null`, счётчики `.status-counts` (§20), граф `.status-graph` (§16, строка 2), сон `.status-sleep` (4), превью `.exec-preview`/факты `.status-facts` (7/5, строка 4), бюджеты `.status-budgets` (12, строка 5), логи `#status-logs` (12, строка 6), экран полного графа `.status-graph-full`. «Мониторинг Интеллекта» — вся ширина (граф вынесен из него, §18-ленты не тронуты).
- `web/static/app.css` — `.status-grid`/`.sg-*`, адаптив §70 (12→6→1), `.status-grid--legacy`, `.status-hero`, `.status-counts`, `.status-sleep`, `.status-facts`, `.status-budgets`, `.status-graph-full`.
- `web/app.js` — computed `statusGridV2`/`statusSys`/`botLastActivity`/`sleepWidget`/`graphGroupOptions`/`factsFeed`/`graphFullVisible`; методы `loadLogCounts`/`scrollToLogs`, `graphNeighborsOf`/`graphSelectNode`/`graphClearDetail`/`focusGraphNode`/`applyGraphFilter`/`graphResetView`/`openGraphFull`/`closeGraphFull`; поиск по алиасу (`searchCognitionGraph`), mobile-упрощение графа, маршрут `#/status/graph`, `loadStatus` догружает бюджеты/факты/счётчики.
- `config/settings.py` — `UI_STATUS_GRID_V2` (env-only, default ON); `APP_VERSION` 2.58.16 → **2.58.17**.
- `web/api/routes.py` — **аддитивно** `UI_STATUS_GRID_V2` в `/api/me.ui_flags` (bool, R16/R17-safe; новых endpoint'ов нет).
- `README.md` — версия/раунд синхронно.
- `tools/ui_round1025_matrix.py` — F11-пробы (§12-спаны/строки/overflow, полный экран графа), `UI_STATUS_GRID_V2`; анти-регресс: `_reset_scroll` (навигация внутри вкладки не сбрасывает скролл — F1 by design) + восстановление скролла в `PROBE_JS`/`F7_PROBE_JS`/H9/H10-пробах после `scrollIntoView` (иначе ложно-красные H9/shell8/H10).
- `tests/js/round1025_f11_status_grid_test.js` (**новый**) — node-маркеры `F11-STATUS-GRID-OK`/`F11-HEARTBEAT-OK`.
- `tests/test_webapp_f11_round1025.py` (**новый**) — 30 pytest-инвариантов.
- Маркер-пины bump обновлены атомарно: `tests/test_round1025_f8_registry.py` (routes-SHA → аддитивный пин `UI_STATUS_GRID_V2`; APP_VERSION), `tests/test_scope_selector_round1025.py`, `test_webapp_design_tokens/f6/f7/f9/hotfix6/7/8/9/10_round1025.py`, `tests/js/round1025_hotfix7/8/9/10_*.js`.
- `tests/test_webapp_round1014_ui.py` — `test_f4_third_ribbon_kept_inside_cognition` AMEND: граф §16 вынесен в строку 2 (виджет не потерян; 3 ленты §18 внутри «Мониторинга»).

### НЕ изменено (инварианты)
Схема БД/миграции, `services/param_catalog.py`, `web/static/execution_graph.js`, `/analytics/*`, §15-heartbeat (Canvas/rAF/пороги), log viewer (§20), §18-разметка, F6-страница «Аналитика», `main.scroll-area`. `web/api/routes.py` — **только аддитивно** (env-only bool `UI_STATUS_GRID_V2` в `ui_flags`, поле `counts` в `/api/status/logs`). `services/log_ring.py` — **только добавленный read-only** `LogRingHandler.level_counts()` (поведение `emit`/`get_entries` не менялось).

### Прогоны (факт)
- `node --check web/app.js` — rc=0.
- JS-тесты: **41/41 PASS**, 0 fail (в т.ч. `round1025_f11_status_grid_test.js`).
- `py -3 -m pytest -q` — **8451 passed, 5 failed, 1 skipped**. Все 5 failed **предсуществующие и не связаны с F11** (подтверждено на baseline-worktree `25cc19c`: те же 5 падают): `test_outgoing_guard_round1022.py` (2), `test_summary_cover_round1023.py` (3) — Telegram send-wrappers (сеть/прод-зависимые). Без этих двух модулей: **8393 passed, 1 skipped, 0 failed**.
- Playwright §70/§71 (`tools/ui_round1025_matrix.py`): 10 вьюпортов + fullscreen, `failures: 0`; F11-спаны 5/7/8/4 и строки §12 подтверждены реальными `boundingClientRect`; baseline-worktree `25cc19c` — тоже `failures: 0` (анти-регресс матрицы).
- `git diff --check` — чисто. Δ каталога=0 (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21). Δ DDL=0 (миграции/БД не менялись). `APP_VERSION` = 2.58.17.

### Не удалось выполнить локально
- §117 п.7–10 скриншоты/визуальная приёмка Liquid Glass/карты токенов — артефакты Playwright-скриншотов приложены (`tools/_ui_round1025_shots/*.png`), но **живая приёмка Telegram WebView/TMA — гейт владельца (T-3097)**; HTTP/локальный Chromium ≠ корректный UI в WebView.
- `F11-FU-DOSSIER-TS` (время/тип в `dossier_feed`) и `F11-FU-GRAPH-ALIAS` — осознанно вне F11 (follow-up, `services/**` не менялись).

## T-3093 [@Builder] — rework по findings @Reviewer B1/H-F11S-1 + @Scanner H/M/L (Step 5, 23.09.2026)

**Статус:** ✅ реализовано. Причина возврата — §20 «Ошибки/Предупреждения» показывал 0/1. Δ DDL=0, Δ каталога=0, `param_catalog.py` не тронут.

### H-F11S-1 (High, блокер) — реальные счётчики §20
- **Корень:** `count` в `/api/status/logs` = `len(entries)` **после** применения `limit`; при `limit=1` максимум 1. Плюс `level=WARNING` — порог «не ниже WARNING», т.е. включал ERROR/CRITICAL.
- **Правка (аддитивная, обратно-совместимая):**
  - `services/log_ring.py` — новый **read-only** `LogRingHandler.level_counts()` (точные числа по уровням по всему буферу, под тем же локом; `emit`/`get_entries` не менялись).
  - `web/api/routes.py` — `GET /api/status/logs` возвращает `{"count": …, "counts": ring.level_counts(), "logs": …}`; поле `count` сохранено как было.
  - `web/app.js` — `loadLogCounts` делает **один** запрос `?level=ALL&limit=1` и читает `counts.ERROR` / `counts.WARNING` (раздельная семантика: только ERROR / только WARNING); нет `counts`/сеть упала → «—», не 0.
- **Тесты «count > 1»:** `tests/js/round1025_f11_log_counts_test.js` (**новый**, маркер `F11-LOG-COUNTS-OK`): `counts={ERROR:5,WARNING:2}` → `5`/`2`, `WARN ≠ 7`, fail-open → `null`; `tests/test_log_ring.py::test_level_counts_*`; `tests/test_webapp_status_control.py::TestStatusLogsEndpoint::test_logs_counts_not_capped_by_limit` (`count==1`, при этом `counts.ERROR==5`, `counts.WARNING==2`).

### M-F11S-1 (Medium) — kill-switch задокументирован честно
- Осознанное решение: полный legacy-DOM под флагом **не** реализуется; OFF = **одноколоночный безопасный режим** (`.status-grid--legacy`), не byte-identical.
- Формулировки приведены к факту: `spec.md` (D5 §20, D6 kill-switch, §7/§9), `adr-1025-23` (D5/D6/контракты/обратимость/AMEND-карта), `web/app.js`, `web/index.html`, `web/static/app.css`.

### Low/Info
- **L-F11S-1:** строгий byte-freeze `web/api/routes.py` **восстановлен** — новая константа `ROUTES_SHA256_F11 = 76bcab3c96fec5c55c4f8ec4e50b30593fd91b98ca6322270c3a71dca5653306` (исторический `f8_baseline.json` не менялся, L-F9S-4).
- **L-F11S-2:** `UI_STATUS_GRID_V2` задокументирован в `.env.example`.
- **L-F11S-3:** полноэкранный граф — `Esc` (через `escClose` → `closeGraphFull`), initial focus (`_focusGraphFull`, `tabindex="-1"`, `ref="graphFullPanel"`, `focus({preventScroll:true})`), `aria-modal` уже был; тач-цели ≥44px (`.status-counts .btn-ghost`, `.status-graph-full .btn-ghost/.badge`). Полный focus-trap **не** добавлялся (Low, «если дёшево»): диалог — единственный верхний слой, фон затемнён overlay'ем, `Esc`/initial-focus доступны.
- **I-F11S-1:** мёртвая ветка `$refs.statusLogs` в `scrollToLogs` удалена (работает `#status-logs`).

### Изменённые/новые файлы (rework)
- Код: `services/log_ring.py`, `web/api/routes.py`, `web/app.js`, `web/index.html`, `web/static/app.css`.
- Тесты: `tests/js/round1025_f11_log_counts_test.js` (**new**), `tests/test_log_ring.py`, `tests/test_webapp_status_control.py`, `tests/test_webapp_f11_round1025.py`, `tests/test_round1025_f8_registry.py`.
- Док/операционка: `.env.example`, `spec.md`, `adr-1025-23-*.md`, `tasks.md`, `evidence.md`.

### Прогоны (факт, после rework)
- `node --check web/app.js` — rc=0; `node --check tests/js/round1025_f11_log_counts_test.js` — rc=0.
- JS: **42/42 PASS, 0 fail** (было 41 — добавлен `round1025_f11_log_counts_test.js`); маркеры `F11-LOG-COUNTS-OK`, `F11-STATUS-GRID-OK`, `F11-HEARTBEAT-OK`.
- `py -3 -m pytest -q tests/test_webapp_f11_round1025.py tests/test_log_ring.py tests/test_webapp_status_control.py tests/test_round1025_f8_registry.py` — **104 passed**.
- Полный pytest **без двух env-модулей**: **8399 passed, 1 skipped, 0 failed** (114.4 c). Два env-модуля отдельно: `test_outgoing_guard_round1022.py` + `test_summary_cover_round1023.py` → **5 failed, 58 passed** (предсуществующие ImportError aiogram rich-типы; `services/**` этих модулей не касался).
- `git diff --check` — OK (только LF/CRLF-warning Git, ошибок пробелов нет). Δ каталога=0 (REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21). Δ DDL=0 (`migrations/`/`alembic/` не тронуты).
- **Playwright не перезапускался** — в этом окружении не установлен; матрица/спаны подтверждены ранее артефактом `tools/_ui_round1025_raw.json` (review §13). Изменения rework DOM-геометрию сетки не затрагивают (правки — контент счётчиков/a11y-атрибуты/тач-цели).

### Не удалось выполнить локально
- Живой Telegram WebView/TMA (§117/§77) — **PENDING OWNER VERIFICATION (T-3097)**.

