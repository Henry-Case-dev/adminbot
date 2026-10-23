# REVIEW R2 — EMBED-REBUILD-MECHANISM: B1/B2 (кандидат 5877810d)

Лейн: **REV-EMBED-REBUILD-R2** (аудит 23.10.2026). Режим: read-only;
единственная запись — этот файл. Прод/SSH не использовались (запрещено лейном).
Дата проверки: **2026-10-23 07:34 +12:00** (Russia Time Zone 11).

## Привязка кандидата

- **Кандидат:** `5877810d1c9760543148b07b859189b5295a7ed6`
  (`fix(embed): B1/B2 review ...`).
- **Прямой родитель:** `3334141a5ba2f57323a1e974df607e668a83e0da`.
  В диапазоне `d3ba845b..5877810d` есть ещё `b1525b60`/`3334141a` — чужие
  коммиты других лейнов; сам fix-коммит меняет **ровно 4 файла** (см. §5).
- **База сравнения:** `d3ba845b4c644f602fdeaab6513aba185003bbd5`.
  Четыре файла лейна не менялись между `d3ba845b` и `3334141a`
  (`git diff --stat` пуст).
- Прогоны — в чистых detached-worktree:
  `...\rev-embed-r2\wt-d3ba845b` и `...\wt-5877810d`; код/тесты worktree
  совпадают с SHA (кроме моих untracked probe-скриптов).
- Окружение: Python **3.12.0**, pytest **9.1.1**, sqlite-vec, tmp-DB;
  без сети/прода.

## Вердикт

**B1 — закрыт. B2 — закрыт.**
**Approved for controlled deployment, parent not DONE** — кандидат можно
включать в поезд **2.58.113** с оговорками по порядку «зафиксировать identity →
деплой → startup-активация → post-deploy canary» (§7). Полный `DONE` родителя
невозможен до реальной активации поколения на проде (postdeploy-only).

Nonblocking-находки NB-1…NB-4 (§6) не блокируют 2.58.113: прод-сценарий
Google→apinet идёт через новый fp/новую джобу, а деплой содержит рестарт,
который закрывает NB-1. Их стоит учесть как маленький follow-up.

## Acceptance ledger

