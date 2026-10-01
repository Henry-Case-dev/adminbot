# ADR-1027-9 — `mca-04b-dossier-rebuild`: полная пересборка досье (3 режима, snapshot boundary, durable batch-состояния), безопасное исправление накопленных данных (staging/generation + атомарная активация), каскадный пересчёт, выборка A95 — Δ DDL = v20, Δ каталога = 0, R3

- **Статус:** **Accepted-ready (Proposed)** — confirm 01.10.2026 (Step 2b-confirm @Architect, T-3889/T-3890): merge-цель **§107+**, baseline прод **2.58.40**; санкции/контракт/DDL/kill-switch/R3 подтверждены без изменений; v20 — единственная SQLite-Δ (PG no-op); auto-budgets — standalone env-only (D14); admin-only гейтинг сохраняется. Финальная ратификация **Accepted** — только по Merge в `plans/ARCHITECTURE.md` **§107+** (T-3916/T-3917).
- **Фича:** `mca-04b-dossier-rebuild` (эпик round 10.27 MCA, Wave 2 — когниция). **Deploy:** `DEFERRED_TO_RELEASE`.
- **ТЗ-основание:** `plans/current_task.md` §8.3 (`:238–250`), §8.3 (`:252–254`), §8.3.1 (`:256–266`), §8.3.3 (`:282–292`), §8.3.4 (`:294–300`); §3/§3.1 (`:47`,`:60–75`); §17.1–§17.3 (`:818–844`); §18 (`:856–872`); §19 A85/A86/A87/A88/A89/A90/A95; §20; §22; R17/R18.
- **Baseline (confirm 01.10.2026, Step 2b-confirm @Architect):** прод **2.58.40** — прод-HEAD **`4cb267a`** (feat `0483386`, docs `4cb267a`/`325b1b5`; локальный docs-HEAD `486b3e9`); `APP_VERSION` **2.58.40** (верифицировано `config/settings.py`); SQLite DDL **v19** (хвост реестра `MigrationStep` = `_SCHEMA_VERSION_OBSERVABILITY`; Δ=0 во всех релизах ASAP/EXTRA/ASAP-3.2); каталог **488/427/463/105/103/21** (Δ=0 с 2.58.39); последний раздел `plans/ARCHITECTURE.md` — **§106** (release-marker ASAP-3.2). Refresh-анкер 30.09.2026 (`1287130` / 2.58.39 / §105) — исторический; `05bc870` / `2.58.31` / `473/430/448/102/100/21` / pytest `9828/0` + JS `48/48` — только как след. Фактический baseline фиксируется на старте Build, не из Step 2.
- **Связано:** AMEND `services/dossier_rebuild_jobs.py`, `services/lore_worker.py`, `web/api/chat_lore.py`, `services/database.py` (`upsert_generated_dossier` + v20 + чтения досье); REUSE `services/provenance.py` (`mca-04a`), `mca-embedding_index_generations` (`mca-07`), `TaskSupervisor`/`task_jobs`/`write_transaction` (`mca-01`), `mca_events`/`mca_process_registry`/`mca_trace` (`mca-13`/`mca-17a`), `memory_backup`, `MigrationStep` (`mca-14`), `message_identity`/`loader` (`mca-03`); рамка `plans/docs/mca-round1027-arch-frames.md`.

## Refresh 30.09.2026 (Step 2b @Architect) — merge-цель, baseline, PG-only EXTRA

