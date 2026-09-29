# `mca-01-tx-task-supervisor` — спецификация (Step 2 @Architect, T-3732)

- **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 0** (фундамент). **Фича-ID:** `mca-01-tx-task-supervisor`.
- **Тип:** backend/reliability — владение транзакцией, конкурентность, фоновые задачи. **P0** (подтверждённые дефекты откатa чужой транзакции и накопления зависших операций).
- **Источник (IMMUTABLE, R17/R18):** `plans/current_task.md` **§5.1** (`:111–124`), **§5.2** (`:126–139`), §22 (`:1066–1070`); приёмки §19 **A01**, **A02**, **A51**.
- **Задачи:** `tasks.md` T-3730…T-3749. **Приёмка:** A01, A02, A51.
- **ADR:** `adr-1027-3-tx-task-supervisor.md` (D1–D10). **Рамка:** `plans/docs/mca-round1027-arch-frames.md`.
- **Статус:** Proposed → Accepted по T-3749. **Deploy:** `DEFERRED_TO_RELEASE`.
- **Risk-Level:** **R3** — меняет общий write-path SQLite (все записи памяти/сводок/кеша/backfill) и жизненный цикл фоновых задач; ложный commit/rollback = порча данных. При R3 — `threat-failure-analysis.md` (Блок H). Триггеры понижения: полная изоляция отката/lock-ownership, доказанная закрытием A01/A02/A51, отсутствие регрессий write-path.
- **Baseline:** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v12**; каталог `473/430/448/102/100/21`; канон 12.

## 1. Область и исключения

**Входит:** семантика владения транзакцией (`BEGIN`/тело/`COMMIT`-`ROLLBACK`/очистка под lock; отмена ожидающего не откатывает чужую; known-state после ошибки; retry/backoff после освобождения lock; сеть/LLM вне транзакции; согласованный механизм **для всех** записей в общую SQLite connection — включая embedding cache/backfill/сводки/служебные `UPDATE`/`DELETE`); TaskSupervisor (реестр задач: владелец/тип/срок/результат/exception handler; durable queue таблица; coalescing/singleflight; bounded очереди; закрытие ресурсов; generation/version invalidation; eviction/cleanup; bounded SQL профиля; pending в finally).

**Не входит (границы):** механизм миграций/backup (`mca-14`); контракт событий (`mca-13` — сюда только регистрация стадий); реестр процессов/heartbeat/watchdog/инциденты (MCA-17a — поверх TaskSupervisor, не второй реестр); второй контур инициативы/отправки (не создаётся); F0.5/ADR-1024-18 `DB_LOCK_RESILIENCE_ENABLED` **не дублируется**, а уважается.

## 2. Трассируемость REQ → SC

| REQ | §ТЗ | SC | Задачи |
|---|---|---|---|
| REQ-MCA01-01 — транзакцией владеет только получившая lock задача; BEGIN/тело/COMMIT-ROLLBACK/очистка под lock; отмена ожидающего не меняет чужую | §5.1 `:117–119` | SC-01, SC-02 | T-3734 |
| REQ-MCA01-02 — known-state после ошибки commit/rollback; явное закрытие/восстановление; видимая ошибка; retry/backoff после освобождения lock | §5.1 `:120–121` | SC-03, SC-04 | T-3735 |
| REQ-MCA01-03 — все записи в общую connection через согласованный механизм; сеть/LLM вне транзакции | §5.1 `:121–122` | SC-05, SC-06 | T-3736, T-3737 |
| REQ-MCA01-04 — pending в finally на всех путях; смена concurrency без превышения ёмкости | §5.2 `:130–131` | SC-07, SC-08 | T-3738, T-3739 |
| REQ-MCA01-05 — фоновые задачи зарегистрированы (владелец/тип/срок/результат/handler); durable queue | §5.2 `:132` | SC-09, SC-10 | T-3740 |
| REQ-MCA01-06 — coalescing/singleflight; bounded очереди; не терять молча | §5.2 `:133–134` | SC-11, SC-12 | T-3741, T-3742 |
| REQ-MCA01-07 — независимое закрытие ресурсов; lore-notifier leak; inflight-cancel; stale-cache; generation/version invalidation | §5.2 `:135–136` | SC-13, SC-14 | T-3743 |
| REQ-MCA01-08 — eviction/cleanup кешей/map/файлов; bounded SQL профиля | §5.2 `:137` | SC-15 | T-3744 |
| REQ-MCA01-09 — R17-логи; события по контракту MCA-13; регистрация стадий (MCA-17) | §17; §27.1 | SC-16 | T-3746 |
| REQ-MCA01-10 — deploy `DEFERRED_TO_RELEASE`; kill-switch/rollback | §5.2 приёмка `:139`; §20 | SC-17 | T-3747 |

