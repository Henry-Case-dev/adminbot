# ADR-1028-8 — ASAP 4.1: Durable Whole-Window Summary (SourceWindow first-class, capacity-first, LLMExecutionSupervisor, durable SummaryRun)

> **Фича:** `asap-4-1-durable-whole-window-summary` (ASAP 4.1, corrective architecture pass).
> **Задача-инициатор:** T-4601 [@Architect]; потребители — Builder/Reviewer/DevOps волн 2–9 (tasks.md T-4603…T-4636).
> **Статус:** Accepted (03.10.2026, design; прод-валидация — после delivery, см. «История статуса»).
> **Контекст:** прод 2.58.46 (SQLite `user_version=23`); источник — `plans/current_task.md:22345–23844` (§0–§52, DoD 35), прод-инцидент §0 (L1 FAILED 622s → L2 FAILED → Legacy fallback «SUCCESS» при урезанном материале); PM-пакет фичи (requirements-map/conflict-audit AM-1…AM-6/reuse-inventory/tasks).
> **Связь:** AMEND/SUPERSEDE → ADR-1028-7 D7.1 (AM-1), ADR-1028-3 (AM-2), ADR-1024-6 (AM-3, Summary-scope); EXTENSION → ADR-1028-7 D7.3 (Legacy), D6 (cover style), D3/D5 (bounded revision — сохраняется); не трогает → ADR-1028-1…-6 (кроме перечисленного), MCA-22 D3 (Quote Resolver — extension), ADR-1028-5 D4–D7 (media — паттерн-донор, контур не дублируется).

---

## Supersede / Amend register (по факт-листу conflict-audit §1–§2; дословные директивы владельца 22351–23843)

| # | Старое решение | Новый статус | Директива владельца | Где |
|---|---|---|---|---|
| 1 | ADR-1028-7 D7.1: L1 planning-estimate **sharding до model call** («раньше так было безопаснее»; триггер = семантическая плотность фактов) | **SUPERSEDED → whole-window-first**: chunking разрешён ТОЛЬКО в режиме `CAPACITY_OVERFLOW` (реальная capacity по serialized prompt); planning-математика demoted в developer bounds overflow-планирования | 22469, 22541–22573, 22607–22619; AM-1 | D2/D3, spec §1/§2 |
| 2 | ADR-1028-3 (ASAP-3.1): name-based `MODEL_CONTEXT_WINDOWS` как основной механизм; developer override = уровень 1 цепочки | **AMENDED**: карта = уровень 3 (registry); цепочка §5 дословно: runtime discovery → provider catalog → registry → developer override → conservative fallback; capacity по реальному serialized prompt; cache-key + capability fingerprint; 400/context-length → переоценка | 22520–22537, 22541–22576; AM-2 | D2, spec §1 A.2 |
| 3 | ADR-1024-6 (Epic 47/53): `LLM_TIMEOUT` (120s-класс), `LLM_MAX_RETRIES`+backoff, `LLM_FALLBACK_MAX_RETRIES`, `LLM_TOTAL_BUDGET` для Summary-пути; вложенные retry-уровни | **AMENDED (scope = Summary only):** retry/fallback/deadline — один LLMExecutionSupervisor; wall-clock не health-метрика; modes A/B/C + capability-декларации; прочие потребители llm_client не тронуты; `total_budget_exceeded` в Summary-эмиccии заменён | 22979–23020, 23022–23108, 23187–23199; AM-3 | D4–D6, spec §4 |
| 4 | ADR-1028-7 зона D: Writer вход = FactPackage-центричный пакет; Reviewer сверяет против FactPackage/SourceRefs | **AMENDED**: Writer/Reviewer получают **Full SourceWindow** первоклассно; FactPackage = derived view (обязательная воронка снята); prompt-миграция явная | 22681–22706, 22798–22849; AM-4 | D5, spec §2 B.3/B.4 |
| 5 | ASAP-2/4: `L1_FALLBACK_PACKAGE`/`FACT_PACKAGE_TRUNCATED` как обязательный путь выживания при L1-фейле | **AMENDED (AM-5):** fallback-package остаётся derived view; Summary не сводится к нему — L1 failure → Writer работает от полного окна (degraded structure assistance) | 22743–22775; §0-перечень | D3/D5, spec §2 B.2 |
| 6 | ADR-1028-7 D7.3 (Legacy full-window) | **EXTENDED:** Legacy начинает с SummarySourceWindow (source_ref); ветка capacity-aware (one request / hierarchical, 100% coverage); 50k-стоп dead-path проверяется | 23202–23229 | D7, spec §3 |
| 7 | ADR-1028-7 D6 (cover style) | **EXTENDED:** наследование «По умолчанию (глобальная настройка)» → global default image-edit slot (Medved Press fix §35); capability registry выбор (§36); fail-soft ladder фиксируется | 23285–23360 | D8, spec §6 |
| 8 | Класс настроек §51 | **NEW CONSTRAINT:** L1_CHUNK_SIZE/L2_TIMEOUT/MAX_INPUT_CHARS/SUMMARY_CONTEXT_TOKENS как admin-настройки запрещены; watchdog/capacity цифры — developer deep | 23773–23798 | D9, spec §8 |

