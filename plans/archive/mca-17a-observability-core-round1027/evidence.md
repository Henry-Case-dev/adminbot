# `mca-17a-observability-core` — evidence (Builder, T-3864…T-3884)

> **Роль:** @Builder (реализация; итерация 2 — rework после `Needs Fixes`, F1–F4/Lows).
> **Deploy:** `DEFERRED_TO_RELEASE`. **Риск:** R3 (`threat-failure-analysis.md`).
> Секреты/сырой контекст не приводятся (R17).
>
> **Статус rework (review.md → build):** F1 (выдуманные события реестра) и F2
> (тихая потеря событий во flush) — **исправлены**; F3 (ложный зелёный UI) и F4
> (placeholder-строки) — **исправлены**; Lows F6 (master-aware фон), F8
> (`_track_incident` owner), F9 (двойное JSON), F10 (optional cancelled), F11
> (RBAC фильтров) — **исправлены**. **F5 — ЗАКРЫТО** по санкции @Architect
> (AMEND F5/ADR-1027-8 D16, spec §4.6/§4.10): read-only данные-API ядра
> (`registry_snapshot`/`active_incidents`/`incident_changes`) + refresh
> существующего индикатора инцидентов ≤10 с — **в scope `mca-17a`**; в `mca-17c`
> остаётся только представление. Детали — §6 (F5) и §4.

## 0. Baseline и текущее состояние

- **Reviewed-Commit (baseline):** `05bc8704c2de5e7de1d5d04ac34df763d35219aa`
  (`master`; `APP_VERSION` 2.58.31; DDL v18). **Анкер отката:** `7165ff7`.
- **Рабочее дерево:** предыдущие фичи (mca-14/13/01/03/02/04a/07) — незакоммичены
  (`DEFERRED_TO_RELEASE`), **не трогались**. `mca-17a` — только аддитивные правки
  поверх. **Коммитов/тегов/bump нет.**
- **DDL:** v18 → **v19** (санкция T-3862/ADR-1027-8 D2).
- **`plans/current_task.md` / `workflow_state.md` / `metrics.md` / `MEMORY.md`**
  не изменялись.

### Изменённые/новые файлы (mca-17a; sha256[:16] рабочего дерева)

**Новые:**
| файл | sha256[:16] |
|---|---|
| `services/mca_process_registry.py` | `61a17910926014ea` |
| `services/mca_trace.py` | `96c8c0e4b29c9c30` |
| `services/mca_incidents.py` | `12b25c11248d7aff` |
| `services/mca_watchdog.py` | `3da3c135f254269e` |
| `tests/test_mca17a_observability_core_round1027.py` | `eb3614d04f6f093e` |
| `tests/js/round1027_mca17a_observability_ui_test.js` | `928c36c490973301` |
| `tools/ui_round1027_mca17a_observability.py` | `16f70ae986d41922` |

**AMEND (аддитивно):**
| файл | sha256[:16] | что |
|---|---|---|
| `services/mca_events.py` | `e22c9fb9d1ee5712` | span-поля, v19-персистенция, spool/degraded/gaps, конкурентный своп-буфер (F2), master-aware фон (F6), pagination |
| `services/task_supervisor.py` | `a54ba23f88b154a0` | correlation/span/progress/requeue, fencing в cancelled/failed (L-MCA01-5) |
| `services/database.py` | `3eb2554db2148f16` | миграция v19 + DDL-константы |
| `services/mca_gates.py` | `220788d5cffc4db4` | 7 под-гейтов + fault-injection + пороги |
| `config/settings.py` | `5e7e11de0f4cfc97` | env-only `ClassVar` (гейты/пороги), Δ каталога=0 |
| `web/api/oversight.py` | `685e5e60614e9359` | `mca_metrics` (SC-13) + read-only данные-API ядра: `/processes`, `/incidents`, `/incidents/changes` (F5/D16) |
| `web/api/routes.py` | `f2ff90b650f18713` | аддитивные фильтры `/api/status/logs` + `events` (SC-14) + RBAC (F11) |
| `web/app.js` | `0ad05ed72e272c43` | фильтры/связ. события, honest-unknown (F3), polling инцидентов ≤10с (F5/D16) |
| `web/index.html` | `5edc3c222d1ea3e7` | блок `mca_metrics` (honest unknown, F3), фильтры log viewer |
| `bot.py` | `9414945271872b1b` | wiring фонового flush/prune + watchdog (startup/shutdown) |