**Орфан-REQ нет:** каждый REQ ≥1 SC; T-3730/3731/3745/3748/3749 — процессные (baseline/PM/приёмка/ревью/merge).

## 3. Наблюдаемое поведение и отказы

- Два одновременных писателя сохраняются независимо: откат A не уничтожает успешную запись B; отмена ожидающего C не делает rollback чужой транзакции. Нет скрытого commit/rollback чужой операции.
- После ошибки `commit`/`rollback` соединение возвращается в известное состояние; при невозможности — явно закрыто/восстановлено, ошибка видна (R17-safe).
- Сеть/LLM никогда не выполняются внутри транзакции записи.
- Отмена/перезапуск worker не оставляют зависших `pending`/`active`; job возобновляется без дубля (A02); при гибели worker — `interrupted`, takeover по fencing/checkpoint без дублей (A51).
- Повторяемый нагрузочный цикл не даёт монотонного роста удерживаемых задач/записей кеша/файлов; RSS наблюдается и объясняется (единичный пик ≠ доказанная утечка).

## 4. Интерфейсы и контракты

### 4.1. Владение транзакцией (D1)
- `write_transaction(op)`: lock берётся **до** `BEGIN`; тело, `COMMIT`/`ROLLBACK` и отменоустойчивая очистка — **под** тем же lock; rollback выполняется **внутри** lock (не после `async with`). Отмена ожидающего (провал acquisition) **не** инициирует rollback общей connection. `commit_if`-паритет сохраняется.
- Отмена владельца: очистка под lock (не оставлять открытую транзакцию следующему писателю).

### 4.2. Known-state, close/restore, retry/backoff (D2)
- После ошибки `commit`/`rollback` соединение в известном состоянии; при невозможности — явное закрытие/пересоздание, ошибка видна. Retry/backoff только для `locked` (существующий `_LOCK_RETRIES`/`_LOCK_BACKOFF`), **после** освобождения lock. Не-`locked` ошибки не маскируются. Поведение при `DB_LOCK_RESILIENCE_ENABLED=OFF` — паритет baseline.

### 4.3. Согласованный write-механизм (D3)
- **Аудит всех записей** в общую connection (не только текст `.execute`): direct `self.db.commit()` (baseline: 91 в `database.py` + `chat_lore.py`, `direct_chat_service.py`, `dossier_rebuild_jobs.py`, `memory_maintenance.py`, `memory_rebuild.py`, `persistent_throttling.py`, `summary_memory.py`) — embedding cache, backfill, сводки, служебные `UPDATE`/`DELETE` — через единый механизм (`write_transaction` или эквивалент single-writer). Чтения не флагаются по совпадению текста.
- Сеть/LLM — вне транзакции (тест-спай).

### 4.4. `smartmodule_concurrency` (D4)
- `pending` декрементируется **в `finally`** на всех путях `try_acquire`/`acquire`, включая `CancelledError` (сейчас — только `TimeoutError`; при отмене `pending` утекает). Смена `concurrency` не создаёт параллельно старый и новый семафоры сверх ёмкости: применение после безопасного drain либо через единый регулируемый счётчик.

### 4.5. TaskSupervisor (D5–D8)
- **Реестр задач:** `task_id/owner/kind/deadline/result_ref/exception_handler`; регистрация всех фоновых задач; exception handler гарантирует видимый терминальный исход (событие MCA-13), не `except: pass`.
- **Durable queue:** таблица `task_jobs` (v14, рамка §1.1.1) — долговременная работа восстанавливается при рестарте; поля `coalesce_key`/`generation`/`fencing_token`/`heartbeat_at`/`attempt`/`max_attempts`.
- **Coalescing/singleflight:** повторяющееся задание по одному чату/версии не запускается дважды (уникальный частичный индекс по `coalesce_key` для активных статусов).
- **Bounded очереди:** при заполнении важное — в durable queue, второстепенное — объединить/отклонить **с причиной** (`queue_coalesced`/`queue_full`); молчаливая потеря запрещена.
- **Закрытие ресурсов:** каждый closer выполняется даже при ошибке другого; отмена освобождает собственные ресурсы; **исправить** незакрытое соединение при ошибке инициализации lore-notifier, отмену общего inflight-запроса одним ожидающим, возврат устаревшего кеша после invalidation (generation/version).
- **Eviction/cleanup:** кеши, cooldown-map, throttle-map, результаты, временные файлы имеют eviction; SQL-выборка профиля ограничена вместо бесконтрольного `fetchall`.

