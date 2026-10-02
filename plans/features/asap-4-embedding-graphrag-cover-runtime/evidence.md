# ASAP-4 — evidence.md

> **Фича:** `asap-4-embedding-graphrag-cover-runtime` (ASAP-4, эпик 5 зон).
> **Builder Wave A (T-4402…T-4412), 02.10.2026.** Статус: реализация и верификация
> завершены; **Rework round 1** (2H+2M по findings независимого ревью T-4413,
> см. §10) — завершён. T-4413 (повторный Reviewer gate волны A) — следующий шаг.
> **Builder Wave B (T-4415…T-4420), 02.10.2026** — Cover Style production path:
> реализация и верификация завершены (раздел Wave B в конце документа).
> **Коммитов нет, деплоя нет** (зона ответственности @DevOps). Спека/ADR — Accepted
> (Step 2), конфликта с контрактами не обнаружено.

## 0. Continuity-заметка

Design-фаза эпика (prod-facts.md / spec.md / adr-1028-7 / handoff-note.md, T-4401/T-4414/
T-4421/T-4427/T-4439) выполнена **General-fallback в роли Architect** (named Architect упал
2× timeout) — см. `handoff-note.md`. Настоящая сессия — **Builder** (named, штатный старт
после `PLANNING_CONSISTENT`); fallback-исполнителя в этой сессии не было, собственный review
Builder'ом не выполнялся (reviewer-разделение соблюдено, gate — T-4413 @Reviewer).

## 1. Базовая линия и состояние рабочего дерева

* Baseline: HEAD `f04564b` (`docs(plans): mca-22 … archive`), прод-эквивалент 2.58.44,
  SQLite `user_version=22`.
* До старта в дереве уже были **чужие изменения** (сохранены, не тронуты):
  `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/workflow_state.md`,
  untracked `.playwright-mcp/`, `extra_images/`, `node_modules/`, `package*.json`,
  `plans/features/asap-4-…/` (design-документы Architect).
* После Wave A: 15 изменённых tracked-файлов + 2 новых файла
  (`services/embedding_control_plane.py`, `tests/test_embedding_control_plane_asap4.py`).
  Коммитов нет; `git diff --stat` = 1167(+)/107(−) по коду Wave A + планы.
* Line-ending гигиена (CRLF-инцидент воспроизведён и закрыт): Edit-инструмент переворачивал
  EOL — нормализовано **по конвенции HEAD каждого файла** (`git ls-files --eol`):
  `config/settings.py`, `services/llm_client.py`, `tests/conftest.py`,
  `tests/test_mca01_…` — CRLF (как в индексе; `config/settings.py` i/mixed — историческая
  1 LF-строка в HEAD, не в диффе); остальные — LF. BOM отсутствует во всех файлах
  (инцидент PowerShell `Set-Content` на database.py — найден и устранён).
  `git diff --check`: на LF-файлах — 0 находок; на CRLF-файлах (`llm_client.py`,
  `conftest.py`, `test_mca01_…`, `settings.py`) — только cr-at-eol на добавленных строках
  (свойство конвенции индекса i/crlf при `core.autocrlf=false` без
  `core.whitespace=cr-at-eol`; полная конверсия в LF создала бы full-file диффы и нарушила
  бы «сверяй с HEAD»). git config не менялся.

## 2. Изменённые файлы (якоря file:line)

| Файл | Что сделано |
|---|---|
| `services/embedding_control_plane.py` (новый, ~1560 строк) | Контрол-плейн зоны A: kill-switches (63–118), credential pool/лестница групп (150–335), 429-классификатор + честный Retry-After + burst/exhausted (340–435), `QuotaGroupRegistry` (DB v23 + in-memory, 440–590), AIMD `AdaptiveController` (595–700), `PriorityScheduler` P0–P3 surplus (700–765), `EmbeddingExecutor` (890–1180, budget ≤4, per-credential group, segmentation), adapter'ы Gemini/OpenAI-compatible (780–870), lossless segmentation (920–990), `RebuildLease` (1245–1400), coalesced log + панели (1400–1540) |
| `services/database.py` | v23 миграция: константы + DDL `embedding_quota_state` (848–878), шаг реестра (1755–1760), `_migrate_embedding_control_plane_v23` (2410–2448), 3 reader-SELECT'а реестра + pause/next_allowed/attempts_total (3073–3121) |
| `services/graphrag_rebuild.py` | Статусы §26 (63–92), adaptive batch/horizon/классификация хелперы (133–360, `_schedule_auto_resume` 322–358), KNN-диагностика §28 в `_validate` (585–660), run_job: авто-resume/конверсия failed→paused/lease/source-empty-precheck/P3-context (830–975), pause-классификация embed-фейлов (995–1030), validation_failed для knn_* (1050–1095), `_handle_build_failure` AM-1/§25 (1175–1285), schedule ordering «меньший/застрявший» (1310–1420), `_ensure_job` auto-resume §68 (1440–1500), `resume_rebuild` для всех pause-статусов (1477–1500), `_current_fp_async` из реестра (1510–1530) |
| `services/summary_memory.py` | `_embed_api` seam ON/OFF (1736–1780), `_embed` priority-kwarg (1694–1734), приоритеты P0/P2 на call-site'ах (1467, 1980, 2013, 2071, 2353, 3351), §31 coalesced INFO вместо WARNING-спама на quota-cooling (2352–2390, 3340–3370), REGISTRY.bind_db в `__init__` (1403–1412), `load_group_states` в `initialize` (1413–1424) |
| `services/llm_client.py` | `_post` opt-in `retry_statuses` (665–700, 745–790: 429/5xx наверх немедленно с in-memory headers/body для классификации — не логируются), `embed_once` (1405–1464: один credential, без каскада, transport retry ≤1, R17) |
| `services/mca_events.py` | REASON_CODES +18: paused_rate_limit/paused_provider/quota_*/embed_deferred/auth_failed/validation_failed/rebuild_lease_waiting/rebuild_quota_conversion/knn_* ×7/knn_smoke_ok (134–152) |
| `config/settings.py` | 5 kill-switches зоны A + 9 developer bounds (789–840) |
| `web/api/memory_agi.py` | `GET /api/memory/embeddings` — панели §32 из structured state (456–495) |
| `tests/conftest.py` | autouse `_asap4_flags_off_by_default` (144–177): флаги зоны A OFF для немаркированных тестов; патч классов {Settings, type(config.settings.settings), type(dcs.settings)} — закрывает S10.18-10 reload-подмену |
| `tests/test_embedding_control_plane_asap4.py` (новый, 42+8 тестов) | §64/§65/§66/§67/§68/§69/§35 + OFF-паритеты + DDL + lease + панели + **8 тестов Rework round 1 (§10)** |
| `tests/test_graphrag_rebuild_asap32.py` | **ПОПРАВКА (M-ASAP4-5, честность):** файл Wave A НЕ изменялся — прежняя строка этого раздела («обновлён 2 теста») была ЛОЖНОЙ; asap32-тесты (9/9) зелёные на Wave A-коде БЕЗ правок, knn-покрытие живёт в новом asap4-файле. В рабочем диффе файла нет (git status чист по нему) |
| `tests/test_mca05_…`, `tests/test_mca22_…`, `tests/test_mca01_…` | пины фронтира схемы v22→v23 (mark = `_SCHEMA_VERSION_EMBEDDING_CONTROL_PLANE`), allowlist write-точек database.py 144→147 (+3 санкционированных commit шага v23) |
| `pytest.ini` | маркер `asap4` |

## 3. DDL-факты (SQLite v22 → v23; PG no-op)

1. `CREATE TABLE IF NOT EXISTS embedding_quota_state (quota_group_id TEXT PRIMARY KEY,
   state TEXT NOT NULL DEFAULT 'healthy', next_allowed_at INTEGER, note TEXT,
   updated_at INTEGER NOT NULL DEFAULT 0)`.
2. `ALTER TABLE mca_embedding_index_generations ADD COLUMN pause_reason TEXT` /
   `next_allowed_at INTEGER` / `attempts_total INTEGER NOT NULL DEFAULT 0` — под guard
   `PRAGMA table_info`.
3. **Ни одного UPDATE существующих строк при миграции** (тест: pre-existing generation row
   сохранён бит-в-бит); повторный прогон — no-op (двойной прогон в тесте); PG — no-op
   (credential labels — hot-config/env; cover_* не тронуты).
4. Пауза-книжки job'ов — в существующем `task_jobs.result_ref` (JSON pause_started_at/
   pause_count/next_allowed_at) — REUSE, ΔDDL=0. Lease — существующая `task_jobs`
   (kind=`embedding_rebuild_lease`, coalesce=`embedding_full_rebuild_permit`).
5. `PRAGMA user_version` = **23** (тест); на чистой БД — в составе штатного DDL раннера.

## 4. Kill-switches зоны A (spec §8.2; env-only)

| Флаг | Default | OFF-паритет (тест) |
|---|---|---|
| `EMBED_CONTROL_PLANE_ENABLED` | ON | legacy 3-аттемпный `_embed_api` поверх `llm.embed` (3 calls, executor не вызывается) + rebuild honest-terminal failed (tests: off_parity_master/off_parity_rebuild) |
| `EMBED_QUOTA_GROUP_COOLDOWN_ENABLED` | ON | перебор ключей группы как сейчас (rotation-тест) |
| `EMBED_PRIORITY_SCHEDULER_ENABLED` | ON | без приоритетов: P0 ждёт слот наравне (test_off_parity_scheduler_flag) |
| `EMBED_ADAPTIVE_CONCURRENCY_ENABLED` | ON | статические `GRAPHRAG_REBUILD_BATCH/SLEEP` (test_off_parity_adaptive_concurrency_flag) |
| `EMBED_ASYNC_BATCH_ENABLED` | **OFF** | async Batch API выключен; включение — только после live-верификации контракта (test_async_batch_default_off) |

Плюс новая conftest-изоляция `_asap4_flags_off_by_default`: весь существующий сьют
(≈10.5k тестов) выполняется с контрол-плейном OFF (бит-в-бит legacy); ON — только
`@pytest.mark.asap4` (новые тесты) и унаследованные маркеры asap3/asap31/asap32.

## 5. Влияние на существующие тесты (честно)

* `test_graphrag_rebuild_asap32.py` — **ПОПРАВКА (M-ASAP4-5): файл НЕ изменялся**
  (заявление Wave A об «обновлённых 2 тестах» было ложным — см. §2); 9/9 зелёные
  на Wave A-коде. Функциональное покрытие «ON → validation_failed + vectors
  preserved для knn_*; структурные фейлы (fingerprint_changed/missing_vectors —
  механика D2 ADR-1028-5) terminal в ОБОИХ режимах» живёт в новом asap4-файле
  (test_validation_failure_preserves_vectors, §69-семейство, OFF-тест).
* Пины фронтира: mca-05 (v21-mark), mca-22 (v22-ассерты), mca-01 (write-point allowlist
  +3) — обновлены на v23 с комментариями (фронтир реестра законно сдвинулся).
* Инцидент изоляции (закрыт): `test_settings_worker_sync` (S10.18-10) после reload
  восстанавливает `config.settings.settings` инстансом ПЕРВОНАЧАЛЬНОГО класса → первый
  вариант conftest-фикстуры патчил только пересозданный класс → у ~3 legacy-тестов
  embed-ретраев control plane оставался ON. Закрыто патчем обоих классов; s-батч
  (1849 тестов) и полный сьют зелёные.

## 6. Прогоны (финальные счётчики)

| Прогон | Результат |
|---|---|
| Полный pytest (`tests --timeout=120 -q`, финал) | **10562 passed / 2 failed** — оба known pre-existing: `test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` (воспроизведены также на чистом HEAD-worktree) |
| Новый файл | 42/42 (`tests/test_embedding_control_plane_asap4.py`, маркер asap4) |
| `tests/test_graphrag_rebuild_asap32.py` | 9/9 |
| `test_graphrag_memory.py` + `test_graphrag_database.py` | 220/220 |
| `test_mca07_retrieval_context_round1027.py` | 43/43 |
| F8: `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488 == REGISTRY…`, **EXIT=0** (Δ каталога = 0) |
| R17-скан диффа | реальных секретов нет (в тестах только placeholder-ключи `k1/kA/super-secret-key-value` — фейковые, для проверки маскировки) |

Воспроизведение: `.venv\Scripts\python.exe -m pytest tests --timeout=120 -q`.

## 7. Покрытие acceptance-фикстур (ТЗ §64–§69, §35)

* **§64 retry storm** — primary 429 + fallback same group + RA=20s: ровно **1** логический
  HTTP-вызов (не 21); group `cooling_down` c `next_allowed_at≈+20s`; same-group key не
  вызван; job → `paused_rate_limit` с checkpoint preserved (processed=2) и registry
  pause-колонками; burst-вариант (RA≤60) — ожидание + одна пере-подача; ceiling ≤4
  зафиксирован отдельным тестом (4 transport-фейла → ровно 4 вызова).
