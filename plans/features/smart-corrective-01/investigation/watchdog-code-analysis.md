# WATCHDOG-INCIDENTS — анализ кода развёрнутого контура (SMART-CORRECTIVE-01 §9)

**Статус:** read-only расследование завершено. Ни один production-инцидент не объявляется
устранённым или объяснённым; реализация исправлений в этой полосе не выполнялась.

**Идентичность кода:** production 2.58.200, deployed `0e4a144d`; читался release-checkout
`…\Worktrees\…\smart-execution-reliability-01-45d7d5f19c3b-db50b61f` (HEAD `13884daa` =
`0e4a144d` + docs). Все `file:line` ниже — по этому checkout. `services/mca_watchdog.py`,
`task_supervisor.py`, `mca_incidents.py` в нём побайтно совпадают с DEV-деревом
(`sha256` совпал), поэтому локальные проверки на DEV-копии применимы к развёрнутой логике.

**Источник требований:** `plans/owner_inputs/2026-11-14-smart-corrective-01.md` §9.2 A–F
(строки 609–665), §9.3 (запреты), AC-20…AC-24 (строки 860–878).

**Гейты в локальном прогоне:** `MCA_HEARTBEAT_WATCHDOG_ENABLED=true`,
`MCA_INCIDENTS_ENABLED=true` (значения по умолчанию; production-effective требует DevOps).

**Метод:** чтение развёрнутого кода; локальные read-only пробы на временных SQLite-БД
(`probe_watchdog_semantics.py`, 10 сценариев); прогон существующих тестов контура
(`16 passed` — baseline до изменений). Production не затрагивался, схема не менялась.

**Артефакты пробы:**
`plans/features/smart-corrective-01/investigation/watchdog-probe-results.json`
(sha256 `2C18E609001635474242A5C22CBA08C63C41A0AD8A4B58F41EFBF98E481EFEDE`),
скрипт `…/investigation/watchdog_probe_semantics.py`
(sha256 `761CB5FCCB01F6CCF70A907C8F2F13B4B475B952A8F80CE47A4DD2208706258A`).
Локальный запуск: `.venv\Scripts\python.exe`, `PYTHONDONTWRITEBYTECODE=1`, cwd/basetemp —
вне репозитория; release-worktree после прогона чист (`git status` пуст).

---

## 1. Сводная таблица находок

