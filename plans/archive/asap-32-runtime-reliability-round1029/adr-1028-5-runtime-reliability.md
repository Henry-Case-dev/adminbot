# ADR-1028-5 — Runtime Reliability: GraphRAG recovery lifecycle (shadow rebuild)

> **Фича:** `asap-32-runtime-reliability-graphrag-provider-discovery` (ASAP-3.2).
> **Задача-инициатор:** T-4190 [@Architect]; потребители T-4191…T-4194, T-4216, T-4217, T-4230, T-4235.
> **Статус:** Accepted (для зон GraphRAG + media/capacity + Summary/Direct + Decision LLM-driven + Analytics/health + EXTRA corrective; решения D1–D14, дополнения без ретроспективных правок). **01.10.2026 — прод-валидация 2.58.40: полный релиз D1–D14 VERIFIED (прод `4cb267a`, feat `0483386`, все зоны живые; после точечного инцидент-фикса первого цикла) — см. «Прод-валидация и история статуса».** **01.10.2026 — хотфикс `cover-style-save-hotfix` 2.58.43 VERIFIED (прод `9906c9d`): prod-подтверждение D14-класса контракта (выбор стиля 200 + персистенция, `pg=`-фикс) — история №5.**
> **Контекст:** прод 2.58.39 (`c0e0362`), SQLite DDL v19 (v20-бронь `mca-04b` не занимать); источник — `plans/current_task.md` §2–§9, §61–§62, §64, §70–§71, §85, §86 (Q6–Q9, Q14), SHA-256 `E828A092…B6750A`.
> **RCA основание:** постоянный `building → FTS-only` при `gen_fp == new_fp` — lifecycle-дефект, не mismatch модели; код 2.58.39 (`services/summary_memory.py:1334–1371, 1426–1439, 1451–1523, 1796–1895`) не содержит перехода `building → validated → active` (детально — spec.md §1).

---

## D1. Решение rebuild: вариант A — shadow generation (§5)

**Выбор: Вариант A.** Под текущим identity-fingerprint (provider/model/dims/preprocessing/endpoint) строится **shadow vec-хранилище**: полный re-embed всех eligible source facts (не fill-missing), затем validation и **атомарный swap/activation**; затем FTS остаётся резервом (§62).

Почему не Вариант B (controlled destructive vec rebuild):

1. raw `graph_facts`/`smart_archive_facts` — source of truth, их НЕ трогаем ни в A, ни в B; но B оставляет сервис без векторного пути на всё время rebuild и без rollback-копии, A — сохраняет FTS-first режим и позволяет отменить/повторить build без отказа сервиса.
2. A даёт честную per-row provenance (векторы shadow-таблицы по построению принадлежат текущему generation), чем закрывает Q7 (real coverage становится измеримым) и условие «нет unknown-origin vectors».
3. Деструктивный rebuild не даёт преимущества: sqlite-vec позволяет создавать дополнительную vec0 virtual table (generation-suffixed shadow) — предположение «shadow невозможен» не выполняется.

**Правила (обязательные):**

- existing vec-rows НЕ trusted как current vectors для generation без доказанной связи с fingerprint (§5) — при A это достигается полным re-embed в shadow; дешёвый путь — переупаковка из `embedding_cache` при неизменном identity (без повторных платных API-вызовов);
- Вариант B остаётся документированным резервом ТОЛЬКО если shadow окажется невозможен без чрезмерной сложности (окончательное решение — за Builder с обязательным возвратом к ADR); в B обязательны: source-of-truth не удаляется, FTS доступен весь период, полная validation перед activate;
- ЗАПРЕЩЕНО `UPDATE … SET status='active'` без проверки происхождения всех vectors (§3/§66); ЗАПРЕЩЕНО помечать `building` active «для тишины» (§66);
- per-row provenance в RAW таблицы не добавляется — маркер принадлежности generation находится в shadow-хранилище/реестре поколений (Q14: Δ SQLite DDL = 0).

## D2. Resumable rebuild lifecycle на durable task infrastructure (§7/§64)

- REUSE `task_jobs` (не заводить новую durability-инфраструктуру); state machine: `queued → running → checkpoint → validated → activated | failed`; checkpoint → продолжение после restart (§70: тест restart mid-build → resume).
- Полный rebuild, НЕ «fill missing»; батчи bounded (`_BACKFILL_BATCH`-образные), sleep/yield между батчами, rate-limit embedding-вызовов, pause/resume/cancellation, прогресс в PROGRESS-логах/health.
- НЕ блокировать startup/polling на часы: rebuild — фоновая durable задача; при деплое допускается «deploy resumable rebuild» по §85 (vector activation = background completion, condition watch; FTS serviceable; auto-activation после completion реализована и проверена на fixture/smaller prod slice).
- Race-защита при смене конфига mid-build: build привязан к полученному на старте CURRENT fingerprint; активируется ТОЛЬКО build, чей генерационный fingerprint == fingerprint на момент validate (§70: config changes during build → старый build НЕ активируется как current; создается новый queued build под новый fp).
- Failure → `failed` (или `building`+reason): состояние фиксируется, FTS остаётся serviceable, повторный build — только по явному триггеру/ретраю policy, БЕЗ автоматического storm.

## D3. Activation criteria + логи + failure/fallback semantics (§6/§8/§9/§62)

- **Activation (все 9 критериев обязаны быть true одновременно):** fingerprint==current; dim==current; provider/model identity соответствует config; preprocessing_version соответствует; все eligible facts имеют vec-row либо явно классифицированную допустимую причину отсутствия; нет orphan vectors; count/coverage validation прошла; sample KNN smoke прошёл; transaction/swap завершён. После activation: `Векторный поиск: работает / FTS fallback: доступен`.
- **Логи (§6):** `EMBEDDING_GENERATION_BUILD_START / PROGRESS / VALIDATED / ACTIVATED`.
- **Severity (§8/§67):** при честном идущем rebuild — это СОСТОЯНИЕ, а не авария: первый `not serviceable` WARNING → далее rate-limit/coalesce; обычные запросы → DEBUG/INFO; повторный WARNING — только при meaningful state change или cooldown; BUILDING expected → INFO + периодический прогресс; rebuild stalled/failed → WARNING/ERROR; fingerprint mismatch → WARNING once/state change.
- **Fail-soft не превращается в ложную уверенность:** FTS-only — явный degraded-режим, отражённый в health (§9): «Векторный индекс: перестраивается / FTS-поиск: работает / Готовность: N% / модель embeddings / generation / последняя ошибка» — без сырого `A06` для владельца (T-4216).
- **FTS — постоянный резерв (§62):** после active — KNN failure → FTS fallback; механику не удалять. Удаление FTS-механики после activation — НЕ допускается (T-4193/T-4230).
- **Rerank (§10–§12):** вторая дефектная линия (parser) чинится независимо от lifecycle: provider-capability aware structured contract `{"selected":[1,4,7]}` / `{"selected":[]}`; иначе strict prompt + robust legacy-numeric parser + acceptance только in-range candidate IDs + детерминированный repair (fences/префикс) локально; второй LLM-вызов ради formatting запрещён; bounded fallback — последний fail-soft, остаётся; метрика `rerank_invalid_rate` (после deploy высокий rate = regression); observability candidate_count/selected_count/parser status/provider/model/latency/response_format/fallback; приватные raw факты НЕ логировать (Q9 — synthetic reproduction).

