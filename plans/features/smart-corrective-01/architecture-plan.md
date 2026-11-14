# SMART-CORRECTIVE-01 — архитектурный контракт

Статус: ранний черновик, deployed SHA `0e4a144db476a1535ae3a2b79a7cce30354ad866` (checkout HEAD `13884daa`). Read-only architecture validation; application code не изменяется.

## Решение

`ARCHITECT_REQUIRED`: проблема пересекает SourceReader/ToolRouter/ToolLoop/checkup/watchdog/prompts и требует общих контрактов результата, бюджета, provenance и lifecycle. Минимальный ремонт использует существующие контуры: один чтения/поиска, один resolver бюджета, существующий ToolLoopResult/execution-state и существующих incident/job consumers. Не вводить vector index, repo DB, новый trace platform или второй agentic pipeline.

## 1. SourceReader

Канонический поток: `repo identity (owner/repo/ref/commit) → source selection → discovery → locator → verified read → continuation/followup`. Результат содержит `status`, query, repository/ref/commit, selected source, locator kind, path, line range, matches, progress/idempotency id, budget snapshot, provider и provenance (URL/API, exact commit, timestamp).

Статусы: `not_found` — поиск завершён без qualifying hit; `search_failed` — bounded retry исчерпан; `partial` — проверенное evidence есть, но исчерпан continuation/budget/chunk; `source_unavailable` — источник недоступен; `permission_denied` — отказ доступа; `provider_limit` — лимит провайдера; `revision_mismatch` — retrieved commit не совпал с requested. Exact GitHub commit обязателен, branch-head substitution запрещена. Один направленный fallback local→remote (либо remote→local, если таков source selection), без local→remote→local loops. Continuation с opaque cursor, тем же identity, идемпотентен и не повторяет завершённые ranges. Используются существующие progress/idempotency/provider-failure механизмы.

Решение: `ARCHITECT_REQUIRED` для структурированного результата/status/provenance/fallback state machine; `ARCH_REUSE_CONFIRMED` для существующих I/O и failure/retry примитивов после проверки символов в deployed checkout.

## 2. Поиск

Только существующий стек: exact strings, symbols, event/process ids, config keys, traceback fragments, imports/calls. Ranking различает implementation, direct caller, tests, docs, plans, deploy scripts и incidental mention; implementation/caller выше prose. Query refinement добавляет symbol/path/trace fragment или scope, но не invent intent/keyword routing. Возвращаются line ranges/context, затем chunked continuation. Новый fixed top-N не вводится: ON использует effective configured budget; OFF снимает semantic top-N, сохраняя physical/security limits и no-progress guards. GitHub pinned to exact commit.

## 3. Budget propagation

Один resolver определяет factory/default, environment, persisted/chat override precedence и `budget_enforced`; явные настройки чата сохраняются. `chat_id` и budget context проходят через каждый `ToolRouter → SourceReader`, nested/repeat/fallback вызов и direct execution. Known-scope fallback переиспользует resolved scope только при неизменных identity/source; иначе resolve заново. Missing chat id не может заимствовать политику другого чата.

Affected call sites для точной сверки: `services/tool_router.py`, `source_reader.py`, `tool_loop.py`, `direct_execution.py`, `checkup_service.py`, factories/registries и прямые тестовые вызовы.

## 4. Checkup completeness

Переиспользовать `ToolLoopResult` и execution-state; допустимо минимальное расширение `complete|partial|failed`, cause, continuation token/next action, evidence refs. Sufficiency: authoritative source выбран, обязательные incident/process facts покрыты, implementation/caller evidence проверено, текстовое “done” не скрывает обязательный gap. Continuation при partial SourceReader, unresolved fact, provider limit или evidence gap; невозможность продолжения возвращает честный partial с cause. Без второго agentic pipeline и бесконечного model↔check loop: bounded continuation/no-progress guard. Ordinary dialogs нейтральны.

## 5. Checkup input

