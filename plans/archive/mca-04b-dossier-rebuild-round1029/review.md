# `mca-04b-dossier-rebuild` — Reviewer gate (T-3916, round 1) — 01.10.2026

- **Feature-ID:** `mca-04b-dossier-rebuild`
- **Risk-Level:** R3 (подтверждён: пересборка/реклассификация памяти, каскад, v20 меняет схему; эскалации не требуется — hot-path/vec-перестройка не затронуты, активация изолирована от LLM-вызовов)
- **Status:** ✅ **Approved for release** (round 2, 01.10.2026 — блокеры H-1/H-2 закрыты и независимо перепроверены по дельте; история round 1 «Needs Fixes» — ниже)
- **Reviewed-Commit:** `486b3e913db18811e4392c0a03b327663378bbbb` (HEAD; `bbdee1c` из постановки задачи — устаревший анкер, он ancestor текущего HEAD: между ними закоммичен полный релиз ASAP-3.2 `0483386` + docs; интеграционная кромка покрыта полным прогоном на объединённом дереве)
- **Working-Tree-Hash:** `4AECC673F8BC1789D378166E148711988F36BA9FFBE6732912E29124C1F34254` (SHA-256 детерминированного манифеста: 42 записи `git status --porcelain` = 33 modified tracked + untracked скоупа (тест-файл + plans/features/mca-04b…) с хэшами содержимого; чужие untracked каталоги `node_modules/`, `.playwright-mcp/`, `extra_images/`, `package*.json` — записью path+DIR, не хэшировались)
- **Spec-Hash:** `18DF21787EEF3462F79E9301A109F6D004E68F65730110EAE6F755CC28C5A3D2` ✅ совпадает с пином; **ADR-1027-9:** `0492EC240BABAF343E765B9525E3303E01654915FD473C4160E75A531E4CEB24` ✅; **tasks.md:** на диске `928ADEB31E519E767A15A41099A3EDE43529F86F3C045E1758F899312986C33A` — не совпадает ни с пином Orchestrator (`CB91E819…1699`), ни с до-Build пином `EF0C62BC…B56B5` в шапке tasks.md; tasks.md сам декларирует пересчёт своего хэша на Build-binding (Low L4 — repin на merge)

## Git base и объём просмотренных изменений

- **Base:** HEAD `486b3e9` (прод-код-коммит `4cb267a`/feat `0483386` = 2.58.40). **Незакоммиченный скоуп mca-04b:** 10 прод-файлов (`services/database.py` +699, `services/lore_worker.py` +585, `services/dossier_rebuild_jobs.py` +584, `web/api/chat_lore.py` +131, `services/mca_gates.py` +116, `config/settings.py` +41, `services/mca_process_registry.py` +37, `tools/history_import/loader.py` +42, `services/provenance.py` +17, `services/mca_events.py` +9) + новый `tests/test_mca04b_dossier_rebuild_round1027.py` (42 теста) + 18 аддитивных правок тестов (пины `==19`→`>=19`, bounds-allowlist `web/api/chat_lore.py`, `contract_version==2`) + docs фичи.
- **Чужой WIP вне скоупа** (не ревьюился, не тронут): `plans/docs/mca-round1027-*.md`, `plans/metrics.md`, `plans/workflow_state.md`; untracked `node_modules/`, `package.json`, `package-lock.json`, `.playwright-mcp/`, `extra_images/`.
- Просмотрены: полный diff 10 прод-файлов, ключевые тела (миграция/активация/движок/раннер/API/гейты/реестр/loader/provenance), diff-сравнение `_run_legacy` vs baseline `run_dossier_rebuild` (поведенчески идентичны — только сигнатура/комментарии), `git diff --name-only pre-round1026-a1 -- web/` (причина 2 bounds-падений), `git diff bbdee1c..HEAD` (объяснение смещения HEAD).

## Checks performed (команда → факт → вывод)

