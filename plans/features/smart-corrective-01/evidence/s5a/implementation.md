# S5A-LIFECYCLE — реализация и доказательства

**Эпик:** SMART-CORRECTIVE-01, срез `S5A-LIFECYCLE` (owner findings W-02/W-05/W-07,
безопасная часть W-03 и partial W-10).
**Ветка:** `sc/corrective-s5a` в отдельном worktree.
**База:** `release/2.58.200` @ `13884daa32e5cf2a1c05c5c43188ca299f8179f8`
(= deployed `0e4a144db476a1535ae3a2b79a7cce30354ad866` + docs).
**Код+тесты:** commit `f6db0913b5ca16443aef6c3eaf0356ec110ffb29`.
**Worktree:** `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-c89fcb78`.
**Production:** не затрагивался; DDL/миграций нет; paid-вызовов нет.

## 1. Что изменено

| Файл | Изменение |
|---|---|
| `services/task_supervisor.py` | `TaskJobStore.takeover_stale()` — атомарный bounded takeover: lease revocation + fencing, затем честный исход `recovered/failed/no_change`; `finish(..., recovery=False)` — no-token терминальная запись не переписывает припаркованную/терминальную строку и не «воскрешает» задачу, отобранную takeover'ом (`worker_lost` + fencing>0); `SETTLED_JOB_STATUSES`, `REASON_*`. `recover_stale`/`requeue`/`set_next_retry` state-machine не изменены. |
| `services/mca_watchdog.py` | `sweep()` возвращает `takeover{discovered,attempted,recovered,failed,no_change,records}`, `incident_outcomes`, `incident_reconcile`; `takeover_recovered` эмитится только при подтверждённом `running→queued`; отказ store/`job_store=None` → `failed`/`skipped` (без success); перед новыми наблюдениями — `reconcile_linked_incidents`; `_track_incident` логирует WARN и возвращает `created/updated/reopened/failed/disabled` (без рекурсивного инцидента); `recover_job` использует явный `recovery=True`; накопленные счётчики `incident_outcome_totals()`/`takeover_outcome_totals()`. |
| `services/mca_incidents.py` | `open_or_update()`: resolved-строка не переоткрывается молча — новое наблюдение создаёт новую строку (`status=reopened`), старая история/evidence сохраняются; активная строка обновляется без очистки `resolved_at`; результат различает `created/updated/reopened/failed/disabled`. Добавлен `reconcile_linked_incidents()` — авто-`resolve(evidence=...)` только когда ВСЕ связанные job в устойчивом терминале (`completed/succeeded/failed/cancelled`; `interrupted` — не итог, отсутствующий job — inconclusive). `resolve()` остаётся явным ручным путём; строки не удаляются, severity не понижается. |
| `services/initiative_observer.py` | W-07: runner фиксирует `fencing_token` после claim и передаёт его в терминальные записи; токен сбрасывается на каждый проход. |
| `services/mca_episode_jobs.py` | W-07: то же для episode-backfill runner (включая cancelled-путь). |
| `services/mca_experience_jobs.py` | W-07: то же для experience-review runner. |
| `services/media_readiness.py` | Recovery-путь vision-watchdog (`_finish_terminal`) передаёт `recovery=True` — припаркованная строка закрывается осознанно. |
| `services/cover_style_jobs.py` | `finish_cover_job(..., recovery=)`; recovery-контур styled cover закрывает припаркованные job через `recovery=True`. |
| `services/meme_initiative.py` | Recovery-путь прерванной deferred-доставки передаёт `recovery=True` (не переотправляет, честный terminal). |
| `services/mca_trace.py` | Санкционированный `control_action(cancel)` передаёт `recovery=True` (admin-путь работает и для припаркованной строки). |
| `tests/test_smart_corrective_watchdog_lifecycle.py` | Новый CONTRACT/REGRESSION-набор: 23 теста W-02/W-03/W-05/W-07/W-10. |
| `tests/test_smart_exec_learning_incidents.py` | Baseline-тест обновлён под новый lifecycle: старые утверждения (severity ERROR, отсутствие механического закрытия) сохранены; добавлен тест «инцидент закрывается только после фактического терминала job; после закрытия повтор создаёт новую строку»; helper читает `resolution_evidence`. |

