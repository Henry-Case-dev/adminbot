# S5D-OBSERVABILITY — реализация и доказательства

**Эпик:** SMART-CORRECTIVE-01, срез `S5D-OBSERVABILITY` (owner finding W-10; owner input §9.2 E; architecture-plan §7.5; linked acceptance AC-24).
**База:** `sc/corrective-s5c` @ `5d7c4798` (S5C Approved; код `e5cc838f` поверх S5B `7d0c6b40`).
**Ветка:** `sc/corrective-s5d` в отдельном worktree.
**Код+тесты:** commit `4185803c46914a593cdf5ebfa5df5bebd5a2585d`.
**Worktree:** `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-e6bece84` (сохранён для независимого ревью).
**Production:** не затрагивался; DDL/миграций нет; новых флагов/настроек нет; paid-вызовов нет.

## 1. Что изменено

| Файл | Изменение |
|---|---|
| `services/mca_watchdog.py` | **W-10:** любой подтверждённый отказ регистрации инцидента наблюдаем. Исключение из `mca_incidents.open_or_update` и уже существующий честный ответ `{"status": "failed"}` (в т.ч. после внутренне перехваченного DB-сбоя) логируются watchdog-логгером и эмитят WARN-событие `WATCHDOG_INCIDENT_FAILURE`; `open_or_update` повторно НЕ вызывается, инцидент из собственной ошибки не создаётся. **S5D-аналитика:** итоговый `WATCHDOG_SWEEP` (существующее имя/событие) публикует bounded-сводку прохода в существующем разрешённом JSON-поле `usage_json`: исходы `discovered/attempted/recovered/failed/no_change`, `incident created/updated/reopened/failed/disabled`, reconcile-статусы, `overdue {running,queued}`, все queued-корзины, `running_contract {heartbeat_only,deadline_bounded}`, `progress_stalled/stale`, а также накопленные `takeover_totals`/`incident_totals`. S5A/S5B/S5C-поведение (per-job события, lifecycle, fencing, delivery_unknown, scope, heartbeat/progress) не менялось. |
| `tests/test_smart_corrective_watchdog_observability.py` | Новый CONTRACT/REGRESSION-набор S5D: 6 тестов на реальной SQLite и реальном `mca_events` — оба пути отказа (raise и `status=failed`) дают лог + WARN + счётчик без рекурсии; recovery-исход не меняется; счётчики различают created/updated/reopened/failed/disabled; `WATCHDOG_SWEEP.usage_json` содержит outcome- и диагностические счётчики; сводка и WARN-событие durable в `mca_events` (успех и `level=WARN` соответственно). |

`services/mca_events.py`, `services/mca_incidents.py`, `services/mca_trace.py`, `services/mca_process_registry.py` не изменялись: `WATCHDOG_SWEEP` уже зарегистрирован как событие `watchdog.jobs`, `usage_json` — существующее разрешённое JSON-поле, `WATCHDOG_INCIDENT_FAILURE` — свободная ось `event_name` (словарь `REASON_CODES` не расширялся; `reason_code` не передаётся). DDL не требуется.

## 2. Контракт W-10 (отказ регистрации)

* `_track_incident` различает два фактических пути отказа:
  * исключение из `open_or_update` → `log.warning` + WARN `WATCHDOG_INCIDENT_FAILURE` (в `error_json.type` — класс исключения, без сырого сообщения/R17);
  * возвращённый `{"status": "failed"}` (единственный путь внутреннего DB-сбоя `mca_incidents`: он сам перехватывает transaction error и возвращает статус, а также отказ `write_transaction`) → `log.warning` + WARN-событие с `error_json.type` из ответа (`OperationalError` и т.п.).
  * Неожиданный результат без статуса тоже даёт WARN (`InvalidRegistrationResult`) и `failed`, а не молчаливый 0.
