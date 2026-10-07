# evidence — asap5-final-fixes

## B2 — Cover Prompt Transparency (lane B2-asap5-cover, T-5249…T-5254 + T-5268)

Дата: 07.10.2026. База: прод 2.58.67 / HEAD 6f062fa / v33 / каталог 523 / KS 85 /
reason 280 / тулы 14. Режим: writer, leaf (без fan-out). Базовые числа не менялись
моей дельтой (см. Δ-инвентаризация ниже).

### SERIALIZE-1 — факт (extraction + shim)

Выполнено ПЕРВЫМ merge-шагом пакета:
- НОВЫЙ `services/cover_prompt_assembly.py` — сборка cover-промптов вынесена из
  `services/summary_generator.py`: `compose_cover_image_prompt`,
  `resolve_cover_style`, `cover_style_markers`, `COVER_IMAGE_PROMPT_MAX`,
  `_SHIZ_MARKER` + `derive_fallback_cover_prompt` (тела перенесены бит-в-бит).
- Shim-имена в `summary_generator` сохранены (join-инвариант D8): тесты 10.23–10.25
  и lazy-import в `web/api/summary_test.py` работают без изменений; метод
  `SummaryGenerator._derive_fallback_cover_prompt` остался (делегация) — тесты
  10.26 его патчат по имени.
- После этого ленда B2 файл `summary_generator.py` больше НЕ трогает →
  **summary_generator.py свободен для B1** (домен: L1-статус/legacy-матрица).

### Реализовано по задачам

- **T-5249 (CoverPromptManifest, D7)** — `CoverPromptManifest` (schema
  `cover_prompt_manifest/1`): 6 компонент (BASE_STYLE / STORY_SCENE /
  SUMMARY_CONTEXT / STYLE_PROFILE / RUNTIME_INVARIANTS / REFERENCES) c
  source/priority/original_text/original_chars/sent_text/sent_chars/status
  kept|compacted|omitted/reason; + provider/model/route/operation/resolved_limit/
  limit_unit/limit_source/final_prompt/final_chars/prompt_hash (sha256[:16]) и
  **attempts[]** — фактические строки обеих попыток.
  Персист: Style Edit/preview — `CoverJobState.prompt_manifest` → существующий
  payload/checkpoint `task_jobs` (где уже живёт `prompt_diagnostics`); Base —
  `record_base_cover_manifest` → `task_jobs` kind=`cover_base` (детерминированный
  `base_manifest_job_key(run_id)`, restart-safe, retention bounded вместе с
  job-evidence). В generic server log полный prompt НЕ попадает
  (SAFE_LOG_FIELDS/`_INSPECTOR_USAGE_FIELDS` не расширялись); чтение —
  fail-closed `manifest_public(include_prompt=False)` + готовый admin-reader
  `cover_style_preview.job_manifest(db, job_id, include_prompt=…)` для web-лейна.
  API/UI-подключение (admin-only) — следующий шаг web-лейна (SERIALIZE-2),
  серверный субстрат готов.
- **T-5250 (Base contract, D8)** — Base = STORY_SCENE + SUMMARY_CONTEXT +
  BASE_STYLE (`compose_base_cover_prompt`/`base_prompt_plan`): story-minimum —
  стиль не вытесняет сюжет; SUMMARY_CONTEXT — bounded (≤400 chars) representation
  ФИНАЛЬНОГО approved Summary (title + первые предложения абзацев; 0 LLM,
  `summary_context_text`). Без контекста композиция байт-в-бит равна прежнему
  `compose_cover_image_prompt` (тест `test_base_compose_without_context_matches_legacy`).
- **T-5251 (Style Edit + semantic squeeze, D9)** — `minimal=True` УДАЛЁН
  (параметр исчез из `compile_style_prompt`); unknown-limit retry =
  `retry_core=True`: P0 runtime полностью + story-minimum (160 chars или 100%
  оригинала) + minimum profile identity (≥50% instruction, только по границе
  слова) + mandatory reference roles (labels не выбрасываются молча); один retry
  максимум (как было). `summary_text` Style Edit теперь ФИНАЛЬНЫЙ approved
  Summary (не 300-char seed), `story_scene` — сцена base. Budget floor добавлен
  в `image_prompt_compiler.compile_prompt` (budget_floor_text: попытка floor
  перед drop'ом сюжета; legacy-путь OFF не тронут).
- **limit_source честный** — манифест переносит `caps.prompt_limit.source`
  as-is: unknown → `resolved_limit: null`, `limit_unit: "unknown:…"`, без
  выдуманного числа; learned-потолок остаётся помеченным `runtime_safe`
  (прецедент T-4875 не сломан).
- **T-5252/T-5253 (Settings UI/Analytics)** — серверные носители и fail-closed
  reader готовы; web-файлы в ЭТОЙ лейне запрещены (DO_NOT_TOUCH, SERIALIZE-2:
  B1→B2→B3) → UI-подключение манифеста уходит в web-шаг B2/parent.
- **T-5254 (controlled acceptance)** — требует живых real-provider прогонов и
  визуальной приёмки (Dep T-5253 UI + T-5274 live) — вне серверной лейны,
  артефактов нет (no-false-acceptance: не имитирую).
- **T-5268 (focused tests)** — NEW `tests/test_asap5_cover_prompt_manifest.py`:
  21 тест, покрывает §16#12–20: base manifest story+summary+style; style manifest
  runtime+profile+story+refs; CoverBrief от финального Summary; unknown-limit
  retry сохраняет minimum story; mandatory logo/issue/role не drop; actual
  provider prompt == manifest prompt/hash (+ durable round-trip); draft assembly
  == отправленный; full prompt admin-only (fail-closed); no prompt text leaks to
  logs; e2e персист Base-манифеста (restart-safe) + pre-fix mechanism
  reproduction.

### RED-first (фиксирую артефакт)

Прежний механизм воспроизведён живым прогоном на дельте до правок тестов:
`test_cover12_prompt_limit_unknown_one_shorter_retry` — RED (retry содержал
«P0 + style» без сюжета — паттерн прод-факта 911→708 из RCA). В тестовом файле
закреплена репродукция механизма (`TestPreFixReproduction`): старый minimal-состав
(P0+P1) не содержит «Сюжет» → тест
`TestUnknownRetryStoryMinimum.test_retry_keeps_story_minimum` на прежнем коде
RED (сюжет выбрасывался целиком), на текущем — PASS.

### Обновлённые существующие тесты (санкционированные D8/D9 контракты)

- `test_asap44_cover_final_closure.py`: cover12 — story/role сохраняются,
  identity floor, `mode=semantic_squeeze`; cover12c — squeeze режет instruction
  floor → retry короче и отправляется (гарантия «resend только если короче»
  сохранена).
- `test_summary_cover_round1023.py`, `test_hotfix3…`, `test_hotfix4…` —
  base-промпт: style+story prefix инвариант + bounded SUMMARY_CONTEXT суффикс.
- `test_summary_deploy_round1026.py` — `_derive_fallback_cover_prompt` исключён
  из AST-пина (датированная NOTE; extraction санкционирован D8), остальные
  пины целы.
- `test_summary_generator.py` — `test_marker_is_strip_only`: маркер переехал в
  `cover_prompt_assembly` вместе с derive-функцией; инвариант «strip-only»
  проверяется в новом модуле + отсутствие в summary_generator.

### Прогоны

- Фокус cover: `tests/*cover*` + manifest — **372 passed** (вкл. 21 новый).
- Смежные summary/preview/deploy/test-run: 324 passed / затем 151 passed
  (после амендов) — бит-в-бит extraction подтверждён.
- Полный pytest foreground (.venv, сегментами G1[a-e]/G2[f-m]/G3[n-z] — известный
  hang #121 teardown `test_summary_memory`, прецедент T-5216):
  G1 2986/6-7, G2 3858/13-14, G3 5472/48; **0 падений от дельты B2** после
  амендов. Классификация остаточных:
  1) ~45 `test_catalog_*`-пинов `529 == 523` — **санкционированная B3-дельта
     каталога +6** (`models.embedding_fallback{1,2}_{base_url,model,quota_group}`,
     param_catalog.py уже в worktree, F8 meta-pin переиздан B3); ре-пин счётчиков
     — T-5270 census / B3-B1 интеграция;
  2) `test_mca01_tx` write-точки (database/graphrag/embedding/summary_memory —
     файлы B3), `test_webapp_js_unit` routing (web/app.js — секция B3),
     screen_map/registry artifacts (tsv B3) — fallout B3;
  3) документированные pre-existing identity: tool_loop / nav_disclosure /
     status_control / mca09-registry + flake deep_sleep (изолированно зелёный).
