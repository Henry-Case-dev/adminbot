# `mca-01-tx-task-supervisor` — threat / failure analysis (R3, батч 1)

> **Risk:** R3 (меняет общий write-path SQLite и жизненный цикл задач).
> **Объём:** реализованное в сессии 1 (T-3734…T-3739, T-3741…T-3744, T-3746
> частично, T-3747). Остальное дополнится в закрывающих сессиях.

## Блок H — модель угроз и отказов

| # | Угроза / отказ | Механизм защиты | Тест / доказательство |
|---|---|---|---|
| H1 | Отменённый ожидающий lock откатывает чужую транзакцию | `async with self._lock` ВНЕ `try`; провал acquisition не входит в ветку rollback | `test_a01_cancelled_waiter_does_not_rollback_owner` |
| H2 | Rollback выполняется после освобождения lock (гонка) | rollback ВНУТРИ lock (`_safe_rollback_locked`) | `test_a01_rollback_does_not_destroy_other_write` |
| H3 | Скрытый commit/rollback чужой операции | коммит только владельцем внутри lock | A01-тесты |
| H4 | После ошибки commit connection в неизвестном состоянии | `_commit_locked` → rollback; флаг `_connection_degraded` + видимая ошибка | `test_commit_error_returns_known_state` |
| H5 | Маскирование не-`locked` ошибок retry'ем | retry только для `_is_locked` | `test_lock_retry_only_locked` |
| H6 | `pending` утекает при отмене ожидания слотом | декремент в `finally` (вкл. `CancelledError`) | `test_a02_pending_released_on_cancel` |
| H7 | Смена concurrency → два семафора сверх ёмкости | пересоздание только после safe drain | `test_n_change_replaces_slot` |
| H8 | Утечка соединения lore-notifier при провале init | `conn.close()` в `except` | `test_lore_notify_closes_conn_on_init_failure` |
| H9 | Ожидающий рвёт чужой inflight (второй SELECT) | ожидающий не снимает inflight владельца | `test_lore_cache_waiter_does_not_break_coalescing` |
| H10 | Возврат устаревшего кеша после invalidation | монотонная `generation` | `test_lore_cache_generation_blocks_stale_write` |
| H11 | Ошибка одного closer блокирует остальные | `_safe()` на каждый ресурс | `test_shutdown_closers_independent` |
| H12 | Молчаливая потеря/дубль повторяющегося задания | singleflight `coalesce_key`; bounded с причиной | `test_task_supervisor_coalescing_singleflight`, `..._bounded_secondary_rejected` |
| H13 | Монотонный рост cooldown-map | lazy eviction при пороге | `test_cooldown_tracker_eviction` |
| H14 | OFF-путь незаметно меняет поведение | OFF → точный baseline-путь | `test_off_parity_baseline_semantics` |

## Остаточные риски (открыты)

- **Durable `task_jobs` (v14)** реализована в сессии 2 (T-3740) — A51 закрыт
  по fencing/checkpoint (rework: H22).
- Полный аудит direct-`commit` **закрыт в rework** (H24/H25; реестр —
  `evidence-rework.md` §1).
- События MCA-13 для терминальных исходов задач подключены (T-3746).
- Нагрузочный цикл/RSS (T-3745) не прогонялся — монотонный рост не проверен
  явно (cooldown/lore_cache eviction — локально).


## Сессия 2 — дополнительные угрозы/защиты (T-3740, T-3745, T-3746)

| # | Угроза / отказ | Механизм защиты | Тест |
|---|---|---|---|
| H15 | Дубль задачи при повторном/параллельном старте | unique partial `idx_task_jobs_coalesce_active` (активные `coalesce_key`) | `test_task_jobs_coalesce_dedup`, `test_a51_takeover_no_duplicate` |
| H16 | Задача «зависла» после гибели worker (вечный `running`) | `recover_stale` → `interrupted` + `fencing_token++` | `test_task_jobs_recover_stale_fencing` |
| H17 | Старый владелец пишет после takeover | fencing_token бампается при recovery (A51) | `test_a51_takeover_no_duplicate` |
| H18 | Неограниченный рост durable-очереди на диске | `prune` (терминальные старше ретенции) | `test_task_jobs_finish_and_prune` |
| H19 | Потеря терминального исхода задачи | `finish` пишет status/reason/result/error; событие MCA-13 | `test_supervisor_durable_lifecycle`, `test_supervisor_emits_events` |
| H20 | Долгая транзакция на весь диапазон archive-job | checkpoint короткой tx (`save_checkpoint`) + resume | `test_archive_job_checkpoint_resume` |

### Остаточные риски (сессия 2, открыты)
- Полная регистрация стадий/виджета MCA-17a — следующая фича (T-3746 частично).
- Нагрузочный RSS-цикл — релизная проверка.
- `mca_13`-события задач эмитятся, но фоновый `flush_events` требует вызова
  планировщика (интеграция flush в worker-loop — следующая фича).


## Rework по review (B-MCA01-1…4, L-MCA01-1…4)

| # | Угроза / отказ | Механизм защиты | Тест / доказательство |
|---|---|---|---|
| H21 | Взаимоблокировка важной очереди (ожидание слота под мьютексом, нужным для освобождения слота) | `asyncio.Condition.wait_for` освобождает блокировку на время ожидания; `_release_locked` → `notify_all` + пере-проверка условия завершающейся задачей | `test_important_queue_no_deadlock_on_overflow` |
| H17a | Устаревший владелец перезаписывает результат после takeover (fencing номинальный) | `finish`/`heartbeat`/`save_checkpoint` обусловлены `fencing_token` (`WHERE … AND fencing_token = ?`); `run(job_store=…)` передаёт выданный токен во все терминальные записи; stale-запись — no-op | `test_stale_fencing_owner_write_rejected` |
| H23 | Recovery-rollback деградировавшего соединения вне lock (откат чужой in-flight tx) | recovery выполняется строго под `_single_writer`/`self._lock`; провал → видимая ошибка + флаг degraded | `test_degraded_recovery_rollback_under_lock` |
| H24 | Интерливинг прямых `execute+commit` с чужой открытой транзакцией (§5.1) | единый single-writer: `DatabaseService.serialized()` + `@_serialized_write` + `write_transaction` на одном lock; аудит-реестр | `test_write_points_go_through_single_writer` |
| H25 | Self-дедлок: `@_serialized_write`-метод повторно берёт raw `self._lock` | статический guard по AST; реальный дефект `slavic_photo_count_tick` исправлен | `test_no_nested_raw_lock_in_serialized_methods`, `test_summary_handlers.py` (integration) |

**Санкционированные исключения single-writer (R17-safe, без секретов):**
`smart_cache.py` — собственное соединение (F17), не общая connection;
`database.py` — 53 точки в `initialize()`/`_migrate_*`/`_run_migrations`
(до старта сервинга) и машинерии `write_transaction`; тестовые
fallback-двойники `persistent_throttling`/`summary_memory` — с маркером
`mca01-write-fallback`. Реестр — `evidence-rework.md` §1.
