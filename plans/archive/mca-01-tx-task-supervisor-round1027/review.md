# `mca-01-tx-task-supervisor` — ревью (повторный единый gate волны 0 MCA, round 10.27)

> **Feature-ID:** `mca-01-tx-task-supervisor`. **Risk-Level:** **R3** (общий write-path SQLite + жизненный цикл фоновых задач).
> **Status: Approved.**
> **Дата / агент:** 26.09.2026, @Reviewer (обе линзы в одном gate; Scanner отсутствует).
> **Deploy:** `DEFERRED_TO_RELEASE` (§20; коммитов НЕТ; `APP_VERSION` 2.58.31 без bump).
> **Цикл:** итер.1 — `Needs Fixes` (B-MCA01-1/2 High, B-MCA01-3/4 Medium) → rework @Builder → **итер.2 — Approved** (binding новый; один новый Low — L-MCA01-5, не блокирует).

## Binding (точное ревьюируемое состояние)

- **Git base:** HEAD `05bc8704c2de5e7de1d5d04ac34df763d35219aa`. Все изменения — **не закоммичены**; ревью рабочего дерева.
- **Reviewed-Commit:** `05bc8704c2de5e7de1d5d04ac34df763d35219aa`.
- **Diff-SHA256 (`git diff --binary HEAD`):** `fbf2eea45be890fb32925b3de67d9039a92430971efb4ae4618c54ae64058299`.
- **Working-Tree-Hash (59 записей; исключены 7 артефактов ревью/workflow: 4 `review.md`, `full_audit_results.md`, `global_map.md`, `workflow_state.md`):** `9cd581e4549e2fc0fd53599ade14b507b42f87e8a864899c3486e8d78b144a97`.
- **Product-Code-Hash (доп., 37 записей):** `9d9254187b50c71b6067aa1ad52c4a3cdaad7c1579ee7ed780752a23fab64827`.
- **Spec-Hash:** `92b1a2b71cf971782a0831806f9cf0873b2e897f591ffdeb37ea0ff95605a79c`.
- **ADR-1027-3-Hash:** `d67378ffafa98959beb2f78ba15706fc61ec82ddbfd35de279712dfdb5d37d51`.
- **tasks-Hash:** `4bd716853630144988618638eacbdb5ddf8cf7c3332484622555166bde53e71b` (T-3736/T-3746 приведены к правде).

> Хэш рабочего дерева зафиксирован **до** записи этого `review.md`; любая правка кода/спеки после фиксации делает вердикт stale.

## 1. Объём проверки

- **Requirements-линза:** REQ-MCA01-01…10 и SC-01…SC-17 (spec §2/§6), A01/A02/A51, трассируемость REQ→SC→tasks, Карта ADR-1027-3 D1–D10.
- **Focused change-audit:** `services/database.py` (`_single_writer`/`serialized`/`_serialized_write`/`_require_write_owner`, `write_transaction` split, `_write_transaction_owned/_baseline`, `_commit_locked`, `_safe_rollback_locked`, `_connection_degraded`, runner), `services/task_supervisor.py` (`TaskSupervisor`, `TaskJobStore`), `services/mca_gates.py`, `config/settings.py`, `services/smartmodule_concurrency.py`, `services/lore_cache.py`, `services/lore_notify.py`, `services/memory_backup.py`, `services/direct_chat_service.py`, `services/smartmodule_throttling.py`, `bot.py`.
- **Инцидент `feature_gates.py`:** diff/status — пусто (== HEAD, F-10 не сломан); новый модуль вынесен в `mca_gates.py`. ✅

## 2. Независимый прогон (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9588 passed, 0 failed** (1 FastAPI-deprecation warning; **leaked aiosqlite — нет**) |
| mca-01 suite | `pytest tests/test_mca01_tx_task_supervisor_round1027.py` | **33 passed** |
| JS vm-харнесс | `node` по всем 47 `tests/js/*.js` | **47/47 ok** |
| Git hygiene | `git diff --check` | чисто (exit 0) |

Совпадает с evidence (`9588/0`, `47/47`, mca-01 `33`).

## 3. Проверка закрытия блокеров (итер.1)