1. **Миграция v20** — `rg`/чтение `services/database.py:589–662, 1517, 2091–2129`: DDL байт-в-байт по spec §5.2 (2 таблицы, partial UNIQUE `idx_mca_dossier_gen_active`, nullable `graph_facts.dossier_generation_id`, 4 индекса); self-guard `sqlite_master`/`PRAGMA table_info`; шаг зарегистрирован в `MigrationStep` сразу после v19; `pg_db.py` вне diff (PG no-op, GEN-R4); `_SCHEMA_VERSION` = 21 в коде отсутствует (v21 свободна). Тесты `TestMigrationV20` на SQLite (объекты/user_version=20/книга `dossier_staging`/повторный init no-op/partial-UNIQUE-семантика/legacy-строки NULL) — **зелёные**. Rollback-compat: аддитивность, legacy-путь новые объекты не читает. **Вывод: соответствует SC-20/A28.**
2. **Субъект факта (§8.3.2)** — `provenance.resolve_subject_ref(..., roster=)`: имя вне ростера scope → `unresolved` без DB-скана (N-1, «старый» одноимённый вне окна ≤500 не даёт ложного resolved); субъект — `subject_ref_id` (устойчивый ID), не имя; `user_source_ref(..., resolution="unresolved")` — без выдуманных TG-id; имя ≠ объединение (`_eq_canon` — только для атрибуции авторства, не для склейки субъектов). Тесты `test_roster_bound_resolution_n1`, `test_roster_none_keeps_legacy_behavior`, `test_guess_subject_determinism_pin_n3` — зелёные. **Вывод: соответствует D6/N-1.**
3. **Layer B person_facts** — `_write_person_facts` (`lore_worker.py:1557–1650`): пишутся независимо от синтеза; `self_report` когда автор evidence-строки == target, иначе `third_party`; EvidenceLink `derived_from` per постоянный SourceRef; без единого валидного источника кандидат не пишется; статус `unconfirmed` (не повышается до confirmed); дедуп `person_fact_exists`. N-2: запись сразу после чанка в `_classify_chunked_user:1288–1297`. Тесты `test_self_report_attribution`, `test_n2_person_facts_written_in_chunked_path`, A95 third_party — зелёные. **Вывод: соответствует §8.3.2/A85/A86.**
4. **Full-rebuild** — `_KEYSET_PAGE_SQL`: keyset `(timestamp,id)` ASC, **без OFFSET**, верхняя граница = snapshot boundary; порции ≤ `MCA_DOSSIER_BATCH_MAX_MESSAGES` (500) с делением на чанки; checkpoint-callback строго после дискового артефакта+записи; budget exhaustion → возврат `budget_exhausted` с курсором **без частичного синтеза** (Layer A путь — эмпирически подтверждено); `progress от count_range_messages` (полный диапазон, `UI "all" → window_hours=0 → scope_kind=full`); 1 batch/чат — через кросс-процессный chat-lock (`chat_lore.py:1183`). Тесты A87 (350>окна, coverage 2022–2026), A89, cancel, empty-range-нулевой-результат, resume+attempt — зелёные. **Вывод: контракт соответствует; НО найдены High-1/High-2 (ниже).**
5. **Staging+атомарная активация** — `activate_dossier_generation` (`database.py:2309–2519`): одна короткая `write_transaction` (commit/rollback под single-writer lock, проверено тело `write_transaction:1256+`); идемпотентный повтор на `active` — no-op; prev active → `superseded` (строки не удаляются); person_fact вставляется `unconfirmed`, дедуп; meme дедуп; портрет — in-place UPDATE с историей в meta; `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED=OFF` → direct-запись (паритет). Backup **до** активации: `memory_backup.migration_backup` в `_stage_and_activate:1040–1048` → `backup_ref`. Legacy cleanup `cleanup_confirmed_dossier_facts` — **только** в `_run_legacy` (master OFF); в full-контракте отсутствует (D7 соблюдено). Тесты `TestStagingActivation` (5), `test_activation_failure_is_failed_not_destroying`, `test_master_off_legacy_parity` — зелёные. **Вывод: соответствует SC-12/D7/A90.**
6. **Портрет** — `upsert_generated_dossier` FIX (`database.py:7484–7568`): `previous_text` + bounded `portrait_history` (последние 4×400 симв.) в `belief_meta`, `contract_version=2`; накопленные `unconfirmed`-факты функцией не трогаются; FTS reindex корректный. Тест `test_upsert_portrait_keeps_history` — зелёный. **Вывод: инвариант 10 закрыт** (ограниченность истории 4 записей — Low L5, rollback через backup+реактивацию компенсирует).
7. **Provenance** — врезка п.5: `_extract_chunk(..., window_rows, roster, stats)` → `provenance.local_evidence_to_source_refs` **сразу после чанка**, каждый чанк — свой `window_rows` (одинаковый локальный номер ≠ один источник); невалидный кандидат → `rejected_by_reason["evidence_invalid"]`, не пишется. Read-time: `_reconstruct_missing_provenance` в `_dossier_payload` — bounded ≤5 (`facts_without_evidence_links` SQL LIMIT=20→фильтр), fail-open, гейт `dossier_read_reconstruction_enabled` (инертен при §98). Тесты `test_evidence_invalid_dropped_and_sourcerefs`, `test_facts_without_evidence_links_bounded`, `test_reconstruction_gated` — зелёные. **Вывод: SC-08/D-MCA04A-2 закрыты.**
8. **Observability** — `mca_process_registry.py`: `dossier.rebuild` **v2** (стадии snapshot/extract/synthesize/activate/cascade/finalize, stages_to_events, event_names оба реально эмитятся, enabled_gate master); `mca_events.REASON_CODES` **+10** dossier_*; события `_emit_rebuild_event` (start+терминальный outcome, reason_code, span-поля через ALLOWED_FIELDS) + `dossier_cascade`; mca-17a-корреляция: durable `mt.start_run` → `mt.touch_run(checkpoint_ref)` на каждом checkpoint → `mt.finish_run` с честными исходами (`partial` при paused). `job_view` аддитивен, R17-safe, percent честный (`min(processed,total)`, на paused <100). Тесты `TestObservability` — зелёные. **Вывод: SC-19/T-3910/3911 закрыты.**
9. **Kill-switches** — 7 имён + 2 env-лимита в `config/settings.py` (env-only ClassVar, default ON) + resolvers `mca_gates.py:400–479` с инертностью (`background_pass`/`reclassify`/`staging_activation` при master OFF → False; `read_reconstruction` инертен при `MCA_EVIDENCE_RECONSTRUCTION_ENABLED=OFF`); master OFF → `_run_legacy` — поведенческий паритет baseline подтверждён диффом и тестами (`test_master_off_legacy_parity`, `test_engineless_worker_falls_back_to_legacy`). **Low L1:** `dossier_direct_priority_enabled` объявлен, но нигде не читается (приоритет direct достигнут неявно — background LLM-роль, HTTP не блокируется). **Вывод: SC-20/D13 соответствует** (L1 — косметика).
10. **Carry-over** — N-1 ✓ (п.2), N-2 ✓ (п.3), N-3 ✓ (пин-тест), L-MCA03-8: `_dataset_namespace` → `import:<tag>:v2:<content-digest>` при гейте ON, `legacy_import_v1` не переприсваивается, OFF → v1-паритет; тесты `TestNamespaceFingerprintV2` — зелёные. **Medium M-1:** v2-digest = голова 256 KiB + size — регенерация большого файла (>256 KiB) с идентичной головой и тем же размером всё ещё коллидит (см. ниже). N-MCA07-1: `activate_embedding_generation` под `serialized()`, A06 не нарушен (ensure no-op при active), auto-trigger сознательно отсутствует (§8.3 запрещает перевекторизацию без необходимости) — операция + 2 теста зелёные.
11. **Открытые пункты** — `threat-failure-analysis.md` **отсутствует** (проверено `Test-Path`); substantive threat/failure-анализ R3 выполнен Reviewer в разделе ниже; артефакт обязателен до merge (M-2). GEN-R20-инспекция прод-БД — по spec на `mca-release`, деплой не блокирует (не finding).
12. **Прогоны (воспроизведены Reviewer независимо):** новый файл **42/42 passed** (4.9s); **полный pytest: 10361 passed / 2 failed** (288s) — совпадает с заявкой Builder; оба failed = `TestBounds::test_forbidden_paths_out_of_diff` + `TestBoundsA3` — **до-существующие, вне скоупа**: дифф против тега `pre-round1026-a1` содержит чужие закоммиченные пути (`web/api/analytics.py`, `web/api/cover_styles.py`, `web/static/polygon-background.js`, `web/static/telegram-init.js` — релизы EXTRA/ASAP); незакоммиченный скоуп mca-04b добавляет в web/ только allowlisted `chat_lore.py`; `-k "summary or a87 or a89 or a95"` → 4 passed.
13. **Staging-перечень для DevOps** — раздел ниже (вход в T-3915/mca-release).

