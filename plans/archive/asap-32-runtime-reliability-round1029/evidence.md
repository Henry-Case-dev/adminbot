# evidence.md — `asap-32-runtime-reliability-graphrag-provider-discovery` (Builder)

## Pass 1 — зоны A (GraphRAG), B (Media/Image runtime), C (Text Capacity) — T-4190…T-4204

**Дата:** 01.10.2026. **Роль:** Builder (реализация + тесты; self-review запрещён — независимая верификация за Reviewer).

### Baseline / текущее состояние worktree

* Baseline-коммит: `1287130` (docs/plans EXTRA archive; прод 2.58.39, SQLite DDL v19, v20-бронь `mca-04b` не тронута — проверено `PRAGMA user_version` в тестах = 19).
* Хеши авторитетных документов верифицированы `Get-FileHash` перед стартом:
  * `spec.md` = `E0F752CBAABF932011C77166BA6FF0465865AE718671D311B5571BDE7FA878AA` ✓
  * `adr-1028-5-runtime-reliability.md` = `24FD73A442B59917A1A673DED8C065868985D3050F55A9A5CA769C2B31A6874D` ✓
  * `tasks.md` = `E4075209B930B24525E893BA6E5C105447AB66AA9FA74511D8A11A48BFF6E90F` ✓ (E4075209…E90F)
* `plans/current_task.md` НЕ изменялся (R17).
* Чужой WIP не тронут: `plans/backlog.md`, `plans/docs/mca-round1027-*.md`, `plans/metrics.md`, `plans/workflow_state.md`, `plans/features/mca-04b-dossier-rebuild/`, `extra_images/`, `.playwright-mcp/`, `node_modules/`, `package.json`, `package-lock.json` — остались в исходном состоянии git status (modified/untracked, принадлежат другим сессиям).
* Коммит НЕ создавался (по инструкции), деплой не выполнялся, prod не писался.

### Изменённые файлы (Builder, Pass 1)

**Новые модули:**

