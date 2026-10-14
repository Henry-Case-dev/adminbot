# Отчёт @Reviewer — ШАГ 5, раунд 10.24, F17 `sqlite-lock-resilience-round1024`

- **Предмет:** коммит `ca40e0f` «fix(services,tests): раунд 10.24 F17 — WAL/busy_timeout/retry в smart_cache против database is locked»
- **Diff:** `config/settings.py` (+7), `services/smart_cache.py` (+199/−39), `tests/test_smart_cache.py` (+231/−…)
- **Артефакты:** `plans/features/sqlite-lock-resilience-round1024/{spec.md, ADR-1024-18.md, tasks.md}`; ТЗ `plans/current_task.md` UPD4 (стр. 281–295), прочитано без цитирования секретов/прод-данных (R17/R18)
- **Статус ревью:** T-2326 (можно закрывать)

---

## Статус

**Approved**

Реализация полностью соответствует `spec.md` и `ADR-1024-18` по всем восьми пунктам аудита: PRAGMA-паритет, bounded retry только на `locked`, явное исчерпание с counter+WARNING, kill-switch, отсутствие утечки fd, нулевые Δ DDL/Δ каталога и целостность инвариантов раунда. Все перечисленные замечания ниже — **не блокирующие** (точностная правка документации риска, унаследованный архитектурный долг, процессная гигиена). Код принят.

---

## Что проверено фактически

Полный `pytest` прогнан **на чистом коммите** `ca40e0f` в изолированном detached-worktree (основной worktree во время аудита мутировался параллельными агентами — см. Finding I1):

