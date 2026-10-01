# `mca-04b-dossier-rebuild` — evidence (Step 3 @Builder, 01.10.2026)

> **Статус:** 🟨 **IMPLEMENTED — rework round 1 применён** (H-1/H-2/M-1/M-2 из `review.md`; повторное ревью — по дельте). Прод/деплой не затронуты; коммитов НЕТ (worktree-only); `plans/current_task.md` не менялся. R17: секреты/сырой контекст в evidence и событиях отсутствуют — только id/коды/числа.

## 0. Baseline и состояние worktree

| Параметр | Факт |
|---|---|
| Baseline (старт Build) | прод 2.58.40, HEAD `486b3e9` (локальный docs-HEAD; прод-код-коммит `4cb267a`/feat `0483386`), SQLite v19, каталог 488/427/463/105/103/21 |
| Binding-хэши входа | `spec.md` = `18DF2178…A3D2` ✅, `adr-1027-9` = `0492EC24…EB24` ✅, `tasks.md` (до Build) = `EF0C62BC…B56B5` — **изменён Build-правками** (чекбоксы T-3892…3914 + секция Build) |
| Точка отката (код) | cold `git revert` → `4cb267a` (прод) / `486b3e9` (локальный docs); v20 аддитивна; hot — `MCA_DOSSIER_REBUILD_ENABLED=false` |
| Чужой WIP (не тронут) | `plans/docs/mca-round1027-*.md`, `plans/metrics.md`, `plans/workflow_state.md` (modified ДО старта — реконсиляция/Step 2b); untracked `node_modules/`, `package.json`, `package-lock.json`, `.playwright-mcp/`, `extra_images/` — не мои, не менялись |

## 1. Манифест изменений (для детерминированного Reviewer-манифеста)

