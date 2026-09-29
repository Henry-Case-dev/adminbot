# ADR-1027-3 — `mca-01-tx-task-supervisor`: семантика владения транзакцией под lock (rollback внутри lock, отмена ожидающего безопасна, known-state/retry), согласованный write-механизм для всех записей в общую SQLite connection (сеть/LLM вне транзакции), TaskSupervisor (реестр + durable `task_jobs` + coalescing/singleflight + bounded очереди + resource closers + generation/fencing + eviction), fix `pending`-в-finally, lore-notifier leak, inflight-cancel, stale-cache — Δ DDL = v14, Δ каталога = 0, R3

- **Статус:** **✅ Accepted** — фактом мержа волны 0 MCA (round 10.27, 26.09.2026) в `plans/ARCHITECTURE.md` **§95** (`mca-01-tx-task-supervisor`). На момент Step 2 @Architect — Proposed; Accepted только по Merge.
- **Фича:** `mca-01-tx-task-supervisor` (Wave 0, P0). **Deploy:** `DEFERRED_TO_RELEASE`.
- **ТЗ-основание:** `plans/current_task.md` §5.1 (`:111–124`), §5.2 (`:126–139`), §22 (`:1066–1070`); приёмки §19 **A01/A02/A51**; R17/R18.
- **Baseline:** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v12**; каталог `473/430/448/102/100/21`; канон 12.
- **Связано:** FIX `services/database.py::write_transaction`; FIX `services/smartmodule_concurrency.py`; FIX `services/lore_notify.py`/`services/lore_cache.py`; REUSE `services/dossier_rebuild_jobs.py` (прецедент durable job-store/registry/retention); REUSE F0.5/ADR-1024-18 (не дублировать); мост с `mca-14` (v14)/`mca-13` (события); рамка `plans/docs/mca-round1027-arch-frames.md`.

## Контекст

§5.1 требует, чтобы транзакцией владела **только** задача, реально получившая lock и начавшая её; `BEGIN`/тело/`COMMIT`-`ROLLBACK`/отменоустойчивая очистка — под этим lock; отмена ожидающего не меняла транзакцию владельца; после ошибки соединение возвращалось в известное состояние (иначе — явное закрытие/восстановление с видимой ошибкой); retry/backoff после освобождения lock; сеть/LLM вне транзакции; **все** записи в общую connection (включая embedding cache/backfill/сводки/служебные `UPDATE`/`DELETE`) проведены через согласованный механизм. §5.2 требует `pending` в `finally`, безопасную смену concurrency, реестр фоновых задач, durable очередь, coalescing/singleflight, bounded очереди, независимое закрытие ресурсов, generation/version-инвалидацию, исправление lore-notifier leak/inflight-cancel/stale-cache, eviction/cleanup, bounded SQL профиля.