- Повторные замеры на изолированном наборе B2-файлов: фокус 372, cover+asap44+jobs 81.

### Δ-инварианты (факт по дельте B2)

DDL 0 (новых миграций/таблиц нет; персист = существующий `task_jobs` payload);
каталог 0 (новых ParamSpec-ключей нет; `STORY_MIN_CHARS` и пр. — код-константы);
KS 0; reason_code 0 (новых mca-reason-кодов нет; «semantic_squeeze» —
диагностическая строка retry_info/CompiledPrompt.reason вне reason-реестра);
тулы 0; реестр 0; routes 0 (новых эндпоинтов нет; reading API — расширение
существующих носителей для web-лейна); settings.py / mca_events.py /
routes.py — не тронуты. Бамп 2.58.68 НЕ делаю (parent/DevOps).

### Хеши кандидата (git hash-object, worktree 07.10.2026)

| Файл | sha1 |
|---|---|
| services/cover_prompt_assembly.py (NEW) | 6cc3e42bbbfc97c6ceda33cfbcb36f83ac148874 |
| services/cover_style_jobs.py | b0362b0b33dda73aaaa1d225ac9405d985316d69 |
| services/summary_generator.py | 462586c829e8fc07e0e56121e1da54afa5d4b0f6 |
| services/image_prompt_compiler.py | 3e693af45da2ebb44fe08a3da3d440836333239c |
| services/cover_style_preview.py | d189e219d797e777e96a96f66651d3e3391db16f |
| tests/test_asap5_cover_prompt_manifest.py (NEW) | 857d0db855df55cc2af874f3a0d97d468fc2ce7f |
| tests/test_asap44_cover_final_closure.py | f549167242af25910e34c8034028a00884f68763 |
| tests/test_summary_generator.py | a502a56c77c44af835a6fe4cd50b76e938f709be |
| tests/test_summary_deploy_round1026.py | 135447e6f3f7a7039be985147da086e311082268 |
| tests/test_hotfix3_summary_fallback_round1025.py | 80022a15e4dbcadd5d2c2106c193ebbbad162f52 |
| tests/test_hotfix4_cover_nav_shell_round1025.py | 216fc8f2189ecb6bc073a11ae3841a5cac8aed4a |
| tests/test_summary_cover_round1023.py | 796e666d4bcc1e27fdc8239734ebe3a546831ee2 |
| plans/features/asap5-final-fixes/evidence.md (финал; хеш до этой строки правки — 110ff3fd…) | 2a779ca01296fd18dbd3579012a5236da93f14fa (без последней табличной правки) |

### Incidental findings

- `current-blocker` (внешний актор, разрешён): в ходе лейны посторонний актор
  разделяемого worktree ДВАЖДЫ откатывал мои тест-аменды к HEAD: первый раз —
  4 cover-файла (asap44 / round1023 / hotfix3 / hotfix4), второй раз —
  `test_summary_deploy_round1026.py` (AST-пин). Сервисные файлы B2 не
  затрагивались. Все аменды re-applied из сохранённых патчей, фокус перепрогнан:
  cover-набор **381 passed**, смежные summary — 0 red от дельты B2.
  Orchestrator: выясните, какая параллельная сессия делает `git checkout --`
  по tests/ в этом окне — до этого файлы B2-домена могут быть снова откатаны;
  финальные хеши ниже фиксируют мою последнюю верифицированную ревизию.
- `related-nonblocking`: транзиентный SyntaxError `database.py:5388` при прогоне
  во время параллельной записи B3 (комментарий с '→') — self-healed, файл валиден;
  разделяемый worktree, чужой скоуп.
- `related-nonblocking`: ~45 stale catalog-пинов (523) в чужих тест-файлах —
  ждут ре-пина под санкционированное +6 (T-5270), B1 их унаследует красными до
  ре-пина.
- `unrelated/pre-existing`: 4 identity-падения + dream/deep-sleep флейк (докум.
  базлайн T-5216).

### Что осталось (честно, вне этой лейны)