** unstaged modified (прод-код, 9):**
1. `services/database.py` — миграция `_migrate_dossier_staging_v20` (ровно spec §5.2: `mca_dossier_generations` +2 idx (partial UNIQUE `idx_mca_dossier_gen_active`), `mca_dossier_staging_items` +1 idx, nullable `graph_facts.dossier_generation_id` + `idx_graph_facts_dossier_gen`; `_SCHEMA_VERSION_DOSSIER_STAGING = 20`; шаг в `migration_steps()`); API поколений: `create_dossier_generation` / `get_dossier_generation` / `get_active_dossier_generation` / `set_dossier_generation_state` / `insert_dossier_staging_item` / `list_dossier_staging_items` / **`activate_dossier_generation`** (одна `write_transaction`: apply staged c тегом поколения → prev active `superseded` → `building→active`; идемпотентный повтор no-op); **`activate_embedding_generation`** (N-MCA07-1, под `serialized()`, A06 не нарушен); **FIX `upsert_generated_dossier`** (инвариант 10: `previous_text` + bounded `portrait_history` в meta, contract_version 2); `insert_graph_fact` + аддитивный kwarg `dossier_generation_id`; `facts_without_evidence_links` (bounded read-time). Вспомогательные `_dossier_render_portrait` / `_provenance_extractor_version` (REUSE `dossier_prompts`/`provenance`).
2. `services/lore_worker.py` — keyset-инфраструктура: `_REBUILD_FILTER` (БЕЗ min_chars — «короткие ответы не отбрасываются», §8.3.3), `_KEYSET_PAGE_SQL` (стабильный `(timestamp,id)` ASC, **без OFFSET**), `_RANGE_COUNT_SQL`/`_RANGE_BOUNDARY_SQL`/`_RANGE_ROSTER_SQL` (bounded 500); `count_range_messages`/`range_boundary`/`rebuild_dossier_full` (единый контракт: порции ≤`MCA_DOSSIER_BATCH_MAX_MESSAGES`, деление на чанки Layer A, backlog-артефакт fsync per batch, checkpoint-callback ПОСЛЕ фиксации, budget-exhaustion → `budget_exhausted` **без частичного синтеза**, resume_cursor, `write_mode` direct/collect, счётчики 11 единиц + rejected_by_reason + coverage год/месяц, один Layer B синтез); врезка п.5: `_extract_chunk(..., window_rows, roster, stats)` → `provenance.local_evidence_to_source_refs` сразу после чанка (невалидный кандидат → не пишется; `_source_ref_ids`/`_author_name`); N-2: `_write_person_facts` в `_classify_chunked_user`; `_write_person_facts`: self_report/third_party по автору evidence-строки + EvidenceLink `derived_from` per SourceRef; `_format_window(..., desc_input=True)` (аддитивный kwarg); N-1 поддержка через `roster`.
3. `services/dossier_rebuild_jobs.py` — `paused` в `_ACTIVE_STATUSES` (неполный диапазон в очереди), `completed` в `_TERMINAL_STATUSES`; job-поля `mode/scope_kind/range_*/snapshot_boundary_*/cursor_*/extractor_version/kernel_version/attempt/reason_code/counters/coverage/generation_id`; `job_view` аддитивно (R17-safe: числа/коды, percent честный); reconcile (store + singleton): `paused` → `interrupted` при рестарте (cursor сохраняется); **`run_dossier_rebuild` dispatch**: master OFF → `_run_legacy` (байт-паритет ADR-1022-8) / ON → `_run_full_contract` (без confirmed-cleanup (D7), движок → честная финализация: budget → `paused`, staging → активация, отмена → `cancelled/interrupted` без деструктивного rollback, каскад); `_stage_and_activate` (backup_ref = `memory_backup.migration_backup` до активации); `_schedule_cascade` (по очереди: портреты `rebuild_dossier_for_chat` → vec-check (без перевекторизации) → `DreamWorker.run_once`); события `_emit_rebuild_event` (`dossier_rebuild` start+терминальный outcome) / `_emit_cascade_event` (`dossier_cascade`); **mca-17a-корреляция (T-3911)**: root-run `mt.start_run(db, pipeline_type="dossier.rebuild", root_job_id, attempt_id="job:attempt")` (durable `mca_pipeline_runs`), span-поля (`pipeline_run_id`/`span_id`/`attempt_id`/`checkpoint_ref`) в каждом событии через `mt.span_fields`, `mt.touch_run(checkpoint_ref=…)` на каждом checkpoint после фиксации, `mt.finish_run` на каждом терминальном исходе (`succeeded`/`partial` при paused/`failed`/`cancelled`/`interrupted`); retry/resume = новый `attempt_id` при том же `pipeline_run_id`-функции (новый run на новый запуск, `root_job_id` связывает).
4. `web/api/chat_lore.py` — `start_dossier_rebuild`: master ON → total от `count_range_messages` (полный диапазон), job `mode=full/scope_kind`; OFF → точный legacy-подсчёт; resume-on-paused (`_resume_paused_rebuild`: тот же job, attempt+1, cursor); cancel на paused-full → `cancelled` без rollback (staging ничего не удалял); read-time reconstruction `_reconstruct_missing_provenance` в `_dossier_payload` (≤5, fail-open). **Гейт `_require_chat`/`_is_global_admin` не менялся** (admin-only сохранён, confirm D14-блок ADR).
5. `services/provenance.py` — `resolve_subject_ref(..., roster=)`: N-1, имя вне ростера scope → `unresolved` без DB-скана (ложный `resolved` для одноимённого вне окна ≤500 устранён).
6. `services/mca_gates.py` — 7 kill-switch (KILL_SWITCHES + resolvers): `dossier_rebuild_enabled` (master), `dossier_background_pass_enabled`, `dossier_read_reconstruction_enabled` (инертен при §98), `dossier_reclassify_enabled`, `dossier_staging_activation_enabled`, `embedding_generation_activation_enabled`, `dossier_namespace_fingerprint_v2_enabled`; лимиты `dossier_batch_max_messages()` (500) / `dossier_direct_priority_enabled()` (ON).
7. `config/settings.py` — те же 7 ClassVar + `MCA_DOSSIER_BATCH_MAX_MESSAGES` / `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` (env-only, default ON; **Δ каталога = 0**, `param_catalog.py` вне diff).
8. `services/mca_events.py` — REASON_CODES +10: `dossier_rebuild_started, dossier_batch_processed, dossier_paused_budget, dossier_interrupted, dossier_partial_range, dossier_reclassified, dossier_staging_activated, dossier_generation_superseded, dossier_cascade_scheduled, dossier_identity_unresolved`.
9. `services/mca_process_registry.py` — `dossier.rebuild` v2: стадии `snapshot/extract/synthesize/activate/cascade/finalize`, widget `Досье/архив`, `event_names=("dossier_rebuild","dossier_cascade")` (оба реально эмитятся — регтест mca-17a зелёный), enabled_gate master.
10. `tools/history_import/loader.py` — L-MCA03-8: `_dataset_namespace` → `import:<tag>:v2:<content-digest>` при гейте ON (content-fingerprint: in-place регенерация того же размера больше не теряет source records; неизменённый файл — тот же namespace); OFF → прежний `import:<tag>:<digest>`; `legacy_import_v1` не переприсваивается.

