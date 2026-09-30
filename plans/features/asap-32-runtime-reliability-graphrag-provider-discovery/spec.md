# `asap-32-runtime-reliability-graphrag-provider-discovery` — spec.md (Step 2 @Architect)

> **Фича:** `asap-32-runtime-reliability-graphrag-provider-discovery` (ASAP-3.2, corrective consolidation).
> **Статус:** Proposed → Accepted (блок A GraphRAG-зона закрыта решениями ADR-1028-5 D1–D3).
> **Автор:** @Architect (только docs; код не пишет).
> **Baseline:** прод **2.58.39** (HEAD `c0e0362`), SQLite DDL **v19** (v20-бронь `mca-04b` — не занимать), каталог 488/427/463/105/103/21.
> **Источник ТЗ:** `plans/current_task.md` 12025–15302 (§0–§135), SHA-256 `E828A092EC47AAEF8C1B470B3FC1C07B3ADF98D2CBBF07E8F8D08D3D34B6750A` — не изменялся.
> **Скоуп этого документа:** зона 1 — GraphRAG lifecycle (T-4190…T-4194, T-4230, T-4235; RCA-вопросы §86 Q6–Q9, Q14). Зона 2 (image runtime, вопросы Q1–Q5) закрывается секцией T-4195 этого же спека; зона 3 — Text Capacity Resolver; зона 4 — Summary semantic integrity (Q10/Q14, T-4205…T-4209); зона 5 — Direct tool-path fallback recompose (Q11, T-4210…T-4212) — секциями этого же спека + решениями D4–D10 ADR-1028-5; зона 6 — Decision полностью LLM-driven (Q12, T-4213…T-4214, D11); зона 7 — Analytics actual snapshot + GraphRAG health + log severity (Q13, T-4215…T-4217, D12–D13); зона 8 — EXTRA corrective audit (PgDatabase-vs-asyncpg.Pool контракт, seed, UI redesign, Browser E2E, §92–§134 ТЗ) + финальные DoD/acceptance/санкции — D14. Q1 верифицирован частично кодом (`services/image_generation.py:1008,1088` — standalone path читает `IMAGE_REQUEST_TIMEOUT_SECONDS`; полные ответы Q1–Q5 см. в секции T-4195).
> **ADR:** `adr-1028-5-runtime-reliability.md` (D1–D3 — GraphRAG; D4–D7 — media/capacity; D8–D10 — Summary/Direct; D11 — Decision LLM-driven; D12–D13 — Analytics actual snapshot + GraphRAG health/log severity; D14 — EXTRA corrective).

---

## 1. RCA: почему вечный `building → FTS-only` (§2–§3 ТЗ, Q6)

Production-симптом:

```text
SmartModule: embedding generation not serviceable
index=graph_facts_vec
status=building
gen_fp=... new_fp=...
— FTS-only
```

`gen_fp == new_fp` — fingerprint зарегистрированного generation совпадает с текущим конфигом. Проблема — lifecycle-статус, НЕ mismatch модели.

**Код (2.58.39, подтверждено чтением `services/summary_memory.py`):**

1. **Карантин на регистрации** — `_init_vec_tables` (:1334–1368) решает «векторы построены текущим конфигом» ТОЛЬКО как `activate=(not vec_preexisting) or dim_mismatch or schema_rebuilt`. `_vec_tables_preexisting` (:1426–1439) — консервативно True для персистентных таблиц неизвестного происхождения. Итог: при плановом рестарте production-БД generation регистрируется `activate=False` → **`building`** (MCA-07 D4/B-MCA07-1 — карантин «до mca-04b»).
2. **Дедупlication не имеет выхода** — `_register_index_generations` (L-MCA07-1, :1466–1473) по `get_generation_by_fingerprint` НЕ заводит дубли `building` при повторных стартах → одна и та же строка остаётся `building` навсегда; поэтому `gen_fp == new_fp`.
3. **Нет пути завершения lifecycle** — backfill (:1796–1895; батчи `_BACKFILL_BATCH=50`, потолок `_BACKFILL_MAX_FACTS=500` фактов/вызов) только досыпает отсутствующие vec-rows и НЕ re-embed'ит существующие rows под current fingerprint; в коде нет перехода `building → validated → active`. «Backfill missing rows finished» ≠ «индекс построен текущим конфигом» (§3 ТЗ).
4. **Gate чтения** — `_index_generation_ok` (:1488–1523) разрешает vector KNN ТОЛЬКО `status=='active' AND fingerprint==current`; иначе FTS-only (безопасный fail-soft, но застрявший навсегда).

**Root cause (одно предложение):** инициализационная policy корректно НЕ доверяет preexisting vec-таблицам, НО при этом в системе отсутствует любой механизм доказать происхождение/покрытие векторов и перевести generation в `active` — backfill не является rebuild и не меняет статус, поэтому `building` — терминальное состояние, а FTS-only — вечный режим.

**Производный дефект — спам лога (§8):** `_index_generation_ok` пишет `embedding generation not serviceable` (WARNING + emit_stage_event) на КАЖДУЮ проверку индекса — «новая авария» каждый RAG-вызов при одном и том же состоянии (рис. T-4192).

**Доля векторов с current verified embeddings (Q7):** на 2.58.39 не измерима честно — vec-rows не несут per-row provenance (только реестр поколений v18 `mca_embedding_index_generations` и `embedding_cache.identity_fingerprint` по text-hash). Обоснованная оценка = UPPER BOUND «в embedding_cache есть строки с current identity»; REAL coverage появляется только после полного re-embed/rebuild под текущим fingerprint (сделать перестройку измеримой — часть решения D1). Числитель/знаменатель для health: `eligible graph_facts имеющие.vec-row поколения с provenance==current / все eligible graph_facts`.

## 2. Решение: восстановление lifecycle (§4–§6 ТЗ, Q8 → ADR-1028-5 D1)

Целевой lifecycle:

```text
UNKNOWN/PERSISTED OLD INDEX → BUILDING → FULL REBUILD UNDER CURRENT FINGERPRINT
→ VALIDATE → ATOMIC ACTIVATE → ACTIVE
   (ошибка → FAILED / building+reason; FTS остаётся serviceable)
```

- **Вариант A (shadow generation, ADR D1 — принят):** под текущим fingerprint строится shadow vec-хранилище (полный re-embed всех eligible facts), валидация, атомарный swap/activation. Преимущества: raw `graph_facts`/`smart_archive_facts` не трогаются; в течение rebuild старое RAW/FTS обслуживание не деградирует; per-row provenance становится доступным; отмена/повтор безопасны.
- **Вариант B (controlled destructive vec rebuild)** — резерв: разрешён ТОЛЬКО если sqlite-vec не позволяет generation-separated shadow без чрезмерной сложности; тем не менее raw facts — source of truth, НЕ удалять; полная валидация перед activate. Решение A — в ADR D1.
- **ЗАПРЕЩЕНО (§3/§66 / tasks.md Инварианты):** `UPDATE … SET status='active'` без проверки происхождения ВСЕХ vectors; пометка `building → active` «для тишины».
- Activation criteria (§6) — см. §4 ниже.

## 3. Resumable rebuild (§7/§64 ТЗ → ADR-1028-5 D2)

- Полный rebuild, НЕ fill-missing; existing vec-rows НЕ trusted для generation без доказанной связи с fingerprint.
- REUSE durable `task_jobs`; state `queued/running/checkpoint/validated/activated/failed`; checkpoint → resume после restart.
- НЕ блокировать startup/polling на часы; фоновое выполнение с ограничениями (§64): bounded batches, sleep/yield, равномерный прогресс, rate-limit embedding-вызовов, pause/resume/cancel.
- `embedding_cache` с current identity позволяет re-embed без повторных платных API-вызовов для неизменённых конфигов (деталь реализации — Builder, T-4191).
- Тесты §70: restart mid-build → resume; смена конфига mid-build → старый build НЕ активируется как current; failed build → FTS остаётся serviceable.

## 4. Activation criteria + логи + severity (§6/§8/§9 ТЗ → ADR-1028-5 D3)

Generation `active` ТОЛЬКО при всех условиях:

1. fingerprint == current;
2. embedding dimension == current;
3. provider/model identity соответствует текущему config;
4. preprocessing_version соответствует;
5. все eligible source facts имеют vector row ИЛИ явно классифицированную допустимую причину отсутствия;
6. нет orphan vectors;
7. count/coverage validation прошла;
8. sample KNN smoke прошёл;
9. transaction/swap завершён.

Логи: `EMBEDDING_GENERATION_BUILD_START / PROGRESS / VALIDATED / ACTIVATED` (§6).

Severity (§8): BUILDING — ожидаемое состояние, НЕ аварийный WARNING на каждый RAG-вызов: первый WARNING → далее rate-limit/coalesce; обычные запросы → DEBUG/INFO; повторный WARNING — только при meaningful state change / cooldown; отдельный health «Индекс перестраивается» (§9, человекочитаемый — T-4216).

## 5. Typed reranker contract (§10–§12 ТЗ)

- Второй warning `rerank(typed) invalid — bounded fallback` НЕ связан с vec `building`: это вторая дефектная линия (parser). Flow: retrieval candidates → LLM reranker → parser; prompt «верни только номера через запятую; если ничего нет — 0»; typed parser invalid ⇔ ответ непустой и не содержит корректных candidate numbers; fail-soft сохраняет top-K pre-rerank (production `kept=8/10`) — запрос не падает, но reranking фактически не сработал.
- Исправление (§11):
  1. provider-capability aware structured contract — при поддержке structured output/JSON schema: `{"selected":[1,4,7]}` / `{"selected":[]}`;
  2. при отсутствии structured: компактный strict prompt + robust parser legacy numeric + acceptance ТОЛЬКО candidate IDs в диапазоне; детерминированный repair (markdown fences / короткий префикс) допустим локально;
  3. НЕ делать второй дорогой LLM call ради formatting, если смысл извлекаем локально;
  4. bounded fallback остаётся последним fail-soft.
