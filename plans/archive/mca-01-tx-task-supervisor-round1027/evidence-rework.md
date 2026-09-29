# `mca-01-tx-task-supervisor` — evidence, rework по review (B-MCA01-1…4, L-MCA01-1…4)

> **Фича-ID:** `mca-01-tx-task-supervisor`. **Дата:** 26.09.2026. **Risk:** R3.
> **Deploy:** `DEFERRED_TO_RELEASE` (§20; коммитов НЕТ; `APP_VERSION` 2.58.31 без
> bump; Δ каталога = 0; Δ DDL без изменений — v13/v14/v15 уже в реестре `mca-14`).
> **Вход:** `review.md` (Needs Fixes), `plans/features/mca-wave0-rework-instructions.md`.
> **Binding ревью** (Reviewed-Commit `05bc870`, wt `cc7e3c0a`) после rework —
> **stale**; повторный re-review обязателен (@Reviewer пересчитает binding).
> R17/R18: секреты/полные пути не логируются; `plans/current_task.md`,
> `workflow_state.md`, `metrics.md`, `MEMORY.md` не изменялись.

## 1. B-MCA01-1 (High) — «единый write-механизм»: охват + аудит

**Механизм (ADR-1027-3 D3):** единый `self._lock` обслуживает три формы записи
с reentrancy по задаче (`DatabaseService._write_owner`):

- `write_transaction(op)` — пакетные транзакции (BEGIN/тело/COMMIT/ROLLBACK под lock);
- `db.serialized()` — публичный контекст для модулей с историческими
  `execute()+commit()` блоками;
- `@_serialized_write` — обёртка доменных write-методов `DatabaseService`.

**Инвентарь write-точек (факт на rework-сессию):**

| Файл | `.commit()` | Статус |
|---|---|---|
| `services/database.py` | 102 | 49 в `@_serialized_write`-методах; 53 — санкционированная DDL/initialize/`write_transaction`-машинерия |
| `services/summary_memory.py` | 13 | 12 внутри `async with self.db.serialized()` (embedding cache/backfill/сводки) + 1 fallback-двойник (`mca01-write-fallback`) |
| `services/smart_cache.py` | 3 | **отдельное соединение** (F17), не общая connection `DatabaseService` |
| `services/dossier_rebuild_jobs.py` | 1 | внутри `async with db.serialized()` |
| `services/memory_maintenance.py` | 1 | внутри `async with self.db.serialized()` |
| `services/persistent_throttling.py` | 1 | fallback-двойник без `write_transaction` (`mca01-write-fallback`) |

`database.py`, 53 санкционированные точки: `initialize()` (4), `_run_migrations`
(2), `_ensure_migration_book` (1), `_commit_locked` (1),
`_write_transaction_baseline` (2), `_migrate_*` (43). Все — до старта сервинга
(нет конкурентных писателей) либо машинерия `write_transaction`; зафиксировано
комментарием в `_run_migrations` (L-MCA14-3).

`chat_lore.py`/`chat_lore_store.py`, `memory_rebuild.py`,
`direct_chat_service.py` — прямых `commit()` не содержат (записи через
`write_transaction`/общий механизм).

**Санкционированные исключения:** `smart_cache.py` (собственное соединение к
тому же файлу БД, отдельный lock/retry — не общая connection) и
fallback-двойники без `write_transaction` (явный маркер `mca01-write-fallback`;
тестовые двойники). Внешние БД (`pg_db.py`) — вне SQLite write-механизма.

**Guard-тесты (охват не деградирует):**

- `test_write_points_go_through_single_writer` — AST-аудит всех `services/*.py`:
  для `database.py` прямой `commit()` допустим только в
  `@_serialized_write`-методе/санкционированном имени/`serialized()`-контексте;
  для остальных — только allowlist + `serialized()`/маркер/отдельное
  соединение. Любое изменение числа точек или новый необоснованный `commit`
  (напр., новый файл) — падение теста.
- `test_no_nested_raw_lock_in_serialized_methods` — запрет повторного захвата
  raw `self._lock` внутри `@_serialized_write`-метода (класс self-дедлока).
  Тест **поймал реальный дефект**: `slavic_photo_count_tick` одновременно имел
  декоратор и внутренний `async with self._lock` → вечный deadlock; исправлено.

## 2. B-MCA01-2 (High) — deadlock важной очереди

- **Фикс:** `TaskSupervisor` переведён на `asyncio.Condition`; ожидание слота —
  `await self._cond.wait_for(lambda: self._running < self._max_concurrent)`
  (блокировка освобождается на время ожидания); `_release_locked` делает
  `notify_all` вместо `Event.set` (проснувшиеся пере-проверяют условие и
  занимают слот). Важная задача при переполнении больше не держит guard и
  дожидается слота; молчаливой потери нет.
