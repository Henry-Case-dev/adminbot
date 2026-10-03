# ASAP 4.1 — tasks.md (Step 1 @PM, 03.10.2026; Step 3-consistency-гейт @PM, 03.10.2026)

Feature: `asap-4-1-durable-whole-window-summary` — срочный corrective architecture pass после ASAP-4. Нумерация: **T-4600+** (максимум занятого — T-4510 `post-asap4-corrective-pass`; диапазон T-46xx свободен — проверено rg, только директива в `workflow_state.md:352`). Формат: ID, роль, цель, **критерий приёмки**, якорь источника, зависимости, пункты DoD §52.

Источник: `plans/current_task.md:22345–23844` (§0–§52, прочитан полностью; файл не изменяется). Трассировка R6-xxx → якоря → задачи: `requirements-map.md` (рядом); reuse: `reuse-inventory.md`; конфликты/AMEND-кандидаты: `conflict-audit.md` (AM-1…AM-6).

**Шаг 3 (consistency-гейт 03.10.2026):** архитектура утверждена — `spec.md` + `adr-1028-8` (Accepted). Решения Architect'а вшиты в критерии задач: DDL v24 (3 таблицы), 9 kill-switches поимённо, semantic map v1, Supervisor modes A/B/C + attempt-ceiling ≤4 HTTP, CoverageLedger, идемпотентность публикации, Inspector-карточки. AM-1…AM-6 закрыты (register ADR-1028-8). Спец-дыр GAP не обнаружено (см. PLANNING_CONSISTENT в конце). Owner-гейты вынесены в блок PENDING OWNER.

**Обязательная предпосылка (22351–22359):** Builder по ASAP 4.1 стартует **после** закрытия пост-ASAP-4 corrective pass'а (его deploy + production acceptance, T-4508–T-4510). Docs-планирование (этот Step 1) идёт параллельно и этому не мешает. Также: «Не превращать ASAP 4.1 в бесконечный redesign» (22361) — задачи без разрастания scope.

---

## Блок 0 — планирование

- [x] **T-4600 [@PM]** — Планирование эпика. **Критерий (выполнен):** созданы `requirements-map.md` (R6-xxx ↔ якоря ↔ проверяемые критерии, DoD 35/35 покрыт), `reuse-inventory.md`, `conflict-audit.md` (AM-1…AM-6) и `tasks.md` (этот файл); `current_task.md` не изменён. Далее — @Architect Step 2. DoD: —.

## Блок A — архитектура/контракты (@Architect)

- [x] **T-4601 [@Architect]** — Спека + ADR ASAP 4.1. **ВЫПОЛНЕН 03.10.2026:** `spec.md` + `adr-1028-8-durable-whole-window-summary.md` (Accepted); Supersede/AMEND register #1–#8 по факт-листу conflict-audit §1. Решения: D1 immutable SummarySourceWindow (SQLite `summary_source_windows`, v23→v24); D2 whole-window-first + capacity engine (цепочка §5, override → уровень 4 — AMEND ADR-1028-3); D3 L1 semantic map v1 (`too_many_facts` снят по построению, MAX_FACTS_PER_THREAD=30 → ceiling в FactPackage-синтезе через существ. `repair_capacity_overflow`); D4 Writer/Reviewer вход = Full SourceWindow, FactPackage — derived view (AMEND ADR-1028-7 зона D); D5 LLMExecutionSupervisor — scope только Summary, attempt-бюджет ≤4 HTTP на логический вызов, modes A/B/C, wall-clock не health-метрика — AMEND ADR-1024-6 (Summary-scope); D6 durable SummaryRun (`summary_runs` + `summary_run_stages`, НЕ task_jobs payload); D7 cover/text independence + Medved inheritance + capability registry; D9 настройки §51. **Критерий:** AM-1…AM-6 разрешены явно, prompt-миграция L1/Writer/Reviewer описана (D3/D4). DoD: 1–5, 7, 14, 17, 20. Зависимости: T-4600.
- [x] **T-4602 [@Architect]** — Контракт настроек и capacity-политик (§51). **ВЫПОЛНЕН 03.10.2026:** spec §8 таблица «ключ → уровень → описание»: L1_CHUNK_SIZE/L2_TIMEOUT/MAX_INPUT_CHARS/SUMMARY_CONTEXT_TOKENS — не создаются (test-контракт «нет новых admin-цифр»); `SUMMARY_LLM_HARD_DEADLINE_SECONDS`, `SUMMARY_LLM_INACTIVITY_SECONDS`, `SUMMARY_L1_MAP_MAX_TOKENS`, `SUMMARY_L1_HINT_MAX_CHARS`, `SUMMARY_SOURCE_WINDOW_RETENTION_DAYS` и др. — developer deep env-only; `limits.summary_hybrid_context_*`/`SUMMARY_MAX_WINDOW_MESSAGES`/`SUMMARY_MAX_CONTEXT_CHARS` demote; `models.chat_context_window_override` остаётся override-слоем 4. DoD: — (сквозное §51). Зависимости: T-4601.

## Блок B — Immutable SourceWindow + capacity engine (@Builder)

- [x] **T-4603 [@Builder]** — `SummarySourceWindow`: один канонический immutable source object на run (run_id, chat_id, window_from/to, source_message_count, messages[] с полным набором полей §2, включая forward metadata и media-derived text if already available). Создаётся один раз, не мутируется; производные стадии ссылаются по `run_id/source_ref`; после создания не строить новые «источники истины» из L1 JSON/FactPackage/XML. Без срезов `messages[:N]`/last N/50k/fixed token caps (§1). **Durable-носитель (ADR-1028-8 D1, spec A.1):** per-run row в новой SQLite-таблице `summary_source_windows` (run_id PK = correlation_id S7; messages_json immutable), additive DDL v23→v24, PostgreSQL no-op; write-once в стадии SOURCE_READY — единая точка создания сразу после SOURCE_WINDOW (summary_generator.py:500-512), до любой LLM-стадии; guard-тест: попытка UPDATE messages_json после создания = дефект; повторное чтение snapshot'а после «мутации» потребителя байт-идентично. Retention: удаляется только cleanup'ом по TTL `SUMMARY_SOURCE_WINDOW_RETENTION_DAYS` (env-only, default 7) после DONE/FAILED. Событие `SUMMARY_SOURCE_WINDOW_READY` с числами (R17). **Критерий:** юнит-тесты immutability/схемы/единой точки создания/write-once; retention-TTL тест; интеграция со `summary_generator.py`; kill-switch `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED` (default ON; OFF → snapshot не пишется, in-memory rows — бит-в-бит 2.58.46). Якорь 22426–22457, 22398–22422. DoD: 1. Зависимости: T-4601.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 2):** `services/summary_source_window.py` (immutable dataclass + build + persistence wrappers + TTL purge; summary_source_window.py:47/58/116/156/221/242/253); DDL v24 additive (database.py:866 `_SCHEMA_VERSION_SUMMARY_SOURCE_WINDOW`, :1773 MigrationStep, :2477 `_migrate_summary_source_window_v24`, :2615/:2649/:2672 save/get/purge — write-once INSERT без overwrite; UPDATE по таблице не существует ни в одной ветке — guard-скан-тест); единая точка создания сразу после SOURCE_WINDOW и empty-чек'а (summary_generator.py:522-537, метод `_establish_source_window` :603); событие `SUMMARY_SOURCE_WINDOW_READY` (pipeline_events.py:134; R17 — числа); retention TTL env-only default 7 (settings.py:926). Kill-switch `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED` (default ON; OFF → записи нет — бит-в-бит). PG no-op (SQLite-only SQL). Тесты: tests/test_summary_source_window_asap41.py (16: схема §2/frozen+deep-copy/readback байт-идентичен/write-once/UPDATE-surface guard/миграция v24+идемпотентность/TTL/env/kill-switch/единая точка+R17). Остаток (честно, зафиксирован): purge-гейт «после DONE/FAILED» в полном виде встанет вместе с durable `summary_runs` (зона F, T-4616) — Wave 2 удаляет только окна старше TTL-горизонта (7д) при старте run'а; Θ столбцов статуса в v24 нет (per-ADR D1-схема).
- [x] **T-4604 [@Builder]** — Capacity plan по реальному serialized prompt (§5–§6): перед LLM-вызовом собрать реальный payload (system prompt, source, semantic instructions, response schema, metadata, output reserve, provider framing overhead) → required_input/reserved_output/safety_margin/effective_context → решение WHOLE_WINDOW | CAPACITY_OVERFLOW. Capacity Resolver — source of truth с цепочкой приоритетов (АМЕНД ADR-1028-3, spec A.2): runtime discovery → provider metadata/catalog → project registry (`model_capacity.py` — уровень 3) → developer override (уровень 4, «По умолчанию»-профили) → conservative fallback; name-based карта не основной механизм (AM-2); lower-capacity сценарии — через конфиг-фикстуру модели/каталога, а не override поверх живого каталога. Статические бюджеты `limits.summary_hybrid_context_*` теряют роль триггера стратегии; остаются только в OFF-паритет-пути `budget_mode=legacy_static`. **Критерий:** тесты resolver-приоритетов; тест payload-учёта (оценка не по одному `message.text`); Inspector-поля заложены (R6-G-002); kill-switch `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED` (default ON; OFF → текущий контур 2.58.46 с planning-estimate sharding волны C — байт-в-бит). Якорь 22504–22605. DoD: 2, 3. Зависимости: T-4601, T-4603.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 2):** Цепочка приоритетов §5 дословно в расширении `model_capacity.py` (AMEND AM-2: override уровень 4 — model_capacity.py:777-805 `_resolve_uncached`; runtime→catalog→registry→override→fallback); решение по ФАКТИЧЕСКОМУ serialized prompt: `decide_summary_mode` (model_capacity.py:935, формула required+reserve ≤ effective) + Inspector-поля в `SummaryCapacityPlan` (:906, as_event_counts); фактический serialized учёт в `run_l1_capacity_first` (summary_l1_clusterizer.py:1298 — build_l1_payload ПОЛНОГО окна + _serialized_len, тот же токенизатор, что pack_l1_input; контрпример «только message.text» покрыт тестом serialized_len > 20×text_only); WHOLE_WINDOW = РОВНО 1 запрос без pack-эвикций (никаких messages[:N]); allowance ресолвится единой точкой `resolve_l1_effective_budget` (manual cap §137 = размер ОДНОГО сегмента; static — не триггер стратегии, только allowance OFF-паритета). События `SUMMARY_CAPACITY_RESOLVED`/`SUMMARY_EXECUTION_MODE_SELECTED` (pipeline_events.py:150/:163, reason-коды через mca_events.REASON_CODES — fits_effective_context/serialized_payload_exceeds_effective_context). Kill-switch master `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED` (settings.py:920, default ON; OFF → прежний контур байт-в-бит, capacity-снапшот не пишется — тест). Тесты: tests/test_summary_capacity_asap41.py (19: цепочка 4 приоритета/singleton-учёт§6/§44-A WHOLE_WINDOW 1 запрос 100% coverage/Inspector-поля/events R17/master-OFF). Прочие существующие override-тесты AMEND'нуты под уровень 4 (test_capacity_resolver_asap31.py, test_capacity_nanogpt_asap32.py — по директиве владельца §5).
- [x] **T-4605 [@Builder]** — Capacity cache + fallback re-plan (§7, §27–§28): ключ кеша = provider + base_url + model + capability fingerprint (Δ против ADR-1028-3); инвалидация при смене модели/base_url/provider; runtime 400/context-length → переоценка в рамках run (событие `SUMMARY_CAPACITY_RESOLVED` с причиной). При provider/model fallback — resolve fallback capacity → compare required input: вмещает → same whole-window task; меньше → CAPACITY_OVERFLOW plan без потери coverage; больше → допустим переход на whole-window, если run ещё не создал сегментные артефакты (§44-E, не ломаем созданный run); семантика задачи (window/coverage/style/completeness) неизменна. **Критерий:** тесты смены модели (§44-C) и fallback-конфигураций (§44-D/E); событие `SUMMARY_EXECUTION_MODE_SELECTED` с причиной. Якорь 22577–22604, 23110–23156. DoD: 3, 4. Зависимости: T-4604.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 2):** Кеш: capability fingerprint в ключе (model_capacity.py:641 `_capability_fingerprint` = provider+endpoint-дескриптор; `_cache_key` :679 — provider+host+model+override+fingerprint; смена любого компонента = промах, точечная `invalidate_runtime_capacity` :665 для runtime 400/context-length — тройка суверенна от fingerprint/override). Событие `SUMMARY_CAPACITY_RESOLVED` — с причиной/window_source/segments (summary_l1_clusterizer.py:1260-1302 → pipeline_events.py:150). Re-plan API §44-D/E: `replan_summary_capacity` (model_capacity.py:974) — вмещает → same whole-window; меньше → CAPACITY_OVERFLOW; больше → переход на whole-window ТОЛЬКО если run ещё не создал сегментные артефакты (иначе reason=`segment_artifacts_exist`, не ломаем созданный run). Тесты: tests/test_summary_capacity_asap41.py §44-C (смена модели новый ключ+авто strategy re-plan), §44-D (fallback 16384 → overflow), §44-D2 (fallback вмещает → whole-window), §44-E (апгрейд gated артефактами), never-raises на network-down (fail-open → fallback window). Supervisor-врезка re-plan'а в fallback-каскад — зона D (T-4612), здесь API+контракт+tests.
- [x] **T-4606 [@Builder]** — CAPACITY_OVERFLOW: иерархический lossless overflow (§8–§10) — Full SourceWindow → capacity-aware segmentation (переиспользование `_partition_lossless`, summary_l1_clusterizer.py:927-964) → segment semantic maps → merge (`summary_semantic_reduction.py` REUSE) → Writer stages; отдельный понятный режим, не обычный flow; **CoverageLedger (ADR-1028-8 D2.4):** `source_message_ids / segment_assignments / processed_ids / fallback_ids / missing_ids`, инвариант XOR-покрытия (каждое сообщение ∈ ровно ≥1 сегмента, дедуп overlap по stable ID); перед Writer coverage == 100%, иначе восстановление сегмента (re-run только проблемного) или честный degraded (не «success»); L1-запросов = число сегментов. Потеря сообщений запрещена. **Критерий:** тест §44-B (32k, все covered, no truncation); ledger-инварианты (XOR-покрытие); fixture «сегмент упал» → restore/честный degraded; kill-switch `SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED` (default ON; OFF → текущий lossless-chunking контур 2.58.46). Якорь 22607–22678. DoD: 5, 6. Зависимости: T-4603, T-4604.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 2):** CAPACITY_OVERFLOW-режим как отдельная ветка capacity-first (summary_l1_clusterizer.py:1425-1458): full SourceWindow → `_partition_lossless` по фактическому serialized размеру (REUSE, overlap=1, oversized verbatim §121-§123) → L1 на каждый сегмент (запросов = сегментов; restore = re-run только проблемного, ровно 1 попытка, :875-890) → merge (`merge_l1_payloads` + `repair_capacity_overflow` REUSE) → coverage/Ledger-gate до Writer-стадий зоны B. **CoverageLedger** — новый чистый модуль `services/summary_coverage_ledger.py` (source/segments/processed/fallback/missing; XOR-инвариант assignments==source; дедуп overlap по stable ID через `stable_message_id`). Честный degraded: missing>0 ИЛИ fallback>0 → error_result (NOT «success», скан :989-1014) + событие `SUMMARY_SEGMENT_LEDGER` WARN с честными counts (pipeline_events.py:177-196); события `SUMMARY_SEGMENT_PLAN/_RESULT` (:169/:181). Kill-switch `SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED` (settings.py:922; OFF → прежний lossless-chunking `_run_l1_lossless` байт-в-бит — тест). Тесты: tests/test_summary_coverage_ledger_asap41.py (10: XOR-инварианты/missing fail-closed/ stranger-ids/снапшот R17/§44-B все covered no truncation/«сегмент упал» → restore/«сегмент упал навсегда» → честный degraded/контрпример «взять 300» невозможен по построению auto-unassigned). Остаток (честно): partial-deterministic minimal maps (успевшие сегменты сохраняются при невосстановимом) — зона B (T-4608); hierarchical Writer по сегментам с ledger-покрытием — зона C (T-4609); Wave 2 ограничивается lossless-ошибкой → LEVEL-2 ladder по полному набору.