- FTS остаётся резервом ПОСЛЕ active vector (§62): KNN failure → FTS fallback; механику не удалять.
- Observability (§12): candidate_count, selected_count, parser status, provider/model, latency, response_format mode, fallback used; метрика `rerank_invalid_rate` — post-deploy высокий invalid rate = regression, НЕ expected normal state. НЕ логировать приватные raw facts (reproduction — на synthetic candidates, Q9).

## 6. Ответы на вопросы Architect §86 (зона 1)

| Q | Ответ |
|---|---|
| **Q6** | Почему вечный `building`: см. §1 RCA. Коротко: preexisting vec-таблицы → `activate=False` (`vec_preexisting`), L-MCA07-1 не плодит дубли → одна строка `building`; backfill не является rebuild и не меняет статус; в коде вообще нет перехода building→validated→active; gate (`_index_generation_ok`) пропускает vector KNN только при `active`+совпадающем fingerprint → вечный FTS-only. Смена модели не при чём: `gen_fp==new_fp`. |
| **Q7** | На 2.58.39 не измерима: vec-rows не несут per-row provenance; реестр поколений (v18) — per-index, `embedding_cache.identity_fingerprint` — per-text-hash (upper bound). Real coverage считается только после rebuild D1: `eligible facts с vec-row provenance==current / eligible facts` (+ классифицированные допустимые причины отсутствия). |
| **Q8** | Вариант A shadow generation (полный re-embed под current fingerprint в отдельное generation-хранилище) → validate (9 критериев §4) → атомарное activation; raw facts не удалять; ADR D1. Вариант B — резерв при невозможности shadow без чрезмерной сложности; `UPDATE … SET active` запрещён. |
| **Q9** | Не логировать raw private facts; воспроизвести на synthetic candidates (T-4228/T-4193): expected inputs — числовой strip/fence-wrapped numeric/JSON-обёртки/проза/пустой ответ; подтверждённый prod-факт — непустой ответ без корректных candidate numbers → invalid + bounded fallback `kept=8/10`. Что именно LLM вернул в прод — фиксируется observability §12 (parser status + response_format mode, без тела фактов) после deploy. |
| **Q14** | GraphRAG-зона БЕЗ нового schema bump: shadow generation-хранилище — идемпотентное `CREATE VIRTUAL TABLE IF NOT EXISTS` (прецедент EXTRA/Фази B, без bump user_version; v19 остаётся, v20-бронь `mca-04b` не нарушена); полная валидация/статусы — в существующей v18-структуре `mca_embedding_index_generations` (аддитивные опциональные колонки по образцу `endpoint_fingerprint`/`identity_fingerprint`); per-row provenance достижим теневым маркером внутри shadow-таблицы, колонка в RAW `graph_facts` НЕ нужна. Resumable state — REUSE `task_jobs` (DDL не требуется). Итог: Δ SQLite DDL = 0 (идемпотентные CREATE); иначе — только через T-4242/Q14-санкцию. |
| Q1–Q5 | Зона 2 image runtime (T-4195, секция media-adapter этого спека) — вне скоупа GraphRAG-зоны; полные ответы фиксируются при консолидации T-4195. Частичный факт Q1 из кода: standalone/tool branch читает `IMAGE_REQUEST_TIMEOUT_SECONDS` в `services/image_generation.py:1008,1088` (90 s). |

---

## 7. Инварианты / запреты (зона 1)

- §66/§3: запрещены `UPDATE … SET status='active'` без provenance-проверки и маскировка `building` под active «для тишины».
- Raw `graph_facts` и `smart_archive_facts` — source of truth; vec-таблицы перестраиваются, raw НЕ удалять (R18).
- FTS fail-soft остаётся serviceable на всём протяжении rebuild и после (KNN failure → FTS fallback — не удалять механику).
- Failure → FAILED/building+reason, состояние видна в health (§9), НЕ спам-лог (§8).
- §85: долгий background rebuild НЕ блокирует roadmap после доказательства durable/resumable/FTS-fail-soft/progress/no-corruption; auto-activation после completion — реализовать и проверить на fixture/smaller prod slice (T-4235).

---

# Зона 2: Media Adapter + adaptive policy (T-4195…T-4201, §13–§36, Q1–Q5)

## 2.1 RCA: почему 90с статик (Q1, §13–§14, §22, §32)

Production-симптом: `qwen-image-3-pro > 90s` автоматическиClassifier как failed, хотя remote generation жива (завершается на 90–180+ с).

**Код 2.58.39 — «три независимых истины» подтверждены:**

1. **Standalone/tool + Summary Base Cover:** `services/image_generation.py:1008,1088` — одна попытка = `IMAGE_REQUEST_TIMEOUT_SECONDS` (default **90 s**); Summary Cover идёт через тот же `generate_image_verbose` (`services/summary_generator.py:1275`) → наследует 90-с окно (или `IMAGE_ATTEMPT_TIMEOUT_SECONDS` default **180 s**, cap 600, retry до 2 попыток — hotfix-5).
2. **Cover Style Edit:** `services/cover_style_edit.py:64` — `COVER_STYLE_EDIT_TIMEOUT_SECONDS` default **240 s** clamp [30,900] — отдельное env-only окно (§69 EXTRA), не связанное с 90/180.
3. **Механизм = arbitrary wall-clock hard timeout** (`httpx.AsyncClient(timeout=...)`), т.е. первый и единственный механизм определения «модель умерла» — соединение рвётся по计时, а не по состоянию job (нарушение порядка §13: hard timeout должен быть последним рубежом).

**Root cause:** все image branches решают «generation умерла» ТРЕМЯ независимыми env-числами (90/180/240) по wall-clock, тогда как решение §13 требует начинать с реального состояния job/status/streaming; существующий async-механизм (`COVER_STYLE_ASYNC_STATUS_URL` poll, `services/cover_style_edit.py:290–319`) есть только у Cover Style и настроен как env-маршруты вручную, а не как обнаруженная capability — core pipeline не имеет provider-agnostic contract, поэтому «жить дольше 90 с» для standalone невозможно по конструкции.

**Honesty-ограничение (§14):** sync POST без job ID/status/streaming нельзя «пинговать» магически — можно знать только, что соединение не оборвалось; capability фиксируется как `remote_progress = job_status | streaming | none`, fake ping запрещён.

## 2.2 Media Adapter — provider-agnostic contract (§15–§18, §20–§21)

Единый `ImageProviderAdapter` (концепт — §15; финальная сигнатура — Builder T-4196): `discover_models() / discover_capabilities(model) / submit_generation / submit_edit / supports_async_job / supports_status / supports_stream / supports_cancel / get_status(job_id) / get_result(job_id) / cancel(job_id)`. Core pipeline НЕ привязан к NanoGPT route names.

- **NanoGPT (§16, основной provider):** OpenAI-compatible image generation/edit endpoints + image model catalog (`/api/v1/image-models?detailed=true`, `/api/v1/images/models/{model}/endpoints` — уже используются `image_capabilities.py`, это единственные маршруты, подтверждённые кодом). **Точная async-верификация обязательна до coding (T-4195):** exact async submit shape, происхождение job/task/request ID, exact status route, terminal statuses, recovery после reconnect, cancel, capability fields — проверять РЕАЛЬНЫЙ deployed endpoint используемым ключом; **не изобретать `task_id` route по аналогии**. Если async/status подтверждён — PRIMARY execution mode для slow generations. Сейчас env-шаблоны `COVER_STYLE_ASYNC_*` — migration evidence, не целевой contract.
- **OpenRouter (§17):** unified image API + programmatic capability metadata (endpoint-specific); НЕ hardcode reference counts/resolutions по имени; streaming preview/progress — liveness/progress source, где реально поддерживается; иначе sync/adaptive path.
- **Другие providers (§18):** Replicate-style prediction jobs, fal-queue, OpenAI-compatible sync, local ComfyUI — НЕ реализовывать все сейчас; нужен generic adapter interface + adapters для текущих connections + **безопасный generic sync fallback**.
- **Shared (§20):** connection identity, cache/invalidation, provider detection, diagnostics — общие с text-capacity framework (зона 3), но без одного класса-монолита.
- **Исправить `image_capabilities.py` (§21, Q4):** discovery вызывается автоматически (не только при переданном готовом dict); NanoGPT catalog реально fetch'ится; OpenRouter `supported_parameters.input_references` и endpoint-level capabilities parse'ятся по РЕАЛЬНОЙ schema; async/status capability НЕ выводится из несвязанных полей; **unknown остаётся честным unknown**; cache invalidates при model/base URL/connection change (сейчас TTL 900 s — `_DEFAULT_TTL_SECONDS`, ключ обязательно включает model+base_url).

## 2.3 Adaptive Media Execution Policy (§22–§28)

- **Один resolver для ВСЕХ image ops (§22):** standalone/tool, Summary Base Cover, Cover Style Edit, Cover Style Preview, будущие; «standalone=90 / summary=180 / style=240» как три независимые истины — ликвидировать.
- **Stage-aware (§23):** key `provider + model + operation` (генерация ≠ редактирование имеют разные latency distributions) — НЕ один общий timeout.
- **Inactivity vs total (§28):** различать connect timeout / read-inactivity timeout / poll request timeout / **total generation deadline**. При remote job/status deadline — safety ceiling, НЕ inactivity timeout: пока provider публикует `queued/starting/running/processing` — job жив; получение RUNNING/progress обновляет liveness; НЕ завершать живую generation потому что с submit прошло 90 с (§24). Provider-опубликованный maximum execution time учитывается.
- **Sync-only (§25):** adaptive deadline по observed successful latency (p50/p90/p95/p99/max-bounded, timeout/failure counts, per operation/provider/model). Формула-кандидат: `clamp(max(cold_default, p95×safety_factor), min_deadline, hard_safety_ceiling)` — окончательная формула = решение Architect после анализа реальных данных.
- **Estimator не обучается на timeout'ах как на success (§26):** timeout→растущий deadline→новый timeout — запрещённая петля; estimator строится по successful durations, timeout/failures — отдельные reliability signals.
- **Cold-start defaults (§27):** developer-level (не UI knobs, не final hard truth); 90/180/240 — migration evidence, пересмотреть при migrate.
- **Honest `remote_progress = job_status | streaming | none` (§14)** — без fake ping.