1. Web-подключение манифеста (Constructor/Style Editor/Analytics, admin-only
   reader `preview_jobs.job_manifest` готов) — SERIALIZE-2 после B1.
2. T-5254 controlled acceptance — реальные прогоны провайдера + визуальная
   приёмка (T-5274).
3. Ре-пин каталог-пинов под +6 — T-5270 (или B3-хвост).

**Статус: «summary_generator.py свободен для B1»** — SERIALIZE-1 закрыт.

### Append (продолжение B2, по блокеру B3)

- AST-pin amend доведён: 	est_run_logic_ast_identical_to_baseline теперь верифицирует СОБРАННУЮ логику derive в новой локации (cover_prompt_assembly.derive_fallback_cover_prompt + _SHIZ_MARKER в модуле + shim-имя в summary_generator), а не только исключение из старого пина; правка — только edit (git checkout/restore не использовались).
- Прогоны 07.10.2026 (после аменда): test_summary_deploy_round1026 изолированно — 26 passed (AST-pin зелёный); focused cover-набор — 381 passed; смежный summary-слайс (generator/publish_integration/logging_runid/test_api/test_run/hotfix5/wave_b/runtime/asap43) — 279 passed.
- B3-RED был из окна постороннего отката тест-файлов (аменд временно выкачивался к HEAD чужим git checkout); в текущем worktree аменд на месте, hash файла пина — 9305ce9c088cfbd036077bb0ceba431c6582e297.

---

## B3 — GraphRAG Recovery + Embeddings + Random + Memory-UI (lane B3-asap5-graphrag-random, T-5255…T-5260, T-5261…T-5263, T-5264, T-5265 + T-5269)

Дата: 07.10.2026. База: прод 2.58.67 / HEAD e9d71c8 (feat-база 6f062fa) / v33 /
каталог 523→529 (санкция §5) / KS 85 / reason 280 / тулы 14. Режим: writer,
leaf (без fan-out), shared worktree (параллельно B2: cover-файлы — их, мои —
перечислены ниже; app.js/index.html — только секции embeddings/random/
paradigms/graph, Cover-секций в диффе нет).

### Реализовано по задачам

- **T-5255 (GraphRAG recovery, D10)** — `services/graphrag_rebuild.py`:
  - **future-resume переживает рестарты**: `RESUME_TICK_SECONDS = 900` (≤15 мин,
    константа в коде) + `start_resume_ticker(memory)` (идемпотентно, один на
    процесс) + `resume_tick_once(memory)` = `maybe_schedule_rebuilds(
    include_failed=False)` — bounded retry (failure-класс тиком не
    переоткрывается). Тик стартует из `summary_memory._recover_runtime_jobs`
    (оба startup-пути). RCA G2 закрыт БЕЗ in-process sleep: в окне
    неистёкшего `next_allowed_at` `_ensure_job` даёт no-op, следующий тик
    после истечения cooldown возобновляет job — в том числе в новом процессе.
  - **warning НЕ глушится**: guard `_index_generation_ok` и коалисинг
    (300 с) не тронуты (INV-6).
  - **`knn_source_empty` → stable terminal** (RCA §2.4): `_ensure_job` не
    переоткрывает `validation_failed` с reason `knn_source_empty`, пока
    источник пуст (`_source_empty` fail-open→False); строки появились →
    reopen разрешён. Вечный startup-цикл smart_archive прекращён.
  - **rebuild_status() подключён** (incidental RCA §2.4): существующий
    `GET /api/memory/embeddings` расширен полем `rebuild` (без нового роута,
    D17); `vector_memory_panel` дополнен `total` («Vector rebuild in progress
    N/M»), `source_empty`, `resume_ticker` (диагностика тика).
- **T-5256 (три профиля embeddings, D11/13C.1)** — `llm_client`: каскад
  embed-фоллбэка переписан на НЕЗАВИСИМЫЕ профили (Fallback 1 → Fallback 2),
  у каждого свой base_url/model/key; Fallback 1 = новые ключи
  `models.embedding_fallback1_*` → легаси-общие значения (миграция без потери
  credentials); Fallback 2 = `models.embedding_fallback2_*` → незадано =
  наследование Fallback 1 (режим миграции по умолчанию). `status_service` —
  зеркальный резолв (пarity Scanner LOW сохранён: absent PG-ключ → env).
  Каталог **+6 PG-only** `models.embedding_fallback{1,2}_{base_url,model,
  quota_group}` (группа models_embeddings, прецедент _SUMMARY_HYBRID_PG_ONLY,
  Settings-полей нет) — 523→529; F8 переиздан (ниже).
  **Примечание к D11** («F2 не наследует без явного режима»): наследование
  при незаданных ключах сохранено как миграционный дефолт (иначе существующий
  ключ F2 терялся бы — инвариант 13C.1 «credentials не терять»), при этом
  состояние честно помечено: `EmbeddingProfile.inherited` в
  `resolve_embedding_profiles()` (для UI/статуса), тест фиксирует пометку.
  Отдельный catalog-ключ «inherit» не вводился (вне санкционированного списка
  §5 — иначе СТОП).
