# MCA (round 10.27) — архитектурные рамки эпика `memory-context-autonomy`

> **Статус:** 🟦 Step 2 @Architect (Wave 0). Код НЕ менялся — только `plans/**`.
> **Источник:** `plans/docs/mca-round1027-plan.md` (§6 вопросы 1/2/3/10/13), `plans/current_task.md` (§5/§17/§18/§19/§20/§22; IMMUTABLE, R17/R18), `tasks.md` трёх фич волны 0.
> **Baseline:** HEAD `7165ff7`; `APP_VERSION` 2.58.31; SQLite DDL **v12**; каталог **473/430/448/102/100/21**; канон **12**; pytest 9513/0 + JS 47/47.
> **Назначение:** единая рамка для всего эпика: механизм Δ DDL, правило Δ каталога/F8, политика kill-switch, нумерация Merge/ADR. Детали решений — в `adr-1027-1/2/3` соответствующих фич.

## 1. Реестр Δ DDL и версий схемы (механизм для всех фич эпика)

**Решение (D1 ADR-1027-1):** единственный механизм изменения схемы SQLite — аддитивный идемпотентный **migration-runner** в `services/database.py` с реестром шагов. Новая версия схемы — не «ручная правка `initialize()`», а **регистрация шага** в упорядоченном реестре. `PRAGMA user_version` сохраняется как маркер применённой версии; добавляется книга `schema_migrations` для аудита/дрейф-детекта.

**Правило нумерации версий:** одна версия = один шаг (`version` — целое, строго +1). Версии **бронируются** фичей по её номеру в этом разделе; фича, которой нужен DDL, обязана заявить версию здесь (санкция @Architect) до старта Build. Шаги применяются по возрастанию версии; параллельная разработка не конфликтует (каждая фича добавляет свою строку реестра, а не правит общую последовательность).

**Формат санкции Δ DDL фичи** (для последующих волн): в `spec.md` фичи — раздел «Δ DDL» с точными `CREATE TABLE/ALTER TABLE/CREATE INDEX`, версией, `nullable`/default, обратным путём; сводный номер версии фиксируется в этом документе. Самовольный DDL без санкции запрещён (границы §18/§20).

### 1.1. Точный Δ DDL волны 0 (санкция)

| Версия | Фича | Объекты (точно) |
|---|---|---|
| **v13** | `mca-14-schema-additive` | `CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at INTEGER NOT NULL, checksum TEXT NOT NULL)`. Только книга реестра; доменных таблиц нет. |
| **v14** | `mca-01-tx-task-supervisor` | `CREATE TABLE task_jobs` (durable-очередь; см. §1.1.1) + индексы. |
| **v15** | `mca-13-event-contract` | `CREATE TABLE mca_events` + `CREATE TABLE mca_event_aggregates` + индексы (см. §1.1.2). |

**Не вводится ни одной PG-таблицы** (сохранённый контракт GEN-R4: SQLite и PG сохраняются, `pg_db.py` вне diff). Старые таблицы не переименовываются/не удаляются (MCA14-R2).

#### 1.1.1. `task_jobs` (v14, `mca-01`)

```
CREATE TABLE IF NOT EXISTS task_jobs (
    job_id         TEXT PRIMARY KEY,              -- UUID4 hex (= run_id/correlation_id)
    owner          TEXT NOT NULL,                 -- логический владелец (модуль)
    kind           TEXT NOT NULL,                 -- тип задачи (summary/backfill/dossier/...)
    coalesce_key   TEXT,                          -- NULL = без коалесинга
    payload        TEXT,                          -- JSON, только R17-safe внутренние поля
    status         TEXT NOT NULL,                 -- queued|running|completed|failed|cancelled|interrupted
    reason_code    TEXT,                          -- словарь MCA-13
    result_ref     TEXT,                          -- ссылка на результат, не сырьё
    error_code     TEXT,
    attempt        INTEGER NOT NULL DEFAULT 0,
    max_attempts   INTEGER NOT NULL DEFAULT 1,
    deadline_at    INTEGER,                       -- unix ts; NULL = без срока
    heartbeat_at   INTEGER,
    generation     INTEGER NOT NULL DEFAULT 0,    -- invalidation версии
    fencing_token  INTEGER NOT NULL DEFAULT 0,    -- takeover-защита (A51)
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    finished_at    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_task_jobs_status_created ON task_jobs (status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_jobs_coalesce_active
    ON task_jobs (coalesce_key) WHERE coalesce_key IS NOT NULL
      AND status IN ('queued', 'running');
```
Legacy-строк нет (новая таблица). Повторный запуск шага — no-op (guard по `sqlite_master`).

#### 1.1.2. `mca_events` / `mca_event_aggregates` (v15, `mca-13`)

```
CREATE TABLE IF NOT EXISTS mca_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             INTEGER NOT NULL,              -- UTC unix
    level          TEXT NOT NULL,                 -- INFO|WARN|ERROR
    event_name     TEXT NOT NULL,
    outcome        TEXT NOT NULL,                 -- start|success|silent|skipped|failed|cancelled|pending_external|interrupted
    trace_id       TEXT,
    operation_id   TEXT,
    parent_operation_id TEXT,
    chat_id        INTEGER,
    component      TEXT,
    stage          TEXT,
    reason_code    TEXT,
    duration_ms    INTEGER,
    attempt        INTEGER,
    config_version TEXT,
    model          TEXT,
    provider       TEXT,
    entity_ids     TEXT,                          -- JSON-массив id (R17-safe)
    usage_json     TEXT,                          -- usage/cost (числа/коды)
    error_json     TEXT,                          -- тип/cause/retryability/восстановление (без секретов)
    source_ref_json TEXT                          -- SourceRef вместо сырого контекста
);
CREATE INDEX IF NOT EXISTS idx_mca_events_ts ON mca_events (ts);
CREATE INDEX IF NOT EXISTS idx_mca_events_trace ON mca_events (trace_id);
CREATE INDEX IF NOT EXISTS idx_mca_events_chat_component ON mca_events (chat_id, component);
CREATE INDEX IF NOT EXISTS idx_mca_events_reason ON mca_events (reason_code);

CREATE TABLE IF NOT EXISTS mca_event_aggregates (
    fingerprint    TEXT PRIMARY KEY,              -- event_name+component+reason_code+error_type
    count          INTEGER NOT NULL DEFAULT 0,
    first_ts       INTEGER NOT NULL,
    last_ts        INTEGER NOT NULL,
    first_trace_id TEXT,                          -- первый полный trace переживает агрегацию
    first_error_json TEXT
);
```
Legacy-строк нет. `mca_events` — **единый durable-стор терминальных событий**; `mca-17a` обязан его переиспользовать, а не создавать второй (запрет «двух хранилищ одинаковых событий», §17 преамбула).