## Блок C — L1 / Writer / Reviewer (@Builder)

- [x] **T-4607 [@Builder]** — L1 = компактная semantic map (§12; ADR-1028-8 D3): контракт **semantic map v1** — `{schema_version, topics[] (topic_id, title, message_ids[], participants[], short_hint ≤160), events[] (kind ≤32 симв., message_ids[]), relationships[] (optional), unassigned_message_ids[] — обязательное поле}`; текст/timestamp/author/reply materialize детерминированно из SourceWindow (по run_id/source_ref); source payload НЕ дублируется в L1 output. Компактность-бюджеты: `topics ≤ MAX_THREADS (100)`, `title ≤ TOPIC_MAX (200)`, `hint ≤ SUMMARY_L1_HINT_MAX_CHARS (160)`, `map ≤ SUMMARY_L1_MAP_MAX_TOKENS (default 6000)` — все env-only; переполнение → **deterministic compaction** (merge мелких тем по пересечению message_ids, дедуп, обрезка hints) + статус `map_degraded` в `L1_RESULT`; **никогда не whole-run invalid и не «гильотина»**: sharding карты — fallback последней инстанции с полным покрытием message_ids. `MAX_FACTS_PER_THREAD=30`/`MAX_FACTS_TOTAL=1000` — structural ceiling в детерминированном синтезе FactPackage (T-4609, `repair_capacity_overflow`), НЕ валидатор L1 — «31 факт → invalid whole L1» невозможен по построению. **Prompt-миграция L1 явная** (прецедент R4-D-003): `SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT` переписывается под map-схему одним коммитом «код+эталон+тесты», старый промпт помечается superseded (ADR-1028-8 D3). **Критерий:** тест «в L1 output нет текстов сообщений»; fixture плотного окна 839 → компактная map; schema-контракт topics/events/relationships/unassigned_message_ids; budget/compaction-тесты; kill-switch `SUMMARY_L1_SEMANTIC_MAP_ENABLED` (default ON; OFF → L1 держит контракт §95-v2 с too_many_facts-валидацией — бит-в-бит 2.58.46, chunking-триггер остаётся planning estimate). Якорь 22708–22741. DoD: 7. Зависимости: T-4603, T-4606 (для overflow-ветки), T-4601.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 3):** контракт map v1 — новый чистый
  модуль `services/summary_l1_semantic_map.py` (validate/compact/merge/
  correction; summary_l1_semantic_map.py:141 MapResult, :186 validator,
  :350 compact, :534 merge, :625 minimal_map); L1Result аддитивен
  (map_degraded/map_reason/map_stats, summary_l1_contract.py:191–232);
  врезка в run_l1 — `_map_mode` (только capacity-first ветка; OFF/legacy
  пути байт-в-байт, summary_l1_clusterizer.py:1840 map-ветка, _RETRYABLE +
  map-коррекция :1976); бюджеты env-only (`SUMMARY_L1_HINT_MAX_CHARS`/
  `SUMMARY_L1_MAP_MAX_TOKENS`, settings.py:942–948; topics≤100/title≤200 —
  числа §0.4 не меняются); compaction ladder (trim → intersect-merge →
  pairwise → relationships drop → hints clear → merge; никогда не invalid,
  ids не теряются) + честный `map_degraded`; Prompt-миграция: канон L1
  «semantic map v1» (R1030, summary_prompts.py:422) — код+эталон
  (plans/docs/canon/architecture.md, байт-идентичность — test_canon_doc_)
  + тесты одним изменением; старый прод-канон = superseded
  `PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41` (+ FORWARD/ROLLBACK ступени
  prompt_migrations). Kill-switch `SUMMARY_L1_SEMANTIC_MAP_ENABLED`
  (settings.py:937; OFF → §95-v2 + too_many_facts — тест
  test_run_l1_kill_switch_off_keeps_v2). Тесты:
  tests/test_summary_semantic_map_asap41.py (27) — контракты/compaction/
  correction/минимальные карты/overflow-partial; golden «31+ факт-класс» —
  tests/test_summary_golden_839_asap41.py (839 synthetic, WHOLE_WINDOW,
  1 L1-запрос, coverage 100%, run жив — слишком урезанный FactPackage
  невозможен, синтез в T-4609). Остаток (честно): Inspector-карточки map_
  degraded — зона G (T-4621/4622), событие читает counts из L1_STAGE.
- [x] **T-4608 [@Builder]** — L1 fail-soft + partial success (§13–§14): timeout/provider unavailable/malformed/invalid → Writer всё равно получает Full SourceWindow + instruction «semantic map unavailable — structure source yourself»; `L1 failed ≠ Summary failed`; в CAPACITY_OVERFLOW успешные maps сохраняются, проблемный segment — deterministic minimal map (структурная заготовка из ledger). Не превращать 3/4 success в 0/839. **Переход на урезанный Legacy из-за L1 запрещён** (§48 Run 1: 23700–23701); LEVEL-2 цепочка «L1 непригоден → fallback package → L2» перестраивается: fallback-package становится опциональной derived view (AM-5), не обязательным путём выживания. **Критерий:** тесты §46 (L1 total failure → Writer с полным окном, Summary завершается без перехода на урезанный Legacy) и partial-success fixture; событие `L1_RESULT` с честным result: failed при сохранном покрытии (Inspector не показывает «L1 ok» рядом с failed, R6-G-001); kill-switch OFF ветка возвращает существующую LEVEL-2 механику (L1_FALLBACK_PACKAGE) байт-в-бит. Якорь 22743–22796. DoD: 8. Зависимости: T-4603, T-4607.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 3):** L1 total failure → writer
  source-ветка (summary_generator.py `if not l1_result.usable` → writer_
  source путь; LEVEL-2 фоллбек-package — опциональная derived view, не путь
  выживания; instruction «semantic map unavailable — structure source
  yourself» в Writer-входе — build_l2_source_input(map_unavailable=True));
  переход на урезанный Legacy из-за L1 ЗАПРЕЩЁН (предохранитель — guard не
  прыгает в Legacy при writer_source ON; тест
  test_l1_failed_writer_source_no_legacy) — Legacy-fallback сохраняется для L2-фейлов
  (санкция). CAPACITY_OVERFLOW partial success: невосстановимый сегмент →
  deterministic minimal map (`minimal_map_for_rows`) через ledger; события
  честные: SUMMARY_SEGMENT_FAILED≠ok перед описанием минимальной карты
  (clusterizer reorder), SUMMARY_SEGMENT_MINIMAL_MAP WARN, L1_RESULT
  map_degraded + SUMMARY_L1_STAGE counts (pipeline_events.l1_stage
  counts-параметр). OFF-ветка (`SUMMARY_L1_SEMANTIC_MAP_ENABLED=false`) —
  прежняя LEVEL-2 механика байт-в-байт (тесты wave-3 включены в golden;
  существующие not-marked тесты = OFF-паритет через conftest). Тесты:
  test_summary_semantic_map_asap41.py::overflow_* и golden (run жив при
  непокрытых раскопках).
