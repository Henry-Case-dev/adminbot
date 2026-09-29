# `mca-17a-observability-core` — threat & failure analysis (R3, T-3884)

> **Уровень риска:** **R3** (ADR-1027-8 D12/§7; reassessment carry-over §94.5 п.5
> сработал). Основание R3: ядро наблюдаемости лежит на общем write-path/очереди
> событий/durable job state — `flush_events` в фоновом контуре конкурирует за
> single-writer lock с direct flow, watchdog/takeover меняет durable-статусы,
> инциденты пишутся в ту же SQLite, миграция v19 меняет схему.
> **Deploy:** `DEFERRED_TO_RELEASE` (§20).
> **Секреты (R17):** документ не содержит токенов/сырого контекста; только
> имена компонентов и режимы отказа.

## 1. Активы и границы

| Актив | Где | Почему важен |
|---|---|---|
| Общий write-path SQLite (single-writer) | `services/database.py::write_transaction`/`serialized()` (§95) | конкуренция записи телеметрии и direct flow |
| Очередь событий | `services/mca_events.py` (`_pending`, spool, `mca_events`) | durable-полнота/потеря событий |
| Durable job state | `task_jobs` (v14+v19), `mca_pipeline_runs` (v19) | takeover/fencing/recovery, отсутствие дублей |
| Инциденты | `mca_incidents` (v19) | grouping, `acknowledged ≠ resolved`, история |
| Схема БД | миграция v19 через реестр `mca-14` | аддитивность/идемпотентность, сохранность данных |
| UI-витрина | `#/oversight` (`mca_metrics`), log viewer (`/api/status/logs` фильтры) | честный статус (`unknown ≠ 0`), нет ложного «зелёного» |

**Вне scope:** второй store/аналитика/`TaskSupervisor`/write-механизм (GEN-R19/R21);
`pg_db.py`/`param_catalog.py` (вне diff); SSE/WS (инфраструктуры нет → polling);
UI-панели «Инциденты/Запуски» и диагностические действия (mca-17c).

## 2. Угрозы и режимы отказа