### 1.2. Правило для последующих волн

- Доменные таблицы волн 1–5 (SourceRef/EvidenceLink, Episode/Story, backfill-job, intent, draw/exploration-журнал, experience/lesson, SelfModel/TraitObservation/BehaviorRule/BehaviorFrame, MediaAsset/MediaAnalysis, ClaimEnvelope/verdict-кеш, process-registry/span/incident) получают версии **v16+** и бронируются здесь при старте каждой фичи (санкция @Architect).
- Общий ориентир (уточняется фичей): backfill/queue-механика наследует `task_jobs`; process-registry/span/incident наследует `mca_events` (единая телеметрия, контракт MCA-13) + отдельные таблицы состояния только там, где нужен durable lifecycle (не дублируя события).
- Каждая DDL-фича обязана: (i) объявить версию здесь, (ii) пройти backup+read-back `mca-14`, (iii) сохранить старые ID/таблицы, (iv) documented обратный путь.

### 1.2.1. AMEND волны 1 (санкции @Architect, Step 2, 26.09.2026) — данные

| Версия | Фича | Объекты (точно) |
|---|---|---|
| **v16** | `mca-03-message-identity` | `ALTER TABLE smart_messages ADD COLUMN` ×18 (все nullable): `sent_at, ingested_at, edited_at, sent_at_source, source_kind, namespace, source_record_id, caption, content_hash, media_ref, reply_to_kind, reply_to_author_id, quote_text, quote_author_id, forward_author_id, message_state, state_evidence, current_revision`; `CREATE TABLE IF NOT EXISTS message_source_records` (+2 индекса), `CREATE TABLE IF NOT EXISTS message_revisions` (+1 индекс), `CREATE TABLE IF NOT EXISTS chat_id_migrations`; `CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_tg`, `idx_smart_messages_chat_sent`; опциональный partial UNIQUE `idx_smart_messages_chat_tg_live_unique` (только при прохождении duplicate pre-check). Backfill legacy bounded/resumable (guard `sent_at_source IS NULL`); старые `id`/`timestamp`/FTS сохраняются. См. `plans/archive/mca-03-message-identity-round1027/spec.md` §5. |
| **— (Δ DDL = 0)** | `mca-02-safe-fetch-cookies` | Доменных таблиц не добавляет: конфигурация/лимиты/allowlist — env-only, egress/аудит — рантайм/durable-документ. При появлении durable-потребности — новая заявка @Architect и версия **v17+** через реестр `mca-14`. См. `plans/archive/mca-02-safe-fetch-cookies-round1027/spec.md` §5. |

**Порядок брони:** `v16` закреплена за `mca-03` (Wave 1); `mca-02` — Δ DDL=0. Доменные таблицы остальных фич волн 1–5 начинаются с `v17`.

### 1.2.2. AMEND волны 1 (санкция @Architect, Step 2, 26.09.2026) — `mca-04a-provenance-contract`

| Версия | Фича | Объекты (точно) |
|---|---|---|
| **v17** | `mca-04a-provenance-contract` | `CREATE TABLE IF NOT EXISTS mca_source_refs` (типизированный SourceRef: `store`/`entity_type`/`entity_id`/`chat_id`/`revision` + nullable `tg_message_id`/`dataset_id`/`source_record_id`/`resolution`) + 2 индекса; `CREATE TABLE IF NOT EXISTS mca_evidence_links` (объект+источник с версиями, `link_type`, `method`, `verification`, `independence`, `claim_key`, `extractor_version`, `basis`, `checks_json`, `established_at`) + 3 индекса; `CREATE TABLE IF NOT EXISTS mca_provenance_status` (`origin_status`/`conflict_status`/`freshness_status`/`coverage_status`/`coverage_covered`/`coverage_total`/`extractor_version`); 6 nullable-колонок `graph_facts` (`subject_ref_id`, `attribution_method`, `assertion_kind`, `speaker_author_id`, `extractor_version`, `provenance_channel`) + `idx_graph_facts_subject_ref`. Backfill — **только прямые ссылки** (bounded/resumable, guard по объектному SourceRef; семантический поиск не выполняется). `origin` CHECK `graph_facts` **не расширяется**. См. `plans/archive/mca-04a-provenance-contract-round1027/spec.md` §5. |
| **— (Δ DDL = 0 доп.)** | (нет) | PG — no-op (GEN-R4; `pg_db.py` вне diff). Старые таблицы/ID/FTS сохраняются. |

**Санкция (T-3819):** Δ DDL = **v17**; Δ каталога = **0**; kill-switch — `MCA_PROVENANCE_ENABLED`/`MCA_FACT_ATTRIBUTION_ENABLED`/`MCA_EVIDENCE_RECONSTRUCTION_ENABLED`; нарезка 04a/04b §8.3.1 санкционирована (04a — п.1/2/3 + контракт п.5); carry-over `L-MCA03-8` — не в 04a, обязательный вход `mca-04b`; Risk **R3**; deploy `DEFERRED_TO_RELEASE`. `mca-04b` — собственные доменные версии **v18+** (отдельная заявка при старте).

### 1.2.3. AMEND волны 1 (санкция @Architect, Step 2, 27.09.2026) — `mca-07-retrieval-context`

