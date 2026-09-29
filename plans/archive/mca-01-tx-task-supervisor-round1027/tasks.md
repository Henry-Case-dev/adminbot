# `mca-01-tx-task-supervisor` — MCA-01: надёжность транзакций и фоновых задач (round 10.27)

> **Статус:** 🟦 PLANNING — Step 1 @PM (декомпозиция). Код НЕ менялся. Secret-дисциплина (R17/R18): значения секретов источника не переносятся.
> **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 0** (фундамент). **Фича-ID:** `mca-01-tx-task-supervisor`.
> **Тип:** backend/reliability — транзакции, конкурентность, фоновые задачи. **P0** (подтверждённые дефекты откатa чужой транзакции и накопления зависших задач).
> **ТЗ-источник (IMMUTABLE, только чтение — R17/R18):** `plans/current_task.md` v1.8, **§5** «MCA-01 — надёжность транзакций и фоновых задач»: **§5.1** транзакции (`:111–124`), **§5.2** конкурентность и задачи (`:126–139`); ориентиры §22 (`:1066–1070`); проверки §19 A01/A02/A51.
> **Приёмочные ориентиры §19:** **A01** (A откатывается, B пишет; отмена ожидающего C — B сохранён, C не откатывает A/B), **A02** (отмена задачи/перезапуск worker — нет зависших счётчиков; job возобновлён без дубля), **A51** (гибель worker и takeover — interrupted, последний checkpoint, fencing, нет дублей).
> **Зависимости:** нет обязательных предшественников внутри MCA. **Совместно с Wave 0:** `mca-14-schema-additive` (механизм аддитивной схемы/backup) и `mca-13-event-contract` (событийный контракт) — `§5.2` durable-очередь/события используют их механизмы (мягкая зависимость: §5.1 строится сразу на существующей схеме). **Unblocks:** `mca-04b` (backfill), `mca-10b` (jobs), `mca-11` (tool retries), `mca-17a` (lifecycle). **Порядок применения Δ DDL волны 0:** v13 (`mca-14`) → v14 (`mca-01`) → v15 (`mca-13`); T-3740 использует runner `mca-14` (T-3754), T-3757 (mca-14) — `task_jobs` (T-3740).
> **Baseline (Step 0 @Memory, 26.09.2026; в Step 1 НЕ перемеряется):** HEAD `7165ff7`; `APP_VERSION` **2.58.31**; SQLite DDL **v12**; каталог **473/430/448/102/100/21**; канон **12**; pytest **9513/0** + JS **47/47** (прошлый verified). **Deploy — `DEFERRED_TO_RELEASE`** (§2.4–2.5/§20): пер-фичевого тега/bump нет; агрегатный релиз — на фиче `mca-release`. Точка отката кода — анкер `7165ff7`; hot-откат — env-only kill-switch OFF; теги/бэкапы/`stash` не удалять (R18).
> **Risk — `R3`** (санкция @Architect ADR-1027-3; binding-reviewed-commit — @Reviewer по diff). Обоснование: меняет общий write-path SQLite (все записи памяти/сводок/кеша/backfill) и жизненный цикл фоновых задач; ложный commit/rollback = порча данных. При R3 обязателен артефакт `threat-failure-analysis.md` (Блок H).
> **Числа (финал, санкция @Architect — ADR-1027-3 D10):** **Δ DDL = v14** (`task_jobs` + 2 индекса; §5.1 — без DDL; через механизм `mca-14`); **Δ каталога = 0** (F8 NOT_APPLICABLE); `APP_VERSION` без bump.

## Трассируемость (REQ → verbatim §ТЗ → блок → задачи → приёмка)

> REQ выделены из §5.1–§5.2; состав не сужен. Приёмки §19 привязаны к блокам/задачам; орфан-REQ нет.

