# ASAP-4 — review.md (FINAL release gate T-4450: волны B/C/E + cross-wave + чек-лист владельца §83)

> **Feature-ID:** `asap-4-embedding-graphrag-cover-runtime` — FINAL comprehensive release gate (T-4450): незакрытые гейтом дельты Wave B (cover style path), Wave C (summary full-window), Wave E (pipeline analytics) + cross-wave интеграция + чек-лист владельца `current_task.md` §83 (14 runtime + 21 semantic) + §84 no-false-acceptance + R4-G-001/002.
> **Risk-Level:** R3 (release gate всего эпика; меняет production-пути Summary/Cover/Analytics).
> **Status: Approved for release** — re-gate round 2 (02.10.2026): единственный блокер round 1 [M-ASAP4-E1] закрыт и независимо верифицирован (дельта строго в 2 файлах; собственный E2E-репро GREEN 21/21; TestRestartHealthDurable 8/8; семья analytics 72/72; полный pytest 10773/2 known; F8 EXIT=0; WTH пересчитан — `f62243b7…`). Весь остальной round-1 каркас (Checks 1–6, coverage, PENDING OWNER/POST-DEPLOY) в силе; round-1 вердикт (Needs Fixes) снят этой дельтой — см. Round-2 ноту ниже в этой секции.
> Остальное (round 1): блокеров больше нет; волны A/D approval'ы в силе по содержанию, но их байтовые binding'и superseded целостным binding'ом эпика (после их одобрений в дерево добавлены аддитивные E-точки эмиссии/coverage-поля — инспектированы, D-семантика не тронута, фикс M-ASAP4-D1 на месте: `summary_l2_review.py:301`).
> **Дата:** 02.10.2026. Ревью независимо: код Builder'а не правился, не коммитился; все прогоны выполнены самостоятельно.

## Binding