- [x] **T-4609 [@Builder]** — Writer видит оригинал (§15–§16; ADR-1028-8 D4): WriterInput = source_window (обязателен; serialized §92 без срезов) + semantic_map? + fact_view? + optional memory/context + target_style + target_extent; FactPackage — derived view (analytics/debug/Reviewer/memory/fallback/compat), `summary_fact_package.py` не удаляется; синтез детерминированный (SourceWindow + semantic_map → package), потолки MAX_FACTS_* применяются здесь через существующий `repair_capacity_overflow` (summary_l1_capacity.py:173-318, без изменений); Writer не зависит от степени урезания FactPackage; prompt-миграция явная (AM-4): `build_l2_input` расширяется секцией source window + инструкция «пакет фактов — вспомогательный индекс, оригинал — истина», prose-first канон ADR-1028-7 D4 сохраняется. **Capacity-aware Writer (CAPACITY_OVERFLOW):** если full window не влезает в Writer-модель — иерархический Writer (per-segment source+map → сегментные черновики → merge-pass c бюджетом; покрытие по ledger, evidence_message_ids абзацев объединяются); в WHOLE_WINDOW — один вызов с полным окном. **Критерий:** контракт-тест WriterInput; тест: Writer работает на полном окне с урезанным/отсутствующим FactPackage; §47-сценарий «Structurer пропустил — Writer восстановил»; kill-switch `SUMMARY_WRITER_SOURCE_INPUT_ENABLED` (default ON; OFF → FactPackage-центричный вход, бит-в-бит 2.58.46). Якорь 22798–22849. DoD: 9, 11. Зависимости: T-4603, T-4608.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 3):** WriterInput — `build_l2_
  source_input` (summary_l2_writer.py:536: ИСТОЧНИК-секция §92 полная +
  SEMANTIC MAP + map-unavailable инструкция + length-блок «мягкий
  ориентир», реиспользованный length-блок `_length_block`); `run_l2`
  аддитивен (`source_input=`, `length=`; пакет — только валидация
  id-space/evidence, summary_l2_writer.py:1200+); derived view — новый
  чистый модуль `services/summary_fact_view.py` (`build_fact_view_from_map`:
  fragments materialize/chronology/roster; потолки MAX_FACTS_* через
  существующий `repair_capacity_overflow` по §95-проекции — для map-синтеза
  фактов нет → no-op; coverage пакета == 100% окна; срезы сегментов
  slice_map_for_ids/slice_package_threads/fallback_view_for_items/
  ensure_full_id_space); capacity-aware Writer — `_run_writer_source_stage`
  (summary_generator.py: fits → 1 вызов; не fits → иерархический Writer
  per-segment (lossless `partition_lossless`) → merge-pass
  (`build_writer_merge_input`, LLM-merge с fallback на детерминированную
  склейку — никогда не выбрасывает; честный вит-маркер (L2_WRITER_HIERARCHICAL)
  L2_WRITER_HIERARCHICAL + review-skip как у paged-прецедента);
  prompt-миграция явная: канон L2 R1030 (блок ИСТОЧНИК «оригинал —
  истина», «пакет фактов — ВСПОМОГАТЕЛЬНЫЙ ИНДЕКС», «semantic map
  отсутствует — структурируй источник сам») — код+эталон+тесты; старый
  канон R1029 = superseded `PREV_SUMMARY_L2_WRITER_R1029_ASAP41`
  (+ FORWARD/ROLLBACK). Kill-switch `SUMMARY_WRITER_SOURCE_INPUT_ENABLED`
  (settings.py:940; OFF → run_l2 без source_input + канон R1029 — тест
  test_off_run_l2_content_is_package_input). §47-сценарий: writer
  восстанавливает пропущенное Structurer'ом (test_writer_restores_omitted_
  by_structurer). Тесты: tests/test_summary_writer_source_asap41.py (18),
  включая иерархический Writer (writer_segments≥2, merge). Остаток (честно):
  Writer-провал сегмента → LEVEL-3 (санкция контура, как ранее L2-фейл).
- [x] **T-4610 [@Builder]** — Reviewer видит оригинал + сохранение bounded revision (§17–§19): ReviewResult = Draft + Full SourceWindow + SemanticMap (не только L1/FactPackage); проверка attribution/quote attribution/people identity/numbers-dates/reply context/major topic omission против реального source. **CAPACITY_OVERFLOW Reviewer:** полный window если влезает, иначе evidence-slices (paragraph `evidence_message_ids[]` + reply-контекст, разворачиваемые детерминированно из SourceWindow) + segment maps для completeness-проверки — никогда только FactPackage. Bounded revision ASAP-4 (макс 2 semantic iteration, targeted revision, patch-контракт `replace_paragraphs`, progress criterion — ADR-1028-7 D3/D5) и prose-first/quote policy (§19) — без изменений, регресс зелёный; quote repair ladder сохраняется, резолв цитат против SourceWindow (extension MCA-22 D3, не fork). **Критерий:** тест §47 (Reviewer ловит wrong speaker, отсутствовавший в FactPackage — R6-B-007); регресс R4-D-024/R4-D-003 зелёные; kill-switch `SUMMARY_L2_REVIEW_ENABLED=false` → прежний single-call L2 → Legacy, бит-в-бит. Якорь 22851–22927. DoD: 10. Зависимости: T-4609.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 3):** ReviewResult = Draft + Full
  SourceWindow + SemanticMap — run_l2_with_review аддитивен
  (writer_source_input/writer_length/semantic_map/source_window_content/
  evidence_slices/review_full_window/review_payload_items/source_message_
  ids); build_review_content/build_revision_content — секции source_window/
  semantic_map/evidence_slices (revision тоже сверяется с оригиналом);
  system-канон Reviewer + блок ИСТОЧНИК (append при переданном source,
  SUMMARY_L2_REVIEWER_SOURCE_BLOCK — без миграции PG, канон-константа не
  меняется); CAPACITY_OVERFLOW — evidence-slices (`build_review_evidence_
  slices`: evidence_message_ids абзаца + reply-контекст — детерминированно
  из SourceWindow; никогда только FactPackage); R6-B-007 fixture:
  wrong speaker доказывается из окна — id-space ReviewResult = пакет ∪
  окно (`ensure_full_id_space(package, source_message_ids)` в
  run_l2_with_review; нужные refs валидны), находки без refs/с выдуманным
  ID — отбрасываются (контакт §50.11 в силе — test_finding_without_refs_
  rejected). Bounded revision ×2 / patch-контракт replace_paragraphs /
  progress criterion / budget ≤6 — БЕЗ изменений (test_bounded_revision_
  and_budget_untouched), quote repair ladder не тронут. Kill-switch
  `SUMMARY_L2_REVIEW_ENABLED=false` → single-call L2 (бит-в-бит;
  test_review_off_generator_single_call). Тесты:
  tests/test_summary_reviewer_source_asap41.py (12). Остаток (честно):
  резолв цитат «против SourceWindow» усиливает существующий quote-repair
  путь (quote repair ladder) — детальный quote-фича-тест не расширялся (MCA-22 extension
  остаётся прежним).

## Блок D — Legacy и output (@Builder)

- [x] **T-4611 [@Builder]** — Legacy от SourceWindow + output length (§31–§33; EXTEND ADR-1028-7 D7.3): Legacy начинает с SummarySourceWindow (source_ref) — тот же snapshot с Hybrid; запрещён hard cap 50000 → stop; фиксированные капы `SUMMARY_MAX_WINDOW_MESSAGES`/`SUMMARY_MAX_CONTEXT_CHARS` больше НЕ триггер «стоп» — ветка capacity-aware: Legacy-модель вмещает → one request (плоский XML на малых окнах остаётся бит-в-бит), нет → CAPACITY_OVERFLOW hierarchical legacy (reduction `summary_semantic_reduction` REUSE) со 100% coverage; coverage <100% → честный degraded, не молча. `MAX_SUMMARY_PARTS` — только Legacy-выходные chunks (не input/L1/L2/Rich); готовый текст не обрезается алгоритмически (soft semantic target для Writer; hard limit только API/transport/runaway; длинный plain → split delivery без потери tail). **Критерий:** тест §31-обеих веток; 50k-stop недостижим (dead-path проверка `summary_xml.py:76`); регресс R4-C-007/008/010 + hybrid budget-тест; split-delivery тест; kill-switch `SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED` (default ON; OFF → текущий контур Legacy full-window 2.58.46, включая действующие капы окна, байт-в-бит). Якорь 23202–23269. DoD: 12, 13. Зависимости: T-4603.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 3):** Legacy от SummarySourceWindow
  — `_run_legacy_pipeline` (summary_generator.py:1113): `lfw.
  load_legacy_rows(db, run_id)` → строки окна из immutable snapshot
  (source_ref; fail-open к переданным rows); `snapshot_rows`/`load_legacy_
  rows` (summary_legacy_fullwindow.py:295/:325 — обратная материализация).
  Капы окна: XmlGroundingBuilder.build(window_caps=...) —
  (None,None) → капы ОТПУЩЕНЫ (ON-ветка); None → прежние капы (OFF
  байт-в-байт, включая 50k-stop: dead-path в ON не достижим; test_off_
  caps_stop_byte_identical / test_caps_no_longer_stop_on_zone_c_on).
  Capacity-aware ветка: `_legacy_capacity_fits` → (а) вмещает → один
  запрос (плоский XML полный, static caps-срез не применяется);
  (б) не вмещает → `_run_legacy_hierarchical` — lossless `_partition_
  lossless` + build_fallback_package per-segment + REUSE
  `reduce_threads` (summary_semantic_reduction) + REUSE paged-лестницы;
  coverage честно (100% или <100% → ctx.health degraded +
  ``LEGACY_COVERAGE_DEGRADED``, не молча); (в) провал сегмента — событие
  виден. Output: `_deliver_plain(split_delivery=True)` на ON — чанки без
   потери хвоста (MAX_SUMMARY_PARTS — только output chunks/soft target
  промпта, max_symbols = parts×4000−200 unchanged); OFF = прежний кап
  (`_cap_legacy_chunks`). Kill-switch `SUMMARY_LEGACY_SOURCE_WINDOW_
  ENABLED` (settings.py:941; OFF → контур 2.58.46 с действующими капами —
  тесты). Тесты: tests/test_summary_legacy_source_window_asap41.py (11).

## Блок E — LLMExecutionSupervisor (@Builder)