| Версия | Фича | Объекты (точно) |
|---|---|---|
| **v18** | `mca-07-retrieval-context` | `CREATE TABLE IF NOT EXISTS mca_embedding_index_generations` (реестр поколений/fingerprint векторных индексов: `index_name`/`generation`/`fingerprint`/`provider`/`model`/`dims`/`preprocessing_version`/`endpoint_fingerprint`/`status`/`created_at`/`activated_at`/`superseded_at`) + уникальный `idx_mca_eig_name_gen(index_name, generation)` + частичный уникальный `idx_mca_eig_active(index_name) WHERE status='active'` + `idx_mca_eig_fingerprint`; `ALTER TABLE embedding_cache ADD COLUMN` ×5 (все nullable): `provider`, `model`, `preprocessing_version`, `endpoint_fingerprint`, `identity_fingerprint`. Vec-таблицы (`smart_archive`/`graph_facts_vec`) **не** модифицируются (ALTER у vec0 нет) — идентичность обслуживается реестром. Backfill **не требуется** (nullable=честный unknown; legacy-ключи кэша не матчатся новым identity-ключом и вытесняются TTL/LRU). См. `plans/archive/mca-07-retrieval-context-round1027/spec.md` §5. |
| **— (Δ DDL = 0 доп.)** | (нет) | Сводки/lookup — CAS по существующим `window_end_ts`/`raw_count` (`chat_running_summary`), Δ DDL не требует. PG — **no-op** (GEN-R4; `pg_db.py` вне diff). Старые таблицы/ID/FTS/vec-данные сохраняются. |

**Санкция (T-3840):** Δ DDL = **v18**; Δ каталога = **0**; kill-switch — `MCA_RETRIEVAL_CONTEXT_ENABLED`/`MCA_EVIDENCE_BUNDLE_ENABLED`/`MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED`/`MCA_TYPED_RERANKER_ENABLED`/`MCA_SUMMARY_SINGLEFLIGHT_ENABLED`/`MCA_CONTEXT_ANSWER_CACHE_ENABLED`; Risk **R3**; deploy `DEFERRED_TO_RELEASE`.

**⚠️ Порядок брони версий (критический путь):** `mca-07` идёт по критическому пути **до** `mca-04b`, поэтому **v18 бронируется за `mca-07`**, а advisory-заявка `mca-04b` «v18+» (§98.4) **сдвигается на v19+** (отдельная заявка @Architect при старте). Фактическая перестройка несовместимого vec-индекса остаётся зоной `mca-04b`; `mca-07` лишь **определяет** механизм поколений/fingerprint и gate (FTS-only при mismatch).

### 1.2.4. AMEND Wave 0 — остаток (санкция @Architect, Step 2, 27.09.2026) — `mca-17a-observability-core`

| Версия | Фича | Объекты (точно) |
|---|---|---|
| **v19** | `mca-17a-observability-core` | `CREATE TABLE IF NOT EXISTS mca_pipeline_runs` (`pipeline_run_id` PK, `pipeline_type`, `pipeline_version`, `root_job_id`, `status`, `reason_code`, `started_at`/`finished_at`/`heartbeat_at`/`progress_at`/`deadline_at`, `checkpoint_ref`, `config_version`, timestamps) + `idx_mca_pipeline_runs_status`/`idx_mca_pipeline_runs_type_started`/`idx_mca_pipeline_runs_root_job`; `CREATE TABLE IF NOT EXISTS mca_incidents` (`incident_id` PK, `fingerprint`, `process_id`, `pipeline_type`, `stage`, `severity`, `title`, `first_ts`/`last_ts`, `repeat_count`, `jobs_json`/`chats_json`, `impact`, `fallback_used`, `first_trace_id`/`last_trace_id`, `acknowledged_at`/`acknowledged_by`, `resolved_at`, `resolution_evidence`, timestamps) + `idx_mca_incidents_fingerprint`/`idx_mca_incidents_active`/`idx_mca_incidents_severity`; `ALTER TABLE task_jobs ADD COLUMN` ×8 (nullable: `pipeline_run_id`, `span_id`, `parent_span_id`, `causation_id`, `attempt_id`, `progress_at`, `next_retry_at`, `checkpoint_ref`) + `idx_task_jobs_pipeline_run`/`idx_task_jobs_status_heartbeat`/`idx_task_jobs_status_next_retry`; `ALTER TABLE mca_events ADD COLUMN` ×15 (nullable: `pipeline_run_id`, `pipeline_type`, `pipeline_version`, `span_id`, `parent_span_id`, `linked_span_ids`, `job_id`, `attempt_id`, `causation_id`, `event_sequence`, `status`, `heartbeat_at`, `progress_at`, `deadline_at`, `checkpoint_ref`) + `idx_mca_events_pipeline_run`/`idx_mca_events_span`/`idx_mca_events_status`. Аддитивно/идемпотентно (guard `sqlite_master`/`PRAGMA table_info`); повторный прогон — no-op; `nullable` = честный unknown; PG — **no-op** (GEN-R4; `pg_db.py` вне diff); старые таблицы/ID/vec сохранены. Точные `CREATE/ALTER/INDEX` — `plans/archive/mca-17a-observability-core-round1027/spec.md` §5.1. См. ADR-1027-8 D2. |
| **— (Δ DDL = 0 доп.)** | `mca-process-registry` (в составе `mca-17a`) | Таблица доменного реестра процессов **не создаётся**: реестр — **code-declared** (`services/mca_process_registry.py`; runtime-статус вычисляется при чтении) — ADR-1027-8 D1. |

**Санкция (T-3862):** Δ DDL = **v19**; Δ каталога = **0** (`param_catalog.py` вне diff; F8 ADR-1026-2 **NOT_APPLICABLE**); kill-switch — `MCA_OBSERVABILITY_ENABLED` (master), `MCA_PROCESS_REGISTRY_ENABLED`, `MCA_TRACE_SPAN_ENABLED`, `MCA_JOB_LIFECYCLE_ENABLED`, `MCA_HEARTBEAT_WATCHDOG_ENABLED`, `MCA_INCIDENTS_ENABLED`, `MCA_INCIDENT_PUSH_ENABLED`, `MCA_TELEMETRY_SPOOL_ENABLED` (default ON, OFF = паритет baseline) + `MCA_FAULT_INJECTION_ENABLED` (default **OFF**, dev/test-only, вне effective-state §20.2); Risk **R3**; deploy `DEFERRED_TO_RELEASE`. REUSE ExecutionGraph §82–§92 + `mca_events` + `TaskSupervisor`/`task_jobs` + `write_transaction` + `MigrationStep` (второй store/аналитика/`TaskSupervisor`/write-механизм запрещены).