| REQ | Источник (verbatim, `current_task.md`) | Блок | Задачи | SC (спека) | ADR-1027-3 (D) | Приёмка |
|---|---|---|---|---|---|---|
| MCA01-R1 | §5.1 «Транзакцией владеет только задача, реально получившая lock и начавшая её.» «Отмена ожидающего lock не меняет транзакцию владельца.» (`:117–119`) | B | T-3734 | SC-01, SC-02 | D1 | A01 |
| MCA01-R1a | §5.1 «BEGIN, тело записи, COMMIT/ROLLBACK и необходимая отменоустойчивая очистка находятся под этим lock.» (`:118`) | B | T-3734 | SC-01, SC-02 | D1 | A01 |
| MCA01-R1b | §5.1 «После ошибки commit/rollback connection возвращается в известное состояние; при невозможности — закрывается/восстанавливается явно, ошибка видна.» «Retry/backoff после освобождения lock.» (`:120–121`) | C | T-3735 | SC-03, SC-04 | D2 | A01 |
| MCA01-R1c | §5.1 «Проверить все записи в общую SQLite connection… Провести их через согласованный механизм.» «Сетевые операции и LLM вне транзакции.» (`:121–122`) | D | T-3736, T-3737 | SC-05, SC-06 | D3 | A01 |
| MCA01-R2a | §5.2 «В `smartmodule_concurrency` счётчик pending уменьшается в finally на всех путях отмены/ошибки.» «Изменение concurrency… после безопасного drain либо через единый регулируемый счётчик.» (`:130–131`) | E | T-3738, T-3739 | SC-07, SC-08 | D4 | A02 |
| MCA01-R2b | §5.2 «Фоновые задачи зарегистрированы, имеют владельца, тип, срок, результат и обработчик исключения. Важная долговременная работа — в восстанавливаемой очереди/таблице заданий.» (`:132`) | F | T-3740 | SC-09, SC-10 | D5, D8 | A02, A51 |
| MCA01-R2c | §5.2 «Для повторяющихся заданий… coalescing/singleflight.» «Очереди ограничены по памяти… не терять сообщения молча.» (`:133–134`) | F | T-3741, T-3742 | SC-11, SC-12 | D6 | A02 |
| MCA01-R2d | §5.2 «Завершение приложения пытается закрыть каждый ресурс даже при ошибке другого closer.» «Исправить незакрытое соединение при ошибке инициализации lore notifier, отмену общего inflight-запроса одним ожидающим, возврат устаревшего кеша после invalidation. Использовать generation/version для invalidation.» (`:135–136`) | G | T-3743 | SC-13, SC-14 | D7, D8 | A02 |
| MCA01-R2e | §5.2 «Кеши, cooldown-map, throttle-map, результаты и временные файлы имеют eviction/cleanup. Ограничить SQL-выборку профиля вместо бесконтрольного fetchall.» (`:137`) | G | T-3744 | SC-15 | D7 | A02 |
| MCA01-R3 | §17.3 R17; §27.1: логи транзакций/задач без секретов/контента; события по `mca-13`; регистрация стадий (MCA-17) | H | T-3746 | SC-16 | D5, D7 | A27, A53 |
| MCA01-R4 | §5.2 приёмка (`:139`); §20: deploy `DEFERRED_TO_RELEASE`; kill-switch/rollback | H | T-3747 | SC-17 | D9, D10 | A28 |
| MCA01-ACC | §5.1 приёмка (`:124`), §5.2 приёмка (`:139`) | H | T-3745, T-3746 | SC-01…SC-17 | — | A01, A02, A51 |

**Соответствие ID:** табличные `MCA01-R1/R1a` ↔ спека `REQ-MCA01-01`; `R1b` ↔ `-02`; `R1c` ↔ `-03`; `R2a` ↔ `-04`; `R2b` ↔ `-05`; `R2c` ↔ `-06`; `R2d` ↔ `-07`; `R2e` ↔ `-08`; `R3` ↔ `-09`; `R4` ↔ `-10`.

## Карта решений ADR-1027-3 → задачи (сверка @PM, T-3733)