* Рекурсия исключена: в обоих путях `open_or_update` вызывается ровно один раз (тесты считают вызовы и проверяют пустую таблицу `mca_incidents`).
* Счётчики bounded: `_INCIDENT_OUTCOME_KEYS = created|updated|reopened|failed|disabled` (фиксированный набор), доступны через существующий `incident_outcome_totals()` и per-sweep `result["incident_outcomes"]`; `disabled` не смешивается с `failed`.
* `WATCHDOG_INCIDENT_FAILURE`: `component=watchdog`, `stage` исходной регистрации (`takeover|progress|queued`), `outcome=failed`, `level=WARN`, `job_id`, `pipeline_type` (owner), `error_json={type,kind,stage}`. Имя не входит в `REASON_CODES`-словарь, т.к. это ось `event_name`; словарь причин и его счётные тесты не тронуты.

## 3. Контракт сводки sweep (analytics)

`WATCHDOG_SWEEP` теперь эмитится один раз в конце прохода (после incident/progress/queued-диагностики) с `usage_json` фиксированной формы:

```text
stale, progress_stalled, incidents,
takeover {discovered, attempted, recovered, failed, no_change},
takeover_records, takeover_totals {recovered, failed, no_change},
incident {created, updated, reopened, failed, disabled},
incident_totals {...}, reconcile {checked, resolved, pending, inconclusive, failed},
overdue {running, queued},
queued {scheduled_retry, deadline_pending, overdue, owner_managed, hang, normal_wait},
running_contract {heartbeat_only, deadline_bounded}
```

* Только числа/фиксированные ключи — форма не растёт с размером batch; `usage_json` проходит существующий `build_event` sanitize/2000-символьный bound.
* Имя события, `outcome=success`, `level=INFO`, `component`, `stage=sweep` сохранены; per-job `WATCHDOG_TAKEOVER` не менялись.
* Накопленные totals — process-local (bounded-счётчики); durable per-проходные числа лежат в самом `usage_json` каждого события.

## 4. Тесты (реальные прогоны)

Окружение: `.venv` основного дерева, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<worktree>`, cwd — worktree; SQLite — временные БД pytest; `MCA_TELEMETRY_SPOOL_PATH` — tmp.

```text
$ pytest tests/test_smart_corrective_watchdog_observability.py -q
6 passed in 9.92s

$ pytest tests/test_smart_corrective_watchdog_events.py \
    tests/test_smart_corrective_watchdog_lifecycle.py \
    tests/test_smart_corrective_recovery_scope.py \
    tests/test_smart_exec_learning_incidents.py \
    tests/test_smart_corrective_watchdog_observability.py -q
70 passed in 21.41s

$ pytest tests/test_mca17a_observability_core_round1027.py \
    tests/test_mca01_tx_task_supervisor_round1027.py \
    tests/test_mca13_event_contract_round1027.py \
    tests/test_qnd_event_path.py \
    tests/test_mca17c_invariants_round1047.py -q
1 failed, 142 passed in 27.49s
# единственный провал — pre-existing census test_write_points_go_through_single_writer;
# независимо воспроизведён на базе S5C 5d7c4798 (worktree e405b67c): 1 failed,
# те же счётчики (database.py:230 vs allow 207 и т.д.); изменением не вызван.

$ pytest tests/test_self_diag_golden.py tests/test_asap8_v6_c03a_style_recovery.py -q
75 passed in 11.19s

$ pytest tests/test_diagnostic_probes.py -q -k "watchdog or incident or takeover or recover or stale or progress"
3 passed, 65 deselected in 4.84s

$ pytest tests/test_summary_supervisor_asap41.py tests/test_summary_incident_empty_package_asap31.py \
    tests/test_summary_wave8_supervisor_runs_asap41.py tests/test_summary_coverage_asap31.py \
    -q -k "incident or watchdog or takeover or recover_stale or task_jobs"
18 passed, 41 deselected in 14.95s

$ pytest tests/test_post_asap5_w2_tech_reasoning.py tests/test_evol_vision_sync_core.py \
    tests/test_dossier_rebuild_round1022.py tests/test_embedding_control_plane_asap4.py \
    tests/test_asap8_v6_c03a_style_recovery.py tests/test_mca19_block_c_round1043.py \
    -q -k "incident or watchdog or takeover or recover_stale or task_jobs"
