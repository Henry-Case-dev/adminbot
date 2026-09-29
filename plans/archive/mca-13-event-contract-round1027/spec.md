# `mca-13-event-contract` — спецификация (Step 2 @Architect, T-3765)

- **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 0**. **Фича-ID:** `mca-13-event-contract`.
- **Тип:** backend/observability — структурированные события, словарь причин, ошибки/маскировка/ретенция, метрики витрины. **P0-enabler** (все фичи пишут события этого контракта; MCA-17 собирает наблюдаемость поверх, **не создавая** второй store).
- **Источник (IMMUTABLE, R17/R18):** `plans/current_task.md` **§17** (`:818–854`: §17.1 `:818–828`, §17.2 `:830–836`, §17.3 `:838–846`, §17.4 `:848–854`), §2.16; сквозные §27.1/§27.3/§27.7; проверки §19 **A27**, **A53**.
- **Задачи:** `tasks.md` T-3763…T-3776. **Приёмка:** A27, A53.
- **ADR:** `adr-1027-2-event-contract.md` (D1–D11). **Рамка:** `plans/docs/mca-round1027-arch-frames.md`.
- **Статус:** Proposed → Accepted по T-3776. **Deploy:** `DEFERRED_TO_RELEASE`.
- **Risk-Level:** **R2** — расширение существующего logging/analytics; риск — рост объёма/утечка через логи. Триггеры повышения до R3: утечка секретов/PII в durable-store, конкуренция записи на hot-path, неограниченный рост объёма. При R3 — `threat-failure-analysis.md`.
  - **Ратификация R2 (Step 2-адъюдикация, 26.09.2026):** B-MCA13-1 (R17-маскирование) закрыт — `sanitize()` применяется ко всем строковым и сериализованным JSON-полям до буфера/лога + defense-in-depth в `_emit_log`; покрыто e2e-тестами, включая проверку durable-строки. Триггер «утечка в durable-store» не сработал; «конкуренция на hot-path» не сработал (durable write не подключён к hot-path, см. §1.1); «неограниченный рост» не сработал (bounded deque + `prune_events`). R2 сохраняется. **Если `mca-17a` подключит `flush_events` к worker-loop/hot-path — обязателен пересмотр триггера конкуренции (кандидат R3).**
- **Baseline:** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v12**; каталог `473/430/448/102/100/21`; канон 12.

## 1. Область и исключения

**Входит:** финальный JSON-контракт события §17.1 (поля, `start`+terminal `outcome`, `interrupted`); расширение существующей точки эмиссии `emit_agentic_event`; словарь `reason_code` §17.2 (минимум + расширяемость); ошибки/агрегация/маскировка/R17/ретенция §17.3 (14d/90d); **backend-часть** метрик §17.4 — единый адаптер (`mca_events.metrics()` с `UNKNOWN`≠0) и фильтры чтения (`query_events` по trace/chat/component/reason, bounded LIMIT); совместимость с ExecutionGraph §82–§92 (REUSE adapter, вторая аналитика запрещена).

**Не входит (границы):** реестр процессов/trace-span-lifecycle/инциденты/watchdog (MCA-17a — строится **поверх** этого контракта и **того же** store); второй event-store/вторая аналитика; изменение поведения решений/инструментов; durable-хранение **нетерминальных** подробных строк (они — в структурном логе 14d); **UI-презентация SC-13/SC-14** (метрики на витрине, переходы из карточек к связанным событиям, логи в существующем viewer) и **живые продюсеры/фоновый контур** (wiring `flush_events`/`prune_events` в worker-loop/shutdown, поставка `runtime`-источников RSS/cache/downloads/provenance/histories/episodes).

### 1.1. Санкционированный перенос в `mca-17a` (Step 2-адъюдикация, 26.09.2026)

> Основание: ADR-1027-2 **D8** (новые endpoint/панели запрещены — только REUSE существующего viewer) + план эпика: `MCA13-R4` числится за `mca-13` **и** `mca-17a/c`; представление «Аналитика» и финальная матрица виджетов — `mca-17a`/`mca-17c` (§27.2), обязательный контур наблюдаемости — `mca-17a` (§27.3–§27.7). Backend контракта завершён в `mca-13`; UI/живой контур — предмет `mca-17a`.