---

## Consequences

- Builder (T-4191/T-4192/T-4193) получает однозначный контракт: shadow-полный-rebuild → resumable на `task_jobs` → 9-критериальная активация → FTS-резерв; Reviewer-checklist (§87 строки GraphRAG, T-4194) проверяет «lifecycle имеет путь building→active; activation только после verified rebuild; FTS работает во время rebuild; rerank invalid — не expected normal state».
- Δ SQLite DDL = 0 (shadow-таблица — идемпотентный `CREATE VIRTUAL TABLE IF NOT EXISTS`, статусы — в v18-реестре поколений с аддитивными опциональными колонками по образцу `endpoint_fingerprint`); v19 остаётся; v20-бронь `mca-04b` не занята (Q14 закрыт без миграции). Любая новая потребность DDL — через T-4242/ADR-waiver.
- Rollback: shadow-подход делает rollback build'а безопасным — raw/старое поколение не разрушены; откат деплоя (git revert 2.58.40) возвращает честный FTS-only без потери данных.
- Риски: R3 — длительность rebuild (~2 млн сообщений) — mitigated D2 (resumable + progress + §85 background completion); конфликт с бронью v20 — снят (DDL=0).

## Compliance-карта

| Секция ТЗ | Покрытие |
|---|---|
| §2–§3 (RCA, запреты) | D1, spec.md §1 |
| §4 (lifecycle) | D1/D2 |
| §5 (shadow vs destructive) | D1 |
| §6 (activation) | D3 |
| §7 (resumable) | D2 |
| §8 (severity/latency лога) | D3 |
| §9 (health) | D3 (UI — T-4216) |
| §10–§12 (rerank) | D3 (реализация — T-4193) |
| §61–§62 (fail-soft/FTS-резерв) | D3 |
| §64 (resource control) | D2 |
| §66 (запреты) | D1 |
| §70/§71 (тесты) | T-4228/T-4230, T-4193 |
| §84/§85 (prologue/live acceptance) | T-4235 |
| Q6/Q7/Q8/Q9/Q14 | spec.md §6 / D1–D3 |
| §13–§36 (media/adaptive) | D4–D7, spec.md «Зона 2» |
| §19–§20, §53–§57 (text capacity) | D5, spec.md «Зона 3» |
| Q1/Q4/Q5/Q14 | spec.md §2.1/§2.2/§2.6 |
| Q2/Q3 | spec.md §2.6 (live-верификация T-4195, route names не выдумывать) |
| §37–§40 (Summary reduction) | D8, spec.md «Зона 4.2» |
| §41–§43 (coverage/oversized/empty-guard) | D9, spec.md «Зона 4.3» |
| Q10/Q14 | spec.md §4.1/§4.4 / D8–D9 |
| §44–§46 (Direct fallback recompose) | D10, spec.md «Зона 5.2» |
| Q11 | spec.md §5.1/§5.3 / D10 |
| §1.7/§47–§52 (LLM decision), §74/§79 | D11, spec.md «Зона 6» |
| Q12 | spec.md §6.1/§6.3 / D11 |
| §1.8/§58–§59 (Analytics actual snapshot) | D12, spec.md «Зона 7» |
| Q13 | spec.md §7.1/§7.4 / D12 |
| §9/§60–§67 (GraphRAG health/severity/config-switch) | D13 (+D1–D3), spec.md «Зона 7» |
| §75 (browser: budgets/health читаемы) | T-4232 |
| §92–§95 (EXTRA RCA PgDatabase/Pool) | D14, spec.md «Зона 8.1» |
| §96–§99 (browser acceptance superseded / seed) | D14, spec.md «Зона 8.2.3/8.2.4» |
| §100–§101 (assets/reference CRUD) | D14, spec.md «Зона 8.2.4» |
| §102–§105 (style selection + connection model) | D14, spec.md «Зона 8.2.1» |
| §106–§114 (UI redesign) | D14, spec.md «Зона 8.2.2» |
| §135 (seeded style permission architecture) | D14, spec.md «Зона 8.2.3b» |
| §115–§118 (Browser Use + Playwright E2E) | D14, spec.md «Зона 8.2.3» |
| §120–§122 (integration tests + static guard + re-eval) | D14, spec.md «Зона 8.2.5» |
| §123–§129 (erratum/selection/counter/Test Style/observability/UI errors) | D14, spec.md «Зона 8.2.6» |
| §131–§132 (frontend directive / order of operations) | D14, spec.md «Зона 8» |
| §130 (EXTRA acceptance gate 20 пунктов) | D14, spec.md «Зона 8.4» |
| §133–§134 (no-false-acceptance / final gate) | D14, spec.md «Зона 8.4» / «Финальные секции» |

---

## D4. Зона 2 — Media Adapter + executor honesty (§15–§18, §20–§21)

**Решение:** единый provider-agnostic `ImageProviderAdapter` contract (discover_models / discover_capabilities / submit_generation / submit_edit / supports_async_job / supports_status / supports_stream / supports_cancel / get_status / get_result / cancel) — core pipeline НЕ привязан к NanoGPT route names; env-шаблоны `COVER_STYLE_ASYNC_*` = migration evidence, НЕ целевой contract.

- NanoGPT adapter: async/status использовать как PRIMARY execution mode для slow generations ТОЛЬКО после live-верификации реального endpoint'а ключом (exact catalog route, async submit shape, job/task/request ID, status route, terminal statuses, recovery после reconnect, cancel, capability fields — §16; запрещено изобретать `task_id` route по аналогии). OpenRouter — unified image API + programmatic capabilities, streaming preview/progress как liveness source где поддерживается, sync/adaptive path иначе, без hardcode counts/resolutions (§17). Прочие providers — generic interface + adapters для текущих connections + безопасный generic sync fallback (§18).
- Shared layer: connection identity, cache/invalidation (по model/base URL/connection change), provider detection, diagnostics — общие с text-capacity framework (D5), но без одного класса-монолита (§20).
- `image_capabilities.py` fixes (§21): discovery вызывается автоматически (не только при переданном готовом dict); NanoGPT catalog реально fetch'ится; OpenRouter `supported_parameters.input_references` и endpoint-level capabilities parse'ятся по реальной schema; async/status capability НЕ выводится из несвязанных полей; unknown остаётся честным unknown; TTL-cache инвалидируется при model/base URL/connection change.