| ID | Sev | `file:line` (deployed) | Классификация | Минимальный фикс | Тест | Production data |
|----|-----|------------------------|---------------|------------------|------|-----------------|
| W-01 | HIGH | `services/mca_watchdog.py:128-135`; `services/mca_events.py:365-398,566-568` | CONFIRMED_DEFECT | Один агрегат-событие на проход + per-job записи через разрешённые поля (`job_id`, `entity_ids`); не эмитить ничего при пустом batch | 3 stale jobs → ровно 1 `WATCHDOG_TAKEOVER`, `entity_ids` содержит 3 id; событие реально доезжает до `build_event` | — |
| W-02 | HIGH | `mca_watchdog.py:109-117,129-135,50-56` | CONFIRMED_DEFECT | Разделить discovered/attempted/recovered/failed/no_change; `takeover_recovered` только при подтверждённом переходе; при отказе — отдельный reason/level | monkeypatch `recover_stale` → raise ⇒ нет `takeover_recovered`; нет store ⇒ нет success-события | — |
| W-03 | HIGH | `task_supervisor.py:547-569`; `mca_watchdog.py:96-143,194-246`; `mca_process_registry.py:899-916` | CONFIRMED_DEFECT | После `recover_stale` применить существующую политику `recover_job`/`requeue`+`next_retry_at` с bounded `attempt/max_attempts`; `delivery_unknown`/dangerous — как сейчас | stale+checkpoint ⇒ `queued`+`next_retry_at`, fencing+1; dangerous без checkpoint ⇒ `checkpoint_missing`; attempt исчерпан ⇒ терминал | — |
| W-04 | HIGH | `media_readiness.py:1756-1801`; `mca_vision.py:4528-4543,1594-1605,3203`; `media_readiness.py:1528-1531` | CONFIRMED_DEFECT | Ограничить `recover_stale` владельцем/kind (параметр в существующем методе), каждый watchdog берёт только свои задачи | чужой running-job старше vision-lease не трогается `watchdog_sweep`; vision-job — восстанавливается | список kind/owner, реально попадавших в `interrupted` без инцидента |
| W-05 | HIGH | `mca_incidents.py:140-152,197-249,284-295`; `runtime_probes.py:2239-2290` | CONFIRMED_DEFECT | (a) не переоткрывать resolved без нового evidence — новая строка/`reopen_reason`; (b) сверка инцидента с состояниями связанных job и авто-`resolve(evidence=…)` после терминала всех job | takeover → job completed → следующий sweep `resolved_at != NULL`, row сохранён; повторный takeover ≠ молчаливый reopen | 6 fingerprint-ов, `jobs_json`, `resolved_at` |
| W-06 | MED-HIGH | `task_supervisor.py:187-247,488-510`; `initiative_observer.py:1946-2004`; `media_execution.py:687-707`; `mca_gates.py:1346-1353` | CONFIRMED_DEFECT | Единый периодический heartbeat для durable-running job (supervisor/observer/image) с интервалом из `MCA_JOB_HEARTBEAT_SECONDS`; либо явный `deadline_at`-контракт владельца | long coroutine под `supervisor.run(job_store=…)` обновляет `heartbeat_at`; иначе sweep её не забирает | `heartbeat_at/progress_at/created_at` job-строк инцидентов |
| W-07 | MED | `initiative_observer.py:1875-1880`; `mca_episode_jobs.py:157-162`; `mca_experience_jobs.py:860,1556`; `mca_exploration.py:1047-1138`; `cover_style_jobs.py:886-888`; `media_execution.py:710-735` | CONFIRMED_DEFECT | Передавать `fencing_token` в терминальные записи (механизм уже есть); для владельцев без токена — не считать takeover «recovery» | после takeover finish без токена должен быть no-op (или явный контракт) | `finished_at` job-строк vs `last_ts` инцидента |
| W-08 | MED | `mca_watchdog.py:74-93`; `mca_gates.py:1366-1383`; `task_supervisor.py:600-613` | CONFIRMED_DEFECT | Ставить `progress_at` при `mark_running`; порог по `kind` (карта `MCA_PROGRESS_STALL_*`), exemptions для длинных внешних kind; добавить takeover по `overdue()` | job с живым heartbeat и `progress_at IS NULL` получает свой bucket, а не «невидим»; `overdue` берётся в takeover | контракты прогресса по kind, `deadline_at` |
| W-09 | MED | `mca_watchdog.py:59-71`; `media_readiness.py:1835-1853`; `mca_exploration.py:1021-1060`; `cover_style_jobs.py:3555-3577`; `runtime_probes.py:1351-1359` | CONFIRMED_DEFECT | Не брать все queued: отдельный диагностический bucket для «нет claimer / истёк deadline_at», исключая `next_retry_at > now`; takeover только по expired deadline | queued 24 ч без deadline ⇒ диагностический инцидент без takeover; `next_retry_at` в будущем ⇒ «scheduled retry», не зависание | `status=queued` строки, `next_retry_at`, `deadline_at`, depth |
| W-10 | MED | `mca_watchdog.py:146-164,133-135`; `mca_incidents.py:157-161` | CONFIRMED_DEFECT | Логировать+эмитить WARN-событие при отказе регистрации (без создания инцидента из ошибки инцидента); возвращать `{created,updated,reopened,failed}` | отказ `open_or_update` ⇒ наблюдаемое событие+лог, нет рекурсии; счётчики не приравнивают update к new | — |
| W-11 | MED | `mca_incidents.py:44-54,85-155,173-182`; `mca_watchdog.py:150-161` | CONFIRMED_DEFECT | Включить `kind` в fingerprint (расширение `compute_fingerprint`), title/impact обновлять или хранить список job; 20-id bound сохранить | 2 job одного owner разных kind ⇒ 2 инцидента; повтор не переписывает title первого job | `fingerprint`, `title`, `jobs_json` |
| W-12 | — | `mca_incidents.py:141-152,173-182` | NEEDS_PRODUCTION_DATA | Диагностическая сверка (ниже §4); фикс не назначать до данных | — | полный набор из §4 |
| W-13 | — | `task_supervisor.py:712-751`; `mca_incidents.py:104-152`; `mca_watchdog.py:128` | NOT_A_DEFECT | — | существующие тесты | — |
| W-14 | LOW | `task_supervisor.py:571-584`; `mca_watchdog.py:128`; `mca_vision.py:4311` | BACKLOG_ONLY | Не трогать в corrective | — | — |