**Фактическое состояние baseline (сверено с рабочей веткой — дефекты ТЗ присутствуют, «уже исправлено» НЕ подтверждается).**
- `services/database.py::write_transaction` (`:563–620`): `try` оборачивает `async with self._lock`; при исключении `except BaseException` выполняет `await self._best_effort_rollback(op_name)` (`:611`) **уже после выхода из lock** → возможен rollback чужой транзакции. Отменённый **ожидающий** (провал на acquisition) тоже попадает в `except BaseException` (`CanceledError`) и вызывает rollback общей connection, не начав транзакцию (`:593–597` OFF-путь и `:606–618` ON-путь). **Оба дефекта §5.1 присутствуют.**
- `services/smartmodule_concurrency.py`: `pending` инкрементируется в `_get_slot` (`:103`), декрементируется только в `_drop_pending` после acquire/по `TimeoutError` (`:137–140`, `:147`). `CancelledError` при `await slot.sem.acquire()` не перехвачен → `pending` утекает. **Дефект §5.2 присутствует.**
- `services/lore_notify.py::_connect_default` (`:47–56`): `conn = await asyncpg.connect(...)` затем `await self._init_fn(conn)`; если `_init_fn` бросает — `conn` не закрывается (утечка). **Дефект §5.2 присутствует.**
- `services/lore_cache.py::get` (`:87–134`): ожидающий в `finally` удаляет `_inflight[chat_id]`, даже будучи не владельцем (`:110–113`) → коалесинг рвётся/возможен второй SELECT; `invalidate` (`:147–151`) удаляет запись, но владелец после `await store.get_profile` пишет `_entries[chat_id]` (`:132–133`) → возврат устаревшего кеша. **Оба дефекта §5.2 присутствуют.**
- Direct `self.db.commit()` — 91 в `database.py` + `chat_lore.py`/`direct_chat_service.py`/`dossier_rebuild_jobs.py`/`memory_maintenance.py`/`memory_rebuild.py`/`persistent_throttling.py`/`summary_memory.py`; `write_transaction` уже используется в 3 модулях. **Аудит write-точек (§5.1) — не завершён.**
- `services/dossier_rebuild_jobs.py::DossierRebuildJobStore` (`:242`) — файловый durable job-store с retention/registry/`register_task` (`:405`) — прецедент для TaskSupervisor.
- F0.5/ADR-1024-18 `DB_LOCK_RESILIENCE_ENABLED` (`config/settings.py:1277`) + single-writer lock — **существующий контракт, не дублируется.**

## Решения

**D1. Владение транзакцией: rollback внутри lock; отмена ожидающего безопасна.**
- **Выбрано:** в `write_transaction` lock берётся **первым** (вне try, либо так, чтобы acquisition-провал не попадал в ветку rollback); `BEGIN`/тело/`COMMIT`/`ROLLBACK`/очистка — **под** lock; rollback вызывается **внутри** `async with self._lock`, а не после. Отменённый ожидающий → ранний выход **без** rollback общей connection. `commit_if`-паритет и OFF-путь (`DB_LOCK_RESILIENCE_ENABLED=false`) сохраняются.
- **Обоснование:** §5.1 verbatim (`:117–119`); устраняет ровно два описанных дефекта; сохраняет F0.5-контракт.
- **Альтернатива:** отдельное соединение на транзакцию — отклонено (WAL/single-writer-контракт, ресурсы, риск `database is locked`).

**D2. Known-state после ошибки + retry/backoff после освобождения lock.**
- После ошибки `commit`/`rollback` соединение возвращается в известное состояние; при невозможности — явное закрытие/восстановление с видимой ошибкой (событие MCA-13). Retry/backoff — только для `locked` (`_LOCK_RETRIES`/`_LOCK_BACKOFF`), **после** освобождения lock; не-`locked` ошибки не маскируются. Поведение OFF-пути — baseline.

**D3. Согласованный механизм всех записей в общую connection.**
- **Выбрано:** аудит **всех** write-точек (не по тексту `.execute`): каждая запись (embedding cache, backfill, сводки, служебные `UPDATE`/`DELETE`, throttle/counter) проходит через единый механизм — `write_transaction` или эквивалентный single-writer. Чтения не флагаются по совпадению. Сеть/LLM — вне транзакции (тест-спай).
- **Обоснование:** §5.1 verbatim (`:121–122`); прецедент F0.5 уже ввёл single-writer и покрыл часть путей.
- **Альтернатива:** механическая замена `.execute` на обёртку — отклонено (§5.1 прямо запрещает считать чтения нарушением по совпадению текста).

**D4. `smartmodule_concurrency`: `pending` в `finally`.**
- **Выбрано:** декремент `pending` в `finally` `try_acquire`/`acquire` на всех путях, включая `CancelledError` (использовать `try/finally` вокруг acquire, а не только `except TimeoutError`). Смена `concurrency` — после безопасного drain либо через единый регулируемый счётчик (не два параллельных семафора сверх ёмкости).
- **Обоснование:** §5.2 verbatim (`:130–131`); дефект подтверждён.