## Requirement/evidence coverage (SC-01…SC-20)

| SC | Статус | Основание |
|---|---|---|
| SC-01/03 | ✅ (контракт) | A87-тест, keyset/boundary/count_range, coverage по годам; UI "all"→full |
| SC-02 | ✅ | режим 1: инкрементальный live (legacy-путь+full), режим 2: read-time reconstruction (bounded 5, гейт), режим 3: фоновый проход через job-раннер; гейт `dossier_background_pass_enabled` (резолвится/уважается; отдельного планировщика фонового запуска нет — см. Unavailable U-2) |
| SC-04/05/11 | ⚠️ частично | states/checkpoint/resume — да; **H-2** (LLM-сбои → completed) нарушает инвариант 2 |
| SC-06/07 | ✅ | backlog-артефакты fsync per batch, 1 Layer B синтез, ≤500, чат-lock; candidates — отфильтрованное подмножество, не весь архив |
| SC-08/16 | ✅ | врезка п.5, row-bound, N-1/N-2/N-3, L-MCA03-8 (M-1 — полнота digest, non-blocking) |
| SC-09 | ⚠️ | direct не блокируется структурно (background role, chat-lock не в hot-path); гейт приоритета — dead knob (L1) |
| SC-10 | ✅ | confirmed не очищаются (cleanup только в legacy), unknown/quarantine через unconfirmed+staging, ручные правки/overrides целы (тест) |
| SC-12/13 | ⚠️ | активация атомарна/идемпотентна, backup до активации, старые факты целы; **H-1** (потеря кандидатов при paused→resume в collect-режиме — дефолтная конфигурация); каскад по очереди (парадигмы — через внутренний контур Dream, L6) |
| SC-14/15 | ✅ (фикстурный контур) | A95: выборка/ожидания до прогона, precision/recall отдельно от coverage, негативные исключены, «да» не отброшен; прод-выборка — GEN-R20 на релизе (по spec) |
| SC-17 | ✅ | REUSE-карта соблюдена: второй движок/store/TaskSupervisor/write-механизм не созданы (проверено по diff) |
| SC-18 | ⏳ deferred | GEN-R20 → `mca-release` (по spec §8, не блокирует) |
| SC-19 | ✅ | п.8 |
| SC-20 | ✅ | п.1/9 |

Приёмки: A87 ✅, A89 ⚠️ (H-1/H-2), A90 ✅, A85/A86/A88 ✅, A95 ✅ (фикстуры), A28 ✅, A27/A48 ✅.

## Focused audit coverage