- **Merge-цель: §106+.** §101–§105 фактически заняты: ASAP-2 → §101, ASAP-2.1 → §102, ASAP-3 → §103, ASAP-3.1 → §104, EXTRA `extra-cover-style-pipeline` → §105. Цель `mca-04b` при merge — **§106+** («следующий фактически свободный» на момент merge, T-3916). Прежняя формулировка «§101+» устарела; правки — в этом ADR, `spec.md` и `plans/docs/mca-round1027-plan.md` §3.10.
- **Baseline refresh:** HEAD `1287130`, `APP_VERSION` **2.58.39**, SQLite DDL **v19**, каталог **488/427/463/105/103/21** (см. «Baseline» выше). Решения D1–D13 от этих чисел не зависят (контракт/DDL/санкции те же).
- **DDL v20 остаётся за `mca-04b`.** EXTRA `extra-cover-style-pipeline` выбрала **PG-only**-хранилище (идемпотентные `CREATE … IF NOT EXISTS` в `services/pg_db.py`); **SQLite `user_version` остаётся 19**. Реестр `MigrationStep` заканчивается `v19` (`_SCHEMA_VERSION_OBSERVABILITY`); объекты v20 (`mca_dossier_generations` / `mca_dossier_staging_items` / `graph_facts.dossier_generation_id`) в коде **отсутствуют**. Доменные версии `mca-04b` начинаются с **v20**; `v21` не объявляется. ADR-1027-9 D13 и `mca-round1027-arch-frames.md` §1.2.5 EXTRA **не правились** (`ARCHITECTURE.md` §105: «SQLite v19 / mca-04b v20 unchanged»).
- **Kill-switch (7) — без изменений.** `MCA_DOSSIER_REBUILD_ENABLED` (master), `MCA_DOSSIER_BACKGROUND_PASS_ENABLED`, `MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED`, `MCA_DOSSIER_RECLASSIFY_ENABLED`, `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED`, `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`, `MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED` (+ env-only лимиты `MCA_DOSSIER_BATCH_MAX_MESSAGES`, `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED`). EXTRA добавила **свои** `COVER_STYLES_ENABLED`/`COVER_RICH_DEGRADED_ENABLED` — пересечений нет.
- **Carry-over / Low-residual (второй уровень входов) — без изменений.** `L-MCA03-8` (namespace `import:<export_id>:<v2>`), `N-MCA04A-1..3`, `N-MCA07-1` (REUSE v18 + операция активации), `D-MCA04A-2/-3/-7` — состав и привязка прежние.
- **Doc-hygiene (scope):** `plans/docs/mca-round1027-plan.md` §3.10/§7 (merge-цель → **§106+**; устаревшая пометка «ADR-1027-9 — следующий свободный после ADR-1027-8» снята — фактически после выпущены ADR-1027-10/-11 и ADR-1028-1…4; номер **ADR-1027-9 остаётся закреплён** за `mca-04b`, коллизии нет) и `plans/docs/mca-round1027-arch-frames.md` §4 (merge-цель `mca-04b` §101+ → §106+; статус-строка ADR). **Архитектурные решения, санкции D1–D13, `§1.2.5` рамки и kill-switch не менялись.**

## Confirm 01.10.2026 (Step 2b-confirm @Architect) — §107+, baseline 2.58.40, v20 re-confirm, auto-budgets, admin-only

- **Merge-цель: §107+.** §106 занят release-marker'ом ASAP-3.2 (VERIFIED 01.10.2026, прод 2.58.40). Семантическое правило («следующий фактически свободный» на момент merge) не менялось — устарела только конкретная метка; правки метки — в этом ADR, `spec.md`, `plans/docs/mca-round1027-plan.md` §3.10/§7 и `plans/docs/mca-round1027-arch-frames.md` §4.
- **v20 — единственная SQLite-Δ (re-confirm @2.58.40, верифицировано кодом):** хвост реестра `MigrationStep` = **v19** (`_SCHEMA_VERSION_OBSERVABILITY`, `services/database.py`); `mca_dossier_generations`/`mca_dossier_staging_items`/`graph_facts.dossier_generation_id`/`activate_embedding_generation` в коде **отсутствуют** (rg по `*.py` — 0 совпадений); EXTRA/ASAP-3.2 добавили только **PG** `cover_style_connections` (PG-only, `pg_db.py` — на SQLite-бронь не влияет); `graph_facts` волной/ASAP не расширялся. **PG — no-op** для `mca-04b` (GEN-R4). **v21 остаётся свободной** (не объявляется; заявка при второй аддитивной потребности на релизе).
- **D14. Auto-budgets — standalone env-only, без интеграции с Model Capacity Resolver (ASAP-3.1).** Выбрано: batch-лимиты `mca-04b` остаются env-only (`MCA_DOSSIER_BATCH_MAX_MESSAGES` — размер обработки порции в **сообщениях**, не токен-бюджет), источник budget exhaustion — **существующий `worker_budget`** (`services/lore_worker.py` — `consume` llm_calls/llm_tokens per-chat+global, baseline-поведение), реакция на исчерпание — D3 (`paused`, никогда `completed`). Новые `services/auto_budget.py`/`model_capacity.py`/`model_slots.py`/`summary_budget_auto.py` (ASAP-3.1, §104) решают другую задачу — контекстно-оконные stage-бюджеты одного LLM-вызова (Summary/Direct) — и не имеют dossier/lore-референсов (rg — 0, верифицировано @2.58.40). **Обоснование:** (a) инвариант «размер окна ≠ прочитано ≠ передано модели» (spec §4.3, инвариант 13) требует раздельных единиц — смешение message-лимита с токен-бюджетом размывает его; (b) «1 активный LLM batch/чат» — правило конкурентности (`TaskSupervisor` coalescing), не токен-бюджет — вне зоны Resolver; (c) интеграция потребовала бы AMEND свежевыпущенного кода ASAP-3.1 (регистрация dossier-StagePolicy) без требования ТЗ — против REUSE-границ D12/GEN-R19; (d) инвариант «budget exhaustion ≠ completed» инвариантен к **источнику** исчерпания — сохранение существующего `worker_budget` обнуляет регрессионный риск для обеих сторон. **Альтернатива** «интеграция с Resolver/worker-quota» — отклонена. **Future:** при фактической потребности — отдельная санкционированная amendment (возможно read-only потребление `model_capacity` consumer-side), не в этой фиче; Builder запрещено переподключать exhaustion на `auto_budget`.
- **Admin-only — подтверждено.** AMEND-пути `web/api/chat_lore.py` (`start_dossier_rebuild`/чтения статусов) сохраняют действующий `_is_global_admin`-гейтинг (определение `:169`; вызовы `:183/:267/:327/:348/:500` — верифицировано @2.58.40) — продолжение политики admin-only мутаций (§104/§135). Δ каталога = **0**: admin-проверка — код-уровень, не параметр каталога.
- **Doc-hygiene scope — подтверждён и исполнен:** `mca-round1027-plan.md` §3.10 и §7, `mca-round1027-arch-frames.md` §4 — метка merge-цели «§106+» → «§107+» (только метка; §1.2.5 рамки — историческая санкция, не правилась). Архитектурные решения D1–D13, санкции, DDL v20, kill-switch (7), reason_code, risk R3, deploy `DEFERRED_TO_RELEASE` — без изменений.
- **Консультация владельца не требуется:** развилка auto-budgets закрыта документированными границами (D12/REUSE, инвариант 13, GEN-R19); пользовательских tradeoff (cost/privacy/interop) нет.