- **Тест:** `test_important_queue_no_deadlock_on_overflow` (`max_concurrent=1`,
  две `kind="important"`, таймаут 2с, `running_count()==0`, оба result_ref).

## 3. B-MCA01-3 (Medium) — fencing реально применяется

- **Фикс:** `TaskJobStore.finish`/`heartbeat`/`save_checkpoint` при заданном
  `fencing_token` обусловливают UPDATE (`WHERE job_id = ? AND
  fencing_token = ?`); `TaskSupervisor.run(job_store=…)` запоминает выданный
  при `mark_running` токен и передаёт его во все терминальные записи. После
  takeover (`recover_stale` бампает токен) запись старого владельца — no-op.
- **Тест:** `test_stale_fencing_owner_write_rejected` — old token 0 после
  recovery: `finish`/`heartbeat`/`save_checkpoint` → `False`, поле не
  перезаписано; актуальный токен пишет успешно.

## 4. B-MCA01-4 (Medium) — recovery-rollback строго под lock

- **Фикс:** ветка `_connection_degraded` в `_write_transaction_owned`
  выполняется внутри `async with self._single_writer()` (тот же `self._lock`),
  а не до его входа; провал recovery → видимая ошибка
  `database_connection_unrecoverable` + флаг degraded (без тихого
  «неизвестного состояния»).
- **Тест:** `test_degraded_recovery_rollback_under_lock` — при
  `_connection_degraded=True` два параллельных `write_transaction` успешны,
  спай фиксирует `_write_owner is current_task` для фазы `recover-degraded`.

## 5. Lows

| Low | Статус | Доказательство |
|---|---|---|
| L-MCA01-1 `chat_id=None` в `_note_lock_exhausted` (baseline) | исправлено: `chat_id` передаётся | `services/database.py::_write_transaction_baseline`; `test_off_parity_baseline_semantics` |
| L-MCA01-2 shutdown не переживает `CancelledError` | исправлено: `bot.on_shutdown._safe` ловит `BaseException` | `test_shutdown_closers_independent` |
| L-MCA01-3 лишний `attempt++` при коалесинге | исправлено: in-process singleflight проверяется ДО durable-enqueue | `test_task_supervisor_coalescing_singleflight` |
| L-MCA01-4 `leaked aiosqlite connection(s)` | исправлено: тесты закрывают соединение при провале init (`finally: d.close()`); полный pytest без warning | `test_migration_fails_if_backup_fails`; финальный прогон — 0 leaked |
| Nit @PM: A28 в шапке приёмок | зарегистрирован (не противоречит), правок не требует | `mca-wave0-reconciliation.md` §8 |

## 6. Числа (rework)

| Прогон | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9588 passed, 0 failed** (1 warning — FastAPI deprecation; leaked/timeout — нет) |
| Новые тесты mca-01 | `pytest tests/test_mca01_tx_task_supervisor_round1027.py` | **33 passed** (review: 27) |
| Регресс cross-round guard | `pytest tests/test_tool_coordinator_round1026.py` | 56 passed (sanction-нота для `summary_memory.py`, см. §7) |
| JS vm-харнесс | `node` по всем `tests/js/*.js` (47 файлов) | **47/47 ok** |
| Git hygiene | `git diff --check` | чисто (exit 0) |

Старт rework (по инструкции/ревью): pytest 9574/0, JS 47/47.

## 7. Прямые правки в чужих артефактах (осознанные, минимальные)

- `tests/test_tool_coordinator_round1026.py::test_forbidden_paths_out_of_diff`:
  round-1026 scope-guard сравнивает рабочее дерево с тегом `pre-round1026-a1` и
  запрещал `services/summary_*`. MCA-01 (ADR-1027-3 D3) санкционированно
  меняет `services/summary_memory.py` (embedding cache/backfill/сводки) — guard
  уточнён: `summary_changed <= {"services/summary_memory.py"}` + NOTE round1027;
  остальные `services/summary_*` по-прежнему запрещены. Иначе полный pytest не
  может быть зелёным после законного изменения.
- `services/database.py::slavic_photo_count_tick`: убран внутренний
  `async with self._lock` (регресс partial-rework: декоратор + raw lock =
  deadlock) — фикс в рамках B-MCA01-1/H25.

## 8. Остаётся / границы

- Полная регистрация стадий/виджета MCA-17a — следующая фича (законная граница
  spec §1; T-3746 → `[~]`).
- Нагрузочный RSS-цикл — релизная проверка `mca-release` (T-3745).
- Фоновый `flush_events` MCA-13 в worker-loop — за `mca-13`/`mca-17a`.