Изменённые файлы и их критические зависимости просмотрены целиком: транзакционные границы активации; владение lock'ом при resume (release в finally раннера; 503 fail-closed с сохранением paused); гонка отмены между последним batch и finalize (перепроверка cancel → не completed); reconcile paused→interrupted при рестарте (курсор сохраняется, reason dossier_interrupted); retention job-store (активные не вытесняются); FTS-consistency при портретном UPDATE (DELETE+INSERT внутри транзакции); SQL — все новые запросы параметизованы (инъекций нет); R17 — в события/job_view/logs идут только id/коды/числа (проверено эмиссию и job_view); `subject_ref_id or 0` fallback при недоступном provenance-реестре (cosmetic); `insert_dossier_staging_item` R17-safe payload.

## Counterexamples checked (негативные сценарии, эмпирика Reviewer)

Скрипт-проба вне репо (temp), SQLite + реальные движок/раннер-пути:
1. **A — paused→resume в collect-режиме (staging ON, дефолт):** прогон 1 → `budget_exhausted`, `candidates=1`, курсор (ts,id)=(msg10); прогон 2 с resume → `completed`, `candidates=0`; **кандидаты до курсора потеряны** (не в отчёте resume, не в БД, backlog-артефакт хранит только счётчики). → **H-1**.
2. **B — модель недоступна весь проход:** `_layer_a_call` raise на каждом чанке → fail-open `[],[]` → движок вернул **`completed`**, errors=3, reason_code=None. → **H-2a**.
3. **C — budget exhaustion на Layer B:** Layer A успех (written=1), синтез тихо пропущен → **`completed`**, portraits=0, reason_code=None. → **H-2b**.
4. Миграция на re-init (no-op), повторная активация (no-op), master OFF (legacy parity), empty range (completed 0 — валиден), cancel (ничего не пишет) — покрыты тестами Builder, повторно не воспроизводились (контрактные тесты предметны).

## Threat/failure analysis (R3, substantive)

- **Границы доверия:** запуск пересборки — аутентифицированный TMA-юзер; авторизация — `_require_chat` (членство в чате) как в baseline; `_is_global_admin` на dossier-эндпоинтах в baseline отсутствовал (L2 — нет ослабления, но doc-заявка spec §5.3 неточна). SQL-инъекции: нет (параметризация). Секреты: не логируются (проверено), SourceRef вместо сырого контекста.
- **Отказы данных:** реклассификация без удаления (staging-only, D7) — потеря накопленного исключена на активационном пути; активация атомарна (write_transaction+rollback под lock); сбой активации → failed без деструкции (тест). Остаточные риски: **H-1** (тихая неполнота generation после resume), **H-2** (ложный completed при сбоях LLM) — именно они эксплуатируют класс «нечестная финализация», ради которого фича создавалась.
- **Конкуренция/ресурсы:** single-writer (write_transaction/serialized) + кросс-процессный chat-lock; порции ≤500; LLM-вызовы вне транзакций (MCA14-R3 соблюдено); OOM-профиль — потоковый keyset, кандидаты — отфильтрованное подмножество.
- **Откат:** hot — master OFF (legacy-раннер); cold — git revert → `4cb267a`; v20 аддитивна (объекты безвредны для старого кода); backup_ref до активации + повторная активация предыдущего поколения; restore БД — аварийный (R18).
- **Вывод:** архитектурная изоляция активации от hot-path доказана; понижение R3 не инициирую. Блокеры — H-1/H-2, не архитектура.

## Blocking findings

### [H-MCA04B-1] [High] OPEN — collect-mode resume теряет кандидатов до курсора (дефолтная конфигурация)
- **Где:** `services/lore_worker.py::rebuild_dossier_full` (budget-выход: `collected` уходит в отчёт и сбрасывается; resume начинает `collected` пустым с курсора) + `services/dossier_rebuild_jobs.py::_run_full_contract` (ветка `budget_exhausted:921–936` не персистит `report["candidates"]`; backlog-артефакт `_write_batch_artifact` хранит только счётчики).
- **Требование:** SC-05 (идемпотентный resume/продолжение с checkpoint), инвариант 4, A89 («продолжение без потерь»), ТЗ §8.3 `:244` (checkpoint/повтор после сбоя).
- **Evidence:** проба A (выше); `test_resume_passes_cursor_and_bumps_attempt` — на моке `_FullContractWorker`, collect-ветку не покрывает; `test_a89…` — только direct-режим.
- **Impact:** при `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED=ON` (default) пауза по бюджету + resume → активированное поколение молча не содержит извлечённых фактов/мемов всех батчей до курсора; job завершается `completed` как полный проход.
- **Исправление:** персистить кандидаты прерванного прогона (в staging под job_id или в backlog-артефакт с содержимым) и до- stage'ить при resume; либо при budget-выходе возвращать курсор на начало **первого незавершённого** батча с reprocess и direct-записью. + интеграционный тест resume в collect-режиме.
- **Проверка после фикса:** collect-resume тест: сумма кандидатов (r1.pre-cursor ∪ r2) == полный проход; активированное поколение содержит факты обоих диапазонов.