**untracked (новые, мои):** `tests/test_mca04b_dossier_rebuild_round1027.py` (42 теста), `plans/features/mca-04b-dossier-rebuild/` (spec/ADR/tasks + этот evidence).

**unstaged modified (тесты, 19 — аддитивные правки под v20/разрешённые пути):** `test_mca01_tx_task_supervisor_round1027.py` (write-точки allowlist 129→137: +7 commit `_migrate_v20` L-MCA14-3 +1 `activate_embedding_generation` под `serialized()`, с комментарием по прецеденту); `test_mca04a_provenance_round1027.py`, `test_mca03_message_identity_round1027.py`, `test_mca07_retrieval_context_round1027.py`, `test_mca14…` (нет правок), `test_mca17a_observability_core_round1027.py` (пин `user_version` `==19` → `>=19`; хвост реестра продолжается v20); `test_graphrag_rebuild_asap32.py` (там же); legacy-migration пины `==19` → `>=19`: `test_database.py`, `test_graphrag_database.py`, `test_graph_facts_origin_v9.py`, `test_graph_scoring_round1018.py`, `test_history_migration_v7.py`, `test_memory_commands.py`, `test_memory_retention_round1019.py`, `test_agentic_ai_round1020.py`, `test_lore_compiler_round1020.py`, `test_webapp_round1020_ui.py`, `test_migrate_direct_chat_v2_script.py`, `test_migrate_epic60_v3_script.py`; `test_multilayer_extraction_round1021.py` (`contract_version==1` → `==2`, инвариант 10); bounds-allowlist `web/api/chat_lore.py` (санкция AMEND spec §4.9): `test_tool_coordinator_round1026.py`, `test_unified_image_request_round1026.py`.

## 2. Верификация (команды и фактические результаты)

| # | Команда | Результат |
|---|---|---|
| V1 | `.venv\Scripts\python.exe -m pytest tests/test_mca04b_dossier_rebuild_round1027.py -q` | **42 passed** (миграция v20, активация/идемпотентность, upsert-history, N-MCA07-1, namespace v2, N-1/N-3, движок A87/A89/отмена/нулевой-результат/collect, врезка SourceRef/self_report, N-2, раннер-состояния, legacy-паритет, наблюдаемость, A95, read-time, счётчики) |
| V2 | полный `pytest tests -q` | **10361 passed / 2 failed / ~4:57** — оба failed = `TestBounds::test_forbidden_paths_out_of_diff` + `TestBoundsA3` (**до-существовавшие**: дрейф git-тега `pre-round1026-a1` по путям `web/api/analytics.py`, `web/api/cover_styles.py`, `web/static/polygon-background.js`, `web/static/telegram-init.js`, закоммиченным чужими релизами AFTER тега; падали на baseline — journal ASAP-3.2 «pytest 10319/2»; к diff mca-04b не относятся) |
| V3 | `pytest tests/test_dossier_rebuild_round1022.py tests/test_mca14_schema_additive_round1027.py -q` | 60 passed (legacy-контракт F8 и реестр миграций не регрессировали) |
| V4 | `pytest tests/test_mca17a… tests/test_mca04a… tests/test_mca13… -q` | 127→ все passed после аддитивных пинов |
| V5 | `pytest tests/test_dossier_* tests/test_chat_lore* tests/test_lore_* tests/test_webapp_lore_ui.py -q` | 335 passed |
| V6 | `pytest tests/test_graphrag_rebuild_asap32.py tests/test_belief_decay.py tests/test_deep_sleep.py -q` | 77 passed |
| V7 | perf-скрипт (T-3909) | см. §4 |