| # | Угроза / режим отказа | Вектор | Обнаружение | Митигиция (код) | Остаточный риск |
|---|---|---|---|---|---|
| H17a-1 | Запись результата устаревшим владельцем после takeover | stale lease + медленный worker | `fencing_token` mismatch → no-op | fencing во **всех** терминальных записях `TaskSupervisor.run()` (success/cancelled/failed) — **L-MCA01-5 закрыт**: `_safe_finish(..., fencing_token=fence)` (`services/task_supervisor.py`); `recover_stale` бампает токен | низкий (no-op тест) |
| H17a-2 | Конкуренция записи телеметрии с direct flow (single-writer) | `flush_events` в фоне/после `write_transaction` | рост `database_lock_retry/exhausted`, `telemetry_degraded` | bounded `_pending` (256) + короткая tx в фоне (не на hot-path), writer lock не удерживается во время сети/LLM; **reassessment §94.5 → R3** | средний (нагрузка) — релизный замер |
| H17a-3 | Потеря событий при недоступном хранилище | ошибка `write_transaction` | `telemetry_degraded`, `spooled_total`, `gaps_total` | ограниченный дисковый spool (`MCA_TELEMETRY_SPOOL_MAX_EVENTS`, default 2000) + дренаж при восстановлении; переполнение → **gaps** (не бесконечный RAM) | низкий; при исчерпании spool — видимый gap |
| H17a-4 | Ложный полный trace при отсутствии части событий | ретенция/spool/ошибка записи | `gaps_total > 0`, `unknown`-группы | «детали удалены по сроку хранения»; часть отсутствует → trace не подаётся полным; `available=False`/`None` (UNKNOWN ≠ 0) | низкий |
| H17a-5 | Ложный «зелёный» статус при потере backend | stale/unknown телеметрии | `telemetry_freshness` (`stale`/`unknown`) | UI при потере backend → `telemetry stale/unknown`; анимация не продолжается на stale | низкий |
| H17a-6 | Takeover без проверки владельца/состояния | stale lease | `WATCHDOG_SWEEP`/`WATCHDOG_TAKEOVER` | подозрение → `recover_stale` (interrupted + fencing bump) → safe retry; проверка durable state periodically **и на старте** | низкий |
| H17a-7 | Слепой повтор внешнего side effect / платной операции | `delivery_unknown` | `reason_code=delivery_unknown` | `recover_job`/`control_action` → `reconcile_required` (сверка по operation ID), не повторяет; `mark_delivery_unknown` | низкий |
| H17a-8 | Дубли результата при shared/singleflight | общий кеш-результат | `linked_span_ids` | links вместо одного ложного владельца; parent-child — только реальное вложение | низкий |
| H17a-9 | Скрытый «успех» async-продолжения | незавершённая дочерняя задача | `run` остаётся `running` при `pending_children>0`/незафиксированной записи | linked job (pending) вместо success; контракт pipeline version `required/optional` | низкий |
| H17a-10 | Ложный success при сбое необязательной ветви | ошибка optional-стадии | stage `failed/skipped` + `has_fallback` | `compute_run_outcome` → `degraded`/`partial` с описанием; обязательная невыполнена → `failed`/`interrupted` | низкий |
| H17a-11 | Ложная авария длительной законной операции | общий stale-таймер | `progress_stall` по типу стадии | пороги LLM/видео/архив/env (`MCA_PROGRESS_STALL_<TYPE>_SECONDS`); heartbeat ≠ progress; video не «упал» через минуту | низкий |
| H17a-12 | Отравление инцидентов (слияние разных симптомов) | группировка по слову «timeout» | разные fingerprint | fingerprint = `process_id|pipeline_type|stage|reason_code|error_type|dependency` (без свободного текста); отдельные trace | низкий |
| H17a-13 | Скрытие сбоя основного пути успешным fallback | fallback скрывает ошибку | `fallback_used` + severity | fallback понижает severity/impact, но инцидент остаётся; `acknowledged ≠ resolved`; история сохраняется | низкий |
| H17a-14 | Утечка секретов в новый trace/incident/экспорт | `checkpoint_ref`/`error_json`/`component` | regex `sk-*` в caplog/durable-строке | `sanitize()` до записи во все каналы (build_event/JSON-поля/error cause); маскировка не удаляет техническую причину | низкий |
| H17a-15 | Несовместимая/разрушительная миграция v19 | DDL | `user_version`, `sqlite_master`, `PRAGMA table_info` | аддитивно/идемпотентно через реестр `mca-14`; guard; повторный прогон no-op; старые таблицы/ID/vec не трогаются | низкий |
| H17a-16 | Дрейф реестра процессов от кода | вторая копия в БД | runtime-сверка | реестр **code-declared** (D1), таблица `mca_process_registry` не создаётся; runtime-статус вычисляется на чтении | низкий |
| H17a-17 | Fault injection как product-функция | production-включение | env `MCA_FAULT_INJECTION_ENABLED` | default **OFF**, dev/test-only, не виджет/не process; вне effective-state §20.2 | низкий |
| H17a-18 | Отказ control-plane меняет чужое состояние | cancel/resume/retry | audit-событие `CONTROL_ACTION` | только разрешённые job-типы; RBAC у вызывающего API (mca-17c); идемпотентно; интерфейса произвольного кода/SQL нет | низкий |
| H17a-19 | Детект недоступности процесса в заблокированном loop | сам watchdog | `external_observer` | детект вне loop (REUSE `uptime_heartbeat` + внешний менеджер); при отсутствии наблюдателя ограничение отражается явно | низкий |
| H17a-20 | Исчерпание диска spool/инцидентами | рост JSONL/таблиц | ретенция/`gaps` | bounded spool + ретенция MCA-13 (14/90) + `prune_events`; incidents — без удаления истории (bounded jobs/chats) | низкий |

## 3. Failure-матрица §27.9 (контролируемые сценарии)

