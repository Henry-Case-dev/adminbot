# ADR-1025-5 — Устойчивость к `database is locked`: расширение ADR-1024-18 на main write-path и `self.db.db`

- **Статус:** **Accepted** (Step 2 @Architect, 20.09.2026)
- **Фича:** F0 `f0-config-bugfixes-round1025` — F0.5 (прод-деградация 20.09.2026)
- **Тип:** backend/надёжность БД (инфраструктура)
- **Связано:** **AMEND/EXTEND ADR-1024-18** (`plans/archive/sqlite-lock-resilience-round1024/`), `spec.md` §5; `tasks.md` T-2442…T-2455
- **Задачи:** T-2442…T-2455

> **Это расширение, а не новый контракт.** ADR-1024-18 закрыл класс дефекта **только** для
> `services/smart_cache.py`. F0.5 переносит тот же контракт (PRAGMA-паритет + bounded retry
> только на `locked` + явный лог исчерпания + kill-switch) на остальные затронутые сервисы.
> `smart_cache` **не трогается** (только сверяется паритет/переиспользуется образец).

## Контекст

1. Прод-лог 20.09.2026 ~08:52–08:53 UTC, chat_id=-1002661910336: `sqlite3.OperationalError: database is locked` в 6 точках (WARNING, fail-open ⇒ возможна тихая потеря записи):
   - `services/summary_memory.py:2436 memorize_self_reply` → `services/database.py:2688 insert_graph_fact`;
   - `services/direct_chat_service.py:546 remember_bot_reply` → `database.py:3611 upsert_bot_reply`;
   - `summary_memory.py:2731 _knn_graph_facts` → `database.py:4330 touch_graph_facts`;
   - `summary_memory.py:1468 _embed_cache_store` → `self.db.db.execute`;
   - `services/persistent_throttling.py:217 reset` и `:121 allow` → `self._db.db.execute`.
2. Основное соединение **уже** применяет `PRAGMA journal_mode=WAL` → `busy_timeout=5000` → `synchronous=NORMAL` (`services/database.py:48,514-520`), но **не имеет bounded retry**; пути (4)–(6) работают через `self.db.db`/`self._db.db` — то же соединение, минуя публичный API.
3. Авторитетные прецеденты: `services/memory_rebuild.py:69-72,92-111` (bounded retry на `locked`), `services/database.py:589-594` (`initialize_existing` повторяет те же PRAGMA), `services/llm_client.py:604` (тест-хук `backoff_base==0`).
4. 10.24 (ADR-1024-18) закрыл `smart_cache`; `smart_cache.py:30-232` — эталон helper'а и счётчика (`smart_cache_lock_exhausted_total`).

Формулировка владельца: *«лучше подождать, чем потерять»*, но ожидание **конечно**, а потеря при исчерпании — **явная**.

## Карта соединений (T-2442, по фактическому коду)

| # | Владелец | Соединение | PRAGMA | Bounded retry | Текущая реакция |
|---|---|---|---|---|---|
| 1 | `Database` основной (`database.py:514-520`) | собственное `aiosqlite` | WAL+bt5000+NORMAL | **нет** | вызывающий |
| 2 | `SmartCache` (`smart_cache.py:150-175`) | собственное | WAL+bt+NORMAL (ADR-1024-18) | **есть** | fail-open |
| 3 | `Database.initialize_existing` (`database.py:589-594`) | собственное (CLI) | WAL+bt+NORMAL | нет | — |
| 4 | `manage.py` CLI (`manage.py:146,197`) | собственное | не подтверждено | нет | — |
| 5 | `memory_rebuild` sqlite3 sync (`memory_rebuild.py:166-168`) | собственное | — | **есть** (своё) | — |
| 6 | `summary_memory._embed_cache_store` (`:1462-1494`) | общее #1 (`self.db.db`) | наследует #1 | **нет** | fail-open |
| 7 | `summary_memory.memorize_self_reply` → `insert_graph_fact` | общее #1 | наследует | **нет** | fail-open |
| 8 | `summary_memory._knn_graph_facts` → `touch_graph_facts` | общее #1 | наследует | **нет** | fail-open |
| 9 | `direct_chat_service.remember_bot_reply` → `upsert_bot_reply` | общее #1 | наследует | **нет** | fail-open |
| 10 | `persistent_throttling.allow/reset/bump` | общее #1 (`self._db.db`) | наследует | **нет** | fail-open |