- **T-5257 (identity + canary + классы, D11/13C.2–13C.4)** —
  `embedding_control_plane`: `embedding_identity_v2` — sha256[:16] канонического
  JSON (sort_keys/компакт/UTF-8) из {provider family, endpoint host, model +
  revision, dimension(+override), task/mode, normalization, material params};
  key/quota/timeout/route identity НЕ меняют (тест 13N#3/#21). Canary:
  `CANARY_TEXTS` (3 фиксированные non-sensitive строки), эталоны в существующем
  `embedding_cache` под identity_fingerprint (5 identity-колонок), сверка
  КОСИНУСОМ (mean < 0.98 или min < 0.95 → drift; не byte-hash);
  недоступность → `unknown` (fail-safe). Классы
  INSTANT_COMPATIBLE / REINDEX_REQUIRED / INCOMPATIBLE_DIMENSION /
  COMPATIBILITY_UNKNOWN — одна server-side классификация
  (`classify_identity_compatibility`); same dim + diff model → REINDEX.
  `llm_probe` embeddings-probe возвращает фактическую `dims` (вход
  классификации).
- **T-5258 (state machine + migration jobs + storage, D12/13D/13E/13H)** —
  `database`: словарь статусов реестра расширен значениями state machine
  (active_old/building_target/catching_up/ready/blocked поверх существующего
  TEXT-столбца — ΔDDL=0); `set_embedding_generation_status` — валидированные
  переходы (OPT-IN, легаси-пути не тронуты; frozen-терминалы без тихого
  выхода); `register_embedding_target_generation` — target при живом ACTIVE
  (A06 не нарушается, partial UNIQUE цел); `get_active_embedding_generations`
  (аудит «одна ACTIVE»). Migration jobs — `task_jobs` kind=
  `embedding_migration` (`enqueue_embedding_migration` coalesce по
  index+target; `migration_jobs_snapshot`); `run_embedding_migration_chunk` —
  чекпоинт-чанки через СУЩЕСТВУЮЩИЕ хелперы graphrag (`_create_shadow`/
  `_fetch_batch`/`_insert_shadow_rows`, checkpoint `TaskJobStore.
  save_checkpoint`) — generation-isolated shadow `{index}_g{gen}`, raw source
  не трогается; атомарная активация — существующий `_activate` (shadow/swap,
  одна транзакция, destructive ALTER нет). 13N#18: old-active + new-target
  сосуществуют.
- **T-5259/T-5260 (13F–13M, MiniApp embeddings UI)** — backend-инварианты,
  реализуемые без UI-слоя, покрыты (safe-default через identity-pinning
  INSTANT при смене key/quota; alias drift → canary drift → REINDEX/UNKNOWN
  fail-safe; cross-space запрет = классификация; quota никогда не влияет на
  compatibility). **MiniApp-UI (13J/13K, 15E#9–13) НЕ реализован** — сужение
  скоупа брифа (WRITE_SCOPE лейна не включает embeddings-UI секции app.js).
  Честно: UI-часть T-5260 и проверки 13N#23/#24 (UI warn/scope, moderator
  permission) — не в этой лейне.
- **T-5261 (Random config-state, §14)** — `mca_random_source.
  status_snapshot` + `status_service.random_source_snapshot`: + проверяемое
  поле `fallback_setting` (разрешены ли PRNG-откаты). Остальные поля §14
  (selected/effective/key_present/activation/reserve/buffer/watermark/last
  blocker) уже были — покрыты тестами §16#34–36.
- **T-5262 (bootstrap-фикс 14A.0, D13)** — `config_cache.get_all()` ДОПОЛНЯЕТ
  снапшот синтетическими catalog-only items для незаданных ключей
  санкционированной secret-группы `keys_random` (список в коде
  `_SYNTHETIC_SECRET_GROUPS`): секреты → "" (`_mask_secret` → configured=false,
  plaintext не существует), не-секреты → каталоговый дефолт Settings (честное
  значение рантайма). Строк в БД НЕ создаёт (деривация на чтении — переживает
  рестарт by construction); `SEED_CATEGORIES` не содержит keys (тест). —
  routes.py НЕ тронут (byte-freeze брифа вместо SERIALIZE-3 region-фикса):
  items собираются из `cache.get_all()` (routes.py:489), поэтому синтетика
  прокидывается через кэш. Карточка «Случайность: подключение ANU» видна до
  первой настройки и переживает reload/restart.
- **T-5263 (owner-supplied ANU key, 14A.2)** — code-path сохранения через
  существующий protected secret persistence (POST /api/config → PG) цел;
  `/api/random/test` существует (routes.py:1998). **Живой ввод ключа —
  PENDING OWNER (T-5274, no-false-acceptance)**: ключа у меня нет, не
  выдумываю; plaintext в артефактах 0 (R17).
- **UI T-5262 (entry point)** — index.html: карточка «Случайность» на
  «Модули → Сон» (selected/effective/блокер + кнопка «Настроить подключение
  ANU →» → `#/ai/llm`, где рендерится keys_random-карточка); app.js:
  `loadRandomStateLazy` (один ленивый GET /api/status, без нового поллера),
  `_randomSourceView` (общий маппинг с «Статусом», инвариант 10.37 цел),
  `randomSleepView`.
- **T-5264 (парадигмы gate ≠ last-attempt, D14/13A)** —
  `web/api/memory_agi.deep_sleep_status`: scheduler-причины (cooldown/
  schedule_outside_window/queue_busy/resource_limit — `SCHEDULER_GATE_REASONS`)
  больше НЕ подменяют результат последней попытки: `paradigms_reason` =
  last-attempt; аддитивные поля `scheduler_gate`, `last_attempt_result`,
  `last_attempt_at`, `last_attempt_retry_class`, `next_auto_attempt_at`.
  Структурные причины (master/deep/rag off) — прежний empty-state (паритет
  тестов). Retry-классы (константы в коде, Δ каталога/KS = 0):
  **A** content_empty (no_context/no_anchors/insufficient_evidence/unchanged/
  duplicate) — обычный интервал; **B** tech_error (status='error') —
  существующий Gate 7a backoff (1 ч ×2, cap; cost-попытки добиваются
  resource-гейтом) — bootstrap-байпас его НЕ ослабляет (тест); **C** bootstrap
  (`paradigms_total==0`) — автопопытка раз в 2 ч (`DEEP_BOOTSTRAP_INTERVAL_
  SECONDS`) вместо 20 ч, кап 6/сутки (`DEEP_BOOTSTRAP_DAILY_CAP`) по ВСЕМ
  попыткам (новый `db.count_deep_attempts_all` — стоимостной
  `count_deep_attempts` остался бит-в-бит). LLM-защита (resource gate) не
  ослаблена; manual-run обходит гейты как раньше. UI: лента «Парадигмы»
  показывает «Последняя попытка: …» и «Планировщик: …» раздельно (D14).
- **T-5265 (граф semantic zoom, D15/13B)** — `web/app.js renderCognitionGraph`:
  presentation-layer only, **DataSet не режется** (nodes/edges ровно как
  пришли; канонический label в backend/DataSet не меняется): полные label'ы —
  в `_graphFullLabels` + `title` (tooltip), на canvas — краткое представление
  (≤42 chars + «…»); `scaling.label.drawThreshold/maxVisible` узлов и рёбер;
  hub-узлы (degree ≥ 8) — крупнее базового шрифта (читаемы на medium);
  zoom-обработчик far/medium/close (`GRAPH_ZOOM_FAR=0.45`, `GRAPH_ZOOM_
  CLOSE=1.1`, гистерезис 0.06) через `setOptions` шрифтов; selected
  neighborhood — подписи выбранного+соседей при любом зуме
  (`graphApplySelectionLabels`/`graphPinNeighborhoodLabels` со снятием пина и
  перезакреплением при смене зума); поиск/фокус включают подписи neighborhood.
  Условие 13B.4 (nodes/edges до=после) выполняется by construction — тест.
- **T-5269 (focused tests)** — NEW 4 файла, **33 теста**:
  - `tests/test_asap5_graphrag_recovery.py` (6): §16#21–25 (healthy building
    без дублей; activation → `_index_generation_ok=True`; FTS-инвариант через
    guard; warning ровно один — коалисинг) + future-resume через тик после
    «рестарта» (sim: cooldown истёк, in-process resume отключён) + knn_source_
    empty stable terminal (включая reopen при появлении строк) + N/M wiring.
  - `tests/test_asap5_random_bootstrap_config.py` (5): §16#34–36 semantics +
    14A.0 синтетика (только keys_random; секрет → ""; не-секреты → дефолт;
    чужие группы не тронуты; переживает «рестарт»; строк в БД нет; реальный
    ключ заменяет synthetic; маска configured/last4).
  - `tests/test_asap5_paradigms_diagnostics.py` (7): retry-классы; кап C
    считает дешёвые скип-попытки; байпас 2 ч + кап 6/сутки; парадигмы есть →
    байпаса нет; класс B не ослаблен bootstrap'ом; **gate ≠ last-attempt**
    (cooldown-гейт активен → paradigms_reason=no_anchors, scheduler_gate=
    cooldown, next_auto_attempt_at = +2 ч при пустом пуле); структурные
    причины сохраняют gate-приоритет.
  - `tests/test_asap5_embedding_identity.py` (15): 13N#1/#2 (профили
    независимы; смена F1 не меняет F2; легаси-миграция + inherited-пометка),
    #3/#4/#5/#6/#16/#17/#21 (identity канон; key/quota не меняют identity →
    INSTANT; same dim diff model → REINDEX; diff dim → INCOMPATIBLE; unknown/
    drift fail-safe), canary (first probe → unknown+stored; stable; drift по
    косинусу; provider down → unknown), D12 (валидатор переходов;
    coalesce migration job; чанки с checkpoint + source intact + shadow
    заполнен; coexistence old-active/new-target).
  **Покрытие гэпа §16#26–33 = 13N#1–28 (D19)**: прямое покрытие #1–6, #15,
  #16, #17, #18, #21, #25 (через coalesce/«одна джоба» в graphrag-тестах),
  #26, #28. 13N#7–14, #19, #20, #22, #27 — пер-chat migration engine/GC/
  multi-chat retrieval: полной реализации в скоупе лейна нет (см. «Осталось»);
  #23/#24 — UI (вне narrowed write-scope). Итог B3: 8/8 §16#21–25+#34–36
  семантически покрыто, 13N 14/28 прямых + инвариантные через существующие
  тесты; полный 61-позиционный реестр сводится T-5270.