## 2.4 Durable media state, restart recovery, fallback (§29–§31)

- **Durable state (§29):** standalone image generation, живущая минуты, получает durable job на REUSE `task_jobs`; минимум полей: operation, provider, model, provider_job_id, status, submitted_at, last_progress_at, deadline_at, attempt, result asset, failure reason.
- **Restart recovery (§30):** известен provider job ID → **resume polling**, а НЕ повторный платный submit; sync-only без recovery → честно `unknown_after_disconnect`; автоматический платный retry без policy/idempotency-понимания — запрещён.
- **Image fallback (§31):** terminal primary failure → fallback provider/model; capability/deadline пересчитывается под fallback; prompt/input recompile под fallback capabilities. **НЕ переключаться на fallback, пока primary честно RUNNING.**

## 2.5 Регрессии + observability (§32–§36)

- §32: `qwen-image-3-pro >90s` перестаёт считаться failed при живой generation — acceptance: реальные 90–180+ с генерации завершаются успешно. §33: Base Cover first-class, happy path не ухудшать. §34: EXTRA ladder сохраняется (style optional → style failed→base cover → base failed→Rich without cover → Rich failed→sendMessage; counter/assets/provenance не ломать); async execution интегрируется через общий adapter, НЕ bespoke env-only route templates.
- §35 events: `MEDIA_JOB_SUBMITTED/PROGRESS/HEARTBEAT/SUCCEEDED/FAILED/DEADLINE_EXCEEDED/RECOVERED/FALLBACK`; safe fields: operation, provider, model, elapsed, remote status, job-id hash/opaque safe id, adaptive deadline, policy source; **НЕ логировать keys/prompts/image bytes**. §36 Miniapp: режим выполнения (async status/streaming/sync), среднее время, P95, статус; «90 seconds» как user input — убрать.

## 2.6 Ответы Q1–Q5 (§86, зона 2)

| Q | Ответ |
|---|---|
| **Q1** | Ветви и их окна (код 2.58.39): standalone/tool image (`image_generation.py:1008,1088`) = `IMAGE_REQUEST_TIMEOUT_SECONDS` default 90; attempt-level retry = `IMAGE_ATTEMPT_TIMEOUT_SECONDS` default 180 (cap 600); Summary Base Cover наследует те же `generate_image`/`generate_image_verbose` окна (`summary_generator.py:1275`); Cover Style Edit = `COVER_STYLE_EDIT_TIMEOUT_SECONDS` default 240 clamp[30,900] (`cover_style_edit.py:64`). Три независимые env-истины; все три — wall-clock hard timeout как ПЕРВЫЙ механизм смерти. |
| **Q2** | Состояние кода: async/status есть ТОЛЬКО у Cover Style через env-шаблоны `COVER_STYLE_ASYNC_*` (`cover_style_edit.py:290–344`, submit→task_id→poll) — т.е. contract настраивается вручную и не обнаруживается capability'ю. Какие providers из current connections реально дают job/status/streaming — подлежит live-верификации (§16/§91): для NanoGPT — официальные materials говорят sync/async режимы и OpenAI-compatible endpoints; любые route names фиксируются ТОЛЬКО после проверки реального endpoint ключом. sync-only без статуса — честный `remote_progress = none`. |
| **Q3** | Определяется T-4195 check-list'ом (PAT): exact catalog route (start: `/api/v1/image-models?detailed=true` — уже потребляется кодом); async submit shape; job/task/request ID источник; exact status route; terminal statuses; recovery после reconnect; cancel; capability fields. Правило: НЕ изобретать `task_id` route по аналогии; подтверждённый async/status для текущей image model → PRIMARY execution mode; неподтверждённый → sync/adaptive path честно. |
| **Q4** | `image_capabilities.py` держит реальный catálogo NanoGPT (`image-models?detailed` + endpoints) и TTL 900 s, НО: (1) discovery срабатывает надёжно только если caller передаёт готовые данные/явно триггерит — automatic live discovery на каждом изменении model/connection не гарантирован; (2) endpoint-level/async-status capability может наследиться из полей, семантически с ним не связанных; (3) unknown не всегда остаётся честным unknown; (4) invalidation не привязана полно к model/base URL/connection change. fixes — §2.2, Builder T-4196. |
| **Q5** | Через ОДИН resolver `MediaExecutionPolicy` с key `provider+model+operation` на всех ops (§2.3): deliverable'ы — единый adapter contract (T-4196), единая policy (T-4197), durable `task_jobs`+recovery+fallback (T-4198), применить к standalone/Base Cover/Style Edit/Preview (T-4199), регресс-гейты §32–§34 (Base Cover happy path, EXTRA ladder, counter/provenance) + тесты §68 A–F. Async через adapter, а НЕ env-templates. |

# Зона 3: Text Capacity Resolver (T-4202–T-4204, §19–§20, §53–§57)

## 3.1 Adapters

- **NanoGPT (§53):** provider adapter вместо постоянного registry guess; резолв `provider/base_url/model → context window → max output (if available) → capability source`; live/public catalog schema проверять; catalog недоступен → registry/fallback, но Analytics честно показывает source.
- **Direct DeepSeek (§54):** отдельный adapter/identity (не generic host); если нет machine-readable context catalog → verified official registry entry с source=`verified_registry`, НЕ `provider_catalog` (не выдавать registry за runtime discovery).
- **OpenRouter (§55):** проверить text capacity discovery, image capability discovery, endpoint-specific capability, cache invalidation; существующий adapter не сломать.
- **Unknown provider (§56):** НЕ угадывать из URL; лестница: standard discovery endpoints (если реально отвечают) → provider plugin → verified registry → developer override → conservative fallback; UI показывает fallback status.
- **Local runtime (§19):** llama.cpp / Ollama / vLLM сохранить.
- **Framework (§20):** `ProviderDiscoveryRegistry` (TextCapacityAdapter / ImageCapabilityAdapter / MediaExecutionAdapter) с shared connection identity, cache/invalidation, provider detection, diagnostics — без одного монолитного класса.

## 3.2 Discovery timeout / caching (§57)

Metadata fetch короткий (не задерживает каждый user request); cache с invalidation по connection/model change; provider discovery failure НЕ блокирует normal generation (fallback capacity + honest source); повторные попытки — async, не в hot path.

## 3.3 Invariants (зоны 2–3)

- No fake ping (§14); hard timeout — не первый механизм строки жизни (§13).
- НЕ обучать deadline на timeout'ах (§26); НЕ делать автоматический платный retry/re-submit после рестарта при известном job ID (§30).
- unknown остаётся unknown (§21/§56); registry никогда не маскируется как `provider_catalog` (§54).
- Δ SQLite DDL = 0 при reuse `task_jobs` (поля §29 — существующая generic-структура; любая новая потребность DDL — через T-4242/ADR-waiver по образцу Q14 зоны 1).

---

# Зона 4: Summary semantic integrity (T-4205…T-4209, §1.4–§1.5, §37–§43, Q10/Q14)

## 4.1 RCA: почему FactPackage destructive shrinking при coverage_policy=exhaustive — skipped_fragments=267/354 (Q10)

Production-симптом (§1.4 ТЗ): `FACT_PACKAGE_TRUNCATED | skipped_fragments=267 | skipped_threads=…` при 354 fragments входа — при том, что L1 честно отработал `exhaustive/chunk_all` (все fragments ДОШЛИ до L2).

**Код 2.58.39 (подтверждено чтением `services/summary_fact_package.py`):**

1. **L1 не виноват:** exhaustive/chunk_all поставляет полный набор fragments (§37 «Configured Summary window = FULL source set» — L1 идёт в правильном направлении).
2. **L2-пакетирование режет позиционно, а не семантически:**
   - `_apply_fragment_caps` (:410–424) — hard-лимиты `MAX_FRAGMENTS_PER_THREAD`/`MAX_FRAGMENTS_TOTAL`: fragment'ы сверх лимита выбрасываются ПО ПОРЯДКУ, без оценки уникальности содержания;
   - `_enforce_budget` (:456–539) — деструктивный каскад: (1) fragments вытесняются «самый старый первым» по `(timestamp, message_id)` (:484–499); (2) `description → ""` (:501–508); (3) целые темы `pop(0)` — самая старая первой (:510–514); (4) chronology последней темы обрезается старые-первыми (:516–533). Селекторы — позиционные идентификаторы, семантическая идентичность fragment'а (уникальный факт/участник/событие/тема) нигде не учитывается;
   - результат — `skipped_ids` → `status=STATUS_TRUNCATED` + WARN `FACT_PACKAGE_TRUNCATED` (:921–931) — это штатный, а не аварийный path.
3. **Смысл бюджета искажён:** L2 budget (`_resolve_budget` :231 → `kind/limit`) — размер ОДНОГО call'а, но код трактует его как разрешение потерять semantic content (§38 ТЗ): вместо уменьшения ОДИНОКОГО пакета система молча выбрасывает 267/354 fragment'ов.

**Root cause (одно предложение):** L2-стадия FactPackage решает «не влезает в один call» деструктивным позиционным усечением (caps + budget-каскад по timestamp), потому что в пайплайне отсутствует стадия семантической редукции (stable-ID merge → dedupe → subpackages → intermediate reduction), и бюджет одного L2-запроса ошибочно наделён полномочием терять уникальный контент.

**Дефект-производные:** (а) `_apply_fragment_caps` режет даже при пустом лимите бюджета — «limit budget» и «количество fragments» смешаны; (б) skipped списки считаются, но coverage-metrics (before/after unique items, merged duplicates, reduction passes) отсутствуют — деградация невидима метрикой (§41); (в) L1_FALLBACK-ветка (`_fallback_package` :810–890) дублирует тот же деструктивный каскад.

## 4.2 Решение: hierarchical semantic reduction (§37–§40 → ADR-1028-5 D8)

- **§37:** Configured Summary window = FULL source set. После L1 semantic destructive truncation УБИРАЕТСЯ: L1 output целиком — вход редукции.
- **§38:** FactPackage НЕ tail-truncate'ится; normal path больше не выдаёт `FACT_PACKAGE_TRUNCATED skipped_fragments=267` при уникальной информации в этих fragments. Budget L2 — размер одного call, НЕ разрешение потерять semantic content: при несоответствии бюджету запускается редукция, а не выбрасывание.
- **§39 pipeline (D8):**