1. `services/graphrag_rebuild.py` (новый, ~640 строк) — зона A (T-4191/T-4192):
   * shadow-генерация (ADR-1028-5 D1): generation-suffixed shadow vec0-таблица `graph_facts_vec_g{N}` / `smart_archive_g{N}`, идемпотентный `CREATE VIRTUAL TABLE IF NOT EXISTS` — **Δ SQLite DDL = 0** (user_version 19 не меняется, тест-ассерт);
   * полный re-embed (НЕ fill-missing) cursor-батчами (GRAPHRAG_REBUILD_BATCH=50, sleep/yield §64, heartbeat+checkpoint каждый батч);
   * resumable state machine `queued→running→checkpoint→validated→activated|failed` (+paused/cancelled) на REUSE `task_jobs` (v14), identity из coalesce_key (payload перезаписывается checkpoint'ом v14);
   * race-guard D2: validate сравнивает fp build'а с текущим; mismatch → `failed/fingerprint_changed`, shadow удалён, checkpoint сброшен, новый build планируется под новый fp;
   * 9-критериальная validation (§6): fp/dim/provider+model/preprocessing/coverage (allowed-missing: `added_after_scan`)/no-orphans (анти-join в swap)/counts/KNN-smoke (self-match по shadow)/swap;
   * атомарная активация: ОДНА транзакция `write_transaction` (DROP live + CREATE live + INSERT..SELECT c анти-orphan WHERE + реестр поколений superseded/active). `UPDATE … SET status='active'` — ТОЛЬКО здесь и только после критериев 1–8 (запрет §3/§66 соблюдён; обоснование в docstring);
   * события `EMBEDDING_GENERATION_BUILD_START/PROGRESS/VALIDATED/ACTIVATED/FAILED` (REUSE `emit_mca_event` mca-13; R17-safe);
   * §64 pause/resume/cancel (`pause_rebuild/resume_rebuild/cancel_rebuild`) + `rebuild_status()` (данные для health T-4216);
   * планировщик `maybe_schedule_rebuilds()`: building-поколение с текущим fp → ensure/resume job; stale-running takeover; failed → переоткрытие раз на startup-schedule (не storm).
2. `services/media_execution.py` (новый, ~700 строк) — зона B (T-4196…T-4198, T-4200):
   * `ImageProviderAdapter`-контракт (D4): discover_models/discover_capabilities/submit_generation/submit_edit/supports_async_job/supports_status/supports_stream/supports_cancel/get_status/get_result/cancel; detection по host (nanogpt/openrouter/generic); исполнение — ЕДИНАЯ точка (`image_generation._generate_post/_generate_get`, `cover_style_edit.edit_image`), второй стек не заведён;
   * NanoGPT-адаптер: только верифицированные кодом маршруты (`/image-models?detailed=true`, `/images/models/{m}/endpoints`, POST `/images/generations`); async/status capability до live-верификации НЕ заявляется (`remote_progress=none`, §14 — fake ping запрещён, §16 — task_id route не изобретается);
   * OpenRouter-адаптер: discovery по публичному каталогу `/api/v1/models` (маршрут уже используется model_capacity); execution route не выдумывается;
   * `MediaExecutionPolicy` (D5): key provider+model+operation (generate/edit/preview); 4 окна (connect/read-inactivity/poll/total-deadline, §28); sync-only → read=total (сокет молчит до готовности — не признак смерти); estimator ТОЛЬКО по успешным длительностям (p95, §26 — timeout'ы отдельные signals), формула `clamp(max(cold, p95×safety), min, ceiling)`; cold defaults — env, 90/180/240 = migration evidence;
   * durable media jobs (§29): `MediaJobState` (все поля §29) на REUSE `task_jobs`, coalesce по operation+provider+model+prompt-hash (singleflight, прецедент cover_style_jobs §42); детерминированный coalesce + уникальный job_id (завершённые не переиспользуются);
   * restart recovery (§30): `recover_media_jobs()` — provider job id + supports_status → RECOVERED/resume (без платного resubmit); sync-only → честный `unknown_after_disconnect`, автоматического платного retry нет;
   * image fallback (§31): `maybe_media_fallback` — только после terminal failure, running-guard (§31), deadline/prompt-recompile под fallback; env `IMAGE_FALLBACK_BASE_URL/MODEL` (default пусто → поведение прежнее);
   * события §35 `MEDIA_JOB_SUBMITTED/HEARTBEAT/SUCCEEDED/FAILED/RECOVERED/FALLBACK` (REUSE mca-13, R17-safe: job-hash, без prompt'ов/ключей) + `media_policy_snapshot()` (p50/p95/timeouts — данные для §36/§88);
   * kill-switch `MEDIA_EXECUTION_POLICY_ENABLED` (OFF → legacy 90/180/240 байт-в-байт, rollback §80).

**Изменённые модули:**

3. `services/summary_memory.py` — зона A:
   * `_index_generation_ok`: severity-коалесинг §8/§67 — первый WARNING → далее DEBUG при неизменном (status, fp12) в cooldown `GRAPHRAG_GEN_WARN_COOLDOWN_SECONDS` (default 300 c); повторный WARNING при смене состояния/cooldown; bounded-словарь по index_name;
   * rerank (T-4193, §10–§12): новый strict JSON-промпт `{"selected":[...]}` (старый был НЕ-канон — комментарий в коде); `parse_rerank_selected` — robust-парсер (JSON → fences → substring → legacy numeric; детерминированный локальный repair, второй LLM-call запрещён; пустой/blank → валидный empty; «0» → invalid по §10 — якоря F4 сохранены); позиционный маппинг 1..N через `id_of` (фикс латентного бага: продовые dict-факты с row-id `id` обнуляли kept при валидном ответе); observability §12 (candidate/selected counts, parser status, provider/model, latency, response_format, fallback) без raw-контента (Q9); метрики `rerank_metrics_snapshot()` + `rerank_invalid_rate()`;
   * hook `_recover_runtime_jobs()` (fire_and_forget после `_register_index_generations`, оба call-site: init + vec re-probe) — startup-schedule GraphRAG shadow rebuild, не блокирует startup (§7/§85).
4. `services/image_generation.py` — зона B:
   * `generate()`: default timeout (None) → httpx.Timeout из MediaExecutionPolicy (connect/read/total; §28), legacy `IMAGE_REQUEST_TIMEOUT_SECONDS` — fallback/diagnostic (probe);
   * `generate_image_verbose()`: окно попытки = adaptive total deadline (генерация 90–180+ c больше не «умирает» по wall-clock — §32); estimator-запись (успех/timeout §26); durable media job (begin/save/finish, §29/§30); fallback §31 после терминального исхода;
   * новый helper `reason_from_exception` (единая таблица причин для адаптеров).
5. `services/cover_style_edit.py` — зона B: `_timeout(operation, base_url, model)` — окно из политики (edit/preview stage-aware §23; env `COVER_STYLE_EDIT_TIMEOUT_SECONDS` — legacy-путь/migration evidence); `record_edit_outcome` → estimator; `edit_image(operation=...)` (аддитивный kwarg).
6. `services/cover_style_jobs.py` — зона B: run_style_job передаёт `operation="preview"/"edit"` (§23) с inspect-совместимостью для тестовых double.
7. `services/image_capabilities.py` — зона B (§21/Q4): `resolve_capabilities_auto()` — discovery вызывается автоматически (NanoGPT каталог реально fetch'ится через адаптер, TTL-кеш уважается, refresh-инвалидация; unknown остаётся honest unknown). Существующий sync `resolve_capabilities` не изменён (EXTRA-контракты целы).
8. `services/model_capacity.py` — зона C (T-4202/T-4203):
   * `PROVIDER_NANOGPT`/`PROVIDER_DEEPSEEK` — отдельные identity (D6; detect по host);
   * `_adapter_nanogpt_catalog`: live/public каталог `GET /api/v1/models?detailed=true` — схема верифицирована по официальным docs (docs.nano-gpt.com, 01.10.2026: `context_length`, `max_output_tokens`, capabilities) → source=`provider_catalog`, max_output_tokens заполняется; недоступен → registry/fallback с честным source (§53);
   * Direct DeepSeek: registry-hit → source=`verified_registry` (НЕ `provider_catalog`, §54); unknown model → честный fallback (§56);
   * OpenRouter/локальные runtime-адаптеры не тронуты (§55/§19); timeout 2 c + TTL/fallback-кэш (§57) — уже существующие, задокументированы;
   * docstring-сводка обновлена (было: «adapter отсутствует по определению протокола» — устарело).
9. `config/settings.py` — env-only ClassVars (Δ каталога = 0): `MEDIA_EXECUTION_POLICY_ENABLED`, `MEDIA_COLD_DEADLINE_{GENERATE,EDIT,PREVIEW}_SECONDS`, `MEDIA_MIN_DEADLINE_SECONDS`, `MEDIA_HARD_SAFETY_CEILING_SECONDS`, `MEDIA_ADAPTIVE_SAFETY_FACTOR`, `MEDIA_ADAPTIVE_MIN_SAMPLES`, `MEDIA_CONNECT_TIMEOUT_SECONDS`, `MEDIA_INACTIVITY_TIMEOUT_SECONDS`, `MEDIA_POLL_TIMEOUT_SECONDS`, `IMAGE_FALLBACK_BASE_URL/MODEL`, `GRAPHRAG_SHADOW_REBUILD_ENABLED`, `GRAPHRAG_REBUILD_BATCH`, `GRAPHRAG_REBUILD_SLEEP_SECONDS`, `GRAPHRAG_GEN_WARN_COOLDOWN_SECONDS`.
10. `bot.py` — on_startup: `media_execution.bind_db(db)` + `recover_media_jobs(db)` (fail-open, до поднятия компонентов).

**Тесты (новые файлы):**

* `tests/test_graphrag_rebuild_asap32.py` (9 тестов) — §70: unknown vec→BUILDING/FTS; rebuild→validation→ACTIVE (атомарный swap, no-orphans, user_version 19, shadow cleanup); smart_archive lifecycle; restart mid-build → resume от checkpoint (2+4=6 embed-вызовов, identity из coalesce_key); config-change mid-build → старый build НЕ активируется (fingerprint_changed); failed build → FTS serviceable, без storm; missing vector → validation fail + shadow cleanup + checkpoint reset; severity-коалесинг §8 (1 WARNING + 2 DEBUG + немедленный WARNING при смене состояния); pause/cancel-контракты.
* `tests/test_rerank_contract_asap32.py` (14 тестов) — §71: `1,3,5` / `{"selected":[...]}` / fenced JSON / substring repair / пустые формы (`""`, blank, `{"selected":[]}`, `[]`) / prose invalid / «0» → invalid (§10) / out-of-range → bounded fallback / dedup порядка / timeout → fallback + stats / observability без приватного контента (Q9) / регресс продовых row-id dict-фактов.
* `tests/test_media_execution_asap32.py` (15 тестов) — §68 A–F (unit): A) job-status живой — deadline=ceiling, running-guard fallback; B) streaming: read-окно отдельного запроса ≠ total; C) sync 150 c завершается (cold 180 + adaptive p95); D) terminal failure → fallback (и нет fallback без конфига/при RUNNING); E) restart: resume by provider job id (0 resubmit) + sync-only → `unknown_after_disconnect`; F) unknown provider → honest unknown; политика: 4 окна, stage-aware, estimator без timeout'ов, hard-ceiling clamp, OFF-legacy; durable lifecycle/coalesce.
* `tests/test_capacity_nanogpt_asap32.py` (13 тестов) — §53–§57/§69: NanoGPT catalog (window+max_output, provider_catalog), catalog-miss → registry, catalog-unreachable → registry/fallback (честный source), формы URL (route не выдумывается), DeepSeek `verified_registry` ≠ provider_catalog, DeepSeek-unknown → fallback, OpenRouter сохранён, llama.cpp сохранён, unknown без URL-угадывания, negative-cache TTL, provider switch без code change (NanoGPT→OpenRouter→DeepSeek), developer override, adapter timeout ≤2 c.