**SUPERSEDE-процедура:** дословных указаний «supersede ADR-XXXX» в §0–§52 нет (conflict-audit §1) — владелец даёт прямые директивы «заменить/запрещено/переименовать»; формальные записи — этот register. Старые каноны (ADR-1028-7 D7.1, ADR-1028-3 цепочка) в своих ADR помечаются superseded/amended этим ADR; второй противоречащий канон не создаётся.

---

## D1. SummarySourceWindow — immutable first-class durable snapshot

**Решение.** В начале каждого run создаётся один канонический immutable `SummarySourceWindow` (§1–§2: run_id, chat_id, window_from/to, source_message_count, messages[] с message_id/author_id/display_name/username/timestamp/text/reply_to/forward metadata/media-derived text) и персистится **per-run row** в новой SQLite-таблице `summary_source_windows` (run_id PK; один write в SOURCE_READY, далее immutable). Все производные стадии ссылаются по `run_id/source_ref`; после создания новые «источники истины» из L1 JSON/FactPackage/XML не строятся.

**Альтернативы (отклонены):** in-memory (не рестарт-безопасен, §21); перечитывание истории при resume (окно дрейфует — `compress_and_purge` выполняется до чтения окна; нарушает immutability); task_jobs payload (L-EXTRA-6 + гигантский JSON в job-строке). **Consequences:** +1 таблица v24, retention по TTL; snapshot — единственный рестарт-безопасный носитель полного окна; kill-switch `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED`.

## D2. Whole-window-first + capacity engine (AM-1/AM-2)

**Решение.** Режим входа выбирается ТОЛЬКО реальной effective model capacity:

1. Capacity Resolver (расширение `model_capacity.py`, не новый модуль) — цепочка §5 владельца дословно: runtime discovery → provider catalog → registry (карта, уровень 3) → developer override (уровень 4) → conservative fallback. Override перемещён с уровня 1 на уровень 4 (AMEND ADR-1028-3): применяется, когда higher levels не дали значения; lower-capacity приёмки — через конфиг-фикстуру модели, не override поверх живого каталога.
2. Capacity считается по **фактическому serialized prompt** (system+source+instructions+schema+metadata+output reserve+provider framing), решение `WHOLE_WINDOW | CAPACITY_OVERFLOW` по `required+reserve ≤ effective_context`.
3. Cache: ключ provider+base_url+model+capability fingerprint; смена любого компонента инвалидирует; 400/context-length → переоценка внутри run.
4. Chunking = только аварийный `CAPACITY_OVERFLOW` (иерархический lossless с CoverageLedger, coverage==100% перед Writer; восстановление сегмента или честный degraded). Fallback-провайдер с другим окном → автоматический strategy re-plan (вмещает → same whole-window; меньше → overflow plan), семантика задачи (window/coverage/style/completeness) неизменна.

**Альтернативы (отклонены):** оставить planning-estimate sharding (владелец запретил дословно); глобальный fixed input token cap (запрещён §1); dynamic re-plan по каждому чанку (ломает созданный run — разрешено только до создания сегментных артефактов). **Consequences:** 839-сообщение окно на large-context модели = 1 L1-запрос; kill-switch master `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED`.

## D3. L1 = компактная semantic map; `too_many_facts` demoted (ответ на открытый вопрос PM по AM-1)

**Вопрос PM:** как в WHOLE_WINDOW удерживается компактность L1 (§12) и не возвращается ли `too_many_facts`-invalid, с учётом `MAX_FACTS_PER_THREAD=30`?

