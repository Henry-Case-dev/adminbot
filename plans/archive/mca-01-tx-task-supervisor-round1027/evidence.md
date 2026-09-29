# `mca-01-tx-task-supervisor` — evidence (Step 4 @Builder, волна 0, сессия 1)

> **Фича-ID:** `mca-01-tx-task-supervisor`. **Сессия:** батч 1 (без DDL).
> **Дата:** 26.09.2026. **Risk:** R3. **Deploy:** `DEFERRED_TO_RELEASE`.
> **Коммиты:** НЕ делались (deploy DEFERRED; `APP_VERSION` без bump — единый релиз).
> **R17/R18:** секреты/полные пути не логируются; `plans/current_task.md`,
> `workflow_state.md`, `metrics.md`, `MEMORY.md` не изменялись.

## 1. Baseline / рабочее дерево

- **Анкер откатa (базовый HEAD):** `05bc8704c2de5e7de1d5d04ac34df763d35219aa`
  (`05bc870` — intake round1027; предшественник планового `7165ff7`).
- **Текущий HEAD:** тот же `05bc870` — **коммитов нет**, изменения только в
  рабочем дереве.
- **`APP_VERSION`:** `2.58.31` (**без bump** — единый релиз на `mca-release`).
- **SQLite DDL:** v12 → **v13** (книга `schema_migrations`, `mca-14`).
- **Δ каталога:** **0** (env-only ClassVar) — `param_catalog.py` вне diff.

## 2. Изменённые / созданные файлы

**Изменённые (implementation):**
- `services/database.py` — T-3734/3735 (владение транзакцией, known-state,
  retry), T-3736 (write-механизм для `_reassign_fact_owners`), T-3754/3755
  (migration runner + backup-обвязка), v13.
- `services/smartmodule_concurrency.py` — T-3738 (`pending` в `finally`),
  T-3739 (safe drain при смене N).
- `services/lore_notify.py` — T-3743 (закрытие соединения при провале init).
- `services/lore_cache.py` — T-3743 (inflight-ownership, generation/stale).
- `services/memory_backup.py` — T-3755 (`migration_backup`).
- `services/direct_chat_service.py` — T-3736 (`write_transaction`).
- `services/smartmodule_throttling.py` — T-3744 (cooldown eviction).
- `config/settings.py` — T-3747/3759 (env-only kill-switch `ClassVar`).
- `bot.py` — T-3743 (независимые closers в `on_shutdown`).

**Созданные (implementation):**
- `services/mca_gates.py` — единая политика kill-switch волны 0 + резолверы.
- `services/task_supervisor.py` — T-3741/T-3742 (registry/coalescing/bounded).

**Созданные (tests):**
- `tests/test_mca01_tx_task_supervisor_round1027.py` (18 тестов).
- `tests/test_mca14_schema_additive_round1027.py` (11 тестов).

**Обновлённые (project tests — версия v12→v13, механика runner):**
`test_database.py`, `test_graphrag_database.py`, `test_graph_facts_origin_v9.py`,
`test_graph_scoring_round1018.py`, `test_history_migration_v7.py`,
`test_memory_commands.py`, `test_memory_retention_round1019.py`,
`test_agentic_ai_round1020.py`, `test_migrate_direct_chat_v2_script.py`,
`test_migrate_epic60_v3_script.py`, `test_webapp_round1020_ui.py`,
`test_lore_compiler_round1020.py`, `test_multilayer_extraction_round1021.py`,
`test_smartmodule_concurrency.py` (safe-drain семантика).

## 3. Тесты (фактические числа)

| Прогон | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9542 passed, 0 failed** (baseline 9513/0 → **+29**) |
| Новые тесты mca-01 | `pytest tests/test_mca01_tx_task_supervisor_round1027.py` | **18 passed** |
| Новые тесты mca-14 | `pytest tests/test_mca14_schema_additive_round1027.py` | **11 passed** |
| JS vm-харнесс | `node tests\js\*.js` (47 файлов) | **47/47 ok** |
| JS через pytest-обёртку | `pytest tests/test_webapp_js_unit.py` | 34 passed (подмножество 47) |

### Покрытые сценарии
- **A01/SC-01:** откат A не уничтожает успешную запись B.
- **A01/SC-02:** отменённый ожидающий C не откатывает транзакцию владельца B.
- **SC-03:** провал COMMIT → известное состояние, ошибка видна.
- **SC-04:** retry только для `locked`, после освобождения lock.
- **OFF-паритет:** `MCA_TX_OWNERSHIP_ENABLED=false` → baseline-путь.
- **A02/SC-07:** отмена/таймаут ожидания слотом уменьшают `pending`.
- **SC-08:** смена concurrency только после safe drain.
- **SC-13/SC-14:** lore-notify leak, inflight-cancel, stale-cache (generation).
- **SC-13:** независимость closers в `on_shutdown`.
- **SC-11/SC-12:** TaskSupervisor coalescing/bounded c причинами.
- **SC-09:** видимый терминальный исход задачи.

## 4. Kill-switch (проверка)

| Имя | Default | OFF-паритет | Резолвер |
|---|---|---|---|
| `MCA_TX_OWNERSHIP_ENABLED` | ON | прежний `write_transaction` (rollback вне lock) | `mca_gates.tx_ownership_enabled` |
| `MCA_TASK_SUPERVISOR_ENABLED` | ON | без реестра/coalescing/bounded | `mca_gates.task_supervisor_enabled` |
| `MCA_SCHEMA_MIGRATIONS_ENABLED` | ON | legacy `_migrate_*`-путь, без книги | `mca_gates.schema_migrations_enabled` |

- env-only `ClassVar`, резолв per-call, никогда не бросает (тест
  `test_kill_switch_defaults_on`, `test_kill_switch_off_legacy_path`).
- Существующие `DB_LOCK_RESILIENCE_ENABLED`/`AGENTIC_EVENTS_ENABLED` не
  дублируются; OFF ownership сохраняет F0.5-retry (уважение контракта).

## 5. Остаётся / блокеры

- **T-3740 (v14 `task_jobs`)** — НЕ начата (следующая сессия; требует T-3754 ✅).
- **T-3745 (A02/A51/нагрузка)** — частично (A02 покрыт); A51/нагрузочный цикл —
  после T-3740.
- **T-3746 (события MCA-13/стадии MCA-17)** — R17-логи ✅; события задач ✅
  (через `mca_events`); регистрация стадий/виджета MCA-17a — следующая фича.
- **Полный охват write-точек** — **закрыт в rework-сессии** (B-MCA01-1):
  единый single-writer (`serialized()`/`@_serialized_write`/`write_transaction`),
  аудит-инвентарь и guard-тесты — см. `evidence-rework.md`.