| Сценарий | Режим | Ожидаемое наблюдаемое | Тест |
|---|---|---|---|
| timeout провайдера | `failed`/`provider_unavailable` | error_json.retryable/recovery | `test_scenario_provider_timeout` |
| невалидный JSON | `failed`/`rerank_invalid` | errors_total | `test_scenario_invalid_json` |
| ошибка записи после LLM | незафиксированная запись | run **не** success | `test_scenario_write_error_after_llm` |
| отмена parent/child | parent cancelled | child не скрыт | `test_scenario_cancel_parent_child` |
| гибель worker между checkpoint и terminal | interrupted→resume | checkpoint прочитан | `test_scenario_worker_dies_between_checkpoint_and_terminal` |
| рестарт | durable correlation | pipeline_run_id сохранён | `test_scenario_restart_resume` |
| потеря heartbeat | stale lease | takeover | `test_scenario_lost_heartbeat` |
| живой heartbeat без прогресса | progress-stall по типу | stall профиля; video не «упал» | `test_scenario_live_heartbeat_no_progress` |
| сбой log storage | недоступное хранилище | degraded/gaps | `test_scenario_log_storage_failure_gap` |
| reconnect миниаппа | polling cursor | нет повторной доставки | `test_scenario_miniapp_reconnect_cursor` |
| ошибка одной ветви | optional failed | `partial` | `test_scenario_branch_error_not_erasing_success` |
| неясный результат отправки | delivery_unknown | reconcile, не слепой retry | `test_scenario_delivery_unknown_scenario` |
| shared task на нескольких потребителей | links | без ложного владельца | `test_scenario_shared_task_multiple_consumers` |

## 4. Вывод

- R3 подтверждён; обязательные митигиции (bounded spool, fencing во всех
  терминальных записях, single-writer для фонового flush, polling-cursor,
  R17-masking, аддитивная идемпотентная миграция) реализованы и покрыты
  тестами.
- **Unavailable (релизные, вне gate):** нагрузочный замер конкуренции
  single-writer lock под прод-объёмом; полный e2e takeover на реальном
  внешнем супервизоре процессов — на `mca-release`.
- **Carry-over:** `MCA_PROGRESS_STALL_*` и `MCA_JOB_*` — env-only, в effective
  state §20.2 фиксируются как пороги (не product-функции).

## 5. Rework-амендменты (Needs Fixes → build, итерация 2)

| Угроза | Изменение после rework |
|---|---|
| H17a-3/H17a-4 (потеря событий/gaps) | **F2:** своп-очередь (`flush_events` снимок+очистка синхронны) — события, эмитированные во время `await write_transaction`, не теряются; failure-ветка spool'ит снимок. `gaps` инкрементируется только при фактической потере (spool недоступен/переполнен). |
| H17a-2/H17a-19 (конкуренция записи) | Без изменения сути: bounded swap + короткая tx; master OFF (`MCA_OBSERVABILITY_ENABLED`, F6) полностью гасит фон → baseline-паритет. |
| H17a-16 (дрейф реестра от кода) | **F1:** реестр объявляет только фактически эмитируемые имена событий; регресс-тест `test_registry_event_names_exist_in_code` (grep-сверка с кодом) ловит любое вымышленное имя; процессы без инструментирования — честный `not_instrumented`. |
| H17a-5 (ложный «зелёный» при потере backend) | **F3:** при `mca_metrics.available=false`/неполноте UI показывает `badge-muted` + «неизвестно» (не `badge-ok`); browser-сценарий SC-13b. |
| H17a-12 (слияние разных симптомов инцидентов) | **F8:** fingerprint watchdog-инцидента берёт `pipeline_type` из `owner` job (а не хардкод) — разные типы не сливаются. |
| H17a-14 (утечка/утечка доступа) | **F11:** связанные `mca_events` по фильтрам `/api/status/logs` — только для глобального админа (fail-closed; chat isolation). |
| H17a-9/H17a-10 (честный итог) | **F10:** optional `cancelled`/`interrupted` с fallback → `degraded`/`partial`, а не run `cancelled`/`interrupted`. |
| H17a-18 (control-plane/RBAC) | Без изменения (ядро; control-plane UI — mca-17c). **F5 — ЗАКРЫТО** санкцией @Architect (AMEND F5/ADR D16): read-only данные-API ядра (`/processes`, `/incidents`, `/incidents/changes`) на существующем роутере `oversight`, RBAC global-admin, fail-open, R17-safe; refresh индикатора ≤10 с с cursor-догоном. Новых рисков не вводит (read-only; второй store не создаётся). |
| H17a-21 (доставка инцидентов: утечка/шум) | Новый endpoint `incident_changes` — RBAC global-admin; только миниапп; stack traces не публикуются; bounded `limit`; cursor-сверка предотвращает повторную доставку. |

_Создано @Builder в рамках T-3884 (`mca-17a-observability-core`; обновлено в rework-итерации 2); `current_task.md`/`workflow_state.md`/`metrics.md`/`MEMORY.md` не изменялись; секреты не цитировались (R17)._
