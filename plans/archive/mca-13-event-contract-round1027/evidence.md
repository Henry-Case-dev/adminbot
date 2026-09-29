# `mca-13-event-contract` — evidence (Step 4 @Builder, волна 0)

> **Фича-ID:** `mca-13-event-contract`. **Risk:** R2. **Deploy:** `DEFERRED_TO_RELEASE`.
> **Дата:** 26.09.2026. **Коммиты:** нет. **`APP_VERSION`:** без bump. **Δ каталога:** 0.
> **Δ DDL:** v15 (`mca_events` + `mca_event_aggregates` + 4 индекса) строкой реестра `mca-14`.

## 1. Реализовано

- **T-3767:** `services/mca_events.py::build_event` — контракт §17.1 (обязательные
  поля, R17-safe через общий `agentic_events._safe_value`, JSON-поля
  `entity_ids`/`usage_json`/`error_json`/`source_ref_json`); поля по типам;
  скрытая CoT не запрашивается.
- **T-3768:** `emit_mca_event` — start + терминальные
  `success|silent|skipped|failed|cancelled|pending_external|interrupted`;
  `TaskSupervisor.recover_stale` → `interrupted`; нет `except: pass` (fail-open
  `return`, не глотание в чужом коде).
- **T-3769:** `REASON_CODES` — 27 базовых кодов §17.2 + расширения; неизвестный
  код отбрасывается, не подменяется `skip`.
- **T-3770:** `build_error_metadata` (тип/очищенный stack/cause/стадия/
  retryability/восстановление) + `_upsert_aggregate` (fingerprint/count/
  first-last/first_trace).
- **T-3771:** маскирование через `log_ring.sanitize` до записи; SourceRef вместо
  сырого контекста.
- **T-3772:** v15 `mca_events`+`mca_event_aggregates` (4 индекса);
  `prune_events` (90d; `memory_manual`/`memory_provenance` не удаляются);
  bounded `_pending` deque (256) + `dropped_total`; env
  `MCA_DETAILED_LOG_RETENTION_DAYS`=14 / `MCA_TERMINAL_EVENT_RETENTION_DAYS`=90.
- **T-3773:** `metrics` — единый адаптер §17.4 (все группы, UNKNOWN≠0);
  `query_events` (trace/chat/component/reason, bounded LIMIT);
  ExecutionGraph §82–§92 REUSE (вторая аналитика не создана). UI-часть
  SC-13/SC-14 — перенос в `mca-17a` (см. §6, нужна санкция @Architect).
- **T-3775 (частично):** поля `trace_id`/`operation_id`/`parent_operation_id` —
  хуки для `mca-17a`.

## 2. Файлы

Созданы: `services/mca_events.py`, `tests/test_mca13_event_contract_round1027.py`.
Изменены: `services/database.py` (v15), `services/mca_gates.py`,
`config/settings.py`, `services/task_supervisor.py` (эмиссия событий задач).

## 3. Тесты

| Прогон | Результат |
|---|---|
| Полный pytest | **9574 passed / 0 failed** |
| `tests/test_mca13_event_contract_round1027.py` | **18 passed** |
| JS-харнесс | **47/47 ok** |

## 4. Kill-switch

`MCA_EVENT_CONTRACT_ENABLED`, `MCA_TELEMETRY_STORE_ENABLED` (env-only, default
ON, per-call, не бросают); `AGENTIC_EVENTS_ENABLED` уважается. OFF-паритет:
`test_emit_off_parity_contract`, `test_flush_off_store_parity`.

## 5. Остаётся

- **T-3775** — полная интеграция MCA-17a (send/span/heartbeat) — следующая фича.
- **T-3776** — ревью/merge.
- Витринная UI-часть SC-13/SC-14 (метрики на экране, переходы из карточек,
  логи в существующем viewer) — перенос в `mca-17a` (см. §6).

## 6. Rework по review (B-MCA13-1, B-MCA13-2, L-MCA13-1…4)

