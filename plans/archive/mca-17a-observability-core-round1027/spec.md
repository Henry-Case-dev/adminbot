# `mca-17a-observability-core` — спецификация (Step 2 @Architect, T-3861/T-3862)

- **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 0 (фундамент) — остаток** (после `mca-14` §93, `mca-13` §94, `mca-01` §95). **Фича-ID:** `mca-17a-observability-core`.
- **Тип:** backend/data — runtime-реестр процессов, расширение контракта событий `mca-13` до сквозного trace/span, durable job lifecycle (root job + batch), heartbeat/watchdog/recovery поверх `TaskSupervisor`, инциденты и их доставка в существующий миниапп, хранение/полнота/безопасность телеметрии. **Потребитель** контрактов `mca-13` (§94: `emit_mca_event`/`mca_events`, `reason_code`, `sanitize()`, ретенция 14/90) и `mca-01` (§95: `TaskSupervisor`/`task_jobs`/fencing/generation/coalescing, единый write-механизм). **Предпосылка** для `mca-04b`, `mca-06`, `mca-16`, `mca-18`, `mca-19` и `mca-17c`.
- **Источник (IMMUTABLE, НЕ изменяется; R17/R18):** `plans/current_task.md` v1.8 **§27.1** (`:1331–1364`), **§27.3** (`:1386–1398`), **§27.4** (`:1400–1410`), **§27.5** (`:1412–1424`), **§27.6** (`:1426–1436`), **§27.7** (`:1438–1450`), **§27.9** (`:1464–1474`); §2.19/§2.16/§3/§3.1/§4/§5.2; §17.1–§17.4; §18; §19 A48–A53/A55 (+ A54/A56/A57/A73 — граница); §20; §22; R17/R18.
- **Задачи:** `tasks.md` T-3859…T-3886 (поставки фичи — T-3861…T-3885). **Приёмки в scope `mca-17a`:** **A48, A49, A50, A51, A52, A53, A55**. **Закреплено за `mca-17c`:** **A54** (`#/oversight`/IA), **A56** (UI диагностических действий), **A57** (виджет самообучения), **A73** (личность/vision/temporal factcheck на реальных запусках) — `mca-17a` поставляет для них backend-предпосылки (реестр/trace/lifecycle/инциденты/control-plane).
- **ADR:** `adr-1027-8-observability-core.md` (D1–D15: D1–D12 — ядро, D13–D15 — carry-over/REUSE/fencing). **Рамка:** `plans/docs/mca-round1027-arch-frames.md` (§1.2.4 — v19, §2, §3, §4). **План:** `plans/docs/mca-round1027-plan.md` §3.8.
- **Статус:** Proposed → Accepted по T-3885 (Merge в `plans/ARCHITECTURE.md` **§100+**, следующий фактически свободный). **Deploy:** `DEFERRED_TO_RELEASE` (§20; пер-фичевых деплоев/тегов/bump нет; агрегатный релиз — `mca-release`).
- **Baseline (Step 0, данность):** Reviewed-Commit `05bc870` (origin/master); `APP_VERSION` 2.58.31; SQLite DDL **v18** (после `mca-07`; цепочка v13…v18); каталог `473/430/448/102/100/21`; канон инструментов 12; pytest `.venv` **9758/0** + JS **47/47**; анкер отката `7165ff7`.
- **Уровень риска:** **R3** (подтверждено, с reassessment по carry-over §94.5) — см. §7.

---

## 1. Область и исключения

### 1.1. Входит

- **Реестр процессов (§27.1)** — технический runtime-каталог из актуального кода: для каждой фактически активной функции `process_id`, `version`, назначение простыми словами, входы/выходы, ожидаемые стадии и ветвления, триггер/расписание, связанные настройки, источник состояния, поддерживаемые операции восстановления, `widget_id`. Mapping фактических стадий на события. Статус `implemented/disabled/not_run/not_instrumented` с причиной. Реестр **сверяется** с фактическими handlers/workers/расписаниями/инструментами/путями отправки. **Новый зарегистрированный процесс без наблюдаемости = незавершённая интеграция.** Регистрация уже закрытых `mca-03`/`mca-02`/`mca-04a`/`mca-07` **без переизобретения** их событий.
- **Сквозной trace/span-контракт (§27.3)** — расширение `mca-13`, не второй store: `pipeline_run_id`, `pipeline_type/version`, `span_id`, `parent_span_id`, `linked_span_ids`, `job_id`, `attempt_id`, `causation_id`, `event_id`, `event_sequence`, `status`, `reason_code`, start/end, `heartbeat_at`, `progress_at`, `deadline_at`, `checkpoint_ref`; correlation в сообщения durable queue и её сохранение при resume; root job + отдельные batch traces (не один бесконечный span); parent-child только для реального вложенного выполнения; singleflight/cache — links; retry — новая попытка; параллельные ветви — отдельные spans; монотонные часы внутри + UTC при отображении; связь по ID/`event_sequence`.
- **Lifecycle/states + честный итог (§27.4)** — 9 состояний стадии (`queued/running/waiting_external/retry_scheduled/succeeded/skipped/failed/cancelled/interrupted`), run дополнительно `partial/degraded`, `stalled` — диагностическое; обязательные/необязательные стадии и ветви по контракту pipeline version; асинхронное продолжение — отдельный linked job с явным pending; информативная ошибка.
- **Heartbeat/lease/progress/deadline + watchdog/recovery (§27.5)** — владелец/lease, heartbeat, progress marker, deadline, ожидаемая внешняя операция, checkpoint, `next_retry_at`; ориентиры 15 s/60 s; progress-stall по типу стадии; lease generation/fencing; детект недоступности вне основного loop; UI `telemetry stale/unknown`; recovery по checkpoint; `delivery_unknown`.
- **Инциденты и доставка (§27.6)** — список активных, группировка по устойчивому признаку, `acknowledged ≠ resolved`, история после исчезновения ошибки, компактный индикатор + прямой переход, доставка в открытый миниапп ≤10 s (incremental polling на существующей инфраструктуре), cursor-сверка при reconnect, **только миниапп**.
- **Хранение/полнота/безопасность телеметрии (§27.7)** — durable, без случайного семплинга, result/checkpoint/outbox в одной локальной tx где возможно, SQLite↔PG подтверждения/сверка и `status pending` без обещания атомарности, bounded очередь batch writes, lock не держится во время сети, spool/structural fallback + счётчики + `telemetry_degraded`, `gaps`, ретенция MCA-13 (14/90), серверная пагинация/индексы, маскировка R17 во все каналы, роли/chat isolation.
- **Ядро диагностических действий (§27.9)** — cancel/resume/retry только для разрешённых jobs, по правам, actor/audit event, идемпотентно; «повторить отображение» — только чтение; повтор внешнего side effect запрещён без безопасной семантики; `delivery_unknown` — сверка вместо слепого retry; нет интерфейса произвольного кода/SQL; fault injection вне production.
- **Закрытие watch-list прошлых волн (обязательный вход)** — carry-over `mca-13` §94.5: (1) UI SC-13 (метрики §17.4 на существующей витрине), (2) UI SC-14 (фильтры trace/chat/component/reason + переход к связанным событиям), (3) живые продюсеры `runtime`-метрик, (4) wiring `flush_events`/`prune_events` (уважая **оба** kill-switch: `MCA_EVENT_CONTRACT_ENABLED` + `MCA_TELEMETRY_STORE_ENABLED`), (5) reassessment триггера «конкуренция записи»; **L-MCA01-5** (`fencing_token` во все терминальные записи, включая cancelled/failed); регистрация стадий/виджет-ID `mca-03`/`mca-02`/`mca-04a`/`mca-07`.
- **Δ DDL v19** через реестр `mca-14`; события MCA-13/стадии MCA-17a; R17-маскирование; kill-switch; тесты/деплой/откат.

### 1.2. Не входит (границы)

- **Полная витрина/матрица «Аналитики»** — представления «Обзор процессов»/«Запуски»/«Инциденты», фильтры по чату/времени/process/статусу/trigger/модели, граф процессов, уровни детализации 1–5, deep links из витрины «Памяти»/«Статуса» — **`mca-17c`** (§27.2/§27.8 UI/§27.10). `mca-17a` доводит **только** carry-over SC-13/SC-14 как **REUSE** существующего viewer/endpoint, без новых панелей/маршрутов. **Уточнение границы (AMEND F5):** read-only **транспорт ядра** (выдача реестра/инцидентов — §4.6/§4.10) входит в `mca-17a`; это **данные-API**, а не панель/маршрут витрины. В `mca-17c` переходит представление/визуализация и действия.
- **UI диагностических действий (A56)** — кнопки cancel/resume/retry/экспорт в миниаппе — **`mca-17c`**; `mca-17a` даёт backend control-plane (ядро) + права/идемпотентность/audit.
- **Виджет самообучения (A57) и опыт/lessons** — `mca-16`/`mca-17c`.
- **SelfModel/TraitObservation/BehaviorRule/BehaviorFrame (`mca-18`), vision/`MediaAsset`/`MediaAnalysis` (`mca-19`), `ClaimEnvelope`/`TemporalVerdict` (`mca-20`)** — их собственные фичи; в реестре `mca-17a` они присутствуют как строки со статусом `not_run`/`not_instrumented` до реализации; их стадии/виджет-ID регистрируются владельцами в том же реестре (инвариант «новый процесс без наблюдаемости = незавершённая интеграция»).
- **`mca-09`/`mca-10a`/`mca-10b`/`mca-11`/`mca-15`** — собственные фичи; их стадии registрируются ими через реестр `mca-17a`.
- **Архивный backfill 3 режима / full rebuild / исправление накопленных данных** — `mca-04b` (mca-17a даёт lifecycle/root-job/batch/checkpoint механику, но перестройку не выполняет); доменные версии `mca-04b` — **v20+** (санкция §5/рамка §1.2.4).
- **Изменение `pg_db.py`** — вне diff (GEN-R4; SQLite и PG сохраняются, PG — no-op).
- **Второй store/вторая аналитика/второй `TaskSupervisor`/второй write-механизм/новый SaaS/Kafka/monitoring cluster** — прямо запрещены (GEN-R19/GEN-R21; §27.3 «новых SaaS, Kafka/отдельного monitoring cluster не требуется»).
- **Рассылки в общий чат/DM/email/сторонние сервисы** — исключены (уведомления только в миниаппе, §27.6).
- **Запуск произвольного кода/SQL из UI; fault injection как production-функция** — исключены (§27.9).