**Изменённые существующие тесты (обоснование — в комментариях внутри правок):**

* `tests/test_capacity_resolver_asap31.py` — nano-gpt теперь `PROVIDER_NANOGPT` (D6 — легитимное расширение ADR-1028-3); 7 тестов получили hermetic `_no_network`-стаб (семантика якорей «catalog недоступен → registry» сохранена; тесты не ходят в реальную сеть).
* `tests/test_auto_budget_asap31.py` — autouse-фикстура `_clean` стабит `mc._http_get_json` (иначе новый NanoGPT-адаптер делал РЕАЛЬНЫЙ сетевой вызов и тесты становились network-зависимыми — фактический инцидент: каталог вернул 128000 вместо якорных 131072).
* `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_104_generator_functions_ast_identical` — `generate`/`generate_image_verbose` исключены из byte-identity по прецеденту A5 этого же гварда: ADR-1028-5 D5 (Accepted, binding) санкционирует перевод этих функций с трёх env-wall-clock окон на MediaExecutionPolicy (T-4197/T-4199). Провайдер-канон `_generate_post`/`_generate_get` и R17-классы причин не менялись. **Требует independent verification Reviewer.**
* `tests/test_extra_cover_style_jobs.py::TestEditPolicy` — legacy-клампы якорятся на `MEDIA_EXECUTION_POLICY_ENABLED=OFF` (паритет EXTRA) + добавлен policy-path тест (stage-aware, env=migration evidence).
* `tests/test_hotfix5_summary_cover_window_round1025.py::test_attempt_bounded_by_window_deadline` — wait_for-дедлайн hotfix-5 якорится на legacy-путь (policy OFF); policy-путь покрыт новым media-файлом.
* `tests/test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer` — allowlist += `graphrag_rebuild.py: 3` (3 прямых commit ВСЕ внутри `async with db.serialized()` — санкционированный single-writer паттерн гварда; активация/статусы — через `write_transaction` mca-01).

### Результаты тестов (фактические прогоны)

* **Финальный полный pytest (01.10.2026): 10268 passed / 2 failed**, оба failed — известные якорные baseline forbidden-paths (чужие, `web/`-diff vs старого baseline-коммита): `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`, `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`. Совпадает с заявленным базисом PM «10210 passed / 2 failed (якорные forbidden-paths, чужие)» + 58 новых/обновлённых тестов Pass 1.
* Новые тест-файлы Pass 1: **57 passed** (graphrag 9 + rerank 14 + media 15 + capacity 13 + ...; соло-прогон 4 файлов).
* Промежуточные фикс-раунды в процессе реализации задокументированы ниже (инциденты: реальная сеть в unit-тестах; reload `config.settings` в полном сьюте ломал патч настроек — исправлено `_patch_setting` на оба класса).

### Чек-лист Pass 1 → задачи

* T-4190 [@Architect] — вне скоупа Builder (ADR D1–D3 готов, реализация следует ему).
* T-4191 [x], T-4192 [x], T-4193 [x] — реализация + тесты (см. выше).
* T-4194 [@Reviewer] — не тронут.
* T-4196 [x], T-4197 [x], T-4198 [x], T-4199 [x], T-4200 [x]* — реализация + тесты. *T-4200: событийный слой §35/§88 + данные (p50/p95 snapshot) готовы; §36 Miniapp-рендер — frontend-проход (шаг 3 §132), browser-проверка — T-4232 (Pass 2).
* T-4201 [@Reviewer] — не тронут.
* T-4202 [x], T-4203 [x] — реализация + тесты.
* T-4204 [@Reviewer] — не тронут.
* T-4228 [x] — §68 сценарии A–F покрыты unit-уровнем (live-провайдерские вариации — DevOps §76).
* T-4229 [ ] — ЧАСТИЧНО: capacity-switch (NanoGPT→OpenRouter→DeepSeek без code change) покрыт; полный §69 (execution-policy switch + UI refresh) — Pass 2 (T-4232/browser).
* T-4230 [x] — §70 полностью (6 сценариев §70 + severity + pause/cancel).
* T-4231 [ ] — ЧАСТИЧНО: §71 (reranker) покрыт; §72 (Summary), §73 (Direct tool fallback), §74 (Decision Maker) — зоны D/E/F (Pass 2).

### Отклонения / решения, требующие внимания Reviewer