**Браузерная верификация (spec §6.3 OPTIONAL):** UI-поверхность визуально не менялась (backend-поля job-view аддитивны; новых экранов/рендеринга нет) — структурный browser-check не выполнялся; решение за Reviewer (критерий: `processed` не показывается как `total` — `job_view`-тест покрывает контракт API-уровня).

## 3. Покрытие приёмок

| Приёмка | Где | Статус |
|---|---|---|
| **A87** (SC-01/03/06/07) | `test_a87_covers_full_range_beyond_window` (350 > окна 300; coverage 2022–2026; boundary/курсор; порции 100; без OFFSET), `test_collect_mode_returns_candidates`, `test_cancel_raises_and_writes_nothing` | ✅ |
| **A89** (SC-04/05/11) | `test_a89_budget_exhaustion_no_partial_synthesis` (paused-семантика движка + resume без дублей + checkpoint после фиксации), `test_budget_exhaustion_paused_never_completed` (percent 50≠100, cursor, find_active), `test_resume_passes_cursor_and_bumps_attempt`, `test_restart_marks_paused_interrupted`, `test_activation_failure_is_failed_not_destroying` | ✅ |
| **A90** (SC-10/12/13) | `TestStagingActivation` (5 тестов: apply+supersede, идемпотентный повтор, failed-переход, upsert-history, confirmed/overrides целы), `test_master_off_legacy_parity` | ✅ |
| **A85/A86/A88** (SC-08/16) | `test_evidence_invalid_dropped_and_sourcerefs` (row-bound верхняя граница + SourceRef + без выдуманных ссылок), `test_self_report_attribution` (self_report/third_party + EvidenceLink), `test_n2_person_facts_written_in_chunked_path`, `test_roster_bound_resolution_n1`, `test_guess_subject_determinism_pin_n3` | ✅ |
| **A95** (SC-14/15) | `TestA95Sample` (фиксированная выборка 10 сообщений 2022–2026/3 участника; включения/исключения зафиксированы ДО прогона; precision ≥0.99, recall-порог; негативные (прайс АЗС/этимология/квадрат/новость/пересылка) исключены; «да» не отброшен; охват отдельно; rejected_by_reason в отчёте) | ✅ (фикстурный контур; прод-выборка — GEN-R20 на релизе) |
| **A28** (SC-20) | `TestMigrationV20` (объекты/user_version/книга/idempotent/partial-UNIQUE-семантика/legacy-NULL) | ✅ |
| **A48/A27** (SC-19) | `TestObservability` (reason_code словарь, реестр v2 стадии/события, эмиссия start+outcome, job_view R17-safe) | ✅ |

## 4. Измерения (T-3909, D-MCA04A-7) — **оценка, не обещание**

Файл-БД, 300 фактов, один прогон (01.10.2026, рабочая машина):
- **0.75 мс/факт** — полный контур `insert_graph_fact` + `record_fact_provenance` (object SourceRef + status) + 1 EvidenceLink (каждый op — свой `write_transaction`);
- рост БД ≈ **2.8 КБ/факт** (включая саму строку факта);
- `local_evidence_to_source_refs` — 1 `resolve_source_ref` на evidence-номер (тот же порядок стоимости);
- **оценка полного прохода**: архив 100k сообщений → ~10k кандидатов (эмпирика Layer A) → ≈ 8 c суммарной provenance-записи + ≈ 28 МБ; доминирующая стоимость — LLM-вызовы (Layer A по чанкам 40 + 1 Layer B), не БД.