## Первопричина: почему `busy_timeout=5000` не спасает (T-2443)

1. **Интерливинг корутин на общем соединении #1 без `Database._lock`.** `self.db.db.execute` (пути 6–10) выполняют многошаговые последовательности с `await` между `execute` и `commit` (`_embed_cache_store` `:1468-1493`; `upsert_bot_reply` `:3611-3628`; `allow` `:121-128`; `reset` `:217-221`; `touch_graph_facts` `:4330-4338`). Другая корутина вклинивается, и SQLite отдаёт `SQLITE_BUSY` **на том же соединении немедленно** — busy-обработчик рассчитан на межсоединённую блокировку, а не на self-lock. Это объясняет, почему `busy_timeout` «не видит» эти ошибки.
2. **Длинные транзакции.** `_embed_cache_store` — N вставок до одного `commit`; `upsert_bot_reply` — 4 стейтмента; `touch_graph_facts` — 2 UPDATE. Держат write-лок дольше 5с под нагрузкой.
3. **Конкуренция соединений/процессов.** Основное `Database` + `SmartCache` + CLI `manage.py` (retention/rebuild) конкурируют за WAL-писателя; превышение 5с → `locked` (межсоединённо).
4. **Нет bounded retry в main write-path.** Даже короткая блокировка поднимается наверх и молча теряется fail-open'ом (`summary_memory.py:2447-2451`, `direct_chat_service.py:549-552`, `persistent_throttling.py:129-133,223-227`).

**Вывод:** лечение «по симптому» (увеличение `busy_timeout`/задержки) не покрывает self-lock и интерливинг — нужны **сериализация** многошаговых транзакций + **bounded retry** + **явный лог** исчерпания.

## Решение (AMEND к ADR-1024-18)

### D1. Единый bounded-retry helper в `services/database.py`
Приватные `Database._is_locked(exc)` и `Database._with_lock_retry(op, *, on_exhausted, op_name)`:
- повторяем **только** `OperationalError` с `"locked" in str(exc).lower()`;
- `_LOCK_RETRIES = 3`, backoff `0.1/0.2/0.4с` (экспоненциальный), best-effort `rollback` перед повтором;
- повторяется **вся транзакция**, не отдельный statement;
- не-`locked` исключения не ретраятся (маскирование запрещено).
Значения — зеркало `memory_rebuild.py:69-72` и ADR-1024-18.

### D2. Сериализация многошаговых транзакций (single-writer)
Публичный `Database.write_transaction()` (или эквивалентный `run_write(fn)`): берёт `self._lock` на всё время логической транзакции, выполняет, коммитит/роллбэчит, при `locked` — bounded retry. Обернуть `insert_graph_fact`, `upsert_bot_reply`, `touch_graph_facts`; перевести `_embed_cache_store`, `persistent_throttling.allow/reset/bump` с `self.db.db`/`self._db.db` на публичный API (T-2449). Одна логическая операция → одна атомарная транзакция.

**Почему не только retry:** retry без сериализации оставляет интерливинг и может коммитить чужую частичную работу; lock + атомарная транзакция устраняют класс.

### D3. PRAGMA-паритет всех прочих собственных соединений
Для каждого `aiosqlite`-соединения вне `smart_cache` — `PRAGMA journal_mode=WAL` → `busy_timeout=5000` → `synchronous=NORMAL` (локальные константы-зеркала; образец `database.py:514-520`). Если T-2442 покажет, что иных (кроме CLI/`initialize_existing`) нет — зафиксировать как результат **без фиктивных правок**. `smart_cache` **не изменять**.