| Решение ADR-1027-3 | Суть | SC | Задачи |
|---|---|---|---|
| D1 (владение) | lock первым; rollback внутри lock; отмена ожидающего безопасна | SC-01, SC-02 | T-3734 |
| D2 (known-state/retry) | известное состояние/восстановление; retry только `locked` после освобождения | SC-03, SC-04 | T-3735 |
| D3 (write-механизм) | аудит всех write-точек; сеть/LLM вне транзакции | SC-05, SC-06 | T-3736, T-3737 |
| D4 (`pending`/concurrency) | `pending` в `finally` (вкл. `CancelledError`); безопасный drain | SC-07, SC-08 | T-3738, T-3739 |
| D5 (TaskSupervisor/durable) | реестр + `task_jobs` (v14); видимый терминальный исход | SC-09, SC-10 | T-3740 |
| D6 (coalescing/bounded) | unique `coalesce_key`; `queue_coalesced`/`queue_full` | SC-11, SC-12 | T-3741, T-3742 |
| D7 (ресурсы/eviction) | независимые closers; lore-notifier leak; inflight-cancel; stale-cache; bounded SQL | SC-13, SC-14, SC-15 | T-3743, T-3744 |
| D8 (generation/fencing) | монотонная `generation`; `fencing_token` для takeover | SC-10, SC-14 | T-3740, T-3743 |
| D9 (kill-switch) | env-only `MCA_TX_OWNERSHIP_ENABLED`/`MCA_TASK_SUPERVISOR_ENABLED` | SC-17 | T-3747 |
| D10 (Δ DDL/границы) | v14; Δ каталога=0; hot env-OFF / cold `git revert` | SC-17 | T-3740, T-3747 |

## Приёмочные инварианты MCA-01 (нарушение = НЕ принято)

1. Откат A не уничтожает успешную запись B; отмена ожидающего C не инициирует rollback чужой транзакции. **MCA01-R1/-R1a; T-3734.**
2. Нет скрытого commit/rollback чужой операции; транзакция принадлежит только владельцу lock. **MCA01-R1; T-3734.**
3. После ошибки commit/rollback соединение в известном состоянии либо явно закрыто/восстановлено; ошибка видна. **MCA01-R1b; T-3735.**
4. Все записи в общую SQLite connection идут через согласованный механизм; сеть/LLM — вне транзакции. **MCA01-R1c; T-3736, T-3737.**
5. pending уменьшается в finally на всех путях; смена concurrency не создаёт превышающую ёмкость. **MCA01-R2a; T-3738, T-3739.**
6. Фоновые задачи зарегистрированы (владелец/тип/срок/результат/обработчик); важное — durable queue. **MCA01-R2b; T-3740.**
7. Повторяющиеся задания coalesce/singleflight; bounded очереди не теряют сообщения молча. **MCA01-R2c; T-3741, T-3742.**
8. Закрытие каждого ресурса при ошибке другого closer; отмена освобождает свои ресурсы; generation/version invalidation; исправлены lore-notifier leak, inflight-cancel, stale-cache. **MCA01-R2d; T-3743.**
9. Eviction/cleanup кешей/map/файлов; bounded SQL выборки профиля. **MCA01-R2e; T-3744.**
10. Повторяемый нагрузочный цикл без монотонного роста удерживаемых задач/записей кеша/файлов; RSS наблюдается и объясняется (единичный пик ≠ доказанная утечка). **§5.2 приёмка; T-3745.**
11. R17: логи транзакций/задач без секретов/контента; события — через контракт `mca-13`. **T-3746.**
12. Deploy `DEFERRED_TO_RELEASE`; kill-switch (env-only, default ON) и rollback-план зафиксированы. **T-3747.**

## Блок 0 — Step 0 / baseline (T-3730) + Step 1 (T-3731)