### 1.3. Фактическое состояние baseline (сверено с рабочей веткой; REUSE §3/§3.1)

- **Единый durable-стор событий есть, но span-полей нет.** `services/mca_events.py` (`build_event`/`emit_mca_event`/`flush_events`/`prune_events`/`query_events`/`metrics`), таблица `mca_events` (v15, 20 колонок). Поля `pipeline_run_id`/`span_id`/`parent_span_id`/`linked_span_ids`/`job_id`/`attempt_id`/`causation_id`/`event_sequence`/`heartbeat_at`/`progress_at`/`deadline_at`/`checkpoint_ref` **отсутствуют** как колонки; `status` присутствует в `_CODE_FIELDS`, но **колонки нет** → молча теряется на `flush` (расхождение ТЗ↔код, §9). `reason_code` содержит `deadline_exceeded`/`delivery_unknown`/`worker_lost`/`queue_coalesced`/`queue_full`, но нет кодов lifecycle-стадий/инцидентов/watchdog (расширяется в §4.9).
- **`metrics()` — единый адаптер §17.4, но без потребителя.** `mca_events.metrics(db, runtime=...)` реализован; живой продюсер `runtime`-словаря (`rss_mb`/`cache_entries`/`downloads`/`provenance_coverage`/`histories`/`episodes`) **отсутствует** (вне тестов); endpoint, отдающий адаптер в UI, отсутствует. Группы без продюсера честно `available=False`/`None` (`UNKNOWN ≠ 0`) — механизм готов, обвязки нет.
- **`flush_events`/`prune_events` не подключены.** Вызовы есть только в тестах `tests/test_mca13_event_contract_round1027.py`; в worker-loop/периодическом job/shutdown вызовов **нет** → durable-персистенция не работает в проде (carry-over §94.5 п.4). Буфер `_pending` — `deque(maxlen=256)` + счётчик `_dropped_total` (bounded, A53-совместимо), дискового spool нет.
- **`TaskSupervisor` и durable `task_jobs` есть, но не подключены в проде.** `TaskJobStore`/`get_task_supervisor` используются только в тестах; `task_jobs` (v14) не имеет колонок `pipeline_run_id`/`span_id`/`parent_span_id`/`causation_id`/`attempt_id`/`progress_at`/`next_retry_at`/`checkpoint_ref` (есть `heartbeat_at`/`fencing_token`/`generation`/`attempt`/`max_attempts`/`deadline_at`/`coalesce_key`/`payload`/`result_ref`). `recover_stale()` (takeover+fencing) реализован, но **не вызывается** ни одним watchdog-циклом. Watchdog/heartbeat-цикла нет.
- **L-MCA01-5 подтверждён кодом.** `TaskSupervisor.run()` (`services/task_supervisor.py`): success-путь (`:286–289`) передаёт `fencing_token=fence`; `cancelled` (`:299–301`) и `failed` (`:310–312`) вызывают `_safe_finish(...)` **без токена**. После takeover «медленный» владелец может перезаписать статус/reason уже терминальной `interrupted`-строки нового владельца.
- **Инцидентов/run-таблиц нет.** Таблиц `mca_pipeline_runs`/`mca_incidents` нет; группировка повторов существует только как `mca_event_aggregates` (fingerprint = `event_name:component:reason_code:error_type`) — это агрегат события, **не** инцидент с acknowledge/resolve/history.
- **Доставка — только polling, SSE/WebSocket нет.** В `web/app.js` `EventSource`/`text/event-stream` не используются; периодический polling применяется (`#/oversight` — 60 s, досье-лента — ~2 s, cognition — 15 s). Значит §27.6 ≤10 s реализуется **инкрементальным polling** (без новых протоколов).
- **Существующий viewer/log-инфраструктура на месте (REUSE):** `web/api/routes.py::GET /api/status/logs` (ring-buffer, `level`/`limit`), `web/api/oversight.py::GET /api/oversight/summary` (`#/oversight`), `web/api/analytics.py` (`/analytics/usage/latest|summary`, `/analytics/execution/latest`), `web/app.js` (Vue, `#/oversight`, `#/status`, log viewer), `services/log_ring.py::sanitize`.
- **Процессы для реестра (фактические workers/schedulers/handlers):** `SchedulerService` (реакции), `SummarySchedulerService`, `GoodmorningSchedulerService`, `MemoryBackupService`, `MemoryMaintenanceService`, `disk_retention`, `LoreWorker`, `DreamWorker` (сон/убеждения + глубокий сон/парадигмы), `NostalgiaWorker`, `AntiClicheWorker`, `UptimeHeartbeatService`, `lore_notify`; handlers `summary`/`direct_chat`/`chat_lifecycle`/`factcheck`/`web`/`video_download`/`youtube`/`voice_transcription`; `tools/history_import/*`; `services/{provenance,message_identity,safe_fetch,mca_retrieval_context,dossier_rebuild_jobs,user_relations,search_aggregator,summary_memory,image_generation,telegram_send}`. Полный список — §4.2 (Builder сверяет построчно).
- **Расхождения ТЗ↔код — в §9.** Ключевые: `status` без колонки; отсутствие wiring `flush`/`prune`/`recover_stale`; отсутствие runtime-продюсера метрик; watchdog-цикла нет; `mca_process_registry` — решение: **code-declared** (см. D1/D2 §4.1/H-примечание).

---

## 2. Трассируемость REQ → SC

| REQ | §ТЗ | SC | Задачи |
|---|---|---|---|
| REQ-MCA17A-01 — реестр процессов из кода (process_id/version/назначение/IO/стадии/триггер/настройки/state_source/recovery/widget_id; mapping стадий на события; статус с причиной; сверка с code) | §27.1 `:1335–1337` | SC-01, SC-02, SC-21 | T-3864, T-3865 |
| REQ-MCA17A-02 — сквозной trace/span (все поля §27.3; correlation в durable queue/resume; root job + batch traces; parent-child vs links; retry=новая попытка; монотонные часы/UTC/sequence) | §27.3 `:1390–1396` | SC-03…SC-06 | T-3867…T-3870 |
| REQ-MCA17A-03 — lifecycle/states + честный итог (9 состояний, run partial/degraded, stalled диагностическое; обязательные/необязательные по pipeline version; linked job; информативная ошибка) | §27.4 `:1404–1410` | SC-07…SC-10 | T-3871…T-3873 |
| REQ-MCA17A-04 — heartbeat/watchdog/recovery (15 s/60 s; progress-stall по типу; lease/fencing; детект вне loop; recovery по checkpoint; delivery_unknown) | §27.5 `:1416–1424` | SC-11…SC-14 | T-3875…T-3877 |
| REQ-MCA17A-05 — инциденты + доставка (активные; группировка; acknowledged≠resolved; история; ≤10 s polling; cursor; только миниапп) | §27.6 `:1430–1436` | SC-15, SC-16 | T-3878, T-3879 |
| REQ-MCA17A-06 — хранение/полнота/безопасность телеметрии (durable; без семплинга; tx/подтверждения/`status pending`; bounded batch; spool/degraded/gaps; ретенция/пагинация/индексы; маскировка) | §27.7 `:1442–1450` | SC-17, SC-16 | T-3879, T-3880 |
| REQ-MCA17A-07 — ядро диагностических действий (cancel/resume/retry по правам/audit/идемпотентно; read-only refresh; без слепого повтора side effect; fault injection вне prod) | §27.9 `:1468–1470` | SC-18, SC-19 | T-3874, T-3877, T-3883 |
| REQ-MCA17A-08 — виджет/детализация/журнал стадий + REUSE ExecutionGraph/`mca_events` (второй контур запрещён; UI не ходит в БД) | GEN-R17/R19/R21; §2.19/§3/§3.1/§4 | SC-01…SC-04, SC-20 | T-3865, T-3866, T-3867, T-3880, T-3881 |
| REQ-MCA17A-09 — REUSE контрактов MCA-13/MCA-14/MCA-01 (событие `start`+`outcome`; `reason_code`; аддитивная идемпотентная Δ DDL через реестр; nullable=честный unknown) | MCA13-R1/R2; MCA14-R1/R2; §17/§18 | SC-03, SC-07, SC-15, SC-21 | T-3867, T-3871, T-3878, T-3864 |
| REQ-MCA17A-10 — R17-маскировка до записи во все каналы (включая error cause и экспорт; SourceRef вместо сырого) | GEN-R14; §2.16/§17.3 | SC-16, SC-17 | T-3879, T-3880, T-3883 |
| REQ-MCA17A-11 — **L-MCA01-5**: `fencing_token` во **все** терминальные записи (cancelled/failed), до прод-подключения | MCA01-R2 (carry); §95.5 | SC-14 | T-3882 |
| REQ-MCA17A-12 — **carry-over MCA-13 §94.5**: UI SC-13/SC-14, живые продюсеры метрик, wiring `flush`/`prune` (оба kill-switch), reassessment R2→R3 | MCA13-R4 (carry); §17.4/§94.5 | SC-13, SC-22 | T-3881 |
| REQ-MCA17A-13 — REUSE/kill-switch/rollback (env-only default ON; OFF = паритет baseline; deploy `DEFERRED_TO_RELEASE`) | MCA14-R4/R5; §18/§20 | SC-21 | T-3862, T-3884 |
| REQ-MCA17A-14 — тесты/прогон/фикстуры без платных операций (максимальное покрытие) | FIN-R1 `:1865` | SC-01…SC-22 | T-3883 |