## 5. Deploy-заметки (Builder-часть T-3915; интеграция — `mca-release` @DevOps)

- **Migration smoke:** v20 на свежей БД, legacy-v19 → v20, повторный прогон no-op — покрыты тестами (V1 `TestMigrationV20`, V3). PG — no-op (`pg_db.py` вне diff, GEN-R4).
- **Config changes (manifest §20):** env-only, default ON — `MCA_DOSSIER_REBUILD_ENABLED`, `MCA_DOSSIER_BACKGROUND_PASS_ENABLED`, `MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED`, `MCA_DOSSIER_RECLASSIFY_ENABLED`, `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED`, `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`, `MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED`; лимиты `MCA_DOSSIER_BATCH_MAX_MESSAGES` (500), `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` (ON). Каталог/TSV не менялись (Δ=0).
- **Rollback:** hot — `MCA_DOSSIER_REBUILD_ENABLED=false` (legacy-раннер; частично активные под-гейты инертны при master OFF); cold — `git revert` → `4cb267a`; v20 аддитивна (совместимый откат кода оставляет данные: таблицы/колонка безвредны, legacy-путь их не читает); повторная активация предыдущего поколения + `memory_backup` (backup_ref) — точечный откат досье; restore БД — только аварийный сценарий (R18).
- **GEN-R20:** инспекция ID-заполненности/объёмов на прод-БД — на релизе (спецификация §18/§3; НЕ блокирует деплой).

## 6. Открытые пункты / границы честности

1. **`threat-failure-analysis.md` отсутствует** — обязателен при R3; зона T-3916 (@Reviewer/@Architect).
2. **CASCADE шаг «парадигмы»** идёт через существующий `DreamWorker.run_once` (глубокий сон — внутренний контур Dream; отдельного вызова deep-режима не добавлялось — второй контур запрещён GEN-R19). Reviewer: достаточность покрытия шага 4.
3. **`kernel_version="mca-04b/v1"`** — константа кода (версия правил деления/реклассификации); bump-механизма нет (вне scope санкции).
4. **Активация vec-поколения не вызывается автоматически** — операция готова+протестирована, гейт есть; фактическая перестройка несовместимого индекса — отдельный resumable job (§8.3 запрещает перевекторизацию без необходимости); auto-trigger сознательно отсутствует.
5. **Пины `== 19` → `>= 19`** в 13 legacy-тестах — аддитивные правки под продолжение реестра (прецедент: mca-17a делала то же с `== 18`); Reviewer может предпочесть явную фиксацию tail-константы.
6. **2 bounds-падения — до-существующие** (тег `pre-round1026-a1` vs закоммиченные пути чужих релизов); мои allowlist-правки добавляют только санкционированный `web/api/chat_lore.py`.
7. **Браузерная проверка** — OPTIONAL (spec §6.3), не выполнялась (визуальных изменений нет).
8. `dossier_reclassify_enabled`/`dossier_background_pass_enabled` резолвятся и respect-ятся в контуре (гейт-иерархия), но отдельной «ф sp-реклассификации старых confirmed» как авто-джоба нет — реклассификация выполняется перестройкой в staging (D7: авто-очистка запрещена). Reviewer: сверить со SC-10 трактовкой.

## 7. Continuity

Первоначальная сессия Builder, fallback не потребовался; частичного наследства от умершей сессии не было (worktree до старта содержал только чужие planning-правки — сохранены).

## 8. REWORK round 1 (01.10.2026) — H-1/H-2/M-1/M-2 из `review.md`

> Вердикт round 1: ❌ Needs Fixes (2 High blocking + M-2 blocker merge). Все четыре пункта закрыты; коммитов нет; полный pytest 10369/2 (оба failed — до-существующие bounds, см. §2 V2). База реворка: HEAD `486b3e9` + worktree до реворка (WTH review `4AECC673…F254`).