`W-01…W-11` — кандидаты на исправление в этом corrective (W-06/W-07 частично пересекаются:
W-06 — причина «ложных» takeover, W-07 — причина несовпадения инцидента и фактического
состояния задачи; оба входят в AC-20/AC-22).

---

## 2. Детали по §9.2 A–F

### A. Stale running jobs — `stale_jobs()`

`mca_watchdog.py:59-71`: только `status='running' AND (heartbeat_at IS NULL OR
heartbeat_at < now-MCA_JOB_STALE_SECONDS)`. Порог — `mca_gates.job_stale_seconds()`
(default 60, `mca_gates.py:1351-1353`), интервал цикла — `max(5, stale_seconds())`
(`mca_watchdog.py:283`), т. е. 60 с.

**Существующие механизмы для queued (проверены, новый не нужен):**

| Механизм | Где | Покрытие |
|---|---|---|
| claim-цикл vision-воркера (5 с) | `mca_vision.py:4545-4567`, `4311` | kind `vision.analyze` (+backfill sweep) |
| queue-wait + deadline vision | `media_readiness.py:1835-1853`, `1817-1831` | только `VISION_JOB_KIND` |
| закрытие «зависших» exploration-jobs | `mca_exploration.py:1021-1060` | kind `exploration.*` (`random.uses`) |
| kick recovery styled cover | `cover_style_jobs.py:3555-3577`, `3668-3682` | cover/style jobs |
| `requeue` + `set_next_retry` | `task_supervisor.py:712-751` | bounded retry, `next_retry_at` в будущем = scheduled retry |
| graphrag retry on schedule | `graphrag_rebuild.py:2255-2260` | `memory`/archive |

**Подтверждено пробой I:** queued-job возрастом 24 ч без `deadline_at` не виден ни
`stale_jobs` (0), ни `progress_stalled_jobs` (0), ни `overdue()` (0); единственный сигнал —
`telemetry_freshness() = "stale"` (`mca_watchdog.py:172-189`). Для `image`
(`media_execution.py:669-671`) задача исполняется в том же запросе, своего claim-цикла нет:
строка, оставшаяся `queued` после падения процесса между `enqueue` и запуском, не будет
подхвачена ни одним общим циклом. У `meme.initiative` есть собственный tick доставки
(`meme_initiative.py:4445-4455`, `deliver_deferred_all`) и `deadline_at` — его считать
осиротевшим нельзя. Для vision/exploration/cover/`memory` claim-циклы существуют
(таблица выше) и должны оставаться единственными владельцами queued-политики.

Вывод: **безусловный takeover queued запрещён требованием** и не нужен; нужен отдельный
диагностический bucket для «нет claimer» и обработка `deadline_at` (W-09).

### B. Отсутствующий `progress_at`

`mca_watchdog.py:82-93`: выборка `status='running' AND progress_at IS NOT NULL`; порог —
`mca_gates.progress_stall_seconds(row["owner"])`. Фактическая карта порогов
(`mca_gates.py:1366-1383`) содержит ключи `llm/video/archive`, а владельцы задач —
`asap8b01, qnd.event, mca16, mca05, memory, image, vision.*, random.uses,
meme.initiative, summary` (собрано по `enqueue(owner=…)`). Значит типизированные пороги
работают только при owner ∈ {`llm`,`video`,`archive`}; для всех прочих — default 600 с.