**Решение.**
1. **L1 меняет выходной контракт** с §95-v2 (threads/facts с текстами) на **semantic map v1**: `topics[] (title, message_ids[], participants[], short_hint)` + `events[] (kind, message_ids[])` + `relationships[]` (optional) + `unassigned_message_ids[]` — **без source payload**: текст/author/timestamp/reply materialize детерминированно из SourceWindow. Кардинальность «фактов» перестаёт быть выходным измерением L1 → класс `too_many_facts*` из L1-валидации **невозможен по построению** (не «поднят кап», а снято измерение).
2. **`MAX_FACTS_PER_THREAD=30`/`MAX_FACTS_TOTAL=1000` остаются structural ceiling'ами** — теперь они живут в детерминированном синтезе **FactPackage (derived view)** из SourceWindow+map через существующий `repair_capacity_overflow` (summary_l1_capacity.py:173-318, переиспользуется): 31+ факт в теме → подсмыслы ≤30, никогда whole-run invalid (соответствует R4-D-036 «ceiling, не guillotine»).
3. **Компактность карты** удерживается output-контрактом промпта + budget'ами (developer deep: topics ≤ MAX_THREADS, hint ≤160, map ≤ `SUMMARY_L1_MAP_MAX_TOKENS` default 6000). Переполнение бюджета → deterministic compaction (merge мелких тем, дедуп) + `map_degraded` в L1_RESULT; **sharding карты — fallback последней инстанции с полным сохранением покрытия message_ids, не гильотина**.
4. L1 failure ≠ Summary failed: Writer получает Full SourceWindow + instruction «semantic map unavailable — structure source yourself»; переход на урезанный Legacy из-за L1 запрещён. Partial success в overflow: успешные maps сохраняются, проблемный сегмент — deterministic minimal map.

**Kill-switch:** `SUMMARY_L1_SEMANTIC_MAP_ENABLED` (OFF → §95-v2 + прежняя валидация, бит-в-бит 2.58.46). **Consequences:** меньше output tokens/JSON complexity/hallucinated attribution/schema breakage/latency (цели §12); prompt L1 мигрируется явно одним коммитом.

## D4. Writer/Reviewer вход — Full SourceWindow (AM-4)

**Решение.** `WriterInput = source_window (обязателен) + semantic_map? + fact_view? + memory? + target_style + target_extent`; `ReviewInput = Draft + Full SourceWindow + SemanticMap`. FactPackage — derived view (analytics/debug/Reviewer/memory/fallback/compat), Writer не зависит от его урезания. Prompt-миграция Writer/Reviewer явная (прецедент R4-D-003): код+эталон+тесты одним коммитом; prose-first канон ADR-1028-7 D4 и bounded revision ×2 (D3/D5) сохраняются. В CAPACITY_OVERFLOW Writer/Reviewer подчиняются capacity (иерархический Writer по сегментам с ledger-покрытием; Reviewer — evidence-slices против оригинала). Attribution-сверка против реального source (§47) — 8 fixture-сценариев обязательны.

**Kill-switch:** `SUMMARY_WRITER_SOURCE_INPUT_ENABLED` (OFF → FactPackage-центричный вход, бит-в-бит). **Consequences:** Writer проверяет «кто реально что сказал» и восстанавливает пропущенное Structurer'ом; Reviewer ловит wrong speaker из оригинала, даже когда FactPackage этого не содержал.

## D5. LLMExecutionSupervisor (AM-3) — scope Summary, liveness-based, no retry multiplication