```text
all L1 outputs
→ stable-ID merge
→ topic dedupe
→ semantic subpackages
→ intermediate reduction
→ merge reduced subpackages
→ final L2 package
```

Все unique topics должны остаться представлены. Финальный пакет НЕ обязан влезать в один call без редукции — но редукция сжимает дубликаты, а не выбрасывает уникальность; при невозможности уложиться в один L2-бюджет без потери — сегментация L2-вызова (chained/paged L2), НИКОГДА silent drop.
- **§40 правила сжатия — МОЖНО сжимать:** повторяющиеся fragments; duplicate evidence; одну тему, повторённую в нескольких chunks; verbose description; repeated chronology wording. **НЕЛЬЗЯ silently выбрасывать:** уникальный факт; уникального участника; уникальное событие; уникальную тему.
- `_apply_fragment_caps`/`_enforce_budget` переезжают с позиционного отбрасывания на семантическое: позиционные каскады остаются ТОЛЬКО как fail-soft последней линии — и при срабатывании обязаны быть видны coverage-metrics (§4.3), а не проходить как норма.

## 4.3 Coverage metrics + oversized segmentation + empty-guard (§41–§43 → ADR-1028-5 D9)

- **§41 Semantic coverage metrics (обязательные):** unique semantic items before; after; merged duplicates; unique dropped; reduction passes. **Normal: `unique_dropped = 0`.** Метрики попадают в события/Analytics (T-4215/T-4216) как числа (R17-safe, без raw content); `unique_dropped > 0` в normal path = regression, а не success.
- **§42 Oversized single message — lossless segmentation:** если одно source message само больше одного L1 request budget — lossless segment: сохраняются original message_id; part index; author; timestamp; reply relation; text parts. Merge знает, что это одно исходное сообщение (reassembly в merge-стадии D8; дубликаты между частями — merge, НЕ потеря).
- **§43 Empty-summary guard ASAP-3.1 СОХРАНЯЕТСЯ (hotfix не откатывать):** инвариант

```text
source > 0 AND semantic package empty → Hybrid invalid → recovery/Legacy
```

Никогда не публиковать article «про пустой пакет». Существующий EMPTY-PACKAGE GUARD (`_emit_near_empty_package` :433–453, §127/§128 degraded-события) — не трогать; новые редукционные стадии обязаны сохранять эту семантику.

## 4.4 Ответ Q10/Q14 (§86, зона 4)

| Q | Ответ |
|---|---|
| **Q10** | См. §4.1: L1 exhaustive отдаёт все fragments, но L2-пакетирование (`services/summary_fact_package.py`: `_apply_fragment_caps` :410–424 + `_enforce_budget` :456–539) режет позиционно «старые первыми» под per-call budget — 267/354 в проде выброшены каскадом caps/budget без какой-либо семантической идентичности; `STATUS_TRUNCATED` — штатный код path. Решение — D8/D9 (hierarchical semantic reduction, coverage metrics `unique_dropped=0`, lossless segmentation §42). |
| **Q14** | Δ SQLite DDL = 0: coverage-metrics/reduction passes — runtime-метрики (события/логи/Analytics snapshot), segmented parts — in-memory структуры внутри одного run FactPackage; пер-пакетные счётчики — в существующих runtime-структурах. Никаких новых таблиц; v20-бронь `mca-04b` не нарушается. |

## 4.5 Invariants (зона 4)

- Budget L2 = размер одного call, НЕ разрешение терять semantic content (§38); silent drop уникального контента запрещён (§40).
- `unique_dropped = 0` — норма; любое срабатывание позиционного fail-soft каскада — видимое degraded-событие (§41/§127-образное).
- Oversized message → lossless segmentation с полным набором полей (§42) — НИКОГДА не «обрезать до лимита».
- Empty-summary guard ASAP-3.1 (§43) неприкосновенен: source>0 ∧ package empty → Hybrid invalid → recovery/Legacy.
- Summary default path остаётся первой линией (§0 baseline: exhaustive/chunked L1 — не переписывать, достроить редукцию после).

---

# Зона 5: Direct tool-path fallback recompose (T-4210…T-4212, §1.6, §44–§46, Q11)

## 5.1 RCA: почему fallback recompose не проходит через tool-enabled `generate_chat` (Q11)

Production-симптом (§1.6 ТЗ): production branch с tool_router при срабатывании фоллбэка отправляет fallback-модели (меньшее окно, напр. 32K) payload, собранный под primary window (напр. 1M) → provider 400/context overflow.

**Код 2.58.39 (подтверждено):**

1. **`generate()` — recompose ЕСТЬ:** `services/llm_client.py:953–959` — параметр `fallback_payload_adapter` (ASAP-3.1, ADR-1028-3 §14/§42); при LLMError primary и активном фоллбэке adapter вызывается ровно один раз ДО отправки (:1003–1012).
2. **`generate_chat()` — recompose НЕТ:** `services/llm_client.py:1149–1269` — параметра не существует; при LLMError primary (:1182–1194) тот же `payload` (включая `tools`/`tool_choice`, собранные под primary) уходит в `_fallback_with_retries(payload)` БЕЗ пересборки.
3. **Direct service — асимметрия веток:** `services/direct_chat_service.py:1942–1963` — ветка `tool_router is not None` вызывает `chat_with_tools` (→ `services/tool_loop.py:225`, внутренний `llm.generate_chat` :278) БЕЗ какого-либо recompose; adapter передаётся ТОЛЬКО в plain-ветке `generate` (:1956–1963). Итог: основной production-путь Direct (tools включены) — именно тот, где recompose отсутствует.
4. **Tool schemas невидимы бюджету:** payload `generate_chat` включает `tools` + `tool_choice` (:1172–1174) — при recompose они обязательная часть mandatory payload (§45: system + persona + tool schemas + tool state + messages), а не только message text; любой recompose обязан их считать в бюджет fallback-окна.

**Root cause (одно предложение):** механизм `fallback_payload_adapter` реализован только в legacy `generate()` (ASAP-3.1), а tool-enabled путь (`chat_with_tools` → `generate_chat` → tool loop) и retry/direct-response ветки выполняют фоллбэк на том же primary-размерном payload, потому что `generate_chat` не имеет adapter-параметра и его mandatory payload (tools/tool_choice/tool state) не участвует ни в каком пересчёте бюджета.

## 5.2 Решение: recompose на ВСЕХ Direct execution paths (§44–§46 → ADR-1028-5 D10)

- **§44 контракт (обязателен на каждом пути):**

```text
primary payload
→ primary failure
→ resolve fallback capacity
→ RECOMPOSE FULL logical context under fallback budget
→ fallback call
```

Пути, на которых обязан работать: plain `generate`; tool-enabled `generate_chat`; tool loop; retry path; any direct response branch. Production branch с tools НЕ отправляет fallback-модели payload, рассчитанный под больший primary window.
- **§45 mandatory payload recompose:** при `generate_chat` fallback recompose учитывает system + persona + tool schemas + tool state + messages — НЕ только message text. Recompose пересобирает ПОЛНЫЙ logical context под fallback budget; tool schemas входят в fallback budget (часто крупнейшая константа). Если полный logical context физически не помещается — hierarchical reduction/сегментация P0-контента (по иерархии §37-образной), НЕ тихая потеря tool schemas.
- **§46 Regression production-like тест (primary 1M → fallback 32K + tools):** primary effective 1M; fallback 32K; tool_router enabled; primary forced failure. EXPECT: fallback payload recomposed; ≤ fallback effective budget; P0 context preserved; tools preserved as needed; no provider 400/context overflow.
- Close carry-over **M-ASAP31-2** (backlog): тот же дефект tool-loop пути.

## 5.3 Ответ Q11 (§86, зона 5)

| Q | Ответ |
|---|---|
| **Q11** | См. §5.1: `fallback_payload_adapter` есть ТОЛЬКО в `generate()` (`llm_client.py:953–959`, вызов :1003–1012); `generate_chat` (`llm_client.py:1149–1269`) параметра не имеет и при фоллбэке (:1182–1194) отправляет тот же payload с tools под primary window; Direct-ветка tool_router (`direct_chat_service.py:1942–1950` → `tool_loop.py:225/:278`) не передаёт recompose вовсе, а plain-ветка (:1956–1963) — передаёт. Плюс tool schemas в payload не участвуют в бюджете. Решение — D10 (единый recompose-контракт на всех путях + mandatory payload с tool schemas + регресс §46). |

## 5.4 Invariants (зона 5)

- Ни одна Direct execution path не может уйти в фоллбэк без recompose под fallback budget (§44).
- Recompose ВСЕГДА включает tool schemas/tool state в подсчёт (§45); «выбросить tools, чтобы влезло» — запрещено без иерархической редукции P0-контента.
- LLMBadResponseError не триггерит фоллбэк (существующая семантика сохраняется).
- Recompose failure adapter'а — fail-open в лог + честная диагностика, НЕ тихая отправка oversized payload (усиление против текущего :1010–1012).
- Δ SQLite DDL = 0 (recompose — runtime-логика; snapshot fallback/recompose — события §59).

---

# Зона 6: Decision полностью LLM-driven (T-4213…T-4214, §1.7, §47–§52, §74/§79, Q12)

## 6.1 RCA: где алгоритм всё ещё выбирает REACT до LLM (Q12)

Production-симптом (§1.7 ТЗ): алгоритм пре-действия сам выбирает REACT по классу сообщения («laughter → REACT»), и только затем LLM подбирает emoji — запрещённая схема §47.

**Код 2.58.39 (подтверждено чтением `services/direct_chat_service.py`):**