**RCA-основание (Q1/Q4):** 90/180/240 — три независимых env wall-clock timeout'а (`IMAGE_REQUEST_TIMEOUT_SECONDS` standalone + Summary Base Cover; `IMAGE_ATTEMPT_TIMEOUT_SECONDS` retry-попытка; `COVER_STYLE_EDIT_TIMEOUT_SECONDS` Style Edit), hard timeout = первый и единственный механизм «модель умерла»; async/status есть только у Cover Style через ручные env-маршруты; автоматический live discovery не гарантирован. Детально — spec.md «Зона 2.1».

## D5. Зона 2 — MediaExecutionPolicy: inactivity vs total, stage-aware, durable state, recovery, fallback (§13–§14, §22–§31)

**Решение:** один resolver `MediaExecutionPolicy` для ВСЕХ image ops; key `provider+model+operation` (stage-aware: generate ≠ edit); четыре различных окна: connect / read-inactivity / poll-request / **total generation deadline** (§28). При remote job/status — deadline = safety ceiling, НЕ inactivity timeout; `queued/starting/running/processing` = job жив; progress обновляет liveness; НЕ рубить живую generation по wall-clock 90 с (§24). Sync-only: adaptive deadline по успешным наблюдениям — estimator p50/p90/p95/p99/max-bounded per provider+model+operation; формула-кандидат `clamp(max(cold_default, p95×safety_factor), min_deadline, hard_safety_ceiling)` (финальные коэффициенты — Architect после анализа реальных данных, §25); estimator НЕ обучается на timeout'ах как на success (§26); cold-start defaults — developer-level, 90/180/240 = migration evidence (§27).

- Honest capability `remote_progress = job_status | streaming | none`; fake ping запрещён (§14) — долгоиграющий sync-запрос без job/status не может быть проверен отдельным пингом.
- Durable media state: standalone long-running ops → durable job на REUSE `task_jobs` (operation/provider/model/provider_job_id/status/submitted_at/last_progress_at/deadline_at/attempt/result asset/failure reason — §29); Δ SQLite DDL = 0.
- Restart recovery: известный provider job ID → resume polling, НЕ автоматический повторный платный submit; sync-only disconnect → честно `unknown_after_disconnect`; платный retry без policy/idempotency-понимания — запрещён (§30).
- Fallback: только после terminal primary failure; capability/deadline пересчитывается + prompt/input recompile под fallback capabilities; НЕ переключаться, пока primary честно RUNNING (§31).
- Regressions обязательны (§32–§34): `qwen-image-3-pro >90s` успешно завершается; Base Cover happy path не ухудшать; EXTRA ladder (style optional → style failed→base cover → base failed→Rich without cover → Rich failed→sendMessage) и issue counter/style assets/provenance не ломать.
- Observability (§35–§36): события `MEDIA_JOB_*`, safe fields (без keys/prompts/image bytes); Miniapp показывает режим выполнения/среднее/P95, без пользовательского input «90 seconds».

## D6. Зона 3 — Text Capacity Resolver (§19–§20, §53–§56)

**Решение:** provider-agnostic capacity adapters на shared framework (§20): **NanoGPT** — provider adapter вместо registry guess (live/public catalog schema; резолв `provider/base_url/model → context window → max output if available → capability source`; catalog недоступен → registry/fallback с честным source в Analytics, §53); **Direct DeepSeek** — отдельный adapter/identity, не generic host; отсутствие machine-readable catalog → verified official registry entry с source=`verified_registry`, НЕ `provider_catalog` (§54); **OpenRouter** — существующий adapter сохранить; проверить text capacity discovery, image capability discovery, endpoint-specific capability, cache invalidation (§55); **Unknown provider** — НЕ угадывать из URL; лестница: standard discovery endpoints (если реально отвечают) → provider plugin → verified registry → developer override → conservative fallback; UI показывает fallback status (§56); local runtime (llama.cpp/Ollama/vLLM) сохранить (§19).

## D7. Зона 3 — Discovery timeout / caching (§57, Q14-грань)

Metadata fetch короткий, НЕ задерживает каждый user request; cache с invalidation по connection/model change; provider discovery failure НЕ блокирует normal generation (fallback capacity + honest source); повторные попытки — async, вне hot path. Media/text discovery используют общий shared-слой (connection identity/cache/detection/diagnostics), но discovery отделён от исполнения запроса. **Δ SQLite DDL = 0:** media-поля — в существующей generic `task_jobs`; capacity source — в runtime-метаданных; любая новая потребность DDL — только через T-4242/ADR-waiver (v20-бронь `mca-04b` не занимать).

## D8. Зона 4 — Summary hierarchical semantic reduction вместо destructive truncation (§37–§40, Q10)

**Решение:** нормальный path Summary/FactPackage НЕ производит semantic destructive truncation после L1: L1 (exhaustive/chunk_all) отдаёт FULL source set (§37), затем при несоответствии бюджету L2 выполняется hierarchical semantic reduction pipeline:

```text
all L1 outputs
→ stable-ID merge
→ topic dedupe
→ semantic subpackages
→ intermediate reduction
→ merge reduced subpackages
→ final L2 package
```

Все unique topics остаются представлены. Budget L2 — размер ОДНОГО call, НЕ разрешение терять semantic content (§38): при невозможности уложиться в один L2-бюджет без потери — chained/paged L2-сегментация, НИКОГДА silent drop. Сжимать МОЖНО: повторяющиеся fragments, duplicate evidence, одну тему в нескольких chunks, verbose description, repeated chronology wording (§40); НЕЛЬЗЯ silently выбрасывать: уникальный факт / участника / событие / тему. Позиционные каскады 2.58.39 (`_apply_fragment_caps`, `_enforce_budget` — «старые первыми» по timestamp) остаются ТОЛЬКО как fail-soft последней линии, каждое срабатывание — видимое degraded-событие, НЕ норма; production-эффект `FACT_PACKAGE_TRUNCATED skipped_fragments=267/354` (§1.4) на нормальном path исчезает. **RCA-основание:** L1 честен — режет L2-пакетирование позиционно без семантической идентичности (детально — spec.md «Зона 4.1», Q10).

## D9. Зона 4 — Coverage metrics + oversized segmentation + empty-guard (§41–§43)

