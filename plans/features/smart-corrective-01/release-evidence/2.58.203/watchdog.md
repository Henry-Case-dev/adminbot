# Watchdog — 2.58.203

Источник: `mca_events` / `mca_incidents` в прод-SQLite (read-only).
Сырые выгрузки: `raw/watchdog_pre203.json` (широкое окно 240 мин),
`raw/watchdog_post_window203.json` (первое «тихое» окно 18:56:52–19:08:00Z),
`raw/watchdog_release_window_203.json` (полное окно релиза до 19:18:03Z),
`raw/watchdog_post203.json` (агрегат широкого окна).

## 1. Окно после релиза (release=1794682609 UTC 18:56:49Z → 19:18:03Z)

```
sweeps                 22 (18:56:52Z … 19:17:02Z), все outcome=success
incidents.created      1  (19:14:01Z — см. §1.1)
incidents.updated      0
incidents.reopened     0
incidents.failed       0
takeover.discovered    1
takeover.attempted     1
takeover.recovered     1
takeover.failed        0
takeover.no_change     0
reconcile.checked      69, resolved 0, pending 69, inconclusive 0, failed 0
stale                  всего 1 (в свипе 19:14:01)
progress_stalled       0
max overdue.running    0 ; max overdue.queued 0
max queued.overdue     0 ; max queued.hang 0 ; max scheduled_retry 1 (в 19:14)
max heartbeat_only     1 ; deadline_bounded 0
WATCHDOG_TAKEOVER      1 (19:14:01Z, outcome=success, reason=takeover_recovered)
WATCHDOG_INCIDENT_FAILURE  0
последний свип 19:17:02Z: takeover 0, incidents 0, queued.normal_wait 1
```

### 1.1 Единственный takeover после релиза (19:14:01Z)

```
event           WATCHDOG_TAKEOVER  outcome=success  reason=takeover_recovered
job             1e900f46aef448bd923009ca9ed3235a  (experience.review / mca16)
sweep usage      stale=1, takeover{discovered:1, attempted:1, recovered:1, failed:0},
                 incident{created:1}, queued{scheduled_retry:1}
incident         inc_583cdba56ad542eea8f3a889db26cb4e
                 fingerprint watchdog.jobs|mca16|takeover|worker_lost|
                 ||experience.review|1e900f46…
                 severity ERROR, stage takeover, first_ts=last_ts=19:14:01Z,
                 repeat_count=1, resolved_at IS NULL на 19:18:03Z
                 (повторная проверка 19:20:41Z — то же состояние)
```

Как читать честно:
- Это **не ложный** takeover: свип зафиксировал реальную потерю воркера
  (`worker_lost` по отсутствию heartbeat), попытка одна, исход `recovered`,
  `failed=0`; `queued.scheduled_retry=1` — задача возвращена в очередь.
- Это **повторяющийся** класс: тот же fingerprint (`experience.review`,
  `worker_lost`) срабатывал ДО релиза — 16:34:42Z и 17:22:04Z, оба раза
  `takeover_recovered`, тогда связанные инциденты закрылись через ~15 минут
  (17:37:04Z). Текущий инцидент на момент последнего наблюдения ещё открыт;
  закрытие зависит от завершения восстановленной задачи, а не от релиза.
- Ни один инцидент не создан из-за промпт-слоя/метки чек-апа; релизная
  дельта — тесты/evidence + метка, runtime-путь watchdog не менялся
  (в 2.58.203 vs 2.58.202 watchdog-код идентичен).

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

- Нет «ложного» takeover: единственный takeover после релиза (19:14:01Z)
  зафиксирован по `worker_lost` и завершился `recovered`; задачи, которая
  была бы жива, он не отбирал (recovered=1, failed=0, no_change=0).
- Recovery фиксируется только при реальном recovery: событие
  `takeover_recovered` соответствует реальной потере воркера, а не
  плановому тику.
- Регистрация инцидентов не падает: `incident.failed=0`,
  `WATCHDOG_INCIDENT_FAILURE=0`; инцидент создан ровно один и связан с
  takeover.
- Ограничения не включены: `overdue`/`hang` = 0, `heartbeat_only` ≤ 1,
  `deadline_bounded=0`.
- `reconcile` не залипает: `failed=0` на всех свипах.
- Исторические инциденты (15 до релиза, 3 открытых) не переписаны и не
  удалены; после релиза добавился один новый (`inc_583cdba5…`).

## 3.1 Что осталось открытым

`inc_583cdba56ad542eea8f3a889db26cb4e` (ERROR, `worker_lost`,
`experience.review`) на 19:18:03Z (и при повторной проверке 19:20:41Z) не
закрыт. Это существующий повторяющийся класс (два таких же события до
релиза, оба закрылись после успешного восстановления), поэтому это не
блокер релиза, но и не «всё чисто»: в последнем свипе задача уже в
`normal_wait` (перезапуск идёт), закрытие ожидается после её завершения.
Наблюдение продолжается на стороне агентов обычной телеметрией, без задачи
владельцу. Если инцидент не закроется после восстановления задачи — это
повод для отдельного разбора watchdog/experience.review, не для отката
2.58.203.

## 4. Journal в окне прогона

См. `postdeploy-health.txt` и `journal-summary.txt`. В окне до 19:08:51Z:
0 traceback, 0 CRITICAL, 2 ERROR (существующий `anticliche`/wikipedia). В
расширенном окне 19:09–19:20Z добавились: 2 `services.llm_client` ERROR
(`ReadTimeout`/`total_budget_exceeded` к nano-gpt.com), 4 `services.summary_memory`
ERROR как следствие того же таймаута (`graph_extract_failed`, «batch kept,
pipeline continues») и 1 `services.mca_events` INCIDENT — тот самый
takeover-инцидент из §1.1. Ни одного traceback; CRITICAL нет; строк
`persisted speech value withheld` — 0. Дерево чистое (`tracked dirty=0`,
untracked только `.cache/`).
