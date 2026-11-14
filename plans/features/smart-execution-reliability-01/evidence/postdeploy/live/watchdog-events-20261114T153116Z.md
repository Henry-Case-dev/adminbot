# Watchdog / observability snapshot — 2.58.202 (0beed63d) — 2026-11-14 15:14:42–15:38:25Z

Read-only снимок durable-телеметрии watchdog на deployed 2.58.202.
Источник: `local_database.db` через SQLite URI `mode=ro` (без записи, без
copy-файла рядом с прод-БД). Окно: от `deployed_at`
(`2026-11-14T15:14:42.974638Z`) до `generated_at 2026-11-14T15:38:25.771417Z`
— весь период с момента деплоя.

Запрос покрывает `mca_events` c именами `WATCHDOG_SWEEP`,
`WATCHDOG_TAKEOVER`, `WATCHDOG_INCIDENT_FAILURE`, таблицу `mca_incidents`,
связанные `task_jobs`, а также события с `prompt_source` в payload.

## 1. Сводные счётчики

```
WATCHDOG_SWEEP                 24
WATCHDOG_TAKEOVER               0
WATCHDOG_INCIDENT_FAILURE       0
mca_incidents (в окне)          0
takeover без job_id             0
takeover с duplicate job_id     0
takeover по уже завершённым job 0
incidents по завершённым job    0
prompt-provenance events        0
```

Инцидентов и takeover-событий в окне нет вообще, поэтому проверки
«takeover несёт job_id/owner/kind/outcome» и «нет агрегатных дублей»
подтверждаются тривиально (нет самих записей), а не на реальных примерах.

## 2. Timeline sweep'ов (24 прохода, 1/мин)

```
15:14:48  ×2 (startup, идентичные нулевые счётчики)
15:15:48 … 15:27:49  по одному в минуту
15:28:49 … 15:36:49  по одному в минуту
```

Два события в 15:14:48 имеют одинаковые нулевые показатели — это
наблюдение startup-прохода сразу после рестарта, не дубль инцидента.

Постоянные значения во всех 24 проходах:

```
stale                          0
progress_stalled               0
incidents                      0
overdue.running                0
overdue.queued                 0
takeover.discovered            0
takeover.attempted             0
takeover.recovered             0
takeover.failed                0
takeover.no_change             0
takeover_records               0
takeover_totals.{recovered,failed,no_change}  0
incident.{created,updated,reopened,failed,disabled}  0
incident_totals                 те же нули
reconcile  checked=3, pending=3, resolved=0, failed=0, inconclusive=0
queued.hang / normal_wait / owner_managed / overdue / scheduled_retry = 0
```

Единственные ненулевые, кроме `reconcile`:

```
queued.deadline_pending    15:28:49=1, 15:29:49=1, 15:30:49=2, 15:33:49=1
running_contract.heartbeat_only
                           15:19:49=1, 15:22:49=1, 15:28:49=2, 15:29:49=2,
                           15:30:49=2, 15:31:49=1, 15:33:49=1, 15:36:49=1
running_contract.deadline_bounded = 0 всегда
```

То есть в окне было 0–2 задачи с близким deadline и 0–2 задачи, у которых
контракт держится только на heartbeat; ни одна не стала overdue/stale,
takeover не потребовался.

## 3. Инциденты и prompt provenance

- `mca_incidents`: 0 строк за окно (и по `last_ts`, и по `resolved_at`).
  Ложных takeover по завершённым задачам нет — сравнивать не с чем,
  потому что takeover-событий тоже нет.
- `WATCHDOG_INCIDENT_FAILURE`: 0. Это ожидаемо при нуле попыток
  регистрации инцидентов; отсутствие события здесь не доказывает
  корректность обработки сбоя регистрации.
- События с `prompt_source`/checkup-телеметрией в `mca_events`: 0. Значит,
  провенанс промпта чекапа **не** публикуется в durable-канал и не может
  быть подтверждён из телеметрии; он проверялся отдельным read-only
  probe (см. `canary-final-20261114T153116Z.md`, §3) — результат FAIL.

## 4. Границы этого снимка (честно)

1. Окно — 24 минуты сразу после деплоя; в нём не было ни одной stale/
   overdue задачи. Нулевые takeover/incident доказывают отсутствие ложных
   срабатываний в спокойном состоянии, но **не** поведение при реальном
   зависании job. W-01/W-11 под нагрузкой этим снимком не подтверждены.
2. `queued.reconcile` стабильно `checked=3, pending=3`: три задачи вне
   активного resolve, без ошибок reconcile; это наблюдение, а не
   подтверждение корректности их финального закрытия.
3. Отсутствие `WATCHDOG_INCIDENT_FAILURE` не проверяет negative-path
   обработки сбоя `open_or_update`.
4. Снимок сделан после обоих харнессов (SMART/FC) и захватывает их окно,
   но события харнессов идут с `chat_id=0`/синтетическими id и в
   watchdog-логику не попадают.

Секретов, DSN, токенов и текстов промптов здесь нет; raw chat id не
печатались.

## 5. Handoff

```
Status:      watchdog в окне 0beed63d: 24 sweep, 0 takeover, 0 incident failure, 0 инцидентов
Evidence:    это наблюдение спокойного окна; поведение под stale-нагрузкой НЕ доказано
Next:        @Orchestrator — учесть границы при оценке W-01/W-10/W-11 и S5-наблюдаемости
```