**Решение.**
1. **Scope = Summary-пайплайн only** (L1/L2/Writer/Reviewer/Revision/Legacy). Direct/STT/image/embeddings не трогаются — их `LLM_TIMEOUT`/каскады остаются (граница AM-3; обобщение на background-LLM вне 4.1).
2. **Один Supervisor владеет** request_id/provider/model/operation/started_at/last_activity_at/state/attempt/fallback и единолично retry/fallback/deadline. Транспорт — существующий per-call контракт llm_client (`_post(budget=, max_retries=, retry_statuses=)`, llm_client.py:665-696 + `generate_background`, :1098): Summary-вызовы = `max_retries=1`, `retry_statuses=()` (статус-ретраи решает Supervisor), fallback-каскад llm_client для Summary-канала выключен (каскад остаётся прочим потребителям). Паттерн-донор — `media_execution.py` (adaptive windows/job state/adapter capabilities) + executor-прецедент `embedding_control_plane.py`.
3. **Attempt-математика (посчитано по факт-коду):** сегодня ≤6 HTTP/логический вызов (3 primary × 3 fallback) × L1 correction ×2 = ≤12, × stage-цепочка. Контракт: **≤4 HTTP на логический вызов** (1 primary + ≤1 transport retry + ≤1 fallback-provider + ≤1 fallback transport retry), задокументирован и закреплён тестом; логические бюджеты стадий сохраняются (L1 ≤2 вкл. correction retry как отдельный supervised logical request; L2 ≤6 по ADR-1028-7 D3.3). Вложенные циклы stage × client × provider × fallback убраны.
4. **Execution modes (§24) + capability discovery (§26):** адаптеры честно декларируют `supports_streaming_liveness / supports_async_status / supports_cancel / opaque_sync_only`; Mode A (async job, polling живого статуса), Mode B (streaming: last token/event/keepalive → last_activity_at; elapsed не убивает; inactivity/stall detection), Mode C (sync opaque: adaptive watchdog — последний рубеж). Выдуманные ping-endpoint запрещены. Честная база: текущий транспорт sync-opaque → Mode C реализуется сразу; A/B — контрактные слоты, активируются только при верифицированном провайдере (прецедент `EMBED_ASYNC_BATCH_ENABLED`).
5. **Watchdog (§25/§29):** unhealthy = нет подтверждённой активности/provider stalled (не «прошло N секунд»); inactivity threshold adaptive из телеметрии per (provider, model, operation, token-buckets): queue time, time-to-first-activity, generation duration, tokens/sec, failure rate (оценщик — REUSE media_execution: только успешные длительности); hard deadline — developer-level fuse (`SUMMARY_LLM_HARD_DEADLINE_SECONDS`, clamp [600,7200]), последний рубеж.
6. **Rename (§30):** `total_budget_exceeded` → `execution_deadline_exceeded` (fuse) / `retry_time_budget_exhausted` (попытки) в Summary-эмиccии; старые логи — read-side alias only; не-Summary логи llm_client не тронуты.

**Kill-switch:** `SUMMARY_LLM_SUPERVISOR_ENABLED` (OFF → прежний контур llm_client байт-в-бит). **Consequences:** живой длинный запрос не убивается «просто потому, что длинный»; зависший не держит pipeline бесконечно; вопрос «повысить L1_TIMEOUT» исчезает — длительность управляется liveness-супервизией, не константой.

## D6. Durable SummaryRun + resume + идемпотентная публикация

**Решение.** Persistent `SummaryRun`: **dedicated additive SQLite-таблицы** `summary_runs` (стабильный `summary_run_id`, state machine §20: CREATED→SOURCE_READY→STRUCTURING→STRUCTURE_READY→WRITING→REVIEWING→TEXT_READY→BASE_COVER→STYLE_EDIT→PUBLISHING→DONE/DEGRADED/FAILED; publication_status/result_ref; pipeline_health) + `summary_run_stages` (append-only §50.54: status/started_at/last_activity_at/finished_at/attempt/provider/model/result_ref/failure_reason). task_jobs (v14) — execution-носитель (heartbeat/fencing/queue resume REUSE); checkpoint run-state — в `summary_runs`, не в payload-колонке (L-EXTRA-6 не наследуется); стабильный run_id закрывает L-EXTRA-7 (cover-джоба уже ключуется от run_id, cover_style_jobs.py:566-573). Resume after restart: продолжение с последней завершённой стадии по durable-артефактам; **публикация идемпотентна** — фикс PUBLISHING до отправки + проверка publication_status + лестница R4-D-051 (sent unknown → reconcile → retry) + content-hash барьер bot_output_ledger; двойной финал невозможен.

**Альтернативы (отклонены):** носитель = task_jobs payload (L-EXTRA-6); носитель = mca_pipeline_runs расширение (перегрузка root-lifecycle домен-состоянием). **Kill-switch:** `SUMMARY_RUN_DURABLE_ENABLED`. **Consequences:** Summary больше не «хрупкий request handler» (§20); рестарт не создаёт duplicate publication (DoD 21).

## D7. Cover/text independence + Medved Press inheritance + capability registry