**Решение:** (1) Semantic coverage metrics обязательны: unique semantic items before / after, merged duplicates, unique dropped, reduction passes; Normal: `unique_dropped = 0` (§41); метрики — числа (R17-safe) в события/Analytics (T-4215); `unique_dropped > 0` на normal path = regression. (2) Oversized single message → lossless segmentation: одно source message больше L1 request budget режется на lossless parts с сохранением original message_id, part index, author, timestamp, reply relation, text parts; merge знает, что это одно исходное сообщение (§42). (3) Empty-summary guard ASAP-3.1 СОХРАНЯЕТСЯ — hotfix не откатывать; инвариант `source > 0 AND semantic package empty → Hybrid invalid → recovery/Legacy`; никогда не публиковать article «про пустой пакет» (§43); существующий EMPTY-PACKAGE GUARD/degraded-события не трогать. **Δ SQLite DDL = 0** (runtime-метрики, in-memory сегменты; Q14-грань — spec.md §4.4).

## D10. Зона 5 — Direct tool-path fallback recompose на всех execution paths (§44–§46, Q11)

**Решение:** контракт `primary payload → primary failure → resolve fallback capacity → RECOMPOSE FULL logical context under fallback budget → fallback call` обязателен на ВСЕХ Direct execution paths: plain `generate`; tool-enabled `generate_chat`; tool loop; retry path; any direct response branch (§44). Recompose при `generate_chat` учитывает ПОЛНЫЙ mandatory payload: system + persona + tool schemas + tool state + messages — НЕ только message text; tool schemas входят в fallback budget (§45); полный logical context не помещается физически → hierarchical reduction/сегментация P0-контента, НЕ тихая потеря tool schemas. Adapter-fail-open текущего `generate()` (:1010–1012) усиливается: recompose failure — лог + честная диагностика, НЕ тихая отправка oversized payload. Regression production-like (§46): primary effective 1M / fallback 32K / tool_router enabled / primary forced failure → EXPECT: fallback payload recomposed; ≤ fallback effective budget; P0 context preserved; tools preserved as needed; no provider 400/context overflow. **RCA-основание (Q11):** `fallback_payload_adapter` есть только в `generate()` (llm_client.py:953–959/:1003–1012); `generate_chat` (llm_client.py:1149–1269, fallback :1182–1194) не имеет adapter и отправляет primary-размерный payload с tools; Direct-ветка tool_router (direct_chat_service.py:1942–1950 → tool_loop.py:225/:278) recompose не передаёт, plain-ветка (:1956–1963) — передаёт. Закрывает carry-over M-ASAP31-2. **Δ SQLite DDL = 0.**

## D11. Зона 6 — Decision полностью LLM-driven (§1.7, §47–§52, Q12)

**Решение:** один Decision Maker structured output в Stage-1 возвращает `{"action":"REACT","reaction":"💀","reason":"..."}` / `{"action":"REPLY"}` / `{"action":"SILENT"}` — выбор REPLY/REACT/SILENT решает LLM, НЕ алгоритм (§47). Алгоритм остаётся ТОЛЬКО hard gates/cheap safety (§48): распознать force keyword, определить reply_to_bot, собрать features, enforce hard product rules; детерминированные ветки `_decision_pre_action`/coordinator демотируются из «решения» в «features» (fail-safe ошибки policy → reply сохраняется).

- **Force Direct (§49):** force keyword/address → всегда REPLY; LLM не может заменить на REACT/SILENT (гейт ДО Decision Maker).
- **SILENT (§50):** direct-autonomous + conscious LLM SILENT → 🗿 hardcode; background silence → ничего.
- **REACT (§51):** LLM выбирает конкретную allowed Telegram reaction из runtime list; backend validates; invalid → deterministic safe fallback либо SILENT по существующей policy (прецедент A8 `react_moai`, ≤2 попытки, без рандома); НЕ навязывать `ахах → 😂` (`_REACTION_BY_REASON` — только fallback-карта).
- **Call count (§52):** НЕ добавлять второй LLM call для emoji — Decision Maker сразу возвращает action + reaction (inject/extract `_llm_react` переиспользуется, контракт расширяется полем `action`).
- **Kill-switch/откат (§80):** существующие тумблеры (`DIRECT_COORDINATOR_ENABLED`, decision-reactions flags, `llm_reaction_enabled`) дают OFF-паритет — прежний алгоритмический decision; rollback-линия «LLM-driven autonomous decision» независима и не разрушает сервис.
- **Тесты (§74)/Reviewer (§87)/live (§79):** REACT mock → reaction; REPLY mock → generation; SILENT (direct addressed autonomous) → 🗿; force keyword + модель говорит SILENT → REPLY по hard gate; REACT action chosen by LLM; SILENT/force gates preserved. **RCA-основание (Q12):** action выбирает `_decision_pre_action` (`services/direct_chat_service.py:1087–1158`; REACT :1112–1149 с emoji из `_reaction_for_reason` :677–683/:750–757), LLM вызывается только внутри исполненного REACT для emoji (:1754/:1883/:1887/:1897; deterministic fallback :1925); SILENT решает алгоритм (:1131/:1145/:1152), coordinator ASAP-3.1 (:1022) — тоже. Детально — spec.md «Зона 6.1/6.3». **Δ SQLite DDL = 0.**

## D12. Зона 7 — Analytics theoretical vs actual + actual request snapshot (§1.8, §58–§59, Q13)

**Решение:** read-side Analytics разделяет ЧЕТЫРЕ уровня без смешивания в одном числе (§58): (1) физическое окно модели; (2) теоретический stage budget (после output/safety reserves); (3) последний effective request budget (после system/persona/tools/mandatory payload); (4) последний actual input (provider usage/estimate). Ложные read-side cards с `mandatory_tokens=0` убираются (§1.8): слот-карточка либо честно помечена «теоретическая», либо дополнена реальным mandatory.

- **Actual request snapshot (§59)** после каждого важного LLM request: slot; provider/model; capacity source; physical window; mandatory tokens; available input; payload estimate; actual provider input usage (если есть; иначе estimate + флаг `estimated`); fallback/recompose маркер — БЕЗ raw content (R17).
- Второй usage store НЕ создаётся (прецедент ADR-1028-3 §24/§50): snapshot — в существующих runtime-событиях/метриках (`MODEL_CAPACITY_RESOLVED`/`AUTO_CONTEXT_BUDGET`/`CONTEXT_PRESSURE`), read-side `/api/analytics/context-budgets` — слот-поле «last_request» из runtime-состояния resolver'а, actual input — из `llm_usage_events`/`record_slot_observation`.
- **RCA-основание (Q13):** `collect_slots` резолвит budget с hardcoded `mandatory_tokens=0` (`services/model_slots.py:105/:122`) — theoretical; real = только observed percentiles (`auto_budget.py:258–296` из provider usage/estimate `llm_client.py:504/:812`); «последний effective request budget» (`resolve_stage_budget` с фактическим mandatory, `auto_budget.py:156–236`) и «последний actual input» не экспонируются. Детально — spec.md «Зона 7.1/7.4». **Δ SQLite DDL = 0;** kill-switch `ANALYTICS_CONTEXT_BUDGETS_ENABLED` не расширяется.