Кто пишет `progress_at`: `cover_style_jobs.py:1021`, `embedding_control_plane.py:4478,4512`,
`graphrag_rebuild.py:1351,1416`, `initiative_observer.py:1868`, `mca_episode_jobs.py:163`,
`mca_experience_jobs.py:1545`, `media_execution.py:694`. Не пишут: `mca_vision.*`
(длинные внешние вызовы — законно, есть heartbeat-цикл 30 с,
`mca_vision.py:1594-1605`), `summary` (короткие in-process), `meme.initiative`
(TTL-контракт `deadline_at`).

**Подтверждено пробой F:** running-job с heartbeat 1 с и `progress_at IS NULL` (age 2 ч) не
попадает ни в stale, ни в stalled; job с `progress_at` 2 ч — попадает (инцидент
`stage=progress`, W-проба K: severity ERROR, job остаётся `running`, восстановления нет).

Контракт прогресса фактически не объявлен: нет карты `kind → обязателен ли промежуточный
прогресс`; `MCA_JOB_HEARTBEAT_SECONDS` (default 15) не читается ни одним производителем
heartbeat (`heartbeat_interval_seconds()` в `mca_watchdog.py:42-43` вызывается только
из него самого).

### C. Дублирование `WATCHDOG_TAKEOVER`

`mca_watchdog.py:128-135`: событие эмитится **внутри** `for row in stale`, при этом
`job_ids` — общий `result["recovered"]`. Проба B: 3 stale-job → **3 идентичных события**,
каждое несёт один и тот же список из 3 id.

Дополнительно: `job_ids` — не разрешённое поле событийного контракта
(`mca_events.py:365-398`), `build_event` молча отбрасывает неизвестные ключи
(`mca_events.py:566-568`). Проба A: реальное событие содержит только
`event_name/outcome/reason_code/component/stage/level/ts` — **идентификаторов job в
событии нет вообще**. Индивидуальных доказательств takeover в телеметрии не остаётся.

Потребители: `mca_process_registry.py:899-916` (`stages_to_events`, `event_names`),
агрегаты `mca_event_aggregates` по fingerprint `event:component:reason:error_type`
(`mca_events.py:864-881`) — дубли просто накручивают `count` одного агрегата; UI-читателя
агрегатов нет. Имя события менять не требуется, поэтому фикс (одно событие на batch +
per-job записи) совместим с реестром.

### D. Ложное подтверждение восстановления

Проба C (инъекция отказа `recover_stale` в store): `result["recovered"] = []`, job остаётся
`running`, но эмитится `WATCHDOG_TAKEOVER` с `reason_code=takeover_recovered`; создаётся
ERROR-инцидент. Проба D (`job_store=None`): recovery не вызывается вовсе, событие
`takeover_recovered` всё равно эмитится.

Корень: `_emit` (`mca_watchdog.py:50-56`) всегда ставит `outcome="success"`, а
`reason_code` захардкожен в цикле; факт перехода не проверяется. Плюс отдельная
семантическая ошибка: `recover_stale` не «восстанавливает», а только снимает lease
(см. W-03), поэтому `takeover_recovered` ложен по построению даже в успешном пути.

### E. Подавление ошибок incident service

`_track_incident` (`mca_watchdog.py:146-164`): `except Exception: return 0` — без лога,
без события, без счётчика. `mca_incidents.open_or_update` при DB-сбое логирует warning и
возвращает `None` (`mca_incidents.py:157-161`), при `incidents_enabled()==False` — тоже
`None` (`:92-93`). Различить «выключено», «БД отказала», «запись создана/обновлена»
невозможно. Рекурсии сейчас нет (ошибка инцидента не создаёт инцидент), но и наблюдаемости
нет; при добавлении наблюдаемости нельзя вызывать `open_or_update` из обработчика его же
ошибок (требование AC-24) — только log + WARN-событие + локальный счётчик.