Разделить семь лимитов: journal window; diagnostics completeness; model capacity; operator budgets; source chunk size; report length; channel limit. Сохранять active ERROR identities, process/job ids, timestamps/status, causal trace fragments, attempted/recovered outcomes и provenance. Не добавлять arbitrary constants и не смешивать fixed memory metrics clip с checkup input budget. Owner settings сохраняются; semantic change требует admin/docs sync.

## 6. Prompt delivery

Telemetry/provenance: `prompt_source`, hash, version_used, chars и layer/component. Слой Core → Expression → Style Policy сохраняется; `prompts.checkup_system_prompt` не переписывать. Stale Betterstack instructions удалять из active contour только при доказанной неактуальности, историю не менять. `CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM` должен соответствовать реально зарегистрированным diagnostic tools и SourceReader.

## 7. Watchdog/incidents — S5 contract (W-01..W-11)

`ARCHITECT_REQUIRED`: read-only analysis/probe подтвердили W-01..W-11. Источники: `investigation/watchdog-code-analysis.md:32-53,115-226`, `investigation/watchdog-probe-results.json:7-153`. S5 должен быть реализуемым контрактом, а не только исправлением эмиссии.

### 7.1 Event vocabulary and compatibility

Сохранить имя `WATCHDOG_TAKEOVER`, `component`, `stage`, `level`, `schema_version`, существующие `REASON_CODES` и `mca_events`/analytics validation. Расширять только разрешёнными additive-полями (`job_id`, при необходимости bounded `entity_ids`; не использовать неизвестный `job_ids`, который сейчас отбрасывается `mca_events.py:365-398,566-568`).

Для каждого обнаруженного job — не более одной записи за один sweep/attempt: `job_id`, owner/kind, previous status/generation, reason, attempt, outcome, fencing/recovery evidence. Допустим один batch summary без job identity только как backward-compatible aggregate, но он не заменяет per-job evidence и не должен дублироваться на каждой строке stale batch. Пустой batch не эмитит takeover. Outcomes строго: `discovered` (найден stale/overdue), `attempted` (recovery вызван), `recovered` (подтверждён допустимый переход в queued/retry), `failed` (ошибка/опасный отказ), `no_change` (проверка не изменила состояние). `takeover_recovered` допустим только для подтверждённого `recovered`; W-02 не маскировать как success.

### 7.2 Recovery and ownership

Не считать снятие lease само по себе recovery. Использовать существующие `recover_job`/requeue и `set_next_retry` с `attempt`, `max_attempts`, `next_retry_at`, checkpoint/dangerous/delivery_unknown semantics. После успешного допустимого recovery job возвращается в `queued` либо получает следующий retry; исчерпание попыток — существующий terminal outcome. Проверять переход и generation/fencing до события.

`recover_stale` получает существующий scope-фильтр `owner`/`kind` (или эквивалентный bounded predicate). Каждый специализированный watchdog восстанавливает только свои задачи: vision не трогает `memory`, `graphrag` и прочие чужие running jobs (W-04). Общий watchdog не берёт queued без отдельного доказанного правила. Queued только диагностируется при отсутствии claimer/истёкшем `deadline_at`, с исключением `next_retry_at > now`; takeover queued запрещён. Нельзя восстанавливать задачу при неопределённом владельце/опасном состоянии; это `failed`/`no_change`, не success.

После takeover старый worker не должен менять terminal state: все terminal writers получают/проверяют fencing token; отсутствие токена не считается безопасным recovery (W-07). Доставка не должна повторно выполнять один recovery attempt при повторной доставке события.

### 7.3 Incident lifecycle and identity

W-05 — первая зависимость: сначала исправить lifecycle, затем менять fingerprint/REASON_CODES. Для связанных job: после фактического terminal state (`completed/succeeded/failed/cancelled` по существующему контракту) следующий sweep автоматически вызывает `resolve(evidence=...)`, когда условие инцидента действительно исчезло. Сохранять строку и историю; DDL не нужен. `resolve()` остаётся явным manual path с evidence, авторизацией и reason.

