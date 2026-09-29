# `mca-01-tx-task-supervisor` — evidence, сессия 2 (T-3740, T-3745, T-3746)

> Продолжение `evidence.md` сессии 1. **Дата:** 26.09.2026. **Risk:** R3.
> **Коммиты:** нет. **`APP_VERSION`:** `2.58.31` (без bump). **Δ каталога:** 0.
> **Δ DDL:** +`task_jobs` (v14) — строкой реестра `mca-14`.

## 1. Реализовано в сессии 2

- **T-3740 (v14):** durable-очередь `task_jobs` через реестр `mca-14`
  (`_migrate_task_jobs_v14`, версия 14, порядок по возрастанию) + 2 индекса
  (`idx_task_jobs_status_created`, unique partial `idx_task_jobs_coalesce_active`).
  `services/task_supervisor.py::TaskJobStore` — enqueue/coalesce-dedup,
  `mark_running` (attempt/fencing), `heartbeat`, `finish` (terminal),
  `recover_stale` (→`interrupted`+fencing), `prune`, `save_checkpoint`/
  `get_checkpoint`. Записи — через write-механизм `mca-01`.
  `TaskSupervisor.run(job_store=...)` ведёт durable lifecycle queued→running→terminal.
- **T-3741/T-3742 durable-часть:** unique partial-индекс по активному
  `coalesce_key`; bounded-очередь с причинами `queue_coalesced`/`queue_full`.
- **T-3745 (A51):** takeover-сценарий: `running` без heartbeat → `interrupted`,
  `fencing_token++`, повторный enqueue без дубля.
- **T-3746:** события задач (`TASK_START`/`TASK_TERMINAL`/`TASK_FAILED`) через
  контракт `mca-13` (`services/mca_events.py`); R17-safe логи.

## 2. Файлы

Изменены: `services/task_supervisor.py`, `services/database.py`,
`services/mca_gates.py`, `config/settings.py`.
Созданы в сессии 2: `tests/test_mca01_tx_task_supervisor_round1027.py`
(дополнен: +8 тестов).

## 3. Тесты (фактические)

| Прогон | Результат |
|---|---|
| Полный pytest | **9574 passed / 0 failed** (сессия 1: 9542) |
| `tests/test_mca01_...round1027.py` | **27 passed** (+8 к сессии 1) |
| JS-харнесс (47 файлов) | **47/47 ok** |

Покрыто: `test_v14_task_jobs_schema_and_version`,
`test_task_jobs_enqueue_and_active`, `test_task_jobs_coalesce_dedup`,
`test_task_jobs_recover_stale_fencing`, `test_task_jobs_finish_and_prune`,
`test_task_jobs_overdue`, `test_supervisor_durable_lifecycle`,
`test_supervisor_emits_events`, `test_archive_job_checkpoint_resume`,
`test_a51_takeover_no_duplicate`.

## 4. Kill-switch

`MCA_TASK_SUPERVISOR_ENABLED` (ON; OFF → без durable/реестра/коалесинга),
`MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED` (ON; OFF → события/
durable как baseline). Проверено `test_emit_off_parity_*`, `test_task_supervisor_off_passthrough`.

## 5. Остаётся

- **T-3748/T-3749** — ревью/merge (@Reviewer/@Architect).
- Полный нагрузочный RSS-цикл — релизная проверка (`mca-release`).
- Регистрация стадий/виджета MCA-17a — следующая фича.