1. **Действие решается алгоритмом ДО LLM:** `_decision_pre_action` (:1087–1158) — детерминированные ветки (1)–(10): `MSG_LAUGHTER`/`MSG_EMOJI` → `ACTION_REACT` (:1112–1127), `MSG_ACK` → SILENT/REACT (:1129–1137), «не адресован» → SILENT/REACT (:1141–1150), «бот недавно отвечал» → SILENT (:1152). Конкретная реакция назначается алгоритмом же: `_reaction_for_reason` (:677–683, карта `_REACTION_BY_REASON` :669–674) / `_reaction_for_class` (:750–757, `_stable_reaction_pick` :738).
2. **Исполнение REACT идёт по пре-решению:** ветка `pre_action == ACTION_REACT` (:1750–1775); LLM (Stage-1, `_llm_react`) вызывается ТОЛЬКО для выбора emoji: гейт `llm_reaction_enabled` (:1754) → `inject_react_task` (:1883) → `extract_llm_reaction` (:1887) → `react_source="llm_decision"` (:1897); LLM off/invalid → deterministic reaction, `source="deterministic"` (:1925). Владение действием — у алгоритма, LLM — «выбор эмодзи».
3. **SILENT решается алгоритмом:** short-circuit (:1705–1745) + 🗿 silent-ack при direct-autonomous (гейт `_silent_ack_enabled` :1721) — скип-семантика корректна, но решение об исходе алгоритмическое.
4. **Coordinator ASAP-3.1 тоже алгоритмический:** `build_coordinator_decision` (:1022–1055; `_coordinator_choose_action` :982) — intent/addressee/evaluation → action без LLM.
5. **Hard gate force сохранён корректно:** force keyword/address → всегда `ACTION_REPLY` (:1662–1672), fail-safe ошибки policy → reply (:1156–1158).