Resolved incident нельзя молча переоткрывать тем же evidence/fingerprint. Новое наблюдение создаёт новую строку либо явный `reopen_reason`/новую evidence-связь; старую `resolved_at` не очищать. Не удалять history, не понижать severity. `compute_fingerprint` расширяется `kind` и `job_id` (W-11), сохраняя старые поля и REASON_CODES; исторические строки не backfill-ить разрушительно, новые записи используют новый fingerprint, старые остаются читаемыми. При необходимости совместимость достигается dual lookup/legacy fingerprint, не миграцией данных.

### 7.4 Heartbeat, progress, queued diagnosis

Каждый durable-running task type обязан иметь явный контракт: heartbeat с периодом `MCA_JOB_HEARTBEAT_SECONDS` либо owner-specific `deadline_at`; `mark_running` должен устанавливать baseline `progress_at`, если kind требует progress. Карта `kind → heartbeat/progress/deadline/stall bucket` должна покрывать реальные owners (`asap8b01`, `qnd.event`, `mca16`, `mca05`, `memory`, `image`, `vision.*`, `random.uses`, `meme.initiative`, `summary`) и не подменять легальные long external calls.

`progress_at IS NULL` не исключает running job: применять контракт kind (обязателен progress, heartbeat-only или deadline-only). Учитывать `overdue()` и kind-specific thresholds; живой heartbeat не должен быть ошибочно stale, а overdue обязан попасть в диагностический результат. Queued age без claimer/deadline — только telemetry/incident diagnosis, не unconditional takeover.

### 7.5 Incident-service failures and counters

`_track_incident` не подавляет DB/open_or_update failure: log + WARN diagnostic event + bounded local counter/result status (`created|updated|reopened|failed|disabled`). Ошибка регистрации не вызывает `open_or_update` повторно и не создаёт incident из собственной ошибки (AC-24). `result.incidents` считает созданные/новые строки отдельно от updates; один batch с двумя jobs не превращается в два новых incidents.

### 7.6 Ordering, tests, ownership

Порядок: **S5a lifecycle/actual-state auto-resolve + fencing/recovery outcome → S5b scoped recovery/requeue and heartbeat/progress → S5c fingerprint/REASON_CODES/event payload compatibility → S5d incident-failure observability and analytics reconciliation**. S5 write scope: `services/mca_watchdog.py`, `mca_incidents.py`, `task_supervisor.py`/existing recovery seam, `mca_events.py` only for additive allowed fields, and affected task-type heartbeat/terminal writers. Vision/media callers and terminal writers are coordinated writers; serialize shared recovery/event contracts, otherwise tests may run read-only in parallel.

Update existing baseline tests together with code: current tests intentionally assert the defect (`tests/test_smart_exec_learning_incidents.py:100,129-131` expects unresolved/repeat reopen; `tests/test_mca17a_observability_core_round1027.py:667-686` does not assert requeue). Add/adjust tests for: 3 stale jobs → one non-duplicated batch plus one per-job evidence record; `build_event` preserves job identity; failed/None-store/no-op recovery never emits recovered; successful recovery requeues with retry/attempt bounds; scoped vision recovery; fencing rejects late finish; NULL progress and kind thresholds/overdue; queued diagnosis without takeover; lifecycle auto-resolve/manual resolve/no silent reopen; kind+job fingerprint; incident write failure observability and counters.

W-12 (meaning of 72 repeats and production attribution) remains `NEEDS_PRODUCTION_DATA`, an investigation item and not a blocker for W-01..W-11. W-13 is not a defect; W-14 remains backlog-only.

## 8. Срезы и безопасность

S1 SourceReader result/provenance/fallback/search/exact-commit; S2 budget resolver Router/Loop/direct/checkup; S3 checkup completeness/input; S4 prompt delivery; S5 watchdog/incidents. S1→S2/S3; S2→S3; S1/S3→S4; S5 параллелен после freeze shared event vocabulary. Write scopes: S1 `source_reader`+tests; S2 router/loop/direct+budget tests; S3 checkup service/prompts as needed+tests; S4 registry/telemetry/addendum+tests; S5 watchdog/incidents/job-store+tests. Overlapping router/loop/checkup и shared event schema serialize. DDL/migration не ожидается; persisted incidents additive. Fixes active on first production deploy; no shadow/off module; rollback exact release. Existing overrides authoritative.