> Вход: `review.md` (Needs Fixes), `plans/features/mca-wave0-rework-instructions.md`.
> Binding ревью (Reviewed-Commit `05bc870`, wt `cc7e3c0a`) после rework — stale;
> re-review обязателен. Risk: **R2 сохраняется** — триггер «утечка секретов в
> durable-store» закрыт маскированием (см. B-MCA13-1); threat-артефакт при R2
> не требуется (ADR-1027-2 санкции).

### B-MCA13-1 (High) — R17-маскирование полей события — исправлено

- `build_event`: строковые (`_CODE_FIELDS`/`_ID_FIELDS`/`_SHORT_FIELDS`) и
  JSON-поля (`_JSON_FIELDS`) проходят `log_ring.sanitize()` до буфера/лога;
  `_emit_log` дополнительно санитизирует строку (defense-in-depth), уровень
  события отражается в логе (L-MCA13-2).
- Реальные e2e-негативные тесты (замена фиктивного): 
  `test_masking_of_secrets_in_event_and_log` (caplog: токен в `component` и
  `source_ref_json` → `***`, сырого значения нет),
  `test_masking_persisted_durable_mca_events` (grep по строке `mca_events`
  после `flush_events` — секрета нет ни в строковом, ни в JSON-поле).

### B-MCA13-2 (Medium) — §17.4 метрики/фильтры — реализовано ядро, UI передан

- `mca_events.metrics(db, *, runtime=None)`: единый адаптер §17.4, все группы
  (`tasks` active/pending/queue depth+age/archive progress; `lock`
  exhausted/retry — in-process счётчики; `providers` latency/errors из
  терминальных событий; `degradations` доля/dropped; `initiatives`/silence —
  распределение `reason_code`; `delivery`; `random fallback`; `cost` по
  категориям из `usage_json`; `cache`/`provenance`/`memory`/`downloads`/
  `runtime` — из runtime-контура, который поставляет MCA-17a).
  Поле без продюсера → `None` + `available=False` + имя в `unknown` (UNKNOWN ≠
  0/здоровье). Тесты: `test_metrics_covers_17_4_groups_with_unknown`,
  `test_metrics_computes_real_groups_from_store`,
  `test_metrics_unknown_not_zero_when_unavailable`.
- `query_events` — фильтры trace/chat/component/reason + bounded LIMIT
  (`test_query_events_reason_filter_and_limit`).
- **Явный перенос (B-MCA13-2-остаток):** UI-презентация SC-13 («метрики на
  витрине») и SC-14 (переходы из карточек, логи в существующем viewer) —
  в `mca-17a`: контур наблюдаемости поверх того же `mca_events`;
  ADR-1027-2 D8 запрещает новые endpoint/панели (только REUSE существующего
  viewer). Требуется **санкция @Architect** на перенос SC-13/SC-14 UI-части
  (спека не правилась — зона @Architect). T-3773 → `[~]`.

### Lows

- **L-MCA13-1** — `flush_events` больше не пишет при `telemetry_store_enabled`
  OFF (терминальные не буферизуются); wiring в периодический job/shutdown —
  регистрируется как перенос в `mca-17a` (сейчас durable-часть —
  library-only, вызов по месту; событий в горячем пути нет).
- **L-MCA13-2** — исправлено: `_emit_log` пишет WARN/ERROR своим уровнем
  (`test_emit_log_reflects_level`).
- **L-MCA13-3** — исправлено: `test_per_type_fields_decision_context_archive_dream`
  покрывает решение/контекст/архив/сон.
- **L-MCA13-4** — закрыто: `test_event_kill_switches_env_default_on` проверяет
  env-чтение `Settings.MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED`.
- **Ниты @PM (зона @Architect, не правились):** опечатка `retención` в
  `spec.md` SC-16; ссылка «Блок C» в `tasks.md`.

### Числа (rework)

| Прогон | Результат |
|---|---|
| `tests/test_mca13_event_contract_round1027.py` | **25 passed** |
| Полный pytest | см. `../mca-wave0-rework-evidence.md` (финальные числа волны 0) |
| JS-харнесс | 47/47 ok (волна 0) |