Счётчик `result["incidents"]` (`mca_watchdog.py:133-135`) считает `1` за **любой**
`res is not None`, т. е. обновление существующего инцидента = «новый инцидент»; проба H:
2 stale-job одного owner в одном batch → `incidents=2`, а строка инцидента одна.

### F. Lifecycle инцидентов

* `open_or_update` при повторе делает `repeat_count+1` и **снимает** `resolved_at`
  (`mca_incidents.py:140-152`) — resolved-инцидент молча переоткрывается без нового
  evidence (проба E: resolve → следующий takeover того же owner ⇒ `resolved_at=NULL`,
  `repeat_count+1`). Это противоречит «resolved — только после реальной проверки».
* `resolve()` (`:221-249`) требует evidence, но **не имеет ни одного production-вызова**:
  в `services/web/handlers/tools` вызовов нет, только тесты; в oversight API есть только
  `GET /incidents` и `GET /incidents/changes` (`web/api/oversight.py:220-262`).
* Автоматического закрытия при исчезновении условия нет; связи «инцидент → актуальное
  состояние job» нет (только `jobs_json`, до 20 id, `mca_incidents.py:39-41,173-182`).
* `runtime_probes._probe_incidents_active` (`:2277-2286`) отдаёт `STATUS_DEGRADED` при
  любом unresolved инциденте, независимо от возраста и фактического состояния job.

**Подтверждено пробой E:** takeover → поздний успешный `finish` без fencing меняет job на
`completed`, но инцидент остаётся активным (1); ручной `resolve` работает; следующий
takeover того же owner переоткрывает строку (4-й repeat). Поэтому «шесть активных
ERROR-инцидентов при чистом 5-минутном окне журналов» объясняется lifecycle-дефектом
**без** необходимости предполагать продолжающийся сбой компонента — но фактическую
причину каждого из шести это не доказывает (см. §4).

---

## 3. Смежные подтверждённые дефекты (нужны для AC-20/AC-22)

### W-04 — vision-watchdog глобально забирает чужие задачи

`mca_vision.py:4528-4543` в каждом 5-секундном тике (`:3203`, `:4311`) вызывает
`media_readiness.watchdog_sweep`; тот вызывает **глобальный** `store.recover_stale(
stale_after_seconds=lease_seconds())` (default 180 с, `media_readiness.py:1528-1531,
1783-1787`) и восстанавливает **только** `kind == VISION_JOB_KIND` (`:1789-1801`).

Проба G: running-job owner `memory`, heartbeat 200 с назад → `watchdog_sweep` ставит
`interrupted/worker_lost`, `requeued=0`, `terminal=0`, инцидентов — **0**. То есть чужие
задачи молча terminated, без события, без инцидента и без восстановления. Для
`graphrag_rebuild` это опасно: его прогресс идёт через CAS `expect=ST_RUNNING`
(`graphrag_rebuild.py:1336-1338`) — после чужого takeover CAS перестаёт проходить.

### W-06 — контракт heartbeat не выполняется частью владельцев

`TaskSupervisor.run` ставит `mark_running` один раз (`task_supervisor.py:224-247`) и
периодического heartbeat не имеет; `dispatch_event` запускает длинный observe через
`supervisor.run(job_store=store)` (`initiative_observer.py:1330-1359`), поэтому job
`qnd.event` живёт без heartbeat. Сам observe-раннер делает один heartbeat
(`initiative_observer.py:1965`) и далее длинные фазы scan/evaluate/meme без него.
`media_execution` heartbeat только при сохранении checkpoint (`:687-707`); одна длинная
генерация > 60 с → stale. `mca16`: heartbeat на старте и в semantic-батчах
(`mca_experience_jobs.py:1573,2176`). При пороге stale 60 с это штатно даёт takeover
живых задач; нужен либо периодический heartbeat, либо owner-specific `deadline_at`.

### W-07 — терминальные записи без fencing

