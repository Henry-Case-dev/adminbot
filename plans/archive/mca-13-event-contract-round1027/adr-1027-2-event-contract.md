# ADR-1027-2 — `mca-13-event-contract`: единый контракт события §17.1 (start+terminal `outcome`, `interrupted`), расширяемый словарь `reason_code` §17.2, ошибки/агрегация/маскировка R17/ретенция 14d–90d §17.3, метрики витрины §17.4; REUSE `emit_agentic_event`/ExecutionGraph §82–§92 (вторая аналитика запрещена) — Δ DDL = v15 (`mca_events` + агрегаты), Δ каталога = 0, R2

- **Статус:** **✅ Accepted** — фактом мержа волны 0 MCA (round 10.27, 26.09.2026) в `plans/ARCHITECTURE.md` **§94** (`mca-13-event-contract`). На момент Step 2 @Architect — Proposed; Accepted только по Merge. AMEND-1/2/3 (ниже) сохранены как исторические записи Step 2-адъюдикации.
- **Фича:** `mca-13-event-contract` (Wave 0, P0-enabler). **Deploy:** `DEFERRED_TO_RELEASE`.
- **ТЗ-основание:** `plans/current_task.md` §17.1 (`:818–828`), §17.2 (`:830–836`), §17.3 (`:838–846`), §17.4 (`:848–854`), §2.16; §27.1/§27.3/§27.7 (сквозные); приёмки §19 **A27**, **A53**; R17.
- **Baseline:** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v12**; каталог `473/430/448/102/100/21`; канон 12; pytest 9513/0 + JS 47/47.
- **Связано:** REUSE `services/agentic_events.py`/`services/execution_graph_source.py`/`web/api/analytics.py`/`services/log_ring.py`/`services/llm_usage_events`; AMEND `web/api/analytics.py`; совместимо с §82–§92 (ADR-1026-10/-11/-22); мост с `mca-14` (v15); потребитель `mca-17a`; рамка `plans/docs/mca-round1027-arch-frames.md`.

## Контекст

§17 задаёт **одну** систему наблюдаемости (преамбула `:810`: «не создавать два независимых хранилища одинаковых событий»): структурированный JSON event §17.1 с полями и обязательным `start`+терминальным исходом (`success/silent/skipped/failed/cancelled/pending_external`; после crash — `interrupted`); отсутствие `except: pass`; стабильный расширяемый словарь `reason_code` §17.2; ошибки с типом/cause chain/стадией/retryability/восстановлением, агрегация без сокрытия сбоя, маскирование секретов, ретенция 14d/90d, запрет неограниченного in-memory буфера §17.3; метрики витрины §17.4 с `UNKNOWN`≠0 и фильтрами. §17.4: логи остаются в существующем viewer.

**Фактическое состояние baseline (сверено с рабочей веткой).**
- `services/agentic_events.py` — единая **fail-open** точка эмиссии `emit_agentic_event` (sync, R17-whitelist `_COMMON_FIELDS`/`EVENT_FIELDS`, закрытый enum 20 типов, `schema_version="1"`), пишет структурную строку лога + аддитивно в `RunSnapshotStore`; kill-switch `AGENTIC_EVENTS_ENABLED` (env-only, default ON). Нет обязательных `start`/`outcome`, нет durable-store/ретенции/агрегации. Вызовы: `direct_chat_service.py`, `tool_loop.py`, `image_generation.py`, `anticliche_worker.py`.
- `services/execution_graph_source.py` (`RunSnapshotStore`, TTL 900 c/maxlen 20; `record_agentic_event`; Δ DDL=0) + `web/api/analytics.py:281` (`GET /analytics/execution/latest`, RBAC `requires_global_admin`, fail-open shape) + `web/static/execution_graph.js` — существующий ExecutionGraph §82–§92.
- `services/log_ring.py` — bounded in-memory ring (`LOG_RING_MAX_ENTRIES`, default 1000) + файл/journald; `LOG_RETENTION_DAYS` (default 7) — journald. `llm_usage_events` (PG, 90d) — токены/стоимость.
- Существующие доменные аудит-таблицы (`memory_dream_log`, `nostalgia_log`, `summary_run_log`) — **не** единая телеметрия; контракт MCA-13 их не ломает.

## Решения