**Root cause (одно предложение):** выбор action (REPLY/REACT/SILENT) закреплён за детерминированным `_decision_pre_action` (и coordinator'ом ASAP-3.1), а Stage-1 LLM подключается только внутри уже выбранного REACT для подбора emoji — контракт §47 «LLM решает действие» не реализован: реализован «алгоритм решает действие, LLM решает эмодзи».

## 6.2 Решение: единый LLM decision (§47–§52 → ADR-1028-5 D11)

- **§47 Один Decision Maker structured output** в Stage-1: `{"action":"REACT","reaction":"💀","reason":"..."}` / `{"action":"REPLY"}` / `{"action":"SILENT"}`. НЕ «сначала algorithm laughter → REACT, потом LLM выбирает emoji»: выбор REPLY/REACT/SILENT решает LLM в Stage-1 output.
- **§48 Алгоритм остаётся только hard gates/cheap safety:** распознать force keyword; определить reply_to_bot; собрать features; enforce hard product rules. Ветки `_decision_pre_action` демотируются из «решения» в «features»: message_class/addr-state/reply-свежесть идут Decision Maker'у контекстом, а не заменой его решения; fail-safe ошибки policy → reply сохраняется (сейчас :1156–1158). Обычный выбор `REPLY vs REACT vs SILENT` — за LLM.
- **§49 Force Direct сохраняется:** `бот, ...` / явный force address → всегда REPLY; LLM НЕ может заменить его на REACT/SILENT (гейт ДО Decision Maker; прецедент :1662–1672; тест-инвариант force+SILENT→REPLY).
- **§50 SILENT сохраняется:** direct-autonomous + conscious LLM SILENT → 🗿 hardcode (существующий silent-ack путь :1705–1745 переиспользуется); background silence → ничего.
- **§51 REACT:** LLM выбирает конкретную allowed Telegram reaction из runtime list; backend validates; invalid → deterministic safe fallback либо SILENT по существующей policy (прецедент A8 `react_moai`: ≤2 попытки, без рандома); НЕ навязывать `ахах → 😂` — `_REACTION_BY_REASON` остаётся ТОЛЬКО fallback-картой, не источником решения.
- **§52 Decision call count:** НЕ добавлять второй LLM call для emoji — Decision Maker сразу возвращает action + reaction (один structured Stage-1 output; существующий inject/extract-механизм `_llm_react` переиспользуется, контракт расширяется полем `action`; дешевле и ближе к контракту).
- **Kill-switch / откат (§80):** существующие тумблеры (`DIRECT_COORDINATOR_ENABLED`, `flags.chat_decision_reactions_enabled`/`image_reactions`, `llm_reaction_enabled`) дают OFF-паритет: OFF → прежний алгоритмический decision без деградации сервиса; отдельная линия rollback «LLM-driven autonomous decision».
- **Тесты (§74):** mock `{"action":"REACT","reaction":"💀"}` → reaction; mock `{"action":"REPLY"}` → text generation; mock `{"action":"SILENT"}` (direct addressed autonomous) → 🗿; force keyword + модель говорит SILENT → REPLY по hard gate.
- **Reviewer (§87) / live acceptance (§79):** REACT action chosen by LLM; SILENT/force gates preserved; прод-проверка force keyword / reply-to-bot autonomous / LLM-chosen REACT / SILENT 🗿.

## 6.3 Ответ Q12 (§86, зона 6)

| Q | Ответ |
|---|---|
| **Q12** | См. §6.1: действие выбирает `_decision_pre_action` (`services/direct_chat_service.py:1087–1158`) — laughter/emoji/ack/not-addressed → REACT с уже назначенным emoji (`_reaction_for_reason` :677–683, `_reaction_for_class` :750–757); LLM вызывается ТОЛЬКО внутри исполненного REACT для выбора emoji (:1754 гейт → inject :1883 → extract :1887 → source="llm_decision" :1897; deterministic fallback :1925); SILENT решает алгоритм (:1131/:1145/:1152); coordinator ASAP-3.1 (`build_coordinator_decision` :1022) тоже алгоритмический. Force-гейт корректен (:1662–1672). Решение — D11: REPLY/REACT/SILENT решает LLM в Stage-1 output; алгоритм — только hard gates/cheap safety (force §49, SILENT 🗿 §50, allowed-набор §51, один call §52). |

## 6.4 Invariants (зона 6)

- Выбор REPLY/REACT/SILENT на обычном пути — за LLM (§47); алгоритм — только hard gates/cheap safety (§48).
- Force keyword/address → REPLY ВСЕГДА (§49); LLM не может переопределить.
- 🗿 — единственный hardcode реакции (direct-autonomous + conscious LLM SILENT) (§50).
- REACT — только из runtime allowed list; backend validates; invalid → deterministic safe fallback/SILENT (§51); без рандома, ≤2 попытки; `_REACTION_BY_REASON` — fallback, не решение.
- Один Decision Maker call на решение (§52); второй LLM call ради emoji запрещён.
- R17: события `DIRECT_REACT`/`DIRECT_SILENT_ACK` — только source/enum/reaction/причина, без raw текста (§74-моки не вводят приватные данные).
- Δ SQLite DDL = 0; Δ каталога — только через существующие тумблеры (новых ключей не требуется; решение — за T-4233/консолидацией T-4242).

---

# Зона 7: Analytics actual snapshot + GraphRAG health + log severity (T-4215…T-4217, §1.8, §58–§67, §75, Q13)

## 7.1 RCA: какие Analytics budget values theoretical, а какие real (Q13)

Production-симптом (§1.8 ТЗ): misleading read-side cards показывают slot budget с `mandatory_tokens=0` — реальный запрос (system + persona + tools + stage instructions) не учитывается, теоретическая capacity-математика выдаётся за реальный бюджет.

**Код 2.58.39 (подтверждено чтением `services/model_slots.py` / `services/auto_budget.py` / `web/api/analytics.py`):**

1. **Read-side карточки — theoretical с mandatory_tokens=0:** `/api/analytics/context-budgets` (`web/api/analytics.py:316–348`) → `collect_slots` (`services/model_slots.py:84–137`) резолвит budget вызовом `resolve_stage_budget(..., mandatory_tokens=0)` (:104–105) и кладёт `mandatory_tokens: 0` (:122) — слот-картина вообще без обязательного payload.
2. **Real per-request effective budget считается, но не экспонируется:** `resolve_stage_budget` (`services/auto_budget.py:156–236`) в рантайме получает фактический mandatory_tokens; `available = max(1, base − mandatory − reserve − markers)` (:190–196) — это и есть last effective request budget, но он не фиксируется как «последний» снапшот и не попадает в read-side view.
3. **Actual input — только агрегат:** provider usage/estimate фиксируется в `llm_client` (`chat_usage.report_call` + `estimate_tokens` :504–530; provider `usage.prompt_tokens` :812–813) и сворачивается в percentiles `record_slot_observation` (`auto_budget.py:258–296`) → `observed.last/p50/p95/max` — агрегат, а не «последний actual input последнего важного request», без связи с capacity source/окном карточки.
4. **Fallback/recompose для аналитики невидим:** recompose-события fallback-пути (зона 5) и capacity `fallback_used` есть в данных, но «последний actual request» их не соединяет в один снапшот (§59).

**Root cause (одно предложение):** read-side slot view резолвится с mandatory_tokens=0 и без привязки к последним фактическим запросам — theoretical (окно/резервы/auto budget) и real (observed percentiles) живут раздельно, а «последний effective request budget» и «последний actual input» вообще не фиксируются, поэтому пользователь видит карточку, не отражающую реальную картину (§58).

## 7.2 Решение: theoretical vs actual + actual request snapshot (§1.8/§58/§59 → ADR-1028-5 D12)

- **§58 Четыре уровня, не смешивать в одном числе:** (1) физическое окно модели (`1 048 576`); (2) теоретический stage budget (после output/safety reserves); (3) последний effective request budget (после system/persona/tools/mandatory payload); (4) последний actual input (provider usage/estimate). Все четыре подписаны и различимы в read-side cards; пользователь понимает реальную картину.
- **§1.8 Убрать ложные read-side cards с `mandatory_tokens=0`:** слот-карточка либо честно помечена «теоретическая, обязательный payload не учтён», либо дополнена реальным mandatory из последних запросов; карта без реального payload не выдаётся за actual.
- **§59 Actual request snapshot после каждого важного LLM request:** slot; provider/model; capacity source; physical window; mandatory tokens; available input; payload estimate; actual provider input usage (если provider отдал usage; иначе estimate + флаг `estimated`); fallback/recompose маркер. БЕЗ raw content (R17: только числа/enum/короткие source-строки; секреты/тексты/сообщения не логируются).
- **Второй usage store НЕ создаётся** (прецедент ADR-1028-3 §24/§50): snapshot — в существующем канале runtime-метрик/событий (`MODEL_CAPACITY_RESOLVED`/`AUTO_CONTEXT_BUDGET`/`CONTEXT_PRESSURE` переиспользуются), read-side `/api/analytics/context-budgets` получает слот-поле «last_request» из runtime-состояния resolver'а (D12), actual input — из `llm_usage_events`/`record_slot_observation`.
- **Estimated vs actual сохраняется** (§12-семантика ADR-1028-3): provider-reported actual отличается флагом от tokenizer-estimate.
- **Kill-switch:** существующий `ANALYTICS_CONTEXT_BUDGETS_ENABLED` (default ON; OFF → 404 + остальная Аналитика не затронута, fail-open §73) — не расширяется.

## 7.3 GraphRAG health + rerank observable + vector/FTS + severity (§9/§60–§67 → ADR-1028-5 D13)

- **§60 GraphRAG Analytics:** FTS status; vector status; embedding generation status; build progress; fingerprint short; embedding model; vector coverage; last rerank status; rerank invalid rate. Miniapp человекочитаемо (§9, T-4216): «Векторный индекс: перестраивается / FTS-поиск: работает / Готовность: 62% / Модель embeddings: … / Generation: … / Последняя ошибка: нет»; после activation — «Векторный поиск: работает / FTS fallback: доступен»; владелец НЕ читает сырой «A06». Coverage-числитель — по D1: `eligible facts с vec-row provenance==current / все eligible`.
- **§61 rerank — не критический, но наблюдаемый:** reranker failure → bounded fallback; Direct response не падает (согласовано D3); НО invalid rate после deploy должен стать НИЗКИМ — постоянный высокий invalid rate = regression, не expected normal state (T-4193: candidate_count/selected_count/parser status/provider/model/latency/response_format mode/fallback; метрика `rerank_invalid_rate`).
- **§62 vector/FTS порядок:** FTS остаётся резервом ПОСЛЕ active vector; KNN failure → FTS fallback; механику не удалять (согласовано D3; тест §70 failed build → FTS serviceable).
- **§63 embedding config switch:** смена embedding model/provider/dim/preprocessing → old generation НЕ обслуживается как current; new rebuild starts; FTS работает во время rebuild; после validation — atomic activate; vectors разных generations НЕ смешиваются (реализация — shadow-generation D1: старая generation остаётся active до атомарного swap новой; race-защита mid-build — D2).
- **§64 rebuild resource control:** bounded batches; sleep/yield; progress; rate-limit embedding-вызовов; pause/resume; cancellation; restart resume (реализация D2 на REUSE `task_jobs`; production не должен страдать от rebuild).
- **§65 existing vectors / embedding cache:** reuse embedding cache ТОЛЬКО если identity metadata доказывает совпадение provider/model/dims/preprocessing/endpoint fingerprint — иначе re-embed (D1/D2: кэш-переупаковка при неизменном identity допустима, платные API-вызовы не дублируются).
- **§66 «building» active «без базы» — ЗАПРЕЩЕНО:** это запрещённый fix — warning исчезнет, но KNN будет работать на недоказанных vectors; сначала rebuild/verification (согласовано D1: запрещены `UPDATE … SET status='active'` без provenance и маскировка «для тишины»).
- **§67 log severity cleanup (T-4217, после исправления lifecycle D1–D3):** ACTIVE → никаких warning; BUILDING expected → INFO + periodic progress; rebuild stalled/failed → WARNING/ERROR; fingerprint mismatch → WARNING once/state change; повторный not-serviceable не спамить (rate-limit/coalesce — D3, T-4192). No machine-language wall в normal UI (§75).

## 7.4 Ответ Q13 (§86, зона 7)

| Q | Ответ |
|---|---|
| **Q13** | См. §7.1: **theoretical** = физическое окно/effective window/резервы/auto budget — read-side `collect_slots` считает с `mandatory_tokens=0` (`services/model_slots.py:105/:122`); **real** = только observed percentiles (`record_slot_observation`, `auto_budget.py:258–296`, из provider usage/estimate `llm_client.py:504/:812`) — агрегат, не «последний input»; **«последний effective request budget»** (перегруз `resolve_stage_budget` с фактическим mandatory, `auto_budget.py:156–236`) и **«последний actual input»** не экспонируются вовсе → карточки врут `mandatory_tokens=0` (§1.8). Решение — D12: 4-уровневое разделение §58 + per-request snapshot §59 (slot/provider/model/capacity source/window/mandatory/available/estimate/actual/fallback-recompose) без raw content, без второго usage store. |

## 7.5 Invariants (зона 7)

- Четыре budget-уровня (physical/theoretical/effective/actual) не смешиваются в одном числе (§58); read-side cards без реального mandatory payload не выдаются за actual (§1.8).
- Snapshot каждого важного request — R17-safe (числа/enum/source), БЕЗ raw content/секретов (§59).
- Второй usage store не создаётся; `MODEL_CAPACITY_RESOLVED`/`AUTO_CONTEXT_BUDGET`/`CONTEXT_PRESSURE` — переиспользование (ADR-1028-3 §49).
- «building» НИКОГДА не помечается active «для тишины» (§66); FTS — постоянный резерв (§62); vectors разных generations не смешиваются (§63); cache reuse — только по доказанному identity (§65).
- Log severity: состояние ≠ авария (§67); активная жизнь без warning-стены; BUILDING — INFO+прогресс; stalled/failed — WARNING/ERROR; mismatch — once/state change.
- Δ SQLite DDL = 0 (snapshot/slot-состояния — runtime-метрики/события; read-side — существующий endpoint); любая новая потребность DDL — только через T-4242/ADR-waiver (v20-бронь `mca-04b` не занимать).

---

# Зона 8: EXTRA corrective audit (§92–§135 ТЗ → ADR-1028-5 D14)

> §92 ТЗ: прежний EXTRA deployment-отчёт («seeded style delivered», «9/9 production checks», «UI delivered») НЕ принят. Владелец видит пустой реестр (`Без дополнительного стиля`) и `503 save failed` на реальном проде. Новый architecture-блок EXTRA (D14) закрыть corrective-редизайном, а не CSS-патчем.

## 8.1 RCA: PgDatabase vs asyncpg.Pool — что именно сломано (§93–§95, Q-owner)

Production-симптом: `GET /api/cover/styles` возвращает только `Без дополнительного стиля` при СУЩЕСТВУЮЩЕМ seeded-профиле в PostgreSQL; `POST /api/cover/styles` → `503 save failed`.

**Код (подтверждено чтением `web/api/cover_styles.py`, `services/cover_style_registry.py`, `services/pg_db.py`):**

1. **Разрыв уровней хранения.** `PgDatabase` (`services/pg_db.py:611–625`) — обёртка над `asyncpg.Pool` (поле `self._pool`, property `.pool`). Registry-функции (`cover_style_registry.*`) ожидают `pg` и достают из него `.pool` через `_pool_of(pg)` (`cover_style_registry.py:95–96` — `return getattr(pg, "pool", None)`, повторено в 16 вызовах: :107/:134/:149/:168/:188/:212/:277/:301/:360/:375/:394/:413/:433/:459/:549/:585).
2. **API отдаёт в registry НЕПРАВИЛЬНЫЙ уровень.** `web/api/cover_styles.py:42–44`:

```python
def _pool(cache):
    pg = getattr(cache, "pg", None)
    return getattr(pg, "pool", None) if pg is not None else None
```

и далее `registry.get_profile(_pool(cache), ...)`, `registry.upsert_profile(_pool(cache), ...)`, `registry.duplicate_profile(_pool(cache), ...)`, `registry.soft_delete_profile(_pool(cache), ...)`, `registry.remove_reference(_pool(cache), ...)` и т.д. (:228/:241/:243/:259/:262/:275/:299/:417/:419/:540…). В registry попадает **raw `asyncpg.Pool`**, у которого `_pool_of(pool)` ищет вложенное `pool.pool` → `None` → fail-open возвращает `[]`/`False`.
3. **Смешанный контракт внутри одного модуля.** Часть кода честна: `cover_style_registry.py:95` обрабатывает PgDatabase-уровень; `_pg(cache)` (`cover_styles.py:47–48`) возвращает правильный `PgDatabase`; тест-стиль/preview/save-пути (`cover_styles.py:552` `pg=_pg(cache)`; `services/cover_style_jobs.py:126–140` `_pg()` → `cache.pg` → `_pool(obj)`) проходят через правильный объект. Иногда смешиваются: `cover_styles.py:241–243` — `upsert_profile(_pool(cache))` + `get_profile_with_refs(_pool(cache))`, но `cover_styles.py:540` — `pool = _pool(cache)` для preview save. `cover_style_jobs.py:723` (`resolve_style_slot`) работает правильно через `_pg()`-объект. Итог: два уровня (`PgDatabase` и `asyncpg.Pool`) перепутаны как между эндпоинтами, так и внутри одного модуля — «no mixed storage contract may remain» (§94) относится ко всем ~18 `registry.*` вызовам (`cover_styles.py` list/detail/create/update/duplicate/delete/select-validation/reference upload/replace/remove/asset usage/asset delete/asset GET/capabilities/connection status/test-style/preview save).
4. **Fail-open маскирует дефект под product-поведение:** регистр-методы fail-open спроектированы для «PG недоступен → base cover продолжает работать» (защита Summary ladder §31), но сюда же попало «registry отдали не тот объект» — молча `[]`/`False`, никаких логов `EXCEPTION`, всё выглядит как «стилей нет». Тесты (§95) — `tests/test_extra_cover_styles_api.py` monkeypatch'ит `services.cover_style_registry.*` (:109–:458) → проверяется `route → mocked function`, не `route → real registry → PgDatabase → real asyncpg pool` — интеграционной дыры не видно, suite зелёный.

**Root cause (одно предложение):** API-слой `web/api/cover_styles.py` передаёт в `cover_style_registry.*` вместо `PgDatabase` низший уровень `asyncpg.Pool` (`_pool(cache)` :42–44 распаковывает `pg.pool` заранее, а `_pool_of` внутри registry ожидает PgDatabase-объект с `.pool`), поэтому каждая registry-операция fail-open молча возвращает `[]`/`False`, и EXISTING seed/CRUD невидим для реального UI — контрактные тесты это пропустили, потому что monkeypatch'или сам registry.

## 8.2 Обязательные исправления (§96–§131 ТЗ → ADR-1028-5 D14)

### 8.2.1 Connection model redesign (§103–§105)

**Дефект (код):** `resolve_style_slot()` (`cover_style_pipeline.py:55–82`) при `model_mode=custom` трактует `profile["connection_id"]` как RAW `base_url` (:68–73: `override_url = profile.connection_id → base_url = override_url`), при этом API key резолвится глобально из `keys.image_style_api_key` — пер-стиль provider со своими credentials архитектурно невозможен. Confirmed тестом: `test_extra_cover_style_pipeline.py:54` `"connection_id": "https://custom/v1"` → `slot["connection_id"] == "custom"` — ID = URL по конструкции.

**Правильная модель (§104):**

```text
Image Connection: id / provider / base_url / api_key(secret ref)
Style Processing Slot: default_connection_id, default_model
Style Profile: use_default_connection=true | connection_id=<настоящая настроенная коннекция> + model_id
```

Профиль НЕ хранит секрет; Base URL принадлежит Connections; `connection_id` = настоящий FK к configured connection (переиспользовать существующие Connections, если подходят; иначе минимальная чистая абстракция — решение Builder). Style Edit UX (§105): normal — «Использовать подключение по умолчанию» + показ имени подключения/модели/статуса + `[Настроить подключения →]`; override — select из настроенных коннекций + select модели из discovery; на странице профиля НИКАКИХ raw URL/секретов.

### 8.2.2 EXTRA UI redesign (§106–§114) — не CSS-патч

- **IA (§107):** `Summary → Стили обложки` = management screen: сверху «Стиль этого чата» (селектор + Применить), затем «Мои стили» карточками (preview, имя, «Пример · активен», Открыть/⋯), `+ Создать стиль`; `Без дополнительного стиля` — selection state, не fake card.
- **Dedicated editor surface (§108):** desktop — отдельная страница/панель/диалог достаточной ширины; mobile — full-screen route/sheet; редактор НЕ живёт перманентно развёрнутым под селектором; пользователь всегда видит «что редактирую / есть несохранённое / как выйти / что сохранит Save».
- **Progressive disclosure (§109):** первые экраны — имя, инструкция, референсы, КРУПНЫЙ Before→After, нумерация, Test Style, Save; техника — под `Модель и подключение` / `Дополнительные настройки` (capabilities/diagnostics/limits — collapsed).
- **Before→After (§110):** первый open seeded-стиля МГНОВЕННО показывает `style_example_01 → style_example_02` крупными превью (не 32px-иконки, не пустые блоки, не спрятанные под техформами).
- **Референс seed'а (§111):** карточка референса с настоящим thumbnail `medved_press.png` («Медведь Press / Логотип издательства / Заменить / Убрать») видна сразу.
- **New Style flow (§112):** либо server-side draft entity при `+ Создать стиль` (референсы сразу доступны), либо two-step («Название и инструкция» → `Создать и продолжить` → референсы активны); ЗАПРЕЩЕНО показывать активные контролы, которые падают с «Сначала сохраните стиль» пост-фактум.
- **Один Save (§113):** у Style CRUD один очевидный Save; при открытом editor'е глобальный sticky-save скрыт/чётко разделён; на mobile нет двух overlapping save-баров.
- **Bottom overlay geometry (§114):** acceptance обязателен по геометрии: контент скроллится до последнего поля; Save полностью видим/тапаем; bottom nav не перекрывает editor actions; Telegram safe-area уважается; клавиатура не делает Save недостижимым; БЕЗ произвольного `padding-bottom: +Npx` без измерений реального viewport.

### 8.2.3 Browser Use + Playwright — implementation tools, E2E против реального бэкенда (§115–§118)

- LOOP во время имплементации (§115): change → open real UI → interact → inspect layout/console/network → screenshot → fix → repeat; frontend-агент GLM 5.3 Flash + Browser Use + Playwright интерактивно (§131); НЕ писать всю страницу статически и смотреть один раз в конце. Reviewer судит актуальный экран, а не наличие селекторов в HTML.
- **Desktop+mobile E2E (§116–§118)** против authenticated real backend (FastAPI + PostgreSQL + managed assets): полный сценарий §116 (open management screen → seeded виден → открыть → bear thumbnail/Before/After/instruction/counter → edit harmless field → save → reload → persisted → restore → create custom → save → reload → remains → reference upload PNG/JPEG/WebP → thumbnail → reload → persists → replace → remove → duplicate → assign to chat → reload → selection persists → Test Style if provider configured → `Настроить подключения →` → вернуться без потери контекста; network: нет 500/503/скрытых «save failed», asset GET 200, mutations 2xx; console: нет uncaught exceptions). Mobile ~360–390px: touch targets, no horizontal overflow, no obscured Save, no bottom-nav overlap. Desktop ~1280/1600: readable max-width/grid, creative preview доминирует (§118).
- Archived stub-приёмка §96 аннулируется: stub backend остаётся для unit-tests, но НЕ закрывает production acceptance.

### 8.2.3b Permission architecture: доступ к seeded стилю (§135)

- Три раздельные возможности — НЕ объединять: (1) использовать/выбрать Cover Style для чата; (2) создавать/редактировать доступные custom styles; (3) мутировать seeded/default `Графический роман Медведь Press`.
- **Admin-only mutation contract:** только администратор меняет seeded профиль (название, инструкция, references, замена/удаление `medved_press.png`, Before/After assets, нумерация/формат/следующий номер, model/connection override, active/enabled, удаление). Обычный пользователь с правами на модуль/чат — использует и выбирает, но не изменяет определение.
- **Backend enforcement обязателен** (не только скрытая кнопка): прямое mutation API без права → authorization error, PostgreSQL/asset storage/counter/references/preview не изменяются.
- **Miniapp UX:** админ — полноценный редактор; без права — read-only, mutation controls скрыты/disabled, понятное русское объяснение («Этот системный стиль может изменять только администратор»), не показывать editable fields, которые упадут на Save.
- **Permission taxonomy:** право отражено явно в центральном разделе прав (например «Редактирование системных/дефолтных стилей обложки»); матрица раздельно показывает выбор/использование, создание custom, мутацию seeded. Default: `Медведь Press mutation = admin only`; если архитектура допускает делегирование — настраиваемое право, если неделегируемо — системное/admin-only право в матрице (без обходных механизмов).
- **Tests/acceptance:** admin редактирует seeded; non-admin не может через UI; non-admin не может обойти прямым API; non-admin с обычным правом на Cover Styles может выбрать/использовать; экран прав показывает отдельную capability; backend/frontend один permission source of truth; изменение permission (если делегируется) применяется одинаково в UI и API.

### 8.2.4 Seed через API + UI (§97–§101, §119)

- Seed-ассеты в архиве есть: `extra_images/medved_press.png`, `style_example_01.png`, `style_example_02.jpg` (реальное расширение `.jpg` — НЕ переименовывать; §97). Код seed'а существует (`cover_style_registry.py:578–630`: идемпотентно, existing → no-op, не ресетит ручные правки owner'а — соответствует §99), НО seed вызывается только в bot/init-пути — §98-инвариант «после install/миграции seeded-профиль гарантированно существует» и §119 «acceptance через PUBLIC API, не direct SQL» не были верифицированы в реальном проде.
- Требуемое seeded state (§98): `profile_id=medved_press / name=Графический роман Медведь Press / origin=seeded_example / pipeline_mode=generate_then_edit / counter_enabled=true / counter_format=ВЫПУСК {counter} / enabled=true` + 3 asset'а + reference metadata `Медведь Press (логотип издательства)`.
- Идемпотентность (§99): первый install → создать; повторный deploy → без дубля; отредактированный owner'ом seeded → НЕ ресетить; прерванный первый seed → детект + report `COVER_STYLE_SEED_INCOMPLETE`; удалённый owner'ом → НЕ воскрешать самопроизвольно (если product явно не решит иначе).
- Asset serving (§100): `GET /api/cover/assets/<ref>`, `<before>`, `<after>` — authenticated 200 реальные картинки; Style Editor показывает настоящие thumbnails; DB-row-есть/файл-нет → clear integrity error + лог asset_id/file, НЕ тихо «нет превью».
- Reference CRUD E2E (§101): upload PNG/JPEG/WebP → immediate thumbnail → label/description → replace → remove → после reload тот же референс; Vue state-only thumbnail persistence НЕ считается.
- Production acceptance (§119): `GET /api/cover/styles` содержит `medved_press`; detail — 1 reference + before/after asset id; authenticated asset endpoints 200; Browser подтверждает thumbnails; только после этого «seeded style delivered».