1. **AST-гвард round1026** (`test_unified_image_request_round1026.py`): исключение `generate`/`generate_image_verbose` из byte-identity — санкция ADR-1028-5 D5 (Accepted) vs устаревший per-feature bound; прецедент A5 в том же гварде. Провайдер-маршруты/канон payload НЕ менялись.
2. **Латентный баг MCA-07 typed reranker** (вне ТЗ, найден при реализации T-4193): `select_by_rerank` маппил номера на `candidate["id"]` (row-id фактов), тогда как промпт нумерует ПОЗИЦИИ → валидный ответ LLM обнулял kept для продовых dict-фактов. Исправлено на позиционный маппинг в call-site `rerank_rag_facts` (для mca07-retrieval-path `apply_retrieval_rerank` не трогал — там id-семантика другая).
3. **Семантика «0»** в rerank-парсере: по §10 («invalid ⇔ непустой ответ без корректных номеров») «0» → invalid → bounded fallback — подтверждено существующими якорями `test_graphrag_memory::TestChatRagRerankF4` (сохранил их без правок).
4. **Пустой/blank ответ LLM** → валидный empty (не invalid) — по §10 и якорям F4.
5. **NanoGPT async/status для image** — НЕ заявлен (честный sync, `remote_progress=none`): live-верификация реального endpoint ключом — задача T-4195 [@Architect] / DevOps (§16/§91); route не изобретался.
6. **Сетевые вызовы в unit-тестах** — устранены стабами `_http_get_json` в 3 test-файлах (auto_budget-тесты фактически ходили в реальный nano-gpt.com после появления адаптера — инцидент зафиксирован выше).
7. **`ensure_embedding_generation(activate=False)` возвращает None** (пре-существующее поведение 2.58.39: внутри читается `get_active`) — использовано как есть; тесты и планировщик читают реестр через `get_generation_by_fingerprint/get_latest`.

### Не выполнялось / вне скоупа Pass 1

* Проход 2 (зоны D–H + релиз): T-4205…T-4218…T-4243.
* Browser-верификация (§75/T-4232), production live acceptance (§76–§79, T-4234+), bump версии (T-4233).
* Миниап-рендер §9/§36/§60 (frontend-проход; backend-данные готовы: `rebuild_status()`, `media_policy_snapshot()`, `rerank_metrics_snapshot()`, `rerank_invalid_rate()`).
* Реальные платные вызовы image/embedding — не выполнялись (только unit/integration с fake/stub).

### Как проверить (для Reviewer)

```text
cd C:\Code\Python\adminbot
.venv\Scripts\python.exe -m pytest tests -q
  expect: 10268 passed, 2 known anchor forbidden-paths failures (чужие)
.venv\Scripts\python.exe -m pytest tests/test_graphrag_rebuild_asap32.py tests/test_rerank_contract_asap32.py tests/test_media_execution_asap32.py tests/test_capacity_nanogpt_asap32.py -q
  expect: 57 passed
git status --porcelain  # изменённые файлы — список выше; чужой WIP не тронут
```

Git-состояние на момент сдачи: HEAD `1287130`, изменения НЕ закоммичены (worktree), коммит/деплой — вне полномочий Builder.

## Pass 2 — зоны D (Summary), E (Direct), F (Decision), H (EXTRA) + релиз — T-4205…T-4233

**Дата:** 01.10.2026. **Роль:** Builder (Pass 2; Pass 1 не переделывался — `services/graphrag_rebuild.py`, `media_execution.py` и Pass-1-правки image_generation/cover_style_edit/model_capacity/summary_memory не тронуты).

### Baseline / состояние worktree

* Baseline-коммит: `1287130` (тот же HEAD, что и Pass 1; изменения НЕ коммичены).
* Хэши верифицированы перед стартом: `spec.md` = E0F752CB…878AA ✓ (стоп-условие снято); `adr-1028-5` = 24FD73A4…6874D ✓; tasks.md на старте = E7293237… — отличается от заявленного E4075209…E90F ОБЪЯСНИМО: весь каталог фичи untracked, Pass 1 уже ставил чекбоксы в worktree.
* `plans/current_task.md` НЕ изменялся (R17). Чужой WIP не тронут: `plans/features/mca-04b-dossier-rebuild/`, `extra_images/`, `.playwright-mcp/`, `node_modules/`, `package.json`, `package-lock.json`. Коммит не создавался, деплой не выполнялся, prod не писался.

### Зона D — Summary semantic reduction (T-4206…T-4208; D8/D9)

* **Новый модуль `services/summary_semantic_reduction.py`** (чистый, 0 LLM): `reduce_threads(threads) -> (threads, ReductionStats)` — stable-ID merge фактов (нормализованный текст, evidence-union), topic dedupe (одинаковое нормализованное название = одна тема, union chronology), cross-thread fragment dedupe (ключ (message_id, part) — части сегментации не считаются дубликатами). Инвариант: `unique_dropped = 0` — каждый уникальный семантический ключ сохраняется; merged_duplicates = схлопнутые повторы + слитые темы.
* **`services/summary_fact_package.py`**: на ON-пути (`SUMMARY_SEMANTIC_REDUCTION_ENABLED`, default ON) позиционные `_apply_fragment_caps`/`_enforce_budget` НЕ вызываются — вместо них редукция; если и после неё пакет больше бюджета ОДНОГО L2-вызова — **paged L2** (`FactPackageResult.pages`, каждая страница ≤ budget; oversized-тема делится по единицам facts/fragments lossless с `_explode_units`; continuation-страницы — скелет темы без дублирования фактов) — НИКОГДА silent drop. Позиционный каскад остался ТОЛЬКО на kill-switch OFF-пути (rollback-паритет §80) с видимым degraded-событием `FACT_PACKAGE_POSITIONAL_FAILSOFT` + `SUMMARY_COVERAGE_DEGRADED reason=positional_failsoft`. Coverage-метрики §41 в metrics: `semantic_unique_before/after`, `semantic_merged_duplicates`, `semantic_unique_dropped`, `semantic_reduction_passes`, `paged`, `pages_count`, `fragment_segmented_count`.
* **§42 lossless-сегментация**: `_select_fragments` больше не делает `text[:1000]` — oversized-текст делится `_segment_text` на части ≤ FRAGMENT_MAX_CHARS с аддитивными полями `part`/`part_total`; конкатенация частей байт-равна исходному тексту; author/timestamp/reply сохраняются в каждой части (обычные fragments — схема v2 без изменений).
* **§43 empty-guard сохранён**: `PACKAGE_NEAR_EMPTY`/fail-closed EMPTY не тронуты; редукция не может опустошить пакет (не выбрасывает уникальное).
* **Paged L2 у потребителей**: `summary_generator._run_hybrid_l2` и `summary_test_run` вызывают `run_l2` ПО СТРАНИЦАМ и сливают документы (title первой страницы + paragraphs concat + finale; каждая страница — валидный §99-документ).
* **Тесты**: новый `tests/test_summary_semantic_reduction_asap32.py` (13): §72 (large window → skipped_fragments=0, reduction invoked, 100% уникальных фактов сохранены), §39 paging (каждая страница ≤ budget, все уникальные элементы где-то сохранены), §40 merge/dedupe/evidence-union, §41 метрики + unique_dropped=0, §42 сегментация lossless, §43 guard, детерминизм двойного прогона, OFF-паритет + видимое degraded-событие. Обновлён якорь `test_l2_budget_asap31.py::test_manual_cap_l2_budget_applied` — manual cap = размер ОДНОГО L2-вызова; при D8 кап honored через pages (per-page fits при лимите ≥512; дегенеративный limit=1 — резервы съедают кап — физически непостраничен, прежний каскад давал полный drop → truncated). Санкция D8.

