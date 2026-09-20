# spec.md — F17 `sqlite-lock-resilience-round1024` (устойчивость smart_cache к `database is locked`)

> Раунд 10.24 (UPD4-C) · Приоритет **P1** · Severity **Medium** · ADR: **ADR-1024-18**
> ТЗ: `plans/current_task.md` UPD4 (стр. 281–295). Файл untracked; секреты/креды не цитировать (R17/R18).
> Baseline: HEAD `00eab85`; прод `4314ea4`; pytest 7424/0; SQLite `v12`; каталог REGISTRY 457 / GROUPS 96 / `_TAB_BY_GROUP` 94.
> Задачи: T-2322…T-2327 (`tasks.md`).
> Секреты в этом документе не приводятся; ключ кэша в примерах — MD5-хэш (R17-safe), payload/ввод пользователя не логируются.

## 1. Цель

`SmartCache` открывает **собственное** соединение к той же SQLite-БД, что и основное `Database`, но **без** настроек `WAL` / `busy_timeout` / `synchronous` и **без** повторов. При конкуренции с основным writer'ом запись ловит `sqlite3.OperationalError: database is locked`, пишет WARNING и делает **no-op** — запись молча теряется (кэш не сохраняется).

Цель фичи: привести настройки этого соединения к **паритету** с основным (`services/database.py:514-520`) и добавить **ограниченный (bounded) retry** при блокировке, чтобы:

1. кратковременная блокировка → запись/чтение **не теряется** (ждём и повторяем);
2. исчерпание попыток → **явный** WARNING с реальной причиной + счётчик (**не тихий** no-op);
3. поведение при **успехе** остаётся байт-в-байт прежним (те же возвраты, те же INFO-логи `hit/miss/expired/set`);
4. fail-open сохраняется как **последний** рубеж (кэш по-прежнему НЕ роняет хендлер).

## 2. Что уже есть (координаты)

| Что | Где | Замечание |
|---|---|---|
| Открытие соединения **без PRAGMA** | `services/smart_cache.py:89-103` (`_ensure_db`) | `aiosqlite.connect` + `row_factory` + `CREATE TABLE IF NOT EXISTS` |
| Запись (при блокировке → WARNING + no-op) | `services/smart_cache.py:148-174` (`_write`) | `except Exception: logger.warning("smart cache: set failed | key=%s", key, exc_info=True)` |
| Чтение | `services/smart_cache.py:125-146` (`_read`) | сбой → WARNING + `None` (miss), fail-open |
| Ленивая чистка TTL / `_active` | `services/smart_cache.py:105-123` | рубильники решают, какие TTL активны |
| Синглтон и shutdown | `services/smart_cache.py:215-231` | `get_smart_cache()` / `close_smart_cache()` (close в `bot.py:on_shutdown`) |
| **Эталон паритета** | `services/database.py:514-520` | `PRAGMA journal_mode=WAL` → `PRAGMA busy_timeout = _BUSY_TIMEOUT_MS` → `PRAGMA synchronous=NORMAL` |
| Значение таймаута | `services/database.py:48` | `_BUSY_TIMEOUT_MS = 5000` (R46-8) |
| Прецедент bounded-retry на `locked` | `services/memory_rebuild.py:69-72, 92-111` | локальные `_LOCK_RETRIES=3`, `_LOCK_BACKOFF=0.1`, проверка `"locked" in str(exc).lower()`, экспоненциальный backoff, `asyncio.sleep` |
| Прецедент «точка паритета вне основного модуля» | `services/database.py:589-594` (`initialize_retention`) | другой клиент БД сам применяет те же PRAGMA (не редактируя `initialize`) |
| Тест-хук нулевого backoff | `services/llm_client.py:604` (`backoff_base == 0`) | образец для тестов retry без сна |
| Формат структурированных лог-событий | `services/external_log.py` (F2 `logging-infra-round1024`) | соглашение `event=...`; жёсткой зависимости нет |

**Инвариант владельца (UPD4-C):** *«лучше подождать, чем потерять запись»*, но ожидание **ограничено**; тихая потеря недопустима.

## 3. Требуемое поведение