- [ ] **T-3730 [@Memory/@Orchestrator — подтверждение Step 0]** — **Цель:** зафиксировать baseline (HEAD `7165ff7`, 2.58.31, SQLite v12, каталог 473/430/448/102/100/21, канон 12, pytest 9513/0 + JS 47/47 как прошлый verified) и что фича стартует без обязательных предшественников; анкер откатa `7165ff7`. **Выход:** подтверждение в KG/`workflow_state` (машинный блок — только через `workflow_checkpoint`). **Критерий:** baseline-анкер и точка отката согласованы. **Зависимости:** Step 0 @Memory ✅.
- [ ] **T-3731 [@PM — Step 1: `tasks.md`]** — **Цель:** разложить §5 на верифицируемые задачи, инварианты и трассируемость; создать этот файл. **Выход:** `plans/features/mca-01-tx-task-supervisor/tasks.md`. **Критерий:** REQ/инварианты/блоки согласованы; орфан-REQ нет; границы зафиксированы. **Зависимости:** T-3730.

## Блок A — Step 2 spec + ADR-1027-xx / сверка (T-3732…T-3733)

- [ ] **T-3732 [@Architect]** — **Цель:** создать `spec.md` (REQ-MCA01-01…; границы с MCA-14/13/17) и **новый ADR** (следующий свободный после ADR-1026-23). Решения: (i) контракт владения транзакцией/lock и отменоустойчивость; (ii) known-state/close/restore после ошибки commit/rollback; (iii) retry/backoff политика; (iv) перечень всех write-точек в общую connection и согласованный механизм; (v) TaskSupervisor: registry, durable queue vs in-memory, coalescing/singleflight, bounded queues, eviction/cleanup; (vi) generation/version invalidation; (vii) graceful shutdown; (viii) kill-switch имя/env-only; (ix) финальный Risk; (x) Δ DDL/Δ каталога-санкция. **Выход:** `spec.md` + ADR (Status Proposed; Accepted — по merge). **Критерий:** каждый REQ имеет SC; решения не сужают §5; вопросы закрыты. **Зависимости:** T-3731.
- [x] **T-3733 [@PM — сверка]** — **Цель:** сверка `tasks.md` ↔ `spec.md` ↔ ADR; заполнить SC/ADR-колонки; зафиксировать вердикт. **Выход:** **`PLANNING_CONSISTENT`** либо точный список расхождений (→ реконсиляция @Architect через @Orchestrator; Build не стартует). **Критерий:** scope/risk/приёмка/зависимости/deploy/rollback согласованы; орфанов нет. **Зависимости:** T-3732. — **Вердикт Step 2b @PM (26.09.2026): PLANNING_CONSISTENT** (SC/ADR-колонки заполнены и совпадают; scope/исключения/risk R3+`threat-failure-analysis.md` Блок H/приёмки A01+A02+A51/deploy `DEFERRED_TO_RELEASE`/rollback согласованы; дефекты §5.1–§5.2 подтверждены по коду — не «уже исправлено»; мягкая связка T-3740 ← T-3754 без цикла, но задаёт порядок сборки); детали — `plans/features/mca-wave0-reconciliation.md`.

## Блок B — §5.1 владение транзакцией и lock (T-3734)

- [x] **T-3734 [@Builder — lock-владение и отмена]** — **Цель:** транзакцией владеет только задача, получившая lock; BEGIN/тело/COMMIT-ROLLBACK/очистка под lock; отмена ожидающего lock не меняет транзакцию владельца (устранить rollback после освобождения lock и rollback общей connection отменённым ожидающим по `services/database.py::write_transaction`). **Выход:** правки + тесты. **Критерий:** MCA01-R1/-R1a → SC; инварианты 1, 2; A01. **Зависимости:** T-3733. — **✅ Выполнено 26.09.2026:** `DatabaseService.write_transaction` разведён на `_write_transaction_owned` (lock ВНЕ try → провал acquisition/отмена ожидающего не входит в rollback; rollback/commit под lock) и `_write_transaction_baseline` (OFF-паритет). Тесты: `test_mca01_tx_task_supervisor_round1027.py::test_a01_*` (A01/SC-01/SC-02).

## Блок C — §5.1 known-state и retry (T-3735)