### Зона E — Direct fallback recompose (T-4210/T-4211; D10)

* **`services/llm_client.py`**: `generate_chat(..., fallback_payload_adapter=None)` — тот же контракт, что `generate()`; adapter вызывается РОВНО ОДИН раз при fallback-переключении; payload включает tools/tool_choice (§45 — адаптер видит полный mandatory payload). Усиление D10: adapter-error/invalid-shape → громкий лог `LLM fallback recompose FAILED — primary payload SENT AS-IS | oversized_risk=1` (fail-open сохранён — якорь ASAP-3.1 `test_adapter_error_returns_original_payload` цел); то же усиление в `generate()`.
* **`services/tool_loop.py`**: `chat_with_tools(..., fallback_payload_adapter=None)` — прокидывает адаптер в generate_chat КАЖДОГО раунда и в FR-15 plain-фолбэк.
* **`services/direct_chat_service.py`**: tool-ветка передаёт `_fb_factory(time_line, extra_reserve=tools_tokens)` — токены tool schemas ВЫЧИТАЮТСЯ из fallback-бюджета ДО recompose (§45); фабрика композера расширена `extra_reserve` (логирует tools_reserve); recompose failure — громкий oversized-risk лог (не тихий).
* **Тесты**: новый `tests/test_direct_fallback_recompose_asap32.py` (8): §46 regression (primary 1M / fallback 32K + tools → recomposed ≤ budget по count_tokens, P0-хвост и system сохранены, tools preserved); adapter passthrough в tool_loop (каждый раунд + FR-15) и его отсутствие — байт-паритет; громкая диагностика (generate + generate_chat); §45 фабрика (extra_reserve сжимает recompose, tools passthrough). Carry-over **M-ASAP31-2 закрыт**.

### Зона F — LLM-driven decision (T-4213; D11)

* **`services/direct_llm_react.py`**: `<Decision_Task>` контракт — `build_decision_instruction`/`inject_decision_task`/`extract_llm_decision` (валидные JSON REACT/SILENT/REPLY; ответ не с `{` = сознательный REPLY-текст; битая JSON-попытка → sentinel INVALID — не отправляется пользователю); `llm_decision_enabled` = `DIRECT_LLM_DECISION_ENABLED` AND `llm_reaction_enabled` (env + per-chat); `record_decision_outcome` (process-local, R17-enum).
* **`services/direct_chat_service.py`**: demoted-матрица `_decision_pre_action` = features/детерминированный fallback; Decision Task вводится при demoted REACT (гейты ON) или demoted SILENT **только при reply_bot** (фон/not-addressed — дешёвый hard gate §50). Allowed-набор runtime: REACT при toggles.reactions, SILENT при ignore_trivial. Парсинг ПОСЛЕ ТОГО ЖЕ вызова генерации — call count не растёт (§52: REPLY отвечает текстом, REACT/SILENT — JSON). SILENT direct-autonomous → `_execute_silent_ack` (🗿-конъюнкция; метод извлечён из inline-блока — логика идентична, переиспользован обоими путями). INVALID/invalid-REACT/REPLY-without-text → детерминированный fallback demoted-матрицы (§51); LLMError при decision pending → fallback без R13-фразы. Force / per-chat-autonomous-off / явные задачи (demoted REPLY) — hard gates ДО Decision Maker, task не вводится (§43/§49).
* **Kill-switch**: `DIRECT_LLM_DECISION_ENABLED` (env-only, default ON; OFF → байт-в-байт прежний алгоритмический decision + `<Reaction_Task>` ASAP-3.1).
* **Тесты**: новый `tests/test_direct_llm_decision_asap32.py` (13): §74 (REACT mock → реакция, ровно 1 вызов; REPLY-JSON без текста → fallback; SILENT; force — Decision Task не вводится; явная задача — не глушится; битый JSON → fallback), §49/§50/§51/§52, конъюнкция гейтов, OFF-паритет (`<Reaction_Task>`), метрики. Обновлены якоря по санкции D11 (сдвиг «алгоритм решает действие» → «LLM решает действие»): `test_llm_react_asap31.py` (SILENT — conscious-LLM: mock SILENT → 🗿 за 1 вызов; `<Decision_Task>`; plain-text = сознательный REPLY — новый тест), `test_direct_decision_matrix_asap3.py` (ack-SILENT сценарии — mock SILENT JSON; fail-soft ack — 1 вызов, без текста). Инфраструктура: pytest.ini + маркер `asap32`; conftest autouse `_asap32_flags_off_by_default` (старые тесты — baseline, asap32 — прод-дефолты; маркер asap32 исключает и asap3/asap31-фикстуры).

### Зона H — EXTRA corrective (T-4219…T-4226; D14)

