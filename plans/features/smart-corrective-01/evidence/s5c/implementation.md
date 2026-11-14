# S5C-EVENTS — реализация и доказательства

**Эпик:** SMART-CORRECTIVE-01, срез `S5C-EVENTS` (owner findings W-01/W-11, owner input §9.2 C/F).
**База:** `sc/corrective-s5b` @ `7d0c6b40` (S5B Approved; код `a515d09d` поверх S5A `e360738b`).
**Ветка:** `sc/corrective-s5c` в отдельном worktree.
**Код+тесты:** commit `e5cc838f7367be830e05be5394a2eea201321f4f`.
**Worktree:** `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-e405b67c` (сохранён для независимого ревью).
**Production:** не затрагивался; DDL/миграций нет; новых флагов/настроек нет; paid-вызовов нет.

## 1. Что изменено

| Файл | Изменение |
|---|---|
| `services/mca_watchdog.py` | **W-01:** `WATCHDOG_TAKEOVER` эмитится по одному событию на реально затронутую задачу (`_emit_takeover_record`) с identity и честным исходом; агрегатное событие на класс исхода, повторяемое на каждой строке stale batch, удалено. `_merge_takeover_records` гарантирует одну запись на job_id (owner/kind/status_before/attempt/fencing добираются из обнаруженной durable-строки; `state_changed` → `no_change`). Путь без store и путь с исключением store тоже дают per-job события. **W-11:** `_track_incident` передаёт `kind` (включая queued-корзину). S5A/S5B-семантика (outcomes, lifecycle, fencing, delivery_unknown, scope, heartbeat/progress) не менялась. |
| `services/mca_incidents.py` | **W-11:** `compute_fingerprint` расширен `kind` и `job_id` (позиции старых полей сохранены, новые в конце); `open_or_update(..., kind=...)`. Исторические строки не backfill-ятся, DDL нет. `jobs_json`/`_MAX_JOBS=20`/title/impact-поведение сохранены. |
| `tests/test_smart_corrective_watchdog_events.py` | Новый CONTRACT/REGRESSION-набор S5C: 13 тестов (per-job identity/outcomes, mixed batch, отсутствие дублей, пустой batch, no-store/failed пути, payload через реальный `build_event`, durable `mca_events`, fingerprint kind/job_id, два kind → два инцидента, 20-id bound, историческая строка без изменений). |
| `tests/test_smart_corrective_watchdog_lifecycle.py` | **Обновлены только тесты, кодировавшие дефект W-11:** бывший `test_auto_resolve_only_after_all_linked_jobs_terminal` ожидал ОДИН инцидент на два job — заменён на `test_per_job_incidents_resolve_with_their_own_job`; W-05-покрытие «все связанные job терминальны» сохранено отдельным тестом на историческую aggregate-строку (`test_legacy_aggregate_incident_resolves_only_after_all_jobs`). `test_created_and_updated_counters` ожидал один инцидент на два job одного owner — теперь 2 инцидента (2 created), а `updated` проверяется повторным sweep тех же queued-задач. |
| `tests/test_smart_exec_learning_incidents.py` | **Обновлён только тест, кодировавший дефект W-11:** `test_repeated_takeover_updates_same_incident_without_closing` ожидал ту же строку для НОВОГО job того же owner/kind; разделён на «повторное наблюдение ТОЙ ЖЕ задачи → update» и «новый job → собственный инцидент». |

`services/mca_events.py` не изменялся: контракт полей уже принимает `job_id`, `entity_ids`,
`pipeline_type`, `status`, `attempt`, `error_json`; расширение DDL/словаря не требуется.

## 2. Контракт W-01 (событие)

* Одно событие `WATCHDOG_TAKEOVER` на **реально затронутую** задачу за sweep/attempt; для job,
  изменившегося между обнаружением и takeover, — `no_change/state_changed`. Дубли job_id не
  создаются. Пустой batch не эмитит takeover. Идентичные агрегаты «на каждую строку stale batch»
  отсутствуют.
* Сохранены: имя события, `component=watchdog`, `stage=takeover`, `schema_version`, §17.1
  `outcome`, `reason_code` (`takeover_recovered`/`worker_lost`) и `level` INFO/ERROR/WARN.
* Разрешённые additive-поля: `job_id`, `entity_ids=[job_id]`, `pipeline_type` (owner),
  `status` (канонический исход `recovered|failed|no_change`), `attempt`; `error_json` —
  `{kind, reason, action, status_before, fencing_token}`.
* Причина `kind` в `error_json`: в `mca_events` нет колонки `kind`, а DDL в S5C запрещён;
  JSON-поле — существующий разрешённый канал деталей (как `vision_watchdog`).
* `discovered`/`attempted` остаются фазами результата sweep (`takeover.discovered/attempted`);
  отдельного события на них нет — §7.1 допускает **не более одной записи** на job за
  sweep/attempt, итоговый исход — `recovered|failed|no_change`.

## 3. Контракт W-11 (инциденты)