Evidence: unit status/ranking/budget/limits; integration Router→Reader and checkup continuation; watchdog lifecycle/dedupe; exact-commit fixture; live health/log/effective-state and real checkup. Production-dependent assertions remain unverified until observed.

## 9. Non-goals/invariants

No intent hardcode/keyword routing, second speech engine, embedding/DB/memory/quantum changes, owner prompt rewrite, new trace platform or future-epic functionality. Invariants: exact provenance, no silent source substitution, no fallback loop, no cross-chat budget leakage, no false checkup completion, no duplicate takeover aggregate, no recursive incident failure, no artificial instruction quota.

## Validation ledger

- `ARCHITECT_REQUIRED`: cross-module result/budget/checkup/watchdog contracts.
- `ARCH_REUSE_CONFIRMED`: existing ToolLoopResult/execution-state, provider-failure/idempotency, job/incident consumers and prompt layering (exact symbols pending deployed-code read).
- `NEEDS_PRODUCTION_DATA`: live causal correlation, stale thresholds, production effective budget/prompt telemetry and recovery outcomes.
- External sources: none; no external API claim used.

## Проверенные deployed-code seams (SHA-bound)

- `services/source_reader.py:2467-2519`: `SourceReader.run()` уже принимает `chat_id`, `budget_enforced` и вычисляет policy через `budget_limits_enforced(chat_id)`; это подтверждает reuse единого budget seam, но контракт передачи из Router неполон.
- `services/source_reader.py:2522-2617`: реальный порядок discovery→locator/fetch→followup уже существует; его следует сохранить и расширить структурированными terminal statuses, а не строить новый pipeline.
- `services/source_reader.py:2957-3016`: `_locate_in_tree()` ранжирует, но физически читает только `ranked[:_MAX_LOCATOR_PATHS]`; при deployed configuration это является подтверждённым fixed locator cap/root cause candidate. `candidate_paths` также обрезается через `_MAX_LOCATOR_PATHS * 2`.
- `services/source_reader.py:3019-3038`: `_followup()` является существующим continuation seam; continuation state должен оставаться идемпотентным и provenance-preserving.
- `services/tool_router.py:3345-3470`: `_read_source_code()` принимает `ctx.chat_id`, но вызов `reader.run(...)` передаёт `budget_chars` и `context_query`, без явной передачи `chat_id`/`budget_enforced`; это подтверждённый budget propagation gap.
- `services/tool_router.py:3442-3462`: source reuse существует и keyed by identity/scope/chat; reuse должен оставаться частью idempotency contract, не подменяться новым cache/index.
- `services/checkup_service.py:59-122`: checkup already receives `chat_id`, `telemetry`, `tool_runtime`, resolves prompt and reads `limits.checkup_max_input_symbols`; diagnostics addendum is appended only when schemas exist. `services/checkup_service.py:130-131` separately clips metrics to `_METRICS_MAX_SYMBOLS`; these are distinct limits and must not be conflated.
- `services/tool_loop.py:320-367`: `ToolLoopResult` already carries `reason`, `finalize_mode`, `tool_trace`, `tool_context`, `tool_results`; minimal completeness extension belongs here rather than a second agentic checkup loop.
- `services/mca_watchdog.py:74-93`: progress-stall query selects only `status='running'` rows with non-null `progress_at`, confirming queued/running distinction must remain explicit.
- `services/mca_watchdog.py:96-143`: `sweep()` emits `WATCHDOG_TAKEOVER` inside the stale-row loop with aggregate `job_ids`; this is the confirmed duplicate/incorrect per-job event seam. It also records `recovered` as the store return without an explicit truthful outcome taxonomy.
- `services/checkup_prompts.py:51,72,99,129,188`: deployed prompt text still contains Betterstack references; active-contour removal requires prompt-source/telemetry verification and must not rewrite `prompts.checkup_system_prompt` blindly.