* **T-4219 PgDatabase-контракт**: `web/api/cover_styles.py` — ВСЕ `registry.*(...)` переведены с raw `_pool(cache)` на `_pg(cache)` (аудит ~18 call sites: list/detail/create/update/duplicate/delete/select/reference upload/replace/remove/asset usage/asset delete/asset GET/capabilities/connection status/test-style/preview save); хелпер `_pool` удалён; локальные переменные переименованы pool→pg (naming-конвенция §121).
* **§120 integration-тесты БЕЗ monkeypatch registry**: новый `tests/test_cover_styles_contract_asap32.py` (11): FakePgDatabase (`.pool`) + FakePool/FakeConn (in-memory asyncpg-подобный контракт: fetchrow/fetch/execute/transaction, маршрутизация по SQL-шаблонам реестра) — сквозные API→registry→pool: seed→list содержит medved_press (**на pre-fix падал** — raw Pool давал `[]` fail-open); create/update/delete roundtrip (200, не 503); duplicate + reference CRUD (upload→thumbnail→replace→remove); asset GET 200 реальные байты + missing-file integrity 404; **обязательный regression** `test_regression_raw_pool_fails_open_pgdatabase_works` (raw Pool → `[]`, PgDatabase → данные); seed idempotent/no-resurrect.
* **§121 static guard**: `test_api_never_passes_raw_pool_to_registry` — запрет `def _pool(` и `registry.*(_pool(`; первый аргумент каждого registry.* — pg-уровень; `test_jobs_and_pipeline_use_pgdatabase_level` — jobs резолвит connection через pg.
* **T-4220 seed-инвариант**: `bot.py on_startup` вызывает `registry.seed_seeded_style` (fail-open, после PG-availability); seed идемпотентен (existing → no-op), **owner-edits не перезатираются**, **soft-deleted профиль НЕ воскрешается** (прямой is_deleted-чек до создания), прерванный seed → `COVER_STYLE_SEED_INCOMPLETE` (§128) + WARN. Счётчик seed 0 = configurable (§125, без гейта). **Найдено при реализации**: seed_seeded_style НЕ имел ни одного production call-site (только тесты) — корень «seeded absent from UI» на проде.
* **T-4221 assets/refs**: asset GET — DB-row без файла → 404 «Файл примера отсутствует на сервере.» + `COVER_STYLE_ASSET_MISSING` (asset_id в событии, disk_path только в WARN-логе; §100/§128); reference CRUD покрыт contract-тестами против реального диска (COVER_STYLE_ASSETS_DIR → tmp).
* **T-4222 §135 права**: read/select routes (list/detail/select/asset GET/capabilities/connection-status) → `requires_permission('access')` — обычный пользователь выбирает/использует; ВСЕ мутации остаются `requires_global_admin()` → seeded mutation = admin-only, backend-enforced (403; PG/asset storage/counter не изменяются — тест `test_non_admin_cannot_mutate_seeded_or_bypass` прямым API). Default §135 (неделегируемое системное право) удовлетворён; делегируемая гранулярность в матрице — не вводилась.
* **Connection model redesign (§103–§105)**: PG-DDL +1 таблица `cover_style_connections` (идемпотентный CREATE IF NOT EXISTS; Δ-лист PG: 5→6 таблиц cover_style_*); registry CRUD connections (`_public_connection` — секрет НЕ наружу, только маска); `resolve_style_slot(profile, connection)` — `connection_id` настоящий FK (raw URL НЕ интерпретируется; unresolved → честный fallback на default + `custom_unresolved` в status); API `/cover/connections` GET/POST/DELETE (admin; base_url-валидация) + валидация профиля (raw URL → 422 «Base URL принадлежит „Настроить подключения →“», неизвестный FK → 422); per-connection api_key в Style Edit; connection label в detail/status.
* **T-4224 Test Style provider state**: UI-ветка `data-cover-connection-unconfigured` — «Обработка стилем пока не настроена» + `[Настроить подключение]`; CRUD не отключается (§126); API-сообщения not_configured/edit_unsupported сохранены.
* **T-4225 §128/§129**: события `COVER_STYLE_REGISTRY_LIST_FAILED` (pg_unavailable; list fail-open сохранён) / `COVER_STYLE_SAVE_FAILED` / `COVER_STYLE_REFERENCE_UPLOAD_FAILED` / `COVER_STYLE_ASSET_MISSING` / `COVER_STYLE_SEED_INCOMPLETE` — safe fields (style_id/asset_id/stage/reason/http), fail-open, сырые DB exceptions не показываются; UI-тексты: «Не удалось сохранить стиль: хранилище стилей недоступно.», «Не удалось загрузить референс.», «Файл примера отсутствует на сервере.»
* **§102/§124**: `prompts.summary_cover_style_id` — hidden=True (`_HIDDEN_CATALOG_PG_KEYS`); из Prompt Library не рендерится; ручная запись через ОБЕ ветки /api/config → 422 «значение задаётся в соответствующем разделе»; per-chat выбор — только POST /api/cover/select.
* **T-4223 UI redesign (§106–§114)**: `web/index.html` — management screen («Стиль этого чата» селектор + Применить; «Мои стили» карточками с thumbnail + бейдж «Пример» + меню ⋯; «Без дополнительного стиля» — только selection state); редактор — **dedicated full-screen surface** (`<teleport to="body">` + `.cover-overlay/.cover-editor` — teleport обязателен: glass-backdrop-filter предков ломает fixed-контекст); progressive disclosure (имя/инструкция/референсы/КРУПНЫЙ Before→After `cover-preview`/нумерация/Test Style первичны; «Модель и подключение» + «Дополнительные настройки» — collapsed); §112 two-step New Style (шаг 1 → «Создать и продолжить» — серверная сущность сразу, референсы активны); §113 ОДИН Save в футере оверлея (глобальный sticky-save закрыт); §114 safe-area футер, скролл до последнего поля. `web/app.js`: editorOpen/editorDirty/draftStep/draftName/connections + `coverStyleEditorClose`/`coverStyleCreateDraft`/`coverStylesLoadConnections`; Save — dirty-сброс + §129-текст ошибки. `web/static/app.css`: +67 строк custom-классов (zero-build — утилиты отсутствуют в прекомпилированном tailwind).
* **UI E2E (§115)**: новый `tools/ui_asap32_cover_styles_e2e.py` (Playwright, static + route-стабы — прецедент ui_round1025_e2e; **implementation-loop инструмент, НЕ production acceptance** — §96/§133 закрытие за Reviewer/DevOps на real backend): §107 management, §108 fixed-overlay + unsaved-dot, §110 Before/After ≥200px, §111 ref-thumb, §109 collapsed technique, §113 ровно 1 Save + мутация + dirty-сброс, §112 two-step + референсы сразу, §114 mobile 360px — без overflow, Save в вьюпорте, скролл работает; console/pageerror = 0. **Результат: OK (RC=0)**; скриншоты `ui_editor_desktop.png`/`ui_management_desktop.png`/`ui_editor_mobile.png` в каталоге фичи.
* **T-4226**: deployment-doc erratum appended (`plans/archive/extra-cover-style-pipeline-round1029/deployment.md` секция 6 — «EXTRA production acceptance was incomplete…», история не стиралась); re-eval §122: НЕ «просто rerun» — integration-покрытие добавлено ПЕРВЫМ (§120 contract-файл), затем `pytest -k "extra or cover"` = **623 passed**; mock-тесты route-семантики (`test_extra_cover_styles_api.py`) сохранены, их слепая зона закрыта contract-файлом.
* **Обновлённые якоря зоны H** (санкции D14/§102/§105/§126): `test_extra_cover_style_pipeline.py::test_per_style_override` (FK вместо raw URL — тест, закреплявший дефект «ID=URL»), `test_extra_cover_styles_ui.py::test_ru_labels_present` («Модель и подключение» §109, «Настроить подключение» §126), `test_extra_cover_style_registry.py::test_idempotent_if_not_exists` (PG-DDL 5→6), `test_round1025_f8_registry.py` (ROUTES_SHA256_F11 re-approved по прецеденту L-F11S-1; hidden=2; fixture sha256 для param_catalog/routes/pg_db), `test_budget_guardrails/test_pg_db/test_budget_data_repair` (PG-DDL 51→52, CREATE TABLE 25×2).