**Вне diff (не тронуто):** `services/pg_db.py`, `param_catalog.py`,
`plans/current_task.md`, `workflow_state.md`, `metrics.md`, `MEMORY.md`,
чужие фичи.

## 1. Сделано по блокам

- **B (T-3864…T-3866):** v19 через реестр `mca-14`; `mca_pipeline_runs` (+3 idx),
  `mca_incidents` (+3 idx), 8 nullable `task_jobs` (+3 idx), 15 nullable
  `mca_events` (+3 idx); `mca_process_registry` **не создаётся**;
  code-declared реестр **41** процесса (10 закрытых/собственных +
  placeholders mca-09/10a/10b/11/15/16/18/19/20); durable job/run state через
  `write_transaction`.
- **C (T-3867…T-3870):** span-контракт §27.3 поверх `mca_events` (тот же store);
  correlation в `task_jobs` + resume; root job + batch spans (links+счётчики);
  монотонные часы/UTC/`event_sequence`.
- **D (T-3871…T-3874):** 9 состояний стадии + run `partial/degraded` +
  диагностическое `stalled`; контракт required/optional; linked job; ядро
  control-plane (cancel/resume/retry/refresh, идемпотентно, delivery_unknown).
- **E (T-3875…T-3877):** heartbeat≠progress; пороги 15s/60s + progress-stall по
  типу; watchdog (startup + периодически) → `recover_stale` (fencing bump);
  recovery по checkpoint; `delivery_unknown` — сверка, не слепой повтор.
- **F (T-3878…T-3880):** durable инциденты, fingerprint-группировка,
  `acknowledged ≠ resolved`, история; polling-cursor ≤10s; spool/degraded/gaps;
  R17-masking в error cause.
- **G (T-3881…T-3883):** carry-over §94.5 (SC-13/SC-14 REUSE viewer, живые
  продюсеры runtime-метрик, wiring flush/prune с обоими kill-switch); L-MCA01-5
  закрыт; 13 контролируемых сценариев §27.9.
- **H (T-3884):** `threat-failure-analysis.md`; deploy/rollback-раздел.

## 2. Тесты (фактические результаты)

| Прогон | Команда | Результат |
|---|---|---|
| Полный pytest `.venv` | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **9828 passed, 0 failed** (baseline 9758/0; +70 — новый suite) |
| Focused mca-17a | `pytest tests/test_mca17a_observability_core_round1027.py -q` | **70 passed** |
| Focused mca-01/13/14 | `pytest tests/test_mca01_… tests/test_mca13_… tests/test_mca14_… -q` | **75 passed** |
| JS vm-харнесс | `node tests/js/*.js` (по 1 файлу) | **48/48 OK** (baseline 47/47; +1 новый) |
| Browser-Verification (Playwright) | `.venv\Scripts\python.exe tools/ui_round1027_mca17a_observability.py` | **0 failures** (SC-13/SC-13b/SC-14, см. §4) |

### v19 — идемпотентность и сохранность

- fresh: `user_version == 19`; таблицы `mca_pipeline_runs`/`mca_incidents`
  созданы; `mca_process_registry` отсутствует; колонки `mca_events`/`task_jobs`
  присутствуют; `event_id`/`start`/`end` **не** добавлены.
- повторный `initialize()`: 1 ряд v19 в `schema_migrations` (no-op).
- legacy v18 (с откатом маркера и удалением новых таблиц): v19 применяется
  аддитивно, старые таблицы/ID не тронуты.
- новые nullable-колонки = NULL (честный unknown).
- PG — no-op (`pg_db.py` вне diff).
- Тесты: `test_v19_tables_and_user_version`, `…_columns_present`,
  `…_indices_present`, `…_idempotent`, `…_legacy_graceful`, `…_new_columns_nullable`.

### Re-pin (конвенция волн: только version/count/boundary)

Добавление v19 требует re-pin head-версии в тестах предыдущих ступеней
(`== 18` → `== 19`) — 16 файлов (`test_database.py`, `test_graphrag_database.py`,
`test_graph_*`, `test_history_migration_v7.py`, `test_memory_*`,
`test_migrate_*_script.py`, `test_multilayer_extraction_round1021.py`,
`test_agentic_ai_round1020.py`, `test_lore_compiler_round1020.py`,
`test_webapp_round1020_ui.py`, `test_mca03/04a/07_…`). Ослабления проверок нет —
только замена номера head-версии.

