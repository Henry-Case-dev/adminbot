# MAC-EXP-06 — живое доказательство (2.58.170)

Кандидат: `42f068df22edeeb82062525446b71d7022a6006b` (`release/2.58.170`, база — `33707364`).
Продукт: `/var/www/admin_bot`, systemd `admin_bot`. Все проверки — на живом процессе
`MainPID=3233804` (старт 2026-11-08T22:08:49Z), **без единого рестарта** между переключениями.

## 1. Тик зарегистрирован в живом планировщике

`journalctl` при старте (22:09:12Z):

```
apscheduler.scheduler - INFO - Added job "MemoryMaintenanceService._tick_experience_review" to job store "default"
apscheduler.scheduler - INFO - Added job "MemoryMaintenanceService._tick_communities" to job store "default"
```

Регистрация не зависит от гейта (EXP-FIX-06): интервал 900 c, гейт резолвится на каждом заходе.

## 2. OFF → ON → OFF → ON без рестарта

Переключение — штатным путём: `POST /api/config` с TMA-initData администратора
(`X-Chat-Id` не передавался, ключ `memory.experience_learning_enabled` — глобальный мастер),
чтение — `GET /api/config` того же процесса.

| Время (UTC) | Действие | Effective (GET /api/config) | PID |
|---|---|---|---|
| 22:15:10 | POST OFF | `False` | 3233804 |
| 22:26:0x | POST ON | `True` | 3233804 |
| 22:41:0x | POST OFF | `False` | 3233804 |
| 22:41:1x | POST ON (финал) | `True` | 3233804 |

`NRestarts=0`, `ExecMainStartTimestamp` не менялся — рестарта не было.

## 3. Нулевая работа при OFF

Проба исполняет **ту же** функцию тика (`mca_experience_jobs.tick_experience_review`) на живой БД
с обёрткой-счётчиком `aiosqlite.Connection.execute`:

```
hot memory.experience_learning_enabled = False
review_enabled() = False
tick status = disabled
sql_execute_calls = 0
```

Живой тик планировщика при OFF (22:24:12Z): в журнале нет ни одной строки `[mca16]`,
`task_jobs kind='experience.review'` остаётся **35**, `MAX(created_at)=1794137187` (старая) —
новых задач нет. Планировщик при этом жив (видны тики `VisionMediaWorker._tick`).

## 4. Живой тик при ON

Тик 22:39:14Z на живом процессе:

```
[mca16] semantic parse invalid | reason=no_usable_candidates
[mca16] experience review tick | status=completed
```

`task_jobs kind='experience.review'`: 35 → **36**, новая задача
`84cfa436040e45468f28e8cf10035e6c`, статус `completed` (created 1794177552 / finished 1794177554).
`reason=no_usable_candidates` — честный типизированный исход разбора, не сбой.

## 5. Effective-state = то, что в конфиге

```
env MCA_MEMORY_SEARCH_ENABLED       = None (не задан)
env MCA_MEMORY_COMMUNITIES_ENABLED  = None (не задан)
flags.memory_search_enabled         = True (GET /api/config)
flags.memory_communities_enabled    = True (GET /api/config)
memory.experience_learning_enabled  = True (финал)
memory.experience_review_cadence    = daily
```

Резолверы `mca_gates.memory_search_enabled` / `memory_communities_enabled` на живом кэше:
`True` для `None` и для чатов `5885953495`, `-1002661910336`, `-1004482340693`.

## 6. Оговорки

- Проба в состоянии ON на read-only соединении даёт `error` (попытка записи в режиме `ro`) —
  это ограничение пробы; авторитетное доказательство ON — живой тик из п. 4.
- `GET /api/memory/cognitive-map` для учётки `5885953495` (`role=admin`) вернул 403 на трёх чатах —
  RBAC-доступ, не дефект релиза; состояние гейтов проверено резолверами (п. 5).