### T-4233 — bump

* `config/settings.py`: APP_VERSION 2.58.39 → **2.58.40** (+ баннер Pass 2); `README.md` — v2.58.40 + сводка. Version-pinned якоря re-pinned (23 py-файла + 4 JS-файла с regex-пинами). F8 переиздан (`tools/gen_param_registry_round1025.py` emit; **CHECK OK**): Δ каталога = 0 — 488/427/463/105/103/21 (hidden — атрибут существующей записи, counts не менялись). SQLite DDL = 0 (v19; v20-бронь `mca-04b` не тронута). PG DDL: +1 таблица (Δ-лист выше).

### Результаты тестов (финальные прогоны)

* **Полный pytest: 10316 passed / 2 failed** — оба failed = известные якорные forbidden-paths (чужие, web/-diff vs старого baseline-коммита; те же, что в baseline/Pass 1): `tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`, `tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`.
* **JS: 52 passed / 0 failed** (все 52 файла `tests/js/*_test.js`).
* **F8: CHECK OK** (488 строк; Δ каталога = 0).
* **UI E2E: OK** (`tools/ui_asap32_cover_styles_e2e.py`, RC=0).
* Новые Pass-2 тест-файлы: contract 11 + semantic_reduction 13 + fallback_recompose 8 + llm_decision 13 = **45 passed**.
* Срезы в процессе: `-k "summary"` = 1176/0; `-k "extra or cover"` = 623/0; direct/decision-сьюты = 340/0.

### Отклонения / решения, требующие внимания Reviewer

1. **Якоря, обновлённые по санкции D11**: test_llm_react_asap31 (SILENT-сценарии, instruction-блок), test_direct_decision_matrix_asap3 (ack-сценарии) — поведенческий сдвиг «алгоритм решает действие» → «LLM решает действие»; старое поведение = OFF-паритет `DIRECT_LLM_DECISION_ENABLED=false`.
2. **Семантика ответа Decision Task**: текст-ответ (не с `{`) = сознательный REPLY и отправляется; битая JSON-попытка → fallback БЕЗ отправки мусора (усиление: раньше JSON-мусор ушёл бы текстом).
3. **read/select Cover Styles** ослаблены до `requires_permission('access')` (§135); мутации — global-admin (seeded admin-only, backend-enforced). Делегируемое право в матрице прав не вводилось (default «системное admin-only» удовлетворяет §135).
4. **PG-DDL 51→52** — санкция D14/§104 (spec H.2: аддитивный идемпотентный DDL под connection-model); Δ-лист выше.
5. **UI E2E — stub-backend**: реализационная верификация §115; production acceptance (§96/§116–§119/§130 — 20 пунктов, real authenticated backend) НЕ закрыта Builder'ом — за Reviewer/DevOps (T-4227/T-4232).
6. **Seed-call-site отсутствовал в проде** — найден и исправлен (startup); на проде после деплоя первый seed создаст профиль (идемпотентно; если владелец ранее вручную создал medved_press — no-op).
7. **Инструментальный инцидент**: PowerShell Set-Content дважды портил UTF-8 (BOM/CRLF) в conftest.py/summary_fact_package.py — восстановлено; финальные файлы BOM-free; правки — только через Write/Edit.
8. **Stale-bytecode ловушка**: same-second правки + `__pycache__` давали фантомные ошибки — кэш чистился; на финальных прогонах не воспроизводится.

### Не выполнялось / вне скоупа Pass 2

* Production live acceptance (§76–§79, T-4234+), production browser E2E против real authenticated backend (§96/§116–§119/§130 — T-4227/T-4232).
* Коммит/деплой (запрещены инструкцией).
* T-4205/T-4218 [@Architect], T-4209/T-4212/T-4214/T-4227 [@Reviewer] — не тронуты.
* T-4229 — закрыт как «покрыто»: capacity/capability switch — Pass 1; execution-policy switch проверяется media-тестами Pass 1; UI refresh — T-4232 (browser, Reviewer/DevOps).
* Реальные платные вызовы — не выполнялись.