- [x] **T-4612 [@Builder]** — Supervisor core (§22–§23; ADR-1028-8 D5, AM-3): один Supervisor владеет request_id/provider/model/operation/started_at/last_activity_at/state/attempt/fallback и единолично управляет retry/fallback/deadline; убрать вложенные stage × client × provider × fallback retry-циклы (scope = Summary-пайплайн only; Direct/STT/image/embeddings/lore не трогаются — их LLM_TIMEOUT/каскады как сегодня). **Attempt-математика (посчитано, spec D.2):** сегодня ≤6 HTTP на логический вызов (3 primary × 3 fallback) × L1 correction ≤2 → ≤12; контракт — **≤4 HTTP на логический вызов** (1 primary + ≤1 primary-transport-retry + ≤1 fallback-provider + ≤1 fallback-transport-retry), задокументирован и закреплён тестом; логические бюджеты стадий сохраняются (ADR-1028-7 D3.3): L1 ≤2 (вкл. semantic correction retry), L2 ≤6 — transport-ретраи в них не входят. Транспорт — существующий per-call контракт `llm_client._post(budget=, max_retries=, retry_statuses=)`: для Summary-вызовов `max_retries=1`, `retry_statuses=()` (статус-ретраи решает Supervisor), fallback-каскад llm_client для Summary-канала выключен (LLM_FALLBACK_* остаётся прочим потребителям). **AMEND ADR-1024-6:** wall-clock `LLM_TIMEOUT`/`LLM_TOTAL_BUDGET` перестают быть health-критерием для Summary-пути. Паттерн-донор — `media_execution.py` (MediaExecutionPolicy/JobState) + executor-прецедент `embedding_control_plane.py`. **Критерий:** тест «один logical запрос → ровно один attempt-бюджет ≤4 HTTP» (верхняя граница задокументирована, прецедент R4-D-057); инспекция отсутствия вложенных циклов; kill-switch `SUMMARY_LLM_SUPERVISOR_ENABLED` (default ON; OFF → Summary-вызовы через прежний llm_client-контур, бюджеты/каскады 2.58.46, байт-в-бит). Якорь 22979–23020. DoD: 14, 17, 18. Зависимости: T-4601.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 4):** новый модуль `services/summary_llm_supervisor.py` — единый владелец (SupervisedCallState :367; execute_supervised :683; attempt-потолок ATTEMPT_CEILING_HTTP=4 :72, PRIMARY/FALLBACK ≤2+≤2; transport_contract :413 — нижний слой только transport max_retries=1/retry_statuses=()/per-call budget+timeout+supervised-метка). Транспорт: `llm_client.generate(..., supervised_transport=)` (:1040/:1083-1103 — per-call контракт в `_post`, ВНУТРЕННИЙ fallback-каскад выключен для supervised-канала; байт-в-бит для прочих потребителей), `_post(..., timeout=, budget_reason_label=)` (:685+, per-request transport-окно), `_post_fallback(..., timeout=)` (:917). Fallback-решение Supervisor'а (§27): capacity re-plan `replan_summary_capacity` — вмещает → тот же whole-window payload; меньше → oversized-отправка ЗАПРЕЩЕНА (честный отказ + capacity-событие, причина `fallback_capacity_smaller`); runtime 400/404/413 → `invalidate_runtime_capacity` + событие. Врезка: `_make_llm_call` L1 (summary_l1_clusterizer.py:1217/:1228), Writer/Reviewer/Revision (`summary_l2_writer.py:1093/:1101` + `summary_l2_review.py` operation-метки), Legacy/Single/Two-call (`summary_generator.py:2751 _supervised_generate` — retry-once стадийный сохранён как ЛОГИЧЕСКИЙ бюджет). OFF → wrap-врезка вертает None = прежний канал байт-в-бит (тест). Тесты: tests/test_summary_supervisor_asap41.py (32) — потолок ≤4 РЕАЛЬНЫМ подсчётом httpx.AsyncClient.post (4 при вечном transport-фейле; 2 при статус-500 без статус-ретрая; 3 при fallback), контракт primary-ноги, каскад generate выключен, OFF-parity. Остаток (честно): `http_attempts` в state — верхняя граница ноги (≤2); точный подсчёт — transport-тест.
- [x] **T-4613 [@Builder]** — Execution modes + capability discovery (§24, §26): Mode A async job (submit→queued→processing→completed, polling; живой status = живой запрос), Mode B streaming (last token/event/keepalive → last_activity_at; не убивать по elapsed; inactivity/stall detection), Mode C sync opaque (adaptive watchdog как последний рубеж). Адаптеры честно декларируют supports_streaming_liveness / supports_async_status / supports_cancel / opaque_sync_only; «пинговать генерацию» выдуманным endpoint запрещено. **Честная база (honest posture):** текущий llm_client — sync-opaque → Mode C реализуется сразу; Mode A/B — контрактные слоты, активируемые ТОЛЬКО при верифицированном провайдер-адаптере (прецедент `EMBED_ASYNC_BATCH_ENABLED` default OFF до live-верификации; live-верификация — owner-гейт, см. блок PENDING OWNER); декларации в Inspector отражают фактическое состояние (не «stream ✓» при sync-транспорте). **Критерий:** декларации всех затронутых провайдеров; тест: режим Supervisor'а следует декларации; отсутствие выдуманных ping-вызовов; kill-switch общий `SUMMARY_LLM_SUPERVISOR_ENABLED`. Якорь 23022–23108. DoD: 15, 16. Зависимости: T-4612.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 4):** `declare_execution_capabilities` (summary_llm_supervisor.py:108) — честная декларация из РЕАЛЬНОГО транспорта: sync-opaque POST /chat/completions → opaque_sync_only=True, streaming/async/cancel=False, source=sync_transport_observed (реестр верифицированных адаптеров пуст — «stream ✓» невозможен); `select_execution_mode` (:134) — режим следует декларации: слоты Mode A (`SUMMARY_LLM_ASYNC_MODE_ENABLED`, default OFF)/Mode B (`SUMMARY_LLM_STREAMING_MODE_ENABLED`, default OFF) требуют И флага, И верифицированной декларации; флаги без адаптера → Mode C (тест). No-ping тест: за логический вызов РОВНО HTTP попыток (1), только /chat/completions. События: SUMMARY_L1_ACTIVITY/SUMMARY_WRITER_ACTIVITY/SUMMARY_LLM_SUPERVISOR (pipeline_events.py:47-49/:235) несут mode/декларации (Inspector зоны G читает). Mode C честная база реализована в execute_supervised; живой длинный запрос не убивается wall-clock (adaptive дедлайн от телеметрии). Live-верификация Mode A/B — PENDING OWNER (PO-4, T-4613-гейт): слоты контрактуальны, эмитят честные декларации.
- [x] **T-4614 [@Builder]** — Adaptive watchdog + hard deadline fuse + telemetry (§25, §29): hard deadline — developer-level `SUMMARY_LLM_HARD_DEADLINE_SECONDS` (default большой, clamp [600, 7200], env-only), зависит от operation/model/input, только аварийная защита; unhealthy = нет подтверждённой активности/provider stalled, не «прошло N секунд»; inactivity threshold `SUMMARY_LLM_INACTIVITY_SECONDS` (clamp [60, 900]) + cold defaults `SUMMARY_LLM_*_COLD_DEFAULTS` (ttfa/generation per mode); adaptive latency telemetry по provider/model/operation/token-бакетам (queue time, time-to-first-activity, generation duration, tokens/sec, failure rate) питает watchdog — percentile-оценщик строится ТОЛЬКО по успешным длительностям (REUSE `media_execution.resolve_windows`); телеметрия process-local + в stage-events (R17-safe); единого глобального timeout-числа нет. **Критерий:** тесты §45 (long streaming не убивается; stalled → cancel/fallback; opaque → watchdog + finite fallback); телеметрия по бакетам в событиях. Якорь 23068–23108, 23159–23185. DoD: 14. Зависимости: T-4613.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 4):** hard fuse `SUMMARY_LLM_HARD_DEADLINE_SECONDS` (default 3600, clamp [600,7200], settings.py:976; developer deep, Δ каталога=0 — F8 pass) — последний рубеж, не health-метрика (AMEND ADR-1024-6: LLM_TIMEOUT/LLM_TOTAL_BUDGET для Summary-пути больше не health-критерий — supervised-нога ходит со СВОИМ per-call budget/timeout). Inactivity `SUMMARY_LLM_INACTIVITY_SECONDS` (default 300, clamp [60,900], :978) + cold defaults per mode `SUMMARY_LLM_COLD_{TTFA,GENERATION}_{SYNC,ASYNC,STREAM}_SECONDS` (:980-988). Adaptive: `record_outcome` (:223) → оценка ТОЛЬКО по успешным длительностям p95×safety per (provider, model, operation, token-bucket) — REUSE паттерна media_execution.resolve_windows/percentile; `resolve_attempt_deadline` (:260) never-raises. Watchdog-поллер РЕАЛЬНЫЙ: `_run_with_watchdog` (:632) + `evaluate_watchdog` (:389) — streaming-ветка (stall по неактивности, elapsed НЕ убивает), sync-ветка (attempt-дедлайн от старта попытки — честный эквивалент неактивности opaque-транспорта), stall → cancel → LLMTimeoutError → finite fallback (§45). Telemetry: ttfa/queue/duration/timeouts/failures process-local (bounded 256 ключей×32 сэмпла) + события SUMMARY_L1_ACTIVITY/SUMMARY_WRITER_ACTIVITY (bucket-deadline_source-ttfa_ms-http_attempts; R17-скан тестом); timeout/failure НЕ обучают оценщик (тест). Единого глобального timeout-числа нет (per attempt-бюджет от телеметрии). Тесты: cold/adaptive/клампы/watchdog-ветки/stall→finite-fallback/fuse-триппинг/бакеты в событиях (в test_summary_supervisor_asap41.py, TestWatchdog). Полные §45-прогоны (streaming/async) — контрактные слоты (T-4626 после live-верификации PO-4).
- [x] **T-4615 [@Builder]** — Rename `total_budget_exceeded` (§30): time/retry budget → `execution_deadline_exceeded` (fuse) / `retry_time_budget_exhausted` (исчерпание попыток) — имена зафиксированы ADR-1028-8 D5.6; `budget` не должен выглядеть как денежный balance; точка эмиссии — llm_client.py:858-874 для Summary-канала (через Supervisor) + события Summary; совместимость старых логов — **read-side alias only** (`map_reason` в pipeline_events.py:58-67 + human-переводы Analytics), новых эмиссий старого кода нет; для не-Summary потребителей llm_client старый лог остаётся (их контракт не трогается). **Критерий:** тест: новый reason эмитится в deadline/budget-фикстурах; старый код не появляется в новых событиях; kill-switch общий `SUMMARY_LLM_SUPERVISOR_ENABLED` (OFF → прежние логи байт-в-бит). Якорь 23187–23199. DoD: 19. Зависимости: T-4614.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 4):** точка эмиссии — `llm_client._post` (supervised-метка `budget_reason_label="summary_supervised"`): fuse-ветка asyncio.TimeoutError → `execution_deadline_exceeded` (llm_client.py:880-885), исчерпание попыток по времени → `retry_time_budget_exhausted` (:894-899); не-Summary потребители (метка None) — прежние строки total_budget_exceeded/budget_exhausted байт-в-бит (тест). Supervisor'а финал: fuse-триппинг → execution_deadline_exceeded; попытки исчерпаны (primary+fallback, fuse не тронут) → retry_time_budget_exhausted (честные события; тест). Reason-коды в словаре `mca_events.REASON_CODES` (+4: execution_deadline_exceeded/retry_time_budget_exhausted/provider_stalled/fallback_capacity_smaller, mca_events.py:199-203). Read-side alias only: `pipeline_events._REASON_MAP` (:67-68) переводит старые строки старых логов под новые коды; Analytics human-описания — `pipeline_analytics.REASONS_RU` (:137-145, по-русски; старый код НЕ ключ новых эмиссий — тест). Kill-switch общий: OFF → supervised-метки не ставятся, прежние строки байт-в-бит (тест).

## Блок F — Durable SummaryRun (@Builder)