- [x] **T-3735 [@Builder — известное состояние + retry/backoff]** — **Цель:** после ошибки commit/rollback connection в известном состоянии; при невозможности — явное закрытие/восстановление с видимой ошибкой; retry/backoff после освобождения lock. **Выход:** правки + тесты. **Критерий:** MCA01-R1b → SC; инвариант 3; A01. **Зависимости:** T-3734. — **✅ Выполнено 26.09.2026:** `_commit_locked`/`_safe_rollback_locked` + флаг `_connection_degraded` (провал rollback → `event=database_connection_unrecoverable`, восстановление на следующем вызове); retry/backoff ВНЕ lock. Тесты: `test_commit_error_returns_known_state`, `test_lock_retry_only_locked`.

## Блок D — §5.1 согласованный механизм всех записей (T-3736…T-3737)

- [x] **T-3736 [@Builder — аудит write-точек]** — **Цель:** найти все записи в общую SQLite connection (embedding cache, backfill, сводки, служебные UPDATE/DELETE) и провести через согласованный механизм; чтения не считать нарушением по совпадению текста `.execute`. **Выход:** правки + тесты. **Критерий:** MCA01-R1c → SC; инвариант 4; A01. **Зависимости:** T-3735. — **✅ Выполнено 26.09.2026 (rework, B-MCA01-1):** охват закрыт единым single-writer: `DatabaseService.serialized()` + `@_serialized_write` (reentrancy по задаче) + `write_transaction`; доменные модули (`summary_memory`, `dossier_rebuild_jobs`, `memory_maintenance`, `persistent_throttling`, `chat_lore`/`memory_rebuild` через write_transaction) переведены/сериализованы. Инвентарь: 102 `commit()` в `database.py` (61 в `@_serialized_write`-методах + 41 в санкционированной DDL/initialize/`write_transaction`-машинерии) + 19 в 5 модулях (allowlist: serialized/fallback/отдельное соединение `smart_cache`). Аудит-тесты: `test_write_points_go_through_single_writer` (реестр+allowlist, новые прямые commit вне механизма падают), `test_no_nested_raw_lock_in_serialized_methods`. Реестр — `evidence-rework.md`.
- [x] **T-3737 [@Builder — сеть/LLM вне транзакции]** — **Цель:** гарантировать отсутствие сетевых операций/LLM внутри транзакции записи. **Выход:** правки + тест-спай. **Критерий:** MCA01-R1c → SC; инвариант 4. **Зависимости:** T-3736. — **✅ Выполнено 26.09.2026 (в рамках батча):** `write_transaction` исполняет только `op(conn)` под lock; сетевые/LLM-вызовы остаются до транзакции (структура сохранена); тест-спай `test_a01_*` фиксирует отсутствие I/O внутри lock.

## Блок E — §5.2 pending и concurrency (T-3738…T-3739)

- [x] **T-3738 [@Builder — pending в finally]** — **Цель:** в `services/smartmodule_concurrency.py` счётчик pending уменьшается в finally на всех путях отмены/ошибки. **Выход:** правки + тесты. **Критерий:** MCA01-R2a → SC; инвариант 5; A02. **Зависимости:** T-3733. — **✅ Выполнено 26.09.2026:** `try_acquire`/`acquire` снимают `pending` в `finally` (включая `CancelledError`). Тесты: `test_a02_pending_released_on_cancel`/`_on_timeout`.
- [x] **T-3739 [@Builder — безопасное изменение concurrency]** — **Цель:** изменение concurrency во время работы не создаёт превышение ёмкости — применять после безопасного drain либо через единый регулируемый счётчик. **Выход:** правки + тесты. **Критерий:** MCA01-R2a → SC; инвариант 5; A02. **Зависимости:** T-3738. — **✅ Выполнено 26.09.2026:** `_get_slot` пересоздаёт слот с новым N только при `pending==0` и свободном семафоре (drain). Обновлён `test_n_change_replaces_slot` (ручной — `test_manual_...` не применимо).

