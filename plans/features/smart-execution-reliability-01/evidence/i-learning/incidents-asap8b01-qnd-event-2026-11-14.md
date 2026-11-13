# I5 — реальные причины инцидентов `asap8b01` и `qnd.event`

Стадия I5 среза `S10-LEARNING-INCIDENTS` (SXR-I5-01), эпик
`SMART-EXECUTION-RELIABILITY-01`. Только чтение production-артефактов и
локальный анализ; production не менялся, detector не отключался, severity не
понижалась, инциденты не закрывались.

## 1. Что зарегистрировано

| Поле | Значение | Источник |
|---|---|---|
| `pipeline_type` | `asap8b01` (owner job'а `initiative.observe`) | `services/initiative_observer.py:86`, `:1198` |
| `pipeline_type` | `qnd.event` (owner job'а `initiative.event`) | `services/initiative_observer.py:1263`, `:1357` |
| `reason_code` | `incident_opened` (открытие/повтор уже открытого) | `services/mca_incidents.py:164-169` |
| stage / причина | `takeover` / `worker_lost`; severity `ERROR` | `services/mca_watchdog.py:129-162` |
| инциденты | `inc_4627f4bd625945b6b330f33bb7f47184` (asap8b01), `inc_0bf85af44dbb48308eae5d672fd9db95` (qnd.event) | `plans/features/p0-init-meme-ux-diag/release-258192/live-trace-2.58.192.json:13-17` |

Первое известное открытие `asap8b01`: **2026-10-22T06:21:11Z**,
`stage=takeover`, `reason_code=incident_opened`, entity `inc_4627...`,
`repeat_count=2` (`plans/features/_audit-2026-10-23/prod-checks/raw/main2.txt:148-149`,
`.../raw/main3.txt:81`). Оба инцидента повторно открыты/обновлены при
рестарте релиза 2.58.192 **2026-11-11T19:05:11Z**: в журнале ровно
`2× INCIDENT incident_opened (qnd.event, inc_0bf85af4...)` и
`2× INCIDENT incident_opened (asap8b01, inc_4627f4bd...)` —
`plans/features/p0-init-meme-ux-diag/release-258192/deploy.md:116`,
`live-trace-2.58.192.json:13-17`.

## 2. Реальная причина

Оба инцидента — **watchdog-takeover прерванных пайплайнов при штатном
рестарте сервиса**, а не сбой incident detector:

1. `initiative.observe` (owner `asap8b01`) и событийный `initiative.event`
   (owner `qnd.event`) — single-flight job'ы с LLM-фазами; при остановке
   процесса на деплое их `task_jobs`-строки остаются `running` с прежним
   `heartbeat_at`.
2. Startup-watchdog (`mca_watchdog.startup_check → sweep`) видит `running`
   без свежего heartbeat, вызывает `TaskJobStore.recover_stale()` (помечает
   `interrupted`) и открывает инцидент `process_id=watchdog.jobs`,
   `pipeline_type=<owner>`, `stage=takeover`, `reason_code=worker_lost`,
   `severity=ERROR` (`services/mca_watchdog.py:59-71`, `:96-162`;
   `services/task_supervisor.py:546-575`).
3. Это корректная классификация: работа процесса действительно потеряна,
   инициативный проход оборван. Severity `ERROR` обоснована; понижать её
   или автозакрывать инцидент нельзя (`acknowledged ≠ resolved`,
   `services/mca_incidents.py:197-248`).

Две строки `incident_opened` на один entity — **не два инцидента**: первая
создаёт строку, вторая — обновление той же незакрытой строки, и
`open_or_update` для любого не-resolution update эмитит тот же
`incident_opened` (`services/mca_incidents.py:164-169`). В durable-таблице
на каждый owner одна строка (`repeat_count`), что подтверждено raw-выгрузкой
аудита (`main3.txt:81`) и тестом
`test_repeated_takeover_updates_same_incident_without_closing`.

## 3. Сверка с текущими эпиками (не дублировать)

| Эпик/артефакт | Что уже зафиксировано |
|---|---|
| `p0-init-meme-ux-diag` 2.58.192 | `qnd.event`/`asap8b01` — watchdog-takeover прерванных пайплайнов при старте; объяснение всех 5 ERROR журнала (`release-258192/deploy.md:116`, `live-trace-2.58.192.json:13-17`) |
| `release-then-migrate` | 4 активных ERROR-инцидента `worker_lost` (memory/summary/vision.media/asap8b01), все `last_ts` до cutover; это устаревшие строки реестра, перенесённые снапшотом, не дефект работы бота (`evidence/final-acceptance-and-backup.md:39,101`) |
| `samples-ux` / `p0-vision-universal` | тот же restart-artifact паттерн для `vision.media`: drain timeout старого PID → `INCIDENT incident_opened` takeover на новом; «pre-existing restart pattern, NOT a defect» (`samples-ux/evidence/release/deploy.json:79`; `p0-vision-universal/evidence/release-25894/acceptance/README.md:76`) |

Инциденты **не закрываются** этим срезом: строки остаются в реестре до
проверки владельцем/админом с `resolution_evidence` (штатный контракт).

## 4. Подтверждённый дефект жизненного цикла — отдельная задача

Найдена структурная причина, по которой тот же `worker_lost` может стать
**ложным даже без рестарта** (в границах I5, но вне write scope этого среза):

* `initiative_observer.run()` обновляет heartbeat **один раз** в начале
  (`services/initiative_observer.py:1958-1965`); периодического heartbeat во
  время LLM-фаз нет (в отличие от `mca_vision._job_heartbeat_loop`,
  `services/mca_vision.py:1594-1602`).
* `TaskSupervisor.run()`/`TaskJobStore.mark_running` также ставят heartbeat
  только на старте (`services/task_supervisor.py:459-483`).
* Порог stale — `MCA_JOB_STALE_SECONDS`, default **60 c**
  (`services/mca_gates.py:1351-1353`).

Следствие: инициативный проход длительностью >60 c может быть объявлен
потерявшим владельца живым watchdog'ом (false `worker_lost` с takeover),
плюс каждый плановый рестарт штатно порождает ERROR-инцидент. Исправление
требует изменения `TaskSupervisor`/`initiative_observer` (периодический
heartbeat на длинных фазах; отдельная маркировка shutdown-прерывания), это
самостоятельный модуль. **Куда передать:** существующая задача
`SELF-DIAG-01` — остаток этапа H консолидирован в этот эпик
(`plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md`, §0;
`plans/progress_scope.json` queue_note 2026-11-14) и/или линия MCA
observability `mca-17a` (TaskSupervisor/heartbeat/watchdog). PM —
дедуплицировать в `plans/backlog.md` с этим evidence; отдельный эпик не
создавать.

Наблюдение (BACKLOG_ONLY, не блокер): повторный update незакрытого
инцидента эмитит `reason_code=incident_opened`, а не отдельный
`incident_updated`; кода `incident_updated` нет в реестре `mca_events`
(`services/mca_events.py:106-112`), добавление потребовало бы расширения
реестра (I4-контур) — в этом срезе не менялось.

## 5. Проверки

* `tests/test_smart_exec_learning_incidents.py` (2 теста, CONTRACT/REGRESSION):
  реальный путь `DatabaseService + TaskJobStore + mca_watchdog.sweep +
  mca_incidents` на владельцах `asap8b01`/`qnd.event`:
  - takeover убитого рестартом job'а даёт `stage=takeover`,
    `severity=ERROR`, `resolved_at IS NULL`, `fallback_used=0`; ack не
    закрывает инцидент; detector/watchdog включены (defaults);
  - повторный takeover — та же строка (`incident_id`), `repeat_count+1`,
    severity остаётся `ERROR`, инцидент не resolved.
* Mutation-proof: принудительное понижение severity до `WARN` в
  `mca_incidents.open_or_update` → **1 failed, 1 passed**
  (`mutation-i5-severity-warn.txt`); после восстановления — **2 passed**.
* Тесты I5 — характеристические (на базе `d20a7f73` тоже зелёные), потому
  что in-scope дефекта detector'а нет; их задача — запретить «зелёную
  панель» (понижение severity/самозакрытие) и зафиксировать реальную
  причину. RED-on-base относится к SXR-I6 (см. binding report).

## 6. Остаточное (честно)

* Текущее состояние этих строк в production на 2026-11-14 повторно не
  выгружалось (не требуется для причины; production read-only не
  использовался). Строки по контракту остаются незакрытыми до ручного
  `resolve` с evidence — это не дефект и не задача владельцу.
* F-I5-1 (heartbeat длинных job'ов) — отдельный модуль, см. §4; в этом
  срезе не исправлялся, чтобы не менять lifecycle без независимого review.