- [x] **T-4616 [@Builder]** — Persistent `SummaryRun` (§20; ADR-1028-8 D6): **носитель — dedicated additive SQLite-таблицы v24 `summary_runs` (run_id PK stable, chat_id, state, manual, window_from/to, source_ref, publication_status/publication_result_ref, pipeline_health, created/updated_at) + `summary_run_stages` (append-only §50.54: status/started_at/last_activity_at/finished_at/attempt/provider/model/result_ref/failure_reason)**; PostgreSQL no-op. State machine: CREATED/SOURCE_READY/STRUCTURING/STRUCTURE_READY/WRITING/REVIEWING/TEXT_READY/BASE_COVER/STYLE_EDIT/PUBLISHING/DONE/DEGRADED/FAILED. **НЕ task_jobs payload** (L-EXTRA-6 не наследуется: checkpoint run-state в `summary_runs`, а не в payload-колонке) и НЕ перегрузка `mca_pipeline_runs` (тот остаётся root-lifecycle/heartbeat mca-17a); task_jobs (v14) — execution-носитель (heartbeat/fencing/resume очереди, TaskJobStore); стабильный `summary_run_id` создаётся один раз и персистится (L-EXTRA-7 закрыт; cover-джоба уже ключуется от run_id, cover_style_jobs.py:566-573). Интеграция с `summary_run_log.py` RunContext — не дубль (R6-C-001). **Критерий:** тест переходов state machine; персистентность полного набора полей; run читается после рестарта процесса; kill-switch `SUMMARY_RUN_DURABLE_ENABLED` (default ON; OFF → runs не персистятся, workflow как сегодня; stage_events append-only семантика ADR-1028-7 D7.6 остаётся независимо). Якорь 22930–22966. DoD: 20. Зависимости: T-4601.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 5, сессия RECOVERY после 2 обрывов):** новый чистый модуль `services/summary_run_store.py` (state machine §20 — константы/VALID_TRANSITIONS/state_rank :47-108; publication_status :111-116; wrappers :139-289; TTL-purge гейт :277); DDL v24 additive — `summary_runs` + `summary_run_stages` + индексы (database.py `_SUMMARY_RUNS_DDL`/`_SUMMARY_RUN_STAGES_DDL`; `_migrate_summary_runs_v24`/`_migrate_summary_run_stages_v24` — `_migrate_*`-паттерн L-MCA14-3; runtime-записи через `write_transaction` — create :2843 / update_state :2866 / set_publication :2903 / record_stage :2990; readers — get_run :2940 / get_active_run_for_chat :2954 / list_stages :3026 / last_completed :3051 / purge :3072). Врезки в `summary_generator.py`: `_durable_run_create` :769 (сразу после SUMMARY_START), `_durable_mark` :779, `_durable_stage_result` :796, `_durable_run_finish` :809 (терминальный DONE/DEGRADED/FAILED + fail_publication + TTL-purge; finally _run :700); checkpoints: SOURCE_READY (`_establish_source_window` :741-753, window_from/to/source_ref), STRUCTURING :1855, STRUCTURE_READY :1890, WRITING :2067, TEXT_READY :1548/:2225, BASE_COVER :2637, STYLE_EDIT :2708; rank-guard — checkpoint не отматывается назад, терминальные не реанимируются (summary_run_store.py:149-177). Kill-switch `SUMMARY_RUN_DURABLE_ENABLED` (settings.py, env-only ClassVar default ON; OFF → 0 записей — тест). PG no-op (scan-тест). MCA-01: allowlist database.py 149→155 (6 новых commit — ТОЛЬКО в `_migrate_summary_runs_v24`/`_migrate_summary_run_stages_v24`, DDL-санкция L-MCA14-3; runtime — write_transaction). Тесты: tests/test_summary_run_store_asap41.py (19: DDL 3 таблицы v24/идемпотентность/PG no-op/state machine happy+DEGRADED-FAILED/полный набор полей/рестарт-читаемость/append-only scan/publication идемпотентность базис/kill-switch OFF/TTL-гейт терминальных/rank-guard/resume-ридер). Остаток (честно): per-попытка last_activity_at-тикер стадий — с Inspector-ридером зоны G (T-4621).
- [x] **T-4617 [@Builder]** — Resume after restart + no duplicate publication (§21): рестарт не начинает Summary заново; TaskJobStore восстанавливает джобу → читается `summary_runs` → последняя успешно завершённая стадия → продолжение с неё; SourceWindow/semantic map/writer draft берутся из durable-артефактов по run_id. **Идемпотентность публикации (ADR-1028-8 D6.2):** переход в PUBLISHING фиксируется в `summary_runs` ДО отправки; перед отправкой — проверка `publication_status` (не публиковать, если DONE/published) + существующая лестница R4-D-051 (sent unknown → reconcile → retry) + content-hash барьер `bot_output_ledger`; двойной финальный месседж невозможен. Учесть L-EXTRA-7 (стабильный `summary_run_id` как ключ resume). Cover-джоба продолжает работу из task_jobs с тем же run_id. **Критерий:** тест: рестарт в произвольной стадии → продолжение; fixture kill в PUBLISHING → рестарт → ровно одна публикация (DoD 21); kill-switch общий с T-4616. Якорь 22968–22977. DoD: 21. Зависимости: T-4616.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волны 5/6, сессия RECOVERY):** resume после рестарта — `_run` (summary_generator.py:509-591): незавершённый durable run чата (`get_active_summary_run_for_chat`, database.py:2954) ДОКАТЫВАЕТСЯ с тем же стабильным run_id (не пересоздание; лог `SUMMARY_RESUME`); окно докатываемого run'а — ТОЛЬКО из durable snapshot'а (`load_legacy_rows` по run_id; перечитка истории запрещена — окно дрейфует после compress_and_purge; snapshot недоступен → fail-open к свежей перечитке с честной отменой resume); write-once snapshot не пере-записывается (`resumed` в `_establish_source_window` :726). Идемпотентность публикации — единый gate `_publication_gate` :834, врезан во ВСЕ каналы доставки: plain `_publish_plain_document` :2450, rich `_publish_rich_document` :2754, rich-without-cover :2993; лестница: mark_publishing ДО send (published → «skip»; stuck publishing → reconcile) → reconcile ФАКТОМ `bot_output_ledger` по correlation_id run'а (R4-D-051: sent unknown → ledger-факт → skip + complete_publication(result_ref=bot_output:N)) → **content-hash барьер** (REUSE `bot_output_ledger.find_bot_output_by_text` — точное совпадение hash'а стабильного plain-рендера; cross-correlation доставка того же контента не дублируется; другой текст → retry-лег) → retry. Checkpoint published после успешной send — `_record_published_output` :2353-2395. Cover-джоба — task_jobs с тем же run_id (existing restart-resume, cover_style_jobs.py:1088-1093). Kill-switch общий с T-4616 (gate → None = байт-в-бит 2.58.46). Тесты (test_summary_cover_style_wave_f_asap41.py): kill ПОСЛЕ send → ledger-reconcile → ровно одна публикация (повторный заход skip); kill ДО send → retry-лег → одна отправка + checkpoint; published блокирует второй финал (rich→plain fallback); content-hash барьер skip + контрпример (другой текст → retry). Остаток (честно): stage-level skip (не пере-LLM'ить завершённые стадии по result_ref) требует persist'а map/draft-артефактов — текущий докат пере-прогоняет LLM-стадии по immutable snapshot с тем же run_id (дубликата публикации нет); полная стадийная докатка — отдельное решение (зона G/I).

## Блок G — Cover pipeline / Style (@Builder)

- [x] **T-4618 [@Builder]** — Разделение cover и text pipeline (§34): после TEXT_READY — Base Cover → Optional Style Edit → Publish; cover-ветка подписывается на approved text snapshot (`publication_result_ref`); text pipeline не регенерируется из-за cover failure; text-fallbacks не наследуются cover'ом (fallback-cover строится детерминированно из финального документа, existing `_derive_fallback_cover_prompt`); единый production Cover Pipeline для всех text outcomes (R4-B-003) сохраняется как регресс. **Критерий:** тест: cover/style failure не трогает text pipeline; регресс ladder R4-B-003 зелёный. Якорь 23271–23283. DoD: 22. Зависимости: T-4603.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 6, сессия RECOVERY):** durable checkpoints зоны F — TEXT_READY :1548/:2225 (approved text snapshot — после successful Writer/review, до cover-ветки), BASE_COVER :2637 (после успешной base generation), STYLE_EDIT :2708 (перед style edit'ом; ветка подписана на approved text — text pipeline не регенерируется, cover работает по run_style_job с cover_prompt); cover-ветка НЕ отматывает text-checkpoint — rank-guard (тест test_zone_f_checkpoints_state_machine_no_rewind_on_cover: повторный checkpoint TEXT_READY при докатке не сбрасывает STYLE_EDIT; stage-история append-only). Text-fallbacks не наследуются cover'ом: fallback-cover — детерминированная `_derive_fallback_cover_prompt` из финального документа (existing, summary_generator.py:2259/:3389 — без изменений). Регресс ladder R4-B-003 — существующие тесты зелёные (test_cover_style_wave_b_asap4.py: test_legacy_fallback_style_invoked_regression_39, test_provider_failure_base_fallback_visible_reason; test_extra_cover_style_pipeline). Kill-switch общий (E-зона/COVER_STYLES_ENABLED семантика прежняя).
- [x] **T-4619 [@Builder]** — Medved Press connection inheritance fix (§35; ADR-1028-8 D7.2): root-cause — `resolve_style_slot` резолвит глобальный слот из `models.image_style_base_url/model` (cover_style_pipeline.py:68-71); при профиле «По умолчанию (глобальная настройка)» пустой глобальный слот даёт `not_configured` → style edit не выполнен. **Фикс — лестница наследования:** 1) per-chat override (как есть) → 2) profile connection override (model_mode=custom, connection_id, как есть) → 3) global default image-edit slot: Connections layer default-подключение с image_edit, иначе `models.image_style_*` → 4) ничего не разрешилось → честный reason (не «успех без стиля»). Отдельная style connection НЕ обязательна. Событие `COVER_STYLE_RESOLVE` с источником резолва. Прод-инцидент («Не настроены адрес/модель обработки» → Style edit NOT EXECUTED → base cover) закрывается. **Критерий:** тест наследования «По умолчанию» → глобальный image-edit provider; регресс: явно настроенная style connection по-прежнему работает; kill-switch `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED` (default ON; OFF → текущий resolver, байт-в-бит). Якорь 23285–23314. DoD: 23. Зависимости: T-4601.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 6, сессия RECOVERY):** лестница наследования §35 — `resolve_style_slot_inherited` (cover_style_pipeline.py:210-266): шаги 1–2 байт-в-байт (`resolve_style_slot`) + leg 3a Connections layer default-подключение (`default_edit_connection` :170 — детерминированно: единственная/ранняя запись; capability image_edit через registry §36; FALSE блокирует лег, UNKNOWN не блокирует — `_capability_supports_edit` :190) → leg 3c global default image provider+model (`models.image_*` — тот же слот, что сгенерировал base cover; «Base cover: success» доказывает настроенность) → leg 4 честный not_configured. Событие `COVER_STYLE_RESOLVE` с `resolve_source` — эмитится ДО COVER_STYLE_START (cover_style_jobs.py:1177-1186; enum-набор 4 источников — SLOT_SOURCE_GLOBAL_STYLE/PROFILE_CONNECTION/CONNECTIONS_DEFAULT/GLOBAL_IMAGE :138-167). API-ключ наследованного global-image слота — `keys.image_api_key` (cover_style_jobs.py:1155-1166). Prod-инцидент закрывается: leg 3c тест = прод-сценарий Medved Press. Регресс: явный custom-профиль — байт-в-байт (test_explicit_style_connection_regression_byte_identical); настроенный глобальный style-слот — прежний контур (test_configured_global_slot_unchanged_25846). Kill-switch `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED` (settings.py, env-only default ON; OFF → ровно resolve_style_slot — тест test_kill_switch_off_resolver_byte_identical). Доводка RECOVERY: импорт slot-source-констант + restore `resolve_style_slot`-импорта в cover_style_jobs.py (обрыв сессии оставил NameError-ссылки).
- [x] **T-4620 [@Builder]** — Capability registry + fail-soft ladder (§36–§37): выбор обработчика стиля через **существующий capability registry** (`services/image_capabilities.py` + `ImageProviderAdapter` media_execution.py:308+): image_edit, reference_images, max_reference_images, prompt_limit if known, async/stream/sync mode; хардкоды NanoGPT/Qwen запрещены (инспекция T-4629); смена image provider → стиль работает или Inspector честно показывает «selected model does not support image_edit» (existing `check_edit_allowed` gate сохраняется). Fail-soft ladder: base fail → publish text without image; style fail → base cover; Rich fail → plain. Никакой cover/style failure не уничтожает текст. События `COVER_STYLE_RESOLVE` / `STYLE_EDIT_START/RESULT` с точной причиной (не generic `style_failed` — правило ADR-1028-7 D6.3). **Критерий:** тесты registry-выбора + смена provider → честный статус; тесты §46 (style → base; base → текст публикуется; Rich → Plain same ResponseDocument). Якорь 23316–23360. DoD: 24, 25, 26, 27. Зависимости: T-4619.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 6, сессия RECOVERY):** capabilities по ФИНАЛЬНОМУ (унаследованному) слоту через существующий capability registry (§36): `_edit_capabilities_for` (cover_style_pipeline.py:199 — `cap.resolve_capabilities_auto`, live-discovery+TTL-кеш, fail-open → conservative unknown) в legs 3a/3c + в `run_style_job` caps резолвятся по фактическому слоту (cover_style_jobs.py:1195-1202 — единый registry, никаких провайдер-хардкодов в ветке; аргументы registry = фактический слот — тест test_capabilities_resolved_by_final_inherited_slot); existing `check_edit_allowed` gate сохранён (edit_unsupported → base публикуется, cover_style_jobs.py:1204-1210). События: COVER_STYLE_RESOLVE (источник резолва) + STYLE_EDIT_START/RESULT с точными reason-кодами ladder (not_configured/edit_unsupported/reference_missing — не generic `style_failed`; R17-safe — test_cover_style_resolve_event_contract). Fail-soft ladder §37 — контракт без изменений, регресс зелёный: style fail → base cover (test_provider_failure_base_fallback_visible_reason — wave B); base fail → Rich без image/plain (`_degrade_without_cover` → `_publish_rich_without_cover` — existing); Rich fail → Plain same ResponseDocument (`_plain_fallback`, test_summary_asap21_rich_cut/test_summary_publish_integration_round1026 — existing). Тесты волны 6: test_summary_cover_style_wave_f_asap41.py (16). Остаток (честно): полные §46-ladder фикстуры 5-штук консолидируются в T-4627 (зона I, волна 7) поверх этих механизмов.
## Блок H — Run Inspector / observability (@Builder)