## D13. Зона 7 — GraphRAG health, rerank observable, vector/FTS/config-switch, log severity (§9, §60–§67)

**Решение:** (1) **§60 GraphRAG Analytics** — FTS status; vector status; embedding generation status; build progress; fingerprint short; embedding model; vector coverage (числитель по D1: `eligible facts с provenance==current / eligible`); last rerank status; rerank invalid rate — человекочитаемо в Miniapp (§9, T-4216): «Векторный индекс: перестраивается / FTS-поиск: работает / Готовность: N% / …»; владелец НЕ читает сырой «A06». (2) **§61 rerank не критический:** failure → bounded fallback, Direct не падает; НО invalid rate после deploy должен стать низким — постоянный высокий = regression, не normal state (наблюдаемость T-4193, метрика `rerank_invalid_rate`). (3) **§62 vector/FTS порядок:** FTS — постоянный резерв ПОСЛЕ active vector; KNN failure → FTS fallback; механику не удалять (согласовано D3). (4) **§63 embedding config switch:** смена model/provider/dim/preprocessing → old generation не обслуживается как current; new rebuild; FTS работает во время rebuild; после validation atomic activate; vectors разных generations не смешиваются (shadow-generation D1 + race-защита D2). (5) **§64 rebuild resource control:** bounded batches, sleep/yield, progress, rate-limit embedding-вызовов, pause/resume, cancellation, restart resume (D2 на REUSE `task_jobs`). (6) **§65 existing vectors/cache:** reuse embedding cache ТОЛЬКО при доказанном совпадении identity (provider/model/dims/preprocessing/endpoint fingerprint) — иначе re-embed. (7) **§66:** помечать `building` active «без базы» — ЗАПРЕЩЕНО (сначала rebuild/verification; согласовано D1). (8) **§67 log severity cleanup (T-4217):** ACTIVE → никаких warning; BUILDING expected → INFO + periodic progress; rebuild stalled/failed → WARNING/ERROR; fingerprint mismatch → WARNING once/state change; повторный not-serviceable — rate-limit/coalesce (D3, T-4192); no machine-language wall в normal UI (§75). **Δ SQLite DDL = 0.**

## D14. Зона 8 — EXTRA corrective audit: PgDatabase-vs-asyncpg.Pool contract + UI/connection/E2E/seed/permissions (§92–§135)

**RCA-основание (код подтверждён):** `web/api/cover_styles.py:42–44` (`_pool(cache)` распаковывает `cache.pg.pool` заранее) передаёт в `cover_style_registry.*` (~18 call sites: list/detail/create/update/duplicate/delete/select-validation/reference upload/replace/remove/asset usage/asset delete/asset GET/capabilities/connection status/test-style/preview save) raw `asyncpg.Pool` вместо `PgDatabase`; `_pool_of(pg)` registry (`cover_style_registry.py:95–96`, 16 вызовах) ожидает PgDatabase-объект с `.pool` → на raw Pool он находит `pool.pool = None` → fail-open молча `[]`/`False`; результат: `GET /api/cover/styles` → только `Без дополнительного стиля` при существующем seeded-профиле, POST → `503 save failed`. Fail-open (спроектированный как «PG down → base cover работает») маскирует контрактный дефект под product-состояние; тесты (`test_extra_cover_styles_api.py`, monkeypatch `services.cover_style_registry.*`) проверяли `route → mock`, а не `route → real registry → PgDatabase → real pool` (§93–§95). Дополнительный дефект модели данных: `resolve_style_slot()` (`cover_style_pipeline.py:55–82`) трактует `profile.connection_id` как raw `base_url` (ID = URL по конструкции, API key резолвится глобально из `keys.image_style_api_key`) — provider-agnostic connection architecture §104 не реализована (детально — spec.md «Зона 8.1»).

**Решение (обязательные исправления):**

