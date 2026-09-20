# Задачи: sqlite-lock-resilience-round1024

> **Раунд 10.24 (UPD4-C)** · Приоритет **P1** · Severity **Medium** · Шаг 1 @PM · Тип: backend/инфраструктура БД
> **ТЗ:** `plans/current_task.md`, секция **UPD4** (строки 281–295). Файл untracked; секреты не цитировать (R17/R18).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`. Отчёт @Memory: `upd4-live-bug-clusters-round1024` (кластер C).
> **Прод-логи:** `services.smart_cache | smart cache: set failed | sqlite3.OperationalError: database is locked`.

## Цель
`smart_cache` открывает **собственное** aiosqlite-соединение без `PRAGMA journal_mode=WAL`/`busy_timeout`/`synchronous` и без retry → при конкуренции с основным соединением ловит `database is locked`, пишет WARNING и **молча теряет запись** (no-op). Привести соединение к паритету с `services/database.py` и добавить bounded retry.

## Что уже есть (координаты)
- Открытие соединения: `services/smart_cache.py:89-103` (`_ensure_db`: `aiosqlite.connect` + `row_factory`, **без PRAGMA**).
- Запись (при блокировке → WARNING + no-op): `services/smart_cache.py:148-174` (`_write`, `except Exception: logger.warning("smart cache: set failed")`).
- Чтение: `services/smart_cache.py:125-146` (`_read`).
- Эталон-паритет: `services/database.py:514-520` (`PRAGMA journal_mode=WAL`, `busy_timeout = _BUSY_TIMEOUT_MS`, `synchronous=NORMAL`).
- Горячие ключи TTL/лимитов: `services/smart_cache.py:105-123` (`_sweep_ttl`, `_active`).
- Логирование внешних причин: `logging-infra-round1024` (T-2197/2198).

## Задачи
- [x] **T-2322** [@Architect] ADR/политика: устойчивость `smart_cache` к `database is locked` — WAL + `busy_timeout` + `synchronous=NORMAL` (паритет с `database.py:514-520`), **bounded retry/backoff** на `_write`/`_read`; семантика «лучше подождать, чем потерять запись», поведение при исчерпании попыток (WARNING + счётчик, не тихий no-op).
- [x] **T-2323** [@Builder] `services/smart_cache.py:89-103`: при открытии соединения применить `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout = <N>`, `PRAGMA synchronous=NORMAL` (значения — по образцу `database.py`).
- [x] **T-2324** [@Builder] `services/smart_cache.py:148-174` (и `_read`): bounded retry с backoff при `OperationalError: database is locked`; при исчерпании — WARNING с реальной причиной + счётчик (не молчание); не ронять вызывающий хендлер (fail-open сохраняется как **последний** рубеж).
- [x] **T-2325** [@Builder] Тесты: (a) PRAGMA реально применены к соединению (WAL/busy_timeout/synchronous); (b) имитация блокировки → retry завершается успехом; (c) исчерпание → WARNING с причиной, не тихий no-op; (d) нет регресса hit/miss/expired и LRU.
- [ ] **T-2326** [@Reviewer] Ревью: соединение действительно WAL, retry ограничен (нет бесконечного ожидания), fail-open не маскирует проблему, R17 (в логах нет секретов/ключей кэша сверх допустимого).
- [ ] **T-2327** [@DevOps] Деплой + live: в прод-логах нет `smart cache: set failed ... database is locked`; при параллельной нагрузке записи кэша не теряются; отчёт.

## Критерии приёмки
- Соединение `smart_cache` использует WAL/busy_timeout/synchronous (паритет с основным соединением).
- При кратковременной блокировке запись **не теряется** (retry); при исчерпании — явный WARNING с причиной.
- В прод-логах исчезло `database is locked` от `smart_cache`.
- Полный pytest — 0 failed; `git diff --check` чист.

## Риски
- **R1 (Medium):** долгий retry подвешивает hot-path кэша → bounded попытки/таймаут, fail-open последним.
- **R2 (Medium):** WAL/`synchronous` на отдельном соединении конфликтуют с основным writer → значения по образцу `database.py`, тест (a).
- **R3 (Low):** маскирование проблемы под «успех» → тест (c) требует явного WARNING при исчерпании.

## Зависимости / ступени
- Зависит от: `logging-infra-round1024` (T-2197/2198) — причинные логи.
- Ступень общих файлов: `services/smart_cache.py` — **только F17** (эксклюзив); переиспользует константы/подход `services/database.py` (не редактируя его).
- Feature flag: `SMART_CACHE_LOCK_RESILIENCE_ENABLED` (env-only `ClassVar`, **default ON**); поэтапная раскатка internal→10%→50%→100% **не требуется**.
- Откат: флаг OFF (возврат к прежнему поведению без PRAGMA/retry) / `git revert`; **Δ DDL = 0**, Δ каталога = 0.