### B-MCA01-1 [High] — write-механизм/аудит → **закрыт**
- **Механизм:** единый `self._lock` через `_single_writer()` (reentrancy по задаче `_write_owner`), три формы: `write_transaction(op)`, `db.serialized()`, `@_serialized_write` (`services/database.py:363-380`, `:719-753`).
- **Инвентарь (независимый AST-подсчёт):** `database.py` — **49** `commit()` в `@_serialized_write`-методах + **53** в санкционированной DDL/`initialize`/`write_transaction`-машинерии = 102; модули: `summary_memory` 12×`serialized()` (+1 fallback-двойник с маркером), `dossier_rebuild_jobs` 1, `memory_maintenance` 1, `persistent_throttling` 1 (маркер), `smart_cache` 3 (отдельное соединение, F17). `chat_lore`/`memory_rebuild`/`direct_chat_service` переведены на `write_transaction` (прямых `commit` больше нет).
- **Guard-тесты:** `test_write_points_go_through_single_writer` (AST-реестр+allowlist: `found==allow`, `unguarded==[]`) и `test_no_nested_raw_lock_in_serialized_methods` (запрет `self._lock` внутри `@_serialized_write`; тест поймал и закрыл реальный self-дедлок `slavic_photo_count_tick`). **Оба зелёные.**
- **Независимая проверка SC-06:** все блоки `serialized()` в `summary_memory` оборачивают только DB-операции; `llm.embed`/`generate` — до/вне `serialized()`. ✅
- **Итог:** «все записи в общую connection» закрыты на уровне фактических write-точек; санкционированные исключения (отдельное соединение `smart_cache`, тестовые fallback-двойники) обоснованы. **Закрыто.**

### B-MCA01-2 [High] — deadlock важной очереди → **закрыт**
- **Фикс:** `TaskSupervisor` переведён на `asyncio.Condition`; ожидание слота — `await self._cond.wait_for(lambda: self._running < self._max_concurrent)` (блокировка освобождается на время ожидания); `_release_locked` — `notify_all` вместо `Event.set` (`services/task_supervisor.py:163-167`, `:242-266`, `:330-339`).
- **Регресс-тест:** `test_important_queue_no_deadlock_on_overflow` (`max_concurrent=1`, две `important`, `running_count()==1` во время ожидания, завершение в пределах 2с). **Воспроизведённый итер.1 deadlock не повторяется. Закрыто.**

### B-MCA01-3 [Medium] — fencing → **закрыт на требуемом уровне (store + result-path)**
- **Фикс:** `TaskJobStore.finish`/`heartbeat`/`save_checkpoint` при заданном `fencing_token` обусловливают UPDATE (`WHERE job_id=? AND fencing_token=?`); `run()` запоминает выданный токен (`job_store.get` после `mark_running`) и передаёт его в **запись результата** (success→`result_ref`) — `services/task_supervisor.py:434-520`, `:590-618`, `:286-289`.
- **Тест:** `test_stale_fencing_owner_write_rejected` — после takeover (token≥1) `finish`/`heartbeat`/`save_checkpoint` старым token=0 → `False`, поле не перезаписано; актуальный токен пишет успешно. **Зелёный.**
- **Остаток (новый, не блокирует):** см. L-MCA01-5 ниже.

### B-MCA01-4 [Medium] — recovery-rollback под lock → **закрыт**
- **Фикс:** ветка `_connection_degraded` в `_write_transaction_owned` выполняется внутри `async with self._single_writer()`; провал → видимая ошибка `database_connection_unrecoverable` + флаг degraded (`services/database.py:885-898`).
- **Тест:** `test_degraded_recovery_rollback_under_lock` — спай фиксирует `_write_owner is current_task` для фазы `recover-degraded`; две параллельные транзакции успешны. **Закрыто.**

## 4. Проверка Lows (итер.1)

- **L-MCA01-1:** исправлено — `chat_id` передаётся в `_note_lock_exhausted` (`chat_id=None` baseline-регресс устранён). ✅
- **L-MCA01-2:** исправлено — `bot.on_shutdown._safe` ловит `BaseException`; `test_shutdown_closers_independent`. ✅
- **L-MCA01-3:** исправлено — in-process singleflight проверяется ДО durable-enqueue (`run()` `:211-217`); коалесцированный вызов не трогает durable; `test_task_supervisor_coalescing_singleflight`. ✅
- **L-MCA01-4:** исправлено — полный pytest без `leaked aiosqlite` (тесты закрывают соединение при провале init). ✅
- **Nit @PM (A28 в шапке приёмок):** зарегистрирован, не противоречит. ✅

## 5. Focused audit coverage / counterexamples checked