### Почему расширен исходный write-scope среза

`slice-graph.json` для S5A перечисляет только `mca_incidents.py`, `task_supervisor.py`
и два теста. Бриф требует W-02 (честный outcome события), W-03 (takeover реально
возвращает job в работу) и замечание W-10; без `services/mca_watchdog.py` они
нереализуемы — там живёт эмиссия `WATCHDOG_TAKEOVER` и цикл takeover. W-07 требует
fencing в терминальных записях, а новый центральный guard иначе заблокировал бы
существующие recovery-пути (`media_readiness`, cover recovery, meme deferred,
`control_action cancel`) — поэтому эти writer'ы получили явный recovery-режим.
Конфликтующих писателей не было: S5B/S5C/S5D зависят от S5A и ещё не стартовали.
DDL не менялся.

## 2. Контракт S5A (по architecture-plan §7.1–7.5)

* **W-02.** Исходы разделены: `discovered` (stale-снимок), `attempted` (вызван
  takeover), `recovered` (подтверждённый переход в `queued`+`next_retry_at`),
  `failed` (опасный отказ/исчерпание попыток/ошибка store), `no_change`
  (нет store, нет checkpoint, `delivery_unknown`, состояние изменилось).
  `takeover_recovered` с `outcome=success` — только для непустого `recovered`.
  Пустой batch не эмитит takeover; на класс исхода — не более одного события
  за проход (per-job identity — S5C).
* **W-03 (безопасная часть; полный owner/kind-scope — S5B).** Takeover сначала
  снимает lease (`interrupted/worker_lost`, `fencing_token+1`), затем по
  существующему recovery-контракту: `delivery_unknown` → без повтора; опасный
  owner без durable checkpoint → `checkpoint_missing` (failed-исход, строка
  припаркована); нет checkpoint → припаркована (`no_change`); `attempt >=
  max_attempts` → терминальный `failed/attempts_exhausted`; иначе — `queued` +
  `next_retry_at` (`recovered`). `attempt`/`max_attempts` сохраняются, повторный
  enqueue по `coalesce_key` не создаёт дубль.
* **W-05.** `resolved_at` не очищается; resolved-инцидент не reopen'ится тем же
  evidence — новое наблюдение создаёт новую строку (история/severity/
  `resolution_evidence` старой сохраняются). Авто-resolve — только после
  терминала ВСЕХ связанных job, до новых наблюдений в sweep; `interrupted` и
  отсутствующая job-строка не закрывают инцидент. Ручной `resolve` сохранён.
* **W-07.** `finish` без токена: разрешён только из активного состояния и не
  переписывает уже устойчивую строку; для строки, отобранной takeover'ом
  (`worker_lost` + fencing>0), требуется токен нового владельца. Recovery-пути
  передают `recovery=True`. Requeue-capable владельцы (observe/episode/experience;
  vision уже был token-aware) передают fencing-токен, полученный при claim.
* **W-10 (partial).** Отказ регистрации инцидента: `log.warning` + счётчик
  `failed`, повторный `open_or_update` не вызывается, инцидент из собственной
  ошибки не создаётся. `open_or_update` различает `created/updated/reopened/
  failed/disabled`; `result["incidents"]` считает только новые строки
  (created/reopened), updates — отдельно. WARN-событие и analytics-reconciliation
  остаются S5D.

## 3. Тесты (реальные прогоны)

Окружение: `.venv` основного дерева проекта, `PYTHONDONTWRITEBYTECODE=1`,
`PYTHONPATH=<worktree>`, cwd — worktree; SQLite — временные БД pytest.

