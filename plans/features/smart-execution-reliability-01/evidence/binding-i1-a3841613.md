# SMART-EXECUTION-RELIABILITY-01 — I1: журнал попыток (`OperationalError` / spool)

**Кандидат (код+тесты):** `a38416137bea76c139dd9a4ea21a4273cd81230c`
(ветка `smart/i1-journal`), short — `a3841613`.
**База:** production `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199).
**Область:** `services/meme_initiative.py`, `tests/test_evol014_meme_initiative.py`.
Схема/DDL/миграции/таблицы/спул-формат не менялись; новых таблиц, очередей и
второго журнала нет. Production не менялся: только read-only чтение журнала
systemd и `mode=ro` выборка из БД.

---

## 1. Что зафиксировано в production (recon + две read-only проверки)

Эпизоды 13.11.2026 UTC: 02:26, 06:13, 06:28, 09:36–09:37, 09:47, 10:38,
11:36–11:38 — каждый `[meme] attempt spooled (journal unavailable)
error=OperationalError`, затем `attempt spool not drained failed=1..3`.

Состояние носителей: таблица `meme_initiative_attempt` жива (28 678 строк,
`MAX(ts)=2026-11-13T12:31:21Z`), `quick_check=ok`, WAL, один процесс (3
handle), права и диск в порядке (32 ГБ), spool-файл на момент проверки
отсутствовал.

**Новое (этот кандидат, read-only).** Обе спулёные строки впоследствии легли
в журнал — перенос работает, потерь нет:

```
rows=2
('266639345caf473c93d258857f7ba108', 1794562589, 'considered', 'passed', '')
('bf20677a446a49f496b6f7b292458b48', 1794562589, 'skipped', 'skipped', 'cooldown_active')
```

`ts=1794562589` = 2026-11-13 09:36:29 UTC — ровно момент первого эпизода.
То есть дефект — не потеря и не «битая схема», а повторяющаяся заморозка
записи и падение в спул.

## 2. Точная причина (доказана)

### 2.1 Тайминги журнала (journalctl, окно 09:36:15–09:37:10)

| событие | время | дельта |
|---|---|---|
| `WATCHDOG_SWEEP` (последний лог перед паузой) | 09:36:29.454 | — |
| `[meme] attempt spooled … error=OperationalError` | 09:36:44.601 | **15.147 s** |
| `[meme] attempt spool not drained … failed=1` | 09:36:49.612 | **5.011 s** |
| `[meme] attempt spooled … second row` | 09:37:04.743 | **15.131 s** |
| `VisionMediaWorker._tick` (каждые 5 с) снова в логе | 09:37:04.750 | тиков не было 38.0 s |

15.147 s = 3 × `busy_timeout` (5.000) + 0.02 + 0.08 (паузы между попытками) —
ровно три попытки `_insert_attempt` в `record_attempt` (`ATTEMPT_WRITE_ATTEMPTS=3`).
5.011 s — один `INSERT` внутри переноса спула. Ещё 15.131 s — следующая строка.
Ожидание синхронное (`sqlite3`) и идёт в петле событий: тики Vision (каждые
5 с) не логировались 38 с — бот был заморожен.

### 2.2 Матрица причин на реальном SQLite (без подмен исключений)

`probe_causes.py` (база `d20a7f73`): один и тот же `_insert_attempt`, разные
условия.

| условие | класс / текст | код | длительность |
|---|---|---|---|
| открытая транзакция другого соединения | `OperationalError: database is locked` | SQLITE_BUSY (5) | **5.500 s** |
| таблицы нет (schema mismatch) | `OperationalError: no such table: meme_initiative_attempt` | SQLITE_ERROR (1) | 0.000 s |
| файл только для чтения | `OperationalError: attempt to write a readonly database` | SQLITE_READONLY (8) | 0.000 s |
| журнал свободен (контроль) | — | — | 0.000 s |

Схема, права и диск дают **мгновенную** ошибку и были бы детерминированными
(таблица принимала 28 678 строк, включая 12:31 того же дня). Наблюдаемая
подпись «три полных ожидания по 5 с» соответствует только `SQLITE_BUSY`.

### 2.3 Механизм

Журнал живёт в том же файле, что данные бота. `_insert_attempt` открывал
**своё** соединение и не участвовал в single-writer дисциплине
`DatabaseService`: `write_transaction` держит `_lock` и неявный `BEGIN` на всё
время `await op(conn)` (включая сетевые ожидания внутри `op`), а журнал в это
время упирался в `busy_timeout`. Из-за синхронного ожидания в петле держатель
транзакции не мог даже выполнить коммит — окно только удлинялось.

**Чего этим НЕ доказано (честно):** какой именно код-путь держал транзакцию в
каждый эпизод 13.11 — в журнале этого не было. Новая диагностика теперь
печатает тип/текст/код SQLite, операцию, таблицу, путь, `busy_timeout_ms` и
`elapsed_ms`, поэтому следующий случай атрибутируется по логу.

## 3. Что исправлено (минимально, в существующем writer/transaction path)

1. **Горячий путь через единого писателя.** `_consider_once` (все
   `skipped`/`_cancel`), `_deliver_deferred_row` пишут строки через
   `record_attempt_async` → `DatabaseService.serialized()` на соединении
   приложения. Тот же `INSERT OR IGNORE` (`_ATTEMPT_INSERT_SQL`/
   `_attempt_params`) в ту же таблицу. Ожидание чужой транзакции —
   асинхронное; после коммита строка попадает в журнал, а не в спул.
   Синхронный `_finish` сохранён для отмены (`record_run_interrupted`) и тестов.
2. **Синхронный путь ограничен.** `ATTEMPT_JOURNAL_BUSY_TIMEOUT_MS = 250`
   (было 5000). Худшее время — 3 × 250 мс + паузы ≈ 0.85 с; строка уходит в
   durable-спул. Probe на базе 5.500 s → после 0.375 s.
3. **Перенос спула останавливается на первой неудаче** (раньше — до 200
   строк × 5 с в петле). Остаток файла переписывается целиком, идемпотентность
   по `attempt_id`, ничего не удаляется.
4. **Диагностика.** Лог отказа несёт
   `error=<тип>: <текст SQLite> [<код>] | op=INSERT OR IGNORE | table=... |
   db=... | busy_timeout_ms=... | elapsed_ms=...`; текст ограничен 160 символами
   и приведён к одной строке; содержимое попытки (`detail`) не печатается.
   Молчаливое проглатывание ошибки чтения журнала в `attempts()` убрано.
5. Не менялись: таблица, спул, реестр удержания (`_UNPERSISTED_BY_PATH`),
   `SPOOL_FIELDS`, merge в `attempts()`, бронь/квота, схема, формат строк.

## 4. Acceptance по пунктам §I1

| требование владельца | доказательство |
|---|---|
| конкретная операция / таблица / путь / исключение / схема / соединение / блокировка / права / диск / writer path | §2.1–2.3 + probe (SQLITE_BUSY 5.5 s vs 0.000 s у schema/readonly); операция, таблица, путь, `busy_timeout` теперь в логе |
| не предполагать лок — доказать | матрица реальных причин: только лок даёт 5-секундное ожидание, совпадающее с production (15.147 s = 3×5 s) |
| восстановить нормальную запись в основной журнал | горячий путь пишет единым писателем: `test_journal_write_waits_for_writer_through_single_writer`, `test_finish_async_writes_attempt_rows_through_single_writer` (строки в таблице, спул не создан) |
| корректное опустошение существующего spool | `test_spool_drain_is_idempotent_and_keeps_existing_rows`, `test_blocked_journal_write_is_bounded_and_recovers`; production: обе спулёные строки найдены в таблице |
| идемпотентность, без потерь и дублей | двойной прогон переноса → каждая строка ровно один раз; `INSERT OR IGNORE` по `attempt_id` |
| корректное отображение последней попытки | `attempts(chat_id, limit=1)` возвращает перенесённую строку (`test_blocked_journal_write_is_bounded_and_recovers`, `test_finish_async_...`) |
| не создавать четвёртый fallback / новый журнал / хранилище | нет: те же таблица + спул + удержание; writer — штатный `DatabaseService.serialized()` |
| сохранить накопленные записи, не чистить spool/старые строки | тест сравнивает все поля накопленных строк до/после переноса |
| не увеличивать вероятность инициативы | код вероятности/триггера не тронут |
| проверить полный путь записи/временного отказа/восстановления существующим контролируемым способом | реальный SQLite + реальная транзакция + реальный `DatabaseService`; RED на базе 16.64 s, GREEN после |

## 5. Тесты

Новые (5, `TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-14-SMART-EXECUTION-RELIABILITY-01`):

1. `test_blocked_journal_write_is_bounded_and_recovers` — открытая транзакция
   другого соединения: синхронная запись ограничена по времени, строка в спуле,
   видна читателю, после коммита переносится ровно один раз, старые строки целы.
2. `test_journal_write_waits_for_writer_through_single_writer` — реальный
   `DatabaseService` держит открытую транзакцию: `record_attempt_async` ждёт её,
   петля событий продолжает тикать (`ticks >= 10`), после коммита строка в
   журнале, спула нет.
3. `test_finish_async_writes_attempt_rows_through_single_writer` — связка
   «итог попытки → единый писатель → журнал»: строки этапа и терминала, режим
   попытки читается как `auto`, спула нет.
4. `test_spool_drain_is_idempotent_and_keeps_existing_rows` — двойной перенос:
   ни дублей, ни потерь, накопленные строки побайтово равны прежним.
5. `test_journal_failure_logs_real_sqlite_detail_without_row_content` — реальная
   ошибка (`no such table`): в логе тип, текст SQLite, операция, таблица,
   `busy_timeout_ms`, `elapsed_ms`; `detail` строки в лог не попадает.

**RED на базе `d20a7f73`:** `test_blocked_journal_write_is_bounded_and_recovers`
— `AssertionError: запись журнала заморозила вызывающего: 16.64s`, в логе
`error=OperationalError` (только имя класса). Тот же probe: 5.500 s vs 0.375 s
после исправления.
**GREEN после:** 5/5 новых тестов.

**Focused-серии** (`python -m pytest`, venv `C:\Code\Python\adminbot\.venv\Scripts\python.exe`):

| набор | база `d20a7f73` | кандидат `a3841613` |
|---|---|---|
| 13 файлов (meme/initiative/publication/journal/DB) | 5 failed / 448 passed | **5 failed / 452 passed** |
| 9 доп. файлов (initiative speech/asap8/soul1/publication/qnd/evol016) | — | **97 passed** |

Те же 5 падений на базе и на кандидате (pre-existing, BACKLOG):

- `tests/test_evol014_meme_initiative.py::test_factory_prompt_is_exact_literal_and_registered`
  (`services.prompt_readback.RESOURCE_KIND_PROMPT` не зарегистрирован);
- `tests/test_initiative_coordination.py::test_act_on_opportunity_conflict_defers_to_intent`
- `tests/test_initiative_coordination.py::test_evaluate_phase_precheck_blocks_before_llm`
- `tests/test_initiative_coordination.py::test_t1_nostalgia_delegated_refusal_sends_nothing`
- `tests/test_initiative_coordination.py::test_t5_every_text_send_site_passes_publish_guard`

## 6. Конфигурация

| настройка | значение | источник |
|---|---|---|
| `ATTEMPT_JOURNAL_BUSY_TIMEOUT_MS` | `250` (было 5000) | константа модуля, новый дефолт |
| `JOURNAL_BUSY_TIMEOUT_MS` | `5000` (паритет для брони/чтений) | константа модуля |
| `ATTEMPT_WRITE_ATTEMPTS` / `ATTEMPT_WRITE_DELAYS` | `3` / `(0.02, 0.08)` | без изменений |
| `ATTEMPT_SPOOL_BATCH` / `_MAX_ROWS` / `_MAX_BATCHES` | `200` / `500` / `20` | без изменений |
| env/фича-флаги | не добавлялись | — |

Прод-значения этих констант совпадут с кандидатом после деплоя (константы, не
чатовые настройки); пользовательские настройки/override не затрагиваются.

## 7. Остаточные риски / что не доказано

- Конкретный держатель транзакции в эпизодах 13.11 не восстановим задним
  числом; новая строка лога даёт точную причину и длительность следующего
  случая (атрибуция по `op`/`error` и времени).
- `record_run_interrupted` (путь отмены) остаётся синхронным: одна строка,
  худшее время ≈0.85 с, затем durable-спул.
- Post-deploy: при следующем реальном контеншне ожидается либо успешная запись
  единым писателем, либо строка `attempt spooled` с точным текстом SQLite —
  это и будет live-подтверждением причины.
- Фоновая конкуренция за писателя не исчезла (она свойство одного файла БД);
  журнал теперь не платит за неё ни потерей, ни 15-секундной заморозкой.

## 8. Хаускипинг

- Probe-прогоны и артефакты: `WorkspaceData/runs/.../probe-c81282c302/`
  (`probe_causes.py`, `base-causes.txt`, `fixed-causes.txt`,
  `prod_attempt_check.py`, `prod-spooled-rows.txt`, `base-red-test.txt`,
  `focused-full.txt`, `extra-fix.txt`) — сохранены как доказательства этого
  кандидата до ревью.
- RED-прогон делался в отдельном checkout базы `d20a7f73` (короткоживущий,
  уже не нужен: воспроизводится `git checkout d20a7f73` + тот же тест);
  вывод снят в `base-red-test.txt`.
- Кандидат-ветка `smart/i1-journal`, worktree
  `.../smart-execution-reliability-01-45d7d5f19c3b-eef05388` остаётся живым для
  ревьюера (это сам кандидат).