- **OFF-паритет:** `MCA_TX_OWNERSHIP_ENABLED=false` → baseline (rollback вне lock, retry F0.5 сохранён) — `test_off_parity_baseline_semantics`. ✅
- **Известное состояние после COMMIT-ошибки:** `test_commit_error_returns_known_state` (частичной строки нет). ✅
- **Отмена ожидающего не откатывает владельца:** `test_a01_cancelled_waiter_does_not_rollback_owner`. ✅
- **pending в `finally` (cancel/timeout):** `test_a02_pending_released_on_cancel/_timeout`. ✅
- **lore_cache:** коалесинг не рвётся ожидающим (`test_lore_cache_waiter_does_not_break_coalescing`), generation блокирует stale-write (`test_lore_cache_generation_blocks_stale_write`). ✅
- **lore_notify:** соединение закрывается при провале init (`test_lore_notify_closes_conn_on_init_failure`). ✅
- **R17:** новые логи (`task_supervisor:*`, `database_*`) — id/op/тип ошибки, без секретов/путей. ✅

## 6. Blocking findings

**Нет.** B-MCA01-1/2/3/4 закрыты на требуемом уровне; новых блокеров не выявлено.

## 7. Non-blocking (Low / debt)

- **L-MCA01-5 [Low, new — fencing-symmetry, «пограничный Medium»]:** `TaskSupervisor.run()` передаёт `fencing_token` только в success-путь (`:287-289`); терминальные записи `cancelled` (`:299-301`) и `failed` (`:310-312`) вызывают `_safe_finish(...)` **без токена** → после takeover «медленный» владелец, падающий/отменяемый, может перезаписать *статус/reason* уже терминальной строки `interrupted` (своей же, не нового владельца). **Blast radius ограничен:** новый владелец использует новый `job_id`; результат (`result_ref`) пишется только success-путём и защищён; дублей/порчи данных нет. **Приёмка A51 («takeover … нет дублей») и инвариант владения результатом выполнены** — поэтому Low. **Рекомендация (перед первым production-подключением TaskSupervisor — `mca-17a`/архив):** передавать `fencing_token=fence` и в cancelled/failed-пути (+ расширить тест), чтобы «старый владелец потеряет право записи» было полным. Дополнительно: формулировка threat H17a/`evidence-rework` «во все терминальные записи» сейчас неточна — привести к факту.
- **L-MCA01-6 [Low, doc]:** `tasks.md` T-3736 указывает разбивку «61 в `@_serialized_write` + 41» (факт по AST: **49 + 53 = 102**); T-3747-примечание содержит устаревшие числа (pytest `9542/0`, Δ DDL `v13`) вместо финальных (`9588/0`, v13/v14/v15). Редакционное — привести к факту.
- **L-MCA01-7 [Low, debt]:** write-audit-тест аудирует `.commit()`-точки, но не «сырые» write-`execute` без commit; независимый AST-скан (`services/*.py`) подтвердил, что все текущие raw-SQLite write-`execute` (кроме отдельного соединения `smart_cache` и PG-модулей) находятся внутри `serialized()`/`write_transaction`/`_body`. Резерв: при появлении новых raw-write добавить проверку в guard.
- **Unavailable (релизные, вне gate):** нагрузочный RSS-цикл (T-3745, `mca-release`); `DB_LOCK_RESILIENCE_ENABLED=false` полный сценарный прогон — только unit.

## 8. Adjudication трактовок @Builder

- **T-3741/T-3742 (durable partial unique `coalesce_key`):** законно — `idx_task_jobs_coalesce_active` совпадает с рамкой §1.1.1; dedup через `INSERT OR IGNORE`+SELECT; A51-тест. ✅
- **T-3746/T-3775/T-3761 (стадии/виджет MCA-17a):** законная граница spec §1 (стадии — не в scope волны 0). ✅
- **T-3736:** теперь `[x]` **правдив** (аудит закрыт) — с поправкой на doc-нит L-MCA01-6.

## 9. Вывод

Все четыре блокера итер.1 закрыты на требуемом уровне, подтверждено независимыми прогонами (pytest 9588/0, JS 47/47, focused 33) и AST-аудитом write-точек. Единственный остаток — L-MCA01-5 (fencing-symmetry, ограниченный blast radius), зарегистрирован как non-blocking с обязательным исправлением до первого production-подключения. **Approved** на binding выше. `ADR-1027-3 → Accepted` и Merge §93+ — за @Architect по факту завершения волны.

> ⚠️ **Связка binding:** три фичи волны делят один Working-Tree-Hash. Любая правка (в т.ч. будущее исправление L-MCA01-5) делает этот binding stale для всех трёх — при следующем цикле требуется bounded re-bind.