9 passed, 214 deselected in 7.08s
```

**Изменённые существующие тесты:** нет. Ни один существующий тест не кодировал прежнее поведение (отсутствие WARN-события/сводки) или порядок `WATCHDOG_SWEEP`; S5A-тест `test_failure_is_logged_and_counted_without_recursion` прошёл без изменения ожиданий и по-прежнему проверяет лог/счётчик/отсутствие рекурсии.

Что именно проверяет новый набор (наблюдаемые исходы):

* `status=failed` от `open_or_update` → ровно один вызов (без retry), `result.incident_outcomes.failed=1`, глобальный счётчик +1, WARN-событие с `job_id/owner/stage/error_json.type`, лог watchdog-логгера, пустая `mca_incidents`, recovery всё равно выполнена (`queued`).
* Исключение из `open_or_update` → тот же набор наблюдаемых эффектов с `type=RuntimeError`; инцидент не создан; recovery не отменена.
* Реальные created→updated→reopened→failed на одной БД: каждая фаза даёт ровно свой ключ счётчика, `created/reopened` двигают `result.incidents`, `failed` — нет; набор ключей bounded и неизменен; история resolved-строки сохранена (2 строки).
* Один проход с 2 stale + heartbeat-only running + queued hang + queued overdue: `WATCHDOG_SWEEP.usage_json` даёт takeover `{discovered:2,attempted:2,recovered:2,...}`, `incident.created=3`, `overdue.queued=1`, `queued.hang=1`, `queued.overdue=1`, `running_contract.heartbeat_only=1`; ровно одно сводное событие на проход.
* Реальный durable-путь `flush_events`: строка `mca_events WATCHDOG_SWEEP` (INFO/success/watchdog/sweep) с parseable `usage_json`; строка `WATCHDOG_INCIDENT_FAILURE` (WARN/failed/watchdog) с `job_id` и типом ошибки.

## 5. Маппинг строк requirements-map

| Row | Статус S5D | Доказательство |
|---|---|---|
| `SC-WD-W10` | выполнено на уровне реализации | raise ⇒ WARN + лог, без рекурсии (счётчик вызовов = 1, `mca_incidents` пуст); счётчики `created/updated/reopened/failed/disabled` различаются; WARN durable в `mca_events`; сводка `WATCHDOG_SWEEP.usage_json` доступна существующей аналитике. Тесты `TestIncidentRegistrationFailure`, `TestIncidentOutcomeCounters`, `TestSweepDiagnosticsExposure`, `TestAnalyticsDurability`. |
| `AC-24` (linked) | выполнено на уровне реализации | Ошибки incident service наблюдаемы (лог + WARN + счётчик + сводка), но не создают рекурсивный инцидент и не меняют recovery-исход. |

Строки карты НЕ переводятся в VERIFIED этим документом — независимая проверка за Reviewer.

## 6. Ограничения и честная неопределённость

* Production не затрагивался; реальные production-события не наблюдались. Future/live-проверки — за S8/DevOps.
* `mca_event_aggregates` пополняется только ERROR-событиями с `error_json`; WARN `WATCHDOG_INCIDENT_FAILURE` durable в `mca_events` и виден аналитике по этому событию, но в aggregate-таблицу не попадает. Это существующая семантика агрегатов (не дефект S5D); менять её — вне write scope.
* Накопленные `incident_totals`/`takeover_totals` process-local и обнуляются при рестарте процесса; измеренные за проход числа durable в `usage_json` каждого `WATCHDOG_SWEEP`.
* `WATCHDOG_SWEEP` теперь эмитится в конце прохода (после incident/progress/queued-диагностики), чтобы нести итоговые счётчики; имя/поля/уровень сохранены. Потребителей, зависящих от его позиции между per-job событиями, в репозитории нет (проверено поиском).
* W-12 (смысл 72 повторов и атрибуция production-инцидентов) остаётся `NEEDS_PRODUCTION_DATA`; S5D его не затрагивает.
* Effective config (без секретов): новых флагов нет; использованы дефолты `MCA_HEARTBEAT_WATCHDOG_ENABLED`/`MCA_INCIDENTS_ENABLED` = ON, stale=60s, heartbeat=15s. Тесты выполнялись с включённой функцией; единственные test-only переопределения — временная SQLite и `MCA_TELEMETRY_SPOOL_PATH` в tmp. Существующий S5A-тест incident-disabled не изменён и проходит.