### [H-MCA04B-2] [High] OPEN — LLM-сбои не дают честной финализации (нарушен инвариант 2 «нарушение = НЕ принято»)
- **Где:** `services/lore_worker.py::_extract_chunk:1372–1384` (любое исключение Layer A → fail-open `[],[]`, модель-недоступность неотличима от parse_error); `_synthesize_full_candidates:1170–1197` (budget fail Layer B — тихий `return 0,[],[]` без статуса/счётчика; exception path тоже не меняет статус); движок возвращает `completed`; раннер доверяет `report["status"]`.
- **Требование:** spec §3.3 инвариант 2 («budget exhaustion, недоступность модели, parse error… никогда не дают completed»), spec §3.2 (строки 2 и 6 таблицы отказов: недоступность модели → paused/failed; сбой Layer B → job не completed), ТЗ §8.3.3 `:290` verbatim.
- **Evidence:** пробы B и C (выше).
- **Impact:** падение модели на время прохода → «успешная» пересборка с 0 извлечений (errors=N виден только в counters); сбой/бюджет на финальном синтезе → completed без портрета; пользователь/наблюдаемость получают ложный сигнал успеха — ровно класс «ложный done», который фича обязана устранить.
- **Исправление:** (a) различать `model_unavailable` (сетевые/5xx/timeout от `llm_client`) и `parse_error`; (b) правило честности: `errors>0 ∧ accepted==0` → `budget_exhausted`/`failed` (не completed); consecutive-failure порог — на усмотрение Builder; (c) budget/exception на Layer B → статус `budget_exhausted`/`failed` с `failed_stage="synthesize"` (портрет не обязателен для завершения — тогда явно частичный исход); + тесты на оба случая.
- **Проверка после фикса:** воспроизведение проб B/C через новые тесты → статус ≠ completed, reason_code заполнен.

## Non-blocking debt