**Carry-over register `mca-13` → `mca-17a` (обязателен к включению в spec/tasks `mca-17a` при её старте):**

1. **UI SC-13:** вывод метрик §17.4 на существующей витрине (REUSE viewer, без новых панелей/endpoint).
2. **UI SC-14:** фильтры trace/chat/component/reason в UI; переход из карточки к связанным событиям; логи в существующем viewer.
3. **Живые продюсеры метрик:** поставка `runtime`-контура (`rss_mb`, `cache_entries`, `downloads`, `provenance_coverage`, `histories`/`episodes`); до подключения соответствующие группы отдаются как `unknown` (это корректно, `UNKNOWN`≠0).
4. **Фоновый контур телеметрии:** wiring `flush_events`/`prune_events` в worker-loop/периодический job/shutdown; при этом `flush_events` должен уважать **оба** kill-switch (`MCA_EVENT_CONTRACT_ENABLED` и `MCA_TELEMETRY_STORE_ENABLED`).
5. **Пересмотр risk:** при подключении flush на hot-path/worker-loop — обязательный reassessment триггера «конкуренция записи» (кандидат R2→R3).

## 2. Трассируемость REQ → SC

| REQ | §ТЗ | SC | Задачи |
|---|---|---|---|
| REQ-MCA13-01 — структурированный JSON event (поля §17.1) | §17.1 `:822` | SC-01, SC-02 | T-3767 |
| REQ-MCA13-02 — start + terminal outcome; `interrupted`; нет `except: pass` | §17.1 `:824` | SC-03, SC-04 | T-3768 |
| REQ-MCA13-03 — поля по типам (решение/retrieval/контекст/архив/сон); без скрытой CoT | §17.1 `:826–828` | SC-05 | T-3767 |
| REQ-MCA13-04 — стабильный расширяемый словарь `reason_code`; ≠ один `skip`; WARN/ERROR влияние/fallback | §17.2 `:832–836` | SC-06, SC-07 | T-3769 |
| REQ-MCA13-05 — ERROR-метаданные + агрегация (счётчик/первое-последнее/первый trace); пустой поиск=INFO | §17.3 `:842` | SC-08, SC-09 | T-3770 |
| REQ-MCA13-06 — маскирование R17; без дубля сырого контекста; доступ к журналам | §17.3 `:844` | SC-10 | T-3771 |
| REQ-MCA13-07 — ретенция 14/90 (настраиваемо); ручные/происхождение вне ротации; нет неограниченного буфера | §17.3 `:846` | SC-11, SC-12 | T-3772 |
| REQ-MCA13-08 — метрики §17.4; `UNKNOWN`≠0; фильтры trace/chat/component/reason | §17.4 `:852–854` | SC-13, SC-14 | T-3773 (backend ✔; UI → `mca-17a`, §1.1) |
| REQ-MCA13-09 — совместимость с ExecutionGraph §82–§92 (REUSE adapter, вторая аналитика запрещена) | §17 преамбула `:810`; §17.4 | SC-15 | T-3773, T-3775 |
| REQ-MCA13-10 — deploy `DEFERRED_TO_RELEASE`; R17 end-to-end | §2.16; §20 | SC-16 | T-3774, T-3775 |

**Орфан-REQ нет:** каждый REQ ≥1 SC; T-3763/3764/3776 — процессные (baseline/PM/ревью-merge).

## 3. Наблюдаемое поведение и отказы

- Каждое принятое в обработку событие имеет `start` и терминальный `outcome`; незавершённые после crash → `interrupted` (помечает supervisor `mca-01`). Ожидаемые пустые исходы — INFO, повреждение данных — ERROR; исключение никогда не исчезает.
- Повторяющиеся ошибки агрегируются, но виден факт продолжения сбоя (счётчик/первое-последнее/первый полный trace).
- Секреты/credentials/initData/URL-параметры маскируются **до записи во все каналы**; сырой контекст не дублируется (SourceRef + сокращённый снимок).
- При недоступности телеметрии/исчерпании буфера — видимый `degraded/gap`, ограниченный рост памяти, без ложного полного trace (A53).
- Метрики витрины считаются из **одного** адаптера; `UNKNOWN` показывается как «неизвестно», не как 0/здоровье.

