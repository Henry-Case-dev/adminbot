# FIX B1/B2 — EMBED-REBUILD-MECHANISM (review 23.10.2026)

Кандидат-база: `d3ba845b` (прошлая итерация лейна) + текущий master
(`b1525b60`/`3334141a` — чужие коммиты, 7 файлов лейна не меняли; проверено
`git diff`). Ревью: `review.md` (Needs Fixes, B1+B2). Исправлены ровно два
блокера + два однострочных nonblocking. Новых таблиц/колонок/env нет,
критерии `_validate` (§6) не тронуты, retry-политика (lease/горизонт/kill-switch)
не менялась.

## B1 — A→B→A: новое поколение не получало джобу (тихий FTS-only)

**Причина.** Coalesce-ключ durable-джобы — `graphrag_rebuild:{index}:{fp}`
(`_coalesce_key`). При возврате identity к прежнему fp `_find_active_job`
находит ЗАВЕРШЁННУЮ джобу этого fp, а `_ensure_job` (до фикса
`:1973-1974`: `if status in (ST_ACTIVATED, ST_CANCELLED): return None`)
возвращал `None` → `maybe_schedule_rebuilds` делал `continue` → свежая
`building`-строка реестра оставалась без сборки. Рестарт не помогал: startup
видит существующую `building`-строку и упирается в ту же terminated-джобу.

**Что сделано** (`services/graphrag_rebuild.py`):
* `_repoint_job_to_generation()` (`:626`) — ОДНА транзакция `task_jobs`:
  CAS по фактическому статусу → `queued`; payload merge (`index`,
  `fingerprint`, `generation`, `cursor={"last_id":0,"processed":0}`,
  `processed=0`); очистка `result_ref` (иначе старый `pause_started_at`
  мгновенно исчерпал бы горизонт §25), `finished_at` (иначе prune мог удалить
  живую джобу), `progress_at`; `checkpoint_ref=cp:{index}:{gen}`.
* `_ensure_job` (`:2077-2093`) — перед ветвлением: целевое поколение НОВЕЕ
  поколения из payload (или payload без generation у `activated`/`cancelled`)
  → переоткрыть и вернуть ту же durable-строку. `RUNNING/BUILDING` не трогаются
  (single-writer/stale-takeover), операторская `paused` уважается; повторный
  тик — CAS по статусу (без двойного переоткрытия).
* `TARGET_GENERATION_STATUSES = {"building"}` (nonblocking B-nb1): `validated`
  больше не возвращается как «цель», под которую нет планируемой джобы (вместо
  вечного висения регистрируется новое `building`); `_activate` по-прежнему
  принимает `building|validated` — критерии §6 целы.

**Трейс A→B→A** (`%OPENCODE_WORKFLOW_SCRATCH%/embed-rebuild/probe_b1b2.py`,
GREEN, exit 0):

```
B1 step1 (A register): gen=1/building
B1 step1 (A active):   gen=1 job=activated write_allowed=True
B1 step2 (B active):   fp=bbbbbbbbbbbb          (генерация 2, A → superseded)
B1 step3 (A снова):    scheduled=['graph_facts_vec'] gen=3/building job=queued
                       state=build_in_progress write_allowed=False
B1 final:              job=activated active_gen=3 fp=96054936e83d write_allowed=True
```

RED-проба (те же файлы на `d3ba845b`):
`scheduled=[] gen=3/building job=activated state=build_in_progress write_allowed=False`
→ `B1 FAIL: новая сборка не запланирована (тихий FTS-only)`.

Regression-тест `test_identity_flipback_a_b_a_rebuilds_again`: полный путь
`maybe_schedule_rebuilds` + `run_job`; проверяет ту же `job_id`, payload
`generation/fingerprint`, сброшенный checkpoint (processed=0), финальный
`activated`, `_index_generation_ok`/`_vec_write_allowed=True`, целость
`graph_facts`/`graph_facts_vec` и старых shadow.

## B2 — `build_failed` недостижим: статус врал «build_in_progress»

**Причина.** Терминальные ветки `_handle_build_failure` (`:1524`, ветки
horizon/auth `:1550-1570`, deterministic `:1686-1695`) и validation-failed
(`:1378-1400`) обновляют только `task_jobs`; реестровая строка остаётся
`building`, а `generation_status` (до фикса `:1706-1715`) классифицировал любой
`building` как `build_in_progress`. Ветка `build_failed` не имела продюсера;
лог gate'а тоже утверждал «build in progress».