- `7648 passed, 1 failed` (итого **7649**).
- Единственный FAIL — `tests/test_history_cli.py::TestCliFts::test_scope_is_required`: сравнение кириллицы через cp1251-консоль в пути temp-worktree (mojibake), **к F17 не относится**; в основном репозитории тест зелёный.
- Изоляция F17: `tests/test_smart_cache.py` — `31 passed`; `TestLockResilience` отдельно — 5 прогонов по `8 passed`, флейка нет (заявленный возможный флейк не подтверждается; тесты backoff обнуляют `_LOCK_BACKOFF` monkeypatch'ем, реального сна нет).
- `git diff --check ca40e0f^ ca40e0f` — чисто; diff ограничен тремя заявленными файлами.

---

## Findings по severity

### [Medium] M1. Заявленная верхняя граница задержки математически неверна: до ~20.7 с, а не «5 с + ≤0.7 с»
- **Файл:** `services/smart_cache.py:197-232` (`_run_with_lock_retry`, `_apply_pragmas`), документарное расхождение — `plans/features/sqlite-lock-resilience-round1024/spec.md:49-50`, `ADR-1024-18.md:51`.
- **Проблема:** `PRAGMA busy_timeout=5000` оплачивается **на каждой попытке** обёртки, а не один раз. При устойчивой внешней блокировке: 1 исходная попытка + 3 повтора = 4 × 5 с на busy_timeout + backoff (0.1/0.2/0.4) ≈ **20.7 с** на одну операцию кэша. В `spec.md` §3.2 и ADR (Negative) суммарный worst-case указан как «busy_timeout (5с) + ≤0.7с», т.е. ~5.7 с — это занижение примерно в 3.5 раза.
- **Почему это важно:** это hot-path кэша, соединение одиночное (aiosqlite worker-thread), поэтому подвешенное ожидание задерживает не только свой хендлер, но и все прочие обращения к `smart_cache`. Решение владельца «лучше подождать, чем потерять» сохраняется, но заявленный бюджет ожидания должен быть честным — иначе @DevOps/on-call неверно оценят деградацию.
- **Требуемая правка (не в коде F17, а в документации/риске):** привести spec/ADR к реальной границе (`≤ _LOCK_RETRIES * _BUSY_TIMEOUT_MS + Σbackoff`), либо (по решению владельца) ввести общий дедлайн на операцию (жёсткий cap суммарного ожидания). Константы, зафиксированные спекой (`N=3`, `busy_timeout=5000`, base `0.1`), менять не требуется — код им соответствует.

### [Medium] M2. `rollback()` на общем соединении без сериализации (унаследованный долг, усилен F17)
- **Файл:** `services/smart_cache.py:226-232` (rollback в retry), `services/smart_cache.py:150-175` (общее `self._db`, без `asyncio.Lock`).
- **Проблема:** `SmartCache` — синглтон с единственным `aiosqlite.Connection` и **без** `asyncio.Lock` (в отличие от `services/database.py:510`, где `self._lock = asyncio.Lock()`). Транзакция `_write_once`/`_read_once` многостатейна и растянута по `await`, поэтому при конкурентных вызовах одного соединения возможна интерливинг-транзакция; добавленный F17 best-effort `rollback()` в этом случае откатит и чужие ещё не закоммиченные стейтменты. Вероятность низкая (aiosqlite сериализует постановку и сам `locked` приходит от внешнего writer'а), но это реальный путь потери записи кэша, который F17 делает явнее.
- **Почему это важно:** «запись не теряется» — ключевая цель фичи; на общем соединении без блокировки возможна взаимная потеря записей при исчерпании.
- **Требуемая правка:** либо защитить `_read`/`_write` (и rollback) `asyncio.Lock` по образцу `database.py:510`, либо явно зафиксировать в ADR, что `smart_cache` полагается на statement-level сериализацию aiosqlite и что rollback не задевает чужие операции. Правка сверх спеки — вынести решением @Architect (не блокирует приёмку текущего объёма).

### [Low] L1. Kill-switch OFF не «байт-в-байт» на аварийной ветке init
- **Файл:** `services/smart_cache.py:166-174`.
- **Проблема:** best-effort `close()` соединения при провале инициализации **не гейтится** флагом `SMART_CACHE_LOCK_RESILIENCE_ENABLED`. В baseline (`ca40e0f^`) при провале `_ensure_db` соединение не закрывалось (утечка fd). Формально OFF не даёт побайтово прежнее поведение — на ветке ошибки fd теперь закрывается.
- **Почему это важно:** это строгое улучшение и оно прямо требуется `spec.md` §4 п.(6) и тестом (g), т.е. противоречия со спекой нет; фиксирую как явный факт, чтобы OFF-семантику в других фичах не трактовали как «абсолютный откат всего кода F17».
- **Требуемая правка:** не требуется (документарная оговорка).

### [Low] L2. Дублирование причины в логе исчерпания
- **Файл:** `services/smart_cache.py:121-124`.
- **Проблема:** одновременно `error=%s` и `exc_info=True` — удобно для grep и для трейса, но в объёме логов дублируется причина.
- **Почему это важно:** не влияет на корректность/R17; чисто косметика наблюдаемости.
- **Требуемая правка:** не требуется.

### [Info] I1. Процессная гигиена: во время аудита основной worktree мутировал параллельными агентами
- **Файл:** репозиторий целиком.
- **Факт:** на старте аудита `git status` был «чистым» (только `plans/backlog.md`), к концу — в рабочем дереве появились правки `services/disk_retention.py`, `manage.py`, `services/param_catalog.py`, `memory_rebuild.py` и др., а HEAD сместился `ca40e0f → 07644db` (чужая F9 iter1). Из-за этого первый полный прогон поймал промежуточное (несогласованное) состояние F9: код возвращал ключ `blocked`, а тест ещё ожидал словарь без него.
- **Почему это важно:** подобные «промежуточные» состояния не должны приниматься за регресс F17; во избежание ложных выводов полный pytest F17 верифицирован в отдельном detached-worktree на точном `ca40e0f`.
- **Требуемая правка:** процессная (не код F17): агентам не писать в общий рабочий каталог одновременно; вердикты фиксировать на неизменяемом commit-ish.

---

## Контракт: чекбоксы

**1. PRAGMA-паритет** — ✅
- `services/smart_cache.py:127-135` `_apply_pragmas`: ровно `PRAGMA journal_mode=WAL` → `PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}` → `PRAGMA synchronous=NORMAL` — тот же порядок/значения, что `services/database.py:516-520`.
- `_BUSY_TIMEOUT_MS = 5000` (`:33`) — зеркало `services/database.py:48`.
- `services/database.py` **не изменён** (diff — 3 файла). Тест (a) подтверждает `wal` / `5000` / `1` на файловой БД (`tmp_path`).

**2. Bounded retry только на `locked`** — ✅
- `_is_locked` (`:105-110`): `isinstance(exc, sqlite3.OperationalError)` + `"locked" in str(exc).lower()`; `aiosqlite` ре-экспортирует `sqlite3.OperationalError` (проверено `aiosqlite/__init__.py`), прод-трейс в ТЗ — именно `sqlite3.OperationalError`.
- `_LOCK_RETRIES = 3` (`:34`), backoff `_LOCK_BACKOFF * 2**(attempt-1)` → `0.1 / 0.2 / 0.4` (`:232`).
- rollback перед повтором best-effort, ошибки глушатся (`:226-231`).
- не-lock исключение не ретраится — `raise` (`:220-221`); тест `test_non_lock_error_not_retried` (`attempts == 1`).

**3. Исчерпание — не тишина** — ✅
- `_note_lock_exhausted` (`:113-124`): `event=smart_cache_lock_exhausted`, `op`, MD5-`key`, `attempts=` (=4: 1+3), `error=<текст>`, `exc_info=True`; инкремент `_lock_exhausted_total`.
- fail-open сохранён: `on_exhausted=lambda exc: None` → `_read` отдаёт `None` (`:259`), `_write` — no-op (`:295`).
- счётчик `smart_cache_lock_exhausted_total()` (`:91-96`), Δ DDL = 0.
- R17: payload/сырой ввод не логируются; тест `test_write_lock_exhausted_is_explicit` прямо проверяет отсутствие payload в `caplog`.

**4. Kill-switch** — ✅ (с оговоркой L1)
- `config/settings.py:884-885` — env-only `ClassVar[bool]`, default **ON**; в `param_catalog` отсутствует (grep по всему коду — только settings/smart_cache/тесты) → Δ каталога = 0.
- OFF: `_run_with_lock_retry` → ровно одна попытка (`:213-214`); `_apply_pragmas` не вызывается (`:157`). Тесты `test_flag_off_no_pragmas` (journal_mode ≠ wal) и `test_flag_off_single_attempt` (`attempts == 1`, прежний WARNING `set failed`).

**5. Нет утечки fd при провале init** — ✅
- `_ensure_db` (`:151-175`): соединение в локальной переменной, `self._db` присваивается только после успешного `CREATE TABLE`+`commit`; в `except` — best-effort `await db.close()`. Тест `test_init_failure_closes_connection` подтверждает `_connection is None` и возможность повторной инициализации.

**6. Инварианты** — ✅
- Δ DDL = 0 (только неизменённый `CREATE TABLE IF NOT EXISTS smart_cache`), Δ каталога = 0, новых файлов нет.
- `parse_mode=None` / egress / physical-two-call / R16-аддитивность — F17 не касается отправки и схем API.
- R17/R18 — в коде только MD5-ключ и класс/текст ошибки; секреты не цитируются.
- F1/F2/F7/F8/F9/F12/F20/F21/F22 — полный прогон на `ca40e0f` зелёный (кроме внешнего encoding-флейка `test_history_cli`).

**7. Тесты** — ✅
- (a) PRAGMA на файловой БД; (b) retry-успех с фактической проверкой сохранённой записи; (c) исчерпание write/read (counter + event + fail-open + R17); (e) OFF (PRAGMA и retry); (f) не-lock; (g) init-fail/fd.
- Не тавтологичны: (b) после retry читает значение через реальное соединение; (c) проверяет `attempts`, счётчик и текст события; (f) проверяет не-ретрай через реально брошенную не-lock ошибку.
- (d) регресс hit/miss/expired/LRU/dezup — покрыт существующими тестами `TestSmartCacheStorage`/`TestDirectDedupCache` (без изменений).
- Незначительный пробел: ветка `expired → DELETE → commit` внутри `_read_once` не имеет отдельного lock-теста (покрыта логикой `_read`), некритично.

**8. Полный pytest (чистый коммит)** — ✅
- `ca40e0f` в изолированном worktree: **7648 passed / 1 failed**, единственный FAIL — консольный encoding-артефакт `test_history_cli` (не F17), в основном репо зелёный. Итого 7649 тестов — совпадает с заявленным объёмом.
- Флейк `TestLockResilience` в изоляции: 5/5 прогонов зелёные.

---

## Итог по T-2326

Ревью пройдено. `services/smart_cache.py` действительно использует WAL/`busy_timeout=5000`/`synchronous=NORMAL`; retry конечен и только на `locked`; исчерпание видно в логе и счётчике (не тихий no-op); R17 соблюдён. Замечания M1/M2 — к обновлению документации риска и в архитектурный backlog (сериализация общего соединения), не к возврату кода. T-2326 можно отмечать `[x]`.

`**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.`