## Контекст

§8.3 требует три **включённых** режима пополнения памяти и durable-задание с `dataset/range/cursor/version/status/heartbeat/attempt/processed/linked/unresolved/errors`, уникальным ключом, checkpoint после фиксации, идемпотентным повтором и стабильной сортировкой **без OFFSET**. §8.3.3 задаёт единый контракт full rebuild (chat/subject, диапазон, snapshot boundary, версия экстрактора, устойчивый cursor), где **live-window limit ≠ предел пересборки**, сообщения после границы снимка догоняются инкрементально; запрещает грузить архив/кандидатов одним списком в RAM/LLM и разрешает worker-конфигурацию «1 активный LLM batch на чат, порции до 500 с делением по токенам/эпизодам, приоритет прямых ответов, backlog на диске». §8.3.3 перечисляет различимые состояния `queued/running/paused/interrupted/failed/completed` и прямо запрещает подменять `processed → total` и трактовать budget exhaustion/ошибку/отмену/рестарт как «всё обработано». §8.3.4 требует безопасной повторной классификации производных (не очищать старые `confirmed` автоматически), сохранения исходных сообщений/ручных правок/защищённых сведений, `unknown`/quarantine для записей без источника, staging/generation с атомарной активацией, сохранения backup/rollback, каскадного пересчёта зависимых «по очереди с сохранением истории» и проверяемой выборки Лехи/Васи/Ярика с precision/recall **отдельно от охвата**.

**Фактическое состояние baseline (сверено на baseline `05bc870`; номера строк — исторические, Builder сверяет фактические пути по границе §22):**
- `services/lore_worker.py::_WINDOW_SQL` (`:154–158`) — `ORDER BY timestamp DESC, id DESC LIMIT ?`; `rebuild_dossier_for_user` (`:775–815`) читает **одно** bounded окно и передаёт его в `_classify_chunked_user`; при `window_hours=0` LIMIT сохраняется → пользовательский запуск не охватывает всю историю.
- `web/api/chat_lore.py::start_dossier_rebuild` (`:1086+`) считает `window_hours` из `_PERIOD_WINDOW`, а прогресс берётся от bounded-окна; `DossierRebuildJobStore` уже ведёт `total/processed/status/stage` (файловый durable JSON), но без `snapshot boundary`/`extractor_version`/`cursor`/групп счётчиков/покрытия.
- `services/dossier_rebuild_jobs.py::run_dossier_rebuild` (`:657–758`) после вызова движка безусловно ставит `status="done"`, `processed=int(total)` (`:741–743`) — budget exhaustion/частичный проход дают **ложный `done`**; `rebuild_dossier_for_user` останавливает цикл чанков при исчерпании бюджета (`_extract_chunk → None` → `break`) и синтезирует частичный результат.
- `services/lore_worker.py::_extract_chunk` (`:886–915`) вызывает `filter_layer_a_candidates(..., row_count=len(lines))` (row-bound **уже подключён**), но **не** вызывает `local_evidence_to_source_refs` → локальные номера evidence не превращаются в постоянные `SourceRef` (врезка п.5 не завершена).
- `services/database.py::upsert_generated_dossier` (`:6848–6899`) заменяет предыдущий портрет новым (SELECT→UPDATE последней `dossier_portrait`-строки) → регулярный прогон короткого окна стирает долгосрочную картину.
- `services/database.py::ensure_embedding_generation` (`:2051–2103`) **никогда** не подменяет активное поколение (A06) и не имеет операции активации (N-MCA07-1); реестр `mca_embedding_index_generations` (v18) существует.
- `services/provenance.py`: `reconstruct_fact_provenance` (`:691–759`) инертен и не вызывается прод-путём; `local_evidence_to_source_refs` (`:819–855`) и `validate_layer_a_row_bounds` (`:858–883`) реализованы; `EXTRACTOR_VERSION`, `_lookup_user_ids_by_names` (`:566+`), `guess_subject` (`:591+`) — на месте (N-MCA04A-1..3).
- Прецеденты REUSE: `TaskSupervisor`/`task_jobs` (v14) + `mca_pipeline_runs` (v19) + `write_transaction` (single-writer); `memory_backup` (VACUUM INTO); `DossierRebuildJobStore` (durable file-store); `MigrationStep` (v13).