**Решение.** (1) Cover-ветка подписывается на approved text snapshot (TEXT_READY) — text pipeline не регенерируется из-за cover failure; cover не наследует text-fallbacks. (2) §35 fix: профиль «Модель обработки: По умолчанию (глобальная настройка)» резолвится по лестнице наследования per-chat override → profile connection override → **global default image-edit slot** (Connections default, поддерживающий image_edit; иначе models.image_style_*) → честный reason; отдельная style connection НЕ обязательна; прод-инцидент Medved Press закрывается. (3) Выбор обработчика — через существующий capability registry (image_capabilities + ImageProviderAdapter): image_edit/reference_images/max_reference_images/prompt_limit/mode; хардкоды NanoGPT/Qwen запрещены; смена image provider → работает или честный Inspector-статус. (4) Fail-soft ladder §37 фиксируется: style fail → Base cover; base fail → Rich без image; Rich fail → Plain same ResponseDocument; текст не уничтожается никогда.

**Kill-switch:** `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED`.

## D8. Inspector и observability

Раздельная coverage semantics (Источник / L1 / Writer input / Final text — 4 метрики, overflow добавляет segments); карточка «КОНТЕКСТ МОДЕЛИ» (capacity + mode + причина); liveness на каждой LLM stage (mode/last activity/fallback/reason); cover style card (§41 + причина fallback); structured events §42 — аддитивное расширение `pipeline_events` (таблица соответствия имён — spec §7.3), append-only, один run_id, R17 (без полных сообщений/промптов/ключей/байтов). Источник данных Inspector — SummaryRun/ledger/stage events, не логи. Производительность — вехи §50 без выдуманного SLA.

## D9. Контракт настроек (§51)

Новые admin-ключи класса `L1_CHUNK_SIZE`/`L2_TIMEOUT`/`MAX_INPUT_CHARS`/`SUMMARY_CONTEXT_TOKENS` запрещены; developer deep settings (env-only, вне каталога, с человеческим описанием): hard deadline, inactivity threshold, capacity safety, map budgets, retention, max revisions. Существующие каталоговые ключи llm_client-группы остаются (не-Summary потребители) с уточнёнными описаниями; `limits.summary_hybrid_context_*` demoted (OFF-паритет); таблица — spec §8.

---

## Sanctions (сводка)

| Решение | SQLite DDL | PostgreSQL | Kill-switches (env-only, default ON) |
|---|---|---|---|
| D1 SourceWindow | v23→v24: `summary_source_windows` | no-op | `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED` |
| D2 capacity/overflow | 0 | no-op | `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED`, `SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED` |
| D3/D4 L1 map + Writer/Reviewer | 0 | no-op | `SUMMARY_L1_SEMANTIC_MAP_ENABLED`, `SUMMARY_WRITER_SOURCE_INPUT_ENABLED` |
| D5 Supervisor | 0 | no-op | `SUMMARY_LLM_SUPERVISOR_ENABLED` |
| D6 SummaryRun | v23→v24: `summary_runs`, `summary_run_stages` | no-op | `SUMMARY_RUN_DURABLE_ENABLED` |
| D7 Cover/Style | 0 (cover_style_* PG не трогаем) | no-op | `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED` |

OFF = бит-в-бит 2.58.46 (parity-тест каждой зоны). Rollback: soft (флаг+рестарт) или cold revert; additive DDL совместима со старым кодом. R17-скан обязателен перед релизом.

## Consequences для Builder/Reviewer/DevOps

- **Builder:** контракты spec.md §1–§8; DDL §10; флаги §11; WriterInput/ReviewInput/semantic map v1/CoverageLedger схемы; attempt-ceiling ≤4; SourceWindow единственная точка создания.
- **Reviewer (T-4629):** линзы «механизм против заглушки» (нет фиктивных coverage/watchdog/supervisor), OFF-паритет всех новых флагов, AM-1…AM-4 выполнены по этому ADR, no-false-quality (R4-D-064)/R17, отсутствие второго resolver/pipeline/реестра, отсутствие хардкодов NanoGPT/Qwen, attempt-бюджет тестом.
- **DevOps:** deploy после пост-ASAP-4 pass'а (AM-6 порядок); бэкап до DDL v24; production acceptance §48 (Run 1 large-context + Run 2 lower-capacity через конфиг-фикстуру, конфиг возвращён), §49 Medved Press, §50 performance (базис 622/155/1331, без SLA).

## История статуса

1. **03.10.2026 — Accepted (design):** D1–D9 утверждены; консистент-гейт с PM — решения отражены в spec §1–§13 и критериях T-4603+; Risk **R3**; прод-валидация pending (delivery → deploy → §48/§49/§50 acceptance).