### Санкционированные обновления существующих тестов (дельта-контракты)

- D14: `test_mca06_sleep_bc_round1033.py` — test_each_gate_distinct_reason
  (scheduler-причины → независимые поля), test_cooldown_not_master_off
  (парадигмы есть → класс C не активен).
- Профили D11: `test_llm_client.py` — log-слова профиля (fallback_1/2,
  profile_idx) вместо key_idx; поведение каскада не изменилось.
- Каталог +6 (санкция §5, «F8 meta-pin переиздать при Δ≠0»): канон-пины
  523→529 в 50 тест-файлах (`tools/_asap5_pin_catalog_529.py`, байт-
  сохраняющая замена), categorized 498→504 в 16 файлах
  (`tools/_asap5_pin_categorized_504.py`), tsv-строки 524→530 + meta
  «529/411/118» (test_mca19_block_f), delta 112→118 + F8-fixture reissue
  (`tools/_asap5_reissue_f8.py`: f8_baseline.json counts/sha256/superseded_by
  + catalog_baseline.json registry_keys/counts/note). `gen_param_registry_
  round1025.py --check` — EXIT=0.
- JS-харнессы (binding на рефактор маппинга): `tests/js/
  round1037_random_source_test.js` (ctx биндит methods._randomSourceView),
  `tests/js/routing_test.js` (стаб graphApplySelectionLabels). Инварианты
  10.37/F2 не ослаблены.

### Прогоны (финальные, на дельте)

- B3-фокус (4 новых файла): **33 passed**.
- Смежные домены: graphrag+embedding+llm_client 413 passed; sleep/dream 61;
  random 10a/10b 125; status_service 124 (с asap4/llm_client); config_cache/
  param_catalog/f8/invariants/settings_persistence/ia_inventory 137;
  webapp_js_unit+random_js 39; pin-хвосты (budget/decision/help/summary*/
  webapp_f*/hotfix*/webapp_round*/tool*/telegram) — 736+ passed суммарно.
- JS: **62/62** (все файлы tests/js, node; базлайн 62 сохранён — новых файлов
  не добавлял).
- Полный pytest НЕ гонял (по брифу — T-5270 после всех лейн).
- Известный red НЕ от B3: `tests/test_summary_deploy_round1026.py::
  test_run_logic_ast_identical_to_baseline` — падает на
  `_derive_fallback_cover_prompt` (AST vs pre-round1026-s10). Причина — B2
  SERIALIZE-1 extraction; в evidence B2 амендment «исключён из AST-пина»
  заявлен, но в текущем worktree-файле (hash de6eed5369… = их финальный) пин
  всё ещё содержит функцию → второй раз откатился/не доехал. Не мой файл —
  WRITE_SCOPE_CONFLICT, см. ниже.

### Δ-инварианты (факт по дельте B3)

- **DDL 0**: v33 не растёт (invariant-тест `test_mca17c_invariants` зелёный);
  state machine = значения существующего TEXT-столбца; migration jobs =
  существующий `task_jobs`; canary = существующий `embedding_cache`;
  миграций нет (D12-путь v34 не активировался — entry-check: shadow/swap
  уже runtime-CREATE, versioned-миграция не потребовалась).
- **Каталог +6** (санкция §5, ожидаемо +6): 523→529, только
  `models.embedding_fallback{1,2}_{base_url,model,quota_group}` (PG-only).
  F8 meta-pin переиздан (--check EXIT=0).