| # | Пункт | Статус | Доказательство |
|---|---|---|---|
| 1 | B1: A→B→A реально доходит до `active`; переоткрывается та же durable-джоба | **VERIFIED** | Мой probe (`probe_indep.py --mode head`): на третьем шаге `scheduled=['graph_facts_vec']`, registry `gen=3/building`, job `queued`, `job_id` тот же, payload `gen=3`, `processed=0`, `result_ref=null`, `finished_at=null`, `checkpoint_ref=cp:graph_facts_vec:3`; после `run_job` → `activated`, active `gen=3`, `_vec_write_allowed=True`. RED на `d3ba845b`: `scheduled=[]`, job `activated`, write `False`. Тест `test_identity_flipback_a_b_a_rebuilds_again` (`tests/test_graphrag_identity_reindex.py:450-514`) — GREEN. |
| 1a | `_repoint_job_to_generation` — одна транзакция, CAS по фактическому статусу | **VERIFIED** | `services/graphrag_rebuild.py:626-686`; один `db.write_transaction` (`:675-676`), один `UPDATE ... WHERE job_id=? AND status=?` (`:664-671`); payload merge (`:648-663`). Повторный/параллельный тик: CAS не даёт двойного переоткрытия. |
| 1b | `RUNNING/BUILDING` не трогаются; операторский `paused` уважается | **VERIFIED** | exclusion `:2085-2088`; `paused` → `return None` (`:2102-2103`). Мой probe: `paused` остался `paused` с payload gen=1; `running` (fresh heartbeat) остался `running`, payload gen=1; `_ensure_job` вернул `None`. |
| 1c | Checkpoint/payload/result_ref/finished_at/checkpoint_ref корректны | **VERIFIED** | `:660-671`: payload `generation/fingerprint/cursor={last_id:0,processed:0}`, `processed=0`, `result_ref=NULL`, `finished_at=NULL`, `progress_at=NULL`, `checkpoint_ref=cp:{index}:{gen}`. Probe подтвердил все поля; `pause_started_at` живёт в `result_ref` (`:405-447`) и очищается вместе с ним. |
| 2 | B2: `failed/validation_failed/cancelled` → `build_failed` + reason | **VERIFIED** | `FAILED_BUILD_JOB_STATUSES` (`:100-101`), `_build_state_from_job` (`:1861-1877`), `generation_status` (`:1824-1830`). Probe: job `failed/ValueError`, registry остался `building`, API `state=build_failed`, `reason_code=ValueError`. Тест `test_generation_status_build_failed` (`:520-569`). |
| 2a | Нет джобы → `build_pending/job_missing`; джоба старого поколения → `build_pending/job_stale_generation` | **VERIFIED** | `:1867-1876`; probe: реальная джоба gen1 + registry gen2 → `build_pending/job_stale_generation`; без джобы → `build_pending/job_missing`. Тест `:573-594`. |
| 2b | Лог `_index_generation_ok` честный | **VERIFIED** | `services/summary_memory.py:1950-1979`; hint кэшируется, запрос только при WARNING (`:1925-1938`). Probe (нет чужого ACTIVE): `build failed — rebuild required (ValueError)`, строки `build in progress` нет. Тест `:554-558`. Если есть ACTIVE другого identity, лог говорит `identity changed — rebuild required` — это тоже правда, просто без reason. |
| 2c | Реестр терминально не переписывается; ΔDDL=0 | **VERIFIED** | B2-ветки только читают `task_jobs`; `set_embedding_generation_status` в этом коммите не вызывается. Тест `:544-546` (registry `building` после провала); probe: `PRAGMA table_info` до/после совпал для `task_jobs`, `mca_embedding_index_generations`, `graph_facts`; `sqlite_master`-DDL не менялся. |
| 3 | Критерии активации не ослаблены; retry-storm нет | **VERIFIED** (с NB-1) | `_validate` не менялся; §6.1 `fingerprint_current` — `:837-844`; `_activate` по-прежнему принимает только `building/validated` (`:1095-1099`). `TARGET_GENERATION_STATUSES` сужен до `building` (`:92`), не расширен. `include_failed=False`/lease/24h/kill-switch не менялись (`:480`, `:1218-1248`, `:237-247`, `:155-164`). Probe: повторный tick `include_failed=False` не создал новых job/generation (`B2_tick_jobs_delta=0`). NB-1 — обратная сторона консервативного guard, не storm. |
| 4 | Данные целы: source/FTS/старые shadow/live-векторы; меняется только строка `task_jobs` | **VERIFIED** | `_repoint` пишет только `task_jobs`; `_activate` не менялся. Probe после A→B→A: source `graph_facts=3`, live `graph_facts_vec=3`, старый `graph_facts_vec_g0=1`; registry: gen1/gen2 `superseded`, gen3 `active`. FTS/DDL не затрагивались. |
| 5 | Скоуп: 4 файла, чужих правок нет; fixture только в тесте | **VERIFIED** | `git show --name-status 5877810d`: `fix-b1b2.md`, `services/graphrag_rebuild.py`, `services/summary_memory.py`, `tests/test_graphrag_identity_reindex.py`. `git show --check` чист. `_isolate_aimd_controller` — только `tests/test_graphrag_identity_reindex.py:81-96` (и аналогичный reset в другом тесте), в прод-коде отсутствует. |
| 6 | Независимые прогоны, два порядка | **VERIFIED** | См. §3: 23 passed; 681 passed ×2; 295 passed ×2; RED 5 failed/9 passed; probe GREEN/RED. |
| 7 | Nonblocking-изменения оценены | **VERIFIED** | NB-1…NB-4 ниже; существующих потребителей/UI не ломают: `generation_status` только добавляет `source_empty` и расширяет `state` значением `build_pending`; в кандидате UI этот контракт не читает (`git show 5877810d:web/*` — нет `generation`), API-ответ аддитивен (`web/api/memory_agi.py:533-542`). |
| 8 | Post-deploy активация поколения на проде | **READY_FOR_LIVE** | Postdeploy-only: §7 (`state`: `identity_changed`/`build_in_progress` → `active`, `_vec_write_allowed=True`, source/live целы, FTS жив); rollback — kill-switch + рестарт. Не parent `DONE`. |

## 3. Независимые числа (не из отчёта Builder)

| Набор | Результат |
|---|---|
| `tests/test_graphrag_identity_reindex.py` + `tests/test_webapp_memory_overview_api.py` | **23 passed** (31.18 s) |
| 20-файловый graphrag/embed/memory/API набор, порядок «мой файл первым» | **681 passed** (81.66 s) |
| тот же набор, алфавитный порядок | **681 passed** (79.81 s) |
| `tests/test_memory_*.py` (11 файлов), прямой порядок | **295 passed** (22.09 s) |
| тот же glob, обратный порядок | **295 passed** (22.42 s) |
| RED: файл кандидата на коде `d3ba845b` | **5 failed, 9 passed** (17.02 s) — ровно изменённые/новые B1/B2-тесты |
| Мой probe `--mode head` | **22/22 проверок PASS** |
| Мой probe `--mode base` | RED воспроизведён: `scheduled=[]`, job `activated`, `write_allowed=False`, `build_in_progress`, лог `build in progress` |