**⚠️ Порядок брони версий (критический путь):** `mca-17a` идёт по критическому пути Wave 0 и стартует **до** `mca-04b`, поэтому **v19 бронируется за `mca-17a`**, а advisory-заявка `mca-04b` «v19+» **сдвигается на v20+** (отдельная заявка @Architect при старте `mca-04b`, как ранее v18→v19). Доменные таблицы `mca-04b` начинаются с **v20**.

### 1.2.5. AMEND Wave 2 (санкция @Architect, Step 2, 27.09.2026) — `mca-04b-dossier-rebuild`

| Версия | Фича | Объекты (точно) |
|---|---|---|
| **v20** | `mca-04b-dossier-rebuild` | `CREATE TABLE IF NOT EXISTS mca_dossier_generations` (регистр staging/generation исправления досье §8.3.4: `generation_id` PK, `chat_id`/`subject_ref_id`, `state ∈ {building,active,superseded,failed}`, `scope_kind`, `range_from_ts`/`range_to_ts`, **`snapshot_boundary_ts`/`snapshot_boundary_id`**, `extractor_version`, `kernel_version`, `counters_json` (группы счётчиков + покрытие по годам/месяцам), `staging_ref`, `supersedes_generation_id`, `backup_ref`, timestamps) + `idx_mca_dossier_gen_subject(chat_id, subject_ref_id, state)` + partial UNIQUE `idx_mca_dossier_gen_active(chat_id, subject_ref_id) WHERE state='active'`; `CREATE TABLE IF NOT EXISTS mca_dossier_staging_items` (`staging_id` PK, `generation_id`, `item_kind ∈ {portrait,person_fact,meme,tree}`, `subject_ref_id`/`source_ref_id`, `classification`, `payload_json` (R17-safe), `verification`, `extractor_version`, `created_at`) + `idx_mca_dossier_staging_gen(generation_id, item_kind)`; `ALTER TABLE graph_facts ADD COLUMN dossier_generation_id TEXT` (nullable; `NULL` = legacy/unknown) + `idx_graph_facts_dossier_gen(dossier_generation_id)`. Аддитивно/идемпотентно (guard `sqlite_master`/`PRAGMA table_info`); повторный прогон — no-op; `nullable` = честный unknown; PG — **no-op** (GEN-R4; `pg_db.py` вне diff); старые таблицы/ID/FTS/vec/`origin` CHECK сохранены. Точные `CREATE/ALTER/INDEX` — `plans/features/mca-04b-dossier-rebuild/spec.md` §5.2. См. ADR-1027-9 D8/D13. |
| **— (Δ DDL = 0 доп.)** | `mca-04b-dossier-rebuild` | Batch-состояния/прогресс/покрытие — **REUSE** `DossierRebuildJobStore` (файловый durable) + `task_jobs`/`mca_pipeline_runs` (v14/v19) с `payload`/`correlation`/`checkpoint_ref`; активация vec-поколения (`N-MCA07-1`) — **REUSE** `mca_embedding_index_generations` (v18) + single-writer операция `activate_embedding_generation` (второй таблицы нет, `ensure_embedding_generation` не меняет активное поколение); версия namespace (`L-MCA03-8`) — в строке отпечатка `import:<export_id>:<v2>` (в `message_source_records.namespace`, без колонки). |