## Решения

**D1. Единый контракт full rebuild (chat/subject, диапазон, snapshot boundary, версия экстрактора, устойчивый cursor).**
- **Выбрано:** один контракт для UI и CLI: область `chat_id` + `subject_ref_id` (устойчивый ID, не имя); `scope_kind ∈ {full, range, incremental}`; `range_from_ts`/`range_to_ts`; **`snapshot_boundary=(ts,id)`**, зафиксированная при старте как текущий максимум `(timestamp,id)`; `extractor_version` (+ `kernel_version`); keyset-cursor `(last_ts, last_id)`. Проход — `ORDER BY timestamp, id LIMIT :batch` по `(timestamp > last_ts) OR (timestamp = last_ts AND id > last_id)` — **без OFFSET**. Live-window limit (`LORE_WINDOW_MAX_MESSAGES`, 300) остаётся размером окна/чтения, но **не** пределом пересборки. Сообщения после границы снимка догоняются режимом 1.
- **Обоснование:** §8.3.3 (`:284`) verbatim; §8.3 (`:244`); A87/A88.
- **Альтернатива:** `window_hours=0` = «вся история» через снятие LIMIT в `_WINDOW_SQL` — отклонено (одно окно в RAM; противоречит поточному проходу и §8.3.3); keyset вместо `OFFSET` — принято (OFFSET по миллионам изменяющихся строк запрещён §8.3).

**D2. Материализация durable-состояния — REUSE, не второй store.**
- **Выбрано:** authoritative rebuild-состояние — существующий `DossierRebuildJobStore` (файловый durable JSON), расширяемый аддитивно полями `snapshot_boundary`/`cursor`/`extractor_version`/группами счётчиков/`coverage_json`/`paused`-состоянием; durable-очередь/coalescing/heartbeat/watchdog — REUSE `TaskSupervisor`/`task_jobs` (v14/v19) + `mca_pipeline_runs` (v19); correlation (`pipeline_run_id`/`span_id`/`checkpoint_ref`/`attempt_id`) — через `mca-17a`-поля. **Δ DDL доп. = 0.** Второй job-store/`TaskSupervisor` запрещены (GEN-R19).
- **Обоснование:** §8.3 (`:244`); рамка §5 (REUSE `DossierRebuildJobStore`); MCA14-R3 (без долгой транзакции); `mca-01`/`mca-17a` контракты.
- **Альтернатива:** новая таблица `dossier_rebuild_batches` — отклонено (дублирует `task_jobs`/`mca_pipeline_runs`; нарушает «второй store запрещён»).

**D3. Batch-состояния и честная финализация.**
- **Выбрано:** rebuild-состояния `queued | running | paused | interrupted | failed | completed` (+ `cancelled`), authoritative в job-store; маппинг в `task_jobs`: `paused → queued` (+`reason_code`), остальные тождественно; `paused ≠ completed`. `completed` — только при обработке всех предусмотренных диапазонов без потерянных/необработанных batch; `processed` фиксируется фактическим значением; budget exhaustion/недоступность модели/`parse error`/отмена/рестарт → `paused`/`failed`/`interrupted`/`cancelled`, никогда `completed`/`100%`. Run-level — `mca_pipeline_runs.status` (`partial`/`degraded` при частичном проходе).
- **Обоснование:** §8.3.3 (`:290`) verbatim; A89; MCA13-R1; `mca-17a` lifecycle (v19).
- **Альтернатива:** оставить `done/failed/cancelled` как сейчас — отклонено (не различает budget/модель/parse/отмену; прямо нарушает §8.3.3).

**D4. Checkpoint/идемпотентность/деление/приоритет/backlog.**
- **Выбрано:** checkpoint продвигается **после** фиксации результата batch (в job-state и `checkpoint_ref`); повтор идемпотентен (дедуп связей/производных); порции чтения ≤500 (`MCA_DOSSIER_BATCH_MAX_MESSAGES`) с дальнейшим делением по токенам/эпизодам; **1 активный LLM batch на чат**; приоритет прямых ответов (`direct`-flow не блокируется, `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED`); backlog на диске (`jobs_dir`/`archive_dir`); результаты извлечения — по batch на диске; иерархический синтез по субъекту/периодам; новый live-batch **обновляет** накопленную картину. Архив не в RAM/одним промптом.
- **Обоснование:** §8.3 (`:244`,`:246`,`:248`), §8.3.3 (`:284`,`:288`) verbatim; A87/A89; MCA14-R3.
- **Альтернатива:** держать кандидатов в памяти и синтезировать одним промптом — отклонено (прямо запрещено; OOM на миллионах строк).