* Fingerprint: `process_id|pipeline_type|stage|reason_code|error_type|dependency|kind|job_id`
  (≤400 символов). Старые поля/REASON_CODES сохранены; новые части добавлены в конец.
* Новые watchdog-инциденты привязаны к конкретному job/kind: два job одного owner разных kind
  (и любые разные job) дают отдельные инциденты; title каждого называет свой job; `jobs_json`
  каждой строки содержит свой job. `_MAX_JOBS=20` сохранён для legacy/иных вызовов.
* Исторические строки не переписываются: backfill/UPDATE fingerprint отсутствует. Строка со
  старым fingerprint остаётся читаемой; её закрытие — существующий
  `reconcile_linked_incidents` после терминального итога связанных job (W-05). Dual lookup
  сознательно не вводился: он снова слил бы разные job в legacy-строку.
* Title не «замерзает на первом job»: разные job больше не попадают в одну строку; повторное
  наблюдение того же fingerprint обновляет `last_ts/repeat_count/severity/jobs_json/impact`.

## 4. Тесты (реальные прогоны)

Окружение: `.venv` основного дерева, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=<worktree>`,
cwd — worktree; SQLite — временные БД pytest; `MCA_TELEMETRY_SPOOL_PATH` — tmp.

```text
$ pytest tests/test_smart_corrective_watchdog_events.py -q
13 passed in 5.86s

$ pytest tests/test_smart_corrective_watchdog_lifecycle.py \
    tests/test_smart_corrective_recovery_scope.py \
    tests/test_smart_exec_learning_incidents.py \
    tests/test_smart_corrective_watchdog_events.py -q
64 passed in 20.38s

$ pytest tests/test_mca17a_observability_core_round1027.py \
    tests/test_mca01_tx_task_supervisor_round1027.py -q
1 failed, 102 passed in 22.22s
# единственный провал — pre-existing census test_write_points_go_through_single_writer,
# воспроизведён на чистой базе 7d0c6b40 (worktree S5B)

$ pytest tests/test_mca13_event_contract_round1027.py tests/test_qnd_event_path.py \
    tests/test_mca17c_invariants_round1047.py -q
40 passed in 8.05s

$ pytest tests/test_self_diag_golden.py -q
39 passed in 8.36s

# Потребители/соседние контуры по тому же -k-набору, что в S5B ("incident or watchdog or
# takeover or recover_stale or task_jobs"), разбито на короткие прогоны:
$ pytest tests/test_summary_supervisor_asap41.py tests/test_summary_incident_empty_package_asap31.py \
    tests/test_summary_wave8_supervisor_runs_asap41.py tests/test_summary_coverage_asap31.py -q -k ...
18 passed, 41 deselected in 14.71s

$ pytest tests/test_post_asap5_w2_tech_reasoning.py tests/test_evol_vision_sync_core.py \
    tests/test_dossier_rebuild_round1022.py tests/test_embedding_control_plane_asap4.py \
    tests/test_asap8_v6_c03a_style_recovery.py tests/test_mca19_block_c_round1043.py -q -k ...
9 passed, 214 deselected in 6.59s

$ pytest tests/test_deploy_identity_d4c.py tests/test_extra_cover_style_jobs.py \
    tests/test_memory_identity_migration.py tests/test_nostalgia_worker.py \
    tests/test_initiative_coordination.py tests/test_self_diag_golden.py \
    tests/test_mca17a_observability_core_round1027.py \
    tests/test_mca01_tx_task_supervisor_round1027.py -q -k ...
23 passed, 305 deselected in 10.74s