`initiative_observer.py:1875-1880`, `mca_episode_jobs.py:157-162`,
`mca_experience_jobs.py:860,1556`, `mca_exploration.py:1047-1138`,
`cover_style_jobs.py:886-888`, `media_execution.py:710-735` вызывают `finish` без
`fencing_token`; `TaskJobStore.finish` при отсутствии токена пишет безусловно
(`task_supervisor.py:512-545`). После takeover старая задача «воскрешает» терминальный
статус, и инцидент `worker_lost` навсегда расходится с фактическим исходом.

### W-11 — fingerprint слишком грубый

`compute_fingerprint` (`mca_incidents.py:44-54`) получает `process_id=watchdog.jobs`,
`pipeline_type=owner`, `stage`, `reason_code`, `error_type=error_code` (обычно `""`),
`dependency=None`. `kind` и `job_id` не входят ⇒ все job одного owner (разные kind,
разные инциденты) сливаются; `title` создаётся из первого job и больше не обновляется
(`:116-152` — UPDATE не трогает `title`), поэтому «инцидент job X» может годами
показывать давно закрытый job X. `jobs_json` хранит максимум 20 последних id
(`:39-41,173-182`) — доказательная база repeat-истории ограничена.

---

## 4. Что докажет реальную причину шести инцидентов, а что — артефакт детекции

**Нужные production-данные (read-only; DevOps):**

1. `SELECT incident_id, fingerprint, process_id, pipeline_type, stage, severity,
   first_ts, last_ts, repeat_count, jobs_json, chats_json, first_trace_id,
   last_trace_id, acknowledged_at, resolved_at, resolution_evidence, created_at,
   updated_at FROM mca_incidents WHERE resolved_at IS NULL ORDER BY first_ts;`
2. Для каждого `job_id` из `jobs_json`: `SELECT job_id, owner, kind, status,
   reason_code, error_code, attempt, max_attempts, deadline_at, heartbeat_at,
   progress_at, next_retry_at, generation, fencing_token, created_at, updated_at,
   finished_at, checkpoint_ref, pipeline_run_id FROM task_jobs WHERE job_id IN (…);`
   (учесть, что `TaskJobStore.prune` в production не вызывается — терминальные строки
   должны быть на месте; W-14).
3. `SELECT status, reason_code, COUNT(*) FROM task_jobs GROUP BY 1,2;` и
   `SELECT owner, kind, status, COUNT(*), MAX(updated_at) FROM task_jobs
   GROUP BY 1,2,3;` — текущее состояние очереди и кто реально «завис» сейчас.
4. Счётчик и время событий takeover: `SELECT event_name, reason_code, COUNT(*),
   MIN(ts), MAX(ts) FROM mca_events WHERE event_name='WATCHDOG_TAKEOVER' GROUP BY 1,2;`
   (ожидаемо: `job_id`/`job_ids` в событиях отсутствуют — W-01).
5. Effective env на процессе: `MCA_HEARTBEAT_WATCHDOG_ENABLED`, `MCA_INCIDENTS_ENABLED`,
   `MCA_JOB_STALE_SECONDS`, `MCA_JOB_HEARTBEAT_SECONDS`,
   `MCA_PROGRESS_STALL_DEFAULT_SECONDS`, `MCA_PROGRESS_STALL_LLM/VIDEO/ARCHIVE_SECONDS`,
   `limits.vision_job_lease_seconds`, `limits.vision_queue_wait_seconds`.
   (без секретов)
6. `process_started_at` процесса (или journal `Started` unit) — для отделения
   restart-сирот от настоящих потерь воркера.
7. Полные строки `mca_media_analyses` со `status IN ('running','pending')` и
   `mca_media_assets` для связанных asset_id — если среди инцидентов есть `vision.*`,
   это покажет текущее пользовательское воздействие.

**Интерпретация (что доказывает что):**

* **Detection artifact / lifecycle-артефакт:** job из `jobs_json` имеет
  `finished_at > incident.last_ts` и терминальный `completed/succeeded`, а
  `heartbeat_at` у него старше `last_ts - 60` ⇒ задача была жива, но молчала; watchdog
  снял lease (W-06), а `takeover_recovered` (W-02) и вечный активный инцидент (W-05) —
  продукты детекции, не падения.