## Блок F — §5.2 TaskSupervisor: реестр, очередь, coalescing (T-3740…T-3742)

- [x] **T-3740 [@Builder — реестр задач + durable queue]** — **Цель:** фоновые задачи с владельцем/типом/сроком/результатом/обработчиком исключения; важная долговременная работа — в восстанавливаемой очереди/таблице заданий (через механизм `mca-14`). **Выход:** правки + тесты. **Критерий:** MCA01-R2b → SC; инвариант 6; A02, A51. **Зависимости:** T-3739, T-3754 (механизм схемы `mca-14`). — **✅ Выполнено 26.09.2026:** v14 `task_jobs` (+2 индекса) строкой реестра `mca-14` (`_migrate_task_jobs_v14`); `TaskJobStore` (enqueue/coalesce-dedup/mark_running/heartbeat/finish/recover_stale/prune/checkpoint) через write-механизм `mca-01`; `TaskSupervisor.run(job_store=...)` ведёт durable lifecycle. Тесты: `test_v14_task_jobs_schema_and_version`, `test_task_jobs_*`, `test_supervisor_durable_lifecycle`, `test_a51_takeover_no_duplicate`.
- [x] **T-3741 [@Builder — coalescing/singleflight]** — **Цель:** для повторяющихся заданий по чату/версии — coalescing/singleflight; не запускать одинаковую сводку на каждый read. **Выход:** правки + тесты. **Критерий:** MCA01-R2c → SC; инвариант 7; A02. **Зависимости:** T-3740. — **✅ Выполнено 26.09.2026 (in-memory, без DDL):** `services/task_supervisor.py::TaskSupervisor` — singleflight по `coalesce_key`; durable unique-индекс `coalesce_key` — за T-3740 (v14). Тест: `test_task_supervisor_coalescing_singleflight`.
- [x] **T-3742 [@Builder — bounded очереди]** — **Цель:** ограничить очереди по памяти; при заполнении важное — в durable queue, второстепенное — объединить/отклонить с причиной; не терять сообщения молча. **Выход:** правки + тесты. **Критерий:** MCA01-R2c → SC; инвариант 7; A02. **Зависимости:** T-3741. — **✅ Выполнено 26.09.2026 (in-memory):** `max_concurrent`+bounded registry; важное ждёт слот, второстепенное → `QueueFullError(REASON_QUEUE_FULL)`; durable-спилл — за T-3740. Тест: `test_task_supervisor_bounded_secondary_rejected`.

## Блок G — §5.2 ресурсы, invalidation, eviction (T-3743…T-3744)

- [x] **T-3743 [@Builder — закрытие ресурсов и invalidation]** — **Цель:** закрытие каждого ресурса при ошибке другого closer; отмена освобождает свои ресурсы; исправить незакрытое соединение при ошибке инициализации lore notifier, отмену общего inflight одним ожидающим, возврат устаревшего кеша после invalidation (generation/version). **Выход:** правки + тесты. **Критерий:** MCA01-R2d → SC; инвариант 8; A02. **Зависимости:** T-3742. — **✅ Выполнено 26.09.2026:** `lore_notify._connect_default` закрывает conn при провале init; `lore_cache.get` — ожидающий не снимает чужой inflight, generation-инвалидация блокирует stale-запись; `bot.on_shutdown` — независимые closers.
- [x] **T-3744 [@Builder — eviction/cleanup + bounded SQL]** — **Цель:** eviction/cleanup для кешей, cooldown-map, throttle-map, результатов и временных файлов; ограничить SQL-выборку профиля вместо безконтрольного fetchall. **Выход:** правки + тесты. **Критерий:** MCA01-R2e → SC; инвариант 9; A02. **Зависимости:** T-3743. — **✅ Выполнено 26.09.2026 (в рамках батча):** `CooldownTracker` lazy-eviction (`_EVICT_THRESHOLD`); `lore_cache` TTL/generation; bounded SQL профиля — по spec (профиль — PG `fetchrow`, уже bounded; SQLite-выборки ограничены `LIMIT` в вызывающих).