## 4. Интерфейсы и контракты

### 4.1. Схема события (D1)
Закрытый контракт полей §17.1 (обязательные/опциональные): `timestamp UTC`, `level` (`INFO|WARN|ERROR`), `event_name`, `trace_id`, `operation_id`, `parent_operation_id`, `chat_id`, `trigger/message refs`, `component`, `stage`, `status`/`outcome`, `reason_code`, краткая причина, `duration_ms`, `attempt`, `config_version`, `model`/`provider` (при наличии), relevant entity IDs, `usage`/`cost`, `error metadata`. `trace_id` = существующий `run_id`/`correlation_id` (S7/S8); второго идентификатора нет.

**Терминальные `outcome`:** `success|silent|skipped|failed|cancelled|pending_external|interrupted` (+ событие-start). Per-тип поля (D3): решение — рассмотренные действия, оценки с пометкой «оценка модели», выбранное действие, основные источники, роль случайности, stale-check, факт доставки (без скрытой CoT); retrieval — query type/filters/candidates/selected IDs/reranker status/empty reason/версии индексов; контекст — размеры по блокам/payload estimate/output reserve/exclusions; архив — range/cursor/checkpoint/rate/coverage; сон — основания/уникальные источники/новые-изменённые-отклонённые выводы/причины.

### 4.2. Точка эмиссии (D2)
- Единая **fail-open** обёртка над существующим `services/agentic_events.py::emit_agentic_event` (R17-whitelist, sync, без `await`): per-call kill-switch → расширенный whitelist/контракт → структурная строка лога → аддитивная запись в `mca_events` (только терминальные события) → при необходимости в существующий `RunSnapshotStore`. **Никогда не бросает.** Второй логгер/канал/store не создаётся.

### 4.3. Хранилище/ретенция (D4)
- Durable-стор терминальных событий — `mca_events` (v15; см. рамку §1.1.2) + `mca_event_aggregates`; подробные строки (14d) — структурный лог → `services/log_ring.py` (bounded, `LOG_RING_MAX_ENTRIES`) + файл/journald. Единый store для MCA-13/MCA-17a; вторая телеметрия запрещена.
- Ретенция: `MCA_DETAILED_LOG_RETENTION_DAYS`=14, `MCA_TERMINAL_EVENT_RETENTION_DAYS`=90 (env-only `ClassVar`, настраиваемо); ротация/удаление старых терминальных событий + row-cap. События ручного изменения и происхождение памяти этой ротацией **не** удаляются. In-memory буфер — только bounded.

### 4.4. Словарь причин (D5)
Минимум §17.2 (28 кодов) — закрытый **базовый** набор, расширяемый (реестр кодов + алиасы); разные исходы не сводятся к `skip`; у `WARN`/`ERROR` обязательны поле влияния и выполненный fallback. Коды синхронизированы с §24.5/§27 (MCA-15/17).

### 4.5. Ошибки/агрегация (D6)
`error_json`: тип исключения, очищенный stack trace, cause chain, стадия, retryability, результат восстановления. Агрегация по `fingerprint(event_name+component+reason_code+error_type)`: `count/first_ts/last_ts/first_trace_id/first_error_json`. Агрегация не скрывает продолжение сбоя.

### 4.6. ExecutionGraph-совместимость (D7)
`run_id`=correlation_id (S7/S8); существующие `RunSnapshotStore`/`build_graph`/`GET /analytics/execution/latest` **расширяются** аддитивно (узлы/связки trace), вторая аналитика/endpoint запрещены. `mca-17a` потребляет те же события/узлы.

## 5. Δ DDL / Δ каталога / kill-switch