**Орфан-REQ нет;** T-3859/3860/3862/3863/3884/3885/3886 — процессные (baseline/декомпозиция/санкции/сверка/deploy-подготовка/merge/архив). Каждый `REQ-MCA17A-01…14` покрыт ≥1 задачей; каждая задача — REQ/SC либо процессная.

---

## 3. Наблюдаемое поведение и отказы

### 3.1. Реестр процессов (§27.1 / A48)
- «Аналитика» показывает все фактически работающие процессы; для каждого — понятное назначение, enabled/effective state, «сейчас», последний успех, последняя ошибка, pending/active, свежесть телеметрии. Отсутствие данных по старому механизму **не** выдаётся за нормальную работу: статусы `disabled` (намеренно выключено), `not_run` (ни разу не запускалось), `not_instrumented` (нет событий/инструментирования) видны явно, с причиной.
- Число карточек само по себе покрытие не доказывает: для процесса обязателен mapping его **фактических** стадий на события. Новый процесс без наблюдаемости — незавершённая интеграция (release-отчёт: матрица покрытия каждого фактического процесса).

### 3.2. Сквозной trace (§27.3 / A49)
- По одному ответу бота можно пройти назад к решению, контексту, найденным сообщениям, инструментам и использованным урокам; по фоновой истории — вперёд от источников к эпизоду и убеждению. Цепочка не рвётся на границе durable queue и переживает рестарт (correlation сохраняется).
- Длительный archive job виден как **root job + отдельные batch traces** (диапазон/счётчики + ссылки на проблемные записи), а не как один бесконечный span; failures не скрываются за «обработано 500». Общий singleflight/кеш-результат обслуживает несколько запросов через `linked_span_ids`, без одного ложного владельца. Retry — новая попытка (`attempt_id`) в рамках того же логического этапа; предыдущая ошибка не затирается.

### 3.3. Честный итог (§27.4 / A50)
- Зелёный статус означает завершение **необходимых** этапов. Невыполненная обязательная стадия → `failed`/`interrupted`; сбой необязательной с работающим fallback → `degraded`/`partial` с описанием; run **не** success, пока не зафиксирована необходимая запись или остаётся обязательная дочерняя задача. Асинхронное продолжение — отдельный linked job с явным pending, а не скрытый успех. `stalled` — диагностическое, outcome не заменяет.
- Ошибка несёт очищенный traceback/cause chain, failed stage, последние успешные stages, попытку, elapsed/deadline, dependency, влияние, fallback, checkpoint, действие восстановления; «предполагаемая причина» — отдельно от подтверждённой. Нулевой результат/валидное молчание ≠ падение; ошибка SQL/парсинга ≠ «нет воспоминаний»; ошибка одной ветви не стирает успех другой. После SIGKILL/потери машины — честный `interrupted`.

### 3.4. Долгие процессы (§27.5 / A51, A52)
- Живой worker без прогресса ≠ здоровый процесс: heartbeat и progress показываются раздельно; порог progress-stall — по типу стадии (LLM/видео/архив), законная длительная транскрибация не объявляется упавшей через минуту. Время в очереди и у внешнего провайдера — отдельно от времени исполнения.
- Watchdog проверяет durable state периодически и на старте; при stale lease — подозрение → проверка владельца/состояния → `interrupted`/retry по безопасной политике. Fencing/generation не даёт старому worker записать результат после takeover — **во всех** терминальных записях, включая `cancelled`/`failed`. Heartbeat не продлевает абсолютный deadline без объяснимой смены этапа.
- Recovery читает checkpoint, определяет подтверждённые записи/side effects и возобновляет только безопасные этапы; бесконечных retries нет. Неопределённая доставка/платная операция — `delivery_unknown` до сверки по operation ID; рестарт не даёт права повторить вслепую. Опасное задание без обязательного durable checkpoint завершается/приостанавливается явно.

### 3.5. Инциденты (§27.6 / A55)
- Владелец видит один связный инцидент вместо сотен одинаковых ошибок: стадия, серьёзность, первое/последнее обнаружение, число повторов, затронутые jobs/chats, влияние, последнее восстановление, ссылка на trace. Повторы группируются по устойчивому признаку (process/stage/reason/error_type/dependency), отдельные trace и счётчик сохраняются; новые симптомы **не** объединяются по одному слову «timeout». Успешный fallback снижает влияние, но не скрывает сбой основного пути. `acknowledged ≠ resolved`; recovered/resolved — только после реальной проверки; история сохраняется после исчезновения ошибки.
- Ошибки/stale-переходы доходят до **открытого** миниаппа ближайшим обновлением (цель ≤10 s; polling на существующей инфраструктуре). При reconnect — пропущенные события по cursor + сверка состояния. Уведомления только в миниаппе; бот не публикует внутренние stack traces.

### 3.6. Телеметрия (§27.7 / A53)
- Компактное начало и итог для каждого run, обязательные переходы, все ошибки/retries/fallbacks и связи; без случайного семплинга; debug-payloads агрегируются с явным счётчиком. Durable state не зависит только от fire-and-forget. При недоступном хранилище — ограниченный дисковый spool или структурный fallback + счётчик недоставленных/потерянных + явный `telemetry_degraded`; при исчерпании spool — не бесконечный RAM-буфер; фактическая потеря — `gaps`; нельзя показывать полный trace при отсутствующей части. После истечения подробной ретенции — «детали удалены по сроку хранения», не «этап не выполнялся».

### 3.7. FAILURE-семантика (сводно)
- `MCA_OBSERVABILITY_ENABLED=OFF` → точный паритет baseline (без реестра/span-расширения/lifecycle/watchdog/инцидентов; `emit_mca_event`/ExecutionGraph как есть). Под-гейты OFF дают паритет по своей оси (§4.8). Ошибка БД при durable-write не рвёт hot-path (события остаются в буфере/spool; счётчик/`degraded` видны). Watchdog при отсутствии внешнего наблюдателя честно отражает ограничение и обнаруживает сбой после восстановления. Creator fail-open: `emit_mca_event` и все адаптеры/эндпоинты не бросают наружу.

---

## 4. Интерфейсы и контракты

### 4.1. Реестр процессов (§27.1; D1/D2)
- **Носитель реестра — code-declared (решение).** Единственный источник правды — модуль `services/mca_process_registry.py`: упорядоченный реестр записей `ProcessDefinition` (+ декларации pipeline-version со стадиями, см. §4.4). Реестр **не** дублируется доменной таблицей: §27.1 требует сверки с фактическим кодом, а вторая копия в БД неизбежно дрейфует и нарушает REUSE (прецеденты code-declared каталогов — `services/mca_gates.py::KILL_SWITCHES`, `services/param_catalog.py`). Viewer получает реестр из code-контракта через read-only API (не из БД).
- **Поля записи:** `process_id` (стабильный opaque), `version`, `purpose` (простые слова), `inputs`, `outputs`, `stages` (ожидаемые + ветвления), `trigger_kind` (`per_message`/`schedule`/`on_write`/`per_request`/`manual`/`background`) + `schedule` (человекочитаемо/ код), `settings_ref` (имена env/настройки; значения не раскрываются), `state_source` (где durable-состояние: `task_jobs`/`mca_events`/`mca_pipeline_runs`/in-memory/…), `recovery_ops` (список операций), `widget_id` (REUSE `widget-map`/`_TAB_BY_GROUP`; для не-UI — явный маркер), `stages_to_events` (mapping фактических стадий на имена событий), `instrumentation` (какие стадии инструментированы), `owner_feature`.
- **Runtime-статус вычисляется при чтении:** `enabled` → резолв kill-switch(ей) процесса per-call; `implemented`/`disabled`/`not_run`/`not_instrumented` → из декларации + наличия событий/стадий (отсутствие событий + декларированная инструментация → `not_instrumented`; декларация без инструментации → `not_instrumented`; есть инструментация, нет событий → `not_run`; выключен гейтом → `disabled`). Реестр **сверяется** с фактическими handlers/workers/расписаниями/инструментами/путями отправки; расхождение фиксируется как незавершённая интеграция.
- **Обязательный минимум строк реестра** (§4.2); процессы будущих фич (`mca-09`/`10a`/`10b`/`11`/`15`/`16`/`18`/`19`/`20`) присутствуют как `not_run`/`not_instrumented` до реализации.
- Регистрация закрытых фич (`mca-03`/`mca-02`/`mca-04a`/`mca-07`) — ссылками на их уже существующие события/стадии (без переизобретения).