### 3.1. Паритет настроек соединения (при включённом флаге)
При первом открытии соединения (`_ensure_db`) применяются ровно те же настройки и в том же порядке, что и в `services/database.py:516-520`:
`PRAGMA journal_mode=WAL` → `PRAGMA busy_timeout = 5000` → `PRAGMA synchronous=NORMAL`.
Значения — **зеркало** `database.py` (не новsключаемые env-ключи в этом раунде). `journal_mode=WAL` — свойство БД (уже активно основным соединением), поэтому повторное применение безвредно.

### 3.2. Bounded retry только на блокировку
- Повторяются **только** ошибки блокировки: `OperationalError`, у которой в тексте есть `locked` (как в `memory_rebuild._guarded_delete`). Прочие исключения — прежнее поведение без повторов.
- Повторяется **вся транзакция** операции: для `_write` — `DELETE(истёкшие) → INSERT OR REPLACE → COUNT → trim → commit`; для `_read` — `SELECT` (и `DELETE` + `commit` на ветке `expired`).
- Перед повтором — **best-effort `rollback`** (ошибки rollback игнорируются), чтобы частично применённая транзакция не «отравила» повтор.
- Ограничение: не более `N` повторов с экспоненциальным backoff. Значения — как в прецеденте: `N = 3`, база `0.1с` → паузы `0.1 / 0.2 / 0.4с`. Суммарно к `busy_timeout` (5с) добавляется ≤0.7с на операцию — **конечно** и мало́.
- `busy_timeout` (5с) + retry: сначала SQLite ждёт на своём уровне, затем — наш bounded-retry для случаев, превысивших таймаут.

### 3.3. Исчерпание попыток — не тишина
- `_read`: как и раньше, возвращает `None` (miss) — fail-open. Но логирует **структурированный WARNING** `event=smart_cache_lock_exhausted` с реальной причиной (`exc_info`), `key` (MD5, R17-safe) и числом попыток, и инкрементирует счётчик.
- `_write`: как и раньше, не бросает исключение вызывающему хендлеру (fail-open/no-op). Но логирует тот же `event=smart_cache_lock_exhausted` с причиной/`key`/попытками и инкрементирует счётчик.
- In-process счётчик доступен для наблюдения (грепы/алерты), Δ DDL = 0 (PG-таблиц/миграций нет — парадигма раунда «метрика = лог + счётчик»).

### 3.4. Неизменность при успехе
- Возвраты `get/get_dedup/set/set_dedup` — без изменений.
- INFO-логи `hit | miss | expired | set` — без изменений (те же формат и условия).
- Все проверки рубильников (`_active`, `_sweep_ttl`, hot-config) — без изменений.
- PRAGMA/retry-код не выполняется на успешном быстром пути (нулевая добавленная задержка; суммарный оверхед — только сами PRAGMA при инициализации соединения).
- `parse_mode=None` и текстовая доставка вообще не затрагиваются (фича не касается egress/отправки).

## 4. Изменения по файлам

| Файл | Владелец | Изменение |
|---|---|---|
| `services/smart_cache.py` | **F17 (эксклюзив)** | (1) локальные константы retry/pragma; (2) приватный помощник применения PRAGMA в `_ensure_db` (под флагом); (3) приватный помощник `is_locked(exc)`; (4) обёртка `_read`/`_write` в bounded-retry; (5) структурированный WARNING + счётчик при исчерпании; (6) best-effort `close()` соединения при провале инициализации (утечка fd) |
| `config/settings.py` | F17 | один env-only `ClassVar[bool]` `SMART_CACHE_LOCK_RESILIENCE_ENABLED` (default ON) рядом с блоком Smart Cache (`:845-852`); **в `param_catalog` НЕ добавляется** |

**НЕ меняется:** `services/database.py` (эталон читаем, не редактируем), `bot.py`, `web/**`, каталог (`param_catalog.py`), схема БД. Новых файлов нет.

## 5. Контракты

### 5.1. Константы (локальные, зеркало прецедентов)
```python
# services/smart_cache.py
_BUSY_TIMEOUT_MS = 5000     # зеркало services/database.py:48
_LOCK_RETRIES = 3           # зеркало services/memory_rebuild.py:71
_LOCK_BACKOFF = 0.1         # зеркало services/memory_rebuild.py:72
```