Cross-feature boundary-guards, заморозившие `web/api/routes.py`, обновлены
осознанно (санкционированный AMEND по ADR-1027-8 D13/§4.10): re-pin sha256
`ROUTES_SHA256_F11` (`test_round1025_f8_registry.py`) + исключение
`web/api/routes.py`/`web/api/oversight.py` из forbiddden-списков с NOTE
(`test_summary_deploy_round1026.py`, `test_summary_execution_graph_round1026.py`,
`test_summary_publish_integration_round1026.py`,
`test_tool_coordinator_round1026.py`, `test_unified_image_request_round1026.py`).
`test_mca01_…::test_write_points_go_through_single_writer` — count re-pin
`database.py: 122→129` (+7 санкционированных commit шага v19).

## 3. Watch-list закрытие

- **L-MCA01-5 (обязательный вход §95.5):** `TaskSupervisor.run()` передаёт
  `fencing_token=fence` в **cancelled** и **failed** путях (симметрично success);
  тест `test_supervisor_cancelled_path_passes_fence` + no-op устаревшего
  владельца `test_fencing_stale_owner_cannot_overwrite_terminal`.
- **Carry-over `mca-13` §94.5:**
  - **(1) UI SC-13** — `mca_events.metrics()` аддитивным блоком `mca_metrics`
    в `/api/oversight/summary` → `#/oversight` (REUSE, без новых endpoint);
  - **(2) UI SC-14** — аддитивные фильтры `trace_id`/`chat_id`/`component`/
    `reason_code`/`pipeline_run_id` + `events` в существующем
    `GET /api/status/logs`; переход к связанным событиям в log viewer;
  - **(3) живые продюсеры** runtime-метрик: `mca_trace.collect_runtime_metrics`
    (`rss_mb` из `memory_health`, `provenance_coverage`, `histories`/`episodes`
    из durable; `cache_entries` из `smart_cache`); отсутствующий источник →
    `None`/`available=false` (UNKNOWN ≠ 0);
  - **(4) wiring** `flush_events`/`prune_events` — `services/mca_watchdog`
    background-контур + `start_telemetry_flusher`/shutdown; уважает **оба**
    kill-switch (`MCA_EVENT_CONTRACT_ENABLED` + `MCA_TELEMETRY_STORE_ENABLED`);
    подключён в `bot.py` (startup/shutdown);
  - **(5) reassessment** «конкуренция записи»: триггер **сработал → R3**
    (зафиксировано в spec §7/ADR D15/threat H17a-2).
- **Регистрация стадий/виджет-ID закрытых фич** (`mca-03`/`02`/`04a`/`07`) —
  в code-declared реестре ссылками на фактические события
  (`owner_feature`/`stages_to_events`), без переизобретения.

## 4. Browser-Verification (SC-13/SC-14, `Browser-Verification: REQUIRED`)

- **Инструмент:** Playwright (Python), харнесс
  `tools/ui_round1027_mca17a_observability.py` (тот же локальный http-сервер +
  `Telegram.WebApp`-stub + перехват `/api/*`, что у существующего
  `tools/ui_round1025_matrix.py`; второго dev-стека нет).
- **Route/entry:** `#/oversight` (метрики), `#/` → блок логов (`#status-logs`,
  фильтры). Viewport 1280×800.
- **Actions/наблюдения (из `tools/_ui_round1027_mca17a.json`):**
  - SC-13: `#mca-metrics-block` присутствует; текст — `«Наблюдаемость (mca)»`,
    `«degraded: неизвестно»`, `«инциденты: 3 (2 не подтв.)»`,
    `«ошибок: 1 · gaps: 2 · spool: 0»`, `«нет данных: cache, runtime,
    provenance»` → группа без продюсера честно «неизвестно», не 0/«здоровье»;
  - SC-14: `#mca-log-filters` присутствует; после заполнения `trace_id=run_ab`
    и «Связанные события» появился `#mca-related-events` с событиями
    `LLM_CALL`/`PIPELINE_START` и `run_ab` (deep link на trace);
  - **SC-13b (F3):** при `mca_metrics.available=false` после рефетча бейджи
    метрик — `badge-muted` (нет `badge-ok`), текст «degraded: неизвестно»,
    «ошибок: неизвестно · gaps: неизвестно · spool: неизвестно» → честный
    unknown, старый «зелёный» не сохраняется;
  - **SC-16 (F5/D16):** при открытом `#/oversight` существующий индикатор
    инцидентов обновляется read-only `GET /api/oversight/incidents/changes` с
    cursor-параметром; за ~3.4 с зафиксировано `changes_calls=[0,1,2,3,4,5]`
    (интервал демо-сервера 1 s; клиент клампит ≤10 s) → доставка ≤ `push_interval`
    и reconnect-догон по cursor.
  - **Registry snapshot API** (§4.10) — **backend-only claim** (браузер не
    требуется; покрыт API-тестами).
  - скриншот: `tools/_ui_round1027_mca17a.png`.