### Как проверить (для Reviewer)

```text
cd C:\Code\Python\adminbot
.venv\Scripts\python.exe -m pytest tests -q
  expect: 10316 passed, 2 known anchor forbidden-paths failures (чужие, поимённо выше)
node --test (52 файла tests\js\*_test.js)
  expect: 52 passed
.venv\Scripts\python.exe tools\gen_param_registry_round1025.py --check
  expect: CHECK OK (488; Δ каталога = 0)
.venv\Scripts\python.exe tools\ui_asap32_cover_styles_e2e.py
  expect: COVER STYLES UI E2E: OK (RC=0)
.venv\Scripts\python.exe -m pytest tests/test_cover_styles_contract_asap32.py tests/test_summary_semantic_reduction_asap32.py tests/test_direct_fallback_recompose_asap32.py tests/test_direct_llm_decision_asap32.py -q
  expect: 45 passed
git status --porcelain  # изменённые файлы — списки выше; чужой WIP не тронут
```

Git-состояние на момент сдачи: HEAD `1287130`, изменения НЕ закоммичены (worktree), коммит/деплой — вне полномочий Builder.

## Post-review fix — H-ASAP32-1 (blocking; fix 01.10.2026, Builder)

**Изменения (diff-резюме файл:строки):**
* `services/summary_fact_package.py` — байт-ремонт **221 строки** (двойное UTF-8-кодирование → корректные литералы). ASCII-проекция каждой изменённой строки идентична (код/структура не менялись). Контроль по трём runtime-сайтам из review: L84 `FALLBACK_TOPIC_NAME = "Общий ход обсуждения"` (байты `d0 9e d0 b1 …`), L118 `DESCRIPTION_SEPARATOR = " · "` (`20 c2 b7 20`), L279 `cut.rstrip(" ·")`. В файле 0 вхождений `d0 92 c2 b7` («В·»), `c3 92`, `ef bf bd`; 0 строк, чинимых round-trip cp1251→utf-8 (до фикса — 221; детектор учитывает 0x98-дыру sloppy-cp1251 как U+0098). Строки 982–983 — уже чистый текст (CRLF-хвост прошлого Set-Content-инцидента) — не тронуты (CRLF-шум = L-ASAP32-3, вне скоупа).
* `tests/test_summary_fact_package.py:644–691` — новый НЕтавтологический класс `TestSourceEncodingIntegrity` (3 теста): литералы ассертятся против ожидаемых значений, заданных в самом тесте («Общий ход обсуждения», `" · "`), кодпоинт-проверки (первый символ 0x041E «О», не mojibake-«Р»; разделитель len=3, [1]==0xB7), явное неравенство повреждённому варианту `" В· "`, байт-аудит исходника модуля (отсутствие `d0 92 c2 b7` / `c3 92` / `ef bf bd` + round-trip-детектор = 0 строк). CRLF-конвенция тест-файла сохранена (691 CRLF / 0 LF).
* `services/graphrag_rebuild.py:473–481` — **M-ASAP32-2** (рекомендация ревью, взята как тривиальная): re-check `memory._identity_fingerprint() != fp → RuntimeError("fingerprint_changed")` первой строкой `_body` транзакции активации. Rollback → `activation_failed` (терминальный fail джобы), shadow цел, FTS serviceable, self-heal на следующем startup-schedule — семантика §3/§66/§70 не нарушена.

**Верификация:**
* Свежий импорт без байткод-кеша (`python -B`, `__pycache__` очищен): обе константы корректны, py_compile OK.
* Целевые наборы: test_summary_fact_package + test_summary_semantic_reduction_asap32 + test_l2_budget_asap31 + test_graphrag_rebuild_asap32 = **84 passed** (вкл. 3 новых теста).
* Срез `-k summary` = **1179 passed / 0 failed**.
* Полный pytest (чистый `__pycache__`, `-B`): **10319 passed / 2 failed** — те же 2 якорных чужих forbidden-paths (test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff, test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline); 10316 базовых + 3 новых. Первая попытка прогона упёрлась в pytest-timeout (60s/thread, asyncio selector) на фоне нагрузки окружения — разовый флейк среды (не продукта): повторный прогон чистый, 276s, timeout-событий нет.
* Чужой WIP (mca-04b, extra_images, node_modules, package*) не тронут; HEAD `1287130` без изменений; ничего не закоммичено.

**WTH-рецепт (уточнение к review.md §Binding):** binding-хеш = SHA-256 контента `plans/reports/asap32_wth_manifest_review.txt` с **LF-концами строк** (файл хранится CRLF; проверено воспроизведением: LF-нормализация даёт `2e61d740…97d967`). Состав: HEAD + staged + sha256/bytes `git diff HEAD` + tracked-modified-count + per-file sha256 всех untracked — 336 записей, как в исходном артефакте; порядок = git status, внутри свёрнутых каталогов — os.walk; написание путей как в старом артефакте: forward-slash префикс git сохраняется, составляющая ниже свёрнутого каталога — через backslash (валидировано перекрёстно: хеши нетронутых файлов совпали со старым манифестом байт-в-байт). Исключения: сам манифест и `review.md` (самореференц; прецедент tools/_asap3_wth.py: артефакт ревью вне манифеста, WTH-литерал не кладётся внутрь хешируемых доков). Внешние дельты после ревью не от Builder'а: mca-04b spec.md изменён параллельным WIP, tracked-modified 78→79 (в т.ч. поздние записи plans/workflow_state.md и plans/reports/full_audit_results.md — Orchestrator/другие агенты). Значение WTH после фикса — в handoff Builder→Orchestrator; сам хеш внутрь манифеста не кладётся (самореференц), файл манифеста перезаписан после фикса.

**Проверка Reviewer (репродукция):** hex-дамп трёх сайтов (выше), свежий импорт `python -B -c "from services.summary_fact_package import FALLBACK_TOPIC_NAME, DESCRIPTION_SEPARATOR; assert FALLBACK_TOPIC_NAME == 'Общий ход обсуждения'; assert DESCRIPTION_SEPARATOR == ' · '"`, pytest-команды выше (expect 10319 passed / 2 known failed), sha256(LF-контент манифеста) = новый WTH.
