# M4B B2 — «Обзор»: KPI/воронка, решения, проверка, последний вызов

- Дата: 2026-11-21, Builder.
- База: production **`275a1b7cd320f67e0ac089d8d5c4b14ca31dbcfa` / 2.58.224**
  (B1 выкачен; 5 лент/сетка сохранены).
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\mod-acl-ux-01-m4b2-fb6b9cda16d7-65c53857`
- Ветка: `release/mod-acl-m4b2-2.58.225` (без bump/deploy).
- Schema: **48**, DDL **0** (D1/D3 read-only; новых таблиц/полей нет).
- Кандидат: **`db92c73ce122ee09a461696ba4d0a8c69b07cbb6`** (ветка
  `release/mod-acl-m4b2-2.58.225`; без bump/deploy).

## 1. Что изменено

### 1.1. D1 — `/api/analytics/usage/latest` (approved, read-only, DDL 0)

`web/api/analytics.py`:

- `_SELECT_STEPS_SQL` аддитивно читает из существующей колонки
  `llm_usage_events.plan_meta`:
  `latency_ms`, `l1_failure_mode`, `l1_finish_reason` (`->>`; NULL → NULL).
- `_step_row()` отдаёт nullable `latency_ms` (float | None),
  `l1_failure_mode` (str | None), `l1_finish_reason` (str | None).
- Без второго endpoint/store; R17-whitelist уже применён при записи
  (`services/usage_events.sanitize_plan_meta`). Старые строки без `plan_meta`
  и битое значение `latency_ms` дают `None`, не `0`.
- `/analytics/execution/latest` использует тот же `_step_row` — аддитивные поля
  не меняют граф.

### 1.2. D3 — `/api/memory/intel-funnels` (approved, read-only, DDL 0)

`web/api/memory_overview.py`:

- `_initiative_domains(init_job, init_events)` — серверное объяснение
  «0 активных намерений при N публикациях»: `intents` (durable snapshot,
  `created_total`, `active_source=status.intents.active`), `publications`
  (`initiative_sent` события 24ч/7д), `same_cohort=false`, `explain`.
- `initiative.domains` добавлен в существующий ответ; UI использует
  `domains.explain` (fallback — та же семантика для старого backend).

### 1.3. UI «Статус» (`web/app.js`, `web/index.html`, `web/static/app.css`)

- Health-лента: deployed revision (`statusData.bot.version`) и серверный
  checked-at (`uptime.generated_at`) — `data-status-observed/version/checked-at`.
- Observer:
  - вместо 8-стадийной `.funnel-grid` — **6 независимых KPI** (`data-observer-kpi`)
    с окном (`всего (durable)` / `24ч` / `сейчас (снимок)`), scope и снимком;
  - явная подпись «это независимые числа, а не конверсия»;
  - две сущности (`data-observer-entity="intents|publications"`) и D3 explain;
  - «Почему сейчас ничего не опубликовано?» (`data-observer-why`) с
    title/warning/recommendation; health ≠ outcome;
  - топ-5 причин кликабельными `<details data-observer-reason>` + полный
    список `data-observer-all-reasons`;
  - последние 5 решений (`data-observer-decision`) с датой/action/причиной/
    доставкой; полный ledger (`data-observer-ledger`) с отказами/доставками;
  - «Проверить инициативу»: постоянное пояснение mock vs real (`data-initiative-help`),
    trace в раскрытии (`data-initiative-trace`), dry-run не выдаётся за отправку.
- «Последний вызов»:
  - `execPreview` states `ok|empty|unavailable`, checked-at, причина unknown;
  - data: 1–2 строки `время · модуль · модель · результат/латентность ·
    вход/выход · стоимость`; cost только при `price_known`, `tokens_estimated`;
  - `l1_failure_mode`/`l1_finish_reason` — error/финиш; correlation_id и полный
    список шагов в `data-exec-technical`; ссылка в Аналитику (`?tab=models`);
  - image-only называется отдельно (`data-exec-image`), mixed — отдельная
    строка изображения; per-chat/global не смешиваются (badge `global`);
  - no-data/503 — компактная строка, без `min-height` 300–500;
    CSS `align-self:start` для `.status-grid > .status-sleep/.exec-preview`.
- CSS: `.funnel-grid/.funnel-cell` удалены; `.observer-kpi__cell` использует
  `--table-*`; причины — touch ≥44px.

## 2. RED на базе `275a1b7c`

См. `red-base/`. Кандидатные тесты на базовом `web/`:

- `m4b_observer_test.js` — rc=1 (`funnel-grid` есть, `data-observer-kpis` нет).
- `m4b_lastcall_test.js` — rc=1 (`data-exec-preview` нет).
- `asap8_v63_w3_status_logs_test.js` — rc=1 (`observer-kpi` CSS/разметки нет).
- `soul1_w5_initiative_panel_test.js` — rc=1 (KPI-маркера нет).
- `test_webapp_m4b_b2_api.py` — **4 failed / 1 passed**:
  D1 `KeyError: latency_ms` (3 теста), D3 `KeyError: domains`.

## 3. Кандидатные проверки

| Проверка | Результат |
|---|---|
| Mandatory 24-file pytest (`tests/test_round1025_f8_registry.py` … `tests/test_webapp_js_unit.py`) | **386 passed, 0 failed** |
| Targeted node B2 + W3/W5/F6/B1 | **6/6 rc=0**: `MOD-ACL-UX-M4B-B2-OBSERVER-OK`, `...-LASTCALL-OK`, `W3-STATUS-UNIT-OK`, `SOUL1-W5-PANEL-OK`, `F6-ANALYTICS-MEMORY-OK`, `MOD-ACL-UX-M4B-B1-FEEDS-OK` |
| Python D1/D3 + regression (`test_webapp_m4b_b2_api`, analytics, memory overview, f6) | **94 passed, 0 failed** (artifact `94 passed`; NB-1: the earlier 110 was a counter error, tests unchanged) |
| Broad JS `tests/js/*_test.js` | **127 files, 124 passed, 3 failed** — те же pre-existing: `evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings` |
| B1 Playwright e2e (`ui_mod_acl_m4b_status_e2e.py`) | **138 checks, 0 failures** |
| B2 Playwright e2e (`ui_mod_acl_m4b2_status_e2e.py`) | **92 checks, 0 failures**; 1920/1440/1280/768/390/320; no-data/503/image-only/chat-scope |
| W3 status e2e (updated consciously) | **OK**; `observer_kpis`, `observer_no_funnel`, observed 420, liveness, domains explain; `initiative_decisions` не входит в W3 |
| W10 sections e2e | те же **3 pre-existing** module/catalog failures |
| W15 composition e2e | **71 fails**, 0 status/observer-related; `observer-kpi__cell` token check passes; count is environment-dependent (B1 stand: 72) |
| `git diff --check -- web tests tools`, `node --check web/app.js`, `py_compile` | rc=0 only for the scoped paths; full-range diff still shows evidence trailing whitespace (NB-1, docs-only) |

### 3.1. Мутации (temp backup → mutate → test → restore)

`mutations.json`: **4/4** ожидаемо красные, после restore зелёные:

1. `kpis = kpis.slice(0, 5)` → observer test rc=1.
2. Вернуть `funnel-grid` в разметку → observer test rc=1.
3. `min-height: 320px` у `.exec-preview` → lastcall test rc=1.
4. `scopeLabel: 'чат'` вместо `global` → lastcall test rc=1.

## 4. Browser Use (реальный Chrome, локальный стенд)

`browse` relay: Brave on this computer, connected. Байты кандидата + синтетический
API (`ui_round1025_matrix` + B2 stubs), не live TMA.

- 1440: `[data-observer-kpi]` = **6**, `.funnel-grid/.funnel-cell` = **0**,
  `data-exec-state=ok`, `data-status-observed` = «Версия: 2.58.225 ·
  проверено: 21.11.2026, 00:00:00», page overflow = false.
- 390 (mobile emulation): 6 KPI, overflow = false, exec height 251 px,
  sleep 364 px (independent), health visible.
- Reason click: first reason opens `code=min_gap`.
- «Проверить инициативу»: trace = «Проверка без отправки в чат (mock): реальная
  отправка выключена настройкой владельца… прогон без публикации ·
  LLM-вызовов: 2»; `РЕАЛЬНАЯ` отсутствует.
- Ограничение: локальный стенд/синтетический API, не production TMA; реальные
  `plan_meta.latency_ms` появятся только при наличии данных.

## 5. Соответствие строкам

- `MAC-S6-306` — version/checked-at в health.
- `MAC-S6-309`, `MAC-S6-FUN-02` — компактный observer, KPI-row/причины/решения,
  без 8-стадийной простыни.
- `MAC-S6-331` — ≤6 KPI с окном/scope/снимком.
- `MAC-S6-332`, `MAC-S6-FUN-01`, `MAC-AC-14` — псевдо-конверсия не рисуется;
  параллельные счётчики и явная подпись; `same_cohort=false`.
- `MAC-S6-333`, `MAC-S15-02` — две сущности; D3 `domains.explain` (0 intentions
  vs N publications — нормальное состояние домена).
- `MAC-S6-334` — топ-5 кликабельных причин + «Все причины» + why-блок.
- `MAC-S6-335` — 3–5 последних решений с датой/action/причиной/доставкой;
  полный ledger в раскрытии.
- `MAC-S6-336` — пояснение проверки mock/real, trace в раскрытии.
- `MAC-S6-344`, `MAC-S15-01`, `MAC-S0-11` — компактный unknown с checked-at/
  причиной, без пустого квадрата.
- `MAC-S6-345`, `MAC-AC-15` — D1 latency/error/finish, честная unknown-цена,
  correlation_id; **D2**: отдельной трасс-страницы нет — ссылка в Аналитику и
  correlation_id, не VERIFIED по «полной трассе».
- `MAC-S6-346` — image-only отдельно; per-chat/global не смешиваются.
- `MAC-S6-347` — независимые высоты sleep/last call.

Строки **не объявляются VERIFIED**: нужен независимый Reviewer. `MAC-S6-345`
и `MAC-AC-15` остаются частичными по «ссылке на полную трассу» (D2: источника
нет). `MAC-S6-346` image-only — детерминированный stub, натуральное событие
не фабриковалось (RFL-кандидат).

## 6. Ограничения / out-of-scope

- Playwright/Browser Use — локальный стенд с синтетическим API; production
  байты проверяются после deploy.
- D1 latency отсутствует у старых строк/без `plan_meta` — это честный unknown.
- 503 и image-only — stub-состояния; натуральные события не создавались.
- W10 (3) и W15 (71 в этом прогоне; 72 на стенде B1 — счётчик
  зависит от окружения) полные инструменты имеют pre-existing failures, не
  связанные с B2; B1/W2a/W2c/W3 контракты не регрессированы.
- Backend/API/DDL/flags/prompts/storage: только D1/D3 read-only; bump/deploy
  не выполнялись.

## 7. Находки Reviewer B2 r1 (evidence-only правки)

Вердикт: **APPROVED_FOR_RELEASE_PREPARATION** (кандидат tip `09ef444d8`,
product `db92c73ce`). В этом кандидате исправлены только evidence-счётчики;
product/test/e2e-код не менялся.

- **NB-1 (исправлено в evidence):** D1/D3-счётчик исправлен **110 → 94**
  (артефакт `test-output/pytest-d1-d3-regression.txt`: `94 passed`);
  `git diff --check` rc=0 только для `-- web tests tools`, полный diff
  по-прежнему содержит trailing whitespace в evidence-документах (NB-1),
  это docs-only.
- **NB-2 (исправлено в evidence):** W15 исправлено **72 → 71** с пометкой
  о зависимости от окружения; 0 падений, связанных со status/observer.
- **NB-3, NB-4, NB-5, NB-6, BL-1:** nonblocking follow-ups/B3, в этом
  кандидате и релизной сборке **не исправлялись**.
