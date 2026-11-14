# S5B-RECOVERY — реализация и доказательства

**Эпик:** SMART-CORRECTIVE-01, срез `S5B-RECOVERY` (owner findings W-03/W-04/W-06/W-08/W-09).
**Зависимость:** `sc/corrective-s5a` (независимо Approved, review r3).
**Ветка:** `sc/corrective-s5b` в отдельном worktree.
**База:** `sc/corrective-s5a` @ `e360738b` (S5A tip; база S5A — release/2.58.200 `13884daa` = deployed `0e4a144d` + docs).
**Код+тесты:** commit `53eea774d1c261c84e084d9be19ed5146f44a2df`.
**Worktree:** `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-756d6104`.
**Production:** не затрагивался; DDL/миграций нет; новых флагов/настроек нет; paid-вызовов нет.

## 1. Что изменено

| Файл | Изменение |
|---|---|
| `services/task_supervisor.py` | **W-04:** `recover_stale(stale_after_seconds, kinds=…, owners=…)` — существующий метод получил bounded owner/kind-предикат (без фильтров поведение прежнее). **W-06:** `heartbeat_period_seconds()` + `JobHeartbeat` (периодический heartbeat по `MCA_JOB_HEARTBEAT_SECONDS`, запись обусловлена fencing-токеном, явная остановка); `TaskSupervisor.run` держит heartbeat на всё время выполнения (включая ожидание слота); `mark_running` пишет baseline `progress_at` для kind'ов с контрактом `progress`. **W-08:** `takeover_stale(include_overdue=…)` — истёкший `deadline_at` у `running`-задачи становится законным поводом снятия lease с причиной `deadline_exceeded` (та же bounded-политика), queued не трогается; `RECOVERY_REVOKE_REASONS` расширяет S5A-guard «без токена нельзя переписать отобранную строку» на новую причину. `set_next_retry`/`requeue` state-machine не изменены. |
| `services/mca_gates.py` | **W-06/W-08/W-09:** контракт `kind → (mode, threshold_bucket)`: `progress|heartbeat|deadline` с fallback на владельца и консервативный default; `job_progress_mode/job_progress_required/job_progress_stall_seconds/job_queued_hang_seconds/job_queued_owner_managed`. Карта покрывает реальных производителей: `vision.*` (heartbeat), `vision.pending_intent`/`media_job`/`meme.pending_publish` (deadline), `initiative.observe/initiative.event/experience.review/episodes.backfill/cover_base/exploration.*` (progress/llm), `graphrag_rebuild`/`embedding_migration` (progress/archive), владельцы `asap8b01/qnd.event/mca16/mca05/summary/memory/random.uses`. Новых env-ключей нет — используются существующие `MCA_PROGRESS_STALL_{LLM,VIDEO,ARCHIVE,DEFAULT}_SECONDS`; `progress_stall_seconds(stage_type)` сохранён для `mca_trace`. |
| `services/mca_watchdog.py` | **W-08:** `progress_stalled_jobs` считает по контракту КАЖДОЙ задачи (kind → порог), `progress_at IS NULL` больше не исключает job (baseline — `created_at`); `running_contract_jobs()` — видимость heartbeat-only и deadline-only задач; `overdue_jobs(store=…)` использует существующий `TaskJobStore.overdue()`. **W-09:** `classify_queued_jobs()` — `scheduled_retry`/`deadline_pending`/`overdue`/`owner_managed`/`hang`/`normal_wait`; `hang` даёт WARN-инцидент (`stage=queued`, `stage_queued`), состояния задач не меняются. **W-08:** `sweep()` вызывает `takeover_stale(include_overdue=True)`, overdue-running попадает в обнаружение/инциденты, queued — только в диагностику. S5A-исходы/события не изменены. |
| `services/media_readiness.py` | **W-04:** `watchdog_sweep` вызывает `recover_stale(kinds=(job_kind,))` — vision-watchdog снимает lease только у своих kind'ов; чужие running-задачи не прерываются. Остальная (существующая) bounded-политика `recover_job` сохранена. |
| `services/mca_vision.py` | **W-04:** `_tick_body` и legacy-fallback `_recover_stale` ограничены `VISION_RECOVERY_KINDS = (VISION_JOB_KIND, VISION_BACKFILL_KIND)`. **W-06:** период heartbeat (`self._heartbeat_seconds`) берётся из `MCA_JOB_HEARTBEAT_SECONDS` вместо локальной константы 30 с. |
| `services/initiative_observer.py` | **W-06:** длинные фазы observe (scan/evaluate/meme) идут под `JobHeartbeat` (интервал из настройки, запись по fencing-токену), остановка в `finally`. |
| `services/media_execution.py` | **W-06:** media-джоба получает явный `deadline_at` в durable-строке (deadline-контракт одноразового внешнего вызова), а не только в checkpoint. |
| `tests/test_smart_corrective_recovery_scope.py` | Новый CONTRACT/REGRESSION-набор S5B: 17 тестов (скоуп, heartbeat, progress/overdue, queued-диагностика, bounded attempts, delivery_unknown, отсутствие дублей). |