**Санкция (T-3889/T-3890):** Δ DDL = **v20**; **v21 остаётся свободной за `mca-04b`** (не объявляется; заявка при второй аддитивной потребности на релизе). Δ каталога = **0** (env-only `ClassVar`; `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES вне diff; F8 ADR-1026-2 **NOT_APPLICABLE**; каталог `473/430/448/102/100/21` не изменяется). Kill-switch (7; default ON, OFF = паритет baseline): `MCA_DOSSIER_REBUILD_ENABLED` (master), `MCA_DOSSIER_BACKGROUND_PASS_ENABLED`, `MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED`, `MCA_DOSSIER_RECLASSIFY_ENABLED`, `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED`, `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`, `MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED`. Env-only лимиты (не каталог): `MCA_DOSSIER_BATCH_MAX_MESSAGES` (500), `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` (ON). Risk **R3**; deploy `DEFERRED_TO_RELEASE`.

**⚠️ Порядок брони версий:** `mca-04b` стартует **после** `mca-04a`/`mca-07`/`mca-17a` (v17/v18/v19 заняты); доменные версии `mca-04b` — **v20** (первая фактическая), **v21** — свободна/не объявлена. **Открытые вопросы плана §6/i–iii закрыты:** материализация full-rebuild контракта — REUSE job-store + `task_jobs`/`mca_pipeline_runs` (не dedicated-таблица); форма staging/generation — регистр `mca_dossier_generations` + staging-таблица + тег `graph_facts.dossier_generation_id` (v20); активация vec-поколения — REUSE v18 + операция.

### 1.2.6. AMEND Wave 2 (санкция @Architect, Step 2, 01.10.2026) — `mca-05-episodes-stories`

| Версия | Фича | Объекты (точно) |
|---|---|---|
| **v21** | `mca-05-episodes-stories` | `CREATE TABLE IF NOT EXISTS mca_episodes` (эпизод: `episode_id` PK, `chat_id`, `title`, `summary`, `participants_json` (устойчивые ID mca-03), `event_start_ts`/`event_end_ts`, `discovered_at`, `updated_at`, `claims_json` (R17-safe), `outcome`/`open_questions`, `extraction_version`, `mapping_status`); `CREATE TABLE IF NOT EXISTS mca_stories` (карточка §9.1: `story_id` PK, `chat_id`, `title`, `summary`, `participants_json`, `event_start_ts`/`event_end_ts`, `discovered_at`, `updated_at`, `claims_json`, `outcome`/`open_questions`, `state ∈ {open,closed,uncertain}`, `verification`, `excluded_from_retrieval`, `active_version_id`, `expected_version` (CAS), `extractor_version`, nullable override-колонки, `task_status_ref` ≠ state); `CREATE TABLE IF NOT EXISTS mca_story_versions` (`version_id` PK, `story_id`, `version_no`, `payload_json`, `created_at`, `created_by`, `extractor_version`); `CREATE TABLE IF NOT EXISTS mca_story_episode_links` (`story_id`/`episode_id`/`order_no`); `CREATE TABLE IF NOT EXISTS mca_story_continuations` (`from_episode_id`/`to_episode_id`/`confirmation`/`status`); `CREATE TABLE IF NOT EXISTS mca_story_redirects` (`old_kind`/`old_id` PK → `new_kind`/`new_id`); `CREATE TABLE IF NOT EXISTS mca_story_legacy_links` (`lore_story_id`, `story_id` nullable, `mapping_status ∈ {mapped,legacy,unmapped}`) + индексы под фактические запросы репозитория (EXPLAIN QUERY PLAN на Build; финальный набор — spec/ADR-1027-12 §5). Аддитивно/идемпотентно (guard `sqlite_master`/`PRAGMA table_info`); повторный прогон — no-op; `nullable` = честный unknown; PG — **no-op** (GEN-R4; `pg_db.py` вне diff); **старые `lore_stories` не трогаются**; стабильные ID сохранены. Точный контракт — `plans/features/mca-05-episodes-stories/spec.md` §3(b)/§5 и ADR-1027-12 §5. См. ADR-1027-12 D2/D3/D9. |

**Санкция (T-4246/T-4247):** Δ DDL = **v21**; **бронь v21 «за `mca-04b`» (§1.2.5) растворена** — `mca-04b` закрыт/архивирован, в проде 2.58.41 с финальным v20, вторая аддитивная потребность не заявлена; версии реестра — упорядоченные клеймы (гэп безвреден); гипотетическая вторая потребность `mca-04b` берёт следующий фактически свободный номер при заявке. Δ каталога = **0** (env-only `ClassVar`; `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES вне diff; F8 ADR-1026-2 **NOT_APPLICABLE**; каталог `488/427/463/105/103/21` не изменяется). Kill-switch (4; default ON, OFF = паритет baseline): `MCA_EPISODES_ENABLED` (master), `MCA_EPISODES_BACKFILL_ENABLED`, `MCA_EPISODES_CONTINUATION_ENABLED`, `MCA_EPISODES_COMPILER_FACADE_ENABLED`. Env-only лимиты (не каталог): `MCA_EPISODES_BATCH_MAX_MESSAGES` (500), `MCA_EPISODES_DIRECT_PRIORITY_ENABLED` (ON). reason_code (+10): `episode_extracted`, `story_segment_empty`, `story_continuation_confirmed`, `story_continuation_rejected`, `story_contradiction_found`, `story_legacy_unmapped`, `story_backfill_paused_budget`, `story_source_recheck_queued`, `story_merged`, `story_split`. Risk **R2**; deploy `DEFERRED_TO_RELEASE`; merge `plans/ARCHITECTURE.md` **§108+**, ADR-1027-12 → Accepted по Merge. REUSE: `provenance` (mca-04a), `task_jobs`/`write_transaction` (mca-01), `mca_events` (mca-13), `mca_process_registry`/`mca_pipeline_runs` (mca-17a), `MigrationStep` (mca-14), `message_identity` (mca-03), `_episode_candidates`/`EvidenceBundle.local_context` (mca-07; carry-over **M-MCA07-2** — владелец наполнения `local_context`). Запрещено: второй каталог историй / второй SourceRef-контракт / второй retrieval-движок / второй bundle / фоновый ремап legacy / send-path в пайплайне / UI-раздел «Истории» (mca-12).

**⚠️ Порядок брони версий:** `mca-05` стартует после закрытия Wave 0/Wave 1 (v17–v20 заняты); доменная версия `mca-05` — **v21** (первая и, на момент санкции, единственная заявленная). Следующие свободные — **v22+** (по факту заявки, без предброни).

### 1.2.7. AMEND Wave 4 (санкция @Architect, Step 2, 06.10.2026) — `mca-18-self-model`

| Версия | Фича | Объекты (точно) |
|---|---|---|
| **v31** | `mca-18-self-model` | `CREATE TABLE mca_self_identity` (singleton `id BOOLEAN PK DEFAULT true CHECK(id)`, `agent_id TEXT NOT NULL`, `bot_user_id INTEGER`, `bound_at INTEGER`, `note TEXT`, `updated_at INTEGER`; сид ON CONFLICT DO NOTHING); `CREATE TABLE mca_trait_observations` (id PK, `agent_id`, `chat_id` NULL, `dimension` NULL, `raw_text`, `normalized`, `source_refs` JSON, `subject_status`, `observed_at`, `source_chat_id`, `legacy_ref` NULL, `created_at`; idx (agent_id, observed_at DESC), idx (chat_id, observed_at DESC)); `CREATE TABLE mca_behavior_rules` (id PK, `agent_id`, `dimension`, `target_value REAL`, `strength REAL`, `confidence_basis`, `scope`, `applicability` JSON, `exclusions` JSON, `expiry_at`, `review_at`, `examples` JSON, `counterexamples` JSON, `status ∈ {observed,candidate,active,rejected,suspended,superseded}`, `status_reason`, `source_observation_ids` JSON, `version INTEGER`, `event_dedup_hash`, `updated_at`; idx (agent_id, status, dimension), idx (scope, status)); `CREATE TABLE mca_adoption_links` (id PK, `subject_entity_id` DEFAULT 'self', `opinion_ref`, `basis_refs`, `adopted_at`, `direction`, UNIQUE (subject_entity_id, opinion_ref)); `ALTER TABLE graph_facts ADD COLUMN` ×9 под guard `PRAGMA table_info`: `subject_entity_id TEXT`, `speaker_entity_id TEXT`, `perspective TEXT`, `memory_kind TEXT`, `scope TEXT`, `valid_from INTEGER`, `valid_to INTEGER`, `confidence_basis TEXT`, `revision INTEGER NOT NULL DEFAULT 1` (`status`/`supersedes`/`weight` — REUSE, database.py:4684–4687); idx (chat_id, memory_kind, status), idx (subject_entity_id). Аддитивно/идемпотентно; nullable = честный unknown; PG — **no-op** (`pg_db.py` вне diff: `personas`/`persona_traits`/`persona_state` не изменяются). Точный контракт — `plans/features/mca-18-self-model/spec.md` §3/§8.1 и ADR-1028-18 D4/D5. |