### 8.2.5 Integration tests storage contract + static guard (§120–§122)

- **§120:** тесты с real/fake PgDatabase (`.pool` + asyncpg-like pool contract) БЕЗ monkeypatch реестра: API list/create/update/duplicate/references/asset GET/preview → registry → pool. Обязателен regression-тест, который падает на pre-fix реализации, когда raw Pool передаётся на месте PgDatabase.
- **§121 Static contract guard:** одна каноническая конфигурация типа хранилища registry (Architect options: type annotations/protocols; naming convention pg vs pool; один adapter-хелпер; AST/статик-правило, запрещающее `registry.*(_pool(cache), …)`; явный accepts-контракт API). Выбор реализации — Builder, но после fix «случайно передать не тот уровень» должно быть трудно; предпочтительное направление fix — `Registry accepts PgDatabase; API passes cache.pg` (см. также tasks.md T-4218); альтернатива «registry повсюду принимает Pool» — только при явном ADR + type-safe tests.
- **§122 re-eval:** СУЩЕСТВУЮЩИЕ 149 EXTRA-тестов НЕ просто перезапустить и объявить успех: определить, какие были false-positive из-за mocks/stubs → сначала добавить недостающую интеграционную coverage → потом registry/API integration/runtime/job/durable/JS/Browser/full relevant suite.