## 5. Δ DDL / Δ каталога / kill-switch

- **Δ DDL:** **v14** — `task_jobs` + индексы (рамка §1.1.1). PG — no-op. §5.1 сам по себе DDL не требует.
- **Δ каталога:** **0** (env-only `ClassVar`). F8 не переиздаётся.
- **Kill-switch:** `MCA_TX_OWNERSHIP_ENABLED` (default ON; OFF → прежний `write_transaction`), `MCA_TASK_SUPERVISOR_ENABLED` (default ON; OFF → без реестра/durable-очереди/coalescing). Существующий `DB_LOCK_RESILIENCE_ENABLED` уважается.

## 6. Приёмочные сценарии (SC)

- **SC-01 (A01):** A откатывается, B пишет; B сохранён.
- **SC-02 (A01):** отмена ожидающего C не делает rollback A/B; нет скрытого commit чужой операции.
- **SC-03:** после ошибки commit/rollback соединение в известном состоянии либо явно закрыто/восстановлено; ошибка видна.
- **SC-04:** retry/backoff только для `locked`, после освобождения lock; не-`locked` не маскируется.
- **SC-05:** каждая запись в общую connection идёт через согласованный механизм (аудит-тест по всем write-точкам).
- **SC-06:** сеть/LLM не вызываются внутри транзакции (спай).
- **SC-07 (A02):** отмена на всех путях уменьшает `pending` в `finally`, включая `CancelledError`; зависших счётчиков нет.
- **SC-08 (A02):** смена concurrency во время работы не превышает ёмкость.
- **SC-09:** фоновые задачи зарегистрированы с владельцем/типом/сроком/результатом/handler.
- **SC-10 (A51):** рестарт worker восстанавливает job из durable queue; takeover по `fencing_token`; нет дублей; гибель → `interrupted`.
- **SC-11:** повторяющееся задание coalesce/singleflight (один запуск на один `coalesce_key`).
- **SC-12:** при переполнении очереди важное в durable, второстепенное отклонено/объединено с причиной; молчаливой потери нет.
- **SC-13:** закрытие каждого ресурса при ошибке другого closer; lore-notifier не оставляет соединение; inflight-cancel корректен; stale-cache не возвращается (generation/version).
- **SC-14:** invalidation по generation/version предотвращает возврат устаревших данных.
- **SC-15:** eviction кешей/map/файлов работает; SQL профиля bounded (`LIMIT`).
- **SC-16:** логи транзакций/задач R17-safe; события — по контракту MCA-13; стадии зарегистрированы для MCA-17.
- **SC-17:** deploy `DEFERRED_TO_RELEASE`; kill-switch/rollback зафиксированы; нагрузочный цикл без монотонного роста; RSS объяснён.

## 7. Зависимости

Нет обязательных предшественников внутри MCA. Совместно с Wave 0: `mca-14` (механизм v14/backup) и `mca-13` (события). Unblocks: `mca-04b`, `mca-10b`, `mca-11`, `mca-17a`. Внешние сервисы не требуются.

## 8. Тесты / деплой / откат

- **Тесты:** A01 (два писателя + отменённый ожидающий), A02 (отмена/перезапуск без зависших и дублей), A51 (гибель worker + takeover с fencing/checkpoint), нагрузочный цикл (нет монотонного роста; RSS объяснён), аудит write-точек, спай сеть/LLM, R17. Полный pytest ≥ baseline; JS зелёные; `git diff --check`=0.
- **Деплой:** `DEFERRED_TO_RELEASE`; на `mca-release` — migration smoke (`task_jobs`), effective-state §20.2.
- **Откат:** hot — `MCA_TASK_SUPERVISOR_ENABLED=false`/`MCA_TX_OWNERSHIP_ENABLED=false`; cold — `git revert` → `7165ff7` (`task_jobs` безвреден).