### D4. Исчерпание — не тишина
Структурированный WARNING `event=<service>_lock_exhausted` (`exc_info`, `op`, `scope`/`chat_id` при допустимости — **без секретов**, R17) + in-process счётчик `<service>_lock_exhausted_total()` (по образцу `smart_cache_lock_exhausted_total`). Развести «успех», «успех после retry», «исчерпание → лог+счётчик+fail-open». Тихая потеря исключена.

### D5. Fail-open — только последний рубеж
Хендлеры direct-chat/саммари/throttling продолжают обслуживать запрос при исчерпании ретраев; ответ пользователю не блокируется и не превращается в ошибку из-за `locked`. Факт возможной потери **наблюдаем** (D4).

### D6. Kill-switch `DB_LOCK_RESILIENCE_ENABLED`
env-only `ClassVar[bool]`, **default ON**, вне `param_catalog` (Δ каталога = 0), по образцу `SMART_CACHE_LOCK_RESILIENCE_ENABLED` (`config/settings.py:976-977`). OFF → ровно прежнее поведение (без retry/сериализации/счётчика/PRAGMA-эффекта). Откат — флаг OFF либо `git revert` (точка отката T-2410).

### D7. Тест-хук нулевого backoff
По образцу `services/llm_client.py:604` (`backoff_base == 0`) — управляемый backoff, чтобы тесты retry не спали.

## Последствия

**Positive**
- Кратковременная блокировка не теряет запись (retry); self-lock/интерливинг устранены сериализацией.
- Исчерпание видимо (лог `event=*_lock_exhausted` + счётчик), а не замаскировано под успех/no-op.
- Единый контракт с ADR-1024-18; `smart_cache` не переделан; Δ DDL = 0, Δ каталога = 0.

**Negative**
- Сериализация main write-path может незначительно увеличить латентность при всплеске записей — приемлемо (владелец предпочёл «подождать, чем потерять»).
- Худший случай на операцию — `busy_timeout` (5с) + ≤0.7с retry; конечно.
- In-process счётчик теряется при рестарте (событие остаётся в логе).

## Альтернативы

- **A1. Только увеличить `busy_timeout`** — **отклонено**: не помогает при self-lock/интерливинге (первопричина 1).
- **A2. Только retry без сериализации** — **отклонено**: интерливинг и коммит чужой частичной работы сохраняются.
- **A3. Новый общий модуль-helper** — **отложено**: для main-клиента helper живёт в `database.py`; `smart_cache` сохраняет локальное зеркало (ADR-1024-18 D2), полная унификация — отдельный раунд.
- **A4. Неограниченный retry** — **отклонено**: подвесит hot-path (риск High в T-2450).
- **A5. Ретраить все исключения БД** — **отклонено**: маскирует неретраибельные дефекты.
- **A6. Отдельное read-соединение для консистентного чтения** — **отложено**: расширяет scope; в F0 достаточно single-writer на запись.

## Ссылки

- **AMEND-база:** `plans/archive/sqlite-lock-resilience-round1024/ADR-1024-18.md`, `spec.md`
- Спека: `plans/features/f0-config-bugfixes-round1025/spec.md` §5
- Задачи: `tasks.md` T-2442…T-2455 (ревью T-2453, деплой/live T-2454, отчёт T-2455)
- Код: `services/database.py:48,507-594,2619-2708,3607-3628,4310-4339`; `services/smart_cache.py:30-232`; `services/memory_rebuild.py:69-72,92-111`; `services/persistent_throttling.py:74-227`; `services/summary_memory.py:1462-1494,2416-2451,2729-2737`; `services/direct_chat_service.py:538-552`; `config/settings.py:966-977`
- Прод-лог: 20.09.2026 ~08:52–08:53 UTC (6 стеков; см. spec §5)

## Human Gate

- **Открытые вопросы:** (1) достаточно ли lock по всему `write_transaction` или нужен отдельный read-путь для консистентного чтения; (2) нужно ли приводить `manage.py` CLI к PRAGMA-паритету в этом раунде (T-2447) или достаточно зафиксировать по T-2442. Значения (`_LOCK_RETRIES=3`, backoff 0.1, `busy_timeout=5000`) — техническая настройка @Architect; флаг default ON согласован в `tasks.md`. Прогрессивная раскатка не требуется.