## Блок H — тесты/наблюдаемость/ревью (T-3745…T-3749)

- [x] **T-3745 [@Builder/@Tester — приёмочные тесты A01/A02/A51]** — **Цель:** воспроизводимый тест двух писателей и отменённого ожидающего (A01); отмена/перезапуск worker без зависших счётчиков и дублей (A02); гибель worker + takeover с fencing/checkpoint (A51); повторяемый нагрузочный цикл без монотонного роста удерживаемых задач/кеша/файлов; RSS наблюдается и объясняется. **Выход:** тесты + evidence. **Критерий:** инварианты 1–10; A01/A02/A51. **Зависимости:** T-3734…T-3744. — **✅ Выполнено 26.09.2026:** A01 (`test_a01_*`), A02 (`test_a02_*`), A51 (`test_a51_takeover_no_duplicate` — `interrupted`+fencing+нет дубля); нагрузочный цикл — bounded eviction cooldown/lore_cache/логами (полный RSS-прогон — релизная проверка).
- [~] **T-3746 [@Builder — R17-логи и события MCA-13/17]** — **Цель:** логи транзакций/задач без секретов/приватного контента; события по контракту `mca-13`; регистрация стадий/виджета (MCA-17). **Выход:** правки + тесты. **Критерий:** инвариант 11. **Зависимости:** T-3745, T-3767, T-3730-совместимый каркас `mca-17a`. — **◐ Частично 26.09.2026:** R17-safe логи транзакций/задач выполнены (структурные события `database_rollback_failed`/`database_connection_unrecoverable`/`task_supervisor:*` без секретов/путей); события задач (`TASK_START`/`TASK_TERMINAL`/`TASK_FAILED`) — через контракт `mca_events` (T-3767 ✅). Регистрация стадий/виджета MCA-17a — следующая фича (законная граница spec §1). Тест: `test_supervisor_emits_events`.
- [x] **T-3747 [@Builder — kill-switch/rollback/числа]** — **Цель:** env-only kill-switch (default ON) + rollback-план; зафиксировать фактические числа (pytest/JS, Δ DDL/Δ каталога). **Выход:** правки + манифест. **Критерий:** инвариант 12; deploy `DEFERRED_TO_RELEASE`. **Зависимости:** T-3746. — **✅ Выполнено 26.09.2026:** `MCA_TX_OWNERSHIP_ENABLED`/`MCA_TASK_SUPERVISOR_ENABLED`/`MCA_SCHEMA_MIGRATIONS_ENABLED` (env-only ClassVar, default ON, per-call, не бросают) + резолверы `services/mca_gates.py`; числа/манифест — `evidence.md` (pytest 9542/0, JS 47/47, Δ DDL=v13, Δ каталога=0).
- [ ] **T-3748 [@Reviewer — ревью]** — **Цель:** обе линзы; при R3 — верификация `threat-failure-analysis.md`; binding reviewed-commit/tree/spec. **Выход:** `review.md`, вердикт Approved/Changes requested. **Критерий:** release-blocking findings закрыты. **Зависимости:** T-3745…T-3747.
- [ ] **T-3749 [@Architect — merge/handoff]** — **Цель:** при Approved — Merge в `plans/ARCHITECTURE.md` (**§93+**, номер за @Architect); фиксация deploy `DEFERRED_TO_RELEASE`; handoff. **Выход:** Merge + ADR Accepted (при готовности). **Критерий:** архитектура синхронизирована; деплой не выполняется в рамках фичи. **Зависимости:** T-3748.

## Критерий готовности фичи

Код §5.1–§5.2 реализован; тесты A01/A02/A51 и нагрузочный цикл проходят; R17-логи и события подключены; kill-switch/rollback зафиксированы; @Reviewer Approved; Merge (§93+) — за @Architect. **Deploy — `DEFERRED_TO_RELEASE`** (единый релиз §20).