**Санкция (T-5073/T-5074):** Δ DDL = **v31** (первая свободная; v30 в проде 2.58.61, `database.py:1273`) через реестр mca-14 + backup-guard. Δ каталога = **0** (errata 06.10.2026: исходная «+1 `flags.persona_enabled`» отозвана — ключ уже существует как pg_key `PERSONA_ENABLED`, `param_catalog.py:1182`; дубликат ломает F8-инвариант; F8 ADR-1026-2 для mca-18 НЕ переиздаётся, каталог 510 не меняется). Kill-switch (3; default ON, OFF = бит-в-бит 2.58.61; реестр mca_gates 73→76): `MCA_SELF_MODEL_ENABLED` (master), `MCA_TRAIT_RULES_ENABLED`, `MCA_LEGACY_TRAITS_MIGRATION_ENABLED`. Env-only лимиты (не каталог): `MCA_TRAIT_MAX_STEP_PER_CYCLE` (0.1), `MCA_TRAIT_MAX_STEP_24H` (0.2), `MCA_MOOD_TTL_HOURS` (6). reason_code (+10, 247→257, словарь `services/mca_events.py:60`): `self_model_unavailable`, `self_model_stale`, `self_model_disabled`, `self_model_snapshot_error`, `trait_attribution_ambiguous`, `trait_conflict_core`, `trait_step_limit`, `trait_reinforcement_dedup`, `legacy_trait_unverified`, `trait_rule_rejected`. Risk **R3** (threat-failure-analysis выпущен); deploy — **пер-фичевый bump 2.58.62** (CA-11, прецедент mca-15/16/09/10b), не DEFERRED_TO_RELEASE. ADR-1028-18 (Proposed → Accepted по merge §122+); merge `plans/ARCHITECTURE.md` **§122+**. REUSE: швы mca-08 (`bot_persona.py:42/:44/:237/:368`), provenance v17 (mca-04a), `task_jobs`/`write_transaction` (mca-01), `mca_events` (mca-13), `mca_process_registry` (mca-17a — процесс `self.model` v1), `MigrationStep` (mca-14), identity (mca-03), `chat_params.get_chat_param` (прецедент наследования), `mca_bot_outputs` (mca-22, анти-самоусиление); carry-over **M-MCA07-2** (persona/interests EvidenceBundle) → mca-18. Граница N-1 mca-10b: `select_memory_recall_candidates` живым путём НЕ подключается (backlog `:289`). Запрещено: второй механизм личности/слой промпта/bundle/контракт памяти/реестр/координатор/словарь событий; `form_contract` не трогается.

## 2. Δ каталога волны 0 и правило F8-переиздания

**Решение:** **Δ каталога волны 0 = 0.** Ни один параметр волны 0 не попадает в `param_catalog`; все рубильники/лимиты — **env-only `ClassVar`** (прецедент `DB_LOCK_RESILIENCE_ENABLED`, `MULTILAYER_EXTRACTION_ENABLED`, ADR-1026-22 D3). F8 (ADR-1026-2) **не переиздаётся**; счётчики `473/430/448/102/100/21` не меняются; `sha256`-пин `param_catalog.py` не трогается.