- **Δ DDL:** **v15** — `mca_events`, `mca_event_aggregates` + индексы (рамка §1.1.2). PG — no-op.
- **Δ каталога:** **0** (env-only `ClassVar`; ретенция тоже). F8 не переиздаётся.
- **Kill-switch:** `MCA_EVENT_CONTRACT_ENABLED` (default ON; OFF → события как сейчас, без start/outcome) и `MCA_TELEMETRY_STORE_ENABLED` (default ON; OFF → только структурный лог, без durable-персистенции). Существующий `AGENTIC_EVENTS_ENABLED` уважается.

## 6. Приёмочные сценарии (SC)

- **SC-01:** событие любого типа несёт обязательные поля §17.1; R17-whitelist отбрасывает небезопасные ключи.
- **SC-02:** `trace_id` = `run_id`/`correlation_id`; события группируются в одну трассировку от start до терминала.
- **SC-03:** у каждого принятого события есть start и терминальный `outcome`; незавершённое после crash → `interrupted`.
- **SC-04:** ни одно исключение не исчезает (нет `except: pass`); тест на сбойный путь.
- **SC-05:** решение/retrieval/контекст/архив/сон несут свои поля §17.1; скрытая CoT не запрашивается/не сохраняется.
- **SC-06:** `reason_code` — стабильный расширяемый словарь; разные исходы различимы; `skip` не replaces конкретных кодов.
- **SC-07:** у `WARN`/`ERROR` видны влияние и выполненный fallback.
- **SC-08:** ERROR содержит тип/очищенный stack/cause chain/стадию/retryability/результат восстановления; пустой поиск = INFO.
- **SC-09:** агрегация повторяющейся ошибки даёт счётчик/первое-последнее/первый полный trace; продолжение сбоя видно.
- **SC-10:** секреты/credentials/initData/URL-параметры маскируются во всех каналах и при экспорте; сырой контекст не дублируется; доступ к журналам ограничен.
- **SC-11:** ретенция 14d (подробные)/90d (терминальные) применяется и настраивается; ручные изменения/происхождение не удаляются.
- **SC-12:** in-memory буфер bounded; при исчерпании — `degraded/gap`, память не растёт неограниченно.
- **SC-13 (backend — закрыт в `mca-13`):** единый адаптер `mca_events.metrics()` отдаёт группы §17.4; поле без продюсера → `available=False`/`None`; `UNKNOWN` ≠ 0/здоровье. **UI-часть** (метрики на витрине) — carry-over `mca-17a` (§1.1).
- **SC-14 (backend — закрыт в `mca-13`):** `query_events` фильтрует по `trace/chat/component/reason` с bounded LIMIT. **UI-часть** (фильтры в интерфейсе, переход из карточки к связанным событиям, логи в существующем viewer) — carry-over `mca-17a` (§1.1).
- **SC-15:** ExecutionGraph §82–§92 не сломан; вторая аналитика/endpoint не созданы; узлы строятся из реальных данных.
- **SC-16:** retention/deploy `DEFERRED_TO_RELEASE`; R17-тесты end-to-end зелёные; логи/экспорт без секретов.

## 7. Зависимости

Нет обязательных предшественников. Потребители: `mca-17a` (реестр/span/lifecycle/инциденты — поверх того же store; **несёт carry-over §1.1**: UI SC-13/SC-14, живые продюсеры, wiring flush/prune), `mca-01` (события транзакций/задач), волны 1–5. Внешние сервисы не требуются.

## 8. Тесты / деплой / откат

- **Тесты:** unit контракта/словаря/маскирования/агрегации; A27 (сбой провайдера/БД/парсинга/job → видимый terminal outcome) и A53 (недоступность телеметрии/исчерпание буфера → degraded/gap, bounded memory); R17; JS-адаптер ExecutionGraph; регресс pytest ≥ baseline, JS зелёные, `git diff --check`=0.
- **Деплой:** `DEFERRED_TO_RELEASE`; на `mca-release` — migration smoke (`mca_events`), проверка backend-метрик/фильтров (`metrics()`/`query_events`), R17-проверка. UI-проверка витрины/переходов — при `mca-17a` (carry-over §1.1).
- **Откат:** hot — `MCA_EVENT_CONTRACT_ENABLED=false`/`MCA_TELEMETRY_STORE_ENABLED=false`; cold — `git revert` → `7165ff7` (`mca_events` безвреден).