- **Console:** `baseline_console_errors=2` — единственная ошибка
  `TypeError: execMetricsRows is not a function` **воспроизводится на ЧИСТЫХ
  baseline web-файлах** (проверено прогоном харнесса против откаченных
  `web/app.js`/`web/index.html` через `git stash`); это **pre-existing дефект
  чужой фичи** (token-flow: `execMetricsRows` в `computed`, вызван как функция);
  к mca-17a не относится и не является mca-17a-регрессом. Любых **других**
  console/pageerror нет.
- **Live TMA-приёмка** (реальный Telegram WebView) — `PENDING OWNER VERIFICATION`
  (как у сопредельных фич):
  Chromium ≠ Telegram WebView; автоматизированный контур проверяет структуру/поведение.

## 5. Не проверено / ограничения (честно)

- **Нагрузочный замер** конкуренции single-writer lock под прод-объёмом (R3),
  полный `DB_LOCK_RESILIENCE_ENABLED=false` сценарий — **на `mca-release`**.
- **Полный e2e takeover** на реальном внешнем супервизоре процессов — релизный.
- **Live TMA WebView** — `PENDING OWNER VERIFICATION`.
- **UI-панели** «Обзор процессов/Запуски/Инциденты» и диагностические действия
  (A54/A56/A57/A73) — **вне scope** `mca-17a` (за `mca-17c`); `mca-17a`
  поставляет backend-предпосылки.

## 6. Rework (Needs Fixes → build, итерация 2)