**D1. Схема события §17.1: закрытый контракт полей + `outcome`-enum; расширение `emit_agentic_event`.**
- **Выбрано:** контракт полей §17.1 (обязательные + опциональные) как расширение существующего whitelist `agentic_events`; терминальные `outcome = success|silent|skipped|failed|cancelled|pending_external|interrupted`; `trace_id = run_id = correlation_id` (S7/S8; второй id не вводится). Единая точка эмиссии — существующая.
- **Обоснование:** §17.1 verbatim; REUSE (вторая система запрещена преамбулой §17); `correlation_id` уже сквозной (ADR-1026-22 D4).
- **Альтернатива:** новый event-модуль/схема — отклонено (дубль точки эмиссии/RBAC/графа).

**D2. Транспорт: fail-open `emit_mca_event` над существующим logger + `RunSnapshotStore` + durable-store для терминальных.**
- **Выбрано:** синхронная fail-open обёртка: kill-switch → whitelist/контракт → лог-строка → запись **терминального** события в `mca_events` → при необходимости в `RunSnapshotStore`. Никогда не бросает, без блокирующего IO на hot-path (запись в SQLite — через общий write-механизм `mca-01`, короткая).
- **Обоснование:** §17 preamble — одна система; существующий logger уже на hot-path (профиль не ухудшается); fail-open гарантирует «0 влияния на чат».
- **Альтернатива:** async event-store/очередь/брокер — отклонено (вторая подсистема, состояние/риск).

**D3. Поля по типам (решение/retrieval/контекст/архив/сон) + запрет скрытой CoT.**
- Per-тип поля §17.1 `:826–828` добавляются в whitelist как **идентификаторные/enum/числовые** (R17-safe); рассуждения модели не запрашиваются/не сохраняются. Основные источники — SourceRef/ID, не сырьё.

**D4. Хранилище/ретенция: `mca_events` (терминальные, 90d) + структурный лог (подробные, 14d); единый store для MCA-13/17.**
- **Выбрано:** durable-таблица `mca_events` + `mca_event_aggregates` (v15, рамка §1.1.2) — **только терминальные** события; подробные start/стадии — структурный лог (bounded ring + файл/journald). Ретенция `MCA_DETAILED_LOG_RETENTION_DAYS`=14, `MCA_TERMINAL_EVENT_RETENTION_DAYS`=90 (env-only `ClassVar`, настраиваемо) + row-cap. `mca-17a` **обязан** читать тот же store (иначе — запрещённое «второе хранилище»).
- **Обоснование:** §17.3 verbatim (раздельные правила, 14/90, ручные/происхождение вне ротации); §17.4 (метрики/фильтры требуют queryable-полей); MCA-17a нужен durable lifecycle — он же источник.
- **Альтернатива:** только file-log — отклонено (нет queryable-агрегации/фильтров §17.4, дорогая агрегация); PG-таблица — отклонено (GEN-R4: PG сохраняется без расширения по умолчанию; SQLite достаточен, Δ DDL через mca-14).

**D5. Словарь `reason_code`: базовый минимум §17.2 + реестр расширения.**
- **Выбрано:** 28 кодов §17.2 — базовый закрытый набор; расширение через реестр (код → описание) без сведения разных исходов к `skip`; у `WARN`/`ERROR` обязательны влияние/fallback. Синхронизация с §24.5/§27 (MCA-15/17).
- **Альтернатива:** свободные строки — отклонено (нестабильно/непроверяемо).

**D6. Ошибки/агрегация.**
- `error_json` = тип/очищенный stack/cause chain/стадия/retryability/восстановление; пустой поиск = INFO, повреждение = ERROR. Агрегация по `fingerprint` в `mca_event_aggregates`: count/first_ts/last_ts/first_trace_id/first_error_json — сбой не «исчезает» за агрегатом.

**D7. Маскирование R17 + доступ.**
- Единый фильтр **до записи** во все каналы (лог, store, экспорт): API keys/Authorization/cookies/proxy/session/initData/секретные URL-параметры. Сырой контекст не дублируется — SourceRef/`context version` + разрешённый сокращённый снимок. Доступ к просмотру/экспорту — по существующим ролям (RBAC admin).

**D8. ExecutionGraph §82–§92: REUSE adapter, вторая аналитика запрещена.**
- **Выбрано:** расширять существующие `RunSnapshotStore`/`record_agentic_event`/`build_graph`/`GET /analytics/execution/latest`/`execution_graph.js` аддитивно; `run_id`=correlation_id. Новых endpoint/панели/второго store нет.
- **Обоснование:** §17 preamble + §17.4 «логи остаются в существующем viewer»; REUSE-дисциплина §3.
- **Альтернатива:** отдельная аналитика/endpoint — запрещено.