### 4.2. Обязательный минимум реестра (фактические процессы; Builder сверяет построчно)

| process_id (предложение) | Фактический носитель | trigger | state_source | widget_id |
|---|---|---|---|---|
| `ingestion.live` | `handlers/summary.py::summary_observer` | per_message | `smart_messages`/`message_source_records` (`mca-03`) | Приём/импорт/редакции |
| `ingestion.import` | `tools/history_import/{parser,loader,llm_worker}.py` | manual/background | `message_source_records`/`task_jobs` | Приём/импорт/редакции |
| `identity.resolve` | `services/message_identity.py` (`mca-03`) | on_write | `smart_messages`/`message_revisions` | Идентичность и адресаты |
| `summary.window` | `services/summary_scheduler.py` + `summary_memory.py` (`get_window_messages`/`_build_running_summary`) | schedule/pressure | `chat_running_summary` | Окно/summary |
| `summary.hybrid` | `services/summary_filter.py`/`summary_l1_clusterizer.py`/`summary_l2_writer.py` | schedule/pressure | `chat_summary_levels` | Summary Hybrid |
| `facts.extract` | `tools/history_import/llm_worker.py` + `database.graph_facts` | queue | `graph_facts` | Факты/граф |
| `dossier.rebuild` | `services/dossier_rebuild_jobs.py` + `services/lore_worker.py` | manual/schedule | `task_jobs`/`DossierRebuildJobStore` | Досье/архив |
| `provenance.record` | `services/provenance.py` (`mca-04a`) | on_write/backfill | `mca_source_refs`/`mca_evidence_links` | Provenance |
| `embeddings.index` | `services/summary_memory.py` (embed/vec) + `mca_retrieval_context.py` (`mca-07`) | on_write/backfill | `embedding_cache`/vec + `mca_embedding_index_generations` | Embeddings/индексы |
| `retrieval.query` | `services/mca_retrieval_context.py` + `search_service.py`/`search_aggregator.py` | per_request | in-memory bundle + `mca_source_refs` | Retrieval/RAG |
| `nostalgia.run` | `services/nostalgia_worker.py` | schedule | `task_jobs`/`graph_facts` | Ностальгия |
| `lore.compile` | `services/lore_compiler_service.py` + `services/lore_worker.py` | schedule/pressure | `lore_stories` | Эпизоды/lore |
| `sleep.dream` | `services/dream_worker.py` (beliefs) | schedule/manual | `task_jobs` | Сон/убеждения |
| `sleep.deep` | `services/dream_worker.py` (парадигмы) | schedule | `task_jobs` | Глубокий сон/парадигмы |
| `persona.traits` | `services/bot_persona.py` | on_demand | `persona_*` | Личность/интересы |
| `anticliche.run` | `services/anticliche_worker.py` | schedule | `anticliche_cache` | Анти-клише |
| `goodmorning.run` | `services/goodmorning_scheduler.py` | schedule/cron | `task_jobs` | Планировщики |
| `scheduler.reactions` | `services/scheduler.py` | schedule | `task_jobs` | Планировщики |
| `direct.reply` | `handlers/direct_chat.py` + `services/direct_chat_service.py` | per_message | `task_jobs`/`mca_events` | Ответы (decision/System2) |
| `tools.chain` | `services/tool_router.py`/`tool_loop.py` | per_request | `mca_events`/`task_jobs` | Tool chain |
| `web.fetch` | `services/safe_fetch.py`/`web_content_extractor.py` (`mca-02`) | per_request | `mca_events` | Web/видео/медиа |
| `media.download` | `tools/video_downloader.py`/`youtube_transcript_engine.py` | per_request | `task_jobs`/ФС | Web/видео/медиа |
| `image.generate` | `services/image_generation.py` | per_request | `mca_events`/PG reservation | Tool chain |
| `summary.publish` | `services/summary_generator.py` (rich/plain) | after summary | `mca_events` | Публикация |
| `factcheck.run` | `handlers/factcheck.py` + `services/factcheck_service.py` | per_request | in-memory/`mca_events` | Фактчек |
| `chat.lifecycle` | `handlers/chat_lifecycle.py` (`mca-03` mapping) | event | `smart_messages`/`chat_id_migrations` | Приём/импорт |
| `maintenance.retention` | `services/memory_maintenance.py`/`disk_retention.py` | schedule | `task_jobs` | Сохранение/ресурсы |
| `backup.memory` | `services/memory_backup.py` | schedule | ФС/`task_jobs` | Сохранение/ресурсы |
| `uptime.heartbeat` | `services/uptime_heartbeat.py` | schedule | ФС/`task_jobs` | Сохранение/ресурсы |
| `telemetry.events` | `services/mca_events.py` (`flush_events`/`prune_events`) | background | `mca_events`/spool | Сохранение/ресурсы |
| `watchdog.jobs` | `services/mca_watchdog.py` | background/startup | `task_jobs`/`mca_pipeline_runs` | Сохранение/ресурсы |
| `incidents.delivery` | `services/mca_incidents.py` | background/poll | `mca_incidents` | Инциденты |
| `identity.future` … `temporal.factcheck` (mca-18/19/20/16/09/10a/15) | — | — | — | `not_run`/`not_instrumented` |

### 4.3. Trace/span-контракт (§27.3; D3/D4)
- **Расширение, не второй store.** Новые поля принимаются `mca_events.build_event` и сохраняются в `mca_events` (v19-колонки). Второй канал/стор запрещён.
- **Логическая модель:** `pipeline_run_id` — корень логического прогона (`mca_pipeline_runs`, §4.4); `span_id` — стадия; `parent_span_id` — реальное вложенное выполнение (иначе NULL); `linked_span_ids` — связи без владения (singleflight/кеш/async continuation); `job_id` — durable-задача (`task_jobs`); `attempt_id` — попытка (retry = новый `attempt_id`, старый не затирается); `causation_id` — причина (кто породил); `event_id` — стабильный ID события (= `mca_events.id`); `event_sequence` — монотонный счётчик в рамках run; `status` — состояние стадии (§4.5); `reason_code` — словарь MCA-13 (расширяется, §4.9); `start` — событие старта span/run; `end` — терминальное событие span/run (по `ts`); `heartbeat_at`/`progress_at`/`deadline_at`/`checkpoint_ref` — durable-маркеры.
- **Correlation в очереди и resume:** `TaskSupervisor.run()`/`TaskJobStore` принимают/хранят `pipeline_run_id`/`span_id`/`parent_span_id`/`causation_id`/`attempt_id`/`progress_at`/`next_retry_at`/`checkpoint_ref` (v19-колонки `task_jobs`); при resume из `task_jobs` correlation восстанавливается и событие продолжения наследует `pipeline_run_id`/`span_id`.
- **Root job + batch:** для длительного archive job — один root span + batch spans; `linked_span_ids` batch→root; внутри batch — диапазон/счётчики + ссылки на проблемные записи; усреднение не скрывает failures.
- **Связь по ID/sequence, не по timestamp:** порядок восстанавливается по `event_sequence`/`event_id`; timestamp — только атрибут.
- **Время:** длительности внутри процесса — `time.monotonic()` (не wall-clock); для отображения — UTC.
- **Стадийные события вокруг реальных операций:** `scheduled/queued → started → ожидаемое действие и объём → завершение внешнего запроса → валидация → фиксация → передача дальше → terminal outcome`; никакой реконструкции этапов задним числом по общему success. Не логировать каждый токен/байт/внутренний SQL как отдельный UI-узел.

### 4.4. Lifecycle/states + honest outcome (§27.4; D5)
- **Состояния стадии (`status`):** `queued`, `running`, `waiting_external`, `retry_scheduled`, `succeeded`, `skipped`, `failed`, `cancelled`, `interrupted`. **Run (`mca_pipeline_runs.status`):** `running`, `succeeded`, `partial`, `degraded`, `failed`, `cancelled`, `interrupted`; дополнительно **диагностическое** `stalled` — вычисляется на чтении (`progress_at`/`heartbeat_at` vs пороги), **не** персистится как outcome и outcome не заменяет. У каждого `skip` — причина (`reason_code`) и влияние.
- **Контракт pipeline version:** для каждого `pipeline_type` декларируется версия со списком стадий и признаком `required`/`optional` и условиями ветвей (`services/mca_process_registry.py`). Итог run: все обязательные `succeeded` → `succeeded`; `optional` с рабочим fallback → `partial`/`degraded` + описание; обязательная невыполнена → `failed`/`interrupted`. Run **не** `succeeded`, пока не зафиксирована необходимая запись или остаётся обязательная незавершённая дочерняя задача; асинхронное продолжение — отдельный linked job со статусом pending.
- **Ошибка:** расширение `build_error_metadata`/`error_json` полями `failed_stage`, `last_successful_stages[]`, `attempt`/`attempt_id`, `elapsed_ms`/`deadline_at`, `dependency`, `impact`, `fallback`, `checkpoint_ref`, `recovery_action`; «предполагаемая причина» (`suspected_cause`) — отдельно от подтверждённой. Нулевой результат/silent ≠ failed; `sql_error`/`parse_error` ≠ `no_relevant_memory`; ошибка одной ветви не стирает успех другой. После SIGKILL/потери машины — `interrupted` с честным «причина неизвестна до данных менеджера процессов».