### 8.1. H-MCA04B-1 (High) — collect-mode resume терял кандидатов до курсора — ✅ ЗАКРЫТ

**Механика фикса (персистентация до паузы + seeding при resume + reuse поколения):**

| Где | Что изменено |
|---|---|
| `services/dossier_rebuild_jobs.py::_run_full_contract` (~`:806–830`) | при старте попытки читается `pending_generation_id` из job; в collect-режиме при resume (`cursor` есть) из building-поколения восстанавливаются staged-элементы → `_staged_items_to_candidates` → `resume_candidates` движка |
| `…::_run_full_contract` pause-ветка (`:945–995`) | `budget_exhausted`/`model_unavailable` → `_persist_pending_candidates(...)` **ДО** записи `paused`: кандидаты прерванного прогона укладываются в staging building-поколения (создаётся однократно, переиспользуется при повторных паузах); `generation_id` durable в job. Если кандидаты есть, а персистентация не удалась → честный `failed` (`error_code=pending_staging_failed`, `reason_code=dossier_pending_staging_failed`) — пауза молча теряла бы сегмент |
| `…::_persist_pending_candidates` (новая, `:1189–1265`) | resolve subject_ref → create/reuse generation (building) → insert staging items (payload как в `_stage_and_activate`; дедуп по ключу) → счётчики поколения (`set_dossier_generation_state`) |
| `…::_staged_items_to_candidates` / `_staging_dedup_key` / `_staging_payload` (новые, `:1130–1186`) | staged-элементы → кандидаты (`_restored`-маркер, `_source_ref_ids`/`_author_name` восстановлены); ключ дедупа `(kind, text.casefold(), target.casefold())` |
| `…::_stage_and_activate` (`:1243+`) | параметр `existing_generation_id`: building-поколение прошлой паузы **переиспользуется** (не создаётся второе); кандидаты с `_restored` пропускаются + дедуп по ключу; финальные counters_json + свежий backup_ref на поколении; активация прежняя атомарная |
| `services/lore_worker.py::rebuild_dossier_full` (`:921–1009`) | параметр `resume_candidates` — посев накопления ДО прохода: Layer B при resume синтезирует по **обоим** сегментам (портрет полного диапазона) |

**Тесты (новые):** `TestResumeCollectKeepsCandidates` — пауза на batch-границе (`MCA_DOSSIER_BATCH_MAX_MESSAGES=10`) → staging содержит кандидатов до курсора → resume → job `completed`, **то же** поколение `active`, в `graph_facts` по 1 экземпляру фактов **обоих** сегментов («факт чанка 1» до курсора + «факт чанка 2/3» после) + портрет поколения; дедуп без дублей. Seeding-тест (spy: `resume_candidates`/`resume_cursor` переданы движку). Pending-staging failure → `failed`, не молчаливая `paused`. Приёмка review («пауза на N, resume, кандидаты из обоих сегментов в финальном досье») — выполнена.

**Гранулярность (честно):** кандидаты фиксируются на границе **батча** (как checkpoint); при исчерпании бюджета внутри батча уже извлечённые чанки этого батча пере-извлекаются при resume (курсор = конец последнего завершённого батча; дедуп исключает дубли) — потерь нет, повторной записи нет.

### 8.2. H-MCA04B-2 (High) — LLM-сбои давали completed с нулём — ✅ ЗАКРЫТ