**D9. Метрики витрины §17.4 и `UNKNOWN`≠0.**
- Единый адаптер отдаёт active/pending tasks, queue depth/age, DB lock wait/retries, RAM/RSS, cache entries, downloads/bytes, provider latency/errors, долю деградаций, покрытие provenance, истории/эпизоды, archive progress, инициативы/молчание по причинам, результаты отправки, random source/fallback, стоимость по категориям. Неизвестное → «неизвестно» (не 0/здоровье). Фильтры по trace/chat/component/reason; переход из карточки к событиям. Источники: `mca_events` + существующие (`llm_usage_events`, live runtime).

**D10. Kill-switch.**
- `MCA_EVENT_CONTRACT_ENABLED` (default ON; OFF → события как сейчас: `emit_agentic_event` без start/outcome/durable) и `MCA_TELEMETRY_STORE_ENABLED` (default ON; OFF → только структурный лог). Существующий `AGENTIC_EVENTS_ENABLED` уважается. env-only `ClassVar` → Δ каталога=0.

**D11. Δ DDL = v15; Δ каталога = 0; границы/откат.**
- `mca_events`/`mca_event_aggregates` — через механизм `mca-14` (v15). PG — no-op. Каталог не меняется, F8 не переиздаётся. Откат: hot env-OFF; cold `git revert` → `7165ff7`.

## Санкции и вердикты

- **Δ DDL = v15** — `mca_events` + `mca_event_aggregates` (+4 индекса). Старые таблицы/ID не трогаются.
- **Δ каталога = 0**; F8 (ADR-1026-2) **NOT_APPLICABLE**.
- **Kill-switch:** `MCA_EVENT_CONTRACT_ENABLED`, `MCA_TELEMETRY_STORE_ENABLED` (env-only, default ON); `AGENTIC_EVENTS_ENABLED` уважается.
- **Risk:** **R2**; `threat-failure-analysis.md` не требуется при R2. Повышение до R3 (утечка секретов/PII в store, конкуренция записи на hot-path, неограниченный рост) — обязателен.
- **Обратный путь:** hot env-OFF; cold `git revert` → `7165ff7`; `mca_events` безвреден.
- **Release policy:** `DEFERRED_TO_RELEASE`.

## AMEND / REUSE-карта

| ADR / артефакт | Статус | Суть |
|---|---|---|
| `services/agentic_events.py` (`emit_agentic_event`, whitelist/enum) | **REUSE + расширение** | добавляются start/outcome, поля по типам, `reason_code`, error/aggregate, durable-write |
| `services/execution_graph_source.py` + `web/api/analytics.py` + `execution_graph.js` | **REUSE + аддитивно** | ExecutionGraph §82–§92; вторая аналитика/endpoint запрещены |
| `services/log_ring.py` / файл-логи | **REUSE** | подробные строки 14d; bounded ring |
| `llm_usage_events` (PG) | **REUSE** | токены/стоимость; не дублируются |
| ADR-1026-10/-11/-22 (ExecutionGraph/agentic events) | **REUSE / граница** | контракт и store не переписываются; вторая телеметрия запрещена |
| `mca-14` (v15, backup/runner) | **зависимость** | DDL через механизм |
| `mca-17a` | **Unblocks** | реестр/trace-span/инциденты — поверх того же store |
| `mca-01` | **зависимость** | запись событий через общий write-механизм |
| ADR-1026-2 (F8) | **NOT_APPLICABLE** | Δ каталога = 0 |

| Решение | Задачи |
|---|---|
| D1 (схема/outcome) | T-3767, T-3768 |
| D2 (транспорт) | T-3768, T-3775 |
| D3 (поля по типам) | T-3767 |
| D4 (store/retention) | T-3772 |
| D5 (reason_code) | T-3769 |
| D6 (ошибки/агрегация) | T-3770 |
| D7 (маскирование) | T-3771 |
| D8 (ExecutionGraph) | T-3773, T-3775 |
| D9 (метрики) | T-3773 |
| D10 (kill-switch) | T-3775 |
| D11 (Δ DDL/границы) | T-3774, T-3776 |

## AMEND (Step 2-адъюдикация @Architect, 26.09.2026)

> Статус ADR: **✅ Accepted** (мерж волны 0 MCA, `plans/ARCHITECTURE.md` §94, 26.09.2026); на момент адъюдикации был Proposed (Accepted — только по Merge, §94). AMEND не меняет DDL/каталог/риск-уровень и не ослабляет REQ.

