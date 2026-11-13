# I1 — аддендум к binding: исправление F1/F2/F3 (кандидат `76d60678`)

**Код+тесты:** `76d6067893238cb71e66cca73470e82c32762737` (ветка `smart/i1-journal`).
**База:** production `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199).
**Предыдущий кандидат:** `a3841613` (binding `binding-i1-a3841613.md`).
**Ревью:** `review-i1-a3841613.md` — Needs Fixes (F1 блокер, F2/F3 малые).
Область та же: `services/meme_initiative.py`, `tests/test_evol014_meme_initiative.py`.
Схема/DDL/спул-формат/новые таблицы — не менялись; production не трогался.

---

## F1 (блокер) — отказ writer'а оставлял открытую транзакцию

**Причина.** `_attempt_journal_writer._write` в не-owner ветке не откатывал
неудачный `INSERT`. Неявный `BEGIN` оставался на общем aiosqlite-соединении,
единственный писатель держал write-lock, и соседний путь (`ledger.reserve()` на
своём соединении) падал по `busy_timeout` → `quota_store_error` — класс
исходного production-инцидента на ветке отказа.

**Исправление.** Под уже взятым `serialized()` при отказе выполняется
`conn.rollback()` (контракт `DatabaseService.write_transaction`); ошибка
отката логируется отдельно, исходное исключение пробрасывается. В
reentrant-ветке (транзакцией владеет вызывающая задача) откат НЕ делается —
чужая транзакция не трогается. Идемпотентность (`INSERT OR IGNORE`) и
durable-спул сохранены.

**Probe `probe_ledger_blocked` (таблица журнала удалена → writer падает):**

| | `a3841613` (до) | `76d60678` (после) |
|---|---|---|
| `app_in_transaction` после отказа | **True** | **False** |
| `ledger.reserve()` | **False / quota_store_error, 5.53 s** | **True / ok, 0.02 s** |
| строка в спуле | да | да (durable-путь не изменился) |

Файлы: `runs/.../probe-c81282c302/f1-before.txt`, `rework-f1.txt`.

## F2 — неверный `busy_timeout_ms` в логе writer-пути

**Причина.** Лог печатал константу файлового пути (250), хотя writer ждёт
`busy_timeout` соединения приложения (5000) — при инциденте это вводит в
заблуждение.

**Исправление.** Таймаут берётся у фактического пути: writer читает
`PRAGMA busy_timeout` своего соединения (при недоступности — константа
приложения); файловый путь сообщает свои 250 мс.

**Probe реального чужого `BEGIN IMMEDIATE`** (`probe_busy_case`):

| | до | после |
|---|---|---|
| лог | `busy_timeout_ms=250`, `elapsed_ms=5485` | **`busy_timeout_ms=5000`, `elapsed_ms=5484`** |
| ожидание | 5.49 s | 5.48 s, петля жива (89 тиков) |
| `app_in_transaction` | False | False |
| после освобождения | запись/дренч OK | WRITABLE, `journal_ids=['busy-1','foreign']` |

Файлы: `f2-busy-after.txt`.

## F3 — durable-тест на настоящий duplicate-drain

Добавлен `test_spool_drain_deduplicates_already_written_attempt_id`: тот же
`attempt_id` уже лежит в журнале и снова во спуле (сбой между вставкой и
удалением файла) вместе с новой строкой. Требование: спул пуст, дубля нет,
новая строка записана.

Мутация `INSERT OR IGNORE` → `INSERT`: **FAILED**
(`спул обязан опустеть при дубликате`, `UNIQUE constraint failed`), прежний
`test_spool_drain_is_idempotent_and_keeps_existing_rows` при этой мутации
оставался зелёным — пробел закрыт новым тестом.

## Мутации (файл восстановлен после каждой, worktree чист)

| мутация | ожидание | наблюдение на `76d60678` |
|---|---|---|
| sync `ATTEMPT_JOURNAL_BUSY_TIMEOUT_MS` 250 → 5000 | red | **FAILED**: `16.59 s`, `SQLITE_BUSY` (исходный дефект) |
| обойти `serialized()` в `_write` | red | **FAILED**: `test_journal_write_waits_for_writer_through_single_writer` |
| `INSERT OR IGNORE` → `INSERT` | red | **FAILED**: новый dedup-тест (спул не опустошён) |

Выводы: `mut-sync5000.txt`, `mut-noserialized.txt`, `mut-plaininsert.txt`.

## Прогоны на коммите `76d60678`

| набор | результат |
|---|---|
| 7 новых тестов (5 прежних + F1-регрессия + dedup-drain) | **7 passed** |
| `tests/test_meme_init_diagnostics.py` | **44 passed** |
| `tests/test_evol014_meme_initiative.py` | **1 failed / 67 passed** |
| вместе | **1 failed / 111 passed** (29.62 s; 32.25 s на финальном прогоне) |

Единственное падение — pre-existing
`test_factory_prompt_is_exact_literal_and_registered`
(`services.prompt_readback.RESOURCE_KIND_PROMPT` не зарегистрирован), то же на
базе `d20a7f73` (BACKLOG, не кандидатом).

Обязательные probe: `probe_ledger_blocked` → PASS без лока (0.02 s),
`probe_busy_case` → PASS с честным `busy_timeout_ms=5000`.

## Новые тесты (итог — 7)

1. `test_blocked_journal_write_is_bounded_and_recovers`
2. `test_journal_write_waits_for_writer_through_single_writer`
3. `test_finish_async_writes_attempt_rows_through_single_writer`
4. `test_spool_drain_is_idempotent_and_keeps_existing_rows`
5. `test_journal_failure_logs_real_sqlite_detail_without_row_content`
6. **`test_writer_failure_rolls_back_and_keeps_other_writers_moving`** (F1+F2):
   отказ writer'а → `in_transaction False` (тест), чужой `BEGIN IMMEDIATE`
   укладывается в <1 с, лог несёт `busy_timeout_ms=5000` и `no such table`,
   после восстановления носителя — ровно одна строка.
7. **`test_spool_drain_deduplicates_already_written_attempt_id`** (F3).

## Совместимость и ограничения

- `record_attempt_async` при чужом локе ждёт до `busy_timeout` приложения
  (5 с), но **асинхронно**: петля жива (89 тиков), затем durable-спул
  (наблюдение ревьюера подтверждено и принято как ожидаемое).
- `_retry_unpersisted` в состоянии «оба носителя мертвы» остаётся pre-existing
  структурой (до 200 строк × 250 мс) — backlog, кандидатом не расширялся.
- Post-deploy подтверждение: следующий реальный контеншн даёт либо успешную
  запись единым писателем, либо `attempt spooled` с корректными
  `busy_timeout_ms=5000` и `error=... [SQLITE_BUSY]`.

## Хаускипинг

- Артефакты реворка в `runs/.../probe-c81282c302/`: `f1-before.txt`,
  `rework-f1.txt`, `f2-busy-after.txt`, `mut-sync5000.txt`,
  `mut-noserialized.txt`, `mut-plaininsert.txt`, `rework-final-suites.txt`,
  `rework-suites.txt`, `rework-head.txt` — нужны ревьюеру для re-check.
- Probe Reviewера `probe-87730469e7` не изменялся (мои копии — с суффиксом `_f1`/`_f2`).
- Кандидат-worktree остаётся живым; ревью-файл `review-i1-a3841613.md` не мой и
  не коммитился.