**D5. Три режима.**
- **Выбрано:** (1) новые данные — инкрементальный live-batch после границы снимка, обновляющий накопленную картину; (2) восстановление при востребованном чтении старой записи — read-time `reconstruct_fact_provenance` (прод-путь), вектор — кандидат, не доказательство; (3) фоновый проход по архиву — resumable обход всего доступного диапазона по карте покрытия (не только популярные темы). Все три включены при первом деплое; отдельный human gate не вводится.
- **Обоснование:** §8.3 (`:242`) verbatim; A87/A89.
- **Альтернатива:** только live + read-time (без фонового прохода) — отклонено (§8.3 прямо требует фоновый проход, «чтобы не изучать только популярные темы»).

**D6. Субъектная/тематическая полнота на chunk/прод-путях.**
- **Выбрано:** учитываются собственные сообщения участника, надёжно разрешённые упоминания другими и reply-контекст; отбор только по имени/автору недостаточен; короткие ответы не отбрасываются механически («да» подтверждает факт из вопроса; без контекста — не факт); для бесшумных участников — идентичности всего нужного scope, а не только ростер говорящих. Субъект — устойчивый `subject_ref_id` (контракт `mca-04a` §8.3.2), второй контракт запрещён.
- **Обоснование:** §8.3.3 (`:286`) verbatim; §8.3.2 (`:270`); A85/A88.
- **Альтернатива:** фильтр `person_facts` только по имени/автору — отклонено (§8.3.3 прямо запрещает).

**D7. Безопасная реклассификация накопленных данных (§8.3.4).**
- **Выбрано:** новые правила **не** очищают старые `confirmed` автоматически; реклассификация выполняется в staging: исправление subject, отделение общих знаний от личных фактов (коды `attribution_method`/`assertion_kind` из `mca-04a`); исходные сообщения/`message_revisions`/ручные правки (`persona_dossier_overrides`)/защищённые сведения сохраняются; **не** удалять все `confirmed` по совпадению target; записи без восстановимого источника → `origin_status='unknown'`/quarantine (не ложное `confirmed`, не удаление всей памяти).
- **Обоснование:** §8.3.4 (`:296`) verbatim; A90; §8.3.2.
- **Альтернатива:** DELETE старых `confirmed` и перезапись — отклонено (прямо запрещено; необратимая потеря памяти).

**D8. Staging/generation + атомарная активация + backup/rollback.**
- **Выбрано:** новая версия строится в staging (`mca_dossier_staging_items`) под управлением регистра `mca_dossier_generations`; **атомарная активация** — одна короткая `write_transaction`: применить staged-элементы к `graph_facts` с `dossier_generation_id`, пометить предыдущее `active → superseded`, новое `building → active`; одна `active` на `(chat_id, subject_ref_id)` (partial UNIQUE); повтор/рестарт идемпотентны; прежняя версия остаётся доступной (строки `superseded` не удаляются; читатели — по активному поколению, legacy `NULL` = unknown); rollback — REUSE `memory_backup` + повторная активация предыдущего поколения; обновления во время пересборки не теряются; сбой Layer B/лимит/частичный проход не уничтожают старые факты.
- **Обоснование:** §8.3.4 (`:298`) verbatim; A90; MCA14-R2; REUSE `memory_backup`/`lore_cache` generation-паттерн.
- **Альтернатива:** (a) прямая запись с file-snapshot-откатом (как сейчас) — отклонено (нет staging/атомарной активации, A90); (b) отдельная generation-копия всех фактов в новой таблице — отклонено (дублирование памяти; достаточно тега `dossier_generation_id` + регистра).

**D9. Каскадный пересчёт зависимых.**
- **Выбрано:** после активации зависимые пересчитываются **по очереди** через существующие контуры: портреты/мемы (Layer B) → RAG-производные → убеждения (сон) → парадигмы (глубокий сон); каждый шаг — идемпотентный job (coalescing `TaskSupervisor`); версионирование с сохранением истории (старое место работы не удаляется при появлении нового); второй контур не создаётся.
- **Обоснование:** §8.3.4 (`:298`) verbatim; A90; GEN-R19.
- **Альтернатива:** пересчитать всё сразу/параллельно — отклонено (§8.3.4: «по очереди»; конкуренция за single-writer lock и зависимые версии).

**D10. Выборка A95: precision/recall отдельно от охвата.**
- **Выбрано:** небольшая проверяемая выборка разных лет и типов (собственные сведения, чужие рассказы, ответы, пересылки, новости, шутки, смена обстоятельств) по Лехе/Васе/Ярику; фиксированные ожидаемые включения/исключения; `precision`/`recall` извлечения измеряются **отдельно** от покрытия архива; негативные регрессионные примеры (заведомо чужие/общие: прайс АЗС, этимология имени, просьба нарисовать квадрат, чужая биография) исключены из личных фактов; отчёт показывает пропущенные примеры и причины; длина портрета — не критерий; результат не подгоняется под ожидания владельца.
- **Обоснование:** §8.3.4 (`:300`) verbatim; §8.3.2 (`:274`); A95; GEN-R20.
- **Альтернатива:** оценивать «полноту» по длине портрета/числу записей — отклонено (прямо запрещено; «полнота по найденным источникам»).