- [x] **T-4621 [@Builder]** — Честная coverage semantics в Inspector (§38): раздельно Источник 839/839 100% / Structurer-L1 (whole-window input + result: failed) / Writer input coverage / Final text source coverage; при overflow — segments 4/4 + messages covered 839/839. «839/839 Coverage 100%» рядом с L1 failure не показывается как единый успех. **Критерий:** fixture «L1 failed, source 100%» → раздельная витрина; данные из `summary_runs`/`summary_run_stages`/CoverageLedger, не из парсинга логов. Якорь 23362–23390. DoD: 28. Зависимости: T-4606, T-4616.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 7, сессия RECOVERY):** `_coverage_breakdown`
  (pipeline_analytics.py:654) — раздельные оси source/l1/writer/final/overflow
  из structured state (usage_json событий SUMMARY_SOURCE_WINDOW_READY /
  SUMMARY_L1_STAGE / SUMMARY_L2_STAGE / SUMMARY_SEGMENT_* + in-memory
  снапшот; НЕ парсинг логов — guard-скан-тест); врезка в `build_run_view`
  (:992 «coverage_breakdown»). Fixture-тест §38: L1 result=failed —
  ОТДЕЛЬНАЯ ось рядом с source 839/839·100% (test_l1_failed_source_full_
  are_separate_axes); overflow — segments 4/4 + covered 839/839 (test_
  overflow_segments_and_messages_covered); map_degraded — карточка из
  SUMMARY_L1_STAGE.counts (test_map_degraded_displayed_in_l1_axis).
  UI: computed `pipelineCoverageRows` (web/app.js:2930) + блок «Покрытие
  источника — по стадиям» (web/index.html:3123). Существующая first-class
  coverage-карточка (R4-E) не редактирована. Тесты:
  tests/test_summary_inspector_zone_g_asap41.py (26).
- [x] **T-4622 [@Builder]** — Inspector capacity + liveness (§39–§40): карточка «КОНТЕКСТ МОДЕЛИ» (Provider/Model/Effective window/Serialized input/Output reserve/Mode WHOLE_WINDOW|CAPACITY_OVERFLOW + человеческая причина) и liveness на каждой LLM stage (execution mode stream/async job/sync, last activity, provider fallback, reason); человекочитаемо, без машинной каши по умолчанию; декларации отражают фактическое состояние (не «stream ✓» при sync-транспорте). **Критерий:** обе карточки по перечню §39/§40; значения из structured state; **Browser-verification (spec, REQUIRED):** Playwright desktop 1280×800 + mobile 390×844, entry `/api/analytics/pipeline/inspector` + run detail, fixture-run через реальный mca-17a-транспорт на temp-SQLite (прод-БД не загрязняется), 0 новых JS-ошибок.   Якорь 23392–23436. DoD: 29. Зависимости: T-4604, T-4614, T-4621.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 7, сессия RECOVERY):** capacity-карточка
  `_capacity_card` (pipeline_analytics.py:345) — Provider/Model/Effective
  window/Serialized input/Output reserve/Mode (WHOLE_WINDOW |
  CAPACITY_OVERFLOW) + человеческая причина (REASONS_RU) + window_source
  по цепочке §5 + счётчик re-plan событий (каждый следующий
  SUMMARY_CAPACITY_RESOLVED = переоценка; test_replan_counter_counts_
  capacity_resolved); честная база: mode из фактической capacity-подписи
  события, «stream ✓» при sync-транспорте невозможен. Liveness `_liveness_
  cards` (:448) — на каждой LLM stage execution mode / last activity /
  provider fallback / reason; человекочитаемые статусы «жива/завершена/
  ждёт» (STAGE_HUMAN/MODE_HUMAN); stage-ключи l1/l2/l2_review/legacy.
  UI: computed `pipelineCapacityCard` (web/app.js:2995), `pipelineLiveness
  Rows` (:3022), карточки #pipeline-capacity-card/#pipeline-liveness-card
  (web/index.html:3137/:3152). Browser-verification (spec REQUIRED):
  Playwright tools/ui_asap41_zone_g_e2e.py — desktop 1280×800 + mobile
  390×844, fixture-run через РЕАЛЬНЫЙ mca-17a транспорт на temp-SQLite
  (прод-БД не загрязняется), failures: 0 в обоих viewport, 0 новых
  console/pageerror; скриншоты в evidence/. Тесты: TestCapacityCard +
  TestLivenessCard в tests/test_summary_inspector_zone_g_asap41.py.
- [x] **T-4623 [@Builder]** — Inspector cover style (§41): Base cover ✓ / Selected style / Style provider / Style model / Style capability image-edit ✓ / Reference assets / Style edit ✓-✕ / Published cover Styled-Base-None + точная причина fallback (DoD 30). **Критерий:** карточка по перечню §41 в существующей Analytics (не новый продукт, R4-E-002); browser-verification как в T-4622 (desktop + mobile). Якорь 23438–23453. DoD: 30. Зависимости: T-4620.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 7, сессия RECOVERY):** `_cover_style_
  card` (pipeline_analytics.py:556) — Base cover ✓/✕ (COVER_BASE_SUCCEEDED/
  FAILED), Selected style, Style provider/model, Style capability image-edit
  (edit_unsupported → ✕ — тест test_style_failure_precise_reason_not_
  generic), Reference assets (только при реальном подсчёте reference_count
  — честное отсутствие = отсутствие), Style edit ✓-✕, Published cover =
  styled | base_fallback | no_cover + ТОЧНАЯ причина fallback через
  _safe_reason_code (connection_missing/not_configured/edit_unsupported/
  capability_unknown/reference_missing — не generic style_failed, D6.3:
  test_reason_ru_for_fallback_cause_families); resolve_source лестницы §35
  (global_style/profile_connection/connections_default/global_image —
  реальные SLOT_SOURCE-идентификаторы, test_resolve_source_translation_
  ladder) + resolve_source_ru. UI: computed `pipelineCoverStyleCard`
  (web/app.js:3038) + карточка #pipeline-cover-style-card (web/index.html:
  3226). Browser-verification: тот же e2e (failures: 0, desktop+mobile;
  карточка рендерится, styled-результат виден). Тесты: TestCoverStyleCard.
- [x] **T-4624 [@Builder]** — Structured events + приватность (§42–§43): один run_id; аддитивное расширение `pipeline_events.py` — **существующие имена не переименовываются** (совместимость mca_events/Analytics); соответствие имён — spec §7.3: новые `SUMMARY_SOURCE_WINDOW_READY`, `SUMMARY_CAPACITY_RESOLVED`, `SUMMARY_EXECUTION_MODE_SELECTED`, `SUMMARY_L1_ACTIVITY`, `SUMMARY_WRITER_ACTIVITY`, `SUMMARY_REVISION_*`, `SUMMARY_TEXT_READY`, `COVER_STYLE_RESOLVE`, `SUMMARY_SEGMENT_PLAN/_RESULT/_LEDGER` (overflow); существующие `SUMMARY_RUN_START/L1_STAGE/L2_STAGE/L2_REVIEW/COVER_BASE_*/COVER_STYLE_*/PUBLISH_*/SUMMARY_RUN_DONE` — как есть. Append-only; fail-open эмиссия; вопрос «повысить L1_TIMEOUT» исчезает — **нового admin-ключа L1_TIMEOUT нет**, длительность управляется Supervisor'ом (T-4614) и whole-window архитектурой. R17: без API keys/полных сообщений/промптов/reference bytes; допустимы counts, token estimates, safe IDs, hashes, reason codes (только через `mca_events.py:REASON_CODES`), provider/model, latency, coverage. **Критерий:** полный перечень событий на fixture-run; overflow-run добавляет три; R17-скан чист. Якорь 23455–23529. DoD: 28–30 (эвитрибуция). Зависимости: T-4616.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 7, сессия RECOVERY):** один run_id
  сквозной (pipeline_run_id = trace_id = run_id на fixture-run'e;
  test_full_event_lamp_on_fixture_run). Аддитивное расширение
  pipeline_events: существующие имена НЕ переименованы (контрактный тест
  test_existing_event_names_not_renamed: EV_SUMMARY_START=SUMMARY_RUN_START,
  EV_L1_STAGE/L2_STAGE/L2_REVIEW/SUMMARY_DONE как есть); новые эмиттеры
  SUMMARY_TEXT_READY (pipeline_events.py:420) + SUMMARY_REVISION_RESULT
  (:429) врезаны в пайплайн (summary_generator.py:1571/:2255; summary_l2_
  review.py:908); SUMMARY_L1_ACTIVITY/SUMMARY_WRITER_ACTIVITY/
  SUMMARY_LLM_SUPERVISOR — волна 4; SUMMARY_SOURCE_WINDOW_READY/
  SUMMARY_CAPACITY_RESOLVED/SUMMARY_EXECUTION_MODE_SELECTED/SUMMARY_SEGMENT_
  PLAN/_RESULT/_LEDGER — волны 2/3; COVER_STYLE_RESOLVE — волна 6; все
  зарегистрированы в `_INSPECTOR_EVENTS` (pipeline_analytics.py:1307).
  Per-attempt last_activity тикер: durable `summary_run_stages` — append-
  only по попытке (retry = НОВАЯ строка с last_activity_at, database.py:
  2990-3019); ридер collect_run (:1366) подмешивает stage-строки в
  liveness (fail-open); живая стадия — из SUMMARY_*_ACTIVITY событий
  (test_running_stage_alive_ticker). map_degraded карточки — из
  SUMMARY_L1_STAGE.counts (test_map_degraded_displayed_in_l1_axis).
  «L1_TIMEOUT»-вопрос: нового admin-ключа нет — контрольная строка в
  settings не появлялась (F8 EXIT=0, реестр 488). R17-скан чист
  (test_r17_scan_no_text_or_keys: без api_key/sk-/bytes/текстов сообщений).
  Fail-open эмиссия сохранена; overflow-run добавляет РОВНО три сегментных
  (test_overflow_run_adds_three_segment_events).