**Что сделано** (источник истины — durable `task_jobs`; реестр терминально не
переписываем → нет новых producer'ов, ΔDDL=0):
* `latest_rebuild_job()` (`:689`) — R17-safe выжимка последней джобы
  (`status/reason_code/generation/updated_at`), fail-open.
* `_build_state_from_job()` (`:1861`): job `failed|validation_failed|cancelled`
  → **`build_failed`** (+reason джобы); джобы нет → **`build_pending` /
  `job_missing`**; джоба СТАРОГО поколения → **`build_pending` /
  `job_stale_generation`**; иначе `build_in_progress`.
* `generation_status` применяет это к `IN_PROGRESS_GENERATION_STATUSES`
  (`building|validated|building_target|catching_up|ready`) — nonblocking B-nb3
  больше не помечает миграционные статусы провалом.
* `summary_memory._generation_hint()` (`:1950`) — тот же учёт джобы в хвосте
  лога; запрос выполняется только при эмиссии WARNING (раз в cooldown), hint
  кэшируется в `_GEN_LOG_STATE` → hot-path не утяжелён.
* Empty-source (nonblocking B-nb2): в ответе `source_empty`; пустой источник
  не требует reindex (`reindex_required=False` для `no_generation`/`build_pending`).

**Трейс B2** (probe, GREEN):

```
B2: job=failed/ValueError state=build_failed reason=ValueError
B2 log: … status=building | gen_fp=96054936e83d new_fp=96054936e83d
        — FTS-only (A06) | build failed — rebuild required (ValueError)
B2 tick: scheduled=[] generations=1        (retry-storm отсутствует)
```

RED (на `d3ba845b`): `state=build_in_progress`, лог `| build in progress`,
`B2 FAIL: статус врёт` + `B2 FAIL: лог говорит «build in progress»`.

Regression-тесты: `test_generation_status_build_failed` (плюс caplog-проверка
честного лога и отсутствие новых поколений/джоб на тике),
`test_generation_status_build_pending_stale_job`, а также обновлённые
`test_generation_status_active_and_build_in_progress` (build_pending без джобы →
build_in_progress с джобой) и `test_generation_status_reports_identity_changed`
(`source_empty`/`reindex_required` пустого `smart_archive`).

## Изоляция тестов (пойманный побочный эффект, не код лейна)

Первый 20-файловый прогон в порядке «мой файл первым» дал падение
`test_asap5_graphrag_recovery::test_future_resume_tick_after_cooldown_restart_survives`
(`assert 'activated' == 'paused_rate_limit'`). Причина — процесс-глобальный AIMD
`embedding_control_plane.CONTROLLER`: успешные батчи моих тестов оставляют
`_batch=50`, из-за чего в чужом тесте `GRAPHRAG_REBUILD_BATCH=2` перестаёт
действовать (4 факта уходят одним батчем, ожидаемый 429 не наступает).
Добавлена autouse-фикстура `_isolate_aimd_controller` в
`tests/test_graphrag_identity_reindex.py` (`CONTROLLER.reset()` до/после —
штатный API «Сброс AIMD-состояния (тесты/переконфигурация)»). Набор зелёный в
ЛЮБОМ порядке: «мой файл первым» и алфавитный — по 681 passed.

## Прогоны (`.venv/Scripts/python.exe -m pytest`, локально, без сети/прода)

| Набор | Результат | База ревьюера |
|---|---|---|
| `test_graphrag_identity_reindex.py` + `test_webapp_memory_overview_api.py` | **23 passed** | 20 (было 11+9; +3 новых теста) |
| 20-файловый graphrag/embed/memory/API набор | **681 passed** (оба порядка) | 678 (+3 новых теста; регрессов нет) |
| `tests/test_memory_*.py` (11 файлов) | **295 passed** | 295 (без изменений) |
| RED: `test_graphrag_identity_reindex.py` на `d3ba845b` | **5 failed, 9 passed** | — |
| RED: probe B1/B2 на `d3ba845b` | exit 1 (оба дефекта воспроизведены) | — |

```powershell
cd C:\Code\Python\adminbot
.\.venv\Scripts\python.exe -m pytest tests/test_graphrag_identity_reindex.py tests/test_webapp_memory_overview_api.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_graphrag_identity_reindex.py tests/test_graphrag_rebuild_asap32.py tests/test_asap5_graphrag_recovery.py tests/test_asap5_embedding_identity.py tests/test_asap6_embedding_generations.py tests/test_asap8_f8_embeddings.py tests/test_graphrag_database.py tests/test_graphrag_memory.py tests/test_summary_memory.py tests/test_asap44_graphrag_batch_breaker.py tests/test_embedding_control_plane_asap4.py tests/test_mca07_retrieval_context_round1027.py tests/test_mca01_tx_task_supervisor_round1027.py tests/test_memory_rebuild_round1021.py tests/test_memory_core_round1020.py tests/test_memory_maintenance.py tests/test_memory_lookup_round1026.py tests/test_soul1_w7_embedding_primary_slot.py tests/test_webapp_memory_overview_api.py tests/test_asap8_v63_b09_migration.py -q
.\.venv\Scripts\python.exe -m pytest (Get-ChildItem tests -Filter "test_memory_*.py" | ForEach-Object { "tests/" + $_.Name }) -q
.\.venv\Scripts\python.exe %OPENCODE_WORKFLOW_SCRATCH%\embed-rebuild\probe_b1b2.py
```

## Риски / границы

* Переоткрытие джобы НЕ ослабляет §6.1 `fingerprint_current`: сборка идёт под
  новый fp, критерии те же; старый shadow не переиспользуется (checkpoint
  сброшен → полный re-embed в `_g{new}`).
* Retry-storm не появляется: тик `include_failed=False` не переоткрывает
  failed/validation_failed; `_repoint` — CAS, параллельный тик не даёт двух
  сборок; lease/горизонт 24 ч/kill-switch `GRAPHRAG_SHADOW_REBUILD_ENABLED`
  не менялись.
* Данные не удаляются: переоткрывается только строка `task_jobs`; реестр,
  source-факты, старые shadow и live-векторы не трогаются.
* `build_pending` — additive-подстатус `generation_status` (контракт
  `active|build_in_progress|build_failed|identity_changed|no_generation`
  расширен, не заменён). W4-UI должен рендерить `state`/`reindex_required`;
  прод-путь «Google → apinet» его не показывает (джоба создаётся сразу).
* Прод/live не проверялись (SSH/прод запрещены лейном); post-deploy активация —
  DevOps + независимая проверка Reviewer.