**D5. TaskSupervisor: реестр задач + durable queue `task_jobs`.**
- **Выбрано:** in-process реестр `task_id/owner/kind/deadline/result_ref/exception_handler`; долговременная работа — в durable-таблице `task_jobs` (v14, рамка §1.1.1). Exception handler гарантирует видимый терминальный исход (событие MCA-13), не `except: pass`. Реестр — **единственный**; MCA-17a строит поверх него, не второй.
- **Обоснование:** §5.2 verbatim (`:132`); транзакционная интеграция с общим write-механизмом, coalescing, bounded SQL. REUSE прецедента `DossierRebuildJobStore` (файловый store остаётся доменным для dossiers-артефактов; каноническая общая очередь — `task_jobs`).
- **Альтернатива:** только файловый store (как dossier) — отклонено (нужны транзакционность/coalescing unique-key/bounded выборки по всем задачам); второй общий механизм — запрещено.

**D6. Coalescing/singleflight + bounded очереди.**
- `coalesce_key` + частичный UNIQUE-индекс по активным статусам — повторяющееся задание по чату/версии не запускается дважды; при переполнении важное остаётся в durable, второстепенное объединяется/отклоняется с причиной (`queue_coalesced`/`queue_full`); молчаливая потеря запрещена.

**D7. Ресурсы/invalidation/eviction.**
- Каждый closer выполняется независимо (ошибка другого не мешает); отмена освобождает свои ресурсы. **Исправить:** lore-notifier leak (закрыть `conn` при провале init), inflight-cancel (ожидающий не снимает чужой inflight), stale-cache (generation/version-инвалидация при записи после invalidate). Eviction/cleanup для кешей/cooldown-map/throttle-map/результатов/временных файлов; bounded SQL профиля (`LIMIT` вместо `fetchall`).

**D8. generation/version-инвалидация.**
- У кешей/задач — монотонная `generation`; запись применяется только если `generation` не изменилась после старта/invalidation; у задач — `fencing_token` для takeover (A51).

**D9. Kill-switch.**
- `MCA_TX_OWNERSHIP_ENABLED` (default ON; OFF → прежний `write_transaction`), `MCA_TASK_SUPERVISOR_ENABLED` (default ON; OFF → без реестра/durable/coalescing). env-only `ClassVar` → Δ каталога=0. `DB_LOCK_RESILIENCE_ENABLED` уважается.

**D10. Δ DDL = v14; Δ каталога = 0; границы/откат.**
- `task_jobs` + индексы через механизм `mca-14` (v14). PG — no-op. Каталог не меняется, F8 не переиздаётся. Откат: hot env-OFF; cold `git revert` → `7165ff7`.

## Санкции и вердикты

- **Δ DDL = v14** — `task_jobs` (+2 индекса). Старые таблицы/ID не трогаются. §5.1 DDL не требует.
- **Δ каталога = 0**; F8 (ADR-1026-2) **NOT_APPLICABLE**.
- **Kill-switch:** `MCA_TX_OWNERSHIP_ENABLED`, `MCA_TASK_SUPERVISOR_ENABLED` (env-only, default ON); `DB_LOCK_RESILIENCE_ENABLED` уважается.
- **Risk:** **R3** (общий write-path/жизненный цикл задач); `threat-failure-analysis.md` обязателен (Блок H). Понижение — при доказанной изоляции/A01/A02/A51 на фактическом diff.
- **Обратный путь:** hot env-OFF; cold `git revert` → `7165ff7`; `task_jobs` безвреден.
- **Release policy:** `DEFERRED_TO_RELEASE`.

## AMEND / REUSE-карта