### 4.5. Heartbeat/lease/watchdog/recovery (§27.5; D7/D8)
- **Поля долгого job:** владелец/lease (`task_jobs.owner`+`fencing_token`+`generation`), `heartbeat_at`, `progress_at` (фактический маркер), `deadline_at`, ожидаемая внешняя операция (в `error_json`/событии стадии), `checkpoint_ref`/`task_jobs.payload`, `next_retry_at`.
- **Пороги (env-only, default):** `MCA_JOB_HEARTBEAT_SECONDS=15`, `MCA_JOB_STALE_SECONDS=60`; progress-stall — `MCA_PROGRESS_STALL_<TYPE>_SECONDS` по типу стадии (LLM/видео/архив) относительно ожидаемой длительности/deadline. Конфигурируемы; законная длительная транскрибация не объявляется упавшей по общему таймеру. Очередь/внешнее ожидание — отдельно от исполнения.
- **Heartbeat ≠ progress.** Heartbeat не продлевает абсолютный deadline без объяснимой смены этапа.
- **Watchdog:** периодически (background asyncio-задача, стартует при инициализации) и **на старте** проверяет durable state; при stale lease — подозрение → проверка владельца/состояния → `interrupted`/retry по безопасной политике через `TaskJobStore.recover_stale()` (fencing/generation бампаются). **Детект недоступности процесса — вне основного event loop** (REUSE `services/uptime_heartbeat.py` + внешний менеджер процессов/systemd); при отсутствии внешнего наблюдателя ограничение отражается явно, сбой обнаруживается после восстановления. UI при потере backend → `telemetry stale/unknown` (старый «зелёный» не сохраняется).
- **Recovery:** прочитать checkpoint (`get_checkpoint`), определить подтверждённые записи/side effects, возобновить только безопасные этапы; бесконечных retries нет. `delivery_unknown` — до сверки по доступному operation ID; повтор внешнего side effect/платной операции запрещён без безопасной семантики. Опасное задание без обязательного durable checkpoint завершается/приостанавливается явно.
- **L-MCA01-5 (обязательно до прод-подключения):** `TaskSupervisor.run()` передаёт `fencing_token=fence` и в `cancelled`, и в `failed` терминальные пути (сейчас — нет); threat H17a выравнивается на «во **все** терминальные записи»; тест на no-op устаревшего владельца.

### 4.6. Инциденты (§27.6; D9/D10)
- **Durable:** `mca_incidents` (v19): `incident_id`, `fingerprint`, `process_id`, `pipeline_type`, `stage`, `severity`, `title`, `first_ts`/`last_ts`, `repeat_count`, `jobs_json`/`chats_json` (bounded), `impact`, `fallback_used`, `first_trace_id`/`last_trace_id`, `acknowledged_at`/`acknowledged_by`, `resolved_at`, `resolution_evidence`, timestamps.
- **Fingerprint (устойчивый признак):** `process_id`+`pipeline_type`+`stage`+`reason_code`+`error_type`+`dependency` (без свободного текста и без одного слова «timeout»); разные симптомы получают разные инциденты. Отдельные trace и счётчик сохраняются (`first_trace_id`/`last_trace_id` + `mca_event_aggregates` как дополнительный агрегат событий).
- **Семантика:** `acknowledged ≠ resolved`; `resolved`/recovered — только после реальной проверки здоровья/завершения восстановления (`resolution_evidence`); история сохраняется (строка не удаляется при исчезновении ошибки — только `resolved_at`). Успешный fallback (`fallback_used=1`) понижает `severity`/`impact`, но инцидент основного пути остаётся видимым.
- **Доставка:** существующий incremental polling (SSE/WS отсутствуют — §1.3); целевой интервал ≤10 s (`MCA_INCIDENT_PUSH_INTERVAL_SECONDS`, ориентир ≤10). Пропущенные при reconnect события — по cursor (`incident_id`/`last_ts` + сверка состояния). **Только миниапп** (без чата/DM/email/сторонних); stack traces пользователям не публикуются; R17-маскировка. **Транспорт (в scope `mca-17a`, AMEND F5/D16):** read-only endpoint на **существующем** роутере `oversight` (`web/api/oversight.py`) отдаёт `active_incidents()` и `incident_changes(since_ts→cursor)`; RBAC global-admin (как `/summary`), fail-open shape-compatible, R17-safe; гейты `MCA_INCIDENTS_ENABLED`+`MCA_INCIDENT_PUSH_ENABLED` (OFF = паритет: нет endpoint-обновления). Потребитель — существующий компактный индикатор на витрине: refresh ≤ `MCA_INCIDENT_PUSH_INTERVAL_SECONDS` на существующей polling-инфраструктуре, **без** новой панели/UI-маршрута.
- **Compact indicator + direct link** — на существующем viewer (REUSE); полный список/представление «Инциденты» — `mca-17c`.

### 4.7. Хранение/полнота/безопасность телеметрии (§27.7; D11)
- **Durable, без случайного семплинга.** Терминальные события и run-итоги — durable (`mca_events`/`mca_pipeline_runs`); debug-payloads агрегируются/сокращаются с явным счётчиком (`truncated`/`count`); критическая ошибка не исчезает.
- **Транзакции:** где возможно — result/checkpoint/outbox в одной локальной tx через `DatabaseService.write_transaction` (mca-01); между SQLite и PG — подтверждения/сверка и `status pending`, **без обещания общей атомарности**; сеть/LLM — вне транзакции (writer lock не держится во время сетевого вызова).
- **Ограниченная очередь batch writes:** существующий bounded буфер `_pending` (`deque(maxlen=256)`)+`_dropped_total`; `flush_events` — батч одной короткой tx. При недоступном хранилище — ограниченный **дисковый spool** (JSONL, `MCA_TELEMETRY_SPOOL_MAX_EVENTS`) либо структурный fallback log, + счётчик недоставленных/потерянных + явный `telemetry_degraded`; при исчерпании spool — **не** бесконечный RAM-буфер; фактическая потеря — `gaps`; при отсутствующей части полный trace не показывается.
- **Ретенция/пагинация/индексы:** REUSE `MCA_DETAILED_LOG_RETENTION_DAYS` (14)/`MCA_TERMINAL_EVENT_RETENTION_DAYS` (90); ручные/происхождение вне ротации; серверная пагинация (`query_events` bounded LIMIT) + индексы v19; после истечения подробной ретенции — «детали удалены по сроку хранения».
- **Кардинальность:** trace/user/message ID — не высококардинальные labels агрегированного metric; хранятся в событиях/индексируемых ссылках.
- **R17:** `sanitize()` применяется до записи во **все** каналы, включая `error_json`/cause и экспорт; ключи/cookies/initData/credentials редактируются; полный промпт/архив не дублируется (SourceRef + ограниченный снимок); доступ к подробному содержимому — по текущим ролям и chat isolation; скрытые рассуждения модели не запрашиваются.

### 4.8. Ядро диагностических действий (§27.9; D6/D12)
- **Backend control-plane:** cancel/resume/retry **только для разрешённых** job-типов; действия — по правам (existing RBAC/`requires_*`), с actor + audit event, идемпотентны (повтор → no-op/тот же результат). «Повторить отображение» — только чтение. Повтор внешнего side effect запрещён без безопасной семантики; у `delivery_unknown` — доступная сверка по operation ID вместо слепого retry. Интерфейса запуска произвольного кода/SQL нет. UI-кнопки — `mca-17c` (A56); `mca-17a` даёт ядро.
- **Fault injection:** `MCA_FAULT_INJECTION_ENABLED` — default **OFF**, dev/test-only, **не** production-постоянно и **не** product-функция (см. §5.4). Демо-данные — с явной меткой, отдельно от production metrics.
- **Управление kill-switch-состоянием:** env-only `ClassVar`, резолв per-call (§4.8.1) — не UI-настройки.

#### 4.8.1. Kill-switch-политика (утверждено; D12)
- env-only `ClassVar[bool] = _env_bool("NAME", True)`, default **ON**, резолв per-call, никогда не бросает, OFF = **точный паритет baseline**. Релиз — со всеми ON, кроме намеренно неактивного stub §14.12 (`mca-10c`) и dev/test-only fault-injection.
- Родитель `MCA_OBSERVABILITY_ENABLED` (master): OFF → паритет baseline целиком. Под-гейты инертны при master OFF там, где это имеет смысл.

### 4.9. Расширение словаря `reason_code` (REUSE MCA-13)
Добавляются коды: `stage_queued`, `stage_waiting_external`, `stage_retry_scheduled`, `stage_skipped`, `run_partial`, `run_degraded`, `run_stalled`, `heartbeat_stale`, `progress_stall`, `takeover_recovered`, `recovery_from_checkpoint`, `checkpoint_missing`, `telemetry_degraded`, `telemetry_gap`, `spool_exhausted`, `incident_opened`, `incident_acknowledged`, `incident_resolved`, `incident_reopened`, `fallback_engaged`, `job_not_allowed`, `action_idempotent_replay`. Словарь остаётся расширяемым (§17.2); второй словарь не создаётся.