**Правило F8-переиздания (для всего эпика):**
1. Если новая настройка — управляемая пользователем в UI (global или per-chat) → это **Δ каталога ≠ 0**; фича обязана заявить точный Δ (новые REGISTRY/Settings/GROUPS/`_TAB_BY_GROUP`/TAB_RULES) и запустить процедуру ADR-1026-2 (repin `sha256` → regenerate TSV/meta/ScreenMap/widget-map → recount/дельта → обновить `tests/fixtures/round1025/f8_baseline.json` и ассерты). Обновление тестов — **не отключение**.
2. Если новая настройка — инфраструктурная/аварийная (kill-switch, TTL, технический лимит) без UI → **env-only `ClassVar`**, Δ каталога = 0, F8 не запускается.
3. Ожидаемый Δ каталога по эпику: волна 0 — **0**; волны 1–5, вероятно, ненулевой (`random.*`, vision-подключение, decision/intent-настройки, statistics, learning, sleep-gates, TTL/лимиты) — каждая фича заявляет точно.
4. **Волна 1 (данные) — Δ каталога = 0:** `mca-03` (kill-switch/env-only), `mca-02` (kill-switch/лимиты/allowlist/env-only), `mca-04a` (provenance/атрибуция — env-only kill-switch, без UI-настроек) и `mca-07` (retrieval/reranker/bundle/бюджет/сводки/answer-cache — env-only kill-switch; `CHAT_DEDUP_*`/`EMBED_CACHE_*` не удаляются, а bypass'ятся при ON) не добавляют параметров в `param_catalog`; F8 не переиздаётся (санкция @Architect, Step 2).
5. **Wave 0 — остаток / Wave 2 — Δ каталога = 0:** `mca-17a` (реестр/trace/lifecycle/watchdog/инциденты/телеметрия — env-only kill-switch/пороги) и `mca-04b` (full rebuild/backfill/реклассификация/staging-активация/vec-активация/namespace — env-only kill-switch и лимиты `MCA_DOSSIER_*`) не добавляют параметров в `param_catalog`; F8 (ADR-1026-2) **NOT_APPLICABLE**.

## 3. Kill-switch: единая политика и имена волн 0–1

**Политика (MCA14-R5, §18):** у каждой функции — оперативный kill-switch; **env-only `ClassVar[bool] = _env_bool("NAME", True)`** (default **ON**), резолв per-call, никогда не бросает; **OFF = паритет baseline** (ровно прежнее поведение, без новых записей/эффектов). Релиз (§20) идёт со всеми ON. Нельзя закрыть задачу с молча отключённой функцией: OFF фиксируется в release-manifest/логе с причиной, временем и планом исправления (R17-safe).

**Имена (волна 0 + волна 1):**

| Фича | Kill-switch | Default | OFF-паритет |
|---|---|---|---|
| `mca-14` | `MCA_SCHEMA_MIGRATIONS_ENABLED` | ON | старый путь миграций без нового runner/backup-обвязки |
| `mca-01` | `MCA_TX_OWNERSHIP_ENABLED` | ON | прежний `write_transaction` (как сейчас: rollback вне lock) |
| `mca-01` | `MCA_TASK_SUPERVISOR_ENABLED` | ON | без реестра/durable-очереди/coalescing (текущее поведение задач) |
| `mca-13` | `MCA_EVENT_CONTRACT_ENABLED` | ON | события как сейчас (`emit_agentic_event` без start/outcome) |
| `mca-13` | `MCA_TELEMETRY_STORE_ENABLED` | ON | только структурный лог, без durable-персистенции |
| `mca-03` | `MCA_MESSAGE_IDENTITY_ENABLED` | ON | legacy-путь идентичности (ingestion/импорт как сейчас, без канонизации/source records) |
| `mca-03` | `MCA_MESSAGE_REVISION_TRACKING_ENABLED` | ON | редакции без версионирования (текущее поведение) |
| `mca-02` | `MCA_SAFE_FETCH_ENABLED` | ON | legacy-путь загрузки (без SSRF-обвязки/лимитов-обёртки) |
| `mca-02` | `MCA_EGRESS_GUARD_ENABLED` | ON | без эквивалентного egress-контроля подпроцессов/yt-dlp/прокси |
| `mca-04a` | `MCA_PROVENANCE_ENABLED` | ON | legacy-путь без типизированных SourceRef/EvidenceLink/статусов; новые записи/связи не создаются |
| `mca-04a` | `MCA_FACT_ATTRIBUTION_ENABLED` | ON | legacy-атрибуция фактов (`target=asker`, name-scope читателей, Layer B `person_facts` не сохраняются); паритет §8.3.2-baseline |
| `mca-04a` | `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` | ON | восстановление старых записей не запускается (прямо сохранённое происхождение по-прежнему фиксируется) |
| `mca-07` | `MCA_RETRIEVAL_CONTEXT_ENABLED` | ON | legacy-путь retrieval (без объединённого контракта/эпизодов-фасада/vector-identity) |
| `mca-07` | `MCA_EVIDENCE_BUNDLE_ENABLED` | ON | legacy-сборка контекста без единого `EvidenceBundle` |
| `mca-07` | `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` | ON | прежний `_apply_context_budget` (без полного учёта payload/адаптивности) |
| `mca-07` | `MCA_TYPED_RERANKER_ENABLED` | ON | прежний reranker (без типизированного списка ID/отдельного статуса) |
| `mca-07` | `MCA_SUMMARY_SINGLEFLIGHT_ENABLED` | ON | прежний fire-and-forget сводки без singleflight/high-watermark/CAS |
| `mca-07` | `MCA_CONTEXT_ANSWER_CACHE_ENABLED` | ON | прежний ответный кеш по одному нормализованному query/chat/user (паритет baseline); ON = MCA-07 context-keyed политика (legacy text-replay OFF, update-дедуп сохранён) |
| `mca-04b` | `MCA_DOSSIER_REBUILD_ENABLED` | ON | legacy `run_dossier_rebuild` как сейчас (без нового full-rebuild контракта/состояний) |
| `mca-04b` | `MCA_DOSSIER_BACKGROUND_PASS_ENABLED` | ON | фоновый проход по архиву не запускается |
| `mca-04b` | `MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED` | ON | read-time восстановление не запускается (связка с `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` — не дублируется) |
| `mca-04b` | `MCA_DOSSIER_RECLASSIFY_ENABLED` | ON | безопасная реклассификация накопленных данных не выполняется |
| `mca-04b` | `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED` | ON | прямая запись как сейчас (без staging/generation) |
| `mca-04b` | `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED` | ON | gate `mca-07` FTS-only как сейчас (активация поколения не выполняется) |
| `mca-04b` | `MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED` | ON | прежний отпечаток namespace (`legacy_import_v1`/v1) |
| `mca-17a` | `MCA_OBSERVABILITY_ENABLED` | ON | мастер: без реестра/span-расширения/lifecycle/watchdog/инцидентов; `emit_mca_event`/ExecutionGraph как есть (паритет baseline) |
| `mca-17a` | `MCA_PROCESS_REGISTRY_ENABLED` | ON | реестр процессов не публикуется/не регистрируется |
| `mca-17a` | `MCA_TRACE_SPAN_ENABLED` | ON | события без расширенных span-полей (только контракт MCA-13) |
| `mca-17a` | `MCA_JOB_LIFECYCLE_ENABLED` | ON | `partial`/`degraded`/linked job не вычисляются; статусы `mca-01` как есть |
| `mca-17a` | `MCA_HEARTBEAT_WATCHDOG_ENABLED` | ON | нет watchdog/takeover/stale-детекта (heartbeat — только данные) |
| `mca-17a` | `MCA_INCIDENTS_ENABLED` | ON | инциденты не группируются/не ведутся (`mca_event_aggregates` как есть) |
| `mca-17a` | `MCA_INCIDENT_PUSH_ENABLED` | ON | доставка в миниапп выключена (нет push/poll-обновления инцидентов) |
| `mca-17a` | `MCA_TELEMETRY_SPOOL_ENABLED` | ON | нет дискового spool/`degraded`-счётчика (только structural fallback log) |
| `mca-17a` | `MCA_FAULT_INJECTION_ENABLED` | **OFF** | dev/test-only; **не** product-функция (вне effective-state §20.2; product-релиз — все ON, исключение только stub §14.12) |

Плюс **существующие** рубильники, которые обязаны уважаться (не дублируются): `DB_LOCK_RESILIENCE_ENABLED` (F0.5/ADR-1024-18), `AGENTIC_EVENTS_ENABLED` (ADR-1026-22 D3). **Совместимость `mca-17a`:** под-гейты инертны/паритетны по своей оси; `MCA_EVENT_CONTRACT_ENABLED` + `MCA_TELEMETRY_STORE_ENABLED` уважаются wiring'ом `flush_events`/`prune_events` (carry-over §94.5 п.4); `MCA_TASK_SUPERVISOR_ENABLED`/`MCA_TX_OWNERSHIP_ENABLED` уважаются lifecycle/watchdog. **Приоритет `mca-04a`:** `MCA_EVIDENCE_RECONSTRUCTION_ENABLED`/`MCA_FACT_ATTRIBUTION_ENABLED` инертны при `MCA_PROVENANCE_ENABLED=OFF`; `MULTILAYER_EXTRACTION_ENABLED`/`GRAPH_RAG_ENABLED`/`MCA_MESSAGE_IDENTITY_ENABLED` уважаются. **Совместимость `mca-07`:** гейты независимы (OFF одного даёт паритет по своей оси); `CHAT_DEDUP_ENABLED`/`CHAT_DEDUP_TTL_SECONDS`/`EMBED_CACHE_ENABLED`/`GRAPH_RAG_ENABLED`/`MCA_MESSAGE_IDENTITY_ENABLED`/`MCA_PROVENANCE_ENABLED`/`MCA_TASK_SUPERVISOR_ENABLED` **уважаются, не дублируются и не удаляются** (Δ каталога = 0).

**Retention-настройки MCA-13** (configurable, §17.3) — env-only `ClassVar`: `MCA_DETAILED_LOG_RETENTION_DAYS` (14), `MCA_TERMINAL_EVENT_RETENTION_DAYS` (90). Δ каталога = 0.

## 4. Нумерация Merge и ADR волны 0

- **Merge в `plans/ARCHITECTURE.md`:** следующий свободный — **§93**. Зарезервировано волне 0: **§93 (`mca-14`), §94 (`mca-13`), §95 (`mca-01`)** — но фактический номер присваивается @Architect по порядку **завершения/merge**, а не по номеру фичи; фича при чтении берёт следующий фактически свободный. Волнам 1–5 — §96+ по тому же правилу.
- **ADR:** следующий свободный после ADR-1026-23. Волна 0: **ADR-1027-1** (`mca-14`), **ADR-1027-2** (`mca-13`), **ADR-1027-3** (`mca-01`); **волна 1: ADR-1027-4** (`mca-03`), **ADR-1027-5** (`mca-02`), **ADR-1027-6** (`mca-04a`), **ADR-1027-7** (`mca-07`); **Wave 0 — остаток: ADR-1027-8** (`mca-17a-observability-core`, Proposed, T-3861/T-3862). **Wave 2: ADR-1027-9** (`mca-04b-dossier-rebuild`, **Accepted** — merge §107 исполнен 01.10.2026, прод-валидация 2.58.41; T-3889/T-3890). Статус волновых ADR — **Proposed → Accepted по Merge** в `plans/ARCHITECTURE.md`. Merge волны 1: следующий фактически свободный **§96+** (по порядку завершения; фактически §96 `mca-03` → §97 `mca-02`; далее **§98+**, `mca-04a`; `mca-07` — **§99+**); **Wave 0 — остаток: `mca-17a` → следующий фактически свободный §100+**; **Wave 2: `mca-04b` → фактически §107** (confirm 01.10.2026, Step 2b-confirm @Architect: §106 занят release-marker'ом ASAP-3.2; refresh 30.09.2026: §101–§105 фактически заняты ASAP-2/2.1/3/3.1 + EXTRA; присваивается по завершению/merge; **факт merge — §107, reconcile 01.10.2026**). Статус исторических волновых ADR — Proposed до Merge (ADR-1027-10/-11 и ADR-1028-1…4 уже выпущены; ADR-1027-9 закреплён за `mca-04b` — коллизии нет). **Wave 2 — эпизоды: ADR-1027-12** (`mca-05-episodes-stories`, Proposed 01.10.2026, T-4246; закреплён, коллизий нет; → Accepted по Merge §108+).
- **Release:** все фичи — `DEFERRED_TO_RELEASE` (§20, единый релиз на `mca-release`); пер-фичевых тегов/bump нет. Kill-switch — hot-откат; код-откат — анкер `7165ff7` (R18: теги/бэкапы не удалять).

## 5. Границы и повторное использование (сводно)

- **REUSE, не дублировать:** `emit_agentic_event`/`RunSnapshotStore`/ExecutionGraph §82–§92 (расширяются, вторая аналитика запрещена); `memory_backup` VACUUM INTO (backup-паттерн); `DossierRebuildJobStore` (прецедент durable job-store/registry/retention); F0.5 `write_transaction` (держать, не переписывать с нуля); `smartmodule_concurrency` (починить, не заменять).
- **Один контур:** одна телеметрия (`mca_events` + log), один TaskSupervisor, один write-механизм, один координатор (не затрагивается волной 0).
- **R17/R18:** секреты/сырьё не логируются, `sanitize()`-маскирование до записи во все каналы; `plans/current_task.md` не изменяется; KG/индекс — на @Memory.

## 6. Точки отката волны 0

| Фича | hot-откат | cold-откат |
|---|---|---|
| `mca-14` | `MCA_SCHEMA_MIGRATIONS_ENABLED=false` | `git revert` → `7165ff7`; DDL аддитивен (новые таблицы безвредны) |
| `mca-01` | `MCA_TASK_SUPERVISOR_ENABLED=false` / `MCA_TX_OWNERSHIP_ENABLED=false` | `git revert` → `7165ff7`; `task_jobs` остаётся (данные не теряются) |
| `mca-13` | `MCA_EVENT_CONTRACT_ENABLED=false` / `MCA_TELEMETRY_STORE_ENABLED=false` | `git revert` → `7165ff7`; `mca_events` остаётся |

**Rollback-compat (MCA14-R4):** совместимый откат кода оставляет новые данные; при несовместимости — rollback build/forward fix, backup restore — только аварийный сценарий (не штатный переключатель).