| Finding | Severity | Фикс | Проверка |
|---|---|---|---|
| **F1** — реестр объявлял вымышленные события закрытых фич (32 из 87 не встречались в коде) → активные процессы навсегда `not_run` | High | `event_names`/`stages_to_events` приведены к **реально эмитируемым** именам: mca-03 → `message_revision`/`message_identity_migration`; mca-02 → `safe_fetch`; mca-04a → `memory_provenance`; mca-07 → `mca07_retrieval/reranker/bundle/budget`; mca-17a → `WATCHDOG_*`/`INCIDENT`; прочие процессы — пустые `instrumentation`/`event_names` → честный `not_instrumented` (без выдуманных имён) | `test_registry_event_names_exist_in_code` (grep-сверка: ни одного вымышленного), `test_registry_real_events_flip_closed_features_to_implemented` (реальное событие → `implemented` для mca-02/03/04a/07) |
| **F2** — `flush_events` терял события, эмитированные во время `await` (`_pending.clear()`); dropped/gaps=0 | High | **своп-очередь**: снимок + `_pending.clear()` выполняются синхронно (без `await` между ними), поэтому события, эмитированные во время записи, попадают в уже пустую очередь и не теряются; failure-ветка spool'ит снимок, новые остаются; счётчики корректны | `test_flush_concurrent_emit_not_lost` (1 + 2 конкурентных = 3 записаны), `test_flush_failure_keeps_new_events` |
| **F3** — UI при недоступной телеметрии показывал «зелёный» `badge-ok`/«degraded undefined» | Medium | `web/index.html` + `web/app.js`: `mcaMetricsBadge`/`mcaDegradedLabel`/`mcaErrorsLabel` → при `available===false`/`degraded_share===null` **`badge-muted`** + «неизвестно» | JS-тест (F3-ассерты) + browser SC-13b (badge-muted, honest unknown) |
| **F4** — нет placeholder-строк `mca-10a/10b/11/15` | Medium/Low | добавлены 4 строки `version="0"` → `not_run` | `test_registry_future_features_not_run` (owners ⊆ mca-09/10a/10b/11/15/16/18/19/20) |
| **F6** — master OFF не гасил фон flush/prune | Low | `_telemetry_enabled()` учитывает `MCA_OBSERVABILITY_ENABLED`; финальный flush на shutdown — тоже под гейтом | расширен `test_flush_and_prune_respects_both_kill_switches` |
| **F7** — прокси/тавтологичные тесты | Low | `test_supervisor_cancelled_fencing_noop_after_takeover` (поведенческий takeover + cancelled no-op), `test_scenario_shared_task_multiple_consumers` (реальные links в durable-строке) | focused mca-17a |
| **F8** — `_track_incident` хардкод `archive.rebuild` | Low | `pipeline_type` берётся из `owner` job (разные типы не сливаются) | `test_watchdog_incident_uses_job_owner` |
| **F9** — двойное JSON-кодирование `linked_span_ids` | Low | `emit_stage` передаёт список как есть; `build_event` сериализует один раз | `test_linked_span_ids_single_encoding` |
| **F10** — optional `cancelled` давал run `cancelled` | Low | `compute_run_outcome`: только **обязательная** cancelled/interrupted → run cancelled/interrupted; optional → `degraded`/`partial` | расширен `test_compute_run_outcome_contract` |
| **F11** — фильтры `/status/logs` отдавали `mca_events` не-админам | Low | новые `events` — только для глобального админа (`_is_global_admin`, fail-closed); не-админ → `events=[]` + `events_restricted=true` | `test_status_logs_events_requires_global_admin` |
| **F5** — доставка инцидентов ≤10 s и read-only API реестра | Medium (граница) | **ЗАКРЫТО** по санкции @Architect (AMEND F5/ADR D16): read-only данные-API ядра на **существующем** роутере `oversight` — `GET /processes` (реестр, гейт `MCA_PROCESS_REGISTRY_ENABLED`), `GET /incidents` (гейт `MCA_INCIDENTS_ENABLED`), `GET /incidents/changes?since_ts` (гейты incidents+push); RBAC `requires_global_admin`; fail-open shape; R17-safe. Клиент: refresh существующего индикатора через `incident_changes` (cursor, ≤10 с), без новой панели/маршрута | backend-тесты `test_endpoint_*` (4) + JS `F5`-ассерты + browser SC-16 (`changes_calls=[0..5]`) |

### 6.1. F5 — read-only данные-API ядра (детали)

| Метод/путь | Гейты | RBAC | Форма (fail-open) |
|---|---|---|---|
| `GET /api/oversight/processes` | `MCA_PROCESS_REGISTRY_ENABLED` | global admin (`requires_global_admin`) | `{available, enabled, count, processes[], pipelines[], coverage{}}`; OFF → `available=false`, пустые списки; R17: только имена настроек |
| `GET /api/oversight/incidents?limit=` | `MCA_INCIDENTS_ENABLED` | global admin | `{available, enabled, incidents[], push_interval_seconds}` |
| `GET /api/oversight/incidents/changes?since_ts=&limit=` | `MCA_INCIDENTS_ENABLED`+`MCA_INCIDENT_PUSH_ENABLED` | global admin | `{available, enabled, cursor, changes[], indicator{}, push_interval_seconds}`; OFF → нет обновлений (`enabled=false`) |

Refresh индикатора: `startIncidentPolling()` (в `setTab('oversight')`) — само-пере-планирующийся `setTimeout`-цикл, интервал `min(push_interval_seconds, 10)` с; первый запрос с `since_ts=cursor`, далее — с обновлённым курсором (reconnect-догон); `enabled=false` → цикл останавливается (паритет); `stopIncidentPolling()` — при уходе с вкладки/`beforeUnmount`.

## 7. Как воспроизвести

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider          # 9828/0
.venv\Scripts\python.exe -m pytest tests/test_mca17a_observability_core_round1027.py -q  # 70
Get-ChildItem tests/js -Filter *.js | ForEach-Object { node $_.FullName }  # 48/48
.venv\Scripts\python.exe tools/ui_round1027_mca17a_observability.py  # 0 failures (SC-13/13b/14/16)
```

_Создано @Builder (T-3884; обновлено в rework-итерации 2). `plans/current_task.md`/`workflow_state.md`/`metrics.md`/`MEMORY.md` не изменялись; секреты не цитировались (R17)._