| ADR / артефакт | Статус | Суть |
|---|---|---|
| `services/database.py::write_transaction` | **FIX** | lock-владение; rollback внутри lock; отмена ожидающего безопасна; known-state/retry |
| `services/smartmodule_concurrency.py` | **FIX** | `pending` в `finally`; безопасная смена concurrency |
| `services/lore_notify.py` / `services/lore_cache.py` | **FIX** | leak connection; inflight-cancel; stale-cache (generation) |
| `services/dossier_rebuild_jobs.py` | **REUSE (прецедент)** | durable job-store/registry/retention; канон — `task_jobs` |
| F0.5 / ADR-1024-18 `DB_LOCK_RESILIENCE_ENABLED` | **REUSE / не дублировать** | существующий single-writer/retry |
| `mca-14` (v14, backup/runner) | **зависимость** | DDL через механизм |
| `mca-13` (события) | **зависимость** | терминальные исходы задач/транзакций |
| MCA-17a | **Unblocks** | реестр/heartbeat/watchdog поверх TaskSupervisor |
| ADR-1026-2 (F8) | **NOT_APPLICABLE** | Δ каталога = 0 |

| Решение | Задачи |
|---|---|
| D1 (владение) | T-3734 |
| D2 (known-state/retry) | T-3735 |
| D3 (write-механизм) | T-3736, T-3737 |
| D4 (`pending`/concurrency) | T-3738, T-3739 |
| D5 (TaskSupervisor/durable) | T-3740 |
| D6 (coalescing/bounded) | T-3741, T-3742 |
| D7 (ресурсы/eviction) | T-3743, T-3744 |
| D8 (generation/fencing) | T-3743, T-3740 |
| D9 (kill-switch) | T-3747 |
| D10 (Δ DDL/границы) | T-3740, T-3747 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Владение tx | rollback после lock; внутри lock | **внутри lock** | §5.1 verbatim; устраняет дефект |
| Транзакция | отдельное соединение; общий single-writer | **общий single-writer** | WAL-контракт F0.5; ресурсы |
| Write-точки | текст `.execute`; аудит по смыслу | **аудит по смыслу** | §5.1 запрещает ложные срабатывания |
| Durable queue | файловый store; `task_jobs` | **`task_jobs`** | транзакционность/coalescing/bounded SQL |
| Coalescing | без ключа; unique `coalesce_key` | **unique `coalesce_key`** | §5.2 singleflight |
| Kill-switch | каталожный; env-only | **env-only ClassVar** | Δ каталога=0 |
| Risk | R2; R3 | **R3** | общий write-path/жизненный цикл |

## Последствия

- §5.1: транзакцией владеет lock-держатель; отмена ожидающего безопасна; known-state/retry; все записи в общую connection — через согласованный механизм; сеть/LLM вне транзакции.
- §5.2: `pending` в `finally`; реестр задач + durable `task_jobs`; coalescing/bounded очереди; независимое закрытие ресурсов; исправлены lore-notifier leak/inflight-cancel/stale-cache; generation/fencing; eviction/bounded SQL.
- Δ DDL=v14; Δ каталога=0; risk R3 + threat-артефакт; hot-откат env-OFF; cold — `git revert` → `7165ff7`; deploy `DEFERRED_TO_RELEASE`.

## Ссылки

- `plans/features/mca-01-tx-task-supervisor/{spec.md, tasks.md}` (spec — T-3732; сверка — @PM T-3733).
- Рамка: `plans/docs/mca-round1027-arch-frames.md` (§1.1.1 v14, §3 kill-switch).
- Код: `services/database.py` (`:563–620`); `services/smartmodule_concurrency.py` (`:96–148`); `services/lore_notify.py` (`:47–56`); `services/lore_cache.py` (`:87–151`); `services/dossier_rebuild_jobs.py` (`:242–361`, `:405`); `config/settings.py:1277`.
- ТЗ: `plans/current_task.md` §5.1 (`:111–124`), §5.2 (`:126–139`), §19 A01/A02/A51 (`:882–883`,`:932`).
- Архитектура: merge → §95; входы — F0.5/ADR-1024-18, §82–§92.
- Точка отката: коммит `7165ff7`.