* **§65 independent groups** — A 429 → B продолжает (`keys_called == [kA, kB]`), A остаётся
  в cooldown, повторный запрос сразу на B; успешный батч один, векторов ровно N.
* **§66 arbitrary pool** — 1/3/5 credentials; aliases `extra_N`; executor живёт с любым
  размером; перебор при OFF-cooldown не предполагает ровно два fallback.
* **§67 online priority** — P3 в полёте → P0 ожидает bounded → обслуживается ДО следующего
  P3-батча → rebuild возобновляется; P3-surplus семантика отдельно.
* **§68 restart during pause** — `paused_rate_limit` + checkpoint=2: до истечения
  `next_allowed_at` schedule не запускает; после (симуляция) — resume ТОЙ ЖЕ generation
  (не gen 2), без дублей (embed.texts == 6), cooldown уважается; авто-resume — отдельный
  тест с реальным фоновым контуром.
* **§69 KNN diagnostics** — 6 различимых причин (вкл. healthy `knn_smoke` ok в валидации);
  каждый — отдельный тест; `knn_smoke_failed` кодом больше не производится.
* **§35 provider-switch** — OpenAI-compatible adapter (2-й провайдер) + Gemini; классификация
  не привязана к 429 Google.

## 8. Что НЕ сделано / остатки (честно)

1. **`EMBED_ASYNC_BATCH_ENABLED` не включается** (default OFF, по спеке): live-верификация
   контракта Batch API — owner/DevOps гейт до включения; кода async-пути в Wave A нет
   (gated-опция), только флаг и контракт в панели.
2. **Embedding Run Inspector §62** — финализация в Wave E (зависимость T-4439 event
   schema); сейчас панели отдают state-срез (`/api/memory/embeddings`), UI-виджет миниаппа
   на панели — Wave E (T-4446 browser-suite).
3. **Live acceptance §34/§77** (реальные 429/KNN на проде, REAL quota) — PENDING OWNER
   (платные вызовы), вне скоупа Builder.
4. **Multi-process lease** покрыт DB-строкой в `task_jobs` + heartbeat/takeover; строгость
   под TaskSupervisor при реально втором процессе бота на проде — верифицируется DevOps
   на деплое (в проде один процесс; прод-факт Q5).
5. **`_save_graph_fact_embedding` и memorize-пути** получают контрол-плейн через общий seam
   `_embed` (P1) — отдельных инструментов приостановки P1-трафика при exhausted не введено
   (не требовалось спекой: P1 через executor получает отказ наверх → существующие
   fail-open ветки WARNING).
6. Две известных pre-existing failure (round1026 forbidden_paths) — вне эпика, не тронуты.
7. Причина `knn_query_vector_failed` — **закрыто в Rework round 1** (M-ASAP4-4):
   ветка существует и покрыта тестом `test_knn_query_vector_failed_distinct_reason`
   (см. §10.4); в Wave A заявления «ветка существует» было неточным — ветки не было.

## 9. Риски/наблюдения для Reviewer (T-4413)

* `PriorityScheduler` — in-process (один deployment = один процесс бота, прод-факт Q5);
  межпроцессная координация — только lease на full-rebuild (по спеке §22 этого достаточно:
  process-local лимиты живого embed-трафика не требуются).
* Adaptive batch: developer `GRAPHRAG_REBUILD_BATCH` трактован как старт И потолок
  (спека: «старт 32–50, границы env»; прод 50 — совпадает; выше конфига AIMD не растёт) —
  осознанный выбор в пользу детерминизма developer-конфига, задокументирован в коде.
* `unknown`-группа при отсутствии provider-сигнала классифицируется как burst (дефолт-
  кулдаун 20s, не exhausted) — консервативно против ложной фиксации exhausted на 20с
  (прод-факт Q4: Gemini обычно без Retry-After); daily/spend детектируются по телу.

## 10. Rework round 1 (02.10.2026, по findings независимого ревью T-4413 round 1)

Base rework'а: то же рабочее дерево Wave A (HEAD `f04564b`, без коммитов); ревью
выполнено на Reviewed-Commit `f04564b` + Wave A-диф. Все правки — в файлах
`services/llm_client.py`, `services/graphrag_rebuild.py`,
`tests/test_embedding_control_plane_asap4.py`, spec.md (ратификация), этот
evidence.md, tasks.md. Коммитов нет.

### 10.1 [H-ASAP4-1] retry-ownership на HTTP-слое — ЗАКРЫТО

* **Было:** `retry_statuses` имел blocklist-семантику; при `()` условие
  `status in retry_statuses` всегда-ложно → ветка «429/5xx наверх немедленно»
  мертва; 429 давал 2 HTTP-вызова, первый нижнеуровневый ретрай спал
  `min(Retry-After, 8s)` (анти-паттерн §9/Q4).
* **Стало:** allowlist-семантика (`llm_client.py:706-718`): `None` → бит-в-бит
  прежний сет (408/425/429/5xx); кортеж → ретраится ТОЛЬКО перечисленное
  (`()` → ни одного статус-ретрая). Terminal-классификация едина
  (`llm_client.py:776-821`): 429 → `LLMRateLimitError` c headers/body
  in-memory (R17) без сна; 5xx → `LLMServerError` (diag-лог — только legacy
  `None`-путь); transport retry не зависит от параметра. Quota-решения —
  ТОЛЬКО в EmbeddingExecutor (не изменено).
* **Тесты (уровень НАСТОЯЩЕГО `_post`, httpx.MockTransport):**
  `test_post_retry_statuses_empty_429_single_call_no_sleep` — 429 → ровно
  1 HTTP-вызов, `sleeps == []`, честный Retry-After=20 в исключении;
  `test_post_retry_statuses_allowlist_retries_only_listed` — `(503,)`:
  503 → 2 вызова (ретраится), 429 → 1 вызов;
  `test_post_retry_statuses_none_legacy_retries_429` — `None` → 2 вызова +
  сон ровно `min(20, backoff_cap)` (бит-в-бит паритет legacy).
* Контракт `embed_once`/`embed_batch` не менялся (docstring уже описывал
  целевую семантику) — сломан был нижний слой.

### 10.2 [H-ASAP4-2] CoolingDown/Budget → terminal failed — ЗАКРЫТО

* **Было:** `EmbeddingGroupCoolingDown`/`EmbeddingBudgetExhausted`/
  `EmbeddingConcurrencyBusy` не матчились ни на один класс → terminal
  `failed` с reason=именем класса (нарушение AM-1/§26; воспроизведено
  ревью: группа ушла в cooldown между батчами → job failed).
* **Стало** (`graphrag_rebuild.py:1279-1326`): явные isinstance-ветки ДО
  эвристик по именам: CoolingDown → `paused_rate_limit` с next_allowed_at
  ИЗ исключения (без повторной классификации тела), reason
  `rate_limit:quota_group`; BudgetExhausted/ConcurrencyBusy →
  `paused_provider` (developer-кулдаун ×2 в пределах ceiling; horizon §25
  ограничивает). Общая механика паузы вынесена в `_apply_pause`
  (`graphrag_rebuild.py:1207-1233`): CAS + pause-bookkeeping (result_ref) +
  pause-колонки реестра v23 + событие + `_schedule_auto_resume`; checkpoint
  НЕ трогается. Resume: paused → queued → build продолжается с checkpoint
  (§68-семантика), для checkpoint-стадии — re-validate
  (`_create_shadow` идемпотентен, векторы живы).
* **Негативный тест:** `test_cooling_group_between_batches_pauses_not_fails`
  — 1-й батч OK, CoolingDown(+120s) между батчами → `paused_rate_limit` (НЕ
  failed), `pause_reason=rate_limit:quota_group`, next_allowed ≥ +100s,
  attempts_total=1, checkpoint processed=2, авто-resume запланирован.
  `test_executor_budget_or_busy_pauses_not_fails` (параметризован) —
  BudgetExhausted/ConcurrencyBusy → `paused_provider`/`provider_unavailable`.

### 10.3 [M-ASAP4-3] пост-checkpoint исключения тонут — ЗАКРЫТО

* **Было:** все CAS в `_handle_build_failure` с жёстким `expect=ST_RUNNING` —
  исключение из `_validate`/emit после CAS RUNNING→CHECKPOINT молча no-op;
  job навсегда checkpoint, пере-resume'ится планировщиком без horizon.
* **Стало** (`graphrag_rebuild.py:1257-1265,94-99`): фактический статус
  читается на входе (`_get_job`), все CAS — от `expect=фактический статус`
  для build-активных статусов (`_FAILURE_CAS_FROM`); deterministic-класс на
  checkpoint-стадии → честный terminal `failed` (§25), quota-класс → пауза с
  checkpoint-preserved; терминальные/паузные статусы остаются безопасным
  no-op (expect=ST_RUNNING). Horizon-проверка — первой, без изменений.
* **Тест:** `test_post_checkpoint_validation_exception_honest_terminal` —
  RuntimeError на sample-fetch в `_validate` (после CAS→CHECKPOINT) →
  `failed`/`RuntimeError`. До фикса: статус оставался `checkpoint`.

### 10.4 [M-ASAP4-4] knn_query_vector_failed недостижим — ЗАКРЫТО

* **Было:** провал построения query-вектора (json.dumps внутри общего try с
  MATCH-запросом) маскировался под `knn_index_schema_mismatch`; 7-й код A.6
  не производился (заявление §8.7 Wave A было неточным — исправлено).
* **Стало** (`graphrag_rebuild.py:729-760`): узкий except вокруг построения
  query-вектора → `knn_query_vector_failed`, diag `stage=query_vector_build`,
  `query_vector_ok=false`; MATCH-запрос — отдельный try → по-прежнему
  `knn_index_schema_mismatch` (с `query_vector_ok=true` — существующий тест
  не тронут и зелёный).
* **Тест:** `test_knn_query_vector_failed_distinct_reason` — несериализуемый
  вектор с корректным len() (проходит dim-гейт) → 7-й код. Все 7 кодов A.6
  теперь воспроизводимы тестами.

### 10.5 Не-блокеры ревью

* **M-ASAP4-5 (evidence-integrity):** исправлено честно — §2/§5 больше не
  утверждают обновление `test_graphrag_rebuild_asap32.py` (файл в дереве не
  менялся; см. поправки в §2/§5).
* **L-ASAP4-6 (лестница §5):** ратифицировано как уточнение спеки —
  spec.md §A.1: шаги 1–2 слиты в один label-источник (2 ступени вместо 4),
  основание — прод-факты Q1/Q8; семантика (safe default, запрет project из
  ключа) сохранена.