**D11. Наблюдаемость, счётчики, покрытие, reason_code.**
- **Выбрано:** раздельные счётчики в разных единицах (доступно/просмотрено/отобрано/кандидаты/принято/отвергнуто по причинам/`unresolved`/обновлено/ошибки/пропуски) + покрытие по годам/месяцам; «размер окна ≠ прочитано ≠ передано модели»; job-счётчики `processed/linked/unresolved/errors`; `start`+терминальный `outcome` через REUSE `emit_mca_event`/`mca_events`; регистрация процесса/стадий/виджет-ID в `mca_process_registry` для `mca-17a`; расширение словаря `reason_code` (см. санкции); нулевой результат при полном корректном проходе — валиден; `sanitize()` до записи, SourceRef вместо сырого контекста.
- **Обоснование:** §8.3.3 (`:290`,`:292`) verbatim; §17.1–§17.3; §27.1; GEN-R14/R17; A27/A48.
- **Альтернатива:** один агрегат «обработано» — отклонено (смешивает разные единицы; прямо запрещено).

**D12. REUSE-дисциплина и границы.**
- **Выбрано:** переиспользуются `lore_worker`/`dossier_rebuild_jobs`/`chat_lore`/`upsert_generated_dossier`/`TaskSupervisor`/`task_jobs`/`write_transaction`/`mca_events`/`mca_process_registry`/`MigrationStep`/`memory_backup`/`mca_embedding_index_generations`; контракт §8.3.2 (`SourceRef`/`EvidenceLink`) — из `mca-04a`. **Запрещено** создавать второй dossier-движок/job-store/embedding-активатор/`TaskSupervisor`/write-механизм/контракт субъекта. Полная витрина/drill-down — зона `mca-17c`.
- **Обоснование:** GEN-R19/§3.1; §4 (один контур); рамка §5.
- **Альтернатива:** вынести пересборку в новый сервис — отклонено (GEN-R19; второй контур).

**D13. Δ DDL = v20; Δ каталога = 0; kill-switch; Risk R3; deploy.**
- **Выбрано:** Δ DDL **v20** (staging/generation: `mca_dossier_generations` + `mca_dossier_staging_items` + nullable `graph_facts.dossier_generation_id` + индексы) через реестр `mca-14`; batch-состояния/покрытие — 0 доп. (REUSE job-store/`task_jobs`/`mca_pipeline_runs`); активация vec — 0 доп. (REUSE v18); версия namespace — 0 доп. (в строке отпечатка). Бронь: `mca-04b` = v20; v21 — свободна (не объявлена). Δ каталога = **0** (env-only; F8 NOT_APPLICABLE). Kill-switch — 7 имён (см. санкции). Risk **R3**; deploy `DEFERRED_TO_RELEASE`; hot env-OFF; cold `git revert` → фактический базовый коммит Build (актуальный baseline `1287130`; исторические анкеры `05bc870`/`7165ff7`).
- **Обоснование:** §18 (`:862–872`); MCA14-R1/R2/R5; tasks.md T-3890; §20.
- **Альтернатива:** Δ DDL = 0 (полностью файловый staging) — отклонено (атомарная активация/идемпотентность/durability A90 требуют durable регистра).

## Санкции и вердикты