### 4.10. Read-only API ядра (REUSE существующих поверхностей; D13)
- **Реестр процессов:** read-only endpoint на **существующем** роутере `oversight` (`web/api/oversight.py`) выдаёт `registry_snapshot()` (code-declared реестр + вычисленный runtime-статус) — **данные** для витрины/`mca-17c`. Гейт `MCA_PROCESS_REGISTRY_ENABLED`; RBAC global-admin; fail-open shape-compatible; R17-safe (значения настроек не раскрываются — только имена). Без нового store; визуализация реестра (карточки/представление «Обзор процессов») — `mca-17c`.
- **Carry-over SC-13 (метрики §17.4 на существующей витрине):** аддитивный блок `mca_metrics` (`mca_events.metrics()`) в существующем `GET /api/oversight/summary`; **новых панелей/endpoint нет**. Поле без продюсера → `available=false`/`null` (`UNKNOWN ≠ 0`).
- **Carry-over SC-14 (фильтры trace/chat/component/reason + переход к связанным событиям):** аддитивные параметры существующего `GET /api/status/logs` (`trace_id`/`chat_id`/`component`/`reason_code`), отдающие связанные `mca_events` через `query_events` (bounded), поверх существующего log viewer; переход из карточки — deep link на trace (не на «начало страницы»).
- **Транспорт инцидентов (§4.6/SC-16):** read-only endpoint `active_incidents()`/`incident_changes()` (cursor ≤10 s) — в scope `mca-17a`; полное представление «Инциденты» — `mca-17c`.
- **Граница с D13:** запрет D13 «без новых панелей/маршрутов/endpoint» относится к carry-over UI (SC-13/SC-14) и витрине `mca-17c`; настоящий §4.10 — read-only **данные-API ядра** (реестр/инциденты), санкционированный §4.6/§4.10 (ADR D16), второй store/аналитику не создаёт.
- Все эндпоинты read-only, RBAC (global admin для аналитики), fail-open shape-compatible, R17-safe.

### 4.11. Модули/файлы (границы diff)
- **Новые:** `services/mca_process_registry.py` (реестр + pipeline-version контракты), `services/mca_trace.py` (run/span lifecycle, состояния стадий, honest-outcome, монотонные таймеры, control-plane ядро), `services/mca_incidents.py` (инциденты/группировка/ack/resolve), `services/mca_watchdog.py` (heartbeat-watchdog/takeover/spool-дренаж).
- **AMEND:** `services/mca_events.py` (span-поля, `status`-колонка, spool/`degraded`/`gaps`, runtime-продюсер, пагинация), `services/task_supervisor.py` (correlation-колонки, `progress_at`/`next_retry_at`/`checkpoint_ref`, fencing во всех терминальных путях — L-MCA01-5), `services/database.py` (v19), `services/mca_gates.py` (имена гейтов), `config/settings.py` (env-only `ClassVar`), `web/api/oversight.py` (аддитивный `mca_metrics`), `web/api/routes.py` (аддитивные фильтры `/status/logs`), `web/api/analytics.py` (аддитивно, при необходимости), `web/app.js`/`web/index.html` (REUSE log viewer — отображение фильтров/ссылки; без новых панелей).
- **Вне diff:** `services/pg_db.py`, `param_catalog.py`, второй store/аналитика/супервизор.

---

## 5. Δ DDL (санкция), бронь версий, Δ каталога

### 5.1. Δ DDL = **v19** (санкция T-3862)
Через механизм `mca-14` (`MigrationStep` + `schema_migrations`, §93): аддитивно/идемпотентно, `user_version` +1, guard по `sqlite_master`/`PRAGMA table_info`, повторный прогон — no-op, PG — **no-op** (GEN-R4), старые таблицы/ID/vec-данные не переименовываются/не удаляются, `nullable` = честный unknown.

```sql
-- 5.1.1. mca_pipeline_runs — durable run/root-job state
CREATE TABLE IF NOT EXISTS mca_pipeline_runs (
    pipeline_run_id   TEXT PRIMARY KEY,
    pipeline_type     TEXT NOT NULL,
    pipeline_version  TEXT NOT NULL,
    root_job_id       TEXT,                 -- ссылка на task_jobs.job_id (root job)
    status            TEXT NOT NULL,        -- running|succeeded|partial|degraded|failed|cancelled|interrupted
    reason_code       TEXT,
    started_at        INTEGER NOT NULL,     -- unix UTC
    finished_at       INTEGER,
    heartbeat_at      INTEGER,
    progress_at       INTEGER,
    deadline_at       INTEGER,
    checkpoint_ref    TEXT,
    config_version    TEXT,
    created_at        INTEGER NOT NULL,
    updated_at        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mca_pipeline_runs_status ON mca_pipeline_runs (status, started_at);
CREATE INDEX IF NOT EXISTS idx_mca_pipeline_runs_type_started ON mca_pipeline_runs (pipeline_type, started_at);
CREATE INDEX IF NOT EXISTS idx_mca_pipeline_runs_root_job ON mca_pipeline_runs (root_job_id);

-- 5.1.2. mca_incidents — durable инциденты
CREATE TABLE IF NOT EXISTS mca_incidents (
    incident_id        TEXT PRIMARY KEY,
    fingerprint        TEXT NOT NULL,       -- process_id|pipeline_type|stage|reason_code|error_type|dependency
    process_id         TEXT,
    pipeline_type      TEXT,
    stage              TEXT,
    severity           TEXT NOT NULL,       -- INFO|WARN|ERROR
    title              TEXT,
    first_ts           INTEGER NOT NULL,
    last_ts            INTEGER NOT NULL,
    repeat_count       INTEGER NOT NULL DEFAULT 1,
    jobs_json          TEXT,                -- bounded JSON-массив job_id
    chats_json         TEXT,                -- bounded JSON-массив chat_id
    impact             TEXT,                -- R17-safe описание
    fallback_used      INTEGER NOT NULL DEFAULT 0,
    first_trace_id     TEXT,
    last_trace_id      TEXT,
    acknowledged_at    INTEGER,
    acknowledged_by    INTEGER,
    resolved_at        INTEGER,
    resolution_evidence TEXT,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mca_incidents_fingerprint ON mca_incidents (fingerprint, last_ts);
CREATE INDEX IF NOT EXISTS idx_mca_incidents_active ON mca_incidents (resolved_at, last_ts);
CREATE INDEX IF NOT EXISTS idx_mca_incidents_severity ON mca_incidents (severity, last_ts);

-- 5.1.3. task_jobs — correlation/span/progress (nullable)
ALTER TABLE task_jobs ADD COLUMN pipeline_run_id TEXT;   -- guard PRAGMA table_info
ALTER TABLE task_jobs ADD COLUMN span_id         TEXT;
ALTER TABLE task_jobs ADD COLUMN parent_span_id  TEXT;
ALTER TABLE task_jobs ADD COLUMN causation_id    TEXT;
ALTER TABLE task_jobs ADD COLUMN attempt_id      TEXT;
ALTER TABLE task_jobs ADD COLUMN progress_at     INTEGER;
ALTER TABLE task_jobs ADD COLUMN next_retry_at   INTEGER;
ALTER TABLE task_jobs ADD COLUMN checkpoint_ref  TEXT;
CREATE INDEX IF NOT EXISTS idx_task_jobs_pipeline_run ON task_jobs (pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_task_jobs_status_heartbeat ON task_jobs (status, heartbeat_at);
CREATE INDEX IF NOT EXISTS idx_task_jobs_status_next_retry ON task_jobs (status, next_retry_at);

-- 5.1.4. mca_events — расширение span-контракта §27.3 (nullable)
ALTER TABLE mca_events ADD COLUMN pipeline_run_id  TEXT;
ALTER TABLE mca_events ADD COLUMN pipeline_type    TEXT;
ALTER TABLE mca_events ADD COLUMN pipeline_version TEXT;
ALTER TABLE mca_events ADD COLUMN span_id          TEXT;
ALTER TABLE mca_events ADD COLUMN parent_span_id   TEXT;
ALTER TABLE mca_events ADD COLUMN linked_span_ids  TEXT;   -- JSON-массив
ALTER TABLE mca_events ADD COLUMN job_id           TEXT;
ALTER TABLE mca_events ADD COLUMN attempt_id       TEXT;
ALTER TABLE mca_events ADD COLUMN causation_id     TEXT;
ALTER TABLE mca_events ADD COLUMN event_sequence   INTEGER;
ALTER TABLE mca_events ADD COLUMN status           TEXT;   -- состояние стадии (§27.4)
ALTER TABLE mca_events ADD COLUMN heartbeat_at     INTEGER;
ALTER TABLE mca_events ADD COLUMN progress_at      INTEGER;
ALTER TABLE mca_events ADD COLUMN deadline_at      INTEGER;
ALTER TABLE mca_events ADD COLUMN checkpoint_ref   TEXT;
CREATE INDEX IF NOT EXISTS idx_mca_events_pipeline_run ON mca_events (pipeline_run_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_mca_events_span ON mca_events (span_id);
CREATE INDEX IF NOT EXISTS idx_mca_events_status ON mca_events (status);
```