### 5.2. Приватные помощники (внутренний контракт модуля)
```python
async def _apply_pragmas(db: aiosqlite.Connection) -> None
    # WAL → busy_timeout=_BUSY_TIMEOUT_MS → synchronous=NORMAL (порядок как database.py:516-520)

def _is_locked(exc: BaseException) -> bool
    # True только для OperationalError с "locked" в тексте; прочее → False

async def _run_with_lock_retry(op, *, on_exhausted) -> Any
    # op — awaitable-фабрика всей транзакции; N повторов + backoff; rollback перед повтором;
    # при исчерпании → on_exhausted(exc) и проброс/возврат по семантике вызывающего
```

### 5.3. Флаг
```python
# config/settings.py (env-only ClassVar, default ON, вне param_catalog)
SMART_CACHE_LOCK_RESILIENCE_ENABLED: ClassVar[bool] = _env_bool(
    "SMART_CACHE_LOCK_RESILIENCE_ENABLED", True)
```
- **ON** (default): PRAGMA применяются + bounded retry.
- **OFF**: ровно прежнее поведение (нет PRAGMA, нет повторов, прежний WARNING/no-op) — kill-switch, возврат байт-в-байт.

### 5.4. Лог при исчерпании (формат, пример)
```
smart cache: lock exhausted | event=smart_cache_lock_exhausted | op=set | key=<md5> | attempts=4 | error=database is locked
```
- `key` — уже существующий MD5-хэш (R17-safe); `payload` и сырой ввод **не логируются**.
- `exc_info=True` сохраняется (реальная причина видна в трейсе).

### 5.5. Счётчик
```python
def smart_cache_lock_exhausted_total() -> int   # in-process, Δ DDL = 0
```
Инкремент при исчерпании в `_read` и `_write`. Сброс процесса = сброс счётчика (приемлемо: событие остаётся в логе).

## 6. План тестов (T-2325)

Обязательное условие: тесты PRAGMA — на **файловой** БД (`tmp_path`); `:memory:` не поддерживает WAL (вернёт `memory`). Для тестов retry backoff обнуляется тест-хуком (прецедент `llm_client.backoff_base=0`).

- **(a) PRAGMA реально применены** (флаг ON): после `_ensure_db` у соединения `PRAGMA journal_mode` → `wal`, `PRAGMA busy_timeout` → `5000`, `PRAGMA synchronous` → `1` (NORMAL).
- **(b) Блокировка → retry успешен**: сымитировать `OperationalError("database is locked")` на первых попытках, затем успех → запись **сохранена**, ошибка не наружу, `event=lock_exhausted` **не** логируется.
- **(c) Исчерпание → явный WARNING, не тихий no-op**: все попытки `locked` → (1) `_write` не бросает (fail-open), (2) в логе запись с `event=smart_cache_lock_exhausted` и реальной причиной, (3) `smart_cache_lock_exhausted_total()` увеличился; для `_read` аналогично с возвратом `None`.
- **(d) Нет регресса hit/miss/expired и LRU/trim**: существующие сценарии кэша (hit, miss, expired→DELETE, превышение `SMART_CACHE_MAX_ROWS` → удаление старейших) возвращают прежние результаты и прежние INFO-логи; `get_dedup`/`set_dedup` и их TTL-семантика не изменились.
- **(e) Kill-switch**: флаг OFF → PRAGMA не применяются и повторов нет (при `locked` — одна попытка, прежний WARNING); поведение идентично baseline.
- **(f) Non-lock исключение не ретраится**: условный сбой (не `locked`) → одна попытка, прежний путь (WARNING + miss/no-op).
- **(g) Нет утечки fd**: провал инициализации (`CREATE TABLE`/PRAGMA бросает) → соединение закрывается, `self._db is None`, повторный `_ensure_db` возможен и корректен.
- **(h) R17**: в логах нет payload/сырого ввода; фигурирует только MD5-ключ.

## 7. Риски

- **R1 (Medium):** долгий retry подвешивает hot-path кэша (`busy_timeout` 5с + ≤0.7с). **Митигация:** число повторов и backoff зафиксированы и малы; fail-open — последний рубеж; при необходимости значение — одна константа. (Наследуется формулировка R1 из `tasks.md`.)
- **R2 (Medium):** конфликт WAL/`synchronous` отдельного соединения с основным writer'ом. **Митигация:** значения строго по образцу `database.py:514-520`; тест (a); WAL допускает несколько соединений (уже так и задумано, см. docstring `smart_cache.py:78-79`).
- **R3 (Medium):** маскирование проблемы под «успех» (fail-open прячет потерю). **Митигация:** тест (c) обязателен — при исчерпании **явный** WARNING + счётчик; тест (b) не должен шуметь.
- **R4 (Low):** лишние повторы при не-lock ошибке. **Митигация:** `_is_locked` фильтрует по `locked`; тест (f).
- **R5 (Low):** `journal_mode=WAL` на `:memory:` в тестах. **Митигация:** тесты только на файловой БД.