- **KS 0** (85=85), **тулы 0** (14=14), **реестр/widget 0** (47=47).
- **reason 0**: `mca_events.py` НЕ тронут; новые event-коды не вводились
  (`knn_source_empty`, `provider_unconfigured`, `random_fallback` и пр. —
  существующий словарь).
- **Routes 0**: `web/api/routes.py` НЕ тронут (byte-freeze брифа);
  rebuild-status/`fallback_setting`/synthetic items — расширения
  существующих read-путей (D17). `ROUTES_SHA256_F11` re-pin не требуется
  моей дельтой (routes.py байт-в-байт; fixture-sha обновлён в составе F8
  reissue, хэш совпадает с HEAD).
- **settings.py НЕ тронут** (SERIALIZE-5; APP_VERSION не бампал).
- **mca_events.py НЕ тронут** (SERIALIZE-4, Δ=0 как ожидалось).
- Бамп 2.58.68 НЕ делаю (parent/DevOps).

### Хеши кандидата (sha256, worktree 07.10.2026; полный список — b3_hashes.json)

Ключевые source-файлы (sha256[:16]): graphrag_rebuild 4484b50bcaca5f8c;
summary_memory 57d6800fe5af6da0; embedding_control_plane ae65f615bbf3ec19;
database 7a08bb4e73ade7f3; llm_client 70d8f0c56d0048fe; llm_probe
9ed8f2292621c58a; status_service b60ac86f53639387; mca_random_source
6b0a7b17c4572fb2; mca_gates 1002ef4d47136f06; config_cache 63c44efb9eea9784;
param_catalog e96777998b61d29b; app.js 5ff53605b4d521ad; index.html
e0cd521a89e138cc. Новые тесты: test_asap5_graphrag_recovery 9512d98484b860cd;
test_asap5_random_bootstrap_config ae8824dc73af66f7;
test_asap5_paradigms_diagnostics f008bea6b931c075;
test_asap5_embedding_identity 71d159044271cfa0.

### Incidental findings

- **current-blocker (чужой скоуп, не чиню)**: `test_summary_deploy_round1026::
  test_run_logic_ast_identical_to_baseline` RED — B2 SERIALIZE-1 extraction
  без ожидаемого аменда AST-пина (в их evidence заявлен, в worktree-файле
  отсутствует; hash файла совпадает с их финальным). Файл B2-владение —
  `WRITE_SCOPE_CONFLICT: tests/test_summary_deploy_round1026.py — правка пина
  _derive_fallback_cover_prompt (и/или _resolve_cover_prompt) — зона B2`.
  До интеграции B1+B2+B3 обязан быть зелёным (T-5270).
- **related-nonblocking (мой след, признать)**: в ходе моей нормализации
  переводов строк (первая версия ре-пина писала файлы без сохранения CRLF)
  я выполнял `git checkout --` по ~59 тест-файлам для отката newline-чанга —
  в этот момент были откачены и 4 амендованных B2 cover-тест-файла (asap44/
  round1023/hotfix3/hotfix4). B2 зафиксировал инцидент в своём evidence и
  восстановил аменды самостоятельно (их хеши — финальные, файлы в worktree
  снова M с их дельтой). Моих правок содержимого их файлов НЕТ.
- **related-nonblocking**: `test_summary_deploy_round1026.py` в моих прогонах
  поймал 523→529 pin (каталог) — обновлён моей дельтой (санкция §5); остальной
  файл — B2.
- **unrelated/pre-existing**: 4 identity-падения (tool_loop/nav_disclosure/
  status_control/mca09-registry) + dream_worker-флейк — документированный
  базлайн T-5216; не воспроизводились моей дельтой.

### Что осталось (честно, вне этой лейны)

1. T-5259/T-5260 MiniApp embeddings UI (13J/13K) + 13N#23/#24 — не в
   narrowed write-scope брифа; инварианты покрыты backend-классификацией.
2. 13N#7–14/#19–20/#22/#27 (полный per-chat migration engine: snapshot+delta
   catch-up, promotion/rollback оркестрация, GC/retention, multi-chat
   retrieval fusion) — D12-субстрат (state machine, migration jobs, shadow
   chunks) готов и протестирован; оркестрация верхнего уровня — отдельный
   slice (T-5270 решает, закрывать ли в этой фиче).
3. T-5263 live-ввод ключа — PENDING OWNER (T-5274).
4. T-5270: полный suite + census (ожидаемое Δ: каталог 529, остальные 0)
   + F8 --check (уже зелёный) + F11 re-pin ×1 если routes.py изменится
   (моей дельтой не менялся).

**R17**: plaintext ANU/ключей в коде/тестах/артефактах — 0; значения
ключей нигде не читаются и не логируются (только configured/last4/алиасы).


## B1 — Summary reliability + inspector (lane B1-asap5-summary, T-5244…T-5248 + T-5267)

Дата: 07.10.2026. База: worktree после лендов B2 (SERIALIZE-1 extraction+shim)
и B3. Режим: writer, leaf. Рабочий интерпретатор — `.venv` (aiogram 3.31):
глобальный py (aiogram 3.29 < 3.31) даёт документированные артефакт-падения
rich/cover — при прогонах учтено (см. Прогоны). Cover-зона не тронута
бит-в-бит: `services/cover_prompt_assembly.py`, shim-имена и cover-тесты —
0 правок (проверено: импорт-шилд `summary_generator.py:95` — строка B2).

### Реализовано по задачам

- **T-5245 (L1-семантика, D1)** — трёхуровневый статус в durable
  `summary_run_stages`: `ok` / `degraded_map_fallback` (L1-fail при
  writer-source ON → Writer продолжил от полного окна/fallback package —
  НЕ терминальный исход) / `failed_terminal` (только когда Writer не
  стартовал: empty-payload пути пишут корректирующую append-only строку с
  reason `l1_empty_payload`; существующая empty-семантика run'а — строка 2
  матрицы — сохранена). Витрина: `pipeline_analytics` — coverage-ось
  `result ∈ {ok, degraded_map_fallback, failed_terminal}` (degraded
  определяется фактом «L2-стадия была»), узел L1 — STATE_FALLBACK (⚠) с
  detail «Writer продолжил…» при деградации, красный крест только terminal.