### Почему расширен исходный write-scope среза

`slice-graph.json` для S5B перечисляет `task_supervisor.py`, `mca_watchdog.py` и два теста.
W-04 физически живёт в `media_readiness.watchdog_sweep` и `mca_vision` (вызовы
глобального `recover_stale`), W-06 — в `initiative_observer`/`media_execution`/
`mca_vision` (производители heartbeat), W-08/W-09 — в контракте порогов
(`mca_gates`) и диагностике (`mca_watchdog`). Без этих файлов требования
нереализуемы. Конфликтующих писателей не было (S5C/S5D зависят от S5B и не
стартовали). DDL не менялся.

## 2. Контракт S5B (architecture-plan §7.2/§7.4)

* **W-04.** Снятие lease ограничено семьёй задач: `TaskJobStore.recover_stale`
  принимает `kinds`/`owners`; vision/maintenance-путь передаёт только свои
  kind'ы, `media_readiness.watchdog_sweep` — `(VISION_JOB_KIND,)`. Чужие
  `running`-задачи (memory, graphrag, embedding, archive…) не прерываются,
  fencing не растёт, инцидентов не создаётся. Vision-job по-прежнему
  восстанавливается (`requeued`, fencing+1, `next_retry_at`).
* **W-06.** `MCA_JOB_HEARTBEAT_SECONDS` (env, default 15) реально используется:
  `TaskSupervisor.run` (все durable-задачи), observe-runner, vision-worker;
  media-job имеет явный `deadline_at`. Живая долгая задача не помечается stale
  и не забирается takeover'ом; после takeover heartbeat старого владельца —
  no-op по fencing.
* **W-08.** `mark_running` ставит baseline `progress_at` для kind'ов с
  контрактом `progress`; пороги — по kind (`llm/video/archive/default`), а не
  по совпадению владельца с типом стадии; `progress_at IS NULL` не исключает
  running-job из диагностики; `heartbeat`/`deadline` kind'ы не объявляются
  stalled по чужому таймеру, но остаются видимыми (`running_contract`);
  `overdue()` включён в takeover (running) и диагностику (running+queued).