## 8. Критерии приёмки

- Соединение `smart_cache` использует `WAL` / `busy_timeout=5000` / `synchronous=NORMAL` (паритет с `database.py:514-520`) при флаге ON.
- При кратковременной блокировке запись **не теряется** (bounded retry); чтение не деградирует до ложного miss из-за lock.
- При исчерпании — **явный** WARNING `event=smart_cache_lock_exhausted` с причиной + счётчик (не тихий no-op).
- Поведение при успехе не изменилось: те же возвраты и INFO-логи `hit/miss/expired/set`; `get_dedup`/`set_dedup` без регресса.
- В прод-логах исчезло `database is locked` от `services.smart_cache` (T-2327).
- Полный pytest — **0 failed**; `git diff --check` чист; `git diff --stat` ограничен `services/smart_cache.py` + `config/settings.py` + тесты.
- **Δ DDL = 0** (SQLite остаётся `v12`), **Δ каталога = 0**.

## 9. Feature-flag и поэтапная доставка

- Флаг: `SMART_CACHE_LOCK_RESILIENCE_ENABLED` — env-only `ClassVar[bool]`, **default ON**, вне `param_catalog` (Δ каталога = 0).
- Семантика: **ON** = новое поведение (PRAGMA + retry); **OFF** = точный возврат к прежнему (kill-switch).
- Progressive delivery (internal→10%→50%→100%) **не требуется** (фича локальная, обратимая флагом; по `tasks.md`). Наблюдение — по логу `event=smart_cache_lock_exhausted` и счётчику: при ON их не должно быть, а «set failed … locked» из baseline должен исчезнуть.

## 10. Откат

- **Мягкий:** `SMART_CACHE_LOCK_RESILIENCE_ENABLED=False` + рестарт → байт-в-байт прежнее поведение без PRAGMA/retry.
- **Полный:** `git revert` коммита фичи.
- **Δ DDL = 0**, Δ каталога = 0, Δ файлов на диске = 0 (кроме штатных служебных файлов WAL, уже существующих); `journal_mode=WAL` — свойство БД, уже установленное основным соединением, отдельного отката не требует.

## 11. Инварианты раунда (проверка)

| Инвариант | Статус |
|---|---|
| **R17** (без секретов в логах) | Соблюдён: логируем только MD5-ключ + тип ошибки; payload/сырой ввод/креды не пишем |
| **R18** (секреты не коммитить/не цитировать) | Соблюдён: секретов в spec/ADR нет |
| **Δ DDL = 0** | Соблюдён: `CREATE TABLE IF NOT EXISTS smart_cache` не меняется; миграций/PG-таблиц нет |
| **`parse_mode=None`** | Не затрагивается: фича не касается отправки/egress |
| **F1** (`core-llm-error-fixes`) | Не затрагивается: другой файл (`summary_memory.py`/`llm_client.py`) |
| **F2** (`logging-infra`) | Не ломается: нет жёсткой зависимости; формат `event=...` согласован |
| **F7** (`anticliche-cron-limit`) | Не затрагивается: другой файл (`anticliche_worker.py`/`anticliche_cache.py`) |
| `imported-history-immutable` / `manual-overrides-immutable` | Не затрагиваются: пишем только в `smart_cache` |
| physical-two-call-pipeline / egress-реестр | Не затрагиваются |

## 12. Ссылки

- ADR: `ADR-1024-18.md`
- Задачи: `plans/features/sqlite-lock-resilience-round1024/tasks.md` (T-2322…T-2327)
- Карта: `plans/features/round1024-architecture.md` (общие инварианты §4, ступени §5)
- Код: `services/smart_cache.py:89-103,125-174`; `services/database.py:48,514-520,589-594`; `services/memory_rebuild.py:69-72,92-111`
- Отчёт @Memory: `upd4-live-bug-clusters-round1024` (кластер C)
- Прод-лог: `services.smart_cache | smart cache: set failed | sqlite3.OperationalError: database is locked`