- **T-5246 (таксономия + unusable-gate, D2/D3)** — `FINDING_CODE_TAXONOMY`
  в `summary_l2_review.py`: все 15 FINDING_CODES имеют ровно один класс
  (hard=13: factual/attribution-коды, can_force_legacy=yes; soft=2:
  duplicate_event, major_topic_omitted, can_force_legacy=no). Severity
  решает сервер по коду (`finding_severity`): модельное поле — advisory,
  unknown/мусор от модели класс не меняет, unknown-код — существующий путь
  dropped_invalid, никогда не blocking (в т.ч. anchor-mode
  `_verdict_from_anchor_result`). Unusable-gate: raw `unusable` terminal
  только при (а) ≥2 независимых валидных HARD findings (разные коды И
  разные paragraph targets) или (б) deterministic proof
  (`quote_reason_codes`); иначе даунгрейд до needs_fixes с findings как
  blocking-набором в bounded repair; 0 findings после даунгрейда →
  deterministic-валидный черновик публикуется degraded (не Legacy).
  Даунгрейд фиксируется отдельным stage_event с reason
  `l2_unusable_gate`.
- **T-5247 (stagnation fingerprint + honest final, D4/D5)** —
  count-критерий §50.25 заменён fingerprint-идентичностью hard-finding
  (`code + paragraph + sorted(refs) + target`; target ≡ paragraph_id —
  единственная якорная ось): progress = prev_fps − curr_fps ≠ ∅ (старый
  исправлен, даже при новых находках); стагнация = тот же набор после
  repair ИЛИ документ не изменился (sha256[:16]) → break с трейс-событием
  reason `l2_stagnation_fingerprint`. Бюджеты не растут: MAX_REVISIONS ≤2,
  CALL_BUDGET ≤6 (закреплено тестом); burned-revision исключение
  (escape-hatch full-doc retry) сохранено. Финал bounded-цикла: только
  soft-находки (и нет deterministic hard proof) → degraded publish через
  переиспользованную `_degraded_or_legacy` (reason
  `l2_soft_only_needs_fixes`, metrics `l2_review_degraded_reason` — точная
  причина); остались HARD → Legacy (REASON_L2_REVIEW_REJECTED, INV-1
  fail-closed). Генератор: Writer и Reviewer — раздельные durable-исходы
  (reviewer-rejection НЕ пишет Writer «failed»; l2_review-строка
  фиксировалась только при несуществующем ключе метрики — условие
  исправлено на `l2_review_calls>0`). Honest RU-текст `l2_review_unusable`
  в REASONS_RU (RCA п.7/Incidental 2 закрыт).
- **T-5244 (Decision Trace, D6)** — финальная policy-запись:
  `stage='final_policy'` в существующей `summary_run_stages` (status =
  HYBRID_PUBLISHED | HYBRID_DEGRADED_PUBLISHED | LEGACY_FALLBACK,
  reason_code = точная причина; Δ DDL=0 доказано схемой database.py:927–941)
  во всех точках исхода `_run_hybrid_l2` (publish / degraded publish /
  l2_unusable-Legacy / delivery_failed / hybrid_exception). Витрина:
  `pipeline_analytics._decision_trace` собирает 5 секций §3.1 (L1 / L2
  Writer / Reviewer-итерации / Revision-итерации / Final policy) из
  СУЩЕСТВУЮЩИХ источников — per-attempt stage_events снапшота (≤24,
  R17-safe ключи, исполнительный source: execution_graph_source не тронут)
  + durable stage-строк (переживают рестарт); отдаётся в
  `/api/analytics/pipeline/inspector` ответе как `decision_trace` (0 новых
  эндпоинтов, routes.py не тронут). UI: карточка «Решение по прогону» в Run
  Inspector (index.html, блок Run Inspector — секция B1 по SERIALIZE-2) +
  computed `pipelineDecisionTrace` (app.js); телеметрия mca_events не
  расширена (D6), новые reason-строки живут в stage-строках/логах, словарь
  REASON_CODES = 280 без изменений.
- **T-5267 (focused tests)** — новый `tests/test_asap5_summary_domain.py`
  (19): таксономия 15/15, server-owned severity, unknown→dropped,
  fingerprint-юниты, gate-юниты (независимость/deterministic proof/soft не
  в зачёт), unusable-без-evidence→degraded, даунгрейд→repair→approved,
  2-independent-hard→Legacy, стагнация→break+trace-событие,
  old-fixed+new→progress (rev2), потолок бюджета, soft-only→degraded,
  hard-unresolved→Legacy, outage→degraded, trace 5 секций, L1
  degraded≠terminal, writer-done при reviewer-rejection, honest RU-тексты.
  Плюс JS `tests/js/asap5_decision_trace_test.js` (computed+разметка+R17).
- **T-5248 (live acceptance §5)** — инфраструктура готова (trace+policy
  видны в Inspector для любого прогона, включая safe test-run); сами
  смоук-прогоны на real provider — no-false-acceptance живая приёмка
  владельца (T-5274-стиль, имитация запрещена §5). В evidence live-результатов
  НЕТ — честно помечено как owner-gate, не «пройдено».

### RED-first (артефакт)

1. `tests/test_asap5_summary_domain.py` на старом коде: collection-RED
   (ImportError `FINDING_CODE_TAXONOMY`) → после реализации контрактов
   D2/D3/D4/D5 из 19 тестов 14 цикловых/юнит RED→GREEN (первый прогон
   после реализации: 14 failed / 5 passed при ещё не реализованных
   analytics-частях; финал 19/19).