* **W-09.** Queued-задачи никогда не забираются: `scheduled_retry`
  (`next_retry_at > now`), `deadline_pending` (ожидание срока/зависимости),
  `overdue` (срок истёк), `owner_managed` (у kind'а есть свой claim/retry-цикл),
  `hang` (нет срока/владельца и возраст больше порога типа) — WARN-инцидент
  без изменения состояния, `normal_wait`.
* **W-03 (совместно с S5A).** Takeover применяет существующую bounded-политику
  (`delivery_unknown` → reconcile, dangerous без checkpoint → failed, нет
  checkpoint → parked, `attempt >= max_attempts` → терминал, иначе `queued` +
  `next_retry_at`); fencing растёт; дублей работы/доставки нет.

## 3. Тесты (реальные прогоны)

Окружение: `.venv` основного дерева, `PYTHONDONTWRITEBYTECODE=1`,
`PYTHONPATH=<worktree>`, cwd — worktree; SQLite — временные БД pytest.

```text
$ pytest tests/test_smart_corrective_recovery_scope.py -q
17 passed in 11.51s

$ pytest tests/test_smart_corrective_recovery_scope.py \
    tests/test_smart_corrective_watchdog_lifecycle.py -q
45 passed in 16.66s

$ pytest tests/test_smart_corrective_watchdog_lifecycle.py \
    tests/test_smart_exec_learning_incidents.py \
    tests/test_mca17a_observability_core_round1027.py \
    tests/test_mca01_tx_task_supervisor_round1027.py \
    tests/test_smart_corrective_recovery_scope.py -q
1 failed, 150 passed in 34.95s

$ pytest tests -k "incident or watchdog or takeover or recover_stale or task_jobs" -q
90 passed, 21143 deselected in 77.76s

$ pytest tests/test_evol_vision_sync_core.py tests/test_p0_vision_fix_core.py -q
120 passed in 23.07s

$ pytest <cover/initiative/episode/experience/meme/memory/graphrag consumer suites> -q
6 failed, 388 passed in 73.55s
```

Что именно проверяет новый набор (наблюдаемые исходы, не внутренние вызовы):

* `test_vision_watchdog_leaves_foreign_running_job_untouched` — stale running
  `memory/graphrag_rebuild` после `media_readiness.watchdog_sweep`: статус
  `running`, fencing/reason не изменены, инцидентов 0; прицельный
  `recover_stale(kinds=vision)` тоже не берёт чужой kind.
* `test_scoped_recover_stale_requeues_only_matching_kind` — два stale running
  job'а: kind-скоуп возвращает только vision-id, чужой остаётся `running`;
  owner-скоуп независимо берёт memory-job.
* `test_vision_watchdog_recovers_its_own_stale_job` — vision-job → `queued` +
  `next_retry_at`, fencing+1, ровно одна активная строка, старый владелец не
  может завершить задачу.
* `test_heartbeat_period_uses_documented_setting` — период берётся из
  `MCA_JOB_HEARTBEAT_SECONDS` (в т.ч. нижняя граница 1 с).
* `test_mark_running_sets_progress_baseline_by_kind` — `initiative.observe`
  получает `progress_at`; `vision.media`/`media_job`/`meme.pending_publish` —
  нет (heartbeat/deadline-контракты).
* `test_supervisor_run_keeps_heartbeat_alive` — долгий `TaskSupervisor.run`
  реально вызывает `heartbeat` (счётчик ≥1) на интервале 1 с.
* `test_live_supervised_job_is_not_marked_stale` — живая долгая задача не
  попадает в `stale`/`takeover.discovered` полного sweep'а.
* `test_job_heartbeat_stops_on_exit` — после `stop()` фон больше не пишет.
* `test_media_job_carries_explicit_deadline` — durable media-строка имеет
  `deadline_at` в будущем.
* `test_null_progress_running_job_detected_by_kind_contract` — running
  `initiative.observe` с `progress_at IS NULL` попадает в progress-stall;
  vision-job с живым heartbeat — нет, но виден в `running_contract.heartbeat_only`.
* `test_progress_thresholds_are_kind_specific` — llm-порог ловит job,
  archive-порог тот же возраст не ловит; `progress_stall_seconds("llm")`
  сохранён для `mca_trace`.
* `test_overdue_running_job_drives_takeover` — running с живым heartbeat и
  истёкшим `deadline_at` → `queued`, `reason_code=deadline_exceeded`,
  fencing+1, `next_retry_at`, исход `recovered`.
* `test_overdue_queued_job_is_diagnosed_not_taken_over` — queued с истёкшим
  сроком остаётся `queued` с тем же fencing и виден в `queued.overdue`.
* `test_queued_buckets_distinguish_wait_retry_dependency_hang` — пять разных
  queued-строк разложены по корзинам; полный sweep не меняет ни одну из них
  (fencing 0), «зависание» даёт ровно один WARN-инцидент (`stage=queued`,
  fingerprint содержит `stage_queued`, `jobs_json` содержит job).
* `test_takeover_respects_attempt_bounds_on_overdue` — исчерпанные попытки →
  терминал `failed/attempts_exhausted`, не `recovered`.
* `test_delivery_unknown_survives_scope_and_overdue` — маркер сохраняется в
  обоих полях после sweep'ов, `next_retry_at` не ставится, `recover_job`
  возвращает `reconcile_required`, строка остаётся `interrupted`.
* `test_takeover_never_duplicates_active_work` — после recovery ровно одна
  активная строка, повторный enqueue — новая строка (без дубля работы).

**Pre-existing baseline failures (не вызваны изменением; подтверждено прогоном
на чистой базе через `git stash`):**
`test_write_points_go_through_single_writer` (census-allowlist разошёлся на
release-линии — падает и на `e360738b`), `test_initiative_coordination.py`
(4 теста publication counters), `test_soul1_w5_observer_gates.py::
test_initiative_writer_shares_core_style_and_persona`,
`test_graphrag_rebuild_asap32.py::test_not_serviceable_warning_coalesced`.
Полный набор совпал на базе и на кандидате (6/6). BACKLOG_ONLY.

**Изменённые существующие тесты:** нет. Ни один baseline-тест не утверждал
дефектное поведение W-04/W-06/W-08/W-09 (старый `progress_stalled`-тест
проверял исход, а не источник порога; vision-тесты используют vision-kind'ы и
продолжают проходить при скоупе). Добавлен один новый файл.

## 4. Маппинг строк requirements-map

| Row | Статус S5B | Доказательство |
|---|---|---|
| `SC-WD-W03` | выполнено (совместно с S5A) | `takeover_stale`: `delivery_unknown` → reconcile, dangerous без checkpoint → failed, нет checkpoint → parked, `attempt>=max_attempts` → терминал `attempts_exhausted`, иначе `queued`+`next_retry_at`; fencing+1; дублей нет. Тесты: attempt-bounds, delivery_unknown, no-duplicate, S5A-набор (28). |
| `SC-WD-W04` | выполнено | `recover_stale(kinds/owners)`; vision-путь (`watchdog_sweep`, `_tick_body`, legacy-fallback) скоупирован. Тесты: foreign untouched, scoped requeue, vision recovery. |
| `SC-WD-W06` | выполнено | `MCA_JOB_HEARTBEAT_SECONDS` применяется `TaskSupervisor.run`/observe-runner/vision-worker; media-job — явный `deadline_at`. Тесты: period setting, mark_running contract, heartbeat-alive, not-stale, stop-on-exit, media deadline. |
| `SC-WD-W08` | выполнено | baseline `progress_at` в `mark_running`; пороги по kind; NULL-progress видим; heartbeat/deadline kind'ы видимы отдельными корзинами; `overdue()` в takeover/диагностике. Тесты: 5 (см. §3). |
| `SC-WD-W09` | выполнено | `classify_queued_jobs` + WARN-диагностика без takeover; `next_retry_at>now` = scheduled retry. Тесты: buckets + overdue-queued. |

## 5. Интерфейсы для следующих срезов

**S5C-EVENTS.** `sweep()` возвращает расширенный результат: `takeover.records`
(S5A), `overdue.{running,queued}`, `queued.{scheduled_retry,deadline_pending,
overdue,owner_managed,hang,normal_wait}` (элементы: `job_id/owner/kind/attempt/
age/next_retry_in/deadline_in`), `running_contract.{heartbeat_only,
deadline_bounded}`. Per-job identity в событии и fingerprint `kind` (W-11) —
по-прежнему S5C; текущие события/REASON_CODES не менялись (`stage_queued`
уже в словаре). Новых имён событий S5B не вводит.

**S5D-OBSERVABILITY.** Диагностика queued уже даёт WARN-инцидент
(`process_id=watchdog.jobs`, `stage=queued`, `error_type=queue_no_claimer`) —
 analytics-reconciliation и WARN-событие отказа регистрации остаются S5D.
Учесть при разборе degraded: любой активный инцидент по-прежнему даёт
`STATUS_DEGRADED` в `runtime_probes._probe_incidents_active` (severity не
фильтруется) — это существующее поведение, не изменено.

**Очередь/recovery.** `TaskJobStore.recover_stale(..., kinds=, owners=)` и
`takeover_stale(..., include_overdue=)` — расширения существующих методов;
`JobHeartbeat`/`heartbeat_period_seconds()` доступны владельцам, которым нужен
явный heartbeat вне `TaskSupervisor.run`.

## 6. Ограничения и остаточный риск

* **Backfill-kind.** Vision-скоуп включает `vision.backfill`; такие строки
  прерываются (lease revoked), но requeue делает существующий `backfill_sweep`
  re-arm через cooldown — поведение прежнее, отдельного инцидента на этот
  kind watchdog не создаёт (он остаётся в семье vision).
* **Progress-порог для неизвестных kind'ов.** Не описанный в карте kind
  получает консервативный `progress` + общий порог (600 с): job с живым
  heartbeat и без прогресса даёт диагностический ERROR-инцидент, но takeover
  из progress-корзины не следует (как и раньше). Карта покрывает всех
  известных производителей; новый kind должен быть добавлен в
  `mca_gates._JOB_CONTRACT_BY_KIND`.
* **`progress_at IS NULL` baseline.** Пока собственный `progress_at`
  отсутствует, baseline берётся из `created_at`. Для строк, созданных до
  S5B и возобновлённых позже, первый sweep может дать диагностический
  progress-stall без takeover (честно: задача не публиковала прогресс).
* **Vision recovery-лимит.** `media_readiness.recover_job` ограничивает
  повторы своим `max_recoveries()` (существующая политика), а не полем
  `max_attempts` строки; generic takeover использует `attempt/max_attempts`.
  Смешение политик существовало до S5B и не менялось.
* **Deadline-driven takeover** применяется только общим watchdog'ом
  (`include_overdue=True`); vision/media-путь сохраняет свою обработку
  `deadline_exceeded`. Пересечение безопасно (атомарный CAS: второй писатель
  видит `state_changed`).
* **Effective config.** Новых флагов нет. `MCA_HEARTBEAT_WATCHDOG_ENABLED`/
  `MCA_INCIDENTS_ENABLED` default ON; `MCA_JOB_HEARTBEAT_SECONDS` default 15,
  `MCA_JOB_STALE_SECONDS` 60, `MCA_PROGRESS_STALL_{LLM,VIDEO,ARCHIVE,DEFAULT}`
  = 300/1800/3600/600. Тесты выполнялись на дефолтах (кроме точечных
  monkeypatch интервала до 1 с). Production effective-state проверяется
  DevOps при выкате (S8), не в этой полосе.
* Для строк S5B `live_required=false`; production-доступа не было. S5C/S5D и
  S8 остаются открытыми.
