# F0.5 — Устойчивость к `database is locked` (раунд 10.25, ADR-1025-5)

> AMEND ADR-1024-18: контракт (PRAGMA-паритет + bounded retry только на
> `locked` + явный лог исчерпания + kill-switch) перенесён на main write-path
> `services/database.py` и переведённые сервисы. `smart_cache` НЕ трогается.
> Δ DDL = 0, Δ каталога = 0.

## 1. Карта соединений и write-путей (T-2442)

| # | Владелец | Соединение | PRAGMA | Bounded retry | Реакция |
|---|---|---|---|---|---|
| 1 | `Database` основной | собственное `aiosqlite` | WAL + bt5000 + NORMAL | **есть** (F0.5) | вызывающий |
| 2 | `SmartCache` | собственное | WAL+bt+NORMAL | есть (ADR-1024-18) | fail-open |
| 3 | `Database.initialize_existing` | собственное (CLI) | WAL+bt+NORMAL | нет (read-probe) | — |
| 4 | `manage.py` CLI | собственное | read-only probe | нет | — |
| 5 | `memory_rebuild` sqlite3 sync | собственное | — | есть (своё) | — |
| 6 | `summary_memory._embed_cache_store` | **публичный `write_transaction`** | наследует #1 | **есть** | fail-open |
| 7 | `summary_memory.memorize_self_reply → insert_graph_fact` | общее #1 | наследует | **есть** | fail-open |
| 8 | `summary_memory._knn_graph_facts → touch_graph_facts` | общее #1 | наследует | **есть** | fail-open |
| 9 | `direct_chat_service.remember_bot_reply → upsert_bot_reply` | общее #1 | наследует | **есть** | fail-open |
| 10 | `persistent_throttling.allow/reset/bump/touch` | **публичный `write_transaction`** | наследует | **есть** | fail-open |
| 11 | `tools/history_import/loader.py` | собственное | WAL+bt5000+NORMAL (F0.5 D3) | — | — |

`manage.py` — read-only probe (`PRAGMA table_info`/VACUUM-checkpoint), не
write-path, поэтому в этом раунде не менялся (Human Gate ADR-1025-5).

## 2. Первопричина (T-2443)

1. Многошаговые транзакции на ОБЩЕМ соединении #1 (`self.db.db.execute`) без
   `Database._lock`: между `execute` и `commit` корутина отдаёт управление, и
   SQLite на том же соединении отдаёт `SQLITE_BUSY` немедленно (self-lock) —
   `busy_timeout` на межсоединённую блокировку тут не помогает.
2. Длинные транзакции (`_embed_cache_store` — N вставок; `upsert_bot_reply` —
   4 стейтмента; `touch_graph_facts` — 2 UPDATE) держат write-лок дольше.
3. Конкуренция соединений (основное + `SmartCache` + CLI) за WAL-писателя.
4. `main write-path` не имел bounded retry — короткая блокировка всплывала и
   молча терялась fail-open'ом.

## 3. Изменения (T-2445…T-2451)

- **`services/database.py`**
  - `Database._is_locked(exc)` — только `OperationalError` с `"locked"`.
  - `Database.write_transaction(op)` — держит `self._lock` на всё время
    логической транзакции, коммитит, при `locked` — bounded retry
    (`_LOCK_RETRIES=3`, backoff 0.1/0.2/0.4с, `rollback` перед повтором,
    повтор ВСЕЙ транзакции); исчерпание → WARNING + счётчик + re-raise.
  - **Ревью-итерация 2:** `rollback` выполняется на **любое** исключение (не
    только `locked`), включая OFF-путь — частичная транзакция не остаётся на
    общем соединении и не может быть закоммичена следующей операцией. Провал
    самого `rollback` логируется на DEBUG (`_best_effort_rollback`).
  - `Database._note_lock_exhausted` + `database_lock_exhausted_total()` +
    `event=database_lock_exhausted`.
  - Обёрнуты `insert_graph_fact` (commit=True), `upsert_bot_reply`,
    `touch_graph_facts`.
- **`services/summary_memory.py`** — `_embed_cache_store` переведён с
  `self.db.db` на публичный `write_transaction` (T-2449).
- **`services/persistent_throttling.py`** — `allow`/`reset`/`bump`/`touch`
  переведены на `write_transaction` через `_db_write` (T-2449).
- **`config/settings.py`** — kill-switch `DB_LOCK_RESILIENCE_ENABLED`
  (env-only `ClassVar`, default **ON**, вне `param_catalog`).
- **`tools/history_import/loader.py`** — `PRAGMA synchronous=NORMAL` (D3).

## 4. Доказательства (T-2452)

`tests/test_db_lock_resilience_round1025.py` (8 тестов, падают на старом коде):
PRAGMA на файловой БД; retry на `locked` → успех; исчерпание → WARNING-событие
+ счётчик; non-lock не ретраится; параллельные транзакции сериализованы
(single-writer); OFF = baseline (нет повторов); fail-open throttle-хендлера.
Тест-хук нулевого backoff (`_LOCK_BACKOFF=0`) — тесты не спят.

Контрольные прогоны: `tests/test_database.py`, `test_smart_cache.py`,
`test_persistent_throttling.py`, `test_summary_memory.py`, `test_history_loader.py`
— зелёные; полный pytest 7933 passed / 0 failed.

## 5. Наблюдаемость

- **Успех** — без изменений.
- **Успех после retry** — без отдельного лога (счётчик исчерпаний не растёт).
- **Исчерпание** — `event=database_lock_exhausted` (`op`, `attempts`,
  `chat_id`, `exc_info`) + рост `database_lock_exhausted_total()`; вызывающий
  хендлер fail-open (пользователь не блокируется). R17: без секретов/фраз.

## 6. Инварианты

- Δ DDL = 0 (нет миграций/новых таблиц; `user_version=12` не менялся).
- Δ каталога = 0 (флаг env-only `ClassVar`, в `param_catalog` не добавлен).
- `smart_cache` не изменён (только использован как образец).