1. **Connection model redesign (§103–§105):** `Image Connection (id/provider/base_url/api_key-secret-ref) → Style Processing Slot (default_connection_id/default_model) → Style Profile (use_default_connection | connection_id = настоящий FK к configured connection + model_id)`. Профиль НЕ хранит секрет; Base URL принадлежит Connections; пер-стиль custom provider с собственными credentials — возможен. Preference: `Registry accepts PgDatabase; API passes cache.pg` (T-4218); альтернатива «registry принимает Pool» — только при ADR + type-safe tests; все ~18 `registry.*` вызовов аудированы — «no mixed storage contract may remain».
2. **UI redesign (§106–§114, не CSS-патч):** management screen (`Стиль этого чата` + `Мои стили` карточками + `Без дополнительного стиля` как selection state); dedicated editor surface (desktop panel/dialog, mobile full-screen route); progressive disclosure (имя/инструкция/референсы/Before→After/нумерация/Test Style/Save первичны, техника collapsed); крупный Before→After seeded (`style_example_01 → style_example_02`) при первом open; видимая reference card с thumbnail `medved_press.png`; New Style flow — server-side draft или two-step (запрещено «Сначала сохраните стиль» пост-фактум); ОДИН Save (без конкурирующего global sticky-save на editor); мобильная геометрия — измеренная (safe-area, клавиатура, bottom nav не перекрывает; без произвольного `padding-bottom`).
3. **Browser Use + Playwright (§115–§118, §131):** обязательные реализационные инструменты GLM 5.3 Flash (loop change → real UI → interact → inspect → screenshot → fix); E2E против authenticated real backend (FastAPI+PostgreSQL+managed assets) — полный 27-шаговый сценарий §116 desktop + mobile ~360–390px (§117) + desktop ~1280/1600 (§118); network без 500/503/hidden save-failed, asset GET 200, console без uncaught exceptions; Reviewer судит актуальный экран, а не селекторы в HTML; stub-приёмка §96 аннулируется.
4. **Seed через API+UI (§97–§101, §119, §98–§99):** seeded state инвариант (medved_press/Графический роман Медведь Press/seeded_example/generate_then_edit/counter/ВЫПУСК {counter}/enabled + 3 asset'а + reference metadata); идемпотентный lifecycle (no duplicate, no reset owner edits, interrupted seed → `COVER_STYLE_SEED_INCOMPLETE`, owner-deleted не воскрешается самопроизвольно); asset serving — authenticated 200 реальные картинки, DB-row-без-файла → clear integrity error (не «тихо нет превью»); reference CRUD E2E c persistence после reload; acceptance состава `GET /api/cover/styles` → detail → asset 200 → thumbnails, только потом «seeded style delivered».
5. **Integration tests storage contract (§120–§122):** тесты API→registry→pool через real/fake PgDatabase БЕЗ monkeypatch registry; обязательный regression RED на pre-fix (raw Pool на месте PgDatabase); static contract guard (§121 — протоколы/naming/AST-правило/accepts-контракт, выбор Builder); re-eval 149 EXTRA-тестов — сначала определить false-positive mocks/stubs и добавить integration coverage, потом registry/API/runtime/job/durable/JS/Browser/full suite.
6. **Supporting (§102/§124/§125/§126–§127/§128–§129/§123):** `prompts.summary_cover_style_id` НЕ textarea в Prompt Library (одна user-facing truth — селектор Summary); counter start 0 configurable без owner-гейта; Test Style без provider → `Обработка стилем пока не настроена` + `[Настроить подключение]` (CRUD не отключён); provider недоступен → честный Unavailable marker без блокировки roadmap; observability `COVER_STYLE_REGISTRY_LIST_FAILED/SAVE_FAILED/ASSET_MISSING/REFERENCE_UPLOAD_FAILED/SEED_INCOMPLETE` (safe fields: style_id/asset_id/stage/reason/HTTP-class; UI русифицирует, raw DB exceptions не показывает); human UI errors §129; deployment-док erratum append: «EXTRA production acceptance was incomplete: live authenticated registry CRUD/assets were not exercised; stub-backed UI tests masked PgDatabase/Pool integration bug» (историю не стирать).
7. **Permission architecture (§135):** три раздельные возможности — не объединять: использовать/выбирать стиль для чата; создавать/редактировать custom styles; мутировать seeded/default `Медведь Press`. **Admin-only mutation contract:** seeded профиль (название/инструкция/references/замена-удаление `medved_press.png`/Before-After assets/нумерация/override/active/удаление) мутирует только администратор; обычный пользователь — использует и выбирает, не изменяет определение. **Backend enforcement обязателен** (не только скрытая кнопка): прямое mutation API без права → authorization error, PG/asset storage/counter/references/preview не изменяются. **Miniapp UX:** админ — полноценный редактор; без права — read-only, controls скрыты/disabled, русское объяснение «Этот системный стиль может изменять только администратор», не показывать editable fields, которые упадут на Save. **Permission taxonomy:** право явно в центральном разделе прав (например «Редактирование системных/дефолтных стилей обложки»); матрица раздельно показывает выбор/создание custom/мутацию seeded; default `Медведь Press mutation = admin only`; делегирование — если архитектура допускает, иначе системное/admin-only право без обходных механизмов. **Tests:** admin редактирует seeded; non-admin — нет через UI; non-admin не обходит прямым API; non-admin с обычным правом Cover Styles может выбрать/использовать; экран прав показывает отдельную capability; единый permission source of truth backend/frontend.

**No-false-acceptance rule (§133, окончательная):** ни один агент не рапортует `implemented/verified/production accepted` для database-backed user-facing фичи, если evidence — только mocked unit-tests/stub backend/HTML-маркеры/guest session/direct SQL; acceptance Cover Styles и всех будущих Miniapp database-backed фич — только через authenticated Miniapp → real API → real DB → real asset storage → persisted reload. **§134:** финальная строка `ASAP-3.2 production acceptance complete; current_task continuation unblocked.` — Orchestrator сразу продолжает `current_task.md` (§83–§84, §132 order of operations).

**Sanctions (D14):** Δ SQLite DDL предпочтительно 0 (бронь v20 `mca-04b` не занимать; реестр — в PG); Δ PostgreSQL — по прецеденту `cover_style_*`, аддитивный идемпотентный DDL под connection-model (без секретов/full URL в таблицах, Δ-лист в отчёте); Δ каталога — только под новые default-slot ключи connection-model (если нужны), F8-нумерация от базовых 488/427/463/105/103/21, через T-4233/T-4242; kill-switches — `COVER_STYLES_ENABLED`/`COVER_RICH_DEGRADED_ENABLED` сохраняются, UI redesign новых флагов не вводит (прежний экран не rollback target).

---

## Прод-валидация и история статуса (reconcile @Architect, 01.10.2026)

**История статуса:**

1. **30.09.2026 — Accepted** (design): решения D1–D14 для зон 1–8 утверждены этим ADR; Builder-контракт T-4191…T-4233, Reviewer-гейт §87/§130/§133.
2. **01.10.2026 — Round 2 Review: APPROVED FOR RELEASE** (H-ASAP32-1 закрыт, M-ASAP32-2 закрыт; гейт-биндинг Reviewed-Commit `1287130`, WTH `0f6e0f5f…4bfa6`).
3. **01.10.2026 — прод 2.58.40 VERIFIED** (инцидент-фикс кодировки, точечный деплой; коммиты `5aa4626` feat + `f5054df` docs + `93fee19` deploy-doc, push `1287130..93fee19` = ровно 3 коммита, чужого WIP нет) — **Accepted + prod-validated (partial)**: на проде только инцидент-фикс-подмножество; полный деплой зоны D1–D14 (GraphRAG rebuild/Media/Capacity/Direct Decision/UI-редизайн, §107–§135) — отдельным полным деплоем после MCA-очереди/решения владельца. Данный раздел — пост-деливери дополнение reconcile; сами решения D1–D14 не менялись, approval ревью не инвалидирован (код дельты байт-идентичен ревью-манифесту, WTH-гейт `0f6e0f5f` воспроизведён байт-в-байт перед коммитом, drift — только служебный заголовок манифеста).
4. **01.10.2026 — полный релиз D1–D14: прод 2.58.40 VERIFIED (второй цикл)** (feat `0483386` — 80 файлов, +6905/−643, зоны A/B/C/E/F/H; docs `4cb267a` + deploy-doc `325b1b5`; push `3198cb5..4cb267a`, ff без force; prod `4cb267a`, health 200) — **Accepted + prod-validated (full)**: все зоны D1–D14 задеплоены и живы (детали ниже). Сами решения D1–D14 не менялись; approval ревью (round 2, полный D1–D14-скоуп) не инвалидирован — binding-гейт `0f6e0f5f` воспроизведён по существу на commit-момент: per-file SHA-256 всех 10 релизных untracked-файлов = байт-в-байт манифесту (10/10), полный pytest **10319/2** = точное воспроизведение ревью-чисел (нулевой дрейф кода), WTH at-commit `cc525203` зафиксирован. Honest tails (resume GraphRAG, smart_archive KNN-smoke, live paid generation T-4234 + authenticated browser acceptance T-4227 — владелец) — `plans/backlog.md` Follow-up ASAP-3.2.
5. **01.10.2026 — хотфикс `cover-style-save-hotfix` 2.58.43 VERIFIED** (root cause — Д-1: `set_chat_params` в `cover_style_select` звался без `pg=` → `ChatLorePgUnavailable` → 503 «save failed» на каждый выбор; Д-2: плоский ключ патча `{"prompts.summary_cover_style_id": id}` молча выбрасывается namespace-мержем chat_params → ложный 200 без записи; feat `f1057db` — 3 скоуп-файла + release-mechanics; review `Approved for release` на `0dc5679` + per-file WTH 4/4 byte-exact; прод ff `0dc5679..e84600e`, prod `9906c9d` = deploy-docs, health 200) — **Accepted + prod-validated (хотфикс-дельта)**: D14-класс «не тот объект/не тот контракт на call-site» (§93) получил prod-подтверждение закрытия на смежной chat_params-границе (детали ниже). Сами решения D1–D14 не менялись; approval хотфикс-ревью не инвалидирован (правки — docs-only).

**Прод-валидация 2.58.40 (инцидент-фикс; evidence — `deployment.md` §3–§7, review.md Round 2):**

- **H-ASAP32-1 (кодировка) закрыт продой:** байт-ремонт 221 строки `services/summary_fact_package.py` (runtime-литералы `FALLBACK_TOPIC_NAME` = «Общий ход обсуждения», `DESCRIPTION_SEPARATOR` = « · », `rstrip(" ·")`); hex-скан чист (mojibake-последовательности `d0 92 c2 b7`/`c3 92`/`ef bf bd` = 0); на проде свежий импорт по кодпоинтам → **LITERALS_OK** до и после рестарта; error-spike 0 после рестарта против базлайна 18/~10 ч предыдущего процесса. 3 нетавтологических encoding-теста (`TestSourceEncodingIntegrity`) чувствительность доказана (3/3 FAIL на pre-fix копии).
- **M-ASAP32-2 (fp-recheck) закрыт в транзакции активации:** re-check `memory._identity_fingerprint() != fp` первой операцией `_body` внутри `write_transaction` (`graphrag_rebuild.py:474–478`); behavioral-матрица 8/8 PASS (mismatch → activate=False, live остаётся на прежнем поколении, shadow не активируется). На проде контур **dormant**: `graphrag_rebuild.py` задеплоен, но не импортируется задеплоенным кодом 2.58.39 (планировщик GraphRAG стартует из незадеплоенного `bot.py`) — fp-recheck активируется будущим полным деплоем зоны D.
- **Пустой fallback-пакет больше не публикуется — Legacy:** контракт крон-верификации (deployment.md §7): при провайдерском таймауте — `L1_FALLBACK_PACKAGE` c `fragments>0`/`chronology>0` ЛИБО `LEGACY_FALLBACK`; пустой пакет в `L2_START` и мета-текст в публикации — никогда. Класс инцидента 2.58.37 (пустая публикация `msg 1120810` / мета-текст) закрыт на уровне литералов и guard-цепочки; первый крон-прогон на 2.58.40 — 01:00 UTC 01.10.2026 под наблюдателем (`/tmp/asap32_watch.sh` → `/tmp/asap32_watch.log`).
- **Санкционированное включение `services/summary_semantic_reduction.py` в релиз** (отклонение от буквальных «3 файлов» инцидент-задания, санкционировано review.md Round-1 §Staging.1, зафиксировано deployment.md §2 и workflow_state): +209 строк, обязательная lazy-import зависимость `summary_fact_package` L909 под default-ON `SUMMARY_SEMANTIC_REDUCTION_ENABLED` (prod kill-switch-резолв: True) — без него первый крон-саммари упал бы ImportError; D8-редукция фактически активна на проде в составе 2.58.40.
- **Границы прод-валидации (честно):** production acceptance §76–§79 (T-4234/T-4235/T-4236 полные live-гейты D1–D14) этим деплоем НЕ выполнялась — деплой не затрагивал web/* и планировщики; полный live acceptance tracked в `plans/backlog.md` (Follow-up ASAP-3.2). Δ SQLite DDL = 0 (v19; бронь v20 `mca-04b` не занята), PG DDL = 0, seeds = 0; откат — cold revert 2.58.39 (`c0e0362`), soft — `SUMMARY_SEMANTIC_REDUCTION_ENABLED=false`.

**Прод-валидация 2.58.40 — полный релиз D1–D14 (второй цикл, 01.10.2026; evidence — `plans/archive/asap-32-runtime-reliability-round1029/deployment-round2.md` §0–§10):**

- **Деплой/гейты:** FF `3198cb5..4cb267a` (feat `0483386` 80 файлов + docs `4cb267a`), deploy-doc `325b1b5`; restart active (PID 2580591); `/healthz` 200 `2.58.40`, `/api/health` 200; каталог F8 488/427/463/105/103/21 — CHECK OK read-only; **Δ SQLite DDL = 0 (v19, v20-бронь не тронута)**; **PG +1 аддитивная таблица `cover_style_connections`** (D14/§104 connection-model, cover_style_* 5→6) — ожидаемый DDL полного релиза, идемпотентный CREATE при старте; автоматический seed-инвариант T-4220 — идемпотентный no-op (`[cover_styles] seed ensure | profile=medved_press`), профиль цел.
- **Зона A GraphRAG (D1–D3/D13) — активна:** планировщик стартует из деплоенного `bot.py` (dormant-состояние цикла 1 снято); 2 джобы засchedule'ены на старте (`graph_facts_vec` gen=1, `smart_archive` gen=1, fp `96f80838f683`); shadow-таблица `graph_facts_vec_g1` создана; checkpoint-прогресс **1300→2500 embed-фактов за ~13 мин**; при исчерпании лимитов эмбеддинг-провайдера джоба **честно перешла в терминальный `failed`** (LLMRateLimitError) вместо вечного `building` — старый класс lifecycle-дефекта устранён; реестр поколений честный (без фейковой активации §66); FTS serviceable (15013 доков); **возобновление с checkpoint на следующем старте** (§85 background completion, активация — автоматически после validation по 9 критериям).
- **Зона B Media (D4–D5) — активна:** `MEDIA_EXECUTION_POLICY_ENABLED=True`; stage-aware cold-окна generate **180s** / edit **240s** (connect 15/read 60/poll 30) — статические 90s более не предел; durable media jobs/restart recovery в проде dormant до первой image-операции (платные вызовы не триггерились — честная граница, не acceptance).
- **Зона C Text Capacity (D6–D7) — активна, источники честные:** NanoGPT каталог fetchится живьём (**625 моделей**, `provider_catalog`, max_output 524288/32768); имена моделей прода вне каталога → честный `registry`/`fallback` 16384 (designed-путь §53/§56); DeepSeek → `verified_registry`; OpenRouter → `provider_catalog` (live).
- **Зоны D/E (D8–D10) — активны:** paged-L2-потребители (`summary_generator`/`summary_test_run`) и fallback-recompose (`llm_client`/`tool_loop`/`direct_chat_service`) задеплоены; ядро semantic reduction — с цикла 1; крон-саммари 01:00 UTC — первый прогон на полном коде.
- **Зона F Decision (D11) — активна:** `DIRECT_LLM_DECISION_ENABLED` ON; гейт-конъюнкция env+per-chat проверена на проде (`llm_decision_enabled(reactions=True)=True`, `(False)=False`); behavioral live-наблюдение (REACT/REPLY/SILENT в реальном чате) — по мере естественного трафика (без credential-триггера не форсировалось).
- **Зона H EXTRA corrective (D14) — активна:** PgDatabase-контракт: `/api/cover/styles` и `/api/cover/connections` без авторизации → **401** (T-4222 enforcement); seeded-профиль в PG цел; `cover_style_connections` создана (6/6 таблиц); новый UI-редизайн отдаётся; unauth browser smoke (SSH-туннель → Playwright): bundle 2.58.40, приложение грузится, **0 консольных ошибок приложения** (только favicon 404), честный guard «Миниапп открыт без Telegram-контекста».
- **Гейты качества:** ladder/parity — 8 asap32-файлов на прод-venv **102 passed**; журнал после рестарта **0 ERROR/CRITICAL/Traceback** (WARNING — только 429-ретраи эмбеддингов, темп rebuild + 1 честный `EMBEDDING_GENERATION_FAILED` на smart_archive); severity-коалесинг §8 подтверждён журналом; R17-скан — 0 попаданий; локальные гейты до пуша: pytest **10319/2** (байт-паритет с review Round 2), JS **52/52**, F8 CHECK OK, UI E2E RC=0.
- **Откат:** soft kill-switches (`DIRECT_LLM_DECISION_ENABLED`/`MEDIA_EXECUTION_POLICY_ENABLED`/`GRAPHRAG_SHADOW_REBUILD_ENABLED`/`SUMMARY_SEMANTIC_REDUCTION_ENABLED` → false + рестарт, OFF-паритет) либо cold revert `3198cb5`; PG-таблица `cover_style_connections` остаётся (аддитивная, пустая, безопасна для старого кода); SQLite не менялся — откат кода безопасен.
- **Честные границы (не acceptance, → backlog):** T-4234 live платная generation — не выполнялась (нет authenticated-триггера из DevOps-сессии); T-4227 20-пунктовый authenticated browser acceptance — нужна реальная Telegram-сессия владельца; полная активация vector — background completion (2500/15013, темп ограничен 429 free-tier Gemini, resume с checkpoint); behavioral live-наблюдение Decision/paged-L2 — по мере трафика. Резюме в `plans/backlog.md` (Follow-up ASAP-3.2).

**Прод-валидация 2.58.43 — хотфикс `cover-style-save-hotfix` (01.10.2026; evidence — `plans/features/hotfix-cover-style-select-save-failed/{deployment.md §4, evidence.md, review.md}`):**

- **Д-1 (`pg=`-фикс) закрыт продой:** прод-смоук `POST /api/cover/select` (init-data, HMAC `WebAppData`, real PG) — **200** `{"chat_id":…,"style_id":"medved_press"}` (прежде — 503 «save failed» на каждый выбор); передача `pg=_pg(cache)` в `set_chat_params` подтверждена живым вызовом на реальном роутере и реальном PG.
- **Д-2 (персистенция в правильной форме):** override `chat_params.overrides["prompts.summary_cover_style_id"]="medved_press"` записан в PG; читающий путь (`get_all_chat_params(pg=)` → `_resolve_from_root`) резолвит тот же выбор — тот же путь, которым мини-апп восстанавливает выбор после reload; снятие выбора (pop-ветка Д-2) — 200, ровно 2 записи `chat_lore_history` (select+clear, `changed_by=user.id`, без дублей); чужие overrides чата (`flags.*` ×2, `memory.*` ×2) байт-в-байт не тронуты.
- **Гигиена деплоя:** NO DDL (SQLite v21, книга миграций и PG — без изменений), каталог F8 **488 Δ=0** CHECK OK на проде, 0 новых ошибок в журнале после рестарта (только известный GraphRAG embed-429 фон), R17-скан чист; UI (`web/app.js`) не менялся — browser smoke N/A по биндингу ревью; откат — cold revert `6888d20` (2.58.42), прод-состояние смоуком не загрязнено.
- **Связь с D14:** хотфикс — тот же класс дефекта «не тот объект/не тот контракт на call-site» (§93), что зона 8 EXTRA corrective: контракт PgDatabase-vs-Pool в `cover_styles.py` сам был чист (`_pg(cache)` для registry), разрыв сидел на соседней chat_params-границе; тесты `TestSelectPersistsViaChatParams` (real chat_params без monkeypatch + RED-on-pre-fix, stash-приём) — применение правила интеграционных тестов §120 D14 на этой границе. Неблокирующие хвосты (L-HOTFIX-1 RMW-гонка, L-HOTFIX-2 per-chat membership) — `plans/backlog.md` (Follow-up hotfix).

---

## Завершение ADR

**Статус:** Accepted — D1–D14 покрывают зоны 1–8 и финальные правила §133–§134. Спецификация фиксирует data-contract для Builder (T-4191…T-4233: включительно EXTRA T-4218 storage contract / T-4222 seeded-permissions), Reviewer (§87 + §130 20-пунктный gate + no-false-acceptance §133) и DevOps (live acceptance §76–§79 + §119).

**Sanctions list (сводный по всем зонам D1–D14):**

| Зона | Решение | SQLite DDL | PostgreSQL | Каталог/kill-switch |
|---|---|---|---|---|
| 1 GraphRAG (D1–D3) | shadow generation rebuild | 0 (идемпотентный CREATE VIRTUAL TABLE + v18-реестр) | — | без изменений |
| 2 media (D4–D5) | единый adapter+policy | 0 (REUSE `task_jobs`) | — | env timeouts → migration evidence |
| 3 capacity (D6–D7) | provider adapters | 0 | — | honest source labels |
| 4 Summary (D8–D9) | hierarchical semantic reduction | 0 | — | coverage-метрики |
| 5 Direct (D10) | universal recompose | 0 | — | — |
| 6 Decision (D11) | LLM-driven decision | 0 | — | существующие тумблеры (OFF-паритет) |
| 7 Analytics (D12–D13) | 4-уровневый budget + health | 0 | — | `ANALYTICS_CONTEXT_BUDGETS_ENABLED` не расширяется |
| 8 EXTRA (D14) | PgDatabase contract + UI redesign + E2E + seed/refs | **0 (предпочтительно)**; бронь v20 `mca-04b` — не занимать | аддитивный идемпотентный DDL допускается (прецедент `cover_style_*`, Δ-лист обязателен) | новые ключи — только под connection-model (T-4233/T-4242); `COVER_STYLES_ENABLED` master; UI redesign без новых флагов |

Общая ledger: v19 остаётся; v20 — бронь `mca-04b`; любая новая потребность DDL — только через T-4242/ADR-waiver. База каталога F8: **488/427/463/105/103/21**. Финальный gate — §134.