## Блок I — тесты (@Builder)

- [x] **T-4625 [@Builder]** — Regression tests capacity/model switch A–E (§44): A large-context → WHOLE_WINDOW/L1 requests=1/coverage 100%; B small local 32k → CAPACITY_OVERFLOW/all covered/no truncation; C смена модели → cache invalidated + авто-смена strategy; D fallback на меньший контекст → re-plan, не oversized вслепую; E fallback на больший → допустим whole-window, если не ломает созданный run. **Критерий:** 5 автотестов с EXPECT-списками §44. DoD: 2–6. Зависимости: T-4605, T-4606.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 8):** консолидированный golden-file
  tests/test_summary_wave8_golden_asap41.py — 5 golden-сценариев §44/§9 + §31/§14:
  G1 839-window fits → WHOLE_WINDOW, РОВНО 1 L1-запрос, coverage 100%, run жив
  до публикации; G2 provider/model switch → ключ кеша сменился + авто re-plan
  (WHOLE_WINDOW → CAPACITY_OVERFLOW, каталог-фикстура), coverage 100%
  инвариант; G3 L1 fail → Writer от Full SourceWindow («structure source
  yourself»), запрет Legacy (§48 Run 1), L1_STAGE честно failed рядом с
  source 100%; G4 Legacy от snapshot (source_ref) → 1 запрос полный XML
  560 сообщений, hard-cap dead-path; G5 overflow с невосстановимыми
  сегментами → deterministic minimal maps, coverage 100% (не 0/N, не
  маскируем success). Реализовано по EXPECT-спискам §44 A–E; сценарии
  A/B/D/E дополнительно закреплены в tests/test_summary_capacity_asap41.py
  (волна 2) и supervisor-fallback решении (волна 4) — консолидация, не дубль.
- [x] **T-4626 [@Builder]** — Тесты liveness (§45): streaming long generation (несколько минут, tokens/events идут) не убивается wall-clock; async job `processing` несколько минут → polling + persisted state, no duplicate submit; stalled stream (нет activity > inactivity threshold) → cancel/fallback по capability; opaque sync → adaptive watchdog + finite fallback. **Критерий:** 4 автотеста §45. DoD: 14–16. Зависимости: T-4613, T-4614.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 8):** tests/test_summary_wave8_
  supervisor_runs_asap41.py — 6 full-run сценариев: F1 primary-fail→fallback
  (3 HTTP ≤ 4); F2 всё падает → finite финал при РОВНО 4 HTTP + честный
  retry_time_budget_exhausted (не misleading budget); F3 ПОЛНЫЙ run_l1 через
  supervisor-канал на реальном llm_client-транспорте (primary ×2 down +
  fallback → map, ≤4 HTTP, coverage 100%); F4 watchdog stall → cancel →
  finite fallback; F5 hard fuse последняя рубеж (execution_deadline_exceeded);
  F6 adaptive-оценщик: timeout/failure НЕ обучают дедлайн (только успешные
  длительности), 400s-образцы дают ≥600s дедлайн — длинная live-
  генерация не убивается wall-clock (§50-критерий). Mode A/B full-прогоны
  — контрактные слоты (PO-4 PENDING OWNER, честная база Mode C закреплена
  в волне 4).
- [x] **T-4627 [@Builder]** — Тесты fail-soft (§46): L1 total failure → Writer с full SourceWindow; Reviewer failure → usable draft не теряется (controlled fallback policy по spec ASAP-4 R4-D-029); base cover failure → Rich без image/plain; style failure → base cover; Rich publish failure → Plain same ResponseDocument. **Критерий:** 5 автотестов §46. DoD: 8, 25–27. Зависимости: T-4608, T-4618, T-4620.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 8):** tests/test_summary_wave8_
  ladder_matrix_asap41.py — единая матрица 5 §46-веток (M1 L1 fail /
  M2 L2 unusable / M3 style fail / M4 base fail / M5 Rich fail), каждая
  с честной тройкой «публикуется / coverage / health»: M1 published +
  Writer-вход 100% + L1_STAGE failed честный; M2 usable исход не потерян
  (LEVEL-3 Legacy) + health degraded (§50.53); M3 base cover публикуется
  после style-fail (REASON_STYLE_FAILED на единственном generator-шве
  _maybe_apply_cover_style — jobs-уровень закреплён волной 6) + health ok;
  M4 Rich без image (media=[]) / plain + cover_status unavailable + health
  ok; M5 plain содержит ТОТ ЖЕ ResponseDocument (title + все абзацы,
  вербатим) + channel text. Без внешних вызовов; durable OFF для
  детерминизма (идемпотентность — fixture зоны E/T-4617).
- [x] **T-4628 [@Builder]** — Тесты attribution против SourceWindow (§47): Writer/Reviewer используют оригинал; сценарии: два похожих имени, reply chain, forwarded message, цитата, шутка vs факт, числа, даты, конфликтующие реплики. **Критерий:** 8 fixture-сценариев §47. DoD: 9, 10. Зависимости: T-4609, T-4610.
  **ВЫПОЛНЕН 03.10.2026 (Builder, волна 8; Orchestrator-директива Wave-8
  определила T-4628 = OFF-parity матрице, обе задачи закрыты):**
  (1) §47-матрица — 8 параметризованных сценариев (similar_names /
  reply_chain / forwarded / quote / joke_vs_fact / numbers / dates /
  conflicting_replicas) в tests/test_summary_wave8_golden_asap41.py:
  Writer И Reviewer получают полный оригинальный SourceWindow (текст
  вербатим у обоих, автор/id/reply/forward-поля сериализованы), никакого
  среза; LLM-качество атрибуции — прод-приёмка §48 Run 1 (механизм
  неделим). R6-B-007 wrong-speaker-фикстура закреплена волной 3
  (test_wrong_speaker_catch_from_source_window). (2) OFF-parity —
  tests/test_summary_wave8_off_parity_asap41.py: ВСЕ 9 kill-switches
  §11.1 комбинированно OFF на одном реальном прогоне с temp-SQLite →
  бит-в-бит 2.58.46 (durable-таблиц v24 runtime ноль записей, capacity-
  snapshot нет, L1 §95-v2 контракт, Writer FactPackage-центричный вход,
  без supervised_transport, legacy-капы trim 560→≤500, style-резолвер
  байт-в-байт resolve_style_slot) + поимённый prod-дефолт ON + never-
  raises per-call резолвы + zone-A точечная проверка (store не вызывается
  из единственной точки при OFF).

## Блок J — release / приёмка / закрытие