```text
$ pytest tests/test_smart_corrective_watchdog_lifecycle.py -q
23 passed in 7.14s

$ pytest tests/test_smart_corrective_watchdog_lifecycle.py \
    tests/test_smart_exec_learning_incidents.py \
    tests/test_mca17a_observability_core_round1027.py \
    tests/test_mca01_tx_task_supervisor_round1027.py -q \
    --deselect tests/test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer
128 passed, 1 deselected in 20.74s

$ pytest tests -k "incident or watchdog or takeover or recover_stale or task_jobs" -q
77 passed, 21133 deselected in 68.20s

$ pytest <cover/initiative/episode/experience/meme/vision/embedding/dossier suites> -q
497 passed, 1 warning in 78.68s
```

Что именно проверяют ключевые тесты (реальные наблюдаемые исходы):

* `test_store_failure_never_emits_recovered`, `test_missing_store_never_claims_recovery`,
  `test_durable_event_pipeline_has_no_false_recovered` — при исключении store и
  `job_store=None` нет success-события `takeover_recovered`; отказ виден как
  `failed`/ERROR или `skipped`/WARN (в т.ч. в durable `mca_events` через
  `build_event`/`flush_events`).
* `test_checkpoint_takeover_requeues_with_retry` +
  `test_durable_event_pipeline_has_confirmed_recovered` — stale+checkpoint+
  `attempt<max_attempts` → `queued`, `next_retry_at>=now`, `fencing_token+1`,
  `attempt/max_attempts` не изменены; ровно одно success-событие.
* `test_without_checkpoint_parks_without_false_success`,
  `test_dangerous_without_checkpoint_is_failed_parked`,
  `test_attempts_exhausted_is_terminal` — честные `no_change`/`failed`, без
  success; `interrupted/checkpoint_missing` и `failed/attempts_exhausted`.
* `test_outcomes_are_separated_per_job` — один sweep с тремя разными исходами:
  recovered/failed/no_change разделены, по одному событию на класс.
* `test_no_token_finish_cannot_revive_after_takeover` — после takeover старый
  владелец без токена/со старым токеном не меняет `queued`-строку; новый
  владелец с текущим токеном завершает задачу.
* `test_no_token_cannot_overwrite_terminal_record`,
  `test_active_state_finish_without_token_still_works`,
  `test_explicit_recovery_path_can_finalize_interrupted` — baseline-паритет для
  активных writer'ов + явный recovery-путь.
* `test_delivery_unknown_not_retried_by_takeover`,
  `test_requeued_job_has_no_duplicate_active_row` — слепой повтор запрещён,
  дублированной работы/доставки нет.
* `test_auto_resolve_only_after_all_linked_jobs_terminal`,
  `test_interrupted_job_keeps_incident_active`,
  `test_missing_linked_job_is_inconclusive` — авто-resolve строго по фактическому
  терминалу всех linked job; история/severity сохраняются; `resolve` с evidence.
* `test_resolved_incident_not_silently_reopened`,
  `test_new_cycle_after_auto_resolve_keeps_history` +
  обновлённый `test_incident_resolves_only_after_linked_job_terminal` — старая
  resolved-строка не переоткрывается; повтор создаёт новую строку.
* `test_failure_is_logged_and_counted_without_recursion`,
  `test_disabled_is_distinguished_from_failed`,
  `test_created_and_updated_counters` — наблюдаемость отказа/выключения,
  корректные счётчики, ни одного рекурсивного инцидента.

**Pre-existing baseline failures (не вызваны изменением; подтверждено прогоном
на чистом `release/2.58.200` через `git stash`):**
`test_write_points_go_through_single_writer` (census-allowlist разошёлся на
release-линии), `test_warning_coalesced_not_repeated` (summary_memory),
`test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons`
(source-scan), 4 теста `test_initiative_coordination.py` (publication counters).
Это BACKLOG_ONLY; S5A их не касается и не ослабляет.

## 4. Маппинг строк requirements-map