**Примечания к DDL (решения):**
- **`mca_process_registry` НЕ создаётся** — реестр процессов **code-declared** (§4.1/D1); вторая копия в БД дрейфует и нарушает REUSE. Остальные заявленные PM объекты (`mca_pipeline_runs`/`mca_incidents` + nullable-колонки correlation/span) — принимаются.
- **`event_id` = существующий `mca_events.id`** (INTEGER PK); отдельная колонка не вводится. `event_sequence` — новый nullable INTEGER (монотонный в рамках run).
- **`start`/`end`** отдельными колонками не вводятся: start = `ts` start-события span, end = `ts` терминального; run-level — `started_at`/`finished_at` в `mca_pipeline_runs`.
- **`heartbeat_at`/`fencing_token`/`generation`/`attempt`/`deadline_at`/`coalesce_key` в `task_jobs` не дублируются** (уже есть в v14).
- **Индексы** — только под реальные запросы; подтверждение `EXPLAIN QUERY PLAN` обязательно в T-3864 (watchdog по `(status, heartbeat_at)`/`(status, next_retry_at)`; trace по `(pipeline_run_id, event_sequence)`/`span_id`; фильтры §27.4 — `status`).

### 5.2. Бронь версий (критический путь)
- **v19 бронируется за `mca-17a`** (рамка `mca-round1027-arch-frames.md` **§1.2.4**). Advisory-заявка `mca-04b` «v19+» **сдвигается на v20+** (отдельная заявка @Architect при старте `mca-04b`; ранее `mca-04b` уже сдвигался v18→v19). Альтернатива (Δ DDL=0 у `mca-17a`) — **отклонена** (§5.3).

### 5.3. Почему не Δ DDL = 0
§27.7 требует durable run-состояния, индексов по run/status и серверной пагинации; §27.3 — correlation в durable queue/resume и root-job/batch; §27.6 — durable `acknowledged ≠ resolved` + история инцидента после исчезновения ошибки + `checkpoint_ref` для recovery. Хранение span/incident-полей в существующих JSON-колонках (`entity_ids`/`usage_json`) сделало бы их неиндексируемыми и неотличимыми от уже занятых полей — это анти-паттерн, нарушающий §27.7 и делающий SC-14/SC-15 непроверяемыми. Вывод: **v19 обязательна**.

### 5.4. Δ каталога = **0**
Все рубильники/пороги/лимиты §27 — инфраструктурные/аварийные, **env-only `ClassVar`** (прецедент `DB_LOCK_RESILIENCE_ENABLED`/`KILL_SWITCHES`); UI-настроек §27 не добавляет. `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES — вне diff; каталог `473/430/448/102/100/21` не меняется; **F8 (ADR-1026-2) NOT_APPLICABLE**. Если позднее потребуется UI-настройка порогов — это **Δ каталога ≠ 0** и обязательная процедура F8 (repin/recount) отдельной заявкой.

### 5.5. Fault-injection вне effective-state
`MCA_FAULT_INJECTION_ENABLED` — **не** product-функция и **не** регистрируется как процесс/виджет; это тест-харнесс/env-флаг, доступный только dev/test. В effective-state §20.2 перечисляется как «отсутствует в production» (рядом с намеренно неактивным stub §14.12 `mca-10c`); «все ON» относится к product-функциям, поэтому противоречия нет. Обычным участникам недоступен; production-постоянно не включается (§27.9).

---

## 6. Сценарии приёмки (SC) и приёмки §19

| SC | Сценарий | Приёмка §19 |
|---|---|---|
| SC-01 | Реестр процессов полон: каждый активный процесс имеет `process_id`/version/назначение/IO/стадии/триггер/настройки/state_source/recovery_ops/`widget_id`; mapping стадий на события; статус `implemented/disabled/not_run/not_instrumented` с причиной; «новый процесс без наблюдаемости = незавершённая интеграция» | A48 |
| SC-02 | Реестр сверен с фактическим кодом (handlers/workers/расписания/инструменты/пути отправки); число карточек ≠ покрытие; закрытые `mca-03`/`02`/`04a`/`07` зарегистрированы без переизобретения событий | A48 |
| SC-03 | Span-поля присутствуют сквозь `start`+терминальное `outcome`; `sanitize()` до записи; тот же store (второго нет) | A49 |
| SC-04 | Correlation проходит durable queue и восстанавливается при resume; retry = новый `attempt_id`, предыдущая ошибка не затирается | A49 |
| SC-05 | Root job + отдельные batch traces (не один бесконечный span); счётчики/ссылки на проблемные записи; failures не скрыты средним | A49 |
| SC-06 | Parent-child только для реального вложения; singleflight/cache — `linked_span_ids`; параллельные ветви — отдельные spans; монотонные часы/UTC; связь по ID/sequence | A49 |
| SC-07 | 9 состояний стадии + run `partial/degraded` + диагностическое `stalled`; у каждого skip причина и влияние | A50 |
| SC-08 | Обязательные/необязательные стадии по pipeline version; `succeeded`/`degraded|partial`/`failed|interrupted`; run не success при незафиксированной записи/обязательном дочернем job; async продолжение — linked job с pending | A50 |
| SC-09 | Ошибка информативна и честна (traceback/cause/failed stage/last successful/attempt/elapsed/deadline/dependency/impact/fallback/checkpoint/recovery); «предполагаемая причина» отдельно; нулевой результат ≠ падение; SQL/parse ≠ «нет воспоминаний»; ветвь не стирает чужой успех | A50 |
| SC-10 | После SIGKILL/потери машины — честный `interrupted`; причина не выдумывается | A50/A51 |
| SC-11 | Heartbeat ≠ progress; 15 s/60 s; progress-stall по типу стадии; конфигурируемо; длительная транскрибация не «упала» через минуту; очередь/внешнее время отдельно | A52 |
| SC-12 | Heartbeat не продлевает deadline без смены этапа; bounded retries (`next_retry_at`); recovery по checkpoint только безопасных этапов; `delivery_unknown` до сверки | A51/A52 |
| SC-13 | Watchdog проверяет durable state periodically+startup; детект вне loop; UI `telemetry stale/unknown` (нет старого «зелёного») | A51 |
| SC-14 | Fencing/generation защищает **во всех** терминальных записях (включая cancelled/failed — L-MCA01-5); дублей результата нет | A51 |
| SC-15 | Активные инциденты (все поля); группировка по устойчивому признаку с отдельными trace/счётчиком; fallback снижает влияние, но не скрывает; новые симптомы не сливаются по слову «timeout»; `acknowledged ≠ resolved`; история сохраняется | A55 |
| SC-16 | Доставка в открытый миниапп ≤10 s (polling); reconnect по cursor + сверка; только миниапп; stack traces не публикуются; R17 | A55/A53 |
| SC-17 | Durable (не только fire-and-forget); tx/подтверждения/`status pending`; bounded batch; lock не держится при сети; spool/`telemetry_degraded`/`gaps`; нет бесконечного RAM; нет ложного полного trace | A53 |
| SC-18 | cancel/resume/retry по правам/audit/идемпотентно; read-only refresh; без слепого повтора side effect; `delivery_unknown` — сверка; нет произвольного кода/SQL; fault injection вне prod; демо-данные отдельно | A56 (ядро) |
| SC-19 | Контролируемые сценарии §27.9 (13) проверяются через **видимый** статус/этап/причину/восстановление (API/миниапп), не только исключение в unit-тесте | A50–A53/A55 |
| SC-20 | REUSE: нет второго store/аналитики/`TaskSupervisor`/write-механизма; ExecutionGraph+`mca_events` расширены аддитивно; UI не ходит в БД | GEN-R19/R21 |
| SC-21 | v19 аддитивна/идемпотентна через реестр; `nullable`=честный unknown; PG no-op; старые таблицы/ID сохранены; повторный прогон — no-op; OFF kill-switch = точный legacy-путь | A28 |
| SC-22 | Живые продюсеры `runtime`-метрик или честный `unknown` (`UNKNOWN ≠ 0`); wiring `flush`/`prune` с уважением **обоих** kill-switch; reassessment триггера «конкуренция записи» (R2→R3) зафиксирован | A48/A53 |

**A48–A53/A55 — в scope `mca-17a`** (§3.2–§3.6). **A54/A56/A57/A73 — закреплены за `mca-17c`**: `mca-17a` поставляет реестр/trace/lifecycle/инциденты/control-plane ядро (вход `mca-17c`), UI-приёмка — у `mca-17c`. **SC-16 (AMEND F5/D16) — остаётся в `mca-17a`:** транспорт (read-only endpoint + cursor + refresh индикатора ≤10 s) — данные-API; полное представление «Инциденты»/фильтры/drill-down/уровни/граф/диагностические действия — `mca-17c`. Перенос транспорта в `mca-17c` **отклонён** — это сузило бы §27.6 в `mca-17a` и обесценило A55.

---

## 7. Риск

- **Level: R3** (подтверждено). Обоснование: ядро наблюдаемости лежит на общем write-path/очереди событий/durable job state (flush на общем `write_transaction`, watchdog/takeover меняет durable-статусы, инциденты пишутся в ту же SQLite, migration v19 меняет схему). Обязателен `threat-failure-analysis.md` (T-3884/блок H).
- **Reassessment carry-over §94.5 п.5:** при подключении `flush_events`/`prune_events` в worker-loop/периодический job триггер «конкуренция записи» **срабатывает** → кандидат R2→R3 **эскалирован в R3** (запись батчей конкурирует за single-writer lock с direct flow). Зафиксировано (SC-22/T-3881); финальная ратификация — @Reviewer по фактическому diff (T-3885).
- **Что может поднять риск:** необходимость писать телеметрию синхронно на hot-path ответа (а не батч/фон) → R3 (усиление) и обязательная дополнительная изоляция; выявление удаления/перезаписи legacy-строк миграцией; превышение `MCA_TELEMETRY_SPOOL_MAX_EVENTS` с непокрытым `gaps`-контуром.
- **Что может понизить до R2:** доказанная изоляция телеметрии от hot-path (batch/фон, writer lock не удерживается при сети), отсутствие перезаписи legacy, A48–A53/A55 на фактическом diff.

---

## 8. Зависимости

- **Вход — ✅ закрыто:** `mca-14` (§93 — migration-runner + реестр `schema_migrations` + механизм заявки Δ DDL; **REUSE**, версии после v18); `mca-13` (§94 — `emit_mca_event`/`mca_events`/`mca_event_aggregates`/`reason_code`/`sanitize()`/ретенция 14/90/`metrics()`/`query_events`; **REUSE**, второй store запрещён); `mca-01` (§95 — `TaskSupervisor`/`task_jobs`/fencing/generation/coalescing/единый write-механизм; **REUSE**); `mca-03`/`mca-02`/`mca-04a`/`mca-07` ✅ (источник стадий/виджет-ID/событий).
- **Исходящие (потребители):** `mca-17c` (полная матрица §27.1/витрина/самообучение/диагностические действия UI/нагрузочный замер); `mca-04b` (доменные версии **v20+**); `mca-06`/`mca-16`/`mca-18`/`mca-19`/`mca-20` (регистрируют свои стадии/виджет-ID в реестре `mca-17a`); `mca-release` (migration smoke v19, effective-state/manifest).
- **Внешние зависимости:** нет новых SaaS/провайдеров/Kafka/monitoring cluster (§27.3).

---

## 9. Расхождения ТЗ↔код (зафиксировано)

1. **`mca_events.status` отсутствует как колонка**, хотя `status` — в `_CODE_FIELDS` `build_event` → значение молча теряется при `flush_events` (INSERT без `status`). Исправляется v19 (§5.1.4).
2. **`flush_events`/`prune_events` не подключены** (только тесты) → durable-персистенция не работает в проде. Carry-over §94.5 п.4; закрывается T-3881.
3. **`recover_stale()` не вызывается** ни одним watchdog-циклом → takeover/fencing не работают в runtime. Закрывается T-3876.
4. **`TaskSupervisor`/`TaskJobStore` не подключены в проде** (только тесты) → L-MCA01-5 обязателен **до** первого прод-подключения (T-3882).
5. **`metrics(runtime=...)` без продюсера** → группы `runtime`/`cache`/`provenance`/`memory`/`downloads` всегда `unknown`. Закрывается T-3881.
6. **SSE/WebSocket отсутствуют** → доставка §27.6 реализуется polling'ом (решение, не расхождение): «SSE/WebSocket использовать, если уже есть подходящая инфраструктура» — её нет.
7. **`mca_event_aggregates` ≠ инцидент**: агрегат события не даёт acknowledge/resolve/history/затронутых jobs/chats → нужна `mca_incidents` (v19).
8. **Заявка PM `mca_process_registry`** скорректирована: реестр — code-declared (обоснование §4.1/§5.1).
9. **Числовые ориентиры `tasks.md`** (каталог `473/…`, pytest 9758/0, DDL v18) — соответствуют baseline; расхождений нет. Ссылки задач на карту плана: `plans/docs/mca-round1027-plan.md` содержит §0–§7 (не §11) — релевантный материал — §3.7 (закрытие `mca-07`)/§3.8 (настоящий шаг)/§6 п.9.

---

## 10. Тесты / деплой / откат

- **Тесты (T-3883):** pytest `.venv` полный прогон + focused `mca-17a`; SC-01…SC-22 (включая SC-16 транспорт: read-only endpoint инцидентов + cursor-реконнект + refresh ≤10 s; §4.10 read-only endpoint реестра); контролируемые сценарии §27.9 (13: timeout провайдера; невалидный JSON; ошибка записи после успешного LLM; отмена parent/child; гибель worker между checkpoint и terminal event; рестарт; потеря heartbeat; живой heartbeat без прогресса; сбой log storage; reconnect миниаппа; ошибка одной параллельной ветви; неясный результат отправки; завершение shared task для нескольких потребителей) — с проверкой **видимого** статуса/этапа/причины/восстановления через API/миниапп; регрессии Epic 1–3 + `mca-03`/`02`/`04a`/`07`; `EXPLAIN QUERY PLAN` для новых индексов; kill-switch OFF = точный legacy-путь; R17-маскировка (caplog + durable-строка + экспорт); маскирование не удаляет техническую причину. Воспроизведение — на fixtures без внешних платных операций.
- **Deploy:** `DEFERRED_TO_RELEASE` (§20; пер-фичевых деплоев/тегов/bump нет; агрегатный релиз — `mca-release`). На `mca-release` — migration smoke v19 (fresh+legacy, идемпотентность), backup+read-back, effective-state §20.2, manifest (`config changes` — имена kill-switch/порогов; fault-injection — dev/test-only).
- **Откат:** hot — kill-switch (master `MCA_OBSERVABILITY_ENABLED=false` и/или под-гейты); cold — `git revert` → `05bc870` (анкер `7165ff7`); v19 аддитивна (новые таблицы/колонки безвредны; данные не теряются); restore БД — только аварийный сценарий (R18: теги/бэкапы не удаляются).

---

## 11. Frontend / Browser-Verification контракт

- **Browser-Verification: REQUIRED** — фича меняет пользовательски видимую часть существующей витрины (carry-over SC-13/SC-14: metrics §17.4 + фильтры/переходы к связанным событиям на REUSE log viewer). Полная матрица «Аналитики» — `mca-17c`; здесь проверяется только carry-over.
- **Обязательные claims (нужен structured browser behavior check):**
  - SC-13: аддитивный блок `mca_metrics` на `#/oversight` отображает группы §17.4; группа без продюсера — честно «неизвестно», **не** `0`/«здоровье»; с живым продюсером — реальные значения; stale-переход → «unknown», без старого «зелёного».
  - SC-14: в лог-viewer (`#/status` логи) доступны фильтры `trace_id`/`chat_id`/`component`/`reason_code`; переход из карточки открывает **связанные** события нужного trace (deep link, не начало страницы); пустой результат — честный empty state.