- **[M-MCA04B-1] [Medium]** L-MCA03-8 v2-digest — только голова 256 KiB + size: in-place регенерация файла >256 KiB с идентичной головой и тем же размером сохраняет коллизию → source records по-прежнему молча теряются. SC-16 (формат/не-переприсвоение) выполнен; «устранить пропуск» выполнено частично. Фикс тривиален (полный стриминговый хэш при импорте). Follow-up до релиза.
- **[M-MCA04B-2] [Medium, блокер merge T-3916]** артефакт `threat-failure-analysis.md` отсутствует (spec §7: «обязателен (R3)»). Содержательный анализ выполнен в этом review (раздел выше); файл должен быть извлечён/оформлен до Merge §107+/ADR Accepted.
- **[L1]** `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` — dead knob (объявлен, не читается); wire либо убрать из release-манифеста.
- **[L2, doc]** spec/ADR §5.3/Confirm: «`_is_global_admin` … сохраняется на всех AMEND-путях (запуск пересборки/чтение статусов)» не соответствует коду — dossier-эндпоинты прикрыты `_require_chat` (членство), admin-гейт в baseline на них отсутствовал; ослабления нет (паритет), но doc-формулировку уточнить @Architect.
- **[L3]** `counters["accepted"] += selected` — «принято» приравнено к «отобрано» до дедупа/записи; инвариант 13 («разные единицы») соблюдён по полям, но семантика accepted грубая.
- **[L4]** tasks.md hash drift (см. шапку): repin на merge; Orchestrator-пин `CB91E819…1699` не валиден ни для одной версии файла.
- **[L5]** портретная история в meta ограничена 4×400 симв. — «прежняя версия доступна» для портрета обеспечивается вторично (staged items + backup_ref + реактивация); принять как дизайн или расширить history.
- **[L6]** шаг каскада «парадигмы» — через `DreamWorker.run_once` (deep-сон внутри контура Dream); отдельного вызова нет (GEN-R19-совместимо, задокументировано Builder'ом).
- **[L7]** evidence.md «9 прод-файлов», фактически 10 (с `config/settings.py`) — косметика.
- **[L8]** `subject_ref_id=int(subject_ref_id or 0)` fallback в `_stage_and_activate` — при сбое provenance-реестра поколение регистрируется с subject_ref_id=0 (не NULL); косметика против «честного unknown».

## Unavailable checks

- **U-1:** Browser-Verification — OPTIONAL по spec §6.3; UI-рендеринг не менялся (job-view поля аддитивны), критерий «processed ≠ total» покрыт API-контрактом (`job_view`-тест). Незачем эскалировать.
- **U-2:** фактический **планировщик** фонового прохода (режим 3 как автозапуск по расписанию) — гейт `dossier_background_pass_enabled` резолвится, но внешнего триггера в diff нет; проход инициируется существующими запусками пересборки (UI/CLI). Трактовка «режим 3 включён» — через resumable-проход раннера; если владелец ожидает крон-автозапуск — это пробел режима 3, уточнить на mca-release.
- **U-3:** прод-выборка A95, скорость/стоимость полного прохода на прод-объёмах, GEN-R20-инспекция — `mca-release` (по spec, честная оценка в evidence §4).
- **U-4:** PG-путь активаций (pg-вариант `write_transaction`) не прогонялся — PG вне diff по санкции (GEN-R4); SQLite-only тесты.

## Staging-перечень для DevOps (вход T-3915 / mca-release)

1. **Миграция:** v20 на свежей БД и на копии прод (v19→v20); повторный прогон — no-op; проверить книгу `schema_migrations` (ровно одна строка `20/dossier_staging`), 4 индекса, nullable `graph_facts.dossier_generation_id`; VACUUM INTO бэкап до миграции (прецедент волны §93–§100).
2. **Config (env, default ON, все задокументировать в manifest §20):** `MCA_DOSSIER_REBUILD_ENABLED`, `MCA_DOSSIER_BACKGROUND_PASS_ENABLED`, `MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED`, `MCA_DOSSIER_RECLASSIFY_ENABLED`, `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED`, `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`, `MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED`; лимиты `MCA_DOSSIER_BATCH_MAX_MESSAGES=500`, `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` (см. L1 — до релиза решить wired/убрать).
3. **Smoke после деплоя:** запуск пересборки периода «all» на одном чате → job `mode=full`, percent от полного диапазона; исчерпание бюджета → `paused` (не done); cancel paused-full → `cancelled` без rollback; события `dossier_rebuild`/`dossier_cascade` в витрине mca-17a.
4. **Kill-switch drill:** master OFF на дежурном чате → legacy-раннер (cleanup+done как baseline) — проверка отката.
5. **GEN-R20:** инспекция ID-заполненности/объёмов архива на прод-БД; измерение скорости/стоимости на разнообразной выборке (оценка, не обещание) — по spec не блокирует деплой.
6. **Откат:** hot — env OFF (под-гейты инертны); cold — revert → `4cb267a`; v20 аддитивна (старый код новые объекты не читает); точечный откат досье — backup_ref + реактивация предыдущего поколения.

## Binding

- Настоящий вердикт действителен только для состояния: HEAD `486b3e913db18811e4392c0a03b327663378bbbb` + worktree с WTH `4AECC673F8BC1789D378166E148711988F36BA9FFBE6732912E29124C1F34254` + Spec `18DF2178…A3D2`. Любое изменение кода/спеки/релевантных untracked-файлов инвалидирует binding; повторное ревью — по дельте фиксов H-1/H-2 (+M-2 артефакт до merge).
- Файлы-якоря: spec/ADR хэши совпали; `plans/current_task.md` не изменялся (заявка Builder; файл в чужих правках не замечен — в `git status` отсутствует).

**Итог счётчиков:** Critical 0 · High 2 (блокирующие) · Medium 2 (M-1 non-blocking; M-2 блокер merge) · Low 8 · недоступные проверки 4 (все — deferred/N-A по spec).

---

# Round 2 (01.10.2026) — дельта-ревалидация реворка H-1/H-2 + M-1/M-2 — ✅ Approved for release

- **Feature-ID:** `mca-04b-dossier-rebuild`
- **Risk-Level:** R3 (без изменений; реворк не расширяет поверхность — персистентация в существующие v20-таблицы, reason-коды в существующий словарь, Δ DDL = 0 доп., Δ каталога = 0)
- **Status:** ✅ **Approved for release** (blocking 0)
- **Reviewed-Commit:** `486b3e913db18811e4392c0a03b327663378bbbb` (HEAD не менялся с round 1)
- **Working-Tree-Hash (recalculated, round 2):** **`B790BE30846034D87AF20646C17F4166ED4902CA224CE019352E292B7C7A6B9F`** — 48 записей по алгоритму evidence §8.6 (`path<TAB>kind<TAB>sha256`, kind M/A, чужие untracked `DIR|FOREIGN` с `-`, сортировка по path, LF-джойн без хвостового `\n`); вариант с хвостовым `\n` — `1FE69BDDD2807362252A18B8D9E7ABC477ADE7D734E267B765990E1B25623088`. Структура манифеста сверена: ровно 36 M + 7 A + 3 DIR + 2 FOREIGN.
- **Spec-Hash:** `18DF21787EEF3462F79E9301A109F6D004E68F65730110EAE6F755CC28C5A3D2` ✅ (пересчитан — байт-идентичен пину); **ADR-1027-9:** `0492EC240BABAF343E765B9525E3303E01654915FD473C4160E75A531E4CEB24` ✅ (пересчитан). tasks.md изменился после round-1-хэша (`928ADEB…` → актуальный в манифесте) — L4 (repin на merge) остаётся открытым.

## Git base и объём изменений round 2

Base тот же: HEAD `486b3e9` + незакоммиченный скоуп mca-04b. Дельта round 2 = только правки реворка в уже просмотренных файлах: `services/dossier_rebuild_jobs.py` (persist-before-pause `:945–995`, resume-seeding `:806–824`, `_staged_items_to_candidates`/`_persist_pending_candidates`/`_stage_and_activate(existing_generation_id)` `:1092–1333+`), `services/lore_worker.py` (`resume_candidates` `:930,1006–1009`; честная финализация `:1113–1180`; `_full_report`; `_synthesize_full_candidates` failure-tuple `:1230–1300+`; `_extract_chunk` разделение `:1477–1509`), `services/mca_events.py` (reason-коды `model_unavailable`/`parse_error` `:111–113`, `dossier_pending_staging_failed` `:122`; счётчики `:260`), `tools/history_import/loader.py` (`_file_content_digest` `:94–116`), новый `tests/test_mca04b_dossier_rebuild_round1027.py` (+8 тестов реворка, всего 50) и docs фичи (`threat-failure-analysis.md` — новый; evidence §8). Чужой WIP не тронут. Манифест-дрифт: `plans/workflow_state.md` (чужой, 14:33:36) и `tasks.md` (14:30:16) изменены ПОСЛЕ записи WTH Builder'ом (evidence, 14:29:48) — код-файлы (14:01–14:17) все ДО; это объясняет невоспроизводимость Builder-хэша `D41CD5232B108A620DF20A548A0AD200E6BEBDC3AFFD0C62CFA10403D584AE43` на текущем дереве (см. N-R2-1), код не затронут.

## Checks performed (round 2)

1. **H-1 (collect-resume без потерь) — код:** (a) pause-ветка `budget_exhausted`/`model_unavailable` при staging ON вызывает `_persist_pending_candidates` ДО записи `paused` (`dossier_rebuild_jobs.py:955–995`); создание building-поколения однократно, переиспользование по `pending_generation_id`, дедуп по `(kind, text.casefold(), target.casefold())`; при кандидатах + неудавшейся персистентации — честный `failed`/`pending_staging_failed` вместо молчаливой паузы (`:962–979`); (b) при старте попытки job читает `generation_id` и при resume-курсоре сеет staged-элементы через `_staged_items_to_candidates` → `resume_candidates` (`:806–824`); портреты сознательно не сеются (синтез повторяется); (c) движок сеет кандидатов в накопление ДО прохода (`lore_worker.py:1006–1009`) — Layer B при resume синтезирует по обоим сегментам; (d) finalize переиспользует то же building-поколение (`_stage_and_activate(existing_generation_id=…)`, пропуск `_restored` + дедуп `:1286–1316`), активация обоих сегментов одним поколением. Гранулярность «батч-граница; чанк внутри прерванного батча пере-извлекается, дедуп исключает дубль» — подтверждена чтением пути и тестом.
   **H-1 — тесты:** `TestResumeCollectKeepsCandidates` 3/3 passed (pause→staging до курсора→resume→`completed`, то же поколение `active`, факты обоих сегментов в `graph_facts` по 1 экземпляру; spy seeding; pending-staging failure → `failed`).
2. **H-2 (честная финализация) — код:** `_extract_chunk` разделяет `ValueError`→`parse_error` и прочее→`model_unavailable` с раздельными счётчиками `parse_errors`/`model_errors` (`lore_worker.py:1477–1509`, `_FULL_COUNTER_FIELDS:260`); правила движка `:1117–1134`: `extracted==0 ∧ model_errors>0` → `model_unavailable` (extract), `extracted==0 ∧ parse>0` → `failed`/`parse_error`, ноль при полном корректном проходе (0 ошибок) — валидный `completed` (инвариант 14); Layer B — failure-tuple `None|budget|model|parse` (`:1240+`), маппинг `:1145–1173`: бюджет в collect → `budget_exhausted`+`failed_stage="synthesize"` (пауза + персистентация кандидатов → resume повторяет синтез), в direct → честный терминальный `failed`; model/parse — аналогично; раннер `:941–1009` маппит честно (не-completed никогда не завершает job успешно; reason_code — от движка, не хардкод). REASON_CODES дополнены (`mca_events.py:111–122`) — санкционированное расширение словаря §17.2.
   **H-2 — тесты:** `TestHonestFinalization` 4/4 passed — пробы B и C из round 1 воспроизведены и теперь дают `paused`/`failed` с заполненными reason_code (`model_unavailable_whole_pass…`, `budget_exhausted_at_synthesis…`, `zero_extract_with_parse_errors…`, `direct_mode_layer_b_budget…`).
3. **M-1:** `threat-failure-analysis.md` оформлен и substantive: границы доверия/активы, класс «нечестная финализация» T-1…T-7 с контрмерами и тест-привязками, отказы данных, конкуренция/ресурсы, R17, откат (включая последствия building-поколений), остаточные риски R-a…R-e, binding-оговорка. Блокер merge снят.
4. **M-2:** `loader.py::_file_content_digest` — полный стриминговый SHA-256 порциями 1 MiB, префикс `v2full|size|`, fallback при OSError; безопасность смены формулы обоснована (v2-namespace существуют только в незакоммиченном worktree, прод-данных с v2 нет — фича DEFERRED_TO_RELEASE). Тест `test_v2_full_digest_distinguishes_tail_beyond_head` — зелёный (в составе файла 50/50).
5. **Прогоны (независимо воспроизведены Reviewer на текущем дереве):** целевые классы 7/7; файл фичи **50 passed**; **полный pytest: 10369 passed / 2 failed** (4:39) — оба failed = `TestBounds::test_forbidden_paths_out_of_diff` + `TestBoundsA3` (те же до-существующие чужие bounds-дрейфы, что в round 1 — вне скоупа); **EXTRA-набор: 150 passed / 0 failed** (заявка задачи «149» — заниженная цифра; фактическая коллекция 150, все зелёные); **JS: 52/52 passed** + `node --check web/app.js` exit 0; **F8 `--check`: CHECK OK (реестр 488, Δ каталога = 0), exit 0**.
6. **WTH:** пересчитан независимо (см. шапку round 2); структура 48 записей сверена поэлементно.

## Requirement/evidence coverage (дельта к round 1)

- SC-04/05/11: ⚠️→✅ — H-2 закрыт (инвариант 2 соблюдён на всех воспроизводимых путях; частичные сбои с extracted>0 → ошибки видимы в счётчиках — принятый residual R-a, задокументирован в threat-анализе §6).
- SC-12/13: ⚠️→✅ — H-1 закрыт (resume в дефолтной collect-конфигурации не теряет кандидатов до курсора; оба сегмента активируются одним поколением атомарно).
- Приёмка A89: ⚠️→✅ (paused-семантика + resume без потерь + честные исходы — тесты round 2).
- Остальное — без изменений к round 1 (SC-18/GEN-R20 — deferred на релиз; SC-02/режим 3 — U-2).

## Focused audit coverage (round 2, дельта)

Транзакционные границы персистентации кандидатов (insert в staging — короткие записи; дедуп-ключи регистрозависимо-нормализованы casefold — коллизий юникода не создаёт); владение `pending_generation_id` при повторных паузах (generation остаётся building; переиспользование валидирует state=='building'); отказ `_resolve_dossier_subject_ref` → subject_ref_id=0 (унаследованный L8, non-blocking); отсутствие двойной активации (`_restored`-фильтр + дедуп в `_persist_pending_candidates` И `_stage_and_activate`); direct-режим при staging OFF не персистит кандидатов (паритет; честный failed на Layer B-бюджете — R-c); reason-коды в mca-13 словаре; R17: в staging `payload_json` — только производные текст/атрибуция (без сырого контекста), в job-view/события — числа/коды.

## Counterexamples checked (round 2)

- Повторная пауза после resume (кандидаты r2 персистятся в то же поколение, дедуп; tested pause→resume→pause→resume в рамках сценария теста бюджет-исчерпания на синтезе).
- Пауза на synth-стадии: кандидаты в отчёте (`collect_candidates = collected`) → персистятся → resume синтезирует заново по полному набору (test_budget_exhausted_at_synthesis…).
- Persist-сбой при непустых кандидатах → `failed`/`pending_staging_failed`, не paused (test_pending_staging_failure…).
- Весь проход с моделью вниз → `paused`/`model_unavailable`, курсор сохранён, percent честный (test_model_unavailable_whole_pass…).
- Full-suite на объединённом дереве (посторонние релизы ASAP-3.2/EXTRA в worktree) — 10369/2 known — регрессий чужих контуров нет.

## Blocking findings (round 2)

Нет. H-MCA04B-1 и H-MCA04B-2 — **RESOLVED** (закрыты реворком, независимо перепроверены кодом + 7 целевых тестов + полный прогон).

## Non-blocking debt (round 2)

- **[N-R2-1] [Low, binding-гигиена]** Builder-хэш `D41CD5232B108A620DF20A548A0AD200E6BEBDC3AFFD0C62CFA10403D584AE43` не воспроизводим на текущем дереве: после записи WTH (14:29:48) изменены `plans/workflow_state.md` (чужой WIP, 14:33:36) и `tasks.md` (14:30:16 — repin-правка шапки). Код-файлы не затронуты (mtime 14:01–14:17, все до WTH; spec/ADR байт-идентичны пинам). Binding round 2 — на пересчитанный `B790BE30…6B9F` текущего дерева, на котором выполнены все прогоны. Рекомендация: WTH — последний шаг Build-фазы.
- **[N-R2-2] [Low, doc]** Постановка round 2 называла «EXTRA 149» — фактическая коллекция 150 (все passed); фигура занижена, действий нет.
- **[L1…L8]** — переносятся из round 1 без изменений (L1 dead knob — решение до релиза; L4 tasks-хэш изменился ещё раз — repin на merge обязателен; L2 — @Architect doc-уточнение).
- **[R-a…R-e]** — остаточные риски из threat-failure-analysis §6 — приняты как non-blocking (задокументированы с компенсациями).

## Unavailable checks (round 2)

U-1…U-4 — без изменений к round 1 (browser OPTIONAL — рендеринг не менялся; планировщик режима 3; прод-выборка A95/GEN-R20 — `mca-release`; PG-путь активации — вне diff по GEN-R4).

## Binding (round 2)

- Вердикт действителен только для состояния: HEAD `486b3e913db18811e4392c0a03b327663378bbbb` + worktree с WTH `B790BE30846034D87AF20646C17F4166ED4902CA224CE019352E292B7C7A6B9F` (альф. `1FE69BDD…3088` при хвостовом `\n`) + Spec `18DF2178…A3D2`. Любое изменение прод-кода/спеки инвалидирует binding.
- WTH вычислен ДО настоящего дополнения review.md; единственное post-binding изменение — сам этот отчёт (round-2 секция), прод-код и тесты не затронуты.
- Следующая фаза контроллера: **delivery** (T-3915/mca-release: staging-перечень round 1 §«Staging-перечень» остаётся входом DevOps; GEN-R20 — на релизе).

**Итог счётчиков round 2:** Critical 0 · High 0 · Medium 0 · Low (новых) 2 + перенос L1–L8 · недоступные 4 (все — deferred/N-A). **Verdict: Approved for release.**