- **Δ DDL = v20** — `mca_dossier_generations` (+2 индекса, из них partial UNIQUE `active`), `mca_dossier_staging_items` (+1 индекс), `ALTER TABLE graph_facts ADD COLUMN dossier_generation_id TEXT` (+1 индекс); аддитивно/идемпотентно через реестр `mca-14` (§93); self-guard `sqlite_master`/`PRAGMA table_info`; PG — no-op; старые таблицы/ID/FTS/vec/`origin` CHECK сохранены. **Бронь:** `mca-04b` доменные версии с **v20**; **v21** — свободна (не объявляется; заявка при второй аддитивной потребности). Точные `CREATE/ALTER/INDEX` — spec §5.2.
- **Δ DDL = 0 доп.** — batch-состояния/прогресс/покрытие (REUSE `DossierRebuildJobStore` + `task_jobs`/`mca_pipeline_runs`), активация vec-поколения (REUSE `mca_embedding_index_generations` v18), версия namespace (в строке отпечатка) — отдельные таблицы/колонки не вводятся (закрытые открытые вопросы §6/i–iii).
- **Δ каталога = 0**; F8 (ADR-1026-2) **NOT_APPLICABLE**; `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES вне diff; каталог **488/427/463/105/103/21** (refresh 30.09.2026) не изменяется.
- **Kill-switch (утверждены, 7):** `MCA_DOSSIER_REBUILD_ENABLED` (master), `MCA_DOSSIER_BACKGROUND_PASS_ENABLED`, `MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED`, `MCA_DOSSIER_RECLASSIFY_ENABLED`, `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED`, `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`, `MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED` (env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline; `MCA_DOSSIER_*` инертны при OFF нижележащих). Env-only лимиты (не каталог): `MCA_DOSSIER_BATCH_MAX_MESSAGES` (500), `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` (ON).
- **reason_code (расширение реестра `mca-13`):** `dossier_rebuild_started`, `dossier_batch_processed`, `dossier_paused_budget`, `dossier_interrupted`, `dossier_partial_range`, `dossier_reclassified`, `dossier_staging_activated`, `dossier_generation_superseded`, `dossier_cascade_scheduled`, `dossier_identity_unresolved` (+ существующие `budget_exhausted`/`model_unavailable`/`parse_error`/`interrupted`/`cancelled`/`evidence_invalid`/`provenance_reconstructed`/`provenance_unresolved`/`embedding_generation_changed` переиспользуются).
- **Carry-over исполняется:** D-MCA04A-2 (прод-вызов `reconstruct_fact_provenance`), D-MCA04A-3 (A95-выборка), D-MCA04A-7 (perf-оценка provenance на batch), врезка п.5 (`local_evidence_to_source_refs` в `_extract_chunk`), N-MCA04A-1 (name-резолв ограничен ростером/окном), N-MCA04A-2 (chunked-путь сохраняет `person_facts`), N-MCA04A-3 (пин `guess_subject`), L-MCA03-8 (`import:<export_id>:<v2>`; `legacy_import_v1` не переприсваивается), N-MCA07-1 (REUSE v18 + операция активации).
- **Risk:** **R3** (пересборка/реклассификация меняет память/досье субъектов; каскад на RAG/убеждения/парадигмы/retrieval; фоновый проход конкурирует за single-writer lock; v20 меняет схему); `threat-failure-analysis.md` обязателен (T-3916). Понижение — только при доказанной изоляции активации от hot-path и SC-01/04/08/10/12/16 на фактическом diff (`@Reviewer`).
- **Обратный путь:** hot env-OFF; cold `git revert` → фактический базовый коммит Build (актуальный baseline `1287130`; исторические анкеры `05bc870`/`7165ff7`); v20 аддитивна; restore БД — только аварийный сценарий (R18).
- **Release policy:** `DEFERRED_TO_RELEASE` (§20).
- **Решение о консультации владельца:** не требуется — все развилки закрыты документированными ограничениями ТЗ (7 kill-switch имён утверждены, DDL-состав определён, каталог = 0).

## AMEND / REUSE-карта

| Артефакт | Режим | Суть |
|---|---|---|
| `services/dossier_rebuild_jobs.py` (`DossierRebuildJobStore`/`run_dossier_rebuild`) | **AMEND/FIX** | batch-состояния (`paused`), checkpoint, финализация без `processed→total`; единственный job-store |
| `services/lore_worker.py` (`rebuild_dossier_for_user`/`_WINDOW_SQL`/`_classify_chunked_user`/`_extract_chunk`) | **AMEND/FIX** | full-rebuild контракт, keyset-проход, снятие LIMIT как предела, врезка `local→SourceRef`, сохранение `person_facts` |
| `web/api/chat_lore.py::start_dossier_rebuild` | **AMEND** | прогресс от полного диапазона; `snapshot boundary`/`extractor_version`; существующие поля UI |
| `services/database.py::upsert_generated_dossier` + чтения досье | **FIX/AMEND** | не стирать долгосрочную картину; активное `dossier_generation_id` |
| `services/database.py` (v20 + `activate_embedding_generation`) | **AMEND (NEW шаг)** | staging/generation + операция активации vec-поколения |
| `services/provenance.py` | **REUSE + прод-вызов** | §8.3.2, `reconstruct_fact_provenance`, `local_evidence_to_source_refs`, row-bound |
| `services/task_supervisor.py`/`task_jobs`/`write_transaction` (`mca-01`) | **REUSE** | очередь/coalescing/single-writer |
| `services/mca_events.py`/`mca_process_registry.py`/`mca_trace.py` (`mca-13`/`mca-17a`) | **REUSE** | события/стадии/виджет-ID/heartbeat |
| `mca_embedding_index_generations` (`mca-07`) | **REUSE + ADD операция** | активация (без второй таблицы) |
| `services/memory_backup.py` | **REUSE** | backup/rollback |
| реестр `MigrationStep`/`schema_migrations` (`mca-14`) | **REUSE** | шаг **v20** |
| `services/message_identity.py`/`tools/history_import/loader.py` (`mca-03`) | **AMEND (L-MCA03-8)** | namespace `v2` |
| `mca-05`/`mca-06`/`mca-16`/`mca-18`/`mca-19`/`mca-20` | **Consumers** | расширяют, не заменяют |

| Решение | Задачи |
|---|---|
| D1 (full rebuild контракт) | T-3893, T-3895 |
| D2 (REUSE job-store/task_jobs) | T-3893, T-3894, T-3898 |
| D3 (batch-состояния) | T-3894, T-3898 |
| D4 (checkpoint/деление/приоритет) | T-3894, T-3896, T-3897, T-3898 |
| D5 (3 режима) | T-3895, T-3896, T-3897 |
| D6 (субъектная полнота) | T-3893, T-3904 |
| D7 (реклассификация) | T-3899 |
| D8 (staging/активация) | T-3900, T-3901 |
| D9 (каскад) | T-3902 |
| D10 (A95) | T-3902, T-3908 |
| D11 (наблюдаемость/счётчики) | T-3910, T-3911 |
| D12 (REUSE/границы) | T-3900, T-3904, T-3907 |
| D13 (Δ DDL/kill-switch/risk) | T-3890, T-3892, T-3915 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Охват полной истории | снять LIMIT в `_WINDOW_SQL`; keyset-проход | **keyset-проход** | §8.3.3; без OFFSET; не в RAM |
| Материализация состояния | новая таблица batches; REUSE job-store + `task_jobs` | **REUSE** | GEN-R19; MCA14-R3 |
| Финализация | `done`+`processed=total`; различимые состояния | **различимые состояния** | §8.3.3 verbatim; A89 |
| Форма активации | прямая запись + file-snapshot; registry+staging+tag | **v20 registry + staging + `dossier_generation_id`** | A90; атомарность/идемпотентность |
| Δ DDL | 0; v20 minimal; отдельная generation-таблица фактов | **v20 minimal** | durable активация без дублирования фактов |
| Активация vec | новая таблица; REUSE v18 + операция | **REUSE операция** | N-MCA07-1; GEN-R19 |
| Namespace v2 | колонка версии; версия в отпечатке | **в отпечатке** | L-MCA03-8; Δ DDL = 0 |
| Метрика полноты | длина портрета; precision/recall на выборке | **precision/recall отдельно от охвата** | §8.3.4 verbatim; A95 |
| Каталог | UI-настройки лимитов; env-only | **env-only (Δ=0)** | рамка §2; F8 NOT_APPLICABLE |
| Risk | R2; R3 | **R3** | изменение памяти/каскад/схема |

## Последствия

- Вводится единый full-rebuild контракт и безопасное исправление накопленных досье; `_WINDOW_SQL LIMIT`, ложный `done` и затирание портрета закрываются.
- `graph_facts` расширяется аддитивно (1 nullable-колонка) + 2 новые таблицы; legacy/ID/FTS/vec сохраняются; PG не меняется.
- Врезка `local→SourceRef` завершает контракт `mca-04a` в chunk-пайплайне; активация vec-поколения закрывает `N-MCA07-1`.
- Δ каталога = 0; risk R3 + threat-артефакт; hot env-OFF; cold `git revert` → фактический базовый коммит Build (актуальный baseline `1287130`); deploy `DEFERRED_TO_RELEASE`.
- Полная витрина/представления — `mca-17c`; потребители `mca-05`/`mca-06`/`mca-16`/`mca-18`/`mca-19`/`mca-20` расширяют, не заменяют.

## Ссылки

- Feature: `plans/features/mca-04b-dossier-rebuild/{spec.md, tasks.md, adr-1027-9-dossier-rebuild.md}`.
- Рамка: `plans/docs/mca-round1027-arch-frames.md` (§1.2.5 v20, §2, §3, §4).
- План: `plans/docs/mca-round1027-plan.md` §3.10.
- Код (baseline): `services/lore_worker.py` (`_WINDOW_SQL:154–158`, `rebuild_dossier_for_user:775–815`, `_classify_chunked_user:817–884`, `_extract_chunk:886–915`); `services/dossier_rebuild_jobs.py` (`DossierRebuildJobStore`, `run_dossier_rebuild:657–758`); `web/api/chat_lore.py` (`start_dossier_rebuild:1086+`); `services/database.py` (`upsert_generated_dossier:6848–6899`, `ensure_embedding_generation:2051–2103`, `migration_steps:1363–1418`); `services/provenance.py` (`reconstruct_fact_provenance:691–759`, `local_evidence_to_source_refs:819–855`, `validate_layer_a_row_bounds:858–883`); `services/mca_gates.py`; `config/settings.py`.
- Архитектура: входы §93 (`mca-14`), §94 (`mca-13`), §95 (`mca-01`), §96 (`mca-03`), §97 (`mca-02`), §98 (`mca-04a`), §99 (`mca-07`), §100 (`mca-17a`); §101–§106 — соседние reconcile'ы/релизы (ASAP-2/2.1/3/3.1, EXTRA, ASAP-3.2), не входы; merge → **§107+** (confirm 01.10.2026; **Accepted-ready**).
- Точка отката: актуальный baseline `1287130` (origin/master на 30.09.2026); исторические анкеры `7165ff7` (анкер) / reviewed `05bc870`.