| Где | Что изменено |
|---|---|
| `services/lore_worker.py::_extract_chunk` (`:1469–1501`) | разделены `except ValueError` → `parse_error` и `except Exception` → `model_unavailable`; раздельные счётчики `parse_errors`/`model_errors` (+`rejected_by_reason`) |
| `…::_FULL_COUNTER_FIELDS` (`:254–262`) | + `model_errors`, `parse_errors` (разные единицы, инвариант 13) |
| `…::rebuild_dossier_full` финал (`:1111–1172`) | честные исходы: `extracted==0 ∧ model_errors>0` → `model_unavailable`; `extracted==0 ∧ parse_errors>0` → `failed`/`parse_error`; нулевой результат при **полном корректном** проходе (0 ошибок) — по-прежнему валидный `completed` (инвариант 14) |
| `…::_synthesize_full_candidates` (`:1268+`) | возврат `(written, portraits, memes, failure)`, `failure ∈ None|budget|model|parse`; бюджет/исключение/невалидный JSON Layer B больше не тихий пропуск |
| `…::rebuild_dossier_full` synth-ветка | Layer B budget в collect → `budget_exhausted`+`failed_stage="synthesize"` (paused+staging → resume повторяет синтез); в direct → `failed` (resume не восстановит набор накопления — paused дал бы silent partial); Layer B model → `model_unavailable` (collect)/`failed` (direct); Layer B parse → `failed`/`parse_error` |
| `services/dossier_rebuild_jobs.py::_run_full_contract` (`:941–1009`) | `status ∈ {budget_exhausted, model_unavailable}` → `paused` (retryable, спека §3.2) с reason_code из отчёта и `stage=failed_stage`; любой иной не-completed → `failed` с reason_code движка (не захардкоженный parse_error) |
| `services/mca_events.py` | `REASON_CODES` + `model_unavailable`, `parse_error` (спека §3.2 требовала их, в словаре их не было — комментарий был неточен), + `dossier_pending_staging_failed` |

**Тесты (новые):** проба B воспроизведена → `paused`+`model_unavailable`, 0 записей, курсор сохранён, процент честный (`test_model_unavailable_whole_pass_is_failed_not_completed`); проба C воспроизведена → `paused` c `stage=synthesize`, кандидаты персистентны, портрета нет, **не** completed/не silent partial; resume → синтез по полному набору → `completed` с портретом и фактами всех чанков (`test_budget_exhausted_at_synthesis_not_completed`); parse-errors-нулл → `failed`/`parse_error` (`test_zero_extract_with_parse_errors_not_completed`); direct-режим Layer B budget → `failed` (`test_direct_mode_layer_b_budget_is_failed_not_silent`).

**Дизайн-решение (для Reviewer):** `model_unavailable` маппится в job-`paused` (не failed) — спека §3.2 «paused/failed по retryability»: модель внизу retryable, курсор+staged кандидаты сохраняются для resume; инвариант оркестратора «interrupted/failed, НЕ completed» удовлетворён по сути (paused — различимый неуспех, `find_active` держит job в очереди). Consecutive-failure порог не введён (сознательно, «на усмотрение Builder»): правило `extracted==0 ∧ errors>0` + resume покрывает пробы B/C без риска ложных пауз на одиночных сбоях.

**Попутно:** 2 существующих теста молча опирались на H-2-баг (битый/чужой Layer-B payload тихо глотался → completed) — стабы заменены на role-aware (`_RoleLLM`); это эмпирическое подтверждение реальности находки.

### 8.3. M-MCA04B-2 (Medium, blocker merge) — threat-failure-analysis.md — ✅ ОФОРМЛЕН

`plans/features/mca-04b-dossier-rebuild/threat-failure-analysis.md` — substantive R3-анализ: границы доверия/активы, класс «нечестная финализация» (T-1…T-7 с контрмерами и тестами, включая реворк), отказы данных, конкуренция/ресурсы, R17, откат (включая последствия building-поколений), остаточные риски R-a…R-e. Основа — анализ Reviewer из review.md, приведён к состоянию после фиксов.

### 8.4. M-MCA04B-1 (Medium) — v2-digest больших файлов — ✅ УЛУЧШЕН

`tools/history_import/loader.py::_file_content_digest` — вместо «голова 256 KiB + size» — **полный стриминговый SHA-256** (порции 1 MiB, память не зависит от размера; префикс `v2full|size|`). Регенерация файла >256 KiB с идентичной головой и тем же размером больше не коллидирует; неизменённый файл — тот же namespace (дедуп работает). Формула меняется безопасно: v2-namespace существуют только в этом незакоммиченном worktree (фича `DEFERRED_TO_RELEASE`, прод-данных с v2 нет). Тест: `test_v2_full_digest_distinguishes_tail_beyond_head` (300+ KiB, одинаковая голова/размер, разные хвосты → разные namespace; неизменённый → тот же).