### 8.2.6 Supporting items (§102, §124, §125, §126–§127, §128–§129, §130, §131, §123)

- **§102/§124 style selection:** `prompts.summary_cover_style_id` НЕ рендерится как текстовый промпт в Prompt Library (сейчас — карточка «Дополнительный стиль обложки» вводит в заблуждение); одна user-facing truth — `Summary → Стили обложки` через настоящий селектор; config key в runtime остаётся; пользователи НИКОГДА не вводят raw profile ID.
- **§125 counter seed:** `SEEDED_COUNTER_START=0` (первое назначение = выпуск 1) — остаётся configurable; отдельного owner-гейта НЕ требуется.
- **§126/§127 Test Style:** без edit-provider — `Обработка стилем пока не настроена` + `[Настроить подключение]`, остальной CRUD НЕ отключается; при наличии provider — visual acceptance на реальной генерации с `medved_press.png` и preview issue text; provider недоступен → честный Unavailable marker, registry/UI/E2E acceptance всё равно РЕАЛЬНЫЕ.
- **§128 observability:** `COVER_STYLE_REGISTRY_LIST_FAILED / COVER_STYLE_SAVE_FAILED / COVER_STYLE_ASSET_MISSING / COVER_STYLE_REFERENCE_UPLOAD_FAILED / COVER_STYLE_SEED_INCOMPLETE`; safe fields: style_id/asset_id/stage/reason/HTTP-class; UI русифицирует, raw DB exceptions НЕ показывает.
- **§129 UI errors:** вместо `save failed` — человеческие формулировки («Не удалось сохранить стиль: хранилище стилей недоступно»; «Не удалось загрузить референс»; «Файл примера отсутствует на сервере»; «Подключение модели редактирования не настроено»); техдетали в логи.
- **§123 deployment doc erratum:** к старому EXTRA deployment-отчёту append (не переписывать историю): «EXTRA production acceptance was incomplete: live authenticated registry CRUD/assets were not exercised; stub-backed UI tests masked PgDatabase/Pool integration bug.»
- **§131 frontend directive:** минимальный diff НЕ ценность против плохого UX — реорганизация Style screen допустима при стабильных backend контрактах.

## 8.3 Sanctions (зона 8)

- **Δ SQLite DDL: предпочтительно 0** — PgDatabase/Pool контракт, UI redesign, E2E, observability-события, селекция стиля, seed-инвариант не требуют новых SQLite таблиц. Бронь v20 оставлена `mca-04b` — НЕ занимать. Реестр Cover Styles живёт в PostgreSQL (`cover_style_*`, PG-DDL — отдельный namespace).
- **Δ PostgreSQL:** по прецеденту EXTRA (`cover_style_profiles/references/assets/issue_assignments/provenance` — идемпотентный `DDL_STATEMENTS`): разрешён аддитивный DDL под connection-model redesign (§104: если нет переиспользуемой Connections-сущности — минимальная чистая абстракция, БЕЗ секретов или full URL в таблицах профиля); добавление таблиц/колонок — идемпотентно, Δ-лист фиксируется в отчёте.
- **Каталог Δ:** существующие ключи Cover Styles (`models.image_style_*` + `prompts.summary_cover_style_id`) сохраняются; НОВЫЕ ключи — только если connection-model redesign требует конфигурируемых default slot полей; при добавлении — Δ-нумерация F8 обновляется от базовых **488/427/463/105/103/21** и согласуется с T-4233/T-4242.
- **Kill-switch реестр:** `COVER_STYLES_ENABLED` (env-only, default ON) — master; `COVER_RICH_DEGRADED_ENABLED` — degraded ladder; новые UI-сущности не должны расширять kill-switch surface (UI redesign — frontend, а не фиче-флаги; fallback на прежний экран НЕ требуется — старый экран признан дефектным).
- **Observability (§88-набор + §128 EXTRA):** management-plane события `COVER_STYLE_*` (§8.2.6) добавляются к media/GraphRAG/Summary/Direct set §88.

## 8.4 Правила §133–§134 (final gates)

- **§133 Final no-false-acceptance rule:** НИКАКОЙ агент не может рапортовать `implemented / verified / production accepted` для user-facing database-backed feature, если evidence = только unit-тесты с mocked storage / stub backend / HTML-маркеры / guest browser session / direct SQL без public API. Acceptance Cover Styles (и будущих Miniapp фич этого класса) — ТОЛЬКО через маршрут владельца: `authenticated Miniapp → real API → real DB → real asset storage → persisted reload`.
- **§134 Final gate:** финальная строка ASAP-3.2 остаётся `ASAP-3.2 production acceptance complete; current_task continuation unblocked.` — после всех critical acceptance Orchestrator СРАЗУ продолжает `current_task.md` (§83–§84).
- **§130 acceptance gate (20 пунктов ТЗ) + §96 + §119 + §133** вместе замещают прежнюю EXTRA acceptance-карточку; задача считается incomplete, пока все 20 пунктов гейта не закрыты на реальном бэкенде.

---

# Финальные секции спека

## F. DoD §90 mapping (кратко)

DoD пункты 1–34 ТЗ ↔ зоны спека:

| DoD §90 | Покрытие |
|---|---|
| 1–6 (image универсальность, общий policy, switch без code change) | Зона 2 (D4–D5), §2.3 |
| 7 (capability discovery автоматически) | Зона 2 §2.2 (Q4 fixes) |
| 8–11 (text capacity, честный unknown) | Зона 3 (D6–D7) |
| 12–15 (GraphRAG lifecycle, FTS, severity) | Зона 1 (D1–D3), Зона 7 (D13) |
| 16–17 (reranker contract) | Зона 1 §5/D3 |
| 18–22 (Summary coverage/reduction/segmentation/empty-guard) | Зона 4 (D8–D9) |
| 23 (Direct recompose) | Зона 5 (D10) |
| 24–26 (LLM decision, force REPLY, 🗿) | Зона 6 (D11) |
| 27–29 (Analytics budgets, health) | Зона 7 (D12–D13) + §88-observability |
| EXTRA: 10–20 acceptance gate §130 | Зона 8 (D14) |
| 30–32 (tests/Browser/Reviewer, deploy, live acceptance) | §76–§79 ниже + T-4232… |
| 33–34 (backlog discipline, current_task continuation) | §82/§83–§84 |

## G. Production live acceptance (§76–§79)

- **§76 Image:** реальный standalone run текущей slow-модели; record provider/model/execution mode/remote status capability/duration; `>90 s success` = инцидент закрыт; отрицательный тест Base Cover + один Style/Preview path без лишней платной повторяемости.
- **§77 GraphRAG:** НЕ подавлением warnings: FTS работает до vector activation; rebuild завершается/видимый healthy progress; `active` ТОЛЬКО после validation; реальный KNN даёт vector-path результат; FTS fallback работает при intentionally недоступном KNN. Если полный rebuild > деплой-окна: deploy resumable rebuild (D2), доказать checkpoint/progress, НЕ блокировать `current_task.md`, vector activation = background completion с watch/health alert, FTS serviceable (§85).
- **§78 Summary:** normal + large 6h windows: 100% source coverage; без empty-package article; без уникального tail-drop; hierarchical reduction если нужно; осмысленные имена/события.
- **§79 Direct:** force keyword; reply-to-bot autonomous; LLM-chosen REACT; SILENT 🗿; tool-enabled fallback recompose.
- Плюс **EXTRA live (D14):** §119/§130 полный authenticated gate против реального бэкенда (реестр/assets/references/per-chat/duplicate/connection model/Prompt Library чист/Browser desktop+mobile).
- **§80 Rollback:** независимые kill-switches сохраняются (media policy / GraphRAG vector activation / LLM autonomous decision / Summary reduction); rollback сохраняет сервис через прежние fail-soft-пути.

## H. Санкции (сводно по зонам)

## H.1 DDL SQLite

- **Предпочтительно: Δ SQLite DDL = 0** для всех зон (см. каждую зону): GraphRAG shadow = идемпотентный `CREATE VIRTUAL TABLE IF NOT EXISTS`; media/Summary/Direct/Analytics — runtime-структуры/события; EXTRA — PG-реестр таблицей.
- Любая новая потребность — ТОЛЬКО через T-4242/ADR-waiver.
- **Бронь v20 остаётся `mca-04b` — НЕ занимать;** ни واحدة зоны её не нарушает.

## H.2 PostgreSQL

- EXTRA reality: реестр Cover Styles живёт в PG по прецеденту (`cover_style_*`); разрешён аддитивный идемпотентный DDL под connection-model redesign (§104) с обязательным Δ-листом в отчёте Builder'а.
- Никаких секретов/full URL в таблицах (R17); raw asset storage на managed disk, PG — метаданные.

## H.3 Каталог Δ + F8

- База F8: **488/427/463/105/103/21** (2.58.39; Δ каталога +4 от EXTRA round1029 уже учтена в этой цифре).
- Дополнительная Δ каталога возможна ТОЛЬКО под новые config-ключи connection-model (если Builder решит, что default slot нуждается в ключах) → данные в отчёт + консолидация T-4242/T-4233; UI/frontend изменения каталога НЕ требуют.

## H.4 Kill-switch реестр

- `IMAGE_*`: существующие env timeouts — migration evidence (зона 2).
- `COVER_STYLES_ENABLED` — master kill; `COVER_RICH_DEGRADED_ENABLED` — degraded ladder; env-only.
- `DIRECT_COORDINATOR_ENABLED` / decision-reactions flags / `llm_reaction_enabled` — OFF-паритет зоны 6.
- `ANALYTICS_CONTEXT_BUDGETS_ENABLED` — не расширяется (зона 7).
- EXTRA UI redesign — без новых kill-switch-флагов; прежний экран не является rollback target (дефектная версия).

## I. Правила §133–§134 (final, распространяются на будущие фичи)

- **§133 explicitly:** no-false-acceptance распространяется на ВСЕ будущие Miniapp database-backed фичи (не только Cover Styles).
- **§134 финальная строка** — контрактное условие разблокировки `current_task.md`; после неё сразу следующий pending task (§83).