* L-ASAP4-7 (прямой тест `load_group_states`) — НЕ делалось (вне объёма
  rework'а); L-ASAP4-8 (вестижный always-true assert в
  `test_restart_during_quota_pause:636-637`) — НЕ трогался (вне объёма;
  за Reviewer'ом решить, чинить в rework или отдельным хвостом).

### 10.6 Прогоны Rework round 1

| Прогон | Результат |
|---|---|
| Полный pytest (`tests --timeout=120 -q`) | **10570 passed / 2 failed** (те же 2 known pre-existing round1026 forbidden_paths) = 10562 Wave A + 8 новых |
| `tests/test_embedding_control_plane_asap4.py` | **50/50** (42 + 8 новых) |
| Соседи: asap32 + graphrag_memory + graphrag_database + deep_sleep + chat_keys + budget_global + direct_fallback_asap32 + mca07 | 371 passed |
| Соседи: summary_memory + пины mca-01/05/22 | 233 passed |
| F8 `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488`, **EXIT=0** |
| EOL/BOM | `llm_client.py` — CRLF по конвенции HEAD (Edit-переворот замечен и нормализован обратно); `graphrag_rebuild.py`, asap4-тест, plans-доки — LF; BOM нет; `git diff --check` по LF-файлам — 0, по CRLF — только cr-at-eol добавленных строк (конвенция индекса, как в §1) |

### 10.7 Diff-якоря Rework round 1 (для детерминированного манифеста Reviewer)

* `services/llm_client.py:671` — сигнатура `_post(..., retry_statuses)` (не менялась);
  `:684-696` — docstring allowlist; `:706-718` — предикат `_retryable`;
  `:778-813` — единая terminal-классификация (условие ретрая 778, 429-raise
  784-791, 5xx-raise 800-813).
* `services/graphrag_rebuild.py:90-99` — `_FAILURE_CAS_FROM`;
  `:729-760` — M-4 (query_blob try/except, knn_query_vector_failed);
  `:1207-1229` — `_apply_pause`; `:1231-1381` — `_handle_build_failure`
  (docstring 1232-1249; expect от фактического статуса: 1251-1258;
  CoolingDown: 1279-1306; Budget/Busy: 1308-1331; rate-limit: 1333-1352;
  provider: 1354-1367; deterministic terminal: 1369-1381).
* `tests/test_embedding_control_plane_asap4.py:1165-1433` — блок
  «Rework round 1»: 8 тестов (H-1 ×3 на настоящем `_post` с
  httpx.MockTransport, H-2 ×2 — cooling между батчами и
  параметризованный budget/busy, M-3 ×1 — пост-checkpoint terminal,
  M-4 ×1 — 7-й код) + helpers `_CountingHandler`/`_post_client`/
  `_spy_sleep`/`_UnserializableVector`.
* `plans/.../spec.md` §A.1 — уточнение лестницы (ратификация L-ASAP4-6).
* `services/embedding_control_plane.py`, `services/database.py`,
  `services/summary_memory.py`, `services/mca_events.py`, `config/settings.py`,
  `web/api/memory_agi.py`, `tests/conftest.py`, пины — **не менялись в rework'е**
  (диффы §2 — только Wave A).

### 10.8 Осталось непроверенным/за пределами rework'а

* Live-acceptance §34/§77 — PENDING OWNER (как раньше).
* §64-фикстура через реальный `_post`-стаб: покрытие обеспечено связкой
  «executor-тесты (FakeLLM на embed_once) + 3 новых `_post`-теста на
  настоящем transport-фейке» — комбинированный слой проверен, сквозной
  fixture §64 через настоящий `_post` не переписывался (FakeLLM остаётся на
  уровне embed_once; теперь контракт обоих слоёв зажат тестами по отдельности).
* L-ASAP4-7/L-ASAP4-8 — не в объёме (см. §10.5).
* `EMBED_ASYNC_BATCH_ENABLED` / multi-process lease — как в §8.

---

# Wave B — Cover Style production path (T-4415…T-4420, 02.10.2026)

> **Builder Wave B** (та же сессия, штатное продолжение после Wave A Rework-1).
> Коммитов нет, деплоя нет. Base: то же рабочее дерево (HEAD `f04564b`),
> Wave A-диф не тронут (файлы Wave A менялись только там, где это контракт
> волны B: `settings.py`/`mca_events.py`/`conftest.py` — аддитивные строки).
> Спека §2 + ADR-1028-7 D6 — Accepted; конфликтов с контрактами не найдено.

## B1. Базовая линия и состояние дерева

* Baseline: HEAD `f04564b` (не менялся); прод-эквивалент 2.58.44, SQLite v23
  (Wave A). До Wave B в дереве: Wave A-диф (15 tracked + 2 новых) + чужие
  plans/untracked — сохранены, не тронуты.
* После Wave B дополнительно: 9 modified (6 services, settings, conftest,
  web/api/cover_styles) + 1 новый тест-файл
  `tests/test_cover_style_wave_b_asap4.py` (26 тестов, маркер `asap4`).
* EOL/BOM: правки по конвенции HEAD каждого файла (`git ls-files --eol`):
  CRLF — `config/settings.py` (i/mixed), `tests/conftest.py`; LF — все
  остальные (`cover_style_jobs.py`, `summary_generator.py`,
  `task_supervisor.py`, `media_execution.py`, `cover_style_registry.py`,
  `mca_events.py`, `summary_test_run.py`, `web/api/cover_styles.py`, новый
  тест — LF). BOM отсутствует во всех 10 файлах (байт-проверка).
  `git diff --check`: на LF-файлах волны B — 0 находок; на CRLF — только
  cr-at-eol добавленных строк (свойство конвенции индекса i/crlf, как в §1).

## B2. Изменённые файлы (якоря file:line)

| Файл | Что сделано (Wave B) |
|---|---|
| `config/settings.py` | `COVER_STYLE_SNAPSHOT_ENABLED` (env-only, default ON; OFF = бит-в-бит legacy) — 841–847 |
| `services/mca_events.py` | REASON_CODES +7 волны B: `no_style/profile_missing/disabled/connection_missing/reference_missing/capability_unknown/not_configured` (155–159; комментарий — прод-факт Q14/Q15) |
| `services/cover_style_jobs.py` | События `COVER_STYLE_SELECTION` (59)/`COVER_STYLE_SKIPPED` (67); причины+`style_reason_code` (75–122)+human-переводы `reason_detail_ru`/`style_skip_status` (§43, 124–145); SAFE_LOG_FIELDS +11 safe-полей (127–143); kill-switch `snapshot_enabled()` (229–241); snapshot-блок §36/§37: `_selection_source` (640)/`resolve_selection` (662)/`emit_style_selection` (693)/`selection_stage` (709); `profile_for_snapshot` (729)/`report_style_skip` (757)/`record_no_cover_provenance` (798); reference integrity §45: `_image_signature_ok` (847)/`_resolve_reference_details` (858); `profile_diagnostics` §41 (897); `run_style_job` (1045): `connection_missing`-выход (1120–1133), `capability_state` (1158), pre-counter `not_configured` (1165–1186), reference integrity+`reference_missing` (1187–1196), counter ПОСЛЕ pre-checks (1201–1212), `prompt_diagnostics` §46 (1230–1242), SUBMITTED с diagnostics при ON (1244–1268), `_style_failed` reason_code passthrough при ON (1395–1420); `__all__` расширен |
| `services/summary_generator.py` | `_publish_rich_document`: snapshot+SELECTION до base generation (1348–1354); provenance `no_cover` на обоих base-failure путях (1391–1400, 1419–1428); `_maybe_apply_cover_style(..., snapshot=)` (1436–1443); `_maybe_apply_cover_style` — snapshot-путь с видимыми skip'ами + legacy-путь бит-в-бит при OFF (1574–1650) |
| `services/task_supervisor.py` | **L-EXTRA-6**: `save_checkpoint` — MERGE вместо overwrite (615–662): SELECT payload в транзакции, `cursor`/`processed` вливаются, identity-поля (cover: chat_id/correlation_id/style_id; graphrag: fingerprint/generation) сохраняются |
| `services/media_execution.py` | Сопутствующий L-EXTRA-6 фикс: `recover_media_jobs` — cursor-снимок приоритетен над identity-полями merged payload (753–766; прежний код полагался на overwrite-семантику; регресс `test_restart_resume_by_provider_job_id_no_resubmit` воспроизведён и закрыт) |
| `services/cover_style_registry.py` | **rowcount→200**: `update_reference` парсит asyncpg-статус `UPDATE N` через `_update_status_count` (408–447); `UPDATE 0` → False → API 404 |
| `services/summary_test_run.py` | **L-ASAP31-4**: dry-run строит FactPackage с resolver-бюджетом живого пути (`resolve_l2_package_budget` → `budget=`, 590–598) |
| `web/api/cover_styles.py` | `GET /cover/styles/{id}` → `payload["diagnostics"]` (§41, 174–191); test-style UI-сообщения для `connection_missing`/`reference_missing` (744–760) |
| `tests/conftest.py` | `COVER_STYLE_SNAPSHOT_ENABLED` в autouse OFF-by-default (173–176): старые тесты — legacy-контур; asap4/asap3x-маркированные — прод-дефолты (ON) |
| `tests/test_cover_style_wave_b_asap4.py` (новый) | 26 тестов — см. B5 |

## B3. Kill-switch зоны B (spec §8.2)

| Флаг | Default | OFF-паритет (тест) |
|---|---|---|
| `COVER_STYLE_SNAPSHOT_ENABLED` | ON | бит-в-бит прежний контур: без snapshot/SELECTION/SKIPPED, тихие ранние выходы, прежний порядок counter'а и событий COVER_*; `run_style_job` — прежний порядок (issue до refs, SUBMITTED до edit), collapsed `reason_code` (parity-тест `test_off_parity_no_snapshot_no_events`; `run_style_job`-ветки `_wb`-гейтованы) |

Изоляция: conftest-фixture волны A расширена флагом зоны B — весь
существующий сьют идёт при OFF (легаси), ON — только `asap4`-маркированные.
Отметка: `test_cover_styles_contract_asap32.py` (маркер asap32) идёт при ON и
зелёный — ON-путь совместим с контрактом ASAP-3.2.

## B4. Прогоны (финальные счётчики)

| Прогон | Результат |
|---|---|
| Полный pytest (`tests --timeout=120 -q`, финал Wave B) | **10596 passed / 2 failed** — те же 2 known pre-existing round1026 forbidden_paths (вне эпика; = Wave A 10570 + 26 новых) |
| Новый файл | 26/26 (`tests/test_cover_style_wave_b_asap4.py`) |
| Соседи cover/summary/supervisor | 382 passed (jobs/pipeline/runtime/api/registry/ui/contract-asap32/round1023/test_run/mca01/publish-integration/logging-runid/hotfix5/model-compat) |
| Соседи checkpoint-потребители + Wave A | 154 passed (mca13/mca17a/asap4-embedding/graphrag-asap32) |
| Изоляция | медиа-регресс L-EXTRA-6 закрыт (`test_media_execution_asap32` 44/44 в связке с новым файлом); off-паритет — устойчив в полном сьюте (патч класса из `type(j.settings)` — третий вариант S10.18-10) |
| F8 `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488`, **EXIT=0** (Δ каталога = 0; новый флаг env-only, в каталог не входит) |
| EOL/BOM | см. B1 — по конвенции HEAD, BOM нет |
| R17 | в событиях/логах только id/числа/enum (`SAFE_LOG_FIELDS` +11 полей — числа/bool/короткие коды); api_key не читается в diagnostics; контент референсов не логируется (тест) |

Воспроизведение: `.venv\Scripts\python.exe -m pytest tests --timeout=120 -q`.

## B5. Покрытие acceptance-фикстур (ТЗ §36–§47, §70–§73)

* **§36/§37 (T-4415)** — snapshot-поля/единый резолв (тест: ровно 1 вызов
  `resolve_selected_style_id` на publication, включая style stage);
  `COVER_STYLE_SELECTION` раньше base generation и edit (order-тест);
  selection_source chat/global/none; R17-safe поля.
* **§38/§39 (T-4416)** — регресс §39: selected `medved_press` → force
  Legacy (`_deliver_rich`) → Legacy article → base cover → `COVER_STYLE_START`
  + `COVER_STYLE_SUCCEEDED` (единое ядро с Hybrid — §70-тест на том же
  `_publish_rich_document`).
* **§40 (T-4417)** — preview/prod через один `run_style_job`: тот же слот,
  различия только issue/mode (тест эквивалентности); connection resolution
  общий; L-ASAP31-4 закрыт (budget-spy).
* **§41 (T-4418)** — `profile_diagnostics` чек-лист (без секретов; тест
  grep'ает blob на `api_key`/`secret`).
* **§42–§44 (T-4419)** — матрица причин: `no_style` (INFO), `profile_missing`
  (WARNING+provenance base), `disabled` (WARNING), `edit_unsupported`
  (gate, API не вызывается), `connection_missing` (default-слот молча не
  подставляется), `reference_missing` (интегрити до counter),
  `not_configured` (pre-counter, SUBMITTED не эмитится), `capability_unknown`
  (виден в meta/event, НЕ блокирует — §58); provenance
  styled/base_fallback/no_cover при всех исходах; counter: 0 на
  конфиг-фейлах / 1 на timeout-after-submission.
* **§45/§46 (T-4418)** — интегрити: DB-row/file/MIME-сигнатура/readable;
  битый (jpg-байты под .png) отфильтрован, валидный в edit request;
  `reference_bytes_total` в событии; diagnostics: instruction/brief/compiled
  chars, issue_present, limit_unit, dropped_sections (P2 выброшен — виден).
* **§47 (T-4418)** — capability matrix yes/no/unknown (no → exit+UI-сообщение;
  unknown → не блокирует + `capability_state`). **Живой Qwen test call —
  PENDING OWNER (DC-4/платный вызов), см. B7.**
* **§70/§71/§72/§73 (T-4420)** — см. тесты `TestUnifiedPipeline`
  (happy/legacy/failure+retry), `TestSelectionSnapshot` (persistence через
  «рестарт»), OFF-паритет.

## B6. Контрактные решения волны B (для Reviewer)

1. **`connection_missing` — ранний выход** (не fallback на default-слот):
   профиль, указывающий на несуществующее подключение, не отправляет edit на
   другую точку, которую владелец не настраивал (spec §2 B.4 —
   `connection_missing` в списке ранних выходов; «ничего не молчит»).
   Узкий случай: ранее default-слот молча подставлялся (§73-UI это и
   показывал как деградацию). Preview идёт через ту же ветку — унификация
   §40 сохранена; UI-сообщение test-style обновлено.
2. **`capability_unknown` НЕ блокирует edit** (диагностика, не выход):
   блокировка противоречила бы §58 («unknown не блокирует») и убила бы
   editing для провайдеров без discovery (default-слот прод). Честность
   обеспечена `capability_state` в meta/событии + переводы §43.
3. **`no_style` — INFO, без provenance** (против WARNING+запись на каждом
   run без стиля): выбор источника виден в `COVER_STYLE_SELECTION`
   (`selection_source=none`); потеря ВЫБРАННОГО стиля (profile_missing/
   disabled) — WARNING + provenance base_fallback.
4. **`not_configured` проверяется в `run_style_job` до counter** и
   `COVER_STYLE_SUBMITTED` на этом пути не эмитится (submission не было —
   событие честнее; прод-таймлайн Q14 `SUBMITTED(issue=1)→FAILED` больше не
   воспроизводится). Поведение гейтовано `_wb` — при OFF прежний порядок.
5. **L-EXTRA-6 merge** затрагивает общий `TaskJobStore.save_checkpoint`:
   graphrag-identity (fingerprint/generation) теперь переживает checkpoint
   (прежний workaround `graphrag_rebuild.py:857` остаётся валидным —
   срабатывает только при отсутствующих полях); media-консьюмер переведён
   на приоритет cursor-снимка (регресс-тест из ASAP-3.2 зелёный).
6. **Provenance при skipped/no_cover пишется только при выбранном стиле**
   (style_id известен); интерпретация R4-B-009 «в каждом production run» —
   «в каждом run с выбранным стилем, при любом исходе» — run без стиля не
   имеет style-контекста для записи; видимость обеспечена
   COVER_STYLE_SELECTION/PIPELINE_DONE.

## B7. Что НЕ сделано / остатки (честно)

1. **§47 real test call / §48/§78/§49 живая приёмка — PENDING OWNER (DC-4 +
   платные вызовы)**: edit-capable connection (Qwen) в Connections layer не
   настроен (прод-факт Q14: все 3 runs пали `not_configured` за 72 мс).
   Код/тесты не блокируются; закрывать кнопкой «Протестировать стиль»
   запрещено (§84).
2. **UI-виджет run detail с human-причиной (§43)** — словарь переводов
   (`reason_detail_ru`/`style_skip_status`) и reason codes в событиях готовы;
   рендер в Mini App — Wave E (Run Inspector, T-4441–T-4444), отдельного UI в
   зоне B по спеке не требуется.
3. **Aggregate-подсчёт reason codes в Analytics** — Wave E (агрегаты из
   mca_events).
4. Два known pre-existing failure (round1026 forbidden_paths) — вне эпика.
5. `update_reference`-фикс меняет контракт API-ответа: ранее `UPDATE 0`
   возвращал ложный 200, теперь 404 — единственный вызов в UI
   (`cover_reference_replace`) уже обрабатывает 404 (проверено кодом);
   живой прогон UI — за Reviewer/DevOps на приёмке.

## B8. Риски/наблюдения для Reviewer

* `resolve_selection` добавляет один PG-запрос профиля в начало cover
  publication (до base generation) при выбранном стиле — latency ~мс,
  fail-open (недоступность PG → snapshot None → legacy-тихий контур).
* `snapshot["_profile"]` — in-memory carry; повторного чтения профиля нет
  (снапшот-семантика §29: правка профиля посреди run не влияет на job).
* OFF-паритет `run_style_job` проверен существующими 62 EXTRA-тестами
  (они идут при OFF через conftest) + явным parity-тестом публикации.
* Изоляция полного сьюта: у flag-патча три класса (третий вариант
  S10.18-10 — consumer-модуль держит instance оригинального класса после
  чужого reload); воспроизведено на `test_bot_main_flow` + off-паритет и
  закрыто в самом тесте (`_flag`).


# Wave C — Summary full-window (T-4422…T-4426, 02.10.2026)

> **Builder Wave C** (штатное продолжение сессии после Wave B). Коммитов нет,
> деплоя нет. Base: то же рабочее дерево (HEAD `f04564b`); Wave A/B-дифы не
> тронуты (файлы волн A/B менялись только там, где это контракт зоны C:
> `settings.py`/`mca_events.py`/`conftest.py` — аддитивные строки).
> Спека §3 + ADR-1028-7 D7 — Accepted; конфликтов с контрактами не найдено.
> **Прод-триада закрыта:** too_many_facts-invalid (Q17), quote_attribution
> reject (Q18), silent XML 307/688 — каждая воспроизведена тестом на
> актуальном коде и починена (R4-D-000).

## C1. Базовая линия и состояние дерева

* Baseline: HEAD `f04564b` (не менялся). До Wave C: Wave A/B-дифы + чужие
  plans/untracked — сохранены, не тронуты.
* После Wave C дополнительно: 8 modified
  (`summary_l1_clusterizer.py`, `summary_l2_writer.py`,
  `summary_generator.py`, `summary_run_log.py`, `mca_events.py`,
  `config/settings.py`, `tests/conftest.py`,
  `tests/test_summary_coverage_asap31.py`) + 4 новых файла
  (`services/summary_l1_capacity.py`, `services/summary_quote_repair.py`,
  `services/summary_legacy_fullwindow.py`,
  `tests/test_summary_wave_c_asap4.py`).
* EOL/BOM: правки по конвенции HEAD (`git ls-files --eol`): CRLF —
  `config/settings.py` (i/mixed), `tests/conftest.py` (i/crlf); LF — все
  остальные (кластеризатор, l2_writer, generator, run_log, mca_events,
  asap31-тест, 4 новых файла). BOM отсутствует (байт-проверка).
  `git diff --check` по файлам волны C (LF) — **0 находок, EXIT=0**; по
  CRLF-файлам — только cr-at-eol добавленных строк (конвенция индекса,
  как в §1; включает унаследованные волны A/B строки).

## C2. Изменённые файлы (якоря file:line)

| Файл | Что сделано (Wave C) |
|---|---|
| `services/summary_l1_capacity.py` (новый, ~350 строк) | T-4422 (§50.36/§51/§52): kill-switch `capacity_guard_enabled` + developer bounds (`target_facts_per_chunk`/`messages_per_fact`); planning estimate `estimate_expected_facts` (message count + reply density) + `plan_required_chunks`; `repartition_by_count` (равномерная хронологическая нарезка с overlap=1, §122); `repair_capacity_overflow` — deterministic §51 repair: topic-dedupe → fact-dedupe (union evidence) → split semantic subthread (тред >30 → подсмыслы ≤30, `topic · N`, `thread_id_pN`) → allocate output budget (drop минимально подтверждённых при тотальном >1000, счётчик); вход не мутируется; `CAPACITY_REASONS`; R17-логи `L1_CAPACITY_PLAN`/`L1_CAPACITY_REPAIR` |
| `services/summary_l1_clusterizer.py` | planning-блок в `run_l1` до model call (~1208–1240: конверт = конверт lossless chunking — `_allow_chunking` + guard + `SUMMARY_COVERAGE_CHUNKING_ENABLED` + не-`legacy_static`; физические партиции — минимум, планировщик добавляет; `_run_l1_lossless(partitions=…)`); pre-validation capacity repair в attempt-цикле (~1408–1432: invalid `too_many_*` при ON → `repair_capacity_overflow` → revalidate, БЕЗ нового LLM-вызова); `_run_l1_lossless(..., partitions=None, overlap_count=0)` + post-merge capacity repair (~890–905: merge-union не превышает капы) |
| `services/summary_quote_repair.py` (новый, ~370 строк) | T-4423 (§53/§53.1/§53.2/§54, §50.20): 5 reason codes; `process_paragraph_quotes` — extract → resolve против FactPackage (speaker-index фрагментов) → validate speaker → deterministic safe repair (снять префикс `Имя:`/хвост `— сказал Имя` + de-quote; последняя линия — удалить недоказуемую формулировку с сохранением события) → revalidate (2 прохода, дедуп обработанных); **extension, не fork**: статусы `resolved/ambiguous/unresolved` импортированы из `services/quote_resolver` (MCA-22 D3, ADR-1028-6), инварианты лестницы сохранены (ближайшее имя ≠ proof; ≥2 автора → ambiguous; unknown > hallucinated); второй resolver живого контура не создан (L2-случай — внутрипайплайновый, без БД/ledger-ступеней — задокументирован как extension); `QuoteStats` (quotes_total/verified/repaired/removed/reason_codes/failure_reason — без текстов цитат); kill-switch `quote_repair_enabled` |
| `services/summary_l2_writer.py` | `_validate`: quote-блок под kill-switch — ON: `process_paragraph_quotes` (fail-closed только при невозможности safe repair, §54; umbrella-счётчик `quote_attribution_count` сохранён + подпричины в `quote_reason_codes`), OFF: прежняя матрица §50.20 бит-в-байт (баг живёт — rollback-контур); metrics +quotes_total/verified/repaired/removed; `_log_complete` +quotes-счётчики (числа); lazy-import quote_repair в `_validate` (разрыв цикла импорта) |
| `services/summary_legacy_fullwindow.py` (новый, ~230 строк) | T-4424/T-4425 (§55/§56/§57, §50.37): kill-switch `legacy_full_window_enabled`; `resolve_window_caps` (те же hot-ключи, что `summary_xml`); `flat_fits`/`xml_built_count` (плоский XML покрыл всё окно?); `compute_package_coverage` (considered = chronology ∪ fragments ∪ evidence ∪ unassigned); `build_legacy_package_content` (детерминированный compact-JSON с Legacy-заголовком, без length-блока; system-канон R11 не меняется); R17-логи `LEGACY_FULL_WINDOW`/`LEGACY_COVERAGE_DEGRADED` |
| `services/summary_generator.py` | `_run_legacy_pipeline(..., semantic_package=None)`: после сборки плоского XML — `flat_fits`; малое окно/OFF → бит-в-бит; большое окно при ON → `_build_legacy_full_window_context` (reuse semantic package от Hybrid; при отсутствии — `build_fallback_package` полного окна с Legacy-бюджетом §92-пэйлоада); контент пакета заменяет ТОЛЬКО секцию истории (`_compose_user_content(full_window_context or xml_context, …)`); safety-обрезка поверх пакета → видимый degraded (`legacy_budget_reduction`); `_build_legacy_full_window_context` (async; coverage → ctx + degraded-событие `SUMMARY_COVERAGE_DEGRADED`/reason `legacy_coverage_partial`); `_run_hybrid_l2._legacy_fallback` передаёт `package_result.package` (Level-3 получает ТОТ ЖЕ пакет, что L2 — ADR D7.3); `package_result = None` до closure (exception-пути); hybrid-путь пишет coverage в ctx (единый расчёт) |
| `services/summary_run_log.py` | `RunContext` +`source_total`/`source_considered`/`source_coverage` (run state, §61.6-каркас); `SUMMARY_COMPLETE` +`coverage=` (аддитивно, R17-число) |
| `services/mca_events.py` | REASON_CODES +9 волны C: `quote_text_not_found/quote_speaker_unresolved/quote_speaker_mismatch/quote_source_ambiguous/quote_attribution_repaired` (§53.1; umbrella `quote_attribution` остался в l2_writer для логов/OFF) + `l1_capacity_sharded/l1_capacity_repaired/legacy_full_window/legacy_coverage_degraded` |
| `config/settings.py` | 3 kill-switches зоны C (env-only, default ON) + 2 developer bounds планировщика (`SUMMARY_L1_TARGET_FACTS_PER_CHUNK=24`, `SUMMARY_L1_FACT_DENSITY_MESSAGES_PER_FACT=12`) — ~848–871 |
| `tests/conftest.py` | 3 флага зоны C в `_asap4_flags_off_by_default` (старые тесты — бит-в-бит прежние контуры; ~181–186) |
| `tests/test_summary_coverage_asap31.py` | **Фронтир по spec C.1 (задокументировано):** 3 пина «369 сообщений → ровно 1 chunk» сняты (`count >= 1`/`chunk_count == calls` — суть тестов: нет искусственного cap, coverage 100%, пересчёт после смены модели — не тронуты); OFF-тесты ASAP-3.1 (`SUMMARY_COVERAGE_CHUNKING_ENABLED=false`, `AUTO_BUDGET_RESOLVER_ENABLED=false`) НЕ менялись и зелёные — capacity planning уважает чужой OFF-конверт |
| `tests/test_summary_wave_c_asap4.py` (новый, 32 теста) | см. C4 |

## C3. Kill-switches зоны C (spec §8.2)

| Флаг | Default | OFF-паритет (тест) |
|---|---|---|
| `SUMMARY_L1_CAPACITY_GUARD_ENABLED` | ON | too_many_facts → invalid → fallback package (тест `test_guard_off_too_many_facts_invalid_parity`: 45 фактов → invalid, 1 вызов, без починки) |
| `SUMMARY_QUOTE_REPAIR_ENABLED` | ON | прежняя validator-матрица §50.20 бит-в-бит (тест `test_off_parity_50_20_matrix`: named+found → reject `quote_attribution`; unverified+named → reject) |
| `SUMMARY_LEGACY_FULL_WINDOW_ENABLED` | ON | тихий XML hard stop бит-в-бит (тест `test_off_parity_xml_hard_stop`: 688 → ≤100 сообщений в `<chat_history>`, без coverage) |

Конверт ASAP-3.1: capacity planning действует только при
`SUMMARY_COVERAGE_CHUNKING_ENABLED` ON и не-`legacy_static` бюджете
(спецификация §0.2 — OFF чужого флага = бит-в-бит; прод-дефолты ON →
планирование активно; `test_off_chunking_keeps_legacy_truncation`/
`test_off_auto_budget_keeps_legacy_static` зелёные БЕЗ правок).

## C4. Покрытие acceptance-фикстур (§50.33–§50.37, §51–§58, §74–§75)

* **T-4422 / Q17 / golden J** — `test_q17_planning_gives_more_than_one_chunk_for_688` (688 → ≥2 chunk по §52); `test_q17_688_messages_sharded_no_invalid` (688 → 3 чанка, 3 вызова, merged ok, **facts=688 — ничего не потеряно**, coverage 100%); `test_golden_j_wide_topic_31_facts_not_invalid` (45 фактов одной темы → repair → ok, подсмысл ≤30); юниты repair (дедуп/подсмыслы/бюджет/не-мутация); `test_cross_chunk_merge_preserves_reply_evidence` (§50.33/§50.34: merge по пересечению id, union evidence, уникальные факты живы); `test_failsoft_unknown_id_still_invalid` (§50.35 не тронут).
* **T-4423 / Q18 / §75** — фикс §50.20 (`test_found_and_proven_speaker_valid_fix_50_20`: named+found+спикер доказан → valid); матрица repair: mismatch/unresolved/ambiguous/not_found+named — каждый с точным reason code и `quote_attribution_repaired`; §75 интеграция (`test_s75_run_l2_repairs_not_legacy`: одна выдуманная цитата в живой статье → usable-документ, НЕ invalid → Legacy не запускается; доказанная цитата с атрибуцией сохранена — §54); R17 (`test_metrics_safe_no_quote_text`: текст цитаты не в метриках); словарь mca_events единый.
* **T-4424 / §74** — `test_q74_688_messages_no_silent_307` (688, капы 100/5000 → full-window пакет, considered=688, coverage=100%, `LEGACY_FULL_WINDOW`, БЕЗ degraded); `test_small_window_flat_xml_bit_identical`; `test_semantic_package_reuse_from_hybrid` (Level-3 получает ТОТ ЖЕ пакет, mode=semantic_package); `test_degraded_coverage_visible` (13/30 → WARN+событие+ctx, ≈43.33%).
* **T-4425** — `test_max_summary_parts_not_input_cap` (§58-guard: max_parts 1 vs 4 → considered/coverage/контент байт-идентичны); `test_prefilter_not_restored` (R4-D-038: pack без выбросов, considered==total); coverage-юниты `compute_package_coverage`; ctx-поля run state (SUMMARY_COMPLETE `coverage=`).
* **T-4426** — OFF-паритеты всех трёх флагов зоны C (см. C3) + §74-сценарий + mca-словарь.

## C5. Прогоны (финальные счётчики)

| Прогон | Результат |
|---|---|
| Полный pytest (`tests --timeout=120 -q`) | **10628 passed / 2 failed** — те же 2 known pre-existing round1026 forbidden_paths (= Wave B 10596 + 32 новых) |
| Новый файл | 32/32 (`tests/test_summary_wave_c_asap4.py`, маркер asap4) |
| Соседи summary (14 файлов) | 396 passed (clusterizer/l2_writer/fact_package/l1_retry/coverage_asap31/reduction/incident/generator/l2_integration/acceptance/failsoft/prefilter/auto_budget/l2_budget) |
| Соседи cross-wave | 340 passed (cover_wave_b, embedding_asap4, summary_xml, пины mca-01/05/22, logging_runid, test_run, two_call, reduction) |
| F8 `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488 == REGISTRY…`, **EXIT=0** (флаги env-only, в каталог не входят) |
| EOL/BOM | см. C1; `git diff --check` по LF-файлам волны C — EXIT=0 |
| R17 | новые логи — только числа/коды/id (`L1_CAPACITY_*`, `LEGACY_*`, quotes-счётчики); тексты цитат/сообщений в логи/метрики не попадают (тест `test_metrics_safe_no_quote_text`); содержание окна идёт только в user-контент LLM |

Воспроизведение: `.venv\Scripts\python.exe -m pytest tests --timeout=120 -q`.

## C6. Контрактные решения волны C (для Reviewer)

1. **Планировщик в конверте lossless chunking**: planning шардит только при `_allow_chunking` + guard ON + `SUMMARY_COVERAGE_CHUNKING_ENABLED` ON + не-`legacy_static` — чужие OFF-флаги остаются бит-в-бит (spec §0.2). Прод-кейс Q17 покрыт (auto-режим).
2. **Фронтир asap31-пинов**: «369 → ровно 1 chunk» снят в 3 тестах — прямое следствие spec C.1 (§51/§52: плотное окно ОБЯЗАНО нарезаться по кардинальности; 369 сообщений ≈ 31 expected facts > капа 30). Суть тестов (нет искусственного cap, coverage 100%, пересчёт при смене модели) сохранена и зелёная.
3. **Эвристика плотности** (1 факт / 12 сообщений + 0.5×reply-фактор) — planning-оценка, не контракт: занижение → просто меньше превентивных чанков, переполнение ловит post-model repair; оба developer-bound'а env-регулируются.
4. **Quote repair — extension ADR-1028-6 D3**: статусы лестницы импортированы из `quote_resolver` (один словарь понятий); L2-резолв против FactPackage — инлайновый (синхронный, без БД) — задокументирован в докстринге модуля как extension-случай, который лестница не покрывает; Wave D (T-4430/T-4431) переиспользует `process_paragraph_quotes`.
5. **Доказанный спикер → direct quote публикуется** (§50.20-после/§54): found+proven → текст не меняется; это ослаблением НЕ является (прямая речь подтверждена текстом и автором фрагмента).
6. **Legacy full-window coverage = considered-based** (chronology ∪ fragments ∪ evidence ∪ unassigned): «100% considered ≠ копия 100% сообщений» (R4-D-016/017-семантика); уточнение coverage-map (per-topic representation) — Wave D (T-4433), каркас run-state готов.
7. **`_compose_user_content`**: full-window пакет заменяет только секцию `<chat_history>`; RAG/graph/memory-секции и system-канон R11 не тронуты; `MAX_SUMMARY_PARTS` читается только как output send-cap (§58-guard-тест).

## C7. Что НЕ сделано / остатки (честно)

1. **Golden L (major topic omission → Revision)** — Wave D (T-4437, семантический Reviewer): на детерминированном слое зоны C этот сценарий не выражается; golden J/K закрыты здесь (K = §74-тест).
2. **Разведение семантики `FACT_PACKAGE_TRUNCATED` (§50.31–32) и coverage-map метаданные пакета** — Wave D (T-4433, «при касании»); в T-4421…T-4426 не входят (проверено по матрице spec §6).
3. **UI-витрина coverage (§61.6 «health = publication_status × source_coverage»)** — Wave E (T-4443); здесь подготовлен только run-state каркас (`ctx.source_coverage` + `coverage=` в SUMMARY_COMPLETE).
4. **Мёртвая (defensive) ветка fail-closed quote-repair**: de-quote не даёт пустого абзаца, поэтому путь «repair невозможен» недостижим на валидных строках — оставлен как защита (§54), прямого теста нет.
5. Live-acceptance §79 (окно 600–700+ на проде) — PENDING OWNER (платные вызовы), T-4449.
6. Два known pre-existing failure (round1026 forbidden_paths) — вне эпика.

## C8. Риски/наблюдения для Reviewer

* Эвристика планирования занижает кардинальность чатов с очень короткими репликами — компенсируется post-model repair (протестировано: 230 фактов/чанк чинятся детерминированно).
* `repartition_by_count` границы — по счётчику сообщений (не по reply-группам): reply-цепочка МОЖЕТ быть разрезана границей чанка; overlap=1 + merge по stable ID покрывают связность тем (§122/§124-механика ASAP-3.1, тест merge); формальный контракт reply-chain preservation — Wave D (T-4434).
* `_build_legacy_full_window_context` строит fallback-пакет синхронно в цикле события (0 LLM, чистый CPU/память на окне) — на окнах ≫1000 сообщений возможно заметное время сериализации; наблюдаемо через `LEGACY_FULL_WINDOW`.
* asap31-файл менялся ТОЛЬКО в 3 assertion-пинах (diff ±19 строк) — остальное тело не тронуто.

---


# Wave D — Hybrid L2 Writer/Reviewer bounded revision (T-4428…T-4437, 02.10.2026)

> **Builder Wave D** (штатное продолжение сессии после Wave C). Коммитов нет,
> деплоя нет. Base: HEAD `f04564b`, то же рабочее дерево (дифы волн A/B/C не
> тронуты; касания только по контрактам зоны D: `settings.py`/`mca_events.py`/
> `conftest.py` — аддитивные строки). Спека §4 + ADR-1028-7 D3/D4/D5 —
> Accepted; SUPERSEDE-процедура §50.65 выполнена Architect'ом (T-4427),
> конфликтов с контрактами не найдено.

## D1. Базовая линия и состояние дерева

* Baseline: HEAD `f04564b` (не менялся). Чужие changes/untracked сохранены.
* После Wave D дополнительно: modified — `services/summary_prompts.py`,
  `services/prompt_migrations.py`, `services/summary_l2_writer.py`,
  `services/summary_fact_package.py`, `services/summary_l1_clusterizer.py`,
  `services/summary_legacy_fullwindow.py`, `services/summary_run_log.py`,
  `services/summary_generator.py`, `services/mca_events.py`,
  `config/settings.py`, `tests/conftest.py`,
  `tests/test_summary_l2_writer.py`, `tests/test_prompt_migrations.py`,
  `tests/test_summary_fact_package.py`,
  `tests/test_summary_asap21_prompt_migrations.py`,
  `plans/docs/canon/architecture.md` + НОВЫЕ:
  `services/summary_l2_review.py` (~890 строк),
  `tests/test_summary_wave_d_asap4.py` (69 тестов).
* EOL/BOM (по конвенции `git ls-files --eol`): новые файлы — LF без BOM
  (байт-проверка); `config/settings.py` (i/mixed) и `tests/conftest.py`
  (i/crlf) — правки в конвенции индекса, `git diff --check` даёт только
  известный cr-at-eol артефакт на CRLF-строках (тот же, что в волнах A–C);
  LF-файлы — 0 находок. **Уточнение Rework-1 (L-ASAP4-D4):** во всех файлах
  волны D НОВОГО BOM нет; `tests/test_summary_l2_writer.py` содержит
  pre-existing BOM из HEAD (проверено байтами: `git show HEAD:` файла
  начинается с того же `\xef\xbb\xbf` — волной D не внесён).

## D2. Изменённые файлы (якоря file:line)

| Файл | Что сделано (Wave D) |
|---|---|
| `services/summary_l2_review.py` (новый) | Kill-switches (94–121); budget constants (124–129); 15 finding codes §50.12 (132–166); ReviewFinding/ReviewVerdict (171–216); `resolve_l2_reviewer_slot` — наследует L2, hot-override (222–248); `parse_review_verdict` — валидация findings (§50.11: refs ⊆ id-space, invalid отбрасываются, needs_fixes без валидных → approved) (254–316); `build_review_content`/`build_revision_content` (§50.22 preserve) (322–388); `apply_revision_patch` (replace + append для omitted topic; полная deterministic-ревалидация) / `apply_full_revision` (391–461); метрики §50.58 + `_log_review` (R17) (465–505); `_stage_event`/`_record` append-only (§50.54) (508–536); `run_l2_with_review` — bounded loop (§50.24/§50.25, бюджет ≤6, progress criterion, escape-hatch, review_degraded §50.29) (557–812) |
| `services/summary_prompts.py` | Канон L2 v1.2 prose-first R1029 (§50.3–§50.6/§50.21/§50.40–§50.45/§50.47; запрет цитат удалён; base 530, слепок 602); `SUMMARY_L2_REVIEWER_SYSTEM_PROMPT` (620) + `SUMMARY_L2_REVISER_SYSTEM_PROMPT` (~660) |
| `services/prompt_migrations.py` | Ступень R1028_ASAP4→R1029 в `PROMPT_MIGRATIONS`; ROLLBACK на `PREV_*_R1028_ASAP4` (189–200, 253–262) |
| `services/summary_l2_writer.py` | `PARAGRAPH_FIELDS += evidence_message_ids` (аддитивно, schema_version 1); `REASON_INVALID_EVIDENCE`; `package_message_id_space` (382); `build_participant_roster` (417); `build_l2_input` — participants (479) + kind/forward_source; `_validate` — детерминированный чек evidence refs (818+) + метрики |
| `services/summary_fact_package.py` | `_relation_kind` (msg/reply/forward/quote — Q35); фрагменты несут kind + forward_source; `package_grade=semantic` + reduction-merge счётчики в service (301–321, 341–362, 646–652, 925–933); fallback-пакет `package_grade=degraded` (1160–1166) |
| `services/summary_l1_clusterizer.py` | `build_l1_payload` — аддитивные is_forward/forward_source (только при наличии в row; синтетика бит-в-бит) (400–421) |
| `services/summary_legacy_fullwindow.py` | `compute_package_coverage` + coverage map §50.32 (major_topics_total/represented, unique_events_total/represented; total = represented + reduction-merged) (95–172) |
| `services/summary_run_log.py` | RunContext += `pipeline_health` / `stage_events` / `package_grade`; `fail()` health-семантика; SUMMARY_COMPLETE += `health=`/`package_grade=` (аддитивно) (160–185, 258–275, 195–200) |
| `services/summary_generator.py` | `_l2_review_enabled_safe`/`_l2_review_extra_calls` (150–176); L2-стадия: review-петля при ON / single-call при OFF (бит-в-бит); L2-fail → `health=degraded` ДО Legacy; review_degraded → health=degraded; paged L2 → видимый skip (`L2_REVIEW_SKIPPED` + degraded); package_grade → ctx; `_legacy_fallback` — Q36: публикация не стирает health (1180–1262, 995–1020) |
| `services/mca_events.py` | REASON_CODES += `l2_review_rejected` / `l2_review_unusable` / `review_degraded` (единый словарь) |
| `config/settings.py` | `SUMMARY_L2_REVIEW_ENABLED`, `SUMMARY_REVISION_PATCH_ENABLED` (env-only, default ON; ClassVar → dataclass-fields 426 не меняются; F8 EXIT=0) |
| `tests/conftest.py` | Волна D: D-флаги OFF для ВСЕХ не-asap4 тестов ВКЛЮЧАЯ asap3/31/32 (их каркас мокает run_l2/LLM — review-петля с мок-каналом давала бы ложные degraded-пути); A/B/C-флаги — как было |
| `plans/docs/canon/architecture.md` | Канон L2 v1.2 байт-в-байт (старый помечен superseded); новые секции Reviewer/Reviser промптов (байт-тест волны D) |
| Пин-тесты (фронтир) | `test_summary_l2_writer.py` (TestCanon: prose-first, миграция, ROLLBACK); `test_prompt_migrations.py` (rollback-цель ASAP4); `test_summary_fact_package.py` (service+grade, kind в фрагментах, +тест forward); `test_summary_asap21_prompt_migrations.py` (rollback-цель, запрет цитат снят) |

## D3. Контрактные решения волны D (для Reviewer)

1. **Evidence refs — аддитивно, без новой схемы пакета** (§50.7 Builder-проверка
   выполнена): refs = существующие stable message-id; id-space = chronology ∪
   fragments ∪ facts.evidence ∪ unassigned (service/budget исключены).
   `>=1 ref на абзац` — НЕ жёсткий reject (иначе все §99-v1.1-документы
   становились бы invalid → противоречит аддитивности ASAP-2.1): отсутствие
   refs — счётчик `paragraphs_without_evidence` + deterministic finding
   Reviewer'у (unsupported_claim по месту); invented refs — fail-closed
   `invalid_evidence` (это жёстко, по spec).
2. **Roster — производное пакета, не новая схема** (`build_participant_roster`
   из фрагментов: первое display_name = канон, остальные = aliases; без
   author_id — не пополняет). Writer получает roster в `build_l2_input`;
   Reviewer — тот же helper.
3. **needs_fixes без единой валидной находки → approved** (§50.11 «invalid
   findings отбрасываются»; нет основания — нет ревизии; unknown >
   hallucinated).
4. **Full-doc escape-hatch (ADR D5(б) «дважды невалидный патч») при бюджете
   ×2**: первая невалидная попытка патча активирует full-doc на СЛЕДУЮЩЕЙ
   (последней) ревизии — буквальное «дважды в patch-режиме» съело бы весь
   бюджет на заведомо сломанный режим. Потолок ≤2 ревизий / ≤6 вызовов не
   меняется. Интерпретация задокументирована в докстринге модуля и пин-тесте.
5. **Progress criterion §50.25 vs сгоревшая ревизия**: patch, не прошедший
   deterministic-валидацию, — НЕ попытка исправления (документ не менялся);
   после неё допускается единственная full-doc ретриа (без неё ADR D5(б)
   был бы недостижим). Реальные безпрогрессные ревизии → немедленный safe
   fallback (тест: 4 вызова, не 6).
6. **Append-расширение patch-контракта**: `index == len(paragraphs)` дописывает
   один абзац (natural fix для major_topic_omitted в patch-режиме); остальные
   абзацы по-прежнему байт-в-байт (§50.23 дух «замены минимального участка»).
7. **review_degraded (§50.29/ADR D3.5)**: reviewer outage (LLM-ошибка/
   невалидный вердикт/slot-fail) на deterministic-валидном документе →
   publish degraded (`l2_review_degraded=1`, WARN `L2_REVIEW_DEGRADED`,
   `health=degraded`, stage-event degraded — не success). «Недоказуемый
   factual support → Legacy» покрывает deterministic-слой (structural/ID/
   quote-lookup/length) — в degraded уходят только его прошедшие.
8. **Paged L2 (ASAP-3.2, k≥2 страниц) — semantic review НЕ применяется**:
   бюджет ADR D3.3 фиксирован для writer=1; k+review превысил бы ≤6 при k≥2.
   Bypass НЕ тихий: `L2_REVIEW_SKIPPED reason=paged_l2` + `health=degraded`.
   (Пардон-окно: paged — редкий деградационный путь после Wave C-редукции.)
9. **Q36 fix**: `publication_status`/`pipeline_health`/`stage_events` —
   раздельные оси; Legacy-успех после L2-fail = publish ok + health degraded;
   "ok" для health выставляется ровно один раз и только под guard
   (пин-тест исходника `_run_hybrid_l2`).
10. **D-флаги в conftest — OFF для всех не-asap4 тестов, включая asap3x**:
    их каркасы мокают `run_l2`/LLM-канал; review-петля с мок-каналом порождала
    бы ложные degraded-пути (поймано тестом инцидента 1089). Прод-дефолт ON
    не меняется; изоляция — тот же паттерн, что волны A/B/C.

## D4. Kill-switches зоны D (spec §8.2)

| Флаг | Default | OFF-паритет (тест) |
|---|---|---|
| `SUMMARY_L2_REVIEW_ENABLED` | ON | single-call run_l2, Reviewer/Revision не вызываются, документ бит-в-бит (test_review_off_single_call_bit_identical; генератор не импортирует review-модуль) |
| `SUMMARY_REVISION_PATCH_ENABLED` | ON | revision ПОЛНЫМ документом (master ON; bounded, не Legacy) (test_patch_off_full_doc_revision_bounded) |

Промпт-rollback: ROLLBACK_MIGRATIONS L2 → `PREV_SUMMARY_L2_WRITER_R1028_ASAP4`
(старый канон с запретом цитат; идемпотентен; кастом не трогается) —
rollback-паритет с флагом.

## D5. Промпт-миграция (старый/новый)

* **Старый (superseded, ADR-1028-7 D4)**: `Не выдумывай цитаты. Прямые цитаты
  не приводи: пересказывай реплики своими словами.` + формат без
  evidence_message_ids — сохранён байт-в-байт как
  `PREV_SUMMARY_L2_WRITER_R1028_ASAP4` (пин-тест: строка запрета есть в
  PREV и отсутствует в активном каноне; PREV не является new-каноном ни
  одной ступени миграции — «двух противоречащих канонов нет»).
* **Новый (активный, R1029)**: prose-first (косвенная речь default,
  narrative continuity), цитаты разрешены как редкий выразительный приём с
  доказанным source+speaker, «видимая действительность» — первая истина,
  ФАКТЫ И МОДАЛЬНОСТЬ (§50.6/§50.41/§50.42/§50.45), ЭВИДЕНЦИЯ
  (evidence_message_ids, §50.7), имена только из пакета (§50.8), числа
  high-risk (§50.14), forward/reply/quote — раздельные отношения
  (§50.9/§50.40), финал — участник пакета (§50.47). Эталон —
  `plans/docs/canon/architecture.md:623-724` (байт-тест), Reviewer/Reviser —
  там же (байт-тест волны D).
* Миграция PG: ступень `PREV_*_R1028_ASAP4 → R1029` (прод 2.58.44 попадает в
  неё при старте; идемпотентно; кастом не перезаписывается); ROLLBACK —
  обратная ступень (runbook @DevOps при cold revert).

## D6. Прогоны (финальные счётчики)

| Прогон | Результат |
|---|---|
| Полный pytest (`tests --timeout=120 -q`, финал) | **10698 passed / 2 failed** — те же 2 known pre-existing round1026 forbidden_paths (= Wave C 10628 + 70 новых) |
| Новый файл | 69/69 (`tests/test_summary_wave_d_asap4.py`, маркер asap4) |
| Соседи summary (l2_writer, prompt_migrations, prompts, fact_package, wave_c, asap21_emphasis, asap21_prompt_migrations, article_formatter, publish_integration, l1_clusterizer, generator, l2_integration, coverage_asap31, acceptance, incident_1089, failsoft) | все зелёные (529+113+20 батчами) |
| F8 `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488 == REGISTRY…`, **EXIT=0** (D-флаги env-only ClassVar) |
| EOL/BOM | см. D1 (включая уточнение Rework-1 про pre-existing BOM `test_summary_l2_writer.py` из HEAD); `git diff --check` — только известный cr-at-eol артефакт CRLF-конвенции (не волна D); новые файлы — LF, нового BOM нет |
| R17 | `L2_REVIEW`/`L2_REVIEW_DEGRADED` — только числа/коды/id (тест `test_no_raw_content_in_review_logs`); findings/prompt-тексты в логи не попадают; секретов в диффе нет (regex-скан 0) |

Воспроизведение: `.venv\Scripts\python.exe -m pytest tests --timeout=120 -q`.

## D7. Что НЕ сделано / остатки (честно)

1. **Агрегаты 24h/7d по §50.58/§50.60** (First-pass approval %, top findings)
   — Wave E (T-4441, R4-D-060): здесь per-run метрики в L2Result/логе —
   источник для агрегатов готов, второй «аналитики с собственной истиной»
   нет (spec §5 E.1).
2. **§50.50 «Читать дальше» / §50.51 idempotency** — существующие контуры
   (FORMAT rich_cut, delivery-retry) не менялись волной D; отдельных новых
   тестов не добавлялось (вне семантики review-петли; каркас покрыт
   тестами Wave B/C). Для Reviewer: пункт принят как REUSE, не новая работа.
3. **Semantic review на paged L2** — сознательно не применяется (D3.8);
   если Reviewer сочтёт блокером — нужно ARCH-решение по бюджету k+review.
4. **Golden I (parallel topics) / K (600–700+)** — I покрыт правилом
   timeline_inconsistency в промпте Reviewer (§50.15) без отдельного
   скриптового golden (LLM-поведение не тестируется в unit-контуре);
   K = §74-тест Wave C (coverage 100% на 688) — ссылка, не дубль.
5. **Browser-verification** — для волны D не применимо (backend-семантика,
   UI-витрины — Wave E T-4442/T-4446).
6. Два known pre-existing failure (round1026 forbidden_paths) — вне эпика,
   воспроизводились до волны D.

## D8. Риски/наблюдения для Reviewer

* **§50.62 prose-quality / §50.64 no-false-quality** — не закрывались Builder'ом
  (это live-приёмка Reviewer'а, T-4438): код/тесты дают детерминированный
  каркас (метрики, golden-сценарии на вердиктах), реальное качество прозы
  нового промпта проверяется на проде (пинд «golden M» — это behavioral
  контракт на вердиктах, не оценка стиля).
* **Reviewer — второй LLM-вызов на каждом саммари** (+1 latency/стоимость на
  happy-path; бюджет ≤6 зафиксирован). Отключение — env
  `SUMMARY_L2_REVIEW_ENABLED=false` (бит-в-бит).
* `l2_review_findings_total` считается по ПЕРВОЙ needs_fixes-ревизии;
  `l2_revision_new_findings` — дифф кодов последующих ревизий против первой
  (считается до обновления seen_codes — тест на 0-улучшение).
* Пины фронтира обновлены: service-секция пакета (+package_grade), фрагменты
  (+kind), канон-тесты L2 (запрет цитат снят), ROLLBACK-цель L2, Settings
  dataclass-fields (не изменились — ClassVar). Все — с комментариями причин.

## D9. Rework round 1 (02.10.2026, по findings независимого ревью T-4438 — review.md «Wave D gate»)

Base rework'а: то же рабочее дерево волн A–D (HEAD `f04564b`, без коммитов).
Затронуто ровно 5 файлов кода/тестов + plans-доки: `services/summary_l2_review.py`,
`tests/test_summary_wave_d_asap4.py`, `services/summary_prompts.py`,
`plans/docs/canon/architecture.md`, `services/summary_generator.py`
(косметика), этот evidence.md, tasks.md. Остальной диф волн A–D не тронут.

### D9.1 [M-ASAP4-D1] находки БЕЗ evidence_refs — ЗАКРЫТО

* **Было (воспроизведено до фикса):** `parse_review_verdict` отбрасывал
  находки с выдуманными refs, но пропускал находки с пустым/отсутствующим
  `evidence_refs` (`refs=[]` → finding сохранялся): репро — needs_fixes с
  1 находкой, `dropped=0` → споровая ревизия → «нет прогресса» → хорошая
  first-pass статья в Legacy (нарушение §50.11).
* **Стало** (`services/summary_l2_review.py:288-315`): `if invalid_ref or
  not refs:` — пустой список и отсутствующее поле отбрасываются так же, как
  выдуманный ID; такая находка не порождает ревизию (needs_fixes без
  валидных находок → approved, механика была и осталась). Observability:
  R17-safe лог `L2_REVIEW_FINDING_DROPPED | code=<§50.12-код> |
  cause=invalid_ref|missing_refs` (только enum-коды, без текстов/инструкций);
  докстринг обновлён. Диф вне функции — только докстринг.
* **Негативные тесты** (`tests/test_summary_wave_d_asap4.py`):
  `test_finding_without_refs_dropped` (юнит: пустой список + отсутствующее
  поле отброшены, валидная находка рядом жива, единственная без-refs →
  approved) и `test_finding_without_refs_no_revision_first_pass_published`
  (интеграция — обязательный сценарий: reviewer возвращает blocking-находку
  без refs → находка отброшена, `revision.calls == 0` (споровой ревизии НЕ
  было), документ байт-в-байт черновика, `l2_first_pass_approved=1`,
  `l2_legacy_after_review=0`, `l2_review_dropped_findings=1` — first-pass
  APPROVED статья публикуется).

### D9.2 Не-блокеры ревью — исправлены

* **L-ASAP4-D2 (пин промпта):** в активный `SUMMARY_L2_REVIEWER_SYSTEM_PROMPT`
  добавлен пин: «Находки уровня minor (неблокирующие неточности) сами по
  себе - не основание для needs_fixes: нет blocking-находок - верди
  approved; minor-замечания не переводят статью в Legacy»
  (`services/summary_prompts.py:645`); эталон
  `plans/docs/canon/architecture.md` синхронизирован байт-в-байт (байт-тест
  волны D зелёный); пин-ассерты в `test_reviewer_prompt_semantics`.
  Безопасное направление: сужает повод для needs_fixes, не ослабляет
  факт-брак (blocking-находки и коды не тронуты).
* **L-ASAP4-D3 (косметика):** `services/summary_generator.py:743` —
  склеенная строка `search_long_term(...)` приведена к чистому виду
  (переформат вызова, поведение идентично — neighbours-прогон зелёный).
* **L-ASAP4-D4 (evidence-честность):** §D1/D6 — «BOM отсутствует во всех
  16 файлах» заменено точной формулировкой: нового BOM в файлах волны D нет;
  `tests/test_summary_l2_writer.py` — pre-existing BOM из HEAD (волной не
  внесён; проверено байтами `git show HEAD:` независимо Builder'ом).
* L-ASAP4-D5/L-ASAP4-D6 — вне объёма реворка (минорные/на live-приёмку,
  как в review.md).

### D9.3 Прогоны Rework round 1

| Прогон | Результат |
|---|---|
| Файл волны D | **71/71** (`tests/test_summary_wave_d_asap4.py` = 69 + 2 новых) |
| Целевые соседи summary_* (wave_d, l2_writer, prompt_migrations, asap21_prompt_migrations, fact_package, wave_c, generator, l2_integration, coverage_asap31) | **350 passed** |
| F8 `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488`, **EXIT=0** |
| EOL/BOM | все 5 затронутых файлов — LF, BOM нет (байт-проверка); `git diff --check` — EXIT=0 |
| Полный pytest | см. §D9.4 |

### D9.4 Diff-якоря Rework round 1 (для детерминированного манифеста Reviewer)

* `services/summary_l2_review.py:254-265` — докстринг
  `parse_review_verdict` (правило непустых refs); `:288-315` — фикс
  (`invalid_ref or not refs` + лог `L2_REVIEW_FINDING_DROPPED`).
* `tests/test_summary_wave_d_asap4.py` — `test_finding_without_refs_dropped`
  (блок `TestReviewVerdictParsing`), 
  `test_finding_without_refs_no_revision_first_pass_published` (блок
  `TestBoundedRevisionLoop`, после golden M), пин-ассерты в
  `test_reviewer_prompt_semantics`.
* `services/summary_prompts.py:645` — строка пина minor-находок в
  `SUMMARY_L2_REVIEWER_SYSTEM_PROMPT` (константа изменена только этой
  строкой); `plans/docs/canon/architecture.md` — та же строка байт-в-байт +
  уточнение преамбулы секции Reviewer.
* `services/summary_generator.py:743-748` — переформат вызова
  `search_long_term` (L-ASAP4-D3, поведение идентично).
* Binding-следствие: WTH ревью T-4438 `a89ee325…` инвалидируется правками
  (ожидаемо — фикс и есть изменение кода); повторный gate Reviewer'а — по
  затронутым проверкам (TestReviewVerdictParsing + golden'ы + репро
  скриптом), полный pytest прогнан Builder'ом (счётчик ниже).

### D9.5 Осталось непроверенным/за пределами реворка

* Live-acceptance §50.62/§50.64 (реальные статьи) и §79 — PENDING OWNER,
  как в §D7/D8; поведенческая доля без-refs находок реальной модели —
  live-метрики (Wave E).
* L-ASAP4-D5 (`_deterministic_findings` не пересчитываются после ревизии)
  и L-ASAP4-D6 (golden I/B без скриптовых golden'ов) — не в объёме, мнение
  Reviewer не изменилось.

---

## E1. Базовая линия и состояние дерева (Wave E, 02.10.2026)

* Baseline: HEAD `f04564b` (не менялся, коммитов НЕТ по инструкции).
  Дерево: всё волны A–D на месте + Wave E; посторонних откатов нет.
  Сессия Builder одна, без наследования частичного состояния (fallback/
  recovery не потребовались).
* Изменённые Wave E файлы — modified: `config/settings.py`,
  `services/mca_events.py`, `services/summary_generator.py`,
  `services/execution_graph_source.py`, `services/embedding_control_plane.py`,
  `web/api/analytics.py`, `web/index.html`, `web/app.js`,
  `web/static/app.css`, `tests/conftest.py`,
  `tests/test_webapp_js_unit.py`,
  `tests/test_webapp_f6_round1025.py` (инвариант §116: 6→8 read-only
  маршрутов, санкция spec §5 E.2),
  `tests/test_summary_publish_integration_round1026.py` (гейт набора
  роутов S6: санкционированный список + Wave E) + НОВЫЕ:
  `services/pipeline_events.py`, `services/pipeline_analytics.py`,
  `tests/test_pipeline_analytics_asap4.py` (64 теста),
  `tests/js/round1030_pipeline_inspector_test.js`.
* EOL/BOM: новые файлы — LF без BOM, файл заканчивается `\n` (байт-проверка);
  CRLF-файлы (`tests/conftest.py`, `tests/test_webapp_js_unit.py`,
  `tests/test_summary_publish_integration_round1026.py`) — правки в их
  родной конвенции; `git diff --check` — только известный cr-at-eol артефакт
  CRLF-файлов (тот же, что в волнах A–D; LF-файлы волны E — 0 находок).

## E2. Изменённые файлы (якоря file:line)

| Файл | Что сделано (Wave E) |
|---|---|
| `services/pipeline_events.py` (новый, ~264 строки) | Единая точка эмиссии стадий текстовой ветки поверх mca-17a (`mca_trace.emit_stage` → durable `mca_events`; НЕТ второго store — §61.11): имена событий SUMMARY_RUN_START/SOURCE_WINDOW/L1_STAGE/L2_STAGE/L2_REVIEW/LEGACY_FALLBACK/RUN_DONE (28–33); kill-switch `events_enabled()` (49); `map_reason` — маппинг LLM-классов/контрактных причин в whitelist REASON_CODES (58–72); `summary_start` (108) / `source_window` (117) / `l1_stage` (125) / `l2_stage` (140) / `l2_review` — лестница ok/repaired/failed (151) / `legacy_fallback` (187) / `summary_done` (200) / `summary_done_from_ctx` — R17-срез coverage/publication/fallback из RunContext (218); всё fail-open |
| `services/pipeline_analytics.py` (новый, ~936 строк) | Адаптер §61.11: узлы/ветки (40–62), состояния ✓/⚠/✕/○/… + repair≠fallback≠failure §61.7 (64–90), health-бейджи текстом §61.13 (93–107), COVERAGE_FULL_EPSILON (71); RU-переводы причин §61.3 + волны A–D (74–135), пояснения стадий 1–3 строки (138–152); `reason_ru` (204); `build_run_view` — карта run из events+snapshot, раздельные ветки ТЕКСТ/ОБЛОЖКА §61.8, running-хвост ○ «ожидает» §61.15 (252); `health_of` — publication × coverage §61.6 (517); `run_list_entry` + styled-флаг (560); `aggregate_from_rows` — per-stage success/repaired/fallback/failed %, median/p95, top-3 причин, итоги runs из ТЕХ ЖЕ событий §61.4/§61.5 (664); `collect_run`/`collect_latest`/`collect_runs_list` (+`_styled_run_ids` 885)/`collect_aggregate` — данные ТОЛЬКО из mca_events + in-memory снапшотов, human-логи не читаются §61.12 (808–920) |
| `config/settings.py` | `SUMMARY_PIPELINE_EVENTS_ENABLED` (env-only ClassVar, default ON; 879–880; Δ каталога = 0, F8 EXIT=0) |
| `services/mca_events.py` | REASON_CODES += `too_many_facts/too_many_threads/too_many_facts_total/rate_limit/timeout` (179–181); `_ID_FIELDS` += `style_id`, `_NUMERIC_FIELDS` += `style_revision` (аддитивно для durable drill-down «selected style» §61.9; 194, 202) |
| `services/summary_generator.py` | 7 fail-open точек эмиссии: SUMMARY_RUN_START (490–495), SOURCE_WINDOW (505–512), LEGACY_FALLBACK при delivered (1028–1037 — до сброса ctx.stage, точка перехода честная), L1_STAGE (1074–1084), L2_REVIEW при review>0 (1256–1263), L2_STAGE (1264–1276), SUMMARY_RUN_DONE в `finally` (578–586) |
| `services/execution_graph_source.py` | `_SNAPSHOT_FIELDS` += source_total/considered/coverage, pipeline_health, package_grade, fallback, model, provider, reason, stage_events (274–292); `_project_stage_events` — bounded ≤24, только R17-safe ключи (294–312); `record_run_from_context` переносит новые поля (337–360) |
| `web/api/analytics.py` | `GET /api/analytics/pipeline/inspector` (mode=latest/24h/7d, ?run_id= drill-down; один виджет/одни данные §61.4; kill-switch внутри адаптера: OFF → state-проекции) (416–469); `GET /api/analytics/pipeline/runs/{run_id}` (§61.9 drill-down) (471–489); оба `requires_global_admin` (401 unauth/403 не-глобал — тест), fail-open shape; import time (25) |
| `services/embedding_control_plane.py` | §62-карточка: `vector_memory_panel` entry += `processed`/`updated_at` из payload/updated_at task_jobs (structured state); `_safe_int` (1474–1480) |
| `web/index.html` | Карточка «Пайплайн саммари» (3064–3250): режимы Последний запуск/За 24 часа/7 дней (§61.4), health-бейдж текстом, coverage-карточка §61.6, вертикальный timeline текстовой ветки + ОТДЕЛЬНАЯ ветка «Обложка» (§61.8/§61.14), tap-поянения + RU-причины, «Итог: опубликовано…», developer `<details>` (§76), «Последние запуски» §61.10 с drill-down; карточка «Embeddings и векторная память» (3251–3305): provider/алиасы/группы/429/кулдаун/прогресс, только алиасы §63 |
| `web/app.js` | data: pipeline*/embeddings* (1693–1706); computed: pipelineRunView/Aggregate/Runs/NodesText/NodesCover/CoverageLine/PublicationLine/ShortId/Duration/embeddingsAliases (2961–3020); methods: loadPipelineInspector/setPipelineMode/openPipelineRun/clearPipelineRunSelection/togglePipelineNode/pipelineHealthBadge/fmtSec/pctLabel/start|stopPipelinePolling (15с, только latest)/loadEmbeddingsPanel (4584–4680); wiring: loadOversight (+2 вызова), setTab('oversight') polling start/stop (8026–8046) |
| `web/static/app.css` | `.pipe-timeline/.pipe-node/.pipe-node__icon--*/.pipe-edge/.pipe-grid` (≤3/2/1 колонки)/`.pipe-runs` (тач ≥44px) (2687–2782); цвета ДОПОЛНЯЮТ значок/текст (§61.2) |
| `tests/conftest.py` | `SUMMARY_PIPELINE_EVENTS_ENABLED` — OFF для всех не-asap4 тестов (бит-в-бит прежний контур; 191–194) |
| `tests/test_pipeline_analytics_asap4.py` (новый, 64 теста) | §61.16-сценарии A–D на модели (TestRunViewScenarios: A healthy 133, B L2→Legacy degraded, C style failure, **D coverage 44.6% → НЕ healthy** 197); repair≠fallback≠failure (TestRunViewStates); §61.3-переводы (TestReasonTranslations); агрегаты %/median/p95/top-3/totals (TestAggregates, coverage<100 → degraded в итогах); список runs (TestRunsList); эмиссия ON/OFF + R17-срез (TestEmission 456+); снапшот-проекция bounded/safe (TestSnapshotProjection); **guard §61.12 (T-4445)** — source-scan: модули виджета без open/read/glob/subprocess, данные из `FROM mca_events`, без импорта summary_run_log (TestGuardNoLogParsing 611); kill-switch OFF → честный пустой агрегат (TestKillSwitchAggregates 659); API 401/403/200-shape (TestPipelineApiRbac 704) |
| `tests/js/round1030_pipeline_inspector_test.js` (новый) | Реальная логика app.js + разметка index.html: (a)–(j) — см. шапку файла; ok-маркер PIPELINE-INSPECTOR-OK; обёртка `test_webapp_js_unit.py:362` |
| Гейты смежных эпиков | `tests/test_webapp_f6_round1025.py:109` — инвариант §116 read-only-поверхности 6→8 (Wave E — read-only, global-admin); `tests/test_summary_publish_integration_round1026.py:1317` — санкционированный набор роутов + pipeline/* |

## E3. Kill-switch / откаты (spec §8.2)

* `SUMMARY_PIPELINE_EVENTS_ENABLED` (env-only, default ON): OFF → эмиссия
  SUMMARY_* прекращается (бит-в-бит прежний контур — тест
  `test_kill_switch_off_is_noop`), Run Inspector работает из state-проекций
  (in-memory снапшоты + события COVER_* волны B — тест
  `test_off_inspector_uses_state_projection`); агрегаты за период честно
  «Данных за период нет», не нули-«здоровье»
  (`test_off_aggregate_honest_empty`).
* Rollback UI/раздела E: env OFF + рестарт; виджет остаётся (read-only),
  durable-данные additive, откат деплой-коммита — cold revert (spec §8.3).
* RBAC: оба новых эндпоинта — `requires_global_admin` (тесты 401/403).

## E4. Прогоны (финальные счётчики)

| Проверка | Результат |
|---|---|
| Полный pytest (`-q --timeout=120`) | **10763 passed / 2 failed** (оба pre-existing round1026 forbidden_paths: `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` — те же, что в волнах A–D) |
| `tests/test_pipeline_analytics_asap4.py` | 64 passed |
| JS-скрипты (`node tests/js/*.js`) | **53/53 OK** (52 прежних + round1030_pipeline_inspector) |
| `test_webapp_js_unit.py` (pytest-обёртки) | 37 passed (вкл. новый round1030) |
| F8 `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488 == REGISTRY…`, **EXIT=0** (флаг env-only ClassVar, Δ каталога = 0) |
| `py_compile` всех затронутых .py | EXIT=0 |
| EOL/BOM | новые файлы LF/noBOM/nl-end (байт-проверка); CRLF-файлы — родная конвенция, артефакт `git diff --check` как в A–D |
| Browser-прогон | **НЕ выполнялся** (по инструкции Orchestrator: live Browser Use + Playwright — T-4446 live/T-4449–T-4450) |

## E5. Контрактные решения волны E (для Reviewer)

1. **Эмиссия — через существующий transport mca-17a** (`mca_trace.emit_stage`
   → `mca_events.build_event` → durable `mca_events`): второго store/схемы
   нет (T-4439/§61.11 соблюдены). Имена SUMMARY_* — свободная ось
   event_name (прецедент DIRECT_* mca-22); НОВЫЕ reason codes — только в
   `mca_events.REASON_CODES` (+5: L1-контракты и mapped-классы LLM-ошибок).
2. **Coverage first-class (§61.6)**: health = publication × coverage в
   `health_of`; прогон с публикацией и coverage<99.95% — degraded, никогда
   не healthy (фикстура D §61.16 закреплена тестом). Health — только
   текстовые бейджи (Здоров/С деградацией/Не издано/Не завершён/
   Выполняется), без числового score (тест `test_health_labels_text_only_no_score`).
3. **Repair ≠ fallback ≠ failure (§61.7)** — отдельные состояния узла
   (repaired «исправлено, продолжено» / fallback «резервный контур» /
   failed «не выполнено») с разными RU-формулировками (тест).
4. **Данные только из structured state (§61.12, T-4445)**: durable
   `mca_events` + in-memory снапшоты `execution_graph_source`; guard-тест —
   source-scan модулей виджета (без open/read/glob/subprocess, наличие
   `FROM mca_events`, отсутствие импорта human-log-модуля).
5. **`style_id`/`style_revision` в mca_events ID/NUMERIC-полях** —
   аддитивное расширение whitelist (§61.9 «selected style» в drill-down);
   R17-safe (id/число). Панель embeddings — только алиасы (§63, Wave A).
6. **Один виджет/одни данные (§61.4)**: endpoint `inspector` отдаёт все три
   режима; агрегат считается из ТЕХ ЖЕ событий, что и Last Run; событие
   SUMMARY_RUN_DONE — единственный источник итогов runs (aggregate
   healthy/degraded считается с coverage-правилом §61.6).
7. **Гейты смежных эпиков обновлены по санкции**: §116-инвариант F6
   (6→8 read-only GET) и S6-набор роутов analytics — Wave E добавляет
   read-only global-admin маршруты spec §5 E.2 (ADR-1028-7 D8); изменение
   утверждённых списков — явное, с комментариями, на ревью.

## E6. Что НЕ сделано / остатки (честно)

* **T-4446 (Browser Use + Playwright suite)** — НЕ закрыт: live-прогон
  4 сценариев §61.16 (A healthy / B L2→Legacy / C style failure /
  D coverage) на desktop+mobile требует production (Browser-прогон
  запрещён инструкцией Orchestrator'а — T-4449/T-4450). Подготовлено:
  виджет, JS-unit (структурные гейты разметки/логики), pytest-API.
* **T-4447/T-4448/T-4449** — production acceptance (платные вызовы
  §77–§79, DC-4) — PENDING OWNER (блок tasks.md), не тронуты.
* Стиль-имя в path строки списка runs — из факта COVER_STYLE_SUCCEEDED
  («стиль»/«базовая»), человекочитаемое имя стиля — в drill-down
  (selection-узел), в списке — без имени (R17-минимализм, spec §61.10
  пример допускает «+ Base Cover»).
* Latency median/p95 для L1/L2 — с момента деплоя волны E (события с
  duration_ms новые; COVER_* длительности жили с волны B).
* Агрегат 24h/7d до деплоя — пустой (честно «Данных за период нет»).

## E7. Риски/наблюдения для Reviewer

* SUMMARY_RUN_START/DONE пишутся в `mca_events` (retention 90d) — объём
  ~2 события/прогон, bounded; flush — существующий фоновый контур mca-13.
* `collect_runs_list` — 2 SQL-запроса с LIMIT ≤50 на обновление виджета;
  polling 15с только пока открыта «Аналитика» и режим latest (без
  drill-down), вне вкладки — stop (прецедент statusTimer).
* `in`-сканер asap31_oversight_render_test: v-for с `in (…).` ломает
  проверку шаблона — в Wave E разметке скобки НЕ используются (найдено
  и устранено при сборке; два новых v-for без скобок).

---

# Rework E-final (02.10.2026) — фикс блокера [M-ASAP4-E1] финального gate

> **Объём дельты:** ровно 2 файла — `services/pipeline_analytics.py` +
> `tests/test_pipeline_analytics_asap4.py` (правило re-gate review.md
> соблюдено; HEAD `f04564b` не менялся; не коммитилось). Остальной диф
> эпика не тронут (git status = манифесту гейта + plans-артефакты реворка).

## E8. Фикс (точечный, по рецепту review.md «Fix (точечный)»)

| Файл | Изменение |
|---|---|
| `services/pipeline_analytics.py` | `health_of` (527–568): whitelist публикации расширен durable-канальными статусами — `_PUBLISHED_STATUSES` (522–525) = прежний {ok, published_rich, published_text} + {rich, text} из `SUMMARY_RUN_DONE.usage_json.publication`; новый kwarg `done_event` (строка DONE-события): провал финализации распознаётся по `status`/`outcome` DONE БЕЗ in-memory снапшота → «Не издано» (545–548); durable `pipeline_health` из usage_json — рестарт-паритет сигнала review_degraded (551–552); `build_run_view` захватывает DONE-строку и передаёт её (276–277, 457). `_publication_block` НЕ менялся (контракт UI сохранён). |
| `tests/test_pipeline_analytics_asap4.py` | +импорты `asyncio`/`mca_trace` (24, 31); новый класс `TestRestartHealthDurable` (240–431), 8 тестов (файл 64→72). |

Семантика health после фикса (§61.6/§61.13): **издан** (publication из
durable-событий или снапшота) + coverage<100% → «С деградацией»; издан +
coverage=100% → «Здоров» (кроме durable `pipeline_health=degraded` /
`fallback=legacy` → «С деградацией»); **финализирован без публикации**
(DONE failed) → «Не издано»; **только реально-незавершённый** (нет DONE) →
«Не завершён». Рестарт-безопасно: финальный health не опирается на
in-memory кэш. L-ASAP4-E2 (список runs, статус `empty`) сознательно НЕ
тронут — non-blocking debt переносится; L-ASAP4-E3 — открыто.

## E9. E2E-репро review.md — воспроизведено, теперь зелёное

Сценарий reviewer'а (реальный транспорт, без моков): `pipeline_events
.summary_*` + `COVER_*` (`mca_trace.emit_stage`) → буфер `mca_events` →
`flush_events` в чистый SQLite (v23) → `egs.reset()` (рестарт:
реестр снапшотов пуст) → `collect_run`/`collect_latest`/
`collect_runs_list`/`collect_aggregate` БЕЗ in-memory снапшота.

* **До фикса (контрфактикум на тех же durable-данных):** `health_of`
  со старым whitelist {ok, published_rich, published_text} → `incomplete`
  («Не завершён») при `_publication_block().status == "rich"` — дефект
  M-ASAP4-E1 подтверждён на воспроизводимых данных.
* **После фикса (автотест `test_restart_published_low_coverage_is_
  degraded_full_is_healthy`):** published rich + coverage 44.6% →
  `degraded`/«С деградацией» (publish-узел ✓, running=False, coverage.full
  =False); published rich + 100% → `healthy`/«Здоров».
* **Независимый E2E-скрипт (вне тест-файла, свежий SQLite):**
  flushed=18; `collect_run[44.6]` = degraded/«С деградацией», pub=rich;
  `collect_run[100]` = healthy/«Здоров»; `collect_latest` (durable DONE,
  без снапшота) — healthy последнего; runs_list = [(100, healthy),
  (44.6, degraded)]; aggregate totals = {total: 2, healthy: 1, degraded: 1,
  failed: 0, incomplete: 0}; **E2E_REPRO_RESULT=GREEN, EXIT=0**. Карточка
  больше не противоречит агрегатам и списку (прод-репро reviewer'а снято).
* Дополнительно покрыты рестарт-исходы: финализированный failed →
  «Не издано» (обa пути DONE: `status`-колонка и `outcome`); START без
  DONE → «Не завершён» + running=True; канальный `publication=text`;
  `publication=failed` из usage_json; review_degraded-паритет через
  durable `pipeline_health`.

## E10. Прогоны (все самостоятельно)

| Проверка | Результат |
|---|---|
| `tests/test_pipeline_analytics_asap4.py` | **72/72** (64 + 8 новых) |
| Целевые семьи (analytics-asap4 + волны B/C/D + webapp_analytics_api + webapp_js_unit) | **300 passed** |
| JS `node tests/js/round1030_pipeline_inspector_test.js` | **PIPELINE-INSPECTOR-OK**, EXIT=0 |
| Полный pytest `tests -q --timeout=120` (detached-джоба, 336.95s) | **10773 passed / 2 failed** (≥10766; оба failed — ровно known pre-existing round1026 bounds `test_tool_coordinator…forbidden_paths_out_of_diff` / `test_unified_image_request…vs_baseline`, падают от факта некоммитнутого фиче-диффа, вне эпика) |
| F8 `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны`, **EXIT=0** |
| EOL/BOM | оба затронутых файла LF / no BOM / конечный newline (байт-проверка, CRLF=0) — конвенция новых файлов эпика |

Наблюдение (не регресс): в полном прогоне присутствует
`WARNING: closed 39 leaked aiosqlite connection(s)` — известный
pre-existing шум тестовой гигиены (корневой `conftest.py:72`; задокументи-
рован с round 10.13, на гейте mca-22 — те же ~34; счёт зависит от состава
прогона). Файл analytics-тестов по отдельности — БЕЗ warning: сценарии
закрывают `DatabaseService` в `finally`.

## E11. Границы и статус

* Изменения строго в предписанных 2 файлах; реализации вне health-
  нормализации не тронуты (nodes/list/aggregate/`_publication_block`
  байт-в-байт).
* Ждёт независимого re-gate Reviewer по рецепту review.md: его E2E-репро +
  `TestRunViewScenarios`/`TestPipelineApiRbac` + новые restart-тесты.
* Не верифицировалось здесь (вне скоупа фикса): live-browser §61.16,
  production acceptance — PENDING OWNER (см. финальную секцию review.md).

---