### 8.5. Верификация реворка (команды и факты)

| # | Команда | Результат |
|---|---|---|
| W1 | `pytest tests/test_mca04b_dossier_rebuild_round1027.py -q` | **50 passed** (42 до реворка + 8 новых: 3×H-1, 4×H-2, 1×M-2; обновлены `test_reason_codes_registered` +2+1 кода, стабы A89/A95 на `_RoleLLM`) |
| W2 | полный `pytest tests -q` | **10369 passed / 2 failed** (4:42) — оба failed = `TestBounds::test_forbidden_paths_out_of_diff` + `TestBoundsA3` (до-существующие, вне скоупа; база review: 10361/2; Δ+8 = новые тесты) |
| W3 | `pytest tests/test_dossier_rebuild_round1027.py tests/test_chat_lore.py tests/test_multilayer_extraction_round1021.py tests/test_mca04a_provenance_round1027.py tests/test_mca03_message_identity_round1027.py -q` | 165 passed (регрессии dossier/lore/provenance/identity) |
| W4 | `pytest tests/test_mca17a_observability_core_round1027.py tests/test_history_migration_v7.py tests/test_memory_commands.py tests/test_history_loader.py tests/test_mca14_schema_additive_round1027.py tests/test_mca01_tx_task_supervisor_round1027.py -q` | 205 passed (наблюдаемость/миграции/loader/write-механизм) |

### 8.6. Состояние worktree после реворка (binding для повторного ревью)

| Параметр | Факт |
|---|---|
| HEAD | `486b3e913db18811e4392c0a03b327663378bbbb` (не менялся) |
| Манифест | `git status --porcelain` по умолчанию: **48 записей** = 36 modified tracked (10 прод-файлов скоупа + config/settings.py + 20 правок тестов + 5 чужих plans-правок) + 7 untracked scope (тест-файл + 6 файлов `plans/features/mca-04b-dossier-rebuild/`, включая новый `threat-failure-analysis.md`) + 5 чужих untracked записью path+DIR (`.playwright-mcp/`, `extra_images/`, `node_modules/`, `package.json`, `package-lock.json`) |
| **WTH round 1** | `D41CD5232B108A620DF20A548A0AD200E6BEBDC3AFFD0C62CFA10403D584AE43` — SHA-256 детерминированного манифеста: строки `path<TAB>kind<TAB>sha256(content)` (kind ∈ M/A), чужие untracked — `path<TAB>DIR|FOREIGN<TAB>-`, сортировка по path; content-hash — SHA-256 байтов файла (UPPER hex). Внимание: алгоритм задокументирован здесь и **не байт-совместим** с манифестом review round 1 (та фиксация использовала счётчик записей 42; текущая — 48, включая новый артефакт) |
| Spec/ADR хэши | не менялись (`18DF2178…A3D2` / `0492EC24…EB24` — совпадают с пинами) |
| Спек-контракт | H-2 реализован в рамках spec §3.2/инварианта 2; new reason-коды — санкционированное расширение словаря §17.2; Δ DDL = 0 доп. (staging-персистентация — REUSE v20-таблиц), Δ каталога = 0 |

### 8.7. Открытые пункты после реворка (все non-blocking, из review round 1)

- **L1** `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` dead knob — не тронут (решение wired/убрать — до релиза, разрешение Reviewer).
- **L2** doc-формулировка `_is_global_admin` в spec §5.3 — @Architect (вне Builder-скоупа).
- **L3–L8** — без изменений (см. review.md «Non-blocking debt»).
- U-1…U-4 (browser OPTIONAL, планировщик режима 3, прод-выборка GEN-R20, PG-путь) — без изменений.