Probe: `C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\rev-embed-r2\probe_indep.py`
(+ `probe_failed_tick.py` для NB-1). Это независимый сценарий, не запуск
Builder-probe; tmp sqlite-vec DB, реальные `maybe_schedule_rebuilds`/`run_job`.

## 4. B1 — что именно проверено

- `_repoint_job_to_generation()` (`:626-686`) вызывается только из
  `_ensure_job` при `target_gen > payload generation`
  (`:2083-2093`), для статусов кроме `running/building/paused`.
- Одна транзакция `task_jobs`, CAS по `expect=status`; payload получает
  `index/fingerprint/generation`, `cursor={last_id:0,processed:0}`,
  `processed=0`; очищаются `result_ref` (а с ним старый `pause_started_at`),
  `finished_at`, `progress_at`; ставится `checkpoint_ref=cp:{index}:{target_gen}`.
- `_find_active_job` возвращает ту же строку; `maybe_schedule_rebuilds`
  возвращает её job_id, `run_job` стартует с `queued` и строит shadow
  `_g{new_gen}`; старый shadow не переиспользуется.
- A→B→A проверен полным путём `maybe_schedule_rebuilds` + `run_job` (не только
  регистрацией): gen3 `building` → job `queued` → gen3 `active`,
  `_vec_write_allowed=True`. Старые поколения и source целы.

## 5. B2 — что именно проверено

- `latest_rebuild_job()` (`:689-708`) — R17-safe выжимка последней durable-джобы
  (`status/reason_code/generation/updated_at`), fail-open.
- `_build_state_from_job()` (`:1861-1877`): `failed/validation_failed/cancelled`
  → `build_failed` + reason; нет джобы → `build_pending/job_missing`; джоба
  gen < registry gen → `build_pending/job_stale_generation`; иначе
  `build_in_progress`.
- `generation_status` применяет это к `IN_PROGRESS_GENERATION_STATUSES`
  (`:95-96`, `:1824-1830`); реестр не переписывается.
- `summary_memory._generation_hint` (`:1950-1979`) повторяет ту же логику для
  лога; запрос к `task_jobs` — только при эмиссии WARNING, hint кэшируется в
  `_GEN_LOG_STATE` (`:1925-1938`), hot-path не утяжелён.
- Контракт аддитивен: добавлено `source_empty`; `state` расширен
  `build_pending`; существующие ключи не удалены. В кандидате UI `generation`
  не читает; API-тест 9/9 зелёный в общем прогоне 23.

## 6. Nonblocking findings

### NB-1 — failed/validation_failed джоба старого поколения не переоткрывается тикером
- **Где:** `services/graphrag_rebuild.py:1952-1957` (guard `include_failed=False`
  стоит до `_ensure_job`), при том что `_ensure_job` умеет repoint
  (`:2083-2093`).
- **Repro:** registry gen2 `building`, job gen1 `failed`; вызов
  `maybe_schedule_rebuilds(mm, include_failed=False)` → `scheduled=[]`,
  job остаётся `failed/gen1`; обычный `maybe_schedule_rebuilds(mm)` →
  `scheduled=['graph_facts_vec']`, job `queued/gen2` (probe
  `probe_failed_tick.py`).
- **Влияние:** A→B→A после **провала** старой A-сборки восстанавливается только
  рестартом/явным default-schedule, не 15-минутным тикером. Это согласуется с
  bounded-retry политикой, но противоречит широкой формулировке «новое
  поколение поднимется следующим тиком». Прод-деплой 2.58.113 содержит
  рестарт, поэтому релиз не блокируется.
- **Минимальная коррекция:** в guard разрешить джобу, если
  `_payload_generation(current_job) < generation` (новое поколение — не retry
  failure-класса), + один тест на этот переход. Перепроверка: тот же probe
  `include_failed=False` → `scheduled=['graph_facts_vec']`, job gen2.

### NB-2 — пустой источник + старая/чужая строка реестра всё ещё даёт `reindex_required=True`
- **Где:** `services/graphrag_rebuild.py:1845-1848`: пустой source исключается
  только для `no_generation`/`build_pending`; при `identity_changed`
  (старая `building`-строка другого fp) флаг остаётся `True`.
- **Факт прода:** в реестре 2 старые `building`-строки; у `graph_facts_vec`
  подтверждён `pause_reason=rate_limit:quota_group` (report §1), для пустого
  `smart_archive` возможен тот же класс состояния. `smart_archive_facts=0`;
  `ensure_current_generation` новое поколение не регистрирует (`:1740-1744`),
  но панель может предлагать reindex пустого индекса — ровно то, что B-nb2
  хотел убрать.
- **Влияние:** косметическое/UX, не блокирует; `generation_status` при этом
  честно отдаёт `source_empty=True`.