- **AMEND-1 (граница D8/D9; SC-13/SC-14 split).** **Backend-часть** REQ-MCA13-08 закрыта в `mca-13`: единый адаптер `mca_events.metrics()` (все группы §17.4, `UNKNOWN`≠0) и `query_events` (фильтры trace/chat/component/reason, bounded LIMIT). **UI-часть** SC-13 («метрики на витрине») и SC-14 (фильтры в UI, переход из карточки, логи в существующем viewer) **санкционированно перенесена в `mca-17a`** (carry-over register — `spec.md` §1.1). Основание: D8 (новые endpoint/панели запрещены; только REUSE viewer) + план эпика (`MCA13-R4` числится за `mca-13` и `mca-17a/c`; представление «Аналитика»/финальная матрица — §27.2, `mca-17a`/`mca-17c`). T-3773 остаётся `[~]` как санкционированный перенос (не молчаливое сужение scope).
- **AMEND-2 (граница D2/D4; L-MCA13-1).** Wiring `flush_events`/`prune_events` в worker-loop/периодический job/shutdown **перенесён в `mca-17a`** (живой контур телеметрии §27.7). До подключения durable-часть — library-only (эмиссия событий и `flush` по месту). В рамках `mca-17a` требуется: `flush_events` уважает **оба** kill-switch (`MCA_EVENT_CONTRACT_ENABLED` и `MCA_TELEMETRY_STORE_ENABLED`); при подключении на hot-path — reassessment триггера конкуренции (кандидат R2→R3).
- **AMEND-3 (ратификация Risk).** **R2 сохраняется**: триггер «утечка секретов/PII в durable-store» (B-MCA13-1) закрыт маскированием до записи во все каналы и e2e-тестами (лог + durable-строка); триггеры «конкуренция записи» и «неограниченный рост» не сработали (bounded deque, retention/row-cap, отсутствие wiring на hot-path). `threat-failure-analysis.md` при R2 не требуется.

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Хранилище | file-log; PG; SQLite | **SQLite `mca_events`** | queryable-метрики/фильтры; PG не расширяем по умолчанию; DDL через mca-14 |
| Транспорт | новый store/брокер; обёртка | **fail-open обёртка** | §17 одна система; hot-path безопасен |
| Точка эмиссии | новый модуль; `emit_agentic_event` | **расширить существующую** | REUSE; нет второй аналитики |
| ExecutionGraph | новый endpoint; расширить | **расширить существующий** | §17 preamble/§17.4 |
| `reason_code` | свободные; реестр | **базовый+реестр** | стабильность/проверяемость |
| Retention | единая; 14/90 раздельно | **14/90 раздельно** | §17.3 verbatim |
| Kill-switch | каталожный; env-only | **env-only ClassVar** | Δ каталога=0 |
| Risk | R3; R2 | **R2** | аддитивно/fail-open/bounded; триггеры в spec |

## Последствия

- §17.1–§17.4 реализованы одним контрактом поверх существующей точки эмиссии; `start`/`outcome`/`interrupted`, словарь причин, ошибки/агрегация, маскирование, ретенция 14/90, метрики/фильтры.
- `mca-17a` получает единый durable-store (`mca_events`) — второй телеметрии нет.
- ExecutionGraph §82–§92 расширен аддитивно; вторая аналитика/endpoint не созданы.
- Δ DDL=v15; Δ каталога=0; risk R2; hot-откат env-OFF; cold — `git revert` → `7165ff7`; deploy `DEFERRED_TO_RELEASE`.

## Ссылки

- `plans/features/mca-13-event-contract/{spec.md, tasks.md}` (spec — T-3765; сверка — @PM T-3766).
- Рамка: `plans/docs/mca-round1027-arch-frames.md` (§1.1.2 v15, §3 kill-switch).
- Код: `services/agentic_events.py` (`:33`, `:76–115`, `:190–234`); `services/execution_graph_source.py` (`:38–126`); `web/api/analytics.py:281`; `web/static/execution_graph.js`; `services/log_ring.py`; `services/llm_usage_events`/`services/usage_events.py`.
- ТЗ: `plans/current_task.md` §17 (`:818–854`), §19 A27 (`:908`)/A53 (`:934`).
- Архитектура: merge → §94; входы §82–§92 (ADR-1026-10/-11/-22).
- Точка отката: коммит `7165ff7`.