## Root-cause disposition

1. `ARCHITECT_REQUIRED / confirmed`: Router→Reader does not pass effective budget policy (`tool_router.py:3463-3469` versus Reader signature at `source_reader.py:2467-2491`). Minimal fix: pass resolved `chat_id` and `budget_enforced` through nested/reuse/followup calls; add isolation tests.
2. `ARCHITECT_REQUIRED / confirmed`: locator has a fixed `_MAX_LOCATOR_PATHS` slice (`source_reader.py:2983-3015`), incompatible with owner’s ON/OFF semantics. Minimal fix: make semantic ranking/continuation budget-aware; OFF removes semantic top-N only, retaining physical/security/no-progress guards.
3. `ARCHITECT_REQUIRED / confirmed`: watchdog defects W-01..W-11 require the S5 contract above: event identity/outcomes, scoped requeue/fencing, lifecycle auto-resolve, heartbeat/progress/queued diagnosis and non-recursive incident failure telemetry (`mca_watchdog.py:59-164`, `mca_incidents.py:44-249`, `task_supervisor.py:187-247,488-569,712-751`).
4. `ARCHITECT_REQUIRED / confirmed`: checkup has separate input and metrics clips (`checkup_service.py:94-97,130-131`), but no typed research completeness state in `ToolLoopResult`. Minimal fix: preserve seven limit dimensions and add minimal state/evidence fields.
5. `NEEDS_PRODUCTION_DATA`: W-12 — interpretation of 72 repeats and attribution of six production ERROR incidents. Confirmed W-01..W-11 are code/probe-backed and do not wait on this data.

## Implementation handoff

Builder should first freeze the shared payload/status vocabulary and exact call signatures, then implement S1, S2, S3, S4, S5 in the dependency order above; inside S5 use S5a→S5d. Must not change `set_next_retry` state-machine semantics, introduce unsafe auto-recovery, delete incident history, lower severity, or remove watchdog from degraded calculation. Reviewer must falsify: (a) exact-commit source fallback, (b) per-chat ON/OFF budget propagation, (c) checkup partial evidence, and (d) W-01..W-11 cases above. No owner QA assignment is created.

## PM map suggestions

PM may bind S5 to stable rows such as `S5-W01_EVENT_IDENTITY`, `S5-W02_RECOVERY_OUTCOMES`, `S5-W03_REQUEUE_ATTEMPT_BOUNDS`, `S5-W04_SCOPED_RECOVERY`, `S5-W05_INCIDENT_LIFECYCLE`, `S5-W06_HEARTBEAT_CONTRACT`, `S5-W07_FENCING`, `S5-W08_PROGRESS_OVERDUE`, `S5-W09_QUEUED_DIAGNOSIS`, `S5-W10_INCIDENT_FAILURE_OBSERVABILITY`, `S5-W11_FINGERPRINT_COMPAT`. These are suggestions only; PM owns actual map IDs and source coverage.

## Alignment confirmation

Проверены `slice-graph.json`, `plan.md` и соответствующие строки `requirements-map.json`. S5 полностью совпадает с контрактом: `S5A-LIFECYCLE → S5B-RECOVERY → S5C-EVENTS → S5D-OBSERVABILITY`, затем join `S5-WATCHDOG`; `S3B-INPUT` корректно заменяет прежний S5-INPUT. Write scopes и обязательная сериализация S5B→S5C→S5D соответствуют §7.6, а W-05 lifecycle находится до W-11 fingerprint/REASON_CODES. Gate plan сообщает `errors=0` (384 required rows, 367 unique IDs). Единственное уточнение: фактический PM-граф не задаёт линейную цепочку `S1→S2→S3→S3B`; он задаёт `S2-SOURCEREADER` и `S3-BUDGET` параллельно после S1, затем `S4-COMPLETION` после обоих, и `S3B-INPUT` после S4. Это расхождение только в shorthand формулировке общей зависимости, не в S5 и не в архитектурном контракте; карту не изменял.