- **Минимальная коррекция:** `reindex_required = state != "active" and not
  source_empty` (или явно исключить `identity_changed`/`build_failed` при
  пустом source) + тест на старую строку `smart_archive`.

### NB-3 — `validated` убран из target, но нового `building` не появляется
- **Где:** комментарий `services/graphrag_rebuild.py:87-92` обещает
  «зарегистрируется новое `building`»; фактически
  `register_embedding_target_generation` идемпотентно возвращает существующую
  строку со статусом `validated` (`services/database.py:6025-6028`), а
  `maybe_schedule_rebuilds:1947` пропускает не-`building`.
- **Влияние:** строка `validated` остаётся без джобы (как и до фикса); в
  прод-пути graphrag статус `validated` в реестр не пишется, поэтому
  недостижимо. Nonblocking; поправить комментарий или явно обработать
  `validated` при появлении producer'а.
- **Проверка:** `ensure_current_generation` + registry `validated` → возвращает
  ту же строку, `maybe_schedule_rebuilds` → `[]`.

### NB-4 — гигиена/наблюдаемость (не блокирует)
- `_GEN_LOG_STATE` аннотирован как 2-tuple (`summary_memory.py:1512`), хранит
  3-tuple; кэш-hint может отставать до `GRAPHRAG_GEN_WARN_COOLDOWN_SECONDS`
  (≤300 s) после смены состояния job. Не влияет на `generation_status`.
- `_payload_generation` (`:617-623`) падает `AttributeError` на payload-JSON не
  dict (list/`null`); исключение поймает внешний `maybe_schedule_rebuilds`, но
  тик индекса будет пропущен. Крайне низкий риск (payload пишет только
  `TaskJobStore`/checkpoint merge).

## 7. Порядок деплоя/активации для 2.58.113

1. **До деплоя зафиксировать финальный embedding identity** (provider/model/
   base_url/dim). Смена identity во время сборки = aborted validation + полный
   повторный re-embed.
2. 2.58.112 (fallback слоты) → **2.58.113** (этот фикс + отдельно одобренный
   W4-UI) в одном окне; рестарт сервиса — штатный. Startup-путь
   (`summary_memory.py:2573`, default `include_failed=True`) сам зарегистрирует
   поколение и запустит сборку; отдельная команда не нужна.
3. Ожидаемо: `graph_facts` eligible ≈15 819 → ≈316 HTTP-вызовов; `smart_archive`
   пуст → поколения/вызовов нет; `generation_status`: `identity_changed` /
   `building` → `build_in_progress` (кратковременно `build_pending` пока нет
   job) → `active`; `_vec_write_allowed` → `True`; FTS5 всё время обслуживает.
4. **Post-deploy canary (READY_FOR_LIVE):** `GET /api/memory/embeddings` —
   `generation.indexes[].state`, `source_empty`, `reindex_required`;
   логи `EMBEDDING_GENERATION_REBUILD_REQUIRED → BUILD_START → PROGRESS →
   VALIDATED → ACTIVATED`; счётчики source/live; ошибок провайдера нет.
   Это postdeploy-only, поэтому сейчас `Approved for controlled deployment`,
   **не** parent `DONE`.
5. Откат: kill-switch `GRAPHRAG_SHADOW_REBUILD_ENABLED=false` + рестарт
   (FTS остаётся); откат кода после успешной активации безопасен (ACTIVE
   совпадает с identity); откат **конфига** после активации запустит ещё один
   полный re-embed. Решение — по факту ошибок/квоты, без отдельного
   согласования (PET_PROJECT).

## 8. Что не проверялось

- Прод/SSH (запрещены лейном): реальная активация поколения на проде —
  post-deploy, не доказана этим ревью.
- UI/Playwright/Browser Use: в кандидате нет визуальных изменений; UI-потребитель
  `generation` — отдельный лейн W4-UI. Аддитивное поле `source_empty` не ломает
  текущий UI (в кандидате он контракт не читает).
- Чужие коммиты `b1525b60`/`3334141a` (summary-L2/B11) — вне этого лейна,
  в fix-коммите не менялись; их ревью — у соответствующих лейнов.
- Отдельной `requirements-map.json` у audit-лейна нет; acceptance — из
  `fix-b1b2.md`/`review.md` и милстоуна. `requirements_gate.py` не применим.

## Следующее действие

Orchestrator: включить `5877810d` в 2.58.113 вместе с отдельно одобренным
W4-UI; зафиксировать identity; деплой → startup-активация → DevOps
post-deploy canary (§7), затем обновить статус родителя. NB-1…NB-4 — маленький
follow-up (не блокируют этот поезд); NB-1 особенно желателен, если ожидается
A→B→A без рестарта после провала старой сборки.