| Поле | Значение |
|---|---|
| Reviewed-Commit | `f04564b2104cb42057fc363fa5d469d7d09af4be` (HEAD не менялся; эпик — некоммитнутый рабочий-диф волн A–E; staged пусто) |
| Working-Tree-Hash | `f62243b7a3ec108695761b38e271c29c78bdf15cdf68fd47692bec5015f493d2` — **round 2**, целый эпик, 52 файла (39 tracked git-diff + 13 untracked content), рецепт round 1 без изменений (`path␣␣hash␣␣(origin)`, sorted, LF-join без хвостового newline, SHA-256); детерминизм подтверждён повторным прогоном. Round-1 значение `f5c93487…` инвалидовано дельтой фикса (ожидаемо): изменились 2 файла манифеста — `services/pipeline_analytics.py` (content-пин `8d82a3d6…`) и `tests/test_pipeline_analytics_asap4.py` (content-пин `a58c04f1…`); остальные 50 пересчитаны рецептом, новых файлов эпика нет |
| Spec-Hash | `ab9dec9451cdd6a003984f4ab28d3e73a4e1da367ebfaa4d5ce1d1d0b8ea1d10` (spec не менялся с Wave A round 2 — совпадает со всеми предыдущими binding'ами) |

Состав манифеста (52): tracked — `config/settings.py`, `plans/docs/canon/architecture.md`, `pytest.ini`, `services/{cover_style_jobs,cover_style_registry,database,execution_graph_source,graphrag_rebuild,llm_client,mca_events,media_execution,prompt_migrations,summary_fact_package,summary_generator,summary_l1_clusterizer,summary_l2_writer,summary_memory,summary_prompts,summary_run_log,summary_test_run,task_supervisor}.py`, `tests/conftest.py`, `tests/test_{mca01_tx_task_supervisor_round1027,mca05_episodes_stories_round1027,mca22_core_round1027,prompt_migrations,summary_asap21_prompt_migrations,summary_coverage_asap31,summary_fact_package,summary_l2_writer,summary_publish_integration_round1026,webapp_f6_round1025,webapp_js_unit}.py`, `web/api/{analytics,cover_styles,memory_agi}.py`, `web/app.js`, `web/index.html`, `web/static/app.css`; untracked (content) — `services/{embedding_control_plane,pipeline_analytics,pipeline_events,summary_l1_capacity,summary_l2_review,summary_legacy_fullwindow,summary_quote_repair}.py`, `tests/js/round1030_pipeline_inspector_test.js`, `tests/test_{cover_style_wave_b_asap4,embedding_control_plane_asap4,pipeline_analytics_asap4,summary_wave_c_asap4,summary_wave_d_asap4}.py`. **Исключены** (правило предыдущих гейтов): чужой WIP `plans/docs/mca-round1027-arch-frames.md` (контент — AMEND mca-05-episodes-stories, не эпик), процессные артефакты `plans/metrics.md`/`plans/workflow_state.md`/`plans/reports/full_audit_results.md`, untracked-артефакты (`node_modules/`, `.playwright-mcp/`, `extra_images/`, `package*.json`), plans-артефакты ревью (пишутся после кода).

## Git base и inspected change scope

Base: HEAD `f04564b`, staged пусто. Полный диф эпика: **43 tracked modified + 13 untracked epic-файлов; ~3920+/345− строк**. Замаплен на волны: A — embedding control plane (`embedding_control_plane.py`, `llm_client`, `summary_memory`, `graphrag_rebuild`, DDL v23 в `database.py`, `memory_agi.py`, панельные тесты; гейт T-4413 round 2 Approved); B — cover style (`cover_style_jobs/registry`, publish-путь `summary_generator`, `task_supervisor` L-EXTRA-6, `media_execution`, `summary_test_run` L-ASAP31-4, `web/api/cover_styles`); C — full-window (`summary_l1_capacity`, `summary_quote_repair`, `summary_legacy_fullwindow`, `summary_l1_clusterizer`, `summary_l2_writer`, `summary_run_log`); D — writer/reviewer (гейт T-4438 round 2 Approved; послевоенные касания — только E-эмиссия и coverage-поля, fail-open); E — analytics (`pipeline_events`, `pipeline_analytics`, `execution_graph_source`, `web/api/analytics`, `web/index.html`, `web/app.js`, `web/static/app.css`, JS-unit). Инфраструктура: `pytest.ini` (+маркер asap4), `tests/conftest.py` (изоляция 11 флагов + default-OFF async batch = 12 по spec §8.2).

## Checks performed (все независимо)

1. **Прогоны (сам):** полный pytest **10765 passed / 2 failed** (329.99s; оба failed — ровно ожидаемые known pre-existing round1026 bounds `test_tool_coordinator_round1026…forbidden_paths_out_of_diff` / `test_unified_image_request_round1026…vs_baseline`, падают от факта некоммитнутого фиче-диффа); целевые файлы волн A–E **243/243** (26 B + 32 C + 64 E + 50 A + 71 D); JS **53/53** (вкл. round1030_pipeline_inspector); F8 `--check` **`CHECK OK: реестр 488`, EXIT=0**. Два зависания прогона через PowerShell-пайп — воспроизведение известного L-ASAP4-9 (инструментальный артефакт, не продукт); чистый прогон detached-джобой.
2. **Wave B (фокус):** единый snapshot-резолв (`selection_stage` в начале `_publish_rich_document`; повторная резолюция запрещена; `profile_for_snapshot`/`report_style_skip`/`record_no_cover_provenance`); 6+ reason codes (`no_style/profile_missing/disabled/connection_missing/reference_missing/capability_unknown/not_configured` + umbrella `style_failed` только после submission; `style_reason_code`); provenance при всех исходах выбранного стиля (styled/base_fallback/no_cover; `no_style` — INFO без provenance, обосновано); единый resolver preview/prod (один `run_style_job`); reference integrity (магические байты/MIME/bytes_total, без контента); capability `image_edit` реален (unknown не блокирует — §58); **issue counter только после pre-execution проверок** (прод-факт Q15 закрыт); L-EXTRA-6 MERGE-семантика `save_checkpoint` (SELECT+merge в транзакции; media-консьюмер переведён на cursor-приоритет, регресс закрыт); L-EXTRA-7 стабильный job key; `update_reference` rowcount→404; OFF-паритет-тест.
3. **Wave C (фокус):** planning-конверт (только при `_allow_chunking` + `SUMMARY_COVERAGE_CHUNKING_ENABLED` ON + не-`legacy_static` — чужие OFF-флаги бит-в-бит, их тесты зелёные без правок); deterministic repair (dedupe→split≤30→budget; вход не мутируется); 688→3 чанка, facts=688, coverage 100% (Q17/golden J/§74); Legacy full-window = reuse semantic package от L2 / иерархическая редукция; degraded coverage виден (включая safety-truncate поверх пакета — `legacy_budget_reduction`); quote §50.20 fix («found+доказан → valid») + fail-closed при невозможности repair + **extension, не fork** (статусы импортированы из `services/quote_resolver`; сам `quote_resolver` в диффе отсутствует — MCA-22 не тронут); R17 (тексты цитат не в логах/метриках — тест).
4. **Wave E (фокус):** единый transport mca-17a (второго store нет; reason codes — только `mca_events.REASON_CODES`; `style_id/style_revision` — аддитивные whitelist-поля); guard-тест §61.12 (source-scan, `FROM mca_events`, без импорта human-log); RBAC `requires_global_admin` на обоих эндпоинтах (401/403 тесты); coverage first-class (`health_of` = publication × coverage, epsilon 99.95; fixture D не-healthy); бейджи только текстом; kill-switch: эмиссия no-op, агрегаты честно «нет данных», Inspector из state-проекций; bounded-запросы (LIMIT ≤5000/50, polling 15с на вкладке).
5. **Cross-wave:** (1) стиль на Legacy И Hybrid — §39/§70/§71 тесты в моём прогоне 243 ✓; (2) события стадий emitter→mca_events→адаптер→view — **мой E2E-репро** (реальный `pipeline_events`+`COVER_*` → `flush_events` в SQLite → `collect_run/collect_aggregate/collect_runs_list`): узлы обеих веток, reason-коды, coverage/publication сквозь `usage_json` ✓ (и этим репро обнаружен M-ASAP4-E1); (3) coverage сквозной: ctx→snapshot(`execution_graph_source` _SNAPSHOT_FIELDS)→`SUMMARY_RUN_DONE.usage_json`→view/list/aggregate ✓; (4) **kill-switch матрица эпика (12 флагов §8.2)**: полный сьют = комбинированный OFF-смок (~10.5k не-asap4 тестов при всех 11 флагах OFF одновременно через conftest; 12-й `EMBED_ASYNC_BATCH` default-OFF) + ON-покрытие в asap4-тестах + пер-флаг parity-тесты каждой волны — конфликтов комбинаций не обнаружено; (5) **R17-скан всего диффа**: 33 добавленных log-вызова — только id/числа/коды; `api_key` не читается в diagnostics (тест); UI-диффы без секретов/контента; env-переменные — имена, не значения; (6) **DDL v23 — единственная миграция эпика**: один новый `MigrationStep` (`_migrate_embedding_control_plane_v23`), additive (CREATE IF NOT EXISTS + ALTER под guard `PRAGMA table_info`), ни одного UPDATE существующих строк, идемпотентна, PG no-op; смежные гейты mca01 (+3 write-points 144→147), mca05/mca22 (tail-mark v22→v23) — санкционированные аддитивные последствия; (7) **скоуп-ползучести нет**: все 56 файлов диффа замаплены (см. выше); канон `architecture.md` — только Wave D промпты (ADR D3/D4/D5); R4-G-001/002 — вторых GraphRAG/Cover/Summary/resolver'а/реестра поколений нет; (8) **2 гейт-обновления санкционированы**: F6-инвариант §116 6→8 read-only GET + S6-набор роутов — read-only, global-admin, требуют spec §5 E.2 (§61.4/§61.9), явные комментарии со ссылкой на ADR-1028-7 D8.
6. **Wave D регрессия после E:** фикс M-ASAP4-D1 на месте (`summary_l2_review.py:301`); 7 fail-open точек эмиссии E и coverage/health-поля инспектированы — семантика review-петли/вердиктов/бюджета не тронута; полный сьют и 71/71 Wave D зелёные.

## Requirement/evidence coverage (чек-лист владельца §83)

**Runtime 14:** 429 без retry storm (§64-тест + H-ASAP4-1 fix) ✓; same-project keys ≠ независимая capacity (§65, safe default «unknown = одна группа») ✓; failover независимых групп (§65) ✓; rebuild pausable/resumable (§68 + AM-1: paused_rate_limit, checkpoint, horizon) ✓; online retrieval без starvation (§67, P0-bucket/preemption) ✓; оба индекса → ACTIVE — код-путь (9 критериев + swap) ✓, live — PENDING OWNER; KNN диагностируем (7 distinct codes, M-ASAP4-4 закрыт; 25/25 targeted) ✓; Legacy не теряет Style stage (§39/§71) ✓; style failure → base cover с причиной (§72 + SKIPPED/provenance) ✓; L1 large output не invalid от cap (golden J/Q17/Q74) ✓; quote repair выполняется (§75) ✓; Legacy не режет XML 50k (§74: considered=688) ✓; Analytics отражает реальность — **⚠ M-ASAP4-E1** (после рестарта health врёт); Medved Press реально применяется в production — PENDING OWNER (DC-4, §78).

**Semantic 21 (Summary):** полностью покрыты Wave D gate round 2 (таблица в истории ниже) и переподтверждены текущим состоянием: prohibition удалён из активного промпта (канон байт-синхронизирован); prose-first default; verified quote разрешён (§50.20-после — проверено мной в коде `_validate`); named-quote не reject при найденном тексте ✓; deterministic validator до Reviewer ✓; findings evidence-based (M-ASAP4-D1 fix на месте) ✓; targeted Revision (patch primary) ✓; bounded loop (≤2, budget ≤6) ✓; single local error не топит статью (golden D/§75 + minor-пин) ✓; wrong-person/unsupported numbers/question-modality/forward-reply/major-topic coverage — golden A/E/F/B/L ✓; 600–700+ considered 100% (Q74) ✓; статья ≠ transcript (§50.56/R4-D-016/017) ✓; first-pass не переписывается (golden M) ✓; Reviewer outage не SPOF (review_degraded, deterministic-слой) ✓; Legacy publication не скрывает L2 failure (pipeline_health append-only, §50.53 — проверено в диффе `summary_generator`) ✓; approved text не регенерируется из-за Cover/formatter (ladder §50.52) ✓.

## Focused audit coverage

Wave B: все 6 задач T-4415–T-4420 по коду+тестам (не по statements); `cover_style_jobs.py` дифф 511 строк прочитан; counter/skip/provenance пути; L-EXTRA-6 влияние на graphrag/media-консьюмеров (workaround `graphrag_rebuild` остаётся валидным). Wave C: 3 новых модуля прочитаны целиком; конверт ASAP-3.1; интеграция в `run_l1`/`_run_l1_lossless`/`_run_legacy_pipeline`. Wave E: оба новых модуля прочитаны целиком (264+936 строк); SQL-пути имена-колонок сверены со схемой v15+v19 (`usage_json`/`pipeline_run_id` — реальные колонки; v19 на проде); RBAC; UI-диффы (index.html/app.js/css) — структурно через JS-гейты. Cross-wave: E2E-репро; изоляция conftest; санкции смежных гейтов. Критические зависимости: `save_checkpoint` MERGE (общий store — полный сьют зелёный), `execution_graph_source` проекция (bounded ≤24, R17-ключи).

## Counterexamples checked

1. **Рестарт процесса → «Последний запуск»/drill-down** (снапшот-реестр in-memory, «при рестарте теряется» — `execution_graph_source.py:178`): опубликованный run с coverage 44.6% показывает «Не завершён» → **M-ASAP4-E1** (репро мой, воспроизведён на реальном transport+SQLite).
2. Агрегаты/список runs по тем же данным — корректны (degraded) → дефект локализован во view-пути, не в данных.
3. 429-фикстура при OFF → прежний 21-аттемпный контур (Wave A parity) ✓; guard OFF → too_many_facts invalid (C parity) ✓; quote OFF → §50.20-матрица бит-в-байт ✓; snapshot OFF → без событий, прежний порядок counter ✓; events OFF → no-op + честные пустые агрегаты ✓.
4. Битый референс (jpg-байты под .png) → отфильтрован, `reference_missing` ✓; connection_missing → ранний выход, default-слот молча не подставляется ✓.
5. Unmapped invalid_reason (структурные коды вне REASON_CODES) в стадийных событиях → reason_code отбрасывается `build_event` — узел ✕ без RU-причины (L-ASAP4-E3, счётчики не искажены).
6. «empty»-run в списке runs → бейдж «Здоров» (L-ASAP4-E2; расхождение с «Не завершён» view-пути).
7. PowerShell-пайп vs detached job — инструментальный, L-ASAP4-9.

## Blocking findings

### [M-ASAP4-E1] [Medium, requirement-blocking] Health-бейдж Run Inspector после рестарта/для исторических run'ов показывает «Не завершён» вместо реального исхода

- **Location:** `services/pipeline_analytics.py` — `health_of` (≈517–542) + `_publication_block` (≈498–514).
- **Requirement:** spec §5 E.2 — §61.6 «health = publication_status × source_coverage» (first-class, Q25) и §61.13 («Не завершён» — только для незавершённых прогонов; бейдж — единственный текстовый носитель health).
- **Repro (независимый E2E):** реальный `pipeline_events.summary_*` + `COVER_*` → `mca_events.flush_events` (SQLite) → `collect_run` **без in-memory снапшота** (состояние после каждого деплоя/рестарта; также ВСЕ drill-down'ы исторических run'ов §61.9): публикация `rich`, coverage 44.6% → `health=incomplete` («Не завершён»), при этом `_publication_block` возвращает `status="rich"` — `health_of` признаёт только `("ok","published_rich","published_text")` и падает в финальный `return HEALTH_INCOMPLETE`. Агрегаты 24h/7d и список runs (считают напрямую из DONE-событий) — корректны: «degraded». Widget противоречит сам себе.
- **Impact:** после каждого рестарта главная карточка «Последний запуск» и любой drill-down по завершённому опубликованному прогону ложны (нарушение §61.6/§61.13; подрыв доверия к единственному new UI-механизму эпика; маскировка degradation-исходов за неправильным бейджем — no-false-visibility). Окно: от рестарта до первого нового Summary-прогона в процессе + перманентно для drill-down старых run'ов.
- **Fix (точечный):** в `health_of` признавать опубликованные канальные статусы из durable-событий: добавить `"rich"`/`"text"` в whitelist (либо нормализовать статус в `_publication_block`); опционально — fallback run_status из `status`-колонки DONE-события. Негативный тест: `collect_run` по durable-событиям без снапшота → published+coverage<100% = degraded; published+full = healthy (restart-сценарий) в `tests/test_pipeline_analytics_asap4.py`.
- **Verification method (re-gate):** мой E2E-репро + `TestRunViewScenarios`/`TestPipelineApiRbac` + новый restart-тест; полный pytest не требуется, если диф не выйдет за `pipeline_analytics.py` + этот тест-файл (прецедент Wave D round 2).

## Non-blocking debt (переносится)

- **[L-ASAP4-E2]** `run_list_entry` (pipeline_analytics.py:560–595): статусы вне `ok/degraded/failed` (напр. `empty`) → бейдж «Здоров» в списке runs — расхождение с «Не завершён» view-пути; закрыть той же нормализацией, что M-ASAP4-E1.
- **[L-ASAP4-E3]** `pipeline_events.map_reason`: invalid_reason'ы вне REASON_CODES (структурные коды L1/L2, кроме too_many_*) → `reason_code` отбрасывается контрактом `build_event` — ✕-узлы без человекочитаемой причины; счётчики/агрегаты не искажены.
- Перенесённые: L-ASAP4-7/8/9 (A), L-ASAP4-D3/D4/D5/D6 (D) — в силе; L-ASAP4-9 (нестабильность полных прогонов) воспроизведён дважды в этом гейте через PowerShell-пайп — DevOps к релизному прогону (детached-джоба чистая).

## PENDING OWNER / POST-DEPLOY (не блокируют release-gate, обязаны в отчёте)

1. **§77 (T-4447) live embeddings** — реальные quota groups, rebuild без storm на проде, оба индекса → ACTIVE, живой KNN каждого индекса, FTS fallback при controlled KNN disable; платные вызовы; ветка evidence §34 (scheduler-proof + меньший slice → ACTIVE) — выбор на T-4447.
2. **§78 (T-4448) live Medved Press + §48/§49** — precondition **DC-4** (edit-capable Qwen-connection; прод-факт Q14: `not_configured` за 72 мс); real edit/«intentional failure» — платные вызовы; закрывать кнопкой «Протестировать стиль» запрещено (§84).
3. **§79 (T-4449) live full window** — окно 600–700+, coverage 100% на проде; платные вызовы.
4. **§50.62/§50.64 (качество Hybrid Writer)** — first-pass %, распределение findings, false-positive rate живого Reviewer, latency/стоимость — post-deploy live-метрики (T-4449/T-4450-delivery); код-уровень верифицирован этим и Wave D гейтами.
5. **T-4446 live Browser Use + Playwright** — 4 сценария §61.16 A–D на desktop+mobile после деплоя (инструкция Orchestrator'а); в этом гейте верифицированы структурные JS-гейты 53/53, API/RBAC и модельные сценарии A–D.

## Unavailable checks

- Live browser-верификация §61.16 A–D — отложена Orchestrator'ом на post-deploy (см. PENDING 5); обязательна на приёмке — иначе пункт §61.16 не закрыт.
- Production Gemini quota/tier/KNN/async Batch ON-контракт — PENDING OWNER (T-4447).
- Multi-process lease под вторым процессом — DevOps на деплое (T-4451).
- Два зависания полного прогона в PowerShell-пайпе — инструментальный артефакт reviewer-сессии (соответствует известному L-ASAP4-9); чистый прогон detached-джобой 10765/2.

## Вердикт

**Needs Fixes.** Волны B/C/E добротны и соответствуют спеке: прод-триада Q17/Q18/307-из-688 закрыта с честным coverage, видимый fail-open Cover Style с сохранным issue-нумератором, единый analytics-контур без второй истины, все 12 kill-switch'ей с parity, DDL v23 единственная/аддитивная, R17 чист, скоуп без ползучести, оба смежных гейт-обновления санкционированы. Один requirement-блокер: [M-ASAP4-E1] — health-бейдж нового Run Inspector врёт после каждого рестарта/на drill-down'ах (Medium, нарушение §61.6/§61.13). Fix — одна нормализация статуса + restart-тест. После закрытия по указанному re-gate рецепту — **Approved for release** с перечнем PENDING OWNER/POST-DEPLOY выше. Binding этого вердикта: HEAD `f04564b` + WTH `f5c93487…` + spec `ab9dec94…`; любые изменения кода/spec инвалидируют привязку. Код Reviewer'ом не правился; MEMORY_DELTA: нет.

---

# FINAL gate — Round 2 (02.10.2026): дельта-реворк [M-ASAP4-E1] → **Approved for release**

> **Feature-ID:** `asap-4-embedding-graphrag-cover-runtime` · **Risk-Level:** R3 · **Status: Approved for release**
> **Reviewed-Commit:** `f04564b2104cb42057fc363fa5d469d7d09af4be` · **Working-Tree-Hash:** `f62243b7a3ec108695761b38e271c29c78bdf15cdf68fd47692bec5015f493d2` · **Spec-Hash:** `ab9dec9451cdd6a003984f4ab28d3e73a4e1da367ebfaa4d5ce1d1d0b8ea1d10`
> Объём: ТОЛЬКО дельта фикса [M-ASAP4-E1] по предписанному round-1 рецепту; весь остальной round-1 вердикт (Checks 1–6, requirement/semantic coverage, non-blocking debt, PENDING OWNER/POST-DEPLOY, unavailable checks) в силе без пересмотра. Код Reviewer'ом не правился, не коммитился; все прогоны выполнены самостоятельно.

## Git base и inspected change scope (round 2)

Base тот же: HEAD `f04564b`, staged пусто, 1 stash (чужой, не тронут). `git status` = round-1 набору бит-в-байт (43 tracked modified + 13 untracked epic-файлов + чужие артефакты) — новых файлов эпика нет. Mtime-анализ: после фиксации round-1 гейта (`review.md` 21:14:56) менялись ровно 2 файла дельты — `services/pipeline_analytics.py` (21:26) и `tests/test_pipeline_analytics_asap4.py` (21:28) — плюс plans-доки Builder'а (`evidence.md` §E8–E11, `tasks.md` T-4443/T-4450); tracked-файлы и spec не тронуты (следующий по свежести продуктовый файл — 20:17, до гейта). Оба файла дельты LF / no BOM / конечный newline. Полный сьют 10773 = 10765 (round 1) + ровно 8 новых тестов при том же наборе из 2 known failed — скрытых изменений кода вне заявленной дельты нет.

## Checks performed (round 2, все независимо)

1. **M-ASAP4-E1 — ЗАКРЫТ (код).** `services/pipeline_analytics.py:522-524`: `_PUBLISHED_STATUSES` = прежний {ok, published_rich, published_text} + durable-канальные {rich, text} из `SUMMARY_RUN_DONE.usage_json.publication` — ровно предписанный round-1 fix. Новый keyword-only kwarg `done_event` (`:527`, default `{}` — обратная совместимость): провал финализации распознаётся по `status`/`outcome` DONE-строки БЕЗ in-memory снапшота → «Не издано» (`:544-548`); durable `pipeline_health` из usage_json — рестарт-паритет сигнала review_degraded (`:551-552`). `build_run_view` захватывает DONE-строку (`done_row = last("SUMMARY_RUN_DONE")`, `:276`) и передаёт её в `health_of` (`:457`). `_publication_block`, nodes, `run_list_entry`, агрегаты — не тронуты (контракт UI сохранён; L-ASAP4-E2 сознательно остаётся non-blocking debt). `health_of` — единственный прод-вызывающий `build_run_view` (проверено поиском; `web/api/analytics.py` его не зовёт напрямую). R17: фикс не добавляет ни одного log-вызова.
2. **Мой E2E-репро round 1 (переписан независимо, вне тест-файла Builder'а) — GREEN 21/21, EXIT=0.** Реальный транспорт (`pipeline_events.summary_*` + `COVER_*` через `mca_trace.emit_stage`) → `mca_events.flush_events` в чистый SQLite v23 (flushed=18, без потерь) → `egs.reset()` (рестарт: реестр снапшотов пуст, проверено `egs.get_run() is None`) → `collect_run`/`collect_latest`/`collect_runs_list`/`collect_aggregate` БЕЗ снапшота: published rich + coverage 44.6% (307/688) → `degraded`/«С деградацией» (publish-узел ✓, `running=False`, `coverage.full=False`); published rich + 100% → `healthy`/«Здоров». Restart-safe: повторное чтение — байт-равный результат (нет опоры на in-memory); карточка/список/агрегаты согласованы (totals {total:2, healthy:1, degraded:1, failed:0, incomplete:0}; в списке runs те же бейджи). **Контрфактикум причинности:** подмена whitelist на round-1 набор {ok, published_rich, published_text} на тех же durable-данных → `incomplete` («Не завершён») — round-1 дефект воспроизведён, закрыт именно этой дельтой.
3. **Негативный restart-тест Builder — PASSED (8/8).** `TestRestartHealthDurable`: обязательный по рецепту `test_restart_published_low_coverage_is_degraded_full_is_healthy` (реальный transport → SQLite → `egs.reset()` → `collect_run` без снапшота: 44.6% → degraded, 100% → healthy) + latest-карточка после рестарта из durable DONE + финализированный failed → «Не издано» (DONE `status` и `outcome` — оба пути) + START без DONE → «Не завершён» + `running=True` + канальный `text` + `publication=failed` из usage_json + review_degraded через durable `pipeline_health`. Рецепт-соседи: `TestRunViewScenarios` 8/8 (вкл. fixture D не-healthy), `TestPipelineApiRbac` 3/3 (401/403/fail-open shape).
4. **Прогоны (все самостоятельно).** Файл analytics-семьи **72/72** (64 + 8 новых). Полный pytest detached-джобой через Task Scheduler (лекарство от L-ASAP4-9; 337.04s): **10773 passed / 2 failed** — ровно ожидание (10765 round 1 + 8), оба failed — те же known pre-existing round1026 bounds `test_tool_coordinator…forbidden_paths_out_of_diff` / `test_unified_image_request…vs_baseline` (падают от факта некоммитнутого фиче-диффа, вне эпика). F8 `--check`: **`CHECK OK: реестр 488 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны`, EXIT=0**.
5. **WTH пересчитан по рецепту round 1** (52 файла: 39 git-diff + 13 content, sorted, `path␣␣hash␣␣(origin)`, LF-join без хвостового newline): **`f62243b7…`** — детерминизм подтверждён повторным прогоном (идентичное значение); пер-файловые пины дельты: `pipeline_analytics.py` `8d82a3d6…` (content), `test_pipeline_analytics_asap4.py` `a58c04f1…` (content). Round-1 агрегат `f5c93487…` инвалидован дельтой — ожидаемо, байтовая привязка не переиспользуется. Spec-Hash `ab9dec94…` не изменился; HEAD `f04564b` не менялся; staged пусто.

## Focused audit coverage (round 2)

Дельта локализована в `health_of` + его единственной точке вызова — второго резолвера health нет (проверено round 1, не изменилось). Кромки: kwarg `done_event` — keyword-only с default `{}` (обратная совместимость всех подписей); DONE-семантика сверена с эмиттером `pipeline_events.summary_done` (`status`-колонка = `health or status`; `outcome` = failed только при `status=="failed"`) — ложных «Не издано» на успешных прогонах нет (покрыто сценарием 100%→healthy в моём репро); corrupt usage_json → fail-open в честный «Не завершён» (парсинг изолирован, не падает); running-семантика не тронута (START без DONE → ○). Регрессии: полный сьют 10773/2 с идентичным набором known failed; соседние сценарии view (A–D, RBAC) зелёные.

## Counterexamples checked (round 2)

1. **Round-1 репро-сценарий** (рестарт → published 44.6%) → теперь `degraded`/«С деградацией», список и агрегаты согласованы ✓ (мой E2E, GREEN).
2. **Published 100% после рестарта** → `healthy`/«Здоров» — фикс не «занижает» здоровые прогоны ✓ (мой E2E + тест).
3. **Контрфактикум**: старый whitelist на тех же данных → `incomplete` ✓ (причинность фикса доказана, не корреляция).
4. **DONE failed без снапшота** → «Не издано», оба кодовых пути (`status`-колонка и `outcome`) ✓ (тесты + чтение эмиттера).
5. **Реально-незавершённый (START без DONE)** → «Не завершён» + running ✓ (§61.13 сохранён).
6. **review_degraded при публикации и coverage 100%** → не «Здоров» после рестарта ✓ (durable pipeline_health).
7. **Канальный `text`** (plain-публикация) → полноценная публикация для health ✓ (тест).

## Requirement/evidence coverage (round 2 — дельта к таблице round 1)

* Пункт «Analytics отражает реальность» таблицы §83 runtime-14 — **✓ полностью** (был ⚠ M-ASAP4-E1): health-бейдж Run Inspector рестарт-безопасен, строится из durable-событий, «Не завершён» — только для реально незавершённых прогонов (§61.6/§61.13).
* Остальные 13 runtime + 21 semantic — без изменений, подтверждены неизменившимся деревом (WTH-рецепт пересчитан, полный сьют идентичен round 1 + 8).

## Blocking findings (round 2)

Нет. **[M-ASAP4-E1] RESOLVED** — закрыт точно по предписанному fixed-рецепту, верифицирован независимо (код, собственный E2E-репро с контрфактикумом, негативные тесты Builder'а 8/8).

## Non-blocking debt (переносится, без изменений)

* **[L-ASAP4-E2]** OPEN: `run_list_entry` — статус `empty` → «Здоров» в списке runs (расхождение с view-путём); закрыть той же нормализацией при следующем касании.
* **[L-ASAP4-E3]** OPEN: структурные invalid_reason'ы вне REASON_CODES → ✕-узлы без RU-причины (счётчики не искажены).
* L-ASAP4-7/8/9 (A), L-ASAP4-D3/D4/D5/D6 (D) — в силе.

## Unavailable checks (round 2)

Без изменений round 1: live-browser §61.16 A–D (T-4446, post-deploy), production Gemini quota/KNN/async-Batch (T-4447), live Medved Press (T-4448, DC-4), live full window (T-4449), multi-process lease (DevOps, T-4451). Документарная верификация зависимостей не требовалась (дельта — stdlib-логика, новых зависимостей нет). OpenViking-память: релевантные ограничения зафиксированы в артефактах фичи; MEMORY_DELTA: нет.

## Вердикт round 2

**Approved for release.** Блокер M-ASAP4-E1 закрыт минимальным точным фиксом ровно по round-1 рецепту (durable-канальные статусы rich/text в whitelist + fallback финализации из DONE status/outcome + рестарт-паритет review_degraded), покрыт обязательным restart-негатив-тестом и независимо воспроизведён моим E2E-репро с доказанной причинностью (контрфактикум старого whitelist). Регрессий нет: 10773/2 known, analytics 72/72, F8 EXIT=0. Одобрение привязано к состоянию: HEAD `f04564b` + WTH `f62243b7…` + spec `ab9dec94…`. Любое изменение кода/spec инвалидирует binding — новый gate. Обязательные хвосты round 1 сохраняются: PENDING OWNER/POST-DEPLOY (5 пунктов) и unavailable checks выше — live-приёмка §61.16/T-4446 обязательна на delivery, иначе §61.16 не закрыт. Следующая фаза контроллера — **delivery**. Для DevOps: детached-прогон полного сьюта стабилен (schtasks-джоба, 337s), PowerShell-пайп по-прежнему не использовать (L-ASAP4-9).

---

# ASAP-4 — review.md (Wave D Reviewer gate, T-4438)

> **Feature-ID:** `asap-4-embedding-graphrag-cover-runtime` — Wave D (зона D, Hybrid L2 Writer/Reviewer bounded revision, T-4428…T-4437)
> **Risk-Level:** R3 (spec §83/T-4438 gate; review-петля меняет семантику публикации Summary)
> **Status: Approved (Wave D)** — gate round 2 (02.10.2026): единственный блокер round 1 [M-ASAP4-D1] закрыт и независимо верифицирован (код + собственный репро + негативные тесты обоих уровней); blocking 0; пин minor-not-Legacy добавлен с байт-синхронизацией канона ([L-ASAP4-D2] закрыт). Каркас-оценка round 1 в силе. История round 1 (Needs Fixes) — ниже в этом файле.
> **Дата:** 02.10.2026. Ревью независимо: код Builder'а не правился, не коммитился; полный pytest прогнан самостоятельно (обе итерации).

## Binding

| Поле | Round 2 (действующий) | Round 1 (историческое) |
|---|---|---|
| Reviewed-Commit | `f04564b2104cb42057fc363fa5d469d7d09af4be` (HEAD; фича — некоммитнутый рабочий-диф волн A–D; HEAD не менялся) | тот же |
| Working-Tree-Hash | `4675df09b5c2e8be51cc86931a5ad7b80d258dcaa2ca672a06725c0c6d875da3` | `a89ee3257dc76e757a4c376ae232c9be48236d36922f724cf7569ac172f94183` (инвалидован правками реворка — ожидаемо) |
| Spec-Hash | `ab9dec9451cdd6a003984f4ab28d3e73a4e1da367ebfaa4d5ce1d1d0b8ea1d10` (spec не менялся — совпадает с round 1/Wave A round 2) | тот же |

Рецепт WTH (детерминированный, воспроизводимый; round 2 воспроизведён повторным прогоном): SHA-256 от UTF-8-манифеста — по одной строке `path␣␣hash␣␣(origin)` на файл, отсортировано по пути; 15 tracked feature-файлов Wave D — hash их `git diff -- <path>` (origin `git-diff`), 3 untracked — hash полного содержимого (origin `content`). Состав (18): `config/settings.py`, `plans/docs/canon/architecture.md`, `services/mca_events.py`, `services/prompt_migrations.py`, `services/summary_fact_package.py`, `services/summary_generator.py`, `services/summary_l1_clusterizer.py`, `services/summary_l2_review.py` (content), `services/summary_l2_writer.py`, `services/summary_legacy_fullwindow.py` (content; файл создан Wave C, расширен Wave D — coverage map §50.32), `services/summary_prompts.py`, `services/summary_run_log.py`, `tests/conftest.py`, `tests/test_prompt_migrations.py`, `tests/test_summary_asap21_prompt_migrations.py`, `tests/test_summary_fact_package.py`, `tests/test_summary_l2_writer.py`, `tests/test_summary_wave_d_asap4.py` (content). Исключены: дифы волн A/B/C вне зоны D (покрыты их binding'ами), чужие WIP plans/*, untracked-артефакты (`node_modules/`, `.playwright-mcp/`, `extra_images/`, `package*.json`), plans-артефакты ревью (пишутся после кода). Дельта реворка round 2 изменила 4 файла манифеста: `summary_l2_review.py` (фикс M-D1), `summary_prompts.py` (пин minor-not-Legacy, строка 645), `plans/docs/canon/architecture.md` (байт-синхронизация канона, строка 770), `test_summary_wave_d_asap4.py` (+2 теста, 69→71); остальные 14 — пересчитаны рецептом без изменений.

---

# Round 2 (02.10.2026) — дельта-реворк M-ASAP4-D1 → **Approved (Wave D)**

> **Feature-ID:** `asap-4-embedding-graphrag-cover-runtime` · **Risk-Level:** R3 · **Status: Approved (Wave D)**
> **Reviewed-Commit:** `f04564b2104cb42057fc363fa5d469d7d09af4be` · **WTH:** `4675df09b5c2e8be51cc86931a5ad7b80d258dcaa2ca672a06725c0c6d875da3` · **Spec-Hash:** `ab9dec9451cdd6a003984f4ab28d3e73a4e1da367ebfaa4d5ce1d1d0b8ea1d10`
> Объём: ТОЛЬКО дельта реворка round 1 (каркас-оценка round 1 в силе). Код Reviewer'ом не правился, не коммитился; все прогоны выполнены самостоятельно.

## Git base и inspected change scope (round 2)

Base тот же: HEAD `f04564b`, staged пусто, 1 stash (чужой, не тронут). Дельта реворка по манифесту (4 файла): `services/summary_l2_review.py` — `parse_review_verdict` (247–323: валидация refs + R17-safe лог + нормализация needs_fixes→approved; docstring дополнен), `services/summary_prompts.py:645` — пин minor-not-Legacy, `plans/docs/canon/architecture.md:770` — байт-синхронизация канона, `tests/test_summary_wave_d_asap4.py` — +`test_finding_without_refs_dropped` (+426–453), +`test_finding_without_refs_no_revision_first_pass_published` (+516–548), +2 пин-ассерта в `test_reviewer_prompt_semantics` (+232–235). Остальные 14 файлов манифеста инспектированы пересчётом рецепта WTH (18/18, детерминирован) + полным сьютом: 10700 = 10698 (round 1) + ровно 2 новых теста — скрытых изменений кода вне заявленной дельты нет.

## Checks performed (round 2, все независимо)

1. **M-ASAP4-D1 — ЗАКРЫТ (код).** `services/summary_l2_review.py:290-311`: refs собираются из `item.get("evidence_refs") or []` → пустой список И отсутствующее поле дают `refs=[]` → единый guard `if invalid_ref or not refs:` отбрасывает находку (дроп как для выдуманного ID) с логом `L2_REVIEW_FINDING_DROPPED | code=<из FINDING_CODES> | cause=invalid_ref|missing_refs` — в записи только enum-код + фикс-строка, ни instruction, ни refs, ни текстов (R17 — проверено захватом записей лога в моём репро: instruction «секретная фраза-инструкция» в записях отсутствует). `319-321`: `needs_fixes` без единой валидной находки → `approved` (§50.11 «нет основания»). Оба условия — ровно предписанный round-1 fixed-рецепт.
2. **Мой репро round 1 (переписан независимо, вне тест-файла Builder'а) — ожидание выполнено.** Parse-уровень: находка `evidence_refs: []` → `approved`, findings=0, dropped=1; вариант вообще без поля → то же; контроль с валидным ref (101) → `needs_fixes`, 1 находка (легитимный путь ревизии не сломан). Loop-уровень (ровно round-1 сценарий: Reviewer возвращает needs_fixes с единственной фантомной blocking-находкой без refs): `status=ok`, usable, документ **байт-в-байт черновика**, writer=1/reviewer=1/**revision=0**, `first_pass_approved=1`, `final_approved=1`, `findings_total=0`, `dropped=1`, `legacy_after_review=0` ✓.
3. **Негативные тесты Builder — PASSED.** Юнит `test_finding_without_refs_dropped`: пустой refs + отсутствующее поле отброшены (dropped=2), валидная находка рядом жива (`needs_fixes`, 1 finding); единственная без-refs → `approved`. Интеграция `test_finding_without_refs_no_revision_first_pass_published`: blocking-finding без refs → dropped=1, `revision.calls==0`, документ == черновик (объектное равенство), `first_pass_approved=1`, `legacy_after_review=0`.
4. **Пин minor-not-Legacy + байт-синхронизация канона — ✓, [L-ASAP4-D2] закрыт.** `summary_prompts.py:645`: «Находки уровня minor … сами по себе - не основание для needs_fixes: нет blocking-находок - верди approved; minor-замечания не переводят статью в Legacy» — ровно рекомендованная round-1 формулировка; канон `architecture.md:770` содержит тот же текст; байт-тест `SUMMARY_L2_REVIEWER_SYSTEM_PROMPT in canon` + пин-ассерты (`сами по себе - не основание для needs_fixes`, `не переводят статью в Legacy`) — зелёные.
5. **Прогоны (все самостоятельно).** Полный pytest `tests --timeout=120 -q`: **10700 passed / 2 failed** (306s; оба failed — те же known pre-existing round1026 bounds `test_forbidden_paths_out_of_diff`/`test_forbidden_paths_out_of_diff_vs_baseline`, причина воспроизведена — падают от самого факта некоммитнутого фиче-диффа vs baseline, вне эпика). Wave D-файл **71/71**. Целевые соседи **357 passed** (wave_c/l2_writer/l2_integration/prompt_migrations/asap21_prompt_migrations/fact_package/coverage_asap31/incident_empty_package/generator); полное семейство `test_summary*` **1124 passed**; пины writer/prompt_migrations/asap21/fact_package **153 passed**. F8 `--check`: **`CHECK OK: реестр 488 == REGISTRY…`, EXIT=0**.
6. **WTH пересчитан по рецепту round 1** (18 файлов: 15 git-diff + 3 content, sorted, `path␣␣hash␣␣(origin)`): **`4675df09…`** — детерминизм подтверждён повторным прогоном (идентичное значение). Предыдущий `a89ee325…` инвалидован правками реворка — ожидаемо, round-1 байтовая привязка не переиспользуется. Spec-Hash `ab9dec94…` не изменился; HEAD `f04564b` не менялся; staged пусто.

## Focused audit coverage (round 2)

Дельта локализована в `parse_review_verdict` — единственной точке разбора вердикта (второго резолвера нет — проверено round 1, не изменилось). Кромки дельты: лог dropped не несёт пользовательских данных (R17 ✓); счётчик `l2_review_dropped_findings` прокидывается в метрики результата и лог `L2_REVIEW` (подтверждено end-to-end в репро) — нормализация `approved` телеметрию не маскирует (dropped остаётся видимым при first-pass approved); downstream-логика (progress criterion, first_pass, бюджет) не тронута — полный сьют 10700/2 без новых падений и идентичный набор failed это подтверждают; пин в промпте согласован с кодом (`needs_fixes` без валидных находок → approved в `parse_review_verdict` — поведение и промпт теперь говорят одно и то же).

## Counterexamples checked (round 2)

1. **Round-1 репро-сценарий** (фантомная blocking-находка без refs) → **теперь approved, без ревизии, не Legacy** ✓ — воспроизведён моим скриптом (ожидание round 1: `approved`/findings=0 — выполнено).
2. **`needs_fixes` вовсе без поля `findings`** → 0 валидных → `approved` ✓ (код 319–321; закрывает и этот край).
3. **Смешанный refs** `[валидный, выдуманный]` → находка целиком дроп (invalid_ref) — консервативно, §50.11 ✓ по коду.
4. **Строковые refs** (`"101"`) → не int → invalid_ref → дроп ✓ по коду.
5. **Валидная находка рядом с бездоказательными** — жива, `needs_fixes` сохраняется (спорная ревизия по-прежнему работает) ✓ (тест + мой репро-контроль).
6. **R17 dropped-лог** — только `code=` (закрытый набор) + `cause=` (фикс-строка); instruction/тексты в записи отсутствуют ✓ (репро с захватом записей).

## Requirement/evidence coverage (round 2 — дельта к таблице round 1)

* Пункт 6 таблицы §83 («semantic Reviewer не придумывает evidence») — **✓ полностью** (был ⚠ M-ASAP4-D1): находки без доказательств отбрасываются наравне с invented, needs_fixes без валидных находок → approved.
* Пункт 9 (single local error не сносит статью) — усилен пином minor-not-Legacy (стилевые/минорные замечания больше не топят статью в ревизию/Legacy на уровне промпта, а «нет blocking → approved» теперь и в промпте, и в коде).

## Blocking findings (round 2)

Нет. **[M-ASAP4-D1] RESOLVED** — закрыт точно по предписанному fixed-рецепту, верифицирован независимо (код, собственный репро, негативные тесты Builder'а обоих уровней).

## Non-blocking debt (переносится)

* **[L-ASAP4-D2] CLOSED** — пин minor-not-Legacy добавлен в промпт Reviewer + канон байт-синхронизирован (п.4 Checks round 2).
* **[L-ASAP4-D3]** OPEN: `services/summary_generator.py:743` склеенная строка — косметика при следующем касании файла.
* **[L-ASAP4-D4]** OPEN: evidence §D1 формулировка про BOM (`test_summary_l2_writer.py` — pre-existing BOM из HEAD) — поправить при следующем касании evidence.
* **[L-ASAP4-D5]** OPEN: `_deterministic_findings` не пересчитываются после ревизии — минорно.
* **[L-ASAP4-D6]** OPEN: golden I/B без скриптовых golden'ов — добрать на live-приёмке при риске.
* Наблюдение (не debt): revision-outage после needs_fixes публикует документ с известными находками как degraded — в силе как следствие принятого ADR D3.5.

## Unavailable checks (round 2)

Без изменений round 1: live-acceptance §79/T-4449 и §50.62/§50.64 prose-quality/semantic-correctness реальных статей — PENDING OWNER (T-4449/T-4450, не закрываются этим gate'ом); поведение реальной LLM-модели на промпты Reviewer/Reviser — только live-метрики Wave E. Документарная верификация зависимостей не требовалась (дельта — stdlib-логика, новых зависимостей нет). OpenViking-память: релевантные ограничения зафиксированы в артефактах фичи; MEMORY_DELTA: нет.

## Вердикт round 2

**Approved (Wave D).** Блокер M-ASAP4-D1 закрыт минимальным точным фиксом (один guard `if invalid_ref or not refs` + R17-safe лог + нормализация needs_fixes→approved), покрыт негативными тестами обоих уровней и независимо воспроизведён моим репро: фантомная находка ревьюера больше не уводит хорошую детерминированно-валидную статью в Legacy — она публикуется first-pass без ревизий. Бонус-пин minor-not-Legacy закрыл [L-ASAP4-D2] с байт-синхронизацией канона. Регрессий нет: 10700/2 known, Wave D 71/71, соседи 357 + полное семейство summary 1124, F8 EXIT=0. Одобрение привязано к состоянию: HEAD `f04564b` + WTH `4675df09…` + spec `ab9dec94…`. Любое изменение кода/spec инвалидирует binding — новый gate. Следующая фаза контроллера — delivery (live-приёмка §50.62/§50.64 — T-4449/T-4450, вне этого gate).

---

# Round 1 (02.10.2026) — история, снято round 2 (выше) → **Needs Fixes (Wave D)**

> Каркас round 1 был верифицирован полностью (см. Checks 1–10 ниже); блокер один — M-ASAP4-D1, закрыт round 2. Текст ниже сохранён без изменений.

## Git base и inspected change scope (Wave D)

Base: HEAD `f04564b`, staged пусто, 1 stash (чужой, не тронут). Рабочее дерево = кумулятивный диф волн A–D; Wave D-объём инспектирован по `evidence.md` §D1–D2 + собственной сверке `git status`/дифов. Inspected полностью/построчно: новый `services/summary_l2_review.py` (881 строка — весь), дифы `summary_prompts.py` (канон R1029 + промпты Reviewer/Reviser), `prompt_migrations.py` (ступень R1028_ASAP4→R1029 + ROLLBACK), `summary_l2_writer.py` (evidence-валидация, id-space, roster, relations в `build_l2_input`, OFF-ветка цитат), `summary_generator.py` (L2-стадия review/paged/OFF, Q36-guard, paged-bypass, package_grade, coverage-прокидка), `summary_run_log.py` (health/stage_events/package_grade), `summary_fact_package.py` (kind/forward_source, package_grade, reduction-счётчики), `summary_l1_clusterizer.py` (is_forward/forward_source), `summary_legacy_fullwindow.py` (весь, 252 строки — coverage map), `mca_events.py`, `settings.py` (2 флага D), `conftest.py` (D-изоляция), `plans/docs/canon/architecture.md` (superseded-маркировка), новый `tests/test_summary_wave_d_asap4.py` (1359 строк, 69 тестов — весь), пин-тесты `test_summary_l2_writer.py`/`test_prompt_migrations.py`/`test_summary_asap21_prompt_migrations.py`/`test_summary_fact_package.py`.

## Checks performed (чек-лист T-4438 — все 10 пунктов, независимо)

1. **Промпт-миграция prose-first — ✓.** Активный канон `_SUMMARY_L2_WRITER_R1029_BASE`: запрета «Прямые цитаты не приводи» нет (строки 404/480 `summary_prompts.py` — исторические PREV-слепки R1027/R1028, не активный канон); prose-first/косвенная речь default/narrative continuity/«статья ≠ transcript» — есть; цитаты разрешены как редкий приём с доказанным source+speaker (soft guidance, §50.21 — без магического cap); «видимая действительность», модальность, стиль≠факт, evidence-секция, имена из пакета, числа high-risk, forward/reply/quote раздельно, финал — участник пакета. Слепок прод-канона `PREV_SUMMARY_L2_WRITER_R1028_ASAP4` байт-в-байт (пин: запрет есть в PREV, нет в активном; PREV не является new-каноном ни одной ступени — «двух противоречащих канонов нет», тесты 222/222 вкл. TestCanon). Ступень миграции `(PREV_*_R1028_ASAP4 → R1029)` в `PROMPT_MIGRATIONS` + ROLLBACK на PREV (идемпотентная механика ADR-1013-3, кастом не трогается). Эталон `architecture.md` — байт-тест (`SUMMARY_L2_REVIEWER_SYSTEM_PROMPT in canon`), старый канон помечен **superseded**. Legacy-промпт не менялся. PG DDL — 0 (миграция контента, Δ каталога = 0 — F8 EXIT=0 независимо).
2. **L2 output: evidence/roster/relations — ✓ (с оговоркой «≥1 ref» — задокументированная интерпретация).** `evidence_message_ids` аддитивно (schema_version 1; документы §99 v1.1 валидны), refs только из `package_message_id_space` = chronology ∪ facts.evidence ∪ fragments ∪ unassigned (service/budget исключены); invented/bитый тип → fail-closed `invalid_evidence` ДО Reviewer; несколько refs и shared evidence — разрешены (тесты). «≥1 ref на параграф» — НЕ жёсткий reject: отсутствие → счётчик `paragraphs_without_evidence` + deterministic finding Reviewer'у — принята как обоснованная интерпретация (§50.7 не требует ≥1 на каждый абзац; жёсткий reject сделал бы все v1.1-документы invalid — противоречило бы аддитивности ASAP-2.1; §50.2 «одна локальная проблема не сносит статью»). Roster `build_participant_roster` — из фрагментов, aliases при смене имени, дубли display-name не склеиваются (golden H), без author_id не пополняет. Relations `kind: msg|reply|forward|quote` (forward > quote > reply > msg) + `forward_source` до Writer/Reviewer (Q35 закрыт; is_forward только при наличии в row — синтетика бит-в-бит).
3. **Deterministic validator ДО Reviewer — ✓.** Порядок закреплён: структурно битый документ отбраковывается `validate_l2_document` внутри writer-вызова, Reviewer не вызывается (`test_deterministic_validator_before_reviewer_order`: reviewer.calls==0). Чек-лист 0-LLM: JSON/schema/unknown fields, invalid IDs (id-space), paragraph structure, evidence-ref existence, emphasis spans (канонизация/дроп), технические длины (200/900/498/32000), exact quote lookup + deterministic speaker mismatch (Wave C `process_paragraph_quotes`, реюз без форка), raw service IDs (strip). Mechanical repair (спан → дроп) без LLM — тест: ревизия не тратится (`l2_revision_count==0`).
4. **Semantic Reviewer — ⚠ (блокер M-ASAP4-D1).** Вердикт строго структурный JSON (`approved|needs_fixes|unusable` + findings{code,severity,paragraph_index,evidence_refs,instruction}); статью не пишет (промпт+parse). 15 кодов §50.12 полностью. Не источник истины: refs ⊆ id-space — invented ref → finding отброшен (тест); needs_fixes без валидных находок → approved (unknown > hallucinated, тест); unknown severity → blocking (консервативно). Style≠fact §50.26 — промпт-пин + golden G; числа/даты/timeline high-risk — промпт-пины §50.14/§50.15; title — factual surface (пин в обоих промптах); модальность — golden F. **НО: находка с ПУСТЫМ/отсутствующим `evidence_refs` НЕ отбрасывается** — см. Blocking findings.
5. **Bounded revision — ✓.** ≤2 ревизий / ≤3 ревью / бюджет ≤6 (константы + проверки перед каждым вызовом; golden потолка: ровно 6, автономных циклов нет). Patch-контракт `replace_paragraphs[{index,text,evidence_message_ids}]` primary — нетронутые абзацы байт-в-байт (тест), append `index==len` для major_topic_omitted (golden L); финальный документ проходит ПОЛНУЮ deterministic-ревалидацию (патч с invented-ref → invalid, тест). Instruction — preserve §50.22 (дословно) + конкретные findings. Первый-pass APPROVED не переписывается — golden M: ровно writer+reviewer=2 вызова, документ байт-в-байт черновик, `l2_first_pass_approved=1`. Progress criterion §50.25 — blocking не уменьшились → без Rev#2 сразу safe fallback (тест: 4 вызова, не 6). Сгоревшая (невалидная) ревизия не считается попыткой исправления — задокументировано + покрыто golden'ом потолка.
6. **Fail-soft — ✓ (интерпретации ADR подтверждены).** Reviewer outage (исключение/мусор-вердикт/слот-фейл) → deterministic-валидный документ публикуется `review_degraded` (`l2_review_degraded=1` + WARN `L2_REVIEW_DEGRADED` + health=degraded + stage-event degraded, не success) — два теста; «недоказуемый factual support → Legacy» покрывает deterministic-слой (в degraded уходят только его прошедшие) — соответствует ADR D3.5 и §50.29; provider/model fallback «по существующим правилам» выполняется внутри общего канала (`_dedicated_generate` наследует `LLM_FALLBACK_*` через `_post`) до outage-пути — пункт §50.29.2 соблюдён наследованием транзита. **Paged L2 bypass — честный:** `L2_REVIEW_SKIPPED reason=paged_l2` INFO + `health=degraded`, НЕ тихий; обоснование (бюджет ADR D3.3 фиксирован для writer=1; k≥2 страниц + review превысил бы ≤6) — корректное, принято. **ADR D5(б) «дважды невалидный патч → full-doc» — интерпретация Builder'а ПОДТВЕРЖДЕНА:** первая детерминированно-невалидная попытка патча активирует full-doc на СЛЕДУЮЩЕЙ ревизии (докстринг модуля + пин-тест `test_full_doc_escape_hatch_after_double_invalid_patch`); буквальное «дважды в patch-режиме» при бюджете ×2 съело бы весь бюджет на заведомо сломанный режим и сделало бы escape-hatch недостижимым; потолки ≤2 ревизий / ≤6 вызовов не меняются. Расхождение с буквой ADR — документировано, суть D5(б) (patch proven broken → full-doc) сохранена; ратификации формулировки ADR при следующем касании не требую (interpretation note достаточна).
7. **publication_status vs pipeline_health + append-only + метрики — ✓.** `RunContext.pipeline_health` (ok|degraded|failed) отделён от publish_status/status; `fail()` ставит failed только если health ещё None; L2-fail фиксирует `health=degraded` ДО `_legacy_fallback`, успешная Legacy-публикация не стирает («L2 rejected → Legacy used» живёт) — Q36 закрыт, пин исходника `_run_hybrid_l2` (ровно одна `"ok"` под guard). `stage_events[]` append-only (l2_reviewer/revision: stage/attempt/status/reason_code/started/finished/input/output/repair_target; тест append-only + порядок в golden'е). Метрики §50.58 все 7 + calls/degraded/dropped — в `L2Result.metrics` → лог `L2_REVIEW` (R17: только числа/коды — тест) → SUMMARY_COMPLETE `health=`/`package_grade=`/`coverage=` аддитивно; агрегаты 24h/7d — Wave E (T-4441, честно задокументировано).
8. **Kill-switches — ✓.** `SUMMARY_L2_REVIEW_ENABLED=false` → single-call run_l2, Reviewer/Revision не вызываются, документ = draft (тест); импорт review-модуля в генераторе — внутри `if review_on:` (OFF-путь модуль не импортирует). `SUMMARY_REVISION_PATCH_ENABLED=false` (master ON) → revision полным документом, ветка bounded, НЕ Legacy (тест). Промпт-rollback ROLLBACK_MIGRATIONS → `PREV_*_R1028_ASAP4` — паритет с флагом. Conftest: D-флаги OFF для всех не-asap4 тестов включая asap3x (обоснование: мок-каналы дают ложные degraded-пути — воспроизведено Builder'ом, инцидент 1089; прод-дефолт ON не менялся).
9. **Тесты — ✓ (прогнаны самостоятельно).** Полный pytest `tests --timeout=120 -q`: **10698 passed / 2 failed** (307.5s; оба failed — те же known pre-existing round1026 forbidden_paths, вне эпика). Wave D-файл + пины: **222 passed** (`test_summary_wave_d_asap4.py` 69 + writer/prompt_migrations/asap21/fact_package). Золотые осмысленны: A (reply-конфликт→ревизия, нетронутый абзац байт-в-байт, 4 вызова), D (wrong-speaker quote → deterministic repair + ревизия, не Legacy), E (unsupported number→ревизия), F (вопрос≠assertion), G (сарказм не бракуется, first-pass), H (дубли имён по ID), J (smoke 31+ фактов на review-петле; полный J — Wave C), L (topic omission→append-патч), M (first-pass = ровно 2 вызова, без rewrite). Целевые соседи — зелёные в составе полного сьюта (wave_c/coverage_asap31/l2_integration/incident_1089/generator и др.). F8 `--check`: **CHECK OK 488, EXIT=0**. Замечание: golden I (parallel topics) — промпт-пин `timeline_inconsistency` без скриптового golden, golden B (forwarded) — правило в каноне+код forward_attribution_error без скриптового golden — честно задокументировано Builder'ом (§D7.4); в обязательном списке гейта (A/D/E/F/G/H/J/L/M) их нет — принято; семантические коды для обоих сценариев в наборе есть.
10. **R17/EOL/BOM — ✓ (с одной неточностью evidence).** R17: логи `L2_REVIEW`/`L2_REVIEW_DEGRADED` — только числа/коды/id (тест + собственный grep); findings/prompt-тексты/секреты в логах нет; `SUMMARY_L2_REVIEWER_API_KEY` не логируется (только hot-алиас). BOM: во всех 18 файлах манифеста Wave D нового BOM нет; **поправка к evidence §D1** («BOM отсутствует во всех 16 файлах»): `tests/test_summary_l2_writer.py` имеет BOM, но он **pre-existing в HEAD** (проверено байтами `git show HEAD:`) — волной D не внесён, заявление неточно (L-ASAP4-D4). EOL: новые файлы LF; правки в конвенции HEAD; `git diff --check` — известный cr-at-eol артефакт на CRLF-конвенционных файлах + trailing-whitespace флаги на добавленных строках `summary_fact_package.py` (i/mixed-конвенция файла; поведение не меняет).

## Requirement/evidence coverage (§83 semantic 21 пункт)

| # | Пункт §83 | Статус |
|---|---|---|
| 1 | direct-quote prohibition удалён из Hybrid prompt | ✓ (канон R1029, пин-тесты, PREV-слепок) |
| 2 | prose-first остаётся default | ✓ (канон: «Основной формат — связный рассказ», transcript-запрет) |
| 3 | verified direct quote допускается | ✓ (§50.20-после Wave C + §54-тест; канон разрешает доказанную цитату) |
| 4 | named-quote validator bug устранён | ✓ (Wave C, OFF-паритет матрицы §50.20) |
| 5 | deterministic validator до semantic Reviewer | ✓ (тест порядка, reviewer.calls==0) |
| 6 | semantic Reviewer не придумывает evidence | **⚠ M-ASAP4-D1**: refs ⊆ id-space и invented отбрасываются, но находка с ПУСТЫМИ refs проходит |
| 7 | Writer findings возвращаются на targeted Revision | ✓ (needs_fixes → patch primary, preserve-инструкция) |
| 8 | максимум две revision итерации | ✓ (MAX_REVISIONS=2 + бюджетный потолок, golden'ы) |
| 9 | single local error не уничтожает хороший draft | ✓ (patch байт-в-байт нетронутых, quote-repair, emphasis-дроп) |
| 10 | wrong-person attribution ловится | ✓ (golden A + код) |
| 11 | unsupported numbers ловятся | ✓ (golden E + промпт-пин high-risk) |
| 12 | question/modality не превращаются в факт | ✓ (golden F + канон + factual_overstatement) |
| 13 | forward/reply attribution сохраняется | ✓ (kind/forward_source до L2 + коды + канон-правила) |
| 14 | major topic omission ловится | ✓ (golden L, append-патч) |
| 15 | 600–700+ source considered 100% | ✓ (Wave C §74-тест K: considered=688, coverage 100%) |
| 16 | article — выжимка, не transcript | ✓ (канон-запрет стенограмм + длины + duplicate_event) |
| 17 | first-pass healthy не переписывается без причины | ✓ (golden M) |
| 18 | Reviewer outage не single point of failure | ✓ (review_degraded fail-soft, §50.29/ADR D3.5) |
| 19 | успешный Legacy не стирает историю L2 failure | ✓ (health-ось, Q36-пин) |
| 20 | approved text не регенерируется из-за Cover/formatter failure | ✓ (REUSE: ladder Wave B §70–72, formatter-ladder не тронуты; новой регенерации в Wave D нет) |
| 21 | §50.64 no-false-quality | см. ниже «§50.64-проверки» |

## Focused audit coverage

Критические зависимости/кромки: общий транзит `summary_l2_writer` (`_make_llm_call`/`_dedicated_generate` → `LLM_FALLBACK_*`) — reviewer/revision наследуют fallback-политику и R17-семантику канала; `validate_l2_document` — единая точка ревалидации патчей (id-space/длины/цитаты повторно применяются к заменённым абзацам); интеракция conftest-изоляции D с asap3x-каркасами (мок `run_l2`) — изоляция не меняет прод-дефолты; `metrics.update(draft_metrics)` — merge draft-метрик в review-результат (quote-счётчики не теряются); generator `calls_so_far += 1 + extra` — честный R17-счётчик; `_legacy_fallback` closure — `package_result` проинициализирован до try (exception-пути безопасны); диф-контекст ревью (emphasize) объявлен, но не активирован в loop'е (повторное ревью смотрит весь документ — безопасное упрощение, токен-бюджет в рамках ≤6). Проверено отсутствие второго resolver'а/pipeline/словаря reason codes (единый REASON_CODES; quote — extension MCA-22 без форка).

## Counterexamples checked (негативные сценарии)

1. **Фантомная находка без refs** (галлюцинация ревьюера, `evidence_refs: []`) → needs_fixes валиден → ревизия → нет прогресса → **`l2_review_rejected` → Legacy для детерминированно-валидной статьи** — воспроизведено моим скриптом вне тестов Builder'а → **[M-ASAP4-D1]**.
2. **Invented ref в находке** → finding отброшен; единственная находка → вердикт approved (нет основания) ✓ (тест).
3. **Reviewer timeout / мусор-вердикт** → degraded-публикация, документ не потерян, health=degraded ✓ (2 теста).
4. **Патч с invented evidence-ref** → `revision_invalid_patch` → полная deterministic-ревалидация отвергает ✓; вторая ревизия — full-doc (D5(б)-интерпретация) ✓ (тест).
5. **Бюджетная осада** (rev1/rev2 всегда needs_fixes с уменьшением blocking) → ровно 6 вызовов → Legacy без автономного цикла ✓ (тест потолка).
6. **OFF-паритет** → 0 вызовов Reviewer, draft как есть ✓; генератор OFF не импортирует review-модуль ✓ (по коду).
7. **Отсутствие refs у абзаца** → НЕ invalid (аддитивность v1.1), счётчик + deterministic finding ✓ (тест `test_paragraph_without_evidence_is_soft`).
8. **`unusable`-вердикт** → немедленный Legacy без ревизий ✓ (тест) — перечень §50.2 соблюдён.
9. **needs_fixes только с minor-находками** → ревизия, затем без «прогресса по blocking» (0→0) → Legacy — консервативный, bounded исход; пограничная интерпретация §50.25 (критерий о blocking) — зарегистрировано как [L-ASAP4-D2], направление безопасное (не публикует спорное, а уводит в Legacy), рекомендация — промпт-пин «minor-only → approved».

## Blocking findings

### [M-ASAP4-D1] [Medium, requirement-blocking] `parse_review_verdict` пропускает находки БЕЗ доказательств (пустые/отсутствующие `evidence_refs`)
* **Где:** `services/summary_l2_review.py:288-302` (цикл валидации refs: пустой список/отсутствующее поле → `refs=[]` → finding сохраняется).
* **Требование:** spec §4 D.4/§50.11 — «finding валиден только с refs ⊆ package (или deterministic rule)»; чек-лист гейта T-4438 п.4 — «находки БЕЗ доказательств из пакета отбрасываются (не источник фактов)»; собственный промпт Reviewer: «находка без refs из пакета или с выдуманным ID недействительна»; докстринг модуля: «finding валиден только с refs ⊆ id-space пакета (доказательственная база)».
* **Наблюдение (воспроизведено):** `parse_review_verdict` с находкой `{"code":"unsupported_number","severity":"blocking","evidence_refs":[]}` (и вариант вообще без поля) возвращает `needs_fixes` с 1 валидной находкой, `dropped=0`. Все 15 кодов §50.12 допускают refs (golden L использует refs для major_topic_omitted) — «законных» без-ref находок в наборе нет; deterministic-правило в вердикт-схеме не представимо. Асимметрия подтверждает недосмотр: invented-ref отбрасывается, а без-ref — нет.
* **Impact (репро):** фантомная blocking-находка без доказательств запускает ревизию; хорошая детерминированно-валидная статья не может «исправить» несуществующее замечание → progress criterion → **`l2_review_rejected` → Legacy** (мой скрипт: `status=invalid, legacy_after_review=1`). Это ровно тот вред, от которого §50.11 защищает («Reviewer не имеет права создавать новую истину»), и прямое нарушение критерия гейта.
* **Fix:** в `parse_review_verdict` отбрасывать находку при `not refs` (одна строка рядом с `if invalid_ref:`) + негативный тест (пустые refs и отсутствующее поле → dropped, needs_fixes→approved при единственной такой находке).
* **Verification:** новый тест + повторный прогон `TestReviewVerdictParsing` и golden-набора + мой репро-скрипт (должен давать `approved`-исход либо findings=0).

## Non-blocking debt

* **[L-ASAP4-D2]** needs_fixes с только minor-находками → после одной безпрогрессной ревизии Legacy (§50.25 сформулирован о blocking). Направление безопасное; рекомендация — пин в промпт Reviewer («нет blocking — approved») при следующем касании промпта.
* **[L-ASAP4-D3]** `services/summary_generator.py:743` — склеенная строка `search_long_term(            chat_id, …` (артефакт правки; синтаксически валидно, поведение не меняет). Поправить при следующем касании файла.
* **[L-ASAP4-D4]** evidence.md §D1 «BOM отсутствует во всех 16 файлах» неточно: `tests/test_summary_l2_writer.py` — pre-existing BOM из HEAD (волной D не внесён). Поправить формулировку при следующем касании evidence.
* **[L-ASAP4-D5]** `_deterministic_findings(draft)` не пересчитываются после ревизии — повторное ревью видит deterministic-находки исходного черновика (контекстная подсказка, не решение); минорно.
* **[L-ASAP4-D6]** Golden I/B без скриптовых golden'ов (промпт-пины/коды есть) — честно задокументировано; добрать скриптовые сценарии при живой приёмке §50.62/§50.64 (T-4450), если LLM-поведение покажет риск.
* Наблюдение (не debt): revision-outage после needs_fixes публикует документ с известными находками как degraded — в рамках буквы ADR D3.5 (deterministic пройден, refs валидны) и §50.24 (runtime failure → §50.29); телеметрия честная (findings_total, stage-events error, health=degraded). Принято как следствие принятого ADR-баланса; при желании ужесточить — отдельное ARCH-решение, не rework.

## §50.64-проверки: что верифицировано без прода, что отложено на live (честно)

**Верифицировано на коде/тестах (этот gate):**
- структурный вердикт + отбрасывание недоказуемых находок — механика есть, **кроме дыры M-ASAP4-D1**;
- invented evidence ID → validation error (writer, patch, full-doc — три слоя);
- bounded ×2, бюджет ≤6, progress criterion, first-pass без rewrite (golden M);
- fail-soft outage → review_degraded / Legacy-развилка по ADR D3.5;
- kill-switch OFF-паритеты (обе), OFF-путь без импорта review-модуля;
- health/publication separation, append-only stage history, «Legacy не стирает L2-отказ» (Q36);
- факт-правила в каноне/промптах (forward/reply/quote, модальность, стиль≠факт, title factual, имена из пакета, числа high-risk, финал из roster) — пин-тестами;
- quote-repair интеграция (golden D), coverage map §50.32, package grade §50.30 (degraded виден);
- R17 (логи без текстов/секретов), полный сьют 10698/2, F8 EXIT=0.

**Отложено на live/прод (PENDING OWNER / T-4449 / T-4450 — не закрывать этим gate'ом):**
- **§50.62 prose-quality** (читается как рассказ, абзацы=события, нет transcript-стены, цитаты редкие и оправданные, голос бота, грамматика) — оценивается только на реальных статьях живого L2; каркас (промпт-правила + golden-верdict'ы) готов, качество прозы не доказуемо unit-контуром;
- **§50.64 semantic correctness реальных статей** (люди не перепутаны, факты не выдуманы, темы не потеряны на живых окнах 600–700+) — live acceptance, платные вызовы;
- реальное поведение LLM-ревьюера по промпту (доля отброшенных/фантомных находок, first-pass approval %, распределение кодов) — только live-метрики 24h/7d (Wave E T-4441);
- latency/стоимость второго LLM-вызова на каждом саммари — прод-наблюдение;
- фактическая частота paged-L2 bypass в реальных окнах (редкий деградационный путь).

## Unavailable checks

* Live-acceptance §79/T-4449 (окно 600–700+, реальные статьи) и §50.62/§50.64 — PENDING OWNER (платные вызовы); R4-D-062/D-064 закрываются T-4450 после live, не этим gate'ом.
* Поведение реальной LLM-модели на промпты Reviewer/Reviser (unit-контур тестирует детерминированную механику на инъекциях — честно задокументировано Builder'ом §D8).
* Документарная верификация внешних зависимостей не требовалась (новых зависимостей нет; только stdlib + внутренние модули). OpenViking-память: релевантные ограничения уже зафиксированы в принятых артефактах фичи (spec/ADR/conflict-audit — прочитаны и сверены); MEMORY_DELTA: нет.

## Вердикт round 1 (исторический, снят round 2)

**Needs Fixes (Wave D).** Ядро волны добротное: миграция промпта с живым ROLLBACK, deterministic-слой до Reviewer, честный bounded-цикл с реальным бюджетным потолком, корректные fail-soft развилки, разделение health/publication с append-only историей, рабочие OFF-паритеты и осмысленный золотой набор — всё подтверждено независимо (10698/2, 222 целевых, F8 EXIT=0, собственные репро). Один requirement-блокер: валидатор вердиктов не отбрасывает находки без доказательств (M-ASAP4-D1) — фантомная находка ревьюера может увести хорошую статью в Legacy, что нарушает §50.11 и пункт 4 семантического чек-листа владельца. Fix — одна строка + негативный тест; после него — повторный gate по затронутой проверке (TestReviewVerdictParsing + golden'ы + репро), полный pytest не требуется, если диф не выйдет за `summary_l2_review.py` + тест. Формулировки evidence/задач честные (§84): «prose-quality/no-false-quality» нигде не заявлены закрытыми — корректно помечены к live. *(Round 2: диф остался в пределах рецепта, полный pytest всё равно прогнан — 10700/2.)*

**Binding:** одобрение/запрос фикса привязаны к HEAD `f04564b` + WTH `a89ee325…` + spec `ab9dec94…`. Любое изменение кода/spec вне fix'а M-ASAP4-D1 инвалидирует привязку.

---

# ASAP-4 — review.md (Wave A Reviewer gate, T-4413)

> **Feature-ID:** `asap-4-embedding-graphrag-cover-runtime` — Wave A (зона A, Embedding Control Plane, T-4402…T-4412)
> **Risk-Level:** R3 (spec §83/T-4413 gate)
> **Status: Approved (Wave A)** — gate round 2 (02.10.2026): все 4 блокера round 1 закрыты и независимо верифицированы; blocking 0. Каркас-оценка round 1 в силе. История round 1 (Needs Fixes) — ниже в этом файле.
> **Дата:** 02.10.2026. Ревью выполнено независимо (Reviewer): код Builder'а не правился, тесты прогнаны самостоятельно.

## Binding

| Поле | Round 2 (действующий) | Round 1 (историческое) |
|---|---|---|
| Reviewed-Commit | `f04564b2104cb42057fc363fa5d469d7d09af4be` (HEAD; фича — некоммитнутый рабочий-диф; HEAD не менялся) | тот же |
| Working-Tree-Hash | `513d0a1aaaf63a990f1e7280a454671ad4dd77849a81fc3fec379afb46914d00` | `d4239cf00a31185dbc98788a77df34f465988d4a8eaa84ff945240bd04ea821c` |
| Spec-Hash | `ab9dec9451cdd6a003984f4ab28d3e73a4e1da367ebfaa4d5ce1d1d0b8ea1d10` (spec изменён в реворке: ратификация лестницы §A.1, spec.md:50) | `f1a3f3bbe8760f23d27e272cd93532b95cea24dfebca9f92e1672c50ac18d665` |

Рецепт WTH round 2 (детерминированный, воспроизводимый): SHA-256 от UTF-8-манифеста — по одной строке `path␣␣hash␣␣(origin)` на файл, отсортировано по пути; для 12 modified tracked feature-файлов hash = SHA-256 их `git diff -- <path>` (origin `git-diff`), для 2 новых файлов hash = SHA-256 полного содержимого (origin `content`). Состав (14): `config/settings.py`, `pytest.ini`, `services/database.py`, `services/embedding_control_plane.py` (content), `services/graphrag_rebuild.py`, `services/llm_client.py`, `services/mca_events.py`, `services/summary_memory.py`, `tests/conftest.py`, `tests/test_embedding_control_plane_asap4.py` (content), `tests/test_mca01_tx_task_supervisor_round1027.py`, `tests/test_mca05_episodes_stories_round1027.py`, `tests/test_mca22_core_round1027.py`, `web/api/memory_agi.py`. Исключены (задокументировано, не feature-код): `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/workflow_state.md` (чужие pre-existing правки), `plans/reports/full_audit_results.md` и настоящий review.md (артефакты ревью, пишутся после кода), чужие untracked (`node_modules/`, `.playwright-mcp/`, `extra_images/`, `package*.json`). В отличие от round 1 список файлов манифеста теперь явный (round-1 рецепт «15 modified tracked» был неоднозначен по составу — см. round-1 текст ниже; байтовая привязка round 1 не переиспользуется).

Реворк round 1 затронул ровно 4 файла манифеста: `llm_client.py`, `graphrag_rebuild.py`, `tests/test_embedding_control_plane_asap4.py` (content) + вне манифеста plans-доки (spec.md/evidence.md/tasks.md). Остальные 11 — byte-идентичны round-1 ревью-состоянию по составу диффа (проверено `git diff --stat` и построчным осмотром дельт).

---

# Round 2 (02.10.2026) — дельта-реворк-проверка → **Approved (Wave A)**

> **Feature-ID:** `asap-4-embedding-graphrag-cover-runtime` · **Risk-Level:** R3 · **Status: Approved (Wave A)**
> **Reviewed-Commit:** `f04564b2104cb42057fc363fa5d469d7d09af4be` · **WTH:** `513d0a1aaaf63a990f1e7280a454671ad4dd77849a81fc3fec379afb46914d00` · **Spec-Hash:** `ab9dec9451cdd6a003984f4ab28d3e73a4e1da367ebfaa4d5ce1d1d0b8ea1d10`
> Объём: ТОЛЬКО дельта реворка round 1 (каркас-оценка round 1 в силе). Код Reviewer'ом не правился, не коммитился; все тесты прогнаны самостоятельно.

## Git base и inspected change scope (round 2)

Base тот же: HEAD `f04564b`, staged пусто. Дельта реворка по `git status`/диффам: `services/llm_client.py` (allowlist `_post`), `services/graphrag_rebuild.py` (`_FAILURE_CAS_FROM`, `_apply_pause`, ветки control-plane в `_handle_build_failure`, узкий except query-вектора), `tests/test_embedding_control_plane_asap4.py` (+8 тестов, блок 1165–1433), plans-доки (spec.md §A.1, evidence.md §2/§5/§10, tasks.md T-4403). Inspected полностью: все четыре код-зоны дельты построчно + смежные контракты (`embed_once` 1405–1464, executor `embedding_control_plane.py:995–1105`, status-машина 63–99, `_ensure_job`/resume 1440–1530).

## Checks performed (round 2, все независимо)

1. **H-ASAP4-1 — ЗАКРЫТ.** Allowlist-семантика на настоящем `_post` (`llm_client.py:706-718`: `None` → бит-в-бит прежний сет 408/425/429/5xx; кортеж → только перечисленное; `() `→ ни одного статус-ретрая), единая terminal-классификация `778-813` (429 → `LLMRateLimitError` с headers/body in-memory БЕЗ сна; 5xx → `LLMServerError`, диаг-лог только на legacy-пути). **Мой независимый репро на реальном `_post` (httpx.MockTransport, вне тест-файла Builder'а):** `()` + 429 (RA=20) → ровно 1 HTTP-вызов, `sleeps=[]`, RA='20' и тело наверху в исключении ✓; `None` + 429 → 2 вызова, сон ровно `min(20, cap=8)=8.0` ✓ (legacy-паритет); `(503,)` + 503 → 2 вызова, `(503,)` + 429 → 1 вызов ✓; `()` + 503 → 1 вызов без сна ✓; `()` + transport-error → 2 попытки (transport-retry от параметра не зависит) ✓. Quota-логики на HTTP-слое нет: `_post` только классифицирует и бросает типизированные исключения; kind/RPM/TPM/cooldown — исключительно `embedding_control_plane.classify_rate_limit`/executor; `retry_statuses` используется только `embed_once` → adapter (`ecp:833`). Тесты Builder'а (3 шт., блок 1216–1276) зелёные в составе 50/50.
2. **H-ASAP4-2 — ЗАКРЫТ.** `graphrag_rebuild.py:1279-1331`: явные isinstance-ветки ДО эвристик по именам — `EmbeddingGroupCoolingDown` → `paused_rate_limit` с `next_allowed_at` из исключения (без повторной классификации тела; exc_next ≤ now → дефолт-кулдаун), `EmbeddingBudgetExhausted`/`EmbeddingConcurrencyBusy` → `paused_provider` (delay min(дефолт×2, ceiling 300)). Общая механика — `_apply_pause` (1207-1229): CAS от фактического статуса + result_ref-bookkeeping (pause_started_at/pause_count) + pause-колонки реестра v23 + событие + `_schedule_auto_resume`; checkpoint не трогается. Негативный тест без HTTP (`test_cooling_group_between_batches_pauses_not_fails`, 1283-1332: CoolingDown(+120s) между батчами): `paused_rate_limit` (НЕ failed), `pause_reason=rate_limit:quota_group`, `next_allowed_at ≥ now+100s`, `attempts_total=1`, checkpoint `processed=2` сохранён, авто-resume запланирован ✓. Бюджет/busy → `paused_provider` (параметризованный тест 1336-1362) ✓. Реалистичность подтверждена кодом: executor действительно бросает CoolingDown без HTTP (`ecp:1032-1038` — scheduler-acquire по `group_blocked`). Контракт test-double честен.
3. **M-ASAP4-3 — ЗАКРЫТ.** `_FAILURE_CAS_FROM` (94-95) = {building, running, checkpoint, validating, validated}; `_handle_build_failure` читает фактический статус на входе (1252-1258), expect = фактический для build-активных, `ST_RUNNING` для терминальных/паузных (безопасный no-op). Horizon — первая проверка (1259-1267), не зависит от стадии; pause-bookkeeping накапливается на любой стадии → «вечный checkpoint» ограничен 24h-горизонтом. Тест (`test_post_checkpoint_validation_exception_honest_terminal`, 1366-1393): RuntimeError на sample-fetch в `_validate` после CAS→CHECKPOINT → честный `failed`/`RuntimeError` ✓ (до фикса — вечный checkpoint).
4. **M-ASAP4-4 — ЗАКРЫТ.** Узкий except вокруг построения query-вектора (`graphrag_rebuild.py:733-742`) → `knn_query_vector_failed`, `stage=query_vector_build`, `query_vector_ok=false`; MATCH — отдельный try (744-759) → по-прежнему `knn_index_schema_mismatch` с `query_vector_ok=true`. Все 7 кодов §A.6 достижимы тестами: source_empty (833), vec_extension_missing (848), dim_mismatch (863), row_corrupt (884), zero_results (901), index_schema_mismatch (935 — старый тест не тронут, зелёный), query_vector_failed (1414 — новый; несериализуемый вектор с корректным len проходит dim-гейт) ✓.
5. **Не-блокеры:** M-ASAP4-5 (evidence-честность) — исправлено: §2/§5 больше не заявляют изменение `test_graphrag_rebuild_asap32.py`; подтверждено `git status` — файла в диффе нет, 9/9 зелёные. L-ASAP4-6 — лестница ратифицирована в spec.md:50 (§A.1 уточнение: label → unknown, 2 ступени; соответствует реализации `parse_quota_group_labels`/`resolve_quota_group` и прод-фактам Q1/Q8). **L-ASAP4-7** (`load_group_states` без прямого теста) — Wave A НЕ блокирует: worst case после рестарта group-cooldown теряется и переучивается консервативно на первом же 429 (burst-дефолт 20s), restart-resume самой джобы покрыт §68-тестами; остаётся debt. **L-ASAP4-8** (вестижный always-true assert) — НЕ блокирует: сдвинулся на строки 638-639, реальная проверка shadow-строк идёт следом (640-642), тест зелёный; косметика.
6. **Прогоны (все самостоятельно):** asap4-файл **50/50** (12.8s); соседи — `asap32+graphrag_memory+graphrag_database+mca07` **272 passed**, `llm_client+circuit_breaker+react_asap31+summary_memory+database` **325 passed**; полный pytest — **10570 passed / 2 failed** (296.65s; оба failed = те же known pre-existing round1026 forbidden_paths). F8 `--check` → `CHECK OK: реестр 488`, **EXIT=0**.

## Counterexamples checked (round 2)

1. **429 на реальном HTTP-слое при `()`** → 1 вызов, без сна, RA наверху — воспроизведено моим скриптом (см. п.1). Регресс-тест уровня `_post` в файле — закреплено.
2. **CoolingDown между батчами без HTTP** → paused, не failed — негативный тест воспроизведён в 50/50 прогоне.
3. **Исключение на validate-стадии после CAS→CHECKPOINT** → честный terminal — тест воспроизведён.
4. **Query-вектор бит при живом индексе** → 7-й код, не маскировка — тест воспроизведён; старый schema_mismatch-тест зелёный.
5. **None-паритет**: сон min(RA,cap)=8.0 и 2 вызова — бит-в-бит legacy подтверждён моим репро (не сломали chat-путь: llm_client-соседи 325 passed).
6. **TOCTOU в `_handle_build_failure`** (чтение статуса → CAS): окно сужено CAS-предусловием; при одном процессе (Q5) + lease гонка классификации одной джобы недостижима — принято.

## Requirement/evidence coverage (round 2)

* R4-A-004…009 (executor/429) — теперь полностью ✓ (retry-ownership на обоих слоях зажат тестами).
* R4-A-022…025 (state machine/AM-1) — полностью ✓ (CoolingDown/Budget/Busy → paused_*; пост-checkpoint честен; horizon ограничивает).
* R4-A-026…028 (KNN) — 7/7 кодов ✓.
* §64-потолок «не 21» — на реальном пути: executor-бюджет 4 (тест) + нижний слой 1 вызов/attempt (новые `_post`-тесты) → комбинированный потолок соблюдён; сквозной §64-фикстуре через настоящий `_post` остаётся связочная композиция (задокументировано evidence §10.8, принято — оба слоя независимо запинены).
* §83-gate, §84 no-false-acceptance — в силе round 1; формулировки evidence §10 соответствуют действительности (проверено построчно).

## Focused audit coverage (round 2)

Критические зависимости дельты: `embed_once`→`_post` контракт (сигнатура не менялась, default `()` только у embed-пути; chat-путь `None` — паритет подтверждён тестами 325); interaction `_apply_pause` ↔ registry/resume ↔ `_ensure_job` (§68-семантика не сломана — тесты зелёные); `_schedule_auto_resume` re-arm по свежему `next_allowed_at` из реестра (344-350) — cooldown-продление покрыто; R17: 429-headers/body только in-memory у исключения (790-791), в логах нет — grep дельты чист.

## Blocking findings (round 2)

Нет. Все 4 блокера round 1 (H-ASAP4-1, H-ASAP4-2, M-ASAP4-3, M-ASAP4-4) — RESOLVED и независимо верифицированы (см. Checks performed 1–4).

## Non-blocking debt (переносится)

* **[L-ASAP4-6]** закрыт ратификацией spec.md:50 (проверено) — снят.
* **[M-ASAP4-5]** закрыт (evidence §2/§5 исправлены честно; подтверждено git status) — снят.
* **[L-ASAP4-7]** OPEN: прямой тест `REGISTRY.load_group_states` — рекомендовать в Wave B/E или ops-hardening (не блокирует, обоснование в п.5).
* **[L-ASAP4-8]** OPEN: вестижный assert (теперь `test_embedding_control_plane_asap4.py:638-639`) — косметика при следующем касании файла.
* **[L-ASAP4-9]** OPEN (вне атрибуции Wave A): нестабильность полных прогонов воспроизведена и в этой сессии — первый полный прогон упёрся в известное зависание (~72%, pytest-timeout убил процесс), контрольный `-v` прогон чист 10570/2 за 296s. DevOps учесть перед релизным прогоном.

## Unavailable checks (round 2)

Без изменений относительно round 1: live-acceptance §34/§77 (PENDING OWNER), `EMBED_ASYNC_BATCH_ENABLED=ON` (default OFF, live-гейт до включения), multi-process lease под реальным вторым процессом (DevOps на деплое; по коду инвариант держится). Документарная верификация зависимостей не требовалась (новых зависимостей нет). MEMORY_DELTA: нет.

## Вердикт round 2

**Approved (Wave A).** Реворк round 1 закрывает все 4 блокера точно по предписанным fixed-рецептам, без побочных регрессий (полный сьют 10570/2 known, соседи зелёные, F8 чист). Одобрение привязано к состоянию: HEAD `f04564b` + рабочее дерево WTH `513d0a1a…` + spec `ab9dec94…`. Любое последующее изменение кода/spec инвалидирует binding — новый gate. Следующая фаза контроллера — delivery (передача DevOps: деплой-гейты live-acceptance/async-batch/multi-process — см. Unavailable checks).

---


## Git base и объём inspected changes — ROUND 1 (история, до реворка)

* Base: HEAD `f04564b` (`docs(plans): mca-22 … archive`), прод-эквивалент 2.58.44, SQLite v22.
* Рабочее дерево: 15 modified tracked + 2 новых файла; `git diff --stat` = 1167(+)/107(−); staged — пусто. Inspected полностью: `embedding_control_plane.py` (1559 строк, весь), полные дифы `llm_client.py`, `summary_memory.py`, `graphrag_rebuild.py`, `database.py`, `settings.py`, `mca_events.py`, `conftest.py`, `memory_agi.py`, новый тест-файл (1160 строк, весь), изменённые пины mca-01/05/22.

## Checks performed — ROUND 1 (история, до реворка)

1. **Executor — единственный retry-owner (A.2):** оркестрационный слой — да (budget `_ATTEMPT_BUDGET=4`, 429 → defer по `next_allowed_at` с bounded `max_defers`, transport-backoff min(1·2ⁿ,8) только на transport; демонтаж 3-аттемпного цикла `_embed_api` при ON; `embed()`-каскад не вызывается). **НО на реальном HTTP-пути контракт нарушен — [H-ASAP4-1].**
2. **Quota-группы (A.1):** лестница §5 — developer label (hot/env) → `unknown`; safe default «все unknown = 1 группа» ✓ (тест); group cooldown (`embedding_quota_state` v23 + in-memory, `group_blocked`, тот же group другим ключом не дёргается ✓ тест §64); key health 6 состояний ✓; 401/403 → `auth_failed` без ретраев как 429 ✓ (тест). Лестница: шаги 1–2 (provider runtime metadata / Connections layer) слиты в один label-источник — задокументировано в коде, соответствует прод-фактам Q1/Q8, формальное отклонение от текста спеки → [L-ASAP4-6].
3. **429-классификация (A.2/§9):** RPM/TPM/daily/spend/unknown по безопасным маркерам тела ✓; честный Retry-After `min(provider, 300)` ✓ (тесты: RA=30→30, RA=9999→300; НЕ min(30,8) на уровне executor). Подрыв нижним слоем — в [H-ASAP4-1] (первый нижнеуровневый ретрай 429 спит min(RA, backoff_cap=8) — анти-паттерн §9/Q4).
4. **State machine §26/AM-1 (A.5):** 429 → `paused_rate_limit` (не terminal) ✓ в основном пути (тесты §68: checkpoint preserved, registry pause-колонки, next_allowed, horizon 24h, resume той же generation без дублей — воспроизведено мной). Terminal FAILED только по §25 ✓ (auth_invalid, retry_horizon_exhausted, deterministic, fingerprint_changed/missing_vectors — structural в обоих режимах). Дыры классификации — [H-ASAP4-2] и [M-ASAP4-3]. FTS serviceable во всех non-active ✓ (gate `_index_generation_ok`, ретрив-код не тронут).
5. **KNN (A.6):** distinct reason codes вместо generic ✓ — 6 из 7 воспроизводимы и покрыты тестами; `knn_query_vector_failed` недостижим ([M-ASAP4-4]); validation_failed сохраняет векторы ✓ (тест: shadow на месте, 2 строки).
6. **Scheduler/lease (A.4):** P0–P3 ✓; P3 = idle-capacity (active_high==0 && waiting_high==0) — surplus/preemption на границе слотов ✓ (тесты §67 + surplus); AIMD cold=1, +1/20 успехов, 429→÷2, cooldown→0, в developer bounds ✓; adaptive batch: GRAPHRAG_REBUILD_BATCH = старт И потолок (осознанное, задокументированное в коде и evidence §9 отклонение в безопасную сторону); burst≠exhausted ✓ (§21-тесты); lease через `task_jobs`+`write_transaction` (Redis нет) ✓; двухпроцессная взаимная исключение доказуема по коду: partial UNIQUE index `idx_task_jobs_coalesce_active (coalesce_key) WHERE status IN ('queued','running')` гарантирует ≤1 активную lease-строку, проигравший acquire строки не оставляет (INSERT OR IGNORE игнорируется), stale-takeover (900s) — UPDATE+INSERT в одной транзакции, верификация единственной running-строки ✓; lease-busy → job назад в queued БЕЗ schedule-цикла (return до try/finally) — retry-storm нет.
7. **DDL v23 (§7):** строго additive ✓ — `CREATE TABLE IF NOT EXISTS embedding_quota_state`, 3×`ALTER ADD COLUMN` под guard `PRAGMA table_info`, 0 UPDATE существующих строк, идемпотентность (двойной прогон в тесте), PG no-op (в дифе 0 PG-кода), reader-SELECT'ы реестра расширены (совместимо: миграция штатным раннером до первого чтения).
8. **Kill-switches (§8.2):** ровно 5 флагов зоны A (4 ON + `EMBED_ASYNC_BATCH_ENABLED` default OFF ✓ тест); OFF-паритет подтверждён тестами (master → legacy 3-цикл + honest-terminal rebuild; cooldown-OFF → ротация ключей; scheduler-OFF → без priority-jump; adaptive-OFF → статические BATCH/SLEEP) + conftest-изоляция `_asap4_flags_off_by_default` с патчем обоих классов Settings (S10.18-10 reload-подмена закрыта) — весь 10.5k-сьют идёт legacy.
9. **R17 (§0.3):** в логах только алиасы/credential_id/group/kind ✓ (grep по новым log-вызовам чист); headers/body 429 прикладываются к исключению in-memory, не логируются ✓; панели `/api/memory/embeddings` — aliases only, `require_global_admin` ✓ (тесты R17).
10. **Тесты (воспроизведены самостоятельно):** полный pytest `tests --timeout=120 -q` → **10562 passed / 2 failed** (обе known pre-existing round1026 forbidden_paths) — воспроизведено на -v прогоне; отдельные прогоны: 42/42 asap4, neighbors 426 passed (graphrag_rebuild_asap32 9, graphrag_memory+database 220, mca07 43, пины mca-01/05/22); F8 `--check` → `CHECK OK: реестр 488`, EXIT=0. Фикстуры §64–§69/§35 осмысленны и соответствуют R4-A-033/036…041. Замечания по стабильности прогона — [L-ASAP4-9].
11. **Соседи:** graphrag/summary_memory/database — без регрессий (426 + полный сьют); `EMBEDDING_GENERATION_*`/mca_events +18 reason codes в контракте §17.2 ✓.
12. **Спец-внимание:** (а) lease при двух процессах — см. п.6, взаимная исключение держится на partial UNIQUE index; (б) single-credential пул: transport-фейл не крутит executor (4 вызова → BudgetExhausted), 429 → group cooldown → CoolingDown наверх без спина ✓ на уровне executor — но наверху см. [H-ASAP4-2]; (в) `include_failed=False` в post-release schedule ✓ (failed/validation_failed не переоткрываются — retry-storm упавших нет); стартовый/авто-resume schedule остаётся bounded (конверсия quota-failed → paused, horizon).

## Requirement/evidence coverage

* R4-A-001…010 (pool/лестница/health) — покрыто кодом+тестами ✓.
* R4-A-004…009 (executor/429) — **частично: [H-ASAP4-1] нарушает retry-ownership на HTTP-пути**.
* R4-A-015…021 (scheduler/reserve/lease) — ✓.
* R4-A-022…025 (state machine/AM-1) — **частично: [H-ASAP4-2], [M-ASAP4-3]**.
* R4-A-026…028 (KNN/activation) — ✓ кроме недостижимого кода ([M-ASAP4-4]); активация — существующая `_activate`, второй реестра/activation API (N-MCA07-1) нет ✓.
* R4-A-029…035 (log hygiene/панели) — ✓.
* R4-A-033/036…041 (fixtures/gate) — ✓ на уровне оркестрации; §64-потолок на реальном пути ×2 из-за [H-ASAP4-1].
* §84 no-false-acceptance: формулировки честные — нигде не заявлено «GraphRAG fixed»; состояние после Wave A — building→FTS-only с паузами, что и фиксируется.
* T-4413 §83-gate: 429-no-storm ✓*, same-group ≤ capacity ✓, failover групп ✓, pause/resume ✓*, online без starvation ✓, honest-vs-ACTIVE ✓, KNN диагностируем ✓ (6/7), OFF-паритет ✓, нет второго GraphRAG/реестра/API ✓. (* — с блокерами ниже.)

## Focused audit coverage

Критические зависимости: `LLMClient._post` (единственный HTTP-слой) — прочитан весь retry-блок; `task_supervisor`/`task_jobs` DDL+partial UNIQUE index (lease-основа) — проверены; mca-01 write_transaction (все записи lease/registry/pause — через него); conftest-изоляция (reload-подмена); интеграционные кромки summary_memory↔control plane (seam `execute_embed`, priority context, coalesced INFO); паритет OFF; миграционная идемпотентность; restart-персистентность (`load_group_states` — код ✓, прямого теста нет → [L-ASAP4-7]).

## Counterexamples checked (негативные сценарии)

1. **429 на первом батче при уже cooling-группе (P0-трафик слов 429 во время rebuild)** → executor raising `EmbeddingGroupCoolingDown` → `_handle_build_failure` → **terminal failed** — воспроизведено скриптом: `job status = 'failed' | reason = 'EmbeddingGroupCoolingDown'` → [H-ASAP4-2].
2. **4 transport-фейла подряд** → ровно 4 HTTP-вызова → BudgetExhausted ✓ (тест); но тот же BudgetExhausted из rebuild → terminal failed вместо pause — воспроизведено → [H-ASAP4-2].
3. **`retry_statuses=()` через реальный `_post`** → 429 даёт **2 нижнеуровневых HTTP-вызова** (лог `LLM request retry … reason=status=429`), 503 — аналогично; нижний слой спит min(RA, 8s) — воспроизведено скриптом на `LLMClient._post` с фейк-клиентом → [H-ASAP4-1].
4. **Исключение из `_validate` после CAS RUNNING→CHECKPOINT** → все CAS `_handle_build_failure` с `expect=ST_RUNNING` молча no-op, job остаётся checkpoint без честного терминала → по коду, [M-ASAP4-3].
5. **Двойной concurrent acquire lease** → partial UNIQUE index не даёт второй активной строке; проигравший без строки; takeover-гонка — оба UPDATE сериализованы write_transaction, верификация по единственной running-строке — взаимная исключение сохраняется ✓.
6. **Post-release schedule при lease-busy** → ветка return до try/finally — цикла планирования нет ✓.
7. **Restart during pause** → `_ensure_job` ждёт `next_allowed_at`, generation не сбрасывается ✓ (тест воспроизведён).
8. **Пустой source** → pre-check + knn_source_empty ✓.

## Blocking findings

### [H-ASAP4-1] [High, blocking] Нижние слои НЕ transport-only: `retry_statuses=()` не отключает ретраи 429/5xx в `_post`
* **Где:** `services/llm_client.py:749-768` (мёртвая для `()` ветка), контракт в `embed_once` (1405-1464) и `EmbeddingProviderAdapter.embed_batch` (`embedding_control_plane.py:825-834`).
* **Требование:** spec A.2 «нижние слои (LLMClient._post): transport retry ONLY»; докстринг `embed_once`: «retry_statuses=() → 429/5xx отдаются наверх немедленно»; R4-A-004…009.
* **Наблюдение (воспроизведено):** условие `status in retry_statuses` при `retry_statuses=()` ложно всегда → ветка немедленного raise недостижима; 429 уходит в legacy-ветку (769) и ретраится (`attempt < call_retries`, call_retries=1 от `max_retries=1`): **2 HTTP-вызова на один вызов адаптера**, лог `LLM request retry … reason=status=429`; первый ретрай спит `min(Retry-After, LLM_RETRY_BACKOFF_CAP=8)` — ровно анти-паттерн §9/прод-факта Q4.
* **Impact:** удвоение давления на квоту в burst (то, с чем борется эпик); потолок §64 «≤4 логических вызова» на реальном пути ×2; «21→не 21» держится только на фейке уровня `embed_once`, т.е. демо-тест меряет не тот слой.
* **Fix:** инвертировать семантику на allowlist: `None` → прежний сет (408/425/429/5xx), иначе ретраить ТОЛЬКО перечисленные (при `()` — не ретраить ничего, transport-исключения не трогать) + тест на уровне `_post` (429 → ровно 1 HTTP-вызов). Проверить, что retry_statuses использован только контрол-плейном.
* **Verification:** прогон нового `_post`-теста + §64-фикстура через реальный клиент-стаб.

### [H-ASAP4-2] [High, blocking] `_handle_build_failure` отправляет control-plane исключения в terminal FAILED (нарушение AM-1/§26)
* **Где:** `services/graphrag_rebuild.py:1186-1285` (`_is_rate_limit_exception`/`_is_provider_unavailable`/fallback-ветка), триггеры: 1002-1009 (embed-батч) и 1148-1154.
* **Требование:** spec A.5/AM-1: «429 / provider-quota pressure → `paused_rate_limit` (не terminal FAILED)»; собственный контракт executor (`embedding_control_plane.py:986-993`): «CoolingDown … P3 → pause job», «BudgetExhausted … P3 → pause».
* **Наблюдение (воспроизведено):** `EmbeddingGroupCoolingDown` (группа cooling в момент батча — реалистично: P0-запрос получил 429 и поставил cooldown, следующий батч rebuild падает сразу, без HTTP) и `EmbeddingBudgetExhausted` не матчатся ни на один класс → terminal `failed`, reason = имя класса. Статус воспроизведён: `job status = 'failed' | reason = 'EmbeddingGroupCoolingDown'`.
* **Impact:** ядро эпика — «production при 429 уходит в building→FTS-only БЕЗ потери билда» — нарушается на реалистичном пути (прод: одна unknown-группа на все ключи, Q1/Q6): generation получает ложный честный-terminal (шум в Analytics/инциденты), resume только через re-open по schedule (`_ensure_job` failed→queued — тот же generation, но семантика «честный terminal» лживая) либо ручное вмешательство.
* **Fix:** в `_handle_build_failure` до эвристик по именам добавить явные ветки: `EmbeddingGroupCoolingDown` → paused_rate_limit с `next_allowed_at` из исключения; `EmbeddingBudgetExhausted`/`EmbeddingConcurrencyBusy` → paused_provider/paused_rate_limit (bounded horizon и так защищает). + негативный тест (executor-CoolingDown → paused_rate_limit).
* **Verification:** новый тест + повторный прогон §68-семейства.

### [M-ASAP4-3] [Medium, blocking] Пост-checkpoint исключения классифицируются CAS'ом не по тому статусу (молчаливый no-op)
* **Где:** `services/graphrag_rebuild.py:1148-1154` (outer except) + все CAS внутри `_handle_build_failure` с жёстким `expect=ST_RUNNING`; окно: после CAS RUNNING→CHECKPOINT (1055-1057).
* **Наблюдение:** исключение из `_validate`/emit-пути при CP ON → `_handle_build_failure` → все CAS no-op (статус уже `checkpoint`) → job остаётся checkpoint; §25-terminal (deterministic DB/schema error) и horizon на этом участке не применяются; job бесконечно пере-resume'ится планировщиком без honest-фиксации.
* **Impact:** ограниченный (погона данных нет, checkpoint-семантика сохраняет работу), но контракт «честный terminal для deterministic error» нарушен и horizon не ограничивает этот класс.
* **Fix:** передавать фактический статус (`_get_job`) в `_handle_build_failure` или CAS-ить от прочитанного статуса; для checkpoint-стадии deterministic-ошибки — terminal как раньше.
* **Verification:** тест: MATCH-execute исключение на стадии `_validate` (не smoke) → ожидаемый честный статус.

### [M-ASAP4-4] [Medium, blocking-by-requirement] `knn_query_vector_failed` недостижим — 7-й код A.6 не производится
* **Где:** `services/graphrag_rebuild.py` `_validate` (~660-755): json-dump/query-вектор провал попадает в общий `except` → `knn_index_schema_mismatch`; `knn_query_vector_failed` существует только в `mca_events.py:152`.
* **Требование:** spec A.6 — 7 distinct reason codes.
* **Impact:** диагностика «битый query-вектор» неотличима от «битая схема индекса» — тот класс проблем, ради которого делался A.6; evidence §8.7 утверждает «ветка существует» — фактически ветки нет (неточность evidence).
* **Fix:** узкий `except` вокруг построения query-вектора → `knn_query_vector_failed` (+ тест с падающим `json.dumps`), либо явный ADR-waiver на 6/7 кодов.
* **Verification:** тест на форс исключения query-вектора.

## Non-blocking debt

* **[M-ASAP4-5] [Medium, non-blocking, evidence-integrity] OPEN:** evidence.md §2/§5 утверждает «`tests/test_graphrag_rebuild_asap32.py` обновлён, 2 теста» — файл в дереве НЕ изменён (git status чист, mtime до волны). Функциональное покрытие knn-класса есть в новом asap4-файле, дыры покрытия нет, но заявление о change-set ложно → исправить evidence.md (или восстановить утерянные правки, если предполагались). asap32-тесты зелёные и с CP ON (инъекции — non-quota классы).
* **[L-ASAP4-6]** Лестница §5: шаги 1–2 (provider runtime metadata / Connections layer) не реализованы как отдельные источники — слиты в developer label → unknown; соответствует прод-фактам Q1/Q8, задокументировано в коде; оформить как уточнение спеки/waiver.
* **[L-ASAP4-7]** `REGISTRY.load_group_states` (restart-персистентность quota-групп) не покрыт прямым тестом.
* **[L-ASAP4-8]** Вестижный always-true assert в `test_restart_during_quota_pause` (строки 636-637: `… if False else True`).
* **[L-ASAP4-9] Наблюдение (стабильность прогона, вне атрибуции Wave A):** на 4 полных прогона этой сессии — 1 флак `test_betterstack_handler::TestNoRedirect::test_real_302_not_followed_by_opener` (реальные loopback-сокеты; в изоляции зелёный) и 2 зависания ≥120s на ~72% сьюта (pytest-timeout thread-method убивал процесс) на фоне тысяч накопленных aiosqlite-воркеров (известная гигиена teardown — backlog N3 mca-05). Контрольный -v прогон: чистые 10562/2 за 296s. Зависания не атрибуируются Wave A (точка зависания вне asap4-файлов; прогон 1 с тем же деревом завершился), но DevOps учесть перед релизным прогоном.
* **[Info]** `PriorityScheduler.acquire` — polling 0.25s + `asyncio.get_event_loop()` (deprecation) — стиль, не блокер.

## Unavailable checks

* Live-acceptance §34/§77 (реальные 429/KNN, REAL quota, платные вызовы) — PENDING OWNER (вне Builder/Reviewer), отмечено в evidence §8.3.
* `EMBED_ASYNC_BATCH_ENABLED=ON` контракт — не верифицирован (default OFF, live-верификация до включения — по спеке §16).
* Multi-process lease под реальным вторым процессом бота — верифицируется DevOps на деплое (прод один процесс, Q5); по коду инвариант держится (см. Counterexample 5).
* Документарная верификация версий внешних зависимостей по этой волне не требовалась (новых зависимостей нет; sqlite-vec/httpx не менялись). OpenViking-память сверена (один bounded-запрос): противоречий с ADR-1028-5/ASAP-3.2 «honest terminal» нет — AM-1 их явно amend'ит; N-MCA07-1 (второй activation API) не нарушен. MEMORY_DELTA: нет.

## Вердикт round 1 (исторический, снят round 2)

**Needs Fixes (Wave A).** Оркестрационный каркас зоны A (pool/группы/cooldown/budget/scheduler/lease/DDL/OFF-паритет/панели) реализован добротно и подтверждён тестами, но два High-дефекта ломают два центральных контракта эпика на реальных путях: (1) retry-ownership на HTTP-слое и (2) «429 никогда не terminal» для rebuild. После фикса H-ASAP4-1/H-ASAP4-2 (+M-ASAP4-3/M-ASAP4-4) — повторный gate по затронутым проверкам: §64-фикстура через реальный `_post`-стаб, executor-CoolingDown → paused-тест, post-checkpoint failure-тест, knn_query_vector_failed тест, полный pytest и F8.