$ pytest tests/test_diagnostic_probes.py -q -k ...
3 passed, 65 deselected in 5.32s
```

**Pre-existing failures (не вызваны изменением):**
`test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer`
(воспроизведён на базе `7d0c6b40`; документирован ещё в S5B);
`test_diagnostic_probes.py::TestValidation::test_time_window_is_bounded` — падает на полном
файле и на базе `7d0c6b40` (не связан с watchdog/incidents; дата-зависимый кейс), в S5C
`-k`-набор не входит. BACKLOG_ONLY.

**Изменённые существующие тесты** — только 3, кодировавшие дефект W-11 (см. §1); ни одно
S5A/S5B-поведение не ослаблено: их ключевые проверки (truthful outcomes, lifecycle, fencing,
delivery_unknown, scope, heartbeat/progress, queued) прошли без изменения ожиданий.

Что именно проверяет новый набор (наблюдаемые исходы):

* 3 stale job → ровно 3 DISTINCT события (по одному на job): у каждого свой `job_id`,
  `entity_ids`, owner в `pipeline_type`, `error_json.kind`, `status`, `attempt`; нет события
  без identity и нет дублей job_id. Смешанный batch: recovered→success/INFO,
  failed→ERROR, no_change→skipped/WARN, статусы не перепутаны.
* Повторный sweep того же batch не добавляет takeover-событий (задачи уже queued); пустой
  batch → 0 событий; no-store путь → per-job `skipped/no_change` с `action=store_unavailable`.
* `build_event` принимает payload и сохраняет `job_id/entity_ids/pipeline_type/status/attempt/
  error_json`; malformed outcome/error_json → `None`; неизвестное `job_ids` отбрасывается,
  не влияя на контракт.
* Реальный durable-путь `flush_events`: строки `mca_events` содержат job identity, owner,
  kind, status, attempt, stage/component/outcome/reason.
* fingerprint стабилен, меняется от `kind` и `job_id`; два job одного owner разных kind →
  два инцидента с разными fingerprint/title/jobs_json; `_job_append` держит 20-id bound;
  историческая строка (старый fingerprint, `jobs_json=["legacy_missing_job"]`) после sweep
  не изменена (fingerprint/title/repeat_count/resolved_at), новое наблюдение создаёт новую
  строку.

## 5. Маппинг строк requirements-map

| Row | Статус S5C | Доказательство |
|---|---|---|
| `SC-WD-W01` | выполнено (W-01) | per-job события с identity/outcome; 3-job batch — 3 distinct события, без агрегатных дублей; пустой batch — 0; payload проходит `build_event` и durable `mca_events`. Тесты `TestPerJobTakeoverEvents`, `TestEventPayloadContract`. |
| `SC-WD-W11` | выполнено (W-11) | `kind`/`job_id` в fingerprint; два job одного owner разных kind → два инцидента; title не общий; `jobs_json` 20-bound; исторические строки не backfill. Тесты `TestIncidentFingerprint` + обновлённые lifecycle/incident-тесты. |

Строки карты НЕ переводятся в VERIFIED этим документом — независимая проверка за Reviewer.

## 6. Совместимость для S5D/аналитики и ограничения

* **Имя/словарь событий не менялись.** `WATCHDOG_TAKEOVER`, `component`, `stage`, `level`,
  `schema_version`, §17.1 `outcome` и `REASON_CODES` — прежние; новые поля additive.
  Поиск по репозиторию: код-потребителей `WATCHDOG_TAKEOVER` нет (только реестр процессов
  `mca_process_registry` и тесты). `mca_event_aggregates` не затронуты.
* **Счётная семантика:** раньше было ≤1 события на класс исхода за sweep; теперь одно событие
  на затронутый job. Для аналитики это переход «на batch» → «на job» — именно требуемая
  per-job доказательная база. Дашборды, считающие recovered-события, увидят N вместо 1 для
  batch из N восстановленных задач; имена/поля для фильтрации сохранены.
* **S5D:** счётчики `incident_outcome_totals`/`takeover_outcome_totals`,
  `result["takeover"]`/`incident_outcomes` не менялись; WARN-событие отказа регистрации
  инцидента и analytics-reconciliation остаются S5D. Отказ incident-service по-прежнему
  наблюдаем существующими log.warning + счётчиками.
* **Переход fingerprint:** после выката новые наблюдения создают строки с kind/job_id, старые
  активные строки остаются до штатного reconcile (когда их job станут терминальными);
  кратковременно возможны обе. Это не backfill и не двойной учёт одной задачи: reconcile
  закрывает legacy-строку по её `jobs_json`.
* **Ограничение формулировки карты:** `SC-WD-W01.acceptance` буквально говорит «ровно одно
  WATCHDOG_TAKEOVER на sweep с N stale jobs». Делегированный бриф S5C, architecture-plan §7.1
  («для каждого обнаруженного job — не более одной записи за sweep/attempt» с per-job
  evidence) и checkpoint `workflow_state` («per-job events») требуют per-job событий.
  Реализовано per-job: N затронутых job → N различных событий; агрегат, повторяемый на каждой
  строке batch, отсутствует, пустой batch событий не даёт. PM следует согласовать текст строки
  `SC-WD-W01` с этим контрактом (сужения требований нет: индивидуальное доказательство
  восстановления — исходное требование owner §9.2 C).
* **`discovered`/`attempted`** не эмитятся отдельными событиями (см. §2): sweep уже отдаёт их
  списками, а §7.1 ограничивает одну запись на job за sweep/attempt.
* **kind в `error_json`, не отдельной колонкой** — следствие запрета DDL; при будущем
  расширении схемы `mca_events` поле можно поднять в колонку без изменения имени события.
* **Effective config (без секретов):** новых флагов нет. Использованы дефолты
  `MCA_HEARTBEAT_WATCHDOG_ENABLED`/`MCA_INCIDENTS_ENABLED` = ON, `MCA_JOB_STALE_SECONDS`=60,
  `MCA_JOB_HEARTBEAT_SECONDS`=15, progress-пороги LLM/VIDEO/ARCHIVE/DEFAULT=300/1800/3600/600.
  Тесты выполнялись на дефолтах; единственные test-only переопределения — временная SQLite и
  `MCA_TELEMETRY_SPOOL_PATH` в tmp. Тестов с выключенной функцией в этой полосе нет (кроме
  существующего S5A incident-disabled теста, не изменённого).
* Production-доступа не было; S5D и S8 остаются открытыми.