* **Restart-артефакт:** `created_at < process_started_at`, `status` был `running`,
  `heartbeat_at` — до старта процесса; инцидент создан `startup_check`
  (`mca_watchdog.py:167-169`) на первом sweep после деплоя.
* **Реальный сбой/зависание:** job остаётся `running`/`interrupted` без терминала,
  downstream ждёт (media analysis `pending`, публикация/ответ не приходит), либо job
  отсутствует в `task_jobs` при отсутствии prune; тогда нужно дополнительно смотреть
  `mca_events`/journal в момент `incident.first_ts`.
* **Масштаб 72 повторов:** `repeat_count` растёт на каждую обнаруженную stale-job того же
  fingerprint; при 60-секундном sweep и непрерывных пятиминутных тиках 72 повтора
  означают 72 отдельных обнаружения, а не 72 падения. Если
  `(last_ts - first_ts)/60 ≈ repeat_count` — каждый sweep находил ≥1 такую задачу
  (хроническая проблема heartbeat/continuation); если повторов значительно меньше —
  спорадические потери воркера. Дополнительно: если из 6 инцидентов часть имеет
  `repeat_count == 1`, их источник — один batch (например, рестарт), а не серия.

**Осторожно:** по событиям `WATCHDOG_TAKEOVER` восстановить job нельзя (W-01: поля нет),
поэтому атрибуция — только через `mca_incidents.jobs_json`/`title` и строки `task_jobs`.
Отсутствие job-строки без prune не объясняется и должно фиксироваться как остаточная
неопределённость.

---

## 5. Состояние тестов и проверок

* Существующий baseline (deployed checkout): `16 passed` —
  `tests/test_mca17a_observability_core_round1027.py` (watchdog/sweep/incident/recover),
  `tests/test_smart_exec_learning_incidents.py`,
  `tests/test_mca01_tx_task_supervisor_round1027.py` (takeover/recover), 6.2 с.
* Действующие тесты **фиксируют дефектное поведение как ожидаемое**:
  `tests/test_smart_exec_learning_incidents.py:100,129-131` требуют
  `resolved_at IS NULL` и роста `repeat_count` без закрытия; тест
  `test_watchdog_takeover_and_recovery` (`test_mca17a...:667-686`) проверяет только
  `interrupted` и отдельный ручной `recover_job`, но не то, что sweep возвращает job в
  работу. При исправлении W-03/W-05 эти проверки должны быть обновлены вместе с
  реализацией (иначе зелёный тест будет противоречить AC-20/AC-23).
* Пробные сценарии W-01…W-11 воспроизведены локально (см. `watchdog-probe-results.json`);
  это PROVISIONAL-проба, а не постоянный тест. Постоянные регрессии — по колонке
  «Тест» в таблице §1, в существующих файлах тестов.

## 6. Границы и остаточная неопределённость

* Реализация исправлений не выполнялась; ни один инцидент не закрыт и не объявлен
  устранённым.
* Причина каждого из шести production-инцидентов не установлена: для этого нужны данные
  §4. Код доказывает механизм, которым инциденты создаются и не закрываются, и механизм,
  которым живые задачи могут помечаться потерянными; он не доказывает, какой именно
  сценарий дал каждый fingerprint.
* Предложенные фиксы минимальны и переиспользуют существующие механизмы
  (`recover_stale`, `recover_job`, `requeue`/`set_next_retry`, `overdue`, `resolve`,
  `mca_events`). Расширение fingerprint/`REASON_CODES` требует согласования с PM/Architect:
  старые строки инцидентов останутся активными до включения W-05 (авто-закрытие по
  фактическому состоянию) — это осознанная миграционная последовательность.
* Вне полосы (BACKLOG_ONLY, не блокирует corrective): неиспользуемый
  `TaskJobStore.prune` (неограниченный рост `task_jobs`), шум `WATCHDOG_SWEEP` каждые
  60 с (раздувает `mca_event_aggregates`), глобальный `recover_stale` каждые 5 с из
  vision-тика.