- **Routes/entry points:** `#/oversight` (метрики), `#/status` → блок логов (фильтры). **Предусловие:** глобальный админ в TMA; kill-switch ON (`MCA_OBSERVABILITY_ENABLED`+`MCA_EVENT_CONTRACT_ENABLED`+`MCA_TELEMETRY_STORE_ENABLED`); предзаполненные fixtures `mca_events` (start+outcome, разные trace/component/reason/chat; одна группа с `available=false`); SSOT — существующий viewer, **без** новых панелей/маршрутов/endpoint.
- **Аутентификация:** используется существующий TMA-контур (initData/`requires_global_admin`); отдельные тест-креды не создаются.
- **Viewports:** 390×844 (TMA mobile, список стадий) + 1280×800 (desktop).
- **Loading/error/empty:** загрузка metrics — skeleton/«…»; пусто (нет событий) — честный empty, группы `unknown`; ошибка API — fail-open пустой shape, без console errors.
- **Console/network:** ошибок в console нет; сетевые запросы — на существующие endpoint (`/api/oversight/summary`, `/api/status/logs`) с аддитивными полями + read-only endpoint инцидентов (§4.10) без утечек R17.
- **SC-16 (транспорт, structured check):** при открытом компактном индикаторе инцидентов формируется повторяющийся запрос read-only endpoint `incident_changes` с интервалом ≤ `MCA_INCIDENT_PUSH_INTERVAL_SECONDS` и cursor-параметром; reconnect — догрузка пропущенного по cursor. Registry snapshot API (§4.10) — **backend-only claim** (браузер не требуется).
- **Что требует visual screenshot inspection:** только корректность отображения «unknown vs 0» и локализация фильтров/ссылки (визуальные подписи статуса рядом с цветом, reduced motion). Всё остальное — structured checks (DOM/ARIA/сеть).
- **Инструмент:** **Playwright MCP** — дефолтный детерминированный таргет. **Browser Use** дополнительно — только при materially visual проверке/сбое Playwright, которого он не воспроизводит; на текущем объёме carry-over не требуется.
- **Backend-only claims (не требуют браузера):** реестр, span-контракт, lifecycle, watchdog/fencing, инциденты (polling-эндпоинт), spool/degraded/gaps, control-plane — проверяются API/durable-состоянием.

---

_Конец документа. Создано @Architect в рамках Step 2 фичи `mca-17a-observability-core` (T-3861/T-3862); код/`plans/current_task.md`/`workflow_state.md`/`metrics.md`/`MEMORY.md` не менялись; секреты источника не цитировались (R17)._