| Row | Статус S5A | Доказательство |
|---|---|---|
| `SC-WD-W02` | выполнено | sweep-исходы + события; тесты W-02 (см. §3) |
| `SC-WD-W05` | выполнено | lifecycle/open_or_update/reconcile + тесты W-05 |
| `SC-WD-W07` | выполнено для takeover/требуемых writer'ов | guard `finish` + fencing в observe/episode/experience, recovery-opt-in + тесты W-07 |
| `SC-WD-NO-02`, `SC-WD-NO-03`, `SC-WD-NO-04` | соблюдено | строки не удаляются, severity не понижается, `runtime_probes`/degraded не тронуты |
| `SC-WD-NO-05` | соблюдено | success только по подтверждённому переходу |
| `SC-WD-NO-06` | соблюдено | requeue только checkpoint+budget; дублей нет; fencing |
| `SC-WD-NO-07` | соблюдено | авто-resolve только по реальному терминалу, с evidence |
| `SC-WD-W03` (row = S5B) | частично, безопасная часть | takeover возвращает checkpointed job в работу; полный owner/kind scope, heartbeat, progress, queued-диагностика — S5B |
| `SC-WD-W10` (row = S5D) | частично | log WARN + counters + статусы без рекурсии; WARN-событие/analytics — S5D |

## 5. Интерфейсы для следующих срезов

**S5B-RECOVERY.** `takeover_stale(stale_after_seconds, retry_delay_seconds,
dangerous_owners, now)` — сюда добавляются owner/kind-scope и kind-политика;
`recover_stale()` сохранён без изменений как lease-revocation для
специализированных watchdog'ов (vision). `finish(..., recovery=True)` —
единственный явный recovery-путь; `SETTLED_JOB_STATUSES` — общий терминальный
набор; `takeover_stale` не трогает queued (W-09 остаётся S5B).

**S5C-EVENTS.** `sweep()` уже даёт один batch-summary на класс исхода и per-job
`takeover.records` (job_id/owner/kind/status_before/attempt/max_attempts/
fencing_token/action/reason/outcome); остаётся добавить разрешённые additive-поля
(`job_id`, `entity_ids`, `status`, `attempt`) и расширение fingerprint `kind`
(W-11). Порядок «reconcile до новых наблюдений» уже обеспечен.

**S5D-OBSERVABILITY.** `incident_outcome_totals()`, `takeover_outcome_totals()`
и `result["incident_outcomes"]/["takeover"]` готовы как счётчики; WARN-событие
отказа регистрации и analytics-reconciliation добавляются в S5D без рекурсии
(`_track_incident` сейчас пишет `logger.warning`).

## 6. Ограничения и остаточный риск

* Bounded-политика использует существующий `max_attempts`; большинство
  producer'ов ставят default 1 → takeover терминализует (`attempts_exhausted`),
  а не повторяет. Это соответствует «исчерпание попыток — существующий terminal
  outcome»; heartbeat-контракт (W-06/S5B) уменьшит ложные takeover.
* Requeue безопасен только при durable payload-checkpoint; без него задача
  припаркована (`interrupted`) и восстанавливается явным `recover_job`.
* Fencing терминальных записей покрывает владельцев, которых этот takeover
  реально возвращает в очередь (observe/episode/experience; vision уже был
  token-aware). Остальные W-07-writer'ы защищены центральным guard'ом для
  терминальных записей, но их checkpoint-write'ы без токена остаются риском
  (кандидат в S5B writer-контракт).
* Проверка «no-token finish» использует состояние+`reason_code=worker_lost`+
  fencing как различитель; ручной `resume` ставит другой reason и продолжает
  работать.
* Авто-resolve ограничен `process_id='watchdog.jobs'` и непустым `jobs_json`;
  отсутствующая (pruned) job-строка оставляет инцидент активным (inconclusive).
* Effective config: `MCA_HEARTBEAT_WATCHDOG_ENABLED`/`MCA_INCIDENTS_ENABLED`
  default ON; тесты выполнялись на дефолтах (baseline-тест утверждает ON);
  новых флагов/shadow-режимов нет. В production effective-state проверяется
  DevOps при выкате (S8), не в этой полосе.
* Для S5A-строк `live_required=false`; production-доступа не было, live-проверки
  не заявляются. S5B/S5C/S5D и S8 остаются открытыми.