- [ ] **T-4629 [@Reviewer]** — Gate ASAP 4.1. Линзы: (1) «механизм против заглушки» — нет фиктивных coverage/watchdog/supervisor-симуляций; (2) OFF-паритет всех 9 kill-switches поимённо (spec §11.1: `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED`, `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED`, `SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED`, `SUMMARY_L1_SEMANTIC_MAP_ENABLED`, `SUMMARY_WRITER_SOURCE_INPUT_ENABLED`, `SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED`, `SUMMARY_LLM_SUPERVISOR_ENABLED`, `SUMMARY_RUN_DURABLE_ENABLED`, `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED`) — бит-в-бит 2.58.46 каждой зоны; (3) AM-1…AM-6 выполнены по ADR-1028-8 (register #1–#8); no-false-quality R4-D-064 (§0-директива) и R17; attempt-ceiling ≤4 HTTP закреплён тестом (T-4612); отсутствие второго resolver/pipeline/реестра и хардкодов NanoGPT/Qwen; (4) контроль разрастания — «бесконечный redesign» признак (22361). **Критерий:** Approved, release-blocking 0. DoD: —. Зависимости: T-4625–T-4628 (тестовые волны) + все Builder-блоки.
- [ ] **T-4630 [@DevOps]** — Deploy. Полный pytest 0 регрессий (known pre-existing отдельно), bump APP_VERSION, прод-деплой (ff-only), **бэкап SQLite до DDL v23→v24 (3 таблицы: summary_source_windows, summary_runs, summary_run_stages; additive; повторный прогон — no-op) по fail-closed guard'у; PostgreSQL no-op проверен**; post-гейты: health 200, версия, миграции/ΔDDL-режим, kill-switches default-ON, R17-скан. **Критерий:** deploy VERIFIED + evidence. DoD: 33. Зависимости: T-4629.
- [ ] **T-4631 [@DevOps+Owner]** — **[PENDING OWNER]** Production acceptance Run 1 (§48): текущая large-context модель, большое реальное окно (владелец, до 839+ сообщений; платные live-вызовы LLM — бюджет владельца): WHOLE_WINDOW, source=100%, L1 one whole-window attempt, Writer/Reviewer full source access; при падении L1 — Writer завершает Summary **без перехода на урезанный Legacy**. DevOps-часть (подготовка чек-листа, evidence-сбор, fixture-аналог на temp-SQLite) — в скоупе команды. **Критерий:** acceptance-чеклист §48 Run 1 с прод-evidence, no-false-acceptance. DoD: 31. Зависимости: T-4630.
- [ ] **T-4632 [@DevOps+Owner]** — **[PENDING OWNER]** Production acceptance Run 2 (§48): controlled lower-capacity configuration (конфиг-фикстура модели с меньшим окном; живой прод): CAPACITY_OVERFLOW, 100% coverage; после теста вернуть production model config (подтверждение владельца). **Критерий:** чек-лист §48 Run 2; конфиг возвращён. DoD: 32. Зависимости: T-4630.
- [ ] **T-4633 [@DevOps+Owner]** — **[PENDING OWNER]** Medved Press production acceptance (§49): Selected Style = Medved Press, Base Cover ✓, image-edit provider/model resolved ✓, reference asset loaded ✓, Style Edit ✓, Published Cover = Styled; при недоступности provider — зафиксировать provider error + доказать правильное resolution и fallback Base cover (живые платные вызовы image-провайдера — владелец). **Критерий:** чек-лист §49 на проде. DoD: 23–25 (прод-подтверждение). Зависимости: T-4630.
- [ ] **T-4634 [@Builder]** — Performance acceptance (§50): фактические замеры против базиса «до: L1 ~622s / L2 ~155s / total ~1331s»; показать time to first activity, active generation duration, wait/queue, fallback count, total run duration; **искусственный SLA не ставится**; главные критерии (живой длинный запрос не убивается; зависший не держит pipeline бесконечно) — по результатам T-4626; прод-замеры — по прогонам владельца из T-4631/T-4632 (PENDING OWNER-часть). **Критерий:** замер-отчёт с реальными цифрами, без выдуманного SLA. DoD: — (evidence для отчёта). Зависимости: T-4631/T-4632.
- [ ] **T-4635 [@PM+Memory]** — Человеческий отчёт владельцу (DoD 34): что было сломано, что изменено, чем подтверждено — человеческим языком; метрики-строка для Orchestrator (start/end, Reviewer rounds, rework, findings обеих линз, evidence-ссылки). **Критерий:** отчёт доставлен; DoD 34. Зависимости: T-4631–T-4634.
- [ ] **T-4636 [@PM+Memory+Orchestrator]** — Финальное закрытие (DoD 35): DoD-чеклист 35/35; фиксация SHA-256 якорей 22345–23844 (append-only проверка `current_task.md`); финальная строка §52 («ASAP 4.1 production acceptance complete; … Resume MCA workflow»); Orchestrator выполняет checkpoint `delivery → reconcile → archive → select_next` → возврат к очереди MCA из `current_task.md`. **Критерий:** DoD 35/35; возврат к MCA зафиксирован. Зависимости: T-4635.

---

## PENDING OWNER — owner-гейты вне скоупа команды

Живое исполнение на проде требует ресурсов и бюджета владельца; без этих прогонов feature не завершается (DoD 31/32/23–25), но они не блокируют Builder/Reviewer/деплой-работы команды:

| # | Гейт | Задача | Что нужно от владельца |
|---|---|---|---|
| PO-1 | §48 Run 1 — большой реальный прогон (839+ сообщений, large-context модель) | T-4631 | Инициация прогона на живом чате; платные live-вызовы LLM |
| PO-2 | §48 Run 2 — controlled lower-capacity прогон + возврат production model config | T-4632 | Подтверждение запуска/возврата конфигурации |
| PO-3 | §49 Medved Press — живой image-edit прогон | T-4633 | Платные вызовы image-провайдера, reference asset |
| PO-4 | Live-верификация Mode A/B провайдеров (async job/streaming) | T-4613 | Платные прогоны; без них A/B остаются контрактными слотами (честная база — Mode C) |
| PO-5 | §50 прод-замеры (базис 622/155/1331) | T-4634 | Наблюдения по прогонам PO-1/PO-2 |

## Порядок исполнения (волны)

```
Волна 1  Архитектура:      T-4601 → T-4602
Волна 2  Source/Capacity:  T-4603 → T-4604 → T-4605 ┐
                           T-4603 → T-4606 ──────────┤ (после T-4604)
Волна 3  L1/W/R/Legacy:    T-4607 → T-4608; T-4609 → T-4610; T-4611   (после T-4603; T-4607 после T-4606)
Волна 4  Supervisor:       T-4612 → T-4613 → T-4614 → T-4615
Волна 5  Durability:       T-4616 → T-4617
Волна 6  Cover/Style:      T-4618; T-4619 → T-4620
Волна 7  Inspector:        T-4621 → T-4622; T-4623; T-4624
Волна 8  Тесты:            T-4625; T-4626; T-4627; T-4628   (после своих зон)
Волна 9  Release:          T-4629 → T-4630 → {T-4631, T-4632, T-4633 [PENDING OWNER]} → T-4634 → T-4635 → T-4636
```

- **Волны 3–7 частично параллельны** (волны 2/4 — первичные; 5/6/7 зависят только от T-4601/T-4603/4604 и своих прямых предков).
- **Жёсткие зависимости:** spec+ADR (T-4601, закрыт) до всех Builder-волн; SourceWindow (T-4603) до всего пайплайна; Supervisor (волна 4) до liveness-тестов; SummaryRun (волна 5) до Inspector coverage/events; Reviewer gate (T-4629) до деплоя (T-4630); acceptance-волны после деплоя [PENDING OWNER]; отчёт (T-4635) и финал (T-4636) — последние.
- **Предпосылка старта Builder-волн:** пост-ASAP-4 corrective pass закрыт (T-4508–T-4510: deploy + прод-приёмка) — директива владельца 22351–22359. Волна 1 (docs @Architect) стартовала и закрыта.

## Риски

| Риск | Уровень | Митигация |
|---|---|---|
| AM-1: whole-window L1 возвращает `too_many_facts`-класс invalid → рождение нового fallback | High | **Решено ADR-1028-8 D3:** semantic map v1 (карта без source payload, класс `too_many_facts` невозможен по построению); тест T-4607 на плотном fixture; kill-switch OFF=бит-в-бит |
| Supervisor меняет тайминги для прочих потребителей llm_client (Direct/STT/image) | High | **Решено ADR-1028-8 D5:** scope = Summary only, per-call контракт сохранён для остальных; инспекция в T-4629; transport-слои не дублируют retry |
| Durable SummaryRun наследует L-EXTRA-6/L-EXTRA-7 (payload-колонка, нестабильный run-id) | Medium | **Решено ADR-1028-8 D6:** dedicated таблицы `summary_runs`/`summary_run_stages`, не task_jobs payload; стабильный run_id; регресс-тесты T-4617 на рестарт/идемпотентность |
| AM-4 prompt-миграция Writer/Reviewer ломает качество ASAP-4 | Medium | Явная миграция (T-4607/T-4609) + регресс R4-D-003/R4-D-024 в T-4610; приёмка prose-quality — в рамках production acceptance §48/§50 |
| Fallback-пере-план (R6-D-006) конфликтует с уже созданными стадиями run'а | Medium | Тест §44-E «не ломает уже созданный run»; решение в T-4605 (переход на whole-window только до создания сегментных артефактов) |
| Возврат production model config после Run 2 забыт | Low | Чек-лист T-4632 включает пункт «конфиг возвращён» (подтверждение владельца) |
| Разрастание scope (анти-паттерн «бесконечный redesign») | Medium | Scope = §0–§52; T-4629 проверяет отсутствие внепроектных доработок |
| Owner-гейты (PENDING OWNER) блокируют финализацию DoD 31/32/23–25 | Medium | Команда закрывает Builder/Reviewer/деплой независимо; прод-прогоны — по готовности владельца; без них archive не выполняется |

## PLANNING_CONSISTENT: yes (docs-only, Step 3, 03.10.2026)

**Основание (проверено по файлам):**
1. **Треугольник requirements-map ↔ spec ↔ tasks согласован:** 52 критерия R6-xxx (A:10, B:9, C:2, D:9, E:3, F:4, G:6, H:9) покрывают §0–§52 без orphan'ов; каждая Builder-задача ссылается на ≥1 R6-ID; DoD 35/35 маппированы на задачи. Исправлены устаревшие ссылки в requirements-map (R6-A-007 → T-4604/T-4605; R6-H-005 → T-4631/T-4632; R6-H-006 → T-4633; R6-H-007 → T-4634; DoD 34 → T-4635).
2. **Матрица spec→tasks (§13) полна в обе стороны:** нет задач вне спека, нет разделов спека без задач; ARCH-задачи T-4601/T-4602 закрыты (spec+ADR-1028-8, register #1–#8).
3. **Решения Architect'а вшиты в критерии:** DDL v24 — 3 таблицы (`summary_source_windows` T-4603; `summary_runs`+`summary_run_stages` T-4616; PG no-op); 9 kill-switches поимённо в своих зонах; semantic map v1 контракт (T-4607); Supervisor modes A/B/C + attempt-ceiling ≤4 HTTP + честная база Mode C (T-4612/T-4613); CoverageLedger с XOR-инвариантом (T-4606); идемпотентность публикации — PUBLISHING-фикс + publication_status + R4-D-051 + bot_output_ledger (T-4617); Inspector-карточки с browser-verification (T-4621–T-4624).
4. **Риск R3 подтверждён обеими сторонами** (spec.md, риск-таблица задач); rollback: kill-switches env-only OFF=бит-в-бит + cold revert; additive DDL v24 совместима со старым кодом (spec §11.2).
5. **Owner-гейты выделены в блок PENDING OWNER** (PO-1…PO-5): живые платные приёмки §48/§49, реальные 839-оконные прогоны, Mode A/B live-верификация — вне скоупа команды, не блокируют Builder/Reviewer/деплой, блокируют финализацию DoD/archive.
6. **GAP-лист спека: пуст.** Дыр в spec/ADR, требующих возврата Architect'у, не обнаружено: все §0–§52 имеют контракты и задачи; открытых вопросов PM→Architect из Step 1 (AM-1…AM-6) все разрешены регистром ADR-1028-8.

**Оговорки:** (а) Builder стартует после закрытия пост-ASAP-4 corrective pass (T-4508–T-4510) — AM-6; (б) archive/DoD-финал невозможен до owner-прогонов PO-1…PO-3 — это known-blocker, не расхождение планирования; (в) verbatim-снимок источника и SHA-256 якорей — за Orchestrator'ом/T-4636.

## Пост-gate фикс [M-ASAP41-1] (Builder, 03.10.2026, doc-only)

Точечный фикс единственного блокера финального gate T-4629
(review.md Blocking findings [M-ASAP41-1], Medium doc-only). Строку
судьбы spec §8.1 «Описание в каталоге дополняется пометкой „не управляет
Summary"» никто из волн не выполнил (T-4602-зона закрылась таблицей
спеки — actionable-часть выпала) — выполняет этот фикс. Коммита нет
(R18-режим; WTH подлежит пересчёту Orchestrator'ом).

**Сделано (doc-only, поведение не тронуто):**
- `services/param_catalog.py` (:735-736 / :745-746 — якоря совпадают
  с review.md): пометка «Не управляет фоновым Саммари (Summary) —
  длительность Саммари определяет супервизор исполнения» у LLM_TIMEOUT
  и LLM_TOTAL_BUDGET;
- `tests/test_summary_param_catalog_annotation_asap41.py` (NEW, 5
  тестов): маркер у обоих ключей + охват «ровно 2 ключа» + doc-only
  инварианты;
- F8 полный свип (`gen_param_registry_round1025.py` без --check):
  TSV/meta перегенерированы, содержательный дифф = ровно 2 строки,
  счётчики 488/105/103/21/77 без изменений; F8 --check EXIT=0;
- `tests/fixtures/round1025/f8_baseline.json`: осознанное обновление
  sha256(param_catalog.py) + запись в superseded_by (прецедент
  round1026/ASAP-2.1/extra-cover; app_version остаётся 2.58.15).

**Результаты:** целевые 68 passed (annotation + f8_registry +
param_catalog), settings_helpers 48 passed, py_compile EXIT=0,
F8 --check EXIT=0. Полный pytest осознанно не перезапускался (директива
— точечный тест; вердикт review.md: «полная ре-аудит-волна не
требуется»). Детали: evidence.md, секция «Пост-gate фикс
[M-ASAP41-1]».