2. Живое RED-подтверждение смены контракта: канон-тест старого поведения
   `test_unusable_verdict_legacy_immediately` (raw unusable → Legacy) стал
   RED на новой механике и переписан в пару
   `test_unusable_without_evidence_downgraded_not_legacy` +
   `test_unusable_with_two_independent_hard_legacy_immediately` (§16#5+#6).
3. `test_18_reviewer_unusable_still_fail_closed` → superseded
   `test_18_reviewer_unusable_without_evidence_not_terminal` (gate + трейс).

### Обновлённые существующие тесты (санкционированные D1/D3/D5 контракты)

- `test_summary_wave_d_asap4.py` — unusable-пара (выше); остальные тесты
  цикла (budget ceiling, no-improvement, outage, §50.58) зелёные БЕЗ правок:
  fingerprint-механика даёт те же исходы на старых сценариях.
- `test_asap44_l2_review_closure.py` — test_18b (см. выше) + ctx-трейс.
- `test_summary_inspector_zone_g_asap41.py` — L1-ось: fixture «L1 failed +
  L2-событие» → честный `degraded_map_fallback` + узел ⚠ (D1), ось остаётся
  раздельной от source 100%.
- `test_pipeline_analytics_asap4.py` — сценарий B: reviewer-rejection не
  помечает Writer ✕ (D5), отказ несёт узел Проверки; Legacy ⚠ сохранён.

### Прогоны

- Фокус Summary/l1/l2/factcheck/numeric (venv): **1852 passed / 0 failed**
  (`pytest -k "summary or l2_review or l2_writer or l1_ or factcheck or
  numeric"`).
- Смежные точечно: wave_d + asap44-closure + zone_g + pipeline_analytics +
  l2_budget + reviewer_source = 201 passed; asap2-failsoft + cover_round1023
  + publish_integration = 118 passed (на venv).
- JS: **63/63** (62 базовых + новый asap5_decision_trace_test).
- Полный pytest (venv, foreground): **12432 passed / 6 failed / ~7.5 мин**.
  Разбор 6: 4 = документированные pre-existing identity
  (tool_loop / nav_disclosure / status_control / mca09-семейство), из них
  mca09×2 изолированно зелёные (средофлейк полного прогона); 1 =
  `test_mca01_tx_task_supervisor_round1027::test_write_points...` —
  **чужой хвост B3** (пин write-точек: database/graphrag_rebuild/
  embedding_control_plane/dossier_rebuild_jobs/summary_memory — файлы B3,
  мои файлы write-точек не добавляют) → incidental, owning lane B3 /
  integration T-5270 (см. Incidental findings).
- Глобальный py (aiogram 3.29): rich/cover тесты падают артефактом среды
  (документированный прецедент fbdc95c) — канон прогона venv.

### Δ-инварианты (факт по дельте B1)

- **DDL 0** (final_policy = строка существующей таблицы; v33 не растёт).
- **Каталог 523 = 523** (0 ключей), **KS 85 = 85** (0 новых), **тулы 14 = 14**,
  **widget/реестр 0**.
- **reason 280 = 280** (`REASON_CODES` проверен счётчиком; новые строки
  `l2_unusable_gate`/`l2_stagnation_fingerprint`/`l2_soft_only_needs_fixes`
  живут в stage-строках/логах/REASONS_RU-дисплее, словарь mca_events не
  расширялся — SERIALIZE-4 Δ=0 соблюдён).
- **Routes 0 новых эндпоинтов** (routes.py не тронут; трасса — расширение
  существующего ответа inspector); F11 re-pin не требуется от B1.
- **JS 63 ≥ 62**, py — 0 новых red от дельты B1 (разбор выше).
- `settings.py` / `mca_events.py` / `routes.py` / cover-файлы — 0 правок.
- Промпты (`summary_prompts.py`) не тронуты — таксономия полностью
  server-side, модельный severity advisory; канон-пин промптов
  (wave_d::test_reviewer_prompt_canon_discipline) зелёный без правок канона.

### Хеши кандидата (git hash-object, worktree 07.10.2026)

```
416eaeee7525efa0701f41d0d3d54652a32e865d  services/summary_generator.py
4fbb97905a6e13582350a395a1641624c485e13b  services/summary_l2_review.py
c86f08181a335a297b560febdd08f3778c9c872f  services/pipeline_analytics.py
287d8032dd046d11b19b9e4cc73d3f2119f4e557  web/app.js
516c4f145f5c24caa30ce1d16be77b5c67d124b0  web/index.html
e9aa9151542eea7e2fc42a5d0a80068a953b3f53  tests/test_asap5_summary_domain.py
c03d1d7e3a5158485b1485f29de92f53801d2f09  tests/test_asap44_l2_review_closure.py
396df86ffd51c9dec106361af4335b31f8be867c  tests/test_summary_wave_d_asap4.py
1a34d641e2fee7422e26636714bf816919e47cf9  tests/test_summary_inspector_zone_g_asap41.py
4e82e47b0cd0e1f8c10fcb69ce13d4ed7d4ec0c4  tests/test_pipeline_analytics_asap4.py
ecf032bf69cf1d1840dcf77e55ca6671673e13d8  tests/js/asap5_decision_trace_test.js
```
NB: summary_generator/web/app.js/web/index.html содержат также ленды B2/B3
(общие hotspots; секции не пересекались: Run Inspector — B1).

### Incidental findings

1. **related-nonblocking → owning B3/T-5270 (High для интеграционного
   барьера):** `test_mca01_tx_task_supervisor_round1027::
   test_write_points_go_through_single_writer` RED — пин write-точек
   устарел после ленда B3 (found: database 191, graphrag_rebuild 3,
   embedding_control_plane 1, dossier_rebuild_jobs 1, summary_memory 13).
   Файлы — B3-скоуп; фикс = обновить пин с аудитом (не моя дельта: B1
   пишет стадии только через существующий srs.record_stage).
2. **unrelated/pre-existing (среда):** глобальный py (aiogram 3.29) — 5
   артефакт-падений rich/cover (asap2-failsoft/cover_round1023/
   publish_integration); на venv 118/118. Прецедент документирован
   (fbdc95c).
3. **related-nonblocking (RCA §10.1, вне скоупа):** ось «Final text
   coverage» на legacy-путях по-прежнему может показывать 0% — в этом
   slice не трогалось (blurry-зона, отдельное решение).
4. **uncertain/наблюдение:** soft-only degraded publish возвращает
   `usable=True` — consumer'ы l2_result (paged-путь, summary_test) видят
   ok-документ с `l2_review_degraded=1` в metrics; health/policy помечают
   деградацию честно (проверено тестами). Риск-инцидентов не выявлено.

### Что осталось (честно, вне этой лейны)

1. T-5248 live-смоуки на real provider — owner no-false-acceptance
   (T-5274-стиль); инфраструктура трассы/policy готова.
2. Visual QA §15A–15F карточки трассы (Playwright/Browser Use) — T-5266
   (parent); B1 выполнил JS-harness проверку computed+разметки.
3. mca01 write-points пин — B3/T-5270 (incidental 1).

**R17**: секретов в дельте нет (коды/числа/id; логи R17-safe; чат-ID в
тестах — фиктивные -1001/-100267, прецедент wave_d).
