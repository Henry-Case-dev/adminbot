# Watchdog — 2.58.203

Источник: `mca_events` / `mca_incidents` в прод-SQLite (read-only).
Сырые выгрузки: `raw/watchdog_pre203.json` (широкое окно),
`raw/watchdog_post_window203.json` (только события от старта релиза),
`raw/watchdog_post203.json`.

## 1. Окно после релиза (release=1794682609 UTC 18:56:49Z → 19:08:00Z)

```
sweeps                 13, все outcome=success
first/last sweep       18:56:52Z / 19:08:00Z
incidents.created      0
incidents.updated      0
incidents.reopened     0
incidents.failed       0
takeover.discovered    0
takeover.attempted     0
takeover.recovered     0
takeover.failed        0
reconcile.checked      39, resolved 0, pending 39, inconclusive 0, failed 0
stale / progress_stalled  0 / 0
max overdue.running    0 ; max overdue.queued 0
max queued.overdue     0 ; max queued.hang 0
max heartbeat_only     1 ; deadline_bounded 0
WATCHDOG_TAKEOVER events   0
WATCHDOG_INCIDENT_FAILURE  0
incidents, созданных после релиза: []
```

Вывод: на 2.58.203 новых инцидентов, ни одного takeover и ни одного сбоя
регистрации инцидента; восстановления не понадобились (нет ни одного
реального recovery в окне). Ложных takeover нет по определению — их нет
вообще.

## 2. Широкое окно (240 мин, включает период до релиза)

```
sweeps                 241 (1/мин)
WATCHDOG_TAKEOVER      2 события
  ts 1794674882 (16:34:42Z) outcome=success reason=takeover_recovered — ДО релиза
  ts 1794679324 (17:22:04Z) outcome=success reason=takeover_recovered — ДО релиза
WATCHDOG_INCIDENT_FAILURE 0
incidents всего        15, открытых 3 (исторические, created до релиза)
reconcile непротиворечив: по всем свипам checked=779, resolved=6, pending=773
```

Оба takeover-события — реальные восстановления до деплоя (job
`1d33839d…` experience.review: `worker_lost` → `takeover_recovered`, связанные
инциденты `stage_queued`/`worker_lost`/`progress_stall` закрыты в 17:37:04Z).
Исторические инциденты не переписаны и не удалены.

## 3. Что проверялось по контракту S5

- Нет «ложного» takeover: после релиза событий takeover нет.
- Recovery фиксируется только при реальном recovery: в окне релиза реальных
  recovery не было, событий нет.
- Регистрация инцидентов не падает: `incident.failed=0`,
  `WATCHDOG_INCIDENT_FAILURE=0`.
- Ограничения не включены: `overdue`/`hang`/`scheduled_retry` = 0,
  `heartbeat_only` ≤ 1 (реальные длинные задачи в работе), `deadline_bounded=0` — нет
  универсального дедлайна исследования.
- `reconcile` не залипает: 3 проверки/свип, `failed=0`.

## 4. Journal в окне прогона

См. `postdeploy-health.txt` и `journal-summary.txt`: 0 traceback,
0 CRITICAL, 2 ERROR — существующий периодический сбой `anticliche`
(`wikipedia` `sources_unavailable`), зафиксирован 6 раз в 6 часах до релиза;
к релизу не относится. Строк `persisted speech value withheld` — 0.
Дерево чистое (`tracked dirty=0`, untracked только `.cache/`).
